#!/usr/bin/env python3
"""Стиль системы по мониторам: Обычный / Skeet / Beta. 04.10.2026.

    system_style.py get [МОНИТОР]          стиль монитора (без имени — монитора в фокусе)
    system_style.py set STYLE [МОНИТОР]    задать (без имени — всем мониторам)
    system_style.py widgets МОНИТОР [system|classic]   виджеты: в стиле монитора или без рамок
    system_style.py watch                  сторож: стиль окон — по монитору в фокусе
    system_style.py apply                  применить для монитора в фокусе (один раз)

Просьба: «единый стиль для всей системы, чтобы не выбирать для каждого окна отдельно», затем
«сделай раздельные стили для разных мониторов, чтобы разная была». Итог: у каждого монитора
свой стиль, все окна на нём — в этом стиле.
  * виджеты на обоях живут на своём мониторе — им стиль пишется прямо (desktop_widgets look);
  * Настройки, буфер обмена, Recorder и меню «Пуск» открываются там, где фокус, и читают
    свои файлы стиля при показе. Сторож следит за фокусом мониторов (поток событий niri) и,
    когда фокус переходит на монитор с другим стилем, переписывает эти файлы. Пишет файлы
    сам, без запуска их скриптов: смена фокуса не должна стоить запуска питона.
Состояние — ~/.config/hypr/state/system-style ({"eDP-1": "skeet", "DP-4": "default"}).
"""
import ctypes
import json
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ST = os.path.expanduser("~/.config/hypr/state")
STATE = os.path.join(ST, "system-style")
STYLES = ("default", "skeet", "beta")
# файлы стиля окон, которые открываются на мониторе в фокусе
FILES = {"settings-skin": None, "clipboard-style": None, "recorder-style": None,
         "start-menu-look": None, "calendar-style": None,
         "alttab-style": None}


def niri(*args):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", *args], capture_output=True,
                                         text=True, timeout=3).stdout or "null")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def outputs():
    return sorted((niri("outputs") or {}).keys())


def focused():
    return (niri("focused-output") or {}).get("name")


def load():
    try:
        d = json.load(open(STATE))
        if isinstance(d, dict):
            return {k: v for k, v in d.items() if v in STYLES}
    except (OSError, ValueError):
        pass
    try:                                          # старый формат — одно слово на все
        v = open(STATE).read().strip()
        if v in STYLES:
            return {o: v for o in outputs()}
    except OSError:
        pass
    return {}


def save(d):
    os.makedirs(ST, exist_ok=True)
    with open(STATE + ".tmp", "w") as f:
        json.dump(d, f)
    os.replace(STATE + ".tmp", STATE)


def style_of(out, d=None):
    d = load() if d is None else d
    if out in d:
        return d[out]
    try:                                          # не задан — вид Настроек
        v = open(os.path.join(ST, "settings-skin")).read().strip()
        return v if v in STYLES else "default"
    except OSError:
        return "default"


def write(name, value):
    path = os.path.join(ST, name)
    try:
        if open(path).read().strip() == value:
            return False
    except OSError:
        pass
    with open(path + ".tmp", "w") as f:
        f.write(value + "\n")
    os.replace(path + ".tmp", path)
    return True


def apply_focus(out=None):
    """Файлы стиля «окон в фокусе» — под стиль монитора out (по умолчанию в фокусе)."""
    out = out or focused()
    if not out:
        return None
    st = style_of(out)
    for name in FILES:
        write(name, st)
    return st


def widgets_look(out, st):
    dw = os.path.join(HERE, "desktop_widgets.py")
    cur = subprocess.run(["python3", dw, "look", out], capture_output=True, text=True).stdout.strip()
    if cur != "classic":                          # «Без рамок» монитора не трогаем
        subprocess.run(["python3", dw, "look", out, "xp" if st == "default" else st],
                       capture_output=True)


def watch():
    """Сторож: переписать файлы при смене монитора в фокусе. Спит на потоке событий."""
    libc = ctypes.CDLL(None)
    last = apply_focus()
    while True:
        try:
            p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True,
                                 preexec_fn=lambda: libc.prctl(1, signal.SIGTERM, 0, 0, 0))
            wss = {}
            for line in p.stdout:
                if line.startswith('{"WorkspacesChanged"'):
                    wss = {w["id"]: w for w in json.loads(line)["WorkspacesChanged"]["workspaces"]}
                elif line.startswith('{"WorkspaceActivated"'):
                    ev = json.loads(line)["WorkspaceActivated"]
                    if ev.get("focused"):
                        out = (wss.get(ev["id"]) or {}).get("output")
                        if out and out != last:
                            last = out
                            apply_focus(out)
            p.wait()
        except (OSError, ValueError, KeyError):
            pass
        import time
        time.sleep(3)


def main():
    a = sys.argv[1:] or ["get"]
    if a[0] == "get":
        print(style_of(a[1] if len(a) > 1 else focused()))
    elif a[0] == "set" and len(a) > 1 and a[1] in STYLES:
        d = load()
        outs = [a[2]] if len(a) > 2 else outputs()
        for o in outs:
            d[o] = a[1]
            widgets_look(o, a[1])
        save(d)
        apply_focus()
        print(a[1])
    elif a[0] == "widgets" and len(a) > 1:
        dw = os.path.join(HERE, "desktop_widgets.py")
        cur = subprocess.run(["python3", dw, "look", a[1]], capture_output=True, text=True).stdout.strip()
        if len(a) == 2:
            print("classic" if cur == "classic" else "system")
        elif a[2] in ("system", "classic"):
            st = style_of(a[1])
            subprocess.run(["python3", dw, "look", a[1],
                            "classic" if a[2] == "classic" else ("xp" if st == "default" else st)],
                           capture_output=True)
            print(a[2])
    elif a[0] == "apply":
        print(apply_focus())
    elif a[0] == "watch":
        watch()
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
