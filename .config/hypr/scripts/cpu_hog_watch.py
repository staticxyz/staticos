#!/usr/bin/env python3
"""Кто греет процессор: уведомление, если программа долго держит целое ядро. 01.10.2026.

    cpu_hog_watch.py          сторож (автозапуск niri; второй экземпляр выходит)
    cpu_hog_watch.py now      что грузит прямо сейчас (замер 5 с), без сторожа

Просьба: «почему кулеры начинают резко крутиться в один момент? почему процессор
начинает греться?» — в тот раз главный поток Telegram держал ядро на 100 % при
заблокированном экране. Чтобы виновника было видно сразу, а не после разбора:
раз в STEP секунд сторож считает долю процессора по программам (группы — как в
appmem) и, если программа держит больше LIMIT % одного ядра дольше HOLD секунд,
шлёт одно уведомление с именем, нагрузкой и температурой. Повторно про ту же
программу — не чаще раза в QUIET секунд.

Сам почти ничего не стоит: один проход по /proc раз в 30 с (~10 мс).
Игры не трогает: при запущенной CS2 молчит (там нагрузка — норма).
"""
import glob
import importlib.machinery
import importlib.util
import os
import subprocess
import sys
import time

STEP, HOLD, LIMIT, QUIET = 30, 180, 85.0, 1800
HZ = os.sysconf("SC_CLK_TCK")
APPMEM = os.path.expanduser("~/.local/bin/appmem")
GAMES = ("cs2", "gamescope")


def appmem():
    loader = importlib.machinery.SourceFileLoader("appmem", APPMEM)
    spec = importlib.util.spec_from_loader("appmem", loader)
    m = importlib.util.module_from_spec(spec)
    loader.exec_module(m)
    return m


def usage(mem, prev, dt):
    now = mem.scan()
    by = {}
    for pid, p in now.items():
        was = prev.get(pid)
        if was:
            by[mem.label_of(p, now)] = by.get(mem.label_of(p, now), 0.0) + \
                (p["cpu"] - was["cpu"]) / dt * 100
    return now, by


def temp():
    best = None
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            if "x86_pkg_temp" in open(z + "/type").read():
                best = int(open(z + "/temp").read()) // 1000
        except (OSError, ValueError):
            pass
    return best


def gaming(now):
    return any(any(g in (p.get("comm") or "").lower() for g in GAMES) for p in now.values())


def main():
    mem = appmem()
    if sys.argv[1:2] == ["now"]:
        prev = mem.scan()
        time.sleep(5)
        _n, by = usage(mem, prev, 5)
        for name, c in sorted(by.items(), key=lambda x: -x[1])[:8]:
            print("%-28s %s" % (load_text(c), name))
        print("температура: %s °C" % temp())
        return
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"cpu_hog_watch.py" and len(argv) <= 3 \
                    and (len(argv) == 2 or argv[2] == b""):
                return
    prev, t0 = mem.scan(), time.time()
    hot, told = {}, {}
    while True:
        time.sleep(STEP)
        t1 = time.time()
        now, by = usage(mem, prev, t1 - t0)
        prev, t0 = now, t1
        if gaming(now):
            hot.clear()
            continue
        for name in list(hot):
            if by.get(name, 0) < LIMIT:
                del hot[name]
        for name, c in by.items():
            if c < LIMIT:
                continue
            hot.setdefault(name, t1)
            if t1 - hot[name] >= HOLD and t1 - told.get(name, 0) >= QUIET:
                told[name] = t1
                tc = temp()
                subprocess.run(["notify-send", "-a", "System", "-i", "dialog-warning",
                                "%s: нагрузка" % name,
                                "%s · %s%s" % (load_text(c), span_text(t1 - hot[name]),
                                               (" · %d °C" % tc) if tc else "")],
                               capture_output=True)


def load_text(c):
    """Понятная нагрузка. Раньше писалось «держит 119 % ядра» (03.10.2026: «почему
    проценты больше 100?»): проценты считались от ОДНОГО ядра, а многопоточная программа
    занимает несколько. Теперь — сколько ядер и какая это доля всего процессора."""
    n = os.cpu_count() or 1
    cores = ("%.1f" % (c / 100)).replace(".", ",")
    return "%s ядра из %d (%d %% процессора)" % (cores, n, round(c / n))


def span_text(sec):
    m = int(sec // 60)
    return "%d ч %d мин" % (m // 60, m % 60) if m >= 60 else "%d мин" % m


if __name__ == "__main__":
    main()
