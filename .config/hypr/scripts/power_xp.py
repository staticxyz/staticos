#!/usr/bin/env python3
"""«Выключить компьютер» в духе Windows XP — кнопка «Питание» в «Пуске». 03.10.2026.

    power_xp.py          показать окно (второй запуск при открытом — закрыть)

пользователь прислал снимок XP-диалога: экран тускнеет, посередине окно с синей шапкой
«Выключить компьютер» и тремя большими кнопками, внизу «Отмена». У нас кнопки —
Выход, Выключение, Перезагрузка (Блокировка, Заставка и Сон стоят в подвале «Пуска»).
Действие уходит в power_menu.py --only КЛЮЧ — с его отсчётом и отменой, как у
остальных кнопок питания: щелчок мимо не гасит машину сразу.

Цвета — палитра обоев (popup_theme.palette): шапка — тёмный и светлый тон акцента,
«Выключение» — error, «Перезагрузка» — tertiary, «Выход» — secondary.
Клавиши: ←/→ (и h/l), Enter, Esc; В/Ы/П по первой букве. Щелчок мимо окна — отмена.
"""
import math
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
PIDFILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-power-xp.pid")

# второй запуск — закрыть открытое
try:
    old = int(open(PIDFILE).read().strip())
    if b"power_xp.py" in open("/proc/%d/cmdline" % old, "rb").read():
        os.kill(old, signal.SIGTERM)
        sys.exit(0)
except (OSError, ValueError):
    pass

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

import popup_theme  # noqa: E402

FONT = "PxPlus HP 100LX 6x8 Jarvis"
NERD = "Symbols Nerd Font"
W, H = 640, 300               # окно
HEAD = 58                     # шапка
FOOT = 52                     # полоса с «Отменой»
BTN = 60                      # квадрат кнопки
ITEMS = [("logout", "Выход", "\U000f0343", "secondary", "в"),
         ("shutdown", "Выключение", "\U000f0425", "error", "ы"),
         ("reboot", "Перезагрузка", "\U000f0709", "tertiary", "п")]


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def rrect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def text(cr, s, x, y, size, color, font=FONT, center=False):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(Pango.FontDescription("%s %dpx" % (font, size)))
    lay.set_text(s, -1)
    w, h = lay.get_pixel_size()
    cr.set_source_rgb(*color)
    cr.move_to(x - (w / 2 if center else 0), y)
    PangoCairo.show_layout(cr, lay)
    return w, h


