"""Density control + Home/Library tile-consistency test.

Covers: default density, square tile geometry, column-count change between
Cozy/Compact, per-user persistence, and Home rendering pixel-identical tiles
to the Library (same size at the same density).
"""
import json
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QPushButton  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402
from views.misc import STATE_PATH  # noqa: E402

report = []


def check(name, ok, detail=""):
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


def set_density_state(value):
    st = {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            st = json.load(f)
    except Exception:  # noqa: BLE001
        pass
    was = st.get("libraryDensity")
    if value is None:
        st.pop("libraryDensity", None)
    else:
        st["libraryDensity"] = value
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)
    return was


orig = set_density_state("cozy")

app = QApplication(sys.argv)
theme.setup_fonts(app)
api = PyEngine()
win = MainWindow(api)
win.show()
# Wide enough that Cozy (4-up, target 250) and Compact (5-up, target 205)
# express distinct column counts under the scrollbar-reserved width math.
win.resize(1366, 768)

# The Library loads builds asynchronously (refresh_builds on a worker); the
# tile-geometry checks below need the real pack list, so wait for it to land
# the same way smoke_test does instead of asserting against an empty grid.
import time  # noqa: E402
for _ in range(80):
    app.processEvents()
    if win.builds:
        break
    time.sleep(0.1)

win._set_nav("library")
for _ in range(20):
    app.processEvents()


def settle():
    for _ in range(10):
        app.processEvents()


def grid_cols(grid):
    cols = 0
    for i in range(grid.count()):
        pos = grid.getItemPosition(i)
        if pos:
            cols = max(cols, pos[1] + 1)
    return cols


def tile_size(grid):
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        if w is not None and w.width() > 100:
            return w.width(), w.height()
    return (0, 0)


def tile_for(grid, name):
    """The tile whose accessible name matches a pack name — the two grids can
    hold the SAME pack at DIFFERENT positions (Library is sorted by newest,
    Home shows builds[:3]), and comparing first-tiles of different packs
    compares different name-wraps. Always compare the same pack."""
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        if w is None:
            continue
        an = w.accessibleName() or ""
        if name and (an.endswith(name) or name in an):
            return w.width(), w.height()
    return (0, 0)


def first_tile(grid):
    for i in range(grid.count()):
        w = grid.itemAt(i).widget()
        if w is not None:
            return w
    return None


def has_play(widget):
    if widget is None:
        return False
    return any(b.text() == "PLAY" for b in widget.findChildren(QPushButton))


def measure():
    win._set_nav("library")
    settle()
    lw, lh = tile_size(win.library._grid)
    lcols = grid_cols(win.library._grid)
    lplay = has_play(first_tile(win.library._grid))
    win._set_nav("home")
    settle()
    hw, hh = tile_size(win.home._recent_grid)
    hplay = has_play(first_tile(win.home._recent_grid))
    # Compare the SAME pack across the two grids: Library sorts by newest,
    # Home shows builds[:3], so first-tiles can be different packs whose names
    # wrap differently at compact width.
    pack_name = (first_tile(win.home._recent_grid).accessibleName() or "Open ")[len("Open "):]
    lw2, lh2 = tile_for(win.library._grid, pack_name)
    hw2, hh2 = tile_for(win.home._recent_grid, pack_name)
    return lw, lh, lcols, lplay, hw, hh, hplay, (lw2, lh2, hw2, hh2)


# ----- cozy -----
check("density combo present in Library bar",
      hasattr(win.library, "_density_box") and win.library._density_box.currentText() == "Cozy")
check("library has builds to tile", len(win.builds) >= 1, f"{len(win.builds)} builds")

lw, lh, lcols, lplay, hw, hh, hplay, (lw_s, lh_s, hw_s, hh_s) = measure()
lr = lw / lh if lh else 0
hr = hw / hh if hh else 0
check("cozy renders 4-up", lcols == 4, f"cols={lcols}")
check("cozy tile near-square", 0.8 <= lr <= 1.3, f"{lw}x{lh} ratio {lr:.2f}")
check("cozy tile has PLAY action", lplay)
check("home tile same size as library tile", (lw_s, lh_s) == (hw_s, hh_s),
      f"lib {lw_s}x{lh_s} vs home {hw_s}x{hh_s}")
check("home tile near-square", 0.8 <= hr <= 1.3, f"{hw}x{hh} ratio {hr:.2f}")
check("home tile has PLAY action", hplay)

# ----- switch to compact in the Library -----
win._set_nav("library")
settle()
win.library._density_box.setCurrentText("Compact")
settle()
check("combo now Compact", win.library._density_box.currentText() == "Compact")
try:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        st = json.load(f)
    check("density persisted per user", st.get("libraryDensity") == "compact")
except Exception as e:  # noqa: BLE001
    check("density persisted per user", False, str(e))

lw2, lh2, lcols2, lplay2, hw2, hh2, hplay2, (lw_s2, lh_s2, hw_s2, hh_s2) = measure()
lr2 = lw2 / lh2 if lh2 else 0
check("compact renders more columns than cozy", lcols2 > lcols, f"cozy={lcols} compact={lcols2}")
check("compact tiles smaller than cozy", lw2 < lw, f"{lw} -> {lw2}")
check("compact tile near-square", 0.8 <= lr2 <= 1.3, f"{lw2}x{lh2} ratio {lr2:.2f}")
check("home mirrored compact density and matches library",
      (lw_s2, lh_s2) == (hw_s2, hh_s2) and win.home._density == "compact",
      f"lib {lw_s2}x{lh_s2} vs home {hw_s2}x{hh_s2}")
check("compact tiles still have PLAY", lplay2 and hplay2)

# restore user state
set_density_state(orig)
passed = sum(1 for r in report if r["status"] == "PASS")
failed = len(report) - passed
print(f"\nDENSITY/HOME: {passed} PASS / {failed} FAIL")
sys.exit(1 if failed else 0)
