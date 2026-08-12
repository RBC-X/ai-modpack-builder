"""Verify the launch_pack fix on the already-built flagship pack: the repaired
mod set (selected-only, repaired versions) must be installed and the game must
reach the main menu via Play, then Stop must work."""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.bridge import PyEngine
from pathlib import Path

BUILD_ID = "b-19fed8cb2cc-1b65ae48"
api = PyEngine()
rec = api.build(BUILD_ID)
print("test status:", (rec.get("testResult") or {}).get("status"))
print("mods selected:", len([s for s in (rec.get("selections") or []) if s.get("projectType") == "mod" and s.get("selected", True)]))

# confirm the record's curios selection points at 5.14.1
for s in (rec.get("selections") or []):
    if s.get("slug") == "curios" and s.get("selected", True):
        print("curios selection ->", s.get("versionNumber"), s.get("downloadPath"))

# Launch
print("\n[VERIFY] Play…")
t0 = time.time()
try:
    result = api.play(BUILD_ID)
    print("  pid:", result.get("pid"))
except Exception as e:
    print("  PLAY FAILED:", str(e)[:200])
    sys.exit(1)

menu = False
err = None
while time.time() - t0 < 420:
    time.sleep(3)
    st = api.status(BUILD_ID)
    if st.get("phase") == "running" and st.get("progress", 0) >= 100:
        menu = True
        print(f"  MAIN MENU after {int(time.time() - t0)}s")
        break
    if st.get("phase") == "error":
        err = st.get("error") or st.get("stage")
        print(f"  ERROR: {err}")
        break

print("\n[VERIFY] Stop…")
api.stop(BUILD_ID)
time.sleep(2)
st = api.status(BUILD_ID)
print("  after stop ->", st.get("phase"), "| running:", st.get("running"))

# Check the instance mods for the repaired set
mods_dir = Path("workspace/builds") / BUILD_ID / "instance/minecraft/mods"
names = sorted(f.name for f in mods_dir.glob("*.jar"))
has_curios = [n for n in names if "curios" in n.lower()]
print("  curios jars in instance:", has_curios)
print("  daily-boss jars in instance:", [n for n in names if "daily" in n.lower()])
print("  origins jars in instance:", [n for n in names if "origin" in n.lower()])

ok = menu and st.get("phase") == "stopped" and not any("daily" in n.lower() for n in names)
print("\n[%s] PLAY VERIFY %s" % ("PASS" if ok else "FAIL", "PASS" if ok else "FAIL"))
sys.exit(0 if ok else 1)
