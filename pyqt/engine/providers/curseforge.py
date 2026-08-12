"""CurseForge provider — official CurseForge API (api.curseforge.com/v1).

Python port of src/providers/curseforge.ts. Distribution policy: CF content may
not be bundled into a redistributable archive; this provider never ships jars
directly — it produces manifest references ({projectID, fileID}) which the
CurseForge launcher resolves at install time. Direct downloads are attempted
only when `allowDirectDownloads` is explicitly enabled (single-machine use).
"""
from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from ..core import sanitize_filename
from .http import provider_get

BASE = "https://api.curseforge.com/v1"
GAME_ID = 432

CLASS = {"mod": 6, "resourcepack": 12, "shader": 6552, "datapack": 6945, "modpack": 4471, "world": 17}
TYPE_BY_CLASS = {6: "mod", 12: "resourcepack", 6552: "shader", 6945: "datapack", 4471: "modpack", 17: "world"}
LOADER_TYPE = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
RELATION_KIND = {
    1: "embedded", 2: "optional", 3: "required", 5: "incompatible", 6: "embedded",
}


class CurseForgeScopeError(RuntimeError):
    """The API key authenticated but lacks access to a specific endpoint
    (HTTP 403). Typically a key generated with search-only access groups in
    the CurseForge console — distinct from a missing/invalid key (401) or an
    author-disabled download (empty downloadUrl)."""


def cf_download_headers(url: str) -> Optional[dict]:
    """x-api-key header for CurseForge CDN (edge.forgecdn.net) downloads.

    CurseForge announced API-key auth for direct CDN downloads (2026-06,
    enforcement rolling out 2026-07): sending the key now keeps downloads
    working once enforcement lands and attributes them to this launcher. No
    key configured -> None (current behavior — unauthenticated downloads
    still succeed today)."""
    if "edge.forgecdn.net" not in (url or ""):
        return None
    from .settings import SettingsStore
    key = SettingsStore().curseforge_key()
    return {"x-api-key": key} if key else None


