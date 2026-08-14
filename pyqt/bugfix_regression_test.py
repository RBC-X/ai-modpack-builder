"""Regression tests for the bug / reliability / UI repair pass (30 issues)."""
from __future__ import annotations
import contextlib
import os, shutil, sys, tempfile, time, zipfile
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent))
checks = []
ENGINES = []

@contextlib.contextmanager
def _td():
    """Temp workspace whose engines are closed before cleanup (Windows sqlite
    handle would otherwise keep the dir locked)."""
    td = tempfile.mkdtemp()
    try:
        yield Path(td)
    finally:
        for e in list(ENGINES):
            try:
                e.close()
            except Exception:
                pass
        ENGINES.clear()
        shutil.rmtree(td, ignore_errors=True)
def check(name, condition, detail=""):
    checks.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))
def make_engine(work):
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine.bridge import PyEngine
    e = PyEngine()
    ENGINES.append(e)
    return e
def seed_pack(work, build_id, selections=None, graph=None, revision=1, test_result=None):
    from engine import core
    bdir = work / "builds" / build_id
    bdir.mkdir(parents=True, exist_ok=True)
    (bdir / "instance" / "minecraft" / "mods").mkdir(parents=True, exist_ok=True)
    rec = {"buildId": build_id, "name": f"Pack {build_id[-4:]}", "request": "seed",
           "status": "done", "phase": "done",
           "requirements": {"minecraftVersion": "1.20.1", "loader": "fabric", "ramGB": 8},
           "selections": selections or [], "downloads": [], "exports": [],
           "graph": graph or {"nodes": {}, "edges": []}, "tests": [],
           "testResult": test_result, "conflicts": [], "repairs": [],
           "packStats": {"modCount": len([s for s in (selections or []) if s.get("selected", True)])},
           "revision": revision, "identity": {},
           "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-01T00:00:00Z",
           "settings": {}}
    core.write_json_file(bdir / "build.json", rec)
    idx_path = work / "builds" / "index.json"
    idx = core.read_json_file(idx_path) or []
    if not any(r.get("buildId") == build_id for r in idx):
        idx.append({"buildId": build_id, "name": rec["name"]})
        core.write_json_file(idx_path, idx)
    return rec
class Logger:
    def stage(self, *_): pass
    def info(self, *_): pass
    def warn(self, *_): pass
    def ok(self, *_): pass
    def error(self, *_): pass

# Issue 15 — set_ram contract + clamping + revision bump
with _td() as td:
    e = make_engine(Path(td))
    bid = "b-ramtest-0001"
    seed_pack(Path(td), bid)
    r = e.set_ram(bid, 16)
    check("set_ram returns exact ramGB", r.get("ramGB") == 16, str(r))
    rec = e.build(bid)
    check("set_ram bumps revision", int(rec.get("revision") or 0) >= 1)
    check("set_ram stores clamped RAM", rec["requirements"]["ramGB"] == 16)
    r2 = e.set_ram(bid, 999)
    check("set_ram clamps to 32", r2.get("ramGB") == 32, str(r2.get("ramGB")))
    try:
        e.set_ram(bid, "junk"); check("set_ram rejects junk", False)
    except ValueError:
        check("set_ram rejects junk", True)

# Issue 26 — stale test evidence reads NEEDS_VALIDATION
with _td() as td:
    e = make_engine(Path(td))
    bid = "b-stale-0002"
    seed_pack(Path(td), bid, revision=5,
              test_result={"status": "PASS", "testedRevision": 5, "level": "standard", "phases": []})
    s = next(b for b in e.builds() if b["buildId"] == bid)
    check("fresh PASS summary", s.get("testStatus") == "PASS", str(s.get("testStatus")))
    seed_pack(Path(td), bid, revision=6,
              test_result={"status": "PASS", "testedRevision": 5, "level": "standard", "phases": []})
    s2 = next(b for b in e.builds() if b["buildId"] == bid)
    check("stale PASS reads NEEDS_VALIDATION", s2.get("testStatus") == "NEEDS_VALIDATION",
          str(s2.get("testStatus")))
    h = e.pack_health(bid)
    check("health sees stale test", h.get("signals", {}).get("testStatus") == "NEEDS_VALIDATION",
          str(h.get("signals", {}).get("testStatus")))

