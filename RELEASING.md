# Releasing & public auto-update

The launcher self-updates by reading a feed (`update.json`) over **HTTPS** — no
insecure dev flags needed (proven in place with the local trusted mirror on
`https://127.0.0.1:8543`). This page turns that local proof into a public,
anywhere auto-update.

## Prerequisites (one time)

1. A GitHub account.
2. Install the GitHub CLI: `winget install GitHub.cli`, then `gh auth login`.
   (Done on this machine: gh 2.97.0, authed as **RBC-X**.)

That's it for publishing. The publish script creates the **public repo itself**
if it doesn't exist — as an **empty repo (release assets only)**: the full
project folder (workspace, tests, build records) is never pushed publicly
unless you explicitly decide to. If you DO want the source up too, that's a
separate deliberate step:

   ```bash
   cd "C:/Users/bsmit/OneDrive/Documents/Minecraft Builder"
   git init && git add -A && git commit -m "AI Modpack Builder"
   gh repo create <owner>/<repo> --public --source . --remote origin --push
   ```

## Publish a release

The signed installer is built by `pyqt/build_installer.py` (or run it with the
version already bumped in `pyqt/product_config.py`). Then publish:

```bash
pyqt/.venv/Scripts/python pyqt/publish_release.py --version 1.0.5 --repo <owner>/<repo>
```

That script (with an authenticated `gh` CLI):

- computes the installer's real SHA-256,
- writes `workspace/update-feed-https/update.json` with the GitHub download URL,
- creates the public repo if missing (empty — release assets only),
- creates the GitHub release and uploads **both** the installer and
  `update.json` as assets (the feed URL only resolves when the feed itself is
  an asset of the latest release).

Without an authenticated `gh` CLI it prints the exact `gh` commands to run
instead. Alternative auth path: create a GitHub token (classic PAT with `repo`
scope, or fine-grained with Contents read/write on the repo) and use the REST
API directly — the feed + installer URLs are the same either way.

If you prefer the web UI: create a Release on the repo, upload
`installers/AI-Modpack-Builder-Setup-<ver>.exe`, tag it `v<ver>`, and copy the
feed at `workspace/update-feed-https/update.json` (rewriting `installerUrl` to
`https://github.com/<owner>/<repo>/releases/download/v<ver>/AI-Modpack-Builder-Setup-<ver>.exe`)
to the repo (e.g. `update.json` at the repo root, served by GitHub Pages or the
release's `latest/download` URL).

## Point the launcher at the public feed

- In the app: **Settings → Updates → Update feed URL** → paste
  `https://github.com/<owner>/<repo>/releases/latest/download/update.json` → Save.
- The installed app is ALREADY pointed at
  `https://github.com/RBC-X/ai-modpack-builder/releases/latest/download/update.json`
  (auto-check on) — verified live with `--check-update`, no dev flags
  (`ok: true, current: 1.0.5, available: false`).
- The local HTTPS mirror (`https://127.0.0.1:8543`, served by
  `pyqt/serve_feed_https.py`) still exists as a fallback: its cert is trusted
  in the machine Root store and a Startup-folder shortcut
  (`pyqt/register_startup_feed.ps1`) relaunches it at every logon. The
  installed app no longer uses it; a backup of the pre-GitHub state is at
  `state.json.bak-local-mirror`.
- Publishing a new version is now: bump `APP_VERSION`, run `build_installer.py`,
  then `publish_release.py --version <v> --repo RBC-X/ai-modpack-builder` —
  the app on this machine (and anyone who sets the feed URL) updates in place.

After that every future release flows to the launcher automatically:
bump `APP_VERSION`, rebuild, publish, done — no manual installs. (The
jump-to-page feature is the next release — 1.0.6 — through this same feed.)

## Verify the loop

```bash
# from a release feed URL, WITHOUT AMB_UPDATE_ALLOW_INSECURE:
"$LOCALAPPDATA/Programs/AI Modpack Builder/AI Modpack Builder.exe" \
  --check-update <feed-url> --apply-update
# then check the verdict:
type "$LOCALAPPDATA/AI Modpack Builder/workspace/update-check.json"
```

## Startup survival (verified + honest gaps)

The local HTTPS mirror is registered as a per-user **Startup-folder shortcut**
(`pyqt/register_startup_feed.ps1` → `%APPDATA%\…\Startup\AI Modpack Builder Update Feed.lnk` →
`pythonw.exe pyqt/serve_feed_https.py`). Verified live on 2026-08-12: killed the
running mirror, relaunched via the shortcut (the exact logon mechanism), and the
feed came back on `https://127.0.0.1:8543` under a fresh pid serving the current
feed. The installed launcher's primary update path is the **public GitHub feed**
(verified: `--check-update` against github.com, `ok: true`, no dev flags) — so
**auto-update keeps working even if the mirror never starts**; the mirror is
only a fallback for the old local feed URL.

Known gaps in the startup path (none break the primary GitHub update path):

1. **The shortcut points into the dev workspace** (`…\OneDrive\Documents\Minecraft
   Builder\pyqt\…`). If that folder is moved/renamed/deleted, the shortcut
   silently fails — Startup shortcuts don't self-heal.
2. **OneDrive files-on-demand**: at logon, if `workspace/feed-tls/cert.pem` /
   `key.pem` are not yet hydrated to local disk, the mirror exits
   ("missing TLS key/cert") and does not retry until the next logon.
3. **Silent failure**: `pythonw` has no console, so a mirror error leaves no
   visible log (the script's own `log_message` is guarded against `None`
   stderr). A task-scheduler equivalent with status would be better, but
   `schtasks /Create` is blocked by machine policy on this box.
4. **Port 8543 collision** would fail the bind — harmless (process exits,
   GitHub path unaffected).
5. **VenV drift**: if `pyqt/.venv` is ever deleted, the shortcut fails silently.
6. **A real reboot is the only full proof.** The logon mechanism itself was
   verified live (shortcut launch), but nothing substitutes for one actual
   reboot to confirm ordering (OneDrive hydration vs. startup-folder run).
