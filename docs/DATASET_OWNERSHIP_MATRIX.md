# Dataset Ownership Matrix

Status: first-pass derived from current dataset tree and repo deployment layout.

Updated with verified TrueNAS app runtime details from UI snapshots on 2026-09-05.
Updated with verified host mount roots from CLI on 2026-09-05.

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

## Verified TrueNAS Host Mount Roots

| Path | Purpose | Owner | Notes |
|---|---|---|---|
| /mnt/.ix-apps/app_mounts | Effective host bind-mount roots for installed apps | root:root | Verified from host shell listing |
| /mnt/.ix-apps/app_configs | App chart/config material | root:root | Useful to verify mount definitions and access mode |
| /mnt/.ix-apps/backups | App backup artifacts | root:root | Not part of shared media acl policy |
| /mnt/.ix-apps/docker | Runtime docker data area | root:root | Keep out of media ownership remediation |

Verified app mount directories currently present under /mnt/.ix-apps/app_mounts:

- plex
- qbittorrent
- tailscale
- filebrowser
- netdata
- gluetun-vpn
- grafana

Verified subpaths from host `find` output:

- /mnt/.ix-apps/app_mounts/plex/config
- /mnt/.ix-apps/app_mounts/plex/data
- /mnt/.ix-apps/app_mounts/netdata/cache
- /mnt/.ix-apps/app_mounts/netdata/lib
- /mnt/.ix-apps/app_mounts/netdata/config
- /mnt/.ix-apps/app_mounts/gluetun-vpn/storage_entry
- /mnt/.ix-apps/app_mounts/tailscale/state
- /mnt/.ix-apps/app_mounts/filebrowser/config
- /mnt/.ix-apps/app_mounts/grafana/plugins
- /mnt/.ix-apps/app_mounts/grafana/data
- /mnt/.ix-apps/app_mounts/qbittorrent/config
- /mnt/.ix-apps/app_mounts/qbittorrent/downloads

## Verified Plex Mount and Permission Facts

From sampled app config/rendered compose snippets:

- Plex host state mounts:
  - /mnt/.ix-apps/app_mounts/plex/config -> /config
  - /mnt/.ix-apps/app_mounts/plex/data -> /data
- Plex media host bind:
  - /mnt/cell_block_d/media -> /mnt/cell_block_d/media (read_write)
- Plex and permissions helper run as user 0:0 with apps supplementary group.
- Permission helper targets uid/gid 568 for selected mounted paths and may correct ownership on check mode.

Ownership implication:

- Avoid granting broad write at /mnt/cell_block_d/media root unless intentionally accepting Plex-managed writes across the full tree.
- Prefer splitting writable managed zones under media and scoping Plex RW there.

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

## Verification Checklist for TrueNAS Managed Apps

Run these commands on host to pin exact path mappings and mount modes:

```sh
ls -lahtr /mnt/.ix-apps/app_mounts
ls -lahtr /mnt/.ix-apps/app_configs
```

Note: filename-based search in /mnt/.ix-apps/app_configs may return nothing because app names are often nested under release/version directories.

Use content-based discovery instead:

```sh
grep -RinE 'hostPath|mountPath|app_mounts|/mnt/cell_block_d|/mnt/.ix-apps' /mnt/.ix-apps/app_configs
```

To reduce noise, restrict to user and rendered config files first:

```sh
find /mnt/.ix-apps/app_configs -type f \( -name 'user_config.yaml' -o -path '*/templates/rendered/docker-compose.yaml' \) -print
grep -RinE 'app_mounts|/mnt/cell_block_d|mount_path|"user"|"group_add"' /mnt/.ix-apps/app_configs/*/versions/*/user_config.yaml /mnt/.ix-apps/app_configs/*/versions/*/templates/rendered/docker-compose.yaml
```

Then enumerate concrete mount directories already created:

```sh
find /mnt/.ix-apps/app_mounts -mindepth 1 -maxdepth 2 -type d -print
```

Then, for each verified mount path:

```sh
stat -c '%n %U:%G %a' <path>
getfacl -p <path>
```

And from each app container context, verify effective access only in intended zones.

## Remediation Order

1. Lock system boundary (`/mnt/cell_block_d`) unchanged.
2. Normalize app-state paths under `/mnt/cell_block_d/apps/*` first.
3. Split shared media into immutable vs managed intent explicitly.
4. Apply scoped RW ACL only to managed paths (for example `media/video`).
5. Re-test Plex/Filebrowser operations and ingestion workflows.

## Open Items

- Confirm exact dataset path for prometheus state under /mnt/.ix-apps/app_mounts or app chart values.
- Confirm exact dataset path for grafana state under /mnt/.ix-apps/app_mounts or app chart values.
- Confirm exact dataset path for filebrowser state and replacement migration target (current app marked deprecated).
- Map each official app release name in /mnt/.ix-apps/app_configs to the corresponding directory in /mnt/.ix-apps/app_mounts.
- Confirm whether Plex writes metadata/sidecars into /mnt/cell_block_d/media or keeps metadata fully under /config.
- Decide if `media/video` should be further split into `managed` and `archive` subpaths.
- Replace deprecated filebrowser app with supported alternative before finalizing long-term acl baselines.
