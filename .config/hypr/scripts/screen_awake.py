#!/usr/bin/env python3
"""«Не отключать экран» — спутник Savage Mode.

    screen_awake.py get            on / off
    screen_awake.py on|off|toggle

Savage Mode держит машину бодрой: сна нет. Но экран при этом всё равно
приглушается и блокируется — так решено 12.09.2026, потому что незапертый
экран это дыра, а не удобство. Этот выключатель отменяет и приглушение с
блокировкой: экран остаётся зажжённым, пока Savage Mode включён.

Работает ТОЛЬКО вместе с Savage Mode: скрипты idle_dim и idle_lock требуют
обоих условий сразу. Поэтому выключение Savage Mode само сбрасывает этот флаг
(savage_battery.toggle_savage) — иначе он тихо ждал бы в файле и однажды
удивил бы незапертым экраном.
"""
import os
import sys

STATE = os.path.expanduser("~/.config/hypr/state/screen-awake")


def get():
    try:
        with open(STATE) as f:
            return f.read().strip() == "on"
    except OSError:
        return False


def set_state(on):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write("on\n" if on else "off\n")
    os.replace(tmp, STATE)
    return on


def main():
    arg = (sys.argv[1:] or ["get"])[0]
    if arg == "get":
        print("on" if get() else "off")
    elif arg in ("on", "off"):
        print("on" if set_state(arg == "on") else "off")
    elif arg == "toggle":
        print("on" if set_state(not get()) else "off")
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
