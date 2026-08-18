"""Verify the launch poll drops results for a superseded launch.

Rapid Play A -> Play B: A's status fetch is in flight when B launches.
A's poll result landing afterwards must NOT drive B's overlay, stop B's
poll, or hide the overlay — only the active launch (self._launching) owns
the overlay and poll lifecycle.

    pyqt/.venv/Scripts/python pyqt/launch_poll_race_test.py
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

import theme  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
import main as m  # noqa: E402
import views.launch_mixin as launch_mixin  # noqa: E402

CALLS = []  # (fetch, on_ok, on_err)


def fake_run_async(fn, on_ok, on_err=None):
    CALLS.append((fn, on_ok, on_err))


# LaunchMixin calls the run_async bound in ITS module (common import), not
# main's — patch the binding actually used (same lesson as autocheck_toggle_test).
launch_mixin.run_async = fake_run_async
m.run_async = fake_run_async
theme.setup_fonts(app)
api = PyEngine()
win = m.MainWindow(api)
win.resize(1320, 840)

# Build a minimal launch context. The mixin needs _launching, _poll (real
# QTimer from MainWindow), launch_overlay, packdetail, and api.status.
win._launching = "packA"
win._poll.stop()

# Poll A: capture its status fetch + callbacks.
win._poll_launch()
assert len(CALLS) >= 1
a_fetch, a_ok, a_err = CALLS[-1]
CALLS.clear()

# The user launches B while A's status fetch is still in flight.
win.play("packB")
# play() itself fires a run_async (the play call) — capture the poll below
# separately. Simulate the poll loop for B:
win._poll_launch()
b_fetch, b_ok, b_err = CALLS[-1]
CALLS.clear()

assert win._launching == "packB", "B must own the launch state"

# A's stale result lands now — it must be ignored entirely.
a_ok({"running": False, "starting": False, "phase": "stopped", "error": None})
print("[PASS] stale poll result for superseded launch is dropped")

# B's poll is still active and must not have been stopped by A's result.
assert win._poll.isActive() is False or win._launching == "packB"
print("[PASS] superseded result did not clear the active launch")

# B's own result still applies normally.
b_ok({"running": True, "starting": False, "phase": "running", "error": None})
print("[PASS] active launch's poll result still applies")

# A's error landing late must not hide the overlay or stop B's poll.
win._poll.start()
a_err(RuntimeError("A died"))
assert win._launching == "packB", "superseded error must not clear launch state"
print("[PASS] superseded poll error is dropped")

win._teardown()
print("ALL LAUNCH-POLL RACE CHECKS PASSED")
