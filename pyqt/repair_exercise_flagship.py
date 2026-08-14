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

# Headless verification run: let the pack launch on a memory-constrained
# box (the RAM guard's 1.0 GB threshold is for real users; the deep-tester
# and repair exercises run under the same conditions as the passing deep
# tests). The sub-3 GB warning still logs.
os.environ["AMB_BYPASS_RAM_GUARD"] = "1"

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

# 0. sanity
rec = api.build(bid)
check("flagship pack exists and passed", (rec.get("testResult") or {}).get("status") == "PASS")
# The launch re-installs mods from the download store, so the mod must be
# removed from BOTH the store and the instance — and every version of it
# (the store may hold 4.8.3 and 4.8.4; leaving one behind silently restores it).
dl_jars = [os.path.join(DL_MODS, f) for f in os.listdir(DL_MODS)
           if f.lower().startswith("geckolib") and f.endswith(".jar")]
inst_jars = [os.path.join(MODS, f) for f in os.listdir(MODS)
             if f.lower().startswith("geckolib") and f.endswith(".jar")]
check("geckolib jars present in download store", bool(dl_jars), str(dl_jars))

# 1. break the pack: remove every geckolib jar from both locations
print("\n[REPAIR] Removing geckolib from the download store + instance…")
backup_pairs = []
for p in dl_jars + inst_jars:
    bak = p + ".bak"
    shutil.move(p, bak)
    backup_pairs.append((p, bak))
check("geckolib removed everywhere",
      not any(os.path.isfile(p) for p in dl_jars + inst_jars))

# 2. launch -> expect a crash
print("\n[REPAIR] Launching broken pack…")
api.play(bid)
outcome, st = wait_menu(600)
if outcome == "menu":
    print("  [WARN] game reached the menu despite missing geckolib — nothing to repair")
    api.stop(bid)
    for p, bak in backup_pairs:
        if os.path.isfile(bak):
            shutil.move(bak, p)
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
    for p, bak in backup_pairs:
        if os.path.isfile(bak):
            os.remove(bak)
    for d in (MODS, DL_MODS):
        for f in os.listdir(d):
            if f.endswith(".jar.bak"):
                os.remove(os.path.join(d, f))

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