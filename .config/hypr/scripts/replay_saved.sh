#!/bin/bash
# Вызывается gpu-screen-recorder после сохранения повтора (-sc): $1 — файл, $2 — тип.
# Файл — в буфер обмена ссылкой (как у Recorder) и уведомление (30.09.2026).
f="$1"
[ -f "$f" ] || exit 0
# wl-copy — отдельной службой: внутри службы replay он умирал вместе с ней при
# «replay off», и ссылка пропадала из буфера (проверено 30.09.2026).
systemd-run --user --quiet --collect --setenv=WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-1}" \
    wl-copy --foreground --type text/uri-list "file://$f"
notify-send -a "Replay" -h string:x-canonical-private-synchronous:jarvis-replay \
    "Повтор сохранён и скопирован" "$(basename "$f")  ·  $(du -h "$f" | cut -f1)"
