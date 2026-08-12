"""Python engine self-test — real data, no mocks.

1. Interpreter on the flagship prompt
2. Live Modrinth search (network)
3. A real small build (instant test mode) through the full pipeline
4. Export validation for the produced .mrpack + CurseForge zip
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from engine.bridge import PyEngine
from engine.interpreter import interpret

PASS = []
FAIL = []


def check(name: str, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name} — {detail}")


def main():
    print("== 1. Interpreter ==")
    reqs = interpret("Make me a Minecraft 1.20.1 medieval fantasy RPG modpack with around 60-80 mods, Create, magic, better villages, bosses, structures, realistic terrain, shaders, 32x textures, multiplayer support, and good performance on 8 GB RAM.")["requirements"]
    check("MC version", reqs["minecraftVersion"] == "1.20.1", reqs["minecraftVersion"])
    check("loader auto", reqs["loader"] in ("auto", "fabric", "forge"), reqs["loader"])
    check("themes", "medieval" in reqs["theme"] and "fantasy" in reqs["theme"], str(reqs["theme"]))
    check("features", any(f["id"] == "create" for f in reqs["features"]), str([f["id"] for f in reqs["features"]][:8]))
    check("shaders", reqs["shaders"] is True, str(reqs["shaders"]))
    check("multiplayer", reqs["multiplayer"] is True, str(reqs["multiplayer"]))

    print("\n== 2. Live Modrinth search ==")
    e = PyEngine()
    r = e.search(q="create", provider="modrinth", mc="1.20.1", loader="forge", type="mod")
    hits = r.get("hits") or []
    check("search returned results", len(hits) > 0, f"{len(hits)} hits")
    if hits:
        check("real project data", bool(hits[0].get("slug")) and bool(hits[0].get("title")),
              f"{hits[0].get('title')} ({hits[0].get('slug')}) dl={hits[0].get('downloads')}")

    print("\n== 3. Real build (instant mode) ==")
    bid = e.start_build({
        "prompt": "Make me a lightweight Minecraft 1.20.1 Fabric fantasy exploration pack with structures, bosses, improved terrain, performance mods, around 8-12 mods, on 8 GB RAM",
        "mcVersion": "1.20.1", "loader": "fabric", "packSize": "light",
        "ramGB": 8, "testMode": "instant",
    })
    print(f"  build started: {bid}")
    # poll for completion (events stream + record status)
    deadline = time.time() + 300
    status = "building"
    last = ""
    while time.time() < deadline:
        time.sleep(3)
        rec = e.build(bid)
        status = rec.get("status", "building")
        if status != last:
            print(f"  status: {status}")
            last = status
        if status in ("done", "failed", "error"):
            break
    check("build completed", status in ("done", "failed"), status)
    rec = e.build(bid)
    if rec.get("error"):
        print(f"  build error: {rec['error']}")
    check("selections made", len(rec.get("selections") or []) > 0, f"{len(rec.get('selections') or [])} selections")
    check("mods downloaded", (rec.get("packStats") or {}).get("modCount", 0) > 0,
          f"{((rec.get('packStats') or {}).get('modCount'))} mods")
    check("test result recorded", (rec.get("testResult") or {}).get("status") in ("PASS", "FAIL"),
          str((rec.get("testResult") or {}).get("status")))

    print("\n== 4. Export validation ==")
    exports = rec.get("exports") or []
    check("exports produced", len(exports) > 0, f"{len(exports)} exports")
    for ex in exports:
        p = Path(ex["path"])
        check(f"export exists: {p.name}", p.exists(), f"{ex.get('sizeBytes')} bytes")
        check(f"export validated: {p.name}", ex.get("validated") is True,
              "; ".join(ex.get("validationDetails") or [])[:160])

    print("\n== 5. Records index ==")
    builds = e.builds()
    check("build visible in library", any(b.get("buildId") == bid for b in builds), f"{len(builds)} builds indexed")

    print(f"\n===== {len(PASS)} passed, {len(FAIL)} failed =====")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    main()
