#!/usr/bin/env python3
"""Рамки окон niri (border).

    niri_border.py get-width       текущая ширина (px)
    niri_border.py set-width N     установить ширину (0..12)
    niri_border.py get-on          on / off
    niri_border.py set-on on|off   включить / выключить
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

LAYOUT = os.path.expanduser("~/.config/niri/cfg/layout.kdl")
NIRI_DIR = os.path.expanduser("~/.config/niri")
WIDTH_LO, WIDTH_HI, WIDTH_DEFAULT = 0, 12, 5


def _read():
    try:
        return open(LAYOUT).read()
    except OSError:
        return ""


def _write_and_reload(new_text):
    tmpdir = tempfile.mkdtemp(prefix="niri-border-")
    try:
        shutil.copytree(NIRI_DIR, os.path.join(tmpdir, "niri"), symlinks=True,
                        ignore=shutil.ignore_patterns("*.tmp", "*.bak*", "__pycache__"))
        with open(os.path.join(tmpdir, "niri", "cfg", "layout.kdl"), "w") as f:
            f.write(new_text)
        r = subprocess.run(["niri", "validate", "-c",
                            os.path.join(tmpdir, "niri", "config.kdl")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return "ошибка валидации: " + (r.stderr or r.stdout).strip().splitlines()[-1]
        tmp = LAYOUT + ".tmp"
        with open(tmp, "w") as f:
            f.write(new_text)
        os.replace(tmp, LAYOUT)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    subprocess.run(["niri", "msg", "action", "load-config-file"], capture_output=True)
    return "OK"


def get_width():
    text = _read()
    # Ищем border { ... width N ... }
    m = re.search(r"border\s*\{[^}]*?\bwidth\s+(\d+)", text, re.S)
    return int(m.group(1)) if m else WIDTH_DEFAULT


def set_width(n):
    n = max(WIDTH_LO, min(WIDTH_HI, int(n)))
    text = _read()
    new_text = re.sub(r"(border\s*\{[^}]*?\bwidth\s+)\d+",
                      lambda m: m.group(1) + str(n), text, flags=re.S)
    if new_text == text:
        return "уже %d" % n
    msg = _write_and_reload(new_text)
    return ("ширина рамки: %d px" % n) if msg == "OK" else msg


def get_on():
    text = _read()
    m = re.search(r"border\s*\{([^}]*)\}", text, re.S)
    if not m:
        return "off"
    block = m.group(1)
    if re.search(r"^\s*off\b", block, re.M):
        return "off"
    if re.search(r"^\s*on\b", block, re.M):
        return "on"
    return "on"


def set_on(state):
    on = state in ("on", "1", "true")
    text = _read()
    # Заменяем первую строку в блоке border: on → off или наоборот
    def replace_border_block(m):
        block = m.group(1)
        block = re.sub(r"^\s*(on|off)\b", ("    on" if on else "    off"), block, flags=re.M)
        return "border {" + block + "}"
    new_text = re.sub(r"border\s*\{([^}]*)\}", replace_border_block, text, flags=re.S)
    if new_text == text:
        return "уже %s" % ("on" if on else "off")
    msg = _write_and_reload(new_text)
    return ("рамки: %s" % ("включены" if on else "выключены")) if msg == "OK" else msg


def main():
    args = sys.argv[1:] or ["get-width"]
    cmd = args[0]
    if cmd == "get-width":
        print(get_width())
    elif cmd == "set-width" and len(args) == 2:
        try:
            print(set_width(int(float(args[1]))))
        except ValueError:
            print("нужно число", file=sys.stderr)
            return 1
    elif cmd == "get-on":
        print(get_on())
    elif cmd == "set-on" and len(args) == 2:
        print(set_on(args[1]))
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
