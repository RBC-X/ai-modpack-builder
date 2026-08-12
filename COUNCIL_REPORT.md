# Council Report — Round 4 (2026-08-12)

Passes over the **visuals stack** (shader + resource-pack engines, the
pipeline's visuals stage, Pack Detail specs card) plus the signed-installer
verify. Same standard — every finding has a real failure, a code read, or a
disk record behind it.

## Round 4 flaws found

| # | Flaw | Evidence | Fix + verification |
|---|---|---|---|
| R4-1 | **Shaders ignored the request's own intent** — "cinematic shaders" and
  "light shaders" both produced the same hardware-only pick; the prompt's
  quality ask was parsed nowhere. | `interpreter.py` (only `shaders: bool`);
  `pick_shader_preset` never saw a quality hint | `QUALITY_KEYWORDS` +
  `shaderQuality` in requirements; `pick_shader_preset(req, hw, requested)`
  honors the ask but caps at the machine (verified: cinematic on iGPU →
  performance with the downgrade in the reason) |
| R4-2 | **`pick_resource_pack` ignored RAM** — 64x on a mid discrete GPU with
  6 GB RAM stayed 64x; only the GPU tier could trigger a downgrade. |
  `resource_packs.py` downgrade branch (tier-only) | RAM < 8 also downgrades
  64x → 32x with an honest reason ("64x textures on 6 GB RAM is risky") |
| R4-3 | **CF "fallback" in choose_* was dead code** — it handed Modrinth slugs
  to the CF provider, which cannot resolve them, so a keyed CF was never
  actually searched. | `shaders.py`/`resource_packs.py` fallback branch | Real
  CF keyword search per preset/resolution; provider recorded in the choice;
  broken-key degradation verified live (`cf_degrade_test.py` 10/10) |
| R4-4 | **403 classification lied** — every 403 became "appears search-only";
  an invalid key said the key was fine. And `retry_fetch` retried 4xx 4×
  (~4 s wasted per broken CF call). | raw probe: stored key → 403 "API Key
  missing or invalid"; `retry_fetch` retried any HTTPError | Body-aware errors
  + no-retry-on-4xx; `_get` raises a clear RuntimeError for invalid keys |
| R4-5 | **Smoke test flake root-caused** — the provider probe's CF call (4×
  retry) exceeded its 8 s window, leaving a worker thread past teardown →
  deterministic rc 127. | `/tmp/smoke_r1.log` stopped at check 35, rc 127;
  probe is live CF search | No-retry-on-4xx → probe ~1 s → smoke rc=0 twice |

## Round 4 strengths (verified, untouched)

- **GPU tiering** (RTX gen, bare "Radeon(TM) Graphics" iGPU) — re-read clean.
- **Visuals install routing** (shaderpacks/ vs resourcepacks/) — held.
- **`set_shader_preset` swap semantics** — old shader deselected, exactly one
  new selected, zip installed, retest scheduled with the new file in the env
  (`shader_swap_test.py` 18/18).

## Round 4 builder work — swap control, CF second source, installer verify

- Pack Detail Settings gains a **Shader Preset** section (current shader +
  reason, preset combo, SWAP SHADER & RE-TEST) wired engine → bridge →
  signal → handler. Verified the control renders and the full swap flow runs
  against a real Modrinth pick.
- `choose_shader`/`choose_resource_pack` return the actual provider;
  pipeline records it in `shaderChoice`/`resourcePackChoice` and the report.
- Signed **1.0.2 installed to a clean prefix**: installed-app `--selftest`
  rc=0, 6/6 checks (legacy-free bundle, shader/RP importable), uninstalled
  cleanly, user's real install untouched.

---

# Council Report — Round 3 (2026-08-12)

Passes over the **shader engine, resource-pack engine, and the round-2
fixes**, plus a real Deep-mode shader launch and the signed 1.0.2 installer.
Same standard — every finding has a real failure, a code read, or a disk
record behind it.

## Round 3 flaws found

| # | Flaw | Evidence | Fix + verification |
|---|---|---|---|
| R3-1 | **Pipeline never selected resource packs** — `interpreter` emits
  `resourcePackResolution` and themes, but nothing searched for or installed
  a resource pack (same Node-port gap as shaders in round 2). | `service.py`
  feature loop (mods only); grep found no RP selection in pyqt | New
  `resource_packs.py` engine + visuals stage wiring (below) |
| R3-2 | **Pack Detail specs card read nonexistent `packStats` keys** — always
  rendered "Shaders 0" regardless of the pack. | `packdetail.py` vs actual
  `packStats` shape | Specs card renders real `shaderChoice` /
  `resourcePackChoice` + reasons; verified in `resource_pack_test.py` |
