#!/usr/bin/env bash
# Разовая установка root-помощника команды power (нужен пароль sudo один раз). 22.10.2026.
#     bash ~/.local/share/power-helper/install.sh
# Откат: sudo rm /usr/local/bin/power-helper /etc/sudoers.d/power-helper
set -euo pipefail
SRC="$HOME/.local/share/power-helper"
tmp=$(mktemp)
echo "$USER ALL=(root) NOPASSWD: /usr/local/bin/power-helper" > "$tmp"
sudo install -o root -g root -m 0755 "$SRC/power-helper" /usr/local/bin/power-helper
sudo visudo -cf "$tmp" >/dev/null || { rm -f "$tmp"; echo "sudoers не прошёл проверку — остановлено"; exit 1; }
sudo install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/power-helper
rm -f "$tmp"
sudo -n -l /usr/local/bin/power-helper >/dev/null && echo "готово: power-helper без пароля"
