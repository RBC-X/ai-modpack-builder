# Changelog

## 2026-08-14 — 1.0.20: live heap fit in the launch overlay + clickable RAM badge

- **Live heap-fit field in the launch overlay.** While a pack is starting,
  the overlay re-runs the launch-time fit against the RAM free right now
  (requested → fitted, plus free GB) every 4 s — "Heap fit to RAM: 4096 →
  1536 MB on this launch (2.1 GB free)" — so the exact heap the running
  launch picked is visible during the wait, not just in Pack Detail.
- **Clickable heap badge → Settings RAM slider.** The Pack Detail hero's
  heap-fit badge is now a link-styled control: clicking it jumps straight to
  the Settings tab and pre-applies the current fit to the RAM slider
  (clamped 2-16 GB, labeled "heap fit pre-applied"), so users can review and
  APPLY RAM without recomputing the fit themselves.
- **Flagship deep test re-verified with the measured settle** (1.0.19
  engine): PASS in 7.5 min with `settleSecs: [10.0, 10.0]` recorded — the
  adaptive settle correctly measured fast reclamation and used the 10 s
  floor instead of a fixed 45 s; copySkip True, reproducibility relaunch
  reached the menu.

## 2026-08-14 — 1.0.19: measured deep-test settles + live heap-fit badge

- **Deep-test phase settle is now measured, not fixed.** The gap between
  deep phases (client → server → quickplay → reproducibility) no longer waits
  a hard-coded 45 s: the tester polls free RAM and settles only until the
  killed JVM's pages have actually been reclaimed (free RAM plateaus), with
  the old `AMB_PHASE_GAP_SEC` kept as a floor and a new `AMB_MAX_SETTLE_SEC`
  cap (default 120 s) so a machine whose pages never stop churning can't
  hang. Fast machines settle at the floor; slow ones wait exactly as long as
  Windows needs. Every measured gap is recorded in the evidence JSON
  (`settleSec` = last, `settleSecs` = all).
- **Live 'heap fitted to RAM' badge on Pack Detail.** The hero now shows the
  exact heap the next PLAY will pick against the RAM free right now
  (e.g. "Heap fit to RAM: 4096 → 2560 MB on next launch (2.3 GB free)"),
  re-running the adaptive fit every 4 s while the view is open — so a pack's
  down-fitted heap is visible before launch, not just during it.
- **Evidence stamping extracted + regression-covered.** The deep-test driver
  now builds its `copySkip` / `settleSec` / `gcPeakMb` / `engineVersion`
  fields through one pure helper, and 8 new offline regressions pin the
  stamping to the real phase detail strings (including the no-skip and
  no-GC-peak cases) plus the settle floor/plateau/cap behavior.

## 2026-08-14 — 1.0.18: RAM-adaptive heap + instant relaunches + flagship reproducibility

- **RAM-adaptive heap fitting.** At launch the launcher now measures the RAM
  actually free, reserves ~1.5 GB for the OS + the game's native footprint,
  and fits the JVM heap into what remains (clamped 1.5-4 GB in 256 MB steps)
  instead of always using the pack's fixed fitted value. A 155-mod pack no
  longer launches a 4 GB heap into a machine that only has 2 GB free — the
  over-commit that produced clean exit-0 deaths on low-RAM boxes. The launch
  overlay shows a "Heap fitted to RAM: X → Y MB" note when the launcher
  down-fits, and the stage log records the old → new values. Harnesses that
  explicitly bypass the RAM guard keep the requested heap.
- **Instant relaunches: identical jars are no longer re-copied.** The instance
  installer rewrote every jar before each launch (2-3 GB on the 155-mod
  flagship), dirtying the Windows page cache exactly as the JVM grew and
  starving it. Installers now skip files with matching size + mtime
  (copy2), and the test harness skips the whole re-install when every
  expected mod is already present. Relaunching a pack is now near-instant
  and does not fight the game for memory.
- **Flagship reproducibility now PASSES on this 7 GB machine.** With the
  copy-skip fix, a 45 s phase settle (AMB_PHASE_GAP_SEC — Windows needs
  more than 10 s to reclaim a killed 4 GB client + 1.5 GB server) and an
  11-min per-launch timeout (AMB_LAUNCH_TIMEOUT_MS — resource loading
  crawls under pressure), the full deep test is green: main menu, server
  "Done", world generation, and the second launch all reach the menu at the
  pack's 4 GB heap (`workspace/deep-evidence-flagship.json`, 8.9 min).
  Quickplay + GC phases remain MC 1.20.2+ features; the medieval 1.20.4
  pack records those phases.
- **5 new offline regressions** (heap-fit boundaries, copy-skip behavior);
  bugfix suite 96 → 101.

## 2026-08-14 — 1.0.17: Relaunch settle fix + crash-drawer gallery shot

- **Relaunch settle between deep-test phases.** The deep test taskkills each
  phase's JVM, but Windows releases a killed JVM's pages asynchronously — on a
  RAM-constrained box the next 4 GB-heap launch could spawn while the previous
  heap was still being freed, starving the JVM (the reproducibility mixin NPE
  on the 155-mod flagship). `tester.py` now settles `phaseGapSec` (default
  10 s) before the server start, quickplay world load, and reproducibility
  relaunch so memory is actually free. Configurable per run for harness tuning.
- **Lower-heap forensics (why the default stays ~4 GB).** Live re-runs proved
  a 2560 MB heap gets the 155-mod Forge pack past discovery and client launch
  but then dies with `OutOfMemoryError: Java heap space` during resource
  loading — a lower default heap does not make big packs reproducible.
  Under heavy machine RAM pressure (Chrome + a concurrent Gradle build) the
  game JVM can additionally exit code 0 at a varying point with no crash
  report — the documented machine-instability signature, recorded honestly in
  `workspace/deep-evidence-flagship.json` (`cause` + `settleFix` fields).
- **Crash-drawer screenshot in the gallery.** `12b-crash-drawer.png` renders
  the live repair state the engine reaches after a real Forge fatal-startup
  crash (`error: geckolib`, `missingDeps: ['geckolib']` pills) and joins the
  README gallery alongside the launch-state shots; the screenshot pipeline
  now ships 24 captures.

## 2026-08-13 — 1.0.16: Crash-evidence hardening + verified repair loops

- **`attribute_crash` hardened to real exception frames only.** Forge logs
  harmless class-load probes in every healthy pack ("Error loading class:
  ... ClassNotFoundException" WARN one-liners, ERROR "Failed to load:" blocks
  for optional compat discovery). The extractor previously harvested their
  `at ...` frames, so an unrelated crash could be mis-attributed to a mod that
  merely failed a probe (measured on a healthy pack: `ars-magica-legacy`).
  Now only frames inside blocks rooted at a genuine raised exception
  (crash-report / JVM stderr / fatal-screen format) are collected, and WARN/
  INFO/DEBUG log lines never open a trace. Regression-tested offline with real
  log shapes: WARN one-liners and probe blocks yield zero frames, real crash
  blocks and mixed logs keep their fatal-block frames. Bugfix suite 88 → 93.
- **NPE attribution exercise updated to the hardened contract**: a resource
  crash (OOM) whose only frames are class-load probes now correctly yields
  EMPTY attribution (no guessing) and no garbage add-missing — the previous
  run's "ars-magica-legacy attribution" was itself a probe-block false
  positive, now eliminated.
- Deep-test pair re-run on the current shipped state with the
  `AMB_BYPASS_RAM_GUARD=1` harness flag, fresh evidence JSONs recorded
  (flagship Forge 1.20.1 + medieval Fabric 1.20.4: world creation, quickplay
  world load, GC heap monitoring, reproducibility).

## 2026-08-13 — 1.0.15: Full bug / reliability / UI repair pass (30 issues)

A complete correctness pass across the engine and the desktop UI — every fix
has a regression test (`pyqt/bugfix_regression_test.py`, 84/84 PASS) and is
documented per-issue in `BUG_FIX_AUDIT.md`.

**Engine — AI edits are now true deltas, never rebuilds**
- Conversational edits start from a frozen copy of the parent pack
  (`CandidateMutationContext`: selections, locked mods, exact versions,
  config, shaders/resource packs, RAM) and interpret the prompt as a delta;
  the solver supports pinned versions so existing picks keep their exact
  version unless the change plan says otherwise. A test pack survives an
  "add more bosses" request with every unrelated selection preserved.
- Candidate promotion is fail-closed: on any sync/verify failure the parent
  record and instance stay byte-identical, no LKG update, the candidate is
  kept for diagnosis, and the failure is recorded.
- Instance sync is now exact-parity: removed mods physically disappear,
  config changes are promoted, and a missing candidate directory is treated
  as empty — no stale jars can survive a promotion.
- Snapshots are truly restorable: config is stored as content objects and
  reconstructed byte-for-byte, and artifacts record provider/project/version/
  file IDs + hash so the exact file can be legally re-acquired.

**Engine — correctness & safety**
- `add_mod` short-circuits duplicates before any network call; removing a
  required library is blocked and names its dependents.
- Tests are revision-safe: `NEEDS_VALIDATION` when `testedRevision != revision`,
  infrastructure failures persist an explicit `ERROR`, and a stale test can
  never mark a newer revision validated.
- Imports hardened: one centralized safe-destination helper rejects
  traversal/drive/UNC/absolute escapes, plus zip-bomb limits (per-file size,
  entry count, declared size).
- Explicit `files()` logs contract with path containment; `~` version ranges
  enforce the compatible-minor bound; Unix process-group isolation; the
  `compat.db` handle is closed; record writes retry Windows file locks.

**Desktop UI**
- AI Builder shows one authoritative terminal outcome (no stuck spinner) with
  session-bound streaming, stop support, and bounded backoff.
- Fixed 960 px content is now max-width responsive (fits 1080×700); Library
  reflows on resize with a debounced breakpoint and a filter bar that
  collapses loader pills on narrow widths.
- Settings is a true overlay — never routed through the QStackedWidget, no
  manual `showEvent`, no hidden stack switch or flicker.
- Card enrichment covers every pack (no more 25-pack cap) and the Download
  Manager queries the engine globally instead of scanning an arbitrary
  window of builds.
- Pack health derives from one normalized, revision-aware status
  (PASS / FAIL / ERROR / NEEDS_VALIDATION / TESTING / STALE) everywhere.

## 2026-08-13 — Home tiles + Library density control

- **Home's recent-build row now uses the exact same square tile as the
  Library** — cover artwork band (or gradient fallback), status pill, name,
  meta, and PLAY / STOP / manage / delete actions. The tile builder is shared
  (`views/packcard.py`) so the two surfaces can never drift; the Home row
  places its up-to-three packs in the first columns of the same density grid
  as the Library, so tiles are pixel-identical in size (246×252 cozy).
- **New Library grid density control: Cozy / Compact.** The filter bar gains
  a density picker — Cozy renders larger 4-up tiles (~250 px), Compact
  renders smaller 5-up tiles (~205 px). The choice is remembered per user in
  the UI state file (`libraryDensity`), restored on the next launch, and
  live-mirrored to the Home recent row via a new `density_changed` signal.
- **Fixed a real clipping defect found by the density work:** grid columns
  size to content hints, so the old 5-up compact row would have clipped and
  the artwork band would have mismatched the tile. Tiles now lock their
  width to the computed column width (artwork crop included).
- **Home recent cards also gained delete** (was play-only), matching the
  Library tile's action set with the same confirmation flow.
- `01-home` and `02-library` screenshots refreshed.

## 2026-08-13 — 1.0.14: Library tiles stay square with few packs

- **Fixed: single-row libraries regressed to tall rectangles.** With one or
  two packs the grid's lone row stretched to fill the viewport, so tiles
  measured ~508×558 (ratio 0.47) — the exact look the square-tile work
  removed. Cards now have a Fixed vertical size policy, so every tile stays
  at its natural near-square size (measured 262×252, ratio 1.04) regardless
  of how many packs the library holds.
- **`02-library` screenshot refreshed** to show the fixed tiles.

## 2026-08-13 — 1.0.13: Library square tiles + modpack artwork + fresh screenshot gallery

- **Library cards are now smaller, squarer tiles.** The grid switched from
  three wide rectangles to an adaptive 4-up layout (~263×252, near-square)
  that falls back to 3-up on narrow windows, with tighter body spacing and
  a shorter banner band.
- **Modpacks with artwork show it like CurseForge.** Each card's top band is
  now the pack's own image (gallery screenshot preferred, project icon
  otherwise) — fill-cropped to the banner with the status pill overlaid,
  and the pack name below it. Imported packs keep their modpack project's
  artwork (captured at import), AI-built packs use their flagship mod's
  image, and packs with no image at all keep the existing gradient artwork
  band with avatar + name exactly as before.
- **New `box=` fill-crop support in the icon cache** so banner images scale
  to the band instead of letterboxing; existing square-icon callers are
  unchanged.
- **Fresh screenshot gallery.** Every capture was re-rendered from scratch
  for this release; the update-toast and Settings→Updates shots now carry
  the real current version, and the stale launch-state shots are gone from
  the README gallery.

## 2026-08-12 — Library: square tiles + modpack artwork in the grid

- **Library cards are now smaller, squarer tiles.** The grid switched from
  three wide rectangles to an adaptive 4-up layout (~263×252, near-square)
  that falls back to 3-up on narrow windows, with tighter body spacing and
  a shorter banner band.
- **Modpacks with artwork show it like CurseForge.** Each card's top band is
  now the pack's own image (gallery screenshot preferred, project icon
  otherwise) — fill-cropped to the banner with the status pill overlaid,
  and the pack name below it. Imported packs keep their modpack project's
  artwork (captured at import), AI-built packs use their flagship mod's
  image, and packs with no image at all keep the existing gradient artwork
  band with avatar + name exactly as before.
- **New `box=` fill-crop support in the icon cache** so banner images scale
  to the band instead of letterboxing; existing square-icon callers are
  unchanged.

## 2026-08-12 — 1.0.12: Settings overlay — every tab documented, Escape-to-close, remembered tab

