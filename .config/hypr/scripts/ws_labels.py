#!/usr/bin/env python3
"""Чем подписаны столы в баре: значками программ или номерами. 21.09.2026.

    ws_labels.py get             icons | numbers
    ws_labels.py icons|numbers   переключить

Значок берётся у ПЕРВОЙ программы стола — самой левой колонки ленты. Пустой
стол всегда показывает номер, даже в режиме значков: показывать там нечего.

Сама подпись проставляется службой ~/.config/niri/scripts/niri_bar.py names:
модуль niri/workspaces в waybar умеет показывать имя стола, но не умеет значки
окон, поэтому значок вписывается в ИМЯ. Правила значков — общие с Hyprland,
из window-rewrite в ~/.config/waybar/config.jsonc.
"""
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.config/hypr/state/ws-labels")
DEFAULT = "icons"


def get():
    try:
        with open(STATE) as f:
            v = f.read().strip()
        return v if v in ("icons", "numbers") else DEFAULT
    except OSError:
        return DEFAULT


def put(value):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, STATE)
    # Служба сама перечитывает файл при каждом событии, но подписи обновятся
    # только к следующему открытию окна — поэтому подталкиваем её сразу.
    subprocess.run(["python3", os.path.expanduser("~/.config/niri/scripts/niri_bar.py"),
                    "relabel"], capture_output=True)


def main():
    args = sys.argv[1:]
    if args == ["get"]:
        print(get())
    elif args and args[0] in ("icons", "numbers"):
        put(args[0])
        print("подписи столов:", args[0])
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
