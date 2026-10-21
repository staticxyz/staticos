#!/usr/bin/env python3
"""Шпаргалка клавиш — стиль системы, vim-навигация, поиск.

Super+Z: j/k прокрутка, Ctrl+D/U полстраницы, / поиск, q/Esc/Ctrl+Q закрыть, g/G в начало/конец.
Тема и цвета — из обоев (palette + settings-skin).
"""
import os
import re
import sys

sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell, Pango, PangoCairo
import cairo

NAMESPACE = "jarvis-keybinds"

APP_ID = "com.jarvis.keybinds"
W, H_MIN = 640, 640
ROW_H = 26
PAD = 20
FONT_SZ = 16

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "

BINDS_KDL = os.path.expanduser("~/.config/niri/cfg/binds.kdl")

# ── палитра (из app_launcher) ────────────────────────────────────────────────
from app_launcher import palette, colors, style_name, hexrgb, mix, read

# ── разбор биндов ────────────────────────────────────────────────────────────

RE_BIND = re.compile(
    r'^\s*(\S+)\s+(?:.*?hotkey-overlay-title="([^"]*)")?\s*\{',
    re.MULTILINE
)

PRETTY = {
    "Mod": "Super", "Ctrl": "Ctrl", "Shift": "Shift", "Alt": "Alt",
    "Grave": "`", "Return": "Enter", "Slash": "/", "Period": ".", "Comma": ",",
    "Minus": "-", "Equal": "=", "BracketLeft": "[", "BracketRight": "]", "Backslash": "\\",
    "Escape": "Esc", "KP_Add": "Num+", "KP_Subtract": "Num-", "Page_Up": "PgUp", "Page_Down": "PgDn",
    "XF86AudioRaiseVolume": "Vol+", "XF86AudioLowerVolume": "Vol-", "XF86AudioMute": "Mute",
    "XF86AudioMicMute": "MicMute", "XF86MonBrightnessUp": "Bright+", "XF86MonBrightnessDown": "Bright-",
    "XF86AudioNext": "Next", "XF86AudioPrev": "Prev", "XF86AudioPlay": "Play", "XF86AudioPause": "Pause",
    "TouchpadScrollLeft": "тачпад ←", "TouchpadScrollRight": "тачпад →",
}

def pretty_key(raw):
    parts = raw.replace("+", " + ").split(" + ")
    out = []
    for p in parts:
        p = p.strip()
        out.append(PRETTY.get(p, p))
    return "+".join(out)

