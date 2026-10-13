#!/usr/bin/env python3
"""hub_app — окно напоминаний и словаря, в стиле Discipline (cairo, рамка skeet/beta/default,
цвета из обоев, управление как в nvim по keycode; вид общий с routine_app.py, код свой —
Discipline тянет будильник и фокус, hub ничего этого не знает).

    hub_app.py            напоминания            hub_app.py dict   словарь (с выделенным текстом)

j/k — вниз/вверх · Tab, Shift+H/L — вкладка · i/a, Ctrl+E — новая запись (ввод обычным
текстом; Enter, jj, Ctrl+E — сохранить, Esc — отмена, Ctrl+S — тоже сохранить) ·
x — выполнено · 1/2/3 — важность High/Mid/Default · v — вид (общий/списком) ·
Alt+j/k — переставить выше/ниже · s — +1 час · Shift+S — на завтра 09:00 · dd — удалить (второе «d» подряд —
само подтверждение) · u — отменить последнее действие · Ctrl+R — повторить отменённое ·
z — повторение слов (Space — показать, y — знал, n — не знал) · q, Esc — закрыть.
Второй запуск поднимает уже открытое окно (GApplication).

При вводе новой (и в «e») Tab переводит на поля дата / время / важность — всё по желанию:
j/k — ±день / ±15 минут (Shift — неделя / час), можно и вписать: «завтра», «пт», «15.10»,
«1830». Без полей срок, как раньше, берётся из текста («купить хлеб завтра в 9»).

Мышь: кнопки-блоки в ряд над строкой статуса (+ запись, Выполнено, +1ч, завтра, удалить,
повторить) — то же самое, что клавиши выше, просто кликом; «удалить» мышью требует
повторного клика («точно?»), так как у мыши нет естественного аналога «dd». Перетаскивание
— за пустое место окна (не за строку и не за кнопку), изменение размера — за край/правый
нижний уголок, как у Discipline.

    hub_app.py --shot F [tab=items|words sel=N mode=normal|text style=…]   PNG без окна
"""
import datetime as dt
import math
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import hublib as H  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

APP_ID = "com.jarvis.hub"
STATE_DIR = os.path.expanduser("~/.config/hypr/state")
MATUGEN = os.path.expanduser("~/.cache/matugen")
FONT = "PxPlus HP 100LX 6x8 Jarvis"
PX = 12
BIG = 28
W = 460
PAD = 14
ROW_H = 22
DRAFT = "черновик"
SIZE_FILE = os.path.expanduser("~/.config/hub/app-size")
VIEW_FILE = os.path.expanduser("~/.config/hub/app-view")    # flat (общий) | list (списком)
PRIO_COL = {2: (0.91, 0.30, 0.30), 1: (0.95, 0.77, 0.22)}  # High — красный, Mid — жёлтый
HEAD_PRIO = {name: p for p, name in H.PRIO_NAMES.items()}
FIELDS = ("title", "date", "time", "prio")
TABS = ("items", "words")
TAB_NAMES = {"items": "Напоминания", "words": "Словарь"}

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "


# ── цвета (как у Discipline / Настроек) ────────────────────────────────────────

