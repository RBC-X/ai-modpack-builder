# Project status

_Generated 2026-08-10T22:33:50.581Z from real artifacts — never hand-edited._

## Latest verified work (2026-08-12, real runs)

- **Foundational layer for the master-spec expansion: Pack Identity, mod intent,
  snapshots, Last Known Good, AI change plans, transactional AI edits.**
  New `engine/identity.py` (deterministic identity + per-mod semantic intent
  with importance/replaceability/locked), `engine/snapshots.py`
  (content-addressed manifests, one-per-pack LKG with supersede),
  `engine/plan.py` (non-mutating change plans with impact/confidence/risk),
  and `PyEngine.apply_ai_change` (snapshot → candidate build → promote only
  on PASS; rejected candidates leave the parent untouched, recorded in
  `aiHistory`). UI: Pack Detail Settings gains an Identity & Recovery
  section (theme, locked mods, LKG status, Restore LKG, snapshot restore)
  and Ask AI now shows a plan preview with APPLY & TEST / MODIFY PLAN /
  CANCEL. Verified: `identity_snapshots_test.py` 33/33 PASS, UI test 8/8
  PASS, engine self-test 18/18 (real build + validated exports), smoke,
  in-process and security-regression suites green. Gap matrix written
  (`MASTER_SPEC_GAP_MATRIX.md`); docs added: PACK_IDENTITY.md, SNAPSHOTS.md,
  AI_SYSTEM.md.
- **1.0.8: periodic checks, rollback, and in-app release notes shipped via the live feed.**
  The launcher re-checks the feed every 2 h while open (own throttle stamp;
  honors the Settings toggle); Settings → Updates now shows a
  **↺ RESTORE v<previous>** button fed by the saved installer pool
  (`updater.rollback_candidate()` — newest version strictly older than the
  running app, no re-download), guarded by a post-update health gate
  (`last-applied.json` marker written on apply; next boot health-checks and
  either clears it or toasts where to roll back). Feed release notes render
  inline in the Updates panel and in the update toast; auto-check URL
  priority fixed to env → user setting → default. Verified: unit checks,
  extended autocheck toggle test, new `rollback_ui_test.py`, smoke, and
  security regression all green; installed 1.0.7 updated in place to 1.0.8
  (SHA `8403d066…1af2c`), reports up to date over the default feed, and all
  new updater symbols are present in the installed binary (PYZ-extracted).
- **1.0.7: default update feed embedded — fresh installs need zero config.**
  `DEFAULT_UPDATE_FEED_URL` (public GitHub feed) is baked into the build and
  `updater.update_url()` uses it when no env/setting exists; `check()` now
  records the resolved `feedUrl`. Fresh-user proof:
  `pyqt/fresh_user_feed_test.ps1` silent-installed 1.0.7 into a clean
  prefix with a fresh LOCALAPPDATA (no state.json), ran `--check-update`
  with no URL and no env override → default resolved to the public GitHub
  feed and reported `ok: true, current: 1.0.7, available: false` (rc 0).
  The installed 1.0.6 launcher then updated in place to 1.0.7 over the live
  feed (SHA `2e183155…cbb7a` verified) and now also reports up to date via
  the default with zero flags.
- **1.0.6 shipped in place via the LIVE GitHub feed**: the installed 1.0.5
  app ran the full loop over `releases/latest/download/update.json` —
  `available: true` → downloaded 29,233,848 bytes → SHA-256 `01d750b3…76`
  verified → Authenticode verified → installed in place. Installed app is
  now **1.0.6** (`available: false`, selftest 6/6 green incl. no-legacy-Node
  and shader/RP-engines checks). Release carries the jump-to-page feature
  (`pagination_test.py` 40/40).
- **Update-path bug fixed**: `apply_installer` now pins `/DIR` to the
  running app's folder in frozen builds (Inno's remembered-dir gotcha would
  have sent the next GUI update into the build-verify scratch dir); verified
  by simulation (frozen → real install dir, AMB_UPDATE_DIR still wins).
- **Source pushed**: `github.com/RBC-X/ai-modpack-builder` main branch now
  holds the full pyqt/ launcher + engine and docs with a `.gitignore` that
  excludes workspace, installers, venv, secrets, logs, state, and
  screenshots (secret-scanned before push). Remote keeps its slim public
  README landing page.
- **Reboot survival documented** (RELEASING.md): startup shortcut re-verified
  live (kill → logon-launch → feed back under fresh pid); the GitHub update
  path needs no local process; six honest gaps listed — none break updates.
- **REAL reboot test PASSED** (2026-08-12): after an actual restart the HTTPS
  mirror relaunched at logon (fresh pid, 1.0.6 feed over TLS) and the
  installed launcher checked the public GitHub feed with no flags
  (`appOk: true, appCurrent: 1.0.6, appAvailable: false`). Timing finding:
  this machine's logon sequence is slow (Run key ~2 min post-boot, Startup
  folder ~4 min), so the mirror is now ALSO in `HKCU\…\Run`
  (`pyqt/register_runkey_feed.ps1`) — the proven-early path — with the
  Startup-folder shortcut kept as redundancy.
