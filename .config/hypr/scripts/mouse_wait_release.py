#!/usr/bin/env python3
"""Подождать, пока отпустят кнопки мыши. 02.10.2026.

    mouse_wait_release.py [секунд]     ждёт не дольше (по умолчанию 1.0), затем ещё 40 мс

Зачем: цепочки «меню → следующее меню → выделение области» (rec_area.sh). Пункт
выбирается нажатием, а отпускание кнопки прилетает уже в следующее окно — оно
«перещёлкивалось» или закрывалось (просьба: «через клаву работает, через мышь
нет»). Состояние кнопок читается у ядра (EVIOCGKEY, группа input), без опроса
событий; нет доступа — просто короткая пауза.
"""
import fcntl
import os
import re
import sys
import time

EVIOCGKEY = 0x80000000 | (96 << 16) | (ord("E") << 8) | 0x18
BUTTONS = (0x110, 0x111, 0x112)          # левая, правая, средняя


def mice():
    out = []
    try:
        for b in open("/proc/bus/input/devices").read().split("\n\n"):
            h = next((l for l in b.splitlines() if l.startswith("H: Handlers=")), "")
            if "mouse" in h:
                out += ["/dev/input/" + e for e in re.findall(r"\bevent\d+", h)]
    except OSError:
        pass
    return out


def pressed(files):
    for f in files:
        try:
            buf = fcntl.ioctl(f, EVIOCGKEY, bytes(96))
        except OSError:
            continue
        if any(buf[b // 8] >> (b % 8) & 1 for b in BUTTONS):
            return True
    return False


def main():
    limit = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    files = []
    for p in mice():
        try:
            files.append(open(p, "rb", buffering=0))
        except OSError:
            pass
    if not files:
        time.sleep(0.15)
        return
    end = time.monotonic() + limit
    was = False
    while pressed(files) and time.monotonic() < end:
        was = True
        time.sleep(0.01)
    if was:
        time.sleep(0.04)
    os._exit(0)          # без закрытия устройств: close() у evdev стоит ~15 мс на штуку


if __name__ == "__main__":
    main()
