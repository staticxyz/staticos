#!/usr/bin/env python3
"""Лупа staticOS — Super+Alt+колесо (03.11.2026).

Просьба: «нажимаю на бинд и скроллю — эта область как лупа увеличивается на экране, но при
этом можно двигаться курсором, и область должна оставаться на месте; увеличенную область
можно двигать, нажав бинд со скроллом в другое место». То есть как зум в просмотрщике
фото: увеличивается картинка экрана вокруг курсора, картинка стоит, курсор ходит свободно.

Как устроено: первый щелчок колеса снимает экран монитора в фокусе (grim, кадр
замирает — видео под лупой не идёт) и кладёт его слоем поверх всего, один в один. Дальше
каждый щелчок увеличивает/уменьшает вокруг курсора: точка под курсором остаётся под ним.
    Super+Alt+колесо        увеличить / уменьшить вокруг курсора (бинд niri → сюда)
    колесо (внутри лупы)    то же, без Super+Alt
    левая кнопка + тянуть   сдвинуть увеличенное
    Esc, q, правая кнопка   закрыть; уменьшили до ×1 — закрывается сама

    magnifier.py in | out | close     команда лупе (нет лупы — in её открывает)

Запущенная лупа слушает канал $XDG_RUNTIME_DIR/jarvis-magnifier.fifo; повторный вызов с
бинда только пишет туда строку — без GTK, ~20 мс. Положение курсора лупа знает по своим
событиям мыши; niri скрывает курсор через 3 с без движения и тогда слою его не сообщает —
пока курсор не пришёл, увеличение идёт от центра экрана.
"""
import fcntl
import json
import os
import subprocess
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
FIFO = os.path.join(RUN, "jarvis-magnifier.fifo")
LOCK = os.path.join(RUN, "jarvis-magnifier.lock")
CMDS = ("in", "out", "close")


