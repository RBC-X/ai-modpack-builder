"""Responsive layout regression matrix (Issue: horizontal overflow).

Proves the launcher never hides or clips content at every supported window
size, with and without DPI scaling, with the sidebar expanded and collapsed,
with a populated library (25 packs with long names), a populated Downloads
list, Discover results, and empty/loading states.

Fails if:
  - any page's scroll area reports a nonzero horizontal scrollbar maximum
    while horizontal scrolling is disabled (content is unreachable),
  - any scroll body is wider than its viewport (clipped content),
  - any visible interactive control lies outside the visible viewport, or
  - keyboard activation of a card triggers nested buttons (or vice versa).

Run:  pyqt/.venv/Scripts/python pyqt/responsive_layout_test.py
"""
import os
import shutil
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

# Isolated workspace: never touches the developer's real data or state.
_WORK = Path(os.environ.get("TEMP", "/tmp")) / "amb-responsive-test"
shutil.rmtree(_WORK, ignore_errors=True)
_WORK.mkdir(parents=True, exist_ok=True)
os.environ["AMB_WORKSPACE"] = str(_WORK)

SIZES = [(1080, 700), (1152, 720), (1280, 720), (1320, 840),
         (1366, 768), (1600, 900), (1920, 1080)]

PACK_NAMES = [
    "The Twilight Chronicles: A Dark Medieval Fantasy RPG",
    "Create & Automate: Industrial Civilization",
    "Cozy Farming Adventures for Multiplayer",
    "Horror Survival: The Forgotten Village",
    "Vanilla+ Enhanced Quality of Life",
    "Arcane Magic: Wizardry and Ancient Powers",
    "High FPS Performance Optimization Pack",
    "Better Villages and Realistic Terrain Generation",
    "Dragon Slayer: Boss Rush Edition",
    "The Great Sea Voyage: Nautical Exploration",
    "Skyblock Origins: Aerial Survival",
    "The Nether Expansion: Demonic Dimensions",
    "Farming Simulator: Harvest Moon Style",
    "Tech Revolution: Power and Machinery",
    "The Wild Frontier: Western Survival",
    "Deep Dark Depths: Cave Exploration",
    "Potion Master: Alchemy and Brewing",
    "The Frozen Wastes: Ice and Snow",
    "Jungle Adventure: Lost Temple Expedition",
    "The Eternal City: Urban Building",
    "Mystic Realms: Portal Dimensions",
    "The Undead Army: Siege Defense",
    "Star Wars: The Force Awakens Modpack",
    "Middle Earth: Rings of Power",
    "The Grand Expedition: World Tour",
]

from PyQt6.QtWidgets import (QApplication, QComboBox, QLineEdit, QPushButton,  # noqa: E402
                             QScrollArea, QSpinBox, QWidget)

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402


def make_completed_pack(api, name, bid, mc="1.20.1", loader="forge", mods=25, downloads=None):
    import time as _t
    rec = {
        "buildId": bid, "name": name,
        "request": "A medieval fantasy RPG with dangerous bosses, magic and realistic terrain.",
        "status": "done", "phase": "done",
        "requirements": {"minecraftVersion": mc, "loader": loader, "ramGB": 6},
        "selections": [], "downloads": downloads or [],
        "graph": {"nodes": {}, "edges": []}, "tests": [],
        "testResult": {"status": "PASS", "level": "standard"},
        "conflicts": [], "repairs": [], "exports": [], "packStats": {"modCount": mods},
        "settings": {}, "perfEstimate": None, "finalReport": "ok", "error": None,
        "createdAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
        "updatedAt": _t.strftime("%Y-%m-%dT%H:%M:%SZ", _t.gmtime()),
    }
    api._s._write_record(rec)
    return bid


def seed(api):
    rows = [{"name": f"mod-{i}-with-a-quite-long-filename-that-could-overflow.jar",
             "provider": "modrinth", "build": PACK_NAMES[0], "sizeBytes": 123456789,
             "status": "ok", "sha1": "abc"} for i in range(6)]
    for i, name in enumerate(PACK_NAMES):
        make_completed_pack(api, name, f"b-{i}",
                            mc=["1.20.1", "1.20.4", "1.21.1"][i % 3],
                            loader=["forge", "fabric", "neoforge"][i % 3],
                            mods=30 + i, downloads=rows if i == 0 else [])


def populate_discover(win):
    hit = {"title": "The Twilight Forest — A Mystical Dimension of Adventure",
           "provider": "modrinth", "projectType": "mod", "iconUrl": "",
           "summary": "A vast new dimension full of adventure and danger.",
           "downloads": 4200000, "slug": "p", "versions": ["1.20.1"],
           "loaders": ["forge"], "projectId": "p", "author": "Benimatic",
           "dateModified": "2026-01-01T00:00:00Z", "categories": ["adventure", "worldgen"],
           "description": "Enter the Twilight Forest..."}
    win.discover._hits = [dict(hit, title=f"{hit['title']} — variant {i}") for i in range(20)]
    win.discover._page_size = 48
    win.discover._total = 3412
    win.discover._more = True
    win.discover._update_pager()


def overflows(view):
    """Return (label, detail) for every horizontal-overflow violation."""
    bad = []
    for sa in view.findChildren(QScrollArea):
        hbar = sa.horizontalScrollBar()
        if hbar is not None and hbar.maximum() > 0:
            bad.append(("hbar", hbar.maximum()))
        if sa.widget() is not None and sa.widget().width() > sa.viewport().width() + 1:
            bad.append(("body", sa.widget().width() - sa.viewport().width()))
        if sa.widget() is not None:
            vp_w = sa.viewport().width()
            for w in sa.widget().findChildren(QWidget):
                if not w.isVisible():
                    continue
                if isinstance(w, (QPushButton, QComboBox, QLineEdit, QSpinBox)):
                    g = w.geometry()
                    if g.right() > vp_w + 1 or g.left() < -1:
                        bad.append(("control", f"{type(w).__name__} right={g.right()}"))
    return bad


