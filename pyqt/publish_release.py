"""Publish a release + HTTPS update feed to GitHub.

Usage:
    pyqt/.venv/Scripts/python pyqt/publish_release.py [--version 1.0.5] [--repo OWNER/REPO] [--tag v1.0.5]
    ... [--assets DIR]      upload every file in DIR (e.g. the screenshots/ gallery) as release assets

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

# Default to the real product version so publishing without --version can
# never target a stale tag (this once silently recreated an old release).
def _default_version() -> str:
    try:
        cfg = (HERE / "product_config.py").read_text("utf-8")
        m = __import__("re").search(r'APP_VERSION\s*=\s*"([^"]+)"', cfg)
        if m:
            return m.group(1)
    except OSError:
        pass
    raise SystemExit("cannot determine APP_VERSION from product_config.py; pass --version")


VERSION = _default_version()
REPO = os.environ.get("GH_REPO", "").strip()
ASSETS_DIR = ""
NOTES = ""


def release_notes() -> str:
    """Feed 'notes' for this version: explicit --notes, else the newest
    CHANGELOG section (markdown) — so the update toast and Settings → Updates
    render real release notes before the user applies."""
    if NOTES.strip():
        return NOTES.strip()
    try:
        text = (ROOT / "CHANGELOG.md").read_text("utf-8")
        # The first "## " section after the intro is the newest entry.
        start = text.find("## ")
        if start < 0:
            return ""
        nxt = text.find("\n## ", start + 3)
        return text[start:nxt if nxt > 0 else None].strip()
    except OSError:
        return ""


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
    global VERSION, REPO, ASSETS_DIR, NOTES
    args = sys.argv[1:]
    if "--version" in args:
        VERSION = args[args.index("--version") + 1]
    if "--repo" in args:
        REPO = args[args.index("--repo") + 1]
    if "--assets" in args:
        ASSETS_DIR = args[args.index("--assets") + 1]
    if "--notes" in args:
        NOTES = args[args.index("--notes") + 1]

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
            "notes": release_notes() or f"{VERSION} release — see the release description on GitHub.",
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

        # Re-publishing the same version (e.g. rebuilt installer, new SHA):
        # drop the old release (keep the tag) so assets are replaced, not
        # duplicated.
        existing = subprocess.run(["gh", "release", "view", "-R", REPO, tag],
                                  capture_output=True, text=True, timeout=60)
        if existing.returncode == 0:
            print(f"release {tag} exists — deleting and recreating with the new assets")
            subprocess.run(["gh", "release", "delete", "-R", REPO, tag, "--yes"],
                           capture_output=True, text=True, timeout=120)

        # Upload BOTH the installer and update.json as release assets — the
        # feed URL (releases/latest/download/update.json) only resolves when
        # the feed itself is an asset of the latest release. -R is required:
        # without a local git repo gh cannot infer the owner/repo.
        release_args = ["gh", "release", "create", "-R", REPO, tag, str(setup), str(feed_path),
                        "--title", f"AI Modpack Builder {VERSION}"]
        if ASSETS_DIR:
            assets = sorted(Path(ASSETS_DIR).glob("*.png")) if Path(ASSETS_DIR).is_dir() else []
            for asset in assets:
                release_args.append(str(asset))
            print(f"extra assets: {len(assets)} images from {ASSETS_DIR}")
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
