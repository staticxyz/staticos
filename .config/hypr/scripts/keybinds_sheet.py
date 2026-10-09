#!/usr/bin/env python3
"""Шпаргалка клавиш — стиль системы, vim-навигация, поиск.

Super+X: j/k прокрутка, / поиск, q/Esc закрыть, g/G в начало/конец.
Тема и цвета — из обоев (palette + settings-skin).
"""
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo
import cairo

APP_ID = "com.jarvis.keybinds"
W, H_MIN = 480, 560
ROW_H = 22
PAD = 16

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "

BINDS_KDL = os.path.expanduser("~/.config/niri/cfg/binds.kdl")

# ── палитра (из app_launcher) ────────────────────────────────────────────────
from app_launcher import palette, colors, style_name, hexrgb, mix, read

# ── разбор биндов ────────────────────────────────────────────────────────────

RE_BIND = re.compile(
    r'^\s*(\S+)\s+(?:.*?hotkey-overlay-title="([^"]*)")?\s*\{',
    re.MULTILINE
)

PRETTY = {
    "Mod": "Super", "Ctrl": "Ctrl", "Shift": "Shift", "Alt": "Alt",
}

def pretty_key(raw):
    parts = raw.replace("+", " + ").split(" + ")
    out = []
    for p in parts:
        p = p.strip()
        out.append(PRETTY.get(p, p))
    return " + ".join(out)

def load_binds():
    try:
        text = open(BINDS_KDL).read()
    except OSError:
        return []
    result = []
    for m in RE_BIND.finditer(text):
        key, title = m.group(1), m.group(2)
        if not title:
            continue
        result.append((pretty_key(key), title))
    cats = {}
    for key, title in result:
        if "терминал" in title.lower():
            cat = "Терминал"
        elif "браузер" in title.lower() or "helium" in title.lower() or "zen" in title.lower() or "tor" in title.lower() or "libre" in title.lower():
            cat = "Браузеры"
        elif "снимок" in title.lower() or "запись" in title.lower() or "gif" in title.lower() or "стикер" in title.lower():
            cat = "Снимки и запись"
        elif "помидор" in title.lower() or "фокус" in title.lower():
            cat = "Фокус"
        elif "hub" in title.lower() or "напомин" in title.lower() or "словарь" in title.lower():
            cat = "Hub"
        elif "настрой" in title.lower() or "noctalia" in title.lower() or "обо" in title.lower() or "стиль" in title.lower():
            cat = "Настройки и вид"
        elif "окно" in title.lower() or "стол" in title.lower() or "монитор" in title.lower() or "плавающ" in title.lower() or "колон" in title.lower() or "полноэкранн" in title.lower():
            cat = "Окна и столы"
        else:
            cat = "Другое"
        cats.setdefault(cat, []).append((key, title))
    order = ["Терминал", "Браузеры", "Hub", "Фокус", "Снимки и запись", "Настройки и вид", "Окна и столы", "Другое"]
    rows = []
    for c in order:
        if c in cats:
            rows.append(("head", c))
            for k, t in cats[c]:
                rows.append(("bind", k, t))
    for c in cats:
        if c not in order:
            rows.append(("head", c))
            for k, t in cats[c]:
                rows.append(("bind", k, t))
    return rows

# ── рисовалка ────────────────────────────────────────────────────────────────

class Painter:
    def __init__(self, cr, c):
        self.cr, self.c = cr, c

    def rgb(self, color):
        self.cr.set_source_rgb(*color)

    def rect(self, x, y, w, h, color):
        self.cr.rectangle(x, y, w, h)
        self.rgb(color)
        self.cr.fill()

    def round(self, x, y, w, h, r):
        import math
        cr = self.cr
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def text(self, x, y, text, color, size=12, align="l", maxw=0, bold=False):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription("PxPlus HP 100LX 6x8 %dpx" % size)
        if bold:
            fd.set_weight(Pango.Weight.BOLD)
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        if maxw > 0:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        w = lay.get_pixel_size()[0]
        if align == "c":
            x -= w / 2
        elif align == "r":
            x -= w
        self.cr.move_to(x, y)
        self.rgb(color)
        PangoCairo.show_layout(self.cr, lay)
        return w

    def text_w(self, text, size=12):
        lay = PangoCairo.create_layout(self.cr)
        lay.set_font_description(Pango.FontDescription("PxPlus HP 100LX 6x8 %dpx" % size))
        lay.set_text(text, -1)
        return lay.get_pixel_size()[0]


