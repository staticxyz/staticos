#!/usr/bin/env python3
"""Standalone calendar, themed from the live wallpaper palette.

Opened by left-clicking the waybar calendar module (waybar_clock.py). Single
instance: launching again re-presents the existing window.

Day cells are Boxes with Labels, not Buttons, on purpose: the Breeze Qt/GTK
theme styles `button` strongly enough that a plain `.today` background-color
never won, so the current day silently lost its highlight. Labels are styled
only by the CSS here, which makes the appearance predictable.

Colours resolve from the named colours matugen writes into
~/.config/gtk-4.0/matugen.css (accent_color, window_bg_color, card_bg_color …),
so the window follows the wallpaper like the rest of the desktop.

Notes are stored per-day in ~/.local/share/calendar-notes.json.

13.10.2026 (Просьба: «оформить под стиль системы (Skeet), с кнопками увеличить на весь
экран и закрыть»): поверх matugen-оформления — вид стиля монитора (Default — окно XP,
Skeet — gamesense, Beta — плоский), тот же, что у Настроек/Recorder/календаря XP-панели.
Стиль — ~/.config/hypr/state/calendar-style (пишет system_style.py по монитору в фокусе),
перечитывается при каждом открытии. Своя полоса заголовка «Calendar.exe» — её можно
тянуть мышью; кнопки рисует close_cap.py (крестик системы и «на весь экран»), F11/f —
то же с клавиатуры. Окно плавающее 600×560 — правило niri в cfg/window-rules.kdl.
"""
import calendar
import datetime
import json
import os
import subprocess
import sys

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GLib, Pango  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import close_cap  # noqa: E402
import popup_theme  # noqa: E402
import rec_style  # noqa: E402

APP_ID = "dev.static.calendar"
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/calendar-style")
STYLES = ("default", "skeet", "beta")
TITLE_H = {"skeet": 28, "beta": 34, "default": 30}   # как у Recorder (rec_menu.geometry)
NOTES_PATH = os.path.expanduser("~/.local/share/calendar-notes.json")

CSS = """
window.calendar-app { background-color: @window_bg_color; }

.cal-header {
    background-color: @headerbar_bg_color;
    padding: 12px 18px;
}
.cal-title { font-size: 21px; font-weight: 800; color: @window_fg_color; }
.cal-subtitle { font-size: 12px; color: alpha(@window_fg_color, 0.5); }

.pill {
    background-image: none;
    box-shadow: none;
    border: none;
    outline: none;
    background-color: alpha(@accent_color, 0.14);
    color: @accent_color;
    border-radius: 999px;
    font-weight: 700;
    padding: 6px 14px;
    min-height: 20px;
}
.pill:hover { background-color: alpha(@accent_color, 0.28); }
.pill.round { padding: 6px 10px; min-width: 20px; }

.cal-weekday {
    color: alpha(@window_fg_color, 0.45);
    font-weight: 700;
    font-size: 11px;
    padding: 4px 0 8px 0;
}
.cal-weekday.we { color: alpha(@accent_color, 0.75); }

/* --- month grid ------------------------------------------------------- */
.day {
    background-color: @card_bg_color;
    border-radius: 14px;
    margin: 3px;
    padding: 8px 10px;
}
.day:hover { background-color: alpha(@accent_color, 0.13); }
.day .num { font-size: 17px; font-weight: 650; color: @window_fg_color; }
.day.dim { background-color: alpha(@card_bg_color, 0.35); }
.day.dim .num { color: alpha(@window_fg_color, 0.25); font-weight: 400; }
.day.we .num { color: alpha(@accent_color, 0.85); }
.day.today { background-color: @accent_color; }
.day.today .num { color: @accent_fg_color; font-weight: 850; }
.day.today:hover { background-color: @accent_color; }
.day.sel { box-shadow: inset 0 0 0 2px @accent_color; }
.day .note {
    font-size: 11px;
    color: alpha(@window_fg_color, 0.7);
}
.day.today .note { color: alpha(@accent_fg_color, 0.85); }
.dot { color: @accent_color; font-size: 15px; }
.day.today .dot { color: @accent_fg_color; }

/* --- year grid -------------------------------------------------------- */
.ycard {
    background-color: @card_bg_color;
    border-radius: 16px;
    padding: 12px 10px;
    margin: 6px;
}
.ycard:hover { background-color: alpha(@accent_color, 0.13); }
.ycard.cur { box-shadow: inset 0 0 0 2px @accent_color; }
.ycard .mon {
    color: @accent_color;
    font-weight: 800;
    font-size: 14px;
    padding-bottom: 8px;
}
.ycard .wd { color: alpha(@window_fg_color, 0.4); font-size: 10px; font-weight: 700; }
.ycard .d  { color: alpha(@window_fg_color, 0.9); font-size: 11px; }
.ycard .d.dim { color: alpha(@window_fg_color, 0.18); }
.ycard .d.today {
    background-color: @accent_color;
    color: @accent_fg_color;
    font-weight: 800;
    border-radius: 999px;
}

/* --- note editor ------------------------------------------------------ */
.note-bar {
    background-color: @headerbar_bg_color;
    padding: 10px 18px;
}
.note-bar entry {
    background-image: none;
    background-color: @view_bg_color;
    color: @window_fg_color;
    border-radius: 10px;
    padding: 8px 12px;
}
"""

