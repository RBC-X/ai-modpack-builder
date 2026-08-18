"""Verify refresh_builds drops stale async results.

refresh_builds fires from 20+ sites (the 20 s timer, bootstrap, build
completion, launch/repair mixins). Two fetches can overlap; without a
generation guard a SLOW earlier fetch landing after a NEWER one would
overwrite fresh library state with stale data until the next tick.

This drives the real MainWindow with a captured run_async so the two
overlapping fetches are resolved in the exact adversarial order: stale
result lands last and must be ignored.

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


def fake_run_async(fn, on_ok, on_err=None):
    CALLS.append((fn, on_ok, on_err))


m.run_async = fake_run_async

theme.setup_fonts(app)
api = PyEngine()
win = m.MainWindow(api)
win.resize(1320, 840)

# Construction itself fires refreshes (bootstrap -> health check -> refresh).
# Fire two more overlapping refreshes; the LAST captured one is the newest gen.
win.refresh_builds()
win.refresh_builds()
assert len(CALLS) >= 3, f"expected at least 3 captured refreshes, got {len(CALLS)}"

_, stale_ok, _ = CALLS[-2]  # the SLOWER, older fetch
_, fresh_ok, _ = CALLS[-1]  # the newer fetch

stale = [{"buildId": "stale", "name": "Stale Pack", "modCount": 1}]
fresh = [{"buildId": "fresh", "name": "Fresh Pack", "modCount": 1}]

# The stale result must land LAST (the race) and be dropped entirely.
stale_ok((stale, {}))
assert win.builds != stale, "FAIL: stale refresh overwrote newer state"
print("[PASS] stale refresh result is dropped (out-of-order landing ignored)")

# The newest result still applies normally.
fresh_ok((fresh, {}))
assert win.builds == fresh, "FAIL: newest refresh result did not apply"
print("[PASS] newest refresh result applies")

# A stale result landing after the fresh one must NOT regress the library.
stale_ok((stale, {}))
assert win.builds == fresh, "FAIL: stale result regressed the library after fresh apply"
print("[PASS] stale result after fresh apply is ignored")

# And an error from a superseded fetch must not toast (no user-visible noise).
win.toast = lambda msg, ms=0: (_ for _ in ()).throw(AssertionError(f"toast fired: {msg}"))
_, _ok2, stale_err = CALLS[-2]
stale_err(RuntimeError("superseded failure"))
print("[PASS] superseded fetch error is not surfaced")

win._teardown()
print("ALL STALE-REFRESH CHECKS PASSED")
