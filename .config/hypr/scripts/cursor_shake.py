#!/usr/bin/env python3
"""«Встряхни мышь — найди курсор»: кольца вокруг указателя. 02.10.2026.

    cursor_shake.py              сторож (автозапуск niri; второй экземпляр выходит)
    cursor_shake.py on|off       включить / выключить (Настройки → Misc)
    cursor_shake.py status       on | off
    cursor_shake.py test         показать эффект сразу (на мониторе, где шевельнётся мышь)
    cursor_shake.py mode [grow|rings]   что делать при встряхивании (по умолчанию grow)

03.10.2026 — режим grow, «как в KDE» (просьба: «когда трясёшь мышкой туда-сюда, она
увеличивается со временем»): пока трясёшь, курсор растёт (до MAX_SCALE раз), перестал —
плавно возвращается. Настоящий курсор niri рисует поверх всех слоёв и размер его меняется
только конфигом, поэтому делается подмена: на время эффекта слои над мониторами
принимают мышь, прячут настоящий курсор (курсор «none») и рисуют на его месте большой
— картинку из той же темы курсора (Xcursor, самый крупный размер, без сглаживания —
тема пиксельная). Слой сам получает координаты мыши, поэтому большой курсор идёт точно
за настоящим. Щелчок во время эффекта сразу его снимает (этот щелчок теряется).
Старые кольца — режим rings.

Идея — из KDE («Shake Cursor») и дотфайлов AngelOS; код свой. Просьба: «про мышь —
если можно сделать, давай, но с переключателем в Настройках».

Как работает.
  * Движение мыши читается напрямую (/dev/input/event*, группа input): считаем
    развороты по горизонтали. REVERSALS разворотов за WINDOW_S с общим путём больше
    MIN_TRAVEL — это встряхивание.
  * Увеличить саму стрелку в niri можно только правкой конфига курсора (а он у нас
    собирается из нескольких файлов и перекрашивается под обои) — поэтому вместо
    этого вокруг указателя на секунду расходятся кольца цветом акцента обоев.
  * Где указатель, niri не сообщает: на каждый монитор кладётся прозрачный слой,
    первое же движение мыши даёт ему координаты; после этого слой становится
    «прозрачным» для ввода — щелчки проходят насквозь, кольца ничего не блокируют.

Процессор: движения читаются пачками раз в 20 мс и только пока мышь движется;
в покое процесс спит. При запущенной игре (cs2, gamescope) мышь не читается вовсе.
"""
import math
import os
import re
import select
import struct
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OFF = os.path.expanduser("~/.config/hypr/state/cursor-shake-off")
MODE_FILE = os.path.expanduser("~/.config/hypr/state/cursor-shake-mode")


def mode():
    try:
        m = open(MODE_FILE).read().strip()
        return m if m in ("grow", "rings") else "grow"
    except OSError:
        return "grow"


if sys.argv[1:2] == ["mode"]:
    if sys.argv[2:3] in (["grow"], ["rings"]):
        os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
        with open(MODE_FILE, "w") as f:
            f.write(sys.argv[2] + "\n")
    print(mode())
    sys.exit(0)

if sys.argv[1:2] in (["on"], ["off"], ["status"]):
    if sys.argv[1] == "on":
        try:
            os.remove(OFF)
        except OSError:
            pass
    elif sys.argv[1] == "off":
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
    print("off" if os.path.exists(OFF) else "on")
    sys.exit(0)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402
import cairo  # noqa: E402

import popup_theme  # noqa: E402

WINDOW_S = 0.6           # за сколько секунд должны уложиться развороты
REVERSALS = 5            # сколько разворотов по горизонтали (4 → 5: срабатывало от лёгкого движения, 04.10)
MIN_STEP = 90            # разворот считается, если до него мышь прошла столько единиц (было 25)
MIN_TRAVEL = 1800        # общий путь за окно (было 500 — «рандомно срабатывает, чуть подвигаю»)
COOLDOWN_S = 1.2
SHOW_MS = 900
GAMES = (b"cs2", b"gamescope")
FMT = "llHHi"
SIZE = struct.calcsize(FMT)
EV_REL, REL_X = 2, 0


def mice():
    out = []
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return out
    for b in blocks:
        h = next((l for l in b.splitlines() if l.startswith("H: Handlers=")), "")
        if "mouse" not in h:
            continue
        # «H: Handlers=event5 mouse0» — event может стоять сразу за «=», поэтому не split()
        out += ["/dev/input/" + e for e in re.findall(r"\bevent\d+", h)]
    return out


def gaming():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


