"""Dual-launch verification: run a SECOND pack while the first is already
running, with proper instance isolation and per-pack process state.

Uses the real in-process engine (PyEngine) and the real play()/stop()/status()
paths — the same ones the PyQt launcher calls. No Node server.

Order is deliberate on this 7 GB machine: the lightweight pack settles at the
main menu first, then the 150-mod flagship boots as the SECOND pack while the
first is still running (the real question being verified).

Usage: python pyqt/dual_launch_test.py
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.bridge import PyEngine  # noqa: E402
from engine.core import builds_dir  # noqa: E402

A = os.environ.get("PACK_A", "b-19fedb2cb00-1fad25cf")   # flagship Forge 1.20.1 (second)
B = os.environ.get("PACK_B", "b-19fedb237cf-4a466b03")   # lightweight Fabric 1.20.1 (first)

report: dict = {"phases": []}


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {_ascii(name)}: {_ascii(detail)}", flush=True)


def wait_phase(bid: str, phases, timeout: float = 600) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = eng.status(bid)
        if st.get("phase") in phases or st.get("phase") == "error":
            return st
        time.sleep(2)
    return eng.status(bid)


eng = PyEngine()
stream_stop = threading.Event()
stream_events: list = []

# The machine reports 7 GB; the lightweight pack is plenty at 4 GB. set_ram is
# the same supported API the Pack Detail RAM editor uses.
eng.set_ram(B, 4)
print("[test] %s RAM lowered to 4 GB via set_ram (supported API)" % B, flush=True)

try:
    # 1. Launch the lightweight pack first; wait for its main menu.
    eng.play(B, "PlayerB")
    stB = wait_phase(B, ("running",))
    phase("pack B (first) reaches main menu", stB.get("phase") == "running" and stB.get("pid"),
          "pid %s phase %s" % (stB.get("pid"), stB.get("phase")))
    pidB = stB.get("pid")

    # 2. Launch the flagship as the SECOND pack while B is already running;
    #    stream its logs live during the whole boot.
    def drain():
        try:
            for ev in eng.game_log_stream(A):
                stream_events.append(ev)
                if stream_stop.is_set() or len(stream_events) >= 400:
                    break
        except Exception as e:  # noqa: BLE001
            stream_events.append({"type": "error", "line": str(e)})

    t = threading.Thread(target=drain, daemon=True)
    t.start()
    eng.play(A, "PlayerA")
    stA = wait_phase(A, ("running",))
    stream_stop.set()
    phase("pack A (second) reaches main menu while B runs",
          stA.get("phase") == "running" and stA.get("pid"),
          "pid %s phase %s" % (stA.get("pid"), stA.get("phase")))
    pidA = stA.get("pid")

    # 3. Distinct per-pack process state (files carry buildId + pid).
    sa = json.loads((builds_dir() / A / "logs" / "launch-state.json").read_text("utf-8"))
    sb = json.loads((builds_dir() / B / "logs" / "launch-state.json").read_text("utf-8"))
    phase("distinct pids", bool(pidA and pidB and pidA != pidB), "A=%s B=%s" % (pidA, pidB))
    phase("per-pack state files", sa.get("buildId") == A and sb.get("buildId") == B
          and sa.get("pid") == pidA and sb.get("pid") == pidB,
          "A.state build=%s pid=%s | B.state build=%s pid=%s" % (sa.get("buildId"), sa.get("pid"),
                                                                 sb.get("buildId"), sb.get("pid")))
    la = Path(builds_dir() / A / "logs" / "launch-play.log")
    lb = Path(builds_dir() / B / "logs" / "launch-play.log")
    phase("distinct log files", la.exists() and lb.exists() and la != lb, "%s + %s" % (la.name, lb.name))
    gdA = Path(builds_dir() / A / "instance" / "minecraft")
    gdB = Path(builds_dir() / B / "instance" / "minecraft")
    phase("instance isolation", gdA != gdB and gdA.is_dir() and gdB.is_dir(),
          "%s != %s" % (gdA.name, gdB.name))

    # 4. Live log streaming: A's boot produced lines delivered in real time.
    kinds = {}
    for e in stream_events:
        kinds[e.get("type", "line")] = kinds.get(e.get("type", "line"), 0) + 1
    sample = [_ascii(e.get("line", ""))[:80] for e in stream_events[:3]]
    live = kinds.get("line", 0) >= 5
    phase("live log streaming (latest.log -> UI)", live,
          "%d events %s - sample: %s" % (len(stream_events), kinds, sample))

    # 5. Both running simultaneously with per-pack state.
    stA2 = eng.status(A)
    stB2 = eng.status(B)
    phase("both running concurrently", bool(stA2.get("running") and stB2.get("running")),
          "A=%s pid=%s | B=%s pid=%s" % (stA2.get("phase"), stA2.get("pid"), stB2.get("phase"), stB2.get("pid")))

    # 6. Stopping A (the second pack) leaves B running; stopping B stops all.
    eng.stop(A)
    time.sleep(2)
    stA3 = eng.status(A)
    stB3 = eng.status(B)
    phase("stop A leaves B running", bool(stB3.get("running") and not stA3.get("running")),
          "A=%s B=%s" % (stA3.get("phase"), stB3.get("phase")))
    eng.stop(B)
    time.sleep(2)
    stB4 = eng.status(B)
    phase("stop B stops everything", not stB4.get("running"), "B=%s" % stB4.get("phase"))
finally:
    stream_stop.set()
    try:
        eng.stop(B)
    except Exception:  # noqa: BLE001
        pass
    try:
        eng.stop(A)
    except Exception:  # noqa: BLE001
        pass

overall = all(p["status"] == "PASS" for p in report["phases"])
report["overall"] = "PASS" if overall else "FAIL"
Path("workspace/dual-launch-result.json").write_text(json.dumps(report, indent=2), "utf-8")
print("\n[dual] OVERALL: %s - saved workspace/dual-launch-result.json" % report["overall"], flush=True)
sys.exit(0 if overall else 1)
