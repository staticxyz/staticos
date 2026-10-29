#!/usr/bin/env python3
"""hubd — демон hub: срабатывание напоминаний, эскалация ПК → Telegram, дайджест, таймеры.

Работает без ИИ и без `server`. Telegram включается сам, когда появляется токен
(~/.config/hub/env) и owner (config.json). Без них — только ПК.
Опрос раз в 2 с; после сна просроченное выходит одной пачкой."""
import datetime as dt
import glob
import json
import os
import signal
import subprocess
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~/.config/hypr/scripts"))
import hublib as H  # noqa: E402
import hubtg as T  # noqa: E402
import growth as G  # noqa: E402
import hubguard  # noqa: E402
import hubwa  # noqa: E402
import session_env  # noqa: E402

TICK = 2
DEFAULT_ESC_MIN = 5                  # 14.10.2026: не тронул уведомление 5 мин — в Telegram
DIGEST_HOUR, DIGEST_MIN = 9, 30
DIGEST_ON = False                  # утренняя сводка выключена (19.10.2026)
NAG_DAYS = [3, 7, 14, 30]            # ступени «запылился» для пунктов без срока
RING_MAX = 60                        # 23.10.2026, просьба: звенеть минуту (было 5), дальше висит уведомление
SOUND = "/usr/share/sounds/freedesktop/stereo/complete.oga"
INPUT_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "jarvis-input")

stop = threading.Event()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def locked():
    return hubguard.locked()


RUN_DIR = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
SCREENS_OFF = os.path.join(RUN_DIR, "jarvis-screens-off.json")    # «Погасить» в боте (idle_dim off)
SCREEN_DIM = os.path.expanduser("~/.cache/screen-dim")             # приглушение по простою (screen_gamma)
WOKE = {"at": 0}                     # плановое пробуждение (RTC): до первого ввода после него — вас нет


def screen_away():
    """Почему экран ПК сейчас никто не смотрит, или None. 21.10.2026, просьба: «уберём нажатия
    с логики уведомлений. Будет считаться, что я за ПК, если на экране нет заставки или экрана
    блокировки, или же любые затемнения»."""
    if hubguard.locked():
        return "блокировка"
    try:
        out = subprocess.run(["niri", "msg", "-j", "layers"], capture_output=True, text=True, timeout=2).stdout
        if '"jarvis-screensaver"' in out:
            return "заставка"
        if '"hyprlock"' in out or '"jarvis-lock' in out:
            return "блокировка"
    except (OSError, subprocess.SubprocessError):
        pass
    if os.path.exists(SCREENS_OFF):
        return "экраны погашены"
    try:
        if open(SCREEN_DIM).read().strip() in ("soft", "deep"):
            return "затемнение"
    except OSError:
        pass
    return None


def input_since(t):
    """Был ли ввод (клавиши, мышь) после t — по jarvis-input от hypridle."""
    try:
        state, ts = open(INPUT_FILE).read().split()
        return state == "active" and int(ts) > t
    except (OSError, ValueError):
        return False


def pc_present():
    """За ПК ли пользователь: на экране нет заставки, блокировки, затемнения и экраны не погашены.
    Иначе — только телефон, без звука и уведомления на ПК. После планового пробуждения (часы
    разбудили ПК ради будильника или напоминания) — нет, пока не тронули клавиатуру или мышь:
    перед сном экран запирается (before_sleep_cmd), но если блокировка не встала, напоминание
    всё равно уйдёт в Telegram."""
    if WOKE["at"]:
        if not input_since(WOKE["at"]):
            return False
        WOKE["at"] = 0
    return screen_away() is None


_mean_db = {}


def mean_db(path):
    """Средняя громкость файла, дБ (ffmpeg volumedetect); помнится по пути и mtime."""
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _mean_db:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-af",
                                  "volumedetect", "-f", "null", "-"],
                                 capture_output=True, text=True, timeout=10).stderr
            m = [ln for ln in out.splitlines() if "mean_volume:" in ln]
            _mean_db[key] = float(m[0].split("mean_volume:")[1].split()[0]) if m else None
        except (OSError, subprocess.SubprocessError, ValueError):
            _mean_db[key] = None
    return _mean_db[key]


def chime_volume():
    """Громкость звонка напоминания — вдвое громче обычного уведомления (14.10.2026, просьба: «сделай им звук х2 громче обычных»). Обычное — ui_sound: свой файл пакета
    на notify-volume в кубе. Файлы разной громкости (complete.oga на ~10 дБ громче
    XP Balloon), поэтому поправка на разницу средних громкостей. Не вышло — 0.3, как было."""
    try:
        import ui_sound
        ref = ui_sound.sound_file("notify")
        amp = (ui_sound.get_notify_volume() / 100) ** 3
        a, b = mean_db(ref) if ref else None, mean_db(SOUND)
        if a is None or b is None:
            return 0.3
        return max(0.0, min(1.0, 2 * amp * 10 ** ((a - b) / 20)))
    except Exception:
        return 0.3


