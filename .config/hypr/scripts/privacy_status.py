#!/usr/bin/env python3
"""Индикаторы приватности для waybar (30.09.2026, по мотивам Noctalia).

Значки появляются ТОЛЬКО пока что-то занято:
  󰍬 mic     — кто-то пишет с микрофона (source-output PipeWire/Pulse на НЕ-мониторном источнике)
  󰖠 camera  — какой-то процесс держит открытым /dev/video*
  󱒃 screen  — идёт трансляция/запись экрана (касты niri, событие screencast Hyprland,
              процессы gpu-screen-recorder / wf-recorder / wl-screenrec)
Ничего не занято — пустой text, waybar прячет модуль.

Работает непрерывно (waybar custom без interval) и печатает строку JSON только при смене
состояния. Всё по событиям, опросов почти нет:
  - микрофон: `pactl subscribe` → перечитать source-outputs, только на события source-output/source;
  - камера: inotify IN_OPEN/IN_CLOSE на /dev/video* → разовый обход /proc/*/fd;
  - экран: `niri msg -j event-stream` (события Cast*) или socket2 Hyprland;
  - раз в 3 с: список /proc (имена читаются только у НОВЫХ pid) — ищем процессы-записчики,
    которые niri не видит (gpu-screen-recorder в режиме KMS, например Replay).
Дочерние процессы получают PDEATHSIG — не переживут скрипт.

Что НЕ считается микрофоном: захват монитора выхода (cava, визуализаторы, звук системы
в jarvis_rec_mic), измерители уровня (pavucontrol «Peak detect», resample.peaks),
приостановленные (corked) и пассивные потоки.

Ключи: --ignore имя[,имя]  — не показывать эти приложения/процессы (сравнение без регистра
по началу имени), напр. --ignore gpu-screen-recorder чтобы Replay не зажигал экран.
       --once — напечатать состояние один раз и выйти (для проверки).
"""
import ctypes
import json
import os
import re
import selectors
import signal
import socket
import struct
import subprocess
import sys
import time

ICON = {"mic": "\U000F036C", "camera": "\U000F05A0", "screen": "\U000F1483"}
LABEL = {"mic": "Микрофон", "camera": "Камера", "screen": "Экран"}
ORDER = ("mic", "camera", "screen")

TICK = 3.0          # период дешёвой проверки процессов-записчиков
DEBOUNCE = 0.15     # склейка пачки событий в одно перечитывание
RECORDER_COMMS = {  # /proc/pid/comm обрезан до 15 символов
    "gpu-screen-reco": "gpu-screen-recorder",
    "wf-recorder": "wf-recorder",
    "wl-screenrec": "wl-screenrec",
}
PEAK_NAMES = ("peak detect",)

IGNORE = []
_libc = ctypes.CDLL(None, use_errno=True)


def _pdeathsig():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)  # PR_SET_PDEATHSIG


def spawn(argv):
    try:
        return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, preexec_fn=_pdeathsig, bufsize=0)
    except OSError:
        return None


def run_json(argv):
    try:
        out = subprocess.run(argv, capture_output=True, timeout=3, stdin=subprocess.DEVNULL).stdout
        return json.loads(out or b"null")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def ignored(name):
    n = name.lower()
    return any(n.startswith(i) for i in IGNORE)


def proc_name(pid):
    """Понятное имя процесса: basename exe, иначе comm."""
    try:
        exe = os.path.basename(os.readlink(f"/proc/{pid}/exe"))
        if exe and not re.match(r"(python[\d.]*|bash|sh|zsh|fish|dash)$", exe):
            return exe.removesuffix(" (deleted)")
    except OSError:
        pass
    try:
        with open(f"/proc/{pid}/comm") as f:
            return f.read().strip()
    except OSError:
        return f"pid {pid}"


