#!/usr/bin/env python3
"""Меню рабочего стола в духе Windows XP: правый щелчок по пустым обоям. 30.09.2026.

    desktop_menu.py               запустить (один экземпляр; второй тихо выходит;
                                  при флаге «выключено» сразу выходит)
    desktop_menu.py --dry-run     то же, но пункты меню только печатают команду
    desktop_menu.py on|off        включить / выключить (флаг ~/.config/hypr/state/desktop-menu-off;
                                  off гасит работающий экземпляр, on поднимает его)
    desktop_menu.py status        включено ли, работает ли, сколько поверхностей у niri
    desktop_menu.py state         on|off одним словом (для переключателя в Настройках)
    desktop_menu.py test          все действия всухую: что именно было бы запущено
    desktop_menu.py --render PNG  нарисовать меню со всеми подменю в файл, без показа на экране

Как ловится щелчок. Обои рисует awww-daemon в слое BACKGROUND, и ввода у его
поверхности нет (пустая input region). Поэтому здесь на каждом мониторе висит
своя прозрачная поверхность GTK LayerShell (namespace «jarvis-desktop»), тоже в
BACKGROUND, растянутая на весь монитор. Окна и слои TOP/OVERLAY (бар, док, горячие
углы) лежат выше и забирают щелчки себе, так что до неё доходят только щелчки
по пустому столу. Exclusive zone 0: поверхность уступает место бару и не
заходит под него.

Что проверено по исходникам niri (main, 30.09.2026), а не догадки:
* в обзоре (Mod+G) слои BACKGROUND/BOTTOM ввода не получают — обзор работает как
  раньше (niri.rs, contents_under: «in the overview background and bottom layers
  don't receive input»);
* щелчок по пустому месту без окна niri и раньше обрабатывал только как «фокус на
  этот монитор» (focus_output) — это остаётся, окно под щелчком не ищется;
* всплывающее меню (xdg_popup) от слоя BACKGROUND niri разрешает, запрещает только
  слоям с place-within-backdrop (это фон обзора awww-daemon-backdrop, не наш).
  Клавиатуры у поверхности нет (keyboard NONE), поэтому меню — мышью; закрывается
  щелчком мимо. Стрелки и Escape в нём не работают: niri не даёт клавиатурный
  захват поверхности, которая не может получить фокус (так же живут меню waybar).

Курсор над пустым столом теперь рисует GTK этого процесса, а тема курсора меняется
вместе с обоями (Jarvis-Cursor-A/B, см. cursor_colors.py). Чтобы стол не остался
со старым курсором, процесс перезапускает сам себя, когда меняется выбранная тема.
"""
import datetime
import fcntl
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

HOME = os.path.expanduser("~")
NAMESPACE = "jarvis-desktop"
FLAG = os.path.expanduser("~/.config/hypr/state/desktop-menu-off")
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-desktop-menu.lock")
SHELL_STATE = os.path.expanduser("~/.config/niri/state/shell")
# Меняются при смене курсора (A/B при каждой смене обоев) — повод перезапуститься.
CURSOR_FILES = [os.path.expanduser("~/.cache/matugen/niri-cursor.kdl"),
                os.path.expanduser("~/.config/hypr/state/cursor-theme")]
POLL_S = 3

FONT = "JetBrainsMono Nerd Font"
ICON_FONT = "JetBrainsMono Nerd Font"
QUICK_N = 5            # значков в верхнем ряду
QUICK_MIN_S = 60       # меньше минуты за неделю — не «часто используемая»
QUICK_PX = 24          # размер значка (Papirus рисует 16/24/32/48 — чёткие); 32 → 24 «чуть меньше» (14.10.2026)

KITTY = [os.path.expanduser("~/.config/hypr/scripts/kitty_shared.sh")]
SETTINGS = ["python3", os.path.join(HERE, "settings_app.py")]
WIDGETS = os.path.join(HERE, "desktop_widgets.py")


def glib_signal_add(prio, signum, handler):
    """Сигнал в главный цикл GLib. GLib.unix_signal_add устарел (PyGObject 3.52+) и однажды
    исчезнет — тогда программа перестала бы запускаться (08.10.2026). Сначала замена
    GLibUnix.signal_add, без неё — старое имя, без обоих — обычный signal.signal."""
    from gi.repository import GLib
    try:
        from gi.repository import GLibUnix
        return GLibUnix.signal_add(prio, signum, handler)
    except (ImportError, AttributeError):
        pass
    try:
        return GLib.unix_signal_add(prio, signum, handler)
    except AttributeError:
        import signal as _signal
        _signal.signal(signum, lambda *_a: GLib.idle_add(lambda: handler() and False))


def desktop_dir():
    """~/Desktop по xdg-user-dirs (у пользователя — ~/Desktop, пока не существует)."""
    try:
        d = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True,
                           timeout=1).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        d = ""
    if not d or os.path.realpath(d) == os.path.realpath(HOME):
        d = os.path.join(HOME, "Desktop")
    return d


def user_dir(kind, fallback):
    try:
        d = subprocess.run(["xdg-user-dir", kind], capture_output=True, text=True,
                           timeout=1).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        d = ""
    return d if d and d != HOME else os.path.join(HOME, fallback)


def shell_is_mine():
    """Своя оболочка (waybar), а не Noctalia: только тогда «Обновить» зовёт barfix."""
    try:
        return open(SHELL_STATE).read().strip() in ("", "mine")
    except OSError:
        return True


def unique_path(folder, stem, ext=""):
    """«Новая папка», «Новая папка (2)», … — как в Проводнике."""
    p = os.path.join(folder, stem + ext)
    n = 2
    while os.path.lexists(p):
        p = os.path.join(folder, "%s (%d)%s" % (stem, n, ext))
        n += 1
    return p


# ── действия ─────────────────────────────────────────────────────────────────
# Каждое действие — список команд (argv). Сложные («создать папку») — функция,
# которая что-то делает на диске и возвращает команду, открывающую результат.

def _create_folder(dry):
    d = desktop_dir()
    p = unique_path(d, "Новая папка")
    if dry:
        return [["mkdir", "-p", p], ["dolphin", "--select", p]]
    os.makedirs(p)
    return [["dolphin", "--select", p]]


def _create_text(dry):
    d = desktop_dir()
    p = unique_path(d, "Новый файл", ".txt")
    if dry:
        return [["mkdir", "-p", d], ["touch", p], ["xdg-open", p]]
    os.makedirs(d, exist_ok=True)
    open(p, "x").close()
    # text/plain у пользователя открывает Mousepad; каталоги xdg-open отдал бы kitty-open,
    # поэтому папки открываются dolphin'ом напрямую.
    return [["xdg-open", p]]


def _open_dir(path, create=False):
    def act(dry):
        cmds = []
        if create and not os.path.isdir(path):
            if dry:
                cmds.append(["mkdir", "-p", path])
            else:
                os.makedirs(path, exist_ok=True)
        return cmds + [["dolphin", path]]
    return act


ACTIONS = {
    "new-folder": _create_folder,
    "new-text": _create_text,
    "open-home": _open_dir(HOME),
    "open-desktop": None,          # заполняется в main: нужен xdg-user-dir
    "open-downloads": None,
    "open-documents": None,
    "open-pictures": None,
    "open-videos": None,
    # «Обновить»: бар (только своя оболочка) + виджеты на обоях — их код грузится один раз
    # при старте сторожа (19.10.2026, просьба: «как я без тебя буду перезапускать виджеты?»)
    "refresh": lambda dry: ([["barfix"]] if shell_is_mine() else []) +
                           [["python3", WIDGETS, "restart"]],
    "wallpaper": [["python3", os.path.join(HERE, "wallpaper_picker.py")]],
    "display": [SETTINGS + ["screen"]],
    "look": [SETTINGS + ["look"]],
    "terminal": [KITTY + ["--directory", HOME]],
    "btop": [KITTY + ["--title", "btop", "btop"]],
    "screentime": [["python3", os.path.join(HERE, "screentime.py")]],
    "control-center": [["python3", os.path.join(HERE, "control_center.py"), "--center"]],
    "screenshot": [["niri", "msg", "action", "screenshot"]],
    "overview": [["niri", "msg", "action", "toggle-overview"]],
    "menu-off": [["python3", os.path.abspath(__file__), "off"]],
    "settings": [SETTINGS],
    "launcher": [["python3", os.path.join(HERE, "app_launcher.py")]],    # Super+X
    # 02.10.2026: таймер, запись видео и виджеты — по просьбе пользователя
    "timer": [[os.path.join(HERE, "timer_ask.sh")]],
    "record-video": [["env", "REC_TOP=Video", os.path.join(HERE, "rec_area.sh")]],
    "widgets-edit": [["python3", WIDGETS, "edit"]],
}

