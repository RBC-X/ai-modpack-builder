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

## One-shot release (`pyqt/release.py`)

The whole clean-checkout build + publish flow is now ONE command, so the
provenance rule is mechanical:

```bash
# 1. bump APP_VERSION in pyqt/product_config.py, write the CHANGELOG entry,
#    commit, and push main — then:
pyqt/.venv/Scripts/python pyqt/release.py
```

It reads `APP_VERSION`, requires a clean tree, ensures `v<ver>` is at HEAD
(creating + pushing the tag if missing), builds the signed installer inside a
throwaway `git worktree` of that exact tag, gates on Authenticode **Valid**,
refreshes the screenshot gallery, publishes the release + `update.json` +
gallery via `publish_release.py`, verifies the public feed serves the new
version, and removes the worktree. `--dry-run` validates the plumbing without
building; `--no-publish` stops after the verified build; `--force-tag` is the
only way to re-point an existing tag (use it to correct a wrong tag, never to
ship).

## Release provenance (source-of-truth rule)

A release's Git tag MUST point at the exact commit that produced its
installer — the tagged source has the same `APP_VERSION`, tests, and fixes the
release notes advertise. On 2026-08-14 the **v1.0.22 tag pointed at a CI
screenshot-bot commit** (`b014885`) whose source still said `APP_VERSION =
"1.0.21"` and lacked the advertised fixes, because the release was published
from the working tree and the tag was created after a bot commit landed.

Correction (documented supersession, no history rewrite):

- `v1.0.22` was force-moved to `113bedd` — the commit whose working tree
  actually produced the published 1.0.22 installer (fixes + tests present,
  `APP_VERSION = "1.0.22"`). GitHub's release page and source archives for
  v1.0.22 now resolve to that commit.
- Rebase reconciliation: if main is ever rebased after a release, the
  release tag lands on an orphaned commit (same tree, new hash). The
  release-guard CI catches this; reconcile by re-pointing the tag at its
  in-history twin (`git tag -f vX.Y.Z <rebased-hash> && git push --force
  origin refs/tags/vX.Y.Z`). The shipped installer is unaffected (trees
  match in source). `release.py` now does this automatically: it rebases
  `-X ours` onto origin/main before tagging and again before its final
  push, then re-points the tag at the rebased twin so the one-command
  flow survives the CI screenshot bot's concurrent commits.
- Every release from 1.0.23 on is **built from a clean checkout of its own
  tag** (`git worktree add` at the tagged commit), so the tag can never drift
  from the shipped bits again. The build reuses the shared toolchain venv via
  `AMB_VENV_PY` — the venv is environment, not source.

To verify any release: `git rev-parse vX.Y.Z^{} ` must match the commit whose
working tree built the installer, and `pyqt/product_config.py` in that commit
must print the same `APP_VERSION` the installer reports.

## Gallery provenance (release assets vs committed screenshots)

- `release.py --guard` additionally verifies that every gallery PNG on the
  release page is byte-for-byte the `screenshots/*.png` committed at the
  release tag (asset `digest` from `gh release view` vs the tag's git blobs —
  no downloads, no extra token scope). This catches the non-deterministic
  toast-render drift class (13-update-toast / 14-settings-updates) where a
  render racing the CI screenshot bot produced released assets that did not
  match the tag. A missing release (tag pushed before publish) is skipped,
  not failed.
- Gallery assets on a release page should be refreshed with the current
  committed set when the README gallery moves on:
  `gh release upload vX.Y.Z screenshots/*.png --clobber`.

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
bump `APP_VERSION`, rebuild, publish, done — no manual installs. (Proven
live: 1.0.5 → 1.0.6 installed itself in place over this feed on 2026-08-12.)

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

### Reboot test: DONE (2026-08-12, real reboot)

One real reboot was performed and verified end-to-end. Evidence
(`%LOCALAPPDATA%\AI Modpack Builder\workspace\reboot-verify.json`):

- Machine rebooted (LastBootUpTime fresh); the HTTPS mirror **did** relaunch at
  logon under a fresh pid (`mirrorListening: true, mirrorFeedVersion 1.0.6,
  mirrorFeedHttp 200` over TLS).
- The installed launcher checked the **public GitHub feed** with no dev flags
  (`appOk: true, appCurrent: 1.0.6, appAvailable: false`).
- **Timing finding**: the logon sequence on this machine is slow — the
  registry Run key wasn't processed until ~2 minutes after boot and the
  Startup-folder items ran ~3–4 minutes in. My first checks (2–3 min after
  boot) were simply too early; the mirror was up by the ~4-minute mark.
- **Hardening from the finding**: the mirror is now ALSO registered in
  `HKCU\...\CurrentVersion\Run` (`pyqt/register_runkey_feed.ps1`) — the
  path proven to be processed early — with the Startup-folder shortcut kept
  as a redundant second hook. The one-shot verifier shortcut
  (`AI Modpack Builder Reboot Verify.lnk`) was removed after use; the
  verifier script (`pyqt/reboot_verify.ps1`) remains for future checks.

Known gaps in the startup path (none break the primary GitHub update path):

1. **Both hooks point into the dev workspace** (`…\OneDrive\Documents\Minecraft
   Builder\pyqt\…`). If that folder is moved/renamed/deleted, both the
   Startup shortcut and the Run-key entry silently fail.
2. **OneDrive files-on-demand**: at logon, if `workspace/feed-tls/cert.pem` /
   `key.pem` are not yet hydrated to local disk, the mirror exits
   ("missing TLS key/cert") and does not retry until the next logon.
3. **Silent failure**: `pythonw` has no console, so a mirror error leaves no
   visible log (the script's own `log_message` is guarded against `None`
   stderr). A task-scheduler equivalent with status would be better, but
   `schtasks /Create` is blocked by machine policy on this box.
4. **Port 8543 collision** would fail the bind — harmless (process exits,
   GitHub path unaffected). With both hooks registered, a healthy logon
   starts the mirror twice; the second instance fails to bind and exits.
5. **VenV drift**: if `pyqt/.venv` is ever deleted, both hooks fail silently.
