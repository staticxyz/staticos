#!/usr/bin/env python3
"""hub_app — окно напоминаний и словаря, в стиле Discipline (cairo, рамка skeet/beta/default,
цвета из обоев, управление как в nvim по keycode; вид общий с routine_app.py, код свой —
Discipline тянет будильник и фокус, hub ничего этого не знает).

    hub_app.py            напоминания            hub_app.py dict   словарь (с выделенным текстом)

j/k — вниз/вверх · Tab, Shift+H/L — вкладка · i/a — новая запись (ввод обычным текстом,
Enter — сохранить, Esc — отмена) · d/x — сделано · s — +1 час · Shift+S — на завтра 09:00 ·
Shift+D — удалить · z — повторение слов (Space — показать, y — знал, n — не знал) ·
r — обновить · q, Esc — закрыть. Второй запуск поднимает уже открытое окно (GApplication).

Мышь: кнопки внизу под рукой (+ запись, готово, +1ч, завтра, удалить, повторить) —
то же самое, что клавиши выше, просто кликом. Перетаскивание — за пустое место окна
(не за строку и не за кнопку), изменение размера — за край/правый нижний уголок, как
у Discipline.

    hub_app.py --shot F [tab=items|words sel=N mode=normal|text style=…]   PNG без окна
"""
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import hublib as H  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

APP_ID = "com.jarvis.hub"
STATE_DIR = os.path.expanduser("~/.config/hypr/state")
MATUGEN = os.path.expanduser("~/.cache/matugen")
FONT = "PxPlus HP 100LX 6x8 Jarvis"
PX = 12
BIG = 28
W = 460
PAD = 14
ROW_H = 22
SIZE_FILE = os.path.expanduser("~/.config/hub/app-size")
TABS = ("items", "words")
TAB_NAMES = {"items": "Напоминания", "words": "Словарь"}

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "


# ── цвета (как у Discipline / Настроек) ────────────────────────────────────────

