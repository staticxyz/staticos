#!/usr/bin/env python3
"""Режим фокуса под niri (06.10.2026; сменил hypr-focus-guard — тот ругал за новые
столы Hyprland, а отвлекаться можно и на уже открытых окнах).

Пока фокус включён:
  • окно, чей заголовок (или app-id) совпал с правилом блокировки (YouTube, Twitch…),
    закрывается слоем «Фокус» во весь монитор, пока оно в фокусе. Клавиатура
    остаётся у окна: Ctrl+W закрыть вкладку, Ctrl+L уйти на другой адрес — и слой
    пропадёт сам. Кнопка на слое возвращает к последнему рабочему окну;
  • плееры (MPRIS), чей адрес или название совпали с правилом, ставятся на паузу —
    и в фоне тоже, чтобы YouTube не играл «просто звуком»;
  • каждая встреча с запрещённым окном — «отвлечение», счёт за день виден в окне
    Routine (вкладка Focus) и в `focus status`.
Фокус — сессия на время (25m, 1h…) или до отмены; можно ещё «авто с помидором»
(включён, пока идёт рабочий отрезок pomo) и «перерывы» (на перерыве pomo
блокировки нет).

    focus_mode.py on [ВРЕМЯ]     начать: 25m, 1h30m, 90 (минуты); без времени — до отмены
    focus_mode.py off [--force]  закончить раньше (из терминала спросит подтверждение)
    focus_mode.py add [+ВРЕМЯ]   продлить (по умолчанию на 15 минут)
    focus_mode.py status [--json]
    focus_mode.py block ИМЯ [ШАБЛОН…] | unblock ИМЯ | list
    focus_mode.py strict [on|off]  строгий режим: сессию не завершить и правила не ослабить
    focus_mode.py allow [on|off|СЛОВА…]  исключения для учёбы (слово в названии ролика)
    focus_mode.py log            журнал за сегодня
    focus_mode.py daemon         сторож (служба jarvis-focus.service)
    focus_mode.py overlay ИМЯ [ВЫХОД] [ID-ОКНА]   слой «Фокус» (зовёт сторож)

Состояние — ~/.config/hypr/state/focus.json, журнал — ~/.local/state/jarvis-focus/log.tsv
(эпоха, событие start|stop|block|end, подпись).
"""
import ctypes
import datetime as dt
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/focus.json")
LOGDIR = os.path.expanduser("~/.local/state/jarvis-focus")
LOG = os.path.join(LOGDIR, "log.tsv")
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
POMO_STATE = os.path.join(RUN, "pomo", "state")
UNIT = "jarvis-focus.service"

DEFAULT_BLOCKS = [
    {"label": "YouTube", "match": "youtube|youtu\\.be", "on": True},
    {"label": "Twitch", "match": "twitch", "on": True},
    {"label": "TikTok", "match": "tiktok", "on": True},
    {"label": "Instagram", "match": "instagram", "on": True},
    {"label": "Reddit", "match": "reddit", "on": True},
    {"label": "VK", "match": "вконтакте|vk видео|vk\\.com|vkvideo", "on": True},
    {"label": "Rutube", "match": "rutube", "on": True},
    {"label": "Netflix", "match": "netflix", "on": True},
    {"label": "Steam", "app": "^steam$", "on": False},
    {"label": "CS2", "app": "^cs2$|gamescope", "on": False},
    {"label": "Discord", "app": "discord|vesktop", "on": False},
    {"label": "Telegram", "app": "org\\.telegram\\.desktop", "on": False},
    {"label": "Claude", "match": "claude", "on": False},
    {"label": "Codex", "match": "codex", "on": False},
]
# Учёба по видео: слово из списка в заголовке/названии — ролик можно и в фокусе
# (только для правил по заголовку; правила по app-id исключений не знают).
DEFAULT_ALLOW = ["java", "spring", "kotlin", "python", "sql", "docker", "linux", "git",
                 "leetcode", "собеседован", "interview", "алгоритм", "algorithm",
                 "программирован", "programming", "tutorial", "лекци", "курс", "урок"]
