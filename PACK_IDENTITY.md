# Pack Identity & Mod Intent

Every pack carries a **PackIdentity** — why the pack exists — and every
selected mod carries an **intent** record — why that mod is there. All AI
operations (edits, repairs, updates, replacements) consider these instead of
treating mods as interchangeable files.

## Pack Identity

Stored on the build record as `identity` (derived deterministically from the
interpreted request, persisted, editable via `set_identity`):

```json
{
  "coreTheme": "medieval, fantasy, rpg",
  "primaryGoals": ["Bosses & combat", "Magic & spells", "Improved terrain generation"],
  "secondaryGoals": [],
  "requiredFeatures": ["bosses", "magic", "terrain"],
  "optionalFeatures": [],
  "forbiddenFeatures": [],
  "lockedMods": [],
  "performanceTarget": {"ramGB": 8, "targetFps": 60, "shaders": true, "textureResolution": 32},
  "multiplayer": true,
  "style": "medieval, fantasy, rpg"
}
```

## Mod intent

Every selection returned by `build()` carries:

```json
{
  "intent": {
    "role": ["combat", "bosses"],
    "roleLabels": ["Combat", "Bosses"],
    "whySelected": "Requested boss content",
    "satisfiesRequest": ["Bosses & combat"],
    "importance": "high",
    "replaceable": true,
    "alternatives": [],
    "performanceCost": "medium",
    "dependencyCost": "medium",
    "compatibilityConfidence": 92,
    "locked": false
  }
}
```

- `locked` honors both the selection's own flag and the pack identity's
  `lockedMods` — locked mods are never auto-replaced.
- `alternatives` is populated by the replacement engine (planned) — it is
  never guessed.

## API

- `identity(build_id)` / `set_identity(build_id, patch)`
- `plan_ai_change(build_id, prompt)` — non-mutating plan
- `apply_ai_change(build_id, prompt)` — transactional candidate build

Deterministic only: no LLM guesses the identity or the intent. Derivation
lives in `engine/identity.py` and is unit-tested.
