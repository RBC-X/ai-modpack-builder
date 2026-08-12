"""Regression: CurseForge key resolution chain and source labels.

Chain: CF_API_KEY env -> per-user Windows DPAPI store -> publisher-embedded
default (baked into installer builds). Modrinth needs no key (open API) and is
out of scope here. Network-free: the provider is never constructed.
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent / "engine"))

import engine.providers.settings as settings_mod  # noqa: E402
from engine.providers.settings import SettingsStore  # noqa: E402

checks = []
def check(name: str, ok: bool, detail: str = "") -> None:
    checks.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))

def patch_embedded(key: str):
    settings_mod._embedded_curseforge_key = lambda: key

def patch_dpapi(store: SettingsStore, key: str):
    store._load_key = lambda: key

with tempfile.TemporaryDirectory() as td:
    store = SettingsStore(path=str(Path(td) / "settings.json"))
    old_env = os.environ.get("CF_API_KEY")
    os.environ.pop("CF_API_KEY", None)

    # 1. Embedded default is used when nothing else is configured.
    patch_embedded("EMBEDDED-KEY")
    patch_dpapi(store, "")
    got = store.curseforge_key()
    check("embedded default resolves when no env or per-user key", got == "EMBEDDED-KEY", got)
    check("source is 'built-in'", store.curseforge_key_source() == "built-in", store.curseforge_key_source())

    # 2. Per-user DPAPI wins over the embedded default.
    patch_embedded("EMBEDDED-KEY")
    patch_dpapi(store, "USER-KEY")
    got = store.curseforge_key()
    check("per-user key wins over embedded", got == "USER-KEY", got)
    check("source is 'windows-secure-storage'",
          store.curseforge_key_source() == "windows-secure-storage", store.curseforge_key_source())

    # 3. Environment wins over everything.
    os.environ["CF_API_KEY"] = "ENV-KEY"
    got = store.curseforge_key()
    check("environment wins over per-user and embedded", got == "ENV-KEY", got)
    check("source is 'environment'", store.curseforge_key_source() == "environment", store.curseforge_key_source())
    os.environ.pop("CF_API_KEY", None)

    # 4. Nothing configured -> empty + 'none'.
    patch_embedded("")
    patch_dpapi(store, "")
    check("no key anywhere -> empty", store.curseforge_key() == "", store.curseforge_key())
    check("source is 'none'", store.curseforge_key_source() == "none", store.curseforge_key_source())

    if old_env is not None:
        os.environ["CF_API_KEY"] = old_env

ok = all(checks)
print("EMBEDDED KEY PASS" if ok else "EMBEDDED KEY FAIL")
sys.exit(0 if ok else 1)
