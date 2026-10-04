#!/usr/bin/env python3
"""Раскладка окон: лента (как в Niri) или классика Hyprland.

    layout_mode.py get                   scrolling / dwindle
    layout_mode.py set scrolling|dwindle переключить (сразу, без перезагрузки)
    layout_mode.py toggle                на другую

scrolling — «лента»: каждое окно — колонка на бесконечной горизонтальной
            ленте, новые встают справа, экран — окошко, через которое на
            неё смотришь. Включена 11.09.2026 после пробы на столе 10.
dwindle   — «классика»: окна делят экран между собой, как было раньше.

Плавающих окон раскладка не касается — только плиточных. Выбор хранится в
~/.config/hypr/state/layout-mode; visuals.lua читает его при загрузке, так
что он переживает и перезапуск Hyprland. Переключатель — в «Настройках»,
раздел «Внешний вид» → «Окна». Клавиши ленты (ribbon_binds.lua) проверяют
раскладку в момент нажатия и подстраиваются сами.
"""
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/layout-mode")
MODES = ("scrolling", "dwindle")
DEFAULT = "scrolling"


def get():
    try:
        with open(STATE) as f:
            v = f.read().strip()
        return v if v in MODES else DEFAULT
    except OSError:
        return DEFAULT


def save(mode):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write(mode + "\n")
    os.replace(tmp, STATE)


def apply(mode):
    r = subprocess.run(["hyprctl", "eval",
                        'hl.config({ general = { layout = "%s" } })' % mode],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def main():
    args = sys.argv[1:] or ["get"]
    if args == ["get"]:
        print(get())
        return 0
    if args == ["toggle"]:
        args = ["set", "dwindle" if get() == "scrolling" else "scrolling"]
    if len(args) == 2 and args[0] == "set" and args[1] in MODES:
        save(args[1])
        print("раскладка: %s (%s)" % (args[1], apply(args[1])))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