class Shade(Gtk.Window):
    """Слой на монитор: тусклый экран; на мониторе в фокусе — само окно."""

    def __init__(self, app, monitor, main):
        super().__init__()
        self.app, self.main = app, main
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-power-xp")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE if main
                                        else GtkLayerShell.KeyboardMode.NONE)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                        | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.KEY_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-release-event", self.on_click)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("key-press-event", self.app.on_key)

    def box(self):
        a = self.get_allocation()
        return (a.width - W) // 2, (a.height - H) // 2

    def zones(self):
        x0, y0 = self.box()
        gap = (W - 3 * BTN) // 4
        out = [(x0 + gap + i * (BTN + gap), y0 + HEAD + 34, BTN, BTN) for i in range(3)]
        cancel = (x0 + W - 98, y0 + H - FOOT + 12, 84, 28)
        return out, cancel

    def hit(self, x, y):
        btns, cancel = self.zones()
        for i, (bx, by, bw, bh) in enumerate(btns):
            if bx - 20 <= x < bx + bw + 20 and by <= y < by + bh + 30:
                return i
        cx, cy, cw, ch = cancel
        if cx <= x < cx + cw and cy <= y < cy + ch:
            return "cancel"
        x0, y0 = self.box()
        if x0 <= x < x0 + W and y0 <= y < y0 + H:
            return "inside"
        return None

    def on_motion(self, _w, ev):
        if self.main:
            h = self.hit(ev.x, ev.y)
            hov = h if isinstance(h, int) or h == "cancel" else None
            if hov != self.app.hover:
                self.app.hover = hov
                if isinstance(hov, int):
                    self.app.sel = hov
                self.queue_draw()
        return False

    def on_click(self, _w, ev):
        h = self.hit(ev.x, ev.y) if self.main else None
        if isinstance(h, int):
            self.app.run(h)
        elif h != "inside":
            self.app.quit()
        return True

    def on_draw(self, _w, cr):
        p = self.app.pal
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0.55 * self.app.fade)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if not self.main:
            return True
        cr.push_group()
        x0, y0 = self.box()
        acc, surf = rgb(p["primary"]), rgb(p["surface"])
        dark = mix(acc, (0, 0, 0), 0.62)
        # тень и корпус
        cr.set_source_rgba(0, 0, 0, 0.45)
        rrect(cr, x0 + 6, y0 + 7, W, H, 8)
        cr.fill()
        # шапка — градиент тёмного акцента, как синяя шапка XP
        g = cairo.LinearGradient(0, y0, 0, y0 + HEAD)
        g.add_color_stop_rgb(0, *mix(acc, (1, 1, 1), 0.10))
        g.add_color_stop_rgb(0.15, *mix(acc, dark, 0.35))
        g.add_color_stop_rgb(1, *dark)
        rrect(cr, x0, y0, W, H, 8)
        cr.set_source(g)
        cr.fill()
        # тело — светлее шапки, с мягким переходом сверху
        body = mix(acc, surf, 0.55)
        g = cairo.LinearGradient(0, y0 + HEAD, 0, y0 + H - FOOT)
        g.add_color_stop_rgb(0, *mix(body, (1, 1, 1), 0.10))
        g.add_color_stop_rgb(1, *body)
        cr.rectangle(x0, y0 + HEAD, W, H - HEAD - FOOT)
        cr.set_source(g)
        cr.fill()
        # полоса с «Отменой» — снова тёмная, как в XP
        cr.save()
        rrect(cr, x0, y0, W, H, 8)
        cr.clip()
        cr.rectangle(x0, y0 + H - FOOT, W, FOOT)
        cr.set_source_rgb(*dark)
        cr.fill()
        cr.restore()
        cr.set_source_rgba(1, 1, 1, 0.18)
        cr.rectangle(x0, y0 + HEAD, W, 1)
        cr.fill()
        # рамка
        rrect(cr, x0 + 0.5, y0 + 0.5, W - 1, H - 1, 8)
        cr.set_source_rgba(*mix(acc, (1, 1, 1), 0.35), 0.9)
        cr.set_line_width(1)
        cr.stroke()
        # заголовок и значок Arch Linux (вместо «флага» из тонов палитры — просьба пользователя)
        text(cr, "Выключить компьютер", x0 + 22, y0 + 20, 16, (1, 1, 1))
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription("%s 30px" % NERD))
        lay.set_text("\uf303", -1)
        gw, gh = lay.get_pixel_size()
        gx, gy = x0 + W - 26 - gw, y0 + (HEAD - gh) / 2
        cr.move_to(gx + 1, gy + 1)
        cr.set_source_rgba(0, 0, 0, 0.35)                 # лёгкая тень, как у значков XP
        PangoCairo.show_layout(cr, lay)
        g = cairo.LinearGradient(0, gy, 0, gy + gh)
        g.add_color_stop_rgb(0, *mix(acc, (1, 1, 1), 0.65))
        g.add_color_stop_rgb(1, *mix(acc, (1, 1, 1), 0.15))
        cr.move_to(gx, gy)
        PangoCairo.layout_path(cr, lay)
        cr.set_source(g)
        cr.fill()
        # кнопки
        btns, cancel = self.zones()
        for i, (bx, by, bw, bh) in enumerate(btns):
            _k, label, glyph, ckey, _l = ITEMS[i]
            c = rgb(p[ckey])
            on = i == self.app.sel
            if on:
                # подсветка — по ширине подписи и ровно по центру кнопки (была уже подписи
                # и съезжала — «рамка немножко кривая», 03.10.2026)
                # одна ширина на все кнопки — по самой длинной подписи («размеры должны
                # быть одинаковые»)
                lay = PangoCairo.create_layout(cr)
                lay.set_font_description(Pango.FontDescription("%s 16px" % FONT))
                widest = 0
                for it in ITEMS:
                    lay.set_text(it[1], -1)
                    widest = max(widest, lay.get_pixel_size()[0])
                hw = max(bw, widest) + 24
                hx = round(bx + bw / 2 - hw / 2)
                cr.set_source_rgba(1, 1, 1, 0.16)
                rrect(cr, hx, by - 10, hw, bh + 46, 6)
                cr.fill()
            g = cairo.LinearGradient(0, by, 0, by + bh)
            g.add_color_stop_rgb(0, *mix(c, (1, 1, 1), 0.45))
            g.add_color_stop_rgb(0.45, *c)
            g.add_color_stop_rgb(1, *mix(c, (0, 0, 0), 0.35))
            rrect(cr, bx, by, bw, bh, 7)
            cr.set_source(g)
            cr.fill_preserve()
            cr.set_source_rgba(1, 1, 1, 0.55 if on else 0.3)
            cr.set_line_width(1.5)
            cr.stroke()
            text(cr, glyph, bx + bw / 2, by + 9, 30, (1, 1, 1), font=NERD, center=True)
            text(cr, label, round(bx + bw / 2), by + bh + 10, 16, (1, 1, 1) if on else (0.92, 0.94, 1), center=True)
        # «Отмена»
        cx, cy, cw, ch = cancel
        hov = self.app.hover == "cancel"
        g = cairo.LinearGradient(0, cy, 0, cy + ch)
        g.add_color_stop_rgb(0, 1, 1, 1)
        g.add_color_stop_rgb(1, *mix((1, 1, 1), acc, 0.25 if hov else 0.12))
        rrect(cr, cx, cy, cw, ch, 3)
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_source_rgb(*dark)
        cr.set_line_width(1)
        cr.stroke()
        text(cr, "Отмена", cx + cw / 2, cy + 6, 16, mix(dark, (0, 0, 0), 0.4), center=True)
        cr.pop_group_to_source()
        cr.paint_with_alpha(self.app.fade)
        return True


