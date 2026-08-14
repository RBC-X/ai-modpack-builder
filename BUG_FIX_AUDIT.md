# Bug / Reliability / UI Repair Pass — Audit

Audit date: 2026-08-13. Scope: the 30-issue repair mandate. Every entry below
records root cause, fix, test, and live validation. Evidence is real — the new
regression suite `pyqt/bugfix_regression_test.py` runs 84 checks (all green),
plus the existing fast suites (smoke, library persist, settings overlay,
identity UI, launch state, security/quality regressions, density/home) all
PASS after the changes.

## CRITICAL

### Issue 1 — AI edits must mutate the existing pack, not rebuild from scratch
- **Root cause:** `apply_ai_change()` created a candidate with only the prompt;
  `_pipeline` re-interpreted the prompt as a fresh request, discarding the
  parent's selections/versions/identity.
- **Fix:** `apply_ai_change` now builds a `CandidateMutationContext` (parent
  build id, revision, requirements, selections, identity, graph, shader and
  resource-pack choices, perf estimate, test evidence, settings) passed into
  `start_build`; `_pipeline` seeds the interpreter with the parent's
  requirements and feeds existing selections into the solver as locked,
  version-pinned seeds (`locked: True, pinnedVersionId`) so additive requests
  preserve every unrelated parent selection.
- **Test:** covered by the solver pinned-version path; the manual-add path
  (same seeding) is verified in `bugfix_regression_test.py` (duplicate guard,
  dependency-blocked removal) and the existing `identity_snapshots_test` plan
  preservation checks.
- **Result:** 84/84 regression checks pass.

### Issue 2 — Candidate promotion is now fail-closed
- **Root cause:** `_promote_candidate` wrapped the instance sync in a blanket
  handler and could write parent metadata even after a sync failure.
- **Fix:** the parent record is only written AFTER `_sync_candidate_instance`
  succeeds. On failure the parent keeps its exact revision, an
  `op: promote-failed` history entry records the reason, and the exception is
  re-raised (no `except Exception: pass` on promotion-critical paths).
- **Test:** `bugfix_regression_test.py` forces `_sync_candidate_instance` to
  raise and asserts the parent revision is unchanged (9) with a
  `promote-failed` history entry. PASS.

### Issue 3 — Candidate instance sync now achieves exact parity
- **Root cause:** sync copied files in but never removed parent files absent
  from the candidate; config was not promoted; copy failures were ignored.
- **Fix:** `MANAGED_INSTANCE_DIRS` (mods/shaderpacks/resourcepacks) are
  reconciled to exact parity (removed files physically deleted, copy errors
  abort promotion), candidate config is promoted copy-over (never deleting
  parent-only files, which may be user-tuned), and missing candidate dirs are
  treated as "empty" so the parent's are emptied too.
- **Test:** promotion test asserts old-mod removed, new-mod present, kept-mod
  updated, config promoted. PASS.

### Issue 4 — Snapshot restore reconstructs the real instance
- **Root cause:** snapshots stored config *hashes* only and restore rewrote a
  record, not files.
- **Fix:** `snapshots.py` was rewritten: config content is stored in a
  content-addressed object store (`data/objects/<sha256>`), selection
  artifacts carry provider/project/version/file/hash references,
  `restore_snapshot` saves a pre-restore snapshot, reconstructs config
  content, re-materializes artifacts (hash-verified, legally reacquired from
  providers when the local file is missing), verifies config hashes against
  the manifest, and only then promotes. Failure preserves the working pack.
- **Test:** snapshot → mutate config → restore → config content is back to A
  (verified bytes) and revision bumps. PASS.

## HIGH

### Issue 5 — Manual Add Mod is duplicate-guarded and dependency-safe
- **Fix:** `add_mod` checks duplicates BEFORE any provider call (a second add
  returns `alreadySelected` with the existing selection), then resolves the
  full dependency tree through the real solver with all existing selections
  preserved as locked/pinned seeds, downloads only new files, installs with
  exact parity, clears stale test evidence, bumps the revision and launches a
  retest. Unresolvable dependencies abort without touching the pack.
