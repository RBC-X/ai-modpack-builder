"""Post-download dependency reconciliation — Python port of src/solver/reconcile.ts.

Reads each downloaded jar's own metadata and adds any missing required
dependency to the graph + downloads dir, running to a fixpoint. Deps already
selected are range-checked against jar-declared constraints and re-picked.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .core import download_to_file, version_satisfies, compare_versions, sanitize_filename
from .descresearch import research_description
from .providers.curseforge import cf_download_headers
from .jarmeta import (read_jar_metadata, provided_mod_ids, map_jar_dep_id,
                      norm_id as _norm_id)

MODID_SLUG_FALLBACKS = {
    "forgeconfigapiport": "forge-config-api-port",
    # mod ids that differ wildly from their Modrinth slug (mna -> Mana and Artifice)
    "mna": "mana-and-artifice",
}

# Common suffixes glued onto mod ids ("connectormod", "brutalbosses", "twilightforest").
# When a search for the raw id fails, we strip these and search the stem + word,
# which matches Modrinth's tokenized search ("connector mod", "brutal bosses").
SPLIT_SUFFIXES = [
    "mod", "mods", "api", "lib", "core", "coremod", "loader", "library", "craft",
    "boss", "bosses", "forest", "dungeons", "structures", "spells", "magic",
    "world", "biome", "biomes", "dimension", "dimensions", "terrain", "village",
    "villages", "mob", "mobs", "weapon", "weapons", "armor", "armour", "tools",
    "food", "blocks", "furniture", "decor", "decoration", "portals", "quest",
    "quests", "spell", "network", "client", "server", "compat", "addition",
    "extensions", "patch", "fix", "enhancement", "realistic", "medieval", "fantasy",
    "creatures", "entity", "entities", "guis", "hud", "map", "maps", "renderer",
    "shaders", "textures", "resourcepacks", "config", "configs", "utility",
    "optimization", "performance", "backpack", "backpacks", "inventory", "storage",
    "wands", "spellbook", "spellbooks", "artifice", "mana", "aether", "aurora",
    "palace", "relic", "relics", "gems", "crystals", "plants", "trees", "crops",
    "animals", "mounts", "pets", "races", "classes", "skills", "levels", "stats",
    "enchant", "enchantments", "potions", "effects", "status", "effectsmod",
]


def _token_contains(text: str, m: str) -> bool:
    if not m:
        return False
    return re.search(rf"(^|[^a-z0-9]){re.escape(m)}([^a-z0-9]|$)", text) is not None


def norm_id(id_: str) -> str:
    return _norm_id(id_)


def loose_resolve_project(provider, id_: str, opts: Optional[dict] = None) -> Optional[dict]:
    """Resolve a project when a direct getProject lookup fails (crash hints and
    jar metadata often carry the mod id, not the slug). Mod ids commonly use
    underscores where slugs use hyphens (irons_lib -> irons-lib), so search
    variants are tried when the raw id finds nothing."""
    opts = opts or {}
    m = norm_id(id_)

    # Direct slug lookup first — cheapest and most reliable when the id IS the slug.
    direct = None
    try:
        direct = provider.get_project(id_)
    except Exception:
        direct = None
    if direct:
        return direct

    # Static fallbacks for well-known mod-id -> slug mismatches.
    fb = MODID_SLUG_FALLBACKS.get(m)
    if fb:
        try:
            direct = provider.get_project(fb)
        except Exception:
            direct = None
        if direct:
            return direct

    queries = [(id_, m)]
    if "_" in id_:
        queries.append((id_.replace("_", "-"), m))
        queries.append((id_.replace("_", " "), m))
        queries.append((id_.replace("_", ""), m))
    if "-" in id_:
        queries.append((id_.replace("-", " "), m))
    # Concatenated ids: try splitting before a known suffix so Modrinth's
    # tokenized search can match ("connector mod", "brutal bosses"). The stem
    # query only counts on an exact slug match (Sinytra Connector's slug is
    # "connector" while its mod id is "connectormod").
    if m and len(m) >= 7 and "_" not in id_ and "-" not in id_:
        for suf in SPLIT_SUFFIXES:
            if m.endswith(suf) and len(m) > len(suf) + 1:
                stem = m[: -len(suf)]
                queries.append((f"{stem} {suf}", stem))
                queries.append((stem, stem))
    for q, match_key in queries:
        hits = []
        try:
            hits = provider.search({
                "query": q, "projectType": "mod",
                "minecraftVersion": opts.get("minecraftVersion"),
                "loaders": opts.get("loaders"),
                "limit": 12,
            }) or []
        except Exception:
            hits = []
        if not m or len(m) < 5:
            # Short ids: only accept an exact slug match to avoid grabbing a random addon.
            for h in hits:
                if norm_id(h.get("slug", "")) == norm_id(id_):
                    return h
            continue
        # Pass 1: exact normalized slug match — must win over substring/title hits.
        # (e.g. "twilightforest" must resolve to twilight-forest, not to an addon
        # whose title merely contains "twilight forest").
        for h in hits:
            if norm_id(h.get("slug", "")) == match_key:
                return h
        if match_key != m:
            # Stem-derived query: only an exact slug match to the stem counts —
            # substring matches against a short stem would grab unrelated mods.
            continue
        # Pass 2: slug containment (still slug-derived, so more reliable than titles).
        for h in hits:
            if m in norm_id(h.get("slug", "")):
                return h
        # Pass 3: title containment, prefer the shortest slug that still contains the id.
        best = None
        for h in hits:
            if m in norm_id(h.get("title", "")):
                if best is None or len(norm_id(h.get("slug", ""))) < len(norm_id(best.get("slug", ""))):
                    best = h
        if best is not None:
            return best
    return None


def _download_version(version: dict, project: dict, downloads_dir) -> Optional[str]:
    files = version.get("files") or []
    f = next((x for x in files if x.get("primary")), files[0] if files else None)
    if not f or not f.get("url"):
        return None
    name = sanitize_filename(f"{project['slug']}-{version['versionNumber']}.jar", "mod.jar")
    dest = Path(downloads_dir) / name
    try:
        if not dest.exists():
            download_to_file(f["url"], dest,
                             max_bytes=max((f.get("size") or 0) * 2 + 1024 * 1024, 5 * 1024 ** 2),
                             expected_sha1=(f.get("hashes") or {}).get("sha1"),
                             timeout_ms=300000,
                             headers=cf_download_headers(f["url"]))
        return str(dest)
    except Exception:
        return None


def reconcile_jar_dependencies(opts: dict) -> dict:
    """opts: {graph, providers, minecraftVersion, loader, logger, fileByKey,
    downloadsDir, maxNew?}"""
    graph = opts["graph"]
    providers = opts["providers"]
    minecraft_version = opts["minecraftVersion"]
    loader = opts["loader"]
    logger = opts.get("logger")
    file_by_key = opts["fileByKey"]
    downloads_dir = opts["downloadsDir"]
    max_new = opts.get("maxNew", 60)

    result = {"addedKeys": [], "addedEdges": [], "issues": [], "extraJars": [],
              "extraFileByKey": {}, "changed": [], "droppedKeys": []}
    nodes = graph["nodes"]
    provider_by_key = {p.name: p for p in providers}
    provider = provider_by_key.get("modrinth") or (providers[0] if providers else None)

    provided_id_to_key: dict = {}

    def refresh_provided_index():
        provided_id_to_key.clear()
        for key, jar_path in file_by_key.items():
            node = nodes.get(key)
            if not node or not node.get("selected"):
                continue
            if not Path(jar_path).exists():
                continue
            try:
                for pid in provided_mod_ids(jar_path):
                    n = norm_id(pid)
                    if n and n not in provided_id_to_key:
                        provided_id_to_key[n] = key
            except Exception:
                pass

    refresh_provided_index()

    scanned_keys = set()
    by_slug = {}
    for n in nodes.values():
        if n["project"].get("slug"):
            by_slug[n["project"]["slug"].lower()] = n
        by_slug[n["project"]["projectId"].lower()] = n

    def is_bundle_submodule_range(raw_id: str, mapped: str) -> bool:
        i = str(raw_id).lower().strip()
        if mapped == "fabric-api":
            return i != "fabric" and i != "fabric-api" and i.startswith("fabric-")
        if mapped == "qsl":
            return i.startswith("qsl-")
        return False

    def importance(node: dict) -> int:
        lock = 1e12 if (node.get("locked") or "essential" in (node.get("featureIds") or [])) else 0
        return lock + (node["project"].get("downloads") or 0)

    def is_essential(node: dict) -> bool:
        return bool(node.get("locked")) or "essential" in (node.get("featureIds") or [])

    def find_existing(mapped: str, raw_id: str, dep_id: str, from_node: dict):
        by_key = by_slug.get(mapped.lower()) or by_slug.get(raw_id.lower())
        if by_key and by_key.get("selected"):
            return {"node": by_key, "viaProvided": False}
        provided_key = provided_id_to_key.get(norm_id(mapped))
        if provided_key:
            n = nodes.get(provided_key)
            if not n or not n.get("selected"):
                return None
            own_norm = f"{norm_id(n['project'].get('slug', ''))}|{norm_id(n['project'].get('projectId', ''))}"
            want_norm = norm_id(mapped) or norm_id(raw_id)
            return {"node": n, "viaProvided": want_norm not in own_norm}
        m = norm_id(mapped)
        if not m:
            return None
        loose = None
        for n in nodes.values():
            if not n.get("selected"):
                continue
            slug = norm_id(n["project"].get("slug", ""))
            title = norm_id(n["project"].get("title", ""))
            if slug == m or title == m:
                loose = n
                break
            if len(m) >= 5 and _token_contains(title, m):
                loose = n
                break
            raw_title = n["project"].get("title", "")
            if f"({dep_id})" in raw_title or raw_title.startswith(f"({dep_id}"):
                loose = n
                break
        if loose:
            return {"node": loose, "viaProvided": False}
        return None

    added = 0
    for _pass in range(4):
        wanted: dict = {}
        range_fixes: list = []
        desc_key = set()

        for node_key, jar_path in file_by_key.items():
            node = nodes.get(node_key)
            if not node or not node.get("selected"):
                continue
            if not Path(jar_path).exists():
                continue
            if node_key in scanned_keys:
                continue
            scanned_keys.add(node_key)
            meta = None
            try:
                meta = read_jar_metadata(jar_path)
            except Exception:
                meta = None
            if meta and meta.get("breaks"):
                for brk in meta["breaks"]:
                    mapped = map_jar_dep_id(brk.get("id", ""), loader)
                    if not mapped:
                        continue
                    existing = find_existing(mapped, brk.get("id", ""), brk.get("id", ""), node)
                    if existing:
                        if not any(e["from"] == node_key and e["to"] == existing["node"]["key"] and e["kind"] == "incompatible" for e in graph["edges"]):
                            graph["edges"].append({"from": node_key, "to": existing["node"]["key"], "kind": "incompatible"})
                            if logger:
                                logger.warn("reconcile", f"Incompatibility: {node['project']['title']} declares conflict with {existing['node']['project']['title']} (jar metadata)")
            if not meta or (not meta.get("depends") and not meta.get("breaks")):
                desc_key.add(node_key)
                continue
            for dep in meta.get("depends") or []:
                raw_id = dep.get("id", "")
                mapped = map_jar_dep_id(raw_id, loader)
                if not mapped:
                    continue
                if dep.get("unless"):
                    unless_mapped = map_jar_dep_id(dep["unless"], loader)
                    unless_norm = norm_id(unless_mapped or dep["unless"])
                    satisfied_by_slug = any(
                        n.get("selected") and norm_id(n["project"].get("slug", "")) == unless_norm
                        for n in nodes.values())
                    satisfied_by_provided = unless_norm in provided_id_to_key
                    if satisfied_by_slug or satisfied_by_provided:
                        continue
                existing = find_existing(mapped, raw_id, dep.get("id", ""), node)
                if existing:
                    if not existing["viaProvided"] and not is_bundle_submodule_range(raw_id, mapped):
                        cv = (existing["node"].get("version") or {}).get("versionNumber")
                        if dep.get("versionRange") and cv and not version_satisfies(cv, dep["versionRange"]):
                            range_fixes.append({"id": mapped, "depKey": existing["node"]["key"],
                                                "range": dep["versionRange"], "fromKey": node_key,
                                                "fromTitle": node["project"]["title"]})
                    continue
                prev = wanted.get(mapped)
                if not prev:
                    wanted[mapped] = {"fromKey": node_key, "fromTitle": node["project"]["title"],
                                      "range": dep.get("versionRange")}
                elif dep.get("versionRange") and not prev.get("range"):
                    prev["range"] = dep["versionRange"]

        for n in nodes.values():
            if not n.get("selected") or n["project"].get("projectType") != "mod":
                continue
            if n["key"] not in scanned_keys and n["key"] not in desc_key:
                desc_key.add(n["key"])

        # Description research for nodes whose jar metadata provided nothing.
        for node_key in desc_key:
            node = nodes.get(node_key)
            if not node or not node.get("selected"):
                continue
            scanned_keys.add(node_key)
            provider_p = provider_by_key.get("modrinth") or (providers[0] if providers else None)
            if not provider_p:
                continue
            body = node["project"].get("body")
            if not body:
                try:
                    proj = provider_p.get_project(node["project"]["projectId"])
                    body = (proj or {}).get("body") or ""
                except Exception:
                    body = ""
            if not body:
                continue
            for hint in research_description(body):
                for cand in hint["candidates"]:
                    mapped = map_jar_dep_id(cand, loader)
                    if not mapped:
                        continue
                    if find_existing(mapped, cand, cand, node):
                        continue
                    if is_bundle_submodule_range(cand, mapped):
                        continue
                    if mapped not in wanted:
                        wanted[mapped] = {"fromKey": node_key,
                                          "fromTitle": f"{node['project']['title']} (description)"}

        if not wanted and not range_fixes:
            break

        # Resolve each missing dep on its provider.
        pass_added = 0
        for id_, req in wanted.items():
            if added >= max_new:
                result["issues"].append({"kind": "unsatisfied", "severity": "warning",
                                         "message": f"Reconciliation budget reached; {id_} (required by {req['fromTitle']}) left unresolved"})
                continue
            if not provider:
                continue
            project = None
            try:
                project = provider.get_project(id_)
            except Exception:
                project = None
            if not project:
                project = loose_resolve_project(provider, id_, {
                    "minecraftVersion": minecraft_version,
                    "loaders": None if loader == "vanilla" else [loader],
                })
            if not project:
                fallback = MODID_SLUG_FALLBACKS.get(norm_id(id_))
                if fallback:
                    try:
                        project = provider.get_project(fallback)
                    except Exception:
                        project = None
            if not project:
                result["issues"].append({"kind": "unsatisfied", "severity": "warning",
                                         "message": f'Jar-required dependency "{id_}" (required by {req["fromTitle"]}) could not be found on {provider.name}'})
                continue
            versions = []
            try:
                versions = provider.get_versions(project["projectId"], {
                    "minecraftVersion": minecraft_version,
                    "loaders": None if loader == "vanilla" else [loader],
                }) or []
            except Exception:
                versions = []
            version = None
            if req.get("range"):
                version = next((v for v in versions if version_satisfies(v.get("versionNumber", ""), req["range"])), versions[0] if versions else None)
            else:
                version = versions[0] if versions else None
            if not version:
                result["issues"].append({"kind": "unsatisfiable", "severity": "error",
                                         "message": f'Jar-required dependency "{project["title"]}" has no versions for MC {minecraft_version} / loader {loader}; {req["fromTitle"]} may fail at launch'})
                continue
            dl = _download_version(version, project, downloads_dir)
            if not dl:
                result["issues"].append({"kind": "unsatisfied", "severity": "warning",
                                         "message": f'Jar-required dependency "{project["title"]}" has no direct download; may need manual install'})
                continue
            key = f"{project['provider']}:{project['projectId']}"
            if key in nodes:
                existing = nodes[key]
                by_slug[project["slug"].lower()] = existing
                # A selected mod hard-requires this jar; a deselected node
                # (e.g. dropped by the conflict engine) would ship a pack that
                # crashes at launch with a missing mandatory dependency.
                # Re-select it so the required dep is actually installed.
                if not existing.get("selected") and not existing.get("locked"):
                    existing["selected"] = True
                    existing["featureIds"] = list(dict.fromkeys(
                        (existing.get("featureIds") or []) + ["dependency"]))
                    result["addedKeys"].append(key)
                    if logger:
                        logger.ok("reconcile", f"Re-selected jar-required dependency {project['title']} (required by {req['fromTitle']})")
                continue
            node = {
                "key": key, "project": project, "version": version,
                "featureIds": ["dependency"], "selected": True,
                "reason": f"Required by {req['fromTitle']} (declared in its jar metadata)",
                "locked": False,
            }
            nodes[key] = node
            by_slug[project["slug"].lower()] = node
            by_slug[project["projectId"].lower()] = node
            result["addedKeys"].append(key)
            result["addedEdges"].append({"from": req["fromKey"], "to": key, "kind": "required",
                                         "versionRange": req.get("range")})
            result["extraFileByKey"][key] = dl
            file_by_key[key] = dl
            result["extraJars"].append({
                "slug": project["slug"], "path": dl,
                "clientSide": project.get("clientSide"), "serverSide": project.get("serverSide"),
                "featureIds": ["dependency"],
            })
            added += 1
            pass_added += 1
            if logger:
                logger.ok("reconcile", f"Added jar-required dependency {project['title']} {version['versionNumber']} (required by {req['fromTitle']})")

        # Enforce jar-declared ranges on already-selected nodes.
        for fix in range_fixes:
            dep_node = nodes.get(fix["depKey"])
            if not dep_node or not dep_node.get("selected"):
                continue
            current = (dep_node.get("version") or {}).get("versionNumber")
            if not current or version_satisfies(current, fix["range"]):
                continue
            if not provider:
                continue
            versions = []
            try:
                versions = provider.get_versions(dep_node["project"]["projectId"], {
                    "minecraftVersion": minecraft_version,
                    "loaders": None if loader == "vanilla" else [loader],
                }) or []
            except Exception:
                versions = []
            satisfying = [v for v in versions if version_satisfies(v.get("versionNumber", ""), fix["range"])]
            best = satisfying[0] if satisfying else None
            if not best:
                dependent = nodes.get(fix["fromKey"])
                drop_dependent = dependent and not dependent.get("locked") and not is_essential(dep_node) and importance(dep_node) >= importance(dependent)
                if drop_dependent and dependent:
                    dependent["selected"] = False
                    result["droppedKeys"].append(dependent["key"])
                    result["issues"].append({
                        "kind": "conflict", "severity": "warning",
                        "message": f'"{dependent["project"]["title"]}" pins "{dep_node["project"]["title"]}" at {fix["range"]} which no {minecraft_version}/{loader} version satisfies; dropped the lower-priority dependent',
                        "nodeKeys": [dependent["key"], dep_node["key"]],
                    })
                    if logger:
                        logger.warn("reconcile", f"Version conflict: {dependent['project']['title']} requires {dep_node['project']['title']} {fix['range']} (unavailable) — dropped {dependent['project']['title']}")
                else:
                    result["issues"].append({
                        "kind": "conflict", "severity": "error",
                        "message": f'"{fix["fromTitle"]}" requires "{dep_node["project"]["title"]}" {fix["range"]} but no {minecraft_version}/{loader} version satisfies it; the pack may fail at launch',
                        "nodeKeys": [fix["depKey"]],
                    })
                    if logger:
                        logger.warn("reconcile", f"Version conflict: {fix['fromTitle']} requires {dep_node['project']['title']} {fix['range']} (no satisfying version)")
                continue
            if best.get("versionId") == (dep_node.get("version") or {}).get("versionId"):
                continue
            cmpv = compare_versions(best.get("versionNumber", ""), current)
            downgrade = cmpv < 0
            if downgrade:
                dependent = nodes.get(fix["fromKey"])
                drop_dependent = dependent and not dependent.get("locked") and not is_essential(dep_node) and importance(dep_node) > importance(dependent)
                if drop_dependent and dependent:
                    dependent["selected"] = False
                    result["droppedKeys"].append(dependent["key"])
                    result["issues"].append({
                        "kind": "conflict", "severity": "warning",
                        "message": f'"{dependent["project"]["title"]}" pins "{dep_node["project"]["title"]}" at {fix["range"]}; kept newer {dep_node["project"]["title"]} {current} and dropped the dependent',
                        "nodeKeys": [dependent["key"], dep_node["key"]],
                    })
                    if logger:
                        logger.warn("reconcile", f"Version conflict: {dependent['project']['title']} pins {dep_node['project']['title']} {fix['range']} — kept {current}, dropped {dependent['project']['title']}")
                    continue
            dl = _download_version(best, dep_node["project"], downloads_dir)
            if not dl:
                result["issues"].append({"kind": "unsatisfied", "severity": "warning",
                                         "message": f"Cannot download {dep_node['project']['title']} {best['versionNumber']} to satisfy {fix['fromTitle']}'s pin"})
                continue
            frm = current
            dep_node["version"] = best
            file_by_key[dep_node["key"]] = dl
            result["extraFileByKey"][dep_node["key"]] = dl
            result["changed"].append({"key": dep_node["key"], "fromVersion": frm,
                                      "toVersion": best["versionNumber"],
                                      "reason": f"{fix['fromTitle']} requires {fix['range']}"})
            if logger:
                logger.ok("reconcile", f"Re-picked {dep_node['project']['title']} {frm} → {best['versionNumber']} ({fix['fromTitle']} requires {fix['range']})")

        if pass_added == 0:
            break
        refresh_provided_index()

    return result
