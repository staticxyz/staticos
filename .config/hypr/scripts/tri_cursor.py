#!/usr/bin/env python3
"""Курсор «Стрелка» — пиксельный набор в цветах обоев. 13.10.2026.

Пользователь выбрал с листа вариант 1B (заливка акцентом, светлый левый край, тёмный контур)
и попросил: «убери нижнюю часть чуть чуть, чтобы он был более похож на курсор», «размер
должен быть как у курсора Jarvis». Встал в Настройках на место Jarvis Bit. Затем:
«почему ты сделал только дефолтную версию, а остальные скопировал у Jarvis? Надо было на
все варианты подогнать», «нижнюю часть ещё чуть чуть убери» и «сделай более пиксельным,
чтобы это заметно было».

Поэтому все 14 форм нарисованы здесь, крупной клеткой: маска — в клетках, клетка на
размерах 16–24 — квадрат 2×2 пикселя (у 32 — 3×3 и т. д.), а тёмный контур и светлый
ореол снаружи — по 1 пикселю, как у Jarvis: зернистость видно, детали не слипаются
(контур в целую клетку пробовали — двойные стрелки превращались в «H»). Светлый край — у клетки, слева от которой пусто, а справа тело (у палочек в
одну клетку его нет). «D» в маске — тёмная деталь внутри тела.

На размере 20 стрелка 14×18 пикселей — как у Jarvis. Тема — Jarvis-Tri-A / -B попеременно
(niri не перечитывает курсор, пока имя темы то же); тему с синонимами имён собирает
cursor_colors.build(), потом эти 14 файлов перезаписываются.

    tri_cursor.py build [ТЕКУЩЕЕ]   собрать в свободный A/B, имя — в stdout
    tri_cursor.py sheet ФАЙЛ        лист: все формы во всех размерах
Включает cursor_theme.py (Настройки → Design → «Тема курсора» → «Стрелка»).
"""
import os
import pathlib
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bit_cursor      # noqa: E402  (palette() — те же цвета, что у листа вариантов)
import cursor_colors   # noqa: E402  (build — тема и синонимы, write_xcursor)

ICONS = pathlib.Path.home() / ".local/share/icons"
NAMES = ("Jarvis-Tri-A", "Jarvis-Tri-B")
# Размер темы → (пикселей в клетке, ширина контура, ширина ореола).
SCALE = {16: (2, 1, 1), 20: (2, 1, 1), 24: (2, 1, 1), 32: (3, 1, 1), 48: (4, 2, 1),
         64: (6, 2, 2)}

# Маски в клетках: «#» тело, «D» тёмная деталь. Остриё — (x, y) клетки и центр ли клетки.
SHAPES = {
    # Стрелка: треугольник 1..5, низ скошен к левому краю (2, 1).
    "default": ("""
#
##
###
####
#####
##
#
""", 0, 0, False),
    "pointer": ("""
..#...
..#...
..####
#.####
######
.#####
..####
""", 2, 0, False),
    "text": ("""
##.##
..#..
..#..
..#..
..#..
..#..
##.##
""", 2, 3, True),
    "watch": ("""
#####
.###.
..#..
.D#D.
.###.
#####
""", 2, 3, True),
    "progress": ("""
#.......
##......
###.....
####....
#...###.
.....#..
....###.
""", 0, 0, False),
    # Круг с тёмной косой чертой: у кольца просветы в клетку заливались контуром.
    "not-allowed": ("""
..###..
.#####.
##D####
###D###
####D##
.#####.
..###..
""", 3, 3, True),
    "move": ("""
...#...
..###..
.#.#.#.
#######
.#.#.#.
..###..
...#...
""", 3, 3, True),
    "cross": ("""
...#...
...#...
.......
##.#.##
.......
...#...
...#...
""", 3, 3, True),
    "col-resize": ("""
..#...#..
.##...##.
#########
.##...##.
..#...#..
""", 4, 2, True),
    "row-resize": ("""
..#..
.###.
#####
..#..
..#..
..#..
#####
.###.
..#..
""", 2, 4, True),
    "nw-resize": ("""
###....
##.....
#.#....
...#...
....#.#
.....##
....###
""", 3, 3, True),
    "ne-resize": ("""
....###
.....##
....#.#
...#...
#.#....
##.....
###....
""", 3, 3, True),
    "copy": ("""
#......
##.....
###....
####...
#....#.
....###
.....#.
""", 0, 0, False),
    "pencil": ("""
.....##
....###
...###.
..###..
.###...
D##....
DD.....
""", 0, 6, False),
}


