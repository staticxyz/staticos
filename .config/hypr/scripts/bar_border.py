#!/usr/bin/env python3
"""Рамка вокруг бара (13.10.2026: толщиной, а не только вкл/выкл).

    bar_border.py get          толщина в px (0 — рамки нет)
    bar_border.py set N        0…4 px; on = 1, off = 0 (как раньше)

Рамка рисуется inset box-shadow, а не border: border прибавил бы высоты окну бара, и
приклеенные попапы (они считают высоту бара по конфигу) разошлись бы с его краем.
Цвет — акцент обоев, как у рамки окон niri.
"""
import os
import re
import subprocess
import sys

BORDER_CSS = os.path.expanduser("~/.config/waybar/looks/bar-border.css")
MAX = 4
CSS_ON = """/* Рамка бара %d px — bar_border.py (Настройки → Waybar) */
window#waybar {
    box-shadow: inset 0 0 0 %dpx alpha(@primary, 0.45);
}
"""
CSS_OFF = "/* bar-border: off */\n"


def get():
    try:
        content = open(BORDER_CSS).read()
    except OSError:
        return 0
    m = re.search(r"inset 0 0 0 (\d+)px", content)
    if m:
        return int(m.group(1))
    return 1 if "border-bottom" in content else 0     # старый вид «on» — линия снизу


def set_width(raw):
    raw = {"on": "1", "true": "1", "off": "0", "false": "0"}.get(raw, raw)
    try:
        n = max(0, min(MAX, int(round(float(raw)))))
    except ValueError:
        return None
    os.makedirs(os.path.dirname(BORDER_CSS), exist_ok=True)
    tmp = BORDER_CSS + ".tmp"
    with open(tmp, "w") as f:
        f.write(CSS_ON % (n, n) if n else CSS_OFF)
    os.replace(tmp, BORDER_CSS)
    # waybar перечитывает стиль по ЗАПИСИ в свой файл (смены времени мало — как в
    # desktop_widgets.write_bar_css); под niri это style-niri.css
    for name in ("style-niri.css", "style.css"):
        style = os.path.expanduser("~/.config/waybar/" + name)
        try:
            txt = open(style, encoding="utf-8").read()
            with open(style, "w", encoding="utf-8") as f:
                f.write(txt)
            break
        except OSError:
            continue
    return n


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "set" and len(args) == 2:
        n = set_width(args[1])
        if n is None:
            print(__doc__, file=sys.stderr)
            return 1
        print(n)
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
