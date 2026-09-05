# Dataset Ownership Matrix

Status: first-pass derived from current dataset tree and repo deployment layout.

Updated with verified TrueNAS app runtime details from UI snapshots on 2026-09-05.

## Legend

- Class: immutable-library, managed-library, staging, app-state, system
- Access profile: ro-indexer, rw-manager, rw-service-state
- Runtime principals:
  - truenas_admin (uid:gid 950:950)
  - apps (uid:gid 568:568)

## Matrix

| Path | Class | Primary Writer | Required Readers | App RW Needed | Target ACL Intent | Notes |
|---|---|---|---|---|---|---|
| /mnt/cell_block_d | system | system/root | all datasets traverse via child mounts | No | Keep root:root boundary; avoid broad ACL edits here | Used by system dataset and prometheus per UI |
| /mnt/cell_block_d/media | shared-root | mixed | plex, filebrowser, roon, host workflows | Scoped only | Keep as boundary; avoid global rw-for-all-apps | Parent for audio/video |
| /mnt/cell_block_d/media/audio | immutable-library | truenas_admin/manual ingest | roon, plex, filebrowser | Usually No | apps/group read+traverse, truenas_admin full | If metadata writes are needed, split to managed subpath |
| /mnt/cell_block_d/media/video | managed-library | plex/filebrowser | truenas_admin, playback/index clients | Yes | scoped app rw + default ACL inheritance where needed | Visible path confirmed in UI: cell_block_d/media/video |
| /mnt/cell_block_d/apps/qbittorrent-vpn/downloads | staging | qbittorrent app flow | rarclean, truenas_admin | Yes | apps rw, truenas_admin rw, inherit defaults | High-churn write path |
| /mnt/cell_block_d/apps/rarclean | app-state | rarclean service | truenas_admin ops | Service only | service user rw, no broad media grants | Keep app state separate from library content |
| /mnt/cell_block_d/apps/rss-curator | app-state | rss-curator service | truenas_admin ops | Service only | service user rw, no broad media grants | Keep isolated from community app ACLs |
| /mnt/cell_block_d/apps/roon | app-state | roon service | truenas_admin ops | Service only | service user rw, media mounts ro unless explicitly required | Includes data and backups |
| /mnt/cell_block_d/apps/plex | app-state | plex app | truenas_admin ops | Yes (state only) | apps rw for app internals; avoid coupling with /media root rw | Path may differ by chart; verify in TrueNAS app config |
| /mnt/cell_block_d/apps/filebrowser | app-state | filebrowser app | truenas_admin ops | Yes (state only) | apps rw for app internals | Path may differ by chart; verify in TrueNAS app config |
| /mnt/cell_block_d/apps/prometheus | app-state | prometheus app | truenas_admin ops | Yes (state only) | apps rw for app internals | Confirm actual volume path from app chart |

## Verified TrueNAS App Runtime Context

| App | Runtime User/Group | Supplementary Groups | Notable Capability/Behavior | Ownership Impact |
|---|---|---|---|---|
| filebrowser | 568:568 (apps) | apps | Deprecated app notice shown; init also 568:568 | Treat as apps-owned state path; plan migration/replacement to reduce future drift risk |
| grafana | 568:568 (apps) | apps | Permissions/init container runs as root with supplementary apps | Keep app state apps-writable; avoid broad media rw unless explicit use-case |
| prometheus | 568:568 (apps) | apps | Permissions/init container runs as root with supplementary apps | Keep app state apps-writable; avoid cross-granting into media without need |
| plex | root:root | apps | Host device /dev/dri passed rw; capabilities include CHOWN, DAC_OVERRIDE, FOWNER | Scope plex rw to managed media zones only; root runtime increases blast radius if acl scope is too broad |
| tailscale | user unknown / group unknown | apps | Permissions container root; capabilities include CHOWN and DAC_OVERRIDE | Keep isolated from media datasets; no broad file dataset grants needed |
| netdata | user unknown / group unknown | apps, docker | Host PID namespace and host socket/system mounts (mostly ro) | Monitoring app should not require media rw; keep dataset access minimal |

## Verified Policy Adjustments

- Plex is the highest-permission media manager in current official apps, so managed-library scope should be explicit and narrow.
- apps uid/gid 568 is validated for filebrowser, grafana, and prometheus runtime contexts.
- Monitoring and network utility apps (netdata, tailscale) should remain out of shared-media rw policy.

## Verification Checklist Per Row

- Confirm path exists: `test -d <path>`
- Capture owner/mode: `stat -c '%n %U:%G %a' <path>`
- Capture ACL: `getfacl -p <path>`
- Confirm consuming app mount mode (ro/rw) in app config or compose
- Run app-specific read/write probe in intended writable paths only

## Remediation Order

1. Lock system boundary (`/mnt/cell_block_d`) unchanged.
2. Normalize app-state paths under `/mnt/cell_block_d/apps/*` first.
3. Split shared media into immutable vs managed intent explicitly.
4. Apply scoped RW ACL only to managed paths (for example `media/video`).
5. Re-test Plex/Filebrowser operations and ingestion workflows.

## Open Items

- Confirm actual app dataset mount paths for plex, filebrowser, prometheus in TrueNAS app settings.
- Confirm whether Plex metadata writes occur inside library path or only app state path.
- Decide if `media/video` should be further split into `managed` and `archive` subpaths.
- Replace deprecated filebrowser app with supported alternative before finalizing long-term acl baselines.
