#!/usr/bin/env python3
"""Режим «пиксельный шрифт» — глобальный переключатель.

    pixel_mode.py get        on / off
    pixel_mode.py set on|off

Когда включён — добавляет правило fontconfig, которое подменяет
JetBrainsMono Nerd Font (UI-шрифт оболочки) на PxPlus HP 100LX 6x8.
Никакие файлы CSS или скрипты не трогаются: замена работает через fontconfig,
прозрачно для всех GTK-приложений (бар, попапы, лаунчер, настройки).
Kitty остаётся на PxPlus HP 100LX 6x8 Jarvis — другое имя, не затронут.
"""
import os
import subprocess
import sys

CONF = os.path.expanduser("~/.config/fontconfig/conf.d/65-pixel-mode.conf")

# Шрифты оболочки, которые подменяются на пиксельный.
UI_FAMILIES = [
    "JetBrainsMono Nerd Font",
    "JetBrainsMono Nerd Font Mono",
    "JetBrainsMono NF",
    "JetBrains Mono",
]
PIXEL_FAMILY = "PxPlus HP 100LX 6x8"

CONF_ON_HEADER = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <!-- pixel_mode.py: подменяем UI-шрифт оболочки на пиксельный -->
"""
CONF_ON_FOOTER = "</fontconfig>\n"


def _rule(family):
    return (
        "  <match target=\"pattern\">\n"
        "    <test name=\"family\" compare=\"eq\"><string>%s</string></test>\n"
        "    <edit name=\"family\" mode=\"assign_replace\">\n"
        "      <string>%s</string>\n"
        "    </edit>\n"
        "  </match>\n" % (family, PIXEL_FAMILY)
    )


CONF_ON = CONF_ON_HEADER + "".join(_rule(f) for f in UI_FAMILIES) + CONF_ON_FOOTER
CONF_OFF = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<fontconfig>
  <!-- pixel_mode.py: off -->
</fontconfig>
"""


def get():
    try:
        content = open(CONF).read()
        return "off" if "off" in content or "assign_replace" not in content else "on"
    except OSError:
        return "off"


def _apply(conf_text, state):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    tmp = CONF + ".tmp"
    with open(tmp, "w") as f:
        f.write(conf_text)
    os.replace(tmp, CONF)
    subprocess.run(["fc-cache", "-f"], capture_output=True)
    # Перезапуск waybar — подхватит новый шрифт.
    try:
        import importlib.util
        here = os.path.dirname(os.path.abspath(__file__))
        spec = importlib.util.spec_from_file_location(
            "bar_style", os.path.join(here, "bar_style.py"))
        bar = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bar)
        bar.restart_waybar()
    except Exception:
        subprocess.run(["pkill", "-x", "waybar"], capture_output=True)
    return state


def set_state(value):
    on = value in ("on", "1", "true")
    return _apply(CONF_ON if on else CONF_OFF, "on" if on else "off")


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
    elif args[0] == "set" and len(args) == 2:
        print(set_state(args[1]))
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
