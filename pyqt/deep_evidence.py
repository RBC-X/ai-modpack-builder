"""Sequential deep-test evidence run for the repair-pass audit.

Runs deep mode (server start + world creation + client quickplay world load
+ GC heap monitoring + reproducibility) on the flagship Forge 1.20.1 pack
(quickplay/GC expected SKIP on <1.20.2) and then on the medieval Fabric
1.20.4 pack (full quickplay + GC), launching the real game on this machine,
and writes one combined evidence summary.

Usage: pyqt/.venv/Scripts/python -u pyqt/deep_evidence.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

# Headless verification run on a RAM-constrained box: same rationale as the
# repair exercises — let the real game launch so the deep phases actually run.
# The guard stays intact for real users; the sub-3 GB warning still logs.
os.environ["AMB_BYPASS_RAM_GUARD"] = "1"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
PY = os.path.join(HERE, ".venv", "Scripts", "python.exe")
DRIVER = os.path.join(HERE, "deep_test_flagship.py")

TARGETS = [
    ("b-19fedb2cb00-1fad25cf", "flagship", "deep-evidence-flagship.json"),
    ("b-19ff3c3b13d-eb53bc68", "medieval", "deep-evidence-medieval.json"),
]

results = []
for bid, label, out_name in TARGETS:
    out_path = os.path.join(ROOT, "workspace", out_name)
    print(f"[deep-evidence] === {label} ({bid}) starting {time.strftime('%H:%M:%S')} ===", flush=True)
    t0 = time.time()
    r = subprocess.run([PY, "-u", DRIVER, bid, out_path], capture_output=True, text=True)
    dt = time.time() - t0
    tail = "\n".join((r.stdout or "").strip().splitlines()[-30:])
    print(f"[deep-evidence] {label} rc={r.returncode} in {dt / 60:.1f} min", flush=True)
    print(tail, flush=True)
    if r.stderr:
        print("[deep-evidence] STDERR:", r.stderr[-1200:], flush=True)
    try:
        rec = json.load(open(out_path, encoding="utf-8"))
        results.append(rec)
    except Exception:  # noqa: BLE001
        results.append({"buildId": bid, "status": "ERROR", "detail": "no output json"})
    print(f"[deep-evidence] {label} DONE rc={r.returncode}", flush=True)

summary_path = os.path.join(ROOT, "workspace", "deep-evidence-summary.json")
with open(summary_path, "w", encoding="utf-8") as f:
    json.dump({"ranAt": time.strftime("%Y-%m-%d %H:%M:%S"), "results": results}, f, indent=2)
print(f"[deep-evidence] SUMMARY written to {summary_path}", flush=True)
print("[deep-evidence] ALL DONE", flush=True)
sys.exit(0 if all(r.get("status") == "PASS" for r in results) else 1)
