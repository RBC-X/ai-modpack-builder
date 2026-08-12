"""Prompt interpreter — plain-English requests → structured requirements.

Python port of src/interpreter/prompt.ts: rule + keyword based, deterministic.
"""
from __future__ import annotations

import re

from .features import FEATURES, THEME_KEYWORDS, PACK_SIZE_MOD_COUNTS, feature_by_id

KNOWN_LOADERS = {"forge": "forge", "neoforge": "neoforge", "fabric": "fabric", "quilt": "quilt"}
KNOWN_MC_VERSIONS = ["1.20.1", "1.21.1", "1.21", "1.20.4", "1.20.2", "1.20.6", "1.19.4",
                     "1.19.2", "1.18.2", "1.17.1", "1.16.5", "1.12.2", "1.21.4", "1.21.5", "1.21.6"]


def interpret(raw_prompt: str) -> dict:
    text = " " + re.sub(r"\s+", " ", raw_prompt.lower()).strip() + " "

    # --- Minecraft version ---
    minecraft_version = "auto"
    unsupported_version = ""
    ver_match = re.search(r"(?:mc|minecraft)?\s*(1\.\d{1,2}(?:\.\d{1,2})?)", text)
    if ver_match:
        cand = ver_match.group(1)
        minecraft_version = cand
        if cand not in KNOWN_MC_VERSIONS:
            unsupported_version = cand

    # --- Loader ---
    loader = "auto"
    for word, l in KNOWN_LOADERS.items():
        if re.search(rf"\b{word}\b", text):
            loader = l
            break

    # --- RAM ---
    ram_gb = 0
    ram_match = re.search(r"(\d{1,3})\s*(?:gb|gigabytes?|ram)", text)
    if ram_match:
        ram_gb = min(64, int(ram_match.group(1)))

    # --- Mod count & pack size ---
    target_mod_count = 0
    count_match = re.search(r"(?:around|about|~|approximately)?\s*(\d{1,4})\s*(?:mods|modpack)", text)
    warnings = []
    if count_match:
        requested_count = int(count_match.group(1))
        target_mod_count = min(200, requested_count)
        if requested_count > target_mod_count:
            warnings.append(f"Requested {requested_count} mods; capped at {target_mod_count} for stability and provider limits")
    pack_size = "medium"
    if "lightweight" in text or "light pack" in text or "small pack" in text or "few mods" in text:
        pack_size = "light"
    elif "massive" in text or "huge" in text or "mega" in text:
        pack_size = "massive"
    elif "large" in text or target_mod_count > 100:
        pack_size = "large"
    elif 0 < target_mod_count <= 40:
        pack_size = "light"
    if target_mod_count > 0:
        pack_size = "light" if target_mod_count <= 40 else "medium" if target_mod_count <= 90 else "large" if target_mod_count <= 160 else "massive"

    # --- Shaders / textures ---
    shaders = "shader" in text
    if "no shaders" in text or "without shaders" in text:
        shaders = False
    shader_quality = None
    if shaders:
        from .shaders import QUALITY_KEYWORDS
        if any(k in text for k in QUALITY_KEYWORDS["cinematic"]):
            shader_quality = "cinematic"
        elif any(k in text for k in QUALITY_KEYWORDS["performance"]):
            shader_quality = "performance"
    res = 0
    res_match = re.search(r"(\d{2,3})x\s*(?:texture|textures|resolution|pack)", text)
    if res_match:
        res = int(res_match.group(1))

    # --- Multiplayer / server ---
    multiplayer = bool(re.search(r"\b(multiplayer|server|play with friends|on a server|co-op|host)\b", text))
    server_pack = bool(re.search(r"server pack|server version|make a server|dedicated server", text))

    # --- Test mode ---
    test_mode = "standard"
    if re.search(r"\binstantly\b|\binstant\b", text):
        test_mode = "instant"
    elif re.search(r"\bdeep\b", text) or re.search(r"thorough|full test", text):
        test_mode = "deep"

    # --- Auto-tune to hardware ---
    auto_tune = bool(re.search(
        r"based on my (?:pc|hardware|specs?)|for my (?:pc|hardware|specs?)|fits? my (?:pc|hardware|pc's specs)|"
        r"my pc can|my computer can|auto[- ]?tune|tune to my (?:pc|hardware)|detect my (?:pc|hardware|specs)|"
        r"use my (?:pc|hardware|specs|system)|what can my pc run", text, re.I))

    # --- Theme ---
    themes = []
    for theme, kws in THEME_KEYWORDS.items():
        if any(k in text for k in kws):
            themes.append(theme)

    # --- Features (negation-aware) ---
    feat_text = re.sub(
        r"^\s*(?:please\s+)?(?:can you\s+)?(?:please\s+)?(?:create|make|build|generate|give me)\s+"
        r"(?:me\s+)?(?:a|an|the|my|me|us|it|one)\s+", " ", text)
    features: list[dict] = []
    negated = set()
    direct = set()
    neg_re = re.compile(r"(?:no|without|less|remove|drop|don't want|do not want)\s+([a-z0-9\- ]{2,24})")
    for m in neg_re.finditer(text):
        phrase = m.group(1).strip()
        for f in FEATURES.values():
            if not f.get("negative") and (
                phrase.startswith(f["label"].lower().split(" ")[0]) or
                any(k in phrase for k in f["keywords"])
            ):
                negated.add(f["id"])
        for theme, kws in THEME_KEYWORDS.items():
            if any(k in phrase for k in kws):
                negated.add("theme:" + theme)
    for f in FEATURES.values():
        if f["id"] == "vanilla":
            continue
        if f["id"] in negated:
            continue
        hit_term = next((k for k in f["keywords"] if k in feat_text), None)
        if hit_term is None and f["label"].lower() in feat_text:
            hit_term = f["label"].lower()
        if hit_term:
            direct.add(f["id"])
            features.append({**f, "sourceTerm": hit_term, "targetCount": f["targetCount"]})
    if "more like vanilla" in text or "vanilla-like" in text or "vanilla feel" in text:
        features.append({**FEATURES["vanilla"], "sourceTerm": "more like vanilla", "targetCount": 1})
    if "horror" in themes and "horror" not in direct:
        features.append({**FEATURES["horror"], "sourceTerm": "horror theme", "targetCount": 2})
    if "fantasy" in themes and "magic" not in direct:
        features.append({**FEATURES["magic"], "sourceTerm": "fantasy theme", "targetCount": 2})
    if "medieval" in themes and "structures" not in direct:
        features.append({**FEATURES["structures"], "sourceTerm": "medieval theme", "targetCount": 2})
    if ("good performance" in text or "performance" in text or "8 gb" in text or (ram_gb > 0 and ram_gb <= 8)) and "performance" not in direct:
        features.append({**FEATURES["performance"], "sourceTerm": "performance request", "targetCount": 3})
    needs_clarification = not features
    if needs_clarification:
        warnings.append("Tell me a theme or feature (for example farming, magic, exploration, or performance) before building")
    _distribute_targets(features, pack_size, target_mod_count)

    # --- Notes ---
    notes = []
    if unsupported_version:
        notes.append(f"Requested Minecraft {unsupported_version}; compatibility is not confirmed and no fallback was substituted")
        warnings.append(f"Minecraft {unsupported_version} is not in the launcher's verified version list")
    elif minecraft_version != "auto":
        notes.append(f"Minecraft version set to {minecraft_version}")
    else:
        notes.append("Minecraft version: auto-detect")
    if loader != "auto":
        notes.append(f"Loader set to {loader}")
    else:
        notes.append("Loader: auto-detect")
    if ram_gb > 0:
        notes.append(f"RAM budget: {ram_gb} GB")
    if target_mod_count > 0:
        notes.append(f"Target mod count: ~{target_mod_count}")
    if negated:
        notes.append(f"Excluded: {', '.join(sorted(negated))}")
    if multiplayer:
        notes.append("Multiplayer requested")
    if server_pack:
        notes.append("Server pack requested")
    if test_mode != "standard":
        notes.append(f"Test mode: {test_mode}")
    if auto_tune:
        notes.append("Auto-tune: pack will be sized to the detected hardware (RAM, pack size, shaders, textures)")

    return {
        "requirements": {
            "theme": themes,
            "minecraftVersion": minecraft_version,
            "loader": loader,
            "targetModCount": target_mod_count,
            "packSize": pack_size,
            "features": features,
            "multiplayer": multiplayer,
            "ramGB": ram_gb,
            "shaders": shaders,
            "shaderQuality": shader_quality,
            "resourcePackResolution": res,
            "performanceMods": "performance" in direct or any("performance" in n for n in notes),
            "serverPack": server_pack,
            "testMode": test_mode,
            "autoTune": auto_tune,
            "notes": notes,
            "warnings": warnings,
            "needsClarification": needs_clarification,
            "confidence": "low" if needs_clarification or unsupported_version else "high",
            "unsupportedMinecraftVersion": unsupported_version,
        }
    }


