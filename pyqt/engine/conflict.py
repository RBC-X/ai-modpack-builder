"""Conflict engine — Python port of src/conflict/rules.ts + engine.ts.

Combines provider metadata, local fork rules, duplicate detection,
dependency-version clashes and compatibility memory to find and auto-resolve
conflicts in the dependency graph.
"""
from __future__ import annotations

import math
import re

from .core import version_satisfies
from .rank import normalize_slug

FORK_RULES = [
    {"group": "rendering-optimization", "description": "Duplicate rendering optimization stack (Sodium family).",
     "members": ["sodium", "rubidium", "embeddium", "sodium-extra", "rubidium-extra"],
     "keep": "embeddium", "reason": "Only one renderer-optimization mod may be installed; mixing them causes crashes (Mixin apply errors)."},
    {"group": "shader-loader", "description": "Two shader loader systems detected.",
     "members": ["iris", "oculus", "optifine", "irisshaders"],
     "keep": "iris", "reason": "Iris, Oculus and OptiFine are mutually exclusive shader/rendering systems."},
    {"group": "entity-performance", "description": "Duplicate entity/AI performance mods.",
     "members": ["lithium", "canary", "performant", "ferritecore", "krypton", "c2me", "chunky"],
     "keep": "c2me", "reason": "Lithium (Fabric), Canary (Forge port) and Performant overlap heavily and conflict at runtime."},
    {"group": "server-loop-performance", "description": "Duplicate server-loop optimization (parkNanos spin-wait fix).",
     "members": ["modernfix", "server-snapshot-performance-backports"],
     "keep": "modernfix", "reason": "modernfix and server-snapshot-performance-backports both patch MinecraftServer.managedBlock — together they throw a mixin InvalidInjectionException at bootstrap."},
    {"group": "worldgen-performance", "description": "Overlapping world-generation mods with conflicting goals.",
     "members": ["terra", "terraforged", "terralith", "biomes-o-plenty", "oh-the-biomes-youll-go", "biomesoplenty", "terralith_1.20.1"],
     "keep": "terralith", "reason": "Multiple full worldgen overhauls fight over biome generation; keep one."},
    {"group": "difficulty", "description": "Duplicate difficulty/combat overhaul stacks.",
     "members": ["epic-fight-mod", "better-combat", "parry"],
     "keep": "better-combat", "reason": "Combat overhaul mods replace the same combat code paths."},
]

KNOWN_CRASH_SIGNATURES = [
    {"pattern": re.compile(r"Duplicate\s+mods?", re.I), "label": "duplicate-mod",
     "hint": "The same mod is loaded twice.", "suggestion": "remove the duplicate jar"},
    {"pattern": re.compile(r"InvalidInjectionException[^\n]*merged by", re.I), "label": "duplicate-mixin-target",
     "hint": "Two mods patch the same method; the second injection cannot apply (e.g. modernfix + sspb both fix the server parkNanos loop).",
     "suggestion": "remove one of the two conflicting mods"},
    {"pattern": re.compile(r"MixinApplyError|mixin apply failed|failed to apply mixin", re.I), "label": "mixin-apply",
     "hint": "A mixin could not be applied, usually a renderer/optimization clash.", "suggestion": "remove the conflicting optimization/renderer mod"},
    {"pattern": re.compile(r"NoClassDefFoundError|ClassNotFound", re.I), "label": "class-not-found",
     "hint": "A required class is missing (missing dependency or bad version mix).", "suggestion": "add the missing dependency or change versions"},
    {"pattern": re.compile(r"NoSuchMethodError", re.I), "label": "no-such-method",
     "hint": "Binary incompatibility between a mod and its library.", "suggestion": "align library versions"},
    {"pattern": re.compile(r"Wrongly used or missing dependenc|missing dependency|unmet dependency|mandatory dependenc|requires (any )?version of [^\n]*, which is missing|currently,[^\n]*is not installed|failure message: mod [^\n]* requires", re.I),
     "label": "missing-dependency", "hint": "A required dependency is not installed.", "suggestion": "add the dependency"},
    {"pattern": re.compile(r"ModLoadingException|mod loading has failed", re.I), "label": "mod-loading-failed",
     "hint": "One or more mods failed to load.", "suggestion": "inspect the crash report mod list"},
    {"pattern": re.compile(r"Invalid module name: '[^']+' is not a Java identifier|invalid module name", re.I),
     "label": "invalid-jar-name", "hint": "A mod jar filename derives an invalid Java module name (starts with a digit or a Java keyword like true/class).",
     "suggestion": "remove or rename the offending jar"},
    {"pattern": re.compile(r"java\.lang\.OutOfMemoryError", re.I), "label": "oom",
     "hint": "Not enough memory allocated.", "suggestion": "increase RAM allocation"},
    {"pattern": re.compile(r"UnsupportedClassVersionError", re.I), "label": "java-version",
     "hint": "Mod requires a different Java version.", "suggestion": "switch Java runtime"},
    {"pattern": re.compile(r"mismatched minecraft version", re.I), "label": "mc-mismatch",
     "hint": "A mod targets another Minecraft version.", "suggestion": "re-select versions for the target MC"},
]


