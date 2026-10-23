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
SAVAGE_BLUE = "#5cc8ff"     # «Энергия» при Savage Mode (power max) — голубой
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
gi.require_version("PangoCairo", "1.0")
from gi.repository import PangoCairo  # noqa: E402

import popup_theme  # noqa: E402
import pixel_recolor  # noqa: E402
import lyrics_bar as LB  # noqa: E402
import nvim_lang  # noqa: E402
from PIL import Image  # noqa: E402

H = 32                   # высота панели, как у верхнего бара
TASK_W = 136             # ширина кнопки окна — наибольшая (было 176; 05.10.2026, просьба: «чтобы больше вмещалось»)
TASK_MIN = 90            # окон много — кнопки сжимаются до этой ширины, дальше прокрутка (было 110)
GLUE_SHOW = 4            # «вплотную»: сколько пикселей нижней рамки окна видно над панелью (2 → 4, 04.10.2026: «рамки вообще не вижу»)
LYR_W = 470              # место под текст песни справа — постоянное, панель не пляшет
ISLAND_LYR_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-island-lyrics")
ISLAND_LYR = set()       # мониторы, где строку песни сейчас показывает островок
BARS_KEEP = []           # живые Gio-мониторы файлов (иначе их соберёт сборщик мусора)
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
    border-radius: 3px; box-shadow: none; padding: 0; margin: 4px 1px 3px 1px;
    min-height: 0; min-width: 20px; color: %(text)s;
}
button.ws label { font-family: "JarvisBarIcons", "JetBrainsMono Nerd Font", %(font)s; font-size: 16px; font-weight: normal; }
button.ws:hover { background-image: linear-gradient(to bottom, %(t_hover_top)s, %(t_hover_bot)s); border-color: %(t_border)s; }
button.ws.active {
    background-image: linear-gradient(to bottom, %(f_top)s, %(f_bot)s);
    border-color: %(f_border)s; box-shadow: inset 1px 1px 2px alpha(black, 0.6);
}
button.ws.empty { color: alpha(%(text)s, 0.5); }
button.ws label.wslbl { padding: 0 5px; min-width: 20px; }   /* поле — у значка, не у кнопки: нота встаёт на него (21.10.2026) */
button.ws label.wsnote { font-size: 9px; opacity: 0.7; }   /* в углу квадрата — WsButton.note_pos; 0.7 — «чуть тусклее» (21.10.2026) */
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
/* Значок провода у JetBrainsMono NF шире своей ячейки (17 px против 8) — без запаса справа
   окно EventBox срезало правую половину (22.10.2026, просьба: «села не полностью»). */