# Issue 6 — remove_mod dependency impact
with _td() as td:
    e = make_engine(Path(td))
    bid = "b-dep-0003"
    lib = {"key": "modrinth:architectury", "provider": "modrinth", "projectId": "architectury",
           "slug": "architectury", "title": "Architectury API", "projectType": "mod", "selected": True}
    moda = {"key": "modrinth:moda", "provider": "modrinth", "projectId": "moda",
            "slug": "moda", "title": "Mod A", "projectType": "mod", "selected": True}
    modb = {"key": "modrinth:modb", "provider": "modrinth", "projectId": "modb",
            "slug": "modb", "title": "Mod B", "projectType": "mod", "selected": True}
    graph = {"nodes": {"modrinth:architectury": {"selected": True},
                       "modrinth:moda": {"selected": True, "project": {"title": "Mod A"}},
                       "modrinth:modb": {"selected": True, "project": {"title": "Mod B"}}},
             "edges": [{"from": "modrinth:moda", "to": "modrinth:architectury"},
                       {"from": "modrinth:modb", "to": "modrinth:architectury"}]}
    seed_pack(Path(td), bid, selections=[lib, moda, modb], graph=graph)
    r = e.remove_mod(bid, "architectury")
    check("remove blocks on dependents", r.get("blocked") is True, str(r.get("message")))
    check("remove names dependents", "Mod A" in (r.get("dependents") or [])
          and "Mod B" in (r.get("dependents") or []), str(r.get("dependents")))
    seed_pack(Path(td), bid, selections=[lib, moda, modb], graph=graph,
              test_result={"status": "PASS", "testedRevision": 1, "phases": []})
    r2 = e.remove_mod(bid, "moda")
    check("leaf remove succeeds", r2.get("removed") is True)
    rec = e.build(bid)
    check("remove clears stale test", rec.get("testResult") is None)
    check("remove bumps revision", int(rec.get("revision") or 0) >= 2)

# Issue 5 — add_mod duplicate guard
with _td() as td:
    e = make_engine(Path(td))
    bid = "b-dup-0004"
    proj = {"provider": "modrinth", "projectId": "jei", "slug": "jei", "title": "JEI",
            "projectType": "mod"}
    seed_pack(Path(td), bid, selections=[{**proj, "key": "modrinth:jei", "selected": True}])
    r = e.add_mod(bid, "modrinth", "jei", "v1")
    check("duplicate add returns alreadySelected", r.get("alreadySelected") is True, str(r))
    check("no duplicate selection entry",
          len([s for s in e.build(bid).get("selections") or [] if s.get("slug") == "jei"]) == 1)

# Issue 7 — files() logs contract + read_file containment
with _td() as td:
    e = make_engine(Path(td))
    bid = "b-logs-0005"
    seed_pack(Path(td), bid)
    gd = Path(td) / "builds" / bid / "instance" / "minecraft"
    (gd / "logs").mkdir(parents=True, exist_ok=True)
    (gd / "crash-reports").mkdir(parents=True, exist_ok=True)
    (gd / "logs" / "latest.log").write_text("boot line", encoding="utf-8")
    (gd / "crash-reports" / "crash-2026.txt").write_text("StackOverflowError", encoding="utf-8")
    (gd / "hs_err_pid123.log").write_text("native crash", encoding="utf-8")
    files = e.files(bid)
    paths = [f.get("path") for f in files]
    check("files() lists latest.log", "logs/latest.log" in paths, str(paths))
    check("files() lists crash report", any("crash-2026.txt" in p for p in paths))
    check("files() lists hs_err", any(p.startswith("hs_err") for p in paths))
    kind = {f.get("path"): f.get("kind") for f in files}
    check("crash report kind", kind.get("crash-reports/crash-2026.txt") == "crash-report", str(kind))
    check("read_file returns log content", e.read_file(bid, "logs/latest.log").strip() == "boot line")
    check("evidence falls back to crash file", "StackOverflowError" in e.evidence(bid, "crash-2026.txt"))
    for evil in ("../secret", "..\secret", "/etc/passwd", "C:/evil.txt", "logs/../secret"):
        try:
            e.read_file(bid, evil)
            check(f"read_file rejects {evil!r}", False)
        except Exception as exc:  # bridge wraps PermissionError in ApiError
            check(f"read_file rejects {evil!r}", True)

# Issues 8 & 9 — import path containment + archive limits
from engine import imports  # noqa: E402

def make_zip_file(members):
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w") as z:
        for name, data in members:
            info = zipfile.ZipInfo(name)
            info.file_size = len(data)
            z.writestr(info, data)
    return Path(tmp.name)

# Path hardening: unsafe members are dropped, safe ones extracted.
check("safe_member_path rejects ..", imports.safe_member_path("overrides/../../evil") is None)
check("safe_member_path rejects absolute", imports.safe_member_path("/etc/passwd") is None)
check("safe_member_path rejects drive", imports.safe_member_path("C:/evil.txt") is None)
check("safe_member_path rejects UNC", imports.safe_member_path("//server/share/evil") is None)
check("safe_member_path keeps normal", imports.safe_member_path("overrides/config/a.toml") is not None)

