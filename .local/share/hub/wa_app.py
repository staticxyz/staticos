#!/usr/bin/env python3
"""wa_app — окно отложенных сообщений WhatsApp (15.10.2026). Просьба: «приложение с понятным
интерфейсом и вводом сообщения вместе с датой и временем… стиль должен повторять интерфейс
системы… перемещение курсором и изменение размера».

Вид и рамка — как у hub_app (Default/Skeet/Beta по ~/.config/hypr/state/settings-skin, цвета
из обоев, смена стиля — на лету). Записи те же, что у `wa` в терминале и /wa в Telegram;
отправляет hubd в срок (опоздание до часа — уйдёт, больше — спросит).

Сверху — форма: Кому (поиск по имени/номеру, в любой раскладке), Сообщение (Enter — новая
строка), Дата и Время (можно вписать «завтра», «пт», «18:30»), быстрые сроки.
Три режима (15.10, просьба: «Ctrl+E режим как сейчас, и режим перехода по полям/кнопкам на
j/k, h/l… Ctrl+J/K как в nvim на очередь и обратно»):
  ВВОД   — печать в поле. В Дате: j/k и h/l (латиница) или ↑/↓ — ±день, с Shift — ±неделя;
           во Времени: j/k — ±15 мин, h/l — ±1 мин, с Shift — ±час. Tab — следующее поле.
  ВЫБОР  — j/k/h/l (или стрелки) по полям и кнопкам (j с нижнего — в очередь), Enter/пробел — нажать кнопку или
           писать в поле, Shift+H — история. Ctrl+E — ВВОД ⇄ ВЫБОР, Esc из ВВОДА — в ВЫБОР, из ВЫБОРА — закрыть.
  ОЧЕРЕДЬ — Ctrl+J (если не пусто; Ctrl+K — обратно): j/k — строка, h/l — её кнопки,
           Enter — нажать (без кнопки — изменить), dd/Del/Backspace — убрать (ждущее — отменить,
           ушедшее — убрать из истории; в базе остаётся), u — вернуть, Ctrl+R — повторить,
           Shift+H — история.
Ctrl+D/U (ВЫБОР, ОЧЕРЕДЬ) — как в nvim: полэкрана очереди; в форме — к нижнему/верхнему пункту.
Ctrl+Enter / Ctrl+S — запланировать из любого режима. «история» (щелчок, Shift+H) — отправленные и отменённые; выбор помнится в ~/.config/hub/wa-history.
Перетаскивание — за пустое место, размер — за край или правый нижний угол.
Вход — по паролю sudo (hub_auth.py): один раз на 15 минут, общий с `wa` в терминале; окно само
запирается через 10 минут без дела.

    wa_app.py                  окно (второй запуск поднимает открытое)
    wa_app.py --shot F [style=skeet|beta|default w= h= sel=N]   PNG без окна
"""
import datetime as dt
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import hub_auth  # noqa: E402
import hub_app as A  # noqa: E402  стиль, рамка, кнопки, разбор дат — общие с окном hub
import title_strip  # noqa: E402  (путь к ~/.config/hypr/scripts добавил hub_app)
import hublib as H  # noqa: E402
import hubwa as W  # noqa: E402
from hub_app import (Gdk, Gio, GLib, Gtk, PangoCairo, cairo, colors, edit_line, fmt_date,  # noqa: E402
                     mix, parse_date, parse_time, rel_day, style_name, with_cursor, Painter)

APP_ID = "com.jarvis.wa"
SIZE_FILE = os.path.expanduser("~/.config/hub/wa-size")
MIN_W, MIN_H = 480, 600
PAD, ROW_H, PX = A.PAD, A.ROW_H, A.PX
FIELDS = ("to", "text", "date", "time")
LABEL = {"to": "Кому", "text": "Сообщение", "date": "Дата", "time": "Время"}
CHIPS = (("+1 ч", "h1"), ("в 20:00", "t20"), ("завтра 9:00", "m9"))
# «история» видна или нет — запоминается (15.10, просьба: «этот выбор тоже должен запоминаться»)
HIST_FILE = os.path.expanduser("~/.config/hub/wa-history")
HIST_N = 40
MARK = {"pending": "◷", "sending": "…", "ask": "!", "sent": "✓", "cancelled": "✕"}

_STACK = [None, False]


def stack_on():
    """Режим «стопка» включён? Тогда «×» не рисуется: закрывает полоса stack_bars.py
    (21.10.2026, «дублируются кнопки»). Файл перечитывается только при смене mtime."""
    p = os.path.expanduser("~/.config/hypr/state/stack-mode.json")
    try:
        m = os.stat(p).st_mtime
        if m != _STACK[0]:
            _STACK[0], _STACK[1] = m, '"active": true' in open(p).read()
    except OSError:
        _STACK[0], _STACK[1] = None, False
    return _STACK[1]


def fmt_left(secs):
    if secs < 60:
        return "меньше минуты"
    m = int(secs // 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    return " ".join(x for x in ("%d д" % d if d else "", "%d ч" % h if h else "",
                                "%d мин" % m if m and not d else "") if x)


def present_unmin(win):
    """present() окна, свёрнутого в стопке, уводил niri на стол свёрнутых — окно появлялось
    «багованно» (22.10.2026). Такое окно возвращает stack_mode.py unmin (wm.raise_own)."""
    try:
        scripts = os.path.expanduser("~/.config/hypr/scripts")
        if scripts not in sys.path:
            sys.path.append(scripts)
        import wm
        if wm.raise_own():
            return
    except Exception:
        pass
    win.present()


