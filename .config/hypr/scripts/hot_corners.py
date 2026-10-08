#!/usr/bin/env python3
"""Горячие углы для niri: увёл курсор в угол экрана — выполнилось действие.

В каждом углу, которому назначено действие, на каждом мониторе висит крошечная
(SIZE×SIZE px) прозрачная поверхность layer-shell в слое OVERLAY с exclusive
zone -1 — поверх бара и окон. Курсор вошёл в неё и продержался HOLD_MS —
выполняется действие; повторно — только после того, как курсор ушёл из угла
(без автоповтора). niri присылает enter только при движении мыши — тут это
как раз то, что нужно.

Не срабатывает поверх игр: если окно в фокусе на этом мониторе развёрнуто на
весь экран (в JSON niri 26.04 нет поля is_fullscreen — сравниваем размер окна
с размером монитора) или запущена игра (процесс cs2 или любая игра Steam, см.
game_guard.py).

Настройка — ~/.config/hypr/state/hot-corners.json, например
    {"top-right": "notifications"}
Работающий экземпляр перечитывает его по SIGHUP (его шлёт CLI) и сам раз в
несколько секунд по времени изменения файла.

    hot_corners.py                      запустить (один экземпляр; второй тихо выходит)
    hot_corners.py --dry-run            то же, но действия только печатаются
    hot_corners.py list                 углы, действия, работает ли
    hot_corners.py set <угол> <действие>
    hot_corners.py off <угол>
    hot_corners.py check                что сейчас мешает срабатыванию (игра, полный экран)

Углы: top-left, top-right, bottom-left, bottom-right.
Действия: notifications, overview, control-center, none.
"""
import fcntl
import json
import os
import signal
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/hot-corners.json")
LOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-hot-corners.lock")
NAMESPACE = "jarvis-hot-corner"

SIZE = 2           # сторона поверхности, px: только самый угол, мимо кнопки питания бара
HOLD_MS = 150      # сколько держать курсор в углу (как delay_ms у Noctalia)
COOLDOWN_MS = 700  # после срабатывания: не ловить случайный повторный вход
POLL_S = 3         # проверка mtime настроек

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
ACTIONS = {
    "notifications": ["swaync-client", "-t", "-sw"],
    "overview": ["niri", "msg", "action", "toggle-overview"],
    "control-center": ["python3", os.path.join(HERE, "control_center.py"), "--center"],
    "none": None,
}
DEFAULT = {"top-right": "notifications"}


# ---------------------------------------------------------------- настройки

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


def load_config():
    try:
        with open(STATE) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("не словарь")
    except FileNotFoundError:
        return dict(DEFAULT)
    except (OSError, ValueError) as e:
        print("hot_corners: плохой %s (%s), беру по умолчанию" % (STATE, e), file=sys.stderr)
        return dict(DEFAULT)
    return {c: a for c, a in data.items() if c in CORNERS and a in ACTIONS}


def save_config(cfg):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({c: cfg[c] for c in CORNERS if c in cfg}, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, STATE)


def running_pid():
    """PID работающего экземпляра или None (по файлу блокировки и /proc)."""
    try:
        pid = int(open(LOCK).read().strip() or 0)
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
    except (OSError, ValueError):
        return None
    if any(a.endswith(b"hot_corners.py") for a in argv):
        return pid
    return None


# ---------------------------------------------------------------- помехи

def niri_json(*what):
    try:
        out = subprocess.run(["niri", "msg", "-j", *what], capture_output=True,
                             text=True, timeout=1.5).stdout
        return json.loads(out) if out.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def fullscreen_output():
    """Имя монитора, где окно в фокусе занимает весь экран, иначе None.

    В niri 26.04 у окна нет is_fullscreen, поэтому сравниваем размер окна
    (layout.window_size) с логическим размером его монитора: развёрнутое на
    весь экран окно закрывает и бар, обычное или «maximize» — нет.
    """
    win = niri_json("focused-window")
    if not win:
        return None
    wss = niri_json("workspaces") or []
    outs = niri_json("outputs") or {}
    out = next((w.get("output") for w in wss if w.get("id") == win.get("workspace_id")), None)
    logical = (outs.get(out) or {}).get("logical") or {}
    size = (win.get("layout") or {}).get("window_size") or [0, 0]
    if logical and size[0] >= logical.get("width", 1 << 30) and size[1] >= logical.get("height", 1 << 30):
        return out
    return None


