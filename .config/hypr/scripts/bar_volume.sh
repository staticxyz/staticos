#!/bin/sh
# Щелчки и колёсико модуля звука в верхнем баре (bar_volume.py, 13.10.2026):
# действуют на то, что модуль сейчас показывает — динамики или микрофон.
#     bar_volume.sh mode | up | down | mute | popup [ВЫХОД]
# Два монитора (29.10.2026): у бара каждого монитора свой режим (mode.<ВЫХОД>; сначала
# ноутбук — микрофон, внешний — звук), СКМ переключает свой бар; один монитор — общий
# файл, как раньше (см. bar_volume.py).
R="${XDG_RUNTIME_DIR:-/tmp}"
OUT=$2
N=0
for c in /sys/class/drm/card*-*; do
    [ "$(cat "$c/status" 2>/dev/null)" = connected ] && [ "$(cat "$c/enabled" 2>/dev/null)" = enabled ] && N=$((N + 1))
done
M="$R/jarvis-barvol.mode"
if [ -n "$OUT" ] && [ "$N" -ge 2 ]; then
    M="$M.$OUT"
    [ -f "$M" ] || case $OUT in eDP*) echo mic ;; *) echo sink ;; esac > "$M"
fi
D=SINK; [ "$(cat "$M" 2>/dev/null)" = mic ] && D=SOURCE
# журнал последних действий (что нажато и на что подействовало) — для разбора жалоб
L="$R/jarvis-barvol.log"
echo "$(date +%T.%N | cut -c1-12) $1 $D $OUT" >> "$L"
[ "$(wc -l < "$L")" -gt 200 ] && tail -100 "$L" > "$L.t" && mv -f "$L.t" "$L"
case "$1" in
    mode)
        if [ $D = SOURCE ]; then echo sink; else echo mic; fi > "$M"
        for f in "$R"/jarvis-barvol*.pid; do kill -USR1 "$(cat "$f" 2>/dev/null)" 2>/dev/null; done ;;
    up)    wpctl set-volume -l 1.5 @DEFAULT_AUDIO_$D@ 5%+ ;;
    down)  wpctl set-volume @DEFAULT_AUDIO_$D@ 5%- ;;
    mute)  wpctl set-mute @DEFAULT_AUDIO_$D@ toggle ;;
    popup)
        if [ $D = SOURCE ]; then exec python3 $HOME/.config/hypr/scripts/mic_popup.py
        else exec python3 $HOME/.config/hypr/scripts/volume_popup.py; fi ;;
    *) sed -n '2,4p' "$0"; exit 2 ;;
esac
