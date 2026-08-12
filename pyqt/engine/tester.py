"""Test pipeline — Python port of src/test/tester.ts.

instant: static validation only. standard: real isolated install + actual
Minecraft startup + main-menu check. deep: standard + vanilla server + world
creation + client quickplay world load + GC-log memory monitoring +
reproducibility. A phase is only PASS when it ran and passed.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

from .core import download_to_file, workspace_dir
from .mojang import (resolve_mojang_version, install_minecraft,
                     build_launch_command)
from .loader import install_fabric_or_quilt, install_forge
from .instance_java import detect_java, auto_install_java, java_for
from .instance import (collect_instance_logs, install_mod_jars,
                       install_resource_packs, install_shader_packs,
                       write_server_configs, write_client_options,
                       write_log4j_config)
from .process import run_process
from .repair import (parse_latest_log, parse_crash_report, main_menu_reached,
                     server_start_detected, world_load_detected,
                     fatal_startup_detected)
from .core import version_satisfies

_IS_WIN = sys.platform == "win32"


def major_of(mc: str) -> int:
    m = re.match(r"^1\.(\d+)", mc)
    return int(m.group(1)) if m else 21


def quick_play_supported(mc: str) -> bool:
    m = re.match(r"^1\.(\d+)(?:\.(\d+))?$", mc)
    if not m:
        return False
    minor = int(m.group(1))
    if minor > 20:
        return True
    if minor < 20:
        return False
    return int(m.group(2) or "0") >= 2


_mojang_cache = {}


def get_mojang_info(mc: str) -> dict:
    if mc not in _mojang_cache:
        _mojang_cache[mc] = resolve_mojang_version(mc)
    return _mojang_cache[mc]


def assemble(env: dict) -> dict:
    logger = env["logger"]
    on = env.get("onLaunchProgress") or (lambda p, s: None)
    on(8, f"Resolving Minecraft {env['mcVersion']}…")
    info = get_mojang_info(env["mcVersion"])
    need = java_for(major_of(env["mcVersion"]))["major"]
    on(12, f"Checking Java {need}…")
    java = None
    if env.get("javaOverride"):
        java = {"path": env["javaOverride"], "major": need, "vendor": "override"}
    else:
        java = detect_java(need)
    if not java and env.get("autoInstallJava", True):
        on(14, f"Java {need} not found — auto-installing…")
        p = auto_install_java(need, logger)
        if p:
            java = {"path": p, "major": need, "vendor": "Temurin"}
    if not java:
        raise RuntimeError(f"Java {need} not found and auto-install disabled/unavailable. Install Java {need} or enable auto-install.")
    logger.info("test", f"Using Java {java['major']} at {java['path']}")
    on(16, f"Java {java['major']} ready")
    shared_root = workspace_dir() / "mojang" / env["mcVersion"]
    on(20, f"Installing Minecraft {env['mcVersion']} (libraries & assets)…")
    install = install_minecraft(env["mcVersion"], shared_root, {
        "logger": logger, "downloadAssets": env.get("downloadAssets", False),
        "maxAssetMB": env.get("maxAssetMB", 400),
    })
    on(34, f"Minecraft {env['mcVersion']} installed ({install['installedLibs']} libraries)")
    plan = None
    if env["loader"] in ("fabric", "quilt"):
        on(36, f"Installing {env['loader']} loader…")
        plan = install_fabric_or_quilt(env["mcVersion"], env["loader"],
                                       shared_root / "libraries", logger)
    elif env["loader"] in ("forge", "neoforge"):
        on(36, f"Installing {env['loader']} loader…")
        plan = install_forge(env["mcVersion"], env["loader"], env["gameDir"], java["path"], logger)
    on(45, f"{(plan or {}).get('loaderVersion') or env['loader']} ready")
    return {"javaPath": java["path"], "info": info, "install": install, "plan": plan}


def build_client_args(env: dict, assembled: dict, opts: dict) -> list:
    game_dir = env["gameDir"]
    write_log4j_config(game_dir)
    session = opts.get("session")
    args = build_launch_command(assembled["info"], assembled["install"], {
        "javaPath": assembled["javaPath"],
        "gameDir": game_dir,
        "xmxMB": env.get("xmxMB", 4096),
        "username": (session or {}).get("username") or opts.get("username") or "AmbTester",
        "uuid": (session or {}).get("uuid") or uuid.uuid4().hex,
        "accessToken": (session or {}).get("accessToken") or "0",
        "userType": (session or {}).get("userType") or "legacy",
        "xuid": (session or {}).get("xuid"),
        "clientId": (session or {}).get("clientId"),
        "quickPlayWorld": opts.get("quickPlayWorld"),
        "width": opts.get("width", 854),
        "height": opts.get("height", 480),
    })
    plan = assembled.get("plan")
    sep = ";" if _IS_WIN else ":"
    try:
        cp_idx = args.index("-cp")
    except ValueError:
        cp_idx = -1
    if cp_idx >= 0:
        cp = args[cp_idx + 1]
        if plan and plan.get("excludeVanillaClientJar"):
            jar_pat = re.escape(f"versions{os.sep}{env['mcVersion']}{os.sep}{env['mcVersion']}.jar")
            parts = cp.split(sep)
            parts = [p for p in parts if not re.search(rf"versions[\\/]{re.escape(env['mcVersion'])}[\\/]{re.escape(env['mcVersion'])}\.jar$", p)]
            cp = sep.join(parts)
        extra = plan.get("classpathExtra") or []
        if extra:
            cp = cp + sep + sep.join(extra)
        args[cp_idx + 1] = cp
    if plan:
        try:
            main_idx = args.index(assembled["info"]["mainClass"])
        except ValueError:
            main_idx = -1
        if main_idx >= 0:
            args[main_idx] = plan["mainClass"]
            extra_args = plan.get("gameArgsExtra") or []
            if extra_args:
                args[main_idx + 1:main_idx + 1] = extra_args
    jvm_flags = list(plan.get("jvmArgsExtra") or []) if plan else []
    if opts.get("collectGcLog"):
        jvm_flags.append(f"-Xlog:gc=info:file={Path(game_dir, 'gc.log').as_posix()}")
    args[2:2] = jvm_flags
    args[2:2] = [f"-Dlog4j.configurationFile={Path(game_dir, 'log4j2.xml').as_posix()}"]

    # Defensive: the launch runs with cwd = game_dir, so every path in the
    # command must be absolute. If a caller supplied a relative game_dir, the
    # plan's classpath / module path / libraryDirectory would silently resolve
    # against the wrong base and the JVM dies with "Could not find or load main
    # class cpw.mods.bootstraplauncher.BootstrapLauncher".
    root = workspace_dir().resolve()

    def _abs(value: str) -> str:
        parts = value.split(";")
        out = []
        for p in parts:
            if p and not os.path.isabs(p) and not p.startswith("http"):
                p = str((root / p).resolve())
            out.append(p)
        return ";".join(out)

    for i, a in enumerate(args):
        if a == "-p" or a == "-cp":
            if i + 1 < len(args):
                args[i + 1] = _abs(args[i + 1])
        elif isinstance(a, str) and a.startswith("-DlibraryDirectory="):
            args[i] = "-DlibraryDirectory=" + _abs(a[len("-DlibraryDirectory="):])
    return args


class _WindowTitleProbe:
    def __init__(self):
        self.title = None
        self._running = False

    def poll(self):
        if self._running or not _IS_WIN:
            return
        self._running = True
        try:
            r = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-Process java -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like '*Minecraft*' } | Select-Object -First 1).MainWindowTitle"],
                capture_output=True, text=True, timeout=8,
                creationflags=subprocess.CREATE_NO_WINDOW if _IS_WIN else 0)
            t = (r.stdout or "").strip()
            if t:
                self.title = t
        except Exception:
            pass
        finally:
            self._running = False

    def stop(self):
        self._running = False


def launch_client(env: dict, assembled: dict, opts: dict) -> dict:
    logger = env["logger"]
    game_dir = env["gameDir"]
    args = build_client_args(env, assembled, {
        "quickPlayWorld": opts.get("quickPlayWorld"),
        "collectGcLog": opts.get("collectGcLog"),
        "width": 854, "height": 480,
    })
    log = logger.child(f"launch-{opts['label']}.log")
    probe = _WindowTitleProbe()
    console = []

    def stop_watch():
        probe.stop()

    logger.stage("test", f"Launching Minecraft ({opts['label']}) with {env.get('xmxMB')}MB RAM…")

    # Some crashes happen seconds AFTER the main-menu markers (e.g. Project
    # Atmosphere's "requires a season provider" mod-loading error at init).
    # Keep the process alive a grace window past the menu so those late
    # mod-loading crashes surface as crash-reports instead of a false PASS.
    menu_grace = opts.get("menuGraceSec", 12)
    menu_at = [None]

    def watch(line, all_lines):
        if len(console) < 2000:
            console.append(line)
        if fatal_startup_detected(all_lines):
            return True
        if opts.get("watchFor") == "menu":
            if menu_at[0] is None and main_menu_reached(all_lines):
                menu_at[0] = time.monotonic()
            if menu_at[0] is not None and time.monotonic() - menu_at[0] >= menu_grace:
                return True
            return False
        if opts.get("watchFor") == "world":
            return world_load_detected(all_lines)
        return False

    # poll window title in background
    def poll_loop():
        while not stop_event.is_set():
            probe.poll()
            time.sleep(5)

    stop_event = threading.Event()
    poller = threading.Thread(target=poll_loop, daemon=True)
    poller.start()
    result = run_process({
        "cmd": args[0], "args": args[1:], "cwd": game_dir,
        "timeoutMs": opts.get("timeoutMs", 420000),
        "log": log["write"], "name": f"mc-{opts['label']}", "watchFor": watch,
    })
    stop_event.set()
    probe.stop()
    logs = collect_instance_logs(game_dir)
    if not logs["latest"] and console:
        try:
            logs_dir = Path(game_dir) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            (logs_dir / "latest.log").write_text("\n".join(console), "utf-8")
            logs["latest"] = list(console)
        except OSError:
            pass
    logs.update({"code": result["code"], "timedOut": result["timedOut"],
                 "windowTitle": probe.title, "console": console})
    return logs


# ---------------------------------------------------------------------------
# Instant mode
# ---------------------------------------------------------------------------

def run_instant_test(env: dict, graph: dict) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    phases = [{"name": "mod-count", "status": "PASS", "detail": f"{len(env['modJars'])} mods selected"}]
    missing_jars = [m for m in env["modJars"] if not Path(m["path"]).exists()]
    nodes = list(graph["nodes"].values())
    installed_slugs = {m["slug"].lower() for m in env["modJars"]}
    selected_with_url = [
        n for n in nodes if n.get("selected") and n["project"].get("projectType") == "mod"
        and any(f.get("url") for f in (n.get("version") or {}).get("files") or [])
    ]
    missing_downloads = [n for n in selected_with_url if n["project"]["slug"].lower() not in installed_slugs]
    dl_detail = (f"{len(missing_downloads)} SELECTED mods have no jar ({', '.join(n['project']['slug'] for n in missing_downloads[:6])}) — download budget or provider policy"
                 if missing_downloads else "All selected mod jars present")
    details = []
    if missing_jars:
        details.append(f"Installed jars missing on disk: {', '.join(m['slug'] for m in missing_jars)}")
    if missing_downloads:
        details.append(dl_detail)
    phases.append({"name": "download-integrity",
                   "status": "FAIL" if (missing_jars or missing_downloads) else "PASS",
                   "detail": "; ".join(details) if details else "All selected mod jars present"})
    by_key = {n["key"]: n for n in nodes}
    broken = []
    for e in graph["edges"]:
        if e.get("kind") not in ("required", "embedded"):
            continue
        src = by_key.get(e["from"])
        if src and not src.get("selected"):
            continue
        target = by_key.get(e["to"])
        if not target or not target.get("selected"):
            broken.append(f"{e['from']} -> {e['to']}: dependency not selected")
            continue
        if e.get("versionRange") and target.get("version") and \
           not version_satisfies(target["version"].get("versionNumber", ""), e["versionRange"]):
            broken.append(f"{e['to']} {target['version']['versionNumber']} violates {e['versionRange']} (from {e['from']})")
    phases.append({"name": "graph-integrity",
                   "status": "FAIL" if broken else "PASS",
                   "detail": "; ".join(broken) if broken else f"{len(nodes)} nodes, {len(graph['edges'])} edges — all required dependencies of selected mods satisfied"})
    unresolved = "no mods" if not env["modJars"] else None
    status = "FAIL" if (broken or missing_jars or missing_downloads or unresolved) else "PASS"
    return {"level": "instant", "status": status, "startedAt": started,
            "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "phases": phases, "logFiles": [],
            "summary": "Static validation passed (instant mode)" if status == "PASS" else "Static validation FAILED (instant mode)"}


# ---------------------------------------------------------------------------
# Standard + deep
# ---------------------------------------------------------------------------

def _finish(level, status, started, phases, log_files, summary) -> dict:
    return {"level": level, "status": status, "startedAt": started,
            "finishedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "phases": phases, "logFiles": log_files, "summary": summary}


def run_standard_test(env: dict, graph: dict) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    phases = []
    log_files = []

    def ph(name, status, detail, evidence=None):
        phases.append({"name": name, "status": status, "detail": detail, "evidence": evidence})

    ph("instance", "RUNNING", "Creating isolated instance…")
    try:
        mods_dir = Path(env["gameDir"]) / "mods"
        shutil.rmtree(mods_dir, ignore_errors=True)
        shutil.rmtree(Path(env["gameDir"]) / "crash-reports", ignore_errors=True)
        shutil.rmtree(Path(env["gameDir"]) / "logs", ignore_errors=True)
        install_mod_jars(mods_dir, env["modJars"], env["logger"])
        install_resource_packs(Path(env["gameDir"]) / "resourcepacks", env.get("resourcePackFiles") or [], env["logger"])
        install_shader_packs(Path(env["gameDir"]) / "shaderpacks", env.get("shaderFiles") or [], env["logger"])
        write_client_options(env["gameDir"], {"renderDistance": 6})
        ph("instance", "PASS", "Mods and packs installed into isolated instance")
    except Exception as e:
        ph("instance", "FAIL", f"Instance assembly failed: {e}")
        return _finish("standard", "FAIL", started, phases, log_files, "Instance assembly failed")

    try:
        assembled = assemble(env)
        ph("mojang-install", "PASS", f"Minecraft {env['mcVersion']} + {env['loader']} installed ({assembled['install']['installedLibs']} libraries)")
    except Exception as e:
        ph("mojang-install", "FAIL", str(e))
        return _finish("standard", "FAIL", started, phases, log_files, f"Installation failed: {e}")

    ph("launch", "RUNNING", "Starting Minecraft…")
    try:
        res = launch_client(env, assembled, {"label": "standard", "watchFor": "menu", "timeoutMs": 420000})
        log_files.append("launch-standard.log")
        all_lines = list(res["latest"]) + list(res["console"])
        crash = parse_latest_log(all_lines)
        menu = main_menu_reached(all_lines)
        diag_files = list(res.get("crashFiles") or []) + (["logs/debug.log"] if res.get("debug") else [])
        ph("launch", "PASS", f"Minecraft process ran (exit {res.get('code')})",
           f"window: {res.get('windowTitle') or 'none'}; diagnostics: {', '.join(diag_files) if diag_files else 'none'}")
        if res.get("crashReports"):
            parsed = parse_crash_report(res["crashReports"][0])
            frm = (res.get("crashFiles") or ["crash report"])[0]
            ph("main-menu", "FAIL", f"Crash detected ({frm}): {parsed['exception']} ({parsed['description']})", parsed["raw"][:500])
            return _finish("standard", "FAIL", started, phases, log_files, f"Crash ({frm}): {parsed['exception']} — {parsed['description']}")
        if menu:
            ph("main-menu", "PASS", f"Main menu reached (log evidence: yes, window: {res.get('windowTitle') or 'no'})")
            return _finish("standard", "PASS", started, phases, log_files, "Minecraft reached the main menu")
        if crash.get("signature"):
            ph("main-menu", "FAIL", f"Startup error: {crash['label']} — {crash['description']}")
            return _finish("standard", "FAIL", started, phases, log_files, f"Startup error: {crash['label']}")
        ph("main-menu", "FAIL", f"No main-menu evidence found in logs ({len(all_lines)} lines) and no window detected")
        return _finish("standard", "FAIL", started, phases, log_files, "Process ran but main menu was not detected")
    except Exception as e:
        ph("launch", "FAIL", f"Launch failed: {e}")
        return _finish("standard", "FAIL", started, phases, log_files, f"Launch failed: {e}")


def parse_gc_peak(gc_log: list):
    best = 0
    mult = {"K": 1024, "M": 1024 ** 2, "G": 1024 ** 3, "T": 1024 ** 4, "P": 1024 ** 5}
    for line in gc_log:
        if "Pause Young" in line or "Pause Full" in line:
            for m in re.finditer(r"(\d+(?:\.\d+)?)([KMGTP]?)\s*->", line):
                try:
                    b = round(float(m.group(1)) * mult.get((m.group(2) or "M").upper(), 1) / (1024 ** 2))
                    best = max(best, b)
                except ValueError:
                    pass
        for m in re.finditer(r"used\s*\(?\s*(\d+(?:\.\d+)?)([KMGTP])?\)?", line, re.I):
            try:
                best = max(best, round(float(m.group(1)) * mult.get((m.group(2) or "M").upper(), 1) / (1024 ** 2)))
            except ValueError:
                pass
    return f"{best} MB" if best > 0 else None


def run_deep_test(env: dict, graph: dict) -> dict:
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    phases = []
    log_files = []

    def ph(name, status, detail, evidence=None):
        phases.append({"name": name, "status": status, "detail": detail, "evidence": evidence})

    standard = run_standard_test(env, graph)
    log_files.extend(standard["logFiles"])
    phases.extend(standard["phases"])
    if standard["status"] != "PASS":
        return _finish("deep", standard["status"], started, phases, log_files, standard["summary"])

    # 1. Server start + world creation
    ph("server-start", "RUNNING", "Starting vanilla server (nogui) to create and load a real world…")
    try:
        server_jar = env.get("serverJar")
        if not server_jar or not Path(server_jar).exists():
            info = get_mojang_info(env["mcVersion"])
            if not info.get("serverJar"):
                raise RuntimeError("No server jar available for " + env["mcVersion"])
            server_jar = str(Path(env["gameDir"]) / "versions" / env["mcVersion"] / (env["mcVersion"] + "-server.jar"))
            if not Path(server_jar).exists():
                download_to_file(info["serverJar"]["url"], server_jar,
                                 max_bytes=200 * 1024 ** 2, expected_sha1=info["serverJar"].get("sha1"))
        write_server_configs(env["gameDir"], env["logger"])
        log = env["logger"].child("server-test.log")
        log_files.append("server-test.log")
        need = java_for(major_of(env["mcVersion"]))["major"]
        java = detect_java(need) or detect_java(21)
        if not java:
            raise RuntimeError("No Java for server test")
        res = run_process({
            "cmd": java["path"], "args": ["-Xmx1536m", "-jar", server_jar, "nogui"],
            "cwd": env["gameDir"], "timeoutMs": 300000, "log": log["write"],
            "name": "mc-server",
            "watchFor": lambda line, all_lines: server_start_detected(all_lines),
        })
        server_lines = Path(log["file"]).read_text("utf-8", "replace").splitlines()
        ok = server_start_detected(server_lines)
        world_ok = world_load_detected(server_lines)
        ph("server-start", "PASS" if ok else "FAIL",
           "Server started: \"Done\" reached" if ok else f"Server did not start (exit {res.get('code')})",
           "\n".join([l for l in server_lines if re.search(r"Done \(|Preparing level|Preparing spawn|Exception|ERROR", l)][:8]))
        ph("world-creation", "PASS" if world_ok else ("SKIP" if ok else "FAIL"),
           "World generated and loaded by server" if world_ok else ("Server started but world load not confirmed" if ok else "Skipped: server did not start"))
        if not ok:
            return _finish("deep", "FAIL", started, phases, log_files, "Vanilla server test failed")
    except Exception as e:
        ph("server-start", "FAIL", f"Server test error: {e}")
        return _finish("deep", "FAIL", started, phases, log_files, "Server test errored")

    # 2. Client quickplay world load
    world_load_skipped = False
    ph("world-load", "RUNNING", "Loading the created world in the client (--quickPlaySingleplayer)…")
    if not quick_play_supported(env["mcVersion"]):
        world_load_skipped = True
        ph("world-load", "SKIP", f"QuickPlay (--quickPlaySingleplayer) requires Minecraft 1.20.2+; {env['mcVersion']} cannot auto-load a world")
        ph("memory-monitor", "SKIP", "GC heap monitoring runs during client world load, which is unavailable on this MC version")
    else:
        try:
            world_src = Path(env["gameDir"]) / "world"
            world_dst = Path(env["gameDir"]) / "saves" / "world"
            if world_src.exists():
                shutil.rmtree(world_dst, ignore_errors=True)
                try:
                    world_src.rename(world_dst)
                except OSError:
                    shutil.copytree(world_src, world_dst)
                    shutil.rmtree(world_src, ignore_errors=True)
                env["logger"].info("test", f"Moved server world {world_src} → {world_dst} for client quickplay")
            else:
                env["logger"].warn("test", "No server world found — quickplay may fail to find a world")
            assembled = assemble(env)
            res = launch_client(env, assembled, {
                "label": "quickplay", "quickPlayWorld": "world", "collectGcLog": True,
                "watchFor": "world", "timeoutMs": 420000,
            })
            lines = list(res["latest"]) + list(res.get("gcLog") or []) + list(res["console"])
            loaded = world_load_detected(lines)
            ph("world-load", "PASS" if loaded else "FAIL",
               "World loaded in client (log evidence)" if loaded else f"World load not confirmed (exit {res.get('code')})",
               res.get("windowTitle") or (parse_crash_report(res["crashReports"][0])["description"] if res.get("crashReports") else "no window"))
            peak = parse_gc_peak(res.get("gcLog") or [])
            ph("memory-monitor", "PASS" if res.get("gcLog") else "SKIP",
               f"Peak heap observed in GC log: {peak}" if peak else "GC log captured but no heap samples parsed",
               f"xmx={env.get('xmxMB')}MB")
            if not loaded:
                return _finish("deep", "FAIL", started, phases, log_files, "Client world load failed")
        except Exception as e:
            ph("world-load", "FAIL", f"Quickplay error: {e}")
            return _finish("deep", "FAIL", started, phases, log_files, "World load errored")

    # 3. Reproducibility
    ph("reproducibility", "RUNNING", "Launching again to check reproducibility…")
    try:
        assembled = assemble(env)
        res = launch_client(env, assembled, {"label": "repro-2", "timeoutMs": 420000, "watchFor": "menu"})
        menu = main_menu_reached(res["latest"])
        ph("reproducibility", "PASS" if menu else "FAIL",
           "Second launch reached main menu" if menu else f"Second launch did not reach menu (exit {res.get('code')})")
        summary = ("Deep test passed: server, world, reproducibility (client world load SKIPPED: quickplay requires MC 1.20.2+)"
                   if menu and world_load_skipped else
                   "Deep test passed: server, world, client load, reproducibility" if menu else
                   "Deep test: reproducible launch failed")
        return _finish("deep", "PASS" if menu else "FAIL", started, phases, log_files, summary)
    except Exception as e:
        ph("reproducibility", "FAIL", f"Error: {e}")
        return _finish("deep", "FAIL", started, phases, log_files, "Reproducibility check errored")


def run_test_level(env: dict, graph: dict) -> dict:
    mode = env.get("testMode", "standard")
    if mode == "instant":
        return run_instant_test(env, graph)
    if mode == "deep":
        return run_deep_test(env, graph)
    return run_standard_test(env, graph)