# Неподписанные бинды — стандартные действия niri. Раньше шпаргалка их пропускала, и в ней
# не было ни навигации, ни столов 1–9, ни Print (13.10.2026, просьба: «обнови бинды на
# Super+Z»). Подпись и категория — отсюда; binds.kdl не трогаем. Повторы (стрелки, KP,
# колесо) склеиваются по подписи: остаётся первая клавиша, т.е. vim-вариант.
RE_FULL = re.compile(r'^\s*([A-Za-z0-9_+]+)\s+([^{\n]*)\{[ \t]*([^}\n]*)\}', re.MULTILINE)
RE_TITLE = re.compile(r'hotkey-overlay-title="([^"]*)"')
WIN, SHOT, MEDIA, SYS = "Окна и столы", "Снимки и запись", "Звук, яркость, медиа", "Система"
ACTION_RU = {
    "toggle-overview": ("Обзор столов", WIN),
    "focus-column-left": ("Колонка слева", WIN),
    "focus-column-right": ("Колонка справа", WIN),
    "focus-column-first": ("Первая колонка", WIN),
    "focus-column-last": ("Последняя колонка", WIN),
    "focus-workspace-up": ("Стол выше", WIN),
    "focus-workspace-down": ("Стол ниже", WIN),
    "focus-window-up": ("Окно выше в колонке", WIN),
    "focus-window-down": ("Окно ниже в колонке", WIN),
    "move-column-left": ("Сдвинуть колонку влево", WIN),
    "move-column-right": ("Сдвинуть колонку вправо", WIN),
    "move-column-to-first": ("Колонку в начало", WIN),
    "move-column-to-last": ("Колонку в конец", WIN),
    "move-window-up": ("Окно вверх в колонке", WIN),
    "move-window-down": ("Окно вниз в колонке", WIN),
    "move-workspace-up": ("Переставить стол выше", WIN),
    "move-workspace-down": ("Переставить стол ниже", WIN),
    "move-column-to-workspace-up": ("Колонку на стол выше", WIN),
    "move-column-to-workspace-down": ("Колонку на стол ниже", WIN),
    "move-workspace-to-monitor-left": ("Стол на монитор слева", WIN),
    "move-workspace-to-monitor-right": ("Стол на монитор справа", WIN),
    "move-window-to-monitor-left": ("Окно на монитор слева", WIN),
    "move-window-to-monitor-right": ("Окно на монитор справа", WIN),
    "focus-monitor-next": ("Следующий монитор", WIN),
    "consume-or-expel-window-left": ("Окно в колонку слева / вынуть", WIN),
    "consume-or-expel-window-right": ("Окно в колонку справа / вынуть", WIN),
    "consume-window-into-column": ("Втянуть соседнее окно в колонку", WIN),
    "fullscreen-window": ("Окно на весь экран", WIN),
    "maximize-column": ("Колонка во всю ширину", WIN),
    "switch-focus-between-floating-and-tiling": ("Фокус: плавающие ↔ плитка", WIN),
    "toggle-column-tabbed-display": ("Колонка вкладками", WIN),
    "center-column": ("Колонку в центр", WIN),
    "screenshot": ("Снимок области", SHOT),
    "screenshot-window": ("Снимок окна", SHOT),
    "screenshot-screen": ("Снимок экрана", SHOT),
    "show-hotkey-overlay": ("Подсказка клавиш niri", SYS),
    "toggle-keyboard-shortcuts-inhibit": ("Отдать клавиши окну (игры, ВМ)", SYS),
    "quit": ("Выйти из niri", SYS),
    "power-off-monitors": ("Погасить мониторы", SYS),
}


def untitled(key, action):
    """(подпись, категория, ключ) для неподписанного бинда или None."""
    a = action.strip().rstrip(";").strip()
    # обёртка nostack (в стопке бинд молчит, 21.10.2026) — подпись по самому действию niri
    m = re.match(r'spawn\s+"[^"]*/nostack"\s+"niri"\s+"msg"\s+"action"\s+(.*)', a)
    if m:
        a = " ".join(re.findall(r'"([^"]*)"', m.group(1)))
    name, _, arg = a.partition(" ")
    if name in ("focus-workspace", "move-column-to-workspace") and arg.isdigit():
        if "KP_" in key:                                   # дубль цифрового ряда
            return None
        what = "Стол" if name == "focus-workspace" else "Колонку на стол"
        return (what + " 1…9", WIN, re.sub(r"\d+$", "1…9", key))
    if name == "set-window-height":
        return ("Высота окна " + ("+" if "+" in arg else "−"), WIN, key)
    if name == "spawn-sh" and "set-mute" in arg:
        return ("Микрофон вкл/выкл" if "SOURCE" in arg else "Звук вкл/выкл", MEDIA, key)
    if name in ACTION_RU:
        return ACTION_RU[name] + (key,)
    return None


def category(title):
    t = title.lower()
    if "терминал" in t:
        return "Терминал"
    if any(w in t for w in ("браузер", "helium", "zen", "tor ", "libre")):
        return "Браузеры"
    if any(w in t for w in ("снимок", "запись", "gif", "стикер", "replay", "текст с экрана")):
        return SHOT
    if any(w in t for w in ("помидор", "discipline")):
        return "Фокус"
    if any(w in t for w in ("hub", "напомин", "словарь")):
        return "Hub"
    if any(w in t for w in ("громкость", "микрофон", "трек", "играть", "яркость", "подсветка", "картинка в картинке")):
        return MEDIA
    if any(w in t for w in ("буфера обмена", "блокнот")):
        return "Программы"
    if any(w in t for w in ("настрой", "noctalia", "обо", "стиль", "панель", "аватар")):
        return "Настройки и вид"
    if any(w in t for w in ("окно", "окна", "окон", "стол", "монитор", "плавающ", "колон", "лент", "дашборд", "полноэкранн")):
        return WIN
    if any(w in t for w in ("блокировка", "питани")):
        return SYS
    return "Программы"