def cells(mask):
    rows = mask.strip("\n").split("\n")
    return {(x, y): ch for y, r in enumerate(rows) for x, ch in enumerate(r) if ch in "#D"}


def render(name, size, pal):
    """(картинка, остриё x, y) для размера темы."""
    mask, hx, hy, center = SHAPES[name]
    f, ow, h = SCALE[size]
    body = cells(mask)
    pad = ow + h
    w = (max(x for x, _ in body) + 1) * f + 2 * pad
    ht = (max(y for _, y in body) + 1) * f + 2 * pad
    im = Image.new("RGBA", (w, ht), (0, 0, 0, 0))
    out = im.load()
    solid = set()
    for (x, y), c in body.items():
        if c == "D":
            col = pal["D"]
        elif (x - 1, y) not in body and (x + 1, y) in body:
            col = pal["L"]
        else:
            col = pal["F"]
        for i in range(f):
            for j in range(f):
                q = (pad + x * f + i, pad + y * f + j)
                out[q] = col + (255,)
                solid.add(q)
    rim = {(x + dx, y + dy) for x, y in solid
           for dx in range(-ow, ow + 1) for dy in range(-ow, ow + 1)} - solid
    for q in rim:
        out[q] = pal["O"] + (255,)
    halo = {(x + dx, y + dy) for x, y in solid | rim
            for dx in range(-h, h + 1) for dy in range(-h, h + 1)
            if abs(dx) + abs(dy) <= h} - solid - rim
    for q in halo:
        out[q] = pal["H"] + (200,)
    off = f // 2 if center else 0
    return im, pad + hx * f + off, pad + hy * f + off


def images(name, pal):
    return [(s,) + render(name, s, pal) + (0,) for s in SCALE]


def build(current=""):
    name = NAMES[1] if current == NAMES[0] else NAMES[0]
    cursor_colors.build(name)                       # тема, синонимы-ссылки
    cur = ICONS / name / "cursors"
    pal = bit_cursor.palette()
    for shape in SHAPES:
        tmp = cur / (".%s.tmp" % shape)
        cursor_colors.write_xcursor(tmp, images(shape, pal))
        os.replace(tmp, cur / shape)                # синонимы — ссылки на эти файлы
    (ICONS / name / "index.theme").write_text(
        "[Icon Theme]\nName=%s\nComment=Стрелка — tri_cursor.py\n"
        "Inherits=breeze_cursors\n" % name)
    return name


def sheet(path, sizes=(20, 32)):
    """Лист: строка на размер, увеличение ×6 (×4 для крупных)."""
    pal = bit_cursor.palette()
    rows = []
    for s in sizes:
        k = 6 if s <= 24 else 4
        ims = [render(n, s, pal) for n in SHAPES]
        rows.append([(im.resize((im.width * k, im.height * k), Image.NEAREST),
                      hx * k, hy * k) for im, hx, hy in ims])
    W = max(sum(i.width + 24 for i, _, _ in r) for r in rows) + 24
    H = sum(max(i.height for i, _, _ in r) + 24 for r in rows) + 24
    out = Image.new("RGBA", (W, H), (24, 26, 38, 255))
    y = 24
    for r in rows:
        x = 24
        for im, hx, hy in r:
            out.alpha_composite(im, (x, y))
            for d in range(-3, 4):                  # красная точка — остриё
                for q in ((x + hx + d, y + hy), (x + hx, y + hy + d)):
                    out.putpixel(q, (255, 60, 60, 255))
            x += im.width + 24
        y += max(i.height for i, _, _ in r) + 24
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
