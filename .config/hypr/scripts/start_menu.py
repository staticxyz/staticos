#!/usr/bin/env python3
"""Меню «Пуск» в духе Windows XP — над кнопкой «Пуск» нижней XP-панели. 01.10.2026.

    start_menu.py [МОНИТОР]      открыть (второй запуск — закрыть); МОНИТОР — имя
                                 выхода niri (DP-4, eDP-1), его передаёт xpbar.py

Просьба: «при нажатии на Пуск — настоящую плашку как в Windows XP, оформи сам».
Устройство как у меню XP (Luna), в цветах обоев:
  * шапка — градиент акцента, аватарка (~/.cache/avatar.png) и надпись staticxyzz
    (пиксельный логотип, перекрашенный в гамму, как на кнопке «Пуск»);
    под шапкой — полоска вторым цветом палитры, как оранжевая линия XP;
  * левая колонка — закреплённые программы крупно (значок 32, имя и что это),
    ниже — часто используемые (по экранному времени за 7 дней), в самом низу —
    «Все программы ▸» (меню программ rofi); ПКМ по программе — закрепить/открепить;
  * правая колонка, тоном темнее, — папки и системное: Документы, Изображения,
    Музыка, Загрузки, Настройки, Центр управления, Карта конфигов, Экранное время, Выполнить;
  * поле поиска внизу левой колонки: печатать можно сразу — список программ
    заменяется найденными, Enter запускает первую;
  * подвал — Блокировка, Выход, Выключение (wlogout — меню питания как было).
Закрывается: Esc, щелчок мимо, повторный щелчок по «Пуску», запуск пункта.
"""
import json
import re
import time
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import popup_theme  # noqa: E402

# single_instance — только при запуске отдельным процессом (main): с 01.10.2026
# меню живёт внутри xpbar.py (готовое, показывается мгновенно), а этот файл
# там просто импортируется.

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402
import cairo  # noqa: E402

PIN_FILE = os.path.expanduser("~/.config/hypr/state/start-pinned.json")
AVATAR = os.path.expanduser("~/.cache/avatar.png")
SCREENTIME = os.path.expanduser("~/.local/share/jarvis/screentime")
BAR_H = 32
# Флаг «меню открыто» (в нём — монитор): xpbar.py следит за ним и держит кнопку
# «Пуск» нажатой, пока меню на экране, — как в XP (01.10.2026).
OPEN_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "start-menu-open")


def bye(*_a):
    try:
        os.remove(OPEN_FLAG)
    except OSError:
        pass
    os._exit(0)


def watch_workspaces():
    """Сменился стол (или фокус ушёл к другому окну) — меню закрыть, как Esc.
    Первые события потока niri — пересказ текущего состояния, их пропускаем."""
    import threading
    import time

    def run():
        try:
            p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True,
                                 preexec_fn=_die_with_parent)
        except OSError:
            return
        t0 = time.monotonic()
        for line in p.stdout:
            if time.monotonic() - t0 < 0.6:
                continue
            if line.startswith('{"WorkspaceActivated"') or line.startswith('{"WindowFocusChanged"'):
                p.kill()
                GLib.idle_add(bye)
                return
    threading.Thread(target=run, daemon=True).start()
FONT = "'JetBrainsMono Nerd Font', 'JetBrainsMono NF', monospace"
NERD = "'Symbols Nerd Font', 'JetBrainsMono NF'"
DEFAULT_PINS = ["zen.desktop", "zen-browser.desktop", "librewolf.desktop", "kitty.desktop",
                "org.telegram.desktop.desktop", "org.kde.dolphin.desktop", "obsidian.desktop"]
# Что это за программа — вторая строка у закреплённых, как «Internet / Internet Explorer».
ROLES = {"zen": "Интернет", "librewolf": "Интернет", "helium": "Интернет", "firefox": "Интернет",
         "kitty": "Терминал", "telegram": "Сообщения", "dolphin": "Файлы", "obsidian": "Заметки",
         "yandex": "Музыка", "music": "Музыка", "steam": "Игры", "mousepad": "Блокнот",
         "keepassxc": "Пароли"}



def _die_with_parent():
    """preexec_fn для фоновых подписок (pactl subscribe, swaync-client -swb,
    niri event-stream): ядро убьёт их вместе с этим процессом (PR_SET_PDEATHSIG).
    01.10.2026: без этого каждый перезапуск панели оставлял сирот — к ночи их
    набралось больше сотни, pipewire-pulse упёрся в предел клиентов («too many
    client application connections») и новые программы остались без звука."""
    import ctypes
    import signal as _signal
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, _signal.SIGTERM)


def run_bg(*args):
    subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


LAUNCH_LOG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "start-menu.log")
TERMINAL = (os.path.expanduser("~/.config/hypr/scripts/kitty_shared.sh"),)


