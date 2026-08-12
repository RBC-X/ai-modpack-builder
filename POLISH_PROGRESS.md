# Launcher Polish — Live Progress

**Quality bar:** match or exceed CurseForge / Modrinth desktop launchers — visually (spacing, typography, states, icons) and on the backend (robustness, honesty, real tests).

**Method:** builder → inspect real output → fresh-context critique → fix → re-verify. Every round logged below with evidence.

---

## Baseline

| Check | Result | Evidence |
|---|---|---|
| Backend unit suite | — | `node --test dist/tests/unit/*.test.js` |
| Acceptance test | — | `node --test dist/tests/acceptance.test.js` |
| PyQt smoke test | — | `pyqt/smoke_test.py` |
| Engine health | — | `GET /api/health` |
| Visual audit | — | screenshots / widget-tree inspection per view |

---

## Round log

### Round 1 — Reconcile correctness on real acceptance builds (backend)

**Builder:** the live acceptance build exposed five real defects; all fixed and
proven against the actual failing build's data.

| # | Defect found in real output | Fix | Evidence |
|---|---|---|---|
| 1 | Interpreter read the leading verb "**Create** a lightweight…" as the Create *mod* feature → dragged create-fabric + aquatic-ambitions + ponder into a fantasy pack | Strip imperative sentence-openers before feature matching (`prompt.ts`) | acceptance provider-queries show zero create/technology searches |
| 2 | `fabric.mod.json` version constraints were **discarded at parse** (Create demands `fabric-api >=0.92.6+1.20.1`, pack shipped 0.92.1 → real launch error) | `jarmeta.ts` captures `versionRange` on every dep (fabric depends, quilt versions, Forge versionRange) | unit tests + live: fabric-api re-picked 0.92.1 → 0.92.11 |
| 3 | Reconcile was **one-shot** — jars it added were never re-scanned → kilt/kubejs deps missed | iterative fixpoint (bounded passes) | iterative kilt/kubejs unit test |
| 4 | Dep matching ignored the jar's provided mod id (`create` vs project `create-fabric`) | provided-mod-id index | create→create-fabric unit test |
| 5 | `parseVersionRange` couldn't handle Modrinth `+` build metadata or comma-less pins → `versionSatisfies` always false | range parser handles `0.92.6+1.20.1` and `[0.5.1-f-build.1417+mc1.20.1]` | real-string checks all correct |

**Critic (fresh context, inspecting real output):** the acceptance build then
launched with **0 errors and the world loaded** — but the reconcile log still
flagged `calio`, `kanos_config`, `cardinal-components-*`, `cloth-config2` as
"could not be found" even though the game booted fine. Root cause: the index
only knew a jar's *own* id, not its `provides` aliases or embedded jars.

**Round-2 fixes (this round):**
- `util.ts`: buffer-based `listZipEntriesBuf` / `readZipEntryBuf` (nested-jar
  reads, single file read per jar instead of 3–4).
- `jarmeta.ts`: `providedModIds()` — own id + `provides` aliases +
  **recursive** embedded-jar ids (origins.jar embeds apoli.jar, which embeds
  calio.jar + cloth-config; Forge jarjar auto-discovered).
