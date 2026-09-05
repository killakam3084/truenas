# Dataset Ownership Plan

Purpose: define a stable ownership model for shared media datasets across custom stacks and TrueNAS community apps.

## Observed Baseline (2026-09-05)

From current TrueNAS UI snapshots:

- Dataset cell_block_d
  - Owner: root:root
  - Permissions style: Unix permissions
  - Marked as used by: prometheus and system dataset

- Dataset media
  - Owner: truenas_admin:truenas_admin
  - Marked as used by: plex, filebrowser
  - ACL model: NFSv4-style entries shown in UI

- Datasets media/audio and media/video
  - Owner: truenas_admin:truenas_admin
  - ACL entries include apps group/user RW-level access in current state

Interpretation:

- This is already a mixed ownership model (root for top-level system dataset, truenas_admin for media datasets).
- Community apps appear to be granted broad write ability on media via ACL, which can work, but should be narrowed to managed paths where possible.

## Core Model

- Keep TrueNAS community app state owned by apps:568:568.
- Keep repo, automation, and provisioning paths owned by truenas_admin:950:950.
- Treat shared media datasets as a governed boundary using ACLs and least privilege.

## Shared Dataset Strategy

Use one of these patterns per dataset:

1. Read-mostly media library
- Owner/group: keep current storage owner/group (do not churn ownership)
- Access: apps read-only, truenas_admin read-write only when needed
- Enforcement: ACL entries preferred over recursive chmod/chown

2. App write staging area (watch, ingest, transcode cache)
- Owner/group: apps:568:568 or dedicated app group
- Access: app read-write, truenas_admin read-write for ops
- Enforcement: ACL with default entries for inherited files

3. Automation output area (post-processing)
- Owner/group: truenas_admin:950:950 or dedicated automation group
- Access: automation read-write, apps read-only unless write is required

4. App-managed library (full RW app behavior)
- Owner/group: keep stable owner; avoid frequent ownership flips
- Access: designated app(s) read-write, other consumers read-only
- Enforcement: explicit ACL entries per app, default ACLs for inheritance
- Use when app needs to create, rename, move, delete, or metadata-write in-place

## App Capability Profiles

Use explicit profiles so permissions match behavior instead of assumptions.

1. Full RW manager (example: Plex, Filebrowser in management mode)
- Needs: create/rename/move/delete files and folders, write sidecar metadata
- Recommended scope: only on managed paths (for example media staging or curated library subset)

2. Read-only indexer/streamer
- Needs: traverse + read only
- Recommended scope: main immutable libraries

3. Service-state writer
- Needs: RW only in app config/data path, no writes to shared media

## Managed vs Immutable Libraries

Split shared media paths to avoid global RW grants:

- Immutable library: app access is read-only; ingestion handled by automation/manual process.
- Managed library: selected app has RW for operational workflows (organize, cleanup, metadata).

This avoids giving broad RW to all media while still supporting apps that truly need it.

## Ownership Matrix Template

Fill this for each critical path:

| Path | Data Type | Primary Writer | Required Readers | Mode | ACL Policy | Notes |
|---|---|---|---|---|---|---|
| /mnt/cell_block_d/media/audio/music | Immutable library | truenas_admin/manual ingest | roon, plex, filebrowser | RO for apps | apps:rx, truenas_admin:rwx | No app writes |
| /mnt/cell_block_d/media/video | Managed library | plex/filebrowser | truenas_admin, other media apps | RW for manager app(s) | apps:rwx (scoped), truenas_admin:rwx, others:rx | Limit RW to specific app paths if possible |
| /mnt/cell_block_d/apps/qbittorrent-vpn/downloads | Staging | qbittorrent (app) | rarclean, truenas_admin | RW shared | apps:rwx, truenas_admin:rwx | Inherit defaults |
| /mnt/cell_block_d/apps/rss-curator | App state | custom stack | truenas_admin | RW app | app user rwx | Not shared to community apps |

## Audit Commands (Read-Only)

Run on host to capture current state before remediation:

```sh
id truenas_admin
id apps
getent passwd truenas_admin
getent passwd apps

find /mnt/cell_block_d/media -maxdepth 3 -type d -print
find /mnt/cell_block_d/apps -maxdepth 3 -type d -print

stat -c '%n %u:%g %a' /mnt/cell_block_d/media /mnt/cell_block_d/apps
getfacl -p /mnt/cell_block_d/media
getfacl -p /mnt/cell_block_d/apps
```

## Remediation Phases

1. Baseline
- Inventory datasets and classify each as library, staging, or app state.
- Fill ownership matrix for all paths touched by Plex, Tailscale, Filebrowser, Prometheus, Roon, qBittorrent, rarclean, rss-curator.

2. Policy Definition
- For each path define:
  - single primary writer
  - secondary readers/writers
  - ro/rw requirement
  - inheritance behavior for new files
  - whether path is immutable or managed library

3. ACL Application
- Apply ACLs path-by-path, smallest blast radius first.
- Prefer setfacl default ACLs for directories that receive new files.
- Avoid recursive chown across large libraries unless absolutely necessary.

