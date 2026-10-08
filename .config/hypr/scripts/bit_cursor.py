#!/usr/bin/env python3
"""Курсор «Jarvis Bit» — свой пиксельный набор в цветах обоев. 07.10.2026.

Просьба: «а можешь сам попробовать создать пиксельный курсор? Под акценты обоев».

Каждая фигура — маска на сетке 16×16 (F — заливка акцентом, L — светлый край, D — тёмная
деталь внутри). Контур (почти чёрный) и светлый ореол снаружи достраиваются сами: так все
фигуры в одной манере, а рисовать надо только «тело». Размеры — целые кратные сетки:
16, 32, 48; 20 и 24 — ×1.25 / ×1.5 (края чуть неровнее). Тема собирается попеременно в
Jarvis-Bit-A / -B (niri не перечитывает курсор, пока имя темы то же).

    bit_cursor.py build [ТЕКУЩЕЕ]   собрать в свободный A/B, имя — в stdout
    bit_cursor.py sheet ФАЙЛ        лист со всеми курсорами (проверка вида)
Включает cursor_theme.py (Настройки → «Тема курсора» → Jarvis Bit).
"""
import json
import os
import pathlib
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cursor_colors  # noqa: E402  (write_xcursor, синонимы имён)

HOME = pathlib.Path.home()
ICONS = HOME / ".local/share/icons"
NAMES = ("Jarvis-Bit-A", "Jarvis-Bit-B")
PALETTE = HOME / ".cache/matugen/colors.json"
SIZES = (16, 20, 24, 32, 48)
PAD = 2                     # поле под контур и ореол вокруг сетки 16×16

# ── фигуры: (маска, остриё x, y в клетках сетки) ──────────────────────────────
SHAPES = {
    "default": ("""
L
LF
LFF
LFFF
LFFFF
LFFFFF
LFFFFFF
LFFFFFFF
LFFFFFFFF
LFFFFF
LFF.FF
LF..FF
L....FF
.....FF
""", 0, 0),
    "pointer": ("""
...LF
...LF
...LF
...LF
...LF
...LF.LF
...LF.LF.LF
...LF.LF.LF.F
...LFFFFFFFFF
.LFLFFFFFFFFF
LFFFFFFFFFFFF
.LFFFFFFFFFFF
..LFFFFFFFFFF
...LFFFFFFFF
....LFFFFFFF
""", 4, 0),
    "text": ("""
FFF.FFF
...F
...F
...F
...F
...F
...F
...F
...F
...F
...F
...F
FFF.FFF
""", 3, 6),
    "watch": ("""
LFFFFFFFFF
.LFFFFFFF
.LF.DDD.F
..LF.D.F
...LF.F
....LF
...LF.F
..LF.D.F
.LF.DDD.F
.LFDDDDDF
LFFFFFFFFF
""", 5, 5),
    "progress": ("""
L
LF
LFF
LFFF
LFFFF
LFFFFF
LFFFFFF
LFFFFFFF
LFFF.LFFFFF
LFF..LF.D.F
LF....LF.F
L......LF
......LF.F
.....LFDDDF
.....LFFFFF
""", 0, 0),
    "cross": ("""
.....F
.....F
.....F
.....F
...........
FFFF...FFFF
...........
.....F
.....F
.....F
.....F
""", 5, 5),
    "move": ("""
.....F
....FFF
...FFFFF
.....F
..F..F..F
.FF..F..FF
FFFFFFFFFFF
.FF..F..FF
..F..F..F
.....F
...FFFFF
....FFF
.....F
""", 5, 6),
    "col-resize": ("""
..F.....F
.FF.....FF
FFFFFFFFFFF
.FF.....FF
..F.....F
""", 5, 2),
    "row-resize": ("""
..F
.FFF
FFFFF
..F
..F
..F
..F
..F
FFFFF
.FFF
..F
""", 2, 5),
    "nw-resize": ("""
FFFF
FFF
FF.F
F...F
.....F
......F
.......F...F
........F.FF
.........FFF
........FFFF
""", 6, 6),
    "ne-resize": ("""
........FFFF
.........FFF
........F.FF
.......F...F
......F
.....F
....F
F..F
FF.F
FFF
FFFF
""", 6, 5),
    "not-allowed": ("""
...FFFFF
..FF...FF
.FFF....FF
FF.FF....FF
F...FF....F
F....FF...F
F.....FF..F
FF.....FF.F
.FF.....FFF
..FF....FF
...FFFFF
""", 5, 5),
    "copy": ("""
L
LF
LFF
LFFF
LFFFF
LFFFFF
LFFFFFF
LFFFFFFF
LFFFFF.FFF
LFF.FF.FDF
LF..FFFFDFFF
L....FDDDDDF
.....FFFFDFF
.......FFDF
.......FFFF
""", 0, 0),
    "pencil": ("""
..........FF
.........FFFF
........FFFF
.......FFFF
......FFFF
.....FFFF
....FFFF
...FFFF
..LFFF
..LLF
.DDD
""", 1, 10),
}


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def palette():
    """Цвета из обоев: заливка — акцент, светлый край — акцент к белому, деталь — тёмная."""
    try:
        c = json.load(open(PALETTE))
        col = lambda k, d: c.get(k, d) if isinstance(c.get(k, d), str) else d  # noqa: E731
        acc = hexrgb(col("primary", "#b4c5ff"))
    except (OSError, ValueError):
        acc = hexrgb("#b4c5ff")
    try:
        vivid = hexrgb(open(HOME / ".cache/matugen/vivid.txt").read().strip())
    except (OSError, ValueError):
        vivid = acc
    fill = mix(vivid, acc, 0.35)
    return {"F": fill, "L": mix(fill, (255, 255, 255), 0.55), "D": mix(fill, (10, 12, 20), 0.70),
            "O": (11, 13, 20), "H": mix(acc, (255, 255, 255), 0.85)}


