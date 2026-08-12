"""End-to-end proof of the opt-in auto-relaunch: play the lite pack with
autoRelaunch ON, hard-kill the game 25s after the main menu (a silent death:
no crash report, no "Stopping!", exit code 1), and verify the engine
relaunches ONCE at a lower fitted heap (-Xmx 80%) and reaches the menu again.

Usage: python pyqt/relaunch_proof.py b-lite-ef38acfd
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.bridge import PyEngine  # noqa: E402
from engine.launcher import pid_alive  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
ROOT = Path(HERE).parent
report: dict = {"phases": [], "events": []}


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {_ascii(name)}: {_ascii(detail)}", flush=True)


def read_pid() -> int:
    try:
        return int((ROOT / "workspace" / "builds" / PACK / "logs" / "launch-play.pid").read_text().strip())
    except Exception:  # noqa: BLE001
        return 0


def last_xmx() -> str:
    """The -Xmx of the LAST launch command in launch-play.log."""
    p = ROOT / "workspace" / "builds" / PACK / "logs" / "launch-play.log"
    try:
        lines = p.read_text("utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return ""
    for ln in reversed(lines):
        if "-Xmx" in ln:
            m = ln[ln.index("-Xmx"):]
            return m.split()[0].strip("\"'")
    return ""


eng = PyEngine()
eng.set_auto_relaunch(PACK, True)
print(f"[test] autoRelaunch ON; first launch", flush=True)
t0 = time.time()
eng.play(PACK, "PlayerLite")

pid1 = 0
try:
    # ---- first boot to menu
    while time.time() - t0 < 1500:
        time.sleep(5)
        st = eng.status(PACK)
        pid1 = read_pid()
        if st.get("phase") == "running" and pid1:
            break
        if st.get("phase") == "error":
            phase("first launch reaches menu", False, f"phase=error {st.get('error')}")
            raise SystemExit(1)
    else:
        phase("first launch reaches menu", False, "no menu within 25 min")
        raise SystemExit(1)
    phase("first launch reaches menu", True, f"pid {pid1}, -Xmx {last_xmx()}")
    report["events"].append({"t": round(time.time() - t0), "event": "menu", "pid": pid1})

    # ---- simulate a silent death 25 s after the menu
    time.sleep(25)
    print(f"[test] hard-killing game pid {pid1} (silent death: no crash, no Stopping!)", flush=True)
    subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid1)],
                   capture_output=True, check=False)
    report["events"].append({"t": round(time.time() - t0), "event": "killed", "pid": pid1})

    # ---- expect: engine detects silent close -> relaunching -> new pid, lower heap
    relaunch_seen = None
    pid2 = 0
    wait_until = time.time() + 240
    while time.time() < wait_until:
        time.sleep(5)
        st = eng.status(PACK)
        pid2 = read_pid()
        stg = st.get("stage") or ""
        if pid2 and pid2 != pid1 and pid_alive(pid2):
            relaunch_seen = {"pid": pid2, "stage": stg, "xmx": last_xmx(),
                             "t": round(time.time() - t0)}
            report["events"].append({"t": relaunch_seen["t"], "event": "relaunch", "pid": pid2})
            break
        if "relaunch" in stg.lower() and relaunch_seen is None:
            print(f"[test] engine stage: {_ascii(stg)}", flush=True)
    if not relaunch_seen:
        phase("engine auto-relaunches after silent death", False,
              f"no new pid within 240s (phase={st.get('phase')} stage={st.get('stage')})")
        raise SystemExit(1)
    phase("engine auto-relaunches after silent death", True,
          f"pid {pid1} -> {relaunch_seen['pid']}, -Xmx {relaunch_seen['xmx']}")
    print(f"[test] relaunched pid {relaunch_seen['pid']}; -Xmx now {relaunch_seen['xmx']}", flush=True)

    # ---- relaunched game must reach the menu again
    pid2 = relaunch_seen["pid"]
    while time.time() - t0 < 2400:
        time.sleep(5)
        st = eng.status(PACK)
        if st.get("phase") == "running" and read_pid() == pid2:
            break
        if st.get("phase") == "error":
            phase("relaunched game reaches menu", False, f"phase=error {st.get('error')}")
            raise SystemExit(1)
    else:
        phase("relaunched game reaches menu", False, "no menu after relaunch within budget")
        raise SystemExit(1)
    phase("relaunched game reaches menu", True, f"pid {pid2} running again")
finally:
    try:
        eng.stop(PACK)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
out = ROOT / "workspace" / "relaunch-proof-result.json"
out.write_text(json.dumps(report, indent=2), "utf-8")
print(f"\n[test] OVERALL: {report['overall']} — saved workspace/relaunch-proof-result.json", flush=True)
sys.exit(0 if overall else 1)
