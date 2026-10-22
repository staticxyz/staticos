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
  source TEXT NOT NULL DEFAULT 'cli',
  prio INTEGER NOT NULL DEFAULT 0,          -- важность: 0 Default, 1 Mid, 2 High
  pos REAL);                                -- ручной порядок в окне (Alt+j/k)
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
CREATE TABLE IF NOT EXISTS journal(          -- сон, пробуждения, доставки: /log (21.10.2026)
  id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS journal_ts ON journal(ts);
CREATE TABLE IF NOT EXISTS outbox(
  id INTEGER PRIMARY KEY, created INTEGER NOT NULL, payload TEXT NOT NULL,
  sent_at INTEGER, tries INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tgmsgs(
  item_id INTEGER NOT NULL, chat INTEGER NOT NULL, mid INTEGER NOT NULL, sig TEXT NOT NULL DEFAULT '',
  created INTEGER NOT NULL, PRIMARY KEY(chat, mid));
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS wa(                -- отложенные сообщения WhatsApp (hubwa.py, 15.10.2026)
  id INTEGER PRIMARY KEY,
  jid TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
  text TEXT NOT NULL,
  due INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',   -- pending | sending | sent | ask | cancelled
  created INTEGER NOT NULL, updated_at INTEGER NOT NULL,
  sent_at INTEGER, tries INTEGER NOT NULL DEFAULT 0, next_try INTEGER,
  error TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'pc',
  hidden INTEGER NOT NULL DEFAULT 0);        -- убрано из истории (dd в окне), не стёрто
CREATE INDEX IF NOT EXISTS wa_due ON wa(status, due);
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
    _migrate(c)
    for f in (path, path + "-wal", path + "-shm"):   # задачи и тексты WhatsApp — только владельцу
        try:
            if os.stat(f).st_mode & 0o077:
                os.chmod(f, 0o600)
        except OSError:
            pass
    return c


PRIO_NAMES = {2: "High", 1: "Mid", 0: "Default"}
# повтор (поле «повтор» в hub_app, 14.10.2026): по умолчанию нет
REPEATS = ("", "daily", "weekly", "monthly")
REPEAT_NAMES = {"": "нет", "daily": "день", "weekly": "неделя", "monthly": "месяц"}


def _migrate(c):
    """13.10.2026: важность (prio) и ручной порядок (pos) — в старую базу. Порядок
    заполняется тем, что был (срок, потом номер), чтобы список не перемешался."""
    cols = {r[1] for r in c.execute("PRAGMA table_info(items)")}
    for col, decl in (("prio", "INTEGER NOT NULL DEFAULT 0"), ("pos", "REAL"),
                      ("allday", "INTEGER NOT NULL DEFAULT 0"), ("rbase", "INTEGER")):
        if col not in cols:
            try:
                c.execute("ALTER TABLE items ADD COLUMN %s %s" % (col, decl))
            except sqlite3.OperationalError:
                pass                         # другой процесс успел первым
            if col == "rbase":       # 16.10.2026: опорный срок повтора = нынешний срок
                c.execute("UPDATE items SET rbase=due WHERE repeat!='' AND rbase IS NULL")
            if col == "pos":
                ids = [r[0] for r in c.execute("SELECT id FROM items WHERE pos IS NULL "
                                               "ORDER BY (due IS NULL), due, id")]
                c.executemany("UPDATE items SET pos=? WHERE id=?",
                              [(i + 1, iid) for i, iid in enumerate(ids)])
    # 15.10.2026: wa.hidden — «убрать запись» из истории окна (u возвращает)
    if "hidden" not in {r[1] for r in c.execute("PRAGMA table_info(wa)")}:
        try:
            c.execute("ALTER TABLE wa ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
        except sqlite3.OperationalError:
            pass


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


# ───────────────────────────── журнал /log ─────────────────────────────
# 21.10.2026, просьба: «/log — просматривать все логи, пробуждения, в том числе плановые…
# бот не будет каждый раз отправлять сообщение, он просто напишет в лог. Лог — файлом.
# Удаляются каждые 2 недели, не полностью, а старые». Сон и пробуждения пишет hubd в
# journal, действия с пунктами уже лежат в events; отчёт собирает оба и журнал охраны.

JOURNAL_DAYS = 14
NOTE_KINDS = {"power": "питание", "wake": "пробуждение", "fire": "сработало"}
EVENT_NAMES = {"add": "новое", "done": "сделано", "drop": "удалено", "snooze": "отложено",
               "edit": "изменено", "prio": "важность", "reopen": "вернуто", "repeat": "повтор",
               "repeat-next": "следующий повтор", "pc": "ПК", "word": "слово",
               "wa_add": "WhatsApp: в очередь", "wa_sent": "WhatsApp: отправлено",
               "wa_edit": "WhatsApp: изменено", "wa_cancel": "WhatsApp: отменено",
               "wa_stop": "WhatsApp: остановлено", "wa_clear": "WhatsApp: очищено"}
WEEKDAY_NAMES = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


def note(c, kind, text, ts=None):
    """Запись в журнал /log; старше JOURNAL_DAYS дней тут же уходит."""
    t = ts or now()
    c.execute("INSERT INTO journal(ts,kind,text) VALUES(?,?,?)", (t, kind, str(text)))
    c.execute("DELETE FROM journal WHERE ts<?", (t - JOURNAL_DAYS * 86400,))


def log_report(c, days=JOURNAL_DAYS, guard_dir=None):
    """Текст файла /log за days дней (по возрастанию времени) и короткая сводка для подписи."""
    since = now() - days * 86400
    rows = [(r["ts"], NOTE_KINDS.get(r["kind"], r["kind"]), r["text"])
            for r in c.execute("SELECT ts, kind, text FROM journal WHERE ts>=? ORDER BY ts, id", (since,))]
    for r in c.execute("SELECT e.ts, e.kind, e.item_id, e.data, i.text AS itext, w.name AS wname "
                       "FROM events e LEFT JOIN items i ON i.id=e.item_id AND e.kind NOT LIKE 'wa_%' "
                       "LEFT JOIN wa w ON w.id=e.item_id AND e.kind LIKE 'wa_%' "
                       "WHERE e.ts>=? ORDER BY e.ts, e.id", (since,)):
        what = EVENT_NAMES.get(r["kind"], r["kind"]) if r["kind"] != "pc" else "команда"
        obj = r["itext"] or r["wname"] or ""
        line = what + (" «%s»" % _cut(obj, 70) if obj else "")
        if r["data"]:
            line += " · " + _cut(r["data"], 60)
        cat = "whatsapp" if r["kind"].startswith("wa_") else {"pc": "пк", "word": "словарь"}.get(r["kind"], "задачи")
        rows.append((r["ts"], cat, line))
    rows.sort(key=lambda x: x[0])
    power = [x for x in rows if x[1] in ("питание", "пробуждение")]
    planned = sum(1 for x in power if x[1] == "пробуждение" and "по часам" in x[2])
    fired = sum(1 for x in rows if x[1] == "сработало")
    out = ["staticOS hub · журнал за %d дн (%s — %s)" % (
               days, time.strftime("%d.%m %H:%M", time.localtime(since)), time.strftime("%d.%m.%Y %H:%M")),
           "Сон и питание: %d · плановых пробуждений: %d · сработало: %d · всего записей: %d" % (
               len(power), planned, fired, len(rows)),
           "Старше %d дней журнал удаляет сам." % JOURNAL_DAYS]
    day = None
    for ts, kind, text in rows:
        lt = time.localtime(ts)
        d = time.strftime("%d.%m", lt)
        if d != day:
            day = d
            out += ["", "── %s, %s ──" % (d, WEEKDAY_NAMES[lt.tm_wday])]
        out.append("%s  %-12s %s" % (time.strftime("%H:%M:%S", lt), kind, text))
    if not rows:
        out.append("Записей нет.")
    if guard_dir and os.path.isdir(guard_dir):
        for name in sorted(os.listdir(guard_dir)):
            try:
                if time.mktime(time.strptime(name[:10], "%Y-%m-%d")) + 86400 < since:
                    continue
                body = open(os.path.join(guard_dir, name), encoding="utf-8", errors="replace").read().strip()
            except (ValueError, OSError):
                continue
            if body:
                out += ["", "── Охрана · %s ──" % name[:10], body]
    summary = "Журнал за %d дн: сон и питание — %d (плановых пробуждений %d), сработало — %d." % (
        days, len(power), planned, fired)
    return "\n".join(out) + "\n", summary


def _cut(t, n):
    t = " ".join(str(t).split())
    return t if len(t) <= n else t[:n - 1] + "…"


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
    «каждую неделю», «5 числа» (ближайшее 5-е), «каждый месяц 5 числа», «каждое
    5 число». Не разобрал — due None (пункт сохраняется без срока)."""
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

    day = dom = None
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
    if day is None:
        # число месяца (14.10.2026: «каждый месяц 5 числа» давало срок None)
        m = re.search(r"\s(каждое\s+)?(\d{1,2})(?:-?(?:го|ое|е))?\s+числ[аоу]\s", low)
        if m and 1 <= int(m.group(2)) <= 31:
            dom = int(m.group(2))
            if m.group(1) and not repeat:
                repeat = "monthly"
            take(m)

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

    if day is None and hh is None and dom is None:
        return text.strip(), None, repeat
    if dom is not None:                                   # ближайшее такое число, ещё не прошедшее
        h_, m_ = (hh, mm) if hh is not None else (9, 0)
        y, mo = base.year, base.month
        for _ in range(14):
            try:
                cand = dt.datetime(y, mo, dom, h_, m_)
                if cand > base:
                    day = cand.date()
                    break
            except ValueError:                            # 31 числа нет в этом месяце
                pass
            y, mo = (y + 1, 1) if mo == 12 else (y, mo + 1)
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


# «Только дата» (15.10.2026, пользователь): напоминает в эти часы своего дня, пока не отмечено.
ALLDAY_HOURS = (9, 12, 15, 18)


def due_class(due, allday):
    """0 — дата и время, 1 — только дата, 2 — без срока."""
    return 2 if not due else 1 if allday else 0


def _new_pos(c, cls):
    """Место новой задачи (15.10.2026, пользователь): с датой и временем — выше задач «только
    дата», те — выше задач без срока. Встаёт перед первой открытой задачей класса ниже;
    ручной порядок Alt+j/k потом главнее."""
    rows = c.execute("SELECT pos, due, allday FROM items WHERE status='open' AND kind='task' "
                     "AND pos IS NOT NULL ORDER BY pos, id").fetchall()
    prev = None
    for r in rows:
        if due_class(r["due"], r["allday"]) > cls:
            return (prev + r["pos"]) / 2 if prev is not None else r["pos"] - 1
        prev = r["pos"]
    top = c.execute("SELECT MAX(pos) FROM items").fetchone()[0]
    return (top or 0) + 1


def _quiet(due, allday):
    """«Только дата» звенит с 09:00 того дня (дальше — ALLDAY_HOURS). Записали на сегодня, когда 9 уже прошло, —
    без звонка: задача и так перед глазами."""
    return bool(allday and due and due <= now())


def add_item(c, text, list_name=None, due=None, repeat="", source="cli", kind="task", prio=0,
             allday=False):
    text = text.strip()
    if not text:
        raise ValueError("пустой текст")
    lid = ensure_list(c, list_name)
    t = now()
    allday = int(bool(allday and due))
    quiet = _quiet(due, allday)
    cur = c.execute(
        "INSERT INTO items(list_id,text,kind,due,repeat,created,updated_at,source,prio,pos,allday,"
        "fired_pc,seen,rbase) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (lid, text, kind, due, repeat, t, t, source, int(prio), _new_pos(c, due_class(due, allday)),
         allday, t if quiet else None, int(quiet), due))
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


def rbase(it):
    """Опорный срок повтора: когда пункт стоял по расписанию. «Отложить» двигает только due,
    поэтому следующий раз считается от rbase — время дня не уползает (16.10.2026)."""
    try:
        return it["rbase"] or it["due"]
    except (IndexError, KeyError):
        return it["due"]


def done(c, iid, source="cli", ts=None):
    it = get_item(c, iid)
    if it is None or it["status"] != "open":
        return False
    if it["repeat"] and it["due"]:
        nd = _next_due(rbase(it), it["repeat"])
        ok = _apply(c, iid, ts, due=nd, rbase=nd, fired_pc=None, fired_tg=None, seen=0)
    else:
        ok = _apply(c, iid, ts, status="done", done_at=now(), seen=1)
    if ok:
        log(c, "done", iid, source)
    return ok


def repeat_catchup(c):
    """Повторяющийся пункт не отметили, а подошёл следующий раз — пункт сам переезжает на
    него и звенит заново. Один пункт на цикл (16.10.2026, просьба: «повторяющиеся
    дублируются»): раньше hubd при каждом звонке заводил копию на следующий раз, а старая
    теряла ↻ и висела рядом. Возвращает id переехавших."""
    t = now()
    moved = []
    for it in c.execute("SELECT * FROM items WHERE status='open' AND repeat!='' AND due IS NOT NULL"
                        ).fetchall():
        base = rbase(it)
        nxt = _next_due(base, it["repeat"], dt.datetime.fromtimestamp(base))
        if nxt is None or nxt > t:
            continue
        last = base
        while nxt is not None and nxt <= t:          # последний наступивший раз
            last, nxt = nxt, _next_due(nxt, it["repeat"], dt.datetime.fromtimestamp(nxt))
        c.execute("UPDATE items SET due=?, rbase=?, fired_pc=NULL, fired_tg=NULL, seen=0, nag=0, "
                  "updated_at=? WHERE id=?", (last, last, t, it["id"]))
        log(c, "repeat-next", it["id"], str(last))
        moved.append(it["id"])
    return moved


# Пробуждение ноутбука ради хаба (21.10.2026, просьба: «Делай. Для задач только дата тоже
# можно будить»). Всё, что хаб сделает сам в будущем: wake_alarm.py заводит на ближайшее часы
# RTC, вкладка Wakeups в App list показывает список. Прошедшее сюда не входит — его hubd
# отработает на первом же тике после пробуждения.
WAKE_KINDS = {"timer": "Таймер", "task": "Напоминание", "allday": "Только дата",
              "esc": "Повтор в Telegram", "wa": "WhatsApp", "outbox": "Недоставленное в Telegram"}
WAKE_ESC_MIN = 5            # как DEFAULT_ESC_MIN в hubd.py
WAKE_RETRY = 300            # недоставленное в Telegram — попробовать снова через 5 мин…
WAKE_RETRY_FOR = 1800       # …но не дольше получаса после создания (без сети не будить по кругу)


def wake_events(c, t=None):
    """[(epoch, вид, текст)] по времени: когда хабу нужно, чтобы ноутбук не спал."""
    t = t or now()
    esc = int(cfg("esc_min", WAKE_ESC_MIN)) * 60
    ev = []
    for it in c.execute("SELECT * FROM items WHERE status='open' AND due IS NOT NULL").fetchall():
        txt = it["text"]
        if it["allday"] and it["kind"] == "task":
            day = dt.datetime.fromtimestamp(it["due"]).date()
            if it["fired_pc"] is None:
                at = it["due"]
            else:
                at = next((x for x in (int(dt.datetime.combine(day, dt.time(h)).timestamp())
                                       for h in ALLDAY_HOURS) if x > it["fired_pc"]), None)
            if at and at > t:
                ev.append((at, "allday", txt))
        elif it["fired_pc"] is None:
            if it["due"] > t:
                ev.append((it["due"], it["kind"] if it["kind"] == "timer" else "task", txt))
        elif it["repeat"]:
            base = rbase(it)
            nxt = _next_due(base, it["repeat"], dt.datetime.fromtimestamp(base))
            if nxt and nxt > t:
                ev.append((nxt, it["kind"] if it["kind"] == "timer" else "task", txt))
        if it["kind"] == "task" and it["fired_pc"] is not None and it["fired_tg"] is None \
                and not it["seen"] and it["fired_pc"] + esc > t:
            ev.append((it["fired_pc"] + esc, "esc", txt))
    for m in c.execute("SELECT due, next_try, name, text FROM wa WHERE status='pending'").fetchall():
        at = m["next_try"] or m["due"]
        if at > t:
            ev.append((at, "wa", "%s: %s" % (m["name"], m["text"])))
    n = c.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL AND created>?",
                  (t - WAKE_RETRY_FOR,)).fetchone()[0]
    if n:
        ev.append((t + WAKE_RETRY, "outbox", "%d сообщ." % n))
    return sorted(ev)


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


def edit(c, iid, text=None, due="keep", list_name=None, source="cli", ts=None, allday=False):
    """allday — только вместе с due: новый срок «только дата» (иначе — с временем)."""
    f = {}
    if text is not None:
        f["text"] = text.strip()
    if due != "keep":
        allday = int(bool(allday and due))
        quiet = _quiet(due, allday)
        f.update(due=due, rbase=due, allday=allday, fired_pc=now() if quiet else None,
                 fired_tg=None, seen=int(quiet))
    if list_name:
        f["list_id"] = ensure_list(c, list_name)
    ok = bool(f) and _apply(c, iid, ts, **f)
    if ok:
        log(c, "edit", iid, source)
    return ok


def set_prio(c, iid, prio, source="cli"):
    ok = _apply(c, iid, None, prio=int(prio))
    if ok:
        log(c, "prio", iid, "%s %s" % (source, prio))
    return ok


def set_repeat(c, iid, repeat, source="cli"):
    it = get_item(c, iid)
    extra = {"rbase": rbase(it)} if it is not None and repeat else {}
    ok = _apply(c, iid, None, repeat=repeat or "", **extra)
    if ok:
        log(c, "repeat", iid, "%s %s" % (source, repeat or "-"))
    return ok


def set_pos(c, mapping):
    """{id: pos} — ручной порядок; срок и «последний пишет» не трогает."""
    c.executemany("UPDATE items SET pos=? WHERE id=?", [(p, i) for i, p in mapping.items()])


def mark_seen(c, iid):
    c.execute("UPDATE items SET seen=1 WHERE id=?", (iid,))


def rename_list(c, old, new):
    c.execute("UPDATE lists SET name=? WHERE name=? COLLATE NOCASE", (new.strip(), old))


# ───────────────────────────── показ ─────────────────────────────

RU_DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def fmt_when(due, base=None, allday=False):
    if not due:
        return ""
    base = base or dt.datetime.now()
    d = dt.datetime.fromtimestamp(due)
    delta = (d.date() - base.date()).days
    hm = "" if allday else d.strftime("%H:%M")
    if delta == 0:
        s = "сегодня " + hm
    elif delta == 1:
        s = "завтра " + hm
    elif delta == -1:
        s = "вчера " + hm
    elif 0 < delta < 7:
        s = "%s %s" % (RU_DOW[d.weekday()], hm)
    else:
        s = d.strftime("%d.%m") + (" " + hm if hm and hm != "09:00" else "")
    return s.strip()


def is_allday(it):
    try:
        return bool(it["due"] and it["allday"])
    except (IndexError, KeyError):
        return False


def when(it, base=None):
    """Срок пункта словами; у «только дата» — без времени."""
    return fmt_when(it["due"], base, is_allday(it))


def overdue(it, t=None):
    """Просрочено: срок прошёл; у «только дата» — когда прошёл весь день."""
    if not it["due"]:
        return False
    if is_allday(it):
        return dt.datetime.fromtimestamp(it["due"]).date() < dt.date.today()
    return it["due"] <= (t or now())


def fmt_secs(s):
    s = int(s)
    if s >= 3600:
        h, m = s // 3600, s % 3600 // 60
        return "%d ч%s" % (h, " %d мин" % m if m else "")
    if s >= 60:
        return "%d мин" % (s // 60) + (" %d с" % (s % 60) if s % 60 and s < 600 else "")
    return "%d с" % s


def fmt_item(it, base=None):
    when = fmt_when(it["due"], base, is_allday(it))
    over = it["status"] == "open" and overdue(it)
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


def find_word_by_id(c, wid):
    return c.execute("SELECT * FROM words WHERE id=?", (wid,)).fetchone()


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
