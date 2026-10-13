#!/usr/bin/env python3
"""hubguard — режим «меня нет дома»: сообщает в Telegram, если кто-то трогает ПК.

Включает и выключает хозяин вручную: /away on|off в боте или `hub away on|off`.
Пока выключен — не открывает устройства ввода и не читает события (нулевая нагрузка).

Что видит:
  • клавиатура/мышь/тачпад: первое касание после тишины (5 мин) — тревога + снимок экрана;
    дальше раз в минуту сводка с конкретными клавишами и кнопками мыши;
  • окна: что открылось и что закрылось (niri event-stream);
  • экран блокировки: снят замок; неверный пароль (журнал unix_chkpwd/pam);
  • сон/пробуждение/выключение — это сообщает hubd и без режима.
  • камера: /away photo — снимок, /away rec N — видео N секунд
  • микрофон: /away mic N — запись N секунд, /away listen — живая запись

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

active_guard = None
QUIET = 300          # тишина, после которой касание снова считается «новым»
SUMMARY = 60         # сводки во время активности
EV = struct.Struct("@llHHi")

# evdev типы
EV_KEY = 1
EV_REL = 2
EV_ABS = 3

# Имена клавиш (основные — остальные пойдут кодом)
KEY_NAMES = {
    1: "ESC", 2: "1", 3: "2", 4: "3", 5: "4", 6: "5", 7: "6", 8: "7", 9: "8", 10: "9", 11: "0",
    12: "-", 13: "=", 14: "BACKSPACE", 15: "TAB",
    16: "Q", 17: "W", 18: "E", 19: "R", 20: "T", 21: "Y", 22: "U", 23: "I", 24: "O", 25: "P",
    26: "[", 27: "]", 28: "ENTER", 29: "L_CTRL",
    30: "A", 31: "S", 32: "D", 33: "F", 34: "G", 35: "H", 36: "J", 37: "K", 38: "L",
    39: ";", 40: "'", 41: "`", 42: "L_SHIFT", 43: "\\",
    44: "Z", 45: "X", 46: "C", 47: "V", 48: "B", 49: "N", 50: "M",
    51: ",", 52: ".", 53: "/", 54: "R_SHIFT", 56: "L_ALT",
    57: "SPACE", 58: "CAPS", 59: "F1", 60: "F2", 61: "F3", 62: "F4", 63: "F5",
    64: "F6", 65: "F7", 66: "F8", 67: "F9", 68: "F10",
    87: "F11", 88: "F12", 96: "KP_ENTER", 97: "R_CTRL",
    100: "R_ALT", 102: "HOME", 103: "UP", 104: "PGUP", 105: "LEFT",
    106: "RIGHT", 107: "END", 108: "DOWN", 109: "PGDN",
    110: "INSERT", 111: "DELETE", 125: "SUPER",
    # мышь
    272: "ЛКМ", 273: "ПКМ", 274: "СКМ", 275: "Бок.назад", 276: "Бок.вперёд",
}


def locked():
    for pat in ("-x", "hyprlock"), ("-f", r"^\S*python\S* \S*jarvis_lock\.py"):
        if subprocess.run(["pgrep", pat[0], pat[1]], capture_output=True).returncode == 0:
            return True
    return False


def _find_camera():
    for d in sorted(glob.glob("/dev/video*")):
        try:
            if os.stat(d).st_mode:
                return d
        except OSError:
            continue
    return None


class Guard:
    def __init__(self, say, photo, send_file, log=print):
        self.say, self.photo, self.send_file, self.log = say, photo, send_file, log
        self.stop = threading.Event()
        self.threads = []
        self.lock = threading.Lock()
        self.last_input = 0.0
        self.keys_pressed = {}     # key_name → count
        self.mouse_moves = 0
        self.mouse_scrolls = 0
        self.session = False
        self.last_summary = 0.0
        self.windows = {}
        self.opened, self.closed = [], []
        self.was_locked = None
        self.procs = []
        self._mic_proc = None
        self._cam_proc = None

    # ── запуск/остановка ──
    def start(self):
        if self.threads:
            return
        self.stop.clear()
        self.was_locked = locked()
        self.last_input = 0.0
        self.session = False
        self.keys_pressed = {}
        self.mouse_moves = 0
        self.mouse_scrolls = 0
        for fn in (self.read_input, self.read_niri, self.read_journal, self.report_loop):
            t = threading.Thread(target=fn, daemon=True)
            t.start()
            self.threads.append(t)
        self.log("guard: включён")

    def halt(self):
        if not self.threads:
            return
        self.stop.set()
        self.stop_mic()
        self.stop_cam()
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
                    for i in range(0, len(data) - EV.size + 1, EV.size):
                        _sec, _usec, typ, code, value = EV.unpack_from(data, i)
                        if typ == EV_KEY and value == 1:
                            name = KEY_NAMES.get(code, "key_%d" % code)
                            with self.lock:
                                self.last_input = time.time()
                                self.keys_pressed[name] = self.keys_pressed.get(name, 0) + 1
                        elif typ == EV_REL:
                            with self.lock:
                                self.last_input = time.time()
                                if code in (8, 11):  # REL_WHEEL, REL_WHEEL_HI_RES
                                    self.mouse_scrolls += 1
                                else:
                                    self.mouse_moves += 1
                        elif typ == EV_ABS:
                            with self.lock:
                                self.last_input = time.time()
                                self.mouse_moves += 1
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

    # ── сводка ввода ──
    def _input_summary(self):
        with self.lock:
            keys = dict(self.keys_pressed)
            moves = self.mouse_moves
            scrolls = self.mouse_scrolls
            self.keys_pressed = {}
            self.mouse_moves = 0
            self.mouse_scrolls = 0

        lines = []
        mouse_btns = {}
        kbd_keys = {}
        for name, cnt in keys.items():
            if name in ("ЛКМ", "ПКМ", "СКМ", "Бок.назад", "Бок.вперёд"):
                mouse_btns[name] = cnt
            else:
                kbd_keys[name] = cnt

        total_keys = sum(kbd_keys.values())
        total_clicks = sum(mouse_btns.values())

        if kbd_keys:
            top = sorted(kbd_keys.items(), key=lambda x: -x[1])[:12]
            keys_str = ", ".join("%s×%d" % (k, v) if v > 1 else k for k, v in top)
            lines.append("⌨ Клавиши (%d): %s" % (total_keys, keys_str))

        if mouse_btns:
            btns_str = ", ".join("%s×%d" % (k, v) if v > 1 else k for k, v in mouse_btns.items())
            lines.append("🖱 Клики (%d): %s" % (total_clicks, btns_str))

        if moves:
            lines.append("🖱 Движение мыши: %d событий" % moves)

        if scrolls:
            lines.append("🖱 Прокрутка: %d" % scrolls)

        return lines, total_keys + total_clicks + moves + scrolls

    # ── камера и микрофон ──
    def take_photo(self):
        cam = _find_camera()
        if not cam:
            return None, "Камера не найдена."
        path = "/tmp/guard_photo_%d.jpg" % int(time.time())
        try:
            subprocess.run(["ffmpeg", "-y", "-f", "v4l2", "-i", cam,
                            "-frames:v", "1", path],
                           capture_output=True, timeout=10)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path, None
            return None, "Снимок пустой."
        except Exception as e:
            return None, str(e)

    def record_video(self, seconds=10):
        cam = _find_camera()
        if not cam:
            return None, "Камера не найдена."
        seconds = min(max(seconds, 3), 120)
        path = "/tmp/guard_video_%d.mp4" % int(time.time())
        try:
            subprocess.run(["ffmpeg", "-y", "-f", "v4l2", "-i", cam,
                            "-t", str(seconds), "-c:v", "libx264", "-preset", "ultrafast",
                            "-pix_fmt", "yuv420p", path],
                           capture_output=True, timeout=seconds + 15)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path, None
            return None, "Видео пустое."
        except Exception as e:
            return None, str(e)

    def record_mic(self, seconds=30):
        seconds = min(max(seconds, 3), 300)
        path = "/tmp/guard_mic_%d.ogg" % int(time.time())
        try:
            subprocess.run(["ffmpeg", "-y", "-f", "pulse", "-i", "default",
                            "-t", str(seconds), "-c:a", "libopus", path],
                           capture_output=True, timeout=seconds + 10)
            if os.path.exists(path) and os.path.getsize(path) > 0:
                return path, None
            return None, "Запись пустая."
        except Exception as e:
            return None, str(e)

    def start_mic_stream(self, seconds=60):
        if self._mic_proc and self._mic_proc.poll() is None:
            return None, "Микрофон уже пишет."
        seconds = min(max(seconds, 5), 600)
        path = "/tmp/guard_listen_%d.ogg" % int(time.time())
        try:
            self._mic_proc = subprocess.Popen(
                ["ffmpeg", "-y", "-f", "pulse", "-i", "default",
                 "-t", str(seconds), "-c:a", "libopus", path],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return path, None
        except Exception as e:
            return None, str(e)

    def stop_mic(self):
        if self._mic_proc and self._mic_proc.poll() is None:
            self._mic_proc.terminate()
            try:
                self._mic_proc.wait(5)
            except Exception:
                self._mic_proc.kill()
        self._mic_proc = None

    def stop_cam(self):
        if self._cam_proc and self._cam_proc.poll() is None:
            self._cam_proc.terminate()
            try:
                self._cam_proc.wait(5)
            except Exception:
                self._cam_proc.kill()
        self._cam_proc = None

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
                li = self.last_input
                op, cl = list(self.opened), list(self.closed)
            if li and not self.session and now - li < 30:
                self.session = True
                self.last_summary = now
                summary_lines, _ = self._input_summary()
                alert = "⚠ Кто-то трогает ПК (%s). Экран %s." % (
                    time.strftime("%H:%M:%S"), "заблокирован" if lk else "НЕ заблокирован")
                if summary_lines:
                    alert += "\n" + "\n".join(summary_lines)
                with self.lock:
                    self.opened, self.closed = [], []
                self.say(alert)
                self.photo("Экран сейчас")
            elif self.session:
                if now - li > QUIET:
                    self.session = False
                    self.say("Активность на ПК прекратилась (последнее касание в %s)." % time.strftime("%H:%M", time.localtime(li)))
                elif now - self.last_summary >= SUMMARY:
                    summary_lines, total = self._input_summary()
                    lines = []
                    if summary_lines:
                        lines.extend(summary_lines)
                    if op:
                        lines.append("Открыто: " + "; ".join(op[:6]))
                    if cl:
                        lines.append("Закрыто: " + "; ".join(cl[:6]))
                    if lines:
                        with self.lock:
                            self.opened, self.closed = [], []
                        self.last_summary = now
                        self.say("📊 Сводка за минуту:\n" + "\n".join(lines))
            elif (op or cl) and now - self.last_summary >= SUMMARY:
                with self.lock:
                    self.opened, self.closed = [], []
                self.last_summary = now
                self.say("На ПК без ввода: открыто %s; закрыто %s." % ("; ".join(op[:5]) or "—", "; ".join(cl[:5]) or "—"))