# Где щёлкнули правой кнопкой (точка на общем полотне мониторов) — новый виджет
# встаёт заголовком под курсор. Пишет on_press.
LAST_CLICK = [None]


def _widget(kind):
    def act(dry):
        if kind == "timer":                  # спросит название и время
            return [["python3", WIDGETS, "timer", "ask=1"] +
                    (["at=%d,%d" % LAST_CLICK[0]] if LAST_CLICK[0] else [])]
        cmd = ["python3", WIDGETS, "add", kind]
        if LAST_CLICK[0]:
            cmd.append("at=%d,%d" % LAST_CLICK[0])
        if kind == "banner":
            cmd.append("ask=1")              # спросит текст надписи
        return [cmd]
    return act


def _preset(label, span, url=""):
    """Готовый отсчёт: виджет-таймер с названием и временем (02.10.2026: hh — 4 часа). Таймер с таким названием уже есть — он перезапускается."""
    def act(dry):
        return [["python3", WIDGETS, "timer", label, span] + (["url=" + url] if url else []) +
                (["at=%d,%d" % LAST_CLICK[0]] if LAST_CLICK[0] else [])]
    return act


# hh — раз в 4 часа резюме на hh.kz можно поднять в поиске; автоматом нельзя (API для
# соискателей закрыт 15.12.2025), поэтому таймер зовёт на страницу «Мои резюме».
ACTIONS["timer-hh"] = _preset("hh", "4h", "https://hh.kz/applicant/resumes")

# (тип, значок, подпись) — подписи как в полосе заголовка виджета
WIDGET_KINDS = [
    ("clock", "\U000f0954", "clock.exe — часы"),
    ("date", "\U000f00ed", "today.exe — день и дата"),
    ("calendar", "\U000f00f0", "calendar.exe — месяц"),
    ("weather", "\U000f0590", "weather.exe — погода"),
    ("sysmon", "\U000f035b", "sysmon.exe — процессор, память, сеть"),
    ("player", "\U000f075a", "player.exe — что играет"),
    ("playermini", "\U000f040a", "nowplaying.exe — плеер одной строкой"),
    ("cava", "\U000f0f74", "visualizer.exe — эквалайзер"),
    ("banner", "\U000f0284", "banner.exe — надпись…"),
    ("pomo", "\U000f051b", "pomodoro.exe — помодоро"),
    ("screentime", "\U000f13ab", "screentime.exe — экранное время"),
    ("screenweek", "\U000f13ab", "screenweek.exe — экранное время за неделю"),
    ("screenmonth", "\U000f13ab", "screenmonth.exe — экранное время за месяц"),
    ("appmem", "\U000f035b", "ram.exe — память по программам"),
    ("appcpu", "\U000f0ee0", "cpu.exe — процессор по программам"),
    ("sysinfo", "\U000f08c7", "fetch.exe — fastfetch"),
    ("matrix", "\U000f0e2b", "matrix.exe — цифровой дождь"),
    ("sprite", "\U000f0531", "octopus.exe — осьминог"),
    ("miku", "\U000f0004", "miku.exe — Мику"),
    ("fire", "\U000f0238", "fire.exe — огонь"),
    ("life", "\U000f0493", "life.exe — «Жизнь»"),
]
for _k, _i, _t in WIDGET_KINDS:
    ACTIONS["widget-" + _k] = _widget(_k)
ACTIONS["widget-timer"] = _widget("timer")     # пункт вынесен в основной список меню
# секундомер — тот же виджет-таймер без срока (05.10.2026)
ACTIONS["widget-stopwatch"] = lambda dry: [["python3", WIDGETS, "timer", "секундомер"] +
                                           (["at=%d,%d" % LAST_CLICK[0]] if LAST_CLICK[0] else [])]


def _fill_dirs():
    ACTIONS["open-desktop"] = _open_dir(desktop_dir(), create=True)
    ACTIONS["open-downloads"] = _open_dir(user_dir("DOWNLOAD", "Downloads"))
    ACTIONS["open-documents"] = _open_dir(user_dir("DOCUMENTS", "Documents"))
    ACTIONS["open-pictures"] = _open_dir(user_dir("PICTURES", "Pictures"))
    ACTIONS["open-videos"] = _open_dir(user_dir("VIDEOS", "Videos"))


