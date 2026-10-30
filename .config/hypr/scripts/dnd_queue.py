#!/usr/bin/env python3
"""Очередь уведомлений «Не беспокоить». 29.10.2026.

    dnd_queue.py            сторож (в хозяине staticOS)
    dnd_queue.py show       что сейчас в очереди
    dnd_queue.py replay     показать очередь сейчас (как при выключении DND)

Просьба: «при включённом “Не беспокоить” пусть все уведомления держатся в холде, потом при
выключении они все будут приходить по очереди».

swaync в DND кладёт уведомление молча в центр, а при выключении DND ничего не показывает.
Сторож слушает шину: вызов Notify (что пришло) и ответ на него (номер в swaync). Пока DND
включён, запоминает молча спрятанные. DND выключили — шлёт каждое заново с replaces_id =
тот же номер: swaync показывает его всплывающим и не плодит копию в центре, а кнопки
(«Ответить» Telegram и т. п.) работают, потому что номер прежний. Проверено 29.10.

Просьба, 30.10: «Мы можем уведомления такие группировать и отправлять один раз, а не 10».
Перед показом одинаковые (программа + заголовок + текст) сворачиваются в одно: остаётся самое
новое с пометкой «×8» в заголовке, остальные закрываются и в центре. У своих системных
(NUM_APPS) числа в тексте не считаются — «Свободно 1840 МБ» и «1990 МБ» одно и то же; у чужих
текст сравнивается целиком, чтобы коды и суммы в чатах не склеились.

Не держит: critical и SWAYNC_BYPASS_DND (их swaync и так показал), с ключом
x-canonical-private-synchronous (громкость, трек, прогресс — устаревают), transient и свои
повторы (подсказка x-jarvis-replay). Закрыли в центре (NotificationClosed) — из очереди вон.
Очередь — ~/.cache/jarvis/dnd-queue.json (переживает перезапуск).
"""
import ctypes
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

QUEUE = os.path.expanduser("~/.cache/jarvis/dnd-queue.json")
GAP = 2.0               # секунд между повторами
GAP_MANY = 1.0          # если в очереди больше MANY
MANY = 10
BODY_MAX = 2000
MARK = "x-jarvis-replay"
NUM_APPS = ("Джарвис", "staticOS", "System", "Энергия")     # в тексте только показания
MATCHES = ("type='method_call',interface='org.freedesktop.Notifications',member='Notify'",
           "type='method_return',sender='org.freedesktop.Notifications'",
           "type='signal',interface='org.freedesktop.Notifications',member='NotificationClosed'")
_libc = ctypes.CDLL(None, use_errno=True)
lock = threading.Lock()
st = {"dnd": None, "replaying": False}


def _pdeath():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)


def load():
    try:
        q = json.load(open(QUEUE))
        return q if isinstance(q, list) else []
    except (OSError, ValueError):
        return []


def save(q):
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    with open(QUEUE + ".tmp", "w") as f:
        json.dump(q, f, ensure_ascii=False)
    os.replace(QUEUE + ".tmp", QUEUE)


def hint(hints, key):
    v = hints.get(key)
    return v.get("data") if isinstance(v, dict) else None


def held(data):
    """Notify(app, replaces_id, icon, summary, body, actions, hints, timeout) — держать ли."""
    hints = data[6] if isinstance(data[6], dict) else {}
    if hint(hints, MARK) or hint(hints, "x-canonical-private-synchronous") or hint(hints, "transient"):
        return False
    if hint(hints, "urgency") == 2 or hint(hints, "SWAYNC_BYPASS_DND"):
        return False
    return bool(data[0] or data[3] or data[4])


# ── слежение ──────────────────────────────────────────────────────────────────
pending = {}            # (отправитель, cookie) → data, ждём номер из ответа


def on_msg(msg):
    kind, member = msg.get("type"), msg.get("member")
    if kind == "method_call" and member == "Notify":
        data = (msg.get("payload") or {}).get("data")
        if st["dnd"] and isinstance(data, list) and len(data) == 8 and held(data):
            pending[(msg.get("sender"), msg.get("cookie"))] = data
            if len(pending) > 200:
                pending.clear()
    elif kind == "method_return":
        data = pending.pop((msg.get("destination"), msg.get("reply_cookie")), None)
        pl = msg.get("payload") or {}
        if data is None or pl.get("type") != "u":
            return
        nid = pl["data"][0]
        data[4] = (data[4] or "")[:BODY_MAX]
        with lock:
            q = [e for e in load() if e["id"] != nid]      # замена того же уведомления — новое место
            q.append({"id": nid, "t": time.time(), "data": data})
            save(q)
    elif kind == "signal" and member == "NotificationClosed":
        nid = ((msg.get("payload") or {}).get("data") or [None])[0]
        if st["replaying"]:
            return                     # во время показа swaync сам закрывает по таймауту
        with lock:
            q = load()
            if any(e["id"] == nid for e in q):
                save([e for e in q if e["id"] != nid])


