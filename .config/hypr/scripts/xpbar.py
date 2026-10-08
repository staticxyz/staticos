#!/usr/bin/env python3
"""Нижняя панель задач в стиле Windows XP — в цветах обоев. 30.09.2026.

    xpbar.py                     сама панель (запускает bottom_bar.py, не руками)
    xpbar.py start|stop|restart  поднять / погасить / перезапустить
    xpbar.py status              on / off

Просьба: «должен полностью быть похожим на классический таскбар Windows XP»,
образец — нижняя панель angelOS. Выбор «ничего / док / XP» и режим появления
(всегда / при наведении) — bottom_bar.py и Настройки. Одновременно с доком
не живёт: включает одно, гасит другое bottom_bar.py.

Слева направо:
  * «Пуск» — скруглённая справа кнопка с логотипом и надписью static: живой
    пиксельный спрайт из ~/Pictures/logo/anime-sprite/chosen/ (кадры + info.json),
    если его нет — телевизор static 14×13 в цветах палитры. Щелчок — меню программ.
  * «Ручка» из точек, как у панелей XP.
  * Окна текущего стола этого монитора: одна кнопка — одно окно, значок и
    заголовок. Не влезают — по краям стрелки, колёсико листает. Левый щелчок —
    перейти к окну, средний — закрыть, правый — меню.
  * По центру — текст песни (lyrics_bar.App): обложка или нота, строка
    появляется на PREVIEW с раньше, чем её начнут петь, пропетое — акцентом.
  * Справа — «область уведомлений» с кромкой, как в XP: раскладка, громкость,
    уведомления, часы.
По верхней кромке — светлая линия в 1 px и полутон под ней: та самая «особая
линия» XP (и образца), дальше — вертикальный градиент.

Процессор: всё по событиям. Окна и раскладка — из потока событий niri (без
вызовов niri msg на каждое изменение), громкость — pactl subscribe, уведомления —
swaync-client -swb, часы — таймер на начало минуты, текст песни — таймер на
следующее слово. Анимация логотипа идёт, только пока панель видна.
"""
import hashlib
import html
import io
import json
import math
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
SHOW_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-show")
GAP_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-gap")      # off — окна вплотную
WORDMARK = os.path.expanduser("~/Pictures/logo/static-logo/static-wordmark-native.png")
LAYOUT_KDL = os.path.expanduser("~/.config/niri/cfg/layout.kdl")
SPRITE_DIR = os.path.expanduser("~/Pictures/logo/anime-sprite/chosen")
COVERS = os.path.expanduser("~/.cache/player-covers")
PALETTE_FILE = os.path.expanduser("~/.cache/matugen/colors.json")



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


def _die_with_parent():
    """preexec_fn для фоновых подписок (pactl subscribe, swaync-client -swb,
    niri event-stream): ядро убьёт их вместе с этим процессом (PR_SET_PDEATHSIG).
    01.10.2026: без этого каждый перезапуск панели оставлял сирот — к ночи их
    набралось больше сотни, pipewire-pulse упёрся в предел клиентов («too many
    client application connections») и новые программы остались без звука."""
    import ctypes
    import signal as _signal
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, _signal.SIGTERM)


def running_pids():
    me = os.getpid()
    out = []
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == me:
            continue
        try:
            argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
        except OSError:
            continue
        if len(argv) >= 2 and b"python" in os.path.basename(argv[0]) \
                and os.path.basename(argv[1]) == b"xpbar.py" \
                and (len(argv) == 2 or argv[2] == b""):
            out.append(int(p))
    return out


def _start():
    if running_pids():
        return
    log = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar.log")
    # Панель поднимает niri, а не вызвавший процесс (02.10.2026): перезапущенная из
    # терминала, она наследовала его окружение (KITTY_*, DESKTOP_STARTUP_ID…) и
    # передавала его всему, что запускалось из «Пуска» и трея.
    if os.environ.get("NIRI_SOCKET"):
        try:
            r = subprocess.run(["niri", "msg", "action", "spawn", "--", "sh", "-c",
                                'exec python3 "$0" 2>>"$1"', os.path.abspath(__file__), log],
                               capture_output=True, timeout=2)
            if r.returncode == 0:
                return
        except (OSError, subprocess.SubprocessError):
            pass
    subprocess.Popen([sys.executable, os.path.abspath(__file__)], stdout=subprocess.DEVNULL,
                     stderr=open(log, "a"), start_new_session=True)


def _stop():
    pids = running_pids()
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass
    # до 3 с: панель на двух мониторах закрывается дольше секунды, и restart тогда не
    # запускал новую — видел старую живой (06.10.2026)
    for _ in range(60):
        if not any(os.path.exists("/proc/%d" % p) for p in pids):
            break
        time.sleep(0.05)
    else:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        time.sleep(0.2)


if sys.argv[1:2] == ["status"]:
    print("on" if running_pids() else "off")
    sys.exit(0)
if sys.argv[1:2] == ["start"]:
    _start()
    sys.exit(0)
if sys.argv[1:2] == ["stop"]:
    _stop()
    sys.exit(0)
if sys.argv[1:2] == ["restart"]:
    _stop()
    _start()
    sys.exit(0)
if sys.argv[1:]:
    print(__doc__)
    sys.exit(0)
if running_pids():
    sys.exit(0)          # уже работает

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango  # noqa: E402
import cairo  # noqa: E402

import popup_theme  # noqa: E402
import pixel_recolor  # noqa: E402
import lyrics_bar as LB  # noqa: E402
from PIL import Image  # noqa: E402

H = 32                   # высота панели, как у верхнего бара
TASK_W = 136             # ширина кнопки окна — наибольшая (было 176; 05.10.2026, Просьба: «чтобы больше вмещалось»)
TASK_MIN = 90            # окон много — кнопки сжимаются до этой ширины, дальше прокрутка (было 110)
GLUE_SHOW = 4            # «вплотную»: сколько пикселей нижней рамки окна видно над панелью (2 → 4, 04.10.2026: «рамки вообще не вижу»)
LYR_W = 470              # место под текст песни справа — постоянное, панель не пляшет
LYRICS_MAX = 40          # знаков строки песни в панели — предел; на деле fit_lyrics() по ширине
PREVIEW = 0.4            # строка появляется раньше, чем её начнут петь, с
                         # (0.8 — «переборщил со скоростью», 01.10.2026)
PAUSE_HIDE_S = 30        # текст песни прячется, если пауза дольше
HIDE_MS = 600            # режим «при наведении»: курсор ушёл — через столько спрятать
FONT = "'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', monospace"
# Подписи окон и трей — 12 px, как было до сведения к сетке (05.10.2026, Просьба: «раньше было
# мельче», «эстетичность, но пиксельность»). Оригинальное имя шрифта (без «Jarvis»): правило
# fontconfig 62-pxplus-grid-trial (12 → 16) его не трогает.
FONT12 = "'PxPlus HP 100LX 6x8', 'PxPlus HP 100LX 6x8 Jarvis', monospace"
NERD = "'Symbols Nerd Font', 'JetBrainsMono NF'"
HIDDEN_APPS = ("dash-",)
LB.MAX_LEN = LYRICS_MAX
LB.DIM_ALPHA = "50%"      # непропетое бледнее, чем в верхнем баре: акцент и текст здесь близки

# Телевизор static в 14×13 пикселей (логотип из ~/Pictures/logo/static-logo,
# пересобранный под панель: крупнее, чем 32×32 в родном размере, быть не может,
# а уменьшение 32 → 16 съедало букву). O контур, H свет, B основной, D тень,
# S экран, W буква, N помехи, K ручки, R лампочка.
TV = [
    "...O......O...",
    "....O....O....",
    ".OOOOOOOOOOOO.",
    "OHHHHHHHHHHHHO",
    "OBOOOOOOOOBBBO",
    "OBOSWWWNSOBKBO",
    "OBONWSSSSOBBBO",
    "OBOSWWWSNOBKBO",
    "OBOSSSWSSOBBBO",
    "OBONWWWSSOBRBO",
    "OBOOOOOOOOBBBO",
    "ODDDDDDDDDDDDO",
    ".OOOOOOOOOOOO.",
]


# ── цвета — в xpbar_colors.py (общие с меню «Пуск») ──────────────────────────

from xpbar_colors import colors, hex2rgb, mix, rgb2hex  # noqa: E402,F401


CSS = """
window.xpbar-win { background: transparent; }
.xpbar {
    background-color: %(g_mid)s;
    background-image: linear-gradient(to bottom, %(g_top)s, %(g_mid)s 45%%, %(g_bot)s);
    border-top: 1px solid %(line1)s;
    box-shadow: inset 0 1px %(line2)s;
    min-height: 31px;
    font-family: %(font12)s; font-size: 12px; font-weight: normal;
    color: %(text)s;
}
button.start {
    background-color: %(st_mid)s;
    background-image: linear-gradient(to bottom, %(st_top)s, %(st_mid)s 55%%, %(st_bot)s);
    border: none; border-radius: 0 13px 13px 0;
    box-shadow: inset 0 1px %(st_hi)s, inset -1px -1px %(st_dark)s, 2px 0 3px alpha(black, 0.45);
    padding: 0 16px 0 6px; margin: 0 8px 0 0; min-height: 0;
    color: %(text)s; text-shadow: 1px 1px alpha(black, 0.7);
    /* «PxPlus Keep» (fontconfig 62-pxplus-keep.conf) — PxPlus 16 px и под пробой Cozette:
       «пуск надо крупным вернуть, как он был» (08.10.2026) */
    font-family: 'PxPlus Keep', %(font)s; font-size: 16px; font-weight: normal;
}
/* Наведение — светлее, а не «нажато»: утопленной кнопка бывает только при
   открытом меню (класс open), 01.10.2026. */
button.start:hover {
    background-image: linear-gradient(to bottom, %(st_hi)s, %(st_hover)s 30%%, %(st_top)s);
    box-shadow: inset 0 1px %(st_hi)s, inset -1px -1px %(st_dark)s, 2px 0 3px alpha(black, 0.45),
                0 0 6px alpha(%(st_hi)s, 0.35);
}
/* Нажатый «Пуск» — пока открыто меню (класс open) и под пальцем: как в XP,
   темнее, тень внутрь, содержимое съезжает на пиксель вниз-вправо. */
button.start.open, button.start.open:hover, button.start.open:active {
    background-image: linear-gradient(to bottom, %(st_press_top)s, %(st_press_bot)s);
    box-shadow: inset 3px 3px 5px alpha(black, 0.8), inset -1px -1px %(st_bot)s;
    padding: 1px 15px 0 7px;
}
/* Столы в нижней панели (03.10.2026, top_bar.py ws bottom): маленькие кнопки между
   «Пуском» и окнами, как «быстрый запуск» в XP. Значки — тот же шрифт, что в верхнем баре. */
button.ws {
    background: transparent; background-image: none; border: 1px solid transparent;
    border-radius: 3px; box-shadow: none; padding: 0 5px; margin: 4px 1px 3px 1px;
    min-height: 0; min-width: 20px; color: %(text)s;
}
button.ws label { font-family: "JarvisBarIcons", "JetBrainsMono Nerd Font", %(font)s; font-size: 16px; font-weight: normal; }
button.ws:hover { background-image: linear-gradient(to bottom, %(t_hover_top)s, %(t_hover_bot)s); border-color: %(t_border)s; }
button.ws.active {
    background-image: linear-gradient(to bottom, %(f_top)s, %(f_bot)s);
    border-color: %(f_border)s; box-shadow: inset 1px 1px 2px alpha(black, 0.6);
}
button.ws.empty { color: alpha(%(text)s, 0.5); }
/* Стол в фокусе — светлая плашка акцента, даже ПУСТОЙ (05.10.2026, Просьба: «перешёл на
   пустой стол — непонятно, где фокус»). Раньше было только цветом текста, и правило
   .empty (тусклый текст) его перебивало. */
button.ws.focused, button.ws.focused.empty {
    background-image: linear-gradient(to bottom, %(st_hi)s, %(st_top)s);
    border-color: %(st_mid)s; color: %(st_dark)s;
    box-shadow: inset 0 1px 0 alpha(white, 0.35);
}
button.task {
    background-color: %(t_bot)s;
    background-image: linear-gradient(to bottom, %(t_top)s, %(t_bot)s);
    border: 1px solid %(t_border)s; border-radius: 3px;
    box-shadow: inset 0 1px %(t_hi)s;
    padding: 0 8px; margin: 4px 2px 3px 2px; min-height: 0;
    color: %(text)s; text-shadow: none;
    font-family: %(font12)s; font-size: 12px; font-weight: normal;
}
button.task:hover { background-image: linear-gradient(to bottom, %(t_hover_top)s, %(t_hover_bot)s); }
button.task.focused {
    background-image: linear-gradient(to bottom, %(f_top)s, %(f_bot)s);
    border-color: %(f_border)s;
    box-shadow: inset 1px 1px 2px alpha(black, 0.6);
    color: %(primary)s;
}
button.task.urgent { border-color: %(error)s; box-shadow: inset 0 -2px %(error)s; }
button.arrow {
    background: transparent; background-image: none; border: none; box-shadow: none;
    padding: 0 4px; margin: 0; min-height: 0; min-width: 0;
    color: %(dim)s; font-family: %(nerd)s; font-size: 12px;
}
button.arrow:hover { color: %(primary)s; }
.tray {
    background-color: %(tr_bot)s;
    background-image: linear-gradient(to bottom, %(tr_top)s, %(tr_bot)s);
    border-left: 1px solid %(tr_dark)s;
    box-shadow: inset 1px 0 %(tr_light)s, inset 0 1px %(tr_light)s;
    padding: 0 12px 0 10px;
}
.tray label { font-family: %(font12)s; font-size: 12px; color: %(text)s; }
window.xptray-win { background: transparent; }
.xptray {
    background-color: %(g_mid)s;
    background-image: linear-gradient(to bottom, %(tr_top)s, %(tr_bot)s);
    border: 1px solid %(tr_light)s; border-radius: 0; padding: 3px;
    box-shadow: 0 0 0 1px %(tr_dark)s, 3px 3px 0 0 alpha(black, 0.45);
}
button.xptray-item {
    background: transparent; background-image: none; border: 1px solid transparent;
    box-shadow: none; padding: 3px; margin: 0; min-width: 0; min-height: 0; border-radius: 2px;
}
button.xptray-item:hover { border-color: %(tr_light)s; background-color: alpha(%(primary)s, 0.18); }
.tray label.glyph { font-family: %(nerd)s; font-size: 14px; }
.tray label.clock { font-size: 12px; }
/* Раскладка — как индикатор языка в трее Windows XP (05.10.2026, Просьба: «стали больше,
   хочу как в Windows — помельче и в своей маленькой рамке»): родной кегль шрифта 8 px
   (чёткий), квадратик тонами «Пуска» со светлой кромкой. */
.tray label.lang {
    font-size: 8px; color: #ffffff; padding: 2px 3px 1px 3px; margin: 7px 0;
    background-color: %(st_mid)s;
    background-image: linear-gradient(to bottom, %(st_top)s, %(st_bot)s);
    border: 1px solid %(st_hi)s; border-radius: 2px;
    box-shadow: inset -1px -1px alpha(black, 0.35);
}
.tray label.off { color: %(dim)s; }
.tray eventbox { padding: 0 2px; }
label.lyrics { font-family: %(font)s; font-size: 16px; color: %(text)s; }
label.note { font-family: %(nerd)s; font-size: 16px; color: %(primary)s; }
menu, .menu, .context-menu {
    background-color: %(surface)s; color: %(on_surface)s;
    border: 2px solid %(primary)s; border-radius: 8px; padding: 4px;
}
menuitem { font-family: %(font)s; font-size: 16px; padding: 5px 12px; border-radius: 5px; }
menuitem:hover { background-color: %(surface_high)s; color: %(primary)s; }
tooltip { background-color: %(surface)s; color: %(on_surface)s; border: 1px solid %(primary)s; border-radius: 6px; }
tooltip label { font-family: %(font)s; font-size: 16px; font-weight: normal; padding: 2px 6px; }
"""

