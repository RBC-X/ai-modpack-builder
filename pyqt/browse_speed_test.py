"""Prove the browse-speed work: warm catalog loads beat cold loads, the
merged \"all sources\" search returns both providers, and Worlds routing is
honest without a CurseForge key.

Run:  pyqt/.venv/Scripts/python pyqt/browse_speed_test.py
"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

from engine.service import PyEngine  # noqa: E402
from engine.providers.http import _cache_root  # noqa: E402

report: dict = {"phases": []}
COMBOS = [
    ("mod", "1.20.1"), ("mod", "1.21.1"), ("modpack", "1.20.1"),
    ("shader", "1.20.1"), ("resourcepack", "1.20.1"), ("world", "1.20.1"),
]


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def main() -> int:
    e = PyEngine()
    # ---- 1. cold vs warm: wipe the provider cache, time the full set -------
    cache_dir = Path(_cache_root)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)

    def run_all() -> dict:
        out = {}
        for ctype, mc in COMBOS:
            t0 = time.perf_counter()
            r = e.search(q="", provider="all", mc=mc, loader="all", type=ctype)
            out[(ctype, mc)] = (time.perf_counter() - t0, r)
        return out

    cold = run_all()
    cold_total = sum(v[0] for v in cold.values())
    phase("cold catalogs queried live", all(not v[1].get("error") or "API key" in str(v[1].get("error")) for v in cold.values()),
          f"total {cold_total*1000:.0f} ms for 6 catalogs")

    warm = run_all()
    warm_total = sum(v[0] for v in warm.values())
    speedup = cold_total / max(warm_total, 1e-6)
    phase("warm catalogs served from disk cache", warm_total < cold_total and warm_total < 1.5,
          f"total {warm_total*1000:.0f} ms vs cold {cold_total*1000:.0f} ms ({speedup:.1f}x faster)")

    for (ctype, mc), (secs, r) in warm.items():
        n = len(r.get("hits") or [])
        print(f"    warm {ctype:13s} {mc}: {secs*1000:6.0f} ms, {n} hits", flush=True)

    # ---- 2. merged \"all sources\" search ------------------------------------
    r = e.search(q="", provider="all", mc="1.20.1", loader="all", type="mod")
    sources = r.get("sources") or []
    phase("all-sources returns both provider statuses",
          any(s.get("provider") == "modrinth" and s.get("ok") for s in sources)
          and any(s.get("provider") == "curseforge" for s in sources),
          f"sources={[{'p': s.get('provider'), 'ok': s.get('ok'), 'count': s.get('count')} for s in sources]}")
    phase("all-sources merges real hits", len(r.get("hits") or []) >= 10,
          f"{len(r.get('hits') or [])} merged hits")

    # ---- 3. worlds routing without a CF key ---------------------------------
    rw = e.search(q="", provider="all", mc="1.20.1", loader="all", type="world")
    honest = "CurseForge API key" in str(rw.get("error") or "")
    phase("worlds honest without CF key", honest and not (rw.get("hits") or []),
          str(rw.get("error"))[:90])

    report["overall"] = "PASS" if all(p["status"] == "PASS" for p in report["phases"]) else "FAIL"
    out = ROOT.parent / "workspace" / "browse-speed-result.json"
    report["coldTotalMs"] = round(cold_total * 1000)
    report["warmTotalMs"] = round(warm_total * 1000)
    report["speedupX"] = round(speedup, 1)
    out.write_text(json.dumps(report, indent=2), "utf-8")
    print(f"\nOVERALL: {report['overall']} -> {out}", flush=True)
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