| R3-3 | **`rendering_mod_for("vanilla")` returned "oculus"** — a Forge mod
  would have been seeded into a vanilla (no-loader) pack. | `shaders.py`
  default branch | Returns `None` for vanilla; verified |
| R3-4 | **Smoke test flaked** — passed 35/35 checks but died before printing
  the final PASS (rc 127 on one run). | repeated runs | Runs stably with
  rc=0, full PASS line (verified twice, with and without faulthandler) |
| R3-5 | **Frozen-bundle self-check looked for loose `.py` files** — PyInstaller
  compiles engine modules into the PYZ archive, so a presence check would
  always fail. | frozen selftest verdict vs `_internal/` layout | Check is now
  importability of the shader/RP engines inside the frozen app; green in the
  shipped bundle |

## Round 3 strengths (verified, untouched)

- **`shaders.py` tier logic** (RTX 30 vs 40/50, bare "Radeon(TM) Graphics"
  as iGPU) — corrected in round 2, re-read clean in round 3.
- **Shader/RP install routing** — `launcher._visual_files` sends shaders to
  `shaderpacks/` and resource packs to `resourcepacks/` (round-1 fix held;
  confirmed in the deep launch).
- **Deep test pipeline** — 14 phases, all green on the real shader pack:
  server `Done`, world creation + load, client quickplay, GC peak from the
  real log, reproducibility second launch.

## Round 3 builder work — resource-pack engine + Deep shader e2e

`pyqt/engine/resource_packs.py`: theme + resolution keywords → real Modrinth
resource packs (faithful-32x/64x, bare-bones, classic-3d verified live), with
explicit resolution downgrades when the machine can't run the requested tier
(reason recorded). The pipeline's new **visuals stage** seeds both shader and
resource pack; choices persist as `shaderChoice` / `resourcePackChoice` and
render in the final report. `pyqt/resource_pack_test.py` 18/18.

**Deep-mode shader launch — full PASS** (`b-19ff3c3b13d`, 14/14 phases):
instance → Mojang 1.20.4 + fabric → launch → **main-menu** (log + window
`Minecraft* 1.20.4`) → **server `Done`** → **world creation + load** →
**client quickplay world load** → **GC peak 805 MB** → **reproducibility**
(second launch at menu). MakeUp Ultra Fast in `shaderpacks/`, Faithful 32x
in `resourcepacks/`, both in the final report.

## Round 3 — signed installer 1.0.2 with frozen self-checks

Rebuilt + signed `AI-Modpack-Builder-Setup-1.0.2.exe`: frozen selftest rc=0
with **"no legacy Node files in bundle"** and **"shader/resource-pack
engines importable"** both green; installer signature **Valid**; installed
app selftest rc=0. `smoke_test.py` 35/35 stable.

---

# Council Report — Round 2 (2026-08-11)

Fresh passes over the six modules round 1 did not deep-read: **solver,
reconcile, exports, tester, hardware, updater**. Same standard — every
finding has a real failure, a code read, or a disk record behind it.

## Round 2 flaws found

| # | Flaw | Evidence | Fix + verification |
|---|---|---|---|
| R1 | **`fit_xmx_mb` re-detects hardware on every call** — 2–3 PowerShell subprocess spawns (each up to 20 s timeout) per launch/build/retest, bypassing the service-level cache. | `hardware.py` (`fit_xmx_mb` → `detect_hardware()` → 3× subprocess); callers: launcher env, retest env, build env | TTL cache (300 s) + `force`; verified 2nd call spawns **0** subprocesses (`round2_verify.py` 5/5) |
| R2 | **`validate_mrpack` promised a stray-entry check it never performed** — an embedded jar at the archive root (the old non-standard export format!) would validate clean. | `exports.py` comment vs code | Real check added; synthetic bad mrpack now returns `ERR stray entries outside overrides/` |
| R3 | **The Python pipeline never selected shaders or resource packs.** `interpreter` set `shaders: true`, perf estimate added +2 GB, but nothing searched for or installed a shader — the Node-era visuals pipeline wasn't ported. | `service.py` feature loop searched only `projectType: mod`; grep found zero shader-selection creation in pyqt | New `shaders.py` engine + pipeline wiring (below) |
| R4 | **Downloaded non-mod files were named `*.jar`** — a shader zip named `.jar` is invisible to Iris/Oculus scanning `shaderpacks/` for `*.zip`. | `downloads.py` hardcoded `{slug}-{version}.jar` | Non-mod files keep the provider's real filename/extension; verified in the e2e (`MakeUp-UltraFast-9.5c.zip`) |
| R5 | **Solver loader filter would kill shader seeds** — Modrinth shader packs are not loader-tagged; `loaders: [loader]` returns zero versions. | `solver.ensure_candidates` | Non-mod projects are versioned by MC only |
| R6 | **Test/retest envs ignored visuals** — standard/deep tests installed no shader/RP files. | `service.py` env `shaderFiles: []` | Envs now carry the pack's real shader/RP download paths |

