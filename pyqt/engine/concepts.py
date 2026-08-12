"""Starter concepts and Surprise Me.

Curated, *editable templates* (not final packs): each concept is a coherent
creative brief — theme, gameplay loop, progression, exploration, combat,
visuals, atmosphere, mod categories, performance target and pack size — that
seeds the AI Builder. The user can read the brief, edit the prompt, and only
then build.

**Surprise Me** is not a random mod picker. It combines a theme concept, a
gameplay loop, a progression style, an exploration style and a combat
philosophy into one coherent creative concept, deterministically seeded so
it is testable and re-rollable.
"""
from __future__ import annotations

import random

from .features import FEATURES, feature_by_id

# ---------------------------------------------------------------------------
# The brief fields both curated concepts and Surprise Me produce.
# ---------------------------------------------------------------------------

BRIEF_FIELDS = (
    "id", "title", "icon", "tagline", "theme", "gameplayLoop", "progression",
    "exploration", "combat", "visuals", "atmosphere", "features", "packSize",
    "ramGB", "shaders", "multiplayer",
)


def _feat_labels(features: list) -> list:
    out = []
    for fid in features:
        f = feature_by_id(fid)
        if f:
            out.append(f["label"])
    return out


def build_prompt(concept: dict) -> str:
    """Compose the creative brief into a single builder prompt.

    The wording deliberately uses the interpreter's vocabulary (theme words,
    feature keywords, "N GB RAM", pack-size words) so the deterministic
    interpreter recovers the intended requirements instead of guessing.
    """
    theme = ", ".join(concept.get("theme") or ["vanilla"])
    parts = [f"Build me a {theme} Minecraft modpack."]
    if concept.get("gameplayLoop"):
        parts.append(concept["gameplayLoop"])
    if concept.get("progression"):
        parts.append("Progression: " + concept["progression"])
    if concept.get("exploration"):
        parts.append("Exploration: " + concept["exploration"])
    if concept.get("combat"):
        parts.append("Combat: " + concept["combat"])
    if concept.get("visuals"):
        parts.append("Visuals: " + concept["visuals"])
    if concept.get("atmosphere"):
        parts.append("Atmosphere: " + concept["atmosphere"])
    feats = _feat_labels(concept.get("features") or [])
    if feats:
        parts.append("Core features: " + ", ".join(feats) + ".")
    flags = []
    size = concept.get("packSize") or "medium"
    ram = concept.get("ramGB") or 8
    flags.append(f"make it a {size} pack with {ram} GB RAM")
    if concept.get("shaders"):
        flags.append("include shaders")
    else:
        flags.append("no shaders")
    if concept.get("multiplayer"):
        flags.append("multiplayer-friendly")
    parts.append("Please " + ", ".join(flags) + ", with good performance.")
    return " ".join(parts)


def _concept(
    id: str, title: str, icon: str, tagline: str, theme: list, features: list,
    loop: str, progression: str, exploration: str, combat: str,
    visuals: str, atmosphere: str, pack_size: str = "medium",
    ram_gb: int = 8, shaders: bool = True, multiplayer: bool = True,
) -> dict:
    c = {
        "id": id, "title": title, "icon": icon, "tagline": tagline,
        "theme": theme, "gameplayLoop": loop, "progression": progression,
        "exploration": exploration, "combat": combat, "visuals": visuals,
        "atmosphere": atmosphere, "features": features, "packSize": pack_size,
        "ramGB": ram_gb, "shaders": shaders, "multiplayer": multiplayer,
    }
    c["prompt"] = build_prompt(c)
    return c


# ---------------------------------------------------------------------------
# Curated starter experiences (editable templates, spec §8)
# ---------------------------------------------------------------------------

