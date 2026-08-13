"""Launcher — Python port of src/launcher/play.ts + progress.ts.

Plays a saved pack using the same launch construction as the test pipeline,
but spawns the game so the user plays normally (no menu-watch kill, no
timeout). Tracks running processes per build; stopping kills the whole tree.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .core import builds_dir
from .hardware import fit_xmx_mb
from .instance import install_mod_jars, install_resource_packs, install_shader_packs, remove_jar
from .tester import assemble, build_client_args
from .repair import (parse_crash_report, missing_dep_ids, fatal_startup_detected,
                     main_menu_reached)
from .process import run_process

_IS_WIN = sys.platform == "win32"
_running: dict = {}
_stopped_marks: dict = {}
_evidence_stamp: dict = {}
_auto_relaunched: set = set()
SILENT_DEATH_WINDOW_S = 120  # relaunch only if the game dies this soon after the menu


def _pid_file(build_dir) -> Path:
    return Path(build_dir) / "logs" / "launch-play.pid"


def pid_alive(pid) -> bool:
    """Windows-safe process probe.

    os.kill(pid, 0) is not a valid probe on Windows (raises WinError 87 for
    signal 0), which crashed stop_pack on the first real game (flagship run).
    """
    if not pid or pid <= 0:
        return False
    if _IS_WIN:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(h, ctypes.byref(code)):
                return code.value == STILL_ACTIVE
            return False
        finally:
            kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError as e:
        return e.errno == 13  # EPERM — exists but not ours


def read_pid(build_id: str):
    return _read_pid_raw(build_id)


def _read_pid_raw(build_id: str):
    try:
        return int(_pid_file(builds_dir() / build_id).read_text().strip())
    except Exception:
        return None


def is_running(build_id: str) -> bool:
    r = _running.get(build_id)
    if r:
        if r["proc"].poll() is not None:
            _running.pop(build_id, None)
            return False
        return True
    return pid_alive(_read_pid_raw(build_id))


def any_running(exclude_id: str = ""):
    for bid, r in _running.items():
        if bid == exclude_id:
            continue
        if r["proc"].poll() is None:
            return {"buildId": bid, "pid": r["pid"]}
    try:
        for d in builds_dir().iterdir():
            if not d.name.startswith("b-") or d.name == exclude_id:
                continue
            pid = _read_pid_raw(d.name)
            if pid and pid_alive(pid):
                return {"buildId": d.name, "pid": pid}
    except OSError:
        pass
    return None


def current_play(build_id: str):
    r = _running.get(build_id)
    if not r:
        pid = _read_pid_raw(build_id)
        if pid and pid_alive(pid):
            return {"buildId": build_id, "pid": pid, "gameDir": "",
                    "logFile": str(_pid_file(builds_dir() / build_id)), "startedAt": ""}
        return None
    if not is_running(build_id):
        return None
    return {"buildId": build_id, "pid": r["pid"], "gameDir": r["gameDir"],
            "logFile": r["logFile"], "startedAt": r["startedAt"]}


def running_pids() -> list:
    return [r["pid"] for r in _running.values()]


# --- progress state ----------------------------------------------------------

def launch_state_path(build_dir) -> Path:
    return Path(build_dir) / "logs" / "launch-state.json"


def write_launch_state(build_dir, state: dict) -> None:
    try:
        launch_state_path(build_dir).write_text(json.dumps(state), "utf-8")
    except OSError:
        pass


def read_launch_state(build_dir):
    try:
        return json.loads(launch_state_path(build_dir).read_text("utf-8"))
    except Exception:
        return None


def play_state(build_id: str, build_dir: str):
    r = _running.get(build_id)
    if r:
        return r["state"]
    st = read_launch_state(build_dir)
    if st and isinstance(st.get("pid"), int) and st["pid"] > 0 and st.get("phase") in ("running", "loading"):
        if not pid_alive(st["pid"]):
            st = {**st, "phase": "stopped", "stage": "Game closed", "error": None,
                  "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    # A persisted state that claims the game is active but carries no live pid
    # is stale garbage: the launcher that wrote it is gone, and a game cannot be
    # running without a process. Without this guard the UI could report "running"
    # forever after a crash that left a pid-less running record behind.
    if st and st.get("phase") in ("running", "loading", "preparing", "installing"):
        live_pid = isinstance(st.get("pid"), int) and st["pid"] > 0 and pid_alive(st["pid"])
        if not live_pid:
            try:
                # updatedAt is written with time.gmtime (UTC) — time.mktime
                # would interpret it as LOCAL time and compute a wrong (often
                # negative) age on non-UTC machines, silently keeping stale
                # records "running" forever. calendar.timegm is the UTC parse.
                import calendar
                age = time.time() * 1000 - calendar.timegm(time.strptime(st["updatedAt"][:19], "%Y-%m-%dT%H:%M:%S")) * 1000
            except Exception:
                age = 0
            # Freshly-written states may legitimately lack a pid for a moment
            # (written before the spawned pid was attached), so only treat
            # pid-less records as dead once they are clearly stale.
            if age > 2 * 60 * 1000:
                st = {**st, "phase": "stopped", "stage": "Game closed (stale launch state)",
                      "error": None, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return st


# --- progress mapping ---------------------------------------------------------

def launch_progress_for(lines: list, mods_total) -> dict:
    text = "\n".join(lines)
    base = {"modsLoaded": None, "modsTotal": mods_total}
    if fatal_startup_detected(lines):
        stage = _error_stage(lines)
        return {**base, "phase": "error", "progress": 0, "stage": stage, "error": stage,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if main_menu_reached(lines):
        return {**base, "phase": "running", "progress": 100, "stage": "Main menu reached — ready to play",
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    loaded_match = re.search(r"Loaded (\d+) mods", text)
    discover_match = re.search(r"Loading (\d+) mods", text)
    loaded_count = loaded_match.group(1) if loaded_match else None
    discover_count = discover_match.group(1) if discover_match else None
    milestones = [
        (re.compile(r"Reloading ResourceManager|Backend library: LWJGL"), 92, lambda: "Reloading resources…"),
        (re.compile(r"Sound engine started|OpenAL initialized"), 88, lambda: "Sound engine started"),
        (re.compile(r"Setting user:"), 82, lambda: "Setting up user…"),
        (re.compile(r"Loaded (\d+) mods from (\d+) mod list"), 74, lambda: f"Loaded {loaded_count} mods"),
        (re.compile(r"Loading (\d+) mods"), 62, lambda: f"Mods discovered: {discover_count}"),
    ]
    for re_, prog, stage_fn in milestones:
        m = re_.search(text)
        if m:
            loaded = re.search(r"Loaded (\d+) mods", text)
            return {**base, "phase": "loading", "progress": prog, "stage": stage_fn(),
                    "modsLoaded": int(loaded.group(1)) if loaded else None,
                    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if re.search(r"Launching Minecraft|Loading Minecraft|\[main/INFO\]:", text):
        return {**base, "phase": "loading", "progress": 54, "stage": "Starting Minecraft…",
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    return {**base, "phase": "preparing", "progress": 52, "stage": "Starting game…",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _error_stage(lines: list) -> str:
    text = "\n".join(lines)
    m = re.search(r"(Some of your mods are incompatible with the game or each other!|Incompatible mods found!|"
                  r"There was a severe problem during mod loading|The game crashed whilst[^\n]*|"
                  r"Failed to start the minecraft server|Exception in thread \"[^\"]*\"[^\n]*|"
                  r"FATAL ERROR in native method[^\n]*|Failure message: Mod [^\n]*|[^\n]*which is missing![^\n]*|"
                  r"[^\n]*which is not installed[^\n]*)", text)
    return m.group(1)[:200] if m else "Fatal startup error detected — see log"


def redact_launch_args(args: list) -> list:
    safe = list(args)
    if "--accessToken" in safe:
        i = safe.index("--accessToken")
        if i + 1 < len(safe):
            safe[i + 1] = "<redacted>"
    return safe


def _kill_tree(proc) -> None:
    try:
        if _IS_WIN:
            subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            try:
                os.killpg(os.getpgid(proc.pid), 9)
            except Exception:
                proc.kill()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def locate_jar(mods_dir, slug: str, preferred: str = "") -> str:
    d = Path(mods_dir)
    try:
        if preferred:
            p = d / preferred
            if p.exists():
                return str(p)
        exact = d / (slug + ".jar")
        if exact.exists():
            return str(exact)
        try:
            cands = [f for f in d.iterdir() if f.name.startswith(slug + "-") and f.name.endswith(".jar")]
        except OSError:
            cands = []
        if len(cands) == 1:
            return str(cands[0])
    except OSError:
        pass
    return ""


# --- evidence -----------------------------------------------------------------

def collect_launch_evidence(game_dir, log_file, opts: dict = None) -> dict:
    opts = opts or {}
    since_ms = opts.get("sinceMs", 0)
    out = {"crash": None, "missingDeps": [], "crashFiles": []}
    gd = Path(game_dir)
    crash_dir = gd / "crash-reports"
    try:
        files = []
        if crash_dir.is_dir():
            for f in crash_dir.iterdir():
                if f.name.endswith(".txt") and "crash-" in f.name and f.stat().st_mtime * 1000 >= since_ms:
                    files.append(f)
        files.sort(key=lambda f: f.name)
        for f in files:
            out["crashFiles"].append("crash-reports/" + f.name)
        if files:
            text = files[-1].read_text("utf-8", "replace")
            parsed = parse_crash_report(text)
            desc = (" — " + parsed["description"][:220]) if parsed["description"] else ""
            out["crash"] = f"Crash: {parsed['exception']}{desc}"
            out["missingDeps"] = missing_dep_ids(text)
    except OSError:
        pass
    try:
        for f in gd.iterdir():
            if re.match(r"^hs_err_pid\d+\.log$", f.name) and f.stat().st_mtime * 1000 >= since_ms:
                out["crashFiles"].append(f.name)
    except OSError:
        pass
    if not out["crash"]:
        try:
            st = Path(log_file).stat()
            key = f"{st.st_size}:{st.st_mtime_ns}"
            if _evidence_stamp.get(log_file) == key:
                return out
            _evidence_stamp[log_file] = key
            text = Path(log_file).read_text("utf-8", "replace")[opts.get("logSinceBytes", 0):]
            tail = "\n".join(text.splitlines()[-800:])
            if re.search(r"The game crashed whilst|MISSING EXCEPTION MESSAGE|Failure message: Mod .* requires|"
                         r"which is not installed|Some of your mods are incompatible with the game or each other!|"
                         r"which is missing!|ClassMetadataNotFoundException|MixinTransformerError", tail):
                m = (re.search(r"The game crashed whilst ([^\n]*)", tail) or
                     re.search(r"ClassMetadataNotFoundException: ([\w.$]+)", tail) or
                     re.search(r"(Failure message: Mod [^\n]*|Some of your mods are incompatible with the game or each other![^\n]*)", tail))
                out["crash"] = m.group(1)[:220] if m else "Fatal startup error — see log"
                if not out["missingDeps"]:
                    out["missingDeps"] = missing_dep_ids(tail)
        except OSError:
            pass
    return out


# --- launch -------------------------------------------------------------------

def launch_pack(record: dict, opts: dict) -> dict:
    """opts: {buildDir, logger, username?, session?, xmxMB?, onState?}"""
    build_dir = opts["buildDir"]
    logger = opts["logger"]
    on_state = opts.get("onState")
    build_id = record["buildId"]
    state = {"buildId": build_id, "phase": "preparing", "progress": 0,
             "stage": "Queued — preparing launch…", "modsLoaded": None,
             "modsTotal": (record.get("packStats") or {}).get("modCount"),
             "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    menu_at = None  # set when the game first reaches the main menu

    def report(s):
        nonlocal state
        state = s
        entry = _running.get(build_id)
        # Persist a stable per-pack identity: advance() states built by
        # launch_progress_for() carry no buildId/pid, so re-attach them here.
        # The entry state keeps the same identity so status() always reports
        # the real pid even after progress updates replace the state dict.
        persisted = {"buildId": build_id, **dict(s)}
        pid = (entry or {}).get("pid")
        if pid and not persisted.get("pid"):
            persisted["pid"] = pid
        if entry:
            entry["state"] = dict(persisted)
        write_launch_state(build_dir, persisted)
        if on_state:
            on_state(s)

    report(state)
    # Multiple packs may run at once: each launch keeps its own process tree,
    # pid file, launch-state file and log inside this build's directory, so
    # concurrent instances are fully isolated. Only the SAME pack is guarded
    # (is_running check further down).
    game_dir = Path(build_dir) / "instance" / "minecraft"
    mods_dir = game_dir / "mods"
    dl_mods = Path(build_dir) / "downloads" / "mods"
    # Only SELECTED mods are part of the pack. Repair may have deselected mods
    # (conflicts, unavailable deps) or swapped versions — launching must use the
    # same repaired set the build test validated, never the raw downloads dir
    # (which still holds old/removed jars).
    selected = [s for s in (record.get("selections") or [])
                if s.get("projectType") == "mod" and s.get("selected", True)]
    selection_slugs = {s["slug"].lower() for s in selected}
    dl_by_name = {d["key"]: d.get("filename") for d in (record.get("downloads") or [])}
    jars = []
    for s in selected:
        p = None
        if s.get("downloadPath") and Path(s["downloadPath"]).exists():
            # Authoritative file — repair may have re-picked a different version.
            p = s["downloadPath"]
        elif dl_mods.is_dir():
            p = locate_jar(dl_mods, s["slug"], dl_by_name.get(s.get("key")) or "")
        if p:
            jars.append({"slug": s["slug"], "path": p, "featureIds": s.get("featureIds") or ["launch"]})
    install_mod_jars(mods_dir, jars, logger)
    try:
        # install_mod_jars names every jar exactly "{slug}.jar", so an exact
        # slug match is safe — a prefix match would wrongly keep e.g.
        # "daily-boss-x-brutal-bosses.jar" because "daily-boss" is a slug.
        for f in mods_dir.iterdir():
            if f.name.endswith(".jar") and f.name[:-4].lower() not in selection_slugs:
                f.unlink()
    except OSError:
        pass
    # Visuals: install recorded shaders/resource packs (skip when already installed)
    visuals = _visual_files(record)
    rp_dir = game_dir / "resourcepacks"
    sh_dir = game_dir / "shaderpacks"
    if visuals["resourcePacks"] and (not rp_dir.is_dir() or not any(f.name != ".keep" for f in rp_dir.iterdir())):
        install_resource_packs(rp_dir, visuals["resourcePacks"], logger)
    if visuals["shaders"] and (not sh_dir.is_dir() or not any(f.name != ".keep" for f in sh_dir.iterdir())):
        install_shader_packs(sh_dir, visuals["shaders"], logger)
    if not mods_dir.exists():
        raise RuntimeError(f"Pack instance is incomplete (missing mods dir at {game_dir})")
    if is_running(build_id):
        raise RuntimeError(f"Pack is already running (pid {_read_pid_raw(build_id) or 0})")

    mc = record["requirements"]["minecraftVersion"]
    loader = "forge" if record["requirements"]["loader"] == "auto" else record["requirements"]["loader"]
    ram_gb = record["requirements"].get("ramGB") or 8
    settings = record.get("settings") or {}
    env = {
        "buildId": build_id, "buildDir": build_dir, "gameDir": str(game_dir),
        "mcVersion": mc, "loader": loader, "testMode": "standard", "logger": logger,
        "xmxMB": opts.get("xmxMB") or fit_xmx_mb(ram_gb),
        "modJars": [], "resourcePackFiles": visuals["resourcePacks"], "shaderFiles": visuals["shaders"],
        "downloadAssets": settings.get("downloadAssets", False),
        "maxAssetMB": settings.get("maxAssetMB", 400),
        "autoInstallJava": settings.get("autoInstallJava", True),
        "onLaunchProgress": lambda p, stage: report({
            **state, "phase": "installing" if 18 <= p < 46 else "preparing",
            "progress": p, "stage": stage,
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }),
    }
    logger.stage("launch", f"Launching pack for play ({record.get('name') or build_id}, {mc} {loader}, {env['xmxMB']} MB)…")
    assembled = assemble(env)
    report({**state, "phase": "preparing", "progress": 46, "stage": "Preparing game files…",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    report({**state, "phase": "preparing", "progress": 50, "stage": "Launching game…",
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    session = opts.get("session")
    # Concurrent-play hardening: when another pack is already running, lower
    # this pack's GPU load (FPS cap + smaller window) so two OpenGL windows
    # can coexist on a shared/ integrated GPU without display-driver hangs.
    concurrent = any_other_running(build_id)
    # RAM guard: refuse to launch into an exhausted machine instead of letting
    # the game die silently 60-200 s later (measured on this 7 GB box: the
    # pack sits at ~0.2 GB free at the menu and gets terminated).
    free_gb = free_physical_gb()
    refuse_below = 1.5 if concurrent else 1.0
    if free_gb < refuse_below:
        raise RuntimeError(
            f"Not enough free RAM ({free_gb} GB) to run this pack safely"
            + (" while another pack is running." if concurrent else ".")
            + " Close other applications, lower the pack's RAM in Pack Details, "
              "or stop the running pack first.")
    if free_gb < 3.0:
        logger.warn("launch", f"Only {free_gb} GB of RAM free — the pack may not stay stable at the menu")
    width, height = 1280, 720
    if concurrent:
        width, height = 960, 540
        _tune_concurrent_options(game_dir, logger)
        logger.info("launch", "Concurrent play: another pack is running — capped FPS at 30 and window at 960x540")
    args = build_client_args(env, assembled, {
        "username": opts.get("username") or "Player",
        "session": session, "width": width, "height": height,
    })

    logs_dir = Path(build_dir) / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / "launch-play.log"
    launch_start = time.time() * 1000
    log_start_bytes = log_file.stat().st_size if log_file.exists() else 0

    def stamp():
        return f"[{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}] "

    with open(log_file, "a", encoding="utf-8", errors="replace") as f:
        f.write(stamp() + "launching: " + " ".join(redact_launch_args(args)) + "\n")

    if is_running(build_id):
        raise RuntimeError(f"Pack is already running (pid {_read_pid_raw(build_id) or 0})")
    logger.info("launch", f"Starting java {args[0]} in {game_dir}…")

    game_lines = []

    def apply_evidence(s):
        ev = collect_launch_evidence(str(game_dir), str(log_file),
                                     {"sinceMs": launch_start, "logSinceBytes": log_start_bytes})
        if ev["crash"] and s.get("phase") != "error":
            return {**s, "phase": "error", "progress": 0, "stage": ev["crash"], "error": ev["crash"],
                    "missingDeps": ev["missingDeps"] or s.get("missingDeps"),
                    "crashFiles": ev["crashFiles"] or s.get("crashFiles"),
                    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        out = dict(s)
        if ev["missingDeps"] and not s.get("missingDeps"):
            out["missingDeps"] = ev["missingDeps"]
        if ev["crashFiles"] and not s.get("crashFiles"):
            out["crashFiles"] = ev["crashFiles"]
        return out

    def advance(extra_lines):
        nonlocal state, menu_at
        if state.get("phase") == "error":
            return
        for line in extra_lines:
            if line.strip():
                game_lines.append(line)
                if len(game_lines) > 3000:
                    del game_lines[: len(game_lines) - 3000]
        nxt = launch_progress_for(game_lines, state.get("modsTotal"))
        if nxt["phase"] == "running" and state.get("phase") != "running":
            menu_at = time.time()
        if nxt["phase"] != "error" and nxt["progress"] < state.get("progress", 0):
            nxt["progress"] = state["progress"]
        nxt = apply_evidence(nxt)
        changed = (nxt["phase"] != state.get("phase") or nxt["progress"] != state.get("progress") or
                   nxt["stage"] != state.get("stage") or
                   (nxt.get("missingDeps") or []) != (state.get("missingDeps") or []) or
                   (nxt.get("crashFiles") or []) != (state.get("crashFiles") or []))
        if changed:
            report(nxt)

    def on_game_data(text: str):
        with open(log_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(text)
        advance(text.splitlines())

    seen_logs = set()
    log_offsets = {}
    stop_watch = threading.Event()

    def log_watch():
        # Read each game log incrementally by byte offset so content written by
        # PREVIOUS launches (which may contain old fatal lines) is never
        # mistaken for the current run's failure.
        while not stop_watch.is_set():
            new_lines = []
            for rel in ("logs/latest.log", "logs/debug.log"):
                p = game_dir / rel
                try:
                    if not p.exists():
                        continue
                    st = p.stat()
                    if st.st_mtime * 1000 < launch_start:
                        continue
                    size = st.st_size
                    start = log_offsets.get(rel, 0)
                    if size < start:
                        start = 0  # game rotated/truncated the file
                    if size == start:
                        continue
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        fh.seek(start)
                        chunk = fh.read()
                    log_offsets[rel] = size
                    key = f"{p}:{size}:{st.st_mtime_ns}"
                    seen_logs.add(key)
                    lines = chunk.splitlines()
                    new_lines.extend(lines[-120:] if len(seen_logs) > 2 else lines[-40:])
                except OSError:
                    pass
            if new_lines:
                advance(new_lines)
            else:
                advance([])
            time.sleep(1.2)

    watcher = threading.Thread(target=log_watch, daemon=True)
    # Snapshot pre-launch sizes: if a game log is appended (not truncated) by
    # the new run, we must not read content the PREVIOUS launch wrote.
    for _rel in ("logs/latest.log", "logs/debug.log"):
        try:
            if (game_dir / _rel).exists():
                log_offsets[_rel] = (game_dir / _rel).stat().st_size
        except OSError:
            pass
    watcher.start()
    _evidence_stamp.pop(str(log_file), None)

    proc = subprocess.Popen(
        args, cwd=str(game_dir), env=dict(os.environ),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
        creationflags=(subprocess.CREATE_NO_WINDOW if _IS_WIN else 0) | getattr(subprocess, "DETACHED_PROCESS", 0),
        text=True, errors="replace", bufsize=1,
    )
    proc._amb_game_dir = str(game_dir)
    proc._amb_log_file = str(log_file)
    proc._amb_launch_start = launch_start
    proc._amb_log_start = log_start_bytes
    proc._amb_advance = advance
    proc._amb_report = report

    def pump(stream):
        try:
            for line in stream:
                on_game_data(line + "\n")
        except Exception:
            pass

    threads = []
    if proc.stdout:
        t = threading.Thread(target=pump, args=(proc.stdout,), daemon=True)
        t.start()
        threads.append(t)
    if proc.stderr:
        t = threading.Thread(target=pump, args=(proc.stderr,), daemon=True)
        t.start()
        threads.append(t)

    def on_exit():
        with open(log_file, "a", encoding="utf-8", errors="replace") as f:
            f.write(stamp() + f"process exited code={proc.returncode}\n")
        stop_watch.set()
        entry = _running.pop(build_id, None)
        mark = _stopped_marks.pop(build_id, None)
        try:
            _pid_file(build_dir).unlink()
        except OSError:
            pass
        logger.info("launch", f"Game exited (code {proc.returncode})")
        base = mark or (entry or {}).get("state") or state
        ev = collect_launch_evidence(str(game_dir), str(log_file),
                                     {"sinceMs": launch_start, "logSinceBytes": log_start_bytes})
        if base.get("phase") in ("error", "stopped"):
            exited = base
        elif ev["crash"]:
            exited = {**base, "phase": "error", "stage": ev["crash"], "error": ev["crash"],
                      "missingDeps": ev["missingDeps"] or base.get("missingDeps"),
                      "crashFiles": ev["crashFiles"] or base.get("crashFiles"),
                      "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        elif base.get("phase") == "running":
            stopped_by_user = mark is not None
            tail = _log_tail_after(game_dir, log_start_bytes, 30)
            # Opt-in auto-relaunch: if the game died silently (no crash, no
            # user Stop, no "Stopping!" window-close) within 2 minutes of the
            # menu, relaunch ONCE with a lower fitted heap instead of leaving
            # the user at a dead session. Default off (autoRelaunch opt-in).
            auto = (opts.get("autoRelaunch") and not stopped_by_user
                    and build_id not in _auto_relaunched
                    and proc.returncode in (0, 1) and not ev["crash"]
                    and menu_at is not None
                    and 0 <= time.time() - menu_at <= SILENT_DEATH_WINDOW_S
                    and not any("Stopping!" in ln for ln in tail))
            if auto:
                _auto_relaunched.add(build_id)
                lower = max(2048, int((env.get("xmxMB") or 4096) * 0.8 // 256 * 256))
                logger.warn("launch", f"Silent close {int(time.time() - menu_at)}s after menu — "
                                      f"auto-relaunching once with {lower} MB (autoRelaunch)")
                rel = {**base, "phase": "relaunching", "progress": 54,
                       "stage": f"Silent close detected — relaunching with {lower} MB RAM",
                       "error": None,
                       "closeContext": {"stoppedByUser": False, "code": proc.returncode,
                                        "reason": "Silent death after main menu — auto-relaunch scheduled",
                                        "logTail": tail},
                       "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                write_launch_state(build_dir, rel)
                if on_state:
                    on_state(rel)

                def relaunch():
                    time.sleep(4)
                    try:
                        launch_pack(record, {**opts, "xmxMB": lower, "autoRelaunch": False})
                    except Exception as e:  # noqa: BLE001
                        logger.error("launch", f"auto-relaunch failed: {e}")

                threading.Thread(target=relaunch, daemon=True).start()
                return
            if proc.returncode == 0 and not stopped_by_user:
                # The game closed by itself after reaching the menu (clean
                # window close / System.exit — no crash evidence). Capture the
                # log tail so the close is explainable instead of a bare
                # "Game closed".
                exited = {**base, "phase": "stopped", "stage": "Game closed (no crash)",
                          "closeContext": {"stoppedByUser": False, "code": 0,
                                           "reason": "Game window closed itself; no crash or error lines in the log.",
                                           "logTail": tail},
                          "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
            else:
                exited = {**base, "phase": "stopped",
                          "stage": "Game closed" if proc.returncode == 0 else f"Game exited (code {proc.returncode})",
                          "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        elif proc.returncode not in (0, None):
            exited = {**base, "phase": "error",
                      "stage": f"Game exited unexpectedly (code {proc.returncode}) — see log",
                      "error": f"Game exited unexpectedly (code {proc.returncode}) — see log",
                      "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        else:
            exited = {**base, "phase": "stopped", "stage": "Game closed",
                      "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        write_launch_state(build_dir, exited)
        if on_state:
            on_state(exited)

    threading.Thread(target=lambda: (_wait(proc), on_exit()), daemon=True).start()

    pid = proc.pid or 0
    _running[build_id] = {"pid": pid, "proc": proc, "gameDir": str(game_dir),
                          "logFile": str(log_file),
                          "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "state": state}
    report({**state, "phase": "loading", "progress": 54, "stage": "Starting Minecraft…", "pid": pid,
            "startedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    try:
        _pid_file(build_dir).write_text(str(pid), "utf-8")
    except OSError:
        pass
    logger.ok("launch", f"Game launched (pid {pid}). Log: {log_file}")
    return {"buildId": build_id, "pid": pid, "gameDir": str(game_dir),
            "logFile": str(log_file), "startedAt": _running[build_id]["startedAt"]}


def free_physical_gb() -> float:
    """Available physical RAM (Windows GlobalMemoryStatusEx / fallback)."""
    if _IS_WIN:
        import ctypes
        class _MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        try:
            m = _MS(); m.dwLength = ctypes.sizeof(_MS)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
                return round(m.ullAvailPhys / 1024 ** 3, 2)
        except Exception:
            pass
    return 0.0


def any_other_running(build_id: str) -> bool:
    """True if any OTHER pack has a live game process right now."""
    for bid, r in list(_running.items()):
        if bid != build_id and r.get("proc") and r["proc"].poll() is None:
            return True
    try:
        idx = json.loads((builds_dir() / "index.json").read_text("utf-8"))
    except Exception:
        return False
    for rec in idx:
        bid = rec.get("buildId")
        if bid == build_id or not bid:
            continue
        pid = _read_pid_raw(bid)
        if pid and pid_alive(pid):
            return True
    return False


def _tune_concurrent_options(game_dir, logger) -> None:
    """Cap the pack's FPS via options.txt before launch (render distance is
    left alone if the user already set it low). Only overrides keys that are
    currently missing or higher than the concurrent-safe value."""
    opts_path = Path(game_dir) / "options.txt"
    cur = {}
    if opts_path.exists():
        for line in opts_path.read_text(encoding="utf-8", errors="replace").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                cur[k.strip()] = v.strip()
    changed = {}
    try:
        if int(cur.get("maxFps", 9999)) > 30:
            changed["maxFps"] = "30"
    except ValueError:
        changed["maxFps"] = "30"
    cur.update(changed)
    try:
        opts_path.write_text("\n".join(f"{k}:{v}" for k, v in cur.items()) + "\n", encoding="utf-8")
        if changed:
            logger.info("launch", f"options.txt tuned for concurrent play: {changed}")
    except OSError as e:
        logger.warn("launch", f"could not write tuned options.txt: {e}")


def _log_tail_after(game_dir, log_start_bytes, n):
    """Last n lines of latest.log written since this launch began."""
    try:
        p = Path(game_dir) / "logs" / "latest.log"
        if not p.exists():
            return []
        data = p.read_text(encoding="utf-8", errors="replace")
        if log_start_bytes:
            data = data[log_start_bytes:]
        return data.strip().splitlines()[-n:]
    except OSError:
        return []


def _wait(proc):
    try:
        proc.wait()
    except Exception:
        pass


def stop_pack(build_id: str) -> bool:
    r = _running.get(build_id)
    stopped = False
    if r:
        stopped_state = {**r["state"], "phase": "stopped", "stage": "Stopped", "error": None,
                         "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _stopped_marks[build_id] = stopped_state
        write_launch_state(builds_dir() / build_id, stopped_state)
        _kill_tree(r["proc"])
        _running.pop(build_id, None)
        stopped = True
    else:
        pid = _read_pid_raw(build_id)
        if pid and pid_alive(pid):
            try:
                if _IS_WIN:
                    subprocess.run(["taskkill", "/pid", str(pid), "/T", "/F"],
                                   capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
                else:
                    try:
                        os.kill(pid, 9)
                    except OSError:
                        pass
            except Exception:
                pass
            stopped = True
            # The game was killed from another process: reflect it in the
            # persisted state immediately (no waiter thread here to do it).
            st = read_launch_state(builds_dir() / build_id)
            if st and st.get("phase") in ("running", "loading", "preparing", "installing"):
                write_launch_state(builds_dir() / build_id,
                                   {**st, "phase": "stopped", "stage": "Stopped", "error": None,
                                    "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    if stopped:
        try:
            _pid_file(builds_dir() / build_id).unlink()
        except OSError:
            pass
    else:
        st = read_launch_state(builds_dir() / build_id)
        if st and st.get("phase") in ("preparing", "installing") and _read_pid_raw(build_id) is None:
            try:
                launch_state_path(builds_dir() / build_id).unlink()
            except OSError:
                pass
    return stopped


def _visual_files(record: dict) -> dict:
    """Shaders + resource packs recorded on the build (used at launch).

    Shaders go to shaders/, resource packs to resourcePacks/ — never mixed
    (a shader zip copied into resourcepacks/ is ignored by the game and the
    shaderpacks folder stays empty).
    """
    shaders = []
    resource_packs = []
    for s in record.get("selections") or []:
        if not s.get("selected", True):
            continue
        if s.get("projectType") == "shader" and s.get("downloadPath"):
            shaders.append(s["downloadPath"])
        elif s.get("projectType") == "resourcepack" and s.get("downloadPath"):
            resource_packs.append(s["downloadPath"])
    return {"shaders": shaders, "resourcePacks": resource_packs}
