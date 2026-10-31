#!/usr/bin/env python3
"""Собеседования таблицей: «Журнал встреч» из Obsidian в окне (Super+Shift+O, 30.10.2026).

Просьба: «Я хочу видеть таблицу, как в Obsidian… Клавиши и бинды те же как в Холсте». Те же заметки
`Вакансии/*`, тот же отбор и порядок, что в dataview журнала (interviews.board); своего хранилища
нет: что поправили здесь, сразу видно в Obsidian и боте, и наоборот.

Клавиши (буквы — по коду клавиши, работают и в русской раскладке)
    h j k l, стрелки    ячейка
    Ctrl+J / Ctrl+K     следующая / предыдущая таблица
    Ctrl+H / Ctrl+L, 0 $  первая / последняя колонка
    gg, G               первая / последняя строка
    Ctrl+E              новая запись: форма-конструктор (iv_form.py); щелчок по полю — строка «Tele2 03.11 15:00»
    e                   открыть запись в форме
    i, a, Enter         править ячейку; Enter — записать, Esc — отмена
    s                   сходил: засчитывается в блок и Замок
    o                   открыть: ссылку из «Резюме» и «Вакансия», иначе заметку в Obsidian
    dd                  убрать: действующее → «отменено», из архива → корзина Obsidian
    u, Ctrl+Z / Ctrl+R  отменить / вернуть
    Esc, q, Ctrl+Q      закрыть; то же сочетание ещё раз тоже закрывает
"""
import json
import os
import re
import signal
import subprocess
import sys

RUN = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
PIDFILE = os.path.join(RUN, "jarvis-ivtable.pid")


def running():
    try:
        pid = int(open(PIDFILE).read())
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return pid if b"iv_table" in f.read() else 0
    except (OSError, ValueError):
        return 0


if __name__ == "__main__":                            # до тяжёлых импортов: второе нажатие закрывает
    if running():
        os.kill(running(), signal.SIGTERM)
        sys.exit(0)
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

if __name__ == "__main__":
    from menu_one import close_others              # Холст не должен остаться под таблицей
    close_others(__file__)

import growth as G  # noqa: E402
import hublib  # noqa: E402
import interviews as IV  # noqa: E402
import preset_ask as pa  # noqa: E402
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

cw, T = pa.cw, pa.T

K_Q, K_E, K_R, K_U, K_I, K_O, K_A, K_S, K_D, K_G, K_H, K_J, K_K, K_L, K_Z, K_0 = (
    24, 26, 27, 30, 31, 32, 38, 39, 40, 42, 43, 44, 45, 46, 52, 19)
K_4 = 13
ARROWS = {Gdk.KEY_Left: K_H, Gdk.KEY_Right: K_L, Gdk.KEY_Down: K_J, Gdk.KEY_Up: K_K}
LIST_MS = 5000                 # заметки правят и в Obsidian, и из бота

# (поле записи, заголовок, ширина в знаках, поле заметки)
COLS = (("name", "Компания", 24, None), ("status", "Статус", 11, "status"),
        ("format", "Собес.", 8, "interview_format"), ("level", "Уровень", 10, "level"),
        ("work", "Формат", 16, "format"), ("salary", "ЗП", 16, "salary"), ("date", "Дата", 15, "date"),
        ("cv", "Резюме", 10, "cv"), ("stack", "Стек", 18, "stack"), ("contacts", "Контакты", 18, "contacts"),
        ("link", "Вакансия", 12, "link"))
COL_PAD = 10
SCREEN_GAP = 40                # от края монитора до окна
SPARE_ROWS = 3                 # запас под новые строки, пока окно открыто
MIN_W, MIN_H = 1180, 420
KEEP = ("status", "date", "work")   # эти колонки не обрезаются: их читают целиком
WIDTHS = {}                    # колонка → ширина в знаках: по содержимому, не больше COLS
HINTS = {"normal": "i — ячейка · e — форма · Ctrl+E — новое · s — сходил · o — открыть · dd — убрать · u, Ctrl+R · gg, G",
         "insert": "Enter — записать · Esc — отмена"}

pa.NAMESPACE = "jarvis-ivtable"
pa.TITLE = "Interviews.exe"
pa.ICON_BMP = pa.PEN_BMP
pa.PLACEHOLDER = "Новое: Tele2 03.11 15:00 онлайн"
pa.GROUP = "Журнал встреч"
pa.EMPTY = "Собеседований нет"
pa.OVERWRITE = ""
pa.DATES = False
pa.MAX_LEN = 300