- **Jump-to-page verified in the installed 1.0.6 binary**: the frozen
  `views.discover` module extracted from the installed exe's PYZ contains
  the jump feature, and `pyqt/jump_visual_test.py` renders the real
  DiscoverView (identical code), searches live, jumps to page 5
  (`Page 5 · showing 385–432 of 3,259`, 0 overlap with page 1) and back,
  saving before/after screenshots (`workspace/jump-page1.png`,
  `workspace/jump-page5.png`).
- **Regression**: pagination 40/40, engine_self_test 18/18, smoke PASS
  (rc=0), frozen selftest 6/6, installed-app selftest rc=0.

## Automated test suite (real run)
- 232 tests: **232 pass / 0 fail**

## Latest acceptance test (live Modrinth)
- Result: **done** (66s, 2026-08-10T09:18:14.728Z)
- Request: `Create a lightweight fantasy exploration pack with structures, bosses, improved terrain, performance mods, and around 10 mods that can run on 8 GB RAM. Use Fabric.`
- Mods selected: 19; downloads OK: 19, failed: 0
- Test: **PASS** — Minecraft reached the main menu
- Server world-load: true (exited-1)
- Exports: modrinth-mrpack ✓, curseforge-zip ✓, server-zip ✓

## Newest build artifact
- Build: `b-19fedb2cb00-1fad25cf` (2026-08-10T22:02:25Z)
- Status: **done**; mods: 150; graph: 165 nodes / 526 edges
- Conflicts: 0 (0 resolved); repairs: 5
- Test: **PASS** — Minecraft reached the main menu (6 test run(s); repairs: 5)
- Exports: modrinth-mrpack ✓, curseforge-zip ✓, server-zip ✓

## Environment
- Java: JDK 21 (C:\Program Files\Common Files\Oracle\Java\javapath\java.exe); JDK 17 (C:\Users\bsmit\OneDrive\Documents\Minecraft Builder\workspace\java\jre-17\jdk-17.0.20+8-jre\bin\java.exe)
- Free disk: 9011 MB
- Workspace: C:\Users\bsmit\OneDrive\Documents\Minecraft Builder\workspace

## Subsystem status

