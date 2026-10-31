"""growth — Better (28.10.2026, до 31.10 «Лучше вчера»): сон, программирование, рынок, прокрастинация,
деньги, сигареты, сила и быт на лестницах. Общий для окна hub (первая вкладка, hub_app.py) и бота hub
(/better, hubtg.py).

День — от пробуждения до сна, а не от полуночи (Пользователь 29.10: «после полуночи я могу ещё сидеть
за ПК, и для меня это всё ещё сегодня»). Граница дня — засыпание: начало долгого сна ПК
(журнал hub), без него — долгая тишина в экранном времени, без неё — 07:00, если вы ещё за ПК. См. night().

Само считается: подъём и отбой (сон ПК; часы разбудили ПК — встали при первом вводе, журнал
'input' от hubd; будильник «Я встал» главнее), помидоры pomo («programming», «речь»,
«гантели»…), экранное время: рынок — вкладка hh.kz, прокрастинация — YouTube, кино, игры
одним числом. Руками — таблица growth в hub.db (day — логический день):

    kind     value          note
    wake     минуты 0..1439  —            подъём руками (/sleep в боте, перебивает систему)
    bed      минуты 720..2159 —           отбой руками (после полуночи — +1440)
    spend    тенге           на что       трата (ещё и в Obsidian Finance/Logs.md, см. fin_*)
    cig      1               —            сигарета
    lift     минуты          «гантели»    тренировка (гантели, отжимания)
    chore    1               ключ CHORES  бытовое дело сделано
    ladder   порог ступени   показатель   ступень взята (день — когда, см. LADDER)

Цели — ступени лестницы LADDER: подъём к 05:00, отбой к 21:00, код к 5 ч. Взятая ступень не теряется,
вершину остаётся удерживать. С прошлым днём ничего не сравнивается, траты — только «обычно»
(медиана 14 дней).
"""
import datetime as dt
import glob
from collections import Counter
import json
import os
import re
import statistics
import time

POMO_LOG = os.path.expanduser("~/.local/share/pomo/log.tsv")
POMO_STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid(),
                          "pomo", "state")
WOKE = os.path.expanduser("~/.local/state/jarvis-wake/woke.json")
SCREEN = os.environ.get("JARVIS_SCREENTIME_DIR") or os.path.expanduser("~/.local/share/jarvis/screentime")

CODE_RE = re.compile(r"program|прогр|oop|ооп|java|code|код|leet|алгоритм", re.I)
SPEECH_RE = re.compile(r"речь|speech|дикци|скорогов|вслух|оратор|говор", re.I)
LIFT_RE = re.compile(r"гантел|отжим|трениров|workout|спорт|зарядк|турник|пресс", re.I)
# сайты — подписи экранного времени (screentime details: домен или имя сайта)
MARKET_SITE_RE = re.compile(r"(^|\.)hh\.(kz|ru|uz)$|headhunter", re.I)
MARKET_RE = re.compile(r"рынок|market|собес|интервью|резюме|вакан|отклик", re.I)   # помидоры на поиск работы
FUN_RE = re.compile(r"youtube|смотреть вместе|wparty|kinogo|rezka|кинопоиск|kinopoisk|netflix|twitch|"
                    r"tiktok|rutube|instagram|reddit|^vk$|вконтакте|anime|аниме|savefrom|cybershoke|"
                    r"серверы кс|картинка в картинке|кино|сериал", re.I)
# «YouTube: учёба» — ролики по правилам ~/.config/jarvis/youtube-study.txt (screentime_daemon,
# 29.10.2026): не прокрастинация
STUDY_SITE_RE = re.compile(r"учёба", re.I)
FUN_APP_NAMES = {"steam_app_730": "CS2", "steam": "Steam", "mpv": "mpv", "vlc": "VLC",
                 "org.videolan.VLC": "VLC", "celluloid": "Celluloid", "io.github.celluloid_player.Celluloid": "Celluloid"}
FUN_APPS = {"mpv", "vlc", "org.videolan.VLC", "io.github.celluloid_player.Celluloid", "celluloid", "steam"}
# + игры Steam (screentime: steam_app_<AppId>, CS2 = 730) — всё одним числом (Пользователь 29.10)

IDEAL_WAKE, IDEAL_BED = 5 * 60, 21 * 60
# План дня (30.10.2026, просьба: «лучше иметь какой-то стандарт/шаблон, если не знаю что выбрать, потом
# уже если захочу поставлю своё время»). Блок дня — минимум на цель: сначала рынок, затем код; откликов
# не считаем («лучше всего просто выделить N время»). Норма — потолок роста: дошли — дальше только
# удержать («в какой-то момент цель станет нереальной… надо добиться удержания такого темпа»); у
# прокрастинации норма — нижняя граница: столько отдыха всегда можно. Свои числа — `block` и /block.
PLAN_FILE = os.path.expanduser("~/.config/jarvis/better-plan.json")
GOAL_NAME = "Оффер"
BLOCK_KEYS = (("market", "Рынок"), ("code", "Код"))
BLOCK_DEFAULT = {"market": 10, "code": 20}     # минут; минимум для старта (31.10.2026, пользователь), было 30 и 50
NORM = {"code": 300, "market": 120, "speech": 30, "lift": 30, "fun": 60}     # минут
# Лестница (31.10.2026, просьба: «лучше не терять прогресс, и закреплять результат, потом в дальнейшем
# удерживать… один срыв не должен всё ломать»; потолки: код 5 ч, подъём 05:00, отбой 21:00). Сравнения
# со вчера больше нет: у показателя своя лестница, ступень берётся за HITS дней из WINDOW и уже не
# откатывается (growth: kind 'ladder', note — показатель, value — порог, день — когда взята). День ниже
# ступени просто серый. «Взято» — день достал до следующей ступени, «удержано» — до своей.
HITS, WINDOW = 5, 7
LADDER_DAY, DAYS_KEY = "g_ladder_day", "g_days"      # meta: до какого дня всё закреплено; итоги дней
LOWER = ("wake", "bed", "fun", "cig")  # меньше — лучше
CLOSED = ("fun", "cig")                # предел ясен только в конце дня
LADDER = {"wake": tuple(range(10 * 60, IDEAL_WAKE - 1, -30)),      # минуты дня
          "bed": tuple(range(28 * 60, IDEAL_BED - 1, -30)),        # по шкале evening(): 04:00 → 21:00
          "code": (20, 30, 60, 120, 180, 240), "market": (10, 20, 30, 60, 90), "speech": (10, 20), "lift": (10, 20),
          "fun": (420, 360, 300, 240, 180, 120),                   # минуты; вершина — норма из plan()
          "cig": (12, 10, 8, 6, 4, 2, 0)}
# Сигареты считаются с этого (логического) дня (Пользователь 29.10.2026: 28.10 неполный).
CIG_START = dt.date(2026, 10, 29)
START = dt.date(2026, 10, 28)          # неполный день до системы: только цифры
FIRST = START + dt.timedelta(days=1)     # первый день системы
LONG_SLEEP = 90                        # мин: сон ПК короче — дрёма, не ночь
DAY_START_H = 7                        # сна не видно — день сменяется не раньше 07:00
NIGHT_GAP = 40 * 60                    # часы разбудили ПК, он уснул снова за 40 мин — та же ночь

# строки вкладки по порядку; «Быт» — сводка, под ней чек-лист CHORES. 29.10.2026, просьба:
# «Речь между Силой и Сигаретами», «Траты в самый конец»
METRICS = (("wake", "Подъём"), ("bed", "Отбой"), ("code", "Программирование"),
           ("market", "Рынок (hh.kz)"), ("fun", "Прокрастинация"), ("cig", "Сигареты"),
           ("speech", "Речь"), ("lift", "Сила"), ("chores", "Быт"), ("money", "Траты"))
NAMES = dict(METRICS)
# (ключ, название, раз в N дней)
CHORES = (("teeth_am", "Зубы утром", 1), ("teeth_pm", "Зубы вечером", 1), ("cook", "Готовил сам", 2),
          ("trash", "Вынес мусор", 2), ("desk", "Убрал рабочее место", 3), ("hair", "Помыть голову", 3),
          ("shower", "Душ", 5), ("laundry", "Стирка", 7))
CHORE_NAMES = {k: n for k, n, _e in CHORES}


# ── база ────────────────────────────────────────────────────────────────────

def ensure(c):
    c.execute("CREATE TABLE IF NOT EXISTS growth (id INTEGER PRIMARY KEY, ts INTEGER NOT NULL,"
              " day TEXT NOT NULL, kind TEXT NOT NULL, value REAL NOT NULL DEFAULT 1,"
              " note TEXT NOT NULL DEFAULT '', src TEXT NOT NULL DEFAULT 'pc')")
    c.execute("CREATE INDEX IF NOT EXISTS growth_day ON growth(day, kind)")


def add(c, kind, value=1, note="", src="pc", day=None):
    ensure(c)
    cur = c.execute("INSERT INTO growth(ts, day, kind, value, note, src) VALUES (?,?,?,?,?,?)",
                    (int(time.time()), (day or today(c)).isoformat(), kind, float(value),
                     note, src))
    if kind == "spend":
        fin_append(get(c, cur.lastrowid))
    invalidate()
    return cur.lastrowid


def get(c, gid):
    ensure(c)
    return c.execute("SELECT * FROM growth WHERE id=?", (gid,)).fetchone()


def remove(c, gid):
    """Удалить запись; вернуть её (для отмены — put_back)."""
    r = get(c, gid)
    c.execute("DELETE FROM growth WHERE id=?", (gid,))
    if r is not None and r["kind"] == "spend":
        fin_remove(r)
    if r is not None and r["kind"] == "later":
        note_save(c, r["day"])
    invalidate()
    return r


def put_back(c, r):
    if r is not None:
        c.execute("INSERT OR REPLACE INTO growth(id, ts, day, kind, value, note, src)"
                  " VALUES (?,?,?,?,?,?,?)", tuple(r[k] for k in
                                                  ("id", "ts", "day", "kind", "value", "note", "src")))
        if r["kind"] == "spend":
            fin_append(r)
        if r["kind"] == "later":
            note_save(c, r["day"])
        invalidate()


def entries(c, day, kind, note=None):
    ensure(c)
    q, a = "SELECT * FROM growth WHERE day=? AND kind=?", [day.isoformat(), kind]
    if note is not None:
        q, a = q + " AND note=?", a + [note]
    return c.execute(q + " ORDER BY ts, id", a).fetchall()


def last_today(c, kind, note=None):
    rs = entries(c, today(c), kind, note)
    return rs[-1] if rs else None


# ── ввод текстом (окно и бот) ───────────────────────────────────────────────

def parse_hm(s):
    """«7», «730», «0730», «7:30», «7.30», «23-40» → минуты или None."""
    s = s.strip().lower().replace(".", ":").replace("-", ":").replace(" ", "")
    if ":" in s:
        h, _, m = s.partition(":")
    elif s.isdigit() and len(s) in (3, 4):
        h, m = s[:-2], s[-2:]
    else:
        h, m = s, "0"
    if not (h.isdigit() and m.isdigit()):
        return None
    h, m = int(h), int(m)
    return h * 60 + m if 0 <= h < 24 and 0 <= m < 60 else None


def evening(m):
    """Отбой на шкале «вечер → утро»: 01:30 позже 23:30 (= 25:30)."""
    return m + 1440 if m < 12 * 60 else m


def parse_sleep(text):
    """«0730» — подъём; «0730 2330» — подъём и отбой; «отбой 2330» / «лёг 1» — только отбой.
    → (подъём|None, отбой|None) или None."""
    t = text.lower().strip()
    bed_only = bool(re.match(r"(отбой|лёг|лег|лег[а-я]*|bed)\b", t))
    nums = [parse_hm(x) for x in re.findall(r"\d{1,2}[:.\-]?\d{0,2}", t)]
    if not nums or None in nums:
        return None
    if bed_only:
        return None, evening(nums[0])
    return nums[0], (evening(nums[1]) if len(nums) > 1 else None)


def parse_money(text):
    """«1500 обед», «1.5к такси», «2k» → (сумма, заметка) или None."""
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(к|k|тыс)?\b\.?\s*(?:₸|тг|тенге)?\s*(.*)$", text.lower())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    if m.group(2):
        v *= 1000
    note = text.strip()[len(text.strip()) - len(m.group(3)):].strip() if m.group(3) else ""
    return (v, note) if 0 <= v < 10 ** 8 else None


def parse_speech(text):
    """«15», «15 мин скороговорки», «1ч читал вслух» → (минут, заметка) или None."""
    m = re.match(r"\s*(\d+(?:[.,]\d+)?)\s*(ч|час[а-я]*|h|м|мин[а-я]*|m)?\b\.?\s*(.*)$", text.lower())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    if m.group(2) and m.group(2)[0] in "чh":
        v *= 60
    note = text.strip()[len(text.strip()) - len(m.group(3)):].strip() if m.group(3) else ""
    return (round(v), note) if 0 < v <= 600 else None


# ── источники ───────────────────────────────────────────────────────────────

_files = {}


def _cached(path, loader):
    try:
        m = os.stat(path).st_mtime
    except OSError:
        return None
    hit = _files.get(path)
    if hit and hit[0] == m:
        return hit[1]
    try:
        val = loader(path)
    except (OSError, ValueError):
        val = None
    _files[path] = (m, val)
    return val


def _pomo_log(path):
    out = []
    with open(path) as f:
        for line in f:
            p = line.rstrip("\n").split("\t")
            if len(p) >= 6 and p[2] == "work" and p[0].isdigit():
                try:
                    out.append((int(p[0]), int(p[4]), p[6] if len(p) > 6 else ""))
                except ValueError:
                    pass
    return out


def pomo_state():
    st = {}
    try:
        for line in open(POMO_STATE):
            k, _, v = line.strip().partition("=")
            st[k] = v
    except OSError:
        pass
    return st


def pomo_secs(t0, t1, rx):
    """Секунды работы помидорами в окне дня [t0, t1) по задачам rx; идёт сейчас — и идущий отрезок."""
    total = sum(sec for start, sec, task in (_cached(POMO_LOG, _pomo_log) or [])
                if t0 <= start < t1 and rx.search(task or ""))
    live = 0
    if t0 <= time.time() <= t1 + 30:
        st = pomo_state()
        if st.get("phase") == "work" and rx.search(st.get("task", "")):
            try:
                started, dur, paused = int(st["started"]), int(st["duration"]), int(st.get("paused") or 0)
                live = max(0, min(dur, (paused or int(time.time())) - started))
            except (KeyError, ValueError):
                pass
    return total + live, live > 0


def pomo_spans(t0, t1, rx):
    """Отрезки помидоров rx в окне [t0, t1) """
    out = [(start, start + sec) for start, sec, task in (_cached(POMO_LOG, _pomo_log) or [])
           if start < t1 and start + sec > t0 and rx.search(task or "")]
    st = pomo_state()
    if st.get("phase") == "work" and rx.search(st.get("task", "")):
        try:
            started, d, paused = int(st["started"]), int(st["duration"]), int(st.get("paused") or 0)
            out.append((started, started + max(0, min(d, (paused or int(time.time())) - started))))
        except (KeyError, ValueError):
            pass
    return _union(out)


def _union(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        elif b > a:
            out.append((a, b))
    return out


def _span_len(iv, t0, t1):
    return sum(max(0, min(b, t1) - max(a, t0)) for a, b in iv)


def _cross(a, b):
    """Длина пересечения двух объединённых списков отрезков."""
    i = j = n = 0
    while i < len(a) and j < len(b):
        n += max(0, min(a[i][1], b[j][1]) - max(a[i][0], b[j][0]))
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return n


def screen(day):
    return _cached(os.path.join(SCREEN, day.isoformat() + ".json"),
                   lambda p: json.load(open(p))) or {}


def _hour_floor(ts):
    lt = time.localtime(ts)
    return int(time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, lt.tm_hour, 0, 0, 0, 0, -1)))


def _hour_data(h):
    """Час, начинающийся в h: (файл дня, ключ часа)."""
    lt = time.localtime(h)
    return screen(dt.date(lt.tm_year, lt.tm_mon, lt.tm_mday)), str(lt.tm_hour)


def hour_act(h):
    d, k = _hour_data(h)
    return sum(((d.get("hours") or {}).get(k) or {}).values())


def screen_window(t0, t1):
    """Экранное время в [t0, t1): ({программа: с}, {сайт: с}). Часы — с долей перекрытия.
    Сайты — по часам (hdetails, пишет screentime_daemon с 29.10); в старых файлах их нет —
    дневные сайты раскладываются по часам пропорционально работе браузеров.

    Час, разрезанный краем окна, делится не по времени (30.10.2026, просьба: «откуда у меня 2м
    кс взялись я даже не запускал его»: игра кончилась в 03:30, отбой в 03:57 — и 3/60 часа
    списались на новый день). Внутри часа край — либо отбой, либо «сейчас», и всё записанное в
    таком часу случилось ДО него: час целиком у дня, который в нём закончился. Граница 07:00
    без сна идёт ровно по часу и сюда не попадает."""
    apps, sites = {}, {}
    h = _hour_floor(t0)
    while h < t1:
        f = 0.0 if h < t0 else 1.0
        d, k = _hour_data(h)
        if f > 0 and d:
            hr = (d.get("hours") or {}).get(k) or {}
            for a, v in hr.items():
                apps[a] = apps.get(a, 0) + v * f
            hd = (d.get("hdetails") or {}).get(k)
            if hd:
                for n, v in hd.items():
                    sites[n] = sites.get(n, 0) + v * f
            else:
                for n, v in _residual(d).get(k, {}).items():
                    sites[n] = sites.get(n, 0) + v * f
            # картинка в картинке без фокуса (screentime_daemon "bg", 29.10.2026) — тоже прокрастинация
            for n, v in ((d.get("bg") or {}).get(k) or {}).items():
                sites[n] = sites.get(n, 0) + v * f
        h += 3600
    return apps, sites


_resid = {}


