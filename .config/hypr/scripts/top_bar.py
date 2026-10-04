#!/usr/bin/env python3
"""Верхний бар: всегда / при наведении / выключен — и где показывать столы. 03.10.2026.

    top_bar.py                     сторож наведения (автозапуск niri; работает только в режиме hover)
    top_bar.py get                 always | hover | off
    top_bar.py set always|hover|off   как показывать верхний бар
    top_bar.py ws                  top | bottom — где список столов
    top_bar.py ws top|bottom       переключить (bottom — в нижней XP-панели, между «Пуском» и окнами)
    top_bar.py apply               применить заново (пересобрать конфиг бара, перезапустить панели)
    top_bar.py opacity always|hover [20–100|default]   плотность фона бара (Настройки)
    top_bar.py blur [on|off]       размытие под баром в режиме «всегда» (Настройки)

пользователь (03.10.2026): «верхний бар пусть умеет исчезать и появляться по наведению —
снизу такое уже есть»; «хочу выбор: столы и окна только в панели снизу (XP) — тогда
верхний waybar исчезает, а столы появляются снизу»; «и ещё выбор: обе панели, столы —
в нижней, в верхней всё остальное, и она прячется и появляется при наведении».

Два независимых выбора:
  * бар сверху: always — как было; hover — спрятан, выезжает при наведении на верхний
    край экрана и лежит ПОВЕРХ окон (место под себя не резервирует — окна занимают
    экран до самого верха); off — бара нет вовсе (waybar не запускается);
  * столы: top — в верхнем баре, bottom — в нижней XP-панели (xpbar.py). Без верхнего
    бара (off) столы всегда внизу; нижняя панель при этом включается сама (XP, «всегда»).
Окна выравниваются сами: niri перекладывает их, когда панель перестаёт резервировать место.

Как устроено «при наведении». У waybar своего автоскрытия нет, зато он прячется и
показывается по SIGUSR1 и умеет стартовать спрятанным (start_hidden — это и
"exclusive": false дописывает в конфиг ~/.config/niri/scripts/waybar_niri.py). Сторож
держит по две невидимые полоски на монитор: верхнюю (2 px у края; углы свободны —
там «горячие углы») — навели → бар показать; и нижнюю (под баром) — пересекли её,
уходя вниз → бар спрятать. Раз в 3 с, пока бар показан, сверяется, где мышь на самом
деле (проба прозрачным слоем): ушла вниз мимо полоски (например, через попап) — бар
прячется; пока открыт попап бара — не трогаем. В игре (cs2, gamescope) полосок нет.
"""
import json
import os
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state")
MODE = os.path.join(STATE, "top-bar")
WS = os.path.join(STATE, "ws-place")
MODES = ("always", "hover", "off")
GEN = os.path.expanduser("~/.config/niri/scripts/waybar_niri.py")
BARFIX = os.path.expanduser("~/.local/bin/barfix")
GAMES = (b"cs2", b"gamescope")


def _read(path, allowed, default):
    try:
        v = open(path).read().strip()
        return v if v in allowed else default
    except OSError:
        return default


