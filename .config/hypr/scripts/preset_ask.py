#!/usr/bin/env python3
"""Окно «сохранить пресет виджетов» — «Preset.exe», родня окна буфера обмена. 05.10.2026.

    preset_ask.py [ИМЯ…]   спросить название; напечатать его (пусто — отмена), выход 0

Аргументы — имена уже сохранённых пресетов, свежие сверху (их даёт
`desktop_widgets.py preset ask`). Выбор имени из списка — перезаписать тот пресет.

Пользователь сравнил снимки: прежнее окно (rofi -dmenu со своей темой, откат —
preset_ask.py.bak-rofi) «не похоже, чуть отличается от окна Буфера обмена». Теперь
это такое же окно, как clipboard_win.py: слой GtkLayerShell, всё рисует cairo, те же
рамки трёх стилей (default — XP, skeet, beta), полоса заголовка, шрифт и его кегли,
поле ввода на месте строки поиска, строки списка и подсказка снизу.

Что берётся у clipboard_win.py импортом (при импорте модулем он ничего не запускает:
pid-файл, сигналы и разбор argv — только под `__main__`): цвета (load_theme,
style_colors — палитра обоев и «Пуска»), размеры стиля (set_geometry → BORDER, TB,
PX, PAD…), шрифт, растровые значки, стекло (read_glass), файл стиля. Рисование —
копии его методов (рамки, заголовок, кнопка «закрыть», поле, группа/карточка списка,
строка, подвал), подогнанные под окно без вкладок. Значит, цвета и размеры окна
меняются вместе с буфером обмена сами; правка его рисования — переносить сюда.

Стиль — state/clipboard-style (его держит system_style.py по монитору в фокусе).
Слои — как у буфера: окно OVERLAY «jarvis-preset» (клавиатура EXCLUSIVE), щелчок мимо
ловят прозрачные слои «jarvis-preset-catch» на всех мониторах; оба размывает niri
(cfg/layer-rules.kdl, blur + xray false — как у буфера).

Клавиши
    печатать (и по-русски)                 — название в поле
    ←/→, Home/End, Ctrl+A/Ctrl+E           — курсор в поле
    Backspace / Delete                     — стереть знак до / после курсора
    Ctrl+Backspace, Ctrl+W                 — стереть слово до курсора
    Ctrl+U                                 — очистить поле
    Ctrl+V                                 — вставить из буфера (первая строка)
    ↑/↓, Ctrl+J/K, Alt+J/K, Ctrl+N/P       — по списку: имя строки встаёт в поле
    Enter                                  — сохранить под именем из поля
    двойной щелчок по строке               — сохранить под этим именем
    Esc, крестик, щелчок мимо окна         — отмена
Выбранная строка — всегда та, чьё имя сейчас в поле (её перезапишет): напечатали
другое имя — подсветка снимается, набрали имя существующего — встаёт на него.

Проверка без экрана: `import preset_ask; d = preset_ask.Dialog(names, test=True)` —
окна не создаётся; d.render_png(путь), d.on_key(событие), d.result. Переменные:
    JARVIS_PRESET_STYLE   стиль вместо state/clipboard-style
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cairo  # noqa: E402

import clipboard_win as cw  # noqa: E402  (импорт без побочных действий: всё запускаемое — под __main__)
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

T = cw.T                       # цвета буфера обмена (заполняет cw.load_theme)
mix = cw.mix
draw_bitmap = cw.draw_bitmap

NAMESPACE = "jarvis-preset"
TITLE = "Preset.exe"
PLACEHOLDER = "название пресета"
GROUP = "Пресеты"
EMPTY = "Пресетов пока нет"
HINT = "Enter — сохранить · Esc — отмена"
OVERWRITE = "перезаписать"
MAX_ROWS = 6                   # строк списка без прокрутки
MAX_LEN = 80                   # длина названия
RING = cw.RING                 # поле вокруг окна (у буфера сейчас 0: мимо ловят слои-ловцы)

# дискета 7×9 — значок заголовка (у буфера на этом месте — планшет CLIP_BMP 7×9)
DISK_BMP = ("######.", "#.##.##", "#.##..#", "#.....#", "#.....#",
            "#.###.#", "#.###.#", "#.###.#", "#######")
ICON_BMP = DISK_BMP            # значок заголовка; режим --ask ставит свой
# часы 7×9 — для Timer.exe (--ask)
CLOCK_BMP = (".#####.", "#.....#", "#..#..#", "#..#..#", "#..##.#", "#.....#", "#.....#",
             ".#####.", "..#.#..")
DATES = True                   # хвост с датами создания/правки — только у пресетов
# карандаш 9×9 — на месте лупы в поле ввода
PEN_BMP = ("......##.", ".....#..#", "....#..#.", "...#..#..", "..#..#...",
           ".#..#....", "#..#.....", "##.#.....", "###......")

W = cw.W
PRESETS = os.path.expanduser("~/.config/hypr/state/widget-presets")
_DATES = {}


def _when(t):
    import time as _t
    lt, now = _t.localtime(t), _t.localtime()
    return _t.strftime("%d.%m %H:%M" if lt.tm_year == now.tm_year else "%d.%m.%y %H:%M", lt)


def _sig(widgets):
    """Раскладка без мелочей привязки — для сравнения «изменён ли пресет»."""
    return sorted(json.dumps([w.get("type"), w.get("output"), bool(w.get("pinned")),
                              w.get("x"), w.get("y"), w.get("w"), w.get("h")]) for w in widgets)


def current_preset():
    """(имя, изменён) — пресет, который сейчас стоит (state/widget-preset-current пишет
    desktop_widgets.py при сохранении и загрузке); изменён — раскладка с тех пор другая."""
    try:
        name = open(os.path.join(os.path.dirname(PRESETS), "widget-preset-current")).read().strip()
    except OSError:
        return None, False
    if not name:
        return None, False
    try:
        live = json.load(open(os.path.join(os.path.dirname(PRESETS), "desktop-widgets.json")))["widgets"]
        snap = None
        for fn in os.listdir(PRESETS):
            if fn.endswith(".json"):
                d = json.load(open(os.path.join(PRESETS, fn)))
                if (d.get("name") or fn[:-5]) == name:
                    snap = d["widgets"]
                    break
        return name, snap is None or _sig(live) != _sig(snap)
    except (OSError, ValueError, KeyError):
        return name, False


def preset_dates(name, short=False):
    """«создан 05.10 17:15 · изм. 05.10 17:40» по файлу пресета (created / saved);
    short — одна дата: последней правки («изм. …»), а без правок — создания."""
    if not DATES:
        return ""
    if not _DATES:
        try:
            files = os.listdir(PRESETS)
        except OSError:
            files = []
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                d = json.load(open(os.path.join(PRESETS, fn)))
                saved = int(d.get("saved") or 0)
                created = int(d.get("created") or saved)
                _DATES[d.get("name") or fn[:-5]] = (created, saved)
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        _DATES.setdefault("", (0, 0))              # прочитано (даже если пусто)
    created, saved = _DATES.get(name, (0, 0))
    if not created:
        return ""
    if saved - created < 60:
        return "создан " + _when(created)
    if short:
        return "изм. " + _when(saved)
    return "создан %s · изм. %s" % (_when(created), _when(saved))
H = 0


def read_style():
    v = (os.environ.get("JARVIS_PRESET_STYLE") or "").strip().lower()
    return v if v in cw.STYLES else cw.read_style()


def set_geometry(style, n):
    """Размеры буфера обмена для стиля (cw.set_geometry) + своё: без вкладок, список
    на n строк (не больше MAX_ROWS), высота окна — по содержимому."""
    global BORDER, TOP, TB, CAP, PAD, PX, ADV, LINE, K, BAR, GAP, X0, CW
    global SEARCH_Y, SEARCH_H, LIST_Y, LIST_H, LX, LW, FOOT_H, FOOT_Y, ROW, H
    cw.set_geometry(style)
    BORDER, TOP, TB, CAP, PAD, PX, ADV, LINE = (cw.BORDER, cw.TOP, cw.TB, cw.CAP, cw.PAD,
                                                cw.PX, cw.ADV, cw.LINE)
    K, BAR, GAP, X0, CW = cw.K, cw.BAR, cw.GAP, cw.X0, cw.CW
    SEARCH_Y, SEARCH_H, FOOT_H = cw.SEARCH_Y, cw.SEARCH_H, cw.FOOT_H
    ROW = PX + (12 if style == "skeet" else 16)      # строка в одну строку текста
    under = SEARCH_Y + SEARCH_H + 8                  # там, где у буфера вкладки
    if style == "skeet":                             # список — в группе с подписью в рамке
        LIST_Y = under + PX // 2 + 8
        LX, LW = X0 + 7, CW - 14
    elif style == "beta":                            # в карточке с рамкой
        LIST_Y = under + 1
        LX, LW = X0 + 1, CW - 2
    else:
        LIST_Y = under
        LX, LW = X0, CW
    rows = max(1, min(n, MAX_ROWS))
    LIST_H = rows * ROW + (rows - 1) * GAP
    if style == "skeet":
        FOOT_Y = LIST_Y + LIST_H + 8 + 6
    elif style == "beta":
        FOOT_Y = LIST_Y + LIST_H + 8
    else:
        FOOT_Y = LIST_Y + LIST_H + 6
    H = FOOT_Y + FOOT_H + PAD + BORDER


class Catcher(Gtk.Window):
    """Прозрачный слой во весь монитор уровнем ниже окна: щелчок мимо — отмена.
    Его размывает niri (layer-rule «jarvis-preset-catch») — как у буфера обмена."""

    def __init__(self, dlg, monitor):
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
        self.connect("draw", cw.Catcher.on_draw)
        self.connect("button-press-event", lambda *_a: dlg.finish("") or True)


class Win(Gtk.Window):
    def __init__(self, dlg):
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
        self.area.set_size_request(W + 2 * RING, H + 2 * RING)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.area.connect("draw", dlg.on_draw)
        self.area.connect("button-press-event", dlg.on_press)
        self.area.connect("motion-notify-event", dlg.on_motion)
        self.area.connect("scroll-event", dlg.on_scroll)
        self.connect("key-press-event", dlg.on_key)
        self.add(self.area)


class Dialog:
    def __init__(self, names, test=False, style=None):
        self.test = test
        self.names = names
        self.cur = current_preset() if DATES else (None, False)
        self.entry, self.pos = "", 0          # текст поля и место курсора (в знаках)
        self.sel, self.scroll = -1, 0         # выбранная строка (-1 — нет), прокрутка списка
        self.hover = None
        self.result = None                    # итог в проверке: строка (пусто — отмена)
        self.fd = Pango.FontDescription(cw.FONT)
        self.fo = cairo.FontOptions()
        self.fo.set_antialias(cairo.ANTIALIAS_GRAY)
        self.fo.set_hint_style(cairo.HINT_STYLE_FULL)
        self.fo.set_hint_metrics(cairo.HINT_METRICS_ON)
        cw.load_theme()
        self.apply_style(style or read_style())
        self.win, self.catchers = None, []
        if not test:
            self.win = Win(self)
            display = Gdk.Display.get_default()
            for i in range(display.get_n_monitors()):
                c = Catcher(self, display.get_monitor(i))
                c.show_all()
                self.catchers.append(c)
            self.win.show_all()

    # ── стиль ──────────────────────────────────────────────────────────────
    def apply_style(self, style):
        """Как App.apply_style у буфера: размеры, кегль, цвета, узор фона skeet."""
        self.style = style if style in cw.STYLES else "default"
        set_geometry(self.style, len(self.names))
        self.fd.set_absolute_size(PX * Pango.SCALE)
        self.C = cw.style_colors(self.style)
        if not cw.read_glass():                       # по умолчанию фон окна непрозрачный
            self.C["win_alpha"] = 1.0
        self.dots = None
        if self.style == "skeet":                     # точки узора: (0,0) и (2,2) плитки 4×4
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
            tc = cairo.Context(tile)
            tc.set_source_rgb(*self.C["dot"])
            tc.rectangle(0, 0, 1, 1)
            tc.rectangle(2, 2, 1, 1)
            tc.fill()
            self.dots = cairo.SurfacePattern(tile)
            self.dots.set_extend(cairo.EXTEND_REPEAT)

    # ── итог ───────────────────────────────────────────────────────────────
    def finish(self, name):
        """Напечатать итог и выйти. os._exit, как у буфера (App.finish): мимо gdk_flush."""
        name = (name or "").strip()
        self.result = name
        if self.test:
            return
        try:
            sys.stdout.write(name + "\n")
            sys.stdout.flush()
            sys.stderr.flush()
        except OSError:
            pass
        os._exit(0)

    def submit(self):
        name = self.entry.strip()
        if not name and 0 <= self.sel < len(self.names):
            name = self.names[self.sel]
        if name:
            self.finish(name)

    def redraw(self):
        if self.win is not None:
            self.win.area.queue_draw()

    # ── поле и список ──────────────────────────────────────────────────────
    def set_entry(self, text, pos=None):
        self.entry = text[:MAX_LEN]
        self.pos = len(self.entry) if pos is None else max(0, min(pos, len(self.entry)))
        # подсветка — на пресете с этим именем (его перезапишет), иначе ни на чём
        key = self.entry.strip()
        self.sel = self.names.index(key) if key in self.names else -1
        self.reveal()
        self.redraw()

    def pick(self, i):
        """Строка i — выбрана, её имя — в поле."""
        if self.names:
            i = max(0, min(len(self.names) - 1, i))
            self.set_entry(self.names[i])
            self.sel = i

    def move(self, d):
        if not self.names:
            return
        if self.sel < 0:
            self.pick(0 if d > 0 else len(self.names) - 1)
        else:
            self.pick(self.sel + d)

    def total(self):
        n = len(self.names)
        return n * ROW + max(0, n - 1) * GAP

    def reveal(self):
        if self.sel >= 0:
            top = self.sel * (ROW + GAP)
            if top < self.scroll:
                self.scroll = top
            elif top + ROW > self.scroll + LIST_H:
                self.scroll = top + ROW - LIST_H
        self.scroll = max(0, min(self.scroll, max(0, self.total() - LIST_H)))

    def list_w(self):
        return LW - (BAR + 4 if self.total() > LIST_H else 0)

    def row_at(self, x, y):
        if not (LX <= x < LX + self.list_w() and LIST_Y <= y < LIST_Y + LIST_H):
            return None
        yy = y - LIST_Y + self.scroll
        i = int(yy // (ROW + GAP))
        if 0 <= i < len(self.names) and yy - i * (ROW + GAP) < ROW:
            return i
        return None

    def thumb_geom(self):
        total = self.total()
        if total <= LIST_H:
            return None
        kh = max(24, int(LIST_H * LIST_H / total))
        return LX + LW - BAR, LIST_Y + int((LIST_H - kh) * self.scroll / max(1, total - LIST_H)), kh

    # ── клавиатура ─────────────────────────────────────────────────────────
    def on_key(self, _w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        G = Gdk
        e, p = self.entry, self.pos
        if k == G.KEY_Escape:
            self.finish("")
        elif k in (G.KEY_Return, G.KEY_KP_Enter):
            self.submit()
        elif k in (G.KEY_Down, G.KEY_KP_Down) or ((ctrl or alt) and (code in (44, 57) or k in (
                G.KEY_j, G.KEY_J, G.KEY_Cyrillic_o, G.KEY_Cyrillic_O, G.KEY_n, G.KEY_N))):
            self.move(1)                                   # 44 — клавиша J, 57 — N
        elif k in (G.KEY_Up, G.KEY_KP_Up) or ((ctrl or alt) and (code in (45, 33) or k in (
                G.KEY_k, G.KEY_K, G.KEY_Cyrillic_el, G.KEY_Cyrillic_EL, G.KEY_p, G.KEY_P))):
            self.move(-1)                                  # 45 — клавиша K, 33 — P
        elif k in (G.KEY_Left, G.KEY_KP_Left):
            self.pos = max(0, p - 1)
        elif k in (G.KEY_Right, G.KEY_KP_Right):
            self.pos = min(len(e), p + 1)
        elif k in (G.KEY_Home, G.KEY_KP_Home) or (ctrl and (code == 38 or k in (G.KEY_a, G.KEY_A))):
            self.pos = 0                                   # 38 — клавиша A
        elif k in (G.KEY_End, G.KEY_KP_End) or (ctrl and (code == 26 or k in (G.KEY_e, G.KEY_E))):
            self.pos = len(e)                              # 26 — клавиша E
        elif ctrl and (k == G.KEY_BackSpace or code == 25 or k in (G.KEY_w, G.KEY_W)):
            head = e[:p].rstrip().rpartition(" ")[0]       # слово до курсора, как в поиске буфера
            self.set_entry(head + e[p:], len(head))        # 25 — клавиша W
        elif k == G.KEY_BackSpace:
            if p:
                self.set_entry(e[:p - 1] + e[p:], p - 1)
        elif k in (G.KEY_Delete, G.KEY_KP_Delete):
            if p < len(e):
                self.set_entry(e[:p] + e[p + 1:], p)
        elif ctrl and (code == 30 or k in (G.KEY_u, G.KEY_U)):
            self.set_entry("", 0)                          # 30 — клавиша U
        elif ctrl and (code == 55 or k in (G.KEY_v, G.KEY_V)):
            self.paste()                                   # 55 — клавиша V
        elif not ctrl and not alt:
            u = Gdk.keyval_to_unicode(k)
            ch = chr(u) if u else ""
            if ch and ch.isprintable() and len(e) < MAX_LEN:
                self.set_entry(e[:p] + ch + e[p:], p + 1)
            else:
                return False
        else:
            return False
        self.redraw()
        return True

    def paste(self):
        import subprocess
        try:
            r = subprocess.run(["wl-paste", "--no-newline", "--type", "text/plain;charset=utf-8"],
                               capture_output=True, timeout=1.5)
            text = r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            text = ""
        text = " ".join((text.strip().splitlines() or [""])[0].split())
        if text:
            e, p = self.entry, self.pos
            add = text[:MAX_LEN - len(e)]
            self.set_entry(e[:p] + add + e[p:], p + len(add))

    # ── мышь ───────────────────────────────────────────────────────────────
    @staticmethod
    def inside(zone, x, y):
        return zone[0] <= x < zone[0] + zone[2] and zone[1] <= y < zone[1] + zone[3]

    def zone_close(self):
        return (W - BORDER - 3 - CAP, TOP + (TB - CAP) // 2, CAP, CAP)

    def on_press(self, _w, ev):
        x, y = ev.x - RING, ev.y - RING
        if not (0 <= x < W and 0 <= y < H):
            self.finish("")
            return True
        if ev.button != 1:
            return True
        if self.inside(self.zone_close(), x, y):
            self.finish("")
            return True
        i = self.row_at(x, y)
        if i is not None:
            if ev.type == Gdk.EventType._2BUTTON_PRESS:
                self.finish(self.names[i])
            else:
                self.pick(i)
        return True

    def on_motion(self, _w, ev):
        x, y = ev.x - RING, ev.y - RING
        hover = "close" if self.inside(self.zone_close(), x, y) else None
        if hover != self.hover:
            self.hover = hover
            self.redraw()
        return True

    def on_scroll(self, _w, ev):
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            _ok, _dx, dy = ev.get_scroll_deltas()
            d = dy * (ROW + GAP)
        else:
            d = {Gdk.ScrollDirection.UP: -(ROW + GAP),
                 Gdk.ScrollDirection.DOWN: ROW + GAP}.get(ev.direction, 0)
        self.scroll = max(0, min(int(self.scroll + d), max(0, self.total() - LIST_H)))
        self.redraw()
        return True

    # ── рисование: общее (копии методов clipboard_win.App) ─────────────────
    def layout(self, cr, text, width=None, lines=1):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.fd)
        lay.set_text(text, -1)
        if width:
            lay.set_width(int(width) * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            if lines > 1:
                lay.set_wrap(Pango.WrapMode.WORD_CHAR)
                lay.set_height(-lines)
                lay.set_spacing((LINE - PX) * Pango.SCALE)
        return lay

    def text(self, cr, s, x, y, color, width=None, lines=1, alpha=1.0, align=None):
        lay = self.layout(cr, s, width, lines)
        if align:
            lay.set_alignment(align)
        cr.set_source_rgba(color[0], color[1], color[2], alpha)
        cr.move_to(int(x), int(y))
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()

    def rect_line(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()

    def rect_fill(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def band(self, cr, i, w, color):
        cr.set_source_rgb(*color)
        cr.rectangle(i, i, W - 2 * i, H - 2 * i)
        cr.rectangle(i + w, i + w, W - 2 * (i + w), H - 2 * (i + w))
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

    def close_button(self, cr):
        """Кнопка «закрыть» заголовка — ветка kind="close" из App.button."""
        x, y, w, h = self.zone_close()
        C, st, hover = self.C, self.style, self.hover == "close"
        if st == "skeet":
            g = cairo.LinearGradient(0, y, 0, y + h)
            g.add_color_stop_rgb(0, *C["field_l"])
            g.add_color_stop_rgb(1, *C["field"])
            cr.set_source(g)
            cr.rectangle(x, y, w, h)
            cr.fill()
            self.rect_line(cr, x, y, w, h, C["line3"])
            self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["gline"])
            ink = C["err"] if hover else C["text_dim"]
        elif st == "beta":
            self.rect_fill(cr, x, y, w, h, C["hover"] if hover else C["field"])
            self.rect_line(cr, x, y, w, h, C["line_strong"])
            ink = C["text"]
            if hover:
                self.rect_fill(cr, x, y, w, h, C["err"])
                ink = C["bg"]
        else:
            g = cairo.LinearGradient(0, y, 0, y + h)
            er = T["error"]
            top = tuple(0.5 * er[i] + 0.5 * T["st_hover"][i] for i in range(3))
            bot = tuple(0.55 * er[i] * 0.6 + 0.45 * T["st_bot"][i] for i in range(3))
            if hover:
                top = mix(top, (1, 1, 1), 0.18)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(x, y, w, h)
            cr.fill()
            self.rect_line(cr, x, y, w, h, T["st_hi"])
            ink = T["on_surface"]
        bmp = cw.X_BMP
        cr.set_source_rgb(*ink)
        draw_bitmap(cr, bmp, x + (w - len(bmp[0])) // 2, y + (h - len(bmp)) // 2)

    # ── рамки и заголовки трёх стилей ──────────────────────────────────────
    def title_bar(self, cr, x, y, w, title):
        """Полоса заголовка XP: градиент «Пуска», значок-квадратик, имя с тенью."""
        g = cairo.LinearGradient(0, y, 0, y + TB)
        for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(off, *T[key])
        cr.set_source(g)
        cr.rectangle(x, y, w, TB)
        cr.fill()
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(x, y + TB - 1, w, 1)
        cr.fill()
        ix, iy = x + 6, y + (TB - 10) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(ix + 1, iy + 1, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["on_surface"])
        cr.rectangle(ix, iy, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["st_mid"])
        cr.rectangle(ix + 3, iy + 3, 4, 4)
        cr.fill()
        lay = self.layout(cr, title, w - 22 - 2 * (CAP + 6))
        ty = y + (TB - lay.get_pixel_size()[1]) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.move_to(ix + 17, ty + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*T["on_surface"])
        cr.move_to(ix + 16, ty)
        PangoCairo.show_layout(cr, lay)

    def frame_default(self, cr):
        self.band(cr, 0, BORDER, T["st_mid"])
        self.title_bar(cr, BORDER, BORDER, W - 2 * BORDER, TITLE)
        self.close_button(cr)

    def frame_skeet(self, cr):
        C = self.C
        for i, w, key in ((0, 1, "line1_on"), (1, 3, "line2"), (4, 1, "line1_on"), (5, 1, "line3")):
            self.band(cr, i, w, C[key])
        for dy, k in ((0, 0.0), (1, 0.55)):
            g = cairo.LinearGradient(BORDER, 0, W - BORDER, 0)
            for off, col in zip((0, 0.5, 1), C["strip"]):
                g.add_color_stop_rgb(off, *mix(col, (0, 0, 0), k))
            cr.set_source(g)
            cr.rectangle(BORDER, BORDER + dy, W - 2 * BORDER, 1)
            cr.fill()
        self.rect_fill(cr, BORDER, TOP + TB - 2, W - 2 * BORDER, 1, C["line2"])
        self.rect_fill(cr, BORDER, TOP + TB - 1, W - 2 * BORDER, 1, C["line3"])
        cr.set_source_rgb(*C["icon_on"])
        draw_bitmap(cr, ICON_BMP, BORDER + 7, TOP + (TB - 9) // 2)
        self.text(cr, TITLE, BORDER + 7 + 7 + 6, TOP + (TB - PX) // 2 - 1, C["text"])
        self.close_button(cr)

    def frame_beta(self, cr):
        C = self.C
        self.band(cr, 0, BORDER, C["frame"])
        self.rect_fill(cr, BORDER, TOP, W - 2 * BORDER, TB, C["bar"])
        self.rect_fill(cr, BORDER, TOP + TB - 1, W - 2 * BORDER, 1, C["line"])
        cr.set_source_rgb(*C["acc_text"])
        draw_bitmap(cr, ICON_BMP, BORDER + 8, TOP + (TB - 18) // 2, 2)
        self.text(cr, TITLE, BORDER + 8 + 14 + 8, TOP + (TB - PX) // 2, C["text"])
        self.close_button(cr)

    # ── поле ввода (строка поиска буфера) ──────────────────────────────────
    def draw_entry(self, cr):
        C, st = self.C, self.style
        sw = CW
        if st == "skeet":
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, C["field"])
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, C["acc_d"])
            self.rect_line(cr, X0 + 1, SEARCH_Y + 1, sw - 2, SEARCH_H - 2, C["gline"])
            pen = C["text_dim"]
        elif st == "beta":
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, C["field"])
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, C["acc"])
            pen = C["dim"]
        else:
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, T["st_dark"], 0.5)
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, T["st_top"])
            pen = T["st_hi"]
        li = 9 * K
        cr.set_source_rgb(*pen)
        draw_bitmap(cr, PEN_BMP, X0 + 8, SEARCH_Y + (SEARCH_H - li) // 2, K)
        x = X0 + 8 + li + 8
        room = sw - (x - X0) - 14
        y = SEARCH_Y + (SEARCH_H - PX) // 2
        if self.entry:
            lay = self.layout(cr, self.entry)
            # место курсора в пикселях; длинное название сдвигается, чтобы курсор был виден
            idx = len(self.entry[:self.pos].encode("utf-8"))
            cx_rel = lay.index_to_pos(idx).x // Pango.SCALE
            shift = max(0, cx_rel + 2 - room)
            cr.save()
            cr.rectangle(x, SEARCH_Y + 1, room + 2, SEARCH_H - 2)
            cr.clip()
            cr.set_source_rgb(*C["text"])
            cr.move_to(x - shift, y)
            PangoCairo.show_layout(cr, lay)
            cr.restore()
            cx = x + cx_rel - shift + (2 if self.pos == len(self.entry) else 0)
        else:
            self.text(cr, PLACEHOLDER, x + 6, y, C["dim"], alpha=0.75)
            cx = x
        cr.set_source_rgb(*C["accent"])                      # курсор — как в поиске буфера
        cr.rectangle(cx, y, 2 if K == 2 else 1, PX)
        cr.fill()

    # ── список ─────────────────────────────────────────────────────────────
    def draw_list_box(self, cr):
        """Подложка списка: в skeet — группа с подписью в рамке, в Beta — карточка."""
        C, st = self.C, self.style
        if st == "skeet":
            gx, gy, gw, gh = X0, LIST_Y - 10, CW, LIST_H + 18
            self.rect_line(cr, gx, gy, gw, gh, C["gline"])
            self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
            lw = len(GROUP) * ADV
            self.rect_fill(cr, gx + 10, gy - 1, lw + 8, 3, C["bg"])
            if self.dots is not None:
                cr.save()
                cr.rectangle(gx + 10, gy - 1, lw + 8, 3)
                cr.clip()
                cr.set_source(self.dots)
                cr.paint()
                cr.restore()
            self.text(cr, GROUP, gx + 14, gy - PX // 2 - 1, C["text"])
        elif st == "beta":
            self.rect_fill(cr, X0, LIST_Y - 1, CW, LIST_H + 2, C["card"])
            self.rect_line(cr, X0, LIST_Y - 1, CW, LIST_H + 2, C["line"])

    def draw_list(self, cr):
        C = self.C
        if not self.names:
            lay = self.layout(cr, EMPTY, LW - 40)
            lay.set_alignment(Pango.Alignment.CENTER)
            cr.set_source_rgba(*C["dim"], 0.9)
            cr.move_to(LX + 20, LIST_Y + (LIST_H - lay.get_pixel_size()[1]) // 2)
            PangoCairo.show_layout(cr, lay)
            return
        lw = self.list_w()
        n = len(self.names)
        for i, name in enumerate(self.names):
            y = LIST_Y + i * (ROW + GAP) - self.scroll
            if y + ROW <= LIST_Y:
                continue
            if y >= LIST_Y + LIST_H:
                break
            self.draw_row(cr, name, LX, y, lw, ROW, i == self.sel, i == n - 1)
        g = self.thumb_geom()
        if g:                                          # полоса прокрутки
            bx, ky, kh = g
            if self.style == "default":
                self.rect_fill(cr, bx, LIST_Y, BAR, LIST_H, T["fg"], 0.07)
            elif self.style == "beta":
                self.rect_fill(cr, bx, LIST_Y, BAR, LIST_H, C["line_soft"])
            self.rect_fill(cr, bx, ky, BAR, kh, C["scroll"])

    def draw_row(self, cr, name, x, y, w, h, sel, last):
        """Строка — как текстовая строка буфера: подсветка выбранной та же."""
        C, st = self.C, self.style
        if sel:
            self.rect_fill(cr, x, y, w, h, C["sel_bg"])
            if st == "skeet":
                self.rect_line(cr, x, y, w, h, C["gline"])
                self.rect_fill(cr, x, y, 2, h, C["acc"])
        elif st == "default":
            self.rect_fill(cr, x, y, w, h, T["fg"], 0.045)
        if st == "beta" and not last:
            self.rect_fill(cr, x, y + h, w, 1, C["line_soft"])
        fg = C["sel_text"] if sel else C["text"]
        tx, ty = x + 10, y + (h - PX) // 2
        right = x + w - 12
        # справа — даты создания и правки (05.10.2026, пользователь), у выбранной ещё и что
        # будет: перезапись; не помещается — сперва уходит «перезаписать», потом даты
        full, short = preset_dates(name), preset_dates(name, short=True)
        cands = ([OVERWRITE + " · " + full] if sel and full and OVERWRITE else []) + [full, short]
        if short:
            cands.append(short.split(" ", 1)[1])      # только дата
        # текущий пресет (05.10.2026): метка-квадрат акцентом слева и «сейчас» в начале хвоста
        if name == self.cur[0]:
            now = "сейчас, изменён" if self.cur[1] else "сейчас"
            cands = [now + " · " + c for c in cands if c] + [now]
            mk = max(4, PX // 3)
            self.rect_fill(cr, x + 4, y + (h - mk) // 2, mk, mk, C["accent"])
            tx += mk
        for tail in cands + [""]:
            if tail and right - len(tail) * ADV - 12 - tx >= min(len(name), 12) * ADV:
                break
        if tail:
            hw = len(tail) * ADV
            self.text(cr, tail, right - hw, ty, C["sel_dim"] if sel else C["dim"])
            right -= hw + 12
        self.text(cr, name, tx, ty, fg, right - tx)

    def draw_footer(self, cr):
        C = self.C
        lay = self.layout(cr, HINT)
        hw = lay.get_pixel_size()[0]
        left = "Закрыть (Esc)" if self.hover == "close" else ""
        lw = self.text(cr, left, X0, FOOT_Y, C["text"], CW)[0] if left else 0
        if lw + 24 <= CW - hw:
            cr.set_source_rgba(*C["dim"], 0.8)
            cr.move_to(X0 + CW - hw, FOOT_Y)
            PangoCairo.show_layout(cr, lay)

    # ── кадр ───────────────────────────────────────────────────────────────
    def on_draw(self, _a, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)               # поле вокруг окна — прозрачное
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_font_options(self.fo)
        cr.translate(RING, RING)
        try:
            self.render(cr)
        except Exception as err:                       # окно без кадра хуже окна с огрехом
            print("preset_ask: кадр: %s" % err, file=sys.stderr)
        return True

    def render(self, cr):
        C = self.C
        cr.save()
        cr.rectangle(0, 0, W, H)
        cr.clip()
        cr.set_source_rgba(*C["win_bg"], C["win_alpha"])
        cr.paint()
        if self.style == "skeet" and self.dots is not None:
            cr.set_source(self.dots)
            cr.paint_with_alpha(C["win_alpha"])
        cr.restore()
        getattr(self, "frame_" + self.style)(cr)
        self.draw_entry(cr)
        self.draw_list_box(cr)
        cr.save()
        cr.rectangle(LX, LIST_Y, LW, LIST_H)
        cr.clip()
        self.draw_list(cr)
        cr.restore()
        self.draw_footer(cr)

    def render_png(self, path):
        """Кадр в PNG без окна (для проверок)."""
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W + 2 * RING, H + 2 * RING)
        self.on_draw(None, cairo.Context(surf))
        surf.write_to_png(path)
        return W + 2 * RING, H + 2 * RING


class Confirm(Dialog):
    """Окно «точно удалить?» (05.10.2026, Просьба: «защита от дурака — отдельное окно по
    центру»). Тот же вид, что Preset.exe: рамка стиля, заголовок, вопрос, кнопки «Удалить» и
    «Отмена» (кнопки — cw.App.button, как «Да/Нет» у очистки буфера). Печатает «yes» или
    пусто. Enter — выбранная кнопка (сразу выбрана «Отмена»), ←/→/Tab/h/l — выбор,
    y — удалить, Esc/n и щелчок мимо — отмена."""
    button = cw.App.button
    BW, BH = 120, 0

    def __init__(self, title, question, sub="", ok="Удалить", test=False, style=None):
        self.title, self.question, self.sub, self.ok = title, question, sub, ok
        self.focus = "no"
        super().__init__([], test=test, style=style)

    def apply_style(self, style):
        global W, CW, H
        super().apply_style(style)
        W = 460
        CW = W - 2 * X0
        self.BH = SEARCH_H
        self.q_y = TOP + TB + 18
        self.b_y = self.q_y + LINE * (2 if self.sub else 1) + 18
        H = self.b_y + self.BH + 10 + FOOT_H + PAD + BORDER
        if self.win is not None if hasattr(self, "win") else False:
            self.win.area.set_size_request(W + 2 * RING, H + 2 * RING)

    def zones(self):
        gap = 12
        x = (W - 2 * self.BW - gap) // 2
        return (x, self.b_y, self.BW, self.BH), (x + self.BW + gap, self.b_y, self.BW, self.BH)

    def answer(self, yes):
        self.finish("yes" if yes else "")

    def on_key(self, _w, ev):
        k, G = ev.keyval, Gdk
        if k in (G.KEY_Escape, G.KEY_n, G.KEY_N, G.KEY_Cyrillic_te, G.KEY_Cyrillic_TE):
            self.answer(False)
        elif k in (G.KEY_y, G.KEY_Y, G.KEY_Cyrillic_en, G.KEY_Cyrillic_EN):
            self.answer(True)
        elif k in (G.KEY_Return, G.KEY_KP_Enter, G.KEY_space):
            self.answer(self.focus == "yes")
        elif k in (G.KEY_Left, G.KEY_Right, G.KEY_Tab, G.KEY_ISO_Left_Tab, G.KEY_h, G.KEY_l,
                   G.KEY_Cyrillic_er, G.KEY_Cyrillic_de):
            self.focus = "no" if self.focus == "yes" else "yes"
            self.redraw()
        return True

    def on_press(self, _w, ev):
        x, y = ev.x - RING, ev.y - RING
        if not (0 <= x < W and 0 <= y < H) or self.inside(self.zone_close(), x, y):
            self.answer(False)
            return True
        yes, no = self.zones()
        if ev.button == 1 and self.inside(yes, x, y):
            self.answer(True)
        elif ev.button == 1 and self.inside(no, x, y):
            self.answer(False)
        return True

    def on_motion(self, _w, ev):
        x, y = ev.x - RING, ev.y - RING
        yes, no = self.zones()
        hover = ("close" if self.inside(self.zone_close(), x, y) else
                 "yes" if self.inside(yes, x, y) else "no" if self.inside(no, x, y) else None)
        if hover != self.hover:
            self.hover = hover
            self.redraw()
        return True

    def on_scroll(self, _w, ev):
        return True

    def render(self, cr):
        C = self.C
        cr.save()
        cr.rectangle(0, 0, W, H)
        cr.clip()
        cr.set_source_rgba(*C["win_bg"], C["win_alpha"])
        cr.paint()
        if self.style == "skeet" and self.dots is not None:
            cr.set_source(self.dots)
            cr.paint_with_alpha(C["win_alpha"])
        cr.restore()
        getattr(self, "frame_" + self.style)(cr)
        self.text(cr, self.question, X0, self.q_y, C["text"], CW, align=Pango.Alignment.CENTER)
        if self.sub:
            self.text(cr, self.sub, X0, self.q_y + LINE, C["dim"], CW, align=Pango.Alignment.CENTER)
        yes, no = self.zones()
        for zone, label, key in ((yes, self.ok, "yes"), (no, "Отмена", "no")):
            self.button(cr, zone, on=self.focus == key, kind="dlg", label=label,
                        hover=self.hover == key)
        hint = "Enter — выбор · Esc — отмена"
        lay = self.layout(cr, hint)
        hw = lay.get_pixel_size()[0]
        if hw <= CW:
            cr.set_source_rgba(*C["dim"], 0.8)
            cr.move_to(X0 + CW - hw, H - BORDER - PAD - FOOT_H)
            PangoCairo.show_layout(cr, lay)


def sound(event):
    """Звук интерфейса, как у буфера при показе; в фоне — окно не ждёт."""
    import threading

    def play():
        try:
            import ui_sound
            ui_sound.play(event)
        except Exception:
            pass
    threading.Thread(target=play, daemon=True).start()


def main():
    global TITLE, PLACEHOLDER, GROUP, EMPTY, HINT, OVERWRITE, ICON_BMP, DATES
    if sys.argv[1:2] == ["--ask"]:
        # preset_ask.py --ask ЗАГОЛОВОК ПОДСКАЗКА-ПОЛЯ ПОДПИСЬ-СПИСКА ПОДСКАЗКА-СНИЗУ [ВАРИАНТ…]
        # то же окно для других вопросов (05.10.2026: «Создать таймер…» → Timer.exe)
        a = sys.argv[2:] + [""] * 4
        TITLE, PLACEHOLDER, GROUP, HINT = a[0] or "Ask.exe", a[1], a[2] or "Варианты", a[3] or HINT
        EMPTY, OVERWRITE, DATES = "", "", False
        if TITLE.lower().startswith(("timer", "pomo")):
            ICON_BMP = CLOCK_BMP
        sys.argv = [sys.argv[0]] + [x for x in sys.argv[6:]]
    if sys.argv[1:2] == ["--confirm"]:
        # preset_ask.py --confirm ЗАГОЛОВОК ВОПРОС [ПОЯСНЕНИЕ] → «yes» или пусто
        a = sys.argv[2:] + ["", "", ""]
        dlg = Confirm(a[0] or TITLE, a[1] or "Точно?", a[2])
        sound("menu")
        Gtk.main()
        print("")
        return 0
    names = []
    for a in sys.argv[1:]:
        a = a.strip()
        if a and a not in names:
            names.append(a)
    dlg = Dialog(names)
    sound("menu")
    try:
        from gi.repository import GLibUnix
        add = GLibUnix.signal_add
    except ImportError:                               # старый PyGObject без GLibUnix
        add = GLib.unix_signal_add
    for sig in (2, 15):                               # SIGINT/SIGTERM — отмена
        add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: dlg.finish("") or False)
    Gtk.main()
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