def screen():
    """Логический размер монитора в фокусе: окно подгоняется под него."""
    try:
        out = json.loads(subprocess.run(("niri", "msg", "-j", "focused-output"), capture_output=True,
                                        text=True, timeout=2).stdout)["logical"]
        return out["width"], out["height"]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return 1920, 1080


def cell_str(it, key):
    if key == "date":
        return date_text(it)
    if key == "link":
        return link_text(it["link"])
    return it[key] or ""


def fit_widths(items, room):
    """Ширины колонок по содержимому. Не вошло в room знаков — ужимается самая широкая: так обрезается
    один длинный столбец, а не все понемногу."""
    w = {key: max(len(title) + 1, min(cap, max((len(cell_str(i, key)) + 1 for i in items), default=0)))
         for key, title, cap, _f in COLS}
    floor = {key: w[key] if key in KEEP else len(title) + 1 for key, title, _c, _f in COLS}
    while sum(w.values()) > room:
        key = max(w, key=lambda k: w[k] - floor[k])
        if w[key] <= floor[key]:
            break
        w[key] -= 1
    WIDTHS.update(w)


def geometry(style):
    global HEAD_Y, HEAD_H, BOX_Y, BOX_H, FOOT_Y, H
    pa.ROW = pa.PX + 8
    pa.GAP = 1
    board = IV.board()
    items = [i for _t, rows in board for i in rows]
    sw, sh = screen()
    frame = 2 * pa.X0 + 18 + pa.BAR + 8
    fit_widths(items, (sw - 2 * SCREEN_GAP - frame - COL_PAD * len(COLS)) // pa.ADV)
    wide = sum(WIDTHS.values()) * pa.ADV + COL_PAD * len(COLS)
    pa.W = max(MIN_W, wide + frame)
    rows = (len(items) + SPARE_ROWS) * (pa.ROW + pa.GAP) + len(board) * (pa.ROW + pa.GAP + 6)
    chrome = pa.TOP + pa.TB + 8 + pa.SEARCH_H + 14 + 10 + pa.PX + 12 + 2 + 8 + 8 + pa.FOOT_H + pa.PAD + pa.BORDER
    H = pa.H = min(sh - 2 * SCREEN_GAP, max(MIN_H, chrome + rows))
    pa.CW = pa.W - 2 * pa.X0
    pa.SEARCH_Y = pa.TOP + pa.TB + 8
    FOOT_Y = pa.FOOT_Y = H - pa.FOOT_H - pa.PAD - pa.BORDER
    BOX_Y = pa.SEARCH_Y + pa.SEARCH_H + 14
    BOX_H = FOOT_Y - 8 - BOX_Y
    pa.LX, pa.LW = pa.X0 + 9, pa.CW - 18
    HEAD_Y, HEAD_H = BOX_Y + 10, pa.PX + 12
    pa.LIST_Y = HEAD_Y + HEAD_H + 2
    pa.LIST_H = BOX_Y + BOX_H - 8 - pa.LIST_Y


def rgb(hexcol):
    return tuple(int(hexcol[i:i + 2], 16) / 255 for i in (1, 3, 5))


def date_text(it):
    w = it["when"]
    if w is None:
        return ""
    clock = w.strftime(" %H:%M") if it["timed"] else ""
    days = (w.date() - G.dt.date.today()).days
    if days == 0:
        return "⚡ сегодня" + clock
    return "%s %02d.%02d%s" % (IV.WEEK[w.weekday()], w.day, w.month, clock)


def link_text(url):
    return re.sub(r"^https?://(www\.)?", "", IV._label(url))


class Table(pa.Dialog):
    def __init__(self, test=False, style=None):
        self.conn = hublib.connect()
        self.mode, self.edit, self.chord, self.note = "normal", None, "", ""
        self.lines, self.items, self.undos, self.redos = [], [], [], []
        self.col, self.sig = 0, None
        super().__init__([], test=test, style=style)
        self.load()
        self.sel = 0 if self.items else -1
        self.caret = False
        if not self.items:
            self.start_new()
        if not test:
            GLib.timeout_add(LIST_MS, self.on_timer)

    def apply_style(self, style):
        super().apply_style(style)
        geometry(self.style)

    # ── данные ─────────────────────────────────────────────────────────────
    def load(self):
        was = self.items[self.sel]["path"] if 0 <= self.sel < len(self.items) else None
        self.lines, self.items = [], []
        for title, rows in IV.board():
            self.lines.append(("head", title, len(rows)))
            self.lines += [("row", it, None) for it in rows]
            self.items += rows
        self.sig = self.signature()
        fit_widths(self.items, sum(WIDTHS.values()))
        paths = [it["path"] for it in self.items]
        self.sel = paths.index(was) if was in paths else min(self.sel, len(self.items) - 1)

    @staticmethod
    def signature():
        return IV.signature(IV.ACTIVE + IV.ARCHIVE)

    def on_timer(self):
        if self.signature() != self.sig:
            self.load()
            self.reveal()
            self.redraw()
        return True

    def current(self):
        return self.items[self.sel] if 0 <= self.sel < len(self.items) else None

    def reload(self, path=None):
        """После правки: перечитать и остаться на той же записи, где бы теперь ни лежала заметка."""
        if path:
            self.load()
            paths = [it["path"] for it in self.items]
            self.sel = paths.index(path) if path in paths else max(0, min(self.sel, len(paths) - 1))
        else:
            self.load()
        self.reveal()
        self.redraw()

    # ── история: пара шагов «назад» и «вперёд» ─────────────────────────────
    def push(self, back, forth):
        self.undos.append((back, forth))
        self.redos.clear()

    def track(self, it, change):
        """Правка заметки со снимками до и после. change → текст ошибки или None."""
        c = self.conn
        was = IV.snapshot(it)
        said = change()
        if said:
            return said
        now = IV.snapshot(it)
        self.push(lambda: (IV.restore(c, now[0], was), was[0])[1], lambda: (IV.restore(c, was[0], now), now[0])[1])
        self.reload(now[0])
        return None

    def undo(self):
        self.step(self.undos, self.redos, 0)

    def redo(self):
        self.step(self.redos, self.undos, 1)

    def step(self, take, put, side):
        if take:
            pair = take.pop()
            put.append(pair)
            self.reload(pair[side]())

    # ── команды ────────────────────────────────────────────────────────────
    def attend(self):
        it = self.current()
        if not it:
            return
        c = self.conn
        ids = {r["id"] for r in IV.visits(c)}
        was = IV.snapshot(it)
        IV.attend(c, it)
        self.note = IV.tally(c)
        now = IV.snapshot(it)
        rows = [r for r in IV.visits(c) if r["id"] not in ids]

        def back():
            for r in rows:
                G.remove(c, r["id"])
            IV.restore(c, now[0], was)
            return was[0]

        def forth():
            for r in rows:
                G.put_back(c, r)
            IV.restore(c, was[0], now)
            return now[0]
        self.push(back, forth)
        self.reload(now[0])

    def drop(self):
        it = self.current()
        if not it:
            return
        i = self.sel
        if it["folder"] in IV.ACTIVE:
            self.track(it, lambda: IV.cancel(self.conn, it))
            self.note = "отменено: " + it["name"]
        else:
            self.track(it, lambda: IV.trash(self.conn, it))
            self.note = "в корзине Obsidian: " + it["name"]
        self.go(i)

    def open_cell(self):
        it = self.current()
        if not it:
            return
        key = COLS[self.col][0]
        url = re.search(r"https?://[^\s)\"']+", it["raw"].get(COLS[self.col][3] or "", "") or "") \
            if key in ("cv", "link") else None
        if url:
            subprocess.Popen(["xdg-open", url.group(0)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            IV.open_note(it)

    def start_new(self):
        self.mode, self.edit, self.caret, self.chord = "insert", None, True, ""
        self.set_entry("")

    def start_edit(self):
        it = self.current()
        if not it:
            return
        key, _title, _w, field = COLS[self.col]
        value = {"name": it["name"], "status": it["status"], "date": date_value(it),
                 "stack": it["stack"]}.get(key, IV._plain(it["raw"].get(field or "", "")))
        self.mode, self.edit, self.caret, self.chord = "insert", (it, key, field), True, ""
        self.set_entry(value)

    def stop_input(self):
        self.mode, self.edit, self.caret = "normal", None, False
        self.set_entry("")

    def set_entry(self, text, pos=None):
        sel = self.sel                                 # поле не связано со строкой, как в preset_ask
        super().set_entry(text, pos)
        self.sel = sel

    def submit(self):
        text = self.entry.strip()
        c = self.conn
        if self.edit is None:
            if not text:
                return
            before = {it["path"] for it in self.items}
            said = IV.create(c, text, need_date=False)
            if not said:
                self.note = "не понял: «Tele2 03.11 15:00»"
                self.redraw()
                return
            self.load()
            added = [it for it in self.items if it["path"] not in before]
            if added:
                snap = IV.snapshot(added[0])
                self.push(lambda: IV.restore(c, snap[0], None), lambda: (IV.restore(c, None, snap), snap[0])[1])
                self.sel = self.items.index(added[0])
            self.note = said
            self.stop_input()
        else:
            it, key, field = self.edit
            if key == "name":
                old = it["name"]
                said = IV.rename(c, it, text)
                if not said:
                    new = it["name"]
                    self.push(lambda: self.rename_back(new, old), lambda: self.rename_back(old, new))
                    self.stop_input()
                    self.reload(it["path"])
                    return
            else:
                said = self.track(it, lambda: IV.set_cell(c, it, field, text))
            if said:
                self.note = said
                self.redraw()
                return
            self.stop_input()
        self.reveal()
        self.redraw()

    def rename_back(self, name, new):
        it = next(i for i in self.items if i["name"] == name)
        IV.rename(self.conn, it, new)
        return it["path"]

    # ── движение ───────────────────────────────────────────────────────────
    def go(self, i):
        if self.items:
            self.sel = max(0, min(len(self.items) - 1, i))
            self.reveal()
            self.redraw()

    def go_section(self, d):
        """Первая строка следующей/предыдущей таблицы; пустые пропускаются."""
        starts, n = [], 0
        for kind, _a, count in self.lines:
            if kind == "head" and count:
                starts.append(n)
                n += count
        now = max((i for i, s in enumerate(starts) if s <= self.sel), default=0)
        if starts:
            self.go(starts[max(0, min(len(starts) - 1, now + d))])

    def set_col(self, i):
        self.col = max(0, min(len(COLS) - 1, i))
        self.redraw()

    def line_y(self, n):
        """Смещение строки n списка."""
        return sum(self.line_h(k) for k, _a, _b in self.lines[:n])

    @staticmethod
    def line_h(kind):
        return pa.ROW + pa.GAP + (6 if kind == "head" else 0)

    def total(self):
        return self.line_y(len(self.lines))

    def reveal(self):
        if self.sel >= 0:
            n = [i for i, ln in enumerate(self.lines) if ln[0] == "row"][self.sel]
            top = self.line_y(n)
            if self.sel == 0:
                top = 0                                # к первой строке — и с её заголовком
            elif self.lines[n - 1][0] == "head":
                top -= self.line_h("head")
            bottom = self.line_y(n + 1)
            if top < self.scroll:
                self.scroll = top
            elif bottom > self.scroll + pa.LIST_H:
                self.scroll = bottom - pa.LIST_H
        self.scroll = max(0, min(self.scroll, max(0, self.total() - pa.LIST_H)))

    # ── клавиши ────────────────────────────────────────────────────────────
    def on_key(self, w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        code = ARROWS.get(k, code)
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and code == K_Q:
            self.finish("")
            return True
        if self.mode == "insert":
            if k == Gdk.KEY_Escape:
                self.stop_input()
                self.redraw()
                return True
            if k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self.submit()
                return True
            return super().on_key(w, ev)
        self.note = ""
        chord, self.chord = self.chord, ""
        if ctrl:
            if code in (K_J, K_K):
                self.go_section(1 if code == K_J else -1)
            elif code in (K_H, K_L):
                self.set_col(0 if code == K_H else len(COLS) - 1)
            elif code == K_E:
                self.open_form()
            elif code == K_Z:
                self.undo()
            elif code == K_R:
                self.redo()
            return True
        if k in (Gdk.KEY_Escape,) or code == K_Q:
            self.finish("")
        elif code == K_G:
            if shift:
                self.go(len(self.items) - 1)
            elif chord == "g":
                self.go(0)
            else:
                self.chord = "g"
        elif code == K_D:
            if chord == "d":
                self.drop()
            else:
                self.chord = "d"
        elif code == K_J:
            self.go(self.sel + 1)
        elif code == K_K:
            self.go(self.sel - 1)
        elif code == K_H:
            self.set_col(self.col - 1)
        elif code == K_L:
            self.set_col(self.col + 1)
        elif code == K_0:
            self.set_col(0)
        elif code == K_4 and shift:
            self.set_col(len(COLS) - 1)
        elif code in (K_I, K_A) or k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.start_edit()
        elif code == K_U:
            self.redo() if shift else self.undo()
        elif code == K_S:
            self.attend()
        elif code == K_O:
            self.open_cell()
        elif code == K_E and self.current():
            self.open_form(self.current()["path"])
        else:
            return True
        self.redraw()
        return True

    def on_press(self, _w, ev):
        x, y = ev.x - pa.RING, ev.y - pa.RING
        if not (0 <= x < pa.W and 0 <= y < pa.H):
            self.finish("")
            return True
        if ev.button != 1:
            return True
        if self.inside(self.zone_close(), x, y):
            self.finish("")
        elif pa.SEARCH_Y <= y < pa.SEARCH_Y + pa.SEARCH_H:
            self.start_new()
        elif pa.LIST_Y <= y < pa.LIST_Y + pa.LIST_H:
            n, yy = 0, y - pa.LIST_Y + self.scroll
            for kind, it, _c in self.lines:
                h = self.line_h(kind)
                if yy < h:
                    if kind == "row":
                        self.sel = self.items.index(it)
                        self.col = self.col_at(x)
                    break
                yy -= h
                n += 1
            self.redraw()
        return True

    def col_at(self, x):
        cx = pa.LX + 6
        for i, c in enumerate(COLS):
            cx += WIDTHS[c[0]] * pa.ADV + COL_PAD
            if x < cx:
                return i
        return len(COLS) - 1

    def open_form(self, path=None):
        """Форма вместо таблицы; записали или закрыли — таблица открывается снова."""
        subprocess.Popen([os.path.join(HERE, "iv_form.py"), "--back"] + (["--edit", path] if path else []),
                         start_new_session=True)
        self.finish("")

    def finish(self, name):
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        if self.test:
            self.result = name
            return
        os._exit(0)

    # ── рисование ──────────────────────────────────────────────────────────
    def line_col(self):
        return self.C.get("gline") or self.C.get("line") or T["st_top"]

    def cut_frame(self, cr, x, y, w, h):
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_source_rgb(*self.C["win_bg"])
        cr.paint()
        if self.dots is not None:
            cr.set_source(self.dots)
            cr.paint()
        cr.restore()

    def draw_box(self, cr):
        """Рамка-группа с подписью в разрыве, как группы Настроек."""
        C, x, y, w = self.C, pa.X0, BOX_Y, pa.CW
        self.rect_line(cr, x, y, w, BOX_H, self.line_col(), 0.9)
        if "gdark" in C:
            self.rect_line(cr, x + 1, y + 1, w - 2, BOX_H - 2, C["gdark"])
        tw = self.layout(cr, pa.GROUP).get_pixel_size()[0]
        self.cut_frame(cr, x + 12, y - 1, tw + 12, 3)
        self.text(cr, pa.GROUP, x + 18, y - pa.PX // 2 - 1, C["text"])

    def cell_text(self, it, key):
        return cell_str(it, key)

    def cell_col(self, it, key, base):
        C = self.C
        if key == "status" and it["status"] in IV.STATUS:
            return rgb(IV.STATUS[it["status"]][1])
        if key == "work":
            m = re.search(r'color="(#[0-9a-fA-F]{6})"', it["raw"].get("format", ""))
            return rgb(m.group(1)) if m else base
        if key in ("cv", "link") and it[key]:
            return C["accent"]
        return base

    def draw_head(self, cr):
        C = self.C
        x = pa.LX + 6
        self.rect_fill(cr, pa.LX, HEAD_Y, pa.LW, HEAD_H, C.get("field", T["st_dark"]))
        for i, (k, title, _c, _f) in enumerate(COLS):
            on = i == self.col
            self.text(cr, title, x + 4, HEAD_Y + (HEAD_H - pa.PX) // 2, C["accent"] if on else C["text"])
            x += WIDTHS[k] * pa.ADV + COL_PAD
        self.rect_fill(cr, pa.LX, HEAD_Y + HEAD_H, pa.LW, 1, self.line_col())

    def draw_rows(self, cr):
        C = self.C
        lw = self.list_w()
        y = pa.LIST_Y - self.scroll
        row = -1
        for kind, a, b in self.lines:
            h = self.line_h(kind)
            if kind == "head":
                if y + h > pa.LIST_Y and y < pa.LIST_Y + pa.LIST_H:
                    ty = y + 6 + (pa.ROW - pa.PX) // 2
                    w = self.text(cr, a, pa.LX + 10, ty, C["accent"])[0]
                    self.text(cr, str(b), pa.LX + 10 + w + 10, ty, C["dim"])
                    if not b:
                        self.text(cr, "пусто", pa.LX + 10 + w + 34, ty, C["dim"], alpha=0.6)
            else:
                row += 1
                if y + h > pa.LIST_Y and y < pa.LIST_Y + pa.LIST_H:
                    self.draw_item(cr, a, pa.LX, y, lw, row == self.sel)
            y += h

    def draw_item(self, cr, it, x, y, w, sel):
        C = self.C
        h = pa.ROW
        if sel:
            self.rect_fill(cr, x, y, w, h, C["sel_bg"])
            self.rect_fill(cr, x, y, 2, h, C["accent"])
        self.rect_fill(cr, x + 8, y + h, w - 16, 1, self.line_col(), 0.35)
        base = C["sel_text"] if sel else C["text"]
        cx, ty = x + 6, y + (h - pa.PX) // 2
        for i, (key, _t, _c, _f) in enumerate(COLS):
            cw_px = WIDTHS[key] * pa.ADV + COL_PAD
            s = self.cell_text(it, key)
            if s:
                self.text(cr, s, cx + 4, ty, base if sel and i != 1 else self.cell_col(it, key, base), cw_px - 12)
            if sel and i == self.col:
                self.rect_line(cr, cx - 1, y, cw_px, h, C["accent"])
            cx += cw_px

    def draw_field(self, cr):
        pa.PLACEHOLDER = COLS_RU.get(self.edit[1], "") if self.edit else "Новое: Tele2 03.11 15:00 онлайн"
        self.draw_entry(cr)

    def draw_footer(self, cr):
        C = self.C
        w = self.text(cr, self.mode.upper(), pa.X0, FOOT_Y, C["accent"])[0]
        hint = HINTS[self.mode]
        hw = self.layout(cr, hint).get_pixel_size()[0]
        self.text(cr, hint, pa.X0 + pa.CW - hw, FOOT_Y, C["dim"], alpha=0.8)
        said = self.note
        it = self.current()
        if self.edit:
            said = "Правка: %s · %s" % (COLS_RU[self.edit[1]], self.edit[0]["name"])
        elif not said and it:
            said = self.cell_text(it, COLS[self.col][0])     # целиком: в узкой колонке обрезано
        if said:
            self.text(cr, said, pa.X0 + w + 14, FOOT_Y, C["dim"], pa.CW - hw - w - 40)

    def render(self, cr):
        C = self.C
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
        self.draw_field(cr)
        self.draw_box(cr)
        self.draw_head(cr)
        cr.save()
        cr.rectangle(pa.LX, pa.LIST_Y, pa.LW, pa.LIST_H)
        cr.clip()
        self.draw_rows(cr)
        g = self.thumb_geom()
        if g:
            bx, ky, kh = g
            self.rect_fill(cr, bx, ky, pa.BAR, kh, C["scroll"])
        cr.restore()
        self.draw_footer(cr)


COLS_RU = {"name": "Компания", "status": "Статус: ожидание, назначено, сходил, отказ, оффер…",
           "format": "Собеседование: онлайн, оффлайн", "level": "Уровень", "work": "Формат работы",
           "salary": "ЗП", "date": "Дата: 04.11 16:00", "cv": "Резюме", "stack": "Стек через запятую",
           "contacts": "Контакты", "link": "Ссылка на вакансию"}


def date_value(it):
    w = it["when"]
    return w.strftime("%d.%m %H:%M" if it["timed"] else "%d.%m") if w else ""


def main():
    dlg = Table()
    if "--at" in sys.argv[:-1]:
        dlg.reload(sys.argv[sys.argv.index("--at") + 1])
    pa.sound("menu")
    for sig in (signal.SIGINT, signal.SIGTERM):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: dlg.finish("") or False)
    Gtk.main()


if __name__ == "__main__":
    main()