def chime():
    """Один звонок напоминания: громкость — chime_volume(). 13.10.2026: напоминания
    приходили молча — общий звук уведомлений (ui_sound_watch) в кубе был ~3 %, не слышно.
    Теперь hub звенит сам, а сторож hub пропускает."""
    try:
        subprocess.Popen(["timeout", "8", "pw-play", "--volume", "%.4f" % chime_volume(), SOUND],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:
        pass


# Висящие (critical) уведомления на экране: ключ → {nid, again}. 14.10.2026, просьба:
# «повисшее уведомление должно остаться висеть даже при переключениях не беспокоить».
# swaync 0.12.6 при включении DND прячет все всплывающие, critical тоже, и обратно их не
# показывает (живут только в центре). Поэтому при смене DND hub закрывает своё и
# показывает его заново: новое critical swaync показывает и при DND. Заменить по id
# (replaces_id) нельзя — у спрятанного swaync оставлял «призрак» рядом с новым.
shown = {}
shown_lock = threading.Lock()
_dnd = {"last": None}
# 19.10.2026: призраки. Карточку, которую спрятал DND, CloseNotification убирает из списка
# swaync, но скрытый виджет остаётся в окне всплывающих и вылезает со следующим уведомлением —
# мёртвый, кнопки не работают (воспроизведено: показать → DND вкл → закрыть → новое).
# Повторный Close его не берёт, берёт только `swaync-client --hide-all`. Поэтому после такого
# закрытия: hide-all, и живые карточки hub показываются заново (purge_ghosts).
_purge_lock = threading.Lock()
# Двойной щелчок: первая карточка закрылась, под курсор въехала соседняя — второй щелчок
# нажимал её кнопку (19.10 09:15:30 так отложились два напоминания разом). Нажатие на другой
# карточке быстрее DOUBLE_GUARD с после предыдущего — не ответ: карточка показывается снова.
DOUBLE_GUARD = 0.6
_last_press = {"t": 0.0, "nid": None}


def notify(title, body, iid, critical=False, timer=False, again=False, rep=False, group=None):
    """Уведомление на ПК. notify-send -A ждёт реакции в потоке: кнопка или закрытие = «увидел».
    again — показ заново после смены DND: без звонка, реакция та же. rep — повторяющееся:
    кнопки «Отметить» (срок → следующий раз) и «Закрыть цикл» (14.10.2026). group — сводка
    «На сегодня» (allday_fire): номера её пунктов, кнопка «Открыть список»."""
    hold = critical and not timer and not again   # напоминание/сводка: в DND ждёт (hublib.dnd_wait)
    if not timer and not again and not hold:
        chime()                                    # у таймера свой звонок — ring()
    def work():
        if hold:
            if H.dnd_wait(stop) and iid:          # пока ждали, могли закрыть в Telegram
                c = H.connect()
                it = H.get_item(c, iid)
                c.close()
                if it is None or it["status"] != "open" or it["seen"]:
                    return
            if stop.is_set():
                return
            chime()
        cmd = ["notify-send", "-a", "hub", "-u", "critical" if critical else "normal", "-p"]
        if group:                                   # сводка «На сегодня»: щелчок или кнопка — окно hub
            cmd += ["-A", "default=Открыть", "-A", "open=☰ Открыть список"]
        elif iid:                                   # у сводки (iid 0) пункта нет — и кнопок тоже
            # 15.10.2026, просьба: «не будем вообще ничего удалять… если я закрою уведомление,
            # это и будет Скрыть». У напоминания две кнопки: «Сделано» (→ «Выполненные»;
            # у повторяющегося — срок на следующий раз) и «+1 час»; закрыть = скрыть.
            # «■ Стоп» остался только у таймера. У таймера «Сделано» убрано (21.10.2026, просьба:
            # «как будто дубль») — то же, что «Стоп»: звонок молкнет, выполненные таймеры нигде
            # не видны. Как в Telegram: «■ Стоп» и отсрочка.
            if timer:
                cmd += ["-A", "stop=■ Стоп", "-A", "later=+1 час"]
            else:
                cmd += ["-A", "done=✓ Отметить" if rep else "done=✓ Сделано", "-A", "later=+1 час"]
        cmd += ["-w", title, body]
        entry, key = {"nid": None, "again": False, "iid": iid, "group": group}, object()
        try:
            p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, text=True)
            first = p.stdout.readline().strip()     # -p: сперва номер уведомления
            entry["nid"] = int(first) if first.isdigit() else None
            if critical and entry["nid"]:
                with shown_lock:
                    shown[key] = entry
            act = p.stdout.read().strip()           # потом — нажатая кнопка (или пусто)
            p.wait()
        except Exception:
            return
        finally:
            with shown_lock:
                shown.pop(key, None)
        if stop.is_set() or entry.get("gone"):     # hub останавливается / убрал сам — это не ответ
            return
        if entry["again"]:                          # закрыл сам hub — показать снова
            gate = entry.get("gate")
            if gate is not None:
                gate.wait(5)                        # сперва hide-all убирает призраков
            notify(title, body, iid, critical, timer, again=True, rep=rep, group=group)
            return
        if group:                                   # закрыл или открыл — увидел все пункты сводки
            c = H.connect()
            for i in group:
                H.mark_seen(c, i)
            c.close()
            if act in ("open", "default"):
                subprocess.Popen([os.path.expanduser("~/.local/bin/hub-open"), "items"], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            return
        if not iid:
            return
        if act in ("done", "later", "stop"):
            t = time.monotonic()
            prev, _last_press["t"], _last_press["nid"] = dict(_last_press), t, entry["nid"]
            if t - prev["t"] < DOUBLE_GUARD and prev["nid"] != entry["nid"]:
                log("двойной щелчок — не ответ, показываю снова:", iid)
                if entry["nid"]:
                    close_nid(entry["nid"])
                    if dnd_on():
                        purge_ghosts()
                notify(title, body, iid, critical, timer, again=True, rep=rep)
                return
        c = H.connect()
        if act in ("done", "later", "stop"):
            pressed(title, body, entry["nid"], act, rep, timer)
        if act == "done":
            H.done(c, iid, "pc")
        elif act == "later":
            H.snooze(c, iid, 3600, source="pc")
        elif timer:
            H.drop(c, iid, "pc")                   # закрыл уведомление таймера = стоп
        # Напоминание из уведомления не удаляется никогда (15.10.2026: «■ Стоп» = drop
        # стёр три задачи — 74, 82, 85, возвращены). Закрыли — только «увидел».
        H.mark_seen(c, iid)                        # закрыл или нажал — эскалации в TG не будет
        c.close()
    threading.Thread(target=work, daemon=True).start()


def pressed(title, body, nid, act, rep=False, timer=False):
    """Кнопку нажали — в центре уведомлений вместо карточки с кнопками остаётся запись
    «что и какая кнопка» (14.10.2026, просьба: «если я уже нажал на один из вариантов, в
    центре не показывать кнопки, просто напоминание, название и какая кнопка нажата»).
    Сама карточка swaync после нажатия не уходит — закрываем её по номеру. Запись идёт
    от имени hub-log: правило swaync (config.json, notification-visibility, muted) кладёт
    её в центр без всплывания; ui_sound_watch hub-log не озвучивает."""
    label = {"done": "✓ Отмечено, срок — на следующий раз" if rep else "✓ Сделано",
             "later": "+1 час",
             "stop": "■ Стоп"}[act]
    try:
        if nid:
            close_nid(nid)
            if dnd_on():                            # закрыта спрятанная DND — убрать призрака
                purge_ghosts()
        subprocess.run(["notify-send", "-a", "hub-log", "-u", "normal", title,
                        "%s\n— нажато: %s" % (body, label)],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.SubprocessError):
        pass


def close_nid(nid):
    subprocess.run(["gdbus", "call", "--session", "--dest", "org.freedesktop.Notifications",
                    "--object-path", "/org/freedesktop/Notifications", "--method",
                    "org.freedesktop.Notifications.CloseNotification", str(nid)],
                   capture_output=True, timeout=5)


def dnd_on():
    try:
        return subprocess.run(["swaync-client", "-D"], capture_output=True, text=True,
                              timeout=3).stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def purge_ghosts(items=None):
    """Убрать призраков: живые карточки hub закрыть, `swaync-client --hide-all` (уносит и
    скрытые виджеты; уведомления остаются в центре), потом живые показываются заново
    (worker ждёт gate). items — уже помеченные again (из dnd_watch)."""
    with _purge_lock:
        if items is None:
            with shown_lock:
                items = [e for e in shown.values() if not e.get("gone")]
            for e in items:
                e["again"] = True
                e["gate"] = threading.Event()
                close_nid(e["nid"])
        try:
            subprocess.run(["swaync-client", "--hide-all"], capture_output=True, timeout=3)
        except (OSError, subprocess.SubprocessError):
            pass
        for e in items:
            if e.get("gate") is not None:
                e["gate"].set()


def unshow_all(c):
    """При остановке hub: висящие убрать с экрана (без hub их кнопки ничего не делают — был
    «мёртвый» двойник), а пункты пометить несработавшими — новый hub покажет их снова."""
    with shown_lock:
        items = list(shown.values())
    for e in items:
        try:
            close_nid(e["nid"])
            for i in ([e["iid"]] if e["iid"] else []) + list(e.get("group") or []):
                c.execute("UPDATE items SET fired_pc=NULL WHERE id=? AND status='open'", (i,))
        except Exception:
            pass
    if items:
        log("убрал висящие при остановке:", len(items))


def close_stale(c):
    """Пункт остановили не с этого уведомления (Telegram, щелчок по виджету-таймеру) или
    отложили («+5 мин») — висящее уведомление убрать. 14.10.2026: таймеры виджетов теперь
    живут в hub, щелчок по виджету гасит звонок — карточка не должна висеть дальше."""
    with shown_lock:
        items = list(shown.values())
    for e in items:
        if e.get("group") and not e.get("gone"):
            if not any((H.get_item(c, i) or {"status": ""})["status"] == "open" for i in e["group"]):
                e["gone"] = True
                close_nid(e["nid"])
            continue
        if not e["iid"] or e.get("gone"):
            continue
        it = H.get_item(c, e["iid"])
        if it is None or it["status"] != "open" or (it["due"] or 0) > H.now():
            e["gone"] = True
            close_nid(e["nid"])
            if dnd_on():
                purge_ghosts()


# Своя блокировка — отсрочка (23.10.2026, просьба: «пусть это сообщение выведется в тг не сразу,
# как только я заблокировал экран, а примерно через 3.5 минуты… если по времени — как обычно»).
# Блокировку по простою (idle_lock) и из бота (/pc lock) отмечает файл LOCK_AUTO перед
# loginctl lock-session; нет свежей отметки — запер сам пользователь, таймер ждёт MANUAL_LOCK_GRACE.
LOCK_AUTO = os.path.join(RUN_DIR, "jarvis-lock-auto")
MANUAL_LOCK_GRACE = 210
LOCK_AT = {"t": 0.0, "auto": False}


def lock_track():
    """Когда встала блокировка и сама ли (простой, бот). Зовётся каждый тик."""
    if not locked():
        LOCK_AT["t"] = 0.0
        return
    if LOCK_AT["t"]:
        return
    now = time.time()
    LOCK_AT["t"] = now
    try:
        LOCK_AT["auto"] = now - os.path.getmtime(LOCK_AUTO) < 60
    except OSError:
        LOCK_AT["auto"] = False
    log("блокировка:", "по простою/из бота" if LOCK_AT["auto"] else "своя — таймер в Telegram через %d с"
        % MANUAL_LOCK_GRACE)


def manual_lock_grace():
    """Своя блокировка моложе MANUAL_LOCK_GRACE — пользователь, скорее всего, рядом."""
    return bool(LOCK_AT["t"]) and not LOCK_AT["auto"] and time.time() - LOCK_AT["t"] < MANUAL_LOCK_GRACE


def announce_away(c):
    """Таймер с виджета на ПК идёт, а вы отошли (pc_present ложно) — один раз прислать
    его в Telegram с кнопкой «■ Стоп» (14.10.2026, пользователь). Сообщение потом само
    подправится под состояние (sync_messages): «Время вышло», «остановлен». fired_tg —
    метка «уже присылал»: при срабатывании fire() всё равно пришлёт «Время вышло»."""
    rows = c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                     "WHERE i.status='open' AND i.kind='timer' AND i.source IN ('widget','island','clocker') AND "
                     "i.due>? AND i.fired_tg IS NULL", (H.now() + 5,)).fetchall()
    if not rows or pc_present() or manual_lock_grace():
        return
    for it in rows:
        send_tg(c, it)
        log("away: таймер в Telegram", it["id"], it["text"])


