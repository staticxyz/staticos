#!/usr/bin/env bash
# Надписи кнопок питания экрана блокировки (hyprlock: cmd[update:250]). 30.09.2026.
#   lock_power_label.sh label <действие> | hint
# Оболочкой, а не питоном: пять надписей обновляются 4 раза в секунду, и запуск
# питона на каждую — ~20 процессов в секунду, пока экран заблокирован. Состояние
# «взведено» пишет lock_power.py (click) в $XDG_RUNTIME_DIR/jarvis-lock-power.json.
st="${XDG_RUNTIME_DIR:-/tmp}/jarvis-lock-power.json"
key=""; left=0
if [ -f "$st" ]; then
    read -r s < "$st"
    k=${s#*\"key\": \"}; k=${k%%\"*}
    t=${s#*\"t\": }; t=${t%%[.\}]*}
    now=$(date +%s)
    if [ -n "$t" ] && [ $((now - t)) -lt 5 ]; then key=$k; left=$((5 - (now - t))); fi
fi
err=$(grep -o '"error": *"#[0-9a-fA-F]*"' "$HOME/.cache/matugen/colors.json" 2>/dev/null | grep -o '#[0-9a-fA-F]*' | head -1)
err=${err:-#ffb4ab}
declare -A icon=([logout]=$'\U000f0343' [suspend]=$'\U000f0904' [reboot]=$'\U000f0709' [shutdown]=$'\U000f0425')
declare -A name=([logout]="выход" [reboot]="перезагрузка" [shutdown]="выключение")
case "$1" in
    label)
        if [ "$key" = "$2" ]; then printf '<span foreground="%s">%s</span>' "$err" "${icon[$2]}"
        else printf '%s' "${icon[$2]}"; fi ;;
    hint)
        [ -n "$key" ] && printf '<span foreground="%s">Ещё раз — %s (%d с)</span>' "$err" "${name[$key]}" "$left" ;;
esac
