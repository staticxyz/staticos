#!/usr/bin/env python3
import os
import sys
import gi
import subprocess
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

class NetBTPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Network & Bluetooth")
        self.set_default_size(280, 140)
        self.set_position(Gtk.WindowPosition.MOUSE)
        self.set_decorated(False)
        self.set_resizable(False)
        self.set_skip_taskbar_hint(True)

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
            padding: 8px 12px;
        }
        button:hover {
            background: %(surface_highest)s;
            color: %(on_surface)s;
        }
        """ % dict(_p,
                   win_bg=popup_theme.rgba(_p["surface"], 0.95),
                   edge=_p["outline_variant"],
                   chip=popup_theme.rgba(_p["surface_container"], 0.6))).encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(main_box)

        # Wi-Fi переключатель
        btn_wifi = Gtk.Button(label="󰤨  Wi-Fi: Переключить / Список")
        btn_wifi.connect("clicked", self.toggle_wifi)
        main_box.pack_start(btn_wifi, True, True, 0)

        # Bluetooth переключатель
        btn_bt = Gtk.Button(label="  Bluetooth: Вкл / Выкл")
        btn_bt.connect("clicked", self.toggle_bt)
        main_box.pack_start(btn_bt, True, True, 0)

        self.connect("focus-out-event", lambda w, e: self.destroy())

    def toggle_wifi(self, btn):
        subprocess.run("nmcli radio wifi $(nmcli radio wifi | grep -q 'enabled' && echo off || echo on)", shell=True)
        self.destroy()

    def toggle_bt(self, btn):
        subprocess.run("rfkill toggle bluetooth", shell=True)
        self.destroy()

win = NetBTPopup()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
