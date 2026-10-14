"""Одно меню за раз (14.10.2026).

Просьба: «если я открываю например Super+Z и, не закрывая её, открываю следом Super+X,
то прошлая должна закрыться сама — чтобы не стакать окна друг в друга».

Каждое меню из MENUS при открытии зовёт close_others(__file__): прочие меню из списка
получают SIGTERM — тот же способ, каким popup_theme.single_instance закрывает попап
повторным нажатием. Процесс узнаётся по /proc: питон, запустивший именно этот файл
(не pgrep -f — тот ловит и терминал с именем файла в команде). Проверки без окна
(--shot, --check, check) не трогаются.

    from menu_one import close_others
    close_others(__file__)
"""
import os

HERE = os.path.dirname(os.path.abspath(__file__))
MENUS = ("app_launcher.py",      # Super+X
         "keybinds_sheet.py",    # Super+Z
         "config_map.py",        # Super+Shift+Z
         "translate_popup.py",   # Super+C
         "wallpaper_picker.py")  # Super+W
QUIET = ("--shot", "--check", "check", "shot")


def close_others(path):
    """SIGTERM всем открытым меню из MENUS, кроме этого файла. → сколько закрыто."""
    mine = os.path.abspath(path)
    targets = {os.path.join(HERE, m) for m in MENUS} - {mine}
    me, n = os.getpid(), 0
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == me:
            continue
        try:
            with open("/proc/%s/cmdline" % p, "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if (len(argv) >= 2 and "python" in os.path.basename(argv[0])
                and os.path.abspath(argv[1]) in targets
                and not any(a in QUIET for a in argv[2:])):
            try:
                os.kill(int(p), 15)
                n += 1
            except OSError:
                pass
    return n


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["check"]:
        print("menu_one: %d меню в списке, все на месте: %s" % (
            len(MENUS), all(os.path.exists(os.path.join(HERE, m)) for m in MENUS)))
