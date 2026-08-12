"""Live probe: CurseForge shader/resource-pack search + file URL availability.

Answers the Task-3 question: when a CF key is configured, can the visuals
engines get shader/RP candidates with real, downloadable file URLs?
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.providers.settings import SettingsStore  # noqa: E402
from engine.providers.curseforge import CurseForgeProvider  # noqa: E402

key = SettingsStore().curseforge_key()
print(f"CF key configured: {bool(key)}")
prov = CurseForgeProvider(api_key=key or "", allow_direct_downloads=False)
if not prov.available:
    print("SKIP: no CF key")
    sys.exit(0)

for ptype, query, mc in (("shader", "complementary", "1.20.1"),
                         ("resourcepack", "faithful", "1.20.1")):
    print(f"\n=== {ptype}: search '{query}' for {mc} ===")
    try:
        hits = prov.search({"query": query, "projectType": ptype, "minecraftVersion": mc, "limit": 5})
    except Exception as e:
        print(f"  search failed: {e}")
        continue
    if not hits:
        print("  no hits")
        continue
    for h in hits[:3]:
        print(f"  {h['title']} (id {h['projectId']}) class={h['projectType']} dl={h['downloads']}")
        try:
            vs = prov.get_versions(h["projectId"], {"minecraftVersion": mc}) or []
        except Exception as e:
            print(f"    versions error: {e}")
            vs = []
        usable = 0
        for v in vs[:6]:
            f = (v.get("files") or [None])[0]
            url = (f or {}).get("url") or ""
            if url:
                usable += 1
        print(f"    versions for {mc}: {len(vs)}; with download URL: {usable}")
        for v in vs[:3]:
            f = (v.get("files") or [None])[0]
            print(f"      {v.get('versionNumber','')[:30]} url={((f or {}).get('url') or '')[:60]} ext={((f or {}).get('filename') or '?')[-8:]}")