def watch_bus():
    while True:
        try:
            p = subprocess.Popen(["busctl", "--user", "monitor", "--json=short",
                                  *("--match=" + m for m in MATCHES)],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, preexec_fn=_pdeath)
            for line in p.stdout:
                try:
                    on_msg(json.loads(line))
                except (ValueError, KeyError, IndexError, TypeError):
                    continue
        except OSError:
            pass
        time.sleep(3)


def watch_dnd():
    while True:
        try:
            p = subprocess.Popen(["swaync-client", "-s"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 preexec_fn=_pdeath)
            for line in p.stdout:
                try:
                    dnd = bool(json.loads(line).get("dnd"))
                except ValueError:
                    continue
                was, st["dnd"] = st["dnd"], dnd
                if was and not dnd:
                    threading.Thread(target=replay, daemon=True).start()
                elif was is None and not dnd and load():
                    threading.Thread(target=replay, daemon=True).start()    # выключили, пока сторож лежал
        except OSError:
            pass
        time.sleep(3)


# ── повтор ────────────────────────────────────────────────────────────────────
def _variant(sig, data):
    from gi.repository import GLib
    if sig == "ay":
        return GLib.Variant("ay", bytes(data))
    if sig.startswith("(") and sig.endswith(")"):
        inner = sig[1:-1]
        if inner == "iiibiiay":
            w, h, rs, a, bps, ch, px = data
            return GLib.Variant(sig, (w, h, rs, a, bps, ch, bytes(px)))
        return None
    if sig in ("s", "b", "y", "i", "u", "x", "t", "d", "n", "q", "as"):
        return GLib.Variant(sig, data)
    return None


def send(e):
    from gi.repository import Gio, GLib
    app, _rid, icon, summary, body, actions, hints, timeout = e["data"]
    if e.get("n", 1) > 1:
        summary = "%s ×%d" % (summary or "", e["n"])
    hv = {}
    for k, v in (hints or {}).items():
        try:
            var = _variant(v["type"], v["data"])
        except (KeyError, TypeError, ValueError):
            var = None
        if var is not None:
            hv[k] = var
    hv[MARK] = GLib.Variant("b", True)
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                  "org.freedesktop.Notifications", "Notify",
                  GLib.Variant("(susssasa{sv}i)", (app or "", e["id"], icon or "", summary or "", body or "",
                                                   list(actions or []), hv, int(timeout))),
                  GLib.VariantType("(u)"), 0, 3000, None)


def close(nid):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION)
    bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                  "org.freedesktop.Notifications", "CloseNotification",
                  GLib.Variant("(u)", (nid,)), None, 0, 3000, None)


def group_key(data):
    app, summary, body = data[0] or "", data[3] or "", data[4] or ""
    return app, summary, re.sub(r"\d+", "#", body) if app in NUM_APPS else body


def compress(q):
    """Одинаковые в одно: остаётся новейшее, в "n" — сколько их было. → (очередь, лишние номера)"""
    last, count = {}, {}
    for e in q:
        k = group_key(e["data"])
        last[k] = e
        count[k] = count.get(k, 0) + e.get("n", 1)
    out, extra = [], []
    for e in q:
        k = group_key(e["data"])
        if last[k] is not e:
            extra.append(e["id"])
            continue
        if count[k] > 1:
            e["n"] = count[k]
        out.append(e)
    return out, extra


def replay():
    """Показать очередь по одному. Включили DND снова — остаток ждёт следующего выключения."""
    if st["replaying"]:
        return
    st["replaying"] = True
    try:
        time.sleep(1.0)
        with lock:
            q, extra = compress(load())
            if extra:
                save(q)                # раньше закрытия: сигнал о нём очередь уже не тронет
        for nid in extra:
            try:
                close(nid)
            except Exception:
                pass
        while True:
            with lock:
                q = load()
                if not q or st["dnd"]:
                    return
                e = q.pop(0)
                save(q)
            try:
                send(e)
            except Exception:
                pass
            time.sleep(GAP_MANY if len(q) > MANY else GAP)
    finally:
        st["replaying"] = False


def main():
    arg = sys.argv[1:2]
    if arg == ["show"]:
        for e in load():
            d = e["data"]
            print(time.strftime("%H:%M", time.localtime(e["t"])), e["id"], d[0], "|", d[3], "|",
                  (d[4] or "").replace("\n", " ")[:60])
        return 0
    if arg == ["replay"]:
        st["dnd"] = False
        replay()
        return 0
    threading.Thread(target=watch_dnd, daemon=True).start()
    watch_bus()


if __name__ == "__main__":
    sys.exit(main())
