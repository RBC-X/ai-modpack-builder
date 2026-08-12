"""Seed a real build into the workspace for CI screenshot regeneration.

Runs the real engine pipeline (interpret -> search -> select -> resolve ->
download -> instant validation) against live providers, so the screenshot
gallery always shows genuine data. Exits non-zero if the build fails.

    AMB_WORKSPACE=/tmp/amb-workspace python pyqt/seed_ci_build.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from engine.bridge import PyEngine  # noqa: E402

BUILD = {
    "prompt": (
        "Make me a lightweight Minecraft 1.20.1 Fabric fantasy exploration pack "
        "with structures, bosses, improved terrain, performance mods, "
        "around 8-12 mods, on 8 GB RAM"
    ),
    "mcVersion": "1.20.1",
    "loader": "fabric",
    "packSize": "light",
    "ramGB": 8,
    "testMode": "instant",
}


def main() -> int:
    e = PyEngine()
    bid = e.start_build(BUILD)
    print(f"build started: {bid}", flush=True)
    deadline = time.time() + 600
    status = "building"
    while time.time() < deadline:
        time.sleep(3)
        status = e.build(bid).get("status", "building")
        if status in ("done", "failed", "error"):
            break
    rec = e.build(bid)
    err = rec.get("error")
    if err:
        print(f"build error: {err}", flush=True)
    n = len(rec.get("selections") or [])
    print(f"final status: {status} | selections: {n}", flush=True)
    return 0 if status == "done" and n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