def grid(mask):
    rows = [r for r in mask.strip("\n").split("\n")]
    return {(x, y): ch for y, r in enumerate(rows) for x, ch in enumerate(r) if ch in "FLD"}


def native(name, pal):
    """Картинка 16+2·PAD на сетке 1:1 и остриё в ней."""
    mask, hx, hy = SHAPES[name]
    cells = grid(mask)
    n = 16 + 2 * PAD
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    px = im.load()
    body = {(x + PAD, y + PAD): ch for (x, y), ch in cells.items()}
    outline = set()
    for (x, y) in body:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                q = (x + dx, y + dy)
                if q not in body:
                    outline.add(q)
    halo = set()
    for (x, y) in outline:
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            q = (x + dx, y + dy)
            if q not in body and q not in outline:
                halo.add(q)
    for (x, y) in halo:
        if 0 <= x < n and 0 <= y < n:
            px[x, y] = pal["H"] + (200,)
    for (x, y) in outline:
        if 0 <= x < n and 0 <= y < n:
            px[x, y] = pal["O"] + (255,)
    for (x, y), ch in body.items():
        px[x, y] = pal[ch] + (255,)
    return im, hx + PAD, hy + PAD


def images_for(name, pal):
    im, hx, hy = native(name, pal)
    out = []
    for s in SIZES:
        f = s / 16
        big = im.resize((round(im.width * f), round(im.height * f)), Image.NEAREST)
        out.append((s, big, int(hx * f + f / 2), int(hy * f + f / 2), 0))
    return out


def build(current=""):
    name = NAMES[1] if current == NAMES[0] else NAMES[0]
    dest = ICONS / name
    tmp = ICONS / (name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "cursors").mkdir(parents=True)
    pal = palette()
    for shape in SHAPES:
        cursor_colors.write_xcursor(tmp / "cursors" / shape, images_for(shape, pal))
    # синонимы имён — те же, что у Jarvis (иначе на краях окон и при перетаскивании — чужой)
    alias = {}
    for table in (cursor_colors.ALIASES, getattr(cursor_colors, "EXTRA_ALIASES", {})):
        for k, v in table.items():
            for a in v.split():
                alias.setdefault(a, k)
    alias.update({"help": "default", "left_ptr": "default", "wait": "watch", "crosshair": "cross"})
    for a, target in alias.items():
        t = target if target in SHAPES else ("default" if target not in SHAPES else target)
        p = tmp / "cursors" / a
        if not p.exists():
            os.symlink(t, p)
    (tmp / "index.theme").write_text("[Icon Theme]\nName=%s\nComment=Jarvis Bit — пиксельный, цвета обоев (bit_cursor.py)\n"
                                     "Inherits=breeze_cursors\n" % name)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    return name


def sheet(path):
    pal = palette()
    names = list(SHAPES)
    cell = 80
    out = Image.new("RGBA", (cell * 7, cell * 4), (24, 26, 38, 255))
    for i, n in enumerate(names):
        im, hx, hy = native(n, pal)
        big = im.resize((im.width * 3, im.height * 3), Image.NEAREST)
        x, y = (i % 7) * cell + (cell - big.width) // 2, (i // 7) * cell * 2 + 8
        out.alpha_composite(big, (x, y))
        small = im.resize((round(im.width * 1.25), round(im.height * 1.25)), Image.NEAREST)
        out.alpha_composite(small, ((i % 7) * cell + 28, (i // 7) * cell * 2 + 8 + big.height + 4))
    out.save(path)


def main():
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        print(build(a[1] if len(a) > 1 else ""))
    elif a[:1] == ["sheet"] and len(a) > 1:
        sheet(a[1])
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
