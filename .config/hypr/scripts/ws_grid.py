"""Обзор столов staticOS — Super+G плитками (03.11.2026).

Просьба: «в обзоре niri не все столы помещаются — больше трёх уже за экраном. Хочу, чтобы
Super+G показывал столы не вертикально, а плитками, как в тайлинге: сразу видно все столы
и окна, и окно можно перетащить с одного стола на другой в одном месте. Не помещаются
окна — сделать помещаемыми». Решено: своё окно, не патч niri (патч пришлось бы
пересобирать после каждого обновления, а ошибка в нём роняла бы весь сеанс).

Вторая версия, тот же вечер. Просьба: «двигать окна, визуально, как в дефолтном обзоре
нири, а не иконки… менять порядок окон в одном и том же столе… и небольшой эффектик,
когда открывается обзор». Поэтому:
  • в плитке — сами окна картинками, колонками как в ленте niri; не влезают — мельче,
    а при многих колонках лента переносится в 2–3 ряда (порядок чтения сохраняется);
  • картинки окон — `screenshot-window --id --path` niri (снимает и окна скрытых столов).
    niri кладёт каждый снимок и в буфер обмена — буфер сохраняется до снимков и
    возвращается после; метка $XDG_RUNTIME_DIR/jarvis-noclip не пускает их в историю
    (cliphist-store). Снимаются при каждом открытии, в фоне; до готовности — прошлые;
  • окно тащится мышью: на другую плитку (и на другой монитор) — между колонками туда,
    куда показывает полоска акцента; в своей же плитке — меняет место колонки;
  • открытие — как в niri: текущий стол (снимок экрана grim) сжимается в свою плитку,
    остальные проявляются; закрытие — выбранный стол разворачивается на весь экран.

Живёт в резиденте Alt+Tab (alt_tab.py): оттуда окна, столы, значки, обои и поток событий
niri. Команда — `alt_tab.sh grid` (открыть/закрыть). Какой обзор на Super+G —
state/overview-mode (niri | staticos), Настройки → Misc → Alt+Tab «Workspace Overview»;
бинд зовёт ~/.config/niri/scripts/overview.

Перестановка внутри стола и место на чужом столе: niri умеет двигать только колонку В
ФОКУСЕ — поэтому под закрытым обзором фокус ненадолго уходит на окно (focus-window,
[consume-or-expel-window-left, если в колонке не одно], move-column-to-index) и
возвращается на прежние стол и окно. Все ссылки — по id (номера столов съезжают).
"""
import json
import math
import os
import socket
import subprocess
import threading
import time
import traceback

import cairo
import gi
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

FAMILY = "JetBrainsMono Nerd Font"
MARGIN_X, MARGIN_TOP, MARGIN_BOT = 56, 48, 60
GAP = 28                 # между плитками
CAP_H = 30               # подпись стола под плиткой
DRAG_START = 6           # px — дальше это уже перетаскивание, не щелчок
MAX_SHARE = 0.46         # одна-две плитки не во весь экран
WGAP = 24                # между колонками окон, в пикселях экрана (до уменьшения)
PAD = 8                  # поле внутри плитки, px плитки
BG_DIM = 0.62    # затемнение фона обзора (04.11.2026: «фон лучше пусть будет темнее»)
TILE_DIM = 0.0   # обои внутри плитки: было 0.18 — стол темнел в конце перехода (снимок экрана без тени), 04.11.2026
IMG_MAX = 1000           # картинка окна в памяти не крупнее
GHOST_MIN, GHOST_MAX = 140, 380
OPEN_S, CLOSE_S = 0.26, 0.22
# рисование на видеокарте (GtkGLArea): переход ровно 60 к/с вместо ~45 рывками (04.11.2026);
# JV_WSGRID_CAIRO=1 — по-старому, процессором (cairo); при ошибке GL — само откатывается
USE_GL = os.environ.get("JV_WSGRID_CAIRO") != "1"
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
CAP_DIR = os.path.join(RUN, "jarvis-wsgrid")
NOCLIP = os.path.join(RUN, "jarvis-noclip")    # читает ~/.local/bin/cliphist-store


def ease(p):
    return 1 - (1 - p) ** 3


def lerp(a, b, p):
    return a + (b - a) * p


def rgba(cr, c, a=1.0):
    cr.set_source_rgba(c.red, c.green, c.blue, c.alpha * a)


def text(cr, s, x, y, w, size, color=(1, 1, 1, 0.92), markup=False, center=False):
    lay = PangoCairo.create_layout(cr)
    lay.set_font_description(Pango.FontDescription.from_string("%s %dpx" % (FAMILY, size)))
    lay.set_width(max(1, int(w)) * Pango.SCALE)
    lay.set_ellipsize(Pango.EllipsizeMode.END)
    lay.set_single_paragraph_mode(True)
    if center:
        lay.set_alignment(Pango.Alignment.CENTER)
    if markup:
        lay.set_markup(s, -1)
    else:
        lay.set_text(s, -1)
    cr.set_source_rgba(*color)
    _ink, log = lay.get_pixel_extents()
    cr.move_to(x, y - log.height / 2)
    PangoCairo.show_layout(cr, lay)


def desk_index(a, b, side):
    """Новый номер стола a (niri, с 1), чтобы встать перед/после стола b того же монитора."""
    if side == "before":
        return b if a > b else b - 1
    return b + 1 if a > b else b


def niri_req(obj):
    """Запрос в сокет niri → разобранный ответ ({"Ok": …} / {"Err": …}) или None."""
    path = os.environ.get("NIRI_SOCKET")
    if not path:
        return None
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(2)
            s.connect(path)
            s.sendall((json.dumps(obj) + "\n").encode())
            return json.loads(s.makefile().readline() or "null")
    except (OSError, ValueError):
        return None


def touch(path):
    try:
        with open(path, "a"):
            os.utime(path, None)
    except OSError:
        pass


