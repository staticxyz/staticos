#!/usr/bin/env python3
"""Замок стола на помидор «programming». 20.10.2026.

Просьба: «когда запускаю помидор с названием programming — фокус должен оставаться на
столе, где я его включил, Super+J/K не работать, новые окна не создаваться, текущие не
закрываться. Поставлю на паузу — всё опять работает».

Замок стоит, пока идёт РАБОЧИЙ отрезок pomo (не пауза, не перерыв, не стоп), а задача
содержит слово из ~/.config/pomo/lock-tasks (без регистра, по строке; нет файла —
«programming»). Стол — тот, что был в фокусе в момент старта или снятия с паузы.
  * Super+J/K и прочие шаги по столам — обёртка niri/scripts/ws-step молчит (`pomo locked`);
  * остальные пути (Super+1…9, обзор, Alt+Tab, щелчок по другому монитору) — сторож
    возвращает фокус на стол замка;
  * новое окно сторож закрывает (кроме Clocker, hub Super+M, polkit, pinentry, диалогов портала);
  * закрыть окно: Ctrl+Q (close-or-clipboard), СКМ/меню xpbar, dock, taskbar — молчат.
    Своё закрытие программы (exit в kitty, :q, Ctrl+Shift+W) композитор не видит.

Отметка замка — $XDG_RUNTIME_DIR/pomo/ws-lock: «began started стол». Она действует, только
пока began/started совпадают с состоянием pomo и отрезок идёт: пауза, перерыв, стоп,
перезагрузка снимают замок сами, даже если сторож умер. Отрезок, шедший до запуска
сторожа, не замыкается (иначе включение сторожа заперло бы на чужом столе).

    pomo_lock.py           сторож (живёт в хозяине staticOS)
    pomo_lock.py status    замок сейчас
Журнал — ~/.cache/pomo-lock.log.
"""
import json
import os
import re
import socket
import sys
import threading
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
POMO_STATE = os.path.join(RUN, "pomo", "state")
FLAG = os.path.join(RUN, "pomo", "ws-lock")
TASKS = os.path.expanduser("~/.config/pomo/lock-tasks")
LOG = os.path.expanduser("~/.cache/pomo-lock.log")
# Clocker — чтобы поставить на паузу, hub (Super+M) — там пишутся задачи (20.10.2026);
# остальное — запросы пароля и диалоги файлов.
ALLOW_APP = re.compile(r"^com\.jarvis\.(clocker|discipline|routine|hub)$|polkit|pinentry|xdg-desktop-portal", re.I)


def log(msg):
    try:
        if os.path.getsize(LOG) > 262144:
            os.replace(LOG, LOG + ".old")
    except OSError:
        pass
    try:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


def pomo_state():
    d = {}
    try:
        for line in open(POMO_STATE):
            k, _, v = line.rstrip("\n").partition("=")
            d[k] = v
    except OSError:
        pass
    for k in ("started", "duration", "paused", "began"):
        try:
            d[k] = int(d.get(k) or 0)
        except ValueError:
            d[k] = 0
    return d


def running(d, now=None):
    """Рабочий отрезок идёт (не пауза, не кончился)."""
    return (d.get("phase") == "work" and not d["paused"]
            and (now or time.time()) < d["started"] + d["duration"])


def lock_words():
    try:
        words = [ln.strip().lower() for ln in open(TASKS)]
    except OSError:
        return ["programming"]
    return [w for w in words if w and not w.startswith("#")]


def wanted(d):
    """(began, started) отрезка, который надо замкнуть, или None."""
    task = (d.get("task") or "").lower()
    if running(d) and any(w in task for w in lock_words()):
        return (d["began"], d["started"])
    return None


def read_flag():
    try:
        b, s, ws = open(FLAG).read().split()[:3]
        return int(b), int(s), int(ws)
    except (OSError, ValueError):
        return None


def write_flag(sig, ws):
    try:
        with open(FLAG + ".tmp", "w") as f:
            f.write("%d %d %d\n" % (sig[0], sig[1], ws))
        os.replace(FLAG + ".tmp", FLAG)
    except OSError as e:
        log("не записал отметку: %s" % e)


def drop_flag():
    try:
        os.unlink(FLAG)
    except OSError:
        pass


def locked():
    """id стола замка или None. Для xpbar/dock/taskbar: «закрывать ли окно»."""
    f = read_flag()
    if not f:
        return None
    d = pomo_state()
    if running(d) and (d["began"], d["started"]) == f[:2]:
        return f[2]
    return None


def niri(req):
    try:
        sk = socket.socket(socket.AF_UNIX)
        sk.settimeout(2)
        sk.connect(os.environ["NIRI_SOCKET"])
        sk.sendall((json.dumps(req) + "\n").encode())
        reply = sk.makefile().readline()
        sk.close()
        return json.loads(reply)
    except (OSError, KeyError, ValueError):
        return None


