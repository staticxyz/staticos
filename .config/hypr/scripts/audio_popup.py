#!/usr/bin/env python3
import os
import sys
import gi
import subprocess
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

class AudioPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Audio Control")
        self.set_default_size(320, 160)
        self.set_position(Gtk.WindowPosition.MOUSE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)

        # Стилизация под тему
        _p = popup_theme.palette()
        css = ("""
        window {
            background-color: %(win_bg)s;
            border: 2px solid %(edge)s;
            border-radius: 16px;
            padding: 14px;
        }
        label {
            color: %(on_surface)s;
            font-family: 'JetBrainsMono Nerd Font', monospace;
            font-size: 13px;
            font-weight: bold;
        }
        button {
            background: %(chip)s;
            border: 1px solid %(edge)s;
            border-radius: 10px;
            color: %(primary)s;
            font-size: 16px;
            padding: 6px 10px;
        }
        button:hover {
            background: %(surface_highest)s;
            color: %(on_surface)s;
        }
        button.muted {
            color: %(error)s;
            border-color: %(error)s;
        }
        scale trough {
            background-color: %(chip)s;
            border-radius: 6px;
            min-height: 8px;
        }
        scale highlight {
            background-color: %(primary)s;
            border-radius: 6px;
        }
        """ % dict(_p,
                   win_bg=popup_theme.rgba(_p["surface"], 0.95),
                   edge=_p["outline_variant"],
                   chip=popup_theme.rgba(_p["surface_container"], 0.6))).encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.add(main_box)

        # 1. Секция Звука
        out_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn_vol = Gtk.Button(label="󰕾")
        self.btn_vol.connect("clicked", self.toggle_sink_mute)
        self.slider_vol = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.slider_vol.set_hexpand(True)
        self.slider_vol.set_value(self.get_vol("@DEFAULT_AUDIO_SINK@"))
        self.slider_vol.connect("value-changed", lambda s: self.set_vol("@DEFAULT_AUDIO_SINK@", s.get_value()))
        out_box.pack_start(self.btn_vol, False, False, 0)
        out_box.pack_start(self.slider_vol, True, True, 0)
        main_box.pack_start(out_box, False, False, 0)

        # 2. Секция Микрофона
        mic_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.btn_mic = Gtk.Button(label="󰍬")
        self.btn_mic.connect("clicked", self.toggle_source_mute)
        self.slider_mic = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
        self.slider_mic.set_hexpand(True)
        self.slider_mic.set_value(self.get_vol("@DEFAULT_AUDIO_SOURCE@"))
        self.slider_mic.connect("value-changed", lambda s: self.set_vol("@DEFAULT_AUDIO_SOURCE@", s.get_value()))
        mic_box.pack_start(self.btn_mic, False, False, 0)
        mic_box.pack_start(self.slider_mic, True, True, 0)
        main_box.pack_start(mic_box, False, False, 0)

        # Закрытие окна при потере фокуса
        self.connect("focus-out-event", lambda w, e: self.destroy())
        self.update_icons()

    def get_vol(self, target):
        try:
            out = subprocess.check_output(f"wpctl get-volume {target}", shell=True).decode()
            parts = out.strip().split()
            return int(float(parts[1]) * 100) if len(parts) > 1 else 50
        except:
            return 50

    def set_vol(self, target, val):
        subprocess.run(f"wpctl set-volume {target} {int(val)}%", shell=True)

    def toggle_sink_mute(self, btn):
        subprocess.run("wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle", shell=True)
        self.update_icons()

    def toggle_source_mute(self, btn):
        subprocess.run("wpctl set-mute @DEFAULT_AUDIO_SOURCE@ toggle", shell=True)
        self.update_icons()

    def update_icons(self):
        try:
            sink_out = subprocess.check_output("wpctl get-volume @DEFAULT_AUDIO_SINK@", shell=True).decode()
            if "MUTED" in sink_out:
                self.btn_vol.set_label("󰝟")
                self.btn_vol.get_style_context().add_class("muted")
            else:
                self.btn_vol.set_label("󰕾")
                self.btn_vol.get_style_context().remove_class("muted")

            src_out = subprocess.check_output("wpctl get-volume @DEFAULT_AUDIO_SOURCE@", shell=True).decode()
            if "MUTED" in src_out:
                self.btn_mic.set_label("󰍭")
                self.btn_mic.get_style_context().add_class("muted")
            else:
                self.btn_mic.set_label("󰍬")
                self.btn_mic.get_style_context().remove_class("muted")
        except:
            pass

win = AudioPopup()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
