"""Feature catalog — Python port of src/selector/features.ts."""

PACK_SIZE_MOD_COUNTS = {"light": 40, "medium": 80, "large": 130, "massive": 200, "custom": 80}

FEATURES: dict = {
    "create": {"id": "create", "label": "Create / automation", "priority": 8, "keywords": ["create", "mechanical", "automation", "contraptions"], "categoryTags": ["technology"], "targetCount": 3},
    "magic": {"id": "magic", "label": "Magic & spells", "priority": 7, "keywords": ["magic", "spells", "wizardry", "arcane"], "categoryTags": ["magic"], "targetCount": 3},
    "bosses": {"id": "bosses", "label": "Bosses & combat", "priority": 6, "keywords": ["bosses", "boss", "epic boss"], "categoryTags": ["adventure", "combat"], "targetCount": 3},
    "structures": {"id": "structures", "label": "Structures & dungeons", "priority": 6, "keywords": ["structures", "dungeons", "ruins", "towers"], "categoryTags": ["adventure"], "targetCount": 3},
    "villages": {"id": "villages", "label": "Better villages & NPCs", "priority": 5, "keywords": ["village", "villages", "villager", "npcs"], "categoryTags": ["adventure", "mobs"], "targetCount": 2},
    "terrain": {"id": "terrain", "label": "Improved terrain generation", "priority": 7, "keywords": ["terrain generation", "world generation", "biomes", "caves", "terrain"], "categoryTags": ["worldgen"], "targetCount": 3},
    "dimensions": {"id": "dimensions", "label": "New dimensions", "priority": 5, "keywords": ["dimension", "dimensions", "new world"], "categoryTags": ["adventure"], "targetCount": 2},
    "performance": {"id": "performance", "label": "Performance & optimization", "priority": 8, "keywords": ["performance", "optimization", "fps boost", "lag"], "categoryTags": ["optimization"], "targetCount": 3},
    "shaders": {"id": "shaders", "label": "Shaders", "priority": 6, "keywords": ["shader", "shaders", "ray tracing"], "categoryTags": [], "targetCount": 1, "sourceTerm": "shaders"},
    "realistic": {"id": "realistic", "label": "Realism & immersion", "priority": 5, "keywords": ["realistic", "immersion", "physics", "weather"], "categoryTags": ["adventure", "game-mechanics"], "targetCount": 2},
    "combat": {"id": "combat", "label": "Combat & weapons", "priority": 5, "keywords": ["combat", "weapons", "swords", "armor"], "categoryTags": ["combat", "equipment"], "targetCount": 2},
    "mobs": {"id": "mobs", "label": "More mobs & creatures", "priority": 5, "keywords": ["mobs", "creatures", "animals", "monsters"], "categoryTags": ["mobs"], "targetCount": 3},
    "quests": {"id": "quests", "label": "Quests & progression", "priority": 4, "keywords": ["quests", "questing", "advancements"], "categoryTags": ["adventure"], "targetCount": 1},
    "food": {"id": "food", "label": "Food & farming", "priority": 3, "keywords": ["food", "cooking", "farming", "agriculture", "crops"], "categoryTags": ["food"], "targetCount": 1},
    "storage": {"id": "storage", "label": "Storage & organization", "priority": 4, "keywords": ["storage", "backpacks", "crates"], "categoryTags": ["storage", "utility"], "targetCount": 1},
    "building": {"id": "building", "label": "Building & decoration", "priority": 4, "keywords": ["building", "decoration", "furniture", "blocks"], "categoryTags": ["building", "decoration"], "targetCount": 2},
    "transportation": {"id": "transportation", "label": "Transport", "priority": 3, "keywords": ["trains", "ships", "airships", "vehicles", "mounts"], "categoryTags": ["transportation"], "targetCount": 1},
    "vanilla": {"id": "vanilla", "label": "Vanilla-style feel", "priority": 5, "keywords": ["vanilla", "vanilla plus", "vanilla tweaks"], "categoryTags": [], "targetCount": 1},
    "horror": {"id": "horror", "label": "Scary / horror", "priority": 5, "keywords": ["horror", "scary", "creepy", "dark", "blood"], "categoryTags": ["adventure", "mobs"], "targetCount": 2},
    "tech": {"id": "tech", "label": "Technology", "priority": 4, "keywords": ["technology", "tech", "industrial", "machines"], "categoryTags": ["technology"], "targetCount": 2},
}

THEME_KEYWORDS: dict = {
    "medieval": ["medieval", "knight", "castle", "rpg"],
    "fantasy": ["fantasy", "magic", "mythical", "elven"],
    "rpg": ["rpg", "role playing", "classes", "leveling"],
    "sci_fi": ["sci-fi", "space", "futuristic", "alien"],
    "modern": ["modern", "urban", "city"],
    "steampunk": ["steampunk", "steam", "clockwork"],
    "cyberpunk": ["cyberpunk", "cyber", "neon"],
    "horror": ["horror", "scary", "creepy", "fear"],
    "vanilla": ["vanilla", "vanilla-like", "vanilla plus"],
    "realistic": ["realistic", "survival", "hardcore"],
    "adventure": ["adventure", "exploration", "journey"],
    "cozy": ["cozy", "chill", "relaxing", "cozy"],
}


def feature_by_id(fid: str) -> dict:
    return FEATURES.get(fid)


def all_features() -> list:
    return list(FEATURES.values())
