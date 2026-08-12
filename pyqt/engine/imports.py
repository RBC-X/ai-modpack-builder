"""Real modpack import: Modrinth .mrpack and CurseForge ZIP archives.

A .mrpack does NOT contain its mods: `modrinth.index.json` lists each file by
URL + hashes and the jars are downloaded from the Modrinth CDN. A CurseForge
ZIP is the same — `manifest.json` references {projectID, fileID} pairs that
must be resolved through the CurseForge API. This module downloads the real
files (hash-verified), extracts overrides, and records every mod as a
first-class selection so the Pack Inspector shows the pack it actually
contains.

Honest limits: CurseForge files are downloadUrl-less for most API keys (CF
policy), so those are recorded as manifest references with a download attempt
only when a signed URL is available. Nothing is faked — counts report exactly
what happened.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Optional

from .core import download_to_file, mkdirp, sanitize_filename
from .providers.curseforge import CurseForgeScopeError, cf_download_headers
from .providers.http import provider_get
from .providers.modrinth import BASE as MR_BASE

ProgressFn = Callable[[str, int, int], None]
CancelFn = Optional[Callable[[], bool]]


def _cancelled(cancel: Optional[object]) -> bool:
    return bool(cancel is not None and getattr(cancel, "is_set", lambda: False)())


def detect_archive(zip_path: Path) -> str:
    """Return 'mrpack' | 'curseforge' from the archive's own manifest."""
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
    if "modrinth.index.json" in names:
        return "mrpack"
    if "manifest.json" in names:
        return "curseforge"
    raise RuntimeError(
        "not a recognized modpack archive (missing modrinth.index.json or manifest.json)")


def _extract_overrides(zf: zipfile.ZipFile, game_dir: Path) -> int:
    """Extract overrides/ safely (path-traversal guarded) into the game dir."""
    count = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        fn = info.filename
        if not fn.startswith("overrides/"):
            continue
        rel = fn[len("overrides/"):]
        if not rel or ".." in rel or rel.startswith(("/", "\\")):
            continue
        dest = game_dir / rel
        mkdirp(dest.parent)
        with zf.open(info) as src, open(dest, "wb") as dst:
            shutil.copyfileobj(src, dst)
        count += 1
    return count


def _slug_from_filename(filename: str) -> str:
    stem = Path(filename).name
    for ext in (".jar", ".zip"):
        if stem.endswith(ext):
            stem = stem[: -len(ext)]
            break
    # Strip a trailing version-ish tail ("jei-1.20.1-15.8.0.17" -> "jei").
    stem = re.sub(r"[-_]\d+([._-][\w.-]+)*$", "", stem)
    return sanitize_filename(stem, "imported-mod").replace(" ", "-").lower() or "imported-mod"


def _version_by_hash(sha1: str) -> Optional[dict]:
    """Resolve a mod's real project via Modrinth's version-file hash endpoint."""
    if not sha1:
        return None
    try:
        data = provider_get("modrinth", f"{MR_BASE}/version_file/{sha1}?algorithm=sha1")
    except Exception:  # noqa: BLE001 — enrichment is best-effort
        return None
    if isinstance(data, dict) and data.get("id"):
        return data
    return None


def _selection(prov, version_raw: Optional[dict], dest: Path, archive_name: str,
               project_id: str = "", provider: str = "modrinth",
               version_id: str = "", version_number: str = "",
               reason: str = "") -> dict:
    """Build a selection record, enriched with real project data when known."""
    proj = None
    pid = project_id or (version_raw or {}).get("project_id") or ""
    if pid and prov is not None:  # prov can be None for key-less CurseForge imports
        try:
            proj = prov.get_project(pid)
        except Exception:  # noqa: BLE001
            proj = None
    filename = dest.name
    slug = (proj or {}).get("slug") or _slug_from_filename(filename)
    title = (proj or {}).get("title") or filename
    return {
        "key": f"{provider}:{pid or slug}",
        "provider": provider,
        "projectId": pid,
        "slug": slug,
        "title": title,
        "description": (proj or {}).get("description") or "",
        "projectType": "mod",
        "versionId": (version_raw or {}).get("id") or version_id,
        "versionNumber": (version_raw or {}).get("version_number") or version_number,
        "filename": filename,
        "featureIds": ["import"],
        "reason": reason or f"Imported from {archive_name}",
        "clientSide": (proj or {}).get("clientSide"),
        "serverSide": (proj or {}).get("serverSide"),
        "selected": True,
        # Only a real file gets a download path — a failed/refused download is
        # a reference (empty path), never a phantom jar.
        "downloadPath": str(dest) if dest.exists() else "",
    }


