"""Add Content page overflow test — no hidden horizontal overflow at the
minimum supported content size (window 1080x700 minus a 224 px sidebar), with
a populated results grid AND with the detail drawer open. Mirrors the checks
responsive_layout_test applies to the sidebar pages.

Run: pyqt/.venv/Scripts/python pyqt/addcontent_overflow_test.py
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QScrollArea  # noqa: E402

app = QApplication(sys.argv)

from views.addcontent import AddContentView  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


class API:
    def search(self, **kwargs):
        hits = [{
            "slug": f"mod-{i}", "projectId": f"P{i}", "title": f"Compatible Mod Number {i}",
            "description": "A reasonably long project summary line to stress card wrapping.",
            "provider": "modrinth" if i % 2 else "curseforge",
            "projectType": "mod", "downloads": 1000 * (i + 1),
            "categories": ["adventure", "technology"],
        } for i in range(20)]
        return {"hits": hits, "error": None, "page_size": 20, "total": 20,
                "more": False, "browse": True, "sources": [
                    {"provider": "modrinth", "ok": True, "count": 10, "total": 10,
                     "available": True, "error": None}]}

    def project_details(self, provider, pid, mc=None, loader=None):
        return {"project": {"title": "Mod", "description": "d"},
                "versions": [{"versionId": "v1", "versionNumber": "1.0",
                              "releaseChannel": "release", "loaders": ["forge"]}],
                "provider": provider}


view = AddContentView(API())
# Minimum window minus sidebar = smallest content surface we ship.
view.resize(1080 - 224, 700 - 60)
view.set_pack({"buildId": "b1", "name": "Overflow Pack", "mcVersion": "1.20.1", "loader": "forge"})
view.show()

t0 = time.time()
while time.time() - t0 < 8 and not view._hits:
    app.processEvents()
    time.sleep(0.02)

app.processEvents()


def overflow(view) -> int:
    """Hidden-overflow amount: scroll extent minus viewport width."""
    area = view.findChildren(QScrollArea)[0]
    return max(0, area.horizontalScrollBar().maximum())


check("populated grid has zero hidden horizontal overflow", overflow(view) == 0,
      f"{overflow(view)} px")

clipped = []
for btn in view.findChildren(type(view._next_btn)):
    if btn.isVisible():
        right = btn.mapTo(view, btn.rect().topRight()).x()
        if right > view.width() + 1:
            clipped.append(f"{btn.text()}@{right}")
check("all visible buttons end inside the view", not clipped, str(clipped[:3]))

view._open_drawer(view._hits[0])
t0 = time.time()
while time.time() - t0 < 8 and "checking" in view._detail_status.text().lower():
    app.processEvents()
    time.sleep(0.02)
app.processEvents()
drawer = view._drawer
check("drawer fits inside the view", drawer.width() <= view.width(),
      f"drawer {drawer.width()} vs view {view.width()}")
close_right = drawer.findChildren(type(view._next_btn))[0] if False else None
from common import icon_btn  # noqa: E402
closes = [w for w in drawer.findChildren(type(icon_btn(drawer, "x", "t")))
          if w.isVisible()]
if closes:
    r = max(w.mapTo(view, w.rect().topRight()).x() for w in closes)
    check("drawer close button inside the view", r <= view.width(), f"@{r}")
else:
    check("drawer close button present", False)
primary = getattr(view, "_drawer_primary", None)
check("drawer primary action enabled after details",
      primary is not None and primary.isEnabled())
check("drawer open does not overflow the grid", overflow(view) == 0, f"{overflow(view)} px")
view._close_drawer()

print()
if failures:
    print(f"ADD CONTENT OVERFLOW TEST FAILED — {failures}")
    sys.exit(1)
print("ADD CONTENT OVERFLOW TEST PASS — no hidden overflow, all controls reachable.")
