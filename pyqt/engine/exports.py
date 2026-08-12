"""Exports — Python port of src/export/{modrinth,curseforge,server}.ts.

- .mrpack (formatVersion 1) with recomputed-hash + env validation
- CurseForge manifest ZIP: CF mods referenced (projectID/fileID), non-CF jars
  bundled into overrides/mods (the launcher downloads CF files on import)
- Server pack: client-only excluded, scripts + README, CF content referenced
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .core import (create_zip_buffer, write_zip_file, sha1_hex, sha512_hex,
                   list_zip_entries, read_zip_entry, sanitize_filename, mkdirp)


def _env(value, default="required") -> str:
    if value == "unsupported":
        return "unsupported"
    if value == "optional":
        return "optional"
    return default


def collect_overrides(game_dir) -> list:
    out = []
    include_dirs = ["config", "options.txt", "server.properties", "resourcepacks", "shaderpacks"]
    root = Path(game_dir)
    for name in include_dirs:
        p = root / name
        if not p.exists():
            continue
        files = _walk(p)
        for f in files:
            rel = str(f.relative_to(root)).replace(os.sep, "/")
            if rel.startswith(".."):
                continue
            try:
                out.append({"relative": rel, "data": f.read_bytes()})
            except OSError:
                continue
    return out


def _walk(p: Path) -> list:
    if not p.exists():
        return []
    if p.is_file():
        return [p]
    out = []
    try:
        for item in p.iterdir():
            out.extend(_walk(item))
    except OSError:
        pass
    return out


def find_jar(mods_dir, slug: str, version_number: str = "", version_id: str = ""):
    d = Path(mods_dir)
    try:
        files = [f.name for f in d.iterdir() if f.is_file()]
    except OSError:
        files = []
    if version_number:
        for f in files:
            if f == f"{slug}-{version_number}.jar" or \
               f.startswith(f"{slug}-{version_number}-") or \
               f.startswith(f"{slug}-{version_number}+") or \
               f.startswith(f"{slug}-{version_number}."):
                return str(d / f)
    if version_id:
        for f in files:
            if f.startswith(version_id + "-") or f.startswith(version_id + "."):
                return str(d / f)
    cands = [f for f in files if f == slug + ".jar" or f.startswith(slug + "-") or f.startswith(slug + ".")]
    cands.sort(key=len)
    return str(d / cands[0]) if cands else None


# ---------------------------------------------------------------------------
# Modrinth .mrpack
# ---------------------------------------------------------------------------

def export_mrpack(opts: dict) -> dict:
    logger = opts["logger"]
    logger.stage("export", "Building Modrinth .mrpack…")
    files = []
    entries = []
    mods_dir = Path(opts["modsDir"])
    included = 0

    seen_slugs = set()
    for sel in opts["selections"]:
        if sel.get("projectType") != "mod" or not sel.get("selected", True):
            continue  # conflict/repair-deselected mods are not part of the pack
        if sel.get("slug") in seen_slugs:
            continue  # repair may have added a slug that already exists once
        seen_slugs.add(sel.get("slug"))
        node = (opts["graph"]["nodes"] or {}).get(sel.get("key"))
        version = (node or {}).get("version") or {}
        vfiles = version.get("files") or []
        f = next((x for x in vfiles if x.get("primary")), vfiles[0] if vfiles else None)
        if not f or not f.get("url"):
            continue  # CF files: cannot bundle; skipped with note
        jar = find_jar(opts["modsDir"], sel["slug"],
                       version_number=sel.get("versionNumber", ""),
                       version_id=sel.get("versionId", ""))
        if not jar:
            logger.warn("export", f"mrpack: missing jar for {sel['slug']}")
            continue
        try:
            data = Path(jar).read_bytes()
        except OSError:
            logger.warn("export", f"mrpack: cannot read jar for {sel['slug']}")
            continue
        # Spec-clean mrpack: indexed files are DOWNLOADED by the launcher from
        # `downloads` and are never embedded in the archive (the archive holds
        # only modrinth.index.json + overrides/). Embedding the jars is both
        # non-standard and ambiguous (some launchers would extract them AND
        # download again). We still hash the real jar so import can verify.
        files.append({
            "path": f"mods/{sel['slug']}.jar",
            "hashes": {"sha1": sha1_hex(data), "sha512": sha512_hex(data)},
            "env": {"client": _env(sel.get("clientSide")), "server": _env(sel.get("serverSide"))},
            "downloads": [f["url"]],
        })
        included += 1

    for ov in collect_overrides(opts["overridesDir"]):
        entries.append({"name": "overrides/" + ov["relative"], "data": ov["data"]})

    dependencies = {"minecraft": opts["mcVersion"]}
    loader = opts["loader"]
    lv = opts.get("loaderVersion") or "*"
    if loader == "fabric":
        dependencies["fabric-loader"] = lv
    elif loader == "quilt":
        dependencies["quilt-loader"] = lv
    elif loader == "forge":
        dependencies["forge"] = lv
    elif loader == "neoforge":
        dependencies["neoforge"] = lv

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": f"{opts['mcVersion']}-{loader}",
        "name": opts["name"],
        "summary": opts.get("summary", ""),
        "files": files,
        "dependencies": dependencies,
    }
    entries.append({"name": "modrinth.index.json", "data": json.dumps(index, indent=2).encode("utf-8")})
    entries.append({"name": "overrides/.mrpack-root", "data": b""})

    zip_data = create_zip_buffer(entries)
    out = Path(opts["outPath"])
    mkdirp(out.parent)
    out.write_bytes(zip_data)

    details = validate_mrpack(out)
    valid = all(not d.startswith("ERR") for d in details)
    logger.ok("export", f"Modrinth pack: {included} mods, {len(entries) - included - 2} override files{'' if valid else ' — VALIDATION FAILED'}")
    return {"kind": "modrinth-mrpack", "path": str(out), "sizeBytes": len(zip_data),
            "validated": valid, "validationDetails": details}


def validate_mrpack(zip_path) -> list:
    details = []
    try:
        names = [e["name"] for e in list_zip_entries(zip_path)]
        if "modrinth.index.json" not in names:
            return ["ERR missing modrinth.index.json"]
        raw = read_zip_entry(zip_path, "modrinth.index.json")
        if not raw:
            return ["ERR cannot read modrinth.index.json"]
        index = json.loads(raw.decode("utf-8"))
        if index.get("formatVersion") != 1:
            details.append("ERR formatVersion != 1")
        if index.get("game") != "minecraft":
            details.append("ERR game != minecraft")
        if not (index.get("dependencies") or {}).get("minecraft"):
            details.append("ERR missing minecraft dependency")
        for f in index.get("files") or []:
            path = f.get("path")
            if not path or not (f.get("hashes") or {}).get("sha1"):
                details.append(f"ERR file entry missing hashes: {path}")
                continue
            # Spec-clean: indexed files are downloaded at install time, not
            # embedded. Verify the entry is structurally sound.
            if not (f.get("downloads") or []):
                details.append(f"ERR file entry missing downloads URL: {path}")
            if (f.get("env") or {}).get("client") not in ("required", "optional", "unsupported"):
                details.append(f"ERR invalid client env for {path}")
            if (f.get("env") or {}).get("server") not in ("required", "optional", "unsupported"):
                details.append(f"ERR invalid server env for {path}")
        # Spec-clean archive: the ONLY non-override entry is the index. Any
        # stray file (e.g. a jar embedded at the root, which some launchers
        # would extract AND re-download from `downloads`) is a defect.
        stray = [n for n in names
                 if n != "modrinth.index.json" and not n.startswith("overrides/")]
        if stray:
            details.append(f"ERR stray entries outside overrides/: {', '.join(sorted(stray)[:5])}")
        details.append(f"OK {len(index.get('files') or [])} indexed files validated")
    except Exception as e:
        details.append(f"ERR {e}")
    return details


# ---------------------------------------------------------------------------
# CurseForge manifest ZIP
# ---------------------------------------------------------------------------

def export_curseforge(opts: dict) -> dict:
    logger = opts["logger"]
    logger.stage("export", "Building CurseForge-compatible manifest ZIP…")
    entries = []
    manifest = {
        "minecraft": {
            "version": opts["mcVersion"],
            "modLoaders": [{"id": f"{opts['loader']}-{opts.get('loaderVersion') or 'latest'}", "primary": True}],
        },
        "manifestType": "minecraftModpack",
        "manifestVersion": 1,
        "name": opts["name"],
        "version": opts["version"],
        "author": "AI Modpack Builder",
        "files": [{"projectID": r["projectID"], "fileID": r["fileID"], "required": True}
                  for r in opts.get("cfReferences", [])],
        "overrides": "overrides",
    }
    entries.append({"name": "manifest.json", "data": json.dumps(manifest, indent=2).encode("utf-8")})

    for ov in collect_overrides(opts["overridesDir"]):
        entries.append({"name": "overrides/" + ov["relative"], "data": ov["data"]})

    cf_slugs = {r["slug"] for r in opts.get("cfReferences", [])}
    non_cf = []
    seen_slugs = set()
    for s in opts["selections"]:
        if s.get("projectType") != "mod" or not s.get("selected", True):
            continue
        if s["slug"] in cf_slugs or s["slug"] in seen_slugs:
            continue
        seen_slugs.add(s["slug"])
        non_cf.append(s)
    bundled = []
    missing_bundled = []
    for sel in non_cf:
        src = find_jar(opts["modsDir"], sel["slug"],
                       version_number=sel.get("versionNumber", ""),
                       version_id=sel.get("versionId", ""))
        if not src:
            missing_bundled.append(sel["slug"])
            continue
        data = Path(src).read_bytes()
        filename = Path(src).name
        entries.append({"name": f"overrides/mods/{filename}", "data": data})
        bundled.append({"slug": sel["slug"], "filename": filename})
        logger.info("export", f"Bundled mod jar into overrides/mods: {filename}")

    if non_cf:
        lines = [
            "This CurseForge pack was built by AI Modpack Builder.",
            (f"- {len(opts.get('cfReferences', []))} mod(s) are CurseForge references (downloaded by the launcher on import)."
             if opts.get("cfReferences") else "- 0 mods are CurseForge references (no CurseForge API key / Modrinth-only pack)."),
            (f"- {len(bundled)} mod jar(s) sourced from Modrinth are bundled in overrides/mods/ and are installed when the launcher applies overrides."
             if bundled else ""),
            (f"- MISSING jars (not bundled): {', '.join(missing_bundled)} — rebuild the pack to include them."
             if missing_bundled else ""),
            "",
            "When publishing this pack on CurseForge, keep only the manifest references",
            "(remove the bundled jars) and upload mod files through the CurseForge app.",
        ]
        entries.append({"name": "NOTES-Pack-Content.txt",
                        "data": "\n".join(l for l in lines if l).encode("utf-8")})

    zip_data = create_zip_buffer(entries)
    out = Path(opts["outPath"])
    mkdirp(out.parent)
    out.write_bytes(zip_data)

    details = validate_curseforge_zip(out, len(bundled))
    if missing_bundled:
        details.append(f"ERR missing jars for {', '.join(missing_bundled)}")
    valid = all(not d.startswith("ERR") for d in details)
    if not opts.get("cfReferences") and not bundled:
        details.append("NOTE: 0 file references AND 0 bundled jars — the launcher will install no mods")
    logger.ok("export", f"CurseForge ZIP: {len(opts.get('cfReferences', []))} manifest references, {len(bundled)} bundled jars, {len([e for e in entries if e['name'].startswith('overrides/') and not e['name'].startswith('overrides/mods/')])} override files{'' if valid else ' — VALIDATION FAILED'}")
    return {"kind": "curseforge-zip", "path": str(out), "sizeBytes": len(zip_data),
            "validated": valid, "validationDetails": details}


def validate_curseforge_zip(zip_path, expected_bundled: int = 0) -> list:
    details = []
    try:
        names = [e["name"] for e in list_zip_entries(zip_path)]
        if "manifest.json" not in names:
            return ["ERR missing manifest.json"]
        raw = read_zip_entry(zip_path, "manifest.json")
        manifest = json.loads(raw.decode("utf-8"))
        if manifest.get("manifestType") != "minecraftModpack":
            details.append("ERR manifestType != minecraftModpack")
        if manifest.get("manifestVersion") != 1:
            details.append("ERR manifestVersion != 1")
        if not manifest.get("minecraft", {}).get("version"):
            details.append("ERR missing minecraft version")
        if not manifest.get("overrides"):
            details.append("ERR missing overrides path")
        for f in manifest.get("files") or []:
            if not f.get("projectID") or not f.get("fileID"):
                details.append(f"ERR invalid reference entry: {f}")
        overrides = [n for n in names if n.startswith("overrides/")]
        if not overrides and not manifest.get("files"):
            details.append("NOTE: no overrides and no file references")
        if expected_bundled:
            bundled = [n for n in names if n.startswith("overrides/mods/")]
            if len(bundled) < expected_bundled:
                details.append(f"ERR expected {expected_bundled} bundled jars, found {len(bundled)}")
        details.append("OK manifest parses and references are valid")
    except Exception as e:
        details.append(f"ERR {e}")
    return details


# ---------------------------------------------------------------------------
# Server pack
# ---------------------------------------------------------------------------

def _java_for_mc(mc: str) -> str:
    import re
    m = re.match(r"^1\.(\d+)", mc)
    major = int(m.group(1)) if m else 21
    return "21" if major >= 21 else "17" if major >= 18 else "16" if major >= 17 else "8"


def export_server_pack(opts: dict) -> dict:
    logger = opts["logger"]
    logger.stage("export", "Building server pack…")
    entries = []
    excluded_client_only = 0

    seen_slugs = set()
    for sel in opts["selections"]:
        if sel.get("projectType") != "mod" or not sel.get("selected", True):
            continue
        if sel.get("slug") in seen_slugs:
            continue
        seen_slugs.add(sel.get("slug"))
        if sel.get("serverSide") == "unsupported":
            excluded_client_only += 1
            continue
        jar = find_jar(opts["modsDir"], sel["slug"])
        if not jar:
            continue
        entries.append({"name": f"mods/{sanitize_filename(sel['slug'] + '.jar', 'mod.jar')}",
                        "data": Path(jar).read_bytes()})

    for ov in collect_overrides(opts["overridesDir"]):
        if ov["relative"].startswith("resourcepacks/") or ov["relative"].startswith("shaderpacks/"):
            continue
        entries.append({"name": "configs/" + ov["relative"], "data": ov["data"]})
    entries.append({"name": "eula.txt", "data": b"eula=true\n"})

    perf = opts.get("perf") or {}
    ram = max(4, round((perf.get("recommendedAllocationMB") or 6144) / 1024)) if perf else 6
    jv = _java_for_mc(opts["mcVersion"])
    win_script = (
        "@echo off\r\n"
        "REM AI Modpack Builder server launcher\r\n"
        f"REM Requires: Java {jv} (64-bit), Minecraft {opts['mcVersion']} {opts['loader']} server\r\n"
        f"set RAM={ram}G\r\n"
        'set /p RAM="Allocated RAM in GB [%RAM%]: "\r\n'
        "java -Xmx%RAM%G -Xms1G -jar server.jar nogui\r\n"
        "pause\r\n"
    )
    linux_script = (
        "#!/usr/bin/env bash\n"
        "# AI Modpack Builder server launcher\n"
        f"# Requires: Java {jv} (64-bit), Minecraft {opts['mcVersion']} {opts['loader']} server\n"
        f"RAM={ram}\n"
        'read -p "Allocated RAM in GB [$RAM]: " input\n'
        "RAM=${input:-$RAM}\n"
        'exec java -Xmx"${RAM}"G -Xms1G -jar server.jar nogui\n'
    )
    entries.append({"name": "run.bat", "data": win_script.encode("utf-8")})
    entries.append({"name": "run.sh", "data": linux_script.encode("utf-8")})

    readme = (
        f"# {opts['name']} — Server Pack\n\n"
        f"Minecraft: {opts['mcVersion']}\n"
        f"Loader: {opts['loader']}\n"
        f"Java: {jv} (64-bit)\n"
        f"Recommended RAM: {ram} GB\n\n"
        "## Setup\n"
        "1. Install the server loader for your version (Fabric/Forge/NeoForge server installer).\n"
        "2. Copy the contents of this zip into your server directory.\n"
        "3. Run run.bat (Windows) or run.sh (Linux).\n\n"
        "## Notes\n"
        "- Client-only mods were excluded automatically.\n"
        "- CurseForge-hosted mods are not redistributed; install them via the CurseForge launcher manifest.\n"
    )
    entries.append({"name": "README.txt", "data": readme.encode("utf-8")})

    zip_data = create_zip_buffer(entries)
    out = Path(opts["outPath"])
    mkdirp(out.parent)
    out.write_bytes(zip_data)
    mod_count = len([e for e in entries if e["name"].startswith("mods/")])
    logger.ok("export", f"Server pack: {mod_count} mods, {excluded_client_only} client-only excluded")
    return {"kind": "server-zip", "path": str(out), "sizeBytes": len(zip_data),
            "validated": any(e["name"] == "README.txt" for e in entries) and any(e["name"] == "run.bat" for e in entries),
            "validationDetails": [f"OK server pack with {mod_count} mods; excluded {excluded_client_only} client-only"]}
