# AI Modpack Builder

Turn a plain-English Minecraft request into a **real, tested, launcher-compatible modpack**.

```
"Make me a Minecraft 1.20.1 medieval fantasy RPG modpack with around 120 mods,
 Create, magic, better villages, bosses, structures, realistic terrain, shaders,
 32x textures, multiplayer support, and good performance on 8 GB RAM."
```

The system interprets the request, searches **real providers** (Modrinth, and
CurseForge with your API key), scores candidates with written-down reasons,
**recursively resolves dependencies** with a version-constraint backtracking
solver, detects and auto-resolves conflicts, downloads hash-verified files into
an **isolated Minecraft instance**, actually **launches the game**, reads the
real logs, **repairs failures automatically** (bounded loop), and exports a
validated **Modrinth `.mrpack`**, a **CurseForge-compatible ZIP** and a
**server pack**.

Nothing here is fake: every PASS in this project comes from a test that ran.
See [PROJECT_STATUS.md](PROJECT_STATUS.md) for the honest current state.

## Downloads & updates

This repository hosts the source **and** the signed installer + auto-update
feed. The latest installer is attached to the newest release.

- Releases: https://github.com/RBC-X/ai-modpack-builder/releases
- Update feed: https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json

Point the launcher's **Settings → Updates → Update feed URL** at the feed URL
above and it will self-update in place, with release notes and SHA-256
verification (proven live: 1.0.5 → 1.0.6 installed itself over this feed).

## Quick start

**Desktop launcher (one self-contained system):**

```bash
pyqt/.venv/Scripts/pip install -r pyqt/requirements.txt   # PyQt6 (one-time)
pyqt/.venv/Scripts/python pyqt/main.py
```

The full engine runs **inside** the app (`pyqt/engine/`, Python) — no Node
server, no localhost, no second process. The desktop app IS the engine.

Type a request into **AI Builder**, hit **GENERATE MODPACK**, and watch the live
build stream: interpret → search → select → resolve → conflict → download →
instance → test → repair → export.

## It's also a launcher

Every pack that passes testing is playable — the project is an AI-powered
Minecraft launcher on top of a modpack builder:

- **Name your pack** — optional pack-name field on the Build tab (auto-named from
your request if omitted); rename any saved pack from the Pack Inspector.
- **History = launcher library** — every build is saved automatically; PASS
builds show a ▶ Play button right in the list.
- **Play** — launches the exact tested instance (same Java/Mojang/loader/classpath)
with a real game window, `1280x720`, RAM from the build's requirement. The game
keeps running after the server; the pid is persisted so status survives restarts.
- **Stop** — kills the whole process tree (taskkill /T on Windows).
- **Status** — live RUNNING badge in Library, refreshed on a timer.

Play / Stop / status / rename all happen through the launcher UI — there is no
separate server to call.

## Tests

The authoritative test suite is the **Python engine suite** (runs against the
in-process engine — no server needed):

```bash
pyqt/.venv/Scripts/python pyqt/engine_self_test.py   # 18/18 engine pipeline checks (live Modrinth)
pyqt/.venv/Scripts/python pyqt/inprocess_test.py     # launcher runs entirely in-process
pyqt/.venv/Scripts/python pyqt/one_system_test.py    # one-system verification (no port, no subprocess)
pyqt/.venv/Scripts/python pyqt/smoke_test.py         # all views construct + live data renders
pyqt/.venv/Scripts/python pyqt/live_build_test.py    # real small instant build end-to-end
pyqt/.venv/Scripts/python pyqt/live_launch_test.py <buildId>   # real game boot → STOP
pyqt/.venv/Scripts/python pyqt/crash_repair_test.py <buildId> <dep>  # crash → add missing → relaunch
```

The legacy Node system (`src/`, `web/`, `tests/`, `api.py`) was **deleted on
2026-08-11** — the Python engine is the only code path; see
[ARCHITECTURE.md](ARCHITECTURE.md).

## What a build does

1. **Prompt interpreter** → structured requirements (MC version, loader, RAM, features, themes…)
2. **Provider search** (Modrinth always; CurseForge when a key is set) for every feature
3. **Ranking** — every candidate is scored and the reason is stored for the UI
4. **Dependency + version solver** — required/embedded deps resolved recursively; version ranges satisfied by backtracking (downgrades, alternatives); conflicts reported honestly
5. **Conflict engine** — duplicate mods, renderer/optimization fork stacks, shader systems, dependency range clashes, memory-driven warnings
6. **Downloads** — SHA1-verified, size-budgeted, sanitized filenames
7. **Isolated instance** — fresh game dir under `workspace/builds/<id>/instance/`; shared Mojang install under `workspace/mojang/`
8. **Testing** — Instant (static validation incl. graph integrity), Standard (real launch, main-menu evidence), Deep (server + world + quickplay + GC memory + reproducibility)
9. **Repair agent** — crash → parse root cause → find culprit → remove/add/downgrade/config/java → retest, up to a per-mode limit (1/5/15)
10. **Compatibility memory** — every real test outcome (mods, versions, signature, repair, result) stored in SQLite for future builds
11. **Exports** — validated `.mrpack`, CurseForge manifest ZIP, server ZIP with client-only filtering and launch scripts

## Requirements

**End users (installed via the signed installer):** nothing to install. The
installer is self-contained — Python 3.11 and PyQt6 are bundled inside the
app, so there is no runtime to set up. Java is auto-detected and
auto-installed (Adoptium) on first launch when missing. A CurseForge API key
is optional (Settings → Sources). Allow ~1.5 GB free disk for a full asset
download (the tool budget-caps downloads).

**Running from source (developers only):**

- Python 3.11+ and PyQt6 (`pyqt/requirements.txt` — the only dependency)
- Java 17 (for MC 1.20.x) / 21 (for MC ≥ 1.20.5) — auto-detected, auto-installable via Adoptium
- CurseForge API key (optional; Settings page or `CF_API_KEY`)

## Layout

```
pyqt/
  main.py            desktop launcher (PyQt6) — constructs the in-process engine
  engine/            the engine — errors.py, core.py, providers/, interpreter.py,
                     features.py, rank.py, solver.py, reconcile.py, conflict.py,
                     downloads.py, shaders.py, exports.py, instance*.py, mojang.py,
                     loader.py, process.py, launcher.py, tester.py, repair.py,
                     compat.py, hardware.py, configs.py, service.py (orchestrator),
                     bridge.py (Api facade)
  views/             home, library, packdetail, discover, aibuilder, misc, overlays
  engine_self_test.py   18/18 engine pipeline checks (interpreter → live search →
                        build → exports)
  inprocess_test.py     launcher runs entirely on the in-process engine
  one_system_test.py    one-system verification (no port, no subprocess)
  smoke_test.py         all views construct + live data renders
  live_build_test.py    real small instant build end-to-end
  live_launch_test.py   real game boot → STOP
  crash_repair_test.py  crash → add missing → relaunch

workspace/  builds/<buildId>/ (build.json, logs/, downloads/, instance/, exports/),
            mojang/<mc>/, compat/compat.db
```
