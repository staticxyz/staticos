#!/usr/bin/env python3
"""Лаунчер приложений с категориями — стиль Discipline/Hub, vim-навигация.

Super+Z: два режима — навигация (j/k/l/h) и поиск (Ctrl+E или /).
Категории берутся из .desktop файлов (те же, что в Пуске).
Тема и цвета — из обоев (palette + settings-skin).
"""
import os
import sys
import subprocess

sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango, PangoCairo
import cairo

NAMESPACE = "jarvis-launcher"

APP_ID = "com.jarvis.launcher"
W, H_MIN = 560, 640
ROW_H = 34
MAX_ROWS = 12                  # строк в окне, дальше — прокрутка
OM_PAD, OM_INPUT, OM_GAP, OM_BORDER = 18, 40, 8, 2   # вид Omarchy
PAD = 20
HEADER_H = 42
FONT_SZ = 16

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "

STATE_DIR = os.path.expanduser("~/.config/hypr/state")

# ── палитра (тот же код, что в Hub) ──────────────────────────────────────────

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

MATUGEN = os.path.expanduser("~/.cache/matugen")

def palette():
    try:
        sys.path.insert(0, os.path.expanduser("~/.config/niri/scripts"))
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
                    bg=g(0x13), field=g(0x1b), field_l=g(0x24), sel=g(0x1e),
                    line=g(0x30, 0.08), line_soft=g(0x22, 0.06), gdark=g(0x0e, 0.03),
                    line3=g(0x0a, 0.03),
                    text=mix(hexrgb("#cdcdcd"), p["on_surface"], 0.35), dim=g(0x92, 0.10),
                    faint=g(0x50, 0.10), err=p["error"])
    bg, cont = p["surface"], p["surface_container"]
    acc = p["primary"]
    return dict(frame="round", acc=acc, acc_l=mix(acc, white, 0.15), acc_d=mix(acc, bg, 0.50),
                bg=bg, field=cont, field_l=p["surface_high"], sel=mix(bg, acc, 0.16),
                line=mix(cont, p["on_surface"], 0.16), line_soft=mix(cont, p["on_surface"], 0.08),
                gdark=bg, line3=bg,
                text=p["on_surface"], dim=mix(p["on_surface_variant"], bg, 0.30),
                faint=mix(p["on_surface_variant"], bg, 0.65), err=p["error"])

# ── категории (как в Пуске) ──────────────────────────────────────────────────

CATS = (
    ("staticOS", ("X-StaticOS",)),
    ("Игры", ("Game",)),
    ("Разработка", ("Development", "IDE")),
    ("Интернет", ("Network", "WebBrowser", "Email", "Chat", "InstantMessaging")),
    ("Графика", ("Graphics", "Photography")),
    ("Звук и видео", ("AudioVideo", "Audio", "Video", "Player")),
    ("Офис", ("Office",)),
    ("Настройки", ("Settings",)),
    ("Система", ("System", "Monitor", "TerminalEmulator", "FileManager")),
    ("Стандартные", ("Utility", "TextEditor", "Accessories")),
)

def load_apps():
    cats = {name: [] for name, _k in CATS}
    cats["Прочее"] = []
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        have = set((a.get_categories() or "").split(";"))
        name = next((n for n, keys in CATS if have & set(keys)), "Прочее")
        cats[name].append(a)
    for v in cats.values():
        v.sort(key=lambda a: (a.get_display_name() or "").lower())
    return [(n, v) for n, v in ([(n, cats[n]) for n, _ in CATS] + [("Прочее", cats["Прочее"])]) if v]

# ── рисовалка (cairo + Pango, как Hub) ───────────────────────────────────────

class Painter:
    def __init__(self, cr, c):
        self.cr, self.c = cr, c

    def rgb(self, color):
        self.cr.set_source_rgb(*color)

    def rgba(self, color, a):
        self.cr.set_source_rgba(*color, a)

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
        fd = Pango.FontDescription("JetBrainsMono Nerd Font %dpx" % size)
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
        lay.set_font_description(Pango.FontDescription("JetBrainsMono Nerd Font %dpx" % size))
        lay.set_text(text, -1)
        return lay.get_pixel_size()[0]

    def icon(self, x, y, size, pixbuf):
        if pixbuf is None:
            return
        if pixbuf.get_width() != size or pixbuf.get_height() != size:
            pixbuf = pixbuf.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)
        Gdk.cairo_set_source_pixbuf(self.cr, pixbuf, x, y)
        self.cr.paint()


_icon_cache = {}

def get_icon(gicon, size=16):
    if gicon is None:
        return None
    key = str(gicon)
    if key in _icon_cache:
        return _icon_cache[key]
    theme = Gtk.IconTheme.get_default()
    try:
        info = theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE)
        pb = info.load_icon() if info else None
    except Exception:
        pb = None
    _icon_cache[key] = pb
    return pb


# ── данные и рисование ───────────────────────────────────────────────────────

