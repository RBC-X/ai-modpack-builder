"""Council round 3 — Deep-mode shader launch.

Builds a small Fabric 1.20.4 pack with shaders AND a 32x resource pack in DEEP
test mode, so the real pipeline runs: standard launch + main menu, vanilla
server start, world creation, client quickplay world load, GC heap monitoring,
and reproducibility — with the shader + resource pack installed.

Run:  pyqt/.venv/Scripts/python -u pyqt/deep_shader_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.bridge import PyEngine  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""), flush=True)


api = PyEngine()
check("engine healthy", api.health())

req = {
    "prompt": "Create a small medieval fantasy exploration pack for Minecraft 1.20.4 Fabric "
              "with a few performance mods, shaders, and 32x textures, and test it deeply.",
    "mcVersion": "1.20.4", "loader": "fabric", "packSize": "light",
    "ramGB": 4, "testMode": "deep", "shaders": True,
}
bid = api.start_build(req)
check("build started", bool(bid), bid)

deadline = time.monotonic() + 1500  # deep mode: real server + world + 2 client launches
rec = None
while time.monotonic() < deadline:
    time.sleep(5)
    rec = api.build(bid)
    st = (rec or {}).get("status")
    if st in ("done", "failed"):
        break
check("deep build finished", (rec or {}).get("status") == "done",
      f"status={rec.get('status')} error={rec.get('error')}")

if rec:
    sc = rec.get("shaderChoice") or {}
    rpc = rec.get("resourcePackChoice") or {}
    check("shader selected", bool(sc.get("title")),
          f"{sc.get('title')} ({sc.get('preset')} preset)" if sc else "none")
    check("resource pack selected", bool(rpc.get("title")),
          rpc.get("title") if rpc else "none")
    tests = rec.get("tests") or []
    if tests:
        t = tests[0]
        for ph in t.get("phases") or []:
            print(f"  [phase] {ph.get('name')}: {ph.get('status')} — {str(ph.get('detail'))[:90]}", flush=True)
        overall = t.get("status")
        check("deep test overall PASS", overall == "PASS", f"level={t.get('level')}")
        phases = {p.get("name"): p.get("status") for p in t.get("phases") or []}
        check("main-menu phase passed", phases.get("main-menu") == "PASS", str(phases))
        check("server-start phase passed", phases.get("server-start") == "PASS", str(phases))
        check("world-creation phase passed", phases.get("world-creation") == "PASS", str(phases))
        wl = phases.get("world-load", "SKIP")
        if wl == "SKIP":
            print("[SKIP] quickplay world-load — requires MC 1.20.2+ (this pack is 1.20.4, so it should have run)", flush=True)
        check("world-load not FAILED", wl != "FAIL", str(phases))
        check("memory-monitor not FAILED", phases.get("memory-monitor", "SKIP") != "FAIL", str(phases))
        check("reproducibility passed", phases.get("reproducibility") == "PASS", str(phases))
        mem = next((p.get("detail", "") for p in t.get("phases") or [] if p.get("name") == "memory-monitor"), "")
        print(f"  memory monitor: {mem}", flush=True)

    # shader + RP zips installed in the instance
    inst = Path(f"workspace/builds/{bid}/instance/minecraft")
    sh_zips = [f.name for f in (inst / "shaderpacks").iterdir()] if (inst / "shaderpacks").is_dir() else []
    rp_zips = [f.name for f in (inst / "resourcepacks").iterdir()] if (inst / "resourcepacks").is_dir() else []
    check("shader zip in shaderpacks/", any(f.lower().endswith(".zip") for f in sh_zips), str(sh_zips))
    check("resource pack zip in resourcepacks/", any(f.lower().endswith(".zip") for f in rp_zips), str(rp_zips))
    print("  finalReport:", str(rec.get("finalReport") or "")[:400], flush=True)

print("DEEP SHADER " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
