#!/usr/bin/env python3
"""Шрифт JarvisBongo — Bongo Cat для waybar. 30.09.2026.

Waybar рисует модуль только текстом, поэтому кот запекается в шрифт, как
волна в JarvisWave (build_wave_font.py): каждый «пиксель» рисунка — квадрат
в единицах шрифта, края ровно на границах экранных пикселей, без размытия.
Кот одноцветный — цвет берётся из CSS (color у #custom-bongo), значит идёт
за акцентом обоев.

Знаки (U+E400..):
    E400  обе лапы подняты (покой)
    E401  левая лапа бьёт по столу
    E402  правая лапа бьёт
    E403  обе бьют

Геометрия под кегль 24 px (18 pt при 96 dpi, так его печатает bongo_cat.py):
unitsPerEm 2400 → 100 единиц на экранный пиксель. Рисунок W×H пикселей,
строка шрифта ровно H px, так что waybar центрирует его по высоте сам.

    python3 build_bongo_font.py              → ~/.local/share/fonts/JarvisBongo.ttf
    python3 build_bongo_font.py --preview DIR → PNG кадров (×1 и ×6) без установки
"""
import os
import subprocess
import sys

UPM = 2400
PX = 100                 # единиц на экранный пиксель при 24 px
BASE = 0xE400
OUT = os.path.expanduser("~/.local/share/fonts/JarvisBongo.ttf")

# ── Рисунок ────────────────────────────────────────────────────────────────
# '#' — закрашено, '.' — пусто. Кот нарисован контуром: сплошной силуэт в баре
# читается как клякса, а контур с глазами и «ω» — как тот самый кот.
# Лапы накладываются поверх: в спрайте лапы 'o' — стереть (внутренность лапы
# закрывает контур тела), '#' — закрасить, '.' — не трогать.
BODY = [
    "................................",
    "........#..............#........",
    ".......#.#............#.#.......",
    ".......#..#..........#..#.......",
    "......#....##########....#......",
    ".....#....................#.....",
    ".....#....................#.....",
    "....#......#........#......#....",
    "....#......#........#......#....",
    "....#.........#.#.#........#....",
    "....#..........#.#.........#....",
    "....#......................#....",
    "....#......................#....",
    "....#......................#....",
    "################################",
    "................................",
    "................................",
]

# Лапа поднята: предплечье встаёт из-за стола аркой «∩». Открытый низ важен:
# замкнутый овал на лице читался как глаз-«0».
PAW_UP = [
    ".##.",
    "#oo#",
    "#oo#",
    "#oo#",
    "#oo#",
]
# Лапа на столе: приплюснутая, лежит прямо на линии стола, рука на 1 px
# ближе к краю — «замах».
PAW_DOWN = [
    ".####.",
    "#oooo#",
]
# Черточки удара — снаружи тела, у края стола с той же стороны.
HIT_L = ["#..", ".#.", "..#"]
HIT_R = ["..#", ".#.", "#.."]

TABLE_Y = 14
UP_Y = 9                      # верх поднятой лапы
LEFT_X, RIGHT_X = 7, 21       # левый край поднятой лапы
DOWN_LX, DOWN_RX = 6, 20      # левый край лапы на столе (перед телом)


def blank():
    return [list(r) for r in BODY]


def stamp(g, sprite, x0, y0):
    for dy, row in enumerate(sprite):
        for dx, ch in enumerate(row):
            y, x = y0 + dy, x0 + dx
            if not (0 <= y < len(g) and 0 <= x < len(g[0])):
                continue
            if ch == "#":
                g[y][x] = "#"
            elif ch == "o":
                g[y][x] = "."


def paw(g, side, down):
    x = LEFT_X if side == "L" else RIGHT_X
    if down:
        xd = DOWN_LX if side == "L" else DOWN_RX
        stamp(g, PAW_DOWN, xd, TABLE_Y - len(PAW_DOWN))
        if side == "L":
            stamp(g, HIT_L, 0, TABLE_Y - 4)
        else:
            stamp(g, HIT_R, len(BODY[0]) - 3, TABLE_Y - 4)
    else:
        stamp(g, PAW_UP, x, UP_Y)


def frame(left_down, right_down):
    g = blank()
    paw(g, "L", left_down)
    paw(g, "R", right_down)
    return ["".join(r) for r in g]


FRAMES = [
    ("idle", frame(False, False)),
    ("left", frame(True, False)),
    ("right", frame(False, True)),
    ("both", frame(True, True)),
]
W = len(BODY[0])
H = len(BODY)


# ── Шрифт ──────────────────────────────────────────────────────────────────
def glyph_from(bitmap):
    """Контур из закрашенных пикселей: подряд идущие в строке сливаются в один
    прямоугольник (меньше контуров, без щелей на стыках при растеризации)."""
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    pen = TTGlyphPen(None)
    for r, row in enumerate(bitmap):
        y_top = (H - r) * PX - DESC_U     # строка 0 — верх
        y_bot = y_top - PX
        x = 0
        while x < W:
            if row[x] != "#":
                x += 1
                continue
            s = x
            while x < W and row[x] == "#":
                x += 1
            pen.moveTo((s * PX, y_bot))
            pen.lineTo((s * PX, y_top))
            pen.lineTo((x * PX, y_top))
            pen.lineTo((x * PX, y_bot))
            pen.closePath()
    return pen.glyph()


# Строка шрифта = высота рисунка. Базовая линия — на 3 px выше низа
# (обычное соотношение, чтобы pango не сдвигал строку относительно соседей).
DESC_U = 3 * PX
ASC_U = H * PX - DESC_U


def build():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    names = [".notdef", "space"] + [n for n, _ in FRAMES]
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(names)
    cmap = {0x20: "space"}
    glyphs = {".notdef": TTGlyphPen(None).glyph(), "space": TTGlyphPen(None).glyph()}
    adv = W * PX
    metrics = {".notdef": (adv, 0), "space": (adv, 0)}
    for i, (name, bm) in enumerate(FRAMES):
        glyphs[name] = glyph_from(bm)
        metrics[name] = (adv, 0)
        cmap[BASE + i] = name
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASC_U, descent=-DESC_U)
    fb.setupNameTable({"familyName": "JarvisBongo", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASC_U, sTypoDescender=-DESC_U, sTypoLineGap=0,
                usWinAscent=ASC_U, usWinDescent=DESC_U, fsSelection=0x40)
    fb.setupPost()
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    fb.save(OUT)
    subprocess.run(["fc-cache", "-f", os.path.dirname(OUT)], capture_output=True)
    print(OUT)


def preview(d):
    from PIL import Image
    os.makedirs(d, exist_ok=True)
    sheet = Image.new("RGB", ((W + 2) * len(FRAMES) * 6, (H + 2) * 6), (24, 24, 32))
    for i, (name, bm) in enumerate(FRAMES):
        im = Image.new("RGB", (W, H), (24, 24, 32))
        for y, row in enumerate(bm):
            for x, ch in enumerate(row):
                if ch == "#":
                    im.putpixel((x, y), (180, 190, 255))
        im.save(os.path.join(d, "bitmap-%s.png" % name))
        big = im.resize((W * 6, H * 6), Image.NEAREST)
        sheet.paste(big, ((W + 2) * 6 * i, 6))
    sheet.save(os.path.join(d, "bitmap-sheet-x6.png"))
    for name, bm in FRAMES:
        print(name)
        print("\n".join(bm))


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    else:
        build()
