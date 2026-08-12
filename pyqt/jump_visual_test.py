"""Visual proof of the jump-to-page feature: renders the real DiscoverView
(the exact code baked into the installed 1.0.6 binary) offscreen, runs a real
provider search, jumps to page 5 via the actual jump spin box, and saves
before/after screenshots + assertions.

Run: pyqt/.venv/Scripts/python pyqt/jump_visual_test.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from PyQt6.QtWidgets import QApplication  # noqa: E402
import theme  # noqa: E402
from engine.service import PyEngine  # noqa: E402
from common import run_async  # noqa: E402

app = QApplication(sys.argv)
theme.setup_fonts(app)
from views.discover import DiscoverView  # noqa: E402

eng = PyEngine()
v = DiscoverView(eng)
v.resize(1280, 900)
v.show()
app.processEvents()

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {extra}" if extra else ""))
    if not cond:
        failures.append(name)


# --- real search, page 1 ---
v._search.setText("create")
v._search_serial += 1
serial = v._search_serial
v._show_loading()


def fetch():
    return v.api.search(q="create", provider="modrinth", mc="auto", loader="all",
                        type="mod", offset=0)


def ok(result):
    v._hits = result.get("hits") or []
    v._apply_results("create", result)


v._search_serial = serial
run_async(fetch, ok, lambda e: check("search fetch", False, str(e)))
deadline = time.time() + 40
while time.time() < deadline and not v._hits:
    app.processEvents()
    time.sleep(0.05)
check("page 1 loaded real hits", len(v._hits) > 0, f"{len(v._hits)} hits")
check("pager shows total-page estimate", f"({v._total and (v._total + v._page_size - 1) // max(1, v._page_size)} pages)" in v._pager_status.text(),
      v._pager_status.text())
p1_ids = [h.get("projectId") for h in v._hits]
v.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workspace", "jump-page1.png"))
print("saved workspace/jump-page1.png")

# --- jump to page 5 via the actual spin box ---
check("jump spin enabled with real total", v._jump_spin.isEnabled(), f"max={v._jump_spin.maximum()}")
v._jump_spin.setValue(5)
deadline = time.time() + 40
while time.time() < deadline and not (v._page == 4 and "Page 5" in v._pager_status.text()):
    app.processEvents()
    time.sleep(0.05)
check("jump navigated to page 5", v._page == 4 and "Page 5" in v._pager_status.text(),
      v._pager_status.text())
p5_ids = [h.get("projectId") for h in v._hits]
check("page 5 returned real hits", len(p5_ids) > 0, f"{len(p5_ids)} hits")
check("page 5 results differ from page 1", bool(p5_ids) and not set(p1_ids) & set(p5_ids),
      f"overlap: {len(set(p1_ids) & set(p5_ids))}")
v.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workspace", "jump-page5.png"))
print("saved workspace/jump-page5.png")

# --- back to page 1 via the spin box ---
v._jump_spin.setValue(1)
deadline = time.time() + 40
while time.time() < deadline and not (v._page == 0 and "Page 1" in v._pager_status.text()):
    app.processEvents()
    time.sleep(0.05)
check("jump returned to page 1", v._page == 0 and "Page 1" in v._pager_status.text(),
      v._pager_status.text())

print("JUMP VISUAL " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
