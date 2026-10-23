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

Микрофон — только настоящий: источник ALSA/bluez5 (гарнитура, встроенный, Bluetooth).
Что НЕ считается микрофоном: виртуальные источники, запись потока программы (pw-record
--target <плеер> у lyrics_sync.py), захват монитора выхода (cava, визуализаторы, звук системы
в jarvis_rec_mic), измерители уровня (pavucontrol «Peak detect», resample.peaks),
приостановленные (corked) и пассивные потоки.

Ключи: --ignore имя[,имя]  — не показывать эти приложения/процессы (сравнение без регистра
по началу имени), напр. --ignore gpu-screen-recorder чтобы Replay не зажигал экран.
       --once — напечатать состояние один раз и выйти (для проверки).
       --camera — режим отдельного модуля камеры (custom/camera): 󰖠 пока камера занята,
                  󱜷 пока выключена щелчком; основной модуль камеру больше не показывает.
       --toggle-camera — выключить/включить камеру (щелчок по значку камеры).
       --screen — режим отдельного модуля экрана (custom/screencast): 󱒃 пока экран
                  транслируется или пишется; основной модуль экран больше не показывает.
       --stop-screen — остановить всё, что показывает значок экрана (щелчок по нему).

Камера вынесена в свой модуль 22.10.2026 (просьба: «при нажатии на камеру чтобы она
отключалась, и наоборот при повторном чтобы включалась»): у одного модуля waybar один
щелчок, а ЛКМ основного уже глушит микрофон. Выключение — USB-устройство камеры
authorized=0 (система его отцепляет, /dev/video* пропадают); право на запись даёт
правило udev /etc/udev/rules.d/70-jarvis-camera.rules. Выключенная остаётся выключенной и
после перезагрузки: флаг ~/.config/hypr/state/camera-off, модуль камеры при старте
повторяет authorized=0.

