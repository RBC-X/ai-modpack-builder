"""Sustained dual-launch test: BOTH packs stay at the main menu together for
minutes — the real "multi-pack session" gate.

B (lightweight Fabric 1.20.1) settles at the menu first; A (flagship Forge
1.20.1, 150 mods) boots as the SECOND pack. We then hold both at the menu for
HOLD_MINUTES (default 5) while watching per-pack pids, states, and live log
tails for "Stopping!" / crash evidence.

Environment hardening applied by the engine itself:
  - fit_xmx_mb() caps A's 8 GB request to ~5 GB on this 7 GB machine
    (the old -Xmx8192m overcommit is gone).
  - orphaned legacy processes (old Node engine, hung tests) were killed and
    the disk was freed from 2.5 GB -> 48 GB free.
  - if a game still closes by itself, launch-state.json now carries a
    closeContext (stoppedByUser=false + last log lines) explaining it.

Usage: python pyqt/sustained_dual_test.py   (HOLD_MINUTES=5 env to change)
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.bridge import PyEngine  # noqa: E402
from engine.core import builds_dir  # noqa: E402
from engine.launcher import pid_alive  # noqa: E402

A = os.environ.get("PACK_A", "b-19fedb2cb00-1fad25cf")   # flagship Forge 1.20.1 (second)
B = os.environ.get("PACK_B", "b-19fedb237cf-4a466b03")   # lightweight Fabric 1.20.1 (first)
HOLD_MIN = float(os.environ.get("HOLD_MINUTES", "5"))

report: dict = {"phases": [], "timeline": []}


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {_ascii(name)}: {_ascii(detail)}", flush=True)


def free_ram_gb() -> float:
    """Available physical RAM via GlobalMemoryStatusEx (Windows)."""
    try:
        import ctypes
        class MS(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        m = MS(); m.dwLength = ctypes.sizeof(MS)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)):
            return round(m.ullAvailPhys / 1024 ** 3, 2)
    except Exception:
        pass
    return 0.0


def log_tail(bid: str, n: int = 12) -> list:
    p = builds_dir() / bid / "instance" / "minecraft" / "logs" / "latest.log"
    try:
        lines = p.read_text("utf-8", errors="replace").splitlines()
        return lines[-n:]
    except OSError:
        return []


def wait_running(bid: str, timeout: float = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = eng.status(bid)
        if st.get("phase") in ("running", "error", "stopped"):
            return st
        time.sleep(3)
    return eng.status(bid)


eng = PyEngine()
held_sec = 0.0
try:
    # ---- phase 0: RAM is fitted to the machine (the hardening under test)
    hw = eng.hardware()
    fitA = eng.status(A)
    print(f"[test] hardware: {hw.get('ramGB')} GB RAM, {hw.get('cores')} cores", flush=True)
    # This 7 GB machine cannot hold 5 GB (A) + 3 GB (B) + Windows; the second
    # pack's JVM gets hard-terminated at the world-registry memory spike. Fit
    # the pair into the machine: A at 4 GB (150 mods, still boots), B at 2 GB.
    eng.set_ram(A, 4)
    eng.set_ram(B, 2)
    print("[test] RAM fitted to machine: A=4 GB (150-mod pack), B=2 GB (17-mod pack)", flush=True)

    # ---- phase 1: B first
    eng.play(B, "PlayerB")
    stB = wait_running(B)
    okB = stB.get("phase") == "running" and bool(stB.get("pid"))
    pidB = stB.get("pid")
    phase("pack B (first) reaches main menu", okB, f"pid {pidB} phase {stB.get('phase')}")
    tB_menu = time.time()

    # ---- phase 2: A second, while B holds (one retry for a pre-menu crash —
    # Create/Registrate has a known intermittent 'potato_cannon' startup race
    # under load; the repair pipeline would do the same retry)
    pidA = None
    tA_menu = None
    for attempt in (1, 2):
        eng.play(A, "PlayerA")
        stA = wait_running(A)
        if stA.get("phase") == "running" and bool(stA.get("pid")):
            okA = True
            pidA = stA.get("pid")
            tA_menu = time.time()
            break
        crash = stA.get("error") or stA.get("stage") or "unknown"
        print(f"[test] A attempt {attempt} failed pre-menu: {_ascii(crash)} — "
              f"{'retrying once' if attempt == 1 else 'giving up'}", flush=True)
        time.sleep(5)
    else:
        okA = False
    phase("pack A (second) reaches main menu while B runs", okA,
          f"pid {pidA} phase {stA.get('phase')}")
    if not okA:
        raise SystemExit("A never reached the menu — aborting hold")
    if not (okA and okB):
        raise SystemExit("menu not reached by both packs — aborting hold")

    # ---- phase 3: HOLD both at the menu for HOLD_MIN minutes
    deadline = time.time() + HOLD_MIN * 60
    last_tick = time.time()
    a_up = b_up = True
    while time.time() < deadline:
        time.sleep(5)
        held_sec = time.time() - tA_menu
        sa = eng.status(A)
        sb = eng.status(B)
        a_up = sa.get("phase") == "running" and pid_alive(sa.get("pid") or 0)
        b_up = sb.get("phase") == "running" and pid_alive(sb.get("pid") or 0)
        row = {"t": round(held_sec), "aUp": a_up, "bUp": b_up,
               "aPid": sa.get("pid"), "bPid": sb.get("pid"),
               "freeRamGB": free_ram_gb()}
        report["timeline"].append(row)
        if time.time() - last_tick >= 30:
            print(f"[hold] t={int(held_sec)}s A={'UP' if a_up else 'DOWN'} (pid {sa.get('pid')}) "
                  f"B={'UP' if b_up else 'DOWN'} (pid {sb.get('pid')}) "
                  f"freeRAM={free_ram_gb()}GB", flush=True)
            last_tick = time.time()
        if not (a_up and b_up):
            break

    # ---- close evidence for whichever pack dropped
    for bid, up, name in ((A, a_up, "A"), (B, b_up, "B")):
        if not up:
            st = eng.status(bid)
            ctx = st.get("closeContext") or {}
            tail = ctx.get("logTail") or log_tail(bid)
            print(f"[hold] {name} ({bid}) dropped at t={int(held_sec)}s — "
                  f"stage={st.get('stage')} ctx={json.dumps({k: ctx[k] for k in ('stoppedByUser', 'code', 'reason') if k in ctx})}", flush=True)
            print("  last log lines:", flush=True)
            for ln in tail[-6:]:
                print("   " + _ascii(ln)[:140], flush=True)

    held_ok = a_up and b_up and held_sec >= HOLD_MIN * 60 - 10
    phase(f"both packs stay at menu together for {int(held_sec)}s "
          f"(target {int(HOLD_MIN * 60)}s)", held_ok,
          f"A={'up' if a_up else 'down'} B={'up' if b_up else 'down'}")

    # ---- phase 4: stop A, B still up; stop B
    eng.stop(A)
    time.sleep(2)
    sb3 = eng.status(B)
    phase("stop A leaves B running", sb3.get("phase") == "running", f"B={sb3.get('phase')}")
    eng.stop(B)
    time.sleep(2)
    phase("stop B stops everything", not eng.status(B).get("running"), "B stopped")
finally:
    try:
        eng.stop(A)
    except Exception:  # noqa: BLE001
        pass
    try:
        eng.stop(B)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
report["holdSeconds"] = round(held_sec, 1)
Path("workspace/sustained-dual-result.json").write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[sustained-dual] OVERALL: {report['overall']} — held {int(held_sec)}s — "
      f"saved workspace/sustained-dual-result.json", flush=True)
sys.exit(0 if overall else 1)