STARTER_CONCEPTS: list[dict] = [
    _concept(
        "medieval-kingdom", "Medieval Kingdom", "swords",
        "Castles, armies, villages, combat, magic, bosses.",
        ["medieval", "fantasy", "rpg"],
        ["combat", "bosses", "structures", "villages", "magic", "terrain", "quests"],
        "Explore a hand-built kingdom: raid dungeons and ruins, defend villages, "
        "and carve out a stronghold of your own.",
        "Leveling through quests and boss trophies — each region unlocks harder "
        "dungeons and better gear.",
        "Structured: villages, keeps and story dungeons dot a varied terrain.",
        "Weighted melee with parries, shields and armor — boss fights that "
        "punish unplanned charges.",
        "Atmospheric shaders, medieval texture pack, realistic terrain.",
        "Torchlit and heroic: weathered castles, misty forests, distant battle horns.",
        pack_size="large", ram_gb=8, shaders=True, multiplayer=True,
    ),
    _concept(
        "nuclear-survival", "Nuclear Survival", "shieldalert",
        "Ruins, radiation, scarcity, technology, difficult exploration.",
        ["realistic", "survival"],
        ["tech", "structures", "terrain", "mobs", "quests", "food", "performance"],
        "Scavenge irradiated ruins by day, fortify against the night's creatures, "
        "and slowly rebuild technology from scrap.",
        "Survival milestones: secure food and water, then restore power, then "
        "repair the machines that let you push deeper.",
        "Dangerous: radiation zones, collapsed cities and buried bunkers reward "
        "careful, equipped exploration.",
        "Desperate and defensive — most fights are ones to avoid or win cheaply.",
        "Gritty textures, muted palette, weather and night that genuinely hide threats.",
        "Eerie stillness punctuated by wind, groaning structures and distant howls.",
        pack_size="medium", ram_gb=6, shaders=False, multiplayer=True,
    ),
    _concept(
        "space-civilization", "Space Civilization", "rocket",
        "Technology, planets, machines, exploration, automation.",
        ["sci_fi"],
        ["tech", "create", "dimensions", "transportation", "storage", "quests", "mobs"],
        "Automate a growing base, then explore and colonize new dimensions as "
        "your machines make it possible.",
        "Technology tree through quests: from coal power to automated factories "
        "and off-world travel.",
        "Expansive: connected base-building in your home dimension, alien biomes beyond.",
        "Optional — the real enemy is logistics; creatures guard valuable sites.",
        "Clean sci-fi textures, neon accents, polished machinery.",
        "Cold and precise: humming reactors, airlock hiss, vast silent horizons.",
        pack_size="large", ram_gb=10, shaders=True, multiplayer=True,
    ),
    _concept(
        "true-horror", "True Horror", "moon",
        "Darkness, psychological tension, dangerous creatures, survival.",
        ["horror", "realistic"],
        ["horror", "mobs", "structures", "terrain", "quests"],
        "Survive the night. Learn what the dark hides, gather light and wards, "
        "and slowly reclaim the places it took.",
        "Fear-gated: each night survived reveals a new threat; quests unravel the "
        "source of the darkness.",
        "Claustrophobic: twisted forests, sunken ruins and pitch-black caves.",
        "Avoidance over heroics — engage only when cornered, and never at night.",
        "Dark shaders, fog, and sound design that sells every shadow.",
        "Oppressive: silence, then movement where there should be none.",
        pack_size="medium", ram_gb=6, shaders=True, multiplayer=False,
    ),
    _concept(
        "industrial-revolution", "Industrial Revolution", "package",
        "Factories, engineering, logistics, automation.",
        ["steampunk", "sci_fi"],
        ["create", "tech", "transportation", "storage", "building", "quests"],
        "Build a workshop into a factory: automate every stage of production and "
        "connect it all with rails.",
        "Engineering milestones: hand tools → steam power → automated assembly — "
        "each step a quest chain.",
        "Focused: a growing industrial zone around your base, with ruins to "
        "salvage for parts.",
        "Light — your machines do the fighting; creatures menace your rail lines.",
        "Brass and iron textures, warm workshop light, animated machinery.",
        "Busy and purposeful: steam, ticking clocks, moving gears everywhere.",
        pack_size="large", ram_gb=8, shaders=True, multiplayer=True,
    ),
    _concept(
        "cozy-adventure", "Cozy Adventure", "coffee",
        "Farming, cooking, villages, exploration, building.",
        ["cozy", "adventure", "vanilla"],
        ["food", "villages", "building", "mobs", "storage", "quests", "vanilla"],
        "Tend a homestead, trade with villagers, and go on gentle expeditions "
        "to discover new recipes and places.",
        "Slow progression: improve crops and cooking, earn villagers' trust, "
        "and unlock travel to new regions.",
        "Leisurely: rolling hills, forests, seaside villages — nothing is hostile "
        "by design.",
        "Playful and fair — creatures are mostly background color.",
        "Soft shaders, warm textures, bright cheerful palette.",
        "Sunny, relaxed, full of birdsong and market bustle.",
        pack_size="medium", ram_gb=6, shaders=True, multiplayer=True,
    ),
]