def load_binds():
    try:
        text = open(BINDS_KDL).read()
    except OSError:
        return []
    text = re.sub(r"//[^\n]*", "", text)
    CAT_ICONS = {
        "Терминал": ">_", "Браузеры": "🌐", "Hub": "📋",
        "Фокус": "⏱", SHOT: "📷", MEDIA: "♪",
        "Настройки и вид": "⚙", WIN: "▣", SYS: "⏻", "Программы": "◆",
    }
    cats, seen = {}, set()
    for m in RE_FULL.finditer(text):
        key, attrs, action = m.groups()
        t = RE_TITLE.search(attrs)
        if t:
            title, cat, shown = t.group(1), category(t.group(1)), key
        else:
            u = untitled(key, action)
            if not u:
                continue
            title, cat, shown = u
            if (cat, title) in seen:                       # стрелки/KP/колесо — тот же смысл
                continue
        seen.add((cat, title))
        cats.setdefault(cat, []).append((pretty_key(shown), title))
    order = ["Терминал", "Браузеры", "Hub", "Фокус", SHOT, MEDIA, "Настройки и вид", WIN, SYS, "Программы"]
    rows = []
    for c in order + [c for c in cats if c not in order]:
        if c in cats:
            rows.append(("head", c, CAT_ICONS.get(c, "")))
            for k, t in cats[c]:
                rows.append(("bind", k, t))
    return rows

# ── рисовалка ────────────────────────────────────────────────────────────────

class Painter:
    def __init__(self, cr, c):
        self.cr, self.c = cr, c

    def rgb(self, color):
        self.cr.set_source_rgb(*color)

    def rect(self, x, y, w, h, color):
        self.cr.rectangle(x, y, w, h)
        self.rgb(color)
        self.cr.fill()

    def round(self, x, y, w, h, r):
        import math
        cr = self.cr
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def text(self, x, y, text, color, size=12, align="l", maxw=0, bold=False):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription("JetBrainsMono Nerd Font %dpx" % size)
        if bold:
            fd.set_weight(Pango.Weight.BOLD)
        lay.set_font_description(fd)
        lay.set_text(text, -1)
        if maxw > 0:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        w = lay.get_pixel_size()[0]
        if align == "c":
            x -= w / 2
        elif align == "r":
            x -= w
        self.cr.move_to(x, y)
        self.rgb(color)
        PangoCairo.show_layout(self.cr, lay)
        return w

    def text_w(self, text, size=12):
        lay = PangoCairo.create_layout(self.cr)
        lay.set_font_description(Pango.FontDescription("JetBrainsMono Nerd Font %dpx" % size))
        lay.set_text(text, -1)
        return lay.get_pixel_size()[0]


