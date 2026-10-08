#!/usr/bin/env python3
"""Обои «искорки»: узор фона Telegram (искорка кнопки «Пуск», «+», крестики,
точки) на весь экран. Плитка та же, что в telegram_colors.py, только пиксели
крупнее (без размытия) и звёзды ярче — на столе их не перекрывает текст.

    sparkle_wallpaper.py [--bg #10131c] [--acc #b4c5ff] [--scale 2]
                         [--gain 1.8] [--size 1920x1080] [-o ФАЙЛ]

Цвета по умолчанию — роли surface и primary текущей палитры. Обои сами задают
палитру (matugen), поэтому файл не перекрашивается при смене обоев: это
снимок цветов на момент сборки (08.10.2026).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import telegram_colors as tc  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bg")
    ap.add_argument("--acc")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--gain", type=float, default=1.8)
    ap.add_argument("--size", default="1920x1080")
    ap.add_argument("-o", "--out", default=os.path.expanduser(
        "~/wallpapers/main/staticos-sparkle-pixelart.png"))
    a = ap.parse_args()
    if not (a.bg and a.acc):
        roles = tc.load_roles()
        a.bg = a.bg or roles["surface"]
        a.acc = a.acc or roles["primary"]
    w, h = (int(v) for v in a.size.split("x"))

    tile = tc._sparkle_tile(a.bg, a.acc, gain=a.gain)
    n, s = tc.TILE, a.scale
    # Плитка бесшовная, поэтому экран собирается взятием по модулю; каждый
    # пиксель плитки — квадрат s×s, как у пиксель-арта.
    rows = []
    for y in range(h):
        src = tile[(y // s) % n]
        rows.append([src[(x // s) % n] for x in range(w)])
    tmp = a.out + ".tmp"
    with open(tmp, "wb") as f:
        f.write(tc._png(rows))
    os.replace(tmp, a.out)
    print("sparkle_wallpaper: %s (%dx%d, ×%d, фон %s, звёзды %s)"
          % (a.out, w, h, s, a.bg, a.acc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