def send(cmd):
    """В канал запущенной лупы. False — читателя нет (лупа не запущена)."""
    try:
        fd = os.open(FIFO, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:                    # ENXIO — канал без читателя, ENOENT — канала нет
        return False
    try:
        os.write(fd, (cmd + "\n").encode())
    finally:
        os.close(fd)
    return True


cmd = sys.argv[1] if len(sys.argv) > 1 else ""
if cmd not in CMDS:
    print(__doc__)
    sys.exit(0)
if send(cmd):
    sys.exit(0)
if cmd != "in":
    sys.exit(0)                        # нечего уменьшать/закрывать
_lock = os.open(LOCK, os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    # лупа как раз открывается (быстрые щелчки колеса) — дождаться её канала
    for _ in range(40):
        time.sleep(0.025)
        if send(cmd):
            break
    sys.exit(0)

import cairo  # noqa: E402
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

STEP = 1.25            # множитель на щелчок колеса
Z_MAX = 16.0
SMOOTH = 0.32          # доля пути к цели за кадр (≈8 мс)
FAMILY = "JetBrainsMono Nerd Font"


def niri_json(*args):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", *args], capture_output=True,
                                         timeout=1).stdout or b"null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def grab(out):
    """Экран выхода целиком, без курсора → cairo-поверхность (ppm: grim ~30 мс)."""
    data = subprocess.run(["grim", "-t", "ppm", "-o", out, "-"], capture_output=True,
                          timeout=2).stdout
    loader = GdkPixbuf.PixbufLoader.new_with_type("pnm")
    loader.write(data)
    loader.close()
    return Gdk.cairo_surface_create_from_pixbuf(loader.get_pixbuf(), 1, None)


class Loupe:
    def __init__(self):
        fo = niri_json("focused-output") or {}
        self.out = fo.get("name") or ""
        lg = fo.get("logical") or {}
        self.lx, self.ly = lg.get("x", 0), lg.get("y", 0)
        self.W, self.H = lg.get("width") or 1920, lg.get("height") or 1080
        self.img = grab(self.out)
        self.z, self.ox, self.oy = 1.0, 0.0, 0.0            # что на экране сейчас
        self.zt, self.oxt, self.oyt = 1.0, 0.0, 0.0         # куда едем
        self.anchor = None                                   # (экран x,y; картинка x,y) зума
        self.ptr = None                                      # курсор в координатах слоя
        self.pending = []                                    # команды до прихода курсора
        self.drag = None
        self.acc = 0.0
        self.closing = False
        self.tick_id = None
        self.badge_until = 0
        self.started = time.monotonic()

        win = self.win = Gtk.Window()
        win.set_decorated(False)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "jarvis-magnifier")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, e, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        disp = Gdk.Display.get_default()
        for i in range(disp.get_n_monitors()):
            g = disp.get_monitor(i).get_geometry()
            if (g.x, g.y) == (self.lx, self.ly):
                GtkLayerShell.set_monitor(win, disp.get_monitor(i))
                break
        win.set_app_paintable(True)
        win.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                       | Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                       | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        win.connect("draw", self.on_draw)
        win.connect("enter-notify-event", self.on_pointer)
        win.connect("motion-notify-event", self.on_motion)
        win.connect("button-press-event", self.on_press)
        win.connect("button-release-event", self.on_release)
        win.connect("scroll-event", self.on_scroll)
        win.connect("key-press-event", self.on_key)
        win.connect("destroy", Gtk.main_quit)

        try:
            os.unlink(FIFO)
        except OSError:
            pass
        os.mkfifo(FIFO, 0o600)
        self.fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)  # RDWR: EOF не приходит никогда
        self.buf = b""
        GLib.io_add_watch(self.fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN, self.on_fifo)
        win.show()
        GLib.timeout_add(450, self.flush_pending)            # курсор так и не пришёл

    # ── команды ──
    def on_fifo(self, fd, _cond):
        try:
            self.buf += os.read(fd, 4096)
        except BlockingIOError:
            return True
        *lines, self.buf = self.buf.split(b"\n")
        for ln in lines:
            self.command(ln.decode(errors="replace").strip())
        return True

    def command(self, c):
        if c == "close":
            self.close()
        elif c in ("in", "out"):
            if self.ptr is None and time.monotonic() - self.started < 0.45:
                self.pending.append(c)
            else:
                self.zoom(c)

    def flush_pending(self):
        p, self.pending = self.pending, []
        for c in p:
            self.zoom(c)
        return False

    def zoom(self, c, at=None):
        if self.closing:
            return
        z = self.zt * (STEP if c == "in" else 1 / STEP)
        self.zoom_to(z, at or self.ptr or (self.W / 2, self.H / 2))

    def zoom_to(self, z, at):
        """Как в просмотрщике фото: точка картинки под `at` остаётся под ним."""
        ax, ay = at
        # точка картинки под курсором — по тому, куда уже едем (быстрые щелчки не дрожат)
        px, py = self.oxt + ax / self.zt, self.oyt + ay / self.zt
        if z <= 1.0001:
            self.close()
            return
        z = min(Z_MAX, z)
        self.zt = z
        self.oxt, self.oyt = self.clamp(px - ax / z, py - ay / z, z)
        self.anchor = (ax, ay, px, py)
        self.badge_until = time.monotonic() + 1.2
        self.animate()

    def clamp(self, ox, oy, z):
        return (min(max(ox, 0.0), self.W - self.W / z), min(max(oy, 0.0), self.H - self.H / z))

    def close(self):
        if self.closing:
            return
        self.closing = True
        self.zt, self.oxt, self.oyt = 1.0, 0.0, 0.0
        self.anchor = None
        self.animate()

    # ── анимация ──
    def animate(self):
        if self.tick_id is None:
            self.tick_id = GLib.timeout_add(8, self.tick)

    def tick(self):
        dz = self.zt - self.z
        if abs(dz) < 0.002 * self.zt and abs(self.oxt - self.ox) < 0.3 and abs(self.oyt - self.oy) < 0.3:
            self.z, self.ox, self.oy = self.zt, self.oxt, self.oyt
            self.tick_id = None
            self.win.queue_draw()
            if self.closing:
                self.win.destroy()
            elif time.monotonic() < self.badge_until:
                GLib.timeout_add(int((self.badge_until - time.monotonic()) * 1000) + 30,
                                 lambda: (self.win.queue_draw(), False)[1])
            return False
        self.z += dz * SMOOTH
        if self.anchor and not self.closing:
            ax, ay, px, py = self.anchor
            self.ox, self.oy = self.clamp(px - ax / self.z, py - ay / self.z, self.z)
            if abs(dz) < 0.02 * self.zt:                      # у края упёрлись — доехать до цели
                self.ox += (self.oxt - self.ox) * SMOOTH
                self.oy += (self.oyt - self.oy) * SMOOTH
        else:
            self.ox += (self.oxt - self.ox) * SMOOTH
            self.oy += (self.oyt - self.oy) * SMOOTH
        self.win.queue_draw()
        return True

    # ── рисование ──
    def on_draw(self, _w, cr):
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        iw, ih = self.img.get_width(), self.img.get_height()
        cr.save()
        cr.scale(self.z, self.z)
        cr.translate(-self.ox, -self.oy)
        cr.scale(self.W / iw, self.H / ih)
        cr.set_source_surface(self.img, 0, 0)
        # крупно — пиксели чёткими квадратами, как у лупы; мельче — сглаживание
        px = self.z * iw / self.W
        cr.get_source().set_filter(cairo.FILTER_NEAREST if px >= 3 else
                                   cairo.FILTER_FAST if self.tick_id else cairo.FILTER_GOOD)
        cr.paint()
        cr.restore()
        if time.monotonic() < self.badge_until and not self.closing:
            self.badge(cr)
        return True

    def badge(self, cr):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription.from_string("%s 14px" % FAMILY))
        lay.set_text("×%.1f   ·   Esc — закрыть" % self.zt, -1)
        _ink, log = lay.get_pixel_extents()
        w, h = log.width + 28, log.height + 14
        x, y = (self.W - w) / 2, self.H - h - 28
        cr.set_source_rgba(0, 0, 0, 0.72)
        r = h / 2
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -1.5708, 1.5708)
        cr.arc(x + r, y + r, r, 1.5708, 4.7124)
        cr.close_path()
        cr.fill()
        cr.set_source_rgba(1, 1, 1, 0.92)
        cr.move_to(x + 14, y + 7)
        PangoCairo.show_layout(cr, lay)

    # ── мышь и клавиши ──
    def on_pointer(self, _w, ev):
        first = self.ptr is None
        self.ptr = (ev.x, ev.y)
        if first and self.pending:
            self.flush_pending()
        return False

    def on_motion(self, w, ev):
        self.on_pointer(w, ev)
        if self.drag:
            x0, y0, ox0, oy0 = self.drag
            self.ox, self.oy = self.clamp(ox0 - (ev.x - x0) / self.z, oy0 - (ev.y - y0) / self.z, self.z)
            self.oxt, self.oyt = self.ox, self.oy
            self.anchor = None
            self.win.queue_draw()
        return True

    def on_press(self, _w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        if ev.button == 3:
            self.close()
        elif ev.button == 1:
            if self.tick_id is not None:                      # доехать сразу, тянуть от готового вида
                self.z, self.ox, self.oy = self.zt, self.oxt, self.oyt
            self.drag = (ev.x, ev.y, self.ox, self.oy)
        return True

    def on_release(self, _w, ev):
        if ev.button == 1:
            self.drag = None
        return True

    def on_scroll(self, _w, ev):
        self.ptr = (ev.x, ev.y)
        d = ev.direction
        if d == Gdk.ScrollDirection.SMOOTH:
            # колесо — ±1 на щелчок; тачпад — дробями, копим до целого щелчка
            ok, _dx, dy = ev.get_scroll_deltas()
            if not ok:
                return True
            self.acc += dy
            while abs(self.acc) >= 1:
                step = 1 if self.acc > 0 else -1
                self.acc -= step
                self.zoom("out" if step > 0 else "in", (ev.x, ev.y))
            return True
        if d == Gdk.ScrollDirection.UP:
            self.zoom("in", (ev.x, ev.y))
        elif d == Gdk.ScrollDirection.DOWN:
            self.zoom("out", (ev.x, ev.y))
        return True

    def on_key(self, _w, ev):
        k = ev.keyval
        if k in (Gdk.KEY_Escape, Gdk.KEY_q, Gdk.KEY_Cyrillic_shorti, Gdk.KEY_0):
            self.close()
        elif k in (Gdk.KEY_plus, Gdk.KEY_equal, Gdk.KEY_KP_Add):
            self.zoom("in")
        elif k in (Gdk.KEY_minus, Gdk.KEY_KP_Subtract):
            self.zoom("out")
        return True


def main():
    try:
        loupe = Loupe()
    except Exception as e:                                    # нет grim/niri — молча не открываться
        print("лупа: %s" % e, file=sys.stderr)
        return
    loupe.command("in")
    try:
        Gtk.main()
    finally:
        try:
            os.unlink(FIFO)
        except OSError:
            pass


main()