4. Validation
- Validate from each runtime context:
  - host shell (truenas_admin)
  - provisioner shell (truenas_admin)
  - TrueNAS community apps (apps user)
- Check read/write behavior matches matrix intent.

5. Drift Prevention
- Add quarterly audit command run and compare against matrix.
- Add a lightweight Make target or script to print owners/ACLs for key paths.

## Immediate Course of Action (Shared Media Focus)

1. Freeze top-level ownership boundaries
- Keep cell_block_d as root-owned system boundary.
- Keep media as truenas_admin-owned unless a strong operational reason requires change.

2. Split media into intent-based paths
- Immutable library paths: read-only for apps that only index/stream.
- Managed library paths: RW only for apps that must organize or mutate files (for example Plex or Filebrowser in manager mode).

3. Reduce broad RW ACL exposure
- Replace global RW grants on broad media roots with scoped RW on specific managed subpaths.
- Keep explicit default ACL inheritance only where new files must remain app-manageable.

4. Separate app state from media data
- Keep app internals/config/state under apps-owned datasets.
- Use media datasets for content only, with explicit consumer ACLs.

5. Validate by runtime role
- truenas_admin host shell: full expected operations on media.
- provisioner truenas_admin context: git/make flows unaffected.
- apps runtime (Plex/Filebrowser): verify only intended write zones are writable.

## Guardrails

- Do not make apps a global owner of all datasets.
- Do not make truenas_admin owner of community app internals unless app docs require it.
- Do not auto-remediate permissions in deploy scripts until the matrix is stable.
- Do not grant full RW on top-level /media when only subpaths require management actions.

## Next Step

Use [docs/DATASET_OWNERSHIP_MATRIX.md](DATASET_OWNERSHIP_MATRIX.md) to track real paths for all active services before applying ACL changes.

## Step-by-Step Action Plan

Use this sequence in the next working session.

### Phase 0: Pre-Flight Safety

1. Confirm clean repo state and latest docs.
2. Rotate any previously exposed secrets (for example Tailscale auth key) before further output sharing.
3. Capture a fresh snapshot or backup checkpoint for media datasets before permission edits.

Success criteria:

- Snapshot exists for rollback.
- No active secret exposure in shared logs.

### Phase 1: Confirm Active vs Legacy App Mounts

1. Validate qbittorrent and gluetun-vpn app mounts are orphaned from TrueNAS managed apps.
2. If orphaned, remove those app_mounts directories.
3. Re-run mount inventory to confirm only active managed-app mounts remain.

Success criteria:

- Active managed-app mount list excludes legacy qbittorrent/gluetun-vpn cruft.

Rollback point:

- Restore removed directories from snapshot if active dependency is discovered.

### Phase 2: Classify Media Paths by Mutation Need

1. Apply mutation-based rule from matrix notes:
  - if app must rename/move/delete/write metadata, classify path as managed.
  - if app never mutates data, classify path as immutable.
2. For current reality, assume Plex and file-management app paths are managed unless proven otherwise.
3. Mark tentative classifications directly in the ownership matrix.

Success criteria:

- Every media path used by apps has explicit managed or immutable classification.

### Phase 3: Define Target ACL Intent Per Path

1. For each managed path:
  - RW for manager apps (Plex and current file manager)
  - RO for non-manager consumers
2. For each immutable path:
  - RO for all app consumers
  - RW only for approved ingest/ops flows
3. Keep app state mounts under apps-owned app_mounts paths.

Success criteria:

- Matrix row for each path includes concrete writer set and reader set.

### Phase 4: Pilot on Smallest Managed Path

1. Select a low-risk pilot path (for example one video managed subpath).
2. Apply ACL changes only to pilot path.
3. Validate:
  - Plex write actions still work where expected.
  - RO paths reject unintended writes.
  - Roon and other readers can still index/stream.

Success criteria:

- Functional app behavior unchanged where intended.
- No unintended write capability outside pilot scope.

Rollback point:

- Revert pilot path ACL using snapshot or recorded previous ACL.

### Phase 5: Expand Incrementally

1. Roll out ACL policy path-by-path from pilot to remaining managed paths.
2. Re-test after each expansion step.
3. Keep change log notes in matrix for what changed and when.

Success criteria:

- All target paths match intended ACL policy.
- No app regressions.

### Phase 6: Finalize and Harden

1. Replace deprecated Filebrowser with supported successor.
2. Re-map successor mounts and update matrix rows.
3. Add recurring permission audit task (quarterly) using verification checklist commands.

Success criteria:

- Deprecated app removed from active policy surface.
- Matrix reflects only active apps and current mounts.

## Quick Start Commands (Session Opening)

```sh
cd /mnt/cell_block_d/repos/truenas
git pull origin main

# verify current mounts
sudo find /mnt/.ix-apps/app_mounts -mindepth 1 -maxdepth 2 -type d -print

# run latest-version mapping extractor from matrix notes
# (copy from docs/DATASET_OWNERSHIP_MATRIX.md)
```