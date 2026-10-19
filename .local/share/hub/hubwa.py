#!/usr/bin/env python3
"""hubwa — отложенные личные сообщения WhatsApp (15.10.2026, просьба: «выбирать контакты сам,
текст заранее, чтобы ушло само в указанную дату и время, не нагружая систему»).

Хранение — таблица wa в hub.db. Отправляет hubd: в минуту срока запускает отправщик
~/.local/share/wa/wa (whatsmeow, Go) — тот подключается, отправляет и выходит; между
отправками ничего не работает. Раз в 3 дня — короткое подключение (wa ping), чтобы
WhatsApp не отвязал устройство.

Опоздание (ноутбук спал/был выключен): до часа — отправить сразу; больше часа — не
отправлять, а спросить: «Отправить сейчас / +1 час / Отменить» (на ПК или в Telegram,
смотря где вы). Не ушло (нет сети) — повтор раз в минуту, пока не прошёл час.

Окно — wa_app.py (Super+Alt+W нет; запуск: wa app), терминал — wa new/list/…, Telegram — /wa.
"""
import calendar
import datetime as dt
import json
import os
import re
import subprocess
import threading
import time

import hublib as H

BIN = os.path.expanduser("~/.local/share/wa/wa")
LATE_MAX = 3600            # опоздание до часа — отправить, больше — спросить (15.10.2026)
RETRY_GAP = 60
PING_EVERY = 3 * 86400
SEND_TIMEOUT = 150
# защита (15.10.2026, просьба: «не оставлять уязвимостей»): адрес — только номер или JID
# человека (не группы и не рассылки), текст — до 4000 знаков, и не больше BURST_MAX отправок
# за BURST_WIN: ошибка/сбой не превратится в рассылку и не подставит номер под блокировку.
JID_RE = re.compile(r"^(\+\d{8,15}|\d{8,15}@s\.whatsapp\.net)$")
TEXT_MAX = 4000
BURST_MAX, BURST_WIN = 10, 600
STATUS_RU = {"pending": "ждёт", "sending": "отправляется", "sent": "отправлено",
             "ask": "нужно решение", "cancelled": "отменено"}


# ───────────────────────────── контакты ─────────────────────────────

_cache = {"t": 0, "list": [], "linked": None}


