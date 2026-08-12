# Known limitations

Honest list of what this system does **not** do (yet), and why.

## Proven in practice vs. code-complete

- **Proven live (real evidence exists in this repo):** Modrinth search/selection/
  dependency resolution/downloads; isolated instance creation; Fabric 1.20.1
  launch to main menu (log markers + window title); vanilla server world
  creation/load; `.mrpack`/CF/server exports with validation; compatibility
  memory; SSE live UI; repair-loop mechanics (integration-tested with a real
  crash log).
- **Code-complete but not yet exercised live:**
  - **Forge / NeoForge** installation (official installer route) — this is the
    flagship 1.20.1 scenario; see PROJECT_STATUS for the live result.
  - **Deep test mode** (client quickplay world load, GC-log heap monitoring,
    reproducibility launch) — the code paths exist and are wired, but have not
    produced live evidence yet.
  - **Live repair on an organic crash** — the loop is exercised deliberately
    (see the repair-exercise run), but no production pack has crashed
    organically during acceptance runs.

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