MAX_SCALE = 24.0         # во сколько раз курсор вырастает (4 → 10 → 16 → 24: «предел маленький, сделай больше»)
GROW_EXP = 1.0           # рост плавный: ×24 примерно за 3 с тряски (1.5 было «слишком быстро»)
                         # (линейный рост 8 «раз»/с казался резким — «пусть плавно растёт»)
CALM_S = 0.22            # сколько без разворотов — тряска кончилась
SHRINK_S = 0.5           # за сколько курсор возвращается к обычному размеру
BASE = 24                # обычный размер курсора (cursor-size)


def cursor_image():
    """(cairo-поверхность самого крупного кадра стрелки темы, её размер, hot x, hot y)."""
    import struct as st
    try:
        from gi.repository import Gio
        theme = Gio.Settings.new("org.gnome.desktop.interface").get_string("cursor-theme")
    except Exception:
        theme = ""
    for base in (os.path.expanduser("~/.local/share/icons"), os.path.expanduser("~/.icons"),
                 "/usr/share/icons"):
        for name in ("left_ptr", "default", "arrow"):
            path = os.path.join(base, theme, "cursors", name)
            if not theme or not os.path.exists(path):
                continue
            try:
                d = open(path, "rb").read()
                n = st.unpack_from("<I", d, 12)[0]
                best = None
                for i in range(n):
                    t, sub, pos = st.unpack_from("<III", d, 16 + 12 * i)
                    if t == 0xfffd0002 and (best is None or sub > best[0]):
                        best = (sub, pos)
                if not best:
                    continue
                _hs, _t, _sub, _v, w, h, xh, yh, _dl = st.unpack_from("<9I", d, best[1])
                px = bytearray(d[best[1] + 36:best[1] + 36 + w * h * 4])   # ARGB, премножено
                surf = cairo.ImageSurface.create_for_data(px, cairo.FORMAT_ARGB32, w, h, w * 4)
                return surf, px, best[0], xh, yh
            except (OSError, ValueError, st.error):
                continue
    return None


class Grow(Gtk.Window):
    """Слой на монитор на время эффекта: прячет настоящий курсор, рисует большой."""

    def __init__(self, monitor, owner):
        super().__init__()
        self.owner = owner
        self.pos = None
        self.drawn = None
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-cursor-shake")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK
                        | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("enter-notify-event", self.on_motion)
        self.connect("leave-notify-event", self.on_leave)
        self.connect("button-press-event", lambda *_a: self.owner.finish() or True)
        self.connect("realize", self.on_realize)
        self.connect("draw", self.on_draw)

    def on_realize(self, _w):
        self.get_window().set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "none"))

    def on_motion(self, _w, ev):
        self.pos = (ev.x, ev.y)
        self.owner.here = self
        self.redraw()
        return False

    def on_leave(self, _w, _ev):
        self.pos = None
        self.redraw()
        return False

    def rect(self):
        img = self.owner.img
        if self.pos is None or not img:
            return None
        k = BASE * self.owner.scale / img[2]
        x, y = self.pos
        return (int(x - img[3] * k) - 2, int(y - img[4] * k) - 2,
                int(img[0].get_width() * k) + 5, int(img[0].get_height() * k) + 5)

    def redraw(self):
        """Перерисовать только место старого и нового курсора."""
        new = self.rect()
        for r in (self.drawn, new):
            if r:
                self.queue_draw_area(*r)
        self.drawn = new

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        img = self.owner.img
        if self.pos is None or not img:
            return True
        cr.set_operator(cairo.OPERATOR_OVER)
        k = BASE * self.owner.scale / img[2]
        x, y = self.pos
        cr.translate(x - img[3] * k, y - img[4] * k)
        cr.scale(k, k)
        cr.set_source_surface(img[0], 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)     # тема пиксельная — без мыла
        cr.paint()
        return True


