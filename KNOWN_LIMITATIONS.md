# Known limitations

Honest list of what this system does **not** do (yet), and why.

## Proven in practice vs. code-complete

- **Proven live (real evidence exists in this repo):** Modrinth search/selection/
  dependency resolution/downloads; isolated instance creation; Fabric 1.20.1
  launch to main menu (log markers + window title); vanilla server world
  creation/load; `.mrpack`/CF/server exports with validation; compatibility
  memory; SSE live UI; repair-loop mechanics (integration-tested with a real
  crash log).
- **Also proven live:** Forge 1.20.1 installation and launch; deep test mode
  across the flagship Forge and medieval Fabric packs; quickplay world load,
  GC heap evidence and reproducibility; and repair of a real missing-dependency
  crash. The dated evidence and machine constraints are recorded below.
- **Still not fully generalizable:** NeoForge has automated coverage but no
  equivalent long-form live acceptance artifact in this repository, and
  obfuscated/reflection-heavy organic crashes can still fall back to heuristic
  attribution.

## External constraints (cannot be solved in code)

- **CurseForge requires your API key.** Without `CF_API_KEY` (or a key in
  Settings) the provider reports unavailable and packs build from Modrinth
  only. With a key, searches and manifest references work; **CF jars are never
  bundled** (distribution policy) — packs reference them via manifest.
- **Microsoft account sign-in requires a launcher app registration.** The
  desktop flow is implemented, but Microsoft may require the public-client app
  ID to be approved for `XboxLive.signin`. A real account consent/ownership
  check cannot be automated headlessly; automated game tests remain offline.
- **Disk space** on this machine was a hard limit during development (~0–1 GB
  free): full asset downloads (~1.1 GB for 1.20.1) were budget-capped, and
  larger Forge installs may fail with ENOSPC. The tool caps and reports this
  honestly.
- **Shaders** are searched and downloadable, but shader *rendering* is not
  verified at runtime (requires GPU/display interaction beyond log analysis).
- **Resource pack resolution/theme matching** is keyword-based; a perfect
  32x-fantasy match is not guaranteed.

## Design limitations (by choice)

- The **version solver** prefers downgrades and alternatives within provider
  candidates; "try another equivalent mod" is delegated to the conflict engine
  / repair agent, which currently removes rather than replaces.
- The **interpreter is rule-based** (deterministic, testable); it does not
  understand arbitrary free-form nuance beyond the covered patterns.
- **Instant mode** cannot prove a pack launches — it is static validation only,
  by design.
- **Optional dependencies** are recorded as edges but not auto-added (standard
  launcher behavior).
- Repair "downgrade/upgrade version" strategies exist in the decision table for
  memory-driven cases but are not yet triggered by live data.

## After the bug / reliability / UI repair pass (2026-08-13)

Facts below are proven by `pyqt/bugfix_regression_test.py` (84/84 PASS) and
the live suites, not by inspection. Full per-issue record: `BUG_FIX_AUDIT.md`.

- **Snapshot restore is content-true for config state**: config content is
  stored as objects (`data/objects/<sha256>`) and reconstructed byte-for-byte
  on restore (verified with written marker bytes). Artifacts are recorded by
  provider + project/version/file IDs + hash, so a restore re-acquires the
  exact legal file when the local cache is gone — but **provider availability
  is an external dependency**: if Modrinth/CF is unreachable and the cached
  jar was deleted, the restore degrades to a recorded state rather than a
  fully materialized instance.
- **Promotion is fail-closed**: any sync/verify failure leaves the parent
  record and instance byte-identical and records `promote-failed`; the
  candidate stays on disk for diagnosis. Physical parity (removed mods
  deleted, config promoted, missing candidate dirs = empty) is asserted by
  tests, not just the happy path.
- **Manual add/remove are dependency-safe**: duplicate provider/project
  selections are blocked *before* any network call; removing a required
  library is refused and names its dependents. A dependency that cannot be
  resolved still fails the candidate rather than promoting a partial pack.
- **Test results are revision-safe**: a mid-test pack mutation cannot be
  overwritten by the stale test thread; `NEEDS_VALIDATION` is shown whenever
  `testedRevision != revision`; infrastructure failures persist an explicit
  `ERROR` record instead of leaving old PASS evidence looking current.
- **Logs/files API is a single explicit contract** with path containment:
  `../secret`, drive-qualified, UNC and absolute paths are rejected; the
  Pack Detail log selector is driven by the same enumeration.
- **Archive imports are bounded**: traversal members are dropped, single-file
  size, entry count and declared uncompressed-size limits are enforced, and
  oversized members abort cleanly without touching existing packs.
- **UI truthfulness repairs**: one authoritative terminal build outcome
  (testResult preferred) used by timeline, done card and Play; no stuck
  spinner on successful builds; Settings is a true overlay (no stack-routing,
  no manual `showEvent`); Library reflows on resize; 960px-fixed screens are
  max-width and shrink to fit 1080×700.

Remaining honest gaps from that pass (with later resolutions recorded below):

- `~` (tilde) ranges now enforce an upper bound for npm-style semantics, but
  Minecraft versions are not strict SemVer; mixed-format ranges (`1.20.x`,
  snapshots) still rely on the provider's own filtering as the final judge.
- Process-group isolation (`start_new_session`) is implemented for Unix-style
  kills; Windows uses TaskKill and remains the platform actually exercised.
- At the time of that pass, deep mode, Forge live-install, and organic-crash
  repair still lacked fresh evidence. The dated runs below subsequently closed
  those three evidence gaps; the current constraints are stated there.

Updated 2026-08-13 — the gaps above are now closed by real runs:

