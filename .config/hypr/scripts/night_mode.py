#!/usr/bin/env python3
"""Ночной режим — единственная точка включения ночного света.

    night_mode.py get           -> "on 65" / "off 65"
    night_mode.py on [теплота]  включить (теплота 0..100, по умолчанию прошлая)
    night_mode.py off           выключить

Почему отдельным скриптом: раньше и «Энергия», и «Настройки» звали
`hyprctl hyprsunset ...` каждая по-своему, и обе молча делали вид, что всё
получилось, когда демон не запущен. Именно так ночной режим и «сломался»
12.09.2026: hyprsunset не работал, hyprctl упирался в несуществующий сокет и
возвращал ошибку, которую никто не читал. Теперь демон при необходимости
поднимается сам (ensure), а ошибки видны в выводе.

Теплота 0..100 переводится в температуру 6500..2800 K — как было в панели.
Состояние хранится в ~/.cache/night-mode: "on|off <время> <теплота>". Время
нужно расписанию (22:00–5:00): если ручное переключение было ДО последней
границы расписания, верно расписание, а не оно.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

STATE = os.path.expanduser("~/.cache/night-mode")
DEFAULT_WARMTH = 65


def running():
    return subprocess.run(["pidof", "hyprsunset"], capture_output=True).returncode == 0


def ensure():
    """Поднять hyprsunset, если он не работает. Возвращает True, если жив."""
    if running():
        return True
    try:
        subprocess.Popen(["hyprsunset"], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        return False
    for _ in range(20):                      # сокет появляется не мгновенно
        time.sleep(0.15)
        if running():
            return True
    return False


def read_state():
    try:
        with open(STATE) as f:
            parts = f.read().split()
        on = parts[0] == "on"
        ts = float(parts[1]) if len(parts) > 1 else 0.0
        warmth = int(float(parts[2])) if len(parts) > 2 else DEFAULT_WARMTH
        return on, ts, warmth
    except (OSError, ValueError, IndexError):
        return False, 0.0, DEFAULT_WARMTH


def write_state(on, warmth):
    try:
        with open(STATE, "w") as f:
            f.write("%s %f %d\n" % ("on" if on else "off", time.time(), warmth))
    except OSError:
        pass


def temperature(warmth):
    """Теплота 0..100 -> температура 6500..2800 K."""
    warmth = max(0, min(100, int(warmth)))
    return int(6500 - warmth / 100.0 * 3700)


def apply(on, warmth=None):
    """Включить/выключить ночной свет. Возвращает текст ответа исполнителя.

    Сами команды экрану отдаёт screen_gamma: гаммой владеет один клиент, и
    ночной свет с приглушением по простою должны применяться вместе.
    """
    if warmth is None:
        warmth = read_state()[2]
    write_state(on, max(0, min(100, int(warmth))))
    import screen_gamma
    return screen_gamma.apply_state()


def scheduled_on(now=None):
    """Должен ли ночной свет гореть СЕЙЧАС по расписанию 22:00–5:00.

    Ручное переключение сильнее расписания, но только до ближайшей границы:
    выключил вечером — до 5:00 тихо, дальше снова решает расписание. То же
    правило читают «Энергия» и «Настройки».
    """
    import datetime
    now = now or datetime.datetime.now()
    today = now.replace(second=0, microsecond=0)
    marks = [today.replace(hour=5, minute=0), today.replace(hour=22, minute=0),
             (today - datetime.timedelta(days=1)).replace(hour=22, minute=0)]
    boundary = max(m for m in marks if m <= now)
    on, ts, _ = read_state()
    if ts >= boundary.timestamp():
        return on
    return now.hour >= 22 or now.hour < 5


def schedule():
    """Привести ночной свет к расписанию. Зовётся таймером systemd.

    В Hyprland этим занимался сам hyprsunset по профилям в своём конфиге; в
    Niri его нет вовсе, и расписание осталось бы неисполненным (21.09.2026).
    """
    want = scheduled_on()
    on, _, warmth = read_state()
    if want == on:
        return "по расписанию уже %s" % ("вкл" if on else "выкл")
    return "по расписанию %s: %s" % ("вкл" if want else "выкл", apply(want, warmth))


def main():
    args = sys.argv[1:] or ["get"]
    if args[0] == "schedule":
        print(schedule())
        return 0
    if args[0] == "get":
        on, _, warmth = read_state()
        print("%s %d" % ("on" if on else "off", warmth))
        return 0
    if args[0] == "on":
        warmth = int(args[1]) if len(args) > 1 else None
        print(apply(True, warmth))
        return 0
    if args[0] == "off":
        print(apply(False))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
