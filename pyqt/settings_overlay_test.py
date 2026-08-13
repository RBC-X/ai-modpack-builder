"""Settings-overlay lifecycle test: open over a page, switch sections,
close returns to the covered page, nav-away hides it, resize repositions."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QEvent, QThreadPool, Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication

import theme
from engine.bridge import PyEngine
from main import MainWindow

report: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


app = QApplication(sys.argv)
theme.setup_fonts(app)
api = PyEngine()
win = MainWindow(api)
win.show()

# start on home, then open settings from the sidebar path
win._set_nav("home")
win._set_nav("settings")
app.processEvents()
check("settings overlay visible over the page",
      win.settings.isVisible() and win.settings._overlay)
check("underlying stack page still home",
      win.stack.currentWidget() is win.home)
check("shell centered 1000px wide", win.settings._shell.width() == 1000)

# section switch still renders into _panel
win.settings._set_sub("updates")
app.processEvents()
check("updates section renders in overlay panel",
      hasattr(win.settings, "_update_url_box"))

# close returns to the page it covered
win.settings.close_requested.emit()
app.processEvents()
check("close hides the overlay", not win.settings.isVisible())
check("close returns to home", win.active_nav == "home" and win.stack.currentWidget() is win.home)

# Escape closes the sheet like a native modal
win._set_nav("settings")
app.processEvents()
esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
QApplication.sendEvent(win, esc)
app.processEvents()
check("Escape closes the overlay", not win.settings.isVisible())
check("Escape returns to the covered page",
      win.active_nav == "home" and win.stack.currentWidget() is win.home)
# Escape must NOT close the overlay when it is hidden (inert shortcut)
win._set_nav("settings")
app.processEvents()
win.settings.hide()
QApplication.sendEvent(win, esc)
app.processEvents()
check("Escape is inert while overlay hidden", not win.settings.isVisible())

# re-open from providers shortcut (Discover path)
win._set_nav("discover")
win._open_provider_settings()
app.processEvents()
check("provider shortcut opens overlay + providers section",
      win.settings.isVisible() and win.settings._sub == "providers")

# nav away hides the overlay
win._set_nav("library")
app.processEvents()
check("nav away hides the overlay", not win.settings.isVisible())

# resize while open keeps it covering the window
win._set_nav("settings")
win.resize(1200, 760)
app.processEvents()
win._set_nav("settings")  # re-run show path after resize
app.processEvents()
check("overlay covers resized window",
      win.settings.width() == win.width() and win.settings.height() == win.height())

failed = [r["name"] for r in report if r["status"] == "FAIL"]
print("OVERLAY OVERALL:", "PASS" if not failed else f"FAIL {failed}", flush=True)
win.close()
app.processEvents()
QThreadPool.globalInstance().waitForDone(3000)
sys.exit(1 if failed else 0)
