#!/usr/bin/env python3
"""hubguard — режим «меня нет дома»: сообщает в Telegram, если кто-то трогает ПК.

Включает и выключает хозяин вручную: /away on|off в боте или `hub away on|off`.
Пока выключен — не открывает устройства ввода и не читает события (нулевая нагрузка).

Что видит:
  • клавиатура/мышь/тачпад: первое касание после тишины (5 мин) — тревога + снимок экрана;
    дальше раз в минуту сводка, в конце — «активность прекратилась»;
  • окна: что открылось и что закрылось (niri event-stream);
  • экран блокировки: снят замок; неверный пароль (журнал unix_chkpwd/pam);
  • сон/пробуждение/выключение — это сообщает hubd и без режима.
Чего не видит: кто именно. Это событие на ПК, а не лицо."""
import glob
import json
import os
import select
import struct
import subprocess
import threading
import time

import hublib as H

QUIET = 300          # тишина, после которой касание снова считается «новым»
SUMMARY = 60         # сводки во время активности
EV = struct.Struct("@llHHi")


def locked():
    # якорь «^»: иначе совпадёт любая командная строка, где упомянуто имя (оболочка, тест)
    for pat in ("-x", "hyprlock"), ("-f", r"^\S*python\S* \S*jarvis_lock\.py"):
        if subprocess.run(["pgrep", pat[0], pat[1]], capture_output=True).returncode == 0:
            return True
    return False


class Guard:
    def __init__(self, say, photo, log=print):
        self.say, self.photo, self.log = say, photo, log
        self.stop = threading.Event()
        self.threads = []
        self.lock = threading.Lock()
        self.last_input = 0.0
        self.input_n = 0
        self.session = False
        self.last_summary = 0.0
        self.windows = {}              # id → (app, title) по niri
        self.opened, self.closed = [], []
        self.was_locked = None
        self.procs = []

    # ── запуск/остановка ──
    def start(self):
        if self.threads:
            return
        self.stop.clear()
        self.was_locked = locked()
        self.last_input = 0.0
        self.session = False
        for fn in (self.read_input, self.read_niri, self.read_journal, self.report_loop):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self.threads.append(t)
        self.log("guard: включён")

    def halt(self):
        if not self.threads:
            return
        self.stop.set()
        for p in self.procs:
            try:
                p.terminate()
            except OSError:
                pass
        self.procs = []
        self.threads = []
        self.log("guard: выключен")

    # ── источники ──
    def read_input(self):
        fds = {}
        for path in glob.glob("/dev/input/event*"):
            try:
                fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
            except OSError:
                continue
        if not fds:
            self.say("⚠ Режим охраны: нет доступа к устройствам ввода, клавиатуру и мышь не вижу.")
        try:
            while not self.stop.is_set() and fds:
                r, _, _ = select.select(list(fds), [], [], 1.0)
                for fd in r:
                    try:
                        data = os.read(fd, EV.size * 64)
                    except OSError:
                        continue
                    # только нажатия клавиш/кнопок и движение; синхронизацию (type 0) пропускаем
                    n = sum(1 for i in range(0, len(data) - EV.size + 1, EV.size)
                            if EV.unpack_from(data, i)[2] in (1, 2, 3))
                    if n:
                        with self.lock:
                            self.last_input = time.time()
                            self.input_n += n
        finally:
            for fd in fds:
                os.close(fd)

    def read_niri(self):
        try:
            p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE, text=True)
        except OSError:
            return
        self.procs.append(p)
        first = True
        for line in p.stdout:
            if self.stop.is_set():
                break
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if "WindowsChanged" in ev:
                self.windows = {w["id"]: (w.get("app_id") or "?", w.get("title") or "") for w in ev["WindowsChanged"]["windows"]}
                first = False
            elif "WindowOpenedOrChanged" in ev and not first:
                w = ev["WindowOpenedOrChanged"]["window"]
                new = w["id"] not in self.windows
                self.windows[w["id"]] = (w.get("app_id") or "?", w.get("title") or "")
                if new:
                    with self.lock:
                        self.opened.append("%s — %s" % self.windows[w["id"]])
            elif "WindowClosed" in ev:
                w = self.windows.pop(ev["WindowClosed"]["id"], None)
                if w:
                    with self.lock:
                        self.closed.append("%s — %s" % w)

    def read_journal(self):
        try:
            p = subprocess.Popen(["journalctl", "-f", "-n0", "-o", "cat", "-t", "unix_chkpwd", "-t", "jarvis_lock",
                                  "-t", "hyprlock", "-t", "sudo", "-t", "sddm-helper"],
                                 stdout=subprocess.PIPE, text=True)
        except OSError:
            return
        self.procs.append(p)
        for line in p.stdout:
            if self.stop.is_set():
                break
            low = line.lower()
            if "password check failed" in low or "authentication failure" in low or "incorrect password" in low:
                self.say("🔑 Неверный пароль на ПК (%s)." % time.strftime("%H:%M:%S"))

    # ── отчёты ──
    def report_loop(self):
        while not self.stop.wait(3):
            now = time.time()
            lk = locked()
            if self.was_locked is not None and lk != self.was_locked:
                self.say("🔓 Экран разблокирован (%s)." % time.strftime("%H:%M:%S") if not lk
                         else "🔒 Экран заблокирован (%s)." % time.strftime("%H:%M:%S"))
                if not lk:
                    self.photo("Экран после разблокировки")
            self.was_locked = lk
            with self.lock:
                li, n = self.last_input, self.input_n
                op, cl = self.opened, self.closed
            if li and not self.session and now - li < 30:
                self.session = True
                self.last_summary = now
                with self.lock:
                    self.input_n = 0
                    self.opened, self.closed = [], []
                self.say("⚠ Кто-то трогает ПК: клавиатура или мышь (%s). Экран %s." % (
                    time.strftime("%H:%M:%S"), "заблокирован" if lk else "НЕ заблокирован"))
                self.photo("Экран сейчас")
            elif self.session:
                if now - li > QUIET:
                    self.session = False
                    self.say("Активность на ПК прекратилась (последнее касание в %s)." % time.strftime("%H:%M", time.localtime(li)))
                elif now - self.last_summary >= SUMMARY and (op or cl or n):
                    lines = ["Сводка за минуту: касаний ввода %d." % n]
                    if op:
                        lines.append("Открыто: " + "; ".join(op[:6]))
                    if cl:
                        lines.append("Закрыто: " + "; ".join(cl[:6]))
                    with self.lock:
                        self.input_n = 0
                        self.opened, self.closed = [], []
                    self.last_summary = now
                    self.say("\n".join(lines))
            elif (op or cl) and now - self.last_summary >= SUMMARY:
                # окна менялись без ввода (скрипт, программа сама) — тихая сводка
                with self.lock:
                    self.opened, self.closed = [], []
                self.last_summary = now
                self.say("На ПК без ввода: открыто %s; закрыто %s." % ("; ".join(op[:5]) or "—", "; ".join(cl[:5]) or "—"))
