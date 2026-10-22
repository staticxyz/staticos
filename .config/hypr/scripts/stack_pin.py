#!/usr/bin/env python3
"""«Поверх всех» в стопке (21.10.2026, просьба: «окно должно быть поверх всех окон, как в
Windows»): у niri 26.04 нет keep-above и подъёма без фокуса, поэтому поверх окон стоит живое
зеркало закреплённого окна — слой TOP на его месте. Картинка — запись окна через
org.gnome.Mutter.ScreenCast niri (RecordWindow, без диалога портала) → pipewiresrc → gtksink.
Щелчок и колесо над зеркалом — фокус настоящему окну (niri его поднимает, зеркало прячется).
Спрятать — погасить картинку и вход, сжать до 1×1, но слой не убирать: после hide()/show() окна GTK
кадры шли и рисовались, а на экране стоял старый (21.10.2026, просьба: «застывает»).

Запускает stack_bars.py (ПКМ по полосе → «Поверх всех»), команды — по строке в stdin:
    show X Y W H     зеркало на место (координаты слоя полос — рабочая область монитора)
    hide             спрятать (окно в фокусе, стол не виден, обзор, свёрнуто)
    quit             закончить запись и выйти

    stack_pin.py ID ВЫХОД            зеркало окна ID на мониторе ВЫХОД
    stack_pin.py --frame ID ФАЙЛ     один кадр окна в PNG (проверка без окон на экране)
    stack_pin.py --sweep             закрыть записи зеркал, убитых без quit (красная рамка)
"""
import ctypes
import os
import signal
import sys

# GL зеркала — на Intel: NVIDIA не будим (RTX спит, см. niri cfg/gpu.kdl)
os.environ.setdefault("__EGL_VENDOR_LIBRARY_FILENAMES", "/usr/share/glvnd/egl_vendor.d/50_mesa.json")

import gi  # noqa: E402

gi.require_version("Gst", "1.0")
gi.require_version("GstVideo", "1.0")
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gst, GstVideo, Gtk, GtkLayerShell  # noqa: E402

try:
    from gi.repository import GLibUnix  # noqa: E402
    signal_add = GLibUnix.signal_add
except (ImportError, AttributeError):
    signal_add = GLib.unix_signal_add

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import stack_mode as sm  # noqa: E402

NAMESPACE = "jarvis-stack-pin"
# метки «это наше зеркало, не трансляция»: файл = id окна, внутри pid. Их читает auto_dnd.py —
# уведомления во время закрепления гасли (21.10.2026, просьба: «выключаются уведомления»)
MARKS = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), NAMESPACE)
MUTTER = "org.gnome.Mutter.ScreenCast"


def die_with_parent():
    """Полосы упали — зеркало не остаётся сиротой (PR_SET_PDEATHSIG = 1)."""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)
    except OSError:
        pass


class Cast:
    """Запись одного окна: сессия Mutter ScreenCast → узел PipeWire (on_node(node_id))."""

    def __init__(self, wid, on_node, on_closed):
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.on_node, self.on_closed = on_node, on_closed
        self.session = self.call("/org/gnome/Mutter/ScreenCast", MUTTER, "CreateSession",
                                 GLib.Variant("(a{sv})", ({},)))[0]
        self.stream = self.call(self.session, MUTTER + ".Session", "RecordWindow", GLib.Variant(
            "(a{sv})", ({"window-id": GLib.Variant("t", wid), "cursor-mode": GLib.Variant("u", 0)},)))[0]
        self.bus.signal_subscribe(MUTTER, MUTTER + ".Stream", "PipeWireStreamAdded", self.stream, None,
                                  Gio.DBusSignalFlags.NONE, self.added)
        self.bus.signal_subscribe(MUTTER, MUTTER + ".Session", "Closed", self.session, None,
                                  Gio.DBusSignalFlags.NONE, lambda *_a: self.on_closed())
        self.call(self.session, MUTTER + ".Session", "Start", None)

    def call(self, path, iface, method, args):
        r = self.bus.call_sync(MUTTER, path, iface, method, args, None, Gio.DBusCallFlags.NONE, 3000, None)
        return r.unpack() if r else None

    def added(self, *a):
        self.on_node(a[-1].unpack()[0])

    def stop(self):
        try:
            self.call(self.session, MUTTER + ".Session", "Stop", None)
        except GLib.Error:
            pass                                 # окно закрыли — сессии уже нет


# niri отдаёт запись только DMA-BUF; сжатый CCS (…06/…08) glupload не берёт, без модификатора —
# мусор (тайлы читаются как линейные). Y-тайлинг Intel проверен кадрами 21.10.
# AR24 (BGRA), не XR24: прозрачность окна сохраняется — у полупрозрачного kitty фон зеркала был
# чёрным (21.10.2026, просьба: «фон окна красится в черный»); под зеркалом размытие, как у окон
# (layer-rules.kdl).
CAPS = "video/x-raw(memory:DMABuf),format=DMA_DRM,drm-format=AR24:0x0100000000000002"


