# 1.0.23 Master Repair Round — Issue Ledger

Audit baseline: release v1.0.22 (tag pointed at `b014885`), repo `RBC-X/ai-modpack-builder`.
Every fix below is committed on `main` and shipped in the signed 1.0.23 installer.

## Verified issues fixed

### 1. Horizontal overflow clips content at supported sizes — HIGH (was blocking)
- **Repro**: window 1080×700 with 25 packs — Library +4…6 px, Discover up to 376 px clipped; Discover's filter row + cards were cut off; a shipped Discover screenshot visibly clipped.
- **Root cause**: (a) Library/Home tiles were sized from the scroll **viewport** before the vertical scrollbar appeared; the scrollbar then narrowed the viewport 2–6 px, so tiles came out too wide and the body clipped (the settle loop oscillated instead of converging). (b) Discover's six type pills + four fixed-width combos sat in one non-wrapping row (~1160 px minimum); `_column_count` also forced `max(width, 760)` so a one-column layout was unreachable.
- **Fix**: `_usable()` now reserves the scrollbar extent and uses the view's stable width (deterministic, no race); Discover's filters split into a type row + a controls row with real one-column support; drawer width clamps to the viewport; pager hint collapses on narrow widths. Files: `views/library.py`, `views/home.py`, `views/discover.py`.
- **Fix commit**: `45bb6b0` (shipped as 1.0.23).

### 2. Update-feed / installer download hazards — HIGH
- **Repro**: forced `max_mb=0` download → `PermissionError [WinError 32]` (partial file unlinked while still open) and a partial `.exe` left behind; hostile oversized feed buffered whole before the cap.
- **Root cause**: `download()` unlinked the destination with the handle open and had no atomic-promote path; `fetch_feed` read the body fully before checking the 2 MB cap.
- **Fix**: downloads write to a unique `.partial` and atomically promote only after size + SHA-256 verification, deleting on every failure path; the feed cap streams. Also fixed the `age > hours` throttle boundary (hours=0 now deterministically allows). Files: `updater.py`.
- **Fix commit**: `45bb6b0`.

### 3. Shutdown hard-crash (native fail-fast) — HIGH (found in audit)
- **Repro**: `rc=-1073740791` (0xC0000409) after every MainWindow session — probes and `library_persist_ui_test` all exited 127 with all checks passed.
- **Root cause**: `run_async` workers on `QThreadPool.globalInstance()` could still be running at interpreter exit and post into the module-level `_poster` while Qt was torn down. Reproduced at HEAD with changes stashed (pre-existing).
- **Fix**: `MainWindow._teardown()` stops all timers, signals import cancellation, and drains the pool (`waitForDone`); wired to `closeEvent` and `app.aboutToQuit`. Sessions now exit rc=0. File: `main.py`.
- **Fix commit**: `45bb6b0`.

### 4. Smoke test not clean-workspace safe — MEDIUM
- **Repro**: fresh checkout → `name 'first' is not defined` after "0 packs"; also a `UnicodeEncodeError` (cp1252 console printing `→`) misreported as a UI failure.
- **Fix**: isolated throwaway workspace, seeded pack fixture, `first` always defined, encoding-safe output; UI state now resolves under `AMB_WORKSPACE` so tests never read a developer's prior prefs. Files: `smoke_test.py`, `views/misc.py`.
- **Fix commit**: `45bb6b0`.

### 5. Mouse-only cards block keyboard users — MEDIUM
- **Fix**: `make_clickable` now sets the accessible name via `setAccessibleName` (not tooltip alone) and accepts an accessible description; four card surfaces verified tab-reachable with Enter/Space activation and no nested-button triggering. Files: `common.py`, `views/packcard.py`, `views/library.py`, `views/home.py`, `views/discover.py`.
- **Fix commit**: `45bb6b0`.

### 6. Test-harness defects (test-only but masking real coverage) — MEDIUM
- `autocheck_toggle_test` patched `main.run_async` while `_auto_check_update` lives in `views/health_mixin.py` (patch silently inert, real thread raced the assert).
- `density_home_test` compared the first tile of two grids holding **different packs** (Library sorted by newest vs Home `builds[:3]`) — the 14 px mismatch was name-wrap, not a bug; also measured at a width where Cozy/Compact don't express distinct layouts.
- `shader_swap_test` broke on the async retest's own TESTING marker (polled for presence, not completion).
- **Fix commits**: `45bb6b0` (density, shader_swap) and the earlier autocheck fix (in 1.0.22).