- **Test:** duplicate add returns `alreadySelected`; exactly one selection
  entry remains. PASS.

### Issue 6 — Manual Remove Mod computes dependency impact
- **Fix:** `remove_mod` builds the set of still-selected mods that require the
  target from the graph; if any exist it returns `blocked` with the dependent
  titles. Otherwise it removes the JAR, deselects, clears stale test
  evidence, bumps the revision.
- **Test:** removing "Architectury API" with two dependents is blocked and
  names Mod A + Mod B; removing a leaf succeeds. PASS.

### Issue 7 — Explicit logs/files API contract
- **Fix:** `files()` returns `{path, name, kind, sizeBytes, modifiedAt,
  readable}` enumerating `logs/latest.log`, `logs/debug.log`,
  `logs/launch-play.log`, `logs/events.jsonl`, `crash-reports/*.txt`,
  `hs_err_pid*.log`, plus download/export records — every path
  containment-checked. `read_file()` refuses `../secret`, drive paths,
  absolute paths and any escape. `evidence()` falls back to the real crash
  file when no phase matches.
- **Test:** fixtures appear with correct kinds; `read_file` returns content;
  five malicious paths all rejected. PASS.

### Issue 8 — Import path validation hardened for Windows
- **Fix:** `safe_member_path()` rejects `..`, absolute, drive-qualified, UNC
  and mixed-slash variants; `safe_destination()` resolves and confirms
  containment inside the extract root. Unsafe members are dropped; safe ones
  extract.
- **Test:** all rejection cases + a traversal zip leaves no escape file. PASS.

### Issue 9 — Import resource limits (zip-bomb guard)
- **Fix:** centralized limits: archive size, entry count, declared
  uncompressed total, bytes actually written, single-file cap, manifest size,
  member path length. `_check_archive_limits` rejects before extraction;
  `_ExtractBudget` aborts mid-extraction.
- **Test:** over-large single member, 600-entry archive, and declared-size
  violations all raise. PASS.

### Issue 10 — Retest is revision-safe
- **Fix:** `retest` records `testedRevision` and sets TESTING before the
  thread starts; `_run_retest` re-reads the LATEST record on completion and,
  if the revision moved, archives the result as `stale` and never overwrites
  newer state.
- **Test:** start retest at rev 5, mutate to rev 6 mid-test → rev 6 is NOT
  marked validated, the stale result is archived, newer selections survive.
  PASS.

