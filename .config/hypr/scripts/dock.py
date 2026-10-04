#!/usr/bin/env python3
"""Док снизу, по образцу Noctalia. 30.09.2026.

    dock.py                    запустить (второй запуск — закрыть прежний), автозапуск niri
    dock.py mode               какой режим
    dock.py mode all|workspace все окна / только окна текущего стола этого монитора
    dock.py on|off|status      включить / выключить док совсем (Настройки → Внешний вид)

Как устроено. На каждом мониторе — слой GTK LayerShell у нижнего края по центру.
В покое от него остаётся невидимая полоска 2 px (TRIGGER_W × 2): курсор, доведённый
до низа экрана посередине, задевает её — и док выезжает (Gtk.Revealer, SLIDE_UP).
Курсор ушёл — через HIDE_MS док уезжает, окно снова сжимается до полоски, щелчки
по экрану под ним не перехватываются. Над полноэкранными окнами (игры) слой TOP
в niri не рисуется — док там не мешает.

Значки — работающие программы, по одному на приложение (app_id), точки под
значком — число окон (до трёх), точка акцентом — у приложения в фокусе.
Левый щелчок — перейти к окну; если оно уже в фокусе — к следующему окну той же
программы. Средний — закрыть последнее окно программы. Подсказка — имя программы.
Окна дашборда (app_id dash-*) не показываются: они и так на своём столе.
Цвета — popup_theme (палитра обоев), рамка — общая для попапов.
"""
import json
import math
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

MODE_FILE = os.path.expanduser("~/.config/hypr/state/dock-mode")



def _die_with_parent():
    """preexec_fn для фоновых подписок (pactl subscribe, swaync-client -swb,
    niri event-stream): ядро убьёт их вместе с этим процессом (PR_SET_PDEATHSIG).
    01.10.2026: без этого каждый перезапуск панели оставлял сирот — к ночи их
    набралось больше сотни, pipewire-pulse упёрся в предел клиентов («too many
    client application connections») и новые программы остались без звука."""
    import ctypes
    import signal as _signal
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, _signal.SIGTERM)


def get_mode():
    try:
        return "workspace" if open(MODE_FILE).read().strip() == "workspace" else "all"
    except OSError:
        return "all"


OFF_FLAG = os.path.expanduser("~/.config/hypr/state/dock-off")


def running_pids():
    me = os.getpid()
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == me:
            continue
        try:
            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) >= 2 and b"python" in os.path.basename(argv[0]) \
                and os.path.basename(argv[1]) == b"dock.py" and len(argv) <= 3 \
                and (len(argv) == 2 or argv[2] == b""):
            out.append(int(p))
    return out


if sys.argv[1:2] == ["status"]:
    print("off" if os.path.exists(OFF_FLAG) else "on")
    sys.exit(0)
if sys.argv[1:2] == ["off"]:
    os.makedirs(os.path.dirname(OFF_FLAG), exist_ok=True)
    open(OFF_FLAG, "w").close()
    for pid in running_pids():
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    print("off")
    sys.exit(0)
if sys.argv[1:2] == ["on"]:
    try:
        os.remove(OFF_FLAG)
    except OSError:
        pass
    if not running_pids():
        import subprocess as _sp
        _sp.Popen([sys.executable, os.path.abspath(__file__)], stdout=_sp.DEVNULL,
                  stderr=_sp.DEVNULL, start_new_session=True)
    print("on")
    sys.exit(0)
if not sys.argv[1:] and os.path.exists(OFF_FLAG):
    sys.exit(0)          # выключен в Настройках — автозапуск ничего не делает

if sys.argv[1:2] == ["mode"]:
    if len(sys.argv) > 2 and sys.argv[2] in ("all", "workspace"):
        os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
        with open(MODE_FILE, "w") as f:
            f.write(sys.argv[2] + "\n")
    print(get_mode())
    sys.exit(0)

popup_theme.single_instance(__file__)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell  # noqa: E402

