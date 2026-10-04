#!/usr/bin/env bash
# Установка темы экрана входа sddm-astronaut и помощника для «Настроек».
#
# Запуск (один раз, от root):
#     sudo bash ~/.config/hypr/scripts/login_theme/install.sh
#
# Что делает:
#   1. копирует тему из ~/.cache/login-theme/src (git-клон
#      github.com/Keyitdev/sddm-astronaut-theme) в /usr/share/sddm/themes;
#      прежняя копия, если была, переименовывается в *.bak-ДАТА;
#   2. шрифты темы — в /usr/share/fonts/sddm-astronaut-theme;
#   3. /etc/sddm.conf.d/10-sddm-astronaut.conf: тема и экранная клавиатура
#      (/etc/sddm.conf нет — ничего не перетирается);
#   4. помощник /usr/local/bin/sddm-astronaut-set (root, 0755);
#   5. /etc/sudoers.d/sddm-astronaut-set: пользователю static разрешено
#      запускать без пароля ТОЛЬКО этот помощник; файл проверяется visudo
#      до установки.
# Откат: удалить /etc/sddm.conf.d/10-sddm-astronaut.conf (SDDM вернётся к
# стандартной теме), /etc/sudoers.d/sddm-astronaut-set, /usr/local/bin/sddm-astronaut-set,
# /usr/share/sddm/themes/sddm-astronaut-theme, /usr/share/fonts/sddm-astronaut-theme.
# 14.09.2026.
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Нужен root: sudo bash $0"; exit 1; }

USER_NAME=${SUDO_USER:-}
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] || { echo "Run via sudo from your own user: sudo bash $0"; exit 1; }
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
SRC=$USER_HOME/.cache/login-theme/src
HERE=$USER_HOME/.config/hypr/scripts/login_theme
THEME=/usr/share/sddm/themes/sddm-astronaut-theme
FONTS=/usr/share/fonts/sddm-astronaut-theme
CONF=/etc/sddm.conf.d/10-sddm-astronaut.conf
SUDOERS=/etc/sudoers.d/sddm-astronaut-set
HELPER=/usr/local/bin/sddm-astronaut-set
STAMP=$(date +%Y%m%d-%H%M%S)

[ -f "$SRC/metadata.desktop" ] && [ -f "$SRC/Main.qml" ] || { echo "Нет исходников темы в $SRC"; exit 1; }
[ -f "$HERE/sddm-astronaut-set" ] || { echo "Нет помощника $HERE/sddm-astronaut-set"; exit 1; }

echo "1/5 тема -> $THEME"
if [ -e "$THEME" ]; then
    mv "$THEME" "$THEME.bak-$STAMP"
    echo "    прежняя копия: $THEME.bak-$STAMP"
fi
install -d -m 0755 "$THEME"
cp -r "$SRC"/. "$THEME"/
rm -rf "$THEME/.git"
chown -R root:root "$THEME"
find "$THEME" -type d -exec chmod 0755 {} +
find "$THEME" -type f -exec chmod 0644 {} +

echo "2/5 шрифты -> $FONTS"
install -d -m 0755 "$FONTS"
cp -r "$SRC/Fonts"/. "$FONTS"/
chown -R root:root "$FONTS"
find "$FONTS" -type d -exec chmod 0755 {} +
find "$FONTS" -type f -exec chmod 0644 {} +
fc-cache -f "$FONTS" >/dev/null 2>&1 || true

echo "3/5 выбор темы -> $CONF"
install -d -m 0755 /etc/sddm.conf.d
[ -e "$CONF" ] && cp -p "$CONF" "$CONF.bak-$STAMP"
cat > "$CONF" <<'EOF'
# Тема экрана входа — ~/.config/hypr/scripts/login_theme/install.sh (14.09.2026).
[Theme]
Current=sddm-astronaut-theme

[General]
InputMethod=qtvirtualkeyboard
EOF
chmod 0644 "$CONF"

echo "4/5 помощник -> $HELPER"
sed "s|@USER_HOME@|$USER_HOME|g" "$HERE/sddm-astronaut-set" > "$HELPER.new"
install -o root -g root -m 0755 "$HELPER.new" "$HELPER" && rm -f "$HELPER.new"

echo "5/5 sudoers -> $SUDOERS"
TMP=$(mktemp)
printf '%s\n' "# «Настройки» переключают вариант темы экрана входа (14.09.2026)." \
    "$USER_NAME ALL=(root) NOPASSWD: $HELPER" > "$TMP"
visudo -cf "$TMP" >/dev/null
install -o root -g root -m 0440 "$TMP" "$SUDOERS"
rm -f "$TMP"
visudo -c >/dev/null

echo "проверка: помощник без пароля от имени $USER_NAME"
if runuser -u "$USER_NAME" -- sudo -n "$HELPER" current; then
    echo "готово: тема установлена, вариант выбирается в «Настройках» → «Экран»"
else
    echo "ВНИМАНИЕ: sudo -n не пустил помощника — проверьте, что /etc/sudoers подключает /etc/sudoers.d"
    exit 1
fi