CONCEPT_BY_ID = {c["id"]: c for c in STARTER_CONCEPTS}


# ---------------------------------------------------------------------------
# Surprise Me — a coherent creative concept, not a random mod list.
# ---------------------------------------------------------------------------

_THEME_POOL = [
    {
        "theme": ["medieval", "fantasy"], "features": ["combat", "bosses", "magic", "structures", "terrain"],
        "atmosphere": "A world of crumbling keeps and buried magic, where every ruin has a story.",
        "visuals": "Atmospheric shaders, medieval textures, dramatic terrain.",
        "seed": "frozen steampunk survival where abandoned factories are buried beneath glaciers",
    },
    {
        "theme": ["sci_fi", "steampunk"], "features": ["create", "tech", "transportation", "storage"],
        "atmosphere": "Cold machinery and clockwork wonder — progress measured in moving parts.",
        "visuals": "Brass-and-neon textures, polished mechanical animation.",
        "seed": "dark medieval kingdom exploration with forbidden magic and roaming bosses",
    },
    {
        "theme": ["horror", "realistic"], "features": ["horror", "mobs", "structures", "quests"],
        "atmosphere": "The quiet places are the dangerous ones; darkness is a resource you manage.",
        "visuals": "Low-light fog, deep shadows, a palette that hides what moves.",
        "seed": "cozy farming civilization where exploration gradually unlocks industrial technology",
    },
    {
        "theme": ["cozy", "adventure", "vanilla"], "features": ["food", "villages", "building", "mobs", "storage"],
        "atmosphere": "Sunlit fields, friendly villages and gentle discovery in every direction.",
        "visuals": "Soft light, warm textures, a cheerful, readable palette.",
        "seed": "a drowned city where the sea level slowly falls and unlocks each district",
    },
    {
        "theme": ["rpg", "adventure"], "features": ["quests", "bosses", "structures", "combat", "magic"],
        "atmosphere": "A living world that responds to your legend — reputation opens doors.",
        "visuals": "Epic scale: massive dungeons, distinct biomes, cinematic shaders.",
        "seed": "a desert caravan line where each oasis hides a different lost civilization",
    },
    {
        "theme": ["steampunk", "sci_fi"], "features": ["create", "tech", "transportation", "building", "quests"],
        "atmosphere": "Steam and static — an industrial frontier where every workshop is a kingdom.",
        "visuals": "Warm workshop light against cold machine steel.",
        "seed": "an arctic research station whose machinery keeps the cold at bay",
    },
]

_LOOPS = [
    "The core loop is explore, gather, build, and survive: each expedition funds the next upgrade.",
    "The loop is survive the night, then venture further each day with what you learned.",
    "The loop is automate one more stage of production, then push into territory that needs it.",
    "The loop is master one discipline (farming, building, or exploration), then unlock the next.",
    "The loop is descend into dungeons for relics, bring them home, and build around their powers.",
    "The loop is establish a forward camp, secure it, and expand the safe area outward.",
]

_PROGRESSIONS = [
    "Progression runs through quests and achievements, with each milestone unlocking a new mod family.",
    "Progression is milestone-based: early survival tools give way to specialized equipment as you complete goals.",
    "Progression ties to exploration — new biomes and structures are the gate to better gear.",
    "Progression is crafting-driven: each tier of the pack's core mod chain unlocks the next.",
    "Progression blends combat and crafting: boss kills drop recipes that open new builds.",
    "Progression is settlement-based: improve your base, attract villagers, and expand into new systems.",
]

_EXPLORATIONS = [
    "Exploration is structured: hand-placed-style structures, dungeons and points of interest reward curiosity.",
    "Exploration is risky and rewarding: hostile biomes hold the best loot.",
    "Exploration is expansive: big biomes, new dimensions and long journeys between discoveries.",
    "Exploration is gradual: the map opens up as your equipment and base allow.",
    "Exploration is vertical: deep caves, floating islands and tall structures to climb.",
    "Exploration is cooperative: landmarks and shared waypoints make wandering together worthwhile.",
]

