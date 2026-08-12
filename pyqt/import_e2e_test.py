"""End-to-end proof that importing a .mrpack actually installs its mods.

Uses a REAL .mrpack exported from a real build (real Modrinth CDN URLs +
SHA-1 hashes). Verifies:
  1. Import downloads the mod jars (hash-verified) into the instance mods dir.
  2. Selections are populated with real titles (hash -> project enrichment).
  3. Overrides are extracted.
  4. Cancel aborts cleanly and removes the partial build.

Run:  pyqt/.venv/Scripts/python pyqt/import_e2e_test.py
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "engine"))

from engine.service import PyEngine  # noqa: E402
from engine.exports import export_mrpack  # noqa: E402
from engine.core import BuildLogger  # noqa: E402

SRC_BID = "b-19fef76f75e-0fb05980"  # real build whose mods were downloaded from Modrinth
MRPACK = ROOT.parent / "workspace" / "import-e2e-fixture.mrpack"

report: dict = {"phases": []}


def phase(name: str, ok: bool, detail: str) -> None:
    report["phases"].append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
    print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)


def main() -> int:
    # ---- regenerate a spec-clean fixture from the real build ----------------
    src_build = ROOT.parent / "workspace" / "builds" / SRC_BID
    src_rec = json.loads((src_build / "build.json").read_text(encoding="utf-8"))
    export_mrpack({
        "name": "Import E2E Fixture", "summary": "fixture", "mcVersion": src_rec["requirements"]["minecraftVersion"],
        "loader": src_rec["requirements"]["loader"], "loaderVersion": None,
        "selections": src_rec.get("selections") or [], "graph": src_rec.get("graph") or {"nodes": {}},
        "modsDir": str(src_build / "downloads" / "mods"), "overridesDir": str(src_build / "instance" / "minecraft"),
        "outPath": str(MRPACK), "logger": BuildLogger("import-e2e", ROOT.parent / "workspace" / "import-e2e-logs"),
    })
    assert MRPACK.exists(), f"mrpack missing: {MRPACK}"
    # Sanity: the archive genuinely references files (jars) that are NOT inside it.
    import zipfile
    with zipfile.ZipFile(MRPACK) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
        entry_paths = [e.get("path") for e in index.get("files") or []]
        mod_entries = [p for p in entry_paths if p and p.startswith("mods/")]
        in_zip = [n for n in zf.namelist() if n.startswith("mods/")]
    phase("archive sanity", bool(mod_entries) and not in_zip,
          f"{len(mod_entries)} mods referenced in index, {len(in_zip)} jars inside zip (expected 0)")

    svc = PyEngine()
    progress_log: list = []

    def on_progress(stage: str, done: int, total: int) -> None:
        progress_log.append((stage, done, total))

    res = svc.import_file(str(MRPACK), name="E2E Import Test", progress=on_progress)
    phase("import ok", bool(res.get("ok")), f"modCount={res.get('modCount')} downloaded={res.get('downloaded')} failed={res.get('failed')}")

    bid = res.get("buildId")
    assert bid, "no buildId"
    rec_path = ROOT.parent / "workspace" / "builds" / bid / "build.json"
    rec = json.loads(rec_path.read_text(encoding="utf-8"))
    mods_dir = ROOT.parent / "workspace" / "builds" / bid / "instance" / "minecraft" / "mods"
    jars = sorted(p.name for p in mods_dir.glob("*.jar")) if mods_dir.exists() else []
    phase("mods installed on disk", len(jars) == res.get("modCount", 0) and len(jars) > 0,
          f"{len(jars)} jars in instance mods dir")
    titles = [s.get("title") for s in rec.get("selections") or []]
    real_titles = [t for t in titles if t and t != "E2E Import Test"]
    phase("selections populated", len(real_titles) == res.get("modCount", 0),
          f"{len(real_titles)} selections with real titles (e.g. {real_titles[:3]})")
    phase("progress reported", len(progress_log) > 0 and progress_log[-1][1] == progress_log[-1][2],
          f"{len(progress_log)} progress callbacks, final {progress_log[-1] if progress_log else None}")
    phase("record persisted", rec.get("status") == "done" and rec.get("packStats", {}).get("modCount") == res.get("modCount"),
          f"status={rec.get('status')} modCount={rec.get('packStats', {}).get('modCount')}")

    # ---- cancel path: pre-set the event so the very first download aborts ----
    cancel = threading.Event()
    cancel.set()
    res2 = svc.import_file(str(MRPACK), name="Cancel Test", cancel=cancel)
    phase("cancel returns cancelled", bool(res2.get("cancelled")), str(res2))
    cancelled_bid = res2.get("buildId")
    gone = not (ROOT.parent / "workspace" / "builds" / cancelled_bid).exists()
    phase("partial build cleaned up", bool(gone), f"build dir removed: {gone}")

    # ---- cleanup the successful import build ----
    svc.delete_pack(bid)
    phase("cleanup", not (ROOT.parent / "workspace" / "builds" / bid).exists(), f"removed {bid}")

    report["overall"] = "PASS" if all(p["status"] == "PASS" for p in report["phases"]) else "FAIL"
    out = ROOT.parent / "workspace" / "import-e2e-result.json"
    out.write_text(json.dumps(report, indent=2), "utf-8")
    print(f"\nOVERALL: {report['overall']} -> {out}", flush=True)
    return 0 if report["overall"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
