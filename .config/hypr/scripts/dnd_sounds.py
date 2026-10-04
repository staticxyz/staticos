#!/usr/bin/env python3
"""Тишина звуков уведомлений мессенджеров в «Не беспокоить». 30.09.2026.

    dnd_sounds.py            сторож (автозапуск niri)
    dnd_sounds.py status     какие программы глушатся

Задача пользователя: в DND не должно быть звуков уведомлений, но звук самих окон
(голосовые, видео в Telegram) нужен. Прежний путь — mute потока Telegram —
ломал звук: WirePlumber запоминает тишину по ключу потока («Playback Stream»),
и Telegram оставался немым и после DND (см. sound_guard.sh, 27.09.2026).

Почему Telegram сам не молчит: он спрашивает у сервиса уведомлений свойство
Inhibited (org.freedesktop.Notifications) — у swaync 0.12.6 его нет (проверено
busctl introspect), и Telegram считает, что DND выключен.

Как здесь. Сторож слушает D-Bus: каждый вызов Notify. Если DND включён и
уведомление от программы из APPS — её потоки на пару секунд ПРИГЛУШАЮТСЯ до
нуля и возвращаются на ту же громкость, что была. Звук уведомления играет
как раз в эти секунды. mute не трогаем вовсе, а громкость возвращаем ровно
прежнюю — WirePlumber запомнит её же, ломаться нечему. Если сторож упадёт
посреди приглушения, прежняя громкость лежит в DUCK_FILE и возвращается при
следующем запуске.

Цена: если в DND слушать голосовое в Telegram и в эту секунду придёт
сообщение — голосовое на ~2 с притихнет. Самое начало сигнала (десятки мс)
может проскочить: уведомление и звук Telegram шлёт одновременно.
"""
import json
import os
import re
import subprocess
import sys
import threading
import time

# Имя программы в уведомлении (app_name, без регистра) → бинарник её потоков.
APPS = {"telegram": "Telegram", "telegram desktop": "Telegram",
        "zapzap": "zapzap", "discord": "Discord", "vesktop": "vesktop"}
if os.environ.get("JARVIS_DND_TEST"):             # проверка: "имя:бинарник"
    _a, _b = os.environ["JARVIS_DND_TEST"].split(":", 1)
    APPS[_a.lower()] = _b
DUCK_S = 2.2
LOG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "dnd_sounds.log")
DUCK_FILE = os.path.expanduser("~/.cache/dnd_sounds.ducked.json")

state = {"dnd": False, "ducked": {}, "notified": {}}
# ducked: sink-input id → прежняя громкость; notified: бинарник → время последнего уведомления
WINDOW_S = 1.5           # поток, открытый в течение стольких секунд после уведомления, — его звук
lock = threading.Lock()


def log(msg):
    with open(LOG, "a") as f:
        f.write(time.strftime("%T ") + msg + "\n")


