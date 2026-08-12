"""Shader presets engine test: GPU tiering, preset choice, and a LIVE Modrinth
shader selection (real project + MC-compatible version + download URL).

Run:  pyqt/.venv/Scripts/python pyqt/shader_preset_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.shaders import gpu_tier, pick_shader_preset, choose_shader, PRESET_SLUGS  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


# --- GPU tier classification ---
check("integrated intel", gpu_tier("Intel(R) UHD Graphics 620") == "integrated")
check("integrated iris xe", gpu_tier("Intel(R) Iris(R) Xe Graphics") == "integrated")
check("integrated amd radeon graphics", gpu_tier("AMD Radeon(TM) Graphics") == "integrated")
check("high rtx 40", gpu_tier("NVIDIA GeForce RTX 4070") == "discrete-high")
check("high rtx 50", gpu_tier("NVIDIA GeForce RTX 5080") == "discrete-high")
check("high rx 7900", gpu_tier("AMD Radeon RX 7900 XT") == "discrete-high")
check("mid rtx 30", gpu_tier("NVIDIA GeForce RTX 3060") == "discrete-mid")
check("mid rx 6600", gpu_tier("AMD Radeon RX 6600") == "discrete-mid")
check("mid gtx 1660", gpu_tier("NVIDIA GeForce GTX 1660 Super") == "discrete-mid")
check("unknown gpu", gpu_tier("Unknown GPU") == "unknown")

# --- preset choice ---
def preset_for(gpu, ram=16, fps=60, requested=None):
    hw = {"effective": {"gpu": gpu, "ramGB": ram, "targetFps": fps}}
    return pick_shader_preset({"ramGB": ram}, hw, requested=requested)["preset"]

check("integrated -> performance", preset_for("Intel UHD Graphics 620") == "performance")
check("mid discrete -> balanced", preset_for("NVIDIA GeForce RTX 3060") == "balanced")
check("high discrete -> cinematic", preset_for("NVIDIA GeForce RTX 4080") == "cinematic")
check("high discrete but 6 GB RAM -> performance", preset_for("NVIDIA GeForce RTX 4080", ram=6) == "performance")
check("high discrete but 10 GB RAM -> balanced", preset_for("NVIDIA GeForce RTX 4080", ram=10) == "balanced")

# --- request-quality intent (Task: honor the prompt, never exceed the machine) ---
check("light shaders on high GPU -> performance", preset_for("NVIDIA GeForce RTX 4080", requested="performance") == "performance")
check("cinematic on high GPU -> cinematic", preset_for("NVIDIA GeForce RTX 4080", requested="cinematic") == "cinematic")
check("cinematic on integrated downgrades to performance", preset_for("Intel UHD Graphics 620", requested="cinematic") == "performance")
check("cinematic on 10 GB downgrades to balanced", preset_for("NVIDIA GeForce RTX 4080", ram=10, requested="cinematic") == "balanced")
check("cinematic reason mentions the downgrade", "can't run them" in pick_shader_preset({"ramGB": 16}, {"effective": {"gpu": "Intel UHD Graphics 620", "ramGB": 16}}, requested="cinematic")["reason"])

# --- explicit Pack Detail override (Task: swap preset) ---
check("explicit balanced on high GPU honored", preset_for("NVIDIA GeForce RTX 4080", requested="balanced") == "balanced")
check("explicit performance on high GPU honored", preset_for("NVIDIA GeForce RTX 4080", requested="performance") == "performance")

# --- interpreter shader-quality intent ---
from engine.interpreter import interpret  # noqa: E402
check("cinematic intent parsed", interpret("make a pack with cinematic shaders")["requirements"].get("shaderQuality") == "cinematic")
check("light shader intent parsed", interpret("use light shaders")["requirements"].get("shaderQuality") == "performance")
check("no quality hint stays None", interpret("add shaders to my pack")["requirements"].get("shaderQuality") is None)

# --- presets map to verified-real slugs ---
for preset, slugs in PRESET_SLUGS.items():
    check(f"preset {preset} has candidates", bool(slugs), str(slugs))

# --- LIVE: pick a real shader for 1.20.1 (balanced preset) ---
from engine.providers.registry import build_providers  # noqa: E402
from engine.providers.settings import SettingsStore  # noqa: E402

providers = build_providers(SettingsStore())
sh = choose_shader(providers, "1.20.1", "balanced")
check("live shader found for 1.20.1", sh is not None,
      f"{sh['project']['title']} {sh['version']['versionNumber']}" if sh else "none")
if sh:
    check("project is a real shader pack", sh["project"]["projectType"] == "shader",
          f"type={sh['project']['projectType']}")
    check("version supports 1.20.1", "1.20.1" in (sh["version"].get("gameVersions") or []),
          str((sh["version"].get("gameVersions") or [])[:4]))
    check("has a direct download URL", bool(sh["file"].get("url")), sh["file"].get("url", "")[:60])
    check("file has a zip-ish extension", sh["file"].get("filename", "").lower().endswith(".zip"),
          sh["file"].get("filename", ""))

print("SHADER PRESET " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