def match_crash_signature(text: str):
    for s in KNOWN_CRASH_SIGNATURES:
        if s["pattern"].search(text):
            return {"label": s["label"], "hint": s["hint"], "suggestion": s["suggestion"]}
    return None


def _node_importance(n: dict) -> int:
    prio = {"create": 8, "magic": 7, "terrain": 7, "performance": 8, "bosses": 6,
            "structures": 6, "shaders": 6, "vanilla": 5}
    best = 0
    for fid in n.get("featureIds") or []:
        best = max(best, prio.get(fid, 3))
    return best * 10 + min(10, int(math.log10((n["project"].get("downloads") or 0) + 1)))


def _pick_drop(group: list) -> dict:
    def sort_key(n: dict):
        locked = 1 if n.get("locked") else 0
        return (locked, _node_importance(n))
    return sorted(group, key=sort_key)[0]


def detect_and_resolve_conflicts(graph: dict, opts: dict) -> dict:
    loader = opts["loader"]
    minecraft_version = opts["minecraftVersion"]
    memory = opts.get("memory")
    logger = opts.get("logger")
    auto_resolve = opts.get("autoResolve", True)
    conflicts = []
    removed = []
    nodes = [n for n in graph["nodes"].values() if n.get("selected")]
    by_slug = {}
    by_project_id = {}
    for n in nodes:
        slug = normalize_slug(n["project"].get("slug", ""))
        by_slug.setdefault(slug, []).append(n)
        by_project_id.setdefault(n["project"]["projectId"], []).append(n)

    # 1. Duplicate projects (same slug or same id across providers)
    for slug, group in by_slug.items():
        if len(group) < 2:
            continue
        ids = {n["project"]["projectId"] for n in group}
        if len(ids) < 2:
            continue
        conflict = {"id": f"dup:{slug}", "severity": "error", "type": "duplicate_mod",
                    "description": f'"{group[0]["project"]["title"]}" exists from multiple sources ({", ".join(n["project"]["provider"] for n in group)})',
                    "modKeys": [n["key"] for n in group], "source": "rule", "resolved": False}
        if auto_resolve:
            drop = _pick_drop(group)
            drop["selected"] = False
            removed.append(drop["key"])
            keeper = next(n for n in group if n is not drop)
            conflict["resolution"] = f"Removed {drop['project']['title']} ({drop['project']['provider']}); kept {keeper['project']['title']}"
            conflict["resolved"] = True
            if logger:
                logger.warn("conflict", conflict["description"] + " → " + conflict["resolution"])
        conflicts.append(conflict)

    # 2. Fork rules
    for rule in FORK_RULES:
        members = [normalize_slug(m) for m in rule["members"]]
        present = [n for n in nodes if normalize_slug(n["project"].get("slug", "")) in members or n["project"]["projectId"] in rule["members"]]
        if len(present) < 2:
            continue
        if loader in ("forge", "neoforge"):
            keep_slug = "embeddium" if rule["group"] == "rendering-optimization" else rule["keep"]
        else:
            keep_slug = "iris" if rule["group"] == "shader-loader" else rule["keep"]
        keeper = next((n for n in present if keep_slug in normalize_slug(n["project"].get("slug", "")) or n["project"]["projectId"] == keep_slug), present[0])
        conflict = {"id": f"fork:{rule['group']}", "severity": "error", "type": "fork_conflict",
                    "description": f'{rule["description"]} Detected: {", ".join(n["project"]["title"] for n in present)}.',
                    "modKeys": [n["key"] for n in present], "source": "rule", "resolved": False}
        if auto_resolve:
            for n in present:
                if n is not keeper:
                    n["selected"] = False
                    removed.append(n["key"])
            conflict["resolution"] = f'Removed {", ".join(n["project"]["title"] for n in present if n is not keeper)}. Reason: {rule["reason"]}'
            conflict["resolved"] = True
            if logger:
                logger.warn("conflict", conflict["description"] + " → " + conflict["resolution"])
        conflicts.append(conflict)

    # 3. Jar-metadata incompatible edges
    def _required_by_selected(n):
        """True if a selected node requires this node (required/embedded edge)."""
        for e in graph["edges"]:
            if e.get("kind") not in ("required", "embedded") or e.get("to") != n["key"]:
                continue
            f = graph["nodes"].get(e.get("from"))
            if f and f.get("selected"):
                return True
        return False

    for e in graph["edges"]:
        if e.get("kind") != "incompatible":
            continue
        to = next((n for n in nodes if n["key"] == e["to"]), None)
        frm = next((n for n in nodes if n["key"] == e["from"]), None)
        if not to or not frm:
            continue
        conflict = {"id": f"incompatible:{e['from']}-{e['to']}", "severity": "error",
                    "type": "provider_incompatibility",
                    "description": f'"{frm["project"]["title"]}" is incompatible with "{to["project"]["title"]}" (jar metadata declares conflict).',
                    "modKeys": [e["from"], e["to"]], "source": "jar", "resolved": False}
        if auto_resolve:
            drop = frm if _node_importance(frm) <= _node_importance(to) else to
            # A required dependency of a selected mod must never be dropped:
            # doing so ships a pack that crashes at launch with a missing
            # mandatory dependency (real flagship finding: incendium was
            # required by ibo but dropped as the lower-priority side). Drop
            # the non-required side instead; if both sides are required deps,
            # leave the conflict honest and unresolved.
            frm_req = _required_by_selected(frm)
            to_req = _required_by_selected(to)
            if drop is frm and frm_req and not to_req:
                drop = to
            elif drop is to and to_req and not frm_req:
                drop = frm
            if (drop is frm and frm_req) or (drop is to and to_req):
                conflict["severity"] = "warning"
                conflict["resolution"] = "Both sides are required dependencies — left in place; may conflict at runtime."
            else:
                drop["selected"] = False
                removed.append(drop["key"])
                conflict["resolution"] = f"Removed {drop['project']['title']} (lower-priority side of the declared incompatibility)."
                conflict["resolved"] = True
                if logger:
                    logger.warn("conflict", conflict["description"] + " → " + conflict["resolution"])
        conflicts.append(conflict)

    # 4. Dependency version-range clashes
    incoming = {}
    for e in graph["edges"]:
        if e.get("kind") not in ("required", "embedded"):
            continue
        arr = incoming.setdefault(e["to"], [])
        frm = next((n for n in nodes if n["key"] == e["from"]), None)
        if frm:
            arr.append({"from": frm, "range": e.get("versionRange"), "pinned": e.get("pinnedVersionId")})
    for to, arr in incoming.items():
        if len(arr) < 2:
            continue
        target = next((n for n in nodes if n["key"] == to), None)
        if not target:
            continue
        ranges = [a for a in arr if a.get("range")]
        if len(ranges) < 2:
            continue
        probe = (target.get("version") or {}).get("versionNumber", "0")
        if all(version_satisfies(probe, r["range"]) for r in ranges):
            continue
        desc_parts = []
        for r in ranges:
            desc_parts.append(f"{r['from']['project']['title']} wants {r['range']}")
        conflict = {"id": f"depver:{to}", "severity": "warning", "type": "dependency_version_conflict",
                    "description": f'Dependency "{target["project"]["title"]}" has conflicting version requirements: {"; ".join(desc_parts)}',
                    "modKeys": [to] + [a["from"]["key"] for a in arr], "source": "solver", "resolved": False}
        if auto_resolve:
            drop = sorted(arr, key=lambda a: _node_importance(a["from"]))[0]
            drop["from"]["selected"] = False
            removed.append(drop["from"]["key"])
            conflict["resolution"] = f"Removed {drop['from']['project']['title']} (lowest-priority requester of the conflicting range)"
            conflict["resolved"] = True
            if logger:
                logger.warn("conflict", conflict["description"] + " → " + conflict["resolution"])
        conflicts.append(conflict)

    # 5. Memory-driven warnings
    if memory is not None:
        for n in nodes:
            rec = memory.best_result_for_mod(minecraft_version, loader, n["project"].get("slug", ""), n["project"]["projectId"])
            if rec and rec.get("result") == "FAIL":
                conflicts.append({
                    "id": f"mem:{n['key']}", "severity": "warning", "type": "memory_fail",
                    "description": f'"{n["project"]["title"]}" previously failed for MC {minecraft_version}/{loader} ({rec.get("crashSignature") or "unknown crash"}). Repair used: {rec.get("repair") or "n/a"}',
                    "modKeys": [n["key"]], "source": "memory", "resolved": False,
                })

    if logger:
        logger.ok("conflict", f"{len(conflicts)} conflict(s) detected, {len([c for c in conflicts if c['resolved']])} auto-resolved")
    return {"conflicts": conflicts, "removed": removed}
