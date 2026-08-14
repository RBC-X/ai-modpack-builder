"""Pack Health — explainable status + score derived from real record data.

The spec (§36–37) demands a persistent, *explainable* health view: every
number comes from an explicit metric, and every metric can say why. Nothing
here is fabricated: scores are deterministic functions of the pack record
(test result, conflict list, perf estimate, mod count, identity, updates
check), the Last Known Good snapshot on disk, and the machine's hardware.

Statuses map the weighted score to the spec's states:
🟢 Excellent · 🟢 Stable · 🟡 Attention · 🟠 Problems · 🔴 Broken.
"""
from __future__ import annotations

import time

from .features import feature_by_id
from .snapshots import last_known_good as _lkg_snapshot

STATUS_LABELS = {
    "excellent": "Excellent",
    "stable": "Stable",
    "attention": "Attention recommended",
    "problems": "Potential problems",
    "broken": "Broken",
}

STATUS_COLORS = {
    "excellent": "green",
    "stable": "green",
    "attention": "warn",
    "problems": "warn",
    "broken": "danger",
}

WEIGHTS = {
    "stability": 0.28,
    "compatibility": 0.22,
    "performance": 0.20,
    "content": 0.12,
    "theme": 0.10,
    "maintenance": 0.08,
}


def _metric(label: str, score: float, reasons: list, weight: float) -> dict:
    return {
        "label": label,
        "score": int(round(max(0.0, min(100.0, score)))),
        "reasons": reasons,
        "weight": weight,
    }


def _test_status(rec: dict) -> dict:
    """Single source of truth for validation status (Issue 26/30): a recorded
    test only describes the revision it tested. If the pack changed since, the
    verdict is NEEDS_VALIDATION — never a PASS badge describing a different
    pack."""
    tr = rec.get("testResult") or {}
    status = tr.get("status")
    tested = int(tr.get("testedRevision") or 0)
    if tested and int(rec.get("revision") or 0) != tested:
        status = "NEEDS_VALIDATION"
    level = tr.get("level")
    phases = tr.get("phases") or []
    passed = sum(1 for p in phases if p.get("status") == "PASS")
    return {"status": status, "level": level, "phases": phases, "passed": passed}


def _lkg_state(rec: dict, build_dir) -> dict:
    """Whether the current selections match the Last Known Good snapshot."""
    try:
        lkg = _lkg_snapshot(build_dir) if build_dir else None
    except Exception:  # noqa: BLE001
        lkg = None
    if not lkg:
        return {"hasLkg": False, "current": False}
    current_keys = set()
    for s in rec.get("selections") or []:
        if s.get("selected", True):
            current_keys.add(s.get("key") or f"{s.get('provider')}:{s.get('projectId')}")
    lkg_keys = {s.get("key") for s in (lkg.get("selections") or []) if s.get("key")}
    return {
        "hasLkg": True,
        "current": current_keys == lkg_keys,
        "lkgCreatedAt": lkg.get("createdAt"),
        "lkgModCount": len(lkg.get("selections") or []),
        "currentModCount": len(current_keys),
    }


def _conflict_stats(rec: dict) -> dict:
    errors = 0
    warnings = 0
    auto = 0
    for c in rec.get("conflicts") or []:
        if c.get("resolved"):
            auto += 1
            continue
        if c.get("severity") == "error":
            errors += 1
        else:
            warnings += 1
    return {"errors": errors, "warnings": warnings, "autoResolved": auto}


def _selection_feature_ids(rec: dict) -> set:
    out = set()
    for s in rec.get("selections") or []:
        if not s.get("selected", True):
            continue
        out.update(s.get("featureIds") or [])
    return out


