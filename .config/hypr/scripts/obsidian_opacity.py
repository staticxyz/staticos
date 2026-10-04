#!/usr/bin/env python3
"""Прозрачность окон Obsidian.

    obsidian_opacity.py get        текущее значение в процентах (70..100)
    obsidian_opacity.py set N      применить сразу ко всем окнам и запомнить

Значение хранится в ~/.config/hypr/state/obsidian-opacity. Неактивное окно на
3% прозрачнее активного. Ползунок — в «Настройках» → «Окна» → «Вид окон».

Как применяется (14.09.2026):
  * visuals.lua при загрузке читает файл и ставит правило окна для класса
    md.obsidian.Obsidian, а обработчик window.open применяет значение к каждому
    новому окну — так новое значение действует без перечитывания конфига;
  * этот скрипт после записи зовёт obsidian_opacity_apply() из visuals.lua:
    она проходит по открытым окнам Obsidian и ставит им прозрачность через
    hl.dsp.window.set_prop (проверено на пробном окне: prop "opacity" берёт одно
    число, у неактивного — отдельный prop "opacity_inactive").
Цвета не затрагиваются: палитра обоев приходит в Obsidian CSS-сниппетом matugen.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import niri_state  # noqa: E402

STATE = os.path.expanduser("~/.config/hypr/state/obsidian-opacity")
DEFAULT = 96   # просьба: 92/88 оказалось слишком прозрачно — «менее прозрачнее»
LO, HI = 70, 100


def get():
    try:
        with open(STATE) as f:
            return max(LO, min(HI, int(float(f.read().strip()))))
    except (OSError, ValueError):
        return DEFAULT


def set_value(n):
    n = max(LO, min(HI, int(round(float(n)))))
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % n)
    os.replace(tmp, STATE)
    if wm.which() == "niri":
        # В Niri прозрачность программы — правило окна в конфиге (21.09.2026).
        return n, niri_state.apply()
    r = subprocess.run(["hyprctl", "eval", "obsidian_opacity_apply()"],
                       capture_output=True, text=True)
    return n, (r.stdout + r.stderr).strip()


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "set" and len(args) == 2:
        try:
            n, answer = set_value(args[1])
        except ValueError:
            print("нужно число", file=sys.stderr)
            return 1
        print("прозрачность Obsidian: %d%% (%s)" % (n, answer))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