def _residual(d):
    """Дневные сайты, которых нет в hdetails, — по часам без hdetails, по доле браузеров в часе."""
    key = id(d)
    hit = _resid.get(key)
    if hit and hit[0] is d:
        return hit[1]
    det = d.get("details") or {}
    hours, hd = d.get("hours") or {}, d.get("hdetails") or {}
    left = {}
    for a, m in det.items():
        for n, v in m.items():
            left[n] = left.get(n, 0) + v
    for m in hd.values():
        for n, v in m.items():
            left[n] = left.get(n, 0) - v
    w = {k: sum(v for a, v in hr.items() if a in det) for k, hr in hours.items() if k not in hd}
    tot = sum(w.values())
    out = {}
    if tot > 0:
        for k, wk in w.items():
            if wk > 0:
                out[k] = {n: v * wk / tot for n, v in left.items() if v > 1}
    _resid.clear()
    _resid[key] = (d, out)
    return out


def _woke(path):
    return json.load(open(path))


def _ts_min(ts):
    t = time.localtime(ts)
    return t.tm_hour * 60 + t.tm_min


def _day_ts(day):
    return int(time.mktime(day.timetuple()))


SLEPT_RE = re.compile(r"спал ((?:\d+ ч)?\s*(?:\d+ мин)?)[^,]*, с (?:\d\d\.\d\d )?(\d\d):(\d\d)")


def sleeps(c, t_from, t_to):
    """Сны ПК из журнала hub: «проснулся · спал 5 ч 43 мин, с 01:41» (power — разбудили руками) и
    «пробуждение по часам … спал …, с …» (wake — разбудили часы) → [{start, end, clock}],
    начало в [t_from, t_to)."""
    out = []
    for j in c.execute("SELECT ts, kind, text FROM journal WHERE kind IN ('wake','power') AND text LIKE '%спал %'"
                       " AND ts>=? AND ts<? ORDER BY ts", (t_from, t_to + 18 * 3600)):
        m = SLEPT_RE.search(j["text"] or "")
        if not m:
            continue
        h = re.search(r"(\d+) ч", m.group(1))
        mi = re.search(r"(\d+) мин", m.group(1))
        mins = (int(h.group(1)) * 60 if h else 0) + (int(mi.group(1)) if mi else 0)
        # начало — ближайшее HH:MM до записи о пробуждении
        t = time.localtime(j["ts"] - mins * 60)
        start = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, int(m.group(2)), int(m.group(3)), 0, 0, 0, -1))
        if start > j["ts"]:
            start -= 86400
        elif j["ts"] - start > (mins + 90) * 60:
            start += 86400
        if t_from <= start < t_to:
            out.append(dict(start=int(start), end=int(j["ts"]), clock=j["kind"] == "wake"))
    return out


def first_input(c, t0, t1):
    """Первый ввод после пробуждения ПК по часам (журнал 'input' — пишет hubd)."""
    try:
        r = c.execute("SELECT MIN(ts) FROM journal WHERE kind='input' AND ts>=? AND ts<?", (t0, t1)).fetchone()
        return r[0] if r and r[0] else None
    except Exception:
        return None


def first_active(t0, t1):
    """≈ начало работы по экранному времени: первый час с активностью ≥ 2 мин, работа — в его конце."""
    h = _hour_floor(t0)
    while h < t1:
        a = hour_act(h)
        if a >= 120:
            return max(t0, h + 3600 - a)
        h += 3600
    return None


_night = {}


def night(c, d):
    """Ночь перед днём d: {bed, up, bed_a, up_a} (ts; «≈» — догадка) или None — ещё не видно."""
    hit = _night.get(d)
    if hit and time.monotonic() - hit[0] < 60:
        return hit[1]
    try:
        v = _night_calc(c, d)
    except Exception:
        v = None
    _night[d] = (time.monotonic(), v)
    return v


def _night_calc(c, d):
    t0, now = _day_ts(d), time.time()
    # сны ПК: начались с 18:00 накануне до 12:00; часы разбудили, а ПК уснул снова — та же ночь
    merged = []
    for x in sorted(sleeps(c, t0 - 6 * 3600, t0 + 12 * 3600), key=lambda x: x["start"]):
        if merged and merged[-1]["clock"] and x["start"] - merged[-1]["end"] <= NIGHT_GAP:
            merged[-1].update(end=x["end"], clock=x["clock"])
        else:
            merged.append(dict(x))
    long = [x for x in merged if x["end"] - x["start"] >= LONG_SLEEP * 60 and x["end"] >= t0 + 3 * 3600]
    n = None
    if long:
        x = long[0]
        n = dict(bed=x["start"], bed_a="", up=x["end"], up_a="")
        if x["clock"]:                       # ПК разбудили часы — встали, когда тронули клавиатуру
            fi = first_input(c, x["end"], x["end"] + 12 * 3600)
            fa = None if fi else first_active(x["end"], min(now, x["end"] + 12 * 3600))
            n["up"], n["up_a"] = (fi, "") if fi else (fa, "≈") if fa else (x["end"], "≈")
    else:
        # ПК не спал: самая долгая тишина в экранном времени (< 2 мин в час, ≥ 3 ч), после которой вернулись.
        # 31.10.2026, просьба: уснули днём и встали после 14:00 — ночи до 14:00 нет, ищем дальше, до конца суток;
        # тишина с 12:00 и позже — это день вне дома, а дольше 16 ч — ноутбук лежал без вас, а не сон
        h, run, best = t0 - 6 * 3600, None, None
        while h < min(now, t0 + 24 * 3600) and not (best and h >= t0 + 14 * 3600):
            a = hour_act(h)
            if a < 120:
                run = run or h
            else:
                if run and run < t0 + 12 * 3600 and 3 * 3600 <= h - run <= 16 * 3600 and h >= t0 + 3 * 3600 \
                        and (not best or h - run > best[1] - best[0]):
                    best = (run, h, a)
                run = None
            h += 3600
        if best:
            pa = hour_act(best[0] - 3600)
            n = dict(bed=best[0] - 3600 + min(3600, pa) if pa >= 120 else best[0], bed_a="≈",
                     up=best[1] + 3600 - best[2], up_a="≈")
    # будильник «Я встал» — главнее
    w = (_cached(WOKE, _woke) or {}).get(d.isoformat())
    if w and parse_hm(w) is not None:
        up = t0 + parse_hm(w) * 60
        if n is None:
            n = dict(bed=min(t0 + DAY_START_H * 3600, up), bed_a="≈", up=up, up_a="")
        elif up >= n["bed"]:
            n.update(up=up, up_a="")
    return n


def boundary(c, d):
    """Начало дня d — засыпание накануне; сна не видно — 07:00. Сегодняшние 07:00 ещё не конец
    вчерашнего дня (31.10.2026, просьба: «пусть не сбрасывается пока я не усну»): новый день идёт,
    только если с 07:00 вы были за ПК. Тихо — граница ещё впереди: дальше либо сон, либо вернётесь."""
    n = night(c, d)
    if n:
        return n["bed"]
    t, now = _day_ts(d) + DAY_START_H * 3600, time.time()
    if d == dt.date.today() and now >= t and first_active(t, now) is None:
        return t + 86400
    return t


_td = {"t": 0, "v": None}


def today(c):
    """Логический сегодня: после полуночи и до сна — ещё вчерашний день."""
    if _td["v"] and time.monotonic() - _td["t"] < 20:
        return _td["v"]
    cal = dt.date.today()
    v = cal if time.time() >= boundary(c, cal) else cal - dt.timedelta(days=1)
    _td.update(t=time.monotonic(), v=v)
    return v


def window(c, d):
    """Окно дня d: [засыпание накануне, засыпание после) — сегодня по «сейчас»."""
    return boundary(c, d), min(boundary(c, d + dt.timedelta(days=1)), time.time())


def wake_info(c, day):
    """Подъём: (минуты|None, «≈» если по догадке)."""
    r = entries(c, day, "wake")
    if r:
        return int(r[-1]["value"]), ""
    n = night(c, day)
    return (_ts_min(n["up"]), n["up_a"]) if n else (None, "")


def bed_info(c, day):
    """Отбой в ночь перед day: (минуты на шкале evening|None, «≈»)."""
    r = entries(c, day, "bed")
    if r:
        return int(r[-1]["value"]), ""
    n = night(c, day)
    return (evening(_ts_min(n["bed"])), n["bed_a"]) if n else (None, "")


def sum_kind(c, day, kind):
    rs = entries(c, day, kind)
    return sum(r["value"] for r in rs), len(rs)


def chores_on(c, day):
    return {r["note"] for r in entries(c, day, "chore")}


def chore_last(c, key, before):
    ensure(c)
    r = c.execute("SELECT MAX(day) FROM growth WHERE kind='chore' AND note=? AND day<=?",
                  (key, before.isoformat())).fetchone()
    return dt.date.fromisoformat(r[0]) if r and r[0] else None


def day_values(c, day):
    """Все цифры дня — для сравнения и для недели в боте."""
    w, wa = wake_info(c, day)
    b, ba = bed_info(c, day)
    t0, t1 = window(c, day)
    apps, sites = screen_window(t0, t1)
    sp, spn = sum_kind(c, day, "spend")
    cg, _n = sum_kind(c, day, "cig")
    lv, ln = sum_kind(c, day, "lift")
    lp, l_live = pomo_secs(t0, t1, LIFT_RE)
    code, live = pomo_secs(t0, t1, CODE_RE)
    sp_min, sp_n = sum_kind(c, day, "speech")
    sp_pomo, sp_live = pomo_secs(t0, t1, SPEECH_RE)
    # помидор «рынок» и вкладка hh.kz идут разом, а экранное время — по часам, наложения не отделить:
    # берём большее, чтобы не считать одну минуту дважды
    mk_pomo, mk_live = pomo_secs(t0, t1, MARKET_RE)
    market = max(sum(v for n, v in sites.items() if MARKET_SITE_RE.search(n)), mk_pomo)
    fun_by = {}                         # откуда прокрастинация: {подпись: с} — «больше всего …»
    for n, v in sites.items():
        if FUN_RE.search(n) and not STUDY_SITE_RE.search(n):
            fun_by[n] = fun_by.get(n, 0) + v
    for a, v in apps.items():
        if a in FUN_APPS or a.startswith("steam_app_"):
            n = FUN_APP_NAMES.get(a) or ("игра Steam" if a.startswith("steam_app_") else a)
            fun_by[n] = fun_by.get(n, 0) + v
    fun = sum(fun_by.values())
    top = max(fun_by.items(), key=lambda kv: kv[1]) if fun_by else None
    return dict(wake=w, wake_a=wa, bed=b, bed_a=ba, t0=t0, t1=t1, code=code, code_live=live,
                fun_top=top,
                speech=int(sp_min * 60 + sp_pomo), speech_live=sp_live, speech_n=sp_n,
                market=int(market), market_live=mk_live, fun=int(fun), spend=sp, spend_n=spn, cig=int(cg),
                lift=int(lv * 60 + lp), lift_live=l_live, lift_n=ln, chores=len(chores_on(c, day)))


# ── числа ───────────────────────────────────────────────────────────────

def hm(m):
    return "%02d:%02d" % divmod(int(m) % 1440, 60)


def fun_top(T):
    """«YouTube 40 мин» — главный источник прокрастинации за день (29.10.2026, пользователь одобрил «больше
    всего …»). Подпись строки — evaluate, полностью — в шапке графика (l)."""
    top = T.get("fun_top")
    return "%s %s" % (top[0], dur(top[1])) if top and top[1] >= 60 else ""


def dur_short(sec):
    m = int(round(sec / 60))
    # «7 ч 18 м», не «7ч18м» (29.10.2026, просьба: «раздели ч и м отдельно»)
    return "%d м" % m if m < 60 else "%d ч %02d м" % divmod(m, 60)


def dur(sec):
    m = int(round(sec / 60))
    if m < 60:
        return "%d мин" % m
    return "%d ч %02d мин" % divmod(m, 60)


def money(v):
    return "{:,.0f}".format(v).replace(",", " ") + " ₸"


def plural(n, one, few, many):
    n = abs(int(n))
    k = n % 100 if n % 100 < 20 else n % 10
    return one if k == 1 and n % 100 != 11 else few if 2 <= k <= 4 and not 12 <= n % 100 <= 14 else many


def usual_spend(c, today):
    ensure(c)
    rows = c.execute("SELECT day, SUM(value) FROM growth WHERE kind='spend' AND day<? AND day>=?"
                     " GROUP BY day", (today.isoformat(), (today - dt.timedelta(days=14)).isoformat())).fetchall()
    return statistics.median(r[1] for r in rows) if rows else None


def cig_recent(c, today):
    ensure(c)
    return c.execute("SELECT COUNT(*) FROM growth WHERE kind='cig' AND day<? AND day>=?",
                     (today.isoformat(), (today - dt.timedelta(days=7)).isoformat())).fetchone()[0] > 0


_dv = {}                                 # прошедшие дни: день → (время, цифры); живут 10 мин
_days = {}                               # итоги закрытых дней, см. day_summary


def day_values_cached(c, day):
    if day >= today(c):
        return day_values(c, day)
    hit = _dv.get(day)
    if hit and time.monotonic() - hit[0] < 600:
        return hit[1]
    v = day_values(c, day)
    _dv[day] = (time.monotonic(), v)
    return v


def compute(c, d=None):
    """→ {"rows": {ключ: {name, value, detail, state, met, frac, ladder…}}, "chores": [...],
    "taken": взято, "held": удержано, "counted": день в счёт (блок дня сделан, 31.10.2026), "week7": таких дней за неделю}.
    state: take — достал до следующей ступени, hold — удержал свою, None — серый, это не поражение."""
    now = today(c)
    d = d or now
    st = evaluate(c, d)
    if d == now:
        st["week7"] = st["counted"] + sum(1 for i in range(1, WINDOW)
                                          if (day_summary(c, now - dt.timedelta(days=i)) or {}).get("ok"))
    return st


def bonus_text(st):
    """Будет ли бонус «День засчитан»: (подпись, будет ли). День в счёт только с блоком дня
    (31.10.2026, просьба: «только hh.kz и код»; подъём и отбой давали счёт без дела)."""
    n = _castle().DAY
    if st["counted"]:
        return "+%d энергии будет" % n, True
    left = ", ".join("%s %dм" % (s["name"], s["left"]) for s in st["block"]["steps"] if not s["ok"])
    return "до +%d энергии: %s" % (n, left), False


def plan():
    """→ (блок, нормы) в минутах: стандарт, поверх — свой файл (block, /block)."""
    block, norm = dict(BLOCK_DEFAULT), dict(NORM)
    try:
        with open(PLAN_FILE) as f:
            d = json.load(f)
        block.update({k: int(v) for k, v in d.get("block", {}).items() if k in block and int(v) > 0})
        norm.update({k: int(v) for k, v in d.get("norm", {}).items() if k in norm and int(v) > 0})
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    for k, v in block.items():             # норма не ниже блока: иначе потолок обесценит блок
        norm[k] = max(norm[k], v)
    return block, norm


def plan_set(block=None):
    """Свой блок дня {рынок, код} в минутах; None — вернуть стандарт."""
    try:
        with open(PLAN_FILE) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    d.pop("block", None)
    if block:
        d["block"] = block
    os.makedirs(os.path.dirname(PLAN_FILE), exist_ok=True)
    tmp = PLAN_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, PLAN_FILE)
    invalidate()


def block_text(text):
    """Своё время блока из строки: «45 60», «45» (код прежний), «с» — стандарт.
    → подпись, None — не понял."""
    w = re.findall(r"\d+|[a-zа-яё]+", text.lower())
    if w[:1] and w[0] in ("с", "стандарт", "default", "d"):
        plan_set(None)
    elif 1 <= len(w) <= 2 and all(x.isdigit() and 0 < int(x) <= 600 for x in w):
        plan_set({"market": int(w[0]), "code": int(w[1]) if w[1:] else plan()[0]["code"]})
    else:
        return None
    b = plan()[0]
    return "Блок дня: рынок %d мин, затем код %d мин" % (b["market"], b["code"])


