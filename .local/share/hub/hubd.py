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
from idle_guard import video_in_focus  # noqa: E402

TICK = 2
DEFAULT_ESC_MIN = 10
DIGEST_HOUR, DIGEST_MIN = 9, 30
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


def notify(title, body, iid, critical=False, timer=False):
    """Уведомление на ПК. notify-send -A ждёт реакции в потоке: кнопка или закрытие = «увидел»."""
    def work():
        cmd = ["notify-send", "-a", "hub", "-u", "critical" if critical else "normal",
               "-A", "done=✓ Сделано", "-A", "later=+1 час", "-A", "stop=■ Стоп", "-w", title, body]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
        except Exception:
            return
        act = r.stdout.strip()
        c = H.connect()
        if act == "done":
            H.done(c, iid, "pc")
        elif act == "later":
            H.snooze(c, iid, 3600, source="pc")
        elif timer or act == "stop":
            H.drop(c, iid, "pc")                   # закрыл уведомление таймера = стоп
        H.mark_seen(c, iid)                        # закрыл или нажал — эскалации в TG не будет
        c.close()
    threading.Thread(target=work, daemon=True).start()


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
            subprocess.run(["pw-play", "--volume", "0.3", SOUND], capture_output=True)
            stop.wait(1.0)
        c.close()
    threading.Thread(target=work, daemon=True).start()


def fire(c, it):
    t = H.now()
    here = pc_present()
    c.execute("UPDATE items SET fired_pc=? WHERE id=?", (t, it["id"]))
    log("fire", it["id"], it["text"], "pc" if here else "телефон")
    if here:
        notify("Таймер" if it["kind"] == "timer" else "Напоминание", it["text"], it["id"],
               critical=it["kind"] == "timer", timer=it["kind"] == "timer")
        if it["kind"] == "timer":
            ring(it["id"])
    elif T.token():
        send_tg(c, it)                              # не рядом — сразу на телефон, без звука на ПК


def send_tg(c, it):
    c.execute("UPDATE items SET fired_tg=? WHERE id=?", (H.now(), it["id"]))
    text, btn = T.render(H.get_item(c, it["id"]))
    T.enqueue(c, text, btn, it["id"])


def tick(c):
    t = H.now()
    esc = int(H.cfg("esc_min", DEFAULT_ESC_MIN)) * 60
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.due IS NOT NULL AND i.due<=? AND i.fired_pc IS NULL",
                        (t,)).fetchall():
        fire(c, it)
        if it["repeat"]:                            # повторяющееся: следующий срок сразу
            nd = H._next_due(it["due"], it["repeat"])
            c.execute("INSERT INTO items(list_id,text,kind,due,repeat,created,updated_at,source) "
                      "VALUES(?,?,?,?,?,?,?,?)", (it["list_id"], it["text"], it["kind"], nd,
                                                  it["repeat"], t, t, "repeat"))
            c.execute("UPDATE items SET repeat='' WHERE id=?", (it["id"],))
    if not T.token():
        return
    for it in c.execute("SELECT i.*, l.name AS list FROM items i JOIN lists l ON l.id=i.list_id "
                        "WHERE i.status='open' AND i.kind='task' AND i.fired_pc IS NOT NULL AND "
                        "i.fired_tg IS NULL AND i.seen=0 AND i.fired_pc<=?", (t - esc,)).fetchall():
        send_tg(c, it)
        log("escalate", it["id"])


def digest(c):
    """Утренняя сводка: просроченное, на сегодня, запылившиеся без срока."""
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
    over = [i for i in tasks if i["due"] and i["due"] < H.now() - 3600]
    soon = [i for i in tasks if i["due"] and H.now() - 3600 <= i["due"] < end]
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
    log("digest")
    T.enqueue(c, text)
    notify("Сводка", "\n".join(lines)[:300], 0)


def say(text):
    """Сразу в Telegram, мимо очереди: перед сном/выключением на очередь времени нет."""
    tok = T.token()
    if not tok or not T.owner_ids():
        return
    bot = T.Bot(tok)
    for ch in T.owner_ids():
        try:
            bot.call("sendMessage", {"chat_id": ch, "text": text}, timeout=4)
        except Exception as e:
            log("say:", repr(e))


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
            say("ПК %s (%s). Пока он %s, я не отвечу, сэр." % (
                "уходит в сон" if member == "sleep" else "выключается или перезагружается", hm,
                "спит" if member == "sleep" else "выключен"))
            try:
                c = H.connect()
                H.meta_set(c, "heartbeat", H.now())
                H.meta_set(c, "down_reason", member)
                c.close()
            except Exception:
                pass
            st["lock"].terminate()
        elif member == "sleep":
            say("ПК проснулся (%s)." % hm)
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
    if not H.meta_get(c, "twin_imported"):
        n = H.import_twin(c)
        H.meta_set(c, "twin_imported", 1)
        log("импорт из twin-claude:", n)
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
    guard = hubguard.Guard(say, photo, log)
    polling = False
    bot = None
    last_tok = None
    while not stop.is_set():
        try:
            tick(c)
            digest(c)
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
    log("стоп")


if __name__ == "__main__":
    main()
