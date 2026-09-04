#!/usr/bin/env bash
# bootstrap.sh — provision truenas_admin shell environment from git
# Run as truenas_admin: bash /mnt/cell_block_d/repos/truenas/dotfiles/bootstrap.sh
set -euo pipefail

DOTFILES_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOME_DIR="$HOME"

echo "==> Bootstrapping truenas_admin environment from $DOTFILES_DIR"

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
  CURRENT_SHELL=$(getent passwd "$USER" | cut -d: -f7)
  if [[ "$CURRENT_SHELL" != "$ZSH_BIN" ]]; then
    echo "==> Setting zsh as default shell for $USER"
    sudo chsh -s "$ZSH_BIN" "$USER"
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
    mv "$dst" "${dst}.bak"
  fi
  ln -sf "$src" "$dst"
  echo "  linked: $dst -> $src"
done

# --- sudo rules ---
SUDOERS_SRC="$DOTFILES_DIR/sudoers.d/truenas_admin"
SUDOERS_DST="/etc/sudoers.d/truenas_admin"
if [[ -f "$SUDOERS_SRC" ]]; then
  echo "==> Installing sudo rules"
  sudo install -m 0440 "$SUDOERS_SRC" "$SUDOERS_DST"
  sudo visudo -cf "$SUDOERS_DST" && echo "  sudo rules OK" || echo "  ERROR: invalid sudoers file"
fi

# --- SSH key perms ---
if [[ -d "$HOME_DIR/.ssh" ]]; then
  echo "==> Fixing .ssh permissions"
  chmod 700 "$HOME_DIR/.ssh"
  chmod 600 "$HOME_DIR/.ssh/"* 2>/dev/null || true
  chmod 644 "$HOME_DIR/.ssh/"*.pub 2>/dev/null || true
fi

if [[ -n "$ZSH_BIN" ]]; then
  echo "==> Done. Start a new zsh session: exec zsh"
else
  echo "==> Done. Dotfiles linked, but zsh is not installed"
fi