class Watch:
    def __init__(self):
        self.mu = threading.Lock()
        self.wins = {}          # id → {"ws", "app"}
        self.wss = set()
        self.focused = None     # стол в фокусе
        self.ready = False      # пришёл первый список окон — дальше «новые» правда новые
        self.sig = None         # замкнутый отрезок
        self.ws = None          # стол замка
        self.skip = None        # отрезок, шедший до запуска сторожа
        self.acts = []

    # ---- поток событий niri ----
    def stream(self):
        while True:
            try:
                sk = socket.socket(socket.AF_UNIX)
                sk.connect(os.environ["NIRI_SOCKET"])
                sk.sendall(b'"EventStream"\n')
                f = sk.makefile()
                f.readline()                       # {"Ok":"Handled"}
                for line in f:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    with self.mu:
                        self.event(ev)
            except (OSError, KeyError) as e:
                log("поток событий: %s" % e)
            with self.mu:
                self.ready = False
            time.sleep(3)

    def event(self, ev):
        if "WorkspacesChanged" in ev:
            wl = ev["WorkspacesChanged"]["workspaces"]
            self.wss = {w["id"] for w in wl}
            self.focused = next((w["id"] for w in wl if w.get("is_focused")), self.focused)
            self.enforce()
        elif "WorkspaceActivated" in ev:
            a = ev["WorkspaceActivated"]
            if a.get("focused"):
                self.focused = a["id"]
                self.enforce()
        elif "WindowsChanged" in ev:
            self.wins = {w["id"]: {"ws": w.get("workspace_id"), "app": w.get("app_id") or ""}
                         for w in ev["WindowsChanged"]["windows"]}
            self.ready = True
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            new = w["id"] not in self.wins
            self.wins[w["id"]] = {"ws": w.get("workspace_id"), "app": w.get("app_id") or ""}
            if new and self.ready and self.ws is not None and locked() is not None:
                self.new_window(w)
            elif w.get("is_focused") and w.get("workspace_id") is not None:
                self.focused = w["workspace_id"]
                self.enforce()
        elif "WindowClosed" in ev:
            self.wins.pop(ev["WindowClosed"]["id"], None)
        elif "WindowFocusChanged" in ev:
            wid = ev["WindowFocusChanged"].get("id")
            ws = (self.wins.get(wid) or {}).get("ws")
            if ws is not None:
                self.focused = ws
                self.enforce()

    def new_window(self, w):
        app, title = w.get("app_id") or "", w.get("title") or ""
        if ALLOW_APP.search(app) or (app == "kitty" and title == "pomo"):   # pomo watch, Super+Ctrl+P
            return
        log("закрыл новое окно %s «%s»" % (app, title[:60]))
        niri({"Action": {"CloseWindow": {"id": w["id"]}}})

    def enforce(self, force=False):
        if self.ws is None or self.focused is None or self.focused == self.ws:
            return
        if locked() is None:
            return
        if self.ws not in self.wss:                # пустой стол niri убрал — замок на текущий
            log("стол %s пропал — замок на %s" % (self.ws, self.focused))
            self.ws = self.focused
            write_flag(self.sig, self.ws)
            return
        now = time.time()
        if not force and self.acts and now - self.acts[-1] < 0.05:
            return                                 # одно переключение = несколько событий
        self.acts = [t for t in self.acts if now - t < 2]
        if len(self.acts) >= 8 and not force:      # кто-то борется за фокус — не зацикливаться;
            return                                 # tick всё равно вернёт стол через ≤1 с
        self.acts.append(now)
        niri({"Action": {"FocusWorkspace": {"reference": {"Id": self.ws}}}})

    # ---- состояние pomo ----
    def tick(self):
        sig = wanted(pomo_state())
        with self.mu:
            if sig is None:
                if self.sig is not None:
                    log("замок снят")
                self.sig = self.ws = None
                if read_flag():
                    drop_flag()
                return
            if sig == self.sig:
                self.enforce(force=True)           # раз в секунду: лимит не даёт застрять на чужом столе
                return
            if sig == self.skip:
                return
            if self.focused is None:
                return                             # стол ещё не знаем — следующий тик
            self.sig, self.ws = sig, self.focused
            write_flag(sig, self.ws)
            log("замок на стол %s" % self.ws)

    def run(self):
        d = pomo_state()
        sig, f = wanted(d), read_flag()
        if sig and f and f[:2] == sig:
            self.sig, self.ws = sig, f[2]          # сторож перезапущен посреди замка
            log("продолжаю замок на стол %s" % self.ws)
        elif sig:
            self.skip = sig
            log("отрезок шёл до запуска — не замыкаю")
        threading.Thread(target=self.stream, name="pomo_lock-stream", daemon=True).start()
        last = None
        while True:
            try:
                m = os.stat(POMO_STATE).st_mtime_ns
            except OSError:
                m = 0
            # по смене файла и раз в секунду — отрезок кончается и без записи в файл
            if m != last or int(time.time() * 3) % 3 == 0:
                last = m
                self.tick()
            time.sleep(1 / 3)


def status():
    ws = locked()
    d = pomo_state()
    if ws is not None:
        print("замок на стол %d · задача «%s»" % (ws, d.get("task", "")))
    else:
        print("замка нет · слова: %s" % ", ".join(lock_words()))
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["status"]:
        sys.exit(status())
    Watch().run()
