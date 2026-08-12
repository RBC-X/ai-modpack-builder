"""Mod loader installation — Python port of src/instance/loader.ts.

Fabric/Quilt: official meta APIs produce a complete launch JSON installed like
a vanilla version. Forge/NeoForge: the official installer JAR is run with
--installClient (headless), then the produced version JSON is parsed back.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from .core import download_to_file, fetch_json, mkdirp, sanitize_filename

_IS_WIN = sys.platform == "win32"
last_loader_versions: dict = {}


def maven_artifact_path(name: str) -> str:
    g, a, v = name.split(":")
    return f"{g.replace('.', '/')}/{a}/{v}/{a}-{v}.jar"


def _download_libs(libs: list, libs_dir: Path, logger) -> list:
    cp = []
    for lib in libs:
        art = (lib.get("downloads") or {}).get("artifact") or {}
        rel = art.get("path") or maven_artifact_path(lib.get("name", ""))
        if not rel:
            continue
        dest = libs_dir / rel
        if not dest.exists():
            url = art.get("url") or (lib.get("url") or "https://maven.fabricmc.net/") + rel
            try:
                download_to_file(url, dest, max_bytes=100 * 1024 ** 2,
                                 expected_sha1=art.get("sha1") or lib.get("sha1"),
                                 timeout_ms=300000)
            except Exception as e:
                logger.warn("instance", f"Loader library download failed ({rel}): {e}")
                continue
        if dest.exists():
            cp.append(str(dest))
    return cp


def pick_newest_loader_version(entries: list):
    def parse(v: str):
        parts = v.split("-", 1)
        core = parts[0]
        pre = parts[1] if len(parts) > 1 else ""
        return {"num": [int(x) if x.isdigit() else 0 for x in core.split(".")], "pre": pre}

    def is_stable(v: str) -> bool:
        return not re.search(r"-.*(beta|alpha|pre|rc)", v, re.I)

    def cmp_nums(a, b):
        n = max(len(a["num"]), len(b["num"]))
        for i in range(n):
            d = (a["num"][i] if i < len(a["num"]) else 0) - (b["num"][i] if i < len(b["num"]) else 0)
            if d != 0:
                return d
        return 0

    all_entries = []
    for l in entries:
        v = (l.get("loader") or {}).get("version") or l.get("version") or ""
        stable = (l.get("loader") or {}).get("stable") if isinstance(l.get("loader"), dict) else l.get("stable")
        if v:
            all_entries.append({"v": v, "stable": bool(stable)})
    stable_pool = [x for x in all_entries if x["stable"] or is_stable(x["v"])]
    pool = stable_pool if stable_pool else all_entries
    pool.sort(key=lambda x: cmp_nums(parse(x["v"]), {"num": [0]}), reverse=True)
    # correct numeric sort: use key tuple
    pool.sort(key=lambda x: tuple(parse(x["v"])["num"]), reverse=True)
    return pool[0]["v"] if pool else None


def install_fabric_or_quilt(mc_version: str, loader: str, libs_dir, logger) -> dict:
    meta = "https://meta.fabricmc.net/v2" if loader == "fabric" else "https://meta.quiltmc.org/v3"
    logger.stage("instance", f"Resolving {loader} loader for {mc_version}…")
    loaders = fetch_json(f"{meta}/versions/loader/{mc_version}") or []
    loader_version = pick_newest_loader_version(loaders)
    if not loader_version:
        raise RuntimeError(f"No {loader} loader available for {mc_version}")
    intermediary = fetch_json(f"{meta}/versions/intermediary/{mc_version}") or []
    json_url = f"{meta}/versions/loader/{mc_version}/{loader_version}/profile/json"
    logger.info("instance", f"Downloading {loader} launch JSON (loader {loader_version})…")
    vjson = fetch_json(json_url)
    cp = _download_libs(vjson.get("libraries") or [], Path(libs_dir), logger)
    logger.ok("instance", f"{loader} loader installed ({len(cp)} loader libs)")
    last_loader_versions[loader] = loader_version
    return {"classpathExtra": cp, "mainClass": vjson.get("mainClass", ""),
            "jvmArgsExtra": [], "gameArgsExtra": [], "label": loader,
            "loaderVersion": loader_version}


def substitute_loader_templates(s: str, ctx: dict) -> str:
    sep = ";" if _IS_WIN else ":"
    subs = {
        "${library_directory}": str(Path(ctx["gameDir"]) / "libraries"),
        "${classpath_separator}": sep,
        "${version_name}": ctx["versionId"],
        "${natives_directory}": str(Path(ctx["gameDir"]) / "natives"),
        "${launcher_name}": "ai-modpack-builder",
        "${launcher_version}": "0.1.0",
        "${assets_root}": str(Path(ctx["gameDir"]) / "assets"),
    }
    out = s
    for k, v in subs.items():
        out = out.replace(k, v)
    return out


def neo_forge_version_prefix(mc_version: str) -> str:
    m = re.match(r"^1\.(\d+)(?:\.(\d+))?$", mc_version)
    if not m:
        return mc_version + "-"
    return f"{m.group(1)}.{m.group(2) or '0'}."


def _run_installer(java_path: str, args: list, cwd: str, timeout_ms: int, logger, attempts: int = 2) -> dict:
    """Run the loader installer with one retry: the Forge/NeoForge CDNs
    (maven.creeperhost.net etc.) regularly time out on library downloads, and
    the installer is designed to be re-run (it resumes missing libraries).
    """
    last = None
    for attempt in range(attempts):
        if attempt > 0:
            logger.warn("instance", f"Retrying installer (attempt {attempt + 1}/{attempts}) after transient failure…")
        try:
            r = subprocess.run([java_path] + args, cwd=cwd, capture_output=True, text=True,
                               timeout=timeout_ms / 1000.0,
                               creationflags=subprocess.CREATE_NO_WINDOW if _IS_WIN else 0,
                               errors="replace")
        except subprocess.TimeoutExpired:
            last = {"code": -1, "stdout": "", "stderr": "timeout"}
            continue
        for line in (r.stdout or "").splitlines():
            if line.strip():
                logger.info("instance", f"[installer] {line.strip()}")
        for line in (r.stderr or "").splitlines():
            if line.strip():
                logger.info("instance", f"[installer] {line.strip()}")
        last = {"code": r.returncode, "stdout": r.stdout or "", "stderr": r.stderr or ""}
        if r.returncode == 0:
            return last
    return last


def install_forge(mc_version: str, loader: str, game_dir, java_path: str, logger) -> dict:
    maven = ("https://maven.minecraftforge.net/net/minecraftforge/forge"
             if loader == "forge" else "https://maven.neoforged.net/releases/net/neoforged/neoforge")
    logger.stage("instance", f"Resolving {loader} build for {mc_version}…")
    try:
        xml = fetch_json(f"{maven}/maven-metadata.xml", headers={"Accept": "application/xml, text/plain, */*"})
    except Exception:
        import urllib.request
        req = urllib.request.Request(f"{maven}/maven-metadata.xml", headers={"User-Agent": "ai-modpack-builder"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            xml = resp.read().decode("utf-8", "replace")
    versions = [m for m in re.findall(r"<version>([^<]+)</version>", str(xml))]
    prefix = neo_forge_version_prefix(mc_version) if loader == "neoforge" else mc_version + "-"
    candidates = [v for v in versions if v.startswith(prefix) and
                  not any(x in v for x in ("-beta", "-pre", "-rc"))]
    version = candidates[-1] if candidates else next((v for v in reversed(versions) if v.startswith(prefix)), None)
    if not version:
        raise RuntimeError(f"No {loader} build found for {mc_version}")

    # Absolute paths are required: the generated plan (classpath, -p module path,
    # -DlibraryDirectory) is used in launches whose cwd is the GAME dir, so a
    # relative game_dir would resolve every path against the wrong base.
    game = Path(game_dir).resolve()
    installer_jar = game / f"{loader}-installer-{version}.jar"
    marker = game / f"{loader}-{version}-installed.marker"
    if not marker.exists():
        url = (f"{maven}/{version}/forge-{version}-installer.jar"
               if loader == "forge" else f"{maven}/{version}/neoforge-{version}-installer.jar")
        logger.info("instance", f"Downloading {loader} installer ({version})…")
        download_to_file(url, installer_jar, max_bytes=200 * 1024 ** 2, timeout_ms=600000)
        logger.info("instance", f"Running {loader} installer (--installClient, headless)…")
        result = _run_installer(java_path, ["-jar", str(installer_jar), "--installClient", str(game)],
                                str(game), 600000, logger)
        if result["code"] != 0:
            raise RuntimeError(f"{loader} installer exited {result['code']} — {loader} installation failed")
        marker.write_text(version, "utf-8")
        logger.ok("instance", f"{loader} {version} installed")
    else:
        logger.ok("instance", f"{loader} {version} already installed")

    short_ver = version[len(mc_version) + 1:] if version.startswith(mc_version + "-") else version
    last_loader_versions[loader] = short_ver
    version_id = f"{mc_version}-forge-{short_ver}" if loader == "forge" else f"{mc_version}-neoforge-{short_ver}"
    if loader == "neoforge":
        try:
            versions_dir = game / "versions"
            if versions_dir.is_dir():
                found = next((d for d in os.listdir(versions_dir)
                              if d == f"neoforge-{short_ver}" or d.endswith(f"-neoforge-{short_ver}")), None)
                if found:
                    version_id = found
        except OSError:
            pass
    vjson_path = game / "versions" / version_id / (version_id + ".json")
    vjson = json.loads(vjson_path.read_text("utf-8"))
    cp = []
    for lib in vjson.get("libraries") or []:
        art = (lib.get("downloads") or {}).get("artifact") or {}
        rel = art.get("path")
        if rel:
            dest = game / "libraries" / rel
            if dest.exists():
                cp.append(str(dest))
    jvm = []
    for a in (vjson.get("arguments") or {}).get("jvm") or []:
        if isinstance(a, str) and not a.startswith("-cp"):
            jvm.append(substitute_loader_templates(a, {"gameDir": str(game), "versionId": version_id}))
    game_args = []
    for a in (vjson.get("arguments") or {}).get("game") or []:
        if isinstance(a, str):
            game_args.append(substitute_loader_templates(a, {"gameDir": str(game), "versionId": version_id}))
    return {"classpathExtra": cp, "mainClass": vjson.get("mainClass", ""),
            "jvmArgsExtra": jvm, "gameArgsExtra": game_args, "label": version_id,
            "loaderVersion": version, "excludeVanillaClientJar": True}
