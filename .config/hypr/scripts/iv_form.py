#!/usr/bin/env python3
"""Форма собеседования: собрать карточку кнопками (Super+Ctrl+O, 31.10.2026).

Просьба: «форма как конструктор, как в игре где я выбираю персонажа… Чтоб там были кнопки». Слева
параметры, справа живая карточка с эмблемой компании. Пишет обычную заметку `Вакансии/*` с тем же
оформлением, что в Obsidian (interviews.save_form); при правке трогает только изменённые поля.

Клавиши
    Tab, стрелки вверх-вниз, Ctrl+J/K   строка (на кнопках ещё j k)
    h l, стрелки влево-вправо           значение; день: ±1, с Shift ±7; время: ±30 мин
    1–9                                 кнопка по номеру
    Пробел, Backspace, Delete           снять выбор (время, день), в стеке — очистить
    Enter                               следующая строка, на последней — записать
    Ctrl+S                              записать
    Esc, q на кнопках                   закрыть; с правками — повторным нажатием

Запуск: iv_form.py [--edit ПУТЬ_ЗАМЕТКИ] [--back]; --back возвращает в таблицу. Проверка: iv_form.py check.
"""
import colorsys
import datetime as dt
import hashlib
import os
import signal
import subprocess
import sys

RUN = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
PIDFILE = os.path.join(RUN, "jarvis-ivform.pid")


def running():
    try:
        pid = int(open(PIDFILE).read())
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return pid if b"iv_form" in f.read() else 0
    except (OSError, ValueError):
        return 0


MAIN = __name__ == "__main__" and "check" not in sys.argv
if MAIN:                                              # до тяжёлых импортов: второе нажатие закрывает
    if running():
        os.kill(running(), signal.SIGTERM)
        sys.exit(0)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

if MAIN:
    from menu_one import close_others
    close_others(__file__)

import hublib  # noqa: E402
import interviews as IV  # noqa: E402
import preset_ask as pa  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

cw = pa.cw
mix = pa.mix

pa.NAMESPACE = "jarvis-ivform"
pa.TITLE = "Interview.exe"
pa.ICON_BMP = pa.PEN_BMP
pa.MAX_LEN = 300               # ссылки длинные

K_Q, K_H, K_J, K_K, K_L, K_S = 24, 43, 44, 45, 46, 39
LABEL_W = 126                  # колонка подписей
CARD_W = 390
ROW_H = 38
CHIP_H = 28
CHIP_GAP = 6
WIDTH = 1310
HOURS = range(9, 20)
MINUTES = (0, 15, 30, 45)
EMBLEM = 7                     # клеток в эмблеме
CELL = 14
FLASH_MS = 30

STATUSES = ("ожидание", "назначено", "сходил", "отказ", "оффер")   # «прошёл» значит то же, что «сходил»
# (ключ, подпись, вид, значения); значения chips: (что пишется, что на кнопке)
ROWS = (("name", "Компания", "text", "Tele2"),
        ("status", "Статус", "chips", tuple((s, s) for s in STATUSES)),
        ("day", "День", "days", None),
        ("time", "Время", "time", None),
        ("interview_format", "Собес", "chips", (("онлайн", "онлайн"), ("оффлайн", "оффлайн"))),
        ("format", "Работа", "chips", (("оффлайн", "офис"), ("удалённо", "удалённо"), ("гибрид/удалённо", "гибрид"))),
        ("level", "Уровень", "chips", (("🟢", "зелёный"), ("🔴", "красный"))),
        ("cv", "Резюме", "chips", (("Java", "Java"), ("PHP", "PHP"), ("Go", "Go"), ("Fullstack", "Fullstack"))),
        ("stack", "Стек", "multi", None),
        ("more", "Ещё стек", "text", "через запятую"),
        ("salary", "ЗП", "text", "1000$ или 700 000 ₸"),
        ("contacts", "Контакты", "text", "+7… или @ник"),
        ("link", "Ссылка", "text", "вакансия: Ctrl+V"))
