#!/usr/bin/env python3
"""Журнал уведомлений для центра управления. 04.10.2026.

    notif_log.py              сторож (автозапуск niri; второй экземпляр выходит)
    notif_log.py show [N]     последние N записей (по умолчанию 10), для проверки
    notif_log.py clear        стереть журнал

Просьба: «а здесь можно отобразить последние вмещаемые уведомления? Чтобы можно
было скроллить» — про страницу «Уведомления» центра управления (control_center.py).

Зачем свой журнал. swaync хранит историю только внутри себя: по D-Bus отдаёт одно
число (`swaync-client -c`), а текст — никак (проверено: в интерфейсе
org.erikreider.swaync.cc нет метода списка). Поэтому сторож сам слушает вызовы
Notify на шине и пишет их в ~/.cache/jarvis-notif-log.json, новые сверху, не более
KEEP записей. Что это значит для пользователя:
  * в журнале только то, что пришло, пока сторож работает (с момента его запуска);
  * удаление уведомления в самом центре swaync журнал не видит — «Очистить историю»
    на странице стирает и то, и другое.

Подписка — `busctl --user monitor --match=…` с PDEATHSIG: сирот не остаётся (память
kill-background-watchers). Сторож спит в чтении потока; процессор — ноль.
Повтор одного и того же уведомления (смена трека, прогресс) обновляет запись, а не
плодит строки: по ключу x-canonical-private-synchronous или по совпадению
приложение+заголовок+текст за последние 5 минут.
"""
import ctypes
import json
import os
import signal
import subprocess
import sys
import time

LOG = os.path.expanduser("~/.cache/jarvis-notif-log.json")
KEEP = 150
BODY_MAX = 400
MATCH = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
SYNC = "x-canonical-private-synchronous"
_libc = ctypes.CDLL(None, use_errno=True)


def load():
    try:
        with open(LOG) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def save(items):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    tmp = LOG + ".tmp"
    with open(tmp, "w") as f:
        json.dump(items[:KEEP], f, ensure_ascii=False)
    os.replace(tmp, LOG)


def hint(hints, key):
    v = hints.get(key)
    return v.get("data") if isinstance(v, dict) else None


def add(payload):
    """payload.data сообщения Notify: app, replaces_id, icon, summary, body, actions, hints, timeout."""
    try:
        app, _rid, icon, summary, body, _acts, hints, _t = payload["data"]
    except (KeyError, ValueError, TypeError):
        return
    hints = hints if isinstance(hints, dict) else {}
    now = time.time()
    entry = {"t": now, "app": app or "", "summary": summary or "", "body": (body or "")[:BODY_MAX],
             "icon": icon or hint(hints, "image-path") or "", "urgency": hint(hints, "urgency"),
             "sync": hint(hints, SYNC) or ""}
    if not (entry["app"] or entry["summary"] or entry["body"]):
        return
    items = load()
    for i, old in enumerate(items):
        same_key = entry["sync"] and old.get("sync") == entry["sync"] and old.get("app") == entry["app"]
        same_text = (now - old.get("t", 0) < 300 and old.get("app") == entry["app"]
                     and old.get("summary") == entry["summary"] and old.get("body") == entry["body"])
        if same_key or same_text:
            del items[i]
            break
    items.insert(0, entry)
    save(items)


# ── Обрезка центра уведомлений (07.10.2026) ──────────────────────────────────
# Просьба: «достаточно очищать с конца, а не весь журнал: свежие могут быть нужны, старые нет».
# swaync держал 139 уведомлений и 231 МиБ (сутки назад — 117). Списка по D-Bus он не
# отдаёт, но номера уведомлений растут по порядку, а CloseNotification(номер) убирает
# одно из центра. Поэтому: больше KEEP_CC — закрываем по возрастанию номера, то есть
# самые старые, пока не останется KEEP_CC. Курсор (с какого номера искать) помнится,
# пока жив тот же swaync; закрытие несуществующего номера ничего не делает.
KEEP_CC = 50
_trim = {"cursor": 1, "pid": None, "timer": None}


def _cc(method, args=None, rtype=None):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    r = bus.call_sync("org.erikreider.swaync.cc", "/org/erikreider/swaync/cc", "org.erikreider.swaync.cc",
                      method, args, GLib.VariantType(rtype) if rtype else None, 0, 3000, None)
    return r.unpack()[0] if rtype else None


def trim_center():
    from gi.repository import GLib
    try:
        pid = subprocess.run(["pgrep", "-xo", "swaync"], capture_output=True, text=True).stdout.strip()
        if pid != _trim["pid"]:
            _trim.update(pid=pid, cursor=1)
        count = _cc("NotificationCount", None, "(u)")
        tries = 0
        while count > KEEP_CC and tries < 20000:
            for _ in range(max(1, min(20, count - KEEP_CC))):   # не больше, чем надо убрать
                _cc("CloseNotification", GLib.Variant("(u)", (_trim["cursor"],)))
                _trim["cursor"] += 1
                tries += 1
            count = _cc("NotificationCount", None, "(u)")
    except Exception:
        pass


def trim_spawn():
    """Обрезка — в отдельном коротком процессе: gi (D-Bus) весит ~10 МиБ, сторожу он
    нужен раз в несколько минут, держать его в памяти всё время незачем (07.10.2026)."""
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "trim"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def trim_later():
    """Не на каждое уведомление сразу: через 5 с после последнего из пачки."""
    import threading
    t = _trim.get("timer")
    if t:
        t.cancel()
    _trim["timer"] = threading.Timer(5, trim_spawn)
    _trim["timer"].daemon = True
    _trim["timer"].start()


def watch():
    trim_later()
    while True:
        try:
            p = subprocess.Popen(["busctl", "--user", "monitor", "--json=short", "--match=" + MATCH],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 preexec_fn=lambda: _libc.prctl(1, signal.SIGTERM, 0, 0, 0))
            for line in p.stdout:
                if b'"member":"Notify"' not in line:
                    continue
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("type") == "method_call" and msg.get("member") == "Notify":
                    add(msg.get("payload") or {})
                    trim_later()
        except OSError:
            pass
        time.sleep(3)


def main():
    a = sys.argv[1:]
    if a[:1] == ["show"]:
        n = int(a[1]) if len(a) > 1 and a[1].isdigit() else 10
        for e in load()[:n]:
            print(time.strftime("%d.%m %H:%M", time.localtime(e["t"])), "|", e["app"], "|",
                  e["summary"], "|", e["body"].replace("\n", " ")[:70])
        return
    if a[:1] == ["trim"]:
        # курсор между запусками: файл в /run, сбрасывается с новым PID swaync
        cur = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-notif-trim")
        try:
            pid, c = open(cur).read().split()
            _trim.update(pid=pid, cursor=int(c))
        except (OSError, ValueError):
            pass
        trim_center()
        try:
            open(cur, "w").write("%s %d" % (_trim["pid"], _trim["cursor"]))
        except OSError:
            pass
        return
    if a[:1] == ["clear"]:
        save([])
        return
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"notif_log.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                return
    watch()


if __name__ == "__main__":
    main()