with _td() as work:
    zpath = make_zip_file([("overrides/../../evil.txt", b"escaped"),
                           ("overrides/config/a.toml", b"a")])
    with zipfile.ZipFile(zpath) as zf:
        count = imports._extract_overrides(zf, work / "inst")
    check("traversal member skipped, safe member extracted", count == 1, str(count))
    check("no escape file written", not (work / "evil.txt").exists())
    check("safe member written", (work / "inst" / "config" / "a.toml").read_bytes() == b"a")

# Zip-bomb: an over-large single member aborts extraction cleanly.
with _td() as work:
    zpath = make_zip_file([("overrides/mods/big.jar", b"x" * 4096)])
    with mock.patch.object(imports, "MAX_SINGLE_FILE_BYTES", 1024):
        try:
            with zipfile.ZipFile(zpath) as zf:
                imports._extract_overrides(zf, work / "inst")
            check("zip bomb single-file limit enforced", False)
        except RuntimeError:
            check("zip bomb single-file limit enforced", True)

# Archive-level limits: entry count and declared-uncompressed total.
with _td() as work:
    zpath = make_zip_file([(f"overrides/mods/m{i}.jar", b"y") for i in range(600)])
    with zipfile.ZipFile(zpath) as zf:
        with mock.patch.object(imports, "MAX_ARCHIVE_ENTRIES", 100):
            try:
                imports._check_archive_limits(zf, zpath)
                check("archive entry-count limit enforced", False)
            except RuntimeError:
                check("archive entry-count limit enforced", True)

with _td() as work:
    zpath = make_zip_file([("overrides/mods/big.jar", b"z" * 4096)])
    with zipfile.ZipFile(zpath) as zf:
        with mock.patch.object(imports, "MAX_UNCOMPRESSED_TOTAL", 2048):
            try:
                imports._check_archive_limits(zf, zpath)
                check("declared-size limit enforced", False)
            except RuntimeError:
                check("declared-size limit enforced", True)

# Issue 16 — version range ~ semantics (npm-compatible minor ranges)
from engine.core import parse_version_range, version_satisfies  # noqa: E402

check("exact version", version_satisfies("1.20.1", "1.20.1"))
check("> lower", version_satisfies("1.21", ">1.20.1"))
check("> excluded", not version_satisfies("1.20.1", ">1.20.1"))
check("<= upper", version_satisfies("1.20.1", "<=1.20.1"))
check("tilde ~1.2 accepts 1.2.x", version_satisfies("1.2.4", "~1.2"))
check("tilde ~1.2 rejects 1.3", not version_satisfies("1.3.0", "~1.2"))
check("tilde ~1.2 accepts 1.2", version_satisfies("1.2", "~1.2"))
check("tilde ~1.2 rejects 1.1", not version_satisfies("1.1.9", "~1.2"))
c = parse_version_range("~1.20.1")
check("parse tilde expands to >= and <", any(x["op"] == ">=" and x["version"] == "1.20" for x in c)
      and any(x["op"] == "<" and x["version"] == "1.21" for x in c), str(c))
check("tilde range accepts 1.20.4", version_satisfies("1.20.4", "~1.20.1"))
check("tilde range rejects 1.21", not version_satisfies("1.21", "~1.20.1"))
c2 = parse_version_range(">=1.20, <1.21")
check("interval parse", any(x["op"] == ">=" and x["version"] == "1.20" for x in c2)
      and any(x["op"] == "<" and x["version"] == "1.21" for x in c2), str(c2))
check("interval accepts 1.20.4", version_satisfies("1.20.4", ">=1.20, <1.21"))
check("interval rejects 1.21", not version_satisfies("1.21", ">=1.20, <1.21"))

# Issue 24 — summary carries presentation for EVERY pack
with _td() as td:
    work = Path(td)
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine import core
    sel = [{"provider": "modrinth", "projectId": "abc123", "slug": "some-mod",
            "title": "Some Mod", "selected": True}]
    for i in range(40):
        seed_pack(work, f"b-enrich-{i:04d}", selections=sel, revision=1)
    e = make_engine(work)
    lst = e.builds()
    check("builds() lists all 40", len(lst) == 40, str(len(lst)))
    for i in (25, 29, 39):
        b = next(x for x in lst if x["buildId"] == f"b-enrich-{i:04d}")
        check(f"pack #{i+1} has coverUrl", bool(b.get("coverUrl")), str(b.get("coverUrl"))[:60])
        check(f"pack #{i+1} has testStatus", "testStatus" in b, "")
        check(f"pack #{i+1} has ramTarget", "ramTarget" in b, "")

