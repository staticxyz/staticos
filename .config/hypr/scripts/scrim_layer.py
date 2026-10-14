"""Затемнение за меню-слоем и «щелчок мимо — закрыть» (14.10.2026).

Просьба: «при открытии Карты сделай небольшое затемнение, как в Super+X» — и в
Super+C, и в Super+Z. Super+X (app_launcher.py) сам во весь экран и красит фон
SCRIM; у карты, шпаргалки и калькулятора окно маленькое, поэтому под ними —
прозрачный слой TOP во весь каждый монитор. На мониторе, где встало меню, он
чёрный SCRIM, на остальных — прозрачный; щелчок по любому — on_click (закрыть).

    from scrim_layer import cover
    scrims = cover(win, "jarvis-calc-catch", win.destroy)   # до win.show_all()

Своё имя слоя у каждого: у jarvis-recmenu-catch в layer-rules.kdl размытие.
"""
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
import cairo  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

SCRIM = 0.22             # как SCRIM у Super+X (app_launcher.py)


class Scrim(Gtk.Window):
    """Слой во весь монитор под меню: тёмный, если dim, иначе прозрачный."""

    def __init__(self, monitor, namespace, on_click):
        super().__init__()
        self.dim = False
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, namespace)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", lambda *_a: on_click() or True)

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, SCRIM if self.dim else 0)
        cr.paint()
        return True


def cover(win, namespace, on_click):
    """Слои на все мониторы (показаны сразу); тёмным станет тот, где встанет win.
    Слои живут, пока жив win: закрылся — убираются сами. → список слоёв."""
    disp = Gdk.Display.get_default()
    mons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())]
    scrims = [Scrim(m, namespace, on_click) for m in mons]
    for s in scrims:
        s.show_all()

    tries = [0]

    def dim_own():
        gw = win.get_window()
        mon = disp.get_monitor_at_window(gw) if gw else None
        if mon is None:
            tries[0] += 1
            return tries[0] < 40         # ещё не вышло на монитор — ждать до ~1 с
        for m, s in zip(mons, scrims):
            s.dim = m == mon
            s.queue_draw()
        return False

    win.connect("map-event", lambda *_a: GLib.timeout_add(30, dim_own) and False)
    win.connect("destroy", lambda *_a: [s.destroy() for s in scrims])
    return scrims