_provider = None


# Вид кнопки «Пуск» (03.10.2026, `start_menu.py button default|square`): square —
# прямоугольный блок с пиксельной рамкой без скругления, по образцу панели angelOS.
# Высота та же: рамка 1 px + внутренняя линия тенью, поля 1 px — под логотип 26 px
# (поля 2 px раздували панель на 1–2 px).
START_BUTTON_FILE = os.path.expanduser("~/.config/hypr/state/start-button-look")
START_LOOK_FILE = os.path.expanduser("~/.config/hypr/state/start-menu-look")
SQUARE_CSS = """
button.start {
    background-color: %(sq_bg)s; background-image: none;
    border-style: solid; border-width: 1px; border-radius: 0;
    border-color: %(sq_dark)s %(sq_light)s %(sq_light)s %(sq_dark)s;
    box-shadow: inset 1px 1px alpha(black, 0.35);
    padding: 0 9px 0 7px; margin: 3px 8px 3px 4px; min-height: 0;
    color: %(sq_text)s; text-shadow: none;
}
button.start:hover {
    background-color: %(sq_hover)s; background-image: none;
    border-color: %(sq_dark)s %(sq_light)s %(sq_light)s %(sq_dark)s;
    box-shadow: inset 1px 1px alpha(black, 0.35);
}
/* меню открыто — заметно, но спокойно: приглушённая заливка акцентом, светлее рамка,
   вдавленность (04.10.2026: «непонятно, что нажата», потом «слишком ярко») */
button.start.open, button.start.open:hover, button.start.open:active {
    background-color: %(sq_open)s; background-image: none;
    border-color: %(st_top)s;
    box-shadow: inset 2px 2px alpha(black, 0.35);
    /* без 1px сверху: кнопка «Квадратный» выше панели, лишний пиксель отступа
       поднимал всю панель при открытом меню (05.10.2026) */
    padding: 0 8px 0 8px; color: %(sq_open_text)s;
}
"""


def start_button_look():
    try:
        return "square" if open(START_BUTTON_FILE).read().strip() == "square" else "default"
    except OSError:
        return "default"


def load_css():
    global _provider
    c = colors()
    c.update(font=FONT, nerd=NERD, font12=FONT12)
    css = CSS % c
    if start_button_look() == "square":
        b, p = c["base"], c["primary"]
        # Утопленный тёмный блок, как кнопка angelOS (04.10.2026, «внимание к деталям»):
        # темнее панели, рамка-«врезка»: сверху/слева тень, снизу/справа светлый край.
        css += SQUARE_CSS % dict(c, sq_bg=mix(b, "#000000", 0.35), sq_hover=mix(b, p, 0.08),
                                 sq_press=mix(b, "#000000", 0.55),
                                 sq_dark=mix(b, "#000000", 0.70), sq_light=c["st_bot"],
                                 sq_text=mix(c["on_surface"], b, 0.12),
                                 sq_open=mix(b, p, 0.30), sq_open_text=c["st_hi"])
    prov = Gtk.CssProvider()
    prov.load_from_data(css.encode())
    screen = Gdk.Screen.get_default()
    if _provider:
        Gtk.StyleContext.remove_provider_for_screen(screen, _provider)
    Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _provider = prov
    return c


# ── niri ───────────────────────────────────────────────────────────────────

def niri_json(*args):
    try:
        out = subprocess.run(["niri", "msg", "-j", *args], capture_output=True, text=True,
                             timeout=2).stdout
        return json.loads(out)
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def action(*args):
    subprocess.Popen(["niri", "msg", "action", *args], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)


def niri_request(obj):
    """Запрос прямо в сокет niri — действия по id стола (`niri msg` принимает только
    номер на мониторе в фокусе или имя)."""
    import socket
    try:
        sk = socket.socket(socket.AF_UNIX)
        sk.settimeout(2)
        sk.connect(os.environ["NIRI_SOCKET"])
        sk.sendall(json.dumps(obj).encode() + b"\n")
        sk.makefile().readline()
        sk.close()
    except (OSError, KeyError):
        pass


def _ws_bottom():
    """Столы показывает нижняя панель (выбор в Настройках / top_bar.py)."""
    try:
        import top_bar
        return top_bar.ws_place() == "bottom"
    except Exception:
        return False


WS_BOTTOM = _ws_bottom()


def _ws_here(connector):
    """Столы на панели этого монитора: общий выбор «в нижней панели» — или панели по
    мониторам, и верхний бар на этом мониторе выключен (иначе столов там не видно вовсе;
    panels.py, 06.10.2026)."""
    try:
        import panels
        d = panels.load()
        if panels.per_monitor(d):
            return panels.ws_for(connector, d) == "bottom"    # у монитора свой выбор
    except Exception:
        pass
    return WS_BOTTOM


def spawn(*args):
    subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


class NiriState:
    """Окна, столы и раскладка — по потоку событий niri, без опроса."""

    def __init__(self, on_change):
        self.windows, self.workspaces = {}, {}
        self.layouts, self.layout_idx = [], 0
        self.on_change = on_change
        threading.Thread(target=self.listen, daemon=True).start()

    def listen(self):
        while True:
            try:
                p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True,
                                     preexec_fn=_die_with_parent)
                for line in p.stdout:
                    try:
                        ev = json.loads(line)
                    except ValueError:
                        continue
                    GLib.idle_add(self.apply, ev)
                p.wait()
            except OSError:
                pass
            time.sleep(2)

    def apply(self, ev):
        kind = next(iter(ev), None)
        d = ev.get(kind) or {}
        if kind == "WorkspacesChanged":
            self.workspaces = {w["id"]: w for w in d["workspaces"]}
        elif kind == "WorkspaceActivated":
            ws = self.workspaces.get(d["id"])
            if ws:
                for w in self.workspaces.values():
                    if w.get("output") == ws.get("output"):
                        w["is_active"] = False
                    if d.get("focused"):
                        w["is_focused"] = False
                ws["is_active"] = True
                if d.get("focused"):
                    ws["is_focused"] = True
        elif kind == "WorkspaceActiveWindowChanged":
            ws = self.workspaces.get(d["workspace_id"])
            if ws:
                ws["active_window_id"] = d.get("active_window_id")
        elif kind == "WindowsChanged":
            self.windows = {w["id"]: w for w in d["windows"]}
        elif kind == "WindowOpenedOrChanged":
            w = d["window"]
            if w.get("is_focused"):
                for o in self.windows.values():
                    o["is_focused"] = False
            self.windows[w["id"]] = w
        elif kind == "WindowClosed":
            self.windows.pop(d["id"], None)
        elif kind == "WindowFocusChanged":
            for o in self.windows.values():
                o["is_focused"] = o["id"] == d.get("id")
        elif kind == "WindowUrgencyChanged":
            w = self.windows.get(d["id"])
            if w:
                w["is_urgent"] = d.get("urgent")
        elif kind == "WindowLayoutsChanged":
            for wid, lay in d.get("changes", []):
                if wid in self.windows:
                    self.windows[wid]["layout"] = lay
        elif kind == "KeyboardLayoutsChanged":
            kl = d.get("keyboard_layouts") or {}
            self.layouts, self.layout_idx = kl.get("names", []), kl.get("current_idx", 0)
        elif kind == "KeyboardLayoutSwitched":
            self.layout_idx = d.get("idx", 0)
        else:
            return False
        self.on_change(kind)
        return False

    def windows_on(self, output):
        act = {w["id"] for w in self.workspaces.values()
               if w.get("is_active") and w.get("output") == output}
        wins = [w for w in self.windows.values() if w.get("workspace_id") in act
                and not (w.get("app_id") or "").startswith(HIDDEN_APPS)]

        def key(w):
            pos = ((w.get("layout") or {}).get("pos_in_scrolling_layout")) or [9999, 0]
            return (bool(w.get("is_floating")), pos[0], pos[1], w["id"])
        return sorted(wins, key=key)


def niri_gaps():
    try:
        m = re.search(r"^\s*gaps\s+(\d+)", open(LAYOUT_KDL).read(), re.M)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def niri_border():
    try:
        txt = open(LAYOUT_KDL).read()
        blk = re.search(r"^\s*border\s*\{(.*?)\}", txt, re.M | re.S)
        if not blk or re.search(r"^\s*off\s*$", blk.group(1), re.M):
            return 0
        m = re.search(r"^\s*width\s+(\d+)", blk.group(1), re.M)
        return int(m.group(1)) if m else 0
    except OSError:
        return 0


def zone_size():
    """Сколько места отнять у окон снизу. С зазором — вся высота панели (niri
    добавит свой обычный зазор gaps). Вплотную — меньше на этот зазор: низ окон
    ложится ровно на верх панели (01.10.2026, выбор в Настройках)."""
    try:
        glued = open(GAP_FILE).read().strip() == "off"
    except OSError:
        glued = False
    # «Вплотную» — нижняя рамка окон уходит ПОД панель (панель лежит слоем выше):
    # у окон толстые рамки (5 px), и рамка на кромке панели сливалась в тяжёлую
    # линию; зазор в 1 px тоже не понравился — Просьба: «попробуй убрать нижнюю
    # рамку, если панель видна» (01.10.2026). Спрятана панель — зоны нет, окна как
    # обычно, с рамкой со всех сторон.
    # Но край окна должен читаться: из рамки над панелью видно GLUE_SHOW px
    # («я всё равно должен видеть, где кончается граница, — на чуть-чуть»).
    return max(1, H - niri_gaps() - max(0, niri_border() - GLUE_SHOW)) if glued else H


# ── значки программ ────────────────────────────────────────────────────────

_app_cache = {}


