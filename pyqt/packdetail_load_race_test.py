"""Verify Pack Detail load() drops stale results from a superseded pack.

_open_detail -> _reload_detail -> packdetail.load() fires on every pack open
AND on every refresh tick while a pack is open. Two overlapping loads for
DIFFERENT packs can resolve out of order: a slow fetch for the OLDER pack
landing after the newer pack rendered must never overwrite the record or
worlds under the newer header.

Drives the real PackDetailView with a captured run_async so the adversarial
order is resolved deterministically.

    pyqt/.venv/Scripts/python pyqt/packdetail_load_race_test.py
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication([])

import theme  # noqa: E402
import common  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from views.packdetail import PackDetailView  # noqa: E402

CALLS = []  # (fn, on_ok, on_err)


def fake_run_async(fn, on_ok, on_err=None):
    CALLS.append((fn, on_ok, on_err))


# PackDetailView.load does `from common import run_async` INSIDE load(), so
# patching the common module attribute is the binding actually used.
common.run_async = fake_run_async

theme.setup_fonts(app)
engine = PyEngine()
a = engine.create_pack("Pack A", mc="1.20.1", loader="fabric", ram_gb=4)
b = engine.create_pack("Pack B", mc="1.20.1", loader="fabric", ram_gb=4)
bid_a, bid_b = a["buildId"], b["buildId"]

v = PackDetailView(engine)
v.resize(1100, 800)
v.show()

# --- Case 1: full-record fetch path (no record supplied) ---
v.load(bid_a)                       # slow fetch for A
_, a_ok, a_err = CALLS[-1]
CALLS.clear()

v.load(bid_b)                       # fast fetch for B
_, b_ok, b_err = CALLS[-1]
CALLS.clear()

b_ok((engine.build(bid_b), engine.worlds(bid_b)))   # B renders
assert v.build_id == bid_b and (v.record or {}).get("buildId") == bid_b
print("[PASS] newer pack (B) renders")

a_ok((engine.build(bid_a), engine.worlds(bid_a)))   # A's stale result lands LAST
assert v.build_id == bid_b, "FAIL: stale load changed the build_id header"
assert (v.record or {}).get("buildId") == bid_b, \
    "FAIL: stale load overwrote the newer pack's record"
print("[PASS] stale load result for the older pack is dropped")

# A stale ERROR for the older pack must not blank the newer pack's page.
a_err(RuntimeError("A record failed"))
assert (v.record or {}).get("buildId") == bid_b, \
    "FAIL: stale load error overwrote the newer pack's record"
print("[PASS] stale load error is dropped")

# --- Case 2: worlds fetch path (record supplied, worlds async) ---
v.load(bid_a, record=engine.build(bid_a))   # worlds fetch for A
_, a_w_ok, _ = CALLS[-1]
CALLS.clear()

v.load(bid_b, record=engine.build(bid_b))   # worlds fetch for B
_, b_w_ok, _ = CALLS[-1]
CALLS.clear()

b_w_ok(engine.worlds(bid_b))
assert v.build_id == bid_b
print("[PASS] newer pack's worlds apply")

a_w_ok(engine.worlds(bid_a))                # A's stale worlds land LAST
assert v.build_id == bid_b, "FAIL: stale worlds fetch changed the build_id header"
print("[PASS] stale worlds result for the older pack is dropped")

# The CURRENT pack's own result still applies normally after a stale one.
v.load(bid_b, record=engine.build(bid_b))
_, b2_w_ok, _ = CALLS[-1]
CALLS.clear()
b2_w_ok(engine.worlds(bid_b))
assert v.build_id == bid_b
print("[PASS] current pack's worlds still apply after stale drop")

v._stop_log_stream()
print("ALL PACKDETAIL LOAD-RACE CHECKS PASSED")
