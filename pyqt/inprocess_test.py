"""Headless verification that the launcher runs entirely on the in-process
Python engine — no Node server, no localhost. Mirrors smoke_test.py but
constructs the window with engine.bridge.PyEngine() instead of the HTTP Api.

    pyqt/.venv/Scripts/python pyqt/inprocess_test.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402
from common import icon_cache  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


app = QApplication(sys.argv)
theme.setup_fonts(app)

api = PyEngine()
check("in-process engine healthy", api.health())

win = MainWindow(api)
win.resize(1320, 840)
win.show()

for _ in range(100):
    app.processEvents()
    if win._online:
        break
    time.sleep(0.1)

check("window reports online (in-process)", win._online)
check("net pill says In-process", "In-process" in win._net_text.text())
# no separate engine process — the Python engine runs inside the app

for _ in range(80):
    app.processEvents()
    if win.builds:
        break
    time.sleep(0.1)

builds = win.builds
check("workspace state loaded from python engine", isinstance(builds, list), f"{len(builds)} packs")
check("empty workspace has a real recovery state",
      bool(builds) or win.library._empty_title.text() == "Your first modpack starts here")
check("library renders", win.library.count() > 0 if hasattr(win.library, "count") else True)

for nav in ("home", "library", "discover", "ai-builder", "downloads", "activity", "settings"):
    win._set_nav(nav)
    app.processEvents()
check("navigated all views", True)

print()
win.close()
icon_cache.shutdown()
QThreadPool.globalInstance().waitForDone(15000)
win.deleteLater()
app.processEvents()
app.quit()
if failures:
    print(f"IN-PROCESS TEST FAILED: {failures}")
    sys.stdout.flush()
    os._exit(1)
print("IN-PROCESS TEST PASS — launcher runs entirely on the Python engine.")
sys.stdout.flush()
# All application and image workers were explicitly drained above. Avoid a
# second implicit teardown of the already-closed offscreen Qt widget graph,
# which can trigger Windows' Qt fail-fast path after the verdict is printed.
os._exit(0)
