#!/usr/bin/env bash
# Заряд для экрана блокировки (правый верхний угол, 30.09.2026). Раньше тут
# печатался текст модуля бара — шестерёнка с line_height 0.7, и hyprlock
# обрезал её сверху. Здесь — простой значок батареи с процентами.
bat=$(ls -d /sys/class/power_supply/BAT* 2>/dev/null | head -1)
[ -n "$bat" ] || exit 0
cap=$(cat "$bat/capacity" 2>/dev/null); st=$(cat "$bat/status" 2>/dev/null)
case "$st" in
    Charging) icon=$'\U000f0084' ;;                   # заряжается
    Full|"Not charging") icon=$'\U000f06a5' ;;        # от сети
    *) if [ "$cap" -ge 80 ]; then icon=$'\U000f0079'
       elif [ "$cap" -ge 50 ]; then icon=$'\U000f007f'
       elif [ "$cap" -ge 20 ]; then icon=$'\U000f007b'
       else icon=$'\U000f0083'; fi ;;
esac
# Savage Mode — его значок (спидометр), как в баре: без него на экране
# блокировки режим не было видно (30.09.2026).
sav=""
pid=$(cat /tmp/savage_mode.pid 2>/dev/null)
if [ -n "$pid" ] && tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | grep -q "24/7 mode"; then
    sav=$'\U000f04c5  '
fi
printf '%s%s  %s%%' "$sav" "$icon" "$cap"