DEFAULT = {"active": False, "started": 0, "until": 0, "auto_pomo": False,
           "free_breaks": True, "strict": False, "allow_on": True, "allow": DEFAULT_ALLOW,
           "blocks": DEFAULT_BLOCKS}


# ── состояние ─────────────────────────────────────────────────────────────────

def glib_signal_add(prio, signum, handler):
    """Сигнал в главный цикл GLib. GLib.unix_signal_add устарел (PyGObject 3.52+) и однажды
    исчезнет — тогда программа перестала бы запускаться (08.10.2026). Сначала замена
    GLibUnix.signal_add, без неё — старое имя, без обоих — обычный signal.signal."""
    from gi.repository import GLib
    try:
        from gi.repository import GLibUnix
        return GLibUnix.signal_add(prio, signum, handler)
    except (ImportError, AttributeError):
        pass
    try:
        return GLib.unix_signal_add(prio, signum, handler)
    except AttributeError:
        import signal as _signal
        _signal.signal(signum, lambda *_a: GLib.idle_add(lambda: handler() and False))


def load():
    try:
        with open(STATE) as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    for k, v in DEFAULT.items():
        s.setdefault(k, json.loads(json.dumps(v)))
    return s


def save(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(s, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE)


def log(event, label=""):
    os.makedirs(LOGDIR, exist_ok=True)
    with open(LOG, "a") as f:
        f.write("%d\t%s\t%s\n" % (time.time(), event, label.replace("\t", " ")))


def parse_dur(s):
    """25m, 1h30m, 90 (минуты), 1ч20м, 45мин → секунды; None — не время."""
    v = s.strip().lower().replace("мин", "m").replace("ч", "h").replace("м", "m").replace("с", "s")
    if re.fullmatch(r"\d+", v):
        return int(v) * 60
    m = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m?)?(?:(\d+)s)?", v)
    if not m or not any(m.groups()):
        return None
    h, mi, se = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + se


def human(sec):
    sec = max(0, int(sec))
    h, m = divmod(sec // 60, 60)
    if h and m:
        return "%d ч %d мин" % (h, m)
    return "%d ч" % h if h else "%d мин" % m


def pomo():
    """{'phase': work|short|long|idle, 'paused': bool, 'left': сек}."""
    d = {}
    try:
        for line in open(POMO_STATE):
            k, _, v = line.strip().partition("=")
            d[k] = v
    except OSError:
        pass
    phase = d.get("phase", "idle") or "idle"
    try:
        started, duration, paused = int(d.get("started", 0)), int(d.get("duration", 0)), int(d.get("paused", 0))
    except ValueError:
        started = duration = paused = 0
    now = time.time()
    left = started + duration - (paused if paused else now)
    if phase != "idle" and not paused and left <= 0:
        phase = "idle"                       # отрезок кончился, pomo ещё не догнал
    return {"phase": phase, "paused": bool(paused), "left": max(0, left), "task": d.get("task", "")}


def effective(s, p=None, now=None):
    """Причина блокировки сейчас: 'session' | 'pomo' | None."""
    now = now or time.time()
    p = p or pomo()
    reason = None
    if s["active"] and (not s["until"] or now < s["until"]):
        reason = "session"
    if not reason and s["auto_pomo"] and p["phase"] == "work" and not p["paused"]:
        reason = "pomo"
    if reason and s["free_breaks"] and p["phase"] in ("short", "long") and not p["paused"]:
        reason = None
    return reason


def today_stats():
    """(отвлечений сегодня, минут фокуса сегодня)."""
    start = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
    blocks, secs, opened = 0, 0, None
    try:
        lines = open(LOG).read().splitlines()[-3000:]
    except OSError:
        lines = []
    for ln in lines:
        parts = ln.split("\t")
        if len(parts) < 2:
            continue
        try:
            t = int(parts[0])
        except ValueError:
            continue
        ev = parts[1]
        if ev == "start":
            opened = t
        elif ev in ("stop", "end") and opened:
            a = max(opened, start)
            if t > a:
                secs += t - a
            opened = None
        elif ev == "block" and t >= start:
            blocks += 1
    s = load()
    if opened and s["active"]:
        secs += time.time() - max(opened, start)
    return blocks, int(secs // 60)


def day_intervals(date):
    """Отрезки сосредоточенной работы за день: сессии фокуса ∪ рабочие отрезки pomo,
    слитые (одно время не считается дважды). [(начало, конец)] в эпохе."""
    a = dt.datetime.combine(date, dt.time()).timestamp()
    b = a + 86400
    raw, opened = [], None
    try:
        lines = open(LOG).read().splitlines()[-5000:]
    except OSError:
        lines = []
    for ln in lines:
        p = ln.split("\t")
        try:
            t = int(p[0])
        except (ValueError, IndexError):
            continue
        ev = p[1] if len(p) > 1 else ""
        if ev == "start":
            opened = t
        elif ev in ("stop", "end") and opened:
            raw.append((opened, t))
            opened = None
    if opened and load()["active"]:
        raw.append((opened, time.time()))
    try:
        plines = open(os.path.expanduser("~/.local/share/pomo/log.tsv")).read().splitlines()[-3000:]
    except OSError:
        plines = []
    for ln in plines:
        p = ln.split("\t")
        if len(p) >= 5 and p[2] == "work":
            try:
                end, spent = int(p[1]), int(p[4])
            except ValueError:
                continue
            raw.append((end - spent, end))
    pst = pomo()
    if pst["phase"] == "work":
        try:
            d = dict(l.strip().partition("=")[::2] for l in open(POMO_STATE))
            st, du = int(d.get("started", 0)), int(d.get("duration", 0))
            raw.append((st, time.time() if not pst["paused"] else int(d.get("paused", 0))))
            _ = du
        except (OSError, ValueError):
            pass
    cut = sorted((max(x, a), min(y, b)) for x, y in raw if y > a and x < b and y > x)
    merged = []
    for x, y in cut:
        if merged and x <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], y))
        else:
            merged.append((x, y))
    return merged