# Issue 25 — download_summary is global
with _td() as td:
    work = Path(td)
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine import core
    for i in range(20):
        bid = f"b-dl-{i:04d}"
        rec = seed_pack(work, bid)
        rec["downloads"] = [{"key": f"modrinth:file{i}", "filename": f"file{i}.jar",
                             "status": "downloading" if i < 2 else "ok", "sizeBytes": 1000 + i}]
        core.write_json_file(work / "builds" / bid / "build.json", rec)
    e = make_engine(work)
    ds = e.download_summary()
    check("summary sees all packs' downloads", ds.get("total") == 20, str(ds.get("total")))
    check("active downloads first", ds.get("active") == 2, str(ds.get("active")))
    check("active records lead the list",
          all(r["status"] in ("downloading",) for r in ds["rows"][:2]), "")

# Issues 2 & 3 — fail-closed promotion + exact parity sync
with _td() as td:
    work = Path(td)
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine import core
    e = make_engine(work)
    parent_id, cand_id = "b-promo-parent", "b-promo-cand"
    seed_pack(work, parent_id, revision=3)
    par_mods = work / "builds" / parent_id / "instance" / "minecraft" / "mods"
    (par_mods / "old-mod.jar").write_bytes(b"old")
    (par_mods / "keep-mod.jar").write_bytes(b"keep")
    cand_dir = work / "builds" / cand_id / "instance" / "minecraft"
    (cand_dir / "mods").mkdir(parents=True, exist_ok=True)
    (cand_dir / "config").mkdir(parents=True, exist_ok=True)
    (cand_dir / "mods" / "keep-mod.jar").write_bytes(b"newer")
    (cand_dir / "mods" / "new-mod.jar").write_bytes(b"new")
    (cand_dir / "config" / "tweaks.toml").write_bytes(b"tweaked")
    cand = seed_pack(work, cand_id, revision=1,
                     test_result={"status": "PASS", "testedRevision": 1, "phases": []})
    cand["buildId"] = cand_id
    cand["requirements"] = {"minecraftVersion": "1.20.1", "loader": "fabric"}
    e._s._promote_candidate(parent_id, cand)
    after = set(p.name for p in par_mods.iterdir())
    check("exact parity: old mod removed", "old-mod.jar" not in after, str(after))
    check("exact parity: new mod present", "new-mod.jar" in after)
    check("exact parity: kept mod updated", (par_mods / "keep-mod.jar").read_bytes() == b"newer")
    cfg = work / "builds" / parent_id / "instance" / "minecraft" / "config" / "tweaks.toml"
    check("config promoted", cfg.read_bytes() == b"tweaked")
    prent = e.build(parent_id)
    check("promotion bumps parent revision", int(prent.get("revision") or 0) >= 4)

    seed_pack(work, parent_id, revision=9)
    bad_cand = dict(cand)
    bad_cand["buildId"] = cand_id + "x"
    bad_cand["requirements"] = {"minecraftVersion": "1.20.1", "loader": "fabric"}
    with mock.patch.object(e._s, "_sync_candidate_instance", side_effect=OSError("simulated copy failure")):
        try:
            e._s._promote_candidate(parent_id, bad_cand)
            check("failed promotion raises", False)
        except OSError:
            check("failed promotion raises", True)
    rec_after = e.build(parent_id)
    check("failed promotion leaves parent revision",
          int(rec_after.get("revision") or 0) == 9, str(rec_after.get("revision")))
    check("failed promotion recorded in history",
          any(h.get("op") == "promote-failed" for h in (rec_after.get("aiHistory") or [])), "")

# Issue 4 — snapshot restore reconstructs real config content
with _td() as td:
    work = Path(td)
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine import core
    e = make_engine(work)
    bid = "b-snap-0006"
    seed_pack(work, bid, revision=1)
    gd = work / "builds" / bid / "instance" / "minecraft"
    (gd / "config").mkdir(parents=True, exist_ok=True)
    (gd / "config" / "alpha.toml").write_text("VERSION_A", encoding="utf-8")
    snap = e.create_snapshot(bid, "state A")
    (gd / "config" / "alpha.toml").write_text("VERSION_B", encoding="utf-8")
    e.restore_snapshot(bid, snap["snapshotId"])
    got = (gd / "config" / "alpha.toml").read_text(encoding="utf-8")
    check("snapshot restore reconstructs config content", got == "VERSION_A", got)
    check("restore bumps revision", int(e.build(bid).get("revision") or 0) >= 2)

