#!/usr/bin/env python3
"""Переключатель окон Alt+Tab, как в Windows. 05.10.2026.

    alt_tab.py daemon [next]   резидент (автозапуск niri; второй экземпляр выходит)
    alt_tab.py next|prev       сигнал резиденту (бинд зовёт быстрый alt_tab.sh)

Просьба: «нормальный Alt+Tab как в Windows, в стиле XP и по теме Настроек (Default,
Skeet, Beta); стабильный, чтобы не отваливался; открывался почти моментально;
минималистично и компактно, но не мелко». Встроенный recent-windows niri ему не
нравится. Alt+Tab — сюда, Super+Tab — следующий монитор (поменяли местами).

Как работает:
  * держим Alt, Tab листает; отпустили Alt — переход в выбранное окно; Esc — отмена;
    стрелки ←/→ тоже листают (Alt+Shift у пользователя меняет раскладку — потому не
    Alt+Shift+Tab), щелчок мышью по значку — сразу туда. Короткое Alt+Tab —
    предыдущее окно, как в Windows;
  * порядок — по последнему фокусу (focus_timestamp niri), текущее окно первым;
  * быстро, потому что всё уже в памяти: окна и фокус приходят по потоку событий
    niri, окно GTK создано заранее. Бинд не запускает питон — alt_tab.sh пишет одну
    строку в канал $XDG_RUNTIME_DIR/jarvis-alttab.fifo;
  * стабильно: упал резидент — следующий Alt+Tab поднимет его сам (alt_tab.sh);
    поток событий niri переподключается; канал пересоздаётся, если пропал;
    ошибки в обработчиках пишутся в журнал и не роняют процесс;
  * вид — стиль системы монитора (state/alttab-style, пишет system_style.py):
    default — окно XP, skeet — как Настройки в Skeet, beta — плоско. Цвета — те же
    роли, что у панели часов (xp_calendar.colors).

Два режима (19.10.2026, просьба: «превью столов вместо окон, переключение окна/столы на ~,
в обоих режимах сразу оба монитора»). Клавиша ` / ~ (на русской — ё) переключает:
  * окна — значки окон, по группе на монитор (слева направо, как стоят мониторы);
  * столы — превью столов каждого монитора столбиком, как столы в niri (сверху вниз).
Режим запоминается (state/alttab-mode). Вид (state/alttab-layout, Настройки → Misc):
  * side — мониторы рядом слева направо, столы монитора столбиком;
  * stack — мониторы друг под другом (внешний сверху, Laptop снизу), столы монитора строкой.
Стол дашборда показывается всегда (виджеты — не окна niri). Окна Tab листает по давности, столы — с прошлого
стола дальше по порядку плиток (короткое Alt+Tab — прошлое окно или прошлый стол), h/l и j/k — по месту: h/l в строке и на соседний монитор.
Превью — снимок монитора (grim), сделанный, пока стол был на экране: в фоне, через
0,7 с после смены стола, после открытия/закрытия окон и раз в 45 с, если за ПК работают;
не во время игры, заставки и блокировки. Снимки — в памяти и в ~/.cache/alt_tab (по
монитору и номеру стола; после перезапуска резидента берутся оттуда). Окна за экраном
поменялись — снимок держится прежний, пока стол не покажут. Стол, у которого снимка нет
вовсе, рисуется схемой: обои + рамки окон со значками.
"""
import json
import os
import subprocess
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
# для проверок: свой каталог канала и «сухой» выбор (только спрятать, не переключать окно)
RUN = os.environ.get("JARVIS_ALTTAB_RUN", RUN)
DRY = bool(os.environ.get("JARVIS_ALTTAB_DRY"))
FIFO = os.path.join(RUN, "jarvis-alttab.fifo")
PIDF = os.path.join(RUN, "jarvis-alttab.pid")
LOG = os.environ.get("JARVIS_ALTTAB_LOG") or os.path.expanduser("~/.cache/alt_tab.log")
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/alttab-style")
HIDDEN_APPS = ("dash-",)            # окна «Dashboard» на первом столе — виджеты, не окна
STACK_STATE = os.path.expanduser("~/.config/hypr/state/stack-mode.json")
STACK_MIN_DESK = "\U000f05b0"   # стол свёрнутых окон стопки (stack_mode.MIN_NAME; у MSI + \u2060 в конце)
MODE_FILE = os.path.expanduser("~/.config/hypr/state/alttab-mode")
MODES = ("windows", "desks")
TW = 240                 # ширина превью стола (19.10.2026: 192 → 240, «чтобы столы было лучше
                         # видно»); высота — по сторонам монитора. В режиме окон не нужна
LAYOUT_FILE = os.path.expanduser("~/.config/hypr/state/alttab-layout")
LAYOUTS = ("side", "stack")       # мониторы рядом | друг под другом (Настройки → Misc)
DASH_JSON = os.path.expanduser("~/.config/niri/dashboard.json")
DASH_WIDGET_WS = "\U000f072c"     # как desktop_widgets.DASH_WIDGET_WS
SNAP_DELAY = 700         # мс после смены стола: анимация niri должна закончиться
# 19.10.2026: снимки столов — ещё и на диске (стол-<монитор>-<номер>.png): после перезапуска
# переключателя превью сразу есть, а не схема со значками до первого показа стола
THUMB_DIR = os.path.join(os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
                         "alt_tab")
GAME_APPS = ("steam_app_", "gamescope")
COLS = 7
ICON = 40
NVIM_ICON = 36
TILE = 72                # 05.10.2026: шире — под подписью короткое имя окна
CAP = 8                 # знаков в подписи
# Подгонка под Cozette (cozette_fit.py, 08.10.2026): текст 13 px вместо 16, знак 6 px вместо 8 —
# плитки 72 px стояли полупустыми. Плитка 60, подпись 9 знаков; значки 40 px как были.
FIT = (os.path.exists(os.path.expanduser("~/.config/fontconfig/conf.d/61-cozette-trial.conf"))
       and os.path.exists(os.path.expanduser("~/.config/hypr/state/cozette-fit")))
if FIT:
    TILE, CAP = 60, 9


def log(msg):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%F %T ") + msg + "\n")
        if os.path.getsize(LOG) > 200_000:
            lines = open(LOG).read().splitlines()[-400:]
            with open(LOG, "w") as f:
                f.write("\n".join(lines) + "\n")
    except OSError:
        pass


def alive_pid():
    try:
        pid = int(open(PIDF).read().strip())
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
        if len(argv) >= 2 and os.path.basename(argv[1]) == b"alt_tab.py":
            return pid
    except (OSError, ValueError):
        pass
    return None


def send(cmd):
    """Строка резиденту; канал открывается на чтение+запись — никогда не блокирует."""
    fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
    try:
        os.write(fd, (cmd + "\n").encode())
    finally:
        os.close(fd)


if sys.argv[1:2] in (["next"], ["prev"]):
    if alive_pid() and os.path.exists(FIFO):
        send(sys.argv[1])
        sys.exit(0)
    sys.argv = [sys.argv[0], "daemon", sys.argv[1]]
if sys.argv[1:2] != ["daemon"]:
    print(__doc__)
    sys.exit(0)
