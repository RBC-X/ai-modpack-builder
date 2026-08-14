"""Publisher-owned settings embedded in distributable launcher builds.

End users never configure these values.  Set MICROSOFT_CLIENT_ID to the
approved public-client application id assigned to AI Modpack Builder before
shipping a Microsoft-enabled build.  The environment override is for local
development and release pipelines only.
"""
from __future__ import annotations

import os


# Release engineers replace this only with the approved publisher-owned public
# client id. The environment override remains a development/build hook.
EMBEDDED_MICROSOFT_CLIENT_ID = ""
MICROSOFT_CLIENT_ID = os.environ.get("MINECRAFT_CLIENT_ID", EMBEDDED_MICROSOFT_CLIENT_ID).strip()

# Publisher-owned CurseForge API key baked into released installer builds so
# end users never configure one (Modrinth needs no key at all — its API is
# open). Resolution order in the engine: CF_API_KEY env -> per-user Windows
# DPAPI store (Settings page) -> this embedded default.
#
# NEVER commit a live key here: this file is tracked, so the committed value
# is always empty. build_installer.py generates the git-ignored pyqt/_amb_secrets.py
# containing the literal key before invoking PyInstaller, so only the frozen
# bundle carries it (an env var alone would NOT survive into the frozen app —
# os.environ is read at runtime, not bake time).
def _embedded_cf_key() -> str:
    env_key = os.environ.get("AMB_EMBEDDED_CURSEFORGE_KEY", "").strip()
    if env_key:
        return env_key
    try:
        from _amb_secrets import CURSEFORGE_KEY  # type: ignore[import-not-found]
        return (CURSEFORGE_KEY or "").strip()
    except Exception:  # noqa: BLE001 — dev trees / fresh clones have no secrets module
        return ""


EMBEDDED_CURSEFORGE_KEY = _embedded_cf_key()

# Single source of truth for the shipped build version. The installer
# pipeline (pyqt/build_installer.py) reads this for the Inno Setup
# MyAppVersion define, and the self-updater compares it against the update
# feed. Bump it for every release.
APP_VERSION = "1.0.26"

# Default self-update feed for installed builds. Fresh installs auto-point
# at this HTTPS feed (Settings → Updates prefills it; the startup check and
# --check-update use it too), so end users never configure anything.
# AMB_UPDATE_URL still wins as an environment override.
DEFAULT_UPDATE_FEED_URL = "https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json"

# Human-readable source label reported to the Settings UI for the key above.
EMBEDDED_KEY_SOURCE_LABEL = "built-in"
