"""Provider HTTP: disk cache (TTL'd) + memory cache + in-flight dedupe.

Port of src/providers/http.ts. Real provider responses are cached so repeated
builds don't hammer APIs; set AMB_NO_CACHE=1 or AMB_CACHE_TTL_SECONDS to tune.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

from ..core import cache_dir, mkdirp, retry_fetch

_cache_root = cache_dir() / "providers"
_memory_cache: dict[str, dict] = {}
_in_flight: dict[str, Any] = {}
_lock = threading.Lock()
_MAX_MEMORY_ENTRIES = 256


def _cache_ttl_seconds() -> int:
    if os.environ.get("AMB_NO_CACHE"):
        return 0
    try:
        v = int(os.environ.get("AMB_CACHE_TTL_SECONDS", ""))
        if v > 0:
            return v
    except ValueError:
        pass
    return 6 * 3600


def provider_get(provider: str, url: str, headers: Optional[dict] = None,
                 cache: bool = True) -> Any:
    headers = headers or {}
    ttl = _cache_ttl_seconds()
    if ttl <= 0 or not cache:
        return retry_fetch(url, headers=headers)

    # Digest only — credentials never touch filenames or the cached response.
    key = hashlib.sha1(f"{provider}\0{url}\0{json.dumps(headers)}".encode()).hexdigest()
    with _lock:
        mem = _memory_cache.get(key)
        if mem and mem["expiresAt"] > time.time() * 1000:
            return mem["data"]
        pending = _in_flight.get(key)
    if pending:
        return pending

    path = _cache_root / provider / key[:2] / (key + ".json")

    def request() -> Any:
        try:
            if path.exists() and time.time() - path.stat().st_mtime < ttl:
                data = json.loads(path.read_text("utf-8"))
                _remember(key, data, path.stat().st_mtime + ttl)
                return data
        except Exception:
            pass
        try:
            data = retry_fetch(url, headers=headers)
            try:
                mkdirp(path.parent)
                path.write_text(json.dumps(data), "utf-8")
            except OSError:
                pass
            _remember(key, data, time.time() * 1000 + ttl * 1000)
            return data
        except Exception as e:
            # Serve stale cache if network failed (graceful degradation).
            try:
                data = json.loads(path.read_text("utf-8"))
                _remember(key, data, time.time() * 1000 + min(60, ttl) * 1000)
                return data
            except Exception:
                raise e

    with _lock:
        _in_flight[key] = request
    try:
        return request()
    finally:
        with _lock:
            _in_flight.pop(key, None)


def _remember(key: str, data: Any, expires_at: float) -> None:
    with _lock:
        _memory_cache[key] = {"expiresAt": expires_at, "data": data}
        while len(_memory_cache) > _MAX_MEMORY_ENTRIES:
            _memory_cache.pop(next(iter(_memory_cache)), None)


def clear_provider_cache() -> None:
    import shutil
    with _lock:
        _memory_cache.clear()
        _in_flight.clear()
    shutil.rmtree(_cache_root, ignore_errors=True)
