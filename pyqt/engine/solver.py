"""Dependency + version solver — Python port of src/solver/resolve.ts.

1. Expands required/embedded dependencies recursively from provider data.
2. Picks per-project versions satisfying MC + loader and every range constraint.
3. Backtracks (downgrades dependents) when constraints clash.
4. Never silently downloads "the newest version" — the chosen version always
   satisfies all constraints.
"""
from __future__ import annotations

from typing import Optional

from .core import version_satisfies, minor_version
from .jarmeta import essential_libraries

FEATURE_PRIORITY = {
    "create": 8, "magic": 7, "bosses": 6, "structures": 6, "terrain": 7,
    "performance": 8, "shaders": 6, "dimensions": 5, "villages": 5,
    "realistic": 5, "combat": 5, "mobs": 5, "quests": 4, "food": 3,
    "storage": 4, "building": 4, "transportation": 3, "vanilla": 5,
    "horror": 5, "tech": 4,
}


def _feature_priority(fid: str) -> int:
    return FEATURE_PRIORITY.get(fid, 3)


def _rank_channel(v: dict) -> int:
    return {"release": 0, "beta": 1, "alpha": 2}.get(v.get("releaseChannel"), 2)


def _key(provider: str, project_id: str) -> str:
    return f"{provider}:{project_id}"


