# AI Modpack Builder (PyQt6)

A native desktop client for the **AI Modpack Builder** engine, ported from the
React/Tailwind launcher design (`ai-minecraft-launcher.zip`).

The launcher is a **frontend for the real engine** — every number you see comes
from the engine itself (real provider searches, real builds, real downloads,
real crash evidence, real exports). There is no mock data and no fake progress.

Since 2026-08-10 the engine **runs inside the app** — the full engine lives in
`pyqt/engine/` (Python) and runs in-process, so the launcher is one
self-contained system: no Node server, no localhost, no second process. The
legacy Node/TypeScript engine (`src/`), the old web UI (`web/`) and the HTTP
client (`api.py`) were deleted on 2026-08-11 — the Python engine is the only
code path.

## Screens

| Screen | What it shows |
| --- | --- |
| Home | Hero card for the selected pack, recently played, hardware recommendation |
| Library | All packs with search / loader filter / sort, grid & list views; **NEW PACK** builds your own blank pack (name, MC version, loader, RAM); trash button deletes a pack (confirmed, refused while running) |
| Pack Detail | Overview (specs, repairs, config changes), Content (mods + visuals, add/remove/retest), Worlds (real saves on disk), Logs (live console + real log files), Settings (RAM, exports, rename) |
| Discover | Real Modrinth/CurseForge search — image-backed cards, provider screenshot gallery, popular browse, content/loader/MC filters, target-pack compatibility and exact version selection before Add/Install |
| AI Builder | Real build pipeline with a **live SSE step stream** (interpret → search → select → resolve → conflict → download → test → export) |
| Downloads | Real download records from your builds (files, sizes, verification) |
| Activity | Engine event feed, crash reports with real evidence files, AI repair history |
| Settings | Hardware detection + re-detect, RAM/FPS/resolution, masked CurseForge API key setup + live connection test, additive build sources & budget, repair mode, Microsoft/Java account management |

Floating overlays:

- **Launch progress** — live status while a pack starts (progress %, stage,
  mods loaded, log tail), running state with STOP, and a crashed state that
  opens the crash drawer.
- **Crash drawer** — the AI diagnosis, missing-dependency chips, **Add Missing
  Mods & Relaunch** (real repair through the providers), and the raw crash
  report file. Unknown crashes are attributed to the mod whose class is on the
  real stack trace (jar class index), not guessed by priority.
- **Import modpack** — provider-based import (Modrinth/CurseForge pack id or
  slug) using the engine's real `.mrpack`/manifest resolution.

## Run

From the project root (no engine to start — it is inside the app):

```bash
python -m venv pyqt/.venv
pyqt/.venv/Scripts/pip install -r pyqt/requirements.txt   # PyQt6
pyqt/.venv/Scripts/python pyqt/main.py
```

The Python engine boots with the app: real hardware detection, live Modrinth
searches, real builds, real launches.

**One-click desktop launcher (Windows):** double-click
`pyqt/run-app.bat` (or the pinned `AI Modpack Builder` taskbar/desktop
shortcut) — it opens the app with `pythonw` (no console, no browser).

If the engine were unhealthy, the pill shows **Offline** with an automatic
restart countdown instead of pretending.

## Verify

All verification runs against the **in-process engine** — no server needed:

```bash
pyqt/.venv/Scripts/python pyqt/engine_self_test.py  # 18/18 engine pipeline checks (live Modrinth)
pyqt/.venv/Scripts/python pyqt/inprocess_test.py    # launcher runs entirely in-process
pyqt/.venv/Scripts/python pyqt/one_system_test.py   # one-system verification (no port, no subprocess)
pyqt/.venv/Scripts/python pyqt/smoke_test.py        # headless: all views + live data
pyqt/.venv/Scripts/python pyqt/screenshot.py        # renders pyqt/screenshots/*.png
pyqt/.venv/Scripts/python pyqt/live_build_test.py   # real small instant build end-to-end
pyqt/.venv/Scripts/python pyqt/live_launch_test.py <buildId>  # real game boot -> STOP
pyqt/.venv/Scripts/python pyqt/crash_repair_test.py <buildId> <dep>  # crash -> add missing -> relaunch
```

