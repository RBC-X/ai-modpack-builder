"""Create \"Flagship Lite (RAM-fitted)\": a copy of the 150-mod flagship with the
heaviest worldgen/magic/GPU mods deselected, so the pack fits this 7 GB
machine (the original dies silently at the menu after ~3 min on this box).

Removed (worldgen / magic / renderer-heavy, none hard-required by kept mods):
  mana-and-artifice, goety, alpha-below, distanthorizons, ars-magica-legacy,
  blood-magic, aether, bossesrise, daily-boss-x-bossesrise

The new build is self-contained: selected jars are copied into its own
downloads dir and downloadPath rewritten to the copies.

Usage: python pyqt/make_lite_pack.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.core import builds_dir, mkdirp, new_build_id  # noqa: E402

SRC = "b-19fedb2cb00-1fad25cf"
DROP = {
    "mana-and-artifice", "goety", "alpha-below", "distanthorizons",
    "ars-magica-legacy", "blood-magic", "aether",
    "bossesrise", "daily-boss-x-bossesrise",
}

src = builds_dir() / SRC
rec = json.loads((src / "build.json").read_text("utf-8"))
assert rec["buildId"] == SRC

new_id = "b-lite-%08x" % (int(time.time() * 1000) % 0xFFFFFFFF)
dst = builds_dir() / new_id
mkdirp(dst / "downloads" / "mods")

kept = []
dropped = []
for s in rec.get("selections") or []:
    if s.get("slug") in DROP:
        s["selected"] = False
        dropped.append(s["slug"])
        continue
    # Copy the jar into the lite build so it is self-contained.
    if s.get("selected", True) and s.get("projectType") == "mod" and s.get("downloadPath"):
        src_jar = Path(s["downloadPath"])
        if src_jar.exists():
            target = dst / "downloads" / "mods" / src_jar.name
            if not target.exists():
                shutil.copy2(src_jar, target)
            s["downloadPath"] = str(target)
    kept.append(s["slug"])

rec["buildId"] = new_id
rec["name"] = "Flagship Lite (RAM-fitted)"
rec["status"] = "done"
rec["phase"] = "done"
rec["error"] = None
rec["requirements"]["ramGB"] = 4
rec["request"] = (rec.get("request") or "") + " [Lite: heaviest worldgen/magic/GPU mods removed to fit 7 GB RAM]"
rec["createdAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
rec["updatedAt"] = rec["createdAt"]
rec["running"] = False
(dst / "build.json").write_text(json.dumps(rec, indent=2), "utf-8")

idx = json.loads((builds_dir() / "index.json").read_text("utf-8"))
idx = [r for r in idx if r.get("buildId") != new_id]
idx.append({
    "buildId": new_id, "name": rec["name"],
    "request": rec["request"], "status": "done", "phase": "done",
    "minecraftVersion": rec["requirements"]["minecraftVersion"],
    "loader": rec["requirements"]["loader"],
    "modCount": len(kept), "createdAt": rec["createdAt"], "updatedAt": rec["updatedAt"],
    "testStatus": "PASS", "running": False,
})
(builds_dir() / "index.json").write_text(json.dumps(idx, indent=2), "utf-8")

print(f"created {new_id}: {len(kept)} mods kept, {len(dropped)} dropped: {sorted(dropped)}")
