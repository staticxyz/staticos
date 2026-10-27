#!/usr/bin/env python3
"""Полосы заголовков режима «стопка» (stack_mode.py daemon). 20.10.2026.

По прозрачному слою TOP на рабочую область каждого монитора стопки (21.10.2026 — все
мониторы, не только ноутбук). Над каждым плавающим окном стола
стопки — полоса по стилю системы монитора: значок, заголовок, [Свернуть][Развернуть]
[Закрыть]. Перекрытие — по очереди фокуса: каждое окно стирает под собой полосы окон,
что ниже него, и входная зона слоя — только видимые части полос.

    полоса: тянуть — двигать окно; двойной щелчок — развернуть ⇄ обратно
    СКМ по полосе — свернуть
    ПКМ по полосе — кнопка «Поверх всех» (у закреплённого — «Открепить»), щелчок по ней
                    закрепляет; поверх окон стоит живое зеркало окна (stack_pin.py)

    stack_bars.py --shot ФАЙЛ [стиль]   макет полос без niri (проверка вида)
"""
import json
import os
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import stack_mode as sm  # noqa: E402
import rec_menu  # noqa: E402  (GTK, слои, цвета стилей)
import close_cap  # noqa: E402
import nvim_lang  # noqa: E402
from rec_menu import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo, cairo, mix  # noqa: E402

NAMESPACE = "jarvis-stack"
MIN_BMP = (".......", ".......", ".......", ".......", ".......", "#######", "#######")
GAP = 2                       # между кнопками
PAD = 6                       # от правого края полосы
ICON = 16
GRIP = 6                      # ручка размера: полоса за краем окна (21.10.2026, просьба: «нельзя менять
GRIP_C = 14                   # размер окна через мышь» — у kitty и др. без CSD niri краёв не даёт); угол
MIN_W, MIN_H = 240, 120
CURSORS = {"l": "ew-resize", "r": "ew-resize", "b": "ns-resize", "bl": "nesw-resize", "br": "nwse-resize",
           "t": "ns-resize", "tl": "nwse-resize", "tr": "nesw-resize"}   # верх — с 21.10.2026
ANIM_MS = 230                 # свернуть/вернуть: окно летит к кнопке нижней панели и обратно, как в XP
REQ = os.path.expanduser("~/.cache/stack-anim-req")          # «min|unmin ID» от stack_mode.py (SIGUSR2)
BTNS = os.path.expanduser("~/.cache/xpbar-buttons-%s.json")  # где кнопки окон — пишет xpbar
ANIM_MAX = 200                # развернуть ⇄ обратно: полоса летит на новое место, потом окно (XP)
# Своя рамка вокруг окна и полосы (21.10.2026: рамку niri в стопке выключает stack-mode.kdl) —
# как у виджетов: Skeet 6 (1+3+1+1), Default 3 (XP), Beta 1. С 21.10 и у развёрнутых.
FRAME = sm.FRAME
SHADOW = {True: 9, False: 4}  # тень вправо-вниз: у окна в фокусе глубже — видно, какое ближе
# Свои окна staticOS в стопке прячут свой заголовок (21.10.2026, просьба: «дублируются линии с
# кнопками»), значок в полосе — тот же, что был у них слева сверху (глиф Nerd Font).
APP_GLYPH = {"com.jarvis.settings": "\U000f0493"}
GLYPH_FONT = "JetBrainsMono Nerd Font"
# «Поверх всех» (21.10.2026, просьба: «сначала должна появиться кнопка как в Windows… повторно
# ПКМ — кнопка наоборот, открепить»): как кнопка «Закрепить сверху» в заголовке окон Windows
# 11 (Калькулятор, Записки), но появляется только по ПКМ — функция редкая. Закреплённое окно —
# в кольце цвета акцента (как PowerToys «Always On Top») и со значком булавки в полосе.
PIN_BMP = ("..###..", "..#.#..", "..#.#..", ".#####.", "...#...", "...#...", "...#...")
PIN_TEXT = {False: "Поверх всех", True: "Открепить"}
OFFER_MS = 4000               # кнопка гаснет, если к ней не подвели мышь
PIN_HELPER = os.path.join(HERE, "stack_pin.py")


def ui_sound(event):
    """Звук окна (ui_sound.py: набор XP/ретро/обычный, группа «winstate» в Настройках)."""
    try:
        import ui_sound as U
        U.play(event)
    except Exception as e:               # noqa: BLE001 — без звука, но не падать
        sm.log("bars: звук", event, e)


def colors(style):
    return rec_menu.style_colors(style)


