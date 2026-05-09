# truenas

Monorepo (git submodule pattern) for all TrueNAS SCALE configuration, custom app definitions, and provisioning tooling.

## Submodules

| Submodule | Purpose |
|---|---|
| [`certrenew`](certrenew/) | Let's Encrypt certificate renewal container |
| [`port-sync`](port-sync/) | Port synchronization utility |
| [`rarclean`](rarclean/) | qBittorrent post-download RAR extraction / organization |
| [`rss-curator`](rss-curator/) | RSS-driven torrent automation + web UI |
| [`truenas-nginx-config`](truenas-nginx-config/) | nginx-proxy reverse proxy configuration (volume-mounted into container) |
| [`truenas-provisioning-image`](truenas-provisioning-image/) | Toolbox container — bootstraps this repo onto the NAS, provides git/make/docker CLI |

## Bootstrap (fresh clone)

```sh
git clone --recurse-submodules git@github.com:killakam3084/truenas.git
cd truenas
```

## Common Tasks

```sh
make init          # initialize submodules after a plain git clone
make pull          # pull latest on all submodules + advance pinned commits
make nginx-reload  # pull + send HUP to nginx-proxy container
```

## Host Layout

```
/mnt/cell_block_d/
  repos/
    truenas/          ← this repo, managed by provisioning container
  apps/
    certrenew/        config.json
    rarclean/         config.json
    rss-curator/      .env
    nginx-proxy/      (runtime state)
```

## Provisioning Container

The `truenas-provisioning-image` container runs as a TrueNAS custom app. On startup it clones/pulls
this monorepo to `/mnt/cell_block_d/repos/truenas` and keeps a shell available for ad-hoc tasks
(`docker exec -it provisioner sh`). It mounts `/var/run/docker.sock` for docker/compose CLI access
and `/root/.ssh` for git authentication.