# Issues 10 & 11 — revision-safe retest + ERROR persistence
with _td() as td:
    work = Path(td)
    os.environ["AMB_WORKSPACE"] = str(work)
    from engine import core
    e = make_engine(work)
    bid = "b-retest-0007"
    seed_pack(work, bid, revision=5,
              selections=[{"key": "modrinth:m", "provider": "modrinth", "projectId": "m",
                           "slug": "m", "title": "M", "projectType": "mod", "selected": True}])
    core.write_json_file(work / "builds" / bid / "build.json",
                         {**e._s._read_record(bid), "downloads": []})

    def slow_pass(env, graph):
        time.sleep(1.2)
        return {"status": "PASS", "level": "standard", "testedRevision": 5,
                "phases": [{"name": "boot", "status": "PASS"}]}

    with mock.patch("engine.service.run_test_level", slow_pass):
        e.retest(bid)
        time.sleep(0.4)
        rec = e._s._read_record(bid)
        rec["selections"] = [{"key": "modrinth:m2", "provider": "modrinth", "projectId": "m2",
                              "slug": "m2", "title": "M2", "projectType": "mod", "selected": True}]
        rec["revision"] = 6
        e._s._write_record(rec)
        time.sleep(1.5)

    final = e._s._read_record(bid)
    check("stale retest cannot mark rev 6 validated",
          (final.get("testResult") or {}).get("status") != "PASS",
          str((final.get("testResult") or {}).get("status")))
    check("stale result archived in tests",
          any(t.get("stale") for t in (final.get("tests") or [])), "")
    check("newer selections survived", len(final.get("selections") or []) == 1
          and final["selections"][0]["slug"] == "m2")

    def boom(env, graph):
        raise RuntimeError("java missing")

    seed_pack(work, bid, revision=8,
              selections=[{"key": "modrinth:m", "provider": "modrinth", "projectId": "m",
                           "slug": "m", "title": "M", "projectType": "mod", "selected": True}])
    with mock.patch("engine.service.run_test_level", boom):
        e.retest(bid)
        time.sleep(1.5)
    final2 = e._s._read_record(bid)
    tr2 = final2.get("testResult") or {}
    check("infra failure persists ERROR", tr2.get("status") == "ERROR", str(tr2.get("status")))
    check("ERROR records errorType", tr2.get("errorType") == "TestInfrastructureError", "")

# Issues 12 & 13 — AI Builder terminal outcome single source
from views.aibuilder import AIBuilderView  # noqa: E402

v = AIBuilderView
check("testResult wins over tests",
      v._terminal_outcome({"testResult": {"status": "PASS"}, "tests": [{"status": "FAIL"}]})
      .get("status") == "PASS")
check("falls back to latest test",
      v._terminal_outcome({"tests": [{"status": "PASS"}, {"status": "FAIL"}]})
      .get("status") == "FAIL")
check("status failed => build failed", v._build_failed({"status": "failed"}))
check("FAIL test => build failed", v._build_failed({"testResult": {"status": "FAIL"}}))
check("PASS test => build ok", not v._build_failed({"testResult": {"status": "PASS"}}))

# Deep-test world move (WinError 183 class — found live 2026-08-13 on the
# medieval 1.20.4 deep run: a stale saves/world from an interrupted run broke
# the quickplay move). Tested offline; no game launch needed.
from engine.tester import move_server_world_to_saves  # noqa: E402

with _td() as t:
    gd = t / "game"
    (gd / "world" / "region").mkdir(parents=True)
    (gd / "world" / "level.dat").write_text("fresh")
    ok = move_server_world_to_saves(str(gd))
    check("world move: fresh server world -> saves/world",
          ok and (gd / "saves" / "world" / "level.dat").read_text() == "fresh"
          and not (gd / "world").exists())

with _td() as t:
    gd = t / "game"
    (gd / "world" / "region").mkdir(parents=True)
    (gd / "world" / "level.dat").write_text("fresh")
    (gd / "saves" / "world").mkdir(parents=True)
    (gd / "saves" / "world" / "stale.dat").write_text("stale")
    ok = move_server_world_to_saves(str(gd))
    check("world move: stale saves/world replaced (WinError 183 class)",
          ok and (gd / "saves" / "world" / "level.dat").read_text() == "fresh"
          and not (gd / "world").exists()
          and not (gd / "saves" / "world" / "stale.dat").exists())

