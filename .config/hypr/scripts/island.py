#!/usr/bin/env python3
"""Островок (dynamic island) сверху по центру — 19.10.2026, план ~/Documents/dynamic-island-plan.md.

Слой layer-shell TOP без своей зоны (exclusive 0): layer-shell сам кладёт его под зону
бара, поэтому на мониторе с баром «всегда» островок висит из нижней кромки бара
вырезом с ушками, а без бара — от края экрана. Места у окон не отнимает.

Состояния: нет — ничего не идёт, окна нет вовсе; нить — 8 px в зазоре над окнами,
пока идёт запись, помидор или музыка; компакт — пилюля с текстом на пару секунд при
событии; карточка — по щелчку, с кнопками. Всё по событиям: inotify (запись, помидор,
настройки), D-Bus MPRIS (музыка), niri event-stream (монитор с фокусом, обзор), сокет
(короткие события от других скриптов). В покое тиков нет.

    island.py                 запустить (один экземпляр; второй тихо выходит)
    island.py push ТЕКСТ [СЕК] [ЗНАЧОК]   показать короткое событие
    island.py get [КЛЮЧ] / set КЛЮЧ ЗНАЧЕНИЕ   настройки (state/island.json)
    island.py restart | stop | status | check
    island.py shot ФАЙЛ.png   рисунок всех состояний вне экрана (для проверок)
"""
import fcntl
import json
import math
import os
import re
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK = os.path.join(RUN, "jarvis-island.lock")
SOCK = os.path.join(RUN, "jarvis-island.sock")
CONF = os.path.expanduser("~/.config/hypr/state/island.json")
LAST = os.path.expanduser("~/.config/hypr/state/island-last")
LOG = os.path.join(RUN, "island.log")
REC = os.path.join(RUN, "jarvis-rec")
POMO = os.path.join(RUN, "pomo", "state")
REC_SH = os.path.join(HERE, "rec_area.sh")
NAMESPACE = "jarvis-island"

DEFAULTS = {
    "on": True,
    "monitor": "focus",      # focus — монитор с фокусом; all — все; или имя выхода (eDP-1)
    "thread": True,          # нить, пока что-то идёт
    "thread_always": True,   # нить и без дел (точка с часами): страницы островка всегда под рукой
    # Страницы островка по порядку (Настройки → Waybar → «Страницы островка»); порядок = и
    # приоритет: первое идущее дело показывает живая нить.
    "pages": "call,music,pomo,timer,rec,cat,clip,capture,focus",
    "rev": 3,                # версия списка страниц: 3 — добавлен «Котик» (20.10.2026)
    # Поверх окон: зазора над окнами нет (край как по системе), островок рисуется поверх
    # всего; в играх всё равно прячется (19.10.2026: «Поверх окон… Кроме игр»).
    "overlay": False,
    "track_pop": False,      # смена трека раскрывает компакт (иначе — уведомление swaync)
    "pop_sec": 2.5,          # сколько держится компакт после события
    "design": "auto",        # вид: auto — как стиль системы (Default/Skeet/Beta), ios
    "thread_style": "line",  # нить: line — линия, dots — точки, pill — капсула с часами, cat — котик
    "thread_alpha": 0.35,    # насколько видна нить (0.15–0.8): «тусклее, чтобы был незаметным»
    "hover": True,           # раскрывать наведением (иначе — щелчком)
    "video_hide": False,     # при видео в фокусе нить не видна (19.10.2026: «пока что убери»)
}

CW, CH = 560, 232            # холст постоянного размера: размер поверхности не меняется
THREAD_W, THREAD_H, COMPACT_H, CARD_W, CARD_H = 132, 4, 34, 420, 120
CARD_HK = {"clip": 212, "timer": 150}   # своя высота страницы: снимки — два ряда, у таймера — ряд отрезков
ANIM_MS = 300
HOVER_MS, LEAVE_MS = 140, 650   # задержка раскрытия наведением и сворачивания после ухода курсора
HOVER_PAD = 18                  # зона наведения вокруг нити (сама нить 3 px — в неё не попасть)
THREAD_Y = 5                    # нить на 5 px ниже края (было 2 — «опусти чуть-чуть», 19.10.2026)
PILL_W, PILL_H = 74, 24         # нить-капсула (20→24, 19.10.2026: «больше пространства между верхом и низом»)
# Зазор между окнами и нитью: добавка к верхнему краю niri (niri_compositor.py island_space).
# Края окон = 8 px. Капсула 24 px → +28 (по 6 px воздуха сверху и снизу); линии/точкам чуть
# меньше, но не впритык (19.10.2026: «для линии поменьше, но не прям сильно меньше»): +17 —
# линия 3 px ровно посередине, по 11 px над и под ней.
SPACE = {"line": 17, "dots": 17, "pill": 28, "cat": 28}
PILLS = ("pill", "cat")         # нити-капсулы: своя высота и ширина по содержимому
NIRI_COMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "niri_compositor.py")


def thread_size(style):
    if style == "cat":                          # спящий кот с часами и датой (превью в Настройках)
        import cairo
        return (cat_w(cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)), None), float(PILL_H))
    return (float(PILL_W), float(PILL_H)) if style == "pill" else (float(THREAD_W), float(THREAD_H))


def thread_y(style, off, edge, overlay=False):
    """Верх нити в координатах поверхности: ровно посередине между краем экрана и верхом окон
    (19.10.2026, просьба: «центрирование островка, сверху и снизу одинаковое пространство»).
    off — отступ поверхности от края (бар «при наведении»). Поверх окон — как раньше, THREAD_Y."""
    h = PILL_H if style in PILLS else THREAD_H
    if overlay:
        return THREAD_Y
    y = int(round((edge + SPACE.get(style, 17) - h) / 2.0)) - off
    return max(1, y)


def space_for(c):
    """Сколько добавить сверху к краю окон: островок выключен, нити нет или поверх окон — 0."""
    if not (c.get("on") and c.get("thread")) or c.get("overlay"):
        return 0
    return SPACE.get(c.get("thread_style"), 17)


def bar_always():
    """Мониторы с постоянным верхним waybar: там нить не рисуется и места не занимает
    (19.10.2026, просьба: «при waybar эта линия не должна рисоваться, только в связке с
    нижней панелью»). None — режим общий для всех; тогда ответ — всё или ничего."""
    try:
        import top_bar
        modes = top_bar.modes_in_use()
    except Exception as e:
        log("bar_always:", e)
        return set(), set()
    outs = set((niri_json("outputs") or {}).keys())
    if None in modes:
        return (set(outs) if modes[None] == "always" else set()), outs
    return {o for o, m in modes.items() if m == "always"}, outs | set(modes)


def space_outputs(c):
    """{монитор: добавка} — только там, где нить может быть (без постоянного верхнего бара;
    монитор задан в настройках — только он)."""
    n = space_for(c)
    if not n:
        return {}
    always, outs = bar_always()
    want = outs - always
    if c.get("monitor") not in ("focus", "all"):
        want &= {c.get("monitor")}
    return {o: n for o in sorted(want)}


def sync_space(c):
    """Привести зазор над окнами к настройкам островка (19.10.2026, просьба: «создать
    пространство между окном и линией островка»). Зазор — по мониторам (outputs.kdl, свой
    layout у выхода); то же значение — ничего не пишет и niri не трогает."""
    want = space_outputs(c)
    try:
        r = subprocess.run(["python3", NIRI_COMP, "get"], capture_output=True, text=True, timeout=5)
        cur = json.loads(r.stdout or "{}")
        if cur.get("island_outs", {}) == want and not cur.get("island_space"):
            return
        n = max(want.values()) if want else 0
        subprocess.run(["python3", NIRI_COMP, "set", "island_space", str(n), *want],
                       capture_output=True, timeout=10)
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log("sync_space:", e)
PAUSED_KEEP = 30             # музыка на паузе держится нитью столько секунд

G_PREV, G_PLAY, G_PAUSE, G_NEXT, G_STOP = "\U000f04ae", "\U000f040a", "\U000f03e4", "\U000f04ad", "\U000f04db"
G_POMO, G_BREAK, G_NOTE, G_REC, G_SKIP = "\U000f051f", "\U000f0176", "\U000f075a", "\U000f044a", "\U000f0661"
G_MIC, G_MIC_OFF, G_TIMER, G_CLIP, G_PICK = "\U000f036c", "\U000f036d", "\U000f051b", "\U000f0192", "\U000f020a"
G_SHOT, G_MEMO, G_OPEN, G_CALL, G_BOARD = "\U000f019e", "\U000f039a", "\U000f03cc", "\U000f03f2", "\U000f014c"
G_TG, G_DISCORD = "", "\U000f066f"

G_VOL, G_VOL_OFF, G_WAVE = "\U000f057e", "\U000f0581", "\U000f0e4e"

# Страницы островка: id → (название, что на ней, вид). Вид: live — есть, только пока дело
# идёт (это и дела капсулы: их порядок в настройках = приоритет); always — есть всегда и
# живая, когда идёт (таймер); static — всегда, без дела.
# 19.10.2026, просьба: «Буфер убери, Таймер отдельным блоком, сразу с готовым пресетом или
# с выбором собственного времени. Запись, Пипетка и Снимок в один общий блок. Заметку,
# Помидор в отдельный блок» — вместо одной страницы «Инструменты» (tools) две: capture и focus.
PAGES = {
    "call":    ("Звонок", "Telegram/Discord: длительность, микрофон звонка, громкость; голосовое — живая волна", "live"),
    "music":   ("Музыка", "где играет (YouTube, Яндекс Музыка…), время, громкость приложения", "live"),
    "pomo":    ("Помидор", "сколько осталось, задача, пауза, пропуск, стоп", "live"),
    "timer":   ("Таймер", "готовые 5–60 минут или своё время; идущие таймеры hub", "always"),
    "rec":     ("Запись экрана", "время записи, пауза, стоп", "live"),
    "clip":    ("Снимки из буфера", "последние картинки: перетащить в чат или поиск, щелчок — скопировать", "static"),
    "capture": ("Захват", "запись экрана, пипетка, снимок", "static"),
    "focus":   ("Фокус", "заметка и помидор", "static"),
    "cat":     ("Котик", "бегает, пока занят терминал, играет музыка или идёт помидор; песня с текстом — караоке", "static"),
}
PAGE_GLYPH = {"call": G_CALL, "rec": G_REC, "pomo": G_POMO, "timer": G_TIMER, "music": G_NOTE,
              "clip": G_CLIP, "capture": G_SHOT, "focus": G_MEMO, "cat": "\U000f011b"}
PAGE_EXE = {"call": "call.exe", "music": "music.exe", "pomo": "pomo.exe", "timer": "timer.exe",
            "rec": "rec.exe", "clip": "clip.exe", "capture": "capture.exe", "focus": "focus.exe",
            "cat": "cat.exe"}
# Инструменты блоков: id, значок, подпись, команда (запуск через niri — отдельным процессом).
CAPTURE = [
    ("rec", G_REC, "Запись", ["bash", os.path.join(HERE, "rec_area.sh")]),
    ("pick", G_PICK, "Пипетка", None),                 # hyprpicker — свой процесс, цвет во flash
    ("shot", G_SHOT, "Снимок", ["niri", "msg", "action", "screenshot"]),
]
FOCUS = [
    ("note", G_MEMO, "Заметка", ["bash", os.path.join(HERE, "notepad.sh"), "new"]),
    ("pomo", G_POMO, "Помидор", [os.path.expanduser("~/.local/bin/pomo"), "ask"]),
]
TOOLS = CAPTURE + FOCUS
TIMER_PRESETS = (5, 10, 15, 25, 45, 60)            # минуты: щелчок — сразу таймер hub
CALL_GREEN = (0.30, 0.82, 0.46)


def page_ids(c):
    """Включённые страницы по порядку из настроек; мусор и повторы отбрасываются."""
    out = []
    for p in str(c.get("pages") or "").split(","):
        p = p.strip()
        if p in PAGES and p not in out:
            out.append(p)
    return out


# ─────────────────────────── настройки ───────────────────────────

def load_conf():
    d = dict(DEFAULTS)
    raw = {}
    try:
        v = json.load(open(CONF))
        if isinstance(v, dict):
            raw = v
            d.update({k: v[k] for k in v if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    # 19.10.2026: «Инструменты» разделены на «Захват» и «Фокус»; видов осталось два
    pg = [x.strip() for x in str(d["pages"]).split(",")]
    if "tools" in pg:
        i = pg.index("tools")
        pg[i:i + 1] = [x for x in ("capture", "focus") if x not in pg]
        d["pages"] = ",".join(pg)
    if d["design"] not in ("auto", "ios"):
        d["design"] = "auto"
    if raw.get("rev", 0) < 3 and raw:           # 20.10.2026: страница «Котик» — один раз перед снимками
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        if "cat" not in pg:
            pg.insert(pg.index("clip") if "clip" in pg else len(pg), "cat")
            d["pages"] = ",".join(pg)
        d["rev"] = 3
        try:
            save_conf(d)
        except OSError:
            pass
    return d


def save_conf(d):
    os.makedirs(os.path.dirname(CONF), exist_ok=True)
    with open(CONF + ".tmp", "w") as f:
        json.dump({k: d[k] for k in DEFAULTS if k in d}, f, ensure_ascii=False, indent=1)
    os.replace(CONF + ".tmp", CONF)


def thread_h():
    """Край окон niri у экрана (gaps + struts по бокам) — без добавки островка: по нему нить
    встаёт посередине между краем экрана и окнами."""
    try:
        t = open(os.path.expanduser("~/.config/niri/cfg/layout.kdl")).read()
        g = int(re.search(r"^\s*gaps\s+(-?\d+)", t, re.M).group(1))
        s = re.search(r"struts\s*\{([^}]*)\}", t, re.S)
        side = int(re.search(r"left\s+(-?\d+)", s.group(1)).group(1)) if s else 0
        return max(0, g + side)
    except (OSError, AttributeError, ValueError):
        return 8


HOVER_TOP = 2                 # датчик бара — 2 px у края, островок ниже его


def hover_offset(output):
    """Бар сверху «при наведении» (top_bar.py) места не резервирует. Островок тогда
    отступает от края ровно настолько, чтобы не лежать под 2-px датчиком бара (19.10.2026:
    сперва прилип к потолку и открывал бар, потом под всей высотой бара — «переборщил с
    пространством сверху»)."""
    try:
        import top_bar
        modes = top_bar.modes_in_use()
        if modes.get(output, modes.get(None)) != "hover":
            return 0
        return HOVER_TOP
    except Exception as e:
        log("hover_offset:", e)
        return 0


def log(*a):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except OSError:
        pass


# ─────────────────────────── источники ───────────────────────────

def _read(path, default=""):
    try:
        return open(path).read().strip()
    except OSError:
        return default


def read_rec():
    """Запись Recorder: {paused, sec, mode} или None. Время — как rec_us() в rec_area.sh."""
    try:
        pid = int(_read(os.path.join(REC, "pid"), "0") or 0)
        if not pid:
            return None
        os.kill(pid, 0)
    except (ValueError, OSError):
        return None
    try:
        us = int(_read(os.path.join(REC, "acc"), "0") or 0)
        t0 = _read(os.path.join(REC, "t0"))
        if t0:
            us += int(time.time() * 1e6) - int(t0)
    except ValueError:
        us = 0
    return {"paused": os.path.exists(os.path.join(REC, "paused")), "sec": max(0, us // 1_000_000),
            "mode": _read(os.path.join(REC, "mode")) or "запись"}


def read_pomo():
    """Помидор: {phase, rem, dur, paused, task} или None — остаток как в pomo status."""
    d = {}
    for line in _read(POMO).splitlines():
        k, _, v = line.partition("=")
        d[k.strip()] = v.strip()
    if d.get("phase", "idle") == "idle":
        return None
    try:
        st, dur, pa = int(d.get("started") or 0), int(d.get("duration") or 0), int(d.get("paused") or 0)
    except ValueError:
        return None
    rem = st + dur - (pa if pa else int(time.time()))
    return {"phase": d["phase"], "rem": max(0, rem), "dur": dur, "paused": pa > 0,
            "task": d.get("task") or ""}


def mmss(s):
    s = int(max(0, s))
    return "%d:%02d:%02d" % (s // 3600, s // 60 % 60, s % 60) if s >= 3600 else "%02d:%02d" % (s // 60, s % 60)


class Music:
    """Плееры MPRIS по D-Bus (по образцу lyrics_bar.App, без текстов): кто играет."""
    MPRIS = "org.mpris.MediaPlayer2."
    PATH = "/org/mpris/MediaPlayer2"
    IFACE = "org.mpris.MediaPlayer2.Player"

    def __init__(self, on_change):
        from gi.repository import Gio, GLib
        from lyrics_bar import Player
        self.Gio, self.GLib, self.Player = Gio, GLib, Player
        self.on_change = on_change
        self.players, self.by_owner, self.paused_at = {}, {}, {}
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                                  "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, self.on_owner)
        self.bus.signal_subscribe(None, "org.freedesktop.DBus.Properties", "PropertiesChanged",
                                  self.PATH, None, Gio.DBusSignalFlags.NONE, self.on_props)
        self.bus.signal_subscribe(None, self.IFACE, "Seeked", self.PATH, None,
                                  Gio.DBusSignalFlags.NONE, self.on_seeked)
        try:
            names = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListNames", None, "(as)")[0]
        except Exception:
            names = []
        for n in names:
            if n.startswith(self.MPRIS):
                self.add(n)

    def call(self, dest, path, iface, method, args, rtype, timeout=800):
        r = self.bus.call_sync(dest, path, iface, method, args,
                               self.GLib.VariantType.new(rtype) if rtype else None,
                               self.Gio.DBusCallFlags.NONE, timeout, None)
        return r.unpack() if r else None

    def add(self, name, owner=None):
        V = self.GLib.Variant
        p = self.Player(name)
        try:
            p.owner = owner or self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "GetNameOwner", V("(s)", (name,)), "(s)")[0]
            props = self.call(name, self.PATH, "org.freedesktop.DBus.Properties", "GetAll",
                              V("(s)", (self.IFACE,)), "(a{sv})")[0]
            p.identity = str(self.call(name, self.PATH, "org.freedesktop.DBus.Properties", "Get",
                                       V("(ss)", ("org.mpris.MediaPlayer2", "Identity")), "(v)")[0] or "")
        except Exception:
            props = {}
        self.apply(p, props)
        if "Position" in props:
            p.set_pos(int(props["Position"] or 0) / 1e6)
        self.players[name] = p
        self.by_owner[p.owner] = p

    def apply(self, p, props):
        if "PlaybackStatus" in props:
            was = p.status
            p.status = str(props["PlaybackStatus"])
            if was == "Playing" and p.status != "Playing":
                self.paused_at[p.name] = time.monotonic()
        if "Metadata" in props:
            p.meta = dict(props["Metadata"] or {})

    def on_owner(self, _c, _s, _p, _i, _sig, params):
        name, _old, new = params.unpack()
        if not name.startswith(self.MPRIS):
            return
        old = self.players.pop(name, None)
        if old:
            self.by_owner.pop(old.owner, None)
        if new:
            self.add(name, new)
        self.on_change()

    def on_props(self, _c, sender, _p, _i, _sig, params):
        ifname, changed, _inv = params.unpack()
        p = self.by_owner.get(sender)
        if not p or ifname != self.IFACE:
            return
        before = (p.status, p.title)
        now = p.position()
        self.apply(p, changed)
        if "Position" in changed:
            p.set_pos(int(changed["Position"] or 0) / 1e6)
        elif before[1] != p.title:
            p.set_pos(0.0)
        else:
            p.pos, p.pos_t = now, time.monotonic()
        if (p.status, p.title) != before:
            self.on_change()

    def on_seeked(self, _c, sender, *_a):
        p = self.by_owner.get(sender)
        if p:
            p.set_pos(int(_a[-1].unpack()[0] or 0) / 1e6)

    def current(self):
        """Играющий плеер (песня важнее видео), иначе недавно поставленный на паузу."""
        ps = [p for p in self.players.values() if p.title and not p.ignored()]
        play = [p for p in ps if p.status == "Playing"]
        if play:
            return max(play, key=lambda p: (p.is_song(), not p.is_browser()))
        now = time.monotonic()
        recent = [p for p in ps if p.status == "Paused" and now - self.paused_at.get(p.name, -1e9) < PAUSED_KEEP]
        return max(recent, key=lambda p: self.paused_at.get(p.name, 0)) if recent else None

    def command(self, p, method):
        try:
            self.bus.call(p.name, self.PATH, self.IFACE, method, None, None,
                          self.Gio.DBusCallFlags.NONE, 800, None, None)
        except Exception as e:
            log("mpris", method, e)


CALL_APPS = (("telegram", "Telegram", G_TG), ("ayugram", "Telegram", G_TG), ("64gram", "Telegram", G_TG),
             ("discord", "Discord", G_DISCORD), ("vesktop", "Discord", G_DISCORD),
             ("webcord", "Discord", G_DISCORD), ("equibop", "Discord", G_DISCORD), ("legcord", "Discord", G_DISCORD))


CALLS_FILE = os.path.join(RUN, "jarvis-island-calls.json")
METER_NAME = "jarvis-island-meter"        # свой поток записи (волна) — не звонок


def scan_calls():
    """Кто сейчас пишет микрофон: Telegram/Discord с живым потоком записи (не монитор, не
    на паузе) = звонок. {Приложение: {ids, muted, gmute, icon, app, voice, vol}}.
    Голосовое сообщение Telegram держит микрофон так же, но звука от Telegram при нём нет:
    поток записи без потока вывода = голосовое (voice). vol — громкость микрофона, %."""
    try:
        so = json.loads(subprocess.run(["pactl", "-f", "json", "list", "source-outputs"],
                                       capture_output=True, text=True, timeout=3).stdout or "[]")
        si = json.loads(subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"],
                                       capture_output=True, text=True, timeout=3).stdout or "[]")
        srcs = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True,
                              timeout=3).stdout.splitlines()
        vol = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"], capture_output=True,
                             text=True, timeout=3).stdout
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log("scan_calls:", e)
        return None
    monitors = {ln.split("\t")[0] for ln in srcs if "\t" in ln and ln.split("\t")[1].endswith(".monitor")}
    gmute = "MUTED" in vol
    try:
        mvol = int(round(float(vol.split("Volume:")[1].split()[0]) * 100))
    except (IndexError, ValueError):
        mvol = None

    def app_of(pr):
        hay = " ".join(str(pr.get(k, "")) for k in ("application.name", "application.process.binary",
                                                     "node.name", "media.name", "application.id")).lower()
        if METER_NAME in hay:
            return None
        try:
            pid = int(pr.get("application.process.id") or 0)
            if pid:
                hay += " " + open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(
                    "utf-8", "replace").lower()
        except (OSError, ValueError):
            pass
        return next(((name, icon) for key, name, icon in CALL_APPS if key in hay), None)
    playing = {a[0] for a in (app_of(o.get("properties") or {}) for o in si if isinstance(si, list)) if a}
    out = {}
    for o in so if isinstance(so, list) else []:
        pr = o.get("properties") or {}
        if o.get("corked") or pr.get("stream.capture.sink") == "true" or str(o.get("source")) in monitors:
            continue
        a = app_of(pr)
        if not a:
            continue
        name, icon = a
        c = out.setdefault(name, {"ids": [], "muted": gmute, "gmute": gmute, "icon": icon, "app": name,
                                  "vol": mvol, "voice": name == "Telegram" and name not in playing})
        c["ids"].append(o.get("index"))
        c["muted"] = c["muted"] or bool(o.get("mute"))
    return out