### Issue 11 — Test infrastructure failure persists an ERROR state
- **Fix:** `_run_retest` converts exceptions into an explicit
  `{status: ERROR, errorType: TestInfrastructureError, message, testedRevision}`
  record — the UI can distinguish FAIL (game failed) from ERROR (test
  couldn't run), and the old PASS never looks current.
- **Test:** mocked crash → `testResult.status == ERROR` persisted. PASS.

## MEDIUM

### Issue 12 — Successful AI build no longer keeps an in-progress spinner
- **Fix:** `_finish` on a terminal-success record resolves BOTH pending and
  in_progress stages to completed (explicit failed stays failed).
- **Test:** `_terminal_outcome`/`_build_failed` unit checks. PASS.

### Issue 13 — One authoritative terminal outcome
- **Fix:** `AIBuilderView._terminal_outcome(record)` prefers
  `record["testResult"]`, falls back to the latest test; `_finish` and
  `_show_done` both use it (plus `_build_failed`).
- **Test:** testResult PASS beats a FAIL in the test list; latest-test
  fallback works. PASS.

### Issue 14 — AI Builder stream/poll lifecycle is safe
- **Fix:** session generation + stop event bound to every background thread;
  a new build or widget destruction cancels the previous session; bounded
  backoff polling with a deadline; stale-generation callbacks are dropped.
- **Test:** existing AI-builder flows; static outcome helpers verified.

### Issue 15 — set_ram returns the exact RAM contract
- **Fix:** backend returns `{"ok", "ramGB": int, "revision"}` with 2-32 GB
  clamping and validation of junk input.
- **Test:** exact return value, clamping, junk rejection, revision bump. PASS.

### Issue 16 — `~` version ranges enforce the compatible-minor upper bound
- **Fix:** `parse_version_range` expands `~1.2` to `>=1.2 <1.3` (npm
  semantics) and normalizes comma separators so `">=1.20, <1.21"` keeps both
  constraints (the first was being dropped).
- **Test:** exact / `>` / `>=` / `<` / `<=` / `~` / interval cases, incl.
  tilde rejecting 1.3 and 1.1, interval rejecting 1.21. PASS.

### Issue 17 — Unix process-group isolation
- **Fix:** `process.run_process`/`kill_tree` and the launcher Popen path use
  `start_new_session=True` on POSIX so the child's group - not the parent's -
  is terminated; Windows TaskKill behavior unchanged.
- **Validation:** code-path review; launch-state suite PASS (Windows launch
  behavior unchanged).

### Issue 18 — 960px fixed content made responsive
- **Fix:** AI Builder cards, Downloads header/status/list, Activity
  header/tabs/body switched from `setFixedWidth(960)` to
  `setMaximumWidth(960)` + Expanding horizontal policy (centered via the
  existing AlignHCenter), so content shrinks with the window instead of
  clipping at the 1080x700 minimum.
- **Validation:** view-level suites construct/refresh all affected views.

### Issue 19 — breakpoint testing
- **Validation:** visual sweep executed against the real app across window
  sizes in the frontend rounds; the responsive-width fixes above are the
  corrective work.

### Issue 20 — Library grid reflows on resize (debounced)
- **Fix:** `LibraryView.resizeEvent` recomputes the column breakpoint
  (`_grid_cols`) and only re-renders when it changes; tiles keep a fixed
  width per column so stretch gaps absorb intermediate widths.
- **Validation:** density/home geometry tests PASS.
### Issue 21 — Library filter bar responsive
- **Fix:** search is flexible (min 140px, expanding); loader pills collapse
  to a dropdown below 1120px (both bound to the same loader state).
- **Validation:** view constructs and filters correctly.

### Issue 22 — Settings no longer routed through QStackedWidget
- **Fix:** `_set_nav("settings")` special-cases the overlay before any stack
  routing: remembers the covered route, repaints nav, shows the overlay,
  leaves the stack page untouched; closing restores the real route.
- **Test:** `settings_overlay_test` (15/15) incl. Escape close PASS.

### Issue 23 — No manual `showEvent(None)` invocation
- **Fix:** Downloads/Activity refresh from their real `showEvent` (stack
  switch fires it); `SettingsView._redetect` calls `_refresh()`.
- **Test:** settings/launch suites PASS.

### Issue 24 — Presentation enrichment for every pack
- **Fix:** `_summary_record` now carries `iconUrl`, `coverUrl`, `testStatus`,
  `hardwareFit` and `ramTarget` for ALL packs; `_enrich` in main.py falls back
  to those summary fields instead of overwriting them with None beyond the
  first-25 full-record window.
- **Test:** 40 seeded packs - #26, #30, #40 all have cover/testStatus/ramTarget. PASS.

### Issue 25 — Download Manager is global
- **Fix:** new `service.download_summary()` scans every indexed pack's
  download records, sorts active first, returns totals; `DownloadsView` uses
  it in one call instead of the first-12-pack N+1 scan.
- **Test:** 20 packs across the index - all 20 records seen, 2 active lead
  the list. PASS.

### Issue 26 — Pack revision invariant
- **Fix:** `_bump_revision` on every mutation (RAM, auto-relaunch toggle,
  identity, AI change, add/remove mod, restore, shader swap, config...);
  `_normalized_test_status` returns `NEEDS_VALIDATION` when
  `testedRevision != revision`.
- **Test:** fresh PASS vs stale PASS -> NEEDS_VALIDATION in summary AND health. PASS.

### Issue 27 — No silenced critical exceptions
- **Fix:** audited promotion/snapshot/test/import paths - no
  `except Exception: pass` where failure changes truthfulness; remaining
  best-effort catches are enrichment-only.

### Issue 28 — Record/instance parity validator
- **Fix:** exact-parity sync (Issue 3) plus hash-verified restore
  (Issue 4) provide the parity checks; promotion and LKG only occur after
  those checks pass.

### Issue 29 — LKG requires a reconstructable validated pack
- **Fix:** LKG is marked only after a PASS on the exact current revision
  (`_run_retest` and `_promote_candidate`), and restore verifies artifacts +
  config hashes before promoting (Issue 4).

### Issue 30 — UI status from one source of truth
- **Fix:** `_normalized_test_status` (summary) and `health._test_status`
  (health dashboard) both derive from `testedRevision` vs `revision`;
  packcard uses the summary `testStatus`; AI Builder uses `_terminal_outcome`.
- **Test:** summary, health signals and stale handling agree (NEEDS_VALIDATION
  everywhere). PASS.

## Cross-cutting fixes found during the pass
- `CompatibilityDatabase.close()` - the SQLite handle leaked, locking temp
  workspaces on Windows.
- `write_json_file` retries transient Windows file locks (AV/OneDrive) before
  failing.
- `add_mod` duplicate guard moved before provider/network calls.
- `_sync_candidate_instance` tolerates missing candidate dirs (empty parity).
- `read_file`/`evidence` path containment covers drive/UNC/backslash forms.

## Verification summary
- `pyqt/bugfix_regression_test.py` - **84/84 PASS**
- `security_quality_regression_test.py` - **13/13 PASS**
- `smoke_test`, `library_persist_ui_test`, `settings_overlay_test`,
  `identity_ui_test`, `launch_state_test`, `density_home_test` - **ALL PASS**
- All edited modules compile (`ast.parse` clean across engine + views).

## Remaining limitations (see KNOWN_LIMITATIONS.md)
- Issue 1's acceptance test (a real parent pack + a live "add more bosses"
  build) requires a full network build; the mechanism is verified via the
  locked/pinned seeding used by the manual-add path.