def spawn(cmd, reap=None):
    """Запустить отдельно от меню; reap(pid) — чтобы долгоживущий процесс не копил зомби."""
    try:
        p = subprocess.Popen(cmd, cwd=HOME, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError as e:
        print("desktop_menu: %s: %s" % (cmd[0], e), file=sys.stderr, flush=True)
        return
    if reap:
        reap(p.pid)


def run_action(key, dry=False, reap=None):
    """Выполнить действие; возвращает список команд (для dry-run и проверки)."""
    act = ACTIONS[key]
    try:
        cmds = act(dry) if callable(act) else act
    except OSError as e:
        print("desktop_menu: %s: %s" % (key, e), file=sys.stderr, flush=True)
        return []
    for cmd in cmds:
        if dry:
            print("desktop_menu: [dry-run] %s → %s" % (key, " ".join(cmd)), flush=True)
        else:
            spawn(cmd, reap)
    return cmds


# ── частые программы (верхний ряд) ───────────────────────────────────────────

# Не «программы, которые запускают»: окна-служебки и то, что уже есть в меню.
QUICK_SKIP = {"com.jarvis.settings", "jarvis-pin", "unknown", "gamescope"}
QUICK_FALLBACK = ["kitty", "org.kde.dolphin", "org.telegram.desktop", "zen"]
# Своя команда вместо .desktop: kitty — окно общей копии (память kitty-single-instance).
QUICK_CMD = {"kitty": KITTY}


def quick_apps(n=QUICK_N):
    """[(app_id, имя, Gio.Icon, DesktopAppInfo)] — самые долгие за 7 дней по «Экранному времени»."""
    import screentime
    try:
        week = screentime.sum_apps(screentime.load_day(d)["apps"] for d in screentime.week_dates())
        ranked = [a for a, s in screentime.ranked(week) if s >= QUICK_MIN_S]
    except Exception as e:           # данных нет или файл битый — только запасные
        print("desktop_menu: экранное время: %s" % e, file=sys.stderr)
        ranked = []
    out, seen = [], set()
    for aid in ranked + QUICK_FALLBACK:
        if len(out) >= n:
            break
        if aid in QUICK_SKIP or aid.startswith("xdg-desktop-portal") or aid.startswith("steam_app_"):
            continue
        try:
            info = screentime._desktop_for(aid)
        except Exception:
            info = None
        if info is None or info.get_nodisplay() or info.get_id() in seen:
            continue
        seen.add(info.get_id())
        name = screentime.NAMES.get(aid) or info.get_string("Name") or aid
        out.append((aid, name, info.get_icon(), info))
    return out


def launch_quick(aid, info, dry=False, reap=None):
    cmd = QUICK_CMD.get(aid) or ["gio", "launch", info.get_filename()]
    if dry:
        print("desktop_menu: [dry-run] quick %s → %s" % (aid, " ".join(cmd)), flush=True)
    else:
        spawn(cmd, reap)
    return cmd


# ── содержимое меню ──────────────────────────────────────────────────────────
# (значок Nerd Font, подпись, действие или подменю, подсказка клавиш справа)
# Значки MDI из JetBrainsMono Nerd Font (наличие каждого проверено по cmap).
SUB_NEW = [
    ("\U000f0257", "Папку", "new-folder", ""),
    ("\U000f0752", "Текстовый файл", "new-text", ""),
]
SUB_OPEN = [
    ("\U000f10b5", "Домашняя папка", "open-home", ""),
    ("\U000f024b", "Рабочий стол", "open-desktop", ""),
    ("\U000f024d", "Загрузки", "open-downloads", ""),
    ("\U000f0219", "Документы", "open-documents", ""),
    ("\U000f024f", "Изображения", "open-pictures", ""),
    ("\U000f19fa", "Видео", "open-videos", ""),
]
SUB_MORE = [
    ("\U000f056e", "Центр управления", "control-center", ""),
    ("\U000f0489", "Снимок области", "screenshot", "Print"),
    ("\U000f0570", "Обзор столов", "overview", "Super+G"),
    ("\U000f00e3", "Внешний вид", "look", ""),
    # 14.10.2026 из основного списка — «Записать видео положи в пункт Ещё. Экранное время тоже»
    ("\U000f0567", "Записать видео", "record-video", ""),
    ("\U000f13ab", "Экранное время", "screentime", ""),
    # «Убрать это меню» убран (05.10.2026, просьба: «случайно нажал — убери кнопку»);
    # выключить меню можно в Настройках или `desktop_menu.py off`.
]
SUB_WIDGET = [(i, t, "widget-" + k, "") for k, i, t in WIDGET_KINDS]
# Готовые отсчёты — таймеры-виджеты с названием и сроком (02.10.2026).
SUB_COUNT = [
    ("\U000f051b", "hh", "timer-hh", ""),
]
# «Управление виджетами» (02.10.2026; переделано 05.10.2026). Утром 05.10 пункты
# работали только на стол, где открыли меню, — пользователь передумал: «как мне понять, на каком
# столе восстанавливать? Сделай как раньше — на все виджеты»; и «пресетов несколько, легко
# переключаться». Теперь: «Сохранить пресет…» — окошко с названием (rofi, как у «Создать
# таймер…»), снимок ВСЕХ виджетов; «Загрузить пресет ▸» — список имён, строится при каждом
# открытии меню; «Удалить все виджеты» — все (копия в «отмену»).
def _sub_presets():
    """Подменю «Загрузить пресет»: имена пресетов (свежие сверху) + «Как было до этого»."""
    try:
        names = subprocess.run(["python3", WIDGETS, "preset", "list"], capture_output=True,
                               text=True, timeout=3).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        names = []
    out = []
    try:
        cur = open(os.path.join(_STATE, "widget-preset-current")).read().strip()
    except (OSError, NameError):
        cur = ""
    for n in [x for x in names if x.strip()]:
        key = "preset-load:" + n
        ACTIONS[key] = (lambda name: lambda dry: [["python3", WIDGETS, "preset", "load", name]])(n)
        # текущий (state/widget-preset-current) — галочкой (05.10.2026)
        out.append(("\U000f012c" if n == cur else "\U000f0570", n, key, "сейчас" if n == cur else ""))
    if not out:
        out.append(("\U000f0450", "Пресетов пока нет", "noop", ""))
    if os.path.exists(os.path.join(_STATE, "desktop-widgets-undo.json")):
        out += [None, ("\U000f054c", "Как было до этого", "widgets-undo", "")]
    return out


def _sub_presets_del():
    """Подменю «Удалить пресет» (05.10.2026, просьба: «добавь возможность удалять пресеты»).
    Файл не стирается, а уходит в widget-presets/.deleted — промах можно вернуть руками."""
    try:
        names = subprocess.run(["python3", WIDGETS, "preset", "list"], capture_output=True,
                               text=True, timeout=3).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        names = []
    out = []
    for n in [x for x in names if x.strip()]:
        key = "preset-del:" + n
        # защита от промаха (05.10.2026, просьба: «подтверждение — отдельное окно по центру»):
        # delete-ask показывает окно Preset.exe «Удалить пресет «…»?», удаляет только «Удалить»
        ACTIONS[key] = (lambda name: lambda dry: [["python3", WIDGETS, "preset", "delete-ask", name]])(n)
        out.append(("\U000f01b4", n, key, ""))
    return out or [("\U000f0450", "Пресетов пока нет", "noop", "")]


SUB_CONTROL = [
    ("\U000f0193", "Сохранить пресет…", "widgets-save", ""),
    ("\U000f0450", "Загрузить пресет", _sub_presets, ""),
    ("\U000f01b4", "Удалить пресет", _sub_presets_del, ""),
    None,
    ("\U000f01b4", "Удалить все виджеты", "widgets-clear", ""),
]
ACTIONS["widgets-save"] = [["python3", WIDGETS, "preset", "ask"]]
ACTIONS["widgets-undo"] = [["python3", WIDGETS, "preset", "undo"]]
ACTIONS["widgets-clear"] = [["python3", WIDGETS, "clear"]]
ACTIONS["noop"] = []
_STATE = os.path.expanduser("~/.config/hypr/state")
# пункт показывается, только пока условие истинно
VISIBLE = {}
MENU = [
    ("\U000f0704", "Создать", SUB_NEW, ""),
    ("\U000f0770", "Открыть", SUB_OPEN, ""),
    ("\U000f0450", "Обновить", "refresh", ""),
    None,
    ("\U000f03d8", "Обои и тема", "wallpaper", "Super+W"),
    None,
    ("\U000f018d", "Терминал", "terminal", ""),
    ("\U000f012a", "Системный монитор", "btop", ""),
    None,
    # «Создать таймер…» — в основном списке, а не в «Создать виджет»: пользователь пользуется им
    # часто, должен быть под рукой (02.10.2026). Спрашивает название и время.
    ("\U000f051b", "Создать таймер…", "widget-timer", ""),
    ("\U000f0e17", "Создать секундомер", "widget-stopwatch", ""),
    ("\U000f051b", "Задать отсчёт hh", "timer-hh", ""),       # одной кнопкой, без подменю (05.10.2026)
    None,
    ("\U000f0e2b", "Создать виджет", SUB_WIDGET, ""),
    ("\U000f03eb", "Редактировать виджеты", "widgets-edit", ""),
    ("\U000f0493", "Управление виджетами", SUB_CONTROL, ""),
    None,
    ("\U000f01d8", "Ещё", SUB_MORE, ""),
    ("\U000f003b", "Системное меню", "launcher", "Super+X"),     # 14.10.2026
    ("\U000f0493", "Настройки", "settings", "Super+/"),
]

CSS = """
/* Окно-подложка всплывающего меню прозрачное — иначе за скруглёнными углами
   рамки видны квадратные углы окна. */
window.popup, window.popup.background, window.popup decoration {
    background-color: transparent; background-image: none;
    box-shadow: none; border: none;
}
menu.jd {
    background-color: %(surface)s; color: %(on_surface)s;
    border: 2px solid %(primary)s; border-radius: 10px; padding: 3px;
    /* Тёмный контур в пиксель, как у .popup-box: на светлых обоях светлая
       рамка акцента иначе сливается с фоном. */
    margin: 2px; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
    font-family: '%(font)s', sans-serif; font-size: 14px; font-weight: normal;
}
/* 04.10.2026, просьба: «чуть компактнее» — было 16px, отступы 4px, высота 24px.
   Бэкап desktop_menu.py.bak-compact-classic. 14.10.2026: «компактнее по горизонтали» —
   поля пункта 5/8 → 4/5, значок 20 → 16, отступ клавиш 20 → 10, стрелка 14+10 → 12+4. */
menu.jd menuitem {
    padding: 2px 5px 2px 4px; border-radius: 6px; min-height: 20px;
    color: %(on_surface)s;
    /* рамка — такая же, как при наведении: тема даёт пункту невидимую рамку 1 px,
       а у наведённого её не было — пункт сжимался на 2 px и меню дёргалось (02.10.2026) */
    border: none; box-shadow: none; outline: none;
}
/* Тема GTK рисует у наведённого пункта ещё и обводку — убрана, остаётся заливка. */
menu.jd menuitem:hover {
    background-color: %(surface_high)s; color: %(primary)s;
    border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover label.mi-accel { color: %(primary)s; }
menu.jd menuitem:disabled label { color: %(on_surface_variant)s; opacity: 0.55; }
menu.jd menuitem.quick { padding: 4px 3px; border-radius: 8px; }
menu.jd menuitem arrow {
    min-width: 12px; min-height: 12px; margin-left: 4px;
    -gtk-icon-source: -gtk-icontheme("pan-end-symbolic");
    color: %(on_surface_variant)s;
}
menu.jd menuitem:hover arrow { color: %(primary)s; }
menu.jd separator {
    background-color: %(outline_variant)s; min-height: 1px; margin: 3px 8px;
}
menu.jd separator.quick-sep { background-color: %(primary)s; opacity: 0.45; margin: 3px 4px 4px 4px; }
label.mi-icon {
    font-family: '%(icon_font)s'; font-size: 16px; min-width: 16px;
    color: %(primary)s;
}
label.mi-title { font-family: '%(font)s', sans-serif; font-size: 14px; }
label.mi-accel {
    font-family: '%(font)s', sans-serif; font-size: 14px;
    color: %(on_surface_variant)s; margin-left: 10px;
}
tooltip {
    background-color: %(surface)s; color: %(on_surface)s;
    border: 1px solid %(primary)s; border-radius: 8px;
    padding: 2px;
}
tooltip label {
    font-family: '%(font)s', sans-serif; font-size: 16px; font-weight: normal;
    padding: 0 3px;
}
"""


# Вид «XP» (01.10.2026, просьба: «компактнее, рамки системные убери, сделай
# собственную в стиле Windows XP, и само меню перерисуй в стиле XP»): прямые углы,
# объёмная кромка в два тона (светлая сверху-слева, тёмная снизу-справа) и тень
# со сдвигом, полоса выделения во всю ширину акцентом, мелкий шрифт 12 px, значки
# 14 px. Цвета — те же тона, что у XP-панели (xpbar_colors), из палитры обоев.
CSS_XP = """
window.popup, window.popup.background, window.popup decoration {
    background-color: transparent; background-image: none;
    box-shadow: none; border: none;
}
menu.jd {
    background-color: %(xp_bg)s; color: %(on_surface)s;
    border: 1px solid %(xp_light)s; border-radius: 0; padding: 2px;
    margin: 1px 4px 4px 1px;
    box-shadow: 0 0 0 1px %(xp_dark)s, 3px 3px 0 0 rgba(0, 0, 0, 0.45);
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
}
menu.jd menuitem {
    padding: 2px 10px 2px 4px; border-radius: 0; min-height: 16px;
    color: %(on_surface)s;
    /* рамка — такая же, как при наведении: тема даёт пункту невидимую рамку 1 px,
       а у наведённого её не было — пункт сжимался на 2 px и меню дёргалось (02.10.2026) */
    border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover {
    background-color: %(xp_sel)s; color: #ffffff;
    border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover label.mi-accel, menu.jd menuitem:hover label.mi-icon { color: #ffffff; }
menu.jd menuitem:disabled label { color: %(on_surface_variant)s; opacity: 0.55; }
menu.jd menuitem.quick { padding: 3px 2px; border-radius: 0; }
menu.jd menuitem arrow {
    min-width: 12px; min-height: 12px; margin-left: 8px;
    -gtk-icon-source: -gtk-icontheme("pan-end-symbolic");
    color: %(on_surface_variant)s;
}
menu.jd menuitem:hover arrow { color: #ffffff; }
menu.jd separator {
    background-color: %(xp_dark)s; min-height: 1px; margin: 2px 2px 3px 2px;
    box-shadow: 0 1px 0 0 %(xp_light)s;
}
menu.jd separator.quick-sep { background-color: %(xp_dark)s; opacity: 1; margin: 2px 2px 3px 2px; }
label.mi-icon {
    font-family: '%(icon_font)s'; font-size: 14px; min-width: 18px;
    color: %(primary)s;
}
label.mi-title { font-family: '%(font)s', sans-serif; font-size: 12px; }
label.mi-accel {
    font-family: '%(font)s', sans-serif; font-size: 12px;
    color: %(on_surface_variant)s; margin-left: 18px;
}
tooltip {
    background-color: %(xp_bg)s; color: %(on_surface)s;
    border: 1px solid %(xp_dark)s; border-radius: 0;
    padding: 2px;
}
tooltip label {
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
    padding: 0 3px;
}
"""
# Вид «Система» (15.10.2026, просьба: «адаптировать под стиль системы (то есть Skeet) и добавить
# ещё одним выбором; назови Система»). Берёт стиль монитора, где щёлкнули (system_style.py).
# Первая версия повторяла каркас XP в цветах Skeet — «чем это отличается от XP?». Переделано:
# skeet — рамка слоями как у gamesense и Настроек (тёмная, светлая, 3 px средняя, светлая,
# тёмная), под ней полоса палитры, без тени со сдвигом; значки серые, выделенный пункт —
# поле светлее, черта акцентом слева, текст акцентом. beta — плоско: рамка 1 px акцентом.
# default — «Обычный» (CSS).
CSS_SKEET = """
window.popup, window.popup.background, window.popup decoration {
    background-color: transparent; background-image: none;
    box-shadow: none; border: none;
}
menu.jd {
    background-color: %(bg)s; color: %(text)s;
    background-image: linear-gradient(to right, %(s0)s, %(s1)s, %(s2)s),
                      linear-gradient(to right, %(s0d)s, %(s1d)s, %(s2d)s)%(dots)s;
    background-size: 100%% 1px, 100%% 1px%(dots_size)s;
    background-position: 0 7px, 0 8px%(dots_pos)s;  /* сразу под рамкой: тени рисуются поверх фона */
    background-repeat: no-repeat, no-repeat%(dots_rep)s;
    /* снаружи светлая кромка line1 — граница видна и на тёмных обоях (15.10) */
    /* 16.10: светлые слои рамки — line1 с акцентом (line1_on), как у окна в фокусе и Programs.exe */
    border: 1px solid %(line1_on)s; border-radius: 0;
    padding: 0 8px; margin: 2px;      /* по вертикали GtkMenu отступ не берёт — см. first/last-child */
    /* GTK кладёт следующую тень поверх предыдущей — от широкой к узкой */
    box-shadow: inset 0 0 0 7px %(line3)s, inset 0 0 0 6px %(line1_on)s,
                inset 0 0 0 5px %(line2)s, inset 0 0 0 2px %(line1_on)s,
                inset 0 0 0 1px %(line3)s;
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
}
menu.jd menuitem {
    padding: 1px 12px 1px 8px; border-radius: 0; min-height: 18px;
    color: %(text)s;
    border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover {
    background-color: %(field_l)s; color: #ffffff;
    border: none; box-shadow: inset 2px 0 %(acc)s; outline: none;
}
/* текст пунктов белый всегда; значки и подсказки клавиш — акцентом всегда (16.10, было только
   при наведении), при наведении светлее */
menu.jd menuitem label.mi-title { color: %(text)s; }
menu.jd menuitem:hover label.mi-title { color: #ffffff; }
menu.jd menuitem:hover label.mi-icon { color: %(acc_l)s; }
menu.jd menuitem:hover label.mi-accel { color: %(acc_l)s; }
menu.jd menuitem:disabled label { color: %(dim)s; opacity: 0.55; }
menu.jd menuitem.quick { padding: 3px 3px; border-radius: 0; margin-top: 10px; }
/* рамка 6 px + полоса: первый пункт подменю и последний пункт — с отступом от рамки */
menu.jd menuitem:first-child { margin-top: 10px; }
menu.jd menuitem:last-child { margin-bottom: 8px; }
menu.jd menuitem.quick:hover { box-shadow: inset 0 -2px %(acc)s; }
menu.jd menuitem arrow {
    min-width: 12px; min-height: 12px; margin-left: 8px;
    -gtk-icon-source: -gtk-icontheme("pan-end-symbolic");
    color: %(dim)s;
}
menu.jd menuitem:hover arrow { color: #ffffff; }
/* разделитель как у групп gamesense: тёмная линия и светлая под ней */
menu.jd separator {
    background-color: %(line3)s; min-height: 1px; margin: 2px 2px 3px 2px;
    box-shadow: 0 1px 0 0 %(gline)s;
}
menu.jd separator.quick-sep { background-color: %(line3)s; opacity: 1; margin: 2px 0 3px 0; }
label.mi-icon {
    font-family: '%(icon_font)s'; font-size: 14px; min-width: 20px;
    color: %(acc)s;
}
label.mi-title { font-family: '%(font)s', sans-serif; font-size: 12px; }
label.mi-accel {
    font-family: '%(font)s', sans-serif; font-size: 12px;
    color: %(acc)s; margin-left: 18px;
}
tooltip {
    background-color: %(bg)s; color: %(text)s;
    border: 1px solid %(line3)s; border-radius: 0;
    box-shadow: inset 0 0 0 1px %(line1)s;
    padding: 2px;
}
tooltip label {
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
    padding: 0 3px;
}
"""
CSS_BETA = """
window.popup, window.popup.background, window.popup decoration {
    background-color: transparent; background-image: none;
    box-shadow: none; border: none;
}
menu.jd {
    background-color: %(bg)s; color: %(text)s;
    border: 1px solid %(frame)s; border-radius: 0; padding: 3px; margin: 2px;
    box-shadow: none;
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
}
menu.jd menuitem {
    padding: 2px 10px 2px 6px; border-radius: 0; min-height: 16px;
    color: %(text)s; border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover {
    background-color: %(sel)s; color: %(sel_text)s;
    border: none; box-shadow: none; outline: none;
}
menu.jd menuitem:hover label { color: %(sel_text)s; }
menu.jd menuitem:disabled label { color: %(dim)s; opacity: 0.55; }
menu.jd menuitem.quick { padding: 3px 2px; border-radius: 0; }
menu.jd menuitem arrow {
    min-width: 12px; min-height: 12px; margin-left: 8px;
    -gtk-icon-source: -gtk-icontheme("pan-end-symbolic");
    color: %(dim)s;
}
menu.jd separator { background-color: %(line)s; min-height: 1px; margin: 3px 0; }
menu.jd separator.quick-sep { background-color: %(line)s; opacity: 1; margin: 3px 0; }
label.mi-icon {
    font-family: '%(icon_font)s'; font-size: 14px; min-width: 18px;
    color: %(acc)s;
}
label.mi-title { font-family: '%(font)s', sans-serif; font-size: 12px; }
label.mi-accel {
    font-family: '%(font)s', sans-serif; font-size: 12px;
    color: %(dim)s; margin-left: 18px;
}
tooltip {
    background-color: %(bg)s; color: %(text)s;
    border: 1px solid %(frame)s; border-radius: 0;
    padding: 2px;
}
tooltip label {
    font-family: '%(font)s', sans-serif; font-size: 12px; font-weight: normal;
    padding: 0 3px;
}
"""
STYLES = ("xp", "classic", "system")
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/desktop-menu-style")
BAR_LOOK = os.path.expanduser("~/.config/waybar/looks/current.jsonc")

# Компактный вид бара (13.10.2026, просьба: «при Вид бара — компакт пусть и меню на ПКМ
# открывается компактным»). Как и у бара, кегли не ужимаются — только вертикальные
# поля пунктов и разделителей. Поверх CSS / CSS_XP.
CSS_COMPACT = """
menu.jd { padding-top: 2px; padding-bottom: 2px; }
menu.jd menuitem { padding-top: 0; padding-bottom: 0; min-height: 16px; }
menu.jd menuitem.quick { padding-top: 1px; padding-bottom: 1px; }
menu.jd separator { margin-top: 1px; margin-bottom: 1px; }
menu.jd separator.quick-sep { margin-top: 1px; margin-bottom: 2px; }
"""


def bar_compact():
    """Вид бара compact / edge-compact (bar_style.py держит ссылку current.jsonc)."""
    try:
        return os.path.basename(os.readlink(BAR_LOOK)) in ("compact.jsonc", "edge-compact.jsonc")
    except OSError:
        return False


def menu_style():
    """xp (по умолчанию), classic — прежний вид с круглой рамкой акцентом, system — по стилю
    монитора (Skeet/Beta; Default → classic)."""
    try:
        v = open(STYLE_FILE).read().strip()
        return v if v in STYLES else "xp"
    except OSError:
        return "xp"


def system_look(point=None):
    """Стиль системы монитора под точкой щелчка (x, y) — skeet | beta | default."""
    import system_style
    out = None
    if point is not None:
        for name, o in (niri_json("outputs") or {}).items():      # niri: {имя: выход}
            lg = (o or {}).get("logical") or {}
            if lg and lg["x"] <= point[0] < lg["x"] + lg["width"] and lg["y"] <= point[1] < lg["y"] + lg["height"]:
                out = name
                break
    if out is None:
        out = (niri_json("focused-output") or {}).get("name", "")
    return system_style.style_of(out)


def skeet_dots(bg, dot):
    """Плитка 4×4 точечного фона gamesense — тот же кэш, что у Настроек (settings_app.skeet_dots)."""
    path = os.path.expanduser("~/.cache/jarvis/skeet-dots-%s-%s.png" % (bg.lstrip("#"), dot.lstrip("#")))
    if os.path.exists(path):
        return path
    try:
        from PIL import Image
        im = Image.new("RGB", (4, 4), bg)
        for xy in ((0, 0), (2, 2)):
            im.putpixel(xy, tuple(int(dot[i:i + 2], 16) for i in (1, 3, 5)))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        im.save(path)
    except Exception:
        return None
    return path


def system_colors(look):
    """(шаблон, цвета) для вида «Система» по стилю монитора или None (Default — «Обычный»)."""
    import rec_style
    if look == "skeet":
        c = rec_style.colors("skeet")
        c["line1_on"] = rec_style._mix(c["line1"], c["acc"], 0.45)
        for i, v in enumerate(c["strip"][:3]):
            c["s%d" % i], c["s%dd" % i] = v, rec_style._mix(v, "#000000", 0.55)
        dots = skeet_dots(c["bg"], rec_style._mix(c["bg"], "#ffffff", 0.022))
        c.update(dots=", url('file://%s')" % dots if dots else "", dots_size=", auto" if dots else "",
                 dots_pos=", 0 0" if dots else "", dots_rep=", repeat" if dots else "")
        return CSS_SKEET, c
    if look == "beta":
        b = rec_style.colors("beta")
        return CSS_BETA, dict(b, bg=b["bar"])
    return None


def gui():
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib, Gtk
    return Gdk, GLib, Gtk


def load_css(Gdk, Gtk, state={}):
    """CSS с текущей палитрой обоев: читается заново при каждом открытии меню."""
    import popup_theme
    p = popup_theme.palette()
    p.update(font=FONT, icon_font=ICON_FONT)
    sysc = system_colors(system_look(LAST_CLICK[0])) if menu_style() == "system" else None
    if sysc is not None:
        data = sysc[0] % dict(sysc[1], font=FONT, icon_font=ICON_FONT)
    elif menu_style() == "xp":
        import xpbar_colors
        c = xpbar_colors.colors()
        p.update(xp_bg=xpbar_colors.mix(c["base"], c["primary"], 0.13),
                 xp_light=c["t_hi"], xp_dark=c["tr_dark"], xp_sel=c["st_mid"])
        data = CSS_XP % p
    else:
        data = CSS % p
    # «Система» (Skeet/Beta) своих размеров: сжатие под компактный бар делало её тесной (15.10)
    if bar_compact() and sysc is None:
        data += CSS_COMPACT
    data = data.encode()
    old = state.get("provider")
    if old is not None and state.get("data") == data:
        return
    screen = Gdk.Screen.get_default()
    if old is not None:
        Gtk.StyleContext.remove_provider_for_screen(screen, old)
    prov = Gtk.CssProvider()
    prov.load_from_data(data)
    Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    state.update(provider=prov, data=data)


def build_menu(Gtk, on_action, on_quick, quick=None):
    """Gtk.Menu с рядом значков сверху. on_action(key), on_quick(aid, info)."""
    shell_mine = shell_is_mine()

    def row(icon, title, accel=""):
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                      spacing=5)
        ic = Gtk.Label(label=icon)
        ic.get_style_context().add_class("mi-icon")
        ic.set_xalign(0.5)
        t = Gtk.Label(label=title)
        t.get_style_context().add_class("mi-title")
        t.set_xalign(0)
        box.pack_start(ic, False, False, 0)
        box.pack_start(t, True, True, 0)
        if accel:
            a = Gtk.Label(label=accel)
            a.get_style_context().add_class("mi-accel")
            a.set_xalign(1)
            box.pack_end(a, False, False, 0)
        return box

    def fill(menu, entries, first_row=0, cols=1):
        r = first_row
        for e in entries:
            if e is None:
                it = Gtk.SeparatorMenuItem()
            else:
                icon, title, what, accel = e
                if callable(what):            # подменю, которое строится при открытии меню
                    what = what()
                if not isinstance(what, list) and what in VISIBLE and not VISIBLE[what]():
                    continue
                it = Gtk.MenuItem()
                it.add(row(icon, title, accel))
                if isinstance(what, list):
                    sub = Gtk.Menu()
                    sub.get_style_context().add_class("jd")
                    sub.set_reserve_toggle_size(False)
                    fill(sub, what)
                    it.set_submenu(sub)
                elif what == "noop":
                    it.set_sensitive(False)
                else:
                    if what == "refresh":
                        it.set_tooltip_text("Перезапустить виджеты на обоях" if not shell_mine
                                            else "Перезапустить верхний бар и виджеты на обоях")
                    it.connect("activate", lambda _w, k=what: on_action(k))
            menu.attach(it, 0, cols, r, r + 1)
            r += 1
        return r

    menu = Gtk.Menu()
    menu.get_style_context().add_class("jd")
    menu.set_reserve_toggle_size(False)
    quick = quick_apps() if quick is None else quick
    cols = max(1, len(quick))
    for i, (aid, name, gicon, info) in enumerate(quick):
        it = Gtk.MenuItem()
        it.get_style_context().add_class("quick")
        img = Gtk.Image.new_from_gicon(gicon, Gtk.IconSize.DND) if gicon else Gtk.Image()
        img.set_pixel_size(QUICK_PX if menu_style() == "classic" else 16)   # xp: 20 → 16 (14.10.2026)
        img.set_halign(Gtk.Align.CENTER)
        it.add(img)
        it.set_tooltip_text(name)
        it.connect("activate", lambda _w, a=aid, inf=info: on_quick(a, inf))
        menu.attach(it, i, i + 1, 0, 1)
    r = 0
    if quick:
        sep = Gtk.SeparatorMenuItem()
        sep.get_style_context().add_class("quick-sep")
        menu.attach(sep, 0, cols, 1, 2)
        r = 2
    fill(menu, MENU, r, cols)
    for m in [menu] + [c.get_submenu() for c in menu.get_children() if c.get_submenu()]:
        m.set_reserve_toggle_size(False)
    menu.show_all()
    return menu


