#!/usr/bin/env python3
"""Буфер обмена — окно в стиле XP с вкладками и избранным. SUPER+ALT+V (03.10.2026).

Было: clipboard_menu.py — `cliphist list | rofi` (остался рядом как откат вместе с
clipboard.rasi). Просьба: «то как он сейчас выглядит мне не нравится, слишком
просто» — и прислал образец: окно «Буфер_обмена.txt» с поиском, вкладками и
избранным. Размытие под окном попросил оставить.

Вид — родственник виджетов на обоях (desktop_widgets.py): та же рамка 3 px, та же
полоса заголовка 22 px с градиентом «Пуска», те же кнопки «закрепить» и «закрыть»,
шрифт PxPlus 16 px (чёткий только на сетке 8 px — см. память pixel-font-system),
значки — растровые 9×9 в «пикселях» шрифта (2×2), а не из Nerd Font. Всё окно —
одна область рисования cairo: без дерева GTK-виджетов оно открывается быстрее, а
список сам собой «ленивый» — рисуются только видимые строки.

Стили (03.10.2026): default (XP, как виджеты), skeet и beta — как одноимённые виды
Настроек. `clipboard_win.py style` — напечатать, `style X` — записать в
~/.config/hypr/state/clipboard-style; живой процесс берёт стиль при следующем показе.

Вкладки: Всё · Текст · Картинки · Избранное (со счётчиками). Поиск — просто
печатать: фокус всегда в строке поиска.

Клавиши
    ↑/↓, Ctrl+J/K, Alt+J/K (и русские о/л), Ctrl+N/P — по списку
    PageUp/PageDown, Home/End                      — страница, начало/конец
    Tab / Shift+Tab, Ctrl+L / Ctrl+H (и д/р)       — вкладки: следующая / предыдущая
    полоса прокрутки: тянуть ползунок, щелчок по дорожке — туда; колесо
    Enter, щелчок по строке                        — посмотреть запись целиком (просмотр)
    в просмотре: Enter, «Скопировать»              — положить в буфер и закрыть
                 Esc, Backspace, «Назад»           — назад к списку; ↑↓ PgUp/PgDn — прокрутка
    ПКМ по строке, Ctrl+C                          — положить в буфер сразу, без просмотра
    Ctrl+S, щелчок по звезде                       — в избранное / из избранного
    Delete                                         — удалить запись (в «Избранном» —
                                                     убрать из избранного)
    Shift+Delete, корзина                          — очистить историю (с вопросом;
                                                     избранное остаётся)
    Backspace, Ctrl+Backspace/Ctrl+W, Ctrl+U       — правка строки поиска
    Escape, щелчок мимо окна, повторный SUPER+ALT+V — закрыть (Esc в просмотре — назад)
    в обычном режиме (не в поиске): Space — положить в буфер и закрыть (как Enter в просмотре),
                 Backspace — закрыть окно; в поиске они печатают пробел / стирают символ

Фон окна по умолчанию непрозрачный; `clipboard_win.py glass on|off|get` — стекло
(state/clipboard-glass). Размытие экрана вокруг (слои-ловцы) — всегда.

Избранное — своё хранилище, НЕ cliphist: ~/.local/share/jarvis-clipboard/
    index.json   {"version": 1, "items": [{sha, kind: text|image, mime, size, added,
                  preview, lines, w, h, fmt, file, thumb}, …]} — новое сверху
    items/<sha16>.<ext>   само содержимое (png/jpg/txt…)
    thumbs/<sha16>.png    миниатюра картинки 240×135
Очистка истории его не трогает; вставка идёт прямо из файла. Во «Всё» у записи,
которая уже в избранном, звезда закрашена — сопоставление по sha256 содержимого.

Скорость. Самое дорогое при запуске — не список (`cliphist list` — 10 мс), а
загрузка Python и GTK: 0,2–0,45 с в зависимости от нагрузки. Поэтому:
  • `cliphist list` запускается ДО импорта GTK и читается, когда тот загрузился;
  • при открытии ничего не декодируется: размер и формат картинок cliphist пишет
    в подписи, миниатюры берутся из ~/.cache/cliphist-thumbs (общий кэш со старым
    меню), недостающие делает поток уже после первого кадра;
  • хэши и размеры текста считаются тем же потоком и кладутся в
    ~/.cache/jarvis-clipboard/meta.json — второй раз запись не декодируется;
  • после закрытия процесс остаётся «тёплым» WARM секунд: окно спрятано, повторное
    нажатие — сигнал SIGUSR1 готовому процессу, и окно появляется за один кадр.
    В игре (cs2) тёплым не остаётся — память нужнее.
    `clipboard_win.py --daemon` — запустить спрятанным и держать без срока (если
    поставить в автозапуск, холодных открытий не будет вовсе); `--quit` — снять.
  • нажатие идёт через ~/.config/niri/scripts/clipboard-toggle: готовому процессу
    сигнал шлёт сама оболочка sh (8 мс), Python ради этого не запускается (30 мс);
    холодный запуск там — `python3 -S -m clipboard_win`: модулем, а не файлом,
    потому что файл Python компилирует при каждом запуске заново (40 мс), а модуль
    берёт из __pycache__; `-S` — без site-packages до тех пор, пока не нужен GTK;
  • asyncio, который PyGObject грузит «на всякий случай», при запуске подменяется
    пустышкой (минус треть времени импорта, пояснение — у самого импорта).
Замер каждого открытия пишется в $XDG_RUNTIME_DIR/jarvis-clipboard.log.

Слои. Само окно — слой OVERLAY «jarvis-clipboard» ровно по размеру окна (размытие —
layer-rule niri по этому имени, xray false). Щелчок мимо ловят прозрачные слои
«jarvis-clipboard-catch» во весь экран на каждом мониторе, уровнем ниже (TOP):
один слой во весь экран размыл бы весь экран, а не то, что под окном.
Монитор окну не задаётся — niri сам кладёт слой на активный.

«Закрепить» в заголовке: окно не закрывается после вставки и щелчка мимо,
клавиатура — по требованию (щёлкнул в другое окно — печатаешь там). Держится до
закрытия окна.

Проверка без экрана и без настоящей истории — переменные окружения:
    JARVIS_CLIP_CLIPHIST  подменная команда cliphist
    JARVIS_CLIP_WLCOPY    подменная команда wl-copy
    JARVIS_CLIP_DIR       каталог избранного
    JARVIS_CLIP_THUMBS    каталог миниатюр истории
    JARVIS_CLIP_CACHE     каталог meta.json
    JARVIS_CLIP_RUN       каталог pid-файла и журнала (вместо $XDG_RUNTIME_DIR)
"""
import os
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.environ.get("JARVIS_CLIP_RUN") or os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
PIDFILE = os.path.join(RUN, "jarvis-clipboard.pid")
LOG = os.path.join(RUN, "jarvis-clipboard.log")
CLIPHIST = os.environ.get("JARVIS_CLIP_CLIPHIST") or "cliphist"
WLCOPY = os.environ.get("JARVIS_CLIP_WLCOPY") or "wl-copy"
STORE = os.environ.get("JARVIS_CLIP_DIR") or os.path.expanduser("~/.local/share/jarvis-clipboard")
THUMBS = os.environ.get("JARVIS_CLIP_THUMBS") or os.path.expanduser("~/.cache/cliphist-thumbs")
CACHE = os.environ.get("JARVIS_CLIP_CACHE") or os.path.expanduser("~/.cache/jarvis-clipboard")
MATUGEN = os.path.expanduser("~/.cache/matugen")
WARM = 600                 # сколько секунд спрятанное окно ждёт следующего нажатия; 0 — не ждать
MAIN = __name__ == "__main__"