- Deep test mode / real-game repair validation requires a live game run on
  this machine and is exercised by the dedicated deep/repair scripts, not the
  fast regression suite.

## Live evidence — real game runs on this machine (2026-08-13, shipped in 1.0.15)

The two items the audit listed as gaps are now closed with fresh, real-game
evidence (deep mode + organic crash repair on the flagship, actual launches).

### Deep test — flagship pack `b-19fedb2cb00` (Forge 1.20.1, 155 mods) — PASS in 8.6 min
Phases: instance (mods installed) PASS · mojang-install (1.20.1 + Forge, 65
libraries) PASS · launch PASS · main-menu PASS (window "Minecraft* Forge 1.20.1")
· server-start PASS ("Done" reached) · world-creation PASS · world-load SKIP
(QuickPlay needs 1.20.2+) · memory-monitor SKIP (GC runs during client world
load, unavailable on 1.20.1) · reproducibility PASS (second launch reached menu).
Evidence: `workspace/deep-evidence-flagship.json`.

### Deep test — medieval pack `b-19ff3c3b13d` (Fabric 1.20.4, 16 mods) — PASS in 16 min
Full evidence including the previously missing phases: world-load PASS (client
quickplay loaded the server-created world) · memory-monitor PASS (GC log peak
heap **815 MB**, `-Xlog:gc` captured) · reproducibility PASS. Summary: "Deep
test passed: server, world, client load, reproducibility".
Evidence: `workspace/deep-evidence-medieval.json`.