# 23.10.2026, просьба: «если таймер упал на ПК, сбой или я менял пресеты и они исчезли — пусть
# бот пишет, что они закрыты, сколько оставалось, когда закрыт и во сколько должны были
# закончиться». Пресет/«Очистить стол» виджеты сами помечают (drop «widget preset|clear»);
# сбой ловит lost_watch: таймер виджета открыт, а виджетов нет (процесс не запущен) или в их
# раскладке нет этого таймера дольше LOST_S — пункт закрывается с пометкой lost.
CLOSED_NOTIFY = ("widget preset", "widget clear", "lost", "lost conf")
WIDGETS_CONF = os.path.expanduser("~/.config/hypr/state/desktop-widgets.json")
LOST_S = 90
LOST = {"miss": {}, "t": 0.0}


def widgets_alive():
    try:
        out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "args="], capture_output=True,
                             text=True, timeout=3).stdout
    except Exception:
        return True                      # не знаем — не трогаем
    return any(ln.split()[-1:] == [os.path.expanduser("~/.config/hypr/scripts/desktop_widgets.py")]
               or ln.strip().endswith("desktop_widgets.py") for ln in out.splitlines())


def lost_watch(c):
    if time.time() - LOST["t"] < 10:
        return
    LOST["t"] = time.time()
    rows = c.execute("SELECT id, created FROM items WHERE status='open' AND kind='timer' AND "
                     "source='widget' AND due>?", (H.now(),)).fetchall()
    if not rows:
        LOST["miss"].clear()
        return
    alive = widgets_alive()
    try:
        refs = {str((w.get("opts") or {}).get("hub")) for w in json.load(open(WIDGETS_CONF)).get("widgets", [])}
    except Exception:
        refs = None                      # раскладку не прочли — судим только по процессу
    t = time.time()
    open_ids = {r["id"] for r in rows}
    for k in list(LOST["miss"]):
        if k not in open_ids:
            del LOST["miss"][k]
    for r in rows:
        why = None if alive else "lost"
        if why is None and refs is not None and str(r["id"]) not in refs and t - r["created"] > 30:
            why = "lost conf"
        if why is None:
            LOST["miss"].pop(r["id"], None)
            continue
        since = LOST["miss"].setdefault(r["id"], t)
        if t - since >= LOST_S and not LOST.setdefault("said", {}).get(r["id"]):
            # 23.10.2026, просьба: виджет убрали/пропал — таймер не закрывается, идёт дальше в
            # hub (и в Clocker → Timer) и звонит сам. Здесь только отметка в журнале.
            LOST["said"][r["id"]] = why
            log("lost: таймер идёт без виджета", r["id"], why)