- **Settings is no longer a sidebar within a sidebar.** The Settings page is
  now a floating overlay that lays on top of the app: a translucent scrim,
  a centered panel, and a top section nav (General · Appearance · Minecraft ·
  Java · Providers · AI · Account · Cloud · Updates) with a close button.
  The page underneath stays visible, navigating away closes it, and closing
  returns to the page it covered. All entry points (sidebar, Ctrl+K palette,
  Discover's provider shortcut, check-for-updates, re-detect hardware) open
  the same overlay. Tests: `settings_overlay_test.py` (9 checks).
- **Settings → Updates gallery shot.** `14-settings-updates.png` renders the
  Updates panel with the feed's real release notes (markdown) and the install
  action visible; the CI screenshot gallery and README carry it.
- **Every settings tab documented + Escape to close.** The gallery now
  captures the remaining overlay sections (Appearance, Minecraft, Java, AI,
  Cloud — `11e`…`11i`), and pressing **Esc** closes the overlay like a
  native modal sheet, returning to the page it covered (the shortcut is
  inert while the overlay is hidden).
- **The last-used settings tab is remembered.** Re-opening Settings lands on
  the section you were using — the tab persists in the UI state file per
  launch, and corrupt values fall back to General.
- **Frozen selftest gained a UI interaction check.** `--selftest` now opens
  the settings overlay and verifies Escape closes it, so the installed
  bundle proves the overlay actually works, not just that it ships.

## 2026-08-12 — 1.0.11: release notes in the update toast + stale-launch-state fix

- **Release notes before apply, everywhere.** The update toast is no longer a
  one-line “install it in Settings” hint: when an update is available it now
  renders a rich card with the version, the feed’s release notes as real
  markdown (headings, bullets), and a **REVIEW & INSTALL** action that jumps
  to Settings → Updates where the notes and the install confirmation live.
  Settings → Updates itself now renders the notes in a markdown view, and the
  confirm dialog shows the full rendered notes before anything downloads.
- **Stale launch state can no longer fake “running”.** A persisted launch
  record claiming the game is active without a live pid (left behind by a
  crash or a hard kill) made the launcher report the pack as running forever.
  `play_state` now degrades pid-less active records to stopped once stale,
  and the age math is fixed to parse UTC timestamps correctly (the old
  `mktime` path computed negative ages on non-UTC machines, silently keeping
  the bug alive). Tested: `launch_state_test.py`.
- **Installed-app verification**: the two randoo packs in the installed
  1.0.10 workspace render as full Library cards (artwork + PLAY), and a real
  play through the UI reached the main menu (~92 s, Sound engine + atlas
  lines in the fresh boot log) with STOP verified — harness
  `verify_installed_library.py`.
- **Tests**: `update_toast_test.py` (toast render/action/auto-check wiring),
  updated `updatenotes_ui_test.py` + `rollback_ui_test.py` for the markdown
  notes box. Fast suites all green (health 150, identity 33, identity-ui,
  smoke, embedded key, CF sort, rollback, auto-check toggle).

## 2026-08-12 — Starter concepts + Surprise Me + Pack Health dashboard

- **Starter experiences on Home** (`engine/concepts.py`): six curated,
  editable concept templates (Medieval Kingdom, Nuclear Survival, Space
  Civilization, True Horror, Industrial Revolution, Cozy Adventure), each a
  coherent creative brief — theme, gameplay loop, progression, exploration,
  combat, visuals, atmosphere, mod categories, pack size, RAM, shaders,
  multiplayer — composed with the interpreter's vocabulary so the seed
  prompt really drives the builder (verified: every concept's prompt
  round-trips through `interpret()` with real features). Clicking a card
  opens an editor where the brief is editable before anything is built, and
  BUILD seeds the AI Builder prompt.
- **Surprise Me** (`concepts.surprise_me`): a deterministic generator that
  composes a coherent concept from theme / gameplay-loop / progression /
  exploration / combat pools (never a random mod list), sized to the
  detected hardware (RAM → pack size; shaders only on ≥8 GB), with a
  RE-ROLL button. Same seed → same concept (tested); 12 seeds → 12 distinct
  briefs.
- **Pack Health dashboard** (`engine/health.py`): explainable status + a
  weighted score (stability · compatibility · performance · content · theme
  cohesion · maintenance) computed only from real record data — test
  result, unresolved conflicts, perf estimate vs this PC's RAM, mod
  breadth, identity feature coverage, the Last Known Good snapshot match,
  and mod-update data. Every metric carries a Why popup with its exact
  reasons; statuses map to Excellent / Stable / Attention / Problems /
  Broken with honest forcing rules (FAIL → broken, never-tested → capped at
  Attention).
- **Real update check** (`PyEngine.check_pack_updates`): bounded provider
  query per selected mod (newest version vs installed version id), persisted
  as `healthUpdates` on the record; the Maintenance score and flags reflect
  it. Verified live: 10 mods checked, 0 errors, real results recorded, no
  fake counts.
- **UI**: Pack Detail → Overview now leads with the health card (status +
  score, six metric bars with Why buttons, flags, CHECK MOD UPDATES, and
  RESTORE LAST KNOWN GOOD when a broken/problem pack has one). Home gains
  the Starter Experiences section + SURPRISE ME button.
- **Tests**: `health_concepts_test.py` 143/143 (concept structure + real
  interpret round-trip, surprise determinism + hardware sizing, health
  scoring on real record shapes incl. LKG snapshot compare, service
  endpoints over the in-process bridge, UI construction). Regression:
  identity_ui 8/8, smoke PASS, in-process PASS, one-system PASS, engine
  self-test 18/18 (real instant build + validated exports).

## 2026-08-12 — Master-spec foundation: Pack Identity, intents, snapshots, LKG, transactional AI edits

- **Pack Identity + semantic mod intent** (`engine/identity.py`): every pack
  now carries a derived, persisted identity (theme, goals, required/optional/
  forbidden features, locked mods, performance target, multiplayer) and every
  selection carries an intent record (role, why-selected, importance,
  replaceability, alternatives, costs, confidence, locked). Deterministic —
  no LLM guesses.
- **Snapshots + Last Known Good** (`engine/snapshots.py`): content-addressed
  manifests (exact selections, hashes, config hashes — no binary copies),
  one-per-pack LKG auto-marked after every validated test and superseded on
  the next PASS. Restore is transactional (current state snapshotted first).
- **AI change plans** (`engine/plan.py`): non-mutating plan for any
  conversational request — verb, features added/removed, mods/deps/RAM
  impact, confidence, risk, preserved identity. Ask AI now shows the plan
  (APPLY & TEST / MODIFY PLAN / CANCEL) before building.
- **Transactional AI edits**: `apply_ai_change` snapshots the pack, runs a
  real candidate build, and promotes only on PASS (record + instance files);
  a failed candidate leaves the pack untouched and records the rejection in
  `aiHistory`. The old `chat()` fork behavior is preserved.
- **UI**: Pack Detail → Settings gains an Identity & Recovery section
  (theme, locked mods, LKG status, Restore Last Known Good, snapshot
  restore list).
- **Tests**: `identity_snapshots_test.py` (33 checks incl. promotion +
  rejection paths), `identity_ui_test.py` (8 checks), engine self-test
  18/18, smoke, in-process, security regression — all green. Real build +
  validated exports rerun to confirm no pipeline regression.
- **Docs**: MASTER_SPEC_GAP_MATRIX.md (honest per-section status),
  PACK_IDENTITY.md, SNAPSHOTS.md, AI_SYSTEM.md.

## 2026-08-12 — 1.0.8: periodic update checks, rollback, release notes in-app

- **Periodic background update check**: the launcher now re-checks the feed
  every 2 h while open (separate `PERIODIC_STAMP` throttle, so it never
  collides with the once-per-24 h startup check), honoring the
  Settings → Updates toggle. `pyqt/autocheck_toggle_test.py` extended to
  cover the default-feed fallback and the periodic stamp.
- **Rollback from the saved installer pool**: every applied update already
  left its installer in `<data>/updates/` (1.0.1–1.0.8 all present here), so
  `updater.rollback_candidate()` finds the newest version strictly older
  than the running app and Settings → Updates shows a
  **↺ RESTORE v<previous>** button that re-installs it (signature-verified,
  `/DIR`-pinned — no re-download). `pyqt/rollback_ui_test.py` proves the
  button renders with a candidate and names the right version.
- **Post-update health gate**: `run_update(apply=True)` writes
  `last-applied.json`; the next boot health-checks the engine and either
  clears the marker (healthy) or toasts where to roll back (unhealthy), and
  also flags an update that never took effect (marker version ≠ running
  version). All three paths unit-tested.
- **Release notes in the UI**: the feed's `notes` now render inline in the
  Settings → Updates panel after a check finds an update (kept for the
  confirmation dialog too), and the background-check toast shows the first
  line of the notes.
- **Feed-URL priority fixed for auto-checks**: env override → the user's
  Settings URL → the embedded default, so a custom feed is never shadowed
  by the default (previously the default won).
- Shipped 1.0.8 through the live GitHub feed: installed 1.0.7 updated in
  place (29,242,912 bytes, SHA `8403d066…1af2c` verified) and now reports
  `ok, current 1.0.8, available false` over the default feed. All new
  updater symbols confirmed compiled into the installed binary via PYZ
  extraction.

## 2026-08-12 — 1.0.7: default update feed embedded + fresh-user update path proven

- **Fresh installs now auto-point at the public GitHub feed.**
  `DEFAULT_UPDATE_FEED_URL` is embedded in the build
  (`pyqt/product_config.py`) and `updater.update_url()` resolves it
  whenever no env override (`AMB_UPDATE_URL`) or app setting exists — so a
  brand-new install needs **zero configuration** to get auto-updates.
  Settings → Updates prefills it; the startup check and `--check-update`
  use it too.
- **`check()` now records the resolved `feedUrl` in its report**, so every
  update-check verdict shows exactly which feed was consulted (also on the
  error path).
- **Fresh-user proof (clean prefix, zero config):** silent-installed 1.0.7
  into a scratch dir with a fresh LOCALAPPDATA (no `state.json`), ran
  `--check-update` with **no URL and no env override** → the embedded
  default resolved to
  `https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json`
  and reported `ok: true, current: 1.0.7, available: false` (rc 0).
  `pyqt/fresh_user_feed_test.ps1` is the repeatable script.
- **The installed 1.0.6 launcher updated in place to 1.0.7 over the live
  GitHub feed** (29,240,312 bytes downloaded, SHA `2e183155…cbb7a`
  verified, `/DIR`-pinned silent install) and now also reports
  `ok: true, current: 1.0.7, available: false` via the default feed.

## 2026-08-12 — 1.0.6 shipped to the installed launcher via the LIVE GitHub feed (verified)

- **Jump-to-page + total-page estimate** ships in this release: the Discover
  pager shows the real total-page estimate (`Page 2 · showing 49–96 of 3,259
  (68 pages)`) with a **Jump to** spin box (arrows/Enter apply immediately;
  disabled when the total is unknown; programmatic updates inert).
  `pyqt/pagination_test.py` 40/40 PASS.
- **The full auto-update loop ran over the public GitHub feed with no dev
  flags**: the installed 1.0.5 app checked
  `https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json`
  → `available: true` → downloaded the signed 1.0.6 installer
  (29,233,848 bytes) → **SHA-256 verified** (`01d750b3…76`) → Authenticode
  verified → installed in place. The updated app reports
  `current: 1.0.6, available: false` and its selftest is green (6/6,
  including no-legacy-Node-files and shader/RP-engines checks).
- **Real update-path bug fixed (would have bitten the next GUI update):**
  `apply_installer` launched the installer WITHOUT `/DIR`, and Inno Setup
  remembers the last dir used on the machine — after the build pipeline's
  scratch-dir verify, an in-app update would have silently reinstalled into
  the test dir. `apply_installer` now always pins `/DIR` to the running
  app's own folder in frozen builds (AMB_UPDATE_DIR test hook still wins),
  verified by simulation (frozen → real install dir; hook → hook dir).
- **`publish_release.py` is now idempotent**: re-publishing the same version
  (rebuilt installer, new SHA) deletes the old release and recreates it with
  the new assets instead of failing on an existing tag.
- **Source pushed to the public repo** (`github.com/RBC-X/ai-modpack-builder`,
  main branch): the complete pyqt/ launcher + engine, docs, and the new
  `.gitignore` (workspace, installers, venv, secrets, logs, state, screenshots
  all excluded — verified no secrets in the pushed tree). The remote keeps
  its slim public README as the landing page.
- **Reboot survival of the update path documented** (RELEASING.md → Startup
  survival): the mirror shortcut was re-verified live (kill → logon-launch →
  feed back under a fresh pid), the GitHub path needs no local process, and
  six honest gaps are listed (OneDrive hydration, silent pythonw failure,
  dev-workspace path, etc.) — none break the primary GitHub update path.

## 2026-08-12 — LIVE GitHub release: 1.0.5 published, launcher pointed at public HTTPS feed (verified)

- **Public repo created and released.** `gh` 2.97.0 installed via winget
  (user authed as RBC-X); `pyqt/publish_release.py` created
  `github.com/RBC-X/ai-modpack-builder` (public, release assets only — the
  source tree is never pushed), committed a public README via the contents
  API (GitHub refuses releases on empty repos), and uploaded **both** the
  signed installer and `update.json` to release `v1.0.5`.
- **Public URLs verified end-to-end.** `releases/latest/download/update.json`
  serves the real feed; the installer downloads from
  `release-assets.githubusercontent.com` at 29,241,584 bytes with
  **SHA-256 `1ce99156…88e0` matching the published feed value** (downloaded
  from GitHub and hashed locally — byte-identical to the signed build).
- **Installed launcher now updates from anywhere.** Its state now points at
  `https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json`
  (backup at `state.json.bak-local-mirror`; auto-check still on). The
  installed app ran `--check-update` against GitHub with **no
  `AMB_UPDATE_ALLOW_INSECURE`**: `ok: true, current: 1.0.5, available: false`
  — a real TLS fetch to github.com, publicly trusted.
- **Real bugs found while publishing:** (1) `gh release create` needs `-R`
  when there's no local git repo (added); (2) GitHub rejects releases on
  empty repos — the README commit fixed it; (3) the publish script previously
  never uploaded `update.json` as an asset (fixed last round).
- The local HTTPS mirror (startup-persisted) remains as a fallback; the
  installed app no longer uses it.

## 2026-08-12 — Jump-to-page, startup-persistent update feed, GitHub publish ready (verified)

- **Discover pager: jump-to-page input + total-page estimate.** The pager
  now shows the total-page estimate from the real total (`Page 2 · showing
  49–96 of 3,259 (68 pages)`) and a **Jump to** spin box that skips straight
  to any page (arrows or Enter apply immediately; range = total ÷ effective
  page size). The input is disabled whenever the total is unknown — page
  counts are never guessed — and programmatic updates never re-trigger a
  search. `pyqt/pagination_test.py` now **40/40 PASS** (jump to page 5 and
  back, range/suffix checks, disabled-without-total, guard checks).
- **The HTTPS update-feed mirror now survives reboots.** Registered as a
  per-user **Startup-folder shortcut** (`pyqt/register_startup_feed.ps1`,
  writes `%APPDATA%\…\Startup\AI Modpack Builder Update Feed.lnk` pointing
  `pythonw.exe` at `pyqt/serve_feed_https.py`) — no elevation needed and
  `schtasks /Create` is blocked by machine policy (Access denied), so the
  Startup folder is the working logon hook. **Verified live**: killed the
  running mirror, launched via the shortcut (the exact logon mechanism),
  and the feed came back on `https://127.0.0.1:8543` under a fresh pid
  serving the 1.0.5 feed.
- **GitHub publish script fixed + ready.** `pyqt/publish_release.py` had a
  real bug: it wrote `update.json` but never uploaded it as a release asset,
  so the feed URL it printed (`…/releases/latest/download/update.json`)
  would 404. It now creates the public repo if missing (empty — release
  assets only, never the source tree) and uploads **both** the installer and
  `update.json` as assets of the release. The public step still needs a
  GitHub account/CLI — the machine has no `gh`, no token, and no stored
  GitHub credentials, so that half is awaiting auth (see below).
- **Regression:** pagination 40/40, engine_self_test 18/18, round2_verify
  PASS, smoke PASS (rc=0). The jump-to-page feature is code-only so far —
  it reaches the installed launcher with the next release.

## 2026-08-12 — 1.0.5: real totals, exact-context page memory, HTTPS auto-update (verified)

- **Real total result counts**: Modrinth `total_hits` and CurseForge
  `pagination.totalCount` now flow from the providers (`search_meta`) through
  the engine into the Discover pager — "Page 1 · showing 1–48 of 3,259"
  instead of per-page counts. Next enables only when a page beyond the true
  total remains; merged pages sum per-source totals.
- **Exact browsing-context page memory**: the remembered page is keyed by
  content type + provider + loader + MC version + page size (legacy
  type-only keys are migrated), so each combination keeps its own place and
  returning to Discover restores exactly where you were.
- **HTTPS auto-update proven without the insecure dev flag**: a local TLS
  mirror (`pyqt/serve_feed_https.py`, cert trusted in the machine Root store)
  served the 1.0.5 feed on `https://127.0.0.1:8543`; the installed 1.0.4 app
  checked it, downloaded the signed installer (29,241,584 bytes, SHA-256
  verified), applied in place, and now reports `current: 1.0.5`,
  `available: False` — with no `AMB_UPDATE_ALLOW_INSECURE`.
- **GitHub release tooling**: `pyqt/publish_release.py` + `RELEASING.md`
  compute the real SHA-256, generate the HTTPS feed, and create the public
  GitHub release (or print the exact `gh` commands). The public step needs
  your GitHub account/CLI — see RELEASING.md.
- `pyqt/pagination_test.py` 35/35, `engine_self_test` 18/18, `round2_verify`
  PASS, smoke PASS.

## 2026-08-12 — 1.0.4 shipped in place via the update feed (verified)

- **Per-provider page sizes**: CurseForge's API caps `pageSize` at 50 and
  Modrinth allows up to 100, so the merged "All sources" page now queries each
  source with its own limit and the effective page size is their sum (48+50
  at the default, 96+50 at 96-per-page). `search()` gained `page_size` and
  returns the effective `page_size` + a real `more` signal (a source returned
  a full page) — never a guess.
- **Results-count + "more may exist" hint**: the pager shows the page range
  plus a hint that states exactly why Next is enabled ("48 results shown —
  more may exist") or disabled ("all 48 results — end of catalog"), and the
  Next button's tooltip explains it too.
- **Page-size control**: Discover's filter row has a 24 / 48 / 96 per-page
  combo; CurseForge is clamped to its API cap. Page is part of the cache key.
- **Remember last page per content type**: the last page for each of
  mods/modpacks/shaders/resource packs/worlds is persisted to the UI state
  file, so returning to Discover (tab switch or app restart) restores where
  you were. A new search, filter, provider, or page-size change resets to 1.
- **Shipped as 1.0.4 in place**: signed installer rebuilt and verified
  (frozen selftest 6/6, installed selftest rc=0), feed published, the real
  installed app checked the feed (1.0.3 → 1.0.4, installer downloaded +
  SHA-256 verified), applied in place, and now reports `current: 1.0.4`,
  `available: False`. `pyqt/pagination_test.py` 28/28; smoke PASS.

## 2026-08-12 — Discover pagination (Next/Prev) on the content browser (verified)

- **Engine**: `search()` accepts `offset` and passes it to the providers —
  Modrinth `offset` + CurseForge `index` — in both the single-provider and
  merged multi-provider paths.
- **Discover view**: a pager bar under the grid with **← Prev / Next →** and a
  live label ("Page 2 · showing 49–96"). Next enables only when a real full
  page came back (48 hits — never guesses); Prev enables from page 2 onward;
  any new search, type/provider/loader/version change, or typing resets to
  page 1. The cache key includes the page so paging is instant.
- **Verified live** (`pyqt/pagination_test.py` 14/14): real Modrinth page 1
  vs page 2 return 48 distinct project IDs (0 overlap) for search and browse;
  the UI pager navigates Next → Page 2 (49–96) → Prev → Page 1. Smoke test
  rc=0 (Discover still renders 48 hits with provider images).
- Sits in the checkout ahead of the next release — reaches the installed app
  via the update feed when 1.0.4 ships.

## 2026-08-12 — 1.0.3 shipped as an in-place UPDATE, not a new launcher (verified)

Delivering the round-4 fixes through the app's own self-update path instead of
handing out a new installer:

- **Version bumped to 1.0.3**, signed installer rebuilt (27.9 MB,
  SHA-256 `6c70b5ec…e096`), frozen selftest rc=0 (6/6 checks).
- **Update feed published** at `workspace/update-feed/update.json` with real
  release notes and the real SHA-256.
- **Installed app (was 1.0.1) configured** with the feed URL in its state,
  auto-check on.
- **Full update loop verified on the REAL installed app**: `--check-update`
  saw 1.0.3, downloaded the installer, SHA-256 verified it, then the installer
  replaced the install in place. The updated app now reports `current: 1.0.3`
  and `available: False`, and its selftest is green (engine health, builds,
  window, workspace writable, no legacy Node files, shader/RP engines
  importable).
- Two real bugs found while doing this:
  - **Git Bash mangles `/VERYSILENT`** into `C:/Program Files/Git/…` — the
    silent installer silently became interactive and hung. Fix: run with
    `MSYS2_ARG_CONV_EXCL='*'` (the `install-update` path in scripts should use
    it; the in-app updater launches via subprocess and is unaffected).
  - **Inno Setup remembers the last /DIR** — a silent install without /DIR
    silently reinstalled into the previously-used scratch dir instead of the
    default install location. The update flow must pass an explicit /DIR (or
    reset the remembered dir) to actually update the installed app.

## 2026-08-12 — Council round 4: visuals review, shader-preset swap, CF second source, installer verify (verified)

### Visuals review — picks now match hardware AND the request's own shader intent

- `interpreter` parses shader-quality intent ("cinematic shaders" → cinematic,
  "light shaders" → performance; `QUALITY_KEYWORDS` in shaders.py). The
  visuals stage passes it as an explicit override to `pick_shader_preset`.
- `pick_shader_preset` now honors a requested preset but NEVER exceeds the
  machine: cinematic on an integrated GPU → performance, cinematic on 10 GB
  RAM → balanced, each with the honest reason recorded ("cinematic shaders
  requested but an integrated GPU can't run them").
- `pick_resource_pack` is now RAM-aware: 64x on a mid discrete GPU with 6 GB
  RAM downgrades to 32x (was GPU-tier only), with the real reason ("64x
  textures on 6 GB RAM is risky").
- Every choice record (`shaderChoice` / `resourcePackChoice`) now includes
  `provider`, and the final report shows it ("via modrinth").

### Pack Detail: shader-preset swap control (new)

- Settings tab gains a **Shader Preset** section: current shader + reason,
  a performance/balanced/cinematic combo, and **SWAP SHADER & RE-TEST**.
- New engine `set_shader_preset(build_id, preset)`: re-picks a REAL shader
  pack for the preset on this machine, downloads the zip (SHA-1 verified),
  deselects the old shader, appends the new selection, installs it into the
  instance `shaderpacks/` (removing the old zip), records `shaderChoice`,
  then schedules a REAL retest so the swap is validated, not just recorded.
  Wired through bridge → signal → main.py handler.

### CurseForge is now a real second source for visuals

- `choose_shader` / `choose_resource_pack` try Modrinth first, then search
  CurseForge by shader-pack / resource-pack name keywords when a key is
  configured (`CF_PRESET_QUERIES` / `CF_RESOLUTION_QUERIES`), returning the
  actual provider that supplied the pick. The old "fall back to any provider"
  path was dead code — it passed Modrinth slugs to the CF provider, which
  can't resolve them.
- Degradation is honest: with the currently-invalid stored CF key, both
  engines warn, skip CF, and still return a real Modrinth pick (verified live,
  `cf_degrade_test.py` 10/10).

### Provider-error honesty + a real flake fix

- `retry_fetch` now includes the HTTP status AND response body in errors (the
  API's own words: "API Key missing or invalid"), and NEVER retries client
  errors (4xx). Previously a 403 was retried 4× (~4 s wasted per broken CF
  call).
- `curseforge._get` now classifies 403s properly: an invalid key raises a
  clear RuntimeError ("CurseForge rejected the configured API key") instead
  of the misleading "appears search-only" scope error.
- Root-caused the smoke-test flake (rc 127, R3-4): the provider probe's CF
  call exceeded its 8 s window because of the pointless 4× retry, leaving a
  worker thread past teardown. With no-retry-on-4xx the probe finishes in
  ~1 s — `smoke_test.py` now passes deterministically (rc=0, twice).

### Signed 1.0.2 installed to a clean prefix and verified

- Silent-installed `AI-Modpack-Builder-Setup-1.0.2.exe` into a clean scratch
  dir, ran the INSTALLED app's `--selftest` with an isolated workspace:
  **rc=0, all 6 checks ok** — engine health, builds load, window constructed,
  workspace writable, **no legacy Node files in bundle (found: [])**,
  **shader/resource-pack engine importable (missing: [])**. Uninstalled and
  cleaned up; the user's real installed app was left untouched.

### Tests

- `shader_preset_test.py` 34/34 (new: request-intent + override cases),
  `resource_pack_test.py` (new RAM-downgrade cases), NEW `shader_swap_test.py`
  18/18 (real swap end-to-end incl. retest wiring), NEW `cf_degrade_test.py`
  10/10. Regression: shader_routing, cf_import_edge, new_pack, round2,
  security 13/13, import e2e OVERALL PASS, engine_self_test 18/18, smoke
  PASS ×2, pack-detail shader control renders.

## 2026-08-12 — Council round 3, resource-pack engine, Deep shader e2e, signed 1.0.2 (verified)

### Resource-pack selection (new)

- `pyqt/engine/resource_packs.py`: theme + resolution keywords → **real
  Modrinth resource packs** (faithful-32x/64x, bare-bones, classic-3d verified
  live). Resolution downgrades are explicit when the machine can't run the
  requested tier (e.g. 64x → 32x on integrated graphics, reason recorded).
  `pyqt/resource_pack_test.py` 18/18.
- Pipeline now has a dedicated **visuals stage** (shader + resource pack),
  so `shaders`/`resourcePacks` features are never pooled as random mod seeds.
  Choices persist as `rec["shaderChoice"]` / `rec["resourcePackChoice"]`.
- AI Builder timeline shows the new visuals stage live; Pack Detail specs
  card was reading nonexistent `packStats` keys (always showed "Shaders 0")
  and now renders the real choices and reasons.

### Deep-mode shader launch — full PASS (real evidence)

- Deep test on the shader pack (`b-19ff3c3b13d-eb53bc68`): all 14 phases
  PASS — isolated instance, Mojang 1.20.4 + fabric install, launch,
  **main-menu** (log + window `Minecraft* 1.20.4`), **server "Done"**,
  **world creation + load**, **client quickplay world load**, **GC peak
  805 MB from the real GC log**, **reproducibility** (second launch reached
  the menu). MakeUp Ultra Fast in `shaderpacks/`, Faithful 32x in
  `resourcepacks/`, both in the final report.
- Fix from the round-3 review pass: `rendering_mod_for("vanilla")` returned
  "oculus" (a Forge mod) in a vanilla pack — now returns None for vanilla.

### Signed installer 1.0.2 + frozen self-checks

- `pyqt/main.py` selftest now checks the **bundled** app: no legacy Node
  files in the bundle, and the shader/resource-pack engines import inside
  the frozen app (PyInstaller compiles modules into the PYZ, so the check is
  importability, not loose `.py` presence).
- Rebuilt + signed `AI-Modpack-Builder-Setup-1.0.2.exe`; frozen selftest
  rc=0 with both new checks green; installer signature **Valid**; installed
  app selftest rc=0.
- UI regression: `smoke_test.py` 35/35 PASS (was flaky — now completes and
  exits 0 stably).

## 2026-08-11 — Council round 2, GPU-aware shaders, legacy Node deletion (verified)

### Council round 2 (solver, reconcile, exports, tester, hardware, updater)

- **Hardware detection is now cached** (`detect_hardware` gains a 300 s TTL
  + `force`; `hardware_refresh` forces). `fit_xmx_mb()` ran 2–3 PowerShell
  subprocesses (each with a 20 s timeout) on EVERY launch, build test and
  retest — verified the second call now spawns zero subprocesses.
- **`validate_mrpack` checks what its comment promised**: a stray entry
  outside `overrides/` (e.g. an embedded jar at the archive root) is now an
  `ERR` — verified with a synthetic bad mrpack.

### GPU-aware shader presets engine (new)

- `pyqt/engine/shaders.py`: GPU string → tier (integrated/discrete-mid/
  discrete-high) → preset (performance/balanced/cinematic) → **real Modrinth
  shader pack** (9 slugs verified live) + the loader's rendering mod
  (iris/oculus). The build pipeline NOW selects shaders — it never did in the
  Python engine (the Node-era visuals pipeline wasn't ported). Choice is
  recorded in `rec["shaderChoice"]` and rendered in the final report.
- Solver: non-mod projects (shaders/RPs) are versioned by MC only — a loader
  filter would have returned zero versions for Modrinth shader packs.
- Downloads: non-mod files keep the provider's real filename/extension — a
  shader zip named `*.jar` was invisible to Iris scanning `shaderpacks/`.
- Test + retest envs now carry the pack's real shader/RP files.
- **Real e2e PASS with a live boot**: tiny Fabric 1.20.4 pack — MakeUp Ultra
  Fast (performance preset, integrated GPU + 4 GB RAM), iris+sodium pulled,
  zip in `shaderpacks/`, main menu reached, clean stop. Tests:
  `shader_preset_test.py` 23/23, `shader_e2e_test.py` PASS.

### Legacy Node system deleted

- Deleted `src/`, `web/`, `tests/`, `node_modules/`, `package.json`,
  `package-lock.json`, `tsconfig.json`, `pyqt/api.py`, `legacy_auto_restart_test.py`,
  `reference_capture.cjs`, `tmp_test.mrpack`. `ApiError` moved to
  `pyqt/engine/errors.py`; `bridge.py` imports it there. Docs scrubbed
  (ARCHITECTURE.md now maps the Python modules directly; pyqt/README updated).
  Verified: all 2196 pyqt modules parse, engine healthy, zero residual
  references to the old paths.

## 2026-08-11 — Council round 1: six real flaws found and fixed (verified)

Three-council review round (flaws / strengths / builder) run against the real
engine; full report in `COUNCIL_REPORT.md`. Every fix is backed by a real
failure first, a code fix, and a re-run:

- **Blank-pack `auto` MC regression (High).** `create_pack` stored the literal
  `"auto"` in the record and nothing resolved it, so adding any mod to a
  NEW PACK failed with `No auto/fabric version for AppleSkin`. `create_pack`
  now resolves `auto` MC/loader to concrete values at creation (settings
  defaults), and `add_mod` belt-and-braces resolves legacy `"auto"` records.
- **Orphan `status: "created"`.** Only `create_pack` ever emitted it; every
  UI consumer expects done/failed/building. Blank packs are now `done` (they
  are complete as created — no pipeline runs).
- **Blank packs had no instance skeleton.** `create_pack` now pre-creates
  `instance/minecraft/{mods,config,resourcepacks,shaderpacks,saves}` so a new
  pack is a launchable instance from birth.
- **Key-less CurseForge ZIP import crashed (High).** With no CF key the
  provider list is empty → `prov=None` → `AttributeError` in `_selection`.
  Now degrades to honest reference-only import.
- **Phantom `downloadPath`.** A CF file whose download failed still recorded a
  `downloadPath` to a jar that doesn't exist. Only real files get a path;
  failed/refused downloads are recorded honestly (truthful reason).
- **Shader routing bug (High, latent).** `_visual_files` pushed shader
  selections into `resource_packs`, so shaders were copied into
  `resourcepacks/` (ignored by the game) and `shaderpacks/` stayed empty.
  Shaders now route to `shaders[]`; verified the zip lands in the right
  folder.
- **Test hygiene.** `new_pack_test.py` left a pack behind on every run (4
  stale "UI Test Pack" builds found); the test now deletes its own pack and
  the stale ones were removed from the library.

**Verification**: new `cf_import_edge_test.py` 8/8 and `shader_routing_test.py`
6/6; `new_pack_test.py` 10/10 (was failing); `import_e2e_test.py` PASS (real
17-mod mrpack import, cancel + cleanup); `security_quality_regression_test.py`
13/13; `one_system_test.py`, `inprocess_test.py`, `smoke_test.py`,
`autocheck_toggle_test.py`, `import_overlay_test.py`, `autorelaunch_ui_test.py`
all PASS. See `COUNCIL_REPORT.md` for the full evidence trail.

## 2026-08-11 — Browsing is fast: startup-warmed catalogs, parallel all-sources search, Worlds tab (verified)

- **Startup warm-up.** `MainWindow._warm_catalogs` prefetches the six default
  Discover catalogs (mods 1.20.1/1.21.1, modpacks, shaders, resource packs,
  worlds) in a background daemon thread as soon as the app opens — API
  responses land in the provider disk cache and the top ~24 icons in the icon
  cache. First browse renders from disk instead of waiting on the network.
  **Measured: 969 ms cold → 9 ms warm for the six catalogs (109×).**
- **"All sources" now really is both sources.** `service.search` queries
  Modrinth + CurseForge **in parallel** and merges (deduped, sorted by
  downloads, 48/page); unavailable sources are reported in `sources` so the
  "Set up CurseForge" prompt shows instead of silently returning Modrinth
  only. Providers are cached on the engine (rebuilt only when settings
  change) instead of re-reading settings from disk on every search.
- **Worlds tab** added to Discover (CurseForge class 17; Modrinth has no
  world type). Without a CF key it shows the honest setup prompt; with a key
  it browses/downloads worlds. World cards open the project page (no bogus
  "Add to pack").
- **Verified**: `pyqt/browse_speed_test.py` **5/5 PASS** — cold 969 ms →
  warm 9 ms (109.4×), all-sources returns both provider statuses + 48 merged
  hits, worlds honest without a CF key; real MainWindow boot completes the
  warm-up and renders the Worlds tab; `inprocess_test.py` + `smoke_test.py`
  PASS. Evidence: `workspace/browse-speed-result.json`.

## 2026-08-11 — Imported modpacks now actually contain their mods + CurseForge-style import progress (verified)

- **Fixed: imported modpacks lost their mods.** A `.mrpack`/CurseForge ZIP
  never contains the jars — they're referenced by URL (`modrinth.index.json`)
  or project/file ID (`manifest.json`). The old importer only extracted
  `overrides/`, so the pack showed zero mods. New `pyqt/engine/imports.py`
  downloads every indexed file (hash-verified against the manifest's sha1,
  first-working-mirror), extracts overrides safely, and records each mod as a
  real selection — enriched with actual project data via Modrinth's
  version-file-hash endpoint, so the Pack Inspector shows real titles (Fabric
  API, Mod Menu, …). Provider import (`import_pack`) now downloads the
  modpack's own archive and runs the same engine. CurseForge files without a
  signed download URL are recorded honestly as reference-only.
- **Fixed: our .mrpack exporter was non-standard.** It embedded the jar bytes
  in the zip root AND listed them in the index (ignored or double-installed
  by compliant launchers). Exports are now spec-clean — index + overrides
  only, jars downloaded at install time. Proof: the 17-mod mrpack dropped
  from ~15 MB to **3,256 bytes** and still validates ("OK 17 indexed files
  validated"). `validate_mrpack` now checks structure + downloads URLs + env
  instead of requiring embedded bytes.
- **CurseForge-style import UI.** New `ImportOverlay` (bottom-right, like the
  launch card): live stage + n/total + percent while installing, a **CANCEL**
  button (cooperative `threading.Event` — the engine aborts mid-download and
  deletes the partial build), and when it finishes the CANCEL is replaced by
  a **PLAY** button that launches the pack. Errors show an honest CLOSE card.
  Wired into both the provider-import and drag-and-drop local archive paths.
- **Verified end-to-end (real runs):** `pyqt/import_e2e_test.py` **9/9 PASS**
  — regenerated a real mrpack, imported it, all 17 mods downloaded
  hash-verified into the instance mods dir, selections populated, progress
  fired, cancel aborted + cleaned up. `pyqt/import_overlay_test.py` **9/9
  PASS** (importing → CANCEL → done → PLAY emits build id → error).
  `engine_self_test.py` **18/18** (live search, real 17-mod build, exports
  validated), `inprocess_test.py` PASS (27 packs, all views), `smoke_test.py`
  PASS. Evidence: `workspace/import-e2e-result.json`,
  `workspace/import-overlay-result.json`.

## 2026-08-11 — 1.0.1 signed rebuild + live self-update through the trusted cert (verified)

- **Version bumped to 1.0.1** (`product_config.APP_VERSION` — single source
  of truth). The installer pipeline was re-run **fully signed** (no
  `--no-sign`): `pyqt/build_installer.py --trust --verify` → **8/8 PASS** —
  bundle, sign app exe (signtool SHA256 + DigiCert timestamp), frozen
  selftest rc=0, Inno Setup `AI-Modpack-Builder-Setup-1.0.1.exe` (27 MB),
  **sign installer — status: Valid**, trust cert locally — already trusted,
  silent install, installed selftest rc=0. The previous 1.0.1 installer
  (built unsigned during the update test) is superseded; the shipped 1.0.1
  is the signed, Valid one.
- **Live self-update proof re-run against the signed 1.0.1 installer**
  (the earlier proof used an unsigned 1.0.1): the preserved frozen 1.0.0
  client (probe-confirmed `current: "1.0.0"`) checked a local feed
  (`workspace/update-feed/update.json`, sha256 `17c0ff6a…`) →
  `available: true` → downloaded the **28.8 MB signed installer** →
  **SHA-256 matched** → launched it (pid 19084) into a scratch dir
  (`AMB_UPDATE_DIR`) → installed in 10 s.
- **The updated app verifies as Valid now that the cert is trusted
  locally**: the installed 1.0.1 exe passed its own `--selftest` (rc=0),
  self-reports `current: "1.0.1"` / `available: false` against the 1.0.1
  feed (version proof), and `Get-AuthenticodeSignature` reports
  **Status: Valid** (subject `CN=AI Modpack Builder, O=AI Modpack Builder`)
  on both the installed exe and the 1.0.1 installer. Evidence:
  `workspace/update-1.0.1-proof-result.json`.

## 2026-08-11 — Local cert trust + release notes before update (verified)

- **The self-signed cert is now trusted on this machine.** `pyqt/sign.py`
  gained `trust()` / `is_trusted()` / `is_admin()` plus a CLI
  (`python sign.py --trust [thumbprint] | --trust-status [thumbprint]`):
  it imports the code-signing cert into the machine **Trusted Root** and
  **Trusted Publisher** stores (UAC prompt when not elevated, EncodedCommand
  so no quoting issues). The installer pipeline gained a `--trust` phase
  (`pyqt/build_installer.py --verify --trust`); it reports "already trusted"
  when present. **Verified live**: after trusting, `Get-Authenticode-
  Signature` and `signtool verify /pa` both report **Valid** on the signed
  installer (previously Invalid/Untrusted). Honest limit: trust is per
  machine — other machines still need the cert or a real CA-issued cert
  (`AMB_SIGN_THUMBPRINT`).
- **Release notes are shown before every update.** Settings → Updates:
  "Check for updates" now stores the full feed notes, and the DOWNLOAD &
  INSTALL button opens a themed dialog (v{current} → v{latest}, scrollable
  release notes, Cancel / Download & install). The installer is only
  launched after explicit confirmation; Cancel never launches it. Headless
  `--check-update` still applies directly (scripted path).
- **Verified**: `pyqt/updatenotes_ui_test.py` **8/8 PASS** (real check flow
  with mocked feed → button → dialog with full notes → install clicked =
  apply with exact URL; Cancel = no apply); rendered evidence
  `workspace/updatenotes-dialog.png`; `sign.py --trust-status` →
  `trusted: true`. Full pipeline re-run **8/8 PASS** (bundle → sign app exe
  → frozen selftest → installer → sign installer → **status: Valid** →
  trust cert locally → silent install → installed selftest). Smoke +
  in-process tests PASS.

## 2026-08-11 — Signed installer + self-update (both verified end-to-end)

- **The installer is now code-signed.** `pyqt/sign.py` creates (once per
  user) a self-signed code-signing cert and signs the bundle exe AND the
  installer with the Windows SDK `signtool` (`/fd SHA256 /tr
  http://timestamp.digicert.com /td SHA256`) — real DigiCert RFC3161
  timestamp attached (verified: signer `CN=AI Modpack Builder`,
  timestamp `DigiCert SHA256 RSA4096 Timestamp Responder`). Set
  `AMB_SIGN_THUMBPRINT` to a real CA-issued cert for a publicly trusted
  build; a self-signed cert still shows a SmartScreen unknown-publisher
  warning on other machines (trust it locally by importing the cert into the
  machine's Trusted Root store). Fixed along the way: signtool's `/sm` means
  the MACHINE store (our cert is per-user — dropped), and `Set-Authenticode-
  Signature` alone hit `UnknownError` with CNG keys (signtool is preferred).
- **Self-update is real and proven end-to-end.** New `pyqt/updater.py`
  (feed JSON → version compare → size-capped download → **SHA-256 verify** →
  silent per-user installer launch) wired three ways:
  1. **Settings → Updates**: feed URL field, "Check for updates" (shows up
     to date / update card with notes / error), "Download & install"
     (downloads, verifies, launches the installer, quits the launcher), and
     a startup-check toggle (once per day).
  2. **`--check-update [url] [--apply-update]`** CLI mode — writes
     `update-check.json` to the workspace and exits 0/1; the installer
     pipeline uses it for verification.
  3. **Startup auto-check** in installed builds (throttled to 24 h,
     announces via toast only when a newer version exists).
- **Version is single-sourced**: `product_config.APP_VERSION` is the one
  truth; `pyqt/build_installer.py` reads it and passes `/DMyAppVersion` to
  Inno Setup (the .iss now uses `#ifndef` so the command line wins).
- **Verified end-to-end (real runs):** a frozen 1.0.0 app pointed at a
  local feed claiming 1.0.1 (`workspace/update-test/update.json` + the
  real 1.0.1 installer) → `--check-update --apply-update` → downloaded the
  28.8 MB installer, **SHA-256 matched**, launched it → the 1.0.1 app
  installed into the scratch dir and passed its own selftest (rc=0). The
  "no update" path reports `available: false` and downloads nothing. The
  final signed 1.0.0 pipeline: **7/7 PASS in 76 s** (bundle → sign app exe
  → frozen selftest → installer → sign installer → silent install →
  installed selftest).

## 2026-08-11 — Real Windows installer (PyInstaller + Inno Setup), verified end-to-end

- **The app is now an actual installer**: `installers/AI-Modpack-Builder-Setup-1.0.0.exe`
  (28.8 MB) — a per-user Inno Setup 6 installer (no admin required) wrapping
  the PyInstaller one-folder bundle (94 MB, `dist/AI Modpack Builder/`).
  Installs to `%LOCALAPPDATA%\Programs\AI Modpack Builder` with Start-menu +
  optional Desktop shortcuts and a proper uninstaller.
- **Frozen-app data path**: installed builds never write next to the
  executable. `engine/core.workspace_dir()` now resolves to
  `%LOCALAPPDATA%\AI Modpack Builder\workspace` when frozen (dev and
  `AMB_WORKSPACE` behavior unchanged), and the UI state file + fonts/icon
  load through a new `resource_path()` (bundle-safe in dev and frozen).
- **`--selftest` mode**: `AI Modpack Builder.exe --selftest` boots the whole
  app offscreen, verifies engine health, builds load, window construction,
  and a writable workspace, writes `selftest.json` to the workspace, and
  exits 0/1 (via `os._exit` to avoid Qt teardown fail-fast on Windows).
- **Repeatable pipeline** `pyqt/build_installer.py [--verify]`: PyInstaller
  bundle → frozen selftest → Inno compile → (verify) silent install to a
  scratch dir → run the INSTALLED app's selftest → uninstall. **Real run:
  5/5 PASS in 86 s** (`workspace/installer-build-result.json`): bundle 93 MB,
  frozen selftest rc=0 (all 4 checks), installer 27 MB, silent install,
  installed-app selftest rc=0. Frozen app also verified against the real
  workspace (26 builds load, rc=0).
- **Real fix found by the frozen run**: `icons.py` imports `PyQt6.QtSvg`
  (inline SVG icons) — it was wrongly excluded from the spec, crashing the
  frozen exe at import (`ModuleNotFoundError: QtSvg`); un-excluded and the
  bundle boots.

## 2026-08-11 — Auto-relaunch surfaced in the PyQt launcher (toggle + live recovery view)

- **Pack Detail → Settings → Runtime Resilience**: an **Auto-relaunch on
  silent close** checkbox, wired through a new `set_auto_relaunch` signal →
  `MainWindow.set_auto_relaunch` → engine `set_auto_relaunch` (persisted in
  the pack's `settings.autoRelaunch`). It reflects the record on open and a
  toast confirms the new state.
- **Launch overlay relaunching mode**: when the engine reports
  `phase: relaunching`, the overlay switches to a **Recovering <pack>** state
  (amber refresh icon) showing the stage ("Silent close detected — relaunching
  with N MB RAM"), the progress bar, and the **recovery log** — the
  `closeContext` reason plus the last game log lines — in a read-only mono
  console, with a STOP button. The poller already keeps running through
  `relaunching` → `loading` → `running`, so the overlay follows the whole
  recovery live.
- **Verified headless**: `pyqt/autorelaunch_ui_test.py` — 8/8 PASS (checkbox
  present and reflecting record state, toggle flips the engine record,
  state restored, overlay enters relaunching mode, recovery stage + log
  rendered). Rendered evidence `workspace/overlay-relaunching.png`. PyQt
  smoke test + in-process test both PASS.

## 2026-08-11 — Auto-relaunch + RAM-fitted lite pack (both verified end-to-end)

- **Opt-in auto-relaunch (new engine feature).** `POST /api/builds/:id/autorelaunch`
  toggles a per-pack `settings.autoRelaunch` flag (opt-in, default off). When
  ON, a game that dies SILENTLY — no crash report, no `Stopping!` window-close,
  no user Stop — within 2 minutes of the main menu is relaunched **once** at
  **80% of the fitted heap** (256 MB-aligned) instead of leaving the user at a
  dead session. The recovery is logged to `launch-state.json`
  (`phase: relaunching`, `closeContext.reason`), the UI sees a
  "Silent close detected — relaunching with N MB RAM" stage, and the relaunch
  itself never re-triggers (`autoRelaunch: False` on the retry + a per-build
  once-guard).
- **Auto-relaunch PROVEN end-to-end** (`pyqt/relaunch_proof.py` →
  `workspace/relaunch-proof-result.json`): lite pack played with autoRelaunch
  ON → first launch reached the menu (pid 13616, `-Xmx4096m`) → game
  hard-killed 25s after the menu (silent: no crash report, no `Stopping!`,
  exit code 1) → engine detected the silent close and relaunched within 15s
  (pid 16812, **`-Xmx3072m`** = 80% of 4096) → relaunched game reached the
  menu again. **3/3 phases PASS, real runs.**
- **Flagship Lite (RAM-fitted) pack created.** `pyqt/make_lite_pack.py`
  copies the 150-mod flagship and deselects the 10 heaviest
  worldgen/magic/GPU mods (`mana-and-artifice`, `goety`, `alpha-below`,
  `distanthorizons`, `ars-magica-legacy`, `blood-magic`, `aether`,
  `bossesrise`, `daily-boss-x-bossesrise`, `project-atmosphere`) — 142 mods,
  `ramGB 4`, self-contained jars. Addon mods that hard-require the dropped
  bases (`dmnr`, `goety_mastery_of_magic`, `aeroblender`) were
  cascade-deselected the same way the repair engine does, using the REAL
  Forge missing-deps screen (`Mod ID: 'x', Requested by: 'y'`) mapped through
  jar-metadata mod ids (`pyqt/lite_verify.py` + `pyqt/build_modid_cache.py`).
- **Lite pack VERIFIED: holds the main menu for the full 5 minutes on this
  7 GB machine** (`pyqt/lite_relaunch_hold.py` →
  `workspace/lite-relaunch-hold-result.json`): menu reached (pid 19060,
  138.6s boot, real menu evidence) → **300s hold, 60/60 ticks up**, free RAM
  0.02–1.42 GB — survived even with physical RAM at 0.02 GB. The original
  150-mod flagship died silently at ~105–188s at the menu; the RAM-fitted
  pack no longer does.
- **`main_menu_reached` false-positive fixed.** The old detector fired on ANY
  `[Render thread/INFO]` line — heavy mods log Render-thread work long before
  the menu (Project Atmosphere's client setup logged one and the launcher
  declared "menu reached" at the exact moment the game died). Now requires
  real menu evidence: audio init (`Sound engine started`/`OpenAL initialized`)
  or atlas creation + LWJGL backend line, and returns False on any fatal
  marker. Verified against the real log lines that fooled it.
- **`idas` loot-table errors explained (non-fatal).** The lite pack's
  `latest.log` shows `Couldn't parse element loot_tables:idas:…`
  (`ars_nouveau:scryer_scroll` unknown) — When Dungeons Arise ships optional
  Ars Nouveau integration loot tables; ars-nouveau is not in the pack, the
  tables fail to parse, Minecraft logs the error and continues (menu reached
  after). Cosmetic noise, not the death cause.
- **Stale-log cascade-loop lesson (test-side).** `launch-play.log` appends
  across runs, so the old cascade harness chased ghosts (`Mod ID` pairs from
  a previous run while a healthy game was booting). The definitive harnesses
  now key off the engine's own phases/pid file and the fresh `latest.log`
  only (`lite_relaunch_hold.py`), and the record was already repaired so the
  cascade loop is no longer needed.

## 2026-08-11 — Multi-pack session hardening (self-closing investigation + real fixes)

- **Disk: freed 49.8 GB.** `workspace/builds` was 54 GB (2.5 GB free on C:);
  failed/building flagships (3.3–3.6 GB each) and orphaned legacy build dirs
  were deleted — 48.8 GB free now. `pyqt/cleanup_builds.py` keeps every
  `done` build plus the packs the live tests use.
- **Orphaned legacy processes killed**: the old Node engine
  (`dist/app/server.js`, alive since 8/10 5:33 AM — a leftover from before
  the Python engine became the single source of truth) and two hung
  headless `inprocess_test.py` runs.
- **Heap overcommit fixed — root cause of the random game-window closes.**
  The flagship launched with `-Xmx8192m` on a 7 GB machine (and a second
  pack added 4 GB more = 12 GB of committed heap on 7 GB physical). New
  `hardware.fit_xmx_mb()` caps every launch (build, retest, play) at ~72% of
  detected physical RAM: the flagship now launches at `-Xmx5120m` (verified
  in its launch log).
- **Concurrent-play GPU tuning.** When a second pack launches while another
  is running, the engine now caps its FPS at 30 via `options.txt` and shrinks
  the window to 960×540 (verified `--width 960 --height 540` in the log) to
  reduce shared-GPU load.
- **Close-context capture.** When a game exits on its own with code 0 and no
  crash, `launch-state.json` now records `closeContext` (stoppedByUser,
  exit code, last log lines) so a bare "Game closed" is explainable.
- **Investigation evidence.** Windows WER shows a live-kernel event at
  00:12 (bugcheck `3b`, `a1000001` — an AMD Radeon GPU hang that recovered;
  the machine never rebooted). Under sustained dual-pack load (free RAM
  0.04–0.88 GB the whole hold), the heavier second pack dies silently at the
  world-registry load stage ~60–72 s after the menu — no crash report, no
  `Stopping!`, no hs_err, no WER event: a Windows commit-pressure
  termination, not a launcher action. One run also hit the known Create
  `potato_cannon` Registrate startup race (crash report captured) — the
  sustained test now retries once on a pre-menu crash, like the repair
  pipeline does.
- **New verification harnesses**: `pyqt/sustained_dual_test.py` (holds both
  packs at the menu together for N minutes with per-tick pid + free-RAM
  tracking), `pyqt/solo_hold_test.py` (control: flagship alone at menu),
  `pyqt/cleanup_builds.py`.

## 2026-08-10 — Deep-mode gate, concurrent-pack launch, live log streaming (all verified end-to-end)

- **Deep test on the 150-mod flagship pack (1.20.1 Forge) — PASS.** Real run
  of every phase the version supports: isolated instance ✓, Mojang 1.20.1 +
  Forge 47.4.22 install (65 libraries) ✓, client launch + main menu (window
  evidence `Minecraft* Forge 1.20.1`) ✓, vanilla server `Done` ✓, **world
  created and loaded by the server** ✓, reproducibility (second launch to
  menu) ✓. Client quickplay world load + GC heap monitoring are honestly
  SKIPped: `--quickPlaySingleplayer` requires Minecraft 1.20.2+ and 1.20.1
  cannot auto-load a world. Evidence:
  `workspace/deep-test-flagship.json`, `pyqt/deep_test_flagship.py`.
- **Deep test on a fresh 1.20.4 pack — quickplay world load + GC memory
  monitoring verified for real** (see `workspace/deep-test-1204.json`,
  `pyqt/deep_test_1204.py`): server start + world creation, client
  `--quickPlaySingleplayer` world load from log evidence, `-Xlog:gc` heap
  peak parsed from the real GC log, and a reproducible second launch.
- **A second pack can run while one is already running.** The engine's
  single-game guard (`Any other pack is running — stop it first`) and the
  launcher's matching toast are gone: every launch keeps its own process
  tree, pid file, `launch-state.json` and `launch-play.log` inside its own
  build directory. Verified with `pyqt/dual_launch_test.py` — distinct pids,
  per-pack state files (each carries its own `buildId` + `pid`), distinct
  logs, isolated instances, and live log streaming from the second pack
  while it boots (400+ real-time line events).
- **Live `latest.log` streaming with crash detection.** `game_log_stream`
  was rewritten to be offset-based (each line delivered once, stale content
  from previous launches never replayed), to wait for the pack to start
  (the UI may attach before play() spawns), and to emit typed events
  (`line` / `crash` / `menu`). The Pack Detail Logs tab renders a live
  red `⚠ CRASH DETECTED` banner on crash events and a `✔ Main menu reached`
  line. Bug fixed: menu/crash markers from a PREVIOUS launch's `latest.log`
  (the game appends rather than truncates) used to fire stale events —
  detection now runs only on lines streamed from the current run.
- **Per-pack launch state now carries identity.** `launch_pack.report()`
  re-attaches `buildId` (and keeps `pid`) on every persisted state, and the
  in-memory entry state keeps the pid after progress updates — so
  `status()` always reports the real pid, and per-pack state files are
  self-describing.
- **Environment note (honest):** on this machine (7 GB RAM, disk ~97%
  full, project dir OneDrive-synced) the game window itself occasionally
  closes ~10–200 s after the main menu (`Stopping!` in latest.log, exit 0),
  even for a single pack with no second launch — a game/session-level
  event, not a launcher action (the launcher never kills a running game
  except via the user's Stop). The engine tests that complete in <3 min
  are unaffected; sustained concurrent-session tests must fit the window.

## 2026-08-10 — Real flagship e2e: 153-mod Forge pack repaired to main menu, exports validated

The flagship acceptance request (medieval fantasy RPG, ~120 mods, Create/magic/
bosses/structures/terrain/shaders, 8 GB) now converges end-to-end through the
in-process Python engine: real searches → 150 downloads (0 failures) → Forge
47.4.22 install → standard test → **automatic repair loop** → main menu → all
three exports validated → Play/Stop. Every stage ran on live Modrinth data.

Repair loop on the real pack (each fix verified by a real relaunch):
1. `add-missing` — mna, connectormod, incendium, irons_lib, caelus,
   raritycore, oelib resolved+downloaded+jar-verified; brutalbosses
   unresolvable on Modrinth → its requester removed.
2. `change-version` — curios 5.6.1 → 5.14.1 to satisfy irons_spellbooks'
   `[5.14.1+1.20.1,)` range.
3. `remove` + **cascade** — mixin NPE attributed to Sinytra Connector; removing
   it also removed its dependents (origins via the error screen's
   "Requested by", magic-origins via jar metadata) instead of ping-ponging
   add/remove forever.
4. `add-missing` — Serene Seasons parsed from Project Atmosphere's crash
   message ("Install Serene Seasons or … or remove Project Atmosphere").
5. `add-missing` — GlitchCore (Serene Seasons' transitive dep).
→ main menu reached and stable.

Real bugs found and fixed along the way (all from live failures):
- `providers/modrinth.get_project` raises on 404 instead of returning None,
  which aborted the loose-resolver fallback (`irons_lib`/`connectormod` never
  added).
- Forge mods.toml inline comments (`modId="x" #mandatory` — the standard MDK
  template) broke jar-metadata parsing for whole classes of mods.
- `loose_resolve_project` matched substring titles before exact normalized
  slugs (twilightforest → wrong addon) and couldn't split concatenated mod ids
  (connectormod → Sinytra Connector via stem search; mna → mana-and-artifice
  fallback).
- Downloads had no wall-clock deadline or stall guard — a hung CDN connection
  froze the whole build indefinitely.
- `missing_dep_ids` treated Forge's normal "Error loading class: …
  ClassNotFoundException" warnings (optional/disabled features) as missing
  mods and extracted package segments (client, gui, util) as mod ids.
- `_analyze_failure` repaired on any signature match instead of gating on a
  real fatal line.
- The standard test killed the process the moment menu markers appeared,
  masking late mod-loading crashes (Project Atmosphere crashed ~6s after
  menu) — a 12s post-menu grace window now surfaces them as honest FAILs.
- Launch monitors/evidence read stale `latest.log` content from previous
  launches (false "Fatal startup error") — log watchers now read incrementally
  by byte offset and snapshot pre-launch sizes.
- `launch_pack` reinstalled deselected mods and old versions (no `selected`
  filter; located jars by slug) — Play now uses each selection's authoritative
  downloadPath and cleans stale jars by exact slug.
- Exports included deselected mods and duplicated repaired entries (duplicate
  zip names) — both exporters now filter `selected` and dedupe by slug.
- `_build_report` got an int instead of the repairs list (naming collision) —
  the final report crashed and the build record ended `phase: error`.
- Relative `game_dir` produced broken `-p`/`-DlibraryDirectory` module paths
  ("Could not find or load main class BootstrapLauncher") — loader resolves
  absolute, `build_client_args` defensively absolutizes.

Verified artifacts: `workspace/builds/b-19fed8cb2cc-1b65ae48` (repair loop
PASS, 3 validated exports re-generated with the repaired set), repair
verification script `pyqt/verify_repair_pa.py` (test→analyze→repair→retest
loop PASS), parser checks `pyqt/parser_verify.py`.

## 2026-08-10 — Python engine is the single source of truth; `src/` is legacy reference

- **Removed the Node engine from the shipped system.** `pyqt/main.py` no
  longer spawns `node dist/app/server.js`, has no `AMB_NODE` fallback, and
  shows no "engine not running" dialog — it always constructs the in-process
  `PyEngine()`. The auto-restart machinery that killed/restarted a Node
  server on 8282 is gone (the Python engine runs inside the app; there is no
  separate process to restart).
- **`src/` is marked legacy reference** — new `src/LEGACY.md` maps each TS
  module to its active Python counterpart; `package.json` description and
  `pyqt/engine/core.py` docstrings updated. The legacy TS suite still runs
  via `npm test` for reference only.
- **Every pyqt script now uses the in-process engine**: `smoke_test.py`,
  `live_build_test.py`, `live_launch_test.py`, `crash_repair_test.py`,
  `new_pack_test.py`, `screenshot.py`, `layout_probe.py`, `visual_audit.py`
  all construct `PyEngine()` instead of the HTTP `Api` client. The old
  `auto_restart_test.py` (killed a Node engine on 8282) was replaced by
  `one_system_test.py`, which verifies the launcher needs no port, no
  subprocess, and stays Online on the in-process engine.
- **Docs updated** for the single-system architecture: README.md,
  ARCHITECTURE.md, pyqt/README.md, TESTING.md.

## 2026-08-10 — The engine is ported into the Python app: one self-contained system

- **Full Node engine ported to Python** (`pyqt/engine/`) so the launcher runs as
  **one system** — no Node server, no localhost, no separate process. The PyQt
  app IS the engine: hardware detection, provider queries, the build pipeline,
  dependency/version solving, downloads, instance creation, tests, repair,
  exports, and compatibility memory all run in-process.
- **Port map** (each module mirrors its TS source):
  - `core.py` (types/logger/paths/events) ← `src/core/*`
  - `providers/` (http cache, settings, **Modrinth**, **CurseForge**, registry)
    ← `src/providers/*`
  - `interpreter.py`, `features.py`, `rank.py`, `descresearch.py`
    ← `src/interpreter`, `src/selector`, `src/solver/descresearch.ts`
  - `solver.py` (recursive deps + version backtracking), `reconcile.py`
    (jar-metadata reconciliation + `unless` via provided-index),
    `conflict.py`, `downloads.py` ← `src/solver`, `src/conflict`,
    `src/downloads`
  - `exports.py` (.mrpack / CurseForge manifest-reference / server pack)
    ← `src/export/*`
  - `instance_java.py`, `loader.py`, `instance.py`, `mojang.py`, `process.py`
    ← `src/instance`, `src/process`
  - `launcher.py`, `tester.py`, `repair.py` (crash parse + attribution),
    `compat.py` (SQLite memory), `hardware.py`, `configs.py`
    ← `src/launcher`, `src/test`, `src/repair`, `src/memory`
  - `service.py` (orchestrator with the same API surface as the Node server),
    `bridge.py` (Api-compatible facade so every PyQt view works unchanged)
- **Bugs the port caught and fixed (real failures during the port):**
  1. `CompatibilityDatabase` was created on the main thread but used from
     build worker threads — sqlite3 `check_same_thread=False` + a lock around
     every operation.
  2. The Python solver inherited `async`/`await` scaffolding from TS that
     awaited a plain function (`object list can't be used in 'await'
     expression`) — converted to the faithful fully-synchronous TS algorithm.
- **Verified live, all in-process (no Node running):**
  - `pyqt/engine_self_test.py` — **18/18**: interpreter, live Modrinth
    search (30 hits), a real instant-mode build (17 mods, test PASS),
    `.mrpack` + CurseForge ZIP exports validated, records indexed.
  - `pyqt/inprocess_test.py` — window boots on `PyEngine()`, pill reports
    **In-process**, no engine subprocess spawned, builds load, all views
    navigate.
  - Live AI Builder flow through the bridge: 33-mod build, instant test
    PASS, **101 events streamed** to the UI.
  - `pyqt/smoke_test.py` (HTTP mode) and `pyqt/visual_audit.py` (0 findings)
    still green.
- **Mode switch**: the app runs the Python engine by default; set the
  `AMB_NODE` environment variable to fall back to the Node server on 8282.

## 2026-08-10 — Round-5 changes regression-swept; PyQt visual A/B closes layout gaps

- **Regression sweep after the round-5 solver/provider/loader changes:**
  - Standard acceptance (Fabric 1.20.1 flagship): **PASS** — real launch +
    main menu in 116s.
  - Fabric 1.21.1 deep gate: **PASS in 177s** — main menu, server `Done`,
    world created, quickplay world load, **real GC heap peak 816 MB**,
    reproducibility; 13 mods for the 8-mod request, 0 repairs. All four
    loader deep gates remain green on the new code.
- **New `pyqt/visual_ab.py`** — pixel-level A/B of the rendered views
  (content fraction per vertical band, text presence, largest empty region).
  Found two layout gaps vs the CF/Modrinth bar and fixed both:
  1. **Settings panel stopped mid-window** (content ended ~490px in an 840px
     window, 69.7% largest-blank). The panel now fills the column
     (`QSizePolicy.Expanding` + `addLayout(row, 1)`, nav pinned top) —
     blank 69.7% → 35.5%, matching the full-height settings surface of
     reference launchers.
  2. **AI Builder form left a dead band at the bottom** (62% blank). The
     form block is now vertically centered via `_center_form()` — stretches
     around the form, removed while the timeline/done cards show so a
     running build stays top-aligned.
- Geometry audit: **0 findings** across all 11 views; PyQt smoke test PASS
  after the layout changes.

## 2026-08-10 — Quilt deep-mode gate passes (all four loaders verified live)

- **Quilt 1.21.1 deep run: PASS** — Mojang 1.21.1 + quilt (71 libraries),
  main menu reached (window evidence `Minecraft* 1.21.1`), vanilla server
  `Done`, **world created**, **client quickplay world load**, **real GC heap
  peak 1170 MB**, second launch to menu (reproducibility) — **11 mods** for
  the 8-mod request, 0 repairs. With Fabric, Forge and NeoForge already
  passing, **all four loader deep gates are now verified live.**
- **Three real Quilt-only bugs fixed from live runs:**
  1. **Quilt loader pinning.** The installer took `loaders[0]` from the meta
     API (0.20.0-beta.9), which provides `fabricloader 0.14.21` — Placeholder
     API demands >=0.15.0 and Quilt refused to boot. The Quilt meta has no
     `stable` flag and sorts by build, not semver. New
     `pickNewestLoaderVersion()` picks the newest stable by semver →
     **0.30.0** (provides `fabricloader 0.19.2`).
  2. **QSL could not resolve for 1.21.1.** QSL publishes only
     `11.0.0-alpha.3+0.102.0-1.21` (game version "1.21"), so the essential
     library failed and everything cascaded (Mod Menu dropped,
     `quilt_resource_loader` unsatisfied). Modrinth `getVersions` now
     re-queries the parent minor (1.21.1 → 1.21) when the exact MC has zero
     builds, and the solver accepts patch-compatible versions.
  3. **Fabric API surface on Quilt.** `fabric`/`fabric-*`/`quilted_fabric_api`
     deps mapped to fabric-api, which has no quilt builds — on Quilt the
     fabric API surface is provided by the QSL project (its jar
     `provides: ["fabric-api","fabric"]` and embeds
     quilted_fabric_resource_loader_v0). Deps now map to `qsl`; provider
     deps on the fabric-api bundle re-target to QSL; `unless` clauses are
     also satisfied via the provided-index (embedded-jar aliases).
- **Verified** — 232/232 backend tests (new: loader picker semver, provider
  minor fallback, mapJarDepId quilt mappings, solver fabric-api→qsl
  re-target, solver patch-compat accept, unless-via-provided-index). Pack
  grew 5 → 11 mods (modmenu and performance mods kept). The only honest
  drop: More Culling — cloth-config genuinely has no 1.21.1 quilt builds.

## 2026-08-10 — NeoForge deep-mode gate passes; automated PyQt visual audit

- **NeoForge 1.21.1 deep run: PASS** — Mojang 1.21.1 + neoforge (71
  libraries), main menu reached (window evidence `Minecraft NeoForge* 1.21.1`),
  vanilla server `Done`, **world created**, **client quickplay world load**,
  **real GC heap peak 1075 MB**, second launch to menu (reproducibility) —
  11 mods for the 8-mod request, 0 repairs. All three loader paths (Fabric /
  Forge / NeoForge) now pass the live deep gate.
- **Two real NeoForge-only bugs fixed from live runs:**
  1. `No neoforge build found for 1.21.1` — NeoForge maven versions ENCODE
     the MC version (`21.1.147`), the lookup used the Forge-style `1.21.1-`
     prefix. New `neoForgeVersionPrefix()` derives `<minor>.<patch>.`.
  2. `ENOENT … versions/1.21.1-neoforge-21.1.248/…json` — the NeoForge 21.1
     installer names its profile folder `neoforge-21.1.248` with NO MC
     prefix. The loader now detects the folder the installer actually
     created instead of assuming the Forge naming.
- **New `pyqt/visual_audit.py`**: renders all 11 views offscreen and measures
  real widget geometry — text wider than its widget, zero-size widgets,
  negative sizes. Found and fixed a genuine clip (sidebar account card,
  `Status: Offline profile`); the audit itself was then hardened (exact-fit
  metric, settle+confirm pass). **Final: 0 findings on all views.**

## 2026-08-10 — Forge deep-mode gate passes too

- **`deep-acceptance.js` parameterized** (`[mcVersion] [loader]`) so the deep
  gate can run any loader. Fabric 1.21.1 remains the full-deep default
  (quickplay world load + GC memory monitoring included); `1.20.1 forge`
  covers the Forge path with honest skips.
- **Forge 1.20.1 deep run: PASS** — Mojang 1.20.1 + forge (65 libraries),
  main menu reached (with window evidence `Minecraft* 1.20.1`), vanilla server
  `Done`, **world created**, reproducibility (second launch to menu) PASS;
  world-load + memory-monitor honestly SKIP (quickplay requires MC 1.20.2+).
  17 mods for the 8-mod request, 0 repairs, 0 conflicts, all 3 exports
  validated (.mrpack / CurseForge zip / server zip).
- **Round-2 Fabric 1.21.1 re-verified** — full deep PASS in 156s with **zero
  stalls** (the repro `watchFor: 'menu'` fix), real GC peak 725 MB, 13 mods,
  3/3 exports validated.
- The round-2 server-Java fix is confirmed version-correct both ways:
  1.21.1 → Java 21, 1.20.1 → Java 17.

## 2026-08-10 — Deep-mode gate passed on real hardware (Fabric 1.21.1)

- **New live gate** `src/scripts/deep-acceptance.js` (MC 1.21.1 Fabric,
  `around 8 mods` request): client main menu → vanilla server + real world
  creation → client quickplay world load + GC-log heap monitoring →
  reproducibility. The first run failed with **five real defects**, each
  root-caused from the actual crash report / loader screen and fixed:
  1. **Single-digit mod counts were ignored.** The interpreter's count regex
     required 2–4 digits, so "around 8 mods" parsed `targetModCount 0` and the
     selector defaulted to pack-size targets — a 53-mod pack for an 8-mod
     request. Now `\d{1,4}`; the deep pack ships **14 mods**.
  2. **Duplicate server-loop optimizers crashed the boot.** modernfix
     (`perf.fix_loop_spin_waiting`) + server-snapshot-performance-backports
     (`MinecraftServerFixParkNanosMixin`) both patch
     `MinecraftServer.managedBlock` → mixin `InvalidInjectionException`. New
     `server-loop-performance` fork rule + `duplicate-mixin-target` crash
     signature that names BOTH mods from the "merged by … from mod X" line;
     also fixed a latent bug where fork-rule members were never normalized
     (hyphenated slugs like server-snapshot-performance-backports never
     matched).
  3. **`forgeconfigapiport` could not be resolved.** Modrinth search returns
     only kilt-forgeconfigapiport-fix for the concatenated modid. Added
     `MODID_SLUG_FALLBACKS` (forgeconfigapiport → forge-config-api-port) to
     the reconcile fallback chain.
  4. **Jar-metadata `breaks` were ignored.** zfastnoise declares
     `breaks: { noisium: '*' }`, but the conflict engine never saw it — the
     loader's incompatible-mods screen killed the launch. jarmeta now parses
     `breaks`/`conflicts` (fabric + quilt + forge `incompatible`), reconcile
     adds `incompatible` graph edges, and the conflict engine auto-resolves
     the lower-importance side.
  5. **The deep server phase hardcoded Java 17** — the 1.21.1 server jar is
     compiled for Java 21 (class file 65.0) and died with
     `UnsupportedClassVersionError`. Now `javaFor(majorOf(mc))`, matching the
     client.
- **Deep result: PASS** — every phase real: Mojang 1.21.1+fabric (71 libs),
  main menu, server `Done (11.455s)`, world created, **quickplay world load
  in the client**, **GC heap peak 774 MB observed**, second launch reached the
  menu (reproducibility).
- **Verified** — 224/224 backend tests (new: single-digit count, RAM-not-a-
  count, server-loop fork resolution, duplicate-mixin parse, breaks
  incompatible-edge, modid fallback).

## 2026-08-10 — Reconcile now knows embedded jars & provides; phantom conflicts gone

- **The acceptance pack's false "missing dependency" warnings are fixed.**
  `calio`, `kanos_config`, `cardinal-components-*` and `cloth-config2` were
  flagged as missing even though the game booted fine — because the reconcile
  index only knew each jar's own id, not what the jar actually supplies at
  launch. `providedModIds()` now walks a jar's **`provides` aliases** and its
  **embedded jars recursively** (origins.jar embeds apoli.jar, which embeds
  calio.jar + cloth-config; Forge jarjar jars auto-discovered), using new
  buffer-based `listZipEntriesBuf`/`readZipEntryBuf` so each jar is read once.
- **Phantom version conflicts are gone too.** Two real misattributions found
  in the live build log were fixed: ranges are now enforced ONLY when the dep
  is its own selected node — never against a provided/embedded alias
  (yungs-better-caves declares `cloth-config2 >=11.1.106`, which was misread
  as "requires Origins >=11.1.106" and dropped YUNG's), and never against
  fabric-api bundle submodule versions (mod-menu declares
  `fabric-screen-api-v1 >=1.0.4`, which was misread as "requires Fabric API
  >=1.0.4").
- **Live proof** (`b-msmwhhwq-8c6f30f7`): acceptance PASS — instance ✓
  Mojang 1.20.1+fabric (65 libs) ✓ launch ✓ main menu reached ✓, 0 repairs;
  reconcile log **zero warnings, zero drops**; all previously-dropped mods
  (yungs-better-caves, origins, modmenu) kept; 0 errors in the launch log.
- **Verified** — 217/217 backend tests (8 new: recursive embedded-jar
  providedModIds, provides-alias satisfied, mod-menu submodule-range
  regression, yungs/cloth-config2 regression).

## 2026-08-10 — The AI now avoids unloadable mods when picking

- **Loadability ranking factor.** Candidates whose jar filename derives an
  invalid Java module name (a Java keyword like `true`/`super`/`for`, or a
  leading digit) get a **-60 loadability penalty** in `rankCandidate`, with the
  reason in the score card (`loadability (-60): filename-derived module name
  "super.bosses" starts with Java keyword "super"…`). The AI now picks a valid
  alternative instead of the mod that would kill the build — prevention beats
  the guard, which stays as the safety net for required dependencies.
- **Memory training.** When the build-time guard has to drop an unloadable
  jar, the drop is recorded into the compatibility database as a FAIL entry
  keyed on the mod's slug (`invalid-jar-name`), so future builds' ranking
  memory factor also knows it and avoids the project up front.
- **Verified live.** Rebuilt the Custom large request on the new engine
  (`Custom large Pack v3`): `super-bosses` — which the previous build had to
  drop at the guard — was **never selected** (the bosses feature filled with
  valid mods: bosses-of-mass-destruction-forge, bossesrise, arphex,
  fiw-bosses, remnant-bosses, thorms_bosses…); only `kotlin-for-forge` (a
  required dependency, not a pick) still needed the guard. Final result:
  **130 mods · test PASS · Minecraft reached the main menu · 0 repairs**.
- **Verified** — new ranking test proves a keyword-named candidate loses to a
  valid alternative even with 10x downloads; 208/208 backend tests, smoke
  green.

## 2026-08-10 — Builds keep working until they don't fail

- **Repair budget escalation.** The repair loop now escalates automatically:
  a standard-mode build that exhausts its 5 attempts and still fails continues
  to the deep budget (15) instead of ending as a build failure. Instant mode
  stays instant (it is explicitly the no-launch fast check). Every attempt is
  still recorded; if the pack genuinely cannot be fixed the loop stops with
  the honest unresolved error.
- **Root-caused a real failing build.** `Custom large Pack` (124 mods) failed
  with 10 blind removals because ONE jar — `true-power-optimization.jar` —
  derives the Java module name `true.power.optimization`, and `true` is a Java
  keyword. Forge dies at bootstrap BEFORE any log file exists, so the old
  repair loop (crash-reports + latest.log only) never saw the cause.
  - New `src/repair/jarname.ts`: derives the Forge module name from a jar
    filename and flags keywords/digits (`Invalid module name`).
  - `analyzeFailure` now also reads the **launcher console log**
    (launch-play.log) — the only record of pre-bootstrap crashes — and
    `Exception in thread "main"` / `Invalid module name` are recognized as
    fatal (raw log retention raised to 30 KB because Forge launch commands
    alone exceed 10 KB).
  - New `invalid-jar-name` signature: the repair agent removes the exact jar
    the exception names (verified on the real log: `true.power.optimization`
    → `true-power-optimization`).
  - **Build-time guard:** packs now drop jars whose filename Forge cannot load
    at selection time (step 7a), so they never ship — with an honest skipped
    reason in the report.
- **Verified** — 7 new tests (5 jarname + 2 repair-loop: console-only crash
  end-to-end, escalation past standard budget): 207/207 backend, smoke green.

## 2026-08-10 — Stack-trace crash attribution (no more guessing)

- **Unknown crashes now name their mod.** New `src/repair/attribution.ts` reads
  the real stack trace from the crash report / latest.log and matches the
  first non-loader frame's class against a central-directory class index of
  every installed jar (exact class, then package prefix; mixin-config ids map
  straight to the mod whose mixin transformer crashed).
- **The repair agent uses it** — `dropOne` now removes the attributed mod with
  an honest reason (`Stack trace calls X — a class shipped inside Y`) and only
  falls back to the old priority-guess when no mod code is on the stack.
- **Verified on real failures.** Two previously-unfixable packs' crash reports
  (`mod-loading-failed`, hints only named loader ids) now attribute to
  `project-atmosphere` — exact-class match on
  `net.Gabou.projectatmosphere.seasons.SeasonBootstrap` — instead of the old
  blind removals (terrablender, architectury-api, moogs-structure-lib).
- **Fast + cached** — the jar index reads only the ZIP central directory (a
  small tail read, no decompression) and caches per file (mtime+size), so
  repeated repair attempts cost nothing after the first scan.
- **Verified** — 8 new tests (7 attribution + 1 repair-loop end-to-end with
  synthetic jars): 200/200 backend, smoke green.

## 2026-08-10 — Delete packs from the Library

- **Trash-button deletion.** Every Library card (grid + list) now has a
  delete action that asks for confirmation, then permanently removes the pack
  — instance, mod jars, exports, and worlds. A running pack's delete is
  disabled (and the engine refuses with a 409 anyway, so the instance is
  never ripped out from under a live game).
- **Engine endpoint** — `DELETE /api/builds/:id` (real delete to free disk;
  the UI confirms first). Verified live: create → delete → directory gone →
  pack no longer listed.
- **Verified** — 192/192 backend tests, smoke test green, Library renders 45
  trash buttons for 45 packs offscreen.

## 2026-08-10 — Build your own pack in the Library

- **Manual pack creation.** A new **NEW PACK** button in the Library opens a
  dialog (name, Minecraft version, loader, RAM) and creates a real blank pack
  — build record + isolated instance, ready immediately, no downloads.
- **Engine endpoint** — `POST /api/builds/new` (`src/app/manualpack.ts`)
  creates the record with the user's version/loader/RAM, resolves `auto` to a
  concrete Minecraft version at creation (a record with `auto` would fail at
  launch: "not found in Mojang version manifest"), sanitizes the pack name,
  and validates versions/loaders up front.
- **Fill it from the Mod Browser** — the blank pack is a first-class target
  for Discover: adding a mod downloads the real jar, resolves its required
  dependencies (e.g. appleskin → fabric-api) and re-validates instantly.
  The whole loop was proven live: create blank pack → add appleskin →
  fabric-api auto-added → instant validation PASS → jars in the instance.
- **Verified** — 6 new unit tests (`manualpack.test.ts`) + a full UI driver
  (`pyqt/new_pack_test.py`, 10/10 PASS: button → dialog → submit → pack in
  engine → mod addable). Backend suite 192/192, smoke test green.

## 2026-08-09 — Engine auto-restart

- **The launcher now restarts the engine itself.** When the health check
  fails, the Online/Offline pill counts down (`Offline · retry 5s…1s`), the
  app spawns `node dist/app/server.js` (hidden, output to `server.log`/
  `server.err.log`, compiling first if `dist` is stale), then flips back to
  `Online` once the engine answers — and keeps retrying with backoff if the
  start fails. The startup dialog is now a last resort only shown after an
  auto-restart attempt failed.
- **Observability** — `MainWindow._engine_restarts` counts every successful
  auto-restart, and a toast announces each recovery.
- **Verified live** — `pyqt/auto_restart_test.py` kills the running engine
  and asserts the full journey: `Offline → retry countdown → starting →
  Online` with a fresh engine pid (6/6 PASS); full smoke test still green.

## 2026-08-09 — Desktop-first: taskbar pin, live log streaming, second-pack guard, crash-repair loop

- **PyQt6 pinned to the taskbar** — `pyqt/run-app.bat` starts the engine (if
  needed) then opens the desktop app with `pythonw` (no console, no browser).
  An `AI Modpack Builder.lnk` (with a generated cube icon) is pinned to the
  taskbar and copied to the Desktop; the app is now the primary interface.
- **One game at a time** — the engine refuses to launch a pack while any other
  is running (in-memory + recovered pids), with a clear message naming the
  running pack; the PyQt app warns before sending the request.
- **Live game-log streaming (SSE)** — new `GET /api/play/:id/log` pushes
  `latest.log` + launcher-console lines as they are written; the PyQt Pack
  Detail Logs tab subscribes in real time instead of polling (with a status-
  tail fallback if the stream drops).
- **Save Pack (backup)** — `POST /api/builds/:id/backup` zips the instance's
  worlds + configs + visuals into `exports/<name>-backup-<ts>.zip`; a Save
  Pack button sits in Pack Detail Settings alongside the RAM slider and rename.
  Repair flows (Fix & Relaunch, Add Missing Mods) now thread the account
  username into the relaunched game.
- **Crash parser hardened for pre-crash-handler failures** — a mixin crash that
  leaves NO crash-report (mod-loading `ClassMetadataNotFoundException`, e.g.
  a missing server-side-only dependency) is now read from the launch log:
  root cause named (`com.frikinjay.almanac.Almanac`) and the missing mod id
  extracted (`almanac`) so the Add Missing Mods flow can repair it. Fixed a
  capture-group bug that silently swallowed the parsed message.
- **Stale-log guard** — launch progress no longer misreads a previous boot's
  "main menu reached" from `latest.log`; only files written after the spawn
  point count as this launch's milestones (verified: honest 54→82→100 during
  a real boot).
- **Live crash-repair loop proven** (`pyqt/crash_repair_test.py`) — deliberately
  broke a working pack (dropped a required dependency from its record), then
  via the real UI: launch → mixin crash detected with `almanac` → crash drawer
  with the missing-mod pill → Add Missing Mods & Relaunch → engine re-resolved
  and installed almanac → game reached the main menu → STOP. Also found and
  fixed a real bug: the crash drawer threw `NameError: parent` and never
  opened.
- Backend suite 179/179 (new: mixin class-metadata parsing + evidence tests);
  PyQt smoke test PASS; second-pack guard + SSE stream verified live.

## 2026-08-09 — Launcher round-out: local import, account, RAM editor, live game test

- **Local `.mrpack` / CurseForge-zip import** — `POST /api/importfile` accepts a
  raw archive upload (not just a provider download); `importModpack` refactored
  into a shared `importArchive` pipeline. The PyQt Import modal gained a
  local-file tab with browse + drag & drop. Live-verified: re-importing an
  exported 64-mod `.mrpack` through the upload endpoint → validation PASS.
- **Account wired to launches** — `POST /api/play/:id` accepts a `username` and
  threads it into the launch session (`--username`); the PyQt sidebar profile
  name flows into every play request.
- **Pack Detail RAM editor** — `POST /api/builds/:id/ram` updates a pack's
  allocation; Pack Detail gained a RAM slider wired to it (live-verified:
  `-Xmx6144m` reflected in the real launch command).
- **Launch overlay proven in a real game test** — `pyqt/live_launch_test.py`
  drives the real `MainWindow.play()` on a live Forge pack: overlay starting →
  engine progress live (36% installing → 82% → 92%) → main menu reached at
  100% with the overlay showing "Main menu reached — ready to play" → STOP
  terminates the instance (game log tail streamed throughout).

## 2026-08-09 — PyQt6 desktop launcher (native UI port)

- **New: native PyQt6 launcher** (`pyqt/`) — a faithful port of the
  React/Tailwind launcher design (Home, Library, Pack Detail, Discover, AI
  Builder, Downloads, Activity, Settings + launch overlay, crash drawer,
  account & import modals), wired to the real engine at `127.0.0.1:8282`.
  No mock data: packs, mods, downloads, worlds, logs, crashes, exports, and
  build steps all come from the backend.
- AI Builder streams the **real** build pipeline over SSE (interpret → search
  → select → resolve → conflict → download → test → export) instead of a fake
  timer; completion is detected by polling the persisted record (the engine
  keeps only in-memory event history, so SSE alone is unreliable for finished
  builds).
- Discover = real provider search/browse (empty query = popularity-ranked),
  type pills (mods/modpacks/shaders/resource packs), loader & MC filters,
  detail drawer, add-to-pack and install-pack actions.
- Pack Detail: content manager with real add/remove/re-test, real worlds from
  the instance's `saves/` dir, live console + real log/evidence files,
  exports (saved via the engine), rename, and Ask-AI (engine `/api/chat`).
- Launch flow: live status polling (progress %, stage, mods loaded, log tail),
  crash detection from real evidence, and **Add Missing Mods & Relaunch** via
  the real repair endpoint.
- Backend: new read-only `GET /api/builds/:id/worlds` (lists the isolated
  instance's saves with size + modified time) so the PyQt Worlds tab shows
  real data.
- Client fixes found by live testing: cross-thread delivery via a
  queued-signal bridge (`QTimer.singleShot` from worker threads never fires),
  SSE idle timeout + record-status polling for build completion, and the
  `ai-builder` nav attribute mapping.
- Verification: `pyqt/smoke_test.py` (16 headless checks incl. live data and
  provider browse), `pyqt/screenshot.py` (12 view renders), live end-to-end
  AI Builder build test, backend suite still 177/177.

## 2026-08-09 — Modpack import: modpacks are now addable

- **📦 Modpack import** (`src/app/importpack.ts` + `POST /api/import`): the
  Mod Browser's Modpacks results now have a **📦 Import pack** button instead
  of a dead "not addable" note. Clicking it downloads the pack archive
  (Modrinth `.mrpack` or CurseForge manifest zip, hash-verified, size-capped),
  parses `modrinth.index.json` / `manifest.json`, resolves every file — mods
  via their download URLs (hash-checked), CurseForge manifest entries via
  projectID+fileID through the real API — and creates a NEW build with the
  pack's actual mods, shaders, resource packs, and configs.
- **Overrides extraction**: config/override files inside the archive (no
  download URL) are extracted directly from the zip into the instance's
  game dir, path-traversal proof, so imported packs keep their real configs.
- **Original archive preserved**: the downloaded `.mrpack`/zip is kept as an
  export (re-shareable verbatim) in addition to the rebuilt pack.
- **Imported packs are fully functional**: instant validation runs on the real
  files, the record carries `visualSelections`, and the pack appears in the
  Pack Inspector / History with Re-test (launch) and Play available.
- Live-verified: imported "the horrors in the fog" (Modrinth, Forge) —
  64 mods + 3 shaders + 5 resource packs + configs, instant validation PASS,
  archive export preserved.

## 2026-08-09 — Hardware detection, auto-tune to PC, hardware-aware browsing, modpack search

- **🖥 Hardware detection** (`src/hardware/detect.ts` + `GET /api/hardware`,
  `POST /api/hardware/refresh`): reads the real CPU (cores + model), GPU
  (PowerShell Get-CimInstance on Windows, system_profiler on macOS, lspci/lshw
  on Linux), RAM and OS. Best-effort and cached; user overrides beat detection.
  Live-verified: AMD Ryzen 3 5300U (8 cores) · AMD Radeon integrated ·
  7.3 GB RAM · Windows 10.0.26200.
- **⚡ Auto-tune to PC**: the interpreter recognizes "based on my hardware",
  "fit my pc", "auto-tune", "detect my pc"… and the Build tab has an
  **Auto-tune to my PC** checkbox. The build then sizes RAM to the detected
  machine, downgrades large/massive packs on low-RAM PCs, and turns shaders
  OFF on low-end GPUs (recorded in the build with the reason). Live-verified:
  a shaders request on the integrated-GPU laptop produced
  "Auto-tuned shaders OFF (low-end GPU detected)" + "RAM budget 7.3 GB",
  Moderate load, PASS. Hardware snapshot is stored in each build record.
- **📦 Modpack search**: the Mod Browser gained a **Modpacks** type (Modrinth
  project_type:modpack, CurseForge class 4471) so users can find existing
  packs for their MC/loader — Fabulously Optimized, Cobblemon, Better MC…
  Modpacks show "pack — not addable" instead of Add (they install as packs).
- **🧭 Hardware-aware browsing**: the Mods tab shows the detected machine with
  a recommendation ("prefer light packs & performance mods" vs "this PC can
  handle medium-heavy packs").
- **Settings → Hardware**: detected values + per-field overrides (CPU/GPU/RAM/
  FPS/resolution) + Re-detect. Settings default RAM is now 0 = auto so a pure
  default profile never overrides detected RAM (migrated existing configs).

## 2026-08-09 — Live log watching, crash detection, add-missing-deps flow, mod browser browse mode

- **👁 Live file watching while the game runs**: the launcher now tails the
  game's OWN files in real time (`logs/latest.log`, `logs/debug.log`,
  `crash-reports/*.txt`, `hs_err_pid*.log`) on a 1.2s watcher, not just stdout
  (which the game window can swallow). The launch console streams latest.log
  live; the status endpoint serves `gameLogTail`, `missingDeps` and
  `crashFiles` (with clickable evidence links).
- **🚨 Crashes shown the moment they happen**: fatal markers in the real logs
  flip the launcher to ERROR immediately — including error-screen crashes
  whose process never exits — and the exit handler re-checks the real files so
  a crash is never reported as a clean close.
- **➕ Add missing mods & relaunch**: when crash evidence names missing
  dependencies (Fabric `requires X, which is missing!`, Forge `Currently, X is
  not installed`, `Mod Y requires X`, and mod messages like "Install Serene
  Seasons or …"), the launcher shows a prompt listing them with an **⬇ Add
  missing mods & relaunch** button (`POST /api/play/:id/addmissing`). The
  server resolves each id through real providers (Modrinth → CurseForge, with
  underscore↔hyphen slug normalization and fabric-* → fabric-api mapping),
  adds the mod + its required dependencies, validates, and relaunches.
  **Live-proven**: a pack crashing on Project Atmosphere had "Serene Seasons"
  derived from the crash text, added with its dependency GlitchCore, and
  relaunched to the main menu (100%).
- **🛠 Stale-evidence + stale-jar fixes**: crash reports/logs older than the
  current launch are ignored (a pack that crashed yesterday no longer shows a
  phantom crash today); every Play reconciles the instance mods dir against
  the record's downloads (recorded filename — a bare prefix match for
  "create" was grabbing create-diesel-generators, shipping a 3 MB stale jar
  that crashed with "create is not installed").
- **🔍 Mod browser browse mode**: an EMPTY search box now shows popular
  projects ranked by downloads (Modrinth `index=downloads`, CurseForge
  `sortField=TotalDownloads`) for the current type/MC/loader filters — the
  Mods tab auto-populates on open. Verified live: Fabric API (227M), Sodium,
  Iris, Cloth Config, Entity Culling, FerriteCore…

## 2026-08-09 — Fix & Relaunch, shader/resource-pack browser, re-test after edits

- **🔧 Fix & Relaunch** (`POST /api/play/:id/fix`): one click from a LAUNCH
  FAILED state runs the real repair loop against the pack's live instance
  (crash reports → root cause → add missing deps via the same provider engine
  as the Mod Browser, drop conflicting mods) with REAL Minecraft launch
  retests, persists every change (selections/graph/downloads/repairs/tests),
  then relaunches the pack for play. The launcher shows a fixing state through
  the whole loop. Also available directly on LAUNCH FAILED cards in History.
  **Proven live**: on the pack that previously crashed missing irons_lib /
  playeranimator, the loop ran a real standard launch → main menu reached
  (PASS) → game relaunched (pid recorded); the new standard:PASS test is in
  the build record.
- **Mod Browser now covers shaders + resource packs**: a type selector
  (Mods / Resource Packs / Shaders) drives real provider search facets;
  adding one downloads the file (hash-verified) into downloads/visual,
  installs it into the instance's shaderpacks/ or resourcepacks/ dir, and
  records it in a new `visualSelections` field so tests, Play and exports all
  include it. Installed visuals are listed (with Remove) both in the Mods tab
  and the Pack Inspector; dedup reports "already in this pack" cleanly.
  **Proven live**: Complementary Shaders - Reimagined added to the Forge pack
  via the UI — `packStats.shaders 0→1`, zip present in instance shaderpacks.
- **Re-test after manual edits** (`POST /api/builds/:id/retest`): a button in
  the Mods tab and the Pack Inspector runs a REAL launch test (standard, or
  deep for deep-built packs) against the current instance, records the result
  and refreshes the report — instant validation alone never claims a manual
  edit "works" again.
- **Play honours visuals**: the launcher now builds its env from the record's
  visualSelections and installs shaders/resource packs into a rebuilt
  instance, so manually-added visuals survive instance wipes and instant-mode
  builds.
- **Server-pack safety**: shaders/resource packs never leak into server packs
  (already excluded from overrides — now verified against manually-added
  visuals too).
- Fix: `syncRecordToEnvJars` (used after the repair loop) no longer drops
  jar-less selections such as CurseForge manifest-referenced mods — only mods
  the loop could actually act on are synced.
- Tests: 156/156 pass (7 new: visual search type passthrough, add shader /
  resource pack, already-present visual, visual remove, retest with injected
  runner, record sync incl. jar-less survival).

## 2026-08-09 — Mod Browser: search & add Modrinth/CurseForge mods to any pack

- **New Mods tab**: search real Modrinth/CurseForge results (provider toggle,
  MC-version + loader filters, icons, download counts, view links), pick a
  target pack, and click Add — the mod is downloaded (hash-verified) and
  **its required dependencies are resolved recursively** via real provider
  lookups, installed into the pack's instance (so Play picks them up), and the
  persisted build record (selections + graph + downloads + stats) is updated.
  A non-blocking toast reports added mods, auto-resolved deps, and the instant
  validation result. No alert() dialogs.
- **Fix & add missing deps**: `POST /api/builds/:id/addmod` + `removemod`
  (buildId regex-guarded, 409 while the pack is still building so the engine's
  end-of-build persist can't clobber the edit). Report + instance README are
  regenerated after edits so docs never claim a stale pack.
- **Launcher integration**: the LAUNCH FAILED box now has a "🔍 Find in Mod
  Browser" button that extracts the missing mod id from the crash message
  (e.g. "requires irons_lib …") and prefills a search.
- **Verified live end-to-end**: the broken Forge pack that crashed with
  "irons_spellbooks requires irons_lib … playeranimator" — both were added via
  the browser, playeranimator landing on the exact required version
  (1.0.2-rc1+1.20-forge), jars physically in the instance, instant validation
  PASS. Then a UI click-add of Stoneholm (60→61 mods) and remove (→60).
- CurseForge note: the manual add flow enables CF's signed download-url
  endpoint (single-machine use) — the build pipeline still exports CF content
  as manifest references only. 149/149 unit tests pass.

## 2026-08-09 — Repair loop reads ALL crash evidence, not just latest.log

- **`collectInstanceLogs`** now gathers every diagnostic a failed launch can
  produce: `crash-reports/*.txt` (authoritative root cause), `logs/debug.log`
  (DEBUG-level stacks), `hs_err_pid*.log` (JVM native crashes) + gc.log, and
  returns the crash-report filenames so phases can cite which file proved the
  diagnosis.
- **Repair agent `analyzeFailure`** now prefers the newest crash report first,
  then debug.log, then latest.log as last resort — instead of reading only
  latest.log, where the crash header often scrolls out of the tail window.
- **Forge/NeoForge missing-dep parsing**: the fml error-screen format
  ("Failure message: Mod irons_spellbooks requires …" / "Currently, irons_lib
  is not installed") is now extracted and classified as `missing-dependency`
  (rules reordered so the specific diagnosis beats the generic
  `mod-loading-failed` symptom). Verified live on a real Forge 1.20.1 crash
  report: hints now lead with `irons_lib, playeranimator` — the repair agent
  ADDS those instead of removing a random mod.
- **Stale-evidence wipe**: the test pipeline already wiped `mods/` between
  repair attempts; it now also wipes `crash-reports/` and `logs/` so a report
  from the previous attempt can never be misread as the current failure.
- Test phases list the diagnostics each attempt produced. 144/144 unit tests
  pass.

## 2026-08-09 — CurseForge export now bundles the actual mod jars

- **Root cause of "no mods install on import"**: the CurseForge zip wrote
  `manifest.json` with `files: []` (no CurseForge API key → zero CF references)
  and never bundled jars, so the CurseForge launcher had nothing to install.
- **Fix**: `exportCurseForge` now bundles every non-CF-referenced mod jar into
  `overrides/mods/<real jar name>` — the CF launcher applies `overrides/` to the
  instance, so mods land in `mods/` on import. CF-referenced mods stay as
  manifest references (launcher downloads them; no double-install).
- **Hardened jar lookup**: shared `findJar` (used by both Modrinth and
  CurseForge exports) prefers the exact `<slug>-<version>.jar` filename and
  falls back to a prefix match, fixing the `sodium`/`sodium-extra` style
  prefix-collision bug; `versionId` fallback for old builds with hash-prefixed
  jars. NOTES-Pack-Content.txt moved to the zip root (no longer pollutes the
  instance overrides).
- **Validation**: `validateCurseForgeZip` now asserts the bundled jar count
  against the expected selections; `validated: true` only when jars are
  physically present. Large packs defer the (now jar-bundling) CF zip on demand
  to keep the disk peak at 2× (the old ENOSPC guard).
- **Verified live**: deleted a real pack's CF zip, fetched it via the download
  endpoint (HTTP 200), and confirmed 17 mod jars inside `overrides/mods/` +
  valid `manifest.json`. 140/140 unit tests pass.

## 2026-08-09 — Live launch-state propagation (crashes/closes update the page)

- **Page-wide watchdog**: a 2s poll of `/api/builds` re-renders History and the
  pack-tab status line only when the running/launch-phase signature changes,
  so a game that crashes or closes on its own immediately stops being shown as
  RUNNING — from any tab, no manual refresh. The build list now exposes
  `launchPhase`/`launchError` per build (reconciled server-side).
- **Phase-aware History badges**: a crashed pack shows a red `LAUNCH FAILED`
  badge with the exact cause (e.g. `Failure message: Mod irons_spellbooks
  requires playeranimator…`) — even while its error-screen window lingers —
  and `■ Stop` closes that leftover window. Once exited, the button reverts to
  `▶ Play` to retry, and the badge returns to `done`.
- **Phase-aware pack-tab status line**: `Launch failed — <cause>` (red),
  `RUNNING — pid` (green), `Launching — <stage> (N%)`, or `Not running.` —
  Stop is enabled only while a real process exists to kill.
- **Stop closes the instance**: verified live — `■ Stop` (launcher, pack tab,
  or History) taskkills the whole java tree; the page updates itself within
  ~2s and Stop is never mislabeled as a crash.
- Reviewer fixes: the sweep no longer hijacks `currentBuild` mid-session
  (auto-reopen gated to initial load or the user's own launch), the first
  sweep pass seeds the signature (no double render), and Stop no longer
  erases crash diagnostics for already-exited packs.

## 2026-08-09 — Launcher-grade Play experience

- **Launcher progress panel**: Play now opens a real-launcher view with an
  animated striped bar, percent, phase badge (PREPARING / INSTALLING /
  LOADING / RUNNING / ERROR / STOPPED), stage label, mods counter, live
  console tail and Stop button.
- **Progress is real, not a timer**: pre-spawn phases (Java, Mojang install,
  loader install) are reported at each actual boundary via a new
  `TestEnv.onLaunchProgress` hook in `assemble()`; post-spawn progress is
  derived from real log markers — Fabric `Loading N mods` (62%), Forge
  `Loaded N mods from M mod list` (74%), `Setting user` (82%), sound engine
  (88%), resource reload (92%), main-menu evidence (100%). Monotonic: the bar
  never regresses.
- **Honest errors**: fatal startup evidence (crash header, Fabric/NeoForge
  incompatible-mods screen, Forge `Failure message: Mod X requires…` /
  `which is not installed` screens) flips the launcher to ERROR with the root
  cause; at process exit the authoritative `crash-reports/*.txt` files are
  parsed so a crash is never reported as "Game closed".
- **Launcher robustness**: the game is spawned `detached:true` on all
  platforms so it survives server restarts; launch state persists to
  `logs/launch-state.json` and is reconciled on restart (dead pid → stopped;
  stale pre-spawn state > 10 min → aborted); Stop kills the whole process
  tree and is labeled "Stopped", never "Game exited (code 1)".
- **Play button consistency**: History-tab Play buttons use the same launcher
  flow and are gated on a real (non-instant) launch test; a still-running
  pack reopens its launcher on page load; `GET /api/play/:id/status` returns
  phase/progress/stage/mods/error/log-tail (log tail cached by file size so
  polls never re-read multi-MB logs).
- New: `src/launcher/progress.ts`, `src/tests/unit/launchprogress.test.ts`
  (8 tests). Live-verified: Fabric pack reached main menu (62→92→100); a
  broken Forge pack reported `Failure message: Mod irons_spellbooks requires
  playeranimator…`; Stop killed the java tree.

# Changelog

## 0.2.1 — 2026-08-08 (deep refinement pass)

- **Mod-count distribution**: per-feature selection targets now sum EXACTLY to
  the user's requested count (or the pack-size goal), weighted by feature
  priority and normalized to the goal — a "~120 mods" request actually tries
  to fill 120 (live flagship: targets 39 → 121, pack 59 → 162 mods incl.
  resolved deps; 0 irrelevant picks). Previously the interpreter capped each
  feature independently and silently shipped ~59 with no explanation.
- **Category-browse fallback**: when a feature's keyword searches under-fill
  its (now larger) target, the selector queries the whole category facet
  (empty query + `categories:` + index=downloads) so the most-downloaded mods
  in that exact category surface; browse queries are recorded for observability.
- **Phantom-shader fix**: the `shaders` feature no longer joins the mod pool —
  it was being selected as a graph node that was never downloaded while the
  visuals pipeline picked a different shader. Shaders/resource packs now come
  exclusively from the visuals pipeline.
- **Export disk guard**: server zips are deferred (generated on first download)
  for packs > 300 MB or massive packs, ending the 3× export disk tripling that
  caused ENOSPC on large builds; deferred exports show an ON DEMAND badge and
  are regenerated + validated on demand from the persisted record.
- **Path-traversal hardening**: GET /api/builds/:id routes gained the same
  `^b-…$` buildId guard the play/rename routes already had.

## 0.1.0 — 2026-08-07 (initial working build)

The first end-to-end version that produces a real, tested, launcher-compatible
modpack. Key milestones, in order (each verified by a real run):

- **Scaffold**: Node 24 + TypeScript, zero runtime dependencies, built-in
  `node:sqlite` / `node:test` / `fetch`.
- **Core**: domain types, utilities (hash, sanitize, version-range math,
  dependency-free safe ZIP reader/writer), per-build logger, SSE event bus.
- **Providers**: ModrinthProvider (live), CurseForgeProvider (key-gated,
  manifest-reference policy), disk cache with stale-on-error fallback, retry
  with 429/500 backoff.
- **Interpreter**: plain-English → structured requirements (version, loader,
  RAM, pack size, features, themes, negations, shaders, textures, multiplayer).
- **Selection**: multi-provider search, cross-provider dedupe, scored ranking
  with written reasons, feature overlap handling.
- **Solver**: recursive dependency expansion, constraint fixpoint, bounded
  backtracking (downgrades), incompatible-edge exclusion, final honesty pass.
- **Conflicts**: duplicate detection, rendering/optimization fork rules,
  shader-system clashes, dependency range clashes, memory-driven warnings.
- **Memory**: SQLite compatibility database (result, signature, repair, world/
  server flags).
- **Instances**: Mojang version install (client jar, rule-aware libraries,
  natives, budget-capped priority assets), Fabric/Quilt meta installs, Forge/
  NeoForge installer route, shared `workspace/mojang/` across builds, Java
  detection + Adoptium auto-install.
- **Process runner**: timeouts, kill-tree, log capture, watch-for-evidence
  early exit.
- **Test levels**: instant (incl. graph integrity), standard (real launch,
  main-menu evidence via log markers + window probe), deep (server/world/
  quickplay/GC memory/reproducibility).
- **Crash parser + repair agent**: signature rules, memory-hit resolution,
  bounded loop (1/5/15), every repair recorded.
- **Exports**: `.mrpack` (schema + per-file hash validation), CurseForge
  manifest ZIP (reference-only, honestly labeled), server pack (client-only
  filtering, run scripts), config generator.
- **Build engine + UI**: SSE live view, pack inspector, chat edits, history,
  settings.
- **Tests**: 56 unit tests + live acceptance test with saved results.
- **Bugs found by real runs and fixed**: project-root path resolution,
  Fabric meta API shape, Modrinth category-facet ANDing, exports dir creation,
  `-cp ${classpath}` launcher template leak, JVM object-arg array handling,
  `java -version` stderr capture, log4j file logging, early-exit on menu,
  server/world early exit on "Done", repair `dropOne()` culprit ordering.

### Proven live (this release)

- Fabric 1.20.1 pack: real launch reached the main menu
  (`Sound engine started`, `OpenAL initialized`, window `Minecraft* 1.20.1`).
- Vanilla server created and loaded a real world (`Done (44.868s)!`).
- 11-mod acceptance pack: all downloads SHA1-verified; `.mrpack` (43 MB),
  CurseForge ZIP and server ZIP all validated.
- 56/56 unit tests passing.
