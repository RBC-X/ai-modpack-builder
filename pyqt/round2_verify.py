"""Council round 2 verification: hardware-detect cache and mrpack stray-entry check."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


# --- 1) detect_hardware is cached: second call must not spawn PowerShell ---
import engine.hardware as hw  # noqa: E402

calls = {"n": 0}
orig_run = hw.subprocess.run


def counting_run(*a, **kw):
    calls["n"] += 1
    return orig_run(*a, **kw)


hw.subprocess.run = counting_run
try:
    first = hw.detect_hardware(force=True)  # bypass cache; populates it
    n_after_first = calls["n"]
    second = hw.detect_hardware()
    check("second detect_hardware() does not re-spawn", calls["n"] == n_after_first,
          f"spawns={calls['n']}")
    check("cached result identical", first == second)
finally:
    hw.subprocess.run = orig_run

# fit_xmx_mb also benefits (same module cache) and returns sane values
x = hw.fit_xmx_mb(8)
check("fit_xmx_mb returns multiple of 256 >= 2048", x >= 2048 and x % 256 == 0, f"xmx={x}")


# --- 2) validate_mrpack rejects stray root entries, accepts clean ones ---
from engine.exports import validate_mrpack  # noqa: E402


def make_mrpack(zpath: Path, stray: bool) -> None:
    index = {
        "formatVersion": 1, "game": "minecraft", "versionId": "1.20.1-fabric",
        "name": "T", "summary": "", "dependencies": {"minecraft": "1.20.1", "fabric-loader": "*"},
        "files": [{"path": "mods/example.jar", "hashes": {"sha1": "0" * 40},
                   "env": {"client": "required", "server": "required"},
                   "downloads": ["https://cdn.modrinth.com/data/x/versions/y/example.jar"]}],
    }
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        zf.writestr("overrides/config/thing.toml", "x=1")
        zf.writestr("overrides/.mrpack-root", "")
        if stray:
            zf.writestr("mods/example.jar", b"JARBYTES")  # embedded jar = leak


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    clean = td / "clean.mrpack"
    make_mrpack(clean, stray=False)
    d = validate_mrpack(clean)
    check("clean mrpack passes", all(not x.startswith("ERR") for x in d), str(d))
    bad = td / "bad.mrpack"
    make_mrpack(bad, stray=True)
    d2 = validate_mrpack(bad)
    check("stray-embedded jar detected", any("stray entries" in x for x in d2), str(d2))

print("ROUND2 VERIFY " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
