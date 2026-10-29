#!/usr/bin/env python3
"""Ctrl+Shift+] — картинка в картинке, бинд niri (cfg/binds.kdl).

Обычно просто пересылает сочетание через wtype: на русской раскладке браузер его иначе не
узнаёт, а другим программам (kitty: следующее окно) ничего не меняется.

Если в фокусе само окошко картинки (29.10.2026, просьба: «в фокусе мини окна нажатие бинда
не работает … чтобы вернуться обратно к браузеру»):
  • Helium — его окошко клавиш страницы не видит. Фокус переводится в главное окно браузера,
    туда уходит Ctrl+Shift+Alt+]: расширение (pip_key.js → pip_bridge.js → bg.js) закрывает
    картинку и открывает её вкладку, как кнопка «Back to tab». Не вышло за 0,8 с — окошко
    закрывается по id.
  • Zen/LibreWolf — Firefox ловит сочетание и в окошке; после закрытия фокус — в браузер.
Журнал — ~/.cache/jarvis/pip-place.log (общий с pip_place.py).
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pip_place import app_of, is_pip, log, request  # noqa: E402

WTYPE = os.path.expanduser("~/.local/bin/wtype")


def send(*mods):
    keys = []
    for m in mods:
        keys += ["-M", m]
    keys += ["-k", "bracketright"]
    for m in reversed(mods):
        keys += ["-m", m]
    subprocess.run([WTYPE, *keys], timeout=3)


def action(*args):
    subprocess.run(["niri", "msg", "action", *args], capture_output=True, timeout=3)


def windows():
    try:
        return request("Windows")["Windows"]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def alive(wid):
    return any(w["id"] == wid for w in windows())


def main():
    try:
        pip = request("FocusedWindow")["FocusedWindow"]
    except (OSError, ValueError, KeyError, TypeError):
        pip = None
    if not pip or not is_pip(pip):
        send("ctrl", "shift")
        return 0
    pid, wid = pip.get("pid"), pip["id"]
    mains = [w for w in windows() if w.get("pid") == pid and not is_pip(w)]
    main_w = max(mains, key=lambda w: tuple((w.get("focus_timestamp") or {}).values()) or (0,),
                 default=None)
    helium = app_of(pip) == "helium"
    if helium:
        if main_w:
            action("focus-window", "--id", str(main_w["id"]))
            time.sleep(0.12)
        send("ctrl", "shift", "alt")
    else:
        send("ctrl", "shift")
    for _ in range(8):
        time.sleep(0.1)
        if not alive(wid):
            break
    else:
        if helium:
            action("close-window", "--id", str(wid))
            log("бинд из окошка %s: расширение не ответило — окошко закрыто по id" % app_of(pip))
    if main_w and not helium:
        action("focus-window", "--id", str(main_w["id"]))
    log("бинд из окошка %s → главное окно %s" % (app_of(pip), main_w and main_w["id"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
