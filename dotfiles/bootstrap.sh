#!/usr/bin/env bash
# bootstrap.sh — provision truenas_admin shell environment from git
# Run as truenas_admin: bash /mnt/cell_block_d/repos/truenas/dotfiles/bootstrap.sh
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Prefer bootstrapping truenas_admin even when the script is invoked from a root/provisioner context.
TARGET_USER="${DOTFILES_USER:-${SUDO_USER:-$USER}}"
if [[ "$TARGET_USER" == "root" ]] && getent passwd truenas_admin >/dev/null 2>&1; then
  TARGET_USER="truenas_admin"
fi

resolve_home_dir() {
  local user="$1"
  local home=""

  if command -v getent >/dev/null 2>&1; then
    home="$(getent passwd "$user" | cut -d: -f6 || true)"
  fi

  if [[ -z "$home" ]] && [[ -r /etc/passwd ]]; then
    home="$(awk -F: -v u="$user" '$1==u {print $6; exit}' /etc/passwd)"
  fi

  if [[ -z "$home" ]]; then
    home="$(eval echo "~$user" 2>/dev/null || true)"
  fi

  echo "$home"
}

HOME_DIR="$(resolve_home_dir "$TARGET_USER")"
if [[ -z "$HOME_DIR" ]]; then
  HOME_DIR="$HOME"
fi

echo "==> Bootstrapping $TARGET_USER environment from $DOTFILES_DIR"

run_as_root() {
  if [[ "$(id -u)" -eq 0 ]]; then
    "$@"
  else
    sudo "$@"
  fi
}

# --- zsh ---
ZSH_BIN="$(command -v zsh 2>/dev/null || true)"
if [[ -z "$ZSH_BIN" ]]; then
  for candidate in /usr/bin/zsh /bin/zsh /usr/local/bin/zsh; do
    if [[ -x "$candidate" ]]; then
      ZSH_BIN="$candidate"
      break
    fi
  done
fi

if [[ -n "$ZSH_BIN" ]]; then
  CURRENT_SHELL=$(getent passwd "$TARGET_USER" | cut -d: -f7)
  if [[ "$CURRENT_SHELL" != "$ZSH_BIN" ]]; then
    echo "==> Setting zsh as default shell for $TARGET_USER"
    run_as_root chsh -s "$ZSH_BIN" "$TARGET_USER"
  fi
else
  echo "WARN: zsh not found; skipping default shell update"
  echo "      Install with: sudo apt-get install -y zsh"
fi

# --- symlink dotfiles ---
echo "==> Linking dotfiles"
for f in zshrc zprofile ssh/config; do
  src="$DOTFILES_DIR/$f"
  dst="$HOME_DIR/.${f}"
  if [[ ! -f "$src" ]]; then
    echo "  skip: $src not found"
    continue
  fi
  mkdir -p "$(dirname "$dst")"
  if [[ -f "$dst" && ! -L "$dst" ]]; then
    echo "  backup: $dst -> ${dst}.bak"
    mv "$dst" "${dst}.bak" || {
      echo "  warn: unable to backup $dst (continuing)"
      continue
    }
  fi
  ln -sf "$src" "$dst" || {
    echo "  warn: unable to link $dst (continuing)"
    continue
  }
  echo "  linked: $dst -> $src"
done

# --- sudo rules ---
SUDOERS_SRC="$DOTFILES_DIR/sudoers.d/truenas_admin"
SUDOERS_DST="/etc/sudoers.d/truenas_admin"
if [[ -f "$SUDOERS_SRC" ]]; then
  echo "==> Installing sudo rules"
  if run_as_root mkdir -p "$(dirname "$SUDOERS_DST")" \
    && run_as_root install -m 0440 "$SUDOERS_SRC" "$SUDOERS_DST"; then
    run_as_root visudo -cf "$SUDOERS_DST" && echo "  sudo rules OK" || echo "  ERROR: invalid sudoers file"
  else
    echo "  warn: unable to install sudoers file to $SUDOERS_DST (continuing)"
  fi
fi

# --- SSH key perms ---
if [[ -d "$HOME_DIR/.ssh" ]]; then
  echo "==> Fixing .ssh permissions"
  chmod 700 "$HOME_DIR/.ssh" || true
  chmod 600 "$HOME_DIR/.ssh/"* 2>/dev/null || true
  chmod 644 "$HOME_DIR/.ssh/"*.pub 2>/dev/null || true
fi

if [[ -n "$ZSH_BIN" ]]; then
  echo "==> Done. Start a new zsh session: exec zsh"
else
  echo "==> Done. Dotfiles linked, but zsh is not installed"
fi