if os.name == "nt":
    with _td() as t:
        gd = t / "game"
        (gd / "world" / "region").mkdir(parents=True)
        (gd / "world" / "level.dat").write_text("fresh")
        (gd / "saves" / "world").mkdir(parents=True)
        locked = gd / "saves" / "world" / "locked.dat"
        locked.write_text("locked")
        handle = open(locked, "r+b")  # delete-blocking handle, like a JVM hold
        try:
            ok = move_server_world_to_saves(str(gd))
        finally:
            handle.close()
        check("world move: locked stale file never raises",
              ok and (gd / "saves" / "world" / "level.dat").read_text() == "fresh"
              and not (gd / "world").exists())
else:
    print("[SKIP] world move: locked-file case (Windows-only)")

with _td() as t:
    gd = t / "game"
    (gd / "saves").mkdir(parents=True)
    ok = move_server_world_to_saves(str(gd))
    check("world move: no server world -> False, saves untouched",
          ok is False and not (gd / "saves" / "world").exists())

# ---------------------------------------------------------------------------
# Hardened attribute_crash: ClassNotFoundException WARN lines and class-load
# probe blocks must never be misread as crash evidence; only real exception
# stack frames (crash-report / fatal-screen / JVM stderr format) attribute.
from engine.repair import extract_stack_frames, mod_frames, attribute_crash

# 1. Healthy Forge latest.log: "Error loading class: ... ClassNotFoundException"
#    WARN one-liners (present in EVERY healthy pack) yield zero frames.
_healthy_log = """\
[00:50:20] [main/WARN]: Error loading class: me/jellysquid/mods/sodium/client/render/chunk/compile/pipeline/BlockRenderer (java.lang.ClassNotFoundException: me.jellysquid.mods.sodium.client.render.chunk.compile.pipeline.BlockRenderer)
[14:33:56] [main/WARN]: Error loading class: io/github/strikerrocker/vt/enchantments/SiphonEnchantment (java.lang.ClassNotFoundException: io.github.strikerrocker.vt.enchantments.SiphonEnchantment)
[14:33:57] [main/WARN]: Error loading class: com/geckolib/animation/AnimationController (java.lang.ClassNotFoundException: com.geckolib.animation.AnimationController)
[14:33:58] [main/WARN]: Force-disabling mixin 'features.render.entity.cull.EntityRendererMixin' as rule 'mixin.features.render.entity' (added by mods [oculus]) disables it and children
[14:34:00] [main/INFO]: Launching target 'forgeclient' with arguments [--version, 1.20.1]
"""
check("attribution: WARN ClassNotFoundException one-liners yield no frames",
      extract_stack_frames(_healthy_log) == [],
      f"got {extract_stack_frames(_healthy_log)}")

# 2. ERROR-rooted "Failed to load:" probe block (optional compat discovery —
#    seen verbatim in the healthy flagship debug.log) yields zero frames even
#    though it carries `at ...` frames into a real mod class.
_probe_block = """\
[14:34:22] [modloading-worker-0/ERROR]: Failed to load: com.github.minecraftschurlimods.arsmagicalegacy.compat.theoneprobe.TOPCompat
java.lang.NoClassDefFoundError: mcjty/theoneprobe/api/IProbeInfoProvider
\tat java.lang.Class.forName0(Native Method) ~[?:?]
\tat java.lang.Class.forName(Unknown Source) ~[?:?]
\tat com.github.minecraftschurlimods.arsmagicalegacy.compat.CompatManager.lambda$getClasses$1(CompatManager.java:118) ~[ars-magica-legacy.jar%23325!/:1.5.0]
\tat com.github.minecraftschurlimods.arsmagicalegacy.compat.CompatManager.getClasses(CompatManager.java:123) ~[ars-magica-legacy.jar%23325!/:1.5.0]
"""
check("attribution: ERROR 'Failed to load:' probe block yields no frames",
      mod_frames(extract_stack_frames(_probe_block)) == [],
      f"got {mod_frames(extract_stack_frames(_probe_block))}")

# 3. A REAL crash block (bare throwable header + frames, crash-report format)
#    still attributes — the mechanism the probe hardening must not break.
_real_crash = """\
---- Minecraft Crash Report ----
// Who set us up the TNB?

Time: 2026-08-13 12:00:00
Description: Rendering screen

java.lang.NullPointerException: Cannot invoke "com.foo.Bar.method()" because "bar" is null
\tat com.foo.Bar.method(Bar.java:42) ~[foo-mod.jar!/:1.0.0]
\tat com.example.Main.tick(Main.java:10) ~[foo-mod.jar!/:1.0.0]
Caused by: java.lang.IllegalStateException: broken state
\tat com.foo.Bar.init(Bar.java:20) ~[foo-mod.jar!/:1.0.0]
"""
_frames_real = mod_frames(extract_stack_frames(_real_crash))
check("attribution: real crash block keeps its mod frames",
      _frames_real == ["com.foo.Bar", "com.example.Main"],
      f"got {_frames_real}")

