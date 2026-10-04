#!/usr/bin/env python3
"""Отступы бара сверху и снизу (01.10.2026).

    bar_margins.py get          «край окна источник край_вида окна_вида»,
                                например «0 0 look 0 0» или «4 8 custom 0 0»
    bar_margins.py set E W      от края экрана E px, до окон W px (0..32)
    bar_margins.py reset        вернуть отступы формы панели

«От края экрана» — отступ бара от того края, у которого он стоит (margin-top у
бара сверху, margin-bottom у вида «Снизу»), «до окон» — с другой стороны.

Состояние — ~/.config/hypr/state/bar-margins («E W»). Нет файла — отступы
берёт форма панели (looks/current.jsonc, её меняет bar_style.py); заданные
здесь отступы действуют при любой форме, пока их не сбросят.

Применяет ~/.config/niri/scripts/waybar_niri.py: вписывает margin-top и
margin-bottom в config-niri.jsonc сразу после include — ключи основного
конфига главнее подключённого вида. Отступы waybar на лету не перечитывает,
поэтому после записи — один перезапуск бара командой barfix, и только если
значение правда поменялось. Только niri: в Hyprland бар читает config.jsonc,
туда скрипт не пишет.

Попапы: обычные стоят под исключительной зоной бара, а она включает оба
отступа, — «до окон» отодвигает их от бара вместе с окнами. «Приклеенные»
(popup-attached) считают место по popup_theme.bar_height() — высоте из
looks/current.jsonc, без отступа сверху (см. отчёт 01.10.2026).
"""
import os
import re
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/bar-margins")
LOOK = os.path.expanduser("~/.config/waybar/looks/current.jsonc")
GEN = os.path.expanduser("~/.config/niri/scripts/waybar_niri.py")
LO, HI = 0, 32


def look_values():
    """(от края, до окон) у текущей формы панели."""
    try:
        raw = open(LOOK, encoding="utf-8").read()
    except OSError:
        return 0, 0

    def num(key):
        m = re.search(r'"%s"\s*:\s*(\d+)' % key, raw)
        return int(m.group(1)) if m else 0
    top, bottom = num("margin-top"), num("margin-bottom")
    m = re.search(r'"position"\s*:\s*"(\w+)"', raw)
    return (bottom, top) if m and m.group(1) == "bottom" else (top, bottom)


def custom():
    """(от края, до окон) из состояния или None."""
    try:
        e, w = open(STATE).read().split()[:2]
        return max(LO, min(HI, int(e))), max(LO, min(HI, int(w)))
    except (OSError, ValueError):
        return None


def apply():
    """Пересобрать config-niri.jsonc и один раз перезапустить бар (только в niri)."""
    if not os.environ.get("NIRI_SOCKET"):
        print("не niri — бар не трогаю", file=sys.stderr)
        return
    subprocess.run(["python3", GEN], capture_output=True)
    subprocess.run(["barfix"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    args = sys.argv[1:] or ["get"]
    look = look_values()
    cur = custom()
    if args[0] == "get":
        e, w = cur or look
        print("%d %d %s %d %d" % (e, w, "custom" if cur else "look", look[0], look[1]))
        return 0
    if args[0] == "set" and len(args) == 3:
        try:
            new = tuple(max(LO, min(HI, int(float(a)))) for a in args[1:3])
        except ValueError:
            print("нужны два числа", file=sys.stderr)
            return 1
        if new == (cur or look):
            return 0                     # то же самое — бар не дёргаем
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        tmp = STATE + ".tmp"
        with open(tmp, "w") as f:
            f.write("%d %d\n" % new)
        os.replace(tmp, STATE)
        apply()
        print("отступы бара: от края %d px, до окон %d px" % new)
        return 0
    if args == ["reset"]:
        if cur is None:
            return 0
        os.remove(STATE)
        if cur != look:
            apply()
        print("отступы бара — как у формы панели")
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
