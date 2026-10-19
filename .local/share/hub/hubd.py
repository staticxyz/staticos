#!/usr/bin/env python3
"""hubd — демон hub: срабатывание напоминаний, эскалация ПК → Telegram, дайджест, таймеры.

Работает без ИИ и без `server`. Telegram включается сам, когда появляется токен
(~/.config/hub/env) и owner (config.json). Без них — только ПК.
Опрос раз в 2 с; после сна просроченное выходит одной пачкой."""
import datetime as dt
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
import hubguard  # noqa: E402
import hubwa  # noqa: E402
from idle_guard import video_in_focus  # noqa: E402
import session_env  # noqa: E402

TICK = 2
DEFAULT_ESC_MIN = 5                  # 14.10.2026: не тронул уведомление 5 мин — в Telegram
DIGEST_HOUR, DIGEST_MIN = 9, 30
DIGEST_ON = False                  # утренняя сводка выключена (19.10.2026)
NAG_DAYS = [3, 7, 14, 30]            # ступени «запылился» для пунктов без срока
RING_MAX = 300
SOUND = "/usr/share/sounds/freedesktop/stereo/complete.oga"
PRESENCE_IDLE = 300                  # простоя без видео — считаем, что ПК не рядом
INPUT_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "jarvis-input")

stop = threading.Event()


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def locked():
    return hubguard.locked()


def pc_present():
    """Рядом ли с ПК: простой меньше 5 мин (hypridle пишет jarvis-input), или в фокусе
    играет видео — тогда и звук, и экран ПК всё равно смотрят/слушают. Иначе — только телефон,
    без звука и уведомления на ПК. Нет данных о простое — считаем, что рядом (меньше риска тишины)."""
    try:
        state, ts = open(INPUT_FILE).read().split()
        idle_for = H.now() - int(ts) if state == "idle" else 0
    except (OSError, ValueError):
        return True
    if idle_for < PRESENCE_IDLE:
        return True
    try:
        return bool(video_in_focus())
    except Exception:
        return True


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


def notify(title, body, iid, critical=False, timer=False, again=False, rep=False):
    """Уведомление на ПК. notify-send -A ждёт реакции в потоке: кнопка или закрытие = «увидел».
    again — показ заново после смены DND: без звонка, реакция та же. rep — повторяющееся:
    кнопки «Отметить» (срок → следующий раз) и «Закрыть цикл» (14.10.2026)."""
    if not timer and not again:
        chime()                                    # у таймера свой звонок — ring()
    def work():
        cmd = ["notify-send", "-a", "hub", "-u", "critical" if critical else "normal", "-p"]
        if iid:                                     # у сводки (iid 0) пункта нет — и кнопок тоже
            # 15.10.2026, просьба: «не будем вообще ничего удалять… если я закрою уведомление,
            # это и будет Скрыть». У напоминания две кнопки: «Сделано» (→ «Выполненные»;
            # у повторяющегося — срок на следующий раз) и «+1 час»; закрыть = скрыть.
            # «■ Стоп» остался только у таймера.
            cmd += ["-A", "done=✓ Отметить" if rep else "done=✓ Сделано", "-A", "later=+1 час"]
            if timer:
                cmd += ["-A", "stop=■ Стоп"]
        cmd += ["-w", title, body]
        entry, key = {"nid": None, "again": False, "iid": iid}, object()
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
            notify(title, body, iid, critical, timer, again=True, rep=rep)
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
            if e["iid"]:
                c.execute("UPDATE items SET fired_pc=NULL WHERE id=? AND status='open'", (e["iid"],))
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
        if not e["iid"] or e.get("gone"):
            continue
        it = H.get_item(c, e["iid"])
        if it is None or it["status"] != "open" or (it["due"] or 0) > H.now():
            e["gone"] = True
            close_nid(e["nid"])
            if dnd_on():
                purge_ghosts()


