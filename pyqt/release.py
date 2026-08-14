"""One-shot release: build the signed installer from a clean checkout of the
version tag, then publish it - in one command.

This makes the 1.0.23 provenance rule mechanical: the installer is ALWAYS
built from the exact tagged source, so the tag, the source archive, the
installer metadata, the update feed, and the release notes cannot drift from
each other again.

Flow:
  1. Resolve APP_VERSION from product_config.py.
  2. Require a clean working tree; ensure the v<ver> tag exists at HEAD
     (creating it if missing), then push it.
  3. `git worktree add` a throwaway FRESH checkout of that tag.
  4. Copy the git-ignored signing/secret environment into the worktree and
     build the signed installer there (PyInstaller -> sign -> frozen selftest
     -> Inno Setup -> sign -> isolated-install selftest), reusing the shared
     toolchain venv via AMB_VENV_PY.
  5. Gate: the installer exists and its Authenticode status is Valid; copy it
     back into the main checkout's installers/.
  6. Re-render the screenshot gallery (from the main checkout - the fresh
     worktree has no pack data) and refresh the committed gallery folder.
  7. Publish: run publish_release.py (creates the release, uploads the
     installer + update feed + gallery assets).
  8. Verify the public HTTPS feed serves v<ver>, then remove the worktree.

Run AFTER bumping APP_VERSION + writing the CHANGELOG entry and committing +
pushing main, e.g.:

    pyqt/.venv/Scripts/python pyqt/release.py
    pyqt/.venv/Scripts/python pyqt/release.py --dry-run   # validate plumbing only

Flags:  --repo OWNER/REPO   (default RBC-X/ai-modpack-builder)
        --version X.Y.Z     (default: product_config APP_VERSION)
        --force-tag         re-point an existing v<ver> tag at HEAD
        --no-push-tag       don't push the tag (publish needs it on origin)
        --no-gallery        skip the screenshot re-render
        --no-publish        build + verify only, no gh release
        --dry-run           stop before the build
        --guard             CI-safe preflight only (no build): working tree
                            clean + current-version tag points at a commit
                            carrying that same APP_VERSION and reachable from
                            HEAD. Run on every push so a mis-tagged release
                            fails before publishing.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # repo root
HERE = ROOT / "pyqt"
VENV_PY = HERE / ".venv" / "Scripts" / "python.exe"
REPO = "RBC-X/ai-modpack-builder"
ASSETS_DIR = ROOT / "screenshots"


def log(msg: str) -> None:
    print(f"[release] {msg}", flush=True)


def phase(name: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    print(f"[{tag}] {name}" + (f" - {detail}" if detail else ""), flush=True)


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], capture_output=True, text=True)


def _git_out(*args: str) -> str:
    r = _git(*args)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout.strip()


def _version() -> str:
    import product_config  # noqa: PLC0415 - needs pyqt/ on sys.path

    return product_config.APP_VERSION


def _authenticode_valid(exe: Path) -> bool:
    """PowerShell Get-AuthenticodeSignature - 'Valid' with our signer."""
    ps = (
        "$f='" + str(exe).replace("'", "''") + "';"
        "$s=Get-AuthenticodeSignature $f;"
        "Write-Output ($s.Status.ToString() + '|' + $s.SignerCertificate.Subject)"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=120)
    out = (r.stdout or "").strip().splitlines()
    return bool(out and out[-1].startswith("Valid|"))


def _run(cmd: list[str], cwd: Path | None = None, env=None, timeout: int = 3600) -> int:
    """Run a command with live output (no capture) and a generous timeout."""
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, env=env, timeout=timeout)
    return r.returncode


def _source_version(commit: str) -> str:
    """The APP_VERSION embedded in a commit's own product_config."""
    src = _git("show", f"{commit}:pyqt/product_config.py")
    if src.returncode != 0:
        return ""
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src.stdout)
    return m.group(1) if m else ""


