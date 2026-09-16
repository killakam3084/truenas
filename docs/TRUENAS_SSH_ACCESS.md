# TrueNAS SSH Access

SSH administration reaches the TrueNAS host over Tailscale only. Do not create
a router port forward, public DNS record, or reverse-proxy route for TCP/22.

## Current Endpoints

- TrueNAS Tailscale IP: `100.80.126.13`
- MagicDNS name: `truenas-scale.coyote-banfish.ts.net`
- Mac SSH alias: `truenas`

## Apply Host Configuration

First, create the dedicated Mac key if it does not exist:

```sh
ssh-keygen -t ed25519 -a 100 -f ~/.ssh/id_ed25519_truenas -C "truenas_admin@truenas-scale"
```

Copy only the public key to the NAS by a trusted console or UI session. From
the TrueNAS host, run the middleware-managed script with a temporary public-key
file. It preserves existing authorized keys and never accepts private key data.

```sh
sudo /mnt/cell_block_d/repos/truenas/scripts/configure-truenas-ssh.sh \
  --public-key /path/to/id_ed25519_truenas.pub \
  --bind-interface tailscale0
```

Pass `--bind-interface tailscale0` only after confirming that `tailscale0`
exists on the TrueNAS host. Omitting it leaves TrueNAS SSH bound to its normal
interfaces; do not substitute a LAN interface, as that weakens the intended
Tailscale-only boundary.

The script uses `midclt` rather than editing `/etc/ssh/sshd_config`, which
TrueNAS owns and may regenerate. It enables SSH at boot, starts it now,
disables password authentication, and ensures the supplied Ed25519 public key
belongs to `truenas_admin`. This TrueNAS release has no `rootlogin` SSH service
property; with password authentication disabled, root cannot log in by
password. Do not add any public key to the `root` account.

## Verify

Keep the TrueNAS UI or local console open during initial testing. On the Mac:

```sh
tailscale ping truenas-scale.coyote-banfish.ts.net
ssh truenas
```

On the NAS, verify the managed settings and listener:

```sh
sudo midclt call ssh.config
sudo midclt call service.query '[["service","=","ssh"]]'
sudo ss -lntp | grep sshd
```

The SSH client configuration must use the MagicDNS endpoint, the dedicated
identity file, `IdentitiesOnly yes`, and `PasswordAuthentication no`.

## Network Guardrails

- Keep router WAN TCP/22 forwarding absent, including any UPnP-created rule.
- In Tailscale access controls, permit only the intended Mac user/device to
  reach `truenas-scale:22`.
- Do not expose port 22 through `truenas.iillmaticc.link`; that is the web UI
  hostname and remains separate from private host administration.
- Test from an off-LAN Tailscale-connected network after applying the setup.