"""Release-notes update toast verification (headless UI):

1. MainWindow.toast_update renders a rich toast: title, markdown-rendered
   release notes, and a Review & install action; the action fires and hides
   the toast; Later dismisses without action.
2. The auto update check (startup/periodic path) calls toast_update with the
   feed's notes and latest version — release notes are shown before apply.

Usage: python pyqt/update_toast_test.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["AMB_WORKSPACE"] = str(Path(os.path.dirname(os.path.abspath(__file__))).parent / "workspace")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import PyQt6  # noqa: F401
from PyQt6.QtWidgets import QApplication, QPushButton, QTextEdit  # noqa: F401

import theme  # noqa: E402
import updater  # noqa: E402
import views.misc as misc  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

NOTES = ("## 1.0.11\n\n- Release notes now render in the update toast\n"
         "- Settings → Updates shows markdown notes before install")

report: list = []


def _ascii(s: str) -> str:
    return s.encode("ascii", "replace").decode("ascii")


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {_ascii(detail)}" if detail else ""), flush=True)


def pump(app, n: int = 20, dt: float = 0.03) -> None:
    for _ in range(n):
        app.processEvents()
        time.sleep(dt)


app = QApplication(sys.argv)
theme.setup_fonts(app)
win = MainWindow(PyEngine())
win.resize(1100, 760)
win.show()
pump(app)

# ---- 1. toast_update renders and its action works -----------------------
fired: list = []
win.toast_update("1.0.11", NOTES, on_action=lambda: fired.append("review"))
pump(app)
t = win._update_toast
check("update toast visible", t.isVisible())
check("toast title shows version", "1.0.11" in win._update_toast_title.text(),
      win._update_toast_title.text())
notes_text = win._update_toast_notes.toPlainText()
# Markdown renders "- " bullets as "• " — match on the phrase, not the raw prefix.
check("toast renders release notes (markdown source kept)",
      "Release notes now render" in notes_text, f"chars={len(notes_text)}")
check("toast notes are a markdown-capable QTextEdit",
      isinstance(win._update_toast_notes, QTextEdit))
btn = [b for b in t.findChildren(QPushButton) if "REVIEW & INSTALL" in b.text().upper()]
check("toast has Review & install action", len(btn) == 1)
if btn:
    btn[0].click()
    pump(app)
    check("Review action fired and toast hidden", fired == ["review"] and not t.isVisible(),
          f"fired={fired} visible={t.isVisible()}")

# Later dismisses without action
fired.clear()
win.toast_update("1.0.11", NOTES, on_action=lambda: fired.append("review"))
pump(app)
later = [b for b in t.findChildren(QPushButton) if b.text().strip() == "Later"]
if later:
    later[0].click()
    pump(app)
check("Later dismisses without action", fired == [] and not t.isVisible(),
      f"fired={fired} visible={t.isVisible()}")

# ---- 2. auto-check wires the feed notes into the toast ------------------
calls: list = []
win.toast_update = lambda latest, notes, on_action=None: calls.append((latest, notes))  # type: ignore[method-assign]
real_check = updater.check
real_throttle = updater.should_auto_check
real_stamp = updater.stamp_check
real_load_state = misc._load_state
misc._load_state = lambda: {"autoCheckUpdates": True,
                             "updateUrl": "https://example.com/update.json"}


def fake_check(url, timeout=20):
    return {"ok": True, "current": "1.0.10", "latest": "1.0.11", "available": True,
            "notes": NOTES, "feedUrl": url, "installerUrl": "https://example.com/a.exe",
            "installerSha256": "a" * 64}


updater.check = fake_check
updater.should_auto_check = lambda *a, **k: True
updater.stamp_check = lambda *a, **k: None
try:
    win._auto_check_update(stamp="toast-test", hours=0)
    for _ in range(300):
        pump(app, 1, 0.02)
        if calls:
            break
    check("auto-check feeds release notes into the toast", calls and calls[0][0] == "1.0.11"
          and NOTES in (calls[0][1] or ""), f"calls={calls}")
finally:
    updater.check = real_check
    updater.should_auto_check = real_throttle
    updater.stamp_check = real_stamp
    misc._load_state = real_load_state

overall = all(r["status"] == "PASS" for r in report)
out = Path(__file__).resolve().parent.parent / "workspace" / "update-toast-result.json"
out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
print(f"\n[toast] OVERALL: {'PASS' if overall else 'FAIL'} — saved {out}")
sys.stdout.flush()
os._exit(0 if overall else 1)
