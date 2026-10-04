#!/usr/bin/env bash
# Бинд Alt+Tab → резидент alt_tab.py (05.10.2026). Без питона: одна строка в канал —
# доли миллисекунды. Канал открывается на чтение+запись (1<>) — запись не блокирует,
# даже если читателя нет. Резидент не жив — поднять (он сам покажет переключатель).
R=${XDG_RUNTIME_DIR:-/tmp}; F=$R/jarvis-alttab.fifo; P=$R/jarvis-alttab.pid
cmd=${1:-next}
pid=$(cat "$P" 2>/dev/null)
if [ -p "$F" ] && [ -n "$pid" ] && grep -qa "alt_tab.py" "/proc/$pid/cmdline" 2>/dev/null; then
    printf '%s\n' "$cmd" 1<>"$F"
else
    setsid python3 "$HOME/.config/hypr/scripts/alt_tab.py" daemon "$cmd" >/dev/null 2>>"$HOME/.cache/alt_tab.log" &
fi