def read_style():
    if os.environ.get("CAL_STYLE") in STYLES:            # для проверок: CAL_STYLE=beta
        return os.environ["CAL_STYLE"]
    try:
        v = open(STYLE_FILE).read().strip().lower()
    except OSError:
        return "default"
    return v if v in STYLES else "default"


def _rgb(h):
    h = h.lstrip("#")[:6]
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def skin_colors(style):
    """#rrggbb стиля: Skeet/Beta — rec_style.colors() (те же, что у Recorder и календаря
    XP-панели), Default — окно XP в тонах «Пуска» (xpbar_colors)."""
    mix = rec_style._mix
    p = popup_theme.palette()
    if style in ("skeet", "beta"):
        c = dict(rec_style.colors(style))
        c["err"] = p.get("error", "#ffb4ab")
        if style == "skeet":
            c["strip_d"] = ", ".join(mix(x, "#000000", 0.55) for x in c["strip"])
            c["strip"] = ", ".join(c["strip"])
            c["line1_on"] = mix(c["line1"], c["acc"], 0.45)
        return c
    try:
        import xpbar_colors
        t = xpbar_colors.colors()
    except Exception:
        t = {}
    g = lambda k, d: t.get(k, p.get(k, d))   # noqa: E731
    base = g("base", "#10131c")
    c = dict(base=base, bg=mix(base, p["surface"], 0.5), row=mix(base, p["surface_high"], 0.55),
             text=p["on_surface"], dim=p["on_surface_variant"], acc=g("st_hi", "#9fb4f5"),
             st_top=g("st_top", "#7f95d8"), st_mid=g("st_mid", "#5f74b4"), st_bot=g("st_bot", "#465a94"),
             st_hi=g("st_hi", "#9fb4f5"), st_hover=g("st_hover", "#8ea4e8"), st_dark=g("st_dark", "#0a0c12"),
             t_top=g("t_top", "#3f4c72"), t_bot=g("t_bot", "#2a3559"), t_border=g("t_border", "#54628c"),
             t_hover_top=g("t_hover_top", "#515e88"), error=p.get("error", "#ffb4ab"),
             on_surface=p["on_surface"])
    c["sel"] = mix(c["st_hi"], "#ffffff", 0.18)
    return c


def cap_colors(style, c):
    """Цвета кнопок заголовка для close_cap.draw — кортежи 0..1."""
    keys = {"skeet": ("field_l", "field", "line3", "gline", "err", "dim", "acc_l"),
            "beta": ("err", "field", "line_strong", "bg", "text", "acc"),
            "default": ("error", "st_hover", "st_bot", "st_hi", "on_surface", "st_top")}[style]
    return {k: _rgb(c[k]) for k in keys}


