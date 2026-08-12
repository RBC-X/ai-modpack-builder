# Testing

A test result only says **PASS** if the corresponding test actually ran and
passed. No fakes, no stubbed progress, no fabricated indicators.

## Test levels (applied to every pack)

| Level | What runs | Evidence produced |
|---|---|---|
| **Instant** | Static validation: mod count, download integrity, **graph integrity** (every required/embedded edge points at a selected node whose version satisfies the range), memory checks | PASS/FAIL per phase |
| **Standard** | Isolated install (Mojang + loader + mods) + **real Minecraft launch**; main-menu detection via log markers (`Sound engine started`, `OpenAL initialized`, `Reloading ResourceManager`, `Backend library: LWJGL`) **and** a Windows window-title probe; early exit the moment evidence appears | `launch-standard.log`, `logs/latest.log`, crash reports, window title |
| **Deep** | Standard + vanilla **server startup** (real world creation, `Done (x.xxs)!`), client **quickplay world load** into that world, **GC-log heap monitoring** (`-Xlog:gc+heap`), **reproducibility** (second launch) | server log, world/level.dat, gc.log, second launch log |

The main-menu check is deliberately conservative: `hasFatal` short-circuits on
crash markers, and at least one strong marker must be present.

## Python engine suite (authoritative)

The shipped system's tests all run against the **in-process Python engine**
(`pyqt/engine/`) — no server, no localhost:

- `pyqt/engine_self_test.py` — **18/18 engine pipeline checks**: interpreter,
  live Modrinth search, a real instant build, `.mrpack` + CurseForge exports
  with validation, record indexing.
- `pyqt/inprocess_test.py` — the launcher window boots entirely on
  `PyEngine()` (pill says In-process, no subprocess, all views navigate).
- `pyqt/one_system_test.py` — one-system verification: no port 8282
  dependency, pill stays Online, builds load from the Python engine.
- `pyqt/smoke_test.py` — every view constructs and renders live data
  (providers, images, masked credentials, compatibility checks).
- `pyqt/live_build_test.py` — real small instant build end-to-end.
- `pyqt/live_launch_test.py` — real game boot → main menu → STOP.
- `pyqt/crash_repair_test.py` — crash → add-missing → relaunch loop.

Coverage of the engine itself (interpreter, providers, dependency/version
solving, conflicts, compatibility memory, crash parsing, repair decisions,
exports + validation, ZIP path security) comes from the legacy TypeScript unit
suite (`src/tests/unit/*.test.ts`, runnable with `npm test` for reference)
plus the Python pipeline checks above.

## Acceptance test (live, in-process)

`pyqt/engine_self_test.py` (and the flagship runs in the history) drive the
**full pipeline against the live Modrinth API** through the in-process engine:
real searches, real selections, real dependency resolution, real downloads,
isolated instance creation, real launch attempt, and validated exports. Every
result is persisted to the build record (`workspace/builds/<id>/build.json`)
and summarized in `PROJECT_STATUS.md`.

## Repair loop tests

The loop runs inside every real build (`service.py`): first launch fails → the
agent parses the crash, removes/adds the **actual culprit**, retests, and
records the repair in memory. Attempt limits are enforced per mode
(1 instant / 5 standard / 15 deep). The user-facing loop is verified live by
`pyqt/crash_repair_test.py`.