def source(node):
    return ("pipewiresrc path=%d keepalive-time=500 ! %s ! glupload ! glcolorconvert ! gldownload ! videoconvert ! video/x-raw,format=BGRA"
            % (node, CAPS))


def frame(wid, path):
    """Один кадр окна в PNG — проверить запись без окон на экране."""
    Gst.init(None)
    loop = GLib.MainLoop()
    res = {"ok": False}

    def on_node(node):
        pipe = Gst.parse_launch(source(node) + " ! videoconvert ! pngenc snapshot=true ! filesink location=" + path)
        bus = pipe.get_bus()
        bus.add_signal_watch()

        def msg(_b, m):
            if m.type in (Gst.MessageType.EOS, Gst.MessageType.ERROR):
                res["ok"] = m.type == Gst.MessageType.EOS
                if m.type == Gst.MessageType.ERROR:
                    print("ошибка:", m.parse_error()[0].message, file=sys.stderr)
                pipe.set_state(Gst.State.NULL)
                loop.quit()
        bus.connect("message", msg)
        pipe.set_state(Gst.State.PLAYING)

    cast = Cast(wid, on_node, loop.quit)
    GLib.timeout_add(5000, loop.quit)
    loop.run()
    cast.stop()
    print(path if res["ok"] else "кадра нет")
    return 0 if res["ok"] else 1


