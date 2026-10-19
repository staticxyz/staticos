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
# reload (16.10.2026): панели по мониторам поменялись — работающая панель перечитывает
# panels.json по SIGHUP и пересоздаёт панель только того монитора, где выбор другой
# (раньше restart гасил и поднимал обе — дёргался и соседний монитор). Метка RELOAD_PID
# пишется, когда обработчик уже стоит: старой панели без него SIGHUP был бы смертелен.
RELOAD_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-reload.pid")
if sys.argv[1:2] == ["reload"]:
    pids = running_pids()
    try:
        rp = int(open(RELOAD_PID).read().strip())
    except (OSError, ValueError):
        rp = 0
    if pids == [rp]:
        os.kill(rp, signal.SIGHUP)
    else:
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
TASK_W = 136             # ширина кнопки окна — наибольшая (было 176; 05.10.2026, просьба: «чтобы больше вмещалось»)
TASK_MIN = 90            # окон много — кнопки сжимаются до этой ширины, дальше прокрутка (было 110)
GLUE_SHOW = 4            # «вплотную»: сколько пикселей нижней рамки окна видно над панелью (2 → 4, 04.10.2026: «рамки вообще не вижу»)
LYR_W = 470              # место под текст песни справа — постоянное, панель не пляшет
LYRICS_MAX = 40          # знаков строки песни в панели — предел; на деле fit_lyrics() по ширине
PREVIEW = 0.4            # строка появляется раньше, чем её начнут петь, с
                         # (0.8 — «переборщил со скоростью», 01.10.2026)
PAUSE_HIDE_S = 30        # текст песни прячется, если пауза дольше
HIDE_MS = 600            # режим «при наведении»: курсор ушёл — через столько спрятать
FONT = "'JetBrainsMono Nerd Font', 'JetBrainsMono NF', monospace"
# Подписи окон и трей — 12 px, как было до сведения к сетке (05.10.2026, просьба: «раньше было
# мельче», «эстетичность, но пиксельность»). Оригинальное имя шрифта (без «Jarvis»): правило
# fontconfig 62-pxplus-grid-trial (12 → 16) его не трогает.
FONT12 = "'JetBrainsMono Nerd Font', 'JetBrainsMono Nerd Font', monospace"
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
button.ws label.wsnote { font-size: 9px; margin-top: -3px; }   /* меньше и выше (19.10.2026) */
button.ws.plus label { font-size: 14px; }
/* Стол в фокусе — светлая плашка акцента, даже ПУСТОЙ (05.10.2026, просьба: «перешёл на
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
/* Раскладка — как индикатор языка в трее Windows XP (05.10.2026, просьба: «стали больше,
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
/* плашка-меню панели (BarPopup, 19.10.2026): компактно, 12 px, рамка как у трея */
.xptray.xppop { padding: 2px; box-shadow: 0 0 0 1px %(tr_dark)s; }
button.xppop-item {
    background: transparent; background-image: none; border: 1px solid transparent;
    box-shadow: none; padding: 0 6px; margin: 0; min-width: 0; min-height: 0; border-radius: 2px;
}
button.xppop-item label { font-family: %(font12)s; font-size: 12px; color: %(text)s; }
button.xppop-item:hover, button.xppop-item:focus { border-color: %(tr_light)s; background-color: alpha(%(primary)s, 0.18); }
button.xppop-item:disabled label { color: alpha(%(text)s, 0.4); }
button.xppop-item label.xppop-side { color: %(st_hi)s; }
.xppop label.xppop-title { font-family: %(font12)s; font-size: 12px; color: %(dim)s; padding: 0 7px 1px 7px; }
.xppop .xppop-sep { min-height: 1px; background-color: alpha(%(text)s, 0.2); margin: 1px 3px; }
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
    """default | square | <вид>-<символ> (badge-bolt, icon-moon… — start_glyphs.py, 15.10.2026)."""
    try:
        v = open(START_BUTTON_FILE).read().strip()
    except OSError:
        return "default"
    import start_glyphs
    return v if v == "square" or start_glyphs.parse(v) else "default"


# Символы «Пуска» (15.10.2026): «ярлык» — квадрат акцентом впритык к левой рамке, «значок» —
# кнопка 29×29 без надписи. Идёт после блоков видов: та же специфичность, побеждает порядок.
GLYPH_CSS = """
window.xpbar-win button.start.badge, window.xpbar-win button.start.badge:hover,
window.xpbar-win button.start.badge.open, window.xpbar-win button.start.badge.open:hover,
window.xpbar-win button.start.badge.open:active { padding: 0 9px 0 1px; }
window.xpbar-win button.start.glyphonly, window.xpbar-win button.start.glyphonly:hover,
window.xpbar-win button.start.glyphonly.open, window.xpbar-win button.start.glyphonly.open:hover,
window.xpbar-win button.start.glyphonly.open:active { padding: 0 1px; }
"""


# ── оформление по стилю системы (15.10.2026) ─────────────────────────────────
# Просьба: «переделать стиль нижней панели под стиль системы (сейчас Skeet), в Настройках
# переключатель; этот (XP) оставь как выбор». state/xpbar-look: xp | system.
# system — у каждой панели вид стиля СВОЕГО монитора (system_style.style_of):
# skeet / beta, default → Light = прежний XP (Default·Light и есть бывший XP), Dark = «dark».
# CSS общий на экран, поэтому вид — класс окна look-<вид>, блоки ниже им ограничены.
BAR_LOOK_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-look")
SYS_STYLE_FILE = os.path.expanduser("~/.config/hypr/state/system-style")
SETTINGS_MODE_FILE = os.path.expanduser("~/.config/hypr/state/settings-mode")
LOOKS = ("xp", "skeet", "beta", "dark")
LOOK_COLS = {}           # вид → цвета для рисунков cairo (ручка, раскладка, искорка)
WS_ACC = {}              # вид → (акцент, радиус) подсветки стола, что переезжает к новому квадрату


def look_choice():
    try:
        return "system" if open(BAR_LOOK_FILE).read().strip() == "system" else "xp"
    except OSError:
        return "xp"


def bar_look(connector):
    if look_choice() != "system":
        return "xp"
    try:
        import system_style
        st = system_style.style_of(connector)
    except Exception:
        return "xp"
    if st in ("skeet", "beta"):
        return st
    try:
        light = open(SETTINGS_MODE_FILE).read().strip() == "light"
    except OSError:
        light = False
    return "xp" if light else "dark"


def look_of(widget):
    top = widget.get_toplevel() if widget is not None else None
    return getattr(top, "look", "xp")


SKEET_BAR_CSS = """
%(W)s .xpbar {
    background-color: %(bg)s;
    /* полоса в тонах акцента, как кромка waybar: к краям темнее, без белого конца
       (15.10.2026, просьба: «линия в конце становится белой») */
    background-image: linear-gradient(to right, %(b0)s, %(b1)s, %(b2)s, %(b1)s, %(b0)s),
                      linear-gradient(to right, %(b0d)s, %(b1d)s, %(b2d)s, %(b1d)s, %(b0d)s),
                      linear-gradient(%(line3)s, %(line3)s);
    background-size: 100%% 1px, 100%% 1px, 100%% 1px;
    background-position: 0 0, 0 1px, 0 2px;
    background-repeat: no-repeat;
    border-top: none; box-shadow: none; color: %(text)s;
    min-height: 35px;                 /* как у XP (31 + кромка + «Пуск» 26 px) — окна не прыгают */
}
%(W)s button.start, %(W)s button.start:hover {
    background-color: %(field)s; background-image: none;
    border: 1px solid %(line1)s; border-radius: 0;
    box-shadow: inset 0 0 0 1px %(line3)s;
    padding: 0 9px 0 7px; margin: 4px 8px 2px 4px; min-height: 0;
    color: %(text)s; text-shadow: none;
}
%(W)s button.start:hover { background-color: %(field_l)s; }
%(W)s button.start.open, %(W)s button.start.open:hover, %(W)s button.start.open:active {
    background-color: %(field_l)s; background-image: none; border-color: %(line1)s;
    box-shadow: inset 0 0 0 1px %(line3)s, inset 0 -2px %(acc)s;
    padding: 0 9px 0 7px; color: %(acc_l)s;
}
%(W)s button.ws {                     /* квадраты столов в рамке, как поля skeet (15.10.2026) */
    background-image: none; background-color: %(field)s; border: 1px solid %(line2)s; border-radius: 0;
    box-shadow: inset 0 0 0 1px %(line3)s; color: %(dim)s; margin: 5px 1px 3px 1px;
}
%(W)s button.ws:hover { background-image: none; background-color: %(field_l)s; border-color: %(line1)s; color: %(text)s; }
%(W)s button.ws.active { background-image: none; border-color: %(line1)s; box-shadow: inset 0 0 0 1px %(line3)s; color: %(text)s; }
%(W)s button.ws.empty { color: alpha(%(dim)s, 0.6); }
%(W)s button.ws.focused, %(W)s button.ws.focused.empty {
    /* открытый стол — тонкая рамка акцентом по кругу, приглушённо, черта снизу остаётся
       (15.10.2026, просьба: «обвести квадратик маленькой линией… не так сильно… не только снизу») */
    background-image: none; background-color: %(field_l)s; border-color: alpha(%(acc)s, 0.55);
    color: %(acc_l)s; box-shadow: inset 0 0 0 1px %(line3)s, inset 0 -2px %(acc)s;
}
%(W)s button.task {
    background-color: %(field)s; background-image: none;
    border: 1px solid %(line1)s; border-radius: 0;
    box-shadow: inset 0 0 0 1px %(line3)s;
    margin: 5px 2px 3px 2px; color: %(text)s; text-shadow: none;
}
%(W)s button.task:hover { background-image: none; background-color: %(field_l)s; }
%(W)s button.task.focused {
    background-image: none; background-color: %(field_l)s; border-color: %(line1)s;
    box-shadow: inset 0 0 0 1px %(line3)s, inset 0 -2px %(acc)s; color: %(acc_l)s;
}
%(W)s button.task.urgent { border-color: %(err)s; box-shadow: inset 0 -2px %(err)s; }
%(W)s button.arrow { color: %(dim)s; }
%(W)s button.arrow:hover { color: %(acc)s; }
%(W)s .tray {
    background-color: %(gdark)s; background-image: none;
    border-left: 1px solid %(line1)s; box-shadow: inset 1px 0 %(line3)s;
    margin-top: 3px;                  /* полоса палитры сверху идёт во всю ширину */
}
%(W)s .tray label { color: %(dim)s; }  /* не белым: значки акцентом, цифры приглушённо */
%(W)s .tray label.glyph { color: %(acc)s; }
%(W)s .tray label.clock { color: %(acc_l)s; }
%(W)s .tray label.off { color: alpha(%(dim)s, 0.55); }
%(W)s label.lyrics { color: %(text)s; }
%(W)s label.note { color: %(acc)s; }
%(T)s .xptray {                      /* окно skeet: полоса акцента сверху, значки в рамках (15.10.2026) */
    background-color: %(bg)s;
    background-image: linear-gradient(to right, %(b0)s, %(b1)s, %(b2)s, %(b1)s, %(b0)s),
                      linear-gradient(to right, %(b0d)s, %(b1d)s, %(b2d)s, %(b1d)s, %(b0d)s),
                      linear-gradient(%(line3)s, %(line3)s);
    background-size: 100%% 1px, 100%% 1px, 100%% 1px;
    background-position: 0 0, 0 1px, 0 2px;
    background-repeat: no-repeat;
    border: 1px solid %(line1)s; padding: 7px 4px 4px 4px;
    border-radius: 0; box-shadow: 0 0 0 1px %(line3)s, 0 0 0 4px %(line2)s, 0 0 0 5px %(line1)s;
}
%(T)s button.xptray-item {
    background-color: %(field)s; background-image: none; border: 1px solid %(line2)s;
    box-shadow: inset 0 0 0 1px %(line3)s; border-radius: 0; padding: 4px; margin: 1px;
}
%(T)s button.xptray-item:hover {
    border-color: %(line1)s; background-color: %(field_l)s;
    box-shadow: inset 0 0 0 1px %(line3)s, inset 0 -2px %(acc)s;
}
%(T)s .xptray label { color: %(dim)s; }
%(T)s .xptray.xppop {                 /* рамка тонкая и внутри плашки — внешнее кольцо обрезалось снизу (19.10.2026) */
    padding: 4px 1px 1px 1px; border: 1px solid %(line1)s; box-shadow: inset 0 0 0 1px %(line3)s;
}
%(T)s button.xppop-item { border: none; border-radius: 0; padding: 1px 7px; }
%(T)s button.xppop-item label { color: %(text)s; }
%(T)s button.xppop-item:hover, %(T)s button.xppop-item:focus {
    background-color: %(field_l)s; box-shadow: inset 2px 0 %(acc)s;
}
%(T)s button.xppop-item:hover label, %(T)s button.xppop-item:focus label { color: %(acc_l)s; }
%(T)s button.xppop-item.current label { color: %(acc)s; }
%(T)s button.xppop-item:disabled label { color: alpha(%(dim)s, 0.5); }
%(T)s button.xppop-item label.xppop-side { color: %(acc)s; }
%(T)s .xppop label.xppop-title { color: %(acc)s; }
%(T)s .xppop .xppop-sep { background-color: %(line2)s; margin: 2px 1px; }
"""

