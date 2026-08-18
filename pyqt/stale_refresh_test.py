"""Verify refresh_builds never regresses to stale async results.

refresh_builds fires from 20+ sites (the 20 s timer, bootstrap, build
completion, launch/repair mixins). Fetches can overlap. Invariant under
test: the library's final displayed state is always the NEWEST successful
result, and an older in-flight fetch landing after a newer result has
applied must be dropped — while a failed newer fetch must NOT swallow an
older successful result.

Drives the real MainWindow with a captured run_async so overlapping
fetches are resolved in each adversarial order.

    pyqt/.venv/Scripts/python pyqt/stale_refresh_test.py
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

CALLS = []  # (fetch, on_ok, on_err) per run_async invocation
TOASTS = []


def fake_run_async(fn, on_ok, on_err=None):
    CALLS.append((fn, on_ok, on_err))


m.run_async = fake_run_async

theme.setup_fonts(app)
api = PyEngine()
win = m.MainWindow(api)
win.resize(1320, 840)
win.toast = lambda msg, ms=0: TOASTS.append(msg)

# --- Case 1: older result lands AFTER a newer result applied -> dropped ---
win.refresh_builds()          # gen N   (slow, older)
win.refresh_builds()          # gen N+1 (fast, newer)
_, older_ok, older_err = CALLS[-2]
_, newer_ok, _ = CALLS[-1]

older = [{"buildId": "older", "name": "Older Pack", "modCount": 1}]
newer = [{"buildId": "newer", "name": "Newer Pack", "modCount": 1}]

newer_ok((newer, {}))
assert win.builds == newer, "FAIL: newest result did not apply"
print("[PASS] newest result applies")

older_ok((older, {}))
assert win.builds == newer, "FAIL: older result overwrote a newer applied result"
print("[PASS] older result landing after a newer applied result is dropped")

# A superseded error must not toast.
older_err(RuntimeError("superseded"))
assert TOASTS == [], f"FAIL: superseded error toasted: {TOASTS}"
print("[PASS] superseded fetch error is not surfaced")

# --- Case 2: a newer fetch FAILS but an older successful one is in flight ---
win.refresh_builds()          # gen M   (slow, in flight)
win.refresh_builds()          # gen M+1 (fails)
_, slow_ok, _ = CALLS[-2]
_, _, fast_err = CALLS[-1]

slow = [{"buildId": "slow", "name": "Slow Pack", "modCount": 1}]

fast_err(RuntimeError("engine hiccup"))
assert len(TOASTS) == 1, f"FAIL: latest invocation's error must toast, got {TOASTS}"
print("[PASS] the failing NEWEST fetch still surfaces its error")

slow_ok((slow, {}))
assert win.builds == slow, "FAIL: failed newer fetch swallowed an older successful result"
print("[PASS] failed newer fetch does not swallow an older successful result")

win._teardown()
print("ALL STALE-REFRESH CHECKS PASSED")
