#!/usr/bin/env bash
# Configure the TrueNAS-managed SSH service without editing sshd_config directly.
set -euo pipefail

USER_NAME="truenas_admin"
PUBLIC_KEY_FILE=""
BIND_INTERFACE=""

usage() {
  cat <<'EOF'
Usage: sudo scripts/configure-truenas-ssh.sh --public-key /path/to/key.pub [--bind-interface tailscale0]

Installs the public key for truenas_admin, enables SSH, disables password
login, and starts the service through TrueNAS middleware. The optional bind
interface must already exist on the host.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-key)
      PUBLIC_KEY_FILE="${2:-}"
      shift 2
      ;;
    --bind-interface)
      BIND_INTERFACE="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ $(id -u) -ne 0 ]]; then
  echo "Run this script with sudo on the TrueNAS host." >&2
  exit 1
fi

if ! command -v midclt >/dev/null; then
  echo "TrueNAS middleware CLI (midclt) is unavailable." >&2
  exit 1
fi

if [[ -z "$PUBLIC_KEY_FILE" || ! -r "$PUBLIC_KEY_FILE" ]]; then
  echo "Provide a readable public key file with --public-key." >&2
  exit 2
fi

PUBLIC_KEY="$(tr -d '\r\n' < "$PUBLIC_KEY_FILE")"
if [[ ! "$PUBLIC_KEY" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [[:print:]]+)?$ ]]; then
  echo "The public key must be a single valid ssh-ed25519 public key." >&2
  exit 2
fi

if [[ -n "$BIND_INTERFACE" ]] && ! ip link show dev "$BIND_INTERFACE" >/dev/null 2>&1; then
  echo "Bind interface does not exist: $BIND_INTERFACE" >&2
  exit 2
fi

USER_JSON="$(midclt call user.query "[[\"username\",\"=\",\"$USER_NAME\"]]")"
USER_ID="$(printf '%s' "$USER_JSON" | python3 -c 'import json, sys; users = json.load(sys.stdin); print(users[0]["id"] if len(users) == 1 else "")')"
if [[ -z "$USER_ID" ]]; then
  echo "Expected exactly one user named $USER_NAME." >&2
  exit 1
fi

USER_UPDATE_PAYLOAD="$(printf '%s' "$USER_JSON" | PUBLIC_KEY="$PUBLIC_KEY" python3 -c '
import json
import os
import sys

users = json.load(sys.stdin)
existing = users[0].get("sshpubkey", "").strip()
key = os.environ["PUBLIC_KEY"]
keys = existing.splitlines()
if key not in keys:
    keys.append(key)
print(json.dumps({"sshpubkey": "\n".join(keys)}))
')"

SSH_UPDATE_PAYLOAD='{"passwordauth":false}'
if [[ -n "$BIND_INTERFACE" ]]; then
  SSH_UPDATE_PAYLOAD="$(BIND_INTERFACE="$BIND_INTERFACE" python3 -c 'import json, os; print(json.dumps({"passwordauth": False, "bindiface": [os.environ["BIND_INTERFACE"]]}))')"
fi

midclt call user.update "$USER_ID" "$USER_UPDATE_PAYLOAD" >/dev/null
midclt call ssh.update "$SSH_UPDATE_PAYLOAD" >/dev/null
midclt call service.update ssh '{"enable":true}' >/dev/null
midclt call service.start ssh >/dev/null

echo "SSH access configured for $USER_NAME."
echo "Verify with: midclt call ssh.config"
echo "Verify service with: midclt call service.query '[[\"service\",\"=\",\"ssh\"]]'"