# ── служба ───────────────────────────────────────────────────────────────────

def running_pid():
    try:
        pid = int(open(LOCK).read().strip() or 0)
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
    except (OSError, ValueError):
        return None
    if pid != os.getpid() and any(a.endswith(b"desktop_menu.py") for a in argv):
        return pid
    return None


def inherited_children():
    """pid детей, доставшихся от прошлого образа процесса. restart() делает execv: pid тот же,
    а подписка niri event-stream (её гасит PDEATHSIG) и звуки «timeout pw-play» прошлого
    образа остаются нашими детьми, которых новый образ не ждёт, — зомби копились
    (07.10.2026: 50 «[niri] <defunct>» за полтора суток, по одному на смену курсора)."""
    me, out = str(os.getpid()), set()
    for d in os.listdir("/proc"):
        if d.isdigit():
            try:
                s = open("/proc/%s/stat" % d).read()
                if s[s.rindex(")") + 2:].split()[1] == me:
                    out.add(int(d))
            except (OSError, ValueError, IndexError):
                pass
    return out


def reap_inherited(pids):
    """Подобрать завершившихся из inherited_children(); живых — при следующем вызове."""
    for pid in list(pids):
        try:
            done = os.waitpid(pid, os.WNOHANG)[0]
        except ChildProcessError:
            done = pid
        if done:
            pids.discard(pid)


