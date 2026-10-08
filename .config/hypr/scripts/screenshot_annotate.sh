#!/usr/bin/env bash
# Снимок области с разметкой (SUPER+Print; до 11.09.2026 — SHIFT+Print).
# Print остался быстрым — сразу в буфер. Здесь область выделяется по
# замороженному экрану, и снимок открывается в редакторе. Какой —
# выбирается в «Настройках» (settings_app.py), выбор лежит в
# ~/.config/hypr/state/shot-editor:
#
#   ksnip (по умолчанию) — нарисованное можно выделить и подвинуть, сменить
#         ему цвет и толщину; размытие и пикселизация, толщина числом.
#         Ctrl+C — скопировать в буфер, Ctrl+S — сохранить.
#   satty — проще и быстрее: Enter — скопировать и закрыть, Escape — закрыть.
#
# Почему без hyprshot. Он кончается строкой `begin_grab & checkRunning`:
# снимок (grim) идёт в ФОНЕ, а checkRunning, как только пропадает slurp,
# гасит заморозку и завершает hyprshot целиком, не дожидаясь grim. Этот
# скрипт проверял файл в ту же долю секунды, видел его пустым, принимал за
# отменённое выделение и молча выходил — окно редактора не появлялось, и
# не каждый раз, а когда grim не успевал. Здесь то же самое — hyprpicker,
# slurp, grim, — но строго по очереди: снимок пишется, пока экран ещё
# заморожен, и разморозка — только после записи.
#
# Каждый шаг пишет строку в $XDG_RUNTIME_DIR/shots/last.log — если что-то
# снова не так, причина видна там. SHOT_GEOMETRY="x,y WxH" — область без
# выделения мышью (для проверки).
#
# ksnip под Wayland падал на старте (SIGSEGV в XKeysymToKeycode): пытался
# завести глобальные клавиши через X11. Они выключены в ~/.config/ksnip/
# ksnip.conf ([HotKeys] GlobalHotKeysEnabled=false) — не включать обратно.
#
# Снимок кладётся в свою папку, а не во временный файл: ksnip может передать
# его уже открытому окну и выйти сразу. Старше суток — стираются здесь же.
editor=$(cat ~/.config/hypr/state/shot-editor 2>/dev/null)
dir="${XDG_RUNTIME_DIR:-/tmp}/shots"
mkdir -p "$dir"
find "$dir" -name 'shot-*.png' -mmin +1440 -delete 2>/dev/null
shot="$dir/shot-$(date +%H%M%S).png"
log="$dir/last.log"
: > "$log"
note() { printf '%s %s\n' "$(date +%T.%3N)" "$*" >> "$log"; }

# Заморозка — общая с Shift+Print (freeze_lib.sh): снимок в момент нажатия,
# выделение по застывшей картинке, область вырезается из снимка. Прежний
# hyprpicker -r -z под niri картинку НЕ замораживал — всё продолжало двигаться
# (29.09.2026) — и забирал клавиатуру: Escape приходилось жать дважды.
. "$HOME/.config/hypr/scripts/freeze_lib.sh"
trap freeze_cleanup EXIT
[ -z "$SHOT_GEOMETRY" ] && freeze_start

if [ -n "$SHOT_GEOMETRY" ]; then geometry=$SHOT_GEOMETRY; else geometry=$(pick_area); fi
note "область: ${geometry:-<отменено>}"
[ -n "$geometry" ] || exit 0      # Escape или щелчок мимо — выделение отменено
unfreeze

crop_area "$geometry" "$shot" 2>>"$log"
note "снимок: код $?, размер $(stat -c %s "$shot" 2>/dev/null || echo 0) байт"
[ -s "$shot" ] || { note "снимок пустой — выхожу"; rm -f "$shot"; exit 1; }

note "редактор: ${editor:-ksnip}"
# Снимок заморозки больше не нужен — убрать ДО exec: exec заменяет скрипт редактором, и
# уборка по trap EXIT уже не срабатывает — в /tmp (он в памяти) копились снимки по 12 МБ,
# к 06.10.2026 набралось 22 штуки, 256 МБ.
freeze_cleanup
trap - EXIT
if [ "$editor" = satty ]; then
    exec satty --filename "$shot" --copy-command wl-copy \
         --actions-on-enter save-to-clipboard,exit --actions-on-escape exit \
         --early-exit copy --disable-notifications
fi
QT_QPA_PLATFORM=wayland exec ksnip -e "$shot"
