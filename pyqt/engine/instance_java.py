"""Java runtime management — Python port of src/instance/java.ts.

Finds installed JVMs with the required major version and (when enabled)
auto-downloads a Temurin JRE from the Adoptium API into the workspace. Never
touches system installs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .core import java_dir, fetch_json, download_to_file, mkdirp, extract_zip_safe

COMMON_PATHS = [
    os.environ.get("JAVA_HOME", ""),
    r"C:\Program Files\Eclipse Adoptium\jdk-17.0.19.10-hotspot\bin\java.exe",
    r"C:\Program Files\Eclipse Adoptium\jdk-21.0.19.10-hotspot\bin\java.exe",
    r"C:\Program Files\Java\jdk-17\bin\java.exe",
    r"C:\Program Files\Common Files\Oracle\Java\javapath\java.exe",
    "/usr/lib/jvm/default-java/bin/java",
    "/usr/lib/jvm/java-17-openjdk-amd64/bin/java",
    "/usr/bin/java",
]

_IS_WIN = sys.platform == "win32"


def _workspace_java_candidates() -> list:
    exe = "java.exe" if _IS_WIN else "java"
    out = []
    root = java_dir()
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            depth = dirpath[len(str(root)):].count(os.sep)
            if depth > 4:
                dirnames[:] = []
                continue
            if exe in filenames:
                out.append(str(Path(dirpath) / exe))
    except OSError:
        pass
    return out


def detect_java(major: Optional[int] = None) -> Optional[dict]:
    candidates = [p for p in COMMON_PATHS if p] + _workspace_java_candidates()
    try:
        which = shutil.which("java")
        if which:
            candidates.append(which)
    except Exception:
        pass
    seen = set()
    for c in candidates:
        c = os.path.abspath(c)
        if c in seen:
            continue
        seen.add(c)
        if not Path(c).exists():
            continue
        try:
            r = subprocess.run([c, "-version"], capture_output=True, text=True,
                               timeout=8, creationflags=subprocess.CREATE_NO_WINDOW if _IS_WIN else 0)
            out = (r.stdout or "") + (r.stderr or "")
            import re
            m = re.search(r'(?:version\s+")?(\d+)(?:\.(\d+))?', out)
            major_num = int(m.group(1)) if m else 0
            if major is not None and major_num != major:
                continue
            vendor = "OpenJDK" if re.search(r"openjdk|temurin|adoptium", out, re.I) else "Oracle"
            return {"path": c, "major": major_num, "vendor": vendor}
        except Exception:
            continue
    return None


def detect_all_java() -> list:
    out = []
    for major in (21, 17, 11, 8):
        j = detect_java(major)
        if j:
            out.append(j)
    return out


def auto_install_java(major: int, logger) -> Optional[str]:
    os_name = "windows" if _IS_WIN else "linux"
    api = f"https://api.adoptium.net/v3/assets/latest/{major}/hotspot?architecture=x64&image_type=jre&os={os_name}&vendor=eclipse"
    try:
        logger.stage("instance", f"Auto-installing Java {major} (Adoptium Temurin JRE)…")
        assets = fetch_json(api)
        asset = (assets or [{}])[0]
        binary = asset.get("binary") or {}
        pkg = binary.get("package") or {}
        link = pkg.get("link")
        if not link:
            raise RuntimeError("No Adoptium asset found")
        target_dir = java_dir() / f"jre-{major}"
        java_bin = target_dir / "bin" / ("java.exe" if _IS_WIN else "java")
        if java_bin.exists():
            return str(java_bin)
        archive = java_dir() / pkg.get("name", f"jre-{major}.zip")
        mkdirp(java_dir())
        logger.info("instance", f"Downloading {pkg.get('name')}…")
        download_to_file(link, archive, max_bytes=300 * 1024 ** 2, timeout_ms=600000)
        logger.info("instance", "Extracting JRE…")
        if str(archive).lower().endswith(".zip"):
            extract_zip_safe(archive, target_dir, {"maxEntries": 20000, "maxTotalBytes": 600 * 1024 ** 2})
        else:
            import tarfile
            with tarfile.open(archive, "r:gz") as tf:
                mkdirp(target_dir)
                tf.extractall(target_dir, filter="data")
        found = None
        for dirpath, dirnames, filenames in os.walk(target_dir):
            if ("java.exe" if _IS_WIN else "java") in filenames:
                found = str(Path(dirpath) / ("java.exe" if _IS_WIN else "java"))
                break
        if not found:
            raise RuntimeError("JRE extracted but java binary not found")
        logger.ok("instance", f"Java {major} installed at {found}")
        return found
    except Exception as e:
        logger.warn("instance", f"Auto-install of Java {major} failed: {e}")
        return None


def java_for(mc_major: int) -> dict:
    if mc_major >= 21:
        return {"major": 21}
    if mc_major >= 18:
        return {"major": 17}
    if mc_major >= 17:
        return {"major": 16}
    return {"major": 8}