# Один резидент — по блокировке файла, а не по pid-файлу: 05.10.2026 бинд и перезапуск
# стартовали в одну секунду, pid-файла ещё не было, и поднялись ДВА резидента на одном
# канале — окна дрались за клавиатуру. Второй отдаёт команду первому и выходит.
import fcntl  # noqa: E402
_LOCK = os.open(os.path.join(RUN, "jarvis-alttab.lock"), os.O_CREAT | os.O_RDWR, 0o600)
try:
    fcntl.flock(_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    first = sys.argv[2] if len(sys.argv) > 2 else None
    if first in ("next", "prev") and os.path.exists(FIFO):
        time.sleep(0.3)                    # первый ещё может открывать канал
        send(first)
    sys.exit(0)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402

sys.path.insert(0, HERE)
import xp_calendar  # noqa: E402  — цвета трёх стилей (colors), шрифт
import nvim_lang  # noqa: E402

STYLES = ("default", "skeet", "beta")


def read_style():
    try:
        v = open(STYLE_FILE).read().strip()
        return v if v in STYLES else "default"
    except OSError:
        return "default"


def stack_active():
    """Режим «стопка» (stack_mode.py) включён?"""
    try:
        return '"active": true' in open(STACK_STATE).read()
    except OSError:
        return False


def read_mode():
    try:
        v = open(MODE_FILE).read().strip()
        return v if v in MODES else "windows"
    except OSError:
        return "windows"


def read_layout():
    try:
        v = open(LAYOUT_FILE).read().strip()
        return v if v in LAYOUTS else "side"
    except OSError:
        return "side"


_DASH = [None, set()]


def dash_names():
    """Имена стола дашборда (терминальный и виджетный вид — один стол), как
    desktop_widgets.dash_names; перечитывается, только если dashboard.json менялся."""
    try:
        mt = os.path.getmtime(DASH_JSON)
    except OSError:
        mt = 0
    if _DASH[0] != mt:
        try:
            d = json.load(open(DASH_JSON))
        except (OSError, ValueError):
            d = {}
        _DASH[:] = [mt, {n for n in (d.get("workspace"), d.get("widget_workspace") or DASH_WIDGET_WS) if n}]
    return _DASH[1]


def save_mode(mode):
    try:
        with open(MODE_FILE, "w") as f:
            f.write(mode + "\n")
    except OSError:
        pass


def plural(n, one, few, many):
    if n % 10 == 1 and n % 100 != 11:
        return one
    return few if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else many


def ppm_pixbuf(data):
    """PPM (P6) от grim → Pixbuf."""
    head, pos = [], 0
    while len(head) < 4:                         # P6, ширина, высота, максимум
        while data[pos:pos + 1].isspace():
            pos += 1
        end = pos
        while not data[end:end + 1].isspace():
            end += 1
        head.append(data[pos:end])
        pos = end
    if head[0] != b"P6":
        return None
    w, h = int(head[1]), int(head[2])
    pix = data[pos + 1:pos + 1 + w * h * 3]
    if len(pix) < w * h * 3:
        return None
    return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(pix), GdkPixbuf.Colorspace.RGB,
                                           False, 8, w, h, w * 3)


def screen_covered():
    """Заставка или блокировка — снимок стола был бы снимком их."""
    for layer in niri_json("layers") or []:
        ns = layer.get("namespace") or ""
        if "screensaver" in ns or "lock" in ns:
            return True
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")[:2]
            except OSError:
                continue
            # блокировщик живёт, только пока экран заперт (lockscreen → jarvis_lock / hyprlock)
            if any(os.path.basename(a) in (b"hyprlock", b"jarvis_lock.py") for a in argv):
                return True
    return False


def wallpapers():
    """Выход → путь обоев (awww query): фон схемы стола без снимка."""
    try:
        out = subprocess.run(["awww", "query"], capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return {}
    res = {}
    for line in out.splitlines():
        parts = line.strip(": ").split(":", 1)
        if len(parts) == 2 and "image: " in parts[1]:
            res[parts[0].strip()] = parts[1].split("image: ", 1)[1].strip()
    return res


def niri_json(*args):
    try:
        out = subprocess.run(["niri", "msg", "-j", *args], capture_output=True, text=True,
                             timeout=3).stdout
        return json.loads(out or "null")
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def ts(w):
    t = w.get("focus_timestamp") or {}
    return t.get("secs", 0) + t.get("nanos", 0) / 1e9


_apps = {}


def steam_game(app_id):
    """Окно игры Steam (06.10.2026, просьба: «у КС иконка как у картинки»): у gamescope и
    steam_app_N своего .desktop нет, значок по имени не находился — рисовалась заглушка.
    Номер игры — из steam_app_N или из запущенного «SteamLaunch AppId=N» (gamescope);
    значок — steam_icon_N (его кладёт Steam, есть и в пиксельной теме), название — из
    ярлыка Steam с этим значком. None — не игра Steam."""
    low = app_id.lower()
    num = low[len("steam_app_"):] if low.startswith("steam_app_") else None
    if low in ("gamescope", "cs2") and not num:
        for pid in os.listdir("/proc"):
            if pid.isdigit():
                try:
                    argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
                except OSError:
                    continue
                for a in argv:
                    if a.startswith(b"AppId="):
                        num = a[6:].decode(errors="replace")
                        break
                if num:
                    break
    if not num or not num.isdigit():
        return None
    name = ""
    for a in Gio.AppInfo.get_all():
        ic = a.get_icon()
        if ic is not None and ic.to_string() == "steam_icon_" + num:
            name = a.get_name() or ""
            break
    return (name or ("Counter-Strike 2" if num == "730" else "Steam")), \
        Gio.ThemedIcon.new_with_default_fallbacks("steam_icon_" + num)


def app_info(app_id):
    """(название, Gio.Icon) программы по app_id — через .desktop, как в нижней панели."""
    if app_id in _apps:
        return _apps[app_id]
    game = steam_game(app_id)
    if game:
        _apps[app_id] = game
        return game
    info = None
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            break
    if not info:
        for a in Gio.AppInfo.get_all():
            if isinstance(a, Gio.DesktopAppInfo) and \
                    (a.get_startup_wm_class() or "").lower() == app_id.lower():
                info = a
                break
    icon = info.get_icon() if info else None
    if icon is None:
        icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower() or "application-x-executable")
    name = (info.get_name() if info else "") or app_id or "Окно"
    if info is None and app_id.lower() in ("gamescope", "cs2"):
        return name, icon                 # игра ещё не видна — не запоминать заглушку
    _apps[app_id] = (name, icon)
    return _apps[app_id]


# ── окна терминала: что в них запущено (05.10.2026, просьба: «все kitty — один значок,
# не понимаю, где что») — значок программы по заголовку и короткая подпись ──
TERMINALS = {"kitty", "foot", "alacritty", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}
PROGRAM_ICONS = {"btop": "btop", "btop++": "btop", "htop": "htop", "top": "utilities-system-monitor",
                 "python": "python", "python3": "python",
                 "ipython": "python", "git": "git", "lazygit": "git", "yazi": "yazi", "node": "node",
                 "java": "java", "man": "accessories-text-editor", "nano": "accessories-text-editor",
                 "jchat": "jchat"}   # jchat в kitty — его значком, как в нижней панели (21.10.2026)
# nvim/vim — значком терминала, как в нижней панели (21.10.2026, просьба: «в alt tab тоже
# была иконка как снизу в панели»); файл в nvim (.md, .java, .py…) — значок языка в цвет
# обоев (nvim_lang.py, рисует md_icon.py)
SHELLS = {"fish", "zsh", "bash", "sh"}
def short(text):
    text = text.strip()
    return text if len(text) <= CAP else text[:CAP - 1].rstrip() + "…"


