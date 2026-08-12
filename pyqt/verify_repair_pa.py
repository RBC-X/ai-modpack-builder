"""Verify the tester grace-window + repair loop on the existing flagship pack:
test (expect FAIL on Project Atmosphere) -> analyze+repair (add Serene Seasons)
-> retest (expect PASS)."""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pathlib import Path

from engine.bridge import PyEngine
from engine.core import BuildLogger
from engine.tester import run_test_level
from engine.instance import collect_instance_logs

BUILD_ID = "b-19fed8cb2cc-1b65ae48"
api = PyEngine()
rec = api.build(BUILD_ID)
build_dir = (Path("workspace/builds") / BUILD_ID).resolve()
game_dir = build_dir / "instance" / "minecraft"
logger = BuildLogger(BUILD_ID, build_dir)

env = {
    "buildId": BUILD_ID, "buildDir": str(build_dir),
    "gameDir": str(game_dir), "mcVersion": rec["requirements"]["minecraftVersion"],
    "loader": rec["requirements"]["loader"], "testMode": "standard", "logger": logger,
    "xmxMB": 8192,
    "modJars": [{"slug": s["slug"], "path": s["downloadPath"], "featureIds": s.get("featureIds") or []}
                for s in (rec.get("selections") or [])
                if s.get("projectType") == "mod" and s.get("selected", True)
                and s.get("downloadPath") and Path(s["downloadPath"]).exists()],
    "resourcePackFiles": [], "shaderFiles": [],
    "downloadAssets": False, "maxAssetMB": 400, "autoInstallJava": True,
}
graph = rec.get("graph") or {"nodes": {}}

# Mirror the build pipeline: wipe stale diagnostics so the previous run's
# menu markers / crash reports can't poison this test.
shutil.rmtree(game_dir / "logs", ignore_errors=True)
shutil.rmtree(game_dir / "crash-reports", ignore_errors=True)

print("[1] repair loop: test -> analyze -> repair -> retest (like the pipeline)…")
mods_dir = build_dir / "instance" / "minecraft" / "mods"
max_rounds = 10
rounds = 0
last = None
while rounds < max_rounds:
    rounds += 1
    shutil.rmtree(game_dir / "logs", ignore_errors=True)
    shutil.rmtree(game_dir / "crash-reports", ignore_errors=True)
    t0 = time.time()
    res = run_test_level(env, graph)
    print(f"  round {rounds}: {res.get('status')} after {int(time.time() - t0)}s — {res.get('summary')}")
    if res.get("status") == "PASS":
        last = res
        break
    action = api._s._analyze_failure(BUILD_ID, rec, env, logger)
    if not action:
        print("    no repair action determined — stopping")
        break
    print(f"    repair: {action.get('action')} — {(action.get('reason') or '')[:130]}")
    api._s._apply_repair(action, rec, {"fileByKey": {}}, env["modJars"], env,
                         mods_dir, logger)
    rec["repairs"] = rec.get("repairs") or []
    rec["repairs"].append(action)
    api._s._write_record(rec)

ok = last is not None and last.get("status") == "PASS"
print(f"\n[{'PASS' if ok else 'FAIL'}] REPAIR LOOP VERIFY {'PASS' if ok else 'FAIL'} ({rounds} rounds)")
if rec.get("repairs"):
    for r_ in rec["repairs"]:
        print("  -", r_.get("action"), "|", (r_.get("reason") or "")[:110])
sys.exit(0 if ok else 1)