def game_running():
    if subprocess.run(["pgrep", "-x", "cs2"], stdout=subprocess.DEVNULL).returncode == 0:
        return "cs2"
    try:
        sys.path.insert(0, HERE)
        import game_guard
        app = game_guard.running_app_id()
        return "steam AppId=%s" % app if app else None
    except Exception:
        return None


def blocker(output=None):
    """Почему сейчас не срабатывать (строка) или None."""
    g = game_running()
    if g:
        return "идёт игра (%s)" % g
    fs = fullscreen_output()
    if fs and (output is None or fs == output):
        return "окно на весь экран на %s" % fs
    return None


# ---------------------------------------------------------------- срабатывание

class Trigger:
    """Логика угла без GTK: вход → задержка → действие, повтор только после выхода.

    Таймеры приходят снаружи (schedule/cancel), чтобы её можно было проверить
    без экрана.
    """

    def __init__(self, corner, output, get_action, schedule, cancel, dry_run=False, log=print):
        self.corner, self.output = corner, output
        self.get_action, self.schedule, self.cancel = get_action, schedule, cancel
        self.dry_run, self.log = dry_run, log
        self.inside = False
        self.armed = True
        self.timer = None
        self.cooling = False

    def enter(self):
        self.inside = True
        if self.armed and not self.cooling and self.timer is None:
            self.timer = self.schedule(HOLD_MS, self.fire)

    def leave(self):
        self.inside = False
        self.armed = True
        if self.timer is not None:
            self.cancel(self.timer)
            self.timer = None

    def fire(self):
        self.timer = None
        if not (self.inside and self.armed):
            return False
        self.armed = False               # до выхода из угла больше не срабатываем
        name = self.get_action(self.corner)
        cmd = ACTIONS.get(name)
        if not cmd:
            return False
        why = blocker(self.output)
        if why:
            self.log("hot_corners: %s %s пропущен: %s" % (self.output or "?", self.corner, why))
            return False
        if self.dry_run:
            self.log("hot_corners: [dry-run] %s %s → %s" % (self.output or "?", self.corner, " ".join(cmd)))
        else:
            try:
                subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            except OSError as e:
                self.log("hot_corners: %s: %s" % (cmd[0], e))
        self.cooling = True
        self.schedule(COOLDOWN_MS, self._cool)
        return False

    def _cool(self):
        self.cooling = False
        return False


# ---------------------------------------------------------------- GTK

