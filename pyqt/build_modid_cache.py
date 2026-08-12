"""One-time cache of modId -> slug for the lite pack's selected jars.

The Forge missing-deps screen reports MOD IDs (e.g. 'dmnr') while the pack
record is keyed by project slug — this map bridges them. Building it reads
every selected jar, so it is cached to workspace/lite-modid-map.json.

Usage: python pyqt/build_modid_cache.py [build_id]
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.core import builds_dir  # noqa: E402
from engine.jarmeta import provided_mod_ids, read_jar_metadata  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
rec = json.loads((builds_dir() / PACK / "build.json").read_text("utf-8"))
out = {}
start = time.time()
n = 0
for s in rec.get("selections") or []:
    if not s.get("selected", True) or s.get("projectType") != "mod":
        continue
    p = s.get("downloadPath")
    if not p or not os.path.exists(p):
        print(f"skip (no file): {s['slug']}", flush=True)
        continue
    meta = read_jar_metadata(p)
    if meta and meta.get("id"):
        out.setdefault(meta["id"], s["slug"])
    for pid in provided_mod_ids(p):
        out.setdefault(pid, s["slug"])
    n += 1
    if n % 25 == 0:
        print(f"  {n} jars... ({time.time() - start:.0f}s)", flush=True)
cache = {"buildId": PACK, "map": out, "slugs": [s["slug"] for s in rec["selections"]
         if s.get("selected", True) and s.get("projectType") == "mod"],
         "builtAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
Path("workspace/lite-modid-map.json").write_text(json.dumps(cache), "utf-8")
print(f"cached {len(out)} modIds from {n} jars in {time.time() - start:.0f}s -> workspace/lite-modid-map.json", flush=True)
