"""Repair-loop exercise on the completed flagship pack, entirely in-process.

1. Remove a required library (geckolib) from the instance mods dir.
2. Play -> the game crashes at mod-load with a missing-dependency error.
3. api.fix() -> add_missing resolves geckolib through the real provider,
   downloads it, installs it.
4. Play again -> main menu reached.
5. Stop.

    pyqt/.venv/Scripts/python pyqt/repair_exercise_flagship.py <buildId>
"""
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.bridge import PyEngine

api = PyEngine()
bid = sys.argv[1] if len(sys.argv) > 1 else "b-19fecb26975-f4fd1656"
MODS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "workspace", "builds", bid, "instance", "minecraft", "mods")
failures = []


def check(name, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"  [{tag}] {name}" + (f" — {extra}" if extra else ""))


def wait_menu(timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(5)
        st = api.status(bid)
        if st.get("phase") == "running" and (st.get("progress") or 0) >= 100:
            return "menu", st
        if st.get("phase") == "error" or st.get("error"):
            return "crash", st
    return "timeout", {}


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DL_MODS = os.path.join(ROOT, "workspace", "builds", bid, "downloads", "mods")
backup_jar = None

# 0. sanity
rec = api.build(bid)
check("flagship pack exists and passed", (rec.get("testResult") or {}).get("status") == "PASS")
# geckolib's jar in the download store (launch re-installs from here, so the
# instance copy alone would be silently restored)
dl_jar = next((os.path.join(DL_MODS, f) for f in os.listdir(DL_MODS)
               if f.lower().startswith("geckolib") and f.endswith(".jar")), None)
check("geckolib jar present in download store", bool(dl_jar), dl_jar)

# 1. break the pack: remove geckolib from BOTH the download store and instance
print("\n[REPAIR] Removing geckolib from the download store + instance…")
backup_jar = dl_jar + ".bak"
shutil.move(dl_jar, backup_jar)
gecko_inst = next((os.path.join(MODS, f) for f in os.listdir(MODS)
                   if f.lower().startswith("geckolib") and f.endswith(".jar")), None)
if gecko_inst:
    shutil.move(gecko_inst, gecko_inst + ".bak")
check("geckolib removed everywhere", not os.path.isfile(dl_jar))

# 2. launch -> expect a crash
print("\n[REPAIR] Launching broken pack…")
api.play(bid)
outcome, st = wait_menu(600)
if outcome == "menu":
    print("  [WARN] game reached the menu despite missing geckolib — nothing to repair")
    api.stop(bid)
    if backup_jar:
        shutil.move(backup_jar, dl_jar)
    sys.exit(1)
check("crash detected with missing dependency", outcome == "crash",
      (st.get("error") or "")[:100])
print(f"  error: {(st.get('error') or '')[:150]}")
missing = st.get("missingDeps") or []
print(f"  missingDeps: {missing}")
check("missing deps include geckolib", any("geckolib" in str(m).lower() for m in missing), str(missing))

# 3. repair via the engine (add-missing) — restores a fresh download
print("\n[REPAIR] Running add-missing repair…")
try:
    res = api.fix(bid)
    print(f"  fix result: {res}")
    check("repair added geckolib", "geckolib" in str(res.get("added", [])).lower(), str(res.get("added")))
finally:
    if backup_jar and os.path.isfile(backup_jar):
        os.remove(backup_jar)
    for f in os.listdir(MODS):
        if f.endswith(".jar.bak"):
            os.remove(os.path.join(MODS, f))

# 4. relaunch -> main menu
print("\n[REPAIR] Relaunching repaired pack…")
api.play(bid)
outcome2, st2 = wait_menu(600)
check("repaired pack reaches the main menu", outcome2 == "menu", (st2.get("stage") or "")[:70])

# 5. stop
print("\n[REPAIR] Stopping…")
api.stop(bid)
time.sleep(2)
check("instance stopped", not api.status(bid).get("running"))
print()
print("[PASS] repair loop verified end-to-end on the flagship pack." if not failures else f"FAILURES: {failures}")
sys.stdout.flush()
os._exit(0 if not failures else 1)