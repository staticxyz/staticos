#!/usr/bin/env python3
import subprocess
import os
import sys
import gi

pid = os.getpid()
try:
    pids = subprocess.check_output(["pgrep", "-f", "quicksettings_popup.py"], text=True).strip().split()
    other_pids = [p for p in pids if int(p) != pid]
    if other_pids:
        for p in other_pids:
            subprocess.run(["kill", "-9", p])
        sys.exit(0)
except Exception:
    pass

gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

class QuickSettingsPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Быстрые настройки")
        
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        css = popup_theme.css("""
        .popup-box {
            font-family: 'JetBrainsMono Nerd Font', 'Noto Sans', sans-serif;
            font-size: 13px;
            padding: 16px;
        }
        label { color: %(on_surface)s; }
        switch:checked { background-color: %(primary)s; }
        button.details-btn {
            background-color: %(surface_container)s;
            color: %(primary)s;
            border-radius: 6px;
            padding: 4px 8px;
            font-size: 11px;
        }
        button.details-btn:hover { background-color: %(surface_highest)s; }
        """)
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Невидимый фон-перехватчик
        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        # Контейнер для сдвига
        self.align = Gtk.Box()
        self.align.set_halign(Gtk.Align.END)
        self.align.set_valign(Gtk.Align.START)
        self.align.set_margin_top(34)
        self.align.set_margin_right(110)
        self.bg.add(self.align)

        # Защитная прослойка
        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        # Сам контент
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        vbox.get_style_context().add_class("popup-box")
        vbox.set_size_request(280, -1)
        self.popup_event.add(vbox)

        # Заголовок
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        title_lbl = Gtk.Label(label="󰤨  Сеть и Bluetooth", xalign=0)
        header.pack_start(title_lbl, True, True, 0)
        vbox.pack_start(header, False, False, 0)

        # 1. Секция Wi-Fi
        wifi_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        wifi_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        wifi_state, wifi_ssid = self.get_wifi_info()
        wifi_lbl = Gtk.Label(label=f"󰤨  Wi-Fi ({wifi_ssid})", xalign=0)
        
        self.wifi_switch = Gtk.Switch()
        self.wifi_switch.set_active(wifi_state)
        self.wifi_switch.connect("notify::active", self.on_wifi_toggled)
        
        wifi_hdr.pack_start(wifi_lbl, True, True, 0)
        wifi_hdr.pack_start(self.wifi_switch, False, False, 0)
        
        wifi_btn = Gtk.Button(label="Управление Wi-Fi...")
        wifi_btn.get_style_context().add_class("details-btn")
        wifi_btn.connect("clicked", lambda b: subprocess.Popen(["nm-connection-editor"]))
        
        wifi_box.pack_start(wifi_hdr, False, False, 0)
        wifi_box.pack_start(wifi_btn, False, False, 0)
        vbox.pack_start(wifi_box, False, False, 0)

        # 2. Секция Bluetooth
        bt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        bt_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        bt_state = self.get_bt_info()
        bt_lbl = Gtk.Label(label="󰂯  Bluetooth", xalign=0)
        
        self.bt_switch = Gtk.Switch()
        self.bt_switch.set_active(bt_state)
        self.bt_switch.connect("notify::active", self.on_bt_toggled)
        
        bt_hdr.pack_start(bt_lbl, True, True, 0)
        bt_hdr.pack_start(self.bt_switch, False, False, 0)
        
        bt_btn = Gtk.Button(label="Устройства Bluetooth...")
        bt_btn.get_style_context().add_class("details-btn")
        bt_btn.connect("clicked", lambda b: subprocess.Popen(["blueman-manager"]))
        
        bt_box.pack_start(bt_hdr, False, False, 0)
        bt_box.pack_start(bt_btn, False, False, 0)
        vbox.pack_start(bt_box, False, False, 0)

        self.connect("key-press-event", lambda w, e: sys.exit(0))

    def get_wifi_info(self):
        try:
            res = subprocess.check_output(["nmcli", "radio", "wifi"], text=True).strip()
            state = (res == "enabled")
            ssid = "Отключен"
            if state:
                out = subprocess.check_output(["nmcli", "-t", "-f", "ACTIVE,SSID", "dev", "wifi"], text=True)
                for line in out.splitlines():
                    if line.startswith("yes:"):
                        ssid = line.split(":", 1)[1]
                        break
            return state, ssid
        except Exception:
            return False, "Выключен"

    def on_wifi_toggled(self, switch, gparam):
        cmd = "on" if switch.get_active() else "off"
        subprocess.run(["nmcli", "radio", "wifi", cmd])

    def get_bt_info(self):
        try:
            res = subprocess.check_output(["bluetoothctl", "show"], text=True)
            return "Powered: yes" in res
        except Exception:
            return False

    def on_bt_toggled(self, switch, gparam):
        cmd = "on" if switch.get_active() else "off"
        subprocess.run(["bluetoothctl", "power", cmd])

if __name__ == "__main__":
    win = QuickSettingsPopup()
    win.show_all()
    Gtk.main()
