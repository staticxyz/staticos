#!/usr/bin/env python3
"""Кнопки питания на экране блокировки (hyprlock onclick). 30.09.2026.

    lock_power.py click <действие>   щелчок по кнопке (из onclick hyprlock)
    lock_power.py label <действие>   текст кнопки (cmd[update:250] label)
    lock_power.py hint               строка-подсказка под кнопками

Действия: shutdown, reboot, suspend, logout.

Просьба: «аккуратно реализуем». Поверх экрана блокировки другие окна не видны
(ext-session-lock), так что окно с отсчётом, как в wlogout, здесь не покажешь.
Поэтому двойное подтверждение: первый щелчок только «взводит» кнопку — она
краснеет, под кнопками подсказка; второй щелчок по ТОЙ ЖЕ кнопке в течение
ARM_S секунд выполняет. Случайный щелчок ничего не делает. Сон — сразу, без
подтверждения: он безопасен, экран остаётся заблокированным.
"""
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-lock-power.json")
ARM_S = 5
ACTIONS = {
    # ключ: (значок, подпись, подтверждение нужно?)
    "logout": ("\U000f0343", "Выход", True),
    "suspend": ("\U000f0904", "Сон", False),
    "reboot": ("\U000f0709", "Перезагрузка", True),
    "shutdown": ("\U000f0425", "Выключение", True),
}


def command(key):
    if key == "logout":
        if popup_theme.on_niri():
            return ["niri", "msg", "action", "quit", "--skip-confirmation"]
        return ["hyprctl", "dispatch", "hl.dsp.exit()"]
    return {"suspend": ["systemctl", "suspend"], "reboot": ["systemctl", "reboot"],
            "shutdown": ["systemctl", "poweroff"]}[key]


def armed():
    try:
        st = json.load(open(STATE))
        if time.time() - st["t"] < ARM_S:
            return st["key"], ARM_S - (time.time() - st["t"])
    except (OSError, ValueError, KeyError):
        pass
    return None, 0


def click(key):
    if key not in ACTIONS:
        return
    cur, _ = armed()
    if not ACTIONS[key][2] or cur == key:
        try:
            os.remove(STATE)
        except OSError:
            pass
        subprocess.Popen(command(key), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return
    with open(STATE, "w") as f:
        json.dump({"key": key, "t": time.time()}, f)


def label(key):
    icon = ACTIONS.get(key, ("?",))[0]
    cur, _ = armed()
    if cur == key:
        err = popup_theme.palette()["error"]
        print('<span foreground="%s">%s</span>' % (err, icon))
    else:
        print(icon)


def hint():
    cur, left = armed()
    if cur:
        err = popup_theme.palette()["error"]
        print('<span foreground="%s">Ещё раз — %s (%d с)</span>'
              % (err, ACTIONS[cur][1].lower(), int(left) + 1))
    else:
        print("")


def main():
    a = sys.argv[1:]
    if a[:1] == ["click"] and len(a) > 1:
        click(a[1])
    elif a[:1] == ["label"] and len(a) > 1:
        label(a[1])
    elif a[:1] == ["hint"]:
        hint()
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
