#!/usr/bin/env python3
"""Утренний будильник для режима сна (05.10.2026).

С 08.10.2026 утро — серия проверок «не спите?» (подробно — у SERIES ниже):
T−5 проверка (окно с фразой на всех мониторах + пример в Telegram), T звонок, если не
подтвердили; повторы T+10/20/30 с проверкой за 2 минуты до каждого. Два подтверждения
подряд — серия окончена. Звонок — через динамики и текущий выход, громкость нарастает;
замолкает только от набранной фразы или ответа на пример боту. Последний сдаётся через 30 минут.

Расписание — ~/.config/hypr/state/wake-alarm.json: время по датам (план
постепенного сдвига) и время по умолчанию для остальных дней.

    wake_alarm.py status            — включён ли, ближайший звонок, план
    wake_alarm.py set 08:30 [ДАТА]  — время на дату (по умолчанию — ближайший звонок)
    wake_alarm.py default 09:00     — время для дней без своей строки в плане
    wake_alarm.py skip [ДАТА]       — не звонить в этот день
    wake_alarm.py on | off          — включить / выключить совсем
                 [--reason ТЕКСТ --via tg] — с записью в журнал (аварийно из Telegram: /alarm)
    wake_alarm.py test [СЕКУНДЫ]    — пробный звонок (по умолчанию 10 с)
    wake_alarm.py stop [--force]    — остановить пробный звонок; серию — только с --force
    wake_alarm.py series            — состояние последней серии
    wake_alarm.py test-series [К] [--dry] — серия ускоренно: К секунд на «минуту» (12)
    wake_alarm.py tg-code ТЕКСТ     — зовёт мост бота: ответ на пример (0 принят, 1 нет, 2 не ждём)
    wake_alarm.py sound [t3|classic] — звук звонка (t3 — 520 Гц сериями по три)
    wake_alarm.py woke [ЧЧ:ММ] [ДАТА] — записать подъём вручную («-» — стереть)
    wake_alarm.py watch [ДАТА] 07:00-21:00 [МИН] — Сторож: день без сна, проверки каждые МИН (45)
    wake_alarm.py watch off [ДАТА] [--force] | watch — снять Сторожа / список
    wake_alarm.py watch daily [on | off --reason ТЕКСТ] — ежедневный Сторож: от звонка будильника до 18:00 (14.10: было 21:00)
    wake_alarm.py watch skip [ДАТА] --reason ТЕКСТ | watch skip off [ДАТА] — без Сторожа на день
    (--with-alarm — и без звонка будильника в этот день; кнопка «Сторож» в Clocker)
    wake_alarm.py watch log [N]     — журнал выключений Сторожа (кто, когда, почему)
    wake_alarm.py emergency off --reason ТЕКСТ | emergency on — аварийно (бот): будильник + Сторож на день
    wake_alarm.py check             — зовёт таймер wake-alarm.timer раз в минуту
    wake_alarm.py rtc [check]       — пробуждение по часам: к чему и когда разбудит сон
    wake_alarm.py rtc-test [СЕК]    — проверка: усыпить и проснуться по часам через СЕК (60)
"""
import contextlib
import datetime as dt
import fcntl
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import session_env  # noqa: E402

# служба стартует при входе раньше, чем niri отдаёт systemd свои переменные: 12.10.2026
# окно проверки упало без экрана, такт встал, и Сторож молчал до ночи
session_env.fill()

HOME = os.path.expanduser("~")
STATE = os.path.join(HOME, ".config/hypr/state/wake-alarm.json")
LAST = os.path.join(HOME, ".cache/wake-alarm.last")      # дата последнего звонка
WOKE = os.path.join(HOME, ".local/state/jarvis-wake/woke.json")   # {дата: «ЧЧ:ММ» — нажал «Я встал»}
PIDF = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "wake-alarm.pid")
# громкость динамиков до звонка — на диске, чтобы вернуть её и после kill -9 (07.10.2026:
# бот в Telegram убил звонок сигналом KILL — динамики остались на 100 %, без звука)
SAVED = os.path.join(HOME, ".local/state/jarvis-wake/speaker-saved.json")
# Звук звонка (06.10.2026): по умолчанию «t3» — 520 Гц прямоугольной волной сериями
# по три (код T-3 пожарной сигнализации): в опытах Bruck и Thomas он будил из глубокого
# сна лучше обычных сигналов. «classic» — прежний мягкий freedesktop.
SOUNDS = {
    "t3": os.path.join(HOME, ".config/hypr/sounds/alarm-520hz-t3.wav"),
    "classic": "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga",
}
SOUND = SOUNDS["classic"]
MATUGEN = os.path.join(HOME, ".cache/matugen")

LATE_OK = 30 * 60        # проспал момент (ноутбук спал) — звонить ещё полчаса
RING_MAX = 30 * 60       # звонит не дольше получаса
RAMP = (0.35, 1.0, 120)  # громкость динамиков: от, до, за сколько секунд

DEFAULT_STATE = {
    "enabled": True,
    "default": "09:00",
    "plan": {"2026-10-06": "11:00", "2026-10-07": "10:00", "2026-10-08": "09:00"},
    "skip": [],
    # ежедневный Сторож (09.10.2026): проверки «не спите?» каждые every минут до to — от
    # дневного сна. С 14.10 начинается со звонком (после утренней серии), нет звонка в этот
    # день — нет и Сторожа; from не используется. watch_skip — дни, где его выключили на день
    "watch_daily": {"enabled": True, "from": "06:00", "to": "18:00", "every": 45},
    "watch_skip": [],
}


# ── расписание ────────────────────────────────────────────────────────────────

def load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    for k, v in DEFAULT_STATE.items():
        s.setdefault(k, json.loads(json.dumps(v)))
    return s


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)
    try:
        rtc_plan_write()                  # расписание поменялось — сразу и время пробуждения
    except Exception:
        pass


def alarm_on(s, day):
    """Время звонка в этот день (datetime) или None."""
    if not s["enabled"] or day.isoformat() in s["skip"] or day.isoformat() in s.get("watch", {}):
        return None          # в день Сторожа звонка нет — будят его проверки
    hm = s["plan"].get(day.isoformat(), s["default"])
    h, m = map(int, hm.split(":"))
    return dt.datetime.combine(day, dt.time(h, m))


def next_alarm(s, now=None):
    now = now or dt.datetime.now()
    rung = last_rung()
    for i in range(0, 8):
        day = now.date() + dt.timedelta(days=i)
        t = alarm_on(s, day)
        if t is None or rung == day.isoformat():
            continue
        if t + dt.timedelta(seconds=LATE_OK) > now:
            return t
    return None


def due_within(hours):
    """Для idle_suspend: звонок в ближайшие hours часов — спать ноутбуку нельзя.
    Во время серии проверок — тоже (сегодняшний звонок уже «был», следующий — завтра)."""
    if series_active():
        return True
    s = load()
    now = dt.datetime.now()
    for i in (0, 1):                               # Сторож: начало скоро или уже идёт
        day = now.date() + dt.timedelta(days=i)
        w = watch_for(s, day)
        if not w:
            continue
        try:
            a = dt.datetime.fromisoformat(day.isoformat() + "T" + w["from"])
            b = dt.datetime.fromisoformat(day.isoformat() + "T" + w["to"])
        except (ValueError, KeyError):
            continue
        if a - dt.timedelta(hours=hours) < now < b + dt.timedelta(minutes=40):
            return True
    t = next_alarm(s)
    return t is not None and t - now < dt.timedelta(hours=hours)


# Пробуждение по часам (14.10.2026). Сон больше не запрещён на 14 ч вперёд: перед КАЖДЫМ
# сном хук root'а /usr/lib/systemd/system-sleep/jarvis-rtc-wake (исходник jarvis-rtc-wake.sh)
# заводит часы RTC на время из RTC_PLAN, а план раз в минуту пишет `check` (и save, и idle_suspend).
RTC_PLAN = os.path.join(HOME, ".local/state/jarvis-wake/rtc-wake")
RTC_HOLD = RTC_PLAN + ".hold"          # rtc-test: план не перезаписывать до этого времени
RTC_HOOK = "/usr/lib/systemd/system-sleep/jarvis-rtc-wake"
RTC_LEAD = 30        # минут: проснуться за полчаса до первой проверки (просьба 14.10)
SLEEP_MARGIN = 40 / 60   # часов: ближе к проверке idle_suspend не усыпляет (больше RTC_LEAD,
                         # иначе после пробуждения уснул бы снова)
RTC_SYS = "/sys/class/rtc/rtc0"