def niri_json(*what):
    try:
        out = subprocess.run(["niri", "msg", "-j", *what], capture_output=True,
                             text=True, timeout=1.5).stdout
        return json.loads(out) if out.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _mtimes():
    res = []
    for f in CURSOR_FILES:
        try:
            res.append(os.stat(f).st_mtime_ns)
        except OSError:
            res.append(None)
    return res


def _self_mtime():
    try:
        return os.stat(os.path.abspath(__file__)).st_mtime_ns
    except OSError:
        return None


def run(dry_run=False):
    if os.path.exists(FLAG):
        print("desktop_menu: выключено (%s)" % FLAG, flush=True)
        return 0
    lock = open(LOCK, "a+")
    # Замок занят — подождать до 10 с (13.10.2026): icon_theme.py и прочие перезапускают
    # меню «TERM + сразу новый»; если старый процесс выходил дольше их ожидания, новый
    # видел занятый замок и уходил, а старый следом умирал — меню не оставалось вовсе.
    for i in range(51):
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if i == 50:
                print("desktop_menu: уже запущен (pid %s)" % running_pid(), file=sys.stderr)
                return 0
            time.sleep(0.2)
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()

    import gi
    Gdk, GLib, Gtk = gui()
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import GtkLayerShell
    import cairo

    _fill_dirs()
    E = GtkLayerShell.Edge
    st = {"wins": [], "menu": None, "cursor": _mtimes(), "self": _self_mtime(), "restart": False,
          "inherited": inherited_children()}      # до первого своего запуска
    reap_inherited(st["inherited"])

    def reap(pid):
        GLib.child_watch_add(GLib.PRIORITY_DEFAULT, pid, lambda *_: None)

    def sound(event):
        try:
            import ui_sound
            ui_sound.play(event)
        except Exception:
            pass

    def on_action(key):
        sound("click")
        run_action(key, dry=dry_run, reap=reap)

    def on_quick(aid, info):
        sound("click")
        launch_quick(aid, info, dry=dry_run, reap=reap)

    # Меню поверх окон (23.10.2026, пользователь прислал снимок: меню рисовалось ПОД окном, но
    # нажималось). Всплывающее меню niri кладёт в слой родителя, а он — BACKGROUND; поэтому
    # на время меню поверхность поднимается в TOP и сразу возвращается. Невидимая
    # поверхность в TOP ловила бы все щелчки монитора — сторож опускает её, как только
    # меню нет на экране, даже если оно не открылось.
    def lower(w):
        if getattr(w, "jarvis_raised", False):
            w.jarvis_raised = False
            GtkLayerShell.set_layer(w, GtkLayerShell.Layer.BACKGROUND)

    def raised_guard(w):
        m = st["menu"]
        if m is None or not m.get_visible():
            lower(w)
            return False
        return True

    def menu_done(_m):
        # Само меню не уничтожаем здесь: GTK шлёт activate пункту уже ПОСЛЕ
        # deactivate меню. Старое меню убирается при следующем открытии.
        for w in st["wins"]:
            lower(w)
        if st["restart"]:
            GLib.timeout_add(300, restart)

    def fit_menus(menu, py, surf_h):
        """Меню и подменю — целиком НАД нижней панелью (05.10.2026, просьба: «меню
        должно быть видно полностью; не хватает места — пусть открывается выше»).
        niri ограничивает всплывающие меню только краем экрана, а XP-панель лежит поверх
        них — низ подменю уходил под неё. Поэтому место считаем сами: где кончается
        свободный низ (высота слоя минус заход панели), и сдвигаем вверх rect-anchor-dy."""
        import popup_theme
        bottom = surf_h - popup_theme.bottom_overlap() - 8
        tops = {}

        def natural_h(mm):
            # до открытия GTK меряет меню в 0 — считаем по пунктам + поля и рамка (~16 px)
            rows = {}                                     # строка сетки → самый высокий пункт
            for c in mm.get_children():
                c.show_all()
                try:
                    r = mm.child_get_property(c, "top-attach")
                except TypeError:
                    r = id(c)
                # пункт, добавленный append (не attach), — top-attach −1 у всех: без этого
                # длинное подменю («Создать виджет», 19 строк) считалось одной строкой и не
                # поднималось над панелью (05.10.2026)
                if r is None or r < 0:
                    r = id(c)
                rows[r] = max(rows.get(r, 0), c.get_preferred_height()[1])
            return sum(rows.values()) + 16

        h = natural_h(menu)
        dy = min(0, bottom - (py + h))
        dy = max(dy, -py)                                 # не выше верха экрана
        menu.set_property("rect-anchor-dy", int(dy))
        tops[menu] = py + dy

        # Сдвиг подменю. GTK, открывая подменю (gtk_menu_item popup_submenu), САМ ставит ему
        # rect-anchor-dy (минус верхнее поле — первый пункт вровень с пунктом-родителем) и
        # затирает наш — поэтому ни расчёт заранее, ни по «select» не действовали, а то,
        # что подменю всё же поднималось, делал niri, прижимая его к краю монитора, — низ
        # длинного «Создать виджет» уходил под панель (05.10.2026). Теперь ловим запись GTK
        # (notify::rect-anchor-dy — синхронно, до показа) и добавляем к ней свой сдвиг.
        want, ours = {}, {}

        def on_dy(sub, _pspec):
            v = sub.get_property("rect-anchor-dy")
            if v == ours.get(sub) or sub not in want:
                return
            ours[sub] = v + want[sub]
            sub.set_property("rect-anchor-dy", ours[sub])

        def place(sub, item_top):
            sh = natural_h(sub)
            d = max(min(0, bottom - (item_top + sh)), -item_top)
            want[sub] = int(d)
            tops[sub] = item_top + d

        def hook(mm):
            # оценка места пункта — сумма высот пунктов выше + поле 8 px; «select» уточняет
            y_acc, rows_seen = 8, {}
            for it in mm.get_children():
                try:
                    r = mm.child_get_property(it, "top-attach")
                except TypeError:
                    r = None
                if r is None or r < 0:
                    r = id(it)
                it_h = it.get_preferred_height()[1]
                if r in rows_seen:
                    est_top = rows_seen[r]
                else:
                    est_top = rows_seen[r] = y_acc
                    y_acc += it_h
                sub = it.get_submenu() if hasattr(it, "get_submenu") else None
                if sub is None:
                    continue
                place(sub, tops.get(mm, 0) + est_top)
                sub.connect("notify::rect-anchor-dy", on_dy)

                def on_select(item, sub=sub, parent=mm):
                    place(sub, tops.get(parent, 0) + item.get_allocation().y)
                it.connect("select", on_select)
                hook(sub)
        hook(menu)

    def on_press(_w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 3:
            return False
        if st["menu"] is not None:
            st["menu"].destroy()
            st["menu"] = None
        try:                                 # место щелчка — для «Создать виджет»
            g = _w.jarvis_monitor.get_geometry()
            # слой меню начинается под верхним баром (exclusive zone 0) — поправка на него
            top = g.height - _w.get_allocated_height() if 0 < _w.get_allocated_height() < g.height else 0
            LAST_CLICK[0] = (int(g.x + ev.x), int(g.y + top + ev.y))
        except AttributeError:
            LAST_CLICK[0] = None
        load_css(Gdk, Gtk)
        m = build_menu(Gtk, on_action, on_quick)
        m.connect("deactivate", menu_done)
        st["menu"] = m
        fit_menus(m, ev.y, _w.get_allocated_height())
        _w.jarvis_raised = True
        GtkLayerShell.set_layer(_w, GtkLayerShell.Layer.TOP)
        _w.queue_draw()
        evc = ev.copy()

        def show():
            # слой меняется со следующим кадром поверхности — меню открывается после него
            if st["menu"] is m:
                m.popup_at_pointer(evc)
                sound("menu")
            GLib.timeout_add(400, raised_guard, _w)
            return False
        GLib.timeout_add(40, show)
        return True

    def make(monitor):
        w = Gtk.Window()
        w.jarvis_monitor = monitor
        w.set_title(NAMESPACE)
        w.set_app_paintable(True)
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.BACKGROUND)
        GtkLayerShell.set_monitor(w, monitor)
        for e in (E.TOP, E.BOTTOM, E.LEFT, E.RIGHT):
            GtkLayerShell.set_anchor(w, e, True)
        # 0, а не -1: поверхность уступает место бару (его exclusive zone) и не
        # лежит под ним. Бар всё равно выше (TOP), но так честнее и дешевле.
        GtkLayerShell.set_exclusive_zone(w, 0)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)

        def draw(_w, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            return True
        w.connect("draw", draw)
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        w.connect("button-press-event", on_press)
        w.show_all()
        return w

    def rebuild(*_):
        for w in st["wins"]:
            w.destroy()
        display = Gdk.Display.get_default()
        st["wins"] = [make(display.get_monitor(i)) for i in range(display.get_n_monitors())]
        print("desktop_menu: поверхностей %d%s" % (len(st["wins"]), " (dry-run)" if dry_run else ""),
              flush=True)
        return False

    def restart():
        # Новая тема курсора: GTK держит загруженную при старте, стол показал бы
        # старый курсор. Перезапуск процесса — самый надёжный способ перечитать.
        if st["menu"] is not None and st["menu"].get_visible():
            st["restart"] = True
            return False
        print("desktop_menu: сменился курсор или код меню — перезапуск", flush=True)
        lock.close()                     # замок отпускается, новый процесс его возьмёт
        args = [sys.executable, os.path.abspath(__file__)] + (["--dry-run"] if dry_run else [])
        os.execv(sys.executable, args)
        return False

    def poll():
        if os.path.exists(FLAG):
            Gtk.main_quit()
            return False
        if st["inherited"]:
            reap_inherited(st["inherited"])
        m = _mtimes()
        if m != st["cursor"]:
            st["cursor"] = m
            GLib.timeout_add(1500, restart)   # дать смене курсора дописать все файлы
        # правка самого меню — тоже перезапуск: иначе новые пункты появлялись только после
        # перезахода (19.10.2026, «Обновить» с перезапуском виджетов)
        me = _self_mtime()
        if me != st["self"]:
            st["self"] = me
            GLib.timeout_add(1500, restart)
        return True

    # Главный источник темы курсора для GTK под Wayland — gsettings; файлы выше —
    # запасной признак (их пишет cursor_colors.py при каждой пересборке).
    try:
        from gi.repository import Gio
        st["gs"] = Gio.Settings.new("org.gnome.desktop.interface")
        for key in ("cursor-theme", "cursor-size"):
            st["gs"].connect("changed::" + key, lambda *_: GLib.timeout_add(1500, restart) and None)
    except Exception as e:
        print("desktop_menu: gsettings: %s" % e, file=sys.stderr, flush=True)

    display = Gdk.Display.get_default()
    display.connect("monitor-added", lambda *_: GLib.timeout_add(500, rebuild))
    display.connect("monitor-removed", lambda *_: GLib.timeout_add(500, rebuild))
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
    GLib.timeout_add_seconds(POLL_S, poll)

    # Сменился стол — открытое меню убрать само (01.10.2026, просьба пользователя).
    # Подписка на события niri умирает вместе с процессом (PR_SET_PDEATHSIG).
    def close_menu():
        if st["menu"] is not None:
            st["menu"].popdown()
        return False

    def watch_niri():
        import ctypes
        import threading

        def die_with_parent():
            ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)

        def loop():
            while True:
                try:
                    p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True,
                                         preexec_fn=die_with_parent)
                    for line in p.stdout:
                        if line.startswith('{"WorkspaceActivated"'):
                            GLib.idle_add(close_menu)
                    p.wait()
                except OSError:
                    pass
                time.sleep(3)
        threading.Thread(target=loop, daemon=True).start()
    if os.environ.get("NIRI_SOCKET"):
        watch_niri()
    rebuild()
    Gtk.main()
    for w in st["wins"]:
        w.destroy()
    return 0


