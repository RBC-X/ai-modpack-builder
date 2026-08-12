"""Print live widget geometries used by visual-regression diagnostics."""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402


def settle(app: QApplication, seconds: float = 1.0) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


app = QApplication(sys.argv)
theme.setup_fonts(app)
win = MainWindow(PyEngine())
win.resize(1320, 840)
win.show()
settle(app, 2.0)

for nav in ("home", "library", "discover", "ai-builder", "downloads", "activity", "settings"):
    win._set_nav(nav)
    settle(app, 0.5)
    view = win.stack.currentWidget()
    scroll = view.findChild(__import__("PyQt6.QtWidgets", fromlist=["QScrollArea"]).QScrollArea)
    body = scroll.widget() if scroll else None
    print(
        nav,
        "stack", win.stack.size().width(), win.stack.size().height(),
        "view", view.size().width(), view.size().height(),
        "scroll", (scroll.size().width(), scroll.size().height()) if scroll else None,
        "viewport", (scroll.viewport().size().width(), scroll.viewport().size().height()) if scroll else None,
        "body", (body.size().width(), body.size().height()) if body else None,
    )

win.close()