def skin_css(style, c):
    """Вид стиля поверх CSS выше: рамка, заголовок, кнопки, клетки дней — без скруглений."""
    c = dict(c, th=TITLE_H[style])
    common = """
    window.calendar-app { background-color: transparent; }
    .day, .ycard, .pill, .pill.round, .note-bar entry, .ycard .d.today { border-radius: 0; }
    .cal-title { font-size: 16px; font-weight: normal; }
    .day .num { font-size: 16px; font-weight: normal; }
    .day.today .num, .ycard .mon, .ycard .d.today { font-weight: normal; }
    .cap-title { font-size: 12px; }
    .titlebar { min-height: %(th)spx; padding: 0 3px 0 8px; }
    """ % c
    if style == "skeet":
        return common + """
    .frame {
        background-color: %(bg)s; color: %(text)s;
        background-image: linear-gradient(to right, %(strip)s), linear-gradient(to right, %(strip_d)s);
        background-size: 100%% 1px, 100%% 1px; background-repeat: no-repeat, no-repeat;
        background-position: 0 6px, 0 7px;
        box-shadow: inset 0 0 0 6px %(line3)s, inset 0 0 0 5px %(line1_on)s,
                    inset 0 0 0 4px %(line2)s, inset 0 0 0 1px %(line1_on)s;
        padding: 8px 6px 6px 6px;
    }
    .titlebar { background: transparent; }
    .cap-title { color: %(dim)s; }
    .cal-header, .note-bar {
        background-color: transparent; margin: 0 8px; padding: 8px 6px;
        border-bottom: 1px solid %(line3)s; box-shadow: inset 0 -1px 0 0 %(line2)s;
    }
    .note-bar { border-bottom: none; border-top: 1px solid %(line3)s; box-shadow: inset 0 1px 0 0 %(line2)s; }
    .cal-title { color: %(text)s; }
    .cal-subtitle { color: %(dim)s; }
    .pill, .pill.round {
        background-image: linear-gradient(to bottom, %(field_l)s, %(field)s); background-color: %(field)s;
        color: %(dim)s; border: 1px solid %(line3)s; box-shadow: inset 0 0 0 1px %(gline)s;
        padding: 3px 10px; font-weight: normal;
    }
    .pill:hover { color: %(acc_l)s; background-color: %(field_l)s; }
    .cal-weekday { color: %(dim)s; font-weight: normal; font-size: 12px; }
    .cal-weekday.we { color: %(acc_l)s; }
    .day, .ycard {
        background-color: transparent; margin: 2px;
        border: 1px solid %(gline)s; box-shadow: inset 0 0 0 1px %(gdark)s;
    }
    .day:hover, .ycard:hover { background-color: %(field)s; }
    .day .num { color: %(text)s; }
    .day.dim { background-color: transparent; border-color: %(line2)s; }
    .day.dim .num { color: %(dim)s; opacity: 0.45; }
    .day.we .num { color: %(acc_l)s; }
    .day.today, .day.today:hover { background-color: %(field_l)s; border-color: %(acc_d)s; }
    .day.today .num { color: %(acc_l)s; }
    .day.sel, .ycard.cur { border-color: %(acc)s; }
    .day .note { color: %(dim)s; }
    .day.today .note { color: %(text)s; }
    .dot, .day.today .dot { color: %(acc_l)s; }
    .ycard .mon { color: %(acc_l)s; }
    .ycard .wd { color: %(dim)s; }
    .ycard .d { color: %(text)s; }
    .ycard .d.today { background-color: %(field_l)s; color: %(acc_l)s; }
    .note-bar entry {
        background-color: %(field)s; color: %(text)s; border: 1px solid %(line3)s;
        box-shadow: inset 0 0 0 1px %(gline)s; outline: none;
    }
    .note-bar entry:focus-within { border-color: %(acc_d)s; }
    """ % c
    if style == "beta":
        return common + """
    .frame { background-color: %(bg)s; color: %(text)s; border: 1px solid %(frame)s; }
    .titlebar { background-color: %(bar)s; border-bottom: 1px solid %(line)s; }
    .cap-title { color: %(text)s; }
    .cal-header, .note-bar { background-color: %(bar)s; padding: 8px 12px; }
    .cal-header { border-bottom: 1px solid %(line)s; }
    .note-bar { border-top: 1px solid %(line)s; }
    .cal-title { color: %(text)s; }
    .cal-subtitle { color: %(dim)s; }
    .pill, .pill.round {
        background-color: %(field)s; color: %(text)s; border: 1px solid %(line_strong)s;
        padding: 3px 10px; font-weight: normal;
    }
    .pill:hover { background-color: %(acc)s; color: %(on_acc)s; }
    .cal-weekday { color: %(dim)s; font-weight: normal; font-size: 12px; }
    .cal-weekday.we { color: %(acc)s; }
    .day, .ycard { background-color: %(card)s; margin: 2px; border: 1px solid %(line)s; }
    .day:hover, .ycard:hover { background-color: %(field)s; }
    .day .num { color: %(text)s; }
    .day.dim { background-color: transparent; }
    .day.dim .num { color: %(dim)s; opacity: 0.5; }
    .day.we .num { color: %(acc)s; }
    .day.today, .day.today:hover { background-color: %(acc)s; border-color: %(acc)s; }
    .day.today .num, .day.today .note, .day.today .dot { color: %(on_acc)s; }
    .day.sel, .ycard.cur { border-color: %(acc)s; }
    .day .note { color: %(dim)s; }
    .dot { color: %(acc)s; }
    .ycard .mon { color: %(acc)s; }
    .ycard .wd { color: %(dim)s; }
    .ycard .d { color: %(text)s; }
    .ycard .d.today { background-color: %(acc)s; color: %(on_acc)s; }
    .note-bar entry { background-color: %(field)s; color: %(text)s; border: 1px solid %(line_strong)s; outline: none; }
    .note-bar entry:focus-within { border-color: %(acc)s; }
    """ % c
    return common + """
    .frame { background-color: %(bg)s; color: %(text)s; border: 3px solid %(st_mid)s; }
    .titlebar {
        background-image: linear-gradient(to bottom, %(st_top)s, %(st_mid)s, %(st_bot)s);
        border-bottom: 1px solid %(st_dark)s;
    }
    .cap-title { color: #ffffff; }
    .cal-header, .note-bar { background-color: %(bg)s; padding: 8px 10px; }
    .note-bar { border-top: 1px solid %(st_dark)s; }
    .cal-title { color: %(text)s; }
    .cal-subtitle { color: %(dim)s; }
    .pill, .pill.round {
        background-image: linear-gradient(to bottom, %(t_top)s, %(t_bot)s); color: %(text)s;
        border: 1px solid %(t_border)s; padding: 3px 10px; font-weight: normal;
    }
    .pill:hover { background-image: linear-gradient(to bottom, %(t_hover_top)s, %(t_top)s); }
    .cal-weekday { color: %(dim)s; font-weight: normal; font-size: 12px; }
    .cal-weekday.we { color: %(st_hi)s; }
    .day, .ycard { background-color: %(row)s; margin: 2px; border-left: 3px solid %(st_bot)s; }
    .day:hover, .ycard:hover { background-color: %(st_bot)s; }
    .day .num { color: %(text)s; }
    .day.dim { background-color: transparent; border-left-color: transparent; }
    .day.dim .num { color: %(dim)s; opacity: 0.45; }
    .day.we .num { color: %(st_hi)s; }
    .day.today, .day.today:hover { background-color: %(sel)s; border-left-color: %(st_top)s; }
    .day.today .num, .day.today .note, .day.today .dot { color: %(base)s; }
    .day.sel, .ycard.cur { box-shadow: inset 0 0 0 1px %(st_hi)s; }
    .day .note { color: %(dim)s; }
    .dot { color: %(st_hi)s; }
    .ycard .mon { color: %(st_hi)s; }
    .ycard .wd { color: %(dim)s; }
    .ycard .d { color: %(text)s; }
    .ycard .d.today { background-color: %(sel)s; color: %(base)s; }
    .note-bar entry { background-color: %(row)s; color: %(text)s; border: 1px solid %(st_dark)s; outline: none; }
    .note-bar entry:focus-within { border-color: %(st_hi)s; }
    """ % c


