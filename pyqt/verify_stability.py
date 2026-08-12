"""Launch the repaired flagship pack, confirm main menu, then wait WITHOUT
stopping to see whether the process genuinely crashes or stays alive."""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.bridge import PyEngine

BUILD_ID = "b-19fed8cb2cc-1b65ae48"
api = PyEngine()

print("[STABILITY] Play…")
t0 = time.time()
result = api.play(BUILD_ID)
print("  pid:", result.get("pid"))

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
        print(f"  ERROR at {int(time.time() - t0)}s: {err}")
        break

if menu:
    # stay alive: watch for 90s for a late crash WITHOUT stopping
    print("  watching 90s post-menu for late crash…")
    crashed = False
    while time.time() - t0 < 420:
        time.sleep(3)
        st = api.status(BUILD_ID)
        if st.get("phase") == "error":
            crashed = True
            print(f"  LATE CRASH after menu at {int(time.time() - t0)}s: {st.get('error') or st.get('stage')}")
            break
        if st.get("phase") in ("stopped",) and not st.get("running"):
            print(f"  process exited at {int(time.time() - t0)}s")
            crashed = True
            break
        if time.time() - t0 > 240:  # menu at ~60s + 90s watch
            break
    if not crashed:
        print(f"  STILL RUNNING at {int(time.time() - t0)}s — no late crash")
        api.stop(BUILD_ID)
        print("  stopped")

sys.exit(0 if menu else 1)