Экран — тоже свой модуль, 22.10.2026 (просьба: «при клике на иконку… отключает запись
экрана? — Делай»). Щелчок останавливает: свою запись rec_area.sh — его же командой halt
(файл сохранится как при Esc), касты niri через PipeWire (Discord, браузер) — stop-cast,
прочие записчики (wf-recorder, wl-screenrec, gpu-screen-recorder) — SIGINT, как Ctrl+C:
файл у них дописывается. Скрытые --ignore не трогаются — их значок и не показывал.
Касты wlr-screencopy у niri по IPC не останавливаются (так в справке stop-cast).
"""
import ctypes
import json
import os
import re
import select
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
ICON_MUTED = "\U000F036D"   # 󰍭 mdi-microphone-off
ICON_CAM_OFF = "\U000F1737"  # 󱜷 mdi-webcam-off
CAM_OFF = os.path.expanduser("~/.config/hypr/state/camera-off")

TICK = 3.0          # период дешёвой проверки процессов-записчиков
DEBOUNCE = 0.15     # склейка пачки событий в одно перечитывание
RECORDER_COMMS = {  # /proc/pid/comm обрезан до 15 символов
    "gpu-screen-reco": "gpu-screen-recorder",
    "wf-recorder": "wf-recorder",
    "wl-screenrec": "wl-screenrec",
}
PEAK_NAMES = ("peak detect",)

IGNORE = []
SCREEN_ONLY = False     # --screen: модуль экрана; иначе основной — микрофон
REC_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-rec", "pid")
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
    # real — только живые микрофоны: гарнитура, встроенный, Bluetooth (ALSA/bluez5, не
    # монитор выхода). Виртуальные источники, мониторы и запись чужого потока (pw-record
    # --target <плеер>) значок не зажигают (23.10.2026, просьба: «значок означает, что
    # используется именно мой микрофон… гарнитуры или встроенного»).
    monitors, real = set(), set()
    for s in sources or []:
        name = s.get("name") or ""
        props = s.get("properties") or {}
        if s.get("monitor_of_sink") not in (None, "", "n/a") or name.endswith(".monitor"):
            monitors.add(s.get("index"))
        elif props.get("device.api") in ("alsa", "bluez5") or \
                name.startswith(("alsa_input.", "bluez_input.")):
            real.add(s.get("index"))
    apps = []
    for o in outputs:
        p = o.get("properties") or {}
        if o.get("source") in monitors or p.get("stream.capture.sink") == "true":
            continue
        # Запись не с источника, а с потока программы (pw-record --target <поток>: так
        # lyrics_sync.py пишет песню плеера) — у pactl источник «нет» (4294967295).
        # Это не микрофон (22.10.2026, просьба: «откуда взялась иконка микрофона?»).
        if sources is not None and o.get("source") not in real:
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


def mic_muted():
    """(заглушён ли, громкость %) микрофона по умолчанию: заглушён — в баре перечёркнутый
    значок; громкость — в подсказке (13.10.2026, просьба: «при наведении процент»)."""
    try:
        out = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False, None
    try:
        pct = round(float(out.split()[1]) * 100)
    except (IndexError, ValueError):
        pct = None
    return "[MUTED]" in out, pct


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
def tell_title(fname, n):
    """Число значков — в файл для bar_window_title.py и SIGUSR1 ему (он держит под них место)."""
    try:
        with open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), fname), "w") as f:
            f.write("%d\n" % n)
        for argv in proc_argvs():
            if len(argv[1]) and os.path.basename(argv[1]) == b"bar_window_title.py":
                os.kill(argv[0], signal.SIGUSR1)
    except OSError:
        pass


def proc_argvs():
    """[(pid, argv1, …)] своих процессов."""
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2:
                out.append((int(p), *argv[1:]))
    return out


# ─────────────────────────── выключатель камеры ───────────────────────────
def camera_usb():
    """Имена USB-устройств с видеоинтерфейсом (класс 0e): ['1-8']."""
    base = "/sys/bus/usb/devices"
    devs = set()
    for n in os.listdir(base):
        if ":" not in n:
            continue
        try:
            if open(f"{base}/{n}/bInterfaceClass").read().strip() == "0e":
                devs.add(n.split(":")[0])
        except OSError:
            pass
    return sorted(devs)


def set_authorized(devs, on):
    ok = True
    for d in devs:
        try:
            with open(f"/sys/bus/usb/devices/{d}/authorized", "w") as f:
                f.write("1" if on else "0")
        except OSError:
            ok = False
    return ok


def cam_off_devs():
    try:
        return open(CAM_OFF).read().split()
    except OSError:
        return None


def toggle_camera():
    off = cam_off_devs()
    if off is not None:
        ok = set_authorized(off, True)
        if ok:
            os.remove(CAM_OFF)
    else:
        devs = camera_usb()
        ok = bool(devs) and set_authorized(devs, False)
        if ok:
            os.makedirs(os.path.dirname(CAM_OFF), exist_ok=True)
            with open(CAM_OFF, "w") as f:
                f.write(" ".join(devs) + "\n")
    if not ok:
        subprocess.run(["notify-send", "-a", "Камера", "Камера",
                        "Нет права выключать камеру — нужно правило udev "
                        "/etc/udev/rules.d/70-jarvis-camera.rules"], stdin=subprocess.DEVNULL)
    for argv in proc_argvs():
        if (len(argv) >= 3 and os.path.basename(argv[1]) == b"privacy_status.py"
                and b"--camera" in argv[2:]):
            os.kill(argv[0], signal.SIGUSR1)


def render_camera(holders, off):
    if off:
        return {"text": ICON_CAM_OFF, "class": ["camera-off"],
                "tooltip": f"{ICON_CAM_OFF}  Камера выключена — щелчок включит"}
    if holders:
        uniq = ", ".join(dict.fromkeys(holders))
        return {"text": ICON["camera"], "class": ["camera"],
                "tooltip": f"{ICON['camera']}  Камера: {esc(uniq)}\nЩелчок — выключить камеру"}
    return {"text": "", "tooltip": "", "class": "idle"}


def camera_main(once):
    off = cam_off_devs()
    if off:
        # после перезагрузки устройство снова authorized=1 — выключить, как было
        set_authorized([d for d in off if os.path.exists(f"/sys/bus/usb/devices/{d}/authorized")
                        and open(f"/sys/bus/usb/devices/{d}/authorized").read().strip() == "1"], False)
    cam = CamWatch()
    poke = [False]
    signal.signal(signal.SIGUSR1, lambda *_: poke.__setitem__(0, True))
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    signal.signal(signal.SIGHUP, lambda *_: os._exit(0))
    last = None
    while True:
        line = json.dumps(render_camera(scan_camera(), cam_off_devs() is not None),
                          ensure_ascii=False)
        if line != last:
            last = line
            tell_title("jarvis-privacy-cam-n", 1 if '"text": ""' not in line else 0)
            try:
                sys.stdout.write(line + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                os._exit(0)
        if once:
            return
        # Выключенная камера — /dev/video* нет, её возвращение ловит IN_CREATE на /dev.
        try:
            r, _, _ = select.select([cam.fd] if cam.fd >= 0 else [], [], [], TICK)
        except InterruptedError:
            r = []
        if poke[0]:
            poke[0] = False
            time.sleep(0.3)      # отцепление/подключение устройства
        if r:
            time.sleep(DEBOUNCE)
            cam.drain()


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(state):
    active = [k for k in (("screen",) if SCREEN_ONLY else ORDER[:2]) if state[k]]
    if not active:
        return {"text": "", "tooltip": "", "class": "idle"}
    # Щелчок по значку глушит микрофон (config.jsonc, custom/privacy) — значок
    # это показывает: 󰍭 вместо 󰍬 и класс muted (13.10.2026, пользователь).
    muted = state.get("mute") and "mic" in active
    text = " ".join(ICON_MUTED if (k == "mic" and muted) else ICON[k] for k in active)
    lines = []
    for k in active:
        uniq = list(dict.fromkeys(state[k]))
        vol = f" — {state['micvol']}%" if k == "mic" and state.get("micvol") is not None else ""
        lines.append(f"{ICON[k]}  {LABEL[k]}{vol}: {esc(', '.join(uniq))}")
    if muted:
        lines.append("Микрофон заглушён — щелчок включит")
    if SCREEN_ONLY:
        lines.append("Щелчок — остановить")
    return {"text": text, "tooltip": "\n".join(lines), "class": active + (["muted"] if muted else [])}


def descendants(pid):
    kids = {}
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                kids.setdefault(int(open(f"/proc/{p}/stat").read().rsplit(")", 1)[1].split()[1]),
                                []).append(int(p))
            except (OSError, IndexError, ValueError):
                pass
    out, todo = set(), [pid]
    while todo:
        for c in kids.get(todo.pop(), []):
            if c not in out:
                out.add(c)
                todo.append(c)
    return out


def stop_screen():
    """Щелчок по значку экрана: остановить запись и трансляцию (см. описание вверху)."""
    stopped, own = [], set()
    try:
        rp = int(open(REC_PID).read().strip())
        os.kill(rp, 0)
        own = descendants(rp) | {rp}
        subprocess.Popen([os.path.join(os.path.dirname(os.path.abspath(__file__)), "rec_area.sh"), "halt"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        stopped.append("запись")
    except (OSError, ValueError):
        pass
    if os.environ.get("NIRI_SOCKET"):
        done = set()
        for c in run_json(["niri", "msg", "-j", "casts"]) or []:
            sid, pid = c.get("session_id"), c.get("pid")
            if sid is None or sid in done or pid in own or ignored(proc_name(pid) if pid else "?"):
                continue
            done.add(sid)
            if subprocess.run(["niri", "msg", "action", "stop-cast", "--session-id", str(sid)],
                              capture_output=True).returncode == 0:
                stopped.append(cast_label(c)[0])
    for pid, name in ProcTable().recorders().items():
        if pid in own or ignored(name):
            continue
        try:
            os.kill(pid, signal.SIGINT)
            stopped.append(name)
        except OSError:
            pass
    if stopped:
        subprocess.run(["notify-send", "-a", "Экран", "Экран", "Остановлено: " + ", ".join(dict.fromkeys(stopped))],
                       stdin=subprocess.DEVNULL)
    return 0


def main():
    global IGNORE, SCREEN_ONLY
    args = sys.argv[1:]
    once = "--once" in args
    if "--ignore" in args:
        i = args.index("--ignore")
        if i + 1 < len(args):
            IGNORE = [x.strip().lower() for x in args[i + 1].split(",") if x.strip()]
    if "--toggle-camera" in args:
        return toggle_camera()
    if "--camera" in args:
        return camera_main(once)
    if "--stop-screen" in args:
        return stop_screen()
    SCREEN_ONLY = "--screen" in args

    state = {"mic": [], "camera": [], "screen": []}
    casts = {}          # stream_id → cast (niri) / "hypr" → флаг
    proc = ProcTable()

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

    mic = None if SCREEN_ONLY else scan_mic()
    state["mic"] = mic or []
    state["mute"], state["micvol"] = (None, None) if SCREEN_ONLY else mic_muted()
    if SCREEN_ONLY and os.environ.get("NIRI_SOCKET"):
        for c in run_json(["niri", "msg", "-j", "casts"]) or []:
            casts[c.get("stream_id")] = c
    state["screen"] = screen_list() if SCREEN_ONLY else []
    last = None

    def emit():
        nonlocal last
        line = json.dumps(render(state), ensure_ascii=False)
        if line != last:
            last = line
            # Сколько значков показано — для заголовка окна (bar_window_title.py): он
            # оставляет под них место, иначе длинный заголовок + значок микрофона
            # выдавливали бар вправо и кнопка питания уезжала за экран (01.10.2026).
            tell_title("jarvis-privacy-scr-n" if SCREEN_ONLY else "jarvis-privacy-n",
                       sum(1 for k in ORDER if state[k]))
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

    # основному — только микрофон (pactl), модулю экрана — только касты
    kinds = [] if SCREEN_ONLY else ["pactl"]
    if SCREEN_ONLY and os.environ.get("NIRI_SOCKET"):
        kinds.append("niri")
    elif SCREEN_ONLY and os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
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
                    elif b"'change' on source #" in ln:
                        dirty.add("mute")    # заглушили / сменили громкость
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
            if SCREEN_ONLY:
                dirty.add("screen")      # процессы-записчики
        if (due is not None and now >= due) or ("screen" in dirty and due is None):
            if "mic" in dirty:
                m = scan_mic()
                if m is not None:
                    state["mic"] = m
            if "mute" in dirty or "mic" in dirty:
                state["mute"], state["micvol"] = mic_muted()
            if "screen" in dirty:
                state["screen"] = screen_list()
            dirty.clear()
            due = None
            emit()


if __name__ == "__main__":
    main()
