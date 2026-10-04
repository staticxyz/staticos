#!/usr/bin/env python3
"""Какое меню питания открывает кнопка в баре (и «Выключение» в «Пуске»). 01.10.2026.

    power_view.py get                 wlogout | jarvis
    power_view.py set wlogout|jarvis  выбрать (Настройки → Power → «Меню питания»)
    power_view.py open [--pointer]    открыть выбранное

wlogout — большие значки на весь экран, как было (выбор пользователя 30.09).
jarvis  — своё меню power_menu.py: рамка, пять кнопок, отсчёт с кольцом.
Просьба: «хочу переключатель вида; доп. вид — то, что ты делал ранее, с рамкой и
кнопками». Состояние — ~/.config/hypr/state/power-view.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/power-view")
VIEWS = ("wlogout", "jarvis")


def get():
    try:
        v = open(STATE).read().strip()
        return v if v in VIEWS else "wlogout"
    except OSError:
        return "wlogout"


def main():
    a = sys.argv[1:]
    if not a or a[0] == "get":
        print(get())
    elif a[0] == "set" and len(a) > 1 and a[1] in VIEWS:
        os.makedirs(os.path.dirname(STATE), exist_ok=True)
        with open(STATE, "w") as f:
            f.write(a[1] + "\n")
        print(a[1])
    elif a[0] == "open":
        if get() == "jarvis":
            cmd = [sys.executable, os.path.join(HERE, "power_menu.py")] + \
                  (["--pointer"] if "--pointer" in a else [])
        else:
            cmd = ["wlogout", "-b", "6", "-l", os.path.expanduser("~/.config/wlogout/layout"),
                   "-C", os.path.expanduser("~/.config/wlogout/style.css")]
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