def term_view(title):
    """(имя значка | None, подпись) для окна терминала по его заголовку."""
    t = (title or "").strip()
    word = t.split()[0] if t.split() else ""
    base = os.path.basename(word)
    if not word or word.startswith(("~", "/")) or base in SHELLS:
        place = os.path.basename(word.rstrip("/")) if word not in ("", "~") else "~"
        return None, short(place or "~")
    rest = t[len(word):].strip()
    if base.lower() in ("nvim", "vim") and rest:
        # nvim пишет в заголовок открытые файлы, текущий первым (07.10.2026, autocmds.lua):
        # «nvim A.java · B.md». Запущенный до этого — заголовок от fish: «nvim АРГУМЕНТ
        # ПАПКА» («nvim . ~/java-practice», «nvim Junior\ Рыцарь ~/D/P/Generator»).
        if " · " not in rest:
            arg, _sp, cwd = rest.replace("\\ ", " ").rpartition(" ")
            if cwd.startswith(("~", "/")):
                rest = os.path.basename(cwd.rstrip("/")) or cwd if arg in ("", ".") \
                    else os.path.basename(arg.rstrip("/")) or arg
        cur = rest.split(" · ")[0]
        lg = nvim_lang.lang(cur)
        return (nvim_lang.PREFIX + lg if lg else None), short(cur)
    return PROGRAM_ICONS.get(base.lower()), short(base)


def window_caption(w, app_name):
    t = (w.get("title") or "").strip()
    for sep in (" — ", " - ", " – ", " | "):
        if sep in t:
            t = t.split(sep)[0]
            break
    return short(t or app_name)


