#!/usr/bin/env python3
"""Символы кнопки «Пуск» (вместо искорки) — пиксельные маски, клетка 2 px. 15.10.2026.

Пользователь выбрал из листа ~/Pictures/start-button-variants-2.png: молния, прицел, кристалл,
снежинка, пламя, полумесяц («подравняй, чтобы был более похож»), «S» — и два вида кнопки:
«ярлык» (квадрат акцентом с тёмным символом + staticOS) и «значок» (только символ со свечением).
Выбор — один список в Настройках → Панели → «Кнопка «Пуск»»; значение пишется в
state/start-button-look как default | square | <вид>-<символ> (badge-bolt, icon-moon…).

Ключи масок: A акцент, L светлее, W почти белый, D темнее, T сиреневый (пламя), k тёмный.
    start_glyphs.py sheet ФАЙЛ    лист всех символов в обоих видах (цвета Skeet)
"""
import sys

CELL = 2

GLYPHS = {
    "sparkle": None,          # рисуется отдельно (тонкие лучи 1 px, как была искорка)
    "bolt": """
.....LL..
....LW...
...LA....
..LA.....
.LAAAAA..
....AAD..
...AAD...
..AAD....
..AD.....
.AD......
.D.......
""",
    "cross": """
....L....
....A....
.........
.........
LA..W..AL
.........
.........
....A....
....L....
""",
    "gem": """
..LLLLL..
.LWLALAL.
LAWAAAAAL
.DAAAAAD.
..DAAAD..
...DAD...
....D....
""",
    "snow": """
....A....
.A..L..A.
..A.L.A..
...LWL...
ALLWWWLLA
...LWL...
..A.L.A..
.A..L..A.
....A....
""",
    "flame": """
....L....
...LA....
...AA.L..
..AAA.AL.
.AAATAAA.
.AATTTAA.
.ATTWTTA.
.ATWWWTA.
..AAAAA..
""",
    "moon": """
....LLL...
..LLA.....
.LAA....W.
.LAA......
LAAA......
LAAA...A..
LAAA......
.LAA......
.DAA......
..DDA.....
....DDD...
""",
    "s": """
.LLLLLL.
LA......
LA......
..AAWAA.
......AD
......AD
DDDDDD..
""",
}

NAMES = {"sparkle": "искорка", "bolt": "молния", "cross": "прицел", "gem": "кристалл",
         "snow": "снежинка", "flame": "пламя", "moon": "полумесяц", "s": "«S»"}
ORDER = ("sparkle", "bolt", "cross", "gem", "snow", "flame", "moon", "s")
FORMS = {"badge": "ярлык", "icon": "значок"}




def cells(name):
    """[(x, y, ключ)] и размер (w, h) в клетках."""
    rows = GLYPHS[name].strip("\n").split("\n")
    out = [(x, y, ch) for y, r in enumerate(rows) for x, ch in enumerate(r) if ch != "."]
    return out, (max(len(r) for r in rows), len(rows))


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def palette(acc, bg):
    """acc, bg — (r, g, b) 0..1 → цвета ключей для «значка» и для «ярлыка» (силуэт на акценте)."""
    white = (1, 1, 1)
    icon = {"A": acc, "L": _mix(acc, white, .3), "W": _mix(acc, white, .65),
            "D": _mix(acc, (0, 0, 0), .4), "T": _mix(_mix(acc, (.82, .74, .96), .6), white, .15),
            "k": bg}
    dark = _mix(bg, acc, .12)
    badge = {"A": dark, "L": bg, "W": bg, "D": _mix(bg, acc, .3), "T": _mix(bg, acc, .2), "k": None}
    return icon, badge


