"""Собеседования (30.10.2026). Источник — заметки Obsidian `Вакансии/*`: их показывает «Журнал
встреч», их правят руками, а hub, бот и команда `iv` читают и пишут те же файлы. Напоминания —
производные: sync() сверяет их с заметками, перенос даты в Obsidian двигает и напоминания.

Просьба: «если я просто схожу на любое собеседование это уже будет считать успехом и мне ресурсы
дадут все равно». Поэтому факт похода — строка growth kind 'interview' (день собеседования, note —
компания): закрывает блок дня, а Замок (этап 3) начислит ресурсы из неё. Результат не важен."""
import datetime as dt
import os
import re
import subprocess
import urllib.parse
import zlib

import growth as G
import hublib as H

ROOT = os.environ.get("IV_ROOT") or os.path.expanduser("~/Documents/Vault/Вакансии")
TEMPLATE = os.path.join(os.path.dirname(ROOT), "Templates", "Interview.md")
VAULT_NAME = "Vault"
LIST = "Собеседования"
ACTIVE = ("Назначено", "Ожидание", "Прошёл")           # эти папки показывает «Журнал встреч»
ARCHIVE = ("Отклоненные", "Архив", "Офферы")           # его нижняя таблица
TRASH = os.path.join(os.path.dirname(ROOT), ".trash")  # корзина Obsidian
# статус → (папка, цвет в заметке)
STATUS = {"назначено": ("Назначено", "#00b0f0"), "переназначить": ("Ожидание", "#ffc000"),
          "ожидание": ("Ожидание", "#ffc000"), "сходил": ("Прошёл", "#8fe388"),
          "прошёл": ("Прошёл", "#00ffaa"),
          "отказ": ("Отклоненные", "#c00000"), "отменено": ("Отклоненные", "#c0504d"),
          "оффер": ("Офферы", "#00ffaa")}
VISITED = ("сходил", "прошёл")                         # эти статусы — поход: энергия Замка
FORMATS = {"онлайн": "онлайн", "online": "онлайн", "оффлайн": "оффлайн", "офлайн": "оффлайн",
           "offline": "оффлайн", "очно": "оффлайн"}
WEEK = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
CV = {"Java": "#f79646", "PHP": "#8064a2", "Go": "#4bacc6"}
ASK_AFTER = 90 * 60                                    # через столько спросить «сходили?»
HELP = ("Так, сэр:\n/iv — список\n/iv Tele2 03.11 15:00 онлайн — новое\n/iv done 1 — сходил\n"
        "/iv move 1 04.11 16:00 — перенос\n/iv cancel 1 — отмена")


# ── заметки ─────────────────────────────────────────────────────────────────

def _fields(text):
    """Свойства из шапки YAML: `ключ: значение`, списки склеиваются через запятую."""
    m = re.match(r"---\n(.*?)\n---(?:\n|$)", text, re.S)
    out, key = {}, None
    for line in (m.group(1).split("\n") if m else ()):
        kv = re.match(r"([^\s:][^:]*):\s*(.*)$", line)
        if kv:
            key, out[key] = kv.group(1), kv.group(2).strip()
        elif key and line.strip().startswith("- "):
            out[key] = ", ".join(x for x in (out[key], line.strip()[2:]) if x)
    return out


def _plain(s):
    """Значение без <font> и кавычек."""
    return re.sub(r"<[^>]+>", "", s or "").strip().strip("\"'").strip()


def _label(s):
    """Подпись markdown-ссылки: `[Java](https://…)` → Java."""
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", _plain(s))


def _when(s):
    """`2026-11-03T15:00:00`, `03.11.2026 15:00`, `2026-11-03` → (datetime, есть ли время)."""
    s = re.sub(r"^[\s\[\"']+|[\s\]\"']+$", "", s or "")
    m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})(.*)$", s)
    if m:
        s = "%s-%s-%s%s" % (m.group(3), m.group(2), m.group(1), m.group(4))
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})(?:[T\s]+(\d{1,2}):(\d{2}))?", s)
    if not m:
        return None, False
    y, mo, d, hh, mm = m.groups()
    try:
        return dt.datetime(int(y), int(mo), int(d), int(hh or 0), int(mm or 0)), hh is not None
    except ValueError:
        return None, False


def _status(s):
    low = _plain(s).lower().replace("прошел", "прошёл")
    return next((k for k in STATUS if k in low), "ожидание" if not low else low)