- **Deep mode**: flagship (Forge 1.20.1, 155 mods) PASS in 8.6 min
  (install/launch/menu/server world/reproducibility; quickplay+GC correctly
  gated to 1.20.2+); medieval (Fabric 1.20.4, 16 mods) PASS in 16 min with
  real **quickplay world load** and **GC heap 815 MB peak** evidence
  (`workspace/deep-evidence-*.json`).
- **Organic crash repair**: real geckolib removal → Forge fatal-startup crash
  → live `missingDeps: ['geckolib']` → add-missing → relaunch → main menu
  → stop (`.freebuff/repair-exercise5.log`).
- **Non-missing-dep crash attribution**: stressed-heap load crash
  (OutOfMemoryError) → `attribute_crash` names ars-magica-legacy from real
  stack frames; missing-dep scan stays `[]` so no garbage mutation
  (`workspace/npe-evidence.json`).
- Remaining real limits: this 7 GB box requires the `AMB_BYPASS_RAM_GUARD=1`
  escape hatch for headless verification runs (the launcher's 1 GB free-RAM
  guard refuses otherwise); Windows is still the only exercised platform;
  attribute_crash's `exact-class` confidence relies on the jar being named in
  the stack, so obfuscated/mod-reflected crashes can still fall back to
  heuristic attribution.
- Hardened (2026-08-13): `extract_stack_frames` counts ONLY real exception
  stack frames — WARN "Error loading class:" one-liners and ERROR "Failed to
  load:" class-probe blocks (present in every healthy pack) no longer feed
  attribution. Measured effect: a healthy flagship debug.log now yields `[]`
  mod frames (previously `ars-magica-legacy` from a probe block), and the NPE
  exercise's old "ars-magica attribution" is retired as a false positive — a
  pure resource crash now correctly gets empty attribution + no mutation.
- Fresh 1.0.16 deep-test re-run (2026-08-13): the medieval Fabric 1.20.4 pack
  PASSES all deep phases on this machine (quickplay world load, GC peak
  816 MB, reproducibility). The 155-mod flagship Forge 1.20.1 pack reaches
  menu / server / world creation but its SECOND launch still dies with the
  mixin-transformer NPE under memory starvation (0.8 GB free at relaunch) —
  a hard RAM ceiling of this 7 GB box, not a pack or engine defect; a fitted
  2.5 GB heap is too small for 155 mods (no menu). Evidence:
  `workspace/deep-evidence-flagship.json` (FAIL, cause named) +
  `workspace/deep-evidence-medieval.json` (PASS).
- RESOLVED (2026-08-13 late): the flagship deep test now PASSES end-to-end on
  this box — menu, server "Done", world generation, and the reproducibility
  second launch all reached the menu at the pack's 4 GB heap
  (`workspace/deep-evidence-flagship.json`, status PASS, 8.9 min). Three
  engine fixes removed the machine-limit behavior: (1) the instance phase
  skips the 2-3 GB jar re-install when every expected mod is already present
  (`_copy_if_changed` size/mtime skip + `_mods_installed`) — the rewrite
  dirtied the page cache right as the JVM grew and caused the clean exit-0
  deaths; (2) a longer phase settle (AMB_PHASE_GAP_SEC, 45 s for this run)
  so Windows reclaims the killed 4 GB client + 1.5 GB server before the
  relaunch (10 s was not enough — the repro JVM died in 1 s, exit 1);
  (3) per-launch timeout raised via AMB_LAUNCH_TIMEOUT_MS (11 min here)
  because the pack's resource loading crawls under memory pressure. Chrome
  was closed for the run. Quickplay + GC phases remain SKIP on MC 1.20.1
  (require 1.20.2+); the medieval pack proves those phases pass.
- Retry forensics (2026-08-13 evening): with Chrome + a Thrive Gradle build
  (~2 GB of daemons) running, the 4096 MB-heap game JVM now exits code 0 at a
  VARYING point (mod discovery / class-probe) with no crash report, no hs_err,
  and no Windows Application-log entry — the same machine-instability
  signature as the documented self-closing window. 2560 MB heap runs get
  past discovery to resource loading then OOM (`Java heap space`), proving a
  lower default heap does NOT make the 155-mod pack reproducible. The
  relaunch-order fix is in: `tester.py` settles `phaseGapSec` (default 10 s)
  between deep phases so a taskkilled JVM's pages are released before the
  next 4 GB launch; end-to-end reproducibility validation needs a RAM window
  (close Chrome / the Thrive build), and the fresh flagships JSON records the
  cause + settle-fix in its `cause`/`settleFix` fields.
- Medieval re-run on the 1.0.18 engine (2026-08-13, `deep-evidence-medieval.json`):
  Fabric 1.20.4 / 16 mods PASS in 9.0 min with the copy-skip + 45 s settle
  path (events.jsonl confirms "Settling 45s before reproducibility relaunch"),
  quickplay world-load PASS, GC heap 790 MB peak, reproducibility PASS — every
  deep phase is now recorded on the shipped engine, not just the pre-fix one.
- Flagship re-run on the 1.0.19 engine with the MEASURED settle (2026-08-13,
  `deep-evidence-flagship.json`): PASS in 7.5 min — menu, server "Done",
  world generation, and the reproducibility relaunch all reached the menu at
  the pack's 4 GB heap. The adaptive settle recorded `settleSecs: [10.0,
  10.0]` (events.jsonl: "Settled 10s … free RAM 2.79 GB — pages
  reclaimed") — with RAM freed up front, reclamation was fast, so the engine
  settled at the 10 s floor instead of the old fixed 45 s, proving the gap is
  now measured per-machine. copySkip True (skip 2-3 GB re-install), engine
  1.0.19.
