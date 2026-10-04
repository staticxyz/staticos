#!/usr/bin/env python3
import sys, os, subprocess, gi, pulsectl

gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402
# Второй щелчок по модулю закрывает открытый попап. Раньше здесь были
# `pgrep -f` и `kill -9` по всему найденному — см. popup_theme.single_instance.
popup_theme.single_instance(__file__)

class MicPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Микрофон")

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        # Общий каркас, см. popup_theme.py. Шкала микрофона красится ролью
        # error, как и была красной в зашитой гамме: это единственный попап,
        # где цвет нёс смысл (запись), поэтому роль выбрана, а не primary.
        css = popup_theme.css(
            popup_theme.SCALE_CSS + """
        /* Компактнее (30.09.2026, просьба: «слишком крупно»): пиксельный шрифт
           12 px (он чёткий на 12/16/24), тонкая шкала, маленькая ручка. */
        .popup-box { font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
                     font-size: 12px; padding: 12px 18px 22px 18px; }
        label { font-weight: normal; font-size: 12px; }
        label.section { color: %(on_surface_variant)s; }
        scale { padding: 0; margin: 0; min-height: 0; }
        scale value { font-size: 12px; min-width: 28px; margin-left: 8px; }
        scale trough { min-height: 5px; }
        scale slider { min-width: 11px; min-height: 11px; margin: -4px; }
        separator { margin: 2px 0; }
        """,
            accent="error", knob="tertiary")
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        self.align = Gtk.Box()
        # Прямо под баром и серединой под точкой щелчка — общая логика всех
        # попапов бара, см. popup_theme.place_under_cursor. Раньше здесь были
        # отступ 34 сверху (слой и так начинается под панелью, так что попап
        # висел на полосу ниже) и жёсткий отступ от правого края.
        popup_theme.place_under_cursor(self.align)
        self.bg.add(self.align)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        vbox.get_style_context().add_class("popup-box")
        vbox.set_size_request(280, -1)
        self.popup_event.add(vbox)

        self.pulse = pulsectl.Pulse('gtk-mic-mixer')

        try:
            srv = self.pulse.server_info()
            default_src = next((s for s in self.pulse.source_list() if s.name == srv.default_source_name), None)
            if not default_src and self.pulse.source_list():
                default_src = self.pulse.source_list()[0]
            
            if default_src:
                lbl = Gtk.Label(label=" Уровень микрофона", xalign=0)
                scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
                scale.set_draw_value(True)
                scale.set_value_pos(Gtk.PositionType.RIGHT)
                scale.set_value(round(default_src.volume.value_flat * 100))
                scale.connect("value-changed", self.on_mic_changed, default_src.index)
                
                vbox.pack_start(lbl, False, False, 0)
                vbox.pack_start(scale, False, False, 0)
        except Exception: pass

        self.connect("key-press-event", lambda w, e: sys.exit(0))

    def on_mic_changed(self, scale, idx):
        vol = scale.get_value() / 100.0
        try:
            src = self.pulse.source_info(idx)
            self.pulse.volume_set_all_chans(src, vol)
        except Exception: pass

if __name__ == "__main__":
    win = MicPopup()
    win.show_all()
    Gtk.main()