ICON = 48                # как у Noctalia (icon_size=48)
TRIGGER_W = 420
HIDE_MS = 500
REFRESH_MS = 1000
HIDDEN_APPS = ("dash-",)


def niri(*args):
    try:
        out = subprocess.run(["niri", "msg", "-j", *args], capture_output=True,
                             text=True, timeout=2).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def action(*args):
    subprocess.Popen(["niri", "msg", "action", *args],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


_app_cache = {}
PIN_FILE = os.path.expanduser("~/.config/hypr/state/dock-pinned.json")


def pinned():
    try:
        return [a for a in json.load(open(PIN_FILE)) if isinstance(a, str)]
    except (OSError, ValueError):
        return []


def set_pinned(ids):
    os.makedirs(os.path.dirname(PIN_FILE), exist_ok=True)
    with open(PIN_FILE, "w") as f:
        json.dump(ids, f)


def desktop_info(app_id):
    app_info(app_id)
    return _app_cache[app_id][2]


def app_info(app_id):
    """(имя, Gio.Icon) по app_id окна — через .desktop, как это делают доки."""
    if app_id in _app_cache:
        return _app_cache[app_id][:2]     # в кэше ещё и DesktopAppInfo (для меню) — наружу имя и значок
    info = None
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            break
    if not info:
        for group in Gio.DesktopAppInfo.search(app_id) or []:
            for did in group:
                try:
                    cand = Gio.DesktopAppInfo.new(did)
                except TypeError:
                    cand = None
                if cand:
                    info = cand
                    break
            if info:
                break
    if not info:   # по StartupWMClass
        for a in Gio.AppInfo.get_all():
            if isinstance(a, Gio.DesktopAppInfo) and (a.get_startup_wm_class() or "").lower() == app_id.lower():
                info = a
                break
    name = info.get_display_name() if info else app_id
    icon = info.get_icon() if info else None
    if icon is None:
        icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower())
    _app_cache[app_id] = (name, icon, info)
    return name, icon


MAG = 1.45               # увеличение значка под курсором, как у Noctalia (magnification_scale)
GAP = 6                  # между значками
PAD_X, PAD_TOP, PAD_BOTTOM = 12, 8, 16   # поля плиты; снизу место под точки
SPREAD = int(ICON * (MAG - 1) * 2) + 8   # запас по бокам: с лупой ряд шире, плита растёт вместе с ним
LIFT = int(ICON * (MAG - 1)) + 4         # запас сверху: увеличенный значок выходит за плиту
RADIUS = 16
BORDER = 3               # рамка — как у остальных попапов (BASE_CSS)


def hexrgb(h, a=1.0):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)


