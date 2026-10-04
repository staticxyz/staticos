#!/usr/bin/env python3
"""Цвет и яркость экрана: ночной свет и приглушение по простою — в одном месте.

    screen_gamma.py apply          применить текущее состояние
    screen_gamma.py dim off|soft|deep   приглушение по простою
    screen_gamma.py status         что применено и чем

Зачем один скрипт на две ручки. Гаммой владеет ОДИН клиент: кто подключился
последним, тот и командует. Пока ночной свет и приглушение шли разными
командами, в Hyprland это сходило с рук (hyprsunset — один демон с двумя
ручками), а в Niri два клиента отнимали бы управление друг у друга. Поэтому
желаемое состояние собирается здесь целиком и применяется одним вызовом.

Два пути, выбор по запущенному композитору:
  Hyprland — hyprsunset (свой протокол hyprland-ctm-control-v1);
  Niri и прочие wlroots — gammastep поверх zwlr_gamma_control_manager_v1.
В Niri hyprsunset не работает вовсе: он выходит с «Compositor doesn't support
hyprland-ctm-control-v1» (проверено 21.09.2026), а hyprctl без Hyprland не с
кем разговаривать — из-за этого в сеансе Niri молча не работали ни ночной
режим, ни приглушение перед блокировкой.

Состояние: ~/.cache/night-mode (ночной свет, пишет night_mode.py) и
~/.cache/screen-dim (приглушение). Здесь они только читаются.
"""
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DIM_STATE = os.path.expanduser("~/.cache/screen-dim")
# Две ступени приглушения. «Глубокая» — вместо выключения экрана: гасить его
# через DPMS нельзя, после этого экран однажды не проснулся и машину пришлось
# перезагружать вслепую (история в hypridle.conf). Чёрная картинка при живом
# выходе просыпается от любого движения мыши.
# 0.10 — нижний предел gammastep: с меньшим он отказывается работать
# («Brightness values must be between 0.1 and 1.0») и молча выходит,
# оставляя экран ярким (поймано замером 21.09.2026).
DIM_LEVELS = {"soft": 0.55, "deep": 0.10}
NEUTRAL_K = 6500
# Ищем демон по ИМЕНИ процесса (pgrep -x), а не по строке запуска: поиск по
# строке ловил заодно и чужие процессы, в чьей команде эта строка упоминается,
# и они получали SIGTERM (поймано на себе 21.09.2026).


def compositor():
    """"hyprland", "wlr" (Niri и прочие) или None, если ничего не нашли."""
    if subprocess.run(["pidof", "Hyprland"], capture_output=True).returncode == 0:
        return "hyprland"
    if subprocess.run(["pidof", "niri"], capture_output=True).returncode == 0:
        return "wlr"
    return None


def night_target():
    """(включён ли ночной свет, температура в K) по ~/.cache/night-mode."""
    import night_mode
    on, _, warmth = night_mode.read_state()
    return on, night_mode.temperature(warmth)


def dim_level():
    """"off", "soft" или "deep". «on» из старого состояния — это soft."""
    try:
        with open(DIM_STATE) as f:
            value = f.read().split()[0]
    except (OSError, IndexError):
        return "off"
    if value == "on":
        return "soft"
    return value if value in DIM_LEVELS else "off"


def set_dim(level):
    """level: off | soft | deep (или True/False по-старому)."""
    if level is True:
        level = "soft"
    elif level is False:
        level = "off"
    if level not in ("off", "soft", "deep"):
        level = "off"
    try:
        with open(DIM_STATE, "w") as f:
            f.write(level + "\n")
    except OSError:
        pass


def apply_hyprland(temp, brightness):
    """hyprsunset: температура и гамма — две отдельные ручки одного демона."""
    import night_mode
    if not night_mode.ensure():
        return "hyprsunset не запускается"
    out = []
    if temp == NEUTRAL_K:
        r = subprocess.run(["hyprctl", "hyprsunset", "identity"], capture_output=True, text=True)
    else:
        r = subprocess.run(["hyprctl", "hyprsunset", "temperature", str(temp)],
                           capture_output=True, text=True)
    out.append((r.stdout + r.stderr).strip())
    r = subprocess.run(["hyprctl", "hyprsunset", "gamma", str(int(brightness * 100))],
                       capture_output=True, text=True)
    out.append((r.stdout + r.stderr).strip())
    return " ".join(x for x in out if x)


def gammastep_pids():
    r = subprocess.run(["pgrep", "-x", "gammastep"], capture_output=True, text=True)
    return [int(p) for p in r.stdout.split()]


def apply_wlr(temp, brightness):
    """gammastep как постоянный клиент гаммы: свои значения — свой процесс.

    Задать другие значения на лету gammastep не умеет, поэтому старый процесс
    гасим и поднимаем новый. Порядок именно такой: при выходе клиента
    композитор возвращает гамму по умолчанию, и запусти мы новый раньше —
    смерть старого стёрла бы его настройку.
    """
    old = gammastep_pids()
    for pid in old:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    # дождаться смерти старого — иначе он умрёт ПОСЛЕ старта нового и сбросит гамму
    for _ in range(20):
        if not any(os.path.exists("/proc/%d" % p) for p in old):
            break
        time.sleep(0.05)
    if temp == NEUTRAL_K and brightness >= 1.0:
        return "обычный цвет (клиент гаммы не нужен)"
    cmd = ["gammastep", "-m", "wayland", "-P", "-r", "-l", "0:0",
           "-t", "%d:%d" % (temp, temp),
           "-b", "%.2f:%.2f" % (brightness, brightness)]
    # Запуск через niri, а не своим дочерним процессом (05.10.2026, просьба: «ночной
    # свет по расписанию включается, но эффекта нет»). Расписание зовёт нас из
    # одноразовой службы systemd (night-schedule.service): когда она завершается,
    # systemd убивает всю её группу процессов — и gammastep вместе с ней, гамма
    # сбрасывается, а состояние остаётся «вкл». start_new_session от этого не спасает.
    if os.environ.get("NIRI_SOCKET"):
        try:
            r = subprocess.run(["niri", "msg", "action", "spawn", "--", *cmd],
                               capture_output=True, timeout=3)
            if r.returncode == 0:
                return "gammastep %d K, яркость %.2f" % (temp, brightness)
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except OSError as e:
        return "gammastep не запускается: %s" % e
    return "gammastep %d K, яркость %.2f" % (temp, brightness)


def apply_state():
    """Собрать желаемое из двух состояний и применить одним вызовом."""
    night, temp = night_target()
    if not night:
        temp = NEUTRAL_K
    brightness = DIM_LEVELS.get(dim_level(), 1.0)
    who = compositor()
    if who == "hyprland":
        return apply_hyprland(temp, brightness)
    if who == "wlr":
        return apply_wlr(temp, brightness)
    return "композитор не опознан — гамма не тронута"


def main():
    args = sys.argv[1:] or ["apply"]
    if args[0] == "apply":
        print(apply_state())
        return 0
    if args[0] == "dim" and len(args) == 2 and args[1] in ("on", "off", "soft", "deep"):
        set_dim("soft" if args[1] == "on" else args[1])
        print(apply_state())
        return 0
    if args[0] == "status":
        night, temp = night_target()
        print("композитор: %s" % (compositor() or "не опознан"))
        print("ночной свет: %s (%d K)" % ("вкл" if night else "выкл", temp))
        print("приглушение: %s" % dim_level())
        print("gammastep: %s" % (gammastep_pids() or "не запущен"))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