def resolve_pack(opts: dict) -> dict:
    """opts: {providers, seeds, minecraftVersion, loader, logger, includeOptional?, maxIterations?}"""
    providers = opts["providers"]
    seeds = opts["seeds"]
    minecraft_version = opts["minecraftVersion"]
    loader = opts["loader"]
    logger = opts.get("logger")
    max_iter = opts.get("maxIterations", 4000)
    provider_by_key = {p.name: p for p in providers}

    nodes: dict = {}
    candidates: dict = {}
    chosen: dict = {}
    constraints: dict = {}
    dependents: dict = {}
    edges: list = []
    issues: list = []
    candidates_fetched = 0
    iterations = 0
    exhausted = False
    excluded = set()

    def ensure_candidates(provider: str, project_id: str, node: dict) -> list:
        nonlocal candidates_fetched
        k = _key(provider, project_id)
        lst = candidates.get(k)
        if lst is None:
            candidates_fetched += 1
            # Non-mod projects (shader packs, resource packs, datapacks) are
            # versioned by Minecraft only — Modrinth shader packs are not
            # loader-tagged, so a loader filter would wrongly return zero
            # versions and fail the seed.
            is_mod = (node or {}).get("project", {}).get("projectType", "mod") == "mod"
            try:
                lst = provider_by_key[provider].get_versions(project_id, {
                    "minecraftVersion": minecraft_version,
                    "loaders": None if (loader == "vanilla" or not is_mod) else [loader],
                }) or []
            except Exception as e:
                issues.append({"kind": "unsatisfiable", "severity": "warning",
                               "message": f"Failed to fetch versions for {node['project']['title']}: {e}",
                               "nodeKeys": [k]})
                lst = []
            lst.sort(key=lambda v: (_rank_channel(v), v.get("datePublished", "")), reverse=False)
            # channel first (release < beta < alpha), then newest
            lst.sort(key=lambda v: (_rank_channel(v), -(_ts(v.get("datePublished")) or 0)))
            candidates[k] = lst
        return lst

    def add_node(provider: str, project_id: str, seed: Optional[dict] = None,
                 source_key: Optional[str] = None) -> Optional[dict]:
        k = _key(provider, project_id)
        node = nodes.get(k)
        if node:
            if seed:
                if seed.get("featureId") not in node["featureIds"]:
                    node["featureIds"].append(seed["featureId"])
                if seed.get("locked"):
                    node["locked"] = True
                if not node.get("reason"):
                    node["reason"] = seed.get("reason")
            return node
        proj = seed["project"] if seed else {
            "provider": provider, "projectId": project_id, "slug": project_id,
            "title": project_id, "description": "", "projectType": "mod",
            "downloads": 0, "follows": 0, "dateCreated": "", "dateModified": "",
            "categories": [], "url": "",
        }
        node = {
            "key": k,
            "project": proj,
            "featureIds": [seed["featureId"]] if seed else [],
            "selected": True,
            "reason": seed.get("reason") if seed else (f"Required by {source_key}" if source_key else None),
            "rankScore": seed.get("score") if seed else None,
            "locked": seed.get("locked") if seed else None,
        }
        nodes[k] = node
        return node

    def pick_for(k: str) -> Optional[dict]:
        lst = candidates.get(k) or []
        cons = constraints.get(k) or []
        for c in lst:
            ok = True
            for cn in cons:
                if cn.get("pinnedVersionId") and c["versionId"] != cn["pinnedVersionId"]:
                    ok = False
                    break
                if cn.get("range") and not version_satisfies(c.get("versionNumber", ""), cn.get("range")):
                    ok = False
                    break
            if ok:
                return c
        return None

    def validate(k: str, v: Optional[dict]) -> bool:
        if not v:
            return False
        gv = v.get("gameVersions") or []
        if gv and minecraft_version not in gv:
            minor = minor_version(minecraft_version)
            if not (minor != minecraft_version and minor in gv):
                return False
        return True

    def add_dependent(frm: str, to: str) -> None:
        lst = dependents.setdefault(to, [])
        if frm not in lst:
            lst.append(frm)

    def _ts(s) -> Optional[float]:
        import time as _t
        try:
            return _t.mktime(_t.strptime(str(s)[:10], "%Y-%m-%d"))
        except Exception:
            return None

    def expand_node(k: str):
        node = nodes.get(k)
        v = chosen.get(k)
        if not node or not v:
            return
        for dep in v.get("dependencies") or []:
            handle_dependency(k, node, dep)

    def handle_dependency(from_key: str, from_node: dict, dep: dict):
        dep_key = _key(from_node["project"]["provider"], dep["projectId"])
        # Project-level loader alias: on Quilt, provider deps referencing the
        # fabric-api BUNDLE project re-target to QSL (which provides the
        # fabric API surface and is the only project with quilt builds).
        if loader == "quilt" and not nodes.get(dep_key):
            try:
                prov = provider_by_key.get(from_node["project"]["provider"])
                proj = prov.get_project(dep["projectId"]) if prov else None
                if proj and proj.get("slug", "").lower() == "fabric-api":
                    qsl = prov.get_project("qsl") if prov else None
                    if qsl:
                        dep_key = _key(qsl["provider"], qsl["projectId"])
            except Exception:
                pass
        if dep.get("kind") == "incompatible":
            edges.append({"from": from_key, "to": dep_key, "kind": "incompatible"})
            existing = nodes.get(dep_key)
            if existing and existing.get("selected"):
                issues.append({
                    "kind": "conflict", "severity": "error",
                    "message": f"{from_node['project']['title']} declares {existing['project']['title']} incompatible",
                    "nodeKeys": [from_key, dep_key],
                })
            return
        if dep.get("kind") == "optional" and not opts.get("includeOptional"):
            exists = nodes.get(dep_key)
            edges.append({"from": from_key, "to": dep_key, "kind": "optional",
                          "versionRange": dep.get("versionRange"), "pinnedVersionId": dep.get("versionId")})
            if exists:
                cons = constraints.setdefault(dep_key, [])
                cons.append({"from": from_key, "range": dep.get("versionRange"),
                             "pinnedVersionId": dep.get("versionId"), "kind": "optional"})
            return
        # required / embedded / optional-included
        dep_node = nodes.get(dep_key)
        if not dep_node:
            created = add_node(from_node["project"]["provider"], dep["projectId"],
                               None, from_node["project"]["title"])
            if not created:
                return
            dep_node = created
            try:
                prov = provider_by_key.get(from_node["project"]["provider"])
                real = prov.get_project(dep["projectId"]) if prov else None
                if real:
                    dep_node["project"] = {**dep_node["project"], **real}
            except Exception:
                pass
            lst = ensure_candidates(dep_node["project"]["provider"],
                                    dep_node["project"]["projectId"], dep_node)
            if not lst:
                dep_node["selected"] = False
                excluded.add(dep_key)
                issues.append({
                    "kind": "unsatisfiable", "severity": "error",
                    "message": f'Dependency "{dep["projectId"]}" required by {from_node["project"]["title"]} has no versions for MC {minecraft_version} / loader {loader}; removed {from_node["project"]["title"]}',
                    "nodeKeys": [from_key, dep_key],
                })
                if from_node.get("selected"):
                    from_node["selected"] = False
                    excluded.add(from_key)
                return
            chosen_dep = pick_for(dep_key) or lst[0]
            chosen[dep_key] = chosen_dep
            dep_node["version"] = chosen_dep
            dep_node["reason"] = f"Required by {from_node['project']['title']} ({from_node['project']['slug']})"
        cons = constraints.setdefault(dep_key, [])
        if not any(c.get("from") == from_key and c.get("range") == dep.get("versionRange") for c in cons):
            cons.append({"from": from_key, "range": dep.get("versionRange"),
                         "pinnedVersionId": dep.get("versionId"), "kind": dep.get("kind", "required")})
        add_dependent(from_key, dep_key)
        if not any(e.get("from") == from_key and e.get("to") == dep_key and e.get("kind") == dep.get("kind") for e in edges):
            edges.append({"from": from_key, "to": dep_key, "kind": dep.get("kind"),
                          "versionRange": dep.get("versionRange"), "pinnedVersionId": dep.get("versionId")})

    def bootstrap_seed(seed: dict, lock: bool) -> Optional[str]:
        k = _key(seed["provider"], seed["projectId"])
        node = add_node(seed["provider"], seed["projectId"], seed)
        if not node:
            return None
        if lock:
            node["locked"] = True
        # A preserved parent selection pins its exact version (candidate edits
        # must not silently drift every preserved mod to a newer build).
        if seed.get("pinnedVersionId"):
            cons = constraints.setdefault(k, [])
            if not any(c.get("pinnedVersionId") == seed["pinnedVersionId"] for c in cons):
                cons.append({"pinnedVersionId": seed["pinnedVersionId"]})
        lst = ensure_candidates(seed["provider"], seed["projectId"], node)
        if not lst:
            issues.append({
                "kind": "unsatisfiable", "severity": "error",
                "message": f'Selected mod "{seed["project"]["title"]}" has no versions for MC {minecraft_version} / loader {loader}',
                "nodeKeys": [k],
            })
            return None
        v = pick_for(k) or lst[0]
        chosen[k] = v
        node["version"] = v
        return k

    def backtrack(target_key: str) -> bool:
        lst = candidates.get(target_key) or []
        cons = constraints.get(target_key) or []
        current = chosen.get(target_key)
        for c in lst:
            if c is current:
                continue
            ok = True
            for cn in cons:
                if cn.get("pinnedVersionId") and c["versionId"] != cn["pinnedVersionId"]:
                    ok = False
                    break
                if cn.get("range") and not version_satisfies(c.get("versionNumber", ""), cn.get("range")):
                    ok = False
                    break
            if ok:
                target = nodes.get(target_key)
                if target and validate(target_key, c):
                    chosen[target_key] = c
                    target["version"] = c
                    return True
        for dk in (dependents.get(target_key) or [])[:6]:
            dlist = candidates.get(dk) or []
            cur = chosen.get(dk)
            for c in dlist:
                if c is cur:
                    continue
                dnode = nodes.get(dk)
                if dnode and validate(dk, c):
                    chosen[dk] = c
                    dnode["version"] = c
                    repick = pick_for(target_key)
                    if repick:
                        tnode = nodes.get(target_key)
                        chosen[target_key] = repick
                        if tnode:
                            tnode["version"] = repick
                        return True
        return False

    def main():
        nonlocal iterations, exhausted
        # Loader-essential libraries
        for ess in essential_libraries(loader):
            try:
                prov = next((p for p in providers if p.available and p.name in ("modrinth", "curseforge")),
                            next((p for p in providers if p.available), None))
                if prov:
                    proj = prov.get_project(ess["slug"])
                    if proj:
                        k = bootstrap_seed({
                            "featureId": "essential", "provider": proj["provider"],
                            "projectId": proj["projectId"], "project": proj,
                            "reason": ess["reason"], "score": 100, "locked": True,
                        }, True)
                        if k and logger:
                            logger.info("resolve", f"Essential library added: {proj['title']} ({proj['slug']}) via {proj['provider']}")
                    elif logger:
                        logger.warn("resolve", f"Essential library not found: {ess['slug']}")
                elif logger:
                    logger.warn("resolve", f"No provider available to resolve essential library {ess['slug']}")
            except Exception as e:
                if logger:
                    logger.warn("resolve", f"Could not add essential library {ess['slug']}: {e}")

        for seed in seeds:
            bootstrap_seed(seed, False)

        # expansion + consistency loop
        for _pass in range(8):
            if exhausted:
                break
            iterations += 1
            if iterations > max_iter:
                exhausted = True
                break
            snapshot = list(nodes.keys())
            for k in snapshot:
                expand_node(k)
            changed = True
            while changed and iterations < max_iter:
                iterations += 1
                changed = False
                for e in edges:
                    target = nodes.get(e["to"])
                    if not target or not target.get("selected"):
                        continue
                    cv = chosen.get(e["to"])
                    ok = True
                    if e.get("pinnedVersionId") and cv and cv["versionId"] != e["pinnedVersionId"]:
                        ok = False
                    if e.get("versionRange") and cv and not version_satisfies(cv.get("versionNumber", ""), e.get("versionRange")):
                        ok = False
                    if ok:
                        continue
                    better = pick_for(e["to"])
                    if better:
                        chosen[e["to"]] = better
                        target["version"] = better
                        changed = True
                        continue
                    saved = backtrack(e["to"])
                    if saved:
                        changed = True

        # cascade: unselect nodes whose required dep was dropped
        cascade_changed = True
        guard = 0
        while cascade_changed and guard < 16:
            cascade_changed = False
            guard += 1
            for e in edges:
                if e["kind"] not in ("required", "embedded"):
                    continue
                frm = nodes.get(e["from"])
                to = nodes.get(e["to"])
                if not frm or not frm.get("selected"):
                    continue
                if not to or not to.get("selected") or e["to"] not in chosen:
                    frm["selected"] = False
                    excluded.add(e["from"])
                    if not any(i["kind"] == "unsatisfiable" and e["from"] in (i.get("nodeKeys") or []) for i in issues):
                        issues.append({
                            "kind": "unsatisfiable", "severity": "error",
                            "message": f"{frm['project']['title']} removed: required dependency {(to or {}).get('project', {}).get('title') or e['to']} could not be satisfied",
                            "nodeKeys": [e["from"], e["to"]],
                        })
                    cascade_changed = True

        # final honesty pass: verify every required/embedded edge holds
        for e in edges:
            if e["kind"] not in ("required", "embedded"):
                continue
            target = nodes.get(e["to"])
            if not target or not target.get("selected"):
                continue
            cv = chosen.get(e["to"])
            ok = cv is not None
            if cv and e.get("pinnedVersionId") and cv["versionId"] != e["pinnedVersionId"]:
                ok = False
            if cv and e.get("versionRange") and not version_satisfies(cv.get("versionNumber", ""), e.get("versionRange")):
                ok = False
            if not ok:
                better = pick_for(e["to"])
                if better:
                    chosen[e["to"]] = better
                    target["version"] = better
                elif not any(i["kind"] == "unsatisfiable" and e["to"] in str(i.get("message", "")) for i in issues):
                    issues.append({
                        "kind": "unsatisfiable", "severity": "error",
                        "message": f"Version constraint on {target['project']['title']} ({target['project']['slug']}) cannot be satisfied; required by {e['from']}",
                        "nodeKeys": [e["from"], e["to"]],
                    })

        # resolve incompatible edges by excluding the lower-value node
        for e in [x for x in edges if x["kind"] == "incompatible"]:
            a = nodes.get(e["from"])
            b = nodes.get(e["to"])
            if not a or not b or not a.get("selected") or not b.get("selected"):
                continue
            keep = _pick_important(a, b, dependents)
            drop = b if keep is a else a
            drop["selected"] = False
            excluded.add(drop["key"])
            for i in issues:
                if i["kind"] == "conflict" and e["from"] in (i.get("nodeKeys") or []) and e["to"] in (i.get("nodeKeys") or []):
                    i["severity"] = "warning"
                    i["message"] = f"{a['project']['title']} is incompatible with {b['project']['title']}; removed {drop['project']['title']} (kept {keep['project']['title']})"

        # dedupe + report
        seen = set()
        final_issues = []
        for i in issues:
            ident = i["kind"] + i["message"]
            if ident in seen:
                continue
            seen.add(ident)
            final_issues.append(i)
        if exhausted:
            final_issues.append({"kind": "unsatisfiable", "severity": "error",
                                 "message": "Version solving hit the iteration budget; constraints could not be fully satisfied."})
        graph = {"nodes": nodes, "edges": edges}
        stats = {
            "projects": len(nodes),
            "deps": len([e for e in edges if e["kind"] in ("required", "embedded")]),
            "candidatesFetched": candidates_fetched,
            "iterations": iterations,
            "excluded": sorted(excluded),
        }
        if logger:
            logger.info("resolve", f"Resolved {len(nodes)} projects ({stats['deps']} required deps) in {iterations} iterations; {len(final_issues)} issue(s)")
        return {"graph": graph, "issues": final_issues, "stats": stats}

    return main()


def _pick_important(a: dict, b: dict, dependents: dict) -> dict:
    def priority(n: dict) -> int:
        return max([0] + [_feature_priority(f) for f in n.get("featureIds") or []])

    def deps(n: dict) -> int:
        return len(dependents.get(n["key"]) or [])

    pa, pb = priority(a), priority(b)
    if pa != pb:
        return a if pa > pb else b
    da, db = deps(a), deps(b)
    if da != db:
        return a if da > db else b
    return a if (a["project"].get("downloads") or 0) >= (b["project"].get("downloads") or 0) else b
