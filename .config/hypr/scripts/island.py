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
# последний открытый блок, которому есть что показать в «Живой» нити (звонок, музыка, помидор,
# таймер, запись, котик); снимки, захват, фокус, настройки его не меняют (20.10.2026, пользователь)
LAST_INFO = os.path.expanduser("~/.config/hypr/state/island-last-info")
INFO_KINDS = ("call", "music", "pomo", "timer", "rec", "nudge", "cat", "cc")
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
    "pages": "call,music,pomo,timer,rec,nudge,cat,cc,clip,tools,wifi,bt,power,prefs",
    "rev": 8,                # версия настроек: 3 — «Котик», 4 — «Настройки», 5 — «Полка», трек 5 с, 6 — «Пора к делу»,
                             # 7 — «Центр», Wi-Fi, Bluetooth, Питание (20.10.2026), 8 — «Центр» за котиком
    "nudge_min": 45.0,       # «Пора к делу»: столько минут подряд видео или дотфайлов — первое напоминание
    "nudge_every": 20.0,     # дальше — раз в столько минут, другой фразой
    "downloads": True,       # загрузки/отправка — панель под живой капсулой (island_dl.py)
    # Поверх окон: зазора над окнами нет (край как по системе), островок рисуется поверх
    # всего; в играх всё равно прячется (19.10.2026: «Поверх окон… Кроме игр»).
    "overlay": False,
    "track_pop": True,       # смена трека: название в компакте на 5 с (TRACK_POP_S)
    "osd": True,             # громкость, микрофон, яркость — индикатором в островке, без шторки eww
    "night_dim": True,       # ночью (NIGHT) островок притушен
    "bubble": True,          # пузырь ▶ рядом с нитью, пока музыка на паузе
    "pop_sec": 2.5,          # сколько держится раскрытым: после ухода курсора и после события
    "design": "auto",        # вид: auto — как стиль системы (Default/Skeet/Beta), ios
    "thread_style": "line",  # нить: line — линия, dots — точки, pill — живая (последний блок с инфо)
    "thread_alpha": 0.8,     # яркость нити: 0.2 Low, 0.8 High (TA_LEVELS)
    "hover": True,           # раскрывать наведением (иначе — щелчком)
    "video_hide": False,     # при видео в фокусе нить не видна (19.10.2026: «пока что убери»)
}

# Холст постоянного размера: размер поверхности не меняется. 232 → 264 (20.10.2026, просьба:
# «где края? снизу островка») — Skeet-карточка снимков 212 + 36 = 248 px срезалась снизу.
# 264 → 420 (20.10.2026): «Ещё…» у Wi-Fi/Bluetooth раскрывает весь список вниз
CW, CH = 560, 420
THREAD_W, THREAD_H, EASE_H, CARD_W, CARD_H = 132, 4, 34, 420, 120
TA_LEVELS = (0.2, 0.8)
# 20.10.2026, просьба: «переименуй на Low Mid High…», затем «опять Mid и High ничем не
# отличаются… тогда оставляй 2 кнопки Low High». Линия на Mid уже почти непрозрачна (0.84),
# ярче полной непрозрачности не сделать — ступеней две: Low притушает и линию, и капсулу,
# High — нить целиком, без прозрачности.
HARD_SHADOW = 5           # тень раскрытого островка — как у виджетов (desktop_widgets.SHADOW)
CARD_HK = {"clip": 212, "shelf": 212,   # своя высота страницы: снимки и полка — два ряда по четыре
           "music": 150,                # музыка: обложка слева и эквалайзер внизу (20.10.2026)
           "cc": 150, "wifi": 150, "bt": 150,
           "prefs": 148}                # настройки: четыре ряда (с 20.10.2026 и яркость нити)   # «Центр»: аватар, система, три плитки; сети и устройства — списком
MUSIC_COVER = 48                        # обложка карточки музыки: 24×24 крупными пикселями ×2
MUSIC_EQ = (4, 4, 24)                   # эквалайзер карточки: рядов, квадратик px, место под него px
SK_TOP, SK_EXTRA = 30, 36  # Skeet: радуга и вкладки над рамкой группы; карточка на столько выше
ANIM_MS = 300
HOVER_MS, LEAVE_MS = 140, 650   # задержка раскрытия наведением и сворачивания после ухода курсора
HOVER_CTL_MS = 550              # то же над капсулой, которой можно управлять (колесо, ЛКМ)
HOVER_PAD = 18                  # зона наведения вокруг нити (сама нить 3 px — в неё не попасть)
THREAD_Y = 5                    # нить на 5 px ниже края (было 2 — «опусти чуть-чуть», 19.10.2026)
PILL_W, PILL_H = 74, 24         # нить-капсула (20→24, 19.10.2026: «больше пространства между верхом и низом»)
# компакт (запись, событие, индикатор) — высотой с мини-островок, 34→24 (20.10.2026, просьба:
# «сохраняло размер мини островка… а то влезает в окно снизу»); раскрытые карточки — как были
COMPACT_H = PILL_H
# Зазор между окнами и нитью: добавка к верхнему краю niri (niri_compositor.py island_space).
# Края окон = 8 px. Капсула 24 px → +28 (по 6 px воздуха сверху и снизу); линии/точкам чуть
# меньше, но не впритык (19.10.2026: «для линии поменьше, но не прям сильно меньше»): +17 —
# линия 3 px ровно посередине, по 11 px над и под ней.
SPACE = {"line": 17, "dots": 17, "pill": 28, "cat": 28}
PILLS = ("pill", "cat", "ccp")  # нити-капсулы: своя высота и ширина по содержимому (ccp — «Центр»)
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
PAUSED_KEEP = 60             # музыка на паузе держится нитью столько секунд (30→60, 20.10.2026:
                             # «исчезает слишком быстро, если ничего не играет»)
TRACK_POP_S = 5.0            # название нового трека в компакте (20.10.2026: «на 5 секунд»)
NIGHT = (22, 7)              # ночное притемнение: с 22:00 до 07:00
NIGHT_A = {"thread": 0.6, "compact": 0.75, "card": 0.9}
G_SUN = "\U000f00df"         # яркость (mdi brightness-6)
VOL_STEP, SEEK_S = 5, 5      # колесо на капсуле: громкость ±5 %, Shift+колесо — перемотка ±5 с
OSD_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-island.osd")
# мониторы, где островок сейчас сам показывает строку песни — там нижняя панель (xpbar) её не
# дублирует (20.10.2026, просьба: «если вверху и так отображается текст — не показывать снизу»)
LYR_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-island-lyrics")
_LYR = {"on": False}            # paint: нарисована полоса строки песни (капсула котика, карточка)
_CAT = {"s": None}              # paint: состояние кота (обложка, cava) — карточке музыки
EWW_VOL_OPEN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "eww-vol.open")

G_PREV, G_PLAY, G_PAUSE, G_NEXT, G_STOP = "\U000f04ae", "\U000f040a", "\U000f03e4", "\U000f04ad", "\U000f04db"
G_POMO, G_BREAK, G_NOTE, G_REC, G_SKIP = "\U000f051f", "\U000f0176", "\U000f075a", "\U000f044a", "\U000f0661"
G_MIC, G_MIC_OFF, G_TIMER, G_CLIP, G_PICK = "\U000f036c", "\U000f036d", "\U000f051b", "\U000f0192", "\U000f020a"
G_TOOLS = "\U000f09ac"                 # md-toolbox; в островке — пикселями (PIX_BMP)
G_SHOT, G_MEMO, G_OPEN, G_CALL, G_BOARD = "\U000f019e", "\U000f039a", "\U000f03cc", "\U000f03f2", "\U000f014c"
G_TG, G_DISCORD, G_WA = "", "\U000f066f", "\U000f05a3"

G_PLUS, G_COG = "\U000f0415", "\U000f0493"
G_NUDGE = "\U000f018d"                # md-console; в островке — пикселями (PIX_BMP)
# «Пора к делу» (20.10.2026, просьба: «если просидел долго за видео или опять настраиваю
# дотфайлы — сверху плашка… текст слева направо, как в старых терминалах»). Янтарь старых
# мониторов — не из палитры обоев; рамка мигает NUDGE_BLINK_S, потом фраза печатается по буквам.
NUDGE_RGB = (1.0, 0.71, 0.2)
NUDGE_POLL_S = 10
NUDGE_BLINK_S, NUDGE_CHAR_S, NUDGE_HOLD_S = 1.0, 0.045, 6.0
DL_POLL_S, DL_FRAME_MS, DL_DONE_S = 2, 90, 1.5   # загрузки: опрос, кадр «бегущих» клеток, «готово»
DL_W, DL_H, DL_PAD, DL_SQ, DL_SQ_GAP = 300, 50, 12, 6, 2   # панель загрузки под капсулой: клетки 6 px
BAR_UP_S = 6.0               # верхний бар показан: островок прячется на столько с последней вести
G_VOL, G_VOL_OFF, G_WAVE = "\U000f057e", "\U000f0581", "\U000f0e4e"

# Страницы островка: id → (название, что на ней, вид). Вид: live — есть, только пока дело
# идёт (это и дела капсулы: их порядок в настройках = приоритет); always — есть всегда и
# живая, когда идёт (таймер); static — всегда, без дела.
# 19.10.2026, просьба: «Буфер убери, Таймер отдельным блоком, сразу с готовым пресетом или
# с выбором собственного времени. Запись, Пипетка и Снимок в один общий блок. Заметку,
# Помидор в отдельный блок» — вместо одной страницы «Инструменты» (tools) две: capture и focus.
PAGES = {
    "call":    ("Звонок", "Telegram/Discord/WhatsApp: длительность, микрофон звонка, громкость; голосовое — живая волна", "live"),
    "music":   ("Музыка", "где играет (YouTube, Яндекс Музыка…), время, громкость приложения", "live"),
    "pomo":    ("Помидор", "сколько осталось, задача, пауза, пропуск, стоп", "live"),
    "timer":   ("Таймер", "идущие таймеры hub; «+» — ещё один, с виджетом timer.exe, как из Telegram", "always"),
    "rec":     ("Запись экрана", "время записи, пауза, стоп", "live"),
    "nudge":   ("Пора к делу", "долго за видео или дотфайлами в редакторе — фраза печатается в островке; внутри — сколько сидите", "live"),
    "clip":    ("Снимки из буфера", "последние картинки: перетащить в чат или поиск, щелчок — скопировать", "static"),
    "tools":   ("Инструменты", "запись экрана, пипетка, снимок, заметка, помидор", "static"),
    "cat":     ("Котик", "бегает, пока занят терминал, играет музыка или идёт помидор; песня с текстом — караоке", "static"),
    "prefs":   ("Настройки", "вид островка, вид и яркость нити, сколько держать раскрытым — прямо в островке", "static"),
    "shelf":   ("Полка", "бросьте файл на островок — полежит здесь; щелчок — открыть, перетащить — куда угодно", "static"),
    "cc":      ("Центр", "аватар и ник, система и uptime; Кофеин (ПКМ — с Таурином), Ночной свет (ПКМ — спектр), Баланс/Мощность (ПКМ — Экономия); свёрнутый — Сторож, день недели, кофеин", "static"),
    "wifi":    ("Wi-Fi", "вкл/выкл, сети: щелчок — кнопки (подключить, пароль, отключить, забыть); «Ещё…» — весь список", "static"),
    "bt":      ("Bluetooth", "вкл/выкл, устройства: щелчок — кнопки (подключить, отключить, забыть); «Ещё…» — поиск новых", "static"),
    "power":   ("Питание", "блокировка, выход, сон, перезагрузка, выключение (с подтверждением)", "static"),
}
SYS_PAGES = ("cc", "wifi", "bt", "power")   # системные страницы (island_sys.py), 20.10.2026
SYS_POLL = ("cc", "wifi", "bt", "pill", "radio")   # что опрашивается (pill — капсула «Центра», radio — значки вкладок)
PAGE_GLYPH = {"call": G_CALL, "rec": G_REC, "nudge": G_NUDGE, "pomo": G_POMO, "timer": G_TIMER, "music": G_NOTE,
              "clip": G_CLIP, "tools": G_TOOLS, "cat": "\U000f011b",
              "prefs": G_COG, "shelf": "\U000f024b", "cc": "\U000f0521", "wifi": "\U000f05a9", "bt": "\U000f00af",
              "power": "\U000f0425"}
PAGE_EXE = {"call": "call.exe", "music": "music.exe", "pomo": "pomo.exe", "timer": "timer.exe",
            "rec": "rec.exe", "nudge": "nudge.exe", "clip": "clip.exe", "tools": "tools.exe",
            "cat": "cat.exe", "prefs": "island.exe", "shelf": "shelf.exe", "cc": "control.exe",
            "wifi": "wifi.exe", "bt": "bluetooth.exe", "power": "power.exe"}
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
# Свой цвет у каждого инструмента (20.10.2026, просьба: «покрась в подходящие цвета, точку
# записи в красный»). Не из палитры обоев — смысл цвета не должен меняться с обоями.
# Вкладки Skeet: блоки, что выходят в нить (живые), — цветные с полоской снизу; инструменты —
# серые (20.10.2026, просьба: «хочу различать блоки информационного блока и просто вкладки»).
# «Центр» — тоже живой: свёрнутый островок показывает его капсулу (20.10.2026)
LIVE_TABS = ("call", "rec", "pomo", "timer", "music", "nudge", "cat", "cc")
TAB_IDS = []    # блоки из настроек по порядку — места вкладок Skeet (App.refresh)
TOOL_RGB = {"rec": (0.94, 0.28, 0.28), "pick": (0.78, 0.55, 0.98), "shot": (0.36, 0.78, 0.96),
            "note": (0.98, 0.82, 0.30), "pomo": (0.98, 0.45, 0.30)}
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
    # 20.10.2026: «Захват» и «Фокус» снова одна страница «Инструменты» (просьба: «блоки Захват
    # и Фокус можешь объединить в одну») — на месте первой из двух
    pg = [x.strip() for x in str(d["pages"]).split(",")]
    if "capture" in pg or "focus" in pg:
        i = min(pg.index(x) for x in ("capture", "focus") if x in pg)
        pg = [x for x in pg[:i] if x != "tools"] + ["tools"] + \
             [x for x in pg[i:] if x not in ("capture", "focus", "tools")]
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
    if raw.get("rev", 0) < 4 and raw:           # 20.10.2026: страница «Настройки», нить-котик → живая
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        if "prefs" not in pg:
            d["pages"] = ",".join(pg + ["prefs"])
        if d["thread_style"] == "cat":          # котик теперь — часть живой нити: её последний блок
            d["thread_style"] = "pill"
            if not _read(LAST_INFO).strip():
                try:
                    with open(LAST_INFO, "w") as f:
                        f.write("cat")
                except OSError:
                    pass
        d["rev"] = 4
        try:
            save_conf(d)
        except OSError:
            pass
    if raw.get("rev", 0) < 5 and raw:           # 20.10.2026: «Полка» после снимков, трек на 5 с
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        if "shelf" not in pg:
            pg.insert(pg.index("clip") + 1 if "clip" in pg else len(pg), "shelf")
            d["pages"] = ",".join(pg)
        d["track_pop"] = True
        d["rev"] = 5
        try:
            save_conf(d)
        except OSError:
            pass
    if raw.get("rev", 0) < 6 and raw:           # 20.10.2026: «Пора к делу» — после записи, перед котиком
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        if "nudge" not in pg:
            pg.insert(pg.index("cat") if "cat" in pg else len(pg), "nudge")
            d["pages"] = ",".join(pg)
        d["rev"] = 6
        try:
            save_conf(d)
        except OSError:
            pass
    if raw.get("rev", 0) < 7 and raw:           # 20.10.2026: «Центр», Wi-Fi, Bluetooth, Питание — перед настройками
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        new = [x for x in SYS_PAGES if x not in pg]
        if new:
            i = pg.index("prefs") if "prefs" in pg else len(pg)
            d["pages"] = ",".join(pg[:i] + new + pg[i:])
        d["rev"] = 7
        try:
            save_conf(d)
        except OSError:
            pass
    if raw.get("rev", 0) < 8 and raw:           # 20.10.2026: «Центр» — между котиком и буфером
        pg = [x.strip() for x in str(d["pages"]).split(",")]
        if "cc" in pg and "cat" in pg:
            pg.remove("cc")
            pg.insert(pg.index("cat") + 1, "cc")
            d["pages"] = ",".join(pg)
        d["rev"] = 8
        try:
            save_conf(d)
        except OSError:
            pass
    if d["thread_style"] not in ("line", "dots", "pill"):
        d["thread_style"] = "pill" if d["thread_style"] == "cat" else "line"
    try:                                        # две ступени: Low / High (TA_LEVELS)
        d["thread_alpha"] = 0.2 if float(d["thread_alpha"]) < 0.3 else 0.8
    except (TypeError, ValueError):
        d["thread_alpha"] = 0.8
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
            meta = dict(props["Metadata"] or {})
            # браузер на паузе/перемотке шлёт метаданные без длины — та же песня, длину помним
            if not meta.get("mpris:length") and p.meta.get("mpris:length") \
                    and str(meta.get("xesam:title") or "").strip() == p.title:
                meta["mpris:length"] = p.meta["mpris:length"]
            p.meta = meta

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

    def paused_player(self, keep=None):
        """Плеер, поставленный на паузу последним (не дольше keep с назад), — если ничто не играет."""
        ps = [p for p in self.players.values() if p.title and not p.ignored()]
        if any(p.status == "Playing" for p in ps):
            return None
        now, keep = time.monotonic(), keep or BUBBLE_KEEP
        recent = [p for p in ps if p.status == "Paused" and now - self.paused_at.get(p.name, -1e9) < keep]
        return max(recent, key=lambda p: self.paused_at.get(p.name, 0)) if recent else None

    def player(self):
        """Кем управлять с капсулы: играющий, иначе недавно поставленный на паузу."""
        return self.current() or self.paused_player()

    def seek(self, p, sec):
        try:
            self.bus.call(p.name, self.PATH, self.IFACE, "Seek", self.GLib.Variant("(x)", (int(sec * 1e6),)),
                          None, self.Gio.DBusCallFlags.NONE, 800, None, None)
        except Exception as e:
            log("mpris seek", e)

    def pid(self, p):
        try:
            return int(self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                 "GetConnectionUnixProcessID", self.GLib.Variant("(s)", (p.name,)), "(u)")[0])
        except Exception:
            return None

    def command(self, p, method):
        try:
            self.bus.call(p.name, self.PATH, self.IFACE, method, None, None,
                          self.Gio.DBusCallFlags.NONE, 800, None, None)
        except Exception as e:
            log("mpris", method, e)


CALL_APPS = (("telegram", "Telegram", G_TG), ("ayugram", "Telegram", G_TG), ("64gram", "Telegram", G_TG),
             ("discord", "Discord", G_DISCORD), ("vesktop", "Discord", G_DISCORD),
             ("webcord", "Discord", G_DISCORD), ("equibop", "Discord", G_DISCORD), ("legcord", "Discord", G_DISCORD),
             ("zapzap", "WhatsApp", G_WA), ("whatsapp", "WhatsApp", G_WA), ("wasistlos", "WhatsApp", G_WA))


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
        # и командная строка родителя: ZapZap пишет микрофон из QtWebEngineProcess («Chromium
        # input»), имя приложения есть только у его родителя (20.10.2026: звонок WhatsApp не виден)
        try:
            pid = int(pr.get("application.process.id") or 0)
            for _ in range(2):
                if pid <= 1:
                    break
                hay += " " + open("/proc/%d/cmdline" % pid, "rb").read().replace(b"\0", b" ").decode(
                    "utf-8", "replace").lower()
                pid = int(open("/proc/%d/stat" % pid).read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
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
        self.quiet = 0.0             # до этого времени OSD микрофона молчит (нажали кнопку в капсуле)
        self.pin = None              # (muted, до) — нажатое держится, пока pactl применяет
        self.vpin = None             # (громкость, до) — то же для ползунка микрофона
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
        if self.pin:
            want, until = self.pin
            if time.monotonic() > until or all(c["muted"] == want for c in new.values()):
                self.pin = None
            else:                               # опрос успел раньше команды — не мигать назад
                for c in new.values():
                    c["muted"] = want
        if self.vpin:
            want, until = self.vpin
            if time.monotonic() > until or all(c["vol"] == want for c in new.values()):
                self.vpin = None
            else:
                for c in new.values():
                    c["vol"] = want
        sig = lambda d: {k: (v["muted"], tuple(v["ids"]), v["voice"], v["vol"]) for k, v in d.items()}
        changed = sig(new) != sig(self.calls)
        self.calls = new
        if changed:
            self.on_change()

    def toggle_mute(self):
        """Микрофон системы — как ЛКМ по микрофону в нижней панели (wpctl set-mute
        @DEFAULT_AUDIO_SOURCE@): 20.10.2026, просьба: «сделаем на выключение микрофона, которая
        работает в нижней панели» — раньше глушился только поток звонка, и ни приложение, ни
        система этого не показывали. Включение снимает и старый mute потоков звонка.
        Кнопка меняется сразу, команды — в потоке (20.10.2026: «как будто с задержкой…»)."""
        muted = any(c["muted"] for c in self.calls.values())
        self.quiet = time.monotonic() + 1.5     # вспышка OSD «Микрофон · выкл» островок не меняет
        ids = [i for c in self.calls.values() for i in c["ids"]] if muted else []
        for c in self.calls.values():
            c["muted"] = c["gmute"] = not muted
        self.pin = (not muted, time.monotonic() + 2)
        self.on_change()

        def run():
            try:
                procs = [subprocess.Popen(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "0" if muted else "1"])]
                procs += [subprocess.Popen(["pactl", "set-source-output-mute", str(i), "0"]) for i in ids]
                for p in procs:
                    p.wait(timeout=3)
            except (OSError, subprocess.SubprocessError) as e:
                log("toggle_mute:", e)
            self.GLib.idle_add(lambda: self.kick() and False)
        import threading
        threading.Thread(target=run, daemon=True).start()
        return not muted

    def set_mic_volume(self, v):
        """Ползунок карточки: громкость микрофона системы — сразу на экране, wpctl — в потоке."""
        self.quiet = time.monotonic() + 1.5     # OSD «Микрофон NN %» островок не трогает
        for c in self.calls.values():
            c["vol"] = v
        self.vpin = (v, time.monotonic() + 2)
        self.on_change()

        def run():
            try:
                subprocess.run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SOURCE@", "%.2f" % (v / 100)], timeout=3)
            except (OSError, subprocess.SubprocessError) as e:
                log("set_mic_volume:", e)
            self.GLib.idle_add(lambda: self.kick() and False)
        import threading
        threading.Thread(target=run, daemon=True).start()

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
CLIP_N = 8                 # 20.10.2026: «почему всего 4 снимка помещаются?» — сетка 4×2


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


SHELF = os.path.expanduser("~/.config/hypr/state/island-shelf.json")
SHELF_N = 8
IMG_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg")
G_FILE, G_FOLDER, G_X = "\U000f0214", "\U000f024b", "\U000f0156"


def shelf_load():
    """Полка: пути файлов, свежие первыми; пропавшие с диска — мимо."""
    try:
        v = json.load(open(SHELF))
    except (OSError, ValueError):
        return []
    return [p for p in v if isinstance(p, str) and os.path.exists(p)][:SHELF_N] if isinstance(v, list) else []


def shelf_save(paths):
    try:
        os.makedirs(os.path.dirname(SHELF), exist_ok=True)
        with open(SHELF + ".tmp", "w") as f:
            json.dump(paths[:SHELF_N], f, ensure_ascii=False)
        os.replace(SHELF + ".tmp", SHELF)
    except OSError as e:
        log("shelf:", e)


def prune_clip(keep):
    try:
        for f in os.listdir(CLIP_DIR):
            if f.split(".")[0] not in keep:
                os.unlink(os.path.join(CLIP_DIR, f))
    except OSError:
        pass


# ─────────────────────────── что показывать ───────────────────────────

def activities(conf, music, calls=None, timers=None, nudge=None):
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
        elif p == "nudge" and nudge:
            out.append(("nudge", nudge))
    return out