## Microsoft account setup

Open the account control in the top bar or sidebar and select **Sign in with
Microsoft**. The normal Microsoft account picker opens in your system browser
and returns to the launcher automatically; there is no device code to copy and
the launcher never receives your password. The launcher uses authorization
code flow with PKCE and a temporary localhost callback.

The distributable launcher still needs its own publisher-owned Microsoft
application (client) ID, embedded in `product_config.py` by the release build
(the `MINECRAFT_CLIENT_ID` environment variable is supported for development).
Players are never asked to supply it. The app registration must support personal Microsoft accounts, the
`http://localhost` mobile/desktop redirect, public client flow, and the
`XboxLive.signin` permission required for Minecraft. Microsoft may require
launcher app registrations to be approved.

After Minecraft ownership and the Java profile are verified, the refresh
credential is encrypted with Windows DPAPI. Each Play, repair-and-relaunch, and
add-missing-and-relaunch operation uses the selected Microsoft profile. Offline
profiles remain available for local testing.

## Notes & honest limitations
- **Local import** is supported: the Import modal has a local-file tab (browse
  + drag & drop) that uploads a `.mrpack`/CurseForge zip to
  `POST /api/importfile` — no provider project id needed.
- **RAM edits** apply live via `POST /api/builds/:id/ram`; the Pack Detail
  Settings tab has a slider wired to it.
- **Save Pack** (`POST /api/builds/:id/backup`) zips worlds + configs +
  visuals into an export; the Settings tab has a Save Pack button.
- **Live game logs**: the Pack Detail Logs tab streams `latest.log` + the
  launcher console over SSE (`GET /api/play/:id/log`) — no polling; it falls
  back to the status tail if the stream drops.
- **One game at a time**: the engine rejects a second launch while any pack
  is running (clear message naming the running pack); the app warns first.
- Build steps stream live during a build via SSE; for already-finished packs
  the timeline is reconstructed from the record (the engine keeps only recent
  event history in memory).
- CurseForge uses the official `x-api-key` flow. The saved secret is never sent
  back to the PyQt renderer; enter it locally under **Settings → API Providers**
  or use `CF_API_KEY`. Modrinth remains available without a key.
- Provider responses use bounded memory/disk caching with in-flight request
  de-duplication. Project artwork has its own six-worker, persistent image
  cache so scrolling and repeat searches do not block the UI thread.

## Verified live (2026-08-09)

- `pyqt/smoke_test.py` — all views construct and render live data, provider
  imagery, masked credentials, and selected-pack compatibility checks.
- `pyqt/live_launch_test.py` — drives the real `MainWindow.play()` on a live
  Forge 1.20.1 pack: overlay starting → engine progress (36% installing → 82%
  → 92%) → main menu at 100% with the overlay showing "Main menu reached —
  ready to play" → STOP terminates the instance. The account profile name
  flowed into the real launch (`--username Test_Player`).
- `pyqt/crash_repair_test.py` — the full user-facing repair loop on a real
  pack broken on purpose (a required dependency dropped from its record):
  launch → mixin `ClassMetadataNotFoundException` crash (no crash-report file
  exists, so the launcher-console root cause is parsed) → crash drawer shows
  the missing-mod pill (`almanac`) → Add Missing Mods & Relaunch → engine
  re-resolves and installs the mod → game reaches the main menu → STOP.
- Second-pack guard and the SSE game-log stream were verified live against
  the running engine; `pyqt/run-app.bat` + the pinned taskbar shortcut were
  exercised end-to-end.

## Building the installer

A real Windows installer is produced end-to-end by one command:

```
pyqt\.venv\Scripts\python pyqt\build_installer.py --verify
```