- `reconcile.ts`: index all of them; **only enforce a jar-declared version
  range when the dep is its own selected node** — never against a
  provided/embedded alias (yungs/cloth-config2 case) and never against
  fabric-api bundle submodule versions (`fabric-screen-api-v1 >=1.0.4` is not
  the bundle's 0.92.x).

**Real validation (live acceptance, `b-msmwhhwq-8c6f30f7`):**
- Acceptance: **PASS** — instance ✓ Mojang 1.20.1+fabric (65 libs) ✓ launch ✓
  main-menu reached ✓, 0 repairs.
- Reconcile log: **zero warnings, zero drops** (was 3 phantom conflicts + 2
  phantom drops). yungs-better-caves, origins, modmenu all kept.
- Launch log: 0 errors.
- Backend suite: **217/217** (new: recursive providedModIds, provides-alias
  satisfied, mod-menu submodule-range, yungs/cloth-config2 — all were real
  failures first).

### Round 2 — Deep-mode gate on real hardware (Fabric 1.21.1)

**Builder:** new `src/scripts/deep-acceptance.ts` drives a real deep build
(client launch → vanilla server + world creation → quickplay world load + GC
monitoring → reproducibility). The first run **failed the gate with five real
defects**, each root-caused from actual crash reports / loader output and fixed:

| # | Real failure found by the deep gate | Fix | Evidence |
|---|---|---|---|
| 1 | **53-mod pack for an "around 8 mods" request** — interpreter's count regex required 2–4 digits (`\d{2,4}`), so "around 8 mods" parsed `targetModCount 0` and the selector fell back to pack-size defaults (structures 17 + performance 23) | count regex `\d{1,4}` | deep pack now **14–16 mods**; unit tests for single-digit + RAM-not-a-count |
| 2 | **mixin `InvalidInjectionException` at bootstrap** — modernfix (`perf.fix_loop_spin_waiting`) + server-snapshot-performance-backports (`MinecraftServerFixParkNanosMixin`) both patch `MinecraftServer.managedBlock` | new `server-loop-performance` fork rule; new `duplicate-mixin-target` crash signature (parses "merged by … from mod X" naming BOTH mods); **latent bug fixed**: fork-rule matching normalized only the node slug, so hyphenated members never matched | conflict + crashparse regression tests; client reaches menu |
| 3 | **Missing dep `forgeconfigapiport`** — Modrinth search returns only kilt-forgeconfigapiport-fix for the concatenated modid (no modid→slug API) | `MODID_SLUG_FALLBACKS` (forgeconfigapiport → forge-config-api-port) in the reconcile fallback chain | unit test; loader screen clean |
| 4 | **`zfastnoise breaks noisium`** — jar-metadata `breaks`/`conflicts` were never read, so the loader's own incompatible-mods screen killed the launch | jarmeta parses `breaks` (fabric/quilt/forge `incompatible`); reconcile adds `incompatible` graph edges; conflict engine auto-resolves the lower-importance side (`provider_incompatibility`) | unit tests; loader screen clean |
| 5 | **Server died with `UnsupportedClassVersionError`** — deep test hardcoded `detectJava(17)`; the 1.21.1 server jar is compiled for Java 21 (class 65.0) | server phase now uses `javaFor(majorOf(mc))` like the client | server-test.log: `Done (11.455s)!` |
| 6 | **Repro launch stalled 120s** — `repro-2` launched without `watchFor`, defaulting to 'world' which never fires on a plain client launch | `watchFor: 'menu'` on the repro launch | (round-3 re-run confirms no stall) |

**Result:** deep test **PASS** — instance ✓ Mojang 1.21.1+fabric (71 libs) ✓
main menu ✓ server `Done` ✓ **world creation ✓** **quickplay world load ✓**
**GC memory monitor ✓ (real peak 774 MB)** **reproducibility ✓**. Pack:
14 mods for the 8-mod request (down from 53). Backend suite **224/224**.

### Round 3 — Forge deep-mode gate (Fabric 1.21.1 re-verified, Forge 1.20.1 added)

**Builder:** `deep-acceptance.js` now takes `[mcVersion] [loader]` args
(Fabric 1.21.1 default; `1.20.1 forge` for the Forge path).

| Run | Result | Evidence |
|---|---|---|
| Fabric 1.21.1 (round 2 fix) | **PASS in 156s** | main menu ✓ server `Done` ✓ world created ✓ **quickplay world load ✓ GC heap peak 725 MB ✓** reproducibility ✓; 0 STALLs (repro `watchFor: 'menu'` fix confirmed); 13 mods for an 8-mod request; 3/3 exports validated |
| Forge 1.20.1 | **PASS** | Mojang 1.20.1+forge (65 libs) ✓ main menu ✓ (**window evidence** `Minecraft* 1.20.1`) server `Done` ✓ world created ✓ reproducibility ✓; world-load + memory-monitor **honestly SKIP** (quickplay needs 1.20.2+); 17 mods, 0 repairs, 0 conflicts, 3/3 exports validated |

**Critic notes:** the Forge run also proves the round-2 server-Java fix is
version-correct both ways (1.21.1→Java 21, 1.20.1→Java 17). PyQt smoke test
still green against the restarted engine.

### Round 5 — Quilt deep-mode gate (last loader path)

**Builder:** `deep-acceptance.js 1.21.1 quilt`. The first run failed fast with
three real Quilt-specific defects, each proven from the loader's own error
screen + the installed jars' metadata:

| # | Real failure | Fix | Evidence |
|---|---|---|---|
| 1 | **`Placeholder API requires fabricloader >=0.15.0, which is missing!`** — the installer picked `loaders[0]` = quilt-loader 0.20.0-beta.9 (Quilt's meta has NO stable flag and sorts by build, not semver), and 0.20.0-beta.9's `quilt.mod.json` provides `fabricloader 0.14.21` | `pickNewestLoaderVersion()`: semver-sort, prefer no `-beta/-alpha/-pre/-rc` (honor explicit `stable` flags when present) | live run installs **quilt-loader 0.30.0**, whose metadata provides `fabricloader 0.19.2`; loader picker unit tests |
| 2 | **`Selected mod QSL has no versions for MC 1.21.1 / loader quilt`** → QSL (the essential library) dropped → Mod Menu dropped → `quilt_resource_loader` unsatisfied → everything cascaded | Modrinth `getVersions` re-queries the parent minor (1.21.1 → 1.21) when the exact MC has zero builds — QSL ships `11.0.0-alpha.3+0.102.0-1.21` for the 1.21 minor only, which is exactly what 1.21.1 Quilt packs use; `resolve.validate()` accepts the parent minor too | live: `Essential library added: QSL … 11.0.0-alpha.3+0.102.0-1.21`; provider + solver unit tests |
| 3 | **`RailOptimization requires any version of fabric` / modmenu's dep on the fabric-api project** — on Quilt the fabric API surface is provided by the **QSL project** (its jar `provides: ["fabric-api","fabric"]`, embedding quilted_fabric_resource_loader_v0), and fabric-api itself has no quilt builds | `mapJarDepId` maps `fabric`/`fabric-*`/`quilted_fabric_api` → `qsl` for the quilt loader; `resolve.handleDependency` re-targets provider deps on the fabric-api bundle project to QSL; reconcile's `unless` check now also consults the provided-index (embedded-jar aliases) | live: modmenu kept, pack 5→11 mods; 3 new unit tests (mapJarDepId quilt, solver re-target, unless-via-provided-index) |

**Quilt 1.21.1 deep run: PASS** — Mojang 1.21.1+quilt (71 libraries) ✓ main
menu ✓ (window `Minecraft* 1.21.1`) server `Done` ✓ world created ✓
**quickplay world load ✓ GC heap peak 1170 MB ✓** reproducibility ✓ —
**11 mods** for the 8-mod request, 197s, 0 repairs. The only honest drop:
More Culling, because cloth-config genuinely publishes no 1.21.1 quilt builds.
**All four loader deep gates (Fabric / Forge / NeoForge / Quilt) now pass live.**

### Round 6 — Cross-loader regression sweep + PyQt visual A/B

**Backend:** round 5 touched the loader picker (now also governs Fabric), the
Modrinth provider (minor fallback), the solver (patch-compat + fabric-api→qsl
re-target) and reconcile (unless-via-provided-index). Re-verified both paths
that hadn't run since:

| Run | Result | Evidence |
|---|---|---|
| Standard acceptance (Fabric 1.20.1 flagship) | **PASS** | `acceptance.test.js` — real launch + main menu, 116s, `"test": "PASS"` |
| Fabric 1.21.1 deep gate | **PASS in 177s** | main menu ✓ server `Done` ✓ world created ✓ **quickplay world load ✓ GC heap peak 816 MB ✓** reproducibility ✓ — 13 mods, 0 repairs |

**Visual A/B — new `pyqt/visual_ab.py`:** renders every screenshot offscreen
and measures what geometry audits can't — content-vs-background fraction per
vertical band, text presence, and the largest empty region in the content
area. Two real layout gaps vs the CF/Modrinth bar, both fixed and re-proven:

| View | Before | After | Fix |
|---|---|---|---|
| Settings | content ended at ~490px in an 840px window (69.7% largest-blank) | panel fills the column (**70% content**, blank 69.7% → 35.5%) | `QSizePolicy.Expanding` on the panel + `addLayout(row, 1)` + nav pinned top (full-height settings surface like reference launchers) |
| AI Builder | form block ended ~670px leaving a dead band (62% blank) | form **vertically centered** (probe: body 790, form 310–682, balanced stretch both sides) | `_center_form()` inserts/removes two stretches around the form — removed while the timeline/done cards show so a running build stays top-aligned |

Reference captures (crash drawer, launch overlay) measure 99–100% content —
Library/Home/Pack views already met the bar. Geometry audit stays **0 findings**;
PyQt smoke test **PASS** after the layout changes.

### Round 4 — NeoForge deep gate + automated visual audit (PyQt)

**Builder, backend:** `deep-acceptance.js 1.21.1 neoforge` — the last unproven
loader path. Two real NeoForge-specific bugs found and fixed, both from live
run output:

| # | Real failure | Fix | Evidence |
|---|---|---|---|
| 1 | **"No neoforge build found for 1.21.1"** — the lookup used the Forge-style `1.21.1-` prefix, but NeoForge maven versions ENCODE the MC version (`21.1.147` for MC 1.21.1, `20.4.x` for 1.20.4, `21.0.x` for 1.21) | `neoForgeVersionPrefix()` derives `<minor>.<patch>.` from the MC version | unit test; live run resolves `neoforge 21.1.248` |
| 2 | **ENOENT on the installed version JSON** — the NeoForge 21.1 installer names its profile folder `neoforge-21.1.248` (NO MC prefix), the code assumed `1.21.1-neoforge-21.1.248` | detect the folder the installer actually created (readdir match) | live run: `versions/neoforge-21.1.248` read correctly |

**NeoForge 1.21.1 deep run: PASS** — Mojang 1.21.1+neoforge (71 libraries) ✓
main menu ✓ (window evidence `Minecraft NeoForge* 1.21.1`) server `Done` ✓
world created ✓ **quickplay world load ✓ GC heap peak 1075 MB ✓**
reproducibility ✓ — 11 mods for an 8-mod request, 302s, 0 repairs.

**Builder, visual: new `pyqt/visual_audit.py`** — walks every view's real
widget tree offscreen (11 views, real geometry) and reports measurable defects
(text wider than its widget, zero-size widgets, negative sizes). Round-1 audit
found one genuine bug: the sidebar account card clipped
`Status: Offline profile` (needed 118px, had 94px). Fixed by widening the card
and shortening the text. The audit then uncovered **two audit bugs of its own**
(an incorrect padding offset that false-flagged every nav label, and transient
zero-heights while the Downloads view streamed live build events) — fixed with
an exact-fit metric and a settle+confirm pass. **Final: 0 findings across all
11 views.**

## Remaining gaps

- **Quilt deep run** — shares Fabric machinery (meta API + intermediary) and
  the deep gate is now parameterized, but a live Quilt run is the honest way
  to claim all four loaders.
- **CurseForge live tests** — blocked on a real CurseForge API key (search,
  manifest-reference exports are unit-tested only).
