#!/usr/bin/env python3
"""Снимок из буфера — в плавающее окно его же размера. 29.09.2026.

    pin_shot.py          показать картинку из буфера обмена

Сценарий пользователя: Print → выделил область → Ctrl+Super+V → рядом всплывает
окно с тем, что снято. Раньше, чтобы просто посмотреть снимок, его вставляли в
Pinta. Print у niri и так кладёт снимок в буфер, поэтому здесь берётся ЛЮБАЯ
картинка из буфера — хоть с Print, хоть с Super+Print, хоть скопированная из
браузера.

Размер окна = размер картинки, один к одному: выделил маленькую область —
маленькое окно, большую — большое (его прямое требование). Только если картинка
больше экрана, она ужимается до 90 % экрана, иначе окно было бы не закрыть.
Дальше окно тянется, как любое другое (Super + правая кнопка, края), а снимок
масштабируется под него с сохранением пропорций. Сначала окно было жёсткого
размера — пользователь попросил, чтобы тянулось (29.09.2026).

Управление:
    Escape, щелчок колёсиком, q   закрыть
    левая кнопка + тяни           двигать окно
    двойной щелчок                открыть в полном просмотрщике (xdg-open)

Окно плавающее и без заголовка — это правило niri по app-id «jarvis-pin»
(~/.config/niri/cfg/window-rules.kdl). Окон можно открыть сколько угодно.
"""
import os
import subprocess
import sys
import tempfile

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk  # noqa: E402

APP_ID = "jarvis-pin"
MAX_SHARE = 0.90          # доля экрана, больше которой картинка ужимается


def clipboard_png():
    """Картинка из буфера обмена как PNG-байты, или None."""
    try:
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True,
                               text=True, timeout=3).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return None
    want = next((t for t in ("image/png", "image/jpeg", "image/webp", "image/bmp")
                 if t in types), None)
    if want is None:
        return None
    try:
        return subprocess.run(["wl-paste", "--type", want], capture_output=True,
                              timeout=5).stdout or None
    except (OSError, subprocess.SubprocessError):
        return None


def notify(text):
    subprocess.run(["notify-send", "-a", "Снимок", "Снимок", text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    data = clipboard_png()
    if not data:
        notify("В буфере нет картинки — сначала снимите область через Print")
        return 1

    loader = GdkPixbuf.PixbufLoader()
    try:
        loader.write(data)
        loader.close()
    except GLib.Error:
        notify("Картинку в буфере не прочитать")
        return 1
    pix = loader.get_pixbuf()
    w, h = pix.get_width(), pix.get_height()

    # Картинка больше экрана — ужать, сохранив пропорции.
    mon = Gdk.Display.get_default().get_monitor_at_point(0, 0)
    display = Gdk.Display.get_default()
    seat = display.get_default_seat()
    if seat is not None and seat.get_pointer() is not None:
        _, px, py = seat.get_pointer().get_position()
        mon = display.get_monitor_at_point(px, py) or mon
    area = mon.get_workarea()
    k = min(1.0, area.width * MAX_SHARE / w, area.height * MAX_SHARE / h)
    if k < 1.0:
        w, h = max(1, int(w * k)), max(1, int(h * k))
    # Сам pixbuf НЕ ужимаем: при растягивании окна рисуем из исходника, чтобы
    # увеличенный снимок не мылился.

    # Исходник — во временный файл: пригодится для полного просмотра.
    src = tempfile.NamedTemporaryFile(prefix="pin-", suffix=".png", delete=False)
    src.write(data)
    src.close()

    win = Gtk.Window(title="Снимок")
    win.set_decorated(False)
    win.set_default_size(w, h)
    area_w = Gtk.DrawingArea()
    area_w.set_size_request(40, 40)          # меньше — уже не разглядеть

    def on_draw(widget, cr):
        aw, ah = widget.get_allocated_width(), widget.get_allocated_height()
        pw, ph = pix.get_width(), pix.get_height()
        s = min(aw / pw, ah / ph)
        # Поля, если пропорции окна и снимка разошлись, — чёрные.
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        cr.translate((aw - pw * s) / 2, (ah - ph * s) / 2)
        cr.scale(s, s)
        Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_GOOD if s < 1 else cairo.FILTER_BILINEAR)
        cr.paint()
        return True

    area_w.connect("draw", on_draw)
    box = Gtk.EventBox()
    box.add(area_w)
    win.add(box)

    def on_key(_w, ev):
        if ev.keyval in (Gdk.KEY_Escape, Gdk.KEY_q, Gdk.KEY_Q):
            win.destroy()
        return False

    viewed = []                       # открывали ли полный просмотр

    def on_button(_w, ev):
        if ev.button == 2:                                  # колёсико — закрыть
            win.destroy()
        elif ev.button == 1 and ev.type == Gdk.EventType._2BUTTON_PRESS:
            viewed.append(True)
            subprocess.Popen(["xdg-open", src.name],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif ev.button == 1:
            win.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        return True

    win.connect("key-press-event", on_key)
    box.connect("button-press-event", on_button)
    def on_destroy(*_):
        # Временный файл нужен только открытому просмотрщику. Не открывали —
        # удаляем сразу; открывали — оставляем в /tmp (его чистит systemd), иначе
        # просмотрщик получил бы исчезнувший файл.
        if not viewed:
            _drop(src.name)
        Gtk.main_quit()

    win.connect("destroy", on_destroy)
    win.show_all()
    Gtk.main()
    return 0


def _drop(path):
    try:
        os.unlink(path)
    except OSError:
        pass
    return False


if __name__ == "__main__":
    GLib.set_prgname(APP_ID)          # app-id окна: по нему niri делает его плавающим
    sys.exit(main())
