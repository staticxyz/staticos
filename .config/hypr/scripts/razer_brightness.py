#!/usr/bin/env python3
"""Яркость подсветки клавиатуры Razer (BlackWidow V3) через openrazer (01.10.2026).

    razer_brightness.py get        яркость 0..100; клавиатуры нет — пусто, код 1
    razer_brightness.py set N      поставить яркость 0..100

Демон openrazer работает от пользователя (группа openrazer), поэтому sudo не
нужен. Цвета и раскладку подсветки не трогает — их держит kbd_colors.py
(профиль Polychromatic в гамме обоев); меняется только общая яркость.
Последнее значение — в ~/.cache/razer-brightness: «Настройки» рисуют строку
сразу из него, а ответ демона лишь уточняет.
"""
import os
import sys

LAST = os.path.expanduser("~/.cache/razer-brightness")


def keyboard():
    try:
        from openrazer.client import DeviceManager
        devs = [d for d in DeviceManager().devices
                if d.type == "keyboard" and d.has("brightness")]
    except Exception:
        return None
    return devs[0] if devs else None


def remember(n):
    try:
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        with open(LAST, "w") as f:
            f.write("%d\n" % n)
    except OSError:
        pass


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        dev = keyboard()
        if dev is None:
            return 1
        n = int(round(dev.brightness))
        remember(n)
        print(n)
        return 0
    if args[0] == "set" and len(args) == 2:
        try:
            n = max(0, min(100, int(float(args[1]))))
        except ValueError:
            print("нужно число 0..100", file=sys.stderr)
            return 1
        dev = keyboard()
        if dev is None:
            print("клавиатура Razer не найдена", file=sys.stderr)
            return 1
        dev.brightness = n
        remember(n)
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
