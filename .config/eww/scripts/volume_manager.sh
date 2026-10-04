#!/bin/bash
PID_FILE="/tmp/eww_vol_timer.pid"

cancel_timer() {
    if [ -f "$PID_FILE" ]; then
        kill -9 "$(cat "$PID_FILE")" 2>/dev/null
        rm -f "$PID_FILE"
    fi
}

show_and_timeout() {
    cancel_timer
    eww open volume-sidebar 2>/dev/null
    ( sleep 2; eww close volume-sidebar 2>/dev/null ) &
    echo $! > "$PID_FILE"
}

muted() {   # $1 — @DEFAULT_AUDIO_SINK@ или @DEFAULT_AUDIO_SOURCE@
    wpctl get-volume "$1" 2>/dev/null | grep -q '\[MUTED\]'
}

# Кнопка в микшере — это "заглушить всё", один выключатель на звук и микрофон.
# Раньше здесь стояло два `set-mute ... toggle` подряд, и они работали каждый
# сам по себе: если микрофон был уже выключен из бара, второй toggle его
# ВКЛЮЧАЛ. Нажатие "mute" оборачивалось открытым микрофоном — ровно то, чего
# от кнопки глушения ждёшь в последнюю очередь.
#
# Теперь состояние задаётся явно (1/0), а не переключается. Ведущий — динамик:
# на него смотрит иконка, от него и пляшем, а микрофон приводится к тому же
# состоянию. Раздельно они по-прежнему управляются из бара.
mute_all() {
    if muted @DEFAULT_AUDIO_SINK@; then
        wpctl set-mute @DEFAULT_AUDIO_SINK@   0
        wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0
    else
        wpctl set-mute @DEFAULT_AUDIO_SINK@   1
        wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 1
    fi
}

case "$1" in
    trigger_hit)
        show_and_timeout
        ;;
    cancel)
        cancel_timer
        ;;
    leave)
        show_and_timeout
        ;;
    toggle_mute)
        mute_all
        show_and_timeout
        ;;
    up)
        wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ "${2:-5%}+"
        show_and_timeout
        ;;
    down)
        wpctl set-volume @DEFAULT_AUDIO_SINK@ "${2:-5%}-"
        show_and_timeout
        ;;
esac