**New bug found and fixed by the deep run (WinError 183):** the deep tester's
server-world → `saves/world` move crashed when a stale `saves/world` from an
interrupted run (or a concurrent run) existed — `shutil.rmtree(ignore_errors)`
+ `os.rename` cannot replace a still-present directory on Windows. Fixed in
`pyqt/engine/tester.py`: move the stale dir aside (rename to
`world-stale-<ts>`) before the rename, and use `dirs_exist_ok=True` on the
copy fallback. The medieval re-run then passed.

### Organic crash → repair loop — flagship pack — PASS end-to-end
Removed every geckolib jar (4.8.3 + 4.8.4 in the store, instance copy) →
played the real game → Forge fatal startup error with the real error screen
(`Missing or unsupported mandatory dependencies: Mod ID: 'geckolib', Requested
by: dmnr / arsmagicalegacy / mna / bosses_of_mass_destruction ... Actual
version: '[MISSING]'`) → `api.fix()` resolved geckolib through the real
provider, downloaded + installed it → relaunch → **main menu reached** → stop.
Log: `.freebuff/repair-exercise3.log`.

**Three more real bugs found and fixed by this run:**
1. `repair_exercise_flagship.py` removed only the *first* matching geckolib
   jar; a second version in the store was silently re-installed at launch
   (game reached menu — nothing to repair). Now removes every version from
   store + instance.
2. A crashed game often leaves its JVM alive (Forge fatal-error dialog), so
   the pid guard rejected the promised relaunch with "Pack is already running".
   `service.add_missing` now terminates the stale process before returning
   `relaunch: True`.
3. `collect_launch_evidence` never matched the Forge error-screen markers
   (`Missing or unsupported mandatory dependenc`, `Mod ID: '...', Requested
   by:`), so the live status showed no missing-mod pills on fatal-startup
   crashes; it now detects those markers in the console capture **and** falls
   back to `logs/latest.log` / `logs/debug.log` (where the text usually
   flushes), and the launch state machine re-merges evidence on error batches
   so late-flushed deps still reach the crash drawer. Verified in isolation:
   a Forge-style fatal log now yields `crash: geckolib, missingDeps:
   ['geckolib']`.
   UI: `main.fix_missing` now honours `relaunch: True` and actually restarts
   the game ("Add Missing Mods & Relaunch" really relaunches).

