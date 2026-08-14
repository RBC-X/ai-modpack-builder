"""One-off flagship deep-test retry with a fitted lower heap (mirrors service.retest env
construction but with testMode=deep so world creation, quickplay world load,
GC memory monitoring and reproducibility actually run).

Usage:  python pyqt/deep_test_flagship.py <buildId> [out.json]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.core import BuildLogger, builds_dir  # noqa: E402
from engine.tester import run_test_level  # noqa: E402

BUILD_ID = sys.argv[1] if len(sys.argv) > 1 else "b-19fedb2cb00-1fad25cf"
OUT = "workspace/deep-evidence-flagship.json"
XMX = int(sys.argv[2]) if len(sys.argv) > 2 else 2560

bdir = builds_dir() / BUILD_ID
rec = json.loads((bdir / "build.json").read_text("utf-8"))
req = rec.get("requirements") or {}
settings = rec.get("settings") or {}
logger = BuildLogger(BUILD_ID, bdir)

mod_jars = []
for s in rec.get("selections") or []:
    if s.get("selected", True) and s.get("projectType") == "mod" and s.get("downloadPath") and Path(s["downloadPath"]).exists():
        mod_jars.append({"slug": s["slug"], "path": s["downloadPath"], "featureIds": s.get("featureIds") or []})

env = {
    "buildId": BUILD_ID, "buildDir": str(bdir),
    "gameDir": str(bdir / "instance" / "minecraft"),
    "mcVersion": req.get("minecraftVersion") or "1.20.1",
    "loader": req.get("loader") or "fabric",
    "testMode": "deep", "logger": logger,
    "xmxMB": XMX,
    "modJars": mod_jars, "resourcePackFiles": [], "shaderFiles": [],
    "downloadAssets": settings.get("downloadAssets", False),
    "maxAssetMB": settings.get("maxAssetMB", 400),
    "autoInstallJava": settings.get("autoInstallJava", True),
}
graph = rec.get("graph") or {"nodes": {}, "edges": []}

print(f"[retry] starting deep test on {BUILD_ID} "
      f"({req.get('minecraftVersion')} {req.get('loader')}, {len(mod_jars)} mods)…", flush=True)
t0 = time.time()
os.environ["AMB_BYPASS_RAM_GUARD"] = "1"
result = run_test_level(env, graph)
dt = time.time() - t0

print(f"\n[deep] RESULT: {result['status']} in {dt / 60:.1f} min", flush=True)
for p in result.get("phases") or []:
    mark = "PASS" if p.get("status") == "PASS" else ("SKIP" if p.get("status") == "SKIP" else p.get("status"))
    print(f"  {mark:5s}  {p.get('name'):18s}  {p.get('detail', '')[:160]}", flush=True)
print(f"  summary: {result.get('summary')}", flush=True)

os.makedirs(os.path.dirname(OUT) or ".", exist_ok=True)
Path(OUT).write_text(json.dumps({
    "buildId": BUILD_ID, "status": result["status"], "minutes": round(dt / 60, 1),
    "phases": result.get("phases"), "summary": result.get("summary"),
}, indent=2), "utf-8")
print(f"[retry] saved {OUT}", flush=True)
sys.exit(0 if result["status"] == "PASS" else 1)
