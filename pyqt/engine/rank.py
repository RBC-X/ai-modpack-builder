"""Ranking engine — Python port of src/selector/rank.ts.

Scores candidate projects against the request and explains every score.
"""
from __future__ import annotations

import math
import re
import time
from typing import Optional

from .jarname import invalid_module_reason

THEME_WORDS = {
    "medieval": ["medieval", "knight", "castle", "rpg"],
    "fantasy": ["fantasy", "magic", "mythical", "dragon"],
    "rpg": ["rpg", "leveling", "classes"],
    "horror": ["horror", "scary", "creepy", "dark"],
    "vanilla": ["vanilla", "vanilla plus"],
    "realistic": ["realistic", "immersion", "survival"],
    "adventure": ["exploration", "adventure"],
    "cozy": ["cozy", "chill"],
}


def _theme_words(theme: str) -> list:
    return THEME_WORDS.get(theme, [theme])


def _clamp_score(n: float) -> float:
    return max(0, min(100, round(n * 10) / 10))


def rank_candidate(project: dict, feature: dict, req: dict, memory=None) -> dict:
    """memory: object with best_result_for_mod() or None (compat DB)."""
    factors = []

    # 1. Relevance (0..40, DOMINANT)
    title = f"{project.get('title', '')} {project.get('slug', '')}".lower()
    body = f"{project.get('description', '')} {' '.join(project.get('categories') or [])}".lower()
    terms = [
        t.strip().lower() for t in list(feature.get("keywords") or [])
        if len(t.strip()) >= 3
    ]
    title_hits = list(dict.fromkeys([k for k in terms if k in title]))
    body_hits = list(dict.fromkeys([k for k in terms if k not in title_hits and k in body]))
    cat_hits = [c for c in (project.get("categories") or []) if c in (feature.get("categoryTags") or [])]
    fit = 0
    if title_hits:
        fit += min(26, len(title_hits) * 13)
    if body_hits:
        fit += min(12, len(body_hits) * 3)
    if cat_hits:
        fit += min(6, len(cat_hits) * 3)
    relevant = fit > 0
    if title_hits:
        fit_note = f"title/slug matches: {', '.join(title_hits[:3])}"
    elif body_hits:
        fit_note = f"description matches: {', '.join(body_hits[:3])}"
    elif cat_hits:
        fit_note = f"matches category {', '.join(cat_hits)}"
    else:
        fit_note = "no relevance — cannot outrank a matching mod"
    factors.append({"name": "relevance", "score": fit, "note": fit_note})

    # 2. Popularity (0..12)
    dl = math.log10(max(1, project.get("downloads") or 0))
    pop = min(12, dl * 1.6)
    factors.append({"name": "popularity", "score": round(pop * 10) / 10,
                    "note": f"{project.get('downloads') or 0:,} downloads"})

    # 3. Recency (0..8)
    rec = 0
    rec_note = "unknown age"
    try:
        modified = time.mktime(time.strptime(project.get("dateModified", "")[:10], "%Y-%m-%d"))
    except (ValueError, TypeError):
        modified = float("nan")
    if modified == modified:
        days = (time.time() - modified) / 86400
        rec = 8 if days < 30 else 6 if days < 120 else 4 if days < 365 else 2
        rec_note = f"updated {round(days)}d ago"
    factors.append({"name": "recency", "score": rec, "note": rec_note})

    # 4. Environment fit (0..4)
    env = 2
    env_note = "env unknown"
    if project.get("clientSide") and project.get("serverSide"):
        if req.get("multiplayer") and project.get("serverSide") == "unsupported":
            env = 0
            env_note = "server-side unsupported"
        elif project.get("serverSide") in ("required", "optional"):
            env = 4
            env_note = f"server: {project.get('serverSide')}"
        else:
            env = 2
    factors.append({"name": "environment", "score": env, "note": env_note})

    # 5. Compatibility memory (0..12, can be negative)
    mem_score = 0
    mem_note = "no history"
    if memory is not None:
        rec2 = memory.best_result_for_mod(req.get("minecraftVersion"), req.get("loader"),
                                          project.get("slug"), project.get("projectId"))
        if rec2:
            if rec2.get("result") == "PASS":
                mem_score = 12
                mem_note = f"known PASS in memory ({len(rec2.get('mods') or [])} mods)"
            elif rec2.get("result") == "FAIL":
                mem_score = -30
                mem_note = f"known FAIL in memory: {rec2.get('crashSignature') or 'unknown'}"
            else:
                mem_score = 4
                mem_note = f"known PARTIAL ({rec2.get('repair') or 'n/a'})"
    factors.append({"name": "memory", "score": mem_score, "note": mem_note})

    # 6. Vanilla-request dampener (-10)
    vanilla_penalty = 0
    if "vanilla" in (req.get("theme") or []) and \
       (any(c in ("technology", "magic") for c in (project.get("categories") or []))):
        vanilla_penalty = -10
    factors.append({"name": "vanilla-fit", "score": vanilla_penalty,
                    "note": "vanilla-themed request, heavy mod penalized"})

    # 7. Loadability (-60): filename-derived Java module name kills Forge/NeoForge
    #    bootstrap before any log. Deterministic from the slug.
    load_penalty = 0
    load_note = "loads cleanly"
    if project.get("projectType") == "mod":
        bad = invalid_module_reason(project.get("slug", ""))
        if bad:
            load_penalty = -60
            load_note = bad
    factors.append({"name": "loadability", "score": load_penalty, "note": load_note})

    # The displayed score is exactly the clamped sum of displayed factors.
    # Relevance remains dominant without a hidden 40-point bonus.
    factors[0]["score"] = min(40, fit + (20 if relevant else 0))
    if not relevant:
        for factor in factors[1:4]:
            factor["score"] = 0
    raw_score = round(sum(float(f["score"]) for f in factors) * 10) / 10
    score = _clamp_score(raw_score)
    if score != raw_score:
        factors.append({"name": "score-bound", "score": round((score - raw_score) * 10) / 10,
                        "note": "score kept within 0–100"})
    pos = ", ".join(f"{f['name']} (+{f['score']})" for f in factors if f["score"] > 0)
    neg = ", ".join(f"{f['name']} ({f['score']})" for f in factors if f["score"] < 0)
    reason = f"Score {score}/100 — {pos}{('. ' + neg) if neg else ''}. {fit_note}."
    return {"project": project, "score": score, "reason": reason, "factors": factors}


def normalize_slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())[:40]