# 4. A real crash next to healthy WARN noise: noise contributes nothing, the
#    genuine block still attributes (this is the organic-crash scenario).
_mixed = _healthy_log + "\n[13:43:47] [main/ERROR]: Missing or unsupported mandatory dependencies:\n" \
    + "\tMod ID: 'incendium', Requested by: 'ibo', Expected range: '[5.1.4,)', Actual version: '[MISSING]'\n" \
    + "net.minecraftforge.fml.ModLoadingException: Mod eibo requires incendium 5.1.4 or above\n" \
    + "\tat net.minecraftforge.fml.ModLoadingException.lambda$fromEarlyException$0(ModLoadingException.java:50) ~[fmlcore-1.20.1-47.4.22.jar%23455!/:?]\n" \
    + "\tat com.foo.Loader.check(Loader.java:8) ~[foo-mod.jar!/:1.0.0]\n"
_frames_mixed = extract_stack_frames(_mixed)
check("attribution: mixed log keeps fatal-block frames only",
      _frames_mixed == ["net.minecraftforge.fml.ModLoadingException", "com.foo.Loader"],
      f"got {_frames_mixed}")

# 5. JVM uncaught-thread format (Exception in thread ...) still attributes.
_uncaught = """\
[13:44:00] [Render thread/ERROR]: An unexpected error occurred
Exception in thread \"Render thread\" java.lang.RuntimeException: boom
\tat com.foo.Bar.render(Bar.java:99) ~[foo-mod.jar!/:1.0.0]
"""
check("attribution: 'Exception in thread' block keeps its frames",
      mod_frames(extract_stack_frames(_uncaught)) == ["com.foo.Bar"],
      f"got {mod_frames(extract_stack_frames(_uncaught))}")

# Issue 31 — launch-time heap fitting against FREE RAM (adaptive 1.5-4 GB).
from engine.hardware import fit_xmx_to_free_mb  # noqa: E402
_fit = fit_xmx_to_free_mb
check("heap fit: plenty of free RAM keeps the requested 4 GB",
      _fit(4096, 5.5) == 4096, str(_fit(4096, 5.5)))
check("heap fit: 4 GB free fits down to ~2.5 GB (reserves 1.5 for native)",
      _fit(4096, 4.0) == 2560, str(_fit(4096, 4.0)))
check("heap fit: tight RAM never goes below the 1.5 GB floor",
      _fit(4096, 1.2) == 1536 and _fit(4096, 0.4) == 1536,
      f"{_fit(4096, 1.2)} / {_fit(4096, 0.4)}")
check("heap fit: never exceeds the 4 GB cap even for oversized requests",
      _fit(6000, 9.0) == 4096, str(_fit(6000, 9.0)))
check("heap fit: small packs are never inflated by a RAM surplus",
      _fit(2048, 8.0) == 2048, str(_fit(2048, 8.0)))

# Issue 32 — instance re-install skips identical jars (copy2 + size/mtime), so
# relaunches stop rewriting 2-3 GB and dirtying the page cache before launch.
from engine.instance import _copy_if_changed  # noqa: E402
_tmp = Path(tempfile.mkdtemp())
_src = _tmp / "src.jar"
_dst = _tmp / "dst.jar"
_src.write_bytes(b"JAR" * 100)
shutil.copy2(_src, _dst)
check("instance: identical jar (size+mtime) is NOT re-copied",
      _copy_if_changed(_src, _dst) is False, "re-copied identical jar")
check("instance: changed jar IS re-copied (new size)",
      _copy_if_changed(_src, _tmp / "dst2.jar") is True, "did not copy new jar")
_src.write_bytes(b"JAR" * 200)
check("instance: size change re-copies over the old dst",
      _copy_if_changed(_src, _dst) is True, "size change not detected")
shutil.rmtree(_tmp, ignore_errors=True)

# -- deep-test evidence stamping (from REAL phase detail strings) ----------
# The driver's evidence JSON must record copy-skip, the actual measured
# settle gap(s), the GC peak heap, and the engine version — extracted from
# the phase records the engine itself wrote during a run.
from engine.tester import deep_evidence_fields  # noqa: E402

