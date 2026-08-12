"""Python engine service — the single in-process system.

Runs the full build pipeline (interpret → search → rank → resolve → reconcile
→ conflict → download → instance → test → repair → export) on real provider
data and exposes the same API surface the PyQt UI expects, so the desktop app
no longer needs the Node server. All events go through EVENT_BUS (persisted to
each build's logs/events.jsonl).
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import traceback
import urllib.parse
from pathlib import Path

from .core import (EVENT_BUS, BuildLogger, builds_dir, mkdirp, new_build_id,
                   read_json_file, write_json_file, sanitize_filename,
                   format_bytes, uid)
from .providers.settings import SettingsStore
from .providers.registry import build_providers
from .providers.curseforge import cf_download_headers
from .interpreter import interpret
from .features import FEATURES, PACK_SIZE_MOD_COUNTS
from .rank import rank_candidate
from .solver import resolve_pack
from .reconcile import reconcile_jar_dependencies, norm_id as _norm
from .conflict import detect_and_resolve_conflicts, match_crash_signature
from .downloads import download_pack_files
from .exports import export_mrpack, export_curseforge, export_server_pack
from .instance import (create_instance_dir, install_mod_jars,
                       install_resource_packs, install_shader_packs,
                       write_pack_readme, write_game_file)
from .tester import run_test_level

# A provider can answer 200 with an empty result set during a momentary
# catalog/network blip. Bounded retries with backoff recover those in the
# build pipeline (AI Builder + Ask-AI feature search) without stalling a
# genuinely empty search forever. Mirrors the Discover view's retry policy.
RETRY_EMPTY_ATTEMPTS = 3
RETRY_BACKOFF_MS = 500
from .launcher import (launch_pack, stop_pack, play_state, is_running,
                       current_play, read_pid, any_running, running_pids,
                       collect_launch_evidence, _read_pid_raw, _error_stage)
from .repair import (parse_crash_report, missing_dep_ids, attribute_crash,
                     version_conflicts, missing_requesters, expected_ranges,
                     fatal_startup_detected, main_menu_reached)
from .hardware import detect_hardware, fit_xmx_mb, performance_estimate
from .shaders import pick_shader_preset, choose_shader, rendering_mod_for
from .resource_packs import pick_resource_pack, choose_resource_pack
from .compat import CompatibilityDatabase
from .identity import derive_identity, apply_intents
from .snapshots import (create_snapshot, list_snapshots, load_snapshot,
                        last_known_good as _lkg_snapshot, mark_last_known_good,
                        restore_from_snapshot)
from .plan import plan_change
from .health import pack_health
from .jarmeta import essential_libraries, norm_id
from .jarname import invalid_module_reason, find_invalid_module_jar

_INDEX_LOCK = threading.RLock()


def _without_secrets(value):
    """Return a record-safe copy; provider credentials never belong in evidence."""
    if isinstance(value, dict):
        return {k: ("" if k.casefold() in {"curseforgeapikey", "cf_api_key"} else _without_secrets(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [_without_secrets(v) for v in value]
    return value

# ---------------------------------------------------------------------------
# Build record helpers
# ---------------------------------------------------------------------------

def _summary_record(rec: dict) -> dict:
    req = rec.get("requirements") or {}
    ps = rec.get("packStats") or {}
    return {
        "buildId": rec.get("buildId"), "name": rec.get("name"),
        "request": rec.get("request"), "status": rec.get("status"),
        "phase": rec.get("phase"), "error": rec.get("error"),
        "minecraftVersion": req.get("minecraftVersion"),
        "loader": req.get("loader"),
        "modCount": ps.get("modCount", 0),
        "createdAt": rec.get("createdAt"), "updatedAt": rec.get("updatedAt"),
        "testStatus": (rec.get("testResult") or {}).get("status"),
        "running": rec.get("running", False),
        "loaderVersion": rec.get("loaderVersion"),
        "launchPhase": rec.get("launchPhase"),
        "launchError": rec.get("launchError"),
        "failure": rec.get("failure"),
    }


class PyEngine:
    """In-process engine. Thread-safe for reads; builds run on worker threads."""

    def __init__(self, settings_store=None):
        self.settings_store = settings_store or SettingsStore()
        self.memory = CompatibilityDatabase()
        self._hardware = None
        self._build_threads: dict = {}
        self._events_subs = []
        self._log_tails: dict = {}
        self._providers: list | None = None
        self._providers_stamp: float = 0.0
        self._scrub_existing_records()

    def _scrub_existing_records(self) -> None:
        """One-time, idempotent migration for records written by older builds."""
        root = builds_dir()
        for path in root.glob("*/build.json") if root.exists() else []:
            rec = read_json_file(path)
            if isinstance(rec, dict):
                clean = _without_secrets(rec)
                if clean != rec:
                    write_json_file(path, clean)
        idx_path = root / "index.json"
        idx = read_json_file(idx_path)
        if idx is not None:
            clean = _without_secrets(idx)
            if clean != idx:
                write_json_file(idx_path, clean)

    # ------------------------------------------------------------------
    # health / settings / hardware
    # ------------------------------------------------------------------

    def _cached_providers(self, sources=None, opts=None):
        """Providers reused across searches — rebuilt only when settings change.

        build_providers() re-reads + merges the settings JSON from disk on
        every call; a browse session fires many searches, so we cache the list
        keyed on the settings file's mtime (fast path: no disk read). The
        browser's default is BOTH catalogs (Modrinth + CurseForge) — the
        build pipeline still passes its own sources where it needs them.
        """
        stamp = self.settings_store.mtime()
        if sources is None and opts is None and self._providers is not None \
                and stamp == self._providers_stamp:
            return self._providers
        provs = build_providers(self.settings_store,
                                sources=sources if sources is not None else ["modrinth", "curseforge"],
                                opts=opts)
        if sources is None and opts is None:
            self._providers = provs
            self._providers_stamp = stamp
        return provs
    def health(self) -> dict:
        return {"ok": True, "now": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}

    def settings_get(self) -> dict:
        settings = self.settings_store.load()
        resolved = self.settings_store.curseforge_key()
        out = {**settings}
        out["curseforgeApiKey"] = "••••••••" if resolved else ""
        out["curseforgeKeyConfigured"] = bool(resolved)
        out["curseforgeKeySource"] = self.settings_store.curseforge_key_source()
        return out

    def settings_post(self, patch: dict) -> dict:
        current = self.settings_store.load()
        clear_curseforge_key = (
            "curseforgeApiKey" in patch
            and str(patch.get("curseforgeApiKey") or "") == ""
        )

        def merge(target, update):
            for k, v in update.items():
                if isinstance(v, dict) and isinstance(target.get(k), dict):
                    merge(target[k], v)
                else:
                    target[k] = v

        merge(current, patch)
        if patch.get("curseforgeApiKey") in ("••••••••",) or "•" in str(patch.get("curseforgeApiKey") or ""):
            current["curseforgeApiKey"] = current.get("curseforgeApiKey")
        if isinstance(patch.get("build"), dict):
            current.setdefault("build", {})["budgetPinned"] = True
        if clear_curseforge_key:
            self.settings_store.clear_curseforge_key()
        self.settings_store.save(current)
        self._providers = None
        return {"ok": True,
                "keyConfigured": bool(self.settings_store.curseforge_key()),
                "keySource": self.settings_store.curseforge_key_source()}

    def hardware(self) -> dict:
        if self._hardware is None:
            self._hardware = self._detect()
        return self._hardware

    def hardware_refresh(self) -> dict:
        self._hardware = self._detect(force=True)
        return self._hardware

    def _detect(self, force: bool = False) -> dict:
        det = detect_hardware(force)
        s = self.settings_store.load()
        p = s.get("performance") or {}
        eff = {
            "cpu": p.get("cpu") if p.get("cpu") and p["cpu"] != "auto" else det["cpu"],
            "gpu": p.get("gpu") if p.get("gpu") and p["gpu"] != "auto" else det["gpu"],
            "ramGB": int(p.get("ramGB") or 0) or det["ramGB"],
            "os": p.get("os") if p.get("os") and p["os"] != "auto" else det["os"],
            "targetFps": p.get("targetFps") or 60,
            "resolution": p.get("resolution") or "1920x1080",
        }
        return {"detected": det, "effective": eff}

    # ------------------------------------------------------------------
    # builds listing / detail
    # ------------------------------------------------------------------
    def _build_dir(self, build_id: str) -> Path:
        return builds_dir() / build_id

    def _read_record(self, build_id: str) -> dict | None:
        return read_json_file(self._build_dir(build_id) / "build.json")

    def _write_record(self, rec: dict) -> None:
        rec = _without_secrets(rec)
        write_json_file(self._build_dir(rec["buildId"]) / "build.json", rec)
        # refresh the index
        idx_path = builds_dir() / "index.json"
        with _INDEX_LOCK:
            idx = read_json_file(idx_path) or []
            if not isinstance(idx, list):
                idx = []
            idx = [r for r in idx if r.get("buildId") != rec["buildId"]]
            idx.insert(0, _summary_record(rec))
            write_json_file(idx_path, idx[:200])

    def builds(self) -> list:
        idx = read_json_file(builds_dir() / "index.json") or []
        if not isinstance(idx, list):
            idx = []
        out = []
        for s in idx[:100]:
            rec = self._read_record(s.get("buildId", "")) or {}
            merged = {**s, **(rec or {})}
            merged["running"] = is_running(s.get("buildId", ""))
            out.append(_summary_record(merged) if rec else s)
        return out

    def _attach_identity(self, rec: dict) -> dict:
        """Attach PackIdentity + per-mod intents to a record on read (no disk write)."""
        rec = dict(rec)
        req = rec.get("requirements") or {}
        if not rec.get("identity"):
            rec["identity"] = derive_identity(req, rec)
        rec["selections"] = apply_intents(rec.get("selections") or [], rec.get("identity"))
        return rec

    def build(self, build_id: str) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec = self._attach_identity(rec)
        rec["running"] = is_running(build_id)
        st = play_state(build_id, str(self._build_dir(build_id)))
        if st:
            rec["launchState"] = st
            rec["launchPhase"] = st.get("phase")
            rec["launchError"] = st.get("error")
        return rec

    def files(self, build_id: str) -> list:
        rec = self._read_record(build_id) or {}
        out = []
        for d in rec.get("downloads") or []:
            out.append({
                "filename": d.get("filename"), "size": d.get("sizeBytes") or 0,
                "status": d.get("status"), "error": d.get("error"),
                "slug": d.get("key", "").split(":")[-1],
            })
        for e in rec.get("exports") or []:
            out.append({"filename": Path(e["path"]).name, "size": e.get("sizeBytes") or 0,
                        "status": "ok", "kind": e.get("kind"), "export": True})
        return out

    def log(self, build_id: str, name: str) -> str:
        p = self._build_dir(build_id) / "logs" / sanitize_filename(name)
        try:
            return p.read_text("utf-8", "replace")
        except OSError:
            return ""

    def evidence(self, build_id: str, name: str) -> str:
        rec = self._read_record(build_id) or {}
        for ph in (rec.get("testResult") or {}).get("phases") or []:
            if ph.get("name") == name:
                return ph.get("evidence") or ph.get("detail") or ""
        return ""

    def worlds(self, build_id: str) -> list:
        gd = self._build_dir(build_id) / "instance" / "minecraft" / "saves"
        out = []
        try:
            for d in gd.iterdir():
                if d.is_dir():
                    out.append({"name": d.name, "path": str(d)})
        except OSError:
            pass
        return out

    def export_file(self, build_id: str, filename: str, dest: str) -> int:
        rec = self._read_record(build_id) or {}
        src = None
        for e in rec.get("exports") or []:
            if Path(e["path"]).name == filename:
                src = Path(e["path"])
                break
        if not src or not src.exists():
            raise KeyError("export not found")
        shutil.copyfile(src, dest)
        return src.stat().st_size

    # ------------------------------------------------------------------
    # pack creation / edits
    # ------------------------------------------------------------------
    def create_pack(self, name: str = "", mc: str = "auto", loader: str = "auto",
                    ram_gb: int = 8) -> dict:
        # Resolve "auto" to concrete values up-front so every later consumer
        # (add_mod version picking, launches, exports) sees a real MC/loader
        # instead of the literal string "auto" (regression: blank packs with
        # auto MC got "No auto/fabric version for AppleSkin" when adding mods).
        settings = self.settings_store.load()
        defaults = settings.get("defaults") or {}
        if mc == "auto":
            d = defaults.get("minecraftVersion")
            mc = d if d and d != "auto" else "1.20.1"
        if loader == "auto":
            d = defaults.get("loader")
            loader = d if d and d != "auto" else "fabric"
        build_id = new_build_id()
        rec = {
            "buildId": build_id, "name": name or "Untitled Pack",
            "request": "", "status": "done", "phase": "done",
            "requirements": {"minecraftVersion": mc, "loader": loader,
                             "ramGB": ram_gb, "packSize": "medium",
                             "features": [], "theme": [], "notes": [],
                             "testMode": "standard"},
            "selections": [], "downloads": [], "graph": {"nodes": {}, "edges": []},
            "tests": [], "testResult": None, "conflicts": [], "repairs": [],
            "exports": [], "packStats": {"modCount": 0}, "settings": self.settings_store.load(),
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        mkdirp(self._build_dir(build_id))
        # Pre-create the instance skeleton so the pack is a real, launchable
        # instance from birth: the Mod Browser drops jars into mods/, the
        # launcher expects these paths on first Play, and the UI can offer
        # "open instance folder" without a first-add/download round trip.
        inst = self._build_dir(build_id) / "instance" / "minecraft"
        for sub in ("mods", "config", "resourcepacks", "shaderpacks", "saves"):
            mkdirp(inst / sub)
        self._write_record(rec)
        return rec

    def rename(self, build_id: str, name: str) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec["name"] = name
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True}

    def set_ram(self, build_id: str, ram_gb: int) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec.setdefault("requirements", {})["ramGB"] = int(ram_gb)
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True}

    def set_auto_relaunch(self, build_id: str, enabled: bool) -> dict:
        """Opt-in per-pack toggle: silently-dying games relaunch once with a
        lower fitted heap instead of leaving a dead session."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec.setdefault("settings", {})["autoRelaunch"] = bool(enabled)
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True, "autoRelaunch": bool(enabled)}

    def set_shader_preset(self, build_id: str, preset: str) -> dict:
        """Swap the pack's shader to a different preset (performance /
        balanced / cinematic) and re-validate compatibility.

        Re-runs the visuals step for the shader only: re-picks a real shader
        pack for the requested preset on this machine, downloads it, replaces
        the old shader selection in the record, installs the new zip into the
        instance's shaderpacks/ (removing the old one), then kicks off a
        real retest so the swap is validated, not just recorded.
        """
        if preset not in ("performance", "balanced", "cinematic"):
            raise ValueError(f"unknown shader preset: {preset}")
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        req = rec.get("requirements") or {}
        if not req.get("minecraftVersion") or not req.get("loader"):
            raise RuntimeError("pack has no concrete Minecraft version/loader yet")
        logger = BuildLogger(build_id, self._build_dir(build_id))
        req["shaders"] = True
        req["shaderQuality"] = preset

        # Build providers exactly as the pipeline does (no direct CF bundling
        # in builds — a CF shader would record a manifest reference, not a jar).
        sources = (rec.get("settings") or {}).get("build", {}).get("sources") or ["modrinth"]
        providers = build_providers(self.settings_store, sources)
        available = [p for p in providers if p.available]
        if not available:
            raise RuntimeError("No providers available. Add a CurseForge API key or restore Modrinth access.")

        preset_info = pick_shader_preset(req, self.hardware(), requested=preset)
        sh = choose_shader(available, req["minecraftVersion"], preset_info["preset"], logger)
        if not sh:
            raise RuntimeError(
                f"No {preset_info['preset']}-preset shader pack found for MC "
                f"{req['minecraftVersion']}. Try another preset.")

        # Download the new shader file into the build's downloads dir.
        from .core import download_to_file, sha1_hex
        f = sh["file"]
        dl_dir = self._build_dir(build_id) / "downloads" / "mods"
        mkdirp(dl_dir)
        name = sanitize_filename(f.get("filename") or f"{sh['project']['slug']}-shader.zip", "shader.zip")
        dest = dl_dir / name
        expected_sha1 = str((f.get("hashes") or {}).get("sha1") or "").lower()
        if dest.exists() and expected_sha1 and sha1_hex(dest.read_bytes()).lower() != expected_sha1:
            dest.unlink(missing_ok=True)
        if not dest.exists():
            download_to_file(f["url"], dest,
                             max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                             expected_sha1=expected_sha1 or None,
                             timeout_ms=300000,
                             headers=cf_download_headers(f["url"]))

        # Mark the old shader selection deselected; add the new one.
        selections = rec.get("selections") or []
        for s in selections:
            if s.get("projectType") == "shader":
                s["selected"] = False
        selections.append({
            "key": f"shader:{sh['provider']}:{sh['project']['projectId']}",
            "provider": sh["provider"], "projectId": sh["project"]["projectId"],
            "slug": sh["project"]["slug"], "title": sh["project"]["title"],
            "description": sh["project"].get("description", ""),
            "projectType": "shader",
            "versionId": sh["version"].get("versionId"),
            "versionNumber": sh["version"].get("versionNumber"),
            "filename": f.get("filename"),
            "featureIds": ["shaders"],
            "reason": f"{preset_info['reason']} — selected {sh['project']['title']} ({sh['provider']})",
            "clientSide": sh["project"].get("clientSide"),
            "serverSide": sh["project"].get("serverSide"),
            "downloadPath": str(dest), "selected": True,
        })
        rec["selections"] = selections
        rec["shaderChoice"] = {
            "preset": preset_info["preset"], "gpuTier": preset_info["gpuTier"],
            "provider": sh["provider"],
            "slug": sh["project"]["slug"], "title": sh["project"]["title"],
            "reason": preset_info["reason"],
        }
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)

        # Install into the instance: remove old shader zips, copy the new one.
        inst = self._build_dir(build_id) / "instance" / "minecraft" / "shaderpacks"
        mkdirp(inst)
        try:
            for f_ in inst.iterdir():
                if f_.name != ".keep" and f_.is_file():
                    f_.unlink(missing_ok=True)
        except OSError:
            pass
        shutil.copyfile(dest, inst / name)

        # Re-validate with a real retest (async — the swap is validated, not
        # just recorded).
        self.retest(build_id)
        return {"ok": True, "buildId": build_id, "preset": preset_info["preset"],
                "title": sh["project"]["title"], "provider": sh["provider"],
                "downloadPath": str(dest)}

    def delete_pack(self, build_id: str) -> dict:
        if is_running(build_id):
            raise RuntimeError("Stop the running game before deleting the pack")
        shutil.rmtree(self._build_dir(build_id), ignore_errors=True)
        idx_path = builds_dir() / "index.json"
        with _INDEX_LOCK:
            idx = read_json_file(idx_path) or []
            idx = [r for r in idx if r.get("buildId") != build_id]
            write_json_file(idx_path, idx)
        return {"ok": True}

    # ------------------------------------------------------------------
    # Pack Identity / snapshots / Last Known Good / AI change plans
    # ------------------------------------------------------------------
    def identity(self, build_id: str) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        return self._attach_identity(rec).get("identity") or {}

    def set_identity(self, build_id: str, patch: dict) -> dict:
        """Update editable identity fields (core theme, locked mods, goals…)."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        cur = rec.get("identity") or derive_identity(rec.get("requirements") or {}, rec)
        for k in ("coreTheme", "primaryGoals", "secondaryGoals", "requiredFeatures",
                  "optionalFeatures", "forbiddenFeatures", "lockedMods", "style", "multiplayer"):
            if k in patch:
                cur[k] = patch[k]
        if isinstance(patch.get("performanceTarget"), dict):
            cur.setdefault("performanceTarget", {})
            cur["performanceTarget"].update(patch["performanceTarget"])
        rec["identity"] = cur
        rec["selections"] = apply_intents(rec.get("selections") or [], cur)
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True, "identity": cur}

    def snapshots(self, build_id: str) -> list:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        return list_snapshots(self._build_dir(build_id))

    def create_snapshot(self, build_id: str, label: str, kind: str = "manual") -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec = self._attach_identity(rec)
        snap = create_snapshot(self._build_dir(build_id), rec, label, kind)
        rec.setdefault("aiHistory", []).append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "op": "snapshot", "label": label, "kind": kind,
            "snapshotId": snap["snapshotId"],
        })
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return snap

    def restore_snapshot(self, build_id: str, snapshot_id: str, label: str = "") -> dict:
        """Restore a snapshot into the pack (transactional, same promotion rules)."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        snap = load_snapshot(self._build_dir(build_id), snapshot_id)
        if not snap:
            raise KeyError("snapshot not found")
        # Protect the current working state first.
        self.create_snapshot(build_id, "Before restore: " + (snap.get("label") or snapshot_id))
        cand = restore_from_snapshot(self._build_dir(build_id), rec, snap)
        self._write_record(cand)
        cand.setdefault("aiHistory", []).append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "op": "restore", "snapshotId": snapshot_id,
            "label": snap.get("label") or "",
        })
        self._write_record(cand)
        return {"ok": True, "buildId": build_id, "snapshotId": snapshot_id,
                "label": snap.get("label") or label}

    def last_known_good(self, build_id: str) -> dict | None:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        lkg = _lkg_snapshot(self._build_dir(build_id))
        if not lkg:
            return None
        return {"snapshotId": lkg["snapshotId"], "label": lkg.get("label"),
                "createdAt": lkg.get("createdAt"), "modCount": len(lkg.get("selections") or []),
                "minecraftVersion": (lkg.get("requirements") or {}).get("minecraftVersion"),
                "loader": (lkg.get("requirements") or {}).get("loader")}

    def restore_last_known_good(self, build_id: str) -> dict:
        lkg = self.last_known_good(build_id)
        if not lkg:
            raise KeyError("no last known good snapshot")
        return self.restore_snapshot(build_id, lkg["snapshotId"], "Last Known Good")

    def pack_health(self, build_id: str) -> dict:
        """Explainable health report — status + weighted score from the real
        record, the LKG snapshot on disk and the machine's hardware."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec = self._attach_identity(rec)
        return pack_health(rec, self._build_dir(build_id), self.hardware().get("effective"))

    def check_pack_updates(self, build_id: str, limit: int = 40) -> dict:
        """Real, bounded update check: query each provider for the newest
        version of every selected mod and compare version ids against what the
        pack has. Results persist on the record (healthUpdates) so the health
        dashboard's Maintenance score reflects reality, not guesses."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        req = rec.get("requirements") or {}
        mc = req.get("minecraftVersion") or "1.20.1"
        loader = req.get("loader") or "fabric"
        settings = self.settings_store.load()
        build_cfg = settings.get("build") or {}
        sources = build_cfg.get("sources") or settings.get("defaults", {}).get("sources") or ["modrinth"]
        providers = {p.name: p for p in build_providers(self.settings_store, sources) if p.available}
        mods = [s for s in (rec.get("selections") or [])
                if s.get("selected", True) and s.get("projectType") == "mod"
                and s.get("provider") and s.get("projectId") and s.get("versionId")]
        available = []
        checked = 0
        errors = 0
        for s in mods[:limit]:
            prov = providers.get(s["provider"])
            if not prov:
                continue
            try:
                versions = prov.get_versions(s["projectId"], {
                    "minecraftVersion": mc, "loaders": [loader],
                })
                checked += 1
            except Exception:  # noqa: BLE001
                errors += 1
                continue
            if not versions:
                continue
            newest = versions[0]
            if newest.get("versionId") and newest["versionId"] != s.get("versionId"):
                available.append({
                    "provider": s["provider"], "slug": s.get("slug"),
                    "title": s.get("title") or s.get("slug"),
                    "currentVersion": s.get("versionNumber"),
                    "latestVersion": newest.get("versionNumber"),
                    "latestVersionId": newest.get("versionId"),
                    "publishedAt": newest.get("datePublished") or newest.get("date_published"),
                })
        rec["healthUpdates"] = {
            "checkedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "count": len(available), "checked": checked, "errors": errors,
            "available": available,
        }
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True, "count": len(available), "checked": checked,
                "errors": errors, "available": available}

    def plan_ai_change(self, build_id: str, prompt: str) -> dict:
        """Non-mutating AI change plan for a conversational request."""
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        rec = self._attach_identity(rec)
        return plan_change(rec, prompt, self.hardware())

    def apply_ai_change(self, build_id: str, prompt: str) -> dict:
        """Transactional AI edit: snapshot → candidate build → promote only on PASS.

        The working pack is never mutated directly. A candidate child build
        runs the requested change; when it validates, its result is promoted
        into this pack's record. On failure the original stays untouched and
        the failed attempt is recorded in aiHistory.
        """
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        # Protect the current state before anything happens.
        self.create_snapshot(build_id, "Before AI: " + (prompt or "")[:60], kind="before-ai-edit")
        candidate_id = self.start_build({
            "prompt": prompt, "parentBuildId": build_id, "candidateOf": build_id,
            "name": (rec.get("name") or "Untitled") + " (AI candidate)",
        })
        return {"ok": True, "buildId": build_id, "candidateBuildId": candidate_id}

    def _promote_candidate(self, parent_id: str, cand: dict) -> None:
        """Merge a validated candidate build into its parent record.

        Only selections/graph/test evidence and the identity are copied — the
        parent keeps its own build dir, name, and history. Never called on a
        failed candidate.
        """
        parent = self._read_record(parent_id)
        if not parent:
            return
        req = cand.get("requirements") or {}
        parent["requirements"] = req
        parent["selections"] = apply_intents(cand.get("selections") or [],
                                              cand.get("identity") or derive_identity(req, cand))
        parent["identity"] = cand.get("identity") or derive_identity(req, cand)
        parent["graph"] = cand.get("graph")
        parent["testResult"] = cand.get("testResult")
        parent["packStats"] = cand.get("packStats") or {}
        parent["shaderChoice"] = cand.get("shaderChoice")
        parent["resourcePackChoice"] = cand.get("resourcePackChoice")
        parent["perfEstimate"] = cand.get("perfEstimate")
        parent["repairs"] = cand.get("repairs") or []
        parent.setdefault("aiHistory", []).append({
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "op": "promote", "fromBuildId": cand.get("buildId"),
            "label": (cand.get("request") or "AI change")[:80],
            "testStatus": (cand.get("testResult") or {}).get("status"),
            "modCount": (cand.get("packStats") or {}).get("modCount"),
        })
        parent["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Sync the validated instance (mods/shaderpacks/resourcepacks) from the
        # candidate build dir into the parent so Play runs the new state.
        try:
            self._sync_candidate_instance(parent_id, cand)
        except Exception:  # noqa: BLE001
            pass
        self._write_record(parent)
        # A promoted pack that validated is the new Last Known Good.
        try:
            mark_last_known_good(self._build_dir(parent_id), self._attach_identity(parent))
        except Exception:  # noqa: BLE001
            pass

    def _sync_candidate_instance(self, parent_id: str, cand: dict) -> None:
        """Copy the candidate build's installed mods/visuals into the parent."""
        cand_inst = self._build_dir(cand["buildId"]) / "instance" / "minecraft"
        par_inst = self._build_dir(parent_id) / "instance" / "minecraft"
        for sub in ("mods", "shaderpacks", "resourcepacks"):
            src = cand_inst / sub
            dst = par_inst / sub
            if not src.is_dir():
                continue
            mkdirp(dst)
            for f_ in src.iterdir():
                if f_.name in (".keep",) or not f_.is_file():
                    continue
                try:
                    shutil.copyfile(f_, dst / f_.name)
                except OSError:
                    continue

    # ------------------------------------------------------------------
    # build pipeline
    # ------------------------------------------------------------------
    def start_build(self, req: dict) -> str:
        prompt = req.get("prompt") or req.get("request") or ""
        if not prompt:
            raise RuntimeError("prompt required")
        build_id = req.get("buildId") or new_build_id()
        rec = {
            "buildId": build_id, "name": req.get("name") or _auto_name(prompt),
            "request": prompt, "status": "building", "phase": "parse",
            "requirements": {}, "selections": [], "downloads": [],
            "graph": {"nodes": {}, "edges": []}, "tests": [], "testResult": None,
            "conflicts": [], "repairs": [], "exports": [], "packStats": {},
            "settings": self.settings_store.load(),
            "perfEstimate": None, "finalReport": None, "error": None,
            "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        # Candidate builds (AI edits / transactional changes) know their parent
        # so completion can promote a PASS or leave the parent untouched on FAIL.
        if req.get("candidateOf"):
            rec["candidateOf"] = req["candidateOf"]
            rec["parentBuildId"] = req.get("parentBuildId") or req["candidateOf"]
        mkdirp(self._build_dir(build_id))
        self._write_record(rec)
        t = threading.Thread(target=self._run_build, args=(build_id, prompt, req), daemon=True)
        self._build_threads[build_id] = t
        t.start()
        return build_id

    def _run_build(self, build_id: str, prompt: str, req: dict) -> None:
        rec = self._read_record(build_id)
        logger = BuildLogger(build_id, self._build_dir(build_id))
        try:
            rec = self._pipeline(build_id, rec, prompt, req, logger)
            rec["status"] = "done" if (rec.get("testResult") or {}).get("status") == "PASS" else "failed"
            rec["phase"] = "done"
        except Exception as e:
            logger.error("system", f"Build failed: {e}")
            logger.error("system", traceback.format_exc())
            rec["status"] = "failed"
            rec["phase"] = "error"
            rec["error"] = str(e)
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        logger.log("ok", "report", f"Build finished: {rec['status']}", progress=100)

        # ---- candidate lifecycle (transactional AI edits)
        if rec.get("candidateOf"):
            parent_id = rec["parentBuildId"] or rec["candidateOf"]
            if rec.get("status") == "done" and (rec.get("testResult") or {}).get("status") == "PASS":
                try:
                    self._promote_candidate(parent_id, rec)
                    logger.log("ok", "promote", f"Candidate validated — promoted into {parent_id}")
                except Exception as e:  # noqa: BLE001
                    logger.error("system", f"Candidate promotion failed: {e}")
            else:
                parent = self._read_record(parent_id)
                if parent:
                    parent.setdefault("aiHistory", []).append({
                        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "op": "rejected", "fromBuildId": build_id,
                        "label": (prompt or "AI change")[:80],
                        "reason": (rec.get("error") or
                                   (rec.get("testResult") or {}).get("status") or "failed"),
                    })
                    parent["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    self._write_record(parent)
                    logger.log("warn", "promote",
                               f"Candidate did not validate — original {parent_id} untouched")

        # ---- Last Known Good: a pack that validated is restorable forever
        if rec.get("status") == "done" and (rec.get("testResult") or {}).get("status") == "PASS":
            try:
                mark_last_known_good(self._build_dir(build_id), self._attach_identity(rec))
            except Exception:  # noqa: BLE001
                pass

    def _pipeline(self, build_id, rec, prompt, req, logger) -> dict:
        settings = self.settings_store.load()
        defaults = settings.get("defaults") or {}
        build_cfg = settings.get("build") or {}
        # ---- interpret
        logger.stage("parse", "Parsing request…")
        interp = interpret(prompt)
        r = interp["requirements"]
        if r.get("needsClarification"):
            raise RuntimeError("I need a little more direction before building. Name a theme or feature, such as cozy farming, magic, exploration, or performance.")
        # merge explicit request overrides (from the UI advanced settings)
        if req.get("mcVersion") and req["mcVersion"] != "auto":
            r["minecraftVersion"] = req["mcVersion"]
        if req.get("loader") and req["loader"] != "auto":
            r["loader"] = req["loader"]
        if req.get("packSize"):
            r["packSize"] = req["packSize"]
        if req.get("ramGB") and req["ramGB"] > 0:
            r["ramGB"] = req["ramGB"]
        if req.get("testMode"):
            r["testMode"] = req["testMode"]
        if req.get("multiplayer") is not None:
            r["multiplayer"] = bool(req["multiplayer"])
        if req.get("serverPack") is not None:
            r["serverPack"] = bool(req["serverPack"])
        if req.get("shaders") is not None:
            r["shaders"] = bool(req["shaders"])
        # auto MC + loader
        if r["minecraftVersion"] == "auto":
            r["minecraftVersion"] = defaults.get("minecraftVersion") if defaults.get("minecraftVersion") != "auto" else "1.20.1"
        if r["loader"] == "auto":
            r["loader"] = defaults.get("loader") if defaults.get("loader") != "auto" else "fabric"
        # auto-tune to hardware
        hw = self.hardware().get("effective") or {}
        if r.get("autoTune") or (req.get("autoTune")):
            r["ramGB"] = r["ramGB"] or hw.get("ramGB") or 8
            if hw.get("ramGB") and hw["ramGB"] < 8:
                r["packSize"] = "light"
                r["shaders"] = False
        logger.ok("parse", "Request parsed",
                  json.dumps({k: r[k] for k in ("theme", "minecraftVersion", "loader", "packSize", "ramGB", "testMode", "shaders", "multiplayer") if k in r}))
        rec["requirements"] = r
        rec["name"] = rec.get("name") or _auto_name(prompt)
        self._write_record(rec)

        # ---- providers
        logger.stage("search", "Contacting providers…")
        sources = build_cfg.get("sources") or defaults.get("sources") or ["modrinth"]
        providers = build_providers(self.settings_store, sources)
        available = [p for p in providers if p.available]
        if not available:
            raise RuntimeError("No providers available. Add a CurseForge API key or restore Modrinth access.")
        logger.info("search", f"{len(available)} provider(s) available: {', '.join(p.name for p in available)}")

        # ---- feature search + ranking
        logger.stage("search", "Searching candidates…")
        features = r.get("features") or []
        seeds = []
        selected_projects = []
        for f in features:
            fid = f["id"]
            # Shader packs are selected by the GPU-aware visuals step below
            # (which also seeds the rendering mod) — not as a random "mod"
            # that merely matches the keyword "shaders".
            if fid == "shaders" and r.get("shaders"):
                continue
            target = f.get("targetCount", 1)
            candidates = []
            for prov in available:
                for attempt in range(RETRY_EMPTY_ATTEMPTS):
                    try:
                        hits = prov.search({
                            "query": fid, "projectType": "mod",
                            "minecraftVersion": r["minecraftVersion"],
                            "loaders": None if r["loader"] == "vanilla" else [r["loader"]],
                            "limit": 15,
                            "categories": f.get("categoryTags"),
                        })
                        if hits or attempt >= RETRY_EMPTY_ATTEMPTS - 1:
                            break
                        # A provider answering 200 with an empty result set is
                        # usually a momentary catalog blip — give it a bounded
                        # retry before deciding the feature has no candidates.
                        logger.warn("search", f"{prov.name} search for '{fid}' returned empty; retrying ({attempt + 1}/{RETRY_EMPTY_ATTEMPTS})")
                        time.sleep(RETRY_BACKOFF_MS * (attempt + 1) / 1000.0)
                    except Exception as e:
                        logger.warn("search", f"{prov.name} search for '{fid}' failed: {e}")
                        hits = []
                        break
                for h in hits:
                    h["_provider"] = prov.name
                    candidates.append(h)
            logger.info("search", f"Feature '{fid}': {len(candidates)} candidates from providers")
            ranked = []
            for c in candidates:
                try:
                    ranked.append(rank_candidate(c, f, r, self.memory))
                except Exception:
                    continue
            ranked.sort(key=lambda x: x["score"], reverse=True)
            taken = 0
            for rc in ranked:
                if taken >= target:
                    break
                p = rc["project"]
                if any(s["projectId"] == p["projectId"] and s["provider"] == p["provider"] for s in seeds):
                    continue
                seeds.append({
                    "featureId": fid, "provider": p["provider"],
                    "projectId": p["projectId"], "project": p,
                    "reason": rc["reason"], "score": rc["score"],
                })
                selected_projects.append({**p, "featureId": fid, "reason": rc["reason"], "score": rc["score"]})
                taken += 1
        logger.ok("search", f"Selected {len(seeds)} seed mods across {len(features)} features")

        # ---- visuals: GPU-aware shader pack + its rendering mod, and the
        #      resolution/theme-aware resource pack. Dedicated "visuals" stage
        #      so the AI Builder timeline shows the picks live.
        shader_choice = None
        resource_pack_choice = None
        if r.get("shaders") or (r.get("resourcePackResolution") or 0) > 0:
            logger.stage("visuals", "Selecting shaders & resource packs…")
        if r.get("shaders"):
            preset = pick_shader_preset(r, self.hardware(),
                                        requested=r.get("shaderQuality"))
            sh = choose_shader(available, r["minecraftVersion"], preset["preset"], logger)
            if sh:
                seeds.append({
                    "featureId": "shaders", "provider": sh["provider"],
                    "projectId": sh["project"]["projectId"], "project": sh["project"],
                    "reason": f"{preset['reason']} — selected {sh['project']['title']} ({sh['provider']})",
                    "score": 100,
                })
                shader_choice = {
                    "preset": preset["preset"], "gpuTier": preset["gpuTier"],
                    "provider": sh["provider"],
                    "slug": sh["project"]["slug"], "title": sh["project"]["title"],
                    "reason": preset["reason"],
                }
                rend_slug = rendering_mod_for(r["loader"])
                if rend_slug and not any((s.get("project") or {}).get("slug", "") == rend_slug
                                         or s.get("projectId") == rend_slug for s in seeds):
                    rp = None
                    for prov in available:
                        try:
                            rp = prov.get_project(rend_slug)
                            if rp:
                                break
                        except Exception:
                            rp = None
                    if rp:
                        seeds.append({
                            "featureId": "shaders", "provider": rp["provider"],
                            "projectId": rp["projectId"], "project": rp,
                            "reason": f"Rendering mod for {r['loader']} — runs the selected shader pack",
                            "score": 100,
                        })
                logger.ok("visuals", f"Shader: {sh['project']['title']} — {preset['preset']} preset on {preset['gpuTier']} GPU")
            else:
                shader_choice = {
                    "preset": preset["preset"], "gpuTier": preset["gpuTier"],
                    "provider": None,
                    "slug": None, "title": None,
                    "reason": f"No shader pack found for MC {r['minecraftVersion']} ({preset['preset']} preset)",
                }
                logger.warn("visuals", f"No shader pack found for MC {r['minecraftVersion']} ({preset['preset']} preset)")
        if (r.get("resourcePackResolution") or 0) > 0:
            rp_req = pick_resource_pack(r, self.hardware())
            if rp_req:
                rp = choose_resource_pack(available, r["minecraftVersion"],
                                          rp_req["resolution"], r.get("theme") or [], logger)
                if rp:
                    seeds.append({
                        "featureId": "resourcepacks", "provider": rp["provider"],
                        "projectId": rp["project"]["projectId"], "project": rp["project"],
                        "reason": f"{rp_req['reason']} — selected {rp['project']['title']}",
                        "score": 100,
                    })
                    resource_pack_choice = {
                        "resolution": rp_req["resolution"], "gpuTier": rp_req["gpuTier"],
                        "provider": rp["provider"],
                        "slug": rp["project"]["slug"], "title": rp["project"]["title"],
                        "reason": rp_req["reason"],
                    }
                    logger.ok("visuals", f"Resource pack: {rp['project']['title']} — {rp_req['resolution']}x tier ({rp['provider']})")
                else:
                    resource_pack_choice = {
                        "resolution": rp_req["resolution"], "gpuTier": rp_req["gpuTier"],
                        "provider": None,
                        "slug": None, "title": None,
                        "reason": f"No resource pack found for MC {r['minecraftVersion']} at {rp_req['resolution']}x",
                    }
                    logger.warn("visuals", f"No resource pack found for MC {r['minecraftVersion']} at {rp_req['resolution']}x")

        # ---- resolve
        logger.stage("resolve", "Resolving dependencies…")
        res = resolve_pack({
            "providers": available, "seeds": seeds,
            "minecraftVersion": r["minecraftVersion"], "loader": r["loader"],
            "logger": logger,
        })
        graph = res["graph"]
        issues = res["issues"]
        logger.info("resolve", f"Graph: {res['stats']['projects']} projects, {res['stats']['deps']} required deps")

        # ---- conflicts
        logger.stage("conflict", "Detecting conflicts…")
        conf = detect_and_resolve_conflicts(graph, {
            "loader": r["loader"], "minecraftVersion": r["minecraftVersion"],
            "memory": self.memory, "logger": logger, "autoResolve": True,
        })
        rec["conflicts"] = conf["conflicts"]
        self._write_record(rec)

        # ---- reconcile (jar metadata) after downloads
        selected = [n for n in graph["nodes"].values() if n.get("selected")]
        logger.stage("download", f"Downloading {len(selected)} files…")
        dl = download_pack_files(selected, str(self._build_dir(build_id) / "downloads"), {
            "logger": logger, "maxTotalDownloadMB": build_cfg.get("maxTotalDownloadMB", 600),
        })
        rec["downloads"] = dl["records"]
        self._write_record(rec)

        # ---- reconcile jar metadata
        if dl["fileByKey"]:
            logger.stage("reconcile", "Reconciling jar metadata…")
            rec_result = reconcile_jar_dependencies({
                "graph": graph, "providers": available,
                "minecraftVersion": r["minecraftVersion"], "loader": r["loader"],
                "logger": logger, "fileByKey": dl["fileByKey"],
                "downloadsDir": str(self._build_dir(build_id) / "downloads" / "mods"),
            })
            issues.extend(rec_result["issues"])
            if rec_result["extraFileByKey"]:
                dl["fileByKey"].update(rec_result["extraFileByKey"])
                dl["records"].extend(
                    {"key": k, "versionId": (graph["nodes"].get(k) or {}).get("version", {}).get("versionId"),
                     "filename": Path(p).name, "url": "", "sizeBytes": Path(p).stat().st_size if Path(p).exists() else 0,
                     "status": "ok"} for k, p in rec_result["extraFileByKey"].items())
                rec["downloads"] = dl["records"]
                self._write_record(rec)

        # ---- selections for the record
        selections = []
        for n in graph["nodes"].values():
            if not n.get("selected"):
                continue
            v = n.get("version") or {}
            f = (v.get("files") or [None])[0] if v.get("files") else None
            selections.append({
                "key": n["key"], "provider": n["project"]["provider"],
                "projectId": n["project"]["projectId"], "slug": n["project"]["slug"],
                "title": n["project"]["title"], "description": n["project"].get("description", ""),
                "projectType": n["project"].get("projectType", "mod"),
                "versionId": v.get("versionId"), "versionNumber": v.get("versionNumber"),
                "filename": f.get("filename") if f else None,
                "featureIds": n.get("featureIds") or [], "reason": n.get("reason"),
                "score": n.get("rankScore"),
                "clientSide": n["project"].get("clientSide"), "serverSide": n["project"].get("serverSide"),
                "downloadPath": dl["fileByKey"].get(n["key"]),
                "selected": True,
            })
        rec["selections"] = selections
        rec["graph"] = graph
        rec["shaderChoice"] = shader_choice
        rec["resourcePackChoice"] = resource_pack_choice
        rec["packStats"] = {"modCount": len([s for s in selections if s["projectType"] == "mod"]),
                            "projectCount": len(graph["nodes"]),
                            "downloadMB": round(dl["totalBytes"] / 1024 ** 2, 1)}
        self._write_record(rec)

        # ---- instance
        logger.stage("instance", "Creating isolated instance…")
        inst = create_instance_dir(str(self._build_dir(build_id)), logger)
        mods_dir = Path(inst["modsDir"])
        for n in graph["nodes"].values():
            if not n.get("selected") or n["project"].get("projectType") != "mod":
                continue
            p = dl["fileByKey"].get(n["key"])
            if p and Path(p).exists():
                shutil.copyfile(p, mods_dir / sanitize_filename(n["project"]["slug"] + ".jar", "mod.jar"))
        mod_jars = []
        for s in selections:
            if s["projectType"] == "mod" and s.get("downloadPath") and Path(s["downloadPath"]).exists():
                mod_jars.append({"slug": s["slug"], "path": s["downloadPath"],
                                 "featureIds": s["featureIds"], "clientSide": s["clientSide"],
                                 "serverSide": s["serverSide"]})
        install_mod_jars(mods_dir, mod_jars, logger)
        write_game_file(inst["gameDir"], "README.txt", f"{rec['name']} — {r['minecraftVersion']} {r['loader']} ({len(mod_jars)} mods)")
        logger.ok("instance", f"Instance ready: {len(mod_jars)} mods installed")

        # ---- perf estimate
        perf = performance_estimate(self.hardware(), r.get("ramGB") or 8,
                                    mod_count=len(mod_jars), shaders=bool(r.get("shaders")))
        rec["perfEstimate"] = perf
        logger.info("perf", f"Estimated RAM {perf['estimatedRamGB']} GB, allocation {perf['recommendedAllocation']}, confidence {perf['confidence']}%")

        # ---- test
        logger.stage("test", f"Testing pack ({r['testMode']} mode)…")
        env = {
            "buildId": build_id, "buildDir": str(self._build_dir(build_id)),
            "gameDir": inst["gameDir"], "mcVersion": r["minecraftVersion"],
            "loader": r["loader"],            "testMode": r["testMode"], "logger": logger,
            "xmxMB": fit_xmx_mb(r.get("ramGB") or 8),
            "modJars": mod_jars,
            "resourcePackFiles": [s["downloadPath"] for s in selections if s["projectType"] == "resourcepack" and s.get("downloadPath")],
            "shaderFiles": [s["downloadPath"] for s in selections if s["projectType"] == "shader" and s.get("downloadPath")],
            "downloadAssets": build_cfg.get("downloadAssets", False),
            "maxAssetMB": build_cfg.get("maxAssetMB", 400),
            "autoInstallJava": build_cfg.get("autoInstallJava", True),
        }
        test_result = run_test_level(env, graph)
        rec["testResult"] = test_result
        rec["tests"] = [test_result]
        self._write_record(rec)

        # ---- repair loop
        repair_mode = build_cfg.get("repairMode", "standard")
        limits = {"instant": 1, "standard": 10, "deep": 15}
        max_repairs = limits.get(repair_mode, 10)
        repairs = 0
        repeats = {}
        while test_result["status"] != "PASS" and repairs < max_repairs:
            logger.stage("repair", f"Repair attempt {repairs + 1}/{max_repairs}…")
            action = self._analyze_failure(build_id, rec, env, logger)
            if not action:
                logger.warn("repair", "No repair action determined — stopping")
                break
            # Stuck-loop guard: if the exact same action repeats 3+ times it is
            # not fixing anything (e.g. an unresolvable mod id) — stop instead
            # of burning the budget.
            sig = action.get("action") + ":" + ",".join(sorted(action.get("mods") or [action.get("slug", "")]))
            repeats[sig] = repeats.get(sig, 0) + 1
            if repeats[sig] >= 3:
                logger.warn("repair", f"Repair '{sig}' has repeated {repeats[sig]}x without fixing the launch — stopping")
                break
            rec["repairs"] = rec.get("repairs") or []
            rec["repairs"].append(action)
            logger.ok("repair", f"Repair: {action.get('action')} — {action.get('reason')}")
            self._apply_repair(action, rec, dl, mod_jars, env, mods_dir, logger)
            self._write_record(rec)
            # wipe stale diagnostics + retest
            shutil.rmtree(Path(env["gameDir"]) / "crash-reports", ignore_errors=True)
            shutil.rmtree(Path(env["gameDir"]) / "logs", ignore_errors=True)
            test_result = run_test_level(env, graph)
            rec["testResult"] = test_result
            rec["tests"].append(test_result)
            self._write_record(rec)
            repairs += 1
            if test_result["status"] == "PASS":
                self.memory.record({
                    "minecraftVersion": r["minecraftVersion"], "loader": r["loader"],
                    "mods": {s["slug"]: s["versionNumber"] for s in rec["selections"] if s["projectType"] == "mod"},
                    "result": "PASS", "buildId": build_id,
                    "resolution": f"PASS after {repairs} repair(s)",
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                })
        if test_result["status"] != "PASS":
            self.memory.record({
                "minecraftVersion": r["minecraftVersion"], "loader": r["loader"],
                "mods": {s["slug"]: s["versionNumber"] for s in rec["selections"] if s["projectType"] == "mod"},
                "result": "FAIL",
                "crashSignature": (test_result.get("phases") or [{}])[0].get("name"),
                "buildId": build_id,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })

        # ---- exports
        logger.stage("export", "Exporting pack…")
        exports = []
        name_slug = sanitize_filename(rec["name"], "pack")
        out_dir = self._build_dir(build_id) / "exports"
        mkdirp(out_dir)
        loader_version = None
        # CF references from selections on curseforge provider
        cf_refs = []
        for s in selections:
            if s["provider"] == "curseforge" and s.get("versionId"):
                cf_refs.append({"slug": s["slug"], "projectID": int(s["projectId"]),
                                "fileID": int(s["versionId"])})
        mr = export_mrpack({
            "name": rec["name"], "summary": prompt[:200], "mcVersion": r["minecraftVersion"],
            "loader": r["loader"], "loaderVersion": loader_version,
            "selections": selections, "graph": graph,
            "modsDir": str(self._build_dir(build_id) / "downloads" / "mods"),
            "overridesDir": inst["gameDir"], "outPath": str(out_dir / f"{name_slug}.mrpack"),
            "logger": logger,
        })
        exports.append(mr)
        cf = export_curseforge({
            "name": rec["name"], "version": "1.0.0", "mcVersion": r["minecraftVersion"],
            "loader": r["loader"], "loaderVersion": loader_version,
            "selections": selections, "cfReferences": cf_refs,
            "modsDir": str(self._build_dir(build_id) / "downloads" / "mods"),
            "overridesDir": inst["gameDir"], "outPath": str(out_dir / f"{name_slug}-CurseForge.zip"),
            "logger": logger,
        })
        exports.append(cf)
        if r.get("serverPack") or r.get("multiplayer"):
            sp = export_server_pack({
                "name": rec["name"], "mcVersion": r["minecraftVersion"],
                "loader": r["loader"], "selections": selections,
                "modsDir": str(self._build_dir(build_id) / "downloads" / "mods"),
                "overridesDir": inst["gameDir"], "outPath": str(out_dir / f"{name_slug}-Server.zip"),
                "perf": perf, "logger": logger,
            })
            exports.append(sp)
        rec["exports"] = exports
        rec["finalReport"] = self._build_report(rec, test_result, conf, issues, rec.get("repairs") or [])
        self._write_record(rec)
        return rec

    # ------------------------------------------------------------------
    # repair analysis
    # ------------------------------------------------------------------
    def _analyze_failure(self, build_id, rec, env, logger) -> dict | None:
        from .instance import collect_instance_logs
        logs = collect_instance_logs(env["gameDir"])
        all_text = "\n".join(
            (logs.get("latest") or []) + (logs.get("crashReports") or []) +
            (logs.get("debug") or []) + (logs.get("console") or []))
        if not all_text.strip():
            logger.warn("repair", "No log evidence captured — cannot diagnose")
            return None
        # Only diagnose a REAL failure. Forge emits harmless warnings in every
        # healthy pack ("Error loading class: ... ClassNotFoundException ..."
        # for optional/disabled features), and those must never trigger repairs.
        if not fatal_startup_detected(all_text.split("\n")):
            logger.warn("repair", "No fatal startup error in logs — not repairing")
            return None
        sig = match_crash_signature(all_text)
        label = sig["label"] if sig else "unknown"
        # 1. Missing dependencies — add them (highest confidence). Entries that are
        # really version conflicts (the mod IS installed, just the wrong version)
        # are excluded here and handled by the change-version repair instead, so
        # we never add a duplicate of an already-present mod.
        conflicts = version_conflicts(all_text)
        conflict_ids = {c["id"] for c in conflicts}
        missing = [m for m in missing_dep_ids(all_text) if m not in conflict_ids]
        # Accumulate requester knowledge across rounds: the screen that says
        # "Mod ID: 'connectormod', Requested by: 'origins'" may appear in a
        # different launch than the crash it eventually causes, and we must
        # remember it when deciding what to cascade-remove.
        rec.setdefault("_depRequesters", {}).update(missing_requesters(all_text))
        if missing:
            # Add ALL detected missing deps in one round — capping starves the
            # cascade when a pack is short 6+ libraries at once.
            ranges = expected_ranges(all_text)
            return {"action": "add-missing", "mods": missing,
                    "ranges": {k: v for k, v in ranges.items() if k in missing},
                    "reason": f"Crash signature '{label}': missing dependency {', '.join(missing)}",
                    "signature": label}
        # 1.5 Version conflicts — the mod IS present but outside the required range.
        if conflicts:
            return {"action": "change-version",
                    "conflicts": [{"id": c["id"], "expected": c["expected"], "actual": c["actual"]} for c in conflicts],
                    "reason": f"Crash signature '{label}': version out of required range — {', '.join(c['id'] + ' (' + c['actual'] + ')' for c in conflicts)}",
                    "signature": label}
        parsed = parse_crash_report(all_text)
        # 2. Invalid jar name — remove that jar
        bad = find_invalid_module_jar(parsed["exception"], [s["slug"] for s in rec["selections"] if s["projectType"] == "mod"])
        if bad:
            return {"action": "remove", "slug": bad,
                    "reason": f"Invalid Java module name derived from jar filename '{bad}'",
                    "signature": label}
        # 3. Unknown crash — attribute from the real stack trace
        jars = [{"slug": s["slug"], "path": s["downloadPath"]} for s in rec["selections"]
                if s["projectType"] == "mod" and s.get("downloadPath") and Path(s["downloadPath"]).exists()]
        attrs = attribute_crash(all_text, jars)
        if attrs:
            return {"action": "remove", "slug": attrs[0]["slug"],
                    "reason": f"Stack trace attributes the crash to {attrs[0]['slug']} ({attrs[0]['confidence']}): {attrs[0]['reason']}",
                    "signature": label}
        # 4. Fall back to culprit hints from the crash report
        for hint in parsed["culpritHints"]:
            slug = next((s["slug"] for s in rec["selections"] if norm_id(s["slug"]) == norm_id(hint) or s["slug"] == hint), None)
            if slug:
                return {"action": "remove", "slug": slug,
                        "reason": f"Crash report names '{hint}' as the culprit (signature {label})",
                        "signature": label}
        return None

    def _apply_repair(self, action, rec, dl, mod_jars, env, mods_dir, logger) -> None:
        from .instance import remove_jar, collect_instance_logs
        from .jarmeta import read_jar_metadata, provided_mod_ids
        from .core import download_to_file, version_satisfies
        providers = build_providers(self.settings_store, rec["settings"].get("build", {}).get("sources") or ["modrinth"])
        prov = next((p for p in providers if p.available and p.name == "modrinth"), None) or next((p for p in providers if p.available), None)

        def log_text():
            try:
                logs = collect_instance_logs(env["gameDir"])
                return "\n".join((logs.get("latest") or []) + (logs.get("crashReports") or []) +
                                  (logs.get("debug") or []) + (logs.get("console") or []))
            except Exception:
                return ""

        def selection_by_mod_id(mid: str):
            want = norm_id(mid)
            for s in rec["selections"]:
                if not s.get("selected", True) or s.get("projectType") != "mod":
                    continue
                if norm_id(s.get("slug", "")) == want:
                    return s
                if s.get("downloadPath") and Path(s["downloadPath"]).exists():
                    try:
                        meta = read_jar_metadata(s["downloadPath"])
                        if meta and norm_id(meta.get("id", "")) == want:
                            return s
                    except Exception:
                        pass
            return None

        if action["action"] == "add-missing":
            if not prov:
                return
            graph = rec["graph"]
            unresolved = []      # cannot find ANY project/version providing the id
            retry_later = []     # found it, but download/network hiccup — retry next round
            for mid in action.get("mods") or []:
                try:
                    # get_project raises on 404 for non-slug mod ids; fall through
                    # to the loose resolver (hyphen/space/suffix variants) instead
                    # of treating the id as unresolvable.
                    proj = None
                    try:
                        proj = prov.get_project(mid)
                    except Exception:
                        proj = None
                    if not proj:
                        proj = _loose_resolve(prov, mid, env)
                    if not proj:
                        logger.warn("repair", f"Could not resolve missing dependency '{mid}'")
                        unresolved.append(mid)
                        continue
                    versions = prov.get_versions(proj["projectId"], {
                        "minecraftVersion": env["mcVersion"],
                        "loaders": None if env["loader"] == "vanilla" else [env["loader"]],
                    }) or []
                    if not versions:
                        logger.warn("repair", f"No {env['mcVersion']}/{env['loader']} version of '{proj['title']}'")
                        unresolved.append(mid)
                        continue
                    # Prefer the newest version that satisfies the required range
                    # from the error screen (e.g. irons_lib must be in
                    # [1.20.1-2,1.20.1-3), not merely any 1.20.1 build).
                    want_range = (action.get("ranges") or {}).get(mid)
                    v = None
                    if want_range:
                        for cand in versions:
                            if version_satisfies(cand.get("versionNumber", ""), want_range):
                                v = cand
                                break
                    if v is None:
                        v = versions[0]
                    f = next((x for x in v.get("files") or [] if x.get("primary")), (v.get("files") or [None])[0])
                    if not f or not f.get("url"):
                        unresolved.append(mid)
                        continue
                    dest = Path(env["buildDir"]) / "downloads" / "mods" / sanitize_filename(f"{proj['slug']}-{v['versionNumber']}.jar", "mod.jar")
                    if not dest.exists():
                        try:
                            download_to_file(f["url"], dest, max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                                             expected_sha1=(f.get("hashes") or {}).get("sha1"), timeout_ms=300000,
                                             headers=cf_download_headers(f["url"]))
                        except Exception as e:
                            # Transient network/CDN failure: the project IS resolvable,
                            # so retry next round instead of removing its requesters.
                            logger.warn("repair", f"Download of '{mid}' failed (retry next round): {e}")
                            retry_later.append(mid)
                            continue
                    # Verify the downloaded jar actually provides the missing mod id.
                    # A loose search can resolve to an addon (e.g. a Twilight Forest
                    # addon) whose own mod id differs from the one that is missing —
                    # adding it would never satisfy the error screen. Provided ids
                    # include embedded jarjar mods (Sinytra Connector ships its
                    # "connectormod" inside META-INF/jarjar).
                    want = norm_id(mid)
                    meta = read_jar_metadata(str(dest))
                    got = norm_id((meta or {}).get("id", "")) if meta else ""
                    provided = [norm_id(x) for x in provided_mod_ids(str(dest))]
                    if not (got and got == want) and want not in provided:
                        shown = got or (",".join(provided) if provided else "nothing")
                        logger.warn("repair", f"'{mid}' resolved to {proj['slug']} which provides '{shown}' — not the missing id, treating as unresolved")
                        unresolved.append(mid)
                        continue
                    key = f"{proj['provider']}:{proj['projectId']}"
                    graph["nodes"][key] = {"key": key, "project": proj, "version": v,
                                           "featureIds": ["repair"], "selected": True,
                                           "reason": f"Added by repair: {action['reason']}", "locked": False}
                    rec["selections"].append({
                        "key": key, "provider": proj["provider"], "projectId": proj["projectId"],
                        "slug": proj["slug"], "title": proj["title"],
                        "description": proj.get("description", ""),
                        "projectType": proj.get("projectType", "mod"),
                        "versionId": v.get("versionId"), "versionNumber": v.get("versionNumber"),
                        "filename": f.get("filename"), "featureIds": ["repair"],
                        "reason": f"Added by repair: {action['reason']}",
                        "clientSide": proj.get("clientSide"), "serverSide": proj.get("serverSide"),
                        "downloadPath": str(dest), "selected": True,
                    })
                    mod_jars.append({"slug": proj["slug"], "path": str(dest), "featureIds": ["repair"]})
                    dl["fileByKey"][key] = str(dest)
                    shutil.copyfile(dest, mods_dir / sanitize_filename(proj["slug"] + ".jar", "mod.jar"))
                    logger.ok("repair", f"Added {proj['title']} {v['versionNumber']} ({proj['slug']})")
                except Exception as e:
                    logger.warn("repair", f"add-missing failed for {mid}: {e}")
                    retry_later.append(mid)
            # Dependencies that could not be satisfied by ANY provider: the mods
            # that require them cannot function without them, so remove the
            # requesters instead of looping forever (e.g. a CurseForge-only base
            # mod like Twilight Forest in a Modrinth-only pack). Only genuine
            # resolution failures count — transient download/network errors are
            # retried in the next repair round.
            if unresolved:
                req_map = missing_requesters(log_text())
                doomed = []
                for mid in unresolved:
                    for req in req_map.get(mid, []):
                        doomed.append((mid, req))
                for mid, req in doomed:
                    target = selection_by_mod_id(req)
                    if not target:
                        logger.warn("repair", f"Could not find selected mod providing '{req}' to remove (its dep '{mid}' is unavailable)")
                        continue
                    target["selected"] = False
                    remove_jar(mods_dir, target["slug"])
                    mod_jars[:] = [m for m in mod_jars if m["slug"] != target["slug"]]
                    logger.ok("repair", f"Removed {target['slug']} — '{mid}' (required by '{req}') is not available on any provider")
        elif action["action"] == "change-version":
            if not prov:
                return
            for c in action.get("conflicts") or []:
                try:
                    mid = c["id"]
                    target = selection_by_mod_id(mid)
                    if not target:
                        logger.warn("repair", f"change-version: no selected mod provides '{mid}'")
                        continue
                    try:
                        proj = prov.get_project(target["slug"])
                    except Exception:
                        proj = None
                    if not proj:
                        proj = _loose_resolve(prov, mid, env)
                    if not proj:
                        logger.warn("repair", f"change-version: cannot resolve '{mid}'")
                        continue
                    versions = prov.get_versions(proj["projectId"], {
                        "minecraftVersion": env["mcVersion"],
                        "loaders": None if env["loader"] == "vanilla" else [env["loader"]],
                    }) or []
                    if not versions:
                        logger.warn("repair", f"change-version: no {env['mcVersion']}/{env['loader']} versions of '{mid}'")
                        continue
                    # pick the newest version that satisfies the required range
                    best = None
                    for v in versions:
                        if version_satisfies(v.get("versionNumber", ""), c.get("expected")):
                            best = v
                            break
                    if not best:
                        logger.warn("repair", f"change-version: no version of '{mid}' satisfies '{c.get('expected')}'")
                        continue
                    f = next((x for x in best.get("files") or [] if x.get("primary")), (best.get("files") or [None])[0])
                    if not f or not f.get("url"):
                        continue
                    dest = Path(env["buildDir"]) / "downloads" / "mods" / sanitize_filename(f"{proj['slug']}-{best['versionNumber']}.jar", "mod.jar")
                    if not dest.exists():
                        download_to_file(f["url"], dest, max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                                         expected_sha1=(f.get("hashes") or {}).get("sha1"), timeout_ms=300000,
                                         headers=cf_download_headers(f["url"]))
                    old = target.get("versionNumber")
                    target["versionId"] = best.get("versionId")
                    target["versionNumber"] = best.get("versionNumber")
                    target["filename"] = f.get("filename")
                    target["downloadPath"] = str(dest)
                    target["reason"] = f"Version bumped by repair: {old} -> {best['versionNumber']} to satisfy {c.get('expected')}"
                    for m in mod_jars:
                        if m["slug"] == target["slug"]:
                            m["path"] = str(dest)
                    shutil.copyfile(dest, mods_dir / sanitize_filename(target["slug"] + ".jar", "mod.jar"))
                    logger.ok("repair", f"{target['slug']}: {old} -> {best['versionNumber']} (required {c.get('expected')})")
                except Exception as e:
                    logger.warn("repair", f"change-version failed for {c.get('id')}: {e}")
        elif action["action"] == "remove":
            slug = action["slug"]
            removed = False
            for s in rec["selections"]:
                if s["slug"] == slug and s.get("selected", True):
                    s["selected"] = False
                    removed = True
            if not removed:
                logger.warn("repair", f"Repair wanted to remove {slug} but it is not selected")
                return
            remove_jar(mods_dir, slug)
            mod_jars[:] = [m for m in mod_jars if m["slug"] != slug]
            logger.ok("repair", f"Removed {slug}")
            # Cascade: any selected mod that hard-requires a removed mod id cannot
            # function and would just re-trigger the missing-dependency screen,
            # creating an add/remove ping-pong (e.g. Origins requires connectormod
            # which only Sinytra Connector provides, and connector itself crashes).
            removed_ids = set()
            # Find the removed jar via its selection's downloadPath (the downloads
            # dir uses versioned filenames, so a direct slug-based path won't exist).
            for s in rec["selections"]:
                if s["slug"] == slug and s.get("downloadPath") and Path(s["downloadPath"]).exists():
                    try:
                        meta = read_jar_metadata(s["downloadPath"])
                        if meta and meta.get("id"):
                            removed_ids.add(norm_id(meta["id"]))
                        removed_ids.update(norm_id(x) for x in provided_mod_ids(s["downloadPath"]))
                    except Exception:
                        pass
                    break
            removed_ids.discard("")
            if removed_ids:
                # 1. Error-screen requesters: Forge tells us exactly who needs the
                # removed mod's id ("Mod ID: 'connectormod', Requested by: 'origins'").
                # This catches Fabric mods running through a removed connector —
                # their jar metadata (fabric.mod.json) never mentions connectormod.
                # Use the accumulated map (the screen may have been from an earlier
                # launch than the current crash log).
                req_map = rec.get("_depRequesters") or missing_requesters(log_text())
                doomed = set()
                for rid in list(removed_ids):
                    for req in req_map.get(rid, []):
                        doomed.add(req)
                for req in doomed:
                    t = selection_by_mod_id(req)
                    if not t:
                        continue
                    t["selected"] = False
                    remove_jar(mods_dir, t["slug"])
                    mod_jars[:] = [m for m in mod_jars if m["slug"] != t["slug"]]
                    try:
                        m2 = read_jar_metadata(t["downloadPath"])
                        if m2 and m2.get("id"):
                            removed_ids.add(norm_id(m2["id"]))
                        removed_ids.update(norm_id(x) for x in provided_mod_ids(t["downloadPath"]))
                    except Exception:
                        pass
                    logger.ok("repair", f"Removed {t['slug']} (cascade: requires removed dependency '{req}')")
                # 2. Jar-metadata cascade: hard depends on any removed id.
                changed = True
                while changed:
                    changed = False
                    for s in [x for x in rec["selections"] if x.get("selected", True) and x.get("projectType") == "mod" and x.get("slug") != slug]:
                        if not s.get("downloadPath") or not Path(s["downloadPath"]).exists():
                            continue
                        try:
                            meta = read_jar_metadata(s["downloadPath"])
                            reqs = [norm_id(d.get("id", "")) for d in (meta or {}).get("depends", [])]
                        except Exception:
                            continue
                        if any(r in removed_ids for r in reqs if r):
                            s["selected"] = False
                            remove_jar(mods_dir, s["slug"])
                            mod_jars[:] = [m for m in mod_jars if m["slug"] != s["slug"]]
                            try:
                                m2 = read_jar_metadata(s["downloadPath"])
                                if m2 and m2.get("id"):
                                    removed_ids.add(norm_id(m2["id"]))
                                removed_ids.update(norm_id(x) for x in provided_mod_ids(s["downloadPath"]))
                            except Exception:
                                pass
                            logger.ok("repair", f"Removed {s['slug']} (cascade: requires removed dependency '{next((r for r in reqs if r in removed_ids), '?')}')")
                            changed = True

    # ------------------------------------------------------------------
    # provider / mod browser
    # ------------------------------------------------------------------
    def provider_status(self, probe: bool = False) -> dict:
        providers = build_providers(self.settings_store)
        out = []
        for p in providers:
            status = {"provider": p.name, "available": p.available}
            if not p.available:
                status["error"] = getattr(p, "unavailable_reason", "unavailable")
            elif probe:
                try:
                    r = p.search({"query": "create", "projectType": "mod", "limit": 1})
                    status["ok"] = len(r) > 0
                    status["error"] = None if len(r) > 0 else "search returned zero results"
                except Exception as e:
                    status["ok"] = False
                    status["error"] = str(e)
            else:
                status["ok"] = True
            out.append(status)
        return {"sources": out}

    @staticmethod
    def _page_size_for(prov, page_size: int) -> int:
        """Per-provider page-size cap so merged pages align: CurseForge's API
        hard-caps pageSize at 50, Modrinth allows up to 100. Every provider
        gets its own limit; the merged page size is their sum."""
        cap = 50 if prov.name == "curseforge" else 100
        return max(1, min(int(page_size or 48), cap))

    # sort keys understood by every source; "name" falls back to a client-side
    # title sort because Modrinth has no server-side name index.
    SORT_KEYS = ("downloads", "updated", "name")

    def search(self, q: str = "", provider: str = "modrinth", mc: str = None,
               loader: str = None, type: str = "mod", offset: int = 0,
               page_size: int = 48, sort: str = "downloads") -> dict:
        providers = self._cached_providers()
        mc_f = mc if mc and mc != "auto" else None
        loaders = [loader] if loader and loader not in ("all", "auto") else None
        sort = sort if sort in self.SORT_KEYS else "downloads"

        # Worlds exist only on CurseForge (class 17) — route there exclusively.
        if type == "world":
            cf = next((p for p in providers if p.name == "curseforge"), None)
            ps = self._page_size_for(cf, page_size) if cf else page_size
            if not cf or not cf.available:
                return {"provider": "curseforge", "hits": [], "browse": not bool(q),
                        "page_size": ps, "more": False, "total": 0,
                        "error": "Missing CurseForge API key — worlds require the CurseForge catalog.",
                        "sources": [{"provider": "curseforge", "ok": False, "count": 0,
                                     "available": bool(cf and cf.available),
                                     "error": getattr(cf, "unavailable_reason", None) or "not configured"}]}
            try:
                meta = cf.search_meta({"query": q, "projectType": "world",
                                       "minecraftVersion": mc_f, "loaders": loaders,
                                       "limit": ps, "offset": offset,
                                       "sort": sort}) or {}
                hits = self._apply_sort(meta.get("hits") or [], sort)
                total = int(meta.get("total") or 0)
                return {"provider": "curseforge", "hits": hits, "browse": not bool(q),
                        "page_size": ps,
                        "more": bool(total and offset + ps < total) or (not total and len(hits) >= ps),
                        "total": total,
                        "sources": [{"provider": "curseforge", "ok": True, "count": len(hits),
                                     "total": total, "available": True, "error": None}]}
            except Exception as e:
                return {"provider": "curseforge", "hits": [], "browse": not bool(q),
                        "page_size": ps, "more": False, "total": 0, "error": str(e)}

        if provider == "all":
            # Query every available source in parallel and merge, so the
            # combined catalog is a single round trip instead of N. Each
            # provider is queried with ITS OWN page size (CurseForge caps at
            # 50, Modrinth can return more) so merged pages stay aligned;
            # `more` reports whether any source returned a full page.
            import concurrent.futures
            wanted = [p for p in providers if p.available]
            sizes = {p.name: self._page_size_for(p, page_size) for p in wanted}
            merged_page = sum(sizes.values()) or page_size
            page = (offset // merged_page) if merged_page else 0
            results: dict = {}
            if wanted:
                with concurrent.futures.ThreadPoolExecutor(max_workers=len(wanted)) as pool:
                    futs = {pool.submit(p.search_meta, {"query": q, "projectType": type,
                                                        "minecraftVersion": mc_f, "loaders": loaders,
                                                        "limit": sizes[p.name],
                                                        "offset": page * sizes[p.name],
                                                        "sort": sort}): p for p in wanted}
                    for fut in concurrent.futures.as_completed(futs):
                        prov = futs[fut]
                        try:
                            results[prov.name] = (True, fut.result() or {})
                        except Exception as e:  # noqa: BLE001
                            results[prov.name] = (False, str(e))
            merged, seen = [], set()
            sources = []
            more = False
            total = 0
            for prov in providers:
                if not prov.available:
                    sources.append({"provider": prov.name, "ok": False, "count": 0,
                                    "available": False,
                                    "error": getattr(prov, "unavailable_reason", None) or "not configured"})
                    continue
                ok, val = results.get(prov.name, (False, "timed out"))
                if ok:
                    meta = val if isinstance(val, dict) else {}
                    meta_hits = meta.get("hits") or []
                    meta_total = int(meta.get("total") or 0)
                    if meta_total:
                        total += meta_total
                        # A real total exists: more results exist exactly when
                        # the current page hasn't consumed the whole catalog.
                        if (page + 1) * sizes[prov.name] < meta_total:
                            more = True
                    elif len(meta_hits) >= sizes[prov.name]:
                        more = True
                    sources.append({"provider": prov.name, "ok": True, "count": len(meta_hits),
                                    "total": meta_total, "available": True, "error": None})
                    for h in meta_hits:
                        key = (h.get("provider"), h.get("projectId"))
                        if key in seen:
                            continue
                        seen.add(key)
                        merged.append(h)
                else:
                    sources.append({"provider": prov.name, "ok": False, "count": 0,
                                    "available": True, "error": str(val)})
            merged = self._apply_sort(merged, sort)
            if not wanted:
                return {"provider": "all", "hits": [], "browse": not bool(q),
                        "page_size": page_size, "more": False, "total": 0,
                        "error": "no provider available", "sources": sources}
            return {"provider": "all", "hits": merged[:merged_page], "browse": not bool(q),
                    "page_size": merged_page, "more": more, "total": total, "sources": sources}

        prov = next((p for p in providers if p.name == provider and p.available), None)
        if not prov:
            prov = next((p for p in providers if p.available and p.name == "modrinth"), None)
        ps = self._page_size_for(prov, page_size) if prov else page_size
        if not prov:
            return {"error": "no provider available", "hits": [], "provider": provider,
                    "page_size": ps, "more": False, "total": 0}
        try:
            meta = prov.search_meta({
                "query": q, "projectType": type,
                "minecraftVersion": mc_f, "loaders": loaders,
                "limit": ps, "offset": offset,
                "sort": sort,
            }) or {}
            hits = self._apply_sort(meta.get("hits") or [], sort)
            total = int(meta.get("total") or 0)
            return {"provider": prov.name, "hits": hits, "browse": not bool(q),
                    "page_size": ps,
                    "more": bool(total and offset + ps < total) or (not total and len(hits) >= ps),
                    "total": total,
                    "sources": [{"provider": prov.name, "ok": True, "count": len(hits),
                                 "total": total, "available": True, "error": None}]}
        except Exception as e:
            return {"provider": prov.name, "hits": [], "page_size": ps, "more": False,
                    "total": 0, "error": str(e)}

    @staticmethod
    def _apply_sort(hits: list, sort: str) -> list:
        """Client-side sort. Server-side sort keys are passed to each provider;
        this re-orders the merged page for consistency and provides the name
        fallback (Modrinth has no server-side title index)."""
        items = list(hits)
        if sort == "name":
            items.sort(key=lambda h: str(h.get("title") or "").lower())
        elif sort == "updated":
            items.sort(key=lambda h: h.get("dateModified") or h.get("dateCreated") or "",
                       reverse=True)
        else:  # downloads (default)
            items.sort(key=lambda h: h.get("downloads") or 0, reverse=True)
        return items

    def project_details(self, provider: str, project_id: str, mc: str = None,
                        loader: str = None) -> dict:
        providers = build_providers(self.settings_store)
        prov = next((p for p in providers if p.name == provider and p.available), None)
        if not prov:
            return {"error": "provider not available"}
        proj = prov.get_project(project_id)
        versions = []
        try:
            versions = prov.get_versions(project_id, {
                "minecraftVersion": mc if mc and mc != "auto" else None,
                "loaders": [loader] if loader and loader not in ("all", "auto") else None,
            }) or []
        except Exception as e:
            versions = []
        return {"project": proj, "versions": versions, "provider": provider, "loaders": ["forge", "fabric", "neoforge", "quilt"]}

    def add_mod(self, build_id: str, provider: str, project_id: str,
                version_id: str = None, type: str = None) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        providers = build_providers(self.settings_store)
        prov = next((p for p in providers if p.name == provider and p.available), None)
        if not prov:
            raise RuntimeError(f"Provider {provider} unavailable")
        proj = prov.get_project(project_id)
        if not proj:
            raise RuntimeError("project not found")
        mc = rec.get("requirements", {}).get("minecraftVersion") or "1.20.1"
        loader = rec.get("requirements", {}).get("loader") or "fabric"
        if mc == "auto":  # belt-and-braces for legacy records created before resolution
            settings = self.settings_store.load()
            d = (settings.get("defaults") or {}).get("minecraftVersion")
            mc = d if d and d != "auto" else "1.20.1"
        if loader == "auto":
            settings = self.settings_store.load()
            d = (settings.get("defaults") or {}).get("loader")
            loader = d if d and d != "auto" else "fabric"
        versions = prov.get_versions(project_id, {
            "minecraftVersion": mc, "loaders": None if loader == "vanilla" else [loader],
        }) or []
        v = next((x for x in versions if x["versionId"] == version_id), versions[0] if versions else None)
        if not v:
            raise RuntimeError(f"No {mc}/{loader} version for {proj['title']}")
        f = next((x for x in v.get("files") or [] if x.get("primary")), (v.get("files") or [None])[0])
        key = f"{proj['provider']}:{proj['projectId']}"
        rec.setdefault("selections", [])
        rec["selections"].append({
            "key": key, "provider": proj["provider"], "projectId": proj["projectId"],
            "slug": proj["slug"], "title": proj["title"], "description": proj.get("description", ""),
            "projectType": proj.get("projectType", "mod") if not type else type,
            "versionId": v["versionId"], "versionNumber": v.get("versionNumber"),
            "filename": f.get("filename") if f else None, "featureIds": ["manual"],
            "reason": "Added manually", "clientSide": proj.get("clientSide"),
            "serverSide": proj.get("serverSide"), "selected": True,
        })
        # download the jar if allowed
        if f and f.get("url"):
            from .core import download_to_file
            dest = self._build_dir(build_id) / "downloads" / "mods" / sanitize_filename(f"{proj['slug']}-{v['versionNumber']}.jar", "mod.jar")
            if not dest.exists():
                download_to_file(f["url"], dest, max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                                 expected_sha1=(f.get("hashes") or {}).get("sha1"), timeout_ms=300000,
                                 headers=cf_download_headers(f["url"]))
            rec["selections"][-1]["downloadPath"] = str(dest)
            # install into instance
            mods_dir = self._build_dir(build_id) / "instance" / "minecraft" / "mods"
            mkdirp(mods_dir)
            shutil.copyfile(dest, mods_dir / sanitize_filename(proj["slug"] + ".jar", "mod.jar"))
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {"ok": True, "added": rec["selections"][-1]}

    def remove_mod(self, build_id: str, slug: str, type: str = None) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        changed = False
        for s in rec.get("selections") or []:
            if s.get("slug") == slug and s.get("selected", True):
                s["selected"] = False
                changed = True
        if changed:
            from .instance import remove_jar
            remove_jar(self._build_dir(build_id) / "instance" / "minecraft" / "mods", slug)
            rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._write_record(rec)
        return {"ok": True, "removed": changed}

    def retest(self, build_id: str) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        logger = BuildLogger(build_id, self._build_dir(build_id))
        req = rec.get("requirements") or {}
        settings = rec.get("settings") or {}
        mod_jars = []
        visuals = {"resourcePackFiles": [], "shaderFiles": []}
        for s in rec.get("selections") or []:
            if not s.get("selected", True) or not s.get("downloadPath"):
                continue
            if s.get("projectType") == "mod" and Path(s["downloadPath"]).exists():
                mod_jars.append({"slug": s["slug"], "path": s["downloadPath"], "featureIds": s.get("featureIds") or []})
            elif s.get("projectType") == "shader" and Path(s["downloadPath"]).exists():
                visuals["shaderFiles"].append(s["downloadPath"])
            elif s.get("projectType") == "resourcepack" and Path(s["downloadPath"]).exists():
                visuals["resourcePackFiles"].append(s["downloadPath"])
        env = {
            "buildId": build_id, "buildDir": str(self._build_dir(build_id)),
            "gameDir": str(self._build_dir(build_id) / "instance" / "minecraft"),
            "mcVersion": req.get("minecraftVersion") or "1.20.1",
            "loader": req.get("loader") or "fabric",
            "testMode": req.get("testMode") or "standard", "logger": logger,
            "xmxMB": fit_xmx_mb(req.get("ramGB") or 8),
            "modJars": mod_jars,
            "resourcePackFiles": visuals["resourcePackFiles"], "shaderFiles": visuals["shaderFiles"],
            "downloadAssets": settings.get("downloadAssets", False),
            "maxAssetMB": settings.get("maxAssetMB", 400),
            "autoInstallJava": settings.get("autoInstallJava", True),
        }
        graph = rec.get("graph") or {"nodes": {}, "edges": []}
        t = threading.Thread(target=lambda: self._run_retest(build_id, rec, env, graph), daemon=True)
        t.start()
        return {"ok": True, "buildId": build_id}

    def _run_retest(self, build_id, rec, env, graph):
        logger = BuildLogger(build_id, self._build_dir(build_id))
        try:
            test_result = run_test_level(env, graph)
            rec["testResult"] = test_result
            rec["tests"] = rec.get("tests") or []
            rec["tests"].append(test_result)
            rec["status"] = "done" if test_result["status"] == "PASS" else "failed"
            rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self._write_record(rec)
            if test_result["status"] == "PASS":
                try:
                    mark_last_known_good(self._build_dir(build_id),
                                         self._attach_identity(self._read_record(build_id) or rec))
                except Exception:  # noqa: BLE001
                    pass
        except Exception as e:
            logger.error("test", f"Retest failed: {e}")

    # ------------------------------------------------------------------
    # launcher
    # ------------------------------------------------------------------
    def play(self, build_id: str, username: str = None, auth: dict = None,
             auto_launch: bool = False) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        logger = BuildLogger(build_id, self._build_dir(build_id))
        session = None
        if auth and auth.get("username") and auth.get("accessToken"):
            session = {"username": auth["username"], "uuid": auth.get("uuid") or uid(""),
                       "accessToken": auth["accessToken"], "userType": "msa"}
        rec["_buildDir"] = str(self._build_dir(build_id))
        handle = launch_pack(rec, {
            "buildDir": str(self._build_dir(build_id)), "logger": logger,
            "username": username or (auth or {}).get("username") or "Player",
            "session": session,
            "autoRelaunch": auto_launch or bool((rec.get("settings") or {}).get("autoRelaunch")),
        })
        rec["launchPhase"] = "loading"
        rec["running"] = True
        self._write_record(rec)
        return {"ok": True, "pid": handle["pid"], "buildId": build_id}

    def stop(self, build_id: str) -> dict:
        stopped = stop_pack(build_id)
        rec = self._read_record(build_id)
        if rec:
            rec["running"] = False
            self._write_record(rec)
        return {"ok": True, "stopped": stopped}

    def status(self, build_id: str) -> dict:
        st = play_state(build_id, str(self._build_dir(build_id)))
        if not st:
            return {"ok": True, "running": False, "phase": "stopped"}
        return {"ok": True, **st, "running": st.get("phase") in ("loading", "running", "preparing", "installing")}

    def fix(self, build_id: str, username: str = None, auth: dict = None) -> dict:
        return self.add_missing(build_id, mods=None, username=username, auth=auth)

    def add_missing(self, build_id: str, mods: list = None, username: str = None,
                    auth: dict = None) -> dict:
        rec = self._read_record(build_id)
        if not rec:
            raise KeyError("build not found")
        logger = BuildLogger(build_id, self._build_dir(build_id))
        gd = self._build_dir(build_id) / "instance" / "minecraft"
        ev = collect_launch_evidence(str(gd), str(self._build_dir(build_id) / "logs" / "launch-play.log"))
        missing = mods or ev["missingDeps"]
        if not missing:
            from .instance import collect_instance_logs
            logs = collect_instance_logs(gd)
            text = "\n".join(logs["latest"] + logs["crashReports"] + logs["debug"])
            missing = missing_dep_ids(text)
        if not missing:
            return {"ok": True, "added": [], "note": "no missing dependencies detected"}
        settings = rec.get("settings") or {}
        env = {
            "buildId": build_id, "buildDir": str(self._build_dir(build_id)),
            "gameDir": str(gd), "mcVersion": rec["requirements"]["minecraftVersion"],
            "loader": rec["requirements"]["loader"], "testMode": "standard", "logger": logger,
            "xmxMB": 4096, "modJars": [], "resourcePackFiles": [], "shaderFiles": [],
            "downloadAssets": False, "maxAssetMB": 400, "autoInstallJava": True,
        }
        mod_jars = []
        for s in rec.get("selections") or []:
            if s.get("selected", True) and s.get("projectType") == "mod" and s.get("downloadPath") and Path(s["downloadPath"]).exists():
                mod_jars.append({"slug": s["slug"], "path": s["downloadPath"], "featureIds": s.get("featureIds") or []})
        action = {"action": "add-missing", "mods": missing,
                  "reason": f"User-confirmed missing dependency add: {', '.join(missing)}",
                  "signature": "missing-dependency"}
        self._apply_repair(action, rec, {"fileByKey": {}}, mod_jars, env,
                           self._build_dir(build_id) / "instance" / "minecraft" / "mods", logger)
        rec["repairs"] = rec.get("repairs") or []
        rec["repairs"].append(action)
        self._write_record(rec)
        return {"ok": True, "added": missing, "relaunch": True}

    def backup(self, build_id: str) -> dict:
        src = self._build_dir(build_id) / "instance" / "minecraft" / "saves"
        dst = self._build_dir(build_id) / "backups" / time.strftime("world-%Y%m%d-%H%M%S")
        if src.is_dir():
            shutil.copytree(src, dst)
            return {"ok": True, "path": str(dst)}
        return {"ok": True, "note": "no worlds to back up"}

    # ------------------------------------------------------------------
    # import
    # ------------------------------------------------------------------
    def import_pack(self, provider: str, project_id: str, version_id: str = None,
                    progress: object = None, cancel: object = None) -> dict:
        """Import a provider modpack (Modrinth .mrpack / CurseForge ZIP).

        Downloads the modpack's own archive, then installs the mods it
        references (hash-verified) so the imported pack actually contains its
        mods. progress(stage, done, total) and cancel (threading.Event) are
        cooperative hooks for the import overlay.
        """
        from .imports import import_mrpack, import_curseforge
        providers = build_providers(self.settings_store, sources=[provider],
                                    opts={"allowCfDirect": True})
        prov = next((p for p in providers if p.name == provider and p.available), None)
        if not prov:
            raise RuntimeError(f"Provider {provider} unavailable")
        proj = prov.get_project(project_id)
        if not proj:
            raise RuntimeError("project not found")
        versions = prov.get_versions(project_id) or []
        v = next((x for x in versions if x["versionId"] == version_id), versions[0] if versions else None)
        if not v:
            raise RuntimeError("no versions found")
        f = prov.get_download_file(v)
        if not f or not f.get("url"):
            raise RuntimeError(
                f"{provider} does not allow direct modpack downloads here — "
                f"{'add a CurseForge API key on Settings' if provider == 'curseforge' else 'provider returned no download'}")
        rec = self.create_pack(name=proj["title"],
                               mc=(v.get("gameVersions") or ["1.20.1"])[0],
                               loader=(v.get("loaders") or ["fabric"])[0])
        bdir = self._build_dir(rec["buildId"])
        rec["request"] = f"Imported {proj['title']} from {provider}"
        dl_dir = bdir / "imports"
        mkdirp(dl_dir)
        ext = ".mrpack" if provider == "modrinth" else ".zip"
        archive_path = dl_dir / sanitize_filename(f"{proj['slug']}{ext}", "pack" + ext)
        if progress:
            progress("Downloading modpack archive", 0, 1)
        download_to_file(f["url"], archive_path,
                         max_bytes=max(int(f.get("size") or 0) * 2 + 1024 * 1024, 100 * 1024 ** 2),
                         expected_sha1=(f.get("hashes") or {}).get("sha1"),
                         timeout_ms=600000,
                         headers=cf_download_headers(f["url"]))
        if progress:
            progress("Downloading modpack archive", 1, 1)
        if provider == "modrinth":
            res = import_mrpack(rec, archive_path, bdir, prov, progress=progress, cancel=cancel)
        else:
            res = import_curseforge(rec, archive_path, bdir, prov, progress=progress, cancel=cancel)
        return self._finalize_import(rec, res)

    def import_file(self, local_path: str, name: str = None,
                    progress: object = None, cancel: object = None) -> dict:
        """Import a local .mrpack / CurseForge ZIP with its real mods."""
        from .imports import detect_archive, import_mrpack, import_curseforge
        p = Path(local_path)
        if not p.exists():
            raise RuntimeError(f"file not found: {p}")
        kind = detect_archive(p)
        providers = build_providers(self.settings_store,
                                    sources=["modrinth" if kind == "mrpack" else "curseforge"],
                                    opts={"allowCfDirect": True})
        prov = providers[0] if providers else None
        rec = self.create_pack(name=name or p.stem)
        rec["request"] = f"Imported {p.name}"
        bdir = self._build_dir(rec["buildId"])
        if kind == "mrpack":
            res = import_mrpack(rec, p, bdir, prov, progress=progress, cancel=cancel)
        else:
            res = import_curseforge(rec, p, bdir, prov, progress=progress, cancel=cancel)
        return self._finalize_import(rec, res)

    def _finalize_import(self, rec: dict, res: dict) -> dict:
        """Persist an import result (or clean up on cancel)."""
        if res.get("cancelled"):
            self.delete_pack(rec["buildId"])
            return {"ok": False, "cancelled": True, "buildId": rec["buildId"]}
        mods = [s for s in res.get("selections") or [] if s.get("projectType") == "mod"]
        rec["selections"] = res.get("selections") or []
        rec["packStats"] = {"modCount": len(mods)}
        rec["status"] = "done"
        rec["phase"] = "done"
        rec["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self._write_record(rec)
        return {
            "ok": True, "buildId": rec["buildId"], "name": rec["name"],
            "modCount": len(mods), "kind": res.get("kind"),
            "downloaded": res.get("downloaded", 0),
            "references": res.get("references", 0),
            "failed": res.get("failed", 0),
            "overrides": res.get("overrides", 0),
            "total": res.get("total", 0),
        }

    # ------------------------------------------------------------------
    # events + live game log
    # ------------------------------------------------------------------
    def events(self, build_id: str):
        """Generator yielding events as they happen (history first, then live)."""
        queue = []
        evt = threading.Event()
        sub = EVENT_BUS.subscribe(lambda ev: (queue.append(ev), evt.set()))
        try:
            for ev in EVENT_BUS.history_for(build_id):
                yield ev
            while True:
                evt.wait(timeout=3)
                evt.clear()
                while queue:
                    ev = queue.pop(0)
                    if ev.get("buildId") == build_id:
                        yield ev
                rec = self._read_record(build_id)
                if rec and rec.get("status") in ("done", "failed", "error") and not queue:
                    yield {"buildId": build_id, "ts": int(time.time() * 1000), "level": "ok",
                           "stage": "report", "message": f"Build {rec['status']}", "progress": 100,
                           "status": rec["status"]}
                    return
        finally:
            sub()

    def game_log_stream(self, build_id: str):
        """Live stream of the game's logs while the pack runs.

        Yields typed events as they are appended (offset-based, so lines are
        delivered once, never replayed):
          {"type": "line",  "src": "game"|"launcher", "line": ...}
          {"type": "crash", "line": "\u26a0 CRASH DETECTED — …", "stage": …,
                             "file": "crash-reports/…txt" (when a report appears)}
          {"type": "menu",  "line": "\u2714 Main menu reached"}
        Ends when the pack stops running.
        """
        offsets = {}
        seen_crash = set()
        menu_sent = [False]
        game_tail = []  # rolling buffer of THIS run's streamed game lines
        ever_running = [False]
        idle_since = [time.time()]
        while True:
            gd = self._build_dir(build_id) / "instance" / "minecraft"
            log = self._build_dir(build_id) / "logs" / "launch-play.log"
            running = is_running(build_id)
            if running:
                ever_running[0] = True
            for rel, src in (("logs/latest.log", "game"), ("logs/debug.log", "game"),
                             ("launch-play.log", "launcher")):
                p = gd / rel if rel.startswith("logs/") else log
                try:
                    if not p.exists():
                        continue
                    st = p.stat()
                    size = st.st_size
                    start = offsets.get(rel)
                    if start is None:
                        # First sighting: only stream lines appended from now on,
                        # never stale content from a previous launch.
                        offsets[rel] = size
                        continue
                    if size < start:
                        start = 0  # the game rotated/truncated the file
                    if size == start:
                        continue
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(start)
                        chunk = fh.read()
                    offsets[rel] = size
                    lines = [l for l in chunk.splitlines() if l.strip()]
                    for line in lines:
                        yield {"type": "line", "src": src, "line": line}
                        if src == "game":
                            game_tail.append(line)
                            if len(game_tail) > 500:
                                del game_tail[: len(game_tail) - 500]
                            if not menu_sent[0] and main_menu_reached(game_tail):
                                menu_sent[0] = True
                                yield {"type": "menu", "line": "\u2714 Main menu reached"}
                    if src == "game" and lines and fatal_startup_detected(lines):
                        stage = _error_stage(lines)
                        yield {"type": "crash",
                               "line": f"\u26a0 CRASH DETECTED — {stage}",
                               "stage": stage}
                except OSError:
                    continue
            # New crash reports written since the stream attached.
            try:
                crash_dir = gd / "crash-reports"
                if crash_dir.is_dir():
                    for f in sorted(crash_dir.iterdir()):
                        if f.name.endswith(".txt") and f.name not in seen_crash:
                            seen_crash.add(f.name)
                            yield {"type": "crash",
                                   "line": f"\u26a0 Crash report written: {f.name}",
                                   "file": "crash-reports/" + f.name}
            except OSError:
                pass
            # End when the pack STOPPED after having run; wait (up to a couple
            # of minutes) if it has not started yet — the UI may attach the
            # stream just before play() spawns the game.
            if ever_running[0] and not running:
                return
            if not running and time.time() - idle_since[0] > 180:
                return
            time.sleep(0.8)

    # ------------------------------------------------------------------
    # report
    # ------------------------------------------------------------------
    def _build_report(self, rec, test_result, conf, issues, repairs) -> str:
        lines = [
            f"## {rec['name']}",
            f"- Build: {rec['buildId']}",
            f"- Status: {test_result['status']} ({test_result.get('summary', '')})",
            f"- Test mode: {(rec['requirements'] or {}).get('testMode', 'standard')}",
        ]
        ps = rec.get("packStats") or {}
        if ps.get("modCount"):
            lines.append(f"- Mods: {ps['modCount']}")
        sc = rec.get("shaderChoice")
        if sc:
            if sc.get("title"):
                prov = f" via {sc['provider']}" if sc.get("provider") else ""
                lines.append(f"- Shader: {sc['title']} ({sc['preset']} preset on {sc.get('gpuTier')} GPU{prov})")
            else:
                lines.append(f"- Shader: none ({sc.get('reason', '')})")
        rpc = rec.get("resourcePackChoice")
        if rpc:
            if rpc.get("title"):
                prov = f" via {rpc['provider']}" if rpc.get("provider") else ""
                lines.append(f"- Resource pack: {rpc['title']} ({rpc['resolution']}x tier{prov})")
            else:
                lines.append(f"- Resource pack: none ({rpc.get('reason', '')})")
        phases = test_result.get("phases") or []
        if phases:
            lines.append("- Tests:")
            for p in phases:
                n = p.get("name", "?")
                s = p.get("status", "?")
                d = p.get("detail", "")
                lines.append(f"  - {n}: {s}" + (f" — {d}" if d else ""))
        if conf:
            cfs = [c for c in conf.get("conflicts") or [] if not c.get("resolved")]
            if cfs:
                lines.append(f"- {len(cfs)} unresolved conflicts:")
                for c in cfs[:5]:
                    lines.append(f"  - {c.get('type')}: {c.get('description', '')}")
        if repairs:
            lines.append(f"- Repairs: {len(repairs)}")
            for r_ in repairs[:3]:
                lines.append(f"  - {r_.get('action')}: {r_.get('reason', '')}")
        return "\n".join(lines)


def _auto_name(prompt: str) -> str:
    words = prompt.split()
    for i, w in enumerate(words):
        if w.lower() in ("modpack", "pack", "minecraft") and i > 0:
            return " ".join(words[:i]).title()[:48]
    return " ".join(words[:6]).title()[:48]


def _loose_resolve(prov, id_, env):
    from .reconcile import loose_resolve_project
    return loose_resolve_project(prov, id_, {
        "minecraftVersion": env["mcVersion"],
        "loaders": None if env["loader"] == "vanilla" else [env["loader"]],
    })
