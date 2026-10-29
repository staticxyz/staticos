"""growth — «Лучше вчера» (28.10.2026): сегодня против вчера по сну, программированию, рынку,
прокрастинации, деньгам, сигаретам, силе и быту. Общий для окна hub (первая вкладка,
hub_app.py) и бота hub (/better, hubtg.py).

День — от пробуждения до сна, а не от полуночи (Пользователь 29.10: «после полуночи я могу ещё сидеть
за ПК, и для меня это всё ещё сегодня»). Граница дня — засыпание: начало долгого сна ПК
(журнал hub), без него — долгая тишина в экранном времени, без неё — 05:00. См. night().

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

Цели — «чуть лучше вчера»: подъём и отбой хотя бы на 1 мин раньше (до 05:00 и 21:00), программирование
+5 мин, речь, рынок и сила +1 мин, прокрастинация −1 мин, траты не больше вчерашних и обычных
(медиана 14 дней), сигарет на одну меньше.
"""
import datetime as dt
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
STEP_SLEEP = 1          # было 15; пользователь 29.10: «даже на одну минуту раньше — успех»
STEP_CODE = 5 * 60                      # 29.10.2026, просьба: было +25 мин — «давай на 5 минут»
STEP_MIN = 60                          # речь, рынок, сила: +1 мин к вчера; прокрастинация: −1 мин
# Сигареты считаются с этого (логического) дня — пользователь 29.10.2026: «пусть начинаются с сегодня,
# красными пока не будут — не с чем сравнивать». Первый день без оценки, сравнение — со второго.
# Сдвинуто на 29.10 (просьба: «вчерашний день не считается, т.к. я начал ночью» — 28.10 неполный).
CIG_START = dt.date(2026, 10, 29)
START = dt.date(2026, 10, 28)          # система с 29.10; вчерашний день — только для сравнения
# 29.10.2026, просьба: «День начался сегодня утром, не надо считать вчерашние пару часов» —
# START сдвинут с 27.10. Первый день (FIRST) без оценки «лучше вчера»: не с чем сравнивать.
FIRST = START + dt.timedelta(days=1)     # первый день системы
# прокрастинация, код и hh.kz сравниваются и в первый день (просьба: «прокрастинацию можно считать
# со вчерашним», «код и hh.kz можно также сравнивать со вчерашним»)
COMPARE_KEYS = ("speech", "money", "lift", "chores")
# Заморозка серии (29.10.2026, пользователь одобрил «один пропуск в неделю не обнуляет 🔥»): файл «on» —
# включено; переключатель — Настройки → Config → «Лучше вчера» (по паролю).
FREEZE_FILE = os.path.expanduser("~/.config/jarvis/better-freeze")
LONG_SLEEP = 90                        # мин: сон ПК короче — дрёма, не ночь
DAY_START_H = 5                        # сна не видно — день сменяется в 05:00
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
    invalidate()
    return r


