"""UI-level test of the Library "NEW PACK" flow: click the button, fill the
dialog, submit, and verify a real blank pack appears in the engine (and that a
mod can then be added to it, which is the point of a blank pack).

Run:  pyqt/.venv/Scripts/python pyqt/new_pack_test.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

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
api = PyEngine()
check("in-process engine healthy", api.health())

win = MainWindow(api)
win.resize(1320, 840)
win.show()
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)

# 1) Library has the NEW PACK button.
win._set_nav("library")
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)

buttons = win.library.findChildren(QPushButton)
new_btn = next((b for b in buttons if b.text() == "NEW PACK"), None)
check("Library shows NEW PACK button", new_btn is not None)

# 2) Clicking it opens the dialog.
new_btn.click()
for _ in range(20):
    app.processEvents()
    time.sleep(0.05)
check("dialog opens", win.new_pack_dialog.isVisible())

# 3) Fill + submit.
dlg = win.new_pack_dialog
dlg._name.setText("UI Test Pack")
dlg._loader.setCurrentText("Fabric")
dlg._ram.setValue(4)
dlg._submit()
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)
check("dialog closed after submit", not dlg.isVisible())

# 4) The pack appears in the engine (async create completes).
bid = None
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.2)
    for b in api.builds():
        if b.get("name") == "UI Test Pack":
            bid = b.get("buildId")
            break
    if bid:
        break
check("pack created in engine", bid is not None, f"buildId {bid}")
if bid:
    rec = api.build(bid)
    check("record is a blank pack", rec.get("selections") == [] and rec.get("status") == "done")
    check("requested loader/ram recorded",
          rec.get("requirements", {}).get("loader") == "fabric" and rec.get("requirements", {}).get("ramGB") == 4,
          f"loader {rec.get('requirements', {}).get('loader')}, ram {rec.get('requirements', {}).get('ramGB')}")
    check("instance dirs created",
          os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "workspace", "builds", bid, "instance", "minecraft", "mods")))

    # 5) A real mod can be added to the blank pack (the whole point).
    out = api.add_mod(bid, "modrinth", "appleskin")
    check("mod addable to blank pack", bool(out.get("ok")), out.get("error") or "")
    if out.get("ok"):
        rec2 = api.build(bid)
        check("pack now has mods", len(rec2.get("selections", [])) >= 1,
              f"{[s.get('slug') for s in rec2.get('selections', [])]}")

# Clean up the pack this run created so repeated runs don't accumulate
# "UI Test Pack" entries in the library (they used to pile up forever).
if bid:
    try:
        api.delete_pack(bid)
        check("test pack cleaned up", True)
    except Exception as e:
        check("test pack cleaned up", False, str(e))

print("NEW PACK TEST " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
