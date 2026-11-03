#!/usr/bin/env python3
"""Холст и Потом — одно окно на время фокуса (30.10.2026).

Просьба пользователя: «интерфейс как в Obsidian, в блокноте: полноценный холст как дневник,
текст не в одну строку… Холст — описание эмоции, то есть не позывы к действиям». Позывы
к действиям идут в список «Потом». «Видеть снизу список отложенных, через разделитель.
А сверху пишу свои мысли».

    holst.py [holst|later]   открыть, ввод в Холсте (Super+Shift+I) или в поле «Потом»

Повторное нажатие той же клавиши закрывает окно, другой — переводит ввод
(SIGUSR1 — Холст, SIGUSR2 — Потом). Окно открыто в одном экземпляре, pid — в
$XDG_RUNTIME_DIR/jarvis-holst.pid; его же берёт Ctrl+Q (niri/scripts/close-or-clipboard).

Рамка, слои-ловцы с размытием, поле и список — из preset_ask.py (родня буфера обмена):
класс наследует его Dialog и меняет размеры через глобальные переменные модуля. Текст
Холста — настоящий Gtk.TextView поверх рисунка: перенос, курсор, мышь, вставка.

Холст — текст заметки дня в Obsidian (growth.holst_page: Personal/2026/Октябрь/2026-10-30.md),
одна на логический день, сохраняется сама: через 1,5 с после правки и при закрытии. Потеря
мысли хуже лишней записи, поэтому здесь не так, как с черновиками hub. Потом — записи kind
later, те, что заведены в этот день, дописываются в заметку разделом «## Потом». Список у
каждого дня свой (01.11.2026): новый день начинается с пустого, старое остаётся в своей
заметке, Ctrl+H/L листают Холст и Потом вместе.

Метки времени (01.11.2026, просьба: «чтобы я понимал, во сколько я это писал… компактно, но
читаемо»): мелкие, тусклые, в конце предложения, только там, где минута меняется. В текст и в
заметку не попадают: это рисунок поверх TextView (draw_stamps), время лежит в holst-times.json
по дням, ключ — текст предложения. Написанное до 01.11, в Obsidian и из бота метки не имеет.

Окно — три остановки сверху вниз, Ctrl+J и Ctrl+K ходят по ним: Холст → поле новой строки →
строки списка (Пользователь 30.10). Холст и поле — только для письма, режимов нет.

Клавиши
    Ctrl+J / Ctrl+K     остановка или строка списка вниз / вверх
    Ctrl+H / Ctrl+L     заметка дня назад / вперёд
    Ctrl+S              записать сейчас
    Ctrl+Z / Ctrl+R     отменить / вернуть
    Esc, Ctrl+Q         закрыть
    В списке            j k, dd или x — убрать, u — отменить, gg — к началу Холста, G — последняя
                        строка, i или Ctrl+E — поле, q — закрыть
Буквы списка узнаются по коду клавиши, поэтому работают и в русской раскладке.
"""
import datetime as dt
import difflib
import json
import math
import os
import re
import signal
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
PIDFILE = os.path.join(RUN, "jarvis-holst.pid")
SIGNALS = {"holst": signal.SIGUSR1, "later": signal.SIGUSR2}
PENDING = []                   # нажатия, пришедшие, пока грузится GTK


def running():
    try:
        pid = int(open(PIDFILE).read())
        with open("/proc/%d/cmdline" % pid, "rb") as f:
            return pid if b"holst" in f.read() else 0
    except (OSError, ValueError):
        return 0


def claim(tab):
    """До тяжёлых импортов: окно уже есть — передать ему нажатие и выйти."""
    pid = running()
    if pid:
        os.kill(pid, SIGNALS[tab])
        sys.exit(0)
    for sig in SIGNALS.values():
        signal.signal(sig, lambda n, _f: PENDING.append(n))
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))


if __name__ == "__main__":
    TAB = sys.argv[1] if sys.argv[1:2] in (["holst"], ["later"]) else "holst"
    claim(TAB)
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from menu_one import close_others              # таблица собеседований не должна лечь поверх
    close_others(__file__)

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

import cairo  # noqa: E402

import growth as G  # noqa: E402
import hublib  # noqa: E402
import preset_ask as pa  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

cw, T = pa.cw, pa.T