BETA_BAR_CSS = """
%(W)s .xpbar {
    background-color: %(bar)s; background-image: none;
    border-top: 1px solid %(line_strong)s; box-shadow: none; color: %(text)s;
}
%(W)s button.start, %(W)s button.start:hover {
    background-color: %(card)s; background-image: none;
    border: 1px solid %(frame)s; border-radius: 0; box-shadow: none;
    padding: 0 9px 0 7px; margin: 3px 8px 3px 4px; min-height: 0;
    color: %(text)s; text-shadow: none;
}
%(W)s button.start:hover { background-color: %(hover)s; }
%(W)s button.start.open, %(W)s button.start.open:hover, %(W)s button.start.open:active {
    background-color: %(sel)s; background-image: none; border-color: %(frame)s;
    box-shadow: inset 0 -2px %(acc)s; padding: 0 9px 0 7px; color: %(sel_text)s;
}
%(W)s button.ws {
    background-image: none; background-color: %(card)s; border: 1px solid %(line)s; border-radius: 0;
    box-shadow: none; color: %(dim)s;
}
%(W)s button.ws:hover { background-image: none; background-color: %(hover)s; border-color: %(line_strong)s; color: %(text)s; }
%(W)s button.ws.active { background-image: none; border-color: %(line_strong)s; box-shadow: none; color: %(text)s; }
%(W)s button.ws.empty { color: alpha(%(dim)s, 0.6); }
%(W)s button.ws.focused, %(W)s button.ws.focused.empty {
    background-image: none; background-color: %(sel)s; border-color: %(frame)s;
    color: %(sel_text)s; box-shadow: none;
}
%(W)s button.task {
    background-color: %(card)s; background-image: none;
    border: 1px solid %(line)s; border-radius: 0; box-shadow: none;
    color: %(text)s; text-shadow: none;
}
%(W)s button.task:hover { background-image: none; background-color: %(hover)s; }
%(W)s button.task.focused {
    background-image: none; background-color: %(sel)s; border-color: %(frame)s;
    box-shadow: none; color: %(sel_text)s;
}
%(W)s button.task.urgent { border-color: %(err)s; box-shadow: inset 0 -2px %(err)s; }
%(W)s button.arrow { color: %(dim)s; }
%(W)s button.arrow:hover { color: %(acc)s; }
%(W)s .tray {
    background-color: %(card)s; background-image: none;
    border-left: 1px solid %(line)s; box-shadow: none;
}
%(W)s .tray label { color: %(dim)s; }
%(W)s .tray label.glyph { color: %(acc)s; }
%(W)s .tray label.clock { color: %(text)s; }
%(W)s .tray label.off { color: alpha(%(dim)s, 0.55); }
%(W)s label.lyrics { color: %(text)s; }
%(W)s label.note { color: %(acc)s; }
%(T)s .xptray {
    background-color: %(bg)s; background-image: none; border: 1px solid %(frame)s;
    border-radius: 0; box-shadow: 3px 3px 0 0 alpha(black, 0.35);
}
%(T)s button.xptray-item {
    background-color: %(card)s; background-image: none; border: 1px solid %(line)s;
    border-radius: 0; padding: 4px; margin: 1px;
}
%(T)s button.xptray-item:hover { border-color: %(acc)s; background-color: %(hover)s; }
%(T)s .xptray label { color: %(dim)s; }
%(T)s .xptray.xppop { padding: 1px; box-shadow: none; }
%(T)s button.xppop-item { border: none; border-radius: 0; padding: 1px 7px; }
%(T)s button.xppop-item label { color: %(text)s; }
%(T)s button.xppop-item:hover, %(T)s button.xppop-item:focus { background-color: %(hover)s; box-shadow: inset 2px 0 %(acc)s; }
%(T)s button.xppop-item.current label, %(T)s button.xppop-item label.xppop-side { color: %(acc)s; }
%(T)s button.xppop-item:disabled label { color: alpha(%(dim)s, 0.5); }
%(T)s .xppop .xppop-sep { background-color: %(line)s; }
"""

DARK_BAR_CSS = """
%(W)s .xpbar {
    background-color: %(base)s; background-image: none;
    border-top: 1px solid %(line)s; box-shadow: none; color: %(on_surface)s;
    min-height: 34px;
}
%(W)s button.start, %(W)s button.start:hover {
    background-color: %(surface_high)s; background-image: none;
    border: none; border-radius: 8px; box-shadow: none;
    padding: 0 12px 0 8px; margin: 3px 8px 3px 4px; min-height: 0;
    color: %(on_surface)s; text-shadow: none;
}
%(W)s button.start:hover { background-color: %(hover)s; }
%(W)s button.start.open, %(W)s button.start.open:hover, %(W)s button.start.open:active {
    background-color: %(sel)s; background-image: none; box-shadow: none;
    padding: 0 12px 0 8px; color: %(primary)s;
}
%(W)s button.ws {
    background-image: none; background-color: %(surface_container)s; border: none; border-radius: 6px;
    box-shadow: inset 0 0 0 1px %(line)s; color: %(dim)s;
}
%(W)s button.ws:hover { background-image: none; background-color: %(surface_high)s; color: %(on_surface)s; }
%(W)s button.ws.active { background-image: none; color: %(on_surface)s; }
%(W)s button.ws.empty { color: alpha(%(dim)s, 0.6); }
%(W)s button.ws.focused, %(W)s button.ws.focused.empty {
    background-image: none; background-color: %(sel)s; color: %(primary)s; box-shadow: none;
}
%(W)s button.task {
    background-color: %(surface_container)s; background-image: none;
    border: none; border-radius: 6px; box-shadow: none;
    color: %(on_surface)s; text-shadow: none;
}
%(W)s button.task:hover { background-image: none; background-color: %(surface_high)s; }
%(W)s button.task.focused {
    background-image: none; background-color: %(sel)s;
    box-shadow: inset 0 -2px %(primary)s; color: %(primary)s;
}
%(W)s button.task.urgent { box-shadow: inset 0 -2px %(error)s; }
%(W)s .tray {
    background-color: transparent; background-image: none;
    border-left: none; box-shadow: none;
}
%(W)s .tray label { color: %(dim)s; }
%(W)s .tray label.glyph { color: %(primary)s; }
%(W)s .tray label.clock { color: %(on_surface)s; }
%(W)s .tray label.off { color: alpha(%(dim)s, 0.55); }
%(T)s .xptray {
    background-color: %(surface)s; background-image: none; border: 1px solid %(line)s;
    border-radius: 8px; box-shadow: none;
}
%(T)s button.xptray-item {
    background-color: %(surface_container)s; background-image: none; border: none;
    box-shadow: inset 0 0 0 1px %(line)s; border-radius: 6px; padding: 4px; margin: 1px;
}
%(T)s button.xptray-item:hover { background-color: %(surface_high)s; }
%(T)s .xptray label { color: %(dim)s; }
%(T)s .xptray.xppop { padding: 2px; }
%(T)s button.xppop-item { border: none; border-radius: 5px; padding: 1px 7px; }
%(T)s button.xppop-item label { color: %(on_surface)s; }
%(T)s button.xppop-item:hover, %(T)s button.xppop-item:focus { background-color: %(surface_high)s; }
%(T)s button.xppop-item:hover label, %(T)s button.xppop-item.current label,
%(T)s button.xppop-item label.xppop-side { color: %(primary)s; }
%(T)s button.xppop-item:disabled label { color: alpha(%(dim)s, 0.5); }
%(T)s .xppop .xppop-sep { background-color: %(line)s; }
"""


def look_css(c):
    """Блоки CSS всех видов, кроме xp, + цвета для рисунков cairo (LOOK_COLS)."""
    import rec_style
    out = []
    p = c
    sk = rec_style.colors("skeet")
    for i, s in enumerate(sk["strip"]):
        sk["s%d" % i] = s
        sk["s%dd" % i] = mix(s, "#000000", 0.55)
    # Кромка тише: середина была почти белой и не сливалась с панелью (19.10.2026, просьба:
    # «слишком яркая… адаптируй под панель») — акцент наполовину в фон панели, без acc_l.
    bstrip = [mix(sk["acc_d"], sk["bg"], 0.55), mix(sk["acc"], sk["bg"], 0.5), mix(sk["acc"], sk["bg"], 0.35)]
    for i, s in enumerate(bstrip):
        sk["b%d" % i] = s
        sk["b%dd" % i] = mix(s, sk["bg"], 0.6)
    sk["err"] = p["error"]
    be = rec_style.colors("beta")
    be.update(err=p["error"], hover=mix(be["card"], be["acc"], 0.12))
    dk = dict(p, line=mix(c["base"], p["on_surface"], 0.14), dim=p["on_surface_variant"],
              hover=mix(p["surface_high"], p["primary"], 0.15),
              sel=mix(c["base"], p["primary"], 0.24))
    for look, tpl, cc in (("skeet", SKEET_BAR_CSS, sk), ("beta", BETA_BAR_CSS, be),
                          ("dark", DARK_BAR_CSS, dk)):
        cc = dict(cc, W="window.xpbar-win.look-" + look, T="window.xptray-win.look-" + look)
        out.append(tpl % cc)
    LOOK_COLS.clear()
    LOOK_COLS.update({
        "skeet": dict(acc=sk["acc"], acc_d=sk["acc_d"], bg=sk["bg"], st_hi=sk["acc_l"], grip=sk["line1"], grip_d=sk["line3"], lang_bg=sk["field"],
                      lang_line=sk["line1"], lang_in=sk["line3"], lang_text=sk["acc_l"], radius=0),
        "beta": dict(acc=be["acc"], bg=be["bar"], st_hi=be["acc"], grip=be["line"], grip_d=None, lang_bg=be["field"],
                     lang_line=be["line_strong"], lang_in=None, lang_text=be["text"], radius=0),
        "dark": dict(acc=p["primary"], bg=c["base"], st_hi=p["primary"], grip=dk["line"], grip_d=None, lang_bg=p["surface_high"],
                     lang_line=None, lang_in=None, lang_text=p["on_surface"], radius=4),
    })
    return "".join(out)


def load_css():
    global _provider
    c = colors()
    c.update(font=FONT, nerd=NERD, font12=FONT12)
    css = CSS % c
    if start_button_look() != "default":
        b, p = c["base"], c["primary"]
        # Утопленный тёмный блок, как кнопка angelOS (04.10.2026, «внимание к деталям»):
        # темнее панели, рамка-«врезка»: сверху/слева тень, снизу/справа светлый край.
        css += SQUARE_CSS % dict(c, sq_bg=mix(b, "#000000", 0.35), sq_hover=mix(b, p, 0.08),
                                 sq_press=mix(b, "#000000", 0.55),
                                 sq_dark=mix(b, "#000000", 0.70), sq_light=c["st_bot"],
                                 sq_text=mix(c["on_surface"], b, 0.12),
                                 sq_open=mix(b, p, 0.30), sq_open_text=c["st_hi"])
    try:
        css += look_css(c)
    except Exception as e:                      # вид по стилю не собрался — остаётся XP
        print("xpbar: look_css: %r" % e, file=sys.stderr)
    # квадрат стола под перетаскиваемой кнопкой окна — рамка акцентом (19.10.2026); правила
    # сильнее .focused/.empty каждого вида, потому по одному на вид
    for sel, col in [("window", c["st_hi"])] + [("window.xpbar-win.look-" + k, v["acc"])
                                                for k, v in LOOK_COLS.items()]:
        css += ("%(s)s button.ws.drop, %(s)s button.ws.drop.focused, %(s)s button.ws.drop.empty, "
                "%(s)s button.ws.drop.focused.empty { border-color: %(c)s; "
                "box-shadow: inset 0 0 0 2px %(c)s; }\n" % dict(s=sel, c=col))
    # 19.10.2026: окно просит внимания — квадрат стола трижды мягко вспыхивает акцентом и
    # остаётся с тонкой чертой снизу; нота — кто на столе звучит (тусклая — заглушён)
    WS_ACC.clear()
    WS_ACC.update({"xp": (c["st_hi"], 3)})
    WS_ACC.update({k: (v["acc"], v.get("radius", 0)) for k, v in LOOK_COLS.items()})
    for key, sel in [("xp", "window")] + [(k, "window.xpbar-win.look-" + k) for k in LOOK_COLS]:
        css += ("@keyframes ws-urgent-%(k)s { from { box-shadow: inset 0 -2px alpha(%(c)s, 0.3); } "
                "to { box-shadow: inset 0 0 0 1px %(c)s, inset 0 -3px %(c)s; } }\n"
                "%(s)s button.ws.urgent { box-shadow: inset 0 -2px %(c)s; "
                "animation: ws-urgent-%(k)s 0.9s ease-in-out 6 alternate; }\n"
                "%(s)s button.ws label.wsnote { color: %(c)s; }\n"
                "%(s)s button.ws label.wsnote.muted { color: alpha(%(c)s, 0.45); }\n"
                "%(s)s button.ws.focused label.wsnote { color: inherit; }\n"
                % dict(k=key, s=sel, c=WS_ACC[key][0]))
    css += GLYPH_CSS
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


