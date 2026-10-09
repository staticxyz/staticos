#!/usr/bin/env python3
"""hub — ядро напоминаний и словаря (09.10.2026). Без ИИ, только стандартная библиотека.

Общая база SQLite (WAL) для демона hubd.py, окна hub_app.py, команд rem / dict / hub
и Telegram-бота. Время — целые секунды UTC (epoch), показ — местное.

    пункт (items)     один тип записи: текст + необязательный срок. Без срока — задача
                      в списке, со сроком — напоминание, оно «стреляет».
    списки (lists)    «Входящие» по умолчанию.
    словарь (words)   термин → перевод, повторение по коробкам (Leitner).
    события (events)  журнал действий, откуда бы ни пришли (pc | tg | cli).

Правка с двух сторон — «последний пишет побеждает» по updated_at: apply(…, ts=…) не
перезаписывает более свежую запись.
"""
import datetime as dt
import json
import os
import re
import sqlite3
import time

HOME = os.path.expanduser("~")
DATA = os.environ.get("HUB_DATA") or os.path.join(HOME, ".local/share/hub")
CONF = os.environ.get("HUB_CONF") or os.path.join(HOME, ".config/hub")
DB = os.path.join(DATA, "hub.db")
DEFAULT_LIST = "Входящие"

SCHEMA = """
CREATE TABLE IF NOT EXISTS lists(
  id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS items(
  id INTEGER PRIMARY KEY,
  list_id INTEGER NOT NULL REFERENCES lists(id),
  text TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'task',        -- task | timer
  status TEXT NOT NULL DEFAULT 'open',      -- open | done | dropped
  due INTEGER,                              -- срок, epoch UTC
  repeat TEXT NOT NULL DEFAULT '',          -- '' | daily | weekly | monthly
  created INTEGER NOT NULL,
  updated_at INTEGER NOT NULL,
  done_at INTEGER,
  fired_pc INTEGER,                         -- когда показано на ПК
  fired_tg INTEGER,                         -- когда ушло в Telegram
  seen INTEGER NOT NULL DEFAULT 0,          -- 1 = отреагировал: эскалации в Telegram не будет
  nag INTEGER NOT NULL DEFAULT 0,           -- сколько ступеней «запылился» уже напомнено
  source TEXT NOT NULL DEFAULT 'cli');
CREATE INDEX IF NOT EXISTS items_due ON items(status, due);
CREATE TABLE IF NOT EXISTS words(
  id INTEGER PRIMARY KEY,
  term TEXT NOT NULL, translation TEXT NOT NULL,
  context TEXT NOT NULL DEFAULT '',
  src TEXT NOT NULL DEFAULT 'en', dst TEXT NOT NULL DEFAULT 'ru',
  created INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  box INTEGER NOT NULL DEFAULT 0,
  next_review INTEGER NOT NULL,
  reps INTEGER NOT NULL DEFAULT 0, lapses INTEGER NOT NULL DEFAULT 0,
  UNIQUE(term, src, dst));
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL,
  item_id INTEGER, data TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY, created INTEGER NOT NULL, payload TEXT NOT NULL,
  sent_at INTEGER, tries INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tgmsgs(
  item_id INTEGER NOT NULL, chat INTEGER NOT NULL, mid INTEGER NOT NULL, sig TEXT NOT NULL DEFAULT '',
  created INTEGER NOT NULL, PRIMARY KEY(chat, mid));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# коробки Leitner: через сколько дней показать слово снова после верного ответа
BOX_DAYS = [0, 1, 3, 7, 14, 30, 90]


def now():
    return int(time.time())


def connect(path=None):
    path = path or DB
    os.makedirs(os.path.dirname(path), exist_ok=True)
    c = sqlite3.connect(path, timeout=10, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    c.executescript(SCHEMA)
    return c


def config():
    try:
        with open(os.path.join(CONF, "config.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def cfg(key, default=None):
    return config().get(key, default)


def meta_get(c, k, default=None):
    r = c.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def meta_set(c, k, v):
    c.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def log(c, kind, item_id=None, data=""):
    c.execute("INSERT INTO events(ts,kind,item_id,data) VALUES(?,?,?,?)", (now(), kind, item_id, str(data)))


# ───────────────────────────── разбор времени ─────────────────────────────

WEEKDAYS = {"понедельник": 0, "пн": 0, "вторник": 1, "вт": 1, "среду": 2, "среда": 2, "ср": 2,
            "четверг": 3, "чт": 3, "пятницу": 4, "пятница": 4, "пт": 4, "субботу": 5, "суббота": 5,
            "сб": 5, "воскресенье": 6, "вс": 6}
PARTS = {"утром": 9, "днём": 13, "днем": 13, "вечером": 19, "ночью": 23}
UNIT = [("сек", 1), ("с", 1), ("мин", 60), ("м", 60), ("час", 3600), ("ч", 3600),
        ("ден", 86400), ("дн", 86400), ("д", 86400), ("недел", 604800), ("нед", 604800)]
SPECIAL = {"полчаса": 1800, "час": 3600, "минуту": 60, "минутку": 60, "день": 86400,
           "неделю": 604800, "пару минут": 120, "полтора часа": 5400}


def _unit_secs(u):
    u = u.lower()
    for p, s in UNIT:
        if u.startswith(p):
            return s
    return None


def parse_duration(s):
    """«25», «25м», «1ч30», «1h 30m», «90с», «5 мин» → секунды; не длительность → None.
    Голое число — минуты."""
    s = s.strip().lower().replace(",", ".")
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return int(float(s) * 60)
    parts = re.findall(r"(\d+(?:\.\d+)?)\s*([a-zа-яё]*)", s)
    if not parts or re.sub(r"(\d+(?:\.\d+)?)\s*([a-zа-яё]*)\s*", "", s):
        return None
    total, last = 0.0, 60
    for i, (n, u) in enumerate(parts):
        if u in ("h", "hr"):
            k = 3600
        elif u in ("m", "min"):
            k = 60
        elif u == "s":
            k = 1
        elif u == "d":
            k = 86400
        elif u == "":
            k = max(60, last // 60) if i else 60      # «1ч30» — хвост без единицы = минуты
            if i:
                k = 60
        else:
            k = _unit_secs(u)
        if k is None:
            return None
        last = k
        total += float(n) * k
    return int(total) or None


def parse_when(text, base=None):
    """Выделяет время из фразы. → (текст без времени, due epoch | None, repeat).

    Понимает: «через 2 часа», «через полчаса», «завтра», «послезавтра», «в пятницу»,
    «в 18:30», «в 9», «18.10», «18.10 в 10:00», «утром/вечером», «каждый день»,
    «каждую неделю». Не разобрал — due None (пункт сохраняется без срока)."""
    base = base or dt.datetime.now()
    t = " " + text.strip() + " "
    low = t.lower()
    due = None
    repeat = ""
    cut = []                                              # (start, end) вырезаемых кусков

    def take(m):
        cut.append(m.span())

    m = re.search(r"\s(каждый день|ежедневно)\s", low)
    if m:
        repeat = "daily"
        take(m)
    m = re.search(r"\s(каждую неделю|еженедельно)\s", low)
    if m:
        repeat = "weekly"
        take(m)
    m = re.search(r"\s(каждый месяц|ежемесячно)\s", low)
    if m:
        repeat = "monthly"
        take(m)

    # относительное: через …
    m = re.search(r"\sчерез\s+(полтора часа|пару минут|полчаса|час|минут[уку]|день|неделю)\s", low)
    if m:
        due = base + dt.timedelta(seconds=SPECIAL[m.group(1).replace("минутку", "минуту")]
                                  if m.group(1) in SPECIAL else 60)
        take(m)
    else:
        m = re.search(r"\sчерез\s+(\d+(?:[.,]\d+)?)\s*([a-zа-яё]+)\s", low)
        if m and _unit_secs(m.group(2)):
            due = base + dt.timedelta(seconds=float(m.group(1).replace(",", ".")) * _unit_secs(m.group(2)))
            take(m)
    if due is not None:
        return _clean(t, cut), int(due.timestamp()), repeat

    day = None
    m = re.search(r"\s(сегодня|завтра|послезавтра)\s", low)
    if m:
        day = base.date() + dt.timedelta(days=("сегодня", "завтра", "послезавтра").index(m.group(1)))
        take(m)
    if day is None:
        m = re.search(r"\s(?:в|во|на)?\s*(понедельник|вторник|среду|среда|четверг|пятницу|пятница|субботу|"
                      r"суббота|воскресенье|пн|вт|ср|чт|пт|сб|вс)\s", low)
        if m:
            wd = WEEKDAYS[m.group(1)]
            delta = (wd - base.weekday()) % 7 or 7
            day = base.date() + dt.timedelta(days=delta)
            take(m)
    if day is None:
        m = re.search(r"\s(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s", low)
        if m:
            d, mo = int(m.group(1)), int(m.group(2))
            y = int(m.group(3)) if m.group(3) else base.year
            y = y + 2000 if y < 100 else y
            try:
                day = dt.date(y, mo, d)
                if not m.group(3) and day < base.date():
                    day = dt.date(y + 1, mo, d)
                take(m)
            except ValueError:
                day = None

    hh = mm = None
    m = re.search(r"\s(?:в|к|at)?\s*(\d{1,2}):(\d{2})\s", low)
    if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
        hh, mm = int(m.group(1)), int(m.group(2))
        take(m)
    else:
        m = re.search(r"\s(?:в|к|at)\s+(\d{1,2})(?:\s*(?:час\w*|ч))?\s", low)
        if m and int(m.group(1)) < 24:
            hh, mm = int(m.group(1)), 0
            take(m)
    if hh is None:
        for w, h in PARTS.items():
            m = re.search(r"\s" + w + r"\s", low)
            if m:
                hh, mm = h, 0
                take(m)
                break

    if day is None and hh is None:
        return text.strip(), None, repeat
    if day is None:
        day = base.date()
        cand = dt.datetime.combine(day, dt.time(hh, mm))
        if cand <= base:
            day = day + dt.timedelta(days=1)
    if hh is None:
        hh, mm = 9, 0
    when = dt.datetime.combine(day, dt.time(hh, mm))
    return _clean(t, cut), int(when.timestamp()), repeat


def _span_of_date(low):
    m = re.search(r"\s(\d{1,2})\.(\d{1,2})(?:\.(\d{2,4}))?\s", low)
    return m.span() if m else None


def _clean(t, cut):
    out, pos = [], 0
    for a, b in sorted(cut):
        if a < pos:
            continue
        out.append(t[pos:a])
        out.append(" ")
        pos = b - 1 if b > a else b
    out.append(t[pos:])
    s = re.sub(r"\s+", " ", "".join(out)).strip(" ,;-—")
    s = re.sub(r"^(напомни(?:ть)?(?:\s+мне)?|remind(?:\s+me)?)\s+", "", s, flags=re.I)
    s = re.sub(r"^(что|о том что|про)\s+", "", s, flags=re.I)
    return s.strip(" ,;-—")


def split_list(text):
    """«Покупки: хлеб» или «#покупки хлеб» → (список, текст)."""
    m = re.match(r"^\s*([^\s:#]{1,40}(?: [^\s:]{1,20})?)\s*:\s+(.+)$", text, re.S)
    if m and len(m.group(1)) <= 40 and not re.search(r"\d{1,2}$", m.group(1)):
        return m.group(1).strip().capitalize(), m.group(2).strip()
    m = re.match(r"^\s*#(\S+)\s+(.+)$", text, re.S)
    if m:
        return m.group(1).replace("_", " ").capitalize(), m.group(2).strip()
    return DEFAULT_LIST, text.strip()


