#!/usr/bin/env python3
"""Отдаёт палитру обоев расширению-теме LibreWolf (native messaging).

Расширению в песочнице нельзя открыть файл на диске, поэтому палитру
приносит этот скрипт. Его запускает сам браузер, когда расширение
подключается: никакого фонового демона и никакого открытого порта.

Протокол native messaging: каждое сообщение — 4 байта длины (порядок
байтов машины) и следом JSON в UTF-8, через stdin/stdout.

Дальше скрипт живёт вместе с браузером и раз в секунду смотрит mtime
colors.json. Как только theme_changer.sh перепишет палитру, новая
уезжает в расширение, и оно зовёт theme.update() — без перезапуска.
"""
import json
import os
import select
import struct
import sys
import time

PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")
POLL_S = 1.0


def send(obj):
    data = json.dumps(obj).encode("utf-8")
    # sys.stdout.buffer, а не print: любой лишний байт в потоке ломает
    # разбор сообщения на стороне браузера.
    sys.stdout.buffer.write(struct.pack("@I", len(data)))
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def read_palette():
    try:
        with open(PALETTE, encoding="utf-8") as f:
            p = json.load(f)
    except Exception:
        return None
    return {k: v for k, v in p.items() if isinstance(v, str) and v.startswith("#")}


def main():
    last_mtime = 0.0
    while True:
        try:
            mtime = os.path.getmtime(PALETTE)
        except OSError:
            mtime = 0.0
        if mtime != last_mtime:
            pal = read_palette()
            if pal:
                send(pal)
                last_mtime = mtime
        # Браузер закрылся -> на stdin приходит EOF. Проверяем это явно
        # через select: без этого процесс остался бы сиротой и продолжал
        # тикать после выхода из браузера.
        r, _, _ = select.select([sys.stdin.buffer], [], [], POLL_S)
        if r:
            head = sys.stdin.buffer.read(4)
            if not head:                    # EOF — браузер ушёл
                return 0
            length = struct.unpack("@I", head)[0]
            sys.stdin.buffer.read(length)   # содержимое запроса не важно
            pal = read_palette()
            if pal:
                send(pal)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (BrokenPipeError, KeyboardInterrupt):
        sys.exit(0)
