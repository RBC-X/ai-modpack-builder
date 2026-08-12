"""Control experiment for the sustained-dual failure: hold the flagship ALONE
at the main menu for HOLD_MINUTES at its current (4 GB) heap. If it survives
solo, the dual-run deaths are concurrency/memory pressure; if it dies the same
silent way, the pack itself is unstable at 4 GB.

Usage: python pyqt/solo_hold_test.py
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

A = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PACK_A", "b-19fedb2cb00-1fad25cf")
HOLD_MIN = float(os.environ.get("HOLD_MINUTES", "5"))

eng = PyEngine()
report = {"phases": [], "timeline": []}


def phase(name, ok, detail):
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def free_ram_gb():
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


try:
    print(f"[test] record ramGB now = {eng.status(A).get('ramGB')}", flush=True)
    eng.play(A, "PlayerSolo")
    t0 = time.time()
    st = eng.status(A)
    while time.time() - t0 < 900 and st.get("phase") not in ("running", "error"):
        time.sleep(3)
        st = eng.status(A)
    if st.get("phase") != "running":
        phase("flagship reaches menu solo", False, f"phase={st.get('phase')} {st.get('error')}")
        raise SystemExit(1)
    pid = st.get("pid")
    phase("flagship reaches menu solo", True, f"pid {pid}")
    deadline = time.time() + HOLD_MIN * 60
    up = True
    last = 0
    while time.time() < deadline:
        time.sleep(5)
        st = eng.status(A)
        up = st.get("phase") == "running" and pid_alive(st.get("pid") or 0)
        t = round(time.time() - t0)
        report["timeline"].append({"t": t, "up": up, "freeRamGB": free_ram_gb()})
        if t - last >= 30:
            print(f"[hold] t={t}s up={up} freeRAM={free_ram_gb()}GB", flush=True)
            last = t
        if not up:
            break
    held = round(time.time() - t0)
    phase(f"flagship alone at menu for {held}s (target {int(HOLD_MIN*60)}s)", up and held >= HOLD_MIN * 60 - 10,
          f"up={up}")
finally:
    try:
        eng.stop(A)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
Path("workspace/solo-hold-result.json").write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[solo] OVERALL: {report['overall']} — saved workspace/solo-hold-result.json", flush=True)
sys.exit(0 if overall else 1)
