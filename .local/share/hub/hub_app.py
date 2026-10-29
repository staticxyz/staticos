#!/usr/bin/env python3
"""hub_app — окно напоминаний и словаря, в стиле Clocker (cairo, рамка skeet/beta/default,
цвета из обоев, управление как в nvim по keycode; вид общий с routine_app.py, код свой —
Clocker тянет будильник и фокус, hub ничего этого не знает).

    hub_app.py            «Лучше вчера» (growth.py, 28.10.2026) — первая вкладка
    hub_app.py items      напоминания            hub_app.py dict   словарь (с выделенным текстом)

j/k — вниз/вверх · Tab / Shift+Tab, Shift+H/L — вкладка вперёд/назад · i/a, Ctrl+E — новая запись (ввод обычным
текстом; Enter, jj (только латиницей), Ctrl+E — сохранить, Esc — отмена, Ctrl+S — тоже сохранить) ·
x — выполнено · 1/2/3 — важность High/Mid/Default · v — вид (общий/списком) ·
Alt+j/k — переставить выше/ниже · Ctrl+H/L — срок на день назад/вперёд (и в окне ввода) ·
s — +1 час · Shift+S — на завтра 09:00 · dd — удалить (второе «d» подряд —
само подтверждение) · u — отменить последнее действие · Ctrl+R — повторить отменённое ·
z — повторение слов (Space — показать, y — знал, n — не знал) · q, Esc — закрыть.
Второй запуск поднимает уже открытое окно (GApplication).

При вводе новой (и в «e») Tab переводит на поля дата / время / важность / повтор — всё по
желанию (повтор по умолчанию «нет»; j/k — нет/день/неделя/месяц, нужен срок):
j/k — ±день / ±15 минут, h/l у времени — ±1 минута (Shift — неделя / час), можно и вписать: «завтра», «пт», «15.10»,
«1830». Без полей срок, как раньше, берётся из текста («купить хлеб завтра в 9»).
Только дата — задача «на день»: без времени, ниже задач со временем, напоминает в 9, 12, 15
и 18 (15.10.2026). Время без даты — нельзя.

Мышь: кнопки-блоки в ряд над строкой статуса (+ запись, Выполнено, +1ч, завтра, удалить,
повторить) — то же самое, что клавиши выше, просто кликом; «удалить» мышью требует
повторного клика («точно?»), так как у мыши нет естественного аналога «dd». Перетаскивание
— за пустое место окна (не за строку и не за кнопку), изменение размера — за край/правый
нижний уголок, как у Clocker.

    hub_app.py --shot F [tab=growth|items|words sel=N mode=normal|text|ginput gop=spend style=…]
                                                                                 PNG без окна
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
import growth as G  # noqa: E402
import title_strip  # noqa: E402

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
CARET = "\u2063"          # метка курсора в строке (невидимый разделитель), см. Painter.layout
BIG = 28
W = 460
PAD = 14
ROW_H = 22
DRAFT = "черновик"
SIZE_FILE = os.path.expanduser("~/.config/hub/app-size")
VIEW_FILE = os.path.expanduser("~/.config/hub/app-view")    # flat (общий) | list (списком)
PRIO_COL = {2: (0.91, 0.30, 0.30), 1: (0.95, 0.77, 0.22)}  # High — красный, Mid — жёлтый
HEAD_PRIO = {name: p for p, name in H.PRIO_NAMES.items()}
FIELDS = ("title", "date", "time", "prio", "repeat")
# поля под строкой ввода: имя, подсказка, ширина; не влезают в ширину — переносятся
FORM = (("date", "дата", 210), ("time", "время", 64), ("prio", None, 96), ("repeat", None, 96))
# 28.10.2026: «Лучше вчера» первой, потом напоминания (просьба: «чтобы она стояла первой»)
TABS = ("growth", "items", "words")
TAB_NAMES = {"growth": "Better", "items": "Reminders", "words": "Dictionary"}
TAB_TITLES = {"growth": "Better", "items": "Reminders", "words": "Dictionary"}

KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "


# ── цвета (как у Clocker / Настроек) ────────────────────────────────────────

_STACK = [None, False]


def stack_on():
    """Режим «стопка» включён? Тогда ни «×», ни своей рамки: их рисует stack_bars.py
    (21.10.2026, «дублируются кнопки», «двойная рамка»). Файл перечитывается при смене mtime."""
    p = os.path.expanduser("~/.config/hypr/state/stack-mode.json")
    try:
        m = os.stat(p).st_mtime
        if m != _STACK[0]:
            _STACK[0], _STACK[1] = m, '"active": true' in open(p).read()
    except OSError:
        _STACK[0], _STACK[1] = None, False
    return _STACK[1]


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

def present_unmin(win):
    """present() окна, свёрнутого в стопке, уводил niri на стол свёрнутых — окно появлялось
    «багованно» (22.10.2026). Такое окно возвращает stack_mode.py unmin (wm.raise_own)."""
    try:
        import wm
        if wm.raise_own():
            return
    except Exception:
        pass
    win.present()


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
        """Раскладка текста; метка курсора CARET из with_cursor вырезается — курсор
        рисует show() поверх, тонкой чертой (14.10.2026: символ «▏» занимал целую клетку
        пиксельного шрифта, и при ходьбе стрелками в тексте появлялся лишний пробел)."""
        lay = PangoCairo.create_layout(self.cr)
        k = s.find(CARET)
        if k >= 0:
            s = s[:k] + s[k + 1:]
        lay.caret = len(s[:k].encode("utf-8")) if k >= 0 else None
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
        self.show(lay, x, y, px)
        return w

    def show(self, lay, x, y, px):
        """Вывести раскладку; если в ней курсор — черта шириной px/6 у его позиции."""
        x, y = round(x), round(y)
        self.cr.move_to(x, y)
        PangoCairo.show_layout(self.cr, lay)
        if lay.caret is not None:
            r = lay.index_to_pos(lay.caret)
            cx, cy = x + r.x // Pango.SCALE, y + r.y // Pango.SCALE
            bw = max(1, round(px / 6))
            self.cr.rectangle(cx - bw, cy, bw, r.height // Pango.SCALE)   # в просвете перед буквой
            self.cr.fill()

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
        self.show(lay, x, y, px)
        return lay.get_pixel_size()[1]


def fld(d, k, default=None):
    """Поле и у sqlite3.Row, и у черновика-словаря (у Row нет .get)."""
    try:
        return d[k]
    except (KeyError, IndexError, TypeError):
        return default


def word_left(s, i):
    """Начало слова слева от позиции i (пробелы перед ним — тоже), как Ctrl+← в блокноте."""
    while i > 0 and s[i - 1].isspace():
        i -= 1
    while i > 0 and not s[i - 1].isspace():
        i -= 1
    return i


def word_right(s, i):
    while i < len(s) and s[i].isspace():
        i += 1
    while i < len(s) and not s[i].isspace():
        i += 1
    return i


def edit_line(s, cur, name, ctrl):
    """Курсор в строке ввода (13.10.2026, просьба: «не могу перемещаться курсором внутри
    текста»): ←/→, Home/End, Backspace/Delete; с Ctrl — по словам.
    → (строка, курсор) или None, если клавиша не про это."""
    cur = len(s) if cur is None else max(0, min(cur, len(s)))
    if name in ("Left", "KP_Left"):
        return s, (word_left(s, cur) if ctrl else max(0, cur - 1))
    if name in ("Right", "KP_Right"):
        return s, (word_right(s, cur) if ctrl else min(len(s), cur + 1))
    if name in ("Home", "KP_Home"):
        return s, 0
    if name in ("End", "KP_End"):
        return s, len(s)
    if name == "BackSpace":
        k = word_left(s, cur) if ctrl else max(0, cur - 1)
        return s[:k] + s[cur:], k
    if name in ("Delete", "KP_Delete"):
        k = word_right(s, cur) if ctrl else min(len(s), cur + 1)
        return s[:cur] + s[k:], cur
    return None


def with_cursor(s, cur):
    cur = len(s) if cur is None else max(0, min(cur, len(s)))
    return s[:cur] + CARET + s[cur:]


REL_DAYS = {0: "сегодня", 1: "завтра", 2: "послезавтра", -1: "вчера", -2: "позавчера"}


def plural_days(n):
    n = abs(n)
    if n % 10 == 1 and n % 100 != 11:
        return "%d день" % n
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "%d дня" % n
    return "%d дней" % n


def rel_day(d, today=None):
    """«сегодня», «послезавтра», «через 3 дня», «5 дней назад» (13.10.2026, пользователь)."""
    delta = (d - (today or dt.date.today())).days
    if delta in REL_DAYS:
        return REL_DAYS[delta]
    return "через " + plural_days(delta) if delta > 0 else plural_days(delta) + " назад"


def fmt_due(ts, allday=False):
    """Срок в списке: сколько дней, потом дата, потом время — «через 3 дня 16.10 21:00».
    «Только дата» — без времени."""
    t = dt.datetime.fromtimestamp(ts)
    day = t.strftime("%d.%m") + ("" if t.year == dt.date.today().year else ".%02d" % (t.year % 100))
    return ("%s %s %s" % (rel_day(t.date()), day, "" if allday else t.strftime("%H:%M"))).strip()


TIME_WORDS = re.compile(r"\d{1,2}[:.]\d{2}|\bв\s*\d{1,2}\b|утр|вечер|дн[её]м|ноч|час|мин", re.I)


GAP = 5            # зазор между синей чертой выбора и квадратом (13.10.2026, пользователь)


def order_open(rows):
    """Порядок открытых записей. Ручной порядок Alt+j/k главнее всего (14.10.2026, просьба:
    «ручная сортировка должна обходить любые ограничения»): записи с pos — строго по нему.
    Записи без pos (новые, ещё не переставленные) встают по правилу 13.10.2026: со сроком —
    сразу за последней записью со сроком, без срока — в конец; между собой — по номеру."""
    out = sorted((r for r in rows if r["pos"] is not None), key=lambda r: (r["pos"], r["id"]))
    for r in sorted((r for r in rows if r["pos"] is None), key=lambda r: (not r["due"], r["id"])):
        if r["due"]:
            out.insert(max((n + 1 for n, x in enumerate(out) if x["due"]), default=0), r)
        else:
            out.append(r)
    return out


DOW_WORDS = (("пн", "пон", "mon"), ("вт", "втор", "tue"), ("ср", "сре", "wed"), ("чт", "чет", "thu"),
             ("пт", "пят", "fri"), ("сб", "суб", "sat"), ("вс", "вос", "sun"))


def parse_date(s, today=None):
    """«15.10», «15.10.26», «15», «завтра», «пт», «+3», «15.10 ср» -> date | None."""
    today = today or dt.date.today()
    s = re.sub(r"\s+[a-zа-яё]{2}$", "", s.strip().lower().replace(",", "."))
    if not s:
        return None
    rel = {"сегодня": 0, "today": 0, "завтра": 1, "tomorrow": 1, "послезавтра": 2,
           "вчера": -1, "yesterday": -1, "позавчера": -2}
    s = re.sub(r"^(сегодня|завтра|послезавтра|вчера|позавчера|через \d+ д\w*|\d+ д\w* назад)\s+(?=\d)",
               "", s)                              # «сегодня 13.10» — как показано в поле
    if s in rel:
        return today + dt.timedelta(days=rel[s])
    m = re.fullmatch(r"([+-])(\d{1,3})", s)
    if m:
        return today + dt.timedelta(days=int(m.group(2)) * (1 if m.group(1) == "+" else -1))
    m = re.fullmatch(r"через (\d{1,3})(?: д\w*)?", s)
    if m:
        return today + dt.timedelta(days=int(m.group(1)))
    m = re.fullmatch(r"(\d{1,3}) д\w* назад", s)
    if m:
        return today - dt.timedelta(days=int(m.group(1)))
    for i, words in enumerate(DOW_WORDS):
        if any(s.startswith(w) for w in words):
            return today + dt.timedelta(days=(i - today.weekday()) % 7 or 7)
    try:
        m = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})(?:[./-](\d{2}|\d{4}))?", s)
        if m:
            y = int(m.group(3)) if m.group(3) else today.year
            d = dt.date(y + 2000 if y < 100 else y, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and d < today - dt.timedelta(days=183):
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
    """Поля «дата» и «время» -> (True, due|None) или (False, «дата»|«время»|«без даты»).
    15.10.2026, просьба: время без даты — нельзя; только дата — задача «на день» (allday):
    срок 09:00 того дня, время не показывается, напоминает в 9, 12, 15 и 18 (hubd)."""
    fdate, ftime = fdate.strip(), ftime.strip()
    if not fdate and not ftime:
        return True, None
    if not fdate:
        return False, "без даты"
    d = parse_date(fdate)
    if d is None:
        return False, "дата"
    t = parse_time(ftime) if ftime else None
    if ftime and t is None:
        return False, "время"
    return True, int(dt.datetime.combine(d, dt.time(*(t or (9, 0)))).timestamp())


def fields_allday(fdate, ftime):
    """Только дата, без времени — задача «на день»."""
    return bool(fdate.strip()) and not ftime.strip()


def fields_err(v, err):
    """Ошибка полей: курсор — в нужное поле, внизу — что не так."""
    v.field = "time" if err == "время" else "date"
    v.flash("к времени нужна дата" if err == "без даты" else "не разобрано поле «%s»" % err)


def fmt_done(ts):
    """Когда выполнено: «13.10 14:32»."""
    return dt.datetime.fromtimestamp(ts).strftime("%d.%m %H:%M") if ts else ""


class View:
    """Данные и раскладка — без GTK, чтобы --shot рисовал без окна."""

    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.active = True
        self.maxed = False          # развёрнуто — значок «вернуть» на полосе заголовка
        self.tab = "growth"
        self.sel = {"growth": 0, "items": 0, "words": 0}
        self.scroll = {"growth": 0, "items": 0, "words": 0}
        self.mode = "normal"            # normal | text | quiz | ginput (ввод во вкладке growth)
        self.g_op = ""                  # что вводится в ginput: wake | spend | lift | apply | hr
        self.g_chart = None             # «Лучше вчера»: график строки за 7 дней (l — войти, h — назад)
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
        self.field = "title"            # поле ввода: title | date | time | prio | repeat (Tab)
        self.f_date, self.f_time, self.f_prio = "", "", 0
        self.f_repeat = ""              # повтор: "" | daily | weekly | monthly (H.REPEATS)
        self.edit_orig = ("", "")       # дата/время до правки — менялись ли
        self.cur = None                 # курсор в тексте (None — в конце)
        self.f_typing = False           # поле дата/время: False — j/k/h/l, True — ввод руками
        self.f_cur = None
        self.f_backup = ""
        self.free_scroll = False        # список прокручен полосой — выбор может быть за краем
        self.sb = None                  # полоса прокрутки: (y0, высота, высоты строк)
        self.page_rows = 10
        self.view_mode = "list" if read(VIEW_FILE) == "list" else "flat"
        self.conn = H.connect()

    def reload_style(self):
        self.style = style_name()
        self.c = colors(self.style)

    def flash(self, text):
        self.msg, self.msg_until = text, time.monotonic() + 3

    # ── данные ──
    def rows(self):
        if self.tab == "growth":
            return G.rows(self)
        out = []
        if self.tab == "items":
            opened = order_open(H.items(self.conn, None, "open"))
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
        self.free_scroll = False
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
        # сверху полоса заголовка как у Настроек (title_strip, 29.10.2026); в стопке её рисует stack_bars
        y = f + (0 if stack_on() else title_strip.TITLE_H) + 2 + 10
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
        if not stack_on():
            self.hits += title_strip.draw(cr, self.style, f, f, w - 2 * f, "\U000f009a", "Hub",
                                          self.hover, self.maxed, self.active,
                                          r=0 if self.c["frame"] == "skeet" else 9)
        x0, x1 = PAD + f, w - PAD - f
        L = self.layout_y(h)
        self.draw_header(p, x0, x1, L["header"])
        if self.mode == "quiz":
            self.draw_quiz(p, x0, x1, L["body_top"], L["body_bottom"])
        elif self.tab == "growth":
            G.draw(self, p, x0, x1, L["body_top"], L["body_bottom"])
        else:
            self.draw_list(p, x0, x1, L["body_top"], L["body_bottom"])
        self.draw_buttons_row(p, x0, x1, L["buttons"])
        self.draw_footer(p, x0, x1, L["footer"])

    def draw_frame(self, p, w, h):
        c, cr = self.c, p.cr
        if stack_on():
            # В стопке рамку окна рисует stack_bars.py — своя была бы второй, внутри
            # (21.10.2026, просьба: «двойную рамку в discipline»). Только фон.
            p.rect(0, 0, w, h, c["bg"])
            if c["frame"] == "skeet":
                p.rgb(c["dot"])
                for yy in range(2, h - 2, 4):
                    for xx in range(2 + (yy // 4) % 2 * 2, w - 2, 4):
                        cr.rectangle(xx, yy, 1, 1)
                cr.fill()
            return
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
            on_col = c["acc_l"] if self.active else c["text"]
            col = on_col if on else (c["text"] if hov else c["dim"])
            G.pix(p, x, y + 2, G.ICONS["tab_" + t], col, 1)
            w = 14 + p.text(x + 14, y, label, col)
            if on:
                p.rect(x, y + 17, w, 2, c["acc"] if self.active else c["line"])
            self.hits.append(((x - 4, y - 6, w + 8, 26), ("tab", t)))
            x += w + 20
        if self.tab == "items":                 # вид: общий / списком (клик или v)
            label = "вид: " + ("списком" if self.view_mode == "list" else "общий")
            hov = self.hover == ("view",)
            vw = p.text(x1, y, label, c["text"] if hov else c["faint"], align="r")
            self.hits.append(((x1 - 4 - vw, y - 4, vw + 8, 20), ("view",)))

    def row_bg(self, p, x0, x1, y, sel, key, h=ROW_H):
        c = self.c
        if sel:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"])
            p.rect(x0 + 1, y, 2, h, c["acc"])
        elif self.hover == key:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"], 0.5)
        self.hits.append(((x0, y, x1 - x0, h), key))

    def edit_prefix(self):
        """Подпись перед вводом — с учётом двух полей у items."""
        if self.editing_id is not None:
            return ""
        if self.tab == "items":
            if self.text_stage == "when":
                return self.buf2 + " · когда: "
            return "новая: "
        return "слово = перевод: "

    def edit_text(self, word=False):
        buf = with_cursor(self.buf, self.cur) if (self.field == "title" or self.tab != "items") \
            else self.buf
        return buf if word else self.edit_prefix() + buf

    def dot_w(self, d):
        """Место под точку важности справа (только в общем виде)."""
        return 14 if self.view_mode == "flat" and (fld(d, "prio", 0) or 0) > 0 else 0

    @staticmethod
    def form_places(x, x1):
        """[(имя, подсказка, x, номер строки, ширина)] — поля в ряд, лишнее на следующей строке
        (четыре в ширину 460 не влезают: «повтор» уходит вниз, 14.10.2026)."""
        out, cx, row = [], x, 0
        for name, ph, w in FORM:
            if cx > x and cx + w > x1:
                cx, row = x, row + 1
            out.append((name, ph, cx, row, w))
            cx += w + 8
        return out

    def form_h(self, x, x1):
        return ROW_H * (1 + max(r for *_a, r, _w in self.form_places(x, x1)))

    def draw_form(self, p, x, y, x1):
        """Поля под вводом: дата · время · важность · повтор (Tab, клик)."""
        c = self.c
        for name, ph, x, row, w in self.form_places(x, x1):
            by, bh = y + 1 + row * ROW_H, ROW_H - 4
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
            elif name == "repeat":
                rp = self.f_repeat
                p.text(x + 6, ty, "↻ " + H.REPEAT_NAMES[rp],
                       (c["acc_l"] if rp else c["text"]) if on else (c["text"] if rp else c["faint"]))
            else:
                val = self.f_date if name == "date" else self.f_time
                if not val:
                    shown, col = ph, c["faint"]
                else:
                    if name == "date":
                        d = parse_date(val)
                        shown = rel_day(d) + " " + fmt_date(d) if (d and not (on and self.f_typing)) else val
                    else:
                        t = parse_time(val)
                        shown = "%02d:%02d" % t if (t and not (on and self.f_typing)) else val
                    col = c["text"] if (parse_date(val) if name == "date" else parse_time(val)) \
                        else c["err"]
                if on and self.f_typing:                 # ввод руками — с курсором
                    shown = with_cursor(val or "", self.f_cur)
                    col = c["acc_l"]
                elif on and val:
                    col = c["acc_l"] if col != c["err"] else col
                p.text(x + 6, ty, shown, col, maxw=w - 10)
            self.hits.append(((x, by, w, bh), ("field", name)))

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
        self.page_rows = max(2, avail // ROW_H)
        max_off = 0
        while max_off < len(rows) - 1 and sum(hs[max_off:]) > avail:
            max_off += 1
        if self.free_scroll and not editing:     # тянут полосу — выбор может уйти за край
            off = max(0, min(self.scroll[self.tab], max_off))
        else:
            # заголовки раздела над выбранной строкой — тоже на экран: после прокрутки вниз и
            # обратно «High» над первой записью оставался скрытым (13.10.2026)
            top = sel
            while top > 0 and rows[top - 1][0] == "head":
                top -= 1
            off = min(self.scroll[self.tab], top)
            while off < sel and sum(hs[off:sel + 1]) > avail:
                off += 1
            while off > 0 and sum(hs[off - 1:]) <= avail:
                off -= 1
        self.scroll[self.tab] = off
        self.sb = None
        total = sum(hs)
        if total > avail:                        # полоса прокрутки — тонкая, справа от списка
            c0 = sum(hs[:off])
            th = max(18, avail * avail / total)
            ty = y0 + (avail - th) * c0 / max(1, total - avail)
            sx = x1 + 5
            p.rect(sx, y0, 3, avail, c["line_soft"])
            hov = self.hover == ("sb",) or getattr(self, "sb_drag", False)
            p.rect(sx, ty, 3, min(th, y0 + avail - ty), c["acc"] if hov else c["line"])
            self.sb = (y0, avail, hs)
            self.hits.append(((x1 + 1, y0, 12, avail), ("sb",)))
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
            h = max(ROW_H, p.measure_wrap(disp, maxw=x1 - x0 - 24 - GAP) + 6)
            return h + (self.form_h(x0 + 14 + GAP, x1) if self.tab == "items" else 0)
        if kind == "item":
            main, due = self.item_parts(d)
            dw = (p.text_w(due) + 12 if due else 0) + self.dot_w(d)
            return max(ROW_H, p.measure_wrap(main, maxw=x1 - x0 - 20 - GAP - dw) + 6)
        text = ("✎ " if fld(d, "_draft") else "") + "%s — %s" % (d["term"], d["translation"])
        return max(ROW_H, p.measure_wrap(text, maxw=x1 - x0 - 20 - GAP) + 6)

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
            if kind == "new":
                disp = self.edit_text()
                tw = x1 - x0 - 24 - GAP
                tb = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                bh = tb + (self.form_h(x0 + 14 + GAP, x1) if self.tab == "items" else 0)
                self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                self.icon_box(p, x0 + 1 + GAP, y + (ROW_H - 9) / 2, 9, c["acc_l"], filled=False)
                p.text_wrap(x0 + 14 + GAP, y + 3, disp, c["acc_l"], maxw=tw)
                if self.tab == "items":
                    self.draw_form(p, x0 + 14 + GAP, y + tb, x1)
                y += bh
                continue
            elif kind == "item":
                draft = bool(fld(d, "_draft"))
                done = fld(d, "status") == "done"
                over = not done and H.overdue(d)
                if draft:
                    col = c["acc_l"]
                elif done:
                    col = c["faint"]
                else:
                    col = c["err"] if over else (c["acc_l"] if is_sel else c["text"])
                main, due = self.item_parts(d)
                if is_edit:
                    disp = self.edit_text()
                    tw = x1 - x0 - 24 - GAP
                    tb = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                    bh = tb + self.form_h(x0 + 14 + GAP, x1)
                    self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                    self.icon_box(p, x0 + 1 + GAP, y + (ROW_H - 9) / 2, 9, c["err"] if over else c["dim"], filled=False)
                    p.text_wrap(x0 + 14 + GAP, y + 3, disp, c["acc_l"], maxw=tw)
                    self.draw_form(p, x0 + 14 + GAP, y + tb, x1)
                    y += bh
                    continue
                dot = self.dot_w(d)
                dw = (p.text_w(due) + 12 if due else 0) + dot
                tw = x1 - x0 - 20 - GAP - dw
                bh = max(ROW_H, p.measure_wrap(main, maxw=tw) + 6)
                self.row_bg(p, x0, x1, y, is_sel, ("row", i), h=bh)
                ty = y + (ROW_H - 16) / 2 + 1
                self.icon_box(p, x0 + 1 + GAP, y + (ROW_H - 9) / 2, 9,
                              c["acc_l"] if draft else (c["err"] if over else c["dim"]), filled=done)
                p.text_wrap(x0 + 14 + GAP, y + 3, main, col, maxw=tw)
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
                    disp = self.edit_text(word=True)
                    tw = x1 - x0 - 24 - GAP
                    bh = max(ROW_H, p.measure_wrap(disp, maxw=tw) + 6)
                    self.row_bg(p, x0, x1, y, True, ("row", i), h=bh)
                    self.icon_dot(p, x0 + 5 + GAP, y + ROW_H / 2, c["acc_l"])
                    p.text_wrap(x0 + 14 + GAP, y + 3, disp, c["acc_l"], maxw=tw)
                    y += bh
                    continue
                tw = x1 - x0 - 20 - GAP
                bh = max(ROW_H, p.measure_wrap(text, maxw=tw) + 6)
                self.row_bg(p, x0, x1, y, is_sel, ("row", i), h=bh)
                self.icon_dot(p, x0 + 5 + GAP, y + ROW_H / 2, c["acc_l"] if (is_sel or draft) else c["faint"])
                p.text_wrap(x0 + 14 + GAP, y + 3, text, col, maxw=tw)
                y += bh
                continue
            y += ROW_H

    def item_parts(self, d):
        """(текст, срок) для строки списка — без «· #29», как в обычных списках задач."""
        main = ("✎ " if fld(d, "_draft") else "") + d["text"] + (" ↻" if d["repeat"] else "")
        if fld(d, "status") == "done":           # выполненная — когда (дата и время)
            return main, fmt_done(fld(d, "done_at"))
        due = fmt_due(d["due"], H.is_allday(d)) if d["due"] else ""
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
        """Полноразмерная кнопка — как в Clocker (button())."""
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
        if self.tab == "growth":
            G.buttons(self, p, x0, x1, y)
            return
        if self.mode == "text":
            save_label = "сохранить" if self.editing_id is not None else "добавить"
            mid = []
            if self.tab == "items":              # мышью: поле, шаг, ввод руками (13.10.2026)
                if self.field == "title":
                    mid = [("дата", ("btn", "f_date")), ("время", ("btn", "f_time")),
                           ("важность", ("btn", "f_prio")), ("повтор", ("btn", "f_repeat"))]
                elif self.field == "repeat":
                    mid = [(H.REPEAT_NAMES[r], ("btn", "rep:" + r), r == self.f_repeat)
                           for r in H.REPEATS]
                elif self.field == "prio":
                    mid = [("ниже", ("btn", "fminus")), ("выше", ("btn", "fplus"))]
                else:
                    unit = "день" if self.field == "date" else "15 мин"
                    mid = [("− " + unit, ("btn", "fminus")), ("+ " + unit, ("btn", "fplus")),
                           ("готово" if self.f_typing else "ввести", ("btn", "ftype"))]
            self.buttons(p, x0, x1, y, [("отмена", ("btn", "canceltext"))] + mid +
                         [(save_label, ("btn", "savetext"), True)])
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
        # повторяющееся (14.10.2026): «отметить» — срок на следующий раз, «закрыть цикл» — конец
        rep = kind == "item" and bool(fld(d, "repeat"))
        delete = ("точно?" if confirming else ("закрыть цикл" if rep else "удалить"), ("btn", "delete"))
        done_l = "Отметить" if rep else "Выполнено"
        if self.tab == "items":
            btns = [("+ запись", ("btn", "new"), not n)] + save
            if kind == "item" and draft:
                btns.append(delete)
            elif kind == "item" and fld(d, "status") == "done":
                btns += [("вернуть", ("btn", "done")), delete]
            elif kind == "item" and n:
                btns += [(done_l, ("btn", "done")), delete]
            elif kind == "item":
                btns += [(done_l, ("btn", "done")), ("+1ч", ("btn", "snooze1")),
                         ("завтра", ("btn", "snoozetomorrow")), delete]
        else:
            btns = [("+ слово", ("btn", "new"), not n)] + save
            if rows and not n:
                btns.append(("повторить", ("btn", "quiz")))
            if kind == "word":
                btns.append(delete)
        self.buttons(p, x0, x1, y, btns)

    FIELD_HINTS = {
        "title": "Enter · Tab — срок, важность, повтор · Esc",
        "date": "j/k h/l ±день, Shift ±неделя · e или / — вписать",
        "time": "j/k ±15 · h/l ±1 мин · Shift ±час · e",
        "prio": "j/k h/l или 1/2/3 · Enter — %s",
        "repeat": "j/k h/l — нет/день/неделя/месяц · Enter — %s",
        "typing": "«пт» «15.10» «+3» «1830» · Enter — готово · Esc",
    }
    HINTS = {
        "text": "Enter / jj — добавить в список · Esc — отмена",
        "quiz": "Space — показать · y знал · n не знал · Esc назад",
    }

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        badge = {"text": "INSERT", "ginput": "INSERT", "quiz": "QUIZ"}.get(self.mode, "NORMAL")
        bw = p.text_w(badge) + 10
        p.rect(x0, y - 1, bw, 16, c["field_l"])
        p.text(x0 + 5, y, badge, c["acc_l"])
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x0 + bw + 10, y, self.msg, c["text"], maxw=x1 - x0 - bw - 10)
        elif self.mode == "normal" and self.n_drafts():
            p.text(x0 + bw + 10, y, "не сохранено: %d · Ctrl+S — сохранить"
                   % self.n_drafts(), c["acc_l"], maxw=x1 - x0 - bw - 10)
        else:
            hint = G.hint(self) if self.tab == "growth" else self.HINTS.get(self.mode) or (
                "n новая · e правка · ^H ^L срок · 1-3 / h l важность · v вид · Alt+j/k порядок" if self.tab == "items"
                else "i/a новое · e ред. · z повторить · d удалить · y/p")
            if self.mode == "text" and self.tab == "items":
                hint = self.FIELD_HINTS["typing" if (self.f_typing and self.field in ("date", "time"))
                                        else self.field]
                if "%s" in hint:
                    hint = hint % ("сохранить" if self.editing_id is not None else "добавить")
            p.text(x0 + bw + 10, y, hint, c["faint"], maxw=x1 - x0 - bw - 10)


