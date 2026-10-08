#!/usr/bin/env python3
"""Discipline — будильник, фокус и помидор в одном окне (06.10.2026; из окна Alarm,
до 07.10.2026 называлось Routine; команды discipline, routine, alarm).

Вкладки:
  Alarm — расписание wake_alarm.py (~/.config/hypr/state/wake-alarm.json);
  Focus — режим фокуса focus_mode.py (state/focus.json, сторож jarvis-focus.service);
  Pomo  — помидор ~/.local/bin/pomo (его состояние и журнал; управляет командой pomo).
Правки пишутся сразу. Вид — как у Настроек (state/settings-skin: skeet | beta |
default), цвета — из обоев. Всё окно рисуется cairo в одной области.

Клавиши — как в nvim пользователя, по keycode (раскладка не важна):
  везде       Shift+H/L, Tab, gt/gT — вкладки · j/k ↓↑ — строки · ? — справка ·
              : — команда (:q :alarm :focus :pomo …) · q, Esc — закрыть
  Alarm       h/l ∓15 мин · Ctrl+X/Ctrl+A, −/= ∓1 ч · i, Enter, Ctrl+E, цифра — время ·
              x пропуск · dd сброс · yy/p · u, Ctrl+R · Space вкл/выкл · t тест · s стоп
  Focus       h/l — длительность / правило · Enter — старт (в сессии — новое время) ·
              Space, x — переключить правило · a — новое правило · dd — удалить ·
              = — +15 мин · Z — завершить раньше (спросит y/n)
  Pomo        h/l — длительность · Enter — старт выбранного · Space, p — старт/пауза ·
              n — пропустить · x — стоп · i — своё («40m отчёт») · c — переименовать задачу
  ввод        Enter, jj, оо, Esc, Ctrl+E — готово · Backspace — стереть

    routine_app.py [alarm|focus|pomo]   открыть на вкладке (второй запуск поднимает окно)
    routine_app.py --shot F [tab=focus sel=N mode=… style=…]   PNG без окна
"""
import datetime as dt
import json
import math
import os
import re
import secrets
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import wake_alarm as wa  # noqa: E402
import focus_mode as fm  # noqa: E402

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

APP_ID = "com.jarvis.discipline"   # было com.jarvis.routine (до 07.10.2026 — «Routine»)
STATE_DIR = os.path.expanduser("~/.config/hypr/state")
MATUGEN = os.path.expanduser("~/.cache/matugen")
POMO = os.path.expanduser("~/.local/bin/pomo")
POMO_LOG = os.path.expanduser("~/.local/share/pomo/log.tsv")
POMO_CONF = os.path.expanduser("~/.config/pomo/config")
FONT = "PxPlus HP 100LX 6x8 Jarvis"
PX = 12            # основной кегль — как у Skeet в Настройках
BIG = 48           # крупные цифры (кратно 8 — без мыла)
SLEEP_H = 8
STEP = 15
TABS = ("alarm", "focus", "pomo")
TAB_NAMES = {"alarm": "Alarm", "focus": "Focus", "pomo": "Pomo"}

W = 440
PAD = 14
ROW_H = 22         # меняется под высоту окна (fit_rows), база — BASE_ROW
BASE_ROW = 22
MAX_ROW = 40
SIZE_FILE = os.path.expanduser("~/.config/hypr/state/discipline-size")   # «ширина высота»
DAYS = 7
PAST = 3           # строк «Недели» в прошлом: там видно, когда встал на деле (06.10.2026)
ON_TIME = 30       # встал не позже плана + столько минут — «вовремя»

DOW = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
          "августа", "сентября", "октября", "ноября", "декабря"]

# параметры фокуса — два ряда по две клетки под длительностями
FOCUS_OPTS = [("auto_pomo", "с помидором"), ("free_breaks", "перерывы свободны"),
              ("strict", "строгий режим"), ("allow_on", "учёба можно")]
FOCUS_DURS = [("25м", 25 * 60), ("50м", 50 * 60), ("1ч", 3600), ("1ч30", 5400),
              ("2ч", 7200), ("∞", 0)]
POMO_DURS = ["25m", "15m", "45m", "1h", "1h30m"]

# keycode → латиница (US-раскладка): раскладка не важна, «оо» = «jj»
KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "
# то же с Shift (US): «:q!», «:w!» в командной строке (07.10.2026 — «!» не печатался)
SHIFTED = dict(zip("1234567890-=[];',./`", "!@#$%^&*()_+{}:\"<>?~"))


# ── цвета ─────────────────────────────────────────────────────────────────────