LEVEL_COL = {"🟢": "#4cc26a", "🔴": "#e0524a"}
CV_COL = dict(IV.CV, Fullstack="#9bbb59")
FILLED = ("name", "status", "day", "time", "interview_format", "format", "level", "cv", "stack", "salary")


def rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))


def link_url(text):
    """Из «[Click](https://…)» — сама ссылка: в форме она правится голой."""
    return text.split("](", 1)[1].rstrip(")") if text.startswith("[") and "](" in text else text


class Form(pa.Dialog):
    def __init__(self, path=None, back=False, test=False, style=None):
        self.conn = hublib.connect()
        self.item = IV.item(path) if path else None
        self.back, self.row, self.note, self.flash = back, 0, "", 0.0
        self.force, self.hits, self.saved, self.shown = False, [], None, 0
        self.touched = set()
        self.vals = self.read_item(self.item)
        words = IV.stack_words()
        self.words = words + [w for w in self.vals["stack"] if w not in words]
        self.first = dict(self.vals, stack=list(self.vals["stack"]))
        self.week = max(0, ((self.vals["day"] or dt.date.today()) - dt.date.today()).days // 7)
        super().__init__([], test=test, style=style)
        self.focus_row(1)                              # со статуса: печать не попадает в название

    @staticmethod
    def read_item(it):
        v = dict(name="", status="ожидание", day=None, time=None, interview_format="", format="", level="", cv="",
                 stack=[], more="", salary="", contacts="", link="")
        if not it:
            return v
        v.update(name=it["name"], status=it["status"], interview_format=it["format"], format=it["work"], cv=it["cv"],
                 salary=it["salary"], contacts=it["contacts"], link=link_url(it["link"]),
                 level=it["level"] if it["level"] in LEVEL_COL else "",
                 stack=[w.strip() for w in it["stack"].split(",") if w.strip()])
        if it["when"]:
            v["day"] = it["when"].date()
            v["time"] = it["when"].strftime("%H:%M") if it["timed"] else None
        return v

    def apply_style(self, style):
        super().apply_style(style)
        self.C.setdefault("field", pa.T["st_dark"])
        pa.W = WIDTH
        pa.CW = pa.W - 2 * pa.X0
        self.top = pa.TOP + pa.TB + 10
        self.foot = self.top + len(ROWS) * ROW_H + 8
        pa.FOOT_Y = self.foot
        pa.H = self.foot + pa.FOOT_H + pa.PAD + pa.BORDER
        self.card_x = pa.X0 + pa.CW - CARD_W

    # ── значения ───────────────────────────────────────────────────────────
    def key(self):
        return ROWS[self.row][0]

    def kind(self):
        return ROWS[self.row][2]

    def focus_row(self, i):
        self.row = max(0, min(len(ROWS) - 1, i))
        self.caret = self.kind() == "text"
        if self.caret:
            self.entry = self.vals[self.key()]
            self.pos = len(self.entry)
        self.redraw()

    def go(self, d):
        if self.key() == "name" and not self.item:
            self.fill_known()
        self.focus_row(self.row + d)

    def fill_known(self):
        """Набрали уже знакомую компанию: заметка та же, её поля подставляются, тронутое остаётся."""
        name = self.vals["name"].strip().lower()
        it = next((i for i in IV._read(IV.ACTIVE + IV.ARCHIVE) if i["name"].lower() == name), None) if name else None
        if it:
            keep = {k: self.vals[k] for k in self.touched}
            self.item = it
            self.vals = self.read_item(it)
            self.first = dict(self.vals, stack=list(self.vals["stack"]))
            self.vals.update(keep)
            self.words += [w for w in self.vals["stack"] if w not in self.words]
            self.note = "Такая заметка уже есть: поля подставлены"

    def set_entry(self, text, pos=None):
        self.entry = text[:pa.MAX_LEN]
        self.pos = len(self.entry) if pos is None else max(0, min(pos, len(self.entry)))
        if self.kind() == "text":
            self.vals[self.key()] = self.entry
            self.touched.add(self.key())
        self.bump()

    def bump(self):
        """Карточка вздрагивает на каждое изменение: видно, что собирается."""
        was, self.flash = self.flash, 1.0
        if not was and not self.test:
            GLib.timeout_add(FLASH_MS, self.fade)
        self.redraw()

    def fade(self):
        self.flash = max(0.0, self.flash - 0.1)
        self.redraw()
        return self.flash > 0

    def put(self, key, value):
        self.vals[key] = value
        self.touched.add(key)
        if key == "day" and "status" not in self.touched and self.vals["status"] in ("назначено", "ожидание"):
            self.vals["status"] = "назначено" if value else "ожидание"   # дата есть — значит назначено
        pa.sound("click") if not self.test else None
        self.bump()

    def options(self):
        return ROWS[self.row][3] or ()

    def chip_step(self, d):
        vals = [o[0] for o in self.options()]
        now = self.vals[self.key()]
        i = vals.index(now) if now in vals else (-1 if d > 0 else len(vals))
        self.put(self.key(), vals[(i + d) % len(vals)])

    def day_step(self, d):
        day = self.vals["day"]
        day = day + dt.timedelta(days=d) if day else dt.date.today()
        self.show_day(day)

    def show_day(self, day):
        self.week = max(0, (day - dt.date.today()).days // 7)
        self.put("day", day)

    def time_step(self, d):
        t = self.vals["time"]
        if not t:
            return self.put("time", "10:00")
        h, m = map(int, t.split(":"))
        m = max(0, min(23 * 60 + 30, h * 60 + m + d * 30))
        self.put("time", "%02d:%02d" % (m // 60, m % 60))

    def toggle_word(self, word):
        words = self.vals["stack"]
        words.remove(word) if word in words else words.append(word)
        self.touched.add("stack")
        self.bump()

    def clear_row(self):
        key, kind = self.key(), self.kind()
        if kind == "multi":
            self.vals["stack"] = []
            self.touched.add("stack")
            self.bump()
        elif kind in ("days", "time") or kind == "chips" and key != "status":
            self.put(key, None if kind != "chips" else "")

    def pick_number(self, n):
        kind = self.kind()
        if kind == "chips" and n < len(self.options()):
            self.put(self.key(), self.options()[n][0])
        elif kind == "multi" and n < self.shown:
            self.toggle_word(self.words[n])
        elif kind == "days" and n < 7:
            self.show_day(dt.date.today() + dt.timedelta(days=self.week * 7 + n))

    # ── запись ─────────────────────────────────────────────────────────────
    def stack_now(self):
        more = [w.strip() for w in self.vals["more"].split(",") if w.strip()]
        return self.vals["stack"] + [w for w in more if w not in self.vals["stack"]]

    def changes(self):
        v, a = self.vals, self.first
        f = {k: v[k].strip() for k in ("name", "status", "interview_format", "format", "level", "cv", "salary",
                                       "contacts", "link") if v[k].strip() != a[k].strip()}
        if not self.item:
            f["status"] = v["status"]
        if self.stack_now() != a["stack"]:
            f["stack"] = self.stack_now()
        if v["day"] != a["day"] or v["time"] != a["time"]:
            f["when"] = None
            if v["day"]:
                h, m = map(int, (v["time"] or "0:0").split(":"))
                f["when"] = dt.datetime.combine(v["day"], dt.time(h, m))
            f["timed"] = bool(v["time"])
        return f

    def dirty(self):
        return bool(self.changes()) and not (not self.item and not self.vals["name"].strip()
                                             and not self.touched)

    def save(self):
        if not self.item:
            self.fill_known()
            if self.item:                              # сперва показать, какая заметка откроется
                self.focus_row(self.row)
                return
        f = self.changes()
        said, path = IV.save_form(self.conn, f, self.item)
        if said:
            self.note = said
            self.focus_row(0)
            return
        self.saved = path
        self.force = True
        self.finish("")

    def finish(self, name):
        if self.dirty() and not self.force and not self.saved:
            self.force = True
            self.note = "Правки не записаны: ещё раз, чтобы закрыть"
            self.redraw()
            return
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        if self.test:
            self.result = name
            return
        if self.back:
            subprocess.Popen([os.path.join(HERE, "iv_table.py")] + (["--at", self.saved] if self.saved else []),
                             start_new_session=True)
        os._exit(0)

    # ── клавиши и мышь ─────────────────────────────────────────────────────
    def on_key(self, w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        kind = self.kind()
        text = kind == "text"
        if ctrl and code == K_S:
            self.save()
        elif ctrl and code == K_Q or k == Gdk.KEY_Escape or code == K_Q and not text:
            self.finish("")
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.save() if ctrl or self.row == len(ROWS) - 1 else self.go(1)
        elif k == Gdk.KEY_ISO_Left_Tab or k == Gdk.KEY_Up or ctrl and code == K_K or code == K_K and not text:
            self.go(-1)
        elif k == Gdk.KEY_Tab or k == Gdk.KEY_Down or ctrl and code == K_J or code == K_J and not text:
            self.go(1)
        elif text:
            return super().on_key(w, ev)
        elif k == Gdk.KEY_Left or code == K_H:
            self.step(-1, shift)
        elif k == Gdk.KEY_Right or code == K_L:
            self.step(1, shift)
        elif k in (Gdk.KEY_space, Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            self.clear_row()
        elif Gdk.KEY_1 <= k <= Gdk.KEY_9:
            self.pick_number(k - Gdk.KEY_1)
        else:
            return False
        self.redraw()
        return True

    def step(self, d, big):
        kind = self.kind()
        if kind == "chips":
            self.chip_step(d)
        elif kind == "days":
            self.day_step(d * 7 if big else d)
        elif kind == "time":
            self.time_step(d)
        elif kind == "multi":
            self.note = "Стек: цифра, щелчок или пробел"

    def on_press(self, _w, ev):
        x, y = ev.x - pa.RING, ev.y - pa.RING
        if ev.button != 1:
            return True
        if self.inside(self.zone_close(), x, y):
            self.finish("")
            return True
        for (hx, hy, hw, hh), act in reversed(self.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                self.press(act)
                break
        self.redraw()
        return True

    def press(self, act):
        what = act[0]
        if what == "row":
            self.focus_row(act[1])
        elif what == "chip":
            self.focus_row(act[1])
            key = ROWS[act[1]][0]
            self.put(key, "" if self.vals[key] == act[2] and key != "status" else act[2])
        elif what == "word":
            self.focus_row(act[1])
            self.toggle_word(act[2])
        elif what == "day":
            self.focus_row(act[1])
            self.put("day", None) if self.vals["day"] == act[2] else self.show_day(act[2])
        elif what == "week":
            self.week = max(0, self.week + act[1])
        elif what == "hour":
            self.focus_row(act[1])
            t = self.vals["time"]
            self.put("time", None if t and t[:2] == "%02d" % act[2] else "%02d:%s" % (act[2], t[3:] if t else "00"))
        elif what == "min":
            self.focus_row(act[1])
            self.put("time", "%s:%02d" % ((self.vals["time"] or "10:00")[:2], act[2]))
        elif what == "save":
            self.save()
        elif what == "close":
            self.finish("")

    def on_motion(self, _w, ev):
        x, y = ev.x - pa.RING, ev.y - pa.RING
        hover = "close" if self.inside(self.zone_close(), x, y) else None
        for (hx, hy, hw, hh), act in reversed(self.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh and act[0] != "row":
                hover = act
                break
        if hover != self.hover:
            self.hover = hover
            self.redraw()
        return True

    def on_scroll(self, _w, _ev):
        return True

    # ── рисование ──────────────────────────────────────────────────────────
    def line_col(self):
        return self.C.get("gline") or self.C.get("line") or pa.T["st_top"]

    def big(self, cr, s, x, y, col, k, width=None):
        lay = self.layout(cr, s, width)
        fd = self.fd.copy()
        fd.set_absolute_size(pa.PX * k * Pango.SCALE)
        lay.set_font_description(fd)
        cr.set_source_rgb(*col)
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()

    def chip(self, cr, x, y, label, on, act, col=None, w=None):
        """Кнопка значения; выбранная залита цветом значения."""
        C = self.C
        tw = self.layout(cr, label).get_pixel_size()[0]
        w = w or tw + 20
        hot = self.hover == act
        col = col or C["accent"]
        self.rect_fill(cr, x, y, w, CHIP_H, col if on else C["field"], 1.0 if on else 0.8)
        self.rect_line(cr, x, y, w, CHIP_H, col if on or hot else self.line_col())
        ink = (0.07, 0.07, 0.1) if on and sum(col) > 1.2 else C["text"]
        self.text(cr, label, x + (w - tw) // 2, y + (CHIP_H - pa.PX) // 2, ink if on else C["text"] if hot else C["dim"])
        self.hits.append(((x, y, w, CHIP_H), act))
        return x + w + CHIP_GAP

    def chip_col(self, key, value):
        if key == "status":
            return rgb(IV.STATUS[value][1])
        if key == "level":
            return rgb(LEVEL_COL[value])
        return rgb(CV_COL[value]) if key == "cv" else None

    def draw_chips(self, cr, i, x, y):
        key = ROWS[i][0]
        for n, (value, label) in enumerate(ROWS[i][3]):
            x = self.chip(cr, x, y, label, self.vals[key] == value, ("chip", i, value), self.chip_col(key, value))

    def draw_multi(self, cr, i, x, y):
        end = self.card_x - 12
        self.shown = 0
        for w in self.words:
            if x + self.layout(cr, w).get_pixel_size()[0] + 20 > end:   # не влезло: пишется в «Ещё стек»
                break
            x = self.chip(cr, x, y, w, w in self.vals["stack"], ("word", i, w))
            self.shown += 1

    def draw_days(self, cr, i, x, y):
        today = dt.date.today()
        x = self.chip(cr, x, y, "<", False, ("week", -1), w=30)
        for n in range(7):
            d = today + dt.timedelta(days=self.week * 7 + n)
            word = {0: "сег", 1: "зав"}.get((d - today).days, IV.WEEK[d.weekday()])
            x = self.chip(cr, x, y, "%s %d" % (word, d.day), self.vals["day"] == d, ("day", i, d), w=72)
        self.chip(cr, x, y, ">", False, ("week", 1), w=30)

    def draw_time(self, cr, i, x, y):
        t = self.vals["time"]
        for h in HOURS:
            x = self.chip(cr, x, y, "%02d" % h, bool(t) and t[:2] == "%02d" % h, ("hour", i, h), w=38)
        x += 6
        for m in MINUTES:
            x = self.chip(cr, x, y, ":%02d" % m, bool(t) and t[3:] == "%02d" % m, ("min", i, m), w=44)

    def draw_text_row(self, cr, i, x, y, w):
        key, _label, _kind, hint = ROWS[i]
        C, on = self.C, i == self.row
        self.rect_fill(cr, x, y, w, CHIP_H, C["field"], 0.8)
        self.rect_line(cr, x, y, w, CHIP_H, C["accent"] if on else self.line_col())
        tx, ty, room = x + 8, y + (CHIP_H - pa.PX) // 2, w - 16
        text = self.vals[key]
        if not text:
            self.text(cr, hint, tx, ty, C["dim"], alpha=0.6)
            cx = tx
        else:
            lay = self.layout(cr, text)
            at = lay.index_to_pos(len(text[:self.pos if on else 0].encode("utf-8"))).x // Pango.SCALE
            shift = max(0, at + 2 - room)
            cr.save()
            cr.rectangle(x + 1, y + 1, w - 2, CHIP_H - 2)
            cr.clip()
            cr.set_source_rgb(*C["text"])
            cr.move_to(tx - shift, ty)
            PangoCairo.show_layout(cr, lay)
            cr.restore()
            cx = tx + at - shift
        if on:
            self.rect_fill(cr, cx, ty, 2, pa.PX, C["accent"])

    def draw_rows(self, cr):
        C = self.C
        fx = pa.X0
        fw = self.card_x - 12 - fx
        for i, (key, label, kind, _o) in enumerate(ROWS):
            y = self.top + i * ROW_H
            self.hits.append(((fx, y, fw, ROW_H), ("row", i)))
            if i == self.row:
                self.rect_fill(cr, fx, y + 1, fw, ROW_H - 2, C["accent"], 0.1)
                self.rect_fill(cr, fx, y + 1, 3, ROW_H - 2, C["accent"])
            self.text(cr, label, fx + 12, y + (ROW_H - pa.PX) // 2, C["text"] if i == self.row else C["dim"])
            x, cy = fx + LABEL_W, y + (ROW_H - CHIP_H) // 2
            if kind == "text":
                self.draw_text_row(cr, i, x, cy, fw - LABEL_W - 8)
            else:
                getattr(self, "draw_" + kind)(cr, i, x, cy)

    def emblem(self, cr, x, y, col):
        """Эмблема компании из её имени: своя у каждой и меняется на каждую букву."""
        name = self.vals["name"].strip().lower()
        C = self.C
        self.rect_fill(cr, x, y, EMBLEM * CELL + 16, EMBLEM * CELL + 16, C["field"])
        self.rect_line(cr, x, y, EMBLEM * CELL + 16, EMBLEM * CELL + 16, col)
        if not name:
            self.text(cr, "?", x + (EMBLEM * CELL + 16 - pa.ADV) // 2, y + (EMBLEM * CELL + 16 - pa.PX) // 2, C["dim"])
            return
        h = hashlib.md5(name.encode("utf-8")).digest()
        hue = colorsys.hsv_to_rgb(h[15] / 255, 0.55, 0.95)
        half = (EMBLEM + 1) // 2
        for r in range(EMBLEM):
            for c in range(half):
                if h[(r * half + c) % 14] & 1 << (c % 8) or (r == 3 and c == half - 1):
                    for cc in {c, EMBLEM - 1 - c}:
                        self.rect_fill(cr, x + 8 + cc * CELL, y + 8 + r * CELL, CELL, CELL, hue)

    def when_line(self):
        v = self.vals
        if not v["day"]:
            return "Дата не назначена", None
        days = (v["day"] - dt.date.today()).days
        word = {0: "сегодня", 1: "завтра", 2: "послезавтра"}.get(days)
        word = word or ("через %d дн." % days if days > 0 else "%d дн. назад" % -days)
        day = "%s %02d.%02d" % (IV.WEEK[v["day"].weekday()], v["day"].day, v["day"].month)
        tip = None
        if days >= 0:
            tip = "Напомню за 2 ч и за 30 мин" if v["time"] else "Без времени напоминаний за 2 ч и 30 мин не будет"
        return "%s%s · %s" % (day, " " + v["time"] if v["time"] else "", word), tip

    def filled(self):
        v = dict(self.vals, stack=self.stack_now())
        return sum(1 for k in FILLED if v[k])

    def draw_stat(self, cr, x, y, w, label, value, col=None):
        C = self.C
        self.text(cr, label, x, y, C["dim"])
        self.text(cr, value or "—", x + 112, y, col or (C["text"] if value else C["dim"]), w - 112)

    def draw_card(self, cr):
        C, v = self.C, self.vals
        x, y, w = self.card_x, self.top + 2, CARD_W
        h = self.foot - y - 8
        scol = rgb(IV.STATUS[v["status"]][1]) if v["status"] in IV.STATUS else C["accent"]
        self.rect_fill(cr, x, y, w, h, C["field"], 0.35)
        self.rect_line(cr, x, y, w, h, mix(self.line_col(), scol, self.flash))
        self.rect_fill(cr, x, y, w, 4, scol)
        ix, iw = x + 16, w - 32
        ey = y + 18
        self.emblem(cr, ix, ey, scol)
        sx = ix + EMBLEM * CELL + 16 + 14
        self.rect_fill(cr, sx, ey, ix + iw - sx, 26, scol)
        ink = (0.07, 0.07, 0.1) if sum(scol) > 1.2 else (1, 1, 1)
        self.text(cr, v["status"], sx + 8, ey + 5, ink, ix + iw - sx - 16)
        got = self.filled()
        self.text(cr, "Собрано %d из %d" % (got, len(FILLED)), sx, ey + 42, C["dim"], ix + iw - sx)
        by = ey + 62
        self.rect_fill(cr, sx, by, ix + iw - sx, 10, C["field"])
        self.rect_fill(cr, sx, by, (ix + iw - sx) * got // len(FILLED), 10, scol)
        if v["status"] in IV.VISITED:
            self.text(cr, "+40 энергии", sx, by + 20, rgb("#ffd76a"))
        y2 = ey + EMBLEM * CELL + 16 + 12
        self.big(cr, v["name"].strip() or "Компания", ix, y2, C["text"] if v["name"].strip() else C["dim"], 1.5, iw)
        y2 += 34
        when, tip = self.when_line()
        self.text(cr, when, ix, y2, C["accent"], iw)
        y2 += 22
        if tip:
            self.text(cr, tip, ix, y2, C["dim"], iw, lines=2)
        y2 += 44
        stack = self.stack_now()
        stats = (("Собес", v["interview_format"], None), ("Работа", v["format"], None),
                 ("Уровень", {"🟢": "зелёный", "🔴": "красный"}.get(v["level"], ""), rgb(LEVEL_COL[v["level"]]) if v["level"] else None),
                 ("Резюме", v["cv"], rgb(CV_COL[v["cv"]]) if v["cv"] in CV_COL else None), ("ЗП", v["salary"], None),
                 ("Стек", ", ".join(stack), None), ("Контакты", v["contacts"], None))
        for label, value, col in stats:
            self.draw_stat(cr, ix, y2, iw, label, value, col)
            y2 += 22
        by = y + h - 52
        half = (iw - 8) // 2
        self.action(cr, ix, by, half, "Записать", ("save",), True)
        self.action(cr, ix + half + 8, by, iw - half - 8, "Закрыть", ("close",), False)

    def action(self, cr, x, y, w, label, act, hot):
        C = self.C
        tw = self.layout(cr, label).get_pixel_size()[0]
        col = C["accent"] if hot else self.line_col()
        self.rect_fill(cr, x, y, w, 38, C["accent"] if hot else C["field"], 1.0 if hot else 0.8)
        self.rect_line(cr, x, y, w, 38, C["text"] if self.hover == act else col)
        ink = (0.07, 0.07, 0.1) if hot and sum(C["accent"]) > 1.2 else C["text"]
        self.text(cr, label, x + (w - tw) // 2, y + (38 - pa.PX) // 2, ink)
        self.hits.append(((x, y, w, 38), act))

    def draw_footer(self, cr):
        C = self.C
        hint = "Tab строка · h l значение · 1–9 кнопка · Backspace снять · Ctrl+S записать · Esc закрыть"
        if self.note:
            self.text(cr, self.note, pa.X0, self.foot, C["accent"])
        else:
            self.text(cr, hint, pa.X0, self.foot, C["dim"], pa.CW, alpha=0.8)

    def render(self, cr):
        C = self.C
        self.hits = []
        cr.save()
        cr.rectangle(0, 0, pa.W, pa.H)
        cr.clip()
        cr.set_source_rgba(*C["win_bg"], C["win_alpha"])
        cr.paint()
        if self.style == "skeet" and self.dots is not None:
            cr.set_source(self.dots)
            cr.paint_with_alpha(C["win_alpha"])
        cr.restore()
        getattr(self, "frame_" + self.style)(cr)
        self.draw_rows(cr)
        self.draw_card(cr)
        self.draw_footer(cr)


def arg(name):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv[:-1] else None


def main():
    dlg = Form(arg("--edit"), "--back" in sys.argv)

    def stop(*_a):                                    # закрыли снаружи: таблицу обратно не открывать
        dlg.force, dlg.back = True, False
        dlg.finish("")
        return False

    pa.sound("menu")
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, stop)
    Gtk.main()


if __name__ == "__main__":
    if "check" in sys.argv:
        Form(test=True).render_png(os.path.join(RUN, "jarvis-ivform-check.png"))
        print("ok")
    else:
        main()
