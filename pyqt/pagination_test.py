"""Discover pagination test — real provider offsets + the pager UI.

Verifies:
1. The engine search honors offset: page 2 (offset 48) returns a real,
   non-empty hit list whose project IDs differ from page 1.
2. The Discover view renders the pager; Next enables when a full page came
   back, navigates to page 2 (distinct hits), and Prev returns to page 1.

Run: pyqt/.venv/Scripts/python pyqt/pagination_test.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.service import PyEngine  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


eng = PyEngine()

# --- engine offset: page 1 vs page 2 must be real, distinct results ---
r1 = eng.search(q="create", provider="modrinth", type="mod", offset=0)
r2 = eng.search(q="create", provider="modrinth", type="mod", offset=48)
h1 = [h.get("projectId") for h in (r1.get("hits") or [])]
h2 = [h.get("projectId") for h in (r2.get("hits") or [])]
check("page 1 has hits", len(h1) > 0, f"{len(h1)} hits")
check("page 2 has hits", len(h2) > 0, f"{len(h2)} hits")
check("page 2 differs from page 1", bool(h1) and bool(h2) and not set(h1) & set(h2),
      f"overlap: {len(set(h1) & set(h2))}")
check("page 2 count is a real page", len(h2) == len(h1), f"p1={len(h1)} p2={len(h2)}")

# --- real total result counts (Modrinth total_hits) ---
total1 = int(r1.get("total") or 0)
check("engine surfaces a real total count", total1 > len(h1), f"total={total1} page={len(h1)}")
check("total is consistent across pages", int(r2.get("total") or 0) == total1,
      f"p1={total1} p2={r2.get('total')}")
check("more derived from total on a non-final page", r1.get("more") is True,
      f"more={r1.get('more')} (48 of {total1})")

# --- merged multi-provider path with offset ---
r3 = eng.search(q="create", provider="all", type="mod", offset=48)
check("merged search page 2 has hits", bool(r3.get("hits")), f"{len(r3.get('hits') or [])} hits")

# --- browse (empty query) pagination ---
rb = eng.search(q="", provider="modrinth", type="shader", offset=0)
rb2 = eng.search(q="", provider="modrinth", type="shader", offset=48)
bh1 = [h.get("projectId") for h in (rb.get("hits") or [])]
bh2 = [h.get("projectId") for h in (rb2.get("hits") or [])]
check("browse page 1 has hits", len(bh1) > 0, f"{len(bh1)} hits")
check("browse page 2 differs from page 1", bool(bh2) and not set(bh1) & set(bh2),
      f"p1={len(bh1)} p2={len(bh2)}")

# --- per-provider page-size control ---
r4 = eng.search(q="create", provider="modrinth", type="mod", offset=0, page_size=96)
check("modrinth page_size honored up to 100", r4.get("page_size") == 96, f"page_size={r4.get('page_size')}")
check("modrinth full page reports more",
      (len(r4.get("hits") or []) < 96) or r4.get("more") is True,
      f"hits={len(r4.get('hits') or [])} more={r4.get('more')}")

r5 = eng.search(q="create", provider="curseforge", type="mod", offset=0, page_size=96)
check("curseforge page_size clamps to its 50 cap", r5.get("page_size") == 50,
      f"page_size={r5.get('page_size')}")
cf_total = int(r5.get("total") or 0)
check("curseforge success path surfaces a real total", cf_total > len(r5.get("hits") or []),
      f"total={cf_total} hits={len(r5.get('hits') or [])}")
check("curseforge success path reports more=True on a full page",
      r5.get("more") is (cf_total > 50), f"more={r5.get('more')} total={cf_total}")

# The REAL error path: a provider outage must report more=False (Next
# disabled) and surface the error — not an empty-page guess. The earlier
# version of this check ran against a keyless CF that failed, so it only
# ever saw the error branch; with the key configured the success branch
# (more=True on a full page) is now the live path. Simulate the outage
# directly on the provider so the error branch is genuinely exercised.
from engine.providers.curseforge import CurseForgeProvider  # noqa: E402

def _boom(opts):
    raise RuntimeError("simulated CurseForge outage")

eng2 = PyEngine()
cf_prov = CurseForgeProvider("invalid-key-for-error-path-test")
cf_prov.search_meta = _boom
mr = next((p for p in eng2._cached_providers() if p.name == "modrinth"), None)
eng2._providers = ([cf_prov, mr] if mr else [cf_prov])
eng2._providers_stamp = eng2.settings_store.mtime()
r5e = eng2.search(q="create", provider="curseforge", type="mod", offset=0)
check("curseforge error path reports more=False", r5e.get("more") is False,
      f"more={r5e.get('more')}")
check("curseforge error path surfaces the real error", bool(r5e.get("error")),
      f"error={r5e.get('error')}")

r6 = eng.search(q="create", provider="all", type="mod", offset=0, page_size=96)
check("merged page_size is the sum of per-source sizes",
      r6.get("page_size") in (96, 146), f"page_size={r6.get('page_size')}")
check("merged results capped at the merged page size",
      len(r6.get("hits") or []) <= (r6.get("page_size") or 0),
      f"hits={len(r6.get('hits') or [])} page_size={r6.get('page_size')}")
if len(r6.get("hits") or []) >= 96:check("merged more=True when a source returns a full page",
      r6.get("more") is True, f"more={r6.get('more')}")

# --- merged total is the sum of per-source totals ---
check("merged surfaces a total across sources", int(r6.get("total") or 0) >= int(r4.get("total") or 0),
      f"merged total={r6.get('total')} modrinth={r4.get('total')}")

# --- UI: pager renders, Next navigates to real page 2, Prev returns ---
from PyQt6.QtWidgets import QApplication  # noqa: E402
import theme  # noqa: E402

app = QApplication(sys.argv)
theme.setup_fonts(app)
from views.discover import DiscoverView  # noqa: E402

v = DiscoverView(eng)
v.resize(1280, 900)
v._type = "mod"
v._provider = "modrinth"
v._search.setText("create")
# force a direct fetch (skip debounce) and wait for the async result
v._search_serial += 1
serial = v._search_serial
v._show_loading()

def fetch():
    return v.api.search(q="create", provider="modrinth", mc="auto", loader="all",
                        type="mod", offset=0)

def ok(result):
    v._hits = result.get("hits") or []
    v._apply_results("create", result)

v._search_serial = serial
from common import run_async
run_async(fetch, ok, lambda e: check("ui fetch", False, str(e)))
deadline = time.time() + 30
while time.time() < deadline and not v._hits:
    app.processEvents()
    time.sleep(0.05)
check("UI page 1 loaded hits", len(v._hits) > 0, f"{len(v._hits)} hits")
check("pager label shows Page 1", "Page 1" in v._pager_status.text(), v._pager_status.text())
check("pager label shows 'of N total'", "of " in v._pager_status.text(), v._pager_status.text())
check("total stored from the real provider count", v._total > len(v._hits),
      f"total={v._total} hits={len(v._hits)}")
check("next button enabled on full page", v._next_btn.isEnabled(),
      f"{len(v._hits)} hits, page size {v._page_size}")

if v._next_btn.isEnabled():
    v._go_next()
    deadline = time.time() + 30
    while time.time() < deadline and len(v._hits) == 0:
        app.processEvents()
        time.sleep(0.05)
    # wait for page 2 to actually land (async fetch)
    for _ in range(120):
        app.processEvents()
        if v._pager_status.text().startswith("Page 2"):
            break
        time.sleep(0.05)
    check("navigated to page 2", v._page == 1 and "Page 2" in v._pager_status.text(),
          f"page={v._page} label={v._pager_status.text()}")
    check("prev button enabled on page 2", v._prev_btn.isEnabled())
    p2_ids = [h.get("projectId") for h in v._hits]
    check("page 2 hits differ from page 1", bool(p2_ids) and not set(h1) & set(p2_ids),
          f"overlap: {len(set(h1) & set(p2_ids))}")
    v._go_prev()
    for _ in range(60):
        app.processEvents()
        if v._pager_status.text().startswith("Page 1"):
            break
        time.sleep(0.05)
    check("prev returns to page 1", v._page == 0 and "Page 1" in v._pager_status.text(),
          v._pager_status.text())

# --- results-count + "more may exist" hint ---
check("more-hint label renders", bool(v._more_hint.text()), v._more_hint.text())
check("next button tooltip explains its state", bool(v._next_btn.toolTip()), v._next_btn.toolTip())

# --- jump-to-page + total-page estimate ---
import math as _math  # noqa: E402
pages_est = _math.ceil(v._total / max(1, v._page_size)) if v._total else 0
check("pager label shows the total-page estimate", f"({pages_est} pages)" in v._pager_status.text(),
      v._pager_status.text())
check("jump spin enabled with range to last page",
      v._jump_spin.isEnabled() and v._jump_spin.maximum() == pages_est,
      f"max={v._jump_spin.maximum()} of {pages_est}")
check("jump spin suffix shows the total", f"/ {pages_est}" in v._jump_spin.suffix(),
      v._jump_spin.suffix())
check("jump spin tracks the current page", v._jump_spin.value() == v._page + 1,
      f"spin={v._jump_spin.value()} page={v._page + 1}")
# real widget wiring: user enters page 5 → immediate navigation + re-search
v._jump_spin.setValue(5)
for _ in range(150):
    app.processEvents()
    if v._page == 4 and "Page 5" in v._pager_status.text():
        break
    time.sleep(0.05)
check("jump input navigates to page 5", v._page == 4 and "Page 5" in v._pager_status.text(),
      f"page={v._page} label={v._pager_status.text()}")
check("spin follows the jumped page", v._jump_spin.value() == 5, f"spin={v._jump_spin.value()}")
# jump back to page 1 via the same control
v._jump_spin.setValue(1)
for _ in range(150):
    app.processEvents()
    if v._page == 0 and "Page 1" in v._pager_status.text():
        break
    time.sleep(0.05)
check("jump input returns to page 1", v._page == 0 and "Page 1" in v._pager_status.text(),
      v._pager_status.text())
# guard: programmatic spin updates never re-trigger a search
page_before = v._page
v._updating_jump = True
v._jump_spin.setValue(v._page + 1)
v._updating_jump = False
check("programmatic spin updates are inert", v._page == page_before,
      f"page={v._page}")
# disabled without a real total — never guess page counts
real_total = v._total
v._total = 0
v._update_pager()
check("jump input disabled when total unknown", not v._jump_spin.isEnabled(),
      f"enabled={v._jump_spin.isEnabled()}")
v._total = real_total
v._update_pager()
check("jump input re-enabled with a total", v._jump_spin.isEnabled() and v._page == 0,
      f"enabled={v._jump_spin.isEnabled()} page={v._page}")

# --- per-provider page-size control in the UI ---
v._page_size_box.setCurrentIndex(2)  # 96 per page
check("page-size combo sets the base page size", v._base_page_size == 96,
      f"base={v._base_page_size}")
v._page_size_box.setCurrentIndex(1)  # back to 48
check("page-size combo restores 48", v._base_page_size == 48, f"base={v._base_page_size}")

# --- remember last page per browsing context (type + provider + loader +
#     version + page size), persisted to the UI state file ---
import json as _json  # noqa: E402
_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state.json")
_state_before = open(_state_path, encoding="utf-8").read() if os.path.exists(_state_path) else None

try:
    v._type = "mod"
    v._provider = "modrinth"
    v._loader = "all"
    v._version = "auto"
    v._page = 2
    v._remember_page()
    ctx_mod = v._ctx_key()
    v._type = "shader"
    v._page = 0
    v._remember_page()
    # a different filter combo is a different context: remember page 4 under
    # mod + curseforge + forge so the restore is exact
    v._type = "mod"
    v._provider = "curseforge"
    v._loader = "forge"
    v._version = "1.20.1"
    v._page = 4
    v._remember_page()
    ctx_mod_cf = v._ctx_key()
    # "returning to Discover restores where you were" — same restore the
    # type/provider/filter handlers perform.
    v._type = "mod"
    v._provider = "modrinth"
    v._loader = "all"
    v._version = "auto"
    v._page = int(v._remembered.get(v._ctx_key(), 0) or 0)
    check("returning to a context restores its page", v._page == 2, f"page={v._page}")
    v._type = "mod"
    v._provider = "curseforge"
    v._loader = "forge"
    v._version = "1.20.1"
    v._page = int(v._remembered.get(v._ctx_key(), 0) or 0)
    check("each filter combo keeps its own page", v._page == 4, f"page={v._page}")
    check("contexts are distinct keys", ctx_mod != ctx_mod_cf, f"{ctx_mod} vs {ctx_mod_cf}")
    from views.misc import _load_state as _ls_state  # noqa: E402
    check("page memory persisted to the state file",
          _ls_state().get("discoverPages", {}).get(ctx_mod) == 2,
          str(_ls_state().get("discoverPages")))
finally:
    # restore the dev state file exactly — the test must not change app state
    if _state_before is not None:
        with open(_state_path, "w", encoding="utf-8") as f:
            f.write(_state_before)
    elif os.path.exists(_state_path):
        os.unlink(_state_path)

print("PAGINATION " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
