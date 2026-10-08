#!/usr/bin/env python3
"""cozette_fit.py on|off|status — подгонка размеров интерфейса под шрифт Cozette (08.10.2026).

Cozette чёткий только на 13 px, PxPlus стоял на 16 — текст стал в 13/16 меньше, а кнопки,
поля и капсулы остались прежними. Подгонка ужимает их в ту же меру:
  • верхний бар — капсулы 26 → 22 px, поля и кнопки столов (waybar_niri.py, STYLE_COZETTE);
  • попапы — поля, отступы, ползунки ×13/16 (popup_theme.SCALE / px());
  • Alt+Tab — плитки 72 → 60 px, подпись 9 знаков (alt_tab.py, перезапуск резидента);
  • экран блокировки — поля 320×40 → 288×34 (jarvis_lock.py; часы чинятся и без подгонки).
off — всё как было до подгонки (утро 08.10), шрифт при этом остаётся Cozette.
Действует только при Cozette (правило 61-cozette-trial.conf); под PxPlus ничего не меняет.
Переключатель — Настройки → Шрифты → «Подгонка размеров под Cozette».
"""
import os
import subprocess
import sys

FLAG = os.path.expanduser("~/.config/hypr/state/cozette-fit")
HERE = os.path.dirname(os.path.abspath(__file__))


def status():
    return "on" if os.path.exists(FLAG) else "off"


def restart_widgets():
    # Ищем по argv[1], а не pgrep -f: иначе под шаблон попадает и сама команда запуска
    # (08.10.2026 так была убита собственная оболочка вместе с виджетами).
    me = os.getpid()
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or int(pid) == me:
            continue
        try:
            argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) > 1 and os.path.basename(argv[0]).startswith(b"python") \
                and os.path.basename(argv[1]) == b"desktop_widgets.py":
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
    subprocess.Popen(["setsid", "-f", "python3", os.path.join(HERE, "desktop_widgets.py"), "on"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def restart_alttab():
    pidf = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-alttab.pid")
    try:
        os.kill(int(open(pidf).read().strip()), 15)
    except (OSError, ValueError):
        pass
    subprocess.Popen(["niri", "msg", "action", "spawn", "--", "python3",
                      os.path.join(HERE, "alt_tab.py"), "daemon"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def apply():
    subprocess.run(["python3", os.path.expanduser("~/.config/niri/scripts/waybar_niri.py")],
                   capture_output=True, timeout=30)
    subprocess.Popen(["setsid", "-f", os.path.expanduser("~/.local/bin/barfix")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    restart_widgets()
    restart_alttab()


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(status())
        return
    if cmd not in ("on", "off"):
        sys.exit(__doc__)
    if cmd == "on":
        os.makedirs(os.path.dirname(FLAG), exist_ok=True)
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)
    if "--no-apply" not in sys.argv:
        apply()
    print(status())


if __name__ == "__main__":
    main()