def hexrgb(h, d=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return d


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""


def palette():
    try:
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    p = {}
    for k, d in (("primary", "#b4c5ff"), ("secondary", "#c5c2ea"), ("tertiary", "#d2bdf6"),
                 ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("surface", "#10131c"), ("surface_container", "#1d1f29"),
                 ("surface_high", "#272a34"), ("on_primary", "#002979"), ("error", "#ffb4ab"),
                 ("st_hi", "#9fb4f5"), ("st_mid", "#5f74b4"), ("st_bot", "#465a94"),
                 ("st_dark", "#0a0c12")):
        p[k] = hexrgb(xc.get(k) or d, hexrgb(d))
    p["vivid"] = hexrgb(read(os.path.join(MATUGEN, "vivid.txt")), p["primary"])
    return p


def style_name():
    s = read(os.path.join(STATE_DIR, "settings-skin")).lower()
    return s if s in ("skeet", "beta") else "default"


def colors(style):
    """Общие имена: bg, dot, text, dim, faint, acc, acc_l, acc_d, field, field_l,
    sel, line, line_soft, strip, frame."""
    p = palette()
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "skeet":
        # как skeet_colors() в settings_app.py: серые оригинала, чуть в акцент обоев
        acc = p["vivid"]

        def g(level, t=0.05):
            return mix((level / 255,) * 3, acc, t)
        return dict(frame="skeet", acc=acc, acc_l=mix(acc, white, 0.22), acc_d=mix(acc, black, 0.40),
                    bg=g(0x13), dot=g(0x18, 0.05), field=g(0x1b), field_l=g(0x24), sel=g(0x1e),
                    line=g(0x30, 0.08), line_soft=g(0x22, 0.06), gdark=g(0x0e, 0.03),
                    line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                    text=mix(hexrgb("#cdcdcd"), p["on_surface"], 0.35), dim=g(0x92, 0.10),
                    faint=g(0x50, 0.10), strip=[acc, p["tertiary"], p["secondary"]], err=p["error"])
    mode = read(os.path.join(STATE_DIR, "settings-mode")).lower() or "dark"
    if style == "beta" and mode == "light":
        ink = mix(p["surface"], black, 0.15)
        ink2 = mix(p["st_bot"], p["surface"], 0.35)
        bg = mix(mix(p["st_hi"], p["on_surface"], 0.85), white, 0.20)
        acc = mix(p["st_mid"], p["st_bot"], 0.40)
        return dict(frame="round", acc=acc, acc_l=acc, acc_d=mix(acc, bg, 0.45), bg=bg, dot=None,
                    field=mix(bg, white, 0.45), field_l=mix(bg, acc, 0.12), sel=mix(bg, acc, 0.16),
                    line=mix(bg, ink2, 0.28), line_soft=mix(bg, ink2, 0.14), gdark=bg,
                    text=ink, dim=mix(ink2, bg, 0.22), faint=mix(ink2, bg, 0.55),
                    strip=[acc], err=mix(p["error"], hexrgb("#7a0000"), 0.55))
    bg, cont = p["surface"], p["surface_container"]
    acc = p["primary"]
    return dict(frame="round", acc=acc, acc_l=mix(acc, white, 0.15), acc_d=mix(acc, bg, 0.50),
                bg=bg, dot=None, field=cont, field_l=p["surface_high"], sel=mix(bg, acc, 0.16),
                line=mix(cont, p["on_surface"], 0.16), line_soft=mix(cont, p["on_surface"], 0.08),
                gdark=bg, text=p["on_surface"], dim=mix(p["on_surface_variant"], bg, 0.30),
                faint=mix(p["on_surface_variant"], bg, 0.65), strip=[acc], err=p["error"])


# ── мелочи ────────────────────────────────────────────────────────────────────

def hm_min(hm):
    h, m = map(int, hm.split(":"))
    return h * 60 + m


def min_hm(m):
    m %= 24 * 60
    return "%02d:%02d" % (m // 60, m % 60)


def dur(minutes):
    h, m = divmod(max(0, int(minutes)), 60)
    if h and m:
        return "%d ч %d мин" % (h, m)
    return "%d ч" % h if h else "%d мин" % m


def mmss(sec):
    sec = max(0, int(sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


def parse_time(buf):
    d = "".join(ch for ch in buf if ch.isdigit())
    if not d:
        return None
    if len(d) <= 2:
        h, m = int(d), 0
    elif len(d) == 3:
        h, m = int(d[0]), int(d[1:])
    else:
        h, m = int(d[:2]), int(d[2:4])
    if h > 23 or m > 59:
        return None
    return "%02d:%02d" % (h, m)


def run_bg(*cmd):
    subprocess.Popen(list(cmd), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def run_out(*cmd):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# ── модели ────────────────────────────────────────────────────────────────────

class Model:
    """Расписание будильника."""

    def __init__(self):
        self.s = wa.load()
        self.mtime = self.stamp()
        self.saved = json.dumps(self.s, sort_keys=True)   # что лежит в файле
        self.undo, self.redo = [], []

    # 07.10.2026: правки — черновик, в файл только по «Сохранить» (Ctrl+S, :w).
    # Пользователь случайно сдвинул время (по умолчанию стало 05:00) — закрыл без
    # сохранения, и при следующем запуске всё как было.
    def dirty(self):
        return json.dumps(self.s, sort_keys=True) != self.saved

    def revert(self):
        if not self.dirty():
            return False
        self.undo.append(json.dumps(self.s, sort_keys=True))
        self.s = json.loads(self.saved)
        return True

    @staticmethod
    def stamp():
        try:
            return os.stat(wa.STATE).st_mtime
        except OSError:
            return 0

    def reload_if_changed(self):
        """Файл поменяли снаружи (CLI, звонок). Черновика нет — перечитать; есть —
        оставить черновик (сохранение перезапишет файл им)."""
        if self.stamp() != self.mtime:
            self.mtime = self.stamp()
            if self.dirty():
                return "kept"
            self.s = wa.load()
            self.saved = json.dumps(self.s, sort_keys=True)
            return True
        return False

    # 08.10.2026: с проверки за 5 минут до звонка и до конца серии день звонка не меняется —
    # ни пропуском, ни выключением, ни сдвигом (иначе серию можно сорвать из полусна).
    # Отменить — только заранее.
    on_refuse = staticmethod(lambda: None)

    @staticmethod
    def series_day():
        d = wa.series_load()
        return d["date"] if wa.series_locks(d) else None

    @staticmethod
    def day_key(s, day):
        return (s["enabled"], s["plan"].get(day), day in s["skip"])

    def change(self, fn):
        before = json.dumps(self.s, sort_keys=True)
        day = self.series_day()
        key = day and self.day_key(self.s, day)
        fn(self.s)
        if day and self.day_key(self.s, day) != key:
            self.s = json.loads(before)
            self.on_refuse()
            return False
        if json.dumps(self.s, sort_keys=True) == before:
            return False
        self.undo.append(before)
        del self.undo[:-100]
        self.redo.clear()
        return True

    def save(self):
        day = self.series_day()
        if day:                          # отменой (u) вернули прежний вид дня серии — его не писать
            f = wa.load()
            if self.day_key(self.s, day) != self.day_key(f, day):
                self.s["enabled"] = f["enabled"]
                if day in f["plan"]:
                    self.s["plan"][day] = f["plan"][day]
                else:
                    self.s["plan"].pop(day, None)
                self.s["skip"] = [x for x in self.s["skip"] if x != day] + ([day] if day in f["skip"] else [])
                self.on_refuse()
        wa.save(self.s)
        self.mtime = self.stamp()
        self.saved = json.dumps(self.s, sort_keys=True)

    def step_back(self, fwd=False):
        src, dst = (self.redo, self.undo) if fwd else (self.undo, self.redo)
        if not src:
            return False
        dst.append(json.dumps(self.s, sort_keys=True))
        self.s = json.loads(src.pop())
        return True

    @staticmethod
    def day(i):
        return dt.date.today() + dt.timedelta(days=i - PAST)

    @staticmethod
    def gone(i):
        """Строка прошедшего дня — план там уже не правится."""
        return i < PAST

    def woke(self, i):
        if i == DAYS:
            return None
        return wa.woke_load().get(self.day(i).isoformat())

    def set_woke(self, i, hm):
        if i == DAYS or i > PAST:
            return False
        wa.woke_set(self.day(i), hm)
        return True

    def on_time(self, i):
        """Встал ли вовремя; None — нет факта или (в прошлом) не было плана."""
        w = self.woke(i)
        if not w or (self.gone(i) and not self.own(i)):
            return None
        if self.via(i) == "tg":
            return None                  # ответ в Telegram можно прислать из кровати
        return hm_min(w) <= hm_min(self.time_of(i)) + ON_TIME

    def via(self, i):
        """Откуда подтверждён подъём: pc — фразой на ПК, tg — только ответом в Telegram."""
        if i == DAYS:
            return None
        return wa.via_load().get(self.day(i).isoformat())

    def time_of(self, i):
        if i == DAYS:
            return self.s["default"]
        return self.s["plan"].get(self.day(i).isoformat(), self.s["default"])

    def own(self, i):
        return i < DAYS and self.day(i).isoformat() in self.s["plan"]

    def skipped(self, i):
        return i < DAYS and self.day(i).isoformat() in self.s["skip"]

    def set_time(self, i, hm):
        if self.gone(i):
            return False

        def f(s):
            if i == DAYS:
                s["default"] = hm
            else:
                d = self.day(i).isoformat()
                s["plan"][d] = hm
                if d in s["skip"]:
                    s["skip"].remove(d)
        return self.change(f)

    def shift(self, i, minutes):
        return self.set_time(i, min_hm(hm_min(self.time_of(i)) + minutes))

    def reset(self, i):
        if i == DAYS or self.gone(i):
            return False
        d = self.day(i).isoformat()
        return self.change(lambda s: (s["plan"].pop(d, None),
                                      s["skip"].remove(d) if d in s["skip"] else None))

    def toggle_skip(self, i):
        if i == DAYS or self.gone(i):
            return False
        d = self.day(i).isoformat()

        def f(s):
            if d in s["skip"]:
                s["skip"].remove(d)
            else:
                s["skip"].append(d)
        return self.change(f)

    def toggle_enabled(self):
        return self.change(lambda s: s.__setitem__("enabled", not s["enabled"]))

    def past(self, i):
        if i < PAST:
            return True
        if i != PAST:
            return False
        if wa.last_rung() == dt.date.today().isoformat():
            return True
        t = wa.alarm_on(self.s, dt.date.today())
        return t is not None and t + dt.timedelta(seconds=wa.LATE_OK) <= dt.datetime.now()


def live_series():
    """Идущая серия проверок (и настоящая, и тестовая) или None."""
    d = wa.series_load()
    if not d or d.get("done"):
        return None
    now = time.time()
    if not d["steps"][0]["check"] <= now <= d["steps"][-1]["until"] + 60:
        return None
    if d.get("test") and not wa.series_pid_alive():
        return None
    return d


def watch_today():
    """Ежедневный Сторож сегодня: "on" — стоит, "skip" — выключен на сегодня, None — выключен
    в Настройках совсем (тогда кнопки в Discipline нет: включают там же, где выключили)."""
    s = wa.load()
    if not s.get("watch_daily", {}).get("enabled", False):
        return None
    return "skip" if dt.date.today().isoformat() in s.get("watch_skip", []) else "on"


# 09.10.2026: выключить Сторожа на день — только через такое «точно?». Каждый раз
# другая фраза (просьба: «Бро, ты уверен? Ты можешь потерять целый день…»).
WATCH_DOUBTS = [
    "Бро, ты уверен? Можно потерять целый день — и шаг к мечте.",
    "Точно выключить? Один такой день легко становится тремя.",
    "Бро, мечта не ждёт. Правда выключить Сторожа на сегодня?",
    "Уверен? Сегодняшний ты решает, кем будет завтрашний.",
    "Дневной сон съест вечер и ночь. Всё равно выключить?",
    "Это ради дела или ради дивана? Выключить?",
    "Дисциплина — делать, когда не хочется. Точно выключить?",
    "Каждый день по шагу — и ты у цели. Пропускаешь шаг?",
    "Будущий ты скажет спасибо, если оставишь. Выключить?",
    "Идёшь по делам — ок. Просто лень — оставь. Выключить?",
    "Бро, ты строил этот режим не для того, чтобы сдаться. Точно?",
    "Один день без Сторожа — это решение. Твоё решение?",
]


def ringing():
    try:
        os.kill(int(open(wa.PIDF).read()), 0)
        return True
    except (OSError, ValueError):
        return False


def pomo_rounds():
    m = re.search(r"^\s*ROUNDS=(\d+)", read(POMO_CONF), re.M)
    return int(m.group(1)) if m else 4


def pomo_state():
    """Состояние pomo из его файла (pomo ничего не тикает — остаток считаем сами)."""
    d = {}
    try:
        for line in open(fm.POMO_STATE):
            k, _, v = line.rstrip("\n").partition("=")
            d[k] = v
    except OSError:
        pass

    def num(k):
        try:
            return int(d.get(k) or 0)
        except ValueError:
            return 0
    phase = d.get("phase") or "idle"
    started, duration, paused = num("started"), num("duration"), num("paused")
    now = time.time()
    left = started + duration - (paused if paused else now)
    if phase != "idle" and not paused and left <= 0:
        phase, left = "idle", 0
    return {"phase": phase, "paused": bool(paused), "left": max(0, left), "duration": duration,
            "end": (now + left) if paused else started + duration, "round": num("round"),
            "custom": d.get("custom") == "1", "task": d.get("task", ""), "next": d.get("next", "")}


def pomo_week():
    """Минуты работы по дням: [(дата, минут, штук)] за 7 дней до сегодня включительно."""
    today = dt.date.today()
    days = {today - dt.timedelta(days=i): [0, 0] for i in range(7)}
    try:
        lines = open(POMO_LOG).read().splitlines()[-2000:]
    except OSError:
        lines = []
    for ln in lines:
        p = ln.split("\t")
        if len(p) < 6 or p[2] != "work":
            continue
        try:
            d = dt.date.fromtimestamp(int(p[0]))
            spent = int(p[4])
        except ValueError:
            continue
        if d in days and spent >= 60:
            days[d][0] += spent // 60
            days[d][1] += 1 if p[5] == "done" else 0
    st = pomo_state()
    if st["phase"] == "work":
        el = st["duration"] - st["left"]
        days[today][0] += int(el // 60)
    return [(d, days[d][0], days[d][1]) for d in sorted(days)]


def pomo_entries(days=14):
    """Журнал pomo по дням: {дата: [отрезок…]} за days дней до сегодня включительно.
    Отрезок — dict(start, end, phase, plan, spent, status, task); день — по концу."""
    today = dt.date.today()
    first = today - dt.timedelta(days=days - 1)
    out = {first + dt.timedelta(days=i): [] for i in range(days)}
    try:
        lines = open(POMO_LOG).read().splitlines()[-5000:]
    except OSError:
        lines = []
    for ln in lines:
        p = ln.split("\t")
        if len(p) < 6:
            continue
        try:
            began, end, plan, spent = int(p[0]), int(p[1]), int(p[3]), int(p[4])
        except ValueError:
            continue
        if spent < 60:
            continue                          # меньше минуты — создан по ошибке (07.10.2026)
        d = dt.date.fromtimestamp(began)      # день — по началу, как у `pomo log`
        if d in out:
            out[d].append(dict(start=began, end=end, phase=p[2], plan=plan, spent=spent,
                               status=p[5], task=p[6] if len(p) > 6 else "", raw=ln))
    for v in out.values():
        v.sort(key=lambda e: (e["start"], e["end"]))
    return out


POMO_TRASH = os.path.expanduser("~/.local/share/pomo/deleted.tsv")
POMO_TODAY = os.path.join(os.path.dirname(fm.POMO_STATE), "today")


def _pomo_today_adjust(e, sign):
    """Счётчик «сегодня» pomo (run/pomo/today: дата, секунды, штук) — тот же учёт, что
    bump_today: только работа ≥ 60 с, начатая сегодня."""
    if e["phase"] != "work" or e["spent"] < 60 or dt.date.fromtimestamp(e["start"]) != dt.date.today():
        return
    try:
        d, t, c = open(POMO_TODAY).read().split("\t")[:3]
        if d != dt.date.today().isoformat():
            return
        t, c = max(0, int(t) + sign * e["spent"]), max(0, int(c) + sign)
        with open(POMO_TODAY, "w") as f:
            f.write("%s\t%d\t%d\n" % (d, t, c))
    except (OSError, ValueError):
        pass


def pomo_delete(e):
    """Удалить отрезок из журнала pomo (строка — в deleted.tsv, чтобы вернуть)."""
    try:
        lines = open(POMO_LOG).read().splitlines()
    except OSError:
        return False
    if e["raw"] not in lines:
        return False
    lines.remove(e["raw"])
    tmp = POMO_LOG + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + ("\n" if lines else ""))
    os.replace(tmp, POMO_LOG)
    with open(POMO_TRASH, "a") as f:
        f.write(e["raw"] + "\n")
    _pomo_today_adjust(e, -1)
    return True


def pomo_restore(e):
    """Вернуть удалённый отрезок на его место (журнал упорядочен по концу)."""
    try:
        lines = open(POMO_LOG).read().splitlines()
    except OSError:
        lines = []
    lines.append(e["raw"])
    lines.sort(key=lambda ln: int(ln.split("\t")[1]) if ln.split("\t")[1].isdigit() else 0)
    tmp = POMO_LOG + ".tmp"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, POMO_LOG)
    _pomo_today_adjust(e, +1)
    return True


def pomo_summary(entries):
    """Итоги по журналу pomo_entries: шт., минуты, серия дней, доля доведённых, частая задача."""
    days = sorted(entries)
    done = [e for d in days for e in entries[d] if e["phase"] == "work" and e["status"] == "done"]
    started = [e for d in days for e in entries[d] if e["phase"] == "work" and e["spent"] >= 60]
    mins = sum(e["spent"] for d in days for e in entries[d] if e["phase"] == "work") // 60
    streak = 0
    for i, d in enumerate(reversed(days)):
        ok = any(e["phase"] == "work" and e["status"] == "done" for e in entries[d])
        if ok:
            streak += 1
        elif i == 0:
            continue                       # сегодня ещё не было — серия считается со вчера
        else:
            break
    tasks = {}
    for e in done:
        if e["task"]:
            tasks[e["task"]] = tasks.get(e["task"], 0) + 1
    top = max(tasks.items(), key=lambda kv: kv[1])[0] if tasks else ""
    rate = round(100 * len(done) / len(started)) if started else 0
    active = sum(1 for d in days if any(e["phase"] == "work" and e["spent"] >= 60 for e in entries[d]))
    return dict(done=len(done), minutes=mins, streak=streak, rate=rate, top=top, active=active)


def task_key(task):
    """Имя задачи для суммирования: без длительности, случайно попавшей в название
    («Исследование 25m» = «Исследование»), без лишних пробелов."""
    words = [w for w in (task or "").split() if not re.fullmatch(r"\d+(?:[.,]\d+)?\s*(?:m|h|м|ч|min|мин)", w, re.I)]
    return " ".join(words) or "без задачи"


def pomo_recent(n=4):
    """Недавние «время задача» — как список в SUPER+T."""
    out = []
    try:
        lines = open(POMO_LOG).read().splitlines()[-300:]
    except OSError:
        lines = []
    for ln in reversed(lines):
        p = ln.split("\t")
        if len(p) >= 7 and p[2] == "work" and p[6]:
            try:
                secs = int(p[3])
            except ValueError:
                continue
            h, m = divmod(secs // 60, 60)
            s = ("%dh" % h if h else "") + ("%dm" % m if m else "")
            item = "%s %s" % (s or "25m", p[6])
            if item not in out:
                out.append(item)
        if len(out) >= n:
            break
    return out


# ── рисование ─────────────────────────────────────────────────────────────────

class Painter:
    def __init__(self, cr):
        self.cr = cr

    def rgb(self, c, a=1.0):
        self.cr.set_source_rgba(c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=1.0):
        self.rgb(c, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()

    def box(self, x, y, w, h, c):
        self.rgb(c)
        self.cr.set_line_width(1)
        self.cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        self.cr.stroke()

    def round(self, x, y, w, h, r):
        cr = self.cr
        cr.new_sub_path()
        cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
        cr.close_path()

    def layout(self, s, px):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(s, -1)
        return lay

    def text_w(self, s, px=PX):
        return self.layout(s, px).get_pixel_size()[0]

    def text(self, x, y, s, c, px=PX, align="l", a=1.0, maxw=None):
        lay = self.layout(s, px)
        if maxw:
            lay.set_width(int(maxw * Pango.SCALE))
            lay.set_ellipsize(Pango.EllipsizeMode.END)
        w, _h = lay.get_pixel_size()
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        self.rgb(c, a)
        self.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(self.cr, lay)
        return w

    def digits(self, x, y, s, c, px=BIG, align="l"):
        """Крупные цифры — каждый знак в своей клетке: ширина строки не прыгает."""
        if not any(ch.isdigit() for ch in s):
            return self.text(x, y, s, c, px=px, align=align)
        cell = self.text_w("0", px)
        w = cell * len(s)
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        for i, ch in enumerate(s):
            self.text(x + i * cell + cell / 2, y, ch, c, px=px, align="c")
        return w


class View:
    """Раскладка и рисунок. Не знает о GTK — рисует в любой cairo-контекст."""

    def __init__(self, model):
        self.m = model
        self.tab = "alarm"
        self.sel = {"alarm": PAST, "focus": 0, "pomo": 0}
        self.col = {"focus": 0, "pomo": 0}       # выбранная клетка в строке-«фишках»/сетке
        self.pomo_view = "start"                 # start | stats — статистика помидоров (s)
        self.stats_day = 13                      # выбранный день из 14 (13 — сегодня)
        self.stats_scroll = 0
        self.stats_sel = -1                      # выбранный отрезок дня (-1 — нет)
        self.stats_rows = []                     # отрезки выбранного дня (для удаления)
        self.stats_undo = []
        self.stats_detail = False                # False — «Сегодня» (кратко), True — 14 дней
        self.mode = "normal"        # normal | insert | text | command | help | confirm
        self.doubt = None           # фраза «точно выключить Сторожа?» на месте кнопок
        self.buf = ""
        self.text_for = None        # что вводим текстом: rule | pomo | task
        self.msg = ""
        self.msg_until = 0
        self.hover = None
        self.hits = []
        self.focus_s = fm.load()
        self.focus_mtime = 0
        self.active = True          # окно в фокусе — рамка в акценте (как у Настроек в Skeet)
        self.reload_style()

    def reload_style(self):
        self.style = style_name()
        self.c = colors(self.style)

    def flash(self, s, secs=2.5):
        self.msg = s
        self.msg_until = time.monotonic() + secs

    def reload_focus(self):
        try:
            mt = os.stat(fm.STATE).st_mtime
        except OSError:
            mt = 0
        if mt != self.focus_mtime:
            self.focus_mtime = mt
            self.focus_s = fm.load()

    # ── раскладка ──
    def height(self):
        """Наименьшая высота окна — раскладка при базовой высоте строки."""
        global ROW_H
        keep, ROW_H = ROW_H, BASE_ROW
        try:
            return self.layout_y()["end"]
        finally:
            ROW_H = keep

    def fit_rows(self, h):
        """Окно выше наименьшего — лишнее поровну на строки (8 строк Alarm), до MAX_ROW."""
        global ROW_H
        extra = max(0, h - self.height())
        ROW_H = min(MAX_ROW, BASE_ROW + extra // (DAYS + 1))

    def layout_y(self):
        f = 6 if self.c["frame"] == "skeet" else 1
        y = f + 2 + 10
        L = {"frame": f, "header": y}
        y += 18 + 14
        L["hero"] = y
        y += BIG + 8 + 16 + 4 + 16 + 16
        L["body"] = y                                    # группы вкладки
        L["week"] = y
        y += 8 + 18 + DAYS * ROW_H + 8 + 14
        L["default"] = y
        y += 8 + ROW_H + 8 + 14
        L["buttons"] = y
        y += 24 + 14
        L["footer"] = y
        y += 18 + 8 + f
        L["end"] = y
        return L

    # ── общий рисунок ──
    def draw(self, cr, w, h):
        self.hits = []
        self.reload_focus()
        self.fit_rows(h)
        p = Painter(cr)
        L = self.layout_y()
        self.draw_frame(p, w, h)
        self.draw_grip(p, w, h, L["frame"])
        x0, x1 = PAD + L["frame"], w - PAD - L["frame"]
        self.draw_header(p, x0, x1, L["header"])
        getattr(self, "draw_" + self.tab)(p, x0, x1, L)
        self.draw_footer(p, x0, x1, L["footer"])
        if self.mode == "help":
            self.draw_help(p, w, h)

    def draw_frame(self, p, w, h):
        c, cr = self.c, p.cr
        if c["frame"] == "skeet":
            # рамка слоями, как у gamesense: 1 светлая, 3 тёмные, 1 светлая, 1 чёрная;
            # у активного окна светлые линии — с акцентом и цветная полоска сверху,
            # у неактивного — серые и полоска гаснет (как Настройки в Skeet)
            l1 = mix(c["line1"], c["acc"], 0.45) if self.active else c["line1"]
            p.rect(0, 0, w, h, c["line3"])
            p.rect(1, 1, w - 2, h - 2, l1)
            p.rect(2, 2, w - 4, h - 4, c["line2"])
            p.rect(5, 5, w - 10, h - 10, l1)
            p.rect(6, 6, w - 12, h - 12, c["bg"])
            p.rgb(c["dot"])
            for yy in range(8, h - 6, 4):
                for xx in range(6 + (yy // 4) % 2 * 2, w - 6, 4):
                    cr.rectangle(xx, yy, 1, 1)
            cr.fill()
            if self.active:
                g = cairo.LinearGradient(6, 0, w - 6, 0)
                n = len(c["strip"])
                for i, col in enumerate(c["strip"]):
                    g.add_color_stop_rgb(i / max(1, n - 1), *col)
                cr.set_source(g)
                cr.rectangle(6, 6, w - 12, 1)
                cr.fill()
                p.rgb(mix(c["strip"][0], c["bg"], 0.55))
            else:
                p.rect(6, 6, w - 12, 1, c["line"])
                p.rgb(c["line2"])
            cr.rectangle(6, 7, w - 12, 1)
            cr.fill()
        else:
            p.round(0.5, 0.5, w - 1, h - 1, 10)
            p.rgb(c["bg"])
            cr.fill_preserve()
            p.rgb(c["acc"] if self.active else c["line"])
            cr.set_line_width(1)
            cr.stroke()

    @staticmethod
    def card(p, c, x, y, w, h):
        """Карточка в стиле окна (для слоя «Фокус»)."""
        if c["frame"] == "skeet":
            p.rect(x, y, w, h, c["line3"])
            p.rect(x + 1, y + 1, w - 2, h - 2, c["line1"])
            p.rect(x + 2, y + 2, w - 4, h - 4, c["line2"])
            p.rect(x + 5, y + 5, w - 10, h - 10, c["line1"])
            p.rect(x + 6, y + 6, w - 12, h - 12, c["bg"])
            g = cairo.LinearGradient(x + 6, 0, x + w - 6, 0)
            n = len(c["strip"])
            for i, col in enumerate(c["strip"]):
                g.add_color_stop_rgb(i / max(1, n - 1), *col)
            p.cr.set_source(g)
            p.cr.rectangle(x + 6, y + 6, w - 12, 1)
            p.cr.fill()
        else:
            p.round(x + 0.5, y + 0.5, w - 1, h - 1, 10)
            p.rgb(c["bg"])
            p.cr.fill_preserve()
            p.rgb(c["line"])
            p.cr.set_line_width(1)
            p.cr.stroke()

    def draw_header(self, p, x0, x1, y):
        c = self.c
        x = x0
        for t in TABS:
            label = TAB_NAMES[t]
            extra = self.tab_badge(t)
            w = p.text_w(label)
            on = t == self.tab
            hov = self.hover == ("tab", t)
            on_col = c["acc_l"] if self.active else c["text"]
            p.text(x, y, label, on_col if on else (c["text"] if hov else c["dim"]))
            if extra:
                ew = p.text(x + w + 6, y, extra, c["acc"] if on else c["faint"])
                w += 6 + ew
            if on:
                p.rect(x, y + 17, w, 2, c["acc"] if self.active else c["line"])
            self.hits.append(((x - 4, y - 6, w + 8, 26), ("tab", t)))
            x += w + 20
        p.text(x1, y, "×", c["dim"] if self.hover != "close" else c["text"], align="r")
        self.hits.append(((x1 - 12, y - 4, 16, 20), "close"))

    def tab_badge(self, t):
        if t == "alarm":
            # «*» — есть несохранённые правки (как [+] у изменённого буфера в nvim)
            return ("*" if self.m.dirty() else "") + ("" if self.m.s["enabled"] else " off")
        if t == "focus":
            return "●" if fm.effective(self.focus_s) else ""
        if t == "pomo":
            st = pomo_state()
            if st["phase"] == "idle":
                return ""
            return ("‖ " if st["paused"] else "") + mmss(st["left"])
        return ""

    def checkbox(self, p, x, y, on):
        c = self.c
        p.rect(x, y, 8, 8, c["line3"] if c["frame"] == "skeet" else c["line"])
        if on:
            g = cairo.LinearGradient(0, y + 1, 0, y + 7)
            g.add_color_stop_rgb(0, *c["acc_l"])
            g.add_color_stop_rgb(1, *c["acc_d"])
            p.cr.set_source(g)
        else:
            p.rgb(c["field_l"])
        p.cr.rectangle(x + 1, y + 1, 6, 6)
        p.cr.fill()

    def group(self, p, x, y, w, h, title, right=""):
        c = self.c
        if c["frame"] == "skeet":
            p.box(x, y, w, h, c["gdark"])
            p.box(x + 1, y + 1, w - 2, h - 2, c["line"])
        else:
            p.round(x + 0.5, y + 0.5, w - 1, h - 1, 6)
            p.rgb(c["field"])
            p.cr.fill_preserve()
            p.rgb(c["line_soft"])
            p.cr.set_line_width(1)
            p.cr.stroke()
        under = c["bg"] if c["frame"] == "skeet" else c["field"]
        tw = p.text_w(title)
        p.rect(x + 10, y - 1, tw + 8, 3, under)
        p.text(x + 14, y - 7, title, c["text"])
        if right:
            rw = p.text_w(right)
            p.rect(x + w - 18 - rw, y - 1, rw + 8, 3, under)
            p.text(x + w - 14, y - 7, right, c["dim"], align="r")

    def button(self, p, x, y, w, label, key, accent=False, dim=False):
        c = self.c
        hov = self.hover == key
        if c["frame"] == "skeet":
            p.rect(x, y, w, 24, c["line3"])
            p.rect(x + 1, y + 1, w - 2, 22, c["line"])
            g = cairo.LinearGradient(0, y + 2, 0, y + 22)
            top = c["field_l"] if not hov else mix(c["field_l"], c["text"], 0.06)
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *c["field"])
            p.cr.set_source(g)
            p.cr.rectangle(x + 2, y + 2, w - 4, 20)
            p.cr.fill()
        else:
            p.round(x + 0.5, y + 0.5, w - 1, 23, 6)
            p.rgb(c["sel"] if hov else c["field"])
            p.cr.fill_preserve()
            p.rgb(c["line"])
            p.cr.set_line_width(1)
            p.cr.stroke()
        col = c["faint"] if dim else (c["acc_l"] if accent or hov else c["text"])
        p.text(x + w / 2, y + 5, label, col, align="c")
        self.hits.append(((x, y, w, 24), key))

    def buttons(self, p, x0, x1, y, labels):
        gap = 8
        n = len(labels)
        w = (x1 - x0 - gap * (n - 1)) / n
        for k, item in enumerate(labels):
            lab, key = item[0], item[1]
            acc = item[2] if len(item) > 2 else False
            self.button(p, round(x0 + k * (w + gap)), y, round(w), lab, key, acc)

    def chip(self, p, x, y, label, on, sel, key):
        """«Фишка» выбора (длительность): рамка, выбранная — в акценте."""
        c = self.c
        w = p.text_w(label) + 14
        if sel:
            p.rect(x, y + 2, w, ROW_H - 4, c["field_l"])
        p.box(x, y + 2, w, ROW_H - 4, c["acc"] if (sel or on) else c["line"])
        p.text(x + 7, y + (ROW_H - 16) // 2 + 1, label, c["acc_l"] if (sel or on) else c["text"])
        self.hits.append(((x, y, w, ROW_H), key))
        return w

    def draw_grip(self, p, w, h, f):
        """Уголок размера, как у виджетов: косые штрихи пунктиром у правого нижнего угла."""
        p.rgb(self.c["faint"])
        for k in (4, 8, 12):
            for t in range(0, k, 2):
                p.cr.rectangle(w - f - 3 - t, h - f - 3 - (k - 1 - t), 1, 1)
        p.cr.fill()

    def row_bg(self, p, x0, x1, y, sel, key, h=None):
        h = h or ROW_H
        c = self.c
        if sel:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"])
            p.rect(x0 + 1, y, 2, h, c["acc"])
        elif self.hover == key:
            p.rect(x0 + 1, y, x1 - x0 - 2, h, c["sel"], 0.5)
        self.hits.append(((x0, y, x1 - x0, h), key))

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        if self.mode in ("command", "text"):
            prompt = ":" if self.mode == "command" else {"rule": "блокировать: ", "pomo": "pomo ",
                                                         "task": "задача: ",
                                                         "allow": "учёба: "}.get(self.text_for, "")
            w = p.text(x0, y, prompt + self.buf, c["text"])
            if int(time.monotonic() * 2) % 2 == 0:
                p.rect(x0 + w, y + 1, 6, 14, c["acc_l"])
            return
        if self.mode == "confirm":
            # кнопки «Да» / «Нет» — щелчком тоже (07.10.2026, пользователь); y/Enter и n/Esc — как было
            bx = x1
            for lab, key, on in (("Нет", "c.no", False), ("Да", "c.yes", True)):
                bw = p.text_w(lab) + 20
                bx -= bw
                p.rect(bx, y - 2, bw, 19, c["acc"] if on else c["field_l"])
                p.text(bx + 10, y, lab, c["bg"] if on else c["text"])
                self.hits.append(((bx, y - 4, bw, 23), key))
                bx -= 8
            p.text(x0, y, self.confirm_text, c["acc_l"], maxw=bx - x0 - 8)
            return
        badge = {"normal": "NORMAL", "insert": "INSERT", "help": "HELP"}.get(self.mode, "NORMAL")
        bw = p.text_w(badge) + 10
        p.rect(x0, y - 1, bw, 16, c["acc"] if self.mode != "normal" else c["field_l"])
        p.text(x0 + 5, y, badge, c["bg"] if self.mode != "normal" else c["acc_l"])
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x0 + bw + 10, y, self.msg, c["text"], maxw=x1 - x0 - bw - 10)
        else:
            hint = {"alarm": "i время · x пропуск · ? клавиши",
                    "focus": "Space правило · ? клавиши",
                    "pomo": (("v кратко · s назад" if self.stats_detail
                              else "v подробно · s назад · ? клавиши") if self.pomo_view == "stats"
                             else "s статистика · Space пауза · ? клавиши")}[self.tab]
            col = c["faint"]
            if self.mode == "insert":
                hint = "цифры · Enter/jj — готово · Esc"
            elif self.tab == "alarm" and self.m.dirty():
                hint, col = "не сохранено · Ctrl+S — сохранить", c["acc_l"]
            p.text(x1, y, hint, col, align="r")

    HELP = {
        "alarm": [("h l  ← →", "−/+ 15 минут"), ("^X ^A  - =", "−/+ 1 час"),
                  ("w", "встал сейчас (сегодня)"), ("прошлые дни", "i — когда встали, dd — стереть"),
                  ("i  Enter  ^E", "ввести время (830 → 08:30)"), ("x", "пропустить день"),
                  ("dd", "как по умолчанию"), ("yy  p", "копировать / вставить время"),
                  ("u  ^R", "отмена / повтор"), ("Space", "будильник вкл / выкл"),
                  ("t  s", "тест / стоп звонка"), ("o", "Сторож: выкл / вкл на сегодня"), ("^S  :w", "сохранить · :q! — выйти без сохранения")],
        "focus": [("h l", "длительность / параметр / правило"), ("Enter", "старт (в сессии — заново)"),
                  ("Space  x", "вкл / выкл"), ("a", "новое правило (текст заголовка)"),
                  ("dd", "удалить правило"), ("e", "слова «учёба можно»"),
                  ("=", "+15 минут"), ("Z", "завершить раньше (не в строгом)")],
        "pomo": [("Space  p", "старт / пауза"), ("n", "пропустить отрезок"), ("x", "стоп"),
                 ("i", "своё: «40m отчёт»"), ("c", "переименовать задачу"),
                 ("s", "итоги дня: h l — день, j k — помидор, s — назад"),
                 ("v", "подробно (14 дней) / обратно кратко"),
                 ("dd  x  Del", "в статистике: удалить отрезок (u — вернуть)")],
    }

    def draw_help(self, p, w, h):
        c = self.c
        f = self.layout_y()["frame"]
        p.rect(f, f + 2, w - 2 * f, h - 2 * f - 2, c["bg"])
        rows = [("Shift+H/L  Tab", "вкладки"), ("j k  g G", "строки")] + self.HELP[self.tab] + [
            (":", ":q  :alarm  :focus  :pomo"), ("q  Esc", "закрыть")]
        x0 = f + PAD + 8
        y = f + 22
        p.text(x0, y, "Клавиши · " + TAB_NAMES[self.tab], c["acc_l"])
        y += 26
        for k, v in rows:
            p.text(x0, y, k, c["acc_l"])
            p.text(x0 + 130, y, v, c["text"], maxw=w - x0 - 130 - f - PAD)
            y += 20
        p.text(x0, h - f - 30, "любая клавиша — назад", c["faint"])

    # ── Alarm ──
    def alarm_rows(self):
        return DAYS + 1

    def draw_alarm(self, p, x0, x1, L):
        c, m = self.c, self.m
        self.draw_alarm_hero(p, x0, x1, L["hero"])
        facts = [m.on_time(i) for i in range(PAST)]
        known = [f for f in facts if f is not None]
        right = ("вовремя %d из %d" % (sum(known), len(known))) if known else ""
        self.group(p, x0, L["week"], x1 - x0, 8 + 18 + DAYS * ROW_H + 8, "Неделя", right)
        self.draw_week(p, x0, x1, L["week"] + 8)
        self.group(p, x0, L["default"], x1 - x0, 8 + ROW_H + 8, "По умолчанию")
        self.draw_day(p, x0 + 1, x1 - 1, L["default"] + 8, DAYS)
        ser = live_series()
        if self.mode == "confirm" and self.doubt:
            # «точно выключить Сторожа?» — фраза целиком на месте кнопок, в две строки
            words, lines = self.doubt.split(), [""]
            for w_ in words:
                t = (lines[-1] + " " + w_).strip()
                if lines[-1] and p.text_w(t) > x1 - x0 - 8:
                    lines.append(w_)
                else:
                    lines[-1] = t
            for i, ln in enumerate(lines[:2]):
                p.text(x0 + 4, L["buttons"] - 6 + i * 18, ln, c["acc_l"])
        elif ser and not ser.get("test") and wa.series_locks(ser):
            p.text(x0 + 4, L["buttons"] + 6, "идёт проверка — сегодня не меняется",
                   c["dim"])
        elif ringing():
            self.buttons(p, x0, x1, L["buttons"], [("Стоп", "a.stop", True)])
        elif m.dirty():
            self.buttons(p, x0, x1, L["buttons"], [("Сохранить", "a.save", True),
                                                   ("Вернуть", "a.revert")])
        else:
            row = [("Тест", "a.test"), ("Пропуск", "a.skip"), ("Как обычно", "a.reset")]
            ws = watch_today()
            if ws:                       # залита — Сторож сегодня на посту; щелчок — выкл / вкл
                row[2] = ("Обычно", "a.reset")
                row.append(("Сторож", "a.watch", ws == "on"))
            self.buttons(p, x0, x1, L["buttons"], row)
        _ = c, m

    def draw_alarm_hero(self, p, x0, x1, y):
        c, m = self.c, self.m
        now = dt.datetime.now()
        # флажок «включён» — справа сверху
        label = "включён" if m.s["enabled"] else "выключен"
        lw = p.text_w(label)
        bx = x1 - lw - 14
        self.checkbox(p, bx, y + 3, m.s["enabled"])
        p.text(bx + 14, y, label, c["text"] if m.s["enabled"] else c["dim"])
        self.hits.append(((bx - 4, y - 4, lw + 22, 20), "a.enabled"))
        ser = live_series()
        if ser:
            self.draw_series(p, x0, x1, y, ser)
            return
        if ringing():
            p.digits(x0, y, time.strftime("%H:%M"), c["acc_l"])
            p.text(x0, y + BIG + 8, "пробный звонок — наберите фразу или s", c["acc_l"])
            return
        t = wa.next_alarm(m.s) if m.s["enabled"] else None
        if t is None:
            p.digits(x0, y, "--:--", c["faint"])
            p.text(x0, y + BIG + 8, "будильник выключен" if not m.s["enabled"]
                   else "на неделе звонков нет", c["dim"])
            return
        p.digits(x0, y, t.strftime("%H:%M"), c["acc_l"])
        left = (t - now).total_seconds() / 60
        when = "сегодня" if t.date() == now.date() else (
            "завтра" if t.date() == now.date() + dt.timedelta(days=1) else DOW[t.weekday()])
        p.text(x0, y + BIG + 8, "%s, %d %s" % (when, t.day, MONTHS[t.month - 1]), c["text"])
        p.text(x1, y + BIG + 8, "через " + dur(left) if left > 0 else "сейчас", c["dim"], align="r")
        bed = t - dt.timedelta(hours=SLEEP_H)
        if bed > now:
            s2, col = "лечь до %s — будет %d ч сна" % (bed.strftime("%H:%M"), SLEEP_H), c["dim"]
        else:
            s2 = "если лечь сейчас — %s сна" % dur(left)
            col = c["acc"] if left < SLEEP_H * 60 - 60 else c["dim"]
        p.text(x0, y + BIG + 8 + 20, s2, col)
        p.text(x1, y + BIG - 18, "+%d повтора · %d мин" % (wa.REPEATS, wa.GAP), c["faint"], align="r")

    def draw_series(self, p, x0, x1, y, d):
        """08.10.2026: идёт серия проверок — какой шаг, до скольки, что уже подтверждено."""
        c = self.c
        st = wa.cur_step(d)
        fmt = "%H:%M:%S" if d.get("test") else "%H:%M"
        ring = st and st["state"] == "ring"
        p.digits(x0, y, d["t"] if not d.get("test") else time.strftime("%H:%M"),
                 c["err"] if ring else c["acc_l"])
        tag = "ТЕСТ · " if d.get("test") else ""
        if st is None:
            line, col = tag + "проверки окончены", c["dim"]
        elif ring:
            line, col = tag + "звонит: фраза на экране или пример в TG", c["err"]
        elif st["state"] == "check":
            line, col = tag + "проверка: наберите фразу — до " + time.strftime(fmt, time.localtime(st["due"])), c["acc_l"]
        else:
            line, col = tag + "следующая проверка в " + time.strftime(fmt, time.localtime(st["check"])), c["text"]
        p.text(x0, y + BIG + 8, line, col)
        if st:
            p.text(x1, y + BIG - 18, "шаг %d из %d" % (st["n"] + 1, len(d["steps"])), c["dim"], align="r")
        # шаги: время звонка; подтверждён — акцент, проспан — красный, текущий — обычный
        x = x0
        steps = d["steps"]
        if len(steps) > 6 and st:          # Сторож: два десятка шагов — показать соседние
            i0 = max(0, min(st["n"] - 2, len(steps) - 6))
            steps = steps[i0:i0 + 6]
        for s_ in steps:
            col = {"ok": c["acc_l"], "fail": c["err"]}.get(s_["state"], c["faint"])
            if st is s_ or (st and s_["n"] == st["n"]):
                col = c["text"]
            mark = {"ok": "+", "fail": "x"}.get(s_["state"], "")
            x += p.text(x, y + BIG + 28, s_["hm"][:5] + mark, col) + 14
        kind = st.get("kind") if st else None
        p.text(x1, y + BIG + 28, "Сторож" if d.get("watch") else "контрольная" if kind == "ctrl"
               else "подряд %d из %d" % (d.get("streak", 0), wa.NEED), c["dim"], align="r")

    def track_range(self):
        mins = [hm_min(self.m.time_of(i)) for i in range(DAYS + 1)]
        mins += [hm_min(w) for w in (self.m.woke(i) for i in range(PAST + 1)) if w]
        lo = min(6 * 60, (min(mins) // 60) * 60)
        hi = max(12 * 60, -(-max(mins) // 60) * 60)
        return lo, hi

    def track_x(self, x0, x1, minutes):
        lo, hi = self.track_range()
        return x0 + (x1 - x0) * (minutes - lo) / (hi - lo)

    @staticmethod
    def track_bounds(x0, x1):
        return x0 + 146, x1 - 14

    def draw_week(self, p, x0, x1, y):
        c = self.c
        tx0, tx1 = self.track_bounds(x0, x1)
        lo, hi = self.track_range()
        for hh in range(lo // 60, hi // 60 + 1):
            if (hh - lo // 60) % (1 if hi - lo <= 8 * 60 else 2) == 0:
                p.text(self.track_x(tx0, tx1, hh * 60), y, str(hh), c["faint"], align="c")
        # легенда меток дорожки (07.10.2026: «а что значит этот квадратик?»)
        lx = x0 + 12
        p.rect(lx, y + 5, 5, 5, c["acc"])
        lx += 9 + p.text(lx + 9, y, "план", c["faint"])
        p.box(lx + 8, y + 3, 9, 9, c["acc_l"])
        p.text(lx + 21, y, "встал", c["faint"])
        y += 18
        pts = []
        for i in range(DAYS):
            if not self.m.skipped(i) and not (Model.gone(i) and not self.m.own(i)):
                pts.append((self.track_x(tx0, tx1, hm_min(self.m.time_of(i))), y + i * ROW_H + ROW_H / 2))
        if len(pts) > 1:
            p.rgb(c["acc_d"], 0.8)
            p.cr.set_line_width(1)
            p.cr.move_to(*pts[0])
            for pt in pts[1:]:
                p.cr.line_to(*pt)
            p.cr.stroke()
        for i in range(DAYS):
            self.draw_day(p, x0 + 2, x1 - 2, y + i * ROW_H, i)

    def draw_day(self, p, x0, x1, y, i):
        c, m = self.c, self.m
        sel = i == self.sel["alarm"] and self.mode != "help"
        self.row_bg(p, x0, x1, y, sel, ("a.row", i))
        ty = y + (ROW_H - 16) / 2 + 1
        skip, past = m.skipped(i), m.past(i)
        woke = m.woke(i)
        if i == DAYS:
            name, ncol = "обычно", c["dim"]
        else:
            d = m.day(i)
            name = "%s %02d" % (DOW[d.weekday()], d.day)
            ncol = c["acc_l"] if sel or i == PAST else (c["faint"] if past else c["text"])
        p.text(x0 + 12, ty, name, ncol)
        if i == PAST:                                    # сегодня — точка у даты
            p.rect(x0 + 6, y + ROW_H // 2 - 1, 3, 3, c["acc"])
        tx = x0 + 80
        if sel and self.mode == "insert":
            p.rect(tx - 3, y + 3, 46, ROW_H - 6, c["field_l"])
            w = p.text(tx, ty, self.buf, c["acc_l"])
            if int(time.monotonic() * 2) % 2 == 0:
                p.rect(tx + w, y + 5, 6, ROW_H - 10, c["acc_l"])
            hm = parse_time(self.buf)
            if hm:
                p.text(tx + 52, ty, "→ " + hm, c["dim"])
        elif m.gone(i):
            # прошедший день: когда встал на деле (вовремя — акцент, позже — приглушённо)
            if woke:
                p.text(tx, ty, woke, c["acc_l"] if m.on_time(i) else c["dim"])
            else:
                p.text(tx, ty, "--:--", c["faint"])
        elif skip:
            p.text(tx, ty, "--:--", c["faint"])
        else:
            col = c["acc_l"] if (m.own(i) or i == DAYS) and not past else (
                c["faint"] if past else c["text"])
            p.text(tx, ty, m.time_of(i), col)
        tx0, tx1 = self.track_bounds(x0, x1)
        cy = y + ROW_H // 2
        p.rect(tx0, cy, tx1 - tx0, 1, c["line_soft"])
        lo, hi = self.track_range()
        for hh in range(lo // 60, hi // 60 + 1):
            p.rect(round(self.track_x(tx0, tx1, hh * 60)), cy - 1, 1, 3, c["line"])
        if skip:
            p.text(tx1, ty, "пропуск", c["faint"], align="r")
            return
        px_ = round(self.track_x(tx0, tx1, hm_min(m.time_of(i))))
        if m.gone(i) and not m.own(i):
            pass                                         # плана тогда не было
        elif past:
            p.rect(px_ - 2, cy - 2, 5, 5, c["faint"])
        else:
            p.rect(px_ - 3, cy - 3, 7, 7, c["bg"])
            p.rect(px_ - 2, cy - 2, 5, 5, c["acc_l"] if sel else c["acc"])
        if woke:
            # факт подъёма — квадратик-рамка: рядом с планом видно опоздание
            fx = round(self.track_x(tx0, tx1, hm_min(woke)))
            ok = m.on_time(i)
            col = c["acc_l"] if ok else (c["dim"] if ok is None else c["err"])
            p.rect(fx - 4, cy - 4, 9, 9, c["bg"])
            p.box(fx - 4, cy - 4, 9, 9, col)

    # ── Focus ──
    # строки: 0 — длительности, 1 — авто с помидором, 2 — перерывы свободны,
    # 3.. — ряды сетки правил (по FOCUS_COLS в ряду)
    FOCUS_COLS = 3

    def focus_grid_rows(self):
        n = len(self.focus_s["blocks"])
        return max(1, -(-n // self.FOCUS_COLS))

    def focus_rows(self):
        return 3 + self.focus_grid_rows()

    def draw_focus(self, p, x0, x1, L):
        c, s = self.c, self.focus_s
        y = L["hero"]
        now = time.time()
        reason = fm.effective(s)
        blocks_today, mins_today = fm.today_stats()
        st = pomo_state()
        if s["active"] and s["until"]:
            p.digits(x0, y, mmss(s["until"] - now), c["acc_l"])
            line1 = "фокус до " + time.strftime("%H:%M", time.localtime(s["until"]))
        elif s["active"]:
            p.digits(x0, y, mmss(now - s["started"]), c["acc_l"])
            line1 = "фокус до отмены · идёт"
        elif reason == "pomo":
            p.digits(x0, y, mmss(st["left"]), c["acc_l"])
            line1 = "фокус на время помидора"
        else:
            p.digits(x0, y, "--:--", c["faint"])
            line1 = "фокус выключен"
        if s["active"] and not reason:
            line1 = "перерыв помидора — можно отдохнуть"
        p.text(x0, y + BIG + 8, line1, c["text"])
        p.text(x1, y + BIG + 8, "отвлечений: %d" % blocks_today,
               c["acc"] if blocks_today else c["dim"], align="r")
        on = [b["label"] for b in s["blocks"] if b.get("on")]
        p.text(x0, y + BIG + 8 + 20, "сегодня в фокусе %s" % dur(mins_today), c["dim"])
        _ = on
        # группа «Сессия»
        gy = L["body"]
        gh = 8 + 3 * ROW_H + 8
        self.group(p, x0, gy, x1 - x0, gh, "Сессия")
        ry = gy + 8
        sel = self.sel["focus"]
        self.row_bg(p, x0 + 1, x1 - 1, ry, sel == 0 and self.mode != "help", ("f.row", 0))
        x = x0 + 12
        cur = None
        if s["active"]:
            cur = s["until"] - s["started"] if s["until"] else 0
        for k, (lab, secs) in enumerate(FOCUS_DURS):
            x += self.chip(p, x, ry, lab, cur == secs, sel == 0 and self.col["focus"] == k,
                           ("f.dur", k)) + 6
        half = (x1 - x0 - 2) / 2
        lock = fm.locked(s)
        for idx, (key, label) in enumerate(FOCUS_OPTS):
            r, col = divmod(idx, 2)
            yy = ry + (r + 1) * ROW_H
            cx = x0 + 1 + col * half
            is_sel = sel == r + 1 and self.col["focus"] == col and self.mode != "help"
            if is_sel:
                p.rect(cx, yy, half, ROW_H, c["sel"])
                p.rect(cx, yy, 2, ROW_H, c["acc"])
            elif self.hover == ("f.opt", idx):
                p.rect(cx, yy, half, ROW_H, c["sel"], 0.5)
            self.hits.append(((cx, yy, half, ROW_H), ("f.opt", idx)))
            self.checkbox(p, cx + 11, yy + (ROW_H - 8) // 2, s.get(key))
            tcol = c["acc_l"] if is_sel else (c["text"] if s.get(key) else c["dim"])
            if key == "strict" and lock:
                label = "строгий до " + (time.strftime("%H:%M", time.localtime(s["until"]))
                                         if s["until"] else "∞")
                tcol = c["acc_l"]
            p.text(cx + 27, yy + (ROW_H - 16) // 2 + 1, label, tcol, maxw=half - 32)
        # группа «Блокируется»
        by = gy + gh + 14
        rows = self.focus_grid_rows()
        bh = L["buttons"] - 14 - by
        n_on = sum(1 for b in s["blocks"] if b.get("on"))
        self.group(p, x0, by, x1 - x0, bh, "Блокируется", "%d из %d" % (n_on, len(s["blocks"])))
        cw_ = (x1 - x0 - 16) / self.FOCUS_COLS
        visible = max(1, (bh - 16) // ROW_H)
        top = max(0, min(sel - 3 - visible + 1, rows - visible)) if sel >= 3 else 0
        top = max(0, top)
        for i, b in enumerate(s["blocks"]):
            r, col = divmod(i, self.FOCUS_COLS)
            if not (top <= r < top + visible):
                continue
            cx = x0 + 8 + col * cw_
            cy = by + 8 + (r - top) * ROW_H
            is_sel = sel == 3 + r and self.col["focus"] == col and self.mode != "help"
            if is_sel:
                p.rect(cx, cy, cw_ - 4, ROW_H, c["sel"])
                p.rect(cx, cy, 2, ROW_H, c["acc"])
            elif self.hover == ("f.rule", i):
                p.rect(cx, cy, cw_ - 4, ROW_H, c["sel"], 0.5)
            self.hits.append(((cx, cy, cw_ - 4, ROW_H), ("f.rule", i)))
            self.checkbox(p, cx + 8, cy + (ROW_H - 8) // 2, b.get("on"))
            col_t = c["acc_l"] if is_sel else (c["text"] if b.get("on") else c["dim"])
            p.text(cx + 22, cy + (ROW_H - 16) // 2 + 1, b["label"], col_t, maxw=cw_ - 30)
        if rows > visible:
            p.text(x1 - 10, by + bh - 20, "↓" if top + visible < rows else "↑", c["faint"], align="r")
        if s["active"]:
            self.buttons(p, x0, x1, L["buttons"], [("+15 мин", "f.more"), ("Завершить", "f.end")])
        else:
            self.buttons(p, x0, x1, L["buttons"], [("Старт", "f.start", True),
                                                   ("Старт + помидор", "f.start_pomo")])

    # ── Pomo ──
    # строки: 0 — длительности, 1.. — недавние задачи
    def pomo_items(self):
        return []          # 07.10.2026: блок «Старт» убран — строк выбора нет

    def pomo_rows(self):
        return 1 + len(self.pomo_items())

    def draw_pomo(self, p, x0, x1, L):
        if self.pomo_view == "stats":
            if self.stats_detail:
                return self.draw_pomo_stats(p, x0, x1, L)
            return self.draw_pomo_today(p, x0, x1, L)
        c = self.c
        st = pomo_state()
        y = L["hero"]
        rounds = pomo_rounds()
        if st["phase"] == "idle":
            p.digits(x0, y, "--:--", c["faint"])
            line1 = "не запущен"
            if st["next"]:
                line1 += " · дальше " + {"work": "работа", "short": "перерыв",
                                         "long": "длинный перерыв"}.get(st["next"], st["next"])
        else:
            p.digits(x0, y, mmss(st["left"]), c["acc_l"] if not st["paused"] else c["dim"])
            name = {"work": "работа", "short": "перерыв", "long": "длинный перерыв"}.get(st["phase"], st["phase"])
            if st["phase"] == "work" and not st["custom"]:
                name += " · %d из %d" % (st["round"] % rounds + 1, rounds)
            if st["paused"]:
                name += " · пауза"
            line1 = name
            p.text(x1, y + BIG + 8, "до " + time.strftime("%H:%M", time.localtime(st["end"])),
                   c["dim"], align="r")
        # кнопка «Статистика» — справа сверху, щелчком (07.10.2026, пользователь: не только клавишей s)
        lab = "Статистика"
        bw = p.text_w(lab) + 20
        p.rect(x1 - bw, y + 2, bw, 22, c["field_l"])
        p.box(x1 - bw, y + 2, bw, 22, c["line"])
        p.text(x1 - bw + 10, y + 5, lab, c["acc_l"])
        self.hits.append(((x1 - bw, y, bw, 26), "p.stats"))
        p.text(x0, y + BIG + 8, line1, c["text"])
        task = st["task"] or "без задачи"
        p.text(x0, y + BIG + 8 + 20, task, c["dim"], maxw=x1 - x0 - 120)
        # полоса прогресса
        if st["phase"] != "idle" and st["duration"]:
            frac = 1 - st["left"] / st["duration"]
            bx, bw = x1 - 110, 110
            by = y + BIG + 8 + 26
            p.rect(bx, by, bw, 4, c["field_l"])
            p.rect(bx, by, round(bw * frac), 4, c["acc"])
        # «Неделя» — столбики минут работы
        gy = L["body"]
        week = pomo_week()
        today_m, today_n = week[-1][1], week[-1][2]
        gh = 8 + 16 + 64 + 18 + 8
        self.group(p, x0, gy, x1 - x0, gh, "Неделя",
                   "сегодня %s · %d шт." % (dur(today_m), today_n))
        self.hits.append(((x0, gy, x1 - x0, gh), "p.stats"))   # щелчок — статистика
        top = max(60, max(m for _d, m, _n in week))
        cw_ = (x1 - x0 - 24) / 7
        base = gy + 8 + 16 + 64
        for k, (d, mins, _n) in enumerate(week):
            cx = x0 + 12 + k * cw_
            bw = min(26, cw_ - 10)
            bx = round(cx + (cw_ - bw) / 2)
            hgt = round(64 * mins / top)
            is_today = k == 6
            p.rect(bx, base - 64, bw, 64, c["field"])
            if hgt:
                p.rect(bx, base - hgt, bw, hgt, c["acc"] if is_today else c["acc_d"])
            if mins:
                p.text(cx + cw_ / 2, base - hgt - 16, "%d" % mins if mins < 60 else "%dч" % (mins // 60)
                       if mins % 60 == 0 else "%d:%02d" % (mins // 60, mins % 60),
                       c["text"] if is_today else c["dim"], align="c")
            p.text(cx + cw_ / 2, base + 4, DOW[d.weekday()], c["acc_l"] if is_today else c["faint"],
                   align="c")
        # «Сегодня» вместо «Старт» (07.10.2026, Просьба: «старт не нужен — покажи, сколько
        # помидоров за сегодня, одинаковые названия суммируй»). Запуск — Space / SUPER+T.
        sy = gy + gh + 14
        sh = L["buttons"] - 14 - sy
        work = [e for e in pomo_entries(1)[dt.date.today()] if e["phase"] == "work"]
        rest = [e for e in pomo_entries(1)[dt.date.today()] if e["phase"] != "work"]
        tasks = {}
        for e in work:
            k = task_key(e["task"])
            t, cnt = tasks.get(k, (0, 0))
            tasks[k] = (t + e["spent"], cnt + 1)
        total = sum(e["spent"] for e in work) // 60
        self.group(p, x0, sy, x1 - x0, sh, "Сегодня",
                   ("%d шт. · %s" % (len(work), dur(total))) if work else "")
        self.hits.append(((x0, sy, x1 - x0, sh), "p.stats"))   # щелчок — итоги дня
        ry = sy + 8
        lh = ROW_H
        if not work:
            p.text(x0 + 12, ry + (lh - 16) // 2 + 1, "сегодня помидоров ещё не было — Space, чтобы начать",
                   c["faint"], maxw=x1 - x0 - 24)
        rows = sorted(tasks.items(), key=lambda kv: -kv[1][0])
        if rest:
            rows.append(("перерывы", (sum(e["spent"] for e in rest), -len(rest))))
        fit = max(1, (sy + sh - 6 - ry) // lh)
        for i, (name, (t, cnt)) in enumerate(rows[:fit]):
            ty = ry + i * lh + (lh - 16) // 2 + 1
            is_rest = cnt < 0
            p.text(x0 + 12, ty, name, c["dim"] if is_rest else c["text"], maxw=x1 - x0 - 200)
            p.text(x1 - 110, ty, "×%d" % abs(cnt), c["dim"], align="r")
            p.text(x1 - 12, ty, dur(t // 60), c["dim"] if is_rest else c["acc_l"], align="r")
        if st["phase"] == "idle":
            first = ("Старт", "p.toggle", True)
        else:
            first = ("Продолжить" if st["paused"] else "Пауза", "p.toggle", True)
        self.buttons(p, x0, x1, L["buttons"], [first, ("Пропустить", "p.skip"), ("Стоп", "p.stop")])

    STATUS = {"done": "готово", "skipped": "пропущен", "aborted": "прерван"}
    PHASE = {"work": "работа", "short": "перерыв", "long": "длинный"}

    def draw_pomo_today(self, p, x0, x1, L):
        """Кратко за день (07.10.2026, Просьба: «вкладка непонятная, 14 дней не надо, базово —
        минимально: сколько помидоров за сегодня, список, внизу общее время на задачи и
        перерывы; подробное — отдельной кнопкой»). Только работа; перерывы — в итоге."""
        c = self.c
        ent = pomo_entries(14)
        days = sorted(ent)
        d = days[max(0, min(len(days) - 1, self.stats_day))]
        allrows = ent[d]
        work = [e for e in allrows if e["phase"] == "work"]
        rest = [e for e in allrows if e["phase"] != "work"]
        self.stats_rows = work
        done = sum(1 for e in work if e["status"] == "done")
        focus = sum(e["spent"] for e in work) // 60
        today = dt.date.today()
        when = ("сегодня" if d == today else "вчера" if d == today - dt.timedelta(days=1)
                else "%s %d %s" % (DOW[d.weekday()], d.day, MONTHS[d.month - 1]))
        y = L["hero"]
        w = p.digits(x0, y, str(len(work)), c["acc_l"] if work else c["faint"])
        p.text(x0 + w + 14, y + 8, "помидоров", c["text"])
        p.text(x0 + w + 14, y + 26, when, c["dim"])
        p.text(x1, y + 8, dur(focus), c["text"] if focus else c["faint"], align="r")
        p.text(x1, y + 26, "на задачи", c["dim"], align="r")
        if work:
            p.text(x0, y + BIG + 8, "доведено до конца %d из %d" % (done, len(work)), c["dim"])
        # итог — внизу, постоянной высоты
        lh = ROW_H
        tasks = {}
        for e in work:
            k = e["task"] or "без задачи"
            t, cnt = tasks.get(k, (0, 0))
            tasks[k] = (t + e["spent"], cnt + 1)
        top = sorted(tasks.items(), key=lambda kv: -kv[1][0])
        sum_rows = 2 + min(3, len(top))
        sh = 8 + sum_rows * lh + 6
        sy = L["buttons"] - 14 - sh
        self.group(p, x0, sy, x1 - x0, sh, "Итог")
        ry = sy + 8
        rest_min = sum(e["spent"] for e in rest) // 60
        lines = [("Время на задачи", dur(focus), c["acc_l"] if focus else c["faint"]),
                 ("Перерывов", "%d · %s" % (len(rest), dur(rest_min)) if rest else "0",
                  c["text"] if rest else c["faint"])]
        for k, (t, cnt) in top[:3]:
            lines.append(("  " + k, "%s · ×%d" % (dur(t // 60), cnt), c["dim"]))
        for lab, val, col in lines:
            ty = ry + (lh - 16) // 2 + 1
            vw = p.text_w(val)
            p.text(x0 + 12, ty, lab, c["text"] if not lab.startswith("  ") else c["dim"],
                   maxw=x1 - x0 - 40 - vw)
            p.text(x1 - 12, ty, val, col, align="r")
            ry += lh
        # список помидоров дня
        gy = L["body"]
        gh = sy - 14 - gy
        self.group(p, x0, gy, x1 - x0, gh, "Помидоры", "h l — день" if work or d != today else "")
        ry = gy + 8
        if not work:
            p.text(x0 + 12, ry + (lh - 16) // 2 + 1,
                   "пока ни одного — Space на таймере, чтобы начать" if d == today
                   else "в этот день помидоров не было", c["faint"])
        fit = max(1, (gy + gh - 6 - ry) // lh)
        if self.stats_sel >= len(work):
            self.stats_sel = len(work) - 1
        if self.stats_sel >= 0:
            if self.stats_sel < self.stats_scroll:
                self.stats_scroll = self.stats_sel
            elif self.stats_sel >= self.stats_scroll + fit:
                self.stats_scroll = self.stats_sel - fit + 1
        self.stats_scroll = max(0, min(self.stats_scroll, max(0, len(work) - fit)))
        for i, e in enumerate(work[self.stats_scroll:self.stats_scroll + fit]):
            k = self.stats_scroll + i
            yy = ry + i * lh
            ty = yy + (lh - 16) // 2 + 1
            on = k == self.stats_sel and self.mode != "help"
            self.row_bg(p, x0 + 1, x1 - 1, yy, on, ("p.seg", k), lh)
            span = "%s–%s" % (time.strftime("%H:%M", time.localtime(e["start"])),
                              time.strftime("%H:%M", time.localtime(e["end"])))
            p.text(x0 + 12, ty, span, c["acc_l"] if on else c["text"])
            p.text(x0 + 120, ty, dur(round(e["spent"] / 60)), c["text"])
            mark = {"done": "✓", "aborted": "прерван", "skipped": "пропущен"}.get(e["status"], e["status"])
            p.text(x0 + 196, ty, mark, c["acc_l"] if e["status"] == "done" else
                   (c["err"] if e["status"] == "aborted" else c["faint"]))
            p.text(x0 + 276, ty, e["task"] or "без задачи", c["dim"] if e["task"] else c["faint"],
                   maxw=x1 - x0 - 288)
        if len(work) > fit:
            more = len(work) - fit - self.stats_scroll
            lab = ("↓ ещё %d" % more) if more > 0 else ("↑ %d выше" % self.stats_scroll)
            p.text(x1 - 12, gy + gh - 18, lab, c["faint"], align="r")
        btns = [("← Таймер", "p.back", True), ("Подробно", "p.detail")]
        if 0 <= self.stats_sel < len(work):
            btns.append(("Удалить", "p.del"))
        self.buttons(p, x0, x1, L["buttons"], btns)

    def draw_pomo_stats(self, p, x0, x1, L):
        """Статистика помидоров (07.10.2026, Просьба: «сколько в днях помидорок и подробно,
        как это проходило»): итоги за 14 дней, столбики по дням, отрезки выбранного дня."""
        c = self.c
        ent = pomo_entries(14)
        days = sorted(ent)
        sm = pomo_summary(ent)
        y = L["hero"]
        w = p.digits(x0, y, str(sm["done"]), c["acc_l"] if sm["done"] else c["faint"])
        p.text(x0 + w + 14, y + 8, "помидоров", c["text"])
        p.text(x0 + w + 14, y + 26, "за 14 дней", c["dim"])
        p.text(x1, y + 8, dur(sm["minutes"]) + " работы", c["text"], align="r")
        p.text(x1, y + 26, "дней с работой: %d" % sm["active"], c["dim"], align="r")
        line = "серия %d дн. · доведено %d %%" % (sm["streak"], sm["rate"])
        p.text(x0, y + BIG + 8, line, c["text"])
        if sm["top"]:
            p.text(x0, y + BIG + 8 + 20, "чаще всего: " + sm["top"], c["dim"], maxw=x1 - x0)
        # 14 дней
        gy = L["body"]
        gh = 8 + 16 + 64 + 18 + 8
        self.group(p, x0, gy, x1 - x0, gh, "14 дней", "h l — день")
        per = []
        for d in days:
            work = [e for e in ent[d] if e["phase"] == "work"]
            per.append((d, sum(e["spent"] for e in work) // 60,
                        sum(1 for e in work if e["status"] == "done")))
        top = max([60] + [m for _d, m, _n in per])
        cw_ = (x1 - x0 - 24) / len(per)
        base = gy + 8 + 16 + 64
        sel = max(0, min(len(per) - 1, self.stats_day))
        for k, (d, mins, n) in enumerate(per):
            cx = x0 + 12 + k * cw_
            bw = max(6, min(18, cw_ - 8))
            bx = round(cx + (cw_ - bw) / 2)
            hgt = round(64 * mins / top)
            on = k == sel
            p.rect(bx, base - 64, bw, 64, c["field"])
            if hgt:
                p.rect(bx, base - hgt, bw, hgt, c["acc"] if on else c["acc_d"])
            if on:
                p.box(bx - 3, base - 67, bw + 6, 70, c["acc_l"])
            if n:
                p.text(cx + cw_ / 2, base - hgt - 16, str(n), c["text"] if on else c["dim"], align="c")
            lab = "%02d" % d.day
            p.text(cx + cw_ / 2, base + 4, lab, c["acc_l"] if on else c["faint"], align="c")
            self.hits.append(((round(cx), gy + 8, round(cw_), gh - 8), ("p.day", k)))
        # выбранный день: итоги как у `pomo log`, по задачам, затем отрезки
        d, mins, n = per[sel]
        rows = ent[d]
        self.stats_rows = rows
        work = [e for e in rows if e["phase"] == "work"]
        focus = sum(e["spent"] for e in work)
        rest = sum(e["spent"] for e in rows if e["phase"] != "work")
        done = sum(1 for e in work if e["status"] == "done")
        sy = gy + gh + 14
        sh = L["buttons"] - 14 - sy
        title = "%s %d %s" % (DOW[d.weekday()], d.day, MONTHS[d.month - 1])
        self.group(p, x0, sy, x1 - x0, sh, title, "отрезков %d · завершено %d" % (len(work), done))
        ry = sy + 8
        lh = ROW_H
        if not rows:
            p.text(x0 + 12, ry + (lh - 16) // 2 + 1, "в этот день помидоров не было", c["faint"])
        else:
            line = "фокус %s" % dur(focus // 60) + ("  ·  перерывы %s" % dur(rest // 60) if rest else "")
            p.text(x0 + 12, ry + (lh - 16) // 2 + 1, line, c["text"])
            ry += lh
            tasks = {}
            for e in work:
                k = e["task"] or "— без задачи —"
                t, cnt = tasks.get(k, (0, 0))
                tasks[k] = (t + e["spent"], cnt + 1)
            for k, (t, cnt) in sorted(tasks.items(), key=lambda kv: -kv[1][0])[:3]:
                ty = ry + (lh - 16) // 2 + 1
                p.text(x0 + 12, ty, dur(t // 60), c["acc_l"])
                p.text(x0 + 120, ty, "×%d" % cnt, c["dim"])
                p.text(x0 + 160, ty, k, c["text"], maxw=x1 - x0 - 170)
                ry += lh
            p.rect(x0 + 10, ry + 3, x1 - x0 - 20, 1, c["line_soft"])
            sep_y = ry + 3
            ry += 8
        fit = max(1, (sy + sh - 6 - ry) // lh)
        if self.stats_sel >= len(rows):
            self.stats_sel = len(rows) - 1
        if self.stats_sel >= 0:
            if self.stats_sel < self.stats_scroll:
                self.stats_scroll = self.stats_sel
            elif self.stats_sel >= self.stats_scroll + fit:
                self.stats_scroll = self.stats_sel - fit + 1
        self.stats_scroll = max(0, min(self.stats_scroll, max(0, len(rows) - fit)))
        for i, e in enumerate(rows[self.stats_scroll:self.stats_scroll + fit]):
            k = self.stats_scroll + i
            yy = ry + i * lh
            ty = yy + (lh - 16) // 2 + 1
            self.row_bg(p, x0 + 1, x1 - 1, yy, k == self.stats_sel and self.mode != "help", ("p.seg", k), lh)
            wrk = e["phase"] == "work"
            col = c["text"] if wrk else c["dim"]
            long_pause = e["end"] - e["start"] > max(3 * e["plan"], e["spent"] + 3600)
            t0 = "…" if long_pause else time.strftime("%H:%M", time.localtime(e["start"]))
            span = "%s–%s" % (t0, time.strftime("%H:%M", time.localtime(e["end"])))
            p.text(x0 + 12, ty, span, col)
            p.text(x0 + 120, ty, self.PHASE.get(e["phase"], e["phase"]), col)
            mins_ = "<1" if e["spent"] < 60 else str(round(e["spent"] / 60))
            p.text(x0 + 192, ty, "%s/%d" % (mins_, round(e["plan"] / 60)), col)
            st_col = c["acc_l"] if e["status"] == "done" else (c["err"] if e["status"] == "aborted" else c["faint"])
            p.text(x0 + 246, ty, self.STATUS.get(e["status"], e["status"]), st_col if wrk else c["faint"])
            if e["task"]:
                p.text(x0 + 328, ty, e["task"], c["dim"], maxw=x1 - x0 - 334)
        if rows and len(rows) > fit:
            # сколько отрезков ещё ниже/выше — на разделительной линии, не поверх строк
            more = len(rows) - fit - self.stats_scroll
            lab = ("↓ ещё %d" % more) if more > 0 else ("↑ %d выше" % self.stats_scroll)
            lw = p.text_w(lab)
            p.rect(x1 - 18 - lw, sep_y - 2, lw + 8, 5, c["bg"] if c["frame"] == "skeet" else c["field"])
            p.text(x1 - 14, sep_y - 8, lab, c["faint"], align="r")
        btns = [("← Кратко", "p.detail", True), ("Сегодня", "p.today")]
        if 0 <= self.stats_sel < len(rows):
            btns.append(("Удалить", "p.del"))
        self.buttons(p, x0, x1, L["buttons"], btns)



# ── окно ──────────────────────────────────────────────────────────────────────

class RoutineWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="alarm"):
        super().__init__(application=app, title="Discipline")
        self.model = Model()
        self.view = View(self.model)
        self.model.on_refuse = lambda: self.view.flash(
            "идёт утренняя проверка — до её конца день звонка не меняется, сэр")
        self.view.tab = tab if tab in TABS else "alarm"
        self.pending = ""
        self.pending_t = 0
        self.last_j = 0
        self.yank = None
        self.confirm_action = None
        self.set_decorated(False)
        # Растягивается (07.10.2026): niri — Super+перетаскивание, само окно — края и
        # уголок справа внизу, как у виджетов. Меньше раскладки не сжимается; размер
        # запоминается в state/discipline-size.
        self.set_resizable(True)
        self.set_size_request(W, self.view.height())
        sw, sh = W, self.view.height()
        try:
            a, b = open(SIZE_FILE).read().split()[:2]
            sw, sh = max(W, int(a)), max(sh, int(b))
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
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", lambda *_: self.set_hover(None))
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("notify::is-active", self.on_active)
        GLib.timeout_add(500, self.tick)

    def on_configure(self, _w, ev):
        size = (ev.width, ev.height)
        if size != self.last_size:
            self.last_size = size
            if getattr(self, "size_save", None):
                GLib.source_remove(self.size_save)
            self.size_save = GLib.timeout_add(600, self.save_size)
        return False

    def save_size(self):
        self.size_save = None
        try:
            with open(SIZE_FILE, "w") as f:
                f.write("%d %d\n" % self.last_size)
        except OSError:
            pass
        return False

    EDGES = {"nw": Gdk.WindowEdge.NORTH_WEST, "n": Gdk.WindowEdge.NORTH,
             "ne": Gdk.WindowEdge.NORTH_EAST, "e": Gdk.WindowEdge.EAST,
             "se": Gdk.WindowEdge.SOUTH_EAST, "s": Gdk.WindowEdge.SOUTH,
             "sw": Gdk.WindowEdge.SOUTH_WEST, "w": Gdk.WindowEdge.WEST}

    def edge_at(self, x, y):
        """Край окна под курсором: рамка (6 px) и уголок 18×18 справа внизу."""
        a = self.area.get_allocation()
        w, h, m = a.width, a.height, 6
        if x >= w - 18 and y >= h - 18:
            return "se"
        v = "n" if y < m else "s" if y >= h - m else ""
        hz = "w" if x < m else "e" if x >= w - m else ""
        return (v + hz) or None

    def set_cursor(self, name):
        if name == self.cursor_name:
            return
        self.cursor_name = name
        gw = self.area.get_window()
        if gw is not None:
            gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), name) if name else None)

    def on_active(self, *_a):
        self.view.active = self.is_active()
        self.redraw()

    def redraw(self):
        self.area.queue_draw()

    def tick(self):
        r = self.model.reload_if_changed()
        if r == "kept":
            self.view.flash("файл изменён снаружи — «Сохранить» перезапишет его")
        elif r:
            self.view.flash("расписание изменено снаружи")
        if style_name() != self.view.style:
            self.view.reload_style()
            self.set_size_request(W, self.view.height())
        self.redraw()
        return True

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.view.draw(cr, a.width, a.height)

    # ── мышь ──
    def hit(self, x, y):
        for (hx, hy, hw, hh), key in reversed(self.view.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return key
        return None

    def set_hover(self, key):
        if key != self.view.hover:
            self.view.hover = key
            self.redraw()

    def on_motion(self, _w, ev):
        edge = self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else None)
        self.set_hover(None if edge else self.hit(ev.x, ev.y))

    def on_click(self, _w, ev):
        v = self.view
        if v.mode == "help":
            v.mode = "normal"
            self.redraw()
            return True
        if v.mode == "confirm" and ev.button == 1:
            # вопрос внизу: «Да» — выполнить, всё прочее — отмена
            key = self.hit(ev.x, ev.y)
            if key == "c.yes" and self.confirm_action:
                self.confirm_action()
            v.mode = "normal"
            v.doubt = None
            self.confirm_action = None
            self.redraw()
            if key in ("c.yes", "c.no"):
                return True
        edge = self.edge_at(ev.x, ev.y)
        if edge and ev.button == 1:
            self.begin_resize_drag(self.EDGES[edge], ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        key = self.hit(ev.x, ev.y)
        if key is None:
            if ev.button == 1:
                self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        dbl = ev.type == Gdk.EventType._2BUTTON_PRESS
        if isinstance(key, tuple):
            kind, val = key
            self.finish_insert()
            if kind == "tab":
                self.set_tab(val)
            elif kind == "a.row":
                v.sel["alarm"] = val
                if dbl:
                    self.start_insert()
            elif kind == "f.row":
                v.sel["focus"] = val
                if val in (1, 2):
                    self.focus_toggle_rule()
            elif kind == "f.opt":
                v.sel["focus"], v.col["focus"] = 1 + val // 2, val % 2
                self.focus_toggle_rule()
            elif kind == "f.dur":
                v.sel["focus"], v.col["focus"] = 0, val
                if dbl:
                    self.focus_start()
            elif kind == "f.rule":
                r, cidx = divmod(val, View.FOCUS_COLS)
                v.sel["focus"], v.col["focus"] = 3 + r, cidx
                self.focus_toggle_rule()
            elif kind == "p.day":
                v.stats_day, v.stats_scroll, v.stats_sel = val, 0, -1
            elif kind == "p.seg":
                v.stats_sel = val
            elif kind == "p.row":
                v.sel["pomo"] = val
                if dbl and val:
                    self.pomo_start_selected()
            elif kind == "p.dur":
                v.sel["pomo"], v.col["pomo"] = 0, val
                if dbl:
                    self.pomo_start_selected()
        else:
            self.action(key)
        self.redraw()
        return True

    def on_scroll(self, _w, ev):
        key = self.hit(ev.x, ev.y)
        if not (isinstance(key, tuple) and key[0] == "a.row"):
            return False
        dy = 0
        if ev.direction == Gdk.ScrollDirection.UP:
            dy = -1
        elif ev.direction == Gdk.ScrollDirection.DOWN:
            dy = 1
        elif ev.direction == Gdk.ScrollDirection.SMOOTH:
            dy = 1 if ev.delta_y > 0 else -1 if ev.delta_y < 0 else 0
        if dy and not Model.gone(key[1]):
            self.view.sel["alarm"] = key[1]
            self.model.shift(key[1], -STEP * dy)
            self.redraw()
        return True

    # ── вкладки ──
    def set_tab(self, t):
        v = self.view
        if t in TABS and t != v.tab:
            self.finish_insert()
            v.tab = t
            v.mode = "normal" if v.mode not in ("help",) else "help"

    def cycle_tab(self, d):
        i = TABS.index(self.view.tab)
        self.set_tab(TABS[(i + d) % len(TABS)])

    def try_close(self):
        """Есть несохранённое — первое нажатие предупреждает, второе (за 3 с) закрывает
        без сохранения: при следующем запуске будет то, что в файле."""
        if self.model.dirty() and time.monotonic() - getattr(self, "close_warn", 0) > 3:
            self.close_warn = time.monotonic()
            self.view.flash("не сохранено — Ctrl+S сохранить, ещё раз q — выйти без сохранения", 3)
            return
        self.close()

    # ── действия ──
    def action(self, key):
        v, m = self.view, self.model
        sel = v.sel["alarm"]
        if key == "close":
            self.try_close()
        elif key == "a.save":
            m.save()
            v.flash("сохранено")
        elif key == "a.revert":
            if m.revert():
                v.flash("вернул как было — u, если передумали")
        elif key == "a.enabled":
            if m.toggle_enabled():
                v.flash("будильник " + ("включён" if m.s["enabled"] else "выключен"))
        elif key in ("a.test", "a.stop") and live_series() and not live_series().get("test"):
            m.on_refuse()
        elif key == "a.test":
            run_bg(sys.executable, os.path.join(HERE, "wake_alarm.py"), "test", "10")
            v.flash("пробный звонок, 10 с")
        elif key == "a.stop":
            run_out(sys.executable, os.path.join(HERE, "wake_alarm.py"), "stop")
            v.flash("остановлен")
        elif key == "a.watch":
            self.watch_today_toggle()
        elif key == "a.skip":
            if m.toggle_skip(sel):
                v.flash("без звонка" if m.skipped(sel) else "звонок вернулся")
        elif key == "a.reset":
            if m.reset(sel):
                v.flash("как по умолчанию — " + m.s["default"])
        elif key == "f.start":
            self.focus_start()
        elif key == "f.start_pomo":
            self.focus_start(with_pomo=True)
        elif key == "f.more":
            fm.extend(15 * 60)
            v.flash("+15 минут")
        elif key == "f.end":
            self.ask_end_focus()
        elif key == "p.stats":
            v.pomo_view, v.stats_day, v.stats_scroll, v.stats_sel = "stats", 13, 0, -1
            v.stats_detail = False
        elif key == "p.detail":
            v.stats_detail = not v.stats_detail
            v.stats_scroll, v.stats_sel = 0, -1
        elif key == "p.del":
            self.ask_delete_segment()
        elif key == "p.back":
            v.pomo_view = "start"
        elif key == "p.today":
            v.stats_day, v.stats_scroll, v.stats_sel = 13, 0, -1
        elif key == "p.toggle":
            out = run_out(POMO, "toggle")
            v.flash(out.splitlines()[0] if out else "pomo")
        elif key == "p.skip":
            out = run_out(POMO, "skip")
            v.flash(out.splitlines()[0] if out else "пропущено")
        elif key == "p.stop":
            out = run_out(POMO, "stop")
            v.flash(out.splitlines()[0] if out else "остановлен")

    # Focus
    def focus_start(self, with_pomo=False):
        v = self.view
        lab, secs = FOCUS_DURS[v.col["focus"]] if v.sel["focus"] == 0 else FOCUS_DURS[0]
        s = fm.load()
        if fm.locked(s) and s["until"] and secs and time.time() + secs < s["until"]:
            v.flash("строгий режим — сократить нельзя, только продлить")
            return
        fm.start(secs)
        if with_pomo and pomo_state()["phase"] == "idle":
            run_out(POMO, "%dm" % (secs // 60) if secs else "start")
        v.flash("фокус: " + ("до отмены" if not secs else lab) + (" + помидор" if with_pomo else ""))

    def ask_delete_segment(self):
        """Удалить выбранный отрезок помидора (создан по ошибке) — после y."""
        v = self.view
        if not (0 <= v.stats_sel < len(v.stats_rows)):
            return
        e = v.stats_rows[v.stats_sel]
        what = "%s %s, %s" % (self.view.PHASE.get(e["phase"], e["phase"]),
                              time.strftime("%H:%M", time.localtime(e["start"])), e["task"] or "без задачи")
        v.confirm_text = "Удалить: %s?" % what
        v.mode = "confirm"

        def go():
            if pomo_delete(e):
                v.stats_undo.append(e)
                v.flash("удалено — u, чтобы вернуть")
            else:
                v.flash("не нашёл строку в журнале")
        self.confirm_action = go

    def watch_today_toggle(self):
        v = self.view
        ws = watch_today()
        if ws is None:
            v.flash("Сторож выключен в Настройках → Config")
            return
        cmd = [sys.executable, os.path.join(HERE, "wake_alarm.py"), "watch", "skip"]
        if ws == "skip":
            run_out(*cmd, "off", "--via", "discipline")
            v.flash("Сторож снова на посту")
            return
        if wa.watch_busy():
            v.flash("идёт проверка Сторожа — сначала ответьте")
            return
        last = getattr(self, "_doubt", None)
        self._doubt = secrets.choice([x for x in WATCH_DOUBTS if x != last])

        def go():
            out = run_out(*cmd, "--reason", "на день, из Discipline", "--via", "discipline")
            v.flash("сегодня без Сторожа" if "без" in out else (out or "не вышло"))
        v.confirm_text = "Выключить Сторожа на сегодня?"
        v.doubt = self._doubt
        v.mode = "confirm"
        self.confirm_action = go

    def ask_end_focus(self):
        s = fm.load()
        if not s["active"]:
            return
        if fm.locked(s):
            self.view.flash("строгий режим — до %s" % (time.strftime(
                "%H:%M", time.localtime(s["until"])) if s["until"] else "отмены (только терминал)"))
            return
        left = s["until"] - time.time() if s["until"] else 0
        self.view.confirm_text = ("Осталось %s. Закончить?" % dur(left / 60)) if left > 60 else "Закончить фокус?"
        self.view.mode = "confirm"
        self.confirm_action = lambda: (fm.stop(), self.view.flash("фокус завершён"))

    def focus_rule_index(self):
        v = self.view
        return (v.sel["focus"] - 3) * View.FOCUS_COLS + v.col["focus"]

    def focus_toggle_rule(self):
        v = self.view
        s = fm.load()
        sel = v.sel["focus"]
        lock = fm.locked(s)
        if sel in (1, 2):
            key = FOCUS_OPTS[(sel - 1) * 2 + min(1, v.col["focus"])][0]
            # строгий режим: ослабить нельзя (снять строгость, перерывы, исключения)
            # снять строгость или включить послабление (перерывы, учёба) — нельзя
            if lock and (key == "strict" or (key in ("free_breaks", "allow_on") and not s.get(key))):
                v.flash("строгий режим — ослабить нельзя до конца сессии")
                return
            s[key] = not s.get(key)
            fm.save(s)
            if key == "auto_pomo" and s[key]:
                fm.ensure_daemon()
            v.flash({"auto_pomo": "фокус на время помидоров", "free_breaks": "перерывы помидора свободны",
                     "strict": "строгий режим", "allow_on": "учебные ролики можно"}[key]
                    + (" — да" if s[key] else " — нет"))
        elif sel >= 3:
            i = self.focus_rule_index()
            if lock and 0 <= i < len(s["blocks"]) and s["blocks"][i].get("on"):
                v.flash("строгий режим — правило не снять до конца сессии")
                return
            if 0 <= i < len(s["blocks"]):
                s["blocks"][i]["on"] = not s["blocks"][i].get("on")
                fm.save(s)
                v.flash("%s — %s" % (s["blocks"][i]["label"],
                                     "блокируется" if s["blocks"][i]["on"] else "можно"))

    def focus_delete_rule(self):
        v = self.view
        if v.sel["focus"] < 3:
            return
        s = fm.load()
        if fm.locked(s):
            v.flash("строгий режим — правило не удалить до конца сессии")
            return
        i = self.focus_rule_index()
        if 0 <= i < len(s["blocks"]):
            b = s["blocks"].pop(i)
            fm.save(s)
            v.flash("правило «%s» удалено" % b["label"])
            self.clamp_focus()

    def clamp_focus(self):
        v = self.view
        v.reload_focus()
        n = len(v.focus_s["blocks"])
        v.sel["focus"] = min(v.sel["focus"], v.focus_rows() - 1)
        if v.sel["focus"] in (1, 2):
            v.col["focus"] = min(v.col["focus"], 1)
        if v.sel["focus"] >= 3:
            r = v.sel["focus"] - 3
            v.col["focus"] = min(v.col["focus"], max(0, n - r * View.FOCUS_COLS - 1))

    # Pomo
    def pomo_start_selected(self):
        v = self.view
        if v.sel["pomo"] == 0:
            args = [POMO_DURS[v.col["pomo"]]]
        else:
            items = v.pomo_items()
            i = v.sel["pomo"] - 1
            if not (0 <= i < len(items)):
                return
            args = items[i].split(" ", 1)
        out = run_out(POMO, *args)
        v.flash(out.splitlines()[0] if out else "pomo " + " ".join(args))

    # ввод
    def start_insert(self):
        self.view.mode = "insert"
        self.view.buf = ""

    def start_text(self, what, init=""):
        self.view.mode = "text"
        self.view.text_for = what
        self.view.buf = init

    def finish_insert(self, apply=True):
        v = self.view
        if v.mode != "insert":
            return
        v.mode = "normal"
        if apply and v.buf:
            hm = parse_time(v.buf)
            i = v.sel["alarm"]
            if hm and Model.gone(i):
                self.model.set_woke(i, hm)
                v.flash("%s — встал в %s" % (self.row_name(i), hm))
            elif hm:
                self.model.set_time(i, hm)
                v.flash("%s — %s" % (self.row_name(i), hm))
            else:
                v.flash("не время: " + v.buf)
        v.buf = ""

    def finish_text(self):
        v = self.view
        txt, what = v.buf.strip(), v.text_for
        v.mode, v.buf, v.text_for = "normal", "", None
        if not txt:
            return
        if what == "rule":
            s = fm.load()
            s["blocks"].append({"label": txt, "match": re.escape(txt.lower()), "on": True})
            fm.save(s)
            v.flash("блокируется: " + txt)
        elif what == "pomo":
            out = run_out(POMO, *txt.split())
            v.flash(out.splitlines()[0] if out else "pomo " + txt)
        elif what == "allow":
            s = fm.load()
            s["allow"] = [w.strip().lower() for w in txt.replace(",", " ").split() if w.strip()]
            fm.save(s)
            v.flash("учёба: %d слов" % len(s["allow"]))
        elif what == "task":
            run_out(POMO, "task", txt)
            v.flash("задача: " + txt)

    def row_name(self, i):
        if i == DAYS:
            return "по умолчанию"
        d = Model.day(i)
        return "%s %02d.%02d" % (DOW[d.weekday()], d.day, d.month)

    def run_command(self, cmd):
        v, m = self.view, self.model
        parts = cmd.strip().split()
        if not parts:
            return
        c0 = parts[0]
        if c0 in ("wq", "x", "wq!"):
            m.save()
            self.close()
        elif c0 == "q!":
            self.close()
        elif c0 == "q":
            if m.dirty():
                v.flash("не сохранено: :w — сохранить, :q! — выйти без сохранения")
            else:
                self.close()
        elif c0 == "w":
            m.save()
            v.flash("сохранено")
        elif c0 in ("e!", "revert"):
            if m.revert():
                v.flash("вернул как было")
        elif c0 in TABS:
            self.set_tab(c0)
        elif c0 in ("on", "off") and v.tab == "alarm":
            if m.s["enabled"] != (c0 == "on"):
                m.toggle_enabled()
            v.flash("будильник " + ("включён" if m.s["enabled"] else "выключен"))
        elif c0 == "on" and v.tab == "focus":
            secs = fm.parse_dur(parts[1]) if len(parts) > 1 else 0
            fm.start(secs or 0)
            v.flash("фокус включён")
        elif c0 == "off" and v.tab == "focus":
            self.ask_end_focus()
        elif c0 == "test" and len(parts) > 1 and parts[1] in ("series", "серия"):
            # :test series [К] — вся серия ускоренно (К секунд на «минуту», по умолчанию 12)
            if live_series():
                v.flash("серия уже идёт")
            else:
                k = parts[2] if len(parts) > 2 and parts[2].isdigit() else "12"
                run_bg(sys.executable, os.path.join(HERE, "wake_alarm.py"), "test-series", k)
                v.flash("тестовая серия: минута = %s с" % k)
        elif c0 == "test":
            sec = parts[1] if len(parts) > 1 and parts[1].isdigit() else "10"
            run_bg(sys.executable, os.path.join(HERE, "wake_alarm.py"), "test", sec)
            v.flash("пробный звонок, %s с" % sec)
        elif c0 in ("default", "def", "d") and len(parts) > 1 and parse_time(parts[1]):
            m.set_time(DAYS, parse_time(parts[1]))
            v.flash("по умолчанию — " + m.s["default"])
        elif c0 == "pomo" and len(parts) > 1:
            out = run_out(POMO, *parts[1:])
            v.flash(out.splitlines()[0] if out else "pomo")
        elif v.tab == "alarm" and parse_time(c0):
            m.set_time(v.sel["alarm"], parse_time(c0))
            v.flash("%s — %s" % (self.row_name(v.sel["alarm"]), m.time_of(v.sel["alarm"])))
        else:
            v.flash("нет такой команды: " + c0)

    # ── клавиатура ──
    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ch = KEYS.get(kc, "")
        name = Gdk.keyval_name(ev.keyval) or ""
        if v.mode == "help":
            v.mode = "normal"
        elif v.mode == "insert":
            self.key_insert(ch, ctrl, name)
        elif v.mode in ("command", "text"):
            self.key_line(ch, shift, ctrl, name, ev)
        elif v.mode == "confirm":
            if ch == "y" or name in ("Return", "KP_Enter"):
                if self.confirm_action:
                    self.confirm_action()
            v.mode = "normal"
            v.doubt = None
            self.confirm_action = None
        else:
            self.key_normal(ch, ctrl, shift, name)
        self.redraw()
        return True

    def key_insert(self, ch, ctrl, name):
        v = self.view
        if name in ("Escape", "Return", "KP_Enter") or (ctrl and ch == "e"):
            self.finish_insert()
        elif name == "BackSpace":
            v.buf = v.buf[:-1]
        elif ch == "j":
            now = time.monotonic()
            if now - self.last_j < 0.4:
                self.finish_insert()
            self.last_j = now
        elif ch.isdigit() or (name.startswith("KP_") and name[3:].isdigit()):
            if len(v.buf) < 4:
                v.buf += ch if ch.isdigit() else name[3:]

    def key_line(self, ch, shift, ctrl, name, ev):
        """Строка команды (латиница по keycode) или текста (буквы как напечатаны)."""
        v = self.view
        if name == "Escape" or (ctrl and ch == "e" and v.mode == "text"):
            if v.mode == "text" and name != "Escape":
                self.finish_text()
            else:
                v.mode, v.buf, v.text_for = "normal", "", None
        elif name in ("Return", "KP_Enter"):
            if v.mode == "command":
                cmd, v.buf, v.mode = v.buf, "", "normal"
                self.run_command(cmd)
            else:
                self.finish_text()
        elif name == "BackSpace":
            if not v.buf:
                v.mode, v.text_for = "normal", None
            v.buf = v.buf[:-1]
        elif v.mode == "command":
            if ch and len(v.buf) < 30:
                if shift:
                    ch = ch.upper() if ch.isalpha() else SHIFTED.get(ch, ch)
                v.buf += ch
        else:
            u = Gdk.keyval_to_unicode(ev.keyval)
            if u and len(v.buf) < 60 and chr(u).isprintable():
                v.buf += chr(u)

    def key_normal(self, ch, ctrl, shift, name):
        v, m = self.view, self.model
        now = time.monotonic()
        pend = self.pending if now - self.pending_t < 1.0 else ""
        self.pending = ""
        tab = v.tab
        if name == "ISO_Left_Tab" or (name == "Tab" and shift):
            self.cycle_tab(-1)
            return
        if name == "Tab":
            self.cycle_tab(1)
            return
        if shift and ch == "h":
            self.cycle_tab(-1)
            return
        if shift and ch == "l":
            self.cycle_tab(1)
            return
        if pend == "g" and ch == "t":
            self.cycle_tab(-1 if shift else 1)
            return
        if ctrl and ch == "s":
            m.save()
            v.flash("сохранено")
            return
        if ctrl:
            if tab == "alarm":
                if ch == "e":
                    self.start_insert()
                elif ch == "r":
                    v.flash("повтор" if m.step_back(fwd=True) else "нечего повторять")
                elif ch == "a":
                    m.shift(v.sel["alarm"], 60)
                elif ch == "x":
                    m.shift(v.sel["alarm"], -60)
            return
        if name == "Escape" or (ch == "q" and not shift):
            self.try_close()
            return
        if (ch == "/" and shift) or name == "question":
            v.mode = "help"
            return
        if ch == ";" and shift:
            v.mode, v.buf = "command", ""
            return
        if tab == "pomo" and v.pomo_view == "stats":
            # в статистике j/k/h/l и стрелки — свои (дни и отрезки)
            self.keys_pomo(ch, shift, name, pend, now)
            return
        rows = {"alarm": DAYS + 1, "focus": v.focus_rows(), "pomo": v.pomo_rows()}[tab]
        if name == "Down" or (ch == "j" and not shift):
            v.sel[tab] = min(rows - 1, v.sel[tab] + 1)
            if tab == "focus":
                self.clamp_focus()
            return
        if name == "Up" or (ch == "k" and not shift):
            v.sel[tab] = max(0, v.sel[tab] - 1)
            if tab == "focus":
                self.clamp_focus()
            return
        if ch == "g" and shift:
            v.sel[tab] = rows - 1
            return
        if ch == "g":
            if pend == "g":
                v.sel[tab] = 0
            else:
                self.pending, self.pending_t = "g", now
            return
        getattr(self, "keys_" + tab)(ch, shift, name, pend, now)

    def keys_alarm(self, ch, shift, name, pend, now):
        v, m = self.view, self.model
        sel = v.sel["alarm"]
        if ch == "w":
            # «встал сейчас» — факт подъёма за сегодня (если будильник не звонил)
            hm = time.strftime("%H:%M")
            m.set_woke(PAST, hm)
            v.flash("сегодня — встал в " + hm)
            return
        if Model.gone(sel):
            # прошедший день: план не правится, только факт подъёма
            if name in ("Return", "KP_Enter") or ch in ("i", "a") or ch.isdigit():
                self.start_insert()
                v.buf = ch if ch.isdigit() else ""
            elif ch == "d":
                if pend == "d":
                    if m.set_woke(sel, None):
                        v.flash("%s — подъём стёрт" % self.row_name(sel))
                else:
                    self.pending, self.pending_t = "d", now
            elif ch in ("h", "l", "x", "-", "=", "p") or name in ("Left", "Right"):
                v.flash("день прошёл — i: когда встали")
            elif name == "space" or ch == " ":
                self.action("a.enabled")
            return
        if name == "Left" or ch == "h":
            m.shift(sel, -STEP)
        elif name == "Right" or ch == "l":
            m.shift(sel, STEP)
        elif ch == "-":
            m.shift(sel, -60)
        elif ch == "=":
            m.shift(sel, 60)
        elif name in ("Return", "KP_Enter") or ch in ("i", "a"):
            self.start_insert()
        elif ch == "x":
            self.action("a.skip")
        elif ch == "d":
            if pend == "d":
                self.action("a.reset")
            else:
                self.pending, self.pending_t = "d", now
        elif ch == "y":
            if pend == "y":
                self.yank = m.time_of(sel)
                v.flash("скопировано " + self.yank)
            else:
                self.pending, self.pending_t = "y", now
        elif ch == "p":
            if self.yank:
                m.set_time(sel, self.yank)
                v.flash("%s — %s" % (self.row_name(sel), self.yank))
            else:
                v.flash("сначала yy")
        elif ch == "u":
            v.flash("отменено" if m.step_back() else "нечего отменять")
        elif name == "space" or ch == " ":
            self.action("a.enabled")
        elif ch == "t":
            self.action("a.test")
        elif ch == "s":
            self.action("a.stop")
        elif ch == "o":
            self.action("a.watch")
        elif ch.isdigit():
            self.start_insert()
            v.buf = ch

    def keys_focus(self, ch, shift, name, pend, now):
        v = self.view
        sel = v.sel["focus"]
        if name == "Left" or ch == "h":
            v.col["focus"] = max(0, v.col["focus"] - 1)
        elif name == "Right" or ch == "l":
            limit = len(FOCUS_DURS) - 1 if sel == 0 else (1 if sel in (1, 2) else View.FOCUS_COLS - 1)
            v.col["focus"] = min(limit, v.col["focus"] + 1)
            self.clamp_focus()
        elif name in ("Return", "KP_Enter"):
            if sel == 0:
                self.focus_start()
            else:
                self.focus_toggle_rule()
        elif name == "space" or ch in (" ", "x"):
            if sel == 0:
                self.focus_start()
            else:
                self.focus_toggle_rule()
        elif ch in ("a", "o"):
            self.start_text("rule")
        elif ch == "e":
            if fm.locked():
                v.flash("строгий режим — исключения не править до конца сессии")
            else:
                self.start_text("allow", ", ".join(fm.load().get("allow", [])))
        elif ch == "d":
            if pend == "d":
                self.focus_delete_rule()
            else:
                self.pending, self.pending_t = "d", now
        elif ch == "=":
            fm.extend(15 * 60)
            v.flash("+15 минут")
        elif ch == "z" and shift:
            self.ask_end_focus()
        elif ch == "s":
            self.focus_start()

    def keys_pomo(self, ch, shift, name, pend, now):
        v = self.view
        sel = v.sel["pomo"]
        if v.pomo_view == "stats":
            # статистика: h/l — день, j/k — отрезки, g — сегодня, s/Backspace — назад
            if name == "Left" or ch == "h":
                v.stats_day, v.stats_scroll, v.stats_sel = max(0, v.stats_day - 1), 0, -1
            elif name == "Right" or ch == "l":
                v.stats_day, v.stats_scroll, v.stats_sel = min(13, v.stats_day + 1), 0, -1
            elif name == "Down" or ch == "j":
                v.stats_sel = min(len(v.stats_rows) - 1, v.stats_sel + 1)
            elif name == "Up" or ch == "k":
                v.stats_sel = max(0, v.stats_sel - 1) if v.stats_rows else -1
            elif ch == "t":
                self.action("p.today")
            elif name == "Delete" or ch == "x":
                self.ask_delete_segment()
            elif ch == "d":
                if pend == "d":
                    self.ask_delete_segment()
                else:
                    self.pending, self.pending_t = "d", now
            elif ch == "u":
                if v.stats_undo:
                    pomo_restore(v.stats_undo.pop())
                    v.flash("вернул")
                else:
                    v.flash("нечего возвращать")
            elif ch == "v":
                self.action("p.detail")
            elif ch == "s" or name == "BackSpace":
                if v.stats_detail:
                    v.stats_detail = False
                    v.stats_scroll, v.stats_sel = 0, -1
                else:
                    v.pomo_view = "start"
            return
        if ch == "s":
            self.action("p.stats")
            return
        if name == "Left" or ch == "h":
            v.col["pomo"] = max(0, v.col["pomo"] - 1)
        elif name == "Right" or ch == "l":
            v.col["pomo"] = min(len(POMO_DURS) - 1, v.col["pomo"] + 1)
        elif name in ("Return", "KP_Enter"):
            self.pomo_start_selected()
        elif name == "space" or ch in (" ", "p"):
            self.action("p.toggle")
        elif ch == "n":
            self.action("p.skip")
        elif ch == "x":
            self.action("p.stop")
        elif ch in ("i", "a"):
            self.start_text("pomo")
        elif ch == "c":
            self.start_text("task", pomo_state()["task"])
        _ = sel


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        toggle = "--toggle" in args
        args = [a for a in args if a != "--toggle"]
        tab = args[0] if args and args[0] in TABS else None
        # --toggle (бинд Super+Alt+F, 06.10.2026): окно открыто и в фокусе — закрыть;
        # открыто, но под другими окнами — поднять; закрыто — открыть.
        if toggle and self.win is not None and self.win.is_active():
            self.win.close()
            return 0
        if self.win is None:
            self.win = RoutineWindow(self, tab or "alarm")
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            self.win.show_all()
        else:
            self.win.view.reload_style()
            if tab:
                self.win.set_tab(tab)
                self.win.redraw()
        self.win.present()
        return 0


def shot(path, mode=None, sel=0, style=None, tab="alarm", col=0, active=1, w=0, h=0,
         view="", detail=0, day=13, seg=-1):
    """PNG без окна — для проверок вида."""
    m = Model()
    v = View(m)
    v.active = bool(active)
    if style:
        v.style, v.c = style, colors(style)
    v.tab = tab
    v.sel[tab] = sel
    if tab in v.col:
        v.col[tab] = col
    if view:
        v.pomo_view, v.stats_detail, v.stats_day = view, bool(detail), day
        v.stats_sel = seg if seg != "-1" else -1
    if mode:
        v.mode = mode
        v.buf = {"insert": "830", "command": "default 9", "text": "shorts"}.get(mode, "")
        v.text_for = "rule"
        v.confirm_text = "Осталось 32 мин. Закончить?"
    ww, h = max(W, w or W), max(v.height(), h or 0)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, ww, h)
    cr = cairo.Context(surf)
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    v.draw(cr, ww, h)
    surf.write_to_png(path)
    return ww, h


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        kw = {}
        for a in sys.argv[3:]:
            k, _, val = a.partition("=")
            kw[k] = int(val) if val.isdigit() else val
        print(shot(sys.argv[2], **kw))
        sys.exit(0)
    GLib.set_prgname(APP_ID)          # app-id окна для правила niri (без этого — имя файла)
    sys.exit(App().run(sys.argv))