# ── окно ──────────────────────────────────────────────────────────────────────

class HubWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="growth"):
        super().__init__(application=app, title="Hub")
        self.view = View()
        self.view.text_target, self.view.text_new = -1, False
        self.view.tab = tab if tab in TABS else "growth"
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
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK
                             | Gdk.EventMask.BUTTON_RELEASE_MASK)
        self.view.sb_drag = False
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", lambda *_: self.set_hover(None))
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("delete-event", self.on_delete)
        self.close_armed = 0
        self.connect("notify::is-active", self.on_active)
        self.connect("window-state-event", self.on_wstate)
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
        return TAB_TITLES[self.view.tab]

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
        if self.view.maxed:                 # развёрнуто — не запоминать как свой размер
            return False
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

    def on_wstate(self, _w, ev):
        m = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED) \
            or title_strip.float_maxed(self)  # TILED не берём: при prefer-no-csd niri шлёт его всем окнам
        if m != self.view.maxed:
            self.view.maxed = m
            self.redraw()
        return False

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

    def sb_to(self, y):
        """Полоса прокрутки: строка списка под указателем — верхней видимой."""
        v = self.view
        if not v.sb:
            return
        y0, avail, hs = v.sb
        total = sum(hs)
        want = (y - y0) / max(1, avail) * total - avail / 2
        acc, off = 0, 0
        while off < len(hs) - 1 and acc + hs[off] <= want:
            acc += hs[off]
            off += 1
        v.scroll[v.tab] = off
        v.free_scroll = True
        self.redraw()

    def on_release(self, _w, ev):
        if self.view.sb_drag:
            self.view.sb_drag = False
            self.redraw()
        return True

    def on_motion(self, _w, ev):
        if self.view.sb_drag:
            self.sb_to(ev.y)
            return
        edge = self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else None)
        self.set_hover(None if edge else self.hit(ev.x, ev.y))

    def on_scroll(self, _w, ev):
        d = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction)
        if d:
            v = self.view
            key = self.hit(ev.x, ev.y)
            if v.mode == "text" and isinstance(key, tuple) and key[0] == "field":
                v.field, v.f_typing = key[1], False     # колесо над полем — шаг значения
                self.field_step(-d, bool(ev.state & Gdk.ModifierType.SHIFT_MASK))
            elif key == ("sb",) and v.sb and v.mode != "text":
                v.scroll[v.tab] = max(0, v.scroll[v.tab] + d * 3)
                v.free_scroll = True
            else:
                v.move(d)
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
        if key == "title":
            title_strip.on_title(self, ev)
            return True
        if key == "max":
            title_strip.toggle_max(self)
            return True
        double = ev.type == Gdk.EventType._2BUTTON_PRESS
        if key == ("sb",):
            v.sb_drag = True
            self.sb_to(ev.y)
            return True
        if double and isinstance(key, tuple):
            # двойной щелчок: по записи — правка, как Ctrl+E; по дате/времени — ввод руками
            if key[0] == "row" and v.mode == "normal":
                v.sel[v.tab] = key[1]
                kind, gk = G.current(v) if v.tab == "growth" else (None, None)
                if kind == "g":
                    # строка «Лучше вчера» — в график (29.10.2026, просьба: «по двойному щелчку
                    # заходить в инфографику»); дела быта — по-прежнему отметить
                    self.g_chart(gk)
                elif v.tab == "growth":
                    self.g_primary()
                else:
                    self.start_edit()
            elif key[0] == "gseg" and v.mode == "normal" and v.tab == "growth" and key[1] < len(G.METRICS):
                self.g_chart(G.METRICS[key[1]][0])          # двойной по отрезку сводки — тоже график
            elif key[0] == "field" and key[1] in ("date", "time") and v.mode == "text":
                v.field = key[1]
                self.field_typing(True)
            self.redraw()
            return True
        if key == "close":
            self.close()
        elif isinstance(key, tuple) and key[0] == "tab":
            v.tab, v.mode = key[1], "normal"
            v.confirm_delete = None
            self.set_title(self.tab_title())
            self.resize_to_min()
        elif isinstance(key, tuple) and key[0] == "row" and v.mode == "text":
            if key[1] == v.text_target:          # щелчок по тексту правки — снова к тексту
                self.field_typing(False)
                v.field = "title"
        elif isinstance(key, tuple) and key[0] == "row":
            if v.mode == "ginput" and key[1] != v.sel[v.tab]:
                v.mode = "normal"                   # щелчок по другой строке — ввод брошен
            v.sel[v.tab] = key[1]
            v.confirm_delete = None
        elif isinstance(key, tuple) and key[0] == "gseg":
            v.sel[v.tab], v.free_scroll = key[1], False     # щелчок по отрезку «Лучше вчера» — к его строке
            if v.g_chart and key[1] < len(G.METRICS):        # в графике — график этой строки
                v.g_chart = G.METRICS[key[1]][0]
        elif isinstance(key, tuple) and key[0] == "btn":
            self.do_button(key[1])
        elif key == ("view",):
            self.toggle_view()
        elif isinstance(key, tuple) and key[0] == "field" and v.mode == "text":
            if key[1] == "prio" and v.field == "prio":
                v.f_prio = (v.f_prio + 1) % 3          # повторный клик — следующая важность
            if key[1] == "repeat" and v.field == "repeat":
                self.field_step(1, False, wrap=True)
            if key[1] != v.field:
                self.field_typing(False)
            v.field = key[1]
        self.redraw()
        return True

    # ── кнопки подвала — те же действия, что и клавиши в key_normal/key_quiz ──
    def do_button(self, action):
        v = self.view
        if action.startswith("g:"):
            self.g_do(action[2:])
            return
        if v.mode == "text":
            if action in ("f_date", "f_time", "f_prio", "f_repeat"):
                self.field_typing(False)
                v.field = action[2:]
                return
            if action.startswith("rep:"):
                v.f_repeat = action[4:]
                return
            if action in ("fminus", "fplus"):
                self.field_typing(False)
                self.field_step(1 if action == "fplus" else -1, False)
                return
            if action == "ftype":
                self.field_typing(not v.f_typing)
                return
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

    # ── отмена/повтор — стек (метка, вперёд, назад), как у Clocker, но
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
        iid, prev_due, prev_allday = d["id"], d["due"], H.is_allday(d)
        if d["status"] == "done":
            self.run_action("вернуть", lambda: H.reopen(v.conn, iid, "pc"),
                            lambda: H.done(v.conn, iid, "pc"))
            v.flash("вернул в список")
            return
        had_repeat = bool(d["repeat"]) and bool(prev_due)
        prev_base = H.rbase(d)

        def fwd():
            H.done(v.conn, iid, "pc")

        def bwd():
            if had_repeat:
                H.edit(v.conn, iid, due=prev_due, allday=prev_allday)
                H._apply(v.conn, iid, None, rbase=prev_base)     # «отложено» не сдвигает расписание
            else:
                H.reopen(v.conn, iid, "pc")
        self.run_action("выполнено", fwd, bwd)

    def act_snooze(self, secs=None, until=None, label="+1ч"):
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item" or fld(d, "_draft") or d["status"] != "open":
            return
        iid, prev_due, prev_allday = d["id"], d["due"], H.is_allday(d)

        def fwd():
            H.snooze(v.conn, iid, secs, until, source="pc")

        def bwd():
            H.edit(v.conn, iid, due=prev_due, allday=prev_allday)
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
        v.cur, v.f_typing, v.f_cur = None, False, None
        v.f_date = v.f_time = ""
        v.f_prio = (fld(d, "prio", 0) or 0) if d is not None else 0
        v.f_repeat = (fld(d, "repeat", "") or "") if d is not None else ""
        if d is not None and d["due"]:
            t = dt.datetime.fromtimestamp(d["due"])
            v.f_date, v.f_time = fmt_date(t.date()), "" if H.is_allday(d) else t.strftime("%H:%M")
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

    def act_prio_step(self, step):
        """h/l — важность на шаг: Default ← Mid ← High (h — ниже, l — выше)."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item":
            return
        pr = max(0, min(2, (fld(d, "prio", 0) or 0) + step))
        if pr == (fld(d, "prio", 0) or 0):
            v.flash("важность уже " + H.PRIO_NAMES[pr])
            return
        self.act_prio(pr)

    def act_shift_day(self, step):
        """Ctrl+H/Ctrl+L — срок текущей записи на день назад/вперёд, время то же; без срока —
        вчера/завтра «на день» (23.10.2026, просьба: «ctrl+h вчера, ctrl+l завтра»). Отмена — u."""
        v = self.view
        kind, d = v.current(v.rows())
        if kind != "item" or d["status"] != "open":
            return
        old, old_allday = d["due"], H.is_allday(d)
        if old:
            new, allday = int((dt.datetime.fromtimestamp(old) + dt.timedelta(days=step)).timestamp()), old_allday
        else:
            day = dt.date.today() + dt.timedelta(days=step)
            new, allday = int(dt.datetime.combine(day, dt.time(9, 0)).timestamp()), True
        if fld(d, "_draft"):
            d["due"], d["allday"] = new, allday
        else:
            iid = d["id"]
            self.run_action("срок", lambda: H.edit(v.conn, iid, due=new, allday=allday, source="pc"),
                            lambda: H.edit(v.conn, iid, due=old, allday=old_allday, source="pc"))
            self.select_item(iid)
        v.flash("срок: " + fmt_due(new, allday))

    def shift_form_date(self, step):
        """Ctrl+H/Ctrl+L в окне ввода — поле «дата» на день; пустое — от сегодня."""
        v = self.view
        d = parse_date(v.f_date) if v.f_date.strip() else None
        v.f_date = fmt_date((d or dt.date.today()) + dt.timedelta(days=step))

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
        opened = order_open(H.items(v.conn, None, "open"))
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
            v.cur = None
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
        if v.tab == "items" and iid is not None and (v.f_date, v.f_time) == v.edit_orig:
            text = self.due_from_text(iid, text)
        if v.tab == "items" and iid is not None:
            ok, due = fields_due(v.f_date, v.f_time)
            if not ok:
                fields_err(v, due)
                return
            allday = fields_allday(v.f_date, v.f_time)
            due_changed = (v.f_date, v.f_time) != v.edit_orig
            prio, repeat = v.f_prio, v.f_repeat
            old = H.get_item(v.conn, iid)
            if repeat and not (due if due_changed else (old and old["due"])):
                v.field = "date"
                v.flash("у повтора должен быть срок — дата или время")
                return
        kind, d = v.current(v.rows())
        self.cancel_text()
        if not text or iid is None:
            return
        if v.tab == "items":
            old = H.get_item(v.conn, iid)
            if old is None:
                return
            old_text, old_due, old_prio = old["text"], old["due"], old["prio"] or 0
            old_allday = H.is_allday(old)
            old_rep = old["repeat"] or ""

            def fwd():
                H.edit(v.conn, iid, text=text, due=due if due_changed else "keep", source="pc",
                       allday=allday)
                if prio != old_prio:
                    H.set_prio(v.conn, iid, prio, "pc")
                if repeat != old_rep:
                    H.set_repeat(v.conn, iid, repeat, "pc")

            def bwd():
                H.edit(v.conn, iid, text=old_text, due=old_due if due_changed else "keep", source="pc",
                       allday=old_allday)
                if prio != old_prio:
                    H.set_prio(v.conn, iid, old_prio, "pc")
                if repeat != old_rep:
                    H.set_repeat(v.conn, iid, old_rep, "pc")
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

    def due_from_text(self, iid, text):
        """Правка: вписали в текст «завтра», «пт», «в 18:30» — это срок, а не слова
        (13.10.2026: «дата просто вписалась как текст»). Разбирается только
        дописанное — в старом названии слово «сегодня» могло остаться нарочно. Поля
        дата/время, если их трогали, главнее (сюда тогда не заходим). Без явного
        времени остаётся прежнее время записи."""
        v = self.view
        old = H.get_item(v.conn, iid)
        old_text = (old["text"] if old else "") or ""
        if text.startswith(old_text):
            head, added = old_text, text[len(old_text):]
        elif old_text and H.parse_when(old_text)[1]:
            return text
        else:
            head, added = "", text
        if not added.strip():
            return text
        clean, tdue, _rep = H.parse_when(added)
        if not tdue:
            return text
        t = dt.datetime.fromtimestamp(tdue)
        notime = False
        if not TIME_WORDS.search(added):            # без явного времени — прежнее; не было — «на день»
            if old and old["due"] and not H.is_allday(old):
                t = dt.datetime.combine(t.date(), dt.datetime.fromtimestamp(old["due"]).time())
            else:
                notime = True
        v.f_date, v.f_time = fmt_date(t.date()), "" if notime else t.strftime("%H:%M")
        v.flash("срок из текста: " + fmt_due(int(t.timestamp()), notime))
        return (head + " " + clean).strip() if head else (clean or text)

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
        v.cur, v.f_typing = None, False
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
        self.set_title(self.tab_title())

    # ── «Лучше вчера» (growth.py, 28.10.2026): действия с отменой через u / Ctrl+R ──
    G_LABEL = {"cig": "сигарета", "spend": "трата", "lift": "тренировка", "speech": "речь"}

    def g_push(self, label, forward, backward):
        """Действие уже сделано — только в стек отмены (run_action выполнил бы его ещё раз)."""
        self.undo_stack.append((label, forward, backward))
        del self.undo_stack[:-50]
        self.redo_stack.clear()

    def g_primary(self):
        kind, key = G.current(self.view)
        if kind == "chore":
            self.g_do("chore")
        elif G.PRIMARY.get(key):
            self.g_do(G.PRIMARY[key])
        elif key == "chores":
            self.g_do("tochores")

    def g_do(self, act):
        v, c = self.view, self.view.conn
        kind, key = G.current(v)
        if act == "refresh":
            G.invalidate()
            v.flash("обновлено")
        elif act == "cancel":
            v.mode, v.buf, v.cur = "normal", "", None
        elif act == "submit":
            self.g_submit()
        elif act == "chart":
            self.g_chart(None)
        elif act == "tochores":
            v.sel["growth"] = next(i for i, r in enumerate(G.rows(v)) if r[0] == "chore")
        elif act.startswith("i:"):
            v.mode, v.g_op, v.buf, v.cur = "ginput", act[2:], "", None
        elif act.startswith("pomo"):
            task = act[5:] or "programming"
            st = G.pomo_state()
            busy = st.get("phase", "idle") != "idle" and not int(st.get("paused") or 0)
            if busy:
                v.flash("помидор уже идёт: %s" % (st.get("task") or st.get("phase")))
                return
            subprocess.Popen([os.path.expanduser("~/.local/bin/pomo"), "start", task],
                             start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            G.invalidate()
            v.flash("▶ помидор «%s»" % task)
        elif act == "chore" and kind == "chore":
            done, r = G.do_chore(c, key)
            label = G.CHORE_NAMES[key].lower()
            if done:
                self.g_push(label, lambda: G.put_back(c, r), lambda: G.remove(c, r["id"]))
            else:
                self.g_push("снято: " + label, lambda: G.remove(c, r["id"]), lambda: G.put_back(c, r))
            v.flash(("✓ " if done else "снято: ") + label)
        elif act.startswith("+"):
            k, box = act[1:], {}

            def fwd():
                box["id"] = G.add(c, k, 1)
            self.run_action(self.G_LABEL[k], fwd, lambda: G.remove(c, box["id"]))
            v.flash("✓ +1 " + self.G_LABEL[k])
        elif act.startswith("-"):
            rs = [r for r in (G.last_today(c, act[1:]),) if r]
            if not rs:
                v.flash("сегодня записей нет")
                return
            r = max(rs, key=lambda r: (r["ts"], r["id"]))
            label = "убрано: " + self.G_LABEL[r["kind"]]
            self.run_action(label, lambda: G.remove(c, r["id"]), lambda: G.put_back(c, r))
            v.flash(label)

    def g_submit(self):
        v, c = self.view, self.view.conn
        text = v.buf.strip()
        if not text:
            v.mode = "normal"
            return
        said, ids = G.do_text(c, v.g_op, text)
        if ids is None:
            v.flash(said)                      # не понял — ввод остаётся, можно поправить
            return
        rs = [G.get(c, i) for i in ids]

        def fwd():
            for r in rs:
                G.put_back(c, r)

        def bwd():
            for r in rs:
                G.remove(c, r["id"])
        self.g_push(said.lstrip("✓ "), fwd, bwd)
        v.mode, v.buf, v.cur = "normal", "", None
        v.flash(said)

    def g_chart(self, key):
        """График строки вместо списка (29.10.2026, просьба: «бинды h/l — заходить в график и
        возвращаться к списку»). key=None — назад к списку, выбор встаёт на эту строку."""
        v = self.view
        if key is None and v.g_chart:
            v.sel["growth"] = G.rows(v).index(("g", v.g_chart))
            v.free_scroll = False
        v.g_chart = key
        self.resize_to_min()

    def g_chart_key(self, ch, name):
        """Клавиши в графике: h/Esc — к списку, j/k — соседняя строка, q — закрыть окно."""
        v = self.view
        if ch == "h" or name in ("Escape", "BackSpace"):
            self.g_chart(None)
        elif ch in ("j", "k"):
            keys = [k for k, _n in G.METRICS]
            i = keys.index(v.g_chart) + (1 if ch == "j" else -1)
            self.g_chart(keys[i % len(keys)])
        elif ch == "q":
            self.close()
        elif ch == "r":
            self.g_do("refresh")

    def g_key(self, ch, name):
        v = self.view
        kind, key = G.current(v)
        if ch == "l" and kind == "g":
            self.g_chart(key)
        elif name in ("Return", "KP_Enter", "space") or ch == " ":
            self.g_primary()
        elif ch in ("i", "a", "n", "e"):
            act = G.PRIMARY.get(key) or ""
            self.g_do(act) if act.startswith("i:") else self.g_primary()
        elif ch == "x" or ch == "-":
            if kind == "chore":
                self.g_do("chore")
            elif key in ("cig", "money", "lift", "speech"):
                self.g_do({"money": "-spend"}.get(key, "-" + key))
        elif ch == "=" and key == "cig":                 # «+» без Shift
            self.g_do("+cig")
        elif ch == "r":
            self.g_do("refresh")

    def g_input_key(self, ev, ch, name, ctrl):
        v = self.view
        if name == "Escape":
            self.g_do("cancel")
        elif name in ("Return", "KP_Enter"):
            self.g_submit()
        elif ctrl and ch == "u":
            v.buf, v.cur = "", None
        else:
            r = edit_line(v.buf, v.cur, name, ctrl)
            if r:
                v.buf, v.cur = r
                return
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u >= 32 and not ctrl:
                cur = len(v.buf) if v.cur is None else v.cur
                v.buf, v.cur = v.buf[:cur] + chr(u) + v.buf[cur:], cur + 1

    # ── клавиатура ──
    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""
        # ^E — правка ТЕКУЩЕЙ записи и обратно (13.10.2026, просьба: не создавать новую).
        # Новая запись — n / i / a.
        if v.mode == "ginput":
            self.g_input_key(ev, ch, name, ctrl)
            self.redraw()
            return True
        if ctrl and ch == "e" and v.mode != "quiz" and v.tab != "growth":
            if v.mode != "text":
                self.start_edit()
            elif v.editing_id is not None:
                self.finish_edit()
            else:
                self.submit_text()
            self.redraw()
            return True
        if ctrl and ch == "s" and v.tab != "growth":
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

    def field_step(self, step, big, wrap=False, fine=False):
        """Шаг поля: дата ±день (big — неделя), время ±15 мин (fine — ±1 мин, big — час),
        важность ±1, повтор — следующий/прошлый (wrap — по кругу, для клика).
        15.10.2026, просьба: у времени h/l — ±1 минута, j/k — ±15."""
        v = self.view
        if v.field == "repeat":
            k = H.REPEATS.index(v.f_repeat) + step
            v.f_repeat = H.REPEATS[k % len(H.REPEATS) if wrap else max(0, min(len(H.REPEATS) - 1, k))]
        elif v.field == "prio":
            v.f_prio = max(0, min(2, v.f_prio + step))
        elif v.field == "date":
            d = parse_date(v.f_date)
            d = d + dt.timedelta(days=step * (7 if big else 1)) if d else dt.date.today()
            v.f_date = fmt_date(d)
        elif v.field == "time":
            t = parse_time(v.f_time)
            if t:
                m = (t[0] * 60 + t[1] + step * (60 if big else 1 if fine else 15)) % (24 * 60)
            else:
                n = dt.datetime.now()
                m = (n.hour * 60 + n.minute + 15) // 15 * 15 % (24 * 60)
            v.f_time = "%02d:%02d" % divmod(m, 60)

    def field_typing(self, on, keep=True):
        """Дата/время: ввод руками (e, /, двойной щелчок) ↔ шаги j/k/h/l.
        keep=False — Esc: вернуть, что было до ввода."""
        v = self.view
        if on and v.field in ("date", "time") and not v.f_typing:
            v.f_backup = getattr(v, "f_" + v.field)
            v.f_cur = None
            v.f_typing = True
        elif not on and v.f_typing:
            if not keep:
                setattr(v, "f_" + v.field, v.f_backup)
            v.f_typing = False

    def key_field(self, ch, name, ev):
        """Поля дата/время/важность. Клавиши — по коду, в любой раскладке (13.10.2026:
        на русской j/k вписывались буквами): j/k h/l и стрелки — шаг, Shift — крупный;
        e или / — вписать руками, там курсор и Enter/Esc."""
        v = self.view
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        u = Gdk.keyval_to_unicode(ev.keyval)
        uc = chr(u) if u else ""
        if v.f_typing:
            attr = "f_" + v.field
            val = getattr(v, attr)
            r = edit_line(val, v.f_cur, name, ctrl)
            if r:
                setattr(v, attr, r[0])
                v.f_cur = r[1]
            elif uc and not ctrl and uc.isprintable() and len(val) < 24:
                k = len(val) if v.f_cur is None else v.f_cur
                setattr(v, attr, val[:k] + uc + val[k:])
                v.f_cur = k + 1
            return
        step = {"Up": 1, "Right": 1, "Down": -1, "Left": -1}.get(name) or \
            {"k": 1, "l": 1, "j": -1, "h": -1}.get(ch, 0)
        if step:
            self.field_step(step, shift, fine=name in ("Left", "Right") or ch in ("h", "l"))
        elif v.field == "prio":
            if ch in ("1", "2", "3"):
                v.f_prio = {"1": 2, "2": 1, "3": 0}[ch]
            elif ch == " ":
                v.f_prio = (v.f_prio + 1) % 3
        elif v.field == "repeat":
            if ch == " ":
                self.field_step(1, False, wrap=True)
            elif name in ("BackSpace", "Delete"):
                v.f_repeat = ""
        elif ch in ("e", "/"):
            self.field_typing(True)
        elif name in ("BackSpace", "Delete"):
            setattr(v, "f_" + v.field, "")           # без даты / без времени
        elif uc and (uc.isdigit() or uc in "+-"):    # цифра — сразу ввод заново
            setattr(v, "f_" + v.field, uc)
            v.f_backup, v.f_cur, v.f_typing = getattr(v, "f_" + v.field), None, True

    def key_text(self, ch, name, ev):
        v = self.view
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        if v.tab == "items" and v.f_typing and v.field in ("date", "time"):
            if name == "Escape":
                self.field_typing(False, keep=False)
                return
            if name in ("Return", "KP_Enter", "Tab", "ISO_Left_Tab"):
                val = getattr(v, "f_" + v.field).strip()
                if val and not (parse_date(val) if v.field == "date" else parse_time(val)):
                    v.flash("не разобрано: «%s» — например %s" % (
                        val, "«пт», «15.10», «+3»" if v.field == "date" else "«18:30», «1830», «9»"))
                    return
                if val:                               # к общему виду: «16.10 пт», «09:00»
                    setattr(v, "f_" + v.field, fmt_date(parse_date(val)) if v.field == "date"
                            else "%02d:%02d" % parse_time(val))
                self.field_typing(False)
                if name in ("Return", "KP_Enter"):
                    return
        if name == "Escape":
            self.cancel_text()
        elif name in ("Return", "KP_Enter"):
            if v.editing_id is not None:
                self.finish_edit()
            else:
                self.submit_text()
        elif v.tab == "items" and ctrl and ch in ("h", "l") and not v.f_typing:
            self.shift_form_date(1 if ch == "l" else -1)
        elif v.tab == "items" and name in ("Tab", "ISO_Left_Tab"):
            k = FIELDS.index(v.field) + (-1 if name == "ISO_Left_Tab" else 1)
            v.field = FIELDS[k % len(FIELDS)]
        elif v.tab == "items" and v.field != "title":
            self.key_field(ch, name, ev)
        elif edit_line(v.buf, v.cur, name, ctrl):     # курсор: ←/→ Home/End, Ctrl — по словам
            v.buf, v.cur = edit_line(v.buf, v.cur, name, ctrl)
            self.pending_jj = False
        else:
            u = Gdk.keyval_to_unicode(ev.keyval)
            if ctrl or not (u and len(v.buf) < 200 and chr(u).isprintable()):
                return
            k = len(v.buf) if v.cur is None else min(v.cur, len(v.buf))
            now = time.monotonic()
            # jj — только латиницей: «оо» в русской раскладке (вообще, кооператив) — просто
            # текст (14.10.2026, просьба: печатать «вообще» без пауз)
            if chr(u) == "j" and self.pending_jj and now - self.pending_t < 0.4 and k > 0:
                v.buf, v.cur = v.buf[:k - 1] + v.buf[k:], k - 1     # jj — первую j убрать
                if v.editing_id is not None:
                    self.finish_edit()
                else:
                    self.submit_text()
                return
            v.buf, v.cur = v.buf[:k] + chr(u) + v.buf[k:], k + 1
            self.pending_jj = chr(u) == "j"
            self.pending_t = now

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
            fields_err(v, fdue)
            return
        allday = fok and fdue is not None and fields_allday(v.f_date, v.f_time)
        prio, frep = v.f_prio, v.f_repeat
        if text and v.tab == "items":
            lname, body = H.split_list(text)
            clean, due, repeat = H.parse_when(body)
            if fdue is not None:                       # поля дата/время главнее текста
                due = fdue
            repeat = frep or repeat                    # поле «повтор» главнее «каждый …» в тексте
            if repeat and not due:                     # без срока повтор не сработает ни разу
                v.field = "date"
                v.flash("у повтора должен быть срок — дата или время")
                return
        self.cancel_text()
        if not text:
            return
        if v.tab == "items":
            d = {"id": v.draft_seq, "text": clean or body.strip(), "due": due, "repeat": repeat,
                 "status": "open", "kind": "task", "list": lname, "_draft": True, "_raw": text,
                 "prio": prio, "allday": allday}
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
                                       prio=d.get("prio", 0), allday=d.get("allday", False))

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
        if ctrl and ch in ("d", "u"):                 # как в nvim: полстраницы вниз/вверх
            v.move((1 if ch == "d" else -1) * max(1, v.page_rows // 2))
            return
        if ctrl and ch in ("h", "l") and v.tab == "items":
            self.act_shift_day(1 if ch == "l" else -1)
            return
        if ctrl:
            return
        if v.tab == "growth" and v.g_chart and not shift:
            self.g_chart_key(ch, name)
            return
        if ch == "g" and shift:                        # G — в самый низ
            v.move(10 ** 6)
            return
        if ch == "g":                                  # gg — наверх
            if pend == "g":
                v.move(-10 ** 6)
            else:
                self.pending, self.pending_t = "g", now
            return
        if name in ("q", "Escape") or ch == "q":
            self.close()
            return
        # 28.10.2026: три вкладки по кругу; Shift+Tab (ISO_Left_Tab) — назад, раньше не ловился
        if name in ("Tab", "ISO_Left_Tab") or (shift and ch in ("h", "l")):
            back = name == "ISO_Left_Tab" or ch == "h"
            v.tab = TABS[(TABS.index(v.tab) + (-1 if back else 1)) % len(TABS)]
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
        if v.tab == "growth":
            self.g_key(ch, name)
            return
        if ch in ("i", "a", "n"):                  # n — новая запись (13.10.2026)
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
        if v.tab == "items" and ch in ("v", "f"):     # f — то же, что v (13.10.2026)
            self.toggle_view()
            return
        if v.tab == "items" and ch in ("h", "l") and not shift:
            self.act_prio_step(1 if ch == "l" else -1)   # h/l — важность ниже/выше
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
        # без аргумента — «Лучше вчера», а у уже открытого окна вкладка остаётся как была
        tab = "words" if "dict" in args else "items" if "items" in args else \
            "growth" if "growth" in args else None
        # --toggle (как в Clocker): окно открыто и в фокусе — закрыть;
        # открыто, но под другими окнами — поднять; закрыто — открыть.
        if toggle and self.win is not None and self.win.is_active():
            self.win.close()
            return 0
        if self.win is None:
            self.win = HubWindow(self, tab or "growth")
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            if tab == "words":
                sel = selection()
                if sel and len(sel) < 200:
                    self.win.view.mode, self.win.view.buf = "text", sel.replace("\n", " ") + " = "
                    self.win.view.text_new = True
            self.win.show_all()
        else:
            self.win.view.reload_style()
            if tab:
                self.win.set_tab(tab)
            self.win.redraw()
        present_unmin(self.win)
        return 0


def shot(path, tab="growth", sel=0, mode="normal", style=None, w=0, h=0, view=None,
         field="title", fdate="", ftime="", fprio=0, frepeat="", gop="spend", chart=None):
    v = View()
    v.g_chart = chart
    if view:
        v.view_mode = view
    v.field, v.f_date, v.f_time, v.f_prio = field, str(fdate), str(ftime), int(fprio)
    v.f_repeat = frepeat
    if style:
        v.style, v.c = style, colors(style)
    v.tab, v.mode = tab, mode
    v.sel[tab] = sel
    v.text_target = sel
    if mode == "text":
        v.buf = "пример"
        v.text_new = True
    if mode == "ginput":
        v.g_op, v.buf = gop, "1500 обед"
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
