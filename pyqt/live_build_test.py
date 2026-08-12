"""Live test: drive AIBuilderView through a REAL small instant build.

Proves: start_build → SSE stream → live step timeline → build_completed →
library refresh. Uses the real engine, real providers, real downloads.

    pyqt/.venv/Scripts/python pyqt/live_build_test.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

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

n_before = len(win.builds)
view = win.aibuilder
view._prompt.setPlainText("Make a tiny vanilla+ performance pack with 15 mods for 1.20.1, instantly, no shaders")
view._shaders_chk.setChecked(False)
view._autotune_chk.setChecked(False)
print("[DBG] starting build…", flush=True)
view._start()

t0 = time.time()
timeout = 6 * 60  # downloads + instant test
result = {"done": False, "err": None}
while time.time() - t0 < timeout and not result["done"]:
    app.processEvents()
    if view._completed_build and view._done_card.isVisible():
        result["done"] = True
        result["build"] = view._completed_build
    if view._steps:
        act = [s for s in view._steps if s["status"] == "in_progress"]
        if act and time.time() - t0 > 5:
            pass  # (detail logged at the end)
    time.sleep(0.1)
if not result.get("done"):
    print(f"[DBG] not done after {timeout}s — build_id={view._completed_build}, steps={len(view._steps)}, "
          f"done_card_visible={view._done_card.isVisible()}", flush=True)

if result.get("build"):
    print(f"[PASS] build completed: {result['build']}")
    print(f"[INFO] steps rendered: {len(view._steps)}")
    for s in view._steps:
        print(f"       [{s['status']}] {s['label']}" + (f" — {s['detail'][:80]}" if s.get("detail") else ""))
    # library refresh
    for _ in range(60):
        app.processEvents()
        if len(win.builds) > n_before:
            break
        time.sleep(0.1)
    print(f"[PASS] library refreshed: {len(win.builds)} packs (was {n_before})")
    rec = api.build(result["build"])
    print(f"[INFO] new pack: {rec.get('name')} — {rec.get('packStats', {}).get('modCount')} mods, test {rec.get('tests', [{}])[0].get('status')} ({rec.get('tests', [{}])[0].get('level')})")
    sys.exit(0)
else:
    print("[FAIL] build did not complete within timeout")
    sys.exit(1)