def announce_closed(c):
    """Таймер закрыт не вами (пресет, очистка, сбой) и время ещё оставалось — новое сообщение."""
    last = H.meta_get(c, "tg_closed_ev")
    top = c.execute("SELECT COALESCE(MAX(id),0) FROM events").fetchone()[0]
    if last is None:
        H.meta_set(c, "tg_closed_ev", str(top))
        return
    last = int(last)
    if top <= last:
        return
    for ev in c.execute("SELECT * FROM events WHERE id>? AND kind='drop' ORDER BY id", (last,)).fetchall():
        if ev["data"] not in CLOSED_NOTIFY:
            continue
        it = H.get_item(c, ev["item_id"])
        if it is None or it["kind"] != "timer" or not it["due"] or it["due"] <= ev["ts"] + 5:
            continue
        text, _b = T.render(it)
        T.enqueue(c, text, None, it["id"])
        log("closed: в Telegram", it["id"], ev["data"])
    H.meta_set(c, "tg_closed_ev", str(top))


def dnd_watch():
    """Раз в тик, пока висит хоть одно critical: DND сменился — показать висящие заново."""
    with shown_lock:
        items = list(shown.values())
    if not items:
        _dnd["last"] = None
        return
    try:
        d = subprocess.run(["swaync-client", "-D"], capture_output=True, text=True,
                           timeout=3).stdout.strip()
    except Exception:
        return
    if d not in ("true", "false"):
        return
    if _dnd["last"] is not None and d != _dnd["last"]:
        log("DND", d, "— показываю заново:", len(items))
        for e in items:
            e["again"] = True
            e["gate"] = threading.Event()
            close_nid(e["nid"])
        purge_ghosts(items)
    _dnd["last"] = d


def timer_amp():
    """Громкость звонка таймера — общий ползунок «Громкость таймера» (Настройки →
    Уведомления, state/timer-volume; 14.10.2026). Не вышло — 0.3, как было."""
    try:
        import ui_sound
        return ui_sound.timer_amp()
    except Exception:
        return 0.3


def ring(iid, secs=RING_MAX):
    """Звонок таймера: минуту (RING_MAX), но стихает сразу, как пункт остановлен/отложен/увиден
    (закрыл уведомление, «Стоп» в Telegram, rem del)."""
    def work():
        c = H.connect()
        end = time.monotonic() + secs
        while not stop.is_set() and time.monotonic() < end:
            it = H.get_item(c, iid)
            if it is None or it["status"] != "open" or it["seen"] or (it["due"] or 0) > H.now():
                break
            subprocess.run(["pw-play", "--volume", "%.4f" % timer_amp(), SOUND], capture_output=True)
            stop.wait(1.0)
        c.close()
    threading.Thread(target=work, daemon=True).start()


def fire(c, it):
    t = H.now()
    here = pc_present()
    c.execute("UPDATE items SET fired_pc=? WHERE id=?", (t, it["id"]))
    log("fire", it["id"], it["text"], "pc" if here else "телефон")
    H.note(c, "fire", "%s «%s» → %s" % ("таймер" if it["kind"] == "timer" else "напоминание",
                                        " ".join(it["text"].split())[:80], "на ПК" if here else "в Telegram"))
    if here:
        # critical — висит, пока не нажмёшь (у swaync timeout-critical 0). 13.10.2026: просьба
        # Пользователя, у normal таймаут 9 с, и напоминание пропадало само, как у таймеров — нет.
        notify("Таймер" if it["kind"] == "timer" else "Напоминание", it["text"], it["id"],
               critical=True, timer=it["kind"] == "timer", rep=bool(it["repeat"]))
        if it["kind"] == "timer":
            ring(it["id"])
    elif T.token():
        # не рядом — сразу на телефон, без звука на ПК; «Идёт» от announce_away заменяется
        send_tg(c, it, replace=it["kind"] == "timer")


def send_tg(c, it, replace=False):
    c.execute("UPDATE items SET fired_tg=? WHERE id=?", (H.now(), it["id"]))
    text, btn = T.render(H.get_item(c, it["id"]))
    T.enqueue(c, text, btn, it["id"], replace=replace)


ALLDAY_SHOW = 3                      # строк в сводке «На сегодня» на ПК, остальное — «и ещё N»


def allday_today(c):
    """Открытые «только дата» на сегодня (уже наступившие, с 09:00): сперва важные, внутри —
    порядок окна hub (order_open)."""
    t0 = int(dt.datetime.combine(dt.date.today(), dt.time(0)).timestamp())
    rows = c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                     "WHERE i.status='open' AND i.kind='task' AND i.allday=1 AND i.due>=? AND "
                     "i.due<? AND i.due<=?", (t0, t0 + 86400, H.now())).fetchall()
    return sorted(T.order_open(rows), key=lambda r: -(r["prio"] or 0))


def is_allday_today(it):
    return bool(it["allday"]) and it["kind"] == "task" and it["due"] is not None and \
        dt.datetime.fromtimestamp(it["due"]).date() == dt.date.today()


def _n_tasks(n):
    w = "задача" if n % 10 == 1 and n % 100 != 11 else \
        "задачи" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "задач"
    return "%d %s" % (n, w)


def _short(t, n=44):
    t = " ".join((t or "").split())
    return t if len(t) <= n else t[:n - 1].rstrip() + "…"


def _done_today(c):
    t0 = int(dt.datetime.combine(dt.date.today(), dt.time(0)).timestamp())
    return c.execute("SELECT COUNT(*) FROM items WHERE allday=1 AND status='done' AND done_at>=?",
                     (t0,)).fetchone()[0]


def allday_text(c, rows, full=False):
    """(заголовок, текст) сводки. На ПК — первые ALLDAY_SHOW и «и ещё N», в Telegram — все."""
    head = "На сегодня: " + _n_tasks(len(rows))
    show = rows if full else rows[:ALLDAY_SHOW]
    lines = [("🔴 " if full and (r["prio"] or 0) == 2 else "🟡 " if full and (r["prio"] or 0) == 1
              else "• ") + (r["text"] if full else _short(r["text"])) for r in show]
    if len(rows) > len(show):
        lines.append("и ещё %d" % (len(rows) - len(show)))
    k = _done_today(c)
    if k:
        lines.append("Сделано сегодня: %d" % k)
    return head, "\n".join(lines)


def send_tg_allday(c, rows):
    """Одна сводка в Telegram вместо сообщения на каждую задачу; кнопка — список на сегодня."""
    t = H.now()
    for r in rows:
        c.execute("UPDATE items SET fired_tg=? WHERE id=?", (t, r["id"]))
    head, body = allday_text(c, rows, full=True)
    T.enqueue(c, head + ", сэр.\n\n" + body, [[T.btn("■ Список на сегодня", "k:per:today")]])


