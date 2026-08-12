# Architecture

The system is a **single, self-contained engine**: the Python engine under
`pyqt/engine/` runs **in-process inside the PyQt6 desktop launcher** — no Node
server, no localhost, no second process. The desktop app IS the engine.

The legacy Node/TypeScript engine (`src/`), the old web UI (`web/`) and the
HTTP client (`api.py`) were **deleted on 2026-08-11** — the Python engine is
the only code path in the repository.

The engine has zero third-party runtime dependencies (Python stdlib only:
`sqlite3`, `zipfile`, `json`, `threading`, `urllib`). It runs the build
pipeline, persists every build as JSON, and streams live progress.

## Big picture

```
User request
   │
   ▼
PyEngine._pipeline (pyqt/engine/service.py) — one run per buildId, emits events
   │
   ├─ interpret()            ── requirements
   ├─ buildProviders()       ── Provider[] (Modrinth, CurseForge if keyed)
   ├─ searchAndSelect()      ── ranked candidates per feature + visuals
   ├─ resolvePack()          ── dependency graph + versions (backtracking)
   ├─ detectAndResolveConflicts()
   ├─ downloadPackFiles()    ── SHA1-verified jars into build dir
   ├─ runRepairLoop()        ── test → crash → repair → retest (bounded)
   ├─ generateConfigs()
   ├─ exportMrPack / exportCurseForge / exportServerPack  (+ validation)
   └─ persist build.json + memory.record()
   │
   ▼
workspace/builds/<buildId>/   build.json, logs/, downloads/, instance/, exports/
workspace/mojang/<mc>/        shared Mojang install (versions, libs, natives, assets)
workspace/compat/compat.db    compatibility memory (SQLite)
```

## Data flow & types

All domain shapes live in `pyqt/engine/core.py` (plain dict/JSON shapes) and
are shared by every subsystem:
`ProviderProject`, `ProviderVersion`, `VersionDependency`, `Requirements`,
`Feature`, `DependencyGraph`, `Conflict`, `MemoryEntry`, `RepairRecord`,
`TestResult`, `BuildRecord` (the persisted per-build snapshot).

A `BuildRecord` is the audit trail: request, interpretation, provider queries,
candidate counts, final selections, the full dependency graph, conflicts,
downloads (with hashes), tests, repairs, exports, config changes, and the final
report. The UI renders it; the acceptance test asserts on it.

## Key subsystems

| Subsystem | Where | What it really does |
|---|---|---|
| Provider interface | `pyqt/engine/providers/*` | `search / getProject / getVersions / getDependencies / getDownloadFile / getHashes / manifestReference` |
| Modrinth | `pyqt/engine/providers/modrinth.py` | Real v2 API: facets, versions, deps, hashes, direct downloads |
| CurseForge | `pyqt/engine/providers/curseforge.py` | Real v1 API (key-gated); manifest references, never bundles |
| Interpreter | `pyqt/engine/interpreter.py` | Deterministic keyword/regex NLP → `Requirements` |
| Ranking | `pyqt/engine/rank.py` | Weighted score + human-readable reason per candidate |
| Solver | `pyqt/engine/solver.py` | Recursive expansion, constraint fixpoint, bounded backtracking |
| Conflicts | `pyqt/engine/conflict.py` | Duplicates, fork stacks, range clashes, memory warnings |
| Memory | `pyqt/engine/compat.py` | SQLite; record/bestResultForMod/resolutionForSignature |
| Mojang install | `pyqt/engine/mojang.py` | Version manifest, client jar, rule-aware libraries, natives, budgeted priority assets |
| Loaders | `pyqt/engine/loader.py` | Fabric/Quilt via meta API; Forge/NeoForge via official installer |
| Test levels | `pyqt/engine/tester.py` | Instant (static), Standard (real launch), Deep (server/world/memory/repro) |
| Repair | `pyqt/engine/repair.py` | Log/crash parsing, decision table, bounded loop, memory hit lookup |
| Exports | `pyqt/engine/exports.py` | `.mrpack`, CF manifest ZIP, server ZIP — each with independent validation |
| Shader presets | `pyqt/engine/shaders.py` | GPU tier → performance/balanced/cinematic preset → real Modrinth shader pack + rendering mod |
| UI | `pyqt/main.py` + `views/` | PyQt6 launcher with the in-process engine (no server) |

### The engine (`pyqt/engine/`) — the single system

| Module | What it does |
|---|---|
| `core.py` | types, logger, paths, event bus, JSON persistence |
| `errors.py` | shared `ApiError` for the UI surface |
| `providers/` | http cache, settings store, **Modrinth v2**, **CurseForge v1**, registry |
| `interpreter.py`, `features.py`, `rank.py`, `descresearch.py` | prompt → requirements; feature catalog; candidate ranking; description research |
| `solver.py`, `reconcile.py` | recursive dependency expansion, version backtracking, jar-metadata reconciliation (`unless` via provided-index) |
| `conflict.py`, `downloads.py` | duplicate/fork/range conflicts; SHA1-verified budgeted downloads (real extensions for shader/RP zips) |
| `shaders.py` | GPU tier → preset → real Modrinth shader pack + iris/oculus rendering mod |
| `exports.py` | `.mrpack` (spec-clean, stray-entry validated), CF manifest-reference ZIP, server ZIP — each validated |
| `instance.py`, `mojang.py`, `loader.py`, `instance_java.py`, `process.py` | isolated instances, Mojang install, Fabric/Quilt/Forge/NeoForge, Java selection, kill-tree process runner |
| `launcher.py`, `tester.py`, `repair.py` | play/stop/progress, instant/standard/deep tests, crash parse + attribution + bounded repair loop |
| `compat.py`, `hardware.py`, `configs.py` | SQLite compatibility memory (thread-safe), cached hardware detection + perf estimate, config generation |
| `service.py` | orchestrator: the full pipeline with the same API surface the UI expects |
| `bridge.py` | Api-compatible facade so every PyQt view works unchanged |

The PyQt app instantiates the engine in-process (`PyEngine()` in
`pyqt/main.py`); there is no fallback engine. `BuildRecord` shapes, the event
stream, and the workspace layout (`workspace/builds/<id>/…`,
`workspace/mojang/`, `workspace/compat/compat.db`) are all produced by this
one engine.

## Isolation & safety

- Every test instance is a fresh directory under `workspace/builds/<id>/instance/` — never a real `.minecraft`.
- Shared Mojang files live under `workspace/mojang/` so builds don't duplicate gigabytes.
- Downloads: per-file + total size budgets, SHA1 verification, sanitized filenames.
- ZIP extraction is path-traversal-proof and CRC/size-checked.
- Process runner: working-directory isolation, hard timeouts, kill-tree on Windows (`taskkill /T /F`).
- Repairs are bounded per mode: instant ≤ 1, standard ≤ 5, deep ≤ 15.

## Extensibility

- **New provider**: implement `Provider` in `pyqt/engine/providers/`, register it in `registry.py`. The solver, selector, exporters and UI never special-case providers.
- **New conflict rule**: add a rule in `pyqt/engine/conflict.py`.
- **New repair strategy**: add a case to the repair loop in `pyqt/engine/service.py` (uses `repair.py` parsing).
- **Remote compatibility service**: `CompatibilityDatabase` is a thin class over SQLite; the same interface can back a shared service later.
- **New feature**: add an entry to the catalog in `pyqt/engine/features.py`.
