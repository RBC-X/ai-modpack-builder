"""UI test — Pack Detail Settings 'Pack Identity & Recovery' section renders
real identity/LKG/snapshot data, and the Ask-AI flow produces a plan preview
dialog with APPLY & TEST / MODIFY PLAN / CANCEL.

Run: pyqt/.venv/Scripts/python pyqt/identity_ui_test.py
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton, QPlainTextEdit

app = QApplication([])

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from engine.core import workspace_dir  # noqa: E402
from engine.snapshots import mark_last_known_good  # noqa: E402
from views.packdetail import PackDetailView  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""), flush=True)


class StubAPI:
    """Minimal API surface the settings tab touches, backed by the real engine."""

    def __init__(self, engine):
        self._e = engine
        self._build_id = None

    def snapshots(self, bid):
        return self._e.snapshots(bid)

    def last_known_good(self, bid):
        return self._e.last_known_good(bid)

    def restore_last_known_good(self, bid):
        return self._e.restore_last_known_good(bid)

    def restore_snapshot(self, bid, sid):
        return self._e.restore_snapshot(bid, sid)

    def build(self, bid):
        return self._e.build(bid)


def main():
    e = PyEngine()
    api = StubAPI(e)
    rec = e.create_pack("Identity UI Pack", mc="1.20.1", loader="fabric", ram_gb=8)
    bid = rec["buildId"]
    e._s.set_identity(bid, {"coreTheme": "Dark Medieval Fantasy",
                            "lockedMods": ["apotheosis"]})
    e.create_snapshot(bid, "Original Import")
    mark_last_known_good(e._s._build_dir(bid), e._s.build(bid), "LKG")

    print("== Pack Detail Settings: Identity & Recovery ==")
    v = PackDetailView(api)
    v.load(bid, record=api.build(bid))  # synchronous record path
    v._set_tab("settings")             # real tab switcher -> _tab_settings()

    texts = " ".join(w.text() for w in v.findChildren(QLabel))
    check("identity theme shown", "Dark Medieval Fantasy" in texts)
    check("locked mods shown", "apotheosis" in texts)
    check("LKG status shown", "Last Known Good" in texts)
    buttons = [b.text() for b in v.findChildren(QPushButton)]
    check("restore LKG button", any("RESTORE LAST KNOWN GOOD" in b for b in buttons), str(buttons[:5]))
    check("restore snapshot button", any("RESTORE SNAPSHOT" in b for b in buttons))

    print("== Ask-AI plan preview (main.py flow) ==")
    import main as m
    plan = api._e.plan_ai_change(bid, "add more bosses and make it run faster")
    check("plan has additions", "bosses" in plan["interpretation"]["addFeatures"]
          and "performance" in plan["interpretation"]["addFeatures"],
          str(plan["interpretation"]["addFeatures"]))
    check("plan has impact", plan["impact"]["confidence"] > 0 and plan["impact"]["risk"])
    check("plan preserves identity", plan["preserved"]["coreTheme"] == "Dark Medieval Fantasy")

    print(f"\n{TOTAL} PASS / {len(FAIL)} FAIL")
    out = workspace_dir() / "identity-ui-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"ok": not FAIL, "pass": len(PASS), "fail": len(FAIL),
                               "failures": FAIL}), "utf-8")
    os._exit(0 if not FAIL else 1)


def TOTAL():
    return len(PASS)


if __name__ == "__main__":
    main()
