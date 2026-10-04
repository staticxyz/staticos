#!/usr/bin/env python3
"""Скругление углов окон Hyprland.

    window_rounding.py get        текущее значение из файла состояния (px)
    window_rounding.py set N      применить сразу и запомнить (0..24)

Значение хранится в ~/.config/hypr/state/window-rounding; visuals.lua читает
его при загрузке, поэтому оно переживает перезапуск Hyprland. Ползунок —
в «Настройках» → «Окна».

14.09.2026: пользователь попросил углы квадратнее — было 12, стало 6, потом 4.
Задумка — единое скругление на всю систему (комментарий в visuals.lua), но
этот скрипт управляет только окнами: у бара, попапов и rofi значения
прописаны в их файлах отдельно.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import niri_state  # noqa: E402

STATE = os.path.expanduser("~/.config/hypr/state/window-rounding")
DEFAULT = 4
LO, HI = 0, 24


def get():
    try:
        with open(STATE) as f:
            return max(LO, min(HI, int(f.read().strip())))
    except (OSError, ValueError):
        return DEFAULT


def set_value(n):
    n = max(LO, min(HI, int(n)))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % n)
    os.replace(tmp, STATE)
    if wm.which() == "niri":
        # В Niri скругление живёт в конфиге — его правит niri_state (21.09.2026).
        return n, niri_state.apply()
    r = subprocess.run(["hyprctl", "eval",
                        "hl.config({ decoration = { rounding = %d } })" % n],
                       capture_output=True, text=True)
    return n, (r.stdout + r.stderr).strip()


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "set" and len(args) == 2:
        try:
            n, answer = set_value(float(args[1]))
        except ValueError:
            print("нужно число", file=sys.stderr)
            return 1
        print("скругление окон: %d px (%s)" % (n, answer))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