def allday_fire(c, rows):
    """Показать задачи «на день» разом: две и больше — одной сводкой, одна — обычным
    напоминанием (с «Сделано»/«+1 час»). Прежние карточки этих пунктов закрываются."""
    ids = {r["id"] for r in rows}
    with shown_lock:
        old = [e for e in shown.values() if not e.get("gone") and
               (e["iid"] in ids or set(e.get("group") or ()) & ids)]
    for e in old:
        e["gone"] = True
        close_nid(e["nid"])
    t = H.now()
    for r in rows:
        c.execute("UPDATE items SET fired_pc=?, fired_tg=NULL, seen=0 WHERE id=?", (t, r["id"]))
    if len(rows) == 1:
        fire(c, rows[0])
        return
    here = pc_present()
    log("allday: сводка", sorted(ids), "pc" if here else "телефон")
    if here:
        head, body = allday_text(c, rows)
        notify(head, body, 0, critical=True, group=sorted(ids))
    elif T.token():
        send_tg_allday(c, rows)


def allday_tick(c):
    """«Только дата» (15.10.2026): в 9, 12, 15 и 18 своего дня напомнить, пока не отмечено.
    21.10.2026, просьба: «прилетают стопкой все сразу… давай одно общее уведомление, где будет
    краткая сводка» — теперь в каждый такой час одна сводка со всеми неотмеченными на сегодня.
    Новая задача на сегодня, записанная после 9, ждёт ближайшего часа (H._quiet)."""
    rows = allday_today(c)
    if not rows:
        return
    t = H.now()
    today = dt.date.today()
    due = False
    for it in rows:
        if it["fired_pc"] is None:
            due = True
            break
        fired = dt.datetime.fromtimestamp(it["fired_pc"])
        nxt = next((x for x in (dt.datetime.combine(today, dt.time(h)) for h in H.ALLDAY_HOURS)
                    if x > fired), None)
        if nxt is not None and nxt.timestamp() <= t:
            due = True
            break
    if due:
        allday_fire(c, rows)


