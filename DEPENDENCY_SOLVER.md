# Dependency & version solver

Implemented in `src/solver/resolve.ts`. The job: from a set of chosen "seed"
mods, produce a **dependency graph** (who needs whom, and why) in which every
project has exactly one version that is compatible with the target Minecraft
version, the loader, and **every** incoming version constraint — or report
honestly that it cannot be done.

## What the solver actually does

1. **Seed bootstrap** — each selected mod becomes a graph node; its candidate
   versions are fetched from the provider, filtered to the target MC version +
   loader, and ordered *release channel first, then newest*.
2. **Recursive expansion** — for every chosen version's `dependencies[]`:
   - `required` / `embedded` → the dependency is pulled in and an edge is
     recorded (`from → to`, kind, version range, pinned id).
   - `optional` → the edge is recorded but the dependency is **not** added
     (launchers don't auto-add optional deps; the edge is visible in the UI).
   - `incompatible` → an exclusion edge; if the target is also selected, the
     solver keeps the higher-priority node (feature priority → dependents →
     popularity) and deselects the other.
3. **Constraint fixpoint** — repeatedly re-validate every edge: the chosen
   version must satisfy every incoming `version_range` (Modrinth-style:
   `>=0.5.1`, `[1.0,2.0)`, …). On violation, a better version is picked; if
   none exists, the solver **backtracks**:
   - try other versions of the dependency itself, then
   - try older (or alternative) versions of each *dependent* (downgrade),
     bounded by an iteration budget.
4. **Final honesty pass** — after all loops, every required/embedded edge is
   re-checked; if any constraint is still unsatisfiable, an `unsatisfiable`
   issue is recorded with the exact pair of mods. Nothing is silently dropped.

## What it detects

- unsatisfied dependencies (project missing / no compatible version)
- impossible version constraints (e.g. `Mod A wants L >=2.0`, `Mod B wants L <2.0`)
- cycles (allowed — they resolve to a fixed point; reported)
- loader mismatches (only Fabric versions exist for a Forge pack)
- Minecraft-version mismatches (no version for the target MC)

## Version solving, not "latest wins"

Candidates are ordered release-first, but the chosen version is the first
candidate that satisfies **all** constraints — so a mod is downgraded when a
newer release violates a dependency's range. When no version works, the solver
escalates to the conflict engine (removal of the lowest-priority requester) and
finally to the repair agent during testing.

## Example

```
Mod A 5.2  requires Library X >=2.0
Mod B 7.1  requires Library X  <2.0
Library X candidates: 3.0, 1.5

→ A and B both selected → no single version satisfies both
→ backtrack: try Library X 1.5 (fails A), try 3.0 (fails B)
→ try downgrading B / A candidates → none work
→ unsatisfiable issue recorded → conflict engine removes the
  lowest-priority requester → graph becomes consistent
```

## Why each dependency exists (explainability)

Every node stores `reason` (`"Required by Create (create)"`), and every edge
stores its kind and range, so the UI can explain the whole graph. The build
record keeps the full serialized graph (`build.json → graph`).

## Jar-metadata reconciliation (provider APIs are incomplete)

Provider APIs only expose the dependencies an author chose to register there.
Many real mods require things the API never lists:

- `fabric` and `fabric-*` module ids (satisfied by the fabric-api bundle jar),
- library mods such as `moogs_structures` (project slug `moogs-structure-lib`),
- quilt `unless` clauses (`quilt_resource_loader` only when
  `fabric-resource-loader-v0` is absent).

After downloads, `reconcileJarDependencies` (src/solver/reconcile.ts) reads each
downloaded jar's own metadata — `fabric.mod.json`, `quilt.mod.json` (with
`unless`), or `META-INF/mods.toml` — and adds any required dependency that is
missing, downloading it from the real provider. Matching is loose but safe:
`fzzy_config` ≈ slug `fzzy-config` via normalized ids, and parenthesized ids in
titles (`"Moog's Structure Lib (moogs_structures)"`) are recognized with
token-boundary checks to avoid substring false positives.

Loader-essential libraries (`fabric-api` for Fabric, `qsl` for Quilt) are added
unconditionally by the resolver before seeds are expanded, locked so the repair
agent never drops them.

`modmenu` is bundled with the essentials for Fabric/Quilt so every pack's
instance shows an in-game mod list (Mod Menu's whole purpose). The description
research pass (`src/solver/descresearch.ts`) additionally scans each project's
real Modrinth `body` for requirement phrases ("requires Fabric API", "requires
GeckoLib to work", "(requires: X, Y)") and feeds those candidates through the
same real-provider resolution as jar metadata. It is deliberately conservative:
bare "and X" continuations (e.g. "compatible with Sodium and Iris") are NOT
treated as requirements, so prose cannot cause wrongful installs. Any
dependency whose compatible version cannot be found is skipped with an honest
warning — never a hard failure — e.g. Create Fabric declaring a "Milk" dep with
no 1.20.1 Fabric version logs `unsatisfiable` and the pack still ships.