class Painter:
    """Рисует одну полосу; общий для живого слоя и --shot."""

    def __init__(self, style):
        self.set_style(style)
        self.icons = {}

    def set_style(self, style):
        self.style = style
        self.C = colors(style)
        self.BH = sm.BAR_H[style]
        self.F = FRAME.get(style, 3)
        self.s = close_cap.size(style)
        self.fd = Pango.FontDescription(rec_menu.FONT)
        # 12 px (21.10.2026, просьба: «шрифт заголовков чуть меньше») — чёткий, как меню панели
        self.fd.set_absolute_size(12 * Pango.SCALE)
        self.fo = cairo.FontOptions()
        self.fo.set_antialias(cairo.ANTIALIAS_GRAY)
        self.fo.set_hint_style(cairo.HINT_STYLE_FULL)
        self.fo.set_hint_metrics(cairo.HINT_METRICS_ON)

    def buttons(self, x, y, w):
        """[(имя, bx, by)] справа налево: закрыть, развернуть, свернуть."""
        s, by = self.s, y + (self.BH - self.s) // 2
        r = x + w - PAD
        out = []
        for name in ("close", "max", "min"):
            r -= s
            out.append((name, r, by))
            r -= GAP
        return out

    def accent(self):
        return self.C.get("acc") or self.C["primary"]

    def text_w(self, s):
        key = ("w", self.style, s)
        if key not in self.icons:
            lay = PangoCairo.create_layout(cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, 1, 1)))
            PangoCairo.context_set_font_options(lay.get_context(), self.fo)
            lay.set_font_description(self.fd)
            lay.set_text(s, -1)
            self.icons[key] = lay.get_pixel_size()[0]
        return self.icons[key]

    def offer_rect(self, x, y, w, pinned):
        """Кнопка «Поверх всех»/«Открепить» слева от «Свернуть»: (bx, by, bw, s)."""
        s = self.s
        bw = 4 + 7 + 4 + self.text_w(PIN_TEXT[pinned]) + 6
        _n, mx, by = self.buttons(x, y, w)[-1]
        return mx - 2 * GAP - bw, by, bw, s

    def bitmap(self, cr, bmp, x, y, col):
        cr.set_source_rgb(*col)
        for r, row in enumerate(bmp):
            for c, ch in enumerate(row):
                if ch == "#":
                    cr.rectangle(x + c, y + r, 1, 1)
        cr.fill()

    def pin_button(self, cr, it, hover):
        C, style = self.C, self.style
        bx, by, bw, s = self.offer_rect(it["x"], it["y"], it["w"], it.get("pinned"))
        if style == "skeet":
            g = cairo.LinearGradient(0, by, 0, by + s)
            g.add_color_stop_rgb(0, *C["field_l"])
            g.add_color_stop_rgb(1, *C["field"])
            cr.set_source(g)
            cr.rectangle(bx, by, bw, s)
            cr.fill()
            cr.set_line_width(1)
            for i, col in ((0, C["line3"]), (1, C["gline"])):
                cr.set_source_rgb(*col)
                cr.rectangle(bx + i + 0.5, by + i + 0.5, bw - 2 * i - 1, s - 2 * i - 1)
                cr.stroke()
            ink = C["acc"] if hover else C["text"]
        elif style == "beta":
            self.fill(cr, bx, by, bw, s, C["acc"] if hover else C["field"])
            cr.set_source_rgb(*C["line_strong"])
            cr.set_line_width(1)
            cr.rectangle(bx + 0.5, by + 0.5, bw - 1, s - 1)
            cr.stroke()
            ink = C["bg"] if hover else C["text"]
        else:                                    # Default: синяя кнопка XP, как «Свернуть»
            top, bot = mix(C["st_top"], (1, 1, 1), 0.22), C["st_bot"]
            if hover:
                top, bot = mix(top, (1, 1, 1), 0.2), mix(bot, (1, 1, 1), 0.15)
            g = cairo.LinearGradient(0, by, 0, by + s)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(bx, by, bw, s)
            cr.fill()
            cr.set_source_rgb(*C["st_hi"])
            cr.set_line_width(1)
            cr.rectangle(bx + 0.5, by + 0.5, bw - 1, s - 1)
            cr.stroke()
            ink = C["on_surface"]
        self.bitmap(cr, PIN_BMP, bx + 4, by + (s - 7) // 2, ink)
        self.text(cr, PIN_TEXT[bool(it.get("pinned"))], bx + 15, it["y"], bw - 15, ink)

    def icon(self, app_id):
        if app_id in self.icons:
            return self.icons[app_id]
        pb = None
        try:
            try:
                from gi.repository import GioUnix as Gio
            except ImportError:
                from gi.repository import Gio
            info = None
            for name in (app_id, (app_id or "").lower()):
                try:
                    info = Gio.DesktopAppInfo.new(name + ".desktop")
                except TypeError:
                    info = None
                if info:
                    break
            if not info and app_id:
                # свои программы (com.jarvis.applist → jarvis-applist.desktop) находятся
                # только по StartupWMClass — иначе в полосе запасной значок (21.10.2026,
                # Просьба: «у них же есть иконки»); так же ищет xpbar.app_info
                from gi.repository import Gio as G
                info = next((a for a in G.AppInfo.get_all() if isinstance(a, Gio.DesktopAppInfo)
                             and (a.get_startup_wm_class() or "").lower() == app_id.lower()), None)
            theme = Gtk.IconTheme.get_default()
            gi_icon = info.get_icon() if info else None
            ii = theme.lookup_by_gicon(gi_icon, ICON, Gtk.IconLookupFlags.FORCE_SIZE) if gi_icon else None
            if ii is None and app_id:
                ii = theme.lookup_icon(app_id, ICON, Gtk.IconLookupFlags.FORCE_SIZE)
            if ii is None:
                ii = theme.lookup_icon("application-x-executable", ICON, Gtk.IconLookupFlags.FORCE_SIZE)
            pb = ii.load_icon() if ii else None
        except Exception as e:
            sm.log("значок", app_id, e)
        self.icons[app_id] = pb
        return pb

    def text(self, cr, s, x, y, width, color, shadow=None):
        lay = PangoCairo.create_layout(cr)
        PangoCairo.context_set_font_options(lay.get_context(), self.fo)
        lay.set_font_description(self.fd)
        lay.set_text(s or "", -1)
        lay.set_width(max(1, int(width)) * Pango.SCALE)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        ty = y + (self.BH - lay.get_pixel_size()[1]) // 2
        if shadow:
            cr.set_source_rgb(*shadow)
            cr.move_to(int(x) + 1, int(ty) + 1)
            PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*color)
        cr.move_to(int(x), int(ty))
        PangoCairo.show_layout(cr, lay)

    def glyph(self, cr, g, x, y, focused):
        """Значок-глиф вместо картинки — цвет как у заголовка своего окна по стилю."""
        C = self.C
        if self.style == "default":
            col, sh = C["on_surface"], C["st_dark"]
        else:
            col, sh = C.get("acc") or C["primary"], None
        if not focused:
            col = mix(col, C.get("dim", C["text"]), 0.5)
        lay = PangoCairo.create_layout(cr)
        PangoCairo.context_set_font_options(lay.get_context(), self.fo)
        fd = Pango.FontDescription(GLYPH_FONT)
        fd.set_absolute_size(ICON * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(g, -1)
        gw, gh = lay.get_pixel_size()
        gx, gy = int(x + (ICON - gw) // 2), int(y + (self.BH - gh) // 2)
        if sh:
            cr.set_source_rgb(*sh)
            cr.move_to(gx + 1, gy + 1)
            PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*col)
        cr.move_to(gx, gy)
        PangoCairo.show_layout(cr, lay)

    def fill(self, cr, x, y, w, h, col, a=1.0):
        cr.set_source_rgba(*col, a)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def background(self, cr, x, y, w, focused, framed=False):
        C, BH = self.C, self.BH
        if self.style == "default":
            g = cairo.LinearGradient(0, y, 0, y + BH)
            for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
                g.add_color_stop_rgb(off, *C[key])
            cr.set_source(g)
            cr.rectangle(x, y, w, BH)
            cr.fill()
            self.fill(cr, x, y + BH - 1, w, 1, C["st_dark"])
            if not focused:
                self.fill(cr, x, y, w, BH, mix(C["st_mid"], (0.85, 0.85, 0.85), 0.55), 0.55)
        elif self.style == "skeet":
            self.fill(cr, x, y, w, BH, C["bg"])
            for dy, k in ((0, 0.0), (1, 0.55)):
                g = cairo.LinearGradient(x, 0, x + w, 0)
                for off, col in zip((0, 0.5, 1), C["strip"]):
                    c = mix(col, (0, 0, 0), k)
                    if not focused:
                        c = mix(c, C["bg"], 0.6)
                    g.add_color_stop_rgb(off, *c)
                cr.set_source(g)
                cr.rectangle(x, y + dy, w, 1)
                cr.fill()
            self.fill(cr, x, y + BH - 2, w, 1, C["line2"])
            self.fill(cr, x, y + BH - 1, w, 1, C["line3"])
            if not framed:                       # в рамке края даёт её внутренняя линия
                self.fill(cr, x, y, 1, BH, C["line3"])
                self.fill(cr, x + w - 1, y, 1, BH, C["line3"])
        else:
            self.fill(cr, x, y, w, BH, C["bar"] if focused else mix(C["bar"], C["bg"], 0.5))
            self.fill(cr, x, y + BH - 1, w, 1, C["line"])
            self.fill(cr, x, y, w, 1, C["frame"])

    def button(self, cr, name, bx, by, hover, maxed):
        C, s, style = self.C, self.s, self.style
        glyph = {"close": None, "max": close_cap.RESTORE_BMP if maxed else close_cap.MAX_BMP,
                 "min": MIN_BMP}[name]
        if name == "close" or style == "skeet":
            close_cap.draw(cr, style, C, bx, by, hover, glyph=glyph,
                           hover_ink=None if name == "close" else C.get("acc"))
            return
        if style == "beta":
            self.fill(cr, bx, by, s, s, C["acc"] if hover else C["field"])
            cr.set_source_rgb(*C["line_strong"])
            cr.set_line_width(1)
            cr.rectangle(bx + 0.5, by + 0.5, s - 1, s - 1)
            cr.stroke()
            ink = C["bg"] if hover else C["text"]
        else:                                    # Default: синяя кнопка XP рядом с красной
            top, bot = mix(C["st_top"], (1, 1, 1), 0.22), C["st_bot"]
            if hover:
                top, bot = mix(top, (1, 1, 1), 0.2), mix(bot, (1, 1, 1), 0.15)
            g = cairo.LinearGradient(0, by, 0, by + s)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(bx, by, s, s)
            cr.fill()
            cr.set_source_rgb(*C["st_hi"])
            cr.set_line_width(1)
            cr.rectangle(bx + 0.5, by + 0.5, s - 1, s - 1)
            cr.stroke()
            ink = C["on_surface"]
        cr.set_source_rgb(*ink)
        for r, row in enumerate(glyph):
            for c, ch in enumerate(row):
                if ch == "#":
                    cr.rectangle(bx + (s - 7) // 2 + c, by + (s - 7) // 2 + r, 1, 1)
        cr.fill()

    def ring(self, cr, x, y, w, h, i, t, col):
        """Кольцо толщиной t, отступив i от края прямоугольника (x, y, w, h)."""
        cr.set_source_rgb(*col)
        cr.rectangle(x + i, y + i, w - 2 * i, h - 2 * i)
        cr.rectangle(x + i + t, y + i + t, w - 2 * (i + t), h - 2 * (i + t))
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

    def frame(self, cr, x, y, w, h, focused):
        """Рамка окна вместе с полосой (снаружи), по стилю — как у виджетов того же вида."""
        C, st = self.C, self.style
        if st == "skeet":                        # gamesense: светлая 1, средняя 3, светлая 1, чёрная 1
            hi = C["line1_on"] if focused else C["line1"]
            for i, t, col in ((0, 1, hi), (1, 3, C["line2"]), (4, 1, hi), (5, 1, C["line3"])):
                self.ring(cr, x, y, w, h, i, t, col)
        elif st == "beta":
            self.ring(cr, x, y, w, h, 0, 1, mix(C["line_strong"], C["acc"], 0.55) if focused
                      else C["line_strong"])
        else:                                    # XP: рамка в цвет заголовка, снаружи тёмная линия
            mid = C["st_mid"] if focused else mix(C["st_mid"], (0.85, 0.85, 0.85), 0.3)
            self.ring(cr, x, y, w, h, 0, self.F, mid)
            self.ring(cr, x, y, w, h, 0, 1, C["st_dark"])

    @staticmethod
    def shadow(cr, x, y, w, h, depth):
        """Мягкая тень вправо-вниз: слои со сдвигом 1…depth — у края гуще."""
        a = 0.34 / depth
        # Только снаружи окна: внутри всё равно закроют рамка, полоса и само окно, а
        # заливка целиком — 3/4 времени перерисовки при перетаскивании (21.10.2026).
        cr.save()
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(x - 1, y - 1, w + depth + 2, h + depth + 2)
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_source_rgba(0, 0, 0, 0.18)
        cr.rectangle(x - 1, y - 1, w + 2, h + 2)
        cr.fill()
        for k in range(1, depth + 1):
            cr.set_source_rgba(0, 0, 0, a)
            cr.rectangle(x + k, y + k, w, h)
            cr.fill()
        cr.restore()

    def bar(self, cr, it, hover=None, offer=False):
        """it: x, y (верх полосы), w, title, app_id, focused, maxed, pinned; offer — кнопка
        «Поверх всех» видна."""
        x, y, w, C = it["x"], it["y"], it["w"], self.C
        self.background(cr, x, y, w, it["focused"], bool(it.get("F")))
        glyph = APP_GLYPH.get(it.get("app_id"))
        # файл в nvim — значок языка, как в нижней панели (nvim_lang.py, 21.10.2026)
        pb = None if glyph else self.icon(nvim_lang.icon(it.get("title"), it.get("app_id"))
                                          or it.get("app_id"))
        ix = x + 7
        if glyph:
            self.glyph(cr, glyph, ix, y, it["focused"])
        elif pb is not None:
            Gdk.cairo_set_source_pixbuf(cr, pb, ix, y + (self.BH - ICON) // 2)
            if it["focused"]:
                cr.paint()
            else:
                cr.paint_with_alpha(0.6)
        btns = self.buttons(x, y, w)
        tx = ix + ICON + 7
        right = btns[-1][1]
        if offer:
            right = self.offer_rect(x, y, w, it.get("pinned"))[0]
        elif it.get("pinned"):                   # булавка: окно закреплено поверх всех
            right -= 2 * GAP + 7
            self.bitmap(cr, PIN_BMP, right, y + (self.BH - 7) // 2, self.accent())
        tw = right - 8 - tx
        if self.style == "default":
            self.text(cr, it.get("title"), tx, y, tw, C["on_surface"] if it["focused"]
                      else mix(C["on_surface"], C["st_mid"], 0.25), C["st_dark"] if it["focused"] else None)
        else:
            self.text(cr, it.get("title"), tx, y, tw, C["text"] if it["focused"] else C.get("dim", C["text"]))
        for name, bx, by in btns:
            self.button(cr, name, bx, by, hover == (it["id"], name), it.get("maxed"))
        if offer:
            self.pin_button(cr, it, hover == (it["id"], "pin"))


class Fast:
    """Запросы niri без ожидания ответа — одно постоянное соединение (перетаскивание и
    размер мышью: каждое движение — запрос; ждать ответ на каждый = рывки). Ответы читаются
    и выбрасываются; соединение порвалось — новое."""

    def __init__(self):
        self.s = None

    def open(self):
        s = socket.socket(socket.AF_UNIX)
        s.connect(sm.sock_path())
        s.setblocking(False)
        GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                          self.drain, s)
        self.s = s

    def drain(self, _fd, cond, s):
        try:
            if cond & (GLib.IO_HUP | GLib.IO_ERR) or not s.recv(65536):
                raise OSError
        except BlockingIOError:
            return True
        except OSError:
            if self.s is s:
                self.s = None
            s.close()
            return False
        return True

    def A(self, _act, **kw):
        data = json.dumps({"Action": {_act: kw}}).encode() + b"\n"
        for _try in (0, 1):
            try:
                if self.s is None:
                    self.open()
                self.s.sendall(data)
                return
            except OSError:
                self.s = None
        sm.A(_act, **kw)


FAST = Fast()


def ease(k):
    return 4 * k ** 3 if k < 0.5 else 1 - (-2 * k + 2) ** 3 / 2


class Ghost:
    """Слой OVERLAY на весь монитор, без ввода — по нему летит окно (полоса и контур)
    между своим местом и кнопкой на нижней панели. Показан только на время полёта."""

    def __init__(self, ob):
        self.ob, self.anims, self.tick_id = ob, [], None
        w = self.win = Gtk.Window()
        w.set_title(NAMESPACE + "-anim")
        w.set_app_paintable(True)
        vis = w.get_screen().get_rgba_visual()
        if vis:
            w.set_visual(vis)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE + "-anim")
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(w, ob.mon)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(w, e, True)
        GtkLayerShell.set_exclusive_zone(w, -1)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        w.set_decorated(False)
        w.set_resizable(False)
        w.connect("draw", self.on_draw)
        # Щелчки сквозь слой. Не только при realize: после hide() и нового show() GTK
        # мог выставить поверхность без пустой области ввода, и курсор над нижней панелью
        # на время полёта становился ↕ (21.10.2026, просьба: «кликаю на окно в панели, а
        # курсор меняет вид»). Курсор слоя — обычная стрелка на случай, если ввод всё же дойдёт
        w.connect("realize", self.no_input)
        w.connect("map", self.no_input)

    def no_input(self, w):
        w.input_shape_combine_region(cairo.Region())
        gw = w.get_window()
        if gw is not None:
            gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), "default"))

    def start(self, it, src, dst, done=None, ms=ANIM_MS):
        a = {"it": it, "src": src, "dst": dst, "t0": None, "done": done, "k": 0.0, "ms": ms}
        self.anims.append(a)
        if not self.win.get_visible():
            self.win.show_all()
            self.no_input(self.win)
        if self.tick_id is None:
            self.tick_id = self.win.add_tick_callback(self.on_tick)
        # кадры не пошли (слой не показался) — действие всё равно выполнить
        GLib.timeout_add(ms + 500, lambda: self.finish(a) and False)

    def finish(self, a):
        if a in self.anims:
            self.anims.remove(a)
        cb = a.pop("done", None)
        if cb:
            try:
                cb()
            except Exception as e:             # noqa: BLE001 — сбой niri не роняет демон
                sm.log("bars: анимация:", e)
        if not self.anims and self.win.get_visible():
            self.win.hide()
        return False

    def on_tick(self, _w, clock):
        now = clock.get_frame_time() / 1000
        for a in list(self.anims):
            if a["t0"] is None:
                a["t0"] = now
            a["k"] = min(1.0, (now - a["t0"]) / a["ms"])
            if a["k"] >= 1:
                self.finish(a)
        self.win.queue_draw()
        if not self.anims:
            self.tick_id = None
            return False
        return True

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_CLEAR)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        P = self.ob.P
        C = P.C
        for a in self.anims:
            e = ease(a["k"])
            x, y, w, h = (s + (d - s) * e for s, d in zip(a["src"], a["dst"]))
            x, y, w, h = int(x), int(y), max(8, int(w)), max(4, int(h))
            if h > P.BH:                        # тело окна — полупрозрачное, с контуром
                P.fill(cr, x, y + P.BH, w, h - P.BH, C["bg"], 0.45)
                cr.set_source_rgba(*C["sel_bg"], 0.9)
                cr.set_line_width(1)
                cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
                cr.stroke()
            cr.save()
            cr.rectangle(x, y, w, min(h, P.BH))
            cr.clip()
            P.bar(cr, dict(a["it"], x=x, y=y, w=w, focused=True, maxed=False))
            cr.restore()
        return False


