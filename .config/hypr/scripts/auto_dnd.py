#!/usr/bin/env python3
"""Авто-«Не беспокоить» на время записи и трансляции экрана и на время игры. 02.10.2026.

    auto_dnd.py              сторож (автозапуск niri; второй экземпляр выходит)
    auto_dnd.py on|off       включить / выключить (Настройки → Misc)
    auto_dnd.py status       on | off
    auto_dnd.py now          что сторож видит сейчас (для проверки)

Идея — из дотфайлов AngelOS, код свой. Просьба: «авто "не беспокоить" попробуй
сделать, вроде полезно». Уведомление, всплывшее посреди записи или демонстрации
экрана, попадает в кадр — на это время DND включается сам и сам же снимается.

Что считается «идёт запись»:
  * наша запись (rec_area.sh: GIF, видео, стикер) — пока жив файл
    $XDG_RUNTIME_DIR/jarvis-rec/pid. Именно pid, а не папка: его rec_area стирает
    в момент остановки, ДО уведомления «Сохранено», — оно должно всплыть как обычно;
  * активная трансляция экрана через niri (Telegram, Discord, OBS, браузер) —
    события Cast* из `niri msg event-stream`.
  * запущена игра (cs2, gamescope) — с 06.10.2026, проверка раз в 5 с.
Replay (gpu-screen-recorder в фоне, «задним числом») записью НЕ считается: он
работает часами, DND на всё это время никому не нужен. niri его и не видит (KMS).

Правила, чтобы не мешать ручному режиму:
  * DND уже был включён — не трогаем ни в начале, ни в конце;
  * включили мы — в конце снимаем (метка ~/.cache/jarvis-auto-dnd; она переживает
    выход из сеанса, поэтому оборванная запись не оставит DND навсегда);
  * посреди записи DND сняли руками — заново не включаем.

Попутно (чтобы не держать второй поток событий niri): на событие ScreenshotCaptured
запускает звук снимка — ui_sound.py play screenshot.

Процессор: ноль. Спит в select на inotify и на потоке событий niri; опросов нет.
Подписка на niri — с PDEATHSIG, сирот не остаётся.
"""
import ctypes
import json
import os
import select
import signal
import struct
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
REC_DIR = os.path.join(RUN, "jarvis-rec")
REC_PID = os.path.join(REC_DIR, "pid")
OFF = os.path.expanduser("~/.config/hypr/state/auto-dnd-off")
OURS = os.path.expanduser("~/.cache/jarvis-auto-dnd")

if sys.argv[1:2] in (["on"], ["off"], ["status"]):
    if sys.argv[1] == "on":
        try:
            os.remove(OFF)
        except OSError:
            pass
    elif sys.argv[1] == "off":
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
    print("off" if os.path.exists(OFF) else "on")
    sys.exit(0)

_libc = ctypes.CDLL(None, use_errno=True)
IN_CREATE, IN_DELETE, IN_MOVED_FROM, IN_MOVED_TO = 0x100, 0x200, 0x40, 0x80
IN_DELETE_SELF, IN_NONBLOCK = 0x400, 0x800
MASK = IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO | IN_DELETE_SELF


def _pdeathsig():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)      # PR_SET_PDEATHSIG


def swaync(*args):
    try:
        return subprocess.run(["swaync-client", *args], capture_output=True, text=True,
                              timeout=3).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def niri_casts():
    try:
        out = subprocess.run(["niri", "msg", "-j", "casts"], capture_output=True, text=True,
                             timeout=2).stdout
        return {c.get("stream_id"): c for c in json.loads(out or "[]")}
    except (OSError, ValueError, subprocess.SubprocessError):
        return {}


GAMES = (b"cs2", b"gamescope")


def gaming():
    """Запущена игра (06.10.2026, Просьба: «почему во время запуска игры не включается
    Выключить уведомления?»). Те же процессы, что у ui_sound / сторожа бара."""
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


def busy(casts):
    if os.path.exists(REC_PID):
        return "запись (rec_area)"
    if gaming():
        return "игра"
    for c in casts.values():
        if c.get("is_active", True):
            return "трансляция экрана"
    return ""


LOG = os.path.expanduser("~/.cache/jarvis-auto-dnd.log")


def log(text):
    """Журнал включений/снятий (02.10.2026): пользователь застал DND включённым и не знал,
    кто и когда его включил. Теперь каждое наше действие — строкой со временем."""
    try:
        import time
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%F %T"), text))
        if os.path.getsize(LOG) > 200_000:
            lines = open(LOG).read().splitlines()[-500:]
            with open(LOG, "w") as f:
                f.write("\n".join(lines) + "\n")
    except OSError:
        pass