class View:
    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.all_rows = load_binds()
        self.mode = "normal"
        self.buf = ""
        self.sel = 0
        self.scroll = 0
        self.pending_jj = False
        self.pending_t = 0

    def rows(self):
        if not self.buf:
            return self.all_rows
        q = self.buf.lower()
        out = []
        for r in self.all_rows:
            if r[0] == "head":
                continue
            if q in r[1].lower() or q in r[2].lower():
                out.append(r)
        return out

    def draw(self, cr, w, h):
        c = self.c
        p = Painter(cr, c)
        if c["frame"] == "skeet":
            p.rect(0, 0, w, h, c.get("line3", c["bg"]))
            p.rect(2, 2, w - 4, h - 4, c["line"])
            p.rect(4, 4, w - 8, h - 8, c["bg"])
        else:
            p.round(0.5, 0.5, w - 1, h - 1, 10)
            p.rgb(c["bg"])
            cr.fill_preserve()
            p.rgb(c["line"])
            cr.set_line_width(1)
            cr.stroke()

        x0, x1 = PAD, w - PAD
        y = 12
        p.text(x0, y, "Клавиши", c["acc_l"], size=12, bold=True)
        y += 22

        # поиск
        p.rect(x0, y, x1 - x0, 20, c["field"])
        if self.mode == "search":
            p.text(x0 + 4, y + 3, self.buf + "▏", c["text"], maxw=x1 - x0 - 8)
        elif self.buf:
            p.text(x0 + 4, y + 3, self.buf, c["text"], maxw=x1 - x0 - 8)
        else:
            p.text(x0 + 4, y + 3, "Поиск…  /", c["faint"], maxw=x1 - x0 - 8)
        y += 26

        rows = self.rows()
        if not rows:
            p.text(x0, y, "Ничего не найдено.", c["faint"])
            self.draw_footer(p, x0, x1, h - 20, w)
            return

        avail = h - y - 28
        max_vis = avail // ROW_H
        sel = max(0, min(self.sel, len(rows) - 1))
        self.sel = sel

        off = self.scroll
        if sel < off:
            off = sel
        if sel >= off + max_vis:
            off = sel - max_vis + 1
        off = max(0, min(off, len(rows) - max_vis))
        self.scroll = off

        cr.save()
        cr.rectangle(x0 - 2, y, x1 - x0 + 4, avail)
        cr.clip()

        key_w = 160
        for i in range(off, min(off + max_vis + 1, len(rows))):
            ry = y + (i - off) * ROW_H
            if ry > y + avail:
                break
            is_sel = i == sel
            row = rows[i]
            if row[0] == "head":
                p.rect(x0, ry + ROW_H - 1, x1 - x0, 1, c["line_soft"])
                p.text(x0 + 2, ry + 5, row[1], c["acc_l"], bold=True)
            else:
                if is_sel:
                    p.rect(x0 - 2, ry, x1 - x0 + 4, ROW_H, c["sel"])
                p.text(x0 + 8, ry + 4, row[1], c["acc_l"] if is_sel else c["dim"], maxw=key_w - 12)
                p.text(x0 + key_w, ry + 4, row[2], c["text"] if is_sel else c["dim"], maxw=x1 - x0 - key_w - 4)

        cr.restore()

        if len(rows) > max_vis:
            bar_h = max(12, avail * max_vis / len(rows))
            bar_y = y + (avail - bar_h) * off / max(1, len(rows) - max_vis)
            p.rect(x1 - 2, bar_y, 2, bar_h, c["faint"])

        self.draw_footer(p, x0, x1, h - 20, w)

    def draw_footer(self, p, x0, x1, y, w):
        c = self.c
        p.rect(x0, y - 4, x1 - x0, 1, c["line_soft"])
        badge = "SEARCH" if self.mode == "search" else "NORMAL"
        bw = p.text_w(badge) + 10
        p.rect(x0, y, bw, 16, c["field_l"])
        p.text(x0 + 5, y + 1, badge, c["acc_l"])
        hint = "j/k ↕ · g/G начало/конец · / поиск · q закрыть" if self.mode == "normal" \
            else "Enter — открыть · jj/Ctrl+E — навигация · Esc"
        p.text(x0 + bw + 8, y + 1, hint, c["faint"], maxw=x1 - x0 - bw - 10)


class SheetWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Keybinds")
        self.view = View()
        self.set_decorated(False)
        self.set_default_size(W, H_MIN)
        self.set_resizable(False)
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK)
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("focus-out-event", lambda *_: self.close())

    def redraw(self):
        self.area.queue_draw()

    def on_draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        self.view.draw(cr, w, h)

    def on_scroll(self, _w, ev):
        v = self.view
        if ev.direction == Gdk.ScrollDirection.UP:
            v.sel = max(0, v.sel - 3)
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            v.sel = min(len(v.rows()) - 1, v.sel + 3)
        self.redraw()
        return True

    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""

        if ctrl and ch == "e":
            v.mode = "normal" if v.mode == "search" else "search"
            self.redraw()
            return True

        if v.mode == "search":
            self.key_search(ch, name, ev)
        else:
            self.key_normal(ch, name, shift)
        self.redraw()
        return True

    def key_search(self, ch, name, ev):
        v = self.view
        import time
        now = time.monotonic()
        if name == "Escape":
            if v.buf:
                v.buf = ""
            else:
                self.close()
        elif name in ("Return", "KP_Enter"):
            v.mode = "normal"
        elif name == "BackSpace":
            v.buf = v.buf[:-1]
            v.sel = 0
        elif ch == "j":
            if now - v.pending_t < 0.4 and v.pending_jj:
                v.buf = v.buf[:-1]
                v.mode = "normal"
                v.pending_jj = False
                return
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 80 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0
            v.pending_t = now
            v.pending_jj = True
        else:
            v.pending_jj = False
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 80 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0

    def key_normal(self, ch, name, shift):
        v = self.view
        rows = v.rows()
        if name == "Escape" or ch == "q":
            self.close()
        elif ch == "j":
            v.sel = min(len(rows) - 1, v.sel + 1)
            while v.sel < len(rows) - 1 and rows[v.sel][0] == "head":
                v.sel += 1
        elif ch == "k":
            v.sel = max(0, v.sel - 1)
            while v.sel > 0 and rows[v.sel][0] == "head":
                v.sel -= 1
        elif ch == "g" and not shift:
            v.sel = 0
        elif ch == "g" and shift:
            v.sel = len(rows) - 1
        elif ch == "/":
            v.mode = "search"


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win is not None:
            self.win.present()
            return
        self.win = SheetWindow(self)
        self.win.connect("destroy", lambda *_: setattr(self, "win", None))
        self.win.show_all()
        self.win.present()


def shot(path, style=None):
    v = View()
    if style:
        v.style, v.c = style, colors(style)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H_MIN)
    cr = cairo.Context(surf)
    v.draw(cr, W, H_MIN)
    surf.write_to_png(path)


def check():
    v = View()
    rows = v.rows()
    binds = [r for r in rows if r[0] == "bind"]
    heads = [r for r in rows if r[0] == "head"]
    print("check: %d биндов, %d категорий" % (len(binds), len(heads)))
    assert binds, "нет биндов"


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        p = sys.argv[sys.argv.index("--shot") + 1] if sys.argv.index("--shot") + 1 < len(sys.argv) else "/tmp/keybinds.png"
        style = None
        for a in sys.argv:
            if a.startswith("style="):
                style = a.split("=", 1)[1]
        shot(p, style=style)
        print("saved", p)
    else:
        App().run([])