class Grower:
    """Режим grow: растёт, пока идёт тряска (feed), потом сжимается и убирает слои."""

    def __init__(self):
        self.wins = []
        self.img = None
        self.scale = 1.0
        self.here = None
        self.last_shake = 0.0
        self.t_prev = 0.0

    def trigger(self):
        if os.path.exists(OFF):
            return False
        self.last_shake = time.monotonic()
        if self.wins:
            return False
        self.img = cursor_image()
        if not self.img:
            return False
        self.scale = 1.0
        d = Gdk.Display.get_default()
        for i in range(d.get_n_monitors()):
            w = Grow(d.get_monitor(i), self)
            w.show_all()
            self.wins.append(w)
        self.t_prev = time.monotonic()
        GLib.timeout_add(16, self.tick)
        return False

    def feed(self):
        """Тряска продолжается (разворот) — расти дальше."""
        self.last_shake = time.monotonic()
        return False

    def tick(self):
        if not self.wins:
            return False
        now = time.monotonic()
        dt, self.t_prev = now - self.t_prev, now
        if now - self.last_shake < CALM_S:
            # от малого — медленно, дальше быстрее: на глаз рост ровный
            self.scale = min(MAX_SCALE, self.scale * math.exp(GROW_EXP * dt))
        else:
            # обратно — тоже по экспоненте, от любого размера за SHRINK_S
            self.scale *= math.exp(-math.log(MAX_SCALE) * dt / SHRINK_S)
            if self.scale <= 1.02:
                self.finish()
                return False
        for w in self.wins:
            if w.pos is not None:
                w.redraw()
        return True

    def finish(self):
        for w in self.wins:
            w.destroy()
        self.wins = []
        self.here = None
        self.scale = 1.0


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Ring(Gtk.Window):
    """Прозрачный слой на монитор: ловит первое движение, рисует кольца, ввод пропускает."""

    def __init__(self, monitor, owner):
        super().__init__()
        self.owner = owner
        self.pos = None
        self.t0 = 0.0
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-cursor-shake")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
        self.connect("motion-notify-event", self.on_motion)
        self.connect("enter-notify-event", self.on_motion)
        self.connect("draw", self.on_draw)

    def passthrough(self):
        # пустая область ввода: щелчки и движение идут сквозь слой
        w = self.get_window()
        if w:
            w.input_shape_combine_region(cairo.Region(), 0, 0)

    def on_motion(self, _w, ev):
        if self.pos is None and self.owner.claim(self):
            self.pos = (ev.x, ev.y)
            self.t0 = time.monotonic()
            self.passthrough()
            GLib.timeout_add(16, self.tick)
        return False

    def tick(self):
        if (time.monotonic() - self.t0) * 1000 >= SHOW_MS:
            self.owner.finish()
            return False
        self.queue_draw()
        return True

    def on_draw(self, _w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        if self.pos is None:
            return True
        cr.set_operator(cairo.OPERATOR_OVER)
        k = min(1.0, (time.monotonic() - self.t0) * 1000 / SHOW_MS)
        r, g, b = self.owner.rgb
        x, y = self.pos
        # три кольца расходятся и гаснут; квадратные концы линий — под пиксельный стиль
        for i in range(3):
            ph = k - i * 0.16
            if ph <= 0:
                continue
            rad = 14 + 86 * ph
            cr.set_source_rgba(r, g, b, max(0.0, 0.85 * (1 - ph)))
            cr.set_line_width(max(2.0, 7 * (1 - ph)))
            cr.arc(x, y, rad, 0, 2 * math.pi)
            cr.stroke()
        cr.set_source_rgba(r, g, b, max(0.0, 0.35 * (1 - k)))
        cr.arc(x, y, 12, 0, 2 * math.pi)
        cr.fill()
        return True


class Shaker:
    def __init__(self):
        self.rings = []
        self.owner_ring = None
        self.rgb = (0.7, 0.77, 1.0)
        self.busy_until = 0.0

    def trigger(self):
        if self.rings or os.path.exists(OFF):
            return False
        try:
            self.rgb = hexrgb(popup_theme.palette()["primary"])
        except Exception:
            pass
        self.owner_ring = None
        d = Gdk.Display.get_default()
        for i in range(d.get_n_monitors()):
            w = Ring(d.get_monitor(i), self)
            w.show_all()
            self.rings.append(w)
        GLib.timeout_add(700, self.give_up)      # мышь так и не шевельнулась над слоем
        return False

    def claim(self, ring):
        if self.owner_ring is None:
            self.owner_ring = ring
            for w in self.rings:
                if w is not ring:
                    w.passthrough()
            return True
        return False

    def give_up(self):
        if self.owner_ring is None:
            self.finish()
        return False

    def finish(self):
        for w in self.rings:
            w.destroy()
        self.rings = []
        self.owner_ring = None


EV_ABS, ABS_X, BTN_TOUCH = 3, 0, 0x14a
PAD_UNITS = 6000          # вся ширина тачпада — столько «отсчётов мыши»


def abs_scale(fd):
    """Множитель для тачпада: PAD_UNITS / ширина диапазона ABS_X; 0 — у устройства нет ABS_X."""
    import array
    import fcntl
    buf = array.array("i", [0] * 6)                 # struct input_absinfo
    try:
        fcntl.ioctl(fd, 0x80184540 + ABS_X, buf)    # EVIOCGABS(ABS_X)
    except OSError:
        return 0
    span = buf[2] - buf[1]
    return PAD_UNITS / span if span > 0 else 0


def watch(shaker):
    feed = getattr(shaker, "feed", None)
    pad = {}                 # fd → [масштаб ABS_X, прошлый X] (тачпады)
    held = set()             # зажатые кнопки мыши
    fds, next_scan, game = {}, 0.0, False
    hist = []            # (время, |dx|) — путь; развороты считаем отдельно
    turns = []           # времена разворотов
    last_dir, run = 0, 0
    cool = 0.0
    while True:
        now = time.monotonic()
        if now >= next_scan:
            next_scan = now + 10
            game = gaming() or os.path.exists(OFF)
            want = set() if game else set(mice())
            if want != set(fds.values()):
                for fd in list(fds):
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                fds = {}
                pad.clear()
                for p in want:
                    try:
                        fd = os.open(p, os.O_RDONLY | os.O_NONBLOCK)
                        fds[fd] = p
                        pad[fd] = [abs_scale(fd), None]     # тачпад: масштаб и прошлый X
                    except OSError:
                        pass
        if not fds:
            time.sleep(5)
            continue
        try:
            r, _, _ = select.select(list(fds), [], [], 5)
        except (OSError, ValueError):
            next_scan = 0
            continue
        if not r:
            continue
        time.sleep(0.02)                         # копим пачку — меньше пробуждений
        dx = 0
        for fd in r:
            try:
                data = os.read(fd, SIZE * 256)
            except BlockingIOError:
                continue
            except OSError:
                next_scan = 0
                continue
            for i in range(0, len(data) - SIZE + 1, SIZE):
                _s, _us, typ, code, val = struct.unpack_from(FMT, data, i)
                if typ == EV_REL and code == REL_X:
                    dx += val
                elif typ == EV_ABS and code == ABS_X and fd in pad and pad[fd][0]:
                    # Тачпад шлёт не сдвиги, а место пальца (04.10.2026: «когда тачпадом
                    # дёргаю, курсор не увеличивается»): сдвиг — разница с прошлым X,
                    # в масштабе «вся ширина тачпада = PAD_UNITS отсчётов мыши».
                    if pad[fd][1] is not None:
                        dx += round((val - pad[fd][1]) * pad[fd][0])
                    pad[fd][1] = val
                elif typ == 1 and code == BTN_TOUCH and val == 0 and fd in pad:
                    pad[fd][1] = None                     # палец поднят — новый отсчёт
                elif typ == 1 and 0x110 <= code <= 0x117:      # кнопки мыши
                    if val:
                        held.add(code)
                    else:
                        held.discard(code)
        # Кнопка зажата — это перенос или растягивание окна (Super+ЛКМ/ПКМ), а не тряска:
        # курсор рос прямо во время растягивания, и оно подвисало (03.10.2026).
        if held:
            turns, hist, last_dir, run = [], [], 0, 0
            continue
        if dx == 0:
            continue
        now = time.monotonic()
        d = 1 if dx > 0 else -1
        if d == last_dir:
            run += abs(dx)
        else:
            if last_dir != 0 and run >= MIN_STEP:
                turns.append(now)
                if feed:
                    GLib.idle_add(feed)          # эффект уже идёт: тряска продолжается
            last_dir, run = d, abs(dx)
        hist.append((now, abs(dx)))
        hist = [h for h in hist if now - h[0] <= WINDOW_S]
        turns = [t for t in turns if now - t <= WINDOW_S]
        if feed and shaker.wins:
            continue                             # уже растёт — порог не нужен
        if now >= cool and len(turns) >= REVERSALS and sum(h[1] for h in hist) >= MIN_TRAVEL:
            cool = now + COOLDOWN_S
            turns, hist = [], []
            GLib.idle_add(shaker.trigger)


def main():
    if sys.argv[1:2] != ["test"]:
        me = os.getpid()
        for p in os.listdir("/proc"):
            if p.isdigit() and int(p) != me:
                try:
                    argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
                except OSError:
                    continue
                if len(argv) >= 2 and os.path.basename(argv[1]) == b"cursor_shake.py" \
                        and (len(argv) == 2 or argv[2] == b""):
                    return
    shaker = Grower() if mode() == "grow" else Shaker()
    if sys.argv[1:2] == ["test"]:
        GLib.idle_add(shaker.trigger)
        GLib.timeout_add(2500, Gtk.main_quit)
    else:
        threading.Thread(target=watch, args=(shaker,), daemon=True).start()
    Gtk.main()


if __name__ == "__main__":
    main()
