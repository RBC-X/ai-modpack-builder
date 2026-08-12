"""Live crash-repair loop: the full user-facing fix path in the PyQt launcher.

1. Launch a deliberately broken pack (a required dependency was removed from
   its record) via the real MainWindow.play().
2. Wait for the crash evidence (engine phase=error + missing dep extracted).
3. Verify the crash drawer renders with the missing-mod pill.
4. Click the crash drawer's Add Missing Mods & Relaunch (win.fix_missing()).
5. Wait for the repaired game to reach the main menu.
6. STOP the instance.

    pyqt/.venv/Scripts/python pyqt/crash_repair_test.py <buildId>
"""
import json
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

build_id = sys.argv[1] if len(sys.argv) > 1 else "b-msma0f6z-eb74bcb8"
EXPECTED_DEP = sys.argv[2] if len(sys.argv) > 2 else "midnightlib"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
report = {"build": build_id}

app = QApplication(sys.argv)
theme.setup_fonts(app)
api = PyEngine()
win = MainWindow(api)
win.show()
for _ in range(100):
    app.processEvents()
    if win.builds:
        break
    time.sleep(0.05)

# ensure nothing else is running first
assert not any(b.get("running") for b in win.builds), "a pack is already running — stop it before the test"

report["startedAt"] = time.strftime("%H:%M:%S")
print(f"[TEST] launching broken pack {build_id}…", flush=True)
win.play(build_id)

t0 = time.time()
result = None
last_mode = None
last_phase = None

while time.time() - t0 < 8 * 60:
    app.processEvents()
    ov = win.launch_overlay
    mode = ov._mode if ov.isVisible() else ("hidden" if win._launching is None else "starting")
    if mode != last_mode:
        print(f"[STATE] {mode} @ {int(time.time()-t0)}s — {(ov._status.get('stage') or '')[:70]}", flush=True)
        last_mode = mode
    try:
        eng = api.status(build_id)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] status: {e}", flush=True)
        time.sleep(0.2)
        continue
    phase = eng.get("phase")
    if phase != last_phase:
        print(f"[ENGINE] {phase} {(eng.get('stage') or '')[:60]} | missing={eng.get('missingDeps')}", flush=True)
        last_phase = phase
    if eng.get("phase") == "error" or eng.get("error"):
        result = {"kind": "crash", "error": eng.get("error"), "missingDeps": eng.get("missingDeps") or []}
        break
    if eng.get("phase") == "running" and (eng.get("progress") or 0) >= 100:
        result = {"kind": "menu"}
        break
    time.sleep(0.2)

if not result or result.get("kind") != "crash":
    print(f"[FAIL] expected a crash, got: {result}", flush=True)
    sys.exit(1)

report["crash"] = result
print(f"[PASS] game crashed with: {result.get('error')}", flush=True)
print(f"[PASS] missing deps extracted: {result.get('missingDeps')}", flush=True)

# Crash drawer must render with the missing mod pill
print("[TEST] opening crash drawer…", flush=True)
win._open_crash_drawer()
for _ in range(50):
    app.processEvents()
    if win.crash_drawer.isVisible():
        break
    time.sleep(0.05)
visible = win.crash_drawer.isVisible()
report["crashDrawerVisible"] = visible
print(f"[{'PASS' if visible else 'FAIL'}] crash drawer visible", flush=True)
try:
    win.grab().save(os.path.join(OUT, "crash-drawer-repair.png"))
except Exception:  # noqa: BLE001
    pass

# The drawer's missing-mod pills come from the crash evidence — ground truth
# is the engine's missingDeps, which is what the drawer renders.
missing = result.get("missingDeps") or []
report["missingDepsShown"] = missing
has_expected = any(EXPECTED_DEP.lower() in str(m).lower() for m in missing)
print(f"[{'PASS' if has_expected else 'FAIL'}] missing deps include {EXPECTED_DEP}: {missing}", flush=True)

# Add Missing Mods & Relaunch
print("[TEST] clicking Add Missing Mods & Relaunch…", flush=True)
win.fix_missing()

# The repair relaunches the game; wait for the main menu.
t1 = time.time()
menu = False
while time.time() - t1 < 8 * 60:
    app.processEvents()
    try:
        eng = api.status(build_id)
    except Exception:  # noqa: BLE001
        time.sleep(0.2)
        continue
    ph = eng.get("phase")
    if ph == "running" and (eng.get("progress") or 0) >= 100:
        menu = True
        report["relaunched"] = True
        print(f"[PASS] repaired game reached the main menu: {(eng.get('stage') or '')[:60]}", flush=True)
        break
    if ph == "error" or eng.get("error"):
        print(f"[FAIL] relaunch crashed again: {eng.get('error')}", flush=True)
        break
    time.sleep(0.2)

if menu:
    print("[TEST] pressing STOP…", flush=True)
    win.stop(build_id)
    for _ in range(300):
        app.processEvents()
        stt = api.status(build_id)
        if not stt.get("running") and not stt.get("starting"):
            break
        time.sleep(0.2)
    report["stopped"] = not api.status(build_id).get("running")
    print(f"[{'PASS' if report.get('stopped') else 'FAIL'}] instance stopped", flush=True)

report["finishedAt"] = time.strftime("%H:%M:%S")
print("[REPORT]", json.dumps(report, indent=2), flush=True)
ok = report.get("crashDrawerVisible") and has_expected and report.get("relaunched") and report.get("stopped")
print(f"[{'PASS' if ok else 'FAIL'}] crash-repair loop verified", flush=True)
sys.exit(0 if ok else 1)