def run(dry_run=False):
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("hot_corners: уже запущен (pid %s)" % running_pid(), file=sys.stderr)
        return 0
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()

    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)  # GLib.unix_signal_add
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell

    E = GtkLayerShell.Edge
    EDGES = {
        "top-left": (E.TOP, E.LEFT), "top-right": (E.TOP, E.RIGHT),
        "bottom-left": (E.BOTTOM, E.LEFT), "bottom-right": (E.BOTTOM, E.RIGHT),
    }
    state = {"cfg": load_config(), "mtime": _mtime(), "wins": []}

    def connectors(display):
        """Gdk-монитор → имя выхода niri (по модели, иначе по порядку, как в dock.py)."""
        outs = niri_json("outputs") or {}
        by_model = {(o.get("model") or ""): c for c, o in outs.items()}
        res = []
        for i in range(display.get_n_monitors()):
            m = display.get_monitor(i)
            c = by_model.get(m.get_model() or "")
            if not c:
                c = sorted(outs)[i] if i < len(outs) else None
            res.append((m, c))
        return res

    def schedule(ms, fn):
        return GLib.timeout_add(ms, fn)

    def make(monitor, output, corner):
        w = Gtk.Window()
        w.set_title(NAMESPACE)
        w.set_app_paintable(True)
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(w, monitor)
        for e in EDGES[corner]:
            GtkLayerShell.set_anchor(w, e, True)
        GtkLayerShell.set_exclusive_zone(w, -1)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        w.set_size_request(SIZE, SIZE)
        w.set_default_size(SIZE, SIZE)
        w.set_resizable(False)

        def draw(_w, cr):
            import cairo
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            return True
        w.connect("draw", draw)

        t = Trigger(corner, output, lambda c: state["cfg"].get(c, "none"),
                    schedule, GLib.source_remove, dry_run=dry_run)
        w.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        w.connect("enter-notify-event", lambda *_: (t.enter(), False)[1])
        w.connect("leave-notify-event", lambda *_: (t.leave(), False)[1])
        w.trigger = t
        w.show_all()
        return w

    def rebuild(*_):
        for w in state["wins"]:
            w.destroy()
        state["wins"] = []
        display = Gdk.Display.get_default()
        active = [c for c in CORNERS if ACTIONS.get(state["cfg"].get(c, "none"))]
        for mon, out in connectors(display):
            for corner in active:
                state["wins"].append(make(mon, out, corner))
        print("hot_corners: %s на %d мониторах" % (", ".join(
            "%s=%s" % (c, state["cfg"][c]) for c in active) or "все углы выключены",
            display.get_n_monitors()), flush=True)
        return False

    def reload():
        state["cfg"] = load_config()
        state["mtime"] = _mtime()
        rebuild()
        return True

    def poll():
        if _mtime() != state["mtime"]:
            reload()
        return True

    display = Gdk.Display.get_default()
    # Монитор подключили/отключили — пересобрать (с задержкой: niri не сразу знает выход).
    display.connect("monitor-added", lambda *_: GLib.timeout_add(500, rebuild))
    display.connect("monitor-removed", lambda *_: GLib.timeout_add(500, rebuild))
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, reload)
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
    GLib.timeout_add_seconds(POLL_S, poll)
    rebuild()
    Gtk.main()
    return 0


def _mtime():
    try:
        return os.stat(STATE).st_mtime_ns
    except OSError:
        return None


# ---------------------------------------------------------------- CLI

def notify_running():
    pid = running_pid()
    if pid:
        os.kill(pid, signal.SIGHUP)
    return pid


def main(argv):
    if not argv or argv[0] in ("run", "--dry-run"):
        return run(dry_run="--dry-run" in argv)
    cmd = argv[0]
    if cmd == "list":
        cfg = load_config()
        for c in CORNERS:
            a = cfg.get(c, "none")
            print("%-13s %-15s %s" % (c, a, " ".join(ACTIONS[a] or [])))
        pid = running_pid()
        print("работает: %s" % ("да, pid %d" % pid if pid else "нет"))
        print("действия: %s" % ", ".join(ACTIONS))
        return 0
    if cmd in ("set", "off"):
        if cmd == "set" and len(argv) != 3 or cmd == "off" and len(argv) != 2:
            print("hot_corners.py set <угол> <действие> | off <угол>", file=sys.stderr)
            return 2
        corner = argv[1]
        action = argv[2] if cmd == "set" else "none"
        if corner not in CORNERS:
            print("угол: %s" % ", ".join(CORNERS), file=sys.stderr)
            return 2
        if action not in ACTIONS:
            print("действие: %s" % ", ".join(ACTIONS), file=sys.stderr)
            return 2
        cfg = load_config()
        if action == "none":
            cfg.pop(corner, None)
        else:
            cfg[corner] = action
        save_config(cfg)
        pid = notify_running()
        print("%s → %s%s" % (corner, action, " (pid %d перечитал)" % pid if pid else ""))
        return 0
    if cmd == "check":
        print(blocker() or "ничто не мешает")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