def launch_log(text):
    try:
        with open(LAUNCH_LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%F %T"), text))
    except OSError:
        pass


def spawn_clean(*args):
    """Запустить программу руками niri — как бинд, а не как ребёнка панели.

    Меню живёт в процессе xpbar, и его дети наследовали окружение панели (а та
    бывает запущена из терминала: KITTY_*, DESKTOP_STARTUP_ID, чужой cwd).
    `niri msg action spawn` даёт программе чистое окружение сеанса (02.10.2026).
    """
    if os.environ.get("NIRI_SOCKET"):
        try:
            r = subprocess.run(["niri", "msg", "action", "spawn", "--", *args],
                               capture_output=True, text=True, timeout=2)
            if r.returncode == 0:
                return
            launch_log("niri spawn отказал: %s" % r.stderr.strip())
        except (OSError, subprocess.SubprocessError) as e:
            launch_log("niri spawn: %s" % e)
    run_bg(*args)


def app_command(a):
    """Exec из .desktop без полей %U/%f…: открываем без файла."""
    cmd = a.get_commandline() or a.get_executable() or ""
    cmd = re.sub(r"%[a-zA-Z]", "", cmd.replace("%%", "\0")).replace("\0", "%")
    return " ".join(cmd.split())


def launch_app(a):
    """Запуск ярлыка. Gio.launch здесь подводил (02.10.2026, «btop не открывается
    через Пуск»): программам с Terminal=true GLib ищет терминал по своему списку
    (xterm, gnome-terminal…), kitty в нём нет — «Unable to find terminal». Поэтому:
    терминальные — в окне общей копии kitty, обычные — командой Exec через niri,
    D-Bus-активируемые (Telegram, Nautilus…) — штатно, с откатом на Exec."""
    name, cmd = a.get_name() or "", app_command(a)
    try:
        path = a.get_string("Path") or ""
        term = a.get_boolean("Terminal")
        dbus = a.get_boolean("DBusActivatable")
    except Exception:
        path, term, dbus = "", False, False
    if dbus and not term:
        try:
            if a.launch([], None):
                launch_log("dbus: %s" % a.get_id())
                return
        except GLib.Error as e:
            launch_log("dbus не вышло (%s): %s" % (a.get_id(), e.message))
    if not cmd:
        launch_log("пустой Exec: %s" % a.get_id())
        return
    sh = ("cd %s && " % GLib.shell_quote(path) if path else "") + "exec " + cmd
    if term:
        launch_log("терминал: %s → %s" % (a.get_id(), cmd))
        spawn_clean(*TERMINAL, "--title", name or cmd, "sh", "-c", sh)
    else:
        launch_log("запуск: %s → %s" % (a.get_id(), cmd))
        spawn_clean("sh", "-c", sh)


def niri_json(*args):
    try:
        return json.loads(subprocess.run(["niri", "msg", "-j", *args], capture_output=True,
                                         text=True, timeout=2).stdout)
    except Exception:
        return None


# ── поиск: другая раскладка и синонимы (02.10.2026) ─────────────────────────
# Словарь и функции — в app_search.py (общий с меню программ rofi, 05.10.2026).
from app_search import APP_SYNONYMS, _LAYOUT, search_forms, search_score  # noqa: E402,F401


# ── программы ──────────────────────────────────────────────────────────────

def app_by_id(did):
    try:
        return Gio.DesktopAppInfo.new(did)
    except TypeError:
        return None


_WM = None


def app_for_window(app_id):
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        a = app_by_id(cand + ".desktop")
        if a:
            return a
    global _WM
    if _WM is None:          # один проход по всем .desktop на процесс, а не на каждое окно
        _WM = {}
        for a in Gio.AppInfo.get_all():
            wm = (a.get_startup_wm_class() or "").lower() if isinstance(a, Gio.DesktopAppInfo) else ""
            if wm:
                _WM.setdefault(wm, a)
    return _WM.get(app_id.lower())


def pinned():
    try:
        ids = [x for x in json.load(open(PIN_FILE)) if isinstance(x, str)]
    except (OSError, ValueError):
        ids, seen = [], set()
        for d in DEFAULT_PINS:          # по умолчанию — что установлено, браузер один
            a = app_by_id(d)
            if not a:
                continue
            role = role_of(a)
            if role == "Интернет" and "Интернет" in seen:
                continue
            seen.add(role)
            ids.append(d)
    return [a for a in (app_by_id(d) for d in ids) if a]


def set_pinned(ids):
    os.makedirs(os.path.dirname(PIN_FILE), exist_ok=True)
    with open(PIN_FILE, "w") as f:
        json.dump(ids, f)


def role_of(a):
    low = (a.get_id() or "").lower() + " " + (a.get_display_name() or "").lower()
    for k, v in ROLES.items():
        if k in low:
            return v
    return a.get_generic_name() or ""


def frequent(skip, n=5):
    """Самые используемые программы за 7 дней — из экранного времени."""
    import datetime
    tot = {}
    today = datetime.date.today()
    for i in range(7):
        day = (today - datetime.timedelta(days=i)).strftime("%Y-%m-%d")
        try:
            apps = json.load(open(os.path.join(SCREENTIME, day + ".json"))).get("apps", {})
        except (OSError, ValueError):
            continue
        for k, v in apps.items():
            tot[k] = tot.get(k, 0) + v
    out = []
    for app_id, _sec in sorted(tot.items(), key=lambda x: -x[1]):
        a = app_for_window(app_id)
        if a and a.get_id() not in skip and a.get_id() not in [x.get_id() for x in out] \
                and a.should_show():
            out.append(a)
        if len(out) >= n:
            break
    return out


def find_apps(q):
    """Программы по запросу: сперва набранное как есть (и начало названия), потом другая
    раскладка, потом синонимы."""
    found = []
    forms = search_forms(q)
    for a in Gio.AppInfo.get_all():
        if not a.should_show():
            continue
        hay = " ".join(x or "" for x in (a.get_display_name(), a.get_name(),
                                          a.get_description(),
                                          getattr(a, "get_generic_name", lambda: "")(),
                                          ";".join(a.get_keywords() or []) if hasattr(a, "get_keywords") else "",
                                          a.get_executable(), a.get_id())).lower()
        name = (a.get_display_name() or "").lower()
        score = search_score(hay, forms)
        if score is not None:
            starts = any(name.startswith(f) for f, wt in forms[0].items() if wt == score)
            found.append((score, 0 if starts else 1, name, a))
    found.sort(key=lambda x: x[:3])
    return [a for _r, _s, _n, a in found]


# ── вид ────────────────────────────────────────────────────────────────────

def colors():
    import xpbar_colors
    return xpbar_colors.colors()


CSS = """
window.start-bg { background: transparent; }
.menu-box {
    background-color: %(left_bg)s;
    border: 1px solid %(frame)s; border-radius: 9px 9px 0 0;
    box-shadow: 3px 0 8px alpha(black, 0.5);
    font-family: %(font)s; font-size: 16px; font-weight: normal; color: %(text)s;
}
.head {
    background-image: linear-gradient(to bottom, %(st_hover)s, %(st_top)s 18%%, %(st_mid)s 70%%, %(st_bot)s);
    border-radius: 8px 8px 0 0; padding: 5px 10px;   /* компактнее (15.10.2026, пользователь) */
    box-shadow: inset 0 1px %(st_hi)s;
}
.head-line { background-image: linear-gradient(to right, alpha(%(tertiary)s, 0.2), %(tertiary)s 50%%, alpha(%(tertiary)s, 0.2)); min-height: 2px; }
label.user { font-size: 24px; color: #ffffff; text-shadow: 1px 1px 1px alpha(black, 0.7); }
.avatar-frame { border: 2px solid %(st_hi)s; border-radius: 5px; background-color: %(base)s; }
.right-col { background-color: %(right_bg)s; border-left: 1px solid %(line)s; padding: 3px 0; }
.left-col { padding: 3px 0; }
button.item {
    background: transparent; background-image: none; border: none; box-shadow: none;
    border-radius: 0; padding: 2px 10px; margin: 0; min-height: 0; color: %(text)s;
    font-family: %(font)s; font-size: 16px; font-weight: normal;
}
button.item:hover, button.item.sel { background-color: %(hover)s; color: %(on_hover)s; }
button.item:hover label.sub, button.item.sel label.sub { color: alpha(%(on_hover)s, 0.8); }
label.sub { font-size: 12px; color: %(dim)s; }
label.all { font-size: 16px; }
label.all-arrow { font-family: %(nerd)s; font-size: 16px; color: %(tertiary)s; }
label.side-glyph { font-family: %(nerd)s; font-size: 18px; color: %(primary)s; min-width: 24px; }
button.item:hover label.side-glyph { color: %(on_hover)s; }
.cascade {
    background-color: %(left_bg)s; border: 1px solid %(frame)s; padding: 3px 0;
    box-shadow: 3px 3px 8px alpha(black, 0.5);
    font-family: %(font)s; font-size: 16px; color: %(text)s;
}
.sep { background-image: linear-gradient(to right, transparent, %(line)s 20%%, %(line)s 80%%, transparent); min-height: 1px; margin: 3px 10px; }
entry.search {
    background-color: %(base)s; color: %(text)s; border: 1px solid %(line)s; border-radius: 4px;
    font-family: %(font)s; font-size: 16px; padding: 2px 8px; margin: 3px 10px 1px 10px;
    box-shadow: inset 1px 1px 2px alpha(black, 0.5); caret-color: %(primary)s;
}
entry.search:focus { border-color: %(primary)s; }
.foot {
    background-image: linear-gradient(to bottom, %(st_mid)s, %(st_bot)s);
    padding: 5px 10px; box-shadow: inset 0 1px %(st_hi)s;
}
button.pw {
    background: transparent; background-image: none; border: none; box-shadow: none;
    padding: 2px 0; margin: 0; min-height: 24px; color: %(text)s;
    font-family: %(font)s; font-size: 16px; font-weight: normal; text-shadow: 1px 1px alpha(black, 0.6);
}
button.pw:hover { color: %(st_hi)s; }
label.pw-ico {
    font-family: %(nerd)s; font-size: 14px; color: %(on_primary)s;
    border-radius: 3px; padding: 0; min-width: 22px; min-height: 22px; border: 1px solid alpha(white, 0.35);
}
label.pw-lock { background-image: linear-gradient(to bottom, %(primary)s, %(st_bot)s); }
label.pw-out { background-image: linear-gradient(to bottom, %(tertiary)s, %(st_bot)s); }
label.pw-saver { background-image: linear-gradient(to bottom, %(secondary)s, %(st_bot)s); }
label.pw-off { background-image: linear-gradient(to bottom, %(error)s, %(err_dark)s); }
menu, .menu, .context-menu {
    background-color: %(surface)s; color: %(on_surface)s;
    border: 2px solid %(primary)s; border-radius: 8px; padding: 4px;
}
menuitem { font-family: %(font)s; font-size: 16px; padding: 5px 12px; border-radius: 5px; }
menuitem:hover { background-color: %(surface_high)s; color: %(primary)s; }
"""

# ── стили меню и вид кнопки «Пуск» (03.10.2026) ────────────────────────────
# Просьба: «добавим настройку внешнего вида Пуск … наши устоявшиеся стили:
# Default, Skeet, Beta». Стили только перекрашивают: шрифты, отступы и толщина
# рамок те же, что у default, — ширина меню (и подвал из четырёх кнопок) не
# меняется. Кнопку «Пуск» (default/square) рисует xpbar.py по BUTTON_FILE.
LOOK_FILE = os.path.expanduser("~/.config/hypr/state/start-menu-look")
BUTTON_FILE = os.path.expanduser("~/.config/hypr/state/start-button-look")
LOOKS = ("default", "skeet", "beta")
BUTTONS = ("default", "square")      # + <вид>-<символ> из start_glyphs.py (15.10.2026)


def read_choice(path, allowed):
    try:
        v = open(path).read().strip()
    except OSError:
        return allowed[0]
    return v if v in allowed else allowed[0]


def menu_look():
    return read_choice(LOOK_FILE, LOOKS)


def skeet_colors(c):
    """Как skeet_colors в settings_app.py: серые с лёгким оттенком акцента,
    акцент — насыщенный тон обоев (vivid.txt), иначе primary."""
    import xpbar_colors
    mix = xpbar_colors.mix
    acc = c["primary"]
    try:
        v = open(os.path.expanduser("~/.cache/matugen/vivid.txt")).read().strip()
        if v.startswith("#") and len(v) == 7:
            acc = v
    except OSError:
        pass

    def g(level, t=0.05):
        return mix("#%02x%02x%02x" % (level, level, level), acc, t)
    return dict(font=FONT, nerd=NERD, acc=acc, acc_l=mix(acc, "#ffffff", 0.22),
                acc_d=mix(acc, "#000000", 0.40),
                bg=g(0x13), rail=g(0x0c, 0.04), field=g(0x1b), field_l=g(0x24),
                line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                icon=g(0x5c, 0.10), icon_on=mix("#e2e2e2", acc, 0.22),
                text=mix("#cdcdcd", c["on_surface"], 0.35), text_dim=g(0x92, 0.10),
                tertiary=c["tertiary"], secondary=c["secondary"], err=c["error"],
                err_d=mix(c["error"], "#000000", 0.45))


def beta_colors(c):
    """Как beta_colors (Dark) в settings_app.py + цвета плиток (beta_tiles)."""
    import colorsys
    import xpbar_colors
    mix = xpbar_colors.mix
    bg = c["surface"]
    tiles = []
    bases = [c["primary"], c["tertiary"], c["secondary"]]
    for i in range(12):
        x = bases[i % 3].lstrip("#")
        r, g, b = (int(x[j:j + 2], 16) / 255 for j in (0, 2, 4))
        h, _l, _s = colorsys.rgb_to_hls(r, g, b)
        h = (h + (0.0, 60.0, -60.0, 120.0)[(i // 3) % 4] / 360.0) % 1.0
        tiles.append(xpbar_colors.rgb2hex(colorsys.hls_to_rgb(h, 0.47, 0.46)))
    return dict(font=FONT, nerd=NERD, bg=bg, rail=mix(bg, c["surface_container"], 0.55),
                bar=mix(bg, c["surface_container"], 0.85), card=c["surface_container"],
                field=c["surface_high"], text=c["on_surface"],
                dim=mix(c["on_surface_variant"], bg, 0.30), acc=c["primary"], on_acc=c["on_primary"],
                sel=mix(bg, c["primary"], 0.30), hover=mix(bg, c["primary"], 0.12),
                line=mix(c["surface_container"], c["on_surface"], 0.16),
                line_soft=mix(c["surface_container"], c["on_surface"], 0.08),
                line_strong=mix(bg, c["on_surface"], 0.32), err=c["error"],
                tile_ink="#f4f4fa", t0=tiles[0], t1=tiles[1], t2=tiles[2], tiles=tiles)


# «Пуск» Windows 11 (компактный) — у панели Centered max, вид один на все стили
W11_CSS = """
.w11 {
    background-color: transparent; border: none;
    border-radius: 8px; box-shadow: 0 6px 18px alpha(black, 0.5);
    font-family: %(font)s; font-size: 12px; font-weight: normal; color: %(text)s;
}
entry.w11-search {
    background-color: alpha(%(base)s, 0.85); background-image: none; color: %(text)s;
    border: 1px solid alpha(%(line)s, 0.8); border-bottom: 2px solid alpha(%(line)s, 0.8);
    border-radius: 16px; box-shadow: none; caret-color: %(primary)s;
    font-family: %(font)s; font-size: 12px; padding: 4px 14px; margin: 26px 32px 8px 32px;
    min-height: 30px;
}
entry.w11-search:focus { border-bottom-color: %(primary)s; }
entry.w11-search image { color: %(dim)s; }
.w11-head { margin: 14px 36px 6px 38px; min-height: 24px; }
label.w11-h { font-size: 12px; font-weight: bold; }
button.w11-more, button.w11-tile, button.w11-row, button.w11-icon {
    background: transparent; background-image: none; border: none; box-shadow: none;
    border-radius: 4px; margin: 0; min-height: 0; color: %(text)s; text-shadow: none;
    font-family: %(font)s; font-size: 12px; font-weight: normal; outline: none;
}
button.w11-more { background-color: alpha(white, 0.06); padding: 1px 8px; }
button.w11-more:hover { background-color: alpha(white, 0.11); }
label.w11-glyph { font-family: %(nerd)s; font-size: 12px; }
.w11-grid { margin: 0 24px; }
button.w11-tile { padding: 10px 2px 6px 2px; min-width: 92px; }
.w11-cell { min-width: 96px; min-height: 76px; }
button.w11-row { padding: 6px 10px; }
button.w11-tile:hover, button.w11-row:hover, button.w11-icon:hover { background-color: alpha(white, 0.07); }
button.w11-tile.sel, button.w11-row.sel {
    background-color: alpha(white, 0.09); box-shadow: inset 0 0 0 1px alpha(%(primary)s, 0.8);
}
label.w11-sub { font-size: 12px; color: %(dim)s; }
.w11-list { margin: 0 24px 6px 24px; }
label.w11-letter { font-size: 12px; color: %(primary)s; margin: 6px 0 2px 10px; }
.w11-foot {
    background-color: alpha(black, 0.2); border-top: 1px solid alpha(%(line)s, 0.6);
    border-radius: 0 0 8px 8px; padding: 12px 36px; margin-top: 18px;
}
label.w11-user { font-size: 12px; }
button.w11-icon { padding: 6px 9px; }
button.w11-icon label { font-family: %(nerd)s; font-size: 16px; }
"""

# Тот же «Пуск» Windows 11 на мониторе со стилем Skeet (22.10.2026, просьба: «адаптировать
# под стиль системы (Skeet)? А то как будто дизайн выбивается среди остальных»): глухой серый
# фон вместо размытых обоев, прямые углы, полоска-градиент сверху, поля и кнопки как в Настройках.
W11_SKEET_CSS = """
.w11.skeet { border-radius: 0; color: %(text)s; box-shadow: 0 0 0 1px %(line3)s, 0 6px 18px alpha(black, 0.55); }
.w11.skeet entry.w11-search {
    background-color: alpha(%(search)s, 0.88); color: %(text)s; border: 1px solid alpha(%(search_line)s, 0.9);
    border-radius: 16px; box-shadow: none; caret-color: %(acc)s; margin: 24px 30px 8px 30px;
}
.w11.skeet entry.w11-search:focus { border-color: %(acc)s; }
.w11.skeet entry.w11-search image { color: %(text_dim)s; }
.w11.skeet label.w11-h { color: %(text)s; }
.w11.skeet button.w11-more, .w11.skeet button.w11-tile, .w11.skeet button.w11-row,
.w11.skeet button.w11-icon { border-radius: 0; color: %(text)s; }
.w11.skeet button.w11-more {
    background-color: alpha(%(search)s, 0.88); box-shadow: inset 0 0 0 1px alpha(%(search_line)s, 0.9);
}
.w11.skeet button.w11-more label.w11-glyph { color: %(acc)s; }
.w11.skeet button.w11-more:hover { box-shadow: inset 0 0 0 1px %(acc)s; color: %(acc_l)s; }
/* наведение и выбор — тёмно-синим, как поиск (22.10.2026: «фон тоже сделай как поиск»), и ещё темнее
   («Можно еще более темнее сделать, выбор приложений фон») — sel_bg */
.w11.skeet button.w11-tile:hover, .w11.skeet button.w11-row:hover {
    background-color: alpha(%(sel_bg)s, 0.92); color: %(acc_l)s; box-shadow: inset 0 0 0 1px alpha(%(search_line)s, 0.9);
}
.w11.skeet button.w11-tile.sel, .w11.skeet button.w11-row.sel {
    background-color: alpha(%(sel_bg)s, 0.92); color: %(acc_l)s; box-shadow: inset 0 0 0 1px %(acc)s;
}
.w11.skeet label.w11-sub { color: %(text_dim)s; }
.w11.skeet label.w11-letter { color: %(acc)s; }
.w11.skeet .w11-foot {
    background-color: alpha(%(rail)s, 0.6); border-top: 1px solid %(line1)s; border-radius: 0;
    box-shadow: inset 0 1px %(line3)s;
}
.w11.skeet label.w11-user { color: %(acc_l)s; text-shadow: 1px 1px %(line3)s; }
.w11.skeet button.w11-icon label { color: #ffffff; }   /* «Вот эти иконки белыми» */
.w11.skeet button.w11-icon:hover { background-color: alpha(%(search)s, 0.88); }
.w11.skeet button.w11-icon:hover label { color: %(acc_l)s; }
"""

SKEET_CSS = """
.menu-box {
    background-color: %(bg)s; border: 1px solid %(line1)s; border-radius: 0;
    box-shadow: 0 0 0 1px %(line3)s, 3px 0 8px alpha(black, 0.5);
}
.head {
    background-color: %(rail)s;
    background-image: linear-gradient(to right, %(acc)s, %(tertiary)s, %(secondary)s);
    background-size: 100%% 2px; background-repeat: no-repeat; background-position: left top;
    border-radius: 0; box-shadow: none;
}
.head-line { background-image: linear-gradient(to bottom, %(line1)s 50%%, %(line3)s 50%%); }
label.user { color: %(acc_l)s; text-shadow: 1px 1px %(line3)s; }   /* не белым — акцентом (15.10.2026) */
.avatar-frame { border-color: %(line1)s; border-radius: 0; background-color: %(field)s; }
.right-col { background-color: %(rail)s; border-left-color: %(line2)s; }
button.item { color: %(text)s; }
button.item:hover, button.item.sel { background-color: %(field_l)s; color: %(acc_l)s; }
button.item:hover label.sub, button.item.sel label.sub { color: %(text_dim)s; }
label.sub { color: %(text_dim)s; }
label.all-arrow { color: %(acc)s; }
label.side-glyph { color: %(icon)s; }
button.item:hover label.side-glyph, button.item.sel label.side-glyph { color: %(icon_on)s; }
.cascade {
    background-color: %(bg)s; border-color: %(line1)s; color: %(text)s;
    box-shadow: 0 0 0 1px %(line3)s, 3px 3px 8px alpha(black, 0.5);
}
.sep { background-image: none; background-color: %(line2)s; }
entry.search {
    background-color: %(field)s; color: %(text)s; border-color: %(line1)s; border-radius: 0;
    box-shadow: inset 0 0 0 1px %(line3)s; caret-color: %(acc)s;
}
entry.search:focus { border-color: %(acc)s; }
.foot { background-image: none; background-color: %(rail)s; box-shadow: inset 0 1px %(line1)s; }
button.pw { color: %(text)s; text-shadow: none; }
button.pw:hover { color: %(acc_l)s; }
label.pw-ico { border-radius: 0; border-color: %(line3)s; color: #ffffff; }
label.pw-lock, label.pw-saver, label.pw-out { background-image: linear-gradient(to bottom, %(acc)s, %(acc_d)s); }
label.pw-off { background-image: linear-gradient(to bottom, %(err)s, %(err_d)s); }
menu, .menu, .context-menu { background-color: %(bg)s; color: %(text)s; border: 1px solid %(line1)s; border-radius: 0; }
menuitem { border-radius: 0; }
menuitem:hover { background-color: %(field_l)s; color: %(acc_l)s; }
"""

BETA_CSS = """
/* Beta (04.10.2026, вторая версия): была почти копией Skeet — Пользователь «не вижу разницы».
   Теперь по-настоящему «бета»: шапка залита акцентом, мягкие скругления, карточки,
   выбор — заливка акцентом с тёмным текстом, цветные плитки значков. */
.menu-box {
    background-color: %(card)s; border: 1px solid %(acc)s; border-radius: 10px 10px 0 0;
    box-shadow: 0 0 0 1px alpha(black, 0.4), 0 6px 18px alpha(black, 0.55); color: %(text)s;
}
.head {
    background-image: none; background-color: %(acc)s; border-radius: 9px 9px 0 0; box-shadow: none;
}
.head-line { background-image: none; background-color: %(acc)s; }
label.user { color: %(on_acc)s; text-shadow: none; }
.avatar-frame { border-color: %(on_acc)s; border-radius: 8px; background-color: %(field)s; }
.right-col { background-color: %(bg)s; border-left-color: transparent; border-radius: 8px 0 0 0; }
button.item { color: %(text)s; border-radius: 6px; }
button.item:hover { background-color: %(hover)s; color: %(text)s; }
button.item.sel { background-color: %(acc)s; color: %(on_acc)s; }
button.item.sel label.sub { color: %(on_acc)s; }
button.item:hover label.sub { color: %(dim)s; }
label.sub { color: %(dim)s; }
label.all-arrow { color: %(acc)s; }
.menu-box label.side-glyph { color: %(tile_ink)s; border-radius: 5px; }
button.item:hover label.side-glyph { color: %(tile_ink)s; }
.cascade { background-color: %(card)s; border-color: %(acc)s; border-radius: 8px; color: %(text)s; }
.sep { background-image: none; background-color: %(line_soft)s; }
entry.search {
    background-color: %(bg)s; color: %(text)s; border-color: %(line)s; border-radius: 8px;
    box-shadow: none; caret-color: %(acc)s;
}
entry.search:focus { border-color: %(acc)s; }
.foot { background-image: none; background-color: %(bg)s; box-shadow: inset 0 1px %(line)s; }
button.pw { color: %(text)s; text-shadow: none; border-radius: 6px; }
button.pw:hover { color: %(on_acc)s; background-color: %(acc)s; }
label.pw-ico { border-radius: 5px; border-color: transparent; color: %(tile_ink)s; background-image: none; }
label.pw-lock { background-color: %(t0)s; }
label.pw-saver { background-color: %(t1)s; }
label.pw-out { background-color: %(t2)s; }
label.pw-off { background-color: %(err)s; }
menu, .menu, .context-menu { background-color: %(card)s; color: %(text)s; border: 1px solid %(acc)s; border-radius: 8px; }
menuitem:hover { background-color: %(acc)s; color: %(on_acc)s; }
"""


TASKBAR_PINS = os.path.expanduser("~/.config/hypr/state/xpbar-pins.json")


def taskbar_app_id(a):
    """app_id окна niri для программы меню: StartupWMClass, иначе имя .desktop."""
    return a.get_startup_wm_class() or (a.get_id() or "").removesuffix(".desktop")


def taskbar_pins():
    try:
        d = json.load(open(TASKBAR_PINS))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("order", {})
    # закрепы у каждого монитора свои — {монитор: [app_id]}, как в xpbar.pins_load
    pins = d.get("pins")
    if isinstance(pins, list):
        pins = {c: list(pins) for c in d["order"]}
    d["pins"] = pins if isinstance(pins, dict) else {}
    return d


def taskbar_pin_toggle(app, conn):
    """Внутри xpbar — его pin_toggle (место на панели не прыгает); иначе — просто файл,
    xpbar подхватит по монитору папки."""
    main = sys.modules.get("__main__")
    if hasattr(main, "pin_toggle") and hasattr(main, "PINS_FILE"):
        main.pin_toggle(app, conn)
        return
    d = taskbar_pins()
    mine = d["pins"].setdefault(conn, [])
    (mine.remove if app in mine else mine.append)(app)
    tmp = TASKBAR_PINS + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, TASKBAR_PINS)


class StartMenu(Gtk.Window):
    def __init__(self, monitor, on_close=None):
        super().__init__(title="Start menu")
        # on_close задан — меню встроено в xpbar.py: закрытие = спрятать окно
        # (и сообщить панели), а не выйти из процесса.
        self.on_close = on_close
        self.sized = False
        self.get_style_context().add_class("start-bg")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-start-menu")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        if monitor:
            GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("key-press-event", self.on_key)

        bg = Gtk.EventBox()
        bg.set_visible_window(False)
        # Закрывать по ОТПУСКАНИЮ: при закрытии по нажатию отпускание доставалось
        # кнопке «Пуск» под меню — и меню тут же открывалось снова (01.10.2026).
        bg.connect("button-release-event", lambda *_a: self.quit())
        self.add(bg)
        # меню — в левом нижнем углу, над панелью (как у XP — вплотную к «Пуску»)
        holder = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        holder.set_halign(Gtk.Align.START)
        holder.set_valign(Gtk.Align.END)
        holder.set_margin_bottom(BAR_H)
        self.holder = holder
        # Каскады «Все программы» лежат поверх меню (Gtk.Overlay), как в XP: первый —
        # от кнопки вправо, второй — от строки папки.
        self.ov = Gtk.Overlay()
        bg.add(self.ov)
        self.ov.add(holder)
        self.casc = [self.cascade_holder(), self.cascade_holder()]
        self.casc_timer = None
        self.casc_cat = None
        catch = Gtk.EventBox()              # щелчки по самому меню не закрывают его
        catch.connect("button-press-event", lambda *_a: self.cascade_close() or True)
        catch.connect("button-release-event", lambda *_a: True)
        holder.add(catch)
        self.classic = catch
        self.w11_catch = None               # «Пуск» Windows 11 — строится при первом показе
        self.w11_on = False

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("menu-box")
        catch.add(box)
        box.pack_start(self.header(), False, False, 0)
        line = Gtk.Box()
        line.get_style_context().add_class("head-line")
        box.pack_start(line, False, False, 0)

        cols = Gtk.Box()
        box.pack_start(cols, True, True, 0)
        self.left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.left.get_style_context().add_class("left-col")
        self.left.set_size_request(290, -1)
        cols.pack_start(self.left, False, False, 0)
        right = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.right_col = right
        self.nav = None
        right.get_style_context().add_class("right-col")
        right.set_size_request(230, -1)
        cols.pack_start(right, False, False, 0)

        # левая колонка: список (меняется поиском) + «Все программы» + поиск
        self.apps_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.left.pack_start(self.apps_box, True, True, 0)
        self.left.pack_start(self.sep(), False, False, 0)
        allb = Gtk.Button()
        allb.get_style_context().add_class("item")
        ab = Gtk.Box(spacing=8)
        ab.set_halign(Gtk.Align.CENTER)
        lab = Gtk.Label(label="Все программы")
        lab.get_style_context().add_class("all")
        arr = Gtk.Label(label="\U000f0142")
        arr.get_style_context().add_class("all-arrow")
        ab.pack_start(lab, False, False, 0)
        ab.pack_start(arr, False, False, 0)
        allb.add(ab)
        # Как в Windows XP (02.10.2026): список программ выезжает вбок от
        # кнопки — по наведению (с короткой задержкой) или по щелчку; щелчок ещё раз
        # закрывает. Раньше кнопка открывала rofi.
        self.allb = allb
        allb.connect("clicked", lambda _b: self.cascade_toggle())
        allb.connect("enter-notify-event", lambda *_a: self.cascade_later(self.cascade_open, 320))
        allb.connect("leave-notify-event", lambda *_a: self.cascade_cancel())
        self.left.pack_start(allb, False, False, 0)
        self.search = Gtk.Entry()
        self.search.get_style_context().add_class("search")
        self.search.set_placeholder_text("Поиск программ…")
        self.search.connect("changed", lambda _e: (self.cascade_close(), self.fill_apps()))
        self.search.connect("activate", lambda _e: self.first and self.launch(self.first))
        self.left.pack_start(self.search, False, False, 0)
        self.first = None

        # правая колонка
        home = os.path.expanduser("~")
        folders = [("\U000f0219", "Документы", os.path.join(home, "Documents")),
                   ("\U000f021f", "Изображения", os.path.join(home, "Pictures")),
                   ("\U000f1359", "Музыка", os.path.join(home, "Music")),
                   ("\U000f024d", "Загрузки", os.path.join(home, "Downloads")),
                   ("\U000f0fce", "Видео", os.path.join(home, "Videos"))]
        for g, name, path in folders:
            if os.path.isdir(path):
                right.pack_start(self.side(g, name, lambda p=path: self.launch_cmd("xdg-open", p)),
                                 False, False, 0)
        right.pack_start(self.sep(), False, False, 0)
        py = sys.executable
        for g, name, cmd in (
                ("\U000f0493", "Настройки", [py, os.path.join(HERE, "settings_app.py")]),
                ("\U000f062e", "Центр управления", [py, os.path.join(HERE, "control_center.py"), "--center"]),
                ("\U000f034d", "Карта конфигов", [py, os.path.join(HERE, "config_map.py")]),
                ("\U000f0128", "Экранное время", [py, os.path.join(HERE, "screentime.py")])):
            right.pack_start(self.side(g, name, lambda c=cmd: self.launch_cmd(*c)), False, False, 0)
        right.pack_start(self.sep(), False, False, 0)
        right.pack_start(self.side("\U000f0349", "Поиск", lambda: self.search.grab_focus()),
                         False, False, 0)
        right.pack_start(self.side("\U000f018d", "Выполнить…",
                                   lambda: self.launch_cmd("rofi", "-show", "run")), False, False, 0)

        box.pack_start(self.footer(), False, False, 0)
        self.fill_apps()
        self.get_child().show_all()          # само окно — только в open()
        if on_close is None:
            self.open()

    # ── «Все программы» ───────────────────────────────────────────────────
    CATS = (("staticOS", ("X-StaticOS",)),
            ("Игры", ("Game",)),
            ("Разработка", ("Development", "IDE")),
            ("Интернет", ("Network", "WebBrowser", "Email", "Chat", "InstantMessaging")),
            ("Графика", ("Graphics", "Photography")),
            ("Звук и видео", ("AudioVideo", "Audio", "Video", "Player")),
            ("Офис", ("Office",)),
            ("Настройки", ("Settings",)),
            ("Система", ("System", "Monitor", "TerminalEmulator", "FileManager")),
            ("Стандартные", ("Utility", "TextEditor", "Accessories")))

    def cascade_holder(self):
        ev = Gtk.EventBox()                 # щелчки по каскаду меню не закрывают
        ev.connect("button-press-event", lambda *_a: True)
        ev.connect("button-release-event", lambda *_a: True)
        ev.set_halign(Gtk.Align.START)
        ev.set_valign(Gtk.Align.START)
        ev.set_no_show_all(True)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("cascade")
        ev.add(box)
        self.ov.add_overlay(ev)
        return ev

    def cascade_cats(self):
        cats = {name: [] for name, _k in self.CATS}
        cats["Прочее"] = []
        for a in Gio.AppInfo.get_all():
            if not a.should_show():
                continue
            have = set((a.get_categories() or "").split(";")) if hasattr(a, "get_categories") else set()
            name = next((n for n, keys in self.CATS if have & set(keys)), "Прочее")
            cats[name].append(a)
        for v in cats.values():
            v.sort(key=lambda a: (a.get_display_name() or "").lower())
        return [(n, v) for n, v in cats.items() if v]

    def cascade_fill(self, ev, rows, max_h):
        box = ev.get_child()
        for c in box.get_children():
            c.destroy()
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for r in rows:
            inner.pack_start(r, False, False, 0)
        inner.show_all()
        h = inner.get_preferred_height()[1]
        if h > max_h:                        # длинный список — с прокруткой
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.set_size_request(-1, max_h)
            sw.add(inner)
            box.pack_start(sw, False, False, 0)
            h = max_h
        else:
            box.pack_start(inner, False, False, 0)
        box.show_all()
        return h + 6

    def cascade_place(self, ev, x, bottom, height):
        """Поставить каскад: левый край x, низ — bottom (вверх, пока хватает места)."""
        top = max(4, bottom - height)
        ev.set_margin_start(int(x))
        ev.set_margin_top(int(top))
        ev.show()

    def cascade_open(self):
        self.casc_timer = None
        if self.casc[0].get_visible():
            return False
        rows = []
        for name, apps in self.cascade_cats():
            b = Gtk.Button()
            b.get_style_context().add_class("item")
            bx = Gtk.Box(spacing=8)
            g = Gtk.Label(label="\U000f024b")
            g.get_style_context().add_class("side-glyph")
            bx.pack_start(g, False, False, 0)
            bx.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
            arr = Gtk.Label(label="\U000f0142")
            arr.get_style_context().add_class("all-arrow")
            bx.pack_end(arr, False, False, 0)
            b.add(bx)
            b.set_size_request(210, -1)
            b.connect("enter-notify-event",
                      lambda w, _e, n=name, a=apps: self.cascade_later(lambda: self.cascade_sub(w, n, a), 110))
            b.connect("clicked", lambda w, n=name, a=apps: self.cascade_sub(w, n, a))
            rows.append(b)
        win_h = self.get_allocated_height()
        h = self.cascade_fill(self.casc[0], rows, win_h - 60)
        pos = self.allb.translate_coordinates(self, self.allb.get_allocated_width(),
                                              self.allb.get_allocated_height())
        x, bottom = pos if pos else (290, win_h - BAR_H - 40)
        self.cascade_place(self.casc[0], x - 2, bottom, h)
        self.allb.get_style_context().add_class("sel")
        return False

    def cascade_sub(self, row, name, apps):
        self.casc_timer = None
        if self.casc_cat == name and self.casc[1].get_visible():
            return False
        self.casc_cat = name
        for c in row.get_parent().get_children():
            (c.get_style_context().add_class if c is row else c.get_style_context().remove_class)("sel")
        win_h = self.get_allocated_height()
        rows = [self.app_row(a, False) for a in apps]
        for r in rows:
            r.set_size_request(250, -1)
        h = self.cascade_fill(self.casc[1], rows, win_h - 60)
        pos = row.translate_coordinates(self, row.get_allocated_width(), 0)
        x, top = pos if pos else (500, 100)
        # как в XP: верх подменю — у строки папки; не помещается — сдвигается вверх
        bottom = min(win_h - BAR_H - 2, top + h)
        self.cascade_place(self.casc[1], x - 2, bottom, h)
        return False

    def cascade_later(self, fn, ms):
        self.cascade_cancel()
        self.casc_timer = GLib.timeout_add(ms, fn)
        return False

    def cascade_cancel(self):
        if self.casc_timer:
            GLib.source_remove(self.casc_timer)
            self.casc_timer = None
        return False

    def cascade_close(self):
        self.cascade_cancel()
        for ev in self.casc:
            ev.hide()
        self.casc_cat = None
        self.allb.get_style_context().remove_class("sel")

    def cascade_toggle(self):
        if self.casc[0].get_visible():
            self.cascade_close()
        else:
            self.cascade_open()

    def open(self, center=False):
        """Показать (встроенное меню — заранее построенное, поэтому мгновенно).
        center — панель в виде Centered max: меню посередине, над «Пуском» в ряду значков."""
        self.holder.set_halign(Gtk.Align.CENTER if center else Gtk.Align.START)
        self.w11_on = center
        if center and self.w11_catch is None:
            self.w11_build()
        self.classic.set_visible(not center)
        if self.w11_catch is not None:
            self.w11_catch.set_visible(center)
        if center:
            self.w11_restyle()
            self.w11_reset()
            self.show()
            self.w11_search.grab_focus()
            return
        self.cascade_close()
        if getattr(self, "nav", None) is not None:
            for c in ("left", "right"):
                for b in self.nav_items(c):
                    b.get_style_context().remove_class("sel")
            self.nav = None
        if self.search.get_text():
            self.search.set_text("")         # поиск прошлого раза — сбросить
        self.show()
        self.search.grab_focus()
        if not self.sized:
            # высота списка — по первому показу: при поиске меню не прыгает
            self.sized = True
            GLib.idle_add(lambda: self.apps_box.set_size_request(
                -1, self.apps_box.get_allocated_height()) and False)

    # ── части ─────────────────────────────────────────────────────────────
    def header(self):
        h = Gtk.Box(spacing=12)
        h.get_style_context().add_class("head")
        fr = Gtk.Box()
        fr.get_style_context().add_class("avatar-frame")
        img = Gtk.Image()
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR, 48, 48, True)
            img.set_from_pixbuf(pb)
        except GLib.Error:
            img.set_from_icon_name("avatar-default", Gtk.IconSize.DIALOG)
        fr.add(img)
        h.pack_start(fr, False, False, 0)
        # Имя — как в центре управления (15.10.2026, просьба: «именно staticxyzz»): файл
        # state/display-name, иначе полное имя учётной записи, иначе логин.
        try:
            shown = open(os.path.expanduser("~/.config/hypr/state/display-name")).read().strip()
        except OSError:
            shown = ""
        real = (GLib.get_real_name() or "").strip()
        shown = shown or (real if real and real != "Unknown" else GLib.get_user_name())
        lab = Gtk.Label(label=shown, xalign=0)
        lab.get_style_context().add_class("user")
        h.pack_start(lab, False, False, 0)
        return h

    def footer(self):
        f = Gtk.Box()
        f.get_style_context().add_class("foot")
        # Четыре кнопки делят ширину поровну (03.10.2026): раньше они жались вправо за
        # распоркой и сдавливали друг друга.
        # кнопки по всей ширине с равными промежутками и полями по бокам (Пользователь:
        # «не толкай в самую правую часть, слева место есть — займи его»)
        f.set_spacing(6)
        py = sys.executable
        for g, cls, name, cmd in (
                ("\U000f033e", "pw-lock", "Блокировка", [os.path.join(HERE, "lockscreen")]),
                ("\U000f07f4", "pw-saver", "Заставка", [py, os.path.join(HERE, "screensaver.py")]),
                ("\U000f0904", "pw-out", "Сон", [py, os.path.join(HERE, "power_menu.py"), "--only", "suspend"]),
                # «Питание» — окно «Выключить компьютер» в духе XP: Выход, Выключение,
                # Перезагрузка (03.10.2026, по снимку пользователя).
                ("\U000f0425", "pw-off", "Питание", [py, os.path.join(HERE, "power_xp.py")])):
            b = Gtk.Button()
            b.get_style_context().add_class("pw")
            bb = Gtk.Box(spacing=5)
            ico = Gtk.Label(label=g)
            ico.get_style_context().add_class("pw-ico")
            ico.set_xalign(0.5)
            ico.set_yalign(0.5)
            ico.set_valign(Gtk.Align.CENTER)
            ico.get_style_context().add_class(cls)
            bb.pack_start(ico, False, False, 0)
            bb.pack_start(Gtk.Label(label=name), False, False, 0)
            b.add(bb)
            bb.set_halign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, c=cmd: self.launch_cmd(*c))
            f.pack_start(b, True, True, 0)
        return f

    def sep(self):
        s = Gtk.Box()
        s.get_style_context().add_class("sep")
        return s

    def side(self, glyph, name, cb):
        b = Gtk.Button()
        b.get_style_context().add_class("item")
        bx = Gtk.Box(spacing=10)
        g = Gtk.Label(label=glyph)
        g.get_style_context().add_class("side-glyph")
        # номер плитки — для вида Beta (цветные плитки-значки, как в Настройках)
        self._side_n = getattr(self, "_side_n", -1) + 1
        g.get_style_context().add_class("t%d" % (self._side_n % 12))
        bx.pack_start(g, False, False, 0)
        bx.pack_start(Gtk.Label(label=name, xalign=0), True, True, 0)
        b.add(bx)
        b.connect("clicked", lambda _b: cb())
        return b

    def app_row(self, a, big):
        b = Gtk.Button()
        b.get_style_context().add_class("item")
        bx = Gtk.Box(spacing=10)
        img = Gtk.Image()
        icon = a.get_icon() or Gio.ThemedIcon.new("application-x-executable")
        img.set_from_gicon(icon, Gtk.IconSize.DND)
        img.set_pixel_size(32 if big else 24)
        bx.pack_start(img, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=a.get_display_name(), xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        # 18 знаков влезают в левую колонку (290 px) вместе со значком; при 22 длинное
        # название в результатах поиска раздвигало весь «Пуск» вправо (04.10.2026)
        name.set_max_width_chars(18)
        col.pack_start(name, False, False, 0)
        if big:
            role = role_of(a)
            if role:
                sub = Gtk.Label(label=role, xalign=0)
                sub.set_ellipsize(Pango.EllipsizeMode.END)
                sub.set_max_width_chars(24)
                sub.get_style_context().add_class("sub")
                col.pack_start(sub, False, False, 0)
        bx.pack_start(col, True, True, 0)
        b.add(bx)
        b.connect("clicked", lambda _b: self.launch(a))
        b.connect("button-press-event", lambda _w, e: self.app_menu(a, e) if e.button == 3 else False)
        return b

    def fill_apps(self):
        self.nav = None
        for c in self.apps_box.get_children():
            c.destroy()
        q = self.search.get_text().strip().lower()
        self.first = None
        if q:
            found = find_apps(q)
            for i, a in enumerate(found[:9]):
                row = self.app_row(a, False)
                if i == 0:
                    self.first = a
                    row.get_style_context().add_class("sel")
                self.apps_box.pack_start(row, False, False, 0)
            if not found:
                lab = Gtk.Label(label="Ничего не нашлось", xalign=0)
                lab.get_style_context().add_class("sub")
                lab.set_margin_start(12)
                lab.set_margin_top(8)
                self.apps_box.pack_start(lab, False, False, 0)
        else:
            pins = pinned()
            for a in pins:
                self.apps_box.pack_start(self.app_row(a, True), False, False, 0)
            freq = frequent({a.get_id() for a in pins})
            if freq:
                self.apps_box.pack_start(self.sep(), False, False, 0)
                for a in freq:
                    self.apps_box.pack_start(self.app_row(a, False), False, False, 0)
        self.apps_box.show_all()

    # ── «Пуск» как в Windows 11 ──────────────────────────────────────────
    # 21.10.2026, просьба: «Пуск… как в Windows новых, только для вида по центру… в стиле
    # Windows 11, но компактную версию — в Windows 11 она слишком большая». Своя панель в том
    # же окне, только у нижней панели Centered max: поиск сверху, закреплённые сеткой,
    # «Рекомендуем» (частые за неделю), внизу пользователь и питание. «Все ›» — список всех
    # программ по алфавиту на месте сетки. Закреплённые — те же, что в «Пуске» XP.
    # Тот же день, позже: «перестарался с компактностью… можешь сделать Пуск побольше,
    # больше похожий на Windows» — 6 колонок, значки 40 px, сетка не меньше двух рядов
    # (недостающее добирают частые программы), «Рекомендуем» — шесть в две колонки.
    W11_COLS = 6
    W11_PINS = 18
    W11_MIN = 12
    W11_REC = 6

    def w11_build(self):
        catch = Gtk.EventBox()
        catch.connect("button-press-event", lambda *_a: True)
        catch.connect("button-release-event", lambda *_a: True)
        catch.set_margin_bottom(8)          # как в Windows 11 — над панелью с зазором
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.get_style_context().add_class("w11")
        box.connect("draw", self.w11_backdrop)
        box.connect_after("draw", self.w11_frame)
        catch.add(box)
        self.w11_box = box
        self.w11_search = Gtk.Entry()
        self.w11_search.get_style_context().add_class("w11-search")
        self.w11_search.set_placeholder_text("Поиск программ…")
        self.w11_search.set_icon_from_icon_name(Gtk.EntryIconPosition.PRIMARY, "system-search-symbolic")
        self.w11_search.connect("changed", lambda _e: self.w11_fill())
        self.w11_search.connect("activate", lambda _e: self.w11_enter())
        box.pack_start(self.w11_search, False, False, 0)

        self.w11_stack = Gtk.Stack()
        self.w11_stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.w11_stack.set_transition_duration(120)
        box.pack_start(self.w11_stack, True, True, 0)
        # главная: закреплённые и рекомендуемые
        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        home.pack_start(self.w11_head("Закреплённые", "Все", "\U000f0142",
                                      lambda: self.w11_page("all")), False, False, 0)
        self.w11_grid = Gtk.Grid()
        self.w11_grid.get_style_context().add_class("w11-grid")
        self.w11_grid.set_halign(Gtk.Align.CENTER)
        home.pack_start(self.w11_grid, False, False, 0)
        self.w11_rec_head = self.w11_head("Рекомендуем")
        home.pack_start(self.w11_rec_head, False, False, 0)
        self.w11_rec = Gtk.Grid()
        self.w11_rec.get_style_context().add_class("w11-grid")
        self.w11_rec.set_halign(Gtk.Align.CENTER)
        home.pack_start(self.w11_rec, False, False, 0)
        self.w11_stack.add_named(home, "home")
        # все программы по алфавиту
        allp = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        allp.pack_start(self.w11_head("Все программы", "Назад", "\U000f0141",
                                      lambda: self.w11_page("home"), back=True), False, False, 0)
        sw = Gtk.ScrolledWindow()
        sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        sw.set_size_request(-1, 60)         # высоту задаёт главная — меню не прыгает
        self.w11_all = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.w11_all.get_style_context().add_class("w11-list")
        sw.add(self.w11_all)
        allp.pack_start(sw, True, True, 0)
        self.w11_stack.add_named(allp, "all")
        # результаты поиска
        self.w11_found = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.w11_found.get_style_context().add_class("w11-list")
        self.w11_stack.add_named(self.w11_found, "find")

        box.pack_start(self.w11_footer(), False, False, 0)
        self.holder.add(catch)
        self.w11_catch = catch
        self.w11_sel = None
        self.w11_first = None
        self.w11_fill()
        catch.show_all()

    # Подложка и рамка (21.10.2026, просьба: «убери прозрачность в этом Пуске, и сделай вместо
    # него блюр», «и рамки добавь… немного ближе к стилю системы»). Правило niri с blur здесь
    # не годится: слой меню — во весь экран (ловит щелчок мимо), размылся бы весь экран. Поэтому
    # как у виджетов на обоях: под меню — свои размытые обои этого монитора (окна не
    # просвечивают), сверху тонировка; рамка — по стилю системы монитора (stack_mode.style).
    W11_BLUR = 16
    W11_TINT = 0.72

    def w11_out(self):
        return getattr(self, "connector", None) or os.environ.get("START_MENU_OUTPUT")

    def w11_style(self):
        import stack_mode
        return stack_mode.style(self.w11_out())

    def w11_restyle(self):
        """Класс .skeet — по стилю монитора на каждое открытие (стиль у монитора свой)."""
        skeet = self.w11_style() == "skeet"
        ctx = self.w11_box.get_style_context()
        (ctx.add_class if skeet else ctx.remove_class)("skeet")
        self.w11_box.queue_draw()

    def w11_blurred(self, W, H):
        """Размытые обои монитора на W×H (кэш по пути обоев и размеру) или None."""
        out = self.w11_out()
        try:
            txt = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        path = None
        for line in txt.splitlines():
            m = re.match(r"^:?\s*([\w-]+):.*?image:\s*(.+?)\s*$", line)
            if m and (m.group(1) == out or path is None):
                path = m.group(2)
        key = (path, W, H)
        cache = getattr(self, "w11_bg", None)
        if cache and cache[0] == key:
            return cache[1]
        surf = None
        try:
            import numpy as np
            from PIL import Image, ImageFilter, ImageOps
            im = Image.open(path)
            im.seek(0)
            k = 4                            # размываем уменьшенную копию, как виджеты
            small = ImageOps.fit(im.convert("RGB"), (max(1, W // k), max(1, H // k)), Image.BILINEAR)
            small = small.filter(ImageFilter.GaussianBlur(self.W11_BLUR / k))
            arr = np.asarray(small.resize((W, H), Image.BILINEAR).convert("RGBA"))
            buf = np.ascontiguousarray(arr[..., [2, 1, 0, 3]])
            surf = (cairo.ImageSurface.create_for_data(memoryview(buf), cairo.FORMAT_RGB24, W, H, W * 4), buf)
        except Exception as e:               # noqa: BLE001 — без обоев: просто тонировка
            print("пуск: подложка", path, e, file=sys.stderr)
        self.w11_bg = (key, surf)
        return surf

    @staticmethod
    def w11_round(cr, x, y, w, h, r):
        cr.new_sub_path()
        for cx, cy, a in ((x + w - r, y + r, -1.5708), (x + w - r, y + h - r, 0),
                          (x + r, y + h - r, 1.5708), (x + r, y + r, 3.14159)):
            cr.arc(cx, cy, r, a, a + 1.5708)
        cr.close_path()

    def w11_backdrop(self, box, cr):
        a = box.get_allocation()
        W, H = self.get_allocated_width(), self.get_allocated_height()
        pos = box.translate_coordinates(self, 0, 0)
        skeet = self.w11_style() == "skeet"
        if skeet:                            # Skeet — прямые углы, как рамка
            cr.rectangle(0, 0, a.width, a.height)
        else:
            self.w11_round(cr, 0, 0, a.width, a.height, 8)
        cr.save()
        cr.clip()
        bg = self.w11_blurred(W, H) if W > 1 and H > 1 else None
        if bg is not None and pos:
            cr.set_source_surface(bg[0], -pos[0], -pos[1])
            cr.paint()
        import xpbar_colors
        c = xpbar_colors.colors()
        tint = xpbar_colors.mix(c["base"], c["primary"], 0.07)
        if skeet:
            # 22.10.2026, просьба: «добавь блюр… как было до этого… цвет приблизить к тому что
            # было, но это не должно выбиваться» — размытые обои под тонировкой посередине
            # между прежней синеватой и серой Skeet (как у Настроек и «Энергии»), чуть гуще.
            import rec_style
            tint = xpbar_colors.mix(rec_style.colors("skeet")["bg"], tint, 0.5)
        rgb = Gdk.RGBA()
        rgb.parse(tint)
        alpha = (self.W11_TINT + 0.08 if skeet else self.W11_TINT) if bg is not None else 0.97
        cr.set_source_rgba(rgb.red, rgb.green, rgb.blue, alpha)
        cr.paint()
        cr.restore()
        return False

    def w11_frame(self, box, cr):
        import rec_menu
        import stack_mode
        st = stack_mode.style(self.w11_out())
        C = rec_menu.style_colors(st)
        mix = rec_menu.mix
        a = box.get_allocation()
        w, h = a.width, a.height
        if st == "skeet":                    # gamesense: светлая, средняя, светлая, чёрная
            rings = ((C["line1_on"], 1), (C["line2"], 2), (C["line1_on"], 1), (C["line3"], 1))
        elif st == "beta":
            rings = ((mix(C["line_strong"], C["acc"], 0.55), 1),)
        else:                                # XP: тёмная линия снаружи, полоса цвета заголовка
            rings = ((C["st_dark"], 1), (C["st_mid"], 2), (C["st_dark"], 1))
        square = st == "skeet"
        i = 0
        for col, t in rings:
            cr.set_source_rgb(*col[:3])
            cr.set_line_width(t)
            if square:
                cr.rectangle(i + t / 2, i + t / 2, w - 2 * i - t, h - 2 * i - t)
            else:
                self.w11_round(cr, i + t / 2, i + t / 2, w - 2 * i - t, h - 2 * i - t, max(1, 8 - i - t / 2))
            cr.stroke()
            i += t
        if square:                           # полоска gamesense под рамкой: цвета и их тень
            strip = C["strip"]
            for row, k in ((0, 0.0), (1, 0.55)):
                g = cairo.LinearGradient(i, 0, w - i, 0)
                for n, col in enumerate(strip):
                    g.add_color_stop_rgb(n / max(1, len(strip) - 1), *mix(col, (0, 0, 0), k)[:3])
                cr.set_source(g)
                cr.rectangle(i, i + row, w - 2 * i, 1)
                cr.fill()
        return False

    def w11_head(self, title, more=None, glyph=None, cb=None, back=False):
        h = Gtk.Box()
        h.get_style_context().add_class("w11-head")
        lab = Gtk.Label(label=title, xalign=0)
        lab.get_style_context().add_class("w11-h")
        if more:
            b = Gtk.Button()
            b.get_style_context().add_class("w11-more")
            bx = Gtk.Box(spacing=4)
            g = Gtk.Label(label=glyph)
            g.get_style_context().add_class("w11-glyph")
            t = Gtk.Label(label=more)
            if back:                         # «‹ Назад» — стрелка слева
                bx.pack_start(g, False, False, 0)
                bx.pack_start(t, False, False, 0)
            else:
                bx.pack_start(t, False, False, 0)
                bx.pack_start(g, False, False, 0)
            b.add(bx)
            b.connect("clicked", lambda _b: cb())
            h.pack_end(b, False, False, 0)
        h.pack_start(lab, True, True, 0)
        return h

    def w11_footer(self):
        f = Gtk.Box(spacing=2)
        f.get_style_context().add_class("w11-foot")
        av = Gtk.DrawingArea()
        av.set_size_request(32, 32)
        av.set_valign(Gtk.Align.CENTER)
        try:
            pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR, 32, 32, False)
        except GLib.Error:
            pb = None

        def draw_av(_w, cr):
            cr.arc(16, 16, 16, 0, 6.2832)    # круглый аватар, как в Windows 11 (и в Skeet — просьба 22.10)
            cr.clip()
            if pb is not None:
                Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            else:
                cr.set_source_rgba(1, 1, 1, 0.2)
            cr.paint()
            return False
        av.connect("draw", draw_av)
        f.pack_start(av, False, False, 0)
        name = self.header().get_children()[-1].get_text()    # то же имя, что в «Пуске» XP
        lab = Gtk.Label(label=name, xalign=0)
        lab.get_style_context().add_class("w11-user")
        lab.set_margin_start(10)
        f.pack_start(lab, True, True, 0)
        py = sys.executable
        for g, tip, cmd in (
                ("\U000f0425", "Питание", [py, os.path.join(HERE, "power_xp.py")]),
                ("\U000f033e", "Блокировка", [os.path.join(HERE, "lockscreen")]),
                ("\U000f0493", "Настройки", [py, os.path.join(HERE, "settings_app.py")])):
            b = Gtk.Button()
            b.get_style_context().add_class("w11-icon")
            b.add(Gtk.Label(label=g))
            b.set_tooltip_text(tip)
            b.connect("clicked", lambda _b, c=cmd: self.launch_cmd(*c))
            f.pack_end(b, False, False, 0)
        return f

    def w11_tile(self, a):
        b = Gtk.Button()
        b.get_style_context().add_class("w11-tile")
        bx = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        img = Gtk.Image()
        img.set_from_gicon(a.get_icon() or Gio.ThemedIcon.new("application-x-executable"),
                           Gtk.IconSize.DIALOG)
        img.set_pixel_size(40)
        bx.pack_start(img, False, False, 0)
        lab = Gtk.Label(label=a.get_display_name())
        lab.set_ellipsize(Pango.EllipsizeMode.END)
        lab.set_max_width_chars(10)
        lab.set_width_chars(10)
        bx.pack_start(lab, False, False, 0)
        b.add(bx)
        b.set_tooltip_text(a.get_display_name())
        self.w11_hook(b, a)
        return b

    def w11_row(self, a, sub=True):
        b = Gtk.Button()
        b.get_style_context().add_class("w11-row")
        bx = Gtk.Box(spacing=10)
        img = Gtk.Image()
        img.set_from_gicon(a.get_icon() or Gio.ThemedIcon.new("application-x-executable"),
                           Gtk.IconSize.DND)
        img.set_pixel_size(32)
        bx.pack_start(img, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        col.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=a.get_display_name(), xalign=0)
        name.set_ellipsize(Pango.EllipsizeMode.END)
        col.pack_start(name, False, False, 0)
        role = role_of(a) if sub else ""
        if role:
            r = Gtk.Label(label=role, xalign=0)
            r.set_ellipsize(Pango.EllipsizeMode.END)
            r.get_style_context().add_class("w11-sub")
            col.pack_start(r, False, False, 0)
        bx.pack_start(col, True, True, 0)
        b.add(bx)
        self.w11_hook(b, a)
        return b

    def w11_hook(self, b, a):
        b.connect("clicked", lambda _b: self.launch(a))
        b.connect("button-press-event", lambda _w, e: self.app_menu(a, e) if e.button == 3 else False)
        b.connect("enter-notify-event", lambda w, _e: self.w11_select(None))

    def w11_fill(self):
        if self.w11_catch is None:
            return
        self.w11_select(None)
        q = self.w11_search.get_text().strip().lower()
        self.w11_first = None
        if q:
            for c in self.w11_found.get_children():
                c.destroy()
            found = find_apps(q)[:7]
            for i, a in enumerate(found):
                row = self.w11_row(a)
                if i == 0:
                    self.w11_first = a
                    row.get_style_context().add_class("sel")
                self.w11_found.pack_start(row, False, False, 0)
            if not found:
                lab = Gtk.Label(label="Ничего не нашлось", xalign=0)
                lab.get_style_context().add_class("w11-sub")
                lab.set_margin_start(20)
                lab.set_margin_top(10)
                self.w11_found.pack_start(lab, False, False, 0)
            self.w11_found.show_all()
            self.w11_stack.set_visible_child_name("find")
            return
        if self.w11_stack.get_visible_child_name() == "find":
            self.w11_stack.set_visible_child_name("home")
        for grid in (self.w11_grid, self.w11_rec, self.w11_all):
            for c in grid.get_children():
                c.destroy()
        pins = pinned()[:self.W11_PINS]
        if len(pins) < self.W11_MIN:
            pins += frequent({a.get_id() for a in pins}, self.W11_MIN - len(pins))
        for i, a in enumerate(pins):
            self.w11_grid.attach(self.w11_tile(a), i % self.W11_COLS, i // self.W11_COLS, 1, 1)
        # пустые клетки до полного ряда — чтобы сетка не съёживалась к центру
        for i in range(len(pins), max(self.W11_COLS, -(-len(pins) // self.W11_COLS) * self.W11_COLS)):
            ph = Gtk.Box()
            ph.get_style_context().add_class("w11-cell")
            self.w11_grid.attach(ph, i % self.W11_COLS, i // self.W11_COLS, 1, 1)
        rec = frequent({a.get_id() for a in pins}, self.W11_REC)
        for i, a in enumerate(rec):
            row = self.w11_row(a)
            row.set_size_request(272, -1)
            self.w11_rec.attach(row, i % 2, i // 2, 1, 1)
        letter = None
        apps = sorted((a for a in Gio.AppInfo.get_all() if a.should_show()),
                      key=lambda a: (a.get_display_name() or "").lower())
        for a in apps:
            ch = (a.get_display_name() or "?")[:1].upper()
            ch = ch if ch.isalpha() else "#"
            if ch != letter:
                letter = ch
                lab = Gtk.Label(label=ch, xalign=0)
                lab.get_style_context().add_class("w11-letter")
                self.w11_all.pack_start(lab, False, False, 0)
            self.w11_all.pack_start(self.w11_row(a, sub=False), False, False, 0)
        for w in (self.w11_grid, self.w11_rec, self.w11_all):
            w.show_all()
        self.w11_rec_head.set_visible(bool(rec))

    def w11_reset(self):
        if self.w11_search.get_text():
            self.w11_search.set_text("")
        self.w11_stack.set_visible_child_name("home")
        self.w11_select(None)

    def w11_page(self, name):
        self.click_sound()
        self.w11_select(None)
        self.w11_stack.set_visible_child_name(name)
        self.w11_search.grab_focus()

    def w11_enter(self):
        if self.w11_sel is not None:
            self.w11_sel.clicked()
        elif self.w11_first is not None:
            self.launch(self.w11_first)

    def w11_items(self):
        out = []

        def walk(w):
            if not w.get_visible():
                return
            if isinstance(w, Gtk.Button):
                out.append(w)
            elif isinstance(w, Gtk.Container):
                w.forall(walk)
        walk(self.w11_stack.get_visible_child())
        return out

    def w11_select(self, b):
        old = getattr(self, "w11_sel", None)
        if old is not None:
            old.get_style_context().remove_class("sel")
        if self.w11_catch is not None:
            # первая находка поиска подсвечена, но w11_sel она не числится — снимать всегда,
            # иначе после Ctrl+J выделены две строки (21.10.2026, просьба: «как будто выбрано 2 сразу»)
            for r in self.w11_found.get_children():
                r.get_style_context().remove_class("sel")
        self.w11_sel = b
        if b is None:
            return
        b.get_style_context().add_class("sel")
        sw = b.get_ancestor(Gtk.ScrolledWindow)
        if sw is not None:
            a = b.get_allocation()
            p = b.translate_coordinates(sw.get_child(), 0, 0)
            y = p[1] if p else a.y
            adj = sw.get_vadjustment()
            if y < adj.get_value():
                adj.set_value(y)
            elif y + a.height > adj.get_value() + adj.get_page_size():
                adj.set_value(y + a.height - adj.get_page_size())

    def w11_move(self, where):
        """Стрелки и Ctrl+H/J/K/L — по ближайшей кнопке в ту сторону (сетка и списки)."""
        items = self.w11_items()
        if not items:
            return
        cur = self.w11_sel
        if cur is None and self.w11_first is not None:
            cur = items[0]                   # с первой находки поиска
        if cur not in items:
            self.w11_select(items[0] if where in ("down", "right") else items[-1])
            return

        def center(w):
            p = w.translate_coordinates(self, 0, 0) or (0, 0)
            a = w.get_allocation()
            return p[0] + a.width / 2, p[1] + a.height / 2
        cx, cy = center(cur)
        best, bd = None, None
        for w in items:
            if w is cur:
                continue
            x, y = center(w)
            dx, dy = x - cx, y - cy
            ahead, side = {"down": (dy, dx), "up": (-dy, dx),
                           "right": (dx, dy), "left": (-dx, dy)}[where]
            if ahead <= 2:
                continue
            d = ahead + 3 * abs(side)
            if bd is None or d < bd:
                best, bd = w, d
        if best is not None:
            self.w11_select(best)

    def w11_key(self, e):
        ctrl = bool(e.state & Gdk.ModifierType.CONTROL_MASK)
        where = self.NAV_CTRL.get(e.keyval) if ctrl else self.NAV_ARROWS.get(e.keyval)
        if where:
            if not ctrl and where in ("left", "right") and self.w11_sel is None \
                    and self.w11_search.get_text():
                return False
            self.w11_move(where)
            return True
        if e.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.w11_enter()
            return True
        if e.keyval == Gdk.KEY_Escape:
            if self.w11_search.get_text():
                self.w11_search.set_text("")
            elif self.w11_stack.get_visible_child_name() != "home":
                self.w11_page("home")
            else:
                self.quit()
            return True
        if not self.w11_search.has_focus() and e.string and e.string.isprintable():
            self.w11_search.grab_focus()
        return False

    # ── действия ──────────────────────────────────────────────────────────
    def app_menu(self, a, e):
        ids = [x.get_id() for x in pinned()]
        m = Gtk.Menu()
        mi = Gtk.MenuItem(label="Открепить от меню" if a.get_id() in ids else "Закрепить в меню")

        def toggle(_m):
            new = [i for i in ids if i != a.get_id()] if a.get_id() in ids else ids + [a.get_id()]
            set_pinned(new)
            self.search.set_text("")
            self.refill()
        mi.connect("activate", toggle)
        m.append(mi)
        # и на панель задач, как в Windows 10 — закрепы нижней панели в стопке (xpbar-pins.json)
        app = taskbar_app_id(a)
        conn = self.w11_out() or ""
        bar_pins = taskbar_pins()["pins"].get(conn) or []
        mt = Gtk.MenuItem(label="Открепить от панели задач" if app in bar_pins
                          else "Закрепить на панели задач")
        mt.connect("activate", lambda _m: taskbar_pin_toggle(app, conn))
        m.append(mt)
        m.show_all()
        m.attach_to_widget(self, None)
        m.popup_at_pointer(e)
        return True

    @staticmethod
    def click_sound():
        try:
            import ui_sound
            ui_sound.play("click")
        except Exception:
            pass

    def launch(self, a):
        self.click_sound()
        launch_app(a)
        self.quit()

    def launch_cmd(self, *cmd):
        self.click_sound()
        launch_log("команда: %s" % " ".join(cmd))
        spawn_clean(*cmd)
        self.quit()

    # ── клавиатура: стрелки и Ctrl+H/J/K/L (02.10.2026) ───────────────────
    # Просьба: «когда открываешь Пуск — перемещение по стрелкам и по ctrl+j/k/h/l».
    # Фокус ввода остаётся в строке поиска (чтобы можно было сразу печатать), поэтому
    # «выделение» своё — класс sel на кнопке. Колонки: left (список и «Все программы»),
    # right, c1 (папки «Всех программ»), c2 (программы папки).
    def nav_items(self, col):
        def buttons(w, out):
            if isinstance(w, Gtk.Button):
                out.append(w)
            elif isinstance(w, Gtk.Container):
                w.forall(lambda c: buttons(c, out))
            return out
        if col == "left":
            return buttons(self.apps_box, []) + [self.allb]
        if col == "right":
            return buttons(self.right_col, [])
        ev = self.casc[0 if col == "c1" else 1]
        return buttons(ev.get_child(), []) if ev.get_visible() else []

    def nav_set(self, col, idx):
        items = self.nav_items(col)
        if not items:
            return
        idx = max(0, min(len(items) - 1, idx))
        for c in ("left", "right", "c1", "c2"):          # выделение — одно на всё меню
            for b in self.nav_items(c):
                if not (c == "c1" and col == "c2" and b is getattr(self, "nav_parent", None)):
                    b.get_style_context().remove_class("sel")
        b = items[idx]
        b.get_style_context().add_class("sel")
        self.nav = (col, idx)
        sw = b.get_ancestor(Gtk.ScrolledWindow)          # длинный список — докрутить до строки
        if sw is not None:
            adj, a = sw.get_vadjustment(), b.get_allocation()
            if a.y < adj.get_value():
                adj.set_value(a.y)
            elif a.y + a.height > adj.get_value() + adj.get_page_size():
                adj.set_value(a.y + a.height - adj.get_page_size())

    def nav_move(self, where):
        nav = getattr(self, "nav", None)
        if nav is None:
            # первое нажатие: вниз/вверх — с начала/конца списка; вправо — в правую колонку
            if where in ("down", "up"):
                items = self.nav_items("left")
                start = 1 if (where == "down" and self.first is not None and len(items) > 2) else 0
                self.nav_set("left", start if where == "down" else len(items) - 1)
            elif where == "right":
                self.nav_set("right", 0)
            return
        col, idx = nav
        items = self.nav_items(col)
        if where in ("down", "up"):
            self.nav_set(col, (idx + (1 if where == "down" else -1)) % max(1, len(items)))
        elif where == "right":
            if col == "left" and items and items[idx] is self.allb:
                self.cascade_open()
                self.nav_set("c1", 0)
            elif col == "left":
                self.nav_set("right", idx)
            elif col == "c1" and items:
                self.nav_parent = items[idx]
                items[idx].clicked()                     # раскрыть папку
                self.nav_set("c2", 0)
        elif where == "left":
            if col == "c2":
                self.casc[1].hide()
                self.casc_cat = None
                c1 = self.nav_items("c1")
                p = getattr(self, "nav_parent", None)
                self.nav_set("c1", c1.index(p) if p in c1 else 0)
            elif col == "c1":
                self.cascade_close()
                self.nav_set("left", len(self.nav_items("left")) - 1)
            elif col == "right":
                self.nav_set("left", idx)

    def nav_activate(self):
        nav = getattr(self, "nav", None)
        if nav is None:
            return False
        items = self.nav_items(nav[0])
        if not items:
            return False
        b = items[min(nav[1], len(items) - 1)]
        if nav[0] == "c1" or b is self.allb:             # папка и «Все программы» — раскрыть
            self.nav_move("right")
        else:
            b.clicked()
        return True

    NAV_CTRL = {Gdk.KEY_j: "down", Gdk.KEY_k: "up", Gdk.KEY_h: "left", Gdk.KEY_l: "right",
                Gdk.KEY_J: "down", Gdk.KEY_K: "up", Gdk.KEY_H: "left", Gdk.KEY_L: "right",
                # те же клавиши на русской раскладке
                Gdk.KEY_Cyrillic_o: "down", Gdk.KEY_Cyrillic_el: "up",
                Gdk.KEY_Cyrillic_er: "left", Gdk.KEY_Cyrillic_de: "right",
                Gdk.KEY_Cyrillic_O: "down", Gdk.KEY_Cyrillic_EL: "up",
                Gdk.KEY_Cyrillic_ER: "left", Gdk.KEY_Cyrillic_DE: "right"}
    NAV_ARROWS = {Gdk.KEY_Down: "down", Gdk.KEY_Up: "up", Gdk.KEY_Left: "left", Gdk.KEY_Right: "right"}

    def on_key(self, _w, e):
        if self.w11_on:
            return self.w11_key(e)
        ctrl = bool(e.state & Gdk.ModifierType.CONTROL_MASK)
        where = self.NAV_CTRL.get(e.keyval) if ctrl else self.NAV_ARROWS.get(e.keyval)
        if where:
            # ← → без выделения и с текстом в поиске — двигают курсор в строке, как обычно
            if not ctrl and where in ("left", "right") and getattr(self, "nav", None) is None \
                    and self.search.get_text():
                return False
            self.nav_move(where)
            return True
        if e.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self.nav_activate():
            return True
        if e.keyval == Gdk.KEY_Escape:
            if self.casc[0].get_visible():       # сперва закрыть «Все программы»
                self.cascade_close()
            elif self.search.get_text():
                self.search.set_text("")
            else:
                self.quit()
            return True
        if not self.search.has_focus() and e.string and e.string.isprintable():
            self.search.grab_focus()
        return False

    def quit(self):
        if self.on_close is None:
            bye()
        if not self.get_visible():
            return
        self.hide()
        self.on_close()
        # Частые программы и закреплённые — обновить в простое, пока меню спрятано:
        # к следующему открытию список готов.
        GLib.idle_add(lambda: self.refill() and False)

    def refill(self):
        self.fill_apps()
        if self.w11_catch is not None:
            self.w11_fill()
        return False


def monitor_for(connector):
    display = Gdk.Display.get_default()
    outs = niri_json("outputs") or {}
    model = (outs.get(connector) or {}).get("model") or ""
    for i in range(display.get_n_monitors()):
        m = display.get_monitor(i)
        if connector and (m.get_model() or "") == model:
            return m
    return None


def load_css():
    """CSS меню в цветах обоев на весь экран; вернуть провайдер (чтобы снять при
    смене обоев)."""
    import xpbar_colors
    c = xpbar_colors.colors()
    c.update(font=FONT, nerd=NERD,
             left_bg=xpbar_colors.mix(c["base"], c["primary"], 0.07),
             right_bg=xpbar_colors.mix(c["base"], c["primary"], 0.17),
             frame=xpbar_colors.mix(c["base"], c["primary"], 0.55),
             line=xpbar_colors.mix(c["base"], c["primary"], 0.30),
             hover=xpbar_colors.mix(c["base"], c["primary"], 0.55),
             on_hover=c["on_primary"] if False else "#ffffff",
             err_dark=xpbar_colors.mix(c["error"], "#000000", 0.45))
    # поиск в Skeet — тёмно-синий, как был (22.10.2026: «не нравится что поиск сероватый…
    # более темным, но ближе к темно синему»): base обоев, притемнённый на 20 %
    sk = dict(skeet_colors(c), search=xpbar_colors.mix(c["base"], "#000000", 0.20),
              search_line=c["line"], sel_bg=xpbar_colors.mix(c["base"], "#000000", 0.50))
    css = CSS % c + W11_CSS % c + W11_SKEET_CSS % sk
    look = menu_look()
    if look == "skeet":
        css += SKEET_CSS % skeet_colors(c)
    elif look == "beta":
        b = beta_colors(c)
        css += BETA_CSS % b
        css += "".join(".menu-box label.side-glyph.t%d { background-color: %s; }\n" % (i, col)
                       for i, col in enumerate(b["tiles"]))
    prov = Gtk.CssProvider()
    prov.load_from_data(css.encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    return prov


def cli(args):
    """look get|default|skeet|beta, button get|default|square — для Настроек."""
    what = args[0]
    path, allowed = (LOOK_FILE, LOOKS) if what == "look" else (BUTTON_FILE, BUTTONS)
    if what == "button":
        import start_glyphs
        allowed = tuple(k for k, _ in start_glyphs.choices())
    val = args[1] if len(args) > 1 else "get"
    if val == "get":
        print(read_choice(path, allowed))
        return 0
    if val not in allowed:
        print("start_menu.py %s get|%s" % (what, "|".join(allowed)), file=sys.stderr)
        return 2
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(val + "\n")
    os.replace(tmp, path)            # xpbar.py следит за файлом и применяет сам
    print(val)
    return 0


def main():
    """Отдельным процессом — запасной путь, если xpbar.py не запущен."""
    if sys.argv[1:2] in (["look"], ["button"]):
        sys.exit(cli(sys.argv[1:]))
    popup_theme.single_instance(__file__)
    load_css()
    conn = sys.argv[1] if len(sys.argv) > 1 else (niri_json("focused-output") or {}).get("name", "")
    with open(OPEN_FLAG, "w") as f:
        f.write(conn + "\n")
    StartMenu(monitor_for(conn))
    watch_workspaces()
    import signal
    signal.signal(signal.SIGTERM, bye)
    Gtk.main()


if __name__ == "__main__":
    main()
