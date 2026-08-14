"""Update-feed edge-case regressions: hostile/malformed feeds, version
pinning, download integrity + cleanup, rollback selection, and throttles.

Pure logic - no GUI, no network beyond loopback/file:// with the dev flag.
Usage: python pyqt/update_feed_edge_test.py
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest import mock

import updater

checks = []


def check(name, condition, detail=""):
    checks.append((name, bool(condition)))
    print(f"[{'PASS' if condition else 'FAIL'}] {name}" + (f" - {detail}" if detail else ""))


def _feed_file(root: Path, data: dict | bytes) -> Path:
    p = root / "update.json"
    p.write_bytes(data if isinstance(data, bytes) else json.dumps(data).encode("utf-8"))
    return p


def _valid_feed(root: Path, version: str = "9.9.9", payload: bytes = b"installer-bytes") -> tuple[Path, str]:
    setup = root / f"AI-Modpack-Builder-Setup-{version}.exe"
    setup.write_bytes(payload)
    feed = _feed_file(root, {
        "version": version,
        "notes": "edge-case feed",
        "installerUrl": setup.as_uri(),
        "installerSha256": hashlib.sha256(payload).hexdigest(),
    })
    return feed, hashlib.sha256(payload).hexdigest()


with tempfile.TemporaryDirectory() as td:
    root = Path(td)

    # -- malformed / hostile feeds ---------------------------------------
    bad = _feed_file(root, b"{not json!!")
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        res = updater.check(bad.as_uri())
    check("malformed JSON feed -> ok=False, no crash",
          res.get("ok") is False and res.get("available") is False)

    missing_ver = _feed_file(root, {"installerUrl": "https://x/y.exe",
                                    "installerSha256": "a" * 64})
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        res = updater.check(missing_ver.as_uri())
    check("feed missing version -> ok=False", res.get("ok") is False)

    missing_url = _feed_file(root, {"version": "9.9.9"})
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        res = updater.check(missing_url.as_uri())
    check("feed missing installerUrl -> ok=False", res.get("ok") is False)

    bad_sha = _feed_file(root, {"version": "9.9.9", "installerUrl": "https://x/y.exe",
                                "installerSha256": "not-a-hash"})
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        res = updater.check(bad_sha.as_uri())
    check("feed with invalid SHA -> ok=False", res.get("ok") is False)

    # Streaming size cap: a feed larger than 2 MB is rejected without being
    # fully buffered (memory-bound hardening).
    huge = _feed_file(root, b"x" * (2 * 1024 * 1024 + 1))
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        try:
            updater.fetch_feed(huge.as_uri())
            huge_rejected = False
        except ValueError as e:
            huge_rejected = "too large" in str(e)
    check("oversized feed rejected with streaming cap", huge_rejected)

    # -- version pinning --------------------------------------------------
    # Pre-release / unparsable suffixes must never read as an upgrade.
    check("pre-release suffix never triggers update",
          updater.version_tuple("1.0.21-rc1") <= updater.version_tuple("1.0.20"))
    check("unparsable version compares as older",
          updater.version_tuple("banana") == (0,))
    check("v-prefix tolerated", updater.version_tuple("v1.0.21") == (1, 0, 21))
    check("two-part version is older than three-part",
          updater.version_tuple("1.0") < updater.version_tuple("1.0.21"))

    # -- download integrity + cleanup -------------------------------------
    feed, digest = _valid_feed(root, "9.9.9")
    installer_url = json.loads(feed.read_text("utf-8"))["installerUrl"]
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        ok_dest = updater.download(installer_url, root / "out1", digest)
        ok_clean = ok_dest.read_bytes() == b"installer-bytes"

        try:
            updater.download(installer_url, root / "out2", "0" * 64)
            mismatch_raised = False
        except ValueError:
            mismatch_raised = True
        mismatch_cleaned = not (root / "out2" / ok_dest.name).exists()

        try:
            updater.download(installer_url, root / "out3", digest, max_mb=0)
            cap_raised = False
        except ValueError:
            cap_raised = True
        cap_cleaned = not any((root / "out3").glob("*.exe"))
    check("download verifies correct SHA", ok_clean)
    check("SHA mismatch -> ValueError + partial file removed", mismatch_raised and mismatch_cleaned)
    check("size cap exceeded -> ValueError + partial file removed", cap_raised and cap_cleaned)

    # -- run_update orchestration ------------------------------------------
    with mock.patch.dict(os.environ, {"AMB_UPDATE_ALLOW_INSECURE": "1"}):
        report = updater.run_update(feed.as_uri(), apply=False, dest_dir=root / "upd")
    check("run_update reports downloaded + applied=False without apply",
          report.get("ok") and report.get("downloaded") and report.get("applied") is False)

    # -- rollback selection -------------------------------------------------
    pool = root / "rollback" / "updates"
    pool.mkdir(parents=True)
    (pool / "AI-Modpack-Builder-Setup-1.0.5.exe").write_bytes(b"a")
    (pool / "AI-Modpack-Builder-Setup-1.0.6.exe").write_bytes(b"b")
    # Current-version installer must not be a rollback target.
    (pool / f"AI-Modpack-Builder-Setup-{updater.APP_VERSION}.exe").write_bytes(b"c")
    (pool / "unrelated.txt").write_text("noise")
    cand = updater.rollback_candidate(root / "rollback")
    check("rollback candidate = newest older version",
          cand and cand["version"] == "1.0.6")
    check("empty pool -> no rollback candidate",
          updater.rollback_candidate(root / "empty-dir") is None)

    # -- applied marker roundtrip -------------------------------------------
    data_dir = root / "data"
    check("applied marker absent initially",
          updater.applied_marker(data_dir) is None)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / updater.ROLLBACK_MARKER).write_text(json.dumps({"version": "1.0.21"}), "utf-8")
    check("applied marker roundtrip",
          updater.applied_marker(data_dir) == "1.0.21")
    updater.clear_applied_marker(data_dir)
    check("clear applied marker",
          updater.applied_marker(data_dir) is None)

    # -- throttles ------------------------------------------------------------
    dd = root / "throttle"
    check("fresh stamp -> check allowed", updater.should_auto_check(dd))
    updater.stamp_check(dd)
    check("stamped now -> check throttled", not updater.should_auto_check(dd, hours=24))
    check("hours=0 overrides throttle", updater.should_auto_check(dd, hours=0))
    updater.stamp_check(dd, stamp=updater.PERIODIC_STAMP)
    check("separate periodic stamp throttled independently",
          updater.should_auto_check(dd, stamp=updater.PERIODIC_STAMP) is False
          and updater.should_auto_check(dd, stamp=updater.CHECK_STAMP) is False)

    # -- network failure never raises -----------------------------------------
    res = updater.check("https://127.0.0.1:1/update.json", timeout=2)
    check("unreachable feed -> ok=False, available=False",
          res.get("ok") is False and res.get("available") is False)

print(f"\n===== {sum(ok for _, ok in checks)} passed, "
      f"{sum(not ok for _, ok in checks)} failed =====")
if not all(ok for _, ok in checks):
    raise SystemExit(1)
