#!/usr/bin/env python3
"""Раскладка в баре с подсветкой Caps Lock — модуль custom/language (23.09.2026).

Штатный niri/language показывает раскладку, но про Caps не знает. Здесь
раскладка берётся у niri (событие KeyboardLayoutSwitched в event-stream, при
старте — keyboard-layouts), Caps — как в layout_osd: по лампочке в sysfs
(/sys/class/leds/*::capslock/brightness, опрос — poll() sysfs не умеет).
На каждое изменение печатается строка JSON для waybar: text, tooltip и
class "caps", когда Caps включён, — по нему CSS красит модуль акцентом.
"""
import glob
import json
import subprocess
import sys
import threading
import time

ICON = "\U000f030c"            # тот же значок клавиатуры, что был в niri/language
CAPS_LEDS = "/sys/class/leds/*::capslock/brightness"
CAPS_POLL = 0.12
SHORT = {"Russian": "RU", "English (US)": "US", "English": "US"}

state = {"layout": "?", "caps": False}
lock = threading.Lock()
last = None


def caps_on():
    for path in glob.glob(CAPS_LEDS):
        try:
            with open(path) as f:
                if f.read().strip() not in ("", "0"):
                    return True
        except OSError:
            pass
    return False


def short(name):
    for k, v in SHORT.items():
        if name.startswith(k):
            return v
    return (name[:2] or "?").upper()


def emit():
    global last
    with lock:
        layout, caps = state["layout"], state["caps"]
    cur = (layout, caps)
    if cur == last:
        return
    last = cur
    out = {"text": "%s %s" % (ICON, layout),
           "tooltip": "Раскладка: %s%s" % (layout, " · Caps Lock включён" if caps else ""),
           "class": "caps" if caps else ""}
    sys.stdout.write(json.dumps(out, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_layouts():
    try:
        d = json.loads(subprocess.run(["niri", "msg", "-j", "keyboard-layouts"],
                                      capture_output=True, text=True, timeout=3).stdout)
        return short(d["names"][d["current_idx"]])
    except Exception:
        return "?"


def watch_layout():
    """Слушать event-stream niri; при обрыве — перечитать и подключиться снова."""
    while True:
        with lock:
            state["layout"] = read_layouts()
        emit()
        try:
            p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            for line in p.stdout:
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                if "KeyboardLayoutSwitched" in ev or "KeyboardLayoutsChanged" in ev:
                    with lock:
                        state["layout"] = read_layouts()
                    emit()
        except OSError:
            pass
        time.sleep(1)


def main():
    threading.Thread(target=watch_layout, daemon=True).start()
    while True:
        c = caps_on()
        with lock:
            changed = c != state["caps"]
            state["caps"] = c
        if changed:
            emit()
        time.sleep(CAPS_POLL)


if __name__ == "__main__":
    main()
