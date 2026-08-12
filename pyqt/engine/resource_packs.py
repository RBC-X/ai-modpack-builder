"""Resource-pack selection for AI builds — resolution + theme aware.

Like the shader engine, this is honest: candidate slugs are real Modrinth
resource-pack projects (verified live 2026-08-11) and `choose_resource_pack`
only returns a project that has a real MC-compatible version with a direct
download URL. A 64x+ request is honestly downgraded when the machine can't
run it — an integrated GPU OR low RAM both trigger the downgrade, with the
real reason recorded. CurseForge is a second source when a key is configured.
"""

from __future__ import annotations

from typing import Optional

from .shaders import gpu_tier, _pick_version_file

# Resolution tier -> Modrinth slugs in preference order (all verified live).
RESOLUTION_SLUGS = {
    16: ["bare-bones", "classic-3d"],   # light vanilla-style packs
    32: ["faithful-32x"],               # the canonical 32x
    64: ["faithful-64x"],               # heavy — discrete GPU only
}

# Resolution tier -> CurseForge search terms (second source; only when a CF
# key is configured and Modrinth finds nothing usable).
CF_RESOLUTION_QUERIES = {
    16: ["bare bones", "classic 3d"],
    32: ["faithful 32x"],
    64: ["faithful 64x"],
}


def pick_resource_pack(req: dict, hardware: dict) -> Optional[dict]:
    """Decide the resolution + reason from the request and the machine."""
    res = int(req.get("resourcePackResolution") or 0)
    if res <= 0:
        return None
    hw = hardware.get("effective") or hardware.get("detected") or {}
    tier = gpu_tier(str(hw.get("gpu") or ""))
    ram = int(hw.get("ramGB") or req.get("ramGB") or 8)
    reasons = []
    if res > 64:
        reasons.append(f"capped the requested {res}x down to 64x (larger packs are impractical)")
        res = 64
    if res >= 64 and (tier in ("integrated", "unknown") or ram < 8):
        if tier in ("integrated", "unknown") and ram < 8:
            reasons.append(f"{res}x textures need a discrete GPU and more RAM — using 32x")
        elif tier in ("integrated", "unknown"):
            reasons.append(f"{res}x textures are too heavy for an {tier} GPU — using 32x")
        else:
            reasons.append(f"{res}x textures on {ram} GB RAM is risky — using 32x")
        res = 32
    theme = [t for t in (req.get("theme") or []) if t != "vanilla"]
    if theme:
        reasons.append(f"{', '.join(theme)} theme")
    reasons.append(f"{res}x tier")
    return {"resolution": res, "gpuTier": tier,
            "reason": "; ".join(dict.fromkeys(reasons))}


def _choose_from_curseforge(providers, mc_version: str, resolution: int,
                            logger=None) -> Optional[dict]:
    """Second source: search CurseForge by resource-pack name keywords."""
    for p in (providers or []):
        if p.name != "curseforge" or not getattr(p, "available", False):
            continue
        for query in CF_RESOLUTION_QUERIES.get(resolution, ["faithful 32x"]):
            try:
                hits = p.search({"query": query, "projectType": "resourcepack",
                                 "minecraftVersion": mc_version, "limit": 5}) or []
            except Exception as e:
                if logger:
                    logger.warn("visuals", f"CurseForge search '{query}' unavailable: {e}")
                continue
            for h in hits:
                if h.get("projectType") != "resourcepack":
                    continue
                try:
                    proj = p.get_project(h["projectId"])
                except Exception:
                    proj = None
                if not proj:
                    continue
                picked = _pick_version_file(p, proj, mc_version, logger)
                if picked:
                    return {"provider": "curseforge", "project": proj,
                            "version": picked["version"], "file": picked["file"]}
    return None


def choose_resource_pack(providers, mc_version: str, resolution: int,
                         theme: list = None, logger=None) -> Optional[dict]:
    """Fetch a real resource-pack project + MC-compatible version.

    Returns {provider, project, version, file} or None. Modrinth first;
    CurseForge is a real second source when a key is configured. The returned
    dict names the actual provider that supplied the pick.
    """
    for p in (providers or []):
        if p.name != "modrinth" or not getattr(p, "available", True):
            continue
        slugs = RESOLUTION_SLUGS.get(resolution, RESOLUTION_SLUGS[32])
        for slug in slugs:
            try:
                proj = p.get_project(slug)
            except Exception:
                proj = None
            if not proj or proj.get("projectType") != "resourcepack":
                continue
            picked = _pick_version_file(p, proj, mc_version, logger)
            if picked:
                return {"provider": "modrinth", "project": proj,
                        "version": picked["version"], "file": picked["file"]}
    return _choose_from_curseforge(providers, mc_version, resolution, logger)