def app_icon(app_id):
    """Gio.Icon программы по app_id окна — через .desktop, как в доке."""
    if app_id in _app_cache:
        return _app_cache[app_id]
    info = None
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            break
    if not info:
        for a in Gio.AppInfo.get_all():
            if isinstance(a, Gio.DesktopAppInfo) and \
                    (a.get_startup_wm_class() or "").lower() == app_id.lower():
                info = a
                break
    icon = info.get_icon() if info else None
    if icon is None:
        icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower() or "application-x-executable")
    _app_cache[app_id] = icon
    return icon


# ── логотип на «Пуске» ────────────────────────────────────────────────────

def pil_surface(im):
    buf = io.BytesIO()
    im.save(buf, "PNG")
    buf.seek(0)
    return cairo.ImageSurface.create_from_png(buf)


class Wordmark(Gtk.DrawingArea):
    """Надпись static_ с «Пуска» — пиксельный логотип пользователя
    (~/Pictures/logo/static-logo), перекрашенный в гамму обоев; курсор «_»
    мигает, как в терминале, пока панель видна. Вместо простой надписи
    шрифтом (01.10.2026: «static в пуске слишком простой»)."""

    CURSOR = (111, 123)          # столбцы курсора в static-wordmark-native.png
    BLINK_MS = 530

    def __init__(self):
        super().__init__()
        self.on, self.timer = True, None
        self.full = self.bare = None
        self.load()
        self.connect("draw", self.on_draw)

    def load(self):
        try:
            im = Image.open(WORDMARK).convert("RGBA")
        except OSError:
            self.full = None
            self.set_size_request(0, 0)
            return
        im = pixel_recolor.recolor(im, pixel_recolor.target_hue(), pixel_recolor.cool_select,
                                   ref=pixel_recolor.hex_hue("#6c8cff"))
        bare = im.copy()
        px = bare.load()
        for x in range(*self.CURSOR):
            for y in range(bare.height):
                px[x, y] = (0, 0, 0, 0)
        self.full, self.bare = pil_surface(im), pil_surface(bare)
        self.set_size_request(im.width, im.height)
        self.queue_draw()

    def play(self, on):
        if on and not self.timer and self.full:
            self.timer = GLib.timeout_add(self.BLINK_MS, self.blink)
        elif not on and self.timer:
            GLib.source_remove(self.timer)
            self.timer = None
            self.on = True
            self.queue_draw()

    def blink(self):
        self.on = not self.on
        self.queue_draw()
        return True

    def on_draw(self, w, cr):
        surf = self.full if self.on else self.bare
        if surf:
            cr.translate(0, (w.get_allocated_height() - surf.get_height()) // 2)
            cr.set_source_surface(surf, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
        return True


def mix_rgb(a, b, t):
    return [x + (y - x) * t for x, y in zip(a, b)]


class LangBadge(Gtk.DrawingArea):
    """Индикатор раскладки как в трее Windows XP (05.10.2026): гладкий квадратик со
    скруглёнными углами тонами «Пуска», светлая кромка, белые буквы обычным жирным
    шрифтом (у XP — Tahoma 8 pt). Пиксельный вариант пользователь отверг: «через чур пиксельно»;
    пиксельный шрифт системы чёткий только на 8/16 px — то мелко, то крупно."""
    FONT = "Noto Sans Bold 10px"
    H = 16
    # Второй вид (06.10.2026, пользователь показал образец): тёмная плашка, пиксельная клавиатура
    # с цветными рядами клавиш и «RU»/«EN» пиксельными буквами; цвета — палитра обоев.
    # Выбор — state/xpbar-lang-look: xp | keyboard (Настройки → Нижняя панель).
    LOOK_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-lang-look")
    KBD = ("FFFFFFFFFFFF", "F1111111111F", "F2222222222F", "F..333333..F", "FFFFFFFFFFFF")
    LETTERS = {
        "A": ("010", "101", "111", "101", "101"), "E": ("111", "100", "110", "100", "111"),
        "K": ("101", "101", "110", "101", "101"), "N": ("101", "111", "111", "101", "101"),
        "R": ("110", "101", "110", "101", "101"), "U": ("101", "101", "101", "101", "111"),
        "Z": ("111", "001", "010", "100", "111"), "?": ("110", "001", "010", "000", "010"),
    }

    def __init__(self, text="EN"):
        super().__init__()
        self.text = text
        self.look = self.read_look()
        self.connect("draw", self.on_draw)
        self.resize_for()
        GLib.timeout_add_seconds(2, self.check_look)       # смена в Настройках — сразу

    def read_look(self):
        try:
            return "keyboard" if open(self.LOOK_FILE).read().strip() == "keyboard" else "xp"
        except OSError:
            return "xp"

    def check_look(self):
        lk = self.read_look()
        if lk != self.look:
            self.look = lk
            self.resize_for()
            self.queue_draw()
        return True

    def text_size(self):
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        cr = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 4, 4))
        lay = PangoCairo.create_layout(cr)
        lay.set_font_description(Pango.FontDescription(self.FONT))
        lay.set_text(self.text, -1)
        return lay, lay.get_pixel_size()

    def resize_for(self):
        if getattr(self, "look", "xp") == "keyboard":
            self.set_size_request(5 + len(self.KBD[0]) * 2 + 5 + len(self.text) * 6 + 6, 22)
            return
        _lay, (tw, _th) = self.text_size()
        self.set_size_request(tw + 10, self.H + 4)

    def set_text(self, t):
        t = (t or "?").upper()[:3]
        if t != self.text:
            self.text = t
            self.resize_for()
            self.queue_draw()

    def get_text(self):
        return self.text

    def draw_keyboard(self, cr):
        import math
        c = colors()

        def rgb(key, d="#5f74b4"):
            v = c.get(key, d)
            return [int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        a = self.get_allocation()
        w, h = a.width, a.height
        bh = 20
        x0, y0, bw, r = 0.5, (h - bh) / 2 + 0.5, w - 1, 3
        cr.new_sub_path()
        cr.arc(x0 + bw - r, y0 + r, r, -math.pi / 2, 0)
        cr.arc(x0 + bw - r, y0 + bh - 1 - r, r, 0, math.pi / 2)
        cr.arc(x0 + r, y0 + bh - 1 - r, r, math.pi / 2, math.pi)
        cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()
        cr.set_source_rgb(*mix_rgb(rgb("st_dark", "#02081b"), rgb("surface", "#10131c"), 0.5))
        cr.fill_preserve()
        cr.set_source_rgb(*rgb("surface_high", "#272a34"))
        cr.set_line_width(1)
        cr.stroke()
        k = 2
        try:
            vv = open(os.path.expanduser("~/.cache/matugen/vivid.txt")).read().strip()
            vivid = [int(vv[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        except (OSError, ValueError):
            vivid = rgb("primary", "#b4c5ff")
        cols = {"F": mix_rgb(rgb("on_surface_variant", "#c4c6d3"), rgb("surface", "#10131c"), 0.25),
                "1": vivid, "2": rgb("tertiary", "#d2bdf6"), "3": rgb("on_surface", "#e1e1ef")}
        ix, iy = 5, int(y0 + (bh - len(self.KBD) * k) / 2)
        for j, row in enumerate(self.KBD):
            for i, ch in enumerate(row):
                if ch in cols:
                    cr.set_source_rgb(*cols[ch])
                    cr.rectangle(ix + i * k, iy + j * k, k, k)
                    cr.fill()
        # буквы — пиксельный шрифт системы в родном кегле 8 px, без сглаживания (чётко)
        from gi.repository import Pango, PangoCairo
        lay = PangoCairo.create_layout(cr)
        fo = cairo.FontOptions()
        fo.set_antialias(cairo.ANTIALIAS_NONE)
        PangoCairo.context_set_font_options(lay.get_context(), fo)
        lay.set_font_description(Pango.FontDescription("PxPlus HP 100LX 6x8 8px"))
        lay.set_text(self.text, -1)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgb(*rgb("on_surface", "#e1e1ef"))
        cr.move_to(ix + len(self.KBD[0]) * k + 5, int(y0 + (bh - th) / 2))
        PangoCairo.show_layout(cr, lay)
        return True

    def on_draw(self, _w, cr):
        if self.look == "keyboard":
            return self.draw_keyboard(cr)
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        import math
        c = colors()

        def rgb(key, d="#5f74b4"):
            v = c.get(key, d)
            return [int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        a = self.get_allocation()
        w, h = a.width, a.height
        x0, y0, bw, bh, r = 1.5, (h - self.H) / 2 + 0.5, w - 3, self.H - 1, 3

        def rounded():
            cr.new_sub_path()
            cr.arc(x0 + bw - r, y0 + r, r, -math.pi / 2, 0)
            cr.arc(x0 + bw - r, y0 + bh - r, r, 0, math.pi / 2)
            cr.arc(x0 + r, y0 + bh - r, r, math.pi / 2, math.pi)
            cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
        g = cairo.LinearGradient(0, y0, 0, y0 + bh)
        g.add_color_stop_rgb(0, *rgb("st_top"))
        g.add_color_stop_rgb(1, *rgb("st_bot"))
        rounded()
        cr.set_source(g)
        cr.fill_preserve()
        cr.set_source_rgba(*rgb("st_hi", "#9fb4f5"), 0.9)
        cr.set_line_width(1)
        cr.stroke()
        lay = PangoCairo.create_layout(cr)
        fo = cairo.FontOptions()
        fo.set_antialias(cairo.ANTIALIAS_GRAY)
        fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
        PangoCairo.context_set_font_options(lay.get_context(), fo)
        lay.set_font_description(Pango.FontDescription(self.FONT))
        lay.set_text(self.text, -1)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgba(0, 0, 0, 0.35)                 # лёгкая тень букв, как в XP
        cr.move_to(round((w - tw) / 2) + 1, round((h - th) / 2) + 1)
        PangoCairo.show_layout(cr, lay)
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(round((w - tw) / 2), round((h - th) / 2))
        PangoCairo.show_layout(cr, lay)
        return True


class Sparkle(Gtk.DrawingArea):
    """Пиксельная четырёхлучевая искорка цветом акцента с мягким свечением (кнопка «Пуск»
    вида «Квадратный»); small — крошечный «+» у надписи, как на образце angelOS."""

    def __init__(self, w, h, small=False):
        super().__init__()
        self.small = small
        self.set_size_request(w, h)
        self.connect("draw", self.on_draw)

    def on_draw(self, _w, cr):
        c = colors()
        acc = [int(c["st_hi"][i:i + 2], 16) / 255 for i in (1, 3, 5)]
        btn = self.get_ancestor(Gtk.Button)
        if btn is not None and btn.get_style_context().has_class("open"):
            acc = [min(1.0, v * 1.15 + 0.08) for v in acc]   # меню открыто: искорка чуть ярче
        hi = [min(1, v * 0.4 + 0.6) for v in acc]               # ядро — почти белое
        a = self.get_allocation()
        if self.small:                                          # «+» 5×5 вверху
            x, y = 1, a.height // 2 - 9
            cr.set_source_rgb(*acc)
            cr.rectangle(x + 2, y, 1, 5)
            cr.rectangle(x, y + 2, 5, 1)
            cr.fill()
            return True
        cx, cy = a.width // 2, a.height // 2
        cr.set_source_rgba(*acc, 0.22)                          # свечение
        cr.rectangle(cx - 5, cy - 5, 11, 11)
        cr.fill()
        cr.set_source_rgba(*acc, 0.12)
        cr.rectangle(cx - 7, cy - 2, 15, 5)
        cr.rectangle(cx - 2, cy - 7, 5, 15)
        cr.fill()
        cr.set_source_rgb(*acc)                                 # лучи
        cr.rectangle(cx, cy - 8, 1, 17)
        cr.rectangle(cx - 8, cy, 17, 1)
        cr.rectangle(cx - 1, cy - 3, 3, 7)
        cr.rectangle(cx - 3, cy - 1, 7, 3)
        cr.fill()
        cr.set_source_rgb(*hi)                                  # ядро
        cr.rectangle(cx - 1, cy - 1, 3, 3)
        cr.fill()
        cr.set_source_rgba(*acc, 0.7)                           # пара крошечных искр рядом
        cr.rectangle(cx - 8, cy - 8, 2, 2)
        cr.rectangle(cx + 7, cy + 7, 2, 2)
        cr.fill()
        return True


class Logo(Gtk.DrawingArea):
    """Живой спрайт (если выбран) или телевизор static в цветах палитры."""

    def __init__(self):
        super().__init__()
        self.frames, self.delays, self.i = [], [], 0
        self.timer = None
        self.scale = 2
        self.load()
        self.connect("draw", self.on_draw)

    def load(self):
        self.frames, self.delays = [], []
        try:
            info = json.load(open(os.path.join(SPRITE_DIR, "info.json")))
            names = sorted(f for f in os.listdir(os.path.join(SPRITE_DIR, "frames"))
                           if f.endswith(".png"))
            hue = pixel_recolor.target_hue()
            for n in names:
                im = Image.open(os.path.join(SPRITE_DIR, "frames", n))
                # Мику в гамме обоев: бирюза и холодный серый — в оттенок акцента,
                # кожа и ленты как были (01.10.2026, просьба пользователя).
                im = pixel_recolor.recolor(im, hue, pixel_recolor.miku_select,
                                           ref=pixel_recolor.MIKU_REF)
                self.frames.append(pil_surface(im))
            ms = info.get("frame_ms") or 150
            self.delays = ms if isinstance(ms, list) else [ms] * len(self.frames)
            if len(self.delays) < len(self.frames):
                self.delays += [self.delays[-1] if self.delays else 150] * \
                    (len(self.frames) - len(self.delays))
        except (OSError, ValueError, cairo.Error, ImportError):
            self.frames = []
        if self.frames:
            h = max(f.get_height() for f in self.frames)
            w = max(f.get_width() for f in self.frames)
            self.scale = max(1, 26 // h) if h <= 26 else 26 / h
            self.set_size_request(math.ceil(w * self.scale), 26)
        else:
            self.scale = 2
            self.set_size_request(len(TV[0]) * 2, 26)
        self.i = 0
        self.queue_draw()

    def play(self, on):
        if on and self.frames and len(self.frames) > 1 and not self.timer:
            self.timer = GLib.timeout_add(self.delays[self.i], self.next)
        elif not on and self.timer:
            GLib.source_remove(self.timer)
            self.timer = None

    def next(self):
        self.i = (self.i + 1) % len(self.frames)
        self.queue_draw()
        self.timer = GLib.timeout_add(max(40, int(self.delays[self.i])), self.next)
        return False

    def on_draw(self, w, cr):
        ww, hh = w.get_allocated_width(), w.get_allocated_height()
        if self.frames:
            f = self.frames[self.i]
            fw, fh = f.get_width() * self.scale, f.get_height() * self.scale
            cr.translate((ww - fw) // 2, (hh - fh) // 2)
            cr.scale(self.scale, self.scale)
            cr.set_source_surface(f, 0, 0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            return True
        c = colors()
        p = c["primary"]
        pal = {"O": mix(c["base"], "#000000", 0.55), "H": mix(p, "#ffffff", 0.45), "B": p,
               "D": mix(p, c["base"], 0.45), "S": mix(c["base"], "#000000", 0.6),
               "W": mix(p, "#ffffff", 0.85), "N": mix(c["base"], p, 0.35), "K": mix(p, "#ffffff", 0.45),
               "R": c["error"]}
        s = self.scale
        x0 = (ww - len(TV[0]) * s) // 2
        y0 = (hh - len(TV) * s) // 2
        for y, row in enumerate(TV):
            for x, ch in enumerate(row):
                if ch == ".":
                    continue
                cr.set_source_rgb(*hex2rgb(pal[ch]))
                cr.rectangle(x0 + x * s, y0 + y * s, s, s)
                cr.fill()
        return True


class Grip(Gtk.DrawingArea):
    """«Ручка» панели XP: столбик точек с тенью."""

    def __init__(self):
        super().__init__()
        self.set_size_request(8, -1)
        self.connect("draw", self.on_draw)

    def on_draw(self, w, cr):
        c = colors()
        hh = w.get_allocated_height()
        for y in range(7, hh - 6, 4):
            cr.set_source_rgb(*hex2rgb(c["tr_dark"]))
            cr.rectangle(4, y + 1, 2, 2)
            cr.fill()
            cr.set_source_rgb(*hex2rgb(c["line1"]))
            cr.rectangle(3, y, 2, 2)
            cr.fill()
        return True


# ── текст песни ────────────────────────────────────────────────────────────

class Lyrics(LB.App):
    """Та же логика, что у lyrics_bar.py (плееры по D-Bus, lrclib, кэш), но вывод
    в виджеты панели и строка — на PREVIEW с раньше пения."""

    def __init__(self, sink):
        self.sink = sink
        super().__init__()

    def write_status(self):
        pass                      # файл состояния ведёт модуль бара, не мы

    def emit(self, obj):
        s = json.dumps(obj, ensure_ascii=False, default=str)
        if s != self.last_out:
            self.last_out = s
            self.sink(obj)

    def step(self):
        p = None if self.off else self.active()
        if not p:
            self.emit({"text": ""})
            return None
        # Пауза дольше PAUSE_HIDE_S — текст убрать (01.10.2026, просьба пользователя):
        # строка песни, которая давно не играет, только занимает место.
        if p.status != "Playing":
            key = p.track_key()
            # Песню на паузе показываем, только если панель видела, как она играла:
            # иначе каждый перезапуск панели выводил на 30 с текст давно остановленного
            # трека (06.10.2026, Просьба: «показывать, только когда трек включён»).
            if getattr(self, "played_key", None) != key:
                self.emit({"text": ""})
                return None
            if getattr(self, "pause_key", None) != key:
                self.pause_key, self.pause_t = key, time.monotonic()
            left = PAUSE_HIDE_S - (time.monotonic() - self.pause_t)
            if left <= 0:
                self.emit({"text": ""})
                return None
        else:
            self.pause_key, left = None, None
            self.played_key = p.track_key()
        lines = self.want_lyrics(p)
        if not lines or not any(t for _, t in lines):
            self.emit({"text": ""})
            return None
        pos = p.position() + LB.LEAD
        i = LB.line_index(lines, pos + PREVIEW)
        art = str(p.meta.get("mpris:artUrl") or "")
        nxt_line = lines[i + 1][0] - PREVIEW if i + 1 < len(lines) else None
        if i < 0 or not lines[i][1]:
            text, nxt_t = None, nxt_line
        else:
            start, dur, line_end = LB.line_timing(lines, i, p.length)
            elapsed = pos - start
            if elapsed < 0:
                done, nw = 0, start          # строка показана заранее, петь ещё не начали
            else:
                done = LB.sung_chars(lines[i][1], elapsed, dur)
                nw = LB.next_word_time(lines[i][1], start, elapsed, dur)
            text = LB.render(lines[i][1], done, self.accent, getattr(lines, "approx", False))
            cands = [t for t in (nw, nxt_line, line_end) if t is not None and t > pos]
            nxt_t = min(cands) if cands else None
        self.emit({"text": text, "gap": text is None, "art": art,
                   "tip": LB.tooltip(lines, i, p.artist, p.title) + (
                       "\n<i>≈ время примерное: у трека нет текста с таймингами</i>"
                       if getattr(lines, "approx", False) else ""),
                   "paused": p.status != "Playing"})
        if p.status != "Playing":
            return max(0.5, left + 0.1)        # проснуться, когда пауза перевалит за предел
        if nxt_t is None:
            return None
        return max(0.05, (nxt_t - pos) / (p.rate or 1.0) + 0.01)


def cover_path(url, done):
    """Путь к обложке (file:// сразу, http — скачать в фоне, как track_notify.py)."""
    if url.startswith("file://"):
        return urllib.request.url2pathname(url[7:])
    if not url.startswith("http"):
        return None
    path = os.path.join(COVERS, hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(path):
        return path

    def work():
        try:
            os.makedirs(COVERS, exist_ok=True)
            urllib.request.urlretrieve(url, path + ".part")
            os.replace(path + ".part", path)
            GLib.idle_add(done)
        except Exception:
            pass
    threading.Thread(target=work, daemon=True).start()
    return None


# ── трей ───────────────────────────────────────────────────────────────────

def short_layout(name):
    low = name.lower()
    for key, short in (("english", "EN"), ("russian", "RU"), ("kazakh", "KZ"), ("ukrainian", "UA")):
        if key in low:
            return short
    return (name[:2] or "??").upper()


# ── плашка системного трея (значки программ) ─────────────────────────────
# 01.10.2026, Просьба: «иконку, по нажатию на которую открывается маленькая плашка с
# треем (в стиле XP), компактно». Значки берём у того же наблюдателя, что и бар
# (org.kde.StatusNotifierWatcher): свойства значка — org.kde.StatusNotifierItem,
# меню — com.canonical.dbusmenu. ЛКМ — Activate, ПКМ — меню программы.
SNW = "org.kde.StatusNotifierWatcher"


class SniItem:
    def __init__(self, bus, ref):
        self.bus = bus
        if "/" in ref:
            self.dest, self.path = ref.split("/", 1)
            self.path = "/" + self.path
        else:
            self.dest, self.path = ref, "/StatusNotifierItem"
        self.props = {}
        try:
            r = bus.call_sync(self.dest, self.path, "org.freedesktop.DBus.Properties", "GetAll",
                              GLib.Variant("(s)", ("org.kde.StatusNotifierItem",)),
                              GLib.VariantType.new("(a{sv})"), Gio.DBusCallFlags.NONE, 400, None)
            self.props = r.unpack()[0]
        except GLib.Error:
            pass

    @property
    def title(self):
        return str(self.props.get("Title") or self.props.get("ToolTip", ("", [], "", ""))[2]
                   or self.props.get("Id") or self.dest)

    def pixbuf(self, px=20):
        name = str(self.props.get("IconName") or "")
        theme = Gtk.IconTheme.get_default()
        path = str(self.props.get("IconThemePath") or "")
        if path and path not in theme.get_search_path():
            theme.append_search_path(path)
        if name:
            try:
                if os.path.isabs(name) and os.path.exists(name):
                    return GdkPixbuf.Pixbuf.new_from_file_at_scale(name, px, px, True)
                if theme.has_icon(name):
                    return theme.load_icon(name, px, Gtk.IconLookupFlags.FORCE_SIZE)
            except GLib.Error:
                pass
        pm = self.props.get("IconPixmap") or []
        if pm:
            w, h, data = max(pm, key=lambda x: x[0])
            data = bytearray(data)
            for i in range(0, len(data) - 3, 4):      # ARGB (сетевой порядок) → RGBA
                a, r, g, b = data[i:i + 4]
                data[i:i + 4] = bytes((r, g, b, a))
            pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)), GdkPixbuf.Colorspace.RGB,
                                                 True, 8, w, h, w * 4)
            return pb.scale_simple(px, px, GdkPixbuf.InterpType.BILINEAR)
        try:
            return theme.load_icon("application-x-executable", px, Gtk.IconLookupFlags.FORCE_SIZE)
        except GLib.Error:
            return None

    def call(self, method, x=0, y=0):
        try:
            self.bus.call_sync(self.dest, self.path, "org.kde.StatusNotifierItem", method,
                               GLib.Variant("(ii)", (x, y)), None, Gio.DBusCallFlags.NONE, 600, None)
            return True
        except GLib.Error:
            return False

    def menu(self, on_done):
        """Gtk.Menu из dbusmenu программы или None."""
        mpath = self.props.get("Menu")
        if not mpath or mpath == "/":
            return None
        iface = "com.canonical.dbusmenu"
        try:
            try:
                self.bus.call_sync(self.dest, mpath, iface, "AboutToShow", GLib.Variant("(i)", (0,)),
                                   None, Gio.DBusCallFlags.NONE, 400, None)
            except GLib.Error:
                pass
            lay = self.bus.call_sync(self.dest, mpath, iface, "GetLayout",
                                     GLib.Variant("(iias)", (0, -1, [])), None,
                                     Gio.DBusCallFlags.NONE, 800, None).unpack()[1]
        except GLib.Error:
            return None

        def click(mid):
            try:
                self.bus.call_sync(self.dest, mpath, iface, "Event",
                                   GLib.Variant("(isvu)", (mid, "clicked", GLib.Variant("i", 0), 0)),
                                   None, Gio.DBusCallFlags.NONE, 600, None)
            except GLib.Error:
                pass
            on_done()

        def build(node):
            m = Gtk.Menu()
            for child in node[2]:
                cid, props, _kids = child
                if props.get("visible") is False:
                    continue
                if props.get("type") == "separator":
                    m.append(Gtk.SeparatorMenuItem())
                    continue
                label = str(props.get("label") or "").replace("_", "")
                if props.get("toggle-type"):
                    mi = Gtk.CheckMenuItem(label=label)
                    mi.set_active(props.get("toggle-state") == 1)
                else:
                    mi = Gtk.MenuItem(label=label)
                mi.set_sensitive(props.get("enabled") is not False)
                if props.get("children-display") == "submenu" and child[2]:
                    mi.set_submenu(build(child))
                else:
                    mi.connect("activate", lambda _m, i=cid: click(i))
                m.append(mi)
            return m
        return build(lay)


class TrayPlate(Gtk.Window):
    """Слой на весь экран (щелчок мимо закрывает) с коробочкой значков над треем."""

    def __init__(self, bar):
        super().__init__(title="XP tray")
        self.bar = bar
        self.get_style_context().add_class("xptray-win")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-xptray")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(self, bar.monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        bg = Gtk.EventBox()
        bg.set_visible_window(False)
        bg.connect("button-release-event", lambda *_a: self.close_plate() or True)
        self.add(bg)
        holder = Gtk.Box()
        holder.set_halign(Gtk.Align.START)      # место по X — в open_plate, над стрелкой
        holder.set_valign(Gtk.Align.END)
        holder.set_margin_bottom(H + 2)
        bg.add(holder)
        self.holder = holder
        catch = Gtk.EventBox()
        catch.connect("button-press-event", lambda *_a: True)
        catch.connect("button-release-event", lambda *_a: True)
        holder.add(catch)
        self.box = Gtk.FlowBox()
        self.box.get_style_context().add_class("xptray")
        self.box.set_selection_mode(Gtk.SelectionMode.NONE)
        self.box.set_max_children_per_line(6)
        self.box.set_min_children_per_line(1)
        self.box.set_homogeneous(True)
        catch.add(self.box)
        self.menu_open = False

    def fill(self):
        for c in self.box.get_children():
            c.destroy()
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        try:
            refs = bus.call_sync(SNW, "/StatusNotifierWatcher", "org.freedesktop.DBus.Properties", "Get",
                                 GLib.Variant("(ss)", (SNW, "RegisteredStatusNotifierItems")),
                                 GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NONE, 500, None).unpack()[0]
        except GLib.Error:
            refs = []
        n = 0
        for ref in refs:
            it = SniItem(bus, ref)
            if not it.props or str(it.props.get("Status") or "") == "Passive":
                continue
            b = Gtk.Button()
            b.get_style_context().add_class("xptray-item")
            b.set_relief(Gtk.ReliefStyle.NONE)
            img = Gtk.Image()
            pb = it.pixbuf(20)
            if pb:
                img.set_from_pixbuf(pb)
            b.add(img)
            b.set_tooltip_text(it.title)
            b.connect("button-release-event", self.on_item, it)
            self.box.add(b)
            n += 1
        if not n:
            lab = Gtk.Label(label="пусто")
            self.box.add(lab)
        # ряд — ровно по числу значков: FlowBox берёт ширину под max_children_per_line,
        # и при пяти программах справа оставалось пустое шестое место (06.10.2026)
        self.box.set_max_children_per_line(max(1, min(6, n)))
        self.box.show_all()

    def on_item(self, _w, e, it):
        if e.button == 1:
            if it.props.get("ItemIsMenu") or not it.call("Activate"):
                self.show_menu(it, e)
            else:
                self.close_plate()
        elif e.button == 2:
            it.call("SecondaryActivate")
            self.close_plate()
        elif e.button == 3:
            self.show_menu(it, e)
        return True

    def show_menu(self, it, e):
        m = it.menu(self.close_plate)
        if m is None:
            it.call("ContextMenu")
            self.close_plate()
            return
        m.show_all()
        m.attach_to_widget(self, None)
        m.popup_at_pointer(e)

    def place(self, width):
        """Поставить плашку серединой над стрелкой трея; у края экрана — прижать."""
        arrow = self.bar.tray.arrow_box
        pos = arrow.translate_coordinates(self.bar, arrow.get_allocated_width() / 2, 0)
        mon_w = self.bar.monitor.get_geometry().width if self.bar.monitor else self.bar.get_allocated_width()
        cx = pos[0] if pos else mon_w - width / 2
        m = int(max(4, min(mon_w - width - 4, cx - width / 2)))
        if os.environ.get("XPBAR_DEBUG"):
            print("xpbar tray place: pos=%r mon_w=%r width=%r -> margin %r" % (pos, mon_w, width, m),
                  file=sys.stderr, flush=True)
        if m != self.holder.get_margin_start():
            self.holder.set_margin_start(m)

    def open_plate(self):
        self.fill()
        # По центру над стрелкой (01.10.2026). Ширину мерить можно только у показанных
        # виджетов: у ни разу не показанной плашки она 0 — плашка вставала левым краем
        # к стрелке, вылезала за экран, и её бросало влево («то у Пуска, то левее»).
        # Поэтому: показать содержимое (не окно) → измерить → поставить → показать окно.
        # Пересчитывать в size-allocate НЕЛЬЗЯ: при повторном открытии окно-слой на миг
        # получает промежуточный размер, раскладка даёт ложную ширину (1779 вместо 212),
        # и плашка уезжала влево («первый раз над стрелкой, второй — опять слева»).
        self.get_child().show_all()
        # Отступ — в ноль ДО замера: get_preferred_width() включает margin_start, и на
        # втором открытии ширина выходила 212 + 1567 = 1779 → отступ 137 → плашка слева
        # (через раз: 212, 1779, 349, 1710… — замерено вживую).
        self.holder.set_margin_start(0)
        self.place(self.holder.get_preferred_width()[1])
        self.show()

    def close_plate(self):
        self.hide()
        return False

    def toggle(self):
        if self.get_visible():
            self.close_plate()
        else:
            self.open_plate()


class Tray(Gtk.Box):
    def __init__(self, bar):
        super().__init__(spacing=14)
        self.bar = bar
        self.get_style_context().add_class("tray")
        # «Скрытые значки», как в XP: стрелка открывает плашку трея программ
        self.plate = None
        arrow = Gtk.Label(label="\U000f0141")
        arrow.get_style_context().add_class("glyph")
        self.arrow_box = self.clickable(arrow, self.on_plate, tip="Значки программ (трей)")
        self.add(self.arrow_box)
        self.lay = LangBadge("EN")
        self.add(self.clickable(self.lay, self.on_layout, tip="Раскладка"))
        vb = Gtk.Box(spacing=5)
        # Микрофон вместо громкости (03.10.2026, пользователь): значок микрофона, щелчок —
        # выключить/включить микрофон, колёсико — его чувствительность, ПКМ — микшер.
        self.vol_g = Gtk.Label(label="\U000f036c")
        self.vol_g.get_style_context().add_class("glyph")
        self.vol_t = Gtk.Label(label="")
        vb.add(self.vol_g)
        vb.add(self.vol_t)
        self.vol_box = self.clickable(vb, self.on_vol, scroll=self.on_vol_scroll,
                                      tip="Микрофон / звук (СКМ — переключить вид)")
        self.add(self.vol_box)
        nb = Gtk.Box(spacing=4)
        self.bell = Gtk.Label(label="\U000f009a")
        self.bell.get_style_context().add_class("glyph")
        self.bell_n = Gtk.Label(label="")
        nb.add(self.bell)
        nb.add(self.bell_n)
        self.add(self.clickable(nb, self.on_bell,
                                tip="Уведомления: ЛКМ — «Не беспокоить» вкл/выкл, ПКМ — открыть"))
        self.clock = Gtk.Label(label="")
        self.clock.get_style_context().add_class("clock")
        self.clock_box = self.clickable(self.clock, self.on_clock)
        self.add(self.clock_box)

    def clickable(self, child, on_click, scroll=None, tip=None):
        eb = Gtk.EventBox()
        eb.add(child)
        eb.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        if on_click:
            eb.connect("button-release-event", lambda _w, e: on_click(e) or True)
        if scroll:
            eb.connect("scroll-event", lambda _w, e: scroll(e) or True)
        if tip:
            eb.set_tooltip_text(tip)
        return eb

    def on_plate(self, _e):
        if self.plate is None:
            self.plate = TrayPlate(self.bar)
        self.plate.toggle()

    def on_layout(self, _e):
        action("switch-layout", "next")

    def audio_view(self):
        """Что показывает значок у этой панели (05.10.2026, пользователь): два монитора — на
        ноутбуке микрофон, на MSI звук; один монитор — звук. СКМ меняет местами."""
        if len(BARS) >= 2:
            base = "mic" if self.bar.connector.startswith("eDP") else "sound"
        else:
            base = "sound"
        if os.path.exists(AUDIO_SWAP):
            base = "sound" if base == "mic" else "mic"
        return base

    def on_vol(self, e):
        view = self.audio_view()
        if e.button == 1:
            spawn("wpctl", "set-mute", AUDIO_DEV[view], "toggle")
        elif e.button == 2:                                  # СКМ — микрофон ↔ звук
            audio_flip()
            if AUDIO_REFRESH[0]:
                GLib.idle_add(AUDIO_REFRESH[0])
        elif e.button == 3:
            if view == "mic":
                spawn("pavucontrol", "-t", "4")             # вкладка устройств ввода
            else:
                # попап бара — над нижней панелью, отдельной плашкой (popup_theme.FROM_XPBAR)
                spawn("env", "JARVIS_POPUP_FROM=xpbar", sys.executable, os.path.join(HERE, "volume_popup.py"))

    def on_vol_scroll(self, e):
        d = e.direction
        if d == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = e.get_scroll_deltas()
            up = dy < 0
        else:
            up = d == Gdk.ScrollDirection.UP
        spawn("wpctl", "set-volume", "-l", "1.0", AUDIO_DEV[self.audio_view()], "5%+" if up else "5%-")

    def on_bell(self, e):
        # ЛКМ — «Не беспокоить» вкл/выкл, ПКМ — центр уведомлений (04.10.2026, пользователь).
        # swaync открывает центр на мониторе с ФОКУСОМ, а не там, где щёлкнули, —
        # поэтому сначала фокус на монитор этой панели.
        if e.button == 1:
            spawn("swaync-client", "-d", "-sw")
            return
        if e.button != 3:
            return
        # Фокус на монитор — только если он сейчас на другом: focus-monitor ставит курсор
        # в центр монитора (05.10.2026, Просьба: «курсор прыгает в центр, не трогай»).
        try:
            cur = json.loads(subprocess.run(["niri", "msg", "-j", "focused-output"],
                                            capture_output=True, text=True, timeout=1).stdout or "{}")
            if (cur or {}).get("name") != self.bar.connector:
                subprocess.run(["niri", "msg", "action", "focus-monitor", self.bar.connector],
                               capture_output=True, timeout=1)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        spawn("swaync-client", "-t", "-sw")

    def set_volume(self, vals):
        view = self.audio_view()
        pct, muted = vals.get(view, (None, False))
        if pct is None:
            return
        if view == "mic":
            g = "\U000f036d" if muted else "\U000f036c"       # микрофон выключен / включён
            tip = "Микрофон: ЛКМ — выкл/вкл, колёсико — чувствительность, ПКМ — микшер, СКМ — показать звук"
        else:
            g = "\U000f075f" if muted else ("\U000f057f", "\U000f0580", "\U000f057e")[min(2, pct * 3 // 101)]
            tip = "Звук: ЛКМ — выкл/вкл, колёсико — громкость, ПКМ — громкость и выход, СКМ — показать микрофон"
        self.vol_box.set_tooltip_text(tip)
        self.vol_g.set_text(g)
        self.vol_t.set_text("%d%%" % pct)
        for w in (self.vol_g, self.vol_t):
            (w.get_style_context().add_class if muted else w.get_style_context().remove_class)("off")

    def set_notif(self, count, dnd):
        self.bell.set_text("\U000f009b" if dnd else ("\U000f116b" if count else "\U000f009a"))
        self.bell_n.set_text(str(count) if count else "")
        (self.bell.get_style_context().add_class if dnd else self.bell.get_style_context().remove_class)("off")

    def on_clock(self, e):
        # ЛКМ — открыть календарь своей панели (xp_calendar.py; не calendar_popup.py —
        # тот принадлежит waybar наверху, 04.10.2026: случайно отдали его сюда же,
        # получилась путаница с «уши» и открытием не с той стороны). СКМ — время ↔
        # дата (01.10.2026). Два монитора: меняются местами, один: сам переключается.
        # Выбор помнится в state/xpbar-clock-swap.
        if e.button == 1:
            spawn(sys.executable, os.path.join(HERE, "xp_calendar.py"))
        elif e.button == 2:
            swap = not clock_swapped()
            try:
                if swap:
                    open(CLOCK_SWAP, "w").close()
                else:
                    os.remove(CLOCK_SWAP)
            except OSError:
                pass
            for b in BARS:
                b.tray.set_clock()

    def show_date(self):
        """По умолчанию: два монитора и больше — на ноутбуке (eDP) время, на
        остальных (MSI) дата; один монитор — время. СКМ переворачивает."""
        if len(BARS) >= 2:
            base = not self.bar.connector.startswith("eDP")
        else:
            base = False
        return base != clock_swapped()

    def set_clock(self):
        now = time.localtime()
        days_short = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
        if self.show_date():
            self.clock.set_text("%s %02d.%02d" % (days_short[now.tm_wday], now.tm_mday, now.tm_mon))
        else:
            self.clock.set_text(time.strftime("%H:%M", now))
        days = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
        months = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
                  "сентября", "октября", "ноября", "декабря")
        self.clock_box.set_tooltip_text("%s, %d %s %d" % (days[now.tm_wday], now.tm_mday,
                                                          months[now.tm_mon - 1], now.tm_year))


# ── сама панель ────────────────────────────────────────────────────────────

class TaskButton(Gtk.Button):
    def __init__(self, bar, wid):
        super().__init__()
        self.bar, self.wid = bar, wid
        self.get_style_context().add_class("task")
        self.set_size_request(TASK_W, -1)
        self.set_relief(Gtk.ReliefStyle.NONE)
        box = Gtk.Box(spacing=6)
        self.img = Gtk.Image()
        self.img.set_pixel_size(16)
        self.lbl = Gtk.Label(xalign=0)
        self.lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl.set_max_width_chars(1)        # ширину держит кнопка, а не текст
        box.pack_start(self.img, False, False, 0)
        box.pack_start(self.lbl, True, True, 0)
        self.add(box)
        self.app = self.title = None
        self.connect("button-release-event", self.on_release)

    def update(self, w):
        app = w.get("app_id") or ""
        if app != self.app:
            self.app = app
            self.img.set_from_gicon(app_icon(app), Gtk.IconSize.MENU)
            self.img.set_pixel_size(16)
        title = w.get("title") or app or "Окно"
        if title != self.title:
            self.title = title
            self.lbl.set_text(title)
            self.set_tooltip_text(title)
        ctx = self.get_style_context()
        for cls, on in (("focused", w.get("is_focused")), ("urgent", w.get("is_urgent"))):
            (ctx.add_class if on else ctx.remove_class)(cls)

    def on_release(self, _w, e):
        if e.button == 1:
            ui_click("click")
            action("focus-window", "--id", str(self.wid))
        elif e.button == 2:
            action("close-window", "--id", str(self.wid))
        elif e.button == 3:
            self.bar.task_menu(self.wid, e)
        return True


BARS = []
CLOCK_SWAP = os.path.expanduser("~/.config/hypr/state/xpbar-clock-swap")


def clock_swapped():
    return os.path.exists(CLOCK_SWAP)


# Значок звука в трее: что он показывает, решает каждая панель сама (Tray.audio_view):
# два монитора — ноутбук микрофон, MSI звук; один — звук; СКМ меняет местами.
# ЛКМ, колёсико и ПКМ действуют на то устройство, что показано.
AUDIO_SWAP = os.path.expanduser("~/.config/hypr/state/xpbar-audio-swap")   # СКМ поменял местами
AUDIO_DEV = {"mic": "@DEFAULT_AUDIO_SOURCE@", "sound": "@DEFAULT_AUDIO_SINK@"}
AUDIO_REFRESH = [None]          # main() кладёт сюда apply_volume — перечитать и перерисовать


def audio_flip():
    """СКМ по значку: поменять местами звук и микрофон на панелях (05.10.2026)."""
    try:
        if os.path.exists(AUDIO_SWAP):
            os.remove(AUDIO_SWAP)
        else:
            os.makedirs(os.path.dirname(AUDIO_SWAP), exist_ok=True)
            open(AUDIO_SWAP, "w").close()
    except OSError:
        pass

# ── меню «Пуск» внутри панели (01.10.2026) ────────────────────────────────
# Отдельным процессом меню открывалось ~0,4 с (питон + GTK + постройка). Здесь
# оно строится заранее (prewarm_menus, через пару секунд после старта) и только
# показывается/прячется — мгновенно. start_menu.py остался запасным путём.
MENUS = {}
MENU = {"prov": None, "opened": 0.0}


def _set_open(bar, on):
    ctx = bar.start.get_style_context()
    (ctx.add_class if on else ctx.remove_class)("open")
    if getattr(bar, "spark", None) is not None:
        bar.spark.queue_draw()


def menu_for(bar):
    import start_menu
    if MENU["prov"] is None:
        MENU["prov"] = start_menu.load_css()
    m = MENUS.get(bar.connector)
    if m is None:
        m = MENUS[bar.connector] = start_menu.StartMenu(
            bar.monitor, on_close=lambda b=bar: _set_open(b, False))
    return m


def ui_click(event):
    """Звук интерфейса (ui_sound.py решает сам, можно ли и какой набор)."""
    try:
        import ui_sound
        ui_sound.play(event)
    except Exception:
        pass


def toggle_menu(conn):
    bar = next((b for b in BARS if b.connector == conn), BARS[0] if BARS else None)
    if bar is None:
        return
    m = menu_for(bar)
    if m.get_visible():
        m.quit()
        return
    close_menus()
    _set_open(bar, True)
    MENU["opened"] = time.monotonic()
    m.open()
    ui_click("menu")


def close_menus():
    for m in MENUS.values():
        if m.get_visible():
            m.quit()


def reset_menus():
    """Смена обоев: меню — заново, в новых цветах (при следующем открытии)."""
    close_menus()
    for m in MENUS.values():
        m.destroy()
    MENUS.clear()
    if MENU["prov"] is not None:
        Gtk.StyleContext.remove_provider_for_screen(Gdk.Screen.get_default(), MENU["prov"])
        MENU["prov"] = None


def prewarm_menus():
    for b in BARS:
        try:
            menu_for(b)
        except Exception as e:
            print("xpbar: start menu: %r" % e, file=sys.stderr)
    return False
VISIBLE_FLAG = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-visible")


def update_visible_flag():
    """Флаг «панель на экране» для super_tap.py: одиночный Super открывает «Пуск»
    только когда панель видна."""
    on = any(getattr(b, "shown_now", False) for b in BARS)
    try:
        if on:
            # В файле — на сколько пикселей панель выступает над своей зоной
            # (режим «вплотную»: зона меньше высоты). Полноэкранные слои, которые
            # уважают зоны (выбор обоев), отступают на это снизу —
            # popup_theme.bottom_overlap().
            over = 0 if BARS and BARS[0].mode == "hover" else H - zone_size()
            with open(VISIBLE_FLAG, "w") as f:
                f.write("%d\n" % max(0, over))
        elif os.path.exists(VISIBLE_FLAG):
            os.remove(VISIBLE_FLAG)
    except OSError:
        pass


class XPBar(Gtk.Window):
    def __init__(self, monitor, connector, state, mode):
        super().__init__(title="XP bar")
        self.connector, self.state, self.mode = connector, state, mode
        self.ws_here = _ws_here(connector)
        self.monitor = monitor
        self.buttons = {}
        self.order = []
        self.menu_open = False
        self.hide_id = None
        self.get_style_context().add_class("xpbar-win")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-xpbar")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, zone_size() if mode == "always" else 0)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)

        outer = Gtk.EventBox()
        outer.set_above_child(False)
        outer.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        outer.connect("enter-notify-event", self.on_enter)
        outer.connect("leave-notify-event", self.on_leave)
        self.add(outer)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.add(col)
        self.rev = Gtk.Revealer()
        self.rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_UP)
        self.rev.set_transition_duration(180)
        self.rev.connect("notify::child-revealed", self.on_revealed)
        if mode == "hover":
            col.pack_start(self.rev, False, False, 0)
        else:
            # «Всегда» / «По кнопке»: окно всегда высотой с панель, панель — у его низа.
            # Пока она выезжает (Super+S), окно уже на экране и полной высоты: кадры
            # анимации идут, и окну не бывает нулевой высоты (06.10.2026, Просьба: «на
            # MSI она просто резко появляется», хотелось как при наведении).
            col.set_size_request(-1, H)
            self.rev.set_valign(Gtk.Align.END)
            col.pack_start(self.rev, True, True, 0)
        if mode == "hover":
            trig = Gtk.Box()
            trig.set_size_request(-1, 2)
            col.pack_start(trig, False, False, 0)

        bar = Gtk.Box()
        bar.get_style_context().add_class("xpbar")
        bar.set_size_request(-1, H)
        self.rev.add(bar)

        # «Пуск»
        self.start = Gtk.Button()
        self.start.get_style_context().add_class("start")
        self.start.set_relief(Gtk.ReliefStyle.NONE)
        sb = Gtk.Box(spacing=6)
        self.logo = Logo()
        sb.pack_start(self.logo, False, False, 0)
        # Надпись — простым текстом, как было: пиксельный static_ в гамме обоев с
        # мигающим курсором пользователь отверг («не должен двигаться, слишком большой,
        # расцветка не нравится», 01.10.2026). Класс Wordmark оставлен на потом.
        self.wordmark = Gtk.Label(label="static")
        sb.pack_start(self.wordmark, False, False, 0)
        # вид «Квадратный» (angelOS): искорка вместо логотипа, «staticOS» с ярким «OS» и
        # маленькая «+» сверху справа — как «angelOS⁺» на образце
        self.spark = Sparkle(20, 26)
        self.sq_label = Gtk.Label()
        self.plus = Sparkle(7, 26, small=True)
        sb.pack_start(self.spark, False, False, 0)
        sb.pack_start(self.sq_label, False, False, 0)
        sb.pack_start(self.plus, False, False, 0)
        self.start.add(sb)
        self.start.set_tooltip_text("Пуск")
        self.start.connect("button-release-event", self.on_start)
        bar.pack_start(self.start, False, False, 0)
        bar.pack_start(Grip(), False, False, 0)

        # столы — только когда их место внизу (top_bar.py ws bottom / верхний бар выключен)
        self.ws_buttons = {}
        self.ws_order = []
        self.wsbox = Gtk.Box(spacing=0)
        self.ws_ev = Gtk.EventBox()
        self.ws_ev.add(self.wsbox)
        self.ws_ev.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.ws_ev.connect("scroll-event", self.on_ws_scroll)
        self.ws_grip = Grip()
        bar.pack_start(self.ws_ev, False, False, 0)
        bar.pack_start(self.ws_grip, False, False, 0)

        # окна
        self.left = self.arrow("\U000f0141", -1)
        self.right = self.arrow("\U000f0142", +1)
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.EXTERNAL, Gtk.PolicyType.NEVER)
        self.sw.set_overlay_scrolling(True)
        self.sw.add_events(Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK)
        self.sw.connect("scroll-event", self.on_task_scroll)
        self.sw.connect("size-allocate", lambda *_a: GLib.idle_add(self.fit_buttons))
        self.btn_w = TASK_W
        self.tasks = Gtk.Box(spacing=0)
        self.sw.add(self.tasks)
        self.hadj = self.sw.get_hadjustment()
        self.hadj.connect("changed", lambda *_a: self.update_arrows())
        self.hadj.connect("value-changed", lambda *_a: self.update_arrows())
        tb = Gtk.Box()
        tb.pack_start(self.left, False, False, 0)
        tb.pack_start(self.sw, True, True, 0)
        tb.pack_start(self.right, False, False, 0)
        bar.pack_start(tb, True, True, 0)

        # текст песни — справа, у трея, постоянной ширины (01.10.2026: «сдвинь вправо,
        # задай ширину, чтобы панель не двигалась» — и окнам слева больше места).
        # Место держится и без песни — прячется только содержимое: иначе при каждом
        # появлении текста кнопки окон ужимались и ехали («не нравится, что из-за
        # текстов двигаются окна в нижней панели»).
        self.lyr = Gtk.EventBox()
        lb = Gtk.Box(spacing=8)
        self.cover = Gtk.Image()
        self.note = Gtk.Label(label="\U000f075a")
        self.note.get_style_context().add_class("note")
        self.lyr_lbl = Gtk.Label()
        self.lyr_lbl.get_style_context().add_class("lyrics")
        lb.pack_start(self.cover, False, False, 0)
        lb.pack_start(self.note, False, False, 0)
        lb.pack_start(self.lyr_lbl, True, True, 0)
        self.lyr_lbl.set_xalign(0)
        self.lyr_lbl.set_ellipsize(Pango.EllipsizeMode.END)
        # ширина — ровно LYR_W: без предела «естественная» ширина подписи = вся строка, и
        # длинная строка песни отжимала кнопки окон слева (05.10.2026). max_width_chars(1)
        # убирает эту просьбу о месте, текст обрезается «…» в своей рамке.
        self.lyr_lbl.set_max_width_chars(1)
        self.lyr.set_size_request(LYR_W, -1)
        lb.set_margin_start(12)
        lb.set_margin_end(12)
        self.lyr.add(lb)
        self.lyr_box = lb
        self.lyr.connect("button-release-event", lambda *_a: spawn("playerctl", "play-pause") or True)
        self.art_url = None

        self.tray = Tray(self)
        bar.pack_end(self.tray, False, False, 0)
        bar.pack_end(self.lyr, False, False, 0)

        if mode == "always":
            self.rev.set_transition_duration(0)
            self.rev.set_reveal_child(True)
        self.show_all()
        if mode == "button":
            self.hide()              # «по кнопке»: до первого Super+S панели нет
        self.apply_start_look()
        self.lyr_box.hide()   # место под текст остаётся — окна слева не сдвигаются
        self.left.hide()
        self.right.hide()
        if not self.ws_here:
            self.ws_ev.hide()
            self.ws_grip.hide()
        if os.environ.get("XPBAR_DEBUG"):
            GLib.timeout_add(2500, lambda: print("xpbar", connector, self.get_size(),
                                                 self.rev.get_child_revealed(),
                                                 bar.get_allocation().height, flush=True) and False)
        self.play(mode == "always")

    def apply_start_look(self):
        """Кнопка «Пуск»: обычная (логотип + static) или квадратная (искорка + staticOS⁺)."""
        sq = start_button_look() == "square"
        c = colors()
        self.sq_label.set_markup('static<span foreground="%s">OS</span>' % c["st_hi"])
        for w in (self.logo, self.wordmark):
            w.set_visible(not sq)
        for w in (self.spark, self.sq_label, self.plus):
            w.set_visible(sq)
            w.queue_draw()

    def play(self, on):
        self.logo.play(on)
        self.shown_now = on
        update_visible_flag()

    # ── Super+S (bottom_bar.py toggle → SIGUSR1) ─────────────────────────
    def set_shown(self, on):
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = None
        if self.mode == "hover":
            self.rev.set_transition_duration(180)
            self.rev.set_reveal_child(on)
        elif on:
            # «Всегда» / «По кнопке»: сперва окно на экран (панель в нём ещё свёрнута),
            # анимация — когда оно уже показано. 01.10.2026 анимация у ещё спрятанного
            # слоя застревала (кадры не шли) — поэтому через паузу, а не сразу.
            self.rev.set_transition_duration(0)
            self.rev.set_reveal_child(False)
            GtkLayerShell.set_exclusive_zone(self, zone_size())
            self.show()

            def slide_in():
                if self.get_visible() and not self.rev.get_reveal_child():
                    self.rev.set_transition_duration(180)
                    self.rev.set_reveal_child(True)
                return False
            GLib.timeout_add(40, slide_in)
        else:
            # уезжает вниз с анимацией; окно прячет on_revealed, когда она закончится
            GtkLayerShell.set_exclusive_zone(self, 0)
            self.rev.set_transition_duration(180)
            self.rev.set_reveal_child(False)
        self.play(on)

    def flush(self, on):
        """«При наведении»: пока панель показана, окно опущено на 2 px за край экрана —
        полоска-датчик под панелью уходит за край, и между панелью и краем не видно
        обоев (06.10.2026, Просьба: «маленький зазор, где виднеется часть обоев»)."""
        if self.mode == "hover":
            GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, -2 if on else 0)

    def toggle(self):
        if os.environ.get("XPBAR_DEBUG"):
            print("toggle", self.connector, "visible", self.get_visible(), "reveal",
                  self.rev.get_reveal_child(), "revealed", self.rev.get_child_revealed(), flush=True)
        self.set_shown(not self.rev.get_reveal_child())

    def arrow(self, glyph, direction):
        b = Gtk.Button(label=glyph)
        b.get_style_context().add_class("arrow")
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.connect("clicked", lambda _b: self.scroll_by(direction * self.btn_w * 2))
        return b

    # ── показ в режиме «при наведении» ────────────────────────────────────
    def on_enter(self, _w, e):
        if self.mode != "hover" or e.detail == Gdk.NotifyType.INFERIOR:
            return False
        if self.hide_id:
            GLib.source_remove(self.hide_id)
            self.hide_id = None
        if not self.rev.get_reveal_child():
            self.rev.set_reveal_child(True)
            self.play(True)
        return False

    def on_leave(self, _w, e):
        if self.mode != "hover" or e.detail == Gdk.NotifyType.INFERIOR or self.menu_open:
            return False
        if self.hide_id:
            GLib.source_remove(self.hide_id)
        self.hide_id = GLib.timeout_add(HIDE_MS, self.hide_now)
        return False

    def hide_now(self):
        self.hide_id = None
        if self.menu_open:
            return False
        self.rev.set_reveal_child(False)
        self.play(False)
        return False

    def on_revealed(self, *_a):
        # выехала целиком — опустить окно на 2 px (flush); раньше это делалось в момент
        # наведения: датчик уходил из-под курсора, панель ловила «мышь ушла» и выезжала
        # с задержкой (06.10.2026)
        if self.rev.get_child_revealed() and self.rev.get_reveal_child():
            self.flush(True)
        if not self.rev.get_child_revealed() and not self.rev.get_reveal_child():
            if self.mode == "hover":
                self.flush(False)   # датчик снова у края экрана
                self.resize(1, 1)   # обратно в полоску 2 px — щелчки по экрану не перехватываются
            else:
                self.hide()         # без полоски-ловушки окну нулевой высоты не место — прячем целиком

    # ── окна ──────────────────────────────────────────────────────────────
    # ── столы ─────────────────────────────────────────────────────────────
    def ws_list(self):
        """Столы этого монитора, как их показывает верхний бар: с окнами, активный, и
        столы с виджетами (метка U+2060); прочие пустые скрыты."""
        out = []
        for w in sorted((w for w in self.state.workspaces.values() if w.get("output") == self.connector),
                        key=lambda w: w.get("idx", 0)):
            name = w.get("name") or ""
            # стол с постоянным именем из конфига niri (дашборд, «карман») виден всегда: в
            # режиме Widget dashboard на дашборде нет окон, и он пропадал из панели (05.10.2026)
            fixed = bool(name) and "\u200b" not in name and "\u2060" not in name
            if w.get("active_window_id") is None and not w.get("is_active") and \
                    not name.startswith("\u2060") and not fixed:
                continue
            out.append(w)
        return out

    def refresh_ws(self):
        if not self.ws_here:
            return
        wss = self.ws_list()
        ids = [w["id"] for w in wss]
        for wid in list(self.ws_buttons):
            if wid not in ids:
                self.ws_buttons.pop(wid).destroy()
        for w in wss:
            b = self.ws_buttons.get(w["id"])
            if b is None:
                b = self.ws_buttons[w["id"]] = Gtk.Button()
                b.get_style_context().add_class("ws")
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.add(Gtk.Label())
                b.connect("clicked", lambda _b, i=w["id"]: self.focus_ws(i))
                self.wsbox.pack_start(b, False, False, 0)
                b.show_all()
            # подпись — имя без невидимых меток служб (значок) или номер стола
            label = (w.get("name") or "").replace("\u200b", "").replace("\u2060", "") or str(w.get("idx"))
            if b.get_child().get_text() != label:
                b.get_child().set_text(label)
            ctx = b.get_style_context()
            for cls, on in (("active", w.get("is_active")), ("focused", w.get("is_focused")),
                            ("empty", w.get("active_window_id") is None)):
                (ctx.add_class if on else ctx.remove_class)(cls)
        if ids != self.ws_order:
            self.ws_order = ids
            for i, wid in enumerate(ids):
                self.wsbox.reorder_child(self.ws_buttons[wid], i)

    def focus_ws(self, ws_id):
        ui_click("click")
        niri_request({"Action": {"FocusWorkspace": {"reference": {"Id": ws_id}}}})

    def on_ws_scroll(self, _w, e):
        """Колесо над столами — соседний стол этого монитора."""
        d = 0
        if e.direction == Gdk.ScrollDirection.UP:
            d = -1
        elif e.direction == Gdk.ScrollDirection.DOWN:
            d = 1
        elif e.direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = e.get_scroll_deltas()
            d = (1 if dy > 0 else -1) if ok and abs(dy) >= 0.5 else 0
        ids = self.ws_order
        cur = next((i for i, wid in enumerate(ids)
                    if (self.state.workspaces.get(wid) or {}).get("is_active")), None)
        if d and cur is not None and 0 <= cur + d < len(ids):
            niri_request({"Action": {"FocusWorkspace": {"reference": {"Id": ids[cur + d]}}}})
        return True

    def refresh(self):
        self.refresh_ws()
        wins = self.state.windows_on(self.connector)
        ids = [w["id"] for w in wins]
        for wid in list(self.buttons):
            if wid not in ids:
                self.buttons.pop(wid).destroy()
        focused = None
        for w in wins:
            b = self.buttons.get(w["id"])
            if b is None:
                b = self.buttons[w["id"]] = TaskButton(self, w["id"])
                self.tasks.pack_start(b, False, False, 0)
                b.show_all()
            b.update(w)
            if w.get("is_focused"):
                focused = b
        if ids != self.order:
            self.order = ids
            for i, wid in enumerate(ids):
                self.tasks.reorder_child(self.buttons[wid], i)
        self.fit_buttons()
        if focused:
            GLib.idle_add(self.reveal_button, focused)

    def fit_buttons(self):
        """Как в XP: окон много — кнопки ужимаются от TASK_W до TASK_MIN, и только
        когда и так не влезают, появляется прокрутка."""
        n = len(self.buttons)
        if not n:
            return False
        avail = self.sw.get_allocated_width()
        w = max(TASK_MIN, min(TASK_W, avail // n - 4))
        if w != self.btn_w:
            self.btn_w = w
            for b in self.buttons.values():
                b.set_size_request(w, -1)
        return False

    def reveal_button(self, b):
        a = b.get_allocation()
        v, page = self.hadj.get_value(), self.hadj.get_page_size()
        if a.x < v:
            self.hadj.set_value(a.x)
        elif a.x + a.width > v + page:
            self.hadj.set_value(a.x + a.width - page)
        return False

    def update_arrows(self):
        over = self.hadj.get_upper() > self.hadj.get_page_size() + 1
        v = self.hadj.get_value()
        self.left.set_visible(over)
        self.right.set_visible(over)
        self.left.set_sensitive(v > 0)
        self.right.set_sensitive(v < self.hadj.get_upper() - self.hadj.get_page_size() - 1)

    def scroll_by(self, dx):
        lo, hi = 0, max(0, self.hadj.get_upper() - self.hadj.get_page_size())
        self.hadj.set_value(max(lo, min(hi, self.hadj.get_value() + dx)))

    def on_task_scroll(self, _w, e):
        d = e.direction
        if d == Gdk.ScrollDirection.SMOOTH:
            _ok, dx, dy = e.get_scroll_deltas()
            self.scroll_by((dx + dy) * TASK_W / 2)
        elif d in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            self.scroll_by(-TASK_W)
        else:
            self.scroll_by(TASK_W)
        return True

    def task_menu(self, wid, e):
        m = Gtk.Menu()

        def item(label, *act):
            mi = Gtk.MenuItem(label=label)
            mi.connect("activate", lambda _m: action(*act))
            m.append(mi)
        w = self.state.windows.get(wid) or {}
        item("Перейти", "focus-window", "--id", str(wid))
        item("Во весь экран", "fullscreen-window", "--id", str(wid))
        item("В ленту" if w.get("is_floating") else "Плавающее", "toggle-window-floating",
             "--id", str(wid))
        m.append(Gtk.SeparatorMenuItem())
        item("Закрыть", "close-window", "--id", str(wid))
        self.popup(m, e)

    def popup(self, m, e):
        m.show_all()
        self.menu_open = True

        def closed(*_a):
            self.menu_open = False
            if self.mode == "hover":
                self.hide_id = GLib.timeout_add(HIDE_MS * 2, self.hide_now)
        m.connect("deactivate", closed)
        m.attach_to_widget(self, None)
        m.popup_at_pointer(e)

    def on_start(self, _w, e):
        if e.button == 1:
            # Меню «Пуск» в духе XP — живёт в этом же процессе, построено заранее.
            toggle_menu(self.connector)
        elif e.button == 3:
            m = Gtk.Menu()
            for label, cmd in (("Программы", [os.path.expanduser("~/.config/niri/scripts/shell-do"), "launcher"]),
                               ("Настройки", [sys.executable, os.path.join(HERE, "settings_app.py")]),
                               ("Экранное время", [sys.executable, os.path.join(HERE, "screentime.py")]),
                               ("Заблокировать", [os.path.join(HERE, "lockscreen")])):
                mi = Gtk.MenuItem(label=label)
                mi.connect("activate", lambda _m, c=cmd: spawn(*c))
                m.append(mi)
            self.popup(m, e)
        return True

    # ── текст песни ───────────────────────────────────────────────────────
    def set_lyrics(self, obj):
        if obj.get("text") is None and not obj.get("gap"):
            self.lyr_box.hide()
            self.lyr.set_tooltip_text(None)
            return
        if not obj.get("text") and not obj.get("gap"):
            self.lyr_box.hide()
            self.lyr.set_tooltip_text(None)
            return
        art = obj.get("art") or ""
        if art != self.art_url:
            self.art_url = art
            self.load_cover()
        if obj.get("gap"):
            self.lyr_lbl.set_markup('<span alpha="70%%">%s</span>' % html.escape(LB.GAP_TEXT))
        else:
            self.lyr_lbl.set_markup(obj["text"])
        self.lyr.set_tooltip_markup(obj.get("tip") or None)
        self.lyr.set_opacity(0.6 if obj.get("paused") else 1.0)
        self.lyr_box.show()

    def load_cover(self):
        path = cover_path(self.art_url or "", self.load_cover) if self.art_url else None
        pb = None
        if path:
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 22, 22, True)
            except GLib.Error:
                pb = None
        if pb:
            self.cover.set_from_pixbuf(pb)
            self.cover.show()
            self.note.hide()
        else:
            self.cover.hide()
            self.note.show()
        return False


def fit_lyrics():
    """Сколько знаков строки песни помещается в её место (LYR_W минус поля, обложка и
    промежуток) при шрифте подписи lyrics. Окно прокрутки строки (lyrics_bar.render) —
    ровно столько: было 40 при месте на ~34, хвост окна съедало «…», и строка не
    «ехала», а обрывалась (06.10.2026, пользователь)."""
    try:
        lbl = Gtk.Label()
        lbl.get_style_context().add_class("lyrics")
        lay = lbl.create_pango_layout("0" * 20)
        w = lay.get_pixel_size()[0] / 20.0
        room = LYR_W - 2 * 12 - 22 - 8 - 4         # поля lb, обложка 22, промежуток 8, запас
        if w > 0:
            LB.MAX_LEN = max(12, min(LYRICS_MAX, int(room // w)))
        if os.environ.get("XPBAR_DEBUG"):
            print("xpbar: знак %.1f px, место %d px → окно строки %d" % (w, room, LB.MAX_LEN), flush=True)
    except Exception as e:
        print("xpbar: ширина текста песни: %r" % e, file=sys.stderr)


def main():
    mode = "always"
    try:
        m = open(SHOW_FILE).read().strip()
        mode = m if m in ("always", "hover", "button") else "always"
    except OSError:
        pass
    load_css()
    fit_lyrics()
    display = Gdk.Display.get_default()
    outs = niri_json("outputs") or {}
    by_model = {(o.get("model") or ""): conn for conn, o in outs.items()}
    bars = []
    pending = {"id": None}

    def refresh_all():
        pending["id"] = None
        for b in bars:
            b.refresh()
        return False

    def on_change(kind):
        # Сменился стол или фокус окна — открытое меню «Пуск» закрыть (как в XP).
        if kind in ("WorkspaceActivated", "WindowFocusChanged") and \
                time.monotonic() - MENU["opened"] > 0.5:
            close_menus()
        if kind.startswith("Keyboard"):
            lay = short_layout(state.layouts[state.layout_idx]) if state.layouts else "??"
            for b in bars:
                b.tray.lay.set_text(lay)
            return
        if pending["id"] is None:
            pending["id"] = GLib.timeout_add(60, refresh_all)

    # Панели по мониторам (panels.py, 06.10.2026): у монитора свой режим — always / hover /
    # off (на нём панели нет). Переключатель «На всех мониторах» включён — общий mode.
    try:
        import panels
        pan = panels.load()
    except Exception as e:
        print("xpbar: panels: %r" % e, file=sys.stderr)
        panels = pan = None

    def mode_for(conn):
        if panels is None:
            return mode
        try:
            return panels.bottom_for(conn, pan) or mode
        except Exception:
            return mode

    state = NiriState(on_change)
    for i in range(display.get_n_monitors()):
        mon = display.get_monitor(i)
        conn = by_model.get(mon.get_model() or "", "") or (sorted(outs)[i] if i < len(outs) else "")
        if os.environ.get("XPBAR_DEBUG"):
            print("xpbar: монитор", i, mon.get_model(), "→", conn, "режим", mode_for(conn), flush=True)
        if mode_for(conn) in ("off", "dock"):         # dock — там док (dock.py), не XP
            continue
        bars.append(XPBar(mon, conn, state, mode_for(conn)))
        BARS.append(bars[-1])
    update_visible_flag()
    seen = {"lyrics": None, "notif": (0, False)}     # последнее показанное — для новой панели

    # текст песни
    def lyrics_sink(obj):
        seen["lyrics"] = obj
        for b in bars:
            b.set_lyrics(obj)
    try:
        Lyrics(lyrics_sink)
    except Exception as e:
        print("xpbar: lyrics: %r" % e, file=sys.stderr)

    # часы — на начало каждой минуты
    def tick_clock():
        for b in bars:
            b.tray.set_clock()
        GLib.timeout_add(int((60 - time.time() % 60) * 1000) + 50, tick_clock)
        return False
    tick_clock()

    # громкость — по событиям pactl
    def read_volume(dev):
        try:
            out = subprocess.run(["wpctl", "get-volume", dev], capture_output=True,
                                 text=True, timeout=2).stdout
            m = re.search(r"([\d.]+)", out)
            pct = round(float(m.group(1)) * 100) if m else None
            return pct, "MUTED" in out
        except (OSError, subprocess.SubprocessError, ValueError):
            return None, False

    vpend = {"id": None}

    def apply_volume():
        vpend["id"] = None
        vals = {k: read_volume(dev) for k, dev in AUDIO_DEV.items()}   # обе — у панелей разный вид
        for b in bars:
            b.tray.set_volume(vals)
        return False

    def schedule_volume():
        if vpend["id"] is None:
            vpend["id"] = GLib.timeout_add(80, apply_volume)
        return False

    def watch_volume():
        while True:
            try:
                p = subprocess.Popen(["pactl", "subscribe"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True,
                                     preexec_fn=_die_with_parent)
                for line in p.stdout:
                    if "'change' on source" in line or "'change' on sink" in line or "on server" in line:
                        GLib.idle_add(schedule_volume)
                p.wait()
            except OSError:
                pass
            time.sleep(3)
    AUDIO_REFRESH[0] = lambda: (apply_volume(), False)[1]
    apply_volume()
    threading.Thread(target=watch_volume, daemon=True).start()

    # уведомления — swaync-client -swb (строка JSON на каждое изменение)
    def watch_notif():
        while True:
            try:
                p = subprocess.Popen(["swaync-client", "-swb"], stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True,
                                     preexec_fn=_die_with_parent)
                for line in p.stdout:
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    cnt = int(d.get("text") or 0) if str(d.get("text") or "0").isdigit() else 0
                    dnd = "dnd" in str(d.get("alt") or d.get("class") or "")
                    seen["notif"] = (cnt, dnd)
                    GLib.idle_add(lambda c=cnt, n=dnd: [b.tray.set_notif(c, n) for b in bars] and False)
                p.wait()
            except OSError:
                pass
            time.sleep(3)
    threading.Thread(target=watch_notif, daemon=True).start()

    # раскладка — начальное значение (дальше по событиям niri)
    kl = niri_json("keyboard-layouts") or {}
    if kl.get("names"):
        state.layouts, state.layout_idx = kl["names"], kl.get("current_idx", 0)
        on_change("Keyboard")

    # Мониторы подключают и отключают (03.10.2026). Панели создавались один раз при
    # запуске: монитор выключился (пропал свет) и вернулся — на нём панели уже не было,
    # и Super+S не помогал («нижняя панель перестала отображаться на втором мониторе»).
    # Теперь список панелей сверяется с мониторами: лишние убираются, новым создаётся
    # панель в том же состоянии (видна/спрятана, громкость, раскладка, уведомления).
    def monitor_pairs():
        """[(монитор Gdk, имя выхода niri)] — по месту монитора на общем полотне."""
        now = niri_json("outputs") or {}
        res = []
        for i in range(display.get_n_monitors()):
            m = display.get_monitor(i)
            g = m.get_geometry()
            conn = next((c for c, o in now.items()
                         if (o.get("logical") or {}).get("x") == g.x
                         and (o.get("logical") or {}).get("y") == g.y), "")
            if not conn:
                conn = next((c for c, o in now.items() if (o.get("model") or "") == (m.get_model() or "")), "")
            if conn:
                res.append((m, conn))
        return res

    resync = {"id": None}

    def sync_bars():
        resync["id"] = None
        pairs = monitor_pairs()
        conns = {c for _m, c in pairs}
        mons = [m for m, _c in pairs]
        shown = any(getattr(b, "shown_now", False) for b in bars)
        for b in list(bars):
            if b.monitor not in mons or b.connector not in conns:
                m = MENUS.pop(b.connector, None)
                if m is not None:
                    m.destroy()
                bars.remove(b)
                if b in BARS:
                    BARS.remove(b)
                b.destroy()
        have = {b.connector for b in bars}
        for m, conn in pairs:
            if conn in have or mode_for(conn) in ("off", "dock"):
                continue
            try:
                b = XPBar(m, conn, state, mode_for(conn))
            except Exception as e:
                print("xpbar: новая панель %s: %r" % (conn, e), file=sys.stderr)
                continue
            bars.append(b)
            BARS.append(b)
            if mode == "button" and shown:
                b.set_shown(True)
            b.tray.set_clock()
            b.tray.set_notif(*seen["notif"])
            if state.layouts:
                b.tray.lay.set_text(short_layout(state.layouts[state.layout_idx]))
            if seen["lyrics"] is not None:
                b.set_lyrics(seen["lyrics"])
            GLib.timeout_add(2000, prewarm_menus)
        apply_volume()
        refresh_all()
        update_visible_flag()
        return False

    def monitors_changed(*_a):
        if resync["id"] is not None:
            GLib.source_remove(resync["id"])
        resync["id"] = GLib.timeout_add(900, sync_bars)
    display.connect("monitor-added", monitors_changed)
    display.connect("monitor-removed", monitors_changed)

    # смена обоев — новые цвета
    last = {"m": 0}
    try:
        last["m"] = os.stat(PALETTE_FILE).st_mtime
    except OSError:
        pass

    def check_palette():
        try:
            m = os.stat(PALETTE_FILE).st_mtime
        except OSError:
            return True
        if m != last["m"]:
            last["m"] = m
            load_css()
            for b in bars:
                b.logo.load()           # Мику — в новую гамму
                b.queue_draw()
            reset_menus()
        return True
    GLib.timeout_add_seconds(10, check_palette)

    # Меню «Пуск» открыто — кнопка нажата (флаг start-menu-open, в нём монитор).
    menu_flag = Gio.File.new_for_path(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"),
                                                   "start-menu-open"))

    def sync_start(*_a):
        try:
            conn = open(menu_flag.get_path()).read().strip()
        except OSError:
            conn = None
        for b in bars:
            ctx = b.start.get_style_context()
            (ctx.add_class if conn is not None and conn in ("", b.connector) else ctx.remove_class)("open")
    mon = menu_flag.monitor_file(Gio.FileMonitorFlags.NONE, None)
    mon.connect("changed", sync_start)
    sync_start()
    main.menu_monitor = mon          # держать ссылку, иначе монитор соберёт сборщик мусора

    # Вид «Пуска» сменили в Настройках (start_menu.py look|button …): кнопку —
    # перерисовать новым CSS, меню — пересоздать, как при смене обоев.
    # start_menu.py пишет через os.replace — в каталоге это переименование tmp → файл.
    def on_look(_m, f, o, ev):
        if ev not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED,
                      Gio.FileMonitorEvent.MOVED_IN, Gio.FileMonitorEvent.RENAMED,
                      Gio.FileMonitorEvent.DELETED):
            return
        paths = {x.get_path() for x in (f, o) if x is not None}
        if START_BUTTON_FILE in paths:
            load_css()
            for b in bars:
                b.apply_start_look()
                b.queue_draw()
        if START_LOOK_FILE in paths:
            reset_menus()
            GLib.timeout_add(500, prewarm_menus)     # готово к следующему открытию
    lm = Gio.File.new_for_path(os.path.dirname(START_BUTTON_FILE)).monitor_directory(
        Gio.FileMonitorFlags.WATCH_MOVES, None)
    lm.connect("changed", on_look)
    main.look_monitor = lm

    # SIGUSR2 — одиночный Super (super_tap.py): меню на мониторе в фокусе.
    def on_usr2():
        out = next((w.get("output") for w in state.workspaces.values() if w.get("is_focused")), "")
        toggle_menu(out)
        return True
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR2, on_usr2)

    # SIGWINCH — открыть/закрыть плашку трея на мониторе в фокусе (для проверок без мыши).
    def on_winch():
        out = next((w.get("output") for w in state.workspaces.values() if w.get("is_focused")), "")
        for b in bars:
            if b.connector == out:
                b.tray.on_plate(None)
        return True
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGWINCH, on_winch)
    GLib.timeout_add(2000, prewarm_menus)

    # SIGUSR1 — Super+S. Общий режим — все панели разом, как было. Панели по мониторам
    # (panels.py) — только панель монитора в фокусе: у соседа может быть другой режим, и
    # Super+S на MSI прятал его панель «всегда» и выдвигал «при наведении» на ноутбуке
    # (06.10.2026).
    def on_usr1():
        targets = bars
        if panels is not None and panels.per_monitor(pan):
            out = next((w.get("output") for w in state.workspaces.values() if w.get("is_focused")), "")
            targets = [b for b in bars if b.connector == out]
        for b in targets:
            b.toggle()
        return True
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, on_usr1)
    def bye():
        try:
            os.remove(VISIBLE_FLAG)
        except OSError:
            pass
        os._exit(0)
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, bye)
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGINT, lambda: os._exit(0) or False)
    Gtk.main()


if __name__ == "__main__":
    main()
