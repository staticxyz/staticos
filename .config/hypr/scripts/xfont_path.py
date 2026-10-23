#!/usr/bin/env python3
"""Пиксельный шрифт в окне «Обновление Steam…» (22.10.2026).

    xfont_path.py          сторож (в хозяине staticOS): новый Xwayland → поставить путь
    xfont_path.py once     поставить путь сейчас
    xfont_path.py check    путь на месте и ClearlyU → PxPlus

Бутстрап Steam (ubuntu12_32/steam, UpdateUI «xwin») рисует окно X11 core-шрифтами и просит
`-mutt-clearlyu-…-120-…-iso10646-1`. Просьба: «Где пиксельность». Xwayland масштабируемые
шрифты не открывает (нет freetype-бэкенда), поэтому PxPlus переведён в растровый BDF
(~/.local/share/x11-fonts/steam/pxplus-8.bdf, 16 px в окно 400 px не влезает), а fonts.alias
там же подменяет им ClearlyU. Каталог ставится первым в путь шрифтов Xwayland; путь живёт до
перезапуска Xwayland — сторож раз в 15 с смотрит его pid и ставит путь заново.

Xlib — в дочернем процессе: при обрыве связи с X-сервером Xlib зовёт exit(), а сторож
живёт потоком в хозяине. Откат: убрать из ~/.config/hypr/state/staticos-host.json.
Без пакетов xorg-fonts-misc + mkfontdir /usr/share/fonts/misc ClearlyU нет вовсе, и
кириллица в окне — квадратами.
"""
import ctypes
import os
import subprocess
import sys
import time

FONT_DIR = os.path.expanduser("~/.local/share/x11-fonts/steam")
ASK = b"-mutt-clearlyu-medium-r-normal--*-120-*-*-p-*-iso10646-1"


def xwayland():
    """(pid, ':N') живого Xwayland пользователя или None."""
    me = os.getuid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            if os.stat("/proc/" + pid).st_uid != me:
                continue
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                argv = f.read().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == b"Xwayland" and len(argv) > 1 \
                and argv[1].startswith(b":"):
            return int(pid), argv[1].decode()
    return None


def _x():
    x = ctypes.CDLL("libX11.so.6")
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XGetFontPath.restype = ctypes.POINTER(ctypes.c_char_p)
    x.XGetFontPath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int)]
    x.XSetFontPath.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p), ctypes.c_int]
    x.XListFonts.restype = ctypes.POINTER(ctypes.c_char_p)
    x.XListFonts.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    d = x.XOpenDisplay(None)
    if not d:
        sys.exit("нет X-дисплея")
    return x, d


def get_path(x, d):
    n = ctypes.c_int()
    p = x.XGetFontPath(d, ctypes.byref(n))
    return [p[i] for i in range(n.value)]


def set_path():
    """Каталог первым; повторная установка перечитывает fonts.dir/fonts.alias."""
    x, d = _x()
    want = FONT_DIR.encode()
    new = [want] + [p for p in get_path(x, d) if p != want]
    arr = (ctypes.c_char_p * len(new))(*new)
    x.XSetFontPath(d, arr, len(new))
    x.XSync(d, 0)
    print("путь:", b", ".join(get_path(x, d)).decode())


def check():
    x, d = _x()
    path = get_path(x, d)
    ok = bool(path) and path[0] == FONT_DIR.encode()
    n = ctypes.c_int()
    r = x.XListFonts(d, ASK, 1, ctypes.byref(n))
    first = r[0].decode() if n.value else "—"
    alias = os.path.join(FONT_DIR, "fonts.alias")
    aliased = os.path.exists(alias) and first in open(alias).read()
    print("каталог первым в пути: %s; ClearlyU → %s: %s" % (
        "да" if ok else "нет", "PxPlus" if aliased else first, "ok" if aliased else "НЕТ"))
    return 0 if ok and aliased else 1


def run_child(arg, disp):
    env = dict(os.environ, DISPLAY=disp)
    return subprocess.run([sys.executable, os.path.abspath(__file__), arg], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)


def watch():
    seen = None
    while True:
        xw = xwayland()
        if xw and xw[0] != seen:
            time.sleep(2)                       # дать Xwayland подняться
            try:
                if run_child("_once", xw[1]).returncode == 0:
                    seen = xw[0]
            except (OSError, subprocess.TimeoutExpired):
                pass
        time.sleep(15)


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "watch"
    if arg in ("_once", "_check"):              # дочерний процесс с DISPLAY нужного Xwayland
        return set_path() if arg == "_once" else check()
    if arg == "watch":
        watch()
        return 0
    if arg not in ("once", "check"):
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    xw = xwayland()
    if not xw:
        print("Xwayland не запущен")
        return 0
    r = run_child("_" + arg, xw[1])
    print((r.stdout or r.stderr).strip())
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
