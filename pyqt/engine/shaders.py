"""GPU-aware shader presets — picks a real shader PACK for AI builds.

Three presets map the user's machine + request to a shader pack:

- performance  -> lightweight packs that run on integrated / low-end GPUs
- balanced     -> the community-standard look that runs on mid-range discrete
- cinematic    -> heavy packs for high-end GPUs

The request's OWN shader intent ("light shaders" vs "cinematic") is honored
when the machine can run it, and honestly downgraded when it cannot. Every
Modrinth slug below was verified live against the Modrinth API (2026-08-11);
CurseForge is searched by keyword as a second source when a key is configured.
`choose_shader` only returns a project that has a real MC-compatible version
with a direct download URL — nothing is hardcoded beyond the candidate slugs,
and nothing is faked if a provider is down or misconfigured.
"""

from __future__ import annotations

import re
from typing import Optional

# Preset -> candidate Modrinth slugs in preference order (all verified live).
PRESET_SLUGS = {
    "performance": ["makeup-ultra-fast-shaders", "nostalgia-shader"],
    "balanced": ["complementary-reimagined", "solas-shader"],
    "cinematic": ["bsl-shaders", "photon-shader", "complementary-unbound"],
}

# Preset -> CurseForge search terms (second source; used only when Modrinth
# finds nothing AND a CF key is configured). Keywords are shader-pack names so
# CF search returns actual packs, not mods tagged "shader".
CF_PRESET_QUERIES = {
    "performance": ["makeup ultra fast", "chocapic13"],
    "balanced": ["complementary reimagined", "sildurs"],
    "cinematic": ["bsl", "photon", "complementary unbound"],
}

TIER_LABELS = {
    "integrated": "integrated GPU — lightest possible shader",
    "discrete-mid": "mid-range discrete GPU — balanced shader",
    "discrete-high": "high-end GPU — cinematic shader",
    "unknown": "GPU unknown — conservative balanced shader",
}

# Shader intent words in the request (interpreted by the prompt interpreter).
QUALITY_KEYWORDS = {
    "performance": ["light shader", "light shaders", "fast shaders", "low-end",
                     "performance shaders", "not too heavy shaders"],
    "cinematic": ["cinematic", "ray tracing", "ray-traced", "path tracing",
                   "ultra shaders", "beautiful shaders", "pretty shaders"],
}


def gpu_tier(gpu: str) -> str:
    """Classify a GPU string into integrated / discrete-mid / discrete-high.

    Heuristic and honest: "Radeon(TM) Graphics" with no model number is an
    iGPU; "Radeon RX 6600" is discrete; RTX 30-series is mid while RTX
    40/50-series is high (generation, not model number, decides).
    """
    g = (gpu or "").lower()
    if not g or "unknown" in g:
        return "unknown"
    if "radeon" in g:
        m = re.search(r"radeon(?:tm)?\s*(?:rx\s*)?(\d{3,4})", g)
        if m:
            n = int(m.group(1))
            return "discrete-high" if n >= 7000 else "discrete-mid"
        # No model number: "AMD Radeon(TM) Graphics" / "Radeon Vega" iGPU,
        # unless it names a discrete product (RX Vega, Radeon VII).
        if "vega" in g or "vii" in g:
            return "discrete-mid"
        return "integrated"
    if any(m in g for m in ("intel", "uhd", "hd graphics", "iris xe",
                            "ryzen", "integrated")):
        return "integrated"
    m = re.search(r"rtx\s*(\d{3,4})", g)
    if m:
        return "discrete-high" if int(m.group(1)) >= 4000 else "discrete-mid"
    if re.search(r"gtx\s*\d{3,4}|quadro|arc\s*[ab]?\s*\d{2,}", g):
        return "discrete-mid"
    if re.search(r"(gtx|rtx|quadro|radeon|arc|geforce)\b", g):
        return "discrete-mid"
    return "discrete-mid"  # unknown discrete card: conservative middle


