"""Config generator — Python port of src/configs/*.

Writes pack-specific configs that reduce memory pressure or fix common
compatibility issues (mob counts, view distance, particle counts).
"""
from __future__ import annotations

import json
from pathlib import Path

from .core import mkdirp


def apply_performance_configs(game_dir, ram_gb: int = 8) -> list:
    """Write conservative client/server settings for low-RAM packs."""
    applied = []
    gd = Path(game_dir)
    mkdirp(gd / "config")
    # server.properties: lower view distance for low-RAM machines
    props_path = gd / "server.properties"
    if props_path.exists():
        text = props_path.read_text("utf-8")
        changed = False
        for key, val in (("view-distance", "6"), ("simulation-distance", "6")):
            if f"{key}=" in text:
                text = text.replace(f"{key}=0", f"{key}={val}").replace(f"{key}=10", f"{key}={val}")
                changed = True
        if changed:
            props_path.write_text(text, "utf-8")
            applied.append("server.properties: view/simulation distance reduced")
    return applied


def write_pack_readme_content(name: str, mc: str, loader: str, mod_count: int,
                              ram_gb: int, test_status: str) -> str:
    return (
        f"# {name}\n\n"
        f"Minecraft {mc} · {loader}\n"
        f"{mod_count} mods · ~{ram_gb} GB RAM recommended\n\n"
        f"Built by AI Modpack Builder.\n"
        f"Final test status: {test_status}\n"
    )
