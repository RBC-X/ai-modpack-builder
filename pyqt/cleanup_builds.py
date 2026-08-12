"""Free disk: remove failed/building build dirs and orphaned dirs (not in the
library index). Keeps every 'done' build plus the specific packs the live
tests use, regardless of index status."""
from __future__ import annotations

import json
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.core import builds_dir  # noqa: E402

KEEP_ALWAYS = {
    "b-19fedb2cb00-1fad25cf",  # flagship PASS (dual test pack A)
    "b-19fedb237cf-4a466b03",  # lightweight PASS (dual test pack B)
    "b-19fee21d983-21576e41",  # 1.20.4 deep test pack
    "b-19fee2237dc-47956b4b",  # recent lightweight PASS
}

bd = builds_dir()
idx = json.loads((bd / "index.json").read_text("utf-8"))
by_id = {r["buildId"]: r for r in idx}

kept = set(KEEP_ALWAYS)
# Keep every build whose index status is 'done' (the user's library).
kept |= {bid for bid, r in by_id.items() if r.get("status") == "done"}

deleted = []
freed = 0
for d in sorted(bd.iterdir()):
    if not d.is_dir():
        continue
    if d.name in kept:
        continue
    sz = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    try:
        shutil.rmtree(d)
        deleted.append((d.name, sz))
        freed += sz
    except Exception as e:  # noqa: BLE001
        print("SKIP %s: %s" % (d.name, e))

print("kept %d build dirs" % len(kept))
print("deleted %d dirs, freed %.2f GB" % (len(deleted), freed / 1e9))
for name, sz in sorted(deleted, key=lambda x: -x[1])[:15]:
    print("  - %s (%.2f GB)" % (name, sz / 1e9))
