"""Flaws-council verification: key-less CurseForge ZIP import must degrade to
reference-only (no crash on prov=None) and a failed download must never record
a phantom downloadPath.

Run:  pyqt/.venv/Scripts/python pyqt/cf_import_edge_test.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

import engine.imports as imp  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


def make_cf_zip(path: Path) -> None:
    manifest = {
        "minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.4.0"}]},
        "manifestType": "minecraftModpack", "manifestVersion": 1,
        "name": "Synthetic CF Pack", "version": "1.0.0",
        "files": [
            {"projectID": 123456, "fileID": 999, "required": True},
        ],
        "overrides": {},
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("overrides/config/toml.txt", "just a config\n")


# --- 1) prov=None must not crash; records an honest reference ---
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    zpath = td / "synth-cf.zip"
    make_cf_zip(zpath)
    rec = {"buildId": "t1", "requirements": {}, "name": "T"}
    res = imp.import_curseforge(rec, zpath, td / "build", None)
    check("key-less CF import does not crash", "kind" in res)
    check("key-less CF import records reference", res["references"] == 1, f"refs={res['references']}")
    sel = res["selections"][0]
    check("reference selection has no phantom downloadPath",
          sel.get("downloadPath") == "", f"path={sel.get('downloadPath')!r}")
    check("reference reason is honest", "reference-only" in sel.get("reason", ""), sel.get("reason", ""))
    check("requirements recorded", rec["requirements"].get("minecraftVersion") == "1.20.1"
          and rec["requirements"].get("loader") == "forge")

# --- 2) failed download must not record a phantom path ---
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    zpath = td / "synth-cf2.zip"
    make_cf_zip(zpath)

    class FakeProv:
        available = True
        def _get(self, url):  # real endpoint shape; file exists with a URL
            return {"data": {"downloadUrl": "https://edge.forgecdn.net/fake.jar",
                             "fileName": "fake.jar", "fileLength": 1000,
                             "hashes": [{"algo": 1, "value": "0" * 40}]}}

    import engine.core as core
    orig = core.download_to_file

    def boom(url, dest, **kw):
        raise RuntimeError("network down")

    core.download_to_file = boom
    try:
        rec = {"buildId": "t2", "requirements": {}, "name": "T"}
        res = imp.import_curseforge(rec, zpath, td / "build", FakeProv())
    finally:
        core.download_to_file = orig
    check("failed CF download counted as failed", res["failed"] == 1, f"failed={res['failed']}")
    sel = res["selections"][0]
    check("failed download has no phantom downloadPath",
          sel.get("downloadPath") == "", f"path={sel.get('downloadPath')!r}")
    check("failed download reason is honest", "download failed" in sel.get("reason", ""), sel.get("reason", ""))

print("CF IMPORT EDGE " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