def clip_save():
    """Что сейчас в буфере: (тип, байты); ("", None) — пусто; None — прочесть не вышло."""
    try:
        r = subprocess.run(["wl-paste", "--list-types"], capture_output=True, timeout=1)
    except (OSError, subprocess.SubprocessError):
        return None
    types = r.stdout.decode(errors="replace").split()
    if not types:
        # пусто — только если wl-paste так и сказал; не достучался до Wayland — буфер не трогать
        return ("", None) if b"Nothing is copied" in r.stderr else None
    want = next((t for t in ("image/png", "text/plain;charset=utf-8", "text/plain",
                             "UTF8_STRING", "STRING") if t in types), types[0])
    try:
        data = subprocess.run(["wl-paste", "-n", "--type", want], capture_output=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return (want, data)


def swaync_inhibit(on):
    """niri на каждый снимок шлёт уведомление «Screenshot captured» (отключить нельзя) —
    на время снимков свой «тормоз» swaync: всплывашек нет; уведомление transient, в центр
    оно не ложится. Журнал (notif_log.py) и звук затвора (auto_dnd.py) пропускают
    снимки из CAP_DIR сами."""
    try:
        subprocess.run(["swaync-client", "-sw", "-Ia" if on else "-Ir", "jarvis-wsgrid"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=1)
    except (OSError, subprocess.SubprocessError):
        pass


def clip_restore(saved):
    if saved is None:
        return
    want, data = saved
    try:
        if not want:
            subprocess.run(["wl-copy", "--clear"], timeout=2)
            return
        # текст — только как text/plain (иначе часть программ не вставляет, см. xclip-обёртку)
        typ = "text/plain" if want.startswith("text/plain") or want in ("UTF8_STRING", "STRING") else want
        subprocess.run(["wl-copy", "--type", typ], input=data, timeout=3)
    except (OSError, subprocess.SubprocessError):
        pass


class Grid:
    def __init__(self, sw, mod):
        self.sw = sw                  # Switcher из alt_tab.py
        self.m = mod                  # сам модуль alt_tab (app_info, term_view, ws_markup…)
        self.wins = {}                # выход → (Gtk.Window, GLArea | DrawingArea)
        self.gl = {}                  # выход → {"P": Painter, "tex": {ключ: (поверхность, id)}}
        self.flat = {}                # выход → поверхность: весь обзор (вне перехода), для GL
        self.tiles = {}               # выход → [плитки]
        self.shown = False
        self.hover = None             # ("win", выход, wid) | ("tile", выход, i)
        self.press = None             # нажатие: {out, x, y, what}
        self.drag = None              # {wid, out, gx, gy, over, fx, fy, w, h}
        self.target = None            # {out, i, g, bar} под окном при перетаскивании
        self.sel = None               # (выход, i) — выбор с клавиатуры
        self.nav_x = None             # j/k: столбец, откуда пошли (ряды со сдвигом, 04.11.2026)
        self.dtarget = None           # перетаскивание стола: {out, i, side, bar}
        self.surf = {}                # кэш поверхностей cairo
        self.sprites = {}             # (выход, i, вид) → готовая плитка на время перехода
        self.img = {}                 # id окна → Pixbuf (снимок окна)
        self.img_at = {}              # id окна → когда снято (time.monotonic)
        self.shots = {}               # выход → поверхность: экран в миг открытия
        self.anim = None              # {kind open|close, t0, dur, p0, focus{out: i}, shot{out: bool}}
        self.tick_id = None
        self.capturing = False
        self.moved = False            # за это открытие что-то переносили
        self.relayout_id = None
        self.opened_at = 0
        # резидент убили посреди снимков — не оставить swaync заторможенным навсегда
        threading.Thread(target=swaync_inhibit, args=(False,), daemon=True).start()

    # ── окна-слои по мониторам ──
    def window_for(self, out):
        if out in self.wins:
            return self.wins[out]
        win = Gtk.Window()
        win.set_decorated(False)
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "jarvis-wsgrid")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.OVERLAY)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, e, True)
        GtkLayerShell.set_exclusive_zone(win, -1)      # поверх баров, не сдвигаясь от них
        visual = win.get_screen().get_rgba_visual()
        if visual:
            win.set_visual(visual)
        win.set_app_paintable(True)
        # события мыши — у коробки поверх холста: холст (GL или cairo) можно подменить
        box = Gtk.EventBox()
        box.set_visible_window(False)
        box.set_above_child(True)
        box.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        box.connect("button-press-event", self.on_press, out)
        box.connect("button-release-event", self.on_release, out)
        box.connect("motion-notify-event", self.on_motion, out)
        win.connect("key-press-event", self.on_key, out)
        win.add(box)
        box.show()
        area = self.canvas_gl(out) if USE_GL else self.canvas_cairo(out)
        box.add(area)
        area.show()
        self.wins[out] = (win, area)
        return self.wins[out]

    def canvas_cairo(self, out):
        area = Gtk.DrawingArea()
        area.connect("draw", self.on_draw, out)
        return area

    def canvas_gl(self, out):
        area = Gtk.GLArea()
        area.set_has_alpha(True)
        area.set_required_version(3, 2)
        area.set_auto_render(True)
        area.connect("realize", self.on_gl_realize, out)
        area.connect("unrealize", self.on_gl_unrealize, out)
        area.connect("render", self.on_render, out)
        return area

    def on_gl_realize(self, area, out):
        err = None
        try:
            area.make_current()
            err = area.get_error()
            if err is None:
                import gl_quads
                self.gl[out] = {"P": gl_quads.Painter(), "tex": {}}
        except Exception:
            err = traceback.format_exc(limit=3)
        if err is not None:
            self.m.log("обзор GL %s: не вышло, рисую процессором: %s" % (out, err))
            GLib.idle_add(self.to_cairo, out)

    def on_gl_unrealize(self, area, out):
        g = self.gl.pop(out, None)
        if g:
            try:
                area.make_current()
                for _s, tex in g["tex"].values():
                    g["P"].free(tex)
            except Exception:
                pass

    def to_cairo(self, out):
        """GL не завёлся — подменить холст на cairo (DrawingArea)."""
        win, area = self.wins.get(out, (None, None))
        if win is None or not isinstance(area, Gtk.GLArea):
            return False
        box = area.get_parent()
        box.remove(area)
        da = self.canvas_cairo(out)
        box.add(da)
        da.show()
        self.wins[out] = (win, da)
        if getattr(area, "_jv_tick", False) and self.anim is not None:
            da._jv_tick = True
            da.add_tick_callback(self._frame_tick)
        da.queue_draw()
        return False

    def origin(self, out):
        lg = self.sw.outs.get(out) or {}
        return lg.get("x", 0), lg.get("y", 0)

    def size(self, out):
        lg = self.sw.outs.get(out) or {}
        return lg.get("width") or 1920, lg.get("height") or 1080

    # ── открыть / закрыть ──
    def toggle(self):
        if self.shown:
            self.close()
        else:
            self.open()

    def grab_screens(self, work=None):
        """Экран каждого монитора до показа обзора — первый кадр перехода (grim, ~30–70 мс).
        work — что сделать, пока grim снимает (раскладка, заготовки плиток)."""
        self.shots = {}
        if self.m.DRY:
            if work:
                work()
            return
        procs = {}
        for out in self.sw.outs:
            try:
                procs[out] = subprocess.Popen(["grim", "-t", "ppm", "-o", out, "-"],
                                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            except OSError:
                pass
        if work:
            try:
                work()
            except Exception:
                self.m.log("обзор заготовка: " + traceback.format_exc(limit=3))
        for out, p in procs.items():
            try:
                data, _ = p.communicate(timeout=0.6)
                pb = self.m.ppm_pixbuf(data) if p.returncode == 0 else None
                if pb is not None:
                    self.shots[out] = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
            except (subprocess.TimeoutExpired, ValueError, GLib.Error):
                p.kill()

    def open(self):
        sw = self.sw
        if sw.shown:
            sw.hide()
        if not sw.outs:
            sw.load_outputs()
        sw.apply_css()
        for out in [o for o in self.wins if o not in sw.outs]:     # монитор сняли
            self.wins.pop(out)[0].destroy()
        try:                          # обои: резидент освежает их раз в 45 с, после запуска — пусто
            for out, path in self.m.wallpapers().items():
                if (sw.walls.get(out) or (None,))[0] != path:
                    sw.walls[out] = (path, sw.load_wall(out, path))
        except Exception:
            self.m.log("обзор обои: " + traceback.format_exc(limit=2))
        here = sw.focused_output()
        self.drag = self.press = self.target = self.hover = self.dtarget = self.nav_x = None
        self.moved = False
        t_in = time.monotonic()
        self.relayout()
        t_lay = time.monotonic()
        self.grab_screens(self.prewarm)           # пока grim снимает — обои и плитки готовятся
        self.stage = (t_in, time.monotonic(), t_lay)
        self.sel = None
        focus = {}
        for out, tiles in self.tiles.items():
            focus[out] = next((i for i, t in enumerate(tiles)
                               if t["ws"] and t["ws"].get("is_active")), None)
        if here in focus and focus[here] is not None:
            self.sel = (here, focus[here])
        self.shown = True
        self.opened_at = time.monotonic()
        for out in sw.outs:
            win, _area = self.window_for(out)
            mon = sw.monitor_for(out)
            if mon:
                GtkLayerShell.set_monitor(win, mon)
            GtkLayerShell.set_keyboard_mode(
                win, GtkLayerShell.KeyboardMode.EXCLUSIVE if out == here
                else GtkLayerShell.KeyboardMode.NONE)
            win.show()
        self.start_anim("open", focus, {o: o in self.shots for o in focus})   # после window_for: часы кадров
        # снимки окон — после перехода: niri и разбор PNG не отнимают кадры у анимации (03.11.2026)
        GLib.timeout_add(int(OPEN_S * 1000) + 120, self._capture_later)
        self.m.log("обзор: открыт (%s)" % ", ".join("%s:%d" % (o, len(t)) for o, t in self.tiles.items()))

    def prewarm(self):
        """Обои и картинки плиток для перехода — заранее, чтобы первый кадр не тормозил."""
        self.sprites = {}
        for out, tiles in self.tiles.items():
            self.bg(out)
            for i, t in enumerate(tiles):
                for kind in ("all", "body", "frame"):
                    self.make_sprite(out, i, t, kind)

    def _capture_later(self):
        if self.shown and not (self.anim and self.anim["kind"] == "close"):
            self.capture()
        return False

    def close(self, focus=None):
        """focus — {выход: i плитки}, какой стол разворачивается; иначе активные столы."""
        if not self.shown or (self.anim and self.anim["kind"] == "close"):
            return
        self.drag = self.press = self.target = self.dtarget = None
        if focus is None:
            focus = {}
        shot = {}
        for out, tiles in self.tiles.items():
            act = next((i for i, t in enumerate(tiles) if t["ws"] and t["ws"].get("is_active")), None)
            if out not in focus:
                focus[out] = act
            # вернуться в тот же вид, что был до обзора, — снимок экрана сходится с концом
            shot[out] = (out in self.shots and not self.moved and focus[out] == act
                         and focus[out] is not None)
        p0 = self.progress() if self.anim else 1.0
        self.start_anim("close", focus, shot, p0)

    def finish_close(self):
        self.shown = False
        self.anim = None
        self.shots = {}
        self.flat = {}
        for g in self.gl.values():                # текстуры остаются, картинки в памяти — нет
            for k, (_s, tid) in list(g["tex"].items()):
                g["tex"][k] = (None, tid)
        for win, _area in self.wins.values():
            win.hide()

    def changed(self):
        """Окна/столы поменялись (поток событий niri) — перестроить, пока открыт."""
        if self.shown and self.relayout_id is None and not (self.anim and self.anim["kind"] == "close"):
            self.relayout_id = GLib.timeout_add(60, self._relayout_tick)

    def _relayout_tick(self):
        self.relayout_id = None
        if self.shown and not (self.anim and self.anim["kind"] == "close"):
            self.sprites = {}                     # плитки сдвинулись — заготовки перехода устарели
            try:
                self.relayout()
            except Exception:
                self.m.log("обзор relayout: " + traceback.format_exc(limit=3))
            self.redraw()
        return False

    def redraw(self):
        for _win, area in self.wins.values():
            area.queue_draw()

    # ── переход ──
    def start_anim(self, kind, focus, shot, p0=1.0):
        # t0 — с первого нарисованного кадра: пока слой появляется на экране, время не идёт
        self.anim = {"kind": kind, "t0": None, "c0": time.monotonic(), "dur": OPEN_S if kind == "open" else CLOSE_S,
                     "p0": p0, "focus": focus, "shot": shot}
        if kind == "close":                       # открытие готовит плитки в prewarm()
            self.sprites = {}
        if self.tick_id is None:
            self.tick_id = GLib.timeout_add(16, self.tick)
        # кадры — по часам кадров GTK (в такт монитору), а не по таймеру: ровнее (03.11.2026)
        for _win, area in self.wins.values():
            if not getattr(area, "_jv_tick", False):
                area._jv_tick = True
                area.add_tick_callback(self._frame_tick)
        self.redraw()

    def _frame_tick(self, area, _clock):
        if self.anim is None:
            area._jv_tick = False
            return False
        area.queue_draw()
        return True

    def log_frames(self, a):
        fr = a.get("frames") or []
        parts = []
        for out in sorted({f[0] for f in fr}):
            ts = [f[1] for f in fr if f[0] == out]
            ds = [f[2] for f in fr if f[0] == out]
            gaps = [b - x for x, b in zip(ts, ts[1:])] or [0]
            parts.append("%s %d к, рис. ср %.1f/макс %.1f мс, интервал макс %.0f мс" % (
                out, len(ts), 1000 * sum(ds) / len(ds), 1000 * max(ds), 1000 * max(gaps)))
        st = getattr(self, "stage", None)
        if a["kind"] == "open" and st and fr:
            parts.append("до 1-го кадра %.0f мс (раскладка %.0f, снимок+заготовка %.0f)" % (
                1000 * (fr[0][1] - st[0]), 1000 * (st[2] - st[0]), 1000 * (st[1] - st[2])))
        self.m.log("обзор переход %s: %s" % (a["kind"], "; ".join(parts)))

    def progress(self):
        """0 — экран как без обзора, 1 — обзор целиком."""
        a = self.anim
        if not a:
            return 1.0
        if a["t0"] is None:
            raw = 0.0
        else:
            raw = min(1.0, (time.monotonic() - a["t0"]) / a["dur"])
        if a["kind"] == "open":
            return ease(raw)
        return a["p0"] * (1 - ease(raw))

    def tick(self):
        a = self.anim
        if not a:
            self.tick_id = None
            return False
        if a["t0"] is None and time.monotonic() - a["c0"] > 0.2:
            a["t0"] = time.monotonic()            # слой так и не нарисовался — не ждать вечно
        if a["t0"] is not None and time.monotonic() - a["t0"] >= a["dur"]:
            self.sprites = {}
            self.log_frames(a)
            if a["kind"] == "close":
                self.tick_id = None
                self.finish_close()
                return False
            self.anim = None
            self.tick_id = None
            self.redraw()
            return False
        return True                               # кадры рисует _frame_tick

    # ── снимки окон ──
    def capture(self, ids=None):
        """ids — только эти окна (Alt+Tab, вид «окна стола», 04.11.2026); иначе все."""
        if self.m.DRY or self.capturing:
            return
        if ids is None:
            ids = [w["id"] for w in self.sw.windows.values()
                   if not (w.get("app_id") or "").startswith(self.m.HIDDEN_APPS)]
        if not ids:
            return
        self.capturing = True
        threading.Thread(target=self._capture, args=(ids,), daemon=True).start()

    def _capture(self, ids):
        inhibited = False
        try:
            os.makedirs(CAP_DIR, exist_ok=True)
            touch(NOCLIP)
            saved = clip_save()
            if saved is None:                      # не вернём буфер — не снимать вовсе
                self.m.log("обзор: буфер обмена не прочитан — снимки окон пропущены")
                return
            inhibited = True
            swaync_inhibit(True)
            paths = {}
            for wid in ids:
                p = os.path.join(CAP_DIR, "w%d.png" % wid)
                try:
                    os.unlink(p)
                except OSError:
                    pass
                r = niri_req({"Action": {"ScreenshotWindow": {
                    "id": wid, "write_to_disk": True, "show_pointer": False, "path": p}}})
                if r and "Ok" in r:
                    paths[wid] = p
            sizes, deadline = {}, time.monotonic() + 4
            while paths and time.monotonic() < deadline:
                time.sleep(0.04)
                for wid, p in list(paths.items()):
                    try:
                        sz = os.path.getsize(p)
                    except OSError:
                        continue
                    if sz <= 0 or sizes.get(wid) != sz:
                        sizes[wid] = sz            # ещё пишется — ждать, пока размер встанет
                        continue
                    try:
                        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(p, IMG_MAX, IMG_MAX, True)
                    except GLib.Error:
                        sizes.pop(wid, None)
                        continue
                    del paths[wid]
                    GLib.idle_add(self.got_img, wid, pb)
                    try:
                        os.unlink(p)
                    except OSError:
                        pass
            touch(NOCLIP)
            clip_restore(saved)
            time.sleep(0.4)                        # уведомление niri идёт после записи файла
            swaync_inhibit(False)
            inhibited = False
            time.sleep(1.6)                          # эхо wl-copy в cliphist-store — тоже мимо
        except Exception:
            self.m.log("обзор снимки: " + traceback.format_exc(limit=3))
        finally:
            if inhibited:
                swaync_inhibit(False)
            try:
                os.unlink(NOCLIP)
            except OSError:
                pass
            GLib.idle_add(self._capture_done)

    def _capture_done(self):
        self.capturing = False
        live = set(self.sw.windows)
        for wid in [w for w in self.img if w not in live]:
            del self.img[wid]
        return False

    def got_img(self, wid, pb):
        self.img[wid] = pb
        self.img_at[wid] = time.monotonic()
        if self.shown:
            self.redraw()
        hook = getattr(self.sw, "win_img", None)   # Alt+Tab, вид «окна стола»
        if hook:
            hook(wid)
        return False

    # ── раскладка ──
    def desks(self, out):
        sw = self.sw
        xs = list(sw.desks_of(out))
        have = {s["id"] for s in xs}
        busy = {w.get("workspace_id") for w in sw.windows.values()}
        empty = sorted((s for s in sw.ws.values() if s.get("output") == out and s["id"] not in have
                        and s["id"] not in busy and s.get("name") not in self.m.dash_names()),
                       key=lambda s: s.get("idx") or 0)
        tiles = [{"kind": "desk", "ws": s} for s in xs]
        if empty:                     # пустой стол niri в конце — «+ Новый стол»
            tiles.append({"kind": "new", "ws": empty[-1]})
        return tiles

    def relayout(self):
        self.tiles = {}
        for out in self.sw.outs:
            tiles = self.desks(out)
            if tiles:
                self.place(out, tiles)
            self.tiles[out] = tiles
        if self.sel and (self.sel[0] not in self.tiles or self.sel[1] >= len(self.tiles[self.sel[0]])):
            self.sel = None

    def place(self, out, tiles):
        ow, oh = self.size(out)
        aw, ah = ow - 2 * MARGIN_X, oh - MARGIN_TOP - MARGIN_BOT
        a = ow / oh
        n = len(tiles)
        best = None
        for cols in range(1, n + 1):
            rows = math.ceil(n / cols)
            cols = math.ceil(n / rows)
            tw = min((aw - GAP * (cols - 1)) / cols, ((ah - GAP * (rows - 1)) / rows - CAP_H) * a,
                     ow * MAX_SHARE)
            if best is None or tw > best[0] + 0.5:
                best = (tw, rows)
        tw, rows = best
        tw = int(tw)
        th = int(tw / a)
        # строки поровну, лишние — в верхние (5 → 3+2, 7 → 4+3)
        base, rest = divmod(n, rows)
        counts = [base + (1 if r < rest else 0) for r in range(rows)]
        full_h = rows * (th + CAP_H) + (rows - 1) * GAP
        y = MARGIN_TOP + (ah - full_h) / 2
        k = 0
        for cnt in counts:
            row_w = cnt * tw + (cnt - 1) * GAP
            x = (ow - row_w) / 2
            for _ in range(cnt):
                t = tiles[k]
                t.update(x=int(x), y=int(y), w=tw, h=th, H=th + CAP_H)
                self.lay_desk(out, t)
                x += tw + GAP
                k += 1
            y += th + CAP_H + GAP

    def wins_of(self, t):
        if not t.get("ws"):
            return []
        sid = t["ws"]["id"]
        return [w for w in self.sw.windows.values() if w.get("workspace_id") == sid
                and not (w.get("app_id") or "").startswith(self.m.HIDDEN_APPS)]

    def lay_desk(self, out, t):
        """Окна стола колонками, как в ленте niri. Масштаб — чтобы влезла вся лента; если
        колонок много и окна вышли бы крошечными — лента переносится в 2–3 ряда."""
        ow, oh = self.size(out)
        tw, th = t["w"], t["h"]
        t["cols"], t["wr"], t["k"] = [], [], tw / ow
        cols, floats = {}, []
        for w in self.wins_of(t):
            lay = w.get("layout") or {}
            pos = lay.get("pos_in_scrolling_layout")
            size = lay.get("tile_size") or lay.get("window_size") or (ow / 2, oh)
            if w.get("is_floating") or not pos:
                floats.append((w, size))
            else:
                cols.setdefault(pos[0], []).append((pos[1], w, size))
        columns = []
        for c in sorted(cols):
            cells = [(w, s) for _r, w, s in sorted(cols[c], key=lambda z: z[0])]
            columns.append({"key": c, "w": max(s[0] for _w, s in cells),
                            "h": sum(s[1] for _w, s in cells) + WGAP * (len(cells) - 1),
                            "cells": cells})
        k = tw / ow
        rows = [columns] if columns else []
        if columns:
            total = sum(c["w"] for c in columns) + WGAP * (len(columns) - 1)
            best = None
            for r in range(1, min(3, len(columns)) + 1):
                groups, cur, acc, goal = [], [], 0, total / r
                for i, c in enumerate(columns):
                    left = len(columns) - i
                    if cur and (acc + c["w"] / 2 > goal or left < r - len(groups)) and len(groups) < r - 1:
                        groups.append(cur)
                        cur, acc = [], 0
                    cur.append(c)
                    acc += c["w"] + WGAP
                groups.append(cur)
                W = max(sum(c["w"] for c in g) + WGAP * (len(g) - 1) for g in groups)
                H = sum(max(c["h"] for c in g) for g in groups) + WGAP * (len(groups) - 1)
                kr = min((tw - 2 * PAD) / W, (th - 2 * PAD) / H, tw / ow)
                if best is None or kr > best[0] * 1.15:
                    best = (kr, groups)
            k, rows = best
        t["k"] = k
        hs = [max(c["h"] for c in g) for g in rows]
        y = t["y"] + (th - (sum(hs) + WGAP * (len(rows) - 1)) * k) / 2
        for r, (g, rh) in enumerate(zip(rows, hs)):
            rw = sum(c["w"] for c in g) + WGAP * (len(g) - 1)
            x = t["x"] + (tw - rw * k) / 2
            for c in g:
                cy = y + (rh - c["h"]) * k / 2
                ids = []
                for w, s in c["cells"]:
                    t["wr"].append((w, (x, cy, s[0] * k, s[1] * k)))
                    ids.append(w["id"])
                    cy += (s[1] + WGAP) * k
                t["cols"].append({"row": r, "x0": x, "x1": x + c["w"] * k,
                                  "y0": y, "y1": y + rh * k, "wins": ids})
                x += (c["w"] + WGAP) * k
            y += (rh + WGAP) * k
        for w, s in floats:                        # плавающие — по центру, поверх
            fw, fh = s[0] * k, s[1] * k
            if fw > tw - 2 * PAD or fh > th - 2 * PAD:
                f = min((tw - 2 * PAD) / fw, (th - 2 * PAD) / fh)
                fw, fh = fw * f, fh * f
            t["wr"].append((w, (t["x"] + (tw - fw) / 2, t["y"] + (th - fh) / 2, fw, fh)))

    def slot_for(self, t, x, y, wid):
        """Куда встанет окно, брошенное в точку (x, y) плитки: (g — сколько колонок слева,
        полоска (x, y0, y1)) или (None, None) — просто на стол."""
        win = self.sw.windows.get(wid) or {}
        if t["kind"] != "desk" or win.get("is_floating"):
            return None, None
        same = t["ws"]["id"] == win.get("workspace_id")
        cols = [c for c in t["cols"] if not (same and c["wins"] == [wid])]
        if not cols:
            return (0, None) if not same else (None, None)
        rows = {}
        for c in cols:
            rows.setdefault(c["row"], []).append(c)
        order = sorted(rows)
        row = next((r for r in order if rows[r][0]["y0"] <= y < rows[r][0]["y1"]), None)
        if row is None:
            row = min(order, key=lambda r: abs((rows[r][0]["y0"] + rows[r][0]["y1"]) / 2 - y))
        rc = rows[row]
        before = sum(len(rows[r]) for r in order if r < row)
        slot = sum(1 for c in rc if (c["x0"] + c["x1"]) / 2 < x)
        half = WGAP * t["k"] / 2
        if slot == 0:
            bx = rc[0]["x0"] - half
        elif slot == len(rc):
            bx = rc[-1]["x1"] + half
        else:
            bx = (rc[slot - 1]["x1"] + rc[slot]["x0"]) / 2
        bx = min(max(bx, t["x"] + 2), t["x"] + t["w"] - 2)
        return before + slot, (bx, rc[0]["y0"], rc[0]["y1"])

    # ── картинки ──
    def surface_of(self, key, pb, w, h, dim=0.0):
        """Pixbuf → поверхность cairo нужного размера, с кэшем (рисуем на каждое движение мыши)."""
        w, h = max(1, int(round(w))), max(1, int(round(h)))
        hit = self.surf.get(key)
        if hit and hit[0] is pb and hit[1] == (w, h, dim):
            return hit[2]
        src = pb
        if pb.get_width() != w or pb.get_height() != h:
            pb = pb.scale_simple(w, h, GdkPixbuf.InterpType.BILINEAR)
        s = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
        if dim:
            cr = cairo.Context(s)
            cr.set_source_rgba(0, 0, 0, dim)
            cr.paint()
        if len(self.surf) > 160:
            self.surf.clear()
        self.surf[key] = (src, (w, h, dim), s)
        return s

    def wall_pb(self, out, w, h):
        path = (self.sw.walls.get(out) or (None,))[0]
        key = ("wpb", out)
        hit = self.surf.get(key)
        if hit and hit[0] == path and hit[1] == (w, h):
            return hit[2]
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, w, h, False)
            except GLib.Error:
                pb = None
        self.surf[key] = (path, (w, h), pb)
        return pb

    def bg(self, out):
        """Обои монитора во весь экран, затемнённые; кэш по пути обоев."""
        path = (self.sw.walls.get(out) or (None,))[0]
        ow, oh = self.size(out)
        key = ("bg", out)
        hit = self.surf.get(key)
        if hit and hit[0] == path and hit[1] == (ow, oh):
            return hit[2]
        s = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, ow, oh, False)
                s = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
                cr = cairo.Context(s)
                cr.set_source_rgba(0, 0, 0, BG_DIM)
                cr.paint()
            except GLib.Error:
                s = None
        self.surf[key] = (path, (ow, oh), s)
        return s

    # ── рисование ──
    def on_draw(self, area, cr, out):
        t0 = time.monotonic()
        try:
            self.draw(cr, out)
        except Exception:
            self.m.log("обзор draw: " + traceback.format_exc(limit=3))
        self.frame_done(out, t0)
        return True

    def frame_done(self, out, t0):
        a = self.anim
        if a is not None:                         # замер перехода: когда и сколько рисовался кадр
            a.setdefault("frames", []).append((out, t0, time.monotonic() - t0))
            if a["t0"] is None:                   # отсчёт — после первого кадра (он = экран как был)
                a["t0"] = time.monotonic()

    # ── видеокарта: кадр = готовые картинки, сдвинутые и прозрачные (04.11.2026) ──
    def on_render(self, area, _ctx, out):
        g = self.gl.get(out)
        if g is None:
            return False
        t0 = time.monotonic()
        try:
            self.gl_draw(area, out, g)
        except Exception:
            self.m.log("обзор GL draw: " + traceback.format_exc(limit=3))
        self.frame_done(out, t0)
        return True

    def tex(self, g, key, surf, fresh=False):
        """Текстура для поверхности cairo; заливается заново, если поверхность другая или fresh."""
        hit = g["tex"].get(key)
        if hit and hit[0] is surf and not fresh:
            return hit[1]
        tid = g["P"].texture(surf, hit[1] if hit else 0)
        g["tex"][key] = (surf, tid)
        return tid

    def gl_draw(self, area, out, g):
        P = g["P"]
        w, h = area.get_allocated_width(), area.get_allocated_height()
        sc = area.get_scale_factor()
        P.begin(w, h, w * sc, h * sc)
        a = self.anim
        if a is None:
            # обычный вид (наведение, перетаскивание) — как раньше рисует cairo, на экран — одной картинкой
            surf = self.flat.get(out)
            if surf is None or (surf.get_width(), surf.get_height()) != (w, h):
                surf = self.flat[out] = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
            self.draw(cairo.Context(surf), out)
            P.quad(self.tex(g, "flat", surf, fresh=True), 0, 0, w, h, 1.0)
            return
        ow, oh = self.size(out)
        p = self.progress()
        focus = a["focus"].get(out)
        use_shot = bool(a["shot"].get(out) and out in self.shots)
        fade = 1.0
        if a["kind"] == "close" and not use_shot:
            fade = min(1.0, p / 0.5)
        bg = self.bg(out)
        if bg is not None:
            P.quad(self.tex(g, "bg", bg), 0, 0, ow, oh, p * fade, opaque=True)
        else:
            P.fill(0, 0, ow, oh, 0.04, 0.04, 0.06, 0.97 * p * fade)
        tiles = self.tiles.get(out) or []
        pad = self.SPRITE_PAD
        for i, t in enumerate(tiles):
            if i == focus:
                continue
            sp = self.make_sprite(out, i, t, "all")
            cx, cy = t["x"] + t["w"] / 2, t["y"] + t["H"] / 2
            k = 0.86 + 0.14 * p
            P.quad(self.tex(g, (i, "all"), sp), cx + (t["x"] - pad - cx) * k, cy + (t["y"] - pad - cy) * k,
                   sp.get_width() * k, sp.get_height() * k, p * fade)
        if focus is not None and focus < len(tiles):
            t = tiles[focus]
            R = (lerp(0, t["x"], p), lerp(0, t["y"], p), lerp(ow, t["w"], p), lerp(oh, t["h"], p))
            sx, sy = R[2] / t["w"], R[3] / t["h"]
            for kind, al in (("body", fade), ("frame", p ** 4 * fade)):
                sp = self.make_sprite(out, focus, t, kind)
                P.quad(self.tex(g, (focus, kind), sp), R[0] - pad * sx, R[1] - pad * sy,
                       sp.get_width() * sx, sp.get_height() * sy, al)
            if use_shot:
                P.quad(self.tex(g, "shot", self.shots[out]), R[0], R[1], R[2], R[3], 1 - p, opaque=True)
        hs, hy = self.hint_sprite(out, tiles)
        P.quad(self.tex(g, "hint", hs), 0, hy, hs.get_width(), hs.get_height(), 0.55 * p * fade)

    def hint_text(self, out, tiles):
        many = len(self.sw.outs) > 1
        head = self.sw.monitor_name(out) + " · " if many else ""
        n = len([t for t in tiles if t["kind"] == "desk"])
        return ("%s%d %s   ·   тащите окно на другой стол или между окнами, подпись стола — переставить стол"
                "   ·   щелчок — перейти   ·   Esc — закрыть") % (head, n, self.m.plural(n, "стол", "стола", "столов"))

    def hint_sprite(self, out, tiles):
        """Подсказка внизу — картинкой (для перехода на видеокарте); (поверхность, y)."""
        ow, oh = self.size(out)
        s = self.hint_text(out, tiles)
        y0 = int(oh - MARGIN_BOT)
        key = ("hint", out)
        hit = self.surf.get(key)
        if hit and hit[0] == (s, ow, oh):
            return hit[2], y0
        sp = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(ow), int(MARGIN_BOT))
        c = cairo.Context(sp)
        c.translate(0, -y0)
        text(c, s, 0, oh - MARGIN_BOT / 2, ow, 13, (1, 1, 1, 1.0), center=True)
        sp.flush()
        self.surf[key] = ((s, ow, oh), None, sp)
        return sp, y0

    def draw(self, cr, out):
        ow, oh = self.size(out)
        acc = self.sw.acc
        p = self.progress()
        a = self.anim
        focus = a["focus"].get(out) if a else None
        use_shot = bool(a and a["shot"].get(out) and out in self.shots)
        fade = 1.0
        if a and a["kind"] == "close" and not use_shot:
            fade = min(1.0, p / 0.5)              # к концу обзор тает, под ним уже нужный стол
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        bg = self.bg(out)
        if bg is not None:
            cr.set_source_surface(bg, 0, 0)
            cr.paint_with_alpha(p * fade)
        else:
            cr.set_source_rgba(0.04, 0.04, 0.06, 0.97 * p * fade)
            cr.paint()
        tiles = self.tiles.get(out) or []
        drag_wid = self.drag["wid"] if self.drag else None
        if a:
            # переход: каждая плитка нарисована один раз в картинку, кадр — только их сдвиг и
            # масштаб (раньше весь обзор рисовался заново: 40–67 мс на кадр, ~20 к/с) (03.11.2026)
            for i, t in enumerate(tiles):
                if i == focus:
                    continue
                cx, cy = t["x"] + t["w"] / 2, t["y"] + t["H"] / 2
                k = 0.86 + 0.14 * p
                cr.save()
                cr.translate(cx, cy)
                cr.scale(k, k)
                cr.translate(-cx, -cy)
                self.paint_sprite(cr, out, i, t, "all", p * fade)
                cr.restore()
            if focus is not None and focus < len(tiles):
                t = tiles[focus]
                R = (lerp(0, t["x"], p), lerp(0, t["y"], p), lerp(ow, t["w"], p), lerp(oh, t["h"], p))
                cr.save()
                cr.translate(R[0], R[1])
                cr.scale(R[2] / t["w"], R[3] / t["h"])
                cr.translate(-t["x"], -t["y"])
                # сильно растянутая плитка прикрыта снимком экрана — сглаживание там не видно, а дорого
                big = R[2] / t["w"] > 1.4
                self.paint_sprite(cr, out, focus, t, "body", fade,
                                  cairo.FILTER_FAST if big else cairo.FILTER_BILINEAR)
                self.paint_sprite(cr, out, focus, t, "frame", p ** 4 * fade)
                cr.restore()
                if use_shot:
                    shot = self.shots[out]
                    cr.save()
                    cr.translate(R[0], R[1])
                    cr.scale(R[2] / max(1, shot.get_width()), R[3] / max(1, shot.get_height()))
                    cr.set_source_surface(shot, 0, 0)
                    cr.get_source().set_filter(cairo.FILTER_FAST)
                    cr.paint_with_alpha(1 - p)
                    cr.restore()
        else:
            dd = self.drag if self.drag and self.drag.get("desk") else None
            for i, t in enumerate(tiles):
                src = dd is not None and dd["out"] == out and dd["i"] == i
                self.draw_tile(cr, out, i, t, acc, drag_wid, 0.3 if src else 1.0)
            dt = self.dtarget
            if dd and dt and dt["out"] == out:
                bx, y0, y1 = dt["bar"]
                rgba(cr, acc)
                cr.rectangle(bx - 3, y0, 6, y1 - y0)
                cr.fill()
        hint = self.hint_text(out, tiles)
        text(cr, hint, 0, oh - MARGIN_BOT / 2, ow, 13, (1, 1, 1, 0.55 * p * fade), center=True)
        if self.drag and self.drag.get("over") == out:
            self.draw_ghost(cr, out, acc)

    SPRITE_PAD = 8

    def paint_sprite(self, cr, out, i, t, kind, alpha, filt=cairo.FILTER_BILINEAR):
        """Плитка из готовой картинки: all — целиком, body — без рамки и подписи, frame — только они."""
        sp = self.make_sprite(out, i, t, kind)
        if alpha <= 0.003:
            return
        pad = self.SPRITE_PAD
        cr.set_source_surface(sp, t["x"] - pad, t["y"] - pad)
        cr.get_source().set_filter(filt)
        cr.paint_with_alpha(alpha)

    def make_sprite(self, out, i, t, kind):
        key = (out, i, kind)
        sp = self.sprites.get(key)
        pad = self.SPRITE_PAD
        if sp is None:
            sp = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(t["w"]) + 2 * pad, int(t["H"]) + 2 * pad)
            c = cairo.Context(sp)
            c.translate(pad - t["x"], pad - t["y"])
            drag_wid = self.drag["wid"] if self.drag else None
            a, fa = {"all": (1.0, None), "body": (1.0, 0.0), "frame": (0.0, 1.0)}[kind]
            self.draw_tile(c, out, i, t, self.sw.acc, drag_wid, a, frame_a=fa)
            sp.flush()
            self.sprites[key] = sp
        return sp

    def draw_tile(self, cr, out, i, t, acc, drag_wid, a, frame_a=None, fast=False):
        """a — прозрачность всей плитки; frame_a — отдельно для рамки и подписи (переход)."""
        fa = a if frame_a is None else frame_a
        x, y, w, h = t["x"], t["y"], t["w"], t["h"]
        s = t["ws"]
        tg = self.target if self.target and self.target["out"] == out and self.target["i"] == i else None
        hover = self.hover == ("tile", out, i) and not self.drag
        if t["kind"] == "new":
            cr.set_source_rgba(1, 1, 1, (0.14 if tg else 0.06) * a)
            cr.rectangle(x, y, w, h)
            cr.fill()
            cr.set_dash([8, 6])
            if tg:
                rgba(cr, acc, a)
            else:
                cr.set_source_rgba(1, 1, 1, (0.45 if hover else 0.28) * a)
            cr.set_line_width(2)
            cr.rectangle(x + 1, y + 1, w - 2, h - 2)
            cr.stroke()
            cr.set_dash([])
            text(cr, "+", x, y + h / 2 - 14, w, 44, (1, 1, 1, 0.7 * a), center=True)
            text(cr, "Новый стол", x, y + h / 2 + 26, w, 14, (1, 1, 1, 0.7 * a), center=True)
        else:
            wall = self.wall_pb(out, w, h)
            if wall is not None:
                cr.set_source_surface(self.surface_of(("w", out), wall, w, h, dim=TILE_DIM), x, y)
                if fast:
                    cr.get_source().set_filter(cairo.FILTER_FAST)
                cr.paint_with_alpha(a)
            else:
                cr.set_source_rgba(0.08, 0.08, 0.1, 0.9 * a)
                cr.rectangle(x, y, w, h)
                cr.fill()
            cr.save()
            cr.rectangle(x, y, w, h)
            cr.clip()
            for win, r in t["wr"]:
                self.draw_win(cr, out, win, r, acc, a * (0.28 if win["id"] == drag_wid else 1.0), fast)
            cr.restore()
            if s.get("is_active"):
                rgba(cr, acc, fa)
                cr.set_line_width(2)
            else:
                cr.set_source_rgba(1, 1, 1, (0.4 if hover else 0.16) * fa)
                cr.set_line_width(1)
            cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
            cr.stroke()
            if tg:
                src_ws = (self.sw.windows.get(drag_wid) or {}).get("workspace_id")
                if s["id"] != src_ws:
                    rgba(cr, acc, 0.16 * a)
                    cr.rectangle(x, y, w, h)
                    cr.fill()
                    rgba(cr, acc, a)
                    cr.set_line_width(3)
                    cr.rectangle(x + 1.5, y + 1.5, w - 3, h - 3)
                    cr.stroke()
                if tg.get("bar"):
                    bx, y0, y1 = tg["bar"]
                    rgba(cr, acc, a)
                    cr.rectangle(bx - 2, y0, 4, y1 - y0)
                    cr.fill()
            # подпись как в Alt+Tab (режим столов): значок + программы стола по колонкам (03.11.2026)
            label = "  " + (" · ".join(self.sw.desk_names(s)) or "пусто")
            mk = self.m.ws_markup(s, self.sw.windows, label)
            col = (1, 1, 1, 0.95 * fa) if s.get("is_active") else (1, 1, 1, 0.72 * fa)
            text(cr, mk, x + 2, y + h + CAP_H / 2 + 1, w - 4, 14, col, markup=True)
        if self.sel == (out, i):
            cr.set_source_rgba(1, 1, 1, 0.85 * fa)
            cr.set_line_width(2)
            cr.rectangle(x - 4, y - 4, w + 8, t["H"] + 6)
            cr.stroke()

    def caption(self, win):
        app_id = win.get("app_id") or ""
        name, _icon = self.m.app_info(app_id)
        if app_id.lower() in self.m.TERMINALS:
            which, cap = self.m.term_view(win.get("title"))
            return cap if which or cap else name
        t = (win.get("title") or "").strip()
        for sep in (" — ", " - ", " – ", " | "):
            if sep in t:
                t = t.split(sep)[0]
                break
        return t or name

    def draw_win(self, cr, out, win, r, acc, a, fast=False):
        X, Y, W, H = r
        if W < 2 or H < 2:
            return
        pb = self.img.get(win["id"])
        if pb is not None:
            surf = self.surface_of(("img", win["id"]), pb, W, H)
            cr.save()
            cr.translate(X, Y)
            cr.scale(W / surf.get_width(), H / surf.get_height())
            cr.set_source_surface(surf, 0, 0)
            if fast:
                cr.get_source().set_filter(cairo.FILTER_FAST)
            cr.paint_with_alpha(a)
            cr.restore()
        else:                                      # снимка ещё нет — плашка со значком
            cr.set_source_rgba(0.07, 0.07, 0.09, 0.9 * a)
            cr.rectangle(X, Y, W, H)
            cr.fill()
            size = int(min(48, W - 8, H - 8))
            ipb = self.sw.icon_for(win.get("app_id") or "", size) if size >= 12 else None
            if ipb is not None:
                cy = Y + H / 2 - (9 if H > size + 34 and W > 70 else 0)
                cr.save()
                Gdk.cairo_set_source_pixbuf(cr, ipb, round(X + (W - size) / 2), round(cy - size / 2))
                cr.paint_with_alpha(a)
                cr.restore()
                if H > size + 34 and W > 70:
                    text(cr, self.caption(win), X + 4, cy + size / 2 + 13, W - 8, 11,
                         (1, 1, 1, 0.8 * a), center=True)
        hov = self.hover == ("win", out, win["id"]) and not self.drag
        if win.get("is_focused"):
            rgba(cr, acc, a)
            cr.set_line_width(2)
            cr.rectangle(X + 1, Y + 1, W - 2, H - 2)
        else:
            cr.set_source_rgba(1, 1, 1, (0.7 if hov else 0.14) * a)
            cr.set_line_width(2 if hov else 1)
            cr.rectangle(X + 0.5, Y + 0.5, W - 1, H - 1)
        cr.stroke()

    def draw_ghost(self, cr, out, acc):
        d = self.drag
        if d.get("desk"):
            self.draw_desk_ghost(cr, out, acc, d)
            return
        win = self.sw.windows.get(d["wid"])
        if not win:
            return
        ox, oy = self.origin(out)
        w, h = d["w"], d["h"]
        f = 1.0
        if w < GHOST_MIN:
            f = GHOST_MIN / w
        elif w > GHOST_MAX:
            f = GHOST_MAX / w
        w, h = w * f, h * f
        X, Y = d["gx"] - ox - d["fx"] * w, d["gy"] - oy - d["fy"] * h
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.rectangle(X + 6, Y + 8, w, h)
        cr.fill()
        self.draw_win(cr, out, dict(win, is_focused=False), (X, Y, w, h), acc, 0.92)
        rgba(cr, acc)
        cr.set_line_width(2)
        cr.rectangle(X + 1, Y + 1, w - 2, h - 2)
        cr.stroke()

    def draw_desk_ghost(self, cr, out, acc, d):
        """Стол под курсором при перетаскивании — уменьшенная плитка (04.11.2026)."""
        tiles = self.tiles.get(d["out"]) or []
        if d["i"] >= len(tiles):
            return
        t = tiles[d["i"]]
        ox, oy = self.origin(out)
        k = min(1.0, 380 / max(1, t["w"]))
        w, h = t["w"] * k, t["H"] * k
        X, Y = d["gx"] - ox - d["fx"] * w, d["gy"] - oy - d["fy"] * h
        cr.set_source_rgba(0, 0, 0, 0.35)
        cr.rectangle(X + 6, Y + 8, w, t["h"] * k)
        cr.fill()
        cr.save()
        cr.translate(X, Y)
        cr.scale(k, k)
        cr.translate(-t["x"], -t["y"])
        self.draw_tile(cr, d["out"], d["i"], t, acc, None, 0.95)
        rgba(cr, acc)
        cr.set_line_width(2 / k)
        cr.rectangle(t["x"] + 1, t["y"] + 1, t["w"] - 2, t["h"] - 2)
        cr.stroke()
        cr.restore()

    def desk_slot(self, out, lx, ly):
        """Куда встанет перетаскиваемый стол: перед/после плитки под курсором → {out, i, side, bar}."""
        d = self.drag
        tiles = self.tiles.get(out) or []
        best = None
        for j, t in enumerate(tiles):
            if not t["ws"]:
                continue
            if t["x"] - GAP / 2 <= lx < t["x"] + t["w"] + GAP / 2 and \
                    t["y"] - GAP / 2 <= ly < t["y"] + t["H"] + GAP / 2:
                best = j
                break
        if best is None:
            return None
        t = tiles[best]
        side = "before" if (t["kind"] == "new" or lx < t["x"] + t["w"] / 2) else "after"
        if out == d["out"]:
            i = d["i"]
            if best == i or (side == "before" and best == i + 1) or (side == "after" and best == i - 1):
                return None                       # туда же, где стоит
        bx = t["x"] - GAP / 2 if side == "before" else t["x"] + t["w"] + GAP / 2
        return {"out": out, "i": best, "side": side, "bar": (bx, t["y"], t["y"] + t["h"])}

    # ── мышь ──
    def hit(self, out, x, y):
        """→ ("win", i, win, rect) | ("tile", i) | None (мимо плиток)."""
        for i, t in enumerate(self.tiles.get(out) or []):
            if not (t["x"] <= x < t["x"] + t["w"] and t["y"] <= y < t["y"] + t["H"]):
                continue
            for win, r in reversed(t.get("wr") or []):
                X, Y, W, H = r
                if X <= x < X + W and Y <= y < Y + H:
                    return ("win", i, win, r)
            return ("tile", i)
        return None

    def out_at(self, gx, gy):
        for out in self.sw.outs:
            ox, oy = self.origin(out)
            ow, oh = self.size(out)
            if ox <= gx < ox + ow and oy <= gy < oy + oh:
                return out
        return None

    def on_motion(self, _area, ev, out):
        try:
            if not self.shown or (self.anim and self.anim["kind"] == "close"):
                return True
            ox, oy = self.origin(out)
            pr = self.press
            if pr and not self.drag and pr["what"][0] == "win":
                if abs(ev.x - pr["x"]) + abs(ev.y - pr["y"]) > DRAG_START:
                    X, Y, W, H = pr["what"][3]
                    self.drag = {"wid": pr["what"][2]["id"], "out": out, "w": W, "h": H,
                                 "fx": (pr["x"] - X) / max(1, W), "fy": (pr["y"] - Y) / max(1, H)}
            # стол целиком — за подпись или пустое место плитки (04.11.2026)
            if pr and not self.drag and pr["what"][0] == "tile" \
                    and abs(ev.x - pr["x"]) + abs(ev.y - pr["y"]) > DRAG_START:
                tiles = self.tiles.get(pr["out"]) or []
                i = pr["what"][1]
                if i < len(tiles) and tiles[i]["kind"] == "desk" and tiles[i]["ws"]:
                    t = tiles[i]
                    self.drag = {"desk": t["ws"]["id"], "wid": None, "out": pr["out"], "i": i,
                                 "fx": (pr["x"] - t["x"]) / max(1, t["w"]),
                                 "fy": (pr["y"] - t["y"]) / max(1, t["H"])}
            if self.drag and self.drag.get("desk"):
                gx, gy = ox + ev.x, oy + ev.y
                o2 = self.out_at(gx, gy)
                self.drag.update(gx=gx, gy=gy, over=o2)
                self.target = None
                if o2:
                    x2, y2 = self.origin(o2)
                    self.dtarget = self.desk_slot(o2, gx - x2, gy - y2)
                else:
                    self.dtarget = None
                self.redraw()
                return True
            if self.drag:
                # пока кнопка зажата, события идут окну, где нажали, — и за его краем:
                # координаты в общих (по монитору под курсором)
                gx, gy = ox + ev.x, oy + ev.y
                self.drag.update(gx=gx, gy=gy, over=self.out_at(gx, gy))
                tgt = None
                o2 = self.drag["over"]
                if o2:
                    x2, y2 = self.origin(o2)
                    lx, ly = gx - x2, gy - y2
                    h = self.hit(o2, lx, ly)
                    if h:
                        t = self.tiles[o2][h[1]]
                        g, bar = self.slot_for(t, lx, ly, self.drag["wid"])
                        tgt = {"out": o2, "i": h[1], "g": g, "bar": bar}
                self.target = tgt
                self.redraw()
                return True
            h = self.hit(out, ev.x, ev.y)
            hov = None
            if h and h[0] == "win":
                hov = ("win", out, h[2]["id"])
            elif h:
                hov = ("tile", out, h[1])
            if hov != self.hover:
                self.hover = hov
                self.redraw()
        except Exception:
            self.m.log("обзор motion: " + traceback.format_exc(limit=3))
        return True

    def on_press(self, _area, ev, out):
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True                       # двойной щелчок — второй раз не считать
        if self.anim and self.anim["kind"] == "close":
            return True
        if ev.button != 1:
            if ev.button == 3:
                self.close()
            return True
        self.press = {"out": out, "x": ev.x, "y": ev.y, "what": self.hit(out, ev.x, ev.y) or ("bg",)}
        return True

    def on_release(self, _area, ev, out):
        try:
            if ev.button != 1 or not self.press:
                return True
            press, drag, target, dtarget = self.press, self.drag, self.target, self.dtarget
            self.press = self.drag = self.target = self.dtarget = None
            if drag and drag.get("desk"):
                if dtarget:
                    self.move_desk(drag, dtarget)
                self.redraw()
                return True
            if drag:
                win = self.sw.windows.get(drag["wid"])
                if win and target:
                    self.move(win, target)
                self.redraw()
                return True
            what = press["what"]
            if what[0] == "win":
                self.focus_window(what[2], out, what[1])
            elif what[0] == "tile":
                self.go_desk(self.tiles[out][what[1]]["ws"], out, what[1])
            elif time.monotonic() - self.opened_at > 0.25:
                self.close()
        except Exception:
            self.m.log("обзор release: " + traceback.format_exc(limit=3))
        return True

    # ── действия ──
    def act(self, steps, why):
        """Шаги niri по сокету, по порядку, в фоне (обзор не ждёт)."""
        if not steps:
            return
        self.m.log("обзор: %s — %s" % (why, " → ".join(next(iter(s)) for s in steps)))
        if self.m.DRY:
            self.m.log("обзор (сухо): " + json.dumps(steps, ensure_ascii=False))
            return

        def run():
            for s in steps:
                r = niri_req({"Action": s})
                if not r or "Ok" not in r:
                    self.m.log("обзор: niri не принял %s: %s" % (json.dumps(s), r))
        threading.Thread(target=run, daemon=True).start()

    def move(self, win, target):
        out, i, g = target["out"], target["i"], target.get("g")
        t = (self.tiles.get(out) or [])[i]
        s = t["ws"]
        if not s:
            return
        wid = int(win["id"])
        same = s["id"] == win.get("workspace_id")
        floating = bool(win.get("is_floating"))
        steps, dance = [], False
        if same:
            if floating or g is None:
                return
            col = next((c for c in t["cols"] if wid in c["wins"]), None)
            if col is None:
                return
            alone = len(col["wins"]) == 1
            if alone and g == t["cols"].index(col):
                return                             # бросили на своё же место
            steps.append({"FocusWindow": {"id": wid}})
            if not alone:
                steps.append({"ConsumeOrExpelWindowLeft": {"id": wid}})
            steps.append({"MoveColumnToIndex": {"index": g + 1}})
            dance = True
        else:
            steps.append({"MoveWindowToWorkspace": {"window_id": wid, "reference": {"Id": s["id"]},
                                                    "focus": False}})
            if not floating and g is not None and t["cols"]:
                steps += [{"FocusWindow": {"id": wid}}, {"MoveColumnToIndex": {"index": g + 1}}]
                dance = True
        if dance:
            # вернуть, как было: стол монитора-цели, стол и окно в фокусе
            here = self.sw.focused_output()
            prev = next((w["id"] for w in self.sw.windows.values() if w.get("is_focused")), None)
            tact = (self.sw.active_ws(out) or {}).get("id")
            hact = (self.sw.active_ws(here) or {}).get("id")
            if out != here and tact is not None:
                steps.append({"FocusWorkspace": {"reference": {"Id": tact}}})
            if hact is not None:
                steps.append({"FocusWorkspace": {"reference": {"Id": hact}}})
            if prev is not None and prev != wid:
                steps.append({"FocusWindow": {"id": prev}})
        self.moved = True
        self.act(steps, "окно %d (%s) → %s стол %s, место %s" % (
            wid, win.get("app_id"), out, s.get("idx"), "—" if g is None else g + 1))

    def move_desk(self, drag, dt):
        """Переставить стол: на другой монитор (MoveWorkspaceToMonitor) и на место
        (MoveWorkspaceToIndex, номера niri с 1). Фокус niri при этом не меняет (04.11.2026)."""
        src = self.sw.ws.get(drag["desk"])
        tiles = self.tiles.get(dt["out"]) or []
        if not src or dt["i"] >= len(tiles) or not tiles[dt["i"]]["ws"]:
            return
        sid, tid = src["id"], tiles[dt["i"]]["ws"]["id"]
        out, side = dt["out"], dt["side"]
        cross = src.get("output") != out
        self.moved = True
        why = "стол %s (%s) → %s, %s стола %s" % (src.get("idx"), src.get("output"), out,
                                                  "перед" if side == "before" else "после",
                                                  tiles[dt["i"]]["ws"].get("idx"))
        self.m.log("обзор: " + why)
        if self.m.DRY:
            self.m.log("обзор (сухо): стол %d → %s %s %d" % (sid, out, side, tid))
            return

        def run():
            try:
                if cross:
                    r = niri_req({"Action": {"MoveWorkspaceToMonitor": {"output": out, "reference": {"Id": sid}}}})
                    if not r or "Ok" not in r:
                        self.m.log("обзор: niri не принял перенос стола: %s" % r)
                        return
                r = niri_req("Workspaces")
                ws = {w["id"]: w for w in r["Ok"]["Workspaces"]}
                a, b = ws[sid]["idx"], ws[tid]["idx"]
                p = desk_index(a, b, side)
                if p != a:
                    r = niri_req({"Action": {"MoveWorkspaceToIndex": {"index": p, "reference": {"Id": sid}}}})
                    if not r or "Ok" not in r:
                        self.m.log("обзор: niri не принял место стола: %s" % r)
            except Exception:
                self.m.log("обзор move_desk: " + traceback.format_exc(limit=3))
        threading.Thread(target=run, daemon=True).start()

    def focus_window(self, win, out, i):
        self.close({out: i})
        self.act([{"FocusWindow": {"id": int(win["id"])}}], "в окно")

    def go_desk(self, s, out, i):
        self.close({out: i})
        if s:
            self.act([{"FocusWorkspace": {"reference": {"Id": s["id"]}}}], "на стол %s" % s.get("idx"))

    # ── клавиатура ──
    def on_key(self, _w, ev, out):
        k = ev.keyval
        G = Gdk
        if k in (G.KEY_Escape, G.KEY_q):
            self.close()
            return True
        if self.anim and self.anim["kind"] == "close":
            return True
        if self.sel and self.sel[0] in self.tiles and self.sel[1] < len(self.tiles[self.sel[0]]):
            so, cur = self.sel
        else:                                     # выбора нет — сперва показать, где он
            so = out if self.tiles.get(out) else next((o for o, t in self.tiles.items() if t), None)
            if so is None:
                return True
            cur = 0
            if k not in (G.KEY_Return, G.KEY_KP_Enter, G.KEY_space) and not (G.KEY_1 <= k <= G.KEY_9):
                self.sel = (so, 0)
                self.redraw()
                return True
        tiles = self.tiles[so]
        d = None
        if k in (G.KEY_Right, G.KEY_l, G.KEY_Cyrillic_de, G.KEY_d, G.KEY_Cyrillic_ve):
            d = "r"
        elif k in (G.KEY_Left, G.KEY_h, G.KEY_Cyrillic_er, G.KEY_a, G.KEY_Cyrillic_ef):
            d = "l"
        elif k in (G.KEY_Down, G.KEY_j, G.KEY_Cyrillic_o, G.KEY_s, G.KEY_Cyrillic_yeru):
            d = "d"
        elif k in (G.KEY_Up, G.KEY_k, G.KEY_Cyrillic_el, G.KEY_w, G.KEY_Cyrillic_tse):
            d = "u"
        elif k in (G.KEY_Tab, G.KEY_ISO_Left_Tab):
            order = [(o, i) for o in self.outs_by_x() for i in range(len(self.tiles.get(o) or []))]
            n = order.index((so, cur)) + (-1 if k == G.KEY_ISO_Left_Tab else 1)
            self.sel = order[n % len(order)]
            self.nav_x = None
            self.redraw()
            return True
        elif k in (G.KEY_Return, G.KEY_KP_Enter, G.KEY_space):
            self.go_desk(tiles[cur]["ws"], so, cur)
            return True
        elif G.KEY_1 <= k <= G.KEY_9 and k - G.KEY_1 < len(tiles):
            self.go_desk(tiles[k - G.KEY_1]["ws"], so, k - G.KEY_1)
            return True
        if d:
            ax = None
            if d in ("u", "d"):                   # j/k держат столбец: j, k — туда же, откуда ушли
                c = tiles[cur]
                ax = self.nav_x if self.nav_x is not None else c["x"] + c["w"] / 2
            nxt = self.neighbour(so, cur, d, ax)
            if nxt:
                self.sel = nxt
                self.nav_x = ax
                self.redraw()
        return True

    def outs_by_x(self):
        return sorted(self.tiles, key=lambda o: self.origin(o))

    def neighbour(self, out, i, d, ax=None):
        """Соседняя плитка по направлению — по положению на экране (ряды бывают 4+3 со сдвигом),
        h/l на краю — на соседний монитор, в тот же по высоте ряд (04.11.2026)."""
        tiles = self.tiles[out]
        c = tiles[i]
        cx, cy = c["x"] + c["w"] / 2, c["y"] + c["H"] / 2
        best = None
        for j, t in enumerate(tiles):
            if j == i:
                continue
            dx, dy = t["x"] + t["w"] / 2 - cx, t["y"] + t["H"] / 2 - cy
            same_row = abs(dy) < c["H"] / 2
            if d in ("l", "r"):
                if not same_row or (dx > 0) != (d == "r"):
                    continue
                key = (abs(dx),)
            else:
                if same_row or (dy > 0) != (d == "d"):
                    continue
                tx = t["x"] + t["w"] / 2
                key = (round(abs(dy)), abs(tx - (cx if ax is None else ax)))   # ближний ряд, в нём — ближняя к столбцу
            if best is None or key < best[0]:
                best = (key, (out, j))
        if best or d in ("u", "d"):
            return best[1] if best else None
        outs = self.outs_by_x()
        n = outs.index(out) + (1 if d == "r" else -1)
        if not 0 <= n < len(outs) or not self.tiles.get(outs[n]):
            return None
        o2 = outs[n]
        _ow, oh = self.size(out)
        rel = cy / oh                             # та же высота на другом мониторе
        t2 = self.tiles[o2]
        oh2 = self.size(o2)[1]
        row_y = min({t["y"] + t["H"] / 2 for t in t2}, key=lambda y: abs(y / oh2 - rel))
        row = [j for j, t in enumerate(t2) if abs(t["y"] + t["H"] / 2 - row_y) < 1]
        j = min(row, key=lambda j: t2[j]["x"]) if d == "r" else max(row, key=lambda j: t2[j]["x"])
        return (o2, j)

