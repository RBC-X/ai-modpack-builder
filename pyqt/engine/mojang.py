"""Mojang installer — Python port of src/instance/mojang.ts.

Assembles a real Minecraft installation from the official Mojang version
manifest: version JSON, client jar, rule-aware libraries, natives, and
budgeted asset objects. Every download is hash-verified.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

from .core import download_to_file, fetch_json, sanitize_filename, mkdirp

MANIFEST_URL = "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json"
_IS_WIN = sys.platform == "win32"
OS = "windows" if _IS_WIN else ("osx" if sys.platform == "darwin" else "linux")
ARCH = "x86_64" if sys.maxsize > 2 ** 32 else "x86"


def _rules_allow(rules):
    if not rules:
        return True
    allow = False
    for r in rules:
        r_os = r.get("os") or {}
        os_ok = (not r_os.get("name") or r_os["name"] == OS) and (not r_os.get("arch") or r_os["arch"] == ARCH)
        if r.get("action") == "allow" and os_ok:
            allow = True
        if r.get("action") == "disallow" and os_ok:
            return False
    return allow


def resolve_mojang_version(mc_version: str) -> dict:
    manifest = fetch_json(MANIFEST_URL)
    entry = next((v for v in (manifest or {}).get("versions") or [] if v.get("id") == mc_version), None)
    if not entry:
        raise RuntimeError(f'Minecraft version "{mc_version}" not found in Mojang version manifest')
    vjson = fetch_json(entry["url"])
    libraries = []
    for lib in vjson.get("libraries") or []:
        if not _rules_allow(lib.get("rules")):
            continue
        art = (lib.get("downloads") or {}).get("artifact") or {}
        if art.get("path"):
            libraries.append({"name": lib.get("name", ""), "path": art["path"], "url": art.get("url", ""),
                              "sha1": art.get("sha1", ""), "size": art.get("size", 0), "natives": False})
        if lib.get("natives"):
            classifier = lib["natives"].get(OS)
            c = ((lib.get("downloads") or {}).get("classifiers") or {}).get(classifier or "")
            if c and c.get("path"):
                libraries.append({"name": lib.get("name", ""), "path": c["path"], "url": c.get("url", ""),
                                  "sha1": c.get("sha1", ""), "size": c.get("size", 0), "natives": True,
                                  "classifier": classifier})
    def argstr(v):
        # Keep Mojang's two shapes intact (mirrors src/instance/mojang.ts): a
        # plain string, or a { value, rules } dict whose value may be a LIST
        # (e.g. ['--add-modules', 'ALL-MODULE-PATH']). build_launch_command
        # expands both; unwrapping .value here produced a bare list that
        # crashed the jvm-args loop (real flagship failure).
        return v if isinstance(v, str) else v
    return {
        "id": vjson.get("id"),
        "type": vjson.get("type"),
        "assets": vjson.get("assets"),
        "mainClass": vjson.get("mainClass"),
        "javaMajor": (vjson.get("javaVersion") or {}).get("majorVersion", 8),
        "clientJar": vjson.get("downloads", {}).get("client"),
        "serverJar": vjson.get("downloads", {}).get("server"),
        "libraries": libraries,
        "gameArgs": [argstr(a) for a in (vjson.get("arguments") or {}).get("game") or []],
        "jvmArgs": [argstr(a) for a in (vjson.get("arguments") or {}).get("jvm") or []],
    }


def _asset_index_hash(mc_version: str) -> str:
    manifest = fetch_json(MANIFEST_URL)
    entry = next((v for v in (manifest or {}).get("versions") or [] if v.get("id") == mc_version), None)
    if not entry:
        raise RuntimeError(f"No version {mc_version}")
    vjson = fetch_json(entry["url"])
    url = (vjson.get("assetIndex") or {}).get("url", "")
    m = re.search(r"packages/([0-9a-f]{40})", url)
    return m.group(1) if m else ""


def install_minecraft(mc_version: str, instance_dir, opts: dict) -> dict:
    logger = opts["logger"]
    logger.stage("instance", f"Installing Minecraft {mc_version} (Mojang)…")
    info = resolve_mojang_version(mc_version)
    libs_dir = Path(instance_dir) / "libraries"
    natives_dir = Path(instance_dir) / "natives"
    assets_dir = Path(instance_dir) / "assets"
    versions_dir = Path(instance_dir) / "versions" / mc_version
    mkdirp(libs_dir)
    mkdirp(natives_dir)
    mkdirp(assets_dir / "indexes")
    mkdirp(versions_dir)

    client_jar = versions_dir / (mc_version + ".jar")
    if not client_jar.exists():
        logger.info("instance", f"Downloading client jar ({round((info['clientJar'] or {}).get('size', 0) / 1e6)} MB)…")
        download_to_file(info["clientJar"]["url"], client_jar,
                         max_bytes=200 * 1024 ** 2, expected_sha1=info["clientJar"].get("sha1"))
    server_jar = None
    if info.get("serverJar"):
        s_path = versions_dir / (mc_version + "-server.jar")
        if not s_path.exists():
            logger.info("instance", f"Downloading server jar ({round(info['serverJar'].get('size', 0) / 1e6)} MB)…")
            download_to_file(info["serverJar"]["url"], s_path,
                             max_bytes=200 * 1024 ** 2, expected_sha1=info["serverJar"].get("sha1"))
        server_jar = str(s_path)

    cp = [str(client_jar)]
    downloaded_bytes = 0
    for lib in info["libraries"]:
        dest = libs_dir / lib["path"]
        if not dest.exists():
            try:
                download_to_file(lib["url"], dest, max_bytes=150 * 1024 ** 2,
                                 expected_sha1=lib.get("sha1") or None)
                downloaded_bytes += lib.get("size") or 0
            except Exception as e:
                logger.warn("instance", f"Library download failed ({Path(lib['path']).name}): {e} — skipping")
                continue
        if lib.get("natives"):
            try:
                _extract_native_lib(dest, natives_dir)
            except Exception as e:
                logger.warn("instance", f"Native extraction failed for {Path(lib['path']).name}: {e}")
        else:
            cp.append(str(dest))

    assets_index = info["assets"]
    try:
        idx_url = f"https://piston-meta.mojang.com/v1/packages/{_asset_index_hash(mc_version)}/{assets_index}.json"
        idx = fetch_json(idx_url)
        index_file = assets_dir / "indexes" / (sanitize_filename(assets_index) + ".json")
        index_file.write_text(json.dumps(idx), "utf-8")
        if opts.get("downloadAssets"):
            objects = idx.get("objects") or {}
            total_bytes = sum(o.get("size", 0) for o in objects.values())
            budget = opts.get("maxAssetMB", 400) * 1024 ** 2
            if total_bytes > budget:
                logger.warn("instance", f"Full asset set is {round(total_bytes / 1e6)} MB; budget is {opts.get('maxAssetMB')} MB — downloading only what fits.")
            entries = sorted(objects.items(),
                             key=lambda kv: 0 if re.search(r"^minecraft/(font|textures/gui|textures/title|icons)/|/font/", kv[0]) else 1)
            got = 0
            for p, o in entries:
                if got >= budget:
                    break
                h = o.get("hash", "")
                if not h:
                    continue
                dest = assets_dir / "objects" / h[:2] / h
                if dest.exists() and dest.stat().st_size == o.get("size"):
                    continue
                try:
                    download_to_file(f"https://resources.download.minecraft.net/{h[:2]}/{h}", dest,
                                     max_bytes=(o.get("size") or 0) + 1024, timeout_ms=30000)
                    got += o.get("size") or 0
                except Exception:
                    pass
            downloaded_bytes += got
            logger.ok("instance", f"Asset download complete: {round(got / 1e6)} MB within {opts.get('maxAssetMB')} MB budget")
        else:
            logger.info("instance", "Asset download disabled (budget) — client launch will be attempted with partial assets.")
    except Exception as e:
        logger.warn("instance", f"Asset index unavailable: {e}")

    sep = ";" if _IS_WIN else ":"
    logger.ok("instance", f"Installed {len(cp)} libraries; natives in {natives_dir}")
    return {"classpath": sep.join(cp), "nativesDir": str(natives_dir),
            "assetsIndexDir": str(assets_dir / "indexes"), "assetsIndex": assets_index,
            "clientJar": str(client_jar), "serverJar": server_jar,
            "installedLibs": len(cp), "downloadedBytes": downloaded_bytes}


def _extract_native_lib(jar_path: Path, natives_dir: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="amb-native-") as tmp:
        with zipfile.ZipFile(jar_path) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                name = info.filename.split("/")[-1]
                if re.search(r"\.(dll|so|dylib)$", name, re.I):
                    mkdirp(natives_dir)
                    with zf.open(info) as src, open(natives_dir / name, "wb") as dst:
                        shutil.copyfileobj(src, dst)


def _arg_rules_allow(a: dict) -> bool:
    return _rules_allow(a.get("rules") or [])


def build_launch_command(info: dict, install: dict, opts: dict) -> list:
    jvm = [
        f"-Xmx{opts['xmxMB']}m",
        f"-Xms{min(opts['xmxMB'], 1024)}m",
        "-Djava.library.path=" + install["nativesDir"],
        "-Dminecraft.launcher.brand=ai-modpack-builder",
        "-Dminecraft.launcher.version=0.1.0",
        "-Dlog4j2.formatMsgNoLookups=true",
        "-XX:+IgnoreUnrecognizedVMOptions",
        "--add-modules", "ALL-MODULE-PATH",
    ]
    for a in info.get("jvmArgs") or []:
        if isinstance(a, dict):
            if not _arg_rules_allow(a):
                continue
            v = a.get("value")
            if isinstance(v, list):
                jvm.extend(str(x) for x in v)
            else:
                jvm.append(str(v))
            continue
        if a.startswith("-cp") or a.startswith("-classpath") or "${classpath}" in a or "${natives_directory}" in a:
            continue
        jvm.append(a)
    game = [
        "--username", opts["username"],
        "--version", info["id"],
        "--gameDir", opts["gameDir"],
        "--assetsDir", install["assetsIndexDir"] + "/..",
        "--assetIndex", install["assetsIndex"],
        "--uuid", opts["uuid"],
        "--accessToken", opts.get("accessToken") or "0",
        "--userType", opts.get("userType") or "legacy",
        "--versionType", "release",
    ]
    declared = [a if isinstance(a, str) else str(a.get("value", "")) for a in (info.get("gameArgs") or [])]
    if opts.get("xuid") and any("${auth_xuid}" in a for a in declared):
        game += ["--xuid", opts["xuid"]]
    if opts.get("clientId") and any("${clientid}" in a for a in declared):
        game += ["--clientId", opts["clientId"]]
    if opts.get("width"):
        game += ["--width", str(opts["width"])]
    if opts.get("height"):
        game += ["--height", str(opts["height"])]
    if opts.get("quickPlayWorld"):
        game += ["--quickPlaySingleplayer", opts["quickPlayWorld"]]
    return [opts["javaPath"]] + jvm + ["-cp", install["classpath"], info["mainClass"]] + game