_cache = {"sig": None, "items": []}


def scan():
    """Активные собеседования: сперва ближайшие с датой, потом без неё, прошедшие в конце."""
    sig = signature()
    if sig != _cache["sig"]:                           # окно спрашивает на каждой отрисовке
        _cache.update(sig=sig, items=_read())
    return [dict(i) for i in _cache["items"]]


def _read(folders=ACTIVE):
    out = []
    for folder in folders:
        base = os.path.join(ROOT, folder)
        try:
            names = [e for e in os.scandir(base) if e.name.endswith(".md") and e.is_file()]
        except OSError:
            continue
        for e in names:
            try:
                with open(e.path, encoding="utf-8") as f:
                    fm = _fields(f.read())
            except OSError:
                continue
            when, timed = _when(fm.get("date"))
            out.append(dict(name=e.name[:-3], path=e.path, folder=folder, status=_status(fm.get("status")),
                            when=when, timed=timed, format=_plain(fm.get("interview_format")),
                            level=_plain(fm.get("level")), salary=_plain(fm.get("salary")),
                            contacts=_plain(fm.get("contacts")), link=_plain(fm.get("link")),
                            work=_plain(fm.get("format")), cv=_label(fm.get("cv")),
                            stack=_plain(fm.get("stack")), raw=fm))
    rank = {"назначено": 0, "переназначить": 1, "ожидание": 2}
    return sorted(out, key=lambda i: (rank.get(i["status"], 3), i["when"] or dt.datetime.max, i["name"]))


def board():
    """Таблицы «Журнала встреч»: [(подпись, записи)], те же отбор и порядок, что в его dataview.
    Заметки без статуса в архив не попадают: это старые вакансии без полей."""
    today = dt.date.today()
    eow = today + dt.timedelta(days=6 - today.weekday())
    nxt = lambda i: i["when"] and eow < i["when"].date() <= eow + dt.timedelta(days=7)
    rank = {"сходил": 1, "прошёл": 1, "назначено": 2, "переназначить": 3, "ожидание": 4}
    gone = {"отказ": 1, "отменено": 2, "архив": 3}
    active = sorted(_read(), key=lambda i: (rank.get(i["status"], 5), i["when"] or dt.datetime.max, i["name"]))
    old = sorted((i for i in _read(ARCHIVE) if i["raw"].get("status")),
                 key=lambda i: (gone.get(i["status"], 4), i["when"] or dt.datetime.max, i["name"]))
    return [("Эта неделя", [i for i in active if not nxt(i)]),
            ("Следующая неделя", [i for i in active if nxt(i)]), ("Архив", old)]


def signature(folders=ACTIVE):
    """Меняется при любой правке заметок: без неё sync раз в 15 секунд читал бы все файлы."""
    sig = []
    for folder in folders:
        try:
            sig += [(e.path, e.stat().st_mtime_ns) for e in os.scandir(os.path.join(ROOT, folder))]
        except OSError:
            pass
    return sorted(sig)


def _set_fields(path, **fields):
    """Записать свойства, не трогая остальной файл; ключа нет — допишется в конец шапки."""
    with open(path, encoding="utf-8") as f:
        text = f.read()
    m = re.match(r"---\n(.*?)\n---(?:\n|$)", text, re.S)
    head = m.group(1) if m else ""
    for k, v in fields.items():
        line = "%s:%s" % (k, "".join("\n  - " + x for x in v)) if isinstance(v, list) else "%s: %s" % (k, v)
        head, n = re.subn(r"^%s:.*(?:\n[ \t]+- .*)*$" % re.escape(k), lambda _m: line, head, count=1, flags=re.M)
        if not n:
            head = (head + "\n" + line).strip("\n")
    text = "---\n%s\n---\n%s" % (head, text[m.end():] if m else text)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def _status_value(status):
    return '<font color="%s">%s</font>' % (STATUS[status][1], status)


def _move(it, status):
    """Сменить статус; заметка едет в папку статуса, куда смотрит «Журнал встреч»."""
    _set_fields(it["path"], status=_status_value(status))
    it["status"] = status
    _to_folder(it, status)


def _to_folder(it, status):
    folder = STATUS[status][0]
    if folder == it["folder"]:
        return
    target = os.path.join(ROOT, folder, it["name"] + ".md")
    if os.path.exists(target):
        return                                         # чужой файл с тем же именем не затираем
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(it["path"], target)
    it["path"], it["folder"] = target, folder


