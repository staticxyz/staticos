#!/usr/bin/env python3
"""Настоящая заморозка экрана для выделения области. 29.09.2026.

    freeze_screen.py СНИМОК.png

Показывает заранее сделанный снимок всего стола поверх каждого монитора, пока
его не завершат (kill). Под ним идёт выделение (slurp), а вырезается кусок из
того же снимка — так на Shift+Print и Super+Print кадр застывает в момент
нажатия, как в обычном Print у niri.

Раньше «заморозку» делал hyprpicker -r -z. Под niri он экран НЕ замораживал:
слой вставал, мышь и клавиатура уходили ему, а изображение под слоем оставалось
живым — пользователь заметил, что при снимке всё продолжает двигаться. К тому же
hyprpicker забирал клавиатуру целиком, и выделению поверх доставалась только
мышь: первый Escape закрывал заморозку, второй — выделение.

Здесь клавиатура слою НЕ нужна (KeyboardMode.NONE): весь ввод получает
выделение, и одного Escape хватает. Мышь слой перехватывает — это и держит
ленту niri на месте, пока водишь по экрану.

Каждый монитор получает свой кусок снимка: геометрия мониторов GDK — в тех же
логических координатах, что и у grim и у slurp.
"""
import os
import signal
import sys
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell  # noqa: E402


def main():
    if len(sys.argv) < 2:
        print(__doc__, file=sys.stderr)
        return 1
    # Снимок делается параллельно с запуском этого окна (freeze_lib.sh) и
    # появляется под своим именем, когда уже дописан. Ждём до 3 с.
    for _ in range(300):
        if os.path.exists(sys.argv[1]):
            break
        time.sleep(0.01)
    try:
        shot = GdkPixbuf.Pixbuf.new_from_file(sys.argv[1])
    except GLib.Error as e:
        print("freeze_screen: не открыть снимок: %s" % e, file=sys.stderr)
        return 1

    display = Gdk.Display.get_default()
    windows = []
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        g = mon.get_geometry()
        # Кусок снимка под этот монитор; на краях не выходим за снимок.
        x = max(0, min(g.x, shot.get_width() - 1))
        y = max(0, min(g.y, shot.get_height() - 1))
        w = max(1, min(g.width, shot.get_width() - x))
        h = max(1, min(g.height, shot.get_height() - y))
        part = shot.new_subpixbuf(x, y, w, h).copy()

        win = Gtk.Window()
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "jarvis-freeze")
        GtkLayerShell.set_monitor(win, mon)
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, edge, True)
        GtkLayerShell.set_exclusive_zone(win, -1)      # поверх бара тоже
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        win.add(Gtk.Image.new_from_pixbuf(part))
        win.show_all()
        windows.append(win)

    # kill от вызывающего скрипта — обычный и единственный способ закрыться
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, Gtk.main_quit)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, Gtk.main_quit)
    # Страховка: если скрипт-хозяин упал и не убрал заморозку — через две минуты
    # она уходит сама, иначе экран остался бы замёрзшим.
    GLib.timeout_add_seconds(120, Gtk.main_quit)
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