def all_pages(conf, acts, clip, cat=None, shelf=None, sysd=None):
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
        elif p == "shelf":
            out.append(("shelf", shelf))
        elif p == "prefs":
            out.append(("prefs", {k: conf[k] for k in ("design", "thread_style", "thread_alpha", "pop_sec")}))
        elif p in ("cc", "wifi", "bt", "power"):
            out.append((p, (sysd or {}).get(p)))
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
    if kind == "nudge":
        return (G_NUDGE, d.get("text") or "Пора к делу", "nudge")
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
        # только длительность: приложение видно по значку, микрофон — по кнопке (20.10.2026,
        # Просьба: «WhatsApp · микрофон вкл» — «это тоже не нужно показывать»)
        return (d["icon"], mmss(call_sec(d)), "call")
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
    if kind == "flash":                         # индикатор громкости/яркости: уровень 0…1
        return d.get("pr")
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
    # чистый акцент обоев — им красятся рамки виджетов (desktop_widgets.load_theme); 20.10.2026,
    # Просьба: «сравни рамки островка и виджета, не хватает акцентной цветности» (было primary)
    try:
        c["vivid"] = rgb(open(os.path.expanduser("~/.cache/matugen/vivid.txt")).read().strip())
    except (OSError, ValueError):
        c["vivid"] = c["primary"]
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
    k = max(0.0, min(1.0, (h - THREAD_H) / max(1, EASE_H - THREAD_H)))
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
    if kind == "nudge":                         # ширина под всю фразу сразу — пока печатается, не растёт
        return max(150, min(CW - 60, 36 + text_w(cr, text, 13 if D and D.get("ios") else 8) + 26))
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
    _CAT["s"] = st.get("cat")
    x = (CW - w) / 2
    ty = st.get("ty", THREAD_Y)
    top = top_of(D, h, ty)
    style = eff_style(st.get("style"), st.get("pk"))
    dl = st.get("dl") if st["mode"] == "thread" and st.get("ta", 1) > 0.01 else None
    if dl and style not in PILLS:               # загрузка — всегда капсулой: тонкой нити не хватит места
        style = "pill"
    if st["mode"] == "thread" and (style in PILLS or h <= THREAD_H + 2):
        cr.push_group()
        ph, PD = h, D
        if dl and h > PILL_H:
            ph, PD = float(PILL_H), dict(D, shadow=None)   # тень — одна, у всей капсулы с панелью
            dl_hits = paint_dl(cr, x, ty, w, h, dl, col, D)
        if style == "cat":
            hits = paint_cat_pill(cr, x, ty, w, ph, st, col, PD)
        elif style == "ccp":
            hits = paint_cc_pill(cr, x, ty, w, ph, st, col, PD)
        elif style == "pill":
            hits = paint_pill(cr, x, ty, w, ph, st, col, PD)
        else:
            paint_thread(cr, x, top, w, st, col, D)
            hits = []
        if dl and h > PILL_H:
            hits = hits + dl_hits
        # пузырь ▶ рядом с нитью убран (20.10.2026, просьба: «никаких отдельных кнопок рядом
        # с островком, я имел в виду кнопки внутри островка»)
        pat = cr.pop_group()
        ta = st.get("ta", 0.8)
        cr.set_source(pat)
        cr.paint_with_alpha(0.55 if style in PILLS and 0 < ta < 0.3 else 1.0)
        return hits
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
    elif D["shadow"] == "hard" and h > 6:      # жёсткая тень, как у виджетов (SHADOW 5, bg×0.25)
        sh = HARD_SHADOW if h > COMPACT_H + 4 else 3
        cr.save()
        cr.translate(sh, sh)
        pill_path(cr, x, w, h, D)
        cr.set_source_rgba(*(c * 0.25 for c in col["bg"]), 0.72)
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
    elif mode == "compact" and kind == "nudge":
        paint_nudge_compact(cr, x, w, h, d, col, a, D)
    elif mode == "compact" and D.get("ios"):
        ios_compact(cr, x, w, h, kind, d, acts, col, a)
    elif mode == "compact":
        icon, text, ck = act_line(kind, d)
        mid = h / 2
        pix_glyph(cr, icon, x + 22, mid, ck_rgb(ck, col), a) or put_text(cr, icon, 16, x + 14, mid, ck_rgb(ck, col), a)
        put_text(cr, text, 8, x + 38, mid, col["on_surface"], a, maxw=w - 38 - 14 - 12 * (len(acts) - 1))
        for i, (k, _dd) in enumerate(acts[1:3]):
            c = act_color(k, col)
            cr.rectangle(x + w - 14 - i * 12, mid - 2, 4, 4)
            cr.set_source_rgba(*c, a)
            cr.fill()
        pr = progress(kind, d)
        if pr is not None and kind == "flash":  # индикатор: дорожка и уровень толще, ровно в пиксели
            bw = int(w - 24)
            cr.rectangle(int(x + 12), int(h - 5), bw, 2)
            cr.set_source_rgba(*col["on_surface"], 0.18 * a)
            cr.fill()
            cr.rectangle(int(x + 12), int(h - 5), int(bw * max(0.0, min(1.0, pr))), 2)
            cr.set_source_rgba(*col["primary"], a)
            cr.fill()
        elif pr is not None:
            cr.rectangle(x + 12, h - 3, (w - 24) * pr, 1)
            cr.set_source_rgba(*col["primary"], 0.7 * a)
            cr.fill()
    elif D.get("ios"):
        hits = paint_card_ios(cr, x, w, h, kind, d, pages, col, a, (len(pages), ci))
    elif D.get("line"):
        hits = paint_skeet_card(cr, x, w, h, kind, d, pages, col, a, ci)
    else:
        hits = paint_card(cr, x, w, h, kind, d, pages, col, a, ci)
    cr.restore()
    cr.restore()
    return [((hx, hy + top, hw, hh), act) for (hx, hy, hw, hh), act in hits]


def paint_thread(cr, x, top, w, st, col, D):
    """Нить: ровная сглаженная линия или точки, тусклая (thread_alpha). Прогресс помидора или
    трека — та же линия ярче, цветом дела. ta=0 — спрятана (видео), наведение проявляет."""
    import cairo
    a = st.get("ta", 0.8)
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
        base = cairo.SolidPattern(*col["primary"], min(1.0, a * 2.4))
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


DL_ARROW = ("..##..", "..##..", "..##..", "######", ".####.", "..##..")   # ↓ пикселями; ↑ — он же сверху вниз


def dl_name(dl):
    if dl.get("up"):
        return "%s — отправка" % dl["name"]
    return dl.get("name") or "загрузка"


