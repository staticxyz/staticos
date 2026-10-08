#!/usr/bin/env python3
"""Постоянный исполнитель модулей верхнего waybar (05.10.2026, оптимизация CPU).

Раньше waybar запускал по интервалу новый python на каждый тик: mpris 2 с,
батарея 2 с, два браузера по 3 с, часы 5 с, pomo каждую секунду — на ДВУХ барах
(по экземпляру на монитор), ~7 запусков в секунду, ≈17 % ядра одним стартом
интерпретаторов. Здесь тот же код модуля вызывается в одном живом процессе:
вывод — побайтно тот же (та же функция печатает ту же строку), печатается
только при изменении, интервал тот же.

    wb_persist.py mpris                      mpris_status.main(), 2 с + события playerctl -F
    wb_persist.py battery                    savage_battery.get_battery_info(), 2 с
    wb_persist.py browser <класс> <подпись>  browser_status.main(), 3 с
    wb_persist.py clock                      waybar_clock.poll(), 5 с + смена минуты
                                             + inotify ~/.cache/waybar-calendar-side
    wb_persist.py pomo                       `pomo status json` — как раньше, сам скрипт;
                                             в простое (phase=idle) только когда сменились
                                             state/today/конфиг/дата; inotify на них

Сигналы обновления (pkill -RTMIN+N waybar) при постоянном exec waybar не
передаёт — поэтому здесь свои источники событий: playerctl -F для плеера
(щелчок play/pause), inotify на файлы состояния часов и pomo.

Процесс умирает вместе с waybar: PR_SET_PDEATHSIG + проверка родителя + EPIPE.
Откат: в ~/.config/waybar/config.jsonc вернуть exec/interval из config.jsonc.bak-wbopt,
пересобрать waybar_niri.py, barfix.
"""
import contextlib
import ctypes
import io
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

_libc = ctypes.CDLL(None, use_errno=True)
PR_SET_PDEATHSIG = 1


def _die_with_parent():
    _libc.prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)


# ── жизнь процесса ──────────────────────────────────────────────────────────
signal.signal(signal.SIGPIPE, signal.SIG_DFL)   # waybar закрыл трубу — тихо выходим
_die_with_parent()
PARENT = os.getppid()
if PARENT == 1:
    sys.exit(0)


def parent_alive():
    return os.getppid() == PARENT


_last = None


def emit(out):
    """Печатать строку модуля, только если она изменилась."""
    global _last
    if not out or out == _last:
        return
    _last = out
    try:
        sys.stdout.write(out)
        sys.stdout.flush()
    except (BrokenPipeError, OSError):
        os._exit(0)


_err_shown = set()


