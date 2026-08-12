"""Bridge: exposes the in-process Python engine with the same method surface
views expect (so they work unchanged) plus the chat endpoint. Errors are
surfaced as ApiError for the UI.
"""
from __future__ import annotations

from typing import Any, Optional

import sys
from pathlib import Path

from .errors import ApiError  # noqa: E402
from .service import PyEngine as _Service  # noqa: E402


class PyEngine:
    """In-process engine with the Api-compatible surface."""

    def __init__(self, service: Optional[_Service] = None):
        self._s = service or _Service()

    # -- helpers ---------------------------------------------------------
    def _call(self, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiError:
            raise
        except Exception as e:  # noqa: BLE001
            raise ApiError(str(e)) from e

    def health(self) -> bool:
        try:
            return bool(self._s.health().get("ok"))
        except Exception:
            return False

    # -- builds ----------------------------------------------------------
    def builds(self) -> list[dict]:
        return self._s.builds()

    def build(self, build_id: str) -> dict:
        return self._call(self._s.build, build_id)

    def files(self, build_id: str) -> list[dict]:
        return self._s.files(build_id)

    def log(self, build_id: str, name: str) -> str:
        return self._s.log(build_id, name)

    def evidence(self, build_id: str, name: str) -> str:
        return self._s.evidence(build_id, name)

    def worlds(self, build_id: str) -> list[dict]:
        return self._s.worlds(build_id)

    def export_file(self, build_id: str, filename: str, dest: str) -> int:
        return self._call(self._s.export_file, build_id, filename, dest)

    def create_pack(self, name: str = "", mc: str = "auto", loader: str = "auto",
                    ram_gb: int = 8) -> dict:
        return self._s.create_pack(name, mc, loader, ram_gb)

    def start_build(self, req: dict) -> str:
        return self._call(self._s.start_build, req)

    def events(self, build_id: str, idle_timeout: float = 8.0):
        # idle_timeout kept for Api parity; the in-process stream is live.
        yield from self._s.events(build_id)

    def chat(self, prompt: str, build_id: str = "") -> dict:
        """AI chat edit: start a child build from the edited request."""
        return {"buildId": self._call(self._s.start_build, {"prompt": prompt, "parentBuildId": build_id or None})}

    # -- pack identity / snapshots / LKG / AI change plans --------------
    def identity(self, build_id: str) -> dict:
        return self._s.identity(build_id)

    def set_identity(self, build_id: str, patch: dict) -> dict:
        return self._s.set_identity(build_id, patch)

    def snapshots(self, build_id: str) -> list:
        return self._s.snapshots(build_id)

    def create_snapshot(self, build_id: str, label: str, kind: str = "manual") -> dict:
        return self._s.create_snapshot(build_id, label, kind)

    def restore_snapshot(self, build_id: str, snapshot_id: str, label: str = "") -> dict:
        return self._s.restore_snapshot(build_id, snapshot_id, label)

    def last_known_good(self, build_id: str) -> dict | None:
        return self._s.last_known_good(build_id)

    def restore_last_known_good(self, build_id: str) -> dict:
        return self._s.restore_last_known_good(build_id)

    def plan_ai_change(self, build_id: str, prompt: str) -> dict:
        return self._s.plan_ai_change(build_id, prompt)

    def pack_health(self, build_id: str) -> dict:
        return self._s.pack_health(build_id)

    def check_pack_updates(self, build_id: str, limit: int = 40) -> dict:
        return self._s.check_pack_updates(build_id, limit)

    def apply_ai_change(self, build_id: str, prompt: str) -> dict:
        return self._s.apply_ai_change(build_id, prompt)

    # -- launcher --------------------------------------------------------
    def play(self, build_id: str, username: Optional[str] = None,
             auth: Optional[dict] = None, auto_launch: bool = False) -> dict:
        return self._call(self._s.play, build_id, username, auth, auto_launch)

    def stop(self, build_id: str) -> dict:
        return self._s.stop(build_id)

    def status(self, build_id: str) -> dict:
        return self._s.status(build_id)

    def fix(self, build_id: str, username: Optional[str] = None,
            auth: Optional[dict] = None) -> dict:
        return self._call(self._s.fix, build_id, username, auth)

    def add_missing(self, build_id: str, mods: Optional[list[str]] = None,
                    username: Optional[str] = None, auth: Optional[dict] = None) -> dict:
        return self._call(self._s.add_missing, build_id, mods, username, auth)

    def backup(self, build_id: str) -> dict:
        return self._s.backup(build_id)

    def game_log_stream(self, build_id: str, idle_timeout: float = 6.0):
        yield from self._s.game_log_stream(build_id)

    # -- mod browser -----------------------------------------------------
    def search(self, q: str = "", provider: str = "modrinth", mc: Optional[str] = None,
               loader: Optional[str] = None, type: str = "mod", offset: int = 0,
               page_size: int = 48, sort: str = "downloads") -> dict:
        return self._s.search(q, provider, mc, loader, type, offset, page_size, sort)

    def project_details(self, provider: str, project_id: str, mc: Optional[str] = None,
                        loader: Optional[str] = None) -> dict:
        return self._s.project_details(provider, project_id, mc, loader)

    def provider_status(self, probe: bool = False) -> dict:
        return self._s.provider_status(probe)

    def add_mod(self, build_id: str, provider: str, project_id: str,
                version_id: Optional[str] = None, type: Optional[str] = None) -> dict:
        return self._call(self._s.add_mod, build_id, provider, project_id, version_id, type)

    def remove_mod(self, build_id: str, slug: str, type: Optional[str] = None) -> dict:
        return self._s.remove_mod(build_id, slug, type)

    def retest(self, build_id: str) -> dict:
        return self._s.retest(build_id)

    def rename(self, build_id: str, name: str) -> dict:
        return self._s.rename(build_id, name)

    def set_ram(self, build_id: str, ram_gb: int) -> dict:
        return self._s.set_ram(build_id, ram_gb)

    def set_auto_relaunch(self, build_id: str, enabled: bool) -> dict:
        return self._s.set_auto_relaunch(build_id, enabled)

    def set_shader_preset(self, build_id: str, preset: str) -> dict:
        return self._call(self._s.set_shader_preset, build_id, preset)

    def delete_pack(self, build_id: str) -> dict:
        return self._call(self._s.delete_pack, build_id)

    # -- import ----------------------------------------------------------
    def import_pack(self, provider: str, project_id: str, version_id: Optional[str] = None,
                    progress=None, cancel=None) -> dict:
        return self._call(self._s.import_pack, provider, project_id, version_id,
                          progress, cancel)

    def import_file(self, local_path: str, name: Optional[str] = None,
                    progress=None, cancel=None) -> dict:
        return self._call(self._s.import_file, local_path, name, progress, cancel)

    # -- hardware & settings ---------------------------------------------
    def hardware(self) -> dict:
        return self._s.hardware()

    def hardware_refresh(self) -> dict:
        return self._s.hardware_refresh()

    def settings_get(self) -> dict:
        return self._s.settings_get()

    def settings_post(self, patch: dict) -> dict:
        return self._s.settings_post(patch)