def block_state(T, went=False):
    """Блок дня: сделано против плана. done — всё закрыто, next — что делать сейчас.
    went — был на собеседовании: день уже успешный, что бы ни показали часы."""
    block = plan()[0]
    steps = [dict(key=k, name=n, done=T[k], goal=block[k] * 60, ok=T[k] >= block[k] * 60,
                  left=max(1, (block[k] * 60 - T[k] + 30) // 60) if T[k] < block[k] * 60 else 0,
                  live=bool(T.get(k + "_live"))) for k, n in BLOCK_KEYS]
    return dict(goal=GOAL_NAME, steps=steps, done=went or all(s["ok"] for s in steps),
                next=next((s["key"] for s in steps if not s["ok"]), None))


def block_line(b):
    """«Рынок 4/10м → Код 0/20м» — одной строкой для бота."""
    return " → ".join("%s%s %d/%dм" % ("✓ " if s["ok"] else "", s["name"], s["done"] // 60, s["goal"] // 60)
                      for s in b["steps"])


# ── лестница ────────────────────────────────────────────────────────────────

def steps(key):
    """Пороги показателя от первого к вершине; у часов вершина — норма из plan()."""
    base = LADDER[key]
    if key in ("wake", "bed", "cig"):
        return base
    top = plan()[1][key]
    return tuple(s for s in base if (s > top if key in LOWER else s < top)) + (top,)


def step_text(key, s):
    """Порог словами: 09:30, 1 ч 30 мин, до 3 ч, до 8, без сигарет."""
    if key in ("wake", "bed"):
        return hm(s)
    if key == "cig":
        return "до %d" % s if s else "без сигарет"
    h, m = divmod(int(s), 60)
    t = "%d мин" % m if not h else "%d ч" % h if not m else "%d ч %02d мин" % (h, m)
    return "до " + t if key == "fun" else t


def reached(key, v, s):
    return v is not None and (v <= s if key in LOWER else v >= s)


def day_state(key, v, S, lvl):
    """take — достал до следующей ступени, hold — не ниже своей, None — ни то ни другое."""
    return "take" if lvl < len(S) and reached(key, v, S[lvl]) else (
        "hold" if lvl and reached(key, v, S[lvl - 1]) else None)


def day_amount(c, key, d, T, now):
    """Число дня в единицах лестницы. None — судить рано: предел ясен только в конце дня,
    а ноль сигарет без записей за неделю значит, что их просто не считали."""
    if d < FIRST or (key in CLOSED and d >= now) or (key == "cig" and not T["cig"] and not cig_recent(c, d)):
        return None
    v = T[key]
    return v if key in ("wake", "bed", "cig") or v is None else v / 60


def level_on(c, key, d, S=None):
    """Сколько ступеней взято до дня d. Хранится порог, а не номер: своя норма лестницу не сбросит."""
    ensure(c)
    S = S or steps(key)
    best = c.execute("SELECT %s(value) FROM growth WHERE kind='ladder' AND note=? AND day<?"
                     % ("MIN" if key in LOWER else "MAX"), (key, d.isoformat())).fetchone()[0]
    return 0 if best is None else sum(1 for s in S if reached(key, best, s))


def hits_in(c, key, step, d, vals):
    """Сколько дней из WINDOW, считая d, дотянули до порога. vals — цифры дней на время подсчёта."""
    now, n = today(c), 0
    for i in range(WINDOW):
        x = d - dt.timedelta(days=i)
        if x < FIRST:
            break
        if x not in vals:
            vals[x] = day_values_cached(c, x)
        n += reached(key, day_amount(c, key, x, vals[x], now), step)
    return n


def ladder_sync(c):
    """Закрепить ступени: HITS дней из WINDOW на пороге — ступень взята, сразу несколько тоже можно.
    Сегодня проверяется каждый раз: подъём и код видны сразу. → [(показатель, порог)] — новые."""
    import hublib as H
    now = today(c)
    try:
        d = dt.date.fromisoformat(H.meta_get(c, LADDER_DAY, "")) + dt.timedelta(days=1)
    except (TypeError, ValueError):
        d = FIRST
    new, vals = [], {}
    while d <= now:
        for key in LADDER:
            S = steps(key)
            lvl = level_on(c, key, d + dt.timedelta(days=1), S)
            while lvl < len(S) and hits_in(c, key, S[lvl], d, vals) >= HITS:
                add(c, "ladder", S[lvl], key, "auto", day=d)
                new.append((key, S[lvl]))
                lvl += 1
        d += dt.timedelta(days=1)
    closed = (now - dt.timedelta(days=1)).isoformat()
    if H.meta_get(c, LADDER_DAY, "") != closed:
        H.meta_set(c, LADDER_DAY, closed)
    return new


def ladder_row(c, key, d, T, now, vals, fresh):
    """Строка показателя: где стоит и что дальше. Состояние дня — от ступени на его начало,
    подпись — с учётом взятой сегодня."""
    S = steps(key)
    n, lvl = len(S), level_on(c, key, d, S)
    v = day_amount(c, key, d, T, now)
    state = day_state(key, v, S, lvl)
    new = fresh.get(key, ())
    lvl = min(n, lvl + len(new))
    top = lvl >= n
    aim = S[-1] if top else S[lvl]
    hits = hits_in(c, key, aim, d, vals)
    if top:
        parts = ["вершина " + step_text(key, aim), "удержано за неделю %d из %d" % (hits, WINDOW)]
    else:
        parts = ["цель " + step_text(key, aim), "за неделю %d из %d" % (min(hits, HITS), HITS)]
    if new:
        parts.insert(0, "взята ступень " + step_text(key, new[-1]))
    return dict(detail=" · ".join(parts), hl=1 if new else None, hl_at=0 if new else None, state=state,
                met=True if state else None, frac=1.0 if top else (lvl + min(hits, HITS) / HITS) / n, over=0,
                rung="%d/%d" % (lvl, n), ladder=dict(n=n, level=lvl, hits=min(hits, HITS), top=top, aim=aim,
                                                     target=step_text(key, aim),
                                                     hold=S[lvl - 1] if lvl else None))


def up_row(c, key, d, T, now, vals, fresh):
    """Часы на лестнице: сверх потолка — отдельная похвала (30.10.2026, просьба: «если я превышу
    потолок, то это тоже должно замечаться и поощряться»); лестница от этого не растёт."""
    r = ladder_row(c, key, d, T, now, vals, fresh)
    t, top = T[key], steps(key)[-1] * 60
    over = t - top if t - top >= 60 else 0
    r.update(value=("▶ " if T.get(key + "_live") else "") + dur(t))
    if over:
        r.update(over=over, hl=1, hl_at=1,
                 detail="потолок %s · +%s сверх, сильно · %s" % (step_text(key, top / 60), dur(over), r["detail"]))
    return r


def evaluate(c, d):
    y = d - dt.timedelta(days=1)
    now = today(c)
    T = day_values_cached(c, d)
    vals = {d: T}
    fresh = {}                              # ступени, взятые в этот день
    ensure(c)
    for r in c.execute("SELECT note, value FROM growth WHERE kind='ladder' AND day=? ORDER BY id", (d.isoformat(),)):
        fresh.setdefault(r[0], []).append(r[1])
    R = {}

    for key in ("wake", "bed"):
        w = T[key]
        R[key] = dict(ladder_row(c, key, d, T, now, vals, fresh),
                      value=T[key + "_a"] + hm(w) if w is not None else "—")
    for key in ("code", "speech", "market", "lift"):
        R[key] = up_row(c, key, d, T, now, vals, fresh)

    # прокрастинация: YouTube, кино, игры — одним числом; норма отдыха — вершина лестницы
    R["fun"] = dict(ladder_row(c, "fun", d, T, now, vals, fresh), value=dur(T["fun"]), note=fun_top(T))
    if fun_top(T):
        R["fun"]["detail"] += " · больше всего " + fun_top(T)

    # траты: лестницы нет, только «обычно»; день в пределах обычного — удержан
    usual = usual_spend(c, d)
    hold = d < now and bool(T["spend_n"]) and usual is not None and T["spend"] <= usual
    R["money"] = dict(value=money(T["spend"]) if T["spend_n"] else "не записано",
                      detail="обычно " + money(usual) if usual is not None else "обычного пока нет",
                      state="hold" if hold else None, met=True if hold else None)

    # сигареты
    R["cig"] = dict(ladder_row(c, "cig", d, T, now, vals, fresh), value=str(T["cig"]))
    last = last_today(c, "cig") if d == now else None
    if last:
        ago = int(time.time()) - last["ts"]
        R["cig"]["detail"] += " · последняя %s (%s назад)" % (time.strftime("%H:%M", time.localtime(last["ts"])), dur(ago))

    # быт: всё, что подошло по сроку, сделано
    done = chores_on(c, d)
    chores, due = [], []
    for key, name, every in CHORES:
        prev = chore_last(c, key, y)
        gap = (d - prev).days if prev else None     # due — пора сделать сегодня
        if key not in done and (gap is None or gap >= every):
            due.append(name.lower())
        chores.append(dict(key=key, name=name, every=every, done=key in done, prev=prev, today=d,
                           due=key not in done and (gap is None or gap >= every)))
    R["chores"] = dict(value="%d/%d" % (len(done), len(CHORES)),
                       detail=("надо: " + ", ".join(due)) if due else "всё по плану ✓",
                       state=None if due else "hold", met=None if due else True,
                       frac=len(done) / max(1, len(done) + len(due)))

    for k, name in METRICS:
        R[k]["name"] = name
        R[k].setdefault("frac", None)
    # пределы (сигареты, отдых, траты) окончательно судятся при закрытии дня, но в счёт идут сразу
    # (31.10.2026, просьба: «не плюсом, а сразу… напишем 4, если не выполнится просто сминусуем
    # обратно»): превысили — строка сама выпадет; лестница и энергия их не видят.
    if d >= now:
        tomorrow = d + dt.timedelta(days=1)
        for k in CLOSED:
            state = day_state(k, day_amount(c, k, d, T, tomorrow), steps(k), level_on(c, k, d))
            if state and R[k]["state"] is None:
                R[k].update(state=state, met=True)
        if T["spend_n"] and usual is not None and T["spend"] <= usual:
            R["money"].update(state="hold", met=True)
    taken = sum(1 for r in R.values() if r["state"] == "take")
    held = sum(1 for r in R.values() if r["state"] == "hold")
    block = block_state(T, bool(entries(c, d, "interview")))
    return dict(rows=R, chores=chores, taken=taken, held=held, counted=block["done"], today=T, block=block)


def day_summary(c, d):
    """Итог дня для месяца: {taken, held, ok, states, vals, fresh}; None — вне системы. Дни старше двух
    суток не меняются и лежат в meta, иначе год по месяцам считался бы заново при каждом кадре."""
    import hublib as H
    key = d.isoformat()
    if key in _days:
        return _days[key]
    now = today(c)
    if d < FIRST or d > now:
        return None
    frozen = (now - d).days >= 2
    cache = {}
    if frozen:
        try:
            cache = json.loads(H.meta_get(c, DAYS_KEY, "{}") or "{}")
        except ValueError:
            pass
        if key in cache:
            _days.update(cache)
            return cache[key]
    st = compute(c) if d == now else evaluate(c, d)
    R = st["rows"]
    out = dict(taken=st["taken"], held=st["held"], ok=st["counted"], states={k: r["state"] for k, r in R.items()},
               vals={k: r["value"] for k, r in R.items()},
               fresh=[[r["note"], r["value"]] for r in c.execute(
                   "SELECT note, value FROM growth WHERE kind='ladder' AND day=? ORDER BY id", (key,))])
    if frozen:
        cache[key] = out
        H.meta_set(c, DAYS_KEY, json.dumps(cache, ensure_ascii=False))
        _days[key] = out
    return out


_status = {"t": 0, "v": None, "s": None}
# Синхронизация (Пользователь 29.10: «полная синхронизация с ботом тг и на десктопе»): любая запись
# трогает штамп; окно hub, виджет better.exe и hubd (Obsidian, пульт в Telegram) видят его сразу.
STAMP = os.path.expanduser("~/.cache/jarvis/growth-stamp")


def stamp():
    try:
        return os.stat(STAMP).st_mtime_ns
    except OSError:
        return 0


def invalidate():
    _status["t"] = 0
    _dv.clear()
    _night.clear()
    _td["v"] = None
    try:
        os.makedirs(os.path.dirname(STAMP), exist_ok=True)
        with open(STAMP, "w") as f:
            f.write("%.3f\n" % time.time())
    except OSError:
        pass


def status(c, ttl=5):
    s = stamp()
    if s != _status["s"]:                    # записали в другом процессе (бот, окно)
        _dv.clear()
        _night.clear()
        _td["v"] = None
    if _status["v"] is None or time.monotonic() - _status["t"] > ttl or s != _status["s"]:
        _status["v"], _status["t"], _status["s"] = compute(c), time.monotonic(), s
    return _status["v"]


def days_ru(n):
    return "%d %s" % (n, plural(n, "день", "дня", "дней"))


def chore_when(ch, today=None):
    """«2 дня назад · через 1 день» / «пора сегодня» (29.10.2026, пользователь одобрил: сколько прошло и
    когда снова, а не «не было · раз в N дн.»)."""
    every = ch["every"]
    if ch["done"]:
        return "сегодня ✓" + ("" if every == 1 else " · снова через " + days_ru(every))
    if ch["prev"] is None:
        return "не было · " + ("ежедневно" if every == 1 else "раз в " + days_ru(every))
    n = (ch["today"] - ch["prev"]).days
    ago = "вчера" if n == 1 else days_ru(n) + " назад"
    left = every - n
    if left > 0:
        return "%s · через %s" % (ago, days_ru(left))
    return "%s · пора сегодня" % ago


_hist = {}
VAL_KEY = {"money": "spend"}


def short_val(key, n):
    """Подпись столбика графика: 10:08, 45м, 1ч15, 3, 2.5к."""
    if n is None:
        return "—"
    if key in ("wake", "bed"):
        return hm(n)
    if key in ("cig", "chores"):
        return str(int(n))
    if key == "money":
        return str(int(n)) if n < 1000 else ("%.1fк" % (n / 1000)).replace(".0к", "к")
    m = int(round(n / 60))
    return "%dм" % m if m < 60 else "%dч%02d" % divmod(m, 60)


def history(c, key, days=7):
    """[(дата, число|None, подпись, состояние)] от старого к новому — график строки (l в hub).
    До START — пусто; START — только цифра."""
    t, s = today(c), stamp()
    hit = _hist.get((key, days))
    if hit and hit[0] == (t, s) and time.monotonic() - hit[1] < 30:
        return hit[2]
    out = []
    for i in range(days - 1, -1, -1):
        d = t - dt.timedelta(days=i)
        if d < START:
            out.append((d, None, "", None))
            continue
        n = day_values_cached(c, d).get(VAL_KEY.get(key, key))
        out.append((d, n, short_val(key, n), (day_summary(c, d) or {"states": {}})["states"].get(key)))
    _hist[(key, days)] = ((t, s), time.monotonic(), out)
    return out


def week(c, days=7):
    """Строки для недели в боте: [(дата, values)] от старого к новому, не раньше START."""
    d = today(c)
    return [(d - dt.timedelta(days=i), day_values_cached(c, d - dt.timedelta(days=i)))
            for i in range(days - 1, -1, -1) if d - dt.timedelta(days=i) >= START]


# ── действия: общие для окна и бота → (подпись, отмена) ─────────────────────

def do_plus(c, kind, note="", src="pc"):
    gid = add(c, kind, 1, note, src)
    return gid


def do_minus(c, kind):
    r = last_today(c, kind)
    return remove(c, r["id"]) if r else None


def do_chore(c, key, src="pc"):
    """Отметить / снять отметку дела на сегодня → (сделано?, запись для отмены)."""
    r = last_today(c, "chore", key)
    if r:
        return False, remove(c, r["id"])
    return True, get(c, add(c, "chore", 1, key, src))


# Листок «потом» (30.10.2026, просьба: «позывы к действиям — проверить тг/ютуб/кс — записывать туда»;
# «сам факт pomo мне не помогает… в начале хочется отвлечься»). Позыв записан — можно вернуться к
# работе. Записи — в growth, так работают и отмена, и синхронизация. Пользователь 30.10: «во время
# фокусирования весь лишний поток мыслей (чувства, эмоции) записывать в холст, а задачи в список
# отложенных»: задачи — kind later в базе, мысли и чувства — Холст.
#
# Холст — это текст заметки дня в Obsidian (30.10.2026, просьба: «чтобы автоматически создавалась
# ежедневная заметка, под свой день, и лежала в своих папках»). Файл — единственное хранилище:
# написанное в окне видно в Obsidian, и наоборот. Заметка заводится при первой записи.
# Задачи дня дописываются в конец разделом «## Потом»; этот раздел собирается из базы.

NOTES = os.environ.get("GROWTH_NOTES") or os.path.expanduser("~/Documents/Vault/Personal")
NOTE_TEMPLATE = os.path.join(os.path.dirname(NOTES), "Templates", "Daily.md")
NOTE_HEAD = "# {{date:dddd, MMMM D, YYYY}}\n\n---\n"
NOTE_MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
               "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
NOTE_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}\.md$")
LATER_HEAD = "## Потом"
LATER_SEEN = "g_later_seen"                    # что записали в заметки сами: день → строки
# раздел идёт до следующего заголовка: пустые строки и строки без маркера — тоже его
LATER_BLOCK_RE = re.compile(r"(?:^|\n)%s[ \t]*(?=\n|$)(?:\n(?!#).*)*" % LATER_HEAD)
LATER_MARK_RE = re.compile(r"^\s*(?:[-*+](?:\s+\[.\])?(?:\s+|$))?")
# Шаблон Obsidian выводит даты по-английски; язык системы здесь ни при чём
EN_DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
EN_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August",
             "September", "October", "November", "December")


def note_path(day):
    """Где заметка дня уже лежит, иначе Personal/2026/Октябрь/2026-10-30.md."""
    d = dt.date.fromisoformat(day)
    name = day + ".md"
    home = os.path.join(NOTES, str(d.year), NOTE_MONTHS[d.month - 1], name)
    if os.path.exists(home):
        return home
    found = glob.glob(os.path.join(NOTES, name)) + glob.glob(os.path.join(NOTES, str(d.year), "*", name))
    return found[0] if found else home