def pack_health(rec: dict, build_dir=None, hardware: dict | None = None) -> dict:
    """Compute the explainable health report for a pack record.

    `build_dir` is the pack's build dir (for the Last Known Good compare);
    `hardware` is the detected/effective machine profile. Pure and
    deterministic — no network, no writes.
    """
    rec = rec or {}
    req = rec.get("requirements") or {}
    identity = rec.get("identity") or {}
    perf = rec.get("perfEstimate") or {}
    stats = rec.get("packStats") or {}
    mod_count = int(stats.get("modCount") or 0)
    test = _test_status(rec)
    lkg = _lkg_state(rec, build_dir)
    conf = _conflict_stats(rec)
    updates = rec.get("healthUpdates") or {}

    metrics: dict = {}
    factors: list[dict] = []
    flags: list[dict] = []

    # ---- Stability (test evidence + LKG) --------------------------------
    reasons = []
    if test["status"] == "PASS":
        base = 95.0 + (2.0 if test["level"] == "deep" else 0.0)
        reasons.append(f"Last test passed ({test['level'] or 'standard'} mode, {test['passed']} phase(s))")
        if lkg["hasLkg"]:
            base = min(100.0, base + 1.0)
            reasons.append("Validated state is saved as Last Known Good")
    elif test["status"] == "FAIL":
        base = 12.0
        reasons.append("The last test failed — the pack may not launch")
    elif test["status"] == "NEEDS_VALIDATION":
        base = 45.0
        reasons.append("The pack changed since its last test — run a re-test for current evidence")
    else:
        base = 45.0
        reasons.append("No test result recorded yet — run a re-test for real evidence")
    metrics["stability"] = _metric("Stability", base, reasons, WEIGHTS["stability"])

    # ---- Compatibility (conflict engine output) -------------------------
    reasons = []
    comp = 100.0
    if conf["errors"]:
        comp -= 22.0 * conf["errors"]
        reasons.append(f"{conf['errors']} unresolved error conflict(s)")
    if conf["warnings"]:
        comp -= 8.0 * conf["warnings"]
        reasons.append(f"{conf['warnings']} unresolved warning(s)")
    if conf["autoResolved"]:
        comp -= 2.0 * conf["autoResolved"]
        reasons.append(f"{conf['autoResolved']} conflict(s) auto-resolved by the engine")
    if not reasons:
        reasons.append("No conflicts detected by the conflict engine")
    metrics["compatibility"] = _metric("Compatibility", comp, reasons, WEIGHTS["compatibility"])

    # ---- Performance (real estimator + hardware fit) --------------------
    reasons = []
    pconf = int(perf.get("confidence") or 0)
    if pconf:
        pscore = float(pconf)
        reasons.append(f"Performance estimate confidence {pconf}%")
    else:
        pscore = 60.0
        reasons.append("No performance estimate — fit comes from the build pipeline")
    if hardware:
        hw_ram_mb = int(hardware.get("ramGB") or 0) * 1024
        est_mb = int(perf.get("estimatedRamMB") or 0)
        if hw_ram_mb and est_mb:
            if est_mb > hw_ram_mb:
                pscore -= 28.0
                reasons.append(
                    f"Estimated RAM {est_mb // 1024} GB exceeds this PC's {hw_ram_mb // 1024} GB")
            elif est_mb > hw_ram_mb * 0.8:
                pscore -= 10.0
                reasons.append("Estimated RAM is close to this PC's ceiling")
            else:
                pscore += 3.0
                reasons.append("Estimated RAM fits comfortably on this PC")
    req_ram = int(req.get("ramGB") or 0)
    if req_ram and hardware and req_ram > int(hardware.get("ramGB") or 0):
        pscore -= 12.0
        reasons.append(f"Allocated {req_ram} GB exceeds the machine's {hardware.get('ramGB')} GB")
    metrics["performance"] = _metric("Performance", pscore, reasons, WEIGHTS["performance"])

    # ---- Content (mod breadth vs pack size) ------------------------------
    reasons = []
    if mod_count == 0:
        cscore = 25.0
        reasons.append("The pack has no content installed yet")
    elif mod_count < 20:
        cscore = 60.0
        reasons.append(f"{mod_count} mods — a lean, focused pack")
    elif mod_count < 60:
        cscore = 80.0
        reasons.append(f"{mod_count} mods — a solid breadth of content")
    elif mod_count < 120:
        cscore = 90.0
        reasons.append(f"{mod_count} mods — broad, genre-spanning content")
    elif mod_count <= 200:
        cscore = 84.0
        reasons.append(f"{mod_count} mods — very large; watch RAM and startup time")
    else:
        cscore = 70.0
        reasons.append(f"{mod_count} mods — extreme size risks stability")
    metrics["content"] = _metric("Content", cscore, reasons, WEIGHTS["content"])

    # ---- Theme cohesion (identity required features actually present) ----
    reasons = []
    required = identity.get("requiredFeatures") or []
    sel_ids = _selection_feature_ids(rec)
    if required:
        satisfied = [f for f in required if f in sel_ids]
        ratio = len(satisfied) / len(required)
        tscore = 50.0 + 50.0 * ratio
        reasons.append(
            f"{len(satisfied)}/{len(required)} required features present"
            + ("" if ratio == 1.0 else " - add the missing ones for a more faithful pack"))
    else:
        tscore = 85.0
        reasons.append("No required-feature list — identity is loosely defined")
    locked = identity.get("lockedMods") or []
    if locked:
        slugs = {s.get("slug") for s in rec.get("selections") or []}
        missing_locked = [m for m in locked if m not in slugs]
        if missing_locked:
            tscore -= 15.0
            reasons.append(f"Locked mod(s) missing: {', '.join(missing_locked[:3])}")
    metrics["theme"] = _metric("Theme cohesion", tscore, reasons, WEIGHTS["theme"])

    # ---- Maintenance (mod updates, if checked) ---------------------------
    reasons = []
    checked_at = updates.get("checkedAt")
    if checked_at:
        n = int(updates.get("count") or 0)
        mscore = max(30.0, 100.0 - 7.0 * n)
        reasons.append(f"Update check at {checked_at}: {n} mod(s) have newer versions")
        if n:
            flags.append({
                "severity": "info",
                "text": f"{n} mod update(s) available — Smart Update can apply them safely.",
            })
    else:
        mscore = 80.0
        reasons.append("Update check not run — press Check Updates for an accurate maintenance score")
    metrics["maintenance"] = _metric("Maintenance", mscore, reasons, WEIGHTS["maintenance"])

    # ---- Weighted overall score ------------------------------------------
    total_w = sum(WEIGHTS.values())
    score = sum(metrics[k]["score"] * WEIGHTS[k] for k in WEIGHTS) / total_w
    score = int(round(max(0.0, min(100.0, score))))

    # ---- Status with honest forcing rules --------------------------------
    status = "excellent" if score >= 88 else \
        "stable" if score >= 72 else \
        "attention" if score >= 55 else \
        "problems" if score >= 35 else "broken"
    if test["status"] == "FAIL":
        status = "broken"
    elif not test["status"] and not lkg["hasLkg"] and status in ("excellent", "stable"):
        status = "attention"  # nothing has ever validated
    if status in ("stable", "excellent") and conf["errors"]:
        status = "attention"

    # ---- Signals + explainable factors ----------------------------------
    signals = {
        "testStatus": test["status"],
        "testLevel": test["level"],
        "hasLkg": lkg["hasLkg"],
        "lkgCurrent": lkg["current"],
        "lkgCreatedAt": lkg.get("lkgCreatedAt"),
        "conflictErrors": conf["errors"],
        "conflictWarnings": conf["warnings"],
        "autoResolvedConflicts": conf["autoResolved"],
        "repairCount": len(rec.get("repairs") or []),
        "modCount": mod_count,
        "updatesAvailable": int(updates.get("count") or 0),
        "updatesCheckedAt": checked_at,
        "running": bool(rec.get("running")),
        "score": score,
        "status": status,
    }

    if test["status"] == "FAIL":
        flags.append({"severity": "error", "text": "The last real test failed — repair or restore a snapshot."})
    if conf["errors"]:
        flags.append({"severity": "error", "text": f"{conf['errors']} unresolved conflict(s) — repair recommended."})
    if not lkg["hasLkg"] and test["status"] != "FAIL":
        flags.append({"severity": "warning", "text": "No Last Known Good yet - every successful test saves one."})
    elif lkg["hasLkg"] and not lkg["current"]:
        flags.append({"severity": "warning", "text": "Pack changed since Last Known Good - restore it if the new state misbehaves."})
    missing_files = [s.get("title") or s.get("slug") for s in (rec.get("selections") or [])
                     if s.get("selected", True) and not s.get("downloadPath")]
    if missing_files:
        flags.append({"severity": "warning", "text": f"{len(missing_files)} selection(s) have no downloaded file recorded."})
    if rec.get("repairs"):
        flags.append({"severity": "info", "text": f"{len(rec.get('repairs'))} repair(s) applied during the last build."})
    if req.get("shaders") and not rec.get("shaderChoice"):
        flags.append({"severity": "info", "text": "Shaders requested but none were selected in the visuals step."})

    for key in ("stability", "compatibility", "performance", "content", "theme", "maintenance"):
        m = metrics[key]
        impact = "up" if m["score"] >= 75 else ("down" if m["score"] < 55 else "neutral")
        factors.append({
            "metric": key,
            "label": m["label"],
            "score": m["score"],
            "impact": impact,
            "reason": m["reasons"][0] if m["reasons"] else "",
        })

    return {
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status),
        "statusColor": STATUS_COLORS.get(status, "muted"),
        "score": score,
        "metrics": metrics,
        "factors": factors,
        "flags": flags,
        "signals": signals,
        "computedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


__all__ = ["pack_health", "STATUS_LABELS", "STATUS_COLORS", "WEIGHTS"]
