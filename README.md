# truenas

Monorepo (git submodule pattern) for all TrueNAS SCALE configuration, custom app definitions, and provisioning tooling.

## Stability Checkpoint

For the known-good host/provisioner convergence workflow, see [docs/STABILITY_CHECKPOINT.md](docs/STABILITY_CHECKPOINT.md).

## Dataset Ownership

For shared-media ownership policy and remediation phases, see [docs/DATASET_OWNERSHIP_PLAN.md](docs/DATASET_OWNERSHIP_PLAN.md).

## Submodules

| Submodule | Purpose |
|---|---|
| [`certrenew`](certrenew/) | Let's Encrypt certificate renewal via Route53 DNS challenge |
| [`port-sync`](port-sync/) | VPN port sync + qBittorrent/gluetun compose stack |
| [`rarclean`](rarclean/) | qBittorrent post-download RAR extraction / organization |
| [`rss-curator`](rss-curator/) | RSS-driven torrent automation + web UI |
| [`truenas-nginx-config`](truenas-nginx-config/) | nginx-proxy reverse proxy configuration (volume-mounted into container) |
| [`truenas-provisioning-image`](truenas-provisioning-image/) | Toolbox container — bootstraps this repo onto the NAS, provides git/make/docker/infisical CLI |

## Bootstrap (fresh clone)

```sh
git clone --recurse-submodules git@github.com:killakam3084/truenas.git
cd truenas
make init
```

## Make Targets

All targets are run from inside the provisioner container, or via the `make` alias in `truenas_admin`'s shell (which proxies to the provisioner automatically).

| Target | Description |
|---|---|
| `make init` | Initialize submodules after a plain `git clone` |
| `make pull` | Pull latest on parent repo + all submodules, then advance pinned commits |
| `make nginx-up` | Start nginx-proxy stack |
| `make nginx-down` | Stop nginx-proxy stack |
| `make nginx-reload` | Pull + send HUP to nginx-proxy container |
| `make infisical-up` | Start Infisical stack |
| `make infisical-down` | Stop Infisical stack |
| `make roon-up` | Start RoonServer stack |
| `make roon-down` | Stop RoonServer stack |
| `make roon-restart` | Restart RoonServer (down + up -d) |
| `make certrenew-dry-run` | Dry-run cert renewal (prints plan, no changes) |
| `make certrenew-run` | Live cert renewal |
| `make rss-curator-up` | Deploy rss-curator stack with Infisical secrets |
| `make rss-curator-down` | Stop rss-curator stack |
| `make rarclean-up` | Deploy rarclean with Infisical secrets |
| `make rarclean-down` | Stop rarclean |
| `make qbittorrent-up` | Deploy gluetun + qBittorrent + port-sync stack (installs VueTorrent first) |
| `make qbittorrent-down` | Stop qbittorrent-vpn stack |
| `make vuetorrent-install` | Install/upgrade VueTorrent theme (no-op if already at pinned version) |
| `make dotfiles` | Apply `truenas_admin` dotfiles on the host |

## Healthchecks

Production compose stacks now include healthchecks for long-running services:

- `nginx-proxy`: HTTP liveness probe via localhost
- `rss-curator`: `/api/health` endpoint probe
- `gluetun`: built-in health server probe (`127.0.0.1:9999`)
- `qbittorrent`: `/api/v2/app/version` probe
- `qbittorrent-port-sync`: process liveness probe
- `infisical-backend`: `/api/status` endpoint probe
- `infisical-redis`: `redis-cli ping`
- `infisical-db`: `pg_isready` probe
- `roonserver`: `pgrep` process probe

## Secrets (Infisical)

Secrets are injected at runtime via [Infisical](https://infisical.com/) (self-hosted at `infisical.iillmaticc.link`). Each app that requires secrets has a corresponding Infisical project.

Each app reads its Infisical credentials from a `.env` file on the host at `/mnt/cell_block_d/apps/<app>/.env`:

```sh
INFISICAL_TOKEN=st.xxxxxxxx...
INFISICAL_PROJECT_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
INFISICAL_ENV=prod
```

See each app's `.env.example` (or `.env.truenas.example`) for the full list of required variables.

## VueTorrent Theme

VueTorrent version is pinned in [`themes/vuetorrent.version`](themes/vuetorrent.version). To upgrade:

1. Edit `themes/vuetorrent.version` with the new version
2. Commit and push
3. Run `make vuetorrent-install` on the NAS

No container restart needed — qBittorrent serves the theme directory as static files.

## Host Layout

```
/mnt/cell_block_d/
  repos/
    truenas/              ← this repo, managed by provisioning container
  apps/
    certrenew/            .env  (INFISICAL_TOKEN, INFISICAL_PROJECT_ID, ...)
    rarclean/             .env
    rss-curator/          .env
    qbittorrent-vpn/      .env
                          config/themes/vuetorrent/   ← installed by make vuetorrent-install
    infisical/            .env
    roon/                 app/ data/ backups/
    nginx-proxy/          (runtime state)
```

## Provisioning Container

The `truenas-provisioning-image` container runs as a TrueNAS custom app. On startup it clones/pulls
this monorepo to `/mnt/cell_block_d/repos/truenas` and keeps a shell available for ad-hoc tasks.
It mounts `/var/run/docker.sock` for docker/compose CLI access and `/home/truenas_admin/.ssh` for git auth.

```sh
# Enter provisioner shell
sudo docker exec -it provisioner bash

# Or use the truenas_admin alias
prov
```

## truenas_admin Dotfiles

Shell environment for `truenas_admin` is managed in [`dotfiles/`](dotfiles/). Apply with:

```sh
make dotfiles
```

The `make` alias in `.zshrc` proxies all `make` calls through the provisioner container, so commands like `make vuetorrent-install` work from the host shell without entering the provisioner.