def eve_notify(title, body):
    """Вечернее «📝 Итоги дня» на ПК (growth.py, 28.10.2026): «Записать» — окно «Better»,
    «На час позже» — снова через час, закрыли — увидел (в Telegram не уйдёт)."""
    chime()

    def work():
        try:
            r = subprocess.run(["notify-send", "-a", "hub", "-i", "jarvis-hub-better", "-u", "critical", "-w",
                                "-A", "default=Записать", "-A", "write=📝 Записать",
                                "-A", "later=⏰ На час позже", title, body],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL)
            act = r.stdout.strip()
        except Exception:
            return
        if stop.is_set():
            return
        c = H.connect()
        try:
            if act == "later":
                log("итоги дня: на час позже →", G.eve_later(c))
                return
            G.eve_done(c)
            if act in ("write", "default"):
                subprocess.Popen([os.path.expanduser("~/.local/bin/hub-open"), "growth"], start_new_session=True,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        finally:
            c.close()
    threading.Thread(target=work, daemon=True).start()


def eve_tick(c, esc):
    """21:00 — напомнить записать показатели дня: на ПК, а нет за ПК / не ответили — в Telegram."""
    e = G.eve_get(c)
    t = H.now()
    if e["done"] or t < e["due"] or e["tg"]:
        return
    title, miss = G.eve_text(c)
    if e["pc"] is None and pc_present():
        body = ("Не записано:\n" + "\n".join(miss)) if miss else "Всё записано — проверьте цифры."
        eve_notify(title, body)
        e["pc"] = t
        G.eve_set(c, e)
        log("итоги дня: на ПК")
        return
    if not T.token() or (e["pc"] is not None and t - e["pc"] < esc and pc_present()):
        return
    text = "<b>%s</b>\n\n%s" % (T.esc(title), ("Не записано, сэр:\n" + "\n".join(
        "· " + T.esc(m) for m in miss)) if miss else "Всё записано — проверьте цифры, сэр.")
    T.enqueue(c, text, [[T.btn("📝 Записать", "g:eve"), T.btn("⏰ На час позже", "g:later")]], html=True)
    e["tg"] = t
    G.eve_set(c, e)
    log("итоги дня: в Telegram")


def nudge_send(n):
    """Предупреждение «Лучше вчера» на ПК; щелчок — окно Better (Super+M)."""
    cmd = ["notify-send", "-a", "hub", "-i", "jarvis-hub-better", "-w", "-A", "default=Открыть"]
    if n["through"]:
        cmd += ["-h", "int:SWAYNC_BYPASS_DND:1"]
    chime()

    def work():
        try:
            r = subprocess.run(cmd + [n["title"], n["body"]], capture_output=True, text=True,
                               stdin=subprocess.DEVNULL)
        except Exception:
            return
        if r.stdout.strip() == "default":
            subprocess.Popen([os.path.expanduser("~/.local/bin/hub-open"), "growth"], start_new_session=True,
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    threading.Thread(target=work, daemon=True).start()


_nudge = {"t": 0}


def nudge_tick(c):
    """Раз в минуту: «до красной чуть-чуть» (growth.nudges, 29.10.2026)."""
    if time.monotonic() - _nudge["t"] < 60:
        return
    _nudge["t"] = time.monotonic()
    here = pc_present()
    for n in G.nudges(c, at_pc=here):
        if here:
            nudge_send(n)
        elif T.token():
            T.enqueue(c, "<b>%s</b>\n%s" % (T.esc(n["title"]), T.esc(n["body"])), html=True)
        log("better: предупреждение", n["key"], "ПК" if here else "TG")


_pomo = {"here": True, "t": 0}


def pomo_tick(c, bot):
    """Помидор в Telegram (hubpomo, 29.10.2026): пульт /pomo идёт вслед за pomo, конец отрезка
    без вас у ПК — сообщением. pc_present — не чаще раза в 10 с."""
    import hubpomo as P
    try:
        if time.monotonic() - _pomo["t"] >= 10:
            _pomo["t"], _pomo["here"] = time.monotonic(), pc_present()
        if P.tg_tick(c, bot, _pomo["here"]):
            log("pomo: конец отрезка → Telegram")
        P.tg_sync(c, bot)
    except Exception as e:
        log("pomo:", repr(e))


_obs = {"t": 0}


def obs_tick(c):
    """«Better» → Obsidian (Развитие/Better) раз в 10 минут и сразу после любой записи (штамп
    growth); пульт /better в Telegram — тоже (29.10.2026: «полная синхронизация с ботом и десктопом»)."""
    if WOKE.get("input") and input_since(WOKE["input"]):
        try:
            ts = int(open(INPUT_FILE).read().split()[1])
        except (OSError, ValueError, IndexError):
            ts = H.now()
        WOKE["input"] = 0
        H.note(c, "input", "первый ввод после пробуждения по часам — встали", ts)
        G.invalidate()
    st = G.stamp()
    changed = st != _obs.get("s")
    if not changed and time.monotonic() - _obs["t"] < 600 and _obs["t"]:
        if T.token() and time.monotonic() - _obs.get("tg", 0) >= 60:
            _obs["tg"] = time.monotonic()
            G.tg_sync(c, T.Bot(T.token()))           # время идёт — цифры экранного времени тоже
        return
    _obs["t"], _obs["s"], _obs["tg"] = time.monotonic(), st, time.monotonic()
    if T.token():
        try:
            if G.tg_sync(c, T.Bot(T.token())):
                log("better → пульт в Telegram обновлён")
        except Exception as e:
            log("better → пульт:", repr(e))
    ch = G.obsidian_export(c)
    if ch:
        log("better → obsidian:", ", ".join(os.path.basename(x) for x in ch))


def tick(c):
    t = H.now()
    esc = int(H.cfg("esc_min", DEFAULT_ESC_MIN)) * 60
    # Повтор — один пункт на цикл (16.10.2026): не отметили до следующего раза — пункт
    # переезжает на него (H.repeat_catchup), прежнее уведомление закрывается. Копий больше нет.
    for iid in H.repeat_catchup(c):
        with shown_lock:
            old = [e for e in shown.values() if e["iid"] == iid and not e.get("gone")]
        for e in old:
            e["gone"] = True
            close_nid(e["nid"])
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.due IS NOT NULL AND i.due<=? AND i.fired_pc IS NULL",
                        (t,)).fetchall():
        if not is_allday_today(it):                 # задачи на сегодня — сводкой (allday_tick)
            fire(c, it)
    allday_tick(c)
    try:
        eve_tick(c, esc)
    except Exception as e:
        log("итоги дня:", repr(e))
    try:
        nudge_tick(c)
    except Exception as e:
        log("better → предупреждения:", repr(e))
    try:
        obs_tick(c)
    except Exception as e:
        log("better → obsidian:", repr(e))
    close_stale(c)
    lock_track()
    lost_watch(c)
    if not T.token():
        return
    announce_away(c)
    announce_closed(c)
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.kind='task' AND i.fired_pc IS NOT NULL AND "
                        "i.fired_tg IS NULL AND i.seen=0 AND i.fired_pc<=?", (t - esc,)).fetchall():
        if is_allday_today(it):
            continue
        send_tg(c, it)
        log("escalate", it["id"])
    # 27.10.2026, просьба: «если таймер покажется на ПК и я никак не отреагирую — придёт на
    # телефон?» Прозвеневший на ПК таймер, который никто не остановил, — в Telegram через
    # esc_min минут или сразу, как вы отошли (заставка/замок/экраны погасли).
    rang = c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                     "WHERE i.status='open' AND i.kind='timer' AND i.fired_pc IS NOT NULL AND "
                     "i.fired_tg IS NULL AND i.seen=0 AND i.due<=?", (t,)).fetchall()
    away = bool(rang) and not pc_present() and not manual_lock_grace()
    for it in rang:
        if away or it["fired_pc"] <= t - esc:
            send_tg(c, it, replace=True)
            log("escalate: таймер", it["id"], "отошли" if away else "%d мин без ответа" % (esc // 60))
    late =[r for r in allday_today(c) if r["fired_pc"] is not None and r["fired_tg"] is None
            and not r["seen"] and r["fired_pc"] <= t - esc]
    if len(late) == 1:
        send_tg(c, late[0])
        log("escalate", late[0]["id"])
    elif late:
        send_tg_allday(c, late)
        log("escalate: сводка", [r["id"] for r in late])


def digest(c):
    """Утренняя сводка: просроченное, на сегодня, запылившиеся без срока.
    19.10.2026, пользователь (снимок уведомления «Сводка»): «этой сводки не должно быть» —
    выключена целиком, ни на ПК, ни в Telegram. Вернуть — DIGEST_ON = True."""
    if not DIGEST_ON:
        return
    today = dt.date.today().isoformat()
    if H.meta_get(c, "digest_day") == today:
        return
    now_ = dt.datetime.now()
    if (now_.hour, now_.minute) < (DIGEST_HOUR, DIGEST_MIN):
        return
    H.meta_set(c, "digest_day", today)
    end = int(dt.datetime.combine(dt.date.today() + dt.timedelta(days=1), dt.time(0)).timestamp())
    lines = []
    tasks = H.items(c, None, "open", "task")
    over = [i for i in tasks if H.overdue(i, H.now() - 3600)]
    soon = [i for i in tasks if i["due"] and not H.overdue(i, H.now() - 3600) and i["due"] < end]
    dusty = []
    for i in tasks:
        if i["due"]:
            continue
        age = (H.now() - i["created"]) // 86400
        stage = sum(1 for d in NAG_DAYS if age >= d)
        if stage > i["nag"]:
            dusty.append((i, age))
            c.execute("UPDATE items SET nag=? WHERE id=?", (stage, i["id"]))
    if over:
        lines.append("Просрочено:\n" + "\n".join(H.fmt_item(i) for i in over))
    if soon:
        lines.append("На сегодня:\n" + "\n".join(H.fmt_item(i) for i in soon))
    if dusty:
        lines.append("Запылились:\n" + "\n".join("%s — %d дн." % (H.fmt_item(i), a) for i, a in dusty))
    w = H.word_stats(c)
    if w["due"]:
        lines.append("Слов к повторению: %d (/quiz)" % w["due"])
    if not lines:
        return
    text = "Доброе утро, сэр.\n\n" + "\n\n".join(lines)
    # 14.10.2026, просьба: «если я на ПК, то надо отправлять на ПК только» — как у напоминаний:
    # рядом с ПК — висит на ПК до закрытия, иначе — только в Telegram.
    here = pc_present()
    log("digest", "pc" if here else "телефон")
    if here or not T.token():
        notify("Сводка", "\n".join(lines)[:600], 0, critical=True)
    else:
        T.enqueue(c, text)


def say(text, html=False, buttons=None):
    """Сразу в Telegram, мимо очереди: перед сном/выключением на очередь времени нет.
    html — разметка Telegram (журнал охраны), buttons — кнопки под сообщением."""
    at = time.strftime("%H:%M")          # не вышло — в очередь с этим временем, не с временем сбоя
    tok = T.token()
    if not tok or not T.owner_ids():
        return
    bot = T.Bot(tok)
    for ch in T.owner_ids():
        p = {"chat_id": ch, "text": text[:4000]}
        if html:
            p["parse_mode"] = "HTML"
        if buttons:
            p["reply_markup"] = {"inline_keyboard": buttons}
        try:
            bot.call("sendMessage", p, timeout=4)
        except Exception as e:
            log("say:", repr(e))
            # 13.10.2026: Telegram с этой сети соединяется через раз — сообщение охраны
            # пропадало. Теперь — в очередь (flush_outbox повторяет каждый такт), с
            # временем, когда оно было сказано.
            try:
                q = H.connect()
                late = "\n<i>(с опозданием, было в %s)</i>" if html else "\n(с опозданием, было в %s)"
                T.enqueue(q, text + late % at, buttons, html=html)
                q.commit()
                q.close()
            except Exception as e2:
                log("say → очередь:", repr(e2))
            return


def photo(caption):
    """Снимок экрана владельцу (для режима охраны)."""
    tok = T.token()
    if not tok or not T.owner_ids():
        return
    path = "/tmp/hub-guard-%d.png" % int(time.time())
    try:
        subprocess.run(["grim", path], timeout=15)
        bot = T.Bot(tok)
        for ch in T.owner_ids():
            bot.photo(ch, path, caption)
    except Exception as e:
        log("photo:", repr(e))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# 21.10.2026, просьба: «/log … бот не будет каждый раз отправлять сообщение, он просто
# напишет в лог». Сон, выключение и пробуждения больше не пишутся в Telegram — только в
# журнал хаба (hublib.note → /log файлом). Скрипты, усыпляющие ПК (idle_suspend по
# простою, power_menu), заранее называют причину: `hubd.py sleep-notice idle|menu`.
RTC_PLAN = os.path.expanduser("~/.local/state/jarvis-wake/rtc-wake")
SLEEP_SRC = {"idle": "по простою", "menu": "из меню питания"}


def jnote(kind, text):
    log("журнал:", text)
    try:
        c = H.connect()
        H.note(c, kind, text)
        c.close()
    except Exception as e:
        log("журнал не записан:", repr(e))


def hm_of(t):
    return time.strftime("%H:%M" if time.localtime(t)[:3] == time.localtime()[:3] else "%d.%m %H:%M",
                         time.localtime(t))


def plan_text():
    """« · проснётся по часам 04:25 — будильник 05:00» по свежему плану или «»."""
    try:
        t = int(open(RTC_PLAN).read().split()[0])
    except (OSError, ValueError, IndexError):
        return " · проснётся только вручную"
    if t <= time.time():
        return " · проснётся только вручную"
    why = rtc_why()
    return " · проснётся по часам в %s%s" % (hm_of(t), (" — " + why["title"]) if why.get("title") else "")


def sleep_notice(src=""):
    """`hubd.py sleep-notice idle|menu` — перед systemctl suspend из своих скриптов: причина сна."""
    try:
        c = H.connect()
        H.meta_set(c, "sleep_src", "%s %d" % (src or "menu", H.now()))
        c.close()
    except Exception:
        return 1
    return 0


def sleep_src():
    try:
        c = H.connect()
        v = (H.meta_get(c, "sleep_src", "") or "").split()
        H.meta_set(c, "sleep_src", "")
        c.close()
        if len(v) == 2 and H.now() - int(v[1]) < 120:
            return SLEEP_SRC.get(v[0], v[0])
    except Exception:
        pass
    return "крышка закрыта" if lid_closed() else "кнопка или команда"


def rtc_planned():
    """Время, к которому хук jarvis-rtc-wake завёл часы перед последним сном (epoch) или None."""
    try:
        out = subprocess.run(["journalctl", "-t", "jarvis-rtc-wake", "-n", "4", "-o", "cat", "--no-pager"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in reversed(out.splitlines()):
        if line.startswith("проснуться в "):
            try:
                return time.mktime(time.strptime(line[len("проснуться в "):].strip(), "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                return None
    return None


def rtc_why():
    """Ради чего завели часы (wake_alarm.py пишет rtc-wake.why): {src: alarm|hub, kind, title…}."""
    try:
        return json.load(open(RTC_PLAN + ".why"))
    except (OSError, ValueError):
        return {}


def quiet_wake():
    """Плановое пробуждение ради напоминания или таймера хаба, к ПК никто не подходил, — о сне
    и пробуждении боту не писать: на каждое напоминание по два лишних сообщения. Будильник
    (src alarm) сообщается, как раньше."""
    return bool(WOKE["at"]) and (WOKE.get("why") or {}).get("src") == "hub" and not input_since(WOKE["at"])


WAKE_HOLD_MAX = 120                  # дольше не держим ПК проснувшимся ради доставки, с
WAKE_HOLD_MIN = 8


def lid_closed():
    for f in glob.glob("/proc/acpi/button/lid/*/state"):
        try:
            if "closed" in open(f).read():
                return True
        except OSError:
            pass
    return False


def wake_hold(woke_at, why):
    """После пробуждения ради хаба не дать logind сразу усыпить ПК снова (крышка закрыта —
    через ~30 с) — пока напоминание не сработало и Telegram не принял всё из очереди, не
    дольше WAKE_HOLD_MAX. Потом, если к ПК никто не подошёл, — обратно в сон через
    idle_suspend, без сообщения «ПК засыпает» (21.10.2026)."""
    lock = subprocess.Popen(["systemd-inhibit", "--what=sleep:handle-lid-switch", "--mode=block", "--who=hub",
                             "--why=доставить напоминание", "sleep", str(WAKE_HOLD_MAX)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    # сеть поднимается за секунды; такт хаба — 2 с, напоминание срабатывает к at+2
    ready = max(woke_at + WAKE_HOLD_MIN, float(why.get("at") or 0) + 4)
    try:
        while not stop.wait(2) and time.time() < woke_at + WAKE_HOLD_MAX:
            if input_since(woke_at):
                jnote("wake", "после пробуждения вы за ПК — не усыплял")
                return
            if time.time() < ready:
                continue
            c = H.connect()
            left = c.execute("SELECT count(*) FROM outbox WHERE sent_at IS NULL AND created>?",
                             (H.now() - 1800,)).fetchone()[0]
            c.close()
            if not left:
                break
    finally:
        lock.terminate()
    if stop.is_set() or input_since(woke_at):
        return
    jnote("wake", "доставлено, обратно в сон (крышка %s)" % ("закрыта" if lid_closed() else "открыта"))
    # idle_suspend сам смотрит Savage Mode, игру, будильник и заводит часы на следующее
    subprocess.run([os.path.expanduser("~/.config/hypr/scripts/idle_suspend")],
                   env=dict(os.environ, HUB_QUIET_SLEEP="1"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def plan_refresh():
    """Перед сном пересчитать план пробуждения (wake_alarm.py rtc check) — пока держим задержку
    logind, хук jarvis-rtc-wake ещё не читал файл."""
    try:
        subprocess.run([sys.executable, os.path.expanduser("~/.config/hypr/scripts/wake_alarm.py"), "rtc", "check"],
                       capture_output=True, timeout=3)
    except (OSError, subprocess.SubprocessError) as e:
        log("план пробуждения перед сном:", e)


def power_watch():
    """Следит за сном/выключением через logind (сигналы PrepareForSleep/Shutdown) и пишет их в
    журнал /log, держа задерживающую блокировку logind, пока план пробуждения пересчитывается.
    До 21.10.2026 о каждом сне и пробуждении писал в Telegram."""
    from gi.repository import Gio, GLib

    def take():
        return subprocess.Popen(["systemd-inhibit", "--what=sleep:shutdown", "--mode=delay", "--who=hub",
                                 "--why=записать сон в журнал", "sleep", "infinity"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = {"lock": take()}

    def on_signal(_c, _s, _p, _i, name, params, *_a):
        going = params.unpack()[0]
        member = "sleep" if name == "PrepareForSleep" else "shutdown"
        if going:
            st["sleep_at"] = time.time()
            try:
                c = H.connect()
                H.meta_set(c, "heartbeat", H.now())
                H.meta_set(c, "down_reason", member)
                c.close()
            except Exception:
                pass
            if member == "sleep":
                plan_refresh()                   # таймер, заведённый перед самой крышкой, — тоже в план
                why = "снова, после пробуждения ради хаба" if quiet_wake() else sleep_src()
                jnote("power", "сон (%s)%s" % (why, plan_text()))
            else:
                jnote("power", "выключение или перезагрузка")
            st["lock"].terminate()
        elif member == "sleep":
            hubguard.resumed()                   # охране: ввод в первые секунды — не человек
            t = rtc_planned()
            if t and abs(time.time() - t) < 180:
                WOKE["at"] = time.time()         # проснулись по часам — вас нет до первого ввода
                WOKE["input"] = WOKE["at"]       # первый ввод → журнал 'input' (подъём в growth.py)
                WOKE["why"] = rtc_why()
            slept = st.get("sleep_at")
            slept = " · спал %s, с %s" % (H.fmt_secs(time.time() - slept), hm_of(slept)) \
                if slept and 0 < time.time() - slept < 30 * 86400 else ""
            if quiet_wake():
                jnote("wake", "пробуждение по часам ради хаба: %s%s" % (WOKE["why"].get("title") or "—", slept))
                threading.Thread(target=wake_hold, args=(WOKE["at"], WOKE["why"]), daemon=True).start()
            elif t and abs(time.time() - t) < 180:
                w = WOKE.get("why") or {}
                jnote("wake", "пробуждение по часам%s%s" % ((": " + w["title"]) if w.get("title") else "", slept))
            else:
                jnote("power", "проснулся%s" % slept)
            st["lock"] = take()
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    for name in ("PrepareForSleep", "PrepareForShutdown"):
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", name,
                             "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, on_signal)
    loop = GLib.MainLoop()
    threading.Thread(target=lambda: (stop.wait(), loop.quit()), daemon=True).start()
    loop.run()


def journal_seed(c):
    """Один раз (21.10.2026): журнал /log начинается с истории хука jarvis-rtc-wake за 2 недели."""
    if H.meta_get(c, "journal_seeded"):
        return
    try:
        out = subprocess.run(["journalctl", "-t", "jarvis-rtc-wake", "--since", "-14d", "-o", "json", "--no-pager", "-q"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    plan = None
    for line in out.splitlines():
        try:
            j = json.loads(line)
            ts, msg = int(j["__REALTIME_TIMESTAMP"]) // 1000000, j.get("MESSAGE") or ""
        except (ValueError, KeyError, TypeError):
            continue
        if msg.startswith("проснуться в "):
            try:
                plan = time.mktime(time.strptime(msg[13:32], "%Y-%m-%d %H:%M:%S"))
            except ValueError:
                plan = None
            H.note(c, "power", "сон · проснётся по часам в %s" % (
                time.strftime("%d.%m %H:%M", time.localtime(plan)) if plan else msg[13:29]), ts)
        elif msg.startswith("план устарел"):
            plan = None
            H.note(c, "power", "сон · проснётся только вручную", ts)
        elif msg == "проснулся":
            H.note(c, "wake" if plan and abs(ts - plan) < 180 else "power",
                   "пробуждение по часам" if plan and abs(ts - plan) < 180 else "проснулся", ts)
            plan = None
    H.meta_set(c, "journal_seeded", 1)


def main():
    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    c = H.connect()
    H.meta_set(c, "started", H.now())
    # возврат после выключения/сна: сколько молчали
    last = H.meta_get(c, "heartbeat")
    reason = H.meta_get(c, "down_reason", "")
    if last and H.now() - int(last) > 90:
        gap = H.now() - int(last)
        why = {"sleep": "сон", "shutdown": "выключение или перезагрузка"}.get(reason, "причина неизвестна — возможно, сбой питания")
        jnote("power", "хаб снова в сети · не был доступен с %s, около %s (%s)" % (
            hm_of(int(last)), H.fmt_secs(gap), why))
    H.meta_set(c, "down_reason", "")
    journal_seed(c)
    threading.Thread(target=power_watch, daemon=True).start()
    def send_file(path, caption="", kind="document"):
        tok = T.token()
        if not tok or not T.owner_ids():
            return
        b = T.Bot(tok)
        for ch in T.owner_ids():
            try:
                if kind == "voice":
                    b.call("sendVoice", {"chat_id": ch, "caption": caption}, {"voice": path})
                elif kind == "video":
                    b.call("sendVideo", {"chat_id": ch, "caption": caption}, {"video": path})
                elif kind == "photo":
                    b.call("sendPhoto", {"chat_id": ch, "caption": caption}, {"photo": path})
                else:
                    b.call("sendDocument", {"chat_id": ch, "caption": caption}, {"document": path})
            except Exception as e:
                log("send_file:", repr(e))
        try:
            os.unlink(path)
        except OSError:
            pass

    wa = hubwa.Sender(pc_present, log)     # отложенные WhatsApp (15.10.2026)
    wa.recover(c)
    guard = hubguard.Guard(say, photo, send_file, log)
    hubguard.active_guard = guard
    polling = False
    bot = None
    last_tok = None
    while not stop.is_set():
        session_env.fill()      # при входе niri ещё не отдал переменные — ищем, пока не найдём
        try:
            tick(c)
            wa.tick(c)
            digest(c)
            dnd_watch()
            away = H.meta_get(c, "away", "0") == "1"
            if away:
                guard.start()
            else:
                guard.halt()
            tok = T.token()
            if tok and T.owner_ids():
                if not polling:
                    polling = True
                    threading.Thread(target=T.poll_loop, args=(stop, log), daemon=True).start()
                    log("Telegram включён")
                if bot is None or tok != last_tok:
                    bot, last_tok = T.Bot(tok), tok
                T.flush_outbox(c, bot)
                T.sync_messages(c, bot)
                pomo_tick(c, bot)
            H.meta_set(c, "heartbeat", H.now())
        except Exception as e:
            log("ошибка цикла:", repr(e))
        stop.wait(TICK)
    unshow_all(c)
    log("стоп")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sleep-notice"]:
        sys.exit(sleep_notice(sys.argv[2] if len(sys.argv) > 2 else ""))
    main()
