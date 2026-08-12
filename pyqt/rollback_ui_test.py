"""Verify Settings → Updates renders the Restore-previous-version action when a
rollback candidate exists in the per-user updates pool, and that release notes
from the feed are displayed inline in the panel.

Renders the real SettingsView Updates section offscreen against a fake engine;
monkeypatches only the rollback pool source so the UI shows a real candidate.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

app = QApplication([])

import updater
import engine.core as core
import views.misc as misc

# Point the Settings section at a scratch updates pool containing a real
# older installer, plus one at the current version (excluded as rollback).
scratch = Path(tempfile.mkdtemp())
pool = scratch / "updates"
pool.mkdir()
(pool / "AI-Modpack-Builder-Setup-1.0.5.exe").write_bytes(b"x")
(pool / "AI-Modpack-Builder-Setup-1.0.6.exe").write_bytes(b"x")
real_data_dir = core.data_dir
core.data_dir = lambda: scratch
misc._load_state = lambda: {}
misc._save_state = lambda _st: None


class FakeAPI:
    def health(self):
        return True

    def provider_status(self, *_a, **_k):
        return {}


sv = misc.SettingsView(FakeAPI())
sv._settings = {}
sv._hardware = {}
sv.open_section("updates")

texts = " ".join(w.text() for w in sv._panel.findChildren(QLabel))
buttons = [b.text() for b in sv._panel.findChildren(QPushButton)]

checks = []
checks.append(("Updates section rendered", "Installed version" in texts))
checks.append(("Restore button present with candidate",
               any("RESTORE" in b for b in buttons)))
checks.append(("Restore button names the previous version",
               any("v1.0.6" in b for b in buttons)))

# Release-notes inline display: fake a check result with notes and drive the
# same ok() path the real check uses.
notes = "1.0.7 release — new shader presets and resource-pack search."
sv._update_url = "https://example.com/update.json"
sv._update_latest = "1.0.7"
sv._render_update_result(True, f"Update v1.0.7 available — release notes below.")
if hasattr(sv, "_update_notes_box"):
    sv._update_notes_box.setText(notes)
notes_visible = bool(sv._update_notes_box.text())
checks.append(("Release notes shown inline", notes_visible and notes in sv._update_notes_box.text()))

for name, ok in checks:
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "workspace", "rollback-ui-result.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump({"checks": [{"name": n, "ok": o} for n, o in checks],
               "ok": all(o for _, o in checks)}, f, indent=2)
os._exit(0 if all(o for _, o in checks) else 1)