class View:
    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.all_rows = load_binds()
        self.mode = "search"          # открылось — сразу печатать (13.10.2026); Esc/jj — навигация
        self.buf = ""
        self.sel = 0
        self.scroll = 0
        self.max_vis = 10
        self.pending_jj = False
        self.pending_t = 0
        self.hover_close = False
        self.close_rect = (0, 0, 0, 0)

    def rows(self):
        if not self.buf:
            return self.all_rows
        if getattr(self, "_rows_key", None) == self.buf:     # кадр зовёт rows() не раз
            return self._rows
        self._rows_key, self._rows = self.buf, self._rows_calc()
        return self._rows

    def _rows_calc(self):
        # Умный поиск (13.10.2026): синонимы, другая раскладка, опечатки, окончания —
        # «скриншот» находит «Снимок окна». Категория строки тоже участвует.
        from smart_search import search
        cat, items = "", []
        for r in self.all_rows:
            if r[0] == "head":
                cat = r[1]
            else:
                items.append((r, cat))
        return [r for r, _c in search(self.buf, items, lambda it: (it[0][1], it[0][2]),
                                         weak=lambda it: (it[1],))]

    def draw(self, cr, w, h):
        c = self.c
        p = Painter(cr, c)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        BG_ALPHA = 0.88
        if c["frame"] == "skeet":
            # Рамка — как у буфера обмена и Super+C (13.10.2026): слои снаружи внутрь
            # 1 светлая с акцентом, 3 средняя, 1 светлая с акцентом, 1 почти чёрная.
            acc = c["acc"]
            line1_on = mix(mix((0x3c / 255,) * 3, acc, 0.08), acc, 0.45)
            line2 = mix((0x28 / 255,) * 3, acc, 0.06)
            cr.set_source_rgba(*c["bg"], BG_ALPHA)
            cr.rectangle(6, 6, w - 12, h - 12); cr.fill()
            for i, bw, col in ((0, 1, line1_on), (1, 3, line2), (4, 1, line1_on), (5, 1, c["line3"])):
                cr.set_source_rgb(*col)
                cr.rectangle(i, i, w - 2 * i, h - 2 * i)
                cr.rectangle(i + bw, i + bw, w - 2 * (i + bw), h - 2 * (i + bw))
                cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD); cr.fill()
                cr.set_fill_rule(cairo.FILL_RULE_WINDING)
        else:
            p.round(1, 1, w - 2, h - 2, 10)
            cr.set_source_rgba(*c["bg"], BG_ALPHA)
            cr.fill_preserve()
            p.rgb(c["acc"])
            cr.set_line_width(2)
            cr.stroke()

        x0, x1 = PAD, w - PAD
        y = 14
        p.text(x0, y, "Клавиши", c["acc_l"], size=FONT_SZ, bold=True)
        # Крестик в углу (13.10.2026, просьба: «в меню Super+Z тоже добавь кнопку закрыть»)
        import close_cap                   # общий крестик системы (как у буфера обмена)
        s = close_cap.size(self.style)
        cy = y + (FONT_SZ + 6 - s) // 2
        self.close_rect = (x1 - s, cy, s, s)
        close_cap.draw(cr, self.style, close_cap.colors(self.style), x1 - s, cy, self.hover_close)
        y += 28

        # поиск
        p.rect(x0, y, x1 - x0, 26, c["field"])
        if self.mode == "search" and not self.buf:
            p.text(x0 + 6, y + 4, "▏", c["text"], size=FONT_SZ)
            p.text(x0 + 16, y + 4, "Поиск: снимок, громкость, браузер…", c["faint"], size=FONT_SZ,
                   maxw=x1 - x0 - 22)
        elif self.mode == "search":
            p.text(x0 + 6, y + 4, self.buf + "▏", c["text"], size=FONT_SZ, maxw=x1 - x0 - 12)
        elif self.buf:
            p.text(x0 + 6, y + 4, self.buf, c["text"], size=FONT_SZ, maxw=x1 - x0 - 12)
        else:
            p.text(x0 + 6, y + 4, "Поиск…  /", c["faint"], size=FONT_SZ, maxw=x1 - x0 - 12)
        y += 32

        rows = self.rows()
        if not rows:
            p.text(x0, y, "Ничего не найдено.", c["faint"], size=FONT_SZ)
            self.draw_footer(p, x0, x1, h - 30, w)
            return

        avail = h - y - 38
        max_vis = avail // ROW_H
        self.max_vis = max_vis
        sel = max(0, min(self.sel, len(rows) - 1))
        self.sel = sel

        off = self.scroll
        if sel < off:
            off = sel
        if sel >= off + max_vis:
            off = sel - max_vis + 1
        off = max(0, min(off, len(rows) - max_vis))
        self.scroll = off

        cr.save()
        cr.rectangle(x0 - 2, y, x1 - x0 + 4, avail)
        cr.clip()

        key_w = 240
        for i in range(off, min(off + max_vis + 1, len(rows))):
            ry = y + (i - off) * ROW_H
            if ry > y + avail:
                break
            is_sel = i == sel
            row = rows[i]
            txt_y = ry + (ROW_H - FONT_SZ) // 2
            if row[0] == "head":
                p.rect(x0, ry + ROW_H - 1, x1 - x0, 1, c["line_soft"])
                icon_txt = row[2] if len(row) > 2 else ""
                if icon_txt:
                    p.text(x0 + 2, txt_y, icon_txt, c["dim"], size=FONT_SZ)
                p.text(x0 + (22 if icon_txt else 2), txt_y, row[1], c["acc_l"], size=FONT_SZ, bold=True)
            else:
                if is_sel:
                    p.rect(x0 - 2, ry, x1 - x0 + 4, ROW_H, c["sel"])
                p.text(x0 + 8, txt_y, row[1], c["acc_l"] if is_sel else c["dim"], size=FONT_SZ, maxw=key_w - 12)
                p.text(x0 + key_w, txt_y, row[2], c["text"] if is_sel else c["dim"], size=FONT_SZ, maxw=x1 - x0 - key_w - 4)

        cr.restore()

        if len(rows) > max_vis:
            bar_h = max(12, avail * max_vis / len(rows))
            bar_y = y + (avail - bar_h) * off / max(1, len(rows) - max_vis)
            p.rect(x1 - 2, bar_y, 2, bar_h, c["faint"])

        self.draw_footer(p, x0, x1, h - 30, w)

    def draw_footer(self, p, x0, x1, y, w):
        c = self.c
        p.rect(x0, y - 4, x1 - x0, 1, c["line_soft"])
        badge = "SEARCH" if self.mode == "search" else "NORMAL"
        bw = p.text_w(badge, FONT_SZ) + 12
        p.rect(x0, y, bw, 20, c["field_l"])
        p.text(x0 + 6, y + 2, badge, c["acc_l"], size=FONT_SZ)
        hint = "j/k ↕ · ^D/^U ½ · g/G · / поиск · q выход" if self.mode == "normal" \
            else "↑↓ выбор · Enter/jj — к списку · Esc"
        p.text(x0 + bw + 8, y + 2, hint, c["faint"], size=FONT_SZ, maxw=x1 - x0 - bw - 10)


