# Snapshots & Last Known Good

## Snapshots

Snapshots are **content-addressed pack-state manifests**, not binary copies.
Each snapshot (`<build>/snapshots/<id>.json`) records everything needed to
deterministically reproduce the pack:

- identity + requirements (MC version, loader, RAM, shaders, visuals)
- exact selections: provider/project/file ids, version numbers, file SHA-1,
  feature ids, reasons, client/server flags
- shader + resource-pack choices
- **config file hashes** (so config drift is detectable without duplicating
  the files)
- JVM args

`create_snapshot(build_dir, rec, label, kind)` writes the manifest.
`restore_from_snapshot(...)` builds a *candidate* record — it never mutates
the working pack; the caller decides whether to promote.

## Last Known Good

Whenever a pack validates — a build passes, a retest passes, or a candidate
is promoted — the engine marks it **Last Known Good** (one per pack; a newer
LKG supersedes the old one). `restore_last_known_good()` restores the most
recent validated state with one call, and the Pack Detail → Settings view
shows a prominent **↺ RESTORE LAST KNOWN GOOD** button.

## Safety rules

- Restoring always snapshots the *current* state first — nothing is lost.
- The pack's working state is never mutated by planning or snapshotting.
- Auto-snapshots are taken before every AI edit (`before-ai-edit`), and the
  transactional apply only promotes a candidate that validated.

Implementation: `engine/snapshots.py` (unit-tested: write/list/restore,
one-per-pack LKG with supersede, restore records its origin).