# ─────────────────────────── микрофон ───────────────────────────
def scan_mic():
    sources = run_json(["pactl", "-f", "json", "list", "sources"])
    outputs = run_json(["pactl", "-f", "json", "list", "source-outputs"])
    if outputs is None:
        return None  # pactl недоступен — оставить прежнее состояние
    monitors = set()
    for s in sources or []:
        name = s.get("name") or ""
        if s.get("monitor_of_sink") not in (None, "", "n/a") or name.endswith(".monitor"):
            monitors.add(s.get("index"))
    apps = []
    for o in outputs:
        p = o.get("properties") or {}
        if o.get("source") in monitors or p.get("stream.capture.sink") == "true":
            continue
        if o.get("corked") or p.get("node.passive") == "true":
            continue
        media = (p.get("media.name") or "").lower()
        if p.get("resample.peaks") == "true" or any(k in media for k in PEAK_NAMES):
            continue
        name = (p.get("application.name") or p.get("application.process.binary")
                or p.get("node.description") or p.get("node.name") or p.get("media.name") or "?")
        if ignored(name) or ignored(p.get("application.process.binary") or name):
            continue
        apps.append(name)
    return apps


# ─────────────────────────── камера ───────────────────────────
IN_OPEN, IN_CLOSE_WRITE, IN_CLOSE_NOWRITE, IN_CREATE, IN_IGNORED = 0x20, 0x08, 0x10, 0x100, 0x8000


class CamWatch:
    """inotify на /dev/video*: любое открытие/закрытие → повод пересканировать держателей."""

    def __init__(self):
        self.fd = _libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
        self.wds = {}
        if self.fd < 0:
            return
        _libc.inotify_add_watch(self.fd, b"/dev", IN_CREATE)
        for n in os.listdir("/dev"):
            if n.startswith("video"):
                self.add(n)

    def add(self, name):
        wd = _libc.inotify_add_watch(self.fd, f"/dev/{name}".encode(),
                                     IN_OPEN | IN_CLOSE_WRITE | IN_CLOSE_NOWRITE)
        if wd >= 0:
            self.wds[wd] = name

    @property
    def ok(self):
        return self.fd >= 0 and bool(self.wds)

    def drain(self):
        """True, если было событие на камере."""
        hit = False
        try:
            buf = os.read(self.fd, 16384)
        except BlockingIOError:
            return False
        i = 0
        while i + 16 <= len(buf):
            wd, mask, _cookie, ln = struct.unpack_from("iIII", buf, i)
            name = buf[i + 16:i + 16 + ln].split(b"\0", 1)[0].decode(errors="replace")
            i += 16 + ln
            if mask & IN_CREATE and name.startswith("video"):
                self.add(name)
                hit = True
            elif mask & IN_IGNORED:
                self.wds.pop(wd, None)
                hit = True
            elif wd in self.wds:
                hit = True
        return hit


def scan_camera():
    """Процессы (свои — чужие /proc/*/fd не читаются), держащие /dev/video*."""
    holders = {}
    for e in os.scandir("/proc"):
        if not e.name.isdigit():
            continue
        try:
            fds = os.scandir(f"/proc/{e.name}/fd")
        except OSError:
            continue
        with fds:
            for fd in fds:
                try:
                    if os.readlink(fd.path).startswith("/dev/video"):
                        holders[int(e.name)] = proc_name(e.name)
                        break
                except OSError:
                    pass
    names = []
    for pid, name in holders.items():
        if name in ("pipewire", "wireplumber"):
            # Камера через PipeWire (портал камеры): настоящий потребитель — Stream/Input/Video.
            nodes = run_json(["pw-dump"]) or []
            users = [
                (o.get("info", {}).get("props", {}).get("application.name")
                 or o.get("info", {}).get("props", {}).get("node.name"))
                for o in nodes
                if o.get("type") == "PipeWire:Interface:Node"
                and o.get("info", {}).get("props", {}).get("media.class") == "Stream/Input/Video"
            ]
            users = [u for u in users if u]
            names.extend(users or ["PipeWire"])
        else:
            names.append(name)
    return [n for n in names if not ignored(n)]


# ─────────────────────────── экран ───────────────────────────
class ProcTable:
    """Кэш pid→comm; на каждом тике читаются только новые pid."""

    def __init__(self):
        self.comm = {}

    def recorders(self):
        pids = {int(n) for n in os.listdir("/proc") if n.isdigit()}
        for gone in self.comm.keys() - pids:
            del self.comm[gone]
        for pid in pids - self.comm.keys():
            try:
                with open(f"/proc/{pid}/comm") as f:
                    self.comm[pid] = f.read().strip()
            except OSError:
                self.comm[pid] = ""
        return {pid: RECORDER_COMMS[c] for pid, c in self.comm.items() if c in RECORDER_COMMS}


