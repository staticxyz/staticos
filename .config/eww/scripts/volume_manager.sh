#!/bin/bash
# Показ микшера (13.10.2026, просьба: «если быстро кликать F1/F2, микшер дрожит, дёргается»).
# Было: каждое нажатие — kill таймера, `eww open` и новый `sleep 2; eww close`. `eww open`
# уже открытого окна пересоздаёт его — отсюда рывки, а параллельные нажатия гонялись за
# PID-файлом, и «осиротевший» таймер закрывал окно посреди серии. Теперь: нажатие лишь
# двигает срок закрытия (файл DEADLINE), окно открывает и закрывает ОДИН сторож — под
# flock, чтобы два нажатия разом не подняли двух.
RUN="${XDG_RUNTIME_DIR:-/tmp}"
DEADLINE="$RUN/eww-vol.deadline"   # мс эпохи, когда закрыть; "hold" — мышь над микшером
LOCK="$RUN/eww-vol.lock"
OPEN="$RUN/eww-vol.open"           # есть, пока сторож жив и окно открыто
STAMP="$RUN/eww-vol.keys"          # последняя смена громкости клавишами/колесом
TARGET="$RUN/eww-vol.target"

now_ms() { date +%s%3N; }

cancel_timer() { echo hold > "$DEADLINE"; }

show_and_timeout() {
    echo $(( $(now_ms) + 2000 )) > "$DEADLINE"
    (
        flock -n 9 || exit 0          # сторож уже работает — он увидит новый срок
        touch "$OPEN"
        # eww reload (mixer_style.py) сбрасывает vol-target в "sink" — сверяем при открытии
        eww update vol-target="$(cat "$TARGET" 2>/dev/null || echo sink)" 2>/dev/null
        eww open volume-sidebar 2>/dev/null
        while :; do
            d=$(cat "$DEADLINE" 2>/dev/null)
            if [ "$d" != hold ] && [ "${d:-0}" -le "$(now_ms)" ]; then break; fi
            sleep 0.1
        done
        eww close volume-sidebar 2>/dev/null
        rm -f "$OPEN"
    ) 9>"$LOCK" &
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

# Что показывает микшер: динамик (sink) или микрофон (source). Колесо над
# значком микрофона в баре переводит его в режим микрофона (13.10.2026, пользователь);
# любое касание динамика — обратно. eww update только при смене: лишний вызов
# заметно тормозит прокрутку.
target() {
    [ "$(cat "$TARGET" 2>/dev/null)" = "$1" ] && return
    echo "$1" > "$TARGET"
    eww update vol-target="$1" 2>/dev/null
}

case "$1" in
    trigger_hit)
        target sink
        show_and_timeout
        ;;
    cancel)
        cancel_timer
        ;;
    leave)
        show_and_timeout
        ;;
    toggle_mute)
        # В режиме микрофона кнопка глушит только микрофон — звук не трогает.
        if [ "$(cat "$TARGET" 2>/dev/null)" = source ]; then
            wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle
        else
            mute_all
        fi
        show_and_timeout
        ;;
    mic_up)
        touch "$STAMP"
        target source
        wpctl set-volume -l 1 @DEFAULT_AUDIO_SOURCE@ "${2:-5%}+"
        show_and_timeout
        ;;
    mic_down)
        touch "$STAMP"
        target source
        wpctl set-volume @DEFAULT_AUDIO_SOURCE@ "${2:-5%}-"
        show_and_timeout
        ;;
    up)
        touch "$STAMP"
        target sink
        wpctl set-volume -l 1 @DEFAULT_AUDIO_SINK@ "${2:-5%}+"
        show_and_timeout
        ;;
    down)
        touch "$STAMP"
        target sink
        wpctl set-volume @DEFAULT_AUDIO_SINK@ "${2:-5%}-"
        show_and_timeout
        ;;
    wheel)
        # колесо над самим микшером: 3 % за щелчок, по тому, что он сейчас показывает
        touch "$STAMP"
        dev=@DEFAULT_AUDIO_SINK@; [ "$(cat "$TARGET" 2>/dev/null)" = source ] && dev=@DEFAULT_AUDIO_SOURCE@
        if [ "$2" = up ]; then wpctl set-volume -l 1 "$dev" 3%+; else wpctl set-volume "$dev" 3%-; fi
        ;;
    set)
        # Ползунок микшера: eww зовёт onchange и тогда, когда значение пришло из опроса.
        # Сразу после нажатия клавиши опрос отстаёт на шаг, и ползунок «возвращал» старую
        # громкость — она прыгала туда-сюда. Пока клавиши в ходу (0,6 с), ползунок молчит.
        if [ -f "$STAMP" ] && [ $(( $(now_ms) - $(date -r "$STAMP" +%s%3N) )) -lt 600 ]; then
            exit 0
        fi
        dev=@DEFAULT_AUDIO_SINK@; [ "$2" = source ] && dev=@DEFAULT_AUDIO_SOURCE@
        cur=$(wpctl get-volume "$dev" 2>/dev/null | awk '{print int($2 * 100 + 0.5)}')
        [ "$cur" = "$3" ] || wpctl set-volume "$dev" "$3%"
        ;;
esac