Pipeline (all real, verified): PyInstaller one-folder bundle → **sign the app
exe** (signtool, SHA256 + timestamp) → frozen app `--selftest` (offscreen;
engine health + builds + window + writable workspace) → Inno Setup 6 compile
(`/DMyAppVersion` from `product_config.APP_VERSION`) → **sign the installer**
→ optional `--verify` silent-installs to a scratch dir, runs the INSTALLED
app's selftest, then uninstalls. Flags: `--version X.Y.Z`, `--no-sign`,
`--trust` (also installs the signing cert into this machine's Trusted
Root/Publisher stores — UAC prompt — so the signed build verifies locally).

- **Output**: `installers/AI-Modpack-Builder-Setup-<version>.exe` (per-user
  install, no admin), bundle at `dist/AI Modpack Builder/`.
- **Signing** (`pyqt/sign.py`): a self-signed code-signing cert is created
  once per user. A self-signed cert does NOT clear SmartScreen on other
  machines — set `AMB_SIGN_THUMBPRINT` to a real OV/EV code-signing cert for
  a publicly trusted build (and optionally `AMB_SIGNTOOL`). To trust it on
  THIS machine, run `python pyqt/sign.py --trust` (imports into LocalMachine
  Trusted Root + Trusted Publisher; `--trust-status` reports the state).
- **Prereqs**: `pyinstaller` in `pyqt/.venv`, Inno Setup 6 (`ISCC.exe`,
  e.g. `winget install --id JRSoftware.InnoSetup --scope user`).
- **Installed-app data**: the frozen app stores everything under
  `%LOCALAPPDATA%\AI Modpack Builder\` (workspace, builds, java, configs) —
  never next to the executable. Dev mode and `AMB_WORKSPACE` are unchanged.
- **Spec/script sources**: `pyqt/installer/amb.spec`, `pyqt/installer/installer.iss`.

## Self-update

The installed app can update itself through the same installer. Feed
contract (`update.json` served at the URL configured in Settings → Updates,
or `AMB_UPDATE_URL`): `{version, notes, installerUrl, installerSha256}`.
The app compares against `product_config.APP_VERSION`, downloads the
installer (size-capped, **SHA-256 verified**) into
`%LOCALAPPDATA%\AI Modpack Builder\updates`, and launches it with Inno's
silent flags. The installer is per-user, so it updates in place.

- **In-app**: Settings → Updates — feed URL, check button (renders up to
  date / update card), Download & install — which first shows a
  **release-notes dialog** (v{current} → v{latest}, scrollable notes,
  Cancel / Download & install; the installer only launches on explicit
  confirmation) and quits the launcher while the installer runs — and a
  once-per-day startup check (installed builds only).
- **Headless**: `AI Modpack Builder.exe --check-update [url] [--apply-update]`
  writes `update-check.json` to the workspace and exits 0/1 — used by the
  installer pipeline to verify the flow (proven live with the **signed**
  1.0.1 installer: 1.0.0 app → feed 1.0.1 → download → SHA-256 verify →
  installer launched → updated app passes `--selftest` and, with the cert
  trusted locally (`sign.py --trust`), `Get-AuthenticodeSignature` reports
  **Valid** on the updated exe and installer; evidence
  `workspace/update-1.0.1-proof-result.json`).

## Layout

```
pyqt/
  main.py            window shell: sidebar, top bar, navigation, launch polling
  engine/            the engine — errors.py, core.py, providers/,
                     interpreter.py, solver.py, reconcile.py, conflict.py,
                     downloads.py, exports.py, instance.py, mojang.py,
                     loader.py, process.py, launcher.py, tester.py,
                     repair.py, compat.py, hardware.py, configs.py,
                     service.py (orchestrator), bridge.py (Api facade)
  theme.py           design tokens + QSS (the Tailwind palette)
  icons.py           inline SVG icons (lucide-style)
  common.py          async workers, icon cache, shared widgets
  views/             home, library, packdetail, discover, aibuilder, misc, overlays
  screenshots/       rendered views (generated, not committed)
  smoke_test.py      headless verification (in-process engine)
  inprocess_test.py  headless verification (in-process Python engine)
  one_system_test.py one-system verification (no port, no subprocess)
  engine_self_test.py 18/18 engine pipeline check (interpreter → live search → build → exports)
```