def _new_note(name, when, timed, fmt):
    status = "назначено" if when else "ожидание"
    try:
        with open(TEMPLATE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = "---\nstatus:\ninterview_format:\ndate:\n---\n# Название вакансии\n"
    text = text.replace("# Название вакансии", "# " + name)
    text = re.sub(r"^\*\*Calendar:.*\n", "", text, flags=re.M)
    path = os.path.join(ROOT, STATUS[status][0], name + ".md")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    _set_fields(path, status=_status_value(status), interview_format=fmt or "",
                date=_date_value(when, timed) if when else "")
    return path


def _date_value(when, timed):
    return when.strftime("%Y-%m-%dT%H:%M:%S" if timed else "%Y-%m-%d")


def _parse(raw):
    """«Tele2 03.11 15:00 онлайн» → (имя, datetime, есть ли время, формат)."""
    fmt = ""
    for w in raw.split():
        if w.lower() in FORMATS:
            fmt = FORMATS[w.lower()]
            raw = re.sub(r"(?<!\S)%s(?!\S)" % re.escape(w), " ", raw)
    rest, due, _rep = H.parse_when(raw)
    timed = bool(re.search(r"\d:\d\d|(?<!\S)в\s+\d{1,2}(?!\S)|утром|вечером|днём|через", raw.lower()))
    name = re.sub(r'[\\/:*?"<>|#^\[\]]', " ", rest)
    return " ".join(name.split()), dt.datetime.fromtimestamp(due) if due else None, timed, fmt


def create(c, raw, need_date=True):
    """Новое собеседование; та же компания — новая дата в её заметке. → подпись или None.
    Таблица заводит и без даты: отклик уже есть, собеседования ещё нет."""
    name, when, timed, fmt = _parse(raw)
    if not name or not when and need_date:
        return None
    if not when:
        _new_note(name, None, False, fmt)
        return "🎯 %s: дата не назначена" % name
    known = next((i for i in scan() if i["name"].lower() == name.lower()), None)
    if known:
        _set_fields(known["path"], date=_date_value(when, timed))
        _move(known, "назначено")
        name = known["name"]
    else:
        _new_note(name, when, timed, fmt)
    sync(c, force=True)
    return "🎯 %s: %s" % (name, when_text(when, timed))


def when_text(when, timed=True):
    if when is None:
        return "дата не назначена"
    days = (when.date() - dt.date.today()).days
    word = {0: "сегодня", 1: "завтра"}.get(days)
    day = word or "%s %02d.%02d" % (WEEK[when.weekday()], when.day, when.month)
    return day + (" " + when.strftime("%H:%M") if timed else "")


def find(ref):
    """По номеру из списка, контрольной сумме из кнопки или части названия."""
    items = scan()
    ref = str(ref).strip()
    if ref.isdigit() and 1 <= int(ref) <= len(items):
        return items[int(ref) - 1]
    for i in items:
        if key(i) == ref:
            return i
    hit = [i for i in items if ref.lower() in i["name"].lower()]
    return hit[0] if len(hit) == 1 else None


def key(it):
    return "%08x" % zlib.crc32(it["name"].encode())    # кнопка Telegram вмещает 64 байта


# ── отметка «сходил» ────────────────────────────────────────────────────────

def _visit_day(c, it):
    return it["when"].date() if it["when"] else G.today(c)


def _visit_rows(c, it):
    """Строки похода: у заметки с датой — за её день, без даты — любые с этим именем."""
    if it["when"]:
        return G.entries(c, it["when"].date(), "interview", it["name"])
    G.ensure(c)
    return c.execute("SELECT * FROM growth WHERE kind='interview' AND note=?", (it["name"],)).fetchall()


def visited(c, it):
    return bool(_visit_rows(c, it))


def visits(c):
    """Все походы: что Замок обратит в ресурсы (этап 3)."""
    G.ensure(c)
    return c.execute("SELECT * FROM growth WHERE kind='interview' ORDER BY day, id").fetchall()


def attend(c, it, src="pc", status="сходил"):
    """Сходил: статус и строка в growth. Повтор не считается дважды, «прошёл» не откатывается."""
    if not visited(c, it):
        G.add(c, "interview", 1, it["name"], src, day=_visit_day(c, it))
    if it["status"] != status and not (status == "сходил" and it["status"] in VISITED):
        _move(it, status)
    sync(c, force=True)


def unattend(c, it):
    """Отмена ошибочной отметки."""
    for r in _visit_rows(c, it):
        G.remove(c, r["id"])
    _move(it, "назначено")
    for r in c.execute("SELECT id FROM items WHERE source LIKE ? AND status!='open'",
                       ("iv|%s|%%" % it["name"],)).fetchall():
        H.reopen(c, r["id"], "iv")                     # иначе «Сделано» на вопросе засчиталось бы снова
    sync(c, force=True)


def move(c, it, raw):
    _rest, when, timed, _fmt = _parse("x " + raw)
    if not when:
        return None
    _set_fields(it["path"], date=_date_value(when, timed))
    _move(it, "назначено")
    sync(c, force=True)
    return when_text(when, timed)


def cancel(c, it):
    _move(it, "отменено")
    sync(c, force=True)


# ── правка из таблицы ───────────────────────────────────────────────────────

def _keep_font(old, value):
    """Новый текст в прежнем <font>, если значение было цветным: цвет — часть вида в Obsidian."""
    m = re.match(r"(<font[^>]*>).*</font>$", old or "")
    return m.group(1) + value + "</font>" if m and value else value


def set_cell(c, it, field, value):
    """Записать ячейку в заметку → None или текст, что не так."""
    value = " ".join(value.split())
    if field == "status":
        low = value.lower().replace("прошел", "прошёл")
        status = next((s for s in STATUS if s.startswith(low)), None) if low else None
        if status is None:
            return "статус: " + ", ".join(STATUS)
        if status in VISITED:
            attend(c, it, status=status)
        elif status == "назначено" and visited(c, it):
            unattend(c, it)                            # отметили по ошибке: энергия уходит вместе с ней
        else:
            _move(it, status)
    elif field == "date":
        if not value:
            _set_fields(it["path"], date="")
        else:
            _rest, when, timed, _fmt = _parse("x " + value)
            if not when:
                return "дата: 04.11 16:00"
            _set_fields(it["path"], date=_date_value(when, timed))
            if it["folder"] in ACTIVE and it["status"] not in VISITED:
                _move(it, "назначено")
    elif field == "stack":
        _set_fields(it["path"], stack=[x.strip() for x in value.split(",") if x.strip()])
    elif field in ("format", "level", "interview_format", "salary", "cv", "contacts", "link"):
        _set_fields(it["path"], **{field: _keep_font(it["raw"].get(field), value)})
    else:
        return "эту колонку не правят"
    sync(c, force=True)
    return None


def item(path):
    return next((i for i in _read(ACTIVE + ARCHIVE) if i["path"] == path), None)


def stack_words(n=8):
    """Частые слова стека по всем заметкам: кнопки формы."""
    seen = {}
    for i in _read(ACTIVE + ARCHIVE):
        for w in i["stack"].split(","):
            if w.strip():
                seen[w.strip()] = seen.get(w.strip(), 0) + 1
    return sorted(seen, key=lambda w: (-seen[w], w))[:n]


def _cv_value(label):
    """Резюме со ссылкой, если она уже встречалась в заметках, иначе цветной ярлык."""
    for i in _read(ACTIVE + ARCHIVE):
        m = re.match(r'"?\[(.+?)\]\((.+?)\)', i["raw"].get("cv") or "")
        if m and m.group(1) == label:
            return '"[%s](%s)"' % (label, m.group(2))
    return '<font color="%s">%s</font>' % (CV[label], label) if label in CV else label


def _yaml(value):
    """«@ник» без кавычек ломает шапку заметки в Obsidian."""
    return '"%s"' % value.replace('"', "'") if re.match(r"[@`*&!%|>{\[#'\"-]", value) or ": " in value else value


def _form_value(field, value):
    if not value:
        return ""
    if field == "interview_format" and value == "оффлайн":
        return '<font color="#c0504d">оффлайн</font>'
    if field == "format" and value != "оффлайн":
        return '<font color="#00b0f0">%s</font>' % value
    if field == "link" and value.startswith("http"):
        return '"[Click](%s)"' % value
    return _cv_value(value) if field == "cv" else value


def save_form(c, f, it=None):
    """Форма пишет только то, что в ней меняли (f): чужое оформление заметки остаётся.
    Та же компания — та же заметка. → (текст ошибки, None) или (None, путь)."""
    name = " ".join(re.sub(r'[\\/:*?"<>|#^\[\]]', " ", f.get("name") or (it["name"] if it else "")).split())
    if not name:
        return "нужно название компании", None
    it = it or next((i for i in _read(ACTIVE + ARCHIVE) if i["name"].lower() == name.lower()), None)
    if it is None:
        it = item(_new_note(name, f.get("when"), f.get("timed", False), ""))
    elif it["name"] != name:
        said = rename(c, it, name)
        if said:
            return said, None
    fields = {k: _form_value(k, f[k]) for k in ("interview_format", "format", "cv", "link") if k in f}
    fields.update({k: _yaml(f[k]) for k in ("level", "salary", "contacts") if k in f})
    if "stack" in f:
        fields["stack"] = f["stack"]
    if "when" in f:
        fields["date"] = _date_value(f["when"], f["timed"]) if f["when"] else ""
    if fields:
        _set_fields(it["path"], **fields)
    if f.get("status") and f["status"] != it["status"]:
        set_cell(c, it, "status", f["status"])
    sync(c, force=True)
    return None, it["path"]


def rename(c, it, new):
    """Имя заметки = компания; походы в growth записаны по имени, едут вместе с ним."""
    new = " ".join(re.sub(r'[\\/:*?"<>|#^\[\]]', " ", new).split())
    target = os.path.join(os.path.dirname(it["path"]), new + ".md")
    if not new or os.path.exists(target):
        return "имя занято или пустое"
    os.replace(it["path"], target)
    c.execute("UPDATE growth SET note=? WHERE kind='interview' AND note=?", (new, it["name"]))
    G.invalidate()
    it["path"], it["name"] = target, new
    sync(c, force=True)
    return None


def snapshot(it):
    with open(it["path"], encoding="utf-8") as f:
        return it["path"], f.read()


def restore(c, now, snap):
    """Откат: файл снова там и такой, как в снимке. now — где он сейчас; снимок None — файла не было."""
    if now and now != (snap[0] if snap else None) and os.path.exists(now):
        os.remove(now)
    if snap:
        os.makedirs(os.path.dirname(snap[0]), exist_ok=True)
        with open(snap[0], "w", encoding="utf-8") as f:
            f.write(snap[1])
        name = os.path.basename(snap[0])[:-3]
        for r in c.execute("SELECT id FROM items WHERE source LIKE ? AND status!='open' AND due>?",
                           ("iv|%s|%%" % name, int(dt.datetime.now().timestamp()))).fetchall():
            H.reopen(c, r["id"], "iv")                 # снятые напоминания возвращаются вместе с заметкой
    sync(c, force=True)


def trash(c, it):
    """Убрать заметку насовсем: в корзину Obsidian, откуда её можно достать."""
    os.makedirs(TRASH, exist_ok=True)
    target = os.path.join(TRASH, it["name"] + ".md")
    n = 1
    while os.path.exists(target):
        n += 1
        target = os.path.join(TRASH, "%s %d.md" % (it["name"], n))
    os.replace(it["path"], target)
    it["path"] = target
    sync(c, force=True)


def open_note(it):
    rel = os.path.relpath(it["path"], os.path.dirname(ROOT))
    url = "obsidian://open?vault=%s&file=%s" % (VAULT_NAME, urllib.parse.quote(rel))
    subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── напоминания: производные заметок ────────────────────────────────────────

def _wanted(it):
    """(метка, когда, текст) для назначенного собеседования."""
    w, name = it["when"], it["name"]
    if it["status"] != "назначено" or w is None:
        return []
    eve = dt.datetime.combine(w.date() - dt.timedelta(days=1), dt.time(20))
    out = [("eve", eve, "Завтра собеседование: %s%s" % (name, w.strftime(" в %H:%M") if it["timed"] else ""))]
    if it["timed"]:
        out += [("2h", w - dt.timedelta(hours=2), "Через 2 часа собеседование: " + name),
                ("30m", w - dt.timedelta(minutes=30), "Через 30 минут собеседование: " + name)]
    after = w + dt.timedelta(seconds=ASK_AFTER) if it["timed"] else dt.datetime.combine(w.date(), dt.time(18))
    return out + [("ask", after, "Сходили на собеседование %s? «Сделано» = сходил, главное сходить" % name)]


_seen = {"sig": None, "answered": set()}


def sync(c, force=False):
    """Сверить папки, отметки и напоминания с заметками. Запускается из hubd и после любой команды."""
    rows = {r["source"]: r for r in c.execute("SELECT * FROM items WHERE source LIKE 'iv|%'")}
    # «Сделано» на вопросе «сходили?» — отметка похода, откуда бы её ни нажали
    answered = [s for s, r in rows.items() if s.endswith("|ask") and r["status"] == "done"
                and (s, r["due"]) not in _seen["answered"]]
    sig = signature()
    if sig == _seen["sig"] and not force and not answered:
        return
    items = scan()
    for it in items:
        if it["status"] in STATUS:
            _to_folder(it, it["status"])               # статус сменили в Obsidian
        due = it["when"]
        src = "iv|%s|ask" % it["name"]
        if it["status"] == "назначено" and src in answered and due is not None:
            want = dict((t, d) for t, d, _x in _wanted(it))["ask"]
            _seen["answered"].add((src, rows[src]["due"]))
            if rows[src]["due"] == int(want.timestamp()):
                G.add(c, "interview", 1, it["name"], "reminder", day=due.date())
                _move(it, "сходил")
        elif it["status"] in VISITED and not visited(c, it):
            G.add(c, "interview", 1, it["name"], "obsidian", day=_visit_day(c, it))
    now = dt.datetime.now()
    wanted = {}
    for it in items:
        for tag, when, text in _wanted(it):
            wanted["iv|%s|%s" % (it["name"], tag)] = (int(when.timestamp()), text, tag)
    for src, (due, text, tag) in wanted.items():
        r = rows.get(src)
        if r is None:
            if due > now.timestamp() or tag == "ask":
                H.add_item(c, text, LIST, due=due, source=src, prio=3)
        elif r["due"] != due:                          # перенос: то же напоминание на новое время
            if r["status"] != "open":
                H.reopen(c, r["id"], "iv")
            H.edit(c, r["id"], text=text, due=due, source="iv")
    for src, r in rows.items():
        if src not in wanted and r["status"] == "open":
            H.drop(c, r["id"], "iv")
    _seen["sig"] = signature()


# ── вывод и команды ─────────────────────────────────────────────────────────

def line(it):
    bits = [when_text(it["when"], it["timed"]) if it["status"] == "назначено" else it["status"]]
    if it["status"] in VISITED and it["when"]:
        bits = [it["status"], "%02d.%02d" % (it["when"].day, it["when"].month)]
    return " · ".join(bits + [x for x in (it["format"], it["salary"]) if x])


def nearest():
    """Ближайшее назначенное, что ещё впереди."""
    now = dt.datetime.now()
    return next((i for i in scan() if i["status"] == "назначено" and i["when"] and
                 (i["when"] >= now or not i["timed"] and i["when"].date() == now.date())), None)


def tally(c):
    n = len(visits(c))
    return "Сходили — это успех, сэр, результат не важен. Всего собеседований: %d." % n


def command(c, arg, src="pc"):
    """Общая часть `iv` и /iv → (текст ответа, сменился ли список)."""
    a = arg.strip()
    w = a.split(None, 1)
    op = w[0].lower() if w else ""
    if op in ("done", "сходил", "cancel", "отмена", "move", "перенос", "undo") and w[1:]:
        ref, _, rest = w[1].partition(" ")
        it = find(ref)
        if it is None:
            return "Такого собеседования нет, сэр.", False
        if op in ("done", "сходил"):
            attend(c, it, src)
            return "🏆 %s. %s" % (it["name"], tally(c)), True
        if op in ("cancel", "отмена"):
            cancel(c, it)
            return "Отменил: %s." % it["name"], True
        if op == "undo":
            unattend(c, it)
            return "Вернул в назначенные: %s." % it["name"], True
        said = move(c, it, rest)
        return ("🎯 %s: %s" % (it["name"], said), True) if said else (HELP, False)
    said = create(c, a) if a else None
    return (said, True) if said else (HELP if a else listing(), False)


def listing():
    items = scan()
    if not items:
        return "Собеседований нет, сэр. Новое: iv Tele2 03.11 15:00 онлайн"
    return "\n".join("%d. %s — %s" % (i, it["name"], line(it)) for i, it in enumerate(items, 1))
