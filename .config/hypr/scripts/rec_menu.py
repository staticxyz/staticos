#!/usr/bin/env python3
"""Меню Recorder — одно окно-слой GTK вместо цепочки rofi. 04.10.2026.

Было: rec_area.sh звал rofi на каждое меню — верхнее, потом подменю, потом снова
верхнее по «Назад». Каждое подменю — новый запуск rofi, окно гасло и появлялось
снова (просьба: «ощущение, будто окно пересоздаётся»). Теперь всё дерево меню
приходит сюда разом, а переходы по подменю — внутри одного окна, с коротким
сдвигом списка (ANIM_MS).

    rec_menu.py [JSON] [--start ИМЯ]      дерево — аргументом или на stdin

    {"title": "Recorder", "back": "󰁍  Назад",
     "items": [{"label": "󰵸  Gif", "title": "Gif", "items": [...]},   — подменю
               {"label": "󰑙  Replay: off", "value": "..."}]}          — пункт

У пункта либо value (нет — берётся label), либо items — вложенное подменю.
--start ИМЯ — открыть сразу подменю верхнего уровня с таким заголовком (REC_TOP
в rec_area.sh: «Записать видео» из меню рабочего стола); «Назад» оттуда — в верхнее.

Итог: код 0 и выбранное value на stdout; 1 — выход (Esc/h/щелчок мимо в верхнем
меню, щелчок мимо или крестик в любом); 3 — ошибка (rec_area.sh тогда показывает
старое меню rofi).

Клавиши — по keycode, раскладка не важна (русская тоже):
    j/k, Ctrl+J/K, ↓/↑, Ctrl+N/P, колесо   — по списку;  Home/End — первый/последний
    l, Enter, →, Ctrl+L, Ctrl+M            — войти в подменю / выбрать
    h, Esc, ←, Backspace, Ctrl+H, Ctrl+[   — назад (в верхнем меню — выход)
    q, Ctrl+G                              — выход
Мышь: наведение подсвечивает, щелчок по пункту — выбрать (срабатывает на
отпускании, если отпустили на том же пункте: отпускание не улетает в выделение
области), по заголовку подменю — назад, мимо окна или по крестику — выход.

Вид — стиль Recorder (state/recorder-style, `rec_area.sh style`): default — окно XP,
как у буфера обмена (clipboard_win.py) в default; skeet и beta — его же родственники.
Цвета — из обоев: skeet/beta — rec_style.colors(), default — тона «Пуска»
(xpbar_colors) и фон kitty, как у буфера. Слой OVERLAY по центру монитора с
фокусом, клавиатура exclusive; щелчок мимо ловят прозрачные слои во весь экран
(«jarvis-recmenu-catch», TOP, их размывает niri — как под rofi).

Скорость: до первого кадра — только gi/GTK/Pango и палитра; звук (ui_sound) —
после первого кадра. Выход — os._exit сразу из обработчика: выход через
Gtk.main_quit у буфера обмена однажды завис в gdk_flush (память clipboard-window).
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXIT_CANCEL, EXIT_ERROR = 1, 3
ANIM_MS = 130                       # сдвиг списка при входе в подменю и назад
FONT = "PxPlus HP 100LX 6x8 Jarvis"
NAMESPACE = "jarvis-recmenu"
TITLE = "Recorder.exe"
BACK = "󰁍  Назад"
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/recorder-style")
MATUGEN = os.path.expanduser("~/.cache/matugen")
ARROW_BMP = ("#...", "##..", "###.", "####", "###.", "##..", "#...")
REC_BMP = ("..###..", ".#####.", "#######", "#######", "#######", ".#####.", "..###..")
X_BMP = ("#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#")

# keycode (evdev + 8) — одинаковы в любой раскладке
K_ESC, K_RET, K_KPENT, K_BS = 9, 36, 104, 22
K_H, K_J, K_K, K_L, K_Q, K_N, K_P, K_M, K_G, K_BRACKET = 43, 44, 45, 46, 24, 57, 33, 58, 42, 34
K_UP, K_DOWN, K_LEFT, K_RIGHT, K_HOME, K_END = 111, 116, 113, 114, 110, 115


def die(msg):
    try:
        print("rec_menu: " + msg, file=sys.stderr)
        sys.stderr.flush()
    finally:
        os._exit(EXIT_ERROR)


# Импорт gi тянет asyncio (~150 мс) — подменяем пустышкой на время импорта, как в
# clipboard_win.py. Не вышло — импортируем как есть.
_stub = None
if __name__ == "__main__" and "gi" not in sys.modules and "asyncio" not in sys.modules:
    import types
    _stub = types.ModuleType("asyncio")
    _stub.InvalidStateError = type("InvalidStateError", (Exception,), {})
    _stub._get_running_loop = _stub.get_running_loop = lambda: None
    sys.modules["asyncio"] = _stub


def _load_gi():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: F401


try:
    try:
        _load_gi()
    except Exception:
        if _stub is None:
            raise
        for _k in [k for k in sys.modules if k == "asyncio" or k == "gi" or k.startswith("gi.")]:
            del sys.modules[_k]
        _stub = None
        _load_gi()
    if _stub is not None and sys.modules.get("asyncio") is _stub:
        del sys.modules["asyncio"]
    import cairo
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo
except Exception as _err:           # нет GTK/слоёв — пусть rec_area.sh покажет rofi
    die("импорт: %s" % _err)


# ── цвета ───────────────────────────────────────────────────────────────────
def hexrgb(h, default=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError, AttributeError):
        return default


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def read_style():
    try:
        v = open(STYLE_FILE).read().strip().lower()
    except OSError:
        return "default"
    return v if v in ("default", "skeet", "beta") else "default"


def xp_theme():
    """Тона default — те же, что load_theme() буфера обмена: полоса заголовка —
    «Пуск» (xpbar_colors), фон — палитра kitty."""
    T = {}
    try:
        kitty = dict(l.split(None, 1) for l in open(os.path.join(MATUGEN, "colors-kitty.conf")).read().splitlines()
                     if len(l.split(None, 1)) == 2 and not l.startswith("#"))
    except OSError:
        kitty = {}
    T["bg"] = hexrgb(kitty.get("background", "#10131c"), (0.06, 0.07, 0.11))
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    for k, d in (("st_hi", "#9fb4f5"), ("st_top", "#7f95d8"), ("st_mid", "#5f74b4"),
                 ("st_bot", "#465a94"), ("st_hover", "#8ea4e8"), ("st_dark", "#0a0c12"),
                 ("line2", "#3a4a7a"), ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("error", "#ffb4ab"), ("primary", "#b4c5ff")):
        T[k] = hexrgb(xc.get(k, d), hexrgb(d))
    T["fg"] = T["on_surface"]
    T["dim"] = mix(T["on_surface_variant"], T["bg"], 0.30)
    return T


def style_colors(style):
    """Словарь цветов (кортежи 0..1). skeet/beta — из rec_style.colors(), недостающие
    роли досчитаны так же, как в clipboard_win.style_colors()."""
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "default":
        T = xp_theme()
        return dict(T, win_bg=T["bg"], text=T["fg"], sel_bg=T["st_hi"], sel_text=T["st_dark"],
                    row=T["fg"], arrow=T["dim"])
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    import rec_style
    raw = rec_style.colors(style)
    c = {k: (hexrgb(v) if isinstance(v, str) else [hexrgb(x) for x in v]) for k, v in raw.items()}
    try:
        err = hexrgb(__import__("popup_theme").palette().get("error", "#ffb4ab"))
    except Exception:
        err = hexrgb("#ffb4ab")
    c["err"] = err
    if style == "skeet":
        acc = c["acc"]
        c.update(line1_on=mix(c["line1"], acc, 0.45), dot=mix((0x18 / 255,) * 3, acc, 0.05),
                 icon_on=mix(hexrgb("#e2e2e2"), acc, 0.22),
                 win_bg=c["bg"], sel_bg=c["field_l"], sel_text=c["acc_l"], arrow=c["dim"])
    else:
        c.update(win_bg=c["bg"], acc_text=c["acc"], hover=mix(c["bg"], c["acc"], 0.14),
                 line_soft=mix(c["card"], c["text"], 0.08), sel_bg=c["sel"], arrow=c["dim"])
    return c


def geometry(style):
    """Размеры стиля: рамка, заголовок, кегль, строка — как у буфера обмена."""
    # Крупнее буфера в 1,3–1,5 раза (04.10.2026: «сделай чуть больше»):
    # пункты во всех стилях — 16 px (на нём PxPlus чёткий), skeet тоже.
    if style == "skeet":
        return dict(BORDER=6, TOP=8, TB=28, PX=16, ROW=36, PAD=14, GROUP=12, K=2)
    if style == "beta":
        return dict(BORDER=2, TOP=2, TB=34, PX=16, ROW=44, PAD=14, GROUP=0, K=2)
    return dict(BORDER=3, TOP=3, TB=30, PX=16, ROW=42, PAD=12, GROUP=0, K=2)


def draw_bitmap(cr, rows, x, y, k=1):
    """Точки значка прямоугольниками k×k; соседние в строке сливаются в один."""
    for r, row in enumerate(rows):
        c, n = 0, len(row)
        while c < n:
            if row[c] == "#":
                e = c
                while e < n and row[e] == "#":
                    e += 1
                cr.rectangle(x + c * k, y + r * k, (e - c) * k, k)
                c = e
            else:
                c += 1
    cr.fill()


# ── дерево меню ─────────────────────────────────────────────────────────────
def bare(label):
    """«󰵸  Gif» → «Gif»: заголовок подменю без значка."""
    i = 0
    while i < len(label) and not label[i].isalnum():
        i += 1
    return label[i:] or label


def parse_tree(node, title, back):
    items = []
    for it in node.get("items") or []:
        if isinstance(it, str):
            it = {"label": it}
        lab = str(it.get("label", ""))
        if isinstance(it.get("items"), list):
            items.append(dict(label=lab, sub=parse_tree(it, str(it.get("title") or bare(lab)), back)))
        else:
            items.append(dict(label=lab, value=str(it.get("value", lab))))
    if not items:
        raise ValueError("пустое меню «%s»" % title)
    return dict(title=title, items=items, back=back)


def rows_of(menu, depth):
    """Строки меню на экране: в подменю первой идёт «Назад»."""
    if depth == 0:
        return menu["items"]
    return [dict(label=menu["back"], is_back=True)] + menu["items"]


def all_menus(menu):
    yield menu
    for it in menu["items"]:
        if "sub" in it:
            yield from all_menus(it["sub"])


# ── окна ────────────────────────────────────────────────────────────────────
class Catcher(Gtk.Window):
    """Прозрачный слой во весь монитор уровнем ниже меню: щелчок мимо — выход."""

    def __init__(self, app, monitor):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE + "-catch")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", lambda *_a: app.cancel() or True)

    @staticmethod
    def on_draw(_w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        return True


class Win(Gtk.Window):
    """Слой по центру монитора с фокусом (монитор не задан — niri ставит на него).
    Размер — под самое длинное меню дерева: меню короче рисуется посередине, а вокруг
    прозрачно, так что переход между меню не меняет размер поверхности."""

    def __init__(self, app, w, h):
        super().__init__()
        self.set_title(NAMESPACE)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(w, h)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.area.connect("draw", app.on_draw)
        self.area.connect("button-press-event", app.on_press)
        self.area.connect("button-release-event", app.on_release)
        self.area.connect("motion-notify-event", app.on_motion)
        self.area.connect("leave-notify-event", app.on_leave)
        self.area.connect("scroll-event", app.on_scroll)
        self.connect("key-press-event", app.on_key)
        self.connect("key-release-event", app.on_key_release)
        self.add(self.area)


class App:
    def __init__(self, tree, start=None, test=False):
        self.test = test
        self.result = None                  # в проверке: (код, значение) вместо выхода
        self.root = tree
        self.style = read_style()
        self.G = geometry(self.style)
        self.C = style_colors(self.style)
        self.fd = Pango.FontDescription(FONT)
        self.fd.set_absolute_size(self.G["PX"] * Pango.SCALE)
        self.fo = cairo.FontOptions()
        self.fo.set_antialias(cairo.ANTIALIAS_GRAY)
        self.fo.set_hint_style(cairo.HINT_STYLE_FULL)
        self.fo.set_hint_metrics(cairo.HINT_METRICS_ON)
        self.dots = None
        if self.style == "skeet":           # точечный узор фона skeet, как у буфера
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
            tc = cairo.Context(tile)
            tc.set_source_rgb(*self.C["dot"])
            tc.rectangle(0, 0, 1, 1)
            tc.rectangle(2, 2, 1, 1)
            tc.fill()
            self.dots = cairo.SurfacePattern(tile)
            self.dots.set_extend(cairo.EXTEND_REPEAT)
        self.measure()
        self.stack = []                     # [(меню, выбранная строка)] — путь назад
        self.menu, self.sel = tree, 0
        if start:
            want = start.strip().lower()
            for i, it in enumerate(tree["items"]):
                if "sub" in it and want in (it["sub"]["title"].lower(), bare(it["label"]).lower()):
                    self.stack, self.menu, self.sel = [(tree, i)], it["sub"], 1
                    break
        self.rows = rows_of(self.menu, len(self.stack))
        self.anim = None                    # (t0, направление, старое меню, его строки, выбор, высота)
        self.hover_cap = False
        self.press = None                   # (поколение меню, строка) нажатия мыши
        self.gen = 0                        # растёт при каждой смене меню
        self.down = set()                   # нажатые клавиши — отличить автоповтор
        self.first = True
        self.catchers = []
        self.win = Win(self, self.SW, self.SH)

    # ── размеры ────────────────────────────────────────────────────────────
    def layout(self, cr, text, width=None):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.fd)
        lay.set_text(text, -1)
        if width:
            lay.set_width(int(width) * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        return lay

    def measure(self):
        """Ширина — по самой длинной строке дерева, высота поверхности — по самому
        длинному меню (с «Назад»)."""
        G = self.G
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
        cr.set_font_options(self.fo)
        longest = 0
        for depth, m in self.walk(self.root, 0):
            for r in rows_of(m, depth):
                longest = max(longest, self.layout(cr, r["label"]).get_pixel_size()[0])
            longest = max(longest, self.layout(cr, TITLE + " » " + m["title"]).get_pixel_size()[0] - 40)
        self.LH = max(G["PX"] + 4, self.layout(cr, "Ag").get_pixel_size()[1])
        side = G["BORDER"] + G["PAD"] + (8 if self.style == "skeet" else 0)
        self.SW = max(420, side * 2 + 20 + longest + 44)
        self.SH = max(self.panel_h(len(rows_of(m, d))) for d, m in self.walk(self.root, 0))

    def walk(self, menu, depth):
        yield depth, menu
        for it in menu["items"]:
            if "sub" in it:
                yield from self.walk(it["sub"], depth + 1)

    def list_top(self):
        G = self.G
        return G["TOP"] + G["TB"] + G["PAD"] + (G["GROUP"] + 4 if G["GROUP"] else 0)

    def panel_h(self, n):
        G = self.G
        extra = 8 if G["GROUP"] else (4 if self.style == "beta" else 0)
        return self.list_top() + n * G["ROW"] + extra + G["PAD"] + G["BORDER"]

    def list_box(self):
        """x и ширина строк списка."""
        G = self.G
        inset = 10 if self.style == "skeet" else (1 if self.style == "beta" else 0)
        x = G["BORDER"] + G["PAD"] + inset
        return x, self.SW - 2 * x

    # ── показ и выход ──────────────────────────────────────────────────────
    def show(self):
        if not self.test:
            display = Gdk.Display.get_default()
            for i in range(display.get_n_monitors()):
                c = Catcher(self, display.get_monitor(i))
                c.show_all()
                self.catchers.append(c)
        self.win.show_all()

    def sound(self, event):
        if self.test:
            return
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import ui_sound
            ui_sound.play(event)         # pw-play в своей сессии — переживёт наш выход
        except Exception:
            pass

    def finish(self, code, value=None):
        if self.test:
            self.result = (code, value)
            return
        if code == 0:
            self.sound("click")
            sys.stdout.write(value + "\n")
        sys.stdout.flush()
        os._exit(code)

    def cancel(self):
        self.finish(EXIT_CANCEL)

    def after_first_frame(self):
        self.sound("menu")
        return False

    # ── переходы ───────────────────────────────────────────────────────────
    def go(self, menu, depth_dir, sel):
        """Сменить меню в том же окне: depth_dir 1 — вглубь, -1 — назад."""
        old = (self.menu, self.rows, self.sel, self.cur_h())
        self.menu = menu
        self.rows = rows_of(menu, len(self.stack))
        self.sel = max(0, min(sel, len(self.rows) - 1))
        self.gen += 1
        self.press = None
        self.anim = (time.monotonic(), depth_dir) + old if ANIM_MS > 0 else None
        self.win.area.queue_draw()

    def enter(self, i):
        self.stack.append((self.menu, i))
        self.go(self.rows[i]["sub"], 1, 1)       # первым выбран первый настоящий пункт

    def back(self):
        if not self.stack:
            self.cancel()
            return
        menu, i = self.stack.pop()
        self.go(menu, -1, i)

    def activate(self, i=None):
        i = self.sel if i is None else i
        if not 0 <= i < len(self.rows):
            return
        r = self.rows[i]
        if r.get("is_back"):
            self.back()
        elif "sub" in r:
            self.enter(i)
        else:
            self.finish(0, r["value"])

    def move(self, d, to=None):
        n = len(self.rows)
        self.sel = (to if to is not None else (self.sel + d) % n) % n
        self.win.area.queue_draw()

    # ── клавиши ────────────────────────────────────────────────────────────
    def on_key(self, _w, ev):
        code, kv = ev.hardware_keycode, ev.keyval
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        # Автоповтор GTK шлёт нажатия без отпусканий: зажатый Enter не должен сам
        # провалиться в подменю и тут же выбрать там пункт. Повтор разрешён только
        # движению по списку.
        rep = code in self.down
        self.down.add(code)
        if code in (K_DOWN, K_J) or kv == Gdk.KEY_Down or (ctrl and code == K_N):
            self.move(1)
        elif code in (K_UP, K_K) or kv == Gdk.KEY_Up or (ctrl and code == K_P):
            self.move(-1)
        elif code == K_HOME:
            self.move(0, 0)
        elif code == K_END:
            self.move(0, len(self.rows) - 1)
        elif rep:
            pass
        elif code in (K_RET, K_KPENT, K_L, K_RIGHT) or (ctrl and code == K_M):
            self.activate()
        elif code in (K_ESC, K_H, K_LEFT, K_BS) or (ctrl and code == K_BRACKET):
            self.back()
        elif code == K_Q or (ctrl and code == K_G):
            self.cancel()
        return True

    def on_key_release(self, _w, ev):
        self.down.discard(ev.hardware_keycode)
        return True

    # ── мышь ───────────────────────────────────────────────────────────────
    def panel_rect(self):
        h = self.cur_h()
        return 0, (self.SH - h) // 2, self.SW, h

    def cap_zone(self):
        G = self.G
        _x, py, w, _h = self.panel_rect()
        s = G["TB"] - 8
        return w - G["BORDER"] - 4 - s, py + G["TOP"] + 4, s, s

    def zone_at(self, x, y):
        """'close', 'title', номер строки, None (внутри окна, мимо строк) или 'out'."""
        G = self.G
        px, py, pw, ph = self.panel_rect()
        if not (px <= x < px + pw and py <= y < py + ph):
            return "out"
        cx, cy, cw, ch = self.cap_zone()
        if cx <= x < cx + cw and cy <= y < cy + ch:
            return "close"
        if y < py + G["TOP"] + G["TB"]:
            return "title"
        lx, lw = self.list_box()
        top = py + self.list_top()
        if lx <= x < lx + lw and y >= top:
            i = int((y - top) // G["ROW"])
            if 0 <= i < len(self.rows):
                return i
        return None

    def on_press(self, _w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 1:
            return True
        z = self.zone_at(ev.x, ev.y)
        if z == "out":
            self.cancel()
        elif isinstance(z, int):
            self.sel = z
            self.press = (self.gen, z)
            self.win.area.queue_draw()
        else:
            self.press = (self.gen, z)
        return True

    def on_release(self, _w, ev):
        if ev.button != 1 or self.press is None:
            return True
        gen, z0 = self.press
        self.press = None
        if gen != self.gen or self.zone_at(ev.x, ev.y) != z0:
            return True
        if isinstance(z0, int):
            self.activate(z0)
        elif z0 == "close":
            self.cancel()
        elif z0 == "title" and self.stack:     # по заголовку подменю — назад, как было у rofi
            self.back()
        return True

    def on_motion(self, _w, ev):
        z = self.zone_at(ev.x, ev.y)
        cap = z == "close"
        if isinstance(z, int) and z != self.sel:
            self.sel = z
            self.win.area.queue_draw()
        if cap != self.hover_cap:
            self.hover_cap = cap
            self.win.area.queue_draw()
        return True

    def on_leave(self, *_a):
        if self.hover_cap:
            self.hover_cap = False
            self.win.area.queue_draw()
        return False

    def on_scroll(self, _w, ev):
        d = 0
        if ev.direction == Gdk.ScrollDirection.UP:
            d = -1
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            d = 1
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            d = 1 if ev.delta_y > 0 else (-1 if ev.delta_y < 0 else 0)
        if d:
            self.move(d)
        return True

    # ── рисование ──────────────────────────────────────────────────────────
    def progress(self):
        """Доля пройденной анимации 0..1 (с замедлением к концу); None — анимации нет."""
        if not self.anim:
            return None
        p = (time.monotonic() - self.anim[0]) * 1000 / ANIM_MS
        if p >= 1:
            self.anim = None
            return None
        return 1 - (1 - p) ** 3

    def cur_h(self):
        e = self.progress()
        h = self.panel_h(len(self.rows))
        if e is None:
            return h
        return round(self.anim[5] + (h - self.anim[5]) * e)

    def on_draw(self, _a, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_font_options(self.fo)
        try:
            self.render(cr)
        except Exception as err:               # окно без кадра хуже окна с огрехом
            print("rec_menu: кадр: %s" % err, file=sys.stderr)
        if self.anim:
            self.win.area.queue_draw()          # следующий кадр анимации
        if self.first:
            self.first = False
            GLib.idle_add(self.after_first_frame)
        return True

    def text(self, cr, s, x, y, color, width=None):
        lay = self.layout(cr, s, width)
        cr.set_source_rgb(*color)
        cr.move_to(int(x), int(y))
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()

    def rect_fill(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def rect_line(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()

    def band(self, cr, i, w, color, W, H):
        cr.set_source_rgb(*color)
        cr.rectangle(i, i, W - 2 * i, H - 2 * i)
        cr.rectangle(i + w, i + w, W - 2 * (i + w), H - 2 * (i + w))
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

    def title_text(self):
        return TITLE if not self.stack else "%s » %s" % (TITLE, self.menu["title"])

    def render(self, cr):
        C, G = self.C, self.G
        _px, py, W, H = self.panel_rect()
        cr.save()
        cr.translate(0, py)
        cr.rectangle(0, 0, W, H)
        cr.clip()
        cr.set_source_rgb(*C["win_bg"])
        cr.paint()
        if self.dots is not None:
            cr.set_source(self.dots)
            cr.paint()
        getattr(self, "frame_" + self.style)(cr, W, H)
        self.close_btn(cr)
        # список: во время анимации — старое меню уезжает, новое въезжает
        lx, lw = self.list_box()
        top = self.list_top()
        bottom = H - G["BORDER"] - G["PAD"] - (8 if G["GROUP"] else (4 if self.style == "beta" else 0))
        self.list_frame(cr, lx, top, lw, bottom - top)
        cr.save()
        cr.rectangle(lx, top - 1, lw, bottom - top + 2)
        cr.clip()
        e = self.progress()
        if e is None:
            self.draw_rows(cr, self.rows, self.sel, lx, top, lw, True)
        else:
            d, slide = self.anim[1], lw + 2 * G["PAD"]
            self.draw_rows(cr, self.anim[3], self.anim[4], lx - d * e * slide, top, lw, False)
            self.draw_rows(cr, self.rows, self.sel, lx + d * (1 - e) * slide, top, lw, True)
        cr.restore()
        cr.restore()

    def list_frame(self, cr, x, y, w, h):
        """Подложка списка: в skeet — группа с подписью-заголовком меню, в beta — карточка."""
        C = self.C
        if self.style == "skeet":
            gx, gy, gw, gh = x - 10, y - 12, w + 20, h + 22
            self.rect_line(cr, gx, gy, gw, gh, C["gline"])
            self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
            name = self.menu["title"]
            lay = self.layout(cr, name)
            lw = lay.get_pixel_size()[0]
            self.rect_fill(cr, gx + 10, gy - 1, lw + 8, 3, C["bg"])
            if self.dots is not None:
                cr.save()
                cr.rectangle(gx + 10, gy - 1, lw + 8, 3)
                cr.clip()
                cr.set_source(self.dots)
                cr.paint()
                cr.restore()
            self.text(cr, name, gx + 14, gy - self.G["PX"] // 2 - 1, C["text"])
        elif self.style == "beta":
            self.rect_fill(cr, x - 1, y - 1, w + 2, h + 2, C["card"])
            self.rect_line(cr, x - 1, y - 1, w + 2, h + 2, C["line"])

    def draw_rows(self, cr, rows, sel, x, top, w, live):
        C, G, st = self.C, self.G, self.style
        R = G["ROW"]
        for i, r in enumerate(rows):
            y = top + i * R
            on = i == sel
            if st == "default":
                ry, rh = y + 1, R - 2
                if on:
                    self.rect_fill(cr, x, ry, w, rh, C["sel_bg"])
                else:
                    self.rect_fill(cr, x, ry, w, rh, C["row"], 0.045)
            elif st == "skeet":
                ry, rh = y + 1, R - 2
                if on:
                    self.rect_fill(cr, x, ry, w, rh, C["sel_bg"])
                    self.rect_line(cr, x, ry, w, rh, C["gline"])
                    self.rect_fill(cr, x, ry, 3, rh, C["acc"])
            else:
                ry, rh = y, R
                if on:
                    self.rect_fill(cr, x, ry, w, rh, C["sel_bg"])
                    self.rect_fill(cr, x, ry, 3, rh, C["acc"])
                if i < len(rows) - 1:
                    self.rect_fill(cr, x, y + R - 1, w, 1, C["line_soft"])
            fg = C["sel_text"] if on else (C["dim"] if r.get("is_back") else C["text"])
            ty = ry + (rh - self.LH) // 2 + 1
            self.text(cr, r["label"], x + 16, ty, fg, w - 48)
            if "sub" in r:                       # стрелка «есть подменю»
                k = 2
                cr.set_source_rgb(*(C["sel_text"] if on else C["arrow"]))
                draw_bitmap(cr, ARROW_BMP, x + w - 14 - 4 * k, ry + (rh - 7 * k) // 2, k)

    # ── рамки трёх стилей ──────────────────────────────────────────────────
    def close_btn(self, cr):
        C, st = self.C, self.style
        x, y, w, h = self.cap_zone()
        y -= self.panel_rect()[1]
        hov = self.hover_cap
        if st == "skeet":
            g = cairo.LinearGradient(0, y, 0, y + h)
            g.add_color_stop_rgb(0, *C["field_l"])
            g.add_color_stop_rgb(1, *C["field"])
            cr.set_source(g)
            cr.rectangle(x, y, w, h)
            cr.fill()
            self.rect_line(cr, x, y, w, h, C["line3"])
            self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["gline"])
            ink = C["err"] if hov else C["dim"]
        elif st == "beta":
            self.rect_fill(cr, x, y, w, h, C["err"] if hov else C["field"])
            self.rect_line(cr, x, y, w, h, C["line_strong"])
            ink = C["bg"] if hov else C["text"]
        else:
            er = C["error"]
            top = tuple(0.5 * er[i] + 0.5 * C["st_hover"][i] for i in range(3))
            bot = tuple(0.55 * er[i] * 0.6 + 0.45 * C["st_bot"][i] for i in range(3))
            if hov:
                top = mix(top, (1, 1, 1), 0.18)
            g = cairo.LinearGradient(0, y, 0, y + h)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(x, y, w, h)
            cr.fill()
            self.rect_line(cr, x, y, w, h, C["st_hi"])
            ink = C["on_surface"]
        cr.set_source_rgb(*ink)
        draw_bitmap(cr, X_BMP, x + (w - 14) // 2, y + (h - 14) // 2, 2)

    def frame_default(self, cr, W, H):
        """Окно XP, как буфер обмена: рамка 3 px, полоса заголовка с градиентом «Пуска»."""
        C, G = self.C, self.G
        B, TB = G["BORDER"], G["TB"]
        self.band(cr, 0, B, C["st_mid"], W, H)
        x, y, w = B, B, W - 2 * B
        g = cairo.LinearGradient(0, y, 0, y + TB)
        for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(off, *C[key])
        cr.set_source(g)
        cr.rectangle(x, y, w, TB)
        cr.fill()
        self.rect_fill(cr, x, y + TB - 1, w, 1, C["st_dark"])
        ix, iy = x + 8, y + (TB - 16) // 2          # значок: квадратик с красной точкой записи
        self.rect_fill(cr, ix + 1, iy + 1, 16, 16, C["st_dark"])
        self.rect_fill(cr, ix, iy, 16, 16, C["on_surface"])
        cr.set_source_rgb(*mix(C["error"], (0.8, 0.1, 0.1), 0.5))
        draw_bitmap(cr, REC_BMP, ix + 1, iy + 1, 2)
        lay = self.layout(cr, self.title_text(), w - 30 - TB - 6)
        ty = y + (TB - lay.get_pixel_size()[1]) // 2
        cr.set_source_rgb(*C["st_dark"])
        cr.move_to(ix + 25, ty + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*C["on_surface"])
        cr.move_to(ix + 24, ty)
        PangoCairo.show_layout(cr, lay)

    def frame_skeet(self, cr, W, H):
        C, G = self.C, self.G
        B, TOP, TB = G["BORDER"], G["TOP"], G["TB"]
        for i, w, key in ((0, 1, "line1_on"), (1, 3, "line2"), (4, 1, "line1_on"), (5, 1, "line3")):
            self.band(cr, i, w, C[key], W, H)
        for dy, k in ((0, 0.0), (1, 0.55)):          # полоска сверху — три тона палитры
            g = cairo.LinearGradient(B, 0, W - B, 0)
            for off, col in zip((0, 0.5, 1), C["strip"]):
                g.add_color_stop_rgb(off, *mix(col, (0, 0, 0), k))
            cr.set_source(g)
            cr.rectangle(B, B + dy, W - 2 * B, 1)
            cr.fill()
        self.rect_fill(cr, B, TOP + TB - 2, W - 2 * B, 1, C["line2"])
        self.rect_fill(cr, B, TOP + TB - 1, W - 2 * B, 1, C["line3"])
        cr.set_source_rgb(*C["err"])
        draw_bitmap(cr, REC_BMP, B + 8, TOP + (TB - 14) // 2, 2)
        self.text(cr, self.title_text(), B + 8 + 14 + 10, TOP + (TB - G["PX"]) // 2 - 1, C["text"],
                  W - 2 * B - 40 - TB)

    def frame_beta(self, cr, W, H):
        C, G = self.C, self.G
        B, TOP, TB = G["BORDER"], G["TOP"], G["TB"]
        self.band(cr, 0, B, C["frame"], W, H)
        self.rect_fill(cr, B, TOP, W - 2 * B, TB, C["bar"])
        self.rect_fill(cr, B, TOP + TB - 1, W - 2 * B, 1, C["line"])
        cr.set_source_rgb(*C["err"])
        draw_bitmap(cr, REC_BMP, B + 8, TOP + (TB - 14) // 2, 2)
        self.text(cr, self.title_text(), B + 8 + 14 + 8, TOP + (TB - G["PX"]) // 2, C["text"],
                  W - 2 * B - 50 - TB)


# ── запуск ──────────────────────────────────────────────────────────────────
def read_args(argv):
    start, src = None, None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--start" and i + 1 < len(argv):
            start = argv[i + 1] or None
            i += 2
            continue
        if a != "-":
            src = a
        i += 1
    if src is None:
        src = sys.stdin.read()
    data = json.loads(src)
    tree = parse_tree(data, str(data.get("title") or "Recorder"), str(data.get("back") or BACK))
    return tree, start


def main():
    try:
        tree, start = read_args(sys.argv)
        ok = Gtk.init_check(sys.argv)
        if not (ok[0] if isinstance(ok, tuple) else ok):
            die("нет дисплея")
        if not GtkLayerShell.is_supported():
            die("слои (wlr-layer-shell) не поддерживаются")
        app = App(tree, start)
        app.show()
        Gtk.main()
    except SystemExit:
        raise
    except BaseException as err:          # любая ошибка — код 3: rec_area.sh покажет rofi
        import traceback
        traceback.print_exc()
        die("%s: %s" % (type(err).__name__, err))
    os._exit(EXIT_CANCEL)


if __name__ == "__main__":
    main()
