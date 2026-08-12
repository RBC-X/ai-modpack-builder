"""Mod jar metadata reader — Python port of src/instance/jarmeta.ts.

The provider APIs expose only the dependencies authors registered there; the
authoritative source is the metadata inside each jar (fabric.mod.json,
quilt.mod.json, META-INF/mods.toml). Read safely entry-by-entry (zipfile, no
extraction).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .core import read_zip_entry_buf

JARJAR_RE = re.compile(r"^META-INF/jarjar/[^/]+\.jar$")


def _read_entry_buf(buf: bytes, name: str) -> Optional[bytes]:
    return read_zip_entry_buf(buf, name)


def read_jar_metadata_buf(buf: bytes) -> Optional[dict]:
    quilt = _read_entry_buf(buf, "quilt.mod.json")
    if quilt:
        m = _parse_quilt(quilt.decode("utf-8", "replace"))
        if m:
            return m
    fabric = _read_entry_buf(buf, "fabric.mod.json")
    if fabric:
        m = _parse_fabric(fabric.decode("utf-8", "replace"))
        if m:
            return m
    toml = _read_entry_buf(buf, "META-INF/mods.toml")
    if toml:
        m = _parse_forge_toml(toml.decode("utf-8", "replace"))
        if m:
            return m
    return None


def read_jar_metadata(jar_path) -> Optional[dict]:
    try:
        buf = Path(jar_path).read_bytes()
    except OSError:
        return None
    return read_jar_metadata_buf(buf)


def _jar_entries(buf: bytes):
    import io
    import zipfile
    try:
        with zipfile.ZipFile(io.BytesIO(buf)) as zf:
            return zf.namelist()
    except Exception:
        return []


def _jar_entry_bytes(buf: bytes, name: str) -> Optional[bytes]:
    return read_zip_entry_buf(buf, name)


def provided_mod_ids(jar_path) -> list:
    ids = set()
    try:
        buf = Path(jar_path).read_bytes()
    except OSError:
        return []
    _collect_provided(buf, ids, set())
    return list(ids)


def _collect_provided(buf: bytes, ids: set, visited: set) -> None:
    meta = read_jar_metadata_buf(buf)
    if meta:
        ids.add(meta["id"])
        for p in meta["provides"]:
            ids.add(p)
    nested = set()
    if meta:
        nested.update(j.replace("\\", "/") for j in meta["embeddedJars"])
    # Always descend into META-INF/jarjar/*.jar even when the outer jar has no
    # mod metadata of its own — e.g. Sinytra Connector's Forge variant is a
    # locator jar whose actual mod (mod id "connectormod") lives in jarjar.
    try:
        for name in _jar_entries(buf):
            if JARJAR_RE.match(name):
                nested.add(name)
    except Exception:
        pass
    for inner in nested:
        if inner in visited:
            continue
        visited.add(inner)
        inner_buf = _jar_entry_bytes(buf, inner)
        if not inner_buf:
            continue
        _collect_provided(inner_buf, ids, visited)


def _parse_fabric(text: str) -> Optional[dict]:
    try:
        json_data = json.loads(text)
    except Exception:
        return None
    mid = str(json_data.get("id", "")).strip()
    if not mid:
        return None
    depends = []
    for k, v in (json_data.get("depends") or {}).items():
        if v is None or str(v) == "":
            continue
        d = {"id": k}
        r = str(v).strip() if isinstance(v, str) else ""
        if r and r != "*":
            d["versionRange"] = r
        depends.append(d)
    suggests = list((json_data.get("suggests") or {}).keys())
    breaks = []
    for k, v in {**(json_data.get("breaks") or {}), **(json_data.get("conflicts") or {})}.items():
        if v is None or str(v) == "":
            continue
        d = {"id": k}
        r = str(v).strip() if isinstance(v, str) else ""
        if r and r != "*":
            d["versionRange"] = r
        breaks.append(d)
    provides = [str(p).strip() for p in (json_data.get("provides") or []) if str(p).strip()]
    embedded = [str(j.get("file", "")).strip() for j in (json_data.get("jars") or []) if str(j.get("file", "")).strip()]
    return {"id": mid, "name": str(json_data.get("name") or mid), "depends": depends,
            "suggests": suggests, "breaks": breaks, "provides": provides, "embeddedJars": embedded}


def _parse_quilt(text: str) -> Optional[dict]:
    try:
        json_data = json.loads(text)
    except Exception:
        return None
    loader = json_data.get("quilt_loader") or {}
    mid = str(loader.get("id", "")).strip()
    if not mid:
        return None
    depends = []
    suggests = []
    lst = loader.get("depends") or []
    for d in lst if isinstance(lst, list) else []:
        did = str(d.get("id", "")).strip() if isinstance(d, dict) else ""
        if not did:
            continue
        dep = {"id": did}
        if isinstance(d, dict) and d.get("unless"):
            dep["unless"] = str(d["unless"])
        vr = str(d.get("version") or d.get("versions") or "").strip() if isinstance(d, dict) else ""
        if vr and vr != "*":
            dep["versionRange"] = vr
        if isinstance(d, dict) and d.get("optional"):
            suggests.append(did)
        else:
            depends.append(dep)
    provides = [str(p).strip() for p in (loader.get("provides") or []) if str(p).strip()]
    embedded = [str(j.get("file", "")).strip() for j in (loader.get("jars") or []) if str(j.get("file", "")).strip()]
    breaks = []
    for d in loader.get("breaks") or []:
        if isinstance(d, dict) and d.get("id"):
            b = {"id": str(d["id"])}
            vr = str(d.get("version") or d.get("versions") or "").strip()
            if vr:
                b["versionRange"] = vr
            breaks.append(b)
    return {"id": mid, "name": str(loader.get("name") or mid), "depends": depends,
            "suggests": suggests, "breaks": breaks, "provides": provides, "embeddedJars": embedded}


def _parse_forge_toml(text: str) -> Optional[dict]:
    depends = []
    suggests = []
    breaks = []
    mod_ids = []
    in_mods = False
    pending_dep_id = ""
    pending_type = ""
    pending_range = ""

    def flush():
        nonlocal pending_dep_id, pending_type, pending_range
        if pending_dep_id and pending_type:
            if pending_type == "required":
                depends.append({"id": pending_dep_id, **({"versionRange": pending_range} if pending_range else {})})
            elif pending_type in ("optional", "discouraged"):
                suggests.append(pending_dep_id)
            elif pending_type == "incompatible":
                breaks.append({"id": pending_dep_id, **({"versionRange": pending_range} if pending_range else {})})
        pending_dep_id = ""
        pending_type = ""
        pending_range = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Strip inline comments. The standard Forge MDK template emits lines
        # like '[[mods]] #mandatory' and 'modId="x" #mandatory', which would
        # otherwise fail every end-of-line regex below.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if re.match(r"^\[\[dependencies\.[a-zA-Z0-9_]+\]\]$", line):
            flush()
            in_mods = False
            continue
        if re.match(r"^\[\[mods\]\]$", line) or re.match(r"^\[mods\..*\]$", line):
            flush()
            in_mods = True
            continue
        m = re.match(r'^modId\s*=\s*"([a-zA-Z0-9_]+)"$', line)
        if m:
            if in_mods:
                if m.group(1) not in mod_ids:
                    mod_ids.append(m.group(1))
                continue
            flush()
            pending_dep_id = m.group(1)
            continue
        t = re.match(r'^type\s*=\s*"([a-zA-Z]+)"$', line)
        if t:
            pending_type = t.group(1)
        r = re.match(r'^versionRange\s*=\s*"([^"]+)"$', line)
        if r:
            pending_range = r.group(1)
    flush()
    mid = mod_ids[0] if mod_ids else "unknown"
    if mid == "unknown" and not depends and not suggests:
        return None
    uniq = {}
    for d in depends:
        uniq[d["id"]] = d
    return {"id": mid, "name": mid, "depends": list(uniq.values()),
            "suggests": list(dict.fromkeys(suggests)), "breaks": breaks, "provides": [], "embeddedJars": []}


# --- dependency id mapping ---------------------------------------------------

FABRIC_PREFIX_STANDALONE = {
    "fabric-language-kotlin", "fabric-permissions-api-v0", "fabric-proxy-api-v1",
    "fabric-forwarding-api-v1", "fabric-carpet", "fabric-asm", "fabric-enchantments",
}


def map_jar_dep_id(id_: str, loader: str) -> Optional[str]:
    i = str(id_).lower().strip()
    if not i:
        return None
    if i in ("minecraft", "java", "fabricloader", "quilt_loader", "forge",
             "neoforge", "bukkit", "spigot", "paper"):
        return None
    if loader in ("fabric", "quilt"):
        if i == "fabric" or i.startswith("fabric-"):
            if loader == "quilt" and i not in FABRIC_PREFIX_STANDALONE:
                return "qsl"
            if loader == "fabric" and i not in FABRIC_PREFIX_STANDALONE:
                return "fabric-api"
        if i == "quilted_fabric_api":
            return "qsl" if loader == "quilt" else "quilted-fabric-api"
        if i == "qsl" or i.startswith("qsl-"):
            return "qsl"
    return i


def norm_id(id_: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(id_).lower())


def essential_libraries(loader: str) -> list:
    if loader == "fabric":
        return [
            {"slug": "fabric-api", "reason": "Fabric loader: fabric-api bundle is required by the vast majority of Fabric mods (provides fabric, fabric-* modules)"},
            {"slug": "modmenu", "reason": "Mod Menu — in-game mod list so every installed mod is visible in the instance"},
        ]
    if loader == "quilt":
        return [
            {"slug": "qsl", "reason": "Quilt loader: Quilt Standard Libraries is the core API library for Quilt mods"},
            {"slug": "modmenu", "reason": "Mod Menu — in-game mod list so every installed mod is visible in the instance"},
        ]
    return []
