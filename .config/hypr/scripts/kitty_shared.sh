#!/bin/sh
# Общая копия kitty (Ctrl+`, Mod+Return, «Пуск», лаунчер, меню стола) — 08.10.2026.
#
# Шрифт у копии kitty один на весь процесс и читается при её запуске, поэтому
# окна, открытые в уже живой копии, смену шрифта в Настройках не видели
# (режим «только новые окна» не работал). Группа копии зависит от font_family
# в kitty.conf: после смены шрифта следующее окно поднимает новую копию с новым
# шрифтом, старые окна живут в прежней, пока их не закроют.
#
#   kitty_shared.sh [аргументы kitty…]
FONT=$(sed -n 's/^font_family[[:space:]]\{1,\}//p' "$HOME/.config/kitty/kitty.conf" 2>/dev/null | head -n1)
TAG=$(printf '%s' "$FONT" | tr -cd 'A-Za-z0-9')
exec kitty --single-instance --instance-group "jarvis${TAG:+-$TAG}" "$@"