| Subsystem | Status | Evidence |
|---|---|---|
| Provider integrations (Modrinth) | Done | live searches/downloads in acceptance + unit tests |
| Provider integrations (CurseForge) | Done | official v1 search/project/file/download-url mapping, content class filters, screenshots and API-key auth covered by shaped unit tests; live account call remains key-gated |
| Prompt interpreter | Done | unit tests cover all spec examples; mergeRequirements keeps parsed 1.20.1 when UI sends mcVersion "auto" (regression b-msjxhopz) |
| Mod search & ranking | Done | multi-keyword parallel searches + relevance-dominant scoring + category-browse fallback; live 162-mod flagship (b-mskbcie8): targets sum EXACTLY to the requested 120 (was 39), 0 "no relevance" selections, per-feature targets met (create 20, magic 17, terrain 17, bosses 15, structures 15…); skipped reasons persisted |
| Target distribution | Done | interpreter distributes the requested count across features, normalized to the exact goal; unit tests assert sum == 120 for the flagship request |
| Phantom-visual fix | Done | shaders no longer pooled as mod seeds (were selected but never downloaded); shaders/RP come only from the visuals pipeline (b-mskbcie8: shaders 1, resourcePacks 1, 0 non-mod selections) |
| Export disk guard | Done | server-zip deferred (>300 MB or massive) and regenerated on first download from the persisted record; on-demand regen verified live (b-mskbcie8: deferred → 570 MB zip produced on download); CF refs persisted for regeneration |
| Dependency solver | Done | unit tests + real graph in builds; jar-metadata reconciliation adds API-hidden required deps (fabric-*, library mods) |
| Version solver | Done | backtracking tests; downgrade-to-satisfy |
| Conflict detection | Done | unit tests + engine output in builds |
| Minecraft instance creation | Done | isolated instances; shared mojang install |
| Process runner | Done | timeouts/kill-tree; real launches |
| Crash parser | Done | unit tests on real-format reports incl. Fabric version-constrained missing-dep; fatalStartupDetected fail-fast kills doomed launches in seconds instead of the 420s timeout |
| Repair agent | Done | live loop: b-msjn55i9 real Fabric 1.20.1 build crashed with "Some of your mods are incompatible… Install kilt" → repair added kilt 20.1.19 → retest reached main menu → PASS |
| Performance estimator | Done | estimates in builds (RAM/load/confidence) |
| Exports (.mrpack/CF/server) | Done | validated exports in acceptance + unit tests |
| Server pack generation | Done | client-only filtering tested; real server-zip export |
| UI / build progress | Done | SSE live view verified end-to-end |
| Launcher (Play/Stop/name/save) | Done | launcher-grade Play: real progress bar from log markers (Fabric pack 62% mods→92% resources→100% main menu, verified live), phase badges, live console tail, honest ERROR with root cause (broken Forge pack reported missing playeranimator), Stop kills the tree, game survives server restarts (detached spawn + state reconciliation) |
| Compatibility memory | Done | SQLite records from builds + tests; real missing-dependency→add fabric-api and add kilt entries |
| Deep test mode | Done | live PASS b-msjz2uds on Fabric 1.20.4: server Done + world-creation + quickplay world-load (log evidence) + GC peak 825 MB + reproducible second launch |
| Forge/NeoForge path | Done | Forge 47.4.22 1.20.1 flagship build PASSED with real main-menu evidence (template substitution + launchTarget + split-package fixes) |
| Shader / resource-pack search | Done | loader-facet bug fixed (forge facet returned 0 shaders on Modrinth; verified live: 0 → 453 hits). Shaders+RP now found and bundled (b-msk18dhn: shaders 1, resourcePacks 1) |
| Instant test honesty | Done | graph-integrity ignores edges from deselected mods (fabric-mod-removal regression); download-integrity fails on missing jars (budget/policy) instead of silently shipping a partial pack; download budget auto-scales with pack size (600 MB → 2200 MB for massive) |
| Native PyQt6 launcher | Done | dark launcher UI talks only to the real engine: responsive image-first Modrinth/CurseForge catalog, project galleries, target-pack compatibility/version selection, secure provider setup and probe, Home/Library/Pack Detail/AI Builder/Downloads/Activity/Settings, live SSE progress/logs, crash repair, provider/local import, RAM controls, backups, and a taskbar-pinned launcher. Verified by pyqt/smoke_test.py, full rendered screenshot set, real launch and crash-repair tests; see pyqt/README.md. |
| Python engine port (one system) | Done | the full Node engine is ported to pyqt/engine/ and runs in-process in the PyQt app — no Node server, no localhost. Port map in ARCHITECTURE.md. Verified live with no Node running: pyqt/engine_self_test.py 18/18 (interpreter, live Modrinth search, real instant build 17 mods → PASS, .mrpack + CurseForge ZIP validated, records indexed), pyqt/inprocess_test.py (window boots on PyEngine(), pill shows In-process, no subprocess, all views navigate), live AI Builder flow (33-mod build, instant PASS, 101 events streamed). Port bugs fixed: sqlite3 cross-thread (check_same_thread=False + lock) and solver async-await on a plain function. |
| Manual pack building | Done | NEW PACK in Library creates a real blank pack (name/MC/loader/RAM) via POST /api/builds/new; auto resolves to a concrete MC version; the pack is a first-class Mod Browser target (appleskin → fabric-api auto-added, instant validation PASS, jars installed). 6 unit tests + pyqt/new_pack_test.py (10/10) drive the button→dialog→create→add-mod flow live. |
| Pack deletion | Done | DELETE /api/builds/:id permanently removes a pack (instance/jars/exports/worlds), refused with 409 while the game runs; Library cards carry a confirmed trash button (disabled while running). Verified live end-to-end. |
| Stack-trace crash attribution | Done | unknown/generic crashes are attributed to the mod whose class is on the real stack (jar central-directory index, exact class → package → mixin-config; cached per file). Repair removes the attributed mod with an honest reason; falls back to priority only with no evidence. Verified on real crash reports (project-atmosphere exact-class match) + 8 new tests (200/200). |
| Persistent builds (keep working) | Done | repair budget escalates standard(5)→deep(15) automatically instead of failing; launcher console log (launch-play.log) is read for pre-bootstrap crashes (invalid jar module names); new invalid-jar-name rule removes the exact jar (true-power-optimization root-caused from a real failed build); build-time guard drops such jars at selection. 7 new tests (207/207). |
| Loadability-aware AI selection | Done | rankCandidate applies a -60 loadability penalty to mods whose filename derives an invalid Java module name (keyword/digit), so the AI picks valid alternatives instead; guard drops are trained into the compat DB as invalid-jar-name FAIL entries keyed on the mod slug. Verified live: Custom large v3 avoided super-bosses entirely (valid boss mods chosen), only a required dependency still hit the guard → 130 mods, main-menu PASS, 0 repairs. 208/208 tests. |

## 2026-08-11 — Council round 2 + GPU-aware shader engine + legacy deletion (verified)

