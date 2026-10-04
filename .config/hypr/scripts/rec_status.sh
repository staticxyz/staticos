#!/bin/bash
# Красная точка в баре, пока идёт запись Recorder (30.09.2026, просьба пользователя).
# waybar custom/rec: опрос раз в 5 с плюс мгновенно по сигналу SIGRTMIN+11, который
# шлёт rec_area.sh при старте и остановке. Нет записи — пустой текст, модуль скрыт.
S="${XDG_RUNTIME_DIR:-/tmp}/jarvis-rec"
if [ -f "$S/pid" ] && kill -0 "$(cat "$S/pid")" 2>/dev/null; then
    mic=""; [ "$(cat "$S/mic" 2>/dev/null)" = on ] && mic=" · микрофон включён"
    # На паузе (03.10.2026) — значок паузы вместо точки: Space/K или ▶ на плашке продолжат.
    if [ -f "$S/paused" ]; then
        printf '{"text":"\U000f03e4","class":"rec","tooltip":"Запись на паузе (%s)%s — Space/K продолжить, щелчок остановит"}\n' "$(cat "$S/mode")" "$mic"
    else
        printf '{"text":"●","class":"rec","tooltip":"Идёт запись (%s)%s — щелчок остановит"}\n' "$(cat "$S/mode")" "$mic"
    fi
elif systemctl --user is-active --quiet jarvis-replay; then
    # Буфер Replay пишет в фоне — тусклая точка, чтобы не забыть, что он включён.
    echo '{"text":"●","class":"replay","tooltip":"Replay: держу последние 5 минут — Super+Alt+Print сохранить"}'
else
    echo '{"text":""}'
fi