class CapButton(Gtk.DrawingArea):
    """Кнопка заголовка, нарисованная close_cap — тем же квадратом, что у всей системы."""

    def __init__(self, handler, glyph=None):
        super().__init__()
        self.glyph, self.hover = glyph, False
        self.style, self.C = "default", {}
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        m = Gtk.EventControllerMotion()
        m.connect("enter", lambda *_a: self._set_hover(True))
        m.connect("leave", lambda *_a: self._set_hover(False))
        self.add_controller(m)
        on_click(self, handler)

    def set_skin(self, style, C):
        self.style, self.C = style, C
        s = close_cap.size(style)
        self.set_content_width(s)
        self.set_content_height(s)
        self.queue_draw()

    def _set_hover(self, on):
        self.hover = on
        self.queue_draw()

    def _draw(self, _a, cr, _w, _h):
        if not self.C:
            return
        C, ink = self.C, None
        if self.glyph:                       # не крестик: под курсором — акцент, не красный
            if self.style == "default":
                C = dict(C, error=C["st_top"])
            ink = C.get("acc_l") or C.get("acc") or C.get("on_surface")
        close_cap.draw(cr, self.style, C, 0, 0, self.hover, glyph=self.glyph, hover_ink=ink)


WD_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WD_MICRO = ["M", "T", "W", "T", "F", "S", "S"]