def _write(path, value):
    os.makedirs(STATE, exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(value + "\n")
    os.replace(path + ".tmp", path)


def get_mode():
    return _read(MODE, MODES, "always")


def ws_place():
    """Где столы на самом деле: без верхнего бара — только внизу."""
    return "bottom" if get_mode() == "off" else _read(WS, ("top", "bottom"), "top")


def session_pids(name):
    """PID процессов ЭТОГО сеанса (бар соседнего сеанса не трогаем)."""
    me = ("WAYLAND_DISPLAY=%s" % os.environ.get("WAYLAND_DISPLAY", "")).encode()
    out = []
    for p in subprocess.run(["pgrep", "-x", name], capture_output=True, text=True).stdout.split():
        try:
            if me in open("/proc/%s/environ" % p, "rb").read().split(b"\0"):
                out.append(int(p))
        except OSError:
            pass
    return out


def daemon_pids():
    me, out = os.getpid(), []
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and b"python" in os.path.basename(argv[0]) \
                    and os.path.basename(argv[1]) == b"top_bar.py" and (len(argv) == 2 or argv[2] == b""):
                out.append(int(p))
    return out


def spawn_detached(*argv):
    if os.environ.get("NIRI_SOCKET"):
        r = subprocess.run(["niri", "msg", "action", "spawn", "--", *argv], capture_output=True)
        if r.returncode == 0:
            return
    subprocess.Popen(list(argv), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


BLUR_KDL = os.path.expanduser("~/.config/niri/cfg/waybar-blur.kdl")


BLUR_OFF = os.path.join(STATE, "bar-blur-off")            # «Размытие под баром» выключено
OPACITY_FILE = {"always": os.path.join(STATE, "bar-opacity-always"),
                "hover": os.path.join(STATE, "bar-opacity-hover")}
OPACITY_DEFAULT = {"always": None, "hover": 100}             # None — как задал вид бара (≈88)
LOOKS = os.path.expanduser("~/.config/waybar/looks")


def blur_on():
    return not os.path.exists(BLUR_OFF)


def blur_rule(mode):
    """Размытие под баром — переключатель в Настройках, и никогда в «при наведении»:
    спрятанный waybar остаётся прозрачной поверхностью, и niri размывал под ним обои
    (сверху висела размытая полоса, 04.10.2026). Силу размытия niri задаёт одну на всю
    систему (cfg/blur.kdl), отдельно для бара её не бывает — поэтому здесь только вкл/выкл."""
    if mode == "hover" or not blur_on():
        body = "// Пишет top_bar.py (blur_rule): без размытия под баром (%s).\n" % (
            "режим «при наведении»" if mode == "hover" else "выключено в Настройках")
    else:
        body = ("// Пишет top_bar.py (blur_rule): размытие под верхним баром.\n"
                "layer-rule {\n    match namespace=r#\"^waybar$\"#\n"
                "    background-effect {\n        blur true\n    }\n}\n")
    try:
        if open(BLUR_KDL).read() == body:
            return
    except OSError:
        pass
    with open(BLUR_KDL + ".tmp", "w") as f:
        f.write(body)
    os.replace(BLUR_KDL + ".tmp", BLUR_KDL)       # niri перечитает включённый файл сам


def get_opacity(kind):
    """Плотность фона бара в процентах для режима kind (always|hover); None — как у вида."""
    try:
        return max(20, min(100, int(open(OPACITY_FILE[kind]).read().strip())))
    except (OSError, ValueError):
        return OPACITY_DEFAULT[kind]


def set_opacity(kind, value):
    if value in (None, "default"):
        try:
            os.remove(OPACITY_FILE[kind])
        except OSError:
            pass
    else:
        _write(OPACITY_FILE[kind], str(max(20, min(100, int(float(value))))))


def look_name():
    try:
        return os.path.basename(os.readlink(os.path.join(LOOKS, "current.css")))[:-4]
    except OSError:
        return ""


OPACITY_CSS = os.path.expanduser("~/.config/waybar/looks/hover-opacity.css")


def opacity_rule(mode=None):
    """Плотность фона бара из Настроек (04.10.2026): своя для «всегда» и «при наведении».
    Только у ПОКАЗАННОГО бара — класс waybar mode-default: правило на весь window#waybar
    красило и спрятанный бар, при выезде мигали чёрные квадраты (04.10.2026, дважды).
    Что красить, зависит от вида бара: у «островов» фон у .modules-*, у «прозрачного»
    его нет вовсе (прозрачность — суть вида, не трогаем). bar_style.py зовёт это заново
    при смене вида. style.css импортирует файл — он должен существовать всегда."""
    mode = mode or get_mode()
    kind = "hover" if mode == "hover" else "always"
    pct = get_opacity(kind)
    look = look_name()
    if pct is None or look == "transparent":
        body = "/* Пишет top_bar.py (opacity_rule): прозрачность — как у вида бара. */\n"
    else:
        a = "%.2f" % (pct / 100)
        if look == "islands":
            sel = ", ".join("window#waybar.mode-default .modules-%s" % x for x in ("left", "center", "right"))
        else:
            sel = "window#waybar.mode-default"
        body = ("/* Пишет top_bar.py (opacity_rule): %s, плотность %d%%. */\n%s { background-color: %s; }\n"
                % (kind, pct, sel, "@bar-bg" if pct >= 100 else "alpha(@bar-bg, %s)" % a))
    try:
        if open(OPACITY_CSS).read() == body:
            return
    except OSError:
        pass
    with open(OPACITY_CSS + ".tmp", "w") as f:
        f.write(body)
    os.replace(OPACITY_CSS + ".tmp", OPACITY_CSS)     # waybar перечитает стиль сам


def apply():
    mode, ws = get_mode(), ws_place()
    opacity_rule(mode)
    blur_rule(mode)
    for pid in daemon_pids():                     # сторож наведения — заново, под новый режим
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    subprocess.run([sys.executable, GEN], capture_output=True)
    if mode == "off":
        for pid in session_pids("waybar"):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass
    else:
        subprocess.run([BARFIX], capture_output=True)       # перезапуск бара с новым конфигом
    # Нижнюю панель перезапускать, только если поменялось место столов (оно читается
    # при её запуске). Раньше она перезапускалась при любой смене режима верхнего бара —
    # «почему-то перезапускается нижняя панель» (04.10.2026).
    applied = os.path.join(STATE, "ws-place-applied")
    try:
        was_ws = open(applied).read().strip()
    except OSError:
        was_ws = ""
    _write(applied, ws)
    if was_ws == ws:
        if mode == "hover":
            spawn_detached(sys.executable, os.path.abspath(__file__))
        return
    # нижняя панель: со столами внизу она нужна обязательно — включаем XP, «всегда»
    bb = os.path.join(HERE, "bottom_bar.py")
    kind = subprocess.run([sys.executable, bb, "get"], capture_output=True, text=True).stdout.strip()
    if ws == "bottom":
        if kind != "xp":
            subprocess.run([sys.executable, bb, "set", "xp"], capture_output=True)
        show = subprocess.run([sys.executable, bb, "show"], capture_output=True, text=True).stdout.strip()
        if show != "always":
            subprocess.run([sys.executable, bb, "show", "always"], capture_output=True)
        else:
            subprocess.run([sys.executable, os.path.join(HERE, "xpbar.py"), "restart"], capture_output=True)
    elif kind == "xp":
        # панель «по кнопке» после перезапуска спрятана — вернуть, если была на экране
        flag = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-visible")
        was = os.path.exists(flag)
        subprocess.run([sys.executable, os.path.join(HERE, "xpbar.py"), "restart"], capture_output=True)
        if was:
            time.sleep(2.2)
            if not os.path.exists(flag):
                subprocess.run([sys.executable, bb, "toggle"], capture_output=True)
    if mode == "hover":
        spawn_detached(sys.executable, os.path.abspath(__file__))


def cli(a):
    if a[0] == "get":
        print(get_mode())
    elif a[0] == "set" and len(a) > 1 and a[1] in MODES:
        _write(MODE, a[1])
        apply()
        print(a[1])
    elif a[0] == "ws":
        if len(a) > 1 and a[1] in ("top", "bottom"):
            _write(WS, a[1])
            apply()
        print(ws_place())
    elif a[0] == "apply":
        apply()
    elif a[0] == "opacity" and len(a) > 1 and a[1] in OPACITY_FILE:
        # top_bar.py opacity always|hover [20–100|default] — без перезапуска бара
        if len(a) > 2:
            set_opacity(a[1], a[2])
            opacity_rule()
        v = get_opacity(a[1])
        print("default" if v is None else v)
    elif a[0] == "blur":
        # top_bar.py blur [on|off] — размытие под баром (только «всегда»)
        if len(a) > 1 and a[1] in ("on", "off"):
            if a[1] == "on":
                try:
                    os.remove(BLUR_OFF)
                except OSError:
                    pass
            else:
                _write(BLUR_OFF, "off")
            blur_rule(get_mode())
        print("on" if blur_on() else "off")
    else:
        print(__doc__)


if __name__ != "__main__":
    pass
elif sys.argv[1:]:
    cli(sys.argv[1:])
    sys.exit(0)
elif get_mode() != "hover" or daemon_pids():
    sys.exit(0)

if __name__ == "__main__":
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    import cairo

    sys.path.insert(0, HERE)
    import popup_theme

    SHOW_MS = 130          # столько мышь должна пробыть у верхнего края
    HIDE_MS = 320          # столько — под баром, прежде чем он спрячется
    CORNER = 56            # углы экрана оставляем «горячим углам» и обзору niri
    STRIP_H = 26           # высота нижней полоски (мышь не перепрыгнет)
    CHECK_S = 3            # как часто сверять, где мышь, пока бар показан

    def gaming():
        for p in os.listdir("/proc"):
            if p.isdigit():
                try:
                    if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                        return True
                except OSError:
                    pass
        return False

    def bar_bottom():
        """Нижний край бара от верха экрана: высота вида + отступ «от края экрана»."""
        h = popup_theme.bar_height()
        try:
            import re
            raw = open(os.path.expanduser("~/.config/waybar/looks/current.jsonc")).read()
            m = re.search(r'"margin-top"\s*:\s*(\d+)', raw)
            h += int(m.group(1)) if m else 0
        except OSError:
            pass
        return h

    class Strip(Gtk.Window):
        """Невидимая полоска-датчик: top=True — у верхнего края, иначе — под баром."""

        def __init__(self, owner, monitor, top):
            super().__init__()
            self.owner, self.top = owner, top
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "jarvis-topbar-sensor")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_monitor(self, monitor)
            for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(self, e, True)
            GtkLayerShell.set_exclusive_zone(self, -1)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
            if top:
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.LEFT, CORNER)
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.RIGHT, CORNER)
                self.set_size_request(-1, 2)
            else:
                GtkLayerShell.set_margin(self, GtkLayerShell.Edge.TOP, bar_bottom() + 4)
                self.set_size_request(-1, STRIP_H)
            visual = self.get_screen().get_rgba_visual()
            if visual:
                self.set_visual(visual)
            self.set_app_paintable(True)
            self.connect("draw", self.on_draw)
            self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
            self.connect("enter-notify-event", lambda *_a: owner.entered(top))
            self.connect("leave-notify-event", lambda _w, e: owner.left(top, e.y))

        def on_draw(self, _w, cr):
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, 0)
            cr.paint()
            return True

    class Watch:
        def __init__(self):
            self.shown = False
            self.pid = None
            self.timer = None
            self.game = False
            self.bad = 0          # сколько проверок подряд бар виден, хотя должен быть спрятан
            self.last_fix = 0.0
            self.tops, self.bottoms = [], []
            self.sig = None
            self.build_strips()
            self.sync()
            GLib.timeout_add_seconds(2, self.sync)
            GLib.timeout_add_seconds(CHECK_S, self.check_pointer)

        def mon_sig(self):
            d = Gdk.Display.get_default()
            out = []
            for i in range(d.get_n_monitors()):
                g = d.get_monitor(i).get_geometry()
                out.append((g.x, g.y, g.width, g.height))
            return tuple(out)

        def build_strips(self):
            """Полоски-датчики — по две на каждый монитор. Пересоздаются при смене набора
            мониторов (04.10.2026: подключили второй монитор — у него датчиков не было,
            и бар на нём не прятался и не выезжал)."""
            for s in self.tops + self.bottoms:
                s.destroy()
            d = Gdk.Display.get_default()
            mons = [d.get_monitor(i) for i in range(d.get_n_monitors())]
            self.tops = [Strip(self, m, True) for m in mons]
            self.bottoms = [Strip(self, m, False) for m in mons]
            self.sig = self.mon_sig()

        def bar_visible_anywhere(self):
            """Есть ли у waybar поверхность в слое Top (показана): спрятанный бар лежит в
            Bottom. У каждого монитора своя поверхность, и показ/скрытие по сигналу у них
            могут разойтись — например, бар на только что подключённом мониторе стартует
            показанным, пока бар на старом спрятан."""
            try:
                out = subprocess.run(["niri", "msg", "-j", "layers"], capture_output=True,
                                     text=True, timeout=3).stdout
                return any(l.get("namespace") == "waybar" and l.get("layer") == "Top"
                           for l in json.loads(out))
            except (OSError, ValueError, subprocess.SubprocessError):
                return False

        def waybar(self):
            p = session_pids("waybar")
            return p[0] if p else None

        def sync(self):
            """Бар перезапустили (он стартует спрятанным) или началась игра — привести
            полоски в порядок."""
            pid = self.waybar()
            game = gaming()
            if self.mon_sig() != self.sig:                 # подключили / отключили монитор
                self.build_strips()
                self.arrange()
                self.bad = 0
            if pid != self.pid or game != self.game:
                self.pid, self.game = pid, game
                self.shown = False
                self.bad = 0
                self.arrange()
            # Бар должен быть спрятан, а какой-то его экземпляр виден (после подключения
            # монитора, после сна…) — две проверки подряд (4 с, чтобы не поймать переход)
            # и перезапуск: все экземпляры стартуют спрятанными. Не чаще раза в 20 с.
            if self.pid and not self.shown and not self.game and not self.timer:
                self.bad = self.bad + 1 if self.bar_visible_anywhere() else 0
                if self.bad >= 2 and time.time() - self.last_fix > 20:
                    self.bad, self.last_fix = 0, time.time()
                    subprocess.Popen([BARFIX], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True)
            else:
                self.bad = 0
            return True

        def arrange(self):
            for s in self.tops:
                (s.show_all if (not self.shown and self.pid and not self.game) else s.hide)()
            for s in self.bottoms:
                (s.show_all if (self.shown and not self.game) else s.hide)()

        def set_bar(self, on):
            self.timer = None
            if on == self.shown or not self.pid:
                return False
            if not on and self.popup_open():
                # плашка открыта — подождать её закрытия; потом спрячет check_pointer
                # (если мышь далеко) или уход курсора с бара
                self.timer = GLib.timeout_add(700, self.set_bar, False)
                return False
            try:
                os.kill(self.pid, signal.SIGUSR1)       # waybar: показать / спрятать
            except OSError:
                self.pid = None
                return False
            self.shown = on
            self.arrange()
            return False

        def cancel(self):
            if self.timer:
                GLib.source_remove(self.timer)
                self.timer = None

        def entered(self, top):
            # Нижняя полоска лежит в Overlay сразу под баром — ровно там, где верх
            # приклеенной плашки (крестик плеера). Щелчок забирала полоска, крестик «не
            # нажимался» (04.10.2026). Пока плашка открыта, бар и так не прячется —
            # полоски убираем, мышь идёт в плашку; бар потом спрячет check_pointer.
            if not top and self.popup_open():
                for s in self.bottoms:
                    s.hide()
                return False
            self.cancel()
            self.timer = GLib.timeout_add(SHOW_MS if top else HIDE_MS, self.set_bar, top)
            return False

        def left(self, top, y):
            # с верхней полоски ушли раньше срока — не показывать; с нижней ушли ВВЕРХ
            # (обратно на бар) — не прятать; ушли вниз — прятать, как и собирались
            if top or y < 0:
                self.cancel()
            return False

        def popup_open(self):
            """Открыта плашка бара — бар не прячем (04.10.2026, просьба: «пока плашка из
            waybar открыта, не скрывать бар»). Раньше проверялся признак клавиатуры у
            слоёв, но niri его в `layers` не отдаёт — проверка всегда была «нет».
            Теперь — по процессам: питон, запустивший *_popup.py или центр управления."""
            for p in os.listdir("/proc"):
                if not p.isdigit():
                    continue
                try:
                    argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
                except OSError:
                    continue
                if len(argv) >= 2 and b"python" in os.path.basename(argv[0]):
                    name = os.path.basename(argv[1])
                    if name.endswith(b"_popup.py") or name in (b"control_center.py", b"power_menu.py"):
                        return True
            return False

        def check_pointer(self):
            """Мышь могла уйти вниз, не задев полоску (через попап под баром): раз в
            несколько секунд узнаём её место и прячем бар, если она далеко."""
            if self.shown and not self.timer and not self.popup_open():
                y = self.probe_y()
                if y is not None and y > bar_bottom() + STRIP_H + 30:
                    self.set_bar(False)
            return True

        def probe_y(self):
            """Высота указателя над/под баром: на каждый монитор на мгновение кладётся
            прозрачный слой, композитор сам сообщает, куда попала мышь (тот же приём, что
            popup_theme._spot_niri). None — узнать не удалось."""
            d = Gdk.Display.get_default()
            found, probes = {}, []
            loop = GLib.MainLoop()

            def hit(_w, ev):
                found.setdefault("y", ev.y)
                loop.quit()
                return False
            for i in range(d.get_n_monitors()):
                pw = Gtk.Window()
                GtkLayerShell.init_for_window(pw)
                GtkLayerShell.set_namespace(pw, "jarvis-pointer-probe")
                GtkLayerShell.set_layer(pw, GtkLayerShell.Layer.OVERLAY)
                GtkLayerShell.set_monitor(pw, d.get_monitor(i))
                for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                          GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                    GtkLayerShell.set_anchor(pw, e, True)
                GtkLayerShell.set_exclusive_zone(pw, -1)
                GtkLayerShell.set_keyboard_mode(pw, GtkLayerShell.KeyboardMode.NONE)
                pw.set_app_paintable(True)
                visual = pw.get_screen().get_rgba_visual()
                if visual:
                    pw.set_visual(visual)
                pw.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
                pw.connect("enter-notify-event", hit)
                pw.connect("motion-notify-event", hit)
                pw.show_all()
                probes.append(pw)
            GLib.timeout_add(120, lambda: (loop.quit(), False)[1])
            loop.run()
            for pw in probes:
                pw.destroy()
            return found.get("y")

    w = Watch()

    def bye():
        if w.shown and w.pid:                 # не оставлять бар «показанным» без сторожа
            try:
                os.kill(w.pid, signal.SIGUSR1)
            except OSError:
                pass
        os._exit(0)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, bye)
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, bye)
    Gtk.main()
