"""Attach to the already-running lite pack game (launched by the engine),
detect the main menu from the REAL latest.log (tightened menu evidence),
then hold-watch the process + free RAM for HOLD_MINUTES and write the real
result. Does NOT launch a new game — the round-1 launch is still booting.

Usage: python pyqt/lite_hold_watch.py b-lite-ef38acfd [hold_minutes]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.launcher import pid_alive  # noqa: E402
from engine.repair import main_menu_reached  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
HOLD_MIN = float(os.environ.get("HOLD_MINUTES", sys.argv[2] if len(sys.argv) > 2 else "5"))
ROOT = Path(HERE).parent
report: dict = {"phases": [], "timeline": [], "pack": PACK}


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


def pid_of() -> int:
    try:
        return int((ROOT / "workspace" / "builds" / PACK / "logs" / "launch-play.pid").read_text().strip())
    except Exception:  # noqa: BLE001
        return 0


def log_lines() -> list:
    p = ROOT / "workspace" / "builds" / PACK / "instance" / "minecraft" / "logs" / "latest.log"
    try:
        return p.read_text("utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return []


pid = pid_of()
print(f"[watch] pack={PACK} pid={pid} — waiting for main menu (real latest.log evidence)...", flush=True)
t0 = time.time()
menu_at = None
while time.time() - t0 < 1200:
    if not pid_alive(pid):
        print(f"[watch] game died while booting (pid {pid} gone)", flush=True)
        phase("lite pack reaches menu", False, f"game pid {pid} died during boot")
        break
    if main_menu_reached(log_lines()):
        menu_at = time.time()
        phase("lite pack reaches menu", True, f"pid {pid} — main menu evidence in latest.log")
        break
    time.sleep(5)
else:
    phase("lite pack reaches menu", False, "menu not reached within 20 min")
    print("[watch] giving up on boot", flush=True)

if menu_at:
    deadline = menu_at + HOLD_MIN * 60
    held = 0.0
    up = True
    while time.time() < deadline:
        time.sleep(5)
        held = time.time() - menu_at
        up = pid_alive(pid)
        report["timeline"].append({"t": round(held), "up": up, "freeRamGB": free_ram_gb()})
        if not up:
            break
    phase(f"lite pack at menu for {int(held)}s (target {int(HOLD_MIN*60)}s)",
          up and held >= HOLD_MIN * 60 - 10, f"up={up} freeRAM={free_ram_gb()}GB")

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
out = ROOT / "workspace" / "lite-hold-result.json"
out.write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[watch] OVERALL: {report['overall']} — saved workspace/lite-hold-result.json", flush=True)
sys.exit(0 if overall else 1)
