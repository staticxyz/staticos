#!/usr/bin/env python3
"""Кнопка «закрыть» staticOS — одна на все окна. 13.10.2026.

Просьба: «переделай [крестики] на вариант из Буфера обмена… система должна выглядеть
единой. Не только выглядеть, а быть ею». Образец — кнопка в заголовке буфера обмена
(clipboard_win.py, Super+Alt+V): квадрат CAP×CAP, тонкий крестик 7×7, у правого края
полосы заголовка. Рисует её этот модуль, и только он: буфер обмена, Recorder и всё на
rec_menu (Super+X, Super+Shift+Z), Super+Z, Super+C, rofi (PNG), центр уведомлений.

    size(style)                          сторона квадрата (как CAP буфера обмена)
    zone(style, right, top, tb)          (x, y, s): кнопка у правого края заголовка
    draw(cr, style, C, x, y, hover)      нарисовать; C — цвета стиля (clipboard_win /
                                         rec_menu.style_colors, у Default — тема XP)
    png(style, path, hover=False)        то же в PNG (rofi, swaync)
"""
import cairo

X_BMP = ("#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#")
# тот же квадрат с другим значком (calendar_app: «на весь экран» / «обратно», 13.10.2026)
MAX_BMP = ("#######", "#######", "#.....#", "#.....#", "#.....#", "#.....#", "#######")
RESTORE_BMP = ("..#####", "..#...#", "#####.#", "#...#.#", "#...###", "#...#..", "#####..")
CAP = {"skeet": 14, "beta": 18, "default": 16}


def size(style):
    return CAP.get(style, CAP["default"])


def zone(style, right, top, tb):
    """Кнопка у правого края заголовка: right — внутренний край рамки, top/tb — полоса."""
    s = size(style)
    return right - 3 - s, top + (tb - s) // 2, s


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _rect_line(cr, x, y, w, h, col):
    cr.set_source_rgb(*col)
    cr.set_line_width(1)
    cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
    cr.stroke()


def _bitmap(cr, rows, x, y):
    for r, row in enumerate(rows):
        for c, ch in enumerate(row):
            if ch == "#":
                cr.rectangle(x + c, y + r, 1, 1)
    cr.fill()


def draw(cr, style, C, x, y, hover=False, s=None, glyph=None, hover_ink=None):
    """glyph — другой значок 7×7 в той же кнопке; hover_ink — его цвет под курсором
    (у крестика — красный, у прочих кнопок задаёт вызывающий)."""
    s = s or size(style)
    if style == "skeet":
        g = cairo.LinearGradient(0, y, 0, y + s)
        g.add_color_stop_rgb(0, *C["field_l"])
        g.add_color_stop_rgb(1, *C["field"])
        cr.set_source(g)
        cr.rectangle(x, y, s, s)
        cr.fill()
        _rect_line(cr, x, y, s, s, C["line3"])
        _rect_line(cr, x + 1, y + 1, s - 2, s - 2, C["gline"])
        ink = C["err"] if hover else C.get("text_dim", C.get("dim"))
    elif style == "beta":
        cr.set_source_rgb(*(C["err"] if hover else C["field"]))
        cr.rectangle(x, y, s, s)
        cr.fill()
        _rect_line(cr, x, y, s, s, C["line_strong"])
        ink = C["bg"] if hover else C["text"]
    else:
        er = C["error"]
        top = tuple(0.5 * er[i] + 0.5 * C["st_hover"][i] for i in range(3))
        bot = tuple(0.55 * er[i] * 0.6 + 0.45 * C["st_bot"][i] for i in range(3))
        if hover:
            top = _mix(top, (1, 1, 1), 0.18)
        g = cairo.LinearGradient(0, y, 0, y + s)
        g.add_color_stop_rgb(0, *top)
        g.add_color_stop_rgb(1, *bot)
        cr.set_source(g)
        cr.rectangle(x, y, s, s)
        cr.fill()
        _rect_line(cr, x, y, s, s, C["st_hi"])
        ink = C["on_surface"]
    if hover and hover_ink is not None:
        ink = hover_ink
    cr.set_source_rgb(*ink)
    _bitmap(cr, glyph or X_BMP, x + (s - 7) // 2, y + (s - 7) // 2)


def colors(style):
    """Цвета стиля для draw() тем, у кого своих нет (rofi, swaync, Super+Z)."""
    import rec_menu
    return rec_menu.style_colors(style)


def png(style, path, hover=False):
    s = size(style)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, s, s)
    draw(cairo.Context(surf), style, colors(style), 0, 0, hover)
    surf.write_to_png(path + ".tmp")
    import os
    os.replace(path + ".tmp", path)
    return path


if __name__ == "__main__":
    import sys
    st = sys.argv[1] if len(sys.argv) > 1 else "skeet"
    print(png(st, sys.argv[2] if len(sys.argv) > 2 else "/tmp/close-%s.png" % st))
