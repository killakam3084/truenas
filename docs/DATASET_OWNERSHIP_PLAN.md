# Dataset Ownership Plan

Purpose: define a stable ownership model for shared media datasets across custom stacks and TrueNAS community apps.

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

## Guardrails

- Do not make apps a global owner of all datasets.
- Do not make truenas_admin owner of community app internals unless app docs require it.
- Do not auto-remediate permissions in deploy scripts until the matrix is stable.
- Do not grant full RW on top-level /media when only subpaths require management actions.

## Next Step

Create a repo-local file docs/DATASET_OWNERSHIP_MATRIX.md and fill real paths for all active services before applying ACL changes.