def run_wa(*args, stdin=None, timeout=20):
    """→ (код, JSON-ответ | {}). Код 3 — не привязан."""
    try:
        p = subprocess.run([BIN, *args], input=stdin, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 1, {"ok": False, "error": "отправщик не ответил за %d с" % timeout}
    except OSError as e:
        return 1, {"ok": False, "error": "нет отправщика: %s" % e}
    out = (p.stdout or "").strip().splitlines()
    try:
        data = json.loads(out[-1]) if out else {}
    except ValueError:
        data = {"ok": False, "error": out[-1][:200]}
    if p.returncode and isinstance(data, dict) and not data.get("error"):
        data["error"] = (p.stderr or "").strip().splitlines()[-1:] or ["код %d" % p.returncode]
        data["error"] = data["error"][0][:200]
    return p.returncode, data


def contacts(force=False):
    """Люди из книги WhatsApp, каждый один раз: только адреса-номера (@s.whatsapp.net),
    повторы под внутренними номерами (@lid) отброшены. Имя из адресной книги — book."""
    if not force and time.monotonic() - _cache["t"] < 60 and _cache["list"]:
        return _cache["list"]
    code, data = run_wa("contacts")
    _cache["linked"] = code != 3
    if code or not isinstance(data, list):
        return _cache["list"]
    out = []
    for x in data:
        if not x.get("jid", "").endswith("@s.whatsapp.net") or not x.get("name"):
            continue
        out.append({"jid": x["jid"], "name": x["name"], "push": x.get("push") or "",
                    "phone": x.get("phone") or "+" + x["jid"].split("@")[0],
                    "book": x["name"] != (x.get("push") or "")})
    out.sort(key=lambda c: (not c["book"], c["name"].casefold()))
    _cache.update(t=time.monotonic(), list=out)
    return out


EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
RU = "йцукенгшщзхъфывапролджэячсмитьбюё"
TO_RU = str.maketrans(EN, RU)
TO_EN = str.maketrans(RU, EN)


def phone_of(q):
    """«+7 701 123-45-67», «87011234567» → «+77011234567» | None."""
    d = re.sub(r"[\s()\-]", "", q.strip())
    if not re.fullmatch(r"\+?\d{10,15}", d):
        return None
    d = d.lstrip("+")
    if len(d) == 11 and d.startswith("8"):          # казахстанская/российская восьмёрка
        d = "7" + d[1:]
    elif len(d) == 10:
        d = "7" + d
    return "+" + d


def search(q, limit=8):
    """Поиск по имени, имени профиля и номеру; понимает другую раскладку («ьфьф» = «мама»).
    Имена из книги — выше, совпадение с начала слова — ещё выше."""
    q = q.strip().casefold()
    allc = contacts()
    if not q:
        return [c for c in allc if c["book"]][:limit]
    digits = re.sub(r"\D", "", q)
    variants = {q, q.translate(TO_RU), q.translate(TO_EN)}
    scored = []
    for c in allc:
        hay = (c["name"] + " " + c["push"]).casefold()
        best = None
        for v in variants:
            k = hay.find(v)
            if k >= 0:
                s = 0 if k == 0 else (1 if hay[k - 1] in " .-_(" else 2)
                best = s if best is None else min(best, s)
        if best is None and len(digits) >= 3 and digits in c["phone"]:
            best = 1
        if best is not None:
            scored.append((best, not c["book"], c["name"].casefold(), c))
    scored.sort(key=lambda x: x[:3])
    out = [x[3] for x in scored[:limit]]
    ph = phone_of(q)
    if ph and not any(c["phone"] == ph for c in out):
        out.insert(0, {"jid": ph, "name": ph, "push": "", "phone": ph, "book": False})
    return out


def by_jid(jid):
    return next((c for c in contacts() if c["jid"] == jid), None)


def linked():
    if _cache["linked"] is None:
        contacts()
    return bool(_cache["linked"])


# ───────────────────────────── хранение ─────────────────────────────

def check(jid, text):
    """Проверка перед записью: → '' или что не так."""
    if not JID_RE.match(jid or ""):
        return "адрес не похож на номер человека"
    if not (text or "").strip():
        return "пустой текст"
    if len(text) > TEXT_MAX:
        return "текст длиннее %d знаков" % TEXT_MAX
    return ""


def add(c, jid, name, text, due, source="pc"):
    err = check(jid, text)
    if err:
        raise ValueError(err)
    t = H.now()
    cur = c.execute("INSERT INTO wa(jid,name,text,due,created,updated_at,source) VALUES(?,?,?,?,?,?,?)",
                    (jid, name or jid, text, int(due), t, t, source))
    H.log(c, "wa_add", cur.lastrowid, "%s @%s" % (name, due))
    return cur.lastrowid


def get(c, mid):
    return c.execute("SELECT * FROM wa WHERE id=?", (mid,)).fetchone()


def edit(c, mid, jid=None, name=None, text=None, due=None):
    """Правка ждущего (или спрашивающего) сообщения; новый срок — снова «ждёт»."""
    m = get(c, mid)
    if m is None or m["status"] not in ("pending", "ask"):
        return False
    err = check(jid or m["jid"], text if text is not None else m["text"])
    if err:
        raise ValueError(err)
    c.execute("UPDATE wa SET jid=?, name=?, text=?, due=?, status='pending', tries=0, next_try=NULL, "
              "error='', updated_at=? WHERE id=?",
              (jid or m["jid"], name or m["name"], text if text is not None else m["text"],
               int(due) if due is not None else m["due"], H.now(), mid))
    H.log(c, "wa_edit", mid)
    return True


def cancel(c, mid):
    n = c.execute("UPDATE wa SET status='cancelled', updated_at=? WHERE id=? AND status IN ('pending','ask')",
                  (H.now(), mid)).rowcount
    H.log(c, "wa_cancel", mid)
    return bool(n)


def send_now(c, mid):
    return edit(c, mid, due=H.now())


def postpone(c, mid, secs=3600):
    m = get(c, mid)
    if m is None:
        return False
    return edit(c, mid, due=max(H.now(), m["due"] if m["status"] == "pending" else 0) + secs)


def restore(c, mid):
    """Вернуть отменённое (u в окне, «вернуть» в терминале) — как «ждёт», срок прежний."""
    return bool(c.execute("UPDATE wa SET status='pending', tries=0, next_try=NULL, error='', updated_at=? "
                          "WHERE id=? AND status='cancelled'", (H.now(), mid)).rowcount)


def hide(c, mid, on=True):
    """Убрать запись из истории (или вернуть). Только отправленные и отменённые; в базе остаётся."""
    return bool(c.execute("UPDATE wa SET hidden=? WHERE id=? AND status IN ('sent','cancelled')",
                          (1 if on else 0, mid)).rowcount)


STOP_KEY = "wa_stopped"                    # id, отменённые последним «стоп» — для «вернуть все»


def stop_all(c):
    """Отменить всё, что ждёт (уходящее прямо сейчас не остановить). Сколько отменено."""
    ids = [r[0] for r in c.execute("SELECT id FROM wa WHERE status IN ('pending','ask')")]
    for mid in ids:
        cancel(c, mid)
    H.meta_set(c, STOP_KEY, json.dumps(ids))
    H.log(c, "wa_stop", None, str(len(ids)))
    return len(ids)


def resume_all(c):
    """Вернуть то, что отменил последний «стоп» (и что с тех пор не стёрто/не вернули). Сколько вернул."""
    try:
        ids = json.loads(H.meta_get(c, STOP_KEY) or "[]")
    except ValueError:
        ids = []
    n = sum(1 for mid in ids if restore(c, mid))
    H.meta_set(c, STOP_KEY, "[]")
    return n


def pending_count(c):
    return c.execute("SELECT COUNT(*) FROM wa WHERE status IN ('pending','ask')").fetchone()[0]


def queue(c):
    """Ждущие и спрашивающие — по сроку; спрашивающие первыми."""
    return c.execute("SELECT * FROM wa WHERE status IN ('pending','sending','ask') "
                     "ORDER BY status!='ask', due, id").fetchall()


def history(c, n=30, hidden=False):
    """Отправленные и отменённые, свежие сверху. hidden=True — журнал целиком, и убранные из окна."""
    return c.execute("SELECT * FROM wa WHERE status IN ('sent','cancelled') %s"
                     "ORDER BY COALESCE(sent_at, updated_at) DESC LIMIT ?" % ("" if hidden else "AND NOT hidden "),
                     (n,)).fetchall()


def history_count(c):
    return c.execute("SELECT COUNT(*) FROM wa WHERE status IN ('sent','cancelled')").fetchone()[0]


def clear_history(c):
    """Стереть журнал: отправленные и отменённые (очередь не трогаем). Насовсем — сколько стёрто."""
    n = c.execute("DELETE FROM wa WHERE status IN ('sent','cancelled')").rowcount
    H.log(c, "wa_clear", None, str(n))
    return n


def plain(s):
    """Текст сообщения в уведомление: swaync понимает разметку — «<b>» из чужого текста
    не должен ничего рисовать."""
    import html
    return html.escape(s, quote=False)


def when(ts):
    return H.fmt_when(ts)


def short(text, n=60):
    t = " ".join(text.split())
    return t if len(t) <= n else t[:n - 1] + "…"


# ───────────────────────────── отправка (hubd) ─────────────────────────────

class Sender:
    """Вызывается из такта hubd. Отправляет по одному в своём потоке — такт не ждёт."""

    def __init__(self, present, log):
        self.present, self.log = present, log
        self.busy = threading.Lock()

    def recover(self, c):
        """hubd упал посреди отправки — неизвестно, ушло ли: не повторять вслепую, спросить."""
        for m in c.execute("SELECT * FROM wa WHERE status='sending'").fetchall():
            c.execute("UPDATE wa SET status='ask', error=? WHERE id=?",
                      ("прервано на отправке — проверьте в WhatsApp, ушло ли", m["id"]))
            self.ask(c, get(c, m["id"]))

    def tick(self, c):
        if self.busy.locked():
            return
        t = H.now()
        m = c.execute("SELECT * FROM wa WHERE status='pending' AND due<=? AND "
                      "(next_try IS NULL OR next_try<=?) ORDER BY due, id LIMIT 1", (t, t)).fetchone()
        if m is None:
            self.maybe_ping(c)
            return
        late = t - m["due"]
        n = c.execute("SELECT COUNT(*) FROM wa WHERE status='sent' AND sent_at>?", (t - BURST_WIN,)).fetchone()[0]
        if n >= BURST_MAX or check(m["jid"], m["text"]):
            why = check(m["jid"], m["text"]) or \
                "пауза для безопасности: уже %d отправок за %d мин" % (n, BURST_WIN // 60)
            c.execute("UPDATE wa SET status='ask', error=?, updated_at=? WHERE id=?", (why, t, m["id"]))
            self.log("wa: задержано", m["id"], why)
            self.ask(c, get(c, m["id"]))
            return
        if late > LATE_MAX:
            why = m["error"] or "опоздало на %s — ноутбук спал или был выключен" % H.fmt_secs(late)
            c.execute("UPDATE wa SET status='ask', error=?, updated_at=? WHERE id=?", (why, t, m["id"]))
            self.log("wa: опоздало", m["id"], late)
            self.ask(c, get(c, m["id"]))
            return
        c.execute("UPDATE wa SET status='sending', updated_at=? WHERE id=?", (t, m["id"]))
        self.busy.acquire()
        threading.Thread(target=self.work, args=(dict(m),), daemon=True).start()

    def work(self, m):
        try:
            self.log("wa: отправляю", m["id"], m["name"])
            code, res = run_wa("send", m["jid"], "-", stdin=m["text"], timeout=SEND_TIMEOUT)
            c = H.connect()
            t = H.now()
            if code == 0 and res.get("ok"):
                c.execute("UPDATE wa SET status='sent', sent_at=?, error='', updated_at=? WHERE id=?",
                          (t, t, m["id"]))
                H.meta_set(c, "wa_last_ok", t)
                H.log(c, "wa_sent", m["id"])
                self.log("wa: отправлено", m["id"])
                self.tell(c, "WhatsApp: отправлено ✓", "%s — «%s»" % (m["name"], short(m["text"], 80)))
            elif code == 3:
                c.execute("UPDATE wa SET status='ask', error=?, updated_at=? WHERE id=?",
                          ("WhatsApp отвязан — в терминале: wa login", t, m["id"]))
                self.ask(c, get(c, m["id"]))
            else:
                err = (res.get("error") or "неизвестная ошибка")[:200]
                tries = m["tries"] + 1
                c.execute("UPDATE wa SET status='pending', tries=?, next_try=?, error=?, updated_at=? "
                          "WHERE id=?", (tries, t + RETRY_GAP, err, t, m["id"]))
                self.log("wa: не ушло (%d):" % tries, m["id"], err)
            c.close()
        except Exception as e:
            self.log("wa: ошибка", repr(e))
        finally:
            self.busy.release()

    def maybe_ping(self, c):
        last = int(H.meta_get(c, "wa_last_ok", 0) or 0)
        tried = int(H.meta_get(c, "wa_ping_try", 0) or 0)
        t = H.now()
        if t - last < PING_EVERY or t - tried < 3600 or not os.path.exists(BIN):
            return
        H.meta_set(c, "wa_ping_try", t)
        self.busy.acquire()

        def work():
            try:
                code, res = run_wa("ping", timeout=90)
                q = H.connect()
                if code == 0:
                    H.meta_set(q, "wa_last_ok", H.now())
                    self.log("wa: ping ok")
                elif code == 3 and H.meta_get(q, "wa_unlinked_day") != dt.date.today().isoformat():
                    H.meta_set(q, "wa_unlinked_day", dt.date.today().isoformat())
                    self.tell(q, "WhatsApp отвязан", "Отложенные сообщения не уйдут. В терминале: wa login")
                else:
                    self.log("wa: ping", code, res.get("error"))
                q.close()
            finally:
                self.busy.release()
        threading.Thread(target=work, daemon=True).start()

    # ── сообщить ──
    def tell(self, c, title, body):
        """Итог — на ПК, если вы рядом, иначе в Telegram (как у напоминаний)."""
        import hubtg as T
        if self.present() or not T.token():
            subprocess.Popen(["notify-send", "-a", "hub", "-i", "whatsapp", title, plain(body)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            T.enqueue(c, "%s\n%s" % (title, body))

    def ask(self, c, m):
        """Опоздало/не ушло: «Отправить сейчас / +1 час / Отменить»."""
        import hubtg as T
        title = "WhatsApp: не отправлено — %s" % m["name"]
        body = "%s\n«%s»\nСрок был: %s" % (m["error"], short(m["text"], 120), when(m["due"]))
        if self.present() or not T.token():
            threading.Thread(target=self.ask_pc, args=(m["id"], title, body), daemon=True).start()
        else:
            T.enqueue(c, tg_card_text(m), tg_card_buttons(m))

    def ask_pc(self, mid, title, body):
        try:
            p = subprocess.run(["notify-send", "-a", "hub", "-i", "whatsapp", "-u", "critical",
                                "-A", "now=▶ Отправить сейчас", "-A", "later=+1 час",
                                "-A", "cancel=✕ Отменить", "-w", title, plain(body)],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            act = p.stdout.strip()
        except OSError:
            return
        c = H.connect()
        m = get(c, mid)
        if m is not None and m["status"] == "ask":
            if act == "now":
                send_now(c, mid)
            elif act == "later":
                postpone(c, mid, 3600)
            elif act == "cancel":
                cancel(c, mid)
        c.close()


# ───────────────────────────── Telegram: /wa ─────────────────────────────

DRAFT_KEY = "tg_wa_draft"
NUMS_KEY = "tg_wa_nums"


def _T():
    import hubtg as T
    return T


def tg_card_text(m):
    T = _T()
    head = {"ask": "⚠ НЕ ОТПРАВЛЕНО", "sent": "✓ ОТПРАВЛЕНО", "cancelled": "✕ ОТМЕНЕНО"}.get(
        m["status"], "◷ ЖДЁТ")
    lines = ["<b>◆ WHATSAPP · %s</b>" % head,
             "<b>Кому:</b> %s <i>%s</i>" % (T.esc(m["name"]), T.esc(m["jid"].split("@")[0])),
             "<b>Когда:</b> %s" % T.esc(when(m["sent_at"] if m["status"] == "sent" else m["due"]))]
    if m["status"] == "ask" and m["error"]:
        lines.append("<i>%s</i>" % T.esc(m["error"]))
    elif m["status"] == "pending" and m["error"]:
        lines.append("<i>повтор: %s</i>" % T.esc(m["error"]))
    lines.append("\n" + T.esc(m["text"]))
    return T.Html("\n".join(lines))


def tg_card_buttons(m):
    T = _T()
    i = m["id"]
    if m["status"] in ("pending", "ask"):
        return [[T.btn("▶ Отправить сейчас", "w:now:%d" % i), T.btn("+1 час", "w:later:%d" % i)],
                [T.btn("🕑 Время", "w:time:%d" % i), T.btn("✎ Текст", "w:txt:%d" % i),
                 T.btn("✕ Отменить", "w:cancel:%d" % i)],
                [T.btn("← Все", "w:list")]]
    if m["status"] == "cancelled":
        return [[T.btn("↺ Вернуть", "w:back:%d" % i), T.btn("← Все", "w:list")]]
    return [[T.btn("← Все", "w:list")]]


def tg_panel(c, note=None, sent=False):
    T = _T()
    rows = history(c, 10, hidden=True) if sent else queue(c)
    head = "<b>◆ %s · WHATSAPP%s</b>" % (T.BRAND, " · ИСТОРИЯ" if sent else "")
    lines = [head, "<i>%s</i>" % T.esc(note) if note else
             ("<i>Отложенные сообщения: уйдут сами в своё время.</i>" if not sent else "")]
    kb, nums = [], {}
    if not rows:
        lines.append("\nПусто." if sent else "\nНичего не запланировано.")
    for n, m in enumerate(rows, 1):
        nums[str(n)] = m["id"]
        mark = {"ask": "⚠", "sending": "…", "sent": "✓", "cancelled": "✕"}.get(m["status"], "◷")
        ts = m["sent_at"] if m["status"] == "sent" else m["due"]
        lines.append("%s <b>%d.</b> %s · %s%s\n    <i>%s</i>" % (
            mark, n, T.esc(m["name"]), T.esc(when(ts)), " · убрано из окна" if m["hidden"] else "",
            T.esc(short(m["text"], 50))))
        kb.append(T.btn("%d. %s" % (n, short(m["name"], 14)), "w:card:%d" % m["id"]))
    H.meta_set(c, NUMS_KEY, json.dumps(nums))
    buttons = [kb[k:k + 3] for k in range(0, len(kb), 3)]
    if not linked():
        lines.append("\n⚠ WhatsApp не привязан — на ПК в терминале: <code>wa login</code>")
    if not sent and any(m["status"] in ("pending", "ask") for m in rows):
        buttons.append([T.btn("⏹ Остановить все", "w:stopask")])
    buttons.append([T.btn("✚ Новое сообщение", "w:new")] if not sent else
                   ([T.btn("🗑 Очистить журнал", "w:clr")] if rows else []))
    buttons.append([T.btn("↻", "w:sent" if sent else "w:list"), T.btn("Очередь" if sent else "История", "w:list" if sent else "w:sent")])
    return T.Html("\n".join(lines)), [b for b in buttons if b]


def tg_pick(c, q):
    T = _T()
    found = search(q, 8)
    if not found:
        T.wait_set(c, "wa_who")
        return T.Html("<b>◆ WHATSAPP · КОМУ</b>\nНе нашёл «%s», сэр. Напишите иначе: имя или номер."
                      % T.esc(q)), [[T.btn("✕ Отмена", "w:list")]]
    kb = [[T.btn("%s · %s" % (short(x["name"], 22), x["phone"]), "w:to:%s" % x["jid"].split("@")[0])]
          for x in found]
    kb.append([T.btn("✕ Отмена", "w:list")])
    T.wait_set(c, "wa_who")
    return T.Html("<b>◆ WHATSAPP · КОМУ</b>\n<i>Выберите — или напишите имя иначе.</i>"), kb


def draft_get(c):
    try:
        return json.loads(H.meta_get(c, DRAFT_KEY) or "{}") or {}
    except ValueError:
        return {}


def draft_set(c, d):
    H.meta_set(c, DRAFT_KEY, json.dumps(d, ensure_ascii=False))


WHEN_HINT = "Например: «завтра в 9», «пт 18:30», «16.10 10:00», «через 2 часа»."


def when_buttons(prefix):
    T = _T()
    tgt = prefix.split(":")[2] if prefix.startswith("w:rt:") else "d"
    return [[T.btn("через 1 ч", prefix + "h1"), T.btn("сегодня 20:00", prefix + "t20"),
             T.btn("завтра 09:00", prefix + "m9")],
            [T.btn("📅 Выбрать дату и время", "w:cal:%s:%s" % (tgt, dt.date.today().strftime("%Y%m")))],
            [T.btn("✕ Отмена", "w:list")]]


# ── выбор любой даты и времени кнопками (15.10, просьба: «чтобы можно было выбрать дату и
# время самому, любое»): месяц → день → час → минуты. tgt — «d» (черновик) или номер записи.
MONTHS_RU = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь",
             "Октябрь", "Ноябрь", "Декабрь")
DAYS_RU = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
CAL_MONTHS = 12                                 # дальше года вперёд не листаем


def _back_when(tgt):
    return "w:dtime" if tgt == "d" else "w:time:%s" % tgt


def tg_cal(tgt, ym, note=None):
    """Календарь месяца: прошедшие дни — «·»."""
    T = _T()
    today = dt.date.today()
    y, m = int(ym[:4]), int(ym[4:6])
    first = dt.date(y, m, 1)
    if first < today.replace(day=1):
        y, m = today.year, today.month
    prev_m = (y * 12 + m - 2)
    next_m = (y * 12 + m)
    far = today.year * 12 + today.month - 1 + CAL_MONTHS
    nav = [T.btn("◀" if (y, m) > (today.year, today.month) else " ",
                 "w:cal:%s:%04d%02d" % (tgt, prev_m // 12, prev_m % 12 + 1)
                 if (y, m) > (today.year, today.month) else "w:nop"),
           T.btn("%s %d" % (MONTHS_RU[m - 1], y), "w:nop"),
           T.btn("▶" if next_m < far else " ",
                 "w:cal:%s:%04d%02d" % (tgt, next_m // 12, next_m % 12 + 1) if next_m < far else "w:nop")]
    rows = [nav, [T.btn(d, "w:nop") for d in DAYS_RU]]
    for week in calendar.monthcalendar(y, m):
        if all(not d or dt.date(y, m, d) < today for d in week):
            continue                            # прошедшие недели — без пустых рядов
        row = []
        for d in week:
            if not d:
                row.append(T.btn(" ", "w:nop"))
            elif dt.date(y, m, d) < today:
                row.append(T.btn("·", "w:nop"))
            else:
                lab = "[%d]" % d if dt.date(y, m, d) == today else str(d)
                row.append(T.btn(lab, "w:hr:%s:%04d%02d%02d" % (tgt, y, m, d)))
        rows.append(row)
    rows.append([T.btn("← Назад", _back_when(tgt)), T.btn("✕ Отмена", "w:list")])
    txt = "<b>◆ WHATSAPP · ДЕНЬ</b>\n<i>Выберите день, потом час и минуты.</i>"
    if note:
        txt = "<i>%s</i>\n" % T.esc(note) + txt
    return T.Html(txt), rows


def tg_hours(tgt, ymd):
    T = _T()
    day = dt.datetime.strptime(ymd, "%Y%m%d").date()
    now = dt.datetime.now()
    rows, row = [], []
    for h in range(24):
        if day == now.date() and h < now.hour:
            row.append(T.btn("·", "w:nop"))
        else:
            row.append(T.btn("%02d" % h, "w:mi:%s:%s:%02d" % (tgt, ymd, h)))
        if len(row) == 6:
            rows.append(row)
            row = []
    rows.append([T.btn("← День", "w:cal:%s:%s" % (tgt, ymd[:6])), T.btn("✕ Отмена", "w:list")])
    return T.Html("<b>◆ WHATSAPP · ЧАС</b>\n%s · <i>выберите час</i>" % T.esc(day.strftime("%d.%m.%Y"))), rows


def tg_minutes(tgt, ymd, hh):
    T = _T()
    day = dt.datetime.strptime(ymd, "%Y%m%d").date()
    now = dt.datetime.now()
    rows, row = [], []
    for mi in range(0, 60, 5):
        t = dt.datetime.combine(day, dt.time(int(hh), mi))
        if t < now - dt.timedelta(minutes=1):
            row.append(T.btn("·", "w:nop"))
        else:
            row.append(T.btn("%s:%02d" % (hh, mi), "w:pk:%s:%s%s%02d" % (tgt, ymd, hh, mi)))
        if len(row) == 4:
            rows.append(row)
            row = []
    rows.append([T.btn("← Час", "w:hr:%s:%s" % (tgt, ymd)), T.btn("✕ Отмена", "w:list")])
    return T.Html("<b>◆ WHATSAPP · МИНУТЫ</b>\n%s · <i>выберите минуты</i>\n"
                  "<i>Точнее 5 минут — напишите текстом, например «%s:07».</i>"
                  % (T.esc(day.strftime("%d.%m.%Y")), hh)), rows


def preset_due(key):
    today = dt.date.today()
    if key == "h1":
        return H.now() + 3600
    if key == "t20":
        return int(dt.datetime.combine(today, dt.time(20)).timestamp())
    if key == "m9":
        return int(dt.datetime.combine(today + dt.timedelta(days=1), dt.time(9)).timestamp())
    return None


def parse_due(text):
    """Срок из текста → (epoch | None, ошибка). Прошлое — нельзя (минута на запас)."""
    if re.search(r"(?i)\b(вчера|позавчера)\b", text):
        return None, "Это время уже прошло. " + WHEN_HINT
    _clean, due, _rep = H.parse_when(text)
    if not due:
        return None, "Не понял срок, сэр. " + WHEN_HINT
    if due < H.now() - 60:
        return None, "Это время уже прошло (%s). %s" % (when(due), WHEN_HINT)
    return due, ""


def tg_confirm(c, note=None):
    T = _T()
    d = draft_get(c)
    txt = "<b>◆ WHATSAPP · ПРОВЕРЬТЕ</b>\n<b>Кому:</b> %s\n<b>Когда:</b> %s\n\n%s" % (
        T.esc(d.get("name", "?")), T.esc(when(d["due"])), T.esc(d.get("text", "")))
    if note:
        txt = "<i>%s</i>\n" % T.esc(note) + txt
    return T.Html(txt), [[T.btn("✓ Запланировать", "w:ok")],
                         [T.btn("🕑 Время", "w:dtime"), T.btn("✎ Текст", "w:dtxt"), T.btn("✕ Отмена", "w:list")]]


def tg_wait(c, op, mid_id, text):
    """Ответ текстом на вопрос пульта /wa → (текст, кнопки)."""
    T = _T()
    text = text.strip()
    if op == "wa_who":
        return tg_pick(c, text)
    if op == "wa_text":
        if len(text) > TEXT_MAX:
            T.wait_set(c, "wa_text")
            return T.Html("Длиннее %d знаков, сэр. Сократите." % TEXT_MAX), None
        d = draft_get(c)
        d["text"] = text
        draft_set(c, d)
        if d.get("due"):
            return tg_confirm(c)
        T.wait_set(c, "wa_when")
        return T.Html("<b>◆ WHATSAPP · КОГДА</b>\n<b>Кому:</b> %s\n<i>%s</i>" % (
            T.esc(d.get("name", "")), WHEN_HINT)), when_buttons("w:at:")
    if op == "wa_when":
        due, err = parse_due(text)
        if not due:
            T.wait_set(c, "wa_when")
            return T.Html(T.esc(err)), when_buttons("w:at:")
        d = draft_get(c)
        d["due"] = due
        draft_set(c, d)
        return tg_confirm(c)
    if op == "wa_retime":
        due, err = parse_due(text)
        if not due:
            T.wait_set(c, "wa_retime", mid_id)
            return T.Html(T.esc(err)), when_buttons("w:rt:%d:" % mid_id)
        edit(c, mid_id, due=due)
        m = get(c, mid_id)
        return tg_card_text(m), tg_card_buttons(m)
    if op == "wa_retext":
        if check("+70000000000", text):
            T.wait_set(c, "wa_retext", mid_id)
            return T.Html(T.esc("Не записал: " + check("+70000000000", text))), None
        edit(c, mid_id, text=text)
        m = get(c, mid_id)
        return tg_card_text(m), tg_card_buttons(m)
    return None


def tg_command(c, arg):
    """/wa — пульт; /wa имя — сразу к выбору контакта; /wa N — карточка N из пульта."""
    arg = arg.strip()
    if not arg:
        return tg_panel(c)
    if arg.isdigit() and len(arg) <= 3:
        mid = json.loads(H.meta_get(c, NUMS_KEY) or "{}").get(arg)
        m = get(c, mid) if mid else None
        if m is None:
            return "Нет номера %s в пульте /wa." % arg, None
        return tg_card_text(m), tg_card_buttons(m)
    if arg in ("history", "история", "sent", "журнал"):
        return tg_panel(c, sent=True)
    if arg in ("clear", "очистить"):
        return tg_clear_ask(c)
    if arg in ("stop", "стоп"):
        return tg_stop_ask(c)
    if arg in ("resume", "вернуть"):
        n = resume_all(c)
        return tg_panel(c, note="↺ Снова ждут: %d." % n if n else "Возвращать нечего.")
    draft_set(c, {})
    return tg_pick(c, arg)


def tg_clear_ask(c):
    T = _T()
    n = history_count(c)
    if not n:
        return tg_panel(c, sent=True, note="Журнал и так пуст.")
    return (T.Html("<b>◆ WHATSAPP · ОЧИСТИТЬ ЖУРНАЛ?</b>\nСотру насовсем записей: %d — отправленные и "
                   "отменённые. Очередь не трогаю. Вернуть будет нельзя." % n),
            [[T.btn("🗑 Да, стереть", "w:clrok"), T.btn("← Нет", "w:sent")]])


def tg_stop_ask(c):
    T = _T()
    n = pending_count(c)
    if not n:
        return tg_panel(c, note="Ничего не ждёт — останавливать нечего.")
    return (T.Html("<b>◆ WHATSAPP · ОСТАНОВИТЬ ВСЁ?</b>\nОтменю все запланированные: %d. Не стираю — "
                   "вернуть можно одной кнопкой или <code>/wa resume</code>." % n),
            [[T.btn("⏹ Да, остановить", "w:stopok"), T.btn("← Нет", "w:list")]])


def tg_pick_apply(c, tgt, stamp):
    """Выбрано кнопками: yyyymmddHHMM → черновик или запись."""
    T = _T()
    try:
        due = int(dt.datetime.strptime(stamp, "%Y%m%d%H%M").timestamp())
    except ValueError:
        return tg_cal(tgt, dt.date.today().strftime("%Y%m"), note="Не понял дату — выберите ещё раз.")
    if due < H.now() - 60:
        return tg_cal(tgt, stamp[:6], note="Это время уже прошло — выберите позже.")
    H.meta_set(c, T.WAIT_KEY, "null")
    if tgt == "d":
        d = draft_get(c)
        d["due"] = due
        draft_set(c, d)
        return tg_confirm(c)
    m = get(c, int(tgt))
    if m is None:
        return tg_panel(c, note="Не нашёл.")
    if not edit(c, m["id"], due=due):
        return tg_panel(c, note="Уже не ждёт — время не изменить.")
    m = get(c, m["id"])
    return tg_card_text(m), tg_card_buttons(m)


def tg_callback(c, bot, chat, msg, cb_id, rest):
    T = _T()
    a = rest.split(":")
    act = a[0]
    i = int(a[1]) if len(a) > 1 and a[1].isdigit() else None
    res, toast = None, ""
    pick_ok = len(a) > 2 and (a[1] == "d" or a[1].isdigit()) and a[2].isdigit()
    if act == "nop":
        pass
    elif act == "cal" and pick_ok and len(a[2]) == 6:
        res = tg_cal(a[1], a[2])
    elif act == "hr" and pick_ok and len(a[2]) == 8:
        res = tg_hours(a[1], a[2])
    elif act == "mi" and pick_ok and len(a[2]) == 8 and len(a) > 3 and a[3].isdigit() and int(a[3]) < 24:
        res = tg_minutes(a[1], a[2], "%02d" % int(a[3]))
    elif act == "pk" and pick_ok and len(a[2]) == 12:
        res = tg_pick_apply(c, a[1], a[2])
    elif act == "list":
        H.meta_set(c, T.WAIT_KEY, "null")
        res = tg_panel(c)
    elif act == "sent":
        res = tg_panel(c, sent=True)
    elif act == "stopask":
        res = tg_stop_ask(c)
    elif act == "stopok":
        n = stop_all(c)
        toast = "Остановлено: %d" % n
        res = (tg_panel(c, note="⏹ Остановлено: %d. Ничего не уйдёт." % n)[0],
               [[T.btn("↺ Вернуть все", "w:resume"), T.btn("← Пульт", "w:list")]])
    elif act == "resume":
        n = resume_all(c)
        toast = "Вернул: %d" % n
        res = tg_panel(c, note="↺ Снова ждут: %d." % n if n else "Возвращать нечего.")
    elif act == "clr":
        res = tg_clear_ask(c)
    elif act == "clrok":
        n = clear_history(c)
        toast = "Стёрто: %d" % n
        res = tg_panel(c, sent=True, note="🗑 Журнал очищен: стёрто записей — %d." % n)
    elif act == "new":
        draft_set(c, {})
        T.wait_set(c, "wa_who", None, chat, msg)
        res = T.Html("<b>◆ WHATSAPP · КОМУ</b>\n<i>Напишите имя или номер, сэр.</i>"), \
            [[T.btn("✕ Отмена", "w:list")]]
    elif act == "to" and len(a) > 1 and a[1].isdigit():
        jid = a[1] + "@s.whatsapp.net"
        x = by_jid(jid)
        name = x["name"] if x else "+" + a[1]
        if not x:                                   # номер вне книги — отправщик проверит сам
            jid = "+" + a[1]
        d = draft_get(c)
        d.update(jid=jid, name=name)
        draft_set(c, d)
        if d.get("text") and d.get("due"):
            res = tg_confirm(c)
        else:
            T.wait_set(c, "wa_text", None, chat, msg)
            res = T.Html("<b>◆ WHATSAPP · ТЕКСТ</b>\n<b>Кому:</b> %s\n<i>Напишите сообщение — "
                         "отправлю его как есть.</i>" % T.esc(name)), [[T.btn("✕ Отмена", "w:list")]]
    elif act == "at":
        d = draft_get(c)
        d["due"] = preset_due(a[1])
        draft_set(c, d)
        H.meta_set(c, T.WAIT_KEY, "null")
        res = tg_confirm(c)
    elif act == "dtime":
        T.wait_set(c, "wa_when", None, chat, msg)
        res = T.Html("<b>◆ WHATSAPP · КОГДА</b>\n<i>%s</i>" % WHEN_HINT), when_buttons("w:at:")
    elif act == "dtxt":
        T.wait_set(c, "wa_text", None, chat, msg)
        res = T.Html("<b>◆ WHATSAPP · ТЕКСТ</b>\n<i>Напишите новый текст.</i>"), [[T.btn("✕ Отмена", "w:list")]]
    elif act == "ok":
        d = draft_get(c)
        if not (d.get("jid") and d.get("text") and d.get("due")):
            res = tg_panel(c, note="Черновик потерялся — начните заново.")
        elif d["due"] < H.now() - 60:
            T.wait_set(c, "wa_when", None, chat, msg)
            res = T.Html("Время уже прошло, сэр. " + WHEN_HINT), when_buttons("w:at:")
        elif check(d["jid"], d["text"]):
            res = tg_panel(c, note="Не записал: " + check(d["jid"], d["text"]))
        else:
            add(c, d["jid"], d["name"], d["text"], d["due"], "tg")
            draft_set(c, {})
            toast = "Запланировано"
            res = tg_panel(c, note="✓ Уйдёт %s: %s" % (when(d["due"]), d["name"]))
    elif act == "card" and i:
        m = get(c, i)
        res = (tg_card_text(m), tg_card_buttons(m)) if m else tg_panel(c, note="Не нашёл.")
    elif act == "now" and i:
        m = get(c, i)
        res = (T.Html("<b>Отправить сейчас?</b>\n%s → «%s»" % (T.esc(m["name"]), T.esc(short(m["text"], 80)))),
               [[T.btn("▶ Да, отправить", "w:nowok:%d" % i), T.btn("← Нет", "w:card:%d" % i)]])
    elif act == "nowok" and i:
        send_now(c, i)
        toast = "Отправляю"
        res = tg_panel(c, note="▶ Отправляю: уйдёт в ближайшие секунды.")
    elif act == "later" and i:
        postpone(c, i, 3600)
        m = get(c, i)
        toast = "Перенесено"
        res = tg_card_text(m), tg_card_buttons(m)
    elif act == "time" and i:
        T.wait_set(c, "wa_retime", i, chat, msg)
        res = T.Html("<b>◆ WHATSAPP · НОВОЕ ВРЕМЯ</b>\n<i>%s</i>" % WHEN_HINT), when_buttons("w:rt:%d:" % i)
    elif act == "rt" and i:
        edit(c, i, due=preset_due(a[2]))
        H.meta_set(c, T.WAIT_KEY, "null")
        m = get(c, i)
        res = tg_card_text(m), tg_card_buttons(m)
    elif act == "txt" and i:
        T.wait_set(c, "wa_retext", i, chat, msg)
        res = T.Html("<b>◆ WHATSAPP · ТЕКСТ</b>\n<i>Напишите новый текст.</i>"), [[T.btn("← Назад", "w:card:%d" % i)]]
    elif act == "cancel" and i:
        cancel(c, i)
        toast = "Отменено"
        m = get(c, i)
        res = tg_card_text(m), tg_card_buttons(m)
    elif act == "back" and i:
        restore(c, i)
        m = get(c, i)
        res = tg_card_text(m), tg_card_buttons(m)
    bot.answer(cb_id, toast)
    if res:
        try:
            bot.edit(chat, msg, *res)
        except Exception:
            bot.send(chat, *res)