class CurseForgeProvider:
    name = "curseforge"

    def __init__(self, api_key: str, allow_direct_downloads: bool = False):
        self.available = bool(api_key)
        self.unavailable_reason = (
            None if self.available
            else "Missing CurseForge API key. Add one on the Settings page (or set CF_API_KEY)."
        )
        self.key = api_key
        self.allow_direct = allow_direct_downloads

    def _get(self, path: str, use_cache: bool = True) -> Any:
        if not self.key:
            raise RuntimeError("CurseForge API key not configured")
        try:
            return provider_get("curseforge", f"{BASE}{path}",
                                headers={"x-api-key": self.key}, cache=use_cache)
        except Exception as e:  # noqa: BLE001 — classify 403s by the API's own words
            msg = str(e)
            if "403" in msg:
                if any(w in msg.lower() for w in ("missing or invalid", "invalid api key",
                                                  "forbidden", "unauthorized", "api key")):
                    # The API's own body says the KEY is wrong (it never says
                    # "scope") — surface the real reason instead of guessing.
                    raise RuntimeError(
                        "CurseForge rejected the configured API key (HTTP 403: "
                        "API Key missing or invalid). Double-check it on the Settings page.") from e
                raise CurseForgeScopeError(
                    "CurseForge API key authenticated but lacks access to this "
                    "endpoint (HTTP 403) — the key appears search-only. Check its "
                    "access groups / API scopes in the CurseForge console.") from e
            raise

    def _map_mod(self, m: dict) -> dict:
        cats = [c.get("slug") for c in (m.get("categories") or [])]
        ptype = TYPE_BY_CLASS.get(m.get("classId") or 0, "mod")
        logo = m.get("logo") or {}
        gallery = []
        for shot in (m.get("screenshots") or []):
            if shot.get("url") or shot.get("thumbnailUrl"):
                gallery.append({
                    "url": shot.get("url") or shot.get("thumbnailUrl"),
                    "thumbnailUrl": shot.get("thumbnailUrl"),
                    "title": shot.get("title"),
                    "description": shot.get("description"),
                })
        authors = ", ".join(a.get("name", "") for a in (m.get("authors") or []) if a.get("name"))
        links = m.get("links") or {}
        return {
            "provider": "curseforge",
            "projectId": str(m.get("id", "")),
            "slug": m.get("slug", ""),
            "title": m.get("name", ""),
            "description": m.get("summary") or "",
            "projectType": ptype,
            "downloads": m.get("downloadCount") or 0,
            "follows": 0,
            "dateCreated": m.get("dateCreated"),
            "dateModified": m.get("dateModified"),
            "iconUrl": logo.get("thumbnailUrl") or logo.get("url") or None,
            "author": authors or None,
            "clientSide": None,
            "serverSide": None,
            "categories": cats,
            "url": links.get("websiteUrl") or f"https://www.curseforge.com/minecraft/mc-mods/{m.get('slug', '')}",
            "gallery": gallery[:8],
        }

    def search(self, opts: dict) -> list[dict]:
        return self.search_meta(opts)["hits"]

    def search_meta(self, opts: dict) -> dict:
        """Search + CurseForge's real `pagination.totalCount` for the query
        (the full catalog count, not capped by pageSize) — same response, no
        extra request. Returns {"hits": [...], "total": int}.
        """
        qp = {
            "gameId": str(GAME_ID),
            "pageSize": str(max(1, min(50, opts.get("limit", 20)))),
        }
        offset = max(0, int(opts.get("offset", 0) or 0))
        if offset:
            qp["index"] = str(offset)
        types = opts.get("projectType") or "mod"
        if isinstance(types, list):
            types = types[0] if types else "mod"
        cls = CLASS.get(types, CLASS["mod"])
        qp["classId"] = str(cls)
        if opts.get("query"):
            qp["searchFilter"] = opts["query"]
        # Rank by total downloads in both browse AND query mode: the merged
        # catalog (service.search) already re-sorts every source by downloads,
        # so ranking each source the same way keeps the per-provider view and
        # the merged view consistent — and the canonical mod (e.g. JEI) is not
        # buried under fuzzy matches (CurseForge's default relevance sort is
        # noisy). opts["sort"] maps the shared vocabulary: downloads (6),
        # updated (3), name (4); unknown keys default to downloads.
        sort_field = {"downloads": "6", "updated": "3", "name": "4"}
        qp["sortField"] = str(opts.get("sort") and sort_field.get(opts["sort"], "6") or "6")
        qp["sortOrder"] = opts.get("sortOrder", "desc")
        if opts.get("minecraftVersion"):
            qp["gameVersion"] = opts["minecraftVersion"]
        loaders = opts.get("loaders") or []
        if loaders:
            qp["modLoaderType"] = str(LOADER_TYPE.get(loaders[0], ""))
        data = self._get(f"/mods/search?{urlencode(qp)}")
        mods = (data or {}).get("data") or []
        total = int(((data or {}).get("pagination") or {}).get("totalCount") or 0)
        hits = [self._map_mod(m) for m in mods if m.get("isAvailable") is not False]
        return {"hits": hits, "total": total}

    def get_project(self, project_id: str) -> Optional[dict]:
        import urllib.parse
        d = self._get(f"/mods/{urllib.parse.quote(project_id)}")
        return self._map_mod(d["data"]) if d and d.get("data") else None

    def get_versions(self, project_id: str, opts: Optional[dict] = None) -> list[dict]:
        import urllib.parse
        opts = opts or {}
        qp = {"pageSize": "50"}
        if opts.get("minecraftVersion"):
            qp["gameVersion"] = opts["minecraftVersion"]
        loaders = opts.get("loaders") or []
        if loaders:
            qp["modLoaderType"] = str(LOADER_TYPE.get(loaders[0], ""))
        try:
            d = self._get(f"/mods/{urllib.parse.quote(project_id)}/files?{urlencode(qp)}")
            files = (d or {}).get("data") or []
        except CurseForgeScopeError:
            raise  # key lacks endpoint access — surface the real reason
        except Exception:
            files = []
        files.sort(key=lambda f: ((f.get("releaseType") or 9), f.get("fileDate", "")), reverse=False)
        files.sort(key=lambda f: f.get("fileDate", ""), reverse=True)
        # release type first (1=release < 2=beta < 3=alpha)
        files.sort(key=lambda f: (f.get("releaseType") or 9))
        channel = opts.get("releaseChannel", "all")
        out = []
        for f in files:
            if f.get("isAvailable") is False:
                continue
            if opts.get("minecraftVersion") and opts["minecraftVersion"] not in (f.get("gameVersions") or []):
                continue
            if channel != "all":
                t = "release" if f.get("releaseType") == 1 else ("beta" if f.get("releaseType") == 2 else "alpha")
                if t != channel:
                    continue
            out.append(self._map_file(project_id, f))
        return out

    def _map_file(self, project_id: str, f: dict) -> dict:
        sha1 = None
        for h in (f.get("hashes") or []):
            if h.get("algo") == 1:
                sha1 = h.get("value")
                break
        deps = []
        for d in (f.get("dependencies") or []):
            deps.append({
                "kind": RELATION_KIND.get(d.get("relationType"), "required"),
                "projectId": str(d.get("modId", "")),
                "versionId": None,
                "versionRange": None,
            })
        return {
            "provider": "curseforge",
            "projectId": project_id,
            "versionId": str(f.get("id", "")),
            "name": f.get("displayName", ""),
            "versionNumber": f.get("displayName", ""),
            "datePublished": f.get("fileDate"),
            "gameVersions": f.get("gameVersions") or [],
            "loaders": [],
            "releaseChannel": "release" if f.get("releaseType") == 1 else ("beta" if f.get("releaseType") == 2 else "alpha"),
            "files": [{
                "filename": sanitize_filename(f.get("fileName") or f.get("fileNameOnDisk") or f.get("displayName") or "file.jar", "file.jar"),
                "url": f.get("downloadUrl") or "",
                "size": f.get("fileLength") or f.get("fileLengthBytes") or 0,
                "hashes": {"sha1": sha1} if sha1 else {},
                "primary": True,
            }],
            "dependencies": deps,
            "url": f"https://www.curseforge.com/minecraft/mc-mods/{project_id}/files/{f.get('id', '')}",
        }

    def get_dependencies(self, version: dict) -> list[dict]:
        return version.get("dependencies") or []

    def get_download_file(self, version: dict) -> Optional[dict]:
        if not self.allow_direct:
            return None  # policy: manifest reference only
        try:
            d = self._get(
                f"/mods/{version['projectId']}/files/{version['versionId']}/download-url",
                False,  # signed URLs are short-lived
            )
            f = (version.get("files") or [None])[0]
            if not f:
                return None
            raw = d.get("data") if d else None
            download_url = raw if isinstance(raw, str) else (raw or {}).get("downloadUrl")
            if not download_url:
                return None
            return {**f, "url": download_url}
        except CurseForgeScopeError:
            raise  # key lacks endpoint access — surface the real reason
        except Exception:
            return None

    def get_hashes(self, version: dict) -> dict:
        files = version.get("files") or []
        return (files[0] or {}).get("hashes") or {}

    def manifest_reference(self, project_id: str, version: dict) -> Any:
        return {"projectID": int(project_id), "fileID": int(version["versionId"])}