def alarm_events(now=None):
    """[(datetime, вид, текст)] — когда ноутбук должен не спать ради будильника и Сторожа:
    первая проверка утренней серии (T−PRE), начало Сторожа или его следующая проверка;
    идёт серия — сейчас."""
    now = now or dt.datetime.now()
    if series_active():
        return [(now, "series", "идёт серия проверок")]
    s = load()
    ev = []
    t = next_alarm(s, now)
    if t is not None:
        ev.append((t - dt.timedelta(minutes=PRE), "alarm", "будильник %s" % t.strftime("%H:%M")))
    for i in (0, 1, 2):
        day = now.date() + dt.timedelta(days=i)
        w = watch_for(s, day)
        if not w:
            continue
        try:
            a = dt.datetime.fromisoformat(day.isoformat() + "T" + w["from"])
            b = dt.datetime.fromisoformat(day.isoformat() + "T" + w["to"])
        except (ValueError, KeyError):
            continue
        if now < a:
            al = alarm_on(s, day)          # ежедневный ждёт утренней серии — будит она
            if not (w["daily"] and al is not None and last_rung() != day.isoformat()):
                ev.append((a, "watch", "Сторож с %s" % w["from"]))
        elif now <= b:                       # Сторож идёт — следующая проверка по сетке
            step = dt.timedelta(minutes=int(w.get("every", WATCH_EVERY)))
            ev.append((a + -(-(now - a) // step) * step, "watch", "проверка Сторожа"))
    return ev


def wake_event(now=None):
    """Ближайшее из alarm_events — datetime или None."""
    ev = alarm_events(now)
    return min(e[0] for e in ev) if ev else None


# 21.10.2026: часы будят и ради хаба — таймеры, напоминания, «только дата», повтор в Telegram,
# отложенный WhatsApp (hublib.wake_events). Будят за HUB_LEAD до срока: сеть успевает
# подняться, а с закрытой крышкой logind усыпит снова через ~30 с — сообщение успеет уйти.
HUB_DIR = os.path.join(HOME, ".local/share/hub")
HUB_LEAD = 20        # секунд
RTC_WHY = RTC_PLAN + ".why"          # ради чего завели часы — hubd молчит о «плановом включении» хаба


def hub_events(now_ts=None):
    try:
        if HUB_DIR not in sys.path:
            sys.path.insert(0, HUB_DIR)
        import hublib
        c = hublib.connect()
        try:
            return hublib.wake_events(c, now_ts)
        finally:
            c.close()
    except Exception:
        return []


def wake_plan(now=None):
    """Все плановые пробуждения: [{wake, at, kind, src, title}] по времени пробуждения.
    at — само событие, wake — когда заведены часы (раньше на RTC_LEAD или HUB_LEAD)."""
    now = now or dt.datetime.now()
    out = []
    for at, kind, title in alarm_events(now):
        ts = int(at.timestamp())
        out.append({"wake": ts - RTC_LEAD * 60, "at": ts, "kind": kind, "src": "alarm", "title": title})
    for ts, kind, title in hub_events(int(now.timestamp())):
        out.append({"wake": ts - HUB_LEAD, "at": ts, "kind": kind, "src": "hub", "title": title})
    return sorted(out, key=lambda e: e["wake"])


def rtc_wake_at(now=None):
    """Когда разбудить (epoch) или 0 — будить не к чему."""
    plan = wake_plan(now)
    if not plan:
        return 0
    return int(max(plan[0]["wake"], time.time() + 60))


def rtc_plan_write():
    try:
        if float(open(RTC_HOLD).read()) > time.time():
            return
    except (OSError, ValueError):
        pass
    plan = wake_plan()
    t = int(max(plan[0]["wake"], time.time() + 60)) if plan else 0
    os.makedirs(os.path.dirname(RTC_PLAN), exist_ok=True)
    tmp = RTC_PLAN + ".tmp"
    with open(tmp, "w") as f:
        f.write("%d\n" % t)
    os.replace(tmp, RTC_PLAN)
    with open(RTC_WHY + ".tmp", "w") as f:
        json.dump(dict(plan[0], plan=t) if plan else {"plan": 0}, f, ensure_ascii=False)
    os.replace(RTC_WHY + ".tmp", RTC_WHY)
    return t


def rtc_ready():
    """Хук стоит и часы доступны — можно спать, будильник разбудит."""
    return os.access(RTC_HOOK, os.X_OK) and os.path.exists(RTC_SYS + "/wakealarm")


def rtc_wakeups():
    try:
        return int(open(RTC_SYS + "/device/power/wakeup_count").read())
    except (OSError, ValueError):
        return -1


def cmd_rtc(check=False):
    t = rtc_plan_write()
    if t is None:
        t = int(open(RTC_PLAN).read() or 0)
    probs = []
    if not os.access(RTC_HOOK, os.X_OK):
        probs.append("хук не установлен: " + RTC_HOOK)
    if not os.path.exists(RTC_SYS + "/wakealarm"):
        probs.append("нет %s/wakealarm" % RTC_SYS)
    try:
        if open(RTC_SYS + "/device/power/wakeup").read().strip() != "enabled":
            probs.append("пробуждение от RTC запрещено (power/wakeup)")
    except OSError:
        pass
    e = wake_event()
    if not check:
        print("событие: %s" % (e.strftime("%d.%m %H:%M") if e else "нет (будильник и Сторож выключены)"))
        print("разбудить: %s" % (time.strftime("%d.%m %H:%M", time.localtime(t)) if t else "не нужно"))
        print("хук: %s" % ("стоит" if os.access(RTC_HOOK, os.X_OK) else "НЕ СТОИТ"))
        print("пробуждений от часов за загрузку: %d" % rtc_wakeups())
    for p in probs:
        print(p)
    return 1 if probs else 0


def cmd_rtc_test(sec):
    """Усыпить ноутбук и проснуться по часам через sec секунд. Итог — в rtc-test.log рядом с планом."""
    log = os.path.join(os.path.dirname(RTC_PLAN), "rtc-test.log")
    if not rtc_ready():
        print("хук не установлен — сначала sudo install (см. rtc)")
        return 1
    while 3 <= time.localtime().tm_sec <= 9:   # не попасть на минутный check таймера
        time.sleep(1)
    src0 = wake_sources()
    t0, slept0 = time.time(), slept_total()
    with open(RTC_HOLD, "w") as f:
        f.write(str(t0 + sec + 120))
    target = int(t0 + sec)
    with open(RTC_PLAN, "w") as f:
        f.write("%d\n" % target)
    print("сплю, проснусь по часам через %d с — ничего не трогайте" % sec, flush=True)
    subprocess.run(["systemctl", "suspend"])
    while slept_total() - slept0 < 1 and time.time() - t0 < 60:
        time.sleep(0.5)                       # процесс замёрзнет на время сна и оттает после
    woke = time.time()                        # оттаял — с точностью до полсекунды + выход из сна
    time.sleep(2)
    slept = slept_total() - slept0
    src1 = wake_sources()
    with contextlib.suppress(OSError):
        os.unlink(RTC_HOLD)
    rtc_plan_write()
    # Счётчик rtc0 wakeup_count на этом ноутбуке не растёт (RTC будит через ACPI), а AC и
    # кнопка питания PNP0C0C отмечаются при КАЖДОМ выходе из сна. Доказательство — время:
    # проснулся в назначенную секунду (+ выход из сна ~3 с), а не раньше.
    late = woke - target
    ok = slept >= 10 and -2 <= late <= 15
    noise = ("AC", "PNP0C0C:00")
    who = [n for n, c in src1.items() if c != src0.get(n) and n not in noise]
    if slept < 1:
        msg = "сна не было (за 60 с ноутбук не уснул)"
    elif ok:
        msg = "ПРОСНУЛСЯ ПО ЧАСАМ: спал %.0f с, назначено %s, проснулся %s" % (
            slept, time.strftime("%H:%M:%S", time.localtime(target)),
            time.strftime("%H:%M:%S", time.localtime(woke)))
    else:
        msg = "часы НЕ разбудили: спал %.0f с, проснулся на %+.0f с от назначенного" % (slept, late)
        if who:
            msg += "; события: " + ", ".join(who)
    print(msg)
    with open(log, "a") as f:
        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    subprocess.run(["notify-send", "-a", "Будильник", "Пробуждение по часам", msg],
                   stderr=subprocess.DEVNULL)
    return 0 if ok else 1


def slept_total():
    """Сколько секунд машина проспала с загрузки: BOOTTIME идёт во сне, MONOTONIC — нет."""
    return time.clock_gettime(time.CLOCK_BOOTTIME) - time.clock_gettime(time.CLOCK_MONOTONIC)


def wake_sources():
    """{имя: счётчик событий} всех источников пробуждения — чтобы назвать, кто разбудил."""
    out = {}
    base = "/sys/class/wakeup"
    for w in os.listdir(base) if os.path.isdir(base) else ():
        try:
            name = open(os.path.join(base, w, "name")).read().strip()
            dev = os.path.realpath(os.path.join(base, w, "device"))
            prod = os.path.join(dev, "product")
            if os.path.exists(prod):
                name += " (%s)" % open(prod).read().strip()
            out[name] = int(open(os.path.join(base, w, "event_count")).read())
        except (OSError, ValueError):
            pass
    return out


def watch_for(s, day):
    """Сторож на этот день: {from, to, every, daily} или None.
    Сторож на дату (watch ДАТА …) заменяет утренний звонок и держится выключателем будильника;
    ежедневный — только в день со звонком: с времени звонка (после утренней серии) до to."""
    w = s.get("watch", {}).get(day.isoformat())
    if w:
        return dict(w, daily=False) if s["enabled"] else None
    w = s.get("watch_daily") or {}
    if not w.get("enabled") or day.isoformat() in s.get("watch_skip", []):
        return None
    # 14.10.2026, просьба: «время начала сторожа зависит от будильника, а время окончания нет;
    # если будильника нет — сторож тоже не активируется». Поставил звонок позже — значит,
    # можно поспать; не встал после повторов — дальше до вечера будит Сторож.
    t = alarm_on(s, day)
    if t is None:
        return None
    to = w.get("to", "18:00")
    if t.strftime("%H:%M") >= to:
        return None
    return {"from": t.strftime("%H:%M"), "to": to,
            "every": int(w.get("every", WATCH_EVERY)), "daily": True}


def watch_log(action, reason="", via="cli", day=None):
    rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "action": action, "via": via}
    if day:
        rec["day"] = day
    if reason:
        rec["reason"] = reason
    os.makedirs(os.path.dirname(WLOG), exist_ok=True)
    with open(WLOG, "a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def watch_log_read(n=50):
    try:
        with open(WLOG) as f:
            rows = [json.loads(x) for x in f if x.strip()]
    except (OSError, ValueError):
        return []
    return rows[-n:]


WLOG_NAMES = {"daily-off": "выключил Сторожа", "daily-on": "включил Сторожа",
              "skip": "без Сторожа на день", "skip-off": "вернул Сторожа на день",
              "alarm-off": "выключил будильник", "alarm-on": "включил будильник",
              "emergency-off": "АВАРИЙНО выключил будильник и Сторожа на день",
              "emergency-on": "включил будильник и Сторожа после аварийного"}


def watch_log_line(r):
    via = {"settings": "Настройки", "clocker": "Clocker", "discipline": "Clocker", "cli": "терминал",
           "tg": "Telegram"}.get(r.get("via"), r.get("via", ""))
    day = r.get("day")
    return "%s  %s%s (%s)%s" % (r["at"][:16], WLOG_NAMES.get(r["action"], r["action"]),
                               " " + dt.date.fromisoformat(day).strftime("%d.%m") if day else "",
                               via, " — " + r["reason"] if r.get("reason") else "")


# 13.10.2026, просьба: «в будильнике показывать, от скольки до скольки работает сторож, и
# только если он работоспособен». 12.10 Сторож молчал 11 ч: служба висела «activating»
# (окно упало без WAYLAND_DISPLAY), таймер новых проверок не запускал. Отсюда признаки.
HEALTH_STALE = 3 * 3600      # серия идёт, а журнал и series.json молчат дольше — зависла


def watch_health():
    """(True, "") — Сторож может сработать; (False, "почему") — нет."""
    try:
        out = subprocess.run(["systemctl", "--user", "show", "wake-alarm.timer", "wake-alarm.service",
                              "-p", "Id,ActiveState,UnitFileState,Result"],
                             capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return False, "systemd молчит"
    u = {}
    for block in out.strip().split("\n\n"):
        kv = dict(x.split("=", 1) for x in block.splitlines() if "=" in x)
        u[kv.get("Id", "")] = kv
    t, sv = u.get("wake-alarm.timer", {}), u.get("wake-alarm.service", {})
    if t.get("ActiveState") != "active":
        return False, "таймер стоит"
    if t.get("UnitFileState") not in ("enabled", "static", "linked"):
        return False, "нет автозапуска"
    if sv.get("ActiveState") == "failed":
        return False, "служба упала"
    if sv.get("ActiveState") in ("activating", "active"):
        if not series_pid_alive():
            return False, "служба зависла"
        last = 0
        for f in (SERIES, SLOG):
            try:
                last = max(last, os.path.getmtime(f))
            except OSError:
                pass
        if time.time() - last > HEALTH_STALE:
            return False, "молчит %d ч" % ((time.time() - last) // 3600)
    return True, ""


def watch_busy(d=None):
    """Идёт проверка или звонок Сторожа — сейчас его не выключить: сначала ответьте."""
    d = d if d is not None else series_load()
    if not d or not d.get("watch") or d.get("done") or d.get("test"):
        return False
    st = cur_step(d)
    return bool(st and st["state"] in ("check", "ring"))


def watch_stop_today(why):
    """Остановить идущего сегодня Сторожа (выключили насовсем или на день)."""
    with series_lock():
        d = series_load()
        if d and d.get("watch") and not d.get("done") and d["date"] == dt.date.today().isoformat():
            finish(d, "stopped")
            series_save(d)
            slog("Сторож остановлен: " + why)        # процесс серии увидит done и закроется сам


def last_rung():
    try:
        return open(LAST).read().strip()
    except OSError:
        return ""


def parse_day(arg, s):
    if arg is None:
        t = next_alarm(s)
        return (t or dt.datetime.now() + dt.timedelta(days=1)).date()
    if arg in ("today", "сегодня"):
        return dt.date.today()
    if arg in ("tomorrow", "завтра"):
        return dt.date.today() + dt.timedelta(days=1)
    return dt.date.fromisoformat(arg)


def check_hm(hm):
    h, m = map(int, hm.split(":"))
    assert 0 <= h < 24 and 0 <= m < 60
    return "%02d:%02d" % (h, m)


def sound_file():
    name = load().get("sound", "t3")
    path = SOUNDS.get(name, SOUNDS["t3"])
    return path if os.path.exists(path) else SOUNDS["classic"]


# ── факт подъёма ──────────────────────────────────────────────────────────────
# 06.10.2026: время нажатия «Я встал» — чтобы видеть рядом с планом, восстанавливается
# ли режим на деле (вкладка Alarm окна Routine).

def woke_load():
    try:
        with open(WOKE) as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def woke_set(day, hm):
    d = woke_load()
    if hm:
        d[day.isoformat()] = hm
    else:
        d.pop(day.isoformat(), None)
    cut = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    d = {k: v for k, v in d.items() if k >= cut}
    os.makedirs(os.path.dirname(WOKE), exist_ok=True)
    tmp = WOKE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp, WOKE)


# ── звук ──────────────────────────────────────────────────────────────────────

def pactl(*a):
    return subprocess.run(["pactl", *a], capture_output=True, text=True).stdout


def sinks():
    """(выход по умолчанию, встроенные динамики или None)."""
    default = pactl("get-default-sink").strip()
    speaker = None
    for line in pactl("list", "short", "sinks").splitlines():
        name = line.split("\t")[1] if "\t" in line else ""
        if name.startswith("alsa_output.pci") and "hdmi" not in name:
            speaker = name
    return default, speaker


def sink_vol_mute(name):
    out = pactl("get-sink-volume", name)
    vol = None
    for tok in out.split():
        if tok.endswith("%"):
            vol = tok
            break
    mute = "yes" in pactl("get-sink-mute", name)
    return vol, mute


class Ringer:
    def __init__(self, seconds):
        self.seconds = seconds
        self.stop_ev = threading.Event()
        self.default, self.speaker = sinks()
        self.saved = sink_vol_mute(self.speaker) if self.speaker else None
        try:                       # прошлый звонок убит, не вернув громкость — верная та
            old = json.load(open(SAVED))
            if old.get("speaker") == self.speaker:
                self.saved = (old.get("vol"), bool(old.get("mute")))
        except (OSError, ValueError, AttributeError):
            pass
        if self.speaker and self.saved:
            try:
                os.makedirs(os.path.dirname(SAVED), exist_ok=True)
                json.dump({"speaker": self.speaker, "vol": self.saved[0], "mute": self.saved[1]},
                          open(SAVED, "w"))
            except OSError:
                pass
        self.procs = []

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def loop(self):
        t0 = time.monotonic()
        if self.speaker:
            pactl("set-sink-mute", self.speaker, "0")
        targets = [self.default]
        if self.speaker and self.speaker != self.default:
            targets.append(self.speaker)
        lo, hi, ramp = RAMP
        while not self.stop_ev.is_set():
            el = time.monotonic() - t0
            if el > self.seconds:
                break
            if self.speaker:
                v = lo + (hi - lo) * min(1.0, el / ramp)
                pactl("set-sink-volume", self.speaker, "%d%%" % round(v * 100))
            self.procs = [subprocess.Popen(
                ["pw-play", "--target", tg, "-P",
                 '{ application.name = "Будильник" media.role = "Alarm" }', sound_file()],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for tg in targets]
            for p in self.procs:
                try:
                    p.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    p.kill()
            self.stop_ev.wait(0.3)
        self.restore()
        self.stop_ev.set()

    def stop(self):
        self.stop_ev.set()
        for p in self.procs:
            if p.poll() is None:
                p.kill()

    def restore(self):
        if self.speaker and self.saved:
            vol, mute = self.saved
            if vol:
                pactl("set-sink-volume", self.speaker, vol)
            pactl("set-sink-mute", self.speaker, "1" if mute else "0")
        try:
            os.remove(SAVED)
        except OSError:
            pass


def recover_speaker():
    """Звонок убит (kill -9) — вернуть динамикам громкость из SAVED. Зовётся из check."""
    if not os.path.exists(SAVED):
        return
    try:
        os.kill(int(open(PIDF).read()), 0)
        return                     # звонок ещё идёт
    except (OSError, ValueError):
        pass
    try:
        old = json.load(open(SAVED))
        if old.get("vol"):
            pactl("set-sink-volume", old["speaker"], old["vol"])
        pactl("set-sink-mute", old["speaker"], "1" if old.get("mute") else "0")
    except (OSError, ValueError, KeyError, AttributeError):
        pass
    try:
        os.remove(SAVED)
    except OSError:
        pass


# ── окно ──────────────────────────────────────────────────────────────────────

def accent():
    try:
        v = open(os.path.join(MATUGEN, "vivid.txt")).read().strip()
        if v.startswith("#") and len(v) == 7:
            return v
    except OSError:
        pass
    return "#7aa2f7"


def lock_screen():
    """Настоящий звонок — сперва заблокировать экран: «Я встал» нажимается только
    после пароля (07.10.2026). Блокировка по простою пропускается при Savage Mode
    с «не отключать экран» и при видео в фокусе — пользователь выключил звонок без пароля."""
    try:
        sid = subprocess.run(["loginctl", "show-user", str(os.getuid()), "-p", "Display", "--value"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        locked = subprocess.run(["loginctl", "show-session", sid, "-p", "LockedHint", "--value"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if locked == "yes":
            return
        subprocess.run(["loginctl", "lock-session"] + ([sid] if sid else []), timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def ring(seconds, window=True, record=False):
    with open(PIDF, "w") as f:
        f.write(str(os.getpid()))
    if record:
        lock_screen()
    subprocess.run(["niri", "msg", "action", "power-on-monitors"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    r = Ringer(seconds)
    started = time.monotonic()

    def done(*_a):
        r.stop()
    signal.signal(signal.SIGTERM, done)
    signal.signal(signal.SIGINT, done)
    r.start()
    try:
        if window:
            run_window(r, record)
        else:
            while not r.stop_ev.is_set():
                r.stop_ev.wait(0.5)
    finally:
        r.stop()
        r.thread.join(timeout=5)   # поток сам вернёт громкость динамиков
        r.restore()
        try:
            os.remove(PIDF)
        except OSError:
            pass
    if seconds >= 60 and time.monotonic() - started >= seconds - 1:
        subprocess.run(["notify-send", "-a", "Будильник", "Будильник",
                        "Звонил %d мин, выключился сам." % (seconds // 60)])


def run_window(r, record=False):
    """Пробный звонок (`test`) и звонок без серии: замолкает, когда набрана фраза."""
    import wake_overlay
    from gi.repository import GLib, Gtk

    def done():
        if record:
            try:
                woke_set(dt.date.today(), time.strftime("%H:%M"))
            except OSError:
                pass
        r.stop()
    ov = wake_overlay.Overlay(done)
    ov.show(dict(mode="ring", key="test", phrase=pick_phrase(), head="БУДИЛЬНИК · ПРОБА",
                 title="Наберите фразу — звонок замолчит.", sub="раскладку переключайте сами",
                 steps=[], tg=""))

    def tick():
        if r.stop_ev.is_set():
            Gtk.main_quit()
            return False
        return True
    GLib.timeout_add(300, tick)
    Gtk.main()
    ov.hide()


# ── серия проверок «не спите?» ────────────────────────────────────────────────
# 08.10.2026, просьба: «могу встать, выключить будильник и спать дальше». Теперь утро —
# серия шагов. Шаг = проверка (окно во весь экран + код в Telegram одновременно) и, если
# её не подтвердили до срока, — громкий звонок:
#   T−5 мин  проверка (5 мин)  → T      звонок
#   T+8      проверка (2 мин)  → T+10   повтор 1
#   T+18     проверка          → T+20   повтор 2
#   T+28     проверка          → T+30   повтор 3
# Подтверждение — набрать фразу на ПК или прислать боту ответ на пример (каждый раз новый,
# ошибся — можно ещё, пока не вышло время). Выключить звонок можно тем же способом — это
# тоже подтверждение. Два подтверждения подряд — серия окончена, дальше план на завтра.
# Звонок шага длится до следующей проверки (последний — до получаса); не выключили —
# шаг «проспан», счёт подряд начинается заново.
# Факт подъёма — время первого подтверждения; откуда (ПК / только Telegram) — в VIA:
# подтверждение только из Telegram могло быть из кровати, Clocker рисует его серым.

SERIES = os.path.join(HOME, ".local/state/jarvis-wake/series.json")
SLOCK = os.path.join(HOME, ".local/state/jarvis-wake/series.lock")
VIA = os.path.join(HOME, ".local/state/jarvis-wake/via.json")    # {дата: "pc" | "tg"}
TG_CONF = os.path.join(HOME, ".config/wake-alarm")   # env: TOKEN=…, OWNER=… (id чата)
SLOG = os.path.join(HOME, ".local/state/jarvis-wake/series.log")
# журнал выключений и включений Сторожа (09.10.2026): строка JSON на событие — причину
# выключения можно посмотреть в любой день (watch log, Настройки → Config)
WLOG = os.path.join(HOME, ".local/state/jarvis-wake/watch-log.jsonl")

PRE = 5          # минут на первую проверку (до звонка)
GAP = 10         # минут между звонками
WIN = 2          # минут на проверку перед повтором
REPEATS = 3
NEED = 2         # подтверждений подряд — серия окончена
LAST_RING = 30   # минут звонит последний повтор
# 08.10.2026 (Пользователь проснулся в 11:03, подтвердил, лёг и проспал до 20:00): после двух
# подтверждений — контрольная проверка через CTRL минут после первого. Тихая (окно + пример
# в Telegram) CTRL_WIN минут, не ответил — громкий звонок до CTRL_RING минут.
CTRL = 50
# 14.10.2026, просьба: «подтверждения с телефона не считаются — иначе лёжа подтвержу и дальше
# сплю». Ответ в Telegram лишь глушит текущий шаг: через TG_SNOOZE минут снова проверка
# (утро, контрольная, Сторож), и так пока не наберёте фразу на ПК. Утренние повторы идут и
# после REPEATS — до подтверждения с ПК (не дольше конца дня Сторожа, cap серии).
TG_SNOOZE = 10
CTRL_WIN = 5
CTRL_RING = 30
WATCH_EVERY = 45  # Сторож: проверка каждые N минут (день, когда спать нельзя)
# 09.10.2026: пока пользователь за компьютером, Сторож молчит. Проверка приходит, только когда
# WATCH_IDLE минут не было ни клавиш, ни мыши; следующая — не раньше чем через WATCH_EVERY.
# Последний ввод пишет основной hypridle (listener 60 с) в INPUT: «idle ts» / «active ts».
# 14.10.2026, просьба: «если активность есть — никакие алерты не присылать; нет активности
# больше 45 минут — активируются все». Тот же порог: утренний звонок не начинается, если вы
# за ПК (засчитывается подъём), контрольная проверка снимается. Видео в фокусе — активность,
# звонок в Telegram — нет (он не ввод и не видео: idle_guard.VIDEO_APPS).
WATCH_IDLE = 45
INPUT = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "jarvis-input")


def last_input(now=None):
    """Время последнего нажатия/движения мыши или None, если неизвестно (тогда не пропускать).
    Видео в фокусе = не простой (09.10.2026: «я могу длинный видос смотреть»)."""
    now = now or time.time()
    if subprocess.run(["pgrep", "-fx", "hypridle"], stdout=subprocess.DEVNULL).returncode:
        return None
    try:
        state, ts = open(INPUT).read().split()[:2]
        ts = float(ts)
    except (OSError, ValueError):
        return None
    if state == "idle":
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            from idle_guard import video_in_focus
            if video_in_focus():
                return now
        except Exception:
            pass
        li = ts - 60
        sl = last_sleep()
        # после сна hypridle мог заново отсчитать минуту простоя: «ввод» в момент пробуждения
        # (часы будят за полчаса до звонка) — не ввод, последний настоящий был до сна
        if sl and sl[0] - 60 <= li <= sl[1] + 90:
            li = min(li, sl[0])
        return li
    return now


def last_sleep():
    """(уснул, проснулся) epoch последнего сна — по журналу хука jarvis-rtc-wake, или None."""
    try:
        out = subprocess.run(["journalctl", "-t", "jarvis-rtc-wake", "-n", "2", "-o", "json",
                              "--no-pager", "-q"], capture_output=True, text=True, timeout=5).stdout
        ev = [json.loads(x) for x in out.splitlines() if x.strip()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    if len(ev) < 2 or ev[-1].get("MESSAGE") != "проснулся" or ev[-2].get("MESSAGE") == "проснулся":
        return None
    return tuple(int(e["__REALTIME_TIMESTAMP"]) / 1e6 for e in ev[-2:])


def awake_at_pc(now=None):
    """Вы за ПК: ввод (или видео в фокусе) за последние WATCH_IDLE минут."""
    now = now or time.time()
    li = last_input(now)
    return li is not None and now - li < WATCH_IDLE * 60

# Фразы: 25–35 знаков, строчные, без знаков препинания и «ё». Русские, английские и
# смешанные — раскладку иногда надо переключить посреди фразы (это и будит).
PHRASES = [
    "я встал и сейчас иду умываться",
    "доброе утро джарвис я уже не сплю",
    "открываю шторы и пью стакан воды",
    "сегодня хороший день чтобы начать",
    "встаю с кровати и иду на кухню",
    "сон закончился пора за работу",
    "я проснулся и голова уже думает",
    "умыться холодной водой и на свет",
    "good morning jarvis i am awake now",
    "time to get up and drink some water",
    "i am out of bed and ready to move",
    "open the window and breathe deeply",
    "coffee first then java practice",
    "доброе утро sir пора вставать",
    "встаю и открываю java конспект",
    "wake up сэр день уже начался",
]


def math_task():
    """08.10.2026: вместо кода из 6 цифр — пример средней трудности. Код перепечатывается
    с уведомления полусонным, лёжа; пример заставляет подумать — проще встать к ПК
    (просьба: «не 2+2, но и не 47×3+18»). Одно действие, с переносом через десяток.
    (текст, ответ строкой)."""
    r = secrets.SystemRandom()
    kind = r.choice("+-*")
    if kind == "+":
        while True:
            a, b = r.randint(23, 79), r.randint(18, 69)
            if a % 10 + b % 10 >= 10:
                break
        return "%d + %d" % (a, b), str(a + b)
    if kind == "-":
        while True:
            a, b = r.randint(52, 96), r.randint(17, 48)
            if a % 10 < b % 10:
                break
        return "%d − %d" % (a, b), str(a - b)
    a, b = r.randint(12, 19), r.randint(3, 8)
    return "%d × %d" % (a, b), str(a * b)


def pick_phrase(avoid=()):
    return secrets.choice([p for p in PHRASES if p not in avoid] or PHRASES)


def slog(msg):
    try:
        os.makedirs(os.path.dirname(SLOG), exist_ok=True)
        with open(SLOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


@contextlib.contextmanager
def series_lock():
    os.makedirs(os.path.dirname(SLOCK), exist_ok=True)
    with open(SLOCK, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def series_load():
    try:
        with open(SERIES) as f:
            d = json.load(f)
        return d if isinstance(d, dict) and d.get("steps") else None
    except (OSError, ValueError):
        return None


def series_save(d):
    os.makedirs(os.path.dirname(SERIES), exist_ok=True)
    tmp = SERIES + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, SERIES)


def series_build(t, test=False, k=60):
    """Серия для звонка в t (datetime). k — секунд в «минуте» (тест — быстрее)."""
    T = t.timestamp()
    steps = []
    for n in range(REPEATS + 1):
        due = T + n * GAP * k
        check = due - (PRE if n == 0 else WIN) * k
        last = n == REPEATS
        until = due + (LAST_RING if last else GAP - WIN) * k
        steps.append({"n": n, "check": check, "due": due, "until": until,
                      "hm": time.strftime("%H:%M:%S" if test else "%H:%M", time.localtime(due)),
                      **dict(zip(("task", "code"), math_task())),
                      "phrase": pick_phrase([s["phrase"] for s in steps[-1:]]),
                      "state": "wait"})
    now = time.time()
    for st in steps:                     # ноутбук спал / включён поздно — прошедшие шаги не в счёт
        if st["until"] <= now:
            st["state"] = "off"
    cap = T + 60 * k if test else 0
    if not test:
        try:
            to = (load().get("watch_daily") or {}).get("to", "18:00")
            cap = dt.datetime.combine(t.date(), dt.time(*map(int, to.split(":")))).timestamp()
        except (ValueError, TypeError):
            pass
        cap = max(cap, T + 3 * 3600)      # звонок поздно вечером — повторы ещё три часа
    return {"date": t.date().isoformat(), "t": t.strftime("%H:%M"), "test": test, "k": k,
            "steps": steps, "streak": 0, "done": False, "result": None, "pid": os.getpid(),
            "started": now, "cap": cap}


def cur_step(d):
    for st in d["steps"]:
        if st["state"] in ("wait", "check", "ring"):
            return st
    return None


def series_locks(d=None, now=None):
    """Запрещено ли сейчас менять сегодняшний день: утро — всю серию, Сторож — только пока
    идёт его проверка или звонок (в остальное время дня будильник и Сторожа можно трогать)."""
    d = d if d is not None else series_load()
    if not series_active(d, now):
        return False
    return watch_busy(d) if d.get("watch") else True


def series_active(d=None, now=None):
    """Идёт ли сейчас НАСТОЯЩАЯ серия (для Clocker и команд: сегодня трогать нельзя)."""
    d = d if d is not None else series_load()
    now = now or time.time()
    if not d or d.get("done") or d.get("test"):
        return False
    return d["steps"][0]["check"] <= now <= d["steps"][-1]["until"] + 300


def via_load():
    try:
        with open(VIA) as f:
            v = json.load(f)
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def via_set(day, via):
    v = via_load()
    v[day] = via
    cut = (dt.date.today() - dt.timedelta(days=120)).isoformat()
    v = {a: b for a, b in v.items() if a >= cut}
    os.makedirs(os.path.dirname(VIA), exist_ok=True)
    tmp = VIA + ".tmp"
    with open(tmp, "w") as f:
        json.dump(v, f, indent=1, sort_keys=True)
    os.replace(tmp, VIA)


def finish(d, result):
    for st in d["steps"]:
        if st["state"] in ("wait", "check", "ring"):
            st["state"] = "off"
    d["done"], d["result"] = True, result


def confirm(d, via, now=None):
    """Подтвердить текущий шаг (на ПК — фразой, в Telegram — ответом на пример). Под series_lock."""
    now = now or time.time()
    st = cur_step(d)
    if st is None or st["state"] not in ("check", "ring"):
        return None
    was_ring = st["state"] == "ring"
    st.update(state="ok", via=via, at=now, rang=was_ring)
    pc = via == "pc"
    if pc:
        d["streak"] = d.get("streak", 0) + 1
    if not d.get("test") and not d.get("watch"):
        try:
            if pc and not d.get("first_pc"):          # подъём — когда дошли до ПК
                woke_set(dt.date.fromisoformat(d["date"]), time.strftime("%H:%M", time.localtime(now)))
                via_set(d["date"], "pc")
            elif not pc and not d.get("first"):
                via_set(d["date"], "tg")
        except OSError:
            pass
    d.setdefault("first", now)
    if pc:
        d.setdefault("first_pc", now)
    kind = st.get("kind")
    if not pc:
        tg_snooze(d, st, now)                 # с телефона — только отсрочка
        if kind == "watch" and cur_step(d) is None:
            finish(d, "ok")
    elif kind == "watch":
        if cur_step(d) is None:
            finish(d, "ok")
    elif kind == "ctrl":
        finish(d, "ok")
    elif d["streak"] >= NEED or st["n"] >= REPEATS:
        add_control(d, now)
    slog("шаг %d подтверждён (%s)%s" % (st["n"], via, " — серия окончена" if d["done"] else ""))
    return st


def add_control(d, now):
    """Утро подтверждено — оставшиеся повторы снять, через CTRL минут после подъёма ещё одна проверка."""
    k = d.get("k", 60)
    for st in d["steps"]:
        if st["state"] == "wait":
            st["state"] = "off"
    check = max(d.get("first_pc", d.get("first", now)) + CTRL * k, now + 10 * k)
    due = check + CTRL_WIN * k
    task, code = math_task()
    d["steps"].append({"n": len(d["steps"]), "kind": "ctrl", "check": check, "due": due,
                       "until": due + CTRL_RING * k,
                       "hm": time.strftime("%H:%M:%S" if d.get("test") else "%H:%M", time.localtime(due)),
                       "task": task, "code": code,
                       "phrase": pick_phrase([d["steps"][-1]["phrase"]]), "state": "wait"})


def add_repeat(d, due):
    """Ещё один утренний повтор (звонок в due) — пока утро не подтверждено с ПК."""
    k = d.get("k", 60)
    task, code = math_task()
    st = {"n": len(d["steps"]), "check": due - WIN * k, "due": due, "until": due + (GAP - WIN) * k,
          "hm": time.strftime("%H:%M:%S" if d.get("test") else "%H:%M", time.localtime(due)),
          "task": task, "code": code, "phrase": pick_phrase([d["steps"][-1]["phrase"]]),
          "state": "wait", "extra": True}
    d["steps"].append(st)
    return st


def tg_snooze(d, st, now):
    """Шаг подтверждён с телефона: через TG_SNOOZE минут — снова проверка того же рода."""
    k = d.get("k", 60)
    kind = st.get("kind")
    if kind is None:                          # утро: следующий повтор уже стоит, иначе — добавить
        if not any(s2["state"] == "wait" for s2 in d["steps"]) and now + GAP * k < d.get("cap", 0):
            add_repeat(d, now + GAP * k)
        return
    check = now + TG_SNOOZE * k
    if kind == "watch" and check >= d.get("end", float("inf")):
        return                                # Сторож на сегодня кончается
    due = check + CTRL_WIN * k
    task, code = math_task()
    new = {"kind": kind, "check": check, "due": due, "until": due + CTRL_RING * k,
           "hm": time.strftime("%H:%M:%S" if d.get("test") else "%H:%M",
                               time.localtime(check if kind == "watch" else due)),
           "task": task, "code": code, "phrase": pick_phrase([st["phrase"]]), "state": "wait",
           "retry": True}
    i = st["n"] + 1
    for s2 in d["steps"][i:]:                 # проверки Сторожа в окне отсрочки не нужны
        if s2["state"] == "wait" and s2["check"] < new["until"]:
            s2.update(state="off", skip="retry")
    d["steps"].insert(i, new)
    for n, s2 in enumerate(d["steps"]):
        s2["n"] = n


def watch_build(day, t0, t1, every, test=False, k=60):
    """Сторож: проверки с t0 до t1 каждые every минут (день, когда нельзя уснуть)."""
    base = dt.datetime.combine(day, dt.time())
    a = (base + dt.timedelta(minutes=t0)).timestamp()
    b = (base + dt.timedelta(minutes=t1)).timestamp()
    steps, t = [], a
    while t <= b:
        steps.append(t)
        t += every * k
    out = []
    for i, c in enumerate(steps):
        due = c + CTRL_WIN * k
        until = due + CTRL_RING * k
        if i + 1 < len(steps):
            until = min(until, steps[i + 1])
        task, code = math_task()
        out.append({"n": i, "kind": "watch", "check": c, "due": due, "until": until,
                    "hm": time.strftime("%H:%M:%S" if test else "%H:%M", time.localtime(c)),
                    "task": task, "code": code,
                    "phrase": pick_phrase([s["phrase"] for s in out[-1:]]), "state": "wait"})
    now = time.time()
    for st in out:
        if st["until"] <= now:
            st["state"] = "off"
    return {"date": day.isoformat(), "t": "%02d:%02d" % divmod(t0, 60), "watch": True,
            "end": b, "every": every,
            "test": test, "k": k, "steps": out, "streak": 0, "done": False, "result": None,
            "pid": os.getpid(), "started": now}


def advance(d, now):
    """Сдвинуть серию по времени. Возвращает события [(вид, шаг)]."""
    ev = []
    for _ in range(len(d["steps"]) + 1):
        st = cur_step(d)
        if (st is None and not d["done"] and not d.get("watch") and not d.get("first_pc")
                and now + WIN * d.get("k", 60) < d.get("cap", 0)):
            st = add_repeat(d, now + WIN * d.get("k", 60))   # утро не подтверждено с ПК — ещё повтор
        if st is None:
            if not d["done"]:
                ok = any(s["state"] == "ok" and (d.get("watch") or s.get("via") != "tg")
                         for s in d["steps"])
                finish(d, "ok" if ok else "fail")
                ev.append(("done", None))
            break
        if (st.get("kind") == "watch" and st["state"] == "wait" and now >= st["check"]
                and not st.get("retry")):             # отсрочку с телефона не откладывать
            k = d.get("k", 60)
            li = last_input(now)
            if li is not None and now - li < WATCH_IDLE * k:      # за компьютером — отложить
                new = li + WATCH_IDLE * k
                if new > d.get("end", float("inf")):
                    st.update(state="off", skip="active")
                    continue
                shift = new - st["check"]
                st.update(check=new, due=st["due"] + shift, until=new + (CTRL_WIN + CTRL_RING) * k,
                          hm=time.strftime("%H:%M:%S" if d.get("test") else "%H:%M", time.localtime(new)))
                for s2 in d["steps"][st["n"] + 1:]:              # обогнанные проверки не нужны
                    if s2["state"] == "wait" and s2["check"] < new + d.get("every", WATCH_EVERY) * k:
                        s2.update(state="off", skip="active")
                break
        if (st.get("kind") == "ctrl" and st["state"] == "wait" and now >= st["check"]
                and not st.get("retry") and not d.get("test") and awake_at_pc(now)):
            st.update(state="off", skip="active")       # за ПК — уже не уснули
            slog("контрольная проверка снята: вы за ПК")
            continue
        if st["state"] == "wait" and now >= st["check"]:
            st["state"] = "check"
            ev.append(("check", st))
        if st["state"] == "check" and now >= st["due"]:
            st["state"] = "ring"
            ev.append(("ring", st))
        if st["state"] == "ring" and now >= st["until"]:
            st["state"] = "fail"
            d["streak"] = 0
            ev.append(("fail", st))
            slog("шаг %d проспан" % st["n"])
            continue
        break
    return ev


# — Telegram: сообщения шлёт сам будильник (Bot API), ответ с кодом ловит бот —
# 14.10.2026, просьба: «хаб основной, первый запасной». Основной — бот hub: шлём его
# токеном, ответ кодом ловит hubd. Запасной — свой бот из ~/.config/wake-alarm (env):
# если служба hub не работает или до Telegram не достучался.
HUB_CONF = os.path.join(HOME, ".config/hub")


def hub_env():
    env = {}
    try:
        for line in open(os.path.join(HUB_CONF, "env"), encoding="utf-8"):
            k, _, v = line.strip().partition("=")
            if k == "TOKEN":
                env["TOKEN"] = v.strip().strip("'\"")
        o = json.load(open(os.path.join(HUB_CONF, "config.json"))).get("owner")
        o = o[0] if isinstance(o, (list, tuple)) and o else o
        if o:
            env["OWNER"] = str(o)
    except (OSError, ValueError):
        pass
    return env if env.get("TOKEN") and env.get("OWNER") else {}


def hub_alive():
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", "hub"]).returncode == 0


def tg_bot_env(bot):
    return hub_env() if bot == "hub" else tg_env()


def tg_route():
    """Каким ботом писать: hub, если служба жива и настроена, иначе свой (own)."""
    if hub_alive() and hub_env():
        return "hub"
    return "own"

def tg_env():
    env = {}
    try:
        for line in open(os.path.join(TG_CONF, "env")):
            k, _, v = line.strip().partition("=")
            if k:
                env[k] = v
    except OSError:
        pass
    return env


def tg_receivable():
    """Ответ кодом ловит hubd (служба hub) или свой бот, который зовёт
    `wake_alarm.py tg-code ТЕКСТ` (файл receiver в ~/.config/wake-alarm). Нет ни того,
    ни другого — подтверждать можно только на ПК."""
    if tg_route() == "hub":
        return True
    return os.path.exists(os.path.join(TG_CONF, "receiver")) and bool(tg_env().get("TOKEN"))


def tg_call(method, bot=None, **params):
    """(результат, бот). bot=None — основной путь (tg_route), не дошло через хаб —
    повтор запасным ботом; для правки сообщения bot — тот, кто его отправил."""
    if bot is None:
        bot = tg_route()
        res = tg_call_one(method, bot, dict(params))
        if res is None and bot == "hub":
            slog("telegram %s: хаб не доставил — запасной бот" % method)
            bot = "own"
            res = tg_call_one(method, bot, dict(params))
        return res, bot
    return tg_call_one(method, bot, params), bot


def tg_call_one(method, bot, params):
    e = tg_bot_env(bot)
    if not e.get("TOKEN") or not e.get("OWNER"):
        return None
    params.setdefault("chat_id", e["OWNER"])
    data = urllib.parse.urlencode(params).encode()
    url = "https://api.telegram.org/bot%s/%s" % (e["TOKEN"], method)
    # 13.10.2026: провайдер пускает к api.telegram.org через раз — не вышло напрямую,
    # пробуем через Tor (9050 — служба hub-tor, 9150 — Tor Browser), как бот hub и мост.
    for port in (None, 9050, 9150):
        try:
            if port is None:
                opener = urllib.request.build_opener()
            else:
                import socks
                import sockshandler
                opener = urllib.request.build_opener(
                    sockshandler.SocksiPyHandler(socks.SOCKS5, "127.0.0.1", port, rdns=True))
            with opener.open(url, data=data, timeout=15 if port is None else 40) as r:
                res = json.load(r)
            return res.get("result") if res.get("ok") else None
        except Exception as ex:
            slog("telegram %s %s%s: %r" % (bot, method, "" if port is None else " (Tor :%d)" % port, ex))
    return None


def hmf(d, ts):
    return time.strftime("%H:%M:%S" if d.get("test") else "%H:%M", time.localtime(ts))


def spaced(code):
    return " ".join(code)


def step_label(d, st):
    if st.get("kind") == "ctrl":
        return "контрольная проверка (звонок в %s)" % st["hm"]
    if st.get("kind") == "watch":
        return "Сторож, проверка %d из %d" % (st["n"] + 1, len(d["steps"]))
    if st["n"] == 0:
        return "звонок в %s" % st["hm"]
    if st["n"] > REPEATS:
        return "повтор %d (%s)" % (st["n"], st["hm"])
    return "повтор %d из %d (%s)" % (st["n"], REPEATS, st["hm"])


def check_text(d, st, can_reply):
    hm = st["hm"]
    if st.get("kind") == "ctrl":
        head = "Сэр, контрольная проверка: почти час после подъёма. Не уснули?"
    elif st.get("kind") == "watch":
        head = "Сэр, Сторож: проверка %d из %d. Не спите?" % (st["n"] + 1, len(d["steps"]))
    elif st["n"] == 0:
        head = "Доброе утро, сэр! Вы проснулись?\nБудильник в %s." % hm
    elif st["n"] == 1:
        head = "Сэр, вы точно ведь встали, да? Подтвердите повторное отключение — %s." % step_label(d, st)
    elif st["n"] == 2:
        head = "Сэр, ещё одна проверка — %s. Не спите?" % step_label(d, st)
    elif st["n"] == 3:
        head = "Сэр, третья проверка — %s." % step_label(d, st)
    else:
        head = "Сэр, утро ещё не подтверждено с ПК — %s." % step_label(d, st)
    if can_reply:
        body = ("Решите пример и пришлите ответ:\n\n%s = ?\n\nДо %s, иначе зазвонит. Ответ здесь — "
                "только отсрочка на %d минут; закончить можно фразой на ПК.") % (
            st.get("task") or spaced(st["code"]), hmf(d, st["due"]), TG_SNOOZE)
    else:
        body = ("Подтвердите на ПК до %s — бот сейчас не принимает ответы."
                % hmf(d, st["due"]))
    return ("ТЕСТ · " if d.get("test") else "") + head + "\n" + body


def next_alarm_text():
    t = next_alarm(load())
    if not t:
        return "Следующего будильника на неделе нет."
    day = "завтра" if t.date() == dt.date.today() + dt.timedelta(days=1) else t.strftime("%d.%m")
    return "Следующий будильник — %s в %s." % (day, t.strftime("%H:%M"))


def done_text(d):
    if d.get("watch"):
        miss = sum(1 for s in d["steps"] if s["state"] == "fail")
        ok = sum(1 for s in d["steps"] if s["state"] == "ok")
        act = sum(1 for s in d["steps"] if s.get("skip") == "active")
        return "Сторож закончил, сэр: подтверждено %d, проспано %d, пропущено (были за ПК) %d." % (ok, miss, act)
    ctrl = [s for s in d["steps"] if s.get("kind") == "ctrl"]
    first = d.get("first_pc") or d.get("first")
    if d.get("result") == "ok" and ctrl and ctrl[-1]["state"] == "fail":
        return ("Встали в %s, но контрольную проверку проспали, сэр. %s" % (
            hmf(d, first) if first else "?",
            "" if d.get("test") else next_alarm_text())).strip()
    if d.get("result") == "ok":
        return ("Утро засчитано, сэр: проверки окончены, встали в %s. %s" % (
            hmf(d, first) if first else "?",
            "" if d.get("test") else next_alarm_text())).strip()
    if d.get("result") == "stopped":
        return "Серия остановлена вручную."
    if d.get("first"):
        return "Утро не засчитано, сэр: подтверждали только с телефона, до ПК так и не дошли."
    return "Утро не засчитано, сэр: ни одна проверка не подтверждена."


def tg_code(text):
    """Ответ боту во время проверки. (код выхода, ответ): 0 — принят, 1 — не тот,
    2 — проверки сейчас нет (сообщение — обычное, пусть отвечает модель)."""
    nums = "".join(ch if ch.isdigit() else " " for ch in text).split()
    digits = nums[-1] if nums else ""        # «15 × 4 = 60» → 60
    with series_lock():
        d = series_load()
        st = cur_step(d) if d and not d.get("done") else None
        if st is None or st["state"] not in ("check", "ring"):
            return 2, ""
        if not digits or digits.lstrip("0") != st["code"].lstrip("0"):
            due = st["due"] if st["state"] == "check" else st["until"]
            return 1, "Неверно, сэр. Попробуйте ещё раз — до %s." % hmf(d, due)
        was = st["state"]
        confirm(d, "tg")
        series_save(d)
    pre = "ТЕСТ · " if d.get("test") else ""
    what = "Звонок выключен" if was == "ring" else "Принято, сэр"
    if d["done"]:
        return 0, pre + "%s. %s" % (what, done_text(d))
    nxt = cur_step(d)
    return 0, pre + ("%s — но с телефона это только отсрочка. Следующая проверка — в %s; "
                     "закончить можно фразой на ПК." % (what, hmf(d, nxt["check"])))


# — сама серия: окно, звонок, сообщения —

class SeriesRun:
    def __init__(self, d, window=True, sound=True, telegram=True):
        self.d0 = d
        self.window, self.sound, self.telegram = window, sound, telegram
        self.ringer = None
        self.ring_n = None
        self.ov = None
        self.shown = None
        self.can_reply = tg_receivable() if telegram else False
        self.stop_ev = threading.Event()

    # Telegram — в потоках, чтобы окно не ждало сеть
    def tg_async(self, fn, *a):
        if self.telegram:
            threading.Thread(target=fn, args=a, daemon=True).start()

    def tg_check(self, n):
        with series_lock():
            d = series_load()
        if not d:
            return
        st = d["steps"][n]
        if st["state"] not in ("check", "ring"):
            return                       # шаг уже прошёл — запоздалая проверка не нужна
        text = check_text(d, st, self.can_reply)
        r, bot = tg_call("sendMessage", text=text, disable_web_page_preview="true")
        if r:
            with series_lock():
                d = series_load()
                d["steps"][n].update(msg=r["message_id"], msg_text=text, msg_bot=bot)
                series_save(d)

    def tg_note(self, n, note):
        """Дописать к сообщению шага (подтверждено на ПК / не подтверждено)."""
        for _ in range(20):              # сообщение могло ещё не уйти
            with series_lock():
                d = series_load()
            if not d:
                return
            st = d["steps"][n]
            if st.get("msg"):
                tg_call("editMessageText", st.get("msg_bot", "own"), message_id=st["msg"],
                        text=(st.get("msg_text") or "")[:3900] + "\n\n" + note)
                return
            time.sleep(1)

    def tg_send(self, text):
        tg_call("sendMessage", text=text, disable_web_page_preview="true")

    # звонок
    def ring_start(self, st):
        if self.ringer:
            return
        self.ring_n = st["n"]
        with open(PIDF, "w") as f:
            f.write(str(os.getpid()))
        if self.window and not self.d0.get("test"):
            lock_screen()            # фраза — только после пароля (как с 07.10)
        if self.window:
            subprocess.run(["niri", "msg", "action", "power-on-monitors"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.sound:
            self.ringer = Ringer(max(5, st["until"] - time.time()))
            self.ringer.start()
        else:
            self.ringer = "dry"

    def ring_stop(self):
        if not self.ringer:
            return
        if self.ringer != "dry":
            self.ringer.stop()
            self.ringer.thread.join(timeout=5)
            self.ringer.restore()
        self.ringer, self.ring_n = None, None
        try:
            os.remove(PIDF)
        except OSError:
            pass

    def soft_signal(self):
        """Проверка: главное — окно (просьба: «суть не в звуке»), звук тихий и короткий."""
        if self.window:
            subprocess.run(["niri", "msg", "action", "power-on-monitors"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if self.sound:
            subprocess.Popen(["pw-play", "--volume", "0.3", "-P",
                              '{ application.name = "Будильник · проверка" }',
                              "/usr/share/sounds/freedesktop/stereo/message-new-instant.oga"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # окно
    def ui_state(self, d, st):
        ring = st["state"] == "ring"
        # точек не больше пяти: у Сторожа их два десятка
        i0 = max(0, min(st["n"] - 2, len(d["steps"]) - 5))
        lab = [(s["state"], s["hm"]) for s in d["steps"][i0:i0 + 5]]
        kind = st.get("kind")
        if kind == "ctrl":
            head = "КОНТРОЛЬНАЯ ПРОВЕРКА" if not ring else "КОНТРОЛЬ · %s" % st["hm"]
        elif kind == "watch":
            head = ("СТОРОЖ · ПРОВЕРКА %d ИЗ %d" % (st["n"] + 1, len(d["steps"])) if not ring
                    else "СТОРОЖ · ЗВОНОК")
        elif st["n"] == 0:
            head = "ПРОВЕРКА ПЕРЕД БУДИЛЬНИКОМ" if not ring else "БУДИЛЬНИК · %s" % st["hm"]
        else:
            of = "" if st["n"] > REPEATS else " ИЗ %d" % REPEATS
            head = ("ПРОВЕРКА · ПОВТОР %d%s" % (st["n"], of) if not ring
                    else "ПОВТОР %d%s · %s" % (st["n"], of, st["hm"]))
        if d.get("test"):
            head = "ТЕСТ · " + head
        if ring and kind:
            title = "Не спать, сэр. Наберите фразу — звонок замолчит."
            sub = "раскладку переключайте сами"
        elif ring:
            title = "Доброе утро, сэр. Наберите фразу — звонок замолчит."
            sub = "раскладку переключайте сами"
        else:
            title = "Не спите, сэр? Наберите фразу."
            sub = ("подтвердите, что не спите: звонок в %s не прозвучит" % hmf(d, st["due"])
                   if st["n"] == 0 or kind else "подтвердите, что не спите: повтор в %s не прозвучит" % st["hm"])
        tg = ("ответ в Telegram — только отсрочка на %d минут" % TG_SNOOZE if self.can_reply else
              "Telegram сейчас не принимает ответ (бот не принимает ответы) — только здесь")
        last = st is d["steps"][-1]
        tail = ("потом звонок" if not ring else
                "звонок сдастся сам" if last else "до следующей проверки")
        return dict(mode="ring" if ring else "check", key=str(st["n"]), tail=tail,
                    phrase=st["phrase"], head=head, title=title, sub=sub, steps=lab,
                    cur=st["n"] - i0, until=st["until"] if ring else st["due"], tg=tg)

    def on_typed(self):
        with series_lock():
            d = series_load()
            st = confirm(d, "pc")
            series_save(d)
        if st is None:
            return
        self.tg_async(self.tg_note, st["n"], "✓ Подтверждено на ПК в %s" % hmf(d, time.time()))
        if d["done"]:
            self.tg_async(self.tg_send, ("ТЕСТ · " if d.get("test") else "") + done_text(d))
        self.step()

    # такт
    def step(self):
        now = time.time()
        with series_lock():
            d = series_load()
            if d is None or d.get("pid") != self.d0.get("pid"):
                self.stop_ev.set()       # серию заменили (новый тест) или стёрли
                d, ev = None, []
            else:
                ev = advance(d, now)
                series_save(d)
        for kind, st in ev:
            if kind == "check":
                slog("шаг %d: проверка" % st["n"])
                self.soft_signal()
                self.tg_async(self.tg_check, st["n"])
            elif kind == "ring":
                slog("шаг %d: звонок" % st["n"])
                if self.can_reply:
                    self.tg_async(self.tg_send, ("ТЕСТ · " if d.get("test") else "") +
                                  "🔔 Звонит будильник (%s). Выключить — ответ на тот же пример: %s = ?" % (
                                      st["hm"], st.get("task", "")))
            elif kind == "fail":
                self.tg_async(self.tg_note, st["n"], "✗ Не подтверждено")
            elif kind == "done":
                self.tg_async(self.tg_send, ("ТЕСТ · " if d.get("test") else "") + done_text(d))
        cur = cur_step(d) if d and not d.get("done") else None
        # звонок: идёт ровно пока текущий шаг в состоянии ring
        if self.ringer and not (cur and cur["state"] == "ring" and cur["n"] == self.ring_n):
            self.ring_stop()
        if cur and cur["state"] == "ring" and not self.ringer:
            self.ring_start(cur)
        # окно
        if self.window:
            try:
                if cur and cur["state"] in ("check", "ring"):
                    self.ov.show(self.ui_state(d, cur))
                elif self.ov.wins:
                    self.ov.hide()
            except Exception as e:      # без окна серия идёт дальше: звук и Telegram
                slog("окно не открылось, дальше без него: %r" % e)
                self.window = False
        if d is None or d.get("done"):
            self.stop_ev.set()
        return not self.stop_ev.is_set()

    def run(self):
        with open(PIDF + ".series", "w") as f:
            f.write(str(os.getpid()))

        def term(*_a):
            self.stop_ev.set()
            if self.window:
                from gi.repository import GLib, Gtk
                GLib.idle_add(Gtk.main_quit)
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, term)
            signal.signal(signal.SIGINT, term)
        try:
            if self.window:
                import wake_overlay
                from gi.repository import GLib, Gtk
                self.ov = wake_overlay.Overlay(self.on_typed)

                def tick():
                    try:
                        if self.step():
                            return True
                    except Exception as e:      # иначе такт молча снимается, а Gtk.main висит
                        slog("такт упал: %r" % e)
                    Gtk.main_quit()
                    return False
                if tick():
                    GLib.timeout_add(250, tick)
                    Gtk.main()
                self.ov.hide()
            else:
                while self.step():
                    self.stop_ev.wait(0.25)
        finally:
            self.ring_stop()
            try:
                os.remove(PIDF + ".series")
            except OSError:
                pass
        time.sleep(2)                    # дать уйти последним сообщениям


def series_pid_alive():
    try:
        os.kill(int(open(PIDF + ".series").read()), 0)
        return True
    except (OSError, ValueError):
        return False


def run_series(d, **kw):
    d["pid"] = os.getpid()
    with series_lock():
        series_save(d)
    slog("серия %s %s%s: старт" % (d["date"], d["t"], " (тест)" if d.get("test") else ""))
    SeriesRun(d, **kw).run()
    d = series_load() or d
    slog("серия окончена: %s" % d.get("result"))


# ── команды ───────────────────────────────────────────────────────────────────

def cmd_check():
    now = time.time()
    with series_lock():
        d = series_load()
    if d and not d.get("done") and not d.get("test"):
        if series_pid_alive():
            return
        if now < d["steps"][-1]["until"]:      # служба упала посреди серии — продолжить
            slog("серия %s: продолжаю после сбоя" % d["date"])
            run_series(d)
            return
    s = load()
    today = dt.date.today()
    # завтра — для звонка около полуночи: проверка в 23:57 ещё «сегодня»
    for day in (today, today + dt.timedelta(days=1)):
        t = alarm_on(s, day)
        if t is None or last_rung() == day.isoformat() or day.isoformat() in s.get("watch", {}):
            continue          # в день Сторожа на дату утреннего звонка нет — его проверки и есть будильник
        T = t.timestamp()
        if not (T - PRE * 60 <= now < T + LATE_OK):
            continue
        os.makedirs(os.path.dirname(LAST), exist_ok=True)
        with open(LAST, "w") as f:
            f.write(day.isoformat())
        # план этого дня — в строку плана: в прошлом рядом с фактом подъёма видно, каким
        # он был (время «по умолчанию» могут потом поменять)
        if day.isoformat() not in s["plan"]:
            s["plan"][day.isoformat()] = t.strftime("%H:%M")
            save(s)
        if awake_at_pc(now):          # вы за ПК — не спите, звонить незачем; подъём засчитан
            if not woke_load().get(day.isoformat()):
                woke_set(day, time.strftime("%H:%M"))
                via_set(day.isoformat(), "pc")
            slog("звонок %s %s: вы за ПК — без проверок" % (day.isoformat(), t.strftime("%H:%M")))
            return
        run_series(series_build(t))
        return
    w = watch_for(s, today)
    if not w:
        return
    if d and d.get("watch") and d["date"] == today.isoformat() and d.get("result") != "stopped":
        return                # сегодняшний Сторож уже отработал (остановленного — после включения заново)
    if w["daily"]:            # ежедневная — после утренней серии: звонок сегодня ещё впереди — ждать
        t = alarm_on(s, today)
        if t is not None and last_rung() != today.isoformat() and now < t.timestamp() + LATE_OK:
            return
    t0, t1 = hm_min(w["from"]), hm_min(w["to"])
    sec = now - dt.datetime.combine(today, dt.time()).timestamp()
    if not t0 * 60 <= sec < t1 * 60 + 60:
        return
    d = watch_build(today, t0, t1, int(w.get("every", WATCH_EVERY)))
    if sec > t0 * 60 + 120:   # начали позже (после утра, после включения) — первая через шаг, не сразу
        for st in d["steps"]:
            if st["state"] == "wait" and st["check"] < now:
                st.update(state="off", skip="late")
    if cur_step(d) is None:
        return
    run_series(d)


def hm_min(hm):
    h, m = check_hm(hm).split(":")
    return int(h) * 60 + int(m)


def series_locked_day(day, argv):
    """Во время серии сегодняшний день не меняется (иначе её можно сорвать из кровати)."""
    d = series_load()
    if "--force" in argv or not series_locks(d) or (day and day.isoformat() != d["date"]):
        return False
    print("Идёт %s — этот день сейчас менять нельзя, сэр. "
          "Закончить её можно только фразой на ПК (ответ в Telegram — лишь отсрочка)."
          % ("проверка Сторожа" if d.get("watch") else "утренняя проверка (%s)" % d["t"]))
    return True


def cmd_status():
    s = load()
    print("будильник:", "включён" if s["enabled"] else "ВЫКЛЮЧЕН")
    t = next_alarm(s)
    print("ближайший звонок:", t.strftime("%a %d.%m %H:%M") if t else "нет")
    print("по умолчанию:", s["default"])
    today = dt.date.today()
    for i in range(0, 5):
        d = today + dt.timedelta(days=i)
        a = alarm_on(s, d)
        w = watch_for(s, d)
        print("  %s  %-6s %s" % (d.strftime("%d.%m %a"), a.strftime("%H:%M") if a else "—",
              "Сторож %s–%s, каждые %s мин%s" % (w["from"], w["to"], w["every"],
                                               "" if w["daily"] else " (на дату)") if w
              else "без Сторожа"))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    s = load()
    if cmd == "check":
        recover_speaker()
        try:
            rtc_plan_write()
        except Exception as e:
            print("план пробуждения не записан: %s" % e, file=sys.stderr)
        cmd_check()
    elif cmd == "rtc":
        return cmd_rtc(check=len(argv) > 2 and argv[2] == "check")
    elif cmd == "rtc-test":
        return cmd_rtc_test(int(argv[2]) if len(argv) > 2 else 60)
    elif cmd == "status":
        cmd_status()
    elif cmd == "set":
        hm = check_hm(argv[2])
        day = parse_day(argv[3] if len(argv) > 3 and argv[3] != "--force" else None, s)
        if series_locked_day(day, argv):
            return 1
        s["plan"][day.isoformat()] = hm
        if day.isoformat() in s["skip"]:
            s["skip"].remove(day.isoformat())
        save(s)
        print("%s — %s" % (day.strftime("%d.%m"), hm))
    elif cmd == "default":
        s["default"] = check_hm(argv[2])
        save(s)
        print("по умолчанию:", s["default"])
    elif cmd == "skip":
        day = parse_day(argv[2] if len(argv) > 2 and argv[2] != "--force" else None, s)
        if series_locked_day(day, argv):
            return 1
        if day.isoformat() not in s["skip"]:
            s["skip"].append(day.isoformat())
        save(s)
        print("%s — без звонка" % day.strftime("%d.%m"))
    elif cmd in ("on", "off"):
        if cmd == "off" and series_locked_day(None, argv):
            return 1
        s["enabled"] = cmd == "on"
        save(s)
        # 13.10.2026: аварийное выключение из Telegram (/alarm) — в журнал, как Сторож
        if "--reason" in argv or "--via" in argv:
            opt = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else ""
            watch_log("alarm-" + cmd, opt("--reason"), opt("--via") or "cli")
        cmd_status()
    elif cmd == "emergency":
        # 13.10.2026, просьба: «аварийное выключение через бота должно выключать и Сторожа на
        # этот день. Если я его выключаю — значит, я не дома». Поэтому — и во время серии:
        # будильник выключается до /alarm on, Сторож снимается на сегодня, идущая серия
        # (проверка, звонок) останавливается. Без причины не выполняется.
        sub = argv[2] if len(argv) > 2 else ""
        opt = lambda k: argv[argv.index(k) + 1] if k in argv and argv.index(k) + 1 < len(argv) else ""
        reason, via = opt("--reason").strip(), opt("--via") or "cli"
        today = dt.date.today().isoformat()
        if sub == "off":
            if len(reason) < 3:
                print("Без причины не выключаю, сэр: --reason «почему»")
                return 2
            s["enabled"] = False
            sk = s.setdefault("watch_skip", [])
            if today not in sk:
                sk.append(today)
            save(s)
            watch_log("emergency-off", reason, via, today)
            with series_lock():
                d = series_load()
                if d and not d.get("done") and not d.get("test") and d["date"] == today:
                    finish(d, "stopped")
                    series_save(d)
                    slog("серия остановлена аварийно (%s): %s" % (via, reason))
                    print("идущая серия остановлена")   # процесс серии увидит done и закроется
            print("будильник ВЫКЛЮЧЕН до включения, Сторож снят на сегодня")
        elif sub == "on":
            s["enabled"] = True
            if today in s.get("watch_skip", []):
                s["watch_skip"].remove(today)
            save(s)
            watch_log("emergency-on", reason, via, today)
            print("будильник включён, Сторож сегодня снова на посту")
        else:
            print("emergency off --reason ТЕКСТ [--via tg] | emergency on [--via tg]")
            return 2
        cmd_status()
        return 0
    elif cmd == "test":
        ring(int(argv[2]) if len(argv) > 2 else 10,
             window="--no-window" not in argv)
    elif cmd == "sound":
        # wake-alarm sound [t3|classic] — какой звук звонка
        if len(argv) > 2:
            if argv[2] not in SOUNDS:
                print("звуки: " + ", ".join(SOUNDS))
                return 2
            s["sound"] = argv[2]
            save(s)
        print("звук: %s (%s)" % (s.get("sound", "t3"), sound_file()))
    elif cmd == "woke":
        # wake-alarm woke [ЧЧ:ММ|-] [ДАТА] — записать подъём вручную (встал до звонка)
        hm = argv[2] if len(argv) > 2 else time.strftime("%H:%M")
        day = parse_day(argv[3], s) if len(argv) > 3 else dt.date.today()
        woke_set(day, None if hm == "-" else check_hm(hm))
        print("%s — встал %s" % (day.strftime("%d.%m"), hm))
    elif cmd == "stop":
        if series_locked_day(None, argv):
            return 1
        if "--force" in argv:
            with series_lock():
                d = series_load()
                if d and not d.get("done"):
                    finish(d, "stopped")
                    series_save(d)
                    slog("серия остановлена вручную (stop --force)")
                    print("серия остановлена")
            return 0
        try:
            os.kill(int(open(PIDF).read()), signal.SIGTERM)
            print("остановлен")
        except (OSError, ValueError):
            print("не звонит")
    elif cmd == "watch":
        # wake-alarm watch [ДАТА] 07:00-21:00 [МИН] | watch off [ДАТА] [--force] | watch
        args, reason, via, with_alarm = [], "", "cli", False
        it = iter(argv[2:])
        for a in it:
            if a == "--with-alarm":       # 27.10.2026: skip Сторожа заодно снимает/возвращает звонок дня
                with_alarm = True
            elif a == "--reason":
                reason = next(it, "").strip()
            elif a == "--via":
                via = next(it, "cli")
            elif a != "--force":
                args.append(a)
        ws = s.setdefault("watch", {})
        wd = s["watch_daily"]
        if args and args[0] == "daily":
            if len(args) == 1:
                print("ежедневный Сторож: %s, от будильника до %s, каждые %s мин" % (
                    "включён" if wd.get("enabled") else "ВЫКЛЮЧЕН",
                    wd["to"], wd.get("every", WATCH_EVERY)))
                return 0
            if args[1] == "on":
                if not wd.get("enabled"):
                    wd["enabled"] = True
                    save(s)
                    watch_log("daily-on", reason, via)
                print("ежедневный Сторож включён")
                return 0
            if args[1] == "off":
                if not reason:
                    print("Без причины Сторож не выключается, сэр: --reason «почему»")
                    return 2
                if watch_busy():
                    print("Сейчас идёт проверка Сторожа — сначала ответьте на неё, сэр.")
                    return 1
                if wd.get("enabled"):
                    wd["enabled"] = False
                    save(s)
                    watch_log("daily-off", reason, via)
                    if not watch_for(s, dt.date.today()):
                        watch_stop_today("выключена насовсем")
                print("ежедневный Сторож выключен — до включения")
                return 0
            if len(args) in (2, 3) and "-" in args[1]:     # watch daily 06:00-21:00 [МИН]
                a, _, b = args[1].partition("-")
                every = int(args[2]) if len(args) > 2 else wd.get("every", WATCH_EVERY)
                if hm_min(b) <= hm_min(a) or not 10 <= every <= 180:
                    print("Сторож: ЧЧ:ММ-ЧЧ:ММ в пределах суток, шаг 10–180 мин")
                    return 2
                wd.update({"from": check_hm(a), "to": check_hm(b), "every": every})
                save(s)
                print("ежедневный Сторож: от будильника до %s, каждые %d мин (начало — время звонка)"
                      % (wd["to"], every))
                return 0
            print("watch daily [on | off --reason ТЕКСТ | 06:00-21:00 [МИН]]")
            return 2
        if args and args[0] == "skip":
            off = len(args) > 1 and args[1] == "off"
            rest = args[2:] if off else args[1:]
            day = parse_day(rest[0], s) if rest else dt.date.today()
            sk = s.setdefault("watch_skip", [])
            if off:
                if day.isoformat() in sk:
                    sk.remove(day.isoformat())
                    save(s)
                    watch_log("skip-off", reason, via, day.isoformat())
                if with_alarm and day.isoformat() in s["skip"]:
                    s["skip"].remove(day.isoformat())
                    save(s)
                print("%s — Сторож снова на посту%s" % (day.strftime("%d.%m"),
                                                        " и будильник тоже" if with_alarm else ""))
                return 0
            if not reason:
                print("Без причины Сторож не выключается, сэр: --reason «почему»")
                return 2
            if day == dt.date.today() and watch_busy():
                print("Сейчас идёт проверка Сторожа — сначала ответьте на неё, сэр.")
                return 1
            if with_alarm and series_locked_day(day, argv):     # утренняя серия идёт — не снимать
                return 1
            if with_alarm and day.isoformat() not in s["skip"]:
                s["skip"].append(day.isoformat())
                save(s)
            if day.isoformat() not in sk:
                sk.append(day.isoformat())
                cut = (dt.date.today() - dt.timedelta(days=30)).isoformat()
                s["watch_skip"] = [x for x in sk if x >= cut]
                save(s)
                watch_log("skip", reason, via, day.isoformat())
            if day == dt.date.today() and not watch_for(s, day):
                watch_stop_today("выключена на день")
            print("%s — без Сторожа%s" % (day.strftime("%d.%m"), " и без будильника" if with_alarm else ""))
            return 0
        if args and args[0] == "log":
            rows = watch_log_read(int(args[1]) if len(args) > 1 else 50)
            for r in rows:
                print(watch_log_line(r))
            if not rows:
                print("выключений Сторожа не было")
            return 0
        if not args:
            print("ежедневный Сторож: %s, от будильника до %s, каждые %s мин" % (
                "включён" if wd.get("enabled") else "выключен", wd["to"],
                wd.get("every", WATCH_EVERY)))
            if s.get("watch_skip"):
                print("без Сторожа:", ", ".join(sorted(s["watch_skip"])))
            for k_, w in sorted(ws.items()):
                print("%s  %s–%s, каждые %s мин" % (k_, w["from"], w["to"], w.get("every", WATCH_EVERY)))
            if not ws:
                print("Сторожей на даты нет")
            return 0
        if args[0] == "off":
            day = parse_day(args[1], s) if len(args) > 1 else dt.date.today()
            if series_locked_day(day, argv):
                return 1
            ws.pop(day.isoformat(), None)
            save(s)
            if day == dt.date.today() and not watch_for(s, day):
                watch_stop_today("Сторож на дату снят")
            print("%s — Сторож на дату снят" % day.strftime("%d.%m"))
            return 0
        day = dt.date.today()
        if ":" not in args[0]:                 # первым — дата (2026-10-09 / завтра)
            day = parse_day(args[0], s)
            args = args[1:]
        a, _, b = args[0].partition("-")
        every = int(args[1]) if len(args) > 1 else WATCH_EVERY
        if hm_min(b) <= hm_min(a) or not 10 <= every <= 180:
            print("Сторож: ЧЧ:ММ-ЧЧ:ММ в пределах суток, шаг 10–180 мин")
            return 2
        if series_locked_day(day, argv):
            return 1
        ws[day.isoformat()] = {"from": check_hm(a), "to": check_hm(b), "every": every}
        cut = (dt.date.today() - dt.timedelta(days=30)).isoformat()
        s["watch"] = {k_: v for k_, v in ws.items() if k_ >= cut}
        save(s)
        n = (hm_min(b) - hm_min(a)) // every + 1
        print("%s — Сторож %s–%s, каждые %d мин (%d проверок); утреннего звонка в этот день нет"
              % (day.strftime("%d.%m"), check_hm(a), check_hm(b), every, n))
    elif cmd == "tg-code":
        # зовёт мост бота: ответ владельца во время проверки → код выхода 0/1/2 и текст
        code, text = tg_code(" ".join(argv[2:]))
        if text:
            print(text)
        return code
    elif cmd == "test-series":
        # wake-alarm test-series [СЕКУНД_В_МИНУТЕ=12] [--dry] — вся серия в ускоренном виде
        args = [a for a in argv[2:] if not a.startswith("--")]
        k = int(args[0]) if args else 12
        dry = "--dry" in argv
        if series_active():
            print("сейчас идёт настоящая утренняя проверка")
            return 1
        t = dt.datetime.now().replace(microsecond=0) + dt.timedelta(seconds=PRE * k)
        run_series(series_build(t, test=True, k=k),
                   window=not dry, sound=not dry, telegram=not dry)
        print(done_text(series_load() or {}))
    elif cmd == "series":
        # состояние серии одной строкой на шаг (для проверок)
        d = series_load()
        if not d:
            print("серий не было")
            return 0
        print("%s %s%s — %s, подряд %d" % (d["date"], d["t"], " ТЕСТ" if d.get("test") else "",
              d.get("result") or "идёт", d.get("streak", 0)))
        for st in d["steps"]:
            print("  %d  проверка %s  звонок %s  %-5s %s" % (
                st["n"], hmf(d, st["check"]), st["hm"], st["state"], st.get("via", "")))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