def _rebased_twin(tag_rev: str, version: str) -> str | None:
    """Find the in-history twin of an orphaned release tag after a rebase.

    The twin is a commit reachable from HEAD that carries the same
    APP_VERSION and whose tree matches the tag's tree everywhere except
    screenshots/ (the CI bot regenerates those independently). Returns the
    newest match, or None if nothing qualifies."""
    tag_tree = _git("ls-tree", "-r", tag_rev)
    if tag_tree.returncode != 0:
        return None
    tag_blobs = {}
    for line in (tag_tree.stdout or "").splitlines():
        meta, path = line.split("\t", 1)
        tag_blobs[path] = meta.split()[2]
    try:
        head = _git_out("rev-parse", "HEAD")
        commits = _git_out("rev-list", head).splitlines()
    except RuntimeError:
        return None
    for c in commits:
        if _source_version(c) != version:
            continue
        diff = _git("diff", "--name-only", tag_rev, c)
        names = [n for n in (diff.stdout or "").splitlines()
                 if not n.startswith("screenshots/")]
        if not names:
            return c
    return None


def _sync_main() -> bool:
    """Fetch origin and rebase local-only commits onto origin/main with -X
    ours, so the release tag is created on an up-to-date base and the final
    push fast-forwards instead of being rejected by the CI screenshot bot's
    concurrent commit. Returns False if the rebase fails."""
    _git("fetch", "origin")
    try:
        behind = int(_git_out("rev-list", "--count", "HEAD..origin/main") or 0)
    except (RuntimeError, ValueError):
        return True
    if behind <= 0:
        return True
    log(f"origin/main is {behind} commit(s) ahead - rebasing -X ours first")
    return _git("pull", "--rebase", "-X", "ours", "origin", "main").returncode == 0


def _guard(version: str) -> int:
    """CI-safe preflight, run on every push so a mis-tagged release fails
    BEFORE publishing. It audits only the CURRENT version's tag - legacy tags
    (pre-1.0.21) predate strict provenance and are not re-litigated here:

      1. the working tree is clean,
      2. if v<version> exists, the commit it points at carries the SAME
         APP_VERSION in its own source (the v1.0.22 failure class: a tag
         pointing at a commit that says a different version), and
      3. that commit is reachable from HEAD (the release is in main's
         history, not an orphaned/force-moved tag).
    """
    dirty = _git("status", "--porcelain")
    if dirty.stdout.strip():
        log(f"[guard] FAIL - working tree is NOT clean "
            f"({len(dirty.stdout.splitlines())} uncommitted paths)")
        return 1
    tag = f"v{version}"
    try:
        tag_rev = _git_out("rev-parse", f"{tag}^{{}}")
    except RuntimeError:
        log(f"[guard] PASS - tag {tag} does not exist yet (version bumped, "
            "not released) - nothing to verify")
        return 0
    head = _git_out("rev-parse", "HEAD")
    src = _git("show", f"{tag}:pyqt/product_config.py")
    if src.returncode != 0:
        log(f"[guard] FAIL - tag {tag} points at {tag_rev[:10]} whose source "
            "has no pyqt/product_config.py (wrong tag)")
        return 1
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', src.stdout)
    tagged = m.group(1) if m else ""
    if tagged != version:
        log(f"[guard] FAIL - tag {tag} points at {tag_rev[:10]} whose source "
            f"carries APP_VERSION {tagged!r}, not {version!r} (mis-tagged - "
            "the v1.0.22 failure class)")
        return 1
    if _git("merge-base", "--is-ancestor", tag_rev, head).returncode != 0:
        log(f"[guard] FAIL - tag {tag} ({tag_rev[:10]}) is not reachable from "
            f"HEAD ({head[:10]})")
        return 1
    log(f"[guard] PASS - tag {tag} -> {tag_rev[:10]}, source APP_VERSION "
        f"{version!r}, ancestor of HEAD ({head[:10]})")
    return 0


