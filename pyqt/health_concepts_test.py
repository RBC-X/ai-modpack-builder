"""Tests — starter concepts / Surprise Me / Pack Health.

Covers: curated concept structure + a real interpret() round-trip (the seed
prompt must actually drive the deterministic interpreter), Surprise Me
determinism and hardware sizing, the explainable health score on real record
shapes (test result, conflicts, updates, LKG snapshot compare), the service
endpoints over the in-process bridge, and minimal UI construction checks.

Run:  pyqt/.venv/Scripts/python pyqt/health_concepts_test.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ws = Path(tempfile.mkdtemp(prefix="amb-health-test-"))
os.environ["AMB_WORKSPACE"] = str(_ws)
os.environ["AMB_DISABLE_CATALOG_WARMUP"] = "1"

from engine import concepts  # noqa: E402
from engine.health import pack_health, STATUS_LABELS, WEIGHTS  # noqa: E402
from engine.interpreter import interpret  # noqa: E402
from engine.snapshots import create_snapshot  # noqa: E402
from engine.bridge import PyEngine  # noqa: E402
from engine.service import PyEngine as Service  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def base_record(**over):
    rec = {
        "buildId": "b-test",
        "name": "Test Pack",
        "requirements": {
            "minecraftVersion": "1.20.1", "loader": "fabric", "ramGB": 8,
            "shaders": True, "packSize": "medium",
            "features": [{"id": "bosses"}, {"id": "magic"}],
        },
        "selections": [
            {"key": "modrinth:a", "provider": "modrinth", "projectId": "a",
             "slug": "apotheosis", "title": "Apotheosis", "projectType": "mod",
             "featureIds": ["bosses"], "versionId": "v1", "versionNumber": "1.0",
             "selected": True},
            {"key": "modrinth:b", "provider": "modrinth", "projectId": "b",
             "slug": "ars", "title": "Ars Nouveau", "projectType": "mod",
             "featureIds": ["magic"], "versionId": "v1", "versionNumber": "1.0",
             "selected": True},
        ],
        "graph": {"nodes": {}, "edges": []},
        "conflicts": [], "repairs": [], "exports": [],
        "packStats": {"modCount": 2},
        "testResult": None, "perfEstimate": None,
        "identity": {
            "coreTheme": "Dark Fantasy", "requiredFeatures": ["bosses", "magic"],
            "lockedMods": [],
        },
        "healthUpdates": None,
    }
    rec.update(over)
    return rec


def main():
    print("== 1. Starter concepts ==")
    check("six curated concepts", len(concepts.STARTER_CONCEPTS) >= 6,
          str(len(concepts.STARTER_CONCEPTS)))
    ids = set()
    for c in concepts.STARTER_CONCEPTS:
        ids.add(c["id"])
        for f in concepts.BRIEF_FIELDS:
            check(f"field {f} on {c['id']}", f in c, c.get("id"))
    check("unique ids", len(ids) == len(concepts.STARTER_CONCEPTS))
    check("prompts composed", all(c.get("prompt") for c in concepts.STARTER_CONCEPTS))

    print("== 2. Seed prompts drive the interpreter (no fake seeds) ==")
    for c in concepts.STARTER_CONCEPTS:
        req = interpret(c["prompt"])["requirements"]
        ok = not req["needsClarification"] and bool(req["features"])
        check(f"interpretable: {c['id']}", ok,
              f"theme={req['theme']} feats={[f['id'] for f in req['features']]}")
        if req["theme"]:
            check(f"theme lands: {c['id']}",
                  any(t in req["theme"] for t in (c.get("theme") or [])), str(req["theme"]))

    print("== 3. Surprise Me determinism + hardware sizing ==")
    a1 = concepts.surprise_me(seed=42)
    a2 = concepts.surprise_me(seed=42)
    check("same seed -> same concept", a1["prompt"] == a2["prompt"])
    distinct = {concepts.surprise_me(seed=s)["prompt"] for s in range(12)}
    check("seeds vary", len(distinct) >= 3, f"{len(distinct)} distinct of 12")
    small = concepts.surprise_me(seed=1, hardware={"ramGB": 4})
    check("low RAM -> light pack, no shaders",
          small["packSize"] == "light" and small["shaders"] is False,
          f"{small['packSize']} / shaders={small['shaders']}")
    big = concepts.surprise_me(seed=1, hardware={"ramGB": 32})
    check("32 GB -> large+ pack", big["packSize"] in ("large", "massive"),
          big["packSize"])
    check("surprise prompt interpretable",
          not interpret(small["prompt"])["requirements"]["needsClarification"])
    check("brief lines non-empty", bool(concepts.brief_lines(a1)))

    print("== 4. Health score on real record shapes ==")
    h_empty = pack_health(base_record())
    check("status in known set", h_empty["status"] in STATUS_LABELS, h_empty["status"])
    check("score in 0..100", 0 <= h_empty["score"] <= 100, str(h_empty["score"]))
    check("metrics all present", all(k in h_empty["metrics"] for k in WEIGHTS))
    check("factors explain every metric", len(h_empty["factors"]) == len(WEIGHTS))
    check("unvalidated pack not 'excellent'", h_empty["status"] != "excellent",
          f"{h_empty['status']} {h_empty['score']}")

    tr_pass = {"status": "PASS", "level": "deep",
               "phases": [{"name": "a", "status": "PASS"}] * 4}
    h_pass = pack_health(base_record(testResult=tr_pass))
    check("PASS deep -> excellent/stable", h_pass["status"] in ("excellent", "stable"),
          f"{h_pass['status']} {h_pass['score']}")
    check("PASS stability high", h_pass["metrics"]["stability"]["score"] >= 95,
          str(h_pass["metrics"]["stability"]["score"]))

    h_fail = pack_health(base_record(testResult={"status": "FAIL", "level": "standard",
                                                 "phases": [{"name": "launch", "status": "FAIL"}]}))
    check("FAIL -> broken", h_fail["status"] == "broken", f"{h_fail['status']} {h_fail['score']}")
    check("FAIL flagged", any(f["severity"] == "error" for f in h_fail["flags"]))

    clean = pack_health(base_record(testResult=tr_pass))
    conflicted = pack_health(base_record(testResult=tr_pass, conflicts=[
        {"id": "c1", "severity": "error", "type": "renderer", "resolved": False,
         "description": "Sodium vs OptiFine", "resolution": ""},
        {"id": "c2", "severity": "warning", "type": "depver", "resolved": False,
         "description": "dep version", "resolution": ""},
    ]))
    check("conflicts lower compatibility",
          conflicted["metrics"]["compatibility"]["score"] < clean["metrics"]["compatibility"]["score"],
          f"{clean['metrics']['compatibility']['score']} -> {conflicted['metrics']['compatibility']['score']}")
    check("unresolved conflicts flagged", any(f["severity"] == "error" for f in conflicted["flags"]))
    check("conflicted pack not stable",
          conflicted["status"] in ("attention", "problems", "broken"), conflicted["status"])

    upd = pack_health(base_record(testResult=tr_pass,
                                  healthUpdates={"checkedAt": "2026-08-12T00:00:00Z", "count": 3,
                                                 "available": []}))
    check("updates lower maintenance",
          upd["metrics"]["maintenance"]["score"] < clean["metrics"]["maintenance"]["score"],
          f"{clean['metrics']['maintenance']['score']} -> {upd['metrics']['maintenance']['score']}")
    check("updates flagged as info", any(f["severity"] == "info" and "update" in f["text"].lower()
                                         for f in upd["flags"]))

    ram_hw = pack_health(base_record(testResult=tr_pass, perfEstimate={"confidence": 90,
                                                                      "estimatedRamMB": 12288}),
                         hardware={"ramGB": 8})
    check("RAM over machine ceiling penalized",
          "exceeds" in " ".join(ram_hw["metrics"]["performance"]["reasons"]),
          str(ram_hw["metrics"]["performance"]["reasons"]))

    print("== 5. LKG compare (real snapshot on disk) ==")
    bdir = Path(tempfile.mkdtemp(prefix="amb-lkg-"))
    rec = base_record(testResult=tr_pass)
    create_snapshot(bdir, rec, "LKG", kind="last-known-good")
    same = pack_health(rec, build_dir=bdir)
    check("LKG present", same["signals"]["hasLkg"] is True)
    check("LKG current when identical", same["signals"]["lkgCurrent"] is True)
    rec2 = base_record(testResult=tr_pass)
    rec2["selections"] = rec2["selections"][:1]  # diverged (one mod removed)
    div = pack_health(rec2, build_dir=bdir)
    check("LKG stale when changed", div["signals"]["hasLkg"] and not div["signals"]["lkgCurrent"])
    check("stale LKG flagged", any("changed since Last Known Good" in f["text"] for f in div["flags"]))

    print("== 6. Service endpoints over the in-process bridge ==")
    e = PyEngine()
    created = e.create_pack("Health Test", "1.20.1", "fabric", 8)
    bid = created["buildId"]
    h = e.pack_health(bid)
    check("pack_health via bridge", h["status"] in STATUS_LABELS and "metrics" in h,
          f"{h['status']} {h['score']}")
    check("empty pack scored low content", h["metrics"]["content"]["score"] <= 40,
          str(h["metrics"]["content"]["score"]))
    check("empty pack flagged", bool(h["flags"]), str([f["text"] for f in h["flags"]]))

    print("== 7. UI construction (home concepts + builder seeding) ==")
    from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
    app = QApplication.instance() or QApplication(sys.argv)
    from views.home import HomeView
    from views.aibuilder import AIBuilderView

    class StubAPI:
        def hardware(self):
            return {"effective": {"ramGB": 16, "cpu": "Test", "gpu": "Test"}}
        def settings_get(self):
            return {"build": {"sources": ["modrinth"]}}

    home = HomeView()
    texts = []
    for child in home.findChildren(QLabel) + home.findChildren(QPushButton):
        texts.append(child.text())
    check("home has Starter Experiences", any("Starter Experiences" in t for t in texts))
    check("home shows SURPRISE ME", any("SURPRISE ME" in t for t in texts))
    home._starter_section.show()

    builder = AIBuilderView(StubAPI())
    seed = concepts.STARTER_CONCEPTS[0]["prompt"]
    builder.seed_prompt(seed)
    check("aibuilder seeded", builder._prompt.toPlainText() == seed)
    check("build button enabled after seed", builder._build_btn.isEnabled())

    print("== 8. Pack Detail health card renders real data (end-to-end) ==")
    from views.packdetail import PackDetailView
    from PyQt6.QtWidgets import QPushButton
    bid2 = e.create_pack("Health UI", "1.20.1", "fabric", 8)["buildId"]
    pd = PackDetailView(e)
    rec = e.build(bid2)
    pd.load(bid2, rec)
    deadline = time.time() + 20
    while pd._health is None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    check("health data fetched through the view", pd._health is not None)
    if pd._health is not None:
        check("health status known", pd._health["status"] in STATUS_LABELS, pd._health["status"])
        texts = []
        for child in pd.findChildren(QLabel) + pd.findChildren(QPushButton):
            texts.append(child.text())
        check("health card shows status + score", any("/100" in t for t in texts),
              [t for t in texts if "/100" in t][:1])
        check("health card has Check Updates", any("CHECK MOD UPDATES" in t for t in texts))
        check("metric Why buttons present", pd.findChildren(QPushButton, "") and
              any(b.toolTip().startswith("Why ") for b in pd.findChildren(QPushButton)))
        upd_btn = next((b for b in pd.findChildren(QPushButton) if "CHECK MOD UPDATES" in b.text()), None)
        if upd_btn is not None:
            upd_btn.click()
            deadline = time.time() + 25
            while time.time() < deadline:
                app.processEvents()
                if (e.build(bid2) or {}).get("healthUpdates"):
                    break
                time.sleep(0.1)
            hu = (e.build(bid2) or {}).get("healthUpdates") or {}
            check("Check Updates persists real result", bool(hu.get("checkedAt")),
                  f"checked={hu.get('checked')}")

    print("== 9. Concept editor: BUILD emits the seed prompt ==")
    from PyQt6.QtCore import QTimer as _QTimer
    from PyQt6.QtWidgets import QDialog as _QDialog
    got = []
    home.seed_requested.connect(lambda p: got.append(p))

    def drive_editor():
        for w in app.allWidgets():
            if isinstance(w, _QDialog) and w.isVisible():
                for b in w.findChildren(QPushButton):
                    if "BUILD WITH AI" in b.text():
                        b.click()
                        return

    _QTimer.singleShot(300, drive_editor)
    home._open_concept_editor(concepts.STARTER_CONCEPTS[1])
    check("editor BUILD emits seed prompt", bool(got) and got[0].startswith("Build me a"),
          (got or ["(none)"])[0][:60])


if __name__ == "__main__":
    main()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", FAIL)
        sys.exit(1)