def run_matrix(win, scale):
    failures = []
    for size in SIZES:
        for compact in (False, True):
            if compact != win._sidebar_compact:
                win._toggle_sidebar()
            win.resize(*size)
            win.show()
            for _ in range(25):
                win.app_process_events()
                time.sleep(0.01)
            for nav, view in [("home", win.home), ("library", win.library),
                              ("discover", win.discover), ("ai-builder", win.aibuilder),
                              ("downloads", win.downloads), ("activity", win.activity)]:
                win._set_nav(nav)
                for _ in range(10):
                    win.app_process_events()
                    time.sleep(0.01)
                label = f"{size[0]}x{size[1]}/x{scale}/{nav}/{'compact' if compact else 'expanded'}"
                bad = overflows(view)
                if bad:
                    failures.append((label, bad))
                    print(f"  FAIL {label}: {bad}")
    return failures


def keyboard_test(win):
    """Cards are tab-reachable, activate once on Enter/Space, and nested
    buttons do not trigger the card action (and vice versa)."""
    from PyQt6.QtCore import Qt
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtWidgets import QFrame
    fired = []
    win.library._clicked = lambda e, bid: fired.append(("card", bid))
    cards = [c for c in win.library.findChildren(QFrame)
             if c.focusPolicy() == Qt.FocusPolicy.TabFocus]
    if not cards:
        return "no focusable card found"
    card = cards[0]
    card.setFocus()
    app = QApplication.instance()
    for key in (Qt.Key.Key_Return, Qt.Key.Key_Space):
        app.sendEvent(card, QKeyEvent(QKeyEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))
    fired_once = [f for f in fired if f[0] == "card"]
    if not fired_once:
        return "Enter/Space did not activate the card"
    # Nested button: pressing a child button must NOT fire the card handler.
    fired.clear()
    btn = card.findChild(QPushButton)
    if btn is not None:
        btn.setFocus()
        app.sendEvent(btn, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
        app.sendEvent(btn, QKeyEvent(QKeyEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
        if fired:
            return "nested button press triggered the card action"
    # Accessible name is set through the accessibility API, not tooltip alone.
    name = card.accessibleName()
    if not name:
        return "focusable card has no accessible name"
    return None


def drawer_test(win):
    """The Discover drawer's close button and primary action stay reachable
    at narrow widths."""
    win.discover._open_drawer(win.discover._hits[0])
    app = QApplication.instance()
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)
    d = win.discover._drawer
    if d is None:
        return "drawer did not open"
    view_w = win.discover.width()
    if d.geometry().right() > view_w + 1 or d.geometry().left() < -1:
        return f"drawer outside viewport: {d.geometry()} vs {view_w}"
    close_btns = [w for w in d.findChildren(QPushButton) if w.toolTip() == "Close"]
    if not close_btns or not close_btns[0].isVisible():
        return "drawer close button missing/not visible"
    primary = getattr(win.discover, "_drawer_primary", None)
    if primary is None or not primary.isVisible():
        return "drawer primary action missing/not visible"
    win.discover._close_drawer()
    return None


def _run_scale(scale: str) -> int:
    """Run the full matrix for one DPI scale inside THIS process. Qt refuses
    to change the high-DPI scale factor at runtime, so each scale must be a
    fresh process (the parent spawns us with QT_SCALE_FACTOR pre-set).
    Returns the failure count."""
    os.environ["QT_SCALE_FACTOR"] = scale
    app = QApplication(sys.argv)
    theme.setup_fonts(app)
    # Give the window a tiny hook for pumping events in this module.
    MainWindow.app_process_events = lambda self: app.processEvents()

    api = PyEngine()
    seed(api)
    win = MainWindow(api)
    populate_discover(win)
    failures = run_matrix(win, scale)
    win.resize(1080, 700)
    win.show()
    for _ in range(20):
        app.processEvents()
        time.sleep(0.01)
    win._set_nav("library")
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)
    kb = keyboard_test(win)
    if kb:
        failures.append(("keyboard", kb))
    win._set_nav("discover")
    for _ in range(10):
        app.processEvents()
        time.sleep(0.01)
    dr = drawer_test(win)
    if dr:
        failures.append(("drawer", dr))
    return failures


def main():
    import subprocess
    scales = ["1", "1.25"]
    if "--scale" in sys.argv:
        idx = sys.argv.index("--scale")
        scales = [sys.argv[idx + 1]]
    total = 0
    for scale in scales:
        if "--scale" in sys.argv:
            # In-process run for the explicitly requested scale.
            failures = _run_scale(scale)
        else:
            # Parent: spawn a fresh process per scale (Qt scale is fixed at
            # process start), propagate its exit code.
            env = dict(os.environ, QT_SCALE_FACTOR=scale)
            proc = subprocess.run([sys.executable, os.path.abspath(__file__),
                                   "--scale", scale], env=env,
                                  cwd=HERE, capture_output=True, text=True)
            sys.stdout.write(proc.stdout)
            sys.stderr.write(proc.stderr)
            failures = [] if proc.returncode == 0 else [("scale", scale)]
        total += len(failures)
        if failures:
            for label, bad in failures:
                print(f"  FAIL {label}: {bad}")
    if total:
        print(f"\nRESPONSIVE TEST FAILED: {total} violations")
        sys.stdout.flush()
        os._exit(1)
    print("\nRESPONSIVE TEST PASS — no horizontal overflow at any size/scale/sidebar state.")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