def hexrgb(h, d=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return d


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def palette():
    try:
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    p = {}
    for k, d in (("primary", "#b4c5ff"), ("secondary", "#c5c2ea"), ("tertiary", "#d2bdf6"),
                 ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("surface", "#10131c"), ("surface_container", "#1d1f29"),
                 ("surface_high", "#272a34"), ("on_primary", "#002979"), ("error", "#ffb4ab"),
                 ("st_hi", "#9fb4f5"), ("st_mid", "#5f74b4"), ("st_bot", "#465a94"),
                 ("st_dark", "#0a0c12")):
        p[k] = hexrgb(xc.get(k) or d, hexrgb(d))
    p["vivid"] = hexrgb(read(os.path.join(MATUGEN, "vivid.txt")), p["primary"])
    return p


def style_name():
    s = read(os.path.join(STATE_DIR, "settings-skin")).lower()
    return s if s in ("skeet", "beta") else "default"


def colors(style):
    p = palette()
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "skeet":
        acc = p["vivid"]

        def g(level, t=0.05):
            return mix((level / 255,) * 3, acc, t)
        return dict(frame="skeet", acc=acc, acc_l=mix(acc, white, 0.22), acc_d=mix(acc, black, 0.40),
                    bg=g(0x13), dot=g(0x18, 0.05), field=g(0x1b), field_l=g(0x24), sel=g(0x1e),
                    line=g(0x30, 0.08), line_soft=g(0x22, 0.06), gdark=g(0x0e, 0.03),
                    line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                    text=mix(hexrgb("#cdcdcd"), p["on_surface"], 0.35), dim=g(0x92, 0.10),
                    faint=g(0x50, 0.10), strip=[acc, p["tertiary"], p["secondary"]], err=p["error"])
    mode = read(os.path.join(STATE_DIR, "settings-mode")).lower() or "dark"
    if style == "beta" and mode == "light":
        ink = mix(p["surface"], black, 0.15)
        ink2 = mix(p["st_bot"], p["surface"], 0.35)
        bg = mix(mix(p["st_hi"], p["on_surface"], 0.85), white, 0.20)
        acc = mix(p["st_mid"], p["st_bot"], 0.40)
        return dict(frame="round", acc=acc, acc_l=acc, acc_d=mix(acc, bg, 0.45), bg=bg, dot=None,
                    field=mix(bg, white, 0.45), field_l=mix(bg, acc, 0.12), sel=mix(bg, acc, 0.16),
                    line=mix(bg, ink2, 0.28), line_soft=mix(bg, ink2, 0.14), gdark=bg,
                    text=ink, dim=mix(ink2, bg, 0.22), faint=mix(ink2, bg, 0.55),
                    strip=[acc], err=mix(p["error"], hexrgb("#7a0000"), 0.55))
    bg, cont = p["surface"], p["surface_container"]
    acc = p["primary"]
    return dict(frame="round", acc=acc, acc_l=mix(acc, white, 0.15), acc_d=mix(acc, bg, 0.50),
                bg=bg, dot=None, field=cont, field_l=p["surface_high"], sel=mix(bg, acc, 0.16),
                line=mix(cont, p["on_surface"], 0.16), line_soft=mix(cont, p["on_surface"], 0.08),
                gdark=bg, text=p["on_surface"], dim=mix(p["on_surface_variant"], bg, 0.30),
                faint=mix(p["on_surface_variant"], bg, 0.65), strip=[acc], err=p["error"])


def run_out(*cmd):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def selection():
    return run_out("wl-paste", "-p", "-n")


# ── рисование ────────────────────────────────────────────────────────────────

class Painter:
    def __init__(self, cr):
        self.cr = cr

    def rgb(self, c, a=1.0):
        self.cr.set_source_rgba(c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=1.0):
        self.rgb(c, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()

    def box(self, x, y, w, h, c):
        self.rgb(c)
        self.cr.set_line_width(1)
        self.cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        self.cr.stroke()

    def round(self, x, y, w, h, r):
        cr = self.cr
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def layout(self, s, px):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(s, -1)
        return lay

    def text_w(self, s, px=PX):
        return self.layout(s, px).get_pixel_size()[0]

    def text(self, x, y, s, c, px=PX, align="l", a=1.0, maxw=None):
        lay = self.layout(s, px)
        if maxw:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        w, _h = lay.get_pixel_size()
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        self.rgb(c, a)
        self.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(self.cr, lay)
        return w

    def measure_wrap(self, s, px=PX, maxw=None):
        lay = self.layout(s, px)
        if maxw:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        return lay.get_pixel_size()[1]

    def text_wrap(self, x, y, s, c, px=PX, maxw=None):
        """Многострочный текст с переносом по словам (строка редактирования) —
        возвращает высоту занятого блока в пикселях."""
        lay = self.layout(s, px)
        if maxw:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        self.rgb(c)
        self.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(self.cr, lay)
        return lay.get_pixel_size()[1]


def fld(d, k, default=None):
    """Поле и у sqlite3.Row, и у черновика-словаря (у Row нет .get)."""
    try:
        return d[k]
    except (KeyError, IndexError, TypeError):
        return default


def order_key(r):
    """Ручной порядок (Alt+j/k), у кого его нет — в конец по номеру."""
    return (r["pos"] is None, r["pos"] or 0, r["id"])


DOW_WORDS = (("пн", "пон", "mon"), ("вт", "втор", "tue"), ("ср", "сре", "wed"), ("чт", "чет", "thu"),
             ("пт", "пят", "fri"), ("сб", "суб", "sat"), ("вс", "вос", "sun"))


def parse_date(s, today=None):
    """«15.10», «15.10.26», «15», «завтра», «пт», «+3», «15.10 ср» -> date | None."""
    today = today or dt.date.today()
    s = re.sub(r"\s+[a-zа-яё]{2}$", "", s.strip().lower().replace(",", "."))
    if not s:
        return None
    rel = {"сегодня": 0, "today": 0, "завтра": 1, "tomorrow": 1, "послезавтра": 2}
    if s in rel:
        return today + dt.timedelta(days=rel[s])
    m = re.fullmatch(r"\+(\d{1,3})", s)
    if m:
        return today + dt.timedelta(days=int(m.group(1)))
    for i, words in enumerate(DOW_WORDS):
        if any(s.startswith(w) for w in words):
            return today + dt.timedelta(days=(i - today.weekday()) % 7 or 7)
    try:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?", s)
        if m:
            y = int(m.group(3)) if m.group(3) else today.year
            d = dt.date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and d < today:
                d = d.replace(year=d.year + 1)
            return d
        m = re.fullmatch(r"(\d{1,2})", s)
        if m:
            d = today.replace(day=int(m.group(1)))
            if d < today:
                nm = today.replace(day=1) + dt.timedelta(days=32)
                d = nm.replace(day=int(m.group(1)))
            return d
    except ValueError:
        return None
    return None


def parse_time(s):
    """«18:30», «1830», «18.30», «9» -> (ч, м) | None."""
    m = re.fullmatch(r"(\d{1,2})(?:[:.\s]?(\d{2}))?", s.strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    return (h, mi) if h < 24 and mi < 60 else None


def fmt_date(d):
    s = "%02d.%02d" % (d.day, d.month)
    if d.year != dt.date.today().year:
        s += ".%02d" % (d.year % 100)
    return s + " " + H.RU_DOW[d.weekday()]


def fields_due(fdate, ftime):
    """Поля «дата» и «время» -> (True, due|None) или (False, «дата»|«время»).
    Только время — сегодня (прошло — завтра); только дата — 09:00, а если это сегодня
    и 9 уже прошло — следующий целый час."""
    fdate, ftime = fdate.strip(), ftime.strip()
    if not fdate and not ftime:
        return True, None
    d = parse_date(fdate) if fdate else None
    if fdate and d is None:
        return False, "дата"
    t = parse_time(ftime) if ftime else None
    if ftime and t is None:
        return False, "время"
    now = dt.datetime.now()
    if d is None:
        d = now.date()
        if dt.datetime.combine(d, dt.time(*t)) <= now:
            d += dt.timedelta(days=1)
    if t is None:
        t = (9, 0)
        if dt.datetime.combine(d, dt.time(*t)) <= now:
            nh = now.replace(minute=0, second=0, microsecond=0) + dt.timedelta(hours=1)
            if nh.date() == d:
                t = (nh.hour, 0)
    return True, int(dt.datetime.combine(d, dt.time(*t)).timestamp())


def fmt_done(ts):
    """Когда выполнено: «13.10 14:32»."""
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else ""


class View:
    """Данные и раскладка — без GTK, чтобы --shot рисовал без окна."""

    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.active = True
        self.tab = "items"
        self.sel = {"items": 0, "words": 0}
        self.scroll = {"items": 0, "words": 0}
        self.mode = "normal"            # normal | text | quiz
        self.buf = ""
        self.buf2 = ""                  # для items: название уже набрано, buf — поле «когда»
        self.text_stage = "title"       # title | when (только для items)
        self.hover = None
        self.hits = []
        self.msg, self.msg_until = "", 0
        self.quiz = []
        self.revealed = False
        self.confirm_delete = None
        self.last_j = 0
        self.draft_items = []           # черновики — набраны, но не сохранены (09.10.2026)
        self.draft_words = []
        self.draft_seq = -1
        self.text_new = False
        self.editing_id = None          # id записи, которую редактируем (e)
        self.field = "title"            # поле ввода: title | date | time | prio (Tab)
        self.f_date, self.f_time, self.f_prio = "", "", 0
        self.edit_orig = ("", "")       # дата/время до правки — менялись ли
        self.view_mode = "list" if read(VIEW_FILE) == "list" else "flat"
        self.conn = H.connect()

    def reload_style(self):
        self.style = style_name()
        self.c = colors(self.style)

    def flash(self, text):
        self.msg, self.msg_until = text, time.monotonic() + 3

    # ── данные ──
    def rows(self):
        out = []
        if self.tab == "items":
            opened = sorted(H.items(self.conn, None, "open"), key=order_key)
            if self.view_mode == "list":        # списком — разделы по важности
                for pr in (2, 1, 0):
                    grp = [it for it in opened if (it["prio"] or 0) == pr]
                    if grp:
                        out.append(("head", H.PRIO_NAMES[pr]))
                        out += [("item", it) for it in grp]
            else:                               # общий — как раньше, важность точкой справа
                opened.sort(key=lambda r: r["list"] != H.DEFAULT_LIST)
                last = H.DEFAULT_LIST           # «Входящие» без заголовка — убрано по просьбе
                for it in opened:
                    if it["list"] != last:
                        out.append(("head", it["list"]))
                        last = it["list"]
                    out.append(("item", it))
            if self.draft_items:
                out.append(("head", "Не сохранено"))
                out += [("item", d) for d in self.draft_items]
            done = H.items(self.conn, None, "done", "task", 50)
            if done:
                out.append(("head", "Выполненные"))
                out += [("item", it) for it in sorted(done, key=lambda r: -(r["done_at"] or 0))]
        else:
            for w in H.words(self.conn, None, 500):
                out.append(("word", w))
            if self.draft_words:
                out.append(("head", "Не сохранено"))
                out += [("word", d) for d in self.draft_words]
        return out

    @staticmethod
    def new_pos(rows):
        """Строка ввода — под последней открытой записью, над «Выполненными»."""
        return next((i for i, r in enumerate(rows) if r == ("head", "Выполненные")), len(rows))

    def n_drafts(self):
        return len(self.draft_items) + len(self.draft_words)

    def sel_rows(self, rows):
        return [i for i, r in enumerate(rows) if r[0] != "head"]

    def move(self, step):
        rows = self.rows()
        sr = self.sel_rows(rows)
        if not sr:
            return
        cur = self.sel[self.tab]
        pos = sr.index(cur) if cur in sr else 0
        pos = max(0, min(len(sr) - 1, pos + step))
        self.sel[self.tab] = sr[pos]
        self.confirm_delete = None

    def current(self, rows):
        i = self.sel[self.tab]
        return rows[i] if 0 <= i < len(rows) else (None, None)

    # ── слои ──
    def frame_f(self):
        return 6 if self.c["frame"] == "skeet" else 1

    def height_min(self):
        return self.frame_f() + 2 + 10 + 18 + 14 + ROW_H * 3 + 10 + 24 + 14 + 18 + 8 + self.frame_f()

    def layout_y(self, h):
        f = self.frame_f()
        y = f + 2 + 10
        L = {"header": y}
        y += 18 + 14
        L["body_top"] = y
        L["footer"] = h - f - 16
        L["buttons"] = L["footer"] - 14 - 24
        L["body_bottom"] = L["buttons"] - 10
        return L

    def draw(self, cr, w, h):
        self.hits = []
        p = Painter(cr)
        f = self.frame_f()
        self.draw_frame(p, w, h)
        self.draw_grip(p, w, h, f)
        x0, x1 = PAD + f, w - PAD - f
        L = self.layout_y(h)
        self.draw_header(p, x0, x1, L["header"])
        if self.mode == "quiz":
            self.draw_quiz(p, x0, x1, L["body_top"], L["body_bottom"])
        else:
            self.draw_list(p, x0, x1, L["body_top"], L["body_bottom"])
        self.draw_buttons_row(p, x0, x1, L["buttons"])
        self.draw_footer(p, x0, x1, L["footer"])

    def draw_frame(self, p, w, h):
        c, cr = self.c, p.cr
        if c["frame"] == "skeet":
            l1 = mix(c["line1"], c["acc"], 0.45) if self.active else c["line1"]
            p.rect(0, 0, w, h, c["line3"])
            p.rect(1, 1, w - 2, h - 2, l1)
            p.rect(2, 2, w - 4, h - 4, c["line2"])
            p.rect(5, 5, w - 10, h - 10, l1)
            p.rect(6, 6, w - 12, h - 12, c["bg"])
            p.rgb(c["dot"])
            for yy in range(8, h - 6, 4):
                for xx in range(6 + (yy // 4) % 2 * 2, w - 6, 4):
                    cr.rectangle(xx, yy, 1, 1)
            cr.fill()
            if self.active:
                g = cairo.LinearGradient(6, 0, w - 6, 0)
                n = len(c["strip"])
                for i, col in enumerate(c["strip"]):
                    g.add_color_stop_rgb(i / max(1, n - 1), *col)
                cr.set_source(g)
                cr.rectangle(6, 6, w - 12, 1)
                cr.fill()
            else:
                p.rect(6, 6, w - 12, 1, c["line"])
        else:
            p.round(0.5, 0.5, w - 1, h - 1, 10)
            p.rgb(c["bg"])
            cr.fill_preserve()
            p.rgb(c["acc"] if self.active else c["line"])
            cr.set_line_width(1)
            cr.stroke()

    def draw_grip(self, p, w, h, f):
        p.rgb(self.c["faint"])
        for k in (4, 8, 12):
            for t in range(0, k, 2):
                p.cr.rectangle(w - f - 3 - t, h - f - 3 - (k - 1 - t), 1, 1)
        p.cr.fill()

    def draw_header(self, p, x0, x1, y):
        c = self.c
        x = x0
        for t in TABS:
            label = TAB_NAMES[t]
            on = t == self.tab
            hov = self.hover == ("tab", t)
            w = p.text_w(label)
            on_col = c["acc_l"] if self.active else c["text"]
            p.text(x, y, label, on_col if on else (c["text"] if hov else c["dim"]))
            if on:
                p.rect(x, y + 17, w, 2, c["acc"] if self.active else c["line"])
            self.hits.append(((x - 4, y - 6, w + 8, 26), ("tab", t)))
            x += w + 20
        p.text(x1, y, "×", c["dim"] if self.hover != "close" else c["text"], align="r")
        self.hits.append(((x1 - 12, y - 4, 16, 20), "close"))
        if self.tab == "items":                 # вид: общий / списком (клик или v)
            label = "вид: " + ("списком" if self.view_mode == "list" else "общий")
            hov = self.hover == ("view",)
            vw = p.text(x1 - 26, y, label, c["text"] if hov else c["faint"], align="r")
            self.hits.append(((x1 - 30 - vw, y - 4, vw + 8, 20), ("view",)))

    def row_bg(self, p, x0, x1, y, sel, key, h=ROW_H):
        c = self.c
        if sel:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"])
            p.rect(x0 + 1, y, 2, h, c["acc"])
        elif self.hover == key:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"], 0.5)
        self.hits.append(((x0, y, x1 - x0, h), key))

    def edit_display(self):
        """Что показывать на месте редактируемой строки — с учётом двух полей у items."""
        if self.editing_id is not None:
            return self.buf
        if self.tab == "items":
            if self.text_stage == "when":
                return self.buf2 + " · когда: " + self.buf
            return "новая: " + self.buf
        return "слово = перевод: " + self.buf

    def edit_text(self, word=False):
        cur = "▏" if (self.field == "title" or self.tab != "items") else ""
        return (self.buf if word else self.edit_display()) + cur

    def dot_w(self, d):
        """Место под точку важности справа (только в общем виде)."""
        return 14 if self.view_mode == "flat" and (fld(d, "prio", 0) or 0) > 0 else 0

    def draw_form(self, p, x, y):
        """Строка полей под вводом: дата · время · важность (Tab, клик)."""
        c = self.c
        by, bh = y + 1, ROW_H - 4
        for name, ph, w in (("date", "дата", 112), ("time", "время", 64), ("prio", None, 96)):
            on = self.field == name
            hov = self.hover == ("field", name)
            p.rect(x, by, w, bh, c["field"])
            p.box(x, by, w, bh, c["acc"] if on else (c["line"] if hov else c["line_soft"]))
            ty = by + (bh - 16) / 2 + 1
            if name == "prio":
                pr = self.f_prio
                tx = x + 6
                if pr:
                    p.rgb(PRIO_COL[pr])
                    p.cr.arc(x + 9, by + bh / 2, 3, 0, 2 * math.pi)
                    p.cr.fill()
                    tx = x + 17
                p.text(tx, ty, H.PRIO_NAMES[pr], c["text"] if (on or pr) else c["faint"])
            else:
                val = self.f_date if name == "date" else self.f_time
                if not val:
                    shown, col = ph, c["faint"]
                else:
                    if name == "date":
                        d = parse_date(val)
                        shown = fmt_date(d) if (d and not on) else val
                    else:
                        t = parse_time(val)
                        shown = "%02d:%02d" % t if (t and not on) else val
                    col = c["text"] if (parse_date(val) if name == "date" else parse_time(val)) \
                        else c["err"]
                if on:
                    shown = (val or "") + "▏"
                    col = c["acc_l"]
                p.text(x + 6, ty, shown, col, maxw=w - 10)
            self.hits.append(((x, by, w, bh), ("field", name)))
            x += w + 8

    def draw_list(self, p, x0, x1, y0, y1):
        c = self.c
        rows = self.rows()
        editing = self.mode == "text"
        if editing and self.text_new:
            k = self.new_pos(rows)
            rows = rows[:k] + [("new", None)] + rows[k:]
            self.text_target = k
        if not rows:
            p.text(x0, y0, "Пусто. Нажмите i или «+ запись» и впишите первое.", c["faint"])
            return
        # высоты строк разные (длинный текст переносится) — прокрутка по настоящим высотам
        hs = [self.row_h(p, i, rows, x0, x1, editing) for i in range(len(rows))]
        avail = y1 - y0
        sel = self.text_target if editing else self.sel[self.tab]
        sel = max(0, min(sel, len(rows) - 1))
        off = min(self.scroll[self.tab], sel)
        while off < sel and sum(hs[off:sel + 1]) > avail:
            off += 1
        while off > 0 and sum(hs[off - 1:]) <= avail:
            off -= 1
        self.scroll[self.tab] = off
        p.cr.save()
        p.cr.rectangle(x0 - 2, y0, x1 - x0 + 4, y1 - y0)
        p.cr.clip()
        try:
            self.draw_rows(p, c, rows, off, x0, x1, y0, y1, editing)
        finally:
            p.cr.restore()

    def row_h(self, p, i, rows, x0, x1, editing):
        kind, d = rows[i]
        if kind == "head":
            return ROW_H
        if kind == "new" or (editing and self.text_target == i):
            disp = self.edit_text(kind == "word")
            h = max(ROW_H, p.measure_wrap(disp, maxw=x1 - x0 - 24) + 6)
            return h + (ROW_H if self.tab == "items" else 0)
        if kind == "item":
            main, due = self.item_parts(d)
            dw = (p.text_w(due) + 12 if due else 0) + self.dot_w(d)
            return max(ROW_H, p.measure_wrap(main, maxw=x1 - x0 - 20 - dw) + 6)
        text = ("✎ " if fld(d, "_draft") else "") + "%s — %s" % (d["term"], d["translation"])
        return max(ROW_H, p.measure_wrap(text, maxw=x1 - x0 - 20) + 6)

    def draw_rows(self, p, c, rows, off, x0, x1, y, y1, editing):
        for i in range(off, len(rows)):
            if y >= y1:
                break
            kind, d = rows[i]
            if kind == "head":
                pr = HEAD_PRIO.get(d) if (self.tab == "items" and self.view_mode == "list") else None
                if pr:
                    p.rgb(PRIO_COL[pr])
                    p.cr.arc(x0 + 4, y + ROW_H / 2, 3, 0, 2 * math.pi)
                    p.cr.fill()
                    p.text(x0 + 13, y + 3, d, PRIO_COL[pr])
                else:
                    p.text(x0, y + 3, d, c["dim"])
                y += ROW_H
                continue
            is_sel = i == self.sel[self.tab]
            is_edit = editing and self.text_target == i
            cursor = "▏"
            if kind == "new":
                disp = self.edit_text()
                tw = x1 - x0 - 24
                tb = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                bh = tb + (ROW_H if self.tab == "items" else 0)
                self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                self.icon_box(p, x0 + 1, y + (ROW_H - 9) / 2, 9, c["acc_l"], filled=False)
                p.text_wrap(x0 + 14, y + 3, disp, c["acc_l"], maxw=tw)
                if self.tab == "items":
                    self.draw_form(p, x0 + 14, y + tb)
                y += bh
                continue
            elif kind == "item":
                draft = bool(fld(d, "_draft"))
                done = fld(d, "status") == "done"
                over = not done and bool(d["due"]) and d["due"] < H.now()
                if draft:
                    col = c["acc_l"]
                elif done:
                    col = c["faint"]
                else:
                    col = c["err"] if over else (c["acc_l"] if is_sel else c["text"])
                main, due = self.item_parts(d)
                if is_edit:
                    disp = self.edit_text()
                    tw = x1 - x0 - 24
                    tb = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                    bh = tb + ROW_H
                    self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                    self.icon_box(p, x0 + 1, y + (ROW_H - 9) / 2, 9, c["err"] if over else c["dim"], filled=False)
                    p.text_wrap(x0 + 14, y + 3, disp, c["acc_l"], maxw=tw)
                    self.draw_form(p, x0 + 14, y + tb)
                    y += bh
                    continue
                dot = self.dot_w(d)
                dw = (p.text_w(due) + 12 if due else 0) + dot
                tw = x1 - x0 - 20 - dw
                bh = max(ROW_H, p.measure_wrap(main, maxw=tw) + 6)
                self.row_bg(p, x0, x1, y, is_sel, ("row", i), h=bh)
                ty = y + (ROW_H - 16) / 2 + 1
                self.icon_box(p, x0 + 1, y + (ROW_H - 9) / 2, 9,
                              c["acc_l"] if draft else (c["err"] if over else c["dim"]), filled=done)
                p.text_wrap(x0 + 14, y + 3, main, col, maxw=tw)
                if dot:
                    p.rgb(PRIO_COL[fld(d, "prio", 0)], 0.5 if done else 1.0)
                    p.cr.arc(x1 - 9, y + ROW_H / 2, 3, 0, 2 * math.pi)
                    p.cr.fill()
                if due:
                    p.text(x1 - 6 - dot, ty, due, c["err"] if over else c["faint"], align="r")
                y += bh
                continue
            else:
                draft = bool(fld(d, "_draft"))
                text = ("✎ " if draft else "") + "%s — %s" % (d["term"], d["translation"])
                col = c["acc_l"] if (is_sel or draft) else c["text"]
                if is_edit:
                    disp = self.buf + cursor
                    tw = x1 - x0 - 24
                    bh = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                    self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                    self.icon_dot(p, x0 + 5, y + ROW_H / 2, c["acc_l"])
                    p.text_wrap(x0 + 14, y + 3, disp, c["acc_l"], maxw=tw)
                    y += bh
                    continue
                tw = x1 - x0 - 20
                bh = max(ROW_H, p.measure_wrap(text, maxw=tw) + 6)
                self.row_bg(p, x0, x1, y, is_sel, ("row", i), h=bh)
                self.icon_dot(p, x0 + 5, y + ROW_H / 2, c["acc_l"] if (is_sel or draft) else c["faint"])
                p.text_wrap(x0 + 14, y + 3, text, col, maxw=tw)
                y += bh
                continue
            y += ROW_H

    def item_parts(self, d):
        """(текст, срок) для строки списка — без «· #29», как в обычных списках задач."""
        main = ("✎ " if fld(d, "_draft") else "") + d["text"] + (" ↻" if d["repeat"] else "")
        if fld(d, "status") == "done":           # выполненная — когда (дата и время)
            return main, fmt_done(fld(d, "done_at"))
        due = H.fmt_when(d["due"]) if d["due"] else ""
        return main, due

    def icon_box(self, p, x, y, s, col, filled):
        if filled:
            p.rect(x, y, s, s, col)
        else:
            p.box(x, y, s, s, col)

    def icon_dot(self, p, x, y, col):
        p.rgb(col)
        p.cr.arc(x, y, 2.5, 0, 2 * math.pi)
        p.cr.fill()

    def draw_quiz(self, p, x0, x1, y0, y1):
        c = self.c
        cy = (y0 + y1) / 2
        if not self.quiz:
            p.text((x0 + x1) / 2, cy, "Повторять нечего. Esc — назад.", c["faint"], align="c")
            return
        w = self.quiz[0]
        p.text((x0 + x1) / 2, cy - 30, w["term"], c["acc_l"], px=BIG, align="c")
        if self.revealed:
            p.text((x0 + x1) / 2, cy + 10, w["translation"], c["text"], align="c")
        p.text((x0 + x1) / 2, y1 - 6, "осталось %d" % len(self.quiz), c["faint"], align="c")

    def button(self, p, x, y, w, label, key, accent=False):
        """Полноразмерная кнопка — как в Discipline (button())."""
        c = self.c
        hov = self.hover == key
        if c["frame"] == "skeet":
            p.rect(x, y, w, 24, c["line3"])
            p.rect(x + 1, y + 1, w - 2, 22, c["line"])
            g = cairo.LinearGradient(0, y + 2, 0, y + 22)
            top = c["field_l"] if not hov else mix(c["field_l"], c["text"], 0.06)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *c["field"])
            p.cr.set_source(g)
            p.cr.rectangle(x + 2, y + 2, w - 4, 20)
            p.cr.fill()
        else:
            p.round(x + 0.5, y + 0.5, w - 1, 23, 6)
            p.rgb(c["sel"] if hov else c["field"])
            p.cr.fill_preserve()
            p.rgb(c["line"])
            p.cr.set_line_width(1)
            p.cr.stroke()
        col = c["acc_l"] if (accent or hov) else c["text"]
        p.text(x + w / 2, y + 5, label, col, align="c")
        self.hits.append(((x, y, w, 24), key))

    def buttons(self, p, x0, x1, y, items):
        """items: [(подпись, ключ[, accent])] — в ряд; ширина по подписи, остаток поровну."""
        n = len(items)
        if not n:
            return
        gap = 6 if n > 4 else 8
        need = [p.text_w(it[0]) + 16 for it in items]
        free = x1 - x0 - gap * (n - 1) - sum(need)
        ws = [w + free / n for w in need] if free >= 0 else \
             [w * (x1 - x0 - gap * (n - 1)) / sum(need) for w in need]
        x = x0
        for it, w in zip(items, ws):
            accent = it[2] if len(it) > 2 else False
            self.button(p, round(x), y, round(w), it[0], it[1], accent)
            x += w + gap

    def draw_buttons_row(self, p, x0, x1, y):
        if self.mode == "text":
            save_label = "сохранить" if self.editing_id is not None else "добавить"
            self.buttons(p, x0, x1, y, [("отмена", ("btn", "canceltext")),
                                         (save_label, ("btn", "savetext"), True)])
            return
        if self.mode == "quiz":
            self.buttons(p, x0, x1, y, [("назад", ("btn", "back")),
                                         ("не знал", ("btn", "no")),
                                         ("знал", ("btn", "yes")),
                                         ("показать", ("btn", "reveal"), True)])
            return
        rows = self.rows()
        kind, d = self.current(rows)
        confirming = bool(self.confirm_delete and kind in ("item", "word") and d
                           and self.confirm_delete[0] == (kind, d["id"])
                           and time.monotonic() < self.confirm_delete[1])
        n = self.n_drafts()
        save = [("сохранить (%d)" % n, ("btn", "savedraft"), True)] if n else []
        draft = bool(d is not None and fld(d, "_draft"))
        delete = ("точно?" if confirming else "удалить", ("btn", "delete"))
        if self.tab == "items":
            btns = [("+ запись", ("btn", "new"), not n)] + save
            if kind == "item" and draft:
                btns.append(delete)
            elif kind == "item" and fld(d, "status") == "done":
                btns += [("вернуть", ("btn", "done")), delete]
            elif kind == "item" and n:
                btns += [("Выполнено", ("btn", "done")), delete]
            elif kind == "item":
                btns += [("Выполнено", ("btn", "done")), ("+1ч", ("btn", "snooze1")),
                         ("завтра", ("btn", "snoozetomorrow")), delete]
        else:
            btns = [("+ слово", ("btn", "new"), not n)] + save
            if rows and not n:
                btns.append(("повторить", ("btn", "quiz")))
            if kind == "word":
                btns.append(delete)
        self.buttons(p, x0, x1, y, btns)

    FIELD_HINTS = {
        "title": "Enter · Tab — срок и важность · Esc",
        "date": "j/k ±день, Shift ±неделя · «пт» «15.10»",
        "time": "j/k ±15 мин, Shift ±час · «1830» «9»",
        "prio": "j/k или 1/2/3 · Enter — %s",
    }
    HINTS = {
        "text": "Enter / jj — добавить в список · Esc — отмена",
        "quiz": "Space — показать · y знал · n не знал · Esc назад",
    }

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        badge = {"text": "INSERT", "quiz": "QUIZ"}.get(self.mode, "NORMAL")
        bw = p.text_w(badge) + 10
        p.rect(x0, y - 1, bw, 16, c["field_l"])
        p.text(x0 + 5, y, badge, c["acc_l"])
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x0 + bw + 10, y, self.msg, c["text"], maxw=x1 - x0 - bw - 10)
        elif self.mode == "normal" and self.n_drafts():
            p.text(x0 + bw + 10, y, "не сохранено: %d · Ctrl+S — сохранить"
                   % self.n_drafts(), c["acc_l"], maxw=x1 - x0 - bw - 10)
        else:
            hint = self.HINTS.get(self.mode) or (
                "1-3 важность · v вид · Alt+j/k порядок" if self.tab == "items"
                else "i/a новое · e ред. · z повторить · d удалить · y/p")
            if self.mode == "text" and self.tab == "items":
                hint = self.FIELD_HINTS[self.field]
                if "%s" in hint:
                    hint = hint % ("сохранить" if self.editing_id is not None else "добавить")
            p.text(x0 + bw + 10, y, hint, c["faint"], maxw=x1 - x0 - bw - 10)


# ── окно ──────────────────────────────────────────────────────────────────────

class HubWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="items"):
        super().__init__(application=app, title="Hub")
        self.view = View()
        self.view.text_target, self.view.text_new = -1, False
        self.view.tab = tab if tab in TABS else "items"
        self.set_title(self.tab_title())
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_size_request(W, self.view.height_min())
        sw, sh = W, max(self.view.height_min(), 480)
        try:
            a, b = open(SIZE_FILE).read().split()[:2]
            sw, sh = max(W, int(a)), max(self.view.height_min(), int(b))
        except (OSError, ValueError):
            pass
        self.set_default_size(sw, sh)
        self.last_size = (sw, sh)
        self.connect("configure-event", self.on_configure)
        self.cursor_name = None
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.undo_stack = []
        self.redo_stack = []
        self.pending = ""
        self.pending_t = 0
        self.pending_jj = False
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", lambda *_: self.set_hover(None))
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        self.close_armed = 0
        self.connect("notify::is-active", self.on_active)
        GLib.timeout_add(500, self.tick)

    def on_delete(self, *_a):
        """Закрытие с несохранённым: первый раз — предупредить, второй (в 3 с) — выйти."""
        v = self.view
        if v.n_drafts() and time.monotonic() > self.close_armed:
            self.close_armed = time.monotonic() + 3
            v.flash("не сохранено: %d — ^S сохранить, ещё раз — закрыть без сохранения"
                    % v.n_drafts())
            self.present()
            self.redraw()
            return True
        return False

    def tab_title(self):
        return "Reminders" if self.view.tab == "items" else "Dictionary"

    def on_configure(self, _w, ev):
        size = (ev.width, ev.height)
        if size != self.last_size:
            self.last_size = size
            if getattr(self, "size_save", None):
                GLib.source_remove(self.size_save)
            self.size_save = GLib.timeout_add(600, self.save_size)
        return False

    def save_size(self):
        self.size_save = None
        try:
            os.makedirs(os.path.dirname(SIZE_FILE), exist_ok=True)
            with open(SIZE_FILE, "w") as f:
                f.write("%d %d\n" % self.last_size)
        except OSError:
            pass
        return False

    EDGES = {"nw": Gdk.WindowEdge.NORTH_WEST, "n": Gdk.WindowEdge.NORTH,
             "ne": Gdk.WindowEdge.NORTH_EAST, "e": Gdk.WindowEdge.EAST,
             "se": Gdk.WindowEdge.SOUTH_EAST, "s": Gdk.WindowEdge.SOUTH,
             "sw": Gdk.WindowEdge.SOUTH_WEST, "w": Gdk.WindowEdge.WEST}

    def edge_at(self, x, y):
        a = self.area.get_allocation()
        w, h, m = a.width, a.height, 6
        if x >= w - 18 and y >= h - 18:
            return "se"
        v = "n" if y < m else "s" if y >= h - m else ""
        hz = "w" if x < m else "e" if x >= w - m else ""
        return (v + hz) or None

    def set_cursor(self, name):
        if name == self.cursor_name:
            return
        self.cursor_name = name
        gw = self.area.get_window()
        if gw is not None:
            gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), name) if name else None)

    def on_active(self, *_a):
        self.view.active = self.is_active()
        self.redraw()

    def redraw(self):
        self.area.queue_draw()

    def tick(self):
        if style_name() != self.view.style:
            self.view.reload_style()
        self.redraw()
        return True

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.view.draw(cr, a.width, a.height)

    def hit(self, x, y):
        for (hx, hy, hw, hh), key in reversed(self.view.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return key
        return None

    def set_hover(self, key):
        if key != self.view.hover:
            self.view.hover = key
            self.redraw()

    def on_motion(self, _w, ev):
        edge = self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else None)
        self.set_hover(None if edge else self.hit(ev.x, ev.y))

    def on_scroll(self, _w, ev):
        d = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction)
        if d:
            self.view.move(d)
            self.redraw()
        return True

    def on_click(self, _w, ev):
        v = self.view
        edge = self.edge_at(ev.x, ev.y)
        if edge and ev.button == 1:
            self.begin_resize_drag(self.EDGES[edge], ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        key = self.hit(ev.x, ev.y)
        if key is None:
            if ev.button == 1:
                self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        if ev.button != 1:
            return True
        if key == "close":
            self.close()
        elif isinstance(key, tuple) and key[0] == "tab":
            v.tab, v.mode = key[1], "normal"
            v.confirm_delete = None
            self.set_title(self.tab_title())
            self.resize_to_min()
        elif isinstance(key, tuple) and key[0] == "row":
            v.sel[v.tab] = key[1]
            v.confirm_delete = None
        elif isinstance(key, tuple) and key[0] == "btn":
            self.do_button(key[1])
        elif key == ("view",):
            self.toggle_view()
        elif isinstance(key, tuple) and key[0] == "field" and v.mode == "text":
            if key[1] == "prio" and v.field == "prio":
                v.f_prio = (v.f_prio + 1) % 3          # повторный клик — следующая важность
            v.field = key[1]
        self.redraw()
        return True

    # ── кнопки подвала — те же действия, что и клавиши в key_normal/key_quiz ──
    def do_button(self, action):
        v = self.view
        if v.mode == "text":
            if action == "savetext":
                if v.editing_id is not None:
                    self.finish_edit()
                else:
                    self.submit_text()
            elif action == "canceltext":
                self.cancel_text()
            return
        if v.mode == "quiz":
            if action == "reveal":
                v.revealed = True
            elif action in ("yes", "no") and v.quiz and v.revealed:
                H.review(v.conn, v.quiz.pop(0)["id"], action == "yes")
                v.revealed = False
            elif action == "back":
                v.mode = "normal"
            return
        if action == "savedraft":
            self.save_drafts()
        elif action == "new":
            self.start_new()
        elif action == "quiz":
            self.start_quiz()
        elif action == "delete":
            self.action_delete()
        elif action == "done":
            self.act_done()
        elif action == "snooze1":
            self.act_snooze(secs=3600, label="+1ч")
        elif action == "snoozetomorrow":
            self.act_snooze_tomorrow()

    # ── отмена/повтор — стек (метка, вперёд, назад), как у Discipline, но
    # для отдельных SQL-операций hublib, а не одного JSON-снимка ──
    def run_action(self, label, forward, backward):
        forward()
        self.undo_stack.append((label, forward, backward))
        del self.undo_stack[:-50]
        self.redo_stack.clear()

    def do_undo(self):
        v = self.view
        if not self.undo_stack:
            v.flash("нечего отменять")
            return
        label, forward, backward = self.undo_stack.pop()
        backward()
        self.redo_stack.append((label, forward, backward))
        v.flash("отменено: " + label)

    def do_redo(self):
        v = self.view
        if not self.redo_stack:
            v.flash("нечего повторять")
            return
        label, forward, backward = self.redo_stack.pop()
        forward()
        self.undo_stack.append((label, forward, backward))
        v.flash("повтор: " + label)

    def act_done(self):
        """x / «Выполнено»: открытая → выполненные; выполненная → обратно («вернуть»)."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item" or fld(d, "_draft"):
            return
        iid, prev_due = d["id"], d["due"]
        if d["status"] == "done":
            self.run_action("вернуть", lambda: H.reopen(v.conn, iid, "pc"),
                            lambda: H.done(v.conn, iid, "pc"))
            v.flash("вернул в список")
            return
        had_repeat = bool(d["repeat"]) and bool(prev_due)

        def fwd():
            H.done(v.conn, iid, "pc")

        def bwd():
            if had_repeat:
                H.edit(v.conn, iid, due=prev_due)
            else:
                H.reopen(v.conn, iid, "pc")
        self.run_action("выполнено", fwd, bwd)

    def act_snooze(self, secs=None, until=None, label="+1ч"):
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item" or fld(d, "_draft") or d["status"] != "open":
            return
        iid, prev_due = d["id"], d["due"]

        def fwd():
            H.snooze(v.conn, iid, secs, until, source="pc")

        def bwd():
            H.edit(v.conn, iid, due=prev_due)
        self.run_action(label, fwd, bwd)

    def act_snooze_tomorrow(self):
        import hubtg
        self.act_snooze(until=hubtg.tomorrow_9(), label="завтра")

    def act_delete_core(self, kind, d):
        v = self.view
        if fld(d, "_draft"):
            lst = v.draft_items if kind == "item" else v.draft_words
            if d in lst:
                lst.remove(d)
            v.confirm_delete = None
            v.flash("черновик убран")
            v.move(0)
            return
        if kind == "item":
            iid, was_done = d["id"], d["status"] == "done"

            def fwd():
                H.drop(v.conn, iid, "pc")

            def bwd():
                H.reopen(v.conn, iid, "pc")
                if was_done:
                    H.done(v.conn, iid, "pc")
        else:
            wid = d["id"]
            term, translation = d["term"], d["translation"]
            try:
                context, src, dst = d["context"], d["src"], d["dst"]
            except (KeyError, IndexError):
                context, src, dst = "", "en", "ru"

            def fwd():
                H.del_word(v.conn, wid)

            def bwd():
                H.add_word(v.conn, term, translation, context, src, dst)
        self.run_action("удаление", fwd, bwd)
        v.confirm_delete = None
        v.flash("удалено")

    def act_delete_keyboard(self):
        """d — подтверждение: первый d помечает, второй d подряд (3 с) удаляет."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind not in ("item", "word"):
            return
        key = (kind, d["id"])
        now = time.monotonic()
        if v.confirm_delete and v.confirm_delete[0] == key and now < v.confirm_delete[1]:
            self.act_delete_core(kind, d)
        else:
            v.confirm_delete = (key, now + 3)
            v.flash("ещё раз d — удалить")

    def reset_fields(self, d=None):
        """Поля дата/время/важность: пустые для новой, из записи — для «e»."""
        v = self.view
        v.field = "title"
        v.f_date = v.f_time = ""
        v.f_prio = (fld(d, "prio", 0) or 0) if d is not None else 0
        if d is not None and d["due"]:
            t = dt.datetime.fromtimestamp(d["due"])
            v.f_date, v.f_time = fmt_date(t.date()), t.strftime("%H:%M")
        v.edit_orig = (v.f_date, v.f_time)

    def cancel_text(self):
        v = self.view
        v.mode, v.buf, v.text_target, v.text_new, v.editing_id = "normal", "", -1, False, None
        self.reset_fields()

    def select_item(self, iid):
        """Курсор — на запись iid (после перестановки, смены важности или вида)."""
        v = self.view
        for k, r in enumerate(v.rows()):
            if r[0] == "item" and not fld(r[1], "_draft") and r[1]["id"] == iid:
                v.sel[v.tab] = k
                return

    def toggle_view(self):
        v = self.view
        kind, d = v.current(v.rows())
        v.view_mode = "list" if v.view_mode == "flat" else "flat"
        try:
            os.makedirs(os.path.dirname(VIEW_FILE), exist_ok=True)
            with open(VIEW_FILE, "w") as f:
                f.write(v.view_mode + "\n")
        except OSError:
            pass
        if kind == "item" and not fld(d, "_draft"):
            self.select_item(d["id"])
        v.move(0)                       # курсор не должен остаться на заголовке
        v.flash("вид: " + ("списком (по важности)" if v.view_mode == "list" else "общий"))

    def act_prio(self, pr):
        """1/2/3 — важность High/Mid/Default текущей записи."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item":
            return
        if fld(d, "_draft"):
            d["prio"] = pr
        else:
            iid, old = d["id"], d["prio"] or 0
            if old == pr:
                return
            self.run_action("важность", lambda: H.set_prio(v.conn, iid, pr, "pc"),
                            lambda: H.set_prio(v.conn, iid, old, "pc"))
            self.select_item(iid)
        v.flash("важность: " + H.PRIO_NAMES[pr])

    def move_item(self, step):
        """Alt+j/k — переставить открытую запись ниже/выше внутри своего раздела."""
        v = self.view
        rows = v.rows()
        i = v.sel[v.tab]
        kind, d = v.current(rows)
        if v.tab != "items" or kind != "item" or fld(d, "_draft") or d["status"] != "open":
            v.flash("переставлять можно открытые записи")
            return
        j = i + step
        if not (0 <= j < len(rows)) or rows[j][0] != "item" or fld(rows[j][1], "_draft") \
                or rows[j][1]["status"] != "open":
            v.flash("выше некуда" if step < 0 else "ниже некуда")
            return
        a, b = d["id"], rows[j][1]["id"]
        opened = sorted(H.items(v.conn, None, "open"), key=order_key)
        before = {r["id"]: r["pos"] for r in opened}
        after = {r["id"]: float(k + 1) for k, r in enumerate(opened)}
        after[a], after[b] = after[b], after[a]
        self.run_action("перестановка", lambda: H.set_pos(v.conn, after),
                        lambda: H.set_pos(v.conn, before))
        self.select_item(a)

    def start_new(self):
        """Ввод новой — всегда последней строкой под списком, остальные видны."""
        v = self.view
        v.mode, v.buf, v.buf2, v.text_stage = "text", "", "", "title"
        v.text_new = True
        v.editing_id = None
        self.reset_fields()
        v.text_target = v.new_pos(v.rows())

    def start_edit(self):
        """e — редактировать текст текущей записи."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind == "item" and not fld(d, "_draft") and d["status"] != "done":
            v.mode, v.buf, v.text_stage = "text", d["text"], "title"
            v.editing_id = d["id"]
            self.reset_fields(d)
            v.text_target = v.sel[v.tab]
            v.text_new = False
        elif kind == "word" and not fld(d, "_draft"):
            v.mode, v.buf = "text", "%s = %s" % (d["term"], d["translation"])
            v.editing_id = d["id"]
            v.text_target = v.sel[v.tab]
            v.text_new = False
        else:
            v.flash("нечего редактировать")

    def finish_edit(self):
        """Завершить редактирование (Enter/jj/^S/^E) — изменить ту же запись, не копию.
        13.10.2026: ^S и ^E шли через submit_text и добавляли дубль."""
        v = self.view
        text = v.buf.strip()
        iid = v.editing_id
        if v.tab == "items" and iid is not None:
            ok, due = fields_due(v.f_date, v.f_time)
            if not ok:
                v.field = "date" if due == "дата" else "time"
                v.flash("не разобрано поле «%s»" % due)
                return
            due_changed = (v.f_date, v.f_time) != v.edit_orig
            prio = v.f_prio
        kind, d = v.current(v.rows())
        self.cancel_text()
        if not text or iid is None:
            return
        if v.tab == "items":
            old = H.get_item(v.conn, iid)
            if old is None:
                return
            old_text, old_due, old_prio = old["text"], old["due"], old["prio"] or 0

            def fwd():
                H.edit(v.conn, iid, text=text, due=due if due_changed else "keep", source="pc")
                if prio != old_prio:
                    H.set_prio(v.conn, iid, prio, "pc")

            def bwd():
                H.edit(v.conn, iid, text=old_text, due=old_due if due_changed else "keep", source="pc")
                if prio != old_prio:
                    H.set_prio(v.conn, iid, old_prio, "pc")
            self.run_action("редактирование", fwd, bwd)
            self.select_item(iid)
        else:
            for sep in ("=", " — ", " - "):
                if sep in text:
                    t, tr = [x.strip() for x in text.split(sep, 1)]
                    break
            else:
                v.flash("формат: слово = перевод")
                return
            old_t, old_tr = d.get("term", ""), d.get("translation", "")
            def fwd():
                H.add_word(v.conn, t, tr)
            def bwd():
                H.add_word(v.conn, old_t, old_tr)
            self.run_action("редактирование", fwd, bwd)

    def copy_current(self):
        """y — скопировать текст записи в буфер обмена."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind == "item":
            text = d["text"]
        elif kind == "word":
            text = "%s = %s" % (d["term"], d["translation"])
        else:
            return
        try:
            import subprocess
            subprocess.Popen(["wl-copy", text], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            v.flash("скопировано")
        except OSError:
            v.flash("wl-copy не найден")

    def paste_new(self):
        """p — вставить текст из буфера обмена как новую запись."""
        v = self.view
        try:
            import subprocess
            text = subprocess.run(["wl-paste", "-n"], capture_output=True, text=True, timeout=2).stdout.strip()
        except (OSError, subprocess.TimeoutExpired):
            v.flash("wl-paste не найден")
            return
        if not text:
            v.flash("буфер пуст")
            return
        v.mode, v.buf, v.buf2, v.text_stage = "text", text, "", "title"
        v.text_new = True
        v.text_target = v.new_pos(v.rows())

    def start_quiz(self):
        v = self.view
        v.quiz = list(H.due_words(v.conn, 20))
        v.revealed = False
        v.mode = "quiz"

    def action_delete(self):
        """Клик по кнопке «удалить» — второй клик подряд подтверждает."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind not in ("item", "word"):
            return
        key = (kind, d["id"])
        now = time.monotonic()
        if v.confirm_delete and v.confirm_delete[0] == key and now < v.confirm_delete[1]:
            self.act_delete_core(kind, d)
        else:
            v.confirm_delete = (key, now + 3)
            v.flash("ещё раз — удалить")

    def resize_to_min(self):
        self.set_size_request(W, self.view.height_min())

    def set_tab(self, tab):
        self.view.tab, self.view.mode = tab, "normal"

    # ── клавиатура ──
    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""
        # ^E — смена режима записи/чтения: из normal входит в ввод, из text — сохраняет.
        if ctrl and ch == "e" and v.mode != "quiz":
            self.submit_text() if v.mode == "text" else self.start_new()
            self.redraw()
            return True
        if ctrl and ch == "s":
            if v.mode == "text":
                self.submit_text()
            self.save_drafts()
            self.redraw()
            return True
        if v.mode == "text":
            self.key_text(ch, name, ev)
        elif v.mode == "quiz":
            self.key_quiz(ch, name)
        elif alt and ch in ("j", "k"):
            self.move_item(1 if ch == "j" else -1)
        else:
            self.key_normal(ch, ctrl, name, shift)
        self.redraw()
        return True

    def key_field(self, ch, name, ev):
        """Поля дата/время/важность: j/k (латиницей) и стрелки — шаг, остальное — ввод."""
        v = self.view
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        u = Gdk.keyval_to_unicode(ev.keyval)
        uc = chr(u) if u else ""
        step = {"Up": 1, "Down": -1}.get(name) or ({"k": 1, "j": -1, "K": 1, "J": -1}.get(uc) or 0)
        if v.field == "prio":
            if step:
                v.f_prio = max(0, min(2, v.f_prio + step))
            elif uc in ("1", "2", "3"):
                v.f_prio = {"1": 2, "2": 1, "3": 0}[uc]
            elif uc == " ":
                v.f_prio = (v.f_prio + 1) % 3
            return
        attr = "f_date" if v.field == "date" else "f_time"
        val = getattr(v, attr)
        if step:
            if v.field == "date":
                d = parse_date(val)
                d = d + dt.timedelta(days=step * (7 if shift else 1)) if d else dt.date.today()
                setattr(v, attr, fmt_date(d))
            else:
                t = parse_time(val)
                if t:
                    m = (t[0] * 60 + t[1] + step * (60 if shift else 15)) % (24 * 60)
                else:
                    n = dt.datetime.now()
                    m = (n.hour * 60 + n.minute + 15) // 15 * 15 % (24 * 60)
                setattr(v, attr, "%02d:%02d" % divmod(m, 60))
        elif name == "BackSpace":
            setattr(v, attr, val[:-1])
        elif name == "Delete":
            setattr(v, attr, "")
        elif uc and uc.isprintable() and len(val) < 16:
            setattr(v, attr, val + uc)

    def key_text(self, ch, name, ev):
        v = self.view
        if name == "Escape":
            self.cancel_text()
        elif name in ("Return", "KP_Enter"):
            if v.editing_id is not None:
                self.finish_edit()
            else:
                self.submit_text()
        elif v.tab == "items" and name in ("Tab", "ISO_Left_Tab"):
            k = FIELDS.index(v.field) + (-1 if name == "ISO_Left_Tab" else 1)
            v.field = FIELDS[k % len(FIELDS)]
        elif v.tab == "items" and v.field != "title":
            self.key_field(ch, name, ev)
        elif name == "BackSpace":
            v.buf = v.buf[:-1]
        elif ch == "j":
            now = time.monotonic()
            if now - self.pending_t < 0.4 and self.pending_jj:
                v.buf = v.buf[:-1]
                if v.editing_id is not None:
                    self.finish_edit()
                else:
                    self.submit_text()
                return
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 200 and chr(u).isprintable():
                v.buf += chr(u)
            self.pending_t = now
            self.pending_jj = True
        else:
            self.pending_jj = False
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 200 and chr(u).isprintable():
                v.buf += chr(u)

    def submit_text(self):
        """Enter/jj/«добавить»: строка уходит в список черновиком. В базу — только по
        ^S или «сохранить» (09.10.2026: «ничего не должно сохраняться само»)."""
        v = self.view
        if v.editing_id is not None:
            self.finish_edit()
            return
        text = v.buf.strip()
        fok, fdue = fields_due(v.f_date, v.f_time) if v.tab == "items" else (True, None)
        if text and not fok:
            v.field = "date" if fdue == "дата" else "time"
            v.flash("не разобрано поле «%s»" % fdue)
            return
        prio = v.f_prio
        self.cancel_text()
        if not text:
            return
        if v.tab == "items":
            lname, body = H.split_list(text)
            clean, due, repeat = H.parse_when(body)
            if fdue is not None:                       # поля дата/время главнее текста
                due = fdue
            d = {"id": v.draft_seq, "text": clean or body.strip(), "due": due, "repeat": repeat,
                 "status": "open", "kind": "task", "list": lname, "_draft": True, "_raw": text,
                 "prio": prio}
            lst = v.draft_items
        else:
            for sep in ("=", " — ", " - "):
                if sep in text:
                    t, tr = [x.strip() for x in text.split(sep, 1)]
                    break
            else:
                v.flash("формат: слово = перевод")
                return
            if not t or not tr:
                v.flash("нужны слово и перевод")
                return
            d = {"id": v.draft_seq, "term": t, "translation": tr, "_draft": True}
            lst = v.draft_words
        v.draft_seq -= 1

        def fwd(d=d, lst=lst):
            if d not in lst:
                lst.append(d)

        def bwd(d=d, lst=lst):
            if d in lst:
                lst.remove(d)
        self.run_action(DRAFT, fwd, bwd)
        rows = v.rows()
        v.sel[v.tab] = next((i for i, r in enumerate(rows) if r[1] is d), v.sel[v.tab])

    def save_drafts(self):
        v = self.view
        n = v.n_drafts()
        if not n:
            return
        # черновые шаги отмены заменяются настоящими (каждая запись — отдельный шаг)
        self.undo_stack[:] = [a for a in self.undo_stack if a[0] != DRAFT]
        self.redo_stack[:] = [a for a in self.redo_stack if a[0] != DRAFT]
        for d in list(v.draft_items):
            box = {}

            def fwd(d=d, box=box):
                box["id"] = H.add_item(v.conn, d["text"], d["list"], d["due"], d["repeat"], "pc",
                                       prio=d.get("prio", 0))

            def bwd(box=box):
                H.drop(v.conn, box["id"], "pc")
            self.run_action("новая запись", fwd, bwd)
        for d in list(v.draft_words):
            box = {}

            def fwd(t=d["term"], tr=d["translation"], box=box):
                box["id"], box["new"] = H.add_word(v.conn, t, tr)

            def bwd(box=box):
                if box.get("new"):
                    H.del_word(v.conn, box["id"])
            self.run_action("новое слово", fwd, bwd)
        v.draft_items.clear()
        v.draft_words.clear()
        v.move(0)
        v.flash("сохранено: %d" % n)

    def key_quiz(self, ch, name):
        v = self.view
        if name == "Escape":
            v.mode = "normal"
        elif name == "space" or ch == " ":
            v.revealed = True
        elif ch in ("y", "n") and v.quiz and v.revealed:
            self.do_button("yes" if ch == "y" else "no")

    def key_normal(self, ch, ctrl, name, shift):
        v = self.view
        now = time.monotonic()
        pend = self.pending if now - self.pending_t < 1.0 else ""
        self.pending = ""
        if ctrl and ch == "r":
            self.do_redo()
            return
        if name in ("q", "Escape") or ch == "q":
            self.close()
            return
        if name == "Tab" or (shift and ch in ("h", "l")):
            v.tab = "words" if v.tab == "items" else "items"
            v.confirm_delete = None
            self.set_title(self.tab_title())
            self.resize_to_min()
            return
        if ch == "j":
            v.move(1)
            return
        if ch == "k":
            v.move(-1)
            return
        if ch == "u":
            self.do_undo()
            return
        if ch in ("i", "a"):
            self.start_new()
            return
        if ch == "e":
            self.start_edit()
            return
        if ch == "y":
            self.copy_current()
            return
        if ch == "p":
            self.paste_new()
            return
        if ch == "z" and v.tab == "words":
            self.start_quiz()
            return
        if v.tab == "items" and ch == "v":
            self.toggle_view()
            return
        if v.tab == "items" and ch in ("1", "2", "3"):
            self.act_prio({"1": 2, "2": 1, "3": 0}[ch])
            return
        rows = v.rows()
        kind, d = v.current(rows)
        if ch == "d" and kind in ("item", "word"):
            self.act_delete_keyboard()
            return
        if kind == "item":
            if ch == "x":
                self.act_done()
            elif ch == "s" and not shift:
                self.act_snooze(secs=3600, label="+1ч")
            elif ch == "s" and shift:
                self.act_snooze_tomorrow()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        toggle = "--toggle" in args
        args = [a for a in args if a != "--toggle"]
        tab = "words" if "dict" in args else "items"
        # --toggle (как в Discipline): окно открыто и в фокусе — закрыть;
        # открыто, но под другими окнами — поднять; закрыто — открыть.
        if toggle and self.win is not None and self.win.is_active():
            self.win.close()
            return 0
        if self.win is None:
            self.win = HubWindow(self, tab)
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            if tab == "words":
                sel = selection()
                if sel and len(sel) < 200:
                    self.win.view.mode, self.win.view.buf = "text", sel.replace("\n", " ") + " = "
                    self.win.view.text_new = True
            self.win.show_all()
        else:
            self.win.view.reload_style()
            self.win.set_tab(tab)
            self.win.redraw()
        self.win.present()
        return 0


def shot(path, tab="items", sel=0, mode="normal", style=None, w=0, h=0, view=None,
         field="title", fdate="", ftime="", fprio=0):
    v = View()
    if view:
        v.view_mode = view
    v.field, v.f_date, v.f_time, v.f_prio = field, str(fdate), str(ftime), int(fprio)
    if style:
        v.style, v.c = style, colors(style)
    v.tab, v.mode = tab, mode
    v.sel[tab] = sel
    v.text_target = sel
    if mode == "text":
        v.buf = "пример"
        v.text_new = True
    ww, hh = max(W, w or W), max(v.height_min(), h or 480)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, hh)
    cr = cairo.Context(surf)
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    v.draw(cr, ww, hh)
    surf.write_to_png(path)
    return ww, hh


def main():
    if "--check" in sys.argv:
        v = View()
        v.draw(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 10, 10)), 10, 10)
        return
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        kw = {}
        for a in sys.argv[3:]:
            k, _, val = a.partition("=")
            kw[k] = int(val) if val.isdigit() else val
        print(shot(sys.argv[2], **kw))
        return
    GLib.set_prgname(APP_ID)
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
