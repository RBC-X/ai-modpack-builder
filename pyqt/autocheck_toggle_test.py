"""Verify the startup auto-update check honors the Settings->Updates toggle.

Drives the real `MainWindow._auto_check_update` with a synchronous run_async
stub so the decision logic is tested deterministically (no threads, no toast
delivery timing). Exits via os._exit to avoid the known Qt teardown fail-fast.
"""
import json
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication

app = QApplication([])

import updater
import views.misc as misc
import main as m

CALLS = []


def fake_check(url, timeout=20):
    CALLS.append(url)
    return {"ok": True, "available": False, "current": "1.0.1", "latest": "1.0.1"}


updater.check = fake_check
updater.should_auto_check = lambda dd, hours=24, stamp=None: True
updater.stamp_check = lambda dd, stamp=None: None
m.run_async = lambda fn, on_ok, on_err=None: on_ok(fn())


class Fake:
    def __init__(self):
        self.toasts = []

    def toast(self, msg, ms=0):
        self.toasts.append(msg)


bound = m.MainWindow._auto_check_update.__get__(Fake())


def set_state(auto, url):
    misc._load_state = lambda: {"autoCheckUpdates": auto, "updateUrl": url}


results = []

CALLS.clear()
set_state(False, "https://example.com/update.json")
bound()
results.append(("toggle OFF -> no check", len(CALLS) == 0))

CALLS.clear()
set_state(True, "https://example.com/update.json")
bound()
results.append(("toggle ON + URL -> check fires",
                len(CALLS) == 1 and CALLS[0] == "https://example.com/update.json"))

CALLS.clear()
set_state(True, "")
bound()
results.append(("toggle ON, no URL -> default feed used",
                len(CALLS) == 1 and CALLS[0].startswith("https://github.com/RBC-X/ai-modpack-builder")))

CALLS.clear()
misc._load_state = lambda: {"updateUrl": "https://example.com/update.json"}  # default ON
bound()
results.append(("default (key absent) -> check fires", len(CALLS) == 1))

for name, ok in results:
    print(("[PASS] " if ok else "[FAIL] ") + name, flush=True)

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "workspace", "autocheck-toggle-result.json")
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump({"checks": [{"name": n, "ok": o} for n, o in results],
               "ok": all(o for _, o in results)}, f, indent=2)
os._exit(0 if all(o for _, o in results) else 1)