def cast_label(c):
    pid = c.get("pid")
    who = proc_name(pid) if pid else "?"
    t = c.get("target") or {}
    if "Output" in t:
        what = f"экран {t['Output'].get('name', '')}".strip()
    elif "Window" in t:
        what = f"окно #{t['Window'].get('id', '')}"
    else:
        what = "без цели"
    return who, what


# ─────────────────────────── вывод ───────────────────────────
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(state):
    active = [k for k in ORDER if state[k]]
    if not active:
        return {"text": "", "tooltip": "", "class": "idle"}
    text = " ".join(ICON[k] for k in active)
    lines = []
    for k in active:
        uniq = list(dict.fromkeys(state[k]))
        lines.append(f"{ICON[k]}  {LABEL[k]}: {esc(', '.join(uniq))}")
    return {"text": text, "tooltip": "\n".join(lines), "class": active}


def main():
    global IGNORE
    args = sys.argv[1:]
    once = "--once" in args
    if "--ignore" in args:
        i = args.index("--ignore")
        if i + 1 < len(args):
            IGNORE = [x.strip().lower() for x in args[i + 1].split(",") if x.strip()]

    state = {"mic": [], "camera": [], "screen": []}
    casts = {}          # stream_id → cast (niri) / "hypr" → флаг
    proc = ProcTable()
    cam = CamWatch()

    def screen_list():
        out, cast_pids = [], set()
        for c in casts.values():
            if c.get("hypr"):
                out.append("Hyprland screencast")
                continue
            if not c.get("is_active", True):
                continue
            who, what = cast_label(c)
            cast_pids.add(c.get("pid"))
            if not ignored(who):
                out.append(f"{who} ({what})")
        for pid, name in proc.recorders().items():
            if pid not in cast_pids and not ignored(name):
                out.append(name)
        return out

    mic = scan_mic()
    state["mic"] = mic or []
    state["camera"] = scan_camera()
    if os.environ.get("NIRI_SOCKET"):
        for c in run_json(["niri", "msg", "-j", "casts"]) or []:
            casts[c.get("stream_id")] = c
    state["screen"] = screen_list()
    last = None

    def emit():
        nonlocal last
        line = json.dumps(render(state), ensure_ascii=False)
        if line != last:
            last = line
            # Сколько значков показано — для заголовка окна (bar_window_title.py): он
            # оставляет под них место, иначе длинный заголовок + значок микрофона
            # выдавливали бар вправо и кнопка питания уезжала за экран (01.10.2026).
            try:
                n = sum(1 for k in ORDER if state[k])
                path = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-privacy-n")
                with open(path, "w") as f:
                    f.write("%d\n" % n)
                for p in os.listdir("/proc"):
                    if p.isdigit():
                        try:
                            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
                        except OSError:
                            continue
                        if len(argv) >= 2 and os.path.basename(argv[1]) == b"bar_window_title.py":
                            os.kill(int(p), signal.SIGUSR1)
            except OSError:
                pass
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                cleanup()

    children = {}

    def cleanup(*_):
        for p in list(children.values()):
            if isinstance(p, subprocess.Popen):
                try:
                    p.terminate()
                except OSError:
                    pass
        os._exit(0)

    emit()
    if once:
        return
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGHUP, cleanup)

    sel = selectors.DefaultSelector()
    if cam.ok:
        sel.register(cam.fd, selectors.EVENT_READ, "cam")

    bufs = {}
    retry = {"pactl": 0.0, "niri": 0.0, "hypr": 0.0}

    def start(kind):
        if kind == "pactl":
            p = spawn(["pactl", "subscribe"])
        elif kind == "niri":
            p = spawn(["niri", "msg", "-j", "event-stream"])
        else:
            sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
            path = f"{os.environ.get('XDG_RUNTIME_DIR', '/tmp')}/hypr/{sig}/.socket2.sock"
            try:
                p = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM | socket.SOCK_CLOEXEC)
                p.connect(path)
            except OSError:
                p = None
        if p is None:
            retry[kind] = time.monotonic() + 5
            return
        children[kind] = p
        bufs[kind] = b""
        sel.register(p.stdout if isinstance(p, subprocess.Popen) else p, selectors.EVENT_READ, kind)

    def stop(kind):
        p = children.pop(kind, None)
        if p is None:
            return
        f = p.stdout if isinstance(p, subprocess.Popen) else p
        try:
            sel.unregister(f)
        except (KeyError, ValueError):
            pass
        if isinstance(p, subprocess.Popen):
            p.terminate()
            try:
                p.wait(1)
            except subprocess.TimeoutExpired:
                p.kill()
        else:
            p.close()
        retry[kind] = time.monotonic() + 2

    kinds = ["pactl"]
    if os.environ.get("NIRI_SOCKET"):
        kinds.append("niri")
    elif os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        kinds.append("hypr")
    for k in kinds:
        start(k)

    dirty = set()
    due = None
    next_tick = time.monotonic() + TICK

    while True:
        now = time.monotonic()
        wake = min(x for x in (next_tick, due, *[retry[k] for k in kinds if k not in children and retry[k]]) if x)
        for key, _ in sel.select(max(0.0, wake - now)):
            kind = key.data
            if kind == "cam":
                if cam.drain():
                    dirty.add("camera")
                continue
            p = children.get(kind)
            f = p.stdout if isinstance(p, subprocess.Popen) else p
            try:
                chunk = os.read(f.fileno(), 65536)
            except OSError:
                chunk = b""
            if not chunk:
                stop(kind)
                dirty.add("mic" if kind == "pactl" else "screen")
                if kind != "pactl":
                    casts.clear()
                continue
            data = bufs[kind] + chunk
            *lines, bufs[kind] = data.split(b"\n")
            for ln in lines:
                if kind == "pactl":
                    if b"source-output" in ln or (b"on source #" in ln and b"'change'" not in ln):
                        dirty.add("mic")
                elif kind == "niri":
                    if not ln.startswith(b'{"Cast'):
                        continue  # окна/столы — мимо, даже не разбираем JSON
                    try:
                        ev = json.loads(ln)
                    except ValueError:
                        continue
                    if "CastsChanged" in ev:
                        casts.clear()
                        for c in ev["CastsChanged"].get("casts", []):
                            casts[c.get("stream_id")] = c
                    elif "CastStartedOrChanged" in ev:
                        c = ev["CastStartedOrChanged"].get("cast", {})
                        casts[c.get("stream_id")] = c
                    elif "CastStopped" in ev:
                        casts.pop(ev["CastStopped"].get("stream_id"), None)
                    dirty.add("screen")
                elif kind == "hypr" and ln.startswith(b"screencast>>"):
                    on = ln.split(b">>", 1)[1].split(b",", 1)[0] == b"1"
                    if on:
                        casts["hypr"] = {"hypr": True}
                    else:
                        casts.pop("hypr", None)
                    dirty.add("screen")
            if dirty and due is None:
                due = time.monotonic() + DEBOUNCE
        if dirty and due is None:
            due = time.monotonic() + DEBOUNCE

        now = time.monotonic()
        for k in kinds:
            if k not in children and retry[k] and now >= retry[k]:
                retry[k] = 0.0
                start(k)
                dirty.add("mic" if k == "pactl" else "screen")
                if k == "niri":
                    casts.clear()
                    for c in run_json(["niri", "msg", "-j", "casts"]) or []:
                        casts[c.get("stream_id")] = c
        if now >= next_tick:
            next_tick = now + TICK
            dirty.add("screen")          # процессы-записчики
            if not cam.ok:
                dirty.add("camera")      # запасной путь без inotify — обход /proc
        if (due is not None and now >= due) or ("screen" in dirty and due is None):
            if "mic" in dirty:
                m = scan_mic()
                if m is not None:
                    state["mic"] = m
            if "camera" in dirty:
                state["camera"] = scan_camera()
            if "screen" in dirty:
                state["screen"] = screen_list()
            dirty.clear()
            due = None
            emit()


if __name__ == "__main__":
    main()