class App:
    def __init__(self):
        try:
            self.pal = popup_theme.palette()
        except Exception:
            self.pal = {"primary": "#7aa2f7", "surface": "#1a1b26", "error": "#f7768e",
                        "secondary": "#9aa5ce", "tertiary": "#9ece6a"}
        self.sel, self.hover, self.fade = 1, None, 0.0
        d = Gdk.Display.get_default()
        focus = self.focused_monitor(d)
        self.wins = []
        for i in range(d.get_n_monitors()):
            m = d.get_monitor(i)
            w = Shade(self, m, m == focus)
            w.show_all()
            self.wins.append(w)
        GLib.timeout_add(16, self.fade_in)

    @staticmethod
    def focused_monitor(d):
        try:
            mon = popup_theme.pointer_monitor()
            if mon is not None:
                return mon
        except Exception:
            pass
        return d.get_monitor(0)

    def fade_in(self):
        self.fade = min(1.0, self.fade + 0.12)
        for w in self.wins:
            w.queue_draw()
        return self.fade < 1.0

    def on_key(self, _w, ev):
        k = Gdk.keyval_name(ev.keyval) or ""
        ch = chr(Gdk.keyval_to_unicode(ev.keyval) or 0).lower()
        if k == "Escape":
            self.quit()
        elif k in ("Left", "h", "Cyrillic_er") or (k == "Tab" and ev.state & Gdk.ModifierType.SHIFT_MASK):
            self.sel = (self.sel - 1) % 3
        elif k in ("Right", "l", "Cyrillic_de", "Tab", "ISO_Left_Tab"):
            self.sel = (self.sel + 1) % 3 if k != "ISO_Left_Tab" else (self.sel - 1) % 3
        elif k in ("Return", "KP_Enter", "space"):
            self.run(self.sel)
            return True
        else:
            for i, item in enumerate(ITEMS):
                if ch == item[4]:
                    self.run(i)
                    return True
        for w in self.wins:
            w.queue_draw()
        return True

    def run(self, i):
        key = ITEMS[i][0]
        try:
            import ui_sound
            ui_sound.play("click")
        except Exception:
            pass
        subprocess.Popen([sys.executable, os.path.join(HERE, "power_menu.py"), "--only", key],
                         start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.quit()

    def quit(self, *_a):
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        os._exit(0)


def main():
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
    app = App()
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    Gtk.main()


if __name__ == "__main__":
    main()
