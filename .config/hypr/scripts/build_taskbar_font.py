#!/usr/bin/env python3
"""Шрифт JarvisTaskbar — кнопки «Панели задач» в баре в духе Windows XP. 30.09.2026.

Waybar рисует модуль только текстом, а панель задач — это ряд квадратных кнопок
со значками. Поэтому кнопка собирается из знаков этого шрифта, наложенных друг
на друга (taskbar.py печатает их подряд, каждый своим цветом):

    E510  подложка кнопки 22×22 со срезанными углами     ┐ нулевая ширина:
    E511  кромка сверху и слева (свет у выпуклой кнопки) │ рисуются ПОВЕРХ
    E512  кромка снизу и справа (тень у выпуклой)        │ того, что идёт
    E513  «шахматка» 1 px — нажатая кнопка, как в 9x/XP  │ следом
    E514  полоска внизу — окно требует внимания          ┘
    <значок>  ширина 22 px, рисунок 16×16 по центру кнопки
    E51A/E51B/E51C  пустые промежутки 2 / 4 / 1 px

Нажатая кнопка (окно в фокусе) — те же кромки, только цвета меняются местами:
тень сверху-слева, свет снизу-справа. Шрифт одноцветный, цвета задаёт разметка.

Значки — копии JarvisBarIcons (build_bar_icons.py) на ТЕХ ЖЕ кодах, что в
window-rewrite конфига waybar: taskbar.py печатает тот же символ, что
показывает стол. Здесь они уменьшены до 16 px (размер значков в панели задач XP)
и поставлены по центру кнопки. Порядок сборки: сначала build_bar_icons.py,
потом этот скрипт.

    E520  значок окна без своего правила — пиксельное «окошко»
    E530..E539, E53A  пиксельные цифры 3×5 (клетка 2 px) и «+» — для «+N»

Геометрия под кегль 22 px (taskbar.py печатает font="JarvisTaskbar 22px"):
unitsPerEm 2200 → 100 единиц на экранный пиксель. Строка ровно 22 px (ascent 17,
descent 5), кнопка занимает её целиком — края кромок на границах пикселей.

    python3 build_taskbar_font.py   → ~/.local/share/fonts/JarvisTaskbar-Regular.otf
"""
import os
import subprocess
import sys

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.recordingPen import DecomposingRecordingPen
from fontTools.pens.t2CharStringPen import T2CharStringPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

HOME = os.path.expanduser("~")
SRC = HOME + "/.local/share/fonts/JarvisBarIcons-Regular.otf"
OUT = HOME + "/.local/share/fonts/JarvisTaskbar-Regular.otf"
FAMILY = "JarvisTaskbar"

PX = 100                  # единиц на пиксель при кегле 22 px
B = 22                    # кнопка B×B пикселей
ICON = 16                 # значок ICON×ICON
ASC, DESC = 17, 5         # в пикселях; ASC + DESC = B
UPM = B * PX
MID = (ASC - DESC) / 2    # середина строки над базовой линией, px (6)

FILL, EDGE_TL, EDGE_BR, DITHER, URGENT = 0xE510, 0xE511, 0xE512, 0xE513, 0xE514
GAP2, GAP4, GAP1 = 0xE51A, 0xE51B, 0xE51C
GENERIC = 0xE520
DIGIT0, PLUS = 0xE530, 0xE53A

SKIP = set(range(0x30, 0x3A)) | {0x200B}      # цифры и метка столов — не значки

WINDOW = [                # 16×16: окошко с заголовком
    "................",
    "................",
    ".##############.",
    ".##############.",
    ".##############.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".#............#.",
    ".##############.",
    "................",
    "................",
]

DIGITS = {                # 3×5, клетка 2 px
    "0": ["###", "#.#", "#.#", "#.#", "###"],
    "1": [".#.", "##.", ".#.", ".#.", "###"],
    "2": ["###", "..#", "###", "#..", "###"],
    "3": ["###", "..#", ".##", "..#", "###"],
    "4": ["#.#", "#.#", "###", "..#", "..#"],
    "5": ["###", "#..", "###", "..#", "###"],
    "6": ["###", "#..", "###", "#.#", "###"],
    "7": ["###", "..#", ".#.", ".#.", ".#."],
    "8": ["###", "#.#", "###", "#.#", "###"],
    "9": ["###", "#.#", "###", "..#", "###"],
    "+": ["...", ".#.", "###", ".#.", "..."],
}


def rects_charstring(rects, adv):
    """Charstring из прямоугольников в ПИКСЕЛЯХ (x0, y0, x1, y1), y — от базовой линии."""
    pen = T2CharStringPen(adv * PX, None)
    for x0, y0, x1, y1 in rects:
        pen.moveTo((x0 * PX, y0 * PX))
        pen.lineTo((x0 * PX, y1 * PX))
        pen.lineTo((x1 * PX, y1 * PX))
        pen.lineTo((x1 * PX, y0 * PX))
        pen.closePath()
    return pen.getCharString()


