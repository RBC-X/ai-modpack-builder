"""Flaws-council verification: shader vs resource-pack routing must not mix.

Run:  pyqt/.venv/Scripts/python pyqt/shader_routing_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.launcher import _visual_files  # noqa: E402
from engine import instance  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    sh = td / "shader.zip"
    rp = td / "rp.zip"
    sh.write_bytes(b"x")
    rp.write_bytes(b"y")
    rec = {"selections": [
        {"projectType": "shader", "downloadPath": str(sh), "selected": True},
        {"projectType": "resourcepack", "downloadPath": str(rp), "selected": True},
        {"projectType": "mod", "downloadPath": str(td / "mod.jar"), "selected": True},
        {"projectType": "shader", "downloadPath": str(td / "gone.zip"), "selected": True},
    ]}
    v = _visual_files(rec)
    check("both shader selections route to shaders[]",
          str(sh) in v["shaders"] and str(td / "gone.zip") in v["shaders"], str(v["shaders"]))
    check("resource pack routes to resourcePacks[]", v["resourcePacks"] == [str(rp)], str(v["resourcePacks"]))
    # Recorded-but-missing files stay listed (download may land later); install
    # time filters them. Both shader entries are routed to shaders[] — the
    # important part is NONE of them leak into resourcePacks[].
    check("all shaders stay out of resourcePacks[]",
          all("shader" not in x for x in v["resourcePacks"]))

    gd = td / "game"
    (gd / "shaderpacks").mkdir(parents=True)
    (gd / "resourcepacks").mkdir(parents=True)

    class _L:
        @staticmethod
        def info(*a): pass
        @staticmethod
        def warn(*a): pass

    instance.install_shader_packs(gd / "shaderpacks", v["shaders"], _L())
    instance.install_resource_packs(gd / "resourcepacks", v["resourcePacks"], _L())
    check("shader lands in shaderpacks/", (gd / "shaderpacks" / "shader.zip").exists())
    check("resource pack lands in resourcepacks/", (gd / "resourcepacks" / "rp.zip").exists())
    check("shader NOT in resourcepacks/", not (gd / "resourcepacks" / "shader.zip").exists())

print("SHADER ROUTING " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