def draw(cr, name, cx, cy, cols, glow=None):
    """Нарисовать символ в cairo с центром (cx, cy). cols — палитра ключей; glow — (r,g,b) свечения."""
    if name == "sparkle":
        return _sparkle(cr, int(cx), int(cy), cols, glow)
    cl, _size = cells(name)
    # центр — по границам самого рисунка, не маски (молния занимала клетки 1–6 из 9
    # и стояла на 2 px левее, 15.10.2026)
    xs, ys = [c[0] for c in cl], [c[1] for c in cl]
    w, h = max(xs) + 1 - min(xs), max(ys) + 1 - min(ys)
    x0 = int(cx - w * CELL / 2) - min(xs) * CELL
    y0 = int(cy - h * CELL / 2) - min(ys) * CELL
    if glow:
        for grow, a in ((3, .07), (2, .09), (1, .12)):
            cr.set_source_rgba(*glow, a)
            for x, y, _k in cl:
                cr.rectangle(x0 + x * CELL - grow, y0 + y * CELL - grow, CELL + 2 * grow, CELL + 2 * grow)
            cr.fill()
    for x, y, k in cl:
        c = cols.get(k)
        if c is None:
            continue
        cr.set_source_rgb(*c)
        cr.rectangle(x0 + x * CELL, y0 + y * CELL, CELL, CELL)
        cr.fill()


def _sparkle(cr, cx, cy, cols, glow):
    acc, hi = cols["A"], cols["W"]
    if glow:
        cr.set_source_rgba(*glow, .22)
        cr.rectangle(cx - 5, cy - 5, 11, 11)
        cr.fill()
        cr.set_source_rgba(*glow, .12)
        cr.rectangle(cx - 7, cy - 2, 15, 5)
        cr.rectangle(cx - 2, cy - 7, 5, 15)
        cr.fill()
    cr.set_source_rgb(*acc)
    cr.rectangle(cx, cy - 8, 1, 17)
    cr.rectangle(cx - 8, cy, 17, 1)
    cr.rectangle(cx - 1, cy - 3, 3, 7)
    cr.rectangle(cx - 3, cy - 1, 7, 3)
    cr.fill()
    if hi is not None and glow:
        cr.set_source_rgb(*hi)
        cr.rectangle(cx - 1, cy - 1, 3, 3)
        cr.fill()
        cr.set_source_rgba(*acc, .7)                     # пара крошечных искр, как у прежней
        cr.rectangle(cx - 8, cy - 8, 2, 2)
        cr.rectangle(cx + 7, cy + 7, 2, 2)
        cr.fill()


def parse(value):
    """'badge-bolt' → ('badge', 'bolt'); иначе None."""
    form, _, g = (value or "").partition("-")
    return (form, g) if form in FORMS and g in GLYPHS else None


def choices():
    """[(значение, подпись)] для списка в Настройках."""
    out = [("default", "Обычная"), ("square", "Системная")]
    for form in FORMS:
        for g in ORDER:
            out.append(("%s-%s" % (form, g), "%s · %s" % (FORMS[form].capitalize(), NAMES[g])))
    return out


def sheet(path):
    """Лист: оба вида всех символов в цветах Skeet (как кнопка на панели, ×3)."""
    import cairo
    sys.path.insert(0, __import__("os").path.dirname(__file__))
    import rec_style
    sk = rec_style.colors("skeet")
    rgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))  # noqa: E731
    acc, bg, field = rgb(sk["acc"]), rgb(sk["bg"]), rgb(sk["field"])
    l1, l3 = rgb(sk["line1"]), rgb(sk["line3"])
    icon, badge = palette(acc, bg)
    K, W, H = 3, 76, 34
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, (W * 2 + 8) * K, H * len(ORDER) * K)
    cr = cairo.Context(surf)
    cr.scale(K, K)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    cr.set_source_rgb(*bg)
    cr.paint()
    for i, g in enumerate(ORDER):
        y = i * H + 2
        for j in range(2):
            x = 4 + j * (W + 4)
            cr.set_source_rgb(*l1); cr.rectangle(x, y, 29, 29); cr.fill()
            cr.set_source_rgb(*l3); cr.rectangle(x + 1, y + 1, 27, 27); cr.fill()
            cr.set_source_rgb(*field); cr.rectangle(x + 2, y + 2, 25, 25); cr.fill()
            if j == 0:
                cr.set_source_rgb(*acc); cr.rectangle(x + 2, y + 2, 25, 25); cr.fill()
                draw(cr, g, x + 14.5 - (g == "sparkle") * .5, y + 14.5 - (g == "sparkle") * .5, badge)
            else:
                draw(cr, g, x + 14.5 - (g == "sparkle") * .5, y + 14.5 - (g == "sparkle") * .5, icon, glow=acc)
    surf.write_to_png(path)


if __name__ == "__main__":
    if sys.argv[1:2] == ["sheet"] and len(sys.argv) > 2:
        sheet(sys.argv[2])
    else:
        print(__doc__)