def grid_rects(rows, left, top, cell=1):
    """'#'-клетки рисунка → прямоугольники; left/top — угол рисунка в px (top — от базовой линии вверх)."""
    out = []
    for r, row in enumerate(rows):
        c = 0
        while c < len(row):
            if row[c] != "#":
                c += 1
                continue
            s = c
            while c < len(row) and row[c] == "#":
                c += 1
            out.append((left + s * cell, top - (r + 1) * cell, left + c * cell, top - r * cell))
    return out


def frame_glyphs():
    top, bot = ASC, -DESC
    g = {}
    # Подложка: срезанные на пиксель углы — «скругление» по-пиксельному.
    g[FILL] = [(1, bot, B - 1, top), (0, bot + 1, 1, top - 1), (B - 1, bot + 1, B, top - 1)]
    g[EDGE_TL] = [(1, top - 1, B - 1, top), (0, bot + 1, 1, top - 1)]
    g[EDGE_BR] = [(1, bot, B - 1, bot + 1), (B - 1, bot + 1, B, top - 1)]
    g[DITHER] = [(x, y, x + 1, y + 1) for x in range(1, B - 1) for y in range(bot + 1, top - 1)
                 if (x + y) % 2 == 0]
    g[URGENT] = [(7, bot + 2, B - 7, bot + 4)]
    return g


def icon_charstring(rec):
    """Значок JarvisBarIcons (ячейка 1 em, центр (500, 400)) → ICON px по центру кнопки."""
    scale = ICON * PX / 1000.0
    dx = B * PX / 2 - 500 * scale
    dy = MID * PX - 400 * scale
    pen = T2CharStringPen(B * PX, None)
    rec.replay(TransformPen(pen, (scale, 0, 0, scale, dx, dy)))
    return pen.getCharString()


def main():
    glyphs, metrics, cmap = {}, {}, {}

    def add(code, cs, adv_px):
        name = "u%04X" % code
        glyphs[name], metrics[name], cmap[code] = cs, (int(adv_px * PX), 0), name

    glyphs[".notdef"], metrics[".notdef"] = T2CharStringPen(B * PX, None).getCharString(), (B * PX, 0)

    for code, rects in frame_glyphs().items():
        add(code, rects_charstring(rects, 0), 0)
    for code, w in ((GAP2, 2), (GAP4, 4), (GAP1, 1)):
        add(code, rects_charstring([], w), w)
    pad = (B - ICON) // 2
    add(GENERIC, rects_charstring(grid_rects(WINDOW, pad, MID + ICON / 2), B), B)
    # Цифры: 6×10 px, по вертикали по середине строки, ширина 8 (по 1 px с боков).
    for i, ch in enumerate("0123456789+"):
        rects = grid_rects(DIGITS[ch], 1, MID + 5, cell=2)
        add(DIGIT0 + i if ch != "+" else PLUS, rects_charstring(rects, 8), 8)

    copied, src_missing = 0, not os.path.exists(SRC)
    if not src_missing:
        src = TTFont(SRC)
        gs = src.getGlyphSet()
        for code, gname in sorted(src.getBestCmap().items()):
            if code in SKIP or code in cmap:
                continue
            rec = DecomposingRecordingPen(gs)
            gs[gname].draw(rec)
            bp = BoundsPen(None)
            rec.replay(bp)
            if not bp.bounds:
                continue
            add(code, icon_charstring(rec), B)
            copied += 1

    order = [".notdef"] + sorted(n for n in glyphs if n != ".notdef")
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(FAMILY + "-Regular", {"FullName": FAMILY, "FamilyName": FAMILY}, glyphs, {})
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASC * PX, descent=-DESC * PX)
    fb.setupNameTable({"familyName": FAMILY, "styleName": "Regular", "psName": FAMILY + "-Regular"})
    fb.setupOS2(sTypoAscender=ASC * PX, sTypoDescender=-DESC * PX, sTypoLineGap=0,
                usWinAscent=ASC * PX, usWinDescent=DESC * PX, fsSelection=0x40)
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    # Новый файл и подмена, а не запись поверх: открытый шрифт держат waybar и
    # другие, перезапись на месте роняет их (SIGBUS — так упал Telegram 23.09).
    fb.save(OUT + ".tmp")
    os.replace(OUT + ".tmp", OUT)
    subprocess.run(["fc-cache", "-f", os.path.dirname(OUT)], capture_output=True)
    print("шрифт: %s" % OUT)
    print("значков из JarvisBarIcons: %d%s" % (copied, " (ИСТОЧНИК НЕ НАЙДЕН: %s)" % SRC if src_missing else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
