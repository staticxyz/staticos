#!/usr/bin/env python3
"""Вид бара — переключатель заготовок.

Вид — пара файлов в ~/.config/waybar/looks/: <имя>.jsonc (отступы бара,
margin-*; подключается в config.jsonc через "include") и <имя>.css (как
выглядит сама подложка, window#waybar; подключается в style.css через
@import). Текущий вид — ссылки current.jsonc и current.css на нужную пару.
Скрипт переставляет их и перезапускает waybar: отступы — настройка самого
бара, а не стиля, и на лету waybar их не перечитывает. Перезапуск именно
kill + запуск: SIGUSR2 на этой машине бар не перезагружает, а убивает.

    bar_style.py get           имя текущего вида
    bar_style.py list          все виды
    bar_style.py set <имя>     переключить
"""
import os
import subprocess
import sys
import time

LOOKS = os.path.expanduser("~/.config/waybar/looks")


def available():
    return sorted(n[:-6] for n in os.listdir(LOOKS)
                  if n.endswith(".jsonc") and n != "current.jsonc"
                  and os.path.exists(os.path.join(LOOKS, n[:-6] + ".css")))


def current():
    try:
        return os.path.basename(os.readlink(os.path.join(LOOKS, "current.jsonc")))[:-6]
    except OSError:
        return ""


def relink(link, target):
    """Переставить ссылку атомарно: бар не увидит её отсутствующей."""
    tmp = link + ".new"
    if os.path.lexists(tmp):
        os.unlink(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, link)


def on_niri():
    return bool(os.environ.get("NIRI_SOCKET")) and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")


def bar_argv():
    """Чем запускать бар. В niri — своим конфигом: в основном столы и раскладка
    сделаны модулями Hyprland, и под niri они пусты (21.09.2026: после смены вида
    из бара пропадали цифры столов — бар поднимался с основным конфигом).
    Файл каждый раз пересобирается из основного, чтобы правки не терялись."""
    if not on_niri():
        return ["waybar"]
    gen = os.path.expanduser("~/.config/niri/scripts/waybar_niri.py")
    cfg = os.path.expanduser("~/.config/waybar/config-niri.jsonc")
    if os.path.exists(gen):
        subprocess.run(["python3", gen], capture_output=True)
    css = os.path.expanduser("~/.config/waybar/style-niri.css")
    if os.path.exists(cfg) and os.path.exists(css):
        return ["waybar", "-c", cfg, "-s", css]
    return ["waybar", "-c", cfg] if os.path.exists(cfg) else ["waybar"]


def kill_our_waybar():
    """Убить бар ТОЛЬКО своего сеанса. pkill -x waybar валит и бар соседнего
    композитора, если тот запущен на другом терминале (Hyprland и niri рядом)."""
    me = os.environ.get("WAYLAND_DISPLAY")
    killed = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            argv = [a for a in open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0") if a]
            if not argv or os.path.basename(argv[0].decode()) != "waybar":
                continue
            env = open("/proc/%s/environ" % pid, "rb").read().decode("utf-8", "replace")
            wd = dict(l.split("=", 1) for l in env.split("\0") if "=" in l).get("WAYLAND_DISPLAY")
        except (OSError, ValueError, UnicodeDecodeError):
            continue
        if me is None or wd == me:
            try:
                os.kill(int(pid), 15)
                killed.append(int(pid))
            except OSError:
                pass
    for _ in range(30):
        if not any(os.path.exists("/proc/%d" % p) for p in killed):
            break
        time.sleep(0.1)


def restart_waybar():
    kill_our_waybar()
    # Журнал — в ~/.cache/waybar.log: по нему видно, если вид не влез в
    # свою высоту ("minimum height") или конфиг не разобрался.
    log = open(os.path.expanduser("~/.cache/waybar.log"), "w")
    argv = bar_argv()
    if on_niri():
        # панели по мониторам (panels.py, 06.10.2026) — свой waybar на каждый монитор
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import panels
            if panels.per_monitor():
                log.close()
                panels.launch_top(os.path.expanduser("~/.cache/waybar.log"))
                return
        except Exception as e:
            print("bar_style: панели по мониторам: %s" % e, file=sys.stderr)
    subprocess.Popen(argv, stdin=subprocess.DEVNULL,
                     stdout=log, stderr=subprocess.STDOUT,
                     start_new_session=True)


def main():
    args = sys.argv[1:]
    if args == ["get"]:
        print(current())
    elif args == ["list"]:
        print("\n".join(available()))
    elif len(args) == 2 and args[0] == "set":
        name = args[1]
        if name not in available():
            print("нет такого вида: %s (есть: %s)" % (name, ", ".join(available())),
                  file=sys.stderr)
            return 1
        if name == current():
            return 0
        relink(os.path.join(LOOKS, "current.jsonc"), name + ".jsonc")
        relink(os.path.join(LOOKS, "current.css"), name + ".css")
        # Плотность фона из Настроек красит у разных видов разное (у «островов» — сами
        # острова, у «прозрачного» — ничего): пересчитать под новый вид (04.10.2026).
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import top_bar
            top_bar.opacity_rule()
        except Exception as e:
            print("bar_style: плотность фона не пересчитана: %s" % e, file=sys.stderr)
        restart_waybar()
        print("вид бара: " + name)
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
