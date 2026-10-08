#!/bin/sh
# Терминал пробным шрифтом — Mod+Grave (23.09.2026).
#
# Шрифт передаётся kitty аргументом -o и живёт только в этом окне: kitty.conf
# не открывается, открытым терминалам ничего не рассылается. Так шрифт щупают,
# ничего не ломая; понравился — Настройки → Шрифты → «Терминал kitty».
#
#   term_font.sh [шрифт] [размер]
#
# Без аргументов шрифт берётся из Настроек (app_fonts.py get termalt), размер —
# из SIZE. У пиксельных шрифтов чёткость только на кратных размерах: PxPlus
# HP 100LX 6x8 рисует клетку 6x8, значит 12 pt = ×2, 18 pt = ×3, между ними
# буквы замыливаются.
SIZE_DEFAULT=12

FONT="$1"
[ -n "$FONT" ] || FONT=$(python3 "$HOME/.config/hypr/scripts/app_fonts.py" get termalt 2>/dev/null)
[ -n "$FONT" ] || FONT="PxPlus HP 100LX 6x8"
# Cozette нарисован на сетке 13 px: чёткий на 9.75 pt, на 12 pt замыливается.
case "$FONT" in Cozette*) SIZE_DEFAULT=9.75 ;; esac
SIZE="${2:-$SIZE_DEFAULT}"

exec kitty --class jarvis-term-font --title "$FONT $SIZE pt" \
     -o font_family="$FONT" -o font_size="$SIZE"