### 7. Release provenance broken — HIGH
- **Repro**: `git rev-parse v1.0.22^{}` → `b014885` (CI screenshot bot commit; `APP_VERSION` still 1.0.21, fixes absent) while the published installer was built from the `113bedd` tree; `origin/main` had drifted ahead.
- **Fix**: `v1.0.22` tag force-moved to `113bedd` (the real source of the 1.0.22 installer); supersession documented in `RELEASING.md`; 1.0.23 built from a **clean checkout of its own tag** (`git worktree add` at `v1.0.23`), with `AMB_VENV_PY` letting a fresh checkout reuse the shared toolchain venv.
- **Fix commits**: `45bb6b0`, `fda3d42`, `30ca5d3`.

## Changed files (shipped in 1.0.23)

`pyqt/views/library.py`, `pyqt/views/home.py`, `pyqt/views/discover.py`, `pyqt/views/misc.py`,
`pyqt/views/packcard.py`, `pyqt/main.py`, `pyqt/common.py`, `pyqt/updater.py`,
`pyqt/build_installer.py`, `pyqt/smoke_test.py`, `pyqt/density_home_test.py`,
`pyqt/shader_swap_test.py`, `pyqt/product_config.py`, `CHANGELOG.md`, `RELEASING.md`,
`screenshots/` (24 fresh renders), new `pyqt/responsive_layout_test.py`.

## Verification evidence (exact)

- `python -m compileall pyqt` → **rc=0** (138 files).
- Gate battery (31 offline suites): **31 passed, 0 failed** — bugfix 114/114, security 13/13,
  update-feed 23/23, WCAG 10/10, engine 18/18, identity 33/33, health 150/150, density 15/15,
  smoke PASS, responsive PASS, plus shader/RP/CF/updater-UI suites.
- `pyqt/responsive_layout_test.py`: **PASS** — 7 sizes × 100/125% scale × sidebar states ×
  populated/empty + keyboard + drawer checks; fails on any nonzero horizontal scrollbar or clipped control.
- Updater edge suite (Windows): forced size overflow + hash mismatch → intended exception, **zero
  `.exe`/`.partial` residue**, no installer launch.
- Build (clean checkout at `v1.0.23`): PyInstaller bundle → signed app exe → frozen selftest
  **rc=0** (8 checks) → Inno Setup 28 MB → signed **Valid** (`CN=AI Modpack Builder, O=AI Modpack Builder`)
  → silent install to isolated prefix → installed-app selftest **rc=0**.
- Installer SHA-256 `8edd682ad469bb74f58d12cdfdccc2d4764d30a975b8a5d9c959c3b3f2ddd7e8` == feed
  `installerSha256`; feed `notes` = real CHANGELOG (not a filename).
- Auto-update: installed 1.0.22 → `--check-update --apply-update` rc=0, `applied: True` → now
  reports `current: 1.0.23, available: False`, frozen selftest **rc=0**, fresh exe.
- Provenance: `git rev-parse v1.0.22^{}` = `113bedd`; `git rev-parse v1.0.23^{}` = the commit
  whose clean worktree produced the signed installer; `origin/main` == local `main`.

## Before/after (responsive failures)

Objective gate: the responsive matrix fails if any page's horizontal scrollbar maximum is nonzero
or any control lies outside the viewport. Old gallery renders (committed before this round) vs the
fresh 24-shot set differ on every layout page — e.g. `02-library.png` and `07-discover.png` were
the clipped captures; the new renders have no clipped cards/filters (verified by pixel diff and the
matrix). The literal old PNGs remain available in git history (`a5ed4f7`).

## Remaining unverified / external prerequisites

- Real-game deep tests (quickplay, GC heap, reproducibility) and dual-launch/sustained-hold require
  a live Minecraft session and free RAM — not exercised in this round (no user game instance).
- Microsoft sign-in, rollback-from-broken-update, and CurseForge key flows need their live
  credentials/endpoints; the embedded-key and provider tests cover the offline contract only.
- CI's screenshot-regeneration workflow will push its own gallery after this push (bot commit) —
  expected noise; the workflow is green and its author-guard prevents self-triggering loops.