class SheetWindow(Gtk.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Keybinds")
        self.view = View()
        self.set_decorated(False)
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(W, H_MIN)
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK)
        self.area.connect("scroll-event", self.on_scroll)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("motion-notify-event", self.on_motion)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("focus-out-event", lambda *_: self.close())

    def redraw(self):
        self.area.queue_draw()

    def on_draw(self, _w, cr):
        w, h = self.get_allocated_width(), self.get_allocated_height()
        self.view.draw(cr, w, h)

    def in_close(self, x, y):
        cx, cy, cw, ch = self.view.close_rect
        return cx <= x < cx + cw and cy <= y < cy + ch

    def on_motion(self, _w, ev):
        hov = self.in_close(ev.x, ev.y)
        if hov != self.view.hover_close:
            self.view.hover_close = hov
            self.redraw()
        return True

    def on_press(self, _w, ev):
        if ev.button == 1 and self.in_close(ev.x, ev.y):
            self.close()
        return True

    def on_scroll(self, _w, ev):
        v = self.view
        if ev.direction == Gdk.ScrollDirection.UP:
            v.sel = max(0, v.sel - 3)
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            v.sel = min(len(v.rows()) - 1, v.sel + 3)
        self.redraw()
        return True

    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        mod = bool(ev.state & Gdk.ModifierType.MOD4_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""

        if mod and ch == "z":
            self.close()
            return True
        if ctrl and ch == "q":
            self.close()
            return True

        if ctrl and ch in ("d", "u"):     # как в nvim: полстраницы вниз/вверх
            rows = v.rows()
            if rows:
                step = max(1, v.max_vis // 2) * (1 if ch == "d" else -1)
                v.sel = max(0, min(len(rows) - 1, v.sel + step))
                v.scroll = max(0, v.scroll + step)
                d = 1 if step > 0 else -1
                while 0 < v.sel < len(rows) - 1 and rows[v.sel][0] == "head":
                    v.sel += d
            self.redraw()
            return True

        if ctrl and ch == "e":
            v.mode = "normal" if v.mode == "search" else "search"
            self.redraw()
            return True

        if v.mode == "search":
            self.key_search(ch, name, ev)
        else:
            self.key_normal(ch, name, shift)
        self.redraw()
        return True

    def key_search(self, ch, name, ev):
        v = self.view
        import time
        now = time.monotonic()
        rows = v.rows()
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if name in ("Down", "Up", "Tab", "ISO_Left_Tab") or (ctrl and ch in ("j", "k", "n", "p")):
            d = 1 if name in ("Down", "Tab") or ch in ("j", "n") else -1
            if rows:
                v.sel = max(0, min(len(rows) - 1, v.sel + d))
                while 0 < v.sel < len(rows) - 1 and rows[v.sel][0] == "head":
                    v.sel += d
            return
        if name == "Escape":
            if v.buf:
                v.buf = ""
                v.sel = 0
            else:
                v.mode = "normal"      # пусто — в навигацию, Esc ещё раз — выход
        elif name in ("Return", "KP_Enter"):
            v.mode = "normal"
        elif name == "BackSpace":
            v.buf = v.buf[:-1]
            v.sel = 0
        elif ch == "j":
            if now - v.pending_t < 0.4 and v.pending_jj:
                v.buf = v.buf[:-1]
                v.mode = "normal"
                v.pending_jj = False
                return
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 80 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0
            v.pending_t = now
            v.pending_jj = True
        else:
            v.pending_jj = False
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 80 and chr(u).isprintable():
                v.buf += chr(u)
                v.sel = 0

    def key_normal(self, ch, name, shift):
        v = self.view
        rows = v.rows()
        if name == "Escape" or ch == "q" or name == "BackSpace":
            self.close()
        elif ch == "j":
            v.sel = min(len(rows) - 1, v.sel + 1)
            while v.sel < len(rows) - 1 and rows[v.sel][0] == "head":
                v.sel += 1
        elif ch == "k":
            v.sel = max(0, v.sel - 1)
            while v.sel > 0 and rows[v.sel][0] == "head":
                v.sel -= 1
        elif ch == "g" and not shift:
            v.sel = 0
        elif ch == "g" and shift:
            v.sel = len(rows) - 1
        elif ch == "/":
            v.mode = "search"


def pidfile():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-keybinds.pid")


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None

    def do_activate(self):
        if self.win is not None:
            self.win.close()
            return
        from menu_one import close_others       # другое меню открыто — закрыть (14.10.2026)
        close_others(__file__)
        close = lambda: self.win.close() if self.win is not None else None
        self.win = SheetWindow(self)
        # щелчок мимо — закрыть (14.10.2026, «Super+Z тоже должен закрывать любым кликом
        # кроме самого окна») и затемнение, как у Super+X (14.10.2026): scrim_layer
        from scrim_layer import cover
        cover(self.win, NAMESPACE + "-catch", close)
        self.win.connect("destroy", lambda *_: self.closed())
        self.win.show_all()
        self.win.present()

    def closed(self):
        self.win = None                         # слои затемнения scrim_layer убирает сам


def shot(path, style=None):
    v = View()
    if style:
        v.style, v.c = style, colors(style)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H_MIN)
    cr = cairo.Context(surf)
    v.draw(cr, W, H_MIN)
    surf.write_to_png(path)


def check():
    v = View()
    rows = v.rows()
    binds = [r for r in rows if r[0] == "bind"]
    heads = [r for r in rows if r[0] == "head"]
    print("check: %d биндов, %d категорий" % (len(binds), len(heads)))
    assert binds, "нет биндов"


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--shot" in sys.argv:
        p = sys.argv[sys.argv.index("--shot") + 1] if sys.argv.index("--shot") + 1 < len(sys.argv) else "/tmp/keybinds.png"
        style = None
        for a in sys.argv:
            if a.startswith("style="):
                style = a.split("=", 1)[1]
        shot(p, style=style)
        print("saved", p)
    else:
        # pid — для close-or-clipboard: Ctrl+Q забирает niri, и без этого он закрывал
        # окно ПОД шпаргалкой (13.10.2026). Скрипт шлёт сюда SIGTERM.
        try:
            with open(pidfile(), "w") as f:
                f.write(str(os.getpid()))
        except OSError:
            pass
        App().run([])
