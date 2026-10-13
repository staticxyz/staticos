#!/bin/sh
# Щелчки и колёсико модуля звука в верхнем баре (bar_volume.py, 13.10.2026):
# действуют на то, что модуль сейчас показывает — динамики или микрофон.
#     bar_volume.sh mode | up | down | mute | popup
R="${XDG_RUNTIME_DIR:-/tmp}"
D=SINK; [ "$(cat "$R/jarvis-barvol.mode" 2>/dev/null)" = mic ] && D=SOURCE
# журнал последних действий (что нажато и на что подействовало) — для разбора жалоб
L="$R/jarvis-barvol.log"
echo "$(date +%T.%N | cut -c1-12) $1 $D" >> "$L"
[ "$(wc -l < "$L")" -gt 200 ] && tail -100 "$L" > "$L.t" && mv -f "$L.t" "$L"
case "$1" in
    mode)
        if [ $D = SOURCE ]; then echo sink; else echo mic; fi > "$R/jarvis-barvol.mode"
        kill -USR1 "$(cat "$R/jarvis-barvol.pid" 2>/dev/null)" 2>/dev/null ;;
    up)    wpctl set-volume -l 1.5 @DEFAULT_AUDIO_$D@ 5%+ ;;
    down)  wpctl set-volume @DEFAULT_AUDIO_$D@ 5%- ;;
    mute)  wpctl set-mute @DEFAULT_AUDIO_$D@ toggle ;;
    popup)
        if [ $D = SOURCE ]; then exec python3 $HOME/.config/hypr/scripts/mic_popup.py
        else exec python3 $HOME/.config/hypr/scripts/volume_popup.py; fi ;;
    *) sed -n '2,4p' "$0"; exit 2 ;;
esac
