"""Deep test on Minecraft 1.20.4 (quickplay world load + GC memory monitoring
are supported on 1.20.2+). Creates a blank Fabric 1.20.4 pack via the real
engine, then runs the full deep test: server start, world creation, client
quickplay world load, GC heap monitoring, reproducibility.

Usage: python pyqt/deep_test_1204.py
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
from engine.core import BuildLogger, builds_dir  # noqa: E402
from engine.tester import run_test_level  # noqa: E402

eng = PyEngine()
# Reuse an existing 1.20.4 blank pack if one exists, else create it.
BID = None
for d in builds_dir().iterdir():
    if not d.name.startswith("b-"):
        continue
    try:
        rec = json.loads((d / "build.json").read_text("utf-8"))
    except Exception:  # noqa: BLE001
        continue
    req = rec.get("requirements") or {}
    if req.get("minecraftVersion") == "1.20.4" and not (rec.get("selections")):
        BID = d.name
        break
if not BID:
    r = eng.create_pack(name="DeepTest 1.20.4", mc="1.20.4", loader="fabric", ram_gb=4)
    BID = r["buildId"]
print(f"[deep1204] pack {BID}", flush=True)

bdir = builds_dir() / BID
rec = json.loads((bdir / "build.json").read_text("utf-8"))
req = rec.get("requirements") or {}
settings = rec.get("settings") or {}
logger = BuildLogger(BID, bdir)
env = {
    "buildId": BID, "buildDir": str(bdir), "gameDir": str(bdir / "instance" / "minecraft"),
    "mcVersion": req.get("minecraftVersion") or "1.20.4", "loader": req.get("loader") or "fabric",
    "testMode": "deep", "logger": logger, "xmxMB": 4096,
    "modJars": [], "resourcePackFiles": [], "shaderFiles": [],
    "downloadAssets": settings.get("downloadAssets", False),
    "maxAssetMB": settings.get("maxAssetMB", 400),
    "autoInstallJava": settings.get("autoInstallJava", True),
}
graph = {"nodes": {}, "edges": []}
t0 = time.time()
print(f"[deep1204] running deep test on 1.20.4 ({env['loader']})…", flush=True)
result = run_test_level(env, graph)
dt = time.time() - t0
print(f"\n[deep1204] RESULT: {result['status']} in {dt / 60:.1f} min", flush=True)
for p in result.get("phases") or []:
    print(f"  {p.get('status'):5s}  {p.get('name'):18s}  {(p.get('detail') or '')[:150]}", flush=True)
print(f"  summary: {result.get('summary')}", flush=True)
Path("workspace/deep-test-1204.json").write_text(json.dumps({
    "buildId": BID, "status": result["status"], "minutes": round(dt / 60, 1),
    "phases": result.get("phases"), "summary": result.get("summary"),
}, indent=2), "utf-8")
print("[deep1204] saved workspace/deep-test-1204.json", flush=True)
sys.exit(0 if result["status"] == "PASS" else 1)