## Round 2 strengths (verified, untouched)

- **Solver**: backtracking with downgrade-to-satisfy, final honesty pass over every required/embedded edge, incompatible-edge resolution by priority, iteration budget. Read in full — no defects found.
- **Reconcile**: provided-mod index (fabric-api bundle submodules), exact-slug-priority loose resolution (`twilightforest` → `twilight-forest`), range enforcement with dependent-drop decisions. Clean.
- **Updater**: SHA-256 mandatory, HTTPS-only in production, size caps, tampered-cache deletion, Authenticode pin before execution. Clean.
- **Tester**: fail-fast on fatal startup lines, 12 s menu-grace for late mod-loading crashes, honest SKIPs, `parse_gc_peak` from real GC logs. Clean.
- **Exports**: spec-clean mrpack, CF manifest-reference + bundled-jars split with NOTES file, server-pack client-only filtering. Clean (after R2).

## Round 2 builder work — GPU-aware shader presets (new capability)

`pyqt/engine/shaders.py`: `gpu_tier()` (integrated/discrete-mid/discrete-high,
handles RTX generation correctly — 30-series is mid, 40/50 high — and bare
"Radeon(TM) Graphics" as iGPU), `pick_shader_preset()` (performance /
balanced / cinematic from GPU + RAM + FPS), `choose_shader()` (fetches a real
Modrinth shader pack + MC-compatible version + CDN URL; 9 slugs verified live),
`rendering_mod_for()` (iris/oculus). Wired into `_pipeline`: the `shaders`
feature is no longer searched as a random mod; the visuals step seeds the
shader + rendering mod, records `shaderChoice` (preset/gpuTier/title/reason),
and the final report shows it. `pyqt/shader_preset_test.py` 23/23.

**Real e2e** (`pyqt/shader_e2e_test.py` PASS): tiny Fabric 1.20.4 pack —
shaderChoice `performance / integrated` → **MakeUp - Ultra Fast**, iris +
sodium pulled by the solver, zip installed into `shaderpacks/`, **game booted
to the main menu with the shader present**, clean stop.

## Round 2 — legacy deletion

Deleted: `src/` (Node engine), `web/` (old UI), `tests/` (Node suite),
`node_modules/`, `package.json`, `package-lock.json`, `tsconfig.json`,
`pyqt/api.py`, `pyqt/legacy_auto_restart_test.py`, `pyqt/reference_capture.cjs`.
`ApiError` moved to `pyqt/engine/errors.py`. Verified: all pyqt modules parse,
engine healthy, zero residual references. ARCHITECTURE.md + pyqt/README.md
now describe only the Python system.

---

# Council Report — Round 1 (2026-08-11)

How this round ran: this environment has no parallel subagent spawns, so the
three councils were run as three rigorously separated review passes by the lead
agent, each grounded in **real evidence** (actual test runs, actual code reads,
actual records on disk). Nothing below is a description-based opinion — every
finding has a file/line, a test result, or a record on disk behind it.

---

## 1. App breakdown (what the councils reviewed)

| # | Subsystem | Core files |
|---|---|---|
| 1 | Prompt interpreter / target distribution | `pyqt/engine/interpreter.py`, `features.py` |
| 2 | Provider integrations | `pyqt/engine/providers/{modrinth,curseforge,http,registry,settings}.py` |
| 3 | Search + ranking | `pyqt/engine/rank.py`, `jarname.py`, `service.search` |
| 4 | Dependency + version solving | `pyqt/engine/solver.py`, `reconcile.py` |
| 5 | Conflict engine + compat memory | `pyqt/engine/conflict.py`, `compat.py` |
| 6 | Instance / Java / Mojang / loader | `pyqt/engine/{instance,instance_java,mojang,loader}.py` |
| 7 | Process runner + launcher | `pyqt/engine/{process,launcher}.py` |
| 8 | Test pipeline (instant/standard/deep) | `pyqt/engine/tester.py` |
| 9 | Crash parser + repair agent | `pyqt/engine/repair.py` |
| 10 | Imports (.mrpack / CurseForge ZIP) | `pyqt/engine/imports.py` |
| 11 | Exports (mrpack / CF / server) | `pyqt/engine/exports.py` |
| 12 | Hardware / perf estimation / configs | `pyqt/engine/{hardware,configs}.py` |
| 13 | PyQt UI (main, views, overlays) | `pyqt/main.py`, `pyqt/views/*` |
| 14 | Updater / installer / signing | `pyqt/updater.py`, `build_installer.py`, `sign.py` |
| 15 | Description research | `pyqt/engine/descresearch.py` |

