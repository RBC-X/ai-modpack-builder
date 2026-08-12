"""Definitive lite-pack verification with the opt-in auto-relaunch exercised.

1. Enables settings.autoRelaunch on the lite pack (silent deaths within 2 min
   of the menu trigger ONE engine-side relaunch at 80% heap).
2. Plays the pack through the engine (menu_at tracked engine-side).
3. Watches status() + the pid file every 5 s: records menu evidence, pid
   transitions (relaunch events), phase transitions, and free RAM.
4. Holds HOLD_MIN minutes from the LAST menu (a relaunch resets the clock).
5. Writes workspace/lite-relaunch-hold-result.json with the real timeline.

Usage: python pyqt/lite_relaunch_hold.py b-lite-ef38acfd [hold_minutes]
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
from engine.launcher import pid_alive  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
HOLD_MIN = float(os.environ.get("HOLD_MINUTES", sys.argv[2] if len(sys.argv) > 2 else "5"))
ROOT = Path(HERE).parent
report: dict = {"phases": [], "timeline": [], "relaunches": [], "pack": PACK}


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {_ascii(name)}: {_ascii(detail)}", flush=True)


def free_ram_gb() -> float:
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
    except Exception:  # noqa: BLE001
        pass
    return 0.0


def read_pid() -> int:
    try:
        return int((ROOT / "workspace" / "builds" / PACK / "logs" / "launch-play.pid").read_text().strip())
    except Exception:  # noqa: BLE001
        return 0


eng = PyEngine()
eng.set_auto_relaunch(PACK, True)
print(f"[test] autoRelaunch ON for {PACK}; record ramGB={eng.status(PACK).get('ramGB')}", flush=True)
t0 = time.time()
eng.play(PACK, "PlayerLite")

last_pid = 0
last_phase = None
menu_at = None
boot_deadline = t0 + 1500
try:
    # ---- wait for the first menu
    while time.time() < boot_deadline:
        time.sleep(5)
        st = eng.status(PACK)
        pid = read_pid()
        phase_now = st.get("phase")
        if pid and pid != last_pid:
            print(f"[test] pid -> {pid} (phase={phase_now})", flush=True)
            last_pid = pid
        if last_phase != phase_now:
            print(f"[test] phase -> {phase_now} | {st.get('stage')}", flush=True)
            last_phase = phase_now
        if phase_now == "running" and pid:
            menu_at = time.time()
            phase("lite pack reaches menu", True, f"pid {pid}")
            break
        if phase_now == "error":
            phase("lite pack reaches menu", False, f"phase=error {st.get('error')}")
            raise SystemExit(1)
    else:
        phase("lite pack reaches menu", False, "menu not reached within 25 min")
        raise SystemExit(1)

    # ---- hold from the LAST menu, following auto-relaunches
    deadline = menu_at + HOLD_MIN * 60
    held = 0.0
    up = False
    while time.time() < deadline:
        time.sleep(5)
        st = eng.status(PACK)
        pid = read_pid()
        phase_now = st.get("phase")
        if pid and pid != last_pid:
            report["relaunches"].append({
                "t": round(time.time() - t0), "from": last_pid, "to": pid,
                "reason": st.get("closeContext") or st.get("stage"),
            })
            print(f"[test] RELAUNCH detected: pid {last_pid} -> {pid} "
                  f"(stage={st.get('stage')}) — hold clock resets", flush=True)
            last_pid = pid
            menu_at = time.time()
            deadline = menu_at + HOLD_MIN * 60
            held = 0.0
        if phase_now == "running":
            up = pid_alive(pid)
        else:
            up = False
        held = time.time() - menu_at
        report["timeline"].append({"t": round(time.time() - t0), "held": round(held),
                                   "phase": phase_now, "pid": pid, "up": up,
                                   "freeRamGB": free_ram_gb()})
        if not up and phase_now not in ("running", "relaunching"):
            break
    if not up:
        # Pull the close evidence the engine captured.
        try:
            st = json.loads((ROOT / "workspace" / "builds" / PACK / "logs" / "launch-state.json").read_text("utf-8"))
            ctx = st.get("closeContext")
        except Exception:  # noqa: BLE001
            ctx = None
        detail = f"up={up} freeRAM={free_ram_gb()}GB phase={phase_now}"
        if ctx:
            detail += f" closeContext={json.dumps(ctx)[:160]}"
        phase(f"lite pack at menu for {int(held)}s (target {int(HOLD_MIN*60)}s)", False, detail)
    else:
        phase(f"lite pack at menu for {int(held)}s (target {int(HOLD_MIN*60)}s)",
              held >= HOLD_MIN * 60 - 10, f"up={up} freeRAM={free_ram_gb()}GB")
finally:
    try:
        eng.stop(PACK)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
out = ROOT / "workspace" / "lite-relaunch-hold-result.json"
out.write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[test] OVERALL: {report['overall']} — saved workspace/lite-relaunch-hold-result.json", flush=True)
sys.exit(0 if overall else 1)
