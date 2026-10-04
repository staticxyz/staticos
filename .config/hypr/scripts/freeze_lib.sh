# Общая заморозка экрана для Shift+Print (ocr_copy.sh) и Super+Print
# (screenshot_annotate.sh). Подключается через `.`, 29.09.2026.
#
#   freeze_start      снять весь стол и показать снимок поверх мониторов
#   pick_area         выделение (slurp) по застывшей картинке; печатает «X,Y WxH»
#   crop_area G ФАЙЛ  вырезать область G из снимка момента нажатия
#   unfreeze          убрать заморозку (снимок остаётся до freeze_cleanup)
#   freeze_cleanup    убрать всё, включая временный снимок
#
# Почему не hyprpicker -r -z, как раньше: под niri он экран НЕ замораживал —
# слой вставал, но изображение под ним оставалось живым, и при снимке всё
# продолжало двигаться (29.09.2026). К тому же он забирал клавиатуру,
# и выделение закрывалось только со второго Escape. Здесь снимок делается в
# момент нажатия, показывается поверх (freeze_screen.py, клавиатуру не берёт),
# и вырезается область ИЗ СНИМКА — ровно как в обычном Print у niri.

freeze_pid=""
freeze_snap=""
_FREEZE_PY="$HOME/.config/hypr/scripts/freeze_screen.py"

freeze_start() {
    freeze_snap=$(mktemp -t freeze-XXXXXX.png) || return 1
    rm -f "$freeze_snap"                  # окно ждёт появления файла — пусть его пока нет
    # Окно заморозки стартует СРАЗУ, параллельно со снимком: его запуск (импорт
    # GTK, ~0.2 с) идёт, пока grim снимает, а снимок оно подождёт само.
    python3 "$_FREEZE_PY" "$freeze_snap" >/dev/null 2>&1 &
    freeze_pid=$!
    # -l 0 — PNG БЕЗ сжатия. Со сжатием по умолчанию grim тратил на два
    # монитора ~1 с, и Shift+Print / Super+Print открывались с заметной
    # задержкой (29.09.2026). Без сжатия — ~0.05 с. Файл временный,
    # его размер не важен. Пишем в .part и переименовываем, чтобы окно не
    # прочитало недописанный снимок.
    if ! grim -l 0 "$freeze_snap.part" 2>/dev/null; then
        kill "$freeze_pid" 2>/dev/null; freeze_pid=""
        rm -f "$freeze_snap.part"; freeze_snap=""; return 1
    fi
    mv "$freeze_snap.part" "$freeze_snap"
    # Дождаться, пока слой заморозки встанет: выделение должно лечь ПОВЕРХ него.
    # Иначе заморозка, вставшая позже, накроет выделение, и его не будет видно.
    # Замер 29.09.2026 после ускорения: слой встаёт через ~0.25 с после
    # нажатия; ждём до 4 с с запасом.
    _i=0
    while [ $_i -lt 100 ]; do
        niri msg --json layers 2>/dev/null | grep -q '"jarvis-freeze"' && return 0
        sleep 0.03; _i=$((_i + 1))
    done
    return 0
}

unfreeze() {
    [ -n "$freeze_pid" ] && kill "$freeze_pid" 2>/dev/null
    freeze_pid=""
}

freeze_cleanup() {
    unfreeze
    [ -n "$freeze_snap" ] && rm -f "$freeze_snap" "$freeze_snap.part"
    freeze_snap=""
}

# Выделение. Сторож на случай, если заморозка закроется раньше (упала или
# сработала страховка по времени), — тогда отменяем и выделение, а не висим.
pick_area() {
    _out=$(mktemp -t pick-XXXXXX)
    slurp -d > "$_out" 2>/dev/null &
    _sp=$!
    _wp=""
    if [ -n "$freeze_pid" ]; then
        ( while kill -0 "$_sp" 2>/dev/null; do
              kill -0 "$freeze_pid" 2>/dev/null || { kill "$_sp" 2>/dev/null; break; }
              sleep 0.05
          done ) &
        _wp=$!
    fi
    wait "$_sp"; _rc=$?
    [ -n "$_wp" ] && kill "$_wp" 2>/dev/null
    cat "$_out"; rm -f "$_out"
    return $_rc
}

# Вырезать «X,Y WxH» из снимка. Без снимка (заморозка не встала) — с живого
# экрана, как раньше: лучше неподвижность потерять, чем снимок.
crop_area() {
    if [ -n "$freeze_snap" ] && [ -s "$freeze_snap" ]; then
        _xy=${1%% *}; _wh=${1#* }
        magick "$freeze_snap" -crop "${_wh}+${_xy%,*}+${_xy#*,}" +repage "$2" 2>/dev/null
    else
        grim -g "$1" "$2" 2>/dev/null
    fi
}
