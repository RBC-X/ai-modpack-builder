"""Modrinth provider — real Modrinth v2 API (Python port of src/providers/modrinth.ts)."""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from ..core import minor_version, sanitize_filename
from .http import provider_get

BASE = "https://api.modrinth.com/v2"

TYPE_MAP = {
    "mod": "mod", "resourcepack": "resourcepack", "shader": "shader",
    "datapack": "datapack", "modpack": "modpack",
}
MODRINTH_LOADERS = ["forge", "neoforge", "fabric", "quilt"]


def _map_side(s: Optional[str]) -> Optional[str]:
    if s in ("required", "optional", "unsupported"):
        return s
    return None


class ModrinthProvider:
    name = "modrinth"
    available = True

    def _type_filters(self, project_type: Any) -> list[str]:
        types = project_type if isinstance(project_type, list) else [project_type]
        return [f"project_type:{t}" for t in types if t]

    def _build_facets(self, opts: dict) -> str:
        facets: list[list[str]] = []
        t = self._type_filters(opts.get("projectType", "mod"))
        if t:
            facets.append(t)
        if opts.get("minecraftVersion"):
            facets.append([f"versions:{opts['minecraftVersion']}"])
        for l in opts.get("loaders") or []:
            facets.append([f"categories:{l}"])
        cats = list(dict.fromkeys(opts.get("categories") or []))
        if cats:
            facets.append([f"categories:{c}" for c in cats])
        return __import__("json").dumps(facets)

    def search(self, opts: dict) -> list[dict]:
        return self.search_meta(opts)["hits"]

    def search_meta(self, opts: dict) -> dict:
        """Search + the provider's real total-hit count (Modrinth `total_hits`
        from the same response — no extra request).

        Returns {"hits": [...], "total": int}. The engine uses `total` so the
        Discover pager can show "of N results" and only enable Next when a
        real page remains — never guessing from a full page alone.
        """
        params = urlencode({
            "query": opts.get("query", ""),
            "facets": self._build_facets(opts),
            "limit": str(opts.get("limit", 20)),
            "index": opts.get("index", "relevance"),
            "offset": str(opts.get("offset", 0)),
        })
        data = provider_get("modrinth", f"{BASE}/search?{params}")
        total = int((data or {}).get("total_hits") or 0)
        hits = (data or {}).get("hits") or []
        out = []
        for h in hits:
            lic = h.get("license")
            out.append({
                "provider": "modrinth",
                "projectId": h.get("project_id", ""),
                "slug": h.get("slug", ""),
                "title": h.get("title", ""),
                "description": h.get("description", "") or "",
                "projectType": TYPE_MAP.get(h.get("project_type"), "mod"),
                "downloads": h.get("downloads") or 0,
                "follows": h.get("follows") or 0,
                "dateCreated": h.get("date_created"),
                "dateModified": h.get("date_modified"),
                "iconUrl": h.get("icon_url") or None,
                "author": h.get("author"),
                "clientSide": _map_side(h.get("client_side")),
                "serverSide": _map_side(h.get("server_side")),
                "categories": h.get("categories") or [],
                "url": f"https://modrinth.com/{h.get('project_type', 'mod')}/{h.get('slug', '')}",
                "license": lic.get("id") if isinstance(lic, dict) else (lic if isinstance(lic, str) else None),
            })
        return {"hits": out, "total": total}

    def get_project(self, project_id: str) -> Optional[dict]:
        import urllib.parse
        p = provider_get("modrinth", f"{BASE}/project/{urllib.parse.quote(project_id)}")
        if not p or not p.get("id"):
            return None
        lic = p.get("license")
        gallery = []
        for shot in (p.get("gallery") or []):
            if shot.get("url") or shot.get("raw_url"):
                gallery.append({
                    "url": shot.get("raw_url") or shot.get("url"),
                    "thumbnailUrl": shot.get("url"),
                    "title": shot.get("title"),
                    "description": shot.get("description"),
                })
        gallery.sort(key=lambda g: 0 if g.get("featured") else 1)
        return {
            "provider": "modrinth",
            "projectId": p.get("id", ""),
            "slug": p.get("slug", ""),
            "title": p.get("title", ""),
            "description": p.get("description", "") or "",
            "projectType": TYPE_MAP.get(p.get("project_type"), "mod"),
            "downloads": p.get("downloads") or 0,
            "follows": p.get("follows") or 0,
            "dateCreated": p.get("date_created"),
            "dateModified": p.get("date_modified"),
            "iconUrl": p.get("icon_url") or None,
            "author": p.get("author"),
            "clientSide": _map_side(p.get("client_side")),
            "serverSide": _map_side(p.get("server_side")),
            "categories": p.get("categories") or [],
            "url": f"https://modrinth.com/{p.get('project_type', 'mod')}/{p.get('slug', '')}",
            "license": lic.get("id") if isinstance(lic, dict) else None,
            "gallery": gallery[:8],
            "body": p.get("body"),
        }

    def get_versions(self, project_id: str, opts: Optional[dict] = None) -> list[dict]:
        import json as _json
        import urllib.parse
        opts = opts or {}
        qp = {}
        if opts.get("minecraftVersion"):
            qp["game_versions"] = _json.dumps([opts["minecraftVersion"]])
        if opts.get("loaders"):
            qp["loaders"] = _json.dumps(opts["loaders"])
        qs = urlencode(qp)
        url = f"{BASE}/project/{urllib.parse.quote(project_id)}/version" + (f"?{qs}" if qs else "")
        versions = provider_get("modrinth", url)
        lst = versions if isinstance(versions, list) else []
        if opts.get("minecraftVersion"):
            mc = opts["minecraftVersion"]
            lst = [v for v in lst if mc in (v.get("game_versions") or [])]
            # Patch-release fallback: many projects publish only for the minor
            # (QSL ships 11.0.0-alpha.3 for "1.21" and it is what 1.21.1 Quilt
            # packs use). When the exact MC has zero builds, RE-QUERY the API
            # for the parent minor (1.21.1 -> 1.21).
            if not lst:
                minor = minor_version(mc)
                if minor and minor != mc:
                    qp2 = {"game_versions": _json.dumps([minor])}
                    if opts.get("loaders"):
                        qp2["loaders"] = _json.dumps(opts["loaders"])
                    url2 = f"{BASE}/project/{urllib.parse.quote(project_id)}/version?{urlencode(qp2)}"
                    minor_versions = provider_get("modrinth", url2)
                    lst = [v for v in (minor_versions if isinstance(minor_versions, list) else [])
                           if minor in (v.get("game_versions") or [])]
        if opts.get("loaders"):
            loaders = set(opts["loaders"])
            lst = [v for v in lst if any(l in loaders for l in (v.get("loaders") or []))]
        channel = opts.get("releaseChannel", "all")
        if channel != "all":
            lst = [v for v in lst if v.get("version_type") == channel]
        lst.sort(key=lambda v: v.get("date_published", ""), reverse=True)
        return [self._map_version(v) for v in lst]

    def _map_version(self, v: dict) -> dict:
        deps = []
        for d in (v.get("dependencies") or []):
            pid = d.get("project_id") or ""
            if not pid:
                continue
            deps.append({
                "kind": d.get("dependency_type") or "required",
                "projectId": pid,
                "versionId": d.get("version_id") or None,
                "versionRange": d.get("version_range") or None,
            })
        files = []
        for f in (v.get("files") or []):
            files.append({
                "filename": sanitize_filename(f.get("filename") or "", f.get("filename") or "file"),
                "url": f.get("url"),
                "size": f.get("size") or 0,
                "hashes": f.get("hashes") or {},
                "primary": bool(f.get("primary")),
                "fileType": f.get("file_type") or None,
            })
        return {
            "provider": "modrinth",
            "projectId": v.get("project_id", ""),
            "versionId": v.get("id", ""),
            "name": v.get("name", ""),
            "versionNumber": v.get("version_number", ""),
            "datePublished": v.get("date_published"),
            "gameVersions": v.get("game_versions") or [],
            "loaders": v.get("loaders") or [],
            "releaseChannel": v.get("version_type"),
            "files": files,
            "dependencies": deps,
            "url": f"https://modrinth.com/project/{v.get('project_id', '')}/version/{v.get('id', '')}",
        }

    def get_dependencies(self, version: dict) -> list[dict]:
        return version.get("dependencies") or []

    def get_download_file(self, version: dict) -> Optional[dict]:
        files = version.get("files") or []
        for f in files:
            if f.get("primary"):
                return f
        return files[0] if files else None

    def get_hashes(self, version: dict) -> dict:
        files = version.get("files") or []
        f = next((x for x in files if x.get("primary")), files[0] if files else None)
        return (f or {}).get("hashes") or {}

    def manifest_reference(self, project_id: str, version: dict) -> Optional[Any]:
        return None