# ───────────────────────────── списки и пункты ─────────────────────────────

def ensure_list(c, name):
    name = (name or DEFAULT_LIST).strip() or DEFAULT_LIST
    r = c.execute("SELECT id FROM lists WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if r:
        return r["id"]
    return c.execute("INSERT INTO lists(name,created) VALUES(?,?)", (name, now())).lastrowid


def lists(c):
    return c.execute(
        "SELECT l.id, l.name, "
        "(SELECT count(*) FROM items i WHERE i.list_id=l.id AND i.status='open' AND i.kind='task') AS open "
        "FROM lists l ORDER BY l.name='" + DEFAULT_LIST + "' DESC, l.name").fetchall()


def add_item(c, text, list_name=None, due=None, repeat="", source="cli", kind="task"):
    text = text.strip()
    if not text:
        raise ValueError("пустой текст")
    lid = ensure_list(c, list_name)
    t = now()
    cur = c.execute(
        "INSERT INTO items(list_id,text,kind,due,repeat,created,updated_at,source) VALUES(?,?,?,?,?,?,?,?)",
        (lid, text, kind, due, repeat, t, t, source))
    log(c, "add", cur.lastrowid, source)
    return cur.lastrowid


def add_smart(c, raw, source="cli"):
    """Одна строка → пункт: список («Список: …»), срок (если разобрался), повтор."""
    lname, body = split_list(raw)
    clean, due, repeat = parse_when(body)
    if not clean:
        clean = body.strip()
    return add_item(c, clean, lname, due, repeat, source), due


def get_item(c, iid):
    return c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                     "WHERE i.id=?", (iid,)).fetchone()


