#!/usr/bin/env python3
"""Меню программ (SUPER+SPACE): rofi в стиле системы, с синонимами и другой раскладкой.

    launcher.py               показать меню (стиль — launcher_style.py, значки — тема системы)
    launcher.py --rebuild     пересобрать кэш списка программ

05.10.2026, Просьба: «чтобы он тоже понимал синонимы и русскую раскладку, как в Пуске».
Встроенный `rofi -show drun` подмешать свои слова к программам не даёт, поэтому список
отдаём rofi сами (-dmenu): у каждой строки значок и невидимые слова (row option «meta»):
её слова в другой раскладке и синонимы её групп — словарь общий с «Пуском» (app_search.py).
«еудупкфь» → Telegram, «браузер» → Zen/LibreWolf, «тг» → Telegram.

Порядок — как у drun: чаще запускаемые выше (~/.cache/jarvis/launcher-history.json),
дальше по алфавиту. Список программ кэшируется (~/.cache/jarvis/launcher-apps.json) и
пересобирается, когда меняется любая папка с .desktop — без Gio меню открывается быстрее.
Запуск — как в «Пуске» (start_menu.launch_app): терминальные — в общей копии kitty,
D-Bus-активируемые — штатно, прочие — Exec через `niri msg action spawn`.

Клавиши: Ctrl+J/K — строки (config.rasi), Ctrl+D/U — страница, как в nvim.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import app_search  # noqa: E402

CACHE_DIR = os.path.expanduser("~/.cache/jarvis")
APPS = os.path.join(CACHE_DIR, "launcher-apps.json")
HISTORY = os.path.join(CACHE_DIR, "launcher-history.json")
DIRS = [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications",
        "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
TERMINAL = (os.path.expanduser("~/.config/hypr/scripts/kitty_shared.sh"),)
KEYS = ["-kb-remove-char-forward", "Delete", "-kb-remove-to-sol", "",
        "-kb-page-next", "Page_Down,Control+d,Control+Cyrillic_ve",
        "-kb-page-prev", "Page_Up,Control+u,Control+Cyrillic_ghe"]


def dirs_stamp():
    st = []
    for d in DIRS:
        try:
            st.append(os.stat(d).st_mtime)
        except OSError:
            st.append(0)
    return st


def build():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    apps = []
    for a in Gio.AppInfo.get_all():
        if not a.should_show() or not isinstance(a, Gio.DesktopAppInfo):
            continue
        icon = a.get_icon()
        hay = " ".join(x or "" for x in (
            a.get_display_name(), a.get_name(), a.get_generic_name(),
            ";".join(a.get_keywords() or []), a.get_executable(), a.get_id()))
        apps.append({"id": a.get_id(), "name": a.get_display_name() or a.get_name() or a.get_id(),
                     "icon": icon.to_string() if icon else "",
                     "meta": " ".join(filter(None, (a.get_generic_name() or "",
                                                    " ".join(a.get_keywords() or []),
                                                    app_search.search_meta(hay))))})
    data = {"stamp": dirs_stamp(), "apps": apps}
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(APPS + ".tmp", "w") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(APPS + ".tmp", APPS)
    return apps


def load_apps():
    try:
        d = json.load(open(APPS))
        if d.get("stamp") == dirs_stamp() and os.path.getmtime(APPS) >= os.path.getmtime(
                os.path.join(HERE, "app_search.py")):
            return d["apps"]
    except (OSError, ValueError, KeyError):
        pass
    return build()


def history():
    try:
        h = json.load(open(HISTORY))
        return h if isinstance(h, dict) else {}
    except (OSError, ValueError):
        pass
    # первый запуск — счётчики из истории rofi drun (~/.cache/rofi3.druncache: «число id»),
    # чтобы привычный порядок не сбросился
    h = {}
    try:
        for line in open(os.path.expanduser("~/.cache/rofi3.druncache")):
            n, _, did = line.strip().partition(" ")
            if n.isdigit() and did:
                h[did] = int(n)
    except OSError:
        pass
    return h


def remember(app_id):
    h = history()
    h[app_id] = h.get(app_id, 0) + 1
    try:
        with open(HISTORY + ".tmp", "w") as f:
            json.dump(h, f)
        os.replace(HISTORY + ".tmp", HISTORY)
    except OSError:
        pass


def theme_args():
    """Тема стиля системы (как в shell-do: свежая — без пересборки) и тема значков."""
    st = ""
    try:
        st = open(os.path.expanduser("~/.config/hypr/state/clipboard-style")).read().strip()
    except OSError:
        pass
    st = st if st in ("default", "skeet", "beta") else "default"
    th = os.path.join(CACHE_DIR, "launcher-%s.rasi" % st)
    srcs = [os.path.expanduser(p) for p in ("~/.cache/matugen/colors.json", "~/.cache/matugen/vivid.txt",
                                           "~/.config/hypr/state/settings-mode")] + [
        os.path.join(HERE, "launcher_style.py")]
    try:
        fresh = os.path.exists(th) and all(not os.path.exists(s) or os.path.getmtime(s) <= os.path.getmtime(th)
                                           for s in srcs)
    except OSError:
        fresh = False
    if not fresh:
        import launcher_style
        th = launcher_style.build(st)
    it = ""
    try:
        it = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "icon-theme"],
                            capture_output=True, text=True, timeout=1).stdout.strip().strip("'")
    except (OSError, subprocess.SubprocessError):
        pass
    return ["-theme", th, "-icon-theme", it or "Papirus-Wall"]


def spawn_clean(*args):
    """Как start_menu.spawn_clean: программа — ребёнок niri, чистое окружение сеанса."""
    if os.environ.get("NIRI_SOCKET"):
        try:
            if subprocess.run(["niri", "msg", "action", "spawn", "--", *args],
                              capture_output=True, timeout=2).returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def launch(app_id):
    """Как start_menu.launch_app (02.10.2026: Gio.launch не находит kitty для Terminal=true)."""
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio, GLib
    try:
        a = Gio.DesktopAppInfo.new(app_id)
    except TypeError:
        a = None
    if a is None:
        return
    name = a.get_name() or ""
    cmd = a.get_commandline() or a.get_executable() or ""
    cmd = " ".join(re.sub(r"%[a-zA-Z]", "", cmd.replace("%%", "\0")).replace("\0", "%").split())
    path = a.get_string("Path") or ""
    term, dbus = a.get_boolean("Terminal"), a.get_boolean("DBusActivatable")
    if dbus and not term:
        try:
            if a.launch([], None):
                return
        except GLib.Error:
            pass
    if not cmd:
        return
    sh = ("cd %s && " % GLib.shell_quote(path) if path else "") + "exec " + cmd
    if term:
        spawn_clean(*TERMINAL, "--title", name or cmd, "sh", "-c", sh)
    else:
        spawn_clean("sh", "-c", sh)


def main():
    if sys.argv[1:2] == ["--rebuild"]:
        print(len(build()))
        return 0
    apps = load_apps()
    h = history()
    apps.sort(key=lambda a: (-h.get(a["id"], 0), a["name"].lower()))
    rows = []
    for a in apps:
        name = a["name"].replace("\n", " ").replace("\0", "")
        opts = []
        if a.get("icon"):
            opts.append("icon\x1f" + a["icon"])
        if a.get("meta"):
            opts.append("meta\x1f" + a["meta"].replace("\x1f", " "))
        rows.append(name + ("\0" + "\x1f".join(opts) if opts else ""))
    r = subprocess.run(["rofi", "-dmenu", "-i", "-p", "\U000f0349", "-show-icons", "-no-custom", "-format", "i",
                        # по началу слов: «тг» — слово-синоним Telegram, а не кусок чужого слова
                        "-matching", "prefix",
                        # пока набирают — лучшие совпадения выше (имя раньше синонимов); пусто —
                        # порядок истории запусков
                        "-sort", "-sorting-method", "fzf",
                        *theme_args(), *KEYS],
                       input="\n".join(rows) + "\n", capture_output=True, text=True)
    out = r.stdout.strip()
    if r.returncode != 0 or not out.isdigit() or int(out) >= len(apps):
        return 0
    app = apps[int(out)]
    launch(app["id"])
    remember(app["id"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