def load_notes():
    try:
        with open(NOTES_PATH) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_notes(notes):
    os.makedirs(os.path.dirname(NOTES_PATH), exist_ok=True)
    tmp = NOTES_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(notes, f, ensure_ascii=False, indent=1)
    os.replace(tmp, NOTES_PATH)   # atomic, so a crash can't truncate the file


def on_click(widget, handler):
    """Make any widget respond to a left click."""
    g = Gtk.GestureClick()
    g.set_button(1)
    g.connect("released", lambda *_a: handler())
    widget.add_controller(g)
    return widget


class CalendarWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Calendar")
        self.add_css_class("calendar-app")
        self.set_default_size(880, 700)

        today = datetime.date.today()
        self.today = today
        self.y, self.m = today.year, today.month
        self.year_view = False
        self.selected = today
        self.notes = load_notes()

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("frame")
        self.set_child(root)
        root.append(self._titlebar())
        root.append(self._header())

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.body.set_vexpand(True)
        root.append(self.body)

        root.append(self._note_bar())

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)
        self._edge_resize()

        self.refresh()

    # Размер курсором (13.10.2026): niri с prefer-no-csd рамок для растягивания не
    # даёт, а у нашей шапки своих нет. Полоса EDGE px у края — курсор-стрелка, нажатие
    # отдаёт растягивание композитору (Gdk.Toplevel.begin_resize).
    EDGE = 6
    _EDGES = {
        (-1, -1): ("NORTH_WEST", "nw-resize"), (0, -1): ("NORTH", "n-resize"),
        (1, -1): ("NORTH_EAST", "ne-resize"), (-1, 0): ("WEST", "w-resize"),
        (1, 0): ("EAST", "e-resize"), (-1, 1): ("SOUTH_WEST", "sw-resize"),
        (0, 1): ("SOUTH", "s-resize"), (1, 1): ("SOUTH_EAST", "se-resize"),
    }

    def _edge_at(self, x, y):
        """Край/угол под точкой (x, y) окна или None. Углы — шире, по 2×EDGE."""
        if self.is_fullscreen() or self.is_maximized():
            return None
        w, h, e = self.get_width(), self.get_height(), self.EDGE
        c = 2 * e
        sx = -1 if x < e else 1 if x >= w - e else 0
        sy = -1 if y < e else 1 if y >= h - e else 0
        if sx and not sy:
            sy = -1 if y < c else 1 if y >= h - c else 0
        if sy and not sx:
            sx = -1 if x < c else 1 if x >= w - c else 0
        return self._EDGES.get((sx, sy))

    def _edge_resize(self):
        motion = Gtk.EventControllerMotion()
        motion.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        motion.connect("motion", self._edge_motion)
        motion.connect("leave", lambda *_a: self.set_cursor(None))
        self.add_controller(motion)
        click = Gtk.GestureClick(button=1)
        click.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        click.connect("pressed", self._edge_press)
        self.add_controller(click)

    def _edge_motion(self, _c, x, y):
        edge = self._edge_at(x, y)
        self.set_cursor(Gdk.Cursor.new_from_name(edge[1], None) if edge else None)

    def _edge_press(self, gesture, _n, x, y):
        edge = self._edge_at(x, y)
        if not edge:
            return
        gesture.set_state(Gtk.EventSequenceState.CLAIMED)
        ox, oy = self.get_surface_transform()
        self.get_surface().begin_resize(
            getattr(Gdk.SurfaceEdge, edge[0]), gesture.get_device(), 1,
            x + ox, y + oy, gesture.get_current_event_time())

    # ---------------------------------------------------------------- chrome
    def _titlebar(self):
        """Заголовок «Calendar.exe»: тянется мышью (WindowHandle), справа — «на весь экран»
        и «закрыть»."""
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=3)
        bar.add_css_class("titlebar")
        lbl = Gtk.Label(label="Calendar.exe", xalign=0)
        lbl.add_css_class("cap-title")
        lbl.set_hexpand(True)
        bar.append(lbl)
        self.max_btn = CapButton(self.toggle_fullscreen, glyph=close_cap.MAX_BMP)
        bar.append(self.max_btn)
        self.close_btn = CapButton(self.close)
        bar.append(self.close_btn)
        self.connect("notify::fullscreened", self._on_fullscreen)
        handle = Gtk.WindowHandle()
        handle.set_child(bar)
        return handle

    def apply_skin(self, style):
        C = cap_colors(style, skin_colors(style))
        self.max_btn.set_skin(style, C)
        self.close_btn.set_skin(style, C)

    def toggle_fullscreen(self):
        if self.is_fullscreen():
            self.unfullscreen()
        else:
            self.fullscreen()

    def _on_fullscreen(self, *_a):
        self.max_btn.glyph = close_cap.RESTORE_BMP if self.is_fullscreen() else close_cap.MAX_BMP
        self.max_btn.queue_draw()

    def _header(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        bar.add_css_class("cal-header")

        self.prev_btn = self._pill("‹", self.go_prev, round_=True)
        bar.append(self.prev_btn)
        self.next_btn = self._pill("›", self.go_next, round_=True)
        bar.append(self.next_btn)

        titles = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        titles.set_hexpand(True)
        titles.set_margin_start(8)
        self.title_lbl = Gtk.Label(xalign=0)
        self.title_lbl.add_css_class("cal-title")
        titles.append(self.title_lbl)
        self.sub_lbl = Gtk.Label(xalign=0)
        self.sub_lbl.add_css_class("cal-subtitle")
        titles.append(self.sub_lbl)
        bar.append(titles)

        bar.append(self._pill("Today", self.go_today))
        self.toggle_btn = self._pill("Year", self.toggle_view)
        bar.append(self.toggle_btn)
        return bar

    def _pill(self, label, handler, round_=False):
        lbl = Gtk.Label(label=label)
        box = Gtk.Box()
        box.append(lbl)
        box.add_css_class("pill")
        if round_:
            box.add_css_class("round")
        box.set_valign(Gtk.Align.CENTER)
        return on_click(box, handler)

    def _note_bar(self):
        bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        bar.add_css_class("note-bar")
        self.note_lbl = Gtk.Label(xalign=0)
        self.note_lbl.add_css_class("cal-subtitle")
        bar.append(self.note_lbl)
        self.note_entry = Gtk.Entry()
        self.note_entry.set_hexpand(True)
        self.note_entry.set_placeholder_text("Note for this day — press Enter to save")
        self.note_entry.connect("activate", self._save_note)
        bar.append(self.note_entry)
        return bar

    # ------------------------------------------------------------ navigation
    def go_prev(self):
        if self.year_view:
            self.y -= 1
        else:
            self.m -= 1
            if self.m < 1:
                self.m, self.y = 12, self.y - 1
        self.refresh()

    def go_next(self):
        if self.year_view:
            self.y += 1
        else:
            self.m += 1
            if self.m > 12:
                self.m, self.y = 1, self.y + 1
        self.refresh()

    def go_today(self):
        self.y, self.m = self.today.year, self.today.month
        self.year_view = False
        self.toggle_btn.get_first_child().set_label("Year")
        self.select(self.today)

    def toggle_view(self):
        self.year_view = not self.year_view
        self.toggle_btn.get_first_child().set_label("Month" if self.year_view else "Year")
        self.refresh()

    def open_month(self, month):
        """Year view: clicking a month card drills into it."""
        self.m = month
        self.year_view = False
        self.toggle_btn.get_first_child().set_label("Year")
        self.refresh()

    def select(self, d):
        self.selected = d
        if d.month != self.m or d.year != self.y:
            self.y, self.m = d.year, d.month
        self.refresh()

    def _on_key(self, _c, keyval, _kc, _st):
        name = Gdk.keyval_name(keyval)
        if self.note_entry.has_focus() and name not in ("Escape",):
            return False
        if name == "Left":
            self.go_prev()
        elif name == "Right":
            self.go_next()
        elif name == "t":
            self.go_today()
        elif name == "y":
            self.toggle_view()
        elif name in ("F11", "f"):
            self.toggle_fullscreen()
        elif name in ("Escape", "q"):
            self.close()
        else:
            return False
        return True

    # ---------------------------------------------------------------- notes
    def _save_note(self, entry):
        text = entry.get_text().strip()
        key = self.selected.isoformat()
        if text:
            self.notes[key] = text
        else:
            self.notes.pop(key, None)
        save_notes(self.notes)
        self.refresh()

    def _sync_note_bar(self):
        d = self.selected
        self.note_lbl.set_text(d.strftime("%a %d %b"))
        self.note_entry.set_text(self.notes.get(d.isoformat(), ""))

    # ------------------------------------------------------------- rendering
    def refresh(self):
        if self.year_view:
            self.title_lbl.set_text(str(self.y))
            self.sub_lbl.set_text("click a month to open it")
            child = self._build_year()
        else:
            self.title_lbl.set_text(f"{calendar.month_name[self.m]} {self.y}")
            n = len(self.notes)
            self.sub_lbl.set_text(f"{n} note{'s' if n != 1 else ''} saved" if n else "click a day to add a note")
            child = self._build_month()

        while (old := self.body.get_first_child()) is not None:
            self.body.remove(old)
        self.body.append(child)
        self._sync_note_bar()

    def _build_month(self):
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       margin_start=16, margin_end=16,
                       margin_top=10, margin_bottom=6)

        head = Gtk.Grid(column_homogeneous=True, hexpand=True)
        for i, wd in enumerate(WD_SHORT):
            lbl = Gtk.Label(label=wd)
            lbl.add_css_class("cal-weekday")
            if i >= 5:
                lbl.add_css_class("we")
            head.attach(lbl, i, 0, 1, 1)
        wrap.append(head)

        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                        hexpand=True, vexpand=True)
        wrap.append(grid)

        for r, week in enumerate(calendar.Calendar(firstweekday=0)
                                 .monthdatescalendar(self.y, self.m)):
            for c, d in enumerate(week):
                grid.attach(self._day_cell(d, c), c, r, 1, 1)
        return wrap

    def _day_cell(self, d, col):
        cell = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        cell.add_css_class("day")
        cell.set_hexpand(True)
        cell.set_vexpand(True)

        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        num = Gtk.Label(label=str(d.day), xalign=0)
        num.add_css_class("num")
        num.set_hexpand(True)
        top.append(num)

        note = self.notes.get(d.isoformat())
        if note:
            dot = Gtk.Label(label="•")
            dot.add_css_class("dot")
            top.append(dot)
        cell.append(top)

        if note:
            nl = Gtk.Label(label=note, xalign=0)
            nl.add_css_class("note")
            nl.set_ellipsize(Pango.EllipsizeMode.END)
            nl.set_max_width_chars(1)   # let it shrink; ellipsis does the rest
            cell.append(nl)

        if d.month != self.m:
            cell.add_css_class("dim")
        if col >= 5:
            cell.add_css_class("we")
        if d == self.today:
            cell.add_css_class("today")
        if d == self.selected:
            cell.add_css_class("sel")

        return on_click(cell, lambda dd=d: self.select(dd))

    def _build_year(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        margin_start=12, margin_end=12,
                        margin_top=8, margin_bottom=8)
        grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                        hexpand=True, vexpand=True)
        outer.append(grid)

        cal = calendar.Calendar(firstweekday=0)
        for m in range(1, 13):
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            card.add_css_class("ycard")
            if (self.y, m) == (self.today.year, self.today.month):
                card.add_css_class("cur")

            title = Gtk.Label(label=calendar.month_name[m], xalign=0)
            title.add_css_class("mon")
            card.append(title)

            g = Gtk.Grid(column_homogeneous=True, hexpand=True, vexpand=True)
            for i, w in enumerate(WD_MICRO):
                lbl = Gtk.Label(label=w)
                lbl.add_css_class("wd")
                g.attach(lbl, i, 0, 1, 1)

            for r, week in enumerate(cal.monthdatescalendar(self.y, m), start=1):
                for c, d in enumerate(week):
                    lbl = Gtk.Label(label=str(d.day))
                    lbl.add_css_class("d")
                    if d.month != m:
                        lbl.add_css_class("dim")
                    elif d == self.today:
                        lbl.add_css_class("today")
                    lbl.set_hexpand(True)
                    g.attach(lbl, c, r, 1, 1)
            card.append(g)

            on_click(card, lambda mm=m: self.open_month(mm))
            grid.attach(card, (m - 1) % 4, (m - 1) // 4, 1, 1)
        return outer


class CalendarApp(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def _float_self(self):
        """Ask Hyprland to float this window, sized and centred.

        A windowrule on `class:` does not fire here: GTK4 sets the Wayland
        app_id after the surface is mapped, so the rule sees an empty class and
        never matches. Matching on our own pid always works.
        """
        pid = os.getpid()
        if os.environ.get("NIRI_SOCKET") and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
            return False   # в niri окно делает плавающим правило в config.kdl
        for cmd in (f'hl.dsp.window.float({{ window = "pid:{pid}", action = "on" }})',
                    f'hl.dsp.window.resize({{ window = "pid:{pid}", x = 900, y = 720 }})',
                    f'hl.dsp.window.center({{ window = "pid:{pid}" }})'):
            subprocess.run(["hyprctl", "dispatch", cmd],
                           capture_output=True, timeout=3)
        return False   # one-shot timeout

    def apply_style(self):
        """Вид стиля монитора — поверх базового CSS; перечитывается при каждом открытии."""
        style = read_style()
        if getattr(self, "skin", None) is None:
            self.skin = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self.skin,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.skin.load_from_string(skin_css(style, skin_colors(style)))
        if self.win is not None:
            self.win.apply_skin(style)

    def do_activate(self):
        if getattr(self, "base_css", None) is None:
            self.base_css = Gtk.CssProvider()
            self.base_css.load_from_string(CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), self.base_css,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if self.win is None:
            self.win = CalendarWindow(self)
        else:
            # Re-opened from the bar: pick up notes written meanwhile and any
            # new wallpaper palette.
            self.win.notes = load_notes()
            self.win.refresh()
        self.apply_style()
        self.win.present()
        # Runs once the surface exists, so Hyprland has something to act on.
        GLib.timeout_add(120, self._float_self)


if __name__ == "__main__":
    CalendarApp().run(None)