class View:
    """Данные и рисование — без GTK, чтобы --shot рисовал без окна."""
    draw_frame = A.View.draw_frame
    draw_grip = A.View.draw_grip
    button = A.View.button
    buttons = A.View.buttons
    frame_f = A.View.frame_f

    def __init__(self):
        self.style = style_name()
        self.c = colors(self.style)
        self.active = True
        self.maxed = False          # развёрнуто — значок «вернуть» на полосе заголовка
        self.hover = None
        self.hits = []
        self.conn = H.connect()
        self.focus = "to"                         # поле в режиме ВВОД (None — не печатаем)
        self.area = "form"                        # form | queue
        self.nav = ("field", "to")                # где рамка в режиме ВЫБОР
        self.nav_rows, self.qkeys, self.qbtn = [], [], None
        self.to_buf, self.to = "", None          # строка поиска / выбранный контакт {jid,name,phone}
        self.text = ""
        self.f_date, self.f_time = "", ""
        self.cur = {k: None for k in FIELDS}      # курсор в каждом поле (None — в конце)
        self.drop, self.drop_sel = [], 0          # подсказки контактов
        self.editing = None                       # id сообщения, которое правим
        self.rows, self.sel, self.scroll = [], 0, 0
        try:
            self.show_hist = open(HIST_FILE).read().strip() != "off"
        except OSError:
            self.show_hist = True                  # по умолчанию видно, что уже ушло
        self.armed = None                         # (действие, id, до когда) — «точно?»
        self.undo_st, self.redo_st = [], []       # («hide»|«cancel», id) — u / Ctrl+R, как в nvim
        self.msg, self.msg_until, self.msg_err = "", 0, False
        self.contacts_ok = None
        self.locked = not hub_auth.ticket_ok()
        self.pw, self.pw_busy, self.pw_msg = bytearray(), False, ""
        self.tries = hub_auth.tries_left() if self.locked else 0
        self.load()

    def lock(self):
        self.locked, self.pw_busy, self.pw_msg = True, False, ""
        hub_auth.wipe(self.pw)
        self.pw = bytearray()
        self.tries = hub_auth.tries_left()

    # ── данные ──
    def reload_style(self):
        self.style = style_name()
        self.c = colors(self.style)

    def load(self):
        keep = self.rows[self.sel]["id"] if self.rows and self.sel < len(self.rows) else None
        rows = list(W.queue(self.conn))
        if self.show_hist:                         # история — отправленные и отменённые, свежие сверху
            rows += list(W.history(self.conn, HIST_N))
        self.rows = rows
        ids = [r["id"] for r in rows]
        self.sel = ids.index(keep) if keep in ids else min(self.sel, max(0, len(rows) - 1))

    # ── убрать / вернуть (15.10, просьба: «очистить запись по dd или backspace/delete, вернуть на u и ctrl+r») ──
    def remove(self):
        """Выбранная строка: ждущее — отменить, отправленное/отменённое — убрать из истории (в базе остаётся)."""
        if not self.rows or self.sel >= len(self.rows):
            return
        r = self.rows[self.sel]
        if r["status"] in ("pending", "ask"):
            op, ok = "cancel", W.cancel(self.conn, r["id"])
        elif r["status"] in ("sent", "cancelled"):
            op, ok = "hide", W.hide(self.conn, r["id"])
        else:
            return self.flash("уходит прямо сейчас — не трогаю", True)
        if not ok:
            self.load()
            return self.flash("уже не ждёт", True)
        self.undo_st.append((op, r["id"]))
        self.redo_st.clear()
        self.armed, self.qbtn = None, None
        self.load()
        if not self.rows:
            self.area = "form"
        self.flash(("отменено" if op == "cancel" else "убрано из истории") + " · u — вернуть")

    def _apply(self, op, mid, back):
        if op == "hide":
            return W.hide(self.conn, mid, not back)
        return W.restore(self.conn, mid) if back else W.cancel(self.conn, mid)

    def undo(self, redo=False):
        src, dst = (self.redo_st, self.undo_st) if redo else (self.undo_st, self.redo_st)
        while src:
            op, mid = src.pop()
            if self._apply(op, mid, not redo):
                dst.append((op, mid))
                if not self.show_hist and (op == "hide" or redo):
                    self.flash("сделано · запись в скрытой истории (Shift+H)")
                else:
                    self.flash({("hide", False): "запись возвращена", ("cancel", False): "снова ждёт",
                                ("hide", True): "убрано снова", ("cancel", True): "отменено снова"}[(op, redo)])
                self.load()
                ids = [r["id"] for r in self.rows]
                if mid in ids:
                    self.sel, self.area, self.qbtn = ids.index(mid), "queue", None
                elif not self.rows:
                    self.area = "form"
                return
            # запись успела измениться (ушла, отменили из TG) — этот шаг пропускаем
        self.flash("нечего " + ("повторять" if redo else "возвращать"), True)

    def toggle_hist(self):
        """История: показать/скрыть (скрыта — только очередь). Выбор пишется в HIST_FILE."""
        self.show_hist = not self.show_hist
        self.qbtn = None
        self.load()
        try:
            os.makedirs(os.path.dirname(HIST_FILE), exist_ok=True)
            with open(HIST_FILE, "w") as f:
                f.write("on\n" if self.show_hist else "off\n")
        except OSError:
            pass
        if not self.rows and self.area == "queue":
            self.area = "form"
        self.flash("история показана" if self.show_hist else "история скрыта — только очередь")

    def flash(self, text, err=False, secs=4):
        self.msg, self.msg_until, self.msg_err = text, time.monotonic() + secs, err

    def search(self):
        q = self.to_buf.strip()
        self.drop = W.search(q, 6) if q else []
        self.drop_sel = 0

    def due(self):
        """→ (epoch, '') или (None, что не так)."""
        if not self.f_date.strip():
            return None, "укажите дату"
        d = parse_date(self.f_date)
        if d is None:
            return None, "не понял дату"
        if not self.f_time.strip():
            return None, "укажите время"
        t = parse_time(self.f_time)
        if t is None:
            return None, "не понял время"
        ts = int(dt.datetime.combine(d, dt.time(*t)).timestamp())
        if ts < H.now() - 60:
            return None, "это время уже прошло"
        return ts, ""

    def target(self):
        if self.to:
            return self.to
        ph = W.phone_of(self.to_buf)
        return {"jid": ph, "name": ph, "phone": ph} if ph else None

    def preset(self, key):
        ts = W.preset_due(key)
        if ts and ts < H.now():
            ts += 86400                            # «сегодня 20:00» поздно вечером — завтра
        t = dt.datetime.fromtimestamp(ts)
        self.f_date, self.f_time = fmt_date(t.date()), t.strftime("%H:%M")
        self.cur["date"] = self.cur["time"] = None

    def mode(self):
        if self.area == "queue":
            return "queue"
        return "edit" if self.focus else "nav"

    def bump(self, field, how, shift):
        """how: up/down (j/k, ↑/↓) или right/left (l/h). Дата — дни (Shift — недели);
        время — up/down ±15 мин, right/left ±1 мин, с Shift — ±час."""
        sign = 1 if how in ("up", "right") else -1
        if field == "date":
            self.step("date", sign * (7 if shift else 1))
        else:
            self.step("time", sign * (60 if shift else (15 if how in ("up", "down") else 1)))

    def step(self, field, n):
        """Дата — на n дней, время — на n минут."""
        if field == "date":
            d = parse_date(self.f_date) or dt.date.today() - dt.timedelta(days=n)
            d = max(dt.date.today(), d + dt.timedelta(days=n))
            self.f_date = fmt_date(d)
        else:
            t = parse_time(self.f_time)
            if t:
                m = (t[0] * 60 + t[1] + n) % 1440
            else:
                now = dt.datetime.now()
                m = (now.hour * 60 + now.minute + 15) // 15 * 15 % 1440
            self.f_time = "%02d:%02d" % divmod(m, 60)
            if not self.f_date:
                self.f_date = fmt_date(dt.date.today())
        self.cur[field] = None

    def reset_form(self):
        self.to_buf, self.to, self.text, self.f_date, self.f_time = "", None, "", "", ""
        self.cur = {k: None for k in FIELDS}
        self.drop, self.editing, self.focus = [], None, "to"
        self.area, self.nav = "form", ("field", "to")

    def load_form(self, m):
        self.editing = m["id"]
        self.to = {"jid": m["jid"], "name": m["name"], "phone": "+" + m["jid"].split("@")[0].lstrip("+")}
        self.to_buf = self.to["name"]
        self.text = m["text"]
        t = dt.datetime.fromtimestamp(max(m["due"], H.now() + 60) if m["status"] == "ask" else m["due"])
        self.f_date, self.f_time = fmt_date(t.date()), t.strftime("%H:%M")
        self.cur = {k: None for k in FIELDS}
        self.drop, self.focus, self.area = [], "text", "form"

    def submit(self):
        to = self.target()
        if not to:
            self.focus = "to"
            return self.flash("выберите, кому", True)
        if not self.text.strip():
            self.focus = "text"
            return self.flash("пустое сообщение", True)
        ts, err = self.due()
        if not ts:
            self.focus = "time" if "время" in err else "date"
            return self.flash(err, True)
        try:
            if self.editing is not None:
                if not W.edit(self.conn, self.editing, to["jid"], to["name"], self.text.strip(), ts):
                    return self.flash("это сообщение уже не ждёт — не изменено", True)
                note = "✓ изменено: %s, %s" % (to["name"], W.when(ts))
            else:
                W.add(self.conn, to["jid"], to["name"], self.text.strip(), ts, "app")
                note = "✓ запланировано: %s, %s" % (to["name"], W.when(ts))
        except ValueError as e:
            return self.flash("не записал: %s" % e, True)
        self.reset_form()
        self.load()
        self.flash(note)

    def act(self, what, mid):
        """Кнопки строки очереди. Отправить сейчас и отменить — со вторым нажатием."""
        m = W.get(self.conn, mid)
        if m is None:
            return
        if what in ("now", "cancel"):
            a = self.armed
            if not (a and a[0] == what and a[1] == mid and time.monotonic() < a[2]):
                self.armed = (what, mid, time.monotonic() + 3)
                return self.flash("ещё раз — %s" % ("отправить сейчас" if what == "now" else "отменить"))
            self.armed = None
        if what == "edit":
            self.load_form(m)
            return self.flash("правка #%d — Ctrl+Enter сохранить, Esc отмена" % mid)
        if what == "again":
            self.reset_form()
            self.to = {"jid": m["jid"], "name": m["name"], "phone": "+" + m["jid"].split("@")[0].lstrip("+")}
            self.to_buf, self.text, self.focus, self.area = m["name"], m["text"], "date", "form"
            return self.flash("текст скопирован — выберите дату и время")
        ok = {"now": W.send_now, "cancel": W.cancel, "back": W.restore,
              "later": lambda c, i: W.postpone(c, i, 3600)}[what](self.conn, mid)
        self.load()
        self.flash({"now": "✓ уйдёт в ближайшие секунды", "cancel": "✓ отменено (можно вернуть в истории)",
                    "back": "✓ снова ждёт", "later": "✓ отложено на час"}[what] if ok else "уже не ждёт", not ok)

    # ── рисование ──
    def draw(self, cr, w, h):
        self.hits, self.nav_rows, self.qkeys = [], [], []
        p = Painter(cr)
        c, f = self.c, self.frame_f()
        self.draw_frame(p, w, h)
        self.draw_grip(p, w, h, f)
        x0, x1 = PAD + f, w - PAD - f
        # сверху полоса заголовка как у Настроек (title_strip, 29.10.2026); в стопке её рисует stack_bars
        if not stack_on():
            self.hits += title_strip.draw(cr, self.style, f, f, w - 2 * f, "\U000f05a3", "WhatsApp",
                                          self.hover, self.maxed, self.active,
                                          r=0 if c["frame"] == "skeet" else 9)
        y = f + (0 if stack_on() else title_strip.TITLE_H) + 12
        if self.locked:
            return self.draw_lock(p, x0, x1, y, h, f)
        title = "правка #%d" % self.editing if self.editing is not None else "новое сообщение"
        p.text(x0, y, title, c["acc_l"] if self.active else c["text"])
        if self.contacts_ok is False:
            p.text(x1, y, "не привязан: wa login", c["err"], align="r")
        y += 30
        y_to = y
        y = self.field_line(p, x0, x1, y, "to") + 10
        y = self.text_box(p, x0, x1, y) + 10
        y = self.when_row(p, x0, x1, y) + 8
        ts, err = self.due()
        if ts:
            left = ts - H.now()
            line = "Уйдёт %s%s" % (W.when(ts), " · через " + fmt_left(left) if left > 60 else " · сразу")
            p.text(x0, y, line, c["text"], maxw=x1 - x0)
        else:
            p.text(x0, y, "Уйдёт: " + err, c["faint"])
        y += 22
        if self.editing is not None:
            items = [("Сохранить  Ctrl+Enter", "submit", True), ("Отмена", "unedit")]
        else:
            items = [("Запланировать  Ctrl+Enter", "submit", True), ("Очистить", "clear")]
        self.buttons(p, x0, x1, y, items)
        self.nav_rows.append([it[1] for it in items])
        y += 24 + 14
        p.rect(x0, y, x1 - x0, 1, c["line_soft"])
        y += 10
        n = sum(1 for r in self.rows if r["status"] in ("pending", "sending", "ask"))
        p.text(x0, y, "Очередь · %d" % n, c["text"])
        lab = "скрыть историю" if self.show_hist else "история"
        hw = p.text(x1, y, lab, c["text"] if self.hover == "hist" else c["faint"], align="r")
        self.hits.append(((x1 - hw - 4, y - 4, hw + 8, 20), "hist"))
        self.nav_rows.append(["hist"])
        y += 22
        foot = h - f - 16
        self.draw_queue(p, x0, x1, y, foot - 12)
        self.draw_footer(p, x0, x1, foot)
        mode = self.mode()
        if mode == "nav":
            if not any(self.nav in r for r in self.nav_rows):
                self.nav = {"unedit": "clear", "clear": "unedit"}.get(self.nav, ("field", "to"))
            self.ring(p, self.nav)
        elif mode == "queue" and self.qbtn is not None and self.qbtn < len(self.qkeys):
            self.ring(p, self.qkeys[self.qbtn])
        if self.focus == "to" and self.drop and not self.to:
            self.draw_drop(p, x0, x1, y_to + 18 + ROW_H)

    def ring(self, p, key):
        """Рамка «здесь» для режима ВЫБОР и кнопок очереди."""
        for (x, y, w, h), k in self.hits:
            if k == key:
                p.box(x - 2, y - 2, w + 4, h + 4, self.c["acc_l"])
                return

    def draw_lock(self, p, x0, x1, y, h, f):
        c = self.c
        p.text(x0, y, "вход", c["acc_l"] if self.active else c["text"])
        y = max(y + 40, h / 2 - 70)
        p.text((x0 + x1) / 2, y, "Пароль sudo", c["text"], align="c")
        y += 26
        bw = min(300, x1 - x0)
        bx = (x0 + x1 - bw) / 2
        p.rect(bx, y, bw, ROW_H, c["field"])
        p.box(bx, y, bw, ROW_H, c["acc"] if self.tries else c["line_soft"])
        dots = "•" * min(len(self.pw), 28)
        if self.pw_busy:
            shown, col = "проверяю…", c["dim"]
        elif self.tries:
            shown, col = dots + "▏", c["acc_l"]
        else:
            shown, col = "", c["faint"]
        p.text(bx + 8, y + (ROW_H - 16) / 2 + 1, shown, col, maxw=bw - 16)
        y += ROW_H + 12
        if not self.tries:
            # 15.10: «Закройте окно и откройте позже» читалось как «система заблокирована»
            at = hub_auth.retry_at()
            lines, col = ("Система не заблокирована — окно остановилось само:",
                          "третья ошибка подряд заперла бы вход на 10 минут.",
                          ("Новая попытка — в %s, поле откроется само." % time.strftime("%H:%M", time.localtime(at + 5)))
                          if at else "Закройте окно и откройте снова."), c["err"]
        elif self.pw_msg:
            lines, col = (self.pw_msg,), c["err"]
        else:
            lines, col = ("Enter — войти · Esc — закрыть",
                          "пароль помнится %d минут — и для wa в терминале" % (hub_auth.TICKET_SECS // 60)), c["faint"]
        for ln in lines:
            p.text((x0 + x1) / 2, y, ln, col, align="c", maxw=x1 - x0)
            y += 18
        return None

    def field_box(self, p, x, y, w, h, name):
        c = self.c
        on = self.focus == name
        p.rect(x, y, w, h, c["field"])
        p.box(x, y, w, h, c["acc"] if on else (c["line"] if self.hover == ("field", name) else c["line_soft"]))
        self.hits.append(((x, y, w, h), ("field", name)))

    def field_line(self, p, x0, x1, y, name):
        c = self.c
        p.text(x0, y, LABEL[name], c["dim"])
        y += 18
        bh = ROW_H
        self.field_box(p, x0, y, x1 - x0, bh, name)
        self.nav_rows.append([("field", name)])
        ty = y + (bh - 16) / 2 + 1
        if self.to and self.focus != "to":
            w = p.text(x0 + 6, ty, self.to["name"], c["text"], maxw=x1 - x0 - 140)
            p.text(x0 + 14 + w, ty, self.to["phone"], c["faint"])
        elif self.focus == "to":
            p.text(x0 + 6, ty, with_cursor(self.to_buf, self.cur["to"]), c["acc_l"], maxw=x1 - x0 - 12)
            if self.to:
                p.text(x1 - 6, ty, self.to["phone"], c["faint"], align="r")
        else:
            p.text(x0 + 6, ty, self.to_buf or "имя или номер", c["text"] if self.to_buf else c["faint"])
        return y + bh

    def text_box(self, p, x0, x1, y):
        c = self.c
        p.text(x0, y, LABEL["text"], c["dim"])
        n = len(self.text)
        p.text(x1, y, "%d / %d" % (n, W.TEXT_MAX), c["err"] if n > W.TEXT_MAX else c["faint"], align="r")
        y += 18
        maxw = x1 - x0 - 12
        on = self.focus == "text"
        s = with_cursor(self.text, self.cur["text"]) if on else (self.text or "текст сообщения")
        th = p.measure_wrap(s or " ", PX, maxw)
        bh = max(16 * 3, min(16 * 8, th)) + 10
        self.field_box(p, x0, y, x1 - x0, bh, "text")
        self.nav_rows.append([("field", "text")])
        p.cr.save()
        p.cr.rectangle(x0 + 1, y + 1, x1 - x0 - 2, bh - 2)
        p.cr.clip()
        off = max(0, th - (bh - 10))               # длинный текст — видно хвост, где курсор
        p.text_wrap(x0 + 6, y + 5 - off, s, c["acc_l"] if on else (c["text"] if self.text else c["faint"]),
                    PX, maxw)
        p.cr.restore()
        return y + bh

    def when_row(self, p, x0, x1, y):
        c = self.c
        p.text(x0, y, "Когда", c["dim"])
        y += 18
        bh = ROW_H
        x = x0
        row = [("field", "date"), ("field", "time")]
        self.nav_rows.append(row)
        for name, w in (("date", 170), ("time", 64)):
            self.field_box(p, x, y, w, bh, name)
            val = self.f_date if name == "date" else self.f_time
            ty = y + (bh - 16) / 2 + 1
            if self.focus == name:
                p.text(x + 6, ty, with_cursor(val, self.cur[name]), c["acc_l"], maxw=w - 10)
            elif not val:
                p.text(x + 6, ty, "дата" if name == "date" else "время", c["faint"])
            else:
                if name == "date":
                    d = parse_date(val)
                    shown, ok = (rel_day(d) + " " + fmt_date(d), True) if d else (val, False)
                else:
                    t = parse_time(val)
                    shown, ok = ("%02d:%02d" % t, True) if t else (val, False)
                p.text(x + 6, ty, shown, c["text"] if ok else c["err"], maxw=w - 10)
            x += w + 6
        if x1 - x > 120:
            items = [(lab, ("chip", key)) for lab, key in CHIPS]
            while items and sum(p.text_w(i[0]) + 22 for i in items) > x1 - x:
                items.pop()
            self.buttons(p, x + 2, x1, y - 1, items)
            row += [i[1] for i in items]
        return y + bh

    def draw_drop(self, p, x0, x1, y):
        c = self.c
        h = len(self.drop) * ROW_H + 4
        p.rect(x0, y, x1 - x0, h, c["field"])
        p.box(x0, y, x1 - x0, h, c["acc"])
        for i, x in enumerate(self.drop):
            ry = y + 2 + i * ROW_H
            sel = i == self.drop_sel
            if sel or self.hover == ("pick", i):
                p.rect(x0 + 1, ry, x1 - x0 - 2, ROW_H, c["sel"])
            if sel:
                p.rect(x0 + 1, ry, 2, ROW_H, c["acc"])
            nw = p.text(x0 + 8, ry + 4, x["name"], c["acc_l"] if sel else c["text"], maxw=x1 - x0 - 150)
            tail = x["phone"] + ("" if x.get("book") or x["name"] == x["phone"] else " · профиль")
            p.text(x1 - 8, ry + 4, tail, c["faint"], align="r", maxw=max(40, x1 - x0 - nw - 30))
            self.hits.append(((x0, ry, x1 - x0, ROW_H), ("pick", i)))

    def row_h(self, r, i):
        h = 38 + (18 if (r["status"] == "ask" or (r["status"] == "pending" and r["error"])) else 0)
        return h + (30 if i == self.sel else 0)

    def draw_queue(self, p, x0, x1, y0, y1):
        c = self.c
        if not self.rows:
            p.text(x0, y0 + 4, "Пусто. Заполните форму сверху — сообщение уйдёт само.", c["faint"],
                   maxw=x1 - x0)
            return
        hs = [self.row_h(r, i) for i, r in enumerate(self.rows)]
        self.q_page = max(1, int((y1 - y0) * len(hs) / max(1, sum(hs))))   # сколько строк влезает — для Ctrl+D/U
        self.scroll = min(self.scroll, self.sel)        # выбранная строка — всегда видна
        while sum(hs[self.scroll:self.sel + 1]) > y1 - y0 and self.scroll < self.sel:
            self.scroll += 1
        y = y0
        p.cr.save()
        p.cr.rectangle(x0, y0, x1 - x0, y1 - y0)
        p.cr.clip()
        for i in range(self.scroll, len(self.rows)):
            if y >= y1:
                break
            r, h = self.rows[i], hs[i]
            sel = i == self.sel
            ask = r["status"] == "ask"
            if sel:
                p.rect(x0 + 1, y, x1 - x0 - 2, h - 4, c["sel"])
            elif self.hover == ("row", i):
                p.rect(x0 + 1, y, x1 - x0 - 2, h - 4, c["sel"], 0.5)
            if sel or ask:
                p.rect(x0 + 1, y, 2 if self.area != "queue" or not sel else 4, h - 4, c["err"] if ask else c["acc"])
            old = r["status"] in ("sent", "cancelled")
            mcol = {"ask": c["err"], "sent": c["acc_l"], "cancelled": c["faint"]}.get(r["status"], c["acc"])
            p.text(x0 + 10, y + 3, MARK.get(r["status"], "?"), mcol)
            ts = r["sent_at"] if r["status"] == "sent" and r["sent_at"] else r["due"]
            wl = ("%s · %s" % (W.STATUS_RU.get(r["status"], ""), W.when(ts))) if old or ask else W.when(ts)
            ww = p.text(x1 - 8, y + 3, wl, c["err"] if ask else c["dim"], align="r")
            p.text(x0 + 26, y + 3, r["name"], c["faint"] if old else c["text"], maxw=x1 - x0 - ww - 44)
            p.text(x0 + 26, y + 19, W.short(r["text"], 200), c["faint"] if old else c["dim"], maxw=x1 - x0 - 34)
            yy = y + 36
            if ask or (r["status"] == "pending" and r["error"]):
                p.text(x0 + 26, yy, r["error"], c["err"], maxw=x1 - x0 - 34)
                yy += 18
            self.hits.append(((x0, y, x1 - x0, yy - y), ("row", i)))
            if sel:
                if r["status"] in ("pending", "ask"):
                    items = [("Изменить", ("act", "edit", r["id"])),
                             ("Отправить сейчас" if not self.is_armed("now", r["id"]) else "Точно?",
                              ("act", "now", r["id"]), self.is_armed("now", r["id"])),
                             ("+1 ч", ("act", "later", r["id"])),
                             ("Отменить" if not self.is_armed("cancel", r["id"]) else "Точно?",
                              ("act", "cancel", r["id"]), self.is_armed("cancel", r["id"]))]
                elif r["status"] == "cancelled":
                    items = [("Вернуть", ("act", "back", r["id"])), ("Ещё раз — новым", ("act", "again", r["id"]))]
                elif r["status"] == "sent":
                    items = [("Ещё раз — новым", ("act", "again", r["id"]))]
                else:
                    items = []
                self.buttons(p, x0 + 26, x1 - 8, yy, items)
                self.qkeys = [it[1] for it in items]
            y += h
        p.cr.restore()

    def is_armed(self, what, mid):
        a = self.armed
        return bool(a and a[0] == what and a[1] == mid and time.monotonic() < a[2])

    HINTS = {"to": "имя или номер · ↑↓ выбор · Enter — взять · Tab — дальше · Ctrl+E — выбор",
             "text": "Enter — новая строка · Ctrl+V вставить · Tab — дальше · Ctrl+Enter — запланировать",
             "date": "j/k h/l ±день · Shift — неделя · или «завтра», «пт», «16.10» · Ctrl+E — выбор",
             "time": "j/k ±15 мин · h/l ±1 мин · Shift — час · или «18:30» · Ctrl+E — выбор",
             "nav": "jkhl ^D^U · H история · ^E ввод · ^J очередь",
             "queue": "jkhl ^D^U · dd убрать · u ^R · H история"}

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        mode = self.mode()
        badge = {"edit": "ВВОД", "nav": "ВЫБОР", "queue": "ОЧЕРЕДЬ"}[mode]
        bw = p.text_w(badge) + 10
        p.rect(x0, y - 1, bw, 16, c["field_l"])
        p.text(x0 + 5, y, badge, c["acc_l"])
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x0 + bw + 10, y, self.msg, c["err"] if self.msg_err else c["text"], maxw=x1 - x0 - bw - 10)
        else:
            p.text(x0 + bw + 10, y, self.HINTS[self.focus if mode == "edit" else mode], c["faint"],
                   maxw=x1 - x0 - bw - 10)


# ── окно ──────────────────────────────────────────────────────────────────────

class WaWindow(Gtk.ApplicationWindow):
    EDGES = A.HubWindow.EDGES
    set_cursor = A.HubWindow.set_cursor
    on_configure = A.HubWindow.on_configure
    hit = A.HubWindow.hit

    def __init__(self, app):
        super().__init__(application=app, title="WhatsApp")
        self.view = View()
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_size_request(MIN_W, MIN_H)
        sw, sh = 540, 720
        try:
            a, b = open(SIZE_FILE).read().split()[:2]
            sw, sh = max(MIN_W, int(a)), max(MIN_H, int(b))
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
        self.connect("notify::is-active", lambda *_: (setattr(self.view, "active", self.is_active()),
                                                      self.redraw()))
        self.connect("window-state-event", lambda _w, ev: (
            setattr(self.view, "maxed", bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED) or title_strip.float_maxed(self)),
            self.redraw(), False)[-1])
        self.n_tick = 0
        self.last_input = time.monotonic()
        GLib.timeout_add(500, self.tick)
        if not self.view.locked:
            threading.Thread(target=self.warm, daemon=True).start()

    def warm(self):
        """Книга контактов — в фоне: окно не ждёт `wa contacts`."""
        W.contacts(force=True)
        ok = W.linked()
        GLib.idle_add(lambda: (setattr(self.view, "contacts_ok", ok), self.view.search(), self.redraw()))

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

    def edge_at(self, x, y):
        return A.HubWindow.edge_at(self, x, y)

    def redraw(self):
        self.area.queue_draw()

    def tick(self):
        v = self.view
        if style_name() != v.style:
            v.reload_style()
        self.n_tick += 1
        if not v.locked and time.monotonic() - self.last_input > hub_auth.IDLE_SECS:
            v.lock()
        if self.n_tick % 6 == 0:                  # очередь — раз в 3 с (меняет её и hubd)
            v.load()
        if v.locked and not v.tries and not v.pw_busy and self.n_tick % 10 == 0:
            v.tries = hub_auth.tries_left()       # ошибки выходят из счёта faillock — снова можно
        self.redraw()
        return True

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.view.draw(cr, a.width, a.height)

    def set_hover(self, key):
        if key != self.view.hover:
            self.view.hover = key
            self.redraw()

    def on_motion(self, _w, ev):
        edge = self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else
                        ("text" if isinstance(self.hit(ev.x, ev.y), tuple)
                         and self.hit(ev.x, ev.y)[0] == "field" else None))
        self.set_hover(None if edge else self.hit(ev.x, ev.y))

    def on_scroll(self, _w, ev):
        d = {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction)
        if not d:
            return True
        v = self.view
        if v.locked:
            return True
        key = self.hit(ev.x, ev.y)
        if isinstance(key, tuple) and key[0] == "field" and key[1] in ("date", "time"):
            v.bump(key[1], "up" if d < 0 else "down", bool(ev.state & Gdk.ModifierType.SHIFT_MASK))
        elif v.drop and v.focus == "to" and isinstance(key, tuple) and key[0] == "pick":
            v.drop_sel = max(0, min(len(v.drop) - 1, v.drop_sel + d))
        elif v.rows:
            v.sel = max(0, min(len(v.rows) - 1, v.sel + d))
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
        self.last_input = time.monotonic()
        if isinstance(key, tuple) and key[0] == "row":
            v.sel, v.qbtn = key[1], None
            if ev.type == Gdk.EventType._2BUTTON_PRESS and v.rows[key[1]]["status"] in ("pending", "ask"):
                v.act("edit", v.rows[key[1]]["id"])
        else:
            self.press(key)
        self.redraw()
        return True

    def press(self, key):
        """Кнопка/поле — одинаково щелчком и клавиатурой (Enter в режиме ВЫБОР/ОЧЕРЕДЬ)."""
        v = self.view
        if key == "close":
            self.close()
        elif key == "submit":
            v.submit()
        elif key == "clear":
            v.reset_form()
        elif key == "unedit":
            v.reset_form()
            v.flash("правка отменена")
        elif key == "hist":
            v.toggle_hist()
        elif key[0] == "field":
            v.area, v.nav = "form", key
            self.set_focus_field(key[1])
        elif key[0] == "pick":
            self.pick(key[1])
        elif key[0] == "chip":
            v.preset(key[1])
        elif key[0] == "act":
            v.act(key[1], key[2])

    def set_focus_field(self, name):
        v = self.view
        v.focus = name
        if name == "to":
            v.search()

    def pick(self, i):
        v = self.view
        if 0 <= i < len(v.drop):
            v.to = v.drop[i]
            v.to_buf, v.cur["to"] = v.to["name"], None
            v.drop, v.focus = [], "text"

    def paste(self):
        cb = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        return cb.wait_for_text() or ""

    def on_key(self, _w, ev):
        v = self.view
        name = Gdk.keyval_name(ev.keyval) or ""
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        u = Gdk.keyval_to_unicode(ev.keyval)
        ch = chr(u) if u and not ctrl else ""
        self.last_input = time.monotonic()
        hw = A.KEYS.get(ev.hardware_keycode)
        if v.locked:
            self.key_lock(name, ch, ctrl)
        elif (ctrl and name in ("Return", "KP_Enter")) or (ctrl and hw == "s"):
            v.submit()
        elif ctrl and hw == "e":                       # ВВОД ⇄ ВЫБОР
            if v.focus:
                v.nav, v.focus, v.drop = ("field", v.focus), None, []
            else:
                v.area = "form"
                if isinstance(v.nav, tuple) and v.nav[0] == "field":
                    self.set_focus_field(v.nav[1])
                else:
                    self.set_focus_field("to")
        elif ctrl and hw == "j" and v.area == "form":   # как в nvim: вниз — в очередь
            if v.rows:
                if v.focus:
                    v.nav = ("field", v.focus)
                v.area, v.focus, v.drop, v.qbtn = "queue", None, [], None
                v.sel = min(v.sel, len(v.rows) - 1)
        elif ctrl and hw == "k" and v.area == "queue":
            v.area = "form"
        elif ctrl and hw in ("j", "k"):
            pass
        elif ctrl and hw == "r":                         # как в nvim: повторить отменённое u
            if not v.focus:
                v.undo(redo=True)
        elif ctrl and hw in ("d", "u"):                 # как в nvim: полэкрана вниз/вверх
            if not v.focus:
                self.half_page(hw == "d")
        elif name == "Escape":
            if v.focus == "to" and v.drop and not v.to:
                v.drop = []
            elif v.focus:
                v.nav, v.focus = ("field", v.focus), None
            elif v.area == "form" and v.editing is not None:
                v.reset_form()
                v.focus = None
                v.flash("правка отменена")
            elif v.area == "queue":
                v.area = "form"
            else:
                self.close()
        elif name in ("Tab", "ISO_Left_Tab"):
            order = list(FIELDS)
            k = order.index(v.focus) if v.focus in order else -1
            nxt = order[(k + (-1 if shift or name == "ISO_Left_Tab" else 1)) % len(order)]
            if v.focus == "to" and v.drop and not v.to:
                self.pick(v.drop_sel)
            self.set_focus_field(nxt)
        elif v.area == "queue":
            self.key_queue(ev, name, shift)
        elif v.focus is None:
            self.key_nav(ev, name)
        else:
            self.key_field(v.focus, name, ch, ctrl, shift, ev)
        self.redraw()
        return True

    def half_page(self, down):
        """ОЧЕРЕДЬ — на полэкрана строк; ВЫБОР — к нижнему/верхнему пункту формы, дальше — в очередь и обратно."""
        v = self.view
        if v.area == "queue" and v.rows:
            if not down and v.sel == 0:
                v.area = "form"
            else:
                half = max(1, getattr(v, "q_page", 6) // 2)
                v.sel = max(0, min(len(v.rows) - 1, v.sel + (half if down else -half)))
            v.qbtn = None
            return
        rows = v.nav_rows or [[("field", "to")]]
        if down and v.nav in rows[-1] and v.rows:
            v.area, v.sel, v.qbtn = "queue", 0, None
        else:
            v.nav = rows[-1 if down else 0][0]

    def key_lock(self, name, ch, ctrl):
        v = self.view
        if name == "Escape":
            return self.close()
        if v.pw_busy or not v.tries:
            return
        if name in ("Return", "KP_Enter"):
            if not v.pw:
                return
            buf, v.pw = v.pw, bytearray()
            v.pw_busy, v.pw_msg = True, ""
            threading.Thread(target=self.check_pw, args=(buf,), daemon=True).start()
        elif name == "BackSpace":
            v.pw = bytearray() if ctrl else v.pw[:-1]
        elif ch and ch.isprintable() and len(v.pw) < 256:
            v.pw += ch.encode()

    def check_pw(self, buf):
        try:
            ok = hub_auth.check(buf)
        finally:
            hub_auth.wipe(buf)
        GLib.idle_add(self.pw_done, ok)

    def pw_done(self, ok):
        v = self.view
        v.pw_busy = False
        if ok:
            v.locked, v.pw_msg = False, ""
            v.load()
            if v.contacts_ok is None:
                threading.Thread(target=self.warm, daemon=True).start()
            self.last_input = time.monotonic()
            v.flash("вход выполнен · окно запрётся через %d мин без дела" % (hub_auth.IDLE_SECS // 60))
        else:
            v.tries -= 1
            v.pw_msg = "Неверный пароль. Осталось попыток: %d" % v.tries
        self.redraw()
        return False

    def key_nav(self, ev, name):
        """ВЫБОР: j/k — ряды формы, h/l — внутри ряда; Enter/пробел/i — нажать или писать в поле."""
        v = self.view
        k = A.KEYS.get(ev.hardware_keycode)
        rows = v.nav_rows or [[("field", "to")]]
        ri = next((i for i, r in enumerate(rows) if v.nav in r), 0)
        ci = rows[ri].index(v.nav) if v.nav in rows[ri] else 0
        if k == "h" and bool(ev.state & Gdk.ModifierType.SHIFT_MASK):
            v.toggle_hist()                        # 15.10: раньше только в ОЧЕРЕДИ — а пустая туда не пускает
        elif k == "u" and not bool(ev.state & Gdk.ModifierType.SHIFT_MASK):
            v.undo()
        elif (k == "j" or name == "Down") and ri == len(rows) - 1 and v.rows:
            v.area, v.sel, v.qbtn = "queue", 0, None   # с нижнего пункта вниз — в очередь (как k с её верха)
        elif k in ("j", "k") or name in ("Down", "Up"):
            ri = max(0, min(len(rows) - 1, ri + (1 if k == "j" or name == "Down" else -1)))
            v.nav = rows[ri][min(ci, len(rows[ri]) - 1)]
        elif k in ("h", "l") or name in ("Left", "Right"):
            ci = max(0, min(len(rows[ri]) - 1, ci + (1 if k == "l" or name == "Right" else -1)))
            v.nav = rows[ri][ci]
        elif name in ("Return", "KP_Enter", "space") or k in ("i", "a"):
            self.press(v.nav)
        elif k == "q":
            self.close()

    def key_queue(self, ev, name, shift):
        """ОЧЕРЕДЬ: j/k — строка, h/l — её кнопки, Enter — нажать (без кнопки — изменить)."""
        v = self.view
        k = A.KEYS.get(ev.hardware_keycode)
        dd, self.d_at = (k == "d" and not shift and time.monotonic() - getattr(self, "d_at", 0) < 1.0), 0
        if k == "h" and shift:
            v.toggle_hist()
        elif k == "u" and not shift:
            v.undo()
        elif not v.rows:
            v.area = "form"
        elif dd or name in ("Delete", "KP_Delete", "BackSpace"):
            v.remove()
        elif k == "d" and not shift:
            self.d_at = time.monotonic()           # первое d — ждём второе, как в nvim
        elif k == "j" or name == "Down":
            v.sel, v.qbtn = min(len(v.rows) - 1, v.sel + 1), None
        elif k == "k" or name == "Up":
            if v.sel == 0:
                v.area = "form"                    # с первой строки вверх — в форму
            v.sel, v.qbtn = max(0, v.sel - 1), None
        elif k in ("h", "l") or name in ("Left", "Right"):
            if v.qkeys:
                fwd = k == "l" or name == "Right"
                b = -1 if v.qbtn is None else v.qbtn
                v.qbtn = max(0, min(len(v.qkeys) - 1, b + (1 if fwd else -1))) if (fwd or b > 0) else None
        elif k == "g":
            v.sel, v.qbtn = (len(v.rows) - 1 if shift else 0), None
        elif k == "n":
            v.reset_form()
        elif k == "q":
            self.close()
        elif v.sel < len(v.rows):
            r = v.rows[v.sel]
            if name in ("Return", "KP_Enter", "space"):
                if v.qbtn is not None and v.qbtn < len(v.qkeys):
                    self.press(v.qkeys[v.qbtn])
                    if v.area == "queue" and not v.is_armed(v.qkeys[v.qbtn][1], v.qkeys[v.qbtn][2]):
                        v.qbtn = None
                elif r["status"] in ("pending", "ask"):
                    v.act("edit", r["id"])
            elif k == "e" and r["status"] in ("pending", "ask"):
                v.act("edit", r["id"])

    def key_field(self, f, name, ch, ctrl, shift, ev):
        v = self.view
        val = {"to": v.to_buf, "text": v.text, "date": v.f_date, "time": v.f_time}[f]
        if f in ("date", "time") and not ctrl:
            how = {"Up": "up", "KP_Up": "up", "Down": "down", "KP_Down": "down",
                   "k": "up", "K": "up", "j": "down", "J": "down",
                   "l": "right", "L": "right", "h": "left", "H": "left"}.get(name)
            if how:                               # только латиница: кириллицей пишется «завтра»
                return v.bump(f, how, shift)
        if f == "to" and name in ("Up", "Down") and v.drop:
            v.drop_sel = max(0, min(len(v.drop) - 1, v.drop_sel + (1 if name == "Down" else -1)))
            return
        if name in ("Return", "KP_Enter"):
            if f == "text":
                val, v.cur[f] = self.insert(val, v.cur[f], "\n")
                return self.store(f, val)
            if f == "to":
                if v.drop and not v.to:
                    return self.pick(v.drop_sel)
                return self.set_focus_field("text")
            return self.set_focus_field("time" if f == "date" else "date") if f == "date" else v.submit()
        if ctrl and A.KEYS.get(ev.hardware_keycode) == "v":
            s = self.paste()
            if f != "text":
                s = " ".join(s.split())
            val, v.cur[f] = self.insert(val, v.cur[f], s[:W.TEXT_MAX])
            return self.store(f, val)
        if ctrl and A.KEYS.get(ev.hardware_keycode) == "a":
            return
        r = edit_line(val, v.cur[f], name, ctrl)
        if r is not None:
            val, v.cur[f] = r
            return self.store(f, val)
        if ch and ch.isprintable():
            val, v.cur[f] = self.insert(val, v.cur[f], ch)
            self.store(f, val)

    @staticmethod
    def insert(s, cur, t):
        cur = len(s) if cur is None else cur
        return s[:cur] + t + s[cur:], cur + len(t)

    def store(self, f, val):
        v = self.view
        if f == "to":
            v.to_buf, v.to = val, None
            v.search()
        elif f == "text":
            v.text = val
        elif f == "date":
            v.f_date = val
        else:
            v.f_time = val


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        if self.win is None:
            self.win = WaWindow(self)
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            self.win.show_all()
        else:
            self.win.view.reload_style()
            self.win.redraw()
        present_unmin(self.win)
        return 0


def shot(path, style=None, w=540, h=720, sel=0, focus="to", q="", text="", date="", time_="", hist=0, locked=0,
         pw=0, area="form", nav="", qbtn=-1, tries=2):
    v = View()
    v.locked, v.pw, v.tries = bool(locked), bytearray(b"x" * pw), tries
    if style:
        v.style, v.c = style, colors(style)
    v.show_hist = bool(hist)                     # снимок не трогает HIST_FILE
    v.load()
    v.sel, v.focus, v.area = sel, (focus or None), area
    if area == "queue":
        v.focus = None
    if nav:
        v.nav = ("field", nav) if nav in FIELDS else (("chip", nav) if nav in ("h1", "t20", "m9") else nav)
    v.qbtn = None if qbtn < 0 else qbtn
    v.to_buf, v.text, v.f_date, v.f_time = str(q), str(text).replace("\\n", "\n"), str(date), str(time_)
    if q:
        v.search()
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    v.draw(cr, w, h)
    surf.write_to_png(path)
    return w, h


def main():
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        kw = {}
        for a in sys.argv[3:]:
            k, _, val = a.partition("=")
            kw[k if k != "time" else "time_"] = int(val) if val.lstrip("-").isdigit() and k not in ("time", "q") else val
        print(shot(sys.argv[2], **kw))
        return
    GLib.set_prgname(APP_ID)
    sys.exit(App().run(sys.argv))


if __name__ == "__main__":
    main()
