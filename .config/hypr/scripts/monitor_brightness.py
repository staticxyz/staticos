#!/usr/bin/env python3
"""Яркость внешнего монитора MSI по DDC/CI (19.09.2026).

    monitor_brightness.py present     есть ли MSI сейчас (код выхода 0/1)
    monitor_brightness.py get         яркость 0..100 (спрашивает монитор, ~0,3 с)
    monitor_brightness.py last        последняя известная яркость, мгновенно
    monitor_brightness.py set N       поставить яркость

Экран ноутбука DDC не умеет — его яркость у brightnessctl. MSI MAG 255XF
отвечает по шине i2c без root: у шин монитора права выдаёт вход в систему
(ACL «+» на /dev/i2c-*). Номер шины кэшируется в ~/.cache/msi-ddc-bus: поиск
(ddcutil detect) идёт ~1 с, запрос по известной шине — ~0,3 с. Если шина
сменилась (переподключили кабель), кэш проверяется запросом и ищется заново.
Панель «Энергия» зовёт set не чаще одного раза за раз: одновременные запросы
по одной шине DDC мешают друг другу.
"""
import os
import re
import subprocess
import sys

MODEL = "MAG 255XF"
CACHE = os.path.expanduser("~/.cache/msi-ddc-bus")
# Последняя прочитанная яркость. Нужна панели «Энергия»: спрашивать монитор по
# DDC — это 0,3 с, и строка яркости выезжала уже после открытия панели, будто
# появляясь заново (21.09.2026). Теперь панель рисует строку сразу из
# этого файла, а ответ монитора лишь уточняет значение.
LAST = os.path.expanduser("~/.cache/msi-brightness")
DDC = ["ddcutil", "--sleep-multiplier", ".5"]


def hypr_has_monitor():
    """Подключён ли MSI — по списку мониторов композитора. Быстрая проверка перед
    медленным ddcutil. Работает и в Hyprland, и в niri (21.09.2026: под niri
    спрашивался hyprctl, его нет, ползунок яркости MSI пропадал из «Энергии»)."""
    cmd = (["niri", "msg", "outputs"] if os.environ.get("NIRI_SOCKET")
           and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
           else ["hyprctl", "monitors", "-j"])
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return True   # не узнали — пусть решит ddcutil
    return MODEL in out


def detect_bus():
    out = subprocess.run(["ddcutil", "detect", "--terse"], capture_output=True, text=True, timeout=20).stdout
    bus = None
    for line in out.splitlines():
        m = re.search(r"/dev/i2c-(\d+)", line)
        if m:
            bus = m.group(1)
        if "Monitor:" in line and MODEL in line and bus:
            with open(CACHE, "w") as f:
                f.write(bus)
            return bus
    return None


def read_value(bus):
    r = subprocess.run(DDC + ["--bus", bus, "getvcp", "10", "--brief"],
                       capture_output=True, text=True, timeout=10)
    m = re.search(r"VCP 10 C (\d+) (\d+)", r.stdout)
    if not m:
        return None
    cur, mx = int(m.group(1)), int(m.group(2)) or 100
    value = round(cur * 100 / mx)
    try:
        with open(LAST, "w") as f:
            f.write("%d\n" % value)
    except OSError:
        pass
    return value


def bus_and_value():
    try:
        with open(CACHE) as f:
            bus = f.read().strip()
    except OSError:
        bus = None
    if bus:
        v = read_value(bus)
        if v is not None:
            return bus, v
    bus = detect_bus()
    return (bus, read_value(bus)) if bus else (None, None)


def main():
    args = sys.argv[1:]
    try:
        if args == ["present"]:
            return 0 if hypr_has_monitor() else 1
        if args == ["last"]:
            try:
                with open(LAST) as f:
                    print(int(f.read().strip()))
                return 0
            except (OSError, ValueError):
                return 1
        if args == ["get"]:
            if not hypr_has_monitor():
                return 1
            _, v = bus_and_value()
            if v is None:
                return 1
            print(v)
            return 0
        if len(args) == 2 and args[0] == "set" and args[1].isdigit():
            n = max(0, min(100, int(args[1])))
            bus, _ = bus_and_value()
            if not bus:
                return 1
            r = subprocess.run(DDC + ["--bus", bus, "setvcp", "10", str(n), "--noverify"],
                               capture_output=True, timeout=10)
            if r.returncode == 0:
                try:
                    with open(LAST, "w") as f:
                        f.write("%d\n" % n)
                except OSError:
                    pass
            return r.returncode
    except (OSError, subprocess.SubprocessError):
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
