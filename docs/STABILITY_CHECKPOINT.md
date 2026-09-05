# Stability Checkpoint

Known-good operational sequence for keeping host and provisioner state converged.

## Identity Contract

- User: truenas_admin
- UID: 950
- GID: 950
- Home: /home/truenas_admin
- Shell: /usr/bin/zsh

## Standard Sync Flow

Run from the TrueNAS host as truenas_admin.

```sh
cd /mnt/cell_block_d/repos/truenas
git pull origin main
git submodule update --init --recursive
sudo docker rm -f provisioner || true
sudo docker compose -f /mnt/cell_block_d/repos/truenas/truenas-provisioning-image/docker-compose.yml up -d --build provisioner
sudo docker logs --tail 120 provisioner
make pull
```

Expected success indicators:

- Provisioner logs show: Repo already present ... refreshing
- Provisioner logs show: Fast-forwarded to origin/main
- Provisioner logs show: Bootstrap complete
- make pull finishes without host-key, identity, or rebase errors

## Dotfiles Flow

```sh
cd /mnt/cell_block_d/repos/truenas
make dotfiles
source ~/.zshrc
```

Expected behavior:

- Dotfiles apply to /home/truenas_admin (not /root)
- make wrapper proxies normal targets to provisioner as truenas_admin

## Quick Diagnostics

If pull or auth fails, collect these first:

```sh
sudo docker logs --tail 120 provisioner
sudo docker exec --user truenas_admin provisioner id
sudo docker exec --user truenas_admin provisioner zsh --version
sudo docker exec --user truenas_admin provisioner ls -la /home/truenas_admin/.ssh
sudo docker exec --user truenas_admin provisioner git config --global --get core.sshCommand
```

## Rebase State Recovery

If a stale rebase blocks pull on host:

```sh
cd /mnt/cell_block_d/repos/truenas
sudo rm -rf .git/rebase-merge .git/rebase-apply
sudo chown -R truenas_admin:truenas_admin .git
git fetch origin
git rebase origin/main
```

Then rerun the Standard Sync Flow.

## Notes

- Provisioner compose intentionally builds from local source to avoid stale image drift.
- Always include --build when provisioning-image or entrypoint changes.