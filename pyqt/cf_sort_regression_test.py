"""Regression test: CurseForge search ranks by downloads by default.

Both query mode and browse mode must send sortField=6 & sortOrder=desc so
the canonical mod (e.g. JEI) surfaces instead of fuzzy relevance matches.
A caller-passed opts["sort"] still wins.

Deterministic — stubs the HTTP layer, no network.

Run: pyqt/.venv/Scripts/python pyqt/cf_sort_regression_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

import engine.providers.curseforge as cfmod  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


# Canned API response: one mod with downloads + pagination.
def _canned(_provider: str, url: str, **_kw):
    captured.append(url)
    return {
        "data": [{
            "id": 238222, "slug": "jei", "name": "Just Enough Items (JEI)",
            "summary": "JEI", "downloadCount": 608818010,
            "classId": 6, "isAvailable": True,
            "logo": {"url": "https://x/logo.png", "thumbnailUrl": "https://x/logo_t.png"},
            "categories": [], "authors": [{"name": "mezz"}], "links": {},
        }],
        "pagination": {"totalCount": 33},
    }


captured: list[str] = []
cfmod.provider_get = _canned
p = cfmod.CurseForgeProvider(api_key="probe-key", allow_direct_downloads=False)

p.search_meta({"query": "Just Enough Items", "limit": 10, "projectType": "mod"})
url = captured[-1]
check("query mode sorts by downloads (sortField=6)",
      "sortField=6" in url and "sortOrder=desc" in url, url)
check("query mode still sends the search filter",
      "searchFilter=Just+Enough+Items" in url, url)

p.search_meta({"limit": 10, "projectType": "mod"})
url = captured[-1]
check("browse mode sorts by downloads too",
      "sortField=6" in url and "sortOrder=desc" in url, url)

p.search_meta({"query": "create", "limit": 10, "projectType": "mod", "sort": "updated"})
url = captured[-1]
check("updated maps to sortField=3", "sortField=3" in url, url)
p.search_meta({"query": "create", "limit": 10, "projectType": "mod", "sort": "name"})
url = captured[-1]
check("name maps to sortField=4", "sortField=4" in url, url)

# And the mapped hit carries the real download count.
r = p.search_meta({"query": "Just Enough Items", "limit": 10, "projectType": "mod"})
h = r["hits"][0]
check("hit maps real downloads", h["downloads"] == 608818010, h["downloads"])
check("hit keeps project id", h["projectId"] == "238222", h["projectId"])

print("CF SORT " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
