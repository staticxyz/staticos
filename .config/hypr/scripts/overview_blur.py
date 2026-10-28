#!/usr/bin/env python3
"""Размытые обои в обзоре Super+G — на каждом мониторе, 29.10.2026.

Просьба: «почему в Super+G фон обоев не блюрится в мониторе MSI? Как на мониторе от ноута».
С 27.10 обычные обои лежат в подложке niri (layer-rules.kdl: awww-daemon
place-within-backdrop) и закрывают второй демон с размытой копией (wallpaper_blur.py
backdrop). На ноутбуке это незаметно — там «Размытие обоев» включено и на столе, а на
MSI выключено, и обзор показывал резкие обои.

Сторож слушает события niri: обзор открылся — на мониторах, где размытие выключено,
основной демон awww плавно показывает размытую копию (ту же, что у фона обзора);
обзор закрылся — возвращает настоящие обои (с учётом «Пиксельных обоев»). Кэш awww
не трогаем (--no-cache): после перезапуска демон поднимет настоящие обои.

    overview_blur.py          сторож (живёт в staticos_host)
    overview_blur.py check    самопроверка (jarvis-doctor)
    overview_blur.py off|on   выключить / включить (файл state/overview-blur-off)
"""
import json
import os
import socket
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wallpaper_blur as wb  # noqa: E402

OFF = os.path.expanduser("~/.config/hypr/state/overview-blur-off")
FADE = ["--transition-type", "fade", "--transition-duration", "0.3", "--transition-fps", "60"]


def put(name, path):
    subprocess.run(["awww", "img", "--no-cache", "--outputs", name, *FADE, path],
                   capture_output=True, timeout=10)


def sharp_outputs():
    state = wb.read_state()
    return [n for n, _ in wb.outputs() if state.get(n, "off") != "on"]


def opened():
    display = wb.shown()
    for name in sharp_outputs():
        path = wb.original(name, display)       # запоминает исходник, пока он на экране
        target = wb.blurred(path) if path else None
        if target and display.get(name) != target:
            put(name, target)


def closed():
    display = wb.shown()
    for name in sharp_outputs():
        cur = display.get(name) or ""
        if not cur.startswith(wb.CACHE):       # уже настоящие (или обои сменили в обзоре)
            continue
        path = wb.original(name, display)
        if path:
            put(name, wb.pixel_base(path))


def run():
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall(b'"EventStream"\n')
    for line in s.makefile("rb"):
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if not isinstance(ev, dict) or "OverviewOpenedOrClosed" not in ev:
            continue
        if os.path.exists(OFF):
            continue
        is_open = ev["OverviewOpenedOrClosed"].get("is_open")
        try:                                    # первое событие — текущее состояние: после
                                                # падения посреди обзора closed() вернёт обои
            (opened if is_open else closed)()
        except Exception as e:
            print("overview_blur: %r" % (e,), file=sys.stderr)
    return 1                                    # niri закрылся — хозяин перезапустит


def check():
    bad = []
    if not wb.shown():
        bad.append("демон обоев awww не отвечает")
    r = subprocess.run(["awww", "img", "--help"], capture_output=True, text=True)
    if "--no-cache" not in r.stdout:
        bad.append("у awww img нет --no-cache")
    try:
        with open(os.path.expanduser("~/.config/hypr/state/staticos-host.json")) as f:
            if "overview_blur.py" not in json.load(f):
                bad.append("нет в staticos-host.json — сторож не запущен")
    except (OSError, ValueError):
        bad.append("не прочитать staticos-host.json")
    for p in bad:
        print("✗", p)
    print("overview_blur: %s" % ("в порядке" + (" (выключен)" if os.path.exists(OFF) else "")
                                 if not bad else "проблем %d" % len(bad)))
    return 1 if bad else 0


def main():
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd == "check":
        return check()
    if cmd == "off":
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
        closed()
        print("выключено")
        return 0
    if cmd == "on":
        try:
            os.remove(OFF)
        except OSError:
            pass
        print("включено")
        return 0
    return run()


if __name__ == "__main__":
    sys.exit(main())
