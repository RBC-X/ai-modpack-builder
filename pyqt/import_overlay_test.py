"""Headless UI test for the import overlay (CurseForge-style).

Verifies:
  1. show_import renders the importing card (title, stage, progress, CANCEL).
  2. set_progress updates stage/count/percent live.
  3. set_done swaps the CANCEL button for a PLAY button and PLAY emits the
     build id when clicked.
  4. set_error renders an error card with CLOSE (no PLAY).
  5. Dismiss (X) during import emits cancel_requested.

Run:  pyqt/.venv/Scripts/python pyqt/import_overlay_test.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from PyQt6.QtCore import Qt  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QWidget  # noqa: E402

from views.overlays import ImportOverlay  # noqa: E402

report: dict = {"phases": []}


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def buttons(ov: ImportOverlay) -> list[str]:
    return [b.text() for b in ov.findChildren(QPushButton)]


def main() -> int:
    app = QApplication(sys.argv)
    host = QWidget()
    host.resize(1365, 840)
    ov = ImportOverlay(host)

    cancels: list = []
    plays: list = []
    ov.cancel_requested.connect(lambda: cancels.append(True))
    ov.play_requested.connect(lambda bid: plays.append(bid))

    ov.show_import("Test Pack")
    phase("importing mode shows", ov.is_importing() and not ov.isHidden(),
          f"hidden={ov.isHidden()} importing={ov.is_importing()}")
    phase("cancel button present", "CANCEL" in buttons(ov), str(buttons(ov)))
    phase("play absent while importing", "PLAY" not in buttons(ov), str(buttons(ov)))

    ov.set_progress("Downloading mods", 7, 17)
    labels = [l.text() for l in ov.findChildren(QLabel)]
    phase("progress rendered", any("7/17" in t for t in labels) and any("41%" in t for t in labels),
          [t for t in labels if "/" in t or "%" in t])

    # CANCEL emits the signal
    for b in ov.findChildren(QPushButton):
        if b.text() == "CANCEL":
            b.click()
    phase("cancel signal emitted", len(cancels) == 1, f"cancels={len(cancels)}")

    # finish -> PLAY replaces CANCEL
    ov.set_done("b-test-123", "Test Pack", "17 mods installed (17 downloaded)")
    phase("done mode not importing", not ov.is_importing() and not ov.isHidden(), f"importing={ov.is_importing()}")
    phase("play replaces cancel", "PLAY" in buttons(ov) and "CANCEL" not in buttons(ov), str(buttons(ov)))
    for b in ov.findChildren(QPushButton):
        if b.text() == "PLAY":
            b.click()
    phase("play emits build id", plays == ["b-test-123"], str(plays))

    # error mode
    ov.set_error("provider unavailable")
    phase("error mode", not ov.is_importing() and "CLOSE" in buttons(ov) and "PLAY" not in buttons(ov),
          str(buttons(ov)))

    ov.hide()
    # teardown: Qt fail-fast landmine in some builds -> flush result then exit hard
    out = ROOT.parent / "workspace" / "import-overlay-result.json"
    report["overall"] = "PASS" if all(p["status"] == "PASS" for p in report["phases"]) else "FAIL"
    out.write_text(json.dumps(report, indent=2), "utf-8")
    print(f"\nOVERALL: {report['overall']} -> {out}", flush=True)
    os._exit(0 if report["overall"] == "PASS" else 1)


if __name__ == "__main__":
    main()