_real_phases = [
    {"name": "instance", "status": "PASS",
     "detail": "Instance mods already present — skipping 2-3 GB re-install"},
    {"name": "memory-monitor", "status": "PASS",
     "detail": "Peak heap observed in GC log: 790 MB"},
]
f = deep_evidence_fields(_real_phases, [10.0, 45.0], "1.0.19")
check("deep evidence: copy-skip read from instance detail", f["copySkip"] is True, str(f["copySkip"]))
check("deep evidence: GC peak read from memory-monitor detail", f["gcPeakMb"] == 790, str(f["gcPeakMb"]))
check("deep evidence: settleSec = last MEASURED gap", f["settleSec"] == 45.0, str(f["settleSec"]))
check("deep evidence: all settle gaps recorded", f["settleSecs"] == [10.0, 45.0], str(f["settleSecs"]))
check("deep evidence: engine version stamped", f["engineVersion"] == "1.0.19", f["engineVersion"])

_no_skip = deep_evidence_fields(
    [{"name": "instance", "status": "PASS", "detail": "Mods and packs installed into isolated instance"}],
    None, "1.0.19")
check("deep evidence: no copy-skip when instance re-installed", _no_skip["copySkip"] is None, str(_no_skip["copySkip"]))
check("deep evidence: no GC peak when detail lacks it", _no_skip["gcPeakMb"] is None, str(_no_skip["gcPeakMb"]))
check("deep evidence: settleSec None without measured gaps", _no_skip["settleSec"] is None, str(_no_skip["settleSec"]))

# -- adaptive phase settle (measured, not fixed) --------------------------
# _settle_before_launch must wait for free RAM to plateau (measuring how long
# Windows actually takes to reclaim the killed JVM), settle at the floor on a
# stable machine, and never exceed maxSettleSec.
from engine.tester import _settle_before_launch as _settle  # noqa: E402
import engine.tester as _tester_mod  # noqa: E402

class _FakeLog:
    def info(self, *a):
        pass

_real = _tester_mod._free_gb
_stable = {"logger": _FakeLog()}
_tester_mod._free_gb = lambda: 3.0
_gap_stable = _settle(_stable, "reproducibility relaunch")
check("settle: stable machine settles at the floor (~10 s)",
      10.0 <= _gap_stable <= 12.0, f"{_gap_stable:.1f}s")
check("settle: measured gap recorded in env['settleSecs']",
      _stable["settleSecs"] == [round(_gap_stable, 1)], str(_stable["settleSecs"]))

_climb = iter([1.0, 1.4, 1.8, 2.4, 2.9, 3.0, 3.0, 3.0, 3.0, 3.0])
_tester_mod._free_gb = lambda: next(_climb, 3.0)
_gap_climb = _settle({"logger": _FakeLog()}, "reproducibility relaunch")
check("settle: waits past the floor while RAM is still climbing",
      _gap_climb >= 12.0, f"{_gap_climb:.1f}s")

_never = iter([0.5, 0.9, 1.3, 1.7, 2.1, 2.5, 2.9, 3.3, 3.7])
_tester_mod._free_gb = lambda: next(_never, 4.1)
_cap_env = {"logger": _FakeLog(), "maxSettleSec": 8}
_gap_cap = _settle(_cap_env, "reproducibility relaunch")
check("settle: hard cap respected when RAM never plateaus",
      8.0 <= _gap_cap <= 10.0, f"{_gap_cap:.1f}s")
_tester_mod._free_gb = _real

# Fresh-compat-db schema regression: the entries table used to be created only
# inside a shadowed close() method, so a brand-new database (new install, CI
# workspace) failed every query with 'no such table: entries'. CI's seed build
# caught it on a fresh AMB_WORKSPACE.
import sqlite3 as _sqlite3  # noqa: E402
with tempfile.TemporaryDirectory() as _cdir:
    from engine.compat import CompatibilityDatabase  # noqa: E402
    cdb = CompatibilityDatabase(os.path.join(_cdir, "compat.db"))
    _schema_err = ""
    try:
        try:
            cdb.record({"minecraftVersion": "1.20.1", "loader": "forge",
                        "mods": {"jei": 1}, "result": "pass", "buildId": "b-x"})
            cdb.record({"minecraftVersion": "1.20.1", "loader": "forge",
                        "mods": {"jei": 1}, "result": "fail", "buildId": "b-y"})
            _ok_schema = (cdb.count() == 2
                          and len(cdb.history_for("1.20.1", "forge")) == 2)
        except _sqlite3.OperationalError as _e:
            _ok_schema = False
            _schema_err = str(_e)
    finally:
        cdb.close()
check("fresh compat.db creates schema and stores entries", _ok_schema, _schema_err)

print()
passed = sum(1 for _n, ok in checks if ok)
failed = [(n, d) for n, ok in checks if not ok]
print(f"===== {passed} passed, {len(failed)} failed =====")
if failed:
    for n, d in failed:
        print("FAILED:", n, d)
    sys.exit(1)
