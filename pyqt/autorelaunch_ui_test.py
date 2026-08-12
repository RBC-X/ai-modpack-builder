"""Headless UI test for the auto-relaunch surface:

1. Pack Detail → Settings shows the "Auto-relaunch on silent close" checkbox
   reflecting the pack's real record state.
2. Toggling it calls the engine's set_auto_relaunch and the record changes.
3. The launch overlay renders the "relaunching" mode with the recovery log
   (closeContext reason + log tail) when the engine reports that phase.

Usage: python pyqt/autorelaunch_ui_test.py b-lite-ef38acfd
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import PyQt6  # noqa: F401  (ensure importable before QApplication)
from PyQt6.QtWidgets import QApplication, QCheckBox

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from main import MainWindow  # noqa: E402

PACK = sys.argv[1] if len(sys.argv) > 1 else "b-lite-ef38acfd"
report: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    report.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


app = QApplication(sys.argv)
theme.setup_fonts(app)

eng = PyEngine()
win = MainWindow(eng)
win.resize(1320, 840)
win.show()
app.processEvents()

# ---- open Pack Detail on the pack (record loads async), then Settings tab
win.open_detail(PACK)
pd = win.packdetail
for _ in range(200):
    app.processEvents()
    if pd.record is not None:
        break
    import time
    time.sleep(0.02)
check("pack detail record loaded", pd.record is not None, f"build={PACK}")
pd._set_tab("settings")
app.processEvents()

chk = getattr(pd, "_relaunch_chk", None)
check("settings tab has auto-relaunch checkbox", isinstance(chk, QCheckBox))

rec_path = Path(__file__).resolve().parent.parent / "workspace" / "builds" / PACK / "build.json"
rec_before = json.loads(rec_path.read_text("utf-8"))
before = bool((rec_before.get("settings") or {}).get("autoRelaunch"))
check("checkbox reflects record state", chk is not None and chk.isChecked() == before,
      f"record={before} checkbox={chk.isChecked() if chk else None}")

# ---- toggle it and confirm the engine record flips
target = not before
if chk is not None:
    chk.setChecked(target)
app.processEvents()
rec_after = json.loads(rec_path.read_text("utf-8"))
after = bool((rec_after.get("settings") or {}).get("autoRelaunch"))
check("toggle wired to engine set_auto_relaunch", after == target, f"record now={after}")

# restore the original value so the pack state is untouched
if chk is not None and chk.isChecked() != before:
    chk.setChecked(before)
    app.processEvents()
rec_restored = json.loads(rec_path.read_text("utf-8"))
check("state restored after test",
      bool((rec_restored.get("settings") or {}).get("autoRelaunch")) == before)

# ---- launch overlay relaunching mode + recovery log
ov = win.launch_overlay
ov.apply_status({
    "phase": "relaunching", "progress": 54,
    "stage": "Silent close detected — relaunching with 3072 MB RAM",
    "closeContext": {
        "stoppedByUser": False, "code": 1,
        "reason": "Silent death after main menu — auto-relaunch scheduled",
        "logTail": ["[02:25:41] [Render thread/INFO]: Flushed changes to Minecraft configuration",
                    "[02:25:45] [main/INFO]: Stopping!"],
    },
})
app.processEvents()
check("overlay enters relaunching mode", ov._mode == "relaunching" and ov.isVisible())
check("recovery stage shown", "relaunching with 3072 MB RAM" in (ov._status.get("stage") or ""))
from PyQt6.QtWidgets import QPlainTextEdit
box_text = ""
for w in ov.findChildren(QPlainTextEdit):
    box_text = w.toPlainText()
check("recovery log rendered (reason + tail)",
      "Silent death after main menu" in box_text and "Stopping!" in box_text,
      f"box={box_text[:80]!r}...")
ov.hide()

overall = all(r["status"] == "PASS" for r in report)
out = Path(__file__).resolve().parent.parent / "workspace" / "autorelaunch-ui-result.json"
out.write_text(json.dumps({"phases": report, "overall": "PASS" if overall else "FAIL"}, indent=2), "utf-8")
print(f"\n[ui] OVERALL: {'PASS' if overall else 'FAIL'} — saved {out}")
sys.exit(0 if overall else 1)
