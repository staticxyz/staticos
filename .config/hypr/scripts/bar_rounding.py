#!/usr/bin/env python3
"""Скругление углов самого бара (waybar).

    bar_rounding.py get        текущее значение (px)
    bar_rounding.py set N      применить сразу и запомнить (0..16)

Управляет только подложкой панели — window#waybar, — таблетки внутри бара не
трогает (их радиусы остаются в style.css). Первая версия 14.09.2026 меняла
именно таблетки, но пользователь имел в виду углы самого бара.

Как устроено. Скрипт пишет ~/.config/waybar/rounding.css с одним правилом
window#waybar { border-radius: N }. Файл импортируется в style.css ПОСЛЕ
looks/current.css, поэтому при равной специфичности перебивает радиус вида.

Перечитать стиль. Waybar следит за style.css (reload_style_on_change), но
реагирует на изменение СОДЕРЖИМОГО: смена одного времени (utime) и запись
импортируемого rounding.css его не будят — проверено 14.09.2026, таблетки при
2 и 16 px выглядели одинаково. Поэтому style.css перезаписывается тем же
содержимым на месте (тот же inode и длина): waybar перечитывает стиль БЕЗ
перезапуска — номер процесса не меняется. Сигнал SIGUSR2 тоже работает, но
перезапускает весь бар, и тот мигает.

Значение хранится в ~/.config/hypr/state/bar-rounding. Ползунок — в
«Настройках» → «Внешний вид».
"""
import os
import sys

STATE = os.path.expanduser("~/.config/hypr/state/bar-rounding")
CSS = os.path.expanduser("~/.config/waybar/rounding.css")
STYLE = os.path.expanduser("~/.config/waybar/style.css")
DEFAULT = 0       # у нынешнего вида «вровень с окнами» углы прямые
LO, HI = 0, 16


def get():
    try:
        with open(STATE) as f:
            return max(LO, min(HI, int(f.read().strip())))
    except (OSError, ValueError):
        return DEFAULT


def render(n):
    return ("/* Сгенерировано scripts/bar_rounding.py — руками не править,\n"
            "   значение задаётся ползунком в «Настройках» → «Внешний вид». */\n\n"
            "window#waybar { border-radius: %dpx; }\n" % n)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def poke_style():
    """Перезаписать style.css тем же содержимым — waybar перечитает стиль."""
    try:
        with open(STYLE, "r+b") as f:
            data = f.read()
            f.seek(0)
            f.write(data)
            f.truncate()
    except OSError:
        pass


def set_value(n):
    n = max(LO, min(HI, int(n)))
    write(CSS, render(n))
    write(STATE, "%d\n" % n)
    poke_style()
    return n


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "set" and len(args) == 2:
        try:
            n = set_value(float(args[1]))
        except ValueError:
            print("нужно число", file=sys.stderr)
            return 1
        print("скругление углов бара: %d px" % n)
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