def announce_away(c):
    """Таймер с виджета на ПК идёт, а вы отошли (pc_present ложно) — один раз прислать
    его в Telegram с кнопкой «■ Стоп» (14.10.2026, пользователь). Сообщение потом само
    подправится под состояние (sync_messages): «Время вышло», «остановлен». fired_tg —
    метка «уже присылал»: при срабатывании fire() всё равно пришлёт «Время вышло»."""
    rows = c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                     "WHERE i.status='open' AND i.kind='timer' AND i.source='widget' AND "
                     "i.due>? AND i.fired_tg IS NULL", (H.now() + 5,)).fetchall()
    if not rows or pc_present():
        return
    for it in rows:
        send_tg(c, it)
        log("away: таймер в Telegram", it["id"], it["text"])


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
    """Звонок таймера: до 5 минут, но стихает сразу, как пункт остановлен/отложен/увиден
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
    if here:
        # critical — висит, пока не нажмёшь (у swaync timeout-critical 0). 13.10.2026: просьба
        # Пользователя, у normal таймаут 9 с, и напоминание пропадало само, как у таймеров — нет.
        notify("Таймер" if it["kind"] == "timer" else "Напоминание", it["text"], it["id"],
               critical=True, timer=it["kind"] == "timer", rep=bool(it["repeat"]))
        if it["kind"] == "timer":
            ring(it["id"])
    elif T.token():
        send_tg(c, it)                              # не рядом — сразу на телефон, без звука на ПК


def send_tg(c, it):
    c.execute("UPDATE items SET fired_tg=? WHERE id=?", (H.now(), it["id"]))
    text, btn = T.render(H.get_item(c, it["id"]))
    T.enqueue(c, text, btn, it["id"])


def allday_again(c):
    """«Только дата» (15.10.2026, пользователь): в 9, 12, 15 и 18 своего дня напомнить снова,
    пока не отмечено. Прежнее уведомление (если висит) — закрыть, чтобы не копились."""
    t = H.now()
    today = dt.date.today()
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.allday=1 AND i.due IS NOT NULL AND "
                        "i.fired_pc IS NOT NULL", ()).fetchall():
        d = dt.datetime.fromtimestamp(it["due"]).date()
        if d != today:
            continue
        fired = dt.datetime.fromtimestamp(it["fired_pc"])
        nxt = next((x for x in (dt.datetime.combine(d, dt.time(h)) for h in H.ALLDAY_HOURS)
                    if x > fired), None)
        if nxt is None or nxt.timestamp() > t:
            continue
        with shown_lock:
            old = [e for e in shown.values() if e["iid"] == it["id"] and not e.get("gone")]
        for e in old:
            e["gone"] = True
            close_nid(e["nid"])
        c.execute("UPDATE items SET fired_tg=NULL, seen=0 WHERE id=?", (it["id"],))
        fire(c, it)


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
        fire(c, it)
    allday_again(c)
    close_stale(c)
    if not T.token():
        return
    announce_away(c)
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.kind='task' AND i.fired_pc IS NOT NULL AND "
                        "i.fired_tg IS NULL AND i.seen=0 AND i.fired_pc<=?", (t - esc,)).fetchall():
        send_tg(c, it)
        log("escalate", it["id"])


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


# 14.10.2026: «ПК уходит в сон (02:05)» пришло в 07:25 — logind ждёт перед сном не дольше
# InhibitDelayMaxSec (было 5 с), а путь до Telegram (напрямую 6 с + Tor) длиннее: ноутбук
# уснул посреди отправки, она доехала после пробуждения. Теперь о сне — только вовремя:
# свой бюджет, в очередь не кладём, а доехавшее после сна — удаляем. Сон по простою и из
# меню (idle_suspend, power_menu) сообщает заранее командой `hubd.py sleep-notice`, до сна.
SLEEP_BUDGET = 12          # logind с 14.10 ждёт до 15 с (logind.conf.d/50-jarvis-delay.conf)
RTC_PLAN = os.path.expanduser("~/.local/state/jarvis-wake/rtc-wake")


def say_in_time(text, budget):
    """Отправить за budget секунд или никак. True — ушло вовремя."""
    tok = T.token()
    if not tok or not T.owner_ids():
        return False
    t0 = time.time()
    res = []

    def run():
        bot = T.Bot(tok)
        for ch in T.owner_ids():
            try:
                m = bot.call("sendMessage", {"chat_id": ch, "text": text}, timeout=budget)
            except Exception as e:
                log("say_in_time:", repr(e))
                continue
            if time.time() - t0 > budget + 20:      # доехало после сна — уже не нужно
                try:
                    bot.call("deleteMessage", {"chat_id": ch, "message_id": m["message_id"]}, timeout=20)
                except Exception:
                    pass
            else:
                res.append(1)
    th = threading.Thread(target=run, daemon=True)
    th.start()
    th.join(budget)
    return bool(res)


def sleep_text(hm):
    nxt = ""
    try:
        t = int(open(RTC_PLAN).read().strip() or 0)
        if t > time.time():
            nxt = " Плановое включение — %s." % time.strftime(
                "%H:%M" if time.localtime(t)[:3] == time.localtime()[:3] else "%d.%m %H:%M",
                time.localtime(t))
    except (OSError, ValueError):
        pass
    return "ПК уходит в сон (%s). Пока он спит, я не отвечу, сэр.%s" % (hm, nxt)


def sleep_notice():
    """`hubd.py sleep-notice` — перед systemctl suspend из своих скриптов: сообщить до сна."""
    ok = say_in_time(sleep_text(time.strftime("%H:%M")), 15)
    try:
        c = H.connect()
        H.meta_set(c, "sleep_noticed", H.now() if ok else 0)
        c.close()
    except Exception:
        pass
    return 0 if ok else 1


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


def wake_text(sleep_at):
    now = time.time()
    hm = time.strftime("%H:%M")
    slept = ""
    if sleep_at and 0 < now - sleep_at < 30 * 86400:
        slept = "Спал %s (%s–%s)." % (H.fmt_secs(now - sleep_at), time.strftime(
            "%H:%M" if time.localtime(sleep_at)[:3] == time.localtime()[:3] else "%d.%m %H:%M",
            time.localtime(sleep_at)), hm)
    t = rtc_planned()
    if t and abs(now - t) < 180:
        return "Плановое включение отработало, сэр. " + ("ПК с" + slept[1:] if slept else "(%s)" % hm)
    return "ПК проснулся (%s). %s" % (hm, slept) if slept else "ПК проснулся (%s)." % hm


def power_watch():
    """Следит за сном/выключением через logind (сигналы PrepareForSleep/Shutdown) и говорит боту
    заранее, держа задерживающую блокировку (до 5 с у logind), чтобы сообщение успело уйти.
    Тишина бота = ПК выключен или спит; последнее сообщение объясняет, почему."""
    from gi.repository import Gio, GLib

    def take():
        return subprocess.Popen(["systemd-inhibit", "--what=sleep:shutdown", "--mode=delay", "--who=hub",
                                 "--why=сообщить боту", "sleep", "infinity"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    st = {"lock": take()}

    def on_signal(_c, _s, _p, _i, name, params, *_a):
        going = params.unpack()[0]
        member = "sleep" if name == "PrepareForSleep" else "shutdown"
        hm = time.strftime("%H:%M")
        if going:
            st["sleep_at"] = time.time()
            try:
                c = H.connect()
                noticed = int(H.meta_get(c, "sleep_noticed", 0) or 0)
                H.meta_set(c, "heartbeat", H.now())
                H.meta_set(c, "down_reason", member)
                c.close()
            except Exception:
                noticed = 0
            if member == "sleep":
                if H.now() - noticed > 120:      # свой скрипт уже сообщил — не повторять
                    say_in_time(sleep_text(hm), SLEEP_BUDGET)
            else:
                say_in_time("ПК выключается или перезагружается (%s). Пока он выключен, я не "
                            "отвечу, сэр." % hm, SLEEP_BUDGET)
            st["lock"].terminate()
        elif member == "sleep":
            try:
                c = H.connect()
                H.meta_set(c, "sleep_noticed", 0)
                c.close()
            except Exception:
                pass
            hubguard.resumed()                   # охране: ввод в первые секунды — не человек
            say(wake_text(st.get("sleep_at")))
            st["lock"] = take()
    bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
    for name in ("PrepareForSleep", "PrepareForShutdown"):
        bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Manager", name,
                             "/org/freedesktop/login1", None, Gio.DBusSignalFlags.NONE, on_signal)
    loop = GLib.MainLoop()
    threading.Thread(target=lambda: (stop.wait(), loop.quit()), daemon=True).start()
    loop.run()


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
        threading.Thread(target=lambda: say("ПК снова в сети (%s). Не был доступен с %s, около %s (%s)." % (
            time.strftime("%H:%M"), time.strftime("%H:%M", time.localtime(int(last))), H.fmt_secs(gap), why)),
            daemon=True).start()
    H.meta_set(c, "down_reason", "")
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
            H.meta_set(c, "heartbeat", H.now())
        except Exception as e:
            log("ошибка цикла:", repr(e))
        stop.wait(TICK)
    unshow_all(c)
    log("стоп")


if __name__ == "__main__":
    if sys.argv[1:2] == ["sleep-notice"]:
        sys.exit(sleep_notice())
    main()