def pick_shader_preset(req: dict, hardware: dict, requested: Optional[str] = None) -> dict:
    """Choose a preset from the machine + request.

    `requested` ("performance"/"balanced"/"cinematic") comes from the prompt's
    own shader intent or an explicit user override (Pack Detail). It can pull
    LIGHTER than the hardware default, but never heavier than the machine can
    actually sustain — an honest downgrade with the reason recorded. Always
    returns a preset + reason; never raises.
    """
    hw = hardware.get("effective") or hardware.get("detected") or {}
    gpu = str(hw.get("gpu") or "")
    tier = gpu_tier(gpu)
    ram = int(req.get("ramGB") or hw.get("ramGB") or 8)
    fps = int(hw.get("targetFps") or 60)

    preset = {"integrated": "performance", "unknown": "balanced",
              "discrete-mid": "balanced", "discrete-high": "cinematic"}.get(tier, "balanced")
    reasons = [TIER_LABELS[tier]]

    if requested and requested != preset:
        if requested == "performance":
            preset = "performance"
            reasons.append("light shaders requested")
        elif requested == "balanced":
            if tier == "integrated":
                preset = "performance"
                reasons.append("balanced shaders requested but an integrated GPU can't sustain them")
            else:
                preset = "balanced"
                reasons.append("balanced shaders requested")
        elif requested == "cinematic":
            if tier == "integrated":
                preset = "performance"
                reasons.append("cinematic shaders requested but an integrated GPU can't run them")
            elif ram < 12:
                preset = "balanced"
                reasons.append(f"cinematic shaders requested but {ram} GB RAM is tight — using balanced")
            else:
                preset = "cinematic"
                reasons.append("cinematic shaders requested")

    if ram < 8 and preset != "performance":
        preset = "performance"
        reasons.append(f"only {ram} GB RAM")
    elif ram < 12 and preset == "cinematic":
        preset = "balanced"
        reasons.append(f"{ram} GB RAM is tight for cinematic shaders")
    if fps >= 120 and preset != "performance":
        preset = "balanced"
        reasons.append(f"{fps} FPS target")
    return {"preset": preset, "gpuTier": tier,
            "reason": "; ".join(dict.fromkeys(reasons)) + f" → {preset} preset"}


def _pick_version_file(prov, project: dict, mc_version: str, logger=None) -> Optional[dict]:
    """First MC-compatible version with a primary file that has a real URL."""
    try:
        versions = prov.get_versions(project["projectId"],
                                     {"minecraftVersion": mc_version}) or []
    except Exception:
        versions = []
    for v in versions:
        f = next((x for x in v.get("files") or [] if x.get("primary")),
                 (v.get("files") or [None])[0])
        if not f or not f.get("url"):
            continue
        return {"version": v, "file": f}
    if not versions and logger:
        logger.warn("shader", f"{project['title']}: no versions for MC {mc_version}")
    return None


def _choose_from_curseforge(providers, mc_version: str, preset: str,
                            logger=None) -> Optional[dict]:
    """Second source: search CurseForge by shader-pack name keywords."""
    for p in (providers or []):
        if p.name != "curseforge" or not getattr(p, "available", False):
            continue
        for query in CF_PRESET_QUERIES.get(preset, []):
            try:
                hits = p.search({"query": query, "projectType": "shader",
                                 "minecraftVersion": mc_version, "limit": 5}) or []
            except Exception as e:
                if logger:
                    logger.warn("shader", f"CurseForge search '{query}' unavailable: {e}")
                continue
            for h in hits:
                if h.get("projectType") != "shader":
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


def choose_shader(providers, mc_version: str, preset: str,
                  logger=None) -> Optional[dict]:
    """Fetch a real shader project + MC-compatible version.

    Returns {provider, project, version, file} or None (no compatible shader
    found). Modrinth first (shader packs are primarily distributed there);
    CurseForge is a real second source when a key is configured. The returned
    dict names the actual provider that supplied the pick.
    """
    for p in (providers or []):
        if p.name != "modrinth" or not getattr(p, "available", True):
            continue
        for slug in PRESET_SLUGS.get(preset, PRESET_SLUGS["balanced"]):
            try:
                proj = p.get_project(slug)
            except Exception:
                proj = None
            if not proj or proj.get("projectType") != "shader":
                continue
            picked = _pick_version_file(p, proj, mc_version, logger)
            if picked:
                return {"provider": "modrinth", "project": proj,
                        "version": picked["version"], "file": picked["file"]}
    return _choose_from_curseforge(providers, mc_version, preset, logger)


def rendering_mod_for(loader: str) -> str:
    """The shader-rendering MOD required for a loader (iris/oculus), so the
    chosen shader pack can actually run. Vanilla has no rendering mod — a
    shader zip alone is inert but harmless there."""
    if loader in ("fabric", "quilt"):
        return "iris"
    if loader in ("forge", "neoforge"):
        return "oculus"
    return ""