KBD = {"fds": {}, "t": 0.0}


def shift_held():
    """Зажат ли Shift — спросить у самих клавиатур (EVIOCGKEY). Панель — слой без фокуса
    клавиатуры, и Wayland не шлёт ей модификаторы: в событии колеса Shift не виден никогда
    (19.10.2026, «Shift+колесо у меня не работает»). Группа input у static есть. Устройства
    держатся открытыми: close() у evdev — ~20 мс на каждое (замерено), опрос — доли мс."""
    import fcntl
    if time.monotonic() - KBD["t"] > 30:
        paths = set()
        try:
            blocks = open("/proc/bus/input/devices").read().split("\n\n")
        except OSError:
            blocks = []
        for b in blocks:
            h = next((ln for ln in b.splitlines() if ln.startswith("H: Handlers=")), "")
            ev = next((ln for ln in b.splitlines() if ln.startswith("B: EV=")), "B: EV=0")
            # настоящая клавиатура — с автоповтором (EV_REP), как в super_tap.py
            if "kbd" in h and int(ev[6:], 16) & 0x100000:
                paths |= {"/dev/input/" + t for t in h.split() if t.startswith("event")}
        for path in set(KBD["fds"]) - paths:
            os.close(KBD["fds"].pop(path))
        for path in paths - set(KBD["fds"]):
            try:
                KBD["fds"][path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_CLOEXEC)
            except OSError:
                pass
        KBD["t"] = time.monotonic()
    for path, fd in list(KBD["fds"].items()):
        try:
            keys = fcntl.ioctl(fd, 0x80604518, bytes(96))      # EVIOCGKEY(96)
        except OSError:                                         # клавиатуру выдернули
            os.close(KBD["fds"].pop(path))
            KBD["t"] = 0.0
            continue
        if any(keys[k // 8] >> (k % 8) & 1 for k in (42, 54)):   # KEY_LEFTSHIFT, KEY_RIGHTSHIFT
            return True
    return False


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
        reply = sk.makefile().readline()
        sk.close()
        return reply
    except (OSError, KeyError) as e:
        return "Err: %s" % e


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
        elif kind == "WorkspaceUrgencyChanged":
            ws = self.workspaces.get(d["id"])
            if ws:
                ws["is_urgent"] = d.get("urgent")
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


# Настоящая высота панели по виду (CSS min-height + кромка): у skeet и dark она 35, а зона
# была H = 32 — панель на 3 px лезла в зазор, снизу он выходил 5 px против 8 сверху
# (19.10.2026, просьба: «зазор до нижней панели отличается от верхнего»).
LOOK_H = {"skeet": 35, "dark": 35}


def zone_size(h=H):
    """Сколько места отнять у окон снизу. h — высота панели (LOOK_H по виду). С зазором — вся высота панели (niri
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
    return max(1, h - niri_gaps() - max(0, niri_border() - GLUE_SHOW)) if glued else h


# ── значки программ ────────────────────────────────────────────────────────

_app_cache = {}

TERMINALS = {"kitty", "foot", "alacritty", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}


def window_icon_id(app_id, title):
    """app_id для значка: терминал с jchat — как jchat."""
    t = (title or "").lstrip()
    # jchat, запущенный из терминала (заголовок «jchat ~», «jchat tg-login ~»), —
    # значком jchat.desktop (15.10.2026, просьба: «показывать иконку вместо kitty»).
    if app_id in TERMINALS and (t == "jchat" or t.startswith("jchat ")):
        return "jchat"
    return app_id


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
        lay.set_font_description(Pango.FontDescription("JetBrainsMono Nerd Font 8px"))
        lay.set_text(self.text, -1)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgb(*rgb("on_surface", "#e1e1ef"))
        cr.move_to(ix + len(self.KBD[0]) * k + 5, int(y0 + (bh - th) / 2))
        PangoCairo.show_layout(cr, lay)
        return True

    def draw_flat(self, cr, lc):
        """Стиль системы (skeet/beta/dark): плоский квадратик, буквы цветом стиля."""
        import gi
        gi.require_version("PangoCairo", "1.0")
        from gi.repository import Pango, PangoCairo
        a = self.get_allocation()
        w, h = a.width, a.height
        x0, y0, bw, bh, r = 1, (h - self.H) // 2, w - 2, self.H, lc.get("radius", 0)
        if r:
            cr.new_sub_path()
            cr.arc(x0 + bw - r, y0 + r, r, -math.pi / 2, 0)
            cr.arc(x0 + bw - r, y0 + bh - r, r, 0, math.pi / 2)
            cr.arc(x0 + r, y0 + bh - r, r, math.pi / 2, math.pi)
            cr.arc(x0 + r, y0 + r, r, math.pi, 3 * math.pi / 2)
            cr.close_path()
        else:
            cr.rectangle(x0, y0, bw, bh)
        cr.set_source_rgb(*hex2rgb(lc["lang_bg"]))
        cr.fill()
        if lc.get("lang_line"):
            cr.set_line_width(1)
            cr.set_source_rgb(*hex2rgb(lc["lang_line"]))
            cr.rectangle(x0 + 0.5, y0 + 0.5, bw - 1, bh - 1)
            cr.stroke()
        if lc.get("lang_in"):
            cr.set_line_width(1)
            cr.set_source_rgb(*hex2rgb(lc["lang_in"]))
            cr.rectangle(x0 + 1.5, y0 + 1.5, bw - 3, bh - 3)
            cr.stroke()
        lay = PangoCairo.create_layout(cr)
        fo = cairo.FontOptions()
        fo.set_antialias(cairo.ANTIALIAS_GRAY)
        fo.set_hint_style(cairo.HINT_STYLE_SLIGHT)
        PangoCairo.context_set_font_options(lay.get_context(), fo)
        lay.set_font_description(Pango.FontDescription(self.FONT))
        lay.set_text(self.text, -1)
        tw, th = lay.get_pixel_size()
        cr.set_source_rgb(*hex2rgb(lc["lang_text"]))
        cr.move_to(round((w - tw) / 2), round((h - th) / 2))
        PangoCairo.show_layout(cr, lay)
        return True

    def on_draw(self, _w, cr):
        if self.look == "keyboard":
            return self.draw_keyboard(cr)
        lc = LOOK_COLS.get(look_of(self))
        if lc:
            return self.draw_flat(cr, lc)
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
        self.set_has_window(False)   # без своего окна: иначе, показанный на лету, перехватывает щелчки кнопки «Пуск» (15.10.2026)
        self.small = small
        self.set_size_request(w, h)
        self.connect("draw", self.on_draw)

    def on_draw(self, _w, cr):
        c = LOOK_COLS.get(look_of(self)) or colors()
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


class StartGlyph(Gtk.DrawingArea):
    """Символ кнопки «Пуск» из start_glyphs.py: «ярлык» (квадрат акцентом с тёмным силуэтом и
    чертой-разделителем) или «значок» (символ акцентом со свечением)."""

    def __init__(self):
        super().__init__()
        self.set_has_window(False)   # без своего окна: иначе, показанный на лету, перехватывает щелчки кнопки «Пуск» (15.10.2026)
        self.form, self.name = "icon", "sparkle"
        self.connect("draw", self.on_draw)

    def set(self, form, name):
        self.form, self.name = form, name
        self.set_size_request(27 if form == "badge" else 25, 25)
        self.queue_draw()

    def on_draw(self, _w, cr):
        import start_glyphs as sg
        c = LOOK_COLS.get(look_of(self)) or colors()
        rgb = lambda h: tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))  # noqa: E731
        acc, bg = rgb(c.get("acc") or c["primary"]), rgb(c.get("bg") or c["base"])
        btn = self.get_ancestor(Gtk.Button)
        op = btn is not None and btn.get_style_context().has_class("open")
        icon, badge = sg.palette(acc, bg)
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        a = self.get_allocation()
        if self.form == "badge":
            y0 = (a.height - 25) // 2
            cr.set_source_rgb(*(rgb(c["st_hi"]) if op else acc))   # меню открыто — светлее
            cr.rectangle(0, y0, 25, 25)
            cr.fill()
            cr.set_source_rgb(*sg._mix(acc, (0, 0, 0), .4))       # нижняя кромка темнее
            cr.rectangle(0, y0 + 24, 25, 1)
            cr.fill()
            cr.set_source_rgb(*bg)                                 # черта между квадратом и надписью
            cr.rectangle(25, y0, 1, 25)
            cr.fill()
            sg.draw(cr, self.name, 12.5, y0 + 12.5, badge)
        else:
            if op:
                icon = {k: sg._mix(v, (1, 1, 1), .15) for k, v in icon.items()}
            sg.draw(cr, self.name, a.width / 2, a.height / 2, icon, glow=acc)
        return True


class Logo(Gtk.DrawingArea):
    """Живой спрайт (если выбран) или телевизор static в цветах палитры."""

    def __init__(self):
        super().__init__()
        self.set_has_window(False)   # без своего окна: иначе, показанный на лету, перехватывает щелчки кнопки «Пуск» (15.10.2026)
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
        hh = w.get_allocated_height()
        lc = LOOK_COLS.get(look_of(w))
        if lc:                                  # стиль системы: тонкий разделитель вместо точек
            cr.set_source_rgb(*hex2rgb(lc["grip"]))
            cr.rectangle(3, 8, 1, hh - 14)
            cr.fill()
            if lc.get("grip_d"):
                cr.set_source_rgb(*hex2rgb(lc["grip_d"]))
                cr.rectangle(4, 8, 1, hh - 14)
                cr.fill()
            return True
        c = colors()
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
            # трека (06.10.2026, просьба: «показывать, только когда трек включён»).
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
# 01.10.2026, просьба: «иконку, по нажатию на которую открывается маленькая плашка с
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
        self.get_style_context().add_class("look-" + getattr(bar, "look", "xp"))
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


POPUP = []               # открытая плашка-меню панели (одна на все мониторы)


def pop_item(text, cb=None, on=True, mark=False, sub=None, back=False):
    """Строка плашки: cb — что сделать; sub — список строк второй ступени; back — назад."""
    return dict(kind="item", text=text, cb=cb, on=on, mark=mark, sub=sub, back=back)


def pop_title(text):
    return dict(kind="title", text=text)


POP_SEP = dict(kind="sep")


class BarPopup(Gtk.Window):
    """Маленькое меню над панелью вместо Gtk.Menu (19.10.2026, просьба: «слишком большое…
    в стиле Skeet… не исчезает, если кликнуть в другое место»). Слой OVERLAY во весь
    монитор, как TrayPlate: щелчок мимо закрывает; на других мониторах — прозрачные
    слои scrim_layer. Вид — рамка .xptray своего вида панели; подменю — вторая ступень
    в той же плашке. Esc — назад или закрыть."""

    def __init__(self, bar, entries, x=None):
        super().__init__(title="XP menu")
        for p in POPUP[:]:
            p.close()
        POPUP.append(self)
        self.bar = bar
        self.x = x
        self.pages = [entries]
        for cls in ("xptray-win", "xppop-win", "look-" + getattr(bar, "look", "xp")):
            self.get_style_context().add_class(cls)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-xppop")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        if bar.monitor:
            GtkLayerShell.set_monitor(self, bar.monitor)
        for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                  GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, e, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.connect("key-press-event", self.on_key)
        bg = Gtk.EventBox()
        bg.set_visible_window(False)
        bg.connect("button-press-event", lambda *_a: self.close() or True)
        self.add(bg)
        self.holder = Gtk.Box()
        self.holder.set_halign(Gtk.Align.START)
        self.holder.set_valign(Gtk.Align.END)
        # над панелью своего вида: у Skeet/Dark она 35 px, и плашка садилась на её край (19.10.2026)
        self.holder.set_margin_bottom(LOOK_H.get(getattr(bar, "look", "xp"), H) + 3)
        bg.add(self.holder)
        catch = Gtk.EventBox()
        catch.connect("button-press-event", lambda *_a: True)
        catch.connect("button-release-event", lambda *_a: True)
        self.holder.add(catch)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        for cls in ("xptray", "xppop"):
            self.box.get_style_context().add_class(cls)
        catch.add(self.box)
        self.scrims = []
        try:
            import scrim_layer
            disp = Gdk.Display.get_default()
            for i in range(disp.get_n_monitors()):
                m = disp.get_monitor(i)
                if m != bar.monitor:
                    s = scrim_layer.Scrim(m, "jarvis-xppop-catch", self.close)
                    s.show_all()
                    self.scrims.append(s)
        except Exception as e:
            print("xpbar popup: scrim: %r" % e, file=sys.stderr)
        bar.menu_open = True
        self.fill()
        self.show()

    def fill(self):
        for c in self.box.get_children():
            c.destroy()
        for it in self.pages[-1]:
            if it["kind"] == "title":
                w = Gtk.Label(label=it["text"], xalign=0)
                w.get_style_context().add_class("xppop-title")
            elif it["kind"] == "sep":
                w = Gtk.Box()
                w.get_style_context().add_class("xppop-sep")
            else:
                w = Gtk.Button()
                w.set_relief(Gtk.ReliefStyle.NONE)
                w.get_style_context().add_class("xppop-item")
                if it["mark"]:
                    w.get_style_context().add_class("current")
                row = Gtk.Box(spacing=6)
                row.pack_start(Gtk.Label(label=it["text"], xalign=0), True, True, 0)
                side = "●" if it["mark"] else "›" if it["sub"] else ""
                if side:
                    sl = Gtk.Label(label=side)
                    sl.get_style_context().add_class("xppop-side")
                    row.pack_end(sl, False, False, 0)
                w.add(row)
                w.set_sensitive(it["on"])
                w.connect("clicked", self.on_item, it)
            self.box.pack_start(w, False, False, 0)
        # ширину мерить у показанного содержимого и с отступом 0 (см. TrayPlate.open_plate)
        self.get_child().show_all()
        self.holder.set_margin_start(0)
        self.place(self.holder.get_preferred_width()[1])

    def place(self, width):
        mon_w = self.bar.monitor.get_geometry().width if self.bar.monitor else self.bar.get_allocated_width()
        x = self.x
        if x is None:
            x = mon_w / 2
            try:
                ptr = Gdk.Display.get_default().get_default_seat().get_pointer()
                x = self.bar.get_window().get_device_position(ptr)[1]
            except Exception:
                pass
            self.x = x
        self.holder.set_margin_start(int(max(4, min(mon_w - width - 4, x))))

    def on_item(self, _b, it):
        if it["back"]:
            self.back()
        elif it["sub"] is not None:
            ui_click("click")
            self.pages.append([pop_item("‹  " + it["text"], back=True), POP_SEP] + it["sub"])
            self.fill()
        else:
            self.close()
            if it["cb"]:
                it["cb"]()

    def back(self):
        if len(self.pages) > 1:
            self.pages.pop()
            self.fill()
        else:
            self.close()

    def on_key(self, _w, e):
        k = e.keyval
        if k in (Gdk.KEY_Escape, Gdk.KEY_BackSpace, Gdk.KEY_h, Gdk.KEY_Left):
            self.back()
            return True
        if k in (Gdk.KEY_j, Gdk.KEY_k):                 # строки — j/k, как в vim
            self.child_focus(Gtk.DirectionType.DOWN if k == Gdk.KEY_j else Gtk.DirectionType.UP)
            return True
        if k in (Gdk.KEY_l, Gdk.KEY_Right):
            f = self.get_focus()
            if isinstance(f, Gtk.Button):
                f.clicked()
            return True
        return False

    def close(self):
        if self in POPUP:
            POPUP.remove(self)
        for s in self.scrims:
            s.destroy()
        self.scrims = []
        bar = self.bar
        bar.menu_open = False
        if bar.mode == "hover":
            bar.hide_id = GLib.timeout_add(HIDE_MS * 2, bar.hide_now)
        self.destroy()
        return False


class PomoBolt(Gtk.DrawingArea):
    """Пиксельная молния pomo в трее (19.10.2026, пользователь): видна, пока идёт pomo (работа
    или перерыв), иначе её нет в панели совсем; на паузе — сильно бледная. В духе Skeet —
    заливка акцентом обоев сверху светлее, книзу темнее, тёмный контур и слабое свечение.
    Цвета — LOOK_COLS["skeet"], их пересобирает load_css при смене обоев."""
    STATE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "pomo", "state")
    # ровная лесенка: внизу правый край уходит на клетку за строку до острого кончика
    # (19.10.2026, просьба: гладкий контур не понравился, «ровнее снизу», без обрубка)
    SHAPE = ("...###",
             "..###.",
             ".###..",
             "######",
             "..###.",
             ".###..",
             "###...",
             "##....",
             "#.....")
    K = 2
    ALL = []
    _mon = None

    def __init__(self):
        super().__init__()
        self.set_has_window(False)
        self.set_size_request(len(self.SHAPE[0]) * self.K + 4, 22)
        self.connect("draw", self.on_draw)
        self.box = None             # EventBox в трее — его и прячем
        self.st = {}
        PomoBolt.ALL.append(self)
        self.connect("destroy", lambda *_a: PomoBolt.ALL.remove(self) if self in PomoBolt.ALL else None)
        if PomoBolt._mon is None:
            # inotify на файл состояния + редкий опрос (на случай, если каталога ещё нет)
            try:
                PomoBolt._mon = Gio.File.new_for_path(self.STATE).monitor_file(Gio.FileMonitorFlags.NONE, None)
                PomoBolt._mon.connect("changed", lambda *_a: PomoBolt.refresh_all())
            except GLib.Error:
                PomoBolt._mon = False
            GLib.timeout_add_seconds(5, lambda: PomoBolt.refresh_all() or True)

    @classmethod
    def read_state(cls):
        st = {}
        try:
            for line in open(cls.STATE):
                k, _, v = line.strip().partition("=")
                st[k] = v
        except OSError:
            pass
        return st

    @classmethod
    def refresh_all(cls):
        st = cls.read_state()
        for b in list(cls.ALL):
            b.apply(st)

    def apply(self, st):
        on = st.get("phase", "idle") in ("work", "break")
        if self.box is not None and self.box.get_visible() != on:
            self.box.set_visible(on)
        if on:
            self.box.set_tooltip_text(self.tip(st))
        if st != self.st:
            self.st = st
            self.queue_draw()

    @staticmethod
    def tip(st):
        what = "работа" if st.get("phase") == "work" else "перерыв"
        try:
            paused = int(st.get("paused") or 0)
            left = int(st.get("started") or 0) + int(st.get("duration") or 0) - int(paused or time.time())
        except ValueError:
            paused, left = 0, 0
        t = "Pomo: %s" % what
        if st.get("task"):
            t += " · %s" % st["task"]
        if left > 0:
            t += " · осталось %d:%02d" % (left // 60, left % 60)
        return t + (" · пауза" if paused else "")

    def on_draw(self, _w, cr):
        c = LOOK_COLS.get("skeet") or {}

        def rgb(v, d):
            v = v or d
            return [int(v[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        hi = rgb(c.get("st_hi"), "#9fb4f5")
        acc = rgb(c.get("acc"), "#7f95e0")
        lo = rgb(c.get("acc_d"), "#4a5a99")
        dark = [v * 0.25 for v in rgb(c.get("bg"), "#0c0c0c")]
        paused = (self.st.get("paused") or "0") != "0"
        if paused:                                              # пауза: сильно бледнее и серее
            gray = [0.55, 0.55, 0.58]
            hi, acc, lo = (mix_rgb(x, gray, 0.6) for x in (hi, acc, lo))
        alpha = 0.3 if paused else 1.0
        k, rows = self.K, self.SHAPE
        a = self.get_allocation()
        x0 = (a.width - len(rows[0]) * k) // 2
        y0 = (a.height - len(rows) * k) // 2
        cells = [(i, j) for j, row in enumerate(rows) for i, ch in enumerate(row) if ch == "#"]
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        cr.set_source_rgba(*acc, 0.16 * alpha)                  # свечение
        for i, j in cells:
            cr.rectangle(x0 + i * k - 2, y0 + j * k - 2, k + 4, k + 4)
        cr.fill()
        cr.set_source_rgba(*dark, 0.9 * alpha)                  # контур
        for i, j in cells:
            cr.rectangle(x0 + i * k - 1, y0 + j * k - 1, k + 2, k + 2)
        cr.fill()
        n = len(rows) - 1
        for i, j in cells:                                      # заливка: светлый верх → тёмный низ
            t = j / n
            col = mix_rgb(hi, acc, t * 2) if t < 0.5 else mix_rgb(acc, lo, (t - 0.5) * 2)
            cr.set_source_rgba(*col, alpha)
            cr.rectangle(x0 + i * k, y0 + j * k, k, k)
            cr.fill()
        return True


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
        self.bolt = PomoBolt()
        self.bolt.box = self.clickable(self.bolt, None)
        self.bolt.box.set_no_show_all(True)
        self.bolt.show()
        self.add(self.bolt.box)
        self.bolt.apply(PomoBolt.read_state())
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
        # в центр монитора (05.10.2026, просьба: «курсор прыгает в центр, не трогай»).
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

# Перенос окна на стол перетаскиванием кнопки окна на квадрат стола (19.10.2026, пользователь
# выбрал из идей по столам в нижней панели). Только внутри панели (SAME_APP) — квадраты
# любых мониторов принимают, окно уходит без фокуса: остаётесь на своём столе.
DND_TARGET = "jarvis/window-id"


def dnd_targets():
    return [Gtk.TargetEntry.new(DND_TARGET, Gtk.TargetFlags.SAME_APP, 0)]


# ── столы: перенос квадратов, звук, меню (19.10.2026) ─────────────────────────
WS_TARGET = "jarvis/workspace-id"       # квадрат стола тащат на другое место / монитор
SPRING_MS = 600                         # окно держат над квадратом — стол открывается
SLIDE_MS = 170                          # подсветка переезжает к новому столу
SLIDE_WAIT = 12                         # кадров ждать места у квадрата нового стола
# Вид перехода между столами — выбор в Настройках → Нижняя панель (19.10.2026, просьба: «какой-то
# один сложно выбрать»). Файл читается при каждом переходе — панель не перезапускать.
WS_ANIM_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-ws-anim")
# 19.10.2026 вечер (понравились Переезд и Червячок): ещё восемь с движением — Гусеница … Телепорт.
WS_ANIMS = (("slide", "Переезд"), ("worm", "Червячок"), ("inch", "Гусеница"), ("stretch", "Резинка"),
            ("goo", "Капля"), ("lean", "Наклон"), ("snap", "Рывок"), ("spring", "Пружина"),
            ("elastic", "Эластик"), ("bounce", "Отскок"), ("teleport", "Телепорт"),
            ("steps", "Пиксельные шаги"), ("trail", "Шлейф"), ("underline", "Черта снизу"),
            ("fade", "Угасание"), ("fill", "Заливка"), ("grow", "Вырастает"), ("off", "Без анимации"))
WS_ANIM_MS = {"worm": 240, "spring": 280, "steps": 210, "trail": 230, "fade": 200, "fill": 230,
              "grow": 200, "stretch": 230, "goo": 300, "lean": 200, "snap": 120, "elastic": 520,
              "bounce": 420, "teleport": 240}


def ws_anim():
    try:
        k = open(WS_ANIM_FILE).read().strip()
    except OSError:
        return "slide"
    return k if k in dict(WS_ANIMS) else "slide"


def _ease(t):
    return 1 - (1 - max(0.0, min(1.0, t))) ** 3


def _back(t):                           # с проскоком за цель и возвратом
    c1 = 2.0
    t = max(0.0, min(1.0, t)) - 1
    return 1 + (c1 + 1) * t ** 3 + c1 * t ** 2


def _elastic(t):
    t = max(0.0, min(1.0, t))
    return 1 if t >= 1 else 2 ** (-10 * t) * math.sin((t * 10 - 0.75) * 2 * math.pi / 3) + 1


def _bounce(t):
    t, n, d = max(0.0, min(1.0, t)), 7.5625, 2.75
    if t < 1 / d:
        return n * t * t
    if t < 2 / d:
        t -= 1.5 / d
        return n * t * t + 0.75
    if t < 2.5 / d:
        t -= 2.25 / d
        return n * t * t + 0.9375
    t -= 2.625 / d
    return n * t * t + 0.984375


def inch_steps(f, to):
    """Сколько квадратов проходит гусеница (шаг — ширина квадрата с зазором)."""
    return max(1, round(abs(to[0] - f[0]) / max(1.0, f[2] + 2)))


def slide_ms(kind, f, to):
    if kind == "inch":
        return min(480, 170 * inch_steps(f, to))
    return WS_ANIM_MS.get(kind, SLIDE_MS)


def _worm(f, to, t, y_t=None):
    lead, tail = _ease(t / 0.6), _ease((t - 0.3) / 0.7)
    el, er = (tail, lead) if to[0] >= f[0] else (lead, tail)
    x1 = f[0] + (to[0] - f[0]) * el
    x2 = f[0] + f[2] + (to[0] + to[2] - f[0] - f[2]) * er
    k = t if y_t is None else y_t
    return (x1, f[1] + (to[1] - f[1]) * k, x2 - x1, f[3] + (to[3] - f[3]) * k)


def _scaled(b, sx, sy=None):
    x, y, w, h = b
    sy = sx if sy is None else sy
    return (x + w * (1 - sx) / 2, y + h * (1 - sy) / 2, w * sx, h * sy)


def _lerp(f, to, e):
    return tuple(f[i] + (to[i] - f[i]) * e for i in range(4))


def slide_rects(kind, f, to, t):
    """[(рамка, прозрачность, полоса?)] — что рисовать на доле пути t; первая — «где сейчас»."""
    if kind == "spring":
        return [(_lerp(f, to, _back(t)), 1, False)]
    if kind == "steps":                 # рывками, как в старых играх
        return [(tuple(round(v) for v in _lerp(f, to, round(_ease(t) * 5) / 5)), 1, False)]
    if kind == "worm":                  # передний край вперёд, хвост догоняет
        return [(_worm(f, to, t), 1, False)]
    if kind == "inch":                  # червячок, но шажками через каждый квадрат
        n = inch_steps(f, to)
        i = min(n - 1, int(t * n))
        a, b = _lerp(f, to, i / n), _lerp(f, to, (i + 1) / n)
        return [(_worm(a, b, t * n - i, t), 1, False)]
    if kind == "stretch":               # тянется по скорости, у цели сжимается обратно
        x, y, w, h = _lerp(f, to, _ease(t))
        v = (1 - t) ** 2 * min(1.0, abs(to[0] - f[0]) / max(1.0, 2 * f[2]))
        sw, sh = 1 + 0.7 * v, 1 - 0.15 * v
        return [(_scaled((x, y, w, h), sw, sh), 1, False)]
    if kind == "goo":                   # перетекает: старая капля тает, новая набухает, перемычка
        e = _ease(t)
        a, b = _scaled(f, 1 - e), _scaled(to, _back(t))
        neck = 0.32 * f[3] * math.sin(math.pi * min(1.0, t * 1.15))
        cx1, cx2 = f[0] + f[2] / 2, to[0] + to[2] / 2
        cy = (f[1] + f[3] / 2 + to[1] + to[3] / 2) / 2
        tip = cx1 + (cx2 - cx1) * _ease(t * 1.6)            # перемычка тянется от старой капли
        tail = cx1 + (cx2 - cx1) * _ease((t - 0.3) / 0.7)    # и подтягивается за ней
        lo, hi = min(tail, tip), max(tail, tip)
        return [(to, 0, False), (a, 1, False), (b, 1, False),
                ((lo, cy - neck / 2, hi - lo, neck), 1, False)]
    if kind == "lean":                  # на ходу кренится вперёд, как в мультфильмах
        x, y, w, h = _lerp(f, to, _ease(t))
        d = 1 if to[0] >= f[0] else -1
        k = d * 5 * (1 - t) ** 2 * min(1.0, abs(to[0] - f[0]) / max(1.0, 2 * f[2]))
        return [((x, y, w, h), 0, False),
                ([(x + k, y), (x + w + k, y), (x + w - k, y + h), (x - k, y + h)], 1, "poly")]
    if kind == "snap":
        return [(_lerp(f, to, 1 - 2 ** (-10 * t)), 1, False)]
    if kind == "elastic":
        return [(_lerp(f, to, _elastic(t)), 1, False)]
    if kind == "bounce":
        return [(_lerp(f, to, _bounce(t)), 1, False)]
    if kind == "teleport":              # схлопывается в черту — разворачивается на новом месте
        if t < 0.45:
            return [(f, 0, False), (_scaled(f, 1 - _ease(t / 0.45) * 0.9, 1 + 0.15 * t / 0.45), 1, False)]
        u = _ease((t - 0.45) / 0.55)
        return [(to, 0, False), (_scaled(to, 0.1 + 0.9 * u, 1.07 - 0.07 * u), 1, False)]
    if kind == "trail":
        return [(_lerp(f, to, _ease(t)), 1, False)] + [
            (_lerp(f, to, _ease(t - 0.08 * k)), a, False) for k, a in ((1, .45), (2, .25), (3, .12))]
    if kind == "underline":
        x, y, w, h = _lerp(f, to, _ease(t))
        return [((x, y, w, h), 0, False), ((x + 2, y + h - 3, w - 4, 2), 1, True)]
    if kind == "fade":
        e = _ease(t)
        return [(to if e > 0.5 else f, 0, False), (f, 1 - e, False), (to, e, False)]
    if kind == "fill":                  # новый квадрат наливается снизу вверх
        x, y, w, h = to
        e = _ease(t)
        return [(to, 0, False), ((x, y + h * (1 - e), w, h * e), 1, False)]
    if kind == "grow":                  # подсветка вырастает из середины нового квадрата
        x, y, w, h = to
        e = _back(t) if t < 1 else 1
        return [(to, 0, False), ((x + w * (1 - e) / 2, y + h * (1 - e) / 2, w * e, h * e), 1, False)]
    return [(_lerp(f, to, _ease(t)), 1, False)]
NOTE, NOTE_OFF = "\U000f075a", "\U000f075b"
NOTE_AFTER = 4.0                        # поток звучит дольше — тогда нота (короткие звуки уведомлений — нет)
# 1.5 → 4 с (19.10.2026, «нота срабатывает от обычных уведомлений»): Telegram и браузер на звук
# уведомления открывают свой поток и держат его ещё несколько секунд после звука
NOTE_AFTER_MEDIA = 1.5                  # браузеру и музыке — быстрее (19.10.2026, «не сразу появляется»)
NOTE_LINGER = 8.0                       # пауза или конец — нота держится, чтобы успеть нажать
BROWSER_RE = re.compile(r"zen|firefox|librewolf|helium|chrom|brave|vivaldi", re.I)
PIP_TITLES = ("Picture-in-Picture", "Картинка в картинке")    # как pip_place.TITLES
NOTE_SKIP_ROLES = {"event", "notification", "alert"}
NOTE_SKIP_NAMES = {"Звуки интерфейса"}  # ui_sound.py — щелчки и уведомления системы
VOL_STEP = 5
# Колесо над нотой крутит одну программу стола, а не все разом: музыка → Telegram → прочее
# (19.10.2026, просьба: «Telegram + Yandexmusic» общим микшером не надо)
MUSIC_RE = re.compile(r"music|музык|spotify|yandex|deezer|tidal|soundcloud|bandcamp|rhythmbox|"
                      r"strawberry|cmus|mpd|ncmpcpp|amberol|lollypop|tauon|feishin|audacious|"
                      r"clementine|quodlibet|elisa|g4music|ytm", re.I)
CHAT_RE = re.compile(r"telegram|ayugram|64gram|materialgram", re.I)
# окна игр — без ноты: звук игры крутят в самой игре (19.10.2026)
GAME_RE = re.compile(r"^(steam_app_\d+|gamescope|cs2|.*\.exe)$", re.I)
GENERIC_WORDS = {"org", "com", "net", "app", "desktop", "electron", "chromium", "client"}
LAYOUT_STATE = os.path.expanduser("~/.config/hypr/state/ws-layout.json")
LAYOUT_MODES = (("scrolling", "Прокрутка"), ("tiling", "Плитка-сетка"), ("peek", "Подглядывание"),
                ("three", "Три в ряд"), ("stacking", "Плавающие"))       # как MODES/NAMES в ws_layout.py
AUDIO = {"streams": [], "seen": {}, "pend": None, "busy": False, "recheck": None,
         "found": [], "last": {}, "info": {},     # поток → когда последний раз играл, его данные
         "lastvol": {}}         # программа → последняя ненулевая громкость (вернуть с 0 %)


def ws_targets():
    return dnd_targets() + [Gtk.TargetEntry.new(WS_TARGET, Gtk.TargetFlags.SAME_APP, 1)]


OUTPUTS = {}                            # разъём → данные niri (make) — имя монитора в меню


def monitor_name(conn):
    if conn.startswith("eDP"):
        return "Laptop"
    make = (OUTPUTS.get(conn) or {}).get("make") or ""
    return "MSI" if "Microstep" in make or "MSI" in make else conn


def read_streams():
    """[(index, имя, цепочка pid, слова, заглушён, громкость %, на паузе)] — все потоки. Цепочка — pid потока и его предки: звук браузера идёт из вкладки-потомка."""
    import app_volume
    import audio_names
    try:
        out = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True,
                             text=True, timeout=2, env=dict(os.environ, LC_ALL="C.UTF-8")).stdout
        data = json.loads(out or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []
    res = []
    for s in data:
        p = s.get("properties") or {}
        if str(p.get("media.role", "")).lower() in NOTE_SKIP_ROLES or \
                p.get("application.name") in NOTE_SKIP_NAMES:
            continue
        pid = p.get("application.process.id")
        try:
            pid = int(pid) if pid else None
        except ValueError:
            pid = None
        chain = ({pid} | set(app_volume.parents(pid, 8))) if pid else set()
        words = app_volume.words_of(p.get("application.name"), p.get("node.name"),
                                    p.get("application.process.binary")) - GENERIC_WORDS
        vols = [int(str(v.get("value_percent", "0")).rstrip("%") or 0)
                for v in (s.get("volume") or {}).values()]
        res.append((s["index"], audio_names.stream_name(p), chain, words, bool(s.get("mute")),
                    round(sum(vols) / len(vols)) if vols else 0, bool(s.get("corked"))))
    return res


def schedule_streams(delay=250):
    """Событие pactl о потоках — перечитать (одним разом на серию событий)."""
    if AUDIO["pend"] is None:
        AUDIO["pend"] = GLib.timeout_add(delay, _load_streams)
    return False


def _load_streams():
    AUDIO["pend"] = None
    if AUDIO["busy"]:                   # чтение уже идёт — повторить после него
        AUDIO["again"] = True
        return False
    AUDIO["busy"] = True

    def work():
        found = read_streams()
        GLib.idle_add(_apply_streams, found)
    threading.Thread(target=work, daemon=True).start()
    return False


def note_after(name, words):
    text = " ".join([name or ""] + sorted(words))
    return NOTE_AFTER_MEDIA if MUSIC_RE.search(text) or BROWSER_RE.search(text) else NOTE_AFTER


def _apply_streams(found):
    AUDIO["busy"] = False
    AUDIO["found"] = found
    AUDIO["lastvol"].update({f[1]: f[5] for f in found if f[5] > 0})
    _eval_streams()
    if AUDIO.pop("again", False):
        schedule_streams(50)
    return False


def _eval_streams():
    """Кого показывать нотой: играет дольше note_after; после паузы или конца потока —
    ещё NOTE_LINGER (повтор в это время — сразу, без нового ожидания)."""
    now = time.monotonic()
    seen, last, info = AUDIO["seen"], AUDIO["last"], AUDIO["info"]
    playing = {f[0]: f for f in AUDIO["found"] if not f[6]}
    for sid in AUDIO.get("was", set()) - set(playing):     # только что смолк — играл до сих пор
        last[sid] = now
    AUDIO["was"] = set(playing)
    for sid, f in playing.items():
        if sid not in seen:
            seen[sid] = now
        last[sid] = now
        info[sid] = f[:6]
    show, wake = [], []
    for sid in list(seen):
        f = info.get(sid)
        after = note_after(f[1], f[3]) if f else NOTE_AFTER
        if sid in playing:
            if now - seen[sid] >= after:
                show.append(f)
            else:
                wake.append(after - (now - seen[sid]))
            continue
        qualified = last[sid] - seen[sid] >= after
        if qualified and now - last[sid] < NOTE_LINGER:
            cur = next((g for g in AUDIO["found"] if g[0] == sid), None)
            show.append(cur[:6] if cur else f)             # заглушили на паузе — видно сразу
            wake.append(NOTE_LINGER - (now - last[sid]))
            continue
        if not qualified and last[sid] - seen[sid] < 15 and f:
            print("xpbar note: поток %s прожил %.1f с" % (f[1], last[sid] - seen[sid]),
                  file=sys.stderr, flush=True)
        for d in (seen, last, info):
            d.pop(sid, None)
    AUDIO["streams"] = show
    if AUDIO["recheck"] is not None:
        GLib.source_remove(AUDIO["recheck"])
        AUDIO["recheck"] = None
    if wake:
        def recheck():
            AUDIO["recheck"] = None
            _eval_streams()
            return False
        AUDIO["recheck"] = GLib.timeout_add(int(min(wake) * 1000) + 100, recheck)
    for bar in BARS:
        bar.refresh_ws()


def audio_by_ws(windows):
    """стол → [{name, sids, muted, vol}]: кто звучит на каком столе. Поток — к окну по
    дереву процессов, а без pid (Telegram) — по имени приложения. Окон с тем же pid
    несколько (два окна Zen) — к тому, что было в фокусе последним."""
    if not AUDIO["streams"]:
        return {}
    import app_volume
    wins = [w for w in windows.values() if w.get("workspace_id") is not None]

    def ts(w):
        t = w.get("focus_timestamp") or {}
        return (t.get("secs", 0), t.get("nanos", 0))
    out = {}
    playing = {f[0] for f in AUDIO.get("found", ()) if not f[6]}
    for sid, name, chain, words, muted, vol in AUDIO["streams"]:
        cand = [w for w in wins if w.get("pid") in chain]
        if not cand and words:
            cand = [w for w in wins
                    if app_volume.same_app(words, app_volume.words_of(w.get("app_id")) - GENERIC_WORDS)]
        if not cand:
            continue
        # 19.10.2026: окно «картинки в картинке» — того же pid, что браузер. Нота — на
        # главном окне браузера (просьба: «не на картинке в картинке, а в самом браузере»),
        # даже если картинку потом трогали и она была в фокусе позже
        w = max(cand, key=lambda w: ((w.get("title") or "") not in PIP_TITLES, ts(w)))
        if GAME_RE.match(w.get("app_id") or ""):
            continue
        apps = out.setdefault(w["workspace_id"], {})
        a = apps.setdefault(name, {"name": name, "sids": [], "muted": True, "vol": 0, "rank": 9,
                                   "playing": False})
        a["rank"] = min(a["rank"], app_rank(name, w))
        a["playing"] = a["playing"] or sid in playing or not AUDIO.get("found")
        a["sids"].append(sid)
        a["muted"] = a["muted"] and muted
        a["vol"] = max(a["vol"], vol)
    # первым — что играет сейчас (музыка на паузе уступает Telegram), дальше по рангу
    return {ws: sorted(apps.values(), key=lambda a: (not a["playing"], a["rank"], a["name"]))
            for ws, apps in out.items()}


def app_rank(name, win):
    """0 — музыка и видео в браузере, 1 — Telegram, 2 — прочее (19.10.2026: браузер
    наравне с музыкой — Просьба: «в приоритете музыка или видео в браузере, потом телеграм»)."""
    text = " ".join((name or "", win.get("app_id") or "", win.get("title") or ""))
    return 0 if MUSIC_RE.search(text) or BROWSER_RE.search(text) else 1 if CHAT_RE.search(text) else 2


def silent(a):
    """Не слышно: заглушена или громкость 0 % — нота перечёркнута (19.10.2026)."""
    return a["muted"] or a["vol"] == 0


def set_app_mute(apps, mute):
    for a in apps:
        for sid in a["sids"]:
            spawn("pactl", "set-sink-input-mute", str(sid), "1" if mute else "0")
            if not mute and a["vol"] == 0:              # с 0 % — вернуть прежнюю громкость
                spawn("pactl", "set-sink-input-volume", str(sid),
                      "%d%%" % AUDIO["lastvol"].get(a["name"], 50))
        a["muted"] = mute
    schedule_streams(150)


def set_app_volume(apps, step):
    """Колесо над нотой — громкость главной программы стола (apps уже по приоритету);
    заглушённые не трогаем."""
    live = ([a for a in apps if not a["muted"]] or apps)[:1]
    for a in live:
        a["vol"] = max(0, min(100, a["vol"] + step))
        for sid in a["sids"]:
            spawn("pactl", "set-sink-input-volume", str(sid), "%d%%" % a["vol"])
        for s_i, s in enumerate(AUDIO["streams"]):           # следующий щелчок колеса — от нового
            if s[0] in a["sids"]:
                AUDIO["streams"][s_i] = s[:5] + (a["vol"],)
    name = " + ".join(a["name"] for a in live)
    pct = live[0]["vol"]

    def show():
        try:
            import app_volume
            app_volume.osd(name, pct, False, "app")
        except Exception as e:
            print("xpbar: osd: %r" % e, file=sys.stderr)
    threading.Thread(target=show, daemon=True).start()


def layout_of(ws_id):
    try:
        return json.load(open(LAYOUT_STATE)).get(str(ws_id), "scrolling")
    except (OSError, ValueError, AttributeError):
        return "scrolling"


class WsButton(Gtk.Button):
    """Квадрат стола: щелчок — перейти, ПКМ — меню стола, перетащить — на другое место или
    другой монитор; нота — кто здесь звучит (щелчок по ней — заглушить, колесо — громкость).
    plus — квадрат «+» в конце: новый пустой стол."""

    def __init__(self, bar, ws_id, plus=False):
        super().__init__()
        self.bar, self.ws_id, self.plus = bar, ws_id, plus
        ctx = self.get_style_context()
        ctx.add_class("ws")
        if plus:
            ctx.add_class("plus")
            ctx.add_class("empty")
            self.set_tooltip_text("Новый стол — щёлкнуть или бросить сюда окно")
        self.set_relief(Gtk.ReliefStyle.NONE)
        box = Gtk.Box(spacing=2)
        self.lbl = Gtk.Label(label="+" if plus else "")
        self.note = Gtk.Label()
        self.note.get_style_context().add_class("wsnote")
        self.note.set_no_show_all(True)
        self.note.set_valign(Gtk.Align.START)   # выше цифры, значком в углу (19.10.2026)
        box.pack_start(self.lbl, True, True, 0)
        box.pack_start(self.note, False, False, 0)
        self.add(box)
        self.apps = []
        self.dragging = False
        self.drag_t = 0.0
        self.spring = None
        self.connect("button-release-event", self.on_release)
        self.drag_dest_set(0, ws_targets(), Gdk.DragAction.MOVE)
        self.connect("drag-motion", self.on_motion)
        self.connect("drag-leave", self.on_leave)
        self.connect("drag-drop", self.on_drop)
        self.connect("drag-data-received", self.on_data)
        if not plus:
            self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK,
                                 [Gtk.TargetEntry.new(WS_TARGET, Gtk.TargetFlags.SAME_APP, 1)],
                                 Gdk.DragAction.MOVE)
            self.connect("drag-begin", self.on_drag_begin)
            self.connect("drag-data-get", lambda _w, _c, data, *_a:
                         data.set(data.get_target(), 8, str(self.ws_id).encode()))
            self.connect("drag-end", self.on_drag_end)
            self.connect("drag-failed", self.on_drag_failed)

    def target_id(self):
        return self.bar.trailing_ws() if self.plus else self.ws_id

    def set_audio(self, apps):
        self.apps = apps or []
        if not self.apps:
            self.note.hide()
            return
        muted = all(silent(a) for a in self.apps)
        self.note.set_text(NOTE_OFF if muted else NOTE)
        (self.note.get_style_context().add_class if muted
         else self.note.get_style_context().remove_class)("muted")
        self.note.show()
        self.set_tooltip_text("Звучит: " + ", ".join(
            a["name"] + (" (заглушён)" if a["muted"] else " · %d%%" % a["vol"]) for a in self.apps)
            + "\nЩелчок по ноте — %s %s, колесо — громкость %s%s"
            % ("вернуть звук" if silent(self.apps[0]) else "заглушить", self.apps[0]["name"],
               ([a for a in self.apps if not a["muted"]] or self.apps)[0]["name"],
               "\nСредняя кнопка или Shift+щелчок — выбрать программу" if len(self.apps) > 1 else ""))

    # ── щелчки ──
    def on_release(self, _w, e):
        # Стол «не кликался» (19.10.2026): щелчок, отпущенный не над квадратом,
        # или залипший dragging молча терялись. Теперь пишется в журнал, а dragging старше 3 с
        # без drag-end считается залипшим и сбрасывается.
        if self.dragging and time.monotonic() - self.drag_t > 3:
            print("xpbar ws: dragging залип у стола %s — сброшен" % self.ws_id, flush=True)
            self.dragging = False
        if self.dragging:
            return True
        a = self.get_allocation()
        if not (0 <= e.x < a.width and 0 <= e.y < a.height):
            print("xpbar ws: щелчок по столу %s отпущен вне квадрата (%.0f,%.0f из %dx%d)"
                  % (self.ws_id, e.x, e.y, a.width, a.height), flush=True)
            return True
        on_note = self.apps and self.note.get_visible() and self.on_note(e)
        if e.button == 2 and on_note:
            self.note_click(e, pick=True)
        elif e.button == 1:
            if on_note:
                self.note_click(e, pick=bool(e.state & Gdk.ModifierType.SHIFT_MASK))
            elif self.plus:
                wid = self.target_id()
                if wid is not None:
                    self.bar.focus_ws(wid)
            else:
                self.bar.focus_ws(self.ws_id)
        elif e.button == 3 and not self.plus:
            self.bar.ws_menu(self.ws_id, e)
        return True

    def on_note(self, e):
        """Только по самой ноте (+3 px), не по всей высоте плитки: ниже ноты — щелчок по
        столу (19.10.2026, просьба: «хочу перейти на стол, а кликается мьют»)."""
        x, y = self.note.translate_coordinates(self, 0, 0) or (0, 0)
        return (x - 3 <= e.x <= x + self.note.get_allocated_width() + 3
                and y - 3 <= e.y <= y + self.note.get_allocated_height() + 1)

    def note_click(self, e, pick=False):
        """Щелчок — заглушить/вернуть первую по приоритету (apps уже упорядочены: что играет,
        потом музыка/браузер → Telegram → прочее), без окна выбора (19.10.2026). pick —
        список, чтобы выбрать программу самому."""
        ui_click("click")
        if len(self.apps) == 1 or not pick:
            set_app_mute(self.apps[:1], not silent(self.apps[0]))
            return
        items = [pop_item("%s  %s — %s" % (NOTE_OFF if silent(a) else NOTE, a["name"],
                                            "вернуть звук" if silent(a) else "заглушить"),
                          lambda a=a: set_app_mute([a], not silent(a))) for a in self.apps]
        allm = all(silent(a) for a in self.apps)
        items += [POP_SEP, pop_item("Вернуть звук всем" if allm else "Заглушить всё на столе",
                                    lambda: set_app_mute(self.apps, not allm))]
        self.bar.menu(items, self)

    # ── этот квадрат тащат ──
    def on_drag_begin(self, _w, ctx):
        self.dragging = True
        self.drag_t = time.monotonic()
        a = self.get_allocation()
        try:
            import cairo
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, max(1, a.width), max(1, a.height))
            self.draw(cairo.Context(surf))
            Gtk.drag_set_icon_surface(ctx, surf)
        except Exception:
            pass

    def on_drag_end(self, *_a):
        clear_drop()
        GLib.timeout_add(150, lambda: setattr(self, "dragging", False))

    def on_drag_failed(self, _w, _ctx, result):
        """Щелчок с дрожью мыши GTK начинает как перетаскивание квадрата; брошенный никуда
        (обратно на себя) — это щелчок: перейти на стол (19.10.2026)."""
        if result == Gtk.DragResult.NO_TARGET or result == Gtk.DragResult.USER_CANCELLED:
            win = self.get_window()
            seat = Gdk.Display.get_default().get_default_seat()
            pos = win.get_device_position(seat.get_pointer()) if win and seat else None
            a = self.get_allocation()
            if pos and 0 <= pos[1] - a.x < a.width and 0 <= pos[2] - a.y < a.height:
                print("xpbar ws: перетаскивание стола %s на себя — щелчок" % self.ws_id, flush=True)
                self.bar.focus_ws(self.ws_id)
        return False

    # ── на квадрат что-то бросают ──
    def kind(self, ctx):
        t = self.drag_dest_find_target(ctx, None)
        name = t.name() if t else None
        return name if name in (DND_TARGET, WS_TARGET) else None

    def on_motion(self, _w, ctx, _x, _y, time_):
        kind = self.kind(ctx)
        src = Gtk.drag_get_source_widget(ctx)
        if kind is None or src is self:
            Gdk.drag_status(ctx, 0, time_)
            return True
        self.get_style_context().add_class("drop")
        Gdk.drag_status(ctx, Gdk.DragAction.MOVE, time_)
        # окно держат над квадратом — стол открывается, как в macOS (пружинящие папки)
        if kind == DND_TARGET and not self.plus and self.spring is None:
            self.spring = GLib.timeout_add(SPRING_MS, self.on_spring)
        return True

    def on_spring(self):
        self.spring = None
        ws = self.bar.state.workspaces.get(self.ws_id) or {}
        if not ws.get("is_active") or not ws.get("is_focused"):
            self.bar.focus_ws(self.ws_id)
        return False

    def cancel_spring(self):
        if self.spring is not None:
            GLib.source_remove(self.spring)
            self.spring = None

    def on_leave(self, *_a):
        self.get_style_context().remove_class("drop")
        self.cancel_spring()

    def on_drop(self, _w, ctx, _x, _y, time_):
        self.cancel_spring()
        kind = self.kind(ctx)
        if kind is None:
            return False
        self.drag_get_data(ctx, Gdk.Atom.intern(kind, False), time_)
        return True

    def on_data(self, _w, ctx, _x, _y, data, _info, time_):
        self.get_style_context().remove_class("drop")
        try:
            val = int(bytes(data.get_data() or b"").decode())
        except ValueError:
            val = None
        kind = data.get_target().name() if data.get_target() else None
        ok = val is not None
        if ok and kind == DND_TARGET:
            self.bar.move_window(val, self.target_id())
        elif ok and kind == WS_TARGET:
            self.bar.move_ws(val, None if self.plus else self.ws_id)
        Gtk.drag_finish(ctx, ok, False, time_)


def clear_drop():
    for bar in BARS:
        for b in list(bar.ws_buttons.values()) + [bar.ws_plus]:
            if b is not None:
                b.get_style_context().remove_class("drop")
                b.cancel_spring()


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
        self.dragging = False
        self.connect("button-release-event", self.on_release)
        self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, dnd_targets(), Gdk.DragAction.MOVE)
        self.connect("drag-begin", self.on_drag_begin)
        self.connect("drag-data-get", self.on_drag_get)
        self.connect("drag-end", self.on_drag_end)

    def update(self, w):
        app = window_icon_id(w.get("app_id") or "", w.get("title"))
        if app != self.app:
            self.app = app
            self.img.set_from_gicon(app_icon(app), Gtk.IconSize.MENU)
            self.img.set_pixel_size(16)
            self.drag_source_set_icon_gicon(app_icon(app))     # под курсором при переносе
        title = w.get("title") or app or "Окно"
        if title != self.title:
            self.title = title
            self.lbl.set_text(title)
            self.set_tooltip_text(title)
        ctx = self.get_style_context()
        for cls, on in (("focused", w.get("is_focused")), ("urgent", w.get("is_urgent"))):
            (ctx.add_class if on else ctx.remove_class)(cls)

    def on_drag_begin(self, *_a):
        self.dragging = True

    def on_drag_get(self, _w, _ctx, data, _info, _time):
        data.set(data.get_target(), 8, str(self.wid).encode())

    def on_drag_end(self, *_a):
        clear_drop()
        # стол открылся под окном (SPRING_MS) — кнопка ушла из панели, но жила до конца переноса
        if getattr(self, "stale", False):
            GLib.idle_add(self.destroy)
        # отпускание кнопки мыши после переноса — не щелчок по окну
        GLib.timeout_add(150, lambda: setattr(self, "dragging", False))

    def on_release(self, _w, e):
        if self.dragging:
            return True
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
        bar.glyph.queue_draw()


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
SHOWN_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-shown")


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
    # На каких мониторах панель выдвинута и держит место (не «при наведении») — для
    # виджетов на обоях: по Super+S они отодвигаются от панели вместе с окнами
    # (13.10.2026, пользователь). Пишем только при изменении — desktop_widgets следит за файлом.
    outs = sorted(b.connector for b in BARS if getattr(b, "shown_now", False) and b.mode != "hover")
    txt = " ".join(outs) + "\n"
    try:
        if open(SHOWN_FILE).read() == txt:
            return
    except OSError:
        pass
    try:
        with open(SHOWN_FILE + ".tmp", "w") as f:
            f.write(txt)
        os.replace(SHOWN_FILE + ".tmp", SHOWN_FILE)
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
        self.look = bar_look(connector)
        self.get_style_context().add_class("look-" + self.look)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-xpbar")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_monitor(self, monitor)
        for edge in (GtkLayerShell.Edge.BOTTOM, GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, zone_size(LOOK_H.get(self.look, H)) if mode == "always" else 0)
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
            # анимации идут, и окну не бывает нулевой высоты (06.10.2026, просьба: «на
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
        self.wordmark = Gtk.Label(label="staticOS")         # 15.10.2026, просьба: «static на staticOS»
        sb.pack_start(self.wordmark, False, False, 0)
        # вид «Квадратный» (angelOS): искорка вместо логотипа, «staticOS» с ярким «OS» и
        # маленькая «+» сверху справа — как «angelOS⁺» на образце
        self.spark = Sparkle(20, 26)
        self.sq_label = Gtk.Label()
        self.plus = Sparkle(7, 26, small=True)
        self.glyph = StartGlyph()
        sb.pack_start(self.glyph, False, False, 0)
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
        self.wsbox.connect_after("draw", self.draw_slide)
        self.slide = None               # подсветка в пути: {to, x0, w0, t0}
        self.ws_focus = None            # стол в фокусе на этой панели — откуда ехать подсветке
        self.ws_plus = WsButton(self, None, plus=True) if self.ws_here else None
        if self.ws_plus:
            self.wsbox.pack_end(self.ws_plus, False, False, 0)
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
        self.sw.drag_dest_set(Gtk.DestDefaults.ALL, dnd_targets(), Gdk.DragAction.MOVE)
        self.sw.connect("drag-data-received", self.on_tasks_data)
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
        """Кнопка «Пуск»: обычная (логотип + static), квадратная (искорка + staticOS⁺),
        ярлык (квадрат с символом + staticOS) или значок (только символ)."""
        import start_glyphs
        v = start_button_look()
        sq, g = v == "square", start_glyphs.parse(v)
        c = LOOK_COLS.get(self.look) or colors()
        self.sq_label.set_markup('static<span foreground="%s">OS</span>' % c["st_hi"])
        ctx = self.start.get_style_context()
        ctx.remove_class("badge")
        ctx.remove_class("glyphonly")
        if g:
            ctx.add_class("badge" if g[0] == "badge" else "glyphonly")
            self.glyph.set(*g)
        self.start.set_tooltip_text("Пуск — staticOS" if g and g[0] == "icon" else "Пуск")
        for w in (self.logo, self.wordmark):
            w.set_visible(v == "default")
        for w, on in ((self.spark, sq), (self.plus, sq), (self.sq_label, sq or (g and g[0] == "badge")),
                      (self.glyph, bool(g))):
            w.set_visible(bool(on))
            w.queue_draw()

    def apply_look(self):
        """Стиль системы / XP сменили (Настройки, system_style.py set) — на лету."""
        new = bar_look(self.connector)
        if new == self.look:
            return
        wins = [self] + ([self.tray.plate] if self.tray.plate is not None else [])
        for w in wins:
            ctx = w.get_style_context()
            ctx.remove_class("look-" + self.look)
            ctx.add_class("look-" + new)
        self.look = new
        if self.mode == "always" and getattr(self, "shown_now", False):
            GtkLayerShell.set_exclusive_zone(self, zone_size(LOOK_H.get(new, H)))
        self.apply_start_look()
        self.queue_draw()

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
            GtkLayerShell.set_exclusive_zone(self, zone_size(LOOK_H.get(self.look, H)))
            self.show()

            def slide_in():
                if self.get_visible() and not self.rev.get_reveal_child():
                    self.rev.set_transition_duration(180)
                    self.rev.set_reveal_child(True)
                return False
            GLib.timeout_add(40, slide_in)
        else:
            # Панель уходит — уходит и её «Пуск» (13.10.2026, просьба: открыл Super+S
            # панель, Super — «Пуск», снова Super+S — панель спряталась, а меню
            # осталось, и Super его уже не закрывал: super_tap шлёт сигнал только
            # видимой панели).
            m = MENUS.get(self.connector)
            if m is not None and m.get_visible():
                m.quit()
            # уезжает вниз с анимацией; окно прячет on_revealed, когда она закончится
            GtkLayerShell.set_exclusive_zone(self, 0)
            self.rev.set_transition_duration(180)
            self.rev.set_reveal_child(False)
        self.play(on)

    def flush(self, on):
        """«При наведении»: пока панель показана, окно опущено на 2 px за край экрана —
        полоска-датчик под панелью уходит за край, и между панелью и краем не видно
        обоев (06.10.2026, просьба: «маленький зазор, где виднеется часть обоев»)."""
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
        focus = next((w["id"] for w in wss if w.get("is_focused")), None)
        # откуда ехать — замерить до уборки квадратов: пустой стол, с которого ушли, исчезает
        frm = self.box_of(self.ws_buttons.get(self.ws_focus)) if focus != self.ws_focus else None
        for wid in list(self.ws_buttons):
            if wid not in ids:
                b = self.ws_buttons.pop(wid)
                if b.dragging:              # квадрат ещё тащат (уехал на другой монитор)
                    b.hide()
                    GLib.timeout_add(3000, lambda b=b: b.destroy() or False)
                else:
                    b.destroy()
        audio = audio_by_ws(self.state.windows)
        urgent = {w.get("workspace_id") for w in self.state.windows.values() if w.get("is_urgent")} | \
            {w["id"] for w in wss if w.get("is_urgent")}
        slide_to = None
        if focus != self.ws_focus:
            slide_to = focus
            self.ws_focus = focus
        for w in wss:
            b = self.ws_buttons.get(w["id"])
            if b is None:
                b = self.ws_buttons[w["id"]] = WsButton(self, w["id"])
                self.wsbox.pack_start(b, False, False, 0)
                b.show_all()
            # подпись — имя без невидимых меток служб (значок) или номер стола
            label = (w.get("name") or "").replace("​", "").replace("⁠", "") or str(w.get("idx"))
            if b.lbl.get_text() != label:
                b.lbl.set_text(label)
            b.set_audio(audio.get(w["id"]))
            if not b.apps and b.get_tooltip_text():
                b.set_tooltip_text(None)
            sliding = (self.slide is not None and self.slide["to"] == w["id"]) or \
                (w["id"] == slide_to and frm is not None)
            ctx = b.get_style_context()
            for cls, on in (("active", w.get("is_active")),
                            ("focused", w.get("is_focused") and not sliding),
                            ("empty", w.get("active_window_id") is None),
                            ("urgent", w["id"] in urgent and not w.get("is_focused"))):
                (ctx.add_class if on else ctx.remove_class)(cls)
        if ids != self.ws_order:
            self.ws_order = ids
            for i, wid in enumerate(ids):
                self.wsbox.reorder_child(self.ws_buttons[wid], i)
        # после квадратов: новый стол («+», окно на «+») получает квадрат только сейчас —
        # раньше подсветка искала его до создания и не ехала (19.10.2026)
        if slide_to is not None:
            self.start_slide(frm, slide_to)
            if self.slide is None:              # ехать не вышло — подсветка сразу на месте
                self.ws_buttons[slide_to].get_style_context().add_class("focused")

    # ── подсветка переезжает к новому квадрату ──
    def box_of(self, b):
        """Рамка квадрата внутри wsbox — без отступов CSS (они входят в allocation)."""
        if b is None or not b.get_mapped():
            return None
        a = b.get_allocation()
        if a.width <= 1:                        # только что создан — места ещё нет
            return None
        xy = b.translate_coordinates(self.wsbox, 0, 0)
        if not xy:
            return None
        ctx = b.get_style_context()
        m = ctx.get_margin(ctx.get_state())
        return (xy[0] + m.left, xy[1] + m.top, a.width - m.left - m.right, a.height - m.top - m.bottom)

    def start_slide(self, frm, new):
        """frm — рамка, откуда ехать (box_of прежнего квадрата); квадрат new может быть ещё
        без места — slide_tick ждёт его до SLIDE_WAIT кадров."""
        if self.slide and self.slide.get("cur"):
            frm = self.slide["cur"]             # смена посреди пути — ехать от того места
        kind = ws_anim()
        if kind == "off" or frm is None or new is None or self.ws_buttons.get(new) is None:
            if self.slide:
                self.slide = None
                self.wsbox.queue_draw()
            return
        first = self.slide is None
        self.slide = {"to": new, "from": frm, "cur": frm, "t0": None, "wait": 0, "kind": kind,
                      "rects": [(frm, 1, False)]}
        if first:
            self.wsbox.add_tick_callback(self.slide_tick)

    def slide_tick(self, _w, clock):
        s = self.slide
        if s is None:
            return False
        now = clock.get_frame_time() / 1000.0
        to = self.box_of(self.ws_buttons.get(s["to"]))
        if to is None and s["t0"] is None and s["wait"] < SLIDE_WAIT and s["to"] in self.ws_buttons:
            s["wait"] += 1                      # новый квадрат ещё раскладывается
            self.wsbox.queue_draw()
            return True
        if s["t0"] is None:
            s["t0"] = now
        t = min(1.0, (now - s["t0"]) / slide_ms(s["kind"], s["from"], to or s["from"]))
        if to is None or t >= 1.0:
            self.slide = None
            self.refresh_ws()                   # квадрат приехал — ему класс focused
            self.wsbox.queue_draw()
            return False
        s["rects"] = slide_rects(s["kind"], s["from"], to, t)
        s["cur"] = s["rects"][0][0]
        self.wsbox.queue_draw()
        return True

    def draw_slide(self, _w, cr):
        """Рамка акцентом поверх квадратов, пока подсветка в пути (координаты — от wsbox)."""
        s = self.slide
        if not s or not s.get("cur"):
            return False
        col, rad = WS_ACC.get(self.look) or WS_ACC.get("xp") or ("#ffffff", 3)
        rgba = Gdk.RGBA()
        rgba.parse(col)
        cr.save()
        # фигуры одной прозрачности — одним контуром: слившиеся (Капля) без тёмных наложений
        groups = []
        for shape, alpha, kind in reversed(s.get("rects") or [(s["cur"], 1, False)]):
            if alpha <= 0.01:
                continue
            if kind is True:
                x, y, ww, hh = shape
                cr.rectangle(x, y, ww, hh)
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.95 * alpha)
                cr.fill()
                continue
            if kind != "poly" and (shape[2] < 1 or shape[3] < 1):
                continue
            if groups and groups[-1][0] == alpha:
                groups[-1][1].append((shape, kind))
            else:
                groups.append((alpha, [(shape, kind)]))
        for alpha, shapes in groups:
            cr.new_path()
            for shape, kind in shapes:
                if kind == "poly":
                    cr.move_to(*shape[0])
                    for pt in shape[1:]:
                        cr.line_to(*pt)
                    cr.close_path()
                    continue
                x, y, ww, hh = shape
                r = min(rad, ww / 2, hh / 2)
                cr.new_sub_path()
                cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0)
                cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2)
                cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi)
                cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
                cr.close_path()
            cr.set_fill_rule(cairo.FILL_RULE_WINDING)
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.55 * alpha)
            if len(shapes) > 1:
                cr.fill()
                continue
            cr.fill_preserve()
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.95 * alpha)
            cr.set_line_width(1)
            cr.stroke()
        cr.restore()
        return False

    # ── действия со столами ──
    def trailing_ws(self):
        """Пустой стол в конце монитора — niri держит его всегда; на него ведёт «+»."""
        mine = sorted((w for w in self.state.workspaces.values() if w.get("output") == self.connector),
                      key=lambda w: w.get("idx", 0))
        if mine and mine[-1].get("active_window_id") is None and not mine[-1].get("name"):
            return mine[-1]["id"]
        return None

    def move_window(self, wid, ws_id):
        if ws_id is None:
            return
        ui_click("click")
        ws = self.state.workspaces.get(ws_id) or {}
        # бросили на стол, который сейчас перед глазами (открылся под окном) — фокус за окном
        niri_request({"Action": {"MoveWindowToWorkspace": {
            "window_id": wid, "reference": {"Id": ws_id},
            "focus": bool(ws.get("is_active") and ws.get("is_focused"))}}})

    def on_tasks_data(self, _w, ctx, _x, _y, data, _info, time_):
        """Окно бросили на полосу окон — на стол, что открыт на этом мониторе."""
        try:
            wid = int(bytes(data.get_data() or b"").decode())
        except ValueError:
            return
        act = next((w["id"] for w in self.state.workspaces.values()
                    if w.get("output") == self.connector and w.get("is_active")), None)
        win = self.state.windows.get(wid) or {}
        if act is not None and win.get("workspace_id") != act:
            self.move_window(wid, act)

    def move_ws(self, src, dst):
        """Квадрат src бросили на квадрат dst (None — на «+»): на его место, а если dst на
        другом мониторе — стол уезжает туда."""
        s = self.state.workspaces.get(src)
        if not s or src == dst:
            return
        ui_click("click")
        if dst is None:
            t = self.state.workspaces.get(self.trailing_ws()) or {}
            idx = t.get("idx")
            if idx and s.get("output") == self.connector:
                idx -= 1                       # пустой стол в конце остаётся последним
        else:
            idx = (self.state.workspaces.get(dst) or {}).get("idx")
        if s.get("output") != self.connector:
            niri_request({"Action": {"MoveWorkspaceToMonitor": {
                "output": self.connector, "reference": {"Id": src}}}})
        if idx:
            niri_request({"Action": {"MoveWorkspaceToIndex": {"index": idx, "reference": {"Id": src}}}})

    def ws_windows(self, ws_id):
        return [w for w in self.state.windows.values() if w.get("workspace_id") == ws_id
                and not (w.get("app_id") or "").startswith(HIDDEN_APPS)]

    def ws_menu(self, ws_id, e):
        ws = self.state.workspaces.get(ws_id) or {}
        cur = layout_of(ws_id)
        lays = [pop_item("%d  %s" % (i + 1, name), mark=mode == cur,
                         cb=None if mode == cur else lambda md=mode: self.set_layout(ws_id, md))
                for i, (mode, name) in enumerate(LAYOUT_MODES)]
        items = [pop_title("Стол %s" % ws.get("idx", "?")), pop_item("Раскладка", sub=lays)]
        others = sorted({w.get("output") for w in self.state.workspaces.values()} - {ws.get("output"), None})
        for out in others:
            items.append(pop_item("Перенести на %s" % monitor_name(out),
                                  lambda o=out: niri_request({"Action": {"MoveWorkspaceToMonitor": {
                                      "output": o, "reference": {"Id": ws_id}}}})))
        wins = self.ws_windows(ws_id)
        here = next((w for w in self.state.workspaces.values() if w.get("is_focused")), None)
        ok = bool(wins) and here is not None and here["id"] != ws_id
        # окна этого стола переедут на стол, где Вы сейчас
        items.append(pop_item("Собрать окна сюда (%d)" % len(wins), on=ok,
                              cb=lambda: [niri_request({"Action": {"MoveWindowToWorkspace": {
                                  "window_id": w["id"], "reference": {"Id": here["id"]},
                                  "focus": False}}}) for w in wins]))
        items += [POP_SEP, pop_item("Закрыть все окна (%d)" % len(wins), on=bool(wins), sub=[
            pop_item("Да, закрыть %d" % len(wins),
                     lambda: [action("close-window", "--id", str(w["id"])) for w in wins]),
            pop_item("Отмена", back=True)])]
        self.menu(items, self.ws_buttons.get(ws_id))

    def menu(self, items, widget=None):
        """Плашка-меню над панелью: левым краем к widget, без него — к курсору."""
        x = None
        if widget is not None and widget.get_mapped():
            xy = widget.translate_coordinates(self, 0, 0)
            x = xy[0] if xy else None
        BarPopup(self, items, x)

    def set_layout(self, ws_id, mode):
        """ws_layout.py меняет раскладку стола в фокусе — сперва открыть нужный стол."""
        niri_request({"Action": {"FocusWorkspace": {"reference": {"Id": ws_id}}}})
        spawn(sys.executable, os.path.join(HERE, "ws_layout.py"), "set", mode)

    def focus_ws(self, ws_id):
        ui_click("click")
        reply = niri_request({"Action": {"FocusWorkspace": {"reference": {"Id": ws_id}}}}) or ""
        if "Ok" not in reply:            # журнал для «стол не кликается» (19.10.2026)
            print("xpbar ws: переход на стол %s не вышел: %s" % (ws_id, reply.strip()[:200]), flush=True)

    def ws_under(self, x):
        for wid in self.ws_order:
            b = self.ws_buttons.get(wid)
            xy = b.translate_coordinates(self.ws_ev, 0, 0) if b and b.get_mapped() else None
            if xy and xy[0] <= x < xy[0] + b.get_allocated_width():
                return b
        return None

    def on_ws_scroll(self, _w, e):
        """Колесо над столами — соседний стол этого монитора; над квадратом с нотой —
        громкость того, что звучит на столе; с Shift — окно в фокусе на соседний стол."""
        d = 0
        if e.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
            d = -1
        elif e.direction in (Gdk.ScrollDirection.DOWN, Gdk.ScrollDirection.RIGHT):
            d = 1
        elif e.direction == Gdk.ScrollDirection.SMOOTH:
            ok, dx, dy = e.get_scroll_deltas()
            v = dy if abs(dy) >= abs(dx) else dx       # Shift+колесо часто приходит как dx
            d = (1 if v > 0 else -1) if ok and abs(v) >= 0.5 else 0
        if not d:
            return True
        if e.state & Gdk.ModifierType.SHIFT_MASK or shift_held():
            action("move-window-to-workspace-down" if d > 0 else "move-window-to-workspace-up")
            return True
        x = e.x
        src = Gtk.get_event_widget(e)           # get_user_data() в PyGObject — число, не виджет
        if src is not None and src is not self.ws_ev:   # событие пришло окну квадрата
            x = (src.translate_coordinates(self.ws_ev, int(e.x), 0) or (x, 0))[0]
        b = self.ws_under(x)
        if b is not None and b.apps:
            set_app_volume(b.apps, -d * VOL_STEP)
            return True
        ids = self.ws_order
        cur = next((i for i, wid in enumerate(ids)
                    if (self.state.workspaces.get(wid) or {}).get("is_active")), None)
        if cur is not None and 0 <= cur + d < len(ids):
            niri_request({"Action": {"FocusWorkspace": {"reference": {"Id": ids[cur + d]}}}})
        return True

    def refresh(self):
        self.refresh_ws()
        wins = self.state.windows_on(self.connector)
        ids = [w["id"] for w in wins]
        for wid in list(self.buttons):
            if wid not in ids:
                b = self.buttons.pop(wid)
                if b.dragging:          # окно ещё тащат (стол открылся под ним) — убрать после
                    b.stale = True
                    b.hide()
                else:
                    b.destroy()
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
        w = self.state.windows.get(wid) or {}

        def item(label, *act):
            return pop_item(label, lambda: action(*act))
        self.menu([item("Перейти", "focus-window", "--id", str(wid)),
                   item("Во весь экран", "fullscreen-window", "--id", str(wid)),
                   item("В ленту" if w.get("is_floating") else "Плавающее", "toggle-window-floating",
                        "--id", str(wid)),
                   POP_SEP,
                   item("Закрыть", "close-window", "--id", str(wid))])

    def on_start(self, _w, e):
        if e.button == 1:
            # Меню «Пуск» в духе XP — живёт в этом же процессе, построено заранее.
            toggle_menu(self.connector)
        elif e.button == 3:
            items = []
            for label, cmd in (("Программы", [os.path.expanduser("~/.config/niri/scripts/shell-do"), "launcher"]),
                               ("Настройки", [sys.executable, os.path.join(HERE, "settings_app.py")]),
                               ("Экранное время", [sys.executable, os.path.join(HERE, "screentime.py")]),
                               ("Заблокировать", [os.path.join(HERE, "lockscreen")])):
                items.append(pop_item(label, lambda c=cmd: spawn(*c)))
            self.menu(items, self.start)
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
    OUTPUTS.update(outs)
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

    pan_box = [pan]                  # SIGHUP (reload) подменяет выбор, не перезапуская процесс

    def mode_for(conn):
        if panels is None:
            return mode
        try:
            return panels.bottom_for(conn, pan_box[0]) or mode
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
                    if "on sink-input" in line:      # кто звучит — ноты на квадратах столов
                        GLib.idle_add(schedule_streams)
                p.wait()
            except OSError:
                pass
            time.sleep(3)
    AUDIO_REFRESH[0] = lambda: (apply_volume(), False)[1]
    apply_volume()
    schedule_streams(400)
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
    # Смотрим и vivid.txt: skeet берёт акцент оттуда, а theme_changer.sh пишет его позже
    # colors.json — опрос между ними оставил бы старый акцент до следующих обоев (15.10.2026).
    vivid_file = os.path.join(os.path.dirname(PALETTE_FILE), "vivid.txt")

    def stamp():
        return tuple(os.stat(f).st_mtime if os.path.exists(f) else 0 for f in (PALETTE_FILE, vivid_file))
    last = {"m": stamp()}

    def check_palette():
        m = stamp()
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
        if paths & {BAR_LOOK_FILE, SYS_STYLE_FILE, SETTINGS_MODE_FILE}:
            if SETTINGS_MODE_FILE in paths or SYS_STYLE_FILE in paths:
                load_css()                  # beta Light/Dark — другие цвета
            for b in bars:
                b.apply_look()
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
    # 19.10.2026, просьба: «на мониторе без нижней панели нажимаю Super — открывается Пуск,
    # и с ним ничего не сделать, только открыть и закрыть». toggle_menu без своей панели брал
    # BARS[0] — меню другого монитора, а клавиатура оставалась здесь. Теперь открытое меню
    # Super закрывает где угодно, а открывает — только если панель этого монитора на экране.
    def on_usr2():
        out = next((w.get("output") for w in state.workspaces.values() if w.get("is_focused")), "")
        if any(m.get_visible() for m in MENUS.values()):
            close_menus()
            return True
        if any(b.connector == out and getattr(b, "shown_now", False) for b in bars):
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
    # SIGHUP — `xpbar.py reload` (panels.py apply): перечитать panels.json; панель монитора,
    # где режим или место столов другие, убрать — sync_bars создаст её заново. Остальные
    # панели не трогаются (16.10.2026).
    def on_hup():
        if panels is None:
            return True
        try:
            pan_box[0] = panels.load()
        except Exception:
            return True
        for b in list(bars):
            if mode_for(b.connector) == b.mode and _ws_here(b.connector) == b.ws_here:
                continue
            m = MENUS.pop(b.connector, None)
            if m is not None:
                m.destroy()
            bars.remove(b)
            if b in BARS:
                BARS.remove(b)
            b.destroy()
        sync_bars()
        return True
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGHUP, on_hup)
    try:
        with open(RELOAD_PID + ".tmp", "w") as f:
            f.write("%d\n" % os.getpid())
        os.replace(RELOAD_PID + ".tmp", RELOAD_PID)
    except OSError:
        pass

    def on_usr1():
        targets = bars
        if panels is not None and panels.per_monitor(pan_box[0]):
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