class DockArea(Gtk.DrawingArea):
    """Весь док одной картинкой: плита, значки с «лупой», точки, подсветка.

    Лупа — формула Noctalia: множитель = 1 + (MAG−1)·cos²(π/2 · d / (1.5·шаг)),
    d — расстояние от курсора до центра значка. Значки растут вверх от общей
    линии, соседи расступаются симметрично, плита своего размера не меняет.
    Движение сглажено: каждый кадр (16 мс) множитель подходит к цели на 28 %.
    """

    def __init__(self, dock):
        super().__init__()
        self.dock = dock
        self.pal = popup_theme.palette()
        self.items = []          # [(app_id, windows, name, pixbuf)]
        self.scales = []
        self.mouse_x = None
        self.anim = None
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                        | Gdk.EventMask.BUTTON_RELEASE_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("leave-notify-event", self.on_area_leave)
        self.connect("button-release-event", self.on_release)
        self.set_has_tooltip(True)
        self.connect("query-tooltip", self.on_tooltip)

    # геометрия
    def slab_w(self):
        n = max(1, len(self.items))
        return 2 * PAD_X + n * ICON + (n - 1) * GAP

    def slab_h(self):
        return PAD_TOP + ICON + PAD_BOTTOM

    def set_apps(self, groups):
        theme = Gtk.IconTheme.get_default()
        big = int(ICON * MAG) * max(1, self.get_scale_factor())
        items = []
        for aid, ws in groups.items():
            name, icon = app_info(aid)
            pix = None
            try:
                info = theme.lookup_by_gicon(icon, big, Gtk.IconLookupFlags.FORCE_SIZE)
                if info is None:
                    info = theme.lookup_icon("application-x-executable", big, Gtk.IconLookupFlags.FORCE_SIZE)
                pix = info.load_icon() if info else None
            except Exception:
                pix = None
            items.append((aid, ws, name, pix))
        self.items = items
        self.scales = [1.0] * len(items)
        self.set_size_request(self.slab_w() + SPREAD, self.slab_h() + LIFT)
        self.queue_resize()
        self.queue_draw()

    def centers(self, w):
        """Середины значков при нынешних множителях (соседи расступаются)."""
        widths = [ICON * s for s in self.scales]
        total = sum(widths) + GAP * (len(widths) - 1)
        x = w / 2 - total / 2
        out = []
        for wd in widths:
            out.append(x + wd / 2)
            x += wd + GAP
        return out

    def targets(self, w):
        base = [w / 2 - (self.slab_w() - 2 * PAD_X) / 2 + ICON / 2 + i * (ICON + GAP)
                for i in range(len(self.items))]
        if self.mouse_x is None:
            return [1.0] * len(base)
        pitch = ICON + GAP
        out = []
        for c in base:
            d = abs(self.mouse_x - c)
            if d >= 1.5 * pitch:
                out.append(1.0)
            else:
                k = math.cos(math.pi / 2 * d / (1.5 * pitch)) ** 2
                out.append(1 + (MAG - 1) * k)
        return out

    def step(self):
        w = self.get_allocated_width()
        tg = self.targets(w)
        moving = False
        for i, t in enumerate(tg):
            d = t - self.scales[i]
            if abs(d) > 0.002:
                self.scales[i] += d * 0.28
                moving = True
            else:
                self.scales[i] = t
        self.queue_draw()
        if not moving:
            self.anim = None
            return False
        return True

    def kick(self):
        if self.anim is None:
            self.anim = GLib.timeout_add(16, self.step)

    # события
    def on_motion(self, _w, ev):
        self.mouse_x = ev.x
        self.kick()
        return False

    def on_area_leave(self, _w, ev):
        if ev.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.mouse_x = None
        self.kick()
        return False

    def hit(self, x):
        w = self.get_allocated_width()
        for i, c in enumerate(self.centers(w)):
            if abs(x - c) <= ICON * self.scales[i] / 2 + GAP / 2:
                return i
        return None

    def on_tooltip(self, _w, x, y, _kb, tip):
        i = self.hit(x)
        if i is None:
            return False
        aid, ws, name, _ = self.items[i]
        tip.set_text(name + " · не запущено" if not ws else
                     name if len(ws) == 1 else "%s · окон: %d" % (name, len(ws)))
        return True

    def on_release(self, _w, ev):
        i = self.hit(ev.x)
        if i is None:
            return False
        aid, ws = self.items[i][0], self.items[i][1]
        if ev.button == 3:
            self.menu(aid, ws, ev)
            return True
        if not ws:
            if ev.button == 1:          # закреплённое, но не запущенное — запустить
                info = desktop_info(aid)
                if info:
                    info.launch([], None)
            return True
        if ev.button == 2:
            action("close-window", "--id", str(ws[-1]["id"]))
        elif ev.button == 1:
            ids = [w["id"] for w in ws]
            cur = next((k for k, w in enumerate(ws) if w.get("is_focused")), None)
            target = ids[(cur + 1) % len(ids)] if cur is not None else ids[-1]
            action("focus-window", "--id", str(target))
        GLib.timeout_add(250, lambda: (self.dock.refresh(), False)[1])
        return True

    def menu(self, aid, ws, ev):
        """Меню по правому щелчку, как у Noctalia: окна программы, закрепить,
        действия из .desktop, закрыть. Пока меню открыто, док не прячется."""
        m = Gtk.Menu()
        m.get_style_context().add_class("dock-menu")

        def item(label, cb):
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda *_: (cb(), GLib.timeout_add(250, lambda: (self.dock.refresh(), False)[1])))
            m.append(it)

        for w in ws:
            title = (w.get("title") or aid)[:48]
            item(("● " if w.get("is_focused") else "   ") + title,
                 lambda w=w: action("focus-window", "--id", str(w["id"])))
        if ws:
            m.append(Gtk.SeparatorMenuItem())
        pins = pinned()
        if aid in pins:
            item("Открепить", lambda: set_pinned([p for p in pins if p != aid]))
        else:
            item("Закрепить в доке", lambda: set_pinned(pins + [aid]))
        info = desktop_info(aid)
        acts = info.list_actions() if info else []
        if info and not ws:
            item("Запустить", lambda: info.launch([], None))
        if acts:
            m.append(Gtk.SeparatorMenuItem())
            for a in acts:
                item(info.get_action_name(a), lambda a=a: info.launch_action(a, None))
        if ws:
            m.append(Gtk.SeparatorMenuItem())
            if len(ws) == 1:
                item("Закрыть", lambda: action("close-window", "--id", str(ws[0]["id"])))
            else:
                item("Закрыть все (%d)" % len(ws),
                     lambda: [action("close-window", "--id", str(w["id"])) for w in ws])
        self.dock.menu_open = True
        m.connect("deactivate", lambda *_: self.dock.menu_closed())
        m.show_all()
        m.popup_at_pointer(ev)
        self._menu = m

    # рисование
    def rounded(self, cr, x, y, w, h, r):
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def on_draw(self, widget, cr):
        pal = self.pal
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        # Плита растёт вместе с рядом (как у macOS): иначе крайние значки при
        # лупе вылезали бы за её края.
        row = sum(ICON * k for k in self.scales) + GAP * max(0, len(self.scales) - 1)
        sw, sh = max(self.slab_w(), row + 2 * PAD_X), self.slab_h()
        sx, sy = (w - sw) / 2, h - sh
        # плита: тёмный контур, рамка акцента, фон
        self.rounded(cr, sx - 1, sy - 1, sw + 2, sh + 2, RADIUS + 1)
        cr.set_source_rgba(0, 0, 0, 0.6)
        cr.fill()
        self.rounded(cr, sx, sy, sw, sh, RADIUS)
        cr.set_source_rgba(*hexrgb(pal["primary"]))
        cr.fill()
        self.rounded(cr, sx + BORDER, sy + BORDER, sw - 2 * BORDER, sh - 2 * BORDER, RADIUS - BORDER)
        cr.set_source_rgba(*hexrgb(pal["surface"]))
        cr.fill()
        if not self.items:
            return True
        base_y = sy + PAD_TOP + ICON           # нижняя линия значков
        hover = self.hit(self.mouse_x) if self.mouse_x is not None else None
        for i, c in enumerate(self.centers(w)):
            aid, ws, name, pix = self.items[i]
            s = self.scales[i]
            size = ICON * s
            x0, y0 = c - size / 2, base_y - size
            focused = any(win.get("is_focused") for win in ws)
            if focused:
                self.rounded(cr, c - ICON / 2 - 4, sy + PAD_TOP - 4, ICON + 8, ICON + 8, 10)
                cr.set_source_rgba(*hexrgb(pal["primary"], 0.16))
                cr.fill()
            if pix is not None:
                cr.save()
                cr.translate(x0, y0)
                k = size / pix.get_width()
                cr.scale(k, k)
                Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
                cr.get_source().set_filter(__import__("cairo").FILTER_GOOD)
                # закреплённое, но не запущенное — бледнее (точек у него нет)
                alpha = 1.0 if (focused or i == hover) else (0.85 if ws else 0.5)
                cr.paint_with_alpha(alpha)
                cr.restore()
            # точки: число окон, до трёх
            n = min(len(ws), 3)
            r = 2.5
            col = pal["primary"] if focused else pal.get("secondary", pal["primary"])
            cr.set_source_rgba(*hexrgb(col))
            span = n * 2 * r + (n - 1) * 3
            dx = c - span / 2 + r
            for _ in range(n):
                cr.arc(dx, base_y + 8, r, 0, 2 * math.pi)
                cr.fill()
                dx += 2 * r + 3
        return True


