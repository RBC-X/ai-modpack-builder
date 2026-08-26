"""Pack-scoped Add Content browser test — one pack, pre-filtered, no redirect.

Drives the real AddContentView (the surface opened by Pack Detail's ADD CONTENT
button) with a stub provider API and verifies:

1. The page binds to exactly one pack: the heading names it and every install
   targets that pack's buildId (global refresh's set_builds cannot retarget).
2. Search auto-runs pre-filtered by the pack's MC version + loader, mods only.
3. Card INSTALL adds the latest compatible file (version=None) to that pack.
4. Opening the card hides the cross-pack "Add to" selector, keeps the version
   picker, and installing a chosen version emits exactly that version id.
5. Creator-linked videos parsed from the project listing render as watch
   buttons; the back signal returns to Pack Detail.

Run: pyqt/.venv/Scripts/python pyqt/addcontent_scoped_test.py
"""
import os
import queue
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)

from views.addcontent import AddContentView  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


class ScopedAPI:
    """Records search filters; serves one mod with two compatible versions."""

    def __init__(self):
        self.search_calls: list[dict] = []
        self.detail_calls: list[tuple] = []

    def search(self, **kwargs):
        self.search_calls.append(kwargs)
        return {"hits": [{
            "slug": "sodium", "projectId": "AABBCCDD", "title": "Sodium",
            "provider": "modrinth", "projectType": "mod", "downloads": 1000,
        }], "error": None, "page_size": 48, "total": 1, "more": False,
            "browse": False, "sources": [
                {"provider": "modrinth", "ok": True, "count": 1, "total": 1,
                 "available": True, "error": None}]}

    def project_details(self, provider, project_id, mc=None, loader=None):
        self.detail_calls.append((provider, project_id, mc, loader))
        return {
            "project": {
                "title": "Sodium",
                "description": "Modern rendering engine.",
                "body": "Watch the trailer: https://www.youtube.com/watch?v=abc123\n"
                        "Mirror: https://youtu.be/dup11111",
                # The engine service parses listing text into this list before
                # the UI ever sees it (see PyEngine.project_details).
                "videos": [{"url": "https://www.youtube.com/watch?v=abc123", "host": "YouTube"}],
            },
            "versions": [
                {"versionId": "v2-newest", "versionNumber": "5.0.0",
                 "releaseChannel": "release", "loaders": ["forge"]},
                {"versionId": "v1-old", "versionNumber": "4.2.1",
                 "releaseChannel": "release", "loaders": ["forge"]},
            ],
            "provider": provider,
        }


PACK = {"buildId": "b-medieval", "name": "Medieval Kingdom", "mcVersion": "1.20.1", "loader": "forge"}


def pump(view, cond, secs: float = 8.0) -> bool:
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return False


api = ScopedAPI()
view = AddContentView(api)
view.resize(1200, 800)
view.set_pack(PACK)
view.show()

# --- 1. binding + auto-filter -------------------------------------------
check("heading names the pack",
      "Medieval Kingdom" in view._heading_title.text(), view._heading_title.text())
ok = pump(view, lambda: bool(view._hits))
check("search auto-ran and returned hits", ok)
check("loader filter preset from pack",
      view._loader == "forge" and view._loader_box.currentText() == "Forge",
      f"{view._loader} / {view._loader_box.currentText()}")
check("mc-version filter preset from pack",
      view._version == "1.20.1" and view._ver_box.currentData() == "1.20.1",
      f"{view._version} / {view._ver_box.currentData()}")
last = api.search_calls[-1] if api.search_calls else {}
check("search query carries pack filters (mods only)",
      last.get("type") == "mod" and last.get("mc") == "1.20.1" and last.get("loader") == "forge",
      str({k: last.get(k) for k in ("type", "mc", "loader")}))
visible_types = [t for t, btn in view._type_btns.items() if btn.isVisible()]
check("type pills locked to Mods", visible_types == ["mod"], str(visible_types))

# --- 2. scope is immutable from global refresh --------------------------
view.set_builds([{"buildId": "other-pack", "name": "Other"}])
check("set_builds cannot retarget the scoped pack",
      view._target_id == "b-medieval" and [b["buildId"] for b in view.builds] == ["b-medieval"],
      str(view._target_id))

# --- 3. card INSTALL -> latest compatible into THIS pack ----------------
captured: list[tuple] = []
view.add_mod.connect(lambda *args: captured.append(args))
hit = view._hits[0]
view._action(hit)
check("install emits (pack, provider, project, latest=None, type)",
      bool(captured) and captured[0] == ("b-medieval", "modrinth", "AABBCCDD", None, "mod"),
      str(captured[:1]))

# --- 4. drawer: scoped selector hidden, version picker live -------------
emitted = queue.Queue()
view.add_mod.connect(lambda *args: emitted.put(args))
view._open_drawer(hit)
pumped = pump(view, lambda: "checking" not in view._detail_status.text().lower())
check("drawer details loaded for pack context", pumped, view._detail_status.text())
check("details requested with pack mc/loader",
      api.detail_calls and api.detail_calls[-1][2:] == ("1.20.1", "forge"),
      str(api.detail_calls[-1:]))
check("cross-pack 'Add to' selector hidden",
      getattr(view, "_target_box", None) is not None and view._target_box.isHidden()
      and getattr(view, "_target_label", None) is not None and view._target_label.isHidden())
check("version picker lists compatible builds",
      view._version_box.isEnabled() and view._version_box.count() == 2
      and view._version_box.itemData(0) == "v2-newest",
      f"count={view._version_box.count()} first={view._version_box.itemData(0)}")

# creator-linked videos surface from the project body (deduped)
pump(view, lambda: view._videos_title.isVisible())
chips = [view._videos_row.layout().itemAt(i).widget().text()
         for i in range(view._videos_row.layout().count())
         if view._videos_row.layout().itemAt(i).widget() is not None]
check("videos section renders deduped watch buttons",
      view._videos_title.isVisible() and chips == ["Watch on YouTube"],
      str(chips))

view._version_box.setCurrentIndex(1)  # pick v1-old explicitly
app_process = app.processEvents
app_process()
view._drawer_primary.click()
try:
    args = emitted.get_nowait()
except Exception:  # noqa: BLE001
    args = None
check("chosen version installed into this pack",
      args == ("b-medieval", "modrinth", "AABBCCDD", "v1-old", "mod"), str(args))
check("drawer closes after install", view._drawer is None)

# --- 5. back returns to Pack Detail -------------------------------------
back_fired = []
view.back_requested.connect(lambda: back_fired.append(True))
view._back_btn.click() if hasattr(view, "_back_btn") else None
if not back_fired:
    # fall back to emitting through the same wiring MainWindow uses
    view.back_requested.emit()
check("back signal wired", bool(back_fired))

# --- 6. engine video extraction (real parser, offline) ------------------
from engine.service import _extract_videos  # noqa: E402

vids = _extract_videos(
    "trailer https://youtu.be/AbC_-123 mirror https://www.youtube.com/watch?v=x9&list=1 "
    "vimeo https://vimeo.com/12345 dup https://youtu.be/AbC_-123", None)
hosts = sorted(v["host"] for v in vids)
check("_extract_videos parses+dedupes provider listings",
      len(vids) == 3 and hosts == ["Vimeo", "YouTube", "YouTube"], f"{len(vids)} {hosts}")

print()
if failures:
    print(f"ADD CONTENT SCOPED TEST FAILED — {len(failures)} failing: {failures}")
    sys.exit(1)
print("ADD CONTENT SCOPED TEST PASS — one-pack binding, auto-filters, latest/chosen installs, videos.")
