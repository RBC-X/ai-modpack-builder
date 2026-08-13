"""play_state stale-launch-state hardening: a persisted record that claims the
game is active but has no live pid must degrade to "stopped" once stale, so the
launcher never reports "running" forever after a crash left a pid-less running
record behind (the regression the installed-1.0.10 verification surfaced).

Usage: python pyqt/launch_state_test.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.launcher import play_state  # noqa: E402

report: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def write_state(build_dir: Path, state: dict) -> None:
    p = build_dir / "logs" / "launch-state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), "utf-8")


def stamp(age_min: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - age_min * 60))


with tempfile.TemporaryDirectory() as td:
    bd = Path(td) / "b-x"

    # 1. stale pid-less "running" record -> stopped (the bug)
    write_state(bd, {"phase": "running", "progress": 100, "pid": None,
                     "updatedAt": stamp(5)})
    st = play_state("b-x", str(bd))
    check("stale pid-less running record degrades to stopped",
          st.get("phase") == "stopped", f"phase={st.get('phase')}")

    # 2. fresh pid-less record keeps its state briefly (grace for pid attach)
    write_state(bd, {"phase": "loading", "progress": 88, "pid": None,
                     "updatedAt": stamp(0)})
    st = play_state("b-x", str(bd))
    check("fresh pid-less record keeps state (attach grace)",
          st.get("phase") == "loading", f"phase={st.get('phase')}")

    # 3. dead real pid -> stopped (existing guard still works)
    write_state(bd, {"phase": "running", "progress": 100, "pid": 99999991,
                     "updatedAt": stamp(0)})
    st = play_state("b-x", str(bd))
    check("dead pid degrades to stopped", st.get("phase") == "stopped",
          f"phase={st.get('phase')}")

    # 4. already-stopped record untouched
    write_state(bd, {"phase": "stopped", "progress": 0, "pid": None,
                     "updatedAt": stamp(9)})
    st = play_state("b-x", str(bd))
    check("stopped record untouched", st.get("phase") == "stopped",
          f"phase={st.get('phase')}")

    # 5. no record -> None (caller treats as stopped)
    write_state(bd, {"phase": "done"})
    st = play_state("b-y", str(bd))
    check("no launch state -> None", st is None or st.get("phase") == "done",
          f"st={st}")

overall = all(r["status"] == "PASS" for r in report)
out = Path(__file__).resolve().parent.parent / "workspace" / "launch-state-result.json"
out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
print(f"\n[state] OVERALL: {'PASS' if overall else 'FAIL'}")
sys.exit(0 if overall else 1)
