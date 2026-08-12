"""Provider registry — Python port of src/providers/registry.ts."""
from __future__ import annotations

from typing import Optional

from .curseforge import CurseForgeProvider
from .modrinth import ModrinthProvider
from .settings import SettingsStore


def build_providers(settings: SettingsStore, sources: Optional[list[str]] = None,
                    opts: Optional[dict] = None) -> list:
    cfg = settings.load()
    wanted = set(sources if sources is not None else (cfg.get("build") or {}).get("sources") or ["modrinth"])
    providers = []
    if "modrinth" in wanted:
        providers.append(ModrinthProvider())
    if "curseforge" in wanted:
        key = settings.curseforge_key()
        # allowCfDirect: used ONLY by the manual Mod Browser add flow (single
        # machine use) via CF's signed download-url endpoint. The build
        # pipeline never sets it.
        providers.append(CurseForgeProvider(
            api_key=key,
            allow_direct_downloads=bool((opts or {}).get("allowCfDirect")),
        ))
    return providers