.tray label.lan { font-size: 12px; padding: 0 6px 0 4px; }
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
button.xppop-item.accent label { color: %(primary)s; }   /* «Вернуть звук» при заглушённом (21.10.2026) */
.xppop label.xppop-title { font-family: %(font12)s; font-size: 12px; color: %(dim)s; padding: 0 7px 1px 7px; }
.xppop .xppop-sep { min-height: 1px; background-color: alpha(%(text)s, 0.2); margin: 1px 3px; }
menu, .menu, .context-menu {
    background-color: %(surface)s; color: %(on_surface)s;
    border: 2px solid %(primary)s; border-radius: 8px; padding: 4px;
}
menuitem { font-family: %(font)s; font-size: 16px; padding: 5px 12px; border-radius: 5px; }
menuitem:hover { background-color: %(surface_high)s; color: %(primary)s; }
tooltip { background-color: %(surface)s; color: %(on_surface)s; border: 1px solid %(primary)s; border-radius: 6px; }
tooltip label { font-family: %(font12)s; font-size: 12px; font-weight: normal; }   /* 12 px, как меню (21.10.2026); поля подсказок — в gtk_live_colors.py TOOLTIP: gtk.css (USER) перебивает стили панели */
"""

_provider = None


# Вид кнопки «Пуск» (03.10.2026, `start_menu.py button default|square`): square —
# прямоугольный блок с пиксельной рамкой без скругления, по образцу панели angelOS.
# Высота та же: рамка 1 px + внутренняя линия тенью, поля 1 px — под логотип 26 px
# (поля 2 px раздували панель на 1–2 px).
START_BUTTON_FILE = os.path.expanduser("~/.config/hypr/state/start-button-look")
# надпись на «Пуске»: staticOS (по умолчанию) | start — «Start» (23.10.2026, пользователь)
START_WORD_FILE = os.path.expanduser("~/.config/hypr/state/start-button-word")


def start_word():
    try:
        return "start" if open(START_WORD_FILE).read().strip() == "start" else "staticos"
    except OSError:
        return "staticos"
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


def attn_color(acc, bg):
    """Цвет «стол просит внимания» (20.10.2026, просьба: «покрась в более жёлто-оранжевый
    кислотный, но не ярко, скорее тусклее, и чтобы сочеталось с гаммой обоев»).
    Оттенок свой — жёлто-оранжевый 45°, а светлота и насыщенность берутся у акцента
    обоев; чуть подмешан сам акцент и фон панели — так цвет и тусклый, и «из той же семьи»."""
    import colorsys
    _h, l, sat = colorsys.rgb_to_hls(*hex2rgb(acc))
    l = min(max(l, 0.5), 0.6)
    sat = min(max(sat * 0.75 + 0.2, 0.85), 1.0)
    pure = rgb2hex(colorsys.hls_to_rgb(45 / 360, l, sat))
    return mix(mix(pure, acc, 0.06), bg, 0.2)


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
    box-shadow: inset 1px 1px 0 alpha(black, 0.55), inset 0 0 0 1px %(line3)s, inset 0 -2px %(acc)s;
    color: %(acc_l)s;
}
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
%(T)s button.xppop-item.current label, %(T)s button.xppop-item.accent label { color: %(acc)s; }
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
    box-shadow: inset 1px 1px 0 alpha(black, 0.35); color: %(sel_text)s;
}
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
%(T)s button.xppop-item.current label, %(T)s button.xppop-item.accent label,
%(T)s button.xppop-item label.xppop-side { color: %(acc)s; }
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
    box-shadow: inset 1px 1px 2px alpha(black, 0.45), inset 0 -2px %(primary)s; color: %(primary)s;
}
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
%(T)s button.xppop-item.accent label, %(T)s button.xppop-item label.xppop-side { color: %(primary)s; }
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
                      lang_line=sk["line1"], lang_in=sk["line3"], lang_text=sk["acc_l"], radius=0, dim=sk["dim"]),
        "beta": dict(acc=be["acc"], bg=be["bar"], st_hi=be["acc"], grip=be["line"], grip_d=None, lang_bg=be["field"],
                     lang_line=be["line_strong"], lang_in=None, lang_text=be["text"], radius=0, dim=be["dim"]),
        "dark": dict(acc=p["primary"], bg=c["base"], st_hi=p["primary"], grip=dk["line"], grip_d=None, lang_bg=p["surface_high"],
                     lang_line=None, lang_in=None, lang_text=p["on_surface"], radius=4, dim=dk["dim"]),
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
    try:                                        # @vivid waybar — sensor_colors.py
        vivid = re.search(r"@define-color vivid (#[0-9a-fA-F]{6})", open(os.path.expanduser(
            "~/.cache/matugen/sensor-colors.css")).read()).group(1)
    except (OSError, AttributeError):
        vivid = c["primary"]
    for sel, col in [("window", c["st_hi"])] + [("window.xpbar-win.look-" + k, v["acc"])
                                                for k, v in LOOK_COLS.items()]:
        # левая группа centered (SideTray): без кромки трея; Savage — подсветка, как в waybar
        css += ("%(s)s .tray.side { border-left: none; box-shadow: none; background-image: none; "
                "background-color: transparent; }\n"
                "%(s)s .tray label.bat.savage { color: %(c)s; text-shadow: 0 0 6px %(c)s; }\n"
                "%(s)s .tray label.bat.awake { text-shadow: 0 0 2px %(c)s, 0 0 5px %(c)s, "
                "0 0 6px alpha(%(c)s, 0.8); }\n"
                # помидор — цвета модуля custom/pomo в waybar (style.css, «без таблеток»)
                # обычный вид — серый, как помидор рядом; «Не отключать экран» — акцент со
                # свечением, Savage — светлее акцента и свечение сильнее (22.10.2026, просьба:
                # «плохо различаю, он включен или нет… в базовом цвет как у pomo»)
                # в правом трее — акцентом, как соседние значки (22.10.2026, просьба: «иконку
                # энергии тоже покрась в акцент»); цвет даёт .tray label.glyph вида
                "%(s)s .tray label.bat { font-size: 18px; }\n"
                "%(s)s .tray label.bat.awake { color: %(c)s; }\n"
                "%(s)s .tray label.bat.savage { color: mix(%(c)s, white, 0.35); "
                "text-shadow: 0 0 3px %(c)s, 0 0 7px %(c)s, 0 0 10px alpha(%(c)s, 0.9); }\n"
                # новый Savage Mode (power max, savage_power.py) — голубой поверх кофеина
                # (22.10.2026, просьба: «иконка Энергии в панели должна перекрашиваться в голубой»)
                "%(s)s .tray label.bat.power { color: %(b)s; "
                "text-shadow: 0 0 3px alpha(%(b)s, 0.7), 0 0 6px alpha(%(b)s, 0.5); }\n"
                "%(s)s .tray label.bat.power.savage { "
                "text-shadow: 0 0 3px %(b)s, 0 0 7px %(b)s, 0 0 10px alpha(%(b)s, 0.9); }\n"
                "%(s)s .tray.side label.pomo { font-family: %(f)s; font-size: 13px; font-weight: 800; "
                "color: %(v)s; }\n"
                "%(s)s .tray.side label.pomo-break, %(s)s .tray.side label.pomo-focus { color: %(p)s; }\n"
                "%(s)s .tray.side label.pomo-paused { color: alpha(%(t)s, 0.55); }\n"
                "%(s)s .tray.side label.pomo-idle { color: alpha(%(t)s, 0.35); }\n"
                % dict(s=sel, c=col, f=FONT12, v=vivid, p=c["primary"], t=c["on_surface"],
                       b=SAVAGE_BLUE))
        css += ("%(s)s button.ws.drop, %(s)s button.ws.drop.focused, %(s)s button.ws.drop.empty, "
                "%(s)s button.ws.drop.focused.empty { border-color: %(c)s; "
                "box-shadow: inset 0 0 0 2px %(c)s; }\n" % dict(s=sel, c=col))
    # стопка: закреплённое — значок без названия; без окон — без рамки, рамка только под мышью
    for sel in ["window"] + ["window.xpbar-win.look-" + k for k in LOOK_COLS]:
        css += ("%(s)s button.task.pinned { padding: 0 6px; }\n"
                "%(s)s button.task.launcher:not(:hover) { background-color: transparent; "
                "background-image: none; border-color: transparent; box-shadow: none; }\n" % dict(s=sel))
    # стопка, вид centered: кнопки-значки без отступов; «Пуск» — плоский значок, как окна
    for sel in ["window.xpbar-win"] + ["window.xpbar-win.look-" + k for k in LOOK_COLS]:
        css += ("%(s)s button.task.compact { padding: 0; }\n"
                # окно в фокусе — мягкая подложка без рамки и черты: черту рисует draw_run_mark
                "%(s)s button.task.compact.focused { background-image: none; "
                "background-color: alpha(white, 0.14); border-color: transparent; box-shadow: none; "
                "border-radius: 0; }\n"
                "%(s)s button.task.compact:hover { background-image: none; "
                "background-color: alpha(white, 0.09); border-color: transparent; box-shadow: none; "
                "border-radius: 0; }\n"
                "%(s)s button.task.compact.focused:hover { background-color: alpha(white, 0.18); }\n"
                "%(s)s button.task.compact:not(.focused):not(:hover) { background-color: transparent; "
                "background-image: none; border-color: transparent; box-shadow: none; }\n"
                "%(s)s button.start.compact, %(s)s button.start.compact:hover, %(s)s button.start.compact.open, "
                "%(s)s button.start.compact.open:hover, %(s)s button.start.compact.open:active { "
                "background-color: transparent; background-image: none; border-color: transparent; "
                "box-shadow: none; border-radius: 4px; padding: 0 8px; margin: 0 2px 0 0; }\n"
                "%(s)s button.start.compact:hover { background-color: alpha(white, 0.10); }\n"
                "%(s)s button.start.compact.open, %(s)s button.start.compact.open:hover { "
                "background-color: alpha(white, 0.18); }\n" % dict(s=sel))
    # 19.10.2026: окно просит внимания — квадрат стола трижды мягко вспыхивает акцентом и
    # остаётся с тонкой чертой снизу; нота — кто на столе звучит (тусклая — заглушён)
    WS_ACC.clear()
    WS_ACC.update({"xp": (c["st_hi"], 3)})
    WS_ACC.update({k: (v["acc"], v.get("radius", 0)) for k, v in LOOK_COLS.items()})
    # 20.10.2026: стол, что просит внимания, — свой жёлто-оранжевый (attn_color), а не акцент:
    # акцентом уже подчёркнут текущий стол, и их было не различить
    for key, sel in [("xp", "window")] + [(k, "window.xpbar-win.look-" + k) for k in LOOK_COLS]:
        bg = c["base"] if key == "xp" else LOOK_COLS[key]["bg"]
        ink = c["text"] if key == "xp" else LOOK_COLS[key]["dim"]     # цвет неактивных столов
        # 20.10.2026, вторая правка: заливка и рамка «слишком бросались в глаза» — квадрат не
        # красится вовсе; цветом горит только значок стола, а черта снизу — едва заметная
        # третья–пятая правки: «всё равно заметно… ближе к цвету остальных неактивных столов» —
        # значок цвета неактивных столов с жёлто-оранжевым оттенком (40 %)
        css += ("%(s)s button.ws.urgent label { color: %(d)s; }\n"
                "%(s)s button.ws.urgent { box-shadow: inset 0 -2px alpha(%(a)s, 0.25); }\n"
                "%(s)s button.ws label.wsnote { color: %(c)s; }\n"
                "%(s)s button.ws label.wsnote.muted { color: alpha(%(c)s, 0.45); }\n"
                "%(s)s button.ws.focused label.wsnote { color: inherit; }\n"
                % dict(k=key, s=sel, c=WS_ACC[key][0], a=attn_color(WS_ACC[key][0], bg),
                       d=mix(attn_color(WS_ACC[key][0], bg), ink, 0.6)))
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


def _pomo_locked():
    """Помидор «programming» — окна не закрываются (pomo_lock.py, 20.10.2026)."""
    try:
        import pomo_lock
        return pomo_lock.locked() is not None
    except Exception:
        return False


# Режим «стопка» (stack_mode.py, Ctrl+Shift+Super+M, 20.10.2026): свёрнутые окна живут на
# столе с этим именем; их кнопки остаются на панели бледными, щелчок возвращает окно,
# щелчок по кнопке окна в фокусе — сворачивает (как в XP).
STACK_MIN_DESK = "\U000f05b0"         # у второго монитора — с \u2060 в конце (имена столов уникальны)


def stack_min(name):
    return (name or "").rstrip("\u2060") == STACK_MIN_DESK
STACK_MODE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stack_mode.py")


def stack_cmd(*args):
    subprocess.Popen([sys.executable, STACK_MODE, *args], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def stack_on():
    try:
        st = json.load(open(os.path.expanduser("~/.config/hypr/state/stack-mode.json")))
        return bool(st.get("active")) and st.get("socket") == os.path.basename(
            os.environ.get("NIRI_SOCKET", ""))
    except (OSError, ValueError):
        return False


# Вид панели в стопке (21.10.2026, просьба: «ещё один вид stack mode: Centered max»):
# classic — как было; centered — как в Windows 11: окна одними значками, крупнее, по
# центру экрана, «Пуск» — значок первым в этом ряду, закреплённое остаётся. Настройки →
# «Нижняя панель» → «Вид в стопке»; вне стопки панель всегда прежняя.
STACK_LOOK_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-stack-look")
# «Тексты песен» выключены (lyrics_bar.py off) — места под строку нет, окнам вся длина (23.10.2026)
LYR_OFF_FILE = os.path.expanduser("~/.config/hypr/state/lyrics-off")
ICON_W = 44              # centered: ширина кнопки-значка
NOTE_TASK_PX = 12        # значок звука в углу кнопки окна (стопка); было 9, как у стола — «чуть побольше»
ICON_PX = 24             # и размер значка (пиксельные значки чёткие на 8/16/24)


def centered_on():
    try:
        look = open(STACK_LOOK_FILE).read().strip()
    except OSError:
        return False
    return look == "centered" and stack_on()


# В стопке программы закрепляются на панели (ПКМ по кнопке окна), кнопки ставятся в свой
# порядок перетаскиванием (21.10.2026, пользователь). Закреплённое — значок без названия; окон
# у программы нет — значок остаётся, щелчок запускает. Вне стопки панель как раньше.
PINS_FILE = os.path.expanduser("~/.config/hypr/state/xpbar-pins.json")
PIN_W = 36
BTNS_CACHE = os.path.expanduser("~/.cache/xpbar-buttons-%s.json")   # для полёта окон в стопке


def pins_load():
    try:
        d = json.load(open(PINS_FILE))
    except (OSError, ValueError):
        d = {}
    if not isinstance(d, dict):
        d = {}
    d.setdefault("order", {})
    # 21.10.2026, просьба: «закреплённое должно закрепляться только в том мониторе, на котором
    # закрепили» — pins: {монитор: [app_id]}; старый общий список достаётся каждой панели
    pins = d.get("pins")
    if isinstance(pins, list):
        pins = {c: list(pins) for c in d["order"]}
    d["pins"] = pins if isinstance(pins, dict) else {}
    return d


def pins_of(d, conn):
    return d["pins"].get(conn) or []


def pins_save(d):
    tmp = PINS_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    os.replace(tmp, PINS_FILE)


def pin_toggle(app, conn):
    """Закрепить/открепить, не сдвигая с места — как в Windows 10 (21.10.2026, просьба: «механика закреплений не очень работает»): прежде у закреплённого появлялся новый ключ
    «p:app», которого нет в сохранённом порядке, и программа уезжала в конец панели."""
    d = pins_load()
    wins = BARS[0].state.windows.values() if BARS else []
    mine = ["w:%d" % w["id"] for w in wins if pin_id(w) == app]
    mine_pins = d["pins"].setdefault(conn, [])
    pin = app not in mine_pins
    if pin:
        mine_pins.append(app)
    else:
        mine_pins.remove(app)
    # окна остаются на своих местах; закреп — место перед первым окном программы
    keys = [k for k in d["order"].get(conn) or [] if k != "p:" + app]
    if pin:
        i = next((i for i, k in enumerate(keys) if k in mine), None)
        if i is not None:
            keys.insert(i, "p:" + app)
    d["order"][conn] = keys
    pins_save(d)
    for bar in BARS:
        bar.refresh()


def action(*args):
    if args[:1] == ("close-window",) and _pomo_locked():
        return
    if args[:2] == ("focus-window", "--id"):
        # свёрнутое в стопке wm.py возвращает unmin — focus-window показал бы стол свёрнутых
        args = ("focus", args[2])
        subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "wm.py"), *args],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
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
            old = self.windows.get(w["id"])
            if old and old.get("title") != w.get("title") and BROWSER_RE.search(w.get("app_id") or ""):
                schedule_streams()      # новое видео во вкладке — перечитать заголовки MPRIS (audio_by)
            self.windows[w["id"]] = w
        elif kind == "WindowClosed":
            self.windows.pop(d["id"], None)
        elif kind == "WindowFocusChanged":
            # уходим из окна — прочитано всё, что пришло, пока оно было в фокусе: отметка
            # только при входе считала их новыми, и после выхода из Telegram вставала «1»
            # на уже прочитанном (22.10.2026, просьба: «появляются как будто ошибочно»)
            prev = next((o for o in self.windows.values() if o.get("is_focused")), None)
            if prev and prev.get("id") != d.get("id"):
                badge_mark_seen(prev.get("app_id"), force=True)
            for o in self.windows.values():
                o["is_focused"] = o["id"] == d.get("id")
        elif kind == "WindowFocusTimestampChanged":     # для badge_holder — какое окно было последним
            w = self.windows.get(d["id"])
            if w:
                w["focus_timestamp"] = d.get("focus_timestamp")
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
               if (w.get("is_active") or stack_min(w.get("name"))) and w.get("output") == output}
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
    # yazi в терминале (заголовок «Yazi: ~/…», «Yazi File Manager», «yazi ~») — свой значок
    # jarvis-yazi через ~/.local/share/applications/yazi.desktop (yazi_icon.py, 21.10.2026).
    if app_id in TERMINALS and t[:4].lower() == "yazi" and t[4:5] in ("", " ", ":"):
        return "yazi"
    # btop в терминале (заголовок «btop ~») — значком btop.desktop (21.10.2026, просьба: «у btop
    # нет иконки в нижней панели»)
    if app_id in TERMINALS and (t == "btop" or t.startswith("btop ")):
        return "btop"
    # файл, открытый в nvim (.md, .java, .py…, заголовок «nvim A.md · B.java»), — значок языка
    # в цвет обоев (nvim_lang.py, рисует md_icon.py; 21.10.2026); прочий nvim — значком kitty
    lang_icon = nvim_lang.icon(t, app_id)
    if lang_icon:
        return lang_icon
    # окно «Обновление Steam…» (X11, без WM_CLASS и заголовка) — значком Steam, пока жив
    # процесс обновлятора (22.10.2026, просьба: «почему иконка localsend стоит у steam?»)
    if not app_id and not t and steam_updater_running():
        return "steam"
    return app_id


def pin_id(w):
    """Чей закреп «занимает» окно — по значку на панели, не по app_id: kitty с Claude, nvim,
    btop показываются своими значками, и закреп kitty при таких окнах пропадал из панели
    (23.10.2026, просьба: «закрываю kitty — он исчезает из панели»)."""
    return window_icon_id(w.get("app_id") or "", w.get("title"))


def steam_updater_running():
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                with open("/proc/%s/cmdline" % pid, "rb") as f:
                    if b"-child-update-ui\0" in f.read():
                        return True
            except OSError:
                pass
    return False


def app_icon(app_id):
    """Gio.Icon программы по app_id окна — через .desktop, как в доке."""
    if app_id in _app_cache:
        return _app_cache[app_id]
    info = app_info(app_id)
    icon = info.get_icon() if info else None
    if icon is None:
        icon = Gio.ThemedIcon.new_with_default_fallbacks(app_id.lower() or "application-x-executable")
    _app_cache[app_id] = icon
    return icon


def app_info(app_id):
    """.desktop программы по app_id окна (значок, запуск закреплённой)."""
    info = None
    for cand in (app_id, app_id.lower(), app_id.split(".")[-1].lower()):
        try:
            info = Gio.DesktopAppInfo.new(cand + ".desktop")
        except TypeError:
            info = None
        if info:
            break
    # пустой app_id совпадал с первым .desktop без StartupWMClass — у безымянного окна
    # обновления Steam был значок LocalSend (22.10.2026)
    if not info and app_id:
        for a in Gio.AppInfo.get_all():
            if isinstance(a, Gio.DesktopAppInfo) and \
                    (a.get_startup_wm_class() or "").lower() == app_id.lower():
                info = a
                break
    return info


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


def pop_item(text, cb=None, on=True, mark=False, sub=None, back=False, accent=False):
    """Строка плашки: cb — что сделать; sub — список строк второй ступени; back — назад;
    accent — текст цветом акцента (заглушённый звук)."""
    return dict(kind="item", text=text, cb=cb, on=on, mark=mark, sub=sub, back=back, accent=accent)


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
                if it.get("accent"):
                    w.get_style_context().add_class("accent")
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
        # без подсветки при открытии (21.10.2026, «Раскладка выбрана, я даже не наводился»):
        # GTK при показе ставит фокус на первую кнопку, а :focus стилизован как :hover.
        # j/k с пустого фокуса встают на первую строку.
        GLib.idle_add(self.set_focus, None)

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
    # флаг «молнии не надо» — Настройки → Нижняя панель (22.10.2026, просьба: «переключатель
    # на вкл/выкл иконки молнии»)
    OFF = os.path.expanduser("~/.config/hypr/state/xpbar-pomo-bolt-off")
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
    LISTENERS = []              # SideTray (centered): тот же файл состояния
    _mon = None

    def __init__(self):
        super().__init__()
        self.set_has_window(False)
        self.set_size_request(len(self.SHAPE[0]) * self.K + 4, 22)
        self.connect("draw", self.on_draw)
        self.box = None             # EventBox в трее — его и прячем
        self.hidden = False         # centered: помидор показывает SideTray слева
        self.st = {}
        PomoBolt.ALL.append(self)
        self.connect("destroy", lambda *_a: PomoBolt.ALL.remove(self) if self in PomoBolt.ALL else None)
        if PomoBolt._mon is None:
            # inotify на файл состояния + редкий опрос (на случай, если каталога ещё нет)
            try:
                PomoBolt._mon = Gio.File.new_for_path(self.STATE).monitor_file(Gio.FileMonitorFlags.NONE, None)
                PomoBolt._mon.connect("changed", lambda *_a: PomoBolt.refresh_all())
                PomoBolt._mon_off = Gio.File.new_for_path(self.OFF).monitor_file(Gio.FileMonitorFlags.NONE, None)
                PomoBolt._mon_off.connect("changed", lambda *_a: PomoBolt.refresh_all())
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
        # pomo пишет перерыв как short / long — в панели это один «break» (22.10.2026,
        # Просьба: «у меня перерывы в pomo, но он не отображается в ниж. панели»)
        if st.get("phase") in ("short", "long"):
            st["phase"] = "break"
        return st

    @classmethod
    def refresh_all(cls):
        st = cls.read_state()
        for b in list(cls.ALL):
            b.apply(st)
        for f in list(cls.LISTENERS):
            f(st)

    def apply(self, st):
        on = (st.get("phase", "idle") in ("work", "break") and not self.hidden
              and not os.path.exists(self.OFF))
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


class SideTray(Gtk.Box):
    """Левая группа панели в виде Centered max (22.10.2026, просьба: «с левой части
    панели что-то добавлять, т.к. там теперь появилось место… pomo… плашку Энергия, ПКМ —
    savage mode, и он также светился бы как сверху»). Слева «Энергия», за ней помидор (с 22.10 «Энергия» — в правом трее, Tray.take_bat). Помидор — как модуль waybar
    custom/pomo (значок + остаток, те же щелчки), «Энергия» — как custom/battery: ЛКМ —
    панель «Энергия», ПКМ — Savage, в Savage светится. Видна только в centered."""
    POMO = os.path.expanduser("~/.local/bin/pomo")
    HIT = 8
    POMO_ICON = {"idle": "\U000f051f", "work": "\U000f051f", "break": "\U000f0176",
                 "paused": "\uf04c"}

    def __init__(self, bar):
        super().__init__(spacing=26 - 2 * self.HIT)   # «чуть расстояния» между плашками (22.10)
        self.bar = bar
        ctx = self.get_style_context()
        ctx.add_class("tray")
        ctx.add_class("side")
        self.set_margin_start(10 - self.HIT)       # отступ от левого края (22.10)
        clickable = Tray.clickable
        # одна надпись, как у custom/pomo в waybar: «󰔟 24:49 󰓾», жирно, цвет — по состоянию
        # (22.10.2026, просьба: «хочу такое же оформление снизу»)
        self.pomo_l = Gtk.Label()
        self.pomo_l.get_style_context().add_class("pomo")
        self.pomo_cls = None
        self.pomo_box = clickable(self, self.pomo_l, self.on_pomo, scroll=self.on_pomo_scroll)
        self.add(self.pomo_box)
        # «Энергия» — один значок, крупнее, без процентов (22.10.2026, просьба: «можно
        # показывать без цифр заряда, просто иконку… чуть увеличить»); заряд — в подсказке
        self.bat_g = Gtk.Label()
        self.bat_g.get_style_context().add_class("glyph")
        self.bat_g.get_style_context().add_class("bat")
        self.bat_box = clickable(self, self.bat_g, self.on_bat)
        self.pack_start(self.bat_box, False, False, 0)
        self.reorder_child(self.bat_box, 0)        # сначала «Энергия», потом помидор (Пользователь)
        # своё окно EventBox обрезало рисунок по ячейке: правый край батарейки, свечение
        # Savage, прицел 󰓾 (22.10.2026, просьба: «рисунок прицела не полностью нарисовался»).
        # Без видимого окна щелчки ловит окно ввода, а рисует родитель — без обрезки.
        for eb in (self.bat_box, self.pomo_box):
            eb.set_visible_window(False)
        # зона щелчка — не только сам значок: по HIT px с боков (за счёт промежутков, вид
        # прежний) и вся высота панели (22.10.2026, просьба: «неотзывчивая»)
        for lab in (self.bat_g, self.pomo_l):
            lab.set_margin_start(self.HIT)
            lab.set_margin_end(self.HIT)
        for eb in (self.bat_box, self.pomo_box):
            eb.set_valign(Gtk.Align.FILL)
        # по высоте — на одной линии (замер grim 22.10: батарейка была на 0,5 px выше
        # середины, песочные часы — на 0,5 px ниже; значки по 11 px, середины 18,5 у
        # них не бывает — обе на 18)
        self.pomo_l.set_margin_bottom(1)
        self.tick = None
        PomoBolt.LISTENERS.append(self.pomo_apply)
        self.connect("destroy", lambda *_a: PomoBolt.LISTENERS.remove(self.pomo_apply)
                     if self.pomo_apply in PomoBolt.LISTENERS else None)
        self.pomo_apply(PomoBolt.read_state())
        self.bat_apply()
        GLib.timeout_add_seconds(10, lambda: self.bat_apply() or True)
        # свечение Savage / «не гасить экран» — сразу по файлам состояния, а не раз в 10 с
        # (22.10.2026, просьба: «иконка светится с задержкой и пропадает тоже»).
        # screen_awake пишет через .tmp и rename — поэтому WATCH_MOVES и оба имени.
        self.bat_mons, self.bat_pending = [], 0
        for path in ("/tmp/savage_mode.pid", os.path.expanduser("~/.config/hypr/state/screen-awake"),
                     os.path.expanduser("~/.cache/power-mode")):     # Savage Mode = power max
            m = Gio.File.new_for_path(path).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
            m.connect("changed", self.on_bat_state)
            self.bat_mons.append(m)

    def on_bat_state(self, *_a):
        # пачку событий одной записи — в одну перерисовку; savage_battery пишет pid чуть
        # раньше, чем systemd-inhibit появится в /proc, — второй взгляд через 400 мс
        if not self.bat_pending:
            self.bat_pending = GLib.timeout_add(60, self.bat_state_now)

    def bat_state_now(self):
        self.bat_pending = 0
        self.bat_apply()
        GLib.timeout_add(400, lambda: self.bat_apply() or False)
        return False

    def pomo_apply(self, st):
        phase = st.get("phase", "idle")
        try:
            paused = int(st.get("paused") or 0)
            left = max(0, int(st.get("started") or 0) + int(st.get("duration") or 0)
                       - (paused or int(time.time())))
        except ValueError:
            paused, left = 0, 0
        cls = "idle" if phase not in ("work", "break") else "paused" if paused else phase
        text = self.POMO_ICON[cls] + ("" if cls == "idle" else " %02d:%02d" % (left // 60, left % 60))
        tip = PomoBolt.tip(st) if cls != "idle" else "Помидор не запущен"
        focus = self.focus()                         # режим фокуса — как в wb_persist.py pomo
        if focus:
            f_left, f_tip = focus
            if cls == "idle" and f_left is not None:
                text, cls = "\U000f04fe %s" % self.mmss(f_left), "focus"
            else:
                text += " \U000f04fe"
            tip = f_tip + "\n" + tip
        self.pomo_l.set_text(text)
        if cls != self.pomo_cls:
            c = self.pomo_l.get_style_context()
            if self.pomo_cls:
                c.remove_class("pomo-" + self.pomo_cls)
            c.add_class("pomo-" + cls)
            self.pomo_cls = cls
        self.pomo_box.set_tooltip_text(
            tip + "\nЛКМ — старт/пауза · ПКМ — пропустить · СКМ — стоп · колесо — ±1 мин")
        run = cls in ("work", "break", "focus") or bool(focus)   # секунды тикают — раз в секунду
        if run and self.tick is None:
            self.tick = GLib.timeout_add_seconds(1, self.on_tick)
        elif not run and self.tick is not None:
            GLib.source_remove(self.tick)
            self.tick = None

    @staticmethod
    def mmss(sec):
        sec = max(0, int(sec))
        h, rest = divmod(sec, 3600)
        return "%d:%02d:%02d" % (h, rest // 60, rest % 60) if h else "%02d:%02d" % (rest // 60, rest % 60)

    @staticmethod
    def focus():
        """Режим фокуса (focus_mode.py): (секунды или None, подсказка) либо None."""
        try:
            import focus_mode
            st = focus_mode.load()
            if not focus_mode.effective(st):
                return None
        except Exception:
            return None
        now = time.time()
        if st.get("active") and st.get("until"):
            return st["until"] - now, "Фокус до " + time.strftime("%H:%M", time.localtime(st["until"]))
        if st.get("active"):
            return now - st["started"], "Фокус до отмены"
        return None, "Фокус на время помидора"

    def on_tick(self):
        self.tick = None
        self.pomo_apply(PomoBolt.read_state())      # снова заведёт себя, если идёт отсчёт
        return False

    def on_pomo(self, e):
        cmd = {1: "toggle", 2: "stop", 3: "skip"}.get(e.button)
        if cmd:
            spawn(self.POMO, cmd)

    def on_pomo_scroll(self, e):
        d = e.direction
        if d == Gdk.ScrollDirection.SMOOTH:
            up = e.get_scroll_deltas()[2] < 0
        else:
            up = d == Gdk.ScrollDirection.UP
        spawn(self.POMO, "add", "1m" if up else "-1m")

    def bat_apply(self):
        try:
            import savage_battery as SB
            import savage_power
            info, savage, power = SB.battery(), SB.is_savage_active(), savage_power.is_on()
            awake = False
            if savage:
                import screen_awake
                awake = screen_awake.get()
        except Exception:
            info, savage, awake, power = None, False, False, False
        self.bat_box.set_visible(info is not None)
        if info is None:
            return
        cap, status, on_ac = info["cap"], info["status"], info["on_ac"]
        level = 0 if cap < 10 else 1 if cap < 35 else 2 if cap < 60 else 3 if cap < 90 else 4
        if status == "Charging" or on_ac:             # батарейка с молнией / вилкой внутри
            self.bat_g.set_markup('<span font_family="JarvisBattery">%s</span>'
                                  % chr((0xE210 if status == "Charging" else 0xE220) + level))
        else:
            self.bat_g.set_text("\uf244\uf243\uf242\uf241\uf240"[level])
        c = self.bat_g.get_style_context()
        for k, on in (("savage", savage), ("awake", awake), ("power", power)):
            (c.add_class if on else c.remove_class)(k)
        # «savage» в классах — прежнее имя Кофеина (без сна); Savage Mode теперь — power
        self.bat_box.set_tooltip_text("Энергия: %d%%%s · %s\nЛКМ — «Энергия» · СКМ — Savage Mode · ПКМ — Кофеин %s"
                                      % (cap, " · Savage Mode (power max)" if power else "",
                                         "Кофеин" if savage else "без кофеина",
                                         "выкл" if savage else "вкл"))

    def on_bat(self, e):
        if e.button == 1:
            spawn("env", "JARVIS_POPUP_FROM=xpbar", "JARVIS_POPUP_SIDE=right", sys.executable,
                  os.path.join(HERE, "battery_popup.py"))
        elif e.button == 2:
            # СКМ — Savage Mode (power max ⇄ mid; 23.10.2026, просьба). Голубой цвет значка
            # ставит Gio-монитор ~/.cache/power-mode
            spawn(sys.executable, os.path.join(HERE, "savage_power.py"), "toggle")
        elif e.button == 3:
            spawn(sys.executable, os.path.join(HERE, "savage_battery.py"), "--toggle")
            for ms in (300, 1200):                 # Savage запускается не мгновенно
                GLib.timeout_add(ms, lambda: self.bat_apply() or False)


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
        # провод — тот же значок, что network#eth в waybar; щелчок — плашка «Сеть»
        # (lan_popup.py) над панелью справа в стиле системы. Без кабеля значка нет.
        # 22.10.2026, просьба: сначала слева между «Энергией» и pomo, потом «перемести в
        # правую часть панели, между уведомлениями и временем».
        self.lan_g = Gtk.Label(label="\uef09")
        self.lan_g.get_style_context().add_class("glyph")
        self.lan_g.get_style_context().add_class("lan")
        self.lan_box = self.clickable(self.lan_g, self.on_lan)
        self.add(self.lan_box)
        self.lan_up = None
        self.lan_box.show_all()
        self.lan_box.set_no_show_all(True)
        self.lan_apply()
        GLib.timeout_add_seconds(5, lambda: self.lan_apply() or True)   # interval 5, как в waybar
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

    def take_bat(self, box, label):
        box.get_parent().remove(box)
        # рисунок батарейки 19 px при ширине знака 11 — вылезает вправо на 8 px; поля
        # подобраны по снимку grim: до провода и до часов по 18 px, как у соседей
        label.set_margin_start(4)
        label.set_margin_end(9)
        box.set_no_show_all(True)
        self.add(box)
        self.reorder_child(box, self.get_children().index(self.lan_box) + 1)

    LAN_IF = "enp3s0"                             # как "interface" у network#eth

    def lan_apply(self):
        def rd(name):
            try:
                with open("/sys/class/net/%s/%s" % (self.LAN_IF, name)) as f:
                    return f.read().strip()
            except OSError:
                return ""
        up = rd("carrier") == "1"
        if up != self.lan_up:
            self.lan_up = up
            self.lan_box.set_visible(up)
        if up:
            sp = rd("speed")
            self.lan_box.set_tooltip_text("Провод%s\nЛКМ — «Сеть»"
                                          % (": %s Мбит/с" % sp if sp.isdigit() else ""))

    def on_lan(self, e):
        if e.button == 1:
            spawn("env", "JARVIS_POPUP_FROM=xpbar", "JARVIS_POPUP_SIDE=right", sys.executable,
                  os.path.join(HERE, "lan_popup.py"))

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
                # микшер микрофона, как у громкости (22.10.2026; был pavucontrol)
                spawn("env", "JARVIS_POPUP_FROM=xpbar", sys.executable, os.path.join(HERE, "mic_popup.py"))
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
            spawn("env", "JARVIS_POPUP_FROM=xpbar", sys.executable, os.path.join(HERE, "xp_calendar.py"))
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
NOTE, NOTE_OFF = "\U000f0580", "\U000f0581"   # динамик с одной волной / выкл.; три волны (f057e) на 9 px сливаются (21.10.2026: «иконку звука вместо ноты»; было f075a/f075b)
NOTE_AFTER = 4.0                        # поток звучит дольше — тогда нота (короткие звуки уведомлений — нет)
# 1.5 → 4 с (19.10.2026, «нота срабатывает от обычных уведомлений»): Telegram и браузер на звук
# уведомления открывают свой поток и держат его ещё несколько секунд после звука
NOTE_AFTER_MEDIA = 1.5                  # браузеру и музыке — быстрее (19.10.2026, «не сразу появляется»)
NOTE_LINGER = 8.0                       # пауза или конец — нота держится, чтобы успеть нажать
NOTE_LINGER_TASK = 60.0                 # значок на кнопке окна в стопке — минуту после паузы (21.10.2026, «хотя бы минуту»)
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
    try:        # заголовки плееров MPRIS — какое из окон браузера звучит (audio_by)
        AUDIO["mpris"] = {t for t in subprocess.run(
            ["playerctl", "-a", "metadata", "--format", "{{title}}"], capture_output=True,
            text=True, timeout=2).stdout.splitlines() if len(t.strip()) > 2}
    except (OSError, subprocess.SubprocessError):
        AUDIO["mpris"] = set()
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
    show, wake, long = [], [], []
    for sid in list(seen):
        f = info.get(sid)
        after = note_after(f[1], f[3]) if f else NOTE_AFTER
        if sid in playing:
            if now - seen[sid] >= after:
                show.append(f)
                long.append(f)
            else:
                wake.append(after - (now - seen[sid]))
            continue
        qualified = last[sid] - seen[sid] >= after
        if qualified and now - last[sid] < NOTE_LINGER_TASK:
            cur = next((g for g in AUDIO["found"] if g[0] == sid), None)
            cur = cur[:6] if cur else f                     # заглушили на паузе — видно сразу
            info[sid] = cur                                 # и после закрытия потока — как было
            long.append(cur)
            if now - last[sid] < NOTE_LINGER:
                show.append(cur)
                wake.append(NOTE_LINGER - (now - last[sid]))
            else:
                wake.append(NOTE_LINGER_TASK - (now - last[sid]))
            continue
        if not qualified and last[sid] - seen[sid] < 15 and f:
            print("xpbar note: поток %s прожил %.1f с" % (f[1], last[sid] - seen[sid]),
                  file=sys.stderr, flush=True)
        for d in (seen, last, info):
            d.pop(sid, None)
    AUDIO["streams"] = show
    AUDIO["streams_long"] = long
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
    return audio_by(windows, "workspace_id")


def audio_by_win(windows):
    """окно → [{name, …}]: то же, по окнам — значок звука на кнопке окна в стопке
    (21.10.2026, просьба: «иконку звука в правом верху квадрата окна в панели»)."""
    return audio_by(windows, "id", "streams_long")


def audio_by(windows, key, src="streams"):
    if not AUDIO.get(src):
        return {}
    import app_volume
    wins = [w for w in windows.values() if w.get("workspace_id") is not None]

    def ts(w):
        t = w.get("focus_timestamp") or {}
        return (t.get("secs", 0), t.get("nanos", 0))
    out = {}
    playing = {f[0] for f in AUDIO.get("found", ()) if not f[6]}
    alive = {f[0] for f in AUDIO.get("found") or ()}
    for sid, name, chain, words, muted, vol in AUDIO[src]:
        cand = [w for w in wins if w.get("pid") in chain]
        if not cand and words:
            cand = [w for w in wins
                    if app_volume.same_app(words, app_volume.words_of(w.get("app_id")) - GENERIC_WORDS)]
        if not cand:
            continue
        # 21.10.2026, просьба: «иконка ноты появляется в браузере где открыт только чат».
        # Окна Zen — один процесс; звучит то, чей заголовок — заголовок плеера MPRIS
        # (вкладка с видео открыта в нём). Не нашлось — как раньше, по фокусу
        hit = [w for w in cand if any(t in (w.get("title") or "") for t in AUDIO.get("mpris") or ())]
        cand = hit or cand
        # 19.10.2026: окно «картинки в картинке» — того же pid, что браузер. Нота — на
        # главном окне браузера (просьба: «не на картинке в картинке, а в самом браузере»),
        # даже если картинку потом трогали и она была в фокусе позже
        w = max(cand, key=lambda w: ((w.get("title") or "") not in PIP_TITLES, ts(w)))
        if GAME_RE.match(w.get("app_id") or ""):
            continue
        apps = out.setdefault(w[key], {})
        a = apps.setdefault(name, {"name": name, "sids": [], "muted": True, "vol": 0, "rank": 9,
                                   "playing": False, "dead": []})
        a["rank"] = min(a["rank"], app_rank(name, w))
        a["playing"] = a["playing"] or sid in playing or not AUDIO.get("found")
        if AUDIO.get("found") is not None and sid not in alive:
            a["dead"].append((sid, muted, vol))
            continue
        a["sids"].append(sid)
        a["muted"] = a["muted"] and muted
        a["vol"] = max(a["vol"], vol)
    # 21.10.2026, просьба: «нажимаю — то включается, то сразу отключается». Zen на паузе
    # закрывает поток и открывает новый; старый ещё держится в «минуте после паузы», и его
    # «не заглушён» перебивал живой — значок мигал обратно. Закрытые потоки — только когда
    # живых нет (показать, как было до закрытия)
    for apps in out.values():
        for a in apps.values():
            dead = a.pop("dead")
            if not a["sids"] and dead:
                a["sids"] = [d[0] for d in dead]     # как было у последнего потока
                a["muted"], a["vol"] = dead[-1][1], dead[-1][2]
    # первым — что играет сейчас (музыка на паузе уступает Telegram), дальше по рангу
    return {ws: sorted(apps.values(), key=lambda a: (not a["playing"], a["rank"], a["name"]))
            for ws, apps in out.items()}


def audio_of_window(win):
    """Колесо над кнопкой окна (21.10.2026, просьба: «почему скролл по окнам в панели
    для регулировки громкости не работает?»): потоки этого окна — по дереву
    процессов, без pid (Telegram) — по имени. Все потоки, не только те, что видны
    динамиком на столе; играющие — первыми. [] — у окна нет звука (или это игра)."""
    if GAME_RE.match(win.get("app_id") or ""):
        return []
    import app_volume
    found = AUDIO.get("found")
    if found is None:
        found = AUDIO["found"] = read_streams()
    aw = app_volume.words_of(win.get("app_id")) - GENERIC_WORDS
    apps = {}
    for sid, name, chain, words, muted, vol, corked in found:
        if not (win.get("pid") in chain or (words and aw and app_volume.same_app(words, aw))):
            continue
        a = apps.setdefault(name, {"name": name, "sids": [], "muted": True, "vol": 0,
                                   "playing": False})
        a["sids"].append(sid)
        a["muted"] = a["muted"] and muted
        a["vol"] = max(a["vol"], vol)
        a["playing"] = a["playing"] or not corked
    return sorted(apps.values(), key=lambda a: (not a["playing"], a["name"]))


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
        for key in ("streams", "found"):                     # следующий щелчок колеса — от нового
            for s_i, s in enumerate(AUDIO.get(key) or ()):
                if s[0] in a["sids"]:
                    AUDIO[key][s_i] = s[:5] + (a["vol"],) + s[6:]
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


# «Карман» (workspaces.kdl): имя стола постоянное — на него ссылаются magic, notepad.sh и
# правило окон, — поэтому значок меняет только панель: как у прочих столов, по первой
# программе (самая левая колонка), по таблице window-rewrite (niri_bar.py). Пустой карман
# или программа без значка — значок самого кармана (21.10.2026).
POCKET_DESK = ""
NOTE_DX, NOTE_DY = 0, 0          # сдвиг ноты от угла квадрата (WsButton.note_pos); >0 по X уведёт за край


def first_app_glyph(ws_id, windows):
    try:
        sys.path.insert(0, os.path.expanduser("~/.config/niri/scripts"))
        import niri_bar
    except Exception:
        return None
    finally:
        sys.path.pop(0)
    mine = sorted((x for x in windows.values() if x.get("workspace_id") == ws_id), key=niri_bar.col_row)
    if not mine:
        return None
    subject = "class<%s> title<%s>" % (mine[0].get("app_id") or "", mine[0].get("title") or "")
    rules, _ = niri_bar.rewrite_rules()
    return next((g for rx, g in rules if rx.search(subject)), None)


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
        # Нота лежит ПОВЕРХ значка в правом верхнем углу и места в ряду не занимает
        # (21.10.2026, просьба: «чтобы не создавать для них дополнительный спейс»)
        box = Gtk.Overlay()
        self.lbl = Gtk.Label(label="+" if plus else "")
        self.lbl.get_style_context().add_class("wslbl")
        self.note = Gtk.Label()
        self.note.get_style_context().add_class("wsnote")
        self.note.set_no_show_all(True)
        self.note.set_halign(Gtk.Align.START)
        self.note.set_valign(Gtk.Align.START)
        box.add(self.lbl)
        box.add_overlay(self.note)
        box.set_overlay_pass_through(self.note, True)
        box.connect("get-child-position", self.note_pos)
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

    def note_pos(self, ov, child, r):
        """Нота — в правом верхнем углу квадрата и видна целиком (21.10.2026, просьба: «именно
        в углу квадрата, но должна быть видна»). Ставится по чернилам ноты (Pango ink), не по
        полю метки: поле шире и выше самой ноты, по нему угол уезжал за край и нота резалась."""
        if child is not self.note:
            return False
        _m, nat = child.get_preferred_size()
        ni = child.get_layout().get_pixel_extents()[0]
        r.width, r.height = max(nat.width, ni.x + ni.width), max(nat.height, ni.y + ni.height)
        ow, oh = ov.get_allocated_width(), ov.get_allocated_height()
        r.x = max(-ni.x, ow - ni.x - ni.width + NOTE_DX)
        r.y = max(-ni.y, -ni.y + NOTE_DY)
        return True

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
            + "\nКолесо — громкость %s, ПКМ → «Звук» — заглушить"
            % ([a for a in self.apps if not a["muted"]] or self.apps)[0]["name"])

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
        # значок звука не щёлкается (21.10.2026, просьба: «уберём мьют прямо из стола») —
        # заглушить можно в ПКМ → «Звук», колесо над квадратом — громкость
        if e.button == 1:
            if self.plus:
                wid = self.target_id()
                if wid is not None:
                    self.bar.focus_ws(wid)
            else:
                self.bar.focus_ws(self.ws_id)
        elif e.button == 3 and not self.plus:
            self.bar.ws_menu(self.ws_id, e)
        return True

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


# ── Счётчик на кнопке окна (21.10.2026, просьба: «вместо перекрашивания окна, где требуется
# внимание, нарисовать цифру… как в новых Windows»). Как в Windows 11: красная таблетка с
# белой цифрой поверх правого верхнего угла значка; больше 99 — «99+». Число — уведомления
# этой программы из журнала notif_log.py, пришедшие после того, как её окно было в фокусе
# последний раз. Окно просит внимания, а уведомлений нет — красная точка.
NOTIF_LOG = os.path.expanduser("~/.cache/jarvis-notif-log.json")
BADGE_SEEN = os.path.expanduser("~/.cache/xpbar-badge-seen.json")
BADGE_RGB = (0.91, 0.07, 0.14)           # #E81123 — красный Windows
_badge = {"mtime": None, "log": [], "seen": None}
# Плееры без счётчика: «Music» — смена трека (track_notify.py), каждая песня зажигала бы
# красную цифру (22.10.2026, просьба: «не надо рисовать для яндекс музыки… это неудобно»).
NO_BADGE = ("yandexmusic", "spotify", "music")
# «Не беспокоить» — счётчиков и точек нет совсем (22.10.2026, просьба: «пусть не появляются,
# когда включен режим не беспокоить»); пришедшее за это время всплывёт после выключения.
# Ставит watch_notif по swaync-client -swb.
BADGE_DND = [False]


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def badge_seen():
    if _badge["seen"] is None:
        try:
            _badge["seen"] = json.load(open(BADGE_SEEN))
        except (OSError, ValueError):
            _badge["seen"] = {}
    return _badge["seen"]


def badge_mark_seen(app_id, force=False):
    """Окно программы в фокусе — её уведомления прочитаны, счётчик в ноль."""
    if not app_id:
        return
    seen = badge_seen()
    now = time.time()
    if not force and now - seen.get(app_id, 0) < 2:
        return
    seen[app_id] = now
    try:
        with open(BADGE_SEEN + ".tmp", "w") as f:
            json.dump(seen, f)
        os.replace(BADGE_SEEN + ".tmp", BADGE_SEEN)
    except OSError:
        pass


def badge_count(app_id):
    if not app_id or any(x in _norm(app_id) for x in NO_BADGE):
        return 0
    try:
        m = os.stat(NOTIF_LOG).st_mtime
    except OSError:
        return 0
    if m != _badge["mtime"]:
        try:
            _badge["log"] = json.load(open(NOTIF_LOG))
        except (OSError, ValueError):
            _badge["log"] = []
        _badge["mtime"] = m
    seen = badge_seen()
    if app_id not in seen:                    # программу видим впервые — старое не считаем
        badge_mark_seen(app_id)
    since = seen.get(app_id, time.time())
    na = _norm(app_id)
    n = 0
    for r in _badge["log"]:
        if r.get("t", 0) <= since:
            break                             # журнал — новые сверху
        a = _norm(r.get("app"))
        if a and a not in NO_BADGE and (a in na or na in a):        # «Telegram Desktop» ↔ org.telegram.desktop, zen ↔ «Zen Browser»
            n += 1
    return n


# Telegram — его собственный счётчик непрочитанного из заголовка окна «Telegram (N)», как
# значок на панели задач Windows (22.10.2026, просьба: «как в windows: пока я не открою сам чат с
# сообщением, чтобы она не пропадала»; счёт по уведомлениям врал — «10» при прочитанном на
# телефоне, гас при фокусе окна). Число то же, что Telegram ставит сам: что в него входит
# (заглушённые чаты, сообщения или чаты) — Telegram → Настройки → Уведомления → «Счётчик».
TITLE_COUNT = {"org.telegram.desktop": re.compile(r"^Telegram(?: \((\d+)\))?$")}


def title_count(app_id, title):
    """Число из заголовка или None — у программы такого счётчика нет. Не главное окно
    (просмотр медиа и т. п.) — 0: счёт по уведомлениям для неё не включается."""
    rx = TITLE_COUNT.get(app_id or "")
    if not rx:
        return None
    m = rx.match(title or "")
    return int(m.group(1) or 0) if m else 0


def badge_holder(wins):
    """Окно программы, на котором рисовать счётчик: одно на программу (21.10.2026, просьба: «у всех окон этот красный значок, хотя уведомлений там нет» — пришло одно от kitty, «1»
    встала на все четыре окна kitty). Просит внимания — оно; уведомление Claude Code —
    окно, где Claude ждёт ввода (заголовок «✳ …»); иначе — последнее бывшее в фокусе."""
    def ts(w):
        t = w.get("focus_timestamp") or {}
        return (t.get("secs", 0), t.get("nanos", 0))
    pick = [w for w in wins if w.get("is_urgent")]
    last = next((r for r in _badge["log"] if _norm(r.get("app")) == _norm(wins[0].get("app_id"))), None) \
        if wins else None
    if not pick and last and last.get("summary") == "Claude Code":
        pick = [w for w in wins if (w.get("title") or "").startswith("\u2733")]
    return max(pick or wins, key=ts)["id"] if wins else None


class TaskButton(Gtk.Button):
    def __init__(self, bar, wid):
        super().__init__()
        self.bar, self.wid = bar, wid
        self.get_style_context().add_class("task")
        self.set_size_request(TASK_W, -1)
        self.set_relief(Gtk.ReliefStyle.NONE)
        box = Gtk.Box(spacing=6)
        self.img = Gtk.Image()
        self.isz = 16
        self.compact = False
        self.img.set_pixel_size(16)
        self.lbl = Gtk.Label(xalign=0)
        self.lbl.set_ellipsize(Pango.EllipsizeMode.END)
        self.lbl.set_max_width_chars(1)        # ширину держит кнопка, а не текст
        box.pack_start(self.img, False, False, 0)
        box.pack_start(self.lbl, True, True, 0)
        self.add(box)
        self.app = self.title = self.app_id = None
        self.box = box
        self.pinned = False
        self.dragging = False
        self.mdrag = None        # стопка: своё перетаскивание по панели {x, moved}
        self.dnd_on = True
        # колесо — на окно кнопки: без маски событие шло ленте, и кнопку под курсором
        # on_task_scroll не находил — громкость не крутилась (21.10.2026)
        self.add_events(Gdk.EventMask.BUTTON1_MOTION_MASK | Gdk.EventMask.SCROLL_MASK |
                        Gdk.EventMask.SMOOTH_SCROLL_MASK | Gdk.EventMask.POINTER_MOTION_MASK |
                        Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.apps = []           # стопка: кто звучит в этом окне — значок в углу (set_audio)
        self.note_box = None     # куда щёлкать по значку (x, y, w, h) — щелчок глушит
        self.note_hover = False
        self.note_force = None   # (заглушено?, до) — после щелчка, пока pactl не применил
        self.connect("button-press-event", self.on_press)
        self.urgent = self.focused = False     # у значка закрепа без окон update() не бывает
        self.connect_after("draw", self.draw_badge)
        self.connect("motion-notify-event", self.on_mmotion)
        self.connect("motion-notify-event", lambda _w, e: self.hover_note(self.in_note(e)))
        self.connect("leave-notify-event", lambda *_a: self.hover_note(False))
        self.connect("button-release-event", self.on_release)
        self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, dnd_targets(), Gdk.DragAction.MOVE)
        self.sync_dnd()
        self.connect("drag-begin", self.on_drag_begin)
        self.connect("drag-data-get", self.on_drag_get)
        self.connect("drag-end", self.on_drag_end)

    @property
    def key(self):
        # 21.10.2026, просьба: «сортировка сбрасывается, когда открываю окно» — прежде все
        # окна закреплённой программы были «p:app», одно место на всех, и слипались снова.
        # Теперь у окна свой ключ всегда, «p:app» — только место значка без окон.
        return "w:%d" % self.wid if self.wid is not None else "p:" + self.app_id

    def set_pinned(self, on):
        """Закреплённое с открытым окном — обычная кнопка с названием, место на панели —
        как у закрепа (21.10.2026, просьба: «если оно открыто — как и остальные, полностью с
        названиями; закрываем — остаётся закреплённым в компактном виде»). Значок без
        названия — у закреплённого без окна, PinButton."""
        self.pinned = on

    def set_compact(self, on):
        """Centered max: только значок, крупнее, по середине кнопки; ширину ставит fit_buttons."""
        if on == self.compact:
            return
        self.compact = on
        self.isz = ICON_PX if on else 16
        self.img.set_pixel_size(self.isz)
        self.lbl.set_no_show_all(on)
        self.lbl.set_visible(not on)
        self.box.set_halign(Gtk.Align.CENTER if on else Gtk.Align.FILL)
        (self.get_style_context().add_class if on else self.get_style_context().remove_class)("compact")

    def update(self, w):
        self.app_id = w.get("app_id") or ""
        app = window_icon_id(w.get("app_id") or "", w.get("title"))
        if app != self.app:
            self.app = app
            self.img.set_from_gicon(app_icon(app), Gtk.IconSize.MENU)
            self.img.set_pixel_size(self.isz)
            if self.dnd_on:
                self.drag_source_set_icon_gicon(app_icon(app))     # под курсором при переносе
        self.sync_dnd()
        title = w.get("title") or app or "Окно"
        if title != self.title:
            self.title = title
            self.lbl.set_text(title)
            self.set_tip()
        ctx = self.get_style_context()
        for cls, on in (("focused", w.get("is_focused")), ("urgent", w.get("is_urgent"))):
            (ctx.add_class if on else ctx.remove_class)(cls)
        ws = self.bar.state.workspaces.get(w.get("workspace_id")) or {}
        self.minimized = stack_min(ws.get("name"))
        self.focused = bool(w.get("is_focused"))
        self.urgent = bool(w.get("is_urgent")) and not self.focused
        if self.focused:
            badge_mark_seen(self.app_id)
        self.queue_draw()
        # свёрнутое — обычная кнопка, как в XP: «нажата» только кнопка окна в фокусе
        # (21.10.2026, просьба: «не делать тусклыми окна в панели, если не открыты»)

    def draw_run_mark(self, cr):
        """Centered max — метка открытого окна, как в Windows 10: у каждого окна (и
        свёрнутого) полоска акцентом под значком, чуть уже кнопки; у окна в фокусе — во всю
        ширину кнопки. 21.10.2026, просьба: свёрнутые «выглядят как будто эти окна не
        открыты»; сперва было как в Windows 11 (короткие черты) — «давай под Windows 10»."""
        if not self.compact or self.get_style_context().has_class("launcher"):
            return
        st = self.get_style_context()
        m = st.get_margin(self.get_state_flags())
        inset = 0 if self.focused else 4
        x = m.left + inset
        w = self.get_allocated_width() - m.left - m.right - 2 * inset
        h = 2
        y = self.get_allocated_height() - m.bottom - h
        col = (WS_ACC.get(getattr(self.bar, "look", "")) or WS_ACC.get("xp") or ("#ffffff", 0))[0]
        rgba = Gdk.RGBA()
        rgba.parse(col)
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1 if self.focused else 0.75)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def set_audio(self, apps):
        apps = apps or []
        key = [(a["name"], silent(a), a["vol"]) for a in apps]
        if key == [(a["name"], silent(a), a["vol"]) for a in self.apps]:
            return
        self.apps = apps
        self.set_tip()
        self.queue_draw()

    def set_tip(self):
        tip = self.title or ""
        if self.apps:
            tip += "\nЗвучит: " + ", ".join(
                a["name"] + (" (заглушён)" if a["muted"] else " · %d%%" % a["vol"]) for a in self.apps) \
                + "\nКолесо — громкость"
        self.set_tooltip_text(tip or None)

    def note_muted(self):
        f = self.note_force
        if f and time.monotonic() < f[1]:
            return f[0]
        self.note_force = None
        return all(silent(a) for a in self.apps)

    def in_note(self, e):
        nb = self.note_box
        return bool(self.apps and nb and nb[0] <= e.x < nb[0] + nb[2] and nb[1] <= e.y < nb[1] + nb[3])

    def hover_note(self, on):
        if on != self.note_hover:
            self.note_hover = on
            self.queue_draw()
        return False

    def draw_note(self, cr):
        """Значок звука в правом верхнем углу квадрата — как нота у стола (WsButton): цвет
        акцента, тусклее; заглушено — перечёркнутый динамик. Щелчок по нему — заглушить
        (21.10.2026, просьба: «чуть побольше, и сделать её кликабельной»). Рисуется поверх
        кнопки, места не занимает — значок программы не сдвигается («должна вставать поверх»)."""
        self.note_box = None
        if not self.apps:
            self.note_hover = False
            return
        muted = self.note_muted()
        lay = self.create_pango_layout(NOTE_OFF if muted else NOTE)
        desc = lay.get_context().get_font_description().copy()
        desc.set_absolute_size(NOTE_TASK_PX * Pango.SCALE)
        lay.set_font_description(desc)
        ink = lay.get_pixel_extents()[0]
        m = self.get_style_context().get_margin(self.get_state_flags())
        x = self.get_allocated_width() - m.right - 2 - ink.width - ink.x
        y = m.top + 2 - ink.y
        # куда щёлкать — весь правый верхний угол до края кнопки (21.10.2026, «сложно на них
        # нажать»: было только по значку ±2 px); середина со значком программы — окно
        W = self.get_allocated_width()
        x0, y0 = max(0, int(x + ink.x) - 5), 0
        self.note_box = (x0, y0, W - x0, int(y + ink.y + ink.height) + 5)
        col = (WS_ACC.get(getattr(self.bar, "look", "")) or WS_ACC.get("xp") or ("#ffffff", 0))[0]
        rgba = Gdk.RGBA()
        rgba.parse(col)
        if self.note_hover:                  # под курсором — подложка: ясно, что щёлкнется значок
            bx, by = x + ink.x - 3, y + ink.y - 2
            bw, bh, r = ink.width + 6, ink.height + 4, 3
            cr.new_sub_path()
            cr.arc(bx + bw - r, by + r, r, -1.5708, 0)
            cr.arc(bx + bw - r, by + bh - r, r, 0, 1.5708)
            cr.arc(bx + r, by + bh - r, r, 1.5708, 3.1416)
            cr.arc(bx + r, by + r, r, 3.1416, 4.7124)
            cr.close_path()
            cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.22)
            cr.fill()
        cr.set_source_rgba(rgba.red, rgba.green, rgba.blue,
                           (1 if self.note_hover else 0.7) * (0.45 if muted else 1))
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)

    def draw_badge(self, _w, cr):
        self.draw_run_mark(cr)
        self.draw_note(cr)
        if BADGE_DND[0]:
            return False
        own = title_count(self.app_id, self.title)      # свой счётчик — виден и в фокусе
        n = own if own is not None else 0 if self.focused else badge_count(self.app_id)
        if n and self.wid is not None and own is None:
            mine = [w for w in self.bar.state.windows_on(self.bar.connector)
                    if (w.get("app_id") or "") == self.app_id]
            if len(mine) > 1 and badge_holder(mine) != self.wid:
                n = 0
        if not n and not self.urgent:
            return False
        r = self.img.translate_coordinates(self, 0, 0)
        if not r:
            return False
        d = self.isz // 2
        ix, iy = r[0] + self.img.get_allocated_width() // 2 + d, r[1] + self.img.get_allocated_height() // 2 - d
        cr.set_source_rgb(*BADGE_RGB)
        if not n:                                # просит внимания без уведомлений — точка
            cr.arc(ix - 1, iy + 1, 3, 0, 2 * math.pi)
            cr.fill()
            return False
        lay = self.create_pango_layout("99+" if n > 99 else str(n))
        desc = lay.get_context().get_font_description().copy()
        desc.set_absolute_size(8 * Pango.SCALE)       # пиксельный шрифт чёткий на 8 px
        lay.set_font_description(desc)
        ink = lay.get_pixel_extents()[0]
        h = 10
        w = max(h, ink.width + 4)
        right = self.get_style_context().get_margin(self.get_state_flags()).right
        x = min(ix - w // 2 + 1, self.get_allocated_width() - right - w - 1)
        top = self.get_style_context().get_margin(self.get_state_flags()).top
        y = max(top + 1, iy - h // 2 + 1)          # не на внешнем отступе — там срезается
        cr.new_sub_path()
        cr.arc(x + h / 2, y + h / 2, h / 2, math.pi / 2, 3 * math.pi / 2)
        cr.arc(x + w - h / 2, y + h / 2, h / 2, -math.pi / 2, math.pi / 2)
        cr.close_path()
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.move_to(x + (w - ink.width) / 2 - ink.x, y + (h - ink.height) / 2 - ink.y)
        PangoCairo.show_layout(cr, lay)
        return False

    def sync_dnd(self):
        """В стопке кнопки только переставляются по панели — своим перетаскиванием, без
        GTK DnD: перенос GTK на слое срывался (кнопку Telegram не утащить), а отпускание
        после него засчитывалось щелчком и окно открывалось (21.10.2026). Вне стопки —
        DnD как раньше: окно бросают на квадрат стола."""
        want = not stack_on()
        if want == self.dnd_on:
            return
        self.dnd_on = want
        if want:
            self.drag_source_set(Gdk.ModifierType.BUTTON1_MASK, dnd_targets(), Gdk.DragAction.MOVE)
        else:
            self.drag_source_unset()

    def tasks_x(self, e):
        r = self.translate_coordinates(self.bar.tasks, int(e.x), int(e.y))
        return r[0] if r else None

    def on_press(self, _w, e):
        if self.in_note(e):                  # значок звука — не перетаскивание кнопки
            return False
        if not self.dnd_on and e.button == 1 and e.type == Gdk.EventType.BUTTON_PRESS:
            self.mdrag = {"x": self.tasks_x(e), "moved": False}
        return False

    def on_mmotion(self, _w, e):
        m = self.mdrag
        if not m or m["x"] is None:
            return False
        x = self.tasks_x(e)
        if x is None or (not m["moved"] and abs(x - m["x"]) < 5):
            return False
        if not m["moved"]:
            m["moved"] = self.dragging = True
            self.get_style_context().add_class("dragging")
        kids = self.bar.tasks.get_children()
        idx = 0
        for k in kids:
            if k is not self and k.get_visible():
                r = k.translate_coordinates(self.bar.tasks, 0, 0)
                if r:
                    idx += r[0] + k.get_allocated_width() / 2 < x
        if kids.index(self) != idx:
            self.bar.tasks.reorder_child(self, idx)
        return True

    def end_mdrag(self):
        """Отпустили после своего перетаскивания — порядок сохранить, это не щелчок."""
        m, self.mdrag = self.mdrag, None
        if not m or not m["moved"]:
            return False
        self.get_style_context().remove_class("dragging")
        self.bar.save_order()
        GLib.timeout_add(150, lambda: setattr(self, "dragging", False))
        return True

    def on_drag_begin(self, *_a):
        self.dragging = True

    def on_drag_get(self, _w, _ctx, data, _info, _time):
        data.set(data.get_target(), 8, str(self.wid).encode())

    def on_drag_end(self, *_a):
        clear_drop()
        if stack_on():
            self.bar.save_order()
        # стол открылся под окном (SPRING_MS) — кнопка ушла из панели, но жила до конца переноса
        if getattr(self, "stale", False):
            GLib.idle_add(self.destroy)
        # отпускание кнопки мыши после переноса — не щелчок по окну
        GLib.timeout_add(150, lambda: setattr(self, "dragging", False))

    def on_release(self, _w, e):
        if self.end_mdrag() or self.dragging:
            return True
        if e.button == 1 and self.in_note(e):
            ui_click("click")
            # что видно, то и переключаем; до ответа pactl значок держит новое состояние
            mute = not self.note_muted()
            live = {a["name"]: a for a in audio_of_window(self.bar.state.windows.get(self.wid) or {})}
            set_app_mute([live.get(a["name"], a) for a in self.apps], mute)
            info = AUDIO["info"]                 # поток уже закрыт (пауза) — запомнить выбор
            for a in self.apps:
                for sid in a["sids"]:
                    if sid in info and a["name"] not in live:
                        info[sid] = info[sid][:4] + (mute,) + info[sid][5:]
            self.note_force = (mute, time.monotonic() + 1.5)
            GLib.timeout_add(1600, lambda: self.queue_draw() or False)
            self.queue_draw()
            return True
        if e.button == 1:
            ui_click("click")
            if getattr(self, "minimized", False):
                stack_cmd("unmin", str(self.wid))
            elif getattr(self, "focused", False) and stack_on():
                stack_cmd("min", str(self.wid))
            else:
                action("focus-window", "--id", str(self.wid))
        elif e.button == 2:
            action("close-window", "--id", str(self.wid))
        elif e.button == 3:
            self.bar.task_menu(self.wid, e)
        return True


class PinButton(TaskButton):
    """Закреплённая программа без открытых окон (только в стопке): значок, щелчок — запуск."""

    def __init__(self, bar, app):
        super().__init__(bar, None)
        self.app_id = app
        self.set_pinned(True)
        self.get_style_context().add_class("launcher")
        self.img.set_from_gicon(app_icon(app), Gtk.IconSize.MENU)
        self.img.set_pixel_size(self.isz)
        if self.dnd_on:
            self.drag_source_set_icon_gicon(app_icon(app))
        self.info = app_info(app)
        self.set_tooltip_text(self.info.get_display_name() if self.info else app)

    def set_compact(self, on):
        """Закреп без окна — всегда один значок; в Left sided (classic) шириной PIN_W, как
        в Centered max (23.10.2026, просьба: «отображаются полным размером»)."""
        super().set_compact(on)
        self.lbl.set_no_show_all(True)
        self.lbl.hide()
        self.box.set_halign(Gtk.Align.CENTER)
        if not on:
            self.set_size_request(PIN_W, -1)

    def launch(self):
        if self.info:
            spawn("gtk-launch", self.info.get_id())
        else:
            spawn(self.app_id)

    def on_drag_get(self, _w, _ctx, data, _info, _time):
        data.set(data.get_target(), 8, self.key.encode())

    def on_release(self, _w, e):
        if self.end_mdrag() or self.dragging:
            return True
        if e.button == 1:
            ui_click("click")
            self.launch()
        elif e.button == 3:
            self.bar.menu([pop_item("Открыть", self.launch), POP_SEP,
                           pop_item("Открепить от панели задач", lambda: pin_toggle(self.app_id, self.bar.connector))])
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
        m.connector = bar.connector          # подложка «Пуска» Win11 — обои и стиль этого монитора
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
    m.open(center=bar.centered)
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
        self.start_grip = Grip()
        bar.pack_start(self.start_grip, False, False, 0)
        self.bar = bar
        self.centered = False

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
        self.sw.connect("drag-motion", self.on_tasks_motion)
        self.launchers = {}
        self.btn_w = TASK_W
        self.tasks = Gtk.Box(spacing=0)
        # «Пуск» и кнопки окон — в одном ряду: в виде centered «Пуск» переезжает в start_slot
        self.inner = Gtk.Box(spacing=0)
        self.start_slot = Gtk.Box(spacing=0)
        self.inner.pack_start(self.start_slot, False, False, 0)
        self.inner.pack_start(self.tasks, False, False, 0)
        self.sw.add(self.inner)
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
        self.side = SideTray(self)                 # слева — только в Centered max
        self.side.show_all()                       # детей показать до no_show_all: иначе
        self.side.hide()                           # show_all их пропускает
        self.side.set_no_show_all(True)
        bar.pack_start(self.side, False, False, 0)
        bar.reorder_child(self.side, 0)
        # «Энергия» — в правом трее между проводом и часами (22.10.2026, просьба: «иконку
        # Энергии тоже перемести в правую часть, между Ethernet и временем… все должно
        # ровно стоять»); обработчики остаются у SideTray. С того же вечера — в обоих видах
        # стопки (просьба: «в Left side режиме тоже добавь иконку Энергии справа»)
        self.tray.take_bat(self.side.bat_box, self.side.bat_g)
        bar.pack_end(self.lyr, False, False, 0)

        if mode == "always":
            self.rev.set_transition_duration(0)
            self.rev.set_reveal_child(True)
        self.show_all()
        if mode == "button":
            self.hide()              # «по кнопке»: до первого Super+S панели нет
        self.apply_start_look()
        self.lyr_box.hide()   # место под текст остаётся — окна слева не сдвигаются
        self.lyr.set_no_show_all(True)
        self.apply_lyr_space()
        self.left.hide()
        self.right.hide()
        if not self.ws_here or stack_on():
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
        if start_word() == "start":
            self.wordmark.set_text("start")
            self.sq_label.set_text("start")
        else:
            self.wordmark.set_text("staticOS")
            self.sq_label.set_markup('static<span foreground="%s">OS</span>' % c["st_hi"])
        ctx = self.start.get_style_context()
        ctx.remove_class("badge")
        ctx.remove_class("glyphonly")
        if g:
            ctx.add_class("badge" if g[0] == "badge" else "glyphonly")
            self.glyph.set(*g)
        self.start.set_tooltip_text("Пуск — staticOS" if g and g[0] == "icon" else "Пуск")
        cen = self.centered                 # centered minimal: «Пуск» — только значок
        for w, on in ((self.logo, v == "default"), (self.wordmark, v == "default" and not cen)):
            w.set_visible(on)
        for w, on in ((self.spark, sq), (self.plus, sq and not cen),
                      (self.sq_label, (sq or (g and g[0] == "badge")) and not cen),
                      (self.glyph, bool(g))):
            w.set_visible(bool(on))
            w.queue_draw()

    def apply_task_look(self):
        """Вид в стопке (classic | centered) — на лету: при смене в Настройках и при
        входе/выходе из стопки (refresh)."""
        on = centered_on()
        if on == self.centered:
            return
        self.centered = on
        want = self.start_slot if on else self.bar
        par = self.start.get_parent()
        if par is not want:
            par.remove(self.start)
            want.pack_start(self.start, False, False, 0)
            if not on:
                self.bar.reorder_child(self.start, 0)
        self.start_grip.set_visible(not on)
        self.side.set_visible(on)
        # текст песни в centered — слева, сразу за «Энергией» и помидором: справа у трея
        # он сдвигал ряд значков влево от середины (22.10.2026, просьба: «можем выводить в
        # левой части… а то как будто слева больше места чем справа» — «делай»)
        self.bar.remove(self.lyr)
        if on:
            self.bar.pack_start(self.lyr, False, False, 0)
            self.bar.reorder_child(self.lyr, 1)    # 0 — SideTray
        else:
            self.bar.pack_end(self.lyr, False, False, 0)
        # молния справа остаётся и при помидоре слева (22.10.2026, просьба: «куда пропала
        # иконка молнии снизу справа?») — PomoBolt.hidden больше не ставится
        self.tray.bolt.apply(PomoBolt.read_state())
        (self.start.get_style_context().add_class if on else
         self.start.get_style_context().remove_class)("compact")
        self.apply_start_look()
        for b in list(self.buttons.values()) + list(self.launchers.values()):
            if not on and not isinstance(b, PinButton):
                b.set_size_request(TASK_W, -1)
            b.set_compact(on)
        self.inner.set_halign(Gtk.Align.START if on else Gtk.Align.FILL)
        self.inner.set_margin_start(0)
        self.btn_w = None
        self.fit_buttons()

    def center_tasks(self):
        """Ряд значков — по центру всего экрана, а не полосы между «Пуском» и треем."""
        r = self.sw.translate_coordinates(self, 0, 0) if self.sw.get_mapped() else None
        if not r:
            return False
        cur = self.inner.get_margin_start()
        iw = self.inner.get_preferred_width()[1] - cur
        m = int(max(0, min(self.sw.get_allocated_width() - iw,
                           self.get_allocated_width() / 2 - iw / 2 - r[0])))
        if m != cur:
            self.inner.set_margin_start(m)
        return False

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
        # в стопке стол у монитора один, общий — квадраты столов не нужны, только окна
        # (21.10.2026, просьба: «я не должен видеть столы, ведь стол же общий»)
        hide = stack_on()
        # ноты на кнопках окон — и там, где столы не в этой панели (21.10.2026, просьба: «на
        # втором мониторе иконка ноты не появляется» — у ноутбука столы в верхнем баре)
        audio = audio_by_win(self.state.windows) if hide else {}
        for wid, b in self.buttons.items():
            b.set_audio(audio.get(wid))
        if not self.ws_here:
            return
        for wdg in (self.ws_ev, self.ws_grip):
            if wdg.get_visible() == hide:
                wdg.set_visible(not hide)
        if hide:
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
            if w.get("name") == POCKET_DESK:
                label = first_app_glyph(w["id"], self.state.windows) or label
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

    def on_tasks_motion(self, _w, ctx, x, _y, _t):
        """Стопка: кнопку тащат по полосе окон — она сразу встаёт на новое место
        (свой порядок, сохраняется на отпускании — TaskButton.on_drag_end)."""
        if not stack_on():
            return False
        src = Gtk.drag_get_source_widget(ctx)
        kids = self.tasks.get_children()
        if src not in kids:
            return False
        tx = x + self.hadj.get_value()
        idx = 0
        for k in kids:
            if k is not src and k.get_visible():
                a = k.get_allocation()
                idx += a.x + a.width / 2 < tx
        if kids.index(src) != idx:
            self.tasks.reorder_child(src, idx)
        return False

    def keep_order(self, order, pins):
        """Записать порядок с новыми кнопками: иначе второе окно, вставшее рядом с первым,
        уехало бы в конец, когда первое закроют. Ключи закрытых окон и откреплённых — вон."""
        live = ({"w:%d" % i for i in self.state.windows} | {"p:" + a for a in pins_of(pins, self.connector)})
        keys = []
        for b in order:
            if b.key not in keys:
                keys.append(b.key)
        d = pins_load()
        keys += [k for k in d["order"].get(self.connector) or [] if k not in keys and k in live]
        d["order"][self.connector] = self.slot_pins(keys, pins_of(d, self.connector))
        pins_save(d)

    def slot_pins(self, keys, pins):
        """Значок закрепа, пока у программы есть окна, не виден — его место держим перед её
        первым окном на панели: закрыли все окна — значок встаёт туда, где они были."""
        app_of = {"w:%d" % i: pin_id(w) for i, w in self.state.windows.items()}
        for a in pins:
            if not any(app_of.get(k) == a for k in keys):
                # окон нет — значок виден и стоит там, куда его поставили (21.10.2026, просьба:
                # «передвигаю влево, а она возвращается назад» — прежде уезжал в конец)
                if "p:" + a not in keys:
                    keys.append("p:" + a)
                continue
            keys = [k for k in keys if k != "p:" + a]
            i = next(i for i, k in enumerate(keys) if app_of.get(k) == a)
            keys.insert(i, "p:" + a)
        return keys

    def save_order(self):
        keys = []
        for b in self.tasks.get_children():
            k = getattr(b, "key", None)
            if k and k not in keys:
                keys.append(k)
        d = pins_load()
        d["order"][self.connector] = self.slot_pins(keys, pins_of(d, self.connector))
        pins_save(d)
        self.order = []
        GLib.idle_add(lambda: self.refresh() and False)

    def export_buttons(self):
        """Где кнопки окон — для полёта окна при «свернуть/вернуть» в стопке (stack_bars)."""
        self.export_id = None
        if not stack_on():
            return False
        btns = {}
        for wid, b in self.buttons.items():
            r = b.translate_coordinates(self, 0, 0) if b.get_mapped() else None
            if r:
                btns[str(wid)] = [r[0], r[1], b.get_allocated_width(), b.get_allocated_height()]
        path = BTNS_CACHE % self.connector
        try:
            with open(path + ".tmp", "w") as f:
                json.dump({"win_h": self.get_allocated_height(), "btns": btns}, f)
            os.replace(path + ".tmp", path)
        except OSError:
            pass
        return False

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
        items = [pop_title("Стол %s" % ws.get("idx", "?")), pop_item("Тип стола", sub=lays)]
        b = self.ws_buttons.get(ws_id)
        apps = b.apps if b is not None else []
        if apps:                         # заглушить — только отсюда, не щелчком по значку (21.10.2026)
            allm = all(silent(a) for a in apps)
            if len(apps) == 1:
                items.append(pop_item("%s %s %s" % (NOTE if allm else NOTE_OFF,
                                                     "Вернуть звук" if allm else "Заглушить", apps[0]["name"]),
                                      lambda: set_app_mute(apps, not allm), accent=allm))
            else:
                items.append(pop_item("%s Звук" % (NOTE_OFF if allm else NOTE), accent=any(silent(a) for a in apps), sub=[
                    pop_item("%s %s — %s" % (NOTE if silent(a) else NOTE_OFF, a["name"],   # значок — что будет
                                              "вернуть звук" if silent(a) else "заглушить"),
                             lambda a=a: set_app_mute([a], not silent(a)), accent=silent(a)) for a in apps] + [
                    POP_SEP, pop_item("Вернуть звук всем" if allm else "Заглушить всё на столе",
                                      lambda: set_app_mute(apps, not allm), accent=allm)]))
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
        self.apply_task_look()
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
        stack = stack_on()
        pins = pins_load() if stack else {"pins": {}, "order": {}}
        my_pins = pins_of(pins, self.connector)
        focused = None
        for w in wins:
            b = self.buttons.get(w["id"])
            if b is None:
                b = self.buttons[w["id"]] = TaskButton(self, w["id"])
                b.set_compact(self.centered)
                self.tasks.pack_start(b, False, False, 0)
                b.show_all()
            b.update(w)
            b.set_pinned(pin_id(w) in my_pins)
            if w.get("is_focused"):
                focused = b
        have = {pin_id(w) for w in wins}
        want = [a for a in my_pins if a not in have]
        for a in list(self.launchers):
            if a not in want:
                self.launchers.pop(a).destroy()
        for a in want:
            if a not in self.launchers:
                b = self.launchers[a] = PinButton(self, a)
                b.set_compact(self.centered)
                self.tasks.pack_start(b, False, False, 0)
                b.show_all()
        order = [self.buttons[i] for i in ids] + [self.launchers[a] for a in want]
        if stack:
            # свой порядок (перетаскивание); новое — в конец: закреплённое, потом окна
            saved = pins["order"].get(self.connector) or []
            pos = {k: i for i, k in enumerate(saved)}
            nat = {b: i for i, b in enumerate(order)}
            # новое окно — в конец, даже если программа уже открыта (21.10.2026, просьба: «чтобы окна
            # открывались в конце списка»; прежде вставало рядом с её окнами, как в Windows 10)
            # закреп, о котором порядок ещё не знает (закрепили из «Пуска»), — на место
            # первого окна программы, а не в конец
            # программа — по видимому значку (pin_id): kitty с nvim/Claude не «окно kitty» (23.10.2026,
            # Пользователь: kitty, переставленный влево, открывался в конце — его место занимали nvim-окна)
            pid = {b: (pin_id(self.state.windows[b.wid]) if b.wid in self.state.windows else b.app_id)
                   for b in order}
            wpos = {}
            for b in order:
                if b.wid is not None and "w:%d" % b.wid in pos:
                    wpos[pid[b]] = min(wpos.get(pid[b], 1 << 30), pos["w:%d" % b.wid])

            def rank(b):
                if b.key in pos:
                    return (pos[b.key], 0, nat[b])
                if b.wid is None and pid[b] in wpos:
                    return (wpos[pid[b]], 0, nat[b])
                # первое окно закреплённой — на место значка; второе и дальше — в конец (21.10.2026:
                # новый kitty вставал на место «p:kitty» посреди панели). wpos считан до sort:
                # во время list.sort сам список пуст — обходить order в rank нельзя
                if pid[b] not in wpos and "p:%s" % pid[b] in pos:
                    return (pos["p:%s" % pid[b]], 1, nat[b])
                return (len(saved) + (not b.pinned), 0, nat[b])
            order.sort(key=rank)
            if any(b.key not in pos for b in order) and not any(b.dragging for b in order):
                self.keep_order(order, pins)
        if order != self.order and not any(b.dragging for b in order):
            self.order = order
            for i, b in enumerate(order):
                self.tasks.reorder_child(b, i)
        self.fit_buttons()
        if stack and getattr(self, "export_id", None) is None:
            self.export_id = GLib.timeout_add(120, self.export_buttons)
        if focused:
            GLib.idle_add(self.reveal_button, focused)

    def fit_buttons(self):
        """Как в XP: окон много — кнопки ужимаются от TASK_W до TASK_MIN, и только
        когда и так не влезают, появляется прокрутка."""
        if self.centered:
            for b in list(self.buttons.values()) + list(self.launchers.values()):
                if b.get_size_request()[0] != ICON_W:
                    b.set_size_request(ICON_W, -1)
            self.btn_w = ICON_W
            GLib.idle_add(self.center_tasks)
            return False
        wide = list(self.buttons.values())
        n = len(wide)
        if not n:
            return False
        avail = self.sw.get_allocated_width() - PIN_W * len(self.launchers)
        w = max(TASK_MIN, min(TASK_W, avail // n - 4))
        if w != self.btn_w:
            self.btn_w = w
            for b in wide:
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
        # над кнопкой окна со звуком — громкость этой программы (как над столом),
        # над окном без звука — прокрутка ленты окон
        b = Gtk.get_event_widget(e)
        while b is not None and not isinstance(b, TaskButton):
            b = b.get_parent()
        win = self.state.windows.get(b.wid) if b is not None and b.wid is not None else None
        apps = audio_of_window(win) if win else []
        if apps:
            v = 0
            if e.direction == Gdk.ScrollDirection.SMOOTH:
                ok, dx, dy = e.get_scroll_deltas()
                v = (dy if abs(dy) >= abs(dx) else dx) if ok else 0
                v = (1 if v > 0 else -1) if abs(v) >= 0.5 else 0
            elif e.direction in (Gdk.ScrollDirection.UP, Gdk.ScrollDirection.LEFT):
                v = -1
            else:
                v = 1
            if v:
                set_app_volume(apps, -v * VOL_STEP)
            return True
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
        if stack_on():
            # в стопке окна и так плавающие; «во весь экран» — развернуть под полосой, как Super+F
            # (настоящий полный экран демон стопки не трогает: его просит видео, 21.10.2026)
            app = w.get("app_id") or ""
            pinned = app in pins_of(pins_load(), self.connector)
            info = app_info(app)
            # окно со своим значком (Claude, nvim, btop в kitty) закрепляет саму программу
            own = pin_id(w) == app
            name = info.get_display_name() if info else app
            pin_label = ("Открепить" if pinned else "Закрепить") + (
                " от панели задач" if pinned and own else " %s от панели задач" % name if pinned else
                " на панели задач" if own else " %s на панели задач" % name)
            new_win = ([pop_item("Новое окно — " + info.get_display_name(),
                                 lambda: spawn("gtk-launch", info.get_id()))] if info else [])
            self.menu([item("Перейти", "focus-window", "--id", str(wid))] + new_win +
                      [pop_item("Во весь экран", lambda: spawn("python3", STACK_MODE, "max", str(wid))),
                       pop_item(pin_label,
                                lambda: pin_toggle(app, self.connector)),
                       POP_SEP,
                       item("Закрыть окно", "close-window", "--id", str(wid))])
            return
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
    def apply_lyr_space(self):
        """Тексты выключены — место LYR_W убрать совсем: окна занимают всю длину панели."""
        on = not os.path.exists(LYR_OFF_FILE)
        if self.lyr.get_visible() != on:
            self.lyr.set_visible(on)
            self.btn_w = None

    def set_lyrics(self, obj):
        # строку уже показывает островок сверху на этом мониторе (живая нить, капсула котика) —
        # здесь не дублировать (20.10.2026, пользователь); не видно сверху — показывать
        if self.connector in ISLAND_LYR:
            self.lyr_box.hide()
            self.lyr.set_tooltip_text(None)
            return
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

    # где строку песни показывает островок (island.py LYR_FLAG) — там не дублировать
    def island_lyr(*_a):
        try:
            new = set(open(ISLAND_LYR_FILE).read().split())
        except OSError:
            new = set()
        if new != ISLAND_LYR:
            ISLAND_LYR.clear()
            ISLAND_LYR.update(new)
            for b in bars:
                b.set_lyrics(seen["lyrics"] or {})
    island_lyr()
    lyr_mon = Gio.File.new_for_path(ISLAND_LYR_FILE).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
    lyr_mon.connect("changed", island_lyr)
    BARS_KEEP.append(lyr_mon)

    # пришло уведомление — счётчики на кнопках окон (TaskButton.draw_badge)
    def badges_redraw(*_a):
        for b in bars:
            for t in b.buttons.values():
                t.queue_draw()
    badge_mon = Gio.File.new_for_path(NOTIF_LOG).monitor_file(Gio.FileMonitorFlags.WATCH_MOVES, None)
    badge_mon.connect("changed", badges_redraw)
    BARS_KEEP.append(badge_mon)

    # Super+Ctrl+Alt+H/L в стопке (niri/scripts/hl-step … move пишет сюда left|right):
    # кнопка окна в фокусе — на место левее/правее, порядок сохраняется как после перетаскивания
    move_file = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-move")

    def task_move(_m, f, _o, ev):
        if ev not in (Gio.FileMonitorEvent.CHANGES_DONE_HINT, Gio.FileMonitorEvent.CREATED):
            return
        try:
            d = open(move_file).read().split()[0]
        except (OSError, IndexError):
            return
        if not stack_on() or d not in ("left", "right"):
            return
        for b in bars:
            t = next((t for t in b.buttons.values() if t.focused), None)
            if t is None:
                continue
            kids = [k for k in b.tasks.get_children() if k.get_visible()]
            i = kids.index(t) if t in kids else -1
            j = i + (-1 if d == "left" else 1)
            if i < 0 or not 0 <= j < len(kids):
                return
            b.tasks.reorder_child(t, b.tasks.get_children().index(kids[j]))
            b.save_order()
            return
    move_mon = Gio.File.new_for_path(move_file).monitor_file(Gio.FileMonitorFlags.NONE, None)
    move_mon.connect("changed", task_move)
    BARS_KEEP.append(move_mon)

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
                    if dnd != BADGE_DND[0]:
                        BADGE_DND[0] = dnd
                        GLib.idle_add(lambda: badges_redraw() and False)
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
        if START_WORD_FILE in paths:
            for b in bars:
                b.apply_start_look()
        if START_BUTTON_FILE in paths:
            load_css()
            for b in bars:
                b.apply_start_look()
                b.queue_draw()
        if PINS_FILE in paths:              # закреп из меню «Пуск» (start_menu.py)
            for b in bars:
                b.refresh()
        if STACK_LOOK_FILE in paths:
            for b in bars:
                b.apply_task_look()
        if LYR_OFF_FILE in paths:
            for b in bars:
                b.apply_lyr_space()
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