- **Council round 2** (solver, reconcile, exports, tester, hardware, updater
  deep-read; full evidence in `COUNCIL_REPORT.md`):
  - **Hardware detection is now cached** (`detect_hardware` TTL 300 s + forced
    refresh). `fit_xmx_mb()` called it on every launch/build/retest — 2–3
    PowerShell spawns (each up to 20 s timeout) per call. Verified: second
    call spawns 0 subprocesses.
  - **`validate_mrpack` now actually checks for stray entries** (the comment
    promised it, the code didn't). An embedded jar in the archive root is now
    an `ERR`.
- **GPU-aware shader presets engine** (`pyqt/engine/shaders.py`): GPU string →
  tier (integrated / discrete-mid / discrete-high) → preset (performance /
  balanced / cinematic) → **real Modrinth shader pack** (9 slugs verified live
  today) + the loader's rendering mod (iris/oculus, deps pulled by the
  solver). The build pipeline now actually selects shaders (it never did —
  the Node-era visuals pipeline wasn't ported); the choice is recorded in
  `shaderChoice` and shown in the final report. Downloads of non-mod files
  keep real extensions (a shader zip named `.jar` was invisible to Iris).
  `pyqt/shader_preset_test.py` 23/23.
- **Real shader-pack e2e PASSED with a live game boot**: tiny Fabric 1.20.4
  pack (10 mods + MakeUp - Ultra Fast shader, performance preset for this
  machine's integrated GPU + 4 GB RAM), iris + sodium rendering stack pulled,
  shader zip landed in `shaderpacks/`, game reached the main menu, stopped
  cleanly. `pyqt/shader_e2e_test.py` PASS.
- **Legacy Node system deleted**: `src/`, `web/`, `tests/`, `node_modules/`,
  `package.json`, `package-lock.json`, `tsconfig.json`, `pyqt/api.py` (HTTP
  client), `pyqt/legacy_auto_restart_test.py`, `pyqt/reference_capture.cjs`,
  `pyqt/tmp_test.mrpack`.  `ApiError` moved to `pyqt/engine/errors.py`;
  `bridge.py` imports it there. All 2196 pyqt modules parse, engine healthy,
  zero residual references; docs updated (ARCHITECTURE, pyqt/README).

## 2026-08-12 — Discover pagination (verified)

- Engine `search(offset)` wired through Modrinth `offset` / CurseForge `index`
  in single + merged paths; Discover pager (← Prev / Next →, "Page 2 ·
  showing 49–96") enables Next only on a real full page and resets on any
  filter change. `pagination_test.py` 14/14 (real 48-hit pages, 0 overlap);
  smoke rc=0. Pending 1.0.4 release.

## 2026-08-12 — 1.0.3 shipped as an in-place UPDATE (verified)

- Round-4 fixes delivered through the app's own self-update path: version
  1.0.3 built + signed, feed published (`workspace/update-feed/update.json`),
  installed app (1.0.1) pointed at the feed, and the full loop verified on the
  real install: check → download → SHA-256 → in-place apply → app now reports
  1.0.3, `available: False`, selftest 6/6 green.
- Two delivery bugs found and fixed: Git Bash mangles Inno `/VERYSILENT`
  flags (use `MSYS2_ARG_CONV_EXCL='*'`), and Inno silently reuses the last
  `/DIR` (pass an explicit /DIR for in-place updates).

## 2026-08-12 — Council round 4: visuals review, shader-preset swap, CF second source, installer verify (verified)

- **Visuals review**: interpreter parses shader-quality intent (cinematic /
  light); `pick_shader_preset` honors the request but never exceeds the
  machine (cinematic on integrated → performance, on 10 GB → balanced, reason
  recorded); `pick_resource_pack` is RAM-aware (64x on 6 GB mid-GPU → 32x);
  choices now record `provider`, shown in the final report.
- **Pack Detail shader-preset swap**: Settings tab combo (performance /
  balanced / cinematic) + SWAP SHADER & RE-TEST → engine `set_shader_preset`
  re-picks a real pack, downloads (SHA-1), swaps the selection, installs into
  `shaderpacks/`, schedules a REAL retest. `shader_swap_test.py` 18/18.
- **CurseForge second source**: `choose_shader` / `choose_resource_pack`
  search CF by name keywords when a key is configured; broken-key degradation
  verified live (`cf_degrade_test.py` 10/10 — real Modrinth pick, honest
  provider).
- **Provider-error honesty**: `retry_fetch` includes HTTP status + body in
  errors and never retries 4xx (was 4 retries ~4 s per broken call — this
  root-caused and fixed the smoke-test rc-127 flake; smoke now rc=0 ×2).
- **Installer verify**: signed 1.0.2 silent-installed to a clean prefix,
  installed-app `--selftest` rc=0, all 6 checks ok (legacy-free bundle,
  shader/RP engines importable), uninstalled cleanly.

## 2026-08-12 — Council round 3, resource-pack engine, Deep shader e2e, signed 1.0.2 (verified)

- **Resource-pack engine** (`pyqt/engine/resource_packs.py`): theme +
  resolution keywords → real Modrinth resource packs (faithful-32x/64x,
  bare-bones, classic-3d verified live); resolution downgrades explicit with
  reasons (64x → 32x on integrated). `pyqt/resource_pack_test.py` 18/18.
- **Visuals stage in the pipeline**: shaders/RPs no longer pooled as mod
  seeds; choices persist as `shaderChoice` / `resourcePackChoice`. AI Builder
  timeline shows the visuals stage; Pack Detail specs card was reading
  nonexistent `packStats` keys (always "Shaders 0") — now renders real
  choices + reasons.
- **Deep-mode shader launch — full PASS** (b-19ff3c3b13d, all 14 phases):
  instance, Mojang 1.20.4 + fabric, main-menu (log + window), server "Done",
  world creation + load, client quickplay world load, **GC peak 805 MB**,
  reproducibility (2nd launch at menu). MakeUp Ultra Fast in `shaderpacks/`,
  Faithful 32x in `resourcepacks/`, both in the final report.
- **Signed installer 1.0.2** with frozen self-checks: no legacy Node files in
  the bundle, shader/resource-pack engines importable inside the frozen app
  (PyInstaller PYZ — importability check, not loose `.py` presence). Frozen
  selftest rc=0, installer signature **Valid**, installed-app selftest rc=0.
  `smoke_test.py` 35/35 stable.

## 2026-08-11 — Council round 1: six real flaws found and fixed (verified)

Three-council review (flaws / strengths / builder) — full evidence trail in
`COUNCIL_REPORT.md`. All fast suites green at round start EXCEPT
`new_pack_test.py`, which failed with a real regression: blank packs stored
`minecraftVersion: "auto"` literally, so adding any mod failed (`No
auto/fabric version for AppleSkin`). Fixed in `create_pack` (auto resolved at
creation) + `add_mod` guard. Also fixed: orphan `status: "created"` (blank
packs now `done`), missing instance skeleton on new packs, key-less CurseForge
ZIP import crash (`prov=None` AttributeError → reference-only), phantom
`downloadPath` on failed downloads, and a **latent shader-routing bug**
(shaders were installed into `resourcepacks/`, never `shaderpacks/`).
`new_pack_test.py` now cleans up after itself (4 stale test packs removed).
Verification: `cf_import_edge_test.py` 8/8, `shader_routing_test.py` 6/6,
`new_pack_test.py` 10/10, `import_e2e_test.py` PASS, all other fast suites
PASS. Next round: visual A/B vs CurseForge/Modrinth; Deep-mode shader launch; saved-
pack favourites and pause/resume for downloads.

## 2026-08-11 — Fast browsing: startup-warmed catalogs, parallel all-sources, Worlds tab (verified)

- **Startup warm-up** (`MainWindow._warm_catalogs`): six default Discover
  catalogs prefetched on a daemon thread at boot into the provider + icon
  disk caches. Measured: **969 ms cold → 9 ms warm (109×)** for the six
  catalogs (`pyqt/browse_speed_test.py` 5/5 PASS).
- **"All sources" is now both catalogs**: Modrinth + CurseForge queried in
  parallel and merged (dedupe, downloads-sorted, 48/page); unavailable
  sources reported so the CF setup prompt shows. Providers cached on the
  engine (settings-mtime keyed) — no per-search disk reads.
- **Worlds tab** in Discover (CurseForge class 17; honest CF-key setup prompt
  without a key; world cards open the project page).
- Verified: real MainWindow boot completes the warm-up and shows the Worlds
  tab; `inprocess_test.py` + `smoke_test.py` PASS. Evidence:
  `workspace/browse-speed-result.json`.

## 2026-08-11 — Imported modpacks now contain their mods + CurseForge-style import progress (verified)

- **Import fixed (real mods now land).** `.mrpack`/CurseForge ZIPs reference
  jars by URL or project/file ID — the old importer only extracted
  `overrides/`, so imported packs had zero mods. New `pyqt/engine/imports.py`
  downloads every indexed file (sha1-verified, first-working-mirror),
  extracts overrides safely, records real selections enriched via Modrinth's
  version-file-hash endpoint (real titles in the Pack Inspector), and provider
  import downloads the modpack's own archive first. CF files without a signed
  URL are recorded as honest reference-only.
- **Mrpack exporter now spec-clean** (index + overrides only; jars downloaded
  at install). 17-mod export: ~15 MB embedded → **3,256 bytes**, still
  validates. `validate_mrpack` checks structure + downloads URLs + env.
- **CurseForge-style import UI**: ImportOverlay with live stage + n/total +
  percent, **CANCEL** (cooperative event; partial build deleted), then **PLAY**
  replaces CANCEL on success; error → CLOSE card. Wired to provider import +
  local archive drop.
- **Verified**: `pyqt/import_e2e_test.py` 9/9 PASS (17/17 mods downloaded
  hash-verified into instance mods, selections populated, cancel + cleanup);
  `pyqt/import_overlay_test.py` 9/9 PASS (cancel → done → PLAY emits id);
  `engine_self_test.py` **18/18** (live build + exports validated);
  `inprocess_test.py` + `smoke_test.py` PASS. Evidence:
  `workspace/import-e2e-result.json`, `workspace/import-overlay-result.json`.

## 2026-08-11 — 1.0.1 signed rebuild + live self-update through the trusted cert (verified)

- **Version → 1.0.1** (`product_config.APP_VERSION`, single source).
  Pipeline re-run **fully signed**: `pyqt/build_installer.py --trust
  --verify` → **8/8 PASS** — bundle, sign app exe (signtool SHA256 +
  DigiCert timestamp), frozen selftest rc=0, Inno Setup
  `AI-Modpack-Builder-Setup-1.0.1.exe` (27 MB), **sign installer —
  status: Valid**, trust cert locally — already trusted, silent install,
  installed selftest rc=0. The earlier 1.0.1 (built unsigned for the
  update test) is superseded — the shipped 1.0.1 is signed and Valid.
- **Live self-update re-proven against the signed 1.0.1**: preserved
  frozen 1.0.0 client (probe `current: "1.0.0"`) → local feed
  (`workspace/update-feed/update.json`, sha256 `17c0ff6a…`) →
  `available: true` → downloaded the **28.8 MB signed installer** →
  SHA-256 matched → launched (pid 19084) into a scratch dir
  (`AMB_UPDATE_DIR`) → installed in 10 s.
- **Updated app verifies Valid with the locally trusted cert**: installed
  1.0.1 exe `--selftest` rc=0, self-reports `current: "1.0.1"` /
  `available: false` against the 1.0.1 feed (version proof), and
  `Get-AuthenticodeSignature` → **Status: Valid** (subject `CN=AI
  Modpack Builder, O=AI Modpack Builder`) on the installed exe AND the
  1.0.1 installer. Evidence: `workspace/update-1.0.1-proof-result.json`.

## 2026-08-11 — Local cert trust + release notes before update (verified)

- **Cert trusted locally.** `pyqt/sign.py` gained `trust()`/`is_trusted()`/
  `is_admin()` + CLI (`--trust` / `--trust-status`); it imports the
  code-signing cert into the machine **Trusted Root + Trusted Publisher**
  stores (UAC when not elevated, EncodedCommand). `build_installer.py` got
  a `--trust` phase. After trusting, `Get-AuthenticodeSignature` AND
  `signtool verify /pa` both report **Valid** on the signed installer
  (were Invalid/Untrusted). Honest limit: per-machine trust only.
- **Release notes before update.** Settings → Updates "Check for updates"
  stores the full feed notes; DOWNLOAD & INSTALL opens a themed dialog
  (v{current} → v{latest}, scrollable notes, Cancel / Download & install);
  the installer only launches after explicit confirmation.
- **Verified**: `pyqt/updatenotes_ui_test.py` 8/8 PASS (real check flow,
  dialog shows full notes, install-click applies with exact URL, Cancel
  never applies); `workspace/updatenotes-dialog.png` rendered;
  `sign.py --trust-status` → `trusted: true`; pipeline re-run **8/8 PASS**
  including `sign installer — status: Valid` and `trust cert locally —
  already trusted`; smoke + in-process tests PASS.

## 2026-08-11 — Signed installer + self-update (verified end-to-end)

- **Signed installer**: `pyqt/sign.py` self-signs the bundle exe AND the
  installer with the Windows SDK signtool (`/fd SHA256`, real DigiCert
  RFC3161 timestamp — verified signer `CN=AI Modpack Builder`,
  timestamp `DigiCert SHA256 RSA4096 Timestamp Responder`).
  `AMB_SIGN_THUMBPRINT` switches to a real CA cert for public trust;
  self-signed still warns on other machines.
- **Self-update proven live**: frozen 1.0.0 app → local feed claiming 1.0.1
  → `--check-update --apply-update` → 28.8 MB installer downloaded,
  SHA-256 verified, launched → updated app installed to scratch dir and
  passed its selftest (rc=0). "No update" path verified (nothing
  downloaded). In-app surface: Settings → Updates (feed URL, check,
  download & install, startup toggle) + 24 h-throttled startup auto-check
  in installed builds. Version single-sourced in
  `product_config.APP_VERSION`, threaded through the installer via
  `/DMyAppVersion` (`#ifndef` in the .iss).
- **Final signed pipeline**: 7/7 PASS in 76 s
  (`workspace/installer-build-result.json`): bundle → sign app exe →
  frozen selftest rc=0 → installer → sign installer → silent install →
  installed selftest rc=0.

## 2026-08-11 — Real Windows installer (PyInstaller + Inno Setup), verified end-to-end

- **Installer produced**: `installers/AI-Modpack-Builder-Setup-1.0.0.exe`
  (28.8 MB, Inno Setup 6, per-user install, no admin; Start-menu + optional
  Desktop shortcut, uninstaller) wrapping the PyInstaller one-folder bundle
  (`dist/AI Modpack Builder/`, 94 MB).
- **Frozen-app data**: `engine/core.workspace_dir()` resolves to
  `%LOCALAPPDATA%\AI Modpack Builder\workspace` when frozen; UI state,
  fonts and the icon load through a new bundle-safe `resource_path()`.
  Dev mode and `AMB_WORKSPACE` unchanged.
- **`--selftest` mode** added to `main()`: boots the whole app offscreen,
  verifies engine health / builds load / window / writable workspace, writes
  `selftest.json`, exits 0/1 (`os._exit`, no Qt-teardown fail-fast).
- **Pipeline** `pyqt/build_installer.py [--verify]` — real run **5/5 PASS
  in 86 s** (`workspace/installer-build-result.json`): PyInstaller bundle →
  frozen selftest rc=0 → installer compile → silent install to scratch →
  installed-app selftest rc=0. Frozen app also loads the real workspace
  (26 builds, rc=0).
- **Bug the frozen run caught**: `icons.py` imports `PyQt6.QtSvg` (inline
  SVG icons) — wrongly excluded from the spec; un-excluded.

## 2026-08-11 — Auto-relaunch surfaced in the PyQt launcher

- **Pack Detail → Settings → Runtime Resilience**: an **Auto-relaunch on
  silent close** checkbox wired to the engine (`set_auto_relaunch` signal →
  `MainWindow.set_auto_relaunch` → engine, persisted in
  `settings.autoRelaunch`), reflecting the record on open.
- **Launch overlay relaunching mode**: `phase: relaunching` renders a
  **Recovering <pack>** card with the stage, progress, a STOP button, and the
  **recovery log** (closeContext reason + last game log lines). The launch
  poller keeps running through relaunching → loading → running, so the
  overlay follows the recovery live.
- Verified: `pyqt/autorelaunch_ui_test.py` 8/8 PASS; rendered evidence
  `workspace/overlay-relaunching.png`; smoke + in-process tests PASS.

## 2026-08-11 — Live verification: auto-relaunch + RAM-fitted lite pack

_Every claim below is from a real run with artifacts on disk._

### Opt-in auto-relaunch — implemented AND proven end-to-end

New per-pack `settings.autoRelaunch` toggle (default off). When ON, a game
that dies silently — no crash report, no `Stopping!` window-close, no user
Stop — within 2 minutes of the main menu is relaunched **once** at **80% of
the fitted heap** (`pyqt/relaunch_proof.py` →
`workspace/relaunch-proof-result.json`):

1. First launch reaches the menu — pid 13616, `-Xmx4096m` — **PASS**
2. Game hard-killed 25s after the menu (silent death) — engine relaunches
   within 15s: pid 13616 → **16812 with `-Xmx3072m`** (80% of 4096) — **PASS**
3. Relaunched game reaches the menu again — **PASS**

`launch-state.json` records `phase: relaunching` + `closeContext` (reason,
log tail); the UI shows a "Silent close detected — relaunching with N MB RAM"
stage; the retry never re-triggers (once-guard + `autoRelaunch: False`).

### Flagship Lite (RAM-fitted) — verified: holds the menu 5 minutes on 7 GB

`pyqt/make_lite_pack.py` created `b-lite-ef38acfd` (142 mods, `ramGB 4`) by
deselecting the 10 heaviest worldgen/magic/GPU mods from the 150-mod
flagship (mna, goety, alpha-below, distanthorizons, ars-magica-legacy,
blood-magic, aether, bossesrise, daily-boss-x-bossesrise,
project-atmosphere); addon mods that hard-require dropped bases were
cascade-deselected from the REAL Forge missing-deps screen via a
jar-metadata modId→slug map. **`pyqt/lite_relaunch_hold.py` →
`workspace/lite-relaunch-hold-result.json`: menu reached (pid 19060, 138.6s
boot) → 300s hold, 60/60 ticks up, free RAM 0.02–1.42 GB — PASS.** The
150-mod original died silently at the menu on this machine; the RAM-fitted
pack no longer does.

Also fixed: `main_menu_reached` now requires REAL menu evidence (audio init
or atlas+LWJGL backend) instead of any `[Render thread/INFO]` line (the old
match declared "menu reached" at the moment Project Atmosphere's client setup
crashed); `idas` loot-table `ars_nouveau` parse errors in latest.log are
optional-integration noise (non-fatal, menu reached after).

## 2026-08-11 — Live verification: multi-pack session hardening (self-closing investigation)

- **Disk freed 49.8 GB** (2.5 → 48.8 GB free): failed/building flagships and
  orphaned legacy build dirs deleted (`pyqt/cleanup_builds.py`).
- **Orphaned legacy processes killed**: old Node engine `dist/app/server.js`
  (leftover from before the Python engine became the single source of truth)
  and two hung headless tests.
- **Heap overcommit fixed** (`hardware.fit_xmx_mb`): every launch is capped at
  ~72% of physical RAM. The flagship was launching with `-Xmx8192m` on this
  7 GB machine; verified live `-Xmx5120m` then `-Xmx4096m` in its launch log.
- **Concurrent-play GPU tuning**: second pack launches with FPS 30
  (`options.txt`) + 960×540 window (verified `--width 960 --height 540`).
- **Pre-launch RAM guard**: refuses to launch into an exhausted machine
  (< 1.0 GB free solo, < 1.5 GB concurrent) with a clear message, and warns
  below 3 GB. Close-context capture in `launch-state.json` explains any
  self-close (stoppedByUser + log tail).
- **Sustained dual-launch findings (real runs)**: both packs reach the main
  menu together and hold ~60–72 s, then the flagship dies SILENTLY at the
  world-registry load stage (no crash report, no `Stopping!`, no hs_err, no
  WER event) while free physical RAM sits at 0.04–0.88 GB. A solo control
  (`pyqt/solo_hold_test.py`) proves the pack alone also dies at ~188 s at
  the menu — this 7 GB machine cannot hold the 150-mod pack at the menu for
  minutes regardless of concurrency; the launcher now fits memory, tunes the
  GPU, and refuses launches into exhausted states instead of letting the
  game die silently. One run hit the known Create `potato_cannon`
  Registrate startup race (crash report captured) — the sustained test
  retries once on pre-menu crashes like the repair pipeline.
- Results: `workspace/sustained-dual-result.json`, `workspace/solo-hold-result.json`.

## 2026-08-10 — Live verification: deep mode, concurrent packs, live log streaming

_Appended by hand to the generated status; every claim below is from a real run with artifacts on disk._

### Deep test mode — verified end-to-end on two real packs

**Flagship 150-mod Forge 1.20.1 pack** (`pyqt/deep_test_flagship.py` →
`workspace/deep-test-flagship.json`): isolated instance ✓, Mojang 1.20.1 +
Forge 47.4.22 (65 libraries) ✓, client launch + main menu (window evidence
`Minecraft* Forge 1.20.1`) ✓, vanilla server `Done` ✓, **world created and
loaded by the server** ✓, reproducibility (second launch → menu) ✓.
`--quickPlaySingleplayer` world load + GC heap monitoring are honestly
**SKIP** on 1.20.1 (the flag requires MC 1.20.2+).

**Fresh Fabric 1.20.4 pack** (`pyqt/deep_test_1204.py` →
`workspace/deep-test-1204.json`): **PASS in 5.8 min** — all phases real:
instance ✓, Mojang 1.20.4 + fabric (65 libraries) ✓, main menu (window
`Minecraft* 1.20.4`) ✓, server `Done` ✓, **world created**
(`saves/world/level.dat` + DIM1/DIM-1/playerdata on disk) ✓, **client
quickplay world load** (`Preparing spawn area` in launch-quickplay.log) ✓,
**GC heap peak 805 MB** (parsed from the real `gc.log`: `805M->474M`) ✓,
reproducibility ✓.

### Two packs at once — verified

`pyqt/dual_launch_test.py`: the engine's single-game guard is removed; each
launch keeps its own process tree, pid file, `launch-state.json` and
`launch-play.log` in its own build dir. Verified live: both packs reached the
main menu concurrently with **distinct pids**, **per-pack state files**
(each carrying its own `buildId` + `pid`), **distinct logs** and **isolated
instances**; stopping one leaves the other running. Per-pack state now keeps
`buildId`/`pid` through progress updates (`status()` always reports the real
pid). Environment caveat (observed, not a launcher bug): on this 7 GB /
97%-disk machine the game window itself occasionally closes ~10–200 s after
the menu (`Stopping!` in latest.log, exit 0) even for a single pack.

### Live log streaming + crash detection — verified

`game_log_stream` is offset-based (lines delivered once; stale content from
previous launches never replayed), waits for the pack to start, and emits
typed events `line` / `crash` / `menu`. The Pack Detail Logs tab shows a live
red `⚠ CRASH DETECTED` banner and `✔ Main menu reached` line. Verified live:
400+ real-time line events streamed from the second pack's boot.

## 2026-08-12 — Discover pagination shipped as 1.0.4 (in-place update)

- **Per-provider page sizes**: CurseForge capped at its API's 50-result limit,
  Modrinth up to 100; merged pages = sum of each source's size (48+50 default,
  96+50 at 96-per-page). `search(page_size=…)` returns the effective
  `page_size` and a real `more` flag (a source returned a full page).
- **Results-count + "more may exist" hint** in the pager, plus a Next-button
  tooltip that says why it's enabled/disabled; page size control (24/48/96)
  on the filter row.
- **Per-content-type page memory** persisted in the UI state file; returning
  to Discover restores where you were (tab switch or restart).
- **Security re-check**: no `.env` file exists anywhere; the CurseForge key
  lives in Windows DPAPI-protected storage (never in settings.json — verified
  `curseforgeApiKey: ''`), records scrub it (`••••••••`), and there is no
  telemetry/analytics code in the codebase.
- **Shipped**: signed 1.0.4 rebuilt and verified (frozen selftest 6/6,
  installer signature Valid, installed selftest rc=0), feed published, real
  installed app updated in place 1.0.3 → 1.0.4 and now reports up to date.
  Regression: pagination_test 28/28, engine_self_test 18/18, round2_verify
  PASS, smoke PASS.

## 2026-08-12 — 1.0.5: real totals, exact-context page memory, HTTPS auto-update

- **Real totals**: Modrinth `total_hits` / CurseForge `pagination.totalCount`
  flow through `search_meta()` into the pager ("of 3,259"), and Next now
  derives from the true total (no more guessing from a full page).
- **Context-keyed page memory**: (type, provider, loader, MC version, page
  size) owns its remembered page; legacy keys migrated.
- **HTTPS auto-update proven with zero flags**: local TLS mirror on
  `https://127.0.0.1:8543` (cert in machine Root store, `serve_feed_https.py`),
  installed app 1.0.4 → 1.0.5 applied in place over real TLS; now reports
  `available: False`. Installed feed URL points at the HTTPS mirror.
- **GitHub release prep**: `pyqt/publish_release.py` + `RELEASING.md` — the
  public step is blocked only on the user's GitHub account/CLI (no `gh`, no
  repo). Regression: pagination 35/35, self-test 18/18, round2, smoke PASS.

## Current failing tests
- None (all unit tests pass; see count above). Acceptance asserts pass on latest run.

## Known external blockers
- CurseForge API key not configured (user-provided; env `CF_API_KEY` or Settings).
- Disk space is tight on this machine; large asset/Forge installs may hit ENOSPC.
- No Microsoft-account auth headless; test sessions are offline sessions.

## Next highest-priority task
- Add the CurseForge API key and run its live suite, or run Deep mode on 1.20.2+ Forge/NeoForge (quickplay world-load with a Forge pack).
- Optional future UX: saved-pack favourites and pause/resume controls for active downloads.
- Run the new Deep mode against a large (162-mod) pack to measure startup wall-clock at scale; fail-fast + stall detector already cut doomed-launch time from 420s to seconds.