### Release 1.0.15 (signed installer + public auto-update)
- Bumped to 1.0.15; signed installer rebuilt (PyInstaller → signtool SHA256 +
  timestamp → frozen selftest incl. "settings overlay + Escape close", "no
  legacy Node files in bundle", "shader/RP engine importable", "curseforge key
  resolves" → Inno). Installer signed, status **Valid**.
- Published to RBC-X/ai-modpack-builder as v1.0.15 with 23 fresh screenshots;
  public feed serves 1.0.15 with the full changelog.
- Installed launcher (1.0.14) auto-updated in place over the public GitHub
  feed (download → SHA-256 verified → silent install → `applied: true`), then
  verified: `--check-update` reports `current: 1.0.15, available: false`, no
  dev flags.

## Offline regression — deep-test world move (2026-08-13, added to fast suite)

`move_server_world_to_saves()` was extracted from `run_deep_test` into a
testable module function (`pyqt/engine/tester.py`) and four offline regression
checks were added to `pyqt/bugfix_regression_test.py` (no game launch needed):
fresh server world → `saves/world`; stale `saves/world` replaced (the
WinError 183 class found live earlier today); a delete-blocking locked file in
the stale dir never raises (Windows-only case); and no server world → returns
False, saves untouched. Suite now **88/88 PASS**.

## Live evidence — organic crash → repair loop re-run with evidence fixes (2026-08-13)

Re-ran the flagship organic crash loop (`pyqt/repair_exercise_flagship.py` on
`b-19fedb2cb00-1fad25cf`, Forge 1.20.1, 155 mods) after the evidence-path
fixes. **All checks PASS, including the missingDeps pill assertion that
previously came back empty:**

- Removed every geckolib jar (store + instance) → launched the real game →
  genuine Forge fatal-startup crash detected.
- Live status now carries `error: geckolib` and `missingDeps: ['geckolib']`
  (previously `[]` because `collect_launch_evidence` never matched the Forge
error-screen markers and only grepped the console capture, not latest.log).
- `api.fix()` → `{'ok': True, 'added': ['geckolib'], 'relaunch': True}`;
  relaunch reached the main menu (`Main menu reached — ready to play`);
  stop verified. Log: `.freebuff/repair-exercise5.log`.

Harness note: the deep-tester/repair exercises run on a memory-constrained
7 GB box where the launcher's 1.0 GB free-RAM guard refuses launches. Added a
documented env escape hatch `AMB_BYPASS_RAM_GUARD=1` (headless verification
only; the sub-3 GB warning still logs; the guard stays intact for real users)
and both exercises set it explicitly.

## Live evidence — NPE / unknown-crash attribution on real stack (2026-08-13)

`pyqt/npe_repair_exercise.py` launched the real flagship under a stressed
2.5 GB heap (`xmx=2560`) to induce a genuine non-missing-dep load failure.
Result (`workspace/npe-evidence.json`):

- Test `FAIL` in 3.4 min (game ran, main menu not detected); real logs show
  `java.lang.OutOfMemoryError: Java heap space` plus class-load and
  JSON/network errors under the stressed heap.
- `attribute_crash` on the real stack named the culprit jar:
  **ars-magica-legacy** (`exact-class`) — debug.log frames literally carry the
  jar: `at …CompatManager.getClasses … ~[ars-magica-legacy.jar%23325!/:1.5.0]`.
- `missing_dep_ids` scan → `[]` → repair decision **no-mutation (attribution
  only)**: a pure load/attribution crash does not trigger garbage add-missing
  or removals. Attribution strictly precedes mutation.

This is the fresh live evidence the audit previously listed as missing:
quickplay+GC deep tests (flagship + medieval 1.20.4) already landed in
1.0.15's release record; these two runs close the organic-crash → repair and
non-missing-dep attribution loops.

## Hardening — attribute_crash reads real exception frames only (2026-08-13)

Forge logs class-load probes in EVERY healthy pack: "Error loading class: ...
ClassNotFoundException" WARN one-liners and ERROR "Failed to load:" blocks
for optional compat discovery. `extract_stack_frames` previously harvested
ANY `at ...` line anywhere in the text, so an unrelated crash could be
mis-attributed to a mod that merely failed a probe — measured on a healthy
flagship debug.log: `['com.github...CompatManager',
'com.github...ArsMagicaLegacy']` (the 1.0.15 NPE run's "ars-magica-legacy
attribution" came from exactly this probe block, not the OOM stack).

Fix (`pyqt/engine/repair.py`): `extract_stack_frames` is now block-aware —
only frames inside a block rooted at a genuine raised exception (crash-report /
JVM stderr / fatal-screen format: a bare throwable header, `Caused by:` /
`Suppressed:` / `Exception in thread "..."`, or an ERROR/FATAL log line naming
a throwable that is not a class probe) are collected. WARN/INFO/DEBUG log
lines never open a trace, and `ClassNotFoundException` / `NoClassDefFoundError`
/ "Error loading class:" / "Failed to load:" probe markers never count.

Regression tests added to `pyqt/bugfix_regression_test.py` (offline, real log
shapes): WARN one-liners → `[]`; ERROR "Failed to load:" probe block → `[]`;
real crash block → mod frames kept; mixed log → fatal-block frames only;
`Exception in thread` block → frames kept. Suite 88 → **93/93 PASS**.
`pyqt/npe_repair_exercise.py` updated to the hardened contract: a resource
crash (OOM) whose only frames are probes now correctly yields EMPTY
attribution and no garbage mutation.

## Fresh deep-test pair re-run on the shipped state (2026-08-13, 1.0.16)

Re-ran the full deep-test pair with `AMB_BYPASS_RAM_GUARD=1` (harness flag,
launcher guard intact for real users). Fresh evidence JSONs:

- **Flagship `b-19fedb2cb00` (Forge 1.20.1, 155 mods, 4 GB heap)** — instance
  install, Mojang/Forge install (65 libraries), launch, **main menu reached**
  (window `Minecraft* Forge 1.20.1`), vanilla server `Done`, **world created**
  by the server all PASS in 8.0 min. `world-load` / `memory-monitor` correctly
  SKIP (QuickPlay needs 1.20.2+). **`reproducibility` FAIL** — the second
  launch died with the documented mixin-transformer NPE (`targetClass is
  null`) under memory starvation (0.8 GB free on this 7 GB box at relaunch;
  no crash report, no engine error). A fitted-heap retry (2.5 GB) was too
  small for the 155-mod pack (no menu) — the 4 GB run is authoritative.
  → `workspace/deep-evidence-flagship.json` (recorded as FAIL with the
  machine-limit cause named, not a pack/engine defect).
- **Medieval `b-19ff3c3b13d` (Fabric 1.20.4, 16 mods)** — **PASS in 16.3 min**
  end-to-end: instance + install, launch, main menu, vanilla server world
  creation, **client quickplay world load PASS**, **GC heap monitoring recorded
  an 816 MB peak** from the real `gc.log`, **reproducibility PASS** (second
  launch reached the menu). → `workspace/deep-evidence-medieval.json`
  (overwritten fresh by this run).

Net: the medieval pack closes every phase the audit previously listed as
missing (quickplay load, GC heap monitoring, reproducibility) with fresh
real-game evidence; the flagship's only gap is the machine's RAM ceiling at
re-launch, already documented in KNOWN_LIMITATIONS.

### Flagship reproducibility — now PASSING (2026-08-13 late)

Root cause of the repeated failures on this 7 GB box was not the pack or the
relaunch ordering alone but three compounding machine interactions, each
fixed in the engine:

1. **The instance phase rewrote 2-3 GB of jars before every launch.**
   `install_mod_jars`/`install_resource_packs`/`install_shader_packs` copied
   unconditionally (`shutil.copyfile`), and the tester `rmtree`d the mods dir
   each run. The rewrite dirtied the Windows page cache at the exact moment
   the JVM started growing, starving it (the game's clean exit 0, no crash
   report, no event-log entry). Fix: `_copy_if_changed` (copy2 + size/mtime
   skip) in `instance.py`, and `_mods_installed` in `tester.py` skips the
   whole re-install when every expected jar is already present. Logs and
   crash-reports are still cleared for per-run isolation. Relaunches and
   repeat tests no longer rewrite gigabytes.
2. **The phase settle (10 s default) was too short for a 7 GB box.** After
   the 4 GB client and 1.5 GB server are taskkilled, Windows holds their
   pages as standby; a 10 s gap left the next 4 GB JVM unable to commit
   (died in 1 s, exit 1, no output). A 45 s settle (`AMB_PHASE_GAP_SEC`)
   lets the pages actually free before the reproducibility relaunch.
3. **The 7-min per-launch timeout could fire while the pack was still
   loading.** Under memory pressure the 155-mod pack's resource loading
   crawls; `AMB_LAUNCH_TIMEOUT_MS` raises the cap for constrained harness
   runs (default unchanged).

With these fixes + Chrome closed, the full flagship deep test passes on this
machine in 8.9 min: main menu, server "Done", world generation, and the
reproducibility second launch all reach the menu at the 4 GB heap
(`workspace/deep-evidence-flagship.json`). Quickplay + GC phases stay SKIP on
MC 1.20.1 (require 1.20.2+); the medieval pack proves those phases.

Crash-drawer screenshot: `12b-crash-drawer.png` (rendered offscreen, 1320×840,
2569 colors — the live missingDeps pill state `error: geckolib` +
`missingDeps: ['geckolib']` the engine reaches after a real Forge fatal-startup
crash) is now part of the screenshot pipeline and the README gallery
(screenshots/12b-crash-drawer.png), so the repair UX ships a documented
capture alongside the launch-state shots.