---

## 2. Flaws council — findings (all verified)

Baseline first: fast suites re-run at round start.
`security_quality_regression_test.py` 13/13, `one_system_test.py` PASS,
`autocheck_toggle_test.py` PASS, `import_overlay_test.py` PASS,
`autorelaunch_ui_test.py` PASS, `smoke_test.py` PASS, `inprocess_test.py` PASS.

**`new_pack_test.py` FAILED at round start** — this was the first real signal.

| # | Flaw | Evidence | Severity |
|---|---|---|---|
| F1 | **Blank packs stored `minecraftVersion: "auto"` literally.** `create_pack` wrote the raw "auto" into the record and nothing resolved it (only the AI pipeline does). `add_mod` then filtered Modrinth versions by `"auto"` → empty → **"No auto/fabric version for AppleSkin"** → adding any mod to a NEW PACK failed. | `new_pack_test.py` traceback; `service.py:add_mod` (`mc = rec["requirements"]["minecraftVersion"]`), `create_pack` stores `mc` as passed | **High — broke the headline "build your own pack" flow** |
| F2 | **Orphan `status: "created"`.** Only `create_pack` ever emitted it; every UI consumer expects `done/failed/building/repaired/stopped`. A new blank pack would render with an undefined status pill. | `service.py:318`; grep showed zero UI readers of `"created"` | Medium |
| F3 | **Blank packs had no instance skeleton.** `workspace/builds/<id>/instance/minecraft/mods` didn't exist at creation (test assertion failed); the pack was a record without a launchable instance until the first add-mod. | `new_pack_test.py` "instance dirs created" FAIL | Medium |
| F4 | **Key-less CurseForge ZIP import crashes.** `import_file` builds providers with `sources=["curseforge"]`; with no API key the list is empty → `prov=None` → `import_curseforge` called with `cf_prov=None` → `_selection` calls `prov.get_project(pid)` on None → `AttributeError` instead of a graceful reference-only import. | `imports.py:_selection` (`prov.get_project` unguarded); caller `service.import_file` (`prov = providers[0] if providers else None`) | **High — crashes a supported path** |
| F5 | **Phantom `downloadPath`.** A CurseForge file whose download failed (hash mismatch / network) still got `"downloadPath": <dest>` recorded even though the jar doesn't exist — the pack would claim a file it doesn't have. | `imports.py:import_curseforge` (selection appended unconditionally after `failed += 1`) | Medium — honesty violation |
| F6 | **Shader routing bug (latent, would have bitten the first real shader pack).** `_visual_files` appended `projectType == "shader"` selections into **`resource_packs`** — both branches push into the same list — so `visuals["shaders"]` was always empty, shader zips were copied into `resourcepacks/` (ignored by the game) and `shaderpacks/` never populated. | `launcher.py:_visual_files` (both `if` branches append to `resource_packs`); confirmed `install_shader_packs` → `shaderpacks/`, `install_resource_packs` → `resourcepacks/` | **High — shaders silently never installed** |
| F7 | **Test hygiene:** `new_pack_test.py` left a "UI Test Pack" build behind on every run (4 stale packs found on disk at round start). | `workspace/builds/index.json` | Low |