def _distribute_targets(features: list, size: str, target_mod_count: int) -> None:
    """Weighted distribution of the mod-count goal across features."""
    if not features:
        return
    # Feature defaults are intentional breadth estimates. Do not turn a narrow
    # request such as "farming" into an entire medium-pack (80 mod) quota.
    if target_mod_count <= 0:
        return
    goal = target_mod_count
    scalable = [f for f in features if f["id"] not in ("vanilla", "shaders")]
    if not scalable:
        return
    w_sum = sum(max(1, f["targetCount"]) * f["priority"] for f in scalable)
    cap = max(8, int(math_ceil(goal / len(scalable)) * 2))
    raw = [(goal * (max(1, f["targetCount"]) * f["priority"])) / w_sum for f in scalable]
    targets = [max(1, min(cap, round(x))) for x in raw]
    order = sorted(range(len(scalable)),
                   key=lambda i: max(1, scalable[i]["targetCount"]) * scalable[i]["priority"],
                   reverse=True)
    diff = goal - sum(targets)
    guard = 0
    while diff != 0 and guard < 1000:
        step = 1 if diff > 0 else -1
        idx = next((i for i in order if (step > 0 and targets[i] < cap) or (step < 0 and targets[i] > 1)), None)
        if idx is None:
            break
        targets[idx] += step
        diff -= step
        guard += 1
    for i, f in enumerate(scalable):
        f["targetCount"] = targets[i]


def math_ceil(x: float) -> int:
    import math
    return math.ceil(x)


def loader_from_text(text: str) -> str:
    return interpret(text)["requirements"]["loader"]


__all__ = ["interpret", "loader_from_text", "feature_by_id"]
