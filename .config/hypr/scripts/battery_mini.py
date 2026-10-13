#!/usr/bin/env python3
"""Батарейка капсулой для бара вида Minimalistic (13.10.2026, по образцу пользователя — как на
iPhone: залитая капсула с «носиком», без цифр). Шрифтом так не нарисовать: заливка по
уровню и тусклый остаток — это картинка. Скрипт рисует PNG и печатает для модуля
waybar `image` путь и подсказку (две строки). Картинки кэшируются по уровню/цвету/зарядке.

    battery_mini.py          путь картинки и подсказка для waybar
    battery_mini.py --shot F нарисовать в файл F крупно (проверка)

Цвет — акцент обоев (primary из matugen), ниже 20 % — красный. Зарядка — тёмная молния.
"""
import os
import re
import sys

from PIL import Image, ImageDraw

BAT = "/sys/class/power_supply/BAT0"
COLORS = os.path.expanduser("~/.cache/matugen/colors.css")
CACHE = os.path.expanduser("~/.cache/jarvis/battery-mini")
W, H, SS = 28, 13, 4                       # размер в пикселях экрана, сглаживание ×4


def read(name, default=""):
    try:
        with open(os.path.join(BAT, name)) as f:
            return f.read().strip()
    except OSError:
        return default


def accent():
    try:
        m = re.search(r"@define-color\s+primary\s+(#[0-9a-fA-F]{6})", open(COLORS).read())
        if m:
            return m.group(1)
    except OSError:
        pass
    return "#b4c5ff"


def rgb(h, a=255):
    return (int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16), a)


def draw(cap, color, charging, scale=SS):
    w, h = W * scale, H * scale
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    body_w = 24 * scale
    r = h // 2 - scale // 2
    d.rounded_rectangle((0, 0, body_w - 1, h - 1), radius=r, fill=rgb(color, 70))   # тусклый остаток
    fill_w = max(int(body_w * cap / 100), h)                                         # не уже круга
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, body_w - 1, h - 1), radius=r, fill=255)
    lvl = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(lvl).rectangle((0, 0, fill_w - 1, h - 1), fill=rgb(color))
    im.paste(lvl, (0, 0), Image.composite(lvl, Image.new("RGBA", (w, h)), mask).split()[3])
    nub_h = 5 * scale
    d.rounded_rectangle((body_w + scale, (h - nub_h) // 2, body_w + 3 * scale - 1, (h + nub_h) // 2),
                        radius=scale, fill=rgb(color, 110))
    if charging:                                                                    # молния
        cx, s = body_w // 2, scale
        d.polygon([(cx + 1 * s, 1.5 * s), (cx - 3 * s, 7 * s), (cx - 0.3 * s, 7 * s),
                   (cx - 1 * s, 11.5 * s), (cx + 3 * s, 6 * s), (cx + 0.3 * s, 6 * s)], fill=(0, 0, 0, 230))
    return im.resize((W, H), Image.LANCZOS) if scale == SS else im


def main(a):
    try:
        cap = max(0, min(100, int(read("capacity", "0"))))
    except ValueError:
        cap = 0
    status = read("status", "Unknown")
    charging = status == "Charging"
    color = "#ff6b6b" if cap < 20 and not charging else accent()
    if a[:1] == ["--shot"] and len(a) == 2:
        draw(cap, color, charging, scale=16).save(a[1])
        return 0
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, "b%d-%s%s.png" % (cap, color[1:], "-c" if charging else ""))
    if not os.path.exists(path):
        draw(cap, color, charging).save(path)
    tip = "Батарея: %d%%%s" % (cap, ", заряжается" if charging else "")
    print(path + "\n" + tip, flush=True)     # модуль image: 1-я строка — путь, 2-я — подсказка
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
