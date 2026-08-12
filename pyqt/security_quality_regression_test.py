"""Focused regressions for the implementation-council security/truth fixes."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import updater
from engine import downloads, service
from engine.providers.settings import SettingsStore
from engine.interpreter import interpret
from engine.rank import rank_candidate


checks = []


def check(name, condition, detail=""):
    checks.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


class Logger:
    def stage(self, *_): pass
    def info(self, *_): pass
    def warn(self, *_): pass
    def ok(self, *_): pass


# Updater policy: production rejects insecure URLs and missing hashes.
with mock.patch.dict(os.environ, {}, clear=False):
    os.environ.pop("AMB_UPDATE_ALLOW_INSECURE", None)
    try:
        updater._validate_url("http://example.com/update.json")
        rejected_http = False
    except ValueError:
        rejected_http = True
check("updater rejects production HTTP", rejected_http)

try:
    updater._validate_sha256("")
    rejected_empty_hash = False
except ValueError:
    rejected_empty_hash = True
check("updater requires a 64-hex SHA-256", rejected_empty_hash)

with tempfile.TemporaryDirectory() as td:
    root = Path(td)
    payload = root / "setup.exe"
    payload.write_bytes(b"signed-test-payload")
    digest = hashlib.sha256(payload.read_bytes()).hexdigest()
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        got = updater.download(payload.as_uri(), root / "out", digest)
    check("dev file update remains testable with valid hash", got.read_bytes() == payload.read_bytes())

# Cached jars are not trusted blindly.
with tempfile.TemporaryDirectory() as td:
    good = b"provider-approved-jar"
    node = {"selected": True, "key": "modrinth:test", "project": {"slug": "test", "title": "Test"},
            "version": {"versionId": "v1", "versionNumber": "1", "files": [{
                "primary": True, "url": "https://example.invalid/test.jar", "size": len(good),
                "hashes": {"sha1": hashlib.sha1(good).hexdigest()}}]}}
    mods = Path(td) / "mods"
    mods.mkdir()
    cached = mods / "test-1.jar"
    cached.write_bytes(b"tampered")
    calls = []
    def fake_download(_url, dest, **_kwargs):
        calls.append(True)
        Path(dest).write_bytes(good)
    with mock.patch.object(downloads, "download_to_file", fake_download):
        result = downloads.download_pack_files([node], td, {"logger": Logger(), "maxTotalDownloadMB": 1})
    check("tampered cached jar is deleted and redownloaded", bool(calls) and result["records"][0]["status"] == "ok")

# Configured budget key controls behavior.
with tempfile.TemporaryDirectory() as td:
    node = {"selected": True, "key": "modrinth:large", "project": {"slug": "large", "title": "Large"},
            "version": {"versionId": "v1", "versionNumber": "1", "files": [{
                "primary": True, "url": "https://example.invalid/large.jar", "size": 2 * 1024 * 1024}]}}
    result = downloads.download_pack_files([node], td, {"logger": Logger(), "maxTotalDownloadMB": 1})
    check("maxTotalDownloadMB enforces the configured budget", result["records"][0]["status"] == "skipped")

# Record serialization strips the key, including historical-shaped nested data.
class SecretSettings:
    path = "missing"
    def load(self): return {"curseforgeApiKey": "MARKER-SECRET-DO-NOT-PERSIST", "build": {}}
    def curseforge_key(self): return "MARKER-SECRET-DO-NOT-PERSIST"
    def mtime(self): return 0

with tempfile.TemporaryDirectory() as td, mock.patch.object(service, "builds_dir", lambda: Path(td)):
    eng = service.PyEngine(SecretSettings())
    rec = {"buildId": "b-test", "settings": SecretSettings().load(), "requirements": {}, "packStats": {}}
    (Path(td) / "b-test").mkdir()
    eng._write_record(rec)
    raw = (Path(td) / "b-test" / "build.json").read_text("utf-8")
check("CurseForge marker secret never enters build records", "MARKER-SECRET" not in raw)

with tempfile.TemporaryDirectory() as td:
    store = SettingsStore(str(Path(td) / "settings.json"))
    with mock.patch.object(store, "_save_key") as save_key, \
            mock.patch.object(store, "clear_curseforge_key") as clear_key, \
            mock.patch.object(store, "curseforge_key", return_value=""):
        eng = service.PyEngine(store)
        eng.settings_post({"curseforgeApiKey": ""})
    check("clearing the CurseForge key removes secure storage",
          clear_key.call_count == 1 and save_key.call_count == 0)

# Interpreter is conservative and truthful.
surprise = interpret("surprise me")["requirements"]
check("vague surprise request asks for clarification", surprise["needsClarification"] and not surprise["features"])
cozy = interpret("a cozy farming pack with no combat")["requirements"]
check("cozy farming keeps narrow targets and excludes combat",
      [f["id"] for f in cozy["features"]] == ["food"] and cozy["features"][0]["targetCount"] < 10)
unsupported = interpret("Minecraft 1.21.10 Fabric magic")["requirements"]
check("unsupported version is preserved and warned", unsupported["minecraftVersion"] == "1.21.10" and unsupported["unsupportedMinecraftVersion"] == "1.21.10")
absurd = interpret("make me 5000 mods")["requirements"]
check("absurd mod count is capped with warning", absurd["targetModCount"] == 200 and bool(absurd["warnings"]))

# Ranking: theme words cannot make an unrelated feature relevant; factors explain score.
project = {"title": "Arcane Spellbook", "slug": "arcane-spellbook", "description": "magic", "categories": ["magic"],
           "downloads": 100000, "dateModified": "2026-08-01", "projectType": "mod"}
feature = {"id": "food", "keywords": ["farming", "food"], "categoryTags": ["food"]}
ranked = rank_candidate(project, feature, {"theme": ["fantasy"], "minecraftVersion": "1.20.1", "loader": "fabric"})
check("global theme cannot make unrelated feature candidate relevant", ranked["score"] == 0)
check("rank factors sum to displayed score", round(sum(f["score"] for f in ranked["factors"]), 1) == ranked["score"])

failed = [name for name, ok in checks if not ok]
print(f"\n{len(checks) - len(failed)}/{len(checks)} checks passed")
raise SystemExit(1 if failed else 0)