def note_head(day):
    """Шапка новой заметки — шаблон Templates/Daily.md, те же метки, что у Obsidian."""
    d = dt.date.fromisoformat(day)
    now = time.localtime()
    tokens = {"dddd": EN_DAYS[d.weekday()], "MMMM": EN_MONTHS[d.month - 1], "YYYY": "%04d" % d.year,
              "MM": "%02d" % d.month, "DD": "%02d" % d.day, "D": str(d.day),
              "HH": "%02d" % now.tm_hour, "mm": "%02d" % now.tm_min}
    fmt = lambda m: re.sub("|".join(tokens), lambda t: tokens[t.group()], m.group(1))
    try:
        with open(NOTE_TEMPLATE, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = NOTE_HEAD
    text = re.sub(r"\{\{(?:date|time):([^}]*)\}\}", fmt, text)
    i = text.find("\n---\n")                       # раздел «Потом» из шаблона дописывает note_save
    return text[:i + 5] if i >= 0 else text.rstrip() + "\n"


def note_parts(text):
    """Файл → (шапка до черты ---, мысли). Раздел «Потом» в мысли не входит."""
    i = text.find("\n---\n")
    head, body = (text[:i + 5], text[i + 5:]) if i >= 0 else ("", text)
    return head, LATER_BLOCK_RE.sub("\n", body).strip()


def later_lines(text):
    """Пункты раздела «Потом» в тексте заметки; маркер списка не обязателен."""
    m = LATER_BLOCK_RE.search(text)
    lines = m.group().strip().split("\n")[1:] if m else ()
    return [x for x in (" ".join(LATER_MARK_RE.sub("", y, 1).split()) for y in lines) if x]


def later_sync(c):
    """Раздел «Потом» правят и в Obsidian: дописанное — в базу, стёртое — из базы (30.10.2026, просьба: «писать откуда угодно и везде все совпадало»). Сверка с тем, что записали сами в
    прошлый раз, иначе не отличить новую строку от удалённой."""
    import hublib as H
    seen = json.loads(H.meta_get(c, LATER_SEEN, "{}") or "{}")
    rows = later_list(c)
    days = {today(c).isoformat(), *seen, *(r["day"] for r in rows)}
    new = {}
    for day in sorted(days):
        try:
            with open(note_path(day), encoding="utf-8") as f:
                lines = later_lines(f.read())
        except OSError:
            continue
        have = Counter(lines)
        db = [r for r in rows if r["day"] == day]
        base = Counter(seen[day]) if day in seen else Counter(r["note"] for r in db) & have
        for text in (have - base).elements():
            add(c, "later", 1, text, "obsidian", day=dt.date.fromisoformat(day))
        for text in (base - have).elements():
            r = next((x for x in db if x["note"] == text), None)
            if r:
                db.remove(r)
                c.execute("DELETE FROM growth WHERE id=?", (r["id"],))
                invalidate()
        if lines or day in seen:
            new[day] = lines
    if new != seen:
        H.meta_set(c, LATER_SEEN, json.dumps(new, ensure_ascii=False))


def note_save(c, day, body=None):
    """Записать заметку дня: мысли (None — оставить) и задачи этого дня из базы."""
    import hublib as H
    later_sync(c)
    path = note_path(day)
    try:
        with open(path, encoding="utf-8") as f:
            old = f.read()
    except OSError:
        old = None
    head, was = note_parts(old) if old is not None else ("", "")
    body = was if body is None else body
    items = [r["note"] for r in later_list(c) if r["day"] == day]
    if old is None and not (body or items):
        return
    if old is None:
        head = note_head(day)
    tail = "\n".join([LATER_HEAD] + ["- " + n for n in items])  # заголовок и при пустом списке: в него пишут
    text = (head + "\n" if head else "") + "\n\n".join([body] * bool(body) + [tail]) + "\n"
    if text != old:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = os.path.join(os.path.dirname(path), "." + os.path.basename(path) + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    seen = json.loads(H.meta_get(c, LATER_SEEN, "{}") or "{}")
    if items or day in seen:
        H.meta_set(c, LATER_SEEN, json.dumps(dict(seen, **{day: items}), ensure_ascii=False))


def later_heading(c):
    """Заметка дня, созданная не нами, получает раздел «Потом». Пока в ней печатают — ждём."""
    day = today(c).isoformat()
    try:
        path = note_path(day)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        fresh = time.time() - os.path.getmtime(path) < 20
    except OSError:
        return
    if not fresh and not LATER_BLOCK_RE.search(text):
        note_save(c, day)


def holst_page(day):
    """Текст Холста за день (окно holst.py): мысли из заметки дня, без шапки и «Потом»."""
    try:
        with open(note_path(day), encoding="utf-8") as f:
            return note_parts(f.read())[1]
    except OSError:
        return ""


def holst_days():
    """Дни, у которых есть заметка."""
    found = glob.glob(os.path.join(NOTES, "*.md")) + glob.glob(os.path.join(NOTES, "*", "*", "*.md"))
    return sorted({os.path.basename(p)[:-3] for p in found if NOTE_DAY_RE.search(p)})


def holst_save(c, text, day=None):
    note_save(c, day or today(c).isoformat(), text)


def later_add(c, text, src="pc", kind="later"):
    if kind == "thought":                          # из бота и `later --holst` — в конец страницы дня
        text = text.strip()
        day = today(c).isoformat()
        if text:
            holst_save(c, (holst_page(day) + "\n" + text).strip(), day)
        return None
    text = " ".join(text.split())
    if not text:
        return None
    gid = add(c, kind, 1, text, src)
    note_save(c, get(c, gid)["day"])
    return gid


def later_list(c):
    ensure(c)
    return c.execute("SELECT * FROM growth WHERE kind='later' ORDER BY ts, id").fetchall()


def do_text(c, op, text, src="pc"):
    """Ввод текстом: op — wake|spend|lift|speech. → (подпись, [id добавленных]) или (ошибка, None)."""
    text = text.strip()
    if op == "bed":                     # своя строка «Отбой» в Super+M: одно время и есть отбой
        text = "отбой " + text
    if op in ("wake", "bed"):
        r = parse_sleep(text)
        if not r:
            return "Не понял время. Например: «0730», «0730 2330», «отбой 2340».", None
        ids, said = [], []
        if r[0] is not None:
            ids.append(add(c, "wake", r[0], "", src))
            said.append("подъём " + hm(r[0]))
        if r[1] is not None:
            ids.append(add(c, "bed", r[1], "", src))
            said.append("отбой " + hm(r[1]))
        return "✓ " + ", ".join(said), ids
    if op == "spend":
        r = parse_money(text)
        if not r:
            return "Не понял сумму. Например: «1500 обед», «2к такси».", None
        return "✓ трата %s%s" % (money(r[0]), (" — " + r[1]) if r[1] else ""), [add(c, "spend", r[0], r[1], src)]
    if op == "lift":
        r = parse_speech(text)
        if not r:
            return "Не понял минуты. Например: «15», «20 гантели», «10 отжимания».", None
        return "✓ тренировка %d мин%s" % (r[0], (" — " + r[1]) if r[1] else ""), [add(c, "lift", r[0], r[1], src)]
    if op == "speech":
        r = parse_speech(text)
        if not r:
            return "Не понял минуты. Например: «15», «10 скороговорки», «20 читал вслух».", None
        return "✓ речь %d мин%s" % (r[0], (" — " + r[1]) if r[1] else ""), [add(c, "speech", r[0], r[1], src)]
    return "?", None


# ── вкладка окна hub ────────────────────────────────────────────────────────

ROW_H, AREA_H, HEAD_H, CHORE_H, TOP_H = 24, 52, 28, 24, 60
TOP_INPUT = ("block",)          # поле не в строке, а в полосе блока
INPUT = {"block": ("блок, минут: ", "«45 60» — рынок и код · «с» — стандарт"),
         "wake": ("подъём: ", "«0730» · «17» · с отбоем: «0730 2330»"),
         "bed": ("отбой прошлой ночи: ", "«2340» · «0130» · «10»"),
         "spend": ("трата: ", "«1500 обед» · «2к такси»"),
         "lift": ("тренировка, минут: ", "«15» · «20 гантели» · «10 отжимания»"),
         "speech": ("речь, минут: ", "«15» · «10 скороговорки» · «20 читал вслух»")}
# строка → что делает Space/Enter и i
PRIMARY = {"wake": "i:wake", "bed": "i:bed", "code": "pomo", "speech": "i:speech", "market": "pomo:рынок",
           "fun": None, "money": "i:spend", "cig": "+cig", "lift": "i:lift", "chores": None}
HINTS = {"wake": "Space — ввести время · x — убрать",
         "bed": "Space — ввести время · x — убрать",
         "code": "Space — помидор «programming» · Tab вкладка",
         "speech": "Space / i — минуты практики · помидор «речь» считается сам",
         "market": "Space — помидор «рынок» · сам: вкладка hh.kz",
         "fun": "сам: YouTube, кино, игры — одним числом",
         "money": "i / Space — трата · x — убрать последнюю",
         "cig": "Space +1 · x −1 · u отмена",
         "lift": "i / Space — минуты тренировки · помидор «гантели» считается сам · x — убрать",
         "chores": "j — к делам · Space — отметить",
         "chore": "Space / x — отметить · u отмена"}

# пиксельные значки 9×9 (Пользователь 28.10: «добавь иконки к каждому пункту, чтобы визуально понимать»)
ICONS = {
    "wake": ("....#....", ".#.....#.", "...###...", "..#####..", "#.#####.#",
             "..#####..", "...###...", ".#.....#.", "....#...."),
    "bed": ("..####...", ".##......", "##.......", "##.......", "##.......",
            "##.......", "##.....##", ".##...##.", "..#####.."),
    "code": (".........", "#........", ".#.......", "..#......", "...#.....",
             "..#......", ".#.......", "#...#####", "........."),
    "speech": (".#######.", "#.......#", "#.#.#.#.#", "#.......#", ".#######.",
               "..#......", ".#.......", "#........", "........."),
    "market": ("...###...", "..#...#..", "#########", "#.......#", "#...#...#",
               "#########", "#.......#", "#.......#", "#########"),
    "fun": ("#########", "#.......#", "#..#....#", "#..##...#", "#..###..#",
            "#..##...#", "#..#....#", "#.......#", "#########"),
    "money": ("..#####..", ".#.....#.", "#.#####.#", "#.......#", "#.#####.#",
              "#...#...#", "#...#...#", ".#..#..#.", "..#####.."),
    "cig": ("......#..", ".....#...", "......#..", ".....#...", ".........",
            ".........", "######.##", "######.##", "........."),
    "lift": (".........", ".#.....#.", "##.....##", "##.....##", "#########",
             "##.....##", "##.....##", ".#.....#.", "........."),
    "chores": ("....#....", "...###...", "..#####..", ".#######.", "#########",
               ".#.....#.", ".#.###.#.", ".#.#.#.#.", ".#.#.#.#."),
    "teeth_am": (".##...##.", "#..###..#", "#.......#", "#.......#", ".#.....#.",
                 ".#.....#.", ".#..#..#.", ".#.#.#.#.", "..#...#.."),
    "shower": ("....#....", "....#....", "...###...", "..#####..", ".#######.",
               ".#######.", ".##.####.", "..#####..", "...###..."),
    "hair": (".........", "#########", "#########", "#.#.#.#.#", "#.#.#.#.#",
             "#.#.#.#.#", "#.#.#.#.#", ".........", "........."),
    "cook": ("....#....", ".#######.", ".........", "#########", ".#######.",
             ".#######.", ".#######.", "..#####..", "........."),
    "desk": ("..#####..", "..#...#..", "..#####..", "....#....", "#########",
             "#.......#", "#.......#", "#.......#", "........."),
    "trash": ("...###...", "#########", ".#######.", ".#.#.#.#.", ".#.#.#.#.",
              ".#.#.#.#.", ".#.#.#.#.", "..#####..", "........."),
    "laundry": (".##...##.", "####.####", "#########", ".#######.", "..#####..",
                "..#####..", "..#####..", "..#####..", "........."),
    "flame": ("....#....", "...##....", "...###.#.", "..######.", ".#######.",
              ".###.###.", ".##...##.", ".##...##.", "..#####.."),
    # вкладки hub
    "tab_growth": (".........", ".......##", ".......##", "....##.##", "....##.##",
                   ".##.##.##", ".##.##.##", ".##.##.##", "#########"),
    "tab_items": ("....#....", "...###...", "..#####..", "..#####..", "..#####..",
                  ".#######.", "#########", ".........", "...###..."),
    "tab_words": (".........", ".###.###.", "#...#...#", "#.#.#.#.#", "#...#...#",
                  "#.#.#.#.#", "#...#...#", ".###.###.", "........."),
    "tab_month": ("..#...#..", "#########", "#########", "#.......#", "#.##.##.#",
                  "#.......#", "#.##.##.#", "#.......#", "#########"),
}
ICONS["teeth_pm"] = ICONS["teeth_am"]
# свой цвет у каждой строки — чтобы различать с первого взгляда
HUES = {"wake": "#ffc857", "bed": "#a08cff", "code": "#6ee7a0", "speech": "#5fd3f0",
        "market": "#7aa2ff", "fun": "#ff7eb6", "money": "#c4e86a", "cig": "#d9a27a",
        "lift": "#ff8a5c", "chores": "#6fe0d0", "flame": "#ff9a3c", "ok": "#7ee08a",
        "hold": "#8fb8e8"}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def hue(v, key):
    """Цвет строки под тему окна: на светлом фоне темнее."""
    base = _rgb(HUES.get(key, HUES["chores"]))
    bg = v.c["bg"]
    if sum(bg) / 3 > 0.55:
        return _mix(base, (0, 0, 0), 0.45)
    return _mix(base, v.c["text"], 0.08)


def pix(p, x, y, art, col, s=2):
    """Пиксельный значок: '#' — точка s×s."""
    x, y = round(x), round(y)
    p.rgb(col)
    for j, row in enumerate(art):
        i = 0
        while i < len(row):
            if row[i] == "#":
                k = i
                while k < len(row) and row[k] == "#":
                    k += 1
                p.cr.rectangle(x + i * s, y + j * s, (k - i) * s, s)
                i = k
            else:
                i += 1
    p.cr.fill()


def rows(v):
    out = [("g", k) for k, _n in METRICS]
    out.append(("head", "Быт — отметить сделанное"))
    return out + [("chore", k) for k, _n, _e in CHORES]


def _iv():
    """Лениво: interviews сам импортирует этот модуль."""
    import interviews
    return interviews


def _caret(s, cur):
    cur = len(s) if cur is None else max(0, min(cur, len(s)))
    return s[:cur] + "⁣" + s[cur:]


def _row_h(kind):
    return AREA_H if kind == "g" else HEAD_H if kind == "head" else CHORE_H


STATE_RU = {"take": "взято", "hold": "удержано", None: "в пути"}
STATE_ALPHA = {"take": 1.0, "hold": 0.55, None: 0.2}


def _state_col(v, state):
    return hue(v, "ok") if state == "take" else hue(v, "hold") if state == "hold" else v.c["faint"]


def _draw_block(v, p, b, x0, x1, y):
    """Блок дня над сводкой: что делать сейчас и сколько уже сделано; под текстом — полоса по шагам."""
    c = v.c
    v.hits.append(((x0, y - 2, x1 - x0, 22), ("btn", "g:i:block")))
    if v.mode == "ginput" and v.g_op in TOP_INPUT:
        prompt, tip = INPUT[v.g_op]
        w = p.text(x0, y, prompt, c["dim"])
        room = x1 - x0 - w - 8
        if v.buf:
            p.text(x0 + w, y, _caret(v.buf, v.cur), c["acc_l"], maxw=room)
        else:
            p.text(x0 + w, y, "⁣" + tip, c["faint"], maxw=room)
        return y + 26
    w = p.text(x0, y, "Блок → %s: " % b["goal"], c["dim"])
    for i, s in enumerate(b["steps"]):
        if i:
            w += p.text(x0 + w, y, " → ", c["faint"])
        col = hue(v, "ok") if s["ok"] else c["text"] if s["key"] == b["next"] else c["dim"]
        w += p.text(x0 + w, y, "%s%s %d/%dм" % ("▶ " if s["live"] else "", s["name"], s["done"] // 60, s["goal"] // 60), col)
    note, col = ("сделан", hue(v, "ok")) if b["done"] else ("b — своё", c["faint"])
    if x0 + w + p.text_w(note) + 8 <= x1:                  # длинные цифры важнее подсказки
        p.text(x1, y, note, col, align="r")
    total = sum(s["goal"] for s in b["steps"])
    bx = x0
    for s in b["steps"]:
        sw = (x1 - x0 - 3) * s["goal"] / total
        p.rect(bx, y + 16, sw, 3, c["line_soft"])
        p.rect(bx, y + 16, sw * min(1.0, s["done"] / s["goal"]), 3, hue(v, "ok") if s["ok"] else hue(v, s["key"]))
        bx += sw + 3
    return y + 26


def draw(v, p, x0, x1, y0, y1):
    c = v.c
    st = status(v.conn)
    if getattr(v, "g_cal", None):
        _draw_month(v, p, x0, x1, y0, y1)
        return
    good = st["taken"] + st["held"]
    y0 = _draw_block(v, p, st["block"], x0, x1, y0)
    # сводка: взято и удержано, полоса из отрезков по строкам
    hov = v.hover[1] if isinstance(v.hover, tuple) and v.hover[0] == "gseg" else None
    if hov is not None and hov < len(METRICS):
        # подпись отрезка под указателем вместо сводки (29.10.2026, просьба: «подпиши отрезки при наведении»)
        k = METRICS[hov][0]
        r = st["rows"][k]
        w = p.text(x0, y0, r["name"], hue(v, k))
        w += p.text(x0 + w, y0, " · " + STATE_RU[r["state"]], _state_col(v, r["state"]))
        p.text(x0 + w, y0, " · " + r["value"], c["text"], maxw=x1 - x0 - w)
    else:
        w = p.text(x0, y0, "Взято %d" % st["taken"], hue(v, "ok"))
        w += p.text(x0 + w, y0, " · ", c["faint"])
        w += p.text(x0 + w, y0, "удержано %d" % st["held"], hue(v, "hold"))
        tw = p.text(x1, y0, "неделя %d/%d" % (st.get("week7", 0), WINDOW), hue(v, "flame"), align="r")
        pix(p, x1 - tw - 14, y0 + 1, ICONS["flame"], hue(v, "flame"), 1)
    y0 += 18
    label, sure = bonus_text(st)
    p.text(x0, y0, label, hue(v, "ok") if sure else c["dim"], maxw=x1 - x0)
    # отрезки со значками строк; отрезок выбранной строки подчёркнут (29.10.2026, пользователь одобрил)
    kind, cur = current(v)
    cur_i = next((i for i, (k, _n) in enumerate(METRICS) if k == (cur if kind == "g" else "chores" if kind else None)), None)
    if getattr(v, "g_chart", None):
        cur_i = next(i for i, (k, _n) in enumerate(METRICS) if k == v.g_chart)
    seg_y, seg_h, gap = y0 + 20, 13, 3
    sw = (x1 - x0 - gap * (len(METRICS) - 1)) / len(METRICS)
    for i, (k, _n) in enumerate(METRICS):
        state = st["rows"][k]["state"]
        sx = x0 + i * (sw + gap)
        p.rect(sx, seg_y, sw, seg_h, c["line_soft"])
        p.rect(sx, seg_y, sw, seg_h, hue(v, k), STATE_ALPHA[state])
        pix(p, sx + (sw - 9) // 2, seg_y + 2, ICONS[k], c["bg"] if state else hue(v, k), 1)
        if hov == i or cur_i == i:
            p.rect(sx, seg_y + seg_h + 2, sw, 2, c["text"] if hov == i else c["acc_l"])
        v.hits.append(((sx, seg_y - 4, sw + gap, 20), ("gseg", i)))
    # расшифровка отрезков; справа — вся лестница
    ly, lx = seg_y + seg_h + 7, x0
    for state, col in (("take", 1.0), ("hold", 0.55), (None, 0.2)):
        p.rect(lx, ly + 1, 11, 9, c["line_soft"])
        p.rect(lx, ly + 1, 11, 9, hue(v, "ok"), col)
        lx += 15
        lx += p.text(lx, ly, STATE_RU[state], c["dim"] if state else c["faint"]) + 12
    a, b = rungs(st)
    p.text(x1, ly, "ступеней %d из %d" % (a, b), c["dim"], align="r")
    y0 += TOP_H
    if getattr(v, "g_chart", None):
        _draw_chart(v, p, x0, x1, y0, y1)
        return
    rs = rows(v)
    sel = max(0, min(v.sel["growth"], len(rs) - 1))
    hs = [_row_h(k) for k, _d in rs]
    avail = y1 - y0
    if getattr(v, "free_scroll", False):     # тянут полосу мышью — выбор может уйти за край (29.10.2026)
        max_off = 0
        while max_off < len(rs) - 1 and sum(hs[max_off:]) > avail:
            max_off += 1
        off = max(0, min(v.scroll["growth"], max_off))
    else:
        off = min(v.scroll["growth"], sel)
        while off < sel and sum(hs[off:sel + 1]) > avail:
            off += 1
        while off > 0 and sum(hs[off - 1:]) <= avail:
            off -= 1
        if off and rs[off - 1][0] == "head" and sum(hs[off - 1:sel + 1]) <= avail:
            off -= 1
    v.scroll["growth"] = off
    v.page_rows = max(2, avail // ROW_H)
    total = sum(hs)
    v.sb = None
    if total > avail:
        c0 = sum(hs[:off])
        th = max(18, avail * avail / total)
        ty = y0 + (avail - th) * c0 / max(1, total - avail)
        p.rect(x1 + 5, y0, 3, avail, c["line_soft"])
        hov = v.hover == ("sb",) or getattr(v, "sb_drag", False)
        p.rect(x1 + 5, ty, 3, min(th, y0 + avail - ty), c["acc"] if hov else c["line"])
        # мышью — как в списке напоминаний: тянуть, щёлкнуть, колесо над полосой (hub_app.sb_to)
        v.sb = (y0, avail, hs)
        v.hits.append(((x1 + 1, y0, 12, avail), ("sb",)))
    p.cr.save()
    p.cr.rectangle(x0 - 2, y0, x1 - x0 + 4, y1 - y0)
    p.cr.clip()
    y = y0
    chores = {ch["key"]: ch for ch in st["chores"]}
    try:
        for i in range(off, len(rs)):
            if y >= y1:
                break
            kind, key = rs[i]
            is_sel = i == sel
            if kind == "head":
                if key.startswith("Быт"):
                    pix(p, x0 + 4, y + 10, ICONS["chores"], hue(v, "chores"), 1)
                hx = x0 + 18 if key.startswith("Быт") else x0 + 4
                p.text(hx, y + 9, key, c["acc_l"] if v.active else c["dim"])
                p.rect(hx + p.text_w(key) + 8, y + 16, max(0, x1 - hx - p.text_w(key) - 12), 1, c["line_soft"])
            elif kind == "g":
                _draw_metric(v, p, key, st["rows"][key], x0, x1, y, is_sel, i)
            else:
                _draw_chore(v, p, chores[key], x0, x1, y, is_sel, i)
            y += hs[i]
    finally:
        p.cr.restore()


def _draw_metric(v, p, key, r, x0, x1, y, sel, i):
    c = v.c
    v.row_bg(p, x0, x1, y, sel, ("row", i), h=AREA_H - 4)
    met, col = r["met"], hue(v, key)
    # плитка со значком в цвете строки
    p.rect(x0 + 9, y + 6, 30, 30, col, 0.16)
    p.rect(x0 + 9, y + 6, 2, 30, col)
    pix(p, x0 + 15, y + 12, ICONS[key], col, 2)
    tx = x0 + 48
    vw = p.text(x1 - 8, y + 5, r["value"], _state_col(v, r["state"]) if r["state"] else c["text"], align="r")
    nw = p.text(tx, y + 5, r["name"], c["text"], maxw=x1 - tx - 60 - vw)
    if r.get("rung"):
        p.text(tx + nw + 10, y + 5, r["rung"], c["faint"])
    if sel and v.mode == "ginput" and v.g_op not in TOP_INPUT:
        prompt = INPUT[v.g_op][0]
        s = v.buf if v.buf else ""
        pw = p.text(tx, y + 21, prompt, c["dim"])
        if s:
            p.text(tx + pw, y + 21, _caret(s, v.cur), c["acc_l"], maxw=x1 - tx - 8 - pw)
        else:
            p.text(tx + pw, y + 21, "⁣" + INPUT[v.g_op][1], c["faint"], maxw=x1 - tx - 8 - pw)
    elif r.get("hl") is not None and " · " in r["detail"]:
        # взятая ступень и «сверх потолка» — своим цветом; hl_at — номер части
        parts = r["detail"].split(" · ")
        i = r["hl_at"]
        head, mid, rest = " · ".join(parts[:i]), parts[i], " · ".join(parts[i + 1:])
        tcol = hue(v, "ok")
        x, room = tx, x1 - tx - 8
        for txt, col in ((head + " · " if head else "", c["dim"]), (mid, tcol), (" · " + rest if rest else "", c["dim"])):
            if txt and room > 20:
                w = p.text(x, y + 21, txt, col, maxw=room)
                x, room = x + w, room - w
    else:
        p.text(tx, y + 21, r["detail"], c["dim"], maxw=x1 - tx - 8)
    _draw_steps(v, p, r, col, tx, y + 38, x1 - tx - 8)


def _draw_steps(v, p, r, col, x, y, w):
    """Лестница строки: взятые ступени залиты, на текущей — доля дней до следующей."""
    c = v.c
    L = r.get("ladder")
    if not L:
        p.rect(x, y, w, 4, c["line_soft"])
        if r["frac"] is not None:
            p.rect(x, y, w * max(0.0, min(1.0, r["frac"])), 4, col)
        elif r["state"]:
            p.rect(x, y, w, 4, _state_col(v, r["state"]), 0.7)
        return
    gap = 2
    sw = (w - gap * (L["n"] - 1)) / L["n"]
    for i in range(L["n"]):
        sx = x + i * (sw + gap)
        p.rect(sx, y, sw, 4, c["line_soft"])
        f = 1.0 if i < L["level"] else L["hits"] / HITS if i == L["level"] else 0
        if f:
            p.rect(sx, y, sw * f, 4, col)


def _draw_chart(v, p, x0, x1, y0, y1):
    """График строки за 7 дней: столбик — значение, яркий — день с результатом (l — войти, h — назад)."""
    c, key = v.c, v.g_chart
    col = hue(v, key)
    H = history(v.conn, key)
    pix(p, x0 + 4, y0 + 6, ICONS[key], col, 1)
    w = p.text(x0 + 18, y0 + 3, NAMES[key], col)
    p.text(x0 + 18 + w, y0 + 3, " — 7 дней", c["dim"])
    good = sum(1 for h in H if h[3])
    p.text(x1, y0 + 3, "результат %d из %d" % (good, len(H)), hue(v, "ok") if good else c["dim"], align="r")
    note = status(v.conn)["rows"][key].get("note")
    if note:
        w = p.text(x0 + 18, y0 + 21, "сегодня больше всего: ", c["dim"])
        p.text(x0 + 18 + w, y0 + 21, note, col)
    top, bot = y0 + 46 + (16 if note else 0), y1 - 24
    vals = [h[1] for h in H if h[1] is not None]
    if key in ("wake", "bed") and vals:      # время: от самого раннего (−30 мин) до самого позднего
        lo, hi = min(vals) - 30, max(vals)
    else:
        lo, hi = 0, max(vals or [0])
    n, gap = len(H), 8
    bw = (x1 - x0 - 8 - gap * (n - 1)) / n
    p.rect(x0 + 4, bot, x1 - x0 - 8, 1, c["line"])
    t = today(v.conn)
    for i, (d, val, lab, state) in enumerate(H):
        bx = x0 + 4 + i * (bw + gap)
        cx = bx + bw / 2
        if val is not None:
            f = (val - lo) / (hi - lo) if hi > lo else (1.0 if val else 0.0)
            bh = max(2, (bot - top) * f)
            p.rect(bx, bot - bh, bw, bh, col, STATE_ALPHA[state] if state else 0.3)
            p.text(cx, bot - bh - 16, lab, c["text"] if d == t else c["dim"], align="c")
        elif d >= START:
            p.text(cx, bot - 16, "—", c["faint"], align="c")
        dl = "%s %d" % (WD[d.weekday()], d.day)
        p.text(cx, bot + 6, dl, c["acc_l"] if d == t else c["dim"] if d >= START else c["faint"], align="c")
        if d == t:
            p.rect(bx, bot + 20, bw, 2, c["acc_l"])


def _draw_chore(v, p, ch, x0, x1, y, sel, i):
    c = v.c
    v.row_bg(p, x0, x1, y, sel, ("row", i), h=CHORE_H - 2)
    st_col = hue(v, "ok") if ch["done"] else c["text"] if ch["due"] else c["line"]
    v.icon_box(p, x0 + 10, y + 7, 9, st_col, ch["done"])
    icol = hue(v, "chores") if not ch["done"] else hue(v, "ok")
    pix(p, x0 + 26, y + 3, ICONS.get(ch["key"], ICONS["chores"]), icol if (ch["due"] or ch["done"]) else c["faint"], 2)
    when = chore_when(ch)
    ww = p.text(x1 - 8, y + 5, when, hue(v, "ok") if ch["done"] else c["dim"] if ch["due"] else c["faint"], align="r")
    p.text(x0 + 52, y + 5, ch["name"], c["dim"] if ch["done"] else c["text"], maxw=x1 - x0 - 64 - ww)


# ── месяц (31.10.2026, просьба: «просматривать сразу по месяцам какой у меня прогресс был в какой
# день»; образец — Планирование в Obsidian). Цели года здесь нет: год — это лестница, месяц и неделя —
# свёртка дней. c — открыть, h/l день, j/k неделя, H/L месяц. Красного нет: пустой день просто бледный.

def rungs(st):
    """(взято ступеней, всего) по всем лестницам."""
    L = [r["ladder"] for r in st["rows"].values() if r.get("ladder")]
    return sum(x["level"] for x in L), sum(x["n"] for x in L)


def month_len(y, m):
    return ((dt.date(y + m // 12, m % 12 + 1, 1)) - dt.date(y, m, 1)).days


def month_days(c, y, m):
    """[(дата, итог | None)] — все дни месяца."""
    out = []
    for i in range(month_len(y, m)):
        d = dt.date(y, m, i + 1)
        out.append((d, day_summary(c, d)))
    return out


def week_ok(c, d):
    """Дней в счёте за календарную неделю дня d."""
    mon = d - dt.timedelta(days=d.weekday())
    return sum(1 for i in range(7) if (day_summary(c, mon + dt.timedelta(days=i)) or {}).get("ok"))


def _ring(v, p, cx, cy, r, frac, col, top, sub):
    c, cr = v.c, p.cr
    cr.set_line_width(5)
    p.rgb(c["line_soft"])
    cr.new_path()
    cr.arc(cx, cy, r, 0, 6.2832)
    cr.stroke()
    if frac > 0:
        p.rgb(col)
        cr.new_path()
        cr.arc(cx, cy, r, -1.5708, -1.5708 + 6.2832 * min(1.0, frac))
        cr.stroke()
    p.text(cx, cy - 7, "%d%%" % round(frac * 100), c["text"], align="c")
    p.text(cx, cy + r + 8, top, c["dim"], align="c")
    p.text(cx, cy + r + 24, sub, c["faint"], align="c")


def _draw_month(v, p, x0, x1, y0, y1):
    c, conn = v.c, v.conn
    cal = v.g_cal
    y, m, sel = cal["y"], cal["m"], cal["day"]
    days = month_days(conn, y, m)
    ok = sum(1 for _d, s in days if s and s["ok"])
    now = today(conn)
    w7 = week_ok(conn, sel)
    a, b = rungs(status(conn))
    ok_col = hue(v, "ok")
    w = x1 - x0
    ry = y0 + 40
    for i, (frac, col, top, sub) in enumerate((
            (a / b if b else 0, hue(v, "flame"), "Лестница", "%d из %d" % (a, b)),
            (ok / len(days), ok_col, "Месяц", "%d из %d" % (ok, len(days))),
            (w7 / 7, hue(v, "hold"), "Неделя", "%d из 7" % w7))):
        _ring(v, p, x0 + w * (2 * i + 1) / 6, ry, 30, frac, col, top, sub)
    # сетка
    y2 = ry + 76
    p.text(x0, y2, "%s %d ПО ДНЯМ" % (NOTE_MONTHS[m - 1].upper(), y), c["acc_l"])
    p.text(x1, y2, "взято + удержано", c["faint"], align="r")
    y2 += 20
    first = dt.date(y, m, 1).weekday()
    nrows = (first + len(days) + 6) // 7
    below = 22 + 98 + 22 + 2 * 36                  # день и плитки года
    ch = max(22, min(36, (y1 - y2 - 18 - below) // nrows))
    gap = 3
    cw = (w - 6 * gap) / 7
    for i in range(7):
        p.text(x0 + i * (cw + gap) + cw / 2, y2, WD[i], c["dim"], align="c")
    y2 += 18
    for d, sum_ in days:
        i = first + d.day - 1
        cx, cy = x0 + (i % 7) * (cw + gap), y2 + (i // 7) * (ch + gap)
        n = sum_["taken"] + sum_["held"] if sum_ else 0
        p.rect(cx, cy, cw, ch, c["line_soft"], 0.5 if d <= now else 0.2)
        if n:
            p.rect(cx, cy, cw, ch, ok_col, 0.12 + 0.68 * min(1.0, n / len(METRICS)) * (1.0 if sum_["ok"] else 0.5))
        p.text(cx + 5, cy + 3, str(d.day), c["text"] if sum_ else c["faint"])
        if sum_:
            p.text(cx + cw - 5, cy + ch - 17, str(n) if n else "·", c["text"] if n else c["faint"], align="r")
        if d == sel:
            p.rect(cx, cy, cw, 1, c["acc_l"])
            p.rect(cx, cy + ch - 1, cw, 1, c["acc_l"])
            p.rect(cx, cy, 1, ch, c["acc_l"])
            p.rect(cx + cw - 1, cy, 1, ch, c["acc_l"])
        elif d == now:
            p.rect(cx, cy + ch - 2, cw, 2, c["acc_l"])
        v.hits.append(((cx, cy, cw, ch), ("gcal_day", d.isoformat())))
    y2 += nrows * (ch + gap) + 6
    y2 = _draw_month_day(v, p, sel, day_summary(conn, sel), x0, x1, y2)
    # год по месяцам
    p.text(x0, y2, "ГОД ПО МЕСЯЦАМ — НАЖМИТЕ НА МЕСЯЦ", c["acc_l"])
    y2 += 20
    cw = (w - 5 * gap) / 6
    for mm in range(1, 13):
        cx, cy = x0 + (mm - 1) % 6 * (cw + gap), y2 + (mm - 1) // 6 * 36
        md = month_days(conn, y, mm)
        n = sum(1 for _d, s in md if s and s["ok"])
        p.rect(cx, cy, cw, 33, c["line_soft"], 0.5)
        if n:
            p.rect(cx, cy, cw, 33, ok_col, 0.12 + 0.6 * n / len(md))
        p.text(cx + 5, cy + 3, NOTE_MONTHS[mm - 1][:3], c["text"] if any(s for _d, s in md) else c["faint"])
        p.text(cx + 5, cy + 17, "%d/%d" % (n, len(md)), c["dim"] if n else c["faint"])
        if mm == m:
            p.rect(cx, cy + 31, cw, 2, c["acc_l"])
        v.hits.append(((cx, cy, cw, 33), ("gcal_mon", mm)))


DAY_SHORT = {"fun": "Прокр.", "cig": "Сигар."}


def _draw_month_day(v, p, d, s, x0, x1, y):
    """Выбранный день: показатели значками, цвет — взято/удержано."""
    c = v.c
    w = p.text(x0, y, _day_ru(d), c["acc_l"])
    if not s:
        p.text(x0 + w, y, " · нет данных", c["faint"])
        return y + 120
    p.text(x0 + w, y, " · взято %d · удержано %d%s" % (s["taken"], s["held"], " · день в счёте" if s["ok"] else ""), c["dim"])
    y += 20
    cw = (x1 - x0) / 5
    for i, (k, _n) in enumerate(METRICS):
        cx, cy = x0 + (i % 5) * cw, y + (i // 5) * 38
        state = s["states"].get(k)
        pix(p, cx + 2, cy + 3, ICONS[k], hue(v, k) if state else c["faint"], 1)
        p.text(cx + 15, cy, DAY_SHORT.get(k, TG_SHORT[k]), c["dim"] if state else c["faint"], maxw=cw - 18)
        val = s["vals"].get(k, "—").replace(" ч ", "ч ").replace(" мин", "м")
        p.text(cx + 2, cy + 16, val, _state_col(v, state) if state else c["faint"], maxw=cw - 4)
    y += 78
    if s["fresh"]:
        p.text(x0, y, "Взята ступень: " + ", ".join("%s %s" % (TG_SHORT[k], step_text(k, t)) for k, t in s["fresh"]),
               hue(v, "ok"), maxw=x1 - x0)
    return y + 22


def cal_open(c, d=None):
    d = d or today(c)
    return dict(y=d.year, m=d.month, day=d)


def cal_step(cal, days=0, months=0):
    """Сдвиг выбора: на дни или на месяцы, число дня сохраняется, насколько можно."""
    if months:
        i = cal["y"] * 12 + cal["m"] - 1 + months
        y, m = divmod(i, 12)
        return dict(y=y, m=m + 1, day=dt.date(y, m + 1, min(cal["day"].day, month_len(y, m + 1))))
    d = cal["day"] + dt.timedelta(days=days)
    return dict(y=d.year, m=d.month, day=d)


def current(v):
    rs = rows(v)
    i = v.sel["growth"]
    return rs[i] if 0 <= i < len(rs) else (None, None)


def buttons(v, p, x0, x1, y):
    if v.mode == "ginput":
        v.buttons(p, x0, x1, y, [("отмена", ("btn", "g:cancel"))]
                  + [("стандарт", ("btn", "g:blockstd"))] * (v.g_op == "block")
                  + [("записать", ("btn", "g:submit"), True)])
        return
    if getattr(v, "g_cal", None):
        v.buttons(p, x0, x1, y, [("← к списку", ("btn", "g:cal"), True), ("‹ месяц", ("btn", "g:calm:-1")),
                                 ("месяц ›", ("btn", "g:calm:1"))])
        return
    if getattr(v, "g_chart", None):
        v.buttons(p, x0, x1, y, [("← к списку", ("btn", "g:chart"), True), ("обновить", ("btn", "g:refresh"))])
        return
    kind, key = current(v)
    B = []
    if kind == "chore":
        ch = next(ch for ch in status(v.conn)["chores"] if ch["key"] == key)
        B = [("не сделано" if ch["done"] else "сделано", ("btn", "g:chore"), not ch["done"])]
    elif key in ("wake", "bed"):
        B = [("ввести время", ("btn", "g:i:" + key), True), ("убрать своё", ("btn", "g:-" + key))]
    elif key == "market":
        B = [("▶ помидор «рынок»", ("btn", "g:pomo:рынок"), True)]
    elif key == "code":
        B = [("▶ помидор programming", ("btn", "g:pomo"), True)]
    elif key == "speech":
        B = [("+ минуты практики", ("btn", "g:i:speech"), True), ("▶ помидор «речь»", ("btn", "g:pomo:речь")),
             ("убрать последнюю", ("btn", "g:-speech"))]
    elif key == "money":
        B = [("+ трата", ("btn", "g:i:spend"), True), ("убрать последнюю", ("btn", "g:-spend"))]
    elif key == "cig":
        B = [("+1 сигарета", ("btn", "g:+cig"), True), ("− 1", ("btn", "g:-cig"))]
    elif key == "lift":
        B = [("+ минуты тренировки", ("btn", "g:i:lift"), True), ("▶ помидор «гантели»", ("btn", "g:pomo:гантели")),
             ("убрать последнюю", ("btn", "g:-lift"))]
    elif key == "chores":
        B = [("к делам", ("btn", "g:tochores"), True)]
    B.append(("обновить", ("btn", "g:refresh")))
    v.buttons(p, x0, x1, y, B)


def hint(v):
    if v.mode == "ginput":
        return "Enter — записать · Esc — отмена"
    if getattr(v, "g_cal", None):
        return "h/l день · j/k неделя · H/L месяц · Esc"
    if getattr(v, "g_chart", None):
        return "h / Esc — к списку · j/k — другая строка"
    kind, key = current(v)
    h = HINTS.get("chore" if kind == "chore" else key, "")
    return h + " · l — график · c — месяц" if kind == "g" else h


# ── бот hub: /better ────────────────────────────────────────────────────────
# Пульт одним сообщением: сводка, кнопки «+1», ввод текстом (трата, подход, сон), быт, неделя.
# Кнопки — g:<действие>; текст после кнопки ловит hubtg.wait_take (op g_<что>) → tg_wait.

UNDO_KEY = "g_undo"                   # последнее действие из бота: {"label", "add": [id] | "back": [row]}
WD = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MON = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
# Пользователь 28.10: «непонятные красные/зелёные круги, всё прижато» → значок строки, статус словом
EMOJI = {"wake": "☀️", "bed": "🌙", "code": "💻", "speech": "🗣", "market": "💼", "fun": "📺",
         "money": "💸", "cig": "🚬", "lift": "🏋", "chores": "🧹"}
VERDICT = {"take": "🟢 взято", "hold": "🔵 удержано", None: "▫️ в пути"}
TG_ASK = {"spend": ("ТРАТА", "Сумма и на что, сэр: «1500 обед», «2к такси». Уйдёт и в Obsidian (Finance)."),
          "lift": ("ТРЕНИРОВКА", "Сколько минут, сэр: «15», «20 гантели», «10 отжимания»."),
          "wake": ("СОН", "Поправить, если система ошиблась: «0730», «0730 2330», «отбой 2340»."),
          "speech": ("РЕЧЬ", "Сколько минут практиковались, сэр: «15», «10 скороговорки», «20 читал вслух»."),
          }


def _undo_set(c, label, add_ids=None, back=None):
    import hublib as H
    H.meta_set(c, UNDO_KEY, json.dumps({"label": label, "add": add_ids or [],
                                         "back": [list(r) for r in back or [] if r is not None]}))


def _undo_get(c):
    import hublib as H
    try:
        return json.loads(H.meta_get(c, UNDO_KEY, "null") or "null")
    except ValueError:
        return None


def tg_undo(c):
    import hublib as H
    u = _undo_get(c)
    if not u:
        return "Отменять нечего, сэр."
    for gid in u.get("add", []):
        remove(c, gid)
    cols = ("id", "ts", "day", "kind", "value", "note", "src")
    for r in u.get("back", []):
        put_back(c, dict(zip(cols, r)))
    H.meta_set(c, UNDO_KEY, "null")
    return "↶ Отменил: " + u["label"]


def _day_ru(d):
    return "%s, %d %s" % (WD[d.weekday()].capitalize(), d.day, MON[d.month - 1])


def bar(frac, n=10):
    f = max(0.0, min(1.0, frac or 0))
    k = int(round(f * n))
    return "▰" * k + "▱" * (n - k)


# Короткие имена для сжатого пульта — как в виджете better.exe (29.10.2026, просьба: «интерфейс
# в боте слишком длинный, компактнее — как в виджетах или в самой программе»)
TG_SHORT = {"wake": "Подъём", "bed": "Отбой", "code": "Код", "speech": "Речь", "market": "hh.kz",
            "fun": "Прокраст.", "money": "Траты", "cig": "Сигареты", "lift": "Сила", "chores": "Быт"}
TG_MARK = {"take": "🟢", "hold": "🔵", None: "▫️"}


def tg_panel(c, note=None, full=False):
    """Пульт: сжатый — строка на показатель (имя · значение · 🟢/🔵), full — с подробностями."""
    import hubtg as T
    s = compute(c)
    R = s["rows"]
    a, b = rungs(s)
    summary = "взято <b>%d</b> · удержано <b>%d</b> · дней в счёте %d из %d\n⚡ %s" % (
        s["taken"], s["held"], s["week7"], WINDOW, bonus_text(s)[0])
    if not full:
        out = ["<b>◆ BETTER</b> · %s" % _day_ru(today(c)), summary,
               "🪜 ступеней %d из %d" % (a, b),
               "🎯 <code>%s</code>" % T.esc(block_line(s["block"]))]
        if note:
            out.append("<i>%s</i>" % T.esc(note))
        out.append("")
        for k, _name in METRICS:
            r = R[k]
            line = "%s <code>%s</code> %s" % (EMOJI[k], T.esc("%-9s%11s" % (TG_SHORT[k], r["value"])),
                                             TG_MARK[r["state"]])
            if r.get("rung"):
                line += " " + r["rung"]
            out.append(line)
        return _view(T.Html("\n".join(out)), "panel"), _tg_rows(c, "📋 Подробно", "g:d")
    out = ["<b>◆ BETTER</b> · %s" % _day_ru(today(c)), "", summary, "🪜 ступеней %d из %d" % (a, b),
           "🎯 Блок → %s: <code>%s</code>" % (GOAL_NAME, T.esc(block_line(s["block"])))]
    if note:
        out[1:1] = ["<i>%s</i>" % T.esc(note)]
    out.append("")
    for k, name in METRICS:
        r = R[k]
        out.append("%s <b>%s</b>  —  %s" % (EMOJI[k], T.esc(name), T.esc(r["value"])))
        line = VERDICT[r["state"]]
        if r["frac"] is not None and k != "chores":
            line = "<code>%s</code>  %s" % (bar(r["frac"]), line)
        if r.get("rung"):
            line += " · ступень " + r["rung"]
        out.append("      " + line)
        out.append("      <i>%s</i>" % T.esc(r["detail"]))
        out.append("")
    return _view(T.Html("\n".join(out).rstrip()), "detail"), _tg_rows(c, "📋 Кратко", "g:m")


def _tg_rows(c, view_label, view_cb):
    import hubtg as T
    u = _undo_get(c)
    b = T.btn
    rows = [[b("🚬 +1", "g:+cig"), b("🚬 −1", "g:-cig"), b("💸 Трата", "g:i:spend")],
            [b("🗣 Речь", "g:i:speech"), b("🏋 Тренировка", "g:i:lift"), b("🧹 Быт", "g:ch"), b("😴 Сон", "g:i:wake")],
            [b(view_label, view_cb), b("📊 Неделя", "g:wk"), b("📅 Месяц", "g:mo"),
             b("🔄", "g:m" if view_cb == "g:d" else "g:d")]]
    if u:
        rows.append([b("↶ Отменить: " + u["label"][:40], "g:u")])
    return rows


def tg_chores(c, note=None):
    import hubtg as T
    s = compute(c)
    out = ["<b>◆ %s · БЫТ</b>" % T.BRAND,
           "<i>%s</i>" % T.esc(note) if note else "<i>Нажмите, что сделано. Ещё раз — снять отметку.</i>", ""]
    btns, row = [], []
    for ch in s["chores"]:
        m = "✅" if ch["done"] else "🔸" if ch["due"] else "▫️"
        out.append("%s %s — <i>%s</i>" % (m, T.esc(ch["name"]), T.esc(chore_when(ch))))
        row.append(T.btn("%s %s" % (m, ch["name"]), "g:ch:" + ch["key"]))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    out.append("\n<i>🔸 пора сегодня</i>")
    nav = [T.btn("← Назад", "g:m")]
    if _undo_get(c):
        nav.append(T.btn("↶ Отменить", "g:u:ch"))
    return _view(T.Html("\n".join(out)), "chores"), btns + [nav]


def _hmin(sec):
    m = int(round(sec / 60))
    return "%d:%02d" % divmod(m, 60)


def _k(v):
    if v >= 10000:
        return "%dk" % round(v / 1000)
    return "%d" % round(v)


def tg_week(c):
    import hubtg as T
    W = week(c)
    td = today(c)
    head = lambda d: ("%s %2d" % (WD[d.weekday()].capitalize(), d.day)) + ("◂" if d == td else " ")
    t1 = ["%-6s%6s%7s%5s%5s%6s" % ("", "Подъём", "Отбой", "Код", "Речь", "Прокр")]
    t2 = ["%-6s%5s%7s%4s%6s%4s" % ("", "Рынок", "Траты", "Сиг", "Сила", "Быт")]
    for d, v in W:
        wk = (v["wake_a"] + hm(v["wake"])) if v["wake"] is not None else "—"
        bd = (v["bed_a"] + hm(v["bed"])) if v["bed"] is not None else "—"
        t1.append("%-6s%6s%7s%5s%5s%6s" % (head(d), wk, bd, _hmin(v["code"]), _hmin(v["speech"]),
                                           _hmin(v["fun"])))
        t2.append("%-6s%5s%7s%4d%6s%4s" % (head(d), _hmin(v["market"]), _k(v["spend"]) if v["spend_n"] else "—",
                                          v["cig"], _hmin(v["lift"]),
                                          "%d/%d" % (v["chores"], len(CHORES))))
    tot = lambda k: sum(v[k] for _d, v in W)
    spent = [v["spend"] for _d, v in W if v["spend_n"]]
    out = ["<b>◆ %s · НЕДЕЛЯ</b>" % T.BRAND,
           "<i>%s — %s · ≈ — посчитано примерно</i>" % (_day_ru(W[0][0]), _day_ru(W[-1][0])), "",
           "<b>Сон и дело</b>", "<pre>%s</pre>" % T.esc("\n".join(t1)),
           "<b>Рынок, деньги, тело</b>", "<pre>%s</pre>" % T.esc("\n".join(t2)),
           "<b>Итого</b>",
           "💻 программирование %s · 🗣 речь %s" % (dur(tot("code")), dur(tot("speech"))),
           "📺 прокрастинация %s · 💼 hh.kz %s" % (dur(tot("fun")), dur(tot("market"))),
           "🏋 тренировки %s · 🚬 сигарет %d" % (dur(tot("lift")), tot("cig")),
           ("💸 траты %s · в среднем %s за день" % (money(sum(spent)), money(sum(spent) / len(spent))))
           if spent else "💸 траты не записаны"]
    return _view(T.Html("\n".join(out)), "week"), [[T.btn("← Назад", "g:m"), T.btn("🔄 Обновить", "g:wk")]]


def tg_month(c, ym=None):
    """Месяц в боте: числа дней и под ними счёт (взято + удержано), как в окне и в Obsidian."""
    import hubtg as T
    now = today(c)
    y, m = (int(ym[:4]), int(ym[5:7])) if ym else (now.year, now.month)
    days = month_days(c, y, m)
    ok = sum(1 for _d, s in days if s and s["ok"])
    a, b = rungs(compute(c))
    pad = dt.date(y, m, 1).weekday()
    cells = [None] * pad + days + [None] * (-(pad + len(days)) % 7)
    lines = [" ".join("%2s" % w for w in WD)]
    for i in range(0, len(cells), 7):
        wk = cells[i:i + 7]
        lines.append(" ".join("%2s" % (x[0].day if x else "") for x in wk))
        lines.append(" ".join("%2s" % ("" if not x or not x[1] else (x[1]["taken"] + x[1]["held"]) or "·") for x in wk))
    ym_of = lambda k: "%04d-%02d" % (divmod(y * 12 + m - 1 + k, 12)[0], divmod(y * 12 + m - 1 + k, 12)[1] + 1)
    out = ["<b>◆ BETTER · %s %d</b>" % (NOTE_MONTHS[m - 1].upper(), y),
           "🪜 ступеней %d из %d · 📅 месяц %d из %d · 🗓 неделя %d из 7" % (a, b, ok, len(days), week_ok(c, now)),
           "<i>Под числом: взято + удержано. В счёт идёт день со сделанным блоком.</i>",
           "<pre>%s</pre>" % T.esc("\n".join(lines))]
    return (_view(T.Html("\n".join(out)), "month:%04d-%02d" % (y, m)),
            [[T.btn("‹", "g:mo:" + ym_of(-1)), T.btn("🔄", "g:mo:%04d-%02d" % (y, m)), T.btn("›", "g:mo:" + ym_of(1))],
             [T.btn("← Назад", "g:m")]])


def _view(h, name):
    """Пометить сообщение бота видом пульта — hubd обновит его, когда цифры изменятся."""
    h.g_view = name
    return h


PANEL_KEY = "g_panel"                 # последнее сообщение-пульт: {"chat", "mid", "view", "sig"}


def tg_track(c, chat, mid, text):
    """Запомнить сообщение-пульт (или забыть, если на его месте теперь другое)."""
    import hublib as H
    view = getattr(text, "g_view", None)
    try:
        cur = json.loads(H.meta_get(c, PANEL_KEY, "null") or "null")
    except ValueError:
        cur = None
    if view and mid:
        H.meta_set(c, PANEL_KEY, json.dumps({"chat": chat, "mid": mid, "view": view, "sig": str(text)}))
    elif cur and cur.get("mid") == mid:
        H.meta_set(c, PANEL_KEY, "null")


def tg_sync(c, bot):
    """hubd: цифры изменились — перерисовать пульт в Telegram (если текст другой)."""
    import hublib as H
    try:
        cur = json.loads(H.meta_get(c, PANEL_KEY, "null") or "null")
    except ValueError:
        return False
    if not cur:
        return False
    if cur["view"].startswith("month:"):
        res = tg_month(c, cur["view"][6:])
    else:
        res = {"panel": tg_panel, "chores": tg_chores, "week": tg_week,
               "detail": lambda c: tg_panel(c, full=True)}.get(cur["view"], tg_panel)(c)
    if str(res[0]) == cur.get("sig"):
        return False
    if bot.edit(cur["chat"], cur["mid"], *res) is None:
        cur["fail"] = cur.get("fail", 0) + 1     # сеть или сообщение удалено: пять раз подряд — забыть
        H.meta_set(c, PANEL_KEY, "null" if cur["fail"] >= 5 else json.dumps(cur))
        return False
    cur["sig"], cur["fail"] = str(res[0]), 0
    H.meta_set(c, PANEL_KEY, json.dumps(cur))
    return True


def tg_ask(op):
    import hubtg as T
    title, hint = TG_ASK[op]
    return T.Html("<b>◆ %s</b>\n<i>%s</i>" % (title, hint)), [[T.btn("✕ Отмена", "g:x")]]


def tg_wait(c, op, text):
    """Текст после кнопки «Трата» / «Подход» / «Сон» → (понял?, ответ | подсказка)."""
    label, ids = do_text(c, op, text, "tg")
    if ids is None:
        return False, label
    _undo_set(c, label.lstrip("✓ "), ids)
    return True, tg_panel(c, note=label)


def tg_callback(c, bot, chat, mid, cb_id, rest):
    """Кнопки пульта: g:<действие>."""
    import hubtg as T
    toast, res = "", None
    if rest in ("m", "x"):
        if rest == "x":
            T.wait_pop(c)
        res = tg_panel(c)
    elif rest == "+cig":
        _undo_set(c, "+1 сигарета", [do_plus(c, "cig", src="tg")])
        toast = "🚬 сегодня %d" % int(sum_kind(c, today(c), "cig")[0])
        res = tg_panel(c)
    elif rest == "-cig":
        r = do_minus(c, "cig")
        if r is None:
            toast = "Сегодня сигарет не записано"
        else:
            _undo_set(c, "−1 сигарета", back=[r])
            toast = "🚬 сегодня %d" % int(sum_kind(c, today(c), "cig")[0])
        res = tg_panel(c)
    elif rest.startswith("i:"):
        op = rest[2:]
        if op in TG_ASK:
            T.wait_set(c, "g_" + op, None, chat, mid)
            res = tg_ask(op)
    elif rest == "ch":
        res = tg_chores(c)
    elif rest.startswith("ch:"):
        key = rest[3:]
        if key in CHORE_NAMES:
            done, r = do_chore(c, key, "tg")
            name = CHORE_NAMES[key]
            if done:
                _undo_set(c, name + " ✓", [r["id"]])
            else:
                _undo_set(c, "снята отметка: " + name, back=[r])
            toast = ("✓ " if done else "снято: ") + name
        res = tg_chores(c)
    elif rest == "d":
        res = tg_panel(c, full=True)
    elif rest == "wk":
        res = tg_week(c)
    elif rest == "mo":
        res = tg_month(c)
    elif rest.startswith("mo:"):
        res = tg_month(c, rest[3:])
    elif rest == "eve":                       # вечернее «📝 Записать» → пульт
        eve_done(c)
        res = tg_panel(c)
    elif rest == "later":
        toast = "⏰ Напомню в %s" % eve_later(c)
        res = (T.Html("<b>◆ ИТОГИ ДНЯ</b>\n<i>Напомню в %s, сэр.</i>" % time.strftime(
            "%H:%M", time.localtime(eve_get(c)["due"]))), [[T.btn("📝 Записать сейчас", "g:eve")]])
    elif rest.startswith("iv:"):
        IV = _iv()
        it = IV.find(rest[3:])
        if it:
            IV.attend(c, it, "tg")
            toast = "🏆 Сходили — успех"
        res = tg_iv(c, IV.tally(c) if it else "Уже нет в списке, сэр.")
    elif rest == "castle":
        toast, res = _castle().tg_build(c)
    elif rest.startswith("u"):
        toast = tg_undo(c)
        res = tg_chores(c) if rest == "u:ch" else tg_panel(c)
    bot.answer(cb_id, toast)
    if res:
        bot.edit(chat, mid, *res)
        tg_track(c, chat, mid, res[0])


def tg_later(c):
    import hubtg as T
    later_sync(c)
    items = later_list(c)
    if not items:
        return "Потом: пусто, сэр.", None
    out = ["<b>◆ ПОТОМ</b>"] + ["%d. %s" % (i, T.esc(r["note"])) for i, r in enumerate(items, 1)]
    return T.Html("\n".join(out + ["", "Убрать: <code>/later done 2</code>"])), None


def _castle():
    """Лениво: castle сам импортирует этот модуль."""
    import castle
    return castle


def tg_iv(c, note=None):
    """/iv: список и кнопки «сходил». Заметки Obsidian — источник, бот правит их же."""
    import hubtg as T
    IV = _iv()
    IV.sync(c)
    items = IV.scan()
    out = ["<b>◆ СОБЕСЕДОВАНИЯ</b>"] + (["<i>%s</i>" % T.esc(note)] if note else [])
    out += ["%d. %s — %s" % (i, T.esc(it["name"]), T.esc(IV.line(it))) for i, it in enumerate(items, 1)]
    out += ["" , "Новое: <code>/iv Tele2 03.11 15:00 онлайн</code>",
            "Перенос: <code>/iv move 1 04.11 16:00</code> · отмена: <code>/iv cancel 1</code>"]
    return T.Html("\n".join(out)), [[T.btn("✅ Сходил: " + it["name"][:30], "g:iv:" + IV.key(it))]
                                    for it in items if it["status"] == "назначено"] or None


def tg_holst(c):
    import hubtg as T
    text = holst_page(today(c).isoformat())
    if not text:
        return "Холст: сегодня пусто, сэр.", None
    return T.Html("<b>◆ ХОЛСТ</b>\n" + T.esc(text if len(text) <= 3000 else "…" + text[-3000:])), None


def tg_block(a):
    """/block → план; /block 45 60 → свой; /block default → стандарт."""
    if a and not block_text(a):
        return "Так, сэр: /block 45 60 — рынок и код в минутах, /block default — стандарт.", None
    b = plan()[0]
    return "🎯 Блок дня: рынок %d мин, затем код %d мин." % (b["market"], b["code"]), None


def tg_command(c, cmd, arg, chat=None):
    """Команды бота → (текст, кнопки) или None, если команда не наша."""
    import hubtg as T
    a = arg.strip()
    if cmd in ("holst", "холст"):
        if a:
            later_add(c, a, "tg", "thought")
            return "📝 Записал, сэр. Можно возвращаться к делу.", None
        return tg_holst(c)
    if cmd in ("iv", "собес", "собеседование", "собеседования", "interview"):
        if not a:
            return tg_iv(c)
        said, changed = _iv().command(c, a, "tg")
        return tg_iv(c, said) if changed else (said, None)
    if cmd in ("castle", "замок"):
        return _castle().tg(c)
    if cmd in ("later", "потом"):
        later_sync(c)
        w = a.split()
        if len(w) == 2 and w[0] == "done" and w[1].isdigit():
            items = later_list(c)
            n = int(w[1])
            if not 1 <= n <= len(items):
                return "Такого номера нет, сэр.", None
            remove(c, items[n - 1]["id"])
            return tg_later(c)
        if a:
            later_add(c, a, "tg")
            return "📝 Записал, сэр. Можно возвращаться к делу.", None
        return tg_later(c)
    if cmd in ("block", "блок"):
        return tg_block(a)
    if cmd in ("better", "growth", "лучше", "вчера"):
        return tg_panel(c)
    if cmd in ("week", "неделя"):
        return tg_week(c)
    if cmd in ("month", "месяц"):
        return tg_month(c)
    if cmd in ("chores", "быт"):
        return tg_chores(c)
    if cmd in ("cig", "сиг", "сигарета"):
        if a in ("-", "−", "-1", "−1"):
            r = do_minus(c, "cig")
            if r is None:
                return tg_panel(c, note="Сегодня сигарет не записано.")
            _undo_set(c, "−1 сигарета", back=[r])
            return tg_panel(c, note="−1 сигарета")
        _undo_set(c, "+1 сигарета", [do_plus(c, "cig", src="tg")])
        return tg_panel(c, note="+1 сигарета")
    ops = {"speech": "speech", "речь": "speech", "spend": "spend", "трата": "spend", "lift": "lift",
           "подход": "lift", "тренировка": "lift", "sleep": "wake", "wake": "wake", "сон": "wake"}
    if cmd in ops:
        op = ops[cmd]
        if not a:
            T.wait_set(c, "g_" + op, None, chat, None)
            return tg_ask(op)
        ok, res = tg_wait(c, op, a)
        return res if ok else (res, None)
    return None


# ── вечерняя запись (21:00) ─────────────────────────────────────────────────
# Пользователь 28.10: «в конце дня напоминать записать сегодняшние показатели; кнопки Записать и
# на час позже; вечером в 21:00». Показывает hubd (tick → eve_tick): на ПК — уведомление,
# нет за ПК или не ответили за esc_min — в Telegram. Состояние дня — meta g_eve.

EVE_KEY, EVE_HOUR = "g_eve", 21


def eve_get(c, today=None):
    import hublib as H
    today = (today or _today_conn(c)).isoformat()
    try:
        e = json.loads(H.meta_get(c, EVE_KEY, "null") or "null")
    except ValueError:
        e = None
    if not e or e.get("day") != today:
        due = time.mktime(dt.datetime.combine(dt.date.fromisoformat(today), dt.time(EVE_HOUR)).timetuple())
        e = {"day": today, "due": int(due), "pc": None, "tg": None, "done": False}
    return e


def eve_set(c, e):
    import hublib as H
    H.meta_set(c, EVE_KEY, json.dumps(e))


def eve_later(c):
    e = eve_get(c)
    e.update(due=int(time.time()) + 3600, pc=None, tg=None, done=False)
    eve_set(c, e)
    return time.strftime("%H:%M", time.localtime(e["due"]))


def eve_done(c):
    e = eve_get(c)
    e["done"] = True
    eve_set(c, e)


def eve_text(c):
    """→ (заголовок, [что не записано])."""
    s = compute(c)
    T = s["today"]
    miss = []
    if not T["spend_n"]:
        miss.append("💸 траты")
    if not T["speech"]:
        miss.append("🗣 речь (минуты)")
    if not T["lift"]:
        miss.append("🏋 тренировка (минуты)")
    if not entries(c, today(c), "cig"):
        miss.append("🚬 сигареты (если были)")
    due = [ch["name"].lower() for ch in s["chores"] if ch["due"]]
    if due:
        miss.append("🧹 быт: " + ", ".join(due))
    title = "📝 Итоги дня: взято %d, удержано %d" % (s["taken"], s["held"])
    return title, miss


# ── Obsidian: заметка на день + сводка (Пользователь 28.10: «инфографика/статистика пусть приходит
# в Obsidian») ── пишет hubd раз в 10 мин и после полуночи дописывает вчерашний день.
# Файлы генерируются — правки руками перезапишутся. Пишем, только если текст изменился
# (obsidian-git не коммитит пустое).

VAULT = os.environ.get("GROWTH_VAULT") or os.path.expanduser("~/Documents/Vault/Развитие/Better")


def _write_if_changed(path, text):
    try:
        if open(path, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def day_note(c, d):
    s = compute(c, d)
    T, R = s["today"], s["rows"]
    good = s["taken"] + s["held"]
    a, b = rungs(s)
    fm = {"better": True, "date": d.isoformat(), "score": good, "score_of": len(R), "taken": s["taken"],
          "held": s["held"], "day_ok": s["counted"], "rungs": a, "rungs_of": b,
          "wake": hm(T["wake"]) if T["wake"] is not None else None,
          "bed": hm(T["bed"]) if T["bed"] is not None else None,
          "wake_min": T["wake"], "bed_min": T["bed"],
          "code_min": round(T["code"] / 60), "speech_min": round(T["speech"] / 60),
          "market_min": round(T["market"] / 60), "fun_min": round(T["fun"] / 60),
          "spend": round(T["spend"]) if T["spend_n"] else None, "cig": T["cig"],
          "lift_min": round(T["lift"] / 60), "chores": T["chores"],
          "chores_of": len(CHORES)}
    for k, _n in METRICS:
        fm["ok_" + k] = R[k]["met"]
        fm["st_" + k] = R[k]["state"]
    y = lambda v: "null" if v is None else ("true" if v is True else "false" if v is False else
                                           ('"%s"' % v if isinstance(v, str) else str(v)))
    out = ["---"] + ["%s: %s" % (k, v if k == "date" else y(v)) for k, v in fm.items()] + ["---", "",
           "# Better — %s" % _day_ru(d), "",
           "**Взято %d · удержано %d**%s" % (s["taken"], s["held"], " · день в счёте" if s["counted"] else ""),
           "", "| | Показатель | Значение | Итог | Подробно |", "|---|---|---|---|---|"]
    for k, name in METRICS:
        r = R[k]
        out.append("| %s | %s | %s | %s | %s |" % (EMOJI[k], name, r["value"].replace("|", "/"),
                                                  VERDICT[r["state"]], r["detail"].replace("|", "/")))
    done = [ch["name"] for ch in s["chores"] if ch["done"]]
    out += ["", "**Быт:** " + (", ".join(done) if done else "ничего не отмечено")]
    notes = [r["note"] for k in ("speech", "spend", "lift") for r in entries(c, d, k) if r["note"]]
    if notes:
        out += ["", "**Заметки:** " + " · ".join(notes)]
    out += ["", "> Пишет hub (growth.py) сам — правки руками перезапишутся. Сводка: [[Better]], ступени: [[Лестница]]", ""]
    return "\n".join(out)


DASH = r'''---
cssclasses:
  - wide-page
---
# Better

> Сводку и заметки дней пишет hub (growth.py). Окно — Super+M, месяц — клавиша c, бот — /better и /month. Ступени: [[Лестница]].

```dataviewjs
// месяц, как в окне: дни складываются в неделю и месяц, вместо цели года — лестница
const all = dv.pages('"Развитие/Better/Дни"').where(p => p.better).sort(p => p.date, "asc").array();
if (!all.length) { dv.paragraph("Записей ещё нет."); return; }
const key = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const by = Object.fromEntries(all.map(p => [String(p.date).slice(0, 10), p]));
const MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"];
const OK = "#7ee08a", now = new Date(), last = all[all.length - 1];
const root = dv.el("div", "");
let year = now.getFullYear(), month = now.getMonth();
const ring = (name, a, b, col, sub) => {
  const f = b ? Math.min(1, a / b) : 0, L = 2 * Math.PI * 40;
  return `<div style="text-align:center"><svg width="110" height="110" viewBox="0 0 110 110">
    <circle cx="55" cy="55" r="40" fill="none" stroke="#88888833" stroke-width="9"/>
    <circle cx="55" cy="55" r="40" fill="none" stroke="${col}" stroke-width="9" stroke-dasharray="${L * f} ${L}" transform="rotate(-90 55 55)"/>
    <text x="55" y="61" text-anchor="middle" fill="currentColor" font-size="18">${Math.round(f * 100)}%</text></svg>
    <div><b>${name}</b></div><div style="opacity:.6;font-size:.85em">${sub}</div></div>`;
};
const shade = n => `${OK}${Math.round(30 + 200 * Math.min(1, n / 10)).toString(16).padStart(2, "0")}`;
const draw = () => {
  const len = new Date(year, month + 1, 0).getDate(), pad = (new Date(year, month, 1).getDay() + 6) % 7;
  const list = Array.from({length: len}, (_, i) => by[key(new Date(year, month, i + 1))]);
  const ok = list.filter(p => p && p.day_ok).length;
  const mon = new Date(now); mon.setDate(now.getDate() - (now.getDay() + 6) % 7);
  const week = Array.from({length: 7}, (_, i) => by[key(new Date(mon.getFullYear(), mon.getMonth(), mon.getDate() + i))]).filter(p => p && p.day_ok).length;
  let h = `<div style="display:flex;justify-content:space-around;flex-wrap:wrap;gap:12px;margin-bottom:16px">` +
    ring("Лестница", last.rungs || 0, last.rungs_of || 0, "#ff9a3c", `${last.rungs || 0} из ${last.rungs_of || 0} ступеней`) +
    ring("Месяц", ok, len, OK, `${ok} из ${len} дней`) + ring("Неделя", week, 7, "#8fb8e8", `${week} из 7 дней`) + `</div>`;
  h += `<div style="letter-spacing:.08em;opacity:.8;margin:8px 0">${MONTHS[month].toUpperCase()} ${year} ПО ДНЯМ</div>`;
  h += `<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:4px">` +
    ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"].map(d => `<div style="text-align:center;opacity:.6;font-size:.8em">${d}</div>`).join("") +
    "<div></div>".repeat(pad);
  list.forEach((p, i) => {
    const n = p ? (p.taken || 0) + (p.held || 0) : 0, day = i + 1;
    const here = year === now.getFullYear() && month === now.getMonth() && day === now.getDate();
    const bg = n ? shade(p.day_ok ? n : n / 2) : "#88888814";
    const t = p ? `${p.date ? String(p.date).slice(0, 10) : ""}: взято ${p.taken || 0}, удержано ${p.held || 0}` : "";
    const open = p ? `<a class="internal-link" data-href="${p.file.path}" href="${p.file.path}" style="color:inherit;text-decoration:none">${day}</a>` : day;
    h += `<div title="${t}" style="min-height:44px;padding:4px 6px;border-radius:6px;background:${bg};${here ? "outline:2px solid #8fb8e8;" : ""}${p ? "" : "opacity:.45"}">${open}<div style="text-align:right;font-size:.85em;opacity:.8">${p ? (n || "·") : ""}</div></div>`;
  });
  h += `</div><div style="letter-spacing:.08em;opacity:.8;margin:16px 0 8px">ГОД ПО МЕСЯЦАМ — НАЖМИТЕ НА МЕСЯЦ</div>`;
  h += `<div style="display:grid;grid-template-columns:repeat(6,1fr);gap:6px">`;
  MONTHS.forEach((name, m) => {
    const size = new Date(year, m + 1, 0).getDate();
    const n = Array.from({length: size}, (_, i) => by[key(new Date(year, m, i + 1))]).filter(p => p && p.day_ok).length;
    h += `<div data-m="${m}" style="cursor:pointer;padding:6px 8px;border-radius:6px;background:${n ? shade(10 * n / size) : "#88888814"};${m === month ? "outline:2px solid #8fb8e8" : ""}">${name.slice(0, 3)}<div style="opacity:.7;font-size:.85em">${n}/${size}</div></div>`;
  });
  root.innerHTML = h + "</div>";
};
root.addEventListener("click", e => {
  const t = e.target.closest("[data-m]");
  if (t) { month = Number(t.dataset.m); draw(); }
});
draw();
```

```dataviewjs
const days = dv.pages('"Развитие/Better/Дни"').where(p => p.better).sort(p => p.date, "asc").array();
if (!days.length) { dv.paragraph("Записей ещё нет."); return; }
const M = [
  ["wake", "☀️ Подъём", "#ffc857"], ["bed", "🌙 Отбой", "#a08cff"], ["code", "💻 Программирование", "#6ee7a0"],
  ["speech", "🗣 Речь", "#5fd3f0"], ["market", "💼 Рынок (hh.kz)", "#7aa2ff"], ["fun", "📺 Прокрастинация", "#ff7eb6"],
  ["money", "💸 Траты", "#c4e86a"], ["cig", "🚬 Сигареты", "#d9a27a"], ["lift", "🏋 Сила", "#ff8a5c"],
  ["chores", "🧹 Быт", "#6fe0d0"]];

// сетка: строка — показатель, клетка — день (ярко — взято, бледнее — удержано)
const tail = days.slice(-28);
let g = `<table style="border-collapse:separate;border-spacing:3px"><tr><td></td>` +
  tail.map(p => `<td style="font-size:.7em;opacity:.6;text-align:center">${String(p.date).slice(8, 10)}</td>`).join("") + "</tr>";
for (const [k, name, col] of M) {
  g += `<tr><td style="white-space:nowrap;padding-right:8px">${name}</td>` + tail.map(p => {
    const v = p["st_" + k];
    const bg = v === "take" ? col : v === "hold" ? col + "88" : "#88888822";
    return `<td title="${p.date}" style="width:18px;height:18px;border-radius:3px;background:${bg}"></td>`;
  }).join("") + "</tr>";
}
dv.el("div", g + "</table>");

// полосы по минутам за последние 14 дней
const bars = (title, key, col, unit) => {
  const t = days.slice(-14), mx = Math.max(1, ...t.map(p => p[key] || 0));
  return `<div style="flex:1;min-width:240px"><b>${title}</b>` + t.map(p =>
    `<div style="display:flex;align-items:center;gap:6px;font-size:.8em"><span style="width:40px;opacity:.6">${String(p.date).slice(5)}</span>` +
    `<div style="flex:1;background:#88888822;border-radius:3px"><div style="width:${100 * (p[key] || 0) / mx}%;height:10px;background:${col};border-radius:3px"></div></div>` +
    `<span style="width:56px;text-align:right">${p[key] ?? "—"} ${unit}</span></div>`).join("") + "</div>";
};
dv.el("div", [bars("💻 Программирование", "code_min", "#6ee7a0", "мин"), bars("🗣 Речь", "speech_min", "#5fd3f0", "мин"),
  bars("💼 hh.kz", "market_min", "#7aa2ff", "мин"), bars("🏋 Тренировки", "lift_min", "#ff8a5c", "мин"),
  bars("📺 Прокрастинация", "fun_min", "#ff7eb6", "мин"), bars("🚬 Сигареты", "cig", "#d9a27a", "шт")].join(""),
  {attr: {style: "display:flex;gap:18px;flex-wrap:wrap;margin:14px 0"}});

dv.table(["День", "Взято", "Удерж.", "Подъём", "Отбой", "Код", "Речь", "hh.kz", "Прокр.", "Сила", "Траты", "Сиг.", "Быт"],
  days.slice().reverse().map(p => [p.file.link, p.taken ?? 0, p.held ?? 0, p.wake ?? "—", p.bed ?? "—",
    p.code_min, p.speech_min, p.market_min ?? "—", p.fun_min, p.lift_min ?? "—", p.spend ?? "—", p.cig,
    `${p.chores}/${p.chores_of}`]));
```
'''


def obsidian_export(c, days=None):
    """Записать сегодня и вчера (если ≥ FIRST), сводку и лестницу. → список изменённых файлов."""
    today = _today_conn(c)
    changed = []
    for d in (days or (today - dt.timedelta(days=1), today)):
        if d < FIRST:
            continue
        p = os.path.join(VAULT, "Дни", d.isoformat() + ".md")
        if _write_if_changed(p, day_note(c, d)):
            changed.append(p)
    for name, text in (("Better.md", DASH), ("Лестница.md", ladder_note(c))):
        if _write_if_changed(os.path.join(VAULT, name), text):
            changed.append(os.path.join(VAULT, name))
    return changed


def ladder_note(c):
    """Заметка «Лестница»: где стоит каждый показатель и когда взяты ступени."""
    st = compute(c)
    out = ["# Лестница", "", "Ступень берётся за %d дней из %d и не теряется. Один срыв ничего не отнимает." % (HITS, WINDOW),
           "", "| Показатель | Ступень | Дальше | За неделю |", "|---|---|---|---|"]
    for k, name in METRICS:
        L = st["rows"][k].get("ladder")
        if L:
            out.append("| %s %s | %d из %d | %s | %s |" % (
                EMOJI[k], name, L["level"], L["n"], "вершина: " + L["target"] if L["top"] else L["target"],
                "%d из %d" % (L["hits"], WINDOW if L["top"] else HITS)))
    rows = c.execute("SELECT day, note, value FROM growth WHERE kind='ladder' ORDER BY day DESC, id DESC").fetchall()
    if rows:
        out += ["", "## Взятые ступени", "", "| День | Показатель | Ступень |", "|---|---|---|"]
        out += ["| %s | %s | %s |" % (r[0], NAMES.get(r[1], r[1]), step_text(r[1], r[2])) for r in rows]
    return "\n".join(out + ["", "> Пишет hub (growth.py) сам — правки руками перезапишутся. Сводка: [[Better]]", ""])


def _today_conn(c):
    return today(c)


# ── траты → Obsidian Finance/Logs.md (Пользователь 29.10: «пусть записывается параллельно в Obsidian,
# там уже была система трат с графиками»). Формат — общий журнал трат хранилища:
# «- 2026-09-14 06:30 | [amount:: 106] | [category:: Бытовые] | [comment:: Вода 5л]»; страница
# «Финансы💰» (dataviewjs) группирует по месяцу и корню категории. Отмена — строка удаляется.

FIN_LOG = os.environ.get("GROWTH_FIN_LOG") or os.path.expanduser("~/Documents/Vault/Finance/Logs.md")
FIN_CATS = ((r"обед|ланч|столов|бизнес.?ланч", "Обед"),
            (r"такси|yandex go|яндекс go|uber|indrive", "Транспорт/Такси"),
            (r"автобус|метро|проезд|транспорт", "Транспорт/Проезд"),
            (r"доставк|wolt|glovo|яндекс.?еда|chocofood", "Доставка"),
            (r"кофе|coffee|латте|капучино", "Кофе"),
            (r"apple|icloud", "Подписки/Apple"),
            (r"подписк|spotify|google one", "Подписки"),
            (r"кредит|рассрочк", "Кредит"),
            (r"мам|пап|брат|сестр|семь", "Семья"),
            (r"наушник|мышк|клавиатур|техник|кабел|зарядк", "Техника"),
            (r"порош|мыло|шампун|бытов|вода", "Бытовые"),
            (r"магаз|продукт|сиг|чай|хлеб", "Магазин"))


def fin_category(note):
    for rx, cat in FIN_CATS:
        if re.search(rx, note or "", re.I):
            return cat
    return "Без категории"


def fin_line(r):
    clean = lambda t: re.sub(r"[|\[\]\n]+", " ", t or "").strip()
    return "- %s | [amount:: %d] | [category:: %s] | [comment:: %s]" % (
        time.strftime("%Y-%m-%d %H:%M", time.localtime(r["ts"])), round(r["value"]),
        fin_category(r["note"]), clean(r["note"]) or "—")


def fin_append(r):
    try:
        if r is None or not os.path.exists(FIN_LOG):
            return
        line = fin_line(r)
        with open(FIN_LOG, "rb") as f:
            f.seek(0, 2)
            nl = True
            if f.tell():
                f.seek(-1, 2)
                nl = f.read(1) == b"\n"
        with open(FIN_LOG, "a", encoding="utf-8") as f:
            f.write(("" if nl else "\n") + line + "\n")
    except OSError:
        pass


def fin_remove(r):
    try:
        line = fin_line(r)
        lines = open(FIN_LOG, encoding="utf-8").read().split("\n")
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].rstrip() == line:
                del lines[i]
                _write_if_changed(FIN_LOG, "\n".join(lines))
                return
    except OSError:
        pass


def day_frac(c, key, st):
    """Полоска виджета — что сделано сегодня, а не вся лестница (31.10.2026, просьба: «полоски не
    заполняются, активности визуально нет»). Часы — доля цели ступени, пределы — доля предела."""
    r, T = st["rows"][key], st["today"]
    if key in ("wake", "bed"):                  # путь к конечной цели, а не к ступени (31.10.2026, просьба)
        S = steps(key)
        return 0.0 if T[key] is None else max(0.0, min(1.0, (S[0] - T[key]) / (S[0] - S[-1])))
    if key == "chores":
        return r["frac"]
    if key == "money":
        usual = usual_spend(c, today(c))
        return min(1.0, T["spend"] / usual) if usual else float(bool(T["spend_n"]))
    aim = r["ladder"]["aim"]
    v = T[key] if key == "cig" else T[key] / 60
    if key in ("code", "market", "speech", "lift") and aim and v >= aim:    # цель дня взята — полоска к следующей
        aim = next((s for s in steps(key) if s > v), aim)                   # (31.10.2026, просьба)
    return min(1.0, v / aim) if aim else float(v > 0)


USUAL_KEY = "g_usual"                   # meta: обычное по строкам на этот день, day_values за 14 дней долгие
USUAL_DAYS = 14
TIMED = ("code", "market", "fun", "speech", "lift")     # секунды
SHOWN = 30                              # с 30 секунд dur() уже пишет «1 мин»: мерили то, что видно на экране


def measured(key, v):
    return bool(v) and (key not in TIMED or v >= SHOWN)


def usual_values(c, d):
    """Обычное число строки на день d: медиана 14 дней, как usual_spend; нули не считаются, это «не мерили»."""
    import hublib as H
    try:
        hit = json.loads(H.meta_get(c, USUAL_KEY, "null") or "null")
    except ValueError:
        hit = None
    if hit and hit["day"] == d.isoformat():
        return hit["vals"]
    keys = TIMED + ("wake", "bed", "cig", "chores")
    got = {k: [] for k in keys}
    for i in range(1, USUAL_DAYS + 1):
        day = d - dt.timedelta(days=i)
        T = day_values_cached(c, day)
        for k in keys:
            if measured(k, T[k]) and (k != "cig" or day >= CIG_START):
                got[k].append(T[k])
    vals = {k: statistics.median(v) for k, v in got.items() if v}
    H.meta_set(c, USUAL_KEY, json.dumps({"day": d.isoformat(), "vals": vals}))
    return vals


def trend(c, key, st):
    """Треугольник виджета (31.10.2026, пользователь): 1 — лучше обычного, -1 — хуже, None — вровень или не мерили."""
    T, d = st["today"], today(c)
    if key == "money":
        v, usual = T["spend"] if T["spend_n"] else 0, usual_spend(c, d)
    else:
        v, usual = T[key], usual_values(c, d).get(key)
    if not measured(key, v) or usual is None or v == usual:
        return None
    return 1 if (v < usual) == (key in LOWER or key == "money") else -1


def day_gap(key, st):
    """Подъём и отбой: минут до конечной цели, 0 — достигнута, None — ещё нет или другая строка."""
    if key not in ("wake", "bed") or st["today"][key] is None:
        return None
    return max(0, st["today"][key] - steps(key)[-1])


def widget_json(c):
    """Сводка для виджета better.exe на обоях (desktop_widgets_extra.py)."""
    st = compute(c)
    a, b = rungs(st)
    need = len(st["block"]["steps"])
    return {"taken": st["taken"], "held": st["held"], "week7": st["week7"], "window": WINDOW,
            "day": [need if st["counted"] else sum(s["ok"] for s in st["block"]["steps"]), need],
            "rungs": [a, b], "block": st["block"],
            "rows": [dict(key=k, name=name, value=st["rows"][k]["value"],
                          # лимит с нулём ещё ничего не значит (31.10.2026, просьба: «цвет как у остальных»)
                          state=st["rows"][k]["state"] if k not in CLOSED or measured(k, st["today"][k]) else None,
                          frac=day_frac(c, k, st), rung=st["rows"][k].get("rung"), gap=day_gap(k, st),
                          trend=trend(c, k, st))
                     for k, name in METRICS],
            "chores": [sum(1 for ch in st["chores"] if ch.get("done")), len(st["chores"])],
            "icons": {k: ICONS[k] for k, _n in METRICS + (("flame", ""),)},
            "hues": HUES}


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["--json"]:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import hublib
        print(json.dumps(widget_json(hublib.connect()), ensure_ascii=False))


# ── Предупреждения (29.10.2026, с 31.10 — относительно ступени, а не вчера) ─────
# просьба: «когда до красной останется чуть-чуть — уведомление, что надо остановиться… или
# заснуть пораньше». Каждое — раз в логический день (meta g_nudge). pc — только на ПК (экранное
# время, отбой — это про ПК); иначе нет за ПК — в Telegram. through — пробивает «Не беспокоить»
# (в игре CS2 это и есть прокрастинация, после игры уже поздно).
NUDGE_KEY = "g_nudge"
NUDGE_FUN = 10 * 60          # до цели прокрастинации осталось 10 мин
NUDGE_BED = 30               # за 30 мин до «лечь до»
NUDGE_BEHIND = 120           # за 2 ч до «лечь до» — что ещё можно взять


def _now_evening():
    t = time.localtime()
    return evening(t.tm_hour * 60 + t.tm_min) if (t.tm_hour >= 18 or t.tm_hour < DAY_START_H) else None


def nudges(c, at_pc=True):
    """→ [dict(key, title, body, pc, through)] — новые предупреждения, уже отмеченные отправленными.
    Нет за ПК — «только ПК» не отмечаются: придут, когда вернётесь (если ещё верно)."""
    import hublib as H
    s = status(c)
    T, R = s["today"], s["rows"]
    day = today(c).isoformat()
    try:
        st = json.loads(H.meta_get(c, NUDGE_KEY, "null") or "null")
    except ValueError:
        st = None
    if not st or st.get("day") != day:
        st = {"day": day, "sent": []}
    out = []

    def say(key, title, body, pc=False, through=False):
        if key not in st["sent"] and (at_pc or not pc):
            st["sent"].append(key)
            out.append(dict(key=key, title=title, body=body, pc=pc, through=through))

    # блок дня: утром строка плана, дальше — только смена шага и конец блока
    b = s["block"]
    plan_m = {x["key"]: x["goal"] // 60 for x in b["steps"]}
    if b["done"]:
        n = len(later_list(c))
        say("block_done", "🏁 Блок дня сделан",
            "Отдых заслужен, +%d ⚡ в Замке." % _castle().BLOCK + (" В листке «потом»: %d." % n if n else ""))
    elif b["steps"][0]["ok"]:
        say("block_step", "✅ %s сделан" % b["steps"][0]["name"], "Теперь код: %d мин." % plan_m["code"])
    elif T["wake"] is not None:
        say("block_am", "🎯 Блок дня: рынок %d мин, затем код %d мин" % (plan_m["market"], plan_m["code"]),
            "Цель: %s. Мысль, чувство или задача в голову — Super+Shift+I." % GOAL_NAME)

    # Замок: хватает на следующую ступень — раз в день, строить или нет решает он сам
    cs = _castle()
    n = cs.state(c)["next"]
    if n and n["ready"]:
        say("castle_ready", "⚡ Хватает на постройку: %s" % n["name"], "%s — построить в Замке." % cs.BIND)

    # сверх потолка — заметить и похвалить, раз в день на строку
    for k in ("code", "market", "speech", "lift"):
        if R[k]["over"]:
            say("over_" + k, "🔥 %s: сверх потолка" % NAMES[k],
                "Сделано %s, потолок %s. Это уже больше плана, сильно." % (dur(T[k]), dur(plan()[1][k] * 60)))

    # прокрастинация: цель ступени
    goal = R["fun"]["ladder"]["aim"] * 60
    rest = goal - T["fun"]
    if T["fun"] and rest < 0:
        say("fun_over", "🛑 Пора остановиться", "Сегодня %s, цель ступени %s. Самое время вернуться к делу." % (
            dur(T["fun"]), dur(goal)), pc=True, through=True)
    elif T["fun"] and goal >= 2 * NUDGE_FUN and rest <= NUDGE_FUN:
        say("fun_near", "⏳ До цели ступени осталось %s" % dur(rest),
            "Сегодня %s из %s." % (dur(T["fun"]), dur(goal)), pc=True, through=True)

    # отбой: цель ступени на эту ночь, а если она уже позади — удержать свою
    L = R["bed"]["ladder"]
    goal, now = L["aim"], _now_evening()
    if now is not None:
        if L["hold"] is not None and goal < L["hold"] and goal <= now and now >= L["hold"] - NUDGE_BED:
            say("bed_keep", "🌙 Ступень %s ещё можно удержать" % hm(L["hold"]), "Лечь до %s." % hm(L["hold"]),
                pc=True, through=True)
        elif now >= goal:
            say("bed_now", "🌙 Пора спать", "Лечь до %s — это шаг к ступени." % hm(goal), pc=True, through=True)
        elif now >= goal - NUDGE_BED:
            say("bed_soon", "🌙 Через %d мин пора спать" % (goal - now), "Лечь до %s." % hm(goal),
                pc=True, through=True)
        if now >= goal - NUDGE_BEHIND:
            left = []
            for k, emo in (("code", "💻"), ("speech", "🗣"), ("market", "💼"), ("lift", "🏋")):
                short = R[k]["ladder"]["aim"] * 60 - T[k]
                if R[k]["state"] is None and short > 0:
                    left.append("%s %s — ещё %s" % (emo, R[k]["name"], dur(short)))
            due = [ch["name"].lower() for ch in s["chores"] if ch["due"]]
            if due:
                left.append("🧹 " + ", ".join(due[:3]) + (" и ещё %d" % (len(due) - 3) if len(due) > 3 else ""))
            if left:
                say("behind", "📈 До отбоя ~%d ч: ещё можно взять" % max(1, round((goal - now) / 60)),
                    "\n".join(left))

    # траты: только предупреждение, что подошли к обычным
    usual = usual_spend(c, today(c))
    if T["spend_n"] and usual and 0.8 * usual <= T["spend"] <= usual:
        say("money_near", "💸 Траты близко к обычным", R["money"]["detail"])

    # сигареты: цель ступени
    goal = R["cig"]["ladder"]["aim"]
    if T["cig"] and goal >= 1:
        if T["cig"] == goal:
            say("cig_limit", "🚬 Это была последняя на сегодня", "Сегодня %d, цель ступени %s." % (T["cig"], step_text("cig", goal)))
        elif goal >= 2 and T["cig"] == goal - 1:
            say("cig_one", "🚬 До цели ступени осталась одна", "Сегодня %d, цель %s." % (T["cig"], step_text("cig", goal)))

    if out:
        H.meta_set(c, NUDGE_KEY, json.dumps(st))
    return out
