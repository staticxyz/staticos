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
"""
import calendar
import datetime
import json
import os
import subprocess

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gio, Gdk, GLib, Pango  # noqa: E402

APP_ID = "dev.static.calendar"
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
        self.set_child(root)
        root.append(self._header())

        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.body.set_vexpand(True)
        root.append(self.body)

        root.append(self._note_bar())

        key = Gtk.EventControllerKey()
        key.connect("key-pressed", self._on_key)
        self.add_controller(key)

        self.refresh()

    # ---------------------------------------------------------------- chrome
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

    def do_activate(self):
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        if self.win is None:
            self.win = CalendarWindow(self)
        else:
            # Re-opened from the bar: pick up notes written meanwhile and any
            # new wallpaper palette.
            self.win.notes = load_notes()
            self.win.refresh()
        self.win.present()
        # Runs once the surface exists, so Hyprland has something to act on.
        GLib.timeout_add(120, self._float_self)


if __name__ == "__main__":
    CalendarApp().run(None)
