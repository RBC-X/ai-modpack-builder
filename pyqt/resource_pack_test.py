"""Resource-pack engine test: resolution/GPU decisions, LIVE Modrinth pick, and
the Pack Detail specs-card rendering (real choices, not dead stats keys).

Run:  pyqt/.venv/Scripts/python pyqt/resource_pack_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.resource_packs import pick_resource_pack, choose_resource_pack, RESOLUTION_SLUGS  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


# --- decision logic ---
def pick_for(gpu, res, ram=8, theme=("medieval",)):
    hw = {"effective": {"gpu": gpu, "ramGB": ram}}
    return pick_resource_pack({"resourcePackResolution": res, "theme": list(theme)}, hw)


check("no resolution request -> None", pick_resource_pack({"resourcePackResolution": 0}, {}) is None)
rp = pick_for("Intel UHD Graphics", 32)
check("32x on integrated stays 32x", rp["resolution"] == 32, str(rp))
rp = pick_for("Intel UHD Graphics", 64)
check("64x on integrated downgrades to 32x", rp["resolution"] == 32, rp["reason"])
rp = pick_for("NVIDIA GeForce RTX 3060", 64)
check("64x on mid discrete stays 64x", rp["resolution"] == 64, rp["reason"])
rp = pick_for("NVIDIA GeForce RTX 3060", 128)
check("128x capped to 64x", rp["resolution"] == 64, rp["reason"])
rp = pick_for("NVIDIA GeForce RTX 3060", 64, ram=6)
check("64x on mid discrete with 6 GB RAM downgrades to 32x", rp["resolution"] == 32, rp["reason"])
rp = pick_for("NVIDIA GeForce RTX 4080", 64, ram=16)
check("64x on high GPU with 16 GB stays 64x", rp["resolution"] == 64, rp["reason"])
check("theme mentioned in reason", "medieval" in pick_for("NVIDIA GeForce RTX 3060", 32)["reason"],
      pick_for("NVIDIA GeForce RTX 3060", 32)["reason"])

for tier, slugs in RESOLUTION_SLUGS.items():
    check(f"resolution {tier} has candidates", bool(slugs), str(slugs))

# --- LIVE: real pick for 1.20.1 at 32x ---
from engine.providers.registry import build_providers  # noqa: E402
from engine.providers.settings import SettingsStore  # noqa: E402

providers = build_providers(SettingsStore())
rp = choose_resource_pack(providers, "1.20.1", 32, ["medieval", "fantasy"])
check("live resource pack found for 1.20.1", rp is not None,
      f"{rp['project']['title']} {rp['version']['versionNumber']}" if rp else "none")
if rp:
    check("project is a real resource pack", rp["project"]["projectType"] == "resourcepack",
          f"type={rp['project']['projectType']}")
    check("version supports 1.20.1", "1.20.1" in (rp["version"].get("gameVersions") or []),
          str((rp["version"].get("gameVersions") or [])[:4]))
    check("has a direct download URL", bool(rp["file"].get("url")), rp["file"].get("url", "")[:60])
    check("file is a zip", rp["file"].get("filename", "").lower().endswith(".zip"),
          rp["file"].get("filename", ""))

# --- Pack Detail specs card renders real choices ---
from PyQt6.QtWidgets import QApplication  # noqa: E402
import theme  # noqa: E402

app = QApplication(sys.argv)
theme.setup_fonts(app)

from views.packdetail import PackDetailView  # noqa: E402

v = PackDetailView(None)
v.record = {
    "requirements": {"minecraftVersion": "1.20.1", "loader": "fabric", "ramGB": 4},
    "packStats": {"modCount": 10},
    "perfEstimate": {"confidence": 85},
    "shaderChoice": {"preset": "performance", "gpuTier": "integrated",
                     "title": "MakeUp - Ultra Fast", "reason": "x"},
    "resourcePackChoice": {"resolution": 32, "gpuTier": "integrated",
                           "title": "Faithful 32x", "reason": "y"},
    "tests": [{"status": "PASS", "level": "standard"}],
}
card = v._specs_card()
labels = [w.text() for w in card.findChildren(type(card.children()[0])) if hasattr(w, "text")]
import PyQt6.QtWidgets as _qw
all_text = " | ".join(w.text() for w in card.findChildren(_qw.QLabel))
check("specs card shows shader title + preset", "MakeUp - Ultra Fast" in all_text and "performance preset" in all_text, all_text[:120])
check("specs card shows resource pack title", "Faithful 32x" in all_text, all_text[:120])
check("specs card no longer shows dead Shaders 0", "Shaders 0" not in all_text)

# no choices at all -> dashes, not dead counts
v2 = PackDetailView(None)
v2.record = {"requirements": {}, "packStats": {}, "tests": []}
c2 = v2._specs_card()
t2 = " | ".join(w.text() for w in c2.findChildren(_qw.QLabel))
check("no-choice pack shows dashes", "—" in t2 and "0 Mods" in t2, t2[:100])

print("RESOURCE PACK " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
