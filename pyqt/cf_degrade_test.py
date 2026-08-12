"""CF-degradation test: a configured-but-broken CurseForge key must NOT break
the visuals engines. With the (invalid) stored key, choose_shader /
choose_resource_pack must warn, skip CF, and still return a real Modrinth pick
with provider recorded — never a crash, never a fake.

Run: pyqt/.venv/Scripts/python pyqt/cf_degrade_test.py
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.providers.registry import build_providers  # noqa: E402
from engine.providers.settings import SettingsStore  # noqa: E402
from engine.shaders import choose_shader  # noqa: E402
from engine.resource_packs import choose_resource_pack  # noqa: E402
from engine.core import BuildLogger  # noqa: E402

failures = []


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


settings = SettingsStore()
key = settings.curseforge_key()
check("CF key configured (the stored one)", bool(key))
if not key:
    print("SKIP: no CF key configured")
    sys.exit(0)

# Build the exact provider set the pipeline uses (both sources, no direct CF).
providers = build_providers(settings, ["modrinth", "curseforge"])
cf = next((p for p in providers if p.name == "curseforge"), None)
check("curseforge provider present", cf is not None)
check("curseforge marked available (key set)", bool(cf and cf.available))

# The stored key is invalid — CF calls must raise a clear RuntimeError
# (not a generic scope error), and the visuals engines must survive it.
from engine.providers.curseforge import CurseForgeProvider  # noqa: E402
probe = CurseForgeProvider(api_key=key, allow_direct_downloads=False)
try:
    probe.search({"query": "complementary", "projectType": "shader", "minecraftVersion": "1.20.1", "limit": 3})
    check("broken CF key surfaces an error", False, "no error raised?!")
except RuntimeError as e:
    check("broken CF key -> clear RuntimeError", "CurseForge rejected" in str(e), str(e)[:100])
except Exception as e:  # noqa: BLE001
    check("broken CF key -> clear RuntimeError", False, f"wrong error type: {type(e).__name__}: {e}")

logger = BuildLogger("cf-degrade-probe", os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "workspace", "builds", "cf-degrade-probe"))

# choose_shader must fall back to Modrinth and record the real provider.
sh = choose_shader(providers, "1.20.1", "balanced", logger)
check("shader picked despite broken CF key", sh is not None,
      f"{sh['project']['title']}" if sh else "none")
if sh:
    check("shader provider recorded as modrinth", sh.get("provider") == "modrinth", sh.get("provider"))
    check("shader project is real", sh["project"].get("projectType") == "shader", sh["project"].get("projectType"))

# choose_resource_pack must do the same.
rp = choose_resource_pack(providers, "1.20.1", 32, ["medieval"], logger)
check("resource pack picked despite broken CF key", rp is not None,
      f"{rp['project']['title']}" if rp else "none")
if rp:
    check("resource pack provider recorded as modrinth", rp.get("provider") == "modrinth", rp.get("provider"))
    check("resource pack project is real", rp["project"].get("projectType") == "resourcepack",
          rp["project"].get("projectType"))

print("CF DEGRADE " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