class Switcher:
    def __init__(self):
        self.windows = {}             # id → окно niri
        self.ws = {}                  # id стола → стол niri
        self.outs = {}                # выход → logical (x, y, width, height)
        self.items = []               # окна или столы — в порядке групп
        self.groups = []              # [(выход, [индексы items], столбцов)]
        self.tiles = {}
        self.order = []               # индексы items по давности (Tab)
        self.opos = 0
        self.sel = 0
        self.mode = read_mode()       # windows | desks (клавиша `, 19.10.2026)
        self.layout = read_layout()   # side | stack — мониторы рядом или друг под другом
        self.ws_seen = {}             # id стола → когда стал активным (давность столов)
        self.thumbs = {}              # id стола → Pixbuf снимка
        self.disk_tried = set()       # столы, чей снимок уже искали на диске
        self.snap_ids = {}            # выход → таймер снимка
        self.snap_procs = {}          # выход → grim в работе
        self.walls = {}               # выход → (путь, Pixbuf) обоев для схемы
        self.icon_pb = {}
        self.areas = {}
        self.acc = Gdk.RGBA()
        self.last_act = time.monotonic()
        self.shown = False
        self.focused_in = False
        self.css_key = None
        self.provider = None

        self.win = Gtk.Window()
        self.win.set_decorated(False)
        GtkLayerShell.init_for_window(self.win)
        GtkLayerShell.set_namespace(self.win, "jarvis-alttab")
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        visual = self.win.get_screen().get_rgba_visual()
        if visual:
            self.win.set_visual(visual)
        self.win.set_app_paintable(True)
        self.win.connect("key-press-event", self.on_key)
        self.win.connect("key-release-event", self.on_key_release)
        self.win.connect("focus-in-event", self.on_focus_in)

        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.box.get_style_context().add_class("at-box")
        self.box.set_size_request(320, -1)      # с 1–2 окнами строка под значками не обрезается
        # по столбцу на монитор (19.10.2026): заголовок-монитор + сетка плиток
        self.cols = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=18)
        self.cols.set_halign(Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0.5)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.get_style_context().add_class("at-title")
        self.sub = Gtk.Label(xalign=0.5)
        self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub.get_style_context().add_class("at-sub")
        # Ширину панели задаёт только сетка плиток (05.10.2026, просьба: «при переходах размер
        # alt+tab меняется на пару пикселей»): у меток с многоточием «желаемая» ширина — весь
        # текст, и длинное имя окна раздвигало панель. max_width_chars 1 — желаемая ширина
        # минимальна, метка растягивается по ширине панели и сокращается многоточием.
        for lab in (self.title, self.sub):
            lab.set_max_width_chars(1)
            lab.set_hexpand(True)
            lab.set_single_line_mode(True)
        self.box.pack_start(self.cols, False, False, 0)
        self.box.pack_start(self.title, False, False, 0)
        self.box.pack_start(self.sub, False, False, 0)
        self.win.add(self.box)
        self.box.show_all()

        self.load_initial()
        self.follow_niri()
        self.open_fifo()
        GLib.timeout_add_seconds(5, self.keep_fifo)
        GLib.idle_add(self.warm)
        GLib.timeout_add_seconds(3, lambda: (self.snap_tick(True), False)[1])   # первые снимки
        GLib.timeout_add_seconds(45, self.snap_tick)

    def warm(self):
        """Прогрев: один раз собрать и отрисовать переключатель вне экрана — шрифты Pango,
        стиль и значки грузятся при старте резидента, а не в момент первого Alt+Tab."""
        try:
            t = time.monotonic()
            self.build(step=1)
            off = Gtk.OffscreenWindow()
            self.win.remove(self.box)
            off.add(self.box)
            off.show_all()
            while Gtk.events_pending():
                Gtk.main_iteration_do(False)
            off.remove(self.box)
            self.win.add(self.box)
            off.destroy()
            log("прогрев %.0f мс" % ((time.monotonic() - t) * 1000))
        except Exception:
            log("прогрев: " + traceback.format_exc(limit=3))
        return False

    # ── состояние niri ──
    def load_initial(self):
        for w in niri_json("windows") or []:
            self.windows[w["id"]] = w
        now = time.monotonic()
        for s in niri_json("workspaces") or []:
            self.ws[s["id"]] = s
            if s.get("is_active"):
                self.ws_seen[s["id"]] = now if s.get("is_focused") else now - 1
        self.load_outputs()

    def load_outputs(self):
        outs = niri_json("outputs") or {}
        self.outs = {k: o["logical"] for k, o in outs.items() if o.get("logical")}
        self.load_disk_thumbs()                   # размер снимка — по сторонам монитора
        return False

    def follow_niri(self):
        """Поток событий niri — в главном цикле GTK, без потоков Python (05.10.2026: с
        потоком читателя первый показ вешал процесс намертво — главный поток ждал
        загрузку шрифтов Pango, тот — что-то ещё; Alt+Tab переставал отвечать)."""
        self.stream_buf = b""
        try:
            self.stream = subprocess.Popen(["niri", "msg", "-j", "event-stream"],
                                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            fd = self.stream.stdout.fileno()
            os.set_blocking(fd, False)
            GLib.io_add_watch(fd, GLib.PRIORITY_DEFAULT, GLib.IO_IN | GLib.IO_HUP | GLib.IO_ERR,
                              self.on_stream)
        except OSError as e:
            log("event-stream: %s" % e)
            GLib.timeout_add_seconds(2, self.restart_stream)
        return False

    def on_stream(self, fd, cond):
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            return True
        except OSError:
            chunk = b""
        if not chunk:                                   # niri перезапущен / поток закрыт
            try:
                self.stream.kill()
                self.stream.wait(timeout=1)
            except (OSError, subprocess.SubprocessError):
                pass
            GLib.timeout_add_seconds(2, self.restart_stream)
            return False
        self.stream_buf += chunk
        *lines, self.stream_buf = self.stream_buf.split(b"\n")
        for line in lines:
            try:
                self.apply_event(json.loads(line))
            except ValueError:
                pass
        return True

    def restart_stream(self):
        self.reload()
        self.follow_niri()
        return False

    def reload(self):
        self.windows.clear()
        self.ws.clear()
        self.load_initial()
        return False

    def apply_event(self, ev):
        try:
            if "WindowsChanged" in ev:
                self.windows = {w["id"]: w for w in ev["WindowsChanged"]["windows"]}
            elif "WindowOpenedOrChanged" in ev:
                w = ev["WindowOpenedOrChanged"]["window"]
                old = self.windows.get(w["id"])
                self.windows[w["id"]] = w
                # смена заголовка (у терминалов — постоянно) снимка не стоит
                if old is None or old.get("workspace_id") != w.get("workspace_id") \
                        or old.get("is_floating") != w.get("is_floating"):
                    self.desk_changed(w.get("workspace_id"))
                    if old is not None:
                        self.desk_changed(old.get("workspace_id"))
            elif "WindowClosed" in ev:
                w = self.windows.pop(ev["WindowClosed"]["id"], None)
                if w:
                    self.desk_changed(w.get("workspace_id"))
            elif "WindowLayoutsChanged" in ev:
                for wid, lay in ev["WindowLayoutsChanged"].get("changes") or []:
                    w = self.windows.get(wid)
                    if w:
                        w["layout"] = lay
                        self.desk_changed(w.get("workspace_id"))
            elif "WindowFocusChanged" in ev:
                fid = ev["WindowFocusChanged"]["id"]
                self.last_act = time.monotonic()
                for w in self.windows.values():
                    w["is_focused"] = w["id"] == fid
                if fid in self.windows:
                    self.focus_desk(self.windows[fid].get("workspace_id"))
            elif "WindowFocusTimestampChanged" in ev:
                d = ev["WindowFocusTimestampChanged"]
                if d.get("id") in self.windows:
                    self.windows[d["id"]]["focus_timestamp"] = d.get("focus_timestamp")
            elif "WorkspacesChanged" in ev:
                self.ws = {s["id"]: s for s in ev["WorkspacesChanged"]["workspaces"]}
                for k in [k for k in self.thumbs if k not in self.ws]:
                    del self.thumbs[k]
                GLib.idle_add(self.load_outputs)          # монитор подключили/сняли
            elif "WorkspaceActivated" in ev:
                d = ev["WorkspaceActivated"]
                s = self.ws.get(d["id"])
                self.last_act = time.monotonic()
                # Давность — только когда на стол перешли сами (focused). Стол, ставший
                # видимым на другом мониторе без фокуса (туда переложили окно, картинку
                # в картинке, дашборд), не «был только что» — 19.10.2026, просьба: «столы
                # переключаются не в правильном порядке»
                if d.get("focused"):
                    self.ws_seen[d["id"]] = self.last_act
                if s:
                    self.schedule_snap(s.get("output"), force=True)
                    for o in self.ws.values():
                        if o.get("output") == s.get("output"):
                            o["is_active"] = o["id"] == s["id"]
                    if d.get("focused"):
                        self.focus_desk(s["id"])
        except Exception:
            log("event: " + traceback.format_exc(limit=2))
        return False

    def focus_desk(self, wsid):
        """Фокус перешёл на стол wsid — окном (в т.ч. на другом мониторе) или столом.
        19.10.2026, просьба: «перешёл с окна на мониторе 1 на окно на мониторе 2 — Alt+Tab
        должен сразу показать стол монитора 1». Переход между мониторами WorkspaceActivated
        не даёт (оба стола уже активны), и столы считали фокусным прежний. Теперь стол,
        с которого ушли, — «был только что», новый — ещё позже."""
        if wsid not in self.ws:
            return
        now = time.monotonic()
        for o in self.ws.values():
            if o.get("is_focused") and o["id"] != wsid:
                self.ws_seen[o["id"]] = now
            o["is_focused"] = o["id"] == wsid
        self.ws_seen[wsid] = now + 0.001

    # ── снимки столов (19.10.2026) ──
    def active_ws(self, out):
        return next((s for s in self.ws.values() if s.get("output") == out and s.get("is_active")), None)

    def desk_changed(self, wsid):
        """На столе открыли/закрыли/подвинули окно: на экране — переснять. За экраном
        снимок остаётся прежним до показа стола (19.10.2026: раньше он сбрасывался в схему
        со значками — Просьба: «иногда сбрасываются… просто иконки вместо предобзора»;
        схема — только если снимка не было вовсе)."""
        s = self.ws.get(wsid)
        if not s:
            return
        self.last_act = time.monotonic()
        if s.get("is_active"):
            self.schedule_snap(s.get("output"))

    def schedule_snap(self, out, delay=SNAP_DELAY, force=False):
        """force — отсчёт заново (смена стола: снимать после анимации); иначе уже
        назначенный снимок не сдвигается — поток событий не откладывает его бесконечно."""
        if not out:
            return
        if out in self.snap_ids:
            if not force:
                return
            GLib.source_remove(self.snap_ids.pop(out))
        self.snap_ids[out] = GLib.timeout_add(delay, self.snap, out)

    def snap_tick(self, force=False):
        """Раз в 45 с — переснять столы на экране (видео, текст меняются без событий),
        если за ПК работали последние 2 минуты. Заодно обои для схем."""
        if force or time.monotonic() - self.last_act < 120:
            walls = wallpapers()
            for out, path in walls.items():
                if (self.walls.get(out) or (None,))[0] != path:
                    self.walls[out] = (path, self.load_wall(out, path))
            for out in self.outs:
                self.schedule_snap(out, 50)
        return True

    def thumb_size(self, out):
        lg = self.outs.get(out) or {}
        w, h = lg.get("width") or 16, lg.get("height") or 9
        return TW, max(1, round(TW * h / w))

    def load_wall(self, out, path):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(path, *self.thumb_size(out), False)
        except GLib.Error:
            return None

    def gaming(self):
        return any((w.get("app_id") or "").startswith(GAME_APPS) for w in self.windows.values()
                   if w.get("is_focused"))

    def snap(self, out):
        self.snap_ids.pop(out, None)
        if self.shown:                        # иначе на снимок попал бы сам переключатель
            self.schedule_snap(out, 800)
            return False
        s = self.active_ws(out)
        if not s or out in self.snap_procs or DRY or self.gaming() or screen_covered():
            return False
        try:
            p = Gio.Subprocess.new(["grim", "-s", "0.2", "-t", "ppm", "-o", out, "-"],
                                   Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
        except GLib.Error as e:
            log("grim: %s" % e.message)
            return False
        self.snap_procs[out] = p
        p.communicate_async(None, None, self.on_snap, (out, s["id"]))
        # grim виснет, если niri не на активной консоли — не ждать вечно
        GLib.timeout_add_seconds(3, lambda: (self.snap_procs.get(out) is p and p.force_exit(), False)[1])
        return False

    def on_snap(self, p, res, data):
        out, wsid = data
        if self.snap_procs.get(out) is p:
            del self.snap_procs[out]
        try:
            _ok, stdout, _err = p.communicate_finish(res)
        except GLib.Error:
            return
        cur = self.active_ws(out)
        if not p.get_successful() or stdout is None or not cur or cur["id"] != wsid:
            return                            # пока снимали, стол сменился — снимок не его
        try:
            pb = ppm_pixbuf(stdout.get_data())
        except (ValueError, GLib.Error):
            pb = None
        if pb:
            self.thumbs[wsid] = pb = pb.scale_simple(*self.thumb_size(out), GdkPixbuf.InterpType.BILINEAR)
            self.save_thumb(cur, pb)

    def thumb_path(self, s):
        return os.path.join(THUMB_DIR, "desk-%s-%s.png" % (s.get("output"), s.get("idx")))

    def save_thumb(self, s, pb):
        """PNG 240×135 — пара миллисекунд; через временный файл, чтобы не прочесть половину."""
        try:
            os.makedirs(THUMB_DIR, exist_ok=True)
            path = self.thumb_path(s)
            pb.savev(path + ".tmp", "png", [], [])
            os.replace(path + ".tmp", path)
        except (OSError, GLib.Error) as e:
            log("thumb save: %s" % e)

    def load_disk_thumbs(self):
        """Столы без снимка — взять последний с диска (по монитору и номеру стола)."""
        if DRY:
            return
        for wsid, s in self.ws.items():
            if wsid in self.thumbs or wsid in self.disk_tried:
                continue
            self.disk_tried.add(wsid)
            path = self.thumb_path(s)
            if not os.path.exists(path):
                continue
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
            except GLib.Error:
                continue
            if (pb.get_width(), pb.get_height()) == self.thumb_size(s.get("output")):
                self.thumbs[wsid] = pb

    # ── канал от бинда ──
    def open_fifo(self):
        try:
            if not os.path.exists(FIFO):
                os.mkfifo(FIFO, 0o600)
            self.fd = os.open(FIFO, os.O_RDWR | os.O_NONBLOCK)
            GLib.io_add_watch(self.fd, GLib.PRIORITY_HIGH, GLib.IO_IN, self.on_fifo)
        except OSError as e:
            log("fifo: %s" % e)

    def keep_fifo(self):
        if not os.path.exists(FIFO):
            log("канал пропал — пересоздаю")
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.open_fifo()
        return True

    def on_fifo(self, fd, _cond):
        try:
            data = os.read(fd, 4096).decode(errors="replace")
        except OSError:
            return True
        # Команду выполнить ПОСЛЕ выхода из обработчика канала: показ окна прямо отсюда
        # (из io_add_watch) вешал процесс в win.show() — воспроизведено 05.10.2026.
        for cmd in data.split():
            GLib.idle_add(self.run_cmd, cmd)
        return True

    def run_cmd(self, cmd):
        try:
            self.command(cmd)
        except Exception:
            log("cmd %s: %s" % (cmd, traceback.format_exc(limit=3)))
        return False

    def command(self, cmd):
        step = -1 if cmd == "prev" else 1
        if not self.shown:
            self.open(step)
        else:
            self.move(step)

    # ── показ ──
    def focused_output(self):
        for w in self.windows.values():
            if w.get("is_focused"):
                s = self.ws.get(w.get("workspace_id"))
                if s and s.get("output"):
                    return s["output"]
        for s in self.ws.values():
            if s.get("is_focused"):
                return s.get("output")
        return None

    def monitor_for(self, name):
        if not name:
            return None
        lg = self.outs.get(name) or ((niri_json("outputs") or {}).get(name) or {}).get("logical") or {}
        d = Gdk.Display.get_default()
        for i in range(d.get_n_monitors()):
            g = d.get_monitor(i).get_geometry()
            if g.x == lg.get("x") and g.y == lg.get("y"):
                return d.get_monitor(i)
        return None

    def open(self, step):
        # Открывается в последнем режиме (окна или столы, клавиша `), оба монитора сразу.
        self.mode = read_mode()         # могли сменить в Настройках → Misc
        if stack_active():              # в стопке все окна на одном столе — только окна
            self.mode = "windows"       # (21.10.2026), выбор в файле не трогаем
        if not self.build(step):
            log("окон нет — нечего показывать")
            return
        self.show()

    def out_order(self):
        """Выходы слева направо, как стоят мониторы; в виде «друг под другом» — внешние
        сверху, экран ноутбука (eDP) внизу (19.10.2026, просьба: «MSI сверху, снизу ноут»)."""
        outs = {s.get("output") for s in self.ws.values() if s.get("output")}
        if self.layout == "stack":
            return sorted(outs, key=lambda o: (o.startswith("eDP"), (self.outs.get(o) or {}).get("x", 0), o))
        return sorted(outs, key=lambda o: ((self.outs.get(o) or {}).get("x", 0), o))

    def desks_of(self, out):
        """Столы монитора сверху вниз; пустые — только активный (в niri внизу всегда пустой)
        и стол дашборда: виджеты не окна niri, и он казался пустым (19.10.2026)."""
        busy = {w.get("workspace_id") for w in self.windows.values()}
        dash = dash_names()
        return sorted((s for s in self.ws.values() if s.get("output") == out
                       and (s["id"] in busy or s.get("is_active") or s.get("name") in dash)),
                      key=lambda s: s.get("idx") or 0)

    def build(self, step, keep=None):
        """Плитки режима: по группе на монитор. keep — id окна/стола, который выбрать;
        иначе step-й по давности (1 — прошлое окно/стол, как короткое Alt+Tab в Windows)."""
        desks = self.mode == "desks"
        self.layout = read_layout()
        stack = self.layout == "stack"
        groups = []
        if desks:
            for out in self.out_order():
                xs = self.desks_of(out)
                if xs:
                    groups.append((out, xs))
        else:
            # 20.10.2026: «можно не разделять экраны, а сразу в общем списке показывать
            # окна» — одна сетка на все мониторы по давности; монитор — в строке под сеткой
            xs = [w for w in self.windows.values()
                  if not (w.get("app_id") or "").startswith(HIDDEN_APPS)
                  and (self.ws.get(w.get("workspace_id")) or {}).get("output")]
            xs.sort(key=lambda w: (not w.get("is_focused"), -ts(w)))
            if xs:
                groups.append((None, xs))
        if not groups:
            return False
        self.items, self.groups = [], []
        for out, xs in groups:
            idx = list(range(len(self.items), len(self.items) + len(xs)))
            if stack:                     # монитор — строка: столы слева направо
                cols = min(6 if desks else COLS, len(xs))
            else:                         # монитор — столбец: столы сверху вниз, как в niri
                cols = (1 if len(xs) <= 5 else 2) if desks else min(COLS, len(xs))
            self.items.extend(xs)
            self.groups.append((out, idx, cols))
        if desks:
            seen = self.ws_seen
            rank = lambda s: (not s.get("is_focused"), -seen.get(s["id"], 0), s.get("idx") or 0)  # noqa: E731
        else:
            rank = lambda w: (not w.get("is_focused"), -ts(w))  # noqa: E731
        recent = sorted(range(len(self.items)), key=lambda i: rank(self.items[i]))
        n = len(recent)
        if desks:
            # 19.10.2026, просьба: «сначала стол, на котором я был до этого, а дальше Tab —
            # по столам слева направо, а не по посещаемости». Tab идёт по плиткам в порядке
            # показа (мониторы слева направо, столы сверху вниз); старт — на прошлом столе
            self.order = list(range(n))
            cur = recent[0]
            start = (recent[1] if step > 0 else (cur - 1) % n) if n > 1 and step else cur
        else:
            self.order = recent
            start = recent[(step if step > 0 else n - 1) % n if n > 1 and step else 0]
        hit = [i for i in self.order if keep is not None and self.items[i]["id"] == keep]
        self.sel = hit[0] if hit else start
        self.opos = self.order.index(self.sel)

        self.apply_css()
        for ch in list(self.cols.get_children()):
            self.cols.remove(ch)
            ch.destroy()
        self.tiles, self.areas = {}, {}
        self.cols.set_orientation(Gtk.Orientation.VERTICAL if stack else Gtk.Orientation.HORIZONTAL)
        self.cols.set_spacing(10 if stack else 18)
        here = self.focused_output()
        many = desks and (len(self.outs) > 1 or len(groups) > 1)
        for out, idx, cols in self.groups:
            col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            col.set_valign(Gtk.Align.START)
            col.set_halign(Gtk.Align.CENTER)
            if many:
                head = Gtk.Label(label=self.monitor_name(out), xalign=0.5)
                head.get_style_context().add_class("at-head")
                if out == here:
                    head.get_style_context().add_class("at-here")
                col.pack_start(head, False, False, 0)
            grid = Gtk.FlowBox()
            grid.set_selection_mode(Gtk.SelectionMode.NONE)
            grid.set_homogeneous(True)
            grid.set_column_spacing(4)
            grid.set_row_spacing(4)
            grid.set_min_children_per_line(cols)    # иначе FlowBox ставит по одному в строку
            grid.set_max_children_per_line(cols)
            grid.get_style_context().add_class("at-grid")
            for i in idx:
                tile = self.desk_tile(i) if desks else self.win_tile(i)
                tile.connect("button-press-event", lambda _t, _e, k=i: self.pick(k))
                grid.add(tile)
                self.tiles[i] = tile
            col.pack_start(grid, False, False, 0)
            self.cols.pack_start(col, False, False, 0)
        self.cols.show_all()
        self.mark()
        return True

    def win_tile(self, i):
        w = self.items[i]
        theme = Gtk.IconTheme.get_default()
        app_id = w.get("app_id") or ""
        name, icon = app_info(app_id)
        img = None
        if app_id.lower() in TERMINALS:
            which, cap = term_view(w.get("title"))
            if which and theme.has_icon(which):
                img = Gtk.Image.new_from_icon_name(which, Gtk.IconSize.DIALOG)
        else:
            cap = window_caption(w, name)
        if img is None:
            img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.DIALOG)
        if app_id.lower() in TERMINALS and (which or "").startswith(nvim_lang.PREFIX):
            # плитка значка nvim без полей — на 40 px крупнее соседей, на 32 мелковата — 36
            # (Пользователь 21.10.2026: «чуть-чуть уменьшить»), место под значок прежнее
            img.set_pixel_size(NVIM_ICON)
            img.set_size_request(ICON, ICON)
        else:
            img.set_pixel_size(ICON)
        label = Gtk.Label(label=cap)
        label.get_style_context().add_class("at-cap")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        inner.pack_start(img, False, False, 0)
        inner.pack_start(label, False, False, 0)
        tile = Gtk.EventBox()
        tile.set_size_request(TILE, -1)
        tile.get_style_context().add_class("at-tile")
        tile.add(inner)
        return tile

    # ── плитка стола (19.10.2026) ──
    def desk_wins(self, s):
        return [w for w in self.windows.values() if w.get("workspace_id") == s["id"]]

    def desk_names(self, s):
        """Имена программ стола по порядку колонок; окна дашборда — одним словом."""
        names, dash = [], False
        for w in sorted(self.desk_wins(s), key=lambda w: tuple((w.get("layout") or {})
                                                                 .get("pos_in_scrolling_layout") or (99, 99))):
            app_id = w.get("app_id") or ""
            if app_id.startswith(HIDDEN_APPS):
                dash = True
                continue
            name = app_info(app_id)[0]
            if app_id.lower() in TERMINALS:
                which, cap = term_view(w.get("title"))
                name = cap if which else name
            if name not in names:
                names.append(name)
        if s.get("name") in dash_names():
            dash = True
        return (["Дашборд"] if dash else []) + names

    def desk_tile(self, i):
        s = self.items[i]
        tw, th = self.thumb_size(s.get("output"))
        area = Gtk.DrawingArea()
        area.set_size_request(tw, th)
        area.connect("draw", self.draw_desk, s["id"], s.get("output"))
        self.areas[i] = area
        names = self.desk_names(s)
        label = Gtk.Label(label="%s  %s" % (s.get("idx") or "", " · ".join(names) or "пусто"), xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(1)
        label.set_hexpand(True)
        label.get_style_context().add_class("at-cap")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        inner.pack_start(area, False, False, 0)
        inner.pack_start(label, False, False, 0)
        tile = Gtk.EventBox()
        tile.get_style_context().add_class("at-tile")
        tile.get_style_context().add_class("at-desk")
        tile.add(inner)
        return tile

    def draw_desk(self, area, cr, wsid, out):
        w, h = area.get_allocated_width(), area.get_allocated_height()
        pb = self.thumbs.get(wsid)
        if pb is not None:
            if pb.get_width() != w or pb.get_height() != h:
                pb = pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
            Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
            cr.paint()
        else:
            self.draw_scheme(cr, w, h, wsid, out)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.set_line_width(1)
        cr.rectangle(0.5, 0.5, w - 1, h - 1)
        cr.stroke()
        if self.items and self.items[self.sel].get("id") == wsid:
            # выбранный стол — рамка акцентом по самой картинке: превью закрывает плитку
            # целиком, и выделение плитки (фон, черта) почти не видно
            Gdk.cairo_set_source_rgba(cr, self.acc)
            cr.set_line_width(2)
            cr.rectangle(1, 1, w - 2, h - 2)
            cr.stroke()
        return False

    def draw_scheme(self, cr, w, h, wsid, out):
        """Стол без снимка: обои монитора, на них рамки окон со значками — колонки ленты
        niri слева направо (сдвиг ленты niri не отдаёт; не влезло — сжато по ширине)."""
        wall = (self.walls.get(out) or (None, None))[1]
        if wall is not None:
            Gdk.cairo_set_source_pixbuf(cr, wall, 0, 0)
            cr.paint()
            cr.set_source_rgba(0, 0, 0, 0.35)
        else:
            cr.set_source_rgb(0.08, 0.08, 0.1)
        cr.paint()
        lg = self.outs.get(out) or {}
        ow, oh = lg.get("width") or 1920, lg.get("height") or 1080
        k = w / ow
        wins = [x for x in self.windows.values() if x.get("workspace_id") == wsid]
        columns = {}
        floats = []
        for x in wins:
            lay = x.get("layout") or {}
            pos = lay.get("pos_in_scrolling_layout")
            size = lay.get("tile_size") or lay.get("window_size") or (ow / 2, oh)
            if x.get("is_floating") or not pos:
                floats.append((x, size))
            else:
                columns.setdefault(pos[0], []).append((pos[1], x, size))
        gap = 8
        rects = []
        cx = gap
        for c in sorted(columns):
            cells = sorted(columns[c], key=lambda t: t[0])
            cw = max(t[2][0] for t in cells)
            ch = sum(t[2][1] for t in cells) + gap * (len(cells) - 1)
            cy = max(gap, (oh - ch) / 2)
            for _row, x, size in cells:
                rects.append((x, cx, cy, cw, size[1]))
                cy += size[1] + gap
            cx += cw + gap
        sx = min(1.0, ow / cx) if cx > gap else 1.0
        for x, size in floats:
            rects.append((x, (ow - size[0]) / 2 / sx, (oh - size[1]) / 2, size[0], size[1]))
        for x, rx, ry, rw, rh in rects:
            X, Y, W, H = rx * sx * k, ry * k, max(4, rw * sx * k - 1), max(4, rh * k)
            cr.set_source_rgba(0.06, 0.06, 0.08, 0.85)
            cr.rectangle(X, Y, W, H)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.35 if x.get("is_focused") else 0.18)
            cr.rectangle(X + 0.5, Y + 0.5, W - 1, H - 1)
            cr.stroke()
            size = int(min(24, W - 4, H - 4))
            pb = self.icon_for(x.get("app_id") or "", size) if size >= 8 else None
            if pb is not None:
                Gdk.cairo_set_source_pixbuf(cr, pb, round(X + (W - size) / 2), round(Y + (H - size) / 2))
                cr.paint()

    def icon_for(self, app_id, size):
        key = (app_id, size)
        if key not in self.icon_pb:
            pb = None
            try:
                info = Gtk.IconTheme.get_default().lookup_by_gicon(
                    app_info(app_id)[1], size, Gtk.IconLookupFlags.FORCE_SIZE)
                pb = info.load_icon() if info else None
            except (GLib.Error, TypeError):
                pass
            self.icon_pb[key] = pb
        return self.icon_pb[key]

    def show(self):
        mon = self.monitor_for(self.focused_output())
        if mon:
            GtkLayerShell.set_monitor(self.win, mon)
        self.focused_in = False
        self.reshown = False
        self.shown = True
        self.opened_at = time.monotonic()
        self.win.show()
        GLib.timeout_add(30, self.watch_alt)

    def mark(self):
        for a in self.areas.values():
            a.queue_draw()
        for i, t in self.tiles.items():
            ctx = t.get_parent().get_style_context() if t.get_parent() else t.get_style_context()
            (ctx.add_class if i == self.sel else ctx.remove_class)("at-sel")
        it = self.items[self.sel]
        many = len(self.outs) > 1
        if self.mode == "desks":
            out = it.get("output") or ""
            head = "Дашборд" if it.get("name") in dash_names() else "Стол %s" % (it.get("idx") or "")
            self.title.set_text(head + (" · " + self.monitor_name(out) if many else ""))
            n = len([w for w in self.desk_wins(it) if not (w.get("app_id") or "").startswith(HIDDEN_APPS)])
            what = "%d %s" % (n, plural(n, "окно", "окна", "окон"))
            if not n and it.get("name") in dash_names():
                what = "виджеты"
            self.sub.set_text(what + "   [~ окна]")
            return
        name, _icon = app_info(it.get("app_id") or "")
        self.title.set_text(it.get("title") or name)
        s = self.ws.get(it.get("workspace_id")) or {}
        where = "стол %s" % s["idx"] if s.get("idx") else ""
        if many and s.get("output"):
            where += (", " if where else "") + self.monitor_name(s["output"])
        self.sub.set_text(name + (" · " + where if where else "") + "   [~ столы]")

    _mon_names = {}

    def monitor_name(self, out):
        if out not in self._mon_names:
            if out.startswith("eDP"):
                self._mon_names[out] = "Laptop"
            else:
                make = ((niri_json("outputs") or {}).get(out) or {}).get("make") or ""
                self._mon_names[out] = "MSI" if "Microstep" in make or "MSI" in make else out
        return self._mon_names[out]

    def where(self, i):
        for g, (_out, idx, _cols) in enumerate(self.groups):
            if i in idx:
                return g, idx.index(i)
        return 0, 0

    def select(self, i):
        self.sel = i
        self.opos = self.order.index(i)
        self.mark()

    def move_row(self, d):
        """Строка вверх/вниз внутри монитора; за краем — по кругу в том же столбце.
        Мониторы друг под другом — за краем на соседний монитор (как h/l в виде «рядом»)."""
        if not self.items:
            return
        g, p = self.where(self.sel)
        _out, idx, n = self.groups[g]
        if self.layout == "stack":
            row, col = divmod(p, n)
            rows = (len(idx) + n - 1) // n
            if not 0 <= row + d < rows:
                _out, idx, n = self.groups[(g + d) % len(self.groups)]
                row = -d if d > 0 else (len(idx) + n - 1) // n
                col = min(col, n - 1)
            k = (row + d) * n + col
            return self.select(idx[min(k, len(idx) - 1)])
        col, rows = p % n, (len(idx) + n - 1) // n
        row = (p // n + d) % rows
        k = row * n + col
        self.select(idx[k] if k < len(idx) else idx[-1])

    def move_col(self, d):
        """Влево/вправо в строке; за краем строки — на соседний монитор, в ту же строку."""
        if not self.items:
            return
        g, p = self.where(self.sel)
        _out, idx, n = self.groups[g]
        row, col = divmod(p, n)
        if 0 <= col + d < min(n, len(idx) - row * n):
            return self.select(idx[p + d])
        if self.layout == "stack":                 # по кругу в своей строке
            width = min(n, len(idx) - row * n)
            return self.select(idx[row * n + (col + d) % width])
        _out, idx, n = self.groups[(g + d) % len(self.groups)]
        row = min(row, (len(idx) - 1) // n)
        width = min(n, len(idx) - row * n)
        self.select(idx[row * n + (0 if d > 0 else width - 1)])

    def move(self, step):
        """Tab — окна по давности, столы — по порядку плиток (19.10.2026)."""
        if not self.items:
            return
        self.select(self.order[(self.opos + step) % len(self.order)])

    def pick(self, i):
        self.sel = i
        self.commit()
        return True

    def hide(self):
        self.shown = False
        self.win.hide()

    def commit(self):
        if not self.shown:
            return
        it = self.items[self.sel] if self.items else None
        self.hide()
        if DRY:
            log("сухой выбор (%s): %s" % (self.mode, (it or {}).get("title") or (it or {}).get("idx")))
            return
        if not it or it.get("is_focused"):
            return
        if self.mode == "desks":
            # на стол — сперва его монитор, потом номер стола: niri сам вернёт фокус окну,
            # которое было на столе активным (окна дашборда фокус не перехватывают)
            cmd = "niri msg action focus-workspace %d" % it["idx"]
            if it.get("output") != self.focused_output():
                cmd = "niri msg action focus-monitor %s && %s" % (it["output"], cmd)
            subprocess.Popen(["sh", "-c", cmd], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if ((self.ws.get(it.get("workspace_id")) or {}).get("name") or "").rstrip("\u2060") == STACK_MIN_DESK:
            # свёрнутое окно стопки (stack_mode.py) — вернуть на общий стол на прежнее место
            subprocess.Popen([sys.executable, os.path.join(HERE, "stack_mode.py"), "unmin", str(it["id"])],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(it["id"])],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ── клавиатура ──
    def on_focus_in(self, *_a):
        # ТОЛЬКО отметка. Спросить здесь состояние клавиш (Gdk.Keymap) нельзя: focus-in
        # приходит прямо внутри win.show(), пока GTK разбирает сообщения Wayland, и вызов
        # повисал навсегда (05.10.2026, Alt+Tab «вообще не работает»). Alt проверяет
        # таймер watch_alt — уже после показа.
        self.focused_in = True
        return False

    def alt_down(self):
        st = Gdk.Keymap.get_for_display(Gdk.Display.get_default()).get_modifier_state()
        return bool(st & Gdk.ModifierType.MOD1_MASK)

    def watch_alt(self):
        """Отпустили Alt — выбор. Состояние клавиш верно, только когда у окна фокус;
        если фокуса так и не дали (1,5 с), не висеть — закрыть с выбором."""
        if not self.shown:
            return False
        if self.focused_in:
            if not self.alt_down():
                self.commit()
                return False
        elif not self.reshown and time.monotonic() - self.opened_at > 0.4:
            # фокус не пришёл — показать заново: niri отдаёт клавиатуру при новом показе
            self.reshown = True
            log("фокус не пришёл за 0,4 с — показываю заново")
            self.win.hide()
            self.win.show()
        elif time.monotonic() - self.opened_at > 1.5:
            log("фокус клавиатуры не пришёл — закрываю с выбором")
            self.commit()
            return False
        return True

    def on_key_release(self, _w, ev):
        if ev.keyval in (Gdk.KEY_Alt_L, Gdk.KEY_Alt_R, Gdk.KEY_Meta_L, Gdk.KEY_Meta_R):
            self.commit()
        return True

    def on_key(self, _w, ev):
        k = ev.keyval
        if k == Gdk.KEY_Escape:
            self.hide()
        # h/j/k/l как в nvim (05.10.2026); на русской раскладке те же клавиши — р/о/л/д
        # Tab — по давности; h/l и стрелки — по месту, за краем — соседний монитор (19.10.2026)
        # и WASD как h/l/j/k: a/d — влево/вправо, w/s — вверх/вниз (21.10.2026); ф/в/ц/ы — русская
        elif k == Gdk.KEY_Tab:
            self.move(1)
        elif k == Gdk.KEY_ISO_Left_Tab:
            self.move(-1)
        elif k in (Gdk.KEY_Right, Gdk.KEY_l, Gdk.KEY_L, Gdk.KEY_Cyrillic_de, Gdk.KEY_Cyrillic_DE,
                   Gdk.KEY_d, Gdk.KEY_D, Gdk.KEY_Cyrillic_ve, Gdk.KEY_Cyrillic_VE):
            self.move_col(1)
        elif k in (Gdk.KEY_Left, Gdk.KEY_h, Gdk.KEY_H, Gdk.KEY_Cyrillic_er, Gdk.KEY_Cyrillic_ER,
                   Gdk.KEY_a, Gdk.KEY_A, Gdk.KEY_Cyrillic_ef, Gdk.KEY_Cyrillic_EF):
            self.move_col(-1)
        elif k in (Gdk.KEY_Down, Gdk.KEY_j, Gdk.KEY_J, Gdk.KEY_Cyrillic_o, Gdk.KEY_Cyrillic_O,
                   Gdk.KEY_s, Gdk.KEY_S, Gdk.KEY_Cyrillic_yeru, Gdk.KEY_Cyrillic_YERU):
            self.move_row(1)
        elif k in (Gdk.KEY_Up, Gdk.KEY_k, Gdk.KEY_K, Gdk.KEY_Cyrillic_el, Gdk.KEY_Cyrillic_EL,
                   Gdk.KEY_w, Gdk.KEY_W, Gdk.KEY_Cyrillic_tse, Gdk.KEY_Cyrillic_TSE):
            self.move_row(-1)
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.commit()
        elif k in (Gdk.KEY_grave, Gdk.KEY_asciitilde, Gdk.KEY_Cyrillic_io, Gdk.KEY_Cyrillic_IO):
            self.toggle_mode()
        return True

    def toggle_mode(self):
        """` / ~ (на русской — ё): окна ↔ столы (19.10.2026). Выбор переходит на «то же
        место»: из окна — на его стол, со стола — на его активное окно."""
        if stack_active():
            return                             # в стопке столов нет — только окна
        cur = self.items[self.sel] if self.items else {}
        if self.mode == "windows":
            self.mode, keep = "desks", cur.get("workspace_id")
        else:
            self.mode, keep = "windows", cur.get("active_window_id")
        if not self.build(0, keep):            # окон нет — остаться на столах
            self.mode = "desks"
            self.build(0, None)
        save_mode(self.mode)
        self.win.resize(1, 1)                  # панель сжимается под новый режим

    # ── вид ──
    def apply_css(self):
        style = read_style()
        try:
            stamp = os.stat(os.path.expanduser("~/.cache/matugen/colors.json")).st_mtime
        except OSError:
            stamp = 0
        key = (style, stamp)
        if key == self.css_key:
            return
        self.css_key = key
        c = dict(xp_calendar.colors(style))
        c["font"] = xp_calendar.FONT
        c["tile"] = TILE
        self.acc = Gdk.RGBA()
        self.acc.parse(c.get("acc") or c.get("accent") or "#89a2f6")
        css = css_for(style, c)
        prov = Gtk.CssProvider()
        prov.load_from_data(css.encode())
        screen = Gdk.Screen.get_default()
        if self.provider is not None:
            Gtk.StyleContext.remove_provider_for_screen(screen, self.provider)
        Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        self.provider = prov


def css_for(style, c):
    common = """
    window { background-color: transparent; }
    .at-box { font-family: %(font)s; }
    .at-grid flowboxchild { padding: 0; margin: 0; background: transparent; border-radius: 0; }
    .at-title { font-size: 16px; margin-top: 8px; }
    .at-sub { font-size: 12px; margin-top: 2px; }
    .at-cap { font-size: 12px; opacity: 0.75; margin-bottom: 2px; }
    .at-grid flowboxchild.at-sel .at-cap { opacity: 1; }
    .at-tile { padding-top: 4px; }
    /* 19.10.2026: монитор над своей группой (тот, где фокус, — ярче) и плитки столов */
    .at-head { font-size: 12px; margin-bottom: 2px; color: %(dim)s; }
    .at-head.at-here { color: %(text)s; }
    .at-tile.at-desk { padding: 4px 4px 2px 4px; }
    """ % c
    if FIT:
        common += ".at-title { margin-top: 6px; }\n"
    if style == "skeet":
        dark = ", ".join(xp_calendar._mix(x, "#000000", 0.55) for x in c["strip"])
        c = dict(c, strip=", ".join(c["strip"]), strip_d=dark,
                 line1_on=xp_calendar._mix(c["line1"], c["acc"], 0.45),
                 sel_hi=xp_calendar._mix(c["field_l"], c["acc"], 0.12))
        return common + """
    .at-box {
        background-color: %(bg)s; color: %(text)s;
        background-image: linear-gradient(to right, %(strip)s), linear-gradient(to right, %(strip_d)s);
        background-size: 100%% 1px, 100%% 1px; background-repeat: no-repeat, no-repeat;
        background-position: 0 6px, 0 7px;
        box-shadow: inset 0 0 0 6px %(line3)s, inset 0 0 0 5px %(line1_on)s,
                    inset 0 0 0 4px %(line2)s, inset 0 0 0 1px %(line1_on)s;
        padding: 16px 16px 12px 16px;
    }
    /* плитки — как кнопки Skeet в Настройках (15.10.2026, просьба: «квадраты … более похоже на
       стиль Skeet»): тёмная рамка line3 + светлая внутренняя линия, поле градиентом сверху
       вниз; выбранная — внутренняя линия акцентом, полоса палитры сверху, подпись акцентом */
    /* невыбранные — без квадратов (просьба: «квадратики у тех окон, которые не выбраны, убери») */
    .at-grid flowboxchild {
        border: 1px solid transparent; box-shadow: none; background-image: none;
    }
    .at-grid flowboxchild.at-sel {
        border: 1px solid %(line3)s; box-shadow: inset 0 0 0 1px %(acc)s, inset 0 -3px 0 0 %(acc)s;
        background-color: %(field_l)s;
        background-image: linear-gradient(to right, %(strip)s), linear-gradient(to right, %(strip_d)s),
                          linear-gradient(to bottom, %(sel_hi)s, %(field_l)s);
        background-size: 100%% 1px, 100%% 1px, 100%% 100%%;
        background-position: 0 1px, 0 2px, 0 0;
        background-repeat: no-repeat;
    }
    .at-grid flowboxchild.at-sel .at-cap { color: %(acc_l)s; }
    .at-head.at-here { color: %(acc_l)s; }
    .at-cap { color: %(dim)s; }
    .at-tile { padding-top: 6px; }
    .at-title { color: %(acc_l)s; }
    .at-sub { color: %(dim)s; }
    """ % c
    if style == "beta":
        return common + """
    .at-box {
        background-color: %(bg)s; color: %(text)s;
        border: 1px solid %(frame)s; padding: 14px 16px 12px 16px;
        box-shadow: 0 0 0 1px rgba(0,0,0,0.5); margin: 2px;
    }
    .at-grid flowboxchild { border: 1px solid transparent; }
    .at-grid flowboxchild.at-sel { border: 1px solid %(acc)s; background-color: %(sel)s; }
    .at-title { color: %(text)s; }
    .at-sub { color: %(dim)s; }
    """ % c
    return common + """
    .at-box {
        background-color: %(win_bg)s; color: %(text)s;
        border: 3px solid %(frame)s; padding: 12px 14px 10px 14px;
        box-shadow: 0 0 0 1px rgba(0,0,0,0.6); margin: 2px;
    }
    .at-grid flowboxchild { border: 2px solid transparent; }
    .at-grid flowboxchild.at-sel { border: 2px solid %(sel_bg)s; background-color: %(row)s; }
    .at-title { color: %(text)s; font-weight: bold; }
    .at-sub { color: %(dim)s; }
    """ % c


def main():
    import faulthandler
    import signal
    try:
        faulthandler.register(signal.SIGUSR1, file=open(LOG, "a"), all_threads=True)
    except (OSError, AttributeError):
        pass
    try:
        with open(PIDF, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass
    sw = Switcher()
    first = sys.argv[2] if len(sys.argv) > 2 else None
    if first in ("next", "prev"):
        # первый показ сразу после старта клавиатуру не получал (05.10.2026) — подождать,
        # пока окно и соединение с niri готовы
        GLib.timeout_add(250, lambda: (sw.command(first), False)[1])
    log("запущен, pid %d" % os.getpid())
    Gtk.main()


if __name__ == "__main__":
    main()