# ── проверка без экрана ──────────────────────────────────────────────────────

def render(path):
    """Меню и все подменю рядом, в PNG, через Gtk.OffscreenWindow — на экран ничего."""
    Gdk, GLib, Gtk = gui()
    load_css(Gdk, Gtk)
    _fill_dirs()
    menu = build_menu(Gtk, lambda k: None, lambda a, i: None)
    subs = [c.get_submenu() for c in menu.get_children() if c.get_submenu()]
    subs += [c.get_submenu() for m in list(subs) for c in m.get_children()
             if hasattr(c, "get_submenu") and c.get_submenu()]          # второй уровень (пресеты)
    # Подсветка «под курсором» у одного пункта — чтобы было видно, как выглядит наведение.
    items = [c for c in menu.get_children() if isinstance(c, Gtk.MenuItem)
             and not isinstance(c, Gtk.SeparatorMenuItem)]
    hover = next((c for c in items if c.get_submenu() is None
                  and "quick" not in c.get_style_context().list_classes()), None)
    if hover:
        hover.set_state_flags(Gtk.StateFlags.PRELIGHT, False)
    # Gtk.Menu вне всплывающего окна не рисуется (вынутое из своего попапа, оно
    # теряет размеры). Поэтому для снимка пункты переезжают в Gtk.Grid с CSS-именем
    # «menu» и классом jd — те же узлы CSS (menu.jd menuitem …) и та же сетка attach.
    class FakeMenu(Gtk.Grid):
        __gtype_name__ = "JarvisDesktopFakeMenu"
    FakeMenu.set_css_name("menu")
    ow = Gtk.OffscreenWindow()
    ow.get_style_context().add_class("popup")
    box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    box.set_border_width(12)
    for m in [menu] + subs:
        fake = FakeMenu()
        fake.get_style_context().add_class("jd")
        fake.set_valign(Gtk.Align.START)
        fake.set_column_homogeneous(True)
        for c in list(m.get_children()):
            l, r, t, b = [m.child_get_property(c, k) for k in
                          ("left-attach", "right-attach", "top-attach", "bottom-attach")]
            m.remove(c)
            fake.attach(c, l, t, r - l, b - t)
        box.pack_start(fake, False, False, 0)
    ow.add(box)
    ow.show_all()
    for _ in range(60):
        while Gtk.events_pending():
            Gtk.main_iteration_do(False)
        time.sleep(0.01)
    pb = ow.get_pixbuf()
    if pb is None:
        print("desktop_menu: не отрисовалось", file=sys.stderr)
        return 1
    pb.savev(path, "png", [], [])
    print("%s %dx%d" % (path, pb.get_width(), pb.get_height()))
    return 0