def pactl_json(*args):
    try:
        return json.loads(subprocess.run(["pactl", "-f", "json", *args], capture_output=True,
                                         text=True, timeout=3).stdout or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def streams_of(binary):
    """sink-input'ы программы: по бинарнику потока или его клиента (у потоков
    OpenAL Telegram своего имени нет — только у клиента)."""
    clients = {str(c.get("index")): c.get("properties", {}).get("application.process.binary", "")
               for c in pactl_json("list", "clients")}
    out = []
    for si in pactl_json("list", "sink-inputs"):
        props = si.get("properties", {})
        b = props.get("application.process.binary") or clients.get(str(si.get("client")), "")
        if b.lower() == binary.lower():
            vols = si.get("volume", {})
            first = next(iter(vols.values()), {}) if vols else {}
            out.append((si.get("index"), first.get("value_percent", "100%")))
    return out


def save_ducked():
    try:
        with open(DUCK_FILE, "w") as f:
            json.dump(state["ducked"], f)
    except OSError:
        pass


def restore(ids=None):
    with lock:
        for sid, vol in list(state["ducked"].items()):
            if ids is not None and sid not in ids:
                continue
            subprocess.run(["pactl", "set-sink-input-volume", str(sid), vol], capture_output=True)
            state["ducked"].pop(sid, None)
            log("#%s громкость возвращена %s" % (sid, vol))
        save_ducked()


def duck(app, binary):
    got = []
    with lock:
        for sid, vol in streams_of(binary):
            sid = str(sid)
            if sid in state["ducked"]:
                got.append(sid)
                continue
            state["ducked"][sid] = vol
            subprocess.run(["pactl", "set-sink-input-volume", sid, "0%"], capture_output=True)
            got.append(sid)
        save_ducked()
    if got:
        log("DND: уведомление %s → приглушены %s на %.1f с" % (app, ",".join(got), DUCK_S))
        threading.Timer(DUCK_S, restore, args=(set(got),)).start()
    else:
        log("DND: уведомление %s — потоков %s нет (звук ещё не открыт?)" % (app, binary))


# ── Полная тишина Telegram в DND (30.09.2026, вечер) ──────────────────────
# Просьба: «из Telegram вообще не должно быть звука, даже в начале, но потом
# звук не должен ломаться». Приглушение по уведомлению опаздывает на десятки
# мс — Telegram начинает звук одновременно с уведомлением. Поэтому: пока DND
# включён и окно Telegram НЕ в фокусе, его громкость — 0, причём и
# ЗАПОМНЕННАЯ WirePlumber'ом (ключ media.name:Playback\sStream — поток OpenAL
# Telegram без имени программы): новый поток стартует немым с первого сэмпла.
# Окно Telegram в фокусе (голосовое, видео) или DND выключен — громкость
# возвращается ровно прежняя. Громкость, а не mute: её мы сами возвращаем.
SILENT = {"Telegram": "org.telegram.desktop"}      # бинарник → app_id окна
WP_KEY = "Output/Audio:media.name:Playback\\sStream="
SILENT_FILE = os.path.expanduser("~/.cache/dnd_sounds.silent.json")
silent = {"on": False, "focus": "", "saved_pct": None, "pending": None}


def save_silent():
    try:
        with open(SILENT_FILE, "w") as f:
            json.dump({k: silent.get(k) for k in ("on", "saved_pct", "pending")}, f)
    except OSError:
        pass


def set_flag(on):
    """Флаг для скрипта WirePlumber ~/.local/share/wireplumber/scripts/jarvis/
    dnd-silence.lua: пока он стоит, НОВЫЕ потоки Telegram глушатся в момент
    создания — без «писка» первых миллисекунд (30.09.2026)."""
    if on:
        subprocess.run(["pw-metadata", "-n", "default", "0", "jarvis.tg-silent", "1"],
                       capture_output=True)
    else:
        subprocess.run(["pw-metadata", "-n", "default", "-d", "0", "jarvis.tg-silent"],
                       capture_output=True)


def unmute_telegram():
    """Снять mute, который поставил скрипт WirePlumber, со всех потоков Telegram."""
    for sid, _vol in streams_of("Telegram"):
        subprocess.run(["pactl", "set-sink-input-mute", str(sid), "0"], capture_output=True)


def silence_on():
    """Только громкость открытых потоков Telegram — WirePlumber сам запоминает её
    (новый поток стартует с неё же). Службу wireplumber НЕ трогаем никогда:
    30.09.2026 версия с остановкой/запуском wireplumber на каждую смену фокуса
    упёрлась в start-limit systemd — wireplumber не поднялся, звук пропал у всех,
    система подвисла. Если потоков нет — первый звук может проскочить, дальше
    его громкость уже запомнена нулевой."""
    st = streams_of("Telegram")
    with lock:
        for sid, vol in st:
            if vol != "0%" and not silent["saved_pct"]:
                silent["saved_pct"] = vol
            subprocess.run(["pactl", "set-sink-input-volume", str(sid), "0%"], capture_output=True)
        silent["on"] = True
        save_silent()
    set_flag(True)
    log("Telegram: тишина (DND, окно не в фокусе); было %s" % (silent["saved_pct"] or "—"))


def silence_off():
    set_flag(False)
    unmute_telegram()
    st = streams_of("Telegram")
    with lock:
        pct = silent["saved_pct"] or silent.get("pending")
        if st and pct:
            for sid, _vol in st:
                subprocess.run(["pactl", "set-sink-input-volume", str(sid), pct], capture_output=True)
            silent["pending"] = None
        elif pct:
            silent["pending"] = pct      # вернуть, как только Telegram откроет поток
        silent.update(on=False, saved_pct=None)
        save_silent()
    log("Telegram: звук возвращён (%s)" % (pct or "—"))


_eval_timer = [None]


def evaluate():
    """Решение — через 1.5 с после последнего изменения (фокус скачет туда-сюда
    при Alt+Tab; дёргать громкость на каждый скачок незачем)."""
    if _eval_timer[0]:
        _eval_timer[0].cancel()
    _eval_timer[0] = threading.Timer(1.5, _evaluate_now)
    _eval_timer[0].start()


def _evaluate_now():
    want = state["dnd"] and silent["focus"] != SILENT["Telegram"]
    if want and not silent["on"]:
        silence_on()
    elif not want and silent["on"]:
        silence_off()


def follow_focus():
    while True:
        try:
            p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            for line in p.stdout:
                if "WindowFocusChanged" not in line and "WindowsChanged" not in line:
                    continue
                try:
                    fw = json.loads(subprocess.run(["niri", "msg", "-j", "focused-window"],
                                                   capture_output=True, text=True).stdout or "null")
                except ValueError:
                    fw = None
                silent["focus"] = (fw or {}).get("app_id") or ""
                evaluate()
        except OSError:
            pass
        time.sleep(2)


def follow_streams():
    """Новые потоки: Telegram открывает поток OpenAL в момент сигнала — к вызову
    Notify его может ещё не быть. Поток программы, появившийся сразу после её
    уведомления в DND, приглушается тут же, при появлении."""
    while True:
        try:
            p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            for line in p.stdout:
                if "'new' on sink-input" not in line:
                    continue
                if not silent["on"] and silent.get("pending"):
                    for sid, _vol in streams_of("Telegram"):
                        subprocess.run(["pactl", "set-sink-input-volume", str(sid), silent["pending"]],
                                       capture_output=True)
                    silent["pending"] = None
                    save_silent()
                if silent["on"]:
                    for sid, vol in streams_of("Telegram"):
                        if vol != "0%":
                            if not silent["saved_pct"]:
                                silent["saved_pct"] = vol
                            subprocess.run(["pactl", "set-sink-input-volume", str(sid), "0%"],
                                           capture_output=True)
                if not state["dnd"]:
                    continue
                now = time.time()
                for binary, t in list(state["notified"].items()):
                    if now - t < WINDOW_S:
                        threading.Thread(target=duck, args=("(новый поток)", binary),
                                         daemon=True).start()
        except OSError:
            pass
        time.sleep(2)


def follow_dnd():
    while True:
        try:
            p = subprocess.Popen(["swaync-client", "-swb"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True)
            for line in p.stdout:
                state["dnd"] = bool(re.search(r'"alt":\s*"dnd', line))
                evaluate()
        except OSError:
            pass
        time.sleep(2)


def follow_notify():
    """dbus-monitor: после строки method call ... member=Notify первой идёт
    строка app_name (string "…")."""
    while True:
        try:
            p = subprocess.Popen(["dbus-monitor", "--session",
                                  "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"],
                                 stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            want = False
            for line in p.stdout:
                if "member=Notify" in line:
                    want = True
                    continue
                if want:
                    want = False
                    m = re.match(r'\s*string "(.*)"', line)
                    if not m:
                        continue
                    app = m.group(1)
                    binary = APPS.get(app.lower())
                    if binary and state["dnd"]:
                        state["notified"][binary] = time.time()
                        # не ждать: звук уже играет
                        threading.Thread(target=duck, args=(app, binary), daemon=True).start()
        except OSError:
            pass
        time.sleep(2)


def main():
    if sys.argv[1:2] == ["status"]:
        print("глушатся в DND:", ", ".join(sorted(set(APPS.values()))))
        return
    # один экземпляр
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"dnd_sounds.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                return
    # вернуть громкость, оставшуюся приглушённой от прошлого запуска
    try:
        state["ducked"] = json.load(open(DUCK_FILE))
    except (OSError, ValueError):
        state["ducked"] = {}
    if state["ducked"]:
        restore()
    open(LOG, "w").close()
    try:
        prev = json.load(open(SILENT_FILE))
        if prev.get("on"):
            silent.update(on=True, saved_pct=prev.get("saved_pct"), pending=prev.get("pending"))
    except (OSError, ValueError):
        pass
    set_flag(silent["on"])        # флаг для WirePlumber — по сохранённому состоянию
    threading.Thread(target=follow_dnd, daemon=True).start()
    threading.Thread(target=follow_streams, daemon=True).start()
    threading.Thread(target=follow_focus, daemon=True).start()
    follow_notify()


if __name__ == "__main__":
    main()
