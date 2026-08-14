"""Shader-preset swap test (Pack Detail control -> engine).

Verifies set_shader_preset end to end WITHOUT a full game launch:
- picks a REAL shader pack for the requested preset (live provider),
- downloads the zip into the build downloads dir,
- marks the old shader deselected and appends the new selection with provider,
- installs the zip into the instance shaderpacks/ and removes the old one,
- records shaderChoice with provider + honest preset reason,
- kicks off a retest thread (real launch validated separately by deep tests).

Run: pyqt/.venv/Scripts/python pyqt/shader_swap_test.py
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "engine"))

from engine.service import PyEngine  # noqa: E402
from engine.providers.registry import build_providers  # noqa: E402
from engine.providers.settings import SettingsStore  # noqa: E402
from engine.core import builds_dir  # noqa: E402

failures = []


def json_dump(o) -> str:
    import json
    try:
        return json.dumps(o)[:160]
    except Exception:  # noqa: BLE001
        return str(o)[:160]


def check(name: str, cond: bool, extra: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    if not cond:
        failures.append(name)
    print(f"[{tag}] {name}" + (f" — {extra}" if extra else ""))


# --- providers must be live (real Modrinth) for a REAL shader pick ---
providers = build_providers(SettingsStore(), ["modrinth"])
live = any(p.available for p in providers)
check("modrinth provider available", live)
if not live:
    print("SKIP: no live provider")
    sys.exit(1)

eng = PyEngine()
name = f"ShaderSwapTest-{int(time.time())}"
created = eng.create_pack(name, "1.20.1", "fabric", 8)
build_id = created["buildId"]
check("pack created", bool(build_id), build_id)

# install a real mod + shader seed so the record looks like a built pack
eng.add_mod(build_id, "modrinth", "appleskin")
rec = eng.build(build_id)
check("pack has selections", bool(rec.get("selections")), f"{len(rec.get('selections') or [])} selections")

# fake a previous shader selection (what a visuals-stage build would record)
rec["selections"].append({
    "key": "shader:modrinth:old", "provider": "modrinth", "projectId": "OLD",
    "slug": "old-shader", "title": "Old Shader", "projectType": "shader",
    "downloadPath": "OLD", "selected": True,
})
rec["shaderChoice"] = {"preset": "performance", "gpuTier": "integrated",
                       "provider": "modrinth", "slug": "old-shader",
                       "title": "Old Shader", "reason": "old"}
from engine.core import write_json_file as _wjf  # noqa: E402
rec_path = builds_dir() / build_id / "build.json"
_wjf(rec_path, rec)

# --- retest wiring: patch run_test_level to a fast PASS BEFORE the swap so
# --- the scheduled retest consumes the patched fn (a real launch is validated
# --- by the deep tests; here we only prove the swap schedules a retest that
# --- carries the new shader files into the test env).
import engine.service as _svc  # noqa: E402
_captured = {}

def _fake_test(env, graph):
    _captured["env"] = env
    return {"level": env.get("testMode"), "status": "PASS", "startedAt": "x",
            "finishedAt": "y", "phases": [{"name": "instance", "status": "PASS",
                                              "detail": "patched for unit test"}],
            "summary": "patched"}

_svc.run_test_level = _fake_test

# --- the swap ---
res = eng.set_shader_preset(build_id, "performance")
check("swap returns a real shader title", bool(res.get("title")), str(res.get("title")))
check("swap records provider", res.get("provider") == "modrinth", res.get("provider"))
check("preset honored", res.get("preset") == "performance", res.get("preset"))

rec = eng.build(build_id)
sc = rec.get("shaderChoice") or {}
check("shaderChoice has title + provider", bool(sc.get("title")) and sc.get("provider") == "modrinth",
      json_dump(sc))

sels = [s for s in (rec.get("selections") or []) if s.get("projectType") == "shader"]
new_shaders = [s for s in sels if s.get("selected", True)]
old_shaders = [s for s in sels if not s.get("selected", True)]
check("old shader deselected", len(old_shaders) == 1, json_dump(old_shaders[0] if old_shaders else None))
check("exactly one new shader selected", len(new_shaders) == 1, json_dump(new_shaders[0] if new_shaders else None))
ns = new_shaders[0] if new_shaders else {}
check("new shader has real download path", bool(ns.get("downloadPath")) and os.path.exists(ns["downloadPath"]),
      ns.get("downloadPath", ""))
check("new shader is a zip", ns.get("downloadPath", "").lower().endswith(".zip"), ns.get("downloadPath", ""))

# --- instance install: shaderpacks/ has the zip, old one gone ---
inst_dir = eng._build_dir(build_id) / "instance" / "minecraft" / "shaderpacks"
files = [f.name for f in inst_dir.iterdir()] if inst_dir.is_dir() else []
check("shader zip installed into shaderpacks/", any(f.lower().endswith(".zip") for f in files),
      str(files))

# --- requirements now flag shaders on ---
req = rec.get("requirements") or {}
check("requirements.shaders set", bool(req.get("shaders")))
check("requirements.shaderQuality set", req.get("shaderQuality") == "performance", str(req.get("shaderQuality")))

# give the async retest thread a moment to consume the patched fn. The
# swap writes testResult.status="TESTING" synchronously, so the poll must
# wait for a NON-TESTING status — checking for the mere presence of
# testResult exits on the first read (the bug this loop fixes).
import threading as _th  # noqa: F401
_deadline = time.time() + 20
while time.time() < _deadline:
    rec = eng.build(build_id)
    _st = (rec.get("testResult") or {}).get("status")
    if _st not in (None, "TESTING"):
        break
    time.sleep(0.25)
check("retest ran and recorded a result", (rec.get("testResult") or {}).get("status") == "PASS",
      json_dump((rec.get("testResult") or {}).get("status")))
env = _captured.get("env") or {}
check("retest env carries the NEW shader file",
      any("ShaderSwapTest" in str(s) or s.lower().endswith(".zip") for s in (env.get("shaderFiles") or [])),
      json_dump((env.get("shaderFiles") or [])[:2]))

# cleanup
try:
    eng.delete_pack(build_id)
    check("test pack cleaned up", True)
except Exception as e:  # noqa: BLE001
    check("test pack cleaned up", False, str(e))

print("SHADER SWAP " + ("PASS" if not failures else "FAIL"))
sys.exit(1 if failures else 0)
