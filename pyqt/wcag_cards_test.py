"""WCAG sweep on the clickable card surfaces (the round's remaining
keyboard gap): pack tiles (Library + Home), starter-concept cards, and the
sidebar nav regression. Verifies every card is tab-focusable and activates
on Enter/Space exactly like a click, with a tooltip as accessible name.

The concept-card handler opens a modal dialog; we monkeypatch the handler
to record the call so the harness proves Enter invokes the *same* handler
as a click without blocking on exec().

Usage: python pyqt/wcag_cards_test.py
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

WORK = HERE.parent / ".freebuff" / "wcag-test"
shutil.rmtree(WORK, ignore_errors=True)
WORK.mkdir(parents=True, exist_ok=True)
os.environ["AMB_WORKSPACE"] = str(WORK)

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    if not cond:
        failures.append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" - {extra}" if extra else ""))


def make_completed_pack(api, name: str, bid: str) -> str:
    rec = {
        "buildId": bid, "name": name, "request": "WCAG test pack",
        "status": "done", "phase": "done", "requirements": {
            "minecraftVersion": "1.20.1", "loader": "forge", "ramGB": 4},
        "selections": [], "downloads": [], "graph": {"nodes": {}, "edges": []},
        "tests": [], "testResult": {"status": "PASS", "level": "standard"},
        "conflicts": [], "repairs": [], "exports": [], "packStats": {"modCount": 12},
        "settings": {}, "perfEstimate": None, "finalReport": "ok", "error": None,
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    api._s._write_record(rec)
    return bid


from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication, QFrame  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

app = QApplication(sys.argv)
theme.setup_fonts(app)

api = PyEngine()
bid = make_completed_pack(api, "WCAG Pack", "b-wcag-1")
win = MainWindow(api)
win.resize(1320, 840)
win.show()

for _ in range(80):
    app.processEvents()
    if any(b.get("buildId") == bid for b in win.library.builds):
        break
    time.sleep(0.1)
check("library lists the seeded pack", any(
    b.get("buildId") == bid for b in win.library.builds))

# ---- Library grid tiles: focusable + Enter/Space activate ----------------
win._set_nav("library")
app.processEvents()
for _ in range(30):
    app.processEvents()
    time.sleep(0.05)
tiles = [c for c in win.library.findChildren(QFrame)
         if (c.toolTip() or "").startswith("Open ")]
check("library pack tiles carry accessible names", len(tiles) >= 1,
      f"{len(tiles)} tiles")
check("library tiles are tab-focusable",
      all(c.focusPolicy() == Qt.FocusPolicy.TabFocus for c in tiles))

tile = tiles[0]
win.library.selected_id = None
QTest.keyClick(tile, Qt.Key.Key_Return)
app.processEvents()
check("Enter on a library tile selects the pack",
      win.library.selected_id == bid)
win.library.selected_id = None
QTest.keyClick(tile, Qt.Key.Key_Space)
app.processEvents()
check("Space on a library tile selects the pack",
      win.library.selected_id == bid)

# ---- Home starter-concept cards: focusable + Enter fires click handler ----
win._set_nav("home")
app.processEvents()
concepts = [c for c in win.home.findChildren(QFrame)
            if (c.toolTip() or "").startswith("Use ")]
check("starter-concept cards carry accessible names", len(concepts) >= 1,
      f"{len(concepts)} cards")
check("concept cards are tab-focusable",
      all(c.focusPolicy() == Qt.FocusPolicy.TabFocus for c in concepts))

opened: list = []
win.home._open_concept_editor = lambda concept, rollable=False: opened.append(concept)
QTest.keyClick(concepts[0], Qt.Key.Key_Return)
app.processEvents()
QTest.keyClick(concepts[1], Qt.Key.Key_Space)
app.processEvents()
check("Enter + Space on concept cards invoke the click handler",
      len(opened) == 2 and opened[0].get("title") and opened[1].get("title"))

# ---- sidebar nav regression (previous round's fix still holds) ------------
nav = win.nav_btns["library"][0]
check("sidebar nav item still tab-focusable",
      nav.focusPolicy() == Qt.FocusPolicy.TabFocus)
win._set_nav("home")
QTest.keyClick(nav, Qt.Key.Key_Return)
app.processEvents()
check("Enter on nav item still navigates",
      win.active_nav == "library")

win.close()
app.processEvents()
from common import icon_cache  # noqa: E402
icon_cache.shutdown()
time.sleep(0.3)
shutil.rmtree(WORK, ignore_errors=True)

ok = not failures
print("WCAG CARDS PASS" if ok else "WCAG CARDS FAIL")
sys.exit(0 if ok else 1)
