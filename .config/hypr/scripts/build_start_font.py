#!/usr/bin/env python3
"""Шрифт JarvisStart — пиксельный логотип Arch для кнопки «Пуск» в баре. 30.09.2026.

Кнопка «Пуск» (custom/launcher) умеет два вида, их переключает start_button.py:
    nerd   — прежний знак 󰣇 (md-arch) из JarvisBarIcons, гладкий;
    pixel  — этот шрифт: тот же треугольный логотип Arch, нарисованный по
             пикселям, как значки Windows 9x/XP.

Waybar рисует модуль только текстом, поэтому рисунок запекается в шрифт — приём
тот же, что у JarvisWave и JarvisBongo: каждый «пиксель» рисунка — квадрат
в единицах шрифта, края ровно на границах экранных пикселей, без размытия.

Геометрия под кегль 16 px (так его печатает start_button.py: font="JarvisStart
16px"): unitsPerEm 1600 → 100 единиц на экранный пиксель. Строка шрифта ровно
16 px (ascent 13, descent 3) — столько же, сколько у знака JarvisBarIcons при
16 px, поэтому таблетка кнопки (20 px, см. #custom-launcher) не меняется.

Знаки:
    E500  логотип Arch 16×16
    E501  зарезервирован под будущий вид «xp» (флажок) — пока не рисуется

    python3 build_start_font.py              → ~/.local/share/fonts/JarvisStart.ttf
    python3 build_start_font.py --preview DIR → PNG рисунка (×1 и ×8) без установки
"""
import os
import subprocess
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

N = 16                    # рисунок N×N пикселей
PX = 100                  # единиц на пиксель при кегле N px
UPM = N * PX
ASC, DESC = 13 * PX, 3 * PX
BASE = 0xE500
OUT = os.path.expanduser("~/.local/share/fonts/JarvisStart.ttf")

# Логотип Arch — крупным пикселем (01.10.2026, просьба: «сделай более пиксельным»).
# Рисунок 8×8, каждый его пиксель — квадрат 2×2 экранных: ступеньки видны
# глазом, как у значков 16-цветных игр. Прежний вариант 16×16 с тонкой аркой
# на панели читался почти гладким. Вершина в два столбца, «арка» снизу.
ARCH8 = [
    "...##...",
    "...##...",
    "..####..",
    "..####..",
    ".######.",
    ".##..##.",
    "##....##",
    "#......#",
]
ARCH = [row.replace("#", "##").replace(".", "..") for row in ARCH8 for _ in (0, 1)]


def glyph(rows):
    """Контур из рядов '#': соседние закрашенные клетки ряда — одна полоса."""
    pen = TTGlyphPen(None)
    for r, row in enumerate(rows):
        y1 = ASC - r * PX
        y0 = y1 - PX
        c = 0
        while c < len(row):
            if row[c] != "#":
                c += 1
                continue
            s = c
            while c < len(row) and row[c] == "#":
                c += 1
            x0, x1 = s * PX, c * PX
            pen.moveTo((x0, y0))
            pen.lineTo((x0, y1))
            pen.lineTo((x1, y1))
            pen.lineTo((x1, y0))
            pen.closePath()
    return pen.glyph()


def build():
    assert len(ARCH) == N and all(len(r) == N for r in ARCH)
    names = [".notdef", "space", "arch"]
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({0x20: "space", BASE: "arch"})
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({".notdef": empty, "space": empty, "arch": glyph(ARCH)})
    fb.setupHorizontalMetrics({".notdef": (UPM, 0), "space": (UPM // 2, 0), "arch": (UPM, 0)})
    fb.setupHorizontalHeader(ascent=ASC, descent=-DESC)
    fb.setupNameTable({"familyName": "JarvisStart", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASC, sTypoDescender=-DESC, sTypoLineGap=0,
                usWinAscent=ASC, usWinDescent=DESC, fsSelection=0x40)
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Новый файл и подмена, а не запись поверх: открытый шрифт держат waybar и
    # другие, перезапись на месте роняет их (SIGBUS — так упал Telegram 23.09).
    fb.save(OUT + ".tmp")
    os.replace(OUT + ".tmp", OUT)
    subprocess.run(["fc-cache", "-f", os.path.dirname(OUT)], capture_output=True)
    print(OUT)


def preview(out_dir):
    from PIL import Image
    im = Image.new("RGBA", (N, N), (0, 0, 0, 0))
    for r, row in enumerate(ARCH):
        for c, ch in enumerate(row):
            if ch == "#":
                im.putpixel((c, r), (180, 197, 255, 255))
    os.makedirs(out_dir, exist_ok=True)
    im.save(os.path.join(out_dir, "start-arch-x1.png"))
    im.resize((N * 8, N * 8), Image.NEAREST).save(os.path.join(out_dir, "start-arch-x8.png"))
    print(out_dir)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    else:
        build()