class OutBar:
    """Слой полос одного монитора: свой стиль, свои полосы, своя рабочая область."""

    def __init__(self, mgr, out, mon):
        self.mgr, self.out, self.mon = mgr, out, mon
        self.ghost = None
        self.style = sm.style(out)
        self.P = Painter(self.style)
        self.items = []          # снизу вверх: {id, x, y, w, tile:(x,y,w,h), …}
        self.visible = False
        self.desk_vis = False    # стол стопки на экране; visible — ещё и не спрятан полным экраном
        self.hover = None
        self.press = None        # {id, zone, x, y, moved, last}
        self.z = []              # порядок окон снизу вверх — свой, niri его не отдаёт
        self.raised = None       # кого последним подняли (FocusWindow) — без повторов
        self.work_size = None
        self.offer = None        # у какого окна видна кнопка «Поверх всех» (ПКМ по полосе)
        self.offer_src = None

        w = self.win = Gtk.Window()
        w.set_title(NAMESPACE)
        w.set_app_paintable(True)
        vis = w.get_screen().get_rgba_visual()
        if vis:
            w.set_visual(vis)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP)
        if mon is not None:
            GtkLayerShell.set_monitor(w, mon)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(w, e, True)
        GtkLayerShell.set_exclusive_zone(w, 0)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                     Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("draw", self.on_draw)
        w.connect("button-press-event", self.on_press)
        w.connect("button-release-event", self.on_release)
        w.connect("motion-notify-event", self.on_motion)
        w.connect("leave-notify-event", self.on_leave)
        w.connect("size-allocate", self.on_alloc)
        w.connect("realize", lambda *_a: self.set_input())
        w.show_all()

    @property
    def st(self):
        return self.mgr.st

    def set_style(self, style):
        if style != self.style:
            self.style = style
            self.P.set_style(style)
            return True
        return False

    def dump(self):
        """Слой как есть → ~/.cache/stack-bars-<монитор>.png (+ контуры окон) и .json."""
        a = self.win.get_allocation()
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, a.width, a.height)
        cr = cairo.Context(surf)
        cr.set_source_rgb(0.1, 0.12, 0.16)
        cr.paint()
        for it in self.items:
            tx, ty, tw, th = it["tile"]
            cr.set_source_rgb(0.5, 0.5, 0.5)
            cr.rectangle(tx + 0.5, ty + 0.5, tw - 1, th - 1)
            cr.stroke()
        vis, self.visible = self.visible, True
        self.on_draw(None, cr)
        self.visible = vis
        base = os.path.expanduser("~/.cache/stack-bars-" + self.out)
        surf.write_to_png(base + ".png")
        with open(base + ".json", "w") as f:
            json.dump({"output": self.out, "style": self.style, "visible": vis,
                       "overview": self.mgr.overview, "size": [a.width, a.height],
                       "items": self.items}, f, ensure_ascii=False, indent=1)

    def on_alloc(self, _w, a):
        if self.work_size != [a.width, a.height]:
            sm.log("bars:", self.out, "рабочая область", self.work_size, "→", [a.width, a.height])
            self.work_size = [a.width, a.height]
            st = sm.load_state()
            o = (st.get("outs") or {}).get(self.out)
            if sm.active(st) and o is not None and o.get("work") != self.work_size:
                o["work"] = self.work_size
                sm._save(sm.STATE, st)
                self.mgr.st = st
            GLib.timeout_add(80, self.recalibrate)

    def recalibrate(self):
        """Рабочая область сменилась (бар подрос, панель ушла) — где теперь SetFixed(0, 0).
        Окно ставится на то место, где оно по старой поправке и так стоит; разница — сдвиг,
        окно тут же возвращается. Развёрнутые окна подгоняются под новую область."""
        st = sm.load_state()
        o = (st.get("outs") or {}).get(self.out)
        if not sm.active(st) or o is None:
            sm.log("bars:", self.out, "перемер — стопка не активна")
            return False
        ox, oy = sm.offset(st, self.out)
        ww, wh = sm.work(st, self.out)
        _wss, wins = sm.query()
        cand = [w for w in wins if w.get("workspace_id") == o["desk"] and w.get("is_floating")
                and not sm.hidden(w) and sm.tpos(w)]
        inside = [w for w in cand if 0 <= sm.tpos(w)[0] - ox and sm.tpos(w)[0] - ox + 200 < ww
                  and 0 <= sm.tpos(w)[1] - oy and sm.tpos(w)[1] - oy + 200 < wh]
        w = (inside or cand or [None])[0]
        # на столе ни одного окна (все свёрнуты) — мерить не по чему: перемерить, как только
        # окно появится (21.10.2026: верхний бар ушёл в «при наведении», смещение 44 осталось)
        self.need_recal = w is None
        if w is not None:
            p = sm.tpos(w)
            gx, gy = int(round(p[0] - ox)), int(round(p[1] - oy))
            sm.A("MoveFloatingWindow", id=w["id"], x={"SetFixed": gx}, y={"SetFixed": gy})
            w2 = next((x for x in sm.query()[1] if x["id"] == w["id"]), None)
            p2 = sm.tpos(w2) if w2 else None
            sm.log("bars:", self.out, "перемер по", w["id"], p, (gx, gy), "→", p2)
            if p2:
                new = [int(round(p2[0] - gx)), int(round(p2[1] - gy))]
                if p2 != p:
                    sm.A("MoveFloatingWindow", id=w["id"], x={"AdjustFixed": p[0] - p2[0]},
                         y={"AdjustFixed": p[1] - p2[1]})
                if new != [ox, oy]:
                    sm.log("bars:", self.out, "рабочая область сдвинулась", [ox, oy], "→", new)
                    st["outs"][self.out]["offset"] = new
                    sm._save(sm.STATE, st)
        bh = self.P.BH
        ids = {x["id"] for x in wins if x.get("workspace_id") == o["desk"]}
        for key in st.get("max") or {}:
            x = next((x for x in wins if x["id"] == int(key)), None)
            if x and x["id"] in ids:
                sm.place(int(key), *sm.max_rect(st, self.out, x))
        self.mgr.st = sm.load_state()
        self.mgr.schedule()
        return False

    def set_fs_layer(self, fs):
        """Полный экран на столе стопки: niri рисует его поверх слоя TOP, а плавающие окна — всё
        равно поверх него, и они оставались голыми, без полос и рамок (21.10.2026, просьба: «когда
        видео на полный экран, окно появляется без рамок»). Пока он есть — полосы в OVERLAY.
        Слой не зависит от фокуса: смена слоя у полос, спрятанных под полным экраном, выходила
        на экран с опозданием ~0,27 с («рамки отстают от окна»), поэтому при фокусе на полном
        экране полосы в OVERLAY просто гаснут (visible), а не уходят вниз — см. apply_fs."""
        if fs != getattr(self, "fs_layer", False):
            self.fs_layer = fs
            GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY if fs else GtkLayerShell.Layer.TOP)
            self.win.queue_draw()
            sm.log("bars: полосы", "над полным экраном" if fs else "обычным слоем", self.out)

    def apply_fs(self, fid):
        """Слой и видимость полос по фокусу fid (по последнему опросу niri). На столе с полным
        экраном фокус на нём — niri прячет плавающие под него, и полосы гаснут: иначе висели бы
        пустыми рамками поверх видео (Alt+Tab, Image 441). True — видимость поменялась."""
        S, wins, size = getattr(self, "fs_snap", (None, (), None))
        fs = bool(self.desk_vis and size and any(
            w.get("workspace_id") == S and not w.get("is_floating") and sm.wsize(w) == list(size) for w in wins))
        foc = next((w for w in wins if w["id"] == fid), None)
        self.set_fs_layer(fs)
        vis = bool(self.desk_vis and (not fs or (foc and foc.get("is_floating"))))
        changed, self.visible = vis != self.visible, vis
        return changed

    def fs_focus(self, fid):
        """Фокус сменился — сразу, не дожидаясь refresh: через цикл обновления полосы
        появлялись позже окна (21.10.2026, просьба: «рамки отстают от окна»)."""
        S, wins, _size = getattr(self, "fs_snap", (None, (), None))
        if any(w["id"] == fid and w.get("workspace_id") == S for w in wins) and self.apply_fs(fid):
            self.set_input()
            self.win.queue_draw()

    def update(self, wss, wins):
        S = sm.so(self.st, self.out).get("desk")
        act = next((d for d in sm.desks(wss, self.out) if d.get("is_active")), None)
        self.desk_vis = bool(S and act and act["id"] == S and not self.mgr.overview)
        size = (getattr(self.mgr, "out_size", None) or {}).get(self.out)
        self.fs_snap = (S, wins, size)
        self.apply_fs(act.get("active_window_id") if act else None)
        ox, oy = sm.offset(self.st, self.out)
        mx = self.st.get("max") or {}
        desk = [w for w in wins if S is not None and w.get("workspace_id") == S
                and w.get("is_floating") and not sm.hidden(w)]
        self.restack(desk)
        if desk and getattr(self, "need_recal", False):
            self.need_recal = False
            GLib.timeout_add(80, self.recalibrate)
        items = []
        for w in sorted(desk, key=lambda w: self.order(w["id"])):
            p, ts_ = sm.tpos(w), sm.lay(w).get("tile_size")
            if not p or not ts_:
                continue
            tx, ty = int(round(p[0] - ox)), int(round(p[1] - oy))
            tw, th = int(round(ts_[0])), int(round(ts_[1]))
            wo, ws_ = sm.lay(w).get("window_offset_in_tile") or (0, 0), sm.wsize(w) or (tw, th)
            items.append({"id": w["id"], "app_id": w.get("app_id"), "title": w.get("title"),
                          "focused": bool(w.get("is_focused")), "maxed": str(w["id"]) in mx,
                          "tile": (tx, ty, tw, th), "x": tx, "y": ty - self.P.BH, "w": tw,
                          "size": sm.wsize(w), "F": self.P.F, "pinned": w["id"] in self.mgr.pins,
                          # зеркалу «поверх всех» — само окно, без отступа плитки: 1:1, не растянуто
                          "win": (tx + int(round(wo[0])), ty + int(round(wo[1])),
                                  int(round(ws_[0])), int(round(ws_[1])))})
        if self.offer is not None and self.offer not in {i["id"] for i in items}:
            self.set_offer(None)
        if self.press and self.press.get("moved"):          # тянем — место знаем сами
            old = next((i for i in self.items if i["id"] == self.press["id"]), None)
            new = next((i for i in items if i["id"] == self.press["id"]), None)
            if old and new:
                new.update({k: old[k] for k in ("tile", "x", "y", "w")})
        self.items = items
        self.set_input()
        self.win.queue_draw()

    def restack(self, desk):
        """Кто над кем. niri поднимает плавающее окно не при каждом фокусе (фокус после
        закрытия соседа, активация самим приложением), а порядок наружу не отдаёт — полосы
        рисовались не в том порядке, полоса нижнего окна ложилась на верхнее (21.10.2026).
        Поэтому порядок свой: новое окно — наверх, окно в фокусе — наверх, и niri его тут же
        поднимает (FocusWindow = activate_window с подъёмом). Так оба порядка совпадают."""
        ids = {w["id"] for w in desk}
        self.z = [i for i in self.z if i in ids]
        self.z += [w["id"] for w in sorted(desk, key=sm.ts) if w["id"] not in self.z]
        fid = next((w["id"] for w in desk if w.get("is_focused")), None)
        if fid is None:
            return
        if self.z[-1] != fid:
            self.z.remove(fid)
            self.z.append(fid)
        if fid != self.raised and not self.press:
            self.raised = fid
            FAST.A("FocusWindow", id=fid)

    def order(self, wid):
        """Снизу вверх: по своему порядку, закреплённые поверх всех — всегда последними
        (их полоса и рамка сверху, их окно стирает полосы под собой — там зеркало)."""
        return (wid in self.mgr.pins, self.z.index(wid) if wid in self.z else 1 << 30)

    def set_offer(self, wid):
        if self.offer_src:
            GLib.source_remove(self.offer_src)
            self.offer_src = None
        if wid != self.offer:
            self.offer = wid
            self.win.queue_draw()
        if wid is not None:
            self.offer_src = GLib.timeout_add(OFFER_MS, self.offer_expire)

    def offer_expire(self):
        if self.offer is not None and self.hover == (self.offer, "pin"):
            return True                          # мышь на кнопке — ждём дальше
        self.offer_src = None
        self.set_offer(None)
        return False

    def deco(self, it):
        """Окно целиком — рамка, полоса, окно: (x, y, w, h)."""
        F = it.get("F", 0)
        tx, ty, tw, th = it["tile"]
        return tx - F, it["y"] - F, tw + 2 * F, th + self.P.BH + 2 * F

    # — свернуть/вернуть с полётом —
    def btn_rect(self, wid):
        """Кнопка окна на нижней панели этого монитора — в координатах монитора."""
        g = self.mon.get_geometry()
        try:
            d = json.load(open(BTNS % self.out))
            x, y, w, h = d["btns"][str(wid)]
            return [x, g.height - d["win_h"] + y, w, h]
        except (OSError, ValueError, KeyError, TypeError):
            return [g.width // 2 - 70, g.height - 30, 140, 28]

    def fly(self, it, src, dst, done=None, ms=ANIM_MS):
        if self.ghost is None:
            self.ghost = Ghost(self)
        self.ghost.start(it, src, dst, done, ms)

    def toggle_max(self, wid, geom=None):
        """Развернуть ⇄ обратно с полётом полосы, как в XP (21.10.2026, просьба: «не хватает
        анимации во весь экран и обратно»): сперва полёт, потом окно встаёт на место."""
        it = next((i for i in self.items if i["id"] == wid), None)
        if not it or not self.visible:
            sm.toggle_max(wid, geom)
            return
        ox, oy = sm.offset(self.st, self.out)
        x, y, w, h = self.deco(it)
        g = (self.st.get("max") or {}).get(str(wid))
        if g:
            F, BH = self.P.F, self.P.BH
            dst = [g[0] + ox - F, g[1] + oy - BH - F, g[2] + 2 * F, g[3] + BH + 2 * F]
        else:
            # полёт туда же, где окно встанет: «Под островком» — ниже островка (21.10.2026)
            ww, wh = sm.work(self.st, self.out)
            t = sm.max_top(self.out)
            dst = [ox, oy + t, ww, wh - t]
        ui_sound("restore" if g else "maximize")
        self.fly(it, [x + ox, y + oy, w, h], dst, lambda: sm.toggle_max(wid, geom), ANIM_MAX)

    def minimize(self, wid):
        it = next((i for i in self.items if i["id"] == wid), None)
        if it and self.visible:
            ox, oy = sm.offset(self.st, self.out)
            th = it["tile"][3]
            x, y, w, h = self.deco(it)
            self.fly(it, [x + ox, y + oy, w, h], self.btn_rect(wid))
        ui_sound("minimize")
        sm.minimize(wid)

    def unminimize(self, w):
        """Сперва полёт от кнопки на прежнее место, потом окно появляется (как в XP)."""
        wid = w["id"]
        g = (self.st.get("min") or {}).get(str(wid))
        if not g:
            sm.unminimize(wid)
            return
        ox, oy = sm.offset(self.st, self.out)
        b = sm.border(w)
        it = {"id": wid, "app_id": w.get("app_id"), "title": w.get("title")}
        ui_sound("unminimize")
        self.fly(it, self.btn_rect(wid),
                 [g[0] + ox, g[1] + oy - self.P.BH, g[2] + 2 * b, g[3] + 2 * b + self.P.BH],
                 lambda: sm.unminimize(wid))

    # — вид —
    def set_input(self):
        gw = self.win.get_window()
        if gw is None:
            return
        reg = cairo.Region()
        if self.visible:
            for it in self.items:
                tx, ty, tw, th = it["tile"]
                if not it["maxed"]:              # рамка и ручки размера за ней
                    G, F = max(GRIP, it["F"]), it["F"]
                    reg.union(cairo.RectangleInt(tx - G, it["y"] - G, tw + 2 * G,
                                                 ty + th + 2 * G - it["y"]))
                reg.subtract(cairo.RectangleInt(tx, ty, tw, th))
                reg.union(cairo.RectangleInt(it["x"], it["y"], it["w"], self.P.BH))
        self.win.input_shape_combine_region(reg)

    def on_draw(self, _w, cr):
        if _w is not None:
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
        if not self.visible:
            return False
        for it in self.items:                    # снизу вверх: тень, окно стирает нижние, рамка
            dx, dy, dw, dh = self.deco(it)
            if it["F"]:
                cr.set_operator(cairo.OPERATOR_OVER)
                self.P.shadow(cr, dx, dy, dw, dh, SHADOW[it["focused"]])
            cr.set_operator(cairo.OPERATOR_CLEAR)
            tx, ty, tw, th = it["tile"]
            cr.rectangle(tx, ty, tw, th)
            cr.fill()
            cr.set_operator(cairo.OPERATOR_OVER)
            if it["F"]:
                self.P.frame(cr, dx, dy, dw, dh, it["focused"])
            cr.save()
            cr.rectangle(it["x"], it["y"], it["w"], self.P.BH)
            cr.clip()
            self.P.bar(cr, it, self.hover, self.offer == it["id"])
            cr.restore()
        return False

    # — мышь —
    def hit(self, x, y):
        for it in reversed(self.items):
            tx, ty, tw, th = it["tile"]
            if tx <= x < tx + tw and ty <= y < ty + th:
                return None, None
            F = it["F"]
            g = self.grip_at(it, x, y)               # края и углы, верх тоже — до полосы
            if g:
                return it, "rs:" + g
            if it["x"] - F <= x < it["x"] + it["w"] + F and it["y"] - F <= y < it["y"]:
                return it, "title"                   # верх рамки над полосой
            if it["x"] <= x < it["x"] + it["w"] and it["y"] <= y < it["y"] + self.P.BH:
                if self.offer == it["id"]:
                    bx, by, bw, s = self.P.offer_rect(it["x"], it["y"], it["w"], it.get("pinned"))
                    if bx <= x < bx + bw and by - 4 <= y < by + s + 4:
                        return it, "pin"
                for name, bx, by in self.P.buttons(it["x"], it["y"], it["w"]):
                    if bx <= x < bx + self.P.s and by - 4 <= y < by + self.P.s + 4:
                        return it, name
                return it, "title"
        return None, None

    @staticmethod
    def grip_at(it, x, y):
        """Край окна под курсором: l, r, t, b, tl, tr, bl, br — или None. Верх — над
        полосой заголовка (21.10.2026, просьба: «со всех углов и краёв, а не только справа
        снизу»), сама полоса по-прежнему таскает окно."""
        if it["maxed"]:
            return None
        tx, ty, tw, th = it["tile"]
        G = max(GRIP, it.get("F", 0))
        if not (tx - G <= x < tx + tw + G and it["y"] - G <= y < ty + th + G):
            return None
        l, r, b, t = x < tx, x >= tx + tw, y >= ty + th, y < it["y"]
        if (l or r) and y >= ty + th - GRIP_C:
            b = True
        if (l or r) and y < it["y"] + GRIP_C:
            t = True
        if (b or t) and not (l or r):
            l, r = x < tx + GRIP_C, x >= tx + tw - GRIP_C
        e = ("t" if t else "b" if b else "") + ("l" if l else "r" if r else "")
        return e or None

    def set_cursor(self, edge):
        gw = self.win.get_window()
        if gw is None or edge == getattr(self, "cursor_edge", None):
            return
        self.cursor_edge = edge
        cur = Gdk.Cursor.new_from_name(gw.get_display(), CURSORS[edge]) if edge else None
        gw.set_cursor(cur)

    def resize_to(self, p, ev):
        """Тянем край: новый размер (и место — у левого края) от положения на нажатии."""
        e, (x0, y0, tw0, th0), (w0, h0) = p["edge"], p["tile0"], p["size0"]
        dx, dy = int(ev.x - p["x"]), int(ev.y - p["y"])
        nw = max(MIN_W, w0 - dx if "l" in e else w0 + dx if "r" in e else w0)
        nh = max(MIN_H, h0 + dy if "b" in e else h0 - dy if "t" in e else h0)
        nx = x0 + (w0 - nw) if "l" in e else x0
        ny = y0 + (h0 - nh) if "t" in e else y0
        top = self.P.BH + self.P.F                 # полоса заголовка не уходит за верх
        if ny < top:
            nh, ny = max(MIN_H, nh - (top - ny)), top
        if (nw, nh, nx, ny) == p.get("sent"):
            return
        p["sent"] = (nw, nh, nx, ny)
        if nw != p.get("sw"):
            FAST.A("SetWindowWidth", id=p["id"], change={"SetFixed": nw})
            p["sw"] = nw
        if nh != p.get("sh"):
            FAST.A("SetWindowHeight", id=p["id"], change={"SetFixed": nh})
            p["sh"] = nh
        if (nx, ny) != (p.get("sx", x0), p.get("sy", y0)):
            FAST.A("MoveFloatingWindow", id=p["id"], x={"SetFixed": nx}, y={"SetFixed": ny})
            p["sx"], p["sy"] = nx, ny
        it = next((i for i in self.items if i["id"] == p["id"]), None)
        if it:
            bw, bh = tw0 - w0, th0 - h0          # рамка niri вокруг окна
            it["tile"] = (nx, ny, nw + bw, nh + bh)
            it["x"], it["w"], it["y"] = nx, nw + bw, ny - self.P.BH
            self.set_input()
            self.win.queue_draw()

    def on_press(self, _w, ev):
        it, zone = self.hit(ev.x, ev.y)
        had_offer = self.offer
        if self.offer is not None and zone != "pin":
            self.set_offer(None)                 # щелчок мимо кнопки — погасить
        if not it:
            return False
        if ev.type == Gdk.EventType._2BUTTON_PRESS:
            if zone == "title" and ev.button == 1:
                self.press = None
                self.toggle_max(it["id"])
            return True
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        self.press = {"id": it["id"], "zone": zone, "x": ev.x, "y": ev.y, "last": (ev.x, ev.y),
                      "moved": False, "button": ev.button, "tile0": it["tile"], "had_offer": had_offer}
        if zone.startswith("rs:"):
            self.press.update(edge=zone[3:], tile0=it["tile"], size0=tuple(it["size"] or it["tile"][2:]))
        if ev.button == 1 and not it["focused"]:
            self.raised = it["id"]
            FAST.A("FocusWindow", id=it["id"])
            if self.z and self.z[-1] != it["id"] and it["id"] in self.z:
                self.z.remove(it["id"])
                self.z.append(it["id"])
                self.items.sort(key=lambda i: self.order(i["id"]))
                self.win.queue_draw()
        return True

    def on_motion(self, _w, ev):
        p = self.press
        if p and p["zone"].startswith("rs:") and p["button"] == 1:
            p["moved"] = True
            self.resize_to(p, ev)
            return True
        if p and p["zone"] == "title" and p["button"] == 1:
            if not p["moved"] and abs(ev.x - p["x"]) + abs(ev.y - p["y"]) < 4:
                return True
            if str(p["id"]) in (self.st.get("max") or {}):
                return True                  # развёрнутое не таскается (как в Windows)
            p["moved"] = True
            # Место — от нажатия, без накопления (21.10.2026, просьба: «лагает, как будто
            # 60 герц»): запрос без ожидания ответа (FAST), полосу рисуем сразу сами,
            # события niri на время перетаскивания не перечитываются (Bars.refresh).
            x0, y0, tw, th = p["tile0"]
            F = self.P.F
            # Курсор ушёл на другой монитор — окно переезжает на его стол стопки и тянется
            # дальше там (21.10.2026, просьба: «не перетаскивается окно с монитора msi на ноут и
            # наоборот»). События идут сюда же: нажатие держит слой, где тянуть начали.
            dst = self.cross(p, ev)
            b = self.mgr.bars.get(p.get("out", self.out)) or self
            dx = p.get("dx", 0)
            nx = x0 + int(ev.x - p["x"]) - dx
            ny = max(b.P.BH + b.P.F, y0 + int(ev.y - p["y"]))   # полоса не уходит за верх
            if dst:
                ny = max(dst.P.BH + dst.P.F, ny)
            if (nx, ny) != p.get("sent"):
                p["sent"] = (nx, ny)
                FAST.A("MoveFloatingWindow", id=p["id"], x={"SetFixed": nx}, y={"SetFixed": ny})
                it = next((i for i in b.items if i["id"] == p["id"]), None)
                if it:
                    d0 = b.deco(it)
                    it["tile"] = (nx, ny, tw, th)
                    it["x"], it["y"] = nx, ny - b.P.BH
                    b.damage(d0, b.deco(it))
                if p.get("trace", 0) > 0:
                    p["trace"] -= 1
                    sm.log("bars: тяну", b.out, "курсор", int(ev.x), int(ev.y), "→", nx, ny)
            return True
        it, zone = self.hit(ev.x, ev.y)
        edge = zone[3:] if zone and zone.startswith("rs:") else None
        self.set_cursor(edge)
        if zone and zone.startswith("rs:"):
            zone = "title"                       # ручка — не кнопка, без подсветки
        h = (it["id"], zone) if it and zone != "title" else None
        if h != self.hover:
            self.hover = h
            self.win.queue_draw()
        return False

    def damage(self, *rects):
        """Перерисовать только там, где окно было и стало (с тенью): весь слой на каждое
        движение мыши — лишняя работа и лишняя передача картинки в niri."""
        m = max(SHADOW.values()) + 2
        x0 = min(r[0] for r in rects) - m
        y0 = min(r[1] for r in rects) - m
        x1 = max(r[0] + r[2] for r in rects) + m
        y1 = max(r[1] + r[3] for r in rects) + m
        self.win.queue_draw_area(x0, y0, x1 - x0, y1 - y0)

    def cross(self, p, ev):
        """Перенос тянущегося окна на соседний монитор стопки, когда курсор туда ушёл.
        Возвращает слой монитора, куда окно только что переехало, иначе None."""
        if p.get("geo") is None:
            outs = sm.get("Outputs") or {}
            p["geo"] = {n: (o["logical"]["x"], o["logical"]["y"], o["logical"]["width"],
                            o["logical"]["height"]) for n, o in outs.items() if o.get("logical")}
        geo = p["geo"]
        if self.out not in geo:
            return None
        sx, sy = geo[self.out][:2]
        gx, gy = sx + ev.x, sy + ev.y            # слой стоит от левого края монитора
        cur = p.get("out", self.out)
        tgt = next((n for n, (x, y, w, h) in geo.items()
                    if x <= gx < x + w and y <= gy < y + h), cur)
        bar = self.mgr.bars.get(tgt)
        desk = sm.so(self.st, tgt).get("desk")
        if tgt == cur or bar is None or desk is None:
            return None
        old = self.mgr.bars.get(cur) or self
        it = next((i for i in old.items if i["id"] == p["id"]), None)
        old.items = [i for i in old.items if i["id"] != p["id"]]
        old.z = [i for i in old.z if i != p["id"]]
        old.win.queue_draw()
        p["out"], p["dx"] = tgt, geo[tgt][0] - sx
        FAST.A("MoveWindowToWorkspace", window_id=p["id"], reference={"Id": desk}, focus=False)
        if it:
            it = dict(it, F=bar.P.F, focused=True)
            bar.items = [i for i in bar.items if i["id"] != p["id"]] + [it]
        bar.z = [i for i in bar.z if i != p["id"]] + [p["id"]]
        bar.raised = p["id"]
        bar.win.queue_draw()
        # FocusWindow здесь нельзя: при смене монитора niri сам ставит курсор в центр
        # экрана (focus_window → move_cursor_to_output), и окно прыгало за ним. Фокус
        # перейдёт по первому щелчку — щелчок niri меняет монитор без прыжка курсора.
        p["trace"] = 4
        sm.log("bars: перенос на монитор", tgt, p["id"], "курсор", int(gx), int(gy), "сдвиг", p["dx"])
        return bar

    @staticmethod
    def trace_end(p):
        w = next((w for w in sm.query()[1] if w["id"] == p["id"]), None)
        sm.log("bars: отпустил", p["id"], "послано", p.get("sent"), "niri:",
               w and w.get("workspace_id"), w and sm.tpos(w))
        return False

    def on_leave(self, *_a):
        if not self.press:
            self.set_cursor(None)
        if self.hover and not self.press:
            self.hover = None
            self.win.queue_draw()

    def on_release(self, _w, ev):
        p, self.press = self.press, None
        if not p:
            return False
        wid = p["id"]
        if p["moved"] and p["zone"].startswith("rs:"):
            self.resize_to(p, ev)
            self.set_cursor(None)
            self.mgr.schedule()
            return True
        if p["moved"]:
            self.set_input()
            if "out" in p:                               # переносили на другой монитор
                GLib.timeout_add(120, self.trace_end, p)
            GLib.timeout_add(60, self.mgr.schedule)      # niri успел встать — перечитать
            return True
        it, zone = self.hit(ev.x, ev.y)
        if p["button"] == 3 and it and it["id"] == wid and not zone.startswith("rs:"):
            # ПКМ по полосе — кнопка; ПКМ ещё раз по той же полосе — убрать
            self.set_offer(None if p.get("had_offer") == wid else wid)
            return True
        if not it or it["id"] != wid or zone != p["zone"]:
            return True
        if p["button"] == 1 and zone == "pin":
            self.set_offer(None)
            self.mgr.toggle_pin(wid, self.out)
        elif p["button"] == 2 and zone == "title":
            self.minimize(wid)
        elif p["button"] == 1 and zone == "close":
            sm.A("CloseWindow", id=wid)
        elif p["button"] == 1 and zone == "max":
            self.toggle_max(wid)
        elif p["button"] == 1 and zone == "min":
            self.minimize(wid)
        self.hover = None
        self.mgr.schedule()
        return True


FS_WAIT = 1.0     # с: окно стопки ушло в ленту — ждать, не полный ли это экран (fs_pending)


class Bars:
    """Общий поток событий niri и порядок на столах; по слою OutBar на каждый монитор стопки."""

    def __init__(self):
        self.st = sm.load_state()
        self.overview = False
        self.handled = {}        # id → время: уже уложено в стопку (без повторов на событиях)
        self.state_mtime = 0
        self.pending = False
        self.buf = b""
        self.bars = {}
        self.pins = {}           # id → {proc, out, sent}: окна «поверх всех», зеркало stack_pin.py
        subprocess.Popen([sys.executable, PIN_HELPER, "--sweep"], stdout=subprocess.DEVNULL)  # хвосты прошлого запуска
        self.sync_outputs()
        self.mon_t = None
        disp = Gdk.Display.get_default()
        disp.connect("monitor-added", self.on_monitors)
        disp.connect("monitor-removed", self.on_monitors)
        self.events()
        GLib.timeout_add(700, self.tick)
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 10, self.dump)     # SIGUSR1
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 12, self.on_req)   # SIGUSR2: свернуть/вернуть
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, 1, lambda: self.on_monitors() or True)  # SIGHUP: как смена мониторов
        self.fs_seen = {}        # id → когда последний раз видели во весь экран (для журнала)
        self.was_float = set()   # id, что лежали плавающими на столе стопки
        self.fs_wait = {}        # id → с какого времени ждём, не полный ли это экран
        self.fs_back = set()     # id, что были во весь экран: вернутся — поставить на место
        self.refresh()

    def dump(self):
        """SIGUSR1: слои как есть → ~/.cache/stack-bars-<монитор>.png и .json."""
        for b in self.bars.values():
            b.dump()
        return True

    def on_req(self):
        """stack_mode.py min|unmin ID (щелчок по кнопке на панели, Alt+Tab) — с полётом."""
        try:
            with open(REQ) as f:
                lines = f.read().split("\n")
            os.unlink(REQ)
        except OSError:
            return True
        for ln in lines:
            cmd, _s, wid = ln.strip().partition(" ")
            if cmd == "desktop":
                self.show_desktop()
                continue
            if not wid.isdigit():
                continue
            w, o = sm.window_out(int(wid))
            b = self.bars.get(o)
            if not w or b is None:
                if w and cmd == "unmin":
                    sm.unminimize(int(wid))
                continue
            if cmd == "min":
                b.minimize(int(wid))
            elif cmd == "unmin":
                b.unminimize(w)
            elif cmd == "max":
                b.toggle_max(int(wid))
        return True

    def show_desktop(self):
        """Super+D в стопке — как в Windows (21.10.2026): все окна столов стопки свернуть с
        полётом; снова Super+D — вернуть их, сверху то, что было сверху. Открыли или
        вернули окно в промежутке — Super+D снова сворачивает всё."""
        st = self.st = sm.load_state()
        shown = [(b, it["id"]) for b in self.bars.values() if b.visible for it in b.items]
        if not shown:
            shown = [(b, it["id"]) for b in self.bars.values() for it in b.items]
        if shown:
            st["desk_hidden"] = [wid for _b, wid in shown]
            sm._save(sm.STATE, st)
            for b, wid in shown:
                b.minimize(wid)
            return
        back = [wid for wid in st.get("desk_hidden") or [] if str(wid) in (st.get("min") or {})]
        st.pop("desk_hidden", None)
        sm._save(sm.STATE, st)
        wss, wins = sm.query()
        for wid in back:                         # снизу вверх: последнее окажется сверху и в фокусе
            w, o = sm.window_out(wid, wss, wins)
            b = self.bars.get(o)
            if w and b is not None:
                b.unminimize(w)
            elif w:
                sm.unminimize(wid)

    # — поверх всех —
    def toggle_pin(self, wid, out):
        if wid in self.pins:
            self.unpin(wid, "открепил")
        else:
            self.pin(wid, out)
        self.schedule()

    def pin(self, wid, out):
        try:
            proc = subprocess.Popen([sys.executable, PIN_HELPER, str(wid), out], stdin=subprocess.PIPE,
                                    text=True)
        except OSError as e:
            sm.log("bars: поверх всех — не запустилось", wid, e)
            return
        self.pins[wid] = {"proc": proc, "out": out, "sent": None}
        sm.log("bars: поверх всех", out, wid, "зеркало", proc.pid)

    def unpin(self, wid, why):
        d = self.pins.pop(wid, None)
        if d is None:
            return
        sm.log("bars: поверх всех — снято", wid, why)
        proc = d["proc"]
        try:
            proc.stdin.write("quit\n")
            proc.stdin.close()
        except (OSError, ValueError):
            pass

        def reap():
            if proc.poll() is None:
                proc.kill()
                proc.wait()
                subprocess.Popen([sys.executable, PIN_HELPER, "--sweep"], stdout=subprocess.DEVNULL)
            return False
        GLib.timeout_add(1500, reap)

    def sync_pins(self, wins):
        """Зеркалу — где окно, или спрятаться: окно в фокусе (niri и так поднял его),
        стол не виден, обзор, свёрнуто. Окно закрыли или зеркало упало — снять."""
        live = {w["id"] for w in wins}
        for wid in list(self.pins):
            d = self.pins[wid]
            if wid not in live or d["proc"].poll() is not None:
                self.unpin(wid, "окно закрыто" if wid not in live else "зеркало закончилось")
                continue
            b, it = next(((b, i) for b in self.bars.values() for i in b.items if i["id"] == wid),
                         (None, None))
            if b is not None and b.out != d["out"]:
                self.unpin(wid, "переехало на " + b.out)
                self.pin(wid, b.out)
                d = self.pins.get(wid)
                if d is None:
                    continue
            cmd = "hide" if b is None or not b.visible or it["focused"] else "show %d %d %d %d" % it["win"]
            if cmd != d["sent"]:
                try:
                    d["proc"].stdin.write(cmd + "\n")
                    d["proc"].stdin.flush()
                    d["sent"] = cmd
                except (OSError, ValueError):
                    self.unpin(wid, "зеркало не отвечает")

    # — мониторы —
    def monitor(self, out):
        """Монитор GDK для выхода niri: по модели, при совпадении/без неё — по месту."""
        o = (sm.get("Outputs") or {}).get(out) or {}
        model = o.get("model") or ""
        lg = o.get("logical") or {}
        disp = Gdk.Display.get_default()
        mons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())]
        same = [m for m in mons if model and (m.get_model() or "") == model]
        if len(same) == 1:
            return same[0]
        for m in same or mons:
            g = m.get_geometry()
            if (g.x, g.y) == (lg.get("x"), lg.get("y")):
                return m
        return None

    def on_monitors(self, *_a):
        """Монитор отключился/подключился (26.10.2026: мигнул свет, MSI пропал на 5 с — слои
        остались на старом GdkMonitor, niri закрывал каждую новую полосу «no output for new
        layer surface», рамки окон пропали; Просьба: «Сделай чтобы такое не повторялось»).
        Через 2 с после последней смены демон перезапускает себя тем же pid — как ручной
        перезапуск; зеркала «поверх всех» снимает --sweep нового запуска."""
        if self.mon_t:
            GLib.source_remove(self.mon_t)
        self.mon_t = GLib.timeout_add(2000, self.reexec)

    def reexec(self):
        self.mon_t = None
        sm.log("bars: мониторы сменились — перезапуск демона")
        try:
            self.sock.close()
        except OSError:
            pass
        sys.stdout.flush()
        sys.stderr.flush()
        os.execv(sys.executable, [sys.executable, os.path.join(HERE, "stack_mode.py"), "daemon"])
        return False

    def sync_outputs(self):
        """Слой на каждый монитор из st["outs"]; монитор отключили — слой убрать."""
        want = set((self.st.get("outs") or {}))
        for out in list(self.bars):
            if out not in want:
                self.bars.pop(out).win.destroy()
        for out in sorted(want - set(self.bars)):
            mon = self.monitor(out)
            if mon is None:
                sm.log("bars: монитор", out, "не найден в GDK")
                continue
            self.bars[out] = OutBar(self, out, mon)

    # — niri —
    def events(self):
        s = self.sock = socket.socket(socket.AF_UNIX)
        s.connect(sm.sock_path())
        s.sendall(b'"EventStream"\n')
        s.setblocking(False)
        GLib.io_add_watch(s.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                          self.on_event)

    def on_event(self, _fd, cond):
        if cond & (GLib.IO_HUP | GLib.IO_ERR):
            sm.log("bars: поток событий niri закрыт")
            Gtk.main_quit()
            return False
        try:
            chunk = self.sock.recv(65536)
        except BlockingIOError:
            return True
        if not chunk:
            Gtk.main_quit()
            return False
        self.buf += chunk
        *lines, self.buf = self.buf.split(b"\n")
        for ln in lines:
            if not ln.strip():
                continue
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            if "OverviewOpenedOrClosed" in ev:
                self.overview = bool(ev["OverviewOpenedOrClosed"].get("is_open"))
                # обзор в стопке показал бы стол свёрнутых и дал таскать окна по столам;
                # Super+G молчит (nostack), а горячий угол и жест тачпада — мимо биндов
                # (21.10.2026, «Делай тоже»)
                if self.overview:
                    sm.log("bars: обзор в стопке — закрываю")
                    sm.A("CloseOverview")
            if "KeyboardLayoutSwitched" in ev or "KeyboardLayoutsChanged" in ev:
                continue
            fid = (ev.get("WindowFocusChanged") or {}).get("id")
            if fid is not None:
                for b in self.bars.values():
                    b.fs_focus(fid)
            self.schedule()
        return True

    def schedule(self):
        if not self.pending:
            self.pending = True
            GLib.timeout_add(12, self.refresh)

    def tick(self):
        try:
            mt = os.stat(sm.STATE).st_mtime
        except OSError:
            mt = 0
        if mt != self.state_mtime:
            self.state_mtime = mt
            self.st = sm.load_state()
            if not sm.active(self.st):
                sm.log("bars: стопка выключена — выхожу")
                Gtk.main_quit()
                return False
            self.sync_outputs()
            self.schedule()
        changed = False
        for out, b in self.bars.items():
            changed |= b.set_style(sm.style(out))
        if changed:
            self.schedule()
        return True

    # — порядок на столах —
    def enforce(self, wss, wins):
        """Окна каждого монитора, и из кармана, — на его стол стопки, плавающими; фокус на
        свёрнутом — вернуть."""
        outs = self.st.get("outs") or {}
        dout = sm.desk_out(wss)
        mins = {d["id"] for d in wss if sm.is_min_name(d.get("name"))}
        now = time.monotonic()
        nfl = {}
        for w in wins:
            ws = w.get("workspace_id")
            o = dout.get(ws)
            if o in outs and ws == outs[o]["desk"] and w.get("is_floating"):
                nfl[o] = nfl.get(o, 0) + 1
        live = {w["id"] for w in wins}
        self.was_float &= live
        for k in [k for k in self.fs_wait if k not in live]:
            del self.fs_wait[k]
        moved = False
        for w in wins:
            ws = w.get("workspace_id")
            o = dout.get(ws)
            if o not in outs or sm.hidden(w):
                continue
            if ws in mins:
                if w.get("is_focused"):
                    sm.unminimize(w["id"])
                    moved = True
                continue
            if self.fullscreen_to_max(w, o):         # видео, игра — с любого стола, как есть
                self.fs_wait.pop(w["id"], None)
                self.was_float.discard(w["id"])      # выход из полного экрана — в стопку сразу
                self.fs_back.add(w["id"])
                continue
            if ws == outs[o]["desk"] and w.get("is_floating"):
                self.was_float.add(w["id"])
                self.fs_wait.pop(w["id"], None)
                if w["id"] in self.fs_back:
                    self.fs_back.discard(w["id"])
                    moved = self.back_from_fs(w, o) or moved
                continue
            if ws == outs[o]["desk"] and self.fs_pending(w):
                continue
            if now - self.handled.get(w["id"], 0) < 1.5:
                continue
            self.handled[w["id"]] = now
            sm.log("bars: в стопку", o, w.get("app_id"), w["id"], "со стола", ws)
            sm.float_into_stack(w, self.st, sm.load_geom(), nfl.get(o, 0), o, avoid=True)
            nfl[o] = nfl.get(o, 0) + 1
            if w.get("is_focused"):
                sm.A("FocusWindow", id=w["id"])
            moved = True
        return moved

    def back_from_fs(self, w, o):
        """Из полного экрана niri возвращает окно в плавающий размер по своей памяти — у
        развёрнутого кнопкой стопки это прежний, неразвёрнутый (21.10.2026: Zen после видео
        стал 1216×633, а полоса считала его развёрнутым). Развёрнутое — снова под полосу."""
        if str(w["id"]) not in (self.st.get("max") or {}):
            return False
        r = sm.max_rect(self.st, o, w)
        p = sm.tpos(w)
        sz = sm.wsize(w)
        if p and abs(sz[0] - r[2]) <= 1 and abs(sz[1] - r[3]) <= 1:
            return False
        sm.log("bars: из полного экрана — снова развёрнуто", o, w.get("app_id"), w["id"])
        sm.place(w["id"], *r)
        return True

    def fs_pending(self, w):
        """Плавающее окно стопки попросило полный экран: niri сразу уносит его в ленту, а размер
        экрана окно получает позже, следующим кадром. Вернуть его в стопку в этот миг — сбить
        полный экран: видео «делало вид, что раскрывается», раскрывалось только со второго F
        (21.10.2026). Поэтому до FS_WAIT с ждём; не дорос до экрана — уложить, как обычно.
        Выход из полного экрана сюда не попадает (fullscreen_to_max снимает отметку). True — ждём."""
        if w["id"] not in self.was_float:
            return False
        now = time.monotonic()
        t0 = self.fs_wait.setdefault(w["id"], now)
        if now - t0 < FS_WAIT:
            GLib.timeout_add(250, lambda: self.schedule() and False)
            return True
        self.fs_wait.pop(w["id"], None)
        self.was_float.discard(w["id"])
        return False

    def fullscreen_to_max(self, w, o):
        """Окно во весь экран niri — не трогать: ни в стопку, ни обратно в окно. True — оно такое.
        Видео в браузере просит полный экран само; раньше демон снимал его и разворачивал окно,
        браузер просил снова — окно мигало по кругу, каждые 2–4 с (21.10.2026, просьба: «багуется
        система, когда я открываю видео в браузере на весь экран»). Super+F и «Во весь экран» в
        меню панели в стопке и так идут через «Развернуть» (stack_mode.py key fs / max), сюда
        доходит только то, что попросила сама программа. Полный экран niri переносит окно из
        плавающих в ленту, выход возвращает его плавающим; если нет — enforce вернёт в стопку."""
        size = self.out_size.get(o)
        if not size or w.get("is_floating") or sm.wsize(w) != list(size):
            return False
        now = time.monotonic()
        if now - self.fs_seen.get(w["id"], -9) > 3:
            sm.log("bars: во весь экран — оставить", o, w.get("app_id"), w["id"])
        self.fs_seen[w["id"]] = now
        return True

    def refresh(self):
        self.pending = False
        if any(b.press and b.press.get("moved") for b in self.bars.values()):
            return False                             # тянут: место знаем сами, niri не дёргать
        self.st = sm.load_state()
        wss, wins = sm.query()
        if not wss or not sm.active(self.st):
            return False
        if sm.heal(self.st, wss, wins):
            wss, wins = sm.query()
        self.out_size = getattr(self, "out_size", {})
        for o in self.st.get("outs") or {}:
            if o not in self.out_size:
                self.out_size[o] = sm.output_size(o)
        pressing = any(b.press is not None for b in self.bars.values())
        if not pressing and self.enforce(wss, wins):
            wss, wins = sm.query()
        for b in self.bars.values():
            b.update(wss, wins)
        self.sync_pins(wins)
        return False


