"""AI change planning — deterministic, non-mutating.

Turns a conversational request ("add more bosses", "make it run faster",
"remove technology") into a *plan* the user approves before anything is
built: the interpreted intent, the concrete mod-level changes it implies,
which features must stay, and a projected impact (mods, dependencies, RAM,
confidence, risk). Planning never touches the pack; applying is a separate
transactional step.
"""
from __future__ import annotations

from .features import FEATURES, feature_by_id
from .identity import derive_identity, roles_for
from .interpreter import interpret
from .hardware import performance_estimate

# Requests that map directly to a feature catalog entry.
FEATURE_VERBS = {
    "add": ["bosses", "magic", "structures", "villages", "terrain", "dimensions",
            "mobs", "quests", "food", "storage", "building", "transportation",
            "horror", "tech", "create", "combat", "realistic", "performance", "vanilla"],
    "remove": ["bosses", "magic", "structures", "villages", "terrain", "dimensions",
               "mobs", "quests", "food", "storage", "building", "transportation",
               "horror", "tech", "create", "combat", "realistic", "vanilla"],
    "shader": ["shaders"],
}

ROLE_ALIASES = {
    "boss": "bosses", "spell": "magic", "dungeon": "structures", "village": "villages",
    "biome": "terrain", "world gen": "terrain", "creature": "mobs", "animal": "mobs",
    "monster": "mobs", "farm": "food", "crop": "food", "storage": "storage",
    "backpack": "storage", "build": "building", "furniture": "building",
    "train": "transportation", "vehicle": "transportation", "scary": "horror",
    "creepy": "horror", "dark": "horror", "tech": "tech", "machine": "tech",
    "automation": "create", "contraption": "create", "quest": "quests",
    "dimension": "dimensions", "fps": "performance", "optimize": "performance",
    "faster": "performance", "lag": "performance", "shader": "shaders",
}


def _feature_mentions(text: str) -> list[str]:
    """Feature ids explicitly mentioned in the request (keyword + alias match)."""
    found: list[str] = []
    for fid, f in FEATURES.items():
        if any(k in text for k in f.get("keywords", [])):
            if fid not in found:
                found.append(fid)
    for alias, fid in ROLE_ALIASES.items():
        if re_search(alias, text) and fid not in found:
            found.append(fid)
    return found


def re_search(needle: str, text: str) -> bool:
    import re
    return re.search(rf"\b{re.escape(needle)}\b", text) is not None


def _verb(text: str) -> str:
    if any(re_search(w, text) for w in
           ("remove", "drop", "get rid", "delete", "without", "no more", "too many")):
        return "remove"
    if any(re_search(w, text) for w in ("change", "swap", "replace")):
        return "change"
    return "add"


def plan_change(rec: dict, prompt: str, hardware: dict | None = None) -> dict:
    """Produce a non-mutating change plan for a conversational request."""
    req = rec.get("requirements") or {}
    identity = rec.get("identity") or derive_identity(req, rec)
    selections = rec.get("selections") or []
    existing_features = set()
    for s in selections:
        existing_features.update(s.get("featureIds") or [])
    existing_roles = set(roles_for(list(existing_features)))

    text = (" " + str(prompt or "").lower() + " ").replace("  ", " ")
    interp = interpret(prompt or "")
    interp_req = interp["requirements"]
    mentioned = _feature_mentions(text)
    verb = _verb(text)

    # What the user asked, mapped to concrete pack changes.
    additions: list[str] = []
    removals: list[str] = []
    shader_change = False
    ram_gb = 0
    for fid in mentioned:
        if fid == "shaders":
            if verb == "remove" or any(re_search(w, text) for w in
                                        ("hate", "no shader", "without shader")):
                removals.append("shaders")
            else:
                shader_change = True
            continue
        if verb == "remove":
            removals.append(fid)
        else:
            additions.append(fid)
    # Feature requested via the interpreter but not yet present.
    for f in interp_req.get("features") or []:
        fid = f.get("id") if isinstance(f, dict) else f
        if fid and fid not in existing_features and fid not in additions:
            if fid in ("shaders",):
                shader_change = True
            else:
                additions.append(fid)
    ram_gb = int(interp_req.get("ramGB") or 0)

    # Never plan removal of a locked feature or a user-locked mod.
    locked = set(identity.get("lockedMods") or [])
    for fid in list(removals):
        for s in selections:
            if s.get("slug") in locked and fid in (s.get("featureIds") or []):
                removals.remove(fid)
                break

    additions = list(dict.fromkeys(additions))
    removals = list(dict.fromkeys(removals))
    mods_added = 0
    mods_removed = 0
    for fid in additions:
        f = feature_by_id(fid)
        mods_added += int((f or {}).get("targetCount") or 1)
    for fid in removals:
        mods_removed += sum(1 for s in selections if fid in (s.get("featureIds") or []))
    deps_estimate = int(mods_added * 0.5)

    # Projected memory using the real performance estimator when possible.
    current_ram = int(req.get("ramGB") or (identity.get("performanceTarget") or {}).get("ramGB") or 8)
    target_ram = ram_gb or current_ram
    perf = performance_estimate(hardware or {}, target_ram, mod_count=mods_added,
                                shaders=bool(req.get("shaders")))
    est_ram = round(float(perf.get("estimatedRamGB") or 0), 1)

    risk = "low"
    changed = len(additions) + len(removals) + (1 if shader_change else 0)
    if verb == "remove" and removals:
        risk = "medium"  # removing a feature can cascade dependencies
    if shader_change:
        risk = "medium"
    if len(removals) >= 3 or changed >= 8:
        risk = "high"

    return {
        "prompt": prompt,
        "interpretation": {
            "verb": verb,
            "addFeatures": additions,
            "removeFeatures": removals,
            "shaderChange": shader_change,
            "ramGB": ram_gb,
            "addLabels": [feature_label(f) for f in additions],
            "removeLabels": [feature_label(f) for f in removals],
        },
        "changes": {
            "modsAdded": mods_added, "modsRemoved": mods_removed,
            "dependenciesEstimated": deps_estimate,
            "shaderChanged": shader_change,
        },
        "impact": {
            "estimatedRamGB": est_ram,
            "ramFrom": current_ram, "ramTo": target_ram,
            "confidence": 96 if not shader_change and not removals else 88,
            "risk": risk,
        },
        "preserved": {
            "coreTheme": identity.get("coreTheme"),
            "lockedMods": list(locked),
            "roles": [r for r in identity.get("primaryGoals") or []],
        },
        "nonMutating": True,
    }


def feature_label(fid: str) -> str:
    f = feature_by_id(fid)
    return f["label"] if f else fid