def test():
    """Все действия всухую + какие программы попали в верхний ряд."""
    _fill_dirs()
    print("верхний ряд:")
    for aid, name, _icon, info in quick_apps():
        launch_quick(aid, info, dry=True)
        print("    %-24s %s (%s)" % (aid, name, info.get_id()))
    print("пункты:")
    keys = []

    def walk(entries):
        for e in entries:
            if e is None:
                continue
            if callable(e[2]):
                walk(e[2]())
            elif isinstance(e[2], list):
                walk(e[2])
            else:
                keys.append(e[2])
    walk(MENU)
    missing = [k for k in ACTIONS if k not in keys]
    for k in keys:
        run_action(k, dry=True)
    if missing:
        print("действия без пункта меню: %s" % ", ".join(missing))
    bad = []
    import shutil
    for k in keys:
        act = ACTIONS[k]
        for cmd in (act(True) if callable(act) else act):
            exe = cmd[0]
            if exe in ("mkdir", "touch"):
                continue
            if not shutil.which(exe):
                bad.append("%s: нет %s" % (k, exe))
            for a in cmd[1:]:
                if a.endswith(".py") and not os.path.exists(a):
                    bad.append("%s: нет файла %s" % (k, a))
    print("проблемы: %s" % ("; ".join(bad) if bad else "нет"))
    return 1 if bad else 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def cmd_off():
    os.makedirs(os.path.dirname(FLAG), exist_ok=True)
    open(FLAG, "w").close()
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGTERM)
    print("меню рабочего стола выключено%s" % (" (pid %d остановлен)" % pid if pid else ""))
    return 0


