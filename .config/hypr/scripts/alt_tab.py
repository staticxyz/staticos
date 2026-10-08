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
COLS = 7
ICON = 40
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

STYLES = ("default", "skeet", "beta")


def read_style():
    try:
        v = open(STYLE_FILE).read().strip()
        return v if v in STYLES else "default"
    except OSError:
        return "default"


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
    """Окно игры Steam (06.10.2026, Просьба: «у КС иконка как у картинки»): у gamescope и
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


# ── окна терминала: что в них запущено (05.10.2026, Просьба: «все kitty — один значок,
# не понимаю, где что») — значок программы по заголовку и короткая подпись ──
TERMINALS = {"kitty", "foot", "alacritty", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}
PROGRAM_ICONS = {"btop": "btop", "btop++": "btop", "htop": "htop", "top": "utilities-system-monitor",
                 "nvim": "nvim", "vim": "vim", "vi": "vim", "python": "python", "python3": "python",
                 "ipython": "python", "git": "git", "lazygit": "git", "yazi": "yazi", "node": "node",
                 "java": "java", "man": "accessories-text-editor", "nano": "accessories-text-editor"}
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
        return PROGRAM_ICONS.get(base.lower()), short(rest.split(" · ")[0])
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
        self.items = []
        self.sel = 0
        self.scope = None             # None — все мониторы, иначе имя выхода (клавиша `)
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
        self.grid = Gtk.FlowBox()
        self.grid.set_selection_mode(Gtk.SelectionMode.NONE)
        self.grid.set_homogeneous(True)
        self.grid.set_max_children_per_line(COLS)
        self.grid.set_min_children_per_line(1)
        self.grid.set_column_spacing(4)
        self.grid.set_row_spacing(4)
        self.grid.get_style_context().add_class("at-grid")
        self.title = Gtk.Label(xalign=0.5)
        self.title.set_ellipsize(Pango.EllipsizeMode.END)
        self.title.get_style_context().add_class("at-title")
        self.sub = Gtk.Label(xalign=0.5)
        self.sub.set_ellipsize(Pango.EllipsizeMode.END)
        self.sub.get_style_context().add_class("at-sub")
        # Ширину панели задаёт только сетка плиток (05.10.2026, Просьба: «при переходах размер
        # alt+tab меняется на пару пикселей»): у меток с многоточием «желаемая» ширина — весь
        # текст, и длинное имя окна раздвигало панель. max_width_chars 1 — желаемая ширина
        # минимальна, метка растягивается по ширине панели и сокращается многоточием.
        for lab in (self.title, self.sub):
            lab.set_max_width_chars(1)
            lab.set_hexpand(True)
            lab.set_single_line_mode(True)
        self.box.pack_start(self.grid, False, False, 0)
        self.box.pack_start(self.title, False, False, 0)
        self.box.pack_start(self.sub, False, False, 0)
        self.win.add(self.box)
        self.box.show_all()

        self.load_initial()
        self.follow_niri()
        self.open_fifo()
        GLib.timeout_add_seconds(5, self.keep_fifo)
        GLib.idle_add(self.warm)

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
        for s in niri_json("workspaces") or []:
            self.ws[s["id"]] = s

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
                self.windows[w["id"]] = w
            elif "WindowClosed" in ev:
                self.windows.pop(ev["WindowClosed"]["id"], None)
            elif "WindowFocusChanged" in ev:
                fid = ev["WindowFocusChanged"]["id"]
                for w in self.windows.values():
                    w["is_focused"] = w["id"] == fid
            elif "WindowFocusTimestampChanged" in ev:
                d = ev["WindowFocusTimestampChanged"]
                if d.get("id") in self.windows:
                    self.windows[d["id"]]["focus_timestamp"] = d.get("focus_timestamp")
            elif "WorkspacesChanged" in ev:
                self.ws = {s["id"]: s for s in ev["WorkspacesChanged"]["workspaces"]}
            elif "WorkspaceActivated" in ev:
                d = ev["WorkspaceActivated"]
                s = self.ws.get(d["id"])
                if s:
                    for o in self.ws.values():
                        if o.get("output") == s.get("output"):
                            o["is_active"] = o["id"] == s["id"]
                        if d.get("focused"):
                            o["is_focused"] = o["id"] == s["id"]
        except Exception:
            log("event: " + traceback.format_exc(limit=2))
        return False

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
        outs = niri_json("outputs") or {}
        lg = (outs.get(name) or {}).get("logical") or {}
        d = Gdk.Display.get_default()
        for i in range(d.get_n_monitors()):
            g = d.get_monitor(i).get_geometry()
            if g.x == lg.get("x") and g.y == lg.get("y"):
                return d.get_monitor(i)
        return None

    def open(self, step):
        # Два режима (05.10.2026, Просьба: «окна этого монитора и другого, только 2 режима»):
        # открывается с окнами монитора в фокусе, ` — окна другого монитора и обратно.
        self.scope = self.focused_output()
        if not self.build(step):
            self.scope = None
            log("окон нет — нечего показывать")
            return
        self.show()

    def build(self, step):
        wins = [w for w in self.windows.values()
                if not (w.get("app_id") or "").startswith(HIDDEN_APPS)]
        if self.scope:
            wins = [w for w in wins if (self.ws.get(w.get("workspace_id")) or {}).get("output") == self.scope]
        if not wins:
            return False
        wins.sort(key=lambda w: (not w.get("is_focused"), -ts(w)))
        self.items = wins
        self.sel = (step if step > 0 else len(wins) - 1) % len(wins) if len(wins) > 1 else 0
        self.apply_css()
        for ch in list(self.grid.get_children()):
            self.grid.remove(ch)
        self.tiles = []
        theme = Gtk.IconTheme.get_default()
        for i, w in enumerate(wins):
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
            tile.connect("button-press-event", lambda _t, _e, k=i: self.pick(k))
            self.grid.add(tile)
            self.tiles.append(tile)
        n = min(COLS, len(wins))
        self.grid.set_min_children_per_line(n)     # иначе FlowBox ставит по одному в строку
        self.grid.set_max_children_per_line(n)
        self.grid.show_all()
        self.mark()
        return True

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
        for i, t in enumerate(self.tiles):
            ctx = t.get_parent().get_style_context() if t.get_parent() else t.get_style_context()
            (ctx.add_class if i == self.sel else ctx.remove_class)("at-sel")
        w = self.items[self.sel]
        name, _icon = app_info(w.get("app_id") or "")
        self.title.set_text(w.get("title") or name)
        s = self.ws.get(w.get("workspace_id")) or {}
        where = "стол %s" % s["idx"] if s.get("idx") else ""
        if not self.scope and s.get("output") and s.get("output") != self.focused_output():
            where += (", " if where else "") + s["output"]
        scope = "все мониторы" if not self.scope else self.monitor_name(self.scope)
        self.sub.set_text(name + (" · " + where if where else "") + "   [` " + scope + "]")

    _mon_names = {}

    def monitor_name(self, out):
        if out not in self._mon_names:
            if out.startswith("eDP"):
                self._mon_names[out] = "ноутбук"
            else:
                make = ((niri_json("outputs") or {}).get(out) or {}).get("make") or ""
                self._mon_names[out] = "MSI" if "Microstep" in make or "MSI" in make else out
        return self._mon_names[out]

    def move_row(self, d):
        """Строка вверх/вниз в сетке; за краем — по кругу в том же столбце."""
        if not self.items:
            return
        n = min(COLS, len(self.items))
        col, rows = self.sel % n, (len(self.items) + n - 1) // n
        row = (self.sel // n + d) % rows
        i = row * n + col
        self.sel = i if i < len(self.items) else len(self.items) - 1
        self.mark()

    def move(self, step):
        if not self.items:
            return
        self.sel = (self.sel + step) % len(self.items)
        self.mark()

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
        w = self.items[self.sel] if self.items else None
        self.hide()
        if DRY:
            log("сухой выбор: %s" % (w or {}).get("title"))
            return
        if w and not w.get("is_focused"):
            subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(w["id"])],
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
        elif k in (Gdk.KEY_Tab, Gdk.KEY_Right, Gdk.KEY_l, Gdk.KEY_L, Gdk.KEY_Cyrillic_de, Gdk.KEY_Cyrillic_DE):
            self.move(1)
        elif k in (Gdk.KEY_ISO_Left_Tab, Gdk.KEY_Left, Gdk.KEY_h, Gdk.KEY_H,
                   Gdk.KEY_Cyrillic_er, Gdk.KEY_Cyrillic_ER):
            self.move(-1)
        elif k in (Gdk.KEY_Down, Gdk.KEY_j, Gdk.KEY_J, Gdk.KEY_Cyrillic_o, Gdk.KEY_Cyrillic_O):
            self.move_row(1)
        elif k in (Gdk.KEY_Up, Gdk.KEY_k, Gdk.KEY_K, Gdk.KEY_Cyrillic_el, Gdk.KEY_Cyrillic_EL):
            self.move_row(-1)
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.commit()
        elif k in (Gdk.KEY_grave, Gdk.KEY_asciitilde, Gdk.KEY_Cyrillic_io, Gdk.KEY_Cyrillic_IO):
            self.next_scope()
        return True

    def next_scope(self):
        """` (на русской раскладке — ё): этот монитор ↔ другой (05.10.2026)."""
        outs = sorted({s.get("output") for s in self.ws.values() if s.get("output")},
                      key=lambda o: (not o.startswith("eDP"), o))
        order = outs or [None]
        i = order.index(self.scope) if self.scope in order else 0
        for _ in order:                       # пропустить мониторы, где окон нет
            i = (i + 1) % len(order)
            self.scope = order[i]
            if self.build(1):
                return
        self.scope = None
        self.build(1)

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
    """ % c
    if FIT:
        common += ".at-title { margin-top: 6px; }\n"
    if style == "skeet":
        dark = ", ".join(xp_calendar._mix(x, "#000000", 0.55) for x in c["strip"])
        c = dict(c, strip=", ".join(c["strip"]), strip_d=dark,
                 line1_on=xp_calendar._mix(c["line1"], c["acc"], 0.45))
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
    .at-grid flowboxchild { border: 1px solid transparent; }
    .at-grid flowboxchild.at-sel { border: 1px solid %(acc)s; background-color: %(field_l)s; }
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