W, H = 1120, 820               # окно: ~100 знаков в строке (04.11.2026: «увеличить, желательно по горизонтали», было 880×780)
ROWS = 4                       # строк списка Потом без прокрутки
LIST_MS = 5000                 # список дописывают и из бота и Obsidian: сверка, пока окно открыто
SAVE_MS = 1500
UNDO_PAUSE_MS = 800            # пауза в наборе — отдельный шаг отмены
UNDO_MAX = 300
MARGIN = 20                    # поле листа слева и справа
MORE_H = 40                    # полоса «ниже ещё текст»
LIST_MAX = 16                  # отступ пункта списка, знаков
SIDE = 40                      # поле листа справа: туда встаёт метка времени в конце строки
STAMP_GAP = 6                  # от текста до метки
NEAR = 0.6                     # похожесть, при которой правка не считается новым предложением
TIMES = os.path.expanduser("~/.local/share/hub/holst-times.json")
SENT_RE = re.compile(r"\S.*?(?:[.!?…]+(?=\s|$)|$)", re.M)
HEAD_RE = re.compile(r"^(#{1,6})\s+\S")
LIST_RE = re.compile(r"^(\s*)(?:[-*+]|\d+[.)])\s+")
TASK_RE = re.compile(r"^(\s*)[-*+]\s+\[(.)\]\s+")
INLINE = ((re.compile(r"\*\*[^*\n]+\*\*"), "bold", 2), (re.compile(r"(?<!\*)\*[^*\s][^*\n]*\*(?!\*)"), "italic", 1),
          (re.compile(r"`[^`\n]+`"), "code", 1), (re.compile(r"\[\[[^\]\n]+\]\]"), "link", 2),
          (re.compile(r"(?<![\w#])#[\w/-]+"), "link", 0))
MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
          "сентября", "октября", "ноября", "декабря")
DAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
PAPER = "Что я сейчас чувствую? Эмоции, не дела."
HINTS = {"holst": "Ctrl+J — Потом · Ctrl+Z, Ctrl+Shift+Z · Esc — закрыть",
         "field": "Enter — добавить · Ctrl+J — список · Ctrl+K — Холст",
         "list": "dd — убрать · u, Ctrl+R · Ctrl+K — вверх · gg — Холст · G — конец"}

# коды клавиш (не буквы): в русской раскладке те же
K_Q, K_E, K_R, K_U, K_I, K_A, K_S, K_D, K_G, K_H, K_J, K_K, K_L, K_Z, K_X = (
    24, 26, 27, 30, 31, 38, 39, 40, 42, 43, 44, 45, 46, 52, 53)
ARROWS = {Gdk.KEY_Left: K_H, Gdk.KEY_Right: K_L, Gdk.KEY_Down: K_J, Gdk.KEY_Up: K_K}

pa.NAMESPACE = "jarvis-holst"
pa.TITLE = "Holst.exe"
pa.ICON_BMP = pa.PEN_BMP
pa.PLACEHOLDER = "Чего хочется вместо задачи?"
pa.GROUP = "Потом"
pa.EMPTY = "Пока пусто"
pa.OVERWRITE = ""
pa.DATES = False
pa.MAX_LEN = 300


def changed_at(old, new):
    """Где курсор после отмены/повтора: конец изменённого места в новом тексте."""
    i = 0
    while i < len(old) and i < len(new) and old[i] == new[i]:
        i += 1
    j = 0
    while j < len(old) - i and j < len(new) - i and old[-1 - j] == new[-1 - j]:
        j += 1
    return len(new) - j


def geometry(style):
    """Размеры поверх preset_ask.set_geometry: сверху лист Холста, снизу группа «Потом» с полем
    и списком внутри, от низа окна; листу — всё остальное."""
    global PAGE_Y, PAGE_H, TEXT_Y, SEP_Y, FOOT_Y
    pa.W, pa.H = W, H
    pa.CW = W - 2 * pa.X0
    PAGE_Y = pa.TOP + pa.TB + 8
    TEXT_Y = PAGE_Y + 2 * pa.PX + 24           # заголовок дня, как имя заметки в Obsidian
    FOOT_Y = pa.FOOT_Y = H - pa.FOOT_H - pa.PAD - pa.BORDER
    pa.ROW = pa.PX + 14
    pa.GAP = 1                                 # в щель между строками ложится черта
    pa.LX, pa.LW = pa.X0 + 9, pa.CW - 18
    pa.LIST_H = ROWS * pa.ROW + (ROWS - 1) * pa.GAP
    pa.LIST_Y = FOOT_Y - 10 - 8 - pa.LIST_H
    pa.SEARCH_Y = pa.LIST_Y - 8 - pa.SEARCH_H
    SEP_Y = pa.SEARCH_Y - 10
    PAGE_H = SEP_Y - pa.PX // 2 - 8 - PAGE_Y


def hexcol(c):
    return "#%02x%02x%02x" % tuple(int(round(v * 255)) for v in c[:3])


def align(old, new, now, gone):
    """Времена предложений после правки. old — [(текст, время)], new — тексты сейчас, now — время
    для нового (None — не ставить). Неизменное и слегка поправленное время не меняет. gone —
    {текст: [время]} убранного: вернётся через отмену или перенос, время то же."""
    n, a, b = min(len(old), len(new)), 0, 0
    while a < n and old[a][0] == new[a]:
        a += 1
    while b < n - a and old[-1 - b][0] == new[-1 - b]:
        b += 1
    was = old[a:len(old) - b]
    fresh = new[a:len(new) - b]
    out = {}
    for i, s in enumerate(fresh):
        j = next((j for j, r in enumerate(was) if r[0] == s), None)
        if j is not None:
            out[i] = was.pop(j)[1]
        elif gone.get(s):
            out[i] = gone[s].pop(0)
    if len(was) * len(fresh) <= 400:
        for i, s in enumerate(fresh):
            if i not in out and was:
                k = [difflib.SequenceMatcher(None, r[0], s, autojunk=False).ratio() for r in was]
                if max(k) >= NEAR:
                    out[i] = was.pop(k.index(max(k)))[1]
    for r in was:
        if r[1]:
            gone.setdefault(r[0], []).append(r[1])
    mid = [(s, out.get(i, now)) for i, s in enumerate(fresh)]
    return old[:a] + mid + old[len(old) - b:] if b else old[:a] + mid