def edge(alpha, spare):
    """Сколько срезать с начала: первая точка, где альфа доходит до 90 % альфы середины окна,
    но не больше лишнего (spare = кадр − окно)."""
    if spare <= 0 or not alpha:
        return 0
    body = alpha[len(alpha) // 2]
    for i in range(min(spare, len(alpha)) + 1):
        if alpha[i] >= body * 0.9:
            return i
    return spare


class Mirror:
    def __init__(self, wid, out):
        self.wid, self.pipe, self.rect, self.shown = wid, None, None, False
        self.crop_key = None
        Gst.init(None)
        w = self.win = Gtk.Window()
        w.set_title(NAMESPACE)
        w.set_app_paintable(True)                # без фона: спрятанное зеркало прозрачно,
        vis = w.get_screen().get_rgba_visual()
        if vis:                                  # а непрозрачный слой заслонил бы окно —
            w.set_visual(vis)                    # niri перестал бы его рисовать (кадр застыл)
        self.widget = None
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_exclusive_zone(w, 0)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT):
            GtkLayerShell.set_anchor(w, e, True)
        mon = self.monitor(out)
        if mon is not None:
            GtkLayerShell.set_monitor(w, mon)
        # колесо — как щелчок: поднять настоящее окно, дальше крутит уже оно. Без фокуса никак —
        # окно под другими, а Wayland не шлёт прокрутку закрытому окну (21.10.2026, просьба:
        # «не могу скроллить по закрепленному окну»; первый щелчок колеса уходит на подъём)
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                     | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        w.connect("button-press-event", self.on_press)
        w.connect("scroll-event", self.on_press)
        self.mark = os.path.join(MARKS, str(wid))
        os.makedirs(MARKS, exist_ok=True)
        with open(self.mark, "w") as f:          # до записи: niri сообщит о ней сразу
            f.write(str(os.getpid()))
        self.cast = Cast(wid, self.on_node, self.quit)
        with open(self.mark + ".session", "w") as f:   # для sweep(), если зеркало убьют силой
            f.write(self.cast.session)
        GLib.io_add_watch(sys.stdin.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP, self.on_cmd)
        signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, self.quit)
        signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, self.quit)

    @staticmethod
    def monitor(out):
        o = (sm.get("Outputs") or {}).get(out) or {}
        lg = o.get("logical") or {}
        disp = Gdk.Display.get_default()
        for i in range(disp.get_n_monitors()):
            m = disp.get_monitor(i)
            g = m.get_geometry()
            if (g.x, g.y) == (lg.get("x"), lg.get("y")):
                return m
        return None

    def on_node(self, node):
        self.pipe = Gst.parse_launch(source(node) + " ! videocrop name=crop ! gtksink name=sink "
                                     "force-aspect-ratio=false")
        self.crop = self.pipe.get_by_name("crop")
        self.crop.get_static_pad("sink").add_probe(Gst.PadProbeType.BUFFER, self.on_buffer)
        self.widget = self.pipe.get_by_name("sink").get_property("widget")
        self.win.add(self.widget)
        bus = self.pipe.get_bus()
        bus.add_signal_watch()
        bus.connect("message::error", lambda _b, m: (sm.log("pin: ошибка", m.parse_error()[0].message),
                                                      self.quit()))
        self.pipe.set_state(Gst.State.PLAYING)
        sm.log("pin: зеркало", self.wid, "узел", node)
        self.apply()

    def on_buffer(self, pad, info):
        """Кадр записи — окно вместе с тенью/полями клиента (Helium: 968×731 при окне 936×689,
        поля 16/10 сверху-слева и 32 снизу), зеркало сжимало всё в рамку окна: «по всем бокам
        черные полотна» (21.10.2026). Где окно в кадре — по непрозрачности: от середины строки
        и столбца к краю, пока альфа держится как у окна (тень тает). Считается заново, только
        когда меняется размер кадра или окна."""
        caps, rect = pad.get_current_caps(), self.rect
        if caps is None or not rect:
            return Gst.PadProbeReturn.OK
        vi = GstVideo.VideoInfo.new_from_caps(caps)
        fw, fh, w, h = vi.width, vi.height, rect[2], rect[3]
        if self.crop_key == (fw, fh, w, h):
            return Gst.PadProbeReturn.OK
        self.crop_key = (fw, fh, w, h)
        left = top = 0
        if fw > w or fh > h:
            ok, m = info.get_buffer().map(Gst.MapFlags.READ)
            if ok:
                data, stride = m.data, vi.stride[0]
                row = data[stride * (fh // 2) + 3:stride * (fh // 2) + 4 * fw:4]
                col = data[stride * 0 + 4 * (fw // 2) + 3::stride][:fh]
                left = edge(row, fw - w)
                top = edge(col, fh - h)
                info.get_buffer().unmap(m)
        right, bottom = max(0, fw - w - left), max(0, fh - h - top)
        for k, v in (("left", left), ("top", top), ("right", right), ("bottom", bottom)):
            self.crop.set_property(k, v)
        sm.log("pin: кадр", fw, "x", fh, "окно", w, "x", h, "поля", left, top, right, bottom)
        return Gst.PadProbeReturn.OK

    def on_press(self, _w, _ev):
        sm.A("FocusWindow", id=self.wid)         # niri поднимет окно, полосы пришлют hide
        return True

    def on_cmd(self, fd, cond):
        line = os.read(fd, 4096).decode(errors="replace") if cond & GLib.IO_IN else ""
        if not line:
            self.quit()
            return False
        for cmd in line.split("\n"):
            p = cmd.split()
            if not p:
                continue
            if p[0] == "show" and len(p) == 5:
                self.rect = tuple(int(v) for v in p[1:])
                self.shown = True
            elif p[0] == "hide":
                self.shown = False
            elif p[0] == "quit":
                self.quit()
                return False
        self.apply()
        return True

    def apply(self):
        import cairo
        if not self.shown or not self.rect or self.pipe is None:
            if self.widget is not None:
                self.widget.hide()
            self.win.set_size_request(1, 1)      # под слоем размытие: пустой слой во всё окно
            self.win.resize(1, 1)                # стоял бы мутным прямоугольником
            if self.win.get_window() is not None:
                self.win.input_shape_combine_region(cairo.Region())   # щелчки — сквозь
            return
        x, y, w, h = self.rect
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.LEFT, x)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, y)
        self.win.set_size_request(w, h)
        self.win.resize(w, h)
        self.widget.show()
        self.win.show()
        self.win.input_shape_combine_region(None)

    def quit(self, *_a):
        if self.pipe is not None:
            self.pipe.set_state(Gst.State.NULL)
        self.cast.stop()
        for path in (self.mark, self.mark + ".session"):
            try:
                os.unlink(path)
            except OSError:
                pass
        Gtk.main_quit()
        return False


def sweep():
    """Закрыть записи мёртвых зеркал. Убитое без quit (SIGKILL, падение) оставляет сессию niri:
    окно в красной рамке трансляции, пока niri не перезапущен (22.10.2026, просьба: «красная
    линия» вокруг btop — три забытые записи с опытов 21.10)."""
    try:
        names = [n for n in os.listdir(MARKS) if n.endswith(".session")]
    except OSError:
        return 0
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    n_closed = 0
    for n in names:
        mark = os.path.join(MARKS, n[:-len(".session")])
        try:
            os.kill(int(open(mark).read().strip()), 0)
            continue                             # зеркало живо
        except (OSError, ValueError):
            pass
        try:
            session = open(os.path.join(MARKS, n)).read().strip()
            bus.call_sync(MUTTER, session, MUTTER + ".Session", "Stop", None, None,
                          Gio.DBusCallFlags.NONE, 3000, None)
            n_closed += 1
        except (OSError, GLib.Error):
            pass                                 # сессии уже нет
        for path in (mark, os.path.join(MARKS, n)):
            try:
                os.unlink(path)
            except OSError:
                pass
    return n_closed


def main(argv):
    if argv[1:] == ["--sweep"]:
        print("закрыто записей:", sweep())
        return 0
    if len(argv) == 4 and argv[1] == "--frame":
        return frame(int(argv[2]), argv[3])
    if len(argv) != 3 or not argv[1].isdigit():
        print(__doc__)
        return 2
    die_with_parent()
    Mirror(int(argv[1]), argv[2])
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