def paint_dl(cr, x, top, w, h, dl, col, D):
    """Загрузка или отправка (island_dl.py) — панель под живой капсулой, одним телом с ней.
    20.10.2026, пользователь (по образцу окна «Загрузки»): «квадратные полоски, которые заполняются;
    название, чтобы знать, что именно загружается или выгружается; снизу — сколько процентов,
    сколько из скольки, скорость и сколько осталось». Всего неизвестно (Telegram, curl, отправка) —
    по клеткам бежит отрезок. Щелчок по панели — папка файла."""
    import cairo
    import island_dl
    ios = bool(D.get("ios"))
    cr.save()
    cr.set_antialias(cairo.ANTIALIAS_GOOD if ios else cairo.ANTIALIAS_NONE)
    if ios:                                         # тело: капсула сверху + панель — одно
        r = PILL_H / 2
        cr.new_path()
        cr.arc(x + w - r, top + r, r, -math.pi / 2, 0)
        cr.arc(x + w - r, top + h - r, r, 0, math.pi / 2)
        cr.arc(x + r, top + h - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, top + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.92)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.stroke()
    else:
        pill_shape(cr, x, top, w, h, col, D)
    a0, ah = top + PILL_H, h - PILL_H
    if ah < DL_H * 0.8 or w < DL_W * 0.8:           # панель ещё раскрывается — пусто
        cr.restore()
        return []
    cr.rectangle(x, a0, w, ah)
    cr.clip()
    acc, on, var = col["primary"], col["on_surface"], col["on_surface_variant"]
    if ios:
        on = var = (1, 1, 1)
    x0, x1 = x + DL_PAD, x + w - DL_PAD
    if not ios:
        x0, x1 = int(x0), int(x1)
    # 1. значок ↓/↑ и имя (+ ещё N справа)
    y1 = int(a0 + 11)
    up = bool(dl.get("up"))
    for j, row in enumerate(DL_ARROW):
        rr = j if not up else len(DL_ARROW) - 1 - j
        for i, ch in enumerate(row):
            if ch == "#":
                cr.rectangle(x0 + i, y1 - 3 + rr, 1, 1)
    cr.set_source_rgba(*acc, 1)
    cr.fill()
    more = "+%d" % (dl["n"] - 1) if dl.get("n", 1) > 1 else ""
    mw = text_w(cr, more, 8) if more else 0
    put_text(cr, dl_name(dl), 8, x0 + 11, y1, on, 0.95, maxw=x1 - x0 - 11 - (mw + 8 if mw else 0))
    if more:
        put_text(cr, more, 8, x1 - mw, y1, var, 0.6)
    # 2. клетки
    sq, gap = DL_SQ, DL_SQ_GAP
    n = max(1, int((x1 - x0 + gap) // (sq + gap)))
    sx = x0 + int((x1 - x0 - (n * (sq + gap) - gap)) / 2)
    y2 = int(a0 + 22)
    pr = 1.0 if dl.get("done") else dl.get("pr")
    if pr is not None:
        lit = set(range(int(n * max(0.0, min(1.0, pr)) + 1e-6)))
    else:                                           # бегущий отрезок из 5 клеток
        run = 5
        head = int(time.monotonic() * 14) % (n + run)
        lit = set(range(max(0, head - run), min(n, head)))
    for i in range(n):
        cr.rectangle(sx + i * (sq + gap), y2, sq, sq)
        if i in lit:
            cr.set_source_rgba(*acc, 1)
        else:
            cr.set_source_rgba(*on, 0.13)
        cr.fill()
    # 3. цифры: «72% · 1 КБ из 1 КБ · 0 КБ/с · ещё 4 с»
    txt = "готово" if dl.get("done") else island_dl.stats(dl)
    put_text(cr, txt, 8, x0, int(a0 + 39), var, 0.8, maxw=x1 - x0)
    cr.restore()
    return [((x, a0, w, ah), ("dl", "open"))]


PILL_PX, PILL_GAP, PILL_PAD, PILL_MAX = 12, 6, 11, 280
CALL_PAD = (5, 5)             # звонок: отступ слева до значка, справа — до кнопки микрофона
CALL_GAP = 26                   # звонок: значок | время | микрофон — просторно, края прижаты (20.10.2026)
MUSIC_MAXW = 130


def pill_parts(acts, col):
    """Живая капсула (19.10.2026, просьба: «если телеграм звонок активный — значок тг,
    длительность и статус микро с возможностью нажать… если музыка — её»): главное дело
    (последний открытый блок с инфо, иначе первое по порядку настроек); дел нет — точка и часы.
    Точек других дел справа больше нет (20.10.2026, просьба: «что это за точка справа? Может
    уберем ее?»). [(вид, значение, цвет)]: g — значок, t — текст, mic — кнопка микрофона,
    bars — полоски музыки, dot — точка слева."""
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
        # 20.10.2026, просьба: «вместо иконки — иконку приложения, откуда звук: YouTube — ютуба,
        # Яндекс Музыка — её»). Строка песни — только у котика; здесь название и время, как у
        # трека или видео («оставляем как было… просто название и продолжительность»).
        app = player_app(d)
        parts = [("app", app, c) if app else ("bars", d.status == "Playing", c), ("tm", d.title or "—", None)]
        # время есть всегда — ширина капсулы не прыгает на паузе и перемотке (20.10.2026, просьба:
        # «должно быть в одном положении всегда»)
        parts.append(("tt", "%s / %s" % (mmss(d.position()), mmss(d.length) if d.length else "--:--"), None))
    elif kind == "nudge":
        parts = [("g", G_NUDGE, NUDGE_RGB), ("t", mmss(nudge_sec(d)), None)]
    else:
        icon, text, ck = act_line(kind, d)
        parts = [("g", icon, c), ("t", text, None)]
    return parts


# Откуда звук → значок (имя в теме значков; youtube — свой пиксельный)
APP_BY_SITE = (("youtube.com", "youtube"), ("youtu.be", "youtube"), ("music.yandex", "yandexmusic"),
               ("open.spotify", "spotify-launcher"), ("soundcloud", "soundcloud"), ("twitch.tv", "twitch"))
APP_BY_PROC = {"yandexmusic": "yandexmusic", "spotify": "spotify-launcher", "zen-bin": "zen-browser",
               "zen": "zen-browser", "firefox": "firefox", "helium": "helium-browser",
               "chromium": "chromium", "telegram-deskto": "org.telegram.desktop", "Telegram": "org.telegram.desktop",
               "mpv": "mpv", "vlc": "vlc", "youtube-music-d": "youtube-music-desktop-app"}
YT_BMP = ("..############..", ".##############.", "################", "######WW########",
          "######WWWW######", "######WWWWWW####", "######WWWWWW####", "######WWWW######",
          "######WW########", "################", ".##############.", "..############..")
_APPICON = {}


def player_app(p):
    """Имя значка приложения плеера: сначала по адресу (вкладка браузера), иначе по процессу
    (pid в имени шины MPRIS: chromium.instance123, firefox.instance_1_123)."""
    url = str((getattr(p, "meta", None) or {}).get("xesam:url") or "")
    for site, icon in APP_BY_SITE:
        if site in url:
            return icon
    name = getattr(p, "name", "") or ""
    if name in _APPICON:
        return _APPICON[name]
    import re
    m = re.search(r"instance(?:_\d+_)?(\d+)$", name)
    comm = ""
    if m:
        # номер в имени шины бывает чужим: Zen 20.10.2026 назвался instance_1_836936, а живёт
        # pid 1273937 (значка в капсуле не было) — сперва спросить у D-Bus, чей это плеер
        for pid in (bus_pid(name), m.group(1)):
            try:
                comm = open("/proc/%s/comm" % pid).read().strip()
                break
            except OSError:
                pass
    else:
        comm = name.rsplit(".", 1)[-1]
    icon = APP_BY_PROC.get(comm)
    if icon is None and m is None:
        icon = APP_BY_PROC.get(name.split(".")[3] if name.count(".") >= 3 else "")
    if icon and icon != "youtube" and app_pixbuf(icon) is None:
        icon = None
    _APPICON[name] = icon
    return icon


def bus_pid(name):
    """pid владельца имени на сессионной шине (или None)."""
    try:
        from gi.repository import Gio, GLib
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        return int(bus.call_sync("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                 "GetConnectionUnixProcessID", GLib.Variant("(s)", (name,)),
                                 GLib.VariantType("(u)"), Gio.DBusCallFlags.NONE, 500, None).unpack()[0])
    except Exception:
        return None


def app_pixbuf(icon):
    if ("pb", icon) not in _APPICON:
        pb = None
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            from gi.repository import Gtk
            pb = Gtk.IconTheme.get_default().load_icon(icon, 16, Gtk.IconLookupFlags.FORCE_SIZE)
        except Exception:
            pb = None
        _APPICON[("pb", icon)] = pb
    return _APPICON[("pb", icon)]


def draw_app_icon(cr, icon, x, y, a=1.0):
    """Значок 16×16 без сглаживания (пиксельные значки темы Jarvis-Pixel); YouTube — свой."""
    import cairo
    if icon == "youtube":
        for r, row in enumerate(YT_BMP):
            for c, ch in enumerate(row):
                if ch != ".":
                    cr.rectangle(x + c, y + 2 + r, 1, 1)
                    cr.set_source_rgba(*((1, 1, 1) if ch == "W" else (1.0, 0.0, 0.2)), a)
                    cr.fill()
        return
    pb = app_pixbuf(icon)
    if pb is None:
        return
    from gi.repository import Gdk
    cr.save()
    Gdk.cairo_set_source_pixbuf(cr, pb, x, y)
    cr.get_source().set_filter(cairo.FILTER_NEAREST)
    cr.paint_with_alpha(a)
    cr.restore()


# Время трека в живой капсуле — тем же шрифтом, но тусклее и с отступом от названия
# (20.10.2026, просьба: мелкие цифры 3×5 — «слишком мелко», «просто небольшое пространство»)
TT_GAP = 6


def pill_text(cr, text, maxw=None, px=None):
    """Текст капсулы: Inter SemiBold, цифры одной ширины (секунды не дёргают капсулу)."""
    import gi
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import Pango
    global FONT
    keep, FONT = FONT, "Inter"
    cr.save()
    font_opts(cr)                                # сглаженный, даже если вид пиксельный
    lay = layout(cr, text, px or PILL_PX)
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


def pill_ios(D):
    """Капсула как в iOS (чёрная, Inter) — только при виде «iOS». 20.10.2026, просьба: «вид
    таймера похож на стиль ios, хотя выбран системный» — до этого она была такой при любом виде."""
    return D is None or bool(D.get("ios"))


def pill_lay(cr, text, maxw=None, D=None, glyph=False, px=None):
    """Надпись капсулы: iOS — Inter (pill_text), иначе шрифт системы, как у капсулы котика."""
    if pill_ios(D):
        return pill_text(cr, text, maxw, px)
    from gi.repository import Pango
    use_font(D)
    lay = layout(cr, text, 16 if glyph else 8)
    if maxw:
        lay.set_width(int(maxw * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    return lay


def part_w(cr, p, D=None):
    k, v, _c = p
    if k == "dot":
        return 6
    if k == "sdot":
        return 5
    if k == "bars":
        return 10
    if k == "app":
        return 16
    if k == "g" and v == G_NUDGE and not pill_ios(D):
        return len(PIX_BMP[G_NUDGE][0])
    if k == "tt":                       # место под самое широкое время этой длины: 00:00 / 00:00
        right = v.split(" / ")[-1]
        ref = re.sub(r"\d", "0", right if ":" in right and right[0] != "-" else "00:00")
        return TT_GAP + max(pill_lay(cr, v, None, D).get_pixel_size()[0],
                            pill_lay(cr, ref + " / " + ref, None, D).get_pixel_size()[0])
    if k == "mic":
        return 18
    lay = pill_lay(cr, v, MUSIC_MAXW if k == "tm" else None, D, k == "g")
    if k in ("g", "t") and not pill_ios(D):  # по видимой части: у MDI и пиксельных цифр поля
        return lay_ink(lay)[1]
    return lay.get_pixel_size()[0]


_INK = {}


def lay_ink(lay):
    """(x, ширина) закрашенных столбцов строки — по пикселям: у значков Nerd Font рамка
    начертания бывает на пиксель шире видимого (WhatsApp: 14 вместо 13), и зазоры выходили
    разные (20.10.2026). Кэш по тексту и шрифту."""
    key = (lay.get_text(), lay.get_font_description().to_string() if lay.get_font_description() else "")
    if key in _INK:
        return _INK[key]
    ie = lay.get_pixel_extents()[0]
    res = (ie.x, ie.width)
    try:
        import cairo
        from gi.repository import PangoCairo
        w, h = max(1, ie.x + ie.width + 2), max(1, ie.y + ie.height + 2)
        sf = cairo.ImageSurface(cairo.FORMAT_A8, w, h)
        c = cairo.Context(sf)
        font_opts(c)                            # как в капсуле: без сглаживания у пиксельного шрифта
        PangoCairo.update_layout(c, lay)
        PangoCairo.show_layout(c, lay)
        sf.flush()
        st, data = sf.get_stride(), bytes(sf.get_data())
        cols = [x for x in range(w) if any(data[y * st + x] > 96 for y in range(h))]
        if cols:
            res = (cols[0], cols[-1] - cols[0] + 1)
    except Exception:
        pass
    _INK[key] = res
    return res


def pill_gap(parts):
    """Зазор между частями капсулы: у звонка шире (20.10.2026, просьба: «не ровная… добавь места
    между элементами»)."""
    return CALL_GAP if any(p[0] == "mic" for p in parts) else PILL_GAP


def pill_pads(parts):
    """Поля капсулы (слева, справа). У звонка справа меньше: фон кнопки микрофона бледный, и
    поле на глаз казалось шире левого (20.10.2026, просьба: «справа от иконки микрофона есть место,
    как будто оно большое… сделай подлиннее»)."""
    return CALL_PAD if any(p[0] == "mic" for p in parts) else (PILL_PAD, PILL_PAD)


def pill_w(cr, acts, col=None, D=None):
    parts = pill_parts(acts, col)
    w = sum(pill_pads(parts)) + sum(part_w(cr, p, D) for p in parts) + pill_gap(parts) * (len(parts) - 1)
    return float(max(PILL_W, min(PILL_MAX, int(math.ceil(w / 2.0)) * 2)))


def pill_edge(col):
    """Рамка капсул (живая нить, котик, компакт): тусклый акцент обоев. 20.10.2026, просьба: «сделай рамки ещё чуть тусклее» — было primary на 45 % в фон при 0.9."""
    return (*mix_rgb(col["primary"], col["bg"], 0.62), 0.8)


def pill_shape(cr, x, top, w, h, col, D):
    """Тело капсулы: iOS — чёрная скруглённая; иначе — прямоугольник цвета системы с тусклой
    акцентной рамкой (как у капсулы котика)."""
    import cairo
    ios = pill_ios(D)
    cr.set_antialias(cairo.ANTIALIAS_GOOD if ios else cairo.ANTIALIAS_NONE)
    cr.new_path()
    if ios:
        r = h / 2
        cr.arc(x + w - r, top + r, r, -math.pi / 2, math.pi / 2)
        cr.arc(x + r, top + r, r, math.pi / 2, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.92)
    else:
        if D and D.get("shadow") == "hard":    # тень 3 px вправо-вниз, как у виджетов
            cr.rectangle(x + 3, top + 3, w, h)
            cr.set_source_rgba(*(c * 0.25 for c in col["bg"]), 0.72)
            cr.fill()
        cr.rectangle(x, top, w, h)
        cr.set_source_rgba(*fill_rgba(D, col)[:3], 0.94)
    cr.fill_preserve()
    cr.set_line_width(1 if ios else 2)
    if ios:
        cr.set_source_rgba(1, 1, 1, 0.08)
    else:
        cr.set_source_rgba(*pill_edge(col))
    cr.stroke()


def paint_pill(cr, x, top, w, h, st, col, D=None):
    """Нить-капсула с живым содержимым (pill_parts) в виде D. Видна целиком, без
    «тусклости». Возвращает щелчковые зоны (кнопка микрофона звонка)."""
    import cairo
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    hits = []
    if st.get("ta", 1) <= 0.01 or w < 4 or h < 2:
        return hits
    ios = pill_ios(D)
    cr.save()
    pill_shape(cr, x, top, w, h, col, D)
    r = h / 2
    ink = (1, 1, 1) if ios else col["on_surface"]
    parts = pill_parts(st["acts"], col)
    gap = pill_gap(parts)
    pl, pr_ = pill_pads(parts)
    need = pl + pr_ + sum(part_w(cr, p, D) for p in parts) + gap * (len(parts) - 1)
    if w >= min(need, PILL_MAX) * 0.85 and h >= PILL_H * 0.6:   # пока капсула растёт — пусто
        cr.rectangle(x, top, w, h)
        cr.clip()
        cx = x + max(pl, (w - need) / 2 + pl)
        cy = top + r
        if not ios:
            cx = float(int(cx))
        for p in parts:
            k, v, c = p
            pw = part_w(cr, p, D)
            if k in ("dot", "sdot") and not ios:          # пиксельный квадратик
                cr.rectangle(int(cx + pw / 2 - 2), int(cy - 2), 4, 4)
                cr.set_source_rgba(*(c if c != (1, 1, 1) else ink), 1)
                cr.fill()
            elif k in ("dot", "sdot"):
                cr.arc(cx + pw / 2, cy, 2.6 if k == "dot" else 2.0, 0, 2 * math.pi)
                cr.set_source_rgba(*c, 1 if k == "dot" else 0.8)
                cr.fill()
            elif k == "g" and v == G_NUDGE and not ios:
                pix_glyph(cr, v, int(cx + pw / 2), int(cy), c or ink, 1)
            elif k == "g" and v == G_PAUSE and not ios:
                # пауза пикселями: глиф MDI без сглаживания на 8 px ложился криво (20.10.2026,
                # Просьба: «иконка паузы кривенькая, когда pomo на паузе»)
                x0, y0 = int(cx + pw / 2) - 3, int(cy) - 4
                cr.rectangle(x0, y0, 2, 8)
                cr.rectangle(x0 + 4, y0, 2, 8)
                cr.set_source_rgba(*(c or ink), 1)
                cr.fill()
            elif k == "app":
                playing = st["acts"][0][1].status == "Playing" if st["acts"] else True
                draw_app_icon(cr, v, int(cx), int(cy - 8), 1.0 if playing else 0.35)   # 0.5→0.35, 20.10
            elif k == "bars":
                hs = (5, 9, 6) if v else (3, 3, 3)
                for i, bh in enumerate(hs):
                    cr.rectangle(int(cx) + i * 4, int(cy + 4.5 - bh), 2, bh)
                cr.set_source_rgba(*c, 1)
                cr.fill()
            elif k == "mic":
                mc = (1.0, 0.36, 0.36) if v else CALL_GREEN
                if ios:
                    cr.arc(cx + 9, cy, 8.5, 0, 2 * math.pi)
                else:
                    cr.rectangle(int(cx), int(cy - 8), 18, 16)
                cr.set_source_rgba(*mc, 0.22)
                cr.fill()
                lay = pill_lay(cr, G_MIC_OFF if v else G_MIC, None, D, True)
                gw, gh = lay.get_pixel_size()
                cr.move_to(cx + 9 - gw / 2, cy - gh / 2)
                cr.set_source_rgba(*mc, 1)
                PangoCairo.show_layout(cr, lay)
                hits.append(((cx - 3, 0, pw + 6, top + h + 4), ("call", "mute")))
            else:
                lay = pill_lay(cr, v, MUSIC_MAXW if k == "tm" else None, D, k == "g")
                tw, th = lay.get_pixel_size()
                tx = cx + (TT_GAP if k == "tt" else 0)
                ty_ = cy - th / 2 if ios else int(cy - th / 2)
                if not ios and k in ("g", "t"):
                    # глиф — с его видимого края; цифры времени — по середине начертания
                    # (по строке они сидели на пиксель выше значков)
                    ie = lay.get_pixel_extents()[0]
                    tx -= lay_ink(lay)[0]
                    if k == "t":
                        ty_ = int(round(cy - ie.y - ie.height / 2))
                cr.move_to(tx, ty_)
                cr.set_source_rgba(*(c or ink), 1 if k == "g" else 0.5 if k == "tt" else 0.92)
                PangoCairo.show_layout(cr, lay)
            cx += pw + gap
    cr.restore()
    return hits


BUBBLE_GAP = 6
BUBBLE_KEEP = 600            # пузырь ▶ у нити держится, пока пауза не дольше 10 минут


def bubble_box(x, ty, w, h, style):
    """(x, y, сторона) пузыря ▶ справа от нити/капсулы."""
    s = PILL_H if style in PILLS else 18
    return (x + w + BUBBLE_GAP, max(0.0, ty + h / 2 - s / 2), s)


def paint_bubble(cr, x, ty, w, h, st, col, D):
    """Пузырь ▶ у нити, пока музыка на паузе (20.10.2026, пользователь одобрил из списка идей
    AngelOS): щелчок — играть дальше. Вид — как у капсулы: iOS круглый чёрный, иначе квадрат
    цвета системы с тусклой акцентной рамкой."""
    import cairo
    if not st.get("bubble") or w < 4:
        return []
    bx, by, s = bubble_box(x, ty, w, h, eff_style(st.get("style"), st.get("pk")))
    ios = pill_ios(D)
    cr.save()
    if ios:
        cr.set_antialias(cairo.ANTIALIAS_GOOD)
        cr.arc(bx + s / 2, by + s / 2, s / 2, 0, 2 * math.pi)
        cr.set_source_rgba(0.02, 0.02, 0.03, 0.92)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(1, 1, 1, 0.08)
        cr.stroke()
    else:
        bx, by = int(bx), int(by)
        pill_shape(cr, bx, by, s, s, col, D)
    lay = pill_lay(cr, G_PLAY, None, D, True)
    gw, gh = lay.get_pixel_size()
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    cr.move_to(int(bx + (s - gw) / 2) + (0 if ios else 1), int(by + (s - gh) / 2))
    cr.set_source_rgba(*act_color("music", col), 1)
    PangoCairo.show_layout(cr, lay)
    cr.restore()
    return [((bx - 3, 0, s + 6, by + s + 4), ("music", "Play"))]


# Значки инструментов пикселями ('#' — точка), 20.10.2026, просьба: «остальные тоже нарисуй
# пикселями, надо сохранять пиксельный стиль». Пипетка, рамка снимка, лист заметки, часы помидора.
PIX_BMP = {
    G_PICK: (
        "........###.",
        ".......#####",
        "....#..#####",
        ".....#######",
        "......####..",
        ".....##.#...",
        "....##......",
        "...##.......",
        "..##........",
        ".##.........",
        "#...........",
    ),
    G_SHOT: (
        "...##.........",
        "...##.........",
        "...##.........",
        "###########...",
        "###########...",
        "...##....##...",
        "...##....##...",
        "...##....##...",
        "...##....##...",
        "...###########",
        "...###########",
        ".........##...",
        ".........##...",
        ".........##...",
    ),
    G_MEMO: (
        "######....",
        "######.#..",
        "######.##.",
        "######.###",
        "##########",
        "##########",
        "##......##",
        "##########",
        "##......##",
        "##########",
        "##########",
        "##########",
    ),
    G_TOOLS: (                  # ящик с инструментами — значок вкладки «Инструменты»
        ".....####.....",
        "....######....",
        "....##..##....",
        "##############",
        "##############",
        "##..........##",
        "##....##....##",
        "######..######",
        "##....##....##",
        "##..........##",
        "##############",
        "##############",
    ),
    G_POMO: (
        "##########",
        ".########.",
        "..######..",
        "...####...",
        "....##....",
        "....##....",
        "...#..#...",
        "..#....#..",
        ".#..##..#.",
        ".#.####.#.",
        ".########.",
        "##########",
    ),
}


def put_glyph(cr, glyph, px, cx, cy, rgb, a):
    """Значок по центру ВИДИМЫХ пикселей (ink), а не рамки шрифта: у глифов MDI рамка шире
    рисунка, и put_text(center=True) сдвигал их в квадратике (20.10.2026)."""
    import gi
    gi.require_version("PangoCairo", "1.0")
    from gi.repository import PangoCairo
    lay = layout(cr, glyph, px)
    ink, _log = lay.get_pixel_extents()
    if ink.width <= 0 or ink.height <= 0:
        return put_text(cr, glyph, px, cx, cy, rgb, a, center=True)
    cr.move_to(int(round(cx - ink.width / 2)) - ink.x, int(round(cy - ink.height / 2)) - ink.y)
    cr.set_source_rgba(*rgb, a)
    PangoCairo.show_layout(cr, lay)
    return ink.width


PIX_BMP[G_NUDGE] = ("############", "#..........#", "#.#........#", "#..#.......#", "#...#......#",
                    "#..#.......#", "#.#..####..#", "#..........#", "############")


def pix_glyph(cr, glyph, cx, cy, rgb, a):
    """Значки плеера пикселями по целой сетке. 20.10.2026, просьба: «кнопка паузы кривая» —
    глиф MDI без сглаживания при дробном центре давал полоски 2 и 3 px. → нарисован ли."""
    if glyph == G_PAUSE:
        px = [(0, 0, 3, 10), (6, 0, 3, 10)]
    elif glyph == G_PLAY:
        px = [(i, i, 1, 11 - 2 * i) for i in range(6)]
    elif glyph == G_STOP:
        px = [(0, 0, 8, 8)]
    elif glyph in (G_REC, "●"):          # круг 10×10 ступеньками («точка записи кривая»)
        px = [(3, 0, 4, 1), (1, 1, 8, 1), (0, 2, 10, 6), (1, 8, 8, 1), (3, 9, 4, 1)]
    elif glyph == G_NEXT:
        px = [(i, i, 1, 9 - 2 * i) for i in range(5)] + [(5, 0, 2, 9)]
    elif glyph == G_PREV:
        px = [(0, 0, 2, 9)] + [(6 - i, i, 1, 9 - 2 * i) for i in range(5)]
    elif glyph in PIX_BMP:
        px = [(x, y, 1, 1) for y, row in enumerate(PIX_BMP[glyph]) for x, c in enumerate(row) if c == "#"]
    else:
        return False
    w = max(x + pw for x, _y, pw, _h in px)
    h = max(y + ph for _x, y, _w, ph in px)
    x0, y0 = int(round(cx)) - w // 2, int(round(cy)) - h // 2
    for x, y, pw, ph in px:
        cr.rectangle(x0 + x, y0 + y, pw, ph)
    cr.set_source_rgba(*rgb, a)
    cr.fill()
    return True


def button(cr, cx, cy, glyph, col, a, hits, action, big=False):
    if _SK["on"]:
        bw, bh = (34, 24) if big else (28, 22)
        bx, by = int(cx - bw / 2), int(cy - bh / 2)
        sk_box(cr, bx, by, bw, bh, col, a, big)
        pix_glyph(cr, glyph, bx + bw // 2, by + bh // 2, sk_ink(col, big), a) or \
            put_text(cr, glyph, 16, bx + bw // 2, by + bh / 2, sk_ink(col, big), a, center=True)
        hits.append(((bx, by, bw, bh), action))
        return
    r = 14 if big else 11
    cr.arc(cx, cy, r, 0, 2 * math.pi)
    cr.set_source_rgba(*(col["primary"] if big else col["surface_high"]), a * (1 if big else 0.9))
    cr.fill()
    ink = col["on_primary"] if big else col["on_surface"]
    pix_glyph(cr, glyph, cx, cy, ink, a) or put_text(cr, glyph, 16, cx, cy, ink, a, center=True)
    hits.append(((cx - r, cy - r, 2 * r, 2 * r), action))


def mic_sub(d):
    """«Микрофон включён · 80 %» (20.10.2026, просьба: «можно здесь также показывать громкость
    микрофона»)."""
    t = "Микрофон выключен" if d["muted"] else "Микрофон включён"
    return t + (" · %d %%" % d["vol"] if d.get("vol") is not None else "")


def mic_slider(cr, x, y, w, d, col, a, hits):
    """Громкость микрофона системы полосой; щелчок по ней ставит громкость (шаг 5 %)."""
    pr = max(0.0, min(1.0, d["vol"] / 100))
    ga = 0.45 * a if d["muted"] else a
    if _SK["on"]:
        sk_slider(cr, x, y, w, 6, pr, col, ga)
    else:
        cr.rectangle(x, y + 2, w, 2)
        cr.set_source_rgba(*col["surface_high"], a)
        cr.fill()
        cr.rectangle(x, y + 2, w * pr, 2)
        cr.set_source_rgba(*col["primary"], ga)
        cr.fill()
    seg = w / 20
    for i in range(20):
        hits.append(((x + i * seg, y - 6, seg, 18), ("call", "vol:%d" % ((i + 1) * 5))))


def paint_card(cr, x, w, h, kind, d, acts, col, a, card_i):
    hits = []
    pad = 18
    icon, text, ck = act_line(kind, d)
    # страницы: квадратики сверху справа цветом дела, щелчок переключает (колесо — тоже)
    for i, (k, _dd) in enumerate(acts if len(acts) > 1 and not _SK["on"] else []):
        c = act_color(k, col)
        bx = x + w - pad - 6 - (len(acts) - 1 - i) * 14
        cr.rectangle(bx, 14, 6, 6)
        cr.set_source_rgba(*c, a if i == card_i else 0.35 * a)
        cr.fill()
        hits.append(((bx - 4, 8, 14, 18), ("page", i)))
    if kind == "cat":
        paint_cat_card(cr, x, w, h, d, col, a, hits, False)
        return hits
    if kind == "shelf":
        paint_shelf(cr, x, w, h, d, col, a, hits, False)
        return hits
    if kind in SYS_PAGES:
        paint_sys(cr, x, w, h, kind, d, col, a, hits, False)
        return hits
    if kind in ("clip", "tools"):
        (paint_clip if kind == "clip" else paint_tools)(cr, x, w, h, d if kind == "clip" else kind, col, a, hits, False)
        return hits
    pr = progress(kind, d)
    by = h - 26 - (MUSIC_EQ[2] if kind == "music" else 0)
    if kind == "music":
        # 20.10.2026, просьба: «квадратик с обложкой, будь то видео или трек» и «эквалайзер в самом
        # низу, на всю длину, невысокий». Обложка слева (щелчок — пауза), квадратики cava под кнопками.
        cat = _CAT["s"] or {}
        cs, cy0 = MUSIC_COVER, 12
        draw_cover(cr, x + pad, cy0, cs, cat, col, a)
        if cat.get("art24") is None:
            put_text(cr, G_NOTE, 16, x + pad + cs / 2, cy0 + cs / 2, ck_rgb(ck, col), a, center=True)
        hits.append(((x + pad, cy0, cs, cs), ("music", "PlayPause")))
        tx = x + pad + cs + 12
        put_text(cr, d.title or "—", 16, tx, 28, col["on_surface"], a, maxw=x + w - pad - tx - (0 if _SK["on"] else 50))
        lk = like_btn(cr, x + w - pad - 5, 48, cat, col, a, hits)
        put_text(cr, d.artist or d.identity, 8, tx, 48, col["on_surface_variant"], 0.85 * a,
                 maxw=x + w - pad - tx - (22 if lk else 0))
        music_eq(cr, x + pad, h - 10, w - 2 * pad, cat, col, a, d.status == "Playing")
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
        pix_glyph(cr, "●", x + pad + 6, 34, col["error"], a)
        put_text(cr, mmss(d["sec"]), 24, x + pad + 22, 34, col["on_surface"], a)
        put_text(cr, ("Пауза · " if d["paused"] else "Идёт запись · ") + d["mode"], 8, x + pad, 56,
                 col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        c = x + w - pad - 50
        button(cr, c, by, G_PLAY if d["paused"] else G_PAUSE, col, a, hits, ("rec", "pause"), big=True)
        button(cr, c + 36, by, G_STOP, col, a, hits, ("rec", "halt"))
    elif kind == "call":
        put_text(cr, d["icon"], 16, x + pad + 8, 30, CALL_GREEN, a, center=True)
        put_text(cr, d["app"] + " · звонок", 16, x + pad + 26, 28, col["on_surface"], a, maxw=w - 2 * pad - 26 - 70)
        put_text(cr, mic_sub(d), 8, x + pad + 26, 46,
                 col["error"] if d["muted"] else col["on_surface_variant"], 0.85 * a)
        if d.get("vol") is not None:
            mic_slider(cr, x + pad, by - 25, w - 2 * pad, d, col, a, hits)
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
        button(cr, c + 36, by, G_PLUS, col, a, hits, ("timer", "add"))
    elif kind == "timer":
        put_text(cr, G_TIMER, 16, x + pad + 8, 32, ck_rgb(ck, col), a, center=True)
        put_text(cr, "Таймер", 16, x + pad + 26, 30, col["on_surface"], a)
        put_text(cr, "«+» — новый таймер: виджет timer.exe на столе, звенит hub.", 8, x + pad, 62,
                 col["on_surface_variant"], 0.85 * a, maxw=w - 2 * pad)
        button(cr, x + w - pad - 14, by, G_PLUS, col, a, hits, ("timer", "add"), big=True)
    elif kind == "nudge":
        paint_nudge(cr, x, w, h, d, col, a, False)
    elif kind == "prefs":
        paint_prefs(cr, x, w, h, d, col, a, hits, False)
    else:
        put_text(cr, icon, 16, x + pad + 8, h / 2, ck_rgb(ck, col), a, center=True)
        put_text(cr, text, 16, x + pad + 26, h / 2, col["on_surface"], a, maxw=w - 2 * pad - 26)
    if pr is not None and _SK["on"]:          # Skeet: полоса-ползунок в рамке, градиент акцента
        sk_slider(cr, x + pad, by - 25, w - 2 * pad, 6, pr, col, a)
    elif pr is not None:
        cr.rectangle(x + pad, by - 22, w - 2 * pad, 2)
        cr.set_source_rgba(*col["surface_high"], a)
        cr.fill()
        cr.rectangle(x + pad, by - 22, (w - 2 * pad) * pr, 2)
        cr.set_source_rgba(*col["primary"], a)
        cr.fill()
    return hits


PREFS = (("design", "Вид", (("auto", "Как система"), ("ios", "iOS"))),
         ("thread_style", "Нить", (("line", "Линия"), ("dots", "Точки"), ("pill", "Живая"))),
         ("thread_alpha", "Яркость", (("0.2", "Low"), ("0.8", "High"))),   # как в Настройках (20.10.2026)
         ("pop_sec", "Держать", (("0.7", "0,7 с"), ("1.5", "1,5 с"), ("2.5", "2,5 с"), ("4.0", "4 с"),
                                 ("6.0", "6 с"))))


def paint_prefs(cr, x, w, h, d, col, a, hits, ios):
    """Страница «Настройки» (20.10.2026, просьба: «зайдя в островок, сразу можем переключить и
    стиль островка, и вид линии»): ряды отрезков — вид, нить, её яркость, сколько держать раскрытым.
    Щелчок пишет настройку (island.py set), как Настройки → Waybar."""
    d = d or {}
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    lw = 64
    if _SK["on"]:                             # в рамке группы — по центру
        bh, step = 22, 30
        y = int((h - (len(PREFS) * step - (step - bh))) / 2)
    else:                                     # под точками страниц сверху справа
        bh, step = 20, 27
        y = 34
    for key, label, opts in PREFS:
        cur = d.get(key)
        if key == "pop_sec":
            cur = "%.1f" % float(cur or 2.5)
        elif key == "thread_alpha":
            cur = "0.2" if float(cur if cur is not None else 0.8) < 0.3 else "0.8"
        put_text(cr, label, 12 if ios else 8, x + pad, y + bh / 2, dim, 0.9 * a)
        gx, gw = x + pad + lw, w - 2 * pad - lw
        gap = 6
        bw = (gw - gap * (len(opts) - 1)) / len(opts)
        for i, (k, name) in enumerate(opts):
            bx = int(gx + i * (bw + gap))
            ww = int(gx + (i + 1) * bw + i * gap) - bx
            on = k == cur
            if _SK["on"]:
                sk_box(cr, bx, y, ww, bh, col, a, on)
                ink = sk_ink(col, on)
            elif ios:
                rrect(cr, bx, y, ww, bh, bh / 2)
                cr.set_source_rgba(1, 1, 1, (0.85 if on else 0.1) * a)
                cr.fill()
                ink = (0.05, 0.05, 0.05) if on else fg
            else:
                cr.rectangle(bx, y, ww, bh)
                cr.set_source_rgba(*(col["primary"] if on else col["surface_high"]), 0.9 * a)
                cr.fill()
                ink = col["on_primary"] if on else fg
            put_text(cr, name, 11 if ios else 8, bx + ww // 2, y + bh / 2, ink, a, maxw=ww - 4, center=True)
            hits.append(((bx, y, ww, bh), ("prefs", "%s=%s" % (key, k))))
        y += step


# ─────────── «Центр», Wi-Fi, Bluetooth, Питание (20.10.2026) ───────────
# Просьба: «аналог Центра управления из waybar… Кофеин (ЛКМ), Кофеин + Таурин (ПКМ) — одна
# кнопка; Ночной свет (ЛКМ), спектр по ПКМ; Баланс/Мощность (ЛКМ), Экономия (ПКМ) — одна
# кнопка; круглая аватарка и ник как в «Пуске»; если влезает — система и uptime. Wifi,
# Bluetooth, Питание» (питание — по образцу: замок, выход | сон, перезагрузка, выключение).
# Опрос и команды — island_sys.py (потоками, см. App.poll_sys); здесь только рисование.
G_COFFEE, G_NIGHT = "\U000f0176", "\U000f0594"
G_PROFILE = {"performance": "\U000f04c5", "balanced": "\U000f0f85", "power-saver": "\U000f0f86"}
PROFILE_RU = {"performance": "Мощность", "balanced": "Баланс", "power-saver": "Экономия"}
G_WIFI, G_WIFI_OFF, G_BT, G_BT_OFF = "\U000f05a9", "\U000f05aa", "\U000f00af", "\U000f00b2"
G_WIFI_LV = ("\U000f091f", "\U000f0922", "\U000f0925", "\U000f0928")
G_LOCKED = "\U000f033e"
DEV_GLYPH = (("headset", "\U000f02cb"), ("headphone", "\U000f02cb"), ("audio", "\U000f02cb"),
             ("mouse", "\U000f037d"), ("keyboard", "\U000f030c"), ("phone", "\U000f011c"),
             ("computer", "\U000f0322"), ("watch", "\U000f0897"))
POWER_BTNS = (("lock", "\U000f033e", "Замок"), ("logout", "\U000f0343", "Выход"), None,
              ("suspend", "\U000f0904", "Сон"), ("reboot", "\U000f0709", "Рестарт"),
              ("shutdown", "\U000f0425", "Выкл."))
SPEC_N = 21                     # спектр ночного света: клеток (теплота 0, 5 … 100)
_AV = {}


def kelvin_rgb(k):
    """Цвет света k кельвинов (приближение Таннера Хелланда) — клетки спектра."""
    t = k / 100.0
    r = 1.0 if t <= 66 else min(1.0, 329.698727446 * (t - 60) ** -0.1332047592 / 255)
    g = (99.4708025861 * math.log(t) - 161.1195681661) / 255 if t <= 66 else \
        288.1221695283 * (t - 60) ** -0.0755148492 / 255
    b = 1.0 if t >= 66 else 0.0 if t <= 19 else (138.5177312231 * math.log(t - 10) - 305.0447927307) / 255
    return tuple(max(0.0, min(1.0, v)) for v in (r, g, b))


def warmth_k(w):
    return int(6500 - (6500 - 2800) * max(0, min(100, w)) / 100)


def sys_chip(cr, x, y, w, h, on, col, a, ios, R=None, tone=None):
    """Плашка страниц системы в любом виде: Skeet — sk_box, iOS — капсула, иначе плашка
    акцентом (вкл) или серая. tone — другой цвет «включено» (таурин — tertiary, как в Центре
    управления бара). → цвет надписи на ней."""
    if _SK["on"]:
        sk_box(cr, x, y, w, h, col, a, on)
        if on and tone:                         # полоска снизу — тоном, а не акцентом
            cr.rectangle(x + 2, y + h - 4, w - 4, 2)
            cr.set_source_rgba(*tone, a)
            cr.fill()
        cr.new_path()
        return tuple(c * 0.78 + 0.22 for c in tone) if on and tone else sk_ink(col, on)
    if ios:
        rrect(cr, x, y, w, h, min(h / 2, 12) if R is None else R)
        if on and tone:
            cr.set_source_rgba(*mix_rgb(tone, (1, 1, 1), 0.2), 0.92 * a)
        else:
            cr.set_source_rgba(1, 1, 1, (0.85 if on else 0.12) * a)
        cr.fill()
        return (0.05, 0.05, 0.05) if on else (1, 1, 1)
    rrect(cr, x, y, w, h, R or 0)
    cr.set_source_rgba(*((tone or col["primary"]) if on else col["surface_high"]), 0.9 * a)
    cr.fill()
    return (col["on_tertiary"] if tone else col["on_primary"]) if on else col["on_surface"]


def sys_hl(col, ios):
    """Выделенное в списке (своя сеть, подключённое): светлый акцент, как надписи Skeet."""
    return mix_rgb(col["primary"], (1, 1, 1), 0.45) if ios else sk_ink(col, True)


def draw_avatar(cr, x, y, size, path, col, a):
    """Круглая аватарка из готовой картинки (island_sys.avatar_png) с тонким кольцом."""
    import cairo
    surf = None
    if path:
        try:
            mt = os.path.getmtime(path)
            if _AV.get(path, (None,))[0] != mt:
                _AV[path] = (mt, cairo.ImageSurface.create_from_png(path))
            surf = _AV[path][1]
        except (OSError, cairo.Error):
            surf = None
    cr.new_path()
    cr.arc(x + size / 2, y + size / 2, size / 2, 0, 2 * math.pi)
    if surf:
        cr.save()
        cr.clip()
        sc = size / max(1, surf.get_width())
        cr.translate(x, y)
        cr.scale(sc, sc)
        cr.set_source_surface(surf, 0, 0)
        cr.paint_with_alpha(a)
        cr.restore()
    else:
        cr.set_source_rgba(*col["surface_high"], a)
        cr.fill()
    cr.new_path()
    cr.arc(x + size / 2, y + size / 2, size / 2 + 1, 0, 2 * math.pi)
    cr.set_line_width(1.5)
    cr.set_source_rgba(*(sk_rgb(0.235, col) if _SK["on"] else col["primary"]), 0.9 * a)
    cr.stroke()


def paint_cc(cr, x, w, h, d, col, a, hits, ios):
    """«Центр»: аватар и ник (как в «Пуске»), uptime, справа CPU/температура/память; ниже
    три плитки. ПКМ по плитке — второе действие (Таурин, спектр, Экономия)."""
    d = d or {}
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    f8, f16 = (11, 15) if ios else (8, 16)
    top = 16 if _SK["on"] else 14             # Skeet: ниже заголовка группы на рамке
    av = 40
    draw_avatar(cr, x + pad, top, av, d.get("avatar"), col, a)
    nx = x + pad + av + 12
    name = d.get("name") or ""
    # ник — как label.user в «Пуске»: Skeet — светлый акцент с тенью 1 px, иначе светлый с тенью
    nick = sk_ink(col, True) if _SK["on"] else fg
    put_text(cr, name, f16, nx + 1, top + 13, (0, 0, 0), 0.55 * a, maxw=w / 2 - av)
    put_text(cr, name, f16, nx, top + 12, nick, a, maxw=w / 2 - av)
    if d.get("uptime"):
        put_text(cr, "uptime " + d["uptime"], f8, nx, top + 31, dim, 0.85 * a, maxw=w / 2 - av)
    # система — справа, под точками страниц (в Skeet их нет — выше)
    ry = top + (12 if _SK["on"] else 24 if ios else 22)
    rows = []
    if d.get("cpu") is not None:
        rows.append("CPU %d%%" % d["cpu"] + (" · %d°" % round(d["temp"]) if d.get("temp") else ""))
    if d.get("mem") is not None:
        rows.append("RAM %.1f / %.0f ГиБ" % (d["mem"], d["mem_total"]))
    for i, t in enumerate(rows):
        put_text(cr, t, f8, x + w - pad - text_w(cr, t, f8), ry + i * 15, dim, 0.85 * a)
    ty = top + av + 12
    th = 48
    if d.get("spec"):
        paint_spectrum(cr, x + pad, ty, w - 2 * pad, th, d, col, a, hits, ios)
    else:
        prof = d.get("profile") or "balanced"
        caf, tau = d.get("caffeine"), d.get("taurine")
        # 20.10.2026, просьба: «между Кофеином и Кофеин + Таурином нет визуальной разницы» —
        # как в Центре управления бара: таурин — третьим цветом палитры, подпись «+ Таурин»
        # и молния рядом с чашкой
        tiles = (("caf", G_COFFEE, "Кофеин", "+ Таурин" if tau else "Вкл" if caf else "Выкл", bool(caf)),
                 ("night", G_NIGHT, "Ночной свет",
                  ("%d K" % warmth_k(d.get("warmth", 65))) if d.get("night") else "Выкл", bool(d.get("night"))),
                 ("prof", G_PROFILE.get(prof, G_PROFILE["balanced"]), PROFILE_RU.get(prof, prof or "—"),
                  "Профиль", prof != "balanced"))
        gap = 8
        tw = (w - 2 * pad - 2 * gap) / 3
        for i, (tid, g, title, sub, on) in enumerate(tiles):
            bx = int(x + pad + i * (tw + gap))
            bw = int(x + pad + (i + 1) * tw + i * gap) - bx
            taur = tid == "caf" and tau
            ink = sys_chip(cr, bx, ty, bw, th, on, col, a, ios, R=14 if ios else 0,
                           tone=col["tertiary"] if taur else None)
            if d.get("loading"):
                ink = dim
            put_glyph(cr, g, 16, bx + 18, ty + th / 2, ink, a)
            put_text(cr, title, f8, bx + 34, ty + th / 2 - 8, ink, a, maxw=bw - 38)
            put_text(cr, sub, f8, bx + 34, ty + th / 2 + 8, ink, (0.95 if taur else 0.7) * a, maxw=bw - 38)
            if taur:                            # молния у правого края плитки
                draw_bitmap(cr, CC_BOLT, int(bx + bw - 8 - len(CC_BOLT[0])),
                            int(ty + th / 2 - len(CC_BOLT) / 2), 1, ink, a)
            hits.append(((bx, ty, bw, th), ("cc", tid)))
    hint = "ПКМ по спектру или «Готово» — закрыть" if d.get("spec") else \
        "ПКМ: Кофеин + Таурин · спектр · Экономия"
    put_text(cr, hint, f8, x + w / 2, ty + th + 14, dim, 0.5 * a, center=True)


def paint_spectrum(cr, x, y, w, h, d, col, a, hits, ios):
    """Спектр ночного света (ПКМ по плитке): клетки 6500 → 2800 K, щелчок — эта теплота
    (и ночной свет включается); «Готово» и ПКМ — обратно к плиткам."""
    f8 = 11 if ios else 8
    fg = (1, 1, 1) if ios else col["on_surface"]
    cur = int(d.get("warmth", 65))
    put_text(cr, "Ночной свет · %s" % ("%d K" % warmth_k(cur) if d.get("night") else "выкл"), f8, x, y + 7, fg, 0.9 * a)
    bw = 60
    ink = sys_chip(cr, x + w - bw, y - 2, bw, 18, False, col, a, ios)
    put_text(cr, "Готово", f8, x + w - bw / 2, y + 7, ink, a, center=True)
    hits.append(((x + w - bw, y - 2, bw, 18), ("cc", "spec")))
    cw = w / SPEC_N
    sel = round(cur / 5) if d.get("night") else -1
    cy = y + 22
    for i in range(SPEC_N):
        cx = int(x + i * cw)
        sw = int(x + (i + 1) * cw) - cx - 3
        rrect(cr, cx, cy, sw, 20, 5 if ios else 0)
        cr.set_source_rgba(*kelvin_rgb(warmth_k(i * 5)), 0.95 * a)
        cr.fill()
        if i == sel:
            cr.rectangle(cx - 1.5, cy - 1.5, sw + 3, 23)
            cr.set_line_width(2)
            cr.set_source_rgba(*fg, a)
            cr.stroke()
        hits.append(((cx, cy - 2, sw + 3, 24), ("cc", "warm:%d" % (i * 5))))


def dev_glyph(dev):
    k = (dev.get("kind") or "").lower()
    n = dev.get("name", "").lower()
    for key, g in DEV_GLYPH:
        if key in k:
            return g
    if any(s in n for s in ("pods", "buds", "head", "наушн")):
        return DEV_GLYPH[0][1]
    return G_BT


SYS_RH, SYS_SELP = 22, 48       # строка списка Wi-Fi/Bluetooth; панель кнопок под выбранной строкой
SYS_MORE_H = 380                # «Ещё…»: страница вытягивается вниз до стольки, дальше — колесом


def sys_key(kind, it):
    return it["ssid"] if kind == "wifi" else it["mac"]


def sys_items(kind, d):
    d = d or {}
    return ((d.get("nets") if kind == "wifi" else d.get("devs")) or []) if d.get("on") else []


def sys_list_h(kind, d, sk):
    """Высота страницы Wi-Fi/Bluetooth: обычная — CARD_HK (+ панель выбранной строки); с «Ещё…» —
    весь список, но не выше SYS_MORE_H."""
    d = d or {}
    items = sys_items(kind, d)
    sel = SYS_SELP if d.get("sel") and any(sys_key(kind, it) == d["sel"] for it in items) else 0
    if not d.get("more"):
        return CARD_HK[kind] + sel
    ry = (16 if sk else 36) + 22 + 8
    return max(CARD_HK[kind] + sel, min(SYS_MORE_H, ry + max(3, len(items)) * SYS_RH + sel + 10))


def paint_sys_list(cr, x, w, h, kind, d, col, a, hits, ios):
    """Wi-Fi и Bluetooth (20.10.2026, просьба: «всё должно быть в островке и только»): сверху
    вкл/выкл, сводка и «Ещё…» — страница вытягивается вниз со всем списком (Wi-Fi пересканирует,
    Bluetooth ищет новые). Щелчок по строке ничего не включает — под ней раскрываются кнопки,
    как в окнах бара: Подключиться / Отключиться / Забыть (в два щелчка), у новой сети с
    паролем — поле пароля."""
    d = d or {}
    pad = 18
    wifi = kind == "wifi"
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    hl = sys_hl(col, ios)
    f8 = 11 if ios else 8
    top = 16 if _SK["on"] else 36
    on = bool(d.get("on"))
    more = bool(d.get("more"))
    g = (G_WIFI if on else G_WIFI_OFF) if wifi else (G_BT if on else G_BT_OFF)
    bw, bh = 76, 22
    ink = sys_chip(cr, x + pad, top, bw, bh, on, col, a, ios)
    put_glyph(cr, g, 16, x + pad + 15, top + bh / 2, ink, a)
    put_text(cr, "Вкл" if on else "Выкл", f8, x + pad + 30, top + bh / 2, ink, a)
    hits.append(((x + pad, top, bw, bh), (kind, "power")))
    mw = 72
    mx = x + w - pad - mw
    if on:
        ink = sys_chip(cr, mx, top, mw, bh, more, col, a, ios)
        put_text(cr, "Свернуть" if more else "Ещё…", f8, mx + mw / 2, top + bh / 2, ink, a, center=True)
        hits.append(((mx, top, mw, bh), (kind, "more")))
    items = sys_items(kind, d)
    if d.get("loading"):
        summary = "…"
    elif not on:
        summary = "выключен"
    elif d.get("scan"):
        summary = "обновляю список…" if wifi else "ищу новые устройства…"
    elif wifi:
        cur = next((n for n in items if n["in_use"]), None)
        summary = (cur["ssid"] + (" · " + d["ip"] if d.get("ip") else "")) if cur else "не подключено"
    else:
        nc = sum(1 for x_ in items if x_["conn"])
        summary = "подключено: %d" % nc if nc else "нет подключённых"
    sx = x + pad + bw + 10
    put_text(cr, summary, f8, sx, top + bh / 2, fg, 0.9 * a, maxw=mx - 10 - sx)
    ry, rh = top + bh + 8, SYS_RH
    keys = [sys_key(kind, it) for it in items]
    sel = d.get("sel") if d.get("sel") in keys else None
    selp = SYS_SELP if sel is not None else 0
    n = max(0, int((h - 6 - ry - selp) // rh))
    off = 0
    if more and len(items) > n:
        off = max(0, min(int(d.get("off", 0)), len(items) - n))
    busy = d.get("busy")
    if on and not items and not d.get("loading"):
        put_text(cr, ("Сетей не видно — «Ещё…» обновит список" if wifi else
                      "Нет сопряжённых — «Ещё…» найдёт новые") if not d.get("scan") else "…",
                 f8, x + w / 2, ry + rh, dim, 0.7 * a, center=True)
    y, prev = ry, False
    for j, it in enumerate(items[off:off + n]):
        key = sys_key(kind, it)
        here = key == sel
        if here:                                # выбранная строка с кнопками — общей подложкой
            cr.rectangle(x + pad - 6, y, w - 2 * pad + 12, rh + SYS_SELP)
            cr.set_source_rgba(*((1, 1, 1) if ios else sk_rgb(0.16, col) if _SK["on"] else col["surface_high"]),
                               (0.07 if ios else 0.9 if _SK["on"] else 0.55) * a)
            cr.fill()
        elif j and not prev:                    # черта между строками (не под панелью кнопок)
            cr.rectangle(x + pad, y, w - 2 * pad, 1)
            cr.set_source_rgba(*dim, 0.12 * a)
            cr.fill()
        if wifi:
            act = it["in_use"]
            gl = G_WIFI_LV[min(3, it["signal"] // 25)]
            name = it["ssid"]
            right = "подключено" if act else "сохранена" if it["known"] else ""
        else:
            act = it["conn"]
            gl = dev_glyph(it)
            name = it["name"]
            right = ("подключено" + (" · " + it["batt"] if it.get("batt") else "")) if act else \
                "сопряжено" if it.get("pair", True) else "новое"
        if busy == key:
            right = {"connect": "подключаю…", "disconnect": "отключаю…", "forget": "забываю…"}.get(
                d.get("busy_what"), "…")
        c = hl if act else fg
        put_glyph(cr, gl, 16, x + pad + 8, y + rh / 2, c, a if act else 0.8 * a)
        rw = text_w(cr, right, f8) if right else 0
        lock = wifi and it["secured"] and not it["known"] and not act
        put_text(cr, name, f8, x + pad + 24, y + rh / 2, c, a, maxw=w - 2 * pad - 24 - rw - (30 if lock else 14))
        if right:
            put_text(cr, right, f8, x + w - pad - rw, y + rh / 2, hl if act else dim, (0.9 if act else 0.6) * a)
        if lock:
            put_glyph(cr, G_LOCKED, 16, x + w - pad - rw - 12, y + rh / 2, dim, 0.6 * a)
        hits.append(((x + pad, y, w - 2 * pad, rh), (kind, "sel:" + key)))
        y += rh
        if here:
            paint_sys_sel(cr, x + pad, y, w - 2 * pad, kind, it, d, col, a, hits, ios)
            y += SYS_SELP
        prev = here
    if more and len(items) > n > 0:             # полоса прокрутки у правого края
        th_ = h - 6 - ry
        bar = max(16, th_ * n / len(items))
        by = ry + (th_ - bar) * off / max(1, len(items) - n)
        cr.rectangle(x + w - pad + 8, by, 2, bar)
        cr.set_source_rgba(*dim, 0.45 * a)
        cr.fill()


def sys_buttons(kind, it, d):
    """Кнопки выбранной строки: [(действие, надпись, главная)], как в окнах бара."""
    ask = d.get("ask") == sys_key(kind, it)
    forget = ("forget", "Точно забыть?" if ask else "Забыть", False)
    if kind == "wifi":
        if it["in_use"]:
            return [("disconnect", "Отключиться", False), forget]
        if it["known"]:
            return [("connect", "Подключиться", True), forget]
        return [("connect", "Подключиться", True)]
    if it["conn"]:
        return [("disconnect", "Отключиться", False), forget]
    if it.get("pair", True):
        return [("connect", "Подключиться", True), forget]
    return [("connect", "Сопрячь и подключить", True)]


def paint_sys_sel(cr, x, y, w, kind, it, d, col, a, hits, ios):
    """Под выбранной строкой: подпись (сигнал/защита или адрес/заряд, либо ответ команды) и
    кнопки; у новой сети с паролем — поле пароля (щелчок — ввод с клавиатуры, Enter —
    подключиться, Esc — отмена)."""
    f8 = 11 if ios else 8
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    key = sys_key(kind, it)
    msg = d.get("msg")
    if msg and msg[0] == key:
        cap, cc, ca = msg[1], (sys_hl(col, ios) if msg[2] else (1.0, 0.45, 0.45) if ios else col["error"]), 1.0
    elif kind == "wifi":
        cap = "сигнал %d%% · %s" % (it["signal"], "защищена" if it["secured"] else "открытая") + \
            (" · пароль сохранён" if it["known"] else "")
        cc, ca = dim, 0.75
    else:
        cap = it["mac"] + (" · заряд " + it["batt"] if it.get("batt") else "") + \
            ("" if it.get("pair", True) else " · сначала сопряжение")
        cc, ca = dim, 0.75
    put_text(cr, cap, f8, x + 24, y + 8, cc, ca * a, maxw=w - 30)
    by, bh = y + 18, 22
    busy = d.get("busy") == key
    btns = sys_buttons(kind, it, d)
    need_pw = kind == "wifi" and it["secured"] and not it["known"] and not it["in_use"]
    bx = x + w
    for act, label, main in reversed(btns):     # кнопки — справа налево
        bwid = max(84, int(text_w(cr, label, f8)) + 22)
        bx -= bwid
        ask = act == "forget" and d.get("ask") == key
        ink = sys_chip(cr, bx, by, bwid, bh, main and not busy, col, a, ios)
        if ask:
            ink = (1.0, 0.45, 0.45) if ios else col["error"]
        put_text(cr, label, f8, bx + bwid / 2, by + bh / 2, ink, (0.45 if busy else 1.0) * a, center=True)
        if not busy:
            hits.append(((bx, by, bwid, bh), (kind, "btn:" + act)))
        bx -= 8
    if need_pw:                                 # поле пароля — слева от «Подключиться»
        fx, fw = x + 24, bx - x - 24
        editing = d.get("pw_on")
        if _SK["on"]:
            sk_box(cr, fx, by, fw, bh, col, a, editing)
        else:
            rrect(cr, fx, by, fw, bh, 11 if ios else 0)
            cr.set_source_rgba(*((1, 1, 1) if ios else col["bg"]), (0.1 if ios else 0.9) * a)
            cr.fill_preserve()
            cr.set_line_width(1.5 if editing else 1)
            cr.set_source_rgba(*(col["primary"] if editing else dim), (0.9 if editing else 0.3) * a)
            cr.stroke()
        pw = d.get("pw") or ""
        if pw:
            shown = "•" * len(pw)
            tw = text_w(cr, shown, f8)
            put_text(cr, shown, f8, fx + 8, by + bh / 2, fg, a, maxw=fw - 18)
        else:
            tw = 0
            put_text(cr, "пароль — щёлкните и вводите" if not editing else "", f8, fx + 8, by + bh / 2,
                     dim, 0.55 * a, maxw=fw - 16)
        if editing:                             # каретка
            cr.rectangle(fx + 8 + min(tw, fw - 18) + 1, by + 5, 1.5 if ios else 2, bh - 10)
            cr.set_source_rgba(*(col["primary"] if not ios else (1, 1, 1)), a)
            cr.fill()
        hits.append(((fx, by, fw, bh), (kind, "pw")))


def paint_sys(cr, x, w, h, kind, d, col, a, hits, ios):
    if kind == "cc":
        paint_cc(cr, x, w, h, d, col, a, hits, ios)
    elif kind == "power":
        paint_power(cr, x, w, h, d, col, a, hits, ios)
    else:
        paint_sys_list(cr, x, w, h, kind, d, col, a, hits, ios)


POWER_ASK = {"logout": ("Выйти из системы?", "Выйти"), "suspend": ("Уйти в сон?", "Уснуть"),
             "reboot": ("Перезагрузить компьютер?", "Перезагрузить"),
             "shutdown": ("Выключить компьютер?", "Выключить")}


def paint_power(cr, x, w, h, d, col, a, hits, ios):
    """Питание по образцу пользователя: квадратные кнопки — замок, выход | сон, перезагрузка,
    выключение. Замок — сразу; остальное сперва спрашивает здесь же (20.10.2026, просьба: «пусть
    сначала спросит подтверждение… гармонично с системой»): значок, вопрос, «Отмена» и «Да»."""
    d = d or {}
    pad = 12
    fg = (1, 1, 1) if ios else col["on_surface"]
    red = (0.96, 0.4, 0.4)
    if not _SK["on"]:
        put_glyph(cr, PAGE_GLYPH["power"], 16, x + pad + 14, 17, fg, 0.6 * a)
        put_text(cr, "Питание", 12 if ios else 8, x + pad + 26, 17, fg, 0.6 * a)
    ask = d.get("ask")
    if ask in POWER_ASK:
        q, yes = POWER_ASK[ask]
        g = next(b[1] for b in POWER_BTNS if b and b[0] == ask)
        f = 12 if ios else 8
        cy = int(h / 2 - (14 if _SK["on"] else 8))
        qw = text_w(cr, q, 16 if not ios else 15)
        gx = int(x + (w - qw - 28) / 2)
        put_glyph(cr, g, 16, gx + 8, cy, red if ask == "shutdown" else fg, a)
        put_text(cr, q, 16 if not ios else 15, gx + 28, cy, fg, a)
        bw, bh, gap = 112, 24, 12
        by = cy + 18
        bx = int(x + (w - 2 * bw - gap) / 2)
        ink = sys_chip(cr, bx, by, bw, bh, False, col, a, ios)
        put_text(cr, "Отмена", f, bx + bw / 2, by + bh / 2, ink, a, center=True)
        hits.append(((bx, by, bw, bh), ("power", "no")))
        bx += bw + gap
        ink = sys_chip(cr, bx, by, bw, bh, True, col, a, ios)
        put_text(cr, yes, f, bx + bw / 2, by + bh / 2, red if ask == "shutdown" and _SK["on"] else ink, a,
                 center=True)
        hits.append(((bx, by, bw, bh), ("power", "yes:" + ask)))
        return
    bs, gap, sep = 44, 12, 26
    btns = [b for b in POWER_BTNS if b]
    total = len(btns) * bs + (len(btns) - 2) * gap + sep
    bx = int(x + (w - total) / 2)
    by = int(h / 2 - bs / 2 - (6 if _SK["on"] else 2))
    for b in POWER_BTNS:
        if b is None:                           # черта между «уйти» и «выключить»
            sx = bx - gap + sep // 2
            cr.rectangle(sx, by + 10, 1, bs - 20)
            cr.set_source_rgba(*fg, 0.25 * a)
            cr.fill()
            bx += sep - gap
            continue
        pid, g, label = b
        ink = sys_chip(cr, bx, by, bs, bs, False, col, a, ios, R=14 if ios else 10)
        put_glyph(cr, g, 16, bx + bs / 2, by + bs / 2, red if pid == "shutdown" else ink, a)
        put_text(cr, label, 11 if ios else 8, bx + bs / 2, by + bs + 11, fg, 0.6 * a, center=True)
        hits.append(((bx, by, bs, bs + 18), ("power", pid)))
        bx += bs + gap


# ─────────────── Skeet: карточка как меню gamesense (20.10.2026) ───────────────
# Просьба: «дизайн самого островка не нравится, адаптируй к более похожему стилю Skeet».
# Приметы (память skeet-settings-skin): рамка слоями 1 #0a0a0a · 1 #3c3c3c · 3 #282828 ·
# 1 #3c3c3c, фон #131313 с точками, радуга палитры сверху, вкладки со значками (выбранная
# светлее и сливается с полем), группа с заголовком на рамке, кнопки-плашки, ползунок
# градиентом акцента. Серые — с лёгким оттенком гаммы обоев, как у Настроек в Skeet.
_SK = {"on": False}             # рисуем содержимое внутри Skeet-карточки (кнопки, ползунки)
_SK_DOTS = {}


def sk_rgb(v, col, k=0.22):
    return tuple(v * (1 - k) + c * k * min(1.0, v * 6) for c in col["bg"])


def sk_box(cr, x, y, w, h, col, a, accent=False):
    """Кнопка Skeet — как button.seg в Настройках: кромка #0a0a0a, внутренняя линия #303030,
    градиент #242424 → #1b1b1b. Выбранная не заливается (20.10.2026, просьба: «уже не похоже
    на стиль Skeet, кнопки не те») — та же плашка, полоска акцента снизу, текст акцентом
    (цвет текста — sk_ink)."""
    import cairo
    cr.rectangle(x, y, w, h)
    cr.set_source_rgba(*sk_rgb(0.04, col, 0.03), a)
    cr.fill()
    cr.rectangle(x + 1, y + 1, w - 2, h - 2)
    cr.set_source_rgba(*sk_rgb(0.188, col, 0.08), a)
    cr.fill()
    g = cairo.LinearGradient(0, y + 2, 0, y + h - 2)
    g.add_color_stop_rgba(0, *sk_rgb(0.141, col, 0.05), a)
    g.add_color_stop_rgba(1, *sk_rgb(0.106, col, 0.05), a)
    cr.rectangle(x + 2, y + 2, w - 4, h - 4)
    cr.set_source(g)
    cr.fill()
    if accent:
        cr.rectangle(x + 2, y + h - 4, w - 4, 2)
        cr.set_source_rgba(*col["primary"], a)
        cr.fill()


def sk_ink(col, on):
    """Текст кнопки Skeet: выбранная — светлый акцент (acc_l), иначе серый #929292."""
    if on:
        return tuple(c * 0.78 + 0.22 for c in col["primary"])
    return sk_rgb(0.573, col, 0.10)


def sk_slider(cr, x, y, w, h, pr, col, a):
    import cairo
    cr.rectangle(x, y, w, h)
    cr.set_source_rgba(*sk_rgb(0.04, col), a)
    cr.fill()
    cr.rectangle(x + 1, y + 1, w - 2, h - 2)
    cr.set_source_rgba(*sk_rgb(0.15, col), a)
    cr.fill()
    if pr and pr > 0:
        p = col["primary"]
        g = cairo.LinearGradient(0, y + 1, 0, y + h - 1)
        g.add_color_stop_rgba(0, *p, a)
        g.add_color_stop_rgba(1, *(c * 0.6 for c in p), a)
        cr.rectangle(x + 1, y + 1, (w - 2) * min(1.0, pr), h - 2)
        cr.set_source(g)
        cr.fill()


def sk_dots(rgb=None):
    """Точечный узор фона Skeet: плитка 4×4. Без цвета — одна светлая точка; с цветом — точки
    (0,0) и (2,2) этим цветом, как у виджетов (desktop_widgets.draw_skeet)."""
    import cairo
    key = rgb or "pat"
    if key not in _SK_DOTS:
        s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
        c = cairo.Context(s)
        c.rectangle(0, 0, 1, 1)
        if rgb:
            c.rectangle(2, 2, 1, 1)
            c.set_source_rgb(*rgb)
        else:
            c.set_source_rgba(1, 1, 1, 0.035)
        c.fill()
        pat = cairo.SurfacePattern(s)
        pat.set_extend(cairo.EXTEND_REPEAT)
        if rgb:                                  # обои сменились — прежний узор не нужен
            for k in [k for k in _SK_DOTS if k != "pat"]:
                del _SK_DOTS[k]
        _SK_DOTS[key] = pat
    return _SK_DOTS[key]


def sk_g(level, col, t=0.05):
    """Серый Skeet с примесью акцента — формула skeet_colors() виджетов и Настроек."""
    return mix_rgb((level / 255.0,) * 3, col.get("vivid", col["primary"]), t)


def sk_frame(cr, x, w, h, col, a):
    """Рамка окна gamesense и поле с точками; y=0 — верх карточки. Слои — как у виджетов
    Skeet (desktop_widgets.draw_skeet): светлая акцентная 1, средняя 3, светлая 1, почти чёрная 1.
    20.10.2026, просьба: «вокруг островка не хватает акцентных линий, как в виджетах»."""
    import cairo
    line1 = mix_rgb(sk_g(0x3c, col, 0.08), col.get("vivid", col["primary"]), 0.45)
    o = 0
    for rgb, t in ((line1, 1), (sk_g(0x28, col, 0.06), 3), (line1, 1), (sk_g(0x0a, col, 0.03), 1)):
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.rectangle(x + o, o, w - 2 * o, h - 2 * o)
        cr.rectangle(x + o + t, o + t, w - 2 * (o + t), h - 2 * (o + t))
        cr.set_source_rgba(*rgb, a)
        cr.fill()
        o += t
    cr.set_fill_rule(cairo.FILL_RULE_WINDING)
    cr.rectangle(x + 6, 6, w - 12, h - 12)
    cr.set_source_rgba(*sk_g(0x13, col), a)      # фон и точки — как у виджета (bg, dot)
    cr.fill_preserve()
    cr.save()
    cr.translate(x + 6, 6)
    cr.set_source(sk_dots(sk_g(0x18, col)))
    cr.restore()
    cr.fill()
    # радуга палитры: верхний пиксель ярко, второй — притушен (как у gamesense)
    g = cairo.LinearGradient(x + 6, 0, x + w - 6, 0)
    for i, k in enumerate(("vivid", "tertiary", "secondary")):
        g.add_color_stop_rgba(i / 2, *col.get(k, col["primary"]), a)
    cr.rectangle(x + 6, 6, w - 12, 1)
    cr.set_source(g)
    cr.fill()
    cr.save()
    cr.rectangle(x + 6, 7, w - 12, 1)
    cr.clip()
    cr.set_source(g)
    cr.paint_with_alpha(0.45)
    cr.restore()


def paint_skeet_card(cr, x, w, h, kind, d, pages, col, a, ci):
    """Карточка Skeet: рамка gamesense, радуга, вкладки страниц со значками (щелчок —
    страница), имя .exe справа, группа с названием страницы; внутри — обычная страница
    (paint_card) с кнопками-плашками и ползунком."""
    hits = []
    sk_frame(cr, x, w, h, col, a)
    # вкладки
    sy, sh = 8, SK_TOP - 8
    cr.rectangle(x + 6, sy, w - 12, sh)
    cr.set_source_rgba(*sk_rgb(0.047, col), a)
    cr.fill()
    exe = PAGE_EXE.get(kind, "island.exe")
    ew = text_w(cr, exe, 8)
    # Вкладки стабильны (20.10.2026, просьба: «меняется расположение вкладок? Они должны быть
    # стабильные»): ширина — по всем блокам из настроек и самому длинному имени .exe, а не по
    # открытой странице (control.exe сужал вкладки). Живые без дела не рисуются и места не
    # держат — ни пустых ячеек, ни разрыва («их не должно быть», «разделение тоже не очень»).
    ids = TAB_IDS or [k for k, _dd in pages]
    n = max(1, len(ids) + sum(1 for k, _dd in pages if k not in ids))
    exw = max(text_w(cr, e, 8) for e in PAGE_EXE.values())
    tw = max(20, min(30, int((w - 12 - exw - 24) / n)))
    line = sk_rgb(0.235, col)
    cr.rectangle(x + 6, sy + sh, w - 12, 1)
    cr.set_source_rgba(*line, a)
    cr.fill()
    for i, (k, _dd) in enumerate(pages):
        tx = x + 6 + i * tw
        live = k in LIVE_TABS
        if i and live != (pages[i - 1][0] in LIVE_TABS):   # черта между живыми и инструментами
            cr.rectangle(tx, sy + 4, 1, sh - 8)
            cr.set_source_rgba(*sk_rgb(0.30, col), a)
            cr.fill()
        on = i == ci
        if on:
            cr.rectangle(tx, sy, tw, sh + 1)
            cr.set_source_rgba(*sk_rgb(0.075, col), a)
            cr.fill()
            for lx in (tx, tx + tw - 1):
                cr.rectangle(lx, sy, 1, sh + 1)
            cr.set_source_rgba(*line, a)
            cr.fill()
        g = PAGE_GLYPH.get(k, "?")
        if live:
            # 20.10: неактивные заметно тусклее — иначе цветные значки спорят с открытой вкладкой
            ink, ga = tab_rgb(k, col), (a if on else 0.32 * a)
            cr.rectangle(tx + 4, sy + sh - 2, tw - 8, 2)
            cr.set_source_rgba(*ink, ga if on else 0.22 * a)
            cr.fill()
        else:
            # 20.10.2026, просьба: «неактивные стали слишком тусклыми» — без притушения 0.6, чуть светлее
            ink, ga = (col["on_surface"] if on else sk_rgb(0.42, col)), a
            lvl = (_dd or {}).get("radio") if k in ("wifi", "bt") else None
            if lvl:                             # включён — приглушённый акцент, подключён — яркий
                ink = radio_rgb(lvl, col)
        gy = int(sy + sh / 2) - (1 if live else 0)
        pix_glyph(cr, g, int(tx + tw / 2), gy, ink, ga) or put_glyph(cr, g, 16, int(tx + tw / 2), gy, ink, ga)
        hits.append(((tx, sy, tw, sh), ("page", i)))
    put_text(cr, exe, 8, x + w - 12 - ew, sy + sh / 2, col["on_surface_variant"], 0.75 * a)
    # группа с заголовком на рамке
    gx, gy, gw = x + 10, SK_TOP + 6, w - 20
    gh = h - gy - 10
    if gh > 8:
        cr.rectangle(gx, gy, gw, gh)
        cr.set_source_rgba(*sk_rgb(0.04, col), a)
        cr.fill()
        cr.rectangle(gx + 1, gy + 1, gw - 2, gh - 2)
        cr.set_source_rgba(*sk_rgb(0.196, col), a)
        cr.fill()
        cr.rectangle(gx + 2, gy + 2, gw - 4, gh - 4)
        cr.set_source_rgba(*sk_rgb(0.086, col), a)
        cr.fill()
        title = {"clip": "Снимки из буфера · перетащите в чат", "prefs": "Настройки островка",
                 "shelf": "Полка · бросьте файл на островок", "cc": "Центр управления"}.get(
            kind, PAGES.get(kind, ("",))[0])
        tt = text_w(cr, title, 8)
        cr.rectangle(gx + 8, gy - 1, tt + 8, 4)
        cr.set_source_rgba(*sk_rgb(0.075, col), a)
        cr.fill()
        put_text(cr, title, 8, gx + 12, gy + 1, col["on_surface"], 0.92 * a)
    # страница внутри группы
    _SK["on"] = True
    try:
        cr.save()
        cr.translate(0, SK_TOP)
        cr.rectangle(gx + 2, gy + 2 - SK_TOP, gw - 4, gh - 4)
        cr.clip()
        inner = paint_card(cr, x + 4, w - 8, h - SK_TOP - 6, kind, d, pages, col, a, ci)
        cr.restore()
    finally:
        _SK["on"] = False
    hits += [((hx, hy + SK_TOP, hw, hh), act) for (hx, hy, hw, hh), act in inner]
    return hits


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
    if k == "nudge":
        return NUDGE_RGB
    return col["error"] if k == "rec" else col["secondary"] if k == "timer" else \
        col["tertiary"] if k == "music" else col["primary"]


def radio_rgb(lvl, col):
    """Значок вкладки Wi-Fi/Bluetooth (20.10.2026): 2 — подключено (яркий акцент обоев),
    1 — только включено (тот же акцент, наполовину к серому неактивных вкладок)."""
    v = col.get("vivid", col["primary"])
    return v if lvl >= 2 else mix_rgb(sk_rgb(0.42, col), v, 0.5)


def tab_rgb(k, col):
    """Цвет вкладки живого блока: запись и помидор — как их инструменты, котик — акцент обоев."""
    if k in ("rec", "pomo"):
        return TOOL_RGB[k]
    if k == "cat":
        return col.get("vivid", col["primary"])
    return act_color(k, col)


def ck_rgb(ck, col):
    """Цвет-ключ act_line → rgb (звонок — свой зелёный, его нет в палитре)."""
    return CALL_GREEN if ck == "call" else NUDGE_RGB if ck == "nudge" else col[ck]


def nudge_sec(d):
    """Сколько подряд: счёт серии раз в NUDGE_POLL_S, между опросами — по часам, если всё ещё там."""
    s = d.get("sec") or 0
    if d.get("here") and d.get("t"):
        s += max(0.0, min(30.0, time.monotonic() - d["t"]))
    return s


def nudge_phase(d):
    """(напечатано букв, вспышка рамки, курсор виден): рамка мигает, потом фраза печатается
    по буквам, курсор-блок мигает. Без t0 (страница, снимок) — фраза целиком."""
    n = len(d.get("text") or "")
    t0 = d.get("t0")
    if t0 is None:
        return n, False, int(time.time()) % 2 == 0
    t = time.monotonic() - t0
    typed = max(0, min(n, int((t - NUDGE_BLINK_S) / NUDGE_CHAR_S)))
    return typed, t < NUDGE_BLINK_S and int(t / 0.15) % 2 == 0, typed < n or int(t / 0.5) % 2 == 0


def paint_nudge_compact(cr, x, w, h, d, col, a, D):
    """Компакт «Пора к делу»: значок терминала и фраза янтарём, печатается слева направо."""
    ios = bool(D.get("ios"))
    text = d.get("text") or ""
    n, flash, cur = nudge_phase(d)
    mid = h / 2
    if flash:                                   # заметить, что появилась: рамка вспыхивает
        pill_path(cr, x, w, h, D)
        cr.set_line_width(4)
        cr.set_source_rgba(*NUDGE_RGB, a)
        cr.stroke()
    if ios:
        put_text(cr, G_NUDGE, 13, x + 20, mid, NUDGE_RGB, a, center=True)
    else:
        pix_glyph(cr, G_NUDGE, x + 20, mid, NUDGE_RGB, a)
    px, tx = (13, x + 36) if ios else (8, x + 36)
    shown = text[:n]
    if shown:
        put_text(cr, shown, px, tx, mid, NUDGE_RGB, a, maxw=w - 36 - 22)
    if cur:
        cw = min(text_w(cr, shown, px) if shown else 0, w - 36 - 22)
        ch = 12 if ios else 8
        cr.rectangle(int(tx + cw + 2), int(mid - ch / 2), 7 if ios else 6, ch)
        cr.set_source_rgba(*NUDGE_RGB, (0.85 if ios else 1) * a)
        cr.fill()


def paint_nudge(cr, x, w, h, d, col, a, ios):
    """Страница «Пора к делу»: сколько подряд и с какого часа, что это и сколько за день,
    внизу — фраза в окошке терминала с мигающим курсором."""
    d = d or {}
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    dim = (0.7, 0.7, 0.74) if ios else col["on_surface_variant"]
    big, small = (20, 12) if ios else (24, 8)
    t = mmss(nudge_sec(d))
    put_text(cr, t, big, x + pad, 32, fg, a)
    since = time.strftime("%H:%M", time.localtime(d.get("start") or time.time()))
    put_text(cr, "подряд · с " + since, small, x + pad + text_w(cr, t, big) + 10, 33, dim, 0.85 * a)
    sub = [d.get("what") or ""]
    if d.get("today"):
        sub.append("сегодня " + mmss(d["today"]))
    if not d.get("here") and d.get("kind") != "demo" and (d.get("away") or 0) >= 20:
        sub.append("отошли %d мин" % max(1, int(d["away"] // 60)) if d["away"] >= 60 else "отошли")
    put_text(cr, " · ".join(s for s in sub if s), small, x + pad, 56, dim, 0.85 * a, maxw=w - 2 * pad)
    bx, by, bw, bh = int(x + pad), int(h - 40), int(w - 2 * pad), 26
    if ios:
        rrect(cr, bx, by, bw, bh, 8)
        cr.set_source_rgba(0, 0, 0, 0.5 * a)
        cr.fill_preserve()
        cr.set_line_width(1)
        cr.set_source_rgba(*NUDGE_RGB, 0.5 * a)
        cr.stroke()
    else:
        cr.rectangle(bx, by, bw, bh)
        cr.set_source_rgba(0, 0, 0, 0.55 * a)
        cr.fill()
        for r in ((bx, by, bw, 1), (bx, by + bh - 1, bw, 1), (bx, by, 1, bh), (bx + bw - 1, by, 1, bh)):
            cr.rectangle(*r)
        cr.set_source_rgba(*NUDGE_RGB, 0.6 * a)
        cr.fill()
    line = "> " + (d.get("text") or "Пора к делу")
    put_text(cr, line, small, bx + 8, by + bh / 2, NUDGE_RGB, a, maxw=bw - 24)
    if int(time.time()) % 2 == 0:
        cw = min(text_w(cr, line, small), bw - 24)
        ch = 12 if ios else 8
        cr.rectangle(int(bx + 8 + cw + 2), int(by + bh / 2 - ch / 2), 7 if ios else 6, ch)
        cr.set_source_rgba(*NUDGE_RGB, a)
        cr.fill()


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
    if kind == "shelf":
        paint_shelf(cr, x, w, h, d, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    if kind in SYS_PAGES:
        paint_sys(cr, x, w, h, kind, d, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    if kind in ("clip", "tools"):
        (paint_clip if kind == "clip" else paint_tools)(cr, x, w, h, d if kind == "clip" else kind, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    icon, text, ck = act_line(kind, d)
    acc = ck_rgb(ck, col)
    pr = progress(kind, d)
    R = 38
    if kind == "nudge":
        paint_nudge(cr, x, w, h, d, col, a, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    if kind == "prefs":
        paint_prefs(cr, x, w, h, d, col, a, hits, True)
        ios_dots(cr, x, w, n, cur, a, hits)
        return hits
    eqh = MUSIC_EQ[2] if kind == "music" else 0
    cx, cy = x + 18 + R, (h - eqh) / 2
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
        sub = mic_sub(d)
        btns = [(G_MIC_OFF if d["muted"] else G_MIC, ("call", "mute"), True), (G_OPEN, ("call", "focus"), False)]
    elif kind == "timer" and d["list"]:
        t = d["list"][0]
        title, sub = t["text"], ("ещё %d" % (len(d["list"]) - 1) if len(d["list"]) > 1 else "")
        btns = [(G_STOP, ("timer", "stop:%d" % t["id"]), True), (G_PLUS, ("timer", "add"), False)]
    elif kind == "timer":
        title, sub, btns = "Таймер", "«+» — новый, с виджетом на столе", [(G_PLUS, ("timer", "add"), True)]
    else:
        title, sub, btns = text, "", []
    dots = 10 * n if n > 1 else 0
    put_text(cr, title, 15, tx, 26, (1, 1, 1), a, maxw=tw - dots - 6)
    lk = kind == "music" and like_btn(cr, tx + tw - 5, 45, _CAT["s"], dict(col, on_surface_variant=(1, 1, 1)), a, hits)
    if sub:
        put_text(cr, sub, 12, tx, 45, (1, 1, 1), 0.55 * a, maxw=tw - (22 if lk else 0))
    ios_dots(cr, x, w, n, cur, a, hits)
    if btns:
        gap, bh = 8, 28
        bw = (tw - gap * (len(btns) - 1)) / len(btns)
        for i, (g, act, prim) in enumerate(btns):
            ios_button(cr, tx + i * (bw + gap), h - 20 - eqh - bh, bw, bh, g, acc, a, hits, act, prim)
    if kind == "music":
        music_eq(cr, x + 18, h - 10, w - 36, _CAT["s"] or {}, col, a, d.status == "Playing")
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
    if not _SK["on"]:                         # в Skeet это заголовок рамки группы
        put_text(cr, "Снимки из буфера · перетащите в чат", px, x + pad, 22 if ios else 17, fg, 0.6 * a,
                 maxw=w - 2 * pad - 80)
    d = d or {}
    items = d.get("items") or []
    if not items:
        put_text(cr, "Загружаю…" if d.get("loading") else "В буфере нет картинок", px, x + w / 2, h / 2 + 10,
                 fg, 0.55 * a, center=True)
        return
    gap = 8
    cols = 4                                  # сетка 4×2: два этажа по четыре (20.10.2026)
    tw = (w - 2 * pad - gap * (cols - 1)) / cols
    top = 16 if _SK["on"] else 34
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


def paint_shelf(cr, x, w, h, d, col, a, hits, ios):
    """Страница «Полка» (20.10.2026, одобрено из списка AngelOS: «бросить файл на островок,
    чтобы подержать его там»): плитки 4×2 — миниатюра картинки или значок и имя файла.
    Щелчок — открыть, перетаскивание — файлом куда угодно, × — убрать с полки."""
    pad = 18
    fg = (1, 1, 1) if ios else col["on_surface"]
    px = 12 if ios else 8
    if not _SK["on"]:
        put_text(cr, "Полка · бросьте файл на островок", px, x + pad, 22 if ios else 17, fg, 0.6 * a,
                 maxw=w - 2 * pad - 80)
    items = (d or {}).get("items") or []
    if not items:
        put_text(cr, "Перетащите файл на островок — он полежит здесь", px, x + w / 2, h / 2 + 10,
                 fg, 0.55 * a, center=True)
        return
    gap, cols = 8, 4
    tw = (w - 2 * pad - gap * (cols - 1)) / cols
    top = 16 if _SK["on"] else 34
    th = (h - top - 14 - gap) / 2
    R = 8 if ios else 0
    for i, it in enumerate(items[:SHELF_N]):
        bx = round(x + pad + (i % cols) * (tw + gap))
        ty = round(top + (i // cols) * (th + gap))
        cr.save()
        rrect(cr, bx, ty, tw, th, R)
        cr.clip()
        cr.set_source_rgba(*((1, 1, 1) if ios else col["surface_high"]), (0.08 if ios else 1) * a)
        cr.paint()
        sf = it.get("surf")
        if sf is not None:
            iw, ih = sf.get_width(), sf.get_height()
            k = max(tw / iw, (th - 14) / ih)
            cr.translate(bx + (tw - iw * k) / 2, ty + (th - 14 - ih * k) / 2)
            cr.scale(k, k)
            cr.set_source_surface(sf, 0, 0)
            cr.paint_with_alpha(a)
        cr.restore()
        if sf is None:
            put_text(cr, G_FOLDER if it.get("dir") else G_FILE, 16, bx + tw / 2, ty + (th - 14) / 2, fg,
                     0.8 * a, center=True)
        cr.rectangle(bx, ty + th - 14, tw, 14)       # подпись — по низу плитки
        cr.set_source_rgba(*((0, 0, 0) if ios else col["bg"]), (0.55 if ios else 0.85) * a)
        cr.fill()
        put_text(cr, it["name"], 11 if ios else 8, bx + 4, ty + th - 7, fg, 0.9 * a, maxw=tw - 8)
        if not ios:
            cr.rectangle(bx + 0.5, ty + 0.5, tw - 1, th - 1)
            cr.set_line_width(1)
            cr.set_source_rgba(*col["outline_variant"], 0.8 * a)
            cr.stroke()
        xb = (bx + tw - 16, ty + 2, 14, 14)          # × — убрать с полки
        cr.rectangle(*xb)
        cr.set_source_rgba(*((0, 0, 0) if ios else col["bg"]), 0.7 * a)
        cr.fill()
        put_text(cr, G_X, 11 if ios else 8, xb[0] + 7, xb[1] + 7, fg, 0.85 * a, center=True)
        hits.append(((xb[0] - 2, xb[1] - 2, 18, 18), ("shelf_rm", i)))
        hits.append(((bx, ty, tw, th), ("shelf", i)))


def paint_tools(cr, x, w, h, _d, col, a, hits, ios):
    """Страница «Инструменты»: запись, пипетка, снимок, заметка, помидор — в один ряд."""
    pad = 12
    fg = (1, 1, 1) if ios else col["on_surface"]
    items = CAPTURE if _d == "capture" else FOCUS if _d == "focus" else TOOLS
    if not _SK["on"]:
        put_text(cr, PAGES.get(_d, ("Инструменты",))[0], 12 if ios else 8, x + pad + 6, 22 if ios else 17, fg, 0.6 * a)
    n = len(items)
    cw = (w - 2 * pad) / n
    cy = h / 2 + 4
    for i, (tid, g, label, _cmd) in enumerate(items):
        cx = round(x + pad + cw * i + cw / 2)      # целые — пиксельный шрифт не мажется
        if _SK["on"]:
            sk_box(cr, cx - 19, cy - 17, 38, 34, col, a, False)
            cr.new_path()
        elif ios:
            rrect(cr, cx - 19, cy - 19, 38, 38, 12)
            cr.set_source_rgba(1, 1, 1, 0.12 * a)
        else:
            cr.new_path()
            cr.arc(cx, cy, 17, 0, 2 * math.pi)
            cr.set_source_rgba(*col["surface_high"], 0.9 * a)
        cr.fill()
        pix_glyph(cr, g, cx, cy, TOOL_RGB.get(tid, fg), a) or \
            put_glyph(cr, g, 16 if not ios else 15, cx, cy, TOOL_RGB.get(tid, fg), a)
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
# «Нравится» в карточке музыки (20.10.2026, просьба: «не вижу кнопки лайка»): полное — нравится
LIKE_ON = (".##...##.", "####.####", "#########", "#########", ".#######.", "..#####..", "...###...", "....#....")
LIKE_OFF = (".##...##.", "#..#.#..#", "#...#...#", "#.......#", ".#.....#.", "..#...#..", "...#.#...", "....#....")
LIKE_RGB = (1.0, 0.36, 0.5)


def like_btn(cr, cx, cy, cat, col, a, hits):
    """Сердце «Нравится» (player_like.py): есть, только если плеер его умеет."""
    st = (cat or {}).get("like")
    if st not in ("liked", "not"):
        return False
    on = st == "liked"
    bmp = LIKE_ON if on else LIKE_OFF
    draw_bitmap(cr, bmp, int(cx) - 4, int(cy) - 4, 1, LIKE_RGB if on else col["on_surface_variant"],
                a if on else 0.8 * a)
    hits.append(((int(cx) - 10, int(cy) - 10, 20, 20), ("music", "like")))
    return True
CAT_NOTE = ("...########", "...########", "...#......#", "...#......#", "...#......#", "...#......#",
            "...#......#", ".###....###", "####...####", "####...####", ".##.....##.")
CAT_TOMATO = ("..##...", "...#...", ".#####.", "#######", "#######", "#######", ".#####.")
# Зверёк занятого терминала (20.10.2026): пиксельный, оранжевый; глаза вырезаны.
CAT_BUSY = (".###########.", ".###########.", ".##.#####.##.", "#############", "#############",
              "#############", ".###########.", "..#.#...#.#..", "..#.#...#.#..", "..#.#...#.#..")
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
        parts.append(("busy", len(CAT_BUSY[0])))
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


def music_eq(cr, x, bottom, w, cat, col, a, playing):
    """Эквалайзер карточки музыки: невысокая полоса квадратиков на всю ширину, низом на bottom;
    64 полосы cava растянуты на число столбцов."""
    rows, blk, _sp = MUSIC_EQ
    n = int((w + 1) // (blk + 1))
    v = cat.get("eqw") or cat.get("eq8") or ()
    m = len(v)
    lv = []
    # 20.10: зеркалом — басы в середине, высокие по краям (просьба: «чтобы в центре больше было
    # и по бокам по чуть-чуть»; слева направо выглядело случайным)
    half = (n - 1) / 2.0
    for i in range(n if m else 0):
        t = abs(i - half) / max(1.0, half) * (m - 1)
        j = int(t)
        lv.append(v[j] + (v[min(j + 1, m - 1)] - v[j]) * (t - j))
    # 20.10: у cava на 64 полосы медиана ~0,24, и почти всё горело одним рядом («стоит на
    # месте»). Растягиваем по самому громкому столбцу кадра и поднимаем тихие кривой.
    # Середина весомее краёв (горка), соседи сглажены — без одиночных «случайных» столбиков.
    lv = [u * (1 - 0.6 * (abs(i - half) / max(1.0, half)) ** 1.5) for i, u in enumerate(lv)]
    lv = [(lv[max(0, i - 1)] + 2 * u + lv[min(len(lv) - 1, i + 1)]) / 4 for i, u in enumerate(lv)]
    pk = max(lv or [0])
    if pk > 0.02:
        lv = [(u / max(pk, 0.3)) ** 0.7 for u in lv]
    ex = int(x + (w - (n * (blk + 1) - 1)) / 2)
    draw_eq(cr, ex, int(bottom - rows * (blk + 1) + 1), n, rows, blk, lv, col, a, playing)


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
        if D.get("shadow") == "hard":
            cr.rectangle(x + 3, top + 3, w, h)
            cr.set_source_rgba(*(c * 0.25 for c in col["bg"]), 0.72)
            cr.fill()
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
        # тусклый акцент обоев, не серый (20.10.2026, просьба: «серый выбивается от системы»)
        cr.set_source_rgba(*pill_edge(col))
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
                _LYR["on"] = True
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
                draw_bitmap(cr, CAT_BUSY, int(cx), int(cy - len(CAT_BUSY) / 2), 1, BUSY_ORANGE)
            elif k == "date":
                put_text(cr, cat_date(), 8, cx, cy, dim, 0.9)
    cr.restore()
    return hits


# Капсула «Центра» (20.10.2026, просьба: «когда захожу в этот блок и закрывается островок —
# сверху маленькими иконками: Таурин/Кофеин+Таурин справа, причём по иконкам заметно, что
# именно; это не должно менять размер островка; Сторож — слева, если включён; в центре день
# недели»). Ширина постоянная (CC_PILL_W): значки встают в зарезервированные места.
CC_CUP = ("...#..#....",
          "..#..#.....",
          "...#..#....",
          "...........",
          "########...",
          "##########.",
          "########..#",
          "########..#",
          "##########.",
          ".######....")
CC_BOLT = ("....###",
           "...###.",
           "..###..",
           ".###...",
           "#######",
           "...###.",
           "..###..",
           ".###...",
           ".##....",
           "##.....")
CC_GUARD = ("#########",             # щит «Сторожа» (20.10.2026: вместо будильника), левая половина залита
            "#####...#",
            "#####...#",
            "#####...#",
            "#####...#",
            ".####..#.",
            ".####..#.",
            "..###.#..",
            "...###...",
            "....#....")
MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")
WEEKDAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


CC_PILL_W = 220                 # уже кота (CAT_MIN_W 270): «воскресенье 30 сен» и значки влезают (20.10.2026)


def cc_pill_w():
    return float(CC_PILL_W)


def paint_cc_pill(cr, x, top, w, h, st, col, D):
    """Слева — будильник Сторожа (если стережёт), в центре — день недели и дата, справа —
    чашка (кофеин, акцентом) и молния (таурин, третьим цветом палитры — как плитка «Кофеин
    + Таурин» в Центре управления бара)."""
    import cairo
    hits = []
    if st.get("ta", 1) <= 0.01 or w < 4 or h < 2:
        return hits
    ios = bool(D.get("ios"))
    cc = st.get("ccp") or {}
    cr.save()
    pill_shape(cr, x, top, w, h, col, D)
    if w >= CC_PILL_W * 0.9 and h >= PILL_H * 0.6:
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        cr.rectangle(x, top, w, h)
        cr.clip()
        ink = (1, 1, 1) if ios else col["on_surface"]
        dim = (0.75, 0.75, 0.78) if ios else col["on_surface_variant"]
        acc = mix_rgb(col["primary"], (1, 1, 1), 0.35) if ios else col["primary"]
        # таурин — tertiary, но насыщеннее: в мягких палитрах он почти как акцент чашки
        import colorsys
        th_, tl_, ts_ = colorsys.rgb_to_hls(*col["tertiary"])
        ter = colorsys.hls_to_rgb(th_, 0.72, max(ts_, 0.85))
        cy = top + h / 2
        if cc.get("guard"):
            draw_bitmap(cr, CC_GUARD, int(x + CAT_PAD), int(cy - len(CC_GUARD) / 2), 1, acc, 0.95)
        lt = time.localtime()
        # справа от дня — дата («20 окт»), не время: часы и так в баре (20.10.2026, пользователь)
        day, clock = WEEKDAYS_FULL[lt.tm_wday], "%d %s" % (lt.tm_mday, MONTHS_SHORT[lt.tm_mon - 1])
        dw, gap = text_w(cr, day, 8), 8
        cw = text_w(cr, clock, 8)
        sx = x + (w - dw - gap - cw) / 2
        put_text(cr, day, 8, int(sx), cy, ink, 0.95)
        put_text(cr, clock, 8, int(sx + dw + gap), cy, dim, 0.9)
        rx = x + w - CAT_PAD                    # справа налево: молния, чашка
        if cc.get("taurine"):
            rx -= len(CC_BOLT[0])
            draw_bitmap(cr, CC_BOLT, int(rx), int(cy - len(CC_BOLT) / 2), 1, ter, 1.0)
            rx -= 4
        if cc.get("caffeine"):
            rx -= len(CC_CUP[0])
            draw_bitmap(cr, CC_CUP, int(rx), int(cy - len(CC_CUP) / 2), 1, acc, 1.0)
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
    # справа: обложка и квадратики — столбец по центру по высоте (20.10.2026: «иконка прибита
    # к верху, надо оцентровать»)
    p = cat.get("p")
    rx = x + w - pad - 48
    if p is not None:                       # 20.10.2026: «квадратик убрать, вместо него иконку,
        k = 3                               # что запущено» — обложка теперь в карточке музыки
        bw, bh = len(CAT_NOTE[0]) * k, len(CAT_NOTE) * k
        bx, y0 = int(rx + 24 - bw / 2), int((h - bh) / 2)
        draw_bitmap(cr, CAT_NOTE, bx, y0, k, act_color("music", col), a if p.status == "Playing" else 0.45 * a)
        hits.append(((bx, y0, bw, bh), ("cat", "music")))
    else:
        pm = cat.get("pomo")
        if pm:
            y0 = int((h - (len(CAT_TOMATO) * 4 + 14)) / 2)
            draw_bitmap(cr, CAT_TOMATO, int(rx + 10), y0, 4, act_color("pomo", col), a)
            put_text(cr, mmss(pomo_rem(pm)), 8, rx + 24, y0 + len(CAT_TOMATO) * 4 + 10, fg, a, center=True)
        elif cat.get("busy"):
            k = 3                               # 20.10.2026: «иконку клода чуть поменьше» (было 4)
            bw, bh = len(CAT_BUSY[0]) * k, len(CAT_BUSY) * k
            bx, y0 = int(rx + 24 - bw / 2), int((h - bh) / 2)
            draw_bitmap(cr, CAT_BUSY, bx, y0, k, BUSY_ORANGE, a)
            hits.append(((bx, y0, bw, bh), ("cat", "busy")))
    # посередине: строки песни или кот
    lx, lw = x + 128, w - 128 - 48 - pad - 14
    ly = lyric_now(cat) if cat.get("lines") else None
    if cat.get("lines"):
        _LYR["on"] = True
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
bars = 64
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
    """Кот виден на этом островке: капсула «Котик» или открыта его страница; и страница музыки —
    ей нужны кадры эквалайзера."""
    if isl.mode == "thread" and isl.geo[0] > 4:
        return eff_style(conf["thread_style"], isl.app.pill_focus()) == "cat"
    if isl.mode == "card" and isl.app.pages:
        return isl.app.pages[isl.card_i % len(isl.app.pages)][0] in ("cat", "music")
    return False


def eff_style(style, focus):
    """Чем рисовать нить: живая нить с последним блоком «Котик» — капсула котика (20.10.2026:
    вида нити «Котик» больше нет, котик — один из блоков живой нити)."""
    if style == "cat":
        style = "pill"
    if style == "pill" and focus == "cc":      # 20.10.2026: «Центр» — Сторож, день недели, кофеин
        return "ccp"
    return "cat" if style == "pill" and focus == "cat" else style


class CatWatch:
    """Чем жив кот: занятый терминал (заголовок окна со спиннером), музыка,
    помидор; обложка, строки песни, эквалайзер cava. Опрос раз в 2 с — только пока кот
    нужен (капсула «Котик» или его страница); кадры и cava — только пока его видно."""

    def __init__(self, app):
        self.app, self.GLib = app, app.GLib
        self.s = {"busy": False, "p": None, "pomo": None, "lines": None, "art8": None, "art24": None,
                  "eq": [], "eq8": [], "eqw": [], "pet_t": -99.0, "ran": 0, "pets": 0}
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
        return c["on"] and ("cat" in page_ids(c) or "music" in page_ids(c))

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
        self.like_poll(p)
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

    def like_poll(self, p):
        """«Нравится» текущего трека (player_like.py): при смене трека (через 1,5 с — плеер
        перерисовывает кнопку не сразу) и раз в 15 с, пока открыта страница музыки (лайк могли
        поставить в самом плеере или F10)."""
        if p is None:
            self.like_key, self.s["like"] = None, None
            return
        k = (p.name, p.title)
        now = time.monotonic()
        new = k != getattr(self, "like_key", None)
        if not new and (now - self.like_t < 15 or not any(
                isl.mode == "card" and self.app.pages and
                self.app.pages[isl.card_i % len(self.app.pages)][0] == "music" for isl in self.app.wins.values())):
            return
        if new:
            self.s["like"] = None
        self.like_key, self.like_t = k, now
        import threading
        threading.Thread(target=self.like_run, args=(k, "state", 1.5 if new else 0), daemon=True).start()

    def like_toggle(self):
        k = getattr(self, "like_key", None)
        if not k or self.s.get("like") not in ("liked", "not"):
            return
        self.s["like"] = "not" if self.s["like"] == "liked" else "liked"     # сразу, ответ поправит
        self.like_t = time.monotonic()
        self.app.redraw_cat()
        import threading
        threading.Thread(target=self.like_run, args=(k, "toggle"), daemon=True).start()

    def like_run(self, k, action, delay=0.0):
        time.sleep(delay)
        if k != self.like_key:
            return
        inst = k[0][len(Music.MPRIS):] if k[0].startswith(Music.MPRIS) else k[0]
        try:
            out = subprocess.run([sys.executable, os.path.join(HERE, "player_like.py"), action, inst],
                                 capture_output=True, text=True, timeout=10).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            out = ""
        if out in ("liked", "not", "unsupported"):
            self.GLib.idle_add(lambda: self.set_like(k, out) and False)

    def set_like(self, k, st):
        if k == self.like_key and self.s.get("like") != st:
            self.s["like"] = st
            self.app.redraw_cat()

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
            self.kick()

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
        music = playing and any(isl.mode == "card" and isl.app.pages and
                                isl.app.pages[isl.card_i % len(isl.app.pages)][0] == "music" for isl in vis)
        self.anim_id = self.GLib.timeout_add(60 if music else CAT_FRAME_MS if fast else 1000, self.frame)
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
            if len(v) >= 64:
                self.s["eqw"] = v[:64]
                self.s["eq8"] = [max(v[i:i + 8]) for i in range(0, 64, 8)]
                self.s["eq"] = [max(v[i:i + 16]) for i in range(0, 64, 16)]
        return True

    def stop_cava(self, watch=True):
        c, self.cava = self.cava, None
        self.cava_off = 0.0
        self.s["eq"] = self.s["eq8"] = self.s["eqw"] = []
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


class OsdWatch:
    """Громкость, микрофон и яркость — индикатором в островке (20.10.2026, одобрено из списка
    AngelOS: «всплывающие индикаторы громкости, микрофона и яркости прямо в островке»).
    pactl subscribe будит (только события sink/source), уровень читается wpctl в потоке и
    сравнивается с прежним — показывается лишь настоящее изменение. Яркость ноутбука —
    uevent backlight (GUdev), MSI — файл ~/.cache/msi-brightness (monitor_brightness.py).
    Пока открыта шторка микшера eww (eww-vol.open) или приглушает простой — молчит.
    Файл OSD_FLAG (pid островка) говорит volume_manager.sh: шторку на клавишах не открывать."""
    MSI = os.path.expanduser("~/.cache/msi-brightness")
    DIM = os.path.expanduser("~/.cache/idle-backlight")
    OFF = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-screens-off.json")

    def __init__(self, app):
        self.app, self.GLib = app, app.GLib
        self.last = {}
        self.t = None
        self.busy = False
        self.proc = None
        self.dim_seen = (os.path.exists(self.DIM), 0.0)
        self.flag()
        import threading
        threading.Thread(target=self.prime, daemon=True).start()
        self.start()
        self.watch_light()

    def flag(self):
        """Файл с pid островка, пока индикатор включён: volume_manager.sh не откроет шторку."""
        try:
            if self.app.conf["osd"]:
                with open(OSD_FLAG, "w") as f:
                    f.write(str(os.getpid()))
            else:
                os.remove(OSD_FLAG)
        except OSError:
            pass

    def stop(self):
        try:
            os.remove(OSD_FLAG)
        except OSError:
            pass
        if self.proc:
            try:
                self.proc.terminate()
            except OSError:
                pass

    @staticmethod
    def level(target):
        try:
            out = subprocess.run(["wpctl", "get-volume", target], capture_output=True, text=True,
                                 timeout=2).stdout
            return (round(float(out.split("Volume:")[1].split()[0]), 2), "[MUTED]" in out)
        except (OSError, subprocess.SubprocessError, IndexError, ValueError):
            return None

    def prime(self):
        self.last["sink"] = self.level("@DEFAULT_AUDIO_SINK@")
        self.last["source"] = self.level("@DEFAULT_AUDIO_SOURCE@")

    def start(self):
        try:
            self.proc = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, preexec_fn=pdeathsig)
        except OSError:
            self.GLib.timeout_add_seconds(5, lambda: self.start() and False)
            return
        ch = self.GLib.IOChannel.unix_new(self.proc.stdout.fileno())
        self.GLib.io_add_watch(ch, self.GLib.PRIORITY_DEFAULT, self.GLib.IO_IN | self.GLib.IO_HUP, self.on_line)

    def on_line(self, _ch, cond):
        line = self.proc.stdout.readline() if not cond & self.GLib.IO_HUP else b""
        if not line:
            self.GLib.timeout_add_seconds(3, lambda: self.start() and False)
            return False
        if b"'change' on sink #" in line or b"'change' on source #" in line or b"on server" in line:
            if self.t is None:
                self.t = self.GLib.timeout_add(90, self.scan)
        return True

    def scan(self):
        self.t = None
        if self.busy:
            self.t = self.GLib.timeout_add(90, self.scan)
            return False
        self.busy = True
        import threading

        def run():
            now = {"sink": self.level("@DEFAULT_AUDIO_SINK@"), "source": self.level("@DEFAULT_AUDIO_SOURCE@")}
            self.GLib.idle_add(lambda: self.done(now) and False)
        threading.Thread(target=run, daemon=True).start()
        return False

    def done(self, now):
        self.busy = False
        for k in ("sink", "source"):
            v, old = now[k], self.last.get(k)
            self.last[k] = v
            if v is None or old is None or v == old:
                continue                        # смена устройства по умолчанию тоже даёт новое — пусть
            if not self.app.conf["osd"] or os.path.exists(EWW_VOL_OPEN):
                continue
            pct, muted = int(round(v[0] * 100)), v[1]
            if k == "sink":
                self.app.osd(G_VOL_OFF if muted or not pct else G_VOL,
                             "Звук  %d%%%s" % (pct, " · выкл" if muted else ""), 0 if muted else v[0])
            elif time.monotonic() >= getattr(self.app.calls, "quiet", 0):
                self.app.osd(G_MIC_OFF if muted else G_MIC,
                             "Микрофон  %d%%%s" % (pct, " · выкл" if muted else ""), 0 if muted else v[0])

    # — яркость —
    def dimming(self):
        """Яркость меняет простой (idle_dim) — не показывать: сейчас и 4 с после смены."""
        d = os.path.exists(self.DIM) or os.path.exists(self.OFF)
        if d != self.dim_seen[0]:
            self.dim_seen = (d, time.monotonic())
        return d or time.monotonic() - self.dim_seen[1] < 4

    def watch_light(self):
        try:
            import gi
            gi.require_version("GUdev", "1.0")
            from gi.repository import GUdev
            self.udev = GUdev.Client.new(["backlight"])
            self.udev.connect("uevent", self.on_backlight)
            self.bl = {d.get_sysfs_path(): self.bl_level(d) for d in self.udev.query_by_subsystem("backlight")}
        except Exception as e:
            log("osd: backlight недоступен:", e)
        try:
            self.msi_last = _read(self.MSI).strip()
            self.msi_mon = self.app.Gio.File.new_for_path(self.MSI).monitor_file(
                self.app.Gio.FileMonitorFlags.NONE, None)
            self.msi_mon.connect("changed", self.on_msi)
        except Exception as e:
            log("osd: msi:", e)

    @staticmethod
    def bl_level(d):
        try:
            return d.get_sysfs_attr_as_int("brightness") / max(1, d.get_sysfs_attr_as_int("max_brightness"))
        except Exception:
            return None

    def on_backlight(self, _c, action, dev):
        if action != "change":
            return
        v = self.bl_level(dev)
        old = self.bl.get(dev.get_sysfs_path())
        self.bl[dev.get_sysfs_path()] = v
        if v is None or old is None or abs(v - old) < 0.005 or self.dimming() or not self.app.conf["osd"]:
            return
        self.app.osd(G_SUN, "Яркость  %d%%" % round(v * 100), v, out="eDP-1")

    def on_msi(self, _m, _f, _o, ev):
        Gio = self.app.Gio
        if ev not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            return
        v = _read(self.MSI).strip()
        old, self.msi_last = self.msi_last, v
        if v == old or not v.isdigit() or self.dimming() or not self.app.conf["osd"]:
            return
        self.app.osd(G_SUN, "Яркость  %s%%" % v, int(v) / 100, out="DP-4")


class Island:
    """Одна поверхность на монитор; общее состояние — у App."""

    def __init__(self, app, monitor, output):
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import Gdk, Gtk, GtkLayerShell
        self.app, self.output, self.monitor = app, output, monitor
        self.scrims = []                 # слои «щелчок мимо — свернуть», пока карточка раскрыта
        self.in_rect = None              # (x, y, w, h) входной области островка на поверхности
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
        self.ctl_used = False            # крутили/жали капсулу — наведение не раскрывает до ухода
        self.scroll_acc = 0.0            # тачпад: доли щелчка колеса копятся
        self.bub = False                 # пузырь ▶ показан — входная зона шире
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
                     Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.SCROLL_MASK |
                     Gdk.EventMask.KEY_PRESS_MASK)
        w.connect("draw", self.on_draw)
        w.connect("key-press-event", lambda _w, e: self.app.pw_key(e))   # только пароль Wi-Fi
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
        # полка: файл, брошенный на островок, ложится на страницу «Полка»
        from gi.repository import Gtk as _Gtk
        w.drag_dest_set(_Gtk.DestDefaults.MOTION | _Gtk.DestDefaults.DROP, [], Gdk.DragAction.COPY)
        w.drag_dest_add_uri_targets()
        w.connect("drag-motion", self.on_drop_motion)
        w.connect("drag-leave", self.on_drop_leave)
        w.connect("drag-data-received", self.on_drop)

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
            style = eff_style(self.app.conf["thread_style"], self.app.pill_focus())
            if self.app.dl and style not in PILLS:
                style = "pill"
            if style in PILLS:
                import cairo
                cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
                if style == "cat":
                    w = cat_w(cr, self.app.cat.s, self.design())
                elif style == "ccp":
                    w = cc_pill_w()
                else:
                    w = pill_w(cr, self.app.pill_acts(), self.app.col, self.design())
                if self.app.dl:                 # загрузка — панель под капсулой
                    return (max(w, float(DL_W)), float(PILL_H + DL_H))
                return (w, float(PILL_H))
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
        sk = SK_EXTRA if self.design().get("line") else 0      # Skeet: радуга и вкладки сверху
        return (float(CARD_W), float(self.app.card_h(pages[self.card_i % len(pages)][0], bool(sk)) + sk))

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
        self.cover(mode == "card")
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
                self.app.lyr_seen(self.output, False)
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
        elif self.mode == "thread" and (self.app.conf["thread_style"] in PILLS or self.app.dl):
            r = cairo.Region(cairo.RectangleInt(x - 6, 0, int(w) + 12, ty + int(h) + 4))
            if self.bub:
                r.union(cairo.RectangleInt(x + int(w), 0, BUBBLE_GAP + PILL_H + 8, ty + int(h) + 6))
        elif self.mode == "thread" and h <= THREAD_H + 2:   # в 3-px линию не попасть — зона шире
            r = cairo.Region(cairo.RectangleInt(x - HOVER_PAD, 0, int(w) + 2 * HOVER_PAD, y + int(h) + 8))
            if self.bub:
                r.union(cairo.RectangleInt(x + int(w), 0, BUBBLE_GAP + 26, ty + 30))
        else:
            r = cairo.Region(cairo.RectangleInt(x, y, int(math.ceil(w)), int(math.ceil(h))))
        gw.input_shape_combine_region(r, 0, 0)
        e = r.get_extents()
        rect = (e.x, e.y, e.width, e.height)
        self.in_rect = rect

    def cover(self, on):
        """Раскрытая карточка: прозрачные слои во весь каждый монитор (scrim_layer.Scrim, как у
        меню), щелчок по ним — свернуть. 20.10.2026, просьба: «если хочу закрыть его быстро —
        кликнуть куда угодно вне островка». Слои выше островка, поэтому на его месте в их
        входной области дыра; при перетаскивании снимка слоёв нет — иначе не бросить в чат."""
        from gi.repository import GtkLayerShell
        if not on or self.dragging:
            for s in self.scrims:
                s.destroy()
            if self.scrims:
                GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.TOP)
            self.scrims = []
            return
        if self.scrims:
            return
        # 20.10.2026: была дыра во входной области слоя под островок — но островок встаёт под
        # верхним баром, а слой от края экрана, и дыра съезжала: щелчки и колесо по карточке
        # ловил слой («по клику на блоки не работает»). Теперь островок на время — OVERLAY.
        GtkLayerShell.set_layer(self.win, GtkLayerShell.Layer.OVERLAY)
        try:
            from gi.repository import Gdk, GLib
            from scrim_layer import Scrim
            disp = Gdk.Display.get_default()
            for i in range(disp.get_n_monitors()):
                # 20.10.2026, просьба: «после закрытия кликом при наведении больше не
                # раскрывается». Закрытие по НАЖАТИЮ уничтожало слой посреди щелчка — GTK
                # оставался с неявным захватом мыши на мёртвом окне и не слал островку
                # enter/leave. Теперь — по отпусканию, а сам слой убирается после, в простое.
                s = Scrim(disp.get_monitor(i), NAMESPACE + "-catch", lambda: None)
                s.add_events(Gdk.EventMask.BUTTON_RELEASE_MASK)
                s.connect("button-release-event", lambda *_a: GLib.idle_add(self.click_away) and True)
                s.show_all()
                self.scrims.append(s)
        except Exception as e:
            log("слой «щелчок мимо»: %s" % e)

    def click_away(self):
        if self.mode != "card" or self.dragging:
            return False
        self.app.pw_stop()                      # щелчок мимо — ввод пароля закончен
        if self.leave_t:
            from gi.repository import GLib
            GLib.source_remove(self.leave_t)
            self.leave_t = None
        self.app.pop_until = 0
        self.collapse()
        return False

    def on_draw(self, _w, cr):
        font_opts(cr)
        st = {"w": self.geo[0], "h": self.geo[1], "mode": self.mode, "alpha": self.alpha,
              "acts": self.app.pill_acts() if self.mode == "thread" else self.app.ordered(0),
              "th": self.app.th, "ty": self.ty(), "pk": self.app.pill_focus(),
              "pages": self.app.pages, "card_i": self.card_i, "style": self.app.conf["thread_style"],
              "ta": self.thread_alpha(), "cat": self.app.cat.s,
              "dl": self.app.dl if self.mode == "thread" else None,
              "ccp": self.app.sys.get("pill") if self.mode == "thread" else None}
        night = NIGHT_A.get(self.mode) if self.app.night() and not self.hovered else None
        if night:                               # ночное притемнение — всё нарисованное разом
            cr.push_group()
        _LYR["on"] = False
        self.hits = paint(cr, st, self.app.col, self.design())
        self.app.lyr_seen(self.output, _LYR["on"] and self.mode != "none")
        if night:
            cr.pop_group_to_source()
            cr.paint_with_alpha(night)
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
        страницу»), и при звонке тоже (20.10.2026, просьба: «почему… сразу блок со звонками? А не
        блок, в котором я был последний раз»). Нет такой страницы — главное дело, иначе первая."""
        acts = self.app.acts
        pages = self.app.pages
        keys = [page_key(p) for p in pages]
        if self.app.last in keys:
            self.card_i = keys.index(self.app.last)
        else:
            self.card_i = next((i for i, p in enumerate(pages) if acts and p[0] == acts[0][0]), 0)
        self.app.pop_until = 0
        if "clip" in page_ids(self.app.conf):   # снимки грузятся заранее, пока карточка раскрывается
            self.app.load_clip()
        self.app.sys_reset()
        if pages and pages[self.card_i % len(pages)][0] in self.app.sys_ui:
            self.app.poll_sys(pages[self.card_i % len(pages)][0])
        if self.design().get("line") and {"wifi", "bt"} & set(page_ids(self.app.conf)):
            self.app.poll_sys("radio")          # цвет значков вкладок Wi-Fi/Bluetooth
        self.go("card")

    def controls(self):
        """Капсула управляет плеером/микрофоном: живая нить (или котик) свёрнута, и есть чем."""
        if self.mode != "thread" or self.app.conf["thread_style"] not in PILLS:
            return False
        return bool(self.app.call_on() or (self.app.music and self.app.music.player()))

    def ctl_touch(self):
        """Капсулой управляют — отложенное раскрытие наведением отменить до ухода курсора."""
        from gi.repository import GLib
        self.ctl_used = True
        if self.open_t:
            GLib.source_remove(self.open_t)
            self.open_t = None

    def on_click(self, _w, e):
        from gi.repository import Gdk
        if e.type != Gdk.EventType.BUTTON_PRESS:
            # двойной щелчок GTK досылает лишним событием (2BUTTON_PRESS) — переключатель
            # срабатывал второй раз: «кнопки на миллисекунду включаются и выключаются» (20.10.2026)
            return True
        kind = self.app.acts[0][0] if self.app.acts else None
        if e.button == 3:
            act = self.hit_at(e.x, e.y) if self.mode == "card" else None
            if act and act[0] in SYS_PAGES:     # ПКМ по плитке «Центра» — второе действие
                self.app.sys_do(act, 3)
                return True
            if self.mode == "thread" and self.app.pages:   # свёрнута: ПКМ раскрывает (ЛКМ — пауза)
                self.open_card()
                return True
            self.app.pop_until = 0
            self.go("thread" if self.app.want_thread(self.output) else "none")
            return True
        if e.button == 2 and kind:
            self.app.primary_action(kind)
            return True
        if e.button != 1:
            return True
        act = self.hit_at(e.x, e.y)
        if act is None and self.controls() and self.app.pill_focus() == "music":
            # 20.10.2026, просьба: «на свёрнутой капсуле… ЛКМ — пауза»
            self.ctl_touch()
            self.app.do(("music", "PlayPause"))
            return True
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
        elif act[0] == "shelf":
            self.press = (e.x, e.y, act)
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
        if p[2][0] == "shelf":
            it = self.app.shelf_item(p[2][1])
            path = it["path"] if it and os.path.exists(it["path"]) else None
        else:
            path = self.app.clip_path(p[2][1])
        if not path:
            return False
        self.drag_path = path
        self.dragging = True
        self.cover(False)
        tl = Gtk.TargetList.new([])
        tl.add_uri_targets(0)
        self.win.drag_begin_with_coordinates(tl, Gdk.DragAction.COPY, 1, e, int(e.x), int(e.y))
        return True

    def shelf_i(self):
        return next((i for i, p in enumerate(self.app.pages) if p[0] == "shelf"), None)

    def on_drop_motion(self, _w, ctx, _x, _y, t):
        """Чужой файл над островком — раскрыть на «Полке»."""
        from gi.repository import GLib
        if self.dragging:
            return False
        i = self.shelf_i()
        if i is None:
            return False
        if self.leave_t:
            GLib.source_remove(self.leave_t)
            self.leave_t = None
        if self.mode != "card" or self.card_i != i:
            self.card_i = i
            self.app.pop_until = 0
            self.go("card")
        return True

    def on_drop_leave(self, *_a):
        from gi.repository import GLib
        if self.mode == "card" and not self.hovered and not self.leave_t:
            self.leave_t = GLib.timeout_add(self.keep_ms(), self.collapse)

    def on_drop(self, _w, ctx, _x, _y, sel, _info, t):
        from gi.repository import GLib, Gtk
        if self.dragging or self.shelf_i() is None:
            return
        paths = [GLib.filename_from_uri(u)[0] for u in sel.get_uris() or [] if u.startswith("file://")]
        if paths:
            self.app.shelf_add(paths)
            self.card_i = self.shelf_i() or 0
            self.go("card")
        if self.leave_t:
            GLib.source_remove(self.leave_t)
        self.leave_t = GLib.timeout_add(self.keep_ms() + 1500, self.collapse)

    def on_drag_begin(self, _w, ctx):
        """Под курсором — уменьшенный снимок."""
        from gi.repository import Gtk
        if self.press and self.press[2][0] == "shelf":
            it = self.app.shelf_item(self.press[2][1])
            pb = it.get("pb") if it else None
            if pb is not None:
                Gtk.drag_set_icon_pixbuf(ctx, pb, pb.get_width() // 2, pb.get_height() // 2)
            return
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
        self.cover(self.mode == "card")
        if not self.hovered and self.mode == "card":
            if self.leave_t:
                GLib.source_remove(self.leave_t)
            self.leave_t = GLib.timeout_add(self.keep_ms(), self.collapse)

    def keep_ms(self):
        """Сколько карточка держится после ухода курсора: «Держать раскрытым» (pop_sec).
        20.10.2026, просьба: «меняю его и всё равно с одной длительностью закрывается» — раньше
        тут были зашиты 0,65 с (наведение) и 2,2 с (щелчок), а pop_sec правил только события."""
        try:
            return int(max(0.3, float(self.app.conf["pop_sec"])) * 1000)
        except (TypeError, ValueError):
            return LEAVE_MS

    def on_scroll(self, _w, e):
        """Колесо листает страницы; над нитью/компактом — раскрывает карточку. Громкость и
        перемотка колесом по капсуле убраны (20.10.2026, просьба: «хочу нормально скроллить, чтобы
        переходить по блокам»)."""
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
        if self.app.sys_scroll(self.app.pages[self.card_i % n][0], step, bool(self.design().get("line"))):
            return True                         # раскрытый список Wi-Fi/Bluetooth листается колесом
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
        if self.app.night():
            self.win.queue_draw()               # ночью под курсором — в полную яркость
        if self.mode in ("thread", "compact") and self.app.conf["hover"] and not self.open_t \
                and not self.ctl_used:
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
        self.ctl_used = False
        self.scroll_acc = 0.0
        if self.open_t:
            GLib.source_remove(self.open_t)
            self.open_t = None
        if self.app.night():
            self.win.queue_draw()
        if self.mode != "card":
            self.win.queue_draw()
            return False
        if self.leave_t:
            GLib.source_remove(self.leave_t)
        self.leave_t = GLib.timeout_add(self.keep_ms(), self.collapse)
        return False

    def collapse(self):
        self.leave_t = None
        if self.dragging:                       # снимок ещё тащат — карточку держать
            return False
        if self.app.sys_editing():              # вводят пароль Wi-Fi — курсор мог уйти
            return False
        self.opened_by_hover = False
        if self.mode == "card":
            self.go("thread" if self.app.want_thread(self.output) else "none")
        return False


class NudgeWatch:
    """«Пора к делу» (island_nudge.py): раз в NUDGE_POLL_S с — что в фокусе (опрос в потоке:
    niri, ps, экранное время); серия дольше nudge_min минут — фраза печатается в компакте, потом
    раз в nudge_every минут — другая. Ничего не закрывает — только показывает."""

    def __init__(self, app):
        import island_nudge
        self.N, self.app = island_nudge, app
        self.streaks = island_nudge.Streaks()
        self.kind = None             # что было в фокусе при последнем опросе
        self.busy = False
        app.GLib.timeout_add_seconds(NUDGE_POLL_S, self.poll)

    def mins(self):
        c = self.app.conf
        try:
            return max(1.0, float(c["nudge_min"])) * 60, max(1.0, float(c["nudge_every"])) * 60
        except (TypeError, ValueError):
            return DEFAULTS["nudge_min"] * 60, DEFAULTS["nudge_every"] * 60

    def poll(self):
        if self.busy or not self.app.conf["on"] or "nudge" not in page_ids(self.app.conf):
            return True
        self.busy = True
        import threading
        threading.Thread(target=self.run, daemon=True).start()
        return True

    def run(self):
        try:
            smp = self.N.sample()
        except Exception as e:
            log("nudge:", e)
            smp = {"locked": False, "kind": None}
        self.app.GLib.idle_add(self.done, smp)

    def done(self, smp):
        self.busy = False
        before = self.current() is None
        min_s, every_s = self.mins()
        fire = self.streaks.tick(smp, min_s, every_s)
        self.kind = smp.get("kind")
        if fire:
            self.app.nudge_fire(fire)
        elif before != (self.current() is None):
            self.app.refresh()
        return False

    def current(self):
        min_s, _e = self.mins()
        k = self.streaks.active(min_s)
        if not k:
            return None
        d = dict(self.streaks.s[k], kind=k, here=k == self.kind)
        d["t0"] = self.app.nudge_t0 if self.app.nudge_kind == k else None
        return d

    def demo(self, text=None):
        """island.py nudge [ТЕКСТ] — показать напоминание сейчас (серия «Проверка», уходит за минуту)."""
        min_s, _e = self.mins()
        self.streaks.s["demo"] = {"sec": min_s, "away": self.N.BREAK_S - 60, "level": 1, "next": 1e12,
                                  "start": time.time() - min_s, "text": text or self.N.phrase("any", 0),
                                  "what": "Проверка", "today": None, "t": time.monotonic()}
        self.app.nudge_fire("demo")


class DlWatch:
    """Загрузки (island_dl.py): раз в DL_POLL_S с — замер в потоке (папка «Загрузки», Steam,
    curl/wget/yt-dlp, pacman). Пока что-то качается — app.dl, полоска в живой капсуле; у
    «бегущей» — свои кадры раз в DL_FRAME_MS, только на мониторах с нитью."""

    def __init__(self, app):
        import island_dl
        self.M, self.app = island_dl, app
        self.d = island_dl.Downloads()
        self.busy = self.anim = False
        self.done_until = 0.0
        app.GLib.timeout_add_seconds(DL_POLL_S, self.poll)

    def poll(self):
        if self.busy:
            return True
        if not (self.app.conf["on"] and self.app.conf["downloads"]):
            if self.app.dl:
                self.app.dl = None
                self.app.refresh()
            return True
        self.busy = True
        import threading
        threading.Thread(target=self.run, daemon=True).start()
        return True

    def run(self):
        try:
            items = self.d.scan()
        except Exception as e:
            log("загрузки:", e)
            items = []
        self.app.GLib.idle_add(self.done, items)

    def done(self, items):
        self.busy = False
        was = self.app.dl
        now = time.monotonic()
        dl = self.M.summary(items)
        if dl:
            self.done_until = 0.0
        elif was and not was.get("done"):              # закончилась — полная полоска на миг
            self.done_until = now + DL_DONE_S
            dl = dict(was, done=True)
        elif was and was.get("done") and now < self.done_until:
            dl = was
        if (dl is None) != (was is None):
            log("загрузка:", "%s (%d)" % (dl["name"], dl["n"]) if dl and not dl.get("done") else "готово" if dl
                else "нет")
        self.app.dl = dl
        if (dl is None) != (was is None):
            self.app.refresh()                          # нить могла появиться или уйти
        else:
            self.app.redraw()
        if dl and dl.get("pr") is None and not dl.get("done") and not self.anim:
            self.anim = True
            self.app.GLib.timeout_add(DL_FRAME_MS, self.frame)
        return False

    def frame(self):
        dl = self.app.dl
        if not dl or dl.get("pr") is not None or dl.get("done"):
            self.anim = False
            return False
        for isl in self.app.wins.values():
            if isl.mode == "thread":
                isl.win.queue_draw()
        return True


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
        self.shelf = {"items": []}
        self.shelf_set(shelf_load())
        self.sys = {}                # «Центр», Wi-Fi, Bluetooth: последнее состояние (island_sys.py)
        self.sys_ui = {"cc": {}, "wifi": {}, "bt": {}, "power": {}}   # спектр, выбранное, вопрос питания
        self.sys_polling = set()
        self.sys_again = set()       # просили опросить, пока шёл прежний опрос
        self.sys_gen = {}            # номер последнего действия: опрос, начатый раньше, отбрасывается
        self.sys_pin = {}            # {k: {поле: (нажатое, до)}} — держать, пока команда применяется
        self.sys_ticks = 0
        self.sys_timer = None
        self.clip_t = 0.0
        self.bar_outs = set()        # мониторы с постоянным верхним waybar — без нити
        self.space_t = None
        self.sig = None              # (вид, фаза) главного дела — смена = событие
        self.pop_until = 0.0
        self.flash = None            # {"text","icon","until"[,"pr","out"]}
        self.track_sig = None        # (плеер, название) играющего трека — смена = название на 5 с
        self.pop_kind = None         # чьё событие раскрыло компакт (music — трек вперёд)
        self.vol = {"q": 0, "busy": False, "cache": None}   # колесо громкости: очередь и потоки плеера
        self.osdw = None
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
        self.nudge_t0 = self.nudge_kind = None      # последнее напоминание: когда и о чём
        self.nudge_anim_on = False
        self.bar_up = {}                            # монитор → до когда показан верхний бар (top_bar.py)
        self.dl = None                              # загрузка сейчас (DlWatch): {"n", "pr", "rate", "name"}
        try:
            self.dlw = DlWatch(self)
        except Exception as e:
            log("загрузки недоступны:", e)
            self.dlw = None
        try:
            self.nudgew = NudgeWatch(self)
        except Exception as e:
            log("nudge недоступен:", e)
            self.nudgew = None
        self.last = _read(LAST).strip()          # страница, на которой остановились
        self.info = _read(LAST_INFO).strip()     # последний блок с инфо — его показывает живая нить
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
        try:
            self.osdw = OsdWatch(self)
        except Exception as e:
            log("osd:", e)
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
        if any(p in SYS_PAGES for p in ids) and self.sys_timer is None:
            self.sys_timer = self.GLib.timeout_add_seconds(3, self.sys_tick)

    # — «Центр», Wi-Fi, Bluetooth (20.10.2026): опрос только пока такая страница раскрыта —
    def sys_pages(self):
        out = {k: dict(self.sys.get(k) or {"loading": True}, **self.sys_ui.get(k, {}))
               for k in ("cc", "wifi", "bt")}
        out["power"] = dict(self.sys_ui["power"])
        for k in ("wifi", "bt"):
            out[k]["radio"] = (self.sys.get("radio") or {}).get(k)
        return out

    def skeet_card_open(self):
        return any(isl.mode == "card" and isl.design().get("line") for isl in self.wins.values())

    def card_h(self, kind, sk):
        """Высота страницы карточки: Wi-Fi/Bluetooth растут вниз (кнопки выбранной строки, «Ещё…»)."""
        if kind in ("wifi", "bt"):
            return sys_list_h(kind, dict(self.sys.get(kind) or {}, **self.sys_ui[kind]), sk)
        return CARD_HK.get(kind, CARD_H)

    def resize_cards(self):
        for isl in self.wins.values():
            if isl.mode == "card":
                isl.go("card")

    def sys_reset(self):
        """Карточку открыли заново — без хвостов прошлого раза: вопрос питания, раскрытые списки,
        выбранная строка, пароль. Идущее подключение (busy) остаётся."""
        self.pw_stop()
        self.sys_ui["cc"].pop("spec", None)
        self.sys_ui["power"].pop("ask", None)
        for k in ("wifi", "bt"):
            for f in ("more", "sel", "ask", "off", "pw", "msg"):
                self.sys_ui[k].pop(f, None)

    def sys_scroll(self, kind, step, sk):
        """Колесо по раскрытому списку («Ещё…») листает его; у края — страницы, но не тем же
        движением колеса (0,5 с тишины), иначе список проскакивал бы в соседний блок."""
        ui = self.sys_ui.get(kind)
        if kind not in ("wifi", "bt") or not ui.get("more"):
            return False
        d = dict(self.sys.get(kind) or {}, **ui)
        items = sys_items(kind, d)
        selp = SYS_SELP if d.get("sel") in [sys_key(kind, it) for it in items] else 0
        top = 16 if sk else 36
        n = max(1, int((self.card_h(kind, sk) - 6 - (top + 30) - selp) // SYS_RH))
        hi = max(0, len(items) - n)
        off = max(0, min(int(ui.get("off", 0)), hi))
        new = max(0, min(off + step, hi))
        now = time.monotonic()
        if new == off:
            return now - ui.get("off_t", 0) < 0.5
        ui["off"], ui["off_t"] = new, now
        self.redraw()
        return True

    def sys_open(self):
        """Какая системная страница сейчас раскрыта (на любом мониторе) — её и опрашивать."""
        for isl in self.wins.values():
            if isl.mode == "card" and self.pages:
                k = self.pages[isl.card_i % len(self.pages)][0]
                if k in self.sys_ui:
                    return k
        return None

    def sys_tick(self):
        if not any(p in SYS_PAGES for p in page_ids(self.conf)) or not self.conf["on"]:
            self.sys_timer = None
            return False
        k = self.sys_open()
        if k:
            self.poll_sys(k)
        self.sys_ticks += 1
        if self.sys_ticks % 2 == 0 and eff_style(self.conf["thread_style"], self.pill_focus()) == "ccp" \
                and any(isl.mode == "thread" for isl in self.wins.values()):
            self.poll_sys("pill")               # капсула «Центра»: кофеин, таурин, Сторож — раз в 6 с
        if self.sys_ticks % 2 == 1 and k not in ("wifi", "bt") and self.skeet_card_open() \
                and {"wifi", "bt"} & set(page_ids(self.conf)):
            self.poll_sys("radio")              # значки вкладок Wi-Fi/Bluetooth — раз в 6 с
        return True

    def poll_sys(self, k):
        """Состояние страницы k — в потоке (nmcli, bluetoothctl, busctl), ответ в цикл GTK.
        Опрос, начатый до последнего действия, состояние не пишет (sys_gen): старое не перебивает
        уже показанное новое — кнопки не мигают (20.10.2026, просьба: «на миллисекунду
        включается и выключается»). Просьба во время опроса — ещё один опрос после него."""
        if k not in SYS_POLL:
            return
        if k in self.sys_polling:
            self.sys_again.add(k)
            return
        self.sys_polling.add(k)
        gen = self.sys_gen.get(k, 0)
        new = bool(self.sys_ui.get(k, {}).get("more"))
        import threading

        def run():
            st = None
            try:
                import island_sys
                if k == "cc":
                    st = island_sys.cc_state()
                    st["avatar"] = island_sys.avatar_png(40)
                elif k == "wifi":
                    st = island_sys.wifi_state()
                elif k == "bt":
                    st = island_sys.bt_state(new=new)
                elif k == "radio":
                    st = island_sys.radio_state()
                else:
                    st = island_sys.pill_state()
            except Exception as e:
                log("island_sys", k, e)
            self.GLib.idle_add(lambda: self.sys_set(k, st, gen) and False)
        threading.Thread(target=run, daemon=True).start()

    def sys_set(self, k, st, gen=None):
        self.sys_polling.discard(k)
        if k in self.sys_again:
            self.sys_again.discard(k)
            self.GLib.idle_add(lambda: self.poll_sys(k) and False)
        if st is None or gen is not None and gen != self.sys_gen.get(k, 0):
            return
        now = time.monotonic()
        pins = self.sys_pin.get("cc" if k == "pill" else k) or {}
        for f, (v, until) in list(pins.items()):
            if now < until and st.get(f) != v:
                st[f] = v                       # команда ещё применяется — держим нажатое
            elif k != "pill":
                pins.pop(f)
        if k == "radio":                        # значки вкладок Wi-Fi/Bluetooth в карточке Skeet
            if st != self.sys.get("radio"):
                self.sys["radio"] = st
                self.refresh()
                self.redraw()
            return
        self.sys[k] = st
        if k in ("wifi", "bt"):                 # полный опрос страницы — заодно и значок вкладки
            self.radio_set(k, st)
        if k == "cc":                           # капсула «Центра» — из того же состояния
            self.sys["pill"] = {f: st.get(f) for f in ("caffeine", "taurine", "guard")}
        if k in ("cc", "pill"):
            for isl in self.wins.values():
                if isl.mode == "thread":
                    isl.win.queue_draw()
        if self.sys_open() == k:
            self.refresh()
            self.resize_cards()
            self.redraw()

    def radio_set(self, k, st):
        on = bool(st.get("on"))
        conn = any(x.get("in_use") if k == "wifi" else x.get("conn") for x in sys_items(k, st))
        self.sys["radio"] = dict(self.sys.get("radio") or {}, **{k: 2 if on and conn else 1 if on else 0})

    def sys_bg(self, kind, fn, *args, after=None):
        """Команда island_sys в потоке; опросы, начатые до неё, больше не в счёт."""
        import threading
        self.sys_gen[kind] = self.sys_gen.get(kind, 0) + 1
        if kind == "cc":
            self.sys_gen["pill"] = self.sys_gen.get("pill", 0) + 1

        def run():
            res = None
            try:
                res = fn(*args)
            except Exception as e:
                log("island_sys", kind, fn.__name__, e)
            self.GLib.idle_add(lambda: self.sys_done(kind, after, res) and False)
        threading.Thread(target=run, daemon=True).start()

    def sys_pin_set(self, kind, **kw):
        until = time.monotonic() + 4
        self.sys_pin.setdefault(kind, {}).update({f: (v, until) for f, v in kw.items()})

    def sys_do(self, act, button=1):
        """Действие системной страницы: ЛКМ (1) или ПКМ (3). Видно сразу: состояние меняется
        заранее и держится, пока опрос не согласится (sys_pin); команда — в потоке."""
        import island_sys
        kind, what = act
        if kind == "power":
            ui = self.sys_ui["power"]
            if button != 1:
                return
            if what == "lock":                  # замок — сразу, как Super+O
                self.collapse_all()
                island_sys.power("lock")
                return
            if what in POWER_ASK:               # остальное — сперва «точно?» (20.10.2026)
                ui["ask"] = what
            elif what == "no":
                ui.pop("ask", None)
            elif what.startswith("yes:") and what[4:] in POWER_ASK:
                ui.pop("ask", None)
                self.collapse_all()
                island_sys.power(what[4:])
                return
            self.refresh()
            self.redraw()
            return
        ui = self.sys_ui[kind]
        st = self.sys.get(kind)
        if st is None:
            return
        if kind == "cc":
            if what == "spec" or what.startswith("warm:") and button == 3 or what == "night" and button == 3:
                ui["spec"] = not ui.get("spec")
            elif what.startswith("warm:"):
                v = int(what[5:])
                st.update(night=True, warmth=v)
                self.sys_pin_set("cc", night=True, warmth=v)
                self.sys_bg("cc", island_sys.warmth, v)
            elif what == "night":
                st["night"] = not st.get("night")
                self.sys_pin_set("cc", night=st["night"])
                self.sys_bg("cc", island_sys.night, st["night"])
            elif what == "caf":
                snap = dict(st)
                if button == 1:
                    st["caffeine"] = not st.get("caffeine")
                    st["taurine"] = bool(st.get("taurine") and st["caffeine"])
                else:
                    st["taurine"] = not st.get("taurine")
                    st["caffeine"] = bool(st["caffeine"] or st["taurine"])
                self.sys_pin_set("cc", caffeine=st["caffeine"], taurine=st["taurine"])
                self.sys["pill"] = dict(self.sys.get("pill") or {}, caffeine=st["caffeine"], taurine=st["taurine"])
                self.sys_bg("cc", island_sys.caffeine, button, snap)
            elif what == "prof":
                cur = st.get("profile")
                st["profile"] = ("performance" if cur == "balanced" else "balanced") if button == 1 else \
                    ("balanced" if cur == "power-saver" else "power-saver")
                self.sys_pin_set("cc", profile=st["profile"])
                self.sys_bg("cc", island_sys.profile, button)
            else:
                return
        elif button != 1:
            return
        elif what == "power":
            st["on"] = not st.get("on")
            self.sys_pin_set(kind, on=st["on"])
            if not st["on"]:
                self.pw_stop()
                for f in ("more", "sel", "ask", "off", "scan"):
                    ui.pop(f, None)
            self.sys_gen["radio"] = self.sys_gen.get("radio", 0) + 1   # прежний опрос значков не в счёт
            self.radio_set(kind, st)
            self.sys_bg(kind, island_sys.wifi_power if kind == "wifi" else island_sys.bt_power, st["on"])
        elif what == "more":
            # 20.10.2026, просьба: «на кнопку Ещё островок растянется именно в этом блоке вниз и
            # покажет весь список» — окна бара больше не открываются
            ui["more"] = not ui.get("more")
            ui.pop("off", None)
            ui.pop("ask", None)
            if ui["more"]:
                ui["scan"] = True
                if kind == "wifi":
                    self.sys_bg(kind, island_sys.wifi_state, True, after="scan")
                else:
                    self.sys_bg(kind, lambda: (island_sys.bt_scan(), island_sys.bt_state(new=True))[1],
                                after="scan")
            else:
                ui.pop("scan", None)
                if kind == "bt":                # найденные новые — только в раскрытом списке
                    st["devs"] = [d_ for d_ in st.get("devs") or [] if d_.get("pair", True)]
                    if ui.get("sel") not in [d_["mac"] for d_ in st["devs"]]:
                        ui.pop("sel", None)
        elif what.startswith("sel:"):
            # щелчок по строке — только кнопки под ней (как в окнах бара), повторный — свернуть
            key = what[4:]
            self.pw_stop()
            for f in ("ask", "msg", "pw"):
                ui.pop(f, None)
            if ui.get("sel") == key:
                ui.pop("sel", None)
            else:
                ui["sel"] = key
        elif what == "pw":
            self.pw_start()
        elif what.startswith("btn:"):
            self.sys_btn(kind, what[4:])
            return
        else:
            return
        self.refresh()
        self.resize_cards()
        self.redraw()

    def sys_btn(self, kind, act):
        """Кнопки выбранной сети/устройства: подключиться (новой сети — с паролем), отключиться,
        забыть — вторым щелчком в течение 3 с, как в окнах бара."""
        import island_sys
        ui = self.sys_ui[kind]
        key = ui.get("sel")
        it = next((x for x in sys_items(kind, self.sys.get(kind) or {}) if sys_key(kind, x) == key), None)
        if it is None or ui.get("busy"):
            return
        if act == "forget" and ui.get("ask") != key:
            ui["ask"] = key

            def reset():
                if ui.get("ask") == key:
                    ui.pop("ask", None)
                    self.redraw()
                return False
            self.GLib.timeout_add(3000, reset)
            self.redraw()
            return
        ui.pop("ask", None)
        args = (act, it)
        if kind == "wifi":
            pw = ""
            if act == "connect" and it["secured"] and not it["known"]:
                pw = ui.get("pw") or ""
                if not pw:
                    ui["msg"] = (key, "Сначала введите пароль", False)
                    self.pw_start()
                    return
            args += (pw,)
        self.pw_stop()
        ui["busy"], ui["busy_what"] = key, act
        ui.pop("msg", None)
        self.sys_bg(kind, island_sys.wifi_do if kind == "wifi" else island_sys.bt_do, *args, after="btn:" + key)
        self.redraw()

    def sys_done(self, k, after=None, res=None):
        ui = self.sys_ui[k]
        if after == "scan":
            ui.pop("scan", None)
            if isinstance(res, dict) and ui.get("more"):   # «Свернуть» успели нажать — не нужно
                self.sys_set(k, res)
            return
        if after and after.startswith("btn:"):
            key = after[4:]
            ok, text = res if isinstance(res, tuple) else (False, "не получилось")
            ui.pop("busy", None)
            ui.pop("busy_what", None)
            m = ui["msg"] = (key, text, ok)
            if ok:
                ui.pop("pw", None)

            def clear():
                if ui.get("msg") is m:
                    ui.pop("msg", None)
                    self.redraw()
                return False
            self.GLib.timeout_add(5000, clear)
            self.redraw()
        else:
            ui.pop("busy", None)
        # кофеин и профиль применяются не мгновенно — опрос чуть позже (а пока держит sys_pin)
        self.GLib.timeout_add(500, lambda: self.poll_sys(k) and False)

    # — пароль новой сети Wi-Fi: клавиатура у островка только на время ввода —
    def sys_editing(self):
        return bool(self.sys_ui["wifi"].get("pw_on"))

    def pw_start(self):
        from gi.repository import GtkLayerShell
        self.sys_ui["wifi"]["pw_on"] = True
        for isl in self.wins.values():
            if isl.mode == "card":
                GtkLayerShell.set_keyboard_mode(isl.win, GtkLayerShell.KeyboardMode.EXCLUSIVE)
                if isl.leave_t:
                    self.GLib.source_remove(isl.leave_t)
                    isl.leave_t = None
        self.redraw()

    def pw_stop(self):
        if not self.sys_ui["wifi"].pop("pw_on", None):
            return
        from gi.repository import GtkLayerShell
        for isl in self.wins.values():
            GtkLayerShell.set_keyboard_mode(isl.win, GtkLayerShell.KeyboardMode.NONE)
        self.redraw()

    def pw_key(self, e):
        """Ввод пароля: буквы, BackSpace, Ctrl+U — стереть, Ctrl+V — вставить, Enter —
        подключиться, Esc — закончить ввод."""
        if not self.sys_editing():
            return False
        from gi.repository import Gdk
        ui = self.sys_ui["wifi"]
        name = Gdk.keyval_name(e.keyval) or ""
        ctrl = bool(e.state & Gdk.ModifierType.CONTROL_MASK)
        pw = ui.get("pw") or ""
        if name == "Escape":
            self.pw_stop()
            return True
        if name in ("Return", "KP_Enter"):
            self.sys_btn("wifi", "connect")
            return True
        if name == "BackSpace":
            ui["pw"] = pw[:-1]
        elif ctrl and name.lower() == "u":
            ui["pw"] = ""
        elif ctrl and name.lower() == "v":
            try:
                t = subprocess.run(["wl-paste", "-n"], capture_output=True, text=True, timeout=2).stdout
            except (OSError, subprocess.SubprocessError):
                t = ""
            ui["pw"] = (pw + t.strip("\r\n"))[:63]
        elif not ctrl:
            u = Gdk.keyval_to_unicode(e.keyval)
            if u and chr(u).isprintable():
                ui["pw"] = (pw + chr(u))[:63]
        ui.pop("msg", None)
        self.redraw()
        return True

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
            isl.cover(False)
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
            if self.osdw:
                self.osdw.flag()
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
        elif d.get("cmd") == "bar":            # top_bar.py: верхний бар «при наведении» показан/спрятан
            now = time.monotonic()
            before = {o for o, t in self.bar_up.items() if t > now}
            for o in d.get("outs") or ():
                if d.get("shown"):
                    self.bar_up[o] = now + BAR_UP_S
                else:
                    self.bar_up.pop(o, None)
            if before == {o for o, t in self.bar_up.items() if t > now}:
                return True
        elif d.get("cmd") == "nudge":
            if self.nudgew:
                self.nudgew.demo(d.get("phrase") or None)
            return True
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
    def pill_focus(self):
        """Что показывает живая нить: блок, открытый последним из тех, кому есть что показать
        (звонок, музыка, помидор, таймер, запись, котик), — если он сейчас идёт. Иначе — первое
        дело по порядку страниц. Звонок выходит вперёд, только когда начался (refresh → set_info);
        открыли потом другой блок — показывается он (20.10.2026, просьба: «островок звонков не надо
        делать приоритетным»). None — часы."""
        live = [k for k, _d in self.acts if k in PAGES]
        info = self.info.split(":", 1)[0]
        if info in ("cat", "cc") and info in page_ids(self.conf):
            return info
        if info == "timer" and "timer" in page_ids(self.conf):
            # таймер — и без идущих отсчётов: тогда часы, как в покое, а не звонок (20.10.2026,
            # Просьба: «блок с таймером если я от него вышел… показывается островок со звонком»;
            # «раньше вместо слова Таймер показывалось время… это должна была быть фича»)
            return info
        if info in live:
            return info
        return live[0] if live else None

    def pill_acts(self):
        """Дела для живой нити: блок pill_focus — первым."""
        acts = self.ordered(0)
        f = self.pill_focus()
        i = next((n for n, (k, _d) in enumerate(acts) if k == f), None)
        if f == "timer" and i is None:
            return []                           # отсчётов нет — точка и часы
        if i:
            acts.insert(0, acts.pop(i))
        return acts

    def ordered(self, i=0):
        acts = list(self.acts)
        if self.pop_kind in ("music", "nudge") and time.monotonic() < self.pop_until:
            j = next((n for n, (k, _d) in enumerate(acts) if k == self.pop_kind), None)
            if j:
                acts.insert(0, acts.pop(j))
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
        if self.conf["on"] and self.info.split(":", 1)[0] == "cc" and "cc" in page_ids(self.conf) \
                and self.conf["thread_style"] in ("pill", "cat"):
            return True                         # капсула «Центра» видна и без дел (20.10.2026)
        return bool(self.acts) or bool(self.dl) or (self.conf["thread_always"] and bool(self.pages))

    def refresh(self, *_a):
        now = time.monotonic()
        on = self.conf["on"]
        calls = self.calls.calls if self.calls and "call" in page_ids(self.conf) else {}
        nudge = self.nudgew.current() if self.nudgew and "nudge" in page_ids(self.conf) else None
        acts = activities(self.conf, self.music, calls, self.timers, nudge) if on else []
        # запись GIF островок не показывает ни в нити, ни всплытием — ни на паузе, ни при старте
        # (20.10.2026, просьба: «хочу заснять этот островок… это исключение только для записей
        # gif'ок»); страница записи с ▶ остаётся в карточке. Видео — как прежде.
        self.acts = [a for a in acts if not (a[0] == "rec" and a[1]["mode"] == "gif")]
        in_call = any(k == "call" for k, _d in self.acts)
        if in_call and not getattr(self, "in_call", False) and self.info.split(":", 1)[0] != "call":
            self.set_info("call")                 # звонок начался — капсула сразу о нём
        self.in_call = in_call
        self.pages = all_pages(self.conf, acts, self.clip, self.cat.s, self.shelf, self.sys_pages()) if on else []
        TAB_IDS[:] = page_ids(self.conf)
        if self.flash and now >= self.flash["until"]:
            self.flash = None
        # событие: появилось новое главное дело, сменилась фаза помидора, пауза, трек, микрофон
        sig = None
        if self.acts:
            k, d = self.acts[0]
            sig = (k, d["level"] if k == "nudge" else d["phase"] if k == "pomo" else d["paused"] if k == "rec" else
                   d["list"][0]["id"] if k == "timer" else
                   "")      # музыка: пауза/play компакт не раскрывают (20.10.2026, просьба: «каждый раз,
                                 # когда ставлю на паузу, островок сверху меняется — лучше не надо»);
                                 # звонок: и кнопка микрофона тоже («не надо менять островок, когда я
                                 # кликаю вкл/выкл микрофон», 20.10.2026) — видно по самой кнопке
        # новый трек: название в компакте на TRACK_POP_S, музыка — первой (даже за помидором)
        tsig = next(((d.name, d.title) for k, d in self.acts if k == "music" and d.status == "Playing"), None)
        if tsig != self.track_sig:
            if tsig and self.track_sig and tsig[1] != self.track_sig[1] and self.conf["track_pop"]:
                self.pop_until = max(self.pop_until, now + TRACK_POP_S)
                self.pop_kind = "music"
            self.track_sig = tsig
        if sig != self.sig:
            if sig is not None and (self.sig is None or sig[0] != self.sig[0] or sig[1:] != self.sig[1:]):
                if not (sig[0] == "music" and self.sig and self.sig[0] == "music"
                        and sig[1] == self.sig[1] and not self.conf["track_pop"]):
                    self.pop_until = max(self.pop_until, now + self.conf["pop_sec"])
            self.sig = sig
        hidden = self.game or self.overview or not on
        tg = self.targets()
        for out, isl in self.wins.items():
            if hidden or out not in tg or (self.bar_up.get(out, 0) > now and isl.mode != "card"):
                mode = "none"
            elif isl.mode == "card" and self.pages:
                mode = "card"
            elif now < self.pop_until and (self.acts or self.flash) and not (
                    self.flash and self.flash.get("out") and self.flash["out"] != out
                    and out in self.wins and self.flash["out"] in self.wins):
                mode = "compact"                # индикатор яркости — только на своём мониторе
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
        pa = self.pill_acts() if self.conf["thread_style"] == "pill" else []
        ticking = bool(pa) and pa[0][0] in ("call", "rec", "pomo", "timer", "nudge") and self.pill_focus() != "cat" \
            and (pa[0][0] != "timer" or bool(pa[0][1]["list"]))
        if (modes & {"compact", "card"} and self.pages) or ("thread" in modes and ticking):
            waits.append(1.0 - (time.time() % 1.0) + 0.01)
        elif "thread" in modes:
            waits.append(15.0)
        if self.music and any(p.status == "Paused" for p in self.music.players.values()):
            waits.append(5.0)
        up = [t for t in self.bar_up.values() if t > now]
        if up:                                      # сторож бара пропал — островок вернётся сам
            waits.append(min(up) - now + 0.05)
        if "thread" in modes and pa and pa[0][0] == "music" and pa[0][1].status == "Playing" \
                and pa[0][1].length and self.pill_focus() != "cat":
            # время трека в капсуле: перерисовка на смене его секунды (часы с ним не совпадают —
            # раньше секунды «подлагивали»)
            waits.append(1.0 - (pa[0][1].position() % 1.0) + 0.03)
        if waits:
            self.timer = self.GLib.timeout_add(int(min(waits) * 1000), self._tick)

    def nudge_fire(self, kind):
        """Пора напомнить: компакт с фразой — рамка вспыхивает, потом печать по буквам."""
        st = (self.nudgew.streaks.s.get(kind) if self.nudgew else None) or {}
        self.nudge_kind, self.nudge_t0 = kind, time.monotonic()
        n = len(st.get("text") or "")
        self.pop_until = max(self.pop_until, self.nudge_t0 + NUDGE_BLINK_S + n * NUDGE_CHAR_S + NUDGE_HOLD_S)
        self.pop_kind = "nudge"
        log("пора к делу:", kind, mmss(st.get("sec") or 0), st.get("text"))
        self.refresh()
        if not self.nudge_anim_on:
            self.nudge_anim_on = True
            self.GLib.timeout_add(40, self.nudge_anim)

    def nudge_anim(self):
        """Кадры печати и курсора, пока компакт с напоминанием раскрыт."""
        if self.pop_kind != "nudge" or time.monotonic() >= self.pop_until:
            self.nudge_anim_on = False
            return False
        for isl in self.wins.values():
            if isl.mode == "compact":
                isl.win.queue_draw()
        return True

    def _tick(self):
        self.timer = None
        self.refresh()
        return False

    def set_info(self, kind):
        self.info = kind                          # живая нить теперь показывает этот блок
        try:
            with open(LAST_INFO, "w") as f:
                f.write(kind)
        except OSError:
            pass
        for isl in self.wins.values():
            if isl.mode == "thread":
                isl.go("thread")

    # — буфер обмена: снимки —
    def on_page(self, kind, page=None):
        if kind != "power":
            self.sys_ui["power"].pop("ask", None)
        if kind != "wifi":
            self.pw_stop()
        if kind == "clip" and "clip" in page_ids(self.conf):
            self.load_clip()
        if kind in self.sys_ui:
            self.poll_sys(kind)
        if page is not None and kind in INFO_KINDS and kind != self.info.split(":", 1)[0]:
            self.set_info(kind)
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

    # — полка —
    def shelf_set(self, paths):
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        old = {it["path"]: it for it in self.shelf.get("items") or []}
        items = []
        for p in paths[:SHELF_N]:
            if p in old:
                items.append(old[p])
                continue
            it = {"path": p, "name": os.path.basename(p.rstrip("/")) or p, "dir": os.path.isdir(p),
                  "surf": None, "pb": None}
            if p.lower().endswith(IMG_EXT):
                try:
                    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(p, 240, 180, True)
                    it["surf"] = self.Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
                    it["pb"] = GdkPixbuf.Pixbuf.new_from_file_at_scale(p, 96, 96, True)
                except Exception as e:
                    log("shelf thumb", p, e)
            items.append(it)
        self.shelf = {"items": items}

    def shelf_add(self, paths):
        cur = [it["path"] for it in self.shelf["items"]]
        new = [p for p in paths if os.path.exists(p)]
        self.shelf_set(new + [p for p in cur if p not in new])
        shelf_save([it["path"] for it in self.shelf["items"]])
        self.refresh()
        self.redraw()

    def shelf_item(self, i):
        items = self.shelf.get("items") or []
        return items[i] if isinstance(i, int) and 0 <= i < len(items) else None

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
        self.pw_stop()
        for isl in self.wins.values():
            if isl.mode == "card":
                isl.collapse()

    def do(self, act, card_i=0):
        kind, what = act
        if kind in SYS_PAGES:
            self.sys_do(act, 1)
            return
        try:
            if kind == "music" and what == "like":
                self.cat.like_toggle()
            elif kind == "music":
                p = self.music.player() if self.music else None
                if p:
                    self.music.command(p, what)
            elif kind == "pomo":
                subprocess.Popen(["pomo", what], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            elif kind == "rec":
                subprocess.Popen(["bash", REC_SH, what], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 start_new_session=True)
            elif kind == "call" and what == "mute" and self.calls:
                self.calls.toggle_mute()                # кнопка — сразу, pactl — в потоке
            elif kind == "call" and what.startswith("vol:") and self.calls:
                self.calls.set_mic_volume(int(what[4:]))
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
            elif kind == "timer" and what in ("add", "ask"):
                self.collapse_all()
                self.spawn([sys.executable, os.path.abspath(__file__), "timer-ask"])
            elif kind == "prefs":
                # 20.10.2026: раньше в conf ложилась строка («0» — истина для да/нет), а `island.py
                # set` следом слал reload — островок перерисовывался дважды и мигал. Теперь
                # значение разбирается как у `set` и пишется здесь же; зазор niri — в потоке.
                k, v = str(what).split("=", 1)
                dv = DEFAULTS[k]
                self.conf[k] = (v.lower() in ("1", "on", "true", "yes", "да")) if isinstance(dv, bool) else \
                    float(v) if isinstance(dv, float) else v
                c = load_conf()
                c[k] = self.conf[k]
                try:
                    save_conf(c)
                except OSError as e:
                    log("prefs", e)
                if k in ("on", "thread", "thread_style", "overlay", "monitor"):
                    import threading
                    threading.Thread(target=sync_space, args=(dict(c),), daemon=True).start()
                    for isl in self.wins.values():
                        isl.place()
                self.refresh()
                for isl in self.wins.values():
                    if isl.mode in ("thread", "card"):
                        isl.go(isl.mode)
                self.redraw()
            elif kind == "clip" and str(what).isdigit():
                subprocess.Popen(["sh", "-c", "cliphist decode %s | wl-copy" % what],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                self.clip["copied"] = what
                self.redraw()
                self.GLib.timeout_add(1200, lambda: (self.clip.pop("copied", None), self.redraw()) and False)
            elif kind == "dl":                  # панель загрузки — папка, где лежит файл
                path = (self.dl or {}).get("path") or ""
                d = path if os.path.isdir(path) else os.path.dirname(path)
                if not os.path.isdir(d):
                    import island_dl
                    d = island_dl.download_dir()
                self.spawn(["xdg-open", d])
            elif kind == "shelf":
                it = self.shelf_item(what)
                if it:
                    self.spawn(["xdg-open", it["path"]])
            elif kind == "shelf_rm":
                it = self.shelf_item(what)
                if it:
                    self.shelf_set([x["path"] for x in self.shelf["items"] if x is not it])
                    shelf_save([x["path"] for x in self.shelf["items"]])
                    self.refresh()
                    self.redraw()
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
        """Окно звонка: Telegram, Discord или WhatsApp — фокус через niri по app_id."""
        names = [n.lower() for n in (self.calls.calls if self.calls else {})]
        keys = {"telegram": ("telegram", "ayugram", "64gram"), "discord": ("discord", "vesktop", "webcord",
                                                                           "equibop", "legcord"),
                "whatsapp": ("zapzap", "whatsapp", "wasistlos")}
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

    def night(self):
        if not self.conf["night_dim"]:
            return False
        h = time.localtime().tm_hour
        return h >= NIGHT[0] or h < NIGHT[1]

    def lyr_seen(self, out, on):
        """Где строка песни видна сверху — файл LYR_FLAG (по монитору в строке) для xpbar."""
        outs = getattr(self, "lyr_outs", set())
        new = (outs | {out}) if on else (outs - {out})
        if new == outs and hasattr(self, "lyr_outs"):
            return
        self.lyr_outs = new
        try:
            if new:
                with open(LYR_FLAG + ".tmp", "w") as f:
                    f.write("\n".join(sorted(new)) + "\n")
                os.replace(LYR_FLAG + ".tmp", LYR_FLAG)
            elif os.path.exists(LYR_FLAG):
                os.unlink(LYR_FLAG)
        except OSError as e:
            log("lyr flag:", e)

    def osd(self, icon, text, pr, out=None):
        """Индикатор в компакте: значок, подпись, полоса уровня; out — только на этом мониторе."""
        self.flash = {"text": text, "icon": icon, "pr": max(0.0, min(1.0, float(pr))), "out": out,
                      "until": time.monotonic() + 1.4}
        self.pop_kind = None
        if not any(isl.mode == "card" for isl in self.wins.values()):
            self.pop_until = self.flash["until"]
        self.refresh()

    def call_on(self):
        return bool(self.calls and self.calls.calls and "call" in page_ids(self.conf))

    def mic_step(self, step):
        import threading
        threading.Thread(target=self.calls.mic_volume, args=(step,), daemon=True).start()

    def seek(self, sec):
        p = self.music.player() if self.music else None
        if p:
            self.music.seek(p, sec)
            pos = max(0, p.position() + sec)
            self.osd(G_NOTE, "%s  %s" % (mmss(pos), p.title or ""), pos / p.length if p.length else 0)

    def player_volume(self, step):
        """Громкость самого плеера (его потоков PipeWire), не всей системы. Нажатия копятся,
        в поток уходит один разбор за раз; потоки плеера помнятся 5 с."""
        p = self.music.player() if self.music else None
        if not p:
            return
        v = self.vol
        c = v["cache"]
        if not c or c["name"] != p.name or time.monotonic() - c["t"] > 5:
            v["cache"] = {"name": p.name, "t": 0.0, "pid": self.music.pid(p), "sids": None, "pct": None,
                          "words": set((p.identity or p.name.rsplit(".", 1)[-1]).lower().split()), "p": p}
        v["q"] += step
        if v["busy"]:
            return
        v["busy"] = True
        import threading
        threading.Thread(target=self._vol_worker, daemon=True).start()

    def _vol_worker(self):
        v = self.vol
        while True:
            step, v["q"] = v["q"], 0
            if not step:
                v["busy"] = False
                return
            c = v["cache"]
            try:
                res = self._vol_apply(c, step)
            except Exception as e:
                log("player_volume:", e)
                res = None
            if res is not None:
                self.GLib.idle_add(lambda r=res, c=c: self.osd(G_VOL, "%s  %d%%" % (
                    c["p"].identity or "Плеер", r), r / 100) and False)

    def _vol_apply(self, c, step):
        if c["sids"] is None or time.monotonic() - c["t"] > 5:
            import app_volume as AV
            ss = AV.streams()
            kin = AV.family(c["pid"]) if c["pid"] else set()
            sids = [s[0] for s in ss if s[2] and s[2] in kin]
            if not sids:
                sids = [s[0] for s in ss if c["words"] & set(s[3])]
            c["sids"], c["t"], c["pct"] = sids, time.monotonic(), None
        if c["sids"]:
            if c["pct"] is None:
                lv = OsdWatch.level(str(c["sids"][0]))
                c["pct"] = int(round(lv[0] * 100)) if lv else 100
            c["pct"] = max(0, min(100, c["pct"] + step))
            for sid in c["sids"]:
                subprocess.run(["wpctl", "set-volume", str(sid), "%d%%" % c["pct"]], timeout=3)
            c["t"] = time.monotonic()
            return c["pct"]
        # потоков не нашли — громкость MPRIS (у браузера это регулятор на странице)
        p, V = c["p"], self.GLib.Variant
        cur = self.music.call(p.name, Music.PATH, "org.freedesktop.DBus.Properties", "Get",
                              V("(ss)", (Music.IFACE, "Volume")), "(v)")[0]
        new = max(0.0, min(1.0, float(cur) + step / 100))
        self.music.call(p.name, Music.PATH, "org.freedesktop.DBus.Properties", "Set",
                        V("(ssv)", (Music.IFACE, "Volume", V("d", new))), None)
        return int(round(new * 100))

    def push_flash(self, text, icon=""):
        self.flash = {"text": text, "icon": icon, "until": time.monotonic() + self.conf["pop_sec"] + 1}
        self.pop_until = self.flash["until"]
        self.refresh()

    def primary_action(self, kind):
        self.do({"music": ("music", "PlayPause"), "pomo": ("pomo", "toggle"),
                 "rec": ("rec", "pause"), "call": ("call", "mute")}.get(kind, ("", "")))


def timer_ask():
    """«+» на странице таймера: то же окно Timer.exe, что у виджетов (preset_ask.py --ask, как
    desktop_widgets.ask_timer) — 20.10.2026, просьба: «должно было появиться привычное окно
    таймера», а открывался голый rofi. Ввод как там: «work 25m», «limit 5h», «07:30», слова
    в любом порядке; голое число — минуты. Пункт hub с источником island — виджет timer.exe
    на столе появляется сам, как у таймера из Telegram."""
    import datetime
    quick = ["5m", "10m", "15m", "25m", "45m", "1h"]
    try:
        r = subprocess.run(["python3", os.path.join(HERE, "preset_ask.py"), "--ask", "Timer.exe",
                            "название и время: work 25m, limit 5h, 07:30", "Быстро",
                            "Enter — запустить · Esc — отмена", *quick],
                           capture_output=True, text=True, timeout=600)
        out = r.stdout.strip() if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        r, out = None, ""
    if r is None or r.returncode not in (0, 1):  # окна нет (сбой) — прежний rofi
        try:
            out = subprocess.run(["rofi", "-dmenu", "-i", "-p", "Таймер"], input="\n".join(quick),
                                 capture_output=True, text=True, timeout=300).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return 1
    if not out:
        return 0
    sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))
    try:
        import hublib as H
    except ImportError:
        return 1
    secs, name = 0, []
    for w in out.split():
        m = re.fullmatch(r"(\d{1,2}):(\d{2})", w)
        d = H.parse_duration(w)
        if m:                                   # «07:30» — до ближайших таких часов
            now = datetime.datetime.now()
            t = now.replace(hour=int(m[1]) % 24, minute=int(m[2]) % 60, second=0, microsecond=0)
            secs += int(((t if t > now else t + datetime.timedelta(days=1)) - now).total_seconds())
        elif d:
            secs += d
        else:
            name.append(w)
    if not secs:
        subprocess.run(["notify-send", "-a", "Таймер", "Таймер", "Не понял время: " + out])
        return 1
    try:
        H.start_timer(H.connect(), secs, " ".join(name), "island")
    except Exception as e:
        subprocess.run(["notify-send", "-a", "Таймер", "Таймер", "Не поставил: %s" % e])
        return 1
    return 0


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
    for path in (SOCK, OSD_FLAG, LYR_FLAG):
        try:
            os.unlink(path)
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
    if cmd == "nudge":                       # показать «Пора к делу» сейчас (проверка)
        return 0 if send({"cmd": "nudge", "phrase": " ".join(argv[1:])}) else 1
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
