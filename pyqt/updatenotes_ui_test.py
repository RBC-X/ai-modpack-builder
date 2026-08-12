"""Headless UI test for the release-notes-before-update surface:

1. Settings → Updates, with a mocked feed reporting v1.0.1 available, shows
   the DOWNLOAD & INSTALL button after the check completes.
2. Clicking it opens a release-notes dialog containing the full feed notes.
3. Clicking the dialog's DOWNLOAD & INSTALL launches the update with the exact
   feed URL; clicking Cancel does not.

Usage: python pyqt/updatenotes_ui_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import PyQt6  # noqa: F401
from PyQt6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
import views.misc as misc  # noqa: E402

NOTES = ("## 1.0.1\n\n- Fixed the Project Atmosphere crash on startup\n"
         "- Faster mod installs\n- New Release Notes dialog before updating")
URL = "https://example.com/update.json"

report: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


app = QApplication(sys.argv)
theme.setup_fonts(app)

view = misc.SettingsView(PyEngine())
view.resize(1200, 800)
view.show()
app.processEvents()
view._set_sub("updates")
app.processEvents()
check("updates panel rendered",
      hasattr(view, "_update_url_box") and hasattr(view, "_update_status"))

# ---- drive the real check flow with a mocked feed
real_run_update = misc.updater.run_update


def fake_run_update(url, apply=False, dest_dir=None, extra_dir=None):
    return {"ok": True, "available": True, "current": "1.0.0", "latest": "1.0.1",
            "notes": NOTES, "installerUrl": URL, "installerSha256": "abc",
            "applied": apply}


misc.updater.run_update = fake_run_update
view._update_url_box.setText(URL)

view._do_update_check()
btn = None
for _ in range(250):  # worker thread -> main thread callback
    app.processEvents()
    btns = [b for b in view._panel.findChildren(QPushButton)
            if "DOWNLOAD & INSTALL" in b.text()]
    if btns:
        btn = btns[0]
        break
    time.sleep(0.02)
check("download button shown after check", btn is not None)

# ---- confirm path: dialog shows full notes, clicking install applies
class FakeDialog(QDialog):
    captured = None

    def exec(self):  # noqa: N802
        FakeDialog.captured = self
        return 1


real_qdialog = misc.QDialog
misc.QDialog = FakeDialog
applied: list = []

# Plain function stored on the instance is NOT a bound method — accept only
# the url argument, exactly how _confirm_update calls it.
view._apply_update = lambda url: applied.append(url)  # type: ignore[method-assign]

FakeDialog.captured = None
view._confirm_update()
d = FakeDialog.captured
check("release-notes dialog opened", d is not None)
texts = [w.toPlainText() for w in d.findChildren(QPlainTextEdit)] if d else []
check("full release notes shown in dialog", any(NOTES in t for t in texts),
      f"box chars={max((len(t) for t in texts), default=0)}")
dlg_go = [b for b in d.findChildren(QPushButton) if "DOWNLOAD & INSTALL" in b.text()] if d else []
check("dialog has install button", len(dlg_go) == 1)
if dlg_go:
    dlg_go[0].click()  # real signal path -> apply()
check("apply launched with exact url on confirm", applied == [URL], f"applied={applied}")

# ---- cancel path: clicking Cancel never applies
applied.clear()
FakeDialog.captured = None
view._confirm_update()
d2 = FakeDialog.captured
dlg_cancel = [b for b in d2.findChildren(QPushButton) if b.text().strip() == "Cancel"] if d2 else []
check("dialog has cancel button", len(dlg_cancel) == 1)
if dlg_cancel:
    dlg_cancel[0].click()  # -> reject(), install never runs
check("no apply when dialog canceled", applied == [], f"applied={applied}")

misc.QDialog = real_qdialog
misc.updater.run_update = real_run_update  # restore module state

overall = all(r["status"] == "PASS" for r in report)
out = Path(__file__).resolve().parent.parent / "workspace" / "updatenotes-ui-result.json"
out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
print(f"\n[ui] OVERALL: {'PASS' if overall else 'FAIL'} — saved {out}")
# Exit without Qt/Python teardown (same fail-fast landmine as the frozen
# selftest): the result is already flushed to disk.
os._exit(0 if overall else 1)
