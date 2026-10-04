#!/usr/bin/env bash
# Обновить только помощника экрана входа (/usr/local/bin/sddm-astronaut-set).
#
# Запуск:  sudo bash ~/.config/hypr/scripts/login_theme/update_helper.sh
#
# Тему, шрифты, файл в /etc/sddm.conf.d и правило sudoers не трогает: путь
# помощника прежний, правило в /etc/sudoers.d подходит как есть. Полный
# install.sh для этого не годится — он переименовал бы установленную тему и
# сбросил собранный вариант «Как рабочий стол».
# 14.09.2026: помощник научился выбирать тему SDDM (dm-current, dm-set) —
# «Как было» и Breeze/Elarun/Maldives/Maya в «Настройках».
set -euo pipefail

[ "$(id -u)" = 0 ] || { echo "Нужен root: sudo bash $0"; exit 1; }

USER_NAME=${SUDO_USER:-}
[ -n "$USER_NAME" ] && [ "$USER_NAME" != root ] || { echo "Run via sudo from your own user: sudo bash $0"; exit 1; }
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
SRC=$USER_HOME/.config/hypr/scripts/login_theme/sddm-astronaut-set
HELPER=/usr/local/bin/sddm-astronaut-set
STAMP=$(date +%Y%m%d-%H%M%S)

[ -f "$SRC" ] || { echo "Нет $SRC"; exit 1; }
/usr/bin/python3 -m py_compile "$SRC"
rm -rf "$USER_HOME/.config/hypr/scripts/login_theme/__pycache__"

[ -f "$HELPER" ] && cp -p "$HELPER" "$HELPER.bak-$STAMP" && echo "прежний помощник: $HELPER.bak-$STAMP"
sed "s|@USER_HOME@|$USER_HOME|g" "$SRC" > "$HELPER.new"
install -o root -g root -m 0755 "$HELPER.new" "$HELPER" && rm -f "$HELPER.new"

echo "проверка от имени static:"
runuser -u "$USER_NAME" -- sudo -n "$HELPER" dm-current | sed 's/^/  тема SDDM: /; s/: $/: (встроенная)/'
runuser -u "$USER_NAME" -- sudo -n "$HELPER" current | sed 's/^/  вариант astronaut: /'
echo "готово"