def day_stats(date):
    """Сводка дня для экранного времени: секунды в фокусе (с помидором), по часам,
    помидоров доведено до конца, отвлечений."""
    ivs = day_intervals(date)
    hours = {}
    for x, y in ivs:
        t = x
        while t < y:
            h = dt.datetime.fromtimestamp(t).hour
            nxt = min(y, dt.datetime.fromtimestamp(t).replace(minute=0, second=0, microsecond=0).timestamp() + 3600)
            hours[h] = hours.get(h, 0) + (nxt - t)
            t = nxt
    a = dt.datetime.combine(date, dt.time()).timestamp()
    blocks = pomos = 0
    try:
        for ln in open(LOG).read().splitlines()[-5000:]:
            p = ln.split("\t")
            if len(p) > 1 and p[1] == "block" and a <= int(p[0]) < a + 86400:
                blocks += 1
    except (OSError, ValueError):
        pass
    try:
        for ln in open(os.path.expanduser("~/.local/share/pomo/log.tsv")).read().splitlines()[-3000:]:
            p = ln.split("\t")
            if len(p) >= 6 and p[2] == "work" and p[5] == "done" and a <= int(p[1]) < a + 86400:
                pomos += 1
    except (OSError, ValueError):
        pass
    return {"focus": sum(y - x for x, y in ivs), "hours": hours, "pomos": pomos, "blocks": blocks}


# ── правила ───────────────────────────────────────────────────────────────────

def compiled(s):
    out = []
    for b in s["blocks"]:
        if not b.get("on"):
            continue
        try:
            t = re.compile(b["match"], re.I) if b.get("match") else None
            a = re.compile(b["app"], re.I) if b.get("app") else None
        except re.error:
            continue
        out.append((b["label"], t, a))
    return out


# Терминалы и редакторы заголовком не судим: файл «youtube-no-popup.css» в nvim —
# это работа, а не YouTube. Правила по app-id для них действуют как обычно.
WORK_APPS = re.compile(r"^(kitty|foot|alacritty|wezterm|org\.wezfurlong\.wezterm|"
                       r"org\.xfce\.mousepad|obsidian|code|code-oss|jetbrains-.*|"
                       r"com\.jarvis\..*)$", re.I)


