"""Render every launcher view to PNG (offscreen) for visual inspection.

    pyqt/.venv/Scripts/python pyqt/screenshot.py

Writes PNGs to pyqt/screenshots/*.png. Runs on the in-process Python engine.
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtCore import QCoreApplication, QEvent, QThreadPool  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel  # noqa: E402

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
os.makedirs(OUT, exist_ok=True)


def wait(win, app, cond, secs=15):
    t0 = time.time()
    while time.time() - t0 < secs:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.05)
    return False


def snap(app, win, name):
    win.resize(1320, 840)
    # Let deferred layouts, async image callbacks, and queued API results settle
    # before capturing. Three immediate processEvents calls were too short on
    # Windows and could record a half-laid-out page.
    for _ in range(8):
        app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        time.sleep(0.05)
    path = os.path.join(OUT, f"{name}.png")
    win.grab().save(path)
    print(f"  saved {path}")
    return path


app = QApplication(sys.argv)
theme.setup_fonts(app)
api = PyEngine()
win = MainWindow(api)
win.show()
wait(win, app, lambda: bool(win.builds))

print("rendering…")
snap(app, win, "01-home")

win._set_nav("library")
snap(app, win, "02-library")

win._open_detail(win.builds[0]["buildId"])
wait(win, app, lambda: bool(win.packdetail.record))
snap(app, win, "03-pack-overview")
win.packdetail._set_tab("content")
snap(app, win, "04-pack-content")
win.packdetail._set_tab("logs")
snap(app, win, "05-pack-logs")
win.packdetail._set_tab("settings")
snap(app, win, "06-pack-settings")

win._set_nav("discover")
wait(win, app, lambda: bool(win.discover._hits))
snap(app, win, "07-discover")
detail_hit = next((hit for hit in win.discover._hits if "iris" in str(hit.get("slug") or "").lower()),
                  win.discover._hits[0])
win.discover._open_drawer(detail_hit)
wait(win, app, lambda: hasattr(win.discover, "_detail_status") and
     "Checking" not in win.discover._detail_status.text(), secs=8)
snap(app, win, "07b-discover-details")
win.discover._close_drawer()

win._set_nav("ai-builder")
wait(win, app, lambda: "Detected" in win.aibuilder._hw_label.text())
snap(app, win, "08-ai-builder")

win._set_nav("downloads")
wait(win, app, lambda: not win.downloads._status.text().startswith("Loading"), secs=8)
snap(app, win, "09-downloads")

win._set_nav("activity")
wait(win, app, lambda: win.activity._body_lay.count() > 0 and
     "Loading" not in " ".join(w.text() for w in win.activity._body.findChildren(QLabel)), secs=5)
snap(app, win, "10-activity")

win._set_nav("settings")
snap(app, win, "11-settings")
win.settings.open_section("providers")
snap(app, win, "11b-provider-settings")
win.settings.open_section("account")
snap(app, win, "11c-account-settings")
# Remaining overlay tabs — every section of the new top-nav surface.
for section, shot in [("appearance", "11e-appearance-settings"),
                      ("minecraft", "11f-minecraft-settings"),
                      ("java", "11g-java-settings"),
                      ("ai", "11h-ai-settings"),
                      ("cloud", "11i-cloud-settings")]:
    win.settings.open_section(section)
    snap(app, win, shot)
win.settings.open_section("account")
win.account_modal.show()
for _ in range(8):
    app.processEvents()
    time.sleep(0.05)
account_path = os.path.join(OUT, "11d-account-dialog.png")
win.account_modal.grab().save(account_path)
print(f"  saved {account_path}")
win.account_modal.close()
# The settings overlay floats above the page — drop it before the
# launch-overlay captures so those render on the plain page again.
win.settings.hide()

# Launch overlay with the real backend status fields (no game launched).
win.launch_overlay.show_launch(win.builds[0].get("name") or "pack")
win.launch_overlay.apply_status({"phase": "preparing", "progress": 42, "stage": "Loading 64 mods & mixin hooks...", "modsLoaded": 27, "modsTotal": 64})
win.launch_overlay._reposition(1320, 840)
snap(app, win, "12-launch-overlay")

# Release-notes update toast (1.0.11): title + rendered markdown notes + the
# Review & install action users see before an update applies.
win.launch_overlay.hide()
win.toast_update(
    "1.0.11",
    "## What's new in 1.0.11\n\n"
    "- Release notes now render in the update toast before you install\n"
    "- Settings → Updates shows the full changelog as markdown\n"
    "- A stale launch record can no longer keep a pack running after a crash",
    on_action=lambda: None)
for _ in range(8):
    app.processEvents()
    time.sleep(0.05)
snap(app, win, "13-update-toast")
win._update_toast.hide()

# Settings -> Updates panel with the feed's real release notes rendered
# (markdown) and the install action visible before anything is applied.
import updater  # noqa: E402
real_run_update = updater.run_update


def fake_run_update(url, apply=False, dest_dir=None, extra_dir=None):
    return {"ok": True, "available": True, "current": "1.0.10", "latest": "1.0.11",
            "notes": "## What's new in 1.0.11\n\n"
                      "- Release notes now render in the update toast before you install\n"
                      "- Settings → Updates shows the full changelog as markdown\n"
                      "- A stale launch record can no longer keep a pack running after a crash\n"
                      "- The library refreshes instantly when you return to it",
            "installerUrl": "https://example.com/update.json",
            "installerSha256": "abc", "applied": apply}


updater.run_update = fake_run_update
win._set_nav("settings")
win.settings.open_section("updates")
win.settings._update_url_box.setText("https://example.com/update.json")
win.settings._do_update_check()
wait(win, app, lambda: bool(win.settings._update_notes_box.toPlainText()), secs=8)
# Scroll the notes + install action fully into view so the capture shows
# the feed's release notes and the download button.
vsb = win.settings._panel_scroll.verticalScrollBar()
vsb.setValue(vsb.maximum())
for _ in range(4):
    app.processEvents()
    time.sleep(0.05)
snap(app, win, "14-settings-updates")
updater.run_update = real_run_update

print("done — launcher screenshots refreshed in pyqt/screenshots/")
win.packdetail._stop_log_stream()
win.close()
app.processEvents()
QThreadPool.globalInstance().waitForDone(8000)
# A stopped SSE socket can remain blocked inside Qt's global worker pool on
# some Windows runs. All files are flushed at this point, so end the standalone
# visual-QA process deterministically instead of leaving a hidden Python task.
sys.stdout.flush()
os._exit(0)
