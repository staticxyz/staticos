#!/usr/bin/env python3
"""Звук в верхнем баре: громкость динамиков или микрофона, СКМ переключает. 13.10.2026.

Просьба: «если кликнуть на иконку звука на СКМ — переключать на микрофон, если ещё раз
то обратно на звук». Штатный модуль waybar pulseaudio показывать то одно, то другое не
умеет (формат задаётся один раз при запуске), поэтому модуль свой — custom/volume, вид
тот же: значок, узкий пробел, проценты; «Muted» при выключенном. Микрофон — акцентом
(класс mic, как было у pulseaudio#microphone).

Обновляется по `pactl subscribe` (только события sink/source/server), без опроса.
pactl — с PDEATHSIG: сироты pactl однажды душили pipewire-pulse.

    bar_volume.py [ВЫХОД]        вывод для waybar (wb_share volume-ВЫХОД — свой у каждого бара)
    bar_volume.py once [ВЫХОД]   одна строка и выход (проверка)
    bar_volume.sh mode|up|down|mute|popup [ВЫХОД]     щелчки и колёсико (сам скрипт — рядом)

Два монитора (29.10.2026, просьба: «иконка микрофона и громкости отображаются одинаково в
обеих мониторах… где-то микро, а где-то звук системы; только если стоит один монитор —
переключаться»): пока включены оба (sysfs drm: connected + enabled), у бара каждого монитора
свой режим (jarvis-barvol.mode.<ВЫХОД>): сначала ноутбук (eDP*) — микрофон, внешний — звук,
СКМ переключает только свой бар («СКМ должна работать всегда», 29.10). Остался один —
общий файл jarvis-barvol.mode, как раньше. Число мониторов перечитывается раз в 5 с.

Режим лежит в $XDG_RUNTIME_DIR/jarvis-barvol.mode (после перезагрузки — снова звук).
Откат: в ~/.config/waybar/config.jsonc в group/audio вернуть "pulseaudio" вместо
"custom/volume", `python3 ~/.config/niri/scripts/waybar_niri.py`, barfix.
"""
import ctypes
import glob
import json
import os
import re
import selectors
import signal
import subprocess
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
MODE = os.path.join(RUN, "jarvis-barvol.mode")
OUT = next((a for a in sys.argv[1:] if a != "once"), "")
PID = os.path.join(RUN, "jarvis-barvol%s.pid" % ("." + OUT if OUT else ""))
SINK_ICONS = ("󰕿", "󰖀", "󰕾")
GAP = "<span font_size='50%'> </span>"
_libc = ctypes.CDLL(None)


def _pdeathsig():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)     # PR_SET_PDEATHSIG


def screens():
    """Сколько мониторов сейчас в работе (подключён и включён)."""
    n = 0
    for d in glob.glob("/sys/class/drm/card*-*"):
        try:
            if open(d + "/status").read().strip() == "connected" and \
                    open(d + "/enabled").read().strip() == "enabled":
                n += 1
        except OSError:
            pass
    return n


def own():
    """При двух мониторах — свой файл режима у бара, иначе None (общий файл)."""
    return MODE + "." + OUT if OUT and screens() >= 2 else None


def mode():
    f = own()
    try:
        return "mic" if open(f or MODE).read().strip() == "mic" else "sink"
    except OSError:
        return "mic" if f and OUT.startswith("eDP") else "sink"   # по умолчанию: ноутбук — микрофон


def wp(*a):
    try:
        return subprocess.run(["wpctl"] + list(a), capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return ""


def state():
    m = mode()
    dev = "@DEFAULT_AUDIO_SOURCE@" if m == "mic" else "@DEFAULT_AUDIO_SINK@"
    out = wp("get-volume", dev)
    v = re.search(r"Volume:\s*([\d.]+)", out)
    vol = round(float(v.group(1)) * 100) if v else None
    muted = "MUTED" in out
    desc = re.search(r'node\.description = "([^"]*)"', wp("inspect", dev))
    desc = desc.group(1) if desc else ""
    if vol is None:
        icon, text = ("󰍭" if m == "mic" else "󰝟"), "--"
    elif muted:
        icon, text = ("󰍭" if m == "mic" else "󰝟"), "Muted"
    else:
        icon = "󰍬" if m == "mic" else SINK_ICONS[min(2, vol * 3 // 100)]
        text = "%d%%" % vol
    cls = [m] + (["muted"] if muted else [])
    what = "Микрофон" if m == "mic" else "Звук"
    tip = "%s: %s\nСредняя кнопка — %s" % (what, desc or "?", "звук" if m == "mic" else "микрофон")
    return {"text": icon + GAP + text, "class": cls, "tooltip": tip,
            "percentage": vol or 0, "alt": m}


def emit(last=[None]):
    s = json.dumps(state(), ensure_ascii=False)
    if s != last[0]:
        last[0] = s
        sys.stdout.write(s + "\n")
        sys.stdout.flush()


def serve():
    try:
        with open(PID, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    r, w = os.pipe()
    os.set_blocking(w, False)
    signal.set_wakeup_fd(w)
    signal.signal(signal.SIGUSR1, lambda *_: None)   # bar_volume.sh mode — перечитать режим
    sel = selectors.DefaultSelector()
    sel.register(r, selectors.EVENT_READ, "sig")
    emit()
    while True:
        try:
            p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, preexec_fn=_pdeathsig, text=True, bufsize=1)
        except OSError:
            p = None
        if p is not None:
            sel.register(p.stdout, selectors.EVENT_READ, "pa")
        due = None
        seen = screens()
        while True:
            ev = sel.select(5 if due is None else max(0, due - time.monotonic()))
            if not ev:
                if due is not None:
                    due = None
                    emit()
                elif screens() != seen:                 # монитор подключили / отключили
                    seen = screens()
                    emit()
                continue
            dead = False
            for key, _m in ev:
                if key.data == "sig":
                    os.read(r, 64)
                    emit()
                    continue
                line = key.fileobj.readline()
                if not line:
                    dead = True
                elif re.search(r"on (sink|source|server) #", line):
                    due = due or time.monotonic() + 0.04    # пачку событий — одним выводом
            if dead:
                sel.unregister(p.stdout)
                p.wait()
                break
        time.sleep(2)                                    # pipewire-pulse перезапускали — заново
        emit()


if __name__ == "__main__":
    if sys.argv[1:2] == ["once"]:
        print(json.dumps(state(), ensure_ascii=False))
    else:
        try:
            serve()
        except (BrokenPipeError, KeyboardInterrupt):
            pass
