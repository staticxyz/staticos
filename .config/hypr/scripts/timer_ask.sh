#!/bin/sh
# Таймер из меню рабочего стола (ПКМ по обоям → «Запустить таймер…»). 02.10.2026.
#
# Просьба: «я обычно запускаю через терминал командой timer *название, если есть* +
# *время*. Хочу, чтобы это делалось через правую кнопку». Здесь — окно ввода (rofi):
# готовые отрезки строками, своё — набрать как в терминале и Enter:
#     25m            tea 5m               work 1h 30m            подъём 07:30
# Дальше открывается обычное окно терминала с ~/.local/bin/timer — тем же, что и раньше.
choice=$(printf '%s\n' 5m 10m 15m 25m 45m 1h | rofi -dmenu -i -p "timer" \
    -theme-str 'entry { placeholder: "название и время: tea 5m, work 25m, 07:30"; }' 2>/dev/null) || exit 0
[ -n "$choice" ] || exit 0
# $choice без кавычек нарочно: «tea 5m» — это два аргумента для timer
# shellcheck disable=SC2086
exec kitty --single-instance --instance-group jarvis --title "timer $choice" "$HOME/.local/bin/timer" $choice