def main() -> int:
    args = sys.argv[1:]
    version = next((args[i + 1] for i, a in enumerate(args) if a == "--version"), None)
    if not version:
        version = _version()
    repo = next((args[i + 1] for i, a in enumerate(args) if a == "--repo"), REPO)
    force_tag = "--force-tag" in args
    no_push_tag = "--no-push-tag" in args
    no_gallery = "--no-gallery" in args
    no_publish = "--no-publish" in args
    dry_run = "--dry-run" in args

    tag = f"v{version}"
    installer_name = f"AI-Modpack-Builder-Setup-{version}.exe"
    sys.path.insert(0, str(HERE))

    if "--guard" in args:
        return _guard(version)

    # ---- 0. Preconditions -------------------------------------------------
    if not VENV_PY.exists():
        log(f"toolchain venv not found: {VENV_PY}")
        return 1
    dirty = _git("status", "--porcelain")
    if dirty.stdout.strip():
        log("working tree is NOT clean - commit/push before releasing "
            f"(uncommitted: {len(dirty.stdout.splitlines())} paths)")
        return 1

    # ---- 0.5 Sync with origin before tagging -------------------------------
    # The CI screenshot bot often lands a commit while the version bump is in
    # flight; rebase -X ours up front so the tag is created on an up-to-date
    # base and the final push fast-forwards.
    if not dry_run and not _sync_main():
        log("initial rebase onto origin/main failed - resolve and re-run")
        return 1

    # ---- 1. Tag must exist at HEAD ---------------------------------------
    head = _git_out("rev-parse", "HEAD")
    try:
        tag_rev = _git_out("rev-parse", f"{tag}^{{}}")
    except RuntimeError:
        tag_rev = None
    if tag_rev is None:
        log(f"tag {tag} missing - creating at HEAD ({head[:10]})")
        if not dry_run and _git("tag", tag, "HEAD").returncode != 0:
            return 1
    elif tag_rev != head and not force_tag:
        log(f"tag {tag} points at {tag_rev[:10]} but HEAD is {head[:10]} - "
            "release from the tag, or pass --force-tag to re-point it")
        return 1
    elif tag_rev != head:
        log(f"--force-tag: re-pointing {tag} from {tag_rev[:10]} to {head[:10]}")
        if not dry_run and _git("tag", "-f", tag, "HEAD").returncode != 0:
            return 1
    else:
        log(f"tag {tag} == HEAD ({head[:10]}) - good")

    if dry_run:
        log("--dry-run: preconditions ok, stopping before build/publish.")
        return 0

    # ---- 2. Push the tag ---------------------------------------------------
    if not no_push_tag:
        # Force: a re-pointed tag (--force-tag) must overwrite the remote
        # marker; the CI release-guard audits tag correctness, so a plain move
        # is the only thing a force push can do.
        r = _git("push", "--force", "origin", f"refs/tags/{tag}")
        phase("push tag", r.returncode == 0, r.stderr.strip() or "up to date")

    # ---- 3. Clean-checkout worktree ---------------------------------------
    worktree = ROOT.parent / f".release-{version}"
    # A previously failed run can leave a partial dir and stale git metadata;
    # prune first so `worktree add` always starts from a clean slate.
    _git("worktree", "prune")
    if worktree.exists():
        shutil.rmtree(worktree, ignore_errors=True)
    r = _git("worktree", "add", str(worktree), tag)
    if r.returncode != 0:
        log(f"git worktree add failed: {r.stderr.strip()}")
        return 1
    phase("clean checkout of the tag", True, str(worktree))
    started = time.time()
    try:
        # ---- 4. Copy the signing/secret environment (git-ignored, not source)
        secrets = HERE / ".secrets"
        if secrets.is_dir():
            shutil.copytree(secrets, worktree / "pyqt" / ".secrets",
                            dirs_exist_ok=True)
            log("copied pyqt/.secrets/ (embedded CurseForge key env)")

        # ---- 5. Build the signed installer IN the worktree ------------------
        log("building signed installer (PyInstaller -> sign -> frozen selftest "
            "-> Inno Setup) - this takes ~30 min")
        env = dict(os.environ, AMB_VENV_PY=str(VENV_PY))
        rc = _run([str(VENV_PY), "pyqt/build_installer.py", "--trust", "--verify"],
                  cwd=worktree, env=env)
        setup = worktree / "installers" / installer_name
        phase("installer build", rc == 0 and setup.exists(),
              f"{setup.name} ({setup.stat().st_size // 1024 // 1024} MB)" if setup.exists() else "missing")
        if rc != 0 or not setup.exists():
            return 1

        # ---- 6. Gate: Authenticode Valid, then copy back ---------------------
        valid = _authenticode_valid(setup)
        phase("installer Authenticode", valid, "signature Valid")
        if not valid:
            return 1
        # publish_release.py reads ROOT/installers — copy there, not pyqt/.
        dest = ROOT / "installers" / installer_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(setup, dest)
        phase("installer copied to main checkout", dest.exists(), str(dest))

        # ---- 7. Refresh the screenshot gallery -

        # ---- 7. Refresh the screenshot gallery -------------------------------
        if not no_gallery:
            log("re-rendering the 24-shot gallery (main checkout - fresh "
                "worktree has no pack data)")
            rc = _run([str(VENV_PY), "pyqt/screenshot.py"], cwd=ROOT)
            rendered = sorted((HERE / "screenshots").glob("*.png"))
            gallery = 0
            for p in rendered:
                shutil.copyfile(p, ASSETS_DIR / p.name)
                gallery += 1
            phase("gallery refresh", rc == 0 and gallery > 0, f"{gallery} shots")
            # The gallery is a tracked release asset (README + Pages). Commit
            # it so the tree never ends the release dirty and the publish is
            # not blocked by the clean-tree precondition on a re-run.
            dirty_gallery = _git("status", "--porcelain", "--", "screenshots")
            if dirty_gallery.stdout.strip():
                _git("add", "--", "screenshots")
                r = _git("commit", "-m",
                         f"chore: refresh screenshot gallery for the {version} renders")
                phase("gallery committed", r.returncode == 0,
                      f"{len(dirty_gallery.stdout.splitlines())} files")

        # ---- 8. Publish -------------------------------------------------------
        if no_publish:
            log("--no-publish: build + verify done; publish manually with:")
            log(f"  pyqt/.venv/Scripts/python pyqt/publish_release.py --repo {repo} --assets {ASSETS_DIR}")
            return 0
        log("publishing release + update feed + gallery...")
        pub = [str(VENV_PY), "pyqt/publish_release.py", "--repo", repo,
               "--assets", str(ASSETS_DIR)]
        rc = _run(pub, cwd=ROOT)
        if rc not in (0, 2):  # 2 = no authenticated gh CLI (manual steps printed)
            return 1

        # ---- 9. Verify the public feed ----------------------------------------
        try:
            feed = subprocess.run(
                ["curl", "-sL",
                 f"https://github.com/{repo}/releases/latest/download/update.json"],
                capture_output=True, text=True, timeout=60).stdout
            d = json.loads(feed)
            phase("public feed serves the release", d.get("version") == version,
                  f"version={d.get('version')} sha={str(d.get('installerSha256'))[:12]}...")
        except Exception as e:  # noqa: BLE001 - feed may lag the CDN briefly
            phase("public feed serves the release", False, str(e)[:120])
        # Keep origin/main in sync with the released state (the gallery commit
        # lands after the tag was built). If the CI bot raced us, rebase -X
        # ours (our gallery wins) and retry; a rebase orphans the release tag,
        # so reconcile it to its in-history twin afterwards.
        r = _git("push", "origin", "main")
        if r.returncode != 0:
            log("push main rejected - syncing with origin (CI bot?) and retrying")
            _git("pull", "--rebase", "-X", "ours", "origin", "main")
            r = _git("push", "origin", "main")
            if r.returncode == 0:
                twin = _rebased_twin(_git_out("rev-parse", f"{tag}^{{}}"), version)
                if twin:
                    log(f"reconciling {tag} to its rebased twin {twin[:10]}")
                    _git("tag", "-f", tag, twin)
                    _git("push", "--force", "origin", f"refs/tags/{tag}")
                else:
                    phase("reconcile tag to rebased twin", False,
                          "no in-history commit matched - run the release guard")
        phase("push main", r.returncode == 0, r.stderr.strip() or "up to date")
        return 0 if r.returncode == 0 else 1
    finally:
        log(f"elapsed {time.time() - started:.0f}s - removing worktree")
        _git("worktree", "remove", str(worktree), "--force")
        shutil.rmtree(worktree, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