### Areas the flaws council hammered and found CLEAN (no action taken)
- **Launcher state machine** (`launcher.py`): per-pack pid files + state, Windows-safe `pid_alive`, log-offset streaming (previous launches' fatal lines never misread), evidence stamping, only-selected-mod install, exact-slug jar cleanup, RAM guard + concurrent GPU tuning, silent-death auto-relaunch once-guard. Reviewed lines 1–838.
- **Repair parser** (`repair.py`): missing-dep extraction correctly skips Forge's `ClassNotFoundException` noise; stack-trace attribution is exact-class → package → mixin-config, never guess-by-priority. The historical `missing[:3]` cap and garbage class-extraction are gone.
- **Imports security**: path-traversal guard (`..` / absolute rejected), size caps, sha1 verification, mirror fallback, honest scope-error abort on 403.
- **Ranker** (`rank.py`): displayed score == sum of displayed factors; relevance dominant; memory FAIL −30; loadability −60; vanilla dampener.
- **Hygiene scan**: zero `TODO/FIXME/XXX`, zero bare `except:`, zero `eval/exec` in project code, all `subprocess` calls have timeouts.
- **Updater**: SHA-256 mandatory, production-HTTP rejected in dev, tampered cached jar deleted+redownloaded (all in `security_quality_regression_test.py` 13/13).

---

## 3. Strengths council — what the app is genuinely best at (keep, don't touch)

1. **Honesty architecture.** The whole engine is built on "never fake": no fake progress (SSE events are real pipeline stages), no fake PASS (main-menu detection requires real audio/atlas evidence), honest reference-only exports, honest scope errors. This is the app's identity — every fix above preserves or *strengthens* it.
2. **The repair loop.** Crash → collect logs → parse → attribute → repair → retest is real and proven on the user's own packs (Serene Seasons add, kilt add, GlitchCore cascade). Stuck-loop guard (3× same action stops) prevents budget burning.
3. **Process isolation & safety.** Per-pack instance isolation, kill-tree stop, `CREATE_NO_WINDOW`, detached spawns that survive server restarts, `free_physical_gb()` pre-launch refusal on exhausted machines.
4. **The imports e2e.** 17 real mods downloaded hash-verified from a real `.mrpack` — the loop that used to install zero mods is now the most impressive feature.
5. **Security posture.** Zip traversal guards, DPAPI secrets, size caps, SHA verification, redacted launch args (`--accessToken`), no key in records.
6. **Ranking explainability.** Every selection carries a scored, human-readable reason; "no relevance — cannot outrank a matching mod" is a real filter, not a vibe.

---

## 4. Builder council — fixes applied (all verified by re-running tests)

| Fix | Change | Verification |
|---|---|---|
| F1 | `create_pack` resolves `auto` MC/loader from settings defaults at creation; `add_mod` belt-and-braces resolves legacy `"auto"` records | `new_pack_test.py` → **10/10 PASS** (mod now addable) |
| F2 | `create_pack` sets `status: "done"`, `phase: "done"` (a blank pack IS complete; no build pipeline runs) | `new_pack_test.py` "record is a blank pack" PASS |
| F3 | `create_pack` pre-creates `instance/minecraft/{mods,config,resourcepacks,shaderpacks,saves}` | `new_pack_test.py` "instance dirs created" PASS |
| F4 | `_selection` only calls `prov.get_project` when a provider exists; key-less CF import degrades to reference-only | `cf_import_edge_test.py` **8/8 PASS** |
| F5 | `downloadPath` only set when the file actually exists; failed/refused downloads recorded honestly with a truthful reason | `cf_import_edge_test.py` 8/8 |
| F6 | `_visual_files` routes shaders → `shaders[]`, resource packs → `resourcePacks[]` (removed dead code) | `shader_routing_test.py` **6/6 PASS** (correct folders on disk) |
| F7 | `new_pack_test.py` deletes its own pack at the end; 4 stale test packs removed from the library | `new_pack_test.py` PASS + "test pack cleaned up"; leftover count 0 |

## 5. Regression sweep after fixes

| Suite | Result |
|---|---|
| `new_pack_test.py` | PASS 10/10 (incl. cleanup) |
| `cf_import_edge_test.py` (new) | PASS 8/8 |
| `shader_routing_test.py` (new) | PASS 6/6 |
| `import_e2e_test.py` (touched imports.py) | PASS — 17 real mods, cancel + cleanup |
| `security_quality_regression_test.py` | PASS 13/13 |
| `one_system_test.py` / `inprocess_test.py` / `smoke_test.py` / `autocheck_toggle_test.py` / `import_overlay_test.py` / `autorelaunch_ui_test.py` | all PASS |
| Syntax check | 6/6 edited files compile |

## 6. Open items for the next round

- **Shader e2e on a real pack**: F6 was latent — no current build carries a shader selection. Next round should build a small pack with `shaders: true` and confirm the zip lands in `shaderpacks/` end-to-end.
- **`api.py` legacy HTTP client** still exists (reference only) — safe to delete once nothing imports it.
- **Visual A/B vs CurseForge/Modrinth** (from the polish backlog): rendered screenshot comparison is pending.
- CurseForge live e2e remains key-gated (stored key is search-scoped; console approval required for file access).