def items(c, list_name=None, status="open", kind=None, limit=500):
    q = ("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id WHERE 1=1")
    a = []
    if status:
        q += " AND i.status=?"
        a.append(status)
    if list_name:
        q += " AND l.name=? COLLATE NOCASE"
        a.append(list_name)
    if kind:
        q += " AND i.kind=?"
        a.append(kind)
    q += " ORDER BY (i.due IS NULL), i.due, i.id LIMIT ?"
    a.append(limit)
    return c.execute(q, a).fetchall()


def _apply(c, iid, ts, **fields):
    """Запись полей с правилом «последний пишет»: ts старше updated_at — отказ (False)."""
    cur = get_item(c, iid)
    if cur is None:
        return False
    ts = ts or now()
    if ts < cur["updated_at"]:
        return False
    fields["updated_at"] = max(ts, now()) if ts >= now() - 5 else ts
    sets = ",".join(k + "=?" for k in fields)
    c.execute("UPDATE items SET " + sets + " WHERE id=?", list(fields.values()) + [iid])
    return True


def _next_due(due, repeat, base=None):
    d = dt.datetime.fromtimestamp(due)
    base = base or dt.datetime.now()
    step = {"daily": dt.timedelta(days=1), "weekly": dt.timedelta(days=7)}.get(repeat)
    if repeat == "monthly":
        while d <= base:
            y, m = (d.year + (d.month // 12), d.month % 12 + 1)
            try:
                d = d.replace(year=y, month=m)
            except ValueError:
                d = d.replace(year=y, month=m, day=28)
        return int(d.timestamp())
    if step is None:
        return None
    while d <= base:
        d += step
    return int(d.timestamp())


def done(c, iid, source="cli", ts=None):
    it = get_item(c, iid)
    if it is None or it["status"] != "open":
        return False
    if it["repeat"] and it["due"]:
        nd = _next_due(it["due"], it["repeat"])
        ok = _apply(c, iid, ts, due=nd, fired_pc=None, fired_tg=None, seen=0)
    else:
        ok = _apply(c, iid, ts, status="done", done_at=now(), seen=1)
    if ok:
        log(c, "done", iid, source)
    return ok


def snooze(c, iid, secs=None, until=None, source="cli", ts=None):
    it = get_item(c, iid)
    if it is None:
        return False
    due = until if until else now() + int(secs or 3600)
    ok = _apply(c, iid, ts, due=due, status="open", fired_pc=None, fired_tg=None, seen=0)
    if ok:
        log(c, "snooze", iid, "%s %s" % (source, due))
    return ok


def drop(c, iid, source="cli", ts=None):
    ok = _apply(c, iid, ts, status="dropped", seen=1)
    if ok:
        log(c, "drop", iid, source)
    return ok


def reopen(c, iid, source="cli"):
    ok = _apply(c, iid, None, status="open", done_at=None)
    if ok:
        log(c, "reopen", iid, source)
    return ok


def edit(c, iid, text=None, due="keep", list_name=None, source="cli", ts=None):
    f = {}
    if text is not None:
        f["text"] = text.strip()
    if due != "keep":
        f.update(due=due, fired_pc=None, fired_tg=None, seen=0)
    if list_name:
        f["list_id"] = ensure_list(c, list_name)
    ok = bool(f) and _apply(c, iid, ts, **f)
    if ok:
        log(c, "edit", iid, source)
    return ok


def mark_seen(c, iid):
    c.execute("UPDATE items SET seen=1 WHERE id=?", (iid,))


def rename_list(c, old, new):
    c.execute("UPDATE lists SET name=? WHERE name=? COLLATE NOCASE", (new.strip(), old))


# ───────────────────────────── показ ─────────────────────────────

RU_DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def fmt_when(due, base=None):
    if not due:
        return ""
    base = base or dt.datetime.now()
    d = dt.datetime.fromtimestamp(due)
    delta = (d.date() - base.date()).days
    hm = d.strftime("%H:%M")
    if delta == 0:
        s = "сегодня " + hm
    elif delta == 1:
        s = "завтра " + hm
    elif delta == -1:
        s = "вчера " + hm
    elif 0 < delta < 7:
        s = "%s %s" % (RU_DOW[d.weekday()], hm)
    else:
        s = d.strftime("%d.%m") + (" " + hm if hm != "09:00" else "")
    return s


def fmt_secs(s):
    s = int(s)
    if s >= 3600:
        h, m = s // 3600, s % 3600 // 60
        return "%d ч%s" % (h, " %d мин" % m if m else "")
    if s >= 60:
        return "%d мин" % (s // 60) + (" %d с" % (s % 60) if s % 60 and s < 600 else "")
    return "%d с" % s


def fmt_item(it, base=None):
    when = fmt_when(it["due"], base)
    over = it["due"] and it["status"] == "open" and it["due"] < now()
    mark = {"open": "·", "done": "✓", "dropped": "✗"}.get(it["status"], "·")
    if it["kind"] == "timer":
        mark = "⏱"
    rep = " ↻" if it["repeat"] else ""
    return "%s #%d %s%s%s" % (mark, it["id"], it["text"],
                              ("  [%s%s]" % ("!" if over else "", when)) if when else "", rep)


# ───────────────────────────── таймеры ─────────────────────────────

def start_timer(c, secs, name="", source="cli"):
    secs = int(secs)
    if not 1 <= secs <= 86400:
        raise ValueError("таймер от 1 секунды до суток")
    due = now() + secs
    iid = add_item(c, name.strip() or "Таймер %s" % fmt_secs(secs), "Таймеры", due, "", source, "timer")
    return iid, due


# ───────────────────────────── словарь ─────────────────────────────

def add_word(c, term, translation, context="", src="en", dst="ru"):
    term, translation = term.strip(), translation.strip()
    if not term or not translation:
        raise ValueError("нужны слово и перевод")
    t = now()
    r = c.execute("SELECT id FROM words WHERE term=? COLLATE NOCASE AND src=? AND dst=?",
                  (term, src, dst)).fetchone()
    if r:
        c.execute("UPDATE words SET translation=?, context=CASE WHEN ?<>'' THEN ? ELSE context END, "
                  "updated_at=? WHERE id=?", (translation, context, context, t, r["id"]))
        return r["id"], False
    cur = c.execute("INSERT INTO words(term,translation,context,src,dst,created,updated_at,next_review) "
                    "VALUES(?,?,?,?,?,?,?,?)", (term, translation, context.strip(), src, dst, t, t, t))
    log(c, "word", cur.lastrowid, term)
    return cur.lastrowid, True


def find_word(c, term):
    return c.execute("SELECT * FROM words WHERE term=? COLLATE NOCASE", (term.strip(),)).fetchone()


def words(c, q=None, limit=1000):
    if q:
        like = "%" + q.lower() + "%"
        return c.execute("SELECT * FROM words WHERE lower(term) LIKE ? OR lower(translation) LIKE ? "
                         "ORDER BY created DESC LIMIT ?", (like, like, limit)).fetchall()
    return c.execute("SELECT * FROM words ORDER BY created DESC LIMIT ?", (limit,)).fetchall()


def del_word(c, wid):
    c.execute("DELETE FROM words WHERE id=?", (wid,))


def due_words(c, n=5):
    return c.execute("SELECT * FROM words WHERE next_review<=? ORDER BY next_review LIMIT ?",
                     (now(), n)).fetchall()


def review(c, wid, ok):
    """Верно — коробка выше и пауза длиннее; неверно — в коробку 1, завтра."""
    w = c.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()
    if w is None:
        return None
    if ok:
        box = min(w["box"] + 1, len(BOX_DAYS) - 1)
        nxt = now() + BOX_DAYS[box] * 86400
        c.execute("UPDATE words SET box=?, next_review=?, reps=reps+1, updated_at=? WHERE id=?",
                  (box, nxt, now(), wid))
    else:
        box = 1
        nxt = now() + 86400 // 2 if w["box"] == 0 else now() + BOX_DAYS[1] * 86400
        c.execute("UPDATE words SET box=?, next_review=?, lapses=lapses+1, updated_at=? WHERE id=?",
                  (box, nxt, now(), wid))
    log(c, "review", wid, "ok" if ok else "miss")
    return box


def word_stats(c):
    r = c.execute("SELECT count(*) n, sum(next_review<=?) due, sum(box>=5) known FROM words",
                  (now(),)).fetchone()
    return {"total": r["n"] or 0, "due": r["due"] or 0, "known": r["known"] or 0}


# ───────────────────────────── перенос из twin-claude ─────────────────────────────

def import_twin(c, path=None):
    """reminders.json двойника → пункты. Возвращает сколько перенесено; повторно не дублирует."""
    path = path or os.path.join(HOME, ".config/twin-claude/reminders.json")
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return 0
    if isinstance(data, dict):
        data = data.get("items") or data.get("reminders") or list(data.values())
    n = 0
    for r in data if isinstance(data, list) else []:
        if not isinstance(r, dict):
            continue
        text = r.get("text") or r.get("message") or r.get("msg") or ""
        due = r.get("at") or r.get("due") or r.get("ts") or r.get("time")
        if isinstance(due, str):
            try:
                due = int(dt.datetime.fromisoformat(due).timestamp())
            except ValueError:
                due = None
        if not text or r.get("done") or r.get("sent"):
            continue
        if c.execute("SELECT 1 FROM items WHERE source='twin'").fetchone():
            continue
        lines = [re.sub(r"^\s*\d+[.)]\s*", "", l).strip() for l in text.splitlines() if l.strip()]
        for l in lines:                       # numbered list → пункты списка «Двойник», без срока
            add_item(c, l, "Двойник", None, "", "twin")
            n += 1
        c.execute("INSERT OR IGNORE INTO meta(k,v) VALUES('twin_due_note', ?)", (str(due),))
    return n
