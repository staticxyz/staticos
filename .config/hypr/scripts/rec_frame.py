#!/usr/bin/env python3
"""Красная рамка вокруг области, которая сейчас записывается. 29.09.2026.

    rec_frame.py "X,Y WxH" [подпись] [папка состояния rec_area.sh]
    rec_frame.py "pill:X,Y WxH" …   только плашка, без рамки — по центру сверху монитора
                                    с этими координатами (запись всего экрана и окна)

Пауза (03.10.2026): кнопки плашки — ⏸/▶ (rec_area.sh pause, как K/Space), 󰍭 (микрофон,
только видео), ⏹ (стоп). Щелчок по остальной плашке ничего не нажимает — рядом с
паузой случайный стоп обидно терять. Время — без пауз: из $S/acc, $S/t0, $S/paused
(пишет rec_area.sh). Вид — стиль Recorder (rec_style.py: default / skeet / beta).

Рамка рисуется СНАРУЖИ области: между областью и линией зазор GAP, линия BORDER.
Раньше слой был размером с рамку и прижимался к краю монитора: у области вплотную к
верху экрана рамка съезжала ВНУТРЬ, и в записи сверху шли две красные строки
(04.10.2026, видно в video-2026-10-04_05-53-06.mp4). Теперь слой — во весь монитор
(прозрачный, ввод только на рамке и плашке), рамка рисуется в координатах области и у
края экрана просто уходит за него.

Перетаскивание (04.10.2026): полоса вокруг области (снаружи, ~11 px) и
плашка — перенос; уголки и метки посередине сторон — размер. Пока тянут, запись на
паузе: файл $S/hold, rec_session дописывает сегмент. Отпустили — новая область
в $S/geom ("X,Y WxH", ширина и высота чётные), hold снят, rec_session начинает
новый сегмент с ней (если до перетаскивания шла запись). Сквозь внутренность области
мышь проходит насквозь. Клавиатуру слой не берёт. Закрывается по SIGTERM от rec_area.sh.
"""
import os
import signal
import subprocess
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("PangoCairo", "1.0")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

# Pango, а не cairo.show_text: только он подбирает запасной шрифт для значков
# (у PxPlus их нет, а имена Nerd Font fontconfig подменяет на PxPlus же).
FONT = Pango.FontDescription("PxPlus HP 100LX 6x8 Jarvis 12")   # 16 px — сетка шрифта


def text_at(cr, s, x, cy, rgba):
    """Нарисовать строку, выровняв по вертикали на cy; вернуть её ширину."""
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(FONT)
    lay.set_text(s, -1)
    tw, th = lay.get_pixel_size()
    cr.set_source_rgba(*rgba)
    cr.move_to(x, cy - th / 2)
    PangoCairo.show_layout(cr, lay)
    return tw


BORDER = 3          # толщина красной линии
GAP = 2             # зазор между областью и линией — запас от любых округлений
GRIP = GAP + BORDER + 6   # ширина полосы ввода снаружи области (за неё тянут)
HANDLE = 7          # толщина меток размера (снаружи, поверх линии)
CORNER = 18         # уголок: столько пикселей от угла области по каждой оси
MIN_SIDE = 16       # меньше область не сжимается
LABEL_H = 26
RED = (1.0, 0.27, 0.27)
REC = os.path.join(os.path.dirname(os.path.realpath(__file__)), "rec_area.sh")
MIC_ON, MIC_OFF, STOP = "\U000f036c", "\U000f036d", "\U000f04db"   # 󰍬 󰍭 󰓛 (Nerd Font)
PAUSE, PLAY = "\U000f03e4", "\U000f040a"                           # 󰏤 󰐊
HINT = "пауза — Space/K или ▶"
BTN = 22                                                           # кнопка плашки
# Курсор над зоной (имена CSS — их знает любая тема курсора)
CURSORS = {"move": "move", "n": "n-resize", "s": "s-resize", "w": "w-resize", "e": "e-resize",
           "nw": "nw-resize", "ne": "ne-resize", "sw": "sw-resize", "se": "se-resize",
           "button": "pointer", None: "default"}

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
import rec_style  # noqa: E402
STYLE = rec_style.read_style()


def _rgb(v):
    return tuple(int(v[i:i + 2], 16) / 255 for i in (1, 3, 5))


C = {k: ([_rgb(x) for x in v] if isinstance(v, list) else _rgb(v))
     for k, v in rec_style.colors(STYLE).items()}
if STYLE == "skeet":                          # 12 px, как Skeet в Настройках
    FONT = Pango.FontDescription("PxPlus HP 100LX 6x8 Jarvis 9")