class CallWatch:
    """Звонки: pactl subscribe будит, разбор — в потоке, не чаще 4 раз в секунду.
    Начало звонка — время, когда приложение открыло поток микрофона; оно хранится в
    $XDG_RUNTIME_DIR (по номерам потоков), и перезапуск островка его не сбрасывает."""

    def __init__(self, GLib, on_change):
        self.GLib, self.on_change = GLib, on_change
        self.calls = {}              # приложение → {ids, muted, icon, app, since, voice, vol}
        self.t = None
        self.busy = False
        try:
            self.saved = json.load(open(CALLS_FILE))
        except (OSError, ValueError):
            self.saved = {}
        self.start()

    def start(self):
        try:
            self.proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, preexec_fn=pdeathsig)
        except OSError:
            self.GLib.timeout_add_seconds(5, lambda: self.start() and False)
            return
        ch = self.GLib.IOChannel.unix_new(self.proc.stdout.fileno())
        self.GLib.io_add_watch(ch, self.GLib.PRIORITY_DEFAULT, self.GLib.IO_IN | self.GLib.IO_HUP, self.on_line)
        self.kick()

    def on_line(self, _ch, cond):
        line = self.proc.stdout.readline() if not cond & self.GLib.IO_HUP else b""
        if not line:
            self.GLib.timeout_add_seconds(3, lambda: self.start() and False)
            return False
        # source-output — поток записи, source — mute микрофона, sink-input — звук звонка
        if b"source" in line or b"sink-input" in line:
            self.kick()
        return True

    def kick(self):
        if self.t is None:
            self.t = self.GLib.timeout_add(250, self.scan)

    def scan(self):
        self.t = None
        if self.busy:
            self.kick()
            return False
        self.busy = True
        import threading

        def run():
            found = scan_calls()
            self.GLib.idle_add(lambda: self.done(found) and False)
        threading.Thread(target=run, daemon=True).start()
        return False

    def done(self, found):
        self.busy = False
        if found is None:
            return
        now = time.time()
        new, keep = {}, {}
        for name, c in found.items():
            ids = set(c["ids"])
            old = self.calls.get(name) or {}
            sv = self.saved.get(name) or {}
            if ids & set(old.get("ids") or ()):
                c["since"] = old["since"]
            elif ids & set(sv.get("ids") or ()):
                c["since"] = sv["since"]            # островок перезапускали посреди звонка
            else:
                c["since"] = now
            new[name] = c
            keep[name] = {"ids": sorted(ids), "since": c["since"]}
        if keep != self.saved:
            self.saved = keep
            try:
                with open(CALLS_FILE + ".tmp", "w") as f:
                    json.dump(keep, f)
                os.replace(CALLS_FILE + ".tmp", CALLS_FILE)
            except OSError:
                pass
        sig = lambda d: {k: (v["muted"], tuple(v["ids"]), v["voice"], v["vol"]) for k, v in d.items()}
        changed = sig(new) != sig(self.calls)
        self.calls = new
        if changed:
            self.on_change()

    def toggle_mute(self):
        """Микрофон только в звонке (19.10.2026, просьба: «выключает микрофон желательно в
        звонке»): глушится поток записи Telegram/Discord, а не микрофон системы — остальные
        программы его слышат. Включение снимает и общий mute, иначе звонок останется немым."""
        muted = any(c["muted"] for c in self.calls.values())
        try:
            if muted and any(c.get("gmute") for c in self.calls.values()):
                subprocess.run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0"], timeout=3)
            for c in self.calls.values():
                for i in c["ids"]:
                    subprocess.run(["pactl", "set-source-output-mute", str(i), "0" if muted else "1"], timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            log("toggle_mute:", e)
        self.kick()
        return not muted

    def mic_volume(self, step):
        """Громкость микрофона колесом над кнопкой микрофона (до 100 %)."""
        try:
            subprocess.run(["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SOURCE@",
                            "%d%%%s" % (abs(step), "+" if step > 0 else "-")], timeout=3)
        except (OSError, subprocess.SubprocessError) as e:
            log("mic_volume:", e)
        self.kick()


class Meter:
    """Живая волна микрофона (голосовое, звонок): parec пишет микрофон 16 кГц моно, поток
    читает кусками по 20 мс, уровень — в кольцо из BARS значений. Работает только пока
    идёт звонок или голосовое; потом процесс закрывается."""
    BARS = 48

    def __init__(self):
        import collections
        self.levels = collections.deque([0.0] * self.BARS, maxlen=self.BARS)
        self.proc = None

    def start(self):
        if self.proc and self.proc.poll() is None:
            return
        import threading
        try:
            self.proc = subprocess.Popen(
                ["parec", "--raw", "--format=s16le", "--rate=16000", "--channels=1", "--latency-msec=20",
                 "--client-name=" + METER_NAME, "--stream-name=" + METER_NAME],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, preexec_fn=pdeathsig)
        except OSError as e:
            log("meter:", e)
            self.proc = None
            return
        threading.Thread(target=self.read, args=(self.proc,), daemon=True).start()

    def read(self, proc):
        import array
        while proc.poll() is None:
            buf = proc.stdout.read(640)
            if not buf:
                break
            a = array.array("h", buf[:len(buf) // 2 * 2])
            peak = max((abs(x) for x in a), default=0) / 32768.0
            # логарифм: шёпот виден, крик не упирается сразу; −50 дБ → 0, 0 дБ → 1
            lv = 0.0 if peak < 0.003 else max(0.0, min(1.0, 1 + math.log10(peak) / 2.5))
            self.levels.append(lv)

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
        self.proc = None
        self.levels.extend([0.0] * self.BARS)

    @property
    def on(self):
        return self.proc is not None and self.proc.poll() is None


HUB_DB = os.path.expanduser("~/.local/share/hub/hub.db")


def read_timers():
    """Идущие таймеры hub: [{id, text, due, created}] по сроку, только чтение базы."""
    import sqlite3
    try:
        db = sqlite3.connect("file:%s?mode=ro" % HUB_DB, uri=True, timeout=1)
        rows = db.execute("SELECT id, text, due, created FROM items WHERE kind='timer' AND status='open' "
                          "AND due > ? ORDER BY due", (int(time.time()),)).fetchall()
        db.close()
    except Exception as e:
        log("read_timers:", e)
        return []
    return [{"id": r[0], "text": r[1], "due": r[2], "created": r[3]} for r in rows]


CLIP_DIR = os.path.join(os.path.expanduser("~/.cache/jarvis-island"), "clip")
CLIP_N = 4


def list_clip_images():
    """Последние картинки в cliphist: [(id, формат, w, h)] — значки и мелочь (<48 px) мимо."""
    try:
        out = subprocess.run(["cliphist", "list"], capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    res = []
    for ln in out.splitlines():
        m = re.match(r"^(\d+)\t\[\[ binary data .*? (png|jpeg|jpg|webp|bmp|gif) (\d+)x(\d+) \]\]$", ln)
        if m and int(m.group(3)) >= 48 and int(m.group(4)) >= 48:
            res.append((m.group(1), m.group(2), int(m.group(3)), int(m.group(4))))
            if len(res) >= CLIP_N:
                break
    return res


def clip_file(cid, fmt):
    """Картинка из буфера файлом (для перетаскивания в чат); уже есть — не декодировать."""
    os.makedirs(CLIP_DIR, exist_ok=True)
    path = os.path.join(CLIP_DIR, "%s.%s" % (cid, "jpg" if fmt == "jpeg" else fmt))
    if not os.path.exists(path):
        with open(path + ".tmp", "wb") as f:
            r = subprocess.run(["cliphist", "decode", cid], stdout=f, stderr=subprocess.DEVNULL, timeout=5)
        if r.returncode != 0:
            os.unlink(path + ".tmp")
            return None
        os.replace(path + ".tmp", path)
    return path


def prune_clip(keep):
    try:
        for f in os.listdir(CLIP_DIR):
            if f.split(".")[0] not in keep:
                os.unlink(os.path.join(CLIP_DIR, f))
    except OSError:
        pass


# ─────────────────────────── что показывать ───────────────────────────

def activities(conf, music, calls=None, timers=None):
    """[(вид, данные)] идущих дел — в порядке страниц из настроек (он же приоритет)."""
    out = []
    for p in page_ids(conf):
        if p == "call":
            for name in sorted(calls or {}, key=lambda k: calls[k]["since"]):
                out.append(("call", calls[name]))
        elif p == "rec":
            r = read_rec()
            if r:
                out.append(("rec", r))
        elif p == "pomo":
            d = read_pomo()
            if d:
                out.append(("pomo", d))
        elif p == "timer":
            if timers:
                out.append(("timer", {"list": timers}))
        elif p == "music" and music is not None:
            m = music.current()
            if m:
                out.append(("music", m))
    return out


def all_pages(conf, acts, clip, cat=None):
    """Страницы карточки по порядку настроек: идущие дела + постоянные (таймер, буфер,
    захват, фокус). Таймер есть всегда: без таймеров на нём только готовые отрезки."""
    out = []
    for p in page_ids(conf):
        mine = [a for a in acts if a[0] == p]
        if PAGES[p][2] == "live":
            out += mine
        elif p == "timer":
            out += mine or [("timer", {"list": []})]
        elif p == "clip":
            out.append(("clip", clip))
        elif p == "cat":
            out.append(("cat", cat))
        else:
            out.append((p, None))
    return out


def page_key(page):
    """Ключ страницы для «запомнить, где остановились»: вид + приложение звонка."""
    k, d = page
    return "call:" + d["app"] if k == "call" else k


def call_sec(d):
    return max(0, int(time.time() - d["since"]))


def timer_rem(t):
    return max(0, int(t["due"] - time.time()))


def act_line(kind, d):
    """(значок, текст, цвет-ключ) для компакта."""
    if kind == "rec":
        return (G_PAUSE if d["paused"] else "●", "%s  %s" % (mmss(d["sec"]), "пауза" if d["paused"] else d["mode"]), "error")
    if kind == "pomo":
        icon = G_PAUSE if d["paused"] else (G_POMO if d["phase"] == "work" else G_BREAK)
        return (icon, "%s  %s" % (mmss(d["rem"]), d["task"] or ("фокус" if d["phase"] == "work" else "перерыв")), "primary")
    if kind == "music":
        t = d.title if not d.artist else "%s — %s" % (d.artist, d.title)
        return (G_PAUSE if d.status != "Playing" else G_NOTE, t, "tertiary")
    if kind == "call" and d.get("voice"):
        return (G_MIC, "%s  голосовое сообщение" % mmss(call_sec(d)), "error")
    if kind == "call":
        return (d["icon"], "%s  %s · микрофон %s" % (mmss(call_sec(d)), d["app"], "выкл" if d["muted"] else "вкл"),
                "call")
    if kind == "timer" and not d["list"]:
        return (G_TIMER, "Таймер", "secondary")
    if kind == "timer":
        t = d["list"][0]
        more = "  +%d" % (len(d["list"]) - 1) if len(d["list"]) > 1 else ""
        return (G_TIMER, "%s  %s%s" % (mmss(timer_rem(t)), t["text"], more), "secondary")
    if kind in PAGES and PAGES[kind][2] == "static":
        return (PAGE_GLYPH[kind], PAGES[kind][0], "primary")
    if kind == "flash":
        return (d.get("icon") or "", d.get("text") or "", "primary")
    return ("", "", "primary")


def progress(kind, d):
    if kind == "pomo" and d["dur"]:
        return 1 - d["rem"] / d["dur"]
    if kind == "music" and d.length:
        return min(1.0, d.position() / d.length)
    if kind == "timer" and d["list"]:
        t = d["list"][0]
        dur = max(1, t["due"] - t["created"])
        return max(0.0, min(1.0, 1 - timer_rem(t) / dur))
    return None


# ─────────────────────────── рисование ───────────────────────────

def colors():
    import popup_theme
    p = popup_theme.palette()
    rgb = lambda h: tuple(int(h.lstrip("#")[i:i + 2], 16) / 255 for i in (0, 2, 4))
    c = {k: rgb(v) for k, v in p.items()}
    c["bg"] = rgb(popup_theme.bar_bg())
    return c


def ease_out(t):
    return 1 - (1 - t) ** 3


def ease_back(t, s=1.4):
    t -= 1
    return 1 + (s + 1) * t ** 3 + s * t ** 2


# Виды островка (19.10.2026: «сделай несколько видов, я выберу»). gap — отступ сверху
# (0 — вырезом из бара), R — радиус, ears — вогнутые ушки у бара, border — (цвет, толщина),
# fill — фон (bg — как у бара, black — чёрный), shadow — soft/hard/None.
DESIGNS = {
    "float":   {"name": "Плашка", "gap": 6, "R": 12, "ears": 0, "border": ("primary", 2), "fill": "bg", "shadow": "soft"},
    "capsule": {"name": "Капсула", "gap": 6, "R": 99, "ears": 0, "border": None, "fill": "black", "shadow": "soft"},
    "pixel":   {"name": "Пиксель", "gap": 6, "R": 0, "ears": 0, "border": ("primary", 2), "fill": "bg", "shadow": "hard",
                "stairs": 3},
    "glass":   {"name": "Стекло", "gap": 6, "R": 16, "ears": 0, "border": ("glass", 1), "fill": "glass", "shadow": "soft"},
    "skeet":   {"name": "Skeet", "gap": 6, "R": 0, "ears": 0, "border": ("skeet", 1), "fill": "skeet", "shadow": "hard",
                "line": True},
    # 19.10.2026: «минималистичные, круглые, как в iOS» — чёрная капсула, Inter, значок в
    # кольце прогресса справа; карточка — большое кольцо слева и кнопки-плашки.
    "ios":     {"name": "iOS", "gap": 6, "R": 99, "ears": 0, "border": None, "fill": "black", "shadow": "soft",
                "font": "Inter", "ios": True},
}
AUTO_DESIGN = {"default": "float", "beta": "pixel", "skeet": "skeet"}   # «как стиль системы»


def design(name, style="default"):
    if name not in DESIGNS:
        name = AUTO_DESIGN.get(style, "float")
    return DESIGNS[name]


def top_of(D, h, ty=THREAD_Y):
    """Отступ сверху: нить — ty под краем (посередине до окон, thread_y), раскрытый островок —
    на gap (вырез без gap висит вплотную); между ними — плавно по высоте."""
    k = max(0.0, min(1.0, (h - THREAD_H) / max(1, COMPACT_H - THREAD_H)))
    return ty + (max(D["gap"], ty) - ty) * k if D["gap"] else ty * (1 - k)


def pill_path(cr, x, w, h, D):
    """Фигура вида D; верх — y=0 (сдвиг сверху делает paint через translate)."""
    cr.new_path()
    E = min(D["ears"], h)
    if E or (not D["gap"] and D["R"]):         # вырез: верх вплотную, ушки, скруглённое дно
        R = min(D["R"], h / 2, w / 2)
        cr.move_to(x - E, 0)
        cr.line_to(x + w + E, 0)
        if E:
            cr.arc_negative(x + w + E, E, E, -math.pi / 2, -math.pi)
        cr.line_to(x + w, h - R)
        if R:
            cr.arc(x + w - R, h - R, R, 0, math.pi / 2)
        cr.line_to(x + R, h)
        if R:
            cr.arc(x + R, h - R, R, math.pi / 2, math.pi)
        cr.line_to(x, E)
        if E:
            cr.arc_negative(x - E, E, E, 0, -math.pi / 2)
    elif D.get("stairs") and h > 8:             # пиксельные углы ступеньками по 2 px
        n, st = D["stairs"], 2
        c = n * st
        poly = []
        for i in range(n):
            poly += [(x + i * st, c - i * st), (x + (i + 1) * st, c - i * st)]
        poly += [(x + c, 0), (x + w - c, 0)]
        for i in range(n):
            poly += [(x + w - c + i * st, i * st), (x + w - c + (i + 1) * st, i * st)]
        poly += [(x + w, c), (x + w, h - c)]
        for i in range(n):
            poly += [(x + w - i * st, h - c + i * st), (x + w - (i + 1) * st, h - c + i * st)]
        poly += [(x + w - c, h), (x + c, h)]
        for i in range(n):
            poly += [(x + c - i * st, h - i * st), (x + c - i * st, h - (i + 1) * st)]
        poly += [(x, h - c), (x, c)]
        cr.move_to(*poly[0])
        for pt in poly[1:]:
            cr.line_to(*pt)
    else:                                       # скруглённый прямоугольник / капсула
        R = min(D["R"], h / 2, w / 2, 28 if h > 40 else h)
        if R <= 0:
            cr.rectangle(x, 0, w, h)
            return
        cr.arc(x + w - R, R, R, -math.pi / 2, 0)
        cr.arc(x + w - R, h - R, R, 0, math.pi / 2)
        cr.arc(x + R, h - R, R, math.pi / 2, math.pi)
        cr.arc(x + R, R, R, math.pi, 3 * math.pi / 2)
    cr.close_path()


def layout(cr, text, px, bold=False):
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(FONT + ", JetBrainsMono Nerd Font")
    if FONT != PIXEL_FONT:
        px = SANS_PX.get(px, px)
    fd.set_absolute_size(px * Pango.SCALE)
    if bold:
        fd.set_weight(Pango.Weight.BOLD)
    lay.set_font_description(fd)
    lay.set_text(text, -1)
    return lay


def text_w(cr, text, px):
    return layout(cr, text, px).get_pixel_size()[0]


def put_text(cr, text, px, x, y, rgb, alpha=1.0, maxw=None, center=False):
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango, PangoCairo
    lay = layout(cr, text, px)
    if maxw:
        lay.set_width(int(maxw * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    w, h = lay.get_pixel_size()
    cr.move_to(x - (w / 2 if center else 0), y - h / 2)
    cr.set_source_rgba(*rgb, alpha)
    PangoCairo.show_layout(cr, lay)
    return w


PIXEL_FONT = "PxPlus HP 100LX 6x8 Jarvis"
FONT = PIXEL_FONT
SANS_PX = {8: 13, 16: 15, 24: 26}   # пиксельные кегли 8/16/24 → обычный шрифт


def use_font(D):
    """Шрифт вида D: пиксельный у всех, кроме тех, где задан свой (iOS — Inter)."""
    global FONT
    FONT = (D or {}).get("font", PIXEL_FONT)


def font_opts(cr):
    import cairo
    fo = cairo.FontOptions()
    fo.set_antialias(cairo.ANTIALIAS_NONE if "PxPlus" in FONT else cairo.ANTIALIAS_GRAY)
    fo.set_hint_style(cairo.HINT_STYLE_FULL)
    import gi
    from gi.repository import PangoCairo
    PangoCairo.context_set_font_options(PangoCairo.create_context(cr), fo)
    cr.set_font_options(fo)


def compact_w(cr, kind, d, extra, D=None):
    icon, text, _c = act_line(kind, d)
    use_font(D)
    if D and D.get("ios"):
        return max(150, min(CW - 60, 18 + text_w(cr, text, 13) + 10 + COMPACT_H + 12 * extra))
    return max(150, min(CW - 60, 16 + 16 + 10 + text_w(cr, text, 8) + 16 + 12 * extra))


def fill_rgba(D, col):
    f = D["fill"]
    if f == "black":
        return (0, 0, 0, 1)
    if f == "skeet":
        return (0.05, 0.05, 0.05, 1)
    if f == "glass":
        return (*col["bg"], 0.62)
    return (*col["bg"], 1)


def border_rgba(D, col):
    k, _w = D["border"]
    if k == "glass":
        return (1, 1, 1, 0.22)
    if k == "skeet":
        return (0.24, 0.24, 0.24, 1)
    return (*col[k], 1)


def paint(cr, st, col, D):
    """Рисует островок вида D по состоянию st (геометрия анимации + содержимое). Чистая
    функция: её же зовёт shot() вне экрана. Щелчковые зоны — в координатах холста."""
    import cairo
    cr.set_operator(cairo.OPERATOR_SOURCE)
    cr.set_source_rgba(0, 0, 0, 0)
    cr.paint()
    cr.set_operator(cairo.OPERATOR_OVER)
    w, h = st["w"], st["h"]
    if w < 2 or h < 1:
        return []
    use_font(D)
    font_opts(cr)
    x = (CW - w) / 2
    ty = st.get("ty", THREAD_Y)
    top = top_of(D, h, ty)
    style = eff_style(st.get("style"), st.get("acts"))
    if st["mode"] == "thread" and style == "cat":
        return paint_cat_pill(cr, x, ty, w, h, st, col, D)
    if st["mode"] == "thread" and style == "pill":
        return paint_pill(cr, x, ty, w, h, st, col)
    if st["mode"] == "thread" and h <= THREAD_H + 2:
        paint_thread(cr, x, top, w, st, col, D)
        return []
    cr.save()
    cr.translate(0, top)
    if D["shadow"] == "soft" and h > 6:
        for dy, al in ((5, 0.10), (3, 0.16), (1.5, 0.22)):
            cr.save()
            cr.translate(0, dy)
            pill_path(cr, x, w, h, D)
            cr.set_source_rgba(0, 0, 0, al)
            cr.fill()
            cr.restore()
    elif D["shadow"] == "hard" and h > 6:
        cr.save()
        cr.translate(3, 3)
        pill_path(cr, x, w, h, D)
        cr.set_source_rgba(0, 0, 0, 0.55)
        cr.fill()
        cr.restore()
    pill_path(cr, x, w, h, D)
    cr.set_source_rgba(*fill_rgba(D, col))
    cr.fill_preserve()
    cr.save()
    cr.clip()
    if D["fill"] == "glass" and h > 6:          # блик сверху, как у стекла
        g = cairo.LinearGradient(0, 0, 0, h)
        g.add_color_stop_rgba(0, 1, 1, 1, 0.10)
        g.add_color_stop_rgba(0.5, 1, 1, 1, 0.0)
        cr.rectangle(x, 0, w, h)
        cr.set_source(g)
        cr.fill()
    if D["border"]:
        pill_path(cr, x, w, h, D)
        cr.set_line_width(2 * D["border"][1])   # половина толщины срезается клипом
        cr.set_source_rgba(*border_rgba(D, col))
        cr.stroke()
    if D.get("line"):                           # полоса палитры по верхней кромке, как у gamesense
        g = cairo.LinearGradient(x, 0, x + w, 0)
        for i, k in enumerate(("primary", "secondary", "tertiary")):
            g.add_color_stop_rgb(i / 2, *col[k])
        cr.rectangle(x, 0, w, 2)
        cr.set_source(g)
        cr.fill()
    cr.restore()
    hits = []
    acts, mode, a = st["acts"], st["mode"], st["alpha"]
    pages, ci = acts, 0
    if mode == "card":                          # карточка листает страницы, не только дела
        pages = st["pages"] if isinstance(st.get("pages"), list) else acts
        ci = st.get("card_i", 0) % len(pages) if pages else 0
    if not pages or a <= 0:
        cr.restore()
        return hits
    kind, d = pages[ci]
    cr.save()
    pill_path(cr, x, w, h, D)
    cr.clip()
    if mode == "thread" or h <= 12:
        # нить: точка записи, полоса помидора/трека, полоски музыки — без текста
        cx = CW / 2 - 6 * (len(acts) - 1)
        for k, dd in acts[:3]:
            c = act_color(k, col)
            if k == "music":
                for i, bh in enumerate((3, 5, 2)):
                    cr.rectangle(cx - 4 + i * 3, h - 2 - bh, 2, bh)
            else:
                cr.rectangle(cx - 2, h / 2 - 2, 4, 4)
            cr.set_source_rgba(*c, a)
            cr.fill()
            cx += 12
        pr = progress(kind, d)
        if pr is not None:
            cr.rectangle(x + 4, h - 2, (w - 8) * pr, 1)
            cr.set_source_rgba(*col["primary"], 0.8 * a)
            cr.fill()
    elif mode == "compact" and D.get("ios"):
        ios_compact(cr, x, w, h, kind, d, acts, col, a)
    elif mode == "compact":
        icon, text, ck = act_line(kind, d)
        mid = h / 2
        put_text(cr, icon, 16, x + 14, mid, ck_rgb(ck, col), a)
        put_text(cr, text, 8, x + 38, mid, col["on_surface"], a, maxw=w - 38 - 14 - 12 * (len(acts) - 1))
        for i, (k, _dd) in enumerate(acts[1:3]):
            c = act_color(k, col)
            cr.rectangle(x + w - 14 - i * 12, mid - 2, 4, 4)
            cr.set_source_rgba(*c, a)
            cr.fill()
        pr = progress(kind, d)
        if pr is not None:
            cr.rectangle(x + 12, h - 3, (w - 24) * pr, 1)
            cr.set_source_rgba(*col["primary"], 0.7 * a)
            cr.fill()
    elif D.get("ios"):
        hits = paint_card_ios(cr, x, w, h, kind, d, pages, col, a, (len(pages), ci))
    else:
        hits = paint_card(cr, x, w, h, kind, d, pages, col, a, ci)
    cr.restore()
    cr.restore()
    return [((hx, hy + top, hw, hh), act) for (hx, hy, hw, hh), act in hits]


def paint_thread(cr, x, top, w, st, col, D):
    """Нить: ровная сглаженная линия или точки, тусклая (thread_alpha). Прогресс помидора или
    трека — та же линия ярче, цветом дела. ta=0 — спрятана (видео), наведение проявляет."""
    import cairo
    a = st.get("ta", 0.35)
    if a <= 0.01:
        return
    cr.save()
    cr.set_antialias(cairo.ANTIALIAS_GOOD)
    acts = st["acts"]
    kind, d = acts[0] if acts else (None, None)
    pr = progress(kind, d) if kind else None
    acc = act_color(kind, col) if kind else col["on_surface"]
    lit_c = acc
    if D.get("line"):                                   # Skeet: перелив палитры, как у виджетов
        base = cairo.LinearGradient(x, 0, x + w, 0)
        for i, k in enumerate(("primary", "secondary", "tertiary")):
            base.add_color_stop_rgba(i / 2, *col[k], a)
    else:                                               # акцент обоев, не серый (19.10.2026, пользователь)
        base = cairo.SolidPattern(*col["primary"], min(0.85, a * 2.4))
        lit_c = tuple(v + (1 - v) * 0.45 for v in acc)  # прогресс светлее основы, иначе сливается
    y = top + THREAD_H / 2
    if st.get("style") == "dots":
        n = max(3, int(w / 11))
        step = w / (n - 1)
        for i in range(n):
            cx = x + i * step
            lit = pr is not None and i / (n - 1) <= pr
            cr.arc(cx, y, 2.1, 0, 2 * math.pi)
            if lit:
                cr.set_source_rgba(*lit_c, min(1.0, a * 2.8))
            else:
                cr.set_source(base)
            cr.fill()
    else:
        r = THREAD_H / 2
        cr.set_line_width(THREAD_H)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.move_to(x + r, y)
        cr.line_to(x + w - r, y)
        cr.set_source(base)
        cr.stroke()
        if pr:
            cr.move_to(x + r, y)
            cr.line_to(x + r + (w - 2 * r) * pr, y)
            cr.set_source_rgba(*lit_c, min(1.0, a * 2.8))
            cr.stroke()
    cr.restore()


PILL_PX, PILL_GAP, PILL_PAD, PILL_MAX = 12, 6, 11, 280
MUSIC_MAXW = 130


def pill_parts(acts, col):
    """Живая капсула (19.10.2026, просьба: «если телеграм звонок активный — значок тг,
    длительность и статус микро с возможностью нажать… если музыка — её»): главное дело
    (первая живая страница по порядку настроек) крупно, остальные — точками справа; дел нет —
    точка и часы. [(вид, значение, цвет)]: g — значок, t — текст, mic — кнопка микрофона,
    bars — полоски музыки, dot — точка слева, sdot — точка другого дела."""
    live = [a for a in acts if a[0] in PAGES]
    on = col["on_surface"] if col else (1, 1, 1)
    if not live:
        return [("dot", None, on), ("t", time.strftime("%H:%M"), None)]
    kind, d = live[0]
    c = act_color(kind, col) if col else on
    if kind == "call":
        parts = [("g", d["icon"], CALL_GREEN), ("t", mmss(call_sec(d)), None), ("mic", d["muted"], None)]
    elif kind == "rec":
        parts = [("g", G_PAUSE, (1.0, 0.27, 0.27)) if d["paused"] else ("dot", None, (1.0, 0.27, 0.27)),
                 ("t", mmss(d["sec"]), None)]
    elif kind == "pomo":
        g = G_PAUSE if d["paused"] else (G_POMO if d["phase"] == "work" else G_BREAK)
        parts = [("g", g, c), ("t", mmss(d["rem"]), None)]
    elif kind == "timer" and d["list"]:
        parts = [("g", G_TIMER, c), ("t", mmss(timer_rem(d["list"][0])), None)]
    elif kind == "music":
        parts = [("bars", d.status == "Playing", c), ("tm", d.title or "—", None)]
    else:
        icon, text, ck = act_line(kind, d)
        parts = [("g", icon, c), ("t", text, None)]
    for k, _d in live[1:3]:
        parts.append(("sdot", None, act_color(k, col) if col else on))
    return parts


def pill_text(cr, text, maxw=None):
    """Текст капсулы: Inter SemiBold, цифры одной ширины (секунды не дёргают капсулу)."""
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango
    global FONT
    keep, FONT = FONT, "Inter"
    cr.save()
    font_opts(cr)                                # сглаженный, даже если вид пиксельный
    lay = layout(cr, text, PILL_PX)
    cr.restore()
    FONT = keep
    fd = lay.get_font_description()
    fd.set_weight(Pango.Weight.SEMIBOLD)
    lay.set_font_description(fd)
    try:
        al = Pango.AttrList()
        al.insert(Pango.attr_font_features_new("tnum"))
        lay.set_attributes(al)
    except Exception:
        pass
    if maxw:
        lay.set_width(int(maxw * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


def part_w(cr, p):
    k, v, _c = p
    if k == "dot":
        return 6
    if k == "sdot":
        return 5
    if k == "bars":
        return 10
    if k == "mic":
        return 18
    return pill_text(cr, v, MUSIC_MAXW if k == "tm" else None).get_pixel_size()[0]


def pill_w(cr, acts, col=None):
    parts = pill_parts(acts, col)
    w = 2 * PILL_PAD + sum(part_w(cr, p) for p in parts) + PILL_GAP * (len(parts) - 1)
    return float(max(PILL_W, min(PILL_MAX, int(math.ceil(w / 2.0)) * 2)))


def paint_pill(cr, x, top, w, h, st, col):
    """Нить-капсула: чёрная капсула с живым содержимым (pill_parts). Видна целиком, без
    «тусклости». Возвращает щелчковые зоны (кнопка микрофона звонка)."""
    import cairo
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    hits = []
    if st.get("ta", 1) <= 0.01 or w < 4 or h < 2:
        return hits
    cr.save()
    cr.set_antialias(cairo.ANTIALIAS_GOOD)
    r = h / 2
    cr.new_path()
    cr.arc(x + w - r, top + r, r, -math.pi / 2, math.pi / 2)
    cr.arc(x + r, top + r, r, math.pi / 2, 3 * math.pi / 2)
    cr.close_path()
    cr.set_source_rgba(0.02, 0.02, 0.03, 0.92)
    cr.fill_preserve()
    cr.set_line_width(1)
    cr.set_source_rgba(1, 1, 1, 0.08)
    cr.stroke()
    parts = pill_parts(st["acts"], col)
    need = 2 * PILL_PAD + sum(part_w(cr, p) for p in parts) + PILL_GAP * (len(parts) - 1)
    if w >= min(need, PILL_MAX) * 0.85 and h >= PILL_H * 0.6:   # пока капсула растёт — пусто
        cr.rectangle(x, top, w, h)
        cr.clip()
        cx = x + max(PILL_PAD, (w - need) / 2 + PILL_PAD)
        cy = top + r
        for p in parts:
            k, v, c = p
            pw = part_w(cr, p)
            if k in ("dot", "sdot"):
                cr.arc(cx + pw / 2, cy, 2.6 if k == "dot" else 2.0, 0, 2 * math.pi)
                cr.set_source_rgba(*c, 1 if k == "dot" else 0.8)
                cr.fill()
            elif k == "bars":
                hs = (5, 9, 6) if v else (3, 3, 3)
                for i, bh in enumerate(hs):
                    cr.rectangle(cx + i * 4, cy + 4.5 - bh, 2, bh)
                cr.set_source_rgba(*c, 1)
                cr.fill()
            elif k == "mic":
                mc = (1.0, 0.36, 0.36) if v else CALL_GREEN
                cr.arc(cx + 9, cy, 8.5, 0, 2 * math.pi)
                cr.set_source_rgba(*mc, 0.22)
                cr.fill()
                lay = pill_text(cr, G_MIC_OFF if v else G_MIC)
                gw, gh = lay.get_pixel_size()
                cr.move_to(cx + 9 - gw / 2, cy - gh / 2)
                cr.set_source_rgba(*mc, 1)
                PangoCairo.show_layout(cr, lay)
                hits.append(((cx - 3, 0, pw + 6, top + h + 4), ("call", "mute")))
            else:
                lay = pill_text(cr, v, MUSIC_MAXW if k == "tm" else None)
                tw, th = lay.get_pixel_size()
                cr.move_to(cx, cy - th / 2)
                cr.set_source_rgba(*(c or (1, 1, 1)), 1 if k == "g" else 0.92)
                PangoCairo.show_layout(cr, lay)
            cx += pw + PILL_GAP
    cr.restore()
    return hits


def button(cr, cx, cy, glyph, col, a, hits, action, big=False):
    r = 14 if big else 11
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.set_source_rgba(*(col["primary"] if big else col["surface_high"]), a * (1 if big else 0.9))
    cr.fill()
    put_text(cr, glyph, 16, cx, cy, col["on_primary"] if big else col["on_surface"], a, center=True)
    hits.append(((cx - r, cy - r, 2 * r, 2 * r), action))


def paint_card(cr, x, w, h, kind, d, acts, col, a, card_i):
    hits = []
    pad = 18
    icon, text, ck = act_line(kind, d)
    # страницы: квадратики сверху справа цветом дела, щелчок переключает (колесо — тоже)
    for i, (k, _dd) in enumerate(acts if len(acts) > 1 else []):
        c = act_color(k, col)
        bx = x + w - pad - 6 - (len(acts) - 1 - i) * 14
        cr.rectangle(bx, 14, 6, 6)
        cr.set_source_rgba(*c, a if i == card_i else 0.35 * a)
        cr.fill()
        hits.append(((bx - 4, 8, 14, 18), ("page", i)))
    if kind == "cat":
        paint_cat_card(cr, x, w, h, d, col, a, hits, False)
        return hits
    if kind in ("clip", "capture", "focus"):
        (paint_clip if kind == "clip" else paint_tools)(cr, x, w, h, d if kind == "clip" else kind, col, a, hits, False)
        return hits
    pr = progress(kind, d)
    by = h - 26 - (32 if kind == "timer" else 0)     # у таймера снизу ряд готовых отрезков
    if kind == "music":
        put_text(cr, G_NOTE, 16, x + pad + 8, 30, ck_rgb(ck, col), a, center=True)
        put_text(cr, d.title or "—", 16, x + pad + 26, 28, col["on_surface"], a, maxw=w - 2 * pad - 26 - 50)
        put_text(cr, d.artist or d.identity, 8, x + pad + 26, 46, col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad - 26)
        if pr is not None:
            put_text(cr, mmss(d.position()), 8, x + pad, by, col["on_surface_variant"], 0.8 * a)
            put_text(cr, mmss(d.length), 8, x + w - pad - text_w(cr, mmss(d.length), 8), by, col["on_surface_variant"], 0.8 * a)
        c = x + w / 2
        button(cr, c - 40, by, G_PREV, col, a, hits, ("music", "Previous"))
        button(cr, c, by, G_PAUSE if d.status == "Playing" else G_PLAY, col, a, hits, ("music", "PlayPause"), big=True)
        button(cr, c + 40, by, G_NEXT, col, a, hits, ("music", "Next"))
    elif kind == "pomo":
        put_text(cr, mmss(d["rem"]), 24, x + pad, 34, col["on_surface"], a)
        sub = ("Фокус" if d["phase"] == "work" else "Перерыв") + (" · пауза" if d["paused"] else "") + \
            (" · " + d["task"] if d["task"] else "")
        put_text(cr, sub, 8, x + pad, 56, col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        c = x + w - pad - 70
        button(cr, c, by, G_PLAY if d["paused"] else G_PAUSE, col, a, hits, ("pomo", "toggle"), big=True)
        button(cr, c + 36, by, G_SKIP, col, a, hits, ("pomo", "skip"))
        button(cr, c + 66, by, G_STOP, col, a, hits, ("pomo", "stop"))
    elif kind == "rec":
        put_text(cr, "●", 16, x + pad + 6, 34, col["error"], a, center=True)
        put_text(cr, mmss(d["sec"]), 24, x + pad + 22, 34, col["on_surface"], a)
        put_text(cr, ("Пауза · " if d["paused"] else "Идёт запись · ") + d["mode"], 8, x + pad, 56,
                 col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        c = x + w - pad - 50
        button(cr, c, by, G_PLAY if d["paused"] else G_PAUSE, col, a, hits, ("rec", "pause"), big=True)
        button(cr, c + 36, by, G_STOP, col, a, hits, ("rec", "halt"))
    elif kind == "call":
        put_text(cr, d["icon"], 16, x + pad + 8, 30, CALL_GREEN, a, center=True)
        put_text(cr, d["app"] + " · звонок", 16, x + pad + 26, 28, col["on_surface"], a, maxw=w - 2 * pad - 26 - 70)
        put_text(cr, "Микрофон выключен" if d["muted"] else "Микрофон включён", 8, x + pad + 26, 46,
                 col["error"] if d["muted"] else col["on_surface_variant"], 0.85 * a)
        put_text(cr, mmss(call_sec(d)), 24, x + pad, by, col["on_surface"], a)
        c = x + w - pad - 50
        button(cr, c, by, G_MIC_OFF if d["muted"] else G_MIC, col, a, hits, ("call", "mute"), big=True)
        button(cr, c + 36, by, G_OPEN, col, a, hits, ("call", "focus"))
    elif kind == "timer" and d["list"]:
        t = d["list"][0]
        put_text(cr, mmss(timer_rem(t)), 24, x + pad, 34, col["on_surface"], a)
        more = " · ещё %d" % (len(d["list"]) - 1) if len(d["list"]) > 1 else ""
        put_text(cr, t["text"] + more, 8, x + pad, 56, col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        c = x + w - pad - 50
        button(cr, c, by, G_STOP, col, a, hits, ("timer", "stop:%d" % t["id"]), big=True)
        button(cr, c + 36, by, G_OPEN, col, a, hits, ("timer", "open"))
    elif kind == "timer":
        put_text(cr, G_TIMER, 16, x + pad + 8, 32, ck_rgb(ck, col), a, center=True)
        put_text(cr, "Таймер", 16, x + pad + 26, 30, col["on_surface"], a)
        put_text(cr, "Сколько поставить? Щелчок — сразу идёт, звенит hub.", 8, x + pad, 62,
                 col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        button(cr, x + w - pad - 14, 30, G_OPEN, col, a, hits, ("timer", "open"))
    else:
        put_text(cr, icon, 16, x + pad + 8, h / 2, ck_rgb(ck, col), a, center=True)
        put_text(cr, text, 16, x + pad + 26, h / 2, col["on_surface"], a, maxw=w - 2 * pad - 26)
    if pr is not None:
        cr.rectangle(x + pad, by - 22, w - 2 * pad, 2)
        cr.set_source_rgba(*col["surface_high"], a)
        cr.fill()
        cr.rectangle(x + pad, by - 22, (w - 2 * pad) * pr, 2)
        cr.set_source_rgba(*col["primary"], a)
        cr.fill()
    if kind == "timer":
        paint_presets(cr, x + pad, h - 34, w - 2 * pad, col, a, hits, False)
    return hits


def paint_presets(cr, x, y, w, col, a, hits, ios):
    """Готовые отрезки таймера 5–60 минут и «Своё…» (19.10.2026, просьба: «сразу с готовым
    пресетом или с выбором собственного времени»)."""
    items = [(("%d м" if ios else "%d мин") % m, "start:%d" % m) for m in TIMER_PRESETS] + [("Своё…", "ask")]
    gap, bh = 6, 22
    bw = (w - gap * (len(items) - 1)) / len(items)
    for i, (label, what) in enumerate(items):
        bx = int(x + i * (bw + gap))            # целые пиксели: пиксельный шрифт не размывается
        if ios:
            rrect(cr, bx, y, bw, bh, bh / 2)
            cr.set_source_rgba(1, 1, 1, (0.2 if what == "ask" else 0.1) * a)
            cr.fill()
            fg = (1, 1, 1)
        else:
            cr.rectangle(bx, y, bw, bh)
            cr.set_source_rgba(*col["surface_high"], 0.9 * a)
            cr.fill()
            if what == "ask":
                cr.rectangle(bx + 0.5, y + 0.5, bw - 1, bh - 1)
                cr.set_line_width(1)
                cr.set_source_rgba(*col["primary"], 0.7 * a)
                cr.stroke()
            fg = col["on_surface"]
        put_text(cr, label, 8, int(bx + bw / 2), y + bh / 2, fg, a, maxw=bw - 4, center=True)
        hits.append(((bx, y, bw, bh), ("timer", what)))


def ring(cr, cx, cy, r, pr, rgb, a, lw):
    """Кольцо прогресса: бледная дорожка и дуга от 12 часов (pr None — полное кольцо)."""
    cr.set_line_width(lw)
    cr.new_path()
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.set_source_rgba(*rgb, (0.28 if pr is not None else 1.0) * a)
    cr.stroke()
    if pr is not None and pr > 0:
        cr.new_path()
        cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * min(1.0, pr))
        cr.set_source_rgba(*rgb, a)
        cr.set_line_cap(1)                      # ROUND
        cr.stroke()
        cr.set_line_cap(0)


def act_color(k, col):
    if k == "call":
        return CALL_GREEN
    return col["error"] if k == "rec" else col["secondary"] if k == "timer" else \
        col["tertiary"] if k == "music" else col["primary"]


def ck_rgb(ck, col):
    """Цвет-ключ act_line → rgb (звонок — свой зелёный, его нет в палитре)."""
    return CALL_GREEN if ck == "call" else col[ck]


def ios_compact(cr, x, w, h, kind, d, acts, col, a):
    """Компакт iOS: белый текст слева, справа значок в кольце прогресса цвета дела."""
    icon, text, ck = act_line(kind, d)
    mid = h / 2
    cx = x + w - h / 2 - 1
    r = h / 2 - 5
    ring(cr, cx, mid, r, progress(kind, d), ck_rgb(ck, col), a, 2.5)
    put_text(cr, icon, 11, cx, mid, ck_rgb(ck, col), a, center=True)
    for i, (k, _dd) in enumerate(acts[1:3]):
        cr.arc(cx - r - 10 - i * 10, mid, 2.5, 0, 2 * math.pi)
        cr.set_source_rgba(*act_color(k, col), a)
        cr.fill()
    put_text(cr, text, 13, x + 16, mid, (1, 1, 1), a, maxw=cx - r - 14 - 10 * (len(acts) - 1) - x - 16)


def ios_button(cr, bx, by, bw, bh, glyph, rgb, a, hits, action, primary):
    R = 8
    cr.new_path()
    cr.arc(bx + bw - R, by + R, R, -math.pi / 2, 0)
    cr.arc(bx + bw - R, by + bh - R, R, 0, math.pi / 2)
    cr.arc(bx + R, by + bh - R, R, math.pi / 2, math.pi)
    cr.arc(bx + R, by + R, R, math.pi, 3 * math.pi / 2)
    cr.close_path()
    cr.set_source_rgba(*(rgb if primary else (1, 1, 1)), a * (1 if primary else 0.12))
    cr.fill()
    put_text(cr, glyph, 15, bx + bw / 2, by + bh / 2, (0.05, 0.05, 0.05) if primary else (1, 1, 1), a, center=True)
    hits.append(((bx, by, bw, bh), action))


def paint_card_ios(cr, x, w, h, kind, d, acts, col, a, pages):
    """Карточка iOS (по примеру пользователя): слева большое кольцо со временем, справа заголовок,
    подпись и кнопки-плашки; несколько дел — точки-страницы, листаются колесом."""
    hits = []
    n, cur = pages or (len(acts), 0)
    if kind == "cat":
        paint_cat_card(cr, x, w, h, d, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    if kind in ("clip", "capture", "focus"):
        (paint_clip if kind == "clip" else paint_tools)(cr, x, w, h, d if kind == "clip" else kind, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    icon, text, ck = act_line(kind, d)
    acc = ck_rgb(ck, col)
    pr = progress(kind, d)
    R = 38
    if kind == "timer":                         # снизу ряд отрезков — остальное выше
        paint_presets(cr, x + 18, h - 34, w - 36, col, a, hits, True)
        h -= 32
    cx, cy = x + 18 + R, h / 2
    ring(cr, cx, cy, R, pr, acc if pr is not None else (1, 1, 1), a if pr is not None else 0.25 * a, 3)
    if kind == "music":
        mid_t = mmss(d.position()) if d.length else G_NOTE
    elif kind == "pomo":
        mid_t = mmss(d["rem"])
    elif kind == "rec":
        mid_t = mmss(d["sec"])
    elif kind == "call":
        mid_t = mmss(call_sec(d))
    elif kind == "timer" and d["list"]:
        mid_t = mmss(timer_rem(d["list"][0]))
    else:
        mid_t = icon
    put_text(cr, mid_t, 20, cx, cy, (1, 1, 1), a, center=True)
    tx = cx + R + 18
    tw = x + w - 18 - tx
    if kind == "music":
        title, sub = d.title or "—", d.artist or d.identity
        btns = [(G_PREV, ("music", "Previous"), False),
                (G_PAUSE if d.status == "Playing" else G_PLAY, ("music", "PlayPause"), True),
                (G_NEXT, ("music", "Next"), False)]
    elif kind == "pomo":
        title = ("Фокус" if d["phase"] == "work" else "Перерыв") + (" · пауза" if d["paused"] else "")
        sub = d["task"] or ""
        btns = [(G_PLAY if d["paused"] else G_PAUSE, ("pomo", "toggle"), True),
                (G_SKIP, ("pomo", "skip"), False), (G_STOP, ("pomo", "stop"), False)]
    elif kind == "rec":
        title, sub = ("Пауза" if d["paused"] else "Идёт запись"), d["mode"]
        btns = [(G_PLAY if d["paused"] else G_PAUSE, ("rec", "pause"), True), (G_STOP, ("rec", "halt"), False)]
    elif kind == "call":
        title = d["app"] + " · звонок"
        sub = "Микрофон выключен" if d["muted"] else "Микрофон включён"
        btns = [(G_MIC_OFF if d["muted"] else G_MIC, ("call", "mute"), True), (G_OPEN, ("call", "focus"), False)]
    elif kind == "timer" and d["list"]:
        t = d["list"][0]
        title, sub = t["text"], ("ещё %d" % (len(d["list"]) - 1) if len(d["list"]) > 1 else "")
        btns = [(G_STOP, ("timer", "stop:%d" % t["id"]), True), (G_OPEN, ("timer", "open"), False)]
    elif kind == "timer":
        title, sub, btns = "Таймер", "Сколько поставить? Звенит hub", [(G_OPEN, ("timer", "open"), False)]
    else:
        title, sub, btns = text, "", []
    dots = 10 * n if n > 1 else 0
    put_text(cr, title, 15, tx, 26, (1, 1, 1), a, maxw=tw - dots - 6)
    if sub:
        put_text(cr, sub, 12, tx, 45, (1, 1, 1), 0.55 * a, maxw=tw)
    ios_dots(cr, x, w, n, cur, a, hits)
    if btns:
        gap, bh = 8, 28
        bw = (tw - gap * (len(btns) - 1)) / len(btns)
        for i, (g, act, prim) in enumerate(btns):
            ios_button(cr, tx + i * (bw + gap), h - 20 - bh, bw, bh, g, acc, a, hits, act, prim)
    return hits


def ios_dots(cr, x, w, n, cur, a, hits):
    """Точки-страницы iOS сверху справа; щелчок — на страницу."""
    if n <= 1:
        return
    for i in range(n):
        dx = x + w - 18 - (n - 1 - i) * 10
        cr.arc(dx, 26, 3, 0, 2 * math.pi)
        cr.set_source_rgba(1, 1, 1, (0.9 if i == cur else 0.3) * a)
        cr.fill()
        hits.append(((dx - 5, 16, 10, 20), ("page", i)))


def rrect(cr, x, y, w, h, R):
    cr.new_path()
    if R <= 0:
        cr.rectangle(x, y, w, h)
        return
    cr.arc(x + w - R, y + R, R, -math.pi / 2, 0)
    cr.arc(x + w - R, y + h - R, R, 0, math.pi / 2)
    cr.arc(x + R, y + h - R, R, math.pi / 2, math.pi)
    cr.arc(x + R, y + R, R, math.pi, 3 * math.pi / 2)
    cr.close_path()


def paint_clip(cr, x, w, h, d, col, a, hits, ios):
    """Страница «Снимки из буфера»: последние картинки плитками. Щелчок — снова в буфер,
    перетаскивание — файлом куда угодно (в чат Telegram, в папку)."""
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    px = 12 if ios else 8
    put_text(cr, "Снимки из буфера · перетащите в чат", px, x + pad, 22 if ios else 17, fg, 0.6 * a,
             maxw=w - 2 * pad - 80)
    d = d or {}
    items = d.get("items") or []
    if not items:
        put_text(cr, "Загружаю…" if d.get("loading") else "В буфере нет картинок", px, x + w / 2, h / 2 + 10,
                 fg, 0.55 * a, center=True)
        return
    gap = 8
    cols = 2                                  # сетка 2×2: два этажа (19.10.2026, пользователь)
    tw = (w - 2 * pad - gap * (cols - 1)) / cols
    top = 34
    th = (h - top - 14 - gap * (2 - 1)) / 2
    R = 8 if ios else 0
    for i, it in enumerate(items[:CLIP_N]):
        bx = x + pad + (i % cols) * (tw + gap)
        ty = top + (i // cols) * (th + gap)
        cr.save()
        rrect(cr, bx, ty, tw, th, R)
        cr.clip()
        cr.set_source_rgba(*((1, 1, 1) if ios else col["surface_high"]), (0.08 if ios else 1) * a)
        cr.paint()
        sf = it.get("surf")
        if sf is not None:
            iw, ih = sf.get_width(), sf.get_height()
            k = max(tw / iw, th / ih)                 # заполнить плитку, лишнее срезать
            cr.translate(bx + (tw - iw * k) / 2, ty + (th - ih * k) / 2)
            cr.scale(k, k)
            cr.set_source_surface(sf, 0, 0)
            cr.paint_with_alpha(a)
        cr.restore()
        if d.get("copied") == it["id"]:
            rrect(cr, bx + 1, ty + 1, tw - 2, th - 2, R)
            cr.set_line_width(2)
            cr.set_source_rgba(*col["primary"], a)
            cr.stroke()
        elif not ios:
            cr.rectangle(bx + 0.5, ty + 0.5, tw - 1, th - 1)
            cr.set_line_width(1)
            cr.set_source_rgba(*col["outline_variant"], 0.8 * a)
            cr.stroke()
        hits.append(((bx, ty, tw, th), ("clip", it["id"])))


def paint_tools(cr, x, w, h, _d, col, a, hits, ios):
    """Страница «Инструменты»: помидор, запись, таймер, заметка, пипетка, снимок, буфер."""
    pad = 12
    fg = (1, 1, 1) if ios else col["on_surface"]
    items = CAPTURE if _d == "capture" else FOCUS if _d == "focus" else TOOLS
    put_text(cr, PAGES.get(_d, ("Инструменты",))[0], 12 if ios else 8, x + pad + 6, 22 if ios else 17, fg, 0.6 * a)
    n = len(items)
    cw = (w - 2 * pad) / n
    cy = h / 2 + 4
    for i, (tid, g, label, _cmd) in enumerate(items):
        cx = round(x + pad + cw * i + cw / 2)      # целые — пиксельный шрифт не мажется
        if ios:
            rrect(cr, cx - 19, cy - 19, 38, 38, 12)
            cr.set_source_rgba(1, 1, 1, 0.12 * a)
        else:
            cr.new_path()
            cr.arc(cx, cy, 17, 0, 2 * math.pi)
            cr.set_source_rgba(*col["surface_high"], 0.9 * a)
        cr.fill()
        put_text(cr, g, 16 if not ios else 15, cx, cy, fg, a, center=True)
        put_text(cr, label, 11 if ios else 8, cx, cy + 31, fg, 0.7 * a, center=True)
        hits.append(((cx - cw / 2, cy - 22, cw, 60), ("tool", tid)))


# ─────────────────────────── резидент ───────────────────────────

# ─────────────────────────── котик ───────────────────────────
# Нить «Котик» (20.10.2026, просьба: «по центру будет бегать котик, если идёт работа в терминале, играет
# музыка или идёт помидор, а если нет — спит; справа обложка и эквалайзер квадратиками, слева
# время»; у песни с текстом вместо кота — строка песни). Подсмотрено у Halo из angelOS
# (github.com/MixaDoDs/AngelOS-Dotfiles, MIT). Кадры кота — оттуда же, из modules/halo/HaloCat.js:
# кот RunCat365 © 2020 Takuto Nakamura, Apache License 2.0 (github.com/runcat-dev/RunCat365),
# сведён к целым пикселям в angelOS. '#' — цвет текста, глаза вырезаны. 1 пиксель рисунка = 1 px.

CAT_RUN = (
    ("...##..........#...#", ".....##........##.##", ".......##......#####", "........#####..#.#.#",
     "........############", ".......############.", ".......###########..", ".......###..######..",
     "........#.....##.##.", "........#.....#...#.", "........##....#.....", "...................."),
    ("...............#...#", "...............##.##", "..........#....#####", "........######.#.#.#",
     "......##############", ".#################..", "#.....###########...", "........#######.....",
     "........######......", ".........##.##......", "..........#..##.....", "...................."),
    ("..............#...#.", "..............##.##.", "..............#####.", "............###.#.#.",
     "........###########.", "....############....", "####...#########....", ".......#########....",
     ".......####..###....", ".......###...##.....", "........#....#......", "...................."),
    ("...............#...#", "...............##.##", "...............#####", "..............##.#.#",
     "..........##########", "..#################.", "##.....############.", ".....#############..",
     "....######.....###..", "...####.........##..", "..##................", "...................."),
    ("...............#...#", "...###.........##.##", "..#...##.......#####", ".......##.....##.#.#",
     "........############", "......##############", ".....##############.", "....#######.#######.",
     ".......##........##.", ".......#..........#.", "....................", "...................."),
)
CAT_NAP = (
    ("....................", "....................", "....................", "....................",
     "..............#...#.", "......######..##.##.", "....##########.####.", "...###############..",
     "..################..", "..#################.", "...##############.#.", "..............####.."),
    ("....................", "....................", "....................", "....................",
     "....................", "..............#...#.", "......######..##.##.", "...###########.####.",
     "..################..", "..#################.", "...##############.#.", "..............####.."),
)
CAT_ZZ = ("####", "..#.", ".#..", "####")
CAT_HEART = (".#.#.", "#####", "#####", ".###.", "..#..")
CAT_TOMATO = ("..##...", "...#...", ".#####.", "#######", "#######", "#######", ".#####.")
CAT_BUSY = ("...#...", "#..#..#", ".#.#.#.", "..###..", ".#.#.#.", "#..#..#", "...#...")
CAT_W, CAT_H = 20, 12
CAT_FRAME_S = 0.14          # кадр бега (у angelOS 0.2 — нам бодрее)
CAT_FRAME_MS = 140
CAT_NAP_S = 1.0             # вдох-выдох спящего
CAT_PAD, CAT_GAP = 10, 9
CAT_MIN_W = 270             # просьба 20.10: длиннее — часы у левого края, обложка у правого
CAT_LYR_W = 210             # полоса строки песни в капсуле
CAT_COVER = 16              # обложка в капсуле: 8×8 «пикселей рисунка» по 2 px
CAT_EQ_N, CAT_EQ_ROWS, CAT_EQ_BLK = 4, 4, 2
BUSY_ORANGE = (0.85, 0.47, 0.34)
_RUNS = {}


def bitmap_runs(rows):
    """Строки '#.' → [(x, y, длина)]: одна заливка на отрезок вместо пикселя за пикселем."""
    key = id(rows)
    if key not in _RUNS:
        out = []
        for y, r in enumerate(rows):
            x = 0
            while x < len(r):
                if r[x] == "#":
                    e = x
                    while e < len(r) and r[e] == "#":
                        e += 1
                    out.append((x, y, e - x))
                    x = e
                else:
                    x += 1
        _RUNS[key] = out
    return _RUNS[key]


def draw_bitmap(cr, rows, x, y, k, rgb, a=1.0):
    for bx, by, n in bitmap_runs(rows):
        cr.rectangle(x + bx * k, y + by * k, n * k, k)
    cr.set_source_rgba(*rgb, a)
    cr.fill()


def pomo_rem(pm):
    """Остаток помидора на сейчас: файл читается раз в 2 с, секунды идут по часам."""
    if pm["paused"]:
        return pm["rem"]
    return max(0, pm["rem"] - (time.monotonic() - pm.get("t", time.monotonic())))


def cat_awake(cat):
    """Почему кот бежит: [(что, подпись)] — пусто, значит спит."""
    why = []
    if not cat:
        return why
    if cat.get("busy"):
        why.append(("busy", "Терминал занят"))
    p = cat.get("p")
    if p is not None and p.status == "Playing":
        why.append(("music", "Играет музыка"))
    pm = cat.get("pomo")
    if pm and not pm["paused"] and pm["phase"] == "work":
        why.append(("pomo", "Помидор: " + mmss(pomo_rem(pm))))
    if time.monotonic() - cat.get("pet_t", -99) < 2.0:
        why.append(("pet", "Мурчит"))
    return why


def draw_cat(cr, x, y, k, cat, ink, a=1.0, t=None):
    """Кот 20×12 рисунка по k px: бежит, если есть дело, иначе спит буханкой (вдох-выдох,
    поднимается «z»); погладили — сердечко и бег пару секунд."""
    t = time.monotonic() if t is None else t
    if cat_awake(cat):
        draw_bitmap(cr, CAT_RUN[int(t / CAT_FRAME_S) % len(CAT_RUN)], x, y, k, ink, a)
    else:
        tick = int(t / CAT_NAP_S)
        draw_bitmap(cr, CAT_NAP[tick % 2], x, y, k, ink, a)
        step = tick % 4                      # «z» над спиной: шаг в такт, каждый четвёртый — нет
        if step < 3:
            draw_bitmap(cr, CAT_ZZ, x + (8 + step) * k, y + (4 - 2 * step) * k - 3 * k, max(1, k // 2), ink, 0.7 * a)
    pt = time.monotonic() - (cat or {}).get("pet_t", -99)
    if pt < 1.6:
        draw_bitmap(cr, CAT_HEART, x + 15 * k, y - k - int(pt / 0.2) % 4 * k, k, (1.0, 0.42, 0.55), a)


def lyric_now(cat):
    """Строка песни сейчас: (текст, пропето знаков, следующая) или None (текста нет/проигрыш)."""
    lines, p = (cat or {}).get("lines"), (cat or {}).get("p")
    if not lines or p is None:
        return None
    try:
        import lyrics_bar as LB
        pos = p.position() + LB.LEAD
        i = LB.line_index(lines, pos)
        nxt = lines[i + 1][1] if 0 <= i + 1 < len(lines) else ""
        if i < 0 or not lines[i][1]:
            return ("", 0, nxt)
        start, dur, _end = LB.line_timing(lines, i, p.length)
        return (lines[i][1], LB.sung_chars(lines[i][1], max(0.0, pos - start), dur), nxt)
    except Exception:
        return None


def cat_right(cat):
    """Правая часть капсулы: music (обложка + квадратики), pomo, busy, date."""
    if not cat:
        return "date"
    if cat.get("p") is not None:
        return "music"
    pm = cat.get("pomo")
    if pm:
        return "pomo"
    return "busy" if cat.get("busy") else "date"


def cat_parts(cr, cat, D=None):
    """[(вид, ширина)] капсулы котика слева направо."""
    use_font(D)
    parts = [("clock", text_w(cr, time.strftime("%H:%M"), 8))]
    parts.append(("lyr", CAT_LYR_W) if (cat or {}).get("lines") else ("cat", CAT_W))
    r = cat_right(cat)
    if r == "music":
        parts.append(("music", CAT_COVER + 5 + CAT_EQ_N * (CAT_EQ_BLK + 1) - 1))
    elif r == "pomo":
        parts.append(("pomo", 7 + 4 + text_w(cr, mmss(pomo_rem(cat["pomo"])), 8)))
    elif r == "busy":
        parts.append(("busy", 7))
    else:
        parts.append(("date", text_w(cr, cat_date(), 8)))
    return parts


WEEKDAYS = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
MONTHS = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def cat_date():
    lt = time.localtime()
    return "%s %d" % (WEEKDAYS[lt.tm_wday], lt.tm_mday)


def cat_w(cr, cat, D=None):
    ps = cat_parts(cr, cat, D)
    w = max(CAT_MIN_W, 2 * CAT_PAD + sum(pw for _k, pw in ps) + CAT_GAP * (len(ps) - 1))
    return float(int(math.ceil(w / 2.0)) * 2)


def draw_eq(cr, x, y, n, rows, blk, levels, col, a, playing):
    """Квадратики эквалайзера снизу вверх; цвет — от акцента у основания к третичному сверху."""
    for i in range(n):
        v = levels[i] if i < len(levels) else 0
        lit = max(1, int(round(v * rows))) if playing else 1
        for r in range(rows):
            by = y + (rows - 1 - r) * (blk + 1)
            cr.rectangle(x + i * (blk + 1), by, blk, blk)
            if r < lit:
                c = mix_rgb(col["primary"], col["tertiary"], r / max(1, rows - 1)) if playing else col["on_surface_variant"]
                cr.set_source_rgba(*c, a)
            else:
                cr.set_source_rgba(*col["on_surface_variant"], 0.16 * a)
            cr.fill()


def mix_rgb(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def draw_cover(cr, x, y, size, cat, col, a):
    """Обложка квадратом, крупными пикселями (8×8 → size, без сглаживания, как у angelOS);
    нет обложки — плашка цвета акцента с нотой."""
    import cairo
    sf = (cat or {}).get("art8" if size <= 24 else "art24")
    if sf is None:
        cr.rectangle(x, y, size, size)
        cr.set_source_rgba(*mix_rgb(col["bg"], col["primary"], 0.35), a)
        cr.fill()
        return
    k = size / sf.get_width()
    cr.save()
    cr.rectangle(x, y, size, size)
    cr.clip()
    cr.translate(x, y)
    cr.scale(k, k)
    cr.set_source_surface(sf, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint_with_alpha(a)
    cr.restore()


def draw_lyric(cr, x, cy, lane, ly, col, a, px=8, center=False):
    """Строка песни в полосе lane: пропетое — акцентом, остальное тускло; длинная едет за
    подсветкой. Проигрыш — «♪ ♪ ♪»."""
    text, done, _nxt = ly
    if not text:
        put_text(cr, "♪  ♪  ♪", px, x + lane / 2, cy, col["on_surface_variant"], 0.7 * a, center=True)
        return
    tw = text_w(cr, text, px)
    sw = text_w(cr, text[:done], px) if done else 0
    off = 0 if tw <= lane else max(0.0, min(tw - lane, sw - lane * 0.6))
    x0 = x + (lane - tw) / 2 if (center and tw <= lane) else x - off
    cr.save()
    cr.rectangle(x, cy - 12, lane, 24)
    cr.clip()
    put_text(cr, text, px, x0, cy, col["on_surface"], 0.45 * a)
    if done:
        put_text(cr, text[:done], px, x0, cy, col["primary"], a)
    cr.restore()


def paint_cat_pill(cr, x, top, w, h, st, col, D):
    """Капсула «Котик»: часы | кот (или строка песни) | обложка с квадратиками / помидор /
    занятый терминал / дата. Целиком видна, без «тусклости» нити."""
    import cairo
    hits = []
    if st.get("ta", 1) <= 0.01 or w < 4 or h < 2:
        return hits
    cat = st.get("cat")
    ios = bool(D.get("ios"))
    cr.save()
    cr.set_antialias(cairo.ANTIALIAS_GOOD if ios else cairo.ANTIALIAS_NONE)
    r = h / 2 if ios else 0
    cr.new_path()
    if r:
        cr.arc(x + w - r, top + r, r, -math.pi / 2, math.pi / 2)
        cr.arc(x + r, top + r, r, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()
    else:
        cr.rectangle(x, top, w, h)
    if ios:
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.92)
    else:
        cr.set_source_rgba(*fill_rgba(D, col)[:3], 0.94)
    cr.fill_preserve()
    cr.set_line_width(1 if ios else 2)
    if ios:
        cr.set_source_rgba(1, 1, 1, 0.08)
    else:
        cr.set_source_rgba(*border_rgba(D, col)[:3], 0.9) if D.get("border") else cr.set_source_rgba(1, 1, 1, 0.1)
    cr.stroke()
    parts = cat_parts(cr, cat, D)
    need = 2 * CAT_PAD + sum(pw for _k, pw in parts) + CAT_GAP * (len(parts) - 1)
    need = max(CAT_MIN_W, need)
    if w >= need * 0.9 and h >= PILL_H * 0.6:      # пока капсула растёт — пусто
        cr.rectangle(x, top, w, h)
        cr.clip()
        ink = (1, 1, 1) if ios else col["on_surface"]
        dim = (0.75, 0.75, 0.78) if ios else col["on_surface_variant"]
        cy = top + h / 2
        # края: первое — у левого края, последнее — у правого, середина — по центру
        n = len(parts)
        xs, cx = [], x + CAT_PAD
        for i, (k, pw) in enumerate(parts):
            if i == n - 1 and n > 1:
                cx = x + w - CAT_PAD - pw
            elif 0 < i < n - 1:
                cx = x + (w - pw) / 2
            xs.append(cx)
            cx += pw + CAT_GAP
        for (k, pw), cx in zip(parts, xs):
            cx = float(int(cx))
            if k == "clock":
                put_text(cr, time.strftime("%H:%M"), 8, cx, cy, ink, 0.95)
            elif k == "cat":
                draw_cat(cr, int(cx), int(cy - CAT_H / 2), 1, cat, ink)
            elif k == "lyr":
                ly = lyric_now(cat)
                if ly is None or not ly[0]:          # проигрыш: кот бежит посреди полосы
                    draw_cat(cr, int(cx + (pw - CAT_W) / 2), int(cy - CAT_H / 2), 1, cat, ink)
                else:
                    draw_lyric(cr, cx, cy, pw, ly, dict(col, on_surface=ink), 1.0, center=True)
            elif k == "music":
                p = cat["p"]
                draw_cover(cr, int(cx), int(cy - CAT_COVER / 2), CAT_COVER, cat, col, 1.0)
                eh = CAT_EQ_ROWS * (CAT_EQ_BLK + 1) - 1
                draw_eq(cr, int(cx + CAT_COVER + 5), int(cy - eh / 2), CAT_EQ_N, CAT_EQ_ROWS, CAT_EQ_BLK,
                        cat.get("eq") or (), col, 1.0, p.status == "Playing")
            elif k == "pomo":
                pm = cat["pomo"]
                draw_bitmap(cr, CAT_TOMATO, int(cx), int(cy - 3.5), 1, act_color("pomo", col))
                put_text(cr, mmss(pomo_rem(pm)), 8, cx + 11, cy, dim if pm["paused"] else ink, 0.95)
            elif k == "busy":
                draw_bitmap(cr, CAT_BUSY, int(cx), int(cy - 3.5), 1, BUSY_ORANGE)
            elif k == "date":
                put_text(cr, cat_date(), 8, cx, cy, dim, 0.9)
    cr.restore()
    return hits


def paint_cat_card(cr, x, w, h, cat, col, a, hits, ios):
    """Страница «Котик» в раскрытом островке: слева часы, дата и сколько кот набегал за день;
    посередине кот крупно (щелчок — погладить) или строки песни; под ним — почему бежит
    (щелчок ведёт к делу: окно терминала, страница музыки или помидора); справа обложка и
    эквалайзер (щелчок по обложке — пауза)."""
    cat = cat or {}
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    # слева: время
    put_text(cr, time.strftime("%H:%M"), 24, x + pad, 40, fg, a)
    lt = time.localtime()
    put_text(cr, "%s, %d %s" % (WEEKDAYS[lt.tm_wday], lt.tm_mday, MONTHS[lt.tm_mon - 1]), 8, x + pad, 66, dim, a)
    ran = int(cat.get("ran", 0))
    put_text(cr, "набегал %d:%02d" % (ran // 3600, ran // 60 % 60), 8, x + pad, 84, dim, 0.8 * a)
    pets = cat.get("pets", 0)
    if pets:
        put_text(cr, "погладили %d" % pets, 8, x + pad, 100, dim, 0.8 * a)
    # справа: обложка и квадратики
    p = cat.get("p")
    rx = x + w - pad - 48
    if p is not None:
        draw_cover(cr, int(rx), 26, 48, cat, col, a)
        hits.append(((rx, 26, 48, 48), ("music", "PlayPause")))
        draw_eq(cr, int(rx), 82, 8, 4, 5, cat.get("eq8") or (), col, a, p.status == "Playing")
    else:
        pm = cat.get("pomo")
        if pm:
            draw_bitmap(cr, CAT_TOMATO, int(rx + 10), 26, 4, act_color("pomo", col), a)
            put_text(cr, mmss(pomo_rem(pm)), 8, rx + 24, 70, fg, a, center=True)
        elif cat.get("busy"):
            draw_bitmap(cr, CAT_BUSY, int(rx + 10), 26, 4, BUSY_ORANGE, a)
    # посередине: строки песни или кот
    lx, lw = x + 128, w - 128 - 48 - pad - 14
    ly = lyric_now(cat) if cat.get("lines") else None
    if ly and ly[0]:
        draw_lyric(cr, lx, 40, lw, ly, dict(col, on_surface=fg), a, px=8, center=True)
        if ly[2]:
            put_text(cr, ly[2], 8, lx + lw / 2, 58, dim, 0.55 * a, maxw=lw, center=True)
        k, cyy = 2, 70
    else:
        k, cyy = 3, 26
    cw = CAT_W * k
    cxx = int(lx + (lw - cw) / 2)
    draw_cat(cr, cxx, cyy, k, cat, fg, a)
    hits.append(((cxx - 6, cyy - 8, cw + 12, CAT_H * k + 12), ("cat", "pet")))
    why = cat_awake(cat)
    txt = " · ".join(t for _k, t in why) if why else "Спит. Погладьте"
    put_text(cr, txt, 8, lx + lw / 2, h - 16, dim, 0.85 * a, maxw=lw, center=True)
    if why and why[0][0] in ("busy", "music", "pomo"):
        hits.append(((lx, h - 26, lw, 20), ("cat", why[0][0])))


CAT_STATS = os.path.expanduser("~/.config/hypr/state/island-cat.json")
CAT_COVERS = os.path.expanduser("~/.cache/player-covers")
BUSY_MARKS = set("◐◓◑◒⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏")   # так консольные программы крутят заголовок окна, пока работают
CAT_CAVA = """[general]
framerate = 20
autosens = 1
bars = 8
lower_cutoff_freq = 40
higher_cutoff_freq = 8000
[input]
method = pipewire
source = auto
[output]
method = raw
channels = mono
raw_target = /dev/stdout
data_format = ascii
ascii_max_range = 1000
bar_delimiter = 59
frame_delimiter = 10
"""


def cat_page_on(conf, isl):
    """Кот виден на этом островке: капсула «Котик» или открыта его страница."""
    if isl.mode == "thread" and isl.geo[0] > 4:
        return eff_style(conf["thread_style"], isl.app.acts) == "cat"
    if isl.mode == "card" and isl.app.pages:
        return isl.app.pages[isl.card_i % len(isl.app.pages)][0] == "cat"
    return False


def eff_style(style, acts):
    """Кот уступает капсулу звонку, записи и таймеру: им нужны свои цифры и кнопки."""
    if style == "cat" and acts and acts[0][0] in ("call", "rec", "timer"):
        return "pill"
    return style


class CatWatch:
    """Чем жив кот: занятый терминал (заголовок окна со спиннером), музыка,
    помидор; обложка, строки песни, эквалайзер cava. Опрос раз в 2 с — только пока кот
    нужен (капсула «Котик» или его страница); кадры и cava — только пока его видно."""

    def __init__(self, app):
        self.app, self.GLib = app, app.GLib
        self.s = {"busy": False, "p": None, "pomo": None, "lines": None, "art8": None, "art24": None,
                  "eq": [], "eq8": [], "pet_t": -99.0, "ran": 0, "pets": 0}
        self.titles = {}             # id окна niri → заголовок
        self.poll_id = self.anim_id = None
        self.key = self.art_url = None
        self.cava = None
        self.no_cava = False
        self.cava_buf = b""
        self.cava_off = 0.0
        self.last = time.monotonic()
        self.saved = 0.0
        self.day = time.strftime("%Y-%m-%d")
        try:
            d = json.load(open(CAT_STATS))
            if d.get("day") == self.day:
                self.s["ran"], self.s["pets"] = int(d.get("ran", 0)), int(d.get("pets", 0))
        except (OSError, ValueError):
            pass

    def wanted(self):
        c = self.app.conf
        return c["on"] and (c["thread_style"] == "cat" or "cat" in page_ids(c))

    def sync(self):
        """Из refresh: опрос включается/выключается по настройкам, кадры — по виду."""
        if self.wanted() and self.poll_id is None:
            self.poll()
            self.poll_id = self.GLib.timeout_add(2000, self.poll)
        self.kick()

    # — источники —
    def on_window(self, ev):
        if "WindowsChanged" in ev:
            self.titles = {w["id"]: w.get("title") or "" for w in ev["WindowsChanged"]["windows"]}
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            self.titles[w["id"]] = w.get("title") or ""
        elif "WindowClosed" in ev:
            self.titles.pop(ev["WindowClosed"]["id"], None)
        else:
            return
        busy = self.title_busy()
        if busy != self.s["busy"]:
            self.s["busy"] = busy
            self.kick()

    def busy_window(self):
        for wid, t in self.titles.items():
            if t[:1] in BUSY_MARKS:
                return wid
        return None

    def title_busy(self):
        return any(t[:1] in BUSY_MARKS for t in self.titles.values())

    def poll(self):
        if not self.wanted():
            self.poll_id = None
            self.stop_cava()
            return False
        s = self.s
        now = time.monotonic()
        s["busy"] = self.title_busy()
        p = self.app.music.current() if self.app.music else None
        s["p"] = p
        pm = read_pomo()
        if pm:
            pm["t"] = now
        s["pomo"] = pm
        self.track(p)
        if cat_awake(s):                     # «набегал за день»
            s["ran"] += min(5.0, now - self.last)
        self.last = now
        day = time.strftime("%Y-%m-%d")
        if day != self.day:
            self.day, s["ran"], s["pets"] = day, 0, 0
        if now - self.saved > 60:
            self.save()
        self.kick()
        return True

    def save(self):
        self.saved = time.monotonic()
        try:
            tmp = CAT_STATS + ".tmp"
            with open(tmp, "w") as f:
                json.dump({"day": self.day, "ran": int(self.s["ran"]), "pets": self.s["pets"]}, f)
            os.replace(tmp, CAT_STATS)
        except OSError as e:
            log("кот: статистика", e)

    def track(self, p):
        """Новый трек: строки песни (кэш lyrics_bar, иначе сами спросим через 6 с) и обложка."""
        import threading
        url = str(p.meta.get("mpris:artUrl") or "") if p is not None else ""
        if url != self.art_url:
            self.art_url = url
            self.s["art8"] = self.s["art24"] = None
            if url:
                threading.Thread(target=self.load_art, args=(url,), daemon=True).start()
        key = p.track_key() if p is not None and p.is_song() else None
        if key == self.key:
            return
        self.key = key
        self.s["lines"] = None
        if key:
            threading.Thread(target=self.load_lyrics, args=(key, p.album), daemon=True).start()

    def load_lyrics(self, key, album):
        try:
            import lyrics_bar as LB
            d = LB.cached_lyrics(*key)
            if d is None:                    # строку бара, может, уже ищет lyrics_bar — подождать
                time.sleep(6)
                if key != self.key:
                    return
                d = LB.cached_lyrics(*key) or LB.store_lyrics(*key, LB.fetch_lyrics(key[0], key[1], key[2], album))
            lines = LB.lines_of(d, key[2]) if d else []
        except Exception as e:
            log("кот: текст", e)
            lines = []
        self.GLib.idle_add(lambda: self.set_lines(key, lines) and False)

    def set_lines(self, key, lines):
        if key == self.key:
            self.s["lines"] = lines or None
            self.app.redraw_cat(resize=True)

    def load_art(self, url):
        """Обложка → два маленьких PNG: 8×8 (капсула, крупные пиксели) и 24×24 (страница)."""
        import hashlib
        try:
            if url.startswith("file://"):
                import urllib.parse
                path = urllib.parse.unquote(url[7:])
            else:
                os.makedirs(CAT_COVERS, exist_ok=True)
                path = os.path.join(CAT_COVERS, hashlib.sha1(url.encode()).hexdigest())
                if not os.path.exists(path):
                    import urllib.request
                    with urllib.request.urlopen(url, timeout=6) as r, open(path + ".tmp", "wb") as f:
                        f.write(r.read(4 << 20))
                    os.replace(path + ".tmp", path)
            from PIL import Image
            im = Image.open(path).convert("RGB")
            w, h = im.size
            side = min(w, h)
            im = im.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side))
            out = []
            for n in (8, 24):
                dst = os.path.join(RUN, "jarvis-island-cover%d.png" % n)
                im.resize((n, n), Image.BOX).save(dst)
                out.append(dst)
        except Exception as e:
            log("кот: обложка", e)
            return
        self.GLib.idle_add(lambda: self.set_art(url, out) and False)

    def set_art(self, url, files):
        import cairo
        if url != self.art_url:
            return
        try:
            self.s["art8"], self.s["art24"] = (cairo.ImageSurface.create_from_png(f) for f in files)
        except Exception as e:
            log("кот: обложка", e)
        self.app.redraw_cat()

    # — кадры и эквалайзер —
    def visible(self):
        return [isl for isl in self.app.wins.values() if cat_page_on(self.app.conf, isl)]

    def kick(self):
        if self.anim_id is None and self.visible():
            self.anim_id = self.GLib.timeout_add(CAT_FRAME_MS, self.frame)

    def frame(self):
        vis = self.visible()
        p = self.s["p"]
        playing = bool(vis) and p is not None and p.status == "Playing"
        if playing:
            self.start_cava()
            self.cava_off = 0.0
        elif self.cava and not self.cava_off:
            self.cava_off = time.monotonic()
        if self.cava and self.cava_off and time.monotonic() - self.cava_off > 3:
            self.stop_cava()
        if not vis:
            self.anim_id = None
            return False
        for isl in vis:
            isl.draw_cat()
        fast = cat_awake(self.s) or self.s["lines"] or playing
        self.anim_id = self.GLib.timeout_add(CAT_FRAME_MS if fast else 1000, self.frame)
        return False

    def start_cava(self):
        if self.cava or self.no_cava:
            return
        conf = os.path.join(RUN, "jarvis-island-cava.conf")
        try:
            with open(conf, "w") as f:
                f.write(CAT_CAVA)
            self.cava = subprocess.Popen(["cava", "-p", conf], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                         stdin=subprocess.DEVNULL, preexec_fn=pdeathsig)
        except OSError as e:
            log("кот: cava", e)
            self.no_cava = True          # нет cava — квадратики стоят, не пытаться каждый кадр
            return
        os.set_blocking(self.cava.stdout.fileno(), False)
        self.cava_buf = b""
        self.cava_watch = self.GLib.io_add_watch(self.cava.stdout.fileno(), self.GLib.PRIORITY_DEFAULT,
                                                 self.GLib.IO_IN | self.GLib.IO_HUP, self.read_cava)

    def read_cava(self, _fd, cond):
        try:
            data = os.read(self.cava.stdout.fileno(), 65536)
        except BlockingIOError:
            return True
        except (OSError, AttributeError):
            data = b""
        if not data:
            self.stop_cava(watch=False)
            return False
        self.cava_buf += data
        *lines, self.cava_buf = self.cava_buf.split(b"\n")
        for line in lines[-1:]:
            v = [int(x) / 1000.0 for x in line.strip().strip(b";").split(b";") if x.isdigit()]
            if len(v) >= 8:
                self.s["eq8"] = v[:8]
                self.s["eq"] = [max(v[i], v[i + 1]) for i in range(0, 8, 2)]
        return True

    def stop_cava(self, watch=True):
        c, self.cava = self.cava, None
        self.cava_off = 0.0
        self.s["eq"] = self.s["eq8"] = []
        if not c:
            return
        if watch:
            try:
                self.GLib.source_remove(self.cava_watch)
            except Exception:
                pass
        c.terminate()
        try:
            c.wait(timeout=1)
        except subprocess.TimeoutExpired:
            c.kill()
        c.stdout.close()

    # — действия —
    def pet(self):
        self.s["pet_t"] = time.monotonic()
        self.s["pets"] += 1
        self.save()
        self.kick()

    def focus_busy(self):
        wid = self.busy_window()
        if wid is not None:
            subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(wid)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def running_pid():
    try:
        pid = int(_read(LOCK, "0") or 0)
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
    except (OSError, ValueError):
        return None
    return pid if any(x.endswith(b"island.py") for x in argv) else None


def niri_json(*what):
    try:
        out = subprocess.run(["niri", "msg", "-j", *what], capture_output=True, text=True, timeout=1.5).stdout
        return json.loads(out) if out.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def pdeathsig():
    import ctypes
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)


class Island:
    """Одна поверхность на монитор; общее состояние — у App."""

    def __init__(self, app, monitor, output):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import Gdk, Gtk, GtkLayerShell
        self.app, self.output = app, output
        self.mode = "none"
        self.geo = (0.0, 0.0)            # текущие w, h
        self.anim = None                 # {from, to, t0, back}
        self.alpha = 0.0
        self.hits = []
        self.leave_t = None
        self.open_t = None
        self.hovered = False
        self.opened_by_hover = False
        self.card_i = 0
        self.off = 0                     # отступ поверхности от края (бар «при наведении»)
        self.press = None                # (x, y, действие) — нажатие на снимок буфера
        self.dragging = False
        self.ptr = (-1, -1)
        w = self.win = Gtk.Window()
        w.set_title(NAMESPACE)
        w.set_app_paintable(True)
        vis = w.get_screen().get_rgba_visual()
        if vis:
            w.set_visual(vis)
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, NAMESPACE)
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(w, monitor)
        GtkLayerShell.set_anchor(w, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_exclusive_zone(w, 0)
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        self.place()
        w.set_size_request(CW, CH)
        w.set_default_size(CW, CH)
        w.set_resizable(False)
        w.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK |
                     Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK |
                     Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.SCROLL_MASK)
        w.connect("draw", self.on_draw)
        w.connect("button-press-event", self.on_click)
        w.connect("button-release-event", self.on_release)
        w.connect("motion-notify-event", self.on_motion)
        w.connect("drag-begin", self.on_drag_begin)
        w.connect("drag-data-get", self.on_drag_get)
        w.connect("drag-end", self.on_drag_end)
        w.connect("scroll-event", self.on_scroll)
        w.connect("enter-notify-event", self.on_enter)
        w.connect("leave-notify-event", self.on_leave)
        w.connect("realize", lambda *_: self.set_input())

    def place(self):
        from gi.repository import GtkLayerShell
        self.off = hover_offset(self.output)
        GtkLayerShell.set_margin(self.win, GtkLayerShell.Edge.TOP, self.off)

    def ty(self):
        c = self.app.conf
        return thread_y(c["thread_style"], self.off, self.app.th, c["overlay"])

    def design(self):
        try:
            import system_style
            style = system_style.style_of(self.output)
        except Exception:
            style = "default"
        return design(self.app.conf["design"], style)

    def target(self, mode):
        if mode == "none":
            return (0.0, 0.0)
        if mode == "thread":
            style = eff_style(self.app.conf["thread_style"], self.app.acts)
            if style in PILLS:
                import cairo
                cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
                if style == "cat":
                    return (cat_w(cr, self.app.cat.s, self.design()), float(PILL_H))
                return (pill_w(cr, self.app.acts, self.app.col), float(PILL_H))
            return thread_size(self.app.conf["thread_style"])
        if mode == "compact":
            acts = self.app.ordered(0)          # и одна вспышка без дел (flash) — компакт
            if not acts:
                return (0.0, 0.0)
            import cairo
            cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
            k, d = acts[0]
            return (float(compact_w(cr, k, d, len(acts) - 1, self.design())), float(COMPACT_H))
        pages = self.app.pages
        if not pages:
            return (0.0, 0.0)
        return (float(CARD_W), float(CARD_HK.get(pages[self.card_i % len(pages)][0], CARD_H)))

    def go(self, mode):
        to = self.target(mode)
        if mode == self.mode and (self.anim is None and self.geo == to):
            self.win.queue_draw()
            return
        grow = to[1] > self.geo[1] or to[0] > self.geo[0]
        keep = self.mode == mode == "card"      # смена страницы: меняется только высота, текст не гаснет
        self.mode = mode
        self.anim = {"from": self.geo, "to": to, "t0": None, "back": grow and mode != "thread" and not keep,
                     "keep": keep}
        if to != (0.0, 0.0) and not self.win.get_visible():
            self.win.show_all()
        self.win.add_tick_callback(self.tick)
        self.win.queue_draw()
        self.app.cat.kick()

    def draw_cat(self):
        """Кадр кота: в нити — только полоса капсулы, в карточке — вся карточка."""
        if self.anim is not None:
            return
        if self.mode == "thread":
            w, h = self.geo
            self.win.queue_draw_area(int((CW - w) / 2) - 4, 0, int(w) + 8, self.ty() + int(h) + 4)
        else:
            self.win.queue_draw()

    def tick(self, _w, clock):
        a = self.anim
        if a is None:
            return False
        now = clock.get_frame_time() / 1000.0
        if a["t0"] is None:
            a["t0"] = now
        t = min(1.0, (now - a["t0"]) / ANIM_MS)
        e = ease_back(t, 1.1) if a["back"] else ease_out(t)
        f, to = a["from"], a["to"]
        self.geo = (f[0] + (to[0] - f[0]) * e, f[1] + (to[1] - f[1]) * e)
        # содержимое проявляется во второй половине раскрытия
        self.alpha = 1.0 if self.mode != "none" and t >= 1 else max(0.0, (t - 0.45) / 0.55) \
            if self.mode != "none" else 0.0
        if a.get("keep"):
            self.alpha = 1.0
        self.set_input()
        self.win.queue_draw()
        if t >= 1.0:
            self.anim = None
            self.geo = to
            self.alpha = 1.0 if self.mode != "none" else 0.0
            self.set_input()
            if self.mode == "none":
                self.win.hide()
            return False
        return True

    def set_input(self):
        import cairo
        gw = self.win.get_window()
        if gw is None:
            return
        w, h = self.geo
        x = int((CW - w) / 2)
        ty = self.ty()
        y = int(top_of(self.design(), h, ty))
        if w < 2 or h < 1:
            r = cairo.Region()
        elif self.mode == "thread" and self.app.conf["thread_style"] in PILLS:
            r = cairo.Region(cairo.RectangleInt(x - 6, 0, int(w) + 12, ty + int(h) + 4))
        elif self.mode == "thread" and h <= THREAD_H + 2:   # в 3-px линию не попасть — зона шире
            r = cairo.Region(cairo.RectangleInt(x - HOVER_PAD, 0, int(w) + 2 * HOVER_PAD, y + int(h) + 8))
        else:
            r = cairo.Region(cairo.RectangleInt(x, y, int(math.ceil(w)), int(math.ceil(h))))
        gw.input_shape_combine_region(r, 0, 0)

    def on_draw(self, _w, cr):
        font_opts(cr)
        st = {"w": self.geo[0], "h": self.geo[1], "mode": self.mode, "alpha": self.alpha,
              "acts": self.app.ordered(0), "th": self.app.th, "ty": self.ty(),
              "pages": self.app.pages, "card_i": self.card_i, "style": self.app.conf["thread_style"],
              "ta": self.thread_alpha(), "cat": self.app.cat.s}
        self.hits = paint(cr, st, self.app.col, self.design())
        return True

    def thread_alpha(self):
        """Тусклая нить; при видео в фокусе не видна, пока на неё не навели."""
        a = max(0.1, min(0.9, float(self.app.conf["thread_alpha"])))
        if self.app.video and self.app.conf["video_hide"] and not self.hovered:
            return 0.0
        return a

    def hit_at(self, x, y):
        for (hx, hy, hw, hh), act in self.hits:
            if hx <= x <= hx + hw and hy <= y <= hy + hh:
                return act
        return None

    def open_card(self):
        """Раскрыть на странице, где остановились (19.10.2026, просьба: «запоминать последнюю
        страницу»); звонок важнее — сразу на него. Нет такой страницы — главное дело, иначе первая."""
        acts = self.app.acts
        pages = self.app.pages
        keys = [page_key(p) for p in pages]
        if acts and acts[0][0] == "call":
            self.card_i = keys.index(page_key(acts[0]))
        elif self.app.last in keys:
            self.card_i = keys.index(self.app.last)
        else:
            self.card_i = next((i for i, p in enumerate(pages) if acts and p[0] == acts[0][0]), 0)
        self.app.pop_until = 0
        if "clip" in page_ids(self.app.conf):   # снимки грузятся заранее, пока карточка раскрывается
            self.app.load_clip()
        self.go("card")

    def on_click(self, _w, e):
        kind = self.app.acts[0][0] if self.app.acts else None
        if e.button == 3:
            self.app.pop_until = 0
            self.go("thread" if self.app.want_thread(self.output) else "none")
            return True
        if e.button == 2 and kind:
            self.app.primary_action(kind)
            return True
        if e.button != 1:
            return True
        act = self.hit_at(e.x, e.y)
        if self.mode in ("thread", "compact") and act is None:
            self.open_card()
            return True
        if act is None:
            return True
        if act[0] == "page":
            self.card_i = act[1]
            self.app.on_page(self.app.pages[self.card_i][0], self.app.pages[self.card_i])
            self.go("card")
        elif act[0] == "cat" and act[1] in ("music", "pomo"):   # «почему бежит» → к делу
            i = next((i for i, p in enumerate(self.app.pages) if p[0] == act[1]), None)
            if i is not None:
                self.card_i = i
                self.app.on_page(act[1], self.app.pages[i])
                self.go("card")
        elif act[0] == "clip":                  # щелчок или перетаскивание — решит отпускание
            self.press = (e.x, e.y, act)
            self.app.clip_prepare(act[1])
        else:
            self.app.do(act, self.card_i)
        return True

    def on_release(self, _w, e):
        p, self.press = self.press, None
        if p and not self.dragging and e.button == 1:
            self.app.do(p[2])
        return True

    def on_motion(self, _w, e):
        self.ptr = (e.x, e.y)
        p = self.press
        if not p or self.dragging:
            return False
        from gi.repository import Gdk, Gtk
        # метод виджета: Gtk.drag_check_threshold в PyGObject нет — до 19.10.2026 здесь каждое
        # движение падало с AttributeError (stderr — /dev/null), и снимок не перетаскивался
        if not self.win.drag_check_threshold(int(p[0]), int(p[1]), int(e.x), int(e.y)):
            return False
        path = self.app.clip_path(p[2][1])
        if not path:
            return False
        self.drag_path = path
        self.dragging = True
        tl = Gtk.TargetList.new([])
        tl.add_uri_targets(0)
        self.win.drag_begin_with_coordinates(tl, Gdk.DragAction.COPY, 1, e, int(e.x), int(e.y))
        return True

    def on_drag_begin(self, _w, ctx):
        """Под курсором — уменьшенный снимок."""
        from gi.repository import Gtk
        it = self.app.clip_item(self.press[2][1]) if self.press else None
        pb = it.get("pb") if it else None
        if pb is not None:
            Gtk.drag_set_icon_pixbuf(ctx, pb, pb.get_width() // 2, pb.get_height() // 2)

    def on_drag_get(self, _w, _ctx, sel, _info, _time):
        sel.set_uris(["file://" + self.drag_path])

    def on_drag_end(self, *_a):
        from gi.repository import GLib
        self.dragging = False
        self.press = None
        if not self.hovered and self.mode == "card":
            if self.leave_t:
                GLib.source_remove(self.leave_t)
            self.leave_t = GLib.timeout_add(LEAVE_MS, self.collapse)

    def on_scroll(self, _w, e):
        """Колесо листает страницы; над нитью/компактом — раскрывает карточку."""
        from gi.repository import Gdk
        n = len(self.app.pages)
        if not n:
            return True
        if e.direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = e.get_scroll_deltas()
            step = 1 if dy > 0 else -1 if dy < 0 else 0
        else:
            step = 1 if e.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT) else -1
        if not step:
            return True
        if self.mode != "card":
            self.open_card()
            return True
        now = time.monotonic()
        if now - getattr(self, "scroll_t", 0) < 0.25:   # тачпад шлёт пачку — одна страница за жест
            return True
        self.scroll_t = now
        self.card_i = (self.card_i + step) % n
        self.app.on_page(self.app.pages[self.card_i][0], self.app.pages[self.card_i])
        self.go("card")
        return True

    def on_enter(self, _w, e):
        """Наведение раскрывает (19.10.2026, просьба: «в маленькую линию сложно кликнуть»).
        Спрятанная при видео нить сперва проявляется, потом островок раскрывается."""
        from gi.repository import GLib, Gdk
        if e.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.leave_t:
            GLib.source_remove(self.leave_t)
            self.leave_t = None
        hidden = self.thread_alpha() == 0.0
        self.hovered = True
        if self.mode in ("thread", "compact") and self.app.conf["hover"] and not self.open_t:
            if hidden:
                self.win.queue_draw()
            self.open_t = GLib.timeout_add(HOVER_MS + (260 if hidden else 0), self.hover_open)
        return False

    def hover_open(self):
        self.open_t = None
        if self.hit_at(*self.ptr):              # курсор на кнопке капсулы (микрофон) — не раскрывать
            return False
        if self.hovered and self.mode in ("thread", "compact") and self.app.pages:
            self.opened_by_hover = True
            self.open_card()
        return False

    def on_leave(self, _w, e):
        from gi.repository import GLib, Gdk
        if e.detail == Gdk.NotifyType.INFERIOR:
            return False
        self.hovered = False
        if self.open_t:
            GLib.source_remove(self.open_t)
            self.open_t = None
        if self.mode != "card":
            self.win.queue_draw()
            return False
        if self.leave_t:
            GLib.source_remove(self.leave_t)
        self.leave_t = GLib.timeout_add(LEAVE_MS if self.opened_by_hover else 2200, self.collapse)
        return False

    def collapse(self):
        self.leave_t = None
        if self.dragging:                       # снимок ещё тащат — карточку держать
            return False
        self.opened_by_hover = False
        if self.mode == "card":
            self.go("thread" if self.app.want_thread(self.output) else "none")
        return False


class App:
    def __init__(self):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("Gdk", "3.0")
        from gi.repository import Gdk, Gio, GLib, Gtk
        self.Gdk, self.Gio, self.GLib, self.Gtk = Gdk, Gio, GLib, Gtk
        self.conf = load_conf()
        self.th = thread_h()
        self.col = colors()
        self.acts = []
        self.pages = []              # страницы карточки (идущие дела + буфер, инструменты)
        self.calls = None            # CallWatch, если страница «Звонок» включена
        self.timers = []
        self.timer_poll = None
        self.clip = {"items": [], "loading": False}
        self.clip_t = 0.0
        self.bar_outs = set()        # мониторы с постоянным верхним waybar — без нити
        self.space_t = None
        self.sig = None              # (вид, фаза) главного дела — смена = событие
        self.pop_until = 0.0
        self.flash = None            # {"text","icon","until"}
        self.focus_out = None
        self.overview = False
        self.game = False
        self.video = False           # видео в окне в фокусе — нить прячется (video_hide)
        self.video_t = None
        self.wins = {}
        self.timer = None
        self.mons = []
        try:
            self.music = Music(lambda *a: (self.refresh(), self.check_video()))
        except Exception as e:
            log("mpris недоступен:", e)
            self.music = None
        self.cat = CatWatch(self)
        self.last = _read(LAST).strip()          # страница, на которой остановились
        self.monitors = []
        for path in (REC, os.path.dirname(POMO), os.path.dirname(CONF), os.path.expanduser("~/.cache/matugen"),
                     os.path.expanduser("~/.config/waybar/looks")):
            try:
                os.makedirs(path, exist_ok=True)
                m = Gio.File.new_for_path(path).monitor_directory(Gio.FileMonitorFlags.NONE, None)
                m.connect("changed", self.on_file)
                self.monitors.append(m)
            except Exception as e:
                log("monitor", path, e)
        self.open_sock()
        self.stream()
        disp = Gdk.Display.get_default()
        disp.connect("monitor-added", lambda *_: GLib.timeout_add(600, self.rebuild))
        disp.connect("monitor-removed", lambda *_: GLib.timeout_add(600, self.rebuild))
        GLib.timeout_add_seconds(4, self.check_game)
        self.clock_tick()
        self.sources()
        self.update_bars()
        self.rebuild()

    def sources(self):
        """Источники по включённым страницам: звонки (pactl) и таймеры hub (раз в 3 с)."""
        ids = page_ids(self.conf)
        if "call" in ids and self.calls is None and self.conf["on"]:
            try:
                self.calls = CallWatch(self.GLib, self.refresh)
            except Exception as e:
                log("CallWatch:", e)
        if "timer" in ids and self.timer_poll is None:
            self.poll_timers()
            self.timer_poll = self.GLib.timeout_add_seconds(3, self.poll_timers)

    def poll_timers(self):
        if "timer" not in page_ids(self.conf) or not self.conf["on"]:
            self.timer_poll = None
            if self.timers:
                self.timers = []
                self.refresh()
            return False
        t = read_timers()
        if [x["id"] for x in t] != [x["id"] for x in self.timers]:
            self.timers = t
            self.refresh()
        else:
            self.timers = t
        return True

    def update_bars(self):
        """Где верхний waybar стоит всегда (там нить не рисуется) — в потоке, ответ в цикл GTK."""
        import threading

        def run():
            always, _outs = bar_always()
            self.GLib.idle_add(lambda: self.set_bars(always) and False)
        threading.Thread(target=run, daemon=True).start()

    def set_bars(self, always):
        if always != self.bar_outs:
            self.bar_outs = always
            self.refresh()

    def clock_tick(self):
        """Часы в нити-капсуле: перерисовка ровно на смене минуты (один таймер в минуту)."""
        if self.conf["thread_style"] in PILLS:
            for isl in self.wins.values():
                if isl.mode == "thread":
                    isl.win.queue_draw()
        self.GLib.timeout_add(int((60 - time.time() % 60) * 1000) + 30, lambda: self.clock_tick() and False)
        return False

    # — мониторы —
    def rebuild(self):
        for isl in self.wins.values():
            isl.win.destroy()
        self.wins = {}
        outs = niri_json("outputs") or {}
        by_model = {(o.get("model") or ""): c for c, o in outs.items()}
        disp = self.Gdk.Display.get_default()
        for i in range(disp.get_n_monitors()):
            m = disp.get_monitor(i)
            c = by_model.get(m.get_model() or "") or (sorted(outs)[i] if i < len(outs) else "mon%d" % i)
            self.wins[c] = Island(self, m, c)
        log("мониторы:", ", ".join(self.wins))
        self.refresh()
        return False

    def targets(self):
        """На каких мониторах показывать."""
        m = self.conf["monitor"]
        if m == "all":
            return set(self.wins)
        if m in self.wins:
            return {m}
        f = self.focus_out if self.focus_out in self.wins else None
        return {f} if f else set(list(self.wins)[:1])

    # — события —
    def on_file(self, _m, f, _o, ev):
        p = f.get_path() or ""
        if p == CONF:
            self.conf = load_conf()
            self.sources()
        elif os.path.basename(p) in ("panels.json", "top-bar", "current.jsonc"):
            for isl in self.wins.values():          # бар «при наведении» включили/выключили
                isl.place()
            self.update_bars()
            if os.path.basename(p) != "current.jsonc" and not self.space_t:
                # зазор над окнами — только на мониторах без постоянного бара (один раз за пачку)
                self.space_t = self.GLib.timeout_add(800, self.resync_space)
        elif p.startswith(os.path.expanduser("~/.cache/matugen")):
            self.col = colors()
        self.GLib.idle_add(lambda: self.refresh() and False)

    def open_sock(self):
        try:
            os.unlink(SOCK)
        except OSError:
            pass
        s = self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.bind(SOCK)
        self.GLib.io_add_watch(s.fileno(), self.GLib.IO_IN, self.on_sock)

    def on_sock(self, *_a):
        try:
            d = json.loads(self.sock.recv(4096).decode())
        except (OSError, ValueError):
            return True
        if d.get("cmd") == "reload":
            self.conf = load_conf()
            self.col = colors()
            self.th = thread_h()
            self.sources()
            self.update_bars()
            for isl in self.wins.values():
                isl.place()
        elif d.get("text"):
            self.flash = {"text": str(d["text"]), "icon": str(d.get("icon") or ""),
                          "until": time.monotonic() + float(d.get("ttl") or self.conf["pop_sec"])}
            self.pop_until = self.flash["until"]
        self.refresh()
        return True

    def stream(self):
        """niri event-stream: монитор с фокусом и обзор. Упал — переподключиться."""
        try:
            self.proc = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, preexec_fn=pdeathsig)
        except OSError:
            self.GLib.timeout_add_seconds(3, lambda: self.stream() and False)
            return
        self.ws_out = {}
        ch = self.GLib.IOChannel.unix_new(self.proc.stdout.fileno())
        self.GLib.io_add_watch(ch, self.GLib.PRIORITY_DEFAULT, self.GLib.IO_IN | self.GLib.IO_HUP, self.on_event)

    def on_event(self, ch, cond):
        if cond & self.GLib.IO_HUP:
            self.GLib.timeout_add_seconds(2, lambda: self.stream() and False)
            return False
        line = self.proc.stdout.readline()
        if not line:
            self.GLib.timeout_add_seconds(2, lambda: self.stream() and False)
            return False
        try:
            ev = json.loads(line)
        except ValueError:
            return True
        before = (self.focus_out, self.overview)
        if "WindowsChanged" in ev or "WindowOpenedOrChanged" in ev or "WindowClosed" in ev:
            self.cat.on_window(ev)              # заголовок со спиннером — терминал занят
        if "WorkspacesChanged" in ev:
            for w in ev["WorkspacesChanged"]["workspaces"]:
                self.ws_out[w["id"]] = w.get("output")
                if w.get("is_focused"):
                    self.focus_out = w.get("output")
        elif "WorkspaceActivated" in ev:
            a = ev["WorkspaceActivated"]
            if a.get("focused"):
                self.focus_out = self.ws_out.get(a["id"], self.focus_out)
        elif "WindowFocusChanged" in ev or "WindowOpenedOrChanged" in ev:
            self.check_video()
        elif "OverviewOpenedOrClosed" in ev:
            self.overview = bool(ev["OverviewOpenedOrClosed"].get("is_open"))
        if (self.focus_out, self.overview) != before:
            self.refresh()
        return True

    def check_video(self, delay=400):
        """Видео в фокусе (как у idle_guard: плеер играет в окне в фокусе). Спрашивается в
        потоке и не чаще раза за delay мс — niri и playerctl не держат цикл GTK."""
        if self.video_t or not self.conf["video_hide"]:
            if not self.conf["video_hide"] and self.video:
                self.video = False
                self.redraw()
            return

        def ask():
            self.video_t = None
            import threading

            def run():
                try:
                    import idle_guard
                    v = idle_guard.video_in_focus() is not None
                except Exception as e:
                    log("video:", e)
                    v = False
                self.GLib.idle_add(lambda: self.set_video(v) and False)
            threading.Thread(target=run, daemon=True).start()
            return False
        self.video_t = self.GLib.timeout_add(delay, ask)

    def set_video(self, v):
        if v != self.video:
            self.video = v
            self.redraw()

    def redraw(self):
        for isl in self.wins.values():
            isl.win.queue_draw()

    def redraw_cat(self, resize=False):
        """Пришли строки песни или обложка: ширина капсулы могла измениться."""
        for isl in self.wins.values():
            if resize and isl.mode == "thread":
                isl.go("thread")
            elif cat_page_on(self.conf, isl):
                isl.win.queue_draw()

    def resync_space(self):
        self.space_t = None
        import threading
        threading.Thread(target=sync_space, args=(dict(self.conf),), daemon=True).start()
        return False

    def check_game(self):
        if not (self.acts or self.flash or self.want_thread()):
            return True
        try:
            import game_guard
            g = game_guard.running_app_id() is not None
        except Exception:
            g = False
        if g != self.game:
            self.game = g
            self.refresh()
        return True

    # — состояние —
    def ordered(self, i=0):
        acts = list(self.acts)
        if self.flash and time.monotonic() < self.flash["until"] and i == 0:
            acts.insert(0, ("flash", self.flash))
        if 0 < i < len(acts):
            acts.insert(0, acts.pop(i))
        return acts

    def want_thread(self, out=None):
        """Нить: включена, есть дело (или «нить всегда» и есть страницы) и над монитором нет
        постоянного верхнего бара."""
        if not self.conf["thread"] or out in self.bar_outs:
            return False
        return bool(self.acts) or (self.conf["thread_always"] and bool(self.pages))

    def refresh(self, *_a):
        now = time.monotonic()
        on = self.conf["on"]
        calls = self.calls.calls if self.calls and "call" in page_ids(self.conf) else {}
        self.acts = activities(self.conf, self.music, calls, self.timers) if on else []
        self.pages = all_pages(self.conf, self.acts, self.clip, self.cat.s) if on else []
        if self.flash and now >= self.flash["until"]:
            self.flash = None
        # событие: появилось новое главное дело, сменилась фаза помидора, пауза, трек, микрофон
        sig = None
        if self.acts:
            k, d = self.acts[0]
            sig = (k, d["phase"] if k == "pomo" else d["paused"] if k == "rec" else
                   d["muted"] if k == "call" else d["list"][0]["id"] if k == "timer" else
                   (d.title if self.conf["track_pop"] else "", d.status))
        if sig != self.sig:
            if sig is not None and (self.sig is None or sig[0] != self.sig[0] or sig[1:] != self.sig[1:]):
                if not (sig[0] == "music" and self.sig and self.sig[0] == "music"
                        and sig[1] == self.sig[1] and not self.conf["track_pop"]):
                    self.pop_until = now + self.conf["pop_sec"]
            self.sig = sig
        hidden = self.game or self.overview or not on
        tg = self.targets()
        for out, isl in self.wins.items():
            if hidden or out not in tg:
                mode = "none"
            elif isl.mode == "card" and self.pages:
                mode = "card"
            elif now < self.pop_until and (self.acts or self.flash):
                mode = "compact"
            else:
                mode = "thread" if self.want_thread(out) else "none"
            isl.go(mode)
        self.schedule(now)
        self.cat.sync()
        return True

    def schedule(self, now):
        """Один таймер: конец компакта, секунды в компакте/карточке и в живой капсуле со
        временем (звонок, запись, помидор, таймер), нить — раз в 15 с."""
        if self.timer:
            self.GLib.source_remove(self.timer)
            self.timer = None
        modes = {isl.mode for isl in self.wins.values()}
        waits = []
        if now < self.pop_until:
            waits.append(self.pop_until - now + 0.02)
        ticking = self.conf["thread_style"] == "pill" and self.acts and \
            self.acts[0][0] in ("call", "rec", "pomo", "timer")
        if (modes & {"compact", "card"} and self.pages) or ("thread" in modes and ticking):
            waits.append(1.0 - (time.time() % 1.0) + 0.01)
        elif "thread" in modes:
            waits.append(15.0)
        if self.music and any(p.status == "Paused" for p in self.music.players.values()):
            waits.append(5.0)
        if waits:
            self.timer = self.GLib.timeout_add(int(min(waits) * 1000), self._tick)

    def _tick(self):
        self.timer = None
        self.refresh()
        return False

    # — буфер обмена: снимки —
    def on_page(self, kind, page=None):
        if kind == "clip" and "clip" in page_ids(self.conf):
            self.load_clip()
        if page is not None and page_key(page) != self.last:   # листнули сами — запомнить
            self.last = page_key(page)
            try:
                with open(LAST, "w") as f:
                    f.write(self.last)
            except OSError:
                pass

    def load_clip(self):
        """Последние картинки буфера: список и файлы — в потоке, миниатюры — в цикле GTK.
        Не чаще раза в 2 с (раскрытие + колесо зовут подряд)."""
        now = time.monotonic()
        if self.clip.get("loading") or now - self.clip_t < 2:
            return
        self.clip_t = now
        self.clip["loading"] = True
        import threading

        def run():
            found = []
            for cid, fmt, w, h in list_clip_images():
                try:
                    path = clip_file(cid, fmt)
                except (OSError, subprocess.SubprocessError):
                    path = None
                if path:
                    found.append({"id": cid, "fmt": fmt, "w": w, "h": h, "path": path})
            prune_clip({it["id"] for it in found})
            self.GLib.idle_add(lambda: self.set_clip(found) and False)
        threading.Thread(target=run, daemon=True).start()

    def set_clip(self, found):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        old = {it["id"]: it for it in self.clip.get("items") or []}
        items = []
        for it in found:
            if it["id"] in old and old[it["id"]].get("surf") is not None:
                items.append(old[it["id"]])
                continue
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(it["path"], 240, 180, True)
                it["surf"] = self.Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
                it["pb"] = GdkPixbuf.Pixbuf.new_from_file_at_scale(it["path"], 96, 96, True)
            except Exception as e:
                log("clip thumb", it["id"], e)
                it["surf"] = it["pb"] = None
            items.append(it)
        self.clip = {"items": items, "loading": False, "copied": self.clip.get("copied")}
        self.refresh()
        self.redraw()

    def clip_item(self, cid):
        return next((it for it in self.clip.get("items") or [] if it["id"] == cid), None)

    def clip_prepare(self, cid):
        pass                                    # файл уже записан load_clip

    def clip_path(self, cid):
        it = self.clip_item(cid)
        return it["path"] if it and os.path.exists(it["path"]) else None

    # — действия —
    def spawn(self, argv):
        subprocess.Popen(["niri", "msg", "action", "spawn", "--", *argv], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)

    def collapse_all(self):
        for isl in self.wins.values():
            if isl.mode == "card":
                isl.collapse()

    def do(self, act, card_i=0):
        kind, what = act
        try:
            if kind == "music":
                p = self.music.current() if self.music else None
                if p:
                    self.music.command(p, what)
            elif kind == "pomo":
                subprocess.Popen(["pomo", what], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            elif kind == "rec":
                subprocess.Popen(["bash", REC_SH, what], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            elif kind == "call" and what == "mute" and self.calls:
                import threading
                threading.Thread(target=self.calls.toggle_mute, daemon=True).start()
            elif kind == "call" and what == "focus":
                self.focus_call()
            elif kind == "timer" and what.startswith("stop:"):
                subprocess.Popen(["rem", "del", what.split(":", 1)[1]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                self.GLib.timeout_add(500, lambda: self.poll_timers() and False)
            elif kind == "timer" and what.startswith("start:"):
                subprocess.Popen(["hub", "timer", what.split(":", 1)[1]], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
                self.GLib.timeout_add(600, lambda: self.poll_timers() and False)
            elif kind == "timer" and what == "ask":
                self.collapse_all()
                self.spawn([sys.executable, os.path.abspath(__file__), "timer-ask"])
            elif kind == "timer" and what == "open":
                self.collapse_all()
                self.spawn(["hub-open"])
            elif kind == "clip" and str(what).isdigit():
                subprocess.Popen(["sh", "-c", "cliphist decode %s | wl-copy" % what],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                self.clip["copied"] = what
                self.redraw()
                self.GLib.timeout_add(1200, lambda: (self.clip.pop("copied", None), self.redraw()) and False)
            elif kind == "tool":
                self.tool(what)
            elif kind == "cat" and what == "pet":
                self.cat.pet()
            elif kind == "cat" and what == "busy":
                self.cat.focus_busy()
                self.collapse_all()
        except OSError as e:
            log("действие", act, e)
        self.GLib.timeout_add(250, lambda: self.refresh() and False)

    def focus_call(self):
        """Окно звонка: Telegram или Discord — фокус через niri по app_id."""
        names = [n.lower() for n in (self.calls.calls if self.calls else {})]
        keys = {"telegram": ("telegram", "ayugram", "64gram"), "discord": ("discord", "vesktop", "webcord",
                                                                           "equibop", "legcord")}
        want = [k for n in names for k in keys.get(n, ())]
        for w in niri_json("windows") or []:
            app = (w.get("app_id") or "").lower()
            if any(k in app for k in want):
                subprocess.Popen(["niri", "msg", "action", "focus-window", "--id", str(w["id"])],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
        self.collapse_all()

    def tool(self, tid):
        """Инструмент со страницы: островок сворачивается, программа запускается отдельно.
        Пипетка — своим процессом: цвет показывается вспышкой (и уже в буфере, -a)."""
        self.collapse_all()
        t = next((t for t in TOOLS if t[0] == tid), None)
        if not t:
            return
        if tid == "pick":
            import threading

            def run():
                time.sleep(0.35)                # островок успевает свернуться и не попасть в кадр
                try:
                    out = subprocess.run(["hyprpicker", "-a", "-f", "hex"], capture_output=True, text=True,
                                         timeout=120).stdout.strip()
                except (OSError, subprocess.SubprocessError):
                    out = ""
                if out:
                    self.GLib.idle_add(lambda: self.push_flash(out + " · скопирован", G_PICK) and False)
            threading.Thread(target=run, daemon=True).start()
            return
        argv = t[3]
        if tid == "shot":                       # снимок niri: сперва убрать островок с экрана
            self.GLib.timeout_add(350, lambda: subprocess.Popen(
                argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) and False)
            return
        self.spawn(argv)

    def push_flash(self, text, icon=""):
        self.flash = {"text": text, "icon": icon, "until": time.monotonic() + self.conf["pop_sec"] + 1}
        self.pop_until = self.flash["until"]
        self.refresh()

    def primary_action(self, kind):
        self.do({"music": ("music", "PlayPause"), "pomo": ("pomo", "toggle"),
                 "rec": ("rec", "pause"), "call": ("call", "mute")}.get(kind, ("", "")))


def timer_ask():
    """«Своё…» на странице таймера: rofi с подсказками; «25», «1ч30», «90с», «10 чай» (после
    времени — название). Запускает hub timer."""
    hint = "\n".join(["%d" % m for m in TIMER_PRESETS] + ["1ч", "1ч30", "90с"])
    try:
        out = subprocess.run(["rofi", "-dmenu", "-i", "-p", "Таймер", "-mesg",
                              "минуты числом, «1ч30», «90с»; после времени — название"],
                             input=hint, capture_output=True, text=True, timeout=300).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return 1
    if not out:
        return 0
    sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))
    try:
        import hublib as H
    except ImportError:
        return 1
    words = out.split()
    for n in range(len(words), 0, -1):          # самое длинное начало, похожее на время
        if H.parse_duration(" ".join(words[:n])):
            dur, name = "".join(words[:n]), " ".join(words[n:])
            break
    else:
        subprocess.run(["notify-send", "-a", "Таймер", "Таймер", "Не понял время: " + out])
        return 1
    return subprocess.run(["hub", "timer", dur] + ([name] if name else []), stdout=subprocess.DEVNULL).returncode


def run():
    lock = open(LOCK, "a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    import warnings
    warnings.filterwarnings("ignore", category=DeprecationWarning)

    def hook(tp, val, tb):                      # ошибки обработчиков GTK — в журнал, не в /dev/null
        import traceback
        log("ошибка:", "".join(traceback.format_exception(tp, val, tb))[-1500:])
    sys.excepthook = hook
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import GLib, Gtk
    from hot_corners import glib_signal_add
    App()
    import threading
    threading.Thread(target=sync_space, args=(load_conf(),), daemon=True).start()
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, lambda: (send({"cmd": "reload"}), True)[1])
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, lambda: (Gtk.main_quit(), False)[1])
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: (Gtk.main_quit(), False)[1])
    log("запущен, pid", os.getpid())
    Gtk.main()
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    return 0


def send(d):
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
        s.sendto(json.dumps(d, ensure_ascii=False).encode(), SOCK)
        return True
    except OSError:
        return False


def shot(path, names=None):
    """Виды островка строками (нить, компакт, карточки) на обоях под полосой бара — в один
    PNG, без экрана (как проверки xpbar)."""
    import cairo
    import gi
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GdkPixbuf

    class FakeP:
        title, artist, identity, status, length = "Bad Apple!!", "Alstroemeria Records", "Яндекс Музыка", "Playing", 312

        def position(self):
            return 97

    pomo = ("pomo", {"phase": "work", "rem": 1453, "dur": 2700, "paused": False, "task": "programming"})
    music = ("music", FakeP())
    rec = ("rec", {"paused": False, "sec": 133, "mode": "видео"})
    th = thread_h()
    cells = [("нить", "thread", THREAD_W, [pomo, music]), ("компакт", "compact", 0, [music]),
             ("карточка: музыка", "card", CARD_W, [music, pomo]), ("карточка: помидор", "card", CARD_W, [pomo, rec])]
    names = names or list(DESIGNS)
    col = colors()
    BAR, CELL_W, HEAD = 30, CW, 22
    CELL_H = BAR + 8 + CARD_H + 12
    S = cairo.ImageSurface(cairo.FORMAT_ARGB32, CELL_W * len(cells), (CELL_H + HEAD) * len(names))
    cr = cairo.Context(S)
    try:
        wp = _read(os.path.expanduser("~/.cache/matugen/wallpaper"))
        pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(wp, S.get_width(), -1, True)
        Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    except Exception:
        cr.set_source_rgb(0.3, 0.32, 0.38)
    cr.paint()
    for r, name in enumerate(names):
        D = DESIGNS[name]
        y0 = r * (CELL_H + HEAD)
        cr.rectangle(0, y0, S.get_width(), HEAD)
        cr.set_source_rgba(0, 0, 0, 0.75)
        cr.fill()
        put_text(cr, "%d. %s  (%s)" % (r + 1, D["name"], name), 16, 8, y0 + HEAD / 2, col["on_surface"])
        for c, (label, mode, w, acts) in enumerate(cells):
            x0 = c * CELL_W
            cr.rectangle(x0, y0 + HEAD, CELL_W, BAR)        # полоса бара, как на экране ноутбука
            cr.set_source_rgba(*col["bg"], 0.92)
            cr.fill()
            put_text(cr, label, 8, x0 + 8, y0 + HEAD + BAR / 2, col["on_surface_variant"])
            sub = cairo.ImageSurface(cairo.FORMAT_ARGB32, CW, CH)
            c2 = cairo.Context(sub)
            font_opts(c2)
            h = {"thread": THREAD_H, "compact": COMPACT_H}.get(mode, CARD_H)
            if mode == "compact":
                k, d = acts[0]
                w = compact_w(c2, k, d, len(acts) - 1, D)
            paint(c2, {"w": w, "h": h, "mode": mode, "alpha": 1.0, "acts": acts, "th": th}, col, D)
            use_font(None)
            cr.save()
            cr.rectangle(x0, y0 + HEAD, CELL_W, CELL_H)
            cr.clip()
            cr.set_source_surface(sub, x0, y0 + HEAD + BAR)
            cr.paint()
            cr.restore()
    S.write_to_png(path)
    print(path)


def main(argv):
    if not argv or argv[0] == "run":
        return run()
    cmd = argv[0]
    if cmd == "push":
        ok = send({"text": argv[1] if len(argv) > 1 else "", "ttl": float(argv[2]) if len(argv) > 2 else None,
                   "icon": argv[3] if len(argv) > 3 else ""})
        return 0 if ok else 1
    if cmd == "timer-ask":
        return timer_ask()
    if cmd == "get":
        c = load_conf()
        print(json.dumps(c, ensure_ascii=False) if len(argv) < 2 else c.get(argv[1], ""))
        return 0
    if cmd == "set" and len(argv) >= 3:
        c = load_conf()
        k, v = argv[1], argv[2]
        if k not in DEFAULTS:
            print("нет такой настройки: %s" % k, file=sys.stderr)
            return 1
        dv = DEFAULTS[k]
        c[k] = (v.lower() in ("1", "on", "true", "yes", "да")) if isinstance(dv, bool) else \
            float(v) if isinstance(dv, float) else v
        save_conf(c)
        send({"cmd": "reload"})
        if k in ("on", "thread", "thread_style", "overlay", "monitor"):
            sync_space(c)
        return 0
    if cmd in ("stop", "restart"):
        pid = running_pid()
        if pid:
            os.kill(pid, signal.SIGTERM)
            for _ in range(30):
                if not running_pid():
                    break
                time.sleep(0.1)
        if cmd == "restart":
            subprocess.Popen(["niri", "msg", "action", "spawn", "--", "python3", os.path.abspath(__file__)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return 0
    if cmd == "status":
        pid = running_pid()
        print("работает: %s" % ("да, pid %d" % pid if pid else "нет"))
        print("настройки:", json.dumps(load_conf(), ensure_ascii=False))
        return 0
    if cmd == "check":
        pid = running_pid()
        ok = pid is not None and os.path.exists(SOCK)
        print("островок: %s" % ("работает, pid %d" % pid if ok else
                                "выключен в настройках" if not load_conf()["on"] else "не запущен"))
        return 0 if ok or not load_conf()["on"] else 1
    if cmd == "shot" and len(argv) > 1:
        shot(argv[1], argv[2:] or None)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
