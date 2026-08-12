"""Settings store — Python port of src/providers/settings.ts.

Persisted to workspace/config/settings.json. The CurseForge API key is never
logged; the CF_API_KEY environment variable takes precedence over the file.
"""
from __future__ import annotations

import os
import ctypes
from ctypes import wintypes
from copy import deepcopy
from typing import Any, Optional

from ..core import config_dir, mkdirp, read_json_file, write_json_file

DEFAULTS: dict = {
    "curseforgeApiKey": "",
    "build": {
        "sources": ["modrinth"],
        "content": {"mods": True, "resourcePacks": True, "shaders": False, "performanceMods": True},
        "maxTotalDownloadMB": 600,
        "budgetPinned": False,
        "downloadAssets": False,
        "maxAssetMB": 400,
        "autoInstallJava": True,
        "repairMode": "standard",
        "serverPack": False,
    },
    "defaults": {
        "minecraftVersion": "auto",
        "loader": "auto",
        "packSize": "medium",
        "ramGB": 8,
        "testMode": "standard",
        "multiplayer": False,
        "serverPack": False,
        "sources": ["modrinth"],
    },
    "performance": {"cpu": "auto", "gpu": "auto", "ramGB": 0, "os": "auto", "targetFps": 60, "resolution": "1920x1080"},
}


def _deep_merge(base: Any, patch: Any) -> Any:
    if patch is None or not isinstance(patch, dict):
        return patch if patch is not None else base
    out = deepcopy(base) if isinstance(base, dict) else {}
    for k, v in patch.items():
        bv = out.get(k) if isinstance(out, dict) else None
        out[k] = _deep_merge(bv, v) if isinstance(v, dict) and isinstance(bv, dict) else deepcopy(v)
    return out


class SettingsStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or str(config_dir() / "settings.json")

    def mtime(self) -> float:
        """Settings file mtime (0 when absent) — cheap change detector so
        callers can cache parsed settings without re-reading on every call."""
        try:
            return os.path.getmtime(self.path)
        except OSError:
            return 0.0

    def load(self) -> dict:
        raw = read_json_file(self.path)
        if isinstance(raw, dict) and raw.get("curseforgeApiKey"):
            # Migrate legacy plaintext immediately, then remove it from JSON.
            self._save_key(str(raw["curseforgeApiKey"]))
            raw["curseforgeApiKey"] = ""
            write_json_file(self.path, raw)
        merged = _deep_merge(DEFAULTS, raw or {})
        perf = merged.get("performance") or {}
        if (not perf.get("cpu") or perf.get("cpu") == "auto") and \
           (not perf.get("gpu") or perf.get("gpu") == "auto") and \
           (not perf.get("os") or perf.get("os") == "auto") and \
           (perf.get("ramGB") == 8 or not perf.get("ramGB")):
            perf = {**perf, "ramGB": 0}
        merged["performance"] = perf
        return merged

    def save(self, s: dict) -> None:
        from ..core import mkdirp as _mkdirp
        _mkdirp(os.path.dirname(self.path) if isinstance(self.path, str) else self.path.parent)
        clean = deepcopy(s)
        key = str(clean.get("curseforgeApiKey") or "")
        if key and "•" not in key:
            self._save_key(key)
        clean["curseforgeApiKey"] = ""
        write_json_file(self.path, clean)

    def clear_curseforge_key(self) -> None:
        """Remove the protected local key; environment configuration is untouched."""
        try:
            os.unlink(self._key_path())
        except FileNotFoundError:
            pass

    def curseforge_key(self) -> str:
        return os.environ.get("CF_API_KEY") or self._load_key()

    def _key_path(self):
        return os.path.join(os.path.dirname(str(self.path)), "curseforge-key.dpapi")

    def _save_key(self, key: str) -> None:
        if os.name != "nt":
            raise RuntimeError("Secure CurseForge key storage is available on Windows only; use CF_API_KEY")
        protected = _dpapi(key.encode("utf-8"), protect=True)
        target = self._key_path()
        mkdirp(os.path.dirname(target))
        temporary = target + ".tmp"
        with open(temporary, "wb") as stream:
            stream.write(protected)
        os.replace(temporary, target)

    def _load_key(self) -> str:
        try:
            with open(self._key_path(), "rb") as stream:
                return _dpapi(stream.read(), protect=False).decode("utf-8")
        except FileNotFoundError:
            return ""
        except Exception:
            return ""


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    buf = ctypes.create_string_buffer(data)
    incoming = _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    entropy_buf = ctypes.create_string_buffer(b"AI Modpack Builder CurseForge key v1")
    entropy = _Blob(len(entropy_buf.raw) - 1, ctypes.cast(entropy_buf, ctypes.POINTER(ctypes.c_ubyte)))
    outgoing = _Blob()
    fn = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not fn(ctypes.byref(incoming), "AI Modpack Builder" if protect else None,
              ctypes.byref(entropy), None, None, 0x1, ctypes.byref(outgoing)):
        raise OSError("Windows could not protect the CurseForge key")
    try:
        return ctypes.string_at(outgoing.pbData, outgoing.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(outgoing.pbData)
