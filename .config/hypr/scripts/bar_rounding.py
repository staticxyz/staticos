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

Значение хранится в ~/.config/hypr/state/bar-rounding («N ВИД») и действует
только у того вида бара, при котором задано (17.10.2026, просьба: «Парящий и
Компактный одинаковы» — 0 px от вида «во всю ширину» делал прямоугольными и
парящие виды). У другого вида rounding.css пустой, и углы — как в его
looks/<вид>.css. Смена вида (bar_style.py) пересобирает файл: refresh().
Ползунок — в «Настройках» → Waybar → «Углы и отступы».

    bar_rounding.py look       скругление самого вида (px)
"""
import os
import re
import sys

STATE = os.path.expanduser("~/.config/hypr/state/bar-rounding")
CSS = os.path.expanduser("~/.config/waybar/rounding.css")
STYLE = os.path.expanduser("~/.config/waybar/style.css")
LOOKS = os.path.expanduser("~/.config/waybar/looks")
DEFAULT = 0       # если у вида радиус не найден
LO, HI = 0, 16


def look_name():
    try:
        return os.path.basename(os.readlink(os.path.join(LOOKS, "current.jsonc")))[:-len(".jsonc")]
    except OSError:
        return ""


def look_radius():
    """Радиус window#waybar в looks/current.css — скругление самого вида."""
    try:
        css = open(os.path.join(LOOKS, "current.css"), encoding="utf-8").read()
    except OSError:
        return DEFAULT
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    m = re.search(r"window#waybar\s*\{[^}]*?border-radius:\s*(\d+)", css)
    return max(LO, min(HI, int(m.group(1)))) if m else DEFAULT


def custom():
    """Своё скругление для текущего вида или None."""
    try:
        n, look = open(STATE).read().split()[:2]
        return max(LO, min(HI, int(n))) if look == look_name() else None
    except (OSError, ValueError):
        return None


def get():
    n = custom()
    return look_radius() if n is None else n


def render(n):
    head = ("/* Сгенерировано scripts/bar_rounding.py — руками не править,\n"
            "   значение задаётся ползунком в «Настройках» → Waybar. */\n\n")
    if n is None:
        return head + "/* у этого вида своего скругления нет — углы как в looks/<вид>.css */\n"
    return head + "window#waybar { border-radius: %dpx; }\n" % n


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
    if n == look_radius():
        try:
            os.remove(STATE)         # как у вида — своего значения не держим
        except OSError:
            pass
        write(CSS, render(None))
    else:
        write(CSS, render(n))
        write(STATE, "%d %s\n" % (n, look_name()))
    poke_style()
    return n


def refresh():
    """Пересобрать rounding.css под текущий вид (bar_style.py после смены вида)."""
    text = render(custom())
    try:
        if open(CSS, encoding="utf-8").read() == text:
            return
    except OSError:
        pass
    write(CSS, text)


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "look":
        print(look_radius())
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