class View:
    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.cats = load_apps()
        self.mode = "normal"            # normal | search
        self.buf = ""
        self.sel = 0                    # выделенная строка
        self.scroll = 0
        self.cat_idx = -1               # -1 = список категорий
        self.pending_jj = False
        self.pending_t = 0
        self.home = (0, 0)              # позиция в списке разделов до входа в раздел
        self.cat_pos = {}               # позиция внутри каждого раздела

    def rows(self):
        if self.cat_idx == -1:
            if self.buf:
                q = self.buf.lower()
                result = []
                for _, apps in self.cats:
                    for a in apps:
                        name = (a.get_display_name() or "").lower()
                        if q in name:
                            result.append(("app", a))
                return result
            return [("cat", name, apps) for name, apps in self.cats]
        _, apps = self.cats[self.cat_idx]
        return [("app", a) for a in apps]

    def title(self):
        if self.cat_idx == -1:
            return "Приложения"
        return self.cats[self.cat_idx][0]

    def visible(self):
        return max(1, min(MAX_ROWS, len(self.rows())))

    def height(self):
        """Окно по содержимому, как у Omarchy (walker): поле + строки, без пустоты."""
        return 2 * OM_PAD + OM_INPUT + OM_GAP + self.visible() * ROW_H

    def draw(self, cr, w, h):
        """Вид Omarchy (13.10.2026, просьба: «привести внешний вид под Omarchy»):
        квадратное окно, рамка 2 px акцентом, плотный фон; сверху поле, в пустом —
        название раздела («Приложения…»); список без подложек — выбранное только цветом
        акцента. Ни заголовка, ни счётчиков, ни подвала; режим — бледно справа в поле."""
        c = self.c
        p = Painter(cr, c)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*c["bg"], 0.96)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        p.rgb(c["acc"])
        cr.set_line_width(OM_BORDER)
        cr.rectangle(OM_BORDER / 2, OM_BORDER / 2, w - OM_BORDER, h - OM_BORDER)
        cr.stroke()
        x0, x1 = OM_PAD, w - OM_PAD

        # поле ввода
        y = OM_PAD
        ty = y + (OM_INPUT - FONT_SZ) // 2
        badge = "ВВОД" if self.mode == "search" else "/ поиск"
        bw = p.text(x1 - 4, ty, badge, c["faint"], size=FONT_SZ, align="r")
        maxw = x1 - x0 - bw - 24
        if self.mode == "search" or self.buf:
            cur = "▏" if self.mode == "search" else ""
            p.text(x0 + 4, ty, self.buf + cur, c["text"], size=FONT_SZ, maxw=maxw)
        else:
            p.text(x0 + 4, ty, self.title() + "…", c["faint"], size=FONT_SZ, maxw=maxw)
        p.rect(x0, y + OM_INPUT - 1, x1 - x0, 1, c["line_soft"])

        # список
        y += OM_INPUT + OM_GAP
        rows = self.rows()
        if not rows:
            p.text(x0 + 4, y + (ROW_H - FONT_SZ) // 2, "Ничего не найдено", c["faint"], size=FONT_SZ)
            return
        max_vis = self.visible()
        sel = max(0, min(self.sel, len(rows) - 1))
        self.sel = sel
        off = self.scroll
        if sel < off:
            off = sel
        if sel >= off + max_vis:
            off = sel - max_vis + 1
        off = max(0, min(off, len(rows) - max_vis))
        self.scroll = off

        ico_sz = 20
        for i in range(off, min(off + max_vis, len(rows))):
            ry = y + (i - off) * ROW_H
            is_sel = i == sel
            row = rows[i]
            txt_x = x0 + 4 + ico_sz + 14
            txt_y = ry + (ROW_H - FONT_SZ) // 2
            ico_y = ry + (ROW_H - ico_sz) // 2
            col = c["acc_l"] if is_sel else c["text"]
            if row[0] == "cat":
                _, name, apps = row
                pb = get_icon(apps[0].get_icon(), ico_sz) if apps else None
                label = name
            else:
                a = row[1]
                pb = get_icon(a.get_icon(), ico_sz)
                label = a.get_display_name() or "?"
            if pb:
                if not is_sel:
                    cr.push_group()
                    p.icon(x0 + 4, ico_y, ico_sz, pb)
                    cr.pop_group_to_source()
                    cr.paint_with_alpha(0.8)
                else:
                    p.icon(x0 + 4, ico_y, ico_sz, pb)
            p.text(txt_x, txt_y, label, col, size=FONT_SZ, maxw=x1 - txt_x - 10)

        if len(rows) > max_vis:                      # тонкая полоса прокрутки у рамки
            avail = max_vis * ROW_H
            bar_h = max(12, avail * max_vis / len(rows))
            bar_y = y + (avail - bar_h) * off / max(1, len(rows) - max_vis)
            p.rect(w - OM_BORDER - 4, bar_y, 2, bar_h, c["faint"])

    def enter(self, idx):
        """Войти в раздел: запомнить, где стоял выбор в списке разделов."""
        self.home = (self.sel, self.scroll)
        self.cat_idx = idx
        self.sel, self.scroll = self.cat_pos.get(idx, (0, 0))

    def back(self):
        """Назад к разделам — на тот, из которого вышли (13.10.2026: раньше — в начало)."""
        self.cat_pos[self.cat_idx] = (self.sel, self.scroll)
        idx = self.cat_idx
        self.cat_idx, self.buf = -1, ""
        names = [n for n, _ in self.cats]
        self.sel = idx if 0 <= idx < len(names) else self.home[0]
        self.scroll = self.home[1]

# ── окно ─────────────────────────────────────────────────────────────────────

class LauncherWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Launcher")
        self.view = View()
        self.set_decorated(False)
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        GtkLayerShell.set_exclusive_zone(self, -1)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)

    def redraw(self):
        self.area.queue_draw()

    def _panel_rect(self, w, h):
        ph = self.view.height()
        px = (w - W) // 2
        py = max(0, (h - H_MIN) // 2)     # верх на месте, окно растёт вниз — не прыгает
        return px, py, W, ph

    def on_draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        px, py, pw, ph = self._panel_rect(w, h)
        cr.save()
        cr.translate(px, py)
        self.view.draw(cr, pw, ph)
        cr.restore()

    def on_scroll(self, _w, ev):
        v = self.view
        if ev.direction == Gdk.ScrollDirection.UP:
            v.sel = max(0, v.sel - 3)
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            v.sel = min(len(v.rows()) - 1, v.sel + 3)
        self.redraw()
        return True

    def on_click(self, _w, ev):
        if ev.button == 1:
            self.activate_current()
        return True

    def activate_current(self):
        v = self.view
        rows = v.rows()
        if not rows or v.sel >= len(rows):
            return
        row = rows[v.sel]
        if row[0] == "cat":
            v.enter(next(i for i, (n, _) in enumerate(v.cats) if n == row[1]))
            self.redraw()
        else:
            a = row[1]
            try:
                a.launch(None, None)
            except Exception:
                cmd = a.get_commandline()
                if cmd:
                    subprocess.Popen(cmd, shell=True, start_new_session=True,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.close()

    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        mod = bool(ev.state & Gdk.ModifierType.MOD4_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""

        if mod and ch == "x":
            self.close()
            return True
        if ctrl and ch == "q":
            self.close()
            return True

        # Ctrl+E — переключение режима
        if ctrl and ch == "e":
            if v.mode == "search":
                v.mode = "normal"
            else:
                v.mode = "search"
            self.redraw()
            return True

        if v.mode == "search":
            self.key_search(ch, name, ev)
        else:
            self.key_normal(ch, name)
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
            self.activate_current()
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
            if u and len(v.buf) < 100 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0
            v.pending_t = now
            v.pending_jj = True
        else:
            v.pending_jj = False
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 100 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0

    def key_normal(self, ch, name):
        v = self.view
        rows = v.rows()
        if name == "Escape" or ch == "q":
            self.close()
        elif name == "BackSpace":
            if v.cat_idx >= 0:
                v.back()
            else:
                self.close()
        elif ch == "j":
            v.sel = min(len(rows) - 1, v.sel + 1)
        elif ch == "k":
            v.sel = max(0, v.sel - 1)
        elif ch == "g":
            v.sel = 0
        elif name in ("Return", "KP_Enter") or ch == "l":
            self.activate_current()
        elif ch == "h":
            if v.cat_idx >= 0:
                v.back()
            else:
                self.close()
        elif ch == "/":
            v.mode = "search"

class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win is not None:
            self.win.close()
            return
        self.win = LauncherWindow(self)
        self.win.connect("destroy", lambda *_: setattr(self, "win", None))
        self.win.show_all()
        self.win.present()

def shot(path, style=None, cat=-1, sel=0, mode="normal", buf=""):
    v = View()
    if style:
        v.style, v.c = style, colors(style)
    v.cat_idx, v.sel, v.mode, v.buf = cat, sel, mode, buf
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, v.height())
    cr = cairo.Context(surf)
    v.draw(cr, W, v.height())
    surf.write_to_png(path)

def check():
    v = View()
    assert v.cats, "нет категорий"
    assert any(n == "staticOS" for n, _ in v.cats), "нет staticOS"
    rows = v.rows()
    assert rows, "нет строк"
    v.buf = "zen"
    found = v.rows()
    print("check: %d категорий, %d строк, поиск 'zen' = %d результатов" % (len(v.cats), len(rows), len(found)))

if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        p = sys.argv[sys.argv.index("--shot") + 1] if sys.argv.index("--shot") + 1 < len(sys.argv) else "/tmp/launcher.png"
        style = None
        for a in sys.argv:
            if a.startswith("style="):
                style = a.split("=", 1)[1]
        shot(p, style=style)
        print("saved", p)
    else:
        App().run([])
