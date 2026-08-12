"""Discover bounded retry test — a 200-empty-result blip must self-recover.

Drives the real DiscoverView with a stub API whose search returns an empty
hit list (no error) on the first call and real hits afterwards, and asserts
the view eventually renders results instead of an empty grid — proving the
in-view bounded retry with backoff recovers transient provider blips.

Also asserts a persistently empty result stays empty (bounded retries give
up) so a genuinely empty search is not papered over forever.

Run: pyqt/.venv/Scripts/python pyqt/discover_retry_test.py
"""
from __future__ import annotations

import os
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication(sys.argv)

import theme  # noqa: E402
from views.discover import DiscoverView, RETRY_EMPTY_ATTEMPTS  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


class BlipAPI:
    """Search returns empty (no error) for the first N calls, then real hits."""

    def __init__(self, blips: int = 1):
        self._blips = blips
        self._calls = 0
        self.results = []

    def search(self, **kwargs):
        self._calls += 1
        if self._calls <= self._blips:
            return {"hits": [], "error": None, "page_size": 24, "total": 0,
                    "more": False, "browse": True, "sources": [
                        {"provider": "modrinth", "ok": True, "count": 0,
                         "total": 0, "available": True, "error": None}]}
        self.results.append(self._calls)
        return {"hits": [{"slug": "recovered-mod", "projectId": f"rec-{self._calls}",
                          "iconUrl": "https://cdn.example/x.png",
                          "provider": "modrinth", "projectType": "mod"}],
                "error": None, "page_size": 24, "total": 1, "more": False,
                "browse": True, "sources": [
                    {"provider": "modrinth", "ok": True, "count": 1,
                     "total": 1, "available": True, "error": None}]}


def drive(api, wait_secs: float = 8.0):
    view = DiscoverView(api)
    view._search.setText("")
    view._search_now()
    saw_retry_notice = False
    t0 = time.time()
    while time.time() - t0 < wait_secs:
        app.processEvents()
        if "retrying" in (view._status.text() or "").lower():
            saw_retry_notice = True
        if view._hits:
            break
        time.sleep(0.05)
    view._saw_retry_notice = saw_retry_notice
    return view


# --- 1. One transient blip: view must recover to real hits ---
api = BlipAPI(blips=1)
view = drive(api)
check("one blip recovers to real hits", bool(view._hits),
      f"{len(view._hits)} hits after {api._calls} search calls")
check("recovery used the retry path", api._calls >= 2 and api._calls <= RETRY_EMPTY_ATTEMPTS,
      f"{api._calls} calls (bounded at {RETRY_EMPTY_ATTEMPTS})")
check("recovered hit is the real one",
      view._hits[0].get("slug") == "recovered-mod", str(view._hits[0].get("slug")))
check("status line announces the retry", view._saw_retry_notice,
      repr(view._status.text()))

# --- 2. Persistent empty: bounded retries must give up, not loop forever ---
api = BlipAPI(blips=10 ** 6)
view = drive(api, wait_secs=6.0)
check("persistent empty stays empty", not view._hits,
      f"{len(view._hits)} hits")
check("retries are bounded", api._calls <= RETRY_EMPTY_ATTEMPTS,
      f"{api._calls} calls (cap {RETRY_EMPTY_ATTEMPTS})")

print()
if failures:
    print("FAILED:", failures)
    sys.exit(1)
print(f"PASS — discover retry recovers blips and stays bounded ({RETRY_EMPTY_ATTEMPTS} max attempts)")
