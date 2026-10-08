#!/usr/bin/env python3
"""Нижняя панель: ничего, док или панель задач в стиле XP — одна из трёх. 30.09.2026.

    bottom_bar.py                    автозапуск niri: поднять то, что выбрано
    bottom_bar.py get                none | dock | xp
    bottom_bar.py set none|dock|xp   выбрать (Настройки → Внешний вид)
    bottom_bar.py show               always | hover | button — как появляется XP-панель
    bottom_bar.py show always|hover|button   сменить (панель перезапускается сама)
    bottom_bar.py gap                on | off — зазор между окнами и панелью
    bottom_bar.py gap on|off         off — окна вплотную к панели
    bottom_bar.py toggle             Super+S: показать/спрятать нижнюю панель

«По кнопке» (01.10.2026): панели нет, пока не нажат Super+S; показанная —
отодвигает окна (с зазором или вплотную, как выбрано). Super+S работает и в
других режимах: «всегда» — спрятать/вернуть, «при наведении» — выдвинуть.
У дока Super+S — показать его на мониторе в фокусе (dock.py, SIGUSR1).

Просьба: «только один вид таскбара может быть включён, dock / xp». Выбор — в
~/.config/hypr/state/bottom-bar. Док (dock.py) и XP-панель (xpbar.py) сами
ничего не знают друг о друге: этот скрипт включает одно и гасит другое.
Старый флаг dock-off остаётся рычагом дока: set dock снимает его, set xp/none ставит.
Нет файла выбора — как было до 30.09: док, если он не выключен флагом dock-off.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/bottom-bar")
SHOW = os.path.expanduser("~/.config/hypr/state/xpbar-show")
GAP = os.path.expanduser("~/.config/hypr/state/xpbar-gap")
SHOWS = ("always", "hover", "button")
DOCK_OFF = os.path.expanduser("~/.config/hypr/state/dock-off")
KINDS = ("none", "dock", "xp")


def get():
    try:
        v = open(STATE).read().strip()
        if v in KINDS:
            return v
    except OSError:
        pass
    return "none" if os.path.exists(DOCK_OFF) else "dock"


def get_show():
    try:
        v = open(SHOW).read().strip()
        return v if v in SHOWS else "always"
    except OSError:
        return "always"


def get_gap():
    try:
        return "off" if open(GAP).read().strip() == "off" else "on"
    except OSError:
        return "on"


def pids_of(name):
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) >= 2 and b"python" in os.path.basename(argv[0]) \
                and os.path.basename(argv[1]) == name.encode() and (len(argv) == 2 or argv[2] == b""):
            out.append(int(p))
    return out


def split():
    """Панели по мониторам (panels.py): у мониторов может быть и XP, и док."""
    try:
        sys.path.insert(0, HERE)
        import panels
        return panels.per_monitor()
    except Exception:
        return False


def toggle():
    import signal
    if split():
        for target in ("xpbar.py", "dock.py"):          # Super+S — всем панелям, что есть
            for pid in pids_of(target):
                try:
                    os.kill(pid, signal.SIGUSR1)
                except OSError:
                    pass
        return
    kind = get()
    target = {"xp": "xpbar.py", "dock": "dock.py"}.get(kind)
    if not target:
        return
    pids = pids_of(target)
    if not pids:
        apply(kind)          # не запущена (упала?) — поднять
        return
    for pid in pids:
        try:
            os.kill(pid, signal.SIGUSR1)
        except OSError:
            pass


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(value + "\n")
    os.replace(path + ".tmp", path)


def _run(*args):
    subprocess.run([sys.executable, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply(kind):
    xp = os.path.join(HERE, "xpbar.py")
    dock = os.path.join(HERE, "dock.py")
    if kind == "dock":
        _run(xp, "stop")
        _run(dock, "on")
    elif kind == "xp":
        _run(dock, "off")
        _run(xp, "start")
    else:
        _run(dock, "off")
        _run(xp, "stop")


def main():
    a = sys.argv[1:]
    if not a and split():
        # автозапуск при панелях по мониторам: XP и/или док — по выбору мониторов
        _run(os.path.join(HERE, "panels.py"), "apply", "bottom")
    elif not a:
        apply(get())
    elif a[0] == "get":
        print(get())
    elif a[0] == "set" and len(a) > 1 and a[1] in KINDS:
        _write(STATE, a[1])
        apply(a[1])
        print(a[1])
    elif a[0] == "show" and len(a) == 1:
        print(get_show())
    elif a[0] == "show" and a[1] in SHOWS:
        _write(SHOW, a[1])
        if get() == "xp":
            _run(os.path.join(HERE, "xpbar.py"), "restart")
        print(a[1])
    elif a[0] == "gap" and len(a) == 1:
        print(get_gap())
    elif a[0] == "gap" and a[1] in ("on", "off"):
        _write(GAP, a[1])
        if get() == "xp":
            _run(os.path.join(HERE, "xpbar.py"), "restart")
        print(a[1])
    elif a[0] == "toggle":
        toggle()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
