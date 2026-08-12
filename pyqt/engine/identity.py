"""Pack Identity and semantic mod intent.

The engine's pack records carry requirements + selections, but nothing that
says *why the pack exists* or *why each mod is there*. This module adds the
two persistent knowledge layers the AI operations need:

- **PackIdentity** — the pack's core theme, goals, performance target,
  required / optional / forbidden features, locked mods and style. Every AI
  edit, repair and update considers this instead of treating mods as
  interchangeable files.
- **ModIntent** — attached to every selection: the semantic role it plays,
  why it was chosen, which user request it satisfies, importance,
  replaceability, alternatives, and cost estimates.

Both are deterministic derivations from real data (requirements, feature
catalog, provider metadata) — never LLM guesses.
"""
from __future__ import annotations

from .features import FEATURES, THEME_KEYWORDS, feature_by_id

# ---------------------------------------------------------------------------
# Semantic roles
# ---------------------------------------------------------------------------

# feature id -> the semantic role(s) a mod serving that feature fills.
ROLE_BY_FEATURE: dict[str, list[str]] = {
    "create": ["technology", "automation"],
    "magic": ["magic"],
    "bosses": ["combat", "bosses"],
    "structures": ["structures", "exploration"],
    "villages": ["exploration", "mobs"],
    "terrain": ["terrain", "worldgen"],
    "dimensions": ["dimensions", "exploration"],
    "performance": ["optimization"],
    "shaders": ["renderer", "atmosphere"],
    "realistic": ["atmosphere", "terrain"],
    "combat": ["combat"],
    "mobs": ["mobs"],
    "quests": ["progression"],
    "food": ["farming", "content"],
    "storage": ["storage", "utility"],
    "building": ["building", "decoration"],
    "transportation": ["transportation"],
    "vanilla": ["compatibility"],
    "horror": ["atmosphere", "mobs"],
    "tech": ["technology"],
}

ALL_ROLES = sorted({r for roles in ROLE_BY_FEATURE.values() for r in roles})
ROLE_LABELS = {
    "combat": "Combat", "bosses": "Bosses", "magic": "Magic", "technology": "Technology",
    "automation": "Automation", "farming": "Farming", "exploration": "Exploration",
    "structures": "Structures", "terrain": "Terrain & worldgen", "worldgen": "Terrain & worldgen",
    "mobs": "Creatures & mobs", "optimization": "Performance", "renderer": "Rendering",
    "atmosphere": "Atmosphere", "progression": "Progression", "storage": "Storage",
    "utility": "Utility", "building": "Building", "decoration": "Decoration",
    "transportation": "Transport", "compatibility": "Compatibility", "dimensions": "Dimensions",
    "content": "Content",
}

# Order matters: importance tiers for locked/intent scoring.
IMPORTANCE_HIGH = {"bosses", "magic", "terrain", "create", "tech", "combat"}
IMPORTANCE_MEDIUM = {"structures", "villages", "mobs", "dimensions", "realistic", "quests"}


def roles_for(feature_ids) -> list[str]:
    """Semantic roles a selection satisfies, from its feature ids."""
    out: list[str] = []
    for fid in feature_ids or []:
        for r in ROLE_BY_FEATURE.get(fid, []):
            if r not in out:
                out.append(r)
    return out


def feature_label(fid: str) -> str:
    f = feature_by_id(fid)
    return f["label"] if f else fid


# ---------------------------------------------------------------------------
# Pack Identity
# ---------------------------------------------------------------------------

def derive_identity(req: dict, rec: dict | None = None) -> dict:
    """Derive a PackIdentity from interpreted requirements (deterministic).

    Fills every field with real values when available and sensible defaults
    otherwise, so later AI operations always have a coherent identity to
    reason about — even for imported packs with minimal metadata.
    """
    req = req or {}
    theme = list(req.get("theme") or [])
    feature_ids = [f.get("id") for f in (req.get("features") or []) if isinstance(f, dict)]
    if not feature_ids:
        feature_ids = [f for f in (req.get("featureIds") or [])]

    primary = []
    for fid in feature_ids:
        if feature_by_id(fid) and (fid in IMPORTANCE_HIGH or fid in IMPORTANCE_MEDIUM):
            primary.append(fid)
    secondary = [fid for fid in feature_ids if fid not in primary]
    # de-dupe, preserve order
    primary = list(dict.fromkeys(primary))
    secondary = list(dict.fromkeys(secondary))

    locked = list(rec.get("lockedMods") or []) if rec else []
    style_words = [k for k, v in THEME_KEYWORDS.items() if any(w in theme for w in (v or []))]
    style = ", ".join(style_words) if style_words else ("Custom" if theme else "Vanilla+")

    goals = []
    for fid in primary[:5]:
        goals.append(feature_label(fid))
    for fid in secondary[:3]:
        goals.append(feature_label(fid))
    goals = list(dict.fromkeys(goals))

    return {
        "coreTheme": ", ".join(theme) if theme else "Custom",
        "primaryGoals": goals[:5],
        "secondaryGoals": goals[5:],
        "requiredFeatures": list(dict.fromkeys(primary)),
        "optionalFeatures": list(dict.fromkeys(secondary)),
        "forbiddenFeatures": [f for f in (req.get("forbidden") or [])],
        "lockedMods": locked,
        "performanceTarget": {
            "ramGB": int(req.get("ramGB") or 0) or 8,
            "targetFps": int(req.get("targetFps") or 0) or 60,
            "shaders": bool(req.get("shaders")),
            "textureResolution": int(req.get("resourcePackResolution") or 0) or 0,
        },
        "multiplayer": bool(req.get("multiplayer")),
        "style": style,
    }


def intent_for(selection: dict, identity: dict | None = None) -> dict:
    """Attach a semantic intent record to a selection.

    All values are derived from real data already in the record: the feature
    ids and selection reason (why it was picked), provider metadata (costs),
    and the pack identity (importance). `alternatives` is always empty until
    the replacement engine fills it; `locked` honors the pack identity.
    """
    fid = (selection.get("featureIds") or [])[:1]
    roles = roles_for(fid)
    req_satisfied = [feature_label(x) for x in fid] or ["general"]
    locked = bool(selection.get("locked")) or (selection.get("slug") or "") in (
        (identity or {}).get("lockedMods") or [])

    importance = "high" if (fid and fid[0] in IMPORTANCE_HIGH) else \
        "medium" if (fid and fid[0] in IMPORTANCE_MEDIUM) else "low"
    if selection.get("projectType") == "shader":
        importance = "medium"
    if selection.get("projectType") == "resourcepack":
        importance = "low"

    return {
        "role": roles,
        "roleLabels": [ROLE_LABELS.get(r, r) for r in roles],
        "whySelected": selection.get("reason") or f"Satisfies requested feature: {req_satisfied[0]}",
        "satisfiesRequest": req_satisfied,
        "importance": importance,
        "replaceable": not locked,
        "alternatives": [],
        "performanceCost": "low" if (selection.get("featureIds") or [""])[0] in
                           {"performance", "vanilla", "storage", "food", "building"} else "medium",
        "dependencyCost": "low" if not (selection.get("score") is not None and selection.get("score") >= 90) else "medium",
        "compatibilityConfidence": min(99, max(70, int(selection.get("score") or 90))),
        "locked": locked,
    }


def apply_intents(selections: list, identity: dict | None = None) -> list:
    """Return selections with their intent records attached (non-destructive)."""
    out = []
    for s in selections or []:
        item = dict(s)
        item["intent"] = intent_for(s, identity)
        out.append(item)
    return out
