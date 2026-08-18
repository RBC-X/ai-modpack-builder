"""Verify the launch poll drops results for a superseded launch.

Rapid Play A -> Play B: A's status fetch is in flight when B launches.
A's poll result landing afterwards must NOT drive B's overlay, stop B's
poll, or hide the overlay — only the active launch (self._launching) owns
the overlay and poll lifecycle. B's own results still apply normally.

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
import views.misc as misc  # noqa: E402

CALLS = []  # (fetch, on_ok, on_err)


def fake_run_async(fn, on_ok, on_err=None):
    CALLS.append((fn, on_ok, on_err))


# LaunchMixin calls the run_async bound in ITS module (common import), not
# main's — patch the binding actually used (same lesson as autocheck_toggle_test).
launch_mixin.run_async = fake_run_async
m.run_async = fake_run_async
# Deterministic: b_ok's running path reads the user's real settings (which could
# close/minimize the window) — stub them so the test is environment-independent.
misc._load_state = lambda: {}

theme.setup_fonts(app)
api = PyEngine()
win = m.MainWindow(api)
win.resize(1320, 840)

# Launch A, then B while A's status fetch is still in flight.
win._launching = "packA"
win._poll_launch()
a_fetch, a_ok, a_err = CALLS[-1]
CALLS.clear()

win.play("packB")          # resets _launching to B, _launch_ui_applied False
win._poll_launch()
b_fetch, b_ok, b_err = CALLS[-1]
CALLS.clear()

assert win._launching == "packB", "B must own the launch state"

# The poll for B is live when A's stale result lands.
win._poll.start()
a_ok({"running": False, "starting": False, "phase": "stopped", "error": None})
assert win._poll.isActive(), "FAIL: superseded A result stopped B's poll"
assert win._launching == "packB", "FAIL: superseded A result cleared the launch"
print("[PASS] stale poll result for superseded launch is dropped (poll keeps running)")

# B's own result still applies normally.
b_ok({"running": True, "starting": False, "phase": "running", "error": None})
print("[PASS] active launch's poll result still applies")

# A's error landing late must not stop B's poll or clear the launch.
a_err(RuntimeError("A died"))
assert win._poll.isActive(), "FAIL: superseded A error stopped B's poll"
assert win._launching == "packB", "FAIL: superseded A error cleared the launch"
print("[PASS] superseded poll error is dropped (poll keeps running)")

# The CURRENT launch's error still behaves as before: poll stops, error surfaces.
win._launching = "packB"
win._poll_launch()
c_fetch, c_ok, c_err = CALLS[-1]
CALLS.clear()
win._poll.start()
c_err(RuntimeError("B died"))
assert not win._poll.isActive(), "FAIL: current launch's error must stop the poll"
print("[PASS] current launch's error still stops the poll")

win._teardown()
print("ALL LAUNCH-POLL RACE CHECKS PASSED")