def capture(fn):
    """Вывод функции модуля как строка — ровно то, что она напечатала бы в waybar."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            fn()
    except Exception as e:  # модуль не должен застыть из-за одной ошибки
        key = repr(e)
        if key not in _err_shown:
            _err_shown.add(key)
            print("wb_persist: %s" % key, file=sys.stderr, flush=True)
        return None
    return buf.getvalue()


# ── inotify через libc ──────────────────────────────────────────────────────
IN_MODIFY, IN_CLOSE_WRITE, IN_MOVED_FROM, IN_MOVED_TO = 0x2, 0x8, 0x40, 0x80
IN_CREATE, IN_DELETE = 0x100, 0x200
WATCH_MASK = IN_CLOSE_WRITE | IN_MOVED_TO | IN_MOVED_FROM | IN_CREATE | IN_DELETE


class Inotify:
    def __init__(self):
        self.fd = _libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        self.names = {}          # wd -> набор имён, которые нас интересуют

    def watch(self, directory, names):
        if self.fd < 0:
            return
        try:
            os.makedirs(directory, exist_ok=True)
        except OSError:
            pass
        wd = _libc.inotify_add_watch(self.fd, os.fsencode(directory), WATCH_MASK)
        if wd >= 0:
            self.names.setdefault(wd, set()).update(names)

    def relevant(self):
        """Прочитать накопившиеся события: было ли что-то про наши файлы."""
        hit = False
        while True:
            try:
                data = os.read(self.fd, 65536)
            except BlockingIOError:
                return hit
            except OSError:
                return hit
            if not data:
                return hit
            i = 0
            while i + 16 <= len(data):
                wd, _mask, _cookie, ln = struct.unpack_from("iIII", data, i)
                name = data[i + 16:i + 16 + ln].rstrip(b"\0").decode("utf-8", "replace")
                i += 16 + ln
                if name in self.names.get(wd, ()):
                    hit = True


# ── окна niri: запрос в сокет вместо `niri msg -j windows` (тот же ответ) ──
def _niri_windows_json():
    path = os.environ.get("NIRI_SOCKET")
    if not path:
        return None
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(2)
    try:
        s.connect(path)
        s.sendall(b'"Windows"\n')
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    finally:
        s.close()
    reply = json.loads(buf)
    return json.dumps(reply["Ok"]["Windows"])


def patch_wm():
    import wm
    orig = wm._run

    def _run(cmd, timeout=3):
        if cmd == ["niri", "msg", "-j", "windows"]:
            try:
                out = _niri_windows_json()
                if out is not None:
                    return out
            except Exception:
                pass
        return orig(cmd, timeout)
    wm._run = _run


# ── общий цикл ──────────────────────────────────────────────────────────────
def loop(compute, interval, next_due=None, fds=(), on_fd=None, min_gap=0.0):
    """compute() → строка. Перезапуск по интервалу (отсчёт от прошлого вызова, как
    у waybar), по next_due() (абсолютное время), или по событию на fds."""
    emit(compute())
    last = time.monotonic()
    while True:
        if not parent_alive():
            os._exit(0)
        now = time.monotonic()
        due = last + interval
        if next_due is not None:
            due = min(due, next_due())
        timeout = max(0.0, due - now)
        r = []
        if fds:
            r, _, _ = select.select(list(fds), [], [], min(timeout, 30))
        else:
            time.sleep(min(timeout, 30))
        fire = time.monotonic() >= due
        if r and on_fd is not None and on_fd(r):
            if min_gap and time.monotonic() - last < min_gap:
                time.sleep(min_gap - (time.monotonic() - last))
            fire = True
        if fire:
            emit(compute())
            last = time.monotonic()


def mono_at(wall):
    """Абсолютное время по часам → время monotonic."""
    return time.monotonic() + (wall - time.time())


# ── режимы ──────────────────────────────────────────────────────────────────
def run_mpris():
    patch_wm()
    import mpris_status
    fmt = "\x1f".join(("{{playerInstance}}", "{{status}}", "{{title}}", "{{artist}}"))
    state = {"proc": None, "retry": 0.0}

    def start_follow():
        try:
            state["proc"] = subprocess.Popen(
                ["playerctl", "-a", "-F", "metadata", "--format", fmt],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                preexec_fn=_die_with_parent)
            os.set_blocking(state["proc"].stdout.fileno(), False)
        except OSError:
            state["proc"] = None
        state["retry"] = time.monotonic() + 30

    start_follow()

    def fds():
        p = state["proc"]
        return [p.stdout.fileno()] if p else []

    def on_fd(_r):
        p = state["proc"]
        try:
            data = os.read(p.stdout.fileno(), 65536)
        except BlockingIOError:
            return False
        if not data:                     # playerctl умер — живём опросом, потом пробуем снова
            try:
                p.wait(timeout=1)
            except Exception:
                pass
            state["proc"] = None
            return False
        time.sleep(0.05)                 # пачка событий (смена трека) — один пересчёт
        try:
            os.read(p.stdout.fileno(), 65536)
        except (BlockingIOError, OSError):
            pass
        return True

    def compute():
        if state["proc"] is None and time.monotonic() >= state["retry"]:
            start_follow()
        return capture(mpris_status.main)

    # fds меняются (перезапуск playerctl) — оборачиваем цикл вручную
    emit(compute())
    last = time.monotonic()
    while True:
        if not parent_alive():
            os._exit(0)
        timeout = max(0.0, last + 2 - time.monotonic())
        f = fds()
        r = select.select(f, [], [], timeout)[0] if f else (time.sleep(timeout) or [])
        fire = time.monotonic() >= last + 2
        if r and on_fd(r):
            fire = True
        if fire:
            emit(compute())
            last = time.monotonic()


def run_battery():
    import savage_battery
    loop(lambda: capture(savage_battery.get_battery_info), 2)


def run_browser(args):
    patch_wm()
    import browser_status
    argv = ["browser_status.py"] + args

    def compute():
        sys.argv = argv
        return capture(browser_status.main)
    loop(compute, 3)


def run_clock():
    import waybar_clock
    ino = Inotify()
    ino.watch(waybar_clock.CACHE_DIR, {os.path.basename(waybar_clock.SIDE_FILE)})

    def next_minute():
        t = time.time()
        return mono_at((int(t // 60) + 1) * 60 + 0.05)
    loop(lambda: capture(waybar_clock.poll), 5, next_due=next_minute,
         fds=[ino.fd] if ino.fd >= 0 else [], on_fd=lambda r: ino.relevant())


def run_pomo():
    pomo = os.path.expanduser("~/.local/bin/pomo")
    xdg_run = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    xdg_conf = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    run_dir = os.environ.get("POMO_RUN") or os.path.join(xdg_run, "pomo")
    conf = os.environ.get("POMO_CONF") or os.path.join(xdg_conf, "pomo", "config")
    state_f, today_f = os.path.join(run_dir, "state"), os.path.join(run_dir, "today")

    ino = Inotify()
    ino.watch(run_dir, {"state", "today"})
    ino.watch(os.path.dirname(conf), {os.path.basename(conf)})
    # режим фокуса (focus_mode.py, 06.10.2026) — в этой же ячейке, без своего модуля
    focus_state = os.path.expanduser("~/.config/hypr/state/focus.json")
    ino.watch(os.path.dirname(focus_state), {os.path.basename(focus_state)})
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import focus_mode
    except Exception:
        focus_mode = None
    blocks = {"t": 0.0, "n": 0}

    def st(path):
        try:
            s = os.stat(path)
            return (s.st_ino, s.st_mtime_ns, s.st_size)
        except OSError:
            return None

    def static_key():
        """Ключ, при неизменности которого `pomo status json` печатает то же самое.

        Простой (phase=idle): вывод зависит только от файлов state/today/конфига
        и от даты. Пауза: ещё и от «Конец в ЧЧ:ММ» = сейчас + остаток. Идёт отсчёт —
        цифры меняются каждую секунду: None, спрашиваем сам pomo (как раньше).
        Любая странность в файле — тоже None: лучше лишний запуск, чем застывший бар."""
        base = (st(state_f), st(today_f), st(conf), st(pomo), time.strftime("%F"))
        try:
            with open(state_f) as f:
                text = f.read()
        except FileNotFoundError:
            return base + ("idle",)          # нет файла — load() оставляет phase=idle
        except OSError:
            return None
        if text and not text.endswith("\n"):
            return None
        kv = {}
        for line in text.splitlines():
            k, _, v = line.partition("=")
            kv[k] = v
        phase = kv.get("phase", "idle")
        if phase == "idle":
            return base + ("idle",)
        nums = {}
        for k in ("started", "duration", "paused"):
            v = kv.get(k, "0")
            if not v.isdigit():
                return None
            nums[k] = int(v)
        if nums["paused"] <= 0:
            return None
        rem = max(0, nums["started"] + nums["duration"] - nums["paused"])
        return base + ("paused", time.strftime("%H:%M", time.localtime(int(time.time()) + rem)))

    cache = {"key": None, "out": None}

    def pomo_out():
        key = static_key()
        if key is not None and key == cache["key"]:
            return cache["out"]
        try:
            out = subprocess.run([pomo, "status", "json"], capture_output=True,
                                 text=True, timeout=10).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        cache["key"], cache["out"] = key, out
        return out

    def mmss(sec):
        sec = max(0, int(sec))
        h, rest = divmod(sec, 3600)
        return "%d:%02d:%02d" % (h, rest // 60, rest % 60) if h else "%02d:%02d" % (rest // 60, rest % 60)

    def compute():
        """Вывод pomo + фокус: идёт только фокус — «󰓾 42:10» (класс focus);
        идут оба — к цифрам помидора добавляется «󰓾» (класс …+focus-on)."""
        out = pomo_out()
        if focus_mode is None or not out:
            return out
        try:
            s = focus_mode.load()
            reason = focus_mode.effective(s)
        except Exception:
            return out
        if not reason:
            return out
        try:
            d = json.loads(out)
        except ValueError:
            return out
        now = time.time()
        if now - blocks["t"] > 15:
            try:
                blocks["n"] = focus_mode.today_stats()[0]
            except Exception:
                pass
            blocks["t"] = now
        if s["active"] and s["until"]:
            left, tip = s["until"] - now, "Фокус до " + time.strftime("%H:%M", time.localtime(s["until"]))
        elif s["active"]:
            left, tip = now - s["started"], "Фокус до отмены"
        else:
            left, tip = None, "Фокус на время помидора"
        if s.get("strict"):
            tip += " · строгий"
        tip += " · отвлечений: %d" % blocks["n"]
        cls = d.get("class", "idle")
        if cls == "idle" and left is not None:
            d["text"], d["class"] = "󰓾 " + mmss(left), "focus"
        else:
            d["text"] = d.get("text", "") + " 󰓾"
            d["class"] = [cls, "focus-on"]
        d["tooltip"] = tip + "\n\n" + d.get("tooltip", "")
        return json.dumps(d, ensure_ascii=False) + "\n"

    def next_second():
        t = time.time()
        return mono_at(int(t) + 1 + 0.02)
    loop(compute, 1, next_due=next_second,
         fds=[ino.fd] if ino.fd >= 0 else [], on_fd=lambda r: ino.relevant())


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: wb_persist.py mpris|battery|browser <cls> <label>|clock|pomo")
    mode = sys.argv[1]
    if mode == "mpris":
        run_mpris()
    elif mode == "battery":
        run_battery()
    elif mode == "browser":
        run_browser(sys.argv[2:])
    elif mode == "clock":
        run_clock()
    elif mode == "pomo":
        run_pomo()
    else:
        sys.exit("unknown mode " + mode)


if __name__ == "__main__":
    main()
