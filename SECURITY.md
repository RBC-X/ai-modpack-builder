# Security

Every downloaded file is treated as **untrusted input**. The safety properties
below are implemented (with tests) rather than promised.

## Downloads (`pyqt/engine/downloads.py`, `pyqt/engine/providers/`)

- **Size limits**: per-file (`maxBytes`) and per-build total budget
  (`maxTotalDownloadMB`); aborts mid-stream when exceeded.
- **Hash verification**: SHA1 checked against provider-declared hashes; the
  file is deleted on mismatch.
- **Sanitized filenames**: provider-controlled names are scrubbed of path
  separators, drive letters and control characters before touching the disk.
- **Hashing at rest**: every downloaded jar's SHA1 is recorded in the build
  record.

## ZIP safety (`pyqt/engine/imports.py`, `pyqt/engine/exports.py`)

- Rejects entries with absolute paths, drive letters or `..` traversal
  (verified: target must stay under the destination).
- CRC verification per entry; size/entry-count caps against zip bombs;
  supports stored + deflate only.

## Process isolation (`pyqt/engine/process.py`, `pyqt/engine/tester.py`)

- Every Minecraft/Java process runs with `cwd` = the isolated instance; the
  user's real `.minecraft` is never touched (only an explicit import would).
- Hard timeouts kill the **whole process tree** (`taskkill /T /F` on Windows,
  process-group kill on POSIX).
- Logs are captured, never executed.

## Instance isolation (`pyqt/engine/instance.py`)

- Fresh game dir per build under `workspace/builds/<id>/instance/`.
- Worlds are never deleted; no destructive operation runs outside the workspace.
- No scripts from mod pages are ever executed; the only things we run are the
  official Mojang/Fabric/Quilt/Forge artifacts we downloaded ourselves.

## Credentials

- CurseForge API key: env `CF_API_KEY` takes precedence; otherwise a per-user
  key is protected with Windows DPAPI, with an optional publisher key embedded
  only in signed release bundles. It is **never logged**, never returned to
  the UI, and never written into build records or exports.
- Microsoft account: the launcher uses Microsoft's system-browser authorization
  code flow with PKCE, a random CSRF state, and a temporary localhost callback,
  then exchanges the resulting token through Xbox Live and Minecraft Services.
  The refresh credential is encrypted with Windows DPAPI for the current
  Windows user and is never stored in `state.json`, the engine, build records,
  exports, or logs. Short-lived game tokens are redacted from launch logs.

## Known caveats

- Hashes are SHA1 as published by providers (their scheme); we verify against
  their declared value.
- Automated tests never perform a real Microsoft sign-in. The OAuth consent
  and ownership check require the user to complete Microsoft's browser flow;
  protocol handling, DPAPI round-tripping, launch argument propagation, input
  validation, and token-log redaction are tested without account credentials.
