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
    левая кнопка + тяни           двигать окно (у края — растянуть)
    колёсико вверх/вниз           крупнее/мельче, пропорции снимка (29.10.2026)
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

    # Свои края для растягивания (29.10.2026, просьба: «не могу изменять размер по вертикали,
    # меняется только по горизонтали»): у окна нет рамки, а Mod+ПКМ niri выбирает сторону по
    # трети окна — у низкого снимка (строка текста) в верхнюю/нижнюю треть почти не попасть.
    EDGE = 8
    EDGES = {"n": Gdk.WindowEdge.NORTH, "s": Gdk.WindowEdge.SOUTH, "e": Gdk.WindowEdge.EAST,
             "w": Gdk.WindowEdge.WEST, "ne": Gdk.WindowEdge.NORTH_EAST, "nw": Gdk.WindowEdge.NORTH_WEST,
             "se": Gdk.WindowEdge.SOUTH_EAST, "sw": Gdk.WindowEdge.SOUTH_WEST}
    CURSORS = {"n": "n-resize", "s": "s-resize", "e": "e-resize", "w": "w-resize",
               "ne": "ne-resize", "nw": "nw-resize", "se": "se-resize", "sw": "sw-resize"}

    def edge_at(x, y):
        aw, ah = box.get_allocated_width(), box.get_allocated_height()
        m = min(EDGE, max(3, ah // 4), max(3, aw // 4))
        v = "n" if y < m else "s" if y >= ah - m else ""
        hz = "w" if x < m else "e" if x >= aw - m else ""
        return (v + hz) or None

    cur = [None]

    def on_motion(_w, ev):
        e = edge_at(ev.x, ev.y)
        if e != cur[0]:
            cur[0] = e
            gw = box.get_window()
            if gw is not None:
                gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), CURSORS[e]) if e else None)
        return False

    def on_button(_w, ev):
        e = edge_at(ev.x, ev.y) if ev.button == 1 and ev.type == Gdk.EventType.BUTTON_PRESS else None
        if e:
            win.begin_resize_drag(EDGES[e], ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        elif ev.button == 2:                                  # колёсико — закрыть
            win.destroy()
        elif ev.button == 1 and ev.type == Gdk.EventType._2BUTTON_PRESS:
            viewed.append(True)
            subprocess.Popen(["xdg-open", src.name],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif ev.button == 1:
            win.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        return True

    # Колёсико — масштаб окна с пропорциями снимка (29.10.2026, просьба: «не могу через
    # super+мышкой вниз или вверх»). Mod+ПКМ niri берёт сторону по трети окна, вертикаль — только
    # из верхней/нижней трети; у низкого снимка это полоска в 10–15 px. Размер ставит niri по
    # своему номеру окна (плавающее окно GTK само себя под Wayland не растянет).
    zoom = {"id": None, "w": 0}

    def on_scroll(_w, ev):
        d = {Gdk.ScrollDirection.UP: 1, Gdk.ScrollDirection.DOWN: -1}.get(ev.direction)
        if d is None and ev.direction == Gdk.ScrollDirection.SMOOTH:
            dy = ev.get_scroll_deltas()[2]
            d = -1 if dy > 0 else 1 if dy < 0 else None
        if d is None or not os.environ.get("NIRI_SOCKET"):
            return False
        if zoom["id"] is None:
            try:
                import json
                out = subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True,
                                     text=True, timeout=2).stdout
                zoom["id"] = next(w["id"] for w in json.loads(out) if w.get("pid") == os.getpid()
                                  and w.get("is_focused")) if out else None
            except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
                return False
            if zoom["id"] is None:
                return False
        pw, ph = pix.get_width(), pix.get_height()
        aw = zoom["w"] or box.get_allocated_width()
        nw = max(40, int(aw * (1.1 if d > 0 else 1 / 1.1)))
        nh = max(40, round(nw * ph / pw))
        zoom["w"] = nw
        GLib.timeout_add(400, lambda: zoom.update(w=0) or False)   # следующий шаг — от нового размера
        wid = str(zoom["id"])
        subprocess.Popen(["sh", "-c", 'niri msg action set-window-width --id "$0" "$1"; '
                          'niri msg action set-window-height --id "$0" "$2"', wid, str(nw), str(nh)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    win.connect("key-press-event", on_key)
    box.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK
                   | Gdk.EventMask.SMOOTH_SCROLL_MASK)
    box.connect("scroll-event", on_scroll)
    box.connect("motion-notify-event", on_motion)
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