def allowed(s, title):
    """Заголовок с учебным словом (исключения включены)."""
    if not s.get("allow_on"):
        return False
    low = (title or "").lower()
    return any(w and w.lower() in low for w in s.get("allow", []))


def blocked_by(rules, app_id, title, s=None):
    work = bool(app_id) and bool(WORK_APPS.match(app_id))
    for label, t, a in rules:
        if a is not None and a.search(app_id or ""):
            return label
        if t is not None and not work and t.search(title or ""):
            if s is not None and allowed(s, title):
                continue
            return label
    return None


def locked(s=None):
    """Строгий режим держит сессию: ни завершить, ни ослабить правила до конца."""
    s = s or load()
    return bool(s.get("strict")) and s["active"] and (not s["until"] or time.time() < s["until"])


# ── команды ───────────────────────────────────────────────────────────────────

def ensure_daemon():
    subprocess.run(["systemctl", "--user", "start", UNIT],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def notify(title, body=""):
    subprocess.Popen(["notify-send", "-a", "Focus", title, body],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start(secs):
    s = load()
    now = int(time.time())
    if not s["active"]:
        s["started"] = now
        log("start", human(secs) if secs else "до отмены")
    if locked(s) and s["until"] and secs and now + secs < s["until"]:
        secs = s["until"] - now          # строгий режим: сократить нельзя
    s["active"] = True
    s["until"] = now + secs if secs else 0
    save(s)
    ensure_daemon()
    return s


def stop(event="stop"):
    s = load()
    if s["active"]:
        s["active"] = False
        log(event, human(time.time() - s["started"]))
        save(s)
    return s


def extend(secs):
    s = load()
    if not s["active"]:
        return start(secs)
    if s["until"]:
        s["until"] = max(s["until"], int(time.time())) + secs
        save(s)
    return s


def status_dict():
    s = load()
    p = pomo()
    blocks, mins = today_stats()
    now = time.time()
    return {"active": s["active"], "until": s["until"], "started": s["started"],
            "left": max(0, int(s["until"] - now)) if s["active"] and s["until"] else None,
            "reason": effective(s, p, now), "auto_pomo": s["auto_pomo"],
            "free_breaks": s["free_breaks"], "pomo": p["phase"], "blocks_today": blocks,
            "minutes_today": mins, "rules": [b["label"] for b in s["blocks"] if b.get("on")]}


def cmd_status(js=False):
    d = status_dict()
    if js:
        print(json.dumps(d, ensure_ascii=False))
        return
    if d["active"]:
        if d["left"] is not None:
            print("Фокус: осталось %s (до %s)" % (human(d["left"]), time.strftime("%H:%M", time.localtime(d["until"]))))
        else:
            print("Фокус: до отмены, идёт %s" % human(time.time() - d["started"]))
    else:
        print("Фокус выключен" + (" · авто с помидором" if d["auto_pomo"] else ""))
    if d["reason"] is None and d["active"] and d["pomo"] in ("short", "long"):
        print("Сейчас перерыв помидора — блокировки нет")
    print("Сегодня: отвлечений %d, в фокусе %s" % (d["blocks_today"], human(d["minutes_today"] * 60)))
    print("Блокируется: " + (", ".join(d["rules"]) or "ничего"))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "status"
    a = argv[2:]
    if cmd in ("on", "start"):
        secs = 0
        if a:
            secs = parse_dur(a[0])
            if secs is None:
                print("Не понял время: %s (например 25m, 1h30m, 90)" % a[0])
                return 1
        start(secs)
        cmd_status()
    elif cmd in ("off", "stop"):
        s = load()
        left = s["until"] - time.time() if s["active"] and s["until"] else 0
        if locked(s) and "--force" not in a:
            print("Строгий режим: фокус до %s. Закончить раньше — focus off --force"
                  % (time.strftime("%H:%M", time.localtime(s["until"])) if s["until"] else "отмены"))
            return 1
        if s["active"] and left > 60 and "--force" not in a and sys.stdin.isatty():
            ans = input("Осталось %s. Точно закончить? Напишите «да»: " % human(left))
            if ans.strip().lower() not in ("да", "yes", "y", "lf"):
                print("Продолжаем.")
                return 0
        stop()
        cmd_status()
    elif cmd in ("add", "extend", "more"):
        secs = parse_dur(a[0].lstrip("+")) if a else 15 * 60
        if not secs:
            print("Не понял время")
            return 1
        extend(secs)
        cmd_status()
    elif cmd == "toggle":
        if load()["active"]:
            stop()
        else:
            start(0)
        cmd_status()
    elif cmd in ("status", "st"):
        cmd_status("--json" in a)
    elif cmd == "list":
        for b in load()["blocks"]:
            print("%s %-12s %s" % ("[x]" if b.get("on") else "[ ]", b["label"],
                                   ("app " + b["app"]) if b.get("app") else b.get("match", "")))
    elif cmd == "block" and a:
        s = load()
        label = a[0]
        pat = "|".join(a[1:]) if len(a) > 1 else re.escape(label.lower())
        for b in s["blocks"]:
            if b["label"].lower() == label.lower():
                b["on"] = True
                if len(a) > 1:
                    b["match"] = pat
                break
        else:
            s["blocks"].append({"label": label, "match": pat, "on": True})
        save(s)
        print("Блокируется: " + label)
    elif cmd == "unblock" and a:
        s = load()
        if locked(s) and "--force" not in a:
            print("Строгий режим: правила не ослабить до конца сессии (--force — всё же)")
            return 1
        for b in s["blocks"]:
            if b["label"].lower() == a[0].lower():
                b["on"] = False
        save(s)
        print("Не блокируется: " + a[0])
    elif cmd == "strict":
        s = load()
        want = (a[0] in ("on", "1", "да")) if a else not s.get("strict")
        if not want and locked(s) and "--force" not in a:
            print("Строгий режим не снять посреди сессии (--force — всё же)")
            return 1
        s["strict"] = want
        save(s)
        print("Строгий режим " + ("включён" if want else "выключен"))
    elif cmd == "allow":
        # focus allow — список; focus allow on|off; focus allow слово… — заменить список
        s = load()
        if a and locked(s) and "--force" not in a:
            print("Строгий режим: исключения не править до конца сессии")
            return 1
        a = [x for x in a if x != "--force"]
        if not a:
            print(("[x] " if s.get("allow_on") else "[ ] ") + ", ".join(s.get("allow", [])))
        elif a[0] in ("on", "off"):
            s["allow_on"] = a[0] == "on"
            save(s)
        else:
            s["allow"] = [w.strip().lower() for w in " ".join(a).replace(",", " ").split() if w.strip()]
            save(s)
            print(", ".join(s["allow"]))
    elif cmd == "log":
        start_t = dt.datetime.combine(dt.date.today(), dt.time()).timestamp()
        try:
            for ln in open(LOG).read().splitlines():
                p = ln.split("\t")
                if len(p) >= 2 and int(p[0]) >= start_t:
                    print(time.strftime("%H:%M", time.localtime(int(p[0]))), *p[1:])
        except OSError:
            print("Журнал пуст")
    elif cmd == "daemon":
        Daemon().run()
    elif cmd == "overlay":
        overlay(a[0] if a else "", a[1] if len(a) > 1 else "", a[2] if len(a) > 2 else "")
    else:
        print(__doc__)
        return 2
    return 0


# ── сторож ────────────────────────────────────────────────────────────────────

def pdeathsig():
    """Дочерний процесс умирает вместе со сторожем (иначе сироты копятся)."""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)
    except Exception:
        pass


class Daemon:
    def __init__(self):
        self.windows = {}
        self.focused = None
        self.wake = threading.Event()
        self.stream = None
        self.overlay = None           # (Popen, подпись)
        self.last_ok = None           # последнее разрешённое окно — «назад к работе»
        self.episode = None           # id окна, на котором уже засчитано отвлечение
        self.last_media = 0
        self.lock = threading.Lock()

    # поток событий niri — только пока блокировка действует
    def stream_on(self):
        if self.stream and self.stream.poll() is None:
            return
        self.windows, self.focused = {}, None
        self.stream = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True, preexec_fn=pdeathsig)
        threading.Thread(target=self.reader, args=(self.stream,), daemon=True).start()

    def stream_off(self):
        if self.stream and self.stream.poll() is None:
            self.stream.terminate()
        self.stream = None

    def reader(self, proc):
        for line in proc.stdout:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            with self.lock:
                if "WindowsChanged" in ev:
                    self.windows = {w["id"]: w for w in ev["WindowsChanged"]["windows"]}
                    for w in self.windows.values():
                        if w.get("is_focused"):
                            self.focused = w["id"]
                elif "WindowOpenedOrChanged" in ev:
                    w = ev["WindowOpenedOrChanged"]["window"]
                    self.windows[w["id"]] = w
                    if w.get("is_focused"):
                        self.focused = w["id"]
                elif "WindowClosed" in ev:
                    self.windows.pop(ev["WindowClosed"]["id"], None)
                elif "WindowFocusChanged" in ev:
                    self.focused = ev["WindowFocusChanged"]["id"]
                elif "WorkspacesChanged" in ev:
                    self.wsout = {w["id"]: w.get("output") for w in ev["WorkspacesChanged"]["workspaces"]}
            self.wake.set()

    def output_of(self, w):
        return getattr(self, "wsout", {}).get(w.get("workspace_id"), "") or ""

    def show_overlay(self, label, w):
        if self.overlay and self.overlay[0].poll() is None and self.overlay[1] == label:
            return
        self.hide_overlay()
        back = str(self.last_ok or "")
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "overlay", label,
                              self.output_of(w), back],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=pdeathsig)
        self.overlay = (p, label)

    def hide_overlay(self):
        if self.overlay and self.overlay[0].poll() is None:
            self.overlay[0].terminate()
        self.overlay = None

    def pause_media(self, rules, titles, s=None):
        """Пауза плееров, чей адрес/название совпали с правилом или с заголовком
        запрещённого окна."""
        try:
            out = subprocess.run(["playerctl", "-a", "metadata", "--format",
                                  "{{playerInstance}}\t{{status}}\t{{xesam:url}}\t{{title}}"],
                                 capture_output=True, text=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return
        for line in out.splitlines():
            p = line.split("\t")
            if len(p) < 4 or p[1] != "Playing":
                continue
            inst, url, title = p[0], p[2], p[3]
            if s is not None and allowed(s, title):
                continue
            hit = blocked_by(rules, "", url) or blocked_by(rules, "", title)
            if not hit and title:
                hit = any(title.lower() in t.lower() for t in titles if len(title) > 3)
            if hit:
                subprocess.run(["playerctl", "-p", inst, "pause"], capture_output=True, timeout=3)

    def step(self):
        s = load()
        now = time.time()
        if s["active"] and s["until"] and now >= s["until"]:
            blocks, _m = today_stats()
            stop("end")
            notify("Фокус завершён", "%s в фокусе · отвлечений сегодня: %d"
                   % (human(now - s["started"]), blocks))
            try:
                sys.path.insert(0, HERE)
                import ui_sound
                ui_sound.play("timer")
            except Exception:
                pass
            s = load()
        reason = effective(s)
        if not reason:
            self.hide_overlay()
            self.stream_off()
            self.episode = None
            return 2.0
        self.stream_on()
        rules = compiled(s)
        with self.lock:
            wins = dict(self.windows)
            fid = self.focused
        bad_titles = []
        for w in wins.values():
            if blocked_by(rules, w.get("app_id"), w.get("title"), s):
                bad_titles.append(w.get("title") or "")
        w = wins.get(fid)
        label = blocked_by(rules, w.get("app_id"), w.get("title"), s) if w else None
        if label:
            self.show_overlay(label, w)
            if self.episode != fid:
                self.episode = fid
                log("block", label)
                self.pause_media(rules, bad_titles, s)
                self.last_media = now
        else:
            self.hide_overlay()
            self.episode = None
            if w:
                self.last_ok = fid
        if bad_titles and now - self.last_media > 3:
            self.pause_media(rules, bad_titles, s)
            self.last_media = now
        return 1.0

    def run(self):
        signal.signal(signal.SIGTERM, lambda *_: (self.hide_overlay(), self.stream_off(), os._exit(0)))
        while True:
            try:
                wait = self.step()
            except Exception as e:                      # сторож не должен падать от мелочи
                print("ошибка: %r" % e, file=sys.stderr, flush=True)
                wait = 2.0
            self.wake.wait(wait)
            self.wake.clear()


# ── слой «Фокус» ──────────────────────────────────────────────────────────────

def overlay(label, output, back):
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell
    sys.path.insert(0, HERE)
    import routine_app as ra
    import cairo

    model = None
    try:
        outs = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"], capture_output=True,
                                         text=True, timeout=2).stdout)
        model = outs.get(output, {}).get("model")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    display = Gdk.Display.get_default()
    monitors = [display.get_monitor(i) for i in range(display.get_n_monitors())]
    chosen = [m for m in monitors if model and m.get_model() == model] or monitors

    c = ra.colors(ra.style_name())
    st = {"hover": None, "hits": []}

    def go_back(*_a):
        if back:
            subprocess.run(["niri", "msg", "action", "focus-window", "--id", back],
                           capture_output=True)
        else:
            subprocess.run(["niri", "msg", "action", "focus-column-left"], capture_output=True)

    def draw(area, cr):
        a = area.get_allocation()
        w, h = a.width, a.height
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(c["bg"][0], c["bg"][1], c["bg"][2], 0.82)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        p = ra.Painter(cr)
        s = load()
        cw_, ch_ = 460, 250
        x, y = (w - cw_) // 2, (h - ch_) // 2
        ra.View.card(p, c, x, y, cw_, ch_)
        p.text(x + 24, y + 26, "Фокус", c["dim"])
        p.text(x + 24, y + 50, label, c["acc_l"], px=32)
        if s["active"] and s["until"]:
            line = "до %s · осталось %s" % (time.strftime("%H:%M", time.localtime(s["until"])),
                                            human(s["until"] - time.time()))
        elif s["active"]:
            line = "до отмены · идёт %s" % human(time.time() - s["started"])
        else:
            line = "идёт рабочий отрезок помидора"
        p.text(x + 24, y + 98, line, c["text"])
        blocks, _m = today_stats()
        p.text(x + 24, y + 120, "отвлечений сегодня: %d" % blocks, c["dim"])
        p.text(x + 24, y + 150, "Ctrl+W — закрыть вкладку, слой исчезнет сам", c["faint"])
        bx, by, bw = x + 24, y + ch_ - 24 - 24, cw_ - 48
        v = ra.View.__new__(ra.View)
        v.c, v.hover, v.hits = c, st["hover"], []
        v.button(p, bx, by, bw, "Назад к работе", "back", accent=True)
        st["hits"] = v.hits

    win = None
    for mon in chosen:
        win = Gtk.Window()
        GtkLayerShell.init_for_window(win)
        GtkLayerShell.set_namespace(win, "jarvis-focus-block")
        GtkLayerShell.set_layer(win, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(win, mon)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(win, e, True)
        GtkLayerShell.set_exclusive_zone(win, -1)
        GtkLayerShell.set_keyboard_mode(win, GtkLayerShell.KeyboardMode.NONE)
        vis = win.get_screen().get_rgba_visual()
        if vis:
            win.set_visual(vis)
        win.set_app_paintable(True)
        area = Gtk.DrawingArea()
        area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        area.connect("draw", draw)

        def press(_w, ev, area=area):
            for (hx, hy, hw, hh), key in st["hits"]:
                if hx <= ev.x < hx + hw and hy <= ev.y < hy + hh and key == "back":
                    go_back()
            return True

        def motion(_w, ev, area=area):
            k = None
            for (hx, hy, hw, hh), key in st["hits"]:
                if hx <= ev.x < hx + hw and hy <= ev.y < hy + hh:
                    k = key
            if k != st["hover"]:
                st["hover"] = k
                area.queue_draw()
            return True
        area.connect("button-press-event", press)
        area.connect("motion-notify-event", motion)
        win.add(area)
        win.show_all()
        GLib.timeout_add(1000, lambda area=area: area.queue_draw() or True)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda *_: os._exit(0))
    Gtk.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