class Dock(Gtk.Window):
    def __init__(self, monitor, connector):
        super().__init__(title="Dock")
        self.connector = connector
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-dock")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_exclusive_zone(self, -1)     # поверх полей бара и всего прочего
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        outer = Gtk.EventBox()
        outer.set_above_child(False)
        outer.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        outer.connect("enter-notify-event", self.on_enter)
        outer.connect("leave-notify-event", self.on_leave)
        self.add(outer)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.add(col)

        self.rev = Gtk.Revealer()
        self.rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.rev.set_transition_duration(220)
        self.rev.connect("notify::child-revealed", self.on_revealed)
        col.pack_start(self.rev, False, False, 0)

        self.area = DockArea(self)
        self.area.set_halign(Gtk.Align.CENTER)
        self.area.set_margin_bottom(6)
        self.rev.add(self.area)

        trig = Gtk.Box()
        trig.set_size_request(TRIGGER_W, 2)
        trig.set_halign(Gtk.Align.CENTER)
        col.pack_start(trig, False, False, 0)

        self.hide_id = None
        self.tick_id = None
        self.sig = None
        self.show_all()

    # ── показ и прятанье ─────────────────────────────────────────────────
    def on_enter(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = None
        if not self.rev.get_reveal_child():
            self.sig = None              # при каждом появлении — список заново
            self.refresh()
            self.rev.set_reveal_child(True)
            if not self.tick_id:
                self.tick_id = GLib.timeout_add(REFRESH_MS, self.tick)
        return False

    def menu_closed(self):
        self.menu_open = False
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add(HIDE_MS * 2, self.hide_now)

    def on_leave(self, _w, event):
        if event.detail == Gdk.NotifyType.INFERIOR or getattr(self, "menu_open", False):
            return False
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add(HIDE_MS, self.hide_now)
        return False

    def hide_now(self):
        self.hide_id = None
        if getattr(self, "menu_open", False):
            return False
        self.rev.set_reveal_child(False)
        if self.tick_id:
            GLib.source_remove(self.tick_id)
            self.tick_id = None
        return False

    def on_revealed(self, *_a):
        if not self.rev.get_child_revealed() and not self.rev.get_reveal_child():
            self.resize(1, 1)        # окно обратно в полоску — не заслоняет щелчки

    def tick(self):
        self.refresh()
        return True

    # ── содержимое ───────────────────────────────────────────────────────
    def apps(self):
        wins = niri("windows") or []
        mode = get_mode()
        if mode == "workspace":
            wss = niri("workspaces") or []
            active = {w["id"] for w in wss if w.get("is_active") and w.get("output") == self.connector}
            wins = [w for w in wins if w.get("workspace_id") in active]
        groups = {a: [] for a in pinned()}      # закреплённые — первыми, по порядку
        for w in sorted(wins, key=lambda w: w["id"]):
            aid = w.get("app_id") or "unknown"
            if aid.startswith(HIDDEN_APPS):
                continue
            groups.setdefault(aid, []).append(w)
        return groups

    def refresh(self):
        groups = self.apps()
        sig = json.dumps({a: [(w["id"], w.get("is_focused")) for w in ws] for a, ws in groups.items()})
        if sig == self.sig:
            return
        self.sig = sig
        self.area.set_apps(groups)


def main():
    pal = popup_theme.palette()
    css = popup_theme.css("""
    .dock {
        font-family: 'PxPlus HP 100LX 6x8 Jarvis', sans-serif;
        font-size: 16px; font-weight: normal;
        border-radius: 16px; padding: 6px 10px 2px 10px;
    }
    button.dock-app {
        background: transparent; background-image: none; border: none; box-shadow: none;
        border-radius: 12px; padding: 6px 6px 0 6px; min-width: 0; min-height: 0;
    }
    button.dock-app:hover { background-color: %(surface_high)s; }
    button.dock-app.focused { background-color: %(focus_bg)s; }
    /* Неактивные приложения приглушены, как у Noctalia (inactive_opacity 0.85). */
    button.dock-app:not(.focused) image { opacity: 0.85; }
    button.dock-app:hover image { opacity: 1; }
    label.dots { color: %(primary)s; font-size: 12px; margin: 0; padding: 0; }
    label.dock-empty { color: %(on_surface_variant)s; }
    menu, .menu, .context-menu {
        background-color: %(surface)s; color: %(on_surface)s;
        border: 2px solid %(primary)s; border-radius: 10px; padding: 4px;
    }
    menuitem {
        font-family: 'PxPlus HP 100LX 6x8 Jarvis', sans-serif; font-size: 16px;
        padding: 5px 12px; border-radius: 6px;
    }
    menuitem:hover { background-color: %(surface_high)s; color: %(primary)s; }
    menu separator { background-color: %(outline_variant)s; min-height: 1px; margin: 4px 6px; }
    tooltip {
        background-color: %(surface)s; color: %(on_surface)s;
        border: 1px solid %(primary)s; border-radius: 8px;
    }
    tooltip label {
        font-family: 'PxPlus HP 100LX 6x8 Jarvis', sans-serif; font-size: 16px;
        font-weight: normal; padding: 2px 6px;
    }
    """, focus_bg=popup_theme.rgba(pal["primary"], "0.16"))
    provider = Gtk.CssProvider()
    provider.load_from_data(css)
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    display = Gdk.Display.get_default()
    outs = niri("outputs") or {}
    by_model = {}
    for conn, o in outs.items():
        by_model[(o.get("model") or "")] = conn
    docks = []
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        conn = by_model.get(mon.get_model() or "", "")
        if not conn:     # модель не совпала — по порядку
            conn = sorted(outs)[i] if i < len(outs) else ""
        docks.append(Dock(mon, conn))

    # SIGUSR1 — показать док на мониторе в фокусе (для бинда и для проверки):
    # pkill -USR1 -f dock.py. Прячется как обычно — когда курсор уйдёт, или через 3 с.
    import signal

    def on_usr1():
        fo = (niri("focused-output") or {}).get("name")
        for d in docks:
            if d.connector == fo:
                d.refresh()
                d.rev.set_reveal_child(True)
                if d.hide_id:
                    GLib.source_remove(d.hide_id)
                d.hide_id = GLib.timeout_add(3000, d.hide_now)
        return True
    GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_usr1)

    # События niri (смена стола, окна открылись/закрылись/переехали) — сразу
    # обновить док. Раньше список обновлялся только при появлении и раз в
    # секунду, и док мог показать окна чужого стола (30.09.2026).
    import threading
    pending = {"id": None}

    def refresh_all():
        pending["id"] = None
        for d in docks:
            d.refresh()
        return False

    def schedule():
        if pending["id"] is None:
            pending["id"] = GLib.timeout_add(80, refresh_all)
        return False

    def listen():
        while True:
            try:
                p = subprocess.Popen(["niri", "msg", "-j", "event-stream"],
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                     preexec_fn=_die_with_parent)
                for line in p.stdout:
                    if any(k in line for k in ("Workspace", "Window")):
                        GLib.idle_add(schedule)
                p.wait()
            except OSError:
                pass
            import time
            time.sleep(2)
    threading.Thread(target=listen, daemon=True).start()
    Gtk.main()


if __name__ == "__main__":
    main()
