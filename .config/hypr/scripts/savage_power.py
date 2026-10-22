#!/usr/bin/env python3
"""Savage Mode — мощность ПК на максимум (22.10.2026).

    savage_power.py on | off | toggle | get

Частоту монитора не трогает (POWER_KEEP_HZ): смена режима гасила MSI на секунду.

Вкл  — `power max` + профиль performance (то, что делала плитка «Мощность» в Центре
       управления); выкл — `power mid` (профиль balanced).
Просьба: «новый переключатель Savage Mode должен переключать мощности ПК на макс… и
действие плитки, и power max. При отключении power mid». Прежний Savage Mode (не гасить
экран, savage_battery.py) теперь называется «Кофеин».

Зовут: плашка «Энергия» (battery_popup.py), плитка «Мощность» (control_center.py),
значок «Энергии» в нижней панели (xpbar.py — голубой, пока включено).

Root-часть `power` идёт только через `sudo -n /usr/local/bin/power-helper` — из окна нет
терминала, а sudo без TTY упирается в faillock. Без помощника применяется только
профиль, а ручки процессора — нет; об этом приходит уведомление.
Установка помощника: bash ~/.local/share/power-helper/install.sh
"""
import os
import subprocess
import sys

STATE = os.path.expanduser("~/.cache/power-mode")
POWER = os.path.expanduser("~/.local/bin/power")
HELPER = "/usr/local/bin/power-helper"


def is_on():
    try:
        with open(STATE) as f:
            return f.read().strip() == "max"
    except OSError:
        return False


def helper_ok():
    try:
        return subprocess.run(["sudo", "-n", "-l", HELPER], stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=3).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def apply(on, profile=None, wait=False):
    """on — max/mid. profile — профиль power-profiles-daemon после (по умолчанию
    performance для max, balanced для mid; «Энергосбережение» передаёт power-saver).

    `power max` ставит balanced + EPP performance; performance поверх пишет тот же EPP
    (у ppd здесь только intel_pstate, PlatformDriver placeholder) — по железу одно и то
    же, зато плитка в Центре управления показывает «Мощность»."""
    profile = profile or ("performance" if on else "balanced")
    if not helper_ok():
        subprocess.Popen(["notify-send", "-a", "Энергия", "Savage Mode",
                          "Нет power-helper: процессор не разогнан, только профиль. "
                          "Установка: bash ~/.local/share/power-helper/install.sh"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    cmd = '"$0" %s >/dev/null 2>&1; powerprofilesctl set %s >/dev/null 2>&1' % (
        "max" if on else "mid", profile)
    # POWER_KEEP_HZ — не трогать частоту MSI: смена режима гасит монитор на секунду, а
    # обычная частота и так 300 Гц (22.10.2026, просьба: «можно без этого?»)
    env = dict(os.environ, POWER_KEEP_HZ="1")
    p = subprocess.Popen(["sh", "-c", cmd, POWER], stdin=subprocess.DEVNULL, env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    if wait:
        p.wait()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "get"
    if arg == "get":
        print("on" if is_on() else "off")
    elif arg in ("on", "off", "toggle"):
        apply(not is_on() if arg == "toggle" else arg == "on", wait=True)
        print("on" if is_on() else "off")
    else:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
