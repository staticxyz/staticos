#!/usr/bin/env python3
"""Выбор аватара для экрана блокировки.

Показывает картинки из ~/Pictures/avatars сеткой. По щелчку картинка
обрезается по центру в квадрат, уменьшается и кладётся в ~/.cache/avatar.png —
именно этот путь читает hyprlock.

Обрезка по центру, а не растяжение: лица на аватарках обычно в середине, а
растянутая в квадрат вертикальная картинка выглядит сдавленной.

Текущая аватарка обведена рамкой цвета акцента. Какая стоит, запоминается в
~/.cache/avatar-source при выборе; если этой записи нет (аватар поставили
раньше), картинка находится сравнением уменьшенных копий с ~/.cache/avatar.png.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402

import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib

SRC_DIR = os.path.expanduser("~/Pictures/avatars")
OUT = os.path.expanduser("~/.cache/avatar.png")
SOURCE = os.path.expanduser("~/.cache/avatar-source")
SIZE = 512
THUMB = 128
PROBE = 16          # сторона копии для сравнения с ~/.cache/avatar.png
EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

CSS = b"""
button.avatar { padding: 3px; border: 4px solid transparent; border-radius: 10px; }
button.avatar.current { border-color: @accent_color;
                        box-shadow: 0 0 12px 2px alpha(@accent_color, 0.55); }
"""


def crop_square(path, size):
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    w, h = pb.get_width(), pb.get_height()
    side = min(w, h)
    sub = GdkPixbuf.Pixbuf.new_subpixbuf(pb, (w - side) // 2, (h - side) // 2,
                                         side, side)
    return sub.scale_simple(size, size, GdkPixbuf.InterpType.BILINEAR)


def probe(pb):
    """Пиксели RGB уменьшенной до PROBE копии — для сравнения картинок."""
    small = pb.scale_simple(PROBE, PROBE, GdkPixbuf.InterpType.BILINEAR)
    data, stride, n = small.read_pixel_bytes().get_data(), small.get_rowstride(), small.get_n_channels()
    return [data[y * stride + x * n + c] for y in range(PROBE) for x in range(PROBE) for c in range(3)]


def current_source(probes):
    """Какая картинка из папки стоит сейчас: по записи, иначе по сходству."""
    try:
        path = open(SOURCE).read().strip()
        if path in probes:
            return path
    except OSError:
        pass
    try:
        ref = probe(GdkPixbuf.Pixbuf.new_from_file(OUT))
    except GLib.Error:
        return None
    best, best_d = None, None
    for path, p in probes.items():
        d = sum(abs(a - b) for a, b in zip(ref, p)) / len(ref)
        if best_d is None or d < best_d:
            best, best_d = path, d
    return best if best_d is not None and best_d < 12 else None


class Picker(Gtk.Application):
    def __init__(self):
        super().__init__(application_id="dev.static.avatarpicker")

    def do_activate(self):
        win = Gtk.ApplicationWindow(application=self, title="Аватар")
        win.set_default_size(680, 520)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(12); root.set_margin_bottom(12)
        root.set_margin_start(12); root.set_margin_end(12)

        files = sorted(f for f in os.listdir(SRC_DIR)
                       if f.lower().endswith(EXTS)) if os.path.isdir(SRC_DIR) else []

        if not files:
            root.append(Gtk.Label(label="Положи картинки в ~/Pictures/avatars"))
        else:
            self.status = Gtk.Label(label="%d картинок — щёлкни, чтобы поставить" % len(files))
            self.status.set_xalign(0)
            root.append(self.status)

            css = Gtk.CssProvider()
            css.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

            flow = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE,
                               max_children_per_line=5, row_spacing=10,
                               column_spacing=10)
            self.buttons, probes = {}, {}
            for name in files:
                path = os.path.join(SRC_DIR, name)
                try:
                    pb = crop_square(path, THUMB)
                except GLib.Error:
                    continue
                probes[path] = probe(pb)
                img = Gtk.Picture.new_for_pixbuf(pb)
                img.set_size_request(THUMB, THUMB)
                btn = Gtk.Button()
                btn.add_css_class("avatar")
                btn.set_child(img)
                btn.connect("clicked", self.on_pick, path, name)
                flow.append(btn)
                self.buttons[path] = btn
            self.current = None
            self.mark(current_source(probes))

            sc = Gtk.ScrolledWindow(vexpand=True)
            sc.set_child(flow)
            root.append(sc)

        win.set_child(root)
        # Плавающим окно просит себя само: правило по классу не срабатывает,
        # GTK4 выставляет app_id уже после появления окна.
        GLib.timeout_add(150, self._float_self)
        win.present()

    def _float_self(self):
        """Попросить композитор сделать это окно плавающим.

        В Niri своей команды «сделай плавающим вон то окно» нет — есть
        «сделай плавающим текущее». Поэтому сначала переводим фокус на себя
        по PID, потом переключаем (21.09.2026).
        """
        me = [w for w in wm.windows() if w.get("pid") == os.getpid()]
        if not me:
            return False
        if wm.which() == "niri":
            wm.focus(me[0])
            subprocess.run(["niri", "msg", "action", "move-window-to-floating"],
                           capture_output=True)
        else:
            subprocess.run(["hyprctl", "dispatch",
                            'hl.dsp.window.float({ window = "address:%s", action = "set" })' % me[0]["id"]],
                           capture_output=True)
        return False

    def mark(self, path):
        """Перенести рамку на кнопку текущей аватарки."""
        if self.current in self.buttons:
            self.buttons[self.current].remove_css_class("current")
        self.current = path
        if path in self.buttons:
            self.buttons[path].add_css_class("current")

    def on_pick(self, _btn, path, name):
        try:
            crop_square(path, SIZE).savev(OUT, "png", [], [])
            with open(SOURCE, "w") as f:
                f.write(path)
            self.mark(path)
            self.status.set_label("Поставлено: %s" % name)
        except (GLib.Error, OSError) as e:
            self.status.set_label("Не вышло: %s" % getattr(e, "message", e))


if __name__ == "__main__":
    sys.exit(Picker().run([]))
