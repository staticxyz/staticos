#!/usr/bin/env python3
"""Рамка окон «.exe» в виде Recorder (Super+Shift+Print) — общая для карты конфигов
(Super+Shift+Z) и лаунчера (Super+X). 13.10.2026.

Просьба: «окно как Recorder.exe», «сверху в рамке меню кнопку закрыть, как в
Super+Shift+Print». Цвета, размеры и крестик берутся у rec_menu.App, здесь — то,
что у них одинаково: подготовка вида (look) и рамка с заголовком (frame), значок в
заголовке у каждого окна свой (битмап 7 строк).

Объект app — наследник rec_menu.App со своими title_text() и panel_rect().
"""
import rec_menu as R

cairo, Pango, PangoCairo = R.cairo, R.Pango, R.PangoCairo
mix = R.mix


def look(app, style):
    """Стиль, размеры, цвета, шрифт и точечный фон skeet — в поля app."""
    app.style = style
    app.G = dict(R.geometry(style))
    app.C = C = R.style_colors(style)
    app.acc = C.get("acc") or C["primary"]
    app.faint = mix(C["dim"], C["win_bg"], 0.30)
    app.soft = mix(C["text"], C["win_bg"], 0.86)
    app.field = C.get("field") or mix(C["win_bg"], (1, 1, 1), 0.06)
    app.fd = Pango.FontDescription(R.FONT)
    app.fd.set_absolute_size(app.G["PX"] * Pango.SCALE)
    app.fo = cairo.FontOptions()
    app.fo.set_antialias(cairo.ANTIALIAS_GRAY)
    app.fo.set_hint_style(cairo.HINT_STYLE_FULL)
    app.fo.set_hint_metrics(cairo.HINT_METRICS_ON)
    app.LH = app.G["PX"] + 4
    app.hover_cap = False
    app.dots = None
    if style == "skeet":
        tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        tc = cairo.Context(tile)
        tc.set_source_rgb(*C["dot"])
        tc.rectangle(0, 0, 1, 1)
        tc.rectangle(2, 2, 1, 1)
        tc.fill()
        app.dots = cairo.SurfacePattern(tile)
        app.dots.set_extend(cairo.EXTEND_REPEAT)


def background(app, cr, W, H):
    cr.set_source_rgb(*app.C["win_bg"])
    cr.rectangle(0, 0, W, H)
    cr.fill()
    if app.dots is not None:
        cr.save()
        cr.rectangle(0, 0, W, H)
        cr.clip()
        cr.set_source(app.dots)
        cr.paint()
        cr.restore()


def frame(app, cr, W, H, bmp):
    """Рамка и полоса заголовка по стилю; координаты — от угла окна."""
    C, G = app.C, app.G
    B, TOP, TB = G["BORDER"], G["TOP"], G["TB"]
    title = app.title_text()
    if app.style == "default":
        app.band(cr, 0, B, C["st_mid"], W, H)
        x, y, w = B, B, W - 2 * B
        g = cairo.LinearGradient(0, y, 0, y + TB)
        for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(off, *C[key])
        cr.set_source(g)
        cr.rectangle(x, y, w, TB)
        cr.fill()
        app.rect_fill(cr, x, y + TB - 1, w, 1, C["st_dark"])
        ix, iy = x + 8, y + (TB - 16) // 2
        app.rect_fill(cr, ix + 1, iy + 1, 16, 16, C["st_dark"])
        app.rect_fill(cr, ix, iy, 16, 16, C["on_surface"])
        cr.set_source_rgb(*C["st_bot"])
        R.draw_bitmap(cr, bmp, ix + 1, iy + 1, 2)
        lay = app.layout(cr, title, w - 30 - TB - 6)
        ty = y + (TB - lay.get_pixel_size()[1]) // 2
        cr.set_source_rgb(*C["st_dark"])
        cr.move_to(ix + 25, ty + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*C["on_surface"])
        cr.move_to(ix + 24, ty)
        PangoCairo.show_layout(cr, lay)
        return
    if app.style == "skeet":
        for i, w, key in ((0, 1, "line1_on"), (1, 3, "line2"), (4, 1, "line1_on"), (5, 1, "line3")):
            app.band(cr, i, w, C[key], W, H)
        for dy, k in ((0, 0.0), (1, 0.55)):          # полоска сверху — три тона палитры
            g = cairo.LinearGradient(B, 0, W - B, 0)
            for off, col in zip((0, 0.5, 1), C["strip"]):
                g.add_color_stop_rgb(off, *mix(col, (0, 0, 0), k))
            cr.set_source(g)
            cr.rectangle(B, B + dy, W - 2 * B, 1)
            cr.fill()
        app.rect_fill(cr, B, TOP + TB - 2, W - 2 * B, 1, C["line2"])
        app.rect_fill(cr, B, TOP + TB - 1, W - 2 * B, 1, C["line3"])
    else:
        app.band(cr, 0, B, C["frame"], W, H)
        app.rect_fill(cr, B, TOP, W - 2 * B, TB, C["bar"])
        app.rect_fill(cr, B, TOP + TB - 1, W - 2 * B, 1, C["line"])
    cr.set_source_rgb(*app.acc)
    R.draw_bitmap(cr, bmp, B + 8, TOP + (TB - 14) // 2, 2)
    app.text(cr, title, B + 8 + 16 + 10, TOP + (TB - G["PX"]) // 2 - 1, C["text"], W - 2 * B - 40 - TB)


def in_cap(app, x, y):
    """Точка (от угла окна) на крестике?"""
    cx, cy, cw, ch = app.cap_zone()
    cy -= app.panel_rect()[1]
    return cx <= x < cx + cw and cy <= y < cy + ch


def close_box(cr, x, y, s, bg, line, ink, round_=False):
    """Отдельный крестик для окон не на rec_menu (Super+Z, Super+C): квадрат s×s,
    крестик X_BMP по центру. Цвета задаёт окно: обычный и при наведении."""
    if round_:
        import math
        r = 4
        cr.new_sub_path()
        cr.arc(x + s - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + s - r, y + s - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + s - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
    else:
        cr.rectangle(x, y, s, s)
    cr.set_source_rgb(*bg)
    cr.fill_preserve()
    cr.set_source_rgb(*line)
    cr.set_line_width(1)
    cr.stroke()
    cr.set_source_rgb(*ink)
    R.draw_bitmap(cr, R.X_BMP, x + (s - 14) // 2, y + (s - 14) // 2, 2)


def recorder_close(cr, style, s, hover=False):
    """Крестик ровно как у Recorder (rec_menu.App.close_btn) в квадрате s×s от (0,0) —
    для окон на GTK-виджетах (Super+C): рисуется в своей DrawingArea."""
    class _Shim:
        pass
    o = _Shim()
    o.style, o.C, o.hover_cap = style, R.style_colors(style), hover
    o.cap_zone = lambda: (0, 0, s, s)
    o.panel_rect = lambda: (0, 0, s, s)
    o.rect_line = lambda *a, **k: R.App.rect_line(o, *a, **k)
    o.rect_fill = lambda *a, **k: R.App.rect_fill(o, *a, **k)
    R.App.close_btn(o, cr)
