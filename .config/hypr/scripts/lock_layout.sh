#!/usr/bin/env bash
# Раскладка для экрана блокировки (30.09.2026). Раньше в шаблоне стоял
# `hyprctl devices`, а под niri hyprctl молчит — надпись пропала.
# Спрашиваем у того композитора, в котором сейчас сеанс.
if [ -n "${NIRI_SOCKET:-}" ]; then
    name=$(niri msg -j keyboard-layouts 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d["names"][d["current_idx"]])' 2>/dev/null)
else
    name=$(hyprctl devices -j 2>/dev/null | jq -r '.keyboards[] | select(.main==true) | .active_keymap' 2>/dev/null)
fi
case "$name" in
    English*) printf '\U000f030c US' ;;
    Russian*) printf '\U000f030c RU' ;;
    "")       ;;
    *)        printf '\U000f030c %s' "${name:0:2}" ;;
esac
# Caps Lock (30.09.2026, просьба пользователя): светодиод любой клавиатуры горит —
# рядом с раскладкой «⇪ CAPS» цветом ошибки, чтобы пароль не ушёл заглавными.
for led in /sys/class/leds/*::capslock/brightness; do
    if [ "$(cat "$led" 2>/dev/null)" = "1" ]; then
        err=$(grep -o '"error": *"#[0-9a-fA-F]*"' "$HOME/.cache/matugen/colors.json" 2>/dev/null | grep -o '#[0-9a-fA-F]*' | head -1)
        printf '   <span foreground="%s">\U000f0632 CAPS</span>' "${err:-#ffb4ab}"
        break
    fi
done
