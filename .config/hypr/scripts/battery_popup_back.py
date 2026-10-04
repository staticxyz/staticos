#!/usr/bin/env python3
import subprocess
import os
import sys
import glob
import gi

# Закрытие при повторном клике
pid = os.getpid()
try:
    pids = subprocess.check_output(["pgrep", "-f", "battery_popup.py"], text=True).strip().split()
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

PID_FILE = "/tmp/savage_mode.pid"

def is_savage_active():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid_val = int(f.read().strip())
        cmdline_path = f"/proc/{pid_val}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().decode("utf-8", errors="ignore")
                if "systemd-inhibit" in cmdline and "24/7 mode" in cmdline:
                    return True
        os.remove(PID_FILE)
    except Exception:
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
    return False

class BatteryPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Панель питания")
        self.set_default_size(300, 270)
        self.set_border_width(12)
        self.set_resizable(False)

        # Привязка вплотную под правый островок Waybar
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, 34)
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, 10)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        # Стили Tokyo Night / Deep Blue
        css = b"""
        window {
            background-color: #1a1b26;
            color: #c0caf5;
            font-family: 'JetBrainsMono Nerd Font', 'Noto Sans', sans-serif;
            font-weight: bold;
            font-size: 13px;
            border: 1px solid rgba(122, 162, 247, 0.25);
            border-radius: 14px;
        }
        .energy-badge {
            background-color: #24283b;
            border-radius: 8px;
            padding: 4px 10px;
            color: #7aa2f7;
            font-size: 13px;
        }
        scale highlight {
            background-color: #7aa2f7;
            border-radius: 4px;
        }
        scale trough {
            background-color: #24283b;
            border-radius: 4px;
            min-height: 6px;
        }
        switch {
            background-color: #24283b;
            border-radius: 12px;
        }
        switch:checked {
            background-color: #7aa2f7;
        }
        button.close-btn {
            background: transparent;
            color: #565f89;
            font-size: 14px;
            padding: 0 4px;
            border: none;
        }
        button.close-btn:hover {
            color: #f7768e;
        }
        .section-label {
            color: #c0caf5;
            font-size: 12px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(vbox)

        # 1. Шапка: "Энергия" + Кнопка закрытия
        cap, icon = self.get_battery_info()
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        
        lbl_energy = Gtk.Label(label=f"{icon}  Энергия: {cap}%", xalign=0)
        lbl_energy.get_style_context().add_class("energy-badge")
        
        close_btn = Gtk.Button(label="󰅖")
        close_btn.get_style_context().add_class("close-btn")
        close_btn.connect("clicked", lambda b: sys.exit(0))
        
        header.pack_start(lbl_energy, True, True, 0)
        header.pack_start(close_btn, False, False, 0)
        vbox.pack_start(header, False, False, 2)

        # 2. Яркость экрана
        bright_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        bright_lbl = Gtk.Label(label="󰃠  Яркость экрана", xalign=0)
        bright_lbl.get_style_context().add_class("section-label")
        
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
        self.scale.set_value(self.get_brightness())
        self.scale.connect("value-changed", self.on_brightness_changed)
        
        bright_box.pack_start(bright_lbl, False, False, 0)
        bright_box.pack_start(self.scale, False, False, 0)
        vbox.pack_start(bright_box, False, False, 0)

        # 3. Night Shift (0% = 6500K, 100% = 2800K)
        night_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        night_hdr = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        night_lbl = Gtk.Label(label="󰖔  Ночной режим", xalign=0)
        night_lbl.get_style_context().add_class("section-label")
        
        self.night_switch = Gtk.Switch()
        self.night_switch.set_active(self.get_night_shift_state())
        self.night_switch.connect("notify::active", self.on_night_shift_toggled)
        
        night_hdr.pack_start(night_lbl, True, True, 0)
        night_hdr.pack_start(self.night_switch, False, False, 0)
        
        self.night_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.night_scale.set_value(65)
        self.night_scale.connect("value-changed", self.on_night_temp_changed)
        
        night_box.pack_start(night_hdr, False, False, 0)
        night_box.pack_start(self.night_scale, False, False, 0)
        vbox.pack_start(night_box, False, False, 0)

        # 4. Энергосбережение
        power_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        power_lbl = Gtk.Label(label="󰌪  Энергосбережение", xalign=0)
        power_lbl.get_style_context().add_class("section-label")
        self.power_switch = Gtk.Switch()
        self.power_switch.set_active(self.get_power_saver_state())
        self.power_switch.connect("notify::active", self.on_power_saver_toggled)
        power_box.pack_start(power_lbl, True, True, 0)
        power_box.pack_start(self.power_switch, False, False, 0)
        vbox.pack_start(power_box, False, False, 2)

        # 5. Savage Mode
        awake_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        awake_lbl = Gtk.Label(label="󰓅  Savage Mode", xalign=0)
        awake_lbl.get_style_context().add_class("section-label")
        self.awake_switch = Gtk.Switch()
        self.awake_switch.set_active(is_savage_active())
        self.awake_switch.connect("notify::active", self.on_savage_toggled)
        awake_box.pack_start(awake_lbl, True, True, 0)
        awake_box.pack_start(self.awake_switch, False, False, 0)
        vbox.pack_start(awake_box, False, False, 2)

        # Закрытие при потере фокуса или клике мимо окна
        self.connect("focus-out-event", lambda w, e: sys.exit(0))
        self.connect("key-press-event", self.on_key_press)

    def get_battery_info(self):
        bats = glob.glob("/sys/class/power_supply/BAT*")
        if not bats:
            return 100, "󰚥"
        bat_path = bats[0]
        try:
            with open(f"{bat_path}/capacity", "r") as f:
                cap = int(f.read().strip())
            with open(f"{bat_path}/status", "r") as f:
                status = f.read().strip()
            
            icon = "󱐋" if status == "Charging" else ("󰚥" if status == "Not charging" else "󰁹")
            return cap, icon
        except Exception:
            return 100, "󰂄"

    def get_night_shift_state(self):
        try:
            res = subprocess.check_output(["pgrep", "wlsunset"], text=True)
            return len(res.strip()) > 0
        except Exception:
            return False

    def apply_night_temp(self):
        intensity = self.night_scale.get_value()
        # 0% = 6500K (холодный), 100% = 2800K (максимально теплый)
        temp = int(6500 - (intensity / 100.0) * 3700)
        subprocess.run(["pkill", "wlsunset"], stderr=subprocess.DEVNULL)
        # Одновременная передача -t и -T предотвращает падение wlsunset
        subprocess.Popen(["wlsunset", "-t", str(temp), "-T", str(temp + 10)])

    def on_night_shift_toggled(self, switch, gparam):
        if switch.get_active():
            self.apply_night_temp()
        else:
            subprocess.run(["pkill", "wlsunset"], stderr=subprocess.DEVNULL)

    def on_night_temp_changed(self, scale):
        if self.night_switch.get_active():
            self.apply_night_temp()

    def on_key_press(self, widget, event):
        if event.keyval == Gdk.KEY_Escape:
            sys.exit(0)

    def get_brightness(self):
        try:
            res = subprocess.check_output(["brightnessctl", "g"], text=True).strip()
            max_b = subprocess.check_output(["brightnessctl", "m"], text=True).strip()
            return int((int(res) / int(max_b)) * 100)
        except Exception:
            return 50

    def on_brightness_changed(self, scale):
        val = int(scale.get_value())
        subprocess.run(["brightnessctl", "set", f"{val}%"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def get_power_saver_state(self):
        try:
            res = subprocess.check_output(["powerprofilesctl", "get"], text=True).strip()
            return res == "power-saver"
        except Exception:
            return False

    def on_power_saver_toggled(self, switch, gparam):
        mode = "power-saver" if switch.get_active() else "balanced"
        subprocess.run(["powerprofilesctl", "set", mode], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_savage_toggled(self, switch, gparam):
        current_state = is_savage_active()
        if switch.get_active() != current_state:
            subprocess.run(["python3", os.path.expanduser("~/.config/hypr/scripts/savage_battery.py"), "--toggle"])

if __name__ == "__main__":
    win = BatteryPopup()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
