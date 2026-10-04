#!/usr/bin/env python3
"""Шрифт JarvisWave — столбики для плавного визуализатора в баре. 30.09.2026.

Waybar рисует модуль только текстом, а плавная «волна» как у Noctalia — это
графика. Поэтому графика запекается в шрифт: символ U+E300+k — столбик шириной
2 px и высотой 2k+2 px, стоящий симметрично по середине строки. cava_bar.py
в режиме «волна» печатает 48 таких символов подряд — получается сплошная
зеркальная волна 96×20 px, и она живёт внутри waybar, без отдельных окон.

Геометрия подогнана под пиксели при кегле 24 px (18 pt при 96 dpi, так его и
задаёт cava_bar.py): unitsPerEm 2400 → 100 единиц на пиксель. Строка 22 px
(ascent 1600, descent 600), середина — 5 px над базовой линией; края столбиков
ровно на границах пикселей, поэтому без размытия.

    python3 build_wave_font.py   → ~/.local/share/fonts/JarvisWave.ttf
"""
import os
import subprocess

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 2400
PX = 100                 # единиц на пиксель при 24 px
ASC, DESC = 1600, 600
MID = 500                # середина строки над базовой линией
COL = 2 * PX             # ширина столбика = 2 px
LEVELS = 10              # 0..9 → высота 2..20 px
BASE = 0xE300
OUT = os.path.expanduser("~/.local/share/fonts/JarvisWave.ttf")


def rect(x0, y0, x1, y1):
    pen = TTGlyphPen(None)
    pen.moveTo((x0, y0))
    pen.lineTo((x0, y1))
    pen.lineTo((x1, y1))
    pen.lineTo((x1, y0))
    pen.closePath()
    return pen.glyph()


def main():
    names = [".notdef", "space"] + ["lv%d" % k for k in range(LEVELS)]
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    cmap = {0x20: "space"}
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph()}
    metrics = {".notdef": (COL, 0), "space": (COL, 0)}
    for k in range(LEVELS):
        half = (k + 1) * PX
        glyphs["lv%d" % k] = rect(0, MID - half, COL, MID + half)
        metrics["lv%d" % k] = (COL, 0)
        cmap[BASE + k] = "lv%d" % k
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASC, descent=-DESC)
    fb.setupNameTable({"familyName": "JarvisWave", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASC, sTypoDescender=-DESC, sTypoLineGap=0,
                usWinAscent=ASC, usWinDescent=DESC, fsSelection=0x40)
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fb.save(OUT)
    subprocess.run(["fc-cache", "-f", os.path.dirname(OUT)], capture_output=True)
    print(OUT)


if __name__ == "__main__":
    main()
