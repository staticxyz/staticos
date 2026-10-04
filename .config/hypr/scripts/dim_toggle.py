#!/usr/bin/env python3
"""Неактивные окна: затемнять или делать прозрачными.

    dim_toggle.py get        on / off
    dim_toggle.py on|off     переключить (сразу, без перезагрузки)
    dim_toggle.py strength V сила затемнения 0.05–0.6 (приложение «Настройки»)
    dim_toggle.py get-strength

on  — неактивные окна слегка затемняются (dim_inactive), непрозрачность 1.
      Фокус видно, а текст в соседних окнах остаётся чётким.
off — как было раньше: неактивные окна полупрозрачные (0.82), сквозь них
      проступает фон.

Выбор хранится в ~/.config/hypr/state/dim-inactive; visuals.lua читает его
при загрузке конфига, так что он переживает и перезапуск Hyprland.
"""
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/dim-inactive")
STRENGTH = os.path.expanduser("~/.config/hypr/state/dim-strength")
DIM_STRENGTH = 0.22         # по умолчанию, если сила не выбрана в «Настройках»
OLD_OPACITY = 0.82


def get():
    try:
        with open(STATE) as f:
            return "off" if f.read().strip() == "off" else "on"
    except OSError:
        return "on"


def strength():
    try:
        with open(STRENGTH) as f:
            return max(0.05, min(0.6, float(f.read().strip())))
    except (OSError, ValueError):
        return DIM_STRENGTH


def apply(on):
    lua = ("hl.config({ decoration = { dim_inactive = %s, dim_strength = %s, "
           "inactive_opacity = %s } })" % ("true" if on else "false",
                                           round(strength(), 2), 1 if on else OLD_OPACITY))
    r = subprocess.run(["hyprctl", "eval", lua], capture_output=True, text=True)
    return r.stdout.strip()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "get"
    if arg == "get":
        print(get())
        return 0
    if arg == "get-strength":
        print(strength())
        return 0
    if arg == "strength" and len(sys.argv) > 2:
        os.makedirs(os.path.dirname(STRENGTH), exist_ok=True)
        with open(STRENGTH, "w") as f:
            f.write("%.2f\n" % max(0.05, min(0.6, float(sys.argv[2]))))
        if get() == "on":
            print(apply(True))
        return 0
    if arg not in ("on", "off"):
        print(__doc__, file=sys.stderr)
        return 1
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w") as f:
        f.write(arg + "\n")
    print(apply(arg == "on"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