def cmd_on():
    try:
        os.remove(FLAG)
    except FileNotFoundError:
        pass
    pid = running_pid()
    if not pid:
        subprocess.Popen([sys.executable, os.path.abspath(__file__)], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(30):
            time.sleep(0.1)
            pid = running_pid()
            if pid:
                break
    n = 0
    for _ in range(30 if pid else 0):     # дождаться, пока niri покажет поверхности
        n = sum(1 for l in (niri_json("layers") or []) if l.get("namespace") == NAMESPACE)
        if n:
            break
        time.sleep(0.1)
    print("меню рабочего стола включено%s" % (" (pid %d, поверхностей %d)" % (pid, n) if pid
                                              else " — но процесс не поднялся"))
    return 0 if pid else 1


def cmd_status():
    off = os.path.exists(FLAG)
    pid = running_pid()
    layers = niri_json("layers") or []
    mine = [l.get("output") for l in layers if l.get("namespace") == NAMESPACE]
    print("включено: %s" % ("нет" if off else "да"))
    print("работает: %s" % ("да, pid %d" % pid if pid else "нет"))
    print("поверхности niri: %s" % (", ".join(mine) if mine else "нет"))
    return 0


def main(argv):
    if not argv or argv[0] in ("run", "--dry-run"):
        return run(dry_run="--dry-run" in argv)
    cmd = argv[0]
    if cmd == "off":
        return cmd_off()
    if cmd == "on":
        return cmd_on()
    if cmd == "status":
        return cmd_status()
    if cmd == "state":                  # одним словом, для Настроек (как dock.py status)
        print("off" if os.path.exists(FLAG) else "on")
        return 0
    if cmd == "style":
        # вид меню: читается при каждом открытии — действует сразу, без перезапуска
        if len(argv) > 1 and argv[1] in STYLES:
            os.makedirs(os.path.dirname(STYLE_FILE), exist_ok=True)
            with open(STYLE_FILE, "w") as f:
                f.write(argv[1] + "\n")
        print(menu_style())
        return 0
    if cmd == "test":
        return test()
    if cmd == "--render" and len(argv) > 1:
        return render(argv[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