def stamps(text, seq, spans):
    """Что рисовать: [(смещение конца предложения, «ЧЧ:ММ», внутри строки?)]; подряд идущие
    предложения одной минуты получают одну метку, после последнего."""
    out = []
    for i, (_s, t) in enumerate(seq):
        nxt = seq[i + 1][1] if i + 1 < len(seq) else None
        if t and t != nxt:
            end = spans[i][1]
            out.append((end, t, i + 1 < len(seq) and "\n" not in text[end:spans[i + 1][0]]))
    return out


def day_title(day, today):
    d = dt.date.fromisoformat(day)
    s = "%d %s, %s" % (d.day, MONTHS[d.month - 1], DAYS[d.weekday()])
    return s + " · сегодня" if day == today else s


class Win(pa.Win):
    def __init__(self, dlg):
        super().__init__(dlg)
        self.remove(self.area)
        self.add(dlg.body(self.area))


class Holst(pa.Dialog):
    def __init__(self, pane="holst", test=False, style=None):
        self.conn = hublib.connect()
        self.pane, self.mode, self.caret = pane, "insert", pane == "later"
        self.today = self.day = G.today(self.conn).isoformat()
        self.names, self.ids, self.dates = [], [], {}
        self.undo_text, self.redo_text = [], []
        self.undo_rows, self.redo_rows = [], []        # ("del"|"add", строка базы)
        self.seq, self.spans, self.gone, self.labels = [], [], {}, []   # см. retime
        self.times_dirty = False
        self.saved = self.base = self.stamp = self.chord = ""
        self.timer, self.loading = 0, False
        self.pause_id, self.last_kind, self.last_end = 0, "", -1   # шаги отмены по словам, см. on_insert
        self.tv = self.sw = self.buf = self.more = None
        self.load_list()
        pa.preset_dates = lambda name, short=False: self.dates.get(name, "")
        super().__init__(self.names, test=test, style=style)
        if not test:
            self.focus(pane)
            GLib.timeout_add(LIST_MS, self.on_list_timer)

    def apply_style(self, style):
        super().apply_style(style)
        geometry(self.style)

    # ── вид Холста: Gtk.TextView поверх рисунка ────────────────────────────
    def body(self, area):
        ov = Gtk.Overlay()
        ov.add(area)
        tv = self.tv = Gtk.TextView()
        tv.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        tv.set_accepts_tab(True)
        tv.set_left_margin(MARGIN)
        tv.set_right_margin(SIDE)
        tv.set_pixels_inside_wrap(pa.LINE - pa.PX + 3)
        tv.set_pixels_below_lines(pa.LINE - pa.PX + 3)
        tv.override_font(self.fd)
        tv.get_style_context().add_class("holst")
        tv.connect("button-press-event", self.on_text_press)
        tv.connect_after("draw", self.draw_stamps)
        css = Gtk.CssProvider()
        css.load_from_data(("""
textview.holst, textview.holst text { background-color: transparent; color: %s; caret-color: %s; }
textview.holst text selection { background-color: %s; }
scrolledwindow.holst scrollbar, scrolledwindow.holst scrollbar trough {
    background: transparent; border: none; box-shadow: none; }
scrolledwindow.holst scrollbar { min-width: 10px; padding: 0; }
scrolledwindow.holst scrollbar slider { min-width: 6px; min-height: 40px; margin: 2px;
    border: none; border-radius: %dpx; background-color: %s; }
scrolledwindow.holst scrollbar slider:hover, scrolledwindow.holst scrollbar slider:active {
    background-color: %s; }
""" % (hexcol(self.C["text"]), hexcol(self.C["accent"]), hexcol(self.C["sel_bg"]),
       0 if self.style == "skeet" else 3, hexcol(self.C["accent"]), hexcol(self.C["text"]))).encode())
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), css,
                                                 Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        sw = self.sw = Gtk.ScrolledWindow()
        # EXTERNAL, а не NEVER: при NEVER ширина рамки идёт за шириной текста, текст занимает её
        # и рамка растёт с каждым знаком — строка уходит за край окна (01.11.2026)
        sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.AUTOMATIC)
        sw.set_overlay_scrolling(False)                # ползунок виден всегда, пока текст не влез
        sw.get_style_context().add_class("holst")
        sw.set_size_request(pa.CW - 2, PAGE_Y + PAGE_H - TEXT_Y - 2)
        sw.set_halign(Gtk.Align.START)
        sw.set_valign(Gtk.Align.START)
        sw.set_margin_start(pa.X0 + 1 + pa.RING)
        sw.set_margin_top(TEXT_Y + pa.RING)
        sw.add(tv)
        ov.add_overlay(sw)
        more = self.more = Gtk.DrawingArea()           # «ниже ещё текст»: над нижним краем листа
        more.set_size_request(pa.CW - 16, MORE_H)
        more.set_halign(Gtk.Align.START)
        more.set_valign(Gtk.Align.START)
        more.set_margin_start(pa.X0 + 1 + pa.RING)
        more.set_margin_top(PAGE_Y + PAGE_H - 1 - MORE_H + pa.RING)
        more.connect("draw", self.draw_more)
        ov.add_overlay(more)
        ov.set_overlay_pass_through(more, True)
        adj = sw.get_vadjustment()
        adj.connect("changed", self.on_scrolled)
        adj.connect("value-changed", self.on_scrolled)
        self.buf = tv.get_buffer()
        self.make_tags()
        self.buf.connect("changed", self.on_changed)
        self.buf.connect("insert-text", self.on_insert)
        self.buf.connect("delete-range", self.on_delete)
        self.load_page(self.day)
        return ov

    # ── разметка как в Obsidian: текст тот же, меняется только вид ─────────
    def make_tags(self):
        C, px = self.C, pa.PX
        text, acc, dim = hexcol(C["text"]), hexcol(C["accent"]), hexcol(C["dim"])
        white = hexcol(cw.mix(C["text"], (1, 1, 1), 0.5))
        tag = self.buf.create_tag
        tag("h1", font_desc=self.sized(2), foreground=white, pixels_above_lines=14, pixels_below_lines=6)
        tag("h2", font_desc=self.sized(1.5), foreground=acc, pixels_above_lines=12, pixels_below_lines=4)
        tag("h3", foreground=acc, weight=Pango.Weight.BOLD, pixels_above_lines=8)
        tag("mark", foreground=dim)
        tag("bullet", foreground=acc)
        tag("bold", foreground=white, weight=Pango.Weight.BOLD)
        tag("italic", style=Pango.Style.ITALIC)
        tag("code", foreground=acc, background=hexcol(C.get("field_l") or C.get("field") or T["st_dark"]))
        tag("link", foreground=acc, underline=Pango.Underline.SINGLE)
        tag("quote", foreground=dim, left_margin=MARGIN + 3 * px // 2)
        tag("done", foreground=dim, strikethrough=True)
        for n in range(1, LIST_MAX + 1):               # перенос под текст пункта, а не под маркер
            tag("list%d" % n, left_margin=MARGIN + n * pa.ADV, indent=-n * pa.ADV)
        self.stamp_fd = self.sized(0.5)                # родной размер пиксельного шрифта: чётко
        self.stamp_w = 5 * pa.ADV // 2
        tag("gap", letter_spacing=(self.stamp_w + 2 * STAMP_GAP) * Pango.SCALE)   # место под метку

    def sized(self, k):
        """Шрифт в k раз крупнее текста: кратный размер, иначе пиксельный шрифт поплывёт."""
        fd = self.fd.copy()
        fd.set_absolute_size(k * pa.PX * Pango.SCALE)
        return fd

    def span(self, name, a, b):
        self.buf.apply_tag_by_name(name, self.buf.get_iter_at_offset(a), self.buf.get_iter_at_offset(b))

    def decorate(self):
        buf = self.buf
        buf.remove_all_tags(buf.get_start_iter(), buf.get_end_iter())
        at = 0
        for line in self.text_now().split("\n"):
            self.decorate_line(line, at)
            at += len(line) + 1
        for end, _t, inside in self.labels:
            if inside:
                self.span("gap", end, end + 1)

    def decorate_line(self, line, at):
        m = HEAD_RE.match(line)
        if m:
            self.span("h%d" % min(3, len(m.group(1))), at, at + len(line))
            self.span("mark", at, at + m.end(1))
            return
        m = TASK_RE.match(line) or LIST_RE.match(line)
        if m:
            indent = len(m.group(1))
            self.span("list%d" % min(LIST_MAX, m.end()), at, at + len(line))
            self.span("bullet", at + indent, at + m.end())
            if m.re is TASK_RE and m.group(2) in "xXхХ":
                self.span("done", at + m.end(), at + len(line))
        elif line.startswith(">"):
            self.span("quote", at, at + len(line))
        elif line.strip() in ("---", "***"):
            self.span("mark", at, at + len(line))
        for rx, name, cut in INLINE:
            for m in rx.finditer(line):
                self.span(name, at + m.start(), at + m.end())
                if cut:
                    self.span("mark", at + m.start(), at + m.start() + cut)
                    self.span("mark", at + m.end() - cut, at + m.end())

    # ── метки времени: только рисунок, в тексте их нет ─────────────────────
    def retime(self, stamp):
        """Сверить предложения с прошлым разбором; stamp — новое получает текущую минуту."""
        text = self.text_now()
        spans = [(m.start(), m.start() + len(m.group().rstrip())) for m in SENT_RE.finditer(text)]
        new = [text[a:b] for a, b in spans]
        seq = align(self.seq, new, time.strftime("%H:%M") if stamp else None, self.gone)
        if stamp and seq != self.seq:
            self.times_dirty = True
        self.seq, self.spans = seq, spans
        self.labels = stamps(text, seq, spans)

    def load_times(self, day):
        try:
            with open(TIMES, encoding="utf-8") as f:
                self.gone = json.load(f).get(day, {})
        except (OSError, ValueError, AttributeError):
            self.gone = {}
        self.seq, self.times_dirty = [], False

    def save_times(self):
        """Файл общий на все дни; повреждённый заменяется: это подписи, а не сами мысли."""
        if not self.times_dirty:
            return
        try:
            with open(TIMES, encoding="utf-8") as f:
                all_days = json.load(f)
        except (OSError, ValueError):
            all_days = {}
        day = {}
        for s, t in self.seq:
            if t:
                day.setdefault(s, []).append(t)
        all_days[self.day] = day
        try:
            with open(TIMES + ".tmp", "w", encoding="utf-8") as f:
                json.dump(all_days, f, ensure_ascii=False)
            os.replace(TIMES + ".tmp", TIMES)
            self.times_dirty = False
        except OSError:
            pass

    def draw_stamps(self, tv, cr):
        if not self.labels or not Gtk.cairo_should_draw_window(cr, tv.get_window(Gtk.TextWindowType.TEXT)):
            return False
        view = tv.get_visible_rect()
        lay = PangoCairo.create_layout(cr)
        PangoCairo.context_set_font_options(lay.get_context(), self.fo)
        lay.set_font_description(self.stamp_fd)
        cr.set_source_rgba(*self.C["dim"][:3], 0.85)
        for end, t, _inside in self.labels:
            r = tv.get_iter_location(self.buf.get_iter_at_offset(end))
            if r.y + r.height < view.y or r.y > view.y + view.height:
                continue
            lay.set_text(t, -1)
            x, y = tv.buffer_to_window_coords(Gtk.TextWindowType.WIDGET, r.x, r.y + r.height)
            cr.move_to(x + STAMP_GAP, y - lay.get_pixel_size()[1] - 2)
            PangoCairo.show_layout(cr, lay)
        return False

    def on_scrolled(self, *_a):
        if self.more is not None:
            self.more.queue_draw()

    def lines_below(self):
        """Сколько строк экрана не влезло ниже: 0 — текст виден до конца."""
        adj = self.sw.get_vadjustment()
        left = adj.get_upper() - adj.get_value() - adj.get_page_size()
        return math.ceil(left / (pa.LINE + 3)) if left > 4 else 0

    def draw_more(self, w, cr):
        """Лист плавно уходит вниз к стрелке: без этого обрез выглядит концом."""
        if self.lines_below():
            ww, hh = w.get_allocated_width(), w.get_allocated_height()
            col = self.C.get("field") or T["st_dark"]
            g = cairo.LinearGradient(0, 0, 0, hh)
            g.add_color_stop_rgba(0, col[0], col[1], col[2], 0)
            g.add_color_stop_rgba(0.7, col[0], col[1], col[2], 0.96)
            g.add_color_stop_rgba(1, col[0], col[1], col[2], 1)
            cr.set_source(g)
            cr.rectangle(0, 0, ww, hh)
            cr.fill()
            lay = self.layout(cr, "▼")
            tw, th = lay.get_pixel_size()
            cr.set_source_rgba(*self.C["accent"][:3], 1)
            cr.move_to((ww - tw) // 2, hh - th - 3)
            PangoCairo.show_layout(cr, lay)
        return False

    def text_now(self):
        return self.buf.get_text(self.buf.get_start_iter(), self.buf.get_end_iter(), True)

    def set_text(self, text, offset=None):
        self.loading = True
        self.buf.set_text(text)
        self.loading = False
        self.retime(False)
        self.decorate()
        at = self.buf.get_end_iter() if offset is None else self.buf.get_iter_at_offset(offset)
        self.buf.place_cursor(at)
        self.redraw()

    def cursor(self):
        return self.buf.get_iter_at_mark(self.buf.get_insert())

    # ── куда идёт ввод ─────────────────────────────────────────────────────
    def in_list(self):
        return self.pane == "later" and self.mode == "normal"

    def focus(self, pane, mode="insert"):
        """Куда идут клавиши: Холст или Потом; в Потом insert — поле, normal — сам список."""
        self.commit()
        self.pane, self.mode, self.chord = pane, mode, ""
        self.caret = pane == "later" and mode == "insert"
        if mode == "insert":
            self.sel = -1
        if self.tv is not None:
            if pane == "holst":
                self.tv.grab_focus()
            else:
                self.win.set_focus(None)
        self.redraw()

    def enter_list(self):
        """С поля вниз, на первую строку; пустой список — остаться в поле: выбирать нечего."""
        if self.names:
            self.focus("later", "normal")
            self.pick(0)

    def pick(self, i):
        """Только выбор строки: то, что набрано в поле, остаётся до возврата в него."""
        if self.names:
            self.sel = max(0, min(len(self.names) - 1, i))
            self.reveal()
            self.redraw()

    def press(self, pane):
        """Нажали клавишу окна: ввод уже здесь — закрыть, иначе перевести его сюда."""
        if pane == self.pane:
            self.finish("")
        else:
            self.focus(pane)

    # ── Холст: страница дня ────────────────────────────────────────────────
    def load_page(self, day):
        self.day = day
        self.saved = self.base = G.holst_page(day)
        self.undo_text = []
        self.redo_text = []
        self.last_kind, self.last_end = "", -1
        self.load_times(day)
        self.set_text(self.saved)

    def page(self, d):
        self.save()
        days = sorted(set(G.holst_days()) | {self.today})
        i = days.index(self.day) + d if self.day in days else len(days) - 1
        if 0 <= i < len(days):
            self.load_page(days[i])
            self.undo_rows.clear()                     # шаги отмены списка — про строки того дня
            self.redo_rows.clear()
            self.scroll = 0
            self.reload_list()
            if self.in_list() and not self.names:
                self.focus("later")
        self.redraw()

    # Шаги отмены (04.11.2026, «Ctrl+Z, Ctrl+Shift+Z работают неправильно»): раньше снимок был
    # только при смене поля — Ctrl+Z стирал всё набранное с открытия окна разом. Теперь шаг —
    # слово: снимок перед пробелом/Enter после слова, при смене набор⇄удаление, при прыжке курсора
    # и после паузы UNDO_PAUSE_MS.
    def on_insert(self, _b, it, text, _n):
        if self.loading:
            return
        pos = it.get_offset()
        prev = self.text_now()[pos - 1:pos] if pos > 0 else ""
        if (self.last_kind != "ins" or pos != self.last_end
                or (text[:1].isspace() and prev and not prev.isspace()) or len(text) > 1):
            self.commit()
        self.last_kind, self.last_end = "ins", pos + len(text)

    def on_delete(self, _b, start, end):
        if self.loading:
            return
        a, b = start.get_offset(), end.get_offset()
        if self.last_kind != "del" or self.last_end not in (a, b):
            self.commit()
        self.last_kind, self.last_end = "del", a

    def on_pause(self):
        self.pause_id = 0
        self.commit()
        self.last_kind = ""
        return False

    def on_changed(self, _b):
        if not self.loading:
            if self.pause_id:
                GLib.source_remove(self.pause_id)
            self.pause_id = GLib.timeout_add(UNDO_PAUSE_MS, self.on_pause)
            if self.timer:
                GLib.source_remove(self.timer)
            self.timer = GLib.timeout_add(SAVE_MS, self.on_timer)
            self.retime(True)
            self.decorate()
            self.tv.queue_draw()
            self.redraw()

    def on_timer(self):
        self.timer = 0
        self.save()
        return False

    def save(self):
        if self.buf is None:
            return
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0
        text = self.text_now().strip()
        cur = G.holst_page(self.day)
        if cur != self.saved:                  # пока окно открыто, дописали из бота или в Obsidian
            mine = set(self.saved.split("\n")) | set(text.split("\n"))
            new = [s for s in cur.split("\n") if s.strip() and s not in mine]
            if new:
                text = "\n".join([text] + new).strip()
                self.set_text(text, self.cursor().get_offset())
        if text != cur:
            try:
                G.holst_save(self.conn, text, self.day)
                self.stamp = "записано " + dt.datetime.now().strftime("%H:%M")
            except OSError:
                with open(os.path.join(RUN, "holst-unsaved.md"), "w", encoding="utf-8") as f:
                    f.write(text)
                self.stamp = "не записано"
        self.saved = text
        self.save_times()
        self.redraw()

    def commit(self):
        """Снимок для отмены: всё, что изменилось с прошлого снимка."""
        if self.tv is not None:
            t = self.text_now()
            if t != self.base:
                self.undo_text.append(self.base)
                del self.undo_text[:-UNDO_MAX]
                self.redo_text.clear()
                self.base = t

    def undo(self):
        self.step(self.undo_text, self.redo_text, self.undo_rows, self.redo_rows)

    def redo(self):
        self.step(self.redo_text, self.undo_text, self.redo_rows, self.undo_rows)

    def step(self, texts, back_texts, rows, back_rows):
        """Шаг по истории: откуда берём и куда кладём обратный шаг. В списке обратное к «del» — «add»."""
        if self.pane == "later":
            if rows:
                op, r = rows.pop()
                if op == "del":
                    G.put_back(self.conn, r)
                else:
                    G.remove(self.conn, r["id"])
                back_rows.append(("add" if op == "del" else "del", r))
                self.reload_list()
                if self.mode == "normal" and op == "del":
                    self.pick(self.ids.index(r["id"]))
            return
        self.commit()
        if self.pause_id:
            GLib.source_remove(self.pause_id)
            self.pause_id = 0
        self.last_kind, self.last_end = "", -1
        if texts:
            old = self.base
            back_texts.append(old)
            self.base = texts.pop()
            self.set_text(self.base, changed_at(old, self.base))
            self.on_changed(None)
            if self.pause_id:                          # шаг истории — не повод для снимка
                GLib.source_remove(self.pause_id)
                self.pause_id = 0

    def on_list_timer(self):
        was = list(self.ids)
        self.load_list()
        if self.ids != was:
            self.sel = min(self.sel, len(self.names) - 1)
            self.reveal()
            self.redraw()
        return True

    def load_list(self):
        G.later_sync(self.conn)
        rows = G.later_list(self.conn, self.day)
        self.ids = [r["id"] for r in rows]
        self.names[:] = [r["note"] for r in rows]
        self.dates = {r["note"]: pa._when(r["ts"]) for r in rows}

    def reload_list(self):
        self.load_list()
        self.sel = min(self.sel, len(self.names) - 1)
        self.reveal()
        self.redraw()

    def submit(self):
        text = self.entry.strip()
        if text:
            gid = G.later_add(self.conn, text, day=self.day)
            self.undo_rows.append(("add", G.get(self.conn, gid)))
            self.redo_rows.clear()
            self.set_entry("")
            self.load_list()
            self.sel = len(self.names) - 1
            self.reveal()
            self.sel = -1
            self.redraw()

    def pick(self, i):
        if self.names:
            self.sel = max(0, min(len(self.names) - 1, i))
            self.reveal()
            self.redraw()

    def row_step(self, d):
        """Строка вниз/вверх; вверх с первой — в поле."""
        if self.sel <= 0 and d < 0:
            self.focus("later")
        else:
            self.pick(self.sel + d)

    def drop_row(self):
        if 0 <= self.sel < len(self.ids):
            self.undo_rows.append(("del", G.remove(self.conn, self.ids[self.sel])))
            self.redo_rows.clear()
            self.reload_list()
            if not self.names:
                self.focus("later")

    def key_later(self, code, shift):
        """Клавиши на строках списка."""
        chord, self.chord = self.chord, ""
        if code == K_G:
            if shift:
                self.pick(len(self.names) - 1)
            elif chord == "g":
                self.focus("holst")
                self.buf.place_cursor(self.buf.get_start_iter())
            else:
                self.chord = "g"
        elif code == K_D:
            if chord == "d":
                self.drop_row()
            else:
                self.chord = "d"
        elif code == K_J:
            self.row_step(1)
        elif code == K_K:
            self.row_step(-1)
        elif code in (K_I, K_A):
            self.focus("later")
        elif code == K_U:
            self.redo() if shift else self.undo()
        elif code == K_X:
            self.drop_row()

    # ── клавиши и мышь ─────────────────────────────────────────────────────
    def on_key(self, w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        if ctrl and code in (K_J, K_K, K_Q, K_H, K_L, K_S, K_Z, K_R):
            if code == K_J:
                self.row_step(1) if self.in_list() else self.enter_list() if self.pane == "later" \
                    else self.focus("later")
            elif code == K_K:
                if self.in_list():
                    self.row_step(-1)
                elif self.pane == "later":
                    self.focus("holst")
            elif code == K_Q:
                self.finish("")
            elif code == K_Z:
                self.redo() if shift else self.undo()  # Ctrl+Shift+Z — повтор, как везде
            elif code == K_R:
                self.redo()
            else:
                self.save() if code == K_S else self.page(-1 if code == K_H else 1)
            return True
        if k == Gdk.KEY_Escape:
            self.finish("")
            return True
        if self.in_list():
            code = ARROWS.get(k, code)
            if ctrl and code == K_E:
                self.focus("later")
            elif code == K_Q:
                self.finish("")
            elif not ctrl:
                self.key_later(code, shift)
            return True
        return super().on_key(w, ev) if self.pane == "later" else False

    def on_text_press(self, _w, _ev):
        if self.pane != "holst":
            self.focus("holst")
        return False

    def on_press(self, _w, ev):
        x, y = ev.x - pa.RING, ev.y - pa.RING
        if ev.button != 1:
            return True
        if self.inside(self.zone_close(), x, y):
            self.finish("")
        elif pa.SEARCH_Y <= y < pa.SEARCH_Y + pa.SEARCH_H:
            self.focus("later")
        else:
            i = self.row_at(x, y)
            if i is not None:
                self.focus("later", "normal")
                self.pick(i)
        return True

    def finish(self, name):
        self.save()
        try:
            os.remove(PIDFILE)
        except OSError:
            pass
        os._exit(0)

    # ── рисование ──────────────────────────────────────────────────────────
    def paper(self, cr, x, y, w, h):
        """Лист — той же заливкой, что поле ввода своего стиля."""
        C, st = self.C, self.style
        if st == "skeet":
            self.rect_fill(cr, x, y, w, h, C["field"])
            self.rect_line(cr, x, y, w, h, C["gline"])
        elif st == "beta":
            self.rect_fill(cr, x, y, w, h, C["field"])
            self.rect_line(cr, x, y, w, h, C["line"])
        else:
            self.rect_fill(cr, x, y, w, h, T["st_dark"], 0.5)
            self.rect_line(cr, x, y, w, h, T["st_top"])

    def draw_group(self, cr):
        """Группа «Потом»: рамка с подписью в разрыве, как группы Настроек в Skeet. Она же черта
        между мыслями и списком; акцентом, пока клавиши здесь."""
        C, x, y, w = self.C, pa.X0, SEP_Y, pa.CW
        h = FOOT_Y - 8 - y
        on = self.pane == "later"
        line = C.get("gline") or C.get("line") or T["st_top"]
        self.rect_line(cr, x, y, w, h, C["accent"] if on else line, 1 if on else 0.9)
        if "gdark" in C:
            self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["gdark"])
        tw = self.layout(cr, "Потом").get_pixel_size()[0]
        self.cut_frame(cr, x + 12, y - 1, tw + 12, 3)
        self.text(cr, "Потом", x + 18, y - pa.PX // 2 - 1, C["accent"] if on else C["text"])

    def cut_frame(self, cr, x, y, w, h):
        """Разрыв рамки под подпись: кусок фона окна."""
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        cr.set_source_rgb(*self.C["win_bg"])
        cr.paint()
        if self.dots is not None:
            cr.set_source(self.dots)
            cr.paint()
        cr.restore()

    def draw_field(self, cr):
        """Поле preset_ask, но в ширину группы."""
        x0, wide, acc = pa.X0, pa.CW, self.C["accent"]
        pa.X0, pa.CW = pa.LX, pa.LW
        if not self.caret:                  # рамка акцентом — только когда ввод здесь
            self.C["accent"] = self.C.get("gline") or self.C.get("line") or T["st_top"]
        self.draw_entry(cr)
        self.C["accent"] = acc
        pa.X0, pa.CW = x0, wide

    def draw_row(self, cr, name, x, y, w, h, sel, last):
        """Строка списка: квадратик как флажок Skeet, текст, когда записано; черта между строками."""
        C = self.C
        line = C.get("gline") or C.get("line") or T["st_top"]
        if sel and self.in_list():
            self.rect_fill(cr, x, y, w, h, C["sel_bg"])
            self.rect_line(cr, x, y, w, h, line)
            self.rect_fill(cr, x, y, 2, h, C["accent"])
            fg, tail = C["sel_text"], C["sel_dim"]
        else:
            fg, tail = C["text"], C["dim"]
            sel = False
        if not last:
            self.rect_fill(cr, x + 8, y + h, w - 16, 1, line, 0.45)
        b = max(8, pa.PX // 2)
        by = y + (h - b) // 2
        self.rect_fill(cr, x + 10, by, b, b, C["accent"] if sel else C.get("field", T["st_dark"]))
        self.rect_line(cr, x + 10, by, b, b, C["accent"] if sel else line)
        tx, ty = x + 10 + b + 10, y + (h - pa.PX) // 2
        when = self.dates.get(name, "")
        hw = self.layout(cr, when).get_pixel_size()[0] if when else 0
        if when:
            self.text(cr, when, x + w - 12 - hw, ty, tail)
        self.text(cr, name, tx, ty, fg, x + w - 12 - hw - 14 - tx)

    def draw_page(self, cr):
        C = self.C
        self.paper(cr, pa.X0, PAGE_Y, pa.CW, PAGE_H)
        self.title(cr, day_title(self.day, self.today), pa.X0 + 1 + MARGIN, PAGE_Y + 12)
        hint = "Ctrl+H/L — дни"
        self.text(cr, hint, pa.X0 + pa.CW - 17 - self.layout(cr, hint).get_pixel_size()[0], PAGE_Y + 12,
                  C["dim"], alpha=0.6)
        if self.buf is not None and not self.buf.get_char_count():
            self.text(cr, PAPER, pa.X0 + 1 + MARGIN, TEXT_Y, C["dim"], alpha=0.6)

    def title(self, cr, s, x, y):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.sized(1.5))
        lay.set_text(s, -1)
        cr.set_source_rgb(*self.C["text"][:3])
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    def draw_footer(self, cr):
        C = self.C
        hint = HINTS["holst" if self.pane == "holst" else "list" if self.in_list() else "field"]
        hw = self.layout(cr, hint).get_pixel_size()[0]
        self.text(cr, hint, pa.X0 + pa.CW - hw, FOOT_Y, C["dim"], alpha=0.8)
        sw = self.layout(cr, self.stamp).get_pixel_size()[0]
        if self.stamp and sw + 26 <= pa.CW - hw:
            self.text(cr, self.stamp, pa.X0, FOOT_Y, C["dim"])

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
        self.draw_page(cr)
        self.draw_group(cr)
        self.draw_field(cr)
        cr.save()
        cr.rectangle(pa.LX, pa.LIST_Y, pa.LW, pa.LIST_H)
        cr.clip()
        self.draw_list(cr)
        cr.restore()
        self.draw_footer(cr)


pa.Win = Win


def signals(dlg):
    try:
        from gi.repository import GLibUnix
        add = GLibUnix.signal_add
    except ImportError:                               # старый PyGObject без GLibUnix
        add = GLib.unix_signal_add

    def on(pane):
        return lambda *_a: dlg.press(pane) or True

    for sig in (signal.SIGINT, signal.SIGTERM):
        add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: dlg.finish("") or False)
    for pane, sig in SIGNALS.items():
        add(GLib.PRIORITY_DEFAULT, sig, on(pane))
    for n in PENDING:                                 # нажали ещё раз, пока окно открывалось
        dlg.press("holst" if n == SIGNALS["holst"] else "later")


def main():
    dlg = Holst(TAB)
    pa.sound("menu")
    signals(dlg)
    Gtk.main()


if __name__ == "__main__":
    main()