def since_start():
    """Секунд от запуска процесса (с точностью до тика ядра, 10 мс)."""
    try:
        st = open("/proc/self/stat").read().rsplit(")", 1)[1].split()
        return time.clock_gettime(time.CLOCK_BOOTTIME) - int(st[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError):
        return 0.0


def running_pid():
    """pid уже работающего окна; None — если его нет (pid сверяется с командной
    строкой: номер мог достаться чужому процессу)."""
    try:
        pid = int(open(PIDFILE).read().strip())
        if pid != os.getpid() and b"clipboard_win" in open("/proc/%d/cmdline" % pid, "rb").read():
            return pid
    except (OSError, ValueError):
        pass
    return None


def remove_pidfile():
    try:
        if open(PIDFILE).read().strip() == str(os.getpid()):
            os.remove(PIDFILE)
    except OSError:
        pass


def spawn_list():
    """Запустить `cliphist list`, не дожидаясь: (pid, дескриптор для чтения).
    posix_spawn, а не subprocess — его импорт сам стоит десяток миллисекунд."""
    r, w = os.pipe()
    try:
        pid = os.posix_spawnp(CLIPHIST, [CLIPHIST, "list"], os.environ,
                              file_actions=[(os.POSIX_SPAWN_DUP2, w, 1), (os.POSIX_SPAWN_CLOSE, r)])
    except OSError:
        os.close(r)
        os.close(w)
        return None
    os.close(w)
    return pid, r


def read_list(handle):
    if not handle:
        return ""
    pid, r = handle
    chunks = []
    while True:
        b = os.read(r, 1 << 16)
        if not b:
            break
        chunks.append(b)
    os.close(r)
    try:
        os.waitpid(pid, 0)
    except OSError:
        pass
    return b"".join(chunks).decode("utf-8", "replace")


PRELIST = None
if MAIN:
    # обёртка clipboard-toggle запускает скрипт модулем (`-m`, ради готового .pyc) и для
    # этого кладёт каталог скриптов в PYTHONPATH — дочерним программам он ни к чему
    if os.environ.get("PYTHONPATH") == HERE:
        del os.environ["PYTHONPATH"]
    if len(sys.argv) > 1 and sys.argv[1] == "style":
        # Контракт со строкой в Настройках: `style` — напечатать default|skeet|beta,
        # `style X` — записать. Живое окно берёт стиль при следующем показе.
        _f = os.environ.get("JARVIS_CLIP_STYLE_FILE") or os.path.expanduser(
            "~/.config/hypr/state/clipboard-style")
        if len(sys.argv) == 2:
            try:
                _v = open(_f).read().strip().lower()
            except OSError:
                _v = ""
            print(_v if _v in ("default", "skeet", "beta") else "default")
            sys.exit(0)
        _v = sys.argv[2].strip().lower()
        if _v not in ("default", "skeet", "beta"):
            print("стиль: default | skeet | beta", file=sys.stderr)
            sys.exit(2)
        os.makedirs(os.path.dirname(_f), exist_ok=True)
        with open(_f + ".tmp", "w") as _o:
            _o.write(_v + "\n")
        os.replace(_f + ".tmp", _f)
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "glass":
        # Контракт со строкой в Настройках: `glass [get]` — напечатать on|off,
        # `glass on|off` — записать. off (по умолчанию) — фон окна непрозрачный.
        _f = os.environ.get("JARVIS_CLIP_GLASS_FILE") or os.path.expanduser(
            "~/.config/hypr/state/clipboard-glass")
        _a = sys.argv[2].strip().lower() if len(sys.argv) > 2 else "get"
        if _a == "get":
            try:
                _v = open(_f).read().strip().lower()
            except OSError:
                _v = ""
            print("on" if _v == "on" else "off")
            sys.exit(0)
        if _a not in ("on", "off"):
            print("glass: get | on | off", file=sys.stderr)
            sys.exit(2)
        os.makedirs(os.path.dirname(_f), exist_ok=True)
        with open(_f + ".tmp", "w") as _o:
            _o.write(_a + "\n")
        os.replace(_f + ".tmp", _f)
        sys.exit(0)
    if "--quit" in sys.argv:
        _p = running_pid()
        if _p:
            os.kill(_p, signal.SIGTERM)
        sys.exit(0)
    _p = running_pid()
    if _p:                                     # окно уже есть: показать/спрятать — и всё
        os.kill(_p, signal.SIGUSR1)
        sys.exit(0)
    # Нетерпеливое второе нажатие, пока GTK ещё грузится, — не замечать: прятать
    # пока нечего, а обычная реакция на SIGUSR1 — смерть процесса (окно не появилось бы).
    signal.signal(signal.SIGUSR1, signal.SIG_IGN)
    try:
        with open(PIDFILE, "w") as _f:
            _f.write("%d\n" % os.getpid())
    except OSError:
        pass
    PRELIST = spawn_list()
    if "site" not in sys.modules:              # запуск с `python3 -S`: быстрый путь выше
        import site                            # обошёлся без site-packages, дальше они нужны
        site.main()

import json  # noqa: E402
import re  # noqa: E402
import zlib  # noqa: E402

import cairo  # noqa: E402

# PyGObject при загрузке тянет за собой asyncio — ради `await` у вызовов Gio, которых
# здесь нет. Это треть времени импорта (замер 03.10.2026: gi 150–185 мс с ним, 36–42
# без). На время загрузки ему подставляется пустышка с двумя именами, которые он
# спрашивает; не хватило (другая версия PyGObject) — всё загруженное выбрасывается и
# грузится обычным порядком. После импорта пустышка убирается: кому понадобится
# настоящий asyncio — получит настоящий.
_stub = None
if MAIN and "gi" not in sys.modules and "asyncio" not in sys.modules:
    import types
    _stub = types.ModuleType("asyncio")
    _stub.InvalidStateError = type("InvalidStateError", (Exception,), {})
    _stub._get_running_loop = _stub.get_running_loop = lambda: None
    sys.modules["asyncio"] = _stub


def _load_gi():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: F401


try:
    _load_gi()
except Exception:
    if _stub is None:
        raise
    for _k in [k for k in sys.modules if k == "asyncio" or k == "gi" or k.startswith("gi.")]:
        del sys.modules[_k]
    _stub = None
    _load_gi()
if _stub is not None and sys.modules.get("asyncio") is _stub:
    del sys.modules["asyncio"]

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

FONT = "PxPlus HP 100LX 6x8 Jarvis"
NAMESPACE = "jarvis-clipboard"
TITLE = "Clipboard.exe"          # пользователь, 03.10.2026 (было «Буфер_обмена.txt»)
GAMES = (b"cs2", b"gamescope")

# ── размеры ─────────────────────────────────────────────────────────────────
# 600, а не 560: знак пиксельного шрифта — 12 px, и четыре вкладки со счётчиками
# в 560 не помещаются.
W, H = 600, 640
# Размытие вокруг окна (03.10.2026: «не вижу блюра вокруг окна. Как в
# Super+Space»): размыт весь экран, как под rofi, — это делают слои-ловцы
# «jarvis-clipboard-catch» во весь экран (правило niri blur, xray false), они же
# ловят щелчок мимо. Узкое поле вокруг окна (RING > 0: слой шире окна, поле
# прозрачное, щелчок в нём — «мимо») пробовали первым и заменили; код оставлен.
RING = 0
THUMB_FILE = (240, 135)
FULL_LIMIT = 20000         # сколько знаков текста записи держать для поиска

# Три стиля окна, как у Настроек: default — XP, родственник виджетов на обоях;
# skeet — как Настройки в виде Skeet (меню gamesense: слоистая рамка, полоска трёх
# тонов, мелкий шрифт, группа с подписью в рамке); beta — как Настройки в виде Beta
# (плоско, прямоугольно, сегменты, карточка; Light/Dark — из state/settings-mode).
STYLES = ("default", "skeet", "beta")
STYLE_FILE = os.environ.get("JARVIS_CLIP_STYLE_FILE") or os.path.expanduser(
    "~/.config/hypr/state/clipboard-style")
MODE_FILE = os.environ.get("JARVIS_CLIP_MODE_FILE") or os.path.expanduser(
    "~/.config/hypr/state/settings-mode")


GLASS_FILE = os.environ.get("JARVIS_CLIP_GLASS_FILE") or os.path.expanduser(
    "~/.config/hypr/state/clipboard-glass")
VIEW_LIMIT = 200000        # сколько знаков текста показывать в просмотре


def read_glass():
    """Полупрозрачный фон окна (размытое под ним видно). По умолчанию — нет."""
    try:
        return open(GLASS_FILE).read().strip().lower() == "on"
    except OSError:
        return False


def image_surface(data):
    """Картинка целиком — поверхность cairo (PNG сам cairo, прочее — GdkPixbuf)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            import io
            return cairo.ImageSurface.create_from_png(io.BytesIO(data))
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        loader = GdkPixbuf.PixbufLoader()
        loader.write(data)
        loader.close()
        return Gdk.cairo_surface_create_from_pixbuf(loader.get_pixbuf(), 1, None)
    except Exception:
        return None


def read_style():
    try:
        with open(STYLE_FILE) as f:
            v = f.read().strip().lower()
        return v if v in STYLES else "default"
    except OSError:
        return "default"


def set_geometry(style):
    """Размеры под стиль — модульные имена: окно одно, и весь код читает их отсюда."""
    global BORDER, TOP, TB, CAP, PAD, PX, ADV, LINE, K, STAR, BAR, GAP, DLG_B
    global X0, CW, SEARCH_Y, SEARCH_H, TABS_Y, TAB_H, LIST_Y, LIST_H, LX, LW
    global FOOT_H, FOOT_Y, IMG_ROW, TXT_ROW, TXT_ROW_S, TW, TH
    if style == "skeet":
        # 12 px, как у Skeet в Настройках (там .skeet label { font-size: 12px })
        BORDER, TOP, TB, CAP, PAD, PX, LINE = 6, 8, 20, 14, 10, 12, 15
        SEARCH_H, TAB_H, FOOT_H, GAP, K, BAR, DLG_B = 22, 20, 14, 2, 1, 4, 2
        TW, TH, pad = 112, 63, 7
    elif style == "beta":
        BORDER, TOP, TB, CAP, PAD, PX, LINE = 2, 2, 26, 18, 10, 16, 20
        SEARCH_H, TAB_H, FOOT_H, GAP, K, BAR, DLG_B = 30, 26, 18, 0, 2, 4, 1
        TW, TH, pad = 144, 81, 9
    else:
        BORDER, TOP, TB, CAP, PAD, PX, LINE = 3, 3, 22, 16, 10, 16, 20
        SEARCH_H, TAB_H, FOOT_H, GAP, K, BAR, DLG_B = 32, 26, 18, 4, 2, 6, 3
        TW, TH, pad = 144, 81, 9
    ADV = PX * 3 // 4                  # знак PxPlus — 0,75 кегля
    STAR = 9 * K                       # значки 9×9 «пикселями» шрифта
    X0 = BORDER + PAD
    CW = W - 2 * X0
    SEARCH_Y = TOP + TB + PAD
    TABS_Y = SEARCH_Y + SEARCH_H + 8
    FOOT_Y = H - BORDER - PAD - FOOT_H
    if style == "skeet":               # список — внутри группы с подписью в рамке
        LIST_Y = TABS_Y + TAB_H + 8 + PX // 2 + 8
        LX, LW = X0 + 7, CW - 14
        LIST_H = FOOT_Y - 6 - 8 - LIST_Y
    elif style == "beta":              # список — в карточке с рамкой
        LIST_Y = TABS_Y + TAB_H + 9
        LX, LW = X0 + 1, CW - 2
        LIST_H = FOOT_Y - 8 - LIST_Y
    else:
        LIST_Y = TABS_Y + TAB_H + 8
        LX, LW = X0, CW
        LIST_H = FOOT_Y - 6 - LIST_Y
    IMG_ROW = TH + (13 if style != "skeet" else 10)
    TXT_ROW = 2 * pad + 3 * LINE - (LINE - PX) + 2      # две строки текста и строка сведений
    TXT_ROW_S = 2 * pad + 2 * LINE - (LINE - PX) + 2    # одна строка текста и строка сведений


set_geometry("default")

TABS = ("Всё", "Текст", "Картинки", "Избранное")
ALL, TEXT, IMAGES, FAVS = range(4)
EMPTY = ("Пока пусто", "Текста в истории нет", "Картинок в истории нет",
         "В избранном ничего нет —\nCtrl+S на записи")

BINARY = re.compile(r"^\[\[\s*binary data\s+(\S+)\s+(\S+)\s+(\w+)\s+(\d+)x(\d+)")
UNITS = {"B": 1, "KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "kB": 1000, "MB": 10 ** 6}

PIN_BMP = ("..####..", "..####..", "..####..", ".######.", "...##...", "...##...", "...##...", "........")
X_BMP = ("#.....#", ".#...#.", "..#.#..", "...#...", "..#.#..", ".#...#.", "#.....#")
STAR_ON = ("....#....", "....#....", "...###...", "#########", ".#######.",
           "..#####..", "..#####..", ".###.###.", ".#.....#.")
STAR_OFF = ("....#....", "...#.#...", "...#.#...", "####.####", ".#.....#.",
            "..#...#..", "..#.#.#..", ".#.#.#.#.", ".#.....#.")
LENS_BMP = ("..####...", ".#....#..", "#......#.", "#......#.", "#......#.",
            ".#....#..", "..####...", "......##.", ".......##")
TRASH_BMP = ("...###...", "#########", ".........", ".#######.", ".#.#.#.#.",
             ".#.#.#.#.", ".#.#.#.#.", ".#.#.#.#.", ".#######.")
IMG_BMP = ("#########", "#.......#", "#.##....#", "#.##..#.#", "#....###.",
           "#.#.#####", "#########", ".........", ".........")
CLIP_BMP = ("..###..", "##...##", "#.###.#", "#.....#", "#.###.#", "#.....#",
            "#.##..#", "#.....#", "#######")
TEXT_BMP = ("#######..", "#.....##.", "#.###..#.", "#......#.", "#.####.#.",
            "#......#.", "#.####.#.", "#......#.", "########.")


def draw_bitmap(cr, rows, x, y, k=1):
    """Точки значка прямоугольниками k×k; соседние в строке сливаются в один."""
    for r, row in enumerate(rows):
        c, n = 0, len(row)
        while c < n:
            if row[c] == "#":
                e = c
                while e < n and row[e] == "#":
                    e += 1
                cr.rectangle(x + c * k, y + r * k, (e - c) * k, k)
                c = e
            else:
                c += 1
    cr.fill()


# ── цвета ───────────────────────────────────────────────────────────────────

def hexrgb(h, default=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, IndexError, AttributeError):
        return default


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


T = {}


def load_theme():
    """Те же цвета, что у виджетов на обоях: полоса заголовка — тона «Пуска»
    (xpbar_colors), фон — палитра kitty. Читается при каждом показе окна."""
    def read(name):
        try:
            return open(os.path.join(MATUGEN, name)).read()
        except OSError:
            return ""
    kitty = dict(l.split(None, 1) for l in read("colors-kitty.conf").splitlines()
                 if len(l.split(None, 1)) == 2 and not l.startswith("#"))
    T["bg"] = hexrgb(kitty.get("background", "#10131c"), (0.06, 0.07, 0.11))
    try:
        if HERE not in sys.path:
            sys.path.insert(0, HERE)
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    for k, d in (("st_hi", "#9fb4f5"), ("st_top", "#7f95d8"), ("st_mid", "#5f74b4"),
                 ("st_bot", "#465a94"), ("st_hover", "#8ea4e8"), ("st_dark", "#0a0c12"),
                 ("line2", "#3a4a7a"), ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("error", "#ffb4ab"), ("primary", "#b4c5ff")):
        T[k] = hexrgb(xc.get(k, d), hexrgb(d))
    T["fg"] = T["on_surface"]
    T["dim"] = mix(T["on_surface_variant"], T["bg"], 0.30)
    T["sel"] = T["st_hi"]                              # выбранная строка — светлый акцент
    T["sel_fg"] = T["st_dark"]
    T["sel_dim"] = mix(T["st_dark"], T["st_hi"], 0.36)
    T["vivid"] = hexrgb(read("vivid.txt") or "", T["primary"])
    # палитра обоев целиком (xpbar_colors отдаёт её вместе со своими тонами)
    for k, d in (("surface", "#10131c"), ("surface_container", "#1d1f29"),
                 ("surface_high", "#272a34"), ("secondary", "#c5c2ea"), ("tertiary", "#d2bdf6"),
                 ("on_primary", "#002979"), ("base", "")):
        T["p_" + k] = hexrgb(xc.get(k) or d or xc.get("surface", "#10131c"))


def style_colors(style):
    """Цвета стиля. Общие имена (win_bg, text, dim, accent, sel_*, star_*, scroll…)
    читает общий код; остальные — рамки и кнопки своего стиля."""
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "skeet":
        # формулы — как skeet_colors() в settings_app.py: серые оригинала
        # (#131313, #282828, #3c3c3c…) чуть подкрашены акцентом обоев (vivid)
        acc = T["vivid"]

        def g(level, t=0.05):
            return mix((level / 255,) * 3, acc, t)
        c = dict(acc=acc, acc_l=mix(acc, white, 0.22), acc_d=mix(acc, black, 0.40),
                 bg=g(0x13), field=g(0x1b), field_l=g(0x24),
                 line1=g(0x3c, 0.08), line2=g(0x28, 0.06), line3=g(0x0a, 0.03),
                 gline=g(0x30, 0.08), gdark=g(0x0e, 0.03), icon=g(0x5c, 0.10),
                 icon_on=mix(hexrgb("#e2e2e2"), acc, 0.22),
                 text=mix(hexrgb("#cdcdcd"), T["on_surface"], 0.35), text_dim=g(0x92, 0.10),
                 dot=g(0x18, 0.05), strip=[acc, T["p_tertiary"], T["p_secondary"]], err=T["error"])
        c["line1_on"] = mix(c["line1"], acc, 0.45)
        c.update(win_bg=c["bg"], win_alpha=0.92, dim=c["text_dim"], accent=c["acc_l"],
                 sel_bg=c["field_l"], sel_text=c["acc_l"], sel_dim=c["text_dim"],
                 star_on=acc, sel_star=c["acc_l"], thumb_bg=c["gdark"], thumb_alpha=1.0,
                 scroll=mix(hexrgb("#414141"), acc, 0.06), scroll_on=c["acc_d"])
        return c
    if style == "beta":
        # как beta_colors() в settings_app.py; режим — общий с Настройками
        try:
            mode = open(MODE_FILE).read().strip().lower()
        except OSError:
            mode = "dark"
        if mode == "light":
            base = T["p_base"]
            ink = mix(base, black, 0.15)
            ink2 = mix(T["st_bot"], base, 0.35)
            bg = mix(mix(T["st_hi"], T["on_surface"], 0.85), white, 0.20)
            rail = mix(T["st_hi"], T["on_surface"], 0.62)
            acc = mix(T["st_mid"], T["st_bot"], 0.40)
            c = dict(bg=bg, bar=mix(T["st_hi"], T["on_surface"], 0.45), card=mix(bg, white, 0.45),
                     field=mix(bg, ink2, 0.10), text=ink, dim=mix(ink2, bg, 0.22),
                     acc=acc, on_acc=mix(T["on_surface"], white, 0.6), acc_text=acc,
                     sel=mix(rail, acc, 0.38), sel_text=ink, hover=mix(rail, acc, 0.16),
                     line=mix(bg, ink2, 0.28), line_soft=mix(bg, ink2, 0.14),
                     line_strong=mix(bg, ink2, 0.55), err=mix(T["error"], hexrgb("#7a0000"), 0.55))
        else:
            bg = T["p_surface"]
            cont = T["p_surface_container"]
            c = dict(bg=bg, bar=mix(bg, cont, 0.85), card=cont, field=T["p_surface_high"],
                     text=T["on_surface"], dim=mix(T["on_surface_variant"], bg, 0.30),
                     acc=T["primary"], on_acc=T["p_on_primary"], acc_text=T["primary"],
                     sel=mix(bg, T["primary"], 0.30), sel_text=T["on_surface"],
                     hover=mix(bg, T["primary"], 0.12),
                     line=mix(cont, T["on_surface"], 0.16), line_soft=mix(cont, T["on_surface"], 0.08),
                     line_strong=mix(bg, T["on_surface"], 0.32), err=T["error"])
        c.update(win_bg=c["bg"], win_alpha=0.90, frame=T["primary"], accent=c["acc_text"],
                 sel_bg=c["sel"], sel_dim=mix(c["sel_text"], c["sel"], 0.30),
                 star_on=c["acc_text"], sel_star=c["acc_text"], thumb_bg=c["field"], thumb_alpha=1.0,
                 scroll=c["line_strong"], scroll_on=c["acc"])
        return c
    return dict(win_bg=T["bg"], win_alpha=0.74, text=T["fg"], dim=T["dim"], accent=T["primary"],
                sel_bg=T["sel"], sel_text=T["sel_fg"], sel_dim=T["sel_dim"],
                star_on=T["primary"], sel_star=T["sel_fg"], thumb_bg=T["st_dark"], thumb_alpha=0.55,
                scroll=T["st_mid"], scroll_on=T["st_hi"])


# ── мелочи ──────────────────────────────────────────────────────────────────

def fmt_size(n):
    if n is None:
        return ""
    if n < 1024:
        return "%d Б" % n
    if n < 1 << 20:
        v = n / 1024
        return ("%.1f КБ" % v).replace(".", ",") if v < 10 else "%d КБ" % round(v)
    return ("%.1f МБ" % (n / (1 << 20))).replace(".", ",")


def plural(n, one, few, many):
    n10, n100 = n % 10, n % 100
    if n10 == 1 and n100 != 11:
        return one
    if 2 <= n10 <= 4 and not 12 <= n100 <= 14:
        return few
    return many


def flat(s, limit=200):
    """Текст одной строкой: пробельные подряд — в один пробел, как делает cliphist."""
    return " ".join(s.split())[:limit]


def crc(s):
    return zlib.crc32(s.encode("utf-8", "replace"))


def run(cmd, data=None, timeout=10, capture=True):
    """Запуск команды; вывод или None. subprocess импортируется здесь: до первого
    кадра он не нужен."""
    import subprocess
    try:
        r = subprocess.run(cmd, input=data, timeout=timeout,
                           stdout=subprocess.PIPE if capture else None,
                           stderr=subprocess.DEVNULL if capture else None)
        return r.stdout if capture else b""
    except (OSError, subprocess.SubprocessError):
        return None


def gaming():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


def log(line):
    try:
        if os.path.exists(LOG) and os.path.getsize(LOG) > 32768:
            os.replace(LOG, LOG + ".1")
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%F %T"), line))
    except OSError:
        pass


def fit_surface(src, bw, bh, canvas=False):
    """Вписать картинку в bw×bh (без увеличения). canvas — на прозрачном поле ровно
    bw×bh, по центру; иначе поверхность по размеру самой уменьшенной картинки."""
    w, h = src.get_width(), src.get_height()
    k = min(bw / w, bh / h, 1.0)
    nw, nh = max(1, round(w * k)), max(1, round(h * k))
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, bw if canvas else nw, bh if canvas else nh)
    cr = cairo.Context(out)
    if canvas:
        cr.translate((bw - nw) // 2, (bh - nh) // 2)
    cr.scale(nw / w, nh / h)
    cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_GOOD)
    cr.paint()
    return out


def make_thumb(data, path):
    """Миниатюра 240×135 на прозрачном поле — тот же вид файла, что делал
    clipboard_menu.py через magick, только без запуска программы.

    PNG (а снимки экрана — это он) читает сам cairo. Через GdkPixbuf вышло бы
    втрое медленнее: нынешний GdkPixbuf на каждый файл запускает отдельный
    процесс-загрузчик glycin в песочнице (замер 03.10.2026: 6,7 мс против 2 мс на
    готовую миниатюру). Он остаётся только для остальных форматов (jpeg, bmp…)."""
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n":
            import io
            src = cairo.ImageSurface.create_from_png(io.BytesIO(data))
        else:
            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf
            loader = GdkPixbuf.PixbufLoader()
            loader.write(data)
            loader.close()
            pb = loader.get_pixbuf()
            k = min(THUMB_FILE[0] * 2 / pb.get_width(), THUMB_FILE[1] * 2 / pb.get_height(), 1.0)
            if k < 1:                                # сперва грубо уменьшить: меньше копировать
                pb = pb.scale_simple(max(1, round(pb.get_width() * k)),
                                     max(1, round(pb.get_height() * k)), GdkPixbuf.InterpType.BILINEAR)
            src = Gdk.cairo_surface_create_from_pixbuf(pb, 1, None)
        out = fit_surface(src, THUMB_FILE[0], THUMB_FILE[1], canvas=True)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp.png"
        out.write_to_png(tmp)
        os.replace(tmp, path)
        return True
    except Exception:
        return False


# ── записи ──────────────────────────────────────────────────────────────────

class Entry:
    """Строка списка: запись истории cliphist (src «hist») или избранного («fav»)."""
    __slots__ = ("src", "cid", "preview", "low", "kind", "fmt", "w", "h", "size",
                 "sha", "lines", "full", "rec")

    def __init__(self, src, cid, preview):
        self.src, self.cid, self.preview = src, cid, preview
        self.kind, self.fmt, self.w, self.h = "text", "", 0, 0
        self.size = self.sha = self.lines = self.full = self.rec = None
        self.low = ""

    def mime(self):
        if self.rec:
            return self.rec.get("mime") or "text/plain"
        return "image/" + self.fmt if self.kind == "image" else "text/plain"

    def set_low(self):
        if self.kind == "image":
            self.low = "картинка изображение image %s %dx%d %d×%d %s" % (
                self.fmt, self.w, self.h, self.w, self.h, fmt_size(self.size).lower())
        else:
            self.low = self.preview.lower()

    def matches(self, words):
        for w in words:
            if w not in self.low and not (self.full and w in self.full):
                return False
        return True

    def height(self):
        if self.kind == "image":
            return IMG_ROW
        return TXT_ROW if len(self.preview) > (LW - BAR - 4 - 34 - STAR) // ADV else TXT_ROW_S

    def meta_line(self):
        if self.kind == "image":
            return " · ".join(p for p in ("%d×%d" % (self.w, self.h) if self.w else "",
                                          fmt_size(self.size), self.fmt.upper()) if p)
        parts = ["Текст"]
        if self.size is not None:
            parts.append(fmt_size(self.size))
        if self.lines and self.lines > 1:
            parts.append("%d %s" % (self.lines, plural(self.lines, "строка", "строки", "строк")))
        return " · ".join(parts)


def parse_history(out):
    """Вывод `cliphist list` → записи, новое сверху. Ничего не декодируется:
    у картинок размер, формат и стороны уже есть в подписи."""
    items = []
    for line in out.splitlines():
        cid, tab, preview = line.partition("\t")
        if not cid or not tab:
            continue
        e = Entry("hist", cid, preview)
        m = BINARY.match(preview)
        if m:
            num, unit, fmt, w, h = m.groups()
            e.kind, e.fmt, e.w, e.h = "image", fmt.lower(), int(w), int(h)
            try:
                e.size = int(float(num) * UNITS.get(unit, 1))
            except ValueError:
                e.size = None
        e.set_low()
        items.append(e)
    return items


# ── избранное ───────────────────────────────────────────────────────────────

def fav_load():
    try:
        with open(os.path.join(STORE, "index.json"), encoding="utf-8") as f:
            items = json.load(f).get("items", [])
        return [r for r in items if isinstance(r, dict) and r.get("sha") and r.get("file")]
    except (OSError, ValueError, AttributeError):
        return []


def fav_save(items):
    os.makedirs(STORE, exist_ok=True)
    tmp = os.path.join(STORE, "index.json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "items": items}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, os.path.join(STORE, "index.json"))


def fav_entry(rec):
    e = Entry("fav", rec["sha"], rec.get("preview") or "")
    e.rec, e.sha, e.kind = rec, rec["sha"], rec.get("kind", "text")
    e.fmt, e.w, e.h = rec.get("fmt", ""), int(rec.get("w") or 0), int(rec.get("h") or 0)
    e.size, e.lines = rec.get("size"), rec.get("lines")
    e.set_low()
    return e


def fav_add(items, data, entry, sha):
    """Положить содержимое в избранное: файл, миниатюра, строка в index.json."""
    key = sha[:16]
    if entry.kind == "image":
        ext = {"jpeg": "jpg"}.get(entry.fmt, entry.fmt or "bin")
    else:
        ext = "txt"
    rel = "items/%s.%s" % (key, ext)
    os.makedirs(os.path.join(STORE, "items"), exist_ok=True)
    tmp = os.path.join(STORE, rel + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(STORE, rel))
    rec = {"sha": sha, "kind": entry.kind, "mime": entry.mime(), "size": len(data),
           "added": time.strftime("%Y-%m-%dT%H:%M:%S"), "file": rel}
    if entry.kind == "image":
        rec.update(fmt=entry.fmt, w=entry.w, h=entry.h, preview="", thumb="thumbs/%s.png" % key)
        make_thumb(data, os.path.join(STORE, rec["thumb"]))
    else:
        text = data.decode("utf-8", "replace")
        rec.update(preview=flat(text), lines=text.rstrip("\n").count("\n") + 1)
    items.insert(0, rec)
    fav_save(items)
    return rec


def fav_remove(items, sha):
    for rec in [r for r in items if r.get("sha") == sha]:
        items.remove(rec)
        for rel in (rec.get("file"), rec.get("thumb")):
            if rel:
                try:
                    os.remove(os.path.join(STORE, rel))
                except OSError:
                    pass
    fav_save(items)


# ── окно ────────────────────────────────────────────────────────────────────

class Catcher(Gtk.Window):
    """Прозрачный слой во весь монитор уровнем ниже окна: щелчок мимо — закрыть.
    Его же размывает niri (layer-rule «jarvis-clipboard-catch»: blur, xray false) —
    весь экран вокруг окна не в фокусе, как под rofi. Без затемнения, как у rofi."""

    def __init__(self, app, monitor):
        super().__init__()
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE + "-catch")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.connect("draw", self.on_draw)
        self.connect("button-press-event", lambda *_a: app.close("щелчок мимо") or True)

    @staticmethod
    def on_draw(_w, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        return True


class Win(Gtk.Window):
    def __init__(self, app):
        super().__init__()
        self.set_title(NAMESPACE)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, NAMESPACE)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(W + 2 * RING, H + 2 * RING)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.area.connect("draw", app.on_draw)
        self.area.connect("button-press-event", app.on_press)
        self.area.connect("button-release-event", app.on_release)
        self.connect("map", lambda *_a: app.update_input())
        self.area.connect("motion-notify-event", app.on_motion)
        self.area.connect("scroll-event", app.on_scroll)
        self.connect("key-press-event", app.on_key)
        self.connect("key-release-event", app.on_key_release)
        self.connect("focus-in-event", app.on_focus, True)
        self.connect("focus-out-event", app.on_focus, False)
        self.add(self.area)


class App:
    # Режимы, как в nvim (03.10.2026): обычный — буквы управляют (H/L вкладки,
    # j/k строки, g/G начало/конец, y скопировать, d удалить, / — в поиск), ничего не
    # вводится; поиск — буквы идут в строку, Esc — обратно в обычный. Ctrl+E — сменить режим.
    # l — зайти в запись, h — выйти; вкладки — Shift+H/L или Tab (уточнение пользователя).
    insert = False

    def __init__(self, test=False):
        self.test = test
        self.fd = Pango.FontDescription(FONT)
        self.fd.set_absolute_size(PX * Pango.SCALE)
        self.fo = cairo.FontOptions()
        self.fo.set_antialias(cairo.ANTIALIAS_GRAY)
        self.fo.set_hint_style(cairo.HINT_STYLE_FULL)
        self.fo.set_hint_metrics(cairo.HINT_METRICS_ON)
        self.win = Win(self)
        self.catchers = []
        self.shown = False
        self.gen = 0                    # номер показа: фоновые потоки прежнего показа сами выходят
        self.lock = None
        self.meta = {}
        self.meta_dirty = False
        self.hist, self.favs, self.fav_entries, self.rows, self.tops = [], [], [], [], []
        self.total = 0
        self.tab, self.query, self.sel, self.scroll = ALL, "", 0, 0
        self.confirm = None             # None или «yes»/«no» — какая кнопка вопроса выбрана
        self.pinned = False
        self.status, self.status_id = "", 0
        self.surfs = {}                 # путь миниатюры → (mtime файла, поверхность cairo)
        self.fast_frame = False         # идёт первый кадр: файлы миниатюр не читать
        self.thumbs_late = False
        self.forever = False            # --daemon: не выходить по времени
        self.quitting = False
        self.sounds = []
        self.style = "default"
        self.C = {}
        self.dots = None                # узор фона skeet (cairo-шаблон)
        self.hover = None               # кнопка под мышью: pin / close / trash / bar
        self.drag = None                # тащат ползунок: смещение точки захвата от его верха
        self.t_open = None
        self.t_mode = ""
        self.mouse0 = None
        self.poke_id = 0
        self.warm_id = 0
        self.full_pass = False
        self.view = None                # запись, открытая целиком (просмотр), или None
        self.vdata = None
        self.vscroll = 0
        self.hiding = False             # окно отдаёт клавиатуру перед тем, как спрятаться
        self.hide_id = 0
        self.has_focus = False
        self.last_key_t = 0             # время (ev.time) последнего настоящего события клавиатуры
        self.stale_t = -1
        self.stale_logged = False
        self.open_t = 0.0

    # ── показ и скрытие ────────────────────────────────────────────────────
    def open(self, listing=None, mode="cold", t0=None):
        self.t_open, self.t_mode = (time.monotonic() if t0 is None else t0), mode
        if self.warm_id:
            GLib.source_remove(self.warm_id)
            self.warm_id = 0
        if self.hiding:                               # прятали — передумали
            GLib.source_remove(self.hide_id)
            self.hide_id, self.hiding = 0, False
        self.open_t = time.monotonic()
        # автоповтор GTK, оставшийся от прошлого показа, несёт время прошлой клавиши
        self.stale_t, self.stale_logged = self.last_key_t, False
        self.view = self.vdata = None
        load_theme()
        self.apply_style(read_style())                # стиль читается при каждом показе
        self.gen += 1
        self.meta = self.load_meta()
        self.meta_dirty = False
        self.hist = parse_history(read_list(spawn_list()) if listing is None else listing)
        ids = {e.cid for e in self.hist}
        for k in [k for k in self.meta if k not in ids]:      # записи ушли из истории
            del self.meta[k]
            self.meta_dirty = True
        self.apply_meta()
        self.favs = fav_load()
        self.fav_entries = [fav_entry(r) for r in self.favs]
        self.tab, self.query, self.sel, self.scroll = ALL, "", 0, 0
        self.confirm, self.status, self.mouse0 = None, "", None
        self.hover = self.drag = None
        self.full_pass = False
        self.fast_frame, self.thumbs_late = True, False
        self.refilter()
        self.set_pinned(False, force=True)
        self.insert = False                  # каждый показ — в обычном режиме (как nvim)
        self.shown = True
        self.win.show_all()
        self.win.area.queue_draw()

    def close(self, why=""):
        """Спрятать окно. Процесс остаётся тёплым на WARM секунд (не в игре)."""
        if not self.shown:
            return
        dt = time.monotonic() - self.open_t
        if dt < 1.5:                                 # подозрительно быстро — в журнал, кто закрыл
            log("закрыто через %d мс после показа: %s" % (dt * 1000, why or "?"))
        self.shown = False
        self.gen += 1
        self.view = self.vdata = None
        self.hide_win()
        self.drop_catchers()
        self.save_meta()
        self.hist, self.fav_entries, self.rows = [], [], []
        if len(self.surfs) > 240:                    # миниатюры держим к следующему открытию,
            self.surfs = {}                          # но не копим без конца
        if self.test or self.forever:
            return
        if WARM > 0 and not gaming():
            self.warm_id = GLib.timeout_add_seconds(WARM, self.quit)
        else:
            self.quit()

    def hide_win(self):
        """Спрятать окно, сперва отдав клавиатуру.

        Причина «открывается и сразу закрывается» (03.10.2026). GTK3 повторяет
        зажатую клавишу сам (автоповтор на стороне программы) и останавливает
        повтор, только когда видит её отпускание или уход фокуса (wl_keyboard.leave).
        А gtk_widget_hide() на Wayland уничтожает wl_surface — leave прийти уже не
        к чему. Esc (или Enter) закрывал окно на нажатии, отпускание уходило другой
        программе, и GTK продолжал «нажимать» Esc 25 раз в секунду в спрятанное
        окно. Следующий показ: первый же такой повтор до прихода фокуса — close().
        В журнале это «записей 0» (закрыто между первым кадром и idle).
        Поэтому: клавиатура NONE → niri шлёт leave → GTK гасит повтор → hide()."""
        if self.test or not self.has_focus:
            self.win.hide()
            return
        if self.hiding:
            return
        self.hiding = True
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.NONE)
        w = self.win.get_window()
        if w:
            w.input_shape_combine_region(cairo.Region(), 0, 0)
        self.win.area.queue_draw()                   # кадр — чтобы смена режима дошла до niri
        self.hide_id = GLib.timeout_add(150, self.finish_hide)

    def finish_hide(self):
        if self.hiding:
            if self.hide_id:
                GLib.source_remove(self.hide_id)
            self.hide_id, self.hiding = 0, False
            self.win.hide()
        return False

    def on_focus(self, _w, _ev, on):
        self.has_focus = on
        if not on and self.hiding:
            self.finish_hide()
        return False

    def quit(self, *_a):
        """Завершить процесс: окно убрать сразу, остальное — из idle (см. finish)."""
        self.warm_id = 0
        self.gen += 1
        if not self.quitting:
            self.quitting = True
            if self.shown:
                self.shown = False
                self.win.hide()
                self.drop_catchers()
            GLib.idle_add(self.finish)
        return False

    def finish(self):
        """Выход — os._exit, а не возврат из Gtk.main(). Причина поймана живым запуском
        03.10.2026: после SIGTERM окно осталось на экране, процесс не вышел.
        gtk_main() на выходе делает gdk_flush() → wl_display_roundtrip(). Источник
        событий GDK в начале каждого оборота цикла объявляет себя «читателем» сокета
        Wayland и снимает это в своей проверке. Но когда срабатывает источник с более
        высоким приоритетом (сигнал шёл с PRIORITY_HIGH), GLib проверку источников
        пониже пропускает — «читатель» остаётся висеть, и roundtrip ждёт его вечно.
        Поэтому: сигналы — с обычным приоритетом, выход — из idle (в этом обороте
        проверены все источники) и мимо gdk_flush вовсе."""
        self.save_meta()
        remove_pidfile()
        for t in self.sounds:                        # дать доиграть уже начатому щелчку
            t.join(2.5)
        if self.test:
            Gtk.main_quit()
            return False
        try:
            sys.stdout.flush()
            sys.stderr.flush()
        except OSError:
            pass
        os._exit(0)

    def toggle(self, *_a):
        """SIGUSR1 от второго запуска: показать спрятанное или спрятать показанное."""
        if self.quitting:
            return False
        if self.shown:
            if time.monotonic() - self.open_t < 0.25:   # дребезг/автоповтор бинда
                log("второй сигнал через <250 мс после показа — пропущен")
                return True
            self.close("повторный бинд")
        else:
            self.open(mode="warm")
        return True

    def apply_style(self, style):
        """Размеры, кегль и цвета под стиль (default / skeet / beta)."""
        self.style = style if style in STYLES else "default"
        set_geometry(self.style)
        self.fd.set_absolute_size(PX * Pango.SCALE)
        self.C = style_colors(self.style)
        if not read_glass():                          # по умолчанию фон окна непрозрачный
            self.C["win_alpha"] = 1.0
        self.dots = None
        if self.style == "skeet":                     # точки узора: (0,0) и (2,2) плитки 4×4
            tile = cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4)
            tc = cairo.Context(tile)
            tc.set_source_rgb(*self.C["dot"])
            tc.rectangle(0, 0, 1, 1)
            tc.rectangle(2, 2, 1, 1)
            tc.fill()
            self.dots = cairo.SurfacePattern(tile)
            self.dots.set_extend(cairo.EXTEND_REPEAT)

    def update_input(self):
        """Куда принимаются щелчки: закреплено — только окно (мимо него щелчок уходит
        тому, что под ним); иначе — и поле вокруг (щелчок там закрывает)."""
        win = self.win.get_window()
        if not win:
            return
        if self.pinned:
            reg = cairo.Region(cairo.RectangleInt(RING, RING, W, H))
        else:
            reg = cairo.Region(cairo.RectangleInt(0, 0, W + 2 * RING, H + 2 * RING))
        win.input_shape_combine_region(reg, 0, 0)

    def make_catchers(self):
        if self.test or self.catchers:
            return
        display = Gdk.Display.get_default()
        for i in range(display.get_n_monitors()):
            c = Catcher(self, display.get_monitor(i))
            c.show_all()
            self.catchers.append(c)

    def drop_catchers(self):
        for c in self.catchers:
            c.destroy()
        self.catchers = []

    def set_pinned(self, on, force=False):
        if on == self.pinned and not force:
            return
        self.pinned = on
        GtkLayerShell.set_keyboard_mode(self.win, GtkLayerShell.KeyboardMode.ON_DEMAND if on
                                        else GtkLayerShell.KeyboardMode.EXCLUSIVE)
        if on:
            self.drop_catchers()
        else:
            self.make_catchers()
        self.update_input()
        self.win.area.queue_draw()

    def after_first_frame(self, ms):
        """Всё небыстрое — после первого кадра: миниатюры, звук, фоновые потоки."""
        self.fast_frame = False
        if self.thumbs_late:
            self.win.area.queue_draw()
        if self.t_mode == "cold":
            total = since_start() * 1000
            log("холодный запуск: %d мс от старта процесса до первого кадра (из них до "
                "начала показа %d мс), записей %d" % (total, total - ms, len(self.hist)))
        else:
            log("%s: %d мс от сигнала до первого кадра, записей %d" % (
                "тёплое открытие" if self.t_mode == "warm" else self.t_mode, ms, len(self.hist)))
        if self.test:
            return False
        self.sound("menu")
        self.start_workers()
        return False

    def sound(self, event):
        if self.test:
            return
        import threading

        def play():
            try:
                if HERE not in sys.path:
                    sys.path.insert(0, HERE)
                import ui_sound
                ui_sound.play(event)
            except Exception:
                pass
        t = threading.Thread(target=play, daemon=True)
        t.start()
        self.sounds = [x for x in self.sounds if x.is_alive()] + [t]

    # ── кэш сведений о записях ─────────────────────────────────────────────
    @staticmethod
    def load_meta():
        try:
            with open(os.path.join(CACHE, "meta.json"), encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            return {}

    def apply_meta(self):
        """Что уже считали раньше — сразу в записи. Номер cliphist после очистки
        может достаться другой записи, поэтому сверяется ещё и подпись (crc)."""
        for e in self.hist:
            m = self.meta.get(e.cid)
            if m and m[0] == crc(e.preview):
                e.sha, e.size, e.lines = m[1], m[2], m[3]     # размер — точный, а не «3 KiB»
                e.set_low()

    def save_meta(self):
        if not self.meta_dirty:
            return
        self.meta_dirty = False
        data = dict(self.meta)
        try:
            os.makedirs(CACHE, exist_ok=True)
            tmp = os.path.join(CACHE, "meta.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp, os.path.join(CACHE, "meta.json"))
        except OSError:
            pass

    # ── фоновые потоки ─────────────────────────────────────────────────────
    def start_workers(self, full=False):
        """Досчитать то, чего не было при открытии: хэши и размеры (для звёзд и
        подписей), недостающие миниатюры; с full — ещё и полный текст для поиска."""
        import threading
        if self.lock is None:
            self.lock = threading.Lock()
        gen, jobs = self.gen, iter(list(self.hist))

        def work():
            import hashlib
            while gen == self.gen:
                with self.lock:
                    e = next(jobs, None)
                if e is None:
                    break
                try:
                    if self.fill(e, full, hashlib, gen):
                        self.poke()
                except Exception as err:
                    print("clipboard_win: запись %s: %s" % (e.cid, err), file=sys.stderr)

        def lead():
            n = 1 if gaming() else 3
            pool = [threading.Thread(target=work, daemon=True) for _ in range(n)]
            for t in pool:
                t.start()
            for t in pool:
                t.join()
            if gen == self.gen and not full:
                self.prune_thumbs({e.cid for e in self.hist})
        threading.Thread(target=lead, daemon=True).start()

    def fill(self, e, full, hashlib, gen):
        thumb = os.path.join(THUMBS, e.cid + ".png")
        need_thumb = e.kind == "image" and not os.path.isfile(thumb)
        need_meta = e.sha is None
        need_full = full and e.kind == "text" and e.full is None
        if not (need_thumb or need_meta or need_full):
            return False
        data = run([CLIPHIST, "decode", e.cid])
        if gen != self.gen:                         # окно закрыли или историю очистили
            return False
        if not data:
            e.sha = e.sha or ""                     # не читается — больше не пробовать
            e.full = e.full or ""
            return False
        if need_meta:
            e.sha, e.size = hashlib.sha256(data).hexdigest(), len(data)
            if e.kind == "text":
                e.lines = data.rstrip(b"\n").count(b"\n") + 1
            else:
                e.set_low()
            self.meta[e.cid] = [crc(e.preview), e.sha, e.size, e.lines]
            self.meta_dirty = True
        if e.kind == "text" and e.full is None:
            e.full = data[:FULL_LIMIT * 2].decode("utf-8", "replace")[:FULL_LIMIT].lower()
        if need_thumb:
            make_thumb(data, thumb)
        return True

    def poke(self):
        """Из потока: попросить перерисовать (не чаще раза в 70 мс)."""
        if not self.poke_id:
            self.poke_id = GLib.timeout_add(70, self.on_poke)

    def on_poke(self):
        self.poke_id = 0
        if self.shown:
            if self.query:
                self.refilter(keep=True)
            self.win.area.queue_draw()
        return False

    @staticmethod
    def prune_thumbs(keep):
        """Убрать миниатюры записей, которых в истории уже нет."""
        try:
            for name in os.listdir(THUMBS):
                if name.endswith(".png") and name[:-4] not in keep:
                    os.remove(os.path.join(THUMBS, name))
        except OSError:
            pass

    # ── список ─────────────────────────────────────────────────────────────
    def source(self, tab):
        if tab == FAVS:
            return self.fav_entries
        if tab == TEXT:
            return [e for e in self.hist if e.kind == "text"]
        if tab == IMAGES:
            return [e for e in self.hist if e.kind == "image"]
        return self.hist

    def counts(self):
        n_img = sum(1 for e in self.hist if e.kind == "image")
        return (len(self.hist), len(self.hist) - n_img, n_img, len(self.favs))

    def refilter(self, keep=False):
        cur = self.rows[self.sel] if keep and 0 <= self.sel < len(self.rows) else None
        words = self.query.lower().split()
        src = self.source(self.tab)
        self.rows = [e for e in src if e.matches(words)] if words else list(src)
        self.tops, y = [], 0
        for e in self.rows:
            self.tops.append(y)
            y += e.height() + GAP
        self.total = max(0, y - GAP)
        if cur is not None and cur in self.rows:
            self.sel = self.rows.index(cur)
        elif not keep:
            self.sel, self.scroll = 0, 0
        self.sel = max(0, min(self.sel, len(self.rows) - 1))
        self.reveal()

    def reveal(self):
        """Прокрутить так, чтобы выбранная строка была видна целиком."""
        if self.rows:
            top = self.tops[self.sel]
            bot = top + self.rows[self.sel].height()
            if top < self.scroll:
                self.scroll = top
            elif bot > self.scroll + LIST_H:
                self.scroll = bot - LIST_H
        self.scroll = max(0, min(self.scroll, max(0, self.total - LIST_H)))

    def move(self, d):
        if self.rows:
            self.sel = max(0, min(len(self.rows) - 1, self.sel + d))
            self.reveal()
            self.win.area.queue_draw()

    def page(self, d, half=False):
        """На страницу (half — на полстраницы, Ctrl+D/U как в vim): к первой строке,
        которая целиком за пределами видимого."""
        if not self.rows:
            return
        i = self.sel
        target = self.tops[i] + d * ((LIST_H // 2) if half else (LIST_H - IMG_ROW))
        while 0 <= i + d < len(self.rows) and (self.tops[i] - target) * d < 0:
            i += d
        self.sel = i
        self.reveal()
        self.win.area.queue_draw()

    def set_tab(self, tab):
        self.tab = tab % len(TABS)
        self.refilter()
        self.win.area.queue_draw()

    def set_query(self, q):
        self.query = q
        if q and not self.full_pass and not self.test:
            self.full_pass = True                  # поиск по всему тексту, а не по подписи
            self.start_workers(full=True)
        self.refilter()
        self.win.area.queue_draw()

    def say(self, text):
        self.status = text
        if self.status_id:
            GLib.source_remove(self.status_id)
        self.status_id = GLib.timeout_add(2200, self.unsay)
        self.win.area.queue_draw()

    def unsay(self):
        self.status, self.status_id = "", 0
        if self.shown:
            self.win.area.queue_draw()
        return False

    def current(self):
        return self.rows[self.sel] if 0 <= self.sel < len(self.rows) else None

    # ── действия ───────────────────────────────────────────────────────────
    def content(self, e):
        """Содержимое записи: из файла избранного или из cliphist."""
        if e.src == "fav":
            try:
                with open(os.path.join(STORE, e.rec["file"]), "rb") as f:
                    return f.read()
            except OSError:
                return None
        return run([CLIPHIST, "decode", e.cid]) or None

    def activate(self, e=None):
        """Положить запись в буфер обмена и закрыть окно."""
        e = e or self.current()
        if e is None:
            return
        data = self.content(e)
        if not data:
            self.say("Запись не читается")
            return
        mime = e.mime()
        self.sound("click")
        if self.pinned:
            run([WLCOPY, "--type", mime], data, timeout=5, capture=False)
            self.say("Скопировано")
            GLib.timeout_add(400, self.reload)        # сторож истории допишет запись сам
            return
        self.hide_win()                               # сперва убрать окно — так быстрее на глаз
        while Gtk.events_pending():
            Gtk.main_iteration()
        # вывод не перехватывать: wl-copy уходит в фон и держал бы трубу открытой
        run([WLCOPY, "--type", mime], data, timeout=5, capture=False)
        self.close("вставка")

    def reload(self):
        if self.shown:
            cur_tab, q = self.tab, self.query
            self.hist = parse_history(read_list(spawn_list()))
            self.apply_meta()
            self.tab, self.query = cur_tab, q
            self.refilter(keep=True)
            self.start_workers()
            self.win.area.queue_draw()
        return False

    def toggle_fav(self, e=None):
        e = e or self.current()
        if e is None:
            return
        if e.src == "fav":
            self.unfav(e.sha)
            return
        data = self.content(e)
        if not data:
            self.say("Запись не читается")
            return
        import hashlib
        sha = hashlib.sha256(data).hexdigest()
        e.sha = sha
        if any(r["sha"] == sha for r in self.favs):
            self.unfav(sha)
            return
        try:
            rec = fav_add(self.favs, data, e, sha)
        except OSError as err:
            self.say("Не записалось: %s" % err.strerror)
            return
        self.fav_entries.insert(0, fav_entry(rec))
        self.say("В избранном")
        self.win.area.queue_draw()

    def unfav(self, sha):
        try:
            fav_remove(self.favs, sha)
        except OSError as err:
            self.say("Не записалось: %s" % err.strerror)
            return
        self.fav_entries = [x for x in self.fav_entries if x.sha != sha]
        self.surfs = {k: v for k, v in self.surfs.items() if not k[0].startswith(STORE)}
        self.say("Убрано из избранного")
        if self.tab == FAVS:
            self.refilter(keep=True)
        self.win.area.queue_draw()

    def delete(self):
        e = self.current()
        if e is None:
            return
        if e.src == "fav":
            self.unfav(e.sha)
            return
        run([CLIPHIST, "delete"], (e.cid + "\t" + e.preview + "\n").encode())
        try:
            os.remove(os.path.join(THUMBS, e.cid + ".png"))
        except OSError:
            pass
        self.hist.remove(e)
        self.meta.pop(e.cid, None)
        self.meta_dirty = True
        self.refilter(keep=True)
        self.win.area.queue_draw()

    def wipe(self):
        """Очистить всю историю cliphist. Избранное лежит отдельно и остаётся."""
        run([CLIPHIST, "wipe"])
        self.gen += 1                                # фоновым потокам больше нечего считать
        self.prune_thumbs(set())
        self.hist, self.meta, self.meta_dirty = [], {}, False
        self.surfs = {k: v for k, v in self.surfs.items() if k[0].startswith(STORE)}
        try:
            os.remove(os.path.join(CACHE, "meta.json"))
        except OSError:
            pass
        self.confirm = None
        self.refilter()
        self.say("История очищена")

    def ask_wipe(self):
        if self.hist:
            self.confirm = "no"                      # по умолчанию — «Нет»: историю не вернуть
            self.win.area.queue_draw()
        else:
            self.say("История и так пуста")

    # ── клавиатура ─────────────────────────────────────────────────────────
    def on_key(self, _w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        K = Gdk
        if not self.shown or self.hiding:
            return True
        if ev.time and ev.time == self.stale_t:     # залипший автоповтор GTK (см. hide_win)
            if not self.stale_logged:
                self.stale_logged = True
                log("отброшен залипший автоповтор клавиши %s" % Gdk.keyval_name(k))
            return True
        self.last_key_t = ev.time
        if self.confirm:
            # буквы — по смыслу, а не по месту клавиши: «д»/y — да, «н»/n — нет
            if k in (K.KEY_Escape, K.KEY_n, K.KEY_N, K.KEY_Cyrillic_en, K.KEY_Cyrillic_EN):
                self.confirm = None
            elif k in (K.KEY_y, K.KEY_Y, K.KEY_Cyrillic_de, K.KEY_Cyrillic_DE):
                self.wipe()
            elif k in (K.KEY_Return, K.KEY_KP_Enter):
                if self.confirm == "yes":
                    self.wipe()
                else:
                    self.confirm = None
            elif k in (K.KEY_Left, K.KEY_Right, K.KEY_Tab, K.KEY_ISO_Left_Tab):
                self.confirm = "no" if self.confirm == "yes" else "yes"
            self.win.area.queue_draw()
            return True
        copy_key = ctrl and (code == 54 or k in (K.KEY_c, K.KEY_C, K.KEY_Cyrillic_es, K.KEY_Cyrillic_ES))
        self.shift_now = shift
        if self.view is not None:
            return self.view_key(k, code, ctrl, alt, copy_key)
        if ctrl and (code == 26 or k in (K.KEY_e, K.KEY_E, K.KEY_Cyrillic_u, K.KEY_Cyrillic_U)):
            self.insert = not self.insert                  # 26 — клавиша E
            self.win.area.queue_draw()
            return True
        if self.insert and k == K.KEY_Escape:
            self.insert = False                            # из поиска — в обычный режим
            self.win.area.queue_draw()
            return True
        # jj подряд в режиме поиска — выход в обычный, как у пользователя в nvim. По месту клавиши
        # (keycode 44), так что работает и «оо» в русской раскладке. Первая j уже попала в
        # строку — её убираем.
        if self.insert and not ctrl and not alt and code == 44:
            prev = getattr(self, "j_at", 0)
            if prev and 0 <= ev.time - prev < 400 and self.query:
                self.j_at = 0
                self.set_query(self.query[:-1])
                self.insert = False
                self.win.area.queue_draw()
                return True
            self.j_at = ev.time
        else:
            self.j_at = 0
        if not self.insert and not ctrl and not alt and self.normal_key(k, code, shift):
            return True
        if not self.insert and ctrl and code in (40, 30):  # Ctrl+D / Ctrl+U — полстраницы
            self.page(1 if code == 40 else -1, half=True)
            return True
        if k == K.KEY_Escape:
            self.close("Esc")
        elif k in (K.KEY_Return, K.KEY_KP_Enter) and ctrl:  # Ctrl+Enter — скопировать сразу
            self.activate()
        elif k in (K.KEY_Return, K.KEY_KP_Enter):
            self.open_view()
        elif copy_key:                                     # 54 — клавиша C
            self.activate()
        elif k == K.KEY_Down or ((ctrl or alt) and (code in (44, 57) or k in (
                K.KEY_j, K.KEY_J, K.KEY_Cyrillic_o, K.KEY_Cyrillic_O, K.KEY_n, K.KEY_N))):
            self.move(1)                                   # 44 — клавиша J, 57 — N
        elif k == K.KEY_Up or ((ctrl or alt) and (code in (45, 33) or k in (
                K.KEY_k, K.KEY_K, K.KEY_Cyrillic_el, K.KEY_Cyrillic_EL, K.KEY_p, K.KEY_P))):
            self.move(-1)                                  # 45 — клавиша K, 33 — P
        elif k in (K.KEY_Page_Down, K.KEY_KP_Page_Down):
            self.page(1)
        elif k in (K.KEY_Page_Up, K.KEY_KP_Page_Up):
            self.page(-1)
        elif k == K.KEY_Home:
            self.move(-len(self.rows))
        elif k == K.KEY_End:
            self.move(len(self.rows))
        elif (ctrl or alt) and (code == 43 or k in (K.KEY_h, K.KEY_H, K.KEY_Cyrillic_er,
                                                    K.KEY_Cyrillic_ER)):
            self.set_tab(self.tab - 1)                     # 43 — клавиша H
        elif (ctrl or alt) and (code == 46 or k in (K.KEY_l, K.KEY_L, K.KEY_Cyrillic_de,
                                                    K.KEY_Cyrillic_DE)):
            self.set_tab(self.tab + 1)                     # 46 — клавиша L
        elif k == K.KEY_ISO_Left_Tab or (k == K.KEY_Tab and shift):
            self.set_tab(self.tab - 1)
        elif k == K.KEY_Tab:
            self.set_tab(self.tab + 1)
        elif k in (K.KEY_Delete, K.KEY_KP_Delete):
            if shift:
                self.ask_wipe()
            else:
                self.delete()
        elif ctrl and (code == 39 or k in (K.KEY_s, K.KEY_S, K.KEY_Cyrillic_yeru, K.KEY_Cyrillic_YERU)):
            self.toggle_fav()                              # 39 — клавиша S
        elif k == K.KEY_BackSpace:
            if ctrl:
                self.set_query(self.query.rstrip().rpartition(" ")[0])
            else:
                self.set_query(self.query[:-1])
        elif ctrl and (code == 25 or k in (K.KEY_w, K.KEY_W)):
            self.set_query(self.query.rstrip().rpartition(" ")[0])
        elif ctrl and (code == 30 or k in (K.KEY_u, K.KEY_U)):
            self.set_query("")
        elif not ctrl and not alt:
            u = Gdk.keyval_to_unicode(k)
            ch = chr(u) if u else ""
            if ch and ch.isprintable() and len(self.query) < 200:
                self.set_query(self.query + ch)
            else:
                return False
        else:
            return False
        return True

    def normal_key(self, k, code, shift):
        """Обычный режим: клавиши по месту (keycode), раскладка не важна. True — съедено."""
        K = Gdk
        if code == 61 or k == K.KEY_slash:                 # 61 — клавиша «/» (в русской — «.»)
            self.insert = True
        elif code == 44:                                   # j
            self.move(1)
        elif code == 45:                                   # k
            self.move(-1)
        elif code == 43 and shift:                         # H — вкладка влево
            self.set_tab(self.tab - 1)
        elif code == 46 and shift:                         # L — вкладка вправо
            self.set_tab(self.tab + 1)
        elif code == 46:                                   # l — зайти в запись (h — выйти)
            self.open_view()
        elif code == 43:                                   # h в списке — ничего
            pass
        elif code == 42:                                   # g / G
            self.move(len(self.rows) if shift else -len(self.rows))
        elif code in (29, 54):                             # y (yank) или c — скопировать
            self.activate()
        elif code == 40:                                   # d — удалить
            self.delete()
        elif code == 41:                                   # f — в избранное / из избранного
            self.toggle_fav()
        elif code == 24:                                   # q — закрыть окно, как в vim
            self.close("q")
            return True
        elif code == 57 and shift:                         # N — как Ctrl+K
            self.move(-1)
        elif code == 57:                                   # n — следующая
            self.move(1)
        elif k == K.KEY_space:                             # Space — скопировать (04.10.2026)
            self.activate()
        elif k == K.KEY_BackSpace:                         # Backspace — выйти (04.10.2026)
            self.close("Backspace")
            return True
        elif (u := Gdk.keyval_to_unicode(k)) and chr(u).isprintable():
            return True                                    # прочие буквы в обычном режиме молчат
        else:
            return False
        self.win.area.queue_draw()
        return True

    def on_key_release(self, _w, ev):
        if self.shown and not self.hiding and ev.time != self.stale_t:
            self.last_key_t = ev.time
        return False

    def view_key(self, k, code, ctrl, alt, copy_key):
        """Клавиши в просмотре записи."""
        K = Gdk
        _x, _y, h, _t, s = self.sc()
        plain = not ctrl and not alt
        if ctrl and code in (40, 30):                      # Ctrl+D / Ctrl+U — полэкрана
            self.set_sc(s + (h // 2 if code == 40 else -(h // 2)))
            self.win.area.queue_draw()
            return True
        if k in (K.KEY_Escape, K.KEY_BackSpace) or (plain and code == 43):   # h — назад
            self.back()
        elif k in (K.KEY_Return, K.KEY_KP_Enter) or copy_key or (plain and code in (29, 54)) \
                or (plain and k == K.KEY_space):           # y, c, Space
            self.activate(self.view)
        elif plain and code == 41:                         # f — в избранное
            self.toggle_fav(self.view)
        elif plain and code == 44:                         # j — вниз
            self.set_sc(s + LINE)
        elif plain and code == 45:                         # k — вверх
            self.set_sc(s - LINE)
        elif plain and code == 42:                         # g / G — начало / конец
            self.set_sc(1 << 30 if self.shift_now else 0)
        elif ctrl and (code == 39 or k in (K.KEY_s, K.KEY_S, K.KEY_Cyrillic_yeru, K.KEY_Cyrillic_YERU)):
            self.toggle_fav(self.view)
        elif k == K.KEY_Down or ((ctrl or alt) and (code in (44, 57) or k in (K.KEY_j, K.KEY_J))):
            self.set_sc(s + LINE)
        elif k == K.KEY_Up or ((ctrl or alt) and (code in (45, 33) or k in (K.KEY_k, K.KEY_K))):
            self.set_sc(s - LINE)
        elif k in (K.KEY_Page_Down, K.KEY_KP_Page_Down, K.KEY_space):
            self.set_sc(s + h - LINE)
        elif k in (K.KEY_Page_Up, K.KEY_KP_Page_Up):
            self.set_sc(s - h + LINE)
        elif k == K.KEY_Home:
            self.set_sc(0)
        elif k == K.KEY_End:
            self.set_sc(1 << 30)
        self.win.area.queue_draw()
        return True

    # ── просмотр записи целиком ────────────────────────────────────────────
    def view_btns(self):
        """Кнопки просмотра: («Назад», «Скопировать») — в строке поиска."""
        pad = 8 if self.style == "skeet" else 12
        bw, cw = 7 * ADV + 2 * pad, 11 * ADV + 2 * pad
        return (X0, SEARCH_Y, bw, SEARCH_H), (X0 + CW - cw, SEARCH_Y, cw, SEARCH_H)

    def view_box(self):
        top = TABS_Y + (PX // 2 + 2 if self.style == "skeet" else 0)
        return X0, top, CW, FOOT_Y - 6 - top

    def open_view(self, e=None):
        e = e or self.current()
        if e is None:
            return
        data = self.content(e)
        if not data:
            self.say("Запись не читается")
            return
        self.sound("click")
        self.view, self.vscroll, self.drag, self.hover = e, 0, None, None
        bx, by, bw, bh = self.view_box()
        pad = 8 if self.style == "skeet" else 10
        v = {"kind": e.kind, "x": bx + pad, "y": by + pad, "h": bh - 2 * pad,
             "bar_x": bx + bw - 4 - BAR, "total": bh - 2 * pad}
        if e.kind == "image":
            v["w"] = bw - 2 * pad
            src = image_surface(data)
            if src is None:
                v["err"] = "Картинка не читается"
            else:
                w, h = src.get_width(), src.get_height()
                k = min(v["w"] / w, v["h"] / h)
                # мелкую — увеличить целым числом раз (пиксели чёткие), крупную — вписать
                k, filt = (float(min(4, int(k))), cairo.FILTER_NEAREST) if k >= 1 else (k, cairo.FILTER_GOOD)
                nw, nh = max(1, round(w * k)), max(1, round(h * k))
                out = cairo.ImageSurface(cairo.FORMAT_ARGB32, nw, nh)
                c = cairo.Context(out)
                c.scale(nw / w, nh / h)
                c.set_source_surface(src, 0, 0)
                c.get_source().set_filter(filt)
                c.paint()
                v["surf"] = out
                v["cap"] = "Картинка · %d×%d · %s · %s" % (w, h, fmt_size(len(data)), (e.fmt or "").upper())
        else:
            v["w"] = bw - 2 * pad - BAR - 6
            text = data.decode("utf-8", "replace")
            n_lines = text.rstrip("\n").count("\n") + 1
            cut = len(text) > VIEW_LIMIT
            text = text[:VIEW_LIMIT].replace("\r\n", "\n").replace("\t", "    ")
            if cut:
                text += "\n\n… показаны первые %d знаков" % VIEW_LIMIT
            v["empty"] = not text.strip()
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1)
            cr = cairo.Context(surf)
            cr.set_font_options(self.fo)
            lay = PangoCairo.create_layout(cr)
            lay.set_font_description(self.fd)
            lay.set_width(int(v["w"]) * Pango.SCALE)
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lay.set_spacing((LINE - PX) * Pango.SCALE)
            lay.set_text(text if not v["empty"] else "(пусто)", -1)
            lines, it = [], lay.get_iter()
            while True:                                # строки и их место — один раз, рисуются видимые
                _ink, lg = it.get_line_extents()
                lines.append((lg.y // Pango.SCALE, (lg.y + lg.height) // Pango.SCALE,
                              it.get_baseline() // Pango.SCALE, it.get_line_readonly()))
                if not it.next_line():
                    break
            v.update(lay=lay, lines=lines, total=lay.get_pixel_size()[1] + 4)
            v["cap"] = "Текст · %s · %d %s" % (fmt_size(len(data)), n_lines,
                                               plural(n_lines, "строка", "строки", "строк"))
        self.vdata = v
        self.win.area.queue_draw()

    def back(self):
        self.view = self.vdata = None
        self.drag = self.hover = None
        self.reveal()
        self.win.area.queue_draw()

    def sc(self):
        """Что прокручивается: (x полосы, y, высота, всего, сдвиг) — список или просмотр."""
        if self.view is not None and self.vdata:
            v = self.vdata
            return v["bar_x"], v["y"], v["h"], v["total"], self.vscroll
        return LX + LW - BAR, LIST_Y, LIST_H, self.total, self.scroll

    def set_sc(self, s):
        _x, _y, h, total, _s = self.sc()
        s = max(0, min(int(s), max(0, total - h)))
        if self.view is not None:
            self.vscroll = s
        else:
            self.scroll = s

    # ── мышь ───────────────────────────────────────────────────────────────
    @staticmethod
    def inside(zone, x, y):
        return zone[0] <= x < zone[0] + zone[2] and zone[1] <= y < zone[1] + zone[3]

    def zone_close(self):
        return (W - BORDER - 3 - CAP, TOP + (TB - CAP) // 2, CAP, CAP)

    def zone_pin(self):
        x, y, w, h = self.zone_close()
        return (x - 3 - CAP, y, w, h)

    def zone_trash(self):
        return (X0 + CW - SEARCH_H, SEARCH_Y, SEARCH_H, SEARCH_H)

    def zone_confirm(self):
        """Плашка вопроса и две её кнопки: (плашка, «Да», «Нет»)."""
        bh_btn, bw_btn = (20, 72) if self.style == "skeet" else (28, 96)
        dtb = TB if self.style != "skeet" else PX + 10
        bw = 420 if self.style != "skeet" else 330
        bh = 2 * DLG_B + dtb + 14 + 2 * LINE + 14 + bh_btn + 12
        bx, by = (W - bw) // 2, LIST_Y + (LIST_H - bh) // 2 - 20
        yes = (bx + bw // 2 - 8 - bw_btn, by + bh - DLG_B - 12 - bh_btn, bw_btn, bh_btn)
        no = (bx + bw // 2 + 8, yes[1], bw_btn, bh_btn)
        return (bx, by, bw, bh), yes, no

    def tab_zones(self):
        """[(x, y, w, h, подпись, счётчик)] — вкладки по ширине подписи."""
        cnt = self.counts()
        pad = 8 if self.style != "skeet" else 7

        def build(with_counts):
            zones, x = [], X0
            for i, name in enumerate(TABS):
                num = str(cnt[i]) if cnt[i] and (with_counts or i == self.tab) else ""
                w = 2 * pad + len(name) * ADV + ((len(num) + 1) * ADV if num else 0)
                if i == FAVS:
                    w += STAR + 6
                zones.append((x, TABS_Y, w, TAB_H, name, num))
                x += w + (6 if self.style != "skeet" else 4)
            return zones, x
        zones, right = build(True)
        if right > X0 + CW:                         # не помещаются — счётчик только у открытой
            zones, right = build(False)
        return zones

    def list_w(self):
        return LW - (BAR + 4 if self.total > LIST_H else 0)

    def star_zone(self, i):
        """Звезда строки i в координатах окна (с запасом вокруг — легче попасть)."""
        y = LIST_Y + self.tops[i] - self.scroll
        h = self.rows[i].height()
        return (LX + self.list_w() - 12 - STAR - 8, y + (h - STAR) // 2 - 8, STAR + 16, STAR + 16)

    def row_at(self, x, y):
        if not (LX <= x < LX + self.list_w() and LIST_Y <= y < LIST_Y + LIST_H):
            return None
        yy = y - LIST_Y + self.scroll
        for i, top in enumerate(self.tops):
            if top <= yy < top + self.rows[i].height():
                return i
            if top > yy:
                break
        return None

    def thumb_geom(self):
        """Ползунок полосы прокрутки: (x, y, высота) или None — прокручивать нечего."""
        x, y0, h, total, s = self.sc()
        if total <= h:
            return None
        kh = max(24, int(h * h / total))
        return x, y0 + int((h - kh) * s / max(1, total - h)), kh

    def zone_bar(self):
        """Полоса прокрутки с запасом влево — тонкую полоску легче поймать мышью."""
        x, y0, h, _t, _s = self.sc()
        return (x - 6, y0, BAR + 6, h)

    def drag_to(self, y):
        """Ползунок тащат: верх ползунка — в y минус точка, за которую взяли."""
        g = self.thumb_geom()
        if not g:
            return
        _x, y0, h, total, _s = self.sc()
        top = y - self.drag - y0
        self.set_sc(round(top * (total - h) / max(1, h - g[2])))
        self.win.area.queue_draw()

    def on_press(self, _w, ev):
        if ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        x, y = ev.x - RING, ev.y - RING
        if not (0 <= x < W and 0 <= y < H):             # размытое поле вокруг окна — «мимо»
            if not self.pinned:
                self.close("щелчок мимо")
            return True
        if ev.button == 3 and not self.confirm:         # ПКМ — скопировать сразу
            if self.view is not None:
                self.activate(self.view)
            else:
                i = self.row_at(x, y)
                if i is not None:
                    self.sel = i
                    self.activate(self.rows[i])
            return True
        if ev.button != 1:
            return True
        if self.confirm:
            _box, yes, no = self.zone_confirm()
            if self.inside(yes, x, y):
                self.sound("click")
                self.wipe()
            elif self.inside(no, x, y):
                self.confirm = None
            self.win.area.queue_draw()
            return True
        if self.inside(self.zone_close(), x, y):
            self.close("крестик")
        elif self.view is not None:
            back, copy = self.view_btns()
            if self.inside(back, x, y):
                self.back()
            elif self.inside(copy, x, y):
                self.activate(self.view)
            elif self.thumb_geom() and self.inside(self.zone_bar(), x, y):
                _bx, ky, kh = self.thumb_geom()
                self.drag = y - ky if ky <= y < ky + kh else kh // 2
                self.drag_to(y)
        elif self.inside(self.zone_pin(), x, y):
            self.sound("click")
            self.set_pinned(not self.pinned)
            self.say("Закреплено — окно не закроется после вставки" if self.pinned
                     else "Откреплено — после вставки окно закроется")
        elif self.inside(self.zone_trash(), x, y):
            self.ask_wipe()
        elif TABS_Y <= y < TABS_Y + TAB_H:
            for i, z in enumerate(self.tab_zones()):
                if self.inside(z[:4], x, y):
                    self.sound("click")
                    self.set_tab(i)
                    break
        elif self.thumb_geom() and self.inside(self.zone_bar(), x, y):
            _bx, ky, kh = self.thumb_geom()
            if ky <= y < ky + kh:
                self.drag = y - ky                    # взяли ползунок
            else:
                self.drag = kh // 2                   # щелчок по дорожке — ползунок сюда
                self.drag_to(y)
        else:
            i = self.row_at(x, y)
            if i is not None:
                self.sel = i
                if self.inside(self.star_zone(i), x, y):
                    self.toggle_fav(self.rows[i])
                else:
                    self.open_view(self.rows[i])          # ЛКМ — посмотреть целиком
        return True

    def on_release(self, _w, ev):
        if ev.button == 1 and self.drag is not None:
            self.drag = None
            self.win.area.queue_draw()
        return True

    def on_motion(self, _w, ev):
        x, y = ev.x - RING, ev.y - RING
        if self.drag is not None:
            self.drag_to(y)
            return True
        hover = None
        if not self.confirm:
            zones = [("pin", self.zone_pin()), ("close", self.zone_close())]
            if self.view is not None:
                zones += list(zip(("back", "copy"), self.view_btns()))
            else:
                zones.append(("trash", self.zone_trash()))
            for name, zone in zones:
                if self.inside(zone, x, y):
                    hover = name
            if hover is None and self.thumb_geom() and self.inside(self.zone_bar(), x, y):
                hover = "bar"
        if hover != self.hover:
            self.hover = hover
            self.win.area.queue_draw()
        # Строка под мышью выбирается, только когда мышь действительно сдвинули:
        # иначе окно, открывшееся под неподвижным указателем, сразу прыгало бы с
        # первой записи на ту, что под ним.
        if self.mouse0 is None:
            self.mouse0 = (x, y)
            return True
        if self.mouse0 != "moved":
            if abs(x - self.mouse0[0]) + abs(y - self.mouse0[1]) < 6:
                return True
            self.mouse0 = "moved"
        if self.confirm or self.view is not None:
            return True
        i = self.row_at(x, y)
        if i is not None and i != self.sel:
            self.sel = i
            self.win.area.queue_draw()
        return True

    def on_scroll(self, _w, ev):
        if self.confirm:
            return True
        if ev.direction == Gdk.ScrollDirection.SMOOTH:
            _ok, _dx, dy = ev.get_scroll_deltas()
            d = dy * 60
        else:
            d = {Gdk.ScrollDirection.UP: -60, Gdk.ScrollDirection.DOWN: 60}.get(ev.direction, 0)
        self.set_sc(self.sc()[4] + d)
        self.win.area.queue_draw()
        return True

    # ── рисование: общее ───────────────────────────────────────────────────
    def layout(self, cr, text, width=None, lines=1):
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(self.fd)
        lay.set_text(text, -1)
        if width:
            lay.set_width(int(width) * Pango.SCALE)
            lay.set_ellipsize(Pango.EllipsizeMode.END)
            if lines > 1:
                lay.set_wrap(Pango.WrapMode.WORD_CHAR)
                lay.set_height(-lines)
                lay.set_spacing((LINE - PX) * Pango.SCALE)
        return lay

    def text(self, cr, s, x, y, color, width=None, lines=1, alpha=1.0, align=None, bold=False):
        lay = self.layout(cr, s, width, lines)
        if align:
            lay.set_alignment(align)
        cr.set_source_rgba(color[0], color[1], color[2], alpha)
        cr.move_to(int(x), int(y))
        PangoCairo.show_layout(cr, lay)
        if bold:            # «жирно» пиксельного шрифта — второй удар на пиксель правее, как в Beta Настроек
            cr.move_to(int(x) + 1, int(y))
            PangoCairo.show_layout(cr, lay)
        return lay.get_pixel_size()

    def thumb(self, e):
        """Поверхность миниатюры; None — файла ещё нет (рисуется значок);
        False — файл есть, но в этом кадре не читается."""
        path = (os.path.join(STORE, e.rec.get("thumb") or "") if e.src == "fav"
                else os.path.join(THUMBS, e.cid + ".png"))
        try:
            stamp = os.stat(path).st_mtime_ns
        except OSError:
            return None
        key = (path, TW)
        hit = self.surfs.get(key)
        if hit and hit[0] == stamp:                   # файл тот же, что читали
            return hit[1]
        if self.fast_frame:
            # Первый кадр файлов не читает (PNG — по 3–4 мс на строку): окно
            # появляется сразу, миниатюры — следующим кадром. При тёплом открытии
            # они уже в памяти, и этого шага нет.
            self.thumbs_late = True
            return False
        try:
            s = fit_surface(cairo.ImageSurface.create_from_png(path), TW, TH)
        except (cairo.Error, OSError, MemoryError):
            s = None
        self.surfs[key] = (stamp, s)
        return s

    def on_draw(self, _a, cr):
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)               # поле вокруг окна — прозрачное: его размывает niri
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        cr.set_font_options(self.fo)
        cr.translate(RING, RING)
        try:
            self.render(cr)
        except Exception as err:                       # окно без кадра хуже окна с огрехом
            print("clipboard_win: кадр: %s" % err, file=sys.stderr)
        if self.t_open is not None:
            ms, self.t_open = (time.monotonic() - self.t_open) * 1000, None
            GLib.idle_add(self.after_first_frame, ms)
        return True

    def render(self, cr):
        C = self.C
        cr.save()
        cr.rectangle(0, 0, W, H)
        cr.clip()
        cr.set_source_rgba(*C["win_bg"], C["win_alpha"])
        cr.paint()
        if self.style == "skeet" and self.dots is not None:   # точечный узор фона skeet
            cr.set_source(self.dots)
            cr.paint_with_alpha(C["win_alpha"])
        cr.restore()
        getattr(self, "frame_" + self.style)(cr)
        if self.view is not None and self.vdata:
            self.draw_view(cr)
        else:
            self.draw_search(cr)
            self.draw_tabs(cr)
            self.draw_list_box(cr)
            cr.save()
            cr.rectangle(LX, LIST_Y, LW, LIST_H)
            cr.clip()
            self.draw_list(cr)
            cr.restore()
        self.draw_footer(cr)
        if self.confirm:
            self.draw_confirm(cr)

    def rect_line(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()

    def rect_fill(self, cr, x, y, w, h, color, alpha=1.0):
        cr.set_source_rgba(*color, alpha)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def band(self, cr, i, w, color):
        """Кольцо рамки толщиной w на отступе i от края окна."""
        cr.set_source_rgb(*color)
        cr.rectangle(i, i, W - 2 * i, H - 2 * i)
        cr.rectangle(i + w, i + w, W - 2 * (i + w), H - 2 * (i + w))
        cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        cr.fill()
        cr.set_fill_rule(cairo.FILL_RULE_WINDING)

    def button(self, cr, zone, on=False, kind="", label=None, bmp=None, hover=False):
        """Кнопка в стиле окна: заголовка (pin/close), корзина, «Да»/«Нет»."""
        x, y, w, h = zone
        C, st = self.C, self.style
        if st == "skeet":
            if on:
                self.rect_fill(cr, x, y, w, h, C["field"])
            else:
                g = cairo.LinearGradient(0, y, 0, y + h)
                g.add_color_stop_rgb(0, *C["field_l"])
                g.add_color_stop_rgb(1, *C["field"])
                cr.set_source(g)
                cr.rectangle(x, y, w, h)
                cr.fill()
            self.rect_line(cr, x, y, w, h, C["line3"])
            self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["acc_d"] if on else C["gline"])
            ink = C["acc_l"] if (on or hover) else C["text_dim"]
            if kind == "close" and hover:
                ink = C["err"]
        elif st == "beta":
            self.rect_fill(cr, x, y, w, h, C["sel"] if on else (C["hover"] if hover else C["field"]))
            self.rect_line(cr, x, y, w, h, C["acc"] if on else C["line_strong"])
            if on and kind == "dlg":
                self.rect_fill(cr, x, y, w, h, C["acc"])
            ink = C["on_acc"] if (on and kind == "dlg") else C["text"]
            if kind == "close" and hover:
                self.rect_fill(cr, x, y, w, h, C["err"])
                ink = C["bg"]
        else:
            g = cairo.LinearGradient(0, y, 0, y + h)
            if kind == "close":
                er = T["error"]
                top = tuple(0.5 * er[i] + 0.5 * T["st_hover"][i] for i in range(3))
                bot = tuple(0.55 * er[i] * 0.6 + 0.45 * T["st_bot"][i] for i in range(3))
                if hover:
                    top = mix(top, (1, 1, 1), 0.18)
            elif kind == "dlg":
                top = T["st_top"] if on else mix(T["bg"], T["st_mid"], 0.30)
                bot = T["st_bot"] if on else mix(T["bg"], T["st_mid"], 0.18)
                if hover:
                    top = mix(top, (1, 1, 1), 0.15)
            elif on:                                   # вдавлена: темнее, чем полоса
                top, bot = mix(T["st_bot"], T["st_dark"], 0.55), T["st_bot"]
            else:
                top, bot = (mix(T["st_hover"], (1, 1, 1), 0.15) if hover else T["st_hover"]), T["st_bot"]
            g.add_color_stop_rgb(0, *top)
            g.add_color_stop_rgb(1, *bot)
            cr.set_source(g)
            cr.rectangle(x, y, w, h)
            cr.fill()
            if kind == "dlg":
                self.rect_line(cr, x, y, w, h, T["st_hi"] if on else T["line2"])
                ink = T["on_surface"] if on else T["on_surface_variant"]
            elif on:
                self.rect_line(cr, x, y, w, h, T["st_dark"])
                cr.set_source_rgba(*T["primary"], 0.9)    # подсветка вдавленной кнопки
                cr.rectangle(x + 1, y + 1, w - 2, 1)
                cr.rectangle(x + 1, y + 1, 1, h - 2)
                cr.fill()
                ink = T["primary"]
            else:
                self.rect_line(cr, x, y, w, h, T["st_hi"])
                ink = T["on_surface"]
        if bmp:
            cr.set_source_rgb(*ink)
            k = 2 if (kind == "trash" and K == 2) else 1
            draw_bitmap(cr, bmp, x + (w - len(bmp[0]) * k) // 2 + (1 if on and st == "default" else 0),
                        y + (h - len(bmp) * k) // 2 + (1 if on and st == "default" else 0), k)
        if label:
            self.text(cr, label, x, y + (h - PX) // 2, ink, w, align=Pango.Alignment.CENTER)

    def caps(self, cr):
        self.button(cr, self.zone_pin(), on=self.pinned, kind="pin", bmp=PIN_BMP,
                    hover=self.hover == "pin")
        self.button(cr, self.zone_close(), kind="close", bmp=X_BMP, hover=self.hover == "close")

    # ── рамки и заголовки трёх стилей ──────────────────────────────────────
    def title_bar(self, cr, x, y, w, title):
        """Полоса заголовка XP: градиент «Пуска», значок-квадратик, имя с тенью."""
        g = cairo.LinearGradient(0, y, 0, y + TB)
        for off, key in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(off, *T[key])
        cr.set_source(g)
        cr.rectangle(x, y, w, TB)
        cr.fill()
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(x, y + TB - 1, w, 1)
        cr.fill()
        ix, iy = x + 6, y + (TB - 10) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.rectangle(ix + 1, iy + 1, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["on_surface"])
        cr.rectangle(ix, iy, 10, 10)
        cr.fill()
        cr.set_source_rgb(*T["st_mid"])
        cr.rectangle(ix + 3, iy + 3, 4, 4)
        cr.fill()
        lay = self.layout(cr, title, w - 22 - 2 * (CAP + 6))
        ty = y + (TB - lay.get_pixel_size()[1]) // 2
        cr.set_source_rgb(*T["st_dark"])
        cr.move_to(ix + 17, ty + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(*T["on_surface"])
        cr.move_to(ix + 16, ty)
        PangoCairo.show_layout(cr, lay)

    def frame_default(self, cr):
        self.band(cr, 0, BORDER, T["st_mid"])
        self.title_bar(cr, BORDER, BORDER, W - 2 * BORDER, TITLE)
        self.caps(cr)

    def frame_skeet(self, cr):
        C = self.C
        # рамка слоями, как у окна skeet в Настройках (снаружи внутрь): 1 светлее,
        # 3 средняя, 1 светлее, 1 почти чёрная; светлые — с акцентом (окно активно)
        for i, w, key in ((0, 1, "line1_on"), (1, 3, "line2"), (4, 1, "line1_on"), (5, 1, "line3")):
            self.band(cr, i, w, C[key])
        # полоска сверху — три тона палитры, под ней та же темнее
        for dy, k in ((0, 0.0), (1, 0.55)):
            g = cairo.LinearGradient(BORDER, 0, W - BORDER, 0)
            for off, col in zip((0, 0.5, 1), C["strip"]):
                g.add_color_stop_rgb(off, *mix(col, (0, 0, 0), k))
            cr.set_source(g)
            cr.rectangle(BORDER, BORDER + dy, W - 2 * BORDER, 1)
            cr.fill()
        # заголовок: тёмный, линия снизу двойная
        self.rect_fill(cr, BORDER, TOP + TB - 2, W - 2 * BORDER, 1, C["line2"])
        self.rect_fill(cr, BORDER, TOP + TB - 1, W - 2 * BORDER, 1, C["line3"])
        cr.set_source_rgb(*C["icon_on"])
        draw_bitmap(cr, CLIP_BMP, BORDER + 7, TOP + (TB - 9) // 2)
        self.text(cr, TITLE, BORDER + 7 + 7 + 6, TOP + (TB - PX) // 2 - 1, C["text"])
        self.caps(cr)

    def frame_beta(self, cr):
        C = self.C
        self.band(cr, 0, BORDER, C["frame"])
        self.rect_fill(cr, BORDER, TOP, W - 2 * BORDER, TB, C["bar"])
        self.rect_fill(cr, BORDER, TOP + TB - 1, W - 2 * BORDER, 1, C["line"])
        cr.set_source_rgb(*C["acc_text"])
        draw_bitmap(cr, CLIP_BMP, BORDER + 8, TOP + (TB - 18) // 2, 2)
        self.text(cr, TITLE, BORDER + 8 + 14 + 8, TOP + (TB - PX) // 2, C["text"])
        self.caps(cr)

    # ── строка поиска, вкладки ─────────────────────────────────────────────
    def draw_search(self, cr):
        C, st = self.C, self.style
        tx, ty, tw, th = self.zone_trash()
        sw = CW - tw - 8
        if st == "skeet":
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, C["field"])
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, C["acc_d"])
            self.rect_line(cr, X0 + 1, SEARCH_Y + 1, sw - 2, SEARCH_H - 2, C["gline"])
            lens = C["text_dim"]
        elif st == "beta":
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, C["field"])
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, C["acc"])
            lens = C["dim"]
        else:
            self.rect_fill(cr, X0, SEARCH_Y, sw, SEARCH_H, T["st_dark"], 0.5)
            self.rect_line(cr, X0, SEARCH_Y, sw, SEARCH_H, T["st_top"])
            lens = T["st_hi"]
        li = 9 * K
        cr.set_source_rgb(*lens)
        draw_bitmap(cr, LENS_BMP, X0 + 8, SEARCH_Y + (SEARCH_H - li) // 2, K)
        x = X0 + 8 + li + 8
        room = sw - (x - X0) - 14
        y = SEARCH_Y + (SEARCH_H - PX) // 2
        if self.query:
            lay = self.layout(cr, self.query, room)
            lay.set_ellipsize(Pango.EllipsizeMode.START)      # длинный запрос — виден хвост
            cr.set_source_rgb(*C["text"])
            cr.move_to(x, y)
            PangoCairo.show_layout(cr, lay)
            cx = x + lay.get_pixel_size()[0] + 2
        else:
            self.text(cr, "поиск…",
                      x + 6, y, C["dim"], alpha=0.75)
            cx = x
        if self.insert:                                       # курсор — только в режиме поиска
            cr.set_source_rgb(*C["accent"])
            cr.rectangle(cx, y, 2 if K == 2 else 1, PX)
            cr.fill()
        # корзина: очистить историю
        self.button(cr, (tx, ty, tw, th), kind="trash", bmp=TRASH_BMP, hover=self.hover == "trash")
        if not self.hist:                                     # истории нет — корзина бледная
            cr.set_source_rgba(*C["win_bg"], 0.55)
            cr.rectangle(tx + 1, ty + 1, tw - 2, th - 2)
            cr.fill()

    def draw_tabs(self, cr):
        C, st = self.C, self.style
        for i, (x, y, w, h, name, num) in enumerate(self.tab_zones()):
            on = i == self.tab
            pad = 8 if st != "skeet" else 7
            if st == "skeet":
                self.rect_fill(cr, x, y, w, h, C["field"] if on else C["bg"])
                self.rect_line(cr, x, y, w, h, C["line3"])
                self.rect_line(cr, x + 1, y + 1, w - 2, h - 2, C["gline"])
                fg, dimc = (C["acc_l"], C["text_dim"]) if on else (C["text_dim"], C["icon"])
            elif st == "beta":
                self.rect_fill(cr, x, y, w, h, C["acc"] if on else C["field"])
                self.rect_line(cr, x, y, w, h, C["acc"] if on else C["line_strong"])
                fg, dimc = (C["on_acc"], C["on_acc"]) if on else (C["text"], C["dim"])
            else:
                if on:
                    g = cairo.LinearGradient(0, y, 0, y + h)
                    g.add_color_stop_rgb(0, *T["st_top"])
                    g.add_color_stop_rgb(1, *T["st_bot"])
                    cr.set_source(g)
                    cr.rectangle(x, y, w, h)
                    cr.fill()
                    self.rect_line(cr, x, y, w, h, T["st_hi"])
                else:
                    self.rect_fill(cr, x, y, w, h, T["fg"], 0.05)
                    self.rect_line(cr, x, y, w, h, T["line2"])
                fg, dimc = (T["on_surface"], T["st_dark"]) if on else (T["on_surface_variant"], T["dim"])
            tx, ty = x + pad, y + (h - PX) // 2
            if i == FAVS:
                cr.set_source_rgb(*fg)
                draw_bitmap(cr, STAR_ON, tx, y + (h - STAR) // 2, K)
                tx += STAR + 6
            lw = self.text(cr, name, tx, ty, fg)[0]
            if num:
                self.text(cr, num, tx + (len(name) + 1) * ADV, ty, dimc, alpha=0.85)
            if st == "skeet" and on:                  # подчёркнутая выбранная, как сегменты skeet
                self.rect_fill(cr, tx, ty + PX + 1, lw + ((len(num) + 1) * ADV if num else 0), 1, C["acc"])

    # ── просмотр ───────────────────────────────────────────────────────────
    def draw_view(self, cr):
        C, st, v = self.C, self.style, self.vdata
        back, copy = self.view_btns()
        self.button(cr, back, kind="dlg", label="← Назад", hover=self.hover == "back")
        self.button(cr, copy, on=True, kind="dlg", label="Скопировать", hover=self.hover == "copy")
        cx = back[0] + back[2] + 10
        self.text(cr, v.get("cap", ""), cx, SEARCH_Y + (SEARCH_H - PX) // 2, C["dim"],
                  copy[0] - 10 - cx, align=Pango.Alignment.CENTER)
        bx, by, bw, bh = self.view_box()
        if st == "skeet":
            self.rect_fill(cr, bx, by, bw, bh, C["gdark"], 0.55)
            self.rect_line(cr, bx, by, bw, bh, C["gline"])
            self.rect_line(cr, bx + 1, by + 1, bw - 2, bh - 2, C["gdark"])
            name = "Просмотр"
            self.rect_fill(cr, bx + 10, by - 1, len(name) * ADV + 8, 3, C["bg"])
            self.text(cr, name, bx + 14, by - PX // 2 - 1, C["text"])
        elif st == "beta":
            self.rect_fill(cr, bx, by, bw, bh, C["card"])
            self.rect_line(cr, bx, by, bw, bh, C["line"])
        else:
            self.rect_fill(cr, bx, by, bw, bh, T["st_dark"], 0.5)
            self.rect_line(cr, bx, by, bw, bh, T["st_top"])
        x, y, w, h = v["x"], v["y"], v["w"], v["h"]
        cr.save()
        cr.rectangle(x, y, w, h)
        cr.clip()
        if v.get("err"):
            self.text(cr, v["err"], x, y + h // 2 - PX, C["dim"], w, align=Pango.Alignment.CENTER)
        elif v["kind"] == "image":
            s = v["surf"]
            ix, iy = x + (w - s.get_width()) // 2, y + (h - s.get_height()) // 2
            cr.set_source_surface(s, ix, iy)
            cr.paint()
            self.rect_line(cr, ix - 1, iy - 1, s.get_width() + 2, s.get_height() + 2, C["dim"], 0.5)
        else:
            col = C["dim"] if v["empty"] else C["text"]
            cr.set_source_rgb(*col)
            top = self.vscroll
            for y0, y1, base, line in v["lines"]:
                if y1 < top:
                    continue
                if y0 > top + h:
                    break
                cr.move_to(x, y + base - top)
                PangoCairo.show_layout_line(cr, line)
        cr.restore()
        g = self.thumb_geom()
        if g:
            gx, ky, kh = g
            if st == "default":
                self.rect_fill(cr, gx, y, BAR, h, T["fg"], 0.07)
            elif st == "beta":
                self.rect_fill(cr, gx, y, BAR, h, C["line_soft"])
            active = self.drag is not None or self.hover == "bar"
            self.rect_fill(cr, gx, ky, BAR, kh, C["scroll_on"] if active else C["scroll"])

    # ── список ─────────────────────────────────────────────────────────────
    def draw_list_box(self, cr):
        """Подложка списка: в skeet — группа с подписью в рамке, в Beta — карточка."""
        C, st = self.C, self.style
        if st == "skeet":
            gx, gy, gw, gh = X0, LIST_Y - 10, CW, LIST_H + 18
            self.rect_line(cr, gx, gy, gw, gh, C["gline"])
            self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
            name = "Поиск" if self.query.strip() else TABS[self.tab]
            lw = len(name) * ADV
            self.rect_fill(cr, gx + 10, gy - 1, lw + 8, 3, C["bg"])
            if self.dots is not None:
                cr.save()
                cr.rectangle(gx + 10, gy - 1, lw + 8, 3)
                cr.clip()
                cr.set_source(self.dots)
                cr.paint()
                cr.restore()
            self.text(cr, name, gx + 14, gy - PX // 2 - 1, C["text"])
        elif st == "beta":
            self.rect_fill(cr, X0, LIST_Y - 1, CW, LIST_H + 2, C["card"])
            self.rect_line(cr, X0, LIST_Y - 1, CW, LIST_H + 2, C["line"])

    def draw_list(self, cr):
        C = self.C
        if not self.rows:
            msg = "Ничего не найдено" if self.query.strip() else EMPTY[self.tab]
            lay = self.layout(cr, msg, LW - 40, 3)
            lay.set_alignment(Pango.Alignment.CENTER)
            cr.set_source_rgba(*C["dim"], 0.9)
            cr.move_to(LX + 20, LIST_Y + LIST_H // 2 - lay.get_pixel_size()[1] // 2 - 16)
            PangoCairo.show_layout(cr, lay)
            return
        lw = self.list_w()
        fav_shas = {r["sha"] for r in self.favs}
        for i, e in enumerate(self.rows):
            y = LIST_Y + self.tops[i] - self.scroll
            h = e.height()
            if y + h <= LIST_Y:
                continue
            if y >= LIST_Y + LIST_H:
                break
            self.draw_row(cr, e, LX, y, lw, h, i == self.sel, e.src == "fav" or e.sha in fav_shas,
                          i == len(self.rows) - 1)
        g = self.thumb_geom()
        if g:                                          # полоса прокрутки
            bx, ky, kh = g
            if self.style == "default":
                self.rect_fill(cr, bx, LIST_Y, BAR, LIST_H, T["fg"], 0.07)
            elif self.style == "beta":
                self.rect_fill(cr, bx, LIST_Y, BAR, LIST_H, C["line_soft"])
            active = self.drag is not None or self.hover == "bar"
            self.rect_fill(cr, bx, ky, BAR, kh, C["scroll_on"] if active else C["scroll"])

    def draw_row(self, cr, e, x, y, w, h, sel, starred, last):
        C, st = self.C, self.style
        if sel:
            self.rect_fill(cr, x, y, w, h, C["sel_bg"])
            if st == "skeet":
                self.rect_line(cr, x, y, w, h, C["gline"])
                self.rect_fill(cr, x, y, 2, h, C["acc"])
        elif st == "default":
            self.rect_fill(cr, x, y, w, h, T["fg"], 0.045)
        if st == "beta" and not last:
            self.rect_fill(cr, x, y + h, w, 1, C["line_soft"])
        fg = C["sel_text"] if sel else C["text"]
        dim = C["sel_dim"] if sel else C["dim"]
        sx = x + w - 12 - STAR
        if e.kind == "image":
            px, py = x + (7 if st != "skeet" else 8), y + (h - TH) // 2
            self.rect_fill(cr, px, py, TW, TH, C["thumb_bg"], C["thumb_alpha"])
            surf = self.thumb(e)
            if surf:
                cr.set_source_surface(surf, px + (TW - surf.get_width()) // 2,
                                      py + (TH - surf.get_height()) // 2)
                cr.paint()
            elif surf is None:
                cr.set_source_rgba(*C["dim"], 0.6)
                draw_bitmap(cr, IMG_BMP, px + (TW - 9 * (K + 1)) // 2, py + (TH - 7 * (K + 1)) // 2, K + 1)
            if st == "skeet":
                self.rect_line(cr, px - 1, py - 1, TW + 2, TH + 2, C["line3"])
            tx = px + TW + 14
            tw = sx - 10 - tx
            n = 3 if sel else 2
            ty = y + (h - (n * LINE - (LINE - PX))) // 2
            cr.set_source_rgb(*fg)
            draw_bitmap(cr, IMG_BMP, tx, ty + (PX - 7 * K) // 2, K)
            self.text(cr, "Картинка", tx + 9 * K + 8, ty, fg, tw - 26)
            self.text(cr, e.meta_line(), tx, ty + LINE, dim, tw)
            if sel:
                self.text(cr, "Enter — посмотреть · ПКМ — в буфер", tx, ty + 2 * LINE, dim, tw)
        else:
            tx = x + 10
            tw = sx - 12 - tx
            long = h == TXT_ROW
            n = 3 if long else 2
            ty = y + (h - (n * LINE - (LINE - PX) + 2)) // 2
            self.text(cr, e.preview or "(пусто)", tx, ty, fg, tw, 2 if long else 1)
            self.text(cr, e.meta_line(), tx, ty + (2 * LINE if long else LINE) + 2, dim, tw)
        if starred:
            cr.set_source_rgb(*(C["sel_star"] if sel else C["star_on"]))
        else:
            cr.set_source_rgba(*dim, 0.9 if sel else 0.55)
        draw_bitmap(cr, STAR_ON if starred else STAR_OFF, sx, y + (h - STAR) // 2, K)

    def draw_footer(self, cr):
        C = self.C
        hints = {"pin": "Открепить" if self.pinned else "Закрепить: окно не закроется после вставки",
                 "close": "Закрыть (Esc)", "trash": "Очистить историю (Shift+Del)",
                 "bar": "Тяните ползунок или щёлкните по полосе",
                 "back": "Назад к списку (Esc)", "copy": "Положить в буфер (Enter, ПКМ, Ctrl+C)"}
        left, color = self.status, C["accent"]
        if not left and self.hover in hints:
            left, color = hints[self.hover], C["text"]
        if not left and self.pinned:
            left = "Закреплено — окно не закроется после вставки"
        if not left and self.query.strip():
            left = "найдено: %d" % len(self.rows)
        lay = self.layout(cr, "Enter — скопировать · Esc — назад" if self.view is not None
                          else ("-- ПОИСК -- · Esc — выйти" if self.insert
                                else "f — избранное · Ctrl+E — режим"))
        hw = lay.get_pixel_size()[0]
        lw = self.text(cr, left, X0, FOOT_Y, color, CW)[0] if left else 0
        if lw + 24 <= CW - hw:                        # подсказка — если рядом с сообщением есть место
            cr.set_source_rgba(*C["dim"], 0.8)
            cr.move_to(X0 + CW - hw, FOOT_Y)
            PangoCairo.show_layout(cr, lay)

    def draw_confirm(self, cr):
        C, st = self.C, self.style
        (bx, by, bw, bh), yes, no = self.zone_confirm()
        cr.set_source_rgba(*C["win_bg"], 0.62)                # приглушить всё под вопросом
        cr.rectangle(BORDER, TOP + TB, W - 2 * BORDER, H - TOP - TB - BORDER)
        cr.fill()
        if st == "skeet":
            self.rect_fill(cr, bx, by, bw, bh, C["bg"])
            if self.dots is not None:
                cr.save()
                cr.rectangle(bx, by, bw, bh)
                cr.clip()
                cr.set_source(self.dots)
                cr.paint()
                cr.restore()
            self.rect_line(cr, bx, by, bw, bh, C["line1_on"])
            self.rect_line(cr, bx + 1, by + 1, bw - 2, bh - 2, C["line3"])
            g = cairo.LinearGradient(bx + 2, 0, bx + bw - 2, 0)
            for off, col in zip((0, 0.5, 1), C["strip"]):
                g.add_color_stop_rgb(off, *col)
            cr.set_source(g)
            cr.rectangle(bx + 2, by + 2, bw - 4, 1)
            cr.fill()
            dtb = PX + 10
            self.text(cr, "Очистка", bx + 10, by + 2 + (dtb - PX) // 2, C["text_dim"])
            self.rect_fill(cr, bx + 2, by + DLG_B + dtb - 1, bw - 4, 1, C["line3"])
        elif st == "beta":
            self.rect_fill(cr, bx, by, bw, bh, C["card"])
            self.rect_line(cr, bx, by, bw, bh, C["line_strong"])
            self.rect_fill(cr, bx + 1, by + 1, bw - 2, TB - 1, C["bar"])
            self.rect_fill(cr, bx + 1, by + TB, bw - 2, 1, C["line"])
            cr.set_source_rgb(*C["acc_text"])
            draw_bitmap(cr, TRASH_BMP, bx + 10, by + (TB - 18) // 2 + 1, 2)
            self.text(cr, "Очистка", bx + 36, by + (TB - PX) // 2, C["text"])
            dtb = TB
        else:
            cr.set_source_rgb(*mix(T["bg"], T["st_mid"], 0.10))
            cr.rectangle(bx, by, bw, bh)
            cr.fill()
            cr.save()
            cr.translate(bx, by)
            sw, sh = bw, bh
            cr.set_source_rgb(*T["st_mid"])
            cr.rectangle(0, 0, sw, sh)
            cr.rectangle(DLG_B, DLG_B, sw - 2 * DLG_B, sh - 2 * DLG_B)
            cr.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            cr.fill()
            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
            cr.restore()
            self.title_bar(cr, bx + DLG_B, by + DLG_B, bw - 2 * DLG_B, "Очистка.exe")
            dtb = TB
        ty = by + DLG_B + dtb + 14
        self.text(cr, "Очистить историю?", bx, ty, C["text"], bw, align=Pango.Alignment.CENTER,
                  bold=st == "beta")
        self.text(cr, "Избранное останется", bx, ty + LINE, C["dim"], bw,
                  align=Pango.Alignment.CENTER)
        for zone, name, key in ((yes, "Да", "yes"), (no, "Нет", "no")):
            self.button(cr, zone, on=self.confirm == key, kind="dlg", label=name)


def main():
    app = App()
    try:
        from gi.repository import GLibUnix
        add = GLibUnix.signal_add
    except ImportError:                        # старый PyGObject без GLibUnix
        add = GLib.unix_signal_add
    # приоритет обычный, не HIGH — см. App.finish
    add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, app.toggle)
    add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, app.quit)
    add(GLib.PRIORITY_DEFAULT, signal.SIGINT, app.quit)
    if "--daemon" in sys.argv:                 # ждать спрятанным, пока не позовут; без срока
        app.forever = True
        read_list(PRELIST)
        load_theme()
    else:
        app.open(read_list(PRELIST), mode="cold")
    try:
        Gtk.main()
    finally:                                   # сюда — только при исключении: обычный выход в App.finish
        app.save_meta()
        remove_pidfile()
    return 0


if __name__ == "__main__":
    sys.exit(main())