def hexrgb(h, d=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return d


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def palette():
    try:
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    p = {}
    for k, d in (("primary", "#b4c5ff"), ("secondary", "#c5c2ea"), ("tertiary", "#d2bdf6"),
                 ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("surface", "#10131c"), ("surface_container", "#1d1f29"),
                 ("surface_high", "#272a34"), ("on_primary", "#002979"), ("error", "#ffb4ab"),
                 ("st_hi", "#9fb4f5"), ("st_mid", "#5f74b4"), ("st_bot", "#465a94"),
                 ("st_dark", "#0a0c12")):
        p[k] = hexrgb(xc.get(k) or d, hexrgb(d))
    p["vivid"] = hexrgb(read(os.path.join(MATUGEN, "vivid.txt")), p["primary"])
    return p


def style_name():
    s = read(os.path.join(STATE_DIR, "settings-skin")).lower()
    return s if s in ("skeet", "beta") else "default"


def colors(style):
    p = palette()
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "skeet":
        acc = p["vivid"]

        def g(level, t=0.05):
            return mix((level / 255,) * 3, acc, t)
        return dict(frame="skeet", acc=acc, acc_l=mix(acc, white, 0.22), acc_d=mix(acc, black, 0.40),
                    bg=g(0x13), dot=g(0x18, 0.05), field=g(0x1b), field_l=g(0x24), sel=g(0x1e),
                    line=g(0x30, 0.08), line_soft=g(0x22, 0.06), gdark=g(0x0e, 0.03),
                    line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                    text=mix(hexrgb("#cdcdcd"), p["on_surface"], 0.35), dim=g(0x92, 0.10),
                    faint=g(0x50, 0.10), strip=[acc, p["tertiary"], p["secondary"]], err=p["error"])
    mode = read(os.path.join(STATE_DIR, "settings-mode")).lower() or "dark"
    if style == "beta" and mode == "light":
        ink = mix(p["surface"], black, 0.15)
        ink2 = mix(p["st_bot"], p["surface"], 0.35)
        bg = mix(mix(p["st_hi"], p["on_surface"], 0.85), white, 0.20)
        acc = mix(p["st_mid"], p["st_bot"], 0.40)
        return dict(frame="round", acc=acc, acc_l=acc, acc_d=mix(acc, bg, 0.45), bg=bg, dot=None,
                    field=mix(bg, white, 0.45), field_l=mix(bg, acc, 0.12), sel=mix(bg, acc, 0.16),
                    line=mix(bg, ink2, 0.28), line_soft=mix(bg, ink2, 0.14), gdark=bg,
                    text=ink, dim=mix(ink2, bg, 0.22), faint=mix(ink2, bg, 0.55),
                    strip=[acc], err=mix(p["error"], hexrgb("#7a0000"), 0.55))
    bg, cont = p["surface"], p["surface_container"]
    acc = p["primary"]
    return dict(frame="round", acc=acc, acc_l=mix(acc, white, 0.15), acc_d=mix(acc, bg, 0.50),
                bg=bg, dot=None, field=cont, field_l=p["surface_high"], sel=mix(bg, acc, 0.16),
                line=mix(cont, p["on_surface"], 0.16), line_soft=mix(cont, p["on_surface"], 0.08),
                gdark=bg, text=p["on_surface"], dim=mix(p["on_surface_variant"], bg, 0.30),
                faint=mix(p["on_surface_variant"], bg, 0.65), strip=[acc], err=p["error"])


def run_out(*cmd):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def selection():
    return run_out("wl-paste", "-p", "-n")


# ── рисование ────────────────────────────────────────────────────────────────

class Painter:
    def __init__(self, cr):
        self.cr = cr

    def rgb(self, c, a=1.0):
        self.cr.set_source_rgba(c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=1.0):
        self.rgb(c, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()

    def box(self, x, y, w, h, c):
        self.rgb(c)
        self.cr.set_line_width(1)
        self.cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        self.cr.stroke()

    def round(self, x, y, w, h, r):
        cr = self.cr
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def layout(self, s, px):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(s, -1)
        return lay

    def text_w(self, s, px=PX):
        return self.layout(s, px).get_pixel_size()[0]

    def text(self, x, y, s, c, px=PX, align="l", a=1.0, maxw=None):
        lay = self.layout(s, px)
        if maxw:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        w, _h = lay.get_pixel_size()
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        self.rgb(c, a)
        self.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(self.cr, lay)
        return w


class View:
    """Данные и раскладка — без GTK, чтобы --shot рисовал без окна."""

    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.active = True
        self.tab = "items"
        self.sel = {"items": 0, "words": 0}
        self.scroll = {"items": 0, "words": 0}
        self.mode = "normal"            # normal | text | quiz
        self.buf = ""
        self.hover = None
        self.hits = []
        self.msg, self.msg_until = "", 0
        self.quiz = []
        self.revealed = False
        self.conn = H.connect()

    def reload_style(self):
        self.style = style_name()
        self.c = colors(self.style)

    def flash(self, text):
        self.msg, self.msg_until = text, time.monotonic() + 3

    # ── данные ──
    def rows(self):
        out = []
        if self.tab == "items":
            last = None
            for it in H.items(self.conn, None, "open"):
                if it["list"] != last:
                    out.append(("head", it["list"]))
                    last = it["list"]
                out.append(("item", it))
        else:
            for w in H.words(self.conn, None, 500):
                out.append(("word", w))
        return out

    def sel_rows(self, rows):
        return [i for i, r in enumerate(rows) if r[0] != "head"]

    def move(self, step):
        rows = self.rows()
        sr = self.sel_rows(rows)
        if not sr:
            return
        cur = self.sel[self.tab]
        pos = sr.index(cur) if cur in sr else 0
        pos = max(0, min(len(sr) - 1, pos + step))
        self.sel[self.tab] = sr[pos]

    def current(self, rows):
        i = self.sel[self.tab]
        return rows[i] if 0 <= i < len(rows) else (None, None)

    # ── слои ──
    def frame_f(self):
        return 6 if self.c["frame"] == "skeet" else 1

    def height_min(self):
        return self.frame_f() + 2 + 10 + 18 + 14 + ROW_H * 3 + 40 + self.frame_f()

    def draw(self, cr, w, h):
        self.hits = []
        p = Painter(cr)
        c = self.c
        f = self.frame_f()
        self.draw_frame(p, w, h)
        self.draw_grip(p, w, h, f)
        x0, x1 = PAD + f, w - PAD - f
        y = f + 2 + 10
        self.draw_header(p, x0, x1, y)
        y += 18 + 14
        body_bottom = h - f - 34
        if self.mode == "quiz":
            self.draw_quiz(p, x0, x1, y, body_bottom)
        else:
            self.draw_list(p, x0, x1, y, body_bottom)
        self.draw_footer(p, x0, x1, h - f - 16)

    def draw_frame(self, p, w, h):
        c, cr = self.c, p.cr
        if c["frame"] == "skeet":
            l1 = mix(c["line1"], c["acc"], 0.45) if self.active else c["line1"]
            p.rect(0, 0, w, h, c["line3"])
            p.rect(1, 1, w - 2, h - 2, l1)
            p.rect(2, 2, w - 4, h - 4, c["line2"])
            p.rect(5, 5, w - 10, h - 10, l1)
            p.rect(6, 6, w - 12, h - 12, c["bg"])
            p.rgb(c["dot"])
            for yy in range(8, h - 6, 4):
                for xx in range(6 + (yy // 4) % 2 * 2, w - 6, 4):
                    cr.rectangle(xx, yy, 1, 1)
            cr.fill()
            if self.active:
                g = cairo.LinearGradient(6, 0, w - 6, 0)
                n = len(c["strip"])
                for i, col in enumerate(c["strip"]):
                    g.add_color_stop_rgb(i / max(1, n - 1), *col)
                cr.set_source(g)
                cr.rectangle(6, 6, w - 12, 1)
                cr.fill()
            else:
                p.rect(6, 6, w - 12, 1, c["line"])
        else:
            p.round(0.5, 0.5, w - 1, h - 1, 10)
            p.rgb(c["bg"])
            cr.fill_preserve()
            p.rgb(c["acc"] if self.active else c["line"])
            cr.set_line_width(1)
            cr.stroke()

    def draw_grip(self, p, w, h, f):
        p.rgb(self.c["faint"])
        for k in (4, 8, 12):
            for t in range(0, k, 2):
                p.cr.rectangle(w - f - 3 - t, h - f - 3 - (k - 1 - t), 1, 1)
        p.cr.fill()

    def draw_header(self, p, x0, x1, y):
        c = self.c
        x = x0
        for t in TABS:
            label = TAB_NAMES[t]
            on = t == self.tab
            hov = self.hover == ("tab", t)
            w = p.text_w(label)
            on_col = c["acc_l"] if self.active else c["text"]
            p.text(x, y, label, on_col if on else (c["text"] if hov else c["dim"]))
            if on:
                p.rect(x, y + 17, w, 2, c["acc"] if self.active else c["line"])
            self.hits.append(((x - 4, y - 6, w + 8, 26), ("tab", t)))
            x += w + 20
        p.text(x1, y, "×", c["dim"] if self.hover != "close" else c["text"], align="r")
        self.hits.append(((x1 - 12, y - 4, 16, 20), "close"))

    def row_bg(self, p, x0, x1, y, sel, key, h=ROW_H):
        c = self.c
        if sel:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"])
            p.rect(x0 + 1, y, 2, h, c["acc"])
        elif self.hover == key:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"], 0.5)
        self.hits.append(((x0, y, x1 - x0, h), key))

    def draw_list(self, p, x0, x1, y0, y1):
        c = self.c
        rows = self.rows()
        visible = max(1, (y1 - y0) // ROW_H)
        sel = self.sel[self.tab]
        off = self.scroll[self.tab]
        if sel < off:
            off = sel
        elif sel >= off + visible:
            off = sel - visible + 1
        off = max(0, min(off, max(0, len(rows) - visible)))
        self.scroll[self.tab] = off
        if not rows:
            p.text(x0, y0, "Пусто. Нажмите i и впишите первое.", c["faint"])
            return
        y = y0
        for i in range(off, min(len(rows), off + visible)):
            kind, d = rows[i]
            if kind == "head":
                p.text(x0, y + 3, d, c["dim"])
                y += ROW_H
                continue
            is_sel = i == sel
            self.row_bg(p, x0, x1, y, is_sel, ("row", i))
            ty = y + (ROW_H - 16) / 2 + 1
            if kind == "item":
                over = bool(d["due"]) and d["due"] < H.now()
                col = c["err"] if over else (c["acc_l"] if is_sel else c["text"])
                text = H.fmt_item(d)
                if " · " in text:
                    main, due = text.split(" · ", 1)
                else:
                    main, due = text, ""
                if is_sel and self.mode == "text" and self.text_target == i:
                    w = p.text(x0 + 10, ty, self.buf, c["acc_l"])
                    if int(time.monotonic() * 2) % 2 == 0:
                        p.rect(x0 + 10 + w, y + 4, 6, ROW_H - 8, c["acc_l"])
                else:
                    p.text(x0 + 10, ty, main, col, maxw=(x1 - x0) * 0.6)
                    if due:
                        p.text(x1 - 6, ty, due, c["faint"] if not over else c["err"], align="r")
            else:
                text = "%s — %s" % (d["term"], d["translation"])
                col = c["acc_l"] if is_sel else c["text"]
                if is_sel and self.mode == "text" and self.text_target == i:
                    w = p.text(x0 + 10, ty, self.buf, c["acc_l"])
                    if int(time.monotonic() * 2) % 2 == 0:
                        p.rect(x0 + 10 + w, y + 4, 6, ROW_H - 8, c["acc_l"])
                else:
                    p.text(x0 + 10, ty, text, col, maxw=x1 - x0 - 20)
            y += ROW_H

    def draw_quiz(self, p, x0, x1, y0, y1):
        c = self.c
        cy = (y0 + y1) / 2
        if not self.quiz:
            p.text((x0 + x1) / 2, cy, "Повторять нечего. Esc — назад.", c["faint"], align="c")
            return
        w = self.quiz[0]
        p.text((x0 + x1) / 2, cy - 30, w["term"], c["acc_l"], px=BIG, align="c")
        if self.revealed:
            p.text((x0 + x1) / 2, cy + 10, w["translation"], c["text"], align="c")
        p.text((x0 + x1) / 2, y1 - 6, "осталось %d" % len(self.quiz), c["faint"], align="c")

    def chip(self, p, x, y, label, key, h=19):
        """Кликабельная кнопка-«фишка» в подвале — то же действие, что и клавиша."""
        c = self.c
        w = p.text_w(label) + 14
        hov = self.hover == key
        p.box(x, y, w, h, c["acc"] if hov else c["line"])
        if hov:
            p.rect(x + 1, y + 1, w - 2, h - 2, c["field_l"])
        p.text(x + 7, y + (h - 16) // 2 + 1, label, c["acc_l"] if hov else c["text"])
        self.hits.append(((x, y, w, h), key))
        return w

    def buttons(self, p, x0, x1, y, items):
        """items: [(подпись, ключ)], справа налево, с отступом."""
        bx = x1
        for lab, key in reversed(items):
            bw = p.text_w(lab) + 14
            bx -= bw + 6
            self.chip(p, bx, y, lab, key)
        return bx

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        if self.mode == "text":
            prompt = {"items": "новая: ", "words": "слово = перевод: "}.get(self.tab, "")
            w = p.text(x0, y, prompt + self.buf, c["text"])
            if int(time.monotonic() * 2) % 2 == 0:
                p.rect(x0 + w, y + 1, 6, 14, c["acc_l"])
            return
        if self.mode == "quiz":
            by = y - 2
            self.buttons(p, x0, x1, by, [("назад", ("btn", "back")),
                                         ("не знал", ("btn", "no")),
                                         ("знал", ("btn", "yes")),
                                         ("показать", ("btn", "reveal"))])
            p.text(x0, y, "Space показать · y знал · n не знал · Esc назад", c["faint"])
            return
        badge = "INSERT" if self.mode == "text" else "NORMAL"
        bw = p.text_w(badge) + 10
        p.rect(x0, y - 1, bw, 16, c["field_l"])
        p.text(x0 + 5, y, badge, c["acc_l"])
        if self.tab == "items":
            btns = [("+ запись", ("btn", "new")), ("готово", ("btn", "done")),
                    ("+1ч", ("btn", "snooze1")), ("завтра", ("btn", "snoozetomorrow")),
                    ("удалить", ("btn", "delete"))]
        else:
            btns = [("+ слово", ("btn", "new")), ("повторить", ("btn", "quiz")),
                    ("удалить", ("btn", "delete"))]
        left_limit = self.buttons(p, x0, x1, y - 2, btns)
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x0 + bw + 10, y, self.msg, c["text"], maxw=max(0, left_limit - x0 - bw - 20))


# ── окно ──────────────────────────────────────────────────────────────────────

class HubWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="items"):
        super().__init__(application=app, title="Hub")
        self.view = View()
        self.view.text_target = -1
        self.view.tab = tab if tab in TABS else "items"
        self.set_title(self.tab_title())
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_size_request(W, self.view.height_min())
        sw, sh = W, max(self.view.height_min(), 480)
        try:
            a, b = open(SIZE_FILE).read().split()[:2]
            sw, sh = max(W, int(a)), max(self.view.height_min(), int(b))
        except (OSError, ValueError):
            pass
        self.set_default_size(sw, sh)
        self.last_size = (sw, sh)
        self.connect("configure-event", self.on_configure)
        self.cursor_name = None
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", lambda *_: self.set_hover(None))
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("notify::is-active", self.on_active)
        GLib.timeout_add(500, self.tick)

    def tab_title(self):
        return "Reminders" if self.view.tab == "items" else "Dictionary"

    def on_configure(self, _w, ev):
        size = (ev.width, ev.height)
        if size != self.last_size:
            self.last_size = size
            if getattr(self, "size_save", None):
                GLib.source_remove(self.size_save)
            self.size_save = GLib.timeout_add(600, self.save_size)
        return False

    def save_size(self):
        self.size_save = None
        try:
            os.makedirs(os.path.dirname(SIZE_FILE), exist_ok=True)
            with open(SIZE_FILE, "w") as f:
                f.write("%d %d\n" % self.last_size)
        except OSError:
            pass
        return False

    EDGES = {"nw": Gdk.WindowEdge.NORTH_WEST, "n": Gdk.WindowEdge.NORTH,
             "ne": Gdk.WindowEdge.NORTH_EAST, "e": Gdk.WindowEdge.EAST,
             "se": Gdk.WindowEdge.SOUTH_EAST, "s": Gdk.WindowEdge.SOUTH,
             "sw": Gdk.WindowEdge.SOUTH_WEST, "w": Gdk.WindowEdge.WEST}

    def edge_at(self, x, y):
        a = self.area.get_allocation()
        w, h, m = a.width, a.height, 6
        if x >= w - 18 and y >= h - 18:
            return "se"
        v = "n" if y < m else "s" if y >= h - m else ""
        hz = "w" if x < m else "e" if x >= w - m else ""
        return (v + hz) or None

    def set_cursor(self, name):
        if name == self.cursor_name:
            return
        self.cursor_name = name
        gw = self.area.get_window()
        if gw is not None:
            gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), name) if name else None)

    def on_active(self, *_a):
        self.view.active = self.is_active()
        self.redraw()

    def redraw(self):
        self.area.queue_draw()

    def tick(self):
        if style_name() != self.view.style:
            self.view.reload_style()
        self.redraw()
        return True

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.view.draw(cr, a.width, a.height)

    def hit(self, x, y):
        for (hx, hy, hw, hh), key in reversed(self.view.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return key
        return None

    def set_hover(self, key):
        if key != self.view.hover:
            self.view.hover = key
            self.redraw()

    def on_motion(self, _w, ev):
        edge = self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else None)
        self.set_hover(None if edge else self.hit(ev.x, ev.y))

    def on_scroll(self, _w, ev):
        d = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction)
        if d:
            self.view.move(d)
            self.redraw()
        return True

    def on_click(self, _w, ev):
        v = self.view
        edge = self.edge_at(ev.x, ev.y)
        if edge and ev.button == 1:
            self.begin_resize_drag(self.EDGES[edge], ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        key = self.hit(ev.x, ev.y)
        if key is None:
            if ev.button == 1:
                self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        if ev.button != 1:
            return True
        if key == "close":
            self.close()
        elif isinstance(key, tuple) and key[0] == "tab":
            v.tab, v.mode = key[1], "normal"
            self.set_title(self.tab_title())
            self.resize_to_min()
        elif isinstance(key, tuple) and key[0] == "row":
            v.sel[v.tab] = key[1]
        elif isinstance(key, tuple) and key[0] == "btn":
            self.do_button(key[1])
        self.redraw()
        return True

    # ── кнопки подвала — те же действия, что и клавиши в key_normal/key_quiz ──
    def do_button(self, action):
        v = self.view
        if v.mode == "quiz":
            if action == "reveal":
                v.revealed = True
            elif action in ("yes", "no") and v.quiz and v.revealed:
                H.review(v.conn, v.quiz.pop(0)["id"], action == "yes")
                v.revealed = False
            elif action == "back":
                v.mode = "normal"
            return
        if action == "new":
            self.start_new()
        elif action == "quiz":
            self.start_quiz()
        elif action == "delete":
            self.action_delete()
        elif v.tab == "items":
            rows = v.rows()
            kind, d = v.current(rows)
            if kind != "item":
                return
            if action == "done":
                H.done(v.conn, d["id"], "pc")
            elif action == "snooze1":
                H.snooze(v.conn, d["id"], 3600, source="pc")
            elif action == "snoozetomorrow":
                import hubtg
                H.snooze(v.conn, d["id"], until=hubtg.tomorrow_9(), source="pc")

    def start_new(self):
        v = self.view
        rows = v.rows()
        if v.sel[v.tab] >= len(rows) or (rows and rows[v.sel[v.tab]][0] == "head"):
            v.move(0)
        v.mode, v.buf = "text", ""
        v.text_target = v.sel[v.tab]

    def start_quiz(self):
        v = self.view
        v.quiz = list(H.due_words(v.conn, 20))
        v.revealed = False
        v.mode = "quiz"

    def action_delete(self):
        v = self.view
        rows = v.rows()
        kind, d = v.current(rows)
        if kind == "item":
            H.drop(v.conn, d["id"], "pc")
        elif kind == "word":
            H.del_word(v.conn, d["id"])

    def resize_to_min(self):
        self.set_size_request(W, self.view.height_min())

    def set_tab(self, tab):
        self.view.tab, self.view.mode = tab, "normal"

    # ── клавиатура ──
    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""
        if v.mode == "text":
            self.key_text(ch, name, ev)
        elif v.mode == "quiz":
            self.key_quiz(ch, name)
        else:
            self.key_normal(ch, name, shift)
        self.redraw()
        return True

    def key_text(self, ch, name, ev):
        v = self.view
        if name == "Escape":
            v.mode, v.buf, v.text_target = "normal", "", -1
        elif name in ("Return", "KP_Enter"):
            self.submit_text()
        elif name == "BackSpace":
            v.buf = v.buf[:-1]
        else:
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 200 and chr(u).isprintable():
                v.buf += chr(u)

    def submit_text(self):
        v = self.view
        text = v.buf.strip()
        v.mode, v.buf, v.text_target = "normal", "", -1
        if not text:
            return
        try:
            if v.tab == "items":
                H.add_smart(v.conn, text, "pc")
            else:
                for sep in ("=", " — ", " - "):
                    if sep in text:
                        t, tr = [x.strip() for x in text.split(sep, 1)]
                        H.add_word(v.conn, t, tr)
                        break
                else:
                    v.flash("формат: слово = перевод")
        except ValueError as e:
            v.flash(str(e))

    def key_quiz(self, ch, name):
        v = self.view
        if name == "Escape":
            v.mode = "normal"
        elif name == "space" or ch == " ":
            v.revealed = True
        elif ch in ("y", "n") and v.quiz and v.revealed:
            self.do_button("yes" if ch == "y" else "no")

    def key_normal(self, ch, name, shift):
        v = self.view
        if name in ("q", "Escape") or ch == "q":
            self.close()
            return
        if name == "Tab" or (shift and ch in ("h", "l")):
            v.tab = "words" if v.tab == "items" else "items"
            self.set_title(self.tab_title())
            self.resize_to_min()
            return
        if ch == "j":
            v.move(1)
            return
        if ch == "k":
            v.move(-1)
            return
        if ch == "r":
            return
        if ch in ("i", "a"):
            self.start_new()
            return
        if ch == "z" and v.tab == "words":
            self.start_quiz()
            return
        rows = v.rows()
        kind, d = v.current(rows)
        if kind == "item":
            if ch in ("d", "x") and not shift:
                self.do_button("done")
            elif ch == "s" and not shift:
                self.do_button("snooze1")
            elif ch == "s" and shift:
                self.do_button("snoozetomorrow")
            elif ch == "d" and shift:
                self.action_delete()
        elif kind == "word" and ch == "d" and shift:
            self.action_delete()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        tab = "words" if "dict" in args else "items"
        if self.win is None:
            self.win = HubWindow(self, tab)
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            if tab == "words":
                sel = selection()
                if sel and len(sel) < 200:
                    self.win.view.mode, self.win.view.buf = "text", sel.replace("\n", " ") + " = "
                    self.win.view.text_target = self.win.view.sel["words"]
            self.win.show_all()
        else:
            self.win.view.reload_style()
            self.win.set_tab(tab)
            self.win.redraw()
        self.win.present()
        return 0


def shot(path, tab="items", sel=0, mode="normal", style=None, w=0, h=0):
    v = View()
    if style:
        v.style, v.c = style, colors(style)
    v.tab, v.mode = tab, mode
    v.sel[tab] = sel
    v.text_target = sel
    if mode == "text":
        v.buf = "пример"
    ww, hh = max(W, w or W), max(v.height_min(), h or 480)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, hh)
    cr = cairo.Context(surf)
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    v.draw(cr, ww, hh)
    surf.write_to_png(path)
    return ww, hh


def main():
    if "--check" in sys.argv:
        v = View()
        v.draw(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)), 10, 10)
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        kw = {}
        for a in sys.argv[3:]:
            k, _, val = a.partition("=")
            kw[k] = int(val) if val.isdigit() else val
        print(shot(sys.argv[2], **kw))
        return
    GLib.set_prgname(APP_ID)
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
