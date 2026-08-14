"""NPE / unknown-crash attribution exercise on the real game.

Induces a NON-missing-dependency crash (heavy client init under a stressed
heap) and proves the hardened repair flow never invents a culprit from class-
load probe noise:

  1. Run the real standard test with a deliberately low heap (xmxMB) so the
     pack crashes at load instead of reaching the menu.
  2. On crash, read the real crash report / latest.log.
  3. attribute_crash(text, real jar dicts) -> culprit jar + confidence + reason.
     The hardened extractor only counts REAL exception stack frames: the
     "Error loading class: ... ClassNotFoundException" WARN one-liners and the
     "Failed to load:" probe blocks (present in every healthy pack) must not
     produce attributions.
  4. missing_dep_ids(text) -> the mutation decision: a pure NPE/OOM must NOT
     trigger garbage add-missing or removals (no evidence = no guessing), and
     a resource crash whose only frames are probes must yield EMPTY attribution.

Usage: pyqt/.venv/Scripts/python pyqt/npe_repair_exercise.py [buildId] [xmxMB] [out.json]
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

# Headless verification run (same rationale as the repair exercise): let the
# real game launch on a memory-constrained box so we can induce the crash.
os.environ["AMB_BYPASS_RAM_GUARD"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.core import BuildLogger, builds_dir  # noqa: E402
from engine.instance import collect_instance_logs  # noqa: E402
from engine.repair import attribute_crash, missing_dep_ids, parse_crash_report  # noqa: E402
from engine.tester import run_test_level  # noqa: E402

BUILD_ID = sys.argv[1] if len(sys.argv) > 1 else "b-19fedb2cb00-1fad25cf"
XMX = int(sys.argv[2]) if len(sys.argv) > 2 else 2560
OUT = sys.argv[3] if len(sys.argv) > 3 else "workspace/npe-evidence.json"

bdir = builds_dir() / BUILD_ID
rec = json.loads((bdir / "build.json").read_text("utf-8"))
req = rec.get("requirements") or {}
settings = rec.get("settings") or {}
logger = BuildLogger(BUILD_ID, bdir)

mod_jars = []
for s in rec.get("selections") or []:
    if s.get("selected", True) and s.get("projectType") == "mod" and s.get("downloadPath") and Path(s["downloadPath"]).exists():
        mod_jars.append({"slug": s["slug"], "path": s["downloadPath"], "featureIds": s.get("featureIds") or []})

print(f"[npe] {BUILD_ID} ({req.get('minecraftVersion')} {req.get('loader')}, "
      f"{len(mod_jars)} mods) — stressed heap xmx={XMX}MB, expecting a load-time crash", flush=True)

# Real test through the engine's own pipeline (isolated instance, real launch).
env = {
    "buildId": BUILD_ID, "buildDir": str(bdir),
    "gameDir": str(bdir / "instance" / "minecraft"),
    "mcVersion": req.get("minecraftVersion") or "1.20.1",
    "loader": req.get("loader") or "forge",
    "testMode": "standard", "logger": logger,
    "xmxMB": XMX,
    "modJars": mod_jars, "resourcePackFiles": [], "shaderFiles": [],
    "downloadAssets": settings.get("downloadAssets", False),
    "maxAssetMB": settings.get("maxAssetMB", 400),
    "autoInstallJava": settings.get("autoInstallJava", True),
}
graph = rec.get("graph") or {"nodes": {}, "edges": []}

t0 = time.time()
result = run_test_level(env, graph)
minutes = round((time.time() - t0) / 60, 1)

# Real evidence from the crash: the tester's log files land in bdir/logs/.
gd = bdir / "instance" / "minecraft"
logs = collect_instance_logs(str(gd))
crash_text = "\n".join(logs.get("crashReports") or [])
if not crash_text:
    crash_text = "\n".join(logs.get("latest") or []) + "\n" + "\n".join(logs.get("debug") or [])
summary = result.get("summary") or ""
status = result.get("status")
print(f"[npe] test status={status} in {minutes} min — {summary[:160]}", flush=True)

evidence = {
    "buildId": BUILD_ID, "xmxMB": XMX, "status": status, "minutes": minutes,
    "summary": summary, "phases": result.get("phases"),
}

if status == "PASS":
    print("[npe] pack reached the menu — no load-time crash under this heap; raising the stress (lower xmx) would be needed", flush=True)
    evidence["verdict"] = "no-crash"
    Path(OUT).write_text(json.dumps(evidence, indent=2), "utf-8")
    sys.exit(2)

# ---- Attribution first: name the culprit jar from the REAL stack trace. ----
attributions = attribute_crash(crash_text, mod_jars)
print("\n[npe] attribution (attribute_crash on the real crash text):", flush=True)
for a in attributions:
    print(f"  - {a['slug']}  [{a['confidence']}]  {a['reason']}", flush=True)
if not attributions:
    print("  (no mod frames / mixin config in this crash — attribution correctly stays empty, no guessing)", flush=True)

# ---- Mutation decision second: missing-dep scan must NOT garbage-add. ----
missing = missing_dep_ids(crash_text)
print(f"\n[npe] missing-dep scan of the crash text: {missing}", flush=True)
decision = ("add-missing" if missing else "no-mutation (attribution only)")
print(f"[npe] repair decision: {decision}", flush=True)

# Stack excerpt for the evidence file.
frames = []
for line in crash_text.splitlines():
    ls = line.strip()
    if ls.startswith("at ") or ls.startswith("Caused by:") or "Exception" in ls:
        frames.append(ls[:200])
    if len(frames) >= 14:
        break

evidence.update({
    "verdict": "crashed", "attributions": attributions,
    "missingDeps": missing, "decision": decision,
    "stackExcerpt": frames,
    "crashReports": logs.get("crashReports") or [],
})
Path(OUT).write_text(json.dumps(evidence, indent=2), "utf-8")
print(f"\n[npe] saved {OUT}", flush=True)

# Hardened contract: for a resource crash (OOM) whose only frames are
# class-load probes, attribution must stay EMPTY (no guessing) and the missing-
# dep scan must stay empty (no garbage add-missing). A bogus attribution from
# the "Failed to load:" probe blocks would be a FAIL — those frames are not
# real exception evidence.
ok = status in ("FAIL", "ERROR") and not missing and not attributions
print("\n" + ("[PASS] crash detected; attribution correctly EMPTY for this resource/"
              "probe crash (no guessing) and no garbage add-missing (attribution "
              "precedes mutation)." if ok
              else f"[FAIL] expected crash with empty attribution + no garbage mutation, "
                   f"got status={status}, attributions={len(attributions)}, missing={missing}"))
sys.exit(0 if ok else 1)
