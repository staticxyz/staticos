#!/usr/bin/env python3
"""Фокус при наведении мыши: следовать или отделить.

    mouse_focus.py get             follow / detached
    mouse_focus.py follow|detached переключить (сразу, без перезагрузки)

follow   (input:follow_mouse = 1) — наведение курсора переводит фокус на окно.
detached (input:follow_mouse = 2) — наведение отдаёт окну только МЫШЬ, а
         клавиатура остаётся там, где вы кликнули последний раз.

Зачем: в ленте (scrolling) фокус тянет за собой вид — стоит задеть мышью
край соседней колонки, как лента прокручивается к ней, и текущее окно
уезжает за край. При «отделить» этого не происходит, а щелчок по окну
по-прежнему переводит фокус.

Выбор хранится в ~/.config/hypr/state/mouse-focus; input.lua читает его при
загрузке, так что он переживает перезапуск Hyprland. Переключатель — в
«Настройках» → «Внешний вид» → «Окна».
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import niri_state  # noqa: E402

STATE = os.path.expanduser("~/.config/hypr/state/mouse-focus")
MODES = {"follow": 1, "detached": 2}
DEFAULT = "detached"


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
    if wm.which() == "niri":
        # В Niri это строка input/focus-follows-mouse в конфиге (21.09.2026).
        return niri_state.apply()
    r = subprocess.run(["hyprctl", "eval",
                        "hl.config({ input = { follow_mouse = %d } })" % MODES[mode]],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def main():
    args = sys.argv[1:] or ["get"]
    if args == ["get"]:
        print(get())
        return 0
    if len(args) == 1 and args[0] in MODES:
        save(args[0])
        print("фокус мыши: %s (%s)" % (args[0], apply(args[0])))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