def read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def rec_us(state):
    """Сколько записано, мкс, без пауз; и стоит ли пауза."""
    acc = int(read(os.path.join(state, "acc"), "0") or 0)
    paused = os.path.exists(os.path.join(state, "paused"))
    t0 = read(os.path.join(state, "t0"))
    if not paused and t0:
        acc += int(time.time() * 1e6) - int(t0)
    return max(acc, 0), paused


PROBE = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def text_w(s):
    return text_at(PROBE, s, 0, 0, (0, 0, 0, 0))


class Frame:
    """Всё, что рисуется и где что ловится, — в координатах МОНИТОРА (логические px).
    Окно с рамкой — во весь монитор (org = 0,0), окно-плашка — маленькое (org = его угол);
    draw() сам сдвигает рисунок на org. Без окна (проверки) — рисует на любой cairo."""

    def __init__(self, area, mon_w, mon_h, label="REC", state="", pill_only=False):
        self.area = list(area)            # x, y, w, h области в координатах монитора
        self.mw, self.mh = mon_w, mon_h
        self.label, self.state, self.pill_only = label, state, pill_only
        self.video = read(os.path.join(state, "mode")) == "video" if state else False
        self.start = time.monotonic()
        self.hot = {}                     # кнопки плашки: имя → (x, y, w, h)
        self.pill = (0, 0, 0, 0)
        self.drag = None                  # (зона, x0, y0, область до начала)
        self.pill_max = 24 + text_w(label + " 00:00") + 10 + text_w(HINT) + 10 + \
            (BTN + 4) * (3 if self.video else 2) + 6
        self.org = (0, 0)
        if pill_only:                     # плашка: по центру сверху, под баром
            self.org = ((mon_w - self.pill_max) // 2, 40)

    # ---- геометрия
    def pill_rect(self, pw):
        """Где стоит плашка шириной pw."""
        if self.pill_only:
            ox, oy = self.org
            return ox + (self.pill_max - pw) / 2, oy + 1, pw, LABEL_H - 2
        x, y, w, h = self.area
        out = GAP + HANDLE                         # от области до внешнего края меток
        if y - out - LABEL_H >= 0:                 # сверху есть место
            py = y - out - LABEL_H
        else:                                      # иначе под рамкой
            py = min(y + h + out, self.mh - LABEL_H)
        px = max(0, min(x - out, self.mw - pw))
        return px, py + 1, pw, LABEL_H - 2

    def zone(self, mx, my):
        """Что под мышью: кнопка плашки / move / сторона n s w e / угол nw ne sw se / None."""
        for name, r in self.hot.items():
            if r and r[0] <= mx <= r[0] + r[2] and r[1] <= my <= r[1] + r[3]:
                return "button"
        p = self.pill
        if p[0] <= mx <= p[0] + p[2] and p[1] <= my <= p[1] + p[3]:
            return "move"
        if self.pill_only:
            return None
        x, y, w, h = self.area
        inside_out = x - GRIP <= mx < x + w + GRIP and y - GRIP <= my < y + h + GRIP
        inside_in = x <= mx < x + w and y <= my < y + h
        if not inside_out or inside_in:            # внутрь области — насквозь
            return None
        v = "n" if my < y + CORNER else ("s" if my >= y + h - CORNER else "")
        u = "w" if mx < x + CORNER else ("e" if mx >= x + w - CORNER else "")
        if v and u:
            return v + u
        hl_x, hl_y = self.handle_len(w), self.handle_len(h)
        if v == "" and u and abs(my - (y + h / 2)) <= hl_y / 2 + 2:
            return u
        if u == "" and v and abs(mx - (x + w / 2)) <= hl_x / 2 + 2:
            return v
        return "move"

    @staticmethod
    def handle_len(side):
        return max(12, min(40, side // 3))

    def input_rects(self):
        """Прямоугольники, где слой принимает мышь (в координатах окна)."""
        ox, oy = self.org
        p = self.pill
        rs = [(p[0] - ox, p[1] - oy, p[2] + 1, p[3])]
        if not self.pill_only:
            x, y, w, h = self.area
            rs += [(x - GRIP, y - GRIP, w + 2 * GRIP, GRIP),      # сверху
                   (x - GRIP, y + h, w + 2 * GRIP, GRIP),         # снизу
                   (x - GRIP, y, GRIP, h),                        # слева
                   (x + w, y, GRIP, h)]                           # справа
        return [tuple(int(round(v)) for v in r) for r in rs]

    def begin(self, zone, mx, my):
        self.drag = (zone, mx, my, tuple(self.area))

    def motion(self, mx, my):
        zone, x0, y0, (ax, ay, aw, ah) = self.drag
        dx, dy = round(mx - x0), round(my - y0)
        if zone == "move":
            ax = max(0, min(ax + dx, self.mw - aw))
            ay = max(0, min(ay + dy, self.mh - ah))
        else:
            if "w" in zone:
                nx = max(0, min(ax + dx, ax + aw - MIN_SIDE)); aw += ax - nx; ax = nx
            if "e" in zone:
                aw = max(MIN_SIDE, min(aw + dx, self.mw - ax))
            if "n" in zone:
                ny = max(0, min(ay + dy, ay + ah - MIN_SIDE)); ah += ay - ny; ay = ny
            if "s" in zone:
                ah = max(MIN_SIDE, min(ah + dy, self.mh - ay))
        self.area = [ax, ay, aw, ah]

    def end(self):
        """Конец перетаскивания: чётные ширина/высота (x264), вернуть, сменилась ли область."""
        before = self.drag[3]
        self.drag = None
        x, y, w, h = self.area
        self.area = [int(x), int(y), int(w) // 2 * 2, int(h) // 2 * 2]
        return tuple(self.area) != tuple(before)

    # ---- рисунок
    def draw(self, cr):
        ox, oy = self.org
        cr.save()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.translate(-ox, -oy)
        if self.state:
            us, paused = rec_us(self.state)
        else:
            us, paused = int((time.monotonic() - self.start) * 1e6), False
        if not self.pill_only:
            self.draw_frame(cr, paused and not self.drag)
        self.draw_pill(cr, us, paused)
        cr.restore()

    def draw_frame(self, cr, dim):
        """Линия и метки — строго снаружи области: внутренний край линии на GAP px от неё."""
        x, y, w, h = self.area
        cr.set_source_rgba(*RED, 0.45 if dim else 0.95)       # на паузе рамка бледнее
        cr.set_line_width(BORDER)
        o = GAP + BORDER / 2                                  # середина линии
        cr.rectangle(x - o, y - o, w + 2 * o, h + 2 * o)
        cr.stroke()
        # Метки размера: уголки «Г» и короткие планки посередине сторон, толще линии.
        # Всё — за линией наружу (от x-GAP и дальше), в кадр не попадает.
        cr.set_source_rgba(*RED, 0.7 if dim else 1.0)
        g, t, c = GAP, HANDLE, CORNER - GAP
        L, T, R, B = x - g - t, y - g - t, x + w + g, y + h + g  # внешние полосы меток
        for cx, cy, sx, sy in ((L, T, 1, 1), (R + t, T, -1, 1), (L, B + t, 1, -1), (R + t, B + t, -1, -1)):
            cr.rectangle(min(cx, cx + sx * (c + t)), min(cy, cy + sy * t), c + t, t)
            cr.rectangle(min(cx, cx + sx * t), min(cy, cy + sy * (c + t)), t, c + t)
        hw, hh = self.handle_len(w), self.handle_len(h)
        cr.rectangle(x + (w - hw) / 2, T, hw, t)
        cr.rectangle(x + (w - hw) / 2, B, hw, t)
        cr.rectangle(L, y + (h - hh) / 2, t, hh)
        cr.rectangle(R, y + (h - hh) / 2, t, hh)
        cr.fill()

    def draw_pill(self, cr, us, paused):
        secs = us // 1000000
        text = "%s %d:%02d" % (self.label, secs // 60, secs % 60)
        tw = text_w(text)
        hw = text_w(HINT) + 10 if paused else 0
        nb = 3 if self.video else 2
        pw = 24 + tw + 10 + hw + (BTN + 4) * nb + 6
        x0, y0, pw, ph = self.pill_rect(pw)
        cy = y0 + ph / 2
        self.pill_bg(cr, x0, y0, pw, ph)
        if paused:                                   # пауза — ровная бледная точка
            cr.set_source_rgba(*RED, 0.5)
        else:                                        # запись — мигает
            cr.set_source_rgba(*RED, 1.0 if int(time.monotonic() * 2) % 2 == 0 else 0.35)
        cr.arc(x0 + 12, cy, 5, 0, 6.2832)
        cr.fill()
        text_at(cr, text, x0 + 24, cy, (*C["text"], 1))
        cx = x0 + 24 + tw + 10
        if paused:
            text_at(cr, HINT, cx, cy, (*C["dim"], 1))
            cx += hw
        self.hot["pause"] = self.button(cr, cx, cy, PLAY if paused else PAUSE, C["acc"], paused)
        cx += BTN + 4
        self.hot["mic"] = None
        if self.video:
            on = read(os.path.join(self.state, "mic")) == "on"
            self.hot["mic"] = self.button(cr, cx, cy, MIC_ON if on else MIC_OFF,
                                          (0.45, 1.0, 0.55) if on else C["dim"], False)
            cx += BTN + 4
        self.hot["stop"] = self.button(cr, cx, cy, STOP, RED, False)
        self.pill = (x0, y0, pw, ph)

    @staticmethod
    def pill_bg(cr, x, y, pw, ph):
        """Подложка плашки в стиле Recorder."""
        if STYLE == "skeet":                         # слоистая рамка и полоска трёх тонов
            for i, k in enumerate(("line3", "line1", "line2", "line1")):
                cr.set_source_rgba(*C[k], 0.97)
                cr.rectangle(x + i, y + i, pw - 2 * i, ph - 2 * i)
                cr.fill()
            cr.set_source_rgba(*C["bg"], 0.97)
            cr.rectangle(x + 4, y + 4, pw - 8, ph - 8)
            cr.fill()
            g = cairo.LinearGradient(x + 4, 0, x + pw - 4, 0)
            for i, col in enumerate(C["strip"]):
                g.add_color_stop_rgb(i / 2, *col)
            cr.set_source(g)
            cr.rectangle(x + 4, y + 4, pw - 8, 1)
            cr.fill()
            return
        r = 0 if STYLE == "beta" else 6
        cr.new_path()
        if r:
            cr.arc(x + pw - r, y + r, r, -1.5708, 0)
            cr.arc(x + pw - r, y + ph - r, r, 0, 1.5708)
            cr.arc(x + r, y + ph - r, r, 1.5708, 3.1416)
            cr.arc(x + r, y + r, r, 3.1416, 4.7124)
            cr.close_path()
        else:
            cr.rectangle(x, y, pw, ph)
        cr.set_source_rgba(*C["bg"], 0.92)
        cr.fill_preserve()
        cr.set_source_rgba(*C["frame" if STYLE == "beta" else "line"], 1)
        cr.set_line_width(1)
        cr.stroke()

    @staticmethod
    def button(cr, x, cy, glyph, col, filled):
        """Кнопка BTN×BTN со значком; filled — залита акцентом (▶ на паузе)."""
        y = cy - BTN / 2
        if STYLE == "skeet":
            cr.set_source_rgba(*C["line1"], 1)
            cr.rectangle(x, y + 2, BTN, BTN - 4)
            cr.fill()
            cr.set_source_rgba(*(C["acc_d"] if filled else C["field"]), 1)
            cr.rectangle(x + 1, y + 3, BTN - 2, BTN - 6)
            cr.fill()
        else:
            cr.set_source_rgba(*(C["acc"] if filled else C["field"]), 1)
            cr.rectangle(x, y + 1, BTN, BTN - 2)
            cr.fill()
            if STYLE == "beta" and not filled:
                cr.set_source_rgba(*C["line_strong"], 1)
                cr.set_line_width(1)
                cr.rectangle(x + 0.5, y + 1.5, BTN - 1, BTN - 3)
                cr.stroke()
        ink = C.get("on_acc", C["bg"]) if filled and STYLE != "skeet" else (col if not filled else C["text"])
        gw = text_w(glyph)
        text_at(cr, glyph, x + (BTN - gw) / 2, cy, (*ink, 1))
        return (x, y, BTN, BTN)


def main():
    geom = sys.argv[1]
    pill_only = geom.startswith("pill:")
    geom = geom[5:] if pill_only else geom
    label = sys.argv[2] if len(sys.argv) > 2 else "REC"
    state = sys.argv[3] if len(sys.argv) > 3 else ""
    xy, wh = geom.split(" ")
    x, y = map(int, xy.split(","))
    w, h = map(int, wh.split("x"))

    display = Gdk.Display.get_default()
    mon = display.get_monitor_at_point(x, y)
    mg = mon.get_geometry()
    fr = Frame((x - mg.x, y - mg.y, w, h), mg.width, mg.height, label, state, pill_only)
    hold = os.path.join(state, "hold") if state else ""

    win = Gtk.Window()
    win.set_app_paintable(True)
    visual = win.get_screen().get_rgba_visual()
    if visual:
        win.set_visual(visual)
    GtkLayerShell.init_for_window(win)
    # Плашке (весь экран/окно) — block-out в rec-binds.kdl. Рамке block-out НЕЛЬЗЯ: её
    # слой во весь монитор, и в записи было бы чёрное всё (04.10.2026, «серая запись»).
    GtkLayerShell.set_namespace(win, "jarvis-rec-pill" if pill_only else "jarvis-rec-frame")
    GtkLayerShell.set_monitor(win, mon)
    GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_exclusive_zone(win, -1)          # от края экрана, не от бара
    GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
    if pill_only:
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(win, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.LEFT, fr.org[0])
        GtkLayerShell.set_margin(win, GtkLayerShell.Edge.TOP, fr.org[1])
        win.set_size_request(fr.pill_max, LABEL_H)
    else:                                              # рамка — во весь монитор
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, e, True)
    win.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                   Gdk.EventMask.POINTER_MOTION_MASK)

    region = [None]
    cursor = [None]
    was_paused = [None]

    def set_input():
        rs = fr.input_rects()
        if region[0] == rs:                        # меняем, только если что-то сдвинулось
            return
        region[0] = rs
        r = cairo.Region([cairo.RectangleInt(*q) for q in rs])
        win.get_window().input_shape_combine_region(r, 0, 0)

    def draw(_w, cr):
        fr.draw(cr)
        if not fr.drag:                            # во время перетаскивания ввод не трогаем
            set_input()
        return True

    def set_cursor(zone):
        if cursor[0] == zone:
            return
        cursor[0] = zone
        gw = win.get_window()
        if gw:
            gw.set_cursor(Gdk.Cursor.new_from_name(display, CURSORS.get(zone, "default")))

    def pos(ev):
        return ev.x + fr.org[0], ev.y + fr.org[1]

    def press(_w, ev):
        if ev.button != 1:
            return True
        mx, my = pos(ev)

        def inside(rect):
            return rect and rect[0] <= mx <= rect[0] + rect[2] and rect[1] <= my <= rect[1] + rect[3]
        if inside(fr.hot.get("pause")):
            subprocess.Popen([REC, "pause"])
            GLib.timeout_add(300, lambda: (win.queue_draw(), False)[1])
        elif inside(fr.hot.get("mic")):
            subprocess.Popen([REC, "mic"])
            GLib.timeout_add(250, lambda: (win.queue_draw(), False)[1])
        elif inside(fr.hot.get("stop")):
            subprocess.Popen([REC], start_new_session=True)
        elif not fr.pill_only:
            zone = fr.zone(mx, my)
            if zone and zone != "button":
                fr.begin(zone, mx, my)
                if hold:                           # rec_session допишет сегмент
                    open(hold, "w").close()
                set_cursor(zone)
        return True

    def motion(_w, ev):
        mx, my = pos(ev)
        if fr.drag:
            fr.motion(mx, my)
            win.queue_draw()
        else:
            set_cursor(fr.zone(mx, my))
        return True

    def release(_w, ev):
        if ev.button != 1 or not fr.drag:
            return True
        fr.end()
        if state:
            ax, ay, aw, ah = fr.area
            tmp = os.path.join(state, "geom.tmp")
            with open(tmp, "w") as f:
                f.write("%d,%d %dx%d\n" % (ax + mg.x, ay + mg.y, aw, ah))
            os.replace(tmp, os.path.join(state, "geom"))
        if hold:
            try:
                os.unlink(hold)
            except OSError:
                pass
        win.queue_draw()
        return True

    def tick():
        # Раз в полсекунды — только плашка (мигание, время); весь слой — если сменилась
        # пауза (рамка бледнеет). Перерисовывать монитор целиком дважды в секунду незачем.
        paused = os.path.exists(os.path.join(state, "paused")) if state else False
        if paused != was_paused[0] or fr.drag:
            was_paused[0] = paused
            win.queue_draw()
        else:
            p = fr.pill
            win.queue_draw_area(int(p[0] - fr.org[0]) - 2, int(p[1] - fr.org[1]) - 2,
                                int(p[2] + fr.pill_max) + 4, int(p[3]) + 4)
        return True

    def quit_(*_a):
        if hold and fr.drag:                       # не оставить запись на вечной паузе
            try:
                os.unlink(hold)
            except OSError:
                pass
        Gtk.main_quit()

    win.connect("draw", draw)
    win.connect("button-press-event", press)
    win.connect("button-release-event", release)
    win.connect("motion-notify-event", motion)
    win.show_all()
    win.get_window().input_shape_combine_region(cairo.Region(), 0, 0)
    GLib.timeout_add(500, tick)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, quit_)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, quit_)
    GLib.timeout_add_seconds(4 * 3600, quit_)  # страховка, если хозяин пропал
    Gtk.main()


if __name__ == "__main__":
    main()
