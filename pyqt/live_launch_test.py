"""Live launch test: drive the real PyQt MainWindow.play() flow.

Launches an actual Minecraft game on this machine through the launcher's own
code path (status poller, launch overlay, log tail). Verifies:
  1. overlay shows the "starting" state with live progress/stage
  2. the engine reaches the real main menu (phase=running, progress=100)
     AND the overlay reflects it ("Main menu reached")
  3. the game log tail streams
  4. STOP terminates the instance
  5. crash drawer renders when a crash happens

    pyqt/.venv/Scripts/python pyqt/live_launch_test.py <buildId>
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
TIMEOUT_S = 9 * 60
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")

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

# set an offline profile so the username flows into the launch
from views.misc import _load_state, _save_state  # noqa: E402
st = _load_state()
st["accountName"] = "Test_Player"
_save_state(st)
win._refresh_account_block()

report = {"build": build_id, "startedAt": time.strftime("%H:%M:%S"), "phases": [], "log_tail_len": 0}
print(f"[TEST] launching {build_id} via MainWindow.play()…", flush=True)
win.play(build_id)

result = {"mode": None}
last_mode = None
t0 = time.time()
engine_seen_menu = False


def sample():
    """One tick: engine truth + overlay state."""
    global last_mode, engine_seen_menu
    app.processEvents()
    ov = win.launch_overlay
    mode = ov._mode if ov.isVisible() else ("hidden" if win._launching is None else "starting")
    if mode != last_mode:
        print(f"[STATE] {mode} @ {int(time.time()-t0)}s — {ov._status.get('stage','')[:60]} {ov._status.get('progress','')}%", flush=True)
        last_mode = mode
        report["phases"].append({"t": int(time.time() - t0), "mode": mode,
                                 "stage": ov._status.get("stage", ""), "progress": ov._status.get("progress")})
        if mode in ("starting", "running", "crashed"):
            try:
                win.grab().save(os.path.join(OUT, f"launch-{mode}.png"))
            except Exception:  # noqa: BLE001
                pass
    try:
        eng = api.status(build_id)
    except Exception as e:  # noqa: BLE001
        print(f"[WARN] status fetch failed: {e}", flush=True)
        return
    tail = len(eng.get("gameLogTail") or [])
    if tail > report["log_tail_len"]:
        report["log_tail_len"] = tail
    ov_stage = ov._status.get("stage", "")
    ov_prog = ov._status.get("progress")
    ev = (f"engine: {eng.get('phase')} {eng.get('progress')}% | overlay: {ov._mode} {ov_prog}% "
          f"{'MAIN MENU' if 'Main menu reached' in ov_stage else ''} | tail={tail}")
    print(f"[SAMPLE] t={int(time.time()-t0)}s {ev}", flush=True)
    if eng.get("phase") == "running" and (eng.get("progress") or 0) >= 100:
        engine_seen_menu = True
        # give the overlay's own poll one more beat to reflect the menu
        if "Main menu reached" in ov_stage:
            result["mode"] = "running"
            result["mainMenuStage"] = ov_stage
    if eng.get("phase") == "error" or eng.get("error"):
        result["mode"] = "crashed"
        result["error"] = eng.get("error", "")
        result["missingDeps"] = eng.get("missingDeps")


timer = QTimer()
timer.timeout.connect(sample)
timer.start(2000)

deadline = time.time() + TIMEOUT_S
while time.time() < deadline and result["mode"] is None:
    app.processEvents()
    time.sleep(0.05)
timer.stop()

if result["mode"] == "running":
    print(f"[PASS] engine reached main menu; overlay reflected it: {result.get('mainMenuStage')}", flush=True)
    # STOP test
    print("[TEST] pressing STOP…", flush=True)
    win.stop(build_id)
    stopped = False
    for _ in range(300):  # up to 60s — a live game needs time to shut down
        app.processEvents()
        stt = api.status(build_id)
        if not stt.get("running") and not stt.get("starting"):
            stopped = True
            break
        time.sleep(0.2)
    report["stopped"] = stopped
    print(f"[{'PASS' if stopped else 'FAIL'}] instance stopped after STOP", flush=True)
    try:
        win.grab().save(os.path.join(OUT, "launch-stopped.png"))
    except Exception:  # noqa: BLE001
        pass
elif result["mode"] == "crashed":
    print(f"[INFO] game crashed: {result.get('error')}", flush=True)
    print("[TEST] opening crash drawer…", flush=True)
    win._open_crash_drawer()
    for _ in range(40):
        app.processEvents()
        if win.crash_drawer.isVisible():
            break
        time.sleep(0.05)
    report["crashDrawerVisible"] = win.crash_drawer.isVisible()
    print(f"[{'PASS' if report['crashDrawerVisible'] else 'FAIL'}] crash drawer visible", flush=True)
    try:
        win.grab().save(os.path.join(OUT, "crash-drawer.png"))
    except Exception:  # noqa: BLE001
        pass
else:
    print(f"[FAIL] neither main menu nor crash within {TIMEOUT_S}s (engine_seen_menu={engine_seen_menu})", flush=True)

report["finishedAt"] = time.strftime("%H:%M:%S")
print("[REPORT]", json.dumps(report), flush=True)
ok = result.get("mode") == "running" and report.get("stopped") is True and report.get("log_tail_len", 0) > 0
print(f"[{'PASS' if ok else 'FAIL'}] launch flow verified (mode={result.get('mode')}, log_tail_len={report.get('log_tail_len')})", flush=True)
sys.exit(0 if ok else 1)
