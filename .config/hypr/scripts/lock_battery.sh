#!/usr/bin/env bash
# Заряд для экрана блокировки (правый верхний угол, 30.09.2026). Раньше тут
# печатался текст модуля бара — шестерёнка с line_height 0.7, и hyprlock
# обрезал её сверху. Здесь — простой значок батареи с процентами.
bat=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)
[ -n "$bat" ] || exit 0
cap=$(cat "$bat/capacity" 2>/dev/null); st=$(cat "$bat/status" 2>/dev/null)
cap=${cap:-0}
ac=$(cat /sys/class/power_supply/AC/online 2>/dev/null)
# Та же батарейка, что в баре (savage_battery.py, 13.10.2026): горизонтальная Font Awesome,
# пять ступеней; заряжается — молния ВНУТРИ, от сети на паузе (лимит FlexiCharger) — вилка
# внутри; оба — шрифт JarvisBattery. Savage больше не спидометром: батарейка светится
# (jarvis_lock.py). Прежняя версия — lock_battery.sh.bak-lan.
if   [ "$cap" -lt 10 ]; then lv=0
elif [ "$cap" -lt 35 ]; then lv=1
elif [ "$cap" -lt 60 ]; then lv=2
elif [ "$cap" -lt 90 ]; then lv=3
else lv=4; fi
if [ "$st" = Charging ]; then
    icon=$(printf "\\u$(printf %X $((0xE210 + lv)))"); icon=$(printf "$icon")
elif [ "$ac" = 1 ] || { [ -z "$ac" ] && [ "$st" != Discharging ]; }; then
    icon=$(printf "\\u$(printf %X $((0xE220 + lv)))"); icon=$(printf "$icon")
else
    icon=$(printf "\\u$(printf %X $((0xF244 - lv)))"); icon=$(printf "$icon")
fi
printf '%s  %s%%' "$icon" "$cap"
