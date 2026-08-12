# Master Spec Gap Matrix

Generated 2026-08-12 from a real audit of the repository (engine + PyQt launcher).
Statuses are honest — they reflect actual code paths and test results, not intent.

Legend:
- ✅ ALREADY EXISTS (implemented + tested)
- 🔶 EXISTS, NEEDS EXPANSION (working core, gaps vs spec)
- 🟡 PARTIALLY EXISTS (some pieces, not the whole feature)
- ❌ DOES NOT EXIST
- ⛔ BLOCKED BY ANOTHER FEATURE

## Foundation (this round: 2026-08-12)

| Area | Status | Evidence |
|---|---|---|
| Pack Identity (§9, §111) | ✅ implemented | `engine/identity.py` — derived from requirements, persisted per pack, editable via `set_identity`; 4 identity unit checks pass |
| Semantic mod intent (§11, §55) | ✅ implemented | `engine/identity.intent_for` — role, why-selected, importance, replaceability, alternatives, costs, locked; attached on every read (`_attach_identity`); verified in tests + UI |
| Snapshots (§22, §23) | ✅ implemented | `engine/snapshots.py` — content-addressed manifests (config hashes, exact selections, identity), no binary duplication; newest-first listing, restore |
| Last Known Good (§24) | ✅ implemented | auto-marked after every PASS (build, retest, promotion); one-per-pack with supersede; `restore_last_known_good`; UI button |
| Transactional AI edits (§14, §66) | ✅ implemented | `apply_ai_change` → before-edit snapshot → candidate child build → promote only on PASS (`_promote_candidate`); rejected candidates leave the parent untouched + recorded in `aiHistory`; instance files synced on promotion |
| AI change plan (§13) | ✅ implemented | `engine/plan.py` — deterministic, non-mutating: interpretation, mods added/removed, RAM impact, confidence, risk, preserved identity; plan-preview dialog in Ask-AI flow |
| Persistent AI history (§65) | ✅ implemented | `aiHistory` append-only on the record: snapshot / promote / rejected entries with timestamps |
| Intent-preserving repair (§10) | 🟡 planned — repair keeps `featureIds`/reason today; role-aware replacement is next |

## Core pipeline (already existed — verified this round)

| Area | Status | Evidence |
|---|---|---|
| Provider abstraction (§46) | ✅ Modrinth + CurseForge | `engine/providers/` — real API calls; live search in engine self-test |
| Prompt interpreter | ✅ | `engine/interpreter.py`; tested |
| Mod ranking with reasons (§19) | ✅ | `engine/rank.py` — score + human reason + factors |
| Dependency solver (§48) | ✅ | `engine/solver.py` — recursive, required/optional/incompatible |
| Version solver (§49) | ✅ | solver with downgrade/upgrade/alternative candidates |
| Conflict engine (§50) | ✅ | `engine/conflict.py` + compatibility memory |
| Repair agent (§52, §53) | ✅ | `engine/repair.py` — bounded, evidence-based, explainable entries |
| Isolated testing (§78) | ✅ | per-pack isolated instance; INSTANT/STANDARD/DEEP levels |
| Crash parsing + diagnosis | ✅ | `repair.parse_crash_report`, stack-trace attribution |
| Exports (§56, §92) | ✅ | mrpack + CurseForge zip + server pack, validated after generation |
| Imports | ✅ | CurseForge/Modrinth/zip; cf_import_edge_test |
| Hardware detection + RAM fit (§31) | ✅ | `engine/hardware.py` |
| Shader engine + presets | ✅ | `engine/shaders.py` — performance/balanced/cinematic, live-selected |
| Resource-pack engine | ✅ | `engine/resource_packs.py` |
| Self-update + rollback (§115) | ✅ | updater with default feed, SHA + Authenticode, `/DIR` pin, installer-pool rollback |
| Credential security (§80) | ✅ | CurseForge key in Windows secure storage, never logged/committed |
| Download safety (§47) | ✅ | size caps, SHA-1 verify, path-traversal-safe extraction, zips |
| Compatibility memory (§51) | ✅ | `engine/compat.py` — real test results persisted |

## Phased features (from the spec's own release plan)

### Phase 2 — lifecycle management
| Feature | Status |
|---|---|
| Smart update (candidate, not blind UPDATE ALL) | 🟡 per-mod updates exist; group-solve + keep-older + performance compare is next |
| Pack health dashboard (§37) | 🟡 testResult + launch state shown; score/health summary pending |
| Pack score (§36) | ❌ |
| Performance optimizer + A/B (§33–35) | 🟡 perfEstimate exists; optimizer candidate pass is next |
| Changelog/history timeline (§90, §25) | 🟡 aiHistory recorded; visual timeline pending |
| Feature overlap / balance analysis (§96–97) | ❌ |
| AI risk level (§106) | 🟡 plan.impact.risk exists; broader risk model pending |

### Phase 3 — social / multiplayer
| Feature | Status |
|---|---|
| Pack codes (§26) + Join Friend (§27) | ❌ (design: share manifests of provider references, never binaries) |
| Multiplayer-safe mode (§28) | 🟡 multiplayer flag + server pack exist; certification gate pending |
| Multiplayer-ready certification (§29) | ❌ |
| Server creation assistant (§30) | 🟡 server pack export exists; guided assistant pending |

### Phase 4 — AAA UX
| Feature | Status |
|---|---|
| Home "what do you want to do" + starter concepts (§5, §8) | 🟡 home has core actions; starter-concept cards pending |
| Surprise Me concept generator (§7) | ❌ |
| Favorites / collections (§42–43) | ❌ |
| Download manager with pause/resume (§40, §75) | 🟡 downloads recorded; pause/resume pending |
| Storage manager (§76) | ❌ |
| Onboarding (§73) | ❌ |
| Empty states everywhere (§72) | 🟡 several exist; audit pending |
| Pack version timeline / branching (§25, §94) | 🟡 snapshots + aiHistory are the substrate; UI timeline pending |
| Pack inspector per-mod intents (§62) | 🟡 selections carry intent; inspector columns pending |

## Cross-cutting
| Area | Status |
|---|---|
| Failure injection tests (§120) | 🟡 several edge tests exist; systematic matrix pending |
| Real-world test matrix A–H (§121) | 🟡 A/B/D/E/F exercised in repo; C/G/H partial |
| Hardware test profiles (§32, §122) | 🟡 one detected profile; saved profiles pending |
| Docs (§127) | 🟡 README/ARCHITECTURE/CHANGELOG/PROJECT_STATUS current; PACK_IDENTITY.md, SNAPSHOTS.md, AI_SYSTEM.md added this round |
| Live dev dashboard (§130) | 🟡 PROJECT_STATUS is the honest record; per-subsystem critic loop documented in CHANGELOG |

## Next highest-priority work
1. **Smart update** (transactional update candidate reusing the snapshot/promote machinery).
2. **Pack health dashboard + pack score** on top of testResult + LKG + aiHistory.
3. **Role-aware replacement engine** (FIND ALTERNATIVE) using mod intent alternatives.
4. **Starter concepts + Surprise Me** (UI-level, deterministic concept templates).