def put_back(c, r):
    if r is not None:
        c.execute("INSERT OR REPLACE INTO growth(id, ts, day, kind, value, note, src)"
                  " VALUES (?,?,?,?,?,?,?)", tuple(r[k] for k in
                                                  ("id", "ts", "day", "kind", "value", "note", "src")))
        if r["kind"] == "spend":
            fin_append(r)
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
    дневные сайты раскладываются по часам пропорционально работе браузеров."""
    apps, sites = {}, {}
    h = _hour_floor(t0)
    while h < t1:
        f = max(0.0, min(t1, h + 3600) - max(t0, h)) / 3600
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
        # ПК не спал: самая долгая тишина в экранном времени (< 2 мин в час, ≥ 3 ч), после которой вернулись
        h, run, best = t0 - 6 * 3600, None, None
        while h + 3600 <= min(now, t0 + 14 * 3600):
            a = hour_act(h)
            if a < 120:
                run = run or h
            else:
                if run and h - run >= 3 * 3600 and h >= t0 + 3 * 3600 and (not best or h - run > best[1] - best[0]):
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
            n = dict(bed=t0 + DAY_START_H * 3600, bed_a="≈", up=up, up_a="")
        elif up >= n["bed"]:
            n.update(up=up, up_a="")
    return n


def boundary(c, d):
    """Начало дня d — засыпание накануне; сна не видно — 05:00."""
    n = night(c, d)
    return n["bed"] if n else _day_ts(d) + DAY_START_H * 3600


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
    market = sum(v for n, v in sites.items() if MARKET_SITE_RE.search(n))
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
                market=int(market), fun=int(fun), spend=sp, spend_n=spn, cig=int(cg),
                lift=int(lv * 60 + lp), lift_live=l_live, lift_n=ln, chores=len(chores_on(c, day)))


# ── сравнение ───────────────────────────────────────────────────────────────

def hm(m):
    return "%02d:%02d" % divmod(int(m) % 1440, 60)


def vs_yday(t, y):
    """Подпись строк «больше вчера»: «вчера 8 мин · сегодня на 5 мин больше» — без цели и «ещё»
    (29.10.2026, просьба: «без "цели" и "ещё", только как было вчера и на сколько сегодня лучше/хуже»)."""
    d = t - y
    return "вчера %s · %s" % (dur(y), "сегодня столько же" if abs(d) < 60 else
                              "сегодня на %s %s" % (dur(abs(d)), "больше" if d > 0 else "меньше"))


def early_late(d, verb):
    """«сегодня на 45 мин раньше» / «лёг на 1 ч 05 мин позже» — d в минутах, минус = раньше
    (29.10.2026, просьба: в Подъёме и Отбое «на N минут/часов раньше вчера или больше»)."""
    d = int(round(d))
    return "%s %s" % (verb, "в то же время" if not d else
                      "на %s %s" % (dur(abs(d) * 60), "раньше" if d < 0 else "позже"))


def fun_top(T):
    """«YouTube 40 мин» — главный источник прокрастинации за день (29.10.2026, пользователь одобрил «больше
    всего …»). Подпись строки — fun_detail, полностью — в шапке графика (l)."""
    top = T.get("fun_top")
    return "%s %s" % (top[0], dur(top[1])) if top and top[1] >= 60 else ""


def dur_short(sec):
    m = int(round(sec / 60))
    # «7 ч 18 м», не «7ч18м» (29.10.2026, просьба: «раздели ч и м отдельно»)
    return "%d м" % m if m < 60 else "%d ч %02d м" % divmod(m, 60)


def fun_detail(T, Y, short=False):
    """С виновником — коротко, иначе не влезает: «на 7 ч 22 м меньше · больше всего YouTube 52 м»."""
    top = T.get("fun_top")
    if not (top and top[1] >= 60):
        return vs_yday(T["fun"], Y["fun"])
    d = T["fun"] - Y["fun"]
    cmp = "столько же, сколько вчера" if abs(d) < 60 else \
        "на %s %s" % (dur_short(abs(d)), "больше" if d > 0 else "меньше")
    # short — окну, если с минутами не влезает в строку (минуты есть в графике и в боте)
    return "%s · больше всего %s" % (cmp, top[0]) + ("" if short else " " + dur_short(top[1]))


def hl_yday(t, y):
    """Цвет хвоста подписи vs_yday в окне: 1 — больше вчера (зелёный), −1 — меньше (красный)."""
    return 0 if abs(t - y) < 60 else (1 if t > y else -1)


def delta_hm(m):
    """Разница в минутах: −12м, +1ч10м, −2ч; ноль — ±0м."""
    m = int(round(m))
    if not m:
        return "±0м"
    h, mm = divmod(abs(m), 60)
    return ("−" if m < 0 else "+") + ("%dч%s" % (h, "%02dм" % mm if mm else "") if h else "%dм" % mm)


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
    """→ {"rows": {ключ: {name, value, detail, met, frac, warn, streak}}, "chores": [...],
    "score": (лучше, из), "streak": дней подряд}.
    met: True — лучше/держусь, False — хуже, None — не с чем сравнить."""
    today_ = today(c)
    st = evaluate(c, d or today_)
    if (d or today_) == today_:
        add_streaks(c, st, today_)
    return st


def add_streaks(c, st, today):
    """Серии с начала системы (START): сколько дней подряд выполнено. Сегодня считается,
    если уже выполнено; не выполнено — серия ещё жива (день не кончился)."""
    R = st["rows"]
    alive = {k: True for k in R}
    cnt = {k: 0 for k in R}
    day_alive, day_cnt = True, 0
    # заморозка: один день «хуже вчера» за календарную неделю (пн–вс) серию не рвёт и не прибавляет;
    # у каждой строки и у общей серии — своя. «Не с чем сравнить» (None) рвёт, как раньше.
    fz = freeze_on()
    used = {}                               # (строка | "day", неделя) → замороженный день
    frozen = {}                             # строка | "day" → день заморозки на этой неделе

    def thaw(k, d):
        wk = d.isocalendar()[:2]
        if not fz or (k, wk) in used:
            return False
        used[(k, wk)] = d
        if wk == today.isocalendar()[:2]:
            frozen[k] = d
        return True
    d = today
    while d > START and (day_alive or any(alive.values())):     # START — только для сравнения
        ev = st if d == today else evaluate(c, d)
        for k in R:
            if not alive[k]:
                continue
            met = ev["rows"][k]["met"]
            if met:
                cnt[k] += 1
            elif d != today and not (met is False and thaw(k, d)):
                alive[k] = False
        good, known = ev["score"]
        if day_alive:
            if known and good * 2 > known:
                day_cnt += 1
            elif d != today and not (known and thaw("day", d)):
                day_alive = False
        d -= dt.timedelta(days=1)
    for k in R:
        R[k]["streak"] = cnt[k]
        R[k]["frozen"] = frozen.get(k) if cnt[k] else None
    st["streak"] = day_cnt
    st["frozen"] = frozen.get("day") if day_cnt else None
    st["freeze"] = fz


def freeze_on():
    try:
        with open(FREEZE_FILE) as f:
            return f.read().strip() == "on"
    except OSError:
        return False


def evaluate(c, d):
    y = d - dt.timedelta(days=1)
    T, Y = day_values_cached(c, d), day_values_cached(c, y)
    R = {}

    # подъём: сегодня против вчера; цель на завтра — сегодняшний −1 мин, не раньше 05:00
    w, wy = T["wake"], Y["wake"]
    goal = max(IDEAL_WAKE, wy - STEP_SLEEP) if wy is not None else None
    det = ["вчера " + (Y["wake_a"] + hm(wy) if wy is not None else "—")]
    # «на N раньше/позже» вместо «цель ≤» (цель = вчера −1 мин, то же самое); цвет — как у значения
    hl = hl_at = None
    if w is not None and wy is not None:
        hl, hl_at = (1 if w <= goal else -1), len(det)
        det.append(early_late(w - wy, "сегодня"))
    elif goal is not None:
        det.append("сегодня проснуться до " + hm(goal))
    if w is not None:
        det.append("завтра проснуться до " + hm(max(IDEAL_WAKE, w - STEP_SLEEP)))
    # насколько раньше/позже вчерашнего (29.10.2026, просьба: «насколько минут раньше проснулся, или
    # наоборот если красный то насколько минут позже, если больше 60 минут то часов»; позже:
    # «получился на 45 минут раньше чем вчера, почему 30?» — разница с вчера, не с целью). Цвет — по цели.
    lead = (delta_hm(w - wy) + " ") if (w is not None and wy is not None) else ""
    R["wake"] = dict(value=(lead + T["wake_a"] + hm(w)) if w is not None else "—", detail=" · ".join(det),
                     hl=hl, hl_at=hl_at, shift=(w - wy) if (w is not None and wy is not None) else None,
                     met=(w <= goal if (w is not None and goal is not None) else None))

    # отбой: прошлая ночь против позапрошлой; сегодня лечь хотя бы на 1 мин раньше прошлой, не раньше 21:00.
    # 29.10.2026 пробовали показывать у сегодняшнего дня только цель на ночь — пользователь вернул:
    # «можно сравнивать с позапрошлым днём, оказывается было правильно, что он красный был».
    b, by = T["bed"], Y["bed"]
    bgoal = max(IDEAL_BED, by - STEP_SLEEP) if by is not None else None
    # подпись «вчера», не «позапрошлой» (29.10.2026, просьба: «после полуночи для меня всё равно сегодня»)
    det = ["вчера " + ((Y["bed_a"] + hm(by)) if by is not None else "—")]
    hl = hl_at = None
    if b is not None and by is not None:
        hl, hl_at = (1 if b <= bgoal else -1), len(det)
        det.append(early_late(b - by, "лёг"))
    if b is not None:
        det.append("сегодня лечь до " + hm(max(IDEAL_BED, b - STEP_SLEEP)))
    # разница — с позапрошлой ночью, как у подъёма со вчера; цвет — по цели (−1 мин)
    lead = (delta_hm(b - by) + " ") if (b is not None and by is not None) else ""
    R["bed"] = dict(value=(lead + T["bed_a"] + hm(b)) if b is not None else "—", detail=" · ".join(det),
                    hl=hl, hl_at=hl_at, shift=(b - by) if (b is not None and by is not None) else None,
                    met=(b <= bgoal if (b is not None and bgoal is not None) else None))

    # программирование: вчера +5 мин
    goal = Y["code"] + STEP_CODE
    left = goal - T["code"]
    R["code"] = dict(value=("▶ " if T["code_live"] else "") + dur(T["code"]),
                     detail=vs_yday(T["code"], Y["code"]), left=left, hl=hl_yday(T["code"], Y["code"]),
                     met=T["code"] >= goal, frac=T["code"] / goal if goal else 1)

    # речь: хотя бы на минуту больше вчерашнего
    goal = Y["speech"] + STEP_MIN        # было +5 мин, не меньше 10 и не больше часа; пользователь 29.10: «на минуту больше»
    left = goal - T["speech"]
    R["speech"] = dict(value=("▶ " if T["speech_live"] else "") + dur(T["speech"]),
                       detail=vs_yday(T["speech"], Y["speech"]), left=left, hl=hl_yday(T["speech"], Y["speech"]),
                       met=T["speech"] >= goal, frac=T["speech"] / goal)

    # рынок: на вкладке hh.kz хотя бы на минуту больше вчерашнего (экранное время)
    goal = Y["market"] + STEP_MIN
    left = goal - T["market"]
    R["market"] = dict(value=dur(T["market"]),
                       detail=vs_yday(T["market"], Y["market"]), left=left, hl=hl_yday(T["market"], Y["market"]),
                       met=T["market"] >= goal, frac=T["market"] / goal)

    # прокрастинация: YouTube, кино, игры — одним числом; хотя бы на минуту меньше вчерашнего
    limit = max(0, Y["fun"] - STEP_MIN)
    rest = limit - T["fun"]
    R["fun"] = dict(value=dur(T["fun"]),
                    # как у кода: «сегодня на N меньше/больше» вместо «осталось» (29.10.2026, просьба:
                    # «не "осталось", а "на N минут меньше, чем вчера"»); меньше — хорошо, зелёным
                    detail=fun_detail(T, Y), detail_short=fun_detail(T, Y, short=True), hl=-hl_yday(T["fun"], Y["fun"]), note=fun_top(T),
                    hl_at=0 if fun_top(T) else None,
                    met=T["fun"] <= limit,
                    frac=(T["fun"] / limit) if limit else (1.0 if T["fun"] else 0), warn=True)

    # траты: не больше вчерашних и обычных
    usual = usual_spend(c, d)
    lims = [v for v in ((Y["spend"] if Y["spend_n"] else None), usual) if v is not None]
    limit = min(lims) if lims else None
    det = ["вчера " + (money(Y["spend"]) if Y["spend_n"] else "—")]
    if usual is not None:
        det.append("обычно " + money(usual))
    if limit is not None and T["spend_n"]:
        rest = limit - T["spend"]
        det.append(("осталось " + money(rest)) if rest >= 0 else ("сверх " + money(-rest)))
    elif limit is not None:
        det.append("предел " + money(limit))
    R["money"] = dict(value=money(T["spend"]) if T["spend_n"] else "не записано", detail=" · ".join(det),
                      met=(T["spend"] <= limit) if (T["spend_n"] and limit is not None) else None,
                      frac=(T["spend"] / limit) if (limit and T["spend_n"]) else None, warn=True)

    # сигареты: на одну меньше вчерашнего
    goal = max(0, Y["cig"] - 1)
    first = d <= CIG_START
    det = "первый день — сравнение с завтра" if first else "вчера %d · цель ≤%d" % (Y["cig"], goal)
    last = last_today(c, "cig") if d == today(c) else None
    if last:
        ago = int(time.time()) - last["ts"]
        det += " · последняя %s (%s назад)" % (time.strftime("%H:%M", time.localtime(last["ts"])), dur(ago))
    known = (Y["cig"] or T["cig"] or cig_recent(c, d)) and not first
    R["cig"] = dict(value=str(T["cig"]), detail=det, met=(T["cig"] <= goal) if known else None,
                    frac=None if first else (T["cig"] / goal) if goal else (1.0 if T["cig"] else 0), warn=True)

    # сила: гантели, отжимания — минут хотя бы на одну больше вчерашнего
    goal = Y["lift"] + STEP_MIN
    left = goal - T["lift"]
    R["lift"] = dict(value=("▶ " if T["lift_live"] else "") + dur(T["lift"]),
                     detail=vs_yday(T["lift"], Y["lift"]), left=left, hl=hl_yday(T["lift"], Y["lift"]),
                     met=T["lift"] >= goal, frac=T["lift"] / goal)

    # быт: всё, что подошло по сроку, сделано
    done = chores_on(c, d)
    chores, due = [], []
    for key, name, every in CHORES:
        prev = chore_last(c, key, y)
        # due — пора сделать сегодня; late — пропущен целый срок (красным)
        gap = (d - prev).days if prev else None
        if key not in done and (gap is None or gap >= every):
            due.append(name.lower())
        chores.append(dict(key=key, name=name, every=every, done=key in done, prev=prev, today=d,
                           due=key not in done and (gap is None or gap >= every),
                           late=key not in done and gap is not None and gap > every))
    R["chores"] = dict(value="%d/%d" % (len(done), len(CHORES)),
                       detail=("надо: " + ", ".join(due)) if due else "всё по плану ✓",
                       met=not due, frac=len(done) / max(1, len(done) + len(due)))

    if d <= FIRST:                          # первый день: сравнивать не с чем
        for k in COMPARE_KEYS:
            R[k].update(met=None, frac=None, hl=None)
            if k != "chores":
                R[k]["detail"] = "первый день — сравнение с завтра"
    for k, name in METRICS:
        R[k]["name"] = name
        R[k].setdefault("frac", None)
        R[k].setdefault("warn", False)
    known = [r for r in R.values() if r["met"] is not None]
    return dict(rows=R, chores=chores, score=(sum(1 for r in known if r["met"]), len(known)),
                today=T, yday=Y)


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
    """«2 дня назад · через 1 день» / «пора сегодня» / «просрочено на 2 дня» (29.10.2026, пользователь
    одобрил: сколько прошло и когда снова, а не «не было · раз в N дн.»)."""
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
    if left == 0:
        return "%s · пора сегодня" % ago
    return "%s · просрочено на %s" % (ago, days_ru(-left))


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
    """[(дата, число|None, подпись, met)] от старого к новому — график строки (l в hub, 29.10.2026).
    До START — пусто; START — только цифра, сравнивать не с чем."""
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
        met = (status(c) if d == t else evaluate(c, d))["rows"][key]["met"] if d > START else None
        out.append((d, n, short_val(key, n), met))
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


def do_text(c, op, text, src="pc"):
    """Ввод текстом: op — wake|spend|lift|speech. → (подпись, [id добавленных]) или (ошибка, None)."""
    text = text.strip()
    if op == "wake":
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

ROW_H, AREA_H, HEAD_H, CHORE_H, TOP_H = 24, 52, 28, 24, 44
INPUT = {"wake": ("подъём [отбой]: ", "«0730» · «0730 2330» · «отбой 2340»"),
         "spend": ("трата: ", "«1500 обед» · «2к такси»"),
         "lift": ("тренировка, минут: ", "«15» · «20 гантели» · «10 отжимания»"),
         "speech": ("речь, минут: ", "«15» · «10 скороговорки» · «20 читал вслух»")}
# строка → что делает Space/Enter и i
PRIMARY = {"wake": None, "bed": None, "code": "pomo", "speech": "i:speech", "market": None,
           "fun": None, "money": "i:spend", "cig": "+cig", "lift": "i:lift", "chores": None}
HINTS = {"wake": "сам: конец сна ПК, первое касание клавиатуры · j/k · Tab вкладка",
         "bed": "сам: начало долгого сна ПК — граница дня",
         "code": "Space — помидор «programming» · Tab вкладка",
         "speech": "Space / i — минуты практики · помидор «речь» считается сам",
         "market": "сам: время на вкладке hh.kz · цель — на минуту больше вчера",
         "fun": "сам: YouTube, кино, игры — одним числом · на минуту меньше вчера",
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
    "freeze": ("....#....", ".#..#..#.", "..#.#.#..", "...###...", "#########",
               "...###...", "..#.#.#..", ".#..#..#.", "....#...."),
    # вкладки hub
    "tab_growth": (".........", ".......##", ".......##", "....##.##", "....##.##",
                   ".##.##.##", ".##.##.##", ".##.##.##", "#########"),
    "tab_items": ("....#....", "...###...", "..#####..", "..#####..", "..#####..",
                  ".#######.", "#########", ".........", "...###..."),
    "tab_words": (".........", ".###.###.", "#...#...#", "#.#.#.#.#", "#...#...#",
                  "#.#.#.#.#", "#...#...#", ".###.###.", "........."),
}
ICONS["teeth_pm"] = ICONS["teeth_am"]
# свой цвет у каждой строки — чтобы различать с первого взгляда
HUES = {"wake": "#ffc857", "bed": "#a08cff", "code": "#6ee7a0", "speech": "#5fd3f0",
        "market": "#7aa2ff", "fun": "#ff7eb6", "money": "#c4e86a", "cig": "#d9a27a",
        "lift": "#ff8a5c", "chores": "#6fe0d0", "flame": "#ff9a3c", "ok": "#7ee08a",
        "freeze": "#9fd8ff"}


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
    out += [("chore", k) for k, _n, _e in CHORES]
    return out


def _caret(s, cur):
    cur = len(s) if cur is None else max(0, min(cur, len(s)))
    return s[:cur] + "⁣" + s[cur:]


def _row_h(kind):
    return AREA_H if kind == "g" else HEAD_H if kind == "head" else CHORE_H


def _state_col(v, met, warn=False):
    return hue(v, "ok") if met else (v.c["err"] if met is False else v.c["faint"])


def draw(v, p, x0, x1, y0, y1):
    c = v.c
    st = status(v.conn)
    good, n = st["score"]
    # сводка: «лучше вчера: N из M», серия и полоса из отрезков по строкам
    hov = v.hover[1] if isinstance(v.hover, tuple) and v.hover[0] == "gseg" else None
    if hov is not None and hov < len(METRICS):
        # подпись отрезка под указателем вместо сводки (29.10.2026, просьба: «подпиши отрезки при наведении»)
        k = METRICS[hov][0]
        r = st["rows"][k]
        verdict = {True: "лучше вчера", False: "хуже вчера"}.get(r["met"], "ещё не ясно")
        w = p.text(x0, y0, r["name"], hue(v, k))
        w += p.text(x0 + w, y0, " · " + verdict, _state_col(v, r["met"]))
        p.text(x0 + w, y0, " · " + r["value"], c["text"], maxw=x1 - x0 - w)
    else:
        w = p.text(x0, y0, "Лучше вчера: ", c["dim"])
        p.text(x0 + w, y0, "%d из %d" % (good, n), hue(v, "ok") if good * 2 > n else c["acc_l"])
    if hov is None and st.get("streak"):
        tw = p.text(x1, y0, "серия %d %s" % (st["streak"], plural(st["streak"], "день", "дня", "дней")),
                    hue(v, "flame"), align="r")
        pix(p, x1 - tw - 14, y0 + 1, ICONS["flame"], hue(v, "flame"), 1)
        if st.get("frozen"):                 # заморозка этой недели уже потрачена
            pix(p, x1 - tw - 27, y0 + 1, ICONS["freeze"], hue(v, "freeze"), 1)
    # отрезки со значками строк; отрезок выбранной строки подчёркнут (29.10.2026, пользователь одобрил)
    kind, cur = current(v)
    cur_i = next((i for i, (k, _n) in enumerate(METRICS) if k == (cur if kind == "g" else "chores" if kind else None)), None)
    if getattr(v, "g_chart", None):
        cur_i = next(i for i, (k, _n) in enumerate(METRICS) if k == v.g_chart)
    seg_y, seg_h, gap = y0 + 20, 13, 3
    sw = (x1 - x0 - gap * (len(METRICS) - 1)) / len(METRICS)
    for i, (k, _n) in enumerate(METRICS):
        met = st["rows"][k]["met"]
        sx = x0 + i * (sw + gap)
        fill = hue(v, k) if met else (c["err"] if met is False else c["line_soft"])
        p.rect(sx, seg_y, sw, seg_h, fill)
        if met is None:
            p.rect(sx, seg_y, sw, seg_h, hue(v, k), 0.25)
        pix(p, sx + (sw - 9) // 2, seg_y + 2, ICONS[k], c["bg"] if met is not None else hue(v, k), 1)
        if hov == i or cur_i == i:
            p.rect(sx, seg_y + seg_h + 2, sw, 2, c["text"] if hov == i else c["acc_l"])
        v.hits.append(((sx, seg_y - 4, sw + gap, 20), ("gseg", i)))
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
                pix(p, x0 + 4, y + 10, ICONS["chores"], hue(v, "chores"), 1)
                hx = x0 + 18
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
    vw = p.text(x1 - 8, y + 5, r["value"], _state_col(v, met) if met is not None else c["text"], align="r")
    nw = p.text(tx, y + 5, r["name"], c["text"], maxw=x1 - tx - 60 - vw)
    if r.get("streak"):
        fx = tx + nw + 10
        pix(p, fx, y + 6, ICONS["flame"], hue(v, "flame"), 1)
        fw = p.text(fx + 12, y + 5, str(r["streak"]), hue(v, "flame"))
        nw += 22 + fw
        if r.get("frozen"):
            pix(p, fx + 16 + fw, y + 6, ICONS["freeze"], hue(v, "freeze"), 1)
            nw += 13
    if sel and v.mode == "ginput":
        prompt = INPUT[v.g_op][0]
        s = v.buf if v.buf else ""
        pw = p.text(tx, y + 21, prompt, c["dim"])
        if s:
            p.text(tx + pw, y + 21, _caret(s, v.cur), c["acc_l"], maxw=x1 - tx - 8 - pw)
        else:
            p.text(tx + pw, y + 21, "⁣" + INPUT[v.g_op][1], c["faint"], maxw=x1 - tx - 8 - pw)
    elif r.get("hl") is not None and " · " in r["detail"]:
        # «сегодня на N больше/меньше» — своим цветом (29.10.2026, просьба: «покрась в другой»);
        # hl_at — номер части, если она не последняя (подъём/отбой: дальше «завтра проснуться до», «лечь до»)
        det = r["detail"]
        if r.get("detail_short") and p.text_w(det) > x1 - tx - 8:
            det = r["detail_short"]
        parts = det.split(" · ")
        i = r.get("hl_at")
        i = len(parts) - 1 if i is None else i
        head, mid, rest = " · ".join(parts[:i]), parts[i], " · ".join(parts[i + 1:])
        tcol = hue(v, "ok") if r["hl"] > 0 else c["err"] if r["hl"] < 0 else c["text"]
        x, room = tx, x1 - tx - 8
        for txt, col in ((head + " · " if head else "", c["dim"]), (mid, tcol), (" · " + rest if rest else "", c["dim"])):
            if txt and room > 20:
                w = p.text(x, y + 21, txt, col, maxw=room)
                x, room = x + w, room - w
    else:
        p.text(tx, y + 21, r["detail"], c["dim"], maxw=x1 - tx - 8)
    bw = x1 - tx - 8
    p.rect(tx, y + 38, bw, 4, c["line_soft"])
    if r.get("shift") is not None:
        # подъём/отбой: середина — вчера, влево — раньше, вправо — позже; край — ±2 ч (29.10.2026)
        mid = tx + bw / 2
        f = max(-1.0, min(1.0, r["shift"] / 120)) * (bw / 2 - 2)
        p.rect(min(mid, mid + f), y + 38, abs(f), 4, _state_col(v, met))
        p.rect(mid - 1, y + 36, 2, 8, c["dim"])
    elif r["frac"] is not None:
        f = max(0.0, min(1.0, r["frac"]))
        bad = r["warn"] and (r["frac"] > 1 or met is False)
        p.rect(tx, y + 38, bw * f, 4, c["err"] if bad else col)
        if r["warn"] and r["frac"] < 1:             # предел — черта в конце
            p.rect(tx + bw - 1, y + 36, 2, 8, c["dim"])
    elif met is not None:
        p.rect(tx, y + 38, bw, 4, _state_col(v, met), 0.7)


def _draw_chart(v, p, x0, x1, y0, y1):
    """График строки за 7 дней: столбик — значение, цвет — лучше/хуже вчера (l — войти, h — назад)."""
    c, key = v.c, v.g_chart
    col = hue(v, key)
    H = history(v.conn, key)
    pix(p, x0 + 4, y0 + 6, ICONS[key], col, 1)
    w = p.text(x0 + 18, y0 + 3, NAMES[key], col)
    p.text(x0 + 18 + w, y0 + 3, " — 7 дней", c["dim"])
    known = [h for h in H if h[3] is not None]
    good = sum(1 for h in known if h[3])
    if known:
        p.text(x1, y0 + 3, "лучше вчера %d из %d" % (good, len(known)),
               hue(v, "ok") if good * 2 > len(known) else c["acc_l"], align="r")
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
    for i, (d, val, lab, met) in enumerate(H):
        bx = x0 + 4 + i * (bw + gap)
        cx = bx + bw / 2
        if val is not None:
            f = (val - lo) / (hi - lo) if hi > lo else (1.0 if val else 0.0)
            bh = max(2, (bot - top) * f)
            p.rect(bx, bot - bh, bw, bh, col if met is None else _state_col(v, met), 0.45 if met is None else 1.0)
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
    st_col = hue(v, "ok") if ch["done"] else (c["err"] if ch["late"] else
                                               c["text"] if ch["due"] else c["line"])
    v.icon_box(p, x0 + 10, y + 7, 9, st_col, ch["done"])
    icol = hue(v, "chores") if not ch["done"] else hue(v, "ok")
    pix(p, x0 + 26, y + 3, ICONS.get(ch["key"], ICONS["chores"]), icol if (ch["due"] or ch["done"]) else c["faint"], 2)
    when = chore_when(ch)
    ww = p.text(x1 - 8, y + 5, when, hue(v, "ok") if ch["done"] else c["err"] if ch["late"]
                else c["dim"] if ch["due"] else c["faint"], align="r")
    p.text(x0 + 52, y + 5, ch["name"], c["dim"] if ch["done"] else c["text"], maxw=x1 - x0 - 64 - ww)


def current(v):
    rs = rows(v)
    i = v.sel["growth"]
    return rs[i] if 0 <= i < len(rs) else (None, None)


def buttons(v, p, x0, x1, y):
    if v.mode == "ginput":
        v.buttons(p, x0, x1, y, [("отмена", ("btn", "g:cancel")), ("записать", ("btn", "g:submit"), True)])
        return
    if getattr(v, "g_chart", None):
        v.buttons(p, x0, x1, y, [("← к списку", ("btn", "g:chart"), True), ("обновить", ("btn", "g:refresh"))])
        return
    kind, key = current(v)
    B = []
    if kind == "chore":
        ch = next(ch for ch in status(v.conn)["chores"] if ch["key"] == key)
        B = [("не сделано" if ch["done"] else "сделано", ("btn", "g:chore"), not ch["done"])]
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
    if getattr(v, "g_chart", None):
        return "h / Esc — к списку · j/k — другая строка"
    kind, key = current(v)
    h = HINTS.get("chore" if kind == "chore" else key, "")
    return h + " · l — график" if kind == "g" else h


# ── бот hub: /better ────────────────────────────────────────────────────────
# Пульт одним сообщением: сводка, кнопки «+1», ввод текстом (трата, подход, сон), быт, неделя.
# Кнопки — g:<действие>; текст после кнопки ловит hubtg.wait_take (op g_<что>) → tg_wait.

UNDO_KEY = "g_undo"                   # последнее действие из бота: {"label", "add": [id] | "back": [row]}
WD = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MON = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
# Пользователь 28.10: «непонятные красные/зелёные круги, всё прижато» → значок строки, статус словом
EMOJI = {"wake": "☀️", "bed": "🌙", "code": "💻", "speech": "🗣", "market": "💼", "fun": "📺",
         "money": "💸", "cig": "🚬", "lift": "🏋", "chores": "🧹"}
VERDICT = {True: "✅ лучше вчера", False: "❌ пока хуже", None: "▫️ не с чем сравнить"}
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
TG_MARK = {True: "✅", False: "❌", None: "▫️"}


def tg_panel(c, note=None, full=False):
    """Пульт: сжатый — строка на показатель (имя · значение · ✅/❌), full — с подробностями."""
    import hubtg as T
    s = compute(c)
    R = s["rows"]
    good, known = s["score"]
    if not full:
        out = ["<b>◆ ЛУЧШЕ ВЧЕРА</b> · %s" % _day_ru(today(c)),
               "<code>%d/%d %s</code>" % (good, known, bar(good / known if known else 0, known or 10)) +
               ("  🔥%d" % s["streak"] if s.get("streak") else "")]
        if note:
            out.append("<i>%s</i>" % T.esc(note))
        out.append("")
        for k, _name in METRICS:
            r = R[k]
            line = "%s <code>%s</code> %s" % (EMOJI[k], T.esc("%-9s%11s" % (TG_SHORT[k], r["value"])),
                                             TG_MARK[r["met"]])
            if r.get("streak"):
                line += "🔥%d" % r["streak"]
            out.append(line)
        return _view(T.Html("\n".join(out)), "panel"), _tg_rows(c, "📋 Подробно", "g:d")
    out = ["<b>◆ ЛУЧШЕ ВЧЕРА</b> · %s" % _day_ru(today(c)), "",
           "Сегодня лучше вчера: <b>%d из %d</b>" % (good, known),
           "<code>%s</code>" % bar(good / known if known else 0, known or 10)]
    if s.get("streak"):
        out.append("🔥 серия: %d %s подряд" % (s["streak"], plural(s["streak"], "день", "дня", "дней")))
    if note:
        out[1:1] = ["<i>%s</i>" % T.esc(note)]
    out.append("")
    for k, name in METRICS:
        r = R[k]
        det = r["detail"]
        head = "%s <b>%s</b>  —  %s" % (EMOJI[k], T.esc(name), T.esc(r["value"]))
        if r.get("streak"):
            head += "  🔥%d" % r["streak"] + ("❄️" if r.get("frozen") else "")
        out.append(head)
        line = VERDICT[r["met"]]
        if r["frac"] is not None and k != "chores":
            line = "<code>%s</code>  %s" % (bar(r["frac"]), line)
        out.append("      " + line)
        out.append("      <i>%s</i>" % T.esc(det))
        out.append("")
    return _view(T.Html("\n".join(out).rstrip()), "detail"), _tg_rows(c, "📋 Кратко", "g:m")


def _tg_rows(c, view_label, view_cb):
    import hubtg as T
    u = _undo_get(c)
    b = T.btn
    rows = [[b("🚬 +1", "g:+cig"), b("🚬 −1", "g:-cig"), b("💸 Трата", "g:i:spend")],
            [b("🗣 Речь", "g:i:speech"), b("🏋 Тренировка", "g:i:lift"), b("🧹 Быт", "g:ch")],
            [b(view_label, view_cb), b("📊 Неделя", "g:wk"), b("🔄", "g:m" if view_cb == "g:d" else "g:d")]]
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
        m = "✅" if ch["done"] else "❗" if ch["late"] else "🔸" if ch["due"] else "▫️"
        out.append("%s %s — <i>%s</i>" % (m, T.esc(ch["name"]), T.esc(chore_when(ch))))
        row.append(T.btn("%s %s" % (m, ch["name"]), "g:ch:" + ch["key"]))
        if len(row) == 2:
            btns.append(row)
            row = []
    if row:
        btns.append(row)
    out.append("\n<i>🔸 пора сегодня · ❗ пропущен срок</i>")
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
    elif rest == "eve":                       # вечернее «📝 Записать» → пульт
        eve_done(c)
        res = tg_panel(c)
    elif rest == "later":
        toast = "⏰ Напомню в %s" % eve_later(c)
        res = (T.Html("<b>◆ ИТОГИ ДНЯ</b>\n<i>Напомню в %s, сэр.</i>" % time.strftime(
            "%H:%M", time.localtime(eve_get(c)["due"]))), [[T.btn("📝 Записать сейчас", "g:eve")]])
    elif rest.startswith("u"):
        toast = tg_undo(c)
        res = tg_chores(c) if rest == "u:ch" else tg_panel(c)
    bot.answer(cb_id, toast)
    if res:
        bot.edit(chat, mid, *res)
        tg_track(c, chat, mid, res[0])


def tg_command(c, cmd, arg, chat=None):
    """Команды бота → (текст, кнопки) или None, если команда не наша."""
    import hubtg as T
    a = arg.strip()
    if cmd in ("better", "growth", "лучше", "вчера"):
        return tg_panel(c)
    if cmd in ("week", "неделя"):
        return tg_week(c)
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
    T, R = s["today"], s["rows"]
    good, known = s["score"]
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
    title = "📝 Итоги дня: лучше вчера %d из %d" % (good, known)
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
    s = st = compute(c, d)
    T, R = s["today"], s["rows"]
    good, known = s["score"]
    fm = {"better": True, "date": d.isoformat(), "score": good, "score_of": known,
          "streak": st.get("streak", 0),
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
    y = lambda v: "null" if v is None else ("true" if v is True else "false" if v is False else
                                           ('"%s"' % v if isinstance(v, str) else str(v)))
    out = ["---"] + ["%s: %s" % (k, v if k == "date" else y(v)) for k, v in fm.items()] + ["---", "",
           "# Лучше вчера — %s" % _day_ru(d), "",
           "**%d из %d** лучше вчера%s" % (good, known, (" · 🔥 серия %d" % st["streak"]) if st.get("streak") else ""),
           "", "| | Показатель | Значение | Итог | Подробно |", "|---|---|---|---|---|"]
    for k, name in METRICS:
        r = R[k]
        out.append("| %s | %s | %s | %s | %s |" % (EMOJI[k], name, r["value"].replace("|", "/"),
                                                  VERDICT[r["met"]], r["detail"].replace("|", "/")))
    done = [ch["name"] for ch in s["chores"] if ch["done"]]
    out += ["", "**Быт:** " + (", ".join(done) if done else "ничего не отмечено")]
    notes = [r["note"] for k in ("speech", "spend", "lift") for r in entries(c, d, k) if r["note"]]
    if notes:
        out += ["", "**Заметки:** " + " · ".join(notes)]
    out += ["", "> Пишет hub (growth.py) сам — правки руками перезапишутся. Сводка: [[Better]]", ""]
    return "\n".join(out)


DASH = r'''---
cssclasses:
  - wide-page
---
# Better — лучше вчера

> Сводку и заметки дней пишет hub (growth.py). Окно — Super+M, бот — /better.

```dataviewjs
const days = dv.pages('"Развитие/Better/Дни"').where(p => p.better).sort(p => p.date, "asc").array();
if (!days.length) { dv.paragraph("Записей ещё нет."); return; }
const last = days[days.length - 1];
const M = [
  ["wake", "☀️ Подъём", "#ffc857"], ["bed", "🌙 Отбой", "#a08cff"], ["code", "💻 Программирование", "#6ee7a0"],
  ["speech", "🗣 Речь", "#5fd3f0"], ["market", "💼 Рынок (hh.kz)", "#7aa2ff"], ["fun", "📺 Прокрастинация", "#ff7eb6"],
  ["money", "💸 Траты", "#c4e86a"], ["cig", "🚬 Сигареты", "#d9a27a"], ["lift", "🏋 Сила", "#ff8a5c"],
  ["chores", "🧹 Быт", "#6fe0d0"]];
const box = (txt, col) => `<div style="flex:1;min-width:120px;padding:10px 14px;border-radius:8px;background:${col}22;border-left:4px solid ${col}">${txt}</div>`;
dv.el("div", [
  box(`<div style="opacity:.7">Сегодня</div><div style="font-size:1.6em"><b>${last.score} из ${last.score_of}</b></div>`, "#7ee08a"),
  box(`<div style="opacity:.7">Серия</div><div style="font-size:1.6em"><b>🔥 ${last.streak || 0}</b></div>`, "#ff9a3c"),
  box(`<div style="opacity:.7">Дней в системе</div><div style="font-size:1.6em"><b>${days.length}</b></div>`, "#7aa2ff"),
].join(""), {attr: {style: "display:flex;gap:10px;flex-wrap:wrap;margin-bottom:14px"}});

// сетка: строка — показатель, клетка — день (зелёный — лучше вчера, красный — хуже)
const tail = days.slice(-28);
let g = `<table style="border-collapse:separate;border-spacing:3px"><tr><td></td>` +
  tail.map(p => `<td style="font-size:.7em;opacity:.6;text-align:center">${String(p.date).slice(8, 10)}</td>`).join("") + "</tr>";
for (const [k, name, col] of M) {
  g += `<tr><td style="white-space:nowrap;padding-right:8px">${name}</td>` + tail.map(p => {
    const v = p["ok_" + k];
    const bg = v === true ? col : v === false ? "#ff5f5f99" : "#88888822";
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

dv.table(["День", "Итог", "Подъём", "Отбой", "Код", "Речь", "hh.kz", "Прокр.", "Сила", "Траты", "Сиг.", "Быт"],
  days.slice().reverse().map(p => [p.file.link, `${p.score}/${p.score_of}`, p.wake ?? "—", p.bed ?? "—",
    p.code_min, p.speech_min, p.market_min ?? "—", p.fun_min, p.lift_min ?? "—", p.spend ?? "—", p.cig,
    `${p.chores}/${p.chores_of}`]));
```

```dataviewjs
// календарь: насыщенность — доля «лучше вчера» за день (плагин Heatmap Calendar)
const days = dv.pages('"Развитие/Better/Дни"').where(p => p.better).array();
if (days.length && typeof renderHeatmapCalendar === "function") {
  renderHeatmapCalendar(this.container, {
    year: new Date().getFullYear(), colors: {better: ["#1f3d2a", "#2e6b45", "#46a067", "#6ee7a0"]},
    showCurrentDayBorder: true,
    entries: days.map(p => ({date: String(p.date).slice(0, 10), intensity: Math.round(4 * p.score / Math.max(1, p.score_of)),
                             content: "", color: "better"}))});
}
```
'''


def obsidian_export(c, days=None):
    """Записать сегодня и вчера (если ≥ FIRST) и сводку. → список изменённых файлов."""
    today = _today_conn(c)
    changed = []
    for d in (days or (today - dt.timedelta(days=1), today)):
        if d < FIRST:
            continue
        p = os.path.join(VAULT, "Дни", d.isoformat() + ".md")
        if d < today:
            # прошедший день: серию берём из его же заметки, если есть (на него не влияет «сегодня»)
            try:
                old = open(p, encoding="utf-8").read()
                m = re.search(r"^streak: (\d+)", old, re.M)
            except OSError:
                m = None
            text = day_note(c, d)
            if m:
                text = re.sub(r"^streak: \d+", "streak: " + m.group(1), text, count=1, flags=re.M)
        else:
            text = day_note(c, d)
        if _write_if_changed(p, text):
            changed.append(p)
    if _write_if_changed(os.path.join(VAULT, "Better.md"), DASH):
        changed.append(os.path.join(VAULT, "Better.md"))
    return changed


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


def widget_json(c):
    """Сводка для виджета better.exe на обоях (desktop_widgets_extra.py)."""
    st = compute(c)
    good, n = st["score"]
    return {"score": [good, n], "streak": st.get("streak", 0),
            "rows": [dict(key=k, name=name, value=st["rows"][k]["value"], met=st["rows"][k]["met"],
                          frac=st["rows"][k].get("frac"), warn=bool(st["rows"][k].get("warn")),
                          streak=st["rows"][k].get("streak", 0))
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


# ── Предупреждения «скоро будет хуже вчера» (29.10.2026) ─────────────────────────
# Просьба: «когда до красной останется чуть-чуть — уведомление, что надо остановиться… или
# заснуть пораньше, чем вчера; то же для остальных параметров, где это можно». Каждое — раз
# в логический день (meta g_nudge). pc — только на ПК (экранное время, отбой — это про ПК);
# иначе нет за ПК — в Telegram. through — пробивает «Не беспокоить» (в игре CS2 это и есть
# прокрастинация, после игры уже поздно).
NUDGE_KEY = "g_nudge"
NUDGE_FUN = 10 * 60          # до предела прокрастинации осталось 10 мин
NUDGE_BED = 30               # за 30 мин до «лечь до»
NUDGE_BEHIND = 120           # за 2 ч до «лечь до» — что ещё не догнало вчера


def _now_evening():
    t = time.localtime()
    return evening(t.tm_hour * 60 + t.tm_min) if (t.tm_hour >= 18 or t.tm_hour < 6) else None


def nudges(c, at_pc=True):
    """→ [dict(key, title, body, pc, through)] — новые предупреждения, уже отмеченные отправленными.
    Нет за ПК — «только ПК» не отмечаются: придут, когда вернётесь (если ещё верно)."""
    import hublib as H
    s = status(c)
    T, Y, R = s["today"], s["yday"], s["rows"]
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

    # прокрастинация: предел = вчера −1 мин (в первый день не с чем сравнивать)
    limit = max(0, Y["fun"] - STEP_MIN)
    rest = limit - T["fun"]
    if R["fun"]["met"] is None:
        pass
    elif T["fun"] and rest < 0:
        say("fun_over", "🛑 Прокрастинация больше вчерашней",
            "Сегодня %s, вчера %s. Остановитесь — дальше только хуже." % (dur(T["fun"]), dur(Y["fun"])),
            pc=True, through=True)
    elif T["fun"] and limit >= 2 * NUDGE_FUN and rest <= NUDGE_FUN:
        say("fun_near", "⏳ Прокрастинация: осталось %s" % dur(rest),
            "Сегодня %s из %s (вчера %s). Пора остановиться." % (dur(T["fun"]), dur(limit), dur(Y["fun"])),
            pc=True, through=True)

    # отбой: лечь хотя бы на 1 мин раньше прошлой ночи
    b = T["bed"]
    now = _now_evening()
    if b is not None and now is not None:
        goal = max(IDEAL_BED, b - STEP_SLEEP)
        if now >= b:
            say("bed_over", "🌙 Уже позже вчерашнего отбоя",
                "Вчера уснули в %s. Ложитесь сейчас." % hm(b), pc=True, through=True)
        elif now >= goal:
            say("bed_now", "🌙 Пора спать",
                "Лечь до %s — и отбой лучше вчерашнего (%s)." % (hm(goal), hm(b)), pc=True, through=True)
        elif now >= goal - NUDGE_BED:
            say("bed_soon", "🌙 Через %d мин пора спать" % (goal - now),
                "Лечь до %s, вчера уснули в %s." % (hm(goal), hm(b)), pc=True, through=True)
        if now >= goal - NUDGE_BEHIND:
            left = []
            for k, emo in (("code", "💻"), ("speech", "🗣"), ("market", "💼"), ("lift", "🏋")):
                if R[k]["met"] is False:
                    left.append("%s %s — ещё %s" % (emo, R[k]["name"], dur(max(60, R[k].get("left", 60)))))
            due = [ch["name"].lower() for ch in s["chores"] if ch["due"]] if R["chores"]["met"] is not None else []
            if due:
                left.append("🧹 " + ", ".join(due[:3]) + (" и ещё %d" % (len(due) - 3) if len(due) > 3 else ""))
            if left:
                say("behind", "📈 До отбоя ~%d ч: догнать вчера" % max(1, round((goal - now) / 60)),
                    "\n".join(left))

    # траты: предел — min(вчера, обычные)
    r = R["money"]
    if T["spend_n"] and r["frac"] is not None:
        if r["met"] is False:
            say("money_over", "💸 Траты больше вчерашних", r["detail"])
        elif r["frac"] >= 0.8:
            say("money_near", "💸 Траты почти на пределе", r["detail"])

    # сигареты: на одну меньше вчерашнего
    goal = max(0, Y["cig"] - 1)
    if R["cig"]["met"] is not None:
        if T["cig"] > goal:
            say("cig_over", "🚬 Сигарет больше цели", "Сегодня %d, вчера %d, цель ≤%d." % (T["cig"], Y["cig"], goal))
        elif goal and T["cig"] == goal:
            say("cig_limit", "🚬 Это была последняя на сегодня", "Сегодня %d из %d — дальше хуже вчера." % (T["cig"], goal))
        elif goal >= 2 and T["cig"] == goal - 1:
            say("cig_one", "🚬 Осталась одна", "Сегодня %d, предел %d." % (T["cig"], goal))

    if out:
        H.meta_set(c, NUDGE_KEY, json.dumps(st))
    return out
