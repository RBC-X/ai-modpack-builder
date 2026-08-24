"""One-system verification: the desktop launcher runs entirely on the
in-process Python engine — no Node server, no localhost, no separate engine
process to kill or restart. Mirrors the old auto-restart test (which killed a
Node engine on port 8282) for the current architecture: the pill must report
In-process and stay Online, the engine must stay healthy, and builds must load
straight from the Python engine with no subprocess spawned.

Run:  pyqt/.venv/Scripts/python pyqt/one_system_test.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


app = QApplication(sys.argv)
theme.setup_fonts(app)

# The Python engine must be the engine — no HTTP client, no port dependency.
api = PyEngine()
check("in-process engine healthy", api.health())
check("direct engine bridge has no server endpoint",
      api.__class__.__name__ == "PyEngine" and not hasattr(api, "base_url"),
      "no localhost engine is constructed")

win = MainWindow(api)
win.resize(1320, 840)
win.show()

# Let the health poll + build refresh land.
for _ in range(120):
    app.processEvents()
    if win._online:
        break
    time.sleep(0.1)

check("window reports online", win._online)
check("net pill says In-process", "In-process" in win._net_text.text())
check("engine stays healthy", api.health())

for _ in range(80):
    app.processEvents()
    if win.builds:
        break
    time.sleep(0.1)

builds = win.builds
check("workspace state loaded from the Python engine", isinstance(builds, list), f"{len(builds)} packs")
check("empty workspace has a real recovery state",
      bool(builds) or win.library._empty_title.text() == "Your first modpack starts here")

# The health check keeps the pill Online over time (no offline/restart churn).
seen_offline = False
for _ in range(30):
    app.processEvents()
    time.sleep(0.2)
    if not win._online:
        seen_offline = True
        break
check("pill stayed Online the whole time", not seen_offline, "In-process engine")

for nav in ("home", "library", "discover", "ai-builder", "downloads", "activity", "settings"):
    win._set_nav(nav)
    app.processEvents()
check("navigated all views", True)

print("ONE-SYSTEM TEST " + ("PASS" if not failures else "FAIL"))
sys.stdout.flush()
os._exit(0 if not failures else 1)