# ---------------------------------------------------------------------------
# Modrinth .mrpack
# ---------------------------------------------------------------------------
def import_mrpack(rec: dict, zip_path: Path, build_dir: Path, prov,
                  progress: Optional[ProgressFn] = None,
                  cancel: Optional[object] = None) -> dict:
    game_dir = build_dir / "instance" / "minecraft"
    mkdirp(game_dir / "mods")
    with zipfile.ZipFile(zip_path) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
        overrides = _extract_overrides(zf, game_dir)
        deps = index.get("dependencies") or {}
        mc = deps.get("minecraft") or "1.20.1"
        loader = "fabric"
        for k in ("fabric-loader", "quilt-loader", "forge", "neoforge"):
            if k in deps:
                loader = k.replace("-loader", "").replace("-", "")
                break
        rec["requirements"]["minecraftVersion"] = mc
        rec["requirements"]["loader"] = loader

        entries = index.get("files") or []
        total = max(len(entries), 1)
        selections: list = []
        downloaded = referenced = failed = skipped = 0
        for i, entry in enumerate(entries):
            if _cancelled(cancel):
                return {"cancelled": True}
            if progress:
                progress("Downloading mods", i, total)
            path = entry.get("path") or ""
            if not path or ".." in path or path.startswith(("/", "\\")):
                skipped += 1
                continue
            dest = game_dir / path
            mkdirp(dest.parent)
            hashes = entry.get("hashes") or {}
            sha1 = str(hashes.get("sha1") or "")
            size = int(entry.get("fileSize") or 0)
            max_bytes = max(size * 2 + 1024 * 1024, 5 * 1024 ** 2)
            ok = False
            for u in (entry.get("downloads") or []):
                try:
                    download_to_file(u, dest, max_bytes=max_bytes, expected_sha1=sha1,
                                     timeout_ms=180000)
                    ok = True
                    break
                except Exception:  # noqa: BLE001 — try the next mirror
                    continue
            if not ok:
                failed += 1
                continue
            downloaded += 1
            selections.append(_selection(
                prov, _version_by_hash(sha1), dest, zip_path.name,
                reason=f"Imported from {zip_path.name}"))
        if progress:
            progress("Extracting overrides", total, total)
    rec["selections"] = selections
    return {"kind": "mrpack", "selections": selections, "downloaded": downloaded,
            "references": referenced, "failed": failed, "skipped": skipped,
            "overrides": overrides, "total": len(entries)}


# ---------------------------------------------------------------------------
# CurseForge ZIP
# ---------------------------------------------------------------------------
def import_curseforge(rec: dict, zip_path: Path, build_dir: Path, cf_prov,
                      progress: Optional[ProgressFn] = None,
                      cancel: Optional[object] = None) -> dict:
    game_dir = build_dir / "instance" / "minecraft"
    mkdirp(game_dir / "mods")
    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        overrides = _extract_overrides(zf, game_dir)
        m = manifest.get("minecraft") or {}
        mc = m.get("version") or "1.20.1"
        loaders = m.get("modLoaders") or []
        loader = "forge"
        if loaders:
            lid = str(loaders[0].get("id") or "")
            loader = lid.split("-")[0] if "-" in lid else (lid or "forge")
        rec["requirements"]["minecraftVersion"] = mc
        rec["requirements"]["loader"] = loader

        files = manifest.get("files") or []
        total = max(len(files), 1)
        selections: list = []
        downloaded = referenced = failed = skipped = 0
        scope_error = None
        for i, f in enumerate(files):
            if _cancelled(cancel):
                return {"cancelled": True}
            if progress:
                progress("Resolving CurseForge files", i, total)
            project_id = str(f.get("projectID") or "")
            file_id = str(f.get("fileID") or "")
            if not project_id or not file_id:
                skipped += 1
                continue
            finfo = {}
            if cf_prov is not None and cf_prov.available:
                try:
                    d = cf_prov._get(f"/mods/{project_id}/files/{file_id}")
                    finfo = (d or {}).get("data") or {}
                except CurseForgeScopeError as e:
                    # Key authenticated but lacks file access — stop and report
                    # the real cause instead of faking every mod as a reference.
                    scope_error = str(e)
                    break
                except Exception:  # noqa: BLE001
                    finfo = {}
            url = finfo.get("downloadUrl") or ""
            sha1 = None
            for h in (finfo.get("hashes") or []):
                if h.get("algo") == 1:
                    sha1 = h.get("value")
                    break
            filename = sanitize_filename(
                finfo.get("fileName") or f"cf-{project_id}-{file_id}.jar",
                f"cf-{project_id}-{file_id}.jar")
            dest = game_dir / "mods" / filename
            if url:
                try:
                    download_to_file(url, dest, max_bytes=max(
                        int(finfo.get("fileLength") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                        expected_sha1=sha1, timeout_ms=180000,
                        headers=cf_download_headers(url))
                    downloaded += 1
                except Exception:  # noqa: BLE001
                    failed += 1
            else:
                # CF policy: no signed URL for this key → manifest reference only.
                referenced += 1
            # Only claim a download path the file actually exists at; a failed
            # download stays visible in the pack (so the user can retry) but is
            # honestly reference-only instead of pointing at a phantom jar.
            selections.append(_selection(
                cf_prov, None, dest, zip_path.name, project_id=project_id,
                provider="curseforge", version_id=file_id,
                version_number=f"file {file_id}",
                reason=(f"Imported from {zip_path.name} (CurseForge)" if dest.exists()
                        else f"Imported from {zip_path.name} (CurseForge) — download failed or reference-only")))
        if progress:
            progress("Extracting overrides", total, total)
    rec["selections"] = selections
    return {"kind": "curseforge", "selections": selections, "downloaded": downloaded,
            "references": referenced, "failed": failed, "skipped": skipped,
            "overrides": overrides, "total": len(files), "error": scope_error}
