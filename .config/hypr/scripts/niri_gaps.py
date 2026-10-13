#!/usr/bin/env python3
"""Зазоры между окнами и до края экрана (niri gaps).

    niri_gaps.py get        текущее значение (px)
    niri_gaps.py set N      установить (0..64)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

LAYOUT = os.path.expanduser("~/.config/niri/cfg/layout.kdl")
NIRI_DIR = os.path.expanduser("~/.config/niri")
LO, HI, DEFAULT = 0, 64, 16


def get():
    try:
        text = open(LAYOUT).read()
        m = re.search(r"^\s*gaps\s+(\d+)", text, re.M)
        return int(m.group(1)) if m else DEFAULT
    except OSError:
        return DEFAULT


def set_val(n):
    n = max(LO, min(HI, int(n)))
    try:
        text = open(LAYOUT).read()
    except OSError:
        return "layout.kdl не читается"
    new_text = re.sub(r"(^\s*gaps\s+)\d+", lambda m: m.group(1) + str(n), text, flags=re.M)
    if new_text == text:
        return "уже %d" % n
    tmpdir = tempfile.mkdtemp(prefix="niri-gaps-")
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
    return "зазор: %d px" % n


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "get":
        print(get())
        return 0
    if args[0] == "set" and len(args) == 2:
        try:
            print(set_val(int(float(args[1]))))
        except ValueError:
            print("нужно число", file=sys.stderr)
            return 1
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
