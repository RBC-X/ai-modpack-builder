"""Publish a release + HTTPS update feed to GitHub.

Usage:
    pyqt/.venv/Scripts/python pyqt/publish_release.py [--version 1.0.5] [--repo OWNER/REPO] [--tag v1.0.5]

What it does:
  1. Computes the installer's real SHA-256.
  2. Generates workspace/update-feed-https/update.json pointing at the GitHub
     release download URL (https://github.com/<owner>/<repo>/releases/download/<tag>/...).
  3. If the GitHub CLI is installed and authenticated: uploads the installer,
     creates the release, and prints the feed URL to set in Settings → Updates.
     Otherwise it prints the exact `gh` commands to run — this machine has no
     `gh` CLI or git repo yet, so the public step needs your GitHub account.

The installed launcher already trusts HTTPS feeds with no flags (proven with
the local mirror on 127.0.0.1:8543). Pointing Settings → Updates at the
published GitHub feed makes auto-update work from anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

VERSION = "1.0.5"
REPO = os.environ.get("GH_REPO", "").strip()


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gh_available() -> bool:
    try:
        return subprocess.run(["gh", "--version"], capture_output=True, timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def gh_authed() -> bool:
    try:
        r = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and "Logged in" in r.stdout
    except Exception:  # noqa: BLE001
        return False


def main() -> int:
    global VERSION, REPO
    args = sys.argv[1:]
    if "--version" in args:
        VERSION = args[args.index("--version") + 1]
    if "--repo" in args:
        REPO = args[args.index("--repo") + 1]

    setup = ROOT / "installers" / f"AI-Modpack-Builder-Setup-{VERSION}.exe"
    if not setup.exists():
        print(f"installer not found: {setup}")
        return 1
    sha = sha256_of(setup)
    size = setup.stat().st_size
    print(f"installer: {setup.name} ({size:,} bytes)")
    print(f"sha256:    {sha}")

    feed_dir = ROOT / "workspace" / "update-feed-https"
    feed_dir.mkdir(parents=True, exist_ok=True)
    tag = f"v{VERSION}"

    if REPO:
        base = f"https://github.com/{REPO}/releases/download/{tag}"
        installer_url = f"{base}/AI-Modpack-Builder-Setup-{VERSION}.exe"
        feed = {
            "version": VERSION,
            "notes": f"{VERSION} release — see the release description on GitHub.",
            "installerUrl": installer_url,
            "installerSha256": sha,
        }
        feed_path = feed_dir / "update.json"
        feed_path.write_text(json.dumps(feed, indent=2), "utf-8")
        print(f"feed written: {feed_path}  (installerUrl {installer_url})")

        if not gh_available() or not gh_authed():
            print("\nNo authenticated GitHub CLI — run these commands yourself:")
            print(f"  gh repo create {REPO} --public")
            print(f"  gh release create {tag} \\")
            print(f"      '{setup}' '{feed_path}' --title 'AI Modpack Builder {VERSION}' \\")
            print(f"      --notes-file RELEASING.md")
            print(f"  then set Settings -> Updates -> feed URL to:")
            print(f"      https://github.com/{REPO}/releases/latest/download/update.json")
            return 2

        # Create the public repo if it does not exist yet. It stays empty
        # (release assets only) — the full source tree is never pushed unless
        # explicitly asked for.
        view = subprocess.run(["gh", "repo", "view", REPO],
                              capture_output=True, text=True, timeout=60)
        if view.returncode != 0:
            print(f"creating public repo {REPO} ...")
            r = subprocess.run(
                ["gh", "repo", "create", REPO, "--public",
                 "--description", "AI Modpack Builder — signed installer + auto-update feed (release assets only)"],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                print("gh repo create failed:", r.stderr)
                return 1
            print("repo created:", (r.stdout or r.stderr).strip())

        # Upload BOTH the installer and update.json as release assets — the
        # feed URL (releases/latest/download/update.json) only resolves when
        # the feed itself is an asset of the latest release. -R is required:
        # without a local git repo gh cannot infer the owner/repo.
        release_args = ["gh", "release", "create", "-R", REPO, tag, str(setup), str(feed_path),
                        "--title", f"AI Modpack Builder {VERSION}"]
        notes_file = ROOT / "RELEASING.md"
        if notes_file.exists():
            release_args += ["--notes-file", str(notes_file)]
        r = subprocess.run(release_args, capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            print("gh release create failed:", r.stderr)
            return 1
        print("release created:", (r.stdout or r.stderr).strip())
        print("feed URL for Settings -> Updates:")
        print(f"  https://github.com/{REPO}/releases/latest/download/update.json")
        return 0

    # No repo given: print the exact feed so the user can host it anywhere.
    print("\nNo --repo given. For any HTTPS host, the feed is:")
    print(json.dumps({"version": VERSION, "installerUrl": "<HTTPS URL of the installer>",
                      "installerSha256": sha}, indent=2))
    print("Host feed + installer together; set the feed URL in Settings -> Updates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