_COMBATS = [
    "Combat is weighty and tactical: better gear and positioning matter more than spam.",
    "Combat is boss-centered: regular creatures are manageable, epic bosses demand preparation.",
    "Combat is defensive: fortification and planning beat open fights whenever possible.",
    "Combat is a pressure valve: occasional danger punctuates mostly peaceful play.",
    "Combat is fast and dangerous: creatures hit hard, so mobility and awareness win.",
    "Combat scales with the world: each region's creatures are a difficulty gate.",
]

_MISSIONS = [
    "Keep the world coherent: every mod should serve the theme rather than just add content.",
    "Prefer packs that feel hand-tuned for the concept over generic mod soup.",
    "Keep the load realistic for the target RAM — nothing that cannot actually run.",
    "Preserve the atmosphere above all: the feel of the world matters more than any single mod.",
]


def _size_for_ram(ram_gb: int) -> str:
    if ram_gb < 8:
        return "light"
    if ram_gb < 16:
        return "medium"
    if ram_gb < 32:
        return "large"
    return "massive"


def surprise_me(seed: object = None, hardware: dict | None = None) -> dict:
    """Generate one coherent, deterministic creative concept.

    `seed` controls the roll (same seed → same concept). When hardware is
    supplied the pack size and RAM target are sized to the machine, and the
    shader flag honors low-RAM systems.
    """
    rng = random.Random(seed)
    hw = hardware or {}
    ram_gb = int(hw.get("ramGB") or 0)
    if not ram_gb:
        ram_gb = rng.choice([6, 8, 10, 12])
    shaders = ram_gb >= 8
    size = _size_for_ram(ram_gb)

    base = rng.choice(_THEME_POOL)
    theme = list(base["theme"])
    features = list(base["features"])
    # Small chance to swap in a curveball feature that still fits the brief.
    curveballs = {
        "horror": "mobs", "create": "performance", "magic": "bosses",
        "tech": "storage", "villages": "food", "terrain": "dimensions",
    }
    if rng.random() < 0.35:
        for fid in features:
            if fid in curveballs:
                alt = curveballs[fid]
                if alt not in features:
                    features.append(alt)
                break

    concept = {
        "id": "surprise",
        "title": "Surprise Me",
        "icon": "sparkles",
        "tagline": "A fresh, coherent creative concept — roll it until you like it.",
        "theme": theme,
        "gameplayLoop": rng.choice(_LOOPS),
        "progression": rng.choice(_PROGRESSIONS),
        "exploration": rng.choice(_EXPLORATIONS),
        "combat": rng.choice(_COMBATS),
        "visuals": base["visuals"],
        "atmosphere": base["atmosphere"],
        "features": features,
        "packSize": size,
        "ramGB": ram_gb,
        "shaders": shaders,
        "multiplayer": True,
        "mission": rng.choice(_MISSIONS),
        "seedConcept": base["seed"],
    }
    concept["prompt"] = build_prompt(concept)
    return concept


def brief_lines(concept: dict) -> list[tuple[str, str]]:
    """Human-readable brief rows for the concept editor (label → value)."""
    rows = []
    if concept.get("theme"):
        rows.append(("Theme", ", ".join(concept["theme"]).title()))
    if concept.get("gameplayLoop"):
        rows.append(("Gameplay loop", concept["gameplayLoop"]))
    if concept.get("progression"):
        rows.append(("Progression", concept["progression"]))
    if concept.get("exploration"):
        rows.append(("Exploration", concept["exploration"]))
    if concept.get("combat"):
        rows.append(("Combat", concept["combat"]))
    if concept.get("visuals"):
        rows.append(("Visuals", concept["visuals"]))
    if concept.get("atmosphere"):
        rows.append(("Atmosphere", concept["atmosphere"]))
    feats = _feat_labels(concept.get("features") or [])
    if feats:
        rows.append(("Mod categories", ", ".join(feats)))
    flags = [f"{concept.get('packSize', 'medium')} pack", f"{concept.get('ramGB', 8)} GB RAM"]
    flags.append("shaders" if concept.get("shaders") else "no shaders")
    if concept.get("multiplayer"):
        flags.append("multiplayer")
    rows.append(("Target", ", ".join(flags)))
    return rows


__all__ = [
    "STARTER_CONCEPTS", "CONCEPT_BY_ID", "BRIEF_FIELDS", "build_prompt",
    "brief_lines", "surprise_me",
]