class Guard:
    def __init__(self):
        self.active = False

    def apply(self, why):
        want = bool(why) and not os.path.exists(OFF)
        if want and not self.active:
            state = swaync("-D")
            if state == "false":
                swaync("-dn")
                open(OURS, "w").close()
                log("ВКЛ: %s (стало: %s)" % (why, swaync("-D")))
            else:
                log("не трогаю: %s, DND уже «%s»" % (why, state))
        elif not want and os.path.exists(OURS):
            # снимаем своё. Ответ swaync здесь не решает: пустой ответ (таймаут) раньше
            # означал «не снимать» — и DND мог остаться навсегда; теперь снимаем всегда
            # и перепроверяем.
            before = swaync("-D")
            if before != "false":
                swaync("-df")
                after = swaync("-D")
                if after == "true":
                    swaync("-df")
                    after = swaync("-D")
                log("СНЯЛ (было: «%s», стало: «%s»)" % (before, after))
            else:
                log("метка была, но DND уже снят руками")
            try:
                os.remove(OURS)
            except OSError:
                pass
        self.active = want


def main():
    if sys.argv[1:2] == ["now"]:
        print("запись:", busy(niri_casts()) or "нет", "| DND:", swaync("-D"),
              "| включён нами:", os.path.exists(OURS), "| сторож:", "off" if os.path.exists(OFF) else "on")
        return
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"auto_dnd.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                return

    ino = _libc.inotify_init1(IN_NONBLOCK)
    _libc.inotify_add_watch(ino, RUN.encode(), IN_CREATE | IN_DELETE | IN_MOVED_FROM | IN_MOVED_TO)
    rec_wd = -1

    def watch_rec():
        nonlocal rec_wd
        if os.path.isdir(REC_DIR):
            rec_wd = _libc.inotify_add_watch(ino, REC_DIR.encode(), MASK)

    watch_rec()
    casts = niri_casts()
    guard = Guard()
    guard.apply(busy(casts))

    stream = None
    buf = b""

    def open_stream():
        nonlocal stream, buf
        buf = b""
        try:
            stream = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                      stderr=subprocess.DEVNULL, preexec_fn=_pdeathsig)
            os.set_blocking(stream.stdout.fileno(), False)
        except OSError:
            stream = None

    open_stream()
    while True:
        fds = [ino] + ([stream.stdout.fileno()] if stream else [])
        try:
            # раз в 5 с — даже без событий: запуск и выход из игры событий не дают
            r, _, _ = select.select(fds, [], [], 5)
        except (OSError, ValueError):
            r = []
        if not stream:
            open_stream()
            casts = niri_casts()
        if ino in r:
            try:
                data = os.read(ino, 65536)
            except OSError:
                data = b""
            i = 0
            while i + 16 <= len(data):
                _wd, _mask, _ck, ln = struct.unpack_from("iIII", data, i)
                name = data[i + 16:i + 16 + ln].split(b"\0", 1)[0]
                i += 16 + ln
                if name == b"jarvis-rec":
                    watch_rec()
        if stream and stream.stdout.fileno() in r:
            try:
                chunk = os.read(stream.stdout.fileno(), 65536)
            except BlockingIOError:
                chunk = None
            except OSError:
                chunk = b""
            if chunk == b"":                       # niri перезапущен — переподключиться
                try:
                    stream.kill()
                    stream.wait(timeout=1)
                except (OSError, subprocess.SubprocessError):
                    pass
                stream = None
            elif chunk:
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for ln in lines:
                    if ln.startswith(b'{"ScreenshotCaptured'):
                        # попутно: звук снимка экрана (ui_sound.py) — поток событий niri
                        # у нас уже открыт, отдельный сторож ради одного события не нужен
                        try:
                            subprocess.Popen([sys.executable, os.path.join(HERE, "ui_sound.py"),
                                              "play", "screenshot"], stdin=subprocess.DEVNULL,
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
                        except OSError:
                            pass
                        continue
                    if not ln.startswith(b'{"Cast'):
                        continue
                    try:
                        ev = json.loads(ln)
                    except ValueError:
                        continue
                    if "CastsChanged" in ev:
                        casts = {c.get("stream_id"): c for c in ev["CastsChanged"].get("casts", [])}
                    elif "CastStartedOrChanged" in ev:
                        c = ev["CastStartedOrChanged"].get("cast", {})
                        casts[c.get("stream_id")] = c
                    elif "CastStopped" in ev:
                        casts.pop(ev["CastStopped"].get("stream_id"), None)
        guard.apply(busy(casts))


if __name__ == "__main__":
    main()
