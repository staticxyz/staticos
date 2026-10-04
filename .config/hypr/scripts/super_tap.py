#!/usr/bin/env python3
"""Одиночное нажатие Super — меню «Пуск» нижней XP-панели. 01.10.2026.

    super_tap.py        сторож (автозапуск niri)

Просьба: «когда нижняя панель открыта — по Super должен открываться Пуск, но
не конфликтовать с биндами Super+что-то». niri не умеет бинд на один
модификатор, поэтому клавиатуры читаются напрямую (/dev/input/event*, нужна
группа input — она есть). «Тап» засчитывается, только если:
  * Super нажат и отпущен быстрее TAP_S;
  * пока он был нажат, не нажималась никакая другая клавиша (Super+T, Super+1…
    тапом не считаются — ни при каком порядке отпускания);
  * XP-панель выбрана и сейчас на экране (флаг $XDG_RUNTIME_DIR/xpbar-visible,
    его ведёт xpbar.py). Спрятанная панель («по Super+S», «при наведении») —
    Super ничего не открывает.
Повторный тап при открытом меню его закрывает (start_menu.py — переключатель).

Читаются только клавиатуры (обработчик kbd в /proc/bus/input/devices), не мышь:
мышь шлёт сотни событий движения в секунду, а связки Super+мышь (перетаскивание,
колёсико) и так дольше TAP_S. Процессор — ноль: спит в select, пока не нажата
клавиша. Клавиатуры переподключаются (Razer после сна) — список перечитывается
при ошибке чтения и раз в RESCAN_S.
"""
import os
import select
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-visible")
TAP_S = 0.35
RESCAN_S = 10
EV_KEY = 1
META = {125, 126}                     # KEY_LEFTMETA, KEY_RIGHTMETA
FMT = "llHHi"
SIZE = struct.calcsize(FMT)


def keyboards():
    out = []
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return out
    for b in blocks:
        h = next((l for l in b.splitlines() if l.startswith("H: Handlers=")), "")
        ev = next((l for l in b.splitlines() if l.startswith("B: EV=")), "")
        if "kbd" not in h or not ev:
            continue
        # настоящая клавиатура шлёт и EV_KEY, и EV_MSC/EV_REP; у кнопки питания EV=3
        if int(ev.split("=")[1], 16) & 0x100000 == 0:      # EV_REP — автоповтор
            continue
        for tok in h.split():
            if tok.startswith("event"):
                out.append("/dev/input/" + tok)
    return out


def open_all(paths):
    fds = {}
    for p in paths:
        try:
            fds[os.open(p, os.O_RDONLY | os.O_NONBLOCK)] = p
        except OSError:
            pass
    return fds


def xpbar_pids():
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) >= 2 and os.path.basename(argv[1]) == b"xpbar.py" and (len(argv) == 2 or argv[2] == b""):
            out.append(int(p))
    return out


def fire():
    if not os.path.exists(FLAG):
        return
    # Меню живёт в процессе панели — ей сигнал SIGUSR2, открывается мгновенно.
    pids = xpbar_pids()
    if pids:
        import signal
        for pid in pids:
            try:
                os.kill(pid, signal.SIGUSR2)
            except OSError:
                pass
        return
    try:
        out = subprocess.run(["niri", "msg", "-j", "focused-output"], capture_output=True,
                             text=True, timeout=1).stdout
        import json
        conn = (json.loads(out) or {}).get("name", "")
    except Exception:
        conn = ""
    subprocess.Popen([sys.executable, os.path.join(HERE, "start_menu.py")] + ([conn] if conn else []),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def main():
    fds = open_all(keyboards())
    next_scan = time.monotonic() + RESCAN_S
    down_at = None          # когда нажат Super
    dirty = False           # за время удержания нажата другая клавиша
    held = set()            # какие клавиши сейчас нажаты (кроме Super)
    while True:
        try:
            r, _, _ = select.select(list(fds), [], [], RESCAN_S)
        except (OSError, ValueError):
            r = []
        broken = False
        for fd in r:
            try:
                data = os.read(fd, SIZE * 64)
            except BlockingIOError:
                continue
            except OSError:
                broken = True
                continue
            for i in range(0, len(data) - SIZE + 1, SIZE):
                _s, _us, typ, code, val = struct.unpack_from(FMT, data, i)
                if typ != EV_KEY or val == 2:          # 2 — автоповтор
                    continue
                if code in META:
                    if val == 1:
                        down_at, dirty = time.monotonic(), bool(held)
                    elif down_at is not None:
                        if not dirty and time.monotonic() - down_at <= TAP_S:
                            fire()
                        down_at = None
                else:
                    if val == 1:
                        held.add(code)
                        if down_at is not None:
                            dirty = True
                    else:
                        held.discard(code)
        now = time.monotonic()
        if broken or now >= next_scan:
            want = set(keyboards())
            if broken or want != set(fds.values()):
                for fd in list(fds):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                fds = open_all(want)
                held.clear()
                down_at = None
            next_scan = now + RESCAN_S


if __name__ == "__main__":
    # один сторож на сеанс
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"super_tap.py":
                sys.exit(0)
    main()
