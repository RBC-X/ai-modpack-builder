"""Pack snapshots and Last Known Good.

Snapshots are deterministic, content-addressed pack states: a small manifest
JSON (identity, requirements, exact selections with provider/file ids and
hashes, shader/resource-pack choices) plus the *content* of generated config
files stored once in a content-addressed object store
(``snapshots/objects/<sha1>``). A hash alone cannot reconstruct content, so
config bytes are always stored; duplicate content is never stored twice.

**Last Known Good**: whenever a pack validates (a real test passes), a
snapshot is tagged ``lkg``. Future changes that break the pack can restore
it with one call. Exactly one LKG snapshot exists per pack.

Restoring replays the manifest and reconstructs the real instance: config
files are rewritten from the object store, and mod/shader/resource-pack
artifacts are re-materialized from their recorded download paths (verified
by hash) or legally reacquired from the provider when the local copy is
gone.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

from .core import uid
from .identity import apply_intents, derive_identity

SNAPSHOT_DIR = "snapshots"
LKG_KIND = "last-known-good"
OBJECTS_DIR = "objects"
CONFIG_MAX_BYTES = 4 * 1024 * 1024


def snapshot_dir(build_dir: Path) -> Path:
    return build_dir / SNAPSHOT_DIR


def objects_dir(build_dir: Path) -> Path:
    return snapshot_dir(build_dir) / OBJECTS_DIR


def _sha1(b: bytes) -> str:
    import hashlib
    return hashlib.sha1(b).hexdigest()


def _store_object(build_dir: Path, data: bytes) -> str:
    """Content-addressed store: returns the object hash, writing once per pack."""
    digest = _sha1(data)
    obj = objects_dir(build_dir) / digest
    if not obj.exists():
        obj.parent.mkdir(parents=True, exist_ok=True)
        tmp = obj.with_name(f".{digest}.tmp")
        tmp.write_bytes(data)
        tmp.replace(obj)
    return digest


def _config_entries(build_dir: Path) -> dict:
    """rel config path -> sha1 of its stored content object.

    Generated/user config content is *stored* (not just hashed) so a snapshot
    can reconstruct the exact bytes on restore.
    """
    out: dict = {}
    cfg = build_dir / "instance" / "minecraft" / "config"
    try:
        for p in sorted(cfg.rglob("*")):
            if p.is_file() and p.stat().st_size < CONFIG_MAX_BYTES:
                try:
                    data = p.read_bytes()
                except OSError:
                    continue
                rel = str(p.relative_to(cfg)).replace("\\", "/")
                out[rel] = _store_object(build_dir, data)
    except OSError:
        pass
    return out


def _selection_manifest(selection: dict, build_dir: Path) -> dict:
    """The reproducible identity of one selected project + its artifact file."""
    v = selection.get("version") or {}
    f = (v.get("files") or [None])[0] if v.get("files") else None
    artifact = None
    dp = selection.get("downloadPath") or ""
    if dp:
        p = Path(dp)
        if p.is_file():
            try:
                artifact = {
                    "path": str(p), "filename": p.name,
                    "size": p.stat().st_size, "sha1": _sha1(p.read_bytes()),
                }
            except OSError:
                artifact = None
    elif f and f.get("hashes", {}).get("sha1"):
        artifact = {"path": "", "filename": f.get("filename"), "size": 0,
                    "sha1": f["hashes"]["sha1"]}
    return {
        "key": selection.get("key"),
        "provider": selection.get("provider"),
        "projectId": selection.get("projectId"),
        "slug": selection.get("slug"),
        "title": selection.get("title"),
        "projectType": selection.get("projectType", "mod"),
        "versionId": selection.get("versionId") or v.get("versionId"),
        "versionNumber": selection.get("versionNumber") or v.get("versionNumber"),
        "filename": selection.get("filename") or (f.get("filename") if f else None),
        "fileSha1": (f.get("hashes") or {}).get("sha1") if f else selection.get("fileSha1"),
        "featureIds": selection.get("featureIds") or [],
        "reason": selection.get("reason"),
        "score": selection.get("score"),
        "clientSide": selection.get("clientSide"),
        "serverSide": selection.get("serverSide"),
        "downloadPath": selection.get("downloadPath"),
        "locked": bool(selection.get("locked")),
        "artifact": artifact,
    }


def create_snapshot(build_dir: Path, rec: dict, label: str, kind: str = "manual") -> dict:
    """Write a snapshot manifest (config content objects + artifact manifest)
    for the pack state in `rec`.

    Returns the snapshot record (also persisted). Non-destructive: the pack's
    working state is untouched.
    """
    sd = snapshot_dir(build_dir)
    sd.mkdir(parents=True, exist_ok=True)
    sid = uid("snap-")
    req = rec.get("requirements") or {}
    selections = rec.get("selections") or []
    identity = rec.get("identity") or derive_identity(req, rec)
    snap = {
        "snapshotId": sid,
        "label": label,
        "kind": kind,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "buildId": rec.get("buildId"),
        "revision": int(rec.get("revision") or 0),
        "identity": identity,
        "requirements": {
            "minecraftVersion": req.get("minecraftVersion"),
            "loader": req.get("loader"),
            "ramGB": req.get("ramGB"),
            "shaders": bool(req.get("shaders")),
            "shaderQuality": req.get("shaderQuality"),
            "resourcePackResolution": req.get("resourcePackResolution"),
            "multiplayer": bool(req.get("multiplayer")),
        },
        "selections": [_selection_manifest(s, build_dir) for s in selections],
        "shaderChoice": rec.get("shaderChoice"),
        "resourcePackChoice": rec.get("resourcePackChoice"),
        # rel config path -> content-object hash (bytes stored under objects/).
        "configObjects": _config_entries(build_dir),
        "jvmArgs": (rec.get("settings") or {}).get("jvmArgs") or "",
    }
    path = sd / f"{sid}.json"
    path.write_text(json.dumps(snap, indent=2), "utf-8")

    # If this is the LKG, demote any previous LKG (one per pack).
    if kind == LKG_KIND:
        for old in sd.glob("*.json"):
            try:
                data = json.loads(old.read_text("utf-8"))
                if data.get("snapshotId") != sid and data.get("kind") == LKG_KIND:
                    data["kind"] = "superseded-lkg"
                    old.write_text(json.dumps(data, indent=2), "utf-8")
            except (OSError, json.JSONDecodeError):
                continue
    return snap


def list_snapshots(build_dir: Path) -> list:
    """Snapshots newest-first with their manifest metadata."""
    sd = snapshot_dir(build_dir)
    out = []
    if not sd.exists():
        return out
    for p in sd.glob("*.json"):
        try:
            data = json.loads(p.read_text("utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out.append({
            "snapshotId": data.get("snapshotId"), "label": data.get("label"),
            "kind": data.get("kind"), "createdAt": data.get("createdAt"),
            "modCount": len(data.get("selections") or []),
            "minecraftVersion": (data.get("requirements") or {}).get("minecraftVersion"),
            "loader": (data.get("requirements") or {}).get("loader"),
        })
    out.sort(key=lambda s: (s.get("createdAt") or ""), reverse=True)
    return out


def load_snapshot(build_dir: Path, snapshot_id: str) -> dict | None:
    p = snapshot_dir(build_dir) / f"{snapshot_id}.json"
    try:
        return json.loads(p.read_text("utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def last_known_good(build_dir: Path) -> dict | None:
    best = None
    for s in list_snapshots(build_dir):
        if s.get("kind") == LKG_KIND:
            best = s
            break
    if not best:
        return None
    return load_snapshot(build_dir, best["snapshotId"])


def mark_last_known_good(build_dir: Path, rec: dict, label: str = "Last Known Good") -> dict:
    """Snapshot the pack as the current Last Known Good (idempotent one-per-pack)."""
    return create_snapshot(build_dir, rec, label, kind=LKG_KIND)


def restore_config(build_dir: Path, snapshot: dict) -> None:
    """Rewrite the instance's config files from the snapshot's object store.

    Files absent from the snapshot are removed so the restored config state
    matches the snapshot exactly (generated config is application-managed).
    """
    cfg = build_dir / "instance" / "minecraft" / "config"
    objs = objects_dir(build_dir)
    wanted = snapshot.get("configObjects") or {}
    # Remove tracked config files not present in the snapshot.
    if cfg.is_dir():
        for p in cfg.rglob("*"):
            if p.is_file():
                rel = str(p.relative_to(cfg)).replace("\\", "/")
                if rel not in wanted:
                    try:
                        p.unlink()
                    except OSError:
                        pass
    # Write back the snapshot's config content.
    for rel, digest in sorted(wanted.items()):
        obj = objs / digest
        if not obj.is_file():
            raise FileNotFoundError(f"snapshot config object missing: {digest}")
        dest = cfg / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(obj, dest)


def restore_from_snapshot(build_dir: Path, rec: dict, snapshot: dict) -> dict:
    """Build a *candidate* record from a snapshot manifest — no mutation.

    Returns a new record dict whose requirements/selections/identity match
    the snapshot. The caller decides whether to promote it; the physical
    instance is reconstructed separately (see service.restore_snapshot).
    """
    cand = dict(rec)
    cand["requirements"] = {**cand.get("requirements", {}), **(snapshot.get("requirements") or {})}
    cand["identity"] = snapshot.get("identity")
    cand["selections"] = [dict(s) for s in (snapshot.get("selections") or [])]
    cand["shaderChoice"] = snapshot.get("shaderChoice")
    cand["resourcePackChoice"] = snapshot.get("resourcePackChoice")
    cand["snapshotRestored"] = {
        "snapshotId": snapshot.get("snapshotId"), "label": snapshot.get("label"),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    # Reattach derived intent records so the UI always has them.
    identity = cand.get("identity") or derive_identity(cand.get("requirements") or {}, cand)
    cand["selections"] = apply_intents(cand["selections"], identity)
    return cand