def shot(path, style):
    """Макет: три окна стопкой на 900×420, верхнее в фокусе и с наведением на «закрыть»."""
    P = Painter(style)
    W, H = 900, 420
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0.18, 0.2, 0.24)
    cr.paint()
    # окно 1 закреплено поверх всех, у окна 3 — кнопка «Поверх всех» (ПКМ по полосе)
    wins = [(1, "kitty", "~ btop", 30, 60, 520, 220, False, False),
            (2, "org.gnome.Nautilus", "Загрузки — очень длинное имя папки, которое не влезает", 260, 130, 360, 200,
             False, True),
            (3, "zen", "YouTube — Zen Browser", 420, 200, 450, 200, True, False)]
    hover = None
    for wid, app, title, x, y, w, h, foc, maxed in wins:
        F = P.F
        cr.set_operator(cairo.OPERATOR_OVER)
        P.shadow(cr, x - F, y - P.BH - F, w + 2 * F, h + P.BH + 2 * F, SHADOW[foc])
        P.fill(cr, x, y, w, h, (0.06, 0.07, 0.09))
        it = {"id": wid, "app_id": app, "title": title, "x": x, "y": y - P.BH, "w": w,
              "focused": foc, "maxed": maxed, "F": F, "pinned": wid == 1}
        P.frame(cr, x - F, y - P.BH - F, w + 2 * F, h + P.BH + 2 * F, foc)
        if foc:
            hover = (wid, "close")
        P.bar(cr, it, hover, offer=wid == 3)
    surf.write_to_png(path)
    print(path)


def run():
    if not sm.active():
        sm.log("bars: стопка не включена")
        return 1
    if os.environ.get("WAYLAND_DISPLAY") is None:
        os.environ["WAYLAND_DISPLAY"] = "wayland-1"
    sm.log("bars: старт", os.getpid())
    Bars()
    Gtk.main()
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        shot(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else sm.style("eDP-1"))
    else:
        sys.exit(run())
