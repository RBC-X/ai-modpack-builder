"""Process runner — Python port of src/process/runner.ts.

Spawns a child (e.g. Java) inside an isolated cwd, streams stdout/stderr to a
log sink, enforces a timeout + stall detection, kills the whole tree on
timeout, and always reports the exit code.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

_IS_WIN = sys.platform == "win32"


def run_process(opts: dict) -> dict:
    """opts: {cmd, args, cwd, env?, timeoutMs, log(line), onExit?, name?,
    watchFor?(line, allLines)->bool, stallMs?}"""
    started = time.time()
    log = opts["log"]
    cwd = opts.get("cwd")
    env = {**os.environ, **(opts.get("env") or {})}
    all_lines: list = []
    state = {"timedOut": False, "earlyExit": False, "stalled": False,
             "code": None, "signal": None, "stdoutBytes": 0, "done": False}
    lock = threading.Lock()
    kill_triggered = [False]

    flags = subprocess.CREATE_NO_WINDOW if _IS_WIN else 0
    try:
        proc = subprocess.Popen(
            [opts["cmd"]] + list(opts.get("args") or []),
            cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL, creationflags=flags, text=True,
            errors="replace", bufsize=1,
        )
    except Exception as e:
        log(f"SPAWN ERROR: {e}")
        return {"code": None, "signal": None, "timedOut": False,
                "durationMs": int((time.time() - started) * 1000), "stdoutBytes": 0}

    def kill_tree():
        with lock:
            if kill_triggered[0]:
                return
            kill_triggered[0] = True
        try:
            if _IS_WIN:
                subprocess.run(["taskkill", "/pid", str(proc.pid), "/T", "/F"],
                               capture_output=True, creationflags=flags)
            else:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except Exception:
                    proc.kill()
        except Exception as e:
            log(f"[runner] kill failed: {e}")
            try:
                proc.kill()
            except Exception:
                pass

    def finish_early():
        with lock:
            if state["done"]:
                return
            state["earlyExit"] = True
        log("[runner] watched condition met — stopping process")
        kill_tree()

    timeout_ms = opts.get("timeoutMs", 30000)
    stall_ms = opts.get("stallMs", 120000)
    stall_check_every = min(15000, max(500, stall_ms // 2))

    def watchdog():
        while not state["done"]:
            time.sleep(stall_check_every / 1000.0)
            with lock:
                if state["done"] or state["earlyExit"]:
                    return
            elapsed = (time.time() - started) * 1000
            if elapsed > timeout_ms:
                with lock:
                    state["timedOut"] = True
                log(f"[runner] TIMEOUT after {int(elapsed)}ms — killing process tree")
                kill_tree()
                return
            if time.time() - last_output[0] > stall_ms:
                with lock:
                    state["timedOut"] = True
                    state["stalled"] = True
                log(f"[runner] STALL — no output for {stall_ms // 1000}s; killing process tree (possible silent hang)")
                kill_tree()
                return

    last_output = [time.time()]

    def pump(stream, is_err):
        try:
            for line in stream:
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                last_output[0] = time.time()
                with lock:
                    if state["earlyExit"]:
                        return
                    all_lines.append(line)
                    if len(all_lines) > 2000:
                        del all_lines[: len(all_lines) - 2000]
                    state["stdoutBytes"] += len(line)
                try:
                    if opts.get("watchFor") and opts["watchFor"](line, all_lines):
                        finish_early()
                        return
                finally:
                    try:
                        log(line)
                    except Exception:
                        pass
        except Exception:
            pass

    threads = []
    if proc.stdout:
        t = threading.Thread(target=pump, args=(proc.stdout, False), daemon=True)
        t.start()
        threads.append(t)
    if proc.stderr:
        t = threading.Thread(target=pump, args=(proc.stderr, True), daemon=True)
        t.start()
        threads.append(t)

    w = threading.Thread(target=watchdog, daemon=True)
    w.start()

    code, sig = proc.wait(), None
    for t in threads:
        t.join(timeout=5)
    with lock:
        state["done"] = True
        state["code"] = code
    code, sig = proc.returncode, None
    if state["timedOut"]:
        sig = "SIGKILL"
    log(f"[runner] process exited code={code} signal={sig}"
        + (" (timed out)" if state["timedOut"] else "")
        + (" (early exit)" if state["earlyExit"] else "")
        + (" (stalled)" if state["stalled"] else ""))
    if opts.get("onExit"):
        try:
            opts["onExit"](code, sig)
        except Exception:
            pass
    return {"code": code, "signal": sig, "timedOut": state["timedOut"],
            "durationMs": int((time.time() - started) * 1000),
            "stdoutBytes": state["stdoutBytes"], "earlyExit": state["earlyExit"]}
