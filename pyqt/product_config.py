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

# Single source of truth for the shipped build version. The installer
# pipeline (pyqt/build_installer.py) reads this for the Inno Setup
# MyAppVersion define, and the self-updater compares it against the update
# feed. Bump it for every release.
APP_VERSION = "1.0.5"
