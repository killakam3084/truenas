#!/usr/bin/env bash
# Configure the TrueNAS-managed SSH service without editing sshd_config directly.
set -euo pipefail

USER_NAME="truenas_admin"
PUBLIC_KEY_FILE=""
REMOVE_PUBLIC_KEY_FILE=""
BIND_INTERFACE=""

usage() {
  cat <<'EOF'
Usage: sudo scripts/configure-truenas-ssh.sh --public-key /path/to/key.pub [options]

Installs the public key for truenas_admin, enables SSH, disables password
login, and starts the service through TrueNAS middleware.

Options:
  --remove-public-key /path/to/key.pub  Remove this specific existing login key.
  --bind-interface tailscale0           Bind only to an existing host interface.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --public-key)
      PUBLIC_KEY_FILE="${2:-}"
      shift 2
      ;;
    --remove-public-key)
      REMOVE_PUBLIC_KEY_FILE="${2:-}"
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

REMOVE_PUBLIC_KEY=""
if [[ -n "$REMOVE_PUBLIC_KEY_FILE" ]]; then
  if [[ ! -r "$REMOVE_PUBLIC_KEY_FILE" ]]; then
    echo "The removal public key file is not readable: $REMOVE_PUBLIC_KEY_FILE" >&2
    exit 2
  fi
  REMOVE_PUBLIC_KEY="$(tr -d '\r\n' < "$REMOVE_PUBLIC_KEY_FILE")"
  if [[ ! "$REMOVE_PUBLIC_KEY" =~ ^ssh-ed25519\ [A-Za-z0-9+/=]+(\ [[:print:]]+)?$ ]]; then
    echo "The removal key must be a single valid ssh-ed25519 public key." >&2
    exit 2
  fi
  if [[ "$REMOVE_PUBLIC_KEY" == "$PUBLIC_KEY" ]]; then
    echo "The login key and removal key must be different." >&2
    exit 2
  fi
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

USER_UPDATE_PAYLOAD="$(printf '%s' "$USER_JSON" | PUBLIC_KEY="$PUBLIC_KEY" REMOVE_PUBLIC_KEY="$REMOVE_PUBLIC_KEY" python3 -c '
import json
import os
import sys

users = json.load(sys.stdin)
existing = users[0].get("sshpubkey", "").strip()
key = os.environ["PUBLIC_KEY"]
remove_key = os.environ["REMOVE_PUBLIC_KEY"]
keys = [existing_key for existing_key in existing.splitlines() if existing_key != remove_key]
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
if [[ -n "$REMOVE_PUBLIC_KEY" ]]; then
  echo "Removed the requested obsolete login key."
fi
echo "Verify with: midclt call ssh.config"
echo "Verify service with: midclt call service.query '[[\"service\",\"=\",\"ssh\"]]'"