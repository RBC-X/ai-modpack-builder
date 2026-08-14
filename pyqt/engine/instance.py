"""Isolated instance creation — Python port of src/instance/instance.ts.

Every pack gets its own fresh game directory under the build's workspace.
Never touches a user's real .minecraft.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from .core import sanitize_filename, mkdirp

LOG4J2_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Configuration status="warn">
  <Appenders>
    <Console name="SysOut" target="SYSTEM_OUT">
      <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level]: %msg%n" />
    </Console>
    <RollingRandomAccessFile name="File" fileName="logs/latest.log" filePattern="logs/%d{yyyy-MM-dd}-%i.log.gz">
      <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level]: %msg%n" />
      <Policies><TimeBasedTriggeringPolicy /><OnStartupTriggeringPolicy /></Policies>
    </RollingRandomAccessFile>
    <RollingRandomAccessFile name="DebugFile" fileName="logs/debug.log" filePattern="logs/debug-%i.log.gz">
      <PatternLayout pattern="[%d{HH:mm:ss}] [%t/%level]: %msg%n" />
      <Policies><OnStartupTriggeringPolicy /></Policies>
      <DefaultRolloverStrategy max="5" />
    </RollingRandomAccessFile>
  </Appenders>
  <Loggers>
    <Root level="info">
      <AppenderRef ref="SysOut" />
      <AppenderRef ref="File" />
      <AppenderRef ref="DebugFile" level="debug" />
    </Root>
  </Loggers>
</Configuration>
"""


def create_instance_dir(build_dir, logger) -> dict:
    game_dir = Path(build_dir) / "instance" / "minecraft"
    dirs = {
        "gameDir": str(game_dir),
        "modsDir": str(game_dir / "mods"),
        "resourcePacksDir": str(game_dir / "resourcepacks"),
        "shaderPacksDir": str(game_dir / "shaderpacks"),
        "configDir": str(game_dir / "config"),
    }
    for d in dirs.values():
        mkdirp(d)
    (game_dir / "launcher_profiles.json").write_text(json.dumps({"profiles": {}}, indent=2), "utf-8")
    logger.info("instance", f"Isolated instance created at {game_dir}")
    return dirs


def _copy_if_changed(src, dst) -> bool:
    """Copy src -> dst only when dst is missing or differs (size or mtime).

    Every launch re-installs the pack's jars into the instance; unconditional
    copies rewrote 2-3 GB and dirtied the Windows page cache right as the JVM
    started growing, starving it on low-RAM boxes (the game's clean exit-0
    with no crash report). copy2 preserves mtime so a repeat run sees matching
    size + mtime and skips, and a re-downloaded jar (new mtime) is re-copied.
    """
    dst = Path(dst)
    try:
        s = Path(src).stat()
        d = dst.stat()
        if s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime):
            return False
    except OSError:
        pass
    shutil.copy2(src, dst)
    return True


def install_mod_jars(mods_dir, jars: list, logger) -> int:
    mkdirp(mods_dir)
    copied = 0
    seen = set()
    for jar in jars:
        if not Path(jar["path"]).exists():
            logger.warn("instance", f"Missing jar for {jar['slug']}: {jar['path']}")
            continue
        name = sanitize_filename(jar["slug"] + ".jar", "mod.jar")
        if name in seen:
            continue
        seen.add(name)
        if _copy_if_changed(jar["path"], Path(mods_dir) / name):
            copied += 1
    logger.info("instance", f"Installed {copied} mod jars into instance")
    return copied


def install_resource_packs(dir_, files: list, logger) -> int:
    mkdirp(dir_)
    n = 0
    for f in files:
        if not Path(f).exists():
            continue
        dst = Path(dir_) / sanitize_filename(str(Path(f).name) or "pack.zip", "pack.zip")
        if _copy_if_changed(f, dst):
            n += 1
    if n:
        logger.info("instance", f"Installed {n} resource packs")
    return n


def install_shader_packs(dir_, files: list, logger) -> int:
    mkdirp(dir_)
    n = 0
    for f in files:
        if not Path(f).exists():
            continue
        dst = Path(dir_) / sanitize_filename(str(Path(f).name) or "shader.zip", "shader.zip")
        if _copy_if_changed(f, dst):
            n += 1
    if n:
        logger.info("instance", f"Installed {n} shader packs")
    return n


def write_server_configs(game_dir, logger) -> None:
    Path(game_dir, "eula.txt").write_text("eula=true\n", "utf-8")
    props = "\n".join([
        "view-distance=6", "spawn-protection=0", "online-mode=false",
        "max-players=8", "level-name=world", "motd=AI Modpack Builder test server",
    ]) + "\n"
    Path(game_dir, "server.properties").write_text(props, "utf-8")
    logger.info("instance", "Wrote eula.txt + server.properties (test server)")


def write_client_options(game_dir, opts: dict) -> None:
    lines = [
        "renderDistance:" + str(opts.get("renderDistance", 6)),
        "gfx_quality:2",
        "fov:" + str(opts.get("fov", 70)),
        "ao:1",
        "particles:0",
    ]
    Path(game_dir, "options.txt").write_text("\n".join(lines) + "\n", "utf-8")


def collect_instance_logs(game_dir) -> dict:
    """latest.log, crash-reports/*.txt, debug.log, gc.log, hs_err_pid*.log."""
    gd = Path(game_dir)
    latest = []
    crash_reports = []
    debug = []
    gc_log = []
    hs_err = []
    crash_files = []
    try:
        latest = (gd / "logs" / "latest.log").read_text("utf-8", "replace").splitlines()
    except OSError:
        pass
    try:
        debug = (gd / "logs" / "debug.log").read_text("utf-8", "replace").splitlines()
    except OSError:
        pass
    crash_dir = gd / "crash-reports"
    if crash_dir.is_dir():
        files = sorted(crash_dir.iterdir(), key=lambda p: p.name, reverse=True)
        for f in files[:5]:
            if f.name.endswith(".txt"):
                crash_files.append(f.name)
                try:
                    crash_reports.append(f.read_text("utf-8", "replace"))
                except OSError:
                    pass
    try:
        for f in sorted(gd.glob("hs_err_pid*.log"))[:3]:
            hs_err.append(f.read_text("utf-8", "replace"))
    except OSError:
        pass
    try:
        gc_log = (gd / "gc.log").read_text("utf-8", "replace").splitlines()
    except OSError:
        pass
    return {"latest": latest, "crashReports": crash_reports, "debug": debug,
            "gcLog": gc_log, "hsErr": hs_err, "crashFiles": crash_files}


def write_log4j_config(game_dir) -> None:
    Path(game_dir, "log4j2.xml").write_text(LOG4J2_XML, "utf-8")


def write_pack_readme(game_dir, content: str) -> None:
    Path(game_dir, "README.txt").write_text(content, "utf-8")


def write_game_file(game_dir, rel_path: str, content: str) -> None:
    p = Path(game_dir) / rel_path
    mkdirp(p.parent)
    p.write_text(content, "utf-8")


def copy_into_instance(game_dir, rel_path: str, src_file) -> None:
    p = Path(game_dir) / rel_path
    mkdirp(p.parent)
    shutil.copyfile(src_file, p)


def remove_jar(mods_dir, slug: str) -> bool:
    d = Path(mods_dir)
    exact = d / (slug + ".jar")
    if exact.exists():
        exact.unlink()
        return True
    try:
        candidates = [f for f in d.iterdir() if f.name.startswith(slug + "-") and f.name.endswith(".jar")]
    except OSError:
        candidates = []
    if len(candidates) == 1:
        candidates[0].unlink()
        return True
    return False
