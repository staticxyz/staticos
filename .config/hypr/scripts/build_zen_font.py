#!/usr/bin/env python3
"""Собрать шрифт с одним глифом — логотипом Zen (копия build_wolf_font.py, 15.09.2026).

Зачем: waybar принимает в список рабочих столов только ТЕКСТ. Картинку туда
положить нельзя — в разметке Pango нет тега изображения, а CSS не умеет
выбирать кнопку по её содержимому. Поэтому логотип превращается в глиф
собственного шрифта и ставится на код U+E101 (у LibreWolf — U+E100 в WolfGlyph).

Код выбран не наугад: Nerd Font плотно занимает частную зону Unicode, и
первый очевидный U+E900 у него свой — вместо волка рисовался чужой значок.
U+E100 лежит в полосе, свободной в JetBrainsMono (проверено по таблице
символов шрифта).

Путь: PNG -> маска -> potrace (вектор) -> контуры -> OTF.

OTF, а не TTF, намеренно: potrace выдаёт кубические кривые Безье, и формат
CFF внутри OTF хранит их как есть. В TrueType кривые квадратичные, и их
пришлось бы пересчитывать с потерей точности.
"""
import os
import re
import subprocess
import sys
import tempfile

from PIL import Image
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.t2CharStringPen import T2CharStringPen

SRC = os.path.expanduser("~/.local/opt/zen/browser/chrome/icons/default/default128.png")
OUT = os.path.expanduser("~/.local/share/fonts/ZenGlyph-Regular.otf")
CODEPOINT = 0xE101
UPM = 1000


def make_mask(path):
    """Волк светлый, подложка синяя — берём светлые пиксели.

    Порог по альфе отсекает полупрозрачную кромку сглаживания: без него
    кольцо обводилось рябым, в крапинку.
    """
    src = Image.open(SRC).convert("RGBA")
    w, h = src.size
    bmp = Image.new("L", (w, h), 255)
    sp, bp = src.load(), bmp.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = sp[x, y]
            if a > 200 and r > 190 and (b - r) < 30:
                bp[x, y] = 0
    bmp.save(path)
    return w, h


def trace(pbm):
    svg = pbm + ".svg"
    subprocess.run(["potrace", "-s", "-o", svg, "--flat", "-a", "1.0", "-O", "0.2", pbm],
                   check=True, capture_output=True)
    return open(svg).read()


def parse_paths(svg):
    """Разобрать d-атрибуты. potrace выдаёт M/m/l/c/z, координаты в 1/10 px."""
    out = []
    for d in re.findall(r'\sd="([^"]+)"', svg):
        nums = re.compile(r"[-+]?\d*\.?\d+")
        i, cur, start = 0, (0.0, 0.0), (0.0, 0.0)
        contour, cmd = [], None
        toks = re.findall(r"[A-Za-z]|[-+]?\d*\.?\d+", d)
        while i < len(toks):
            t = toks[i]
            if t.isalpha():
                cmd = t; i += 1
                if cmd in "zZ":
                    if contour: out.append(contour); contour = []
                    cur = start
                continue
            v = lambda k: float(toks[i + k])
            if cmd in "Mm":
                x, y = (v(0), v(1))
                if cmd == "m": x, y = cur[0] + x, cur[1] + y
                if contour: out.append(contour); contour = []
                cur = start = (x, y); contour.append(("move", cur)); i += 2
            elif cmd in "Ll":
                x, y = (v(0), v(1))
                if cmd == "l": x, y = cur[0] + x, cur[1] + y
                cur = (x, y); contour.append(("line", cur)); i += 2
            elif cmd in "Cc":
                pts = [(v(0), v(1)), (v(2), v(3)), (v(4), v(5))]
                if cmd == "c":
                    pts = [(cur[0] + px, cur[1] + py) for px, py in pts]
                contour.append(("curve", pts)); cur = pts[-1]; i += 6
            else:
                i += 1
        if contour: out.append(contour)
    return out


def main():
    with tempfile.TemporaryDirectory() as tmp:
        pbm = os.path.join(tmp, "m.pbm")
        w, h = make_mask(pbm)
        contours = parse_paths(trace(pbm))

    # potrace: координаты в 1/10 пикселя, ось Y уже направлена вверх
    # (transform="translate(0,H) scale(0.1,-0.1)"), пересчёт не нужен.
    span = h * 10.0
    # 1.10 кегля — глиф намеренно крупнее em-квадрата. Начинал с 0.78,
    # волк выглядел мельче соседних значков.
    # dy пересчитан так, чтобы оптический центр глифа остался на той же
    # высоте — иначе увеличенный волк поехал бы вверх относительно цифр.
    k = (UPM * 1.10) / span
    dy = -UPM * 0.22
    tr = lambda p: (round(p[0] * k), round(p[1] * k + dy))

    pen = T2CharStringPen(UPM, None)
    for c in contours:
        started = False
        for kind, val in c:
            if kind == "move":
                if started: pen.closePath()
                pen.moveTo(tr(val)); started = True
            elif kind == "line":
                pen.lineTo(tr(val))
            else:
                pen.curveTo(*[tr(p) for p in val])
        if started: pen.closePath()

    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder([".notdef", "wolf"])
    fb.setupCharacterMap({CODEPOINT: "wolf"})
    empty = T2CharStringPen(UPM, None); empty.moveTo((0, 0)); empty.closePath()
    fb.setupCFF("ZenGlyph",
                {"FullName": "Zen Glyph", "FamilyName": "ZenGlyph"},
                {".notdef": empty.getCharString(), "wolf": pen.getCharString()},
                {})
    # Шаг как у значков Nerd Font — 0.6 кегля: они тоже рисуются шире своей
    # ячейки. При шаге 1.20 логотип отодвигал соседние значки, и в баре между
    # ними зиял пробел (замечено 20.09.2026).
    adv = round(UPM * 0.60)
    fb.setupHorizontalMetrics({".notdef": (adv, 0), "wolf": (adv, 0)})
    fb.setupHorizontalHeader(ascent=round(UPM * 0.8), descent=-round(UPM * 0.2))
    fb.setupNameTable({"familyName": "ZenGlyph", "styleName": "Regular",
                       "psName": "ZenGlyph-Regular"})
    fb.setupOS2(sTypoAscender=round(UPM * 0.8), usWinAscent=round(UPM * 0.8),
                usWinDescent=round(UPM * 0.2))
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fb.save(OUT)
    print("шрифт: %s" % OUT)
    print("контуров: %d, глиф на U+%04X" % (len(contours), CODEPOINT))
    return 0


if __name__ == "__main__":
    sys.exit(main())
