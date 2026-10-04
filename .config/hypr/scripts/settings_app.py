#!/usr/bin/env python3
"""Настройки рабочего стола — одно окно для всего, что раньше было разбросано
по попапам бара.

Открывается шестерёнкой в панели «Энергия», клавишами SUPER+/ и из меню
приложений («Настройки»). Окно плавающее, по центру — правило float-settings в
workspace.lua (класс окна com.jarvis.settings). Второй запуск не открывает
второе окно, а поднимает уже открытое (Gtk.Application).

Оформление переделано 30.09.2026 по образцу настроек angelOS (до того —
12.09.2026, с оглядкой на caelestia shell), 01.10.2026 — компактнее и деревом.
Чего держаться при правках:

* слева — поле поиска и дерево: пункты (со значком) и под ними с отступом
  подпункты (TREE), скрытые, пока пункт не раскрыт щелчком;
* справа — заголовок страницы (24 px; над ним мелко — пункт-родитель)
  и карточки секций с тонкой рамкой: у секции заголовок со
  значком (16 px), строки «подпись слева — управление справа». Выбор из 2–5
  вариантов — сегменты, не выпадающие списки. Плитки-схемы — небольшие, по
  3–4 в ряд, ползунки — фиксированной ширины (SLIDER_W);
* пиксельный шрифт PxPlus HP 100LX 6x8 Jarvis и только 12/16/24/32 px:
  на других размерах он мылится. Значки — Nerd Font;
* пояснение к строке — подсказкой при наведении, по нему же ищет поиск;
* все цвета — из палитры обоев (popup_theme.palette), ни одного зашитого.

Пункты (с 02.10.2026): Waybar (и всё про XP: меню рабочего стола, нижняя
панель), Fonts, Cursors, Applications, Visuals (экран), Misc (снимки, окна,
уведомления, питание, мышь и запись), Config (вид Настроек).
Подзаголовков страниц и пояснений секций на экране нет (просьба пользователя
01.10.2026) — пояснения строк живут подсказками при наведении.
Всё применяется сразу, кнопки «Применить» нет намеренно.

Сверху — полоса заголовка в духе Windows XP: таскать окно, развернуть между
баром и нижней панелью, закрыть (свернуть в niri некуда).

Виды окна (раунд 6, 02.10.2026) — выбор в Config, применяется без перезапуска:
* Default — один вид в двух режимах: Dark — прежний «Обычный» (карточки и
  пилюли), Light — прежний «XP» (панель управления Windows XP, xp_css);
* Skeet — в стиле меню gamesense/skeet (skeet_css); режима у него нет, стиль один;
* Beta — по образцу Настроек AngelOS (beta_css): цветные плитки-значки слева,
  карточка пользователя, «‹ ›» с историей и хлебные крошки, блок «Частое».
Внизу страницы (Default и Beta; в Skeet нет) — «Сбросить эту страницу ·
изменено здесь: N» (раунд 7, 03.10.2026): реестр настроек с умолчаниями —
DEFAULTS, row → register, add_reset_bar; обработчики зовутся только через fire.
Режим Light/Dark — отдельное состояние, общее для Default и Beta. Вид — в
SKIN_FILE, режим — в MODE_FILE; прежние значения normal/xp понимаются
(view_get). Внутри кода оформление выбирает self.look: normal|xp|skeet|beta.
Для проверок: JARVIS_SETTINGS_TEST=1 — свой application_id, не перехватывает
настоящий запуск.

Скорость открытия (раунд 8, 03.10.2026, «открываются с задержкой»):
* чтения состояний запускаются заранее по страницам (prefetch_page): до первого
  кадра — только открываемой страницы, остальных — после него;
* резидент: крестик прячет окно, процесс остаётся (App.on_close → park), а
  повторный запуск стучится в сокет ещё до импорта GTK (ask_resident) и окно
  показывается сразу; состояния при показе перечитываются (revive → reread:
  страницы по одной подменяются свежими, replace_page). Выключатель — файл RESIDENT_OFF, строка «Быстрое открытие» в
  Config. «--hidden» — запустить спрятанным (для автозапуска), «--quit» —
  завершить резидента.
"""
import os
import sys

# ── быстрый показ (раунд 8) ─────────────────────────────────────────────────
# Замер 03.10.2026: до первой нашей строки уходит python + разбор этого файла +
# import gi/Gtk — больше половины холодного старта, и убрать это нечем. Поэтому
# уже работающему процессу (резиденту) просьба «покажись» уходит отсюда, ДО
# импорта GTK: один коннект к сокету, и этот процесс сразу выходит. Никто не
# ответил — обычный запуск ниже. Проверки (JARVIS_SETTINGS_TEST=1) ходят в свой
# сокет и настоящему окну не мешают.
TEST = os.environ.get("JARVIS_SETTINGS_TEST") == "1"
SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp",
                         "jarvis-settings%s.sock" % ("-test" if TEST else ""))


def ask_resident(argv):
    """Передать аргументы запуска живому процессу Настроек. True — принял."""
    import socket
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(1.5)
            c.connect(SOCK_PATH)
            c.sendall(("\x1f".join(argv) + "\n").encode())
            return c.recv(16).startswith(b"ok")
    except OSError:
        return False


if __name__ == "__main__":
    if ask_resident(sys.argv[1:]):
        sys.exit(0)
    if "--quit" in sys.argv[1:]:                 # завершать некого
        sys.exit(0)

import datetime  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import threading  # noqa: E402
import time  # noqa: E402

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

# Имя окна для Hyprland (app_id на Wayland). Без этого окно называлось по
# имени файла, «settings_app.py», и правило float-settings (класс
# com.jarvis.settings) к нему не применялось — окно вставало в мозаику.
# Задаётся ДО создания окон.
GLib.set_prgname("com.jarvis.settings")

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import popup_theme  # noqa: E402
import login_theme  # noqa: E402
import wm  # noqa: E402

# Часть настроек существует только в Hyprland: в Niri нет ни затемнения
# неактивных окон, ни выбора раскладки — там раскладка одна. Такие строки не
# прячем, а гасим и подписываем: иначе переключатель выглядел бы рабочим и
# молча ничего не делал (21.09.2026).
# В сеансе niri ответ виден по окружению; wm.which() сперва зовёт «pidof Hyprland»
# (лишний процесс на каждом старте) — к нему только если окружение молчит.
NIRI = (bool(os.environ.get("NIRI_SOCKET")) and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")) \
    or wm.which() == "niri"

# Значок строки настройки — по началу её названия. Строки стали компактными:
# пояснение больше не занимает место под названием, оно всплывает подсказкой
# при наведении, а слева стоит значок (просьба пользователя 21.09.2026: «много
# текста и мало иконок»). Значки из Nerd Font, наличие каждого проверено.
ROW_ICONS = {
    "Форма панели": "\U000f1513",
    "Скругление углов бара": "\U000f0607",
    "Шейдер терминала": "\U000f0e30",
    "Скругление окон": "\U000f0607",
    "Прозрачность Obsidian": "\U000f1853",
    "Окно с фокусом": "\U000f061e",
    "Наведение мыши": "\U000f037d",
    "Neovim": "\U000f05e7",
    "Ночной режим": "\U000f0594",
    "Размытие": "\U000f00b5",
    "Сила размытия": "\U000f00b5",
    "Тема экрана входа": "\U000f0009",
    "Предпросмотр": "\U000f0976",
    "Стиль экрана блокировки": "\U000f033e",
    "Экран блокировки — свой": "\U000f033e",
    "Энергосбережение": "\U000f0084",
    "Savage Mode": "\U000f0241",
    "Не беспокоить": "\U000f009b",
    "Уведомление при смене трека": "\U000f0386",
    "Эквалайзер": "\U000f1542",
    "Попапы приклеены к бару": "\U000f0403",
    "Bongo Cat в баре": "\U000f011b",
    "Тексты песен в баре": "\U000f0387",
    "Кнопка «Пуск» — пиксельная": "\U000f08c7",
    "Окна в баре — панель задач": "\U000f0570",
    "Меню выключения — новые значки": "\U000f0425",
    "Окна в доке": "\U000f0eb2",
    "Появление": "\U000f06d0",
    "Окна и панель": "\U000f0a6e",
    "Тексты песен": "\U000f0387",
    "Редактор": "\U000f11e4",
    "Эффект экрана": "\U000f07b7",
    "След курсора": "\U000f01bf",
    "Отдача и молнии": "\U000f140c",
    "ЭЛТ-монитор": "\U000f07f4",
    "Какой курсор": "\U000f01bf",
    "Теплота": "\U000f0594",
    "Дашборд": "\U000f056e",
    "Менять и в открытых": "\U000f018d",
    "Zen": "\U000f059f",
    "Действие на правый клик": "\U000f035c",
    "Яркость ноутбука": "\U000f00de",
    "Яркость MSI": "\U000f0379",
    "Подсветка клавиатуры": "\U000f030c",
    "Подсветка Razer": "\U000f030c",
    "Настройки Razer": "\U000f0493",
    "Вид как в Noctalia": "\U000f03d8",
    "Шрифт системы": "\U000f06d6",
    "Obsidian": "\U000f0354",
    "Терминал kitty": "\U000f018d",
    "LibreWolf": "\U000f059f",
    "Helium": "\U000f059f",
    "Где показывать окно": "\U000f061e",
    "Окно памяти": "\U000f035b",
    "Показать сейчас": "\U000f06a9",
    "От края экрана": "\U000f0603",
    "До окон": "\U000f084f",
    "Отступы — как у формы": "\U000f099b",
}
ROW_ICON_DEFAULT = "\U000f09de"

APP_ID = "com.jarvis.settings"
BAR_STYLE = os.path.join(HERE, "bar_style.py")
BLUR = os.path.join(HERE, "wallpaper_blur.py")
PIXEL = os.path.join(HERE, "wallpaper_pixel.py")
CLIPBOARD = os.path.join(HERE, "clipboard_win.py")
REC_AREA = os.path.join(HERE, "rec_area.sh")
SYSSTYLE = os.path.join(HERE, "system_style.py")    # единый стиль системы (04.10.2026)
STYLE_LOOKS = [("default", "Обычный"), ("skeet", "Skeet"), ("beta", "Beta")]


def has_command(path, word):
    """Знает ли скрипт команду `word`. rec_area.sh на незнакомое слово открывает
    меню записи на экране (03.10.2026, поймано проверкой) — такое чтение звать нельзя."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return False
    return re.search(r"(^|[\s|(\"'])%s\)|[\"']%s[\"']" % (word, word), text, re.M) is not None
MOUSE = os.path.join(HERE, "mouse_focus.py")
RIBBON_CENTER = os.path.join(HERE, "ribbon_center.py")
ROUNDING = os.path.join(HERE, "window_rounding.py")
OBSIDIAN_OPACITY = os.path.join(HERE, "obsidian_opacity.py")
LOGIN_THEME = os.path.join(HERE, "login_theme.py")
LOCK_STYLE = os.path.join(HERE, "lock_style.py")
BAR_ROUNDING = os.path.join(HERE, "bar_rounding.py")
BAR_MARGINS = os.path.join(HERE, "bar_margins.py")
SAVAGE = os.path.join(HERE, "savage_battery.py")
APP_FONTS = os.path.join(HERE, "app_fonts.py")
APPMEM_POPUP = os.path.join(HERE, "appmem_popup.py")
CURSOR_THEME = os.path.join(HERE, "cursor_theme.py")
KITTY_SHADER = os.path.join(HERE, "kitty_shader.py")
SCREEN_AWAKE = os.path.join(HERE, "screen_awake.py")
MON_BRIGHT = os.path.join(HERE, "monitor_brightness.py")
MSI_LAST = os.path.expanduser("~/.cache/msi-brightness")
RAZER_BRIGHT = os.path.join(HERE, "razer_brightness.py")
RAZER_LAST = os.path.expanduser("~/.cache/razer-brightness")
KBD_LED = "rgb:kbd_backlight"
KBD_LEVEL = os.path.expanduser("~/.cache/kbdlight-level")   # общий с scripts/kbdlight
NIGHT_STATE = os.path.expanduser("~/.cache/night-mode")
NIGHT_MODE = os.path.join(HERE, "night_mode.py")
# Neovim: курсор всегда по центру (scrolloff 999). Файл читает
# ~/.config/nvim/lua/config/centered.lua и следит за каталогом — открытые Neovim
# переключаются сразу. Нет файла — включено.
NVIM_CENTER_STATE = os.path.expanduser("~/.config/hypr/state/nvim-center")
NVIM_DARKBG_STATE = os.path.expanduser("~/.config/hypr/state/nvim-darkbg")
# Дашборд (часы, таймер, cava, brrt… на экране ноутбука): scripts/dashboard в niri.
# Есть файл-флаг — при входе окна не открываются. Тот же флаг читает `dashboard restore --login`.
DASHBOARD = os.path.expanduser("~/.config/niri/scripts/dashboard")
DASHBOARD_OFF = os.path.expanduser("~/.config/niri/dashboard.off")
# Редактор для SUPER+Print; читает scripts/screenshot_annotate.sh при каждом снимке.
SHOT_STATE = os.path.expanduser("~/.config/hypr/state/shot-editor")
EDITORS = [
    ("ksnip", "ksnip",
     "Нарисованное можно выделить и подвинуть, сменить ему цвет и толщину. "
     "Толщина — числом, размытие и пикселизация. Ctrl+C — в буфер."),
    ("satty", "satty",
     "Проще и быстрее. Enter — в буфер и закрыть. "
     "Толщина — S/M/L и множитель «1.00» справа от них."),
]
# Порядок задан пользователем 14.09.2026 под сетку в два столбца (пары Парящий /
# Компактный, Во всю ширину / Во всю, компакт, Острова / Прозрачный, Снизу) —
# так он и стоит в «Энергии». В «Настройках» с 01.10.2026 — по 4 в ряд.
LOOKS = [("floating", "Парящий"), ("compact", "Компактный"),
         ("edge", "Во всю ширину"), ("edge-compact", "Во всю, компакт"),
         ("islands", "Острова"), ("transparent", "Прозрачный"),
         ("bottom", "Снизу")]


def cursor_pixbuf(path, want=32):
    """Первый кадр XCursor ближе всего к want px → GdkPixbuf (или None)."""
    import struct
    try:
        data = open(path, "rb").read()
        ntoc = struct.unpack_from("<I", data, 12)[0]
        toc = [struct.unpack_from("<III", data, 16 + i * 12) for i in range(ntoc)]
        toc = [t for t in toc if t[0] == 0xFFFD0002]
        nominal = min({t[1] for t in toc}, key=lambda n: abs(n - want))
        pos = next(t[2] for t in toc if t[1] == nominal)
        w, h = struct.unpack_from("<II", data, pos + 16)
        raw = data[pos + 36:pos + 36 + w * h * 4]
        out = bytearray(len(raw))
        for i in range(0, len(raw), 4):
            b, g, r, a = raw[i:i + 4]
            if a:
                r, g, b = min(255, r * 255 // a), min(255, g * 255 // a), min(255, b * 255 // a)
            out[i:i + 4] = bytes((r, g, b, a))
        return GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(out)), GdkPixbuf.Colorspace.RGB,
                                               True, 8, w, h, w * 4)
    except (OSError, ValueError, StopIteration, struct.error):
        return None

# Боковое меню — пункты и подпункты (01.10.2026, просьба пользователя: «правильно
# разделить пункты и подпункты»; названия пунктов — его). Пункт: (ключ,
# значок, название, есть ли своя страница, [(ключ подпункта, название)]).
# Подпункты скрыты, пока пункт не раскрыт щелчком; второй щелчок сворачивает.
# Пункт без своей страницы открывает первый подпункт. Ключи страниц — они же
# ключи self.builders и аргумент settings_app.py <страница>.
# Второй раунд того же дня: Waybar — одна страница, «Окна» — пункт Niri,
# уведомления, питание и приложения — свои пункты, в Misc — экран и снимки.
TREE = [
    ("waybar", "\U000f1513", "Waybar", True, []),
    ("fonts", "\U000f0284", "Fonts", True, []),
    ("cursor", "\U000f01bf", "Cursors", True, []),
    ("apps", "\U000f003b", "Applications", True, []),
    ("visuals", "\U000f08b5", "Visuals", True, []),
    ("misc", "\U000f01d8", "Misc", True, []),
    ("config", "\U000f0493", "Config", True, []),
]
# Страницы по порядку меню; пункт-родитель каждой; название каждой.
PAGE_ORDER = []
PAGE_PARENT = {}
PAGE_TITLE = {}
for _k, _i, _t, _own, _kids in TREE:
    PAGE_TITLE[_k] = _t
    if _own:
        PAGE_ORDER.append(_k)
    for _ck, _ct in _kids:
        PAGE_ORDER.append(_ck)
        PAGE_PARENT[_ck] = _k
        PAGE_TITLE[_ck] = _ct
# Прежние ключи разделов (до 01.10.2026) — чтобы старые вызовы
# «settings_app.py look» и т. п. открывали то же место.
PAGE_ALIASES = {"look": "waybar", "bar-shape": "waybar", "bar-geometry": "waybar",
                "bottom": "waybar", "xp": "waybar", "notify": "misc", "power": "misc",
                "shaders": "apps", "terminal": "apps",
                "windows": "misc", "visuals-windows": "misc", "niri": "misc",
                "shots": "misc", "screen": "visuals"}
# Какие пункты раскрыты — помнится между запусками.
NAV_STATE = os.path.expanduser("~/.cache/jarvis/settings_nav.json")
SECTION_ICON_DEFAULT = "\U000f08bb"
# Размеры окна (01.10.2026: было 1040×760 — «уменьшить и сделать компактнее»).
# То же число — в правиле niri ~/.config/niri/cfg/window-rules.kdl.
WIN_W, WIN_H = 860, 620
# Меню: самый длинный пункт, «Notifications», — 13 знаков по 12 px со значком.
RAIL_W = 216
PAGE_PAD = 12          # поля страницы слева и справа
CARD_PAD = 10          # поля карточки слева и справа (.card в CSS)
# Ширина строки внутри карточки при размере окна по умолчанию: по ней строка
# решает, встанут ли сегменты справа от подписи или уйдут под неё. Полоса
# прокрутки места не занимает — она поверх (overlay).
ROW_W = WIN_W - 4 - RAIL_W - 2 * PAGE_PAD - 2 * CARD_PAD - 2   # 4 — своя рамка окна
SLIDER_W = 200
# Плитки-схемы: одна ширина на всех страницах, по 4 в ряд; 8 — поля и рамка
# плитки. «Во всю, компакт» (15 знаков по 9 px) должно влезать целиком.
TILE_GAP = 6
TILE_W = (ROW_W - 3 * TILE_GAP) // 4 - 8

# Нижняя панель (30.09.2026): одна из трёх, выбирает bottom_bar.py.
BOTTOM_BAR = os.path.join(HERE, "bottom_bar.py")
DOCK = os.path.join(HERE, "dock.py")
BOTTOMS = [("none", "Ничего"), ("dock", "Док"), ("xp", "XP-панель")]

_serial_q = None


def leading(label, px):
    """Межстрочный интервал в целых пикселях: у пиксельного шрифта строки
    переноса иначе слипаются, а дробный интервал его мылит."""
    try:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_line_height_new_absolute(px * Pango.SCALE))
        label.set_attributes(attrs)
    except (AttributeError, TypeError):
        pass


def run_serial(args):
    """Команду — в фоне, но строго по очереди: быстрые щелчки «док → XP»
    не должны запускать и гасить панели наперегонки."""
    global _serial_q
    if _serial_q is None:
        import queue
        import threading
        _serial_q = queue.Queue()

        def worker():
            while True:
                cmd = _serial_q.get()
                try:
                    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     start_new_session=True).wait(timeout=30)
                except (OSError, subprocess.TimeoutExpired):
                    pass
        threading.Thread(target=worker, daemon=True).start()
    _serial_q.put(list(args))


def _hex(cr, color, a=1.0):
    c = color.lstrip("#")
    cr.set_source_rgba(int(c[0:2], 16) / 255, int(c[2:4], 16) / 255, int(c[4:6], 16) / 255, a)


def _rrect(cr, x, y, w, h, r):
    r = min(r, w / 2, h / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def _pixel_text(cr, text, x, y, color, a=1.0, px=8):
    """Надпись пиксельным шрифтом в родном размере (8 px — без мыла)."""
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string("PxPlus HP 100LX 6x8 Jarvis")
    fd.set_absolute_size(px * Pango.SCALE)
    layout.set_font_description(fd)
    layout.set_text(text, -1)
    _ink, log = layout.get_pixel_extents()
    cr.move_to(round(x), round(y - log.height / 2))
    _hex(cr, color, a)
    PangoCairo.show_layout(cr, layout)
    return log.width


def draw_bottom_look(cr, w, h, key, pal):
    """Схема нижней панели: экран с баром сверху и двумя окнами; внизу —
    пусто, док по центру или полоса XP с «Пуском» слева и треем справа."""
    w, h = int(w), int(h)
    _hex(cr, pal["surface"])
    _rrect(cr, 0, 0, w, h, 6)
    cr.fill()
    # бар сверху и окна — приглушённо, чтобы глаз шёл к низу
    _hex(cr, pal["primary"], 0.28)
    _rrect(cr, 6, 5, w - 12, 5, 2)
    cr.fill()
    low = h - (22 if key == "xp" else 26 if key == "dock" else 10)
    top, gap = 16, 6
    ww = (w - 12 - gap) / 2
    for i in range(2):
        x = 6 + i * (ww + gap)
        _hex(cr, pal["surface_high"], 1.0 if i == 0 else 0.7)
        _rrect(cr, round(x), top, round(ww), low - top, 3)
        cr.fill()
        _hex(cr, pal["primary"], 0.35 if i == 0 else 0.15)
        cr.set_line_width(1)
        _rrect(cr, round(x) + 0.5, top + 0.5, round(ww) - 1, low - top - 1, 3)
        cr.stroke()
    if key == "none":
        # пустой низ: пунктир по краю — «здесь ничего»
        _hex(cr, pal["on_surface_variant"], 0.35)
        cr.set_line_width(1)
        cr.set_dash([3, 3])
        cr.move_to(8, h - 4.5)
        cr.line_to(w - 8, h - 4.5)
        cr.stroke()
        cr.set_dash([])
    elif key == "dock":
        n, cell, pad = 5, 12, 4
        dw = n * cell + (n - 1) * pad + 2 * pad + 2
        dx, dy, dh = (w - dw) // 2, h - 20, 16
        _hex(cr, pal["surface_highest"])
        _rrect(cr, dx, dy, dw, dh, 5)
        cr.fill()
        _hex(cr, pal["primary"], 0.5)
        cr.set_line_width(1)
        _rrect(cr, dx + 0.5, dy + 0.5, dw - 1, dh - 1, 5)
        cr.stroke()
        for i in range(n):
            x = dx + pad + 1 + i * (cell + pad)
            _hex(cr, pal["primary"] if i == 1 else pal["on_surface_variant"], 1.0 if i == 1 else 0.45)
            _rrect(cr, x, dy + 2, cell, cell, 3)
            cr.fill()
    else:
        bh = 16
        by = h - bh
        _hex(cr, pal["surface_highest"])
        cr.rectangle(0, by, w, bh)
        cr.fill()
        _hex(cr, pal["primary"], 0.5)
        cr.rectangle(0, by, w, 1)
        cr.fill()
        # «Пуск»
        sw = 40
        _hex(cr, pal["primary"])
        _rrect(cr, 2, by + 2, sw, bh - 4, 4)
        cr.fill()
        _pixel_text(cr, "Пуск", 2 + (sw - 24) // 2, by + bh / 2, pal["on_primary"])
        # кнопки окон; на узкой плитке (01.10.2026 — плитки стали ~130 px) —
        # одна кнопка и трей без значков, иначе всё налезает друг на друга
        narrow = w < 170
        for i, bw in enumerate((28,) if narrow else (34, 34)):
            x = 2 + sw + 6 + i * (bw + 4)
            _hex(cr, pal["primary"] if i == 0 else pal["on_surface_variant"], 0.35 if i == 0 else 0.2)
            _rrect(cr, x, by + 3, bw, bh - 6, 2)
            cr.fill()
        # трей и часы
        clock_w = 30
        tx = w - clock_w - 6
        tray = 4 if narrow else 26
        _hex(cr, pal["surface_high"])
        _rrect(cr, tx - tray, by + 2, clock_w + tray + 4, bh - 4, 3)
        cr.fill()
        for i in range(0 if narrow else 3):
            _hex(cr, pal["on_surface_variant"], 0.7)
            cr.rectangle(tx - 22 + i * 7, by + 6, 4, 4)
            cr.fill()
        _pixel_text(cr, "12:00", tx, by + bh / 2, pal["on_surface"])


# ── быстрый запуск ─────────────────────────────────────────────────────────
# При построении окна разделы читают состояние ~40 вызовами вспомогательных
# скриптов, и шли они по очереди: ~1.5 с из 2.5 с до появления окна (замер
# 29.09.2026 — пользователь жаловался, что Super+/ открывается секунды через 2–3).
# Теперь окно запоминает, какие ЧТЕНИЯ делали его разделы при построении, и в
# следующий раз запускает их все разом в самом начале; run() берёт готовый
# ответ. Команда, которой в прошлый раз не было, просто выполнится как раньше.
# Команды, что-то меняющие, в список не попадают (READ_ONLY_SKIP).
PREFETCH_FILE = os.path.expanduser("~/.cache/jarvis/settings_prefetch_pages.json")
PREFETCH_OLD = os.path.expanduser("~/.cache/jarvis/settings_prefetch.json")
READ_ONLY_SKIP = {"set", "on", "off", "apply", "try", "save", "restore", "toggle"}
# Раунд 8 (03.10.2026): чтения запоминаются ПО СТРАНИЦАМ и запускаются так же.
# Раньше все ~70 стартовали разом до первого кадра: сам запуск процессов стоил
# ~0,5 с главного потока, и ещё дольше они отнимали процессор у постройки окна
# (замер: 2,0–2,4 с до кадра против ~1,0 с с чтениями одной страницы; процессор
# в тот день был зажат на 1,2 ГГц, без этого цифры втрое меньше). Теперь до кадра
# стартуют только чтения открываемой страницы, остальные — перед постройкой своей
# страницы в простое (build_rest). Файл: {страница: [команда, …]} — под новым
# именем, чтобы копии прежнего кода (settings_app.py.bak-*) не читали чужой вид;
# пока его нет, прежний файл — один общий список — берётся как группа «*» и
# запускается целиком, один раз.
_plan = None              # страница -> [tuple(args)]: что она читала в прошлый раз
_plan_dirty = False
_started = set()          # страницы, чьи чтения в этом круге уже запущены
_prefetched = {}          # tuple(args) -> Popen, запущенный заранее
_reading_page = None      # страница, которая строится сейчас (ensure_page)
_reading = []             # её чтения — для следующего раза
_round = 0                # номер круга чтений (резидент перечитывает при каждом показе)


def prefetch_load():
    global _plan
    if _plan is not None:
        return
    _plan = {}
    for path in (PREFETCH_FILE, PREFETCH_OLD):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                data = {"*": data}
            _plan = {str(k): [tuple(c) for c in v] for k, v in data.items()}
            break
        except (OSError, ValueError, TypeError, AttributeError):
            continue


def prefetch_page(key):
    """Запустить разом чтения одной страницы (если в этом круге ещё не запущены).
    Возвращает, сколько процессов стартовало."""
    prefetch_load()
    n = 0
    for group in (key, "*"):
        if group in _started:
            continue
        _started.add(group)
        for c in _plan.get(group, ()):
            if not c or READ_ONLY_SKIP & set(c) or c in _prefetched:
                continue
            try:
                _prefetched[c] = subprocess.Popen(list(c), stdout=subprocess.PIPE,
                                                  stderr=subprocess.DEVNULL, text=True)
                n += 1
            except OSError:
                pass
    return n


def prefetch_wait(key, cb):
    """Позвать cb() в главном цикле, когда чтения страницы `key` закончатся. Ждёт
    отдельный поток, главный цикл свободен: окно не замирает на время ожидания
    (раньше постройка страницы сама стояла на communicate). Чтение зависло —
    через 3 с строим как есть."""
    procs = [_prefetched[c] for c in (_plan or {}).get(key, ()) if c in _prefetched]
    if not procs:
        GLib.idle_add(cb, priority=GLib.PRIORITY_LOW)
        return

    def wait():
        deadline = time.monotonic() + 3
        for p in procs:
            try:
                p.wait(timeout=max(0.05, deadline - time.monotonic()))
            except (subprocess.TimeoutExpired, OSError):
                pass
        GLib.idle_add(cb, priority=GLib.PRIORITY_LOW)
    threading.Thread(target=wait, daemon=True).start()


def prefetch_drop():
    """Брошенные заготовки (не пригодились или устарели) — не оставлять зомби."""
    for p in _prefetched.values():
        try:
            p.kill()
            p.wait(timeout=1)
        except (OSError, subprocess.TimeoutExpired):
            pass
    _prefetched.clear()


def prefetch_stale():
    """Настройку только что изменили: ответы чтений, запущенных заранее, могут
    быть уже неверны — выбросить; страницы спросят заново, когда будут строиться."""
    if _prefetched:
        prefetch_drop()
        _started.clear()


def prefetch_start(page=None):
    """Новый круг чтений: прежние ответы устарели; чтения страницы `page` стартуют
    сразу. Возвращает номер круга (build_rest чужого круга сам останавливается)."""
    global _round
    _round += 1
    prefetch_drop()
    _started.clear()
    if page:
        prefetch_page(page)
    return _round


def prefetch_note(key):
    """Страница построена: запомнить её чтения для следующего запуска."""
    global _reading_page, _plan_dirty
    prefetch_load()
    cmds = list(dict.fromkeys(_reading))
    if _plan.get(key) != cmds:
        _plan[key] = cmds
        _plan_dirty = True
    _reading_page = None
    del _reading[:]


def prefetch_finish(rnd=None):
    """Все разделы построены: прибрать брошенные процессы, записать список чтений.
    `rnd` — круг, который закончился; уже идёт следующий — его процессы не трогать."""
    global _plan_dirty
    if rnd is None or rnd == _round:
        prefetch_drop()
    if not _plan_dirty or _plan is None:
        return
    if all(k in _plan for k in PAGE_ORDER):      # по страницам знаем всё — общий список не нужен
        _plan.pop("*", None)
    try:
        os.makedirs(os.path.dirname(PREFETCH_FILE), exist_ok=True)
        tmp = PREFETCH_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: [list(c) for c in v] for k, v in _plan.items()}, f, ensure_ascii=False)
        os.replace(tmp, PREFETCH_FILE)
        _plan_dirty = False
    except OSError:
        pass


def run(*args):
    key = tuple(str(a) for a in args)
    if _reading_page is not None and not READ_ONLY_SKIP & set(key):
        _reading.append(key)
    p = _prefetched.pop(key, None)
    if p is not None:
        try:
            return p.communicate(timeout=5)[0].strip()
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()
            return ""
    try:
        return subprocess.run(list(args), capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def blur_outputs():
    """[(выход, подпись, состояние)] — размытие обоев отдельно по мониторам."""
    res = []
    for line in run("python3", BLUR, "outputs").splitlines():
        parts = line.split("\t")
        if len(parts) == 3:
            res.append(tuple(parts))
    return res


# ── состояние системы ─────────────────────────────────────────────────────
def brightness_get():
    try:
        return int(int(run("brightnessctl", "g")) / int(run("brightnessctl", "m")) * 100)
    except ValueError:
        return 50


def last_number(path, default):
    try:
        with open(path) as f:
            return max(0, min(100, int(float(f.read().strip()))))
    except (OSError, ValueError):
        return default


def kbd_light_get():
    """Подсветка клавиатуры ноутбука в процентах или None, если её нет."""
    parts = run("brightnessctl", "-d", KBD_LED, "-m").split(",")
    if len(parts) < 5 or not parts[2].isdigit():
        return None
    try:
        return round(int(parts[2]) * 100 / max(1, int(parts[4])))
    except ValueError:
        return None


def kbd_light_set(val):
    """Яркость подсветки клавиатуры. Ненулевой уровень запоминается там же, где
    его хранит kbdlight: гашение по простою (idle_dim) и «kbdlight on» вернут его."""
    val = int(val)
    run_serial(["brightnessctl", "-d", KBD_LED, "-q", "set", "%d%%" % val])
    if val > 0:
        try:
            with open(KBD_LEVEL, "w") as f:
                f.write("%d\n" % round(val * 255 / 100))
        except OSError:
            pass


def night_state():
    """(включён, теплота) с учётом расписания 22:00–5:00.

    В файле три поля: состояние, время записи, теплота. Читается через
    split() с индексами, а не распаковкой в две переменные: третье поле
    появилось позже, и жёсткая распаковка на нём падала.
    """
    now = datetime.datetime.now()
    today = now.replace(second=0, microsecond=0)
    marks = [today.replace(hour=5, minute=0), today.replace(hour=22, minute=0),
             (today - datetime.timedelta(days=1)).replace(hour=22, minute=0)]
    boundary = max(m for m in marks if m <= now)
    warmth = 65
    try:
        with open(NIGHT_STATE) as f:
            parts = f.read().split()
        if len(parts) > 2:
            warmth = max(0, min(100, int(float(parts[2]))))
        if len(parts) > 1 and float(parts[1]) >= boundary.timestamp():
            return parts[0] == "on", warmth
    except (OSError, ValueError, IndexError):
        pass
    return (now.hour >= 22 or now.hour < 5), warmth


def night_set(on, warmth):
    """Ночной режим — через scripts/night_mode.py.

    Раньше здесь звали hyprctl напрямую, и когда демон hyprsunset не работал,
    переключатель молча делал вид, что сработал (так режим и «сломался»
    12.09.2026). night_mode.py сам поднимает демон и пишет состояние.
    """
    run("python3", NIGHT_MODE, *(["on", str(int(warmth))] if on else ["off"]))


def shot_get():
    try:
        with open(SHOT_STATE) as f:
            val = f.read().strip()
    except OSError:
        val = ""
    return val if val in dict((k, 1) for k, _, _ in EDITORS) else "ksnip"


def shot_set(key):
    os.makedirs(os.path.dirname(SHOT_STATE), exist_ok=True)
    with open(SHOT_STATE, "w") as f:
        f.write(key + "\n")


def nvim_center_get():
    try:
        with open(NVIM_CENTER_STATE) as f:
            return f.read().strip() != "off"
    except OSError:
        return True


def nvim_center_set(on):
    os.makedirs(os.path.dirname(NVIM_CENTER_STATE), exist_ok=True)
    with open(NVIM_CENTER_STATE, "w") as f:
        f.write(("on" if on else "off") + "\n")


def nvim_darkbg_get():
    try:
        with open(NVIM_DARKBG_STATE) as f:
            return f.read().strip() == "on"
    except OSError:
        return False


def nvim_darkbg_set(on):
    os.makedirs(os.path.dirname(NVIM_DARKBG_STATE), exist_ok=True)
    with open(NVIM_DARKBG_STATE, "w") as f:
        f.write(("on" if on else "off") + "\n")


def dashboard_login_get():
    return not os.path.exists(DASHBOARD_OFF)


def dashboard_login_set(on):
    subprocess.run(["python3", DASHBOARD, "autostart", "on" if on else "off"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def savage_get():
    try:
        spec = importlib.util.spec_from_file_location("savage_battery", SAVAGE)
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return bool(m.is_savage_active())
    except Exception:
        return False


# ── вид «Skeet» (01.10.2026) ────────────────────────────────────────────────
# Второй вид Настроек — по образцу меню gamesense/skeet (только оформление):
# многослойная тёмная рамка, тонкая градиентная полоса сверху, почти чёрный фон
# с точечным узором, слева узкая колонка вкладок с крупными значками, секции —
# групповые блоки с заголовком в рамке, по две колонки; шрифт 12 px, острые
# углы, галочки-квадратики и ползунки с градиентом акцента. Все цвета — из
# палитры обоев (просьба пользователя: «скит меню тоже должен подхватывать цвета»).
# Переключатель «Обычный / Skeet» — внизу левой колонки; выбор помнится в
# SKIN_FILE и применяется сразу: стили, левая колонка и страницы перестраиваются
# на месте. Обычный вид при этом не меняется: стили skeet привязаны к классу
# .skeet корневой коробки, которого в обычном виде нет.
SKIN_FILE = os.path.expanduser("~/.config/hypr/state/settings-skin")
TITLE_H = 24               # полоса заголовка в духе XP
# Раунд 6 (02.10.2026, решение пользователя): «Обычный» и «XP» — один вид Default в
# двух режимах (Dark — бывший «Обычный», Light — бывший «XP»), плюс новый вид
# Beta (по образцу Настроек AngelOS) с тем же переключателем режима. Skeet
# режима не знает — у него единый стиль. Режим — отдельный файл MODE_FILE,
# общий для Default и Beta. Прежние значения SKIN_FILE (normal, xp) понимаются.
MODE_FILE = os.path.expanduser("~/.config/hypr/state/settings-mode")
SKINS = [("default", "Default"), ("skeet", "Skeet"), ("beta", "Beta")]
# Значки режима: солнце и луна (mdi weather-sunny / weather-night).
MODES = [("light", "Light"), ("dark", "Dark")]
MODE_ICONS = {"light": "\U000f0599", "dark": "\U000f0594"}
SKIN_LEGACY = {"normal": ("default", "dark"), "обычный": ("default", "dark"),
               "xp": ("default", "light")}
# Beta: имя в карточке пользователя (то же, что в шапке «Пуска», start_menu.py)
# и аватарка; группы пунктов меню — по 2–3 с просветом между группами.
BETA_USER = "staticxyzz"
BETA_AVATAR = os.path.expanduser("~/.cache/avatar.png")
BETA_GROUP_STARTS = {"apps", "misc"}
# Значки вкладок skeet — НАСТОЯЩИЕ, перенесены со снимков меню skeet (02.10.2026:
# «иконки должны быть как в скит-меню»): маски прозрачности PNG 48×48 в
# scripts/skeet_icons/, вырезанные из снимка по яркости, — заливаются цветом
# состояния. Visuals — полусолнце, Fonts — керамбит, Cursors — прицел, Config —
# силуэт человека, Misc — шестерёнки. Остальным пунктам в skeet вкладок нет:
# их маски — сплошные силуэты в той же манере (waybar, notify, xp, power, apps).
SK_ICON_DIR = os.path.join(HERE, "skeet_icons")
SK_ICONS = {"waybar": "waybar", "fonts": "skins", "cursor": "aim", "notify": "notify",
            "xp": "xp", "power": "power", "apps": "rage", "visuals": "visuals",
            "misc": "misc", "config": "players"}
SK_RAIL_W = 76             # колонка вкладок
SK_TAB_H = 52              # высота вкладки (10 вкладок, значок ~40 px)
SK_FRAME = 6               # слои рамки окна: 1 + 3 + 1 + 1
SK_COL_GAP = 10
# Ширина колонки групп: окно − рамка − вкладки − поля страницы, пополам.
SK_COL_W = (WIN_W - 2 * SK_FRAME - SK_RAIL_W - 2 * 10 - SK_COL_GAP) // 2
SK_ROW_W = SK_COL_W - 2 - 2 * 10
SK_SLIDER_W = 110


# ── сброс страницы (раунд 7, 03.10.2026) ────────────────────────────────────
# «Сбросить эту страницу · изменено здесь: N»: строка с управляющим элементом,
# у которой есть умолчание, попадает в реестр страницы (row → register), внизу
# страницы — счётчик отличий и кнопка сброса (add_reset_bar). Умолчание — то, как
# ведёт себя система БЕЗ файла состояния: значения взяты из самих скриптов
# (рядом указано, откуда). Чего здесь нет — не считается и не сбрасывается:
#  * сиюминутное и железо: яркости, «Не беспокоить», «Ночной режим»,
#    «Энергосбережение», Savage Mode, «Не отключать экран», «Виджеты на обоях»
#    вкл/выкл, «Показать поверх окон»;
#  * выбор, а не настройка: шрифты, курсор, приложения по умолчанию, значки
#    папок, темы экранов входа и блокировки, вид и режим самих Настроек;
#  * «Форма верхней панели»: у bar_style.py умолчания нет (вид — ссылка
#    looks/current.*, без неё — пустая строка).
# Строки с именем монитора или группы в подписи получают умолчание прямо в
# вызове row(..., default=…): «Размытие — …», «Вид виджетов — …», «Звук: …».
# Отступы бара — одна составная настройка «Отступы бара» (page_waybar).
DEFAULTS = {
    "waybar": {
        "Скругление углов бара": 0,                  # bar_rounding.py DEFAULT
        "Кнопка «Пуск» — пиксельная": False,         # start_button.py DEFAULT = "nerd"
        "Bongo Cat в баре": True,                    # bongo_cat.py: нет флага bongo-off
        "Эквалайзер": "blocks",                      # cava_bar.py: нет bar-vis — блоки
        "Меню выключения — новые значки": False,     # wlogout_icons.py status → "old"
        "Попапы приклеены к бару": False,            # popup_theme.attached(): нет флага
        "Действие на правый клик": True,             # desktop_menu.py: нет desktop-menu-off
        "Вид меню": "xp",                            # desktop_menu.py style → "xp"
        "Форма панели": "dock",                      # bottom_bar.py get(): нет состояния и dock-off
        "Появление": "always",                       # bottom_bar.py get_show()
        "Верхний бар": "always",                     # top_bar.py get_mode(): нет файла — always
        "Список столов": "top",                      # top_bar.py ws_place()
        "Плотность фона бара": 88,                   # top_bar.py: как у вида бара (alpha 0.88)
        "Размытие под баром": True,                  # top_bar.py: нет флага bar-blur-off
        "Окна и панель": "on",                       # bottom_bar.py get_gap()
        "Тексты песен": True,                        # lyrics_bar.py: нет флага lyrics-off
        "Окна в доке": "all",                        # dock.py get_mode()
    },
    "fonts": {
        "Менять и в открытых окнах": False,          # app_fonts.py scope() → "new"
        "LibreWolf: навязывать шрифт сайтам": False,  # app_fonts.py browser_fonts() → "off"
        "Helium: навязывать шрифт сайтам": False,
        "Zen: навязывать шрифт сайтам": False,       # app_fonts.py zen_fonts() → "off"
    },
    "apps": {
        "Эффект экрана": "off",                      # kitty_shader.py get() → "off"
        "След курсора": "off",
        "Отдача и молнии": "off",
        "Neovim: курсор по центру": True,            # nvim_center_get(): нет файла — вкл
        "Neovim: тёмный фон": False,                 # nvim_darkbg_get()
        "ЭЛТ-монитор в Zen": False,                  # zen-crt: нет файла — off
        "Дашборд при входе": True,                   # dashboard: нет флага dashboard.off
        "Окно памяти": "top-right",                  # popup_theme.PLACE_DEFAULT
        "Прозрачность Obsidian": 96,                 # obsidian_opacity.py DEFAULT
    },
    "visuals": {
        "Теплота": 65,                               # night_mode.py DEFAULT_WARMTH
        "Сила размытия": "2",                        # wallpaper_blur.py DEFAULT_LEVEL
        "Пиксельные обои": False,                    # wallpaper_pixel.py: нет состояния — off
        "Размер пикселя": "2",                       # wallpaper_pixel.py level → 2 (средний)
        "Прозрачный фон виджетов": True,             # desktop_widgets.py STYLE_DEFAULT
        "Тень у виджетов": False,                    # desktop_widgets.py STYLE_DEFAULT["shadow"]
        "Плотность фона": 62,
        "Размытие под виджетом": 16,
        "Анимация под окнами": False,
        "Экран блокировки — свой (с обводкой кнопок)": False,   # нет state/lock-engine — hyprlock
    },
    "config": {},                                    # «Стиль системы» в сброс не входит, как выбор вида
    "misc": {
        "Редактор": "ksnip",                         # shot_get()
        "Скругление окон": 4,                        # window_rounding.py DEFAULT
        "Окно с фокусом — по центру": False,         # ribbon_center.py DEFAULT = "fit"
        "Наведение мыши забирает фокус": False,      # mouse_focus.py DEFAULT = "detached"
        "Эффект открытия/закрытия окон": "off",      # window_fx.py get(): нет файла — off
        "Уведомление при смене трека": True,         # track_notify.py: нет флага -off
        "Вид как в Noctalia": False,                 # notif-look: без вставки в style.css — off
        "Громкость уведомлений": 100,                # ui_sound.py get_notify_volume()
        "Звуки интерфейса": True,                   # ui_sound.py: нет флага ui-sound-off
        "Набор звуков": "xp",                        # ui_sound.py get_pack()
        "Громкость звуков": 75,                      # ui_sound.py VOLUME_DEFAULT
        "Меню питания (кнопка в баре)": "wlogout",   # power_view.py get()
        "Встряхни мышь — найти курсор": True,        # cursor_shake.py: нет флага -off
        "Авто «Не беспокоить» при записи экрана": True,   # auto_dnd.py: нет флага -off
    },
}
# Группы звуков интерфейса: включена ли по умолчанию — ui_sound.py GROUPS.
UI_SOUND_GROUP_DEFAULTS = {"system": True, "capture": True, "devices": True, "menu": True,
                           "timer": True, "notify": False, "windows": False, "mouse": False}
_NODEF = object()          # «умолчание не задано» (None — законное значение)


# ── резидент (раунд 8, 03.10.2026) ──────────────────────────────────────────
# Закрытое окно не уничтожается, а прячется; процесс ждёт следующего запуска и
# показывает окно сразу (см. ask_resident наверху, App.on_close, park, revive).
# Спрятанный процесс ничего не делает: ни таймеров, ни опросов — только сокет в
# главном цикле. Выключатель — файл RESIDENT_OFF (есть — крестик закрывает
# насовсем, как было до раунда 8); в окне — Config → «Быстрое открытие».
RESIDENT_OFF = os.path.expanduser("~/.config/hypr/state/settings-resident-off"
                                  + ("-test" if TEST else ""))      # у проверок — свой


def resident_on():
    return not os.path.exists(RESIDENT_OFF)


def resident_set(on):
    try:
        if on:
            if os.path.exists(RESIDENT_OFF):
                os.remove(RESIDENT_OFF)
        else:
            os.makedirs(os.path.dirname(RESIDENT_OFF), exist_ok=True)
            with open(RESIDENT_OFF, "w") as f:
                f.write("off\n")
    except OSError:
        pass


def look_stamp():
    """Отпечаток того, чего спрятанный процесс сам не заметит: свой код и модули
    рядом (правка файла), палитра обоев и акцент skeet (смена обоев), скругление
    окон. Изменился, пока окно спрятано, — процесс запускает себя заново (App.
    show_window): иначе Super+/ поднимал бы старый код в старых цветах."""
    out = []
    for path in (os.path.abspath(__file__), popup_theme.__file__, login_theme.__file__,
                 wm.__file__, os.path.join(HERE, "xpbar_colors.py"), CURSOR_THEME):
        try:
            st = os.stat(path)
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    for path in (popup_theme.PALETTE, os.path.expanduser("~/.cache/matugen/vivid.txt"),
                 os.path.expanduser("~/.config/hypr/state/window-rounding")):
        try:
            with open(path, "rb") as f:
                out.append(f.read())
        except OSError:
            out.append(None)
    return out


def parse_args(argv):
    """[страница] [--skin=…] [--mode=…] → (страница или None, {skin, mode, …})."""
    opts = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    words = [a for a in argv if not a.startswith("--")]
    return (words[0] if words else None), opts


def plural_settings(n):
    """«1 настройку», «3 настройки», «5 настроек» — для вопроса о сбросе."""
    if n % 10 == 1 and n % 100 != 11:
        return "%d настройку" % n
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "%d настройки" % n
    return "%d настроек" % n


def _state_word(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip().lower()
    except (OSError, ValueError):
        return ""


def view_norm(skin, mode=None):
    """(вид, режим) из любых написаний: прежние normal/«обычный» → default+dark,
    xp → default+light (прежнее имя вида задаёт и режим); незнакомое → default,
    dark."""
    skin = (skin or "").strip().lower()
    mode = (mode or "").strip().lower()
    if skin in SKIN_LEGACY:
        skin, mode = SKIN_LEGACY[skin]
    if skin not in dict(SKINS):
        skin = "default"
    if mode not in dict(MODES):
        mode = "dark"
    return skin, mode


def view_get():
    """Сохранённые (вид, режим). Нет файлов — default, dark (как было «Обычный»)."""
    return view_norm(_state_word(SKIN_FILE), _state_word(MODE_FILE))


def view_set(skin, mode):
    skin, mode = view_norm(skin, mode)
    for path, v in ((SKIN_FILE, skin), (MODE_FILE, mode)):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w") as f:
                f.write(v + "\n")
            os.replace(tmp, path)
        except OSError:
            pass


def look_of(skin, mode):
    """Какое оформление строить: normal (Default·Dark), xp (Default·Light),
    skeet или beta. У beta режим — только цвета (beta_css), виджеты те же."""
    if skin in ("skeet", "beta"):
        return skin
    return "xp" if mode == "light" else "normal"


def beta_tiles(pal, n):
    """Цвета плиток-значков меню Beta: тон primary / tertiary / secondary палитры
    обоев, у каждой следующей тройки сдвинутый (+60°, −60°, +120°); насыщенность и
    светлота общие — чтобы светлый значок читался на любой плитке."""
    import colorsys
    out = []
    shifts = (0.0, 60.0, -60.0, 120.0)
    bases = [pal["primary"], pal["tertiary"], pal["secondary"]]
    for i in range(n):
        c = bases[i % 3].lstrip("#")
        r, g, b = (int(c[j:j + 2], 16) / 255 for j in (0, 2, 4))
        h, _l, _s = colorsys.rgb_to_hls(r, g, b)
        h = (h + shifts[(i // 3) % len(shifts)] / 360.0) % 1.0
        r, g, b = colorsys.hls_to_rgb(h, 0.47, 0.46)
        out.append("#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255)))
    return out


def _mix(a, b, t):
    """Смесь двух цветов #rrggbb: t=0 — a, t=1 — b."""
    a, b = a.lstrip("#"), b.lstrip("#")
    ca = [int(a[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(round(x * (1 - t) + y * t) for x, y in zip(ca, cb))


def skeet_colors(pal):
    """Цвета skeet из палитры обоев. Серые оригинала (#111, #282828, #3c3c3c…)
    чуть подкрашены акцентом — как bar-bg у бара; акцент — насыщенный тон обоев
    (vivid.txt, ближе к яркому зелёному оригинала), иначе primary."""
    acc = pal["primary"]
    try:
        v = open(os.path.expanduser("~/.cache/matugen/vivid.txt")).read().strip()
        if v.startswith("#") and len(v) == 7:
            acc = v
    except OSError:
        pass

    def g(level, t=0.05):
        return _mix("#%02x%02x%02x" % (level, level, level), acc, t)
    return {
        "acc": acc,
        "acc_l": _mix(acc, "#ffffff", 0.22),
        "acc_d": _mix(acc, "#000000", 0.40),
        "bg": g(0x13), "rail": g(0x0c, 0.04), "field": g(0x1b), "field_l": g(0x24),
        "line1": g(0x3c, 0.08), "line2": g(0x28, 0.06), "line3": g(0x0a, 0.03),
        "gline": g(0x30, 0.08), "gdark": g(0x0e, 0.03),
        "icon": g(0x5c, 0.10), "icon_hover": g(0x8c, 0.14),
        "icon_on": _mix("#e2e2e2", acc, 0.22),
        "text": _mix("#cdcdcd", pal["on_surface"], 0.35),
        "text_dim": g(0x92, 0.10),
        "dot": g(0x18, 0.05),
        # полоса сверху — три тона палитры, ниже — та же полоса темнее
        "strip": [acc, pal["tertiary"], pal["secondary"]],
        "err": pal["error"],
    }


def skeet_split(heights, gap=12, slack=12):
    """Кому в какую колонку skeet (0 — левая, 1 — правая): высоты групп по порядку
    страницы → список колонок. Раунд 8 (03.10.2026, «остаются пустоты»): раньше
    группа шла «в ту колонку, что сейчас короче» — и длинная группа в конце
    (Visuals: «Виджеты на обоях») оставляла под соседней колонкой дыру в 200 px.
    Теперь перебираются все разбиения (групп в ряду — единицы, первая всегда
    слева) и берётся то, где высоты колонок ближе всего; из почти равных (в
    пределах slack px) — то, где меньше нарушен порядок чтения «левая колонка
    сверху вниз, затем правая»."""
    n = len(heights)
    if n < 2:
        return [0] * n
    if n > 14:                                   # столько групп в ряду не бывает — жадно
        side, h = [], [0, 0]
        for x in heights:
            i = 0 if h[0] <= h[1] else 1
            side.append(i)
            h[i] += x + gap
        return side
    cand = []
    for mask in range(0, 1 << n, 2):             # бит 0 всегда 0: первая группа слева
        h = [0, 0]
        cnt = [0, 0]
        inv = 0                                  # пар «правая раньше левой»
        for i, x in enumerate(heights):
            k = mask >> i & 1
            h[k] += x
            cnt[k] += 1
            if not k:
                inv += cnt[1]
        diff = abs(h[0] + gap * max(0, cnt[0] - 1) - h[1] - gap * max(0, cnt[1] - 1))
        cand.append((diff, inv, mask))
    best = min(c[0] for c in cand)
    mask = min((c for c in cand if c[0] <= best + slack), key=lambda c: (c[1], c[0]))[2]
    return [mask >> i & 1 for i in range(n)]


def skeet_dots(c):
    """Плитка 4×4 точечного узора фона (PNG в кэше, по цвету — своя)."""
    path = os.path.expanduser("~/.cache/jarvis/skeet-dots-%s-%s.png"
                              % (c["bg"].lstrip("#"), c["dot"].lstrip("#")))
    if os.path.exists(path):
        return path
    bg = [int(c["bg"][i:i + 2], 16) for i in (1, 3, 5)]
    dot = [int(c["dot"][i:i + 2], 16) for i in (1, 3, 5)]
    data = bytearray()
    for y in range(4):
        for x in range(4):
            data += bytes(dot if (x, y) in ((0, 0), (2, 2)) else bg)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        pb = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(bytes(data)),
                                             GdkPixbuf.Colorspace.RGB, False, 8, 4, 4, 12)
        pb.savev(path, "png", [], [])
    except (GLib.Error, OSError):
        return None
    return path


def win_rounding():
    """Скругление окон (window_rounding.py пишет его в state) — углы своей рамки."""
    try:
        with open(os.path.expanduser("~/.config/hypr/state/window-rounding")) as f:
            return max(0, min(24, int(f.read().strip())))
    except (OSError, ValueError):
        return 4


# Поиск (02.10.2026): слово запроса совпадает, если в тексте есть оно само, оно
# же в другой раскладке («ифк» → «bar», «,fh» → «бар») или любое слово из его
# группы синонимов.
_EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`"
_RU = "йцукенгшщзхъфывапролджэячсмитьбюё"
_LAYOUT = dict(zip(_EN + _RU, _RU + _EN))
SYNONYMS = [
    {"бар", "панель", "waybar", "bar", "таскбар"},
    {"звук", "громкость", "sound", "audio"},
    {"обои", "wallpaper", "фон"},
    {"шрифт", "font"},
    {"курсор", "мышь", "указатель", "cursor", "mouse"},
    {"уведомления", "notifications", "нотификации", "dnd", "не беспокоить"},
    {"питание", "power", "батарея", "энергия", "сон"},
    {"снимок", "снимки", "скриншот", "screenshot", "запись"},
    {"окна", "окно", "windows", "рамка", "border"},
    {"терминал", "kitty", "terminal"},
    {"яркость", "brightness", "подсветка"},
    {"цвет", "тема", "theme", "палитра"},
    {"виджет", "виджеты", "widget", "widgets", "дашборд", "dashboard"},
    {"буфер", "clipboard", "cliphist", "вставка"},
]


def search_variants(query):
    """[{варианты слова}, …] для запроса: слово, оно в другой раскладке и синонимы."""
    out = []
    for w in query.split():
        forms = {w, "".join(_LAYOUT.get(ch, ch) for ch in w)}
        for f in list(forms):
            if len(f) < 3:
                continue
            for group in SYNONYMS:
                if any(m.startswith(f) for m in group):
                    forms |= group
        out.append(forms)
    return out


def search_hit(text, variants):
    t = text.casefold()
    return all(any(f in t for f in forms) for forms in variants)


def resolve_page(key):
    """Ключ страницы из аргумента: прежние имена и пункты без своей страницы
    ведут на свою страницу, незнакомое — на первую."""
    key = PAGE_ALIASES.get(key, key)
    return key if key in PAGE_ORDER else PAGE_ORDER[0]


class SettingsWindow(Gtk.ApplicationWindow):
    # Какую страницу открыть при запуске: settings_app.py <ключ из TREE>
    # (прежние look|bottom|shaders|windows тоже понимает — PAGE_ALIASES). Без
    # аргумента — первая. Нужно и для снимков при правке оформления, и чтобы
    # из панелей открывать сразу нужную страницу.
    def __init__(self, app, page=None, skin=None, mode=None):
        self.start_page = resolve_page(page)
        super().__init__(application=app, title="Настройки")
        # 860×620 (01.10.2026; было 1040×760) — то же в правиле niri.
        self.set_default_size(WIN_W, WIN_H)
        self.pal = popup_theme.palette()
        self.apply_css()
        # Вид и режим: сохранённые; --skin= / --mode= из командной строки главнее
        # и запоминаются (прежние имена normal/xp тоже годятся).
        self.skin, self.mode = view_get()
        if skin or mode:
            self.skin, self.mode = view_norm(skin or self.skin, mode or self.mode)
            if skin in SKIN_LEGACY and mode:         # «--skin=xp --mode=dark»: режим явный
                self.mode = view_norm("default", mode)[1]
            view_set(self.skin, self.mode)
        self.look = look_of(self.skin, self.mode)
        self._skeet_provider = None
        self._xp_provider = None
        self._beta_provider = None
        self.skeet_rail = None
        self.beta_top = None
        self.mode_seg = None
        # История открытых разделов — для «‹ ›» вида Beta (и Alt+←/→ в любом виде).
        self._hist = [self.start_page]
        self._hist_i = 0
        self._hist_lock = False
        # Сброс страницы: реестр настроек с умолчаниями, полосы внизу страниц,
        # снимок для «Вернуть как было» (ключ страницы, [(запись, прежнее значение)]).
        self._settings = {}
        self._reset_bars = {}
        self._undo = None
        self._resetting = False
        self._page_v = {}              # ключ страницы → её коробка (для колонок skeet)
        self._sk_runs = {}             # skeet: ключ → [(группы ряда, пара, [колонки])]
        self._appeared = False         # окно уже показывалось (appear)
        self._stale = set()            # страницы с прежними значениями (резидент, new_round)
        self._warmed = False           # картинки плиток разобраны заранее (warm_previews)
        # Окно уничтожено (резидент выключен, крестик) — достройку страниц бросить.
        # Иначе цепочка build_bg шла дальше уже после закрытия: приложение перед
        # выходом дочищает главный цикл, и процесс висел ещё секунды, строя
        # невидимые страницы (поймано проверкой 03.10.2026).
        self._dead = False
        self.connect("destroy", self.on_destroy)

        # Поиск: какие строки и карточки есть в построенных разделах.
        self.query = ""
        self._building = None          # раздел, который строится прямо сейчас
        self._pending_section = None   # заголовок, ждущий своей карточки
        self._rows = []                # (раздел, виджет строки, текст для поиска)
        self._cards = []
        self._page_text = {}
        self._visible_pages = set()
        self._search_timer = None

        # Сверху — полоса заголовка в духе Windows XP (01.10.2026): за неё окно
        # таскается мышью без Super, двойной щелчок и кнопка разворачивают.
        self.outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        # Своя рамка окна (01.10.2026): рамку niri для com.jarvis.settings пользователь
        # отключил — она налезала на полосу заголовка. Активное окно — акцент,
        # неактивное — приглушённая; в skeet её заменяют слои рамки skeet.
        self.outer.get_style_context().add_class("win-frame")
        self.connect("notify::is-active", self.on_active_changed)
        self.add(self.outer)
        self.outer.pack_start(self.build_titlebar(), False, False, 0)
        root = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.root = root
        self.outer.pack_start(root, True, True, 0)

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(120)
        empty = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        empty.set_valign(Gtk.Align.CENTER)
        for text, cls in (("\U000f0349", "empty-icon"), ("Ничего не нашлось", "empty"),
                          ("Esc — очистить поиск", "page-sub")):
            l = Gtk.Label(label=text)
            l.get_style_context().add_class(cls)
            empty.pack_start(l, False, False, 0)
        self.stack.add_named(empty, "_empty")

        self.rail = self.build_rail()
        root.pack_start(self.rail, False, False, 0)
        # Справа — страница; над ней полоса skeet (вкладки второго уровня и поиск),
        # в обычном виде скрытая и места не занимающая.
        self.main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.skeet_top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.skeet_top.get_style_context().add_class("skeet-top")
        self.skeet_top.set_no_show_all(True)
        self.main.pack_start(self.skeet_top, False, False, 0)
        self.main.pack_start(self.stack, True, True, 0)
        root.pack_start(self.main, True, True, 0)
        self.connect("key-press-event", self.on_key)
        if self.look == "skeet":
            self.enter_skeet()
        elif self.look == "xp":
            self.enter_xp()
        elif self.look == "beta":
            self.enter_beta()

        # Разделы строятся по требованию (29.09.2026): сразу — только тот, что
        # открывается, остальные — после появления окна, по одному в простое
        # цикла GTK (build_rest). Щёлкнули по ещё не построенному — строится
        # тут же (ensure_page). Раньше все десять строились до показа окна, и
        # Super+/ открывался с задержкой в пару секунд.
        self.builders = {
            "waybar": self.page_waybar, "fonts": self.page_fonts,
            "cursor": self.page_cursor, "apps": self.page_apps,
            "visuals": self.page_screen, "misc": self.page_misc,
            "config": self.page_config,
        }
        self.ensure_page(self.start_page)

    def on_destroy(self, *_a):
        self._dead = True
        self._stale = set()
        prefetch_drop()

    def ensure_page(self, key):
        global _reading_page
        if self._dead or self.stack.get_child_by_name(key) is not None \
                or key not in self.builders:
            return
        prefetch_page(key)               # её чтения — разом (если ещё не запущены)
        self._building = key
        _reading_page = key
        del _reading[:]
        try:
            page = self.builders[key]()
        finally:
            self._building = None
            self._pending_section = None
            prefetch_note(key)
        self.stack.add_named(page, key)
        self.add_reset_bar(key)
        page.show_all()
        if self.look == "skeet":
            self.skeet_columns(key)
        if self.query:
            self.apply_filter()

    def pages_todo(self):
        """Что ещё строить: разделы, которых нет, и построенные с прежними значениями
        (self._stale — резидент показал окно заново). Открытый раздел — первым."""
        todo = [k for k in self.builders
                if self.stack.get_child_by_name(k) is None or k in self._stale]
        if self._selected in todo:
            todo.remove(self._selected)
            todo.insert(0, self._selected)
        return todo

    def build_page(self, key):
        if key in self._stale:
            self.replace_page(key)
        else:
            self.ensure_page(key)

    def replace_page(self, key):
        """Построить раздел заново по свежим чтениям и подменить им прежний — на
        месте: открытый остаётся открытым, прокрутка та же, кадра между сносом
        и постройкой нет."""
        self._stale.discard(key)
        old = self.stack.get_child_by_name(key)
        if old is None:
            self.ensure_page(key)
            return
        pos = old.get_vadjustment().get_value()
        shown = self.stack.get_visible_child_name() == key
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.forget_page(key)
        self.stack.remove(old)
        old.destroy()
        self.ensure_page(key)
        if shown and not self.query:     # при поиске страницу выбирает фильтр (ensure_page)
            self.stack.set_visible_child_name(key)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        if pos:
            # после раскладки (у новой страницы ещё нет высоты), но до отрисовки
            adj = self.stack.get_child_by_name(key).get_vadjustment()
            GLib.idle_add(lambda: (adj.set_value(pos), False)[1],
                          priority=GLib.PRIORITY_HIGH_IDLE + 15)

    def build_rest(self, rnd=None):
        """Достроить остальные разделы в простое; конец — прибрать заготовки.
        `rnd` — круг чтений, для которого запущена цепочка: начался новый (окно
        показали заново, сменили вид) — эта цепочка останавливается, у нового своя."""
        if self._dead or (rnd is not None and rnd != _round):
            return False
        todo = self.pages_todo()
        if not todo:
            prefetch_finish(rnd)
            return False
        # Чтения следующего раздела стартуют уже сейчас — успеют, пока строится этот.
        for key in todo[:2]:
            prefetch_page(key)
        self.build_page(todo[0])
        return True                              # ещё позовут

    def build_bg(self, rnd, key=None):
        """То же, но не замирая на чтениях: цепочка «чтения раздела закончились
        (prefetch_wait) → построить его → запустить чтения следующего». Главный
        цикл занят только самой постройкой страницы. Так достраивается живое окно;
        build_rest — для проверок и как запасной путь."""
        if self._dead or rnd != _round:
            return False
        if key is not None:
            self.build_page(key)
        todo = self.pages_todo()
        if not todo:
            prefetch_finish(rnd)
            self.warm_previews()
            return False
        for k in todo[:2]:                       # следующему за ним — фору
            prefetch_page(k)
        prefetch_wait(todo[0], lambda: self.build_bg(rnd, todo[0]))
        return False

    def warm_previews(self):
        """Резидент: картинки тем экрана входа (фоны до 3840 px) разобрать заранее,
        в фоновом потоке, один раз за жизнь процесса. Иначе первый показ Visuals
        замирал, пока плитки разбирали их при отрисовке (замер: ~0,7 с из 0,9 с
        до окна). Без резидента не греем: открыли-закрыли — работа впустую."""
        if self._warmed or not resident_on() or not login_theme.installed():
            return
        self._warmed = True
        cache = self.__dict__.setdefault("_login_pix", {})
        keys = [k for k, _t in login_theme.variants() if k not in cache]

        def work():
            for key in keys:
                if key in cache:
                    continue
                try:
                    path = login_theme.preview(key)
                    cache[key] = (GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 480, -1, True)
                                  if path else None)
                except Exception:        # GLib.Error: файла нет или не картинка
                    cache[key] = None
        threading.Thread(target=work, daemon=True).start()

    def after_frame(self, cb, *args):
        """Позвать cb в простое ПОСЛЕ ближайшей отрисовки окна. Простой, заказанный
        сразу за show(), срабатывает раньше первого кадра (окно ещё ждёт ответа
        композитора) — и постройка следующей страницы задерживала сам показ."""
        hid = []

        def drawn(*_a):
            self.disconnect(hid.pop())
            GLib.idle_add(cb, *args, priority=GLib.PRIORITY_LOW)
            return False
        hid.append(self.connect_after("draw", drawn))

    # ── резидент: спрятать и показать заново ─────────────────────────────
    def goto(self, key):
        """Открыть страницу «с чистого листа»: без перехода, история «‹ ›» — с
        неё, прокрутка — к началу."""
        lock, self._hist_lock = self._hist_lock, True
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        try:
            self.select_page(key)
            if self._selected == key:            # строка уже была выбрана — сигнала не было
                self.ensure_page(key)
                self.stack.set_visible_child_name(key)
        finally:
            self._hist_lock = lock
            self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self._hist, self._hist_i = [key], 0
        page = self.stack.get_child_by_name(key)
        if page is not None:
            page.get_vadjustment().set_value(0)
        self.sync_beta()

    def appear(self):
        """Показать окно. Первый раз — show_all (окно, запущенное спрятанным, не
        показывалось ни разу); потом — show: что спрятано внутри, остаётся спрятано."""
        if self._appeared:
            self.show()
        else:
            self._appeared = True
            self.show_all()
        self.present()

    def park(self):
        """Окно закрыли, а процесс остаётся: привести окно к виду «только что
        открыли» (поиск пуст, первая страница, начало) и спрятать. Таймеров после
        себя не оставляет — спрятанный процесс не должен просыпаться."""
        self.search_entry.set_text("")
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        if self.query:
            self.run_search()                    # снять фильтр сразу, не таймером
        self.reset_bars_idle()
        if self._maximized:
            self.unmaximize()
        self.goto(PAGE_ORDER[0])
        self.hide()

    def view_arg(self, skin=None, mode=None):
        """Вид и режим для показа: сохранённые в файлах; --skin= / --mode= главнее."""
        s, md = view_get()
        if skin or mode:
            s2, md2 = view_norm(skin or s, mode or md)
            if skin in SKIN_LEGACY and mode:
                md2 = view_norm("default", mode)[1]
            s, md = s2, md2
        return s, md

    def revive(self, page=None, skin=None, mode=None):
        """Показать спрятанное окно. Обычный случай — страница уже построена:
        окно появляется сразу, с теми значениями, что были при закрытии, а после
        первого кадра страницы по одной подменяются построенными по свежим
        чтениям (reread): открытая — первой; щелчок по ещё не подменённой
        показывает прежнюю, без ожидания. Страницы ещё нет или сменился вид —
        она строится по свежим чтениям до показа, как при холодном старте."""
        key = resolve_page(page)
        view = self.view_arg(skin, mode)
        changed = look_of(*view) != self.look
        self.set_view(*view)             # сменился вид — всё перестроится само, новым кругом
        if changed:
            self.goto(key)
            self.appear()
        elif self.stack.get_child_by_name(key) is not None:
            self.goto(key)
            self.appear()
            self.after_frame(self.reread, key)
        else:
            rnd = self.new_round(key)
            self.goto(key)
            self.appear()
            self.after_frame(self.build_bg, rnd)

    def new_round(self, key):
        """Новый круг чтений: всё построенное считается устаревшим (подменит
        build_bg), чтения страницы `key` стартуют сразу. Возвращает номер круга."""
        self._stale = {k for k in self.builders if self.stack.get_child_by_name(k) is not None}
        return prefetch_start(key)

    def reread(self, key=None):
        """Перечитать все страницы, начиная с `key` (или открытой)."""
        key = key or self._selected
        rnd = self.new_round(key)
        prefetch_wait(key, lambda: self.build_bg(rnd, key))
        return False

    # ── оформление ────────────────────────────────────────────────────────
    # Переделано 30.09.2026 по образцу настроек angelOS: слева — поиск и
    # разделы по группам, справа — крупный заголовок и карточки с тонкой
    # рамкой, строки «подпись слева — управление справа», выбор из 2–4
    # вариантов — сегментами. Шрифт пиксельный и ТОЛЬКО 12/16/24/32 px: на
    # других размерах PxPlus мылится (память pixel-font-system). Жирного у
    # него нет — синтетический жирный тоже мылится, поэтому акцент — цветом.
    def apply_css(self):
        p = self.pal
        css = ("""
        window {
            background-color: %(surface)s; color: %(on_surface)s;
            font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono Nerd Font', monospace;
            font-size: 16px; font-weight: normal;
        }
        scrolledwindow, viewport { background: transparent; border: none; box-shadow: none; }
        /* Полоса прокрутки — тонкая, цветом палитры (01.10.2026: у темы
           Breeze-Dark она широкая, светлая и в рамке). Без кнопок-стрелок. */
        scrollbar, scrollbar.vertical, scrollbar.horizontal {
            background-color: transparent; background-image: none; border: none;
            box-shadow: none; margin: 0; padding: 0; min-width: 0; min-height: 0;
            -GtkScrollbar-has-backward-stepper: false; -GtkScrollbar-has-forward-stepper: false;
            -GtkScrollbar-has-secondary-backward-stepper: false;
            -GtkScrollbar-has-secondary-forward-stepper: false;
        }
        scrollbar trough, scrollbar contents {
            background-color: transparent; background-image: none; border: none;
            box-shadow: none; margin: 0; padding: 0; min-width: 0; min-height: 0;
        }
        scrollbar button {
            min-width: 0; min-height: 0; margin: 0; padding: 0; border: none;
            background: none; box-shadow: none; -gtk-icon-source: none; opacity: 0;
        }
        scrollbar slider {
            min-width: 4px; min-height: 24px; margin: 2px 1px; border: none;
            border-radius: 2px; box-shadow: none; background-image: none;
            background-color: %(line_strong)s;
        }
        scrollbar.horizontal slider { min-width: 24px; min-height: 4px; margin: 1px 2px; }
        scrollbar slider:hover, scrollbar slider:active { background-color: %(primary)s; }
        scrollbar.overlay-indicator:not(.dragging):not(.hovering) slider {
            min-width: 3px; margin: 2px 1px; background-color: %(line_strong)s;
        }
        scrolledwindow junction, scrolledwindow undershoot, scrolledwindow overshoot {
            background: none; border: none; box-shadow: none;
        }
        tooltip { background-color: %(surface_high)s; border: 1px solid %(line_strong)s;
                  border-radius: 6px; }
        tooltip label { color: %(on_surface)s; font-size: 12px; }

        /* ── боковое меню: пункты и подпункты ── */
        .rail { background-color: %(rail)s; border-right: 1px solid %(line)s; padding: 10px 6px; }
        .search {
            background-color: %(surface)s; border: 1px solid %(line_strong)s;
            border-radius: 6px; padding: 0 6px;
        }
        .search.focus { border-color: %(primary)s; }
        .search-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px; color: %(primary)s; }
        entry.search-entry {
            background: transparent; background-image: none; border: none; box-shadow: none;
            outline: none; padding: 4px 0; min-height: 0; color: %(on_surface)s;
            caret-color: %(primary)s; font-size: 16px;
        }
        entry.search-entry selection { background-color: %(primary)s; color: %(on_primary)s; }
        label.search-clear { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                             color: %(on_surface_variant)s; }
        list.nav { background-color: transparent; }
        list.nav row {
            background-color: transparent; padding: 0; margin: 1px 0; border-radius: 5px;
            color: %(on_surface)s; outline: none;
        }
        list.nav row:hover { background-color: %(hover)s; }
        list.nav row:selected, list.nav row:selected:hover { background-color: %(primary)s; }
        list.nav row:selected label { color: %(on_primary)s; }
        label.nav-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px; color: %(primary)s; }
        label.nav-label { font-size: 16px; }
        label.nav-arrow { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                          color: %(on_surface_variant)s; }
        /* Подпункт: мельче, с отступом и тонкой линией-«веткой» слева. */
        .nav-branch { border-left: 1px solid %(line_strong)s; }
        label.nav-sub { font-size: 12px; color: %(on_surface_variant)s; }
        list.nav row:hover label.nav-sub { color: %(on_surface)s; }
        /* Пункт, чей подпункт открыт, — подпись акцентом. */
        list.nav row.open label.nav-label { color: %(primary)s; }
        list.nav row.open:selected label.nav-label { color: %(on_primary)s; }

        /* ── страница ── */
        label.page-crumb { font-size: 12px; color: %(primary)s; }
        label.page-title { font-size: 24px; color: %(on_surface)s; }
        label.page-sub { font-size: 12px; color: %(on_surface_variant)s; }
        label.empty { font-size: 16px; color: %(on_surface)s; }
        label.empty-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 24px;
                           color: %(primary)s; }
        .card {
            background-color: %(card_bg)s; border: 1px solid %(line)s;
            border-radius: 6px; padding: 8px 10px 6px 10px;
        }
        label.sec-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px; color: %(primary)s; }
        label.sec-title { font-size: 16px; color: %(primary)s; }
        label.row-title { font-size: 16px; color: %(on_surface)s; }
        label.row-title:disabled { color: %(on_surface_variant)s; }
        label.row-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                         color: %(icon_dim)s; }
        label.value { font-size: 12px; color: %(primary)s; }

        /* Выключатель — плоский, с почти прямыми углами: в пару пиксельному шрифту.
           Кнопки «Вкл/Выкл» пробовались 12.09.2026 и не прижились. */
        switch {
            min-width: 30px; min-height: 14px;
            border: 1px solid %(line_strong)s; box-shadow: none; border-radius: 3px;
            background-color: %(surface_high)s; background-image: none;
        }
        switch:hover { border-color: %(primary)s; }
        switch:checked { background-color: %(primary)s; border-color: %(primary)s; }
        switch slider {
            min-width: 12px; min-height: 12px; margin: 1px;
            border: none; box-shadow: none; border-radius: 2px;
            background-color: %(on_surface_variant)s; background-image: none;
        }
        switch:checked slider { background-color: %(on_primary)s; }
        switch:disabled { opacity: 0.45; }

        scale { margin: 0; padding: 4px 0; }
        scale trough {
            min-height: 4px; border: none; border-radius: 2px;
            background-color: %(line_strong)s; background-image: none;
        }
        scale highlight { background-color: %(primary)s; background-image: none;
                          border-radius: 2px; border: none; }
        scale slider {
            min-width: 12px; min-height: 12px; margin: -5px;
            border: 2px solid %(surface)s; box-shadow: none; border-radius: 3px;
            background-color: %(primary)s; background-image: none;
        }
        scale:disabled { opacity: 0.45; }

        /* Сегменты — выбор из нескольких, активный залит акцентом. */
        button.seg {
            background-color: %(surface_high)s; background-image: none; box-shadow: none;
            border: 1px solid %(line)s; border-radius: 4px; padding: 2px 7px;
            min-height: 0; min-width: 0; color: %(on_surface_variant)s;
        }
        button.seg label { font-size: 12px; }
        button.seg label.seg-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px; }
        button.seg:hover { border-color: %(primary)s; color: %(on_surface)s; }
        button.seg.on, button.seg.on:hover {
            background-color: %(primary)s; border-color: %(primary)s; color: %(on_primary)s;
        }

        /* Плитки-схемы (форма бара, нижняя панель, курсор…). Рамка в 2 px у
           всех, у невыбранных — прозрачная: при выборе плитка не прыгает. */
        button.tile {
            background-color: %(surface)s; background-image: none; box-shadow: none;
            border: 2px solid %(line)s; border-radius: 6px; padding: 2px;
            min-height: 0; min-width: 0;
        }
        button.tile:hover { border-color: %(line_strong)s; }
        button.tile.tile-active { border-color: %(primary)s; background-color: %(sel)s; }
        label.tile-name { font-size: 12px; color: %(on_surface_variant)s; }
        button.tile.tile-active label.tile-name { color: %(primary)s; }
        button.tile:disabled { opacity: 0.5; }

        /* Своя рамка окна: 2 px, углы — как скругление окон (window_rounding). */
        .win-frame { border: 2px solid %(frame_off)s; border-radius: %(win_r)spx; }
        .win-frame.active { border-color: %(primary)s; }
        .xp-title { border-radius: %(win_r_in)spx %(win_r_in)spx 0 0; }

        /* Полоса заголовка в духе Windows XP — градиент из тех же тонов, что
           «Пуск» XP-панели (xpbar_colors: st_*), текст светлый с тенью. */
        .xp-title {
            background-image: linear-gradient(to bottom, %(st_hi)s 0%%, %(st_top)s 12%%,
                %(st_mid)s 50%%, %(st_bot)s 88%%, %(line2)s 100%%);
            border-bottom: 1px solid %(st_dark)s;
        }
        label.xp-title-text { font-size: 16px; color: %(on_surface)s;
                              text-shadow: 1px 1px %(st_dark)s; }
        label.xp-title-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                              color: %(on_surface)s; text-shadow: 1px 1px %(st_dark)s; }
        button.xp-cap {
            min-width: 16px; min-height: 16px; padding: 0 1px; margin: 0;
            border: 1px solid %(cap_border)s; border-radius: 3px;
            background-image: linear-gradient(to bottom, %(st_hover)s, %(st_mid)s 60%%, %(st_bot)s);
            box-shadow: inset 0 1px 0 0 %(cap_hi)s;
        }
        button.xp-cap:hover {
            background-image: linear-gradient(to bottom, %(st_hi)s, %(st_top)s 60%%, %(st_mid)s);
        }
        button.xp-cap:active {
            background-image: linear-gradient(to bottom, %(st_press_top)s, %(st_press_bot)s);
        }
        button.xp-cap label { font-family: 'JetBrainsMono Nerd Font'; font-size: 12px;
                              color: %(on_surface)s; }
        button.xp-close {
            background-image: linear-gradient(to bottom, %(close_hi)s, %(close_mid)s 60%%,
                                              %(close_bot)s);
        }
        button.xp-close:hover {
            background-image: linear-gradient(to bottom, %(close_hi)s, %(close_hi)s 40%%,
                                              %(close_mid)s);
        }

        /* Кнопка с меню (шрифт, место окна) и обычная кнопка действия. */
        button.fontpick {
            background-color: %(surface)s; background-image: none; box-shadow: none;
            border: 1px solid %(line_strong)s; border-radius: 4px; padding: 2px 8px;
            min-height: 0; color: %(on_surface)s;
        }
        button.fontpick:hover { border-color: %(primary)s; }
        button.fontpick label { font-size: 12px; }
        /* Низ страницы: «Сбросить эту страницу» и «изменено здесь: N». */
        button.reset-btn label.reset-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px; }
        button.reset-btn:disabled { opacity: 0.45; }
        label.reset-note { font-size: 12px; color: %(on_surface_variant)s; }
        label.reset-ask { font-size: 12px; color: %(on_surface)s; }
        label.pick-arrow { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                           color: %(primary)s; }
        menu, .menu {
            background-color: %(surface_container)s; border: 1px solid %(line_strong)s;
            padding: 4px;
        }
        menu menuitem { padding: 4px 10px; border-radius: 4px; color: %(on_surface)s; }
        menu menuitem label { font-size: 16px; }
        menu menuitem:hover { background-color: %(primary)s; color: %(on_primary)s; }
        menu menuitem:hover label { color: %(on_primary)s; }
        """ % dict(p, **self.title_colors(),
                   rail=popup_theme.rgba(p["surface_container"], 0.45),
                   card_bg=popup_theme.rgba(p["surface_container"], 0.55),
                   line=popup_theme.rgba(p["primary"], 0.13),
                   line_strong=popup_theme.rgba(p["primary"], 0.30),
                   icon_dim=popup_theme.rgba(p["primary"], 0.75),
                   sel=popup_theme.rgba(p["primary"], 0.10),
                   frame_off=p["outline_variant"],
                   win_r=win_rounding(), win_r_in=max(0, win_rounding() - 2),
                   hover=popup_theme.rgba(p["primary"], 0.10))).encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def title_colors(self):
        """Тона полосы заголовка: из xpbar_colors (как у «Пуска» XP-панели),
        закрыть — красноватый error палитры."""
        try:
            import xpbar_colors
            x = xpbar_colors.colors()
        except Exception:
            x = {}
        p = self.pal
        out = {k: x.get(k, d) for k, d in (
            ("st_hi", p["primary"]), ("st_top", p["surface_highest"]),
            ("st_mid", p["surface_high"]), ("st_bot", p["surface_container"]),
            ("line2", p["surface_container"]), ("st_dark", p["surface"]),
            ("st_hover", p["surface_highest"]), ("st_press_top", p["surface_container"]),
            ("st_press_bot", p["surface_high"]))}
        out.update(cap_border=popup_theme.rgba(p["on_surface"], 0.55),
                   cap_hi=popup_theme.rgba(p["on_surface"], 0.30),
                   close_hi=_mix(p["error"], p["surface"], 0.15),
                   close_mid=_mix(p["error"], p["surface"], 0.45),
                   close_bot=_mix(p["error"], p["surface"], 0.62))
        return out

    # ── боковое меню ──────────────────────────────────────────────────────
    # Дерево (01.10.2026): пункт со значком, под ним с отступом и линией-веткой
    # — подпункты помельче. Всё в одном ListBox: строка пункта без своей
    # страницы (Waybar, Misc) при выборе передаёт выбор первому подпункту.
    def build_rail(self):
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        rail.get_style_context().add_class("rail")
        rail.set_size_request(RAIL_W, -1)

        # Поле поиска: значок лупы, поле, крестик очистки (когда есть текст).
        sbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        sbox.get_style_context().add_class("search")
        self.search_box = sbox
        glass = Gtk.Label(label="\U000f0349")
        glass.get_style_context().add_class("search-icon")
        self.search_entry = Gtk.Entry()
        self.search_entry.get_style_context().add_class("search-entry")
        self.search_entry.set_placeholder_text("Поиск…")
        self.search_entry.set_width_chars(6)
        self.search_entry.set_has_frame(False)
        clear = Gtk.EventBox()
        clear_l = Gtk.Label(label="\U000f0156")
        clear_l.get_style_context().add_class("search-clear")
        clear.add(clear_l)
        clear.set_no_show_all(True)
        clear_l.show()
        clear.connect("button-press-event", lambda *_a: (self.search_entry.set_text(""), True)[1])
        self._search_clear = clear
        sbox.pack_start(glass, False, False, 0)
        sbox.pack_start(self.search_entry, True, True, 0)
        sbox.pack_start(clear, False, False, 0)
        self.search_entry.connect("changed", self.on_search_changed)
        self.search_entry.connect("focus-in-event",
                                  lambda *_a: sbox.get_style_context().add_class("focus"))
        self.search_entry.connect("focus-out-event",
                                  lambda *_a: sbox.get_style_context().remove_class("focus"))
        rail.pack_start(sbox, False, False, 0)

        self.xp_rail_head = Gtk.Label(label="Категории", xalign=0)
        self.xp_rail_head.get_style_context().add_class("xp-rail-head")
        self.xp_rail_head.set_no_show_all(True)
        # Карточка пользователя вида Beta: коробка пустая и скрытая, пока Beta
        # не включён (наполняет enter_beta — аватарка читается только тогда).
        self.user_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.user_slot.set_no_show_all(True)
        rail.pack_start(self.user_slot, False, False, 0)

        nav = Gtk.ListBox()
        self.nav = nav
        nav.get_style_context().add_class("nav")
        nav.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self.nav_rows = {}        # ключ страницы → строка (пункты со страницей и подпункты)
        self.nav_items = []       # (строка пункта, ключ, своя страница?, [ключи подпунктов])
        self.nav_parent_row = {}  # ключ пункта → его строка
        # Раскрытые пункты (01.10.2026): по умолчанию все свёрнуты, помнится
        # между запусками; пункт открытой при запуске страницы раскрыт всегда.
        try:
            with open(NAV_STATE, encoding="utf-8") as f:
                self.expanded = set(json.load(f))
        except (OSError, ValueError, TypeError):
            self.expanded = set()
        if self.start_page in PAGE_PARENT:
            self.expanded.add(PAGE_PARENT[self.start_page])
        for ti, (key, icon, title, own, kids) in enumerate(TREE):
            row = Gtk.ListBoxRow()
            row.page_key = key if own else None
            row.kids = [k for k, _t in kids]
            line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            line.set_margin_top(4)
            line.set_margin_bottom(4)
            line.set_margin_start(6)
            line.set_margin_end(6)
            ico = Gtk.Label(label=icon)
            ico.get_style_context().add_class("nav-icon")
            # bt<N> — цвет плитки-значка в виде Beta; в остальных видах правил
            # на этот класс нет.
            ico.get_style_context().add_class("bt%d" % ti)
            ico.set_size_request(18, -1)
            ico.set_valign(Gtk.Align.CENTER)
            lbl = Gtk.Label(label=title, xalign=0)
            lbl.get_style_context().add_class("nav-label")
            lbl.set_ellipsize(Pango.EllipsizeMode.END)
            line.pack_start(ico, False, False, 0)
            line.pack_start(lbl, True, True, 0)
            row.arrow = None
            if kids:
                # стрелка: свёрнут — вправо, раскрыт — вниз
                row.arrow = Gtk.Label()
                row.arrow.get_style_context().add_class("nav-arrow")
                line.pack_end(row.arrow, False, False, 0)
            row.add(line)
            if ti:
                row.set_margin_top(4)
            nav.add(row)
            if own:
                self.nav_rows[key] = row
            self.nav_items.append((row, key, own, row.kids))
            self.nav_parent_row[key] = row
            for ck, ct in kids:
                crow = Gtk.ListBoxRow()
                crow.page_key = ck
                crow.kids = []
                # ветка: отступ под значок пункта, линия слева, подпись 12 px
                branch = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
                branch.get_style_context().add_class("nav-branch")
                branch.set_margin_start(12)
                cl = Gtk.Label(label=ct, xalign=0)
                cl.get_style_context().add_class("nav-sub")
                cl.set_ellipsize(Pango.EllipsizeMode.END)
                cl.set_margin_start(8)
                cl.set_margin_top(4)
                cl.set_margin_bottom(4)
                branch.pack_start(cl, True, True, 0)
                crow.add(branch)
                crow.set_no_show_all(True)       # показывает только раскрытие пункта
                branch.show_all()
                crow.set_visible(key in self.expanded)
                nav.add(crow)
                self.nav_rows[ck] = crow
        nav.connect("row-selected", self.on_nav)
        nav.connect("row-activated", self.on_nav_click)
        self.show_nav_tree()
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(nav)
        scroll.get_style_context().add_class("xp-rail-body")
        navbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        navbox.pack_start(self.xp_rail_head, False, False, 0)
        navbox.pack_start(scroll, True, True, 0)
        rail.pack_start(navbox, True, True, 0)
        # Переключатель вида Настроек переехал в пункт Config (01.10.2026, раунд 3).
        first = self.start_page
        self._selected = first
        GLib.idle_add(lambda: (nav.select_row(self.nav_rows[first]), False)[1])
        return rail

    def on_nav(self, _list, row):
        """Выбор строки меню — показать её страницу. У пункта без своей страницы
        (Misc) выбор ничего не меняет: открыть подпункт — дело щелчка."""
        if row is None or row.page_key is None:
            return
        key = row.page_key
        # Пункт со своей страницей при поиске может оказаться без совпадений,
        # а совпадения — в подпункте: тогда открыть подпункт.
        if row.kids and self.query and key not in self._visible_pages:
            kid = next((k for k in row.kids if self.nav_rows[k].get_visible()), None)
            if kid is not None:
                self.nav.select_row(self.nav_rows[kid])
            return
        if key != self._selected:
            self.reset_bars_idle()
        self._selected = key
        self.hist_push(key)
        self.ensure_page(key)
        self.stack.set_visible_child_name(key)
        parent = PAGE_PARENT.get(key)
        for prow, pkey, _own, _kids in self.nav_items:
            ctx = prow.get_style_context()
            (ctx.add_class if pkey == parent else ctx.remove_class)("open")
        self.sync_beta()

    # История открытых разделов: «‹ ›» в шапке Beta, Alt+←/→ в любом виде.
    def hist_push(self, key):
        if self._hist_lock or self._hist[self._hist_i] == key:
            return
        del self._hist[self._hist_i + 1:]
        self._hist.append(key)
        del self._hist[:-50]
        self._hist_i = len(self._hist) - 1

    def hist_go(self, step):
        i = self._hist_i + step
        if not 0 <= i < len(self._hist):
            return
        if self.search_entry.get_text():           # поиск прячет разделы — снять его
            self.search_entry.set_text("")
            if self._search_timer:
                GLib.source_remove(self._search_timer)
                self._search_timer = None
            self.query = ""
            self.apply_filter()
        self._hist_i = i
        self._hist_lock = True
        try:
            self.select_page(self._hist[i])
        finally:
            self._hist_lock = False
        self.sync_beta()

    def on_nav_click(self, _list, row):
        """Щелчок (или Enter) по пункту с подпунктами: свёрнут — раскрыть и
        открыть страницу (свою или первый подпункт), раскрыт — свернуть."""
        if not row.kids or self.query:
            return
        key = self.nav_parent_of(row)
        if key in self.expanded:
            self.expanded.discard(key)
            sel = self.nav.get_selected_row()
            if sel is not None and sel.page_key in row.kids:
                # Открытый подпункт прячется. У пункта со своей страницей выбор
                # переходит на неё; у пункта без страницы выбор просто снимается
                # (иначе он оставался залит акцентом, будто выбран — 271.png),
                # а подпись пункта остаётся акцентом: «открытое — внутри».
                if row.page_key is not None:
                    self.nav.select_row(row)
                else:
                    self.nav.unselect_all()
            elif sel is row and row.page_key is None:
                self.nav.unselect_all()
        else:
            self.expanded.add(key)
            if row.page_key is None:
                self.nav.select_row(self.nav_rows[row.kids[0]])
        self.show_nav_tree()
        self.save_nav_state()

    def nav_parent_of(self, row):
        return next(k for k, r in self.nav_parent_row.items() if r is row)

    def show_nav_tree(self):
        """Подпункты видны у раскрытых пунктов (вне поиска)."""
        for prow, pkey, _own, kids in self.nav_items:
            prow.set_visible(True)
            if prow.arrow is not None:
                prow.arrow.set_text("\U000f0140" if pkey in self.expanded else "\U000f0142")
            for k in kids:
                self.nav_rows[k].set_visible(pkey in self.expanded)

    def save_nav_state(self):
        try:
            os.makedirs(os.path.dirname(NAV_STATE), exist_ok=True)
            with open(NAV_STATE, "w", encoding="utf-8") as f:
                json.dump(sorted(self.expanded), f)
        except OSError:
            pass

    def select_page(self, key):
        """Открыть страницу так же, как щелчком слева (и для снимков при правке)."""
        key = PAGE_ALIASES.get(key, key)
        if key in self.nav_rows:
            parent = PAGE_PARENT.get(key)
            if parent and parent not in self.expanded:
                self.expanded.add(parent)
                self.show_nav_tree()
            self.nav.select_row(self.nav_rows[key])

    # ── полоса заголовка в духе Windows XP ────────────────────────────────
    # Свернуть нет намеренно: в niri свернуть окно некуда (нет панели задач
    # с окнами-иконками). Развернуть — не полный экран: окно занимает место
    # между баром и нижней панелью (xdg set_maximized; niri — maximize-to-edges).
    def build_titlebar(self):
        bar = Gtk.EventBox()
        bar.get_style_context().add_class("xp-title")
        bar.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                       | Gdk.EventMask.POINTER_MOTION_MASK)
        bar.set_size_request(-1, TITLE_H)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_start(6)
        box.set_margin_end(3)
        ic = Gtk.Label(label="\U000f0493")
        ic.get_style_context().add_class("xp-title-icon")
        t = Gtk.Label(label="Настройки", xalign=0)
        t.get_style_context().add_class("xp-title-text")
        self.title_label = t
        box.pack_start(ic, False, False, 0)
        box.pack_start(t, False, False, 0)
        close = self.cap_button("\U000f0156", "Закрыть", self.close)
        close.get_style_context().add_class("xp-close")
        self.max_btn = self.cap_button("\U000f05af", "Развернуть", self.toggle_max)
        box.pack_end(close, False, False, 0)
        box.pack_end(self.max_btn, False, False, 0)
        bar.add(box)
        self._press = None
        self._maximized = False
        bar.connect("button-press-event", self.on_title_press)
        bar.connect("motion-notify-event", self.on_title_motion)
        bar.connect("button-release-event", lambda *_a: setattr(self, "_press", None))
        self.connect("window-state-event", self.on_window_state)
        return bar

    def on_active_changed(self, *_a):
        ctx = self.outer.get_style_context()
        (ctx.add_class if self.is_active() else ctx.remove_class)("active")

    def cap_button(self, glyph, tip, cb):
        b = Gtk.Button()
        b.set_relief(Gtk.ReliefStyle.NONE)
        b.set_can_focus(False)
        b.get_style_context().add_class("xp-cap")
        l = Gtk.Label(label=glyph)
        b.add(l)
        b.set_tooltip_text(tip)
        b.set_valign(Gtk.Align.CENTER)
        b.connect("clicked", lambda _b: cb())
        return b

    def on_title_press(self, _w, ev):
        if ev.button != 1:
            return False
        double = getattr(Gdk.EventType, "DOUBLE_BUTTON_PRESS",
                         getattr(Gdk.EventType, "_2BUTTON_PRESS", None))
        if ev.type == double:
            self._press = None
            self.toggle_max()
            return True
        if ev.type == Gdk.EventType.BUTTON_PRESS:
            # Тащить начинаем только после сдвига на несколько пикселей: иначе
            # композитор забирал бы указатель сразу и двойной щелчок не ловился.
            self._press = (ev.x_root, ev.y_root)
        return True

    def on_title_motion(self, _w, ev):
        if self._press is None or not ev.state & Gdk.ModifierType.BUTTON1_MASK:
            return False
        x0, y0 = self._press
        if abs(ev.x_root - x0) + abs(ev.y_root - y0) > 4:
            self._press = None
            self.begin_move_drag(1, int(x0), int(y0), ev.time)
        return True

    def on_window_state(self, _w, ev):
        self._maximized = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED)
        self.max_btn.get_child().set_text("\U000f05b2" if self._maximized else "\U000f05af")
        self.max_btn.set_tooltip_text("Восстановить" if self._maximized else "Развернуть")
        return False

    def toggle_max(self):
        want = not self._maximized
        (self.maximize if want else self.unmaximize)()
        # Не сработало (плавающее окно niri может не принять xdg set_maximized) —
        # то же действием niri для своего окна по id.
        GLib.timeout_add(400, self._max_fallback, want)

    def _max_fallback(self, want):
        if self._maximized == want or not NIRI:
            return False
        try:
            out = subprocess.run(["niri", "msg", "--json", "windows"], capture_output=True,
                                 text=True, timeout=2).stdout
            wid = next((w["id"] for w in json.loads(out)
                        if w.get("pid") == os.getpid()
                        and str(w.get("app_id", "")).startswith(APP_ID)), None)
            if wid is not None:
                subprocess.run(["niri", "msg", "action", "maximize-window-to-edges",
                                "--id", str(wid)], capture_output=True, timeout=2)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
        return False

    # ── вид «XP» = Default · Light (с раунда 6) ───────────────────────────
    # Третий вид (01.10.2026): панель управления Windows XP (Luna) в тонах обоев.
    # Слева — панель задач с плашкой «Категории», справа — сиренево-синий фон и
    # светлые группы с закруглёнными плашками-заголовками; кнопки, флажки и
    # ползунки в духе XP. Тона — xpbar_colors (те же, что у XP-панели внизу).
    def xp_css(self):
        t = self.title_colors()
        p = self.pal
        try:
            import xpbar_colors
            base = xpbar_colors.colors().get("base", p["surface"])
        except Exception:
            base = p["surface"]
        light = _mix(t["st_hi"], p["on_surface"], 0.55)       # светлые панели
        lighter = _mix(t["st_hi"], p["on_surface"], 0.80)
        ink = _mix(base, "#000000", 0.15)                     # тёмный текст на светлом
        ink2 = _mix(t["st_bot"], base, 0.35)
        check = os.path.expanduser("~/.cache/jarvis/xp-check-%s.svg" % ink.lstrip("#"))
        if not os.path.exists(check):
            try:
                os.makedirs(os.path.dirname(check), exist_ok=True)
                with open(check, "w") as f:
                    f.write('<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13">'
                            '<path d="M3 6.5 L5.5 9.5 L10 3.5" stroke="%s" stroke-width="2" '
                            'fill="none"/></svg>' % ink)
            except OSError:
                pass
        c = dict(t, light=light, lighter=lighter, ink=ink, ink2=ink2, check=check,
                 text=p["on_surface"], hot=p["tertiary"], primary=p["primary"],
                 sel=_mix(t["st_mid"], base, 0.25))
        return ("""
        .xpskin { background-image: linear-gradient(to bottom, %(st_mid)s, %(st_bot)s); }
        .xpskin label.page-title { color: %(text)s; text-shadow: 1px 1px %(st_dark)s; }
        .xpskin label.page-crumb, .xpskin label.page-sub, .xpskin label.empty { color: %(text)s; }

        /* левая панель задач: градиент, плашка «Категории», светлый список */
        .xpskin .rail {
            background-color: transparent;
            background-image: linear-gradient(to bottom, %(st_top)s, %(st_bot)s);
            border-right: 1px solid %(st_dark)s;
        }
        .xpskin label.xp-rail-head {
            background-image: linear-gradient(to right, %(lighter)s, %(st_hi)s);
            color: %(ink)s; font-size: 16px; padding: 3px 8px;
            border-radius: 4px 4px 0 0; margin-top: 2px;
        }
        .xpskin .xp-rail-body {
            background-color: %(light)s; border: 1px solid %(lighter)s; border-top: none;
        }
        .xpskin list.nav row { border-radius: 0; margin: 0; }
        .xpskin list.nav row label.nav-label, .xpskin list.nav row label.nav-sub { color: %(ink)s; }
        .xpskin list.nav row label.nav-icon, .xpskin list.nav row label.nav-arrow { color: %(ink2)s; }
        .xpskin list.nav row:hover { background-color: %(lighter)s; }
        .xpskin list.nav row:selected, .xpskin list.nav row:selected:hover {
            background-image: linear-gradient(to bottom, %(st_mid)s, %(sel)s);
        }
        .xpskin list.nav row:selected label { color: %(text)s; }
        .xpskin .search {
            background-color: %(lighter)s; border: 1px solid %(ink2)s; border-radius: 0;
        }
        .xpskin entry.search-entry { color: %(ink)s; caret-color: %(ink)s; }
        .xpskin label.search-icon, .xpskin label.search-clear { color: %(ink2)s; }

        /* группы: закруглённая плашка-заголовок и светлое тело */
        .xpskin .xp-group-head {
            background-image: linear-gradient(to right, %(lighter)s, %(st_hi)s);
            border-radius: 4px 4px 0 0; padding: 3px 10px;
        }
        .xpskin .xp-group-head label { color: %(ink)s; font-size: 16px; }
        .xpskin .xp-group-body {
            background-color: %(light)s; border: 1px solid %(lighter)s; border-top: none;
            border-radius: 0 0 3px 3px; padding: 6px 10px;
        }
        .xpskin .xp-group-body.solo { border-top: 1px solid %(lighter)s; border-radius: 3px; }
        .xpskin .xp-group-body label.row-title { color: %(ink)s; }
        .xpskin .xp-group-body label.row-icon { color: %(ink2)s; }
        .xpskin .xp-group-body label.value { color: %(ink)s; }
        .xpskin .xp-group-body label.tile-name { color: %(ink)s; }

        /* флажок XP: квадрат с градиентом и галочкой */
        .xpskin checkbutton { padding: 0; margin: 0; min-height: 0; }
        .xpskin checkbutton check {
            min-width: 13px; min-height: 13px; margin: 0; padding: 0;
            border: 1px solid %(ink2)s; border-radius: 0; box-shadow: none;
            background-image: linear-gradient(135deg, %(light)s, %(text)s);
            -gtk-icon-source: none;
        }
        .xpskin checkbutton:hover check { box-shadow: inset 0 0 0 2px %(hot)s; }
        .xpskin checkbutton check:checked { -gtk-icon-source: url("file://%(check)s"); }

        /* ползунок XP: утопленная дорожка и ручка-брусок */
        .xpskin scale trough {
            min-height: 4px; border: 1px solid %(ink2)s; border-radius: 1px;
            background-color: %(lighter)s; background-image: none;
        }
        .xpskin scale highlight { background-color: %(st_mid)s; background-image: none; border-radius: 0; }
        .xpskin scale slider {
            min-width: 9px; min-height: 17px; margin: -7px 0; border: 1px solid %(ink2)s;
            border-radius: 2px; box-shadow: inset 0 -2px 0 0 %(st_mid)s;
            background-image: linear-gradient(to bottom, %(text)s, %(st_hi)s);
        }

        /* кнопки XP: светлый градиент, скруглённая рамка; выбранная — утоплена */
        .xpskin button.seg, .xpskin button.fontpick {
            background-image: linear-gradient(to bottom, %(text)s, %(light)s);
            border: 1px solid %(ink2)s; border-radius: 3px; padding: 2px 8px;
            box-shadow: none; color: %(ink)s;
        }
        .xpskin button.seg label, .xpskin button.fontpick label { color: %(ink)s; }
        .xpskin button.seg:hover, .xpskin button.fontpick:hover {
            box-shadow: inset 0 0 0 2px %(hot)s; border-color: %(ink2)s;
        }
        .xpskin button.seg.on, .xpskin button.seg.on:hover {
            background-image: linear-gradient(to bottom, %(sel)s, %(st_mid)s);
            border-color: %(st_dark)s; box-shadow: inset 0 1px 2px 0 %(st_dark)s;
        }
        .xpskin button.seg.on label { color: %(text)s; }
        .xpskin label.pick-arrow { color: %(ink2)s; }
        .xpskin button.tile {
            background-color: %(lighter)s; border: 2px solid %(st_hi)s; border-radius: 3px;
        }
        .xpskin button.tile:hover { border-color: %(hot)s; }
        .xpskin button.tile.tile-active { border-color: %(ink2)s; background-color: %(st_hi)s; }
        .xpskin button.tile.tile-active label.tile-name { color: %(ink)s; }
        .xpskin scrollbar slider { background-color: %(ink2)s; }
        """ % c).encode()

    def enter_xp(self):
        if self._xp_provider is None:
            self._xp_provider = Gtk.CssProvider()
            self._xp_provider.load_from_data(self.xp_css())
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), self._xp_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.outer.get_style_context().add_class("xpskin")
        self.xp_rail_head.set_no_show_all(False)
        self.xp_rail_head.show()

    def leave_xp(self):
        self.outer.get_style_context().remove_class("xpskin")
        self.xp_rail_head.set_no_show_all(True)
        self.xp_rail_head.hide()

    def xp_group(self, v):
        """Группа вида XP: плашка-заголовок и светлое тело."""
        g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        g.page_key = self._building
        g.sec_text = ""
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.get_style_context().add_class("xp-group-body")
        if self._pending_section:
            text, _icon, hint = self._pending_section
            self._pending_section = None
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
            head.get_style_context().add_class("xp-group-head")
            head.pack_start(Gtk.Label(label=text, xalign=0), False, False, 0)
            if hint:
                head.set_tooltip_text(hint)
            g.pack_start(head, False, False, 0)
            g.sec_text = "%s %s" % (text, hint or "")
        else:
            body.get_style_context().add_class("solo")
        g.pack_start(body, False, False, 0)
        v.pack_start(g, False, False, 0)
        self._cards.append(g)
        return body

    # ── вид «Beta» ────────────────────────────────────────────────────────
    # Раунд 6 (02.10.2026) — по образцу Настроек AngelOS (только облик, кода
    # оттуда нет): всё прямоугольное, слева поиск, карточка пользователя и пункты
    # с цветными плитками-значками (группами по 2–3), справа шапка «‹ › путь»,
    # заголовок страницы 32 px, секции — маленький заголовок над карточкой с
    # тонкой рамкой, выключатели-рычажки, сегменты, на Config — блок «Частое».
    # Виджеты — те же, что у Default·Dark (левая колонка, полоса заголовка,
    # карточки), меняются стили под классом .beta и пара добавок (beta_top,
    # карточка пользователя). Режим Light/Dark — только набор цветов beta_colors.
    def beta_colors(self):
        p = self.pal
        t = self.title_colors()
        if self.mode == "light":
            # Светлая подложка — те же тона, что у Default·Light (xp_css): светлый
            # акцент «Пуска», смешанный с цветом текста палитры; чернила — тёмная
            # основа XP-панели.
            try:
                import xpbar_colors
                base = xpbar_colors.colors().get("base", p["surface"])
            except Exception:
                base = p["surface"]
            ink = _mix(base, "#000000", 0.15)
            ink2 = _mix(t["st_bot"], base, 0.35)
            bg = _mix(_mix(t["st_hi"], p["on_surface"], 0.85), "#ffffff", 0.20)
            rail = _mix(t["st_hi"], p["on_surface"], 0.62)
            acc = _mix(t["st_mid"], t["st_bot"], 0.40)
            c = dict(bg=bg, rail=rail, bar=_mix(t["st_hi"], p["on_surface"], 0.45),
                     card=_mix(bg, "#ffffff", 0.45),
                     field=_mix(bg, ink2, 0.10), text=ink, dim=_mix(ink2, bg, 0.22),
                     acc=acc, on_acc=_mix(p["on_surface"], "#ffffff", 0.6), acc_text=acc,
                     sel=_mix(rail, acc, 0.38), sel_text=ink, hover=_mix(rail, acc, 0.16),
                     line=_mix(bg, ink2, 0.28), line_soft=_mix(bg, ink2, 0.14),
                     line_strong=_mix(bg, ink2, 0.55),
                     err=_mix(p["error"], "#7a0000", 0.55))
        else:
            bg = p["surface"]
            c = dict(bg=bg, rail=_mix(bg, p["surface_container"], 0.55),
                     bar=_mix(bg, p["surface_container"], 0.85),
                     card=p["surface_container"], field=p["surface_high"],
                     text=p["on_surface"], dim=_mix(p["on_surface_variant"], bg, 0.30),
                     acc=p["primary"], on_acc=p["on_primary"], acc_text=p["primary"],
                     sel=_mix(bg, p["primary"], 0.30), sel_text=p["on_surface"],
                     hover=_mix(bg, p["primary"], 0.12),
                     line=_mix(p["surface_container"], p["on_surface"], 0.16),
                     line_soft=_mix(p["surface_container"], p["on_surface"], 0.08),
                     line_strong=_mix(bg, p["on_surface"], 0.32),
                     err=p["error"])
        c["tile_ink"] = "#f4f4fa"
        return c

    def beta_css(self):
        """Стили Beta — все под классом .beta корневой коробки; цвета — по режиму."""
        c = self.beta_colors()
        tiles = "".join(
            "        .beta label.nav-icon.bt%d { background-color: %s; }\n" % (i, col)
            for i, col in enumerate(beta_tiles(self.pal, len(TREE))))
        return ("""
        .beta { background-color: %(bg)s; color: %(text)s; }

        /* полоса заголовка — плоская: значок, «Настройки · раздел», кнопки */
        .beta .xp-title {
            background-image: none; background-color: %(bar)s;
            border-bottom: 1px solid %(line)s;
        }
        .beta label.xp-title-text { color: %(text)s; text-shadow: none; }
        .beta label.xp-title-icon { color: %(acc_text)s; text-shadow: none; }
        .beta button.xp-cap {
            border: 1px solid %(line_strong)s; border-radius: 0; box-shadow: none;
            background-image: none; background-color: %(field)s;
        }
        .beta button.xp-cap label { color: %(text)s; }
        .beta button.xp-cap:hover { background-image: none; border-color: %(acc)s; }
        .beta button.xp-cap:active { background-image: none; background-color: %(sel)s; }
        .beta button.xp-close:hover { background-color: %(err)s; border-color: %(err)s; }
        .beta button.xp-close:hover label { color: %(bg)s; }

        /* левая колонка: поиск, карточка пользователя, пункты с плитками */
        .beta .rail {
            background-color: %(rail)s; background-image: none;
            border-right: 1px solid %(line)s; padding: 10px 0 6px 0;
        }
        .beta .search {
            background-color: %(field)s; border: 1px solid %(line_strong)s;
            border-radius: 0; margin: 0 8px;
        }
        .beta .search.focus { border-color: %(acc)s; }
        .beta entry.search-entry { color: %(text)s; caret-color: %(acc_text)s; }
        .beta entry.search-entry selection { background-color: %(acc)s; color: %(on_acc)s; }
        .beta label.search-icon, .beta label.search-clear { color: %(dim)s; }
        .beta button.user-card {
            background-image: none; background-color: transparent; box-shadow: none;
            border: 1px solid transparent; border-radius: 0; padding: 4px 5px; margin: 0 8px;
            min-height: 0;
        }
        .beta button.user-card:hover { background-color: %(hover)s; border-color: %(line)s; }
        .beta .avatar-frame {
            border: 1px solid %(line_strong)s; background-color: %(field)s; padding: 1px;
        }
        .beta label.avatar-glyph { font-family: 'JetBrainsMono Nerd Font'; font-size: 24px;
                                   color: %(dim)s; }
        /* «жирно» у пиксельного шрифта — второй удар на пиксель правее: настоящего
           жирного начертания нет, синтетическое мылит */
        .beta label.user-name { font-size: 16px; color: %(text)s; text-shadow: 1px 0 %(text)s; }
        .beta label.user-sub { font-size: 12px; color: %(dim)s; }
        .beta list.nav row { border-radius: 0; margin: 0; padding: 0 4px; }
        .beta list.nav row:hover { background-color: %(hover)s; }
        .beta list.nav row:selected, .beta list.nav row:selected:hover {
            background-color: %(sel)s; background-image: none;
        }
        .beta list.nav row label.nav-label { color: %(text)s; }
        .beta list.nav row:selected label.nav-label { color: %(sel_text)s; }
        .beta list.nav row label.nav-icon, .beta list.nav row:selected label.nav-icon {
            min-width: 22px; min-height: 22px; color: %(tile_ink)s;
            box-shadow: inset -1px -1px 0 0 rgba(0, 0, 0, 0.28),
                        inset 1px 1px 0 0 rgba(255, 255, 255, 0.22);
        }
%(tiles)s
        /* шапка страницы: «‹ ›» и путь */
        .beta .beta-top { padding: 6px 12px; border-bottom: 1px solid %(line)s; }
        .beta button.nav-btn {
            min-width: 22px; min-height: 22px; padding: 0; margin: 0;
            border: 1px solid %(line_strong)s; border-radius: 0; box-shadow: none;
            background-image: none; background-color: %(field)s;
        }
        .beta button.nav-btn label { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                                     color: %(text)s; }
        .beta button.nav-btn:hover { border-color: %(acc)s; }
        .beta button.nav-btn:disabled { border-color: %(line)s; background-color: transparent; }
        .beta button.nav-btn:disabled label { color: %(line_strong)s; }
        .beta label.crumb-root { font-size: 16px; color: %(dim)s; }
        .beta label.crumb-sep { font-family: 'JetBrainsMono Nerd Font'; font-size: 16px;
                                color: %(dim)s; }
        .beta label.crumb-cur { font-size: 16px; color: %(text)s; text-shadow: 1px 0 %(text)s; }

        /* страница */
        .beta label.page-title { font-size: 32px; color: %(text)s; }
        .beta label.page-crumb { color: %(acc_text)s; }
        .beta label.page-sub { color: %(dim)s; }
        .beta label.empty { color: %(text)s; }
        .beta label.empty-icon { color: %(acc_text)s; }
        .beta label.sec-icon { font-size: 16px; color: %(acc_text)s; }
        .beta label.sec-title { font-size: 12px; color: %(dim)s; }
        .beta .card {
            background-color: %(card)s; border: 1px solid %(line)s; border-radius: 0;
            padding: 0 10px;
        }
        .beta .brow { padding: 6px 0; border-top: 1px solid %(line_soft)s; }
        .beta .brow.first { border-top: none; }
        .beta label.row-title { color: %(text)s; }
        .beta label.row-title:disabled { color: %(dim)s; }
        .beta label.value { color: %(acc_text)s; }

        /* выключатель — прямоугольный рычажок */
        .beta switch {
            min-width: 34px; min-height: 14px; border: 1px solid %(line_strong)s;
            border-radius: 0; background-color: %(field)s; background-image: none;
        }
        .beta switch:hover { border-color: %(acc)s; }
        .beta switch:checked { background-color: %(acc)s; border-color: %(acc)s; }
        .beta switch slider {
            min-width: 14px; min-height: 12px; margin: 1px; border: none; border-radius: 0;
            background-color: %(dim)s; background-image: none;
        }
        .beta switch:checked slider { background-color: %(on_acc)s; }

        .beta scale trough { border-radius: 0; background-color: %(line_strong)s; }
        .beta scale highlight { border-radius: 0; background-color: %(acc)s; }
        .beta scale slider {
            min-width: 6px; min-height: 14px; margin: -6px 0; border-radius: 0;
            border: 1px solid %(card)s; background-color: %(acc)s;
        }

        /* сегменты и кнопки — прямоугольные, выбранная залита акцентом */
        .beta button.seg, .beta button.fontpick {
            background-color: %(field)s; background-image: none; box-shadow: none;
            border: 1px solid %(line_strong)s; border-radius: 0; color: %(text)s;
        }
        .beta button.seg label, .beta button.fontpick label { color: %(text)s; }
        .beta button.seg:hover, .beta button.fontpick:hover { border-color: %(acc)s; }
        .beta button.seg.on, .beta button.seg.on:hover {
            background-color: %(acc)s; border-color: %(acc)s;
        }
        .beta button.seg.on label { color: %(on_acc)s; }
        .beta label.pick-arrow { color: %(acc_text)s; }
        .beta label.reset-note { color: %(dim)s; }
        .beta label.reset-ask { color: %(text)s; }
        .beta button.reset-btn label.reset-icon { color: %(acc_text)s; }
        .beta button.tile {
            background-color: %(field)s; border: 2px solid %(line)s; border-radius: 0;
        }
        .beta button.tile:hover { border-color: %(line_strong)s; }
        .beta button.tile.tile-active { border-color: %(acc)s; background-color: %(sel)s; }
        .beta label.tile-name { color: %(dim)s; }
        .beta button.tile.tile-active label.tile-name { color: %(text)s; }

        /* «Частое»: плитки со значком и подписью */
        .beta button.quick {
            background-color: %(field)s; background-image: none; box-shadow: none;
            border: 1px solid %(line_strong)s; border-radius: 0; padding: 8px 2px;
            min-height: 0; min-width: 0;
        }
        .beta button.quick:hover { border-color: %(acc)s; background-color: %(hover)s; }
        .beta label.quick-icon { font-family: 'JetBrainsMono Nerd Font'; font-size: 24px;
                                 color: %(acc_text)s; }
        .beta label.quick-name { font-size: 12px; color: %(text)s; }

        .beta scrollbar slider { border-radius: 0; background-color: %(line_strong)s; }
        .beta scrollbar slider:hover, .beta scrollbar slider:active { background-color: %(acc)s; }
        """ % dict(c, tiles=tiles)).encode()

    def build_beta_parts(self):
        """Добавки Beta: шапка «‹ › путь» над страницей и карточка пользователя."""
        top = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        top.get_style_context().add_class("beta-top")
        top.set_no_show_all(True)
        self.hist_btns = []
        for glyph, tip, step in (("\U000f0141", "Назад (Alt+←)", -1),
                                 ("\U000f0142", "Вперёд (Alt+→)", 1)):
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.set_can_focus(False)
            b.get_style_context().add_class("nav-btn")
            b.add(Gtk.Label(label=glyph))
            b.set_tooltip_text(tip)
            b.set_valign(Gtk.Align.CENTER)
            b.connect("clicked", lambda _b, st=step: self.hist_go(st))
            top.pack_start(b, False, False, 0)
            self.hist_btns.append(b)
        root = Gtk.Label(label="Настройки")
        root.get_style_context().add_class("crumb-root")
        root.set_margin_start(8)
        sep = Gtk.Label(label="\U000f0142")
        sep.get_style_context().add_class("crumb-sep")
        self.crumb = Gtk.Label(xalign=0)
        self.crumb.get_style_context().add_class("crumb-cur")
        for w in (root, sep, self.crumb):
            top.pack_start(w, False, False, 0)
        self.main.pack_start(top, False, False, 0)
        self.main.reorder_child(top, 0)
        self.beta_top = top

        # Карточка пользователя: аватарка в квадратной рамке, имя и подпись;
        # щелчок открывает Config.
        card = Gtk.Button()
        card.set_relief(Gtk.ReliefStyle.NONE)
        card.set_can_focus(False)
        card.get_style_context().add_class("user-card")
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        frame = Gtk.Box()
        frame.get_style_context().add_class("avatar-frame")
        frame.set_valign(Gtk.Align.CENTER)
        try:
            pix = GdkPixbuf.Pixbuf.new_from_file_at_scale(BETA_AVATAR, 36, 36, False)
            frame.pack_start(Gtk.Image.new_from_pixbuf(pix), False, False, 0)
        except GLib.Error:
            ph = Gtk.Label(label="\U000f0004")
            ph.get_style_context().add_class("avatar-glyph")
            ph.set_size_request(36, 36)
            frame.pack_start(ph, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        text.set_valign(Gtk.Align.CENTER)
        name = Gtk.Label(label=BETA_USER, xalign=0)
        name.get_style_context().add_class("user-name")
        name.set_ellipsize(Pango.EllipsizeMode.END)
        sub = Gtk.Label(label="%s@%s" % (GLib.get_user_name(), GLib.get_host_name()), xalign=0)
        sub.get_style_context().add_class("user-sub")
        sub.set_ellipsize(Pango.EllipsizeMode.END)
        text.pack_start(name, False, False, 0)
        text.pack_start(sub, False, False, 0)
        line.pack_start(frame, False, False, 0)
        line.pack_start(text, True, True, 0)
        card.add(line)
        card.set_tooltip_text("Config — вид Настроек")
        card.connect("clicked", lambda _b: self.select_page("config"))
        self.user_slot.pack_start(card, False, False, 0)
        card.show_all()

    def enter_beta(self):
        if self._beta_provider is None:
            self._beta_provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), self._beta_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self._beta_provider.load_from_data(self.beta_css())     # цвета — по режиму
        self.outer.get_style_context().add_class("beta")
        if self.beta_top is None:
            self.build_beta_parts()
        self.beta_top.set_no_show_all(False)
        self.beta_top.show_all()
        self.user_slot.set_no_show_all(False)
        self.user_slot.show()
        # Пункты — вплотную, группы по 2–3 отделены просветом.
        for row, key, _own, _kids in self.nav_items:
            row.set_margin_top(12 if key in BETA_GROUP_STARTS else 0)
        self.sync_beta()

    def leave_beta(self):
        self.outer.get_style_context().remove_class("beta")
        if self.beta_top is not None:
            self.beta_top.set_no_show_all(True)
            self.beta_top.hide()
        self.user_slot.set_no_show_all(True)
        self.user_slot.hide()
        for i, (row, _key, _own, _kids) in enumerate(self.nav_items):
            row.set_margin_top(4 if i else 0)
        self.title_label.set_text("Настройки")

    def sync_beta(self):
        """Шапка Beta по открытому разделу: путь, заголовок окна, «‹ ›»."""
        if self.look != "beta" or self.beta_top is None:
            return
        title = PAGE_TITLE.get(self._selected, "")
        self.crumb.set_text(title)
        self.title_label.set_text("Настройки · %s" % title)
        self.hist_btns[0].set_sensitive(self._hist_i > 0)
        self.hist_btns[1].set_sensitive(self._hist_i < len(self._hist) - 1)

    def beta_group(self, v):
        """Секция Beta: маленький заголовок со значком, под ним карточка-рамка."""
        g = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        g.page_key = self._building
        g.sec_text = ""
        if self._pending_section:
            text, icon, hint = self._pending_section
            self._pending_section = None
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            head.set_margin_start(2)
            ic = Gtk.Label(label=icon)
            ic.get_style_context().add_class("sec-icon")
            ic.set_size_request(16, -1)                 # значки разной ширины — подписи в ряд
            t = Gtk.Label(label=text, xalign=0)
            t.get_style_context().add_class("sec-title")
            head.pack_start(ic, False, False, 0)
            head.pack_start(t, False, False, 0)
            if hint:
                head.set_tooltip_text(hint)
            g.pack_start(head, False, False, 0)
            g.sec_text = "%s %s" % (text, hint or "")
        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        body.get_style_context().add_class("card")
        g.pack_start(body, False, False, 0)
        v.pack_start(g, False, False, 0)
        self._cards.append(g)
        return body

    # ── вид «Skeet» ───────────────────────────────────────────────────────
    def skeet_css(self):
        """Стили skeet — все под классом .skeet корневой коробки: без него (в
        обычном виде) ни одно правило не срабатывает."""
        c = skeet_colors(self.pal)
        dots = skeet_dots(c)
        strip = ", ".join(c["strip"])
        dark = ", ".join(_mix(x, "#000000", 0.55) for x in c["strip"])
        tail = ", url('file://%s')" % dots if dots else ""
        bg_img = ("linear-gradient(to right, %s), linear-gradient(to right, %s)%s"
                  % (strip, dark, tail))
        # неактивное окно: полоска серая, рамка тусклая
        gray = ", ".join([c["line1"], c["icon"], c["line1"]])
        bg_off = ("linear-gradient(to right, %s), linear-gradient(to right, %s)%s"
                  % (gray, ", ".join([c["line2"]] * 2), tail))
        c.update(bg_off=bg_off, line1_on=_mix(c["line1"], c["acc"], 0.45),
                 line1_off=_mix(c["line1"], c["line2"], 0.6))
        sizes = "100%% 1px, 100%% 1px%s" % (", auto" if dots else "")
        repeats = "no-repeat, no-repeat%s" % (", repeat" if dots else "")
        pos = "0 %dpx, 0 %dpx%s" % (SK_FRAME, SK_FRAME + 1, ", 0 0" if dots else "")
        c.update(bg_img=bg_img, sizes=sizes, repeats=repeats, pos=pos,
                 frame=SK_FRAME, top=SK_FRAME + 2, tab_h=SK_TAB_H,
                 scroll=_mix("#414141", c["acc"], 0.06))
        return ("""
        .skeet {
            background-color: %(bg)s; background-image: %(bg_off)s;
            background-size: %(sizes)s; background-repeat: %(repeats)s;
            background-position: %(pos)s;
            /* рамка окна слоями (снаружи внутрь): 1 светлее, 3 средняя, 1 светлее,
               1 почти чёрная. GTK кладёт тени по порядку, следующую ПОВЕРХ
               предыдущей, — поэтому список идёт от самой широкой к самой узкой. */
            box-shadow: inset 0 0 0 6px %(line3)s, inset 0 0 0 5px %(line1_off)s,
                        inset 0 0 0 4px %(line2)s, inset 0 0 0 1px %(line1_off)s;
            padding: %(top)spx %(frame)spx %(frame)spx %(frame)spx;
            color: %(text)s;
        }
        /* активное окно (notify::is-active → класс active): полоска сверху в
           цветах палитры, светлые линии рамки — с акцентом, заголовок ярче */
        .skeet.active {
            background-image: %(bg_img)s;
            box-shadow: inset 0 0 0 6px %(line3)s, inset 0 0 0 5px %(line1_on)s,
                        inset 0 0 0 4px %(line2)s, inset 0 0 0 1px %(line1_on)s;
        }
        .skeet:not(.active) label.xp-title-text { color: %(text_dim)s; }
        .skeet:not(.active) label.xp-title-icon { color: %(icon)s; }
        .skeet.win-frame { border: none; border-radius: 0; }
        .skeet .xp-title { border-radius: 0; }
        .skeet label, .skeet entry, .skeet button label, .skeet menuitem label { font-size: 12px; }

        /* полоса заголовка — тёмная, под градиентной полоской рамки */
        .skeet .xp-title {
            background-image: none; background-color: transparent;
            border-bottom: 1px solid %(line3)s; box-shadow: inset 0 -1px 0 0 %(line2)s;
        }
        .skeet label.xp-title-text { font-size: 12px; color: %(text)s; text-shadow: none; }
        .skeet label.xp-title-icon { font-size: 12px; color: %(icon_on)s; text-shadow: none; }
        .skeet button.xp-cap {
            border: 1px solid %(line3)s; border-radius: 0;
            box-shadow: inset 0 0 0 1px %(gline)s;
            background-image: linear-gradient(to bottom, %(field_l)s, %(field)s);
        }
        .skeet button.xp-cap label { font-size: 12px; color: %(text_dim)s; }
        .skeet button.xp-cap:hover label { color: %(acc_l)s; }
        .skeet button.xp-close:hover { box-shadow: inset 0 0 0 1px %(err)s; }
        .skeet button.xp-close:hover label { color: %(err)s; }

        /* колонка вкладок: крупные серые значки, выбранная — светлее, с линиями */
        .skeet .skeet-rail {
            background-color: %(rail)s; border-right: 1px solid %(line3)s;
            box-shadow: inset -1px 0 0 0 %(line2)s;
        }
        .skeet button.skeet-tab {
            background: none; background-color: transparent; border: none; box-shadow: none;
            border-radius: 0; padding: 0; margin: 0; min-height: %(tab_h)spx;
            border-top: 1px solid transparent; border-bottom: 1px solid transparent;
        }
        .skeet label.skeet-tab-icon {
            font-family: 'JetBrainsMono Nerd Font'; font-size: 32px; color: %(icon)s;
        }
        .skeet button.skeet-tab:hover label.skeet-tab-icon { color: %(icon_hover)s; }
        .skeet button.skeet-tab.on {
            background-color: %(bg)s; border-top-color: %(line1)s; border-bottom-color: %(line1)s;
            box-shadow: inset 0 1px 0 0 %(line3)s, inset 0 -1px 0 0 %(line3)s;
        }
        .skeet button.skeet-tab.on label.skeet-tab-icon { color: %(icon_on)s; }

        /* полоса над страницей: вкладки второго уровня или название, справа поиск */
        .skeet .skeet-top { padding: 6px 10px 0 10px; }
        .skeet label.skeet-title { color: %(text_dim)s; }
        .skeet button.skeet-sub {
            background: none; background-color: transparent; box-shadow: none;
            border: none; border-bottom: 1px solid transparent; border-radius: 0;
            padding: 1px 6px; min-height: 0; color: %(text_dim)s;
        }
        .skeet button.skeet-sub:hover { color: %(text)s; }
        .skeet button.skeet-sub.on { color: %(acc_l)s; border-bottom-color: %(acc)s; }
        .skeet .search {
            background-color: %(field)s; border: 1px solid %(line3)s; border-radius: 0;
            box-shadow: inset 0 0 0 1px %(gline)s; padding: 0 4px;
        }
        .skeet .search.focus { border-color: %(acc_d)s; }
        .skeet entry.search-entry { padding: 2px 0; color: %(text)s; caret-color: %(acc)s; }
        .skeet entry.search-entry selection { background-color: %(acc_d)s; color: %(text)s; }
        .skeet label.search-icon, .skeet label.search-clear { font-size: 12px; color: %(text_dim)s; }

        /* групповые блоки: заголовок в верхней рамке, рамка двойная */
        .skeet frame.skeet-group > border {
            border: 1px solid %(gline)s; border-radius: 0;
            box-shadow: inset 0 0 0 1px %(gdark)s;
        }
        .skeet frame.skeet-group > label {
            color: %(text)s; background-color: %(bg)s; padding: 0 3px;
        }
        .skeet label.row-title { font-size: 12px; color: %(text)s; }
        .skeet label.row-title:disabled { color: %(text_dim)s; }
        .skeet label.value { font-size: 12px; color: %(text_dim)s; }
        .skeet label.empty { font-size: 12px; color: %(text)s; }
        .skeet label.empty-icon { font-size: 24px; color: %(icon)s; }
        .skeet label.page-sub { color: %(text_dim)s; }

        /* галочка — квадратик ~9 px, включённая залита градиентом акцента */
        .skeet checkbutton { padding: 0; margin: 0; min-height: 0; min-width: 0; }
        .skeet checkbutton check {
            min-width: 9px; min-height: 9px; margin: 0; padding: 0;
            border: 1px solid %(line3)s; border-radius: 0; box-shadow: none;
            background-color: %(field_l)s;
            background-image: linear-gradient(to bottom, %(field_l)s, %(field)s);
            -gtk-icon-source: none; color: transparent;
        }
        .skeet checkbutton:hover check { border-color: %(acc_d)s; }
        .skeet checkbutton check:checked {
            background-image: linear-gradient(to bottom, %(acc_l)s, %(acc_d)s);
        }

        /* ползунок — тонкая полоса с градиентом, без ручки */
        .skeet scale { padding: 3px 0; margin: 0; }
        .skeet scale trough {
            min-height: 6px; border: 1px solid %(line3)s; border-radius: 0;
            background-color: %(field)s;
            background-image: linear-gradient(to bottom, %(field)s, %(field_l)s);
        }
        .skeet scale highlight {
            border: none; border-radius: 0; background-color: %(acc)s;
            background-image: linear-gradient(to bottom, %(acc_l)s, %(acc_d)s);
        }
        .skeet scale slider {
            min-width: 2px; min-height: 6px; margin: 0; border: none; border-radius: 0;
            background: none; background-color: transparent; box-shadow: none;
        }

        /* кнопки, сегменты, меню — тёмные прямоугольники с тонкой рамкой */
        .skeet button.seg, .skeet button.fontpick {
            background-color: %(field)s;
            background-image: linear-gradient(to bottom, %(field_l)s, %(field)s);
            border: 1px solid %(line3)s; box-shadow: inset 0 0 0 1px %(gline)s;
            border-radius: 0; padding: 2px 7px; color: %(text_dim)s;
        }
        .skeet button.seg:hover, .skeet button.fontpick:hover { color: %(text)s; border-color: %(line3)s; }
        .skeet button.seg.on, .skeet button.seg.on:hover {
            color: %(acc_l)s; background-color: %(field_l)s;
            background-image: linear-gradient(to bottom, %(field_l)s, %(field)s);
            box-shadow: inset 0 0 0 1px %(gline)s, inset 0 -2px 0 0 %(acc)s;
            border-color: %(line3)s;
        }
        .skeet button.skeet-skin { padding: 2px 3px; }
        .skeet label.pick-arrow { font-size: 12px; color: %(text_dim)s; }
        .skeet button.tile {
            background-color: %(field)s; background-image: none; border-radius: 0;
            border: 1px solid %(line3)s; box-shadow: inset 0 0 0 1px %(gline)s; padding: 3px;
        }
        .skeet button.tile:hover { border-color: %(line3)s; box-shadow: inset 0 0 0 1px %(icon)s; }
        .skeet button.tile.tile-active {
            background-color: %(field_l)s; border-color: %(line3)s;
            box-shadow: inset 0 0 0 1px %(acc)s;
        }
        .skeet label.tile-name { color: %(text_dim)s; }
        .skeet button.tile.tile-active label.tile-name { color: %(acc_l)s; }

        /* полоса прокрутки — дорожка и ползунок в серых skeet */
        .skeet scrollbar slider { min-width: 4px; border-radius: 0; background-color: %(scroll)s; }
        .skeet scrollbar slider:hover, .skeet scrollbar slider:active { background-color: %(acc_d)s; }
        """ % c).encode()

    def build_skeet_rail(self):
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        rail.get_style_context().add_class("skeet-rail")
        rail.set_size_request(SK_RAIL_W, -1)
        tabs = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        tabs.set_margin_top(8)
        self.sk_tabs = {}
        for key, icon, title, own, kids in TREE:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("skeet-tab")
            b.set_can_focus(False)
            ic = Gtk.DrawingArea()
            ic.set_size_request(48, 48)
            ic.set_halign(Gtk.Align.CENTER)
            ic.set_valign(Gtk.Align.CENTER)
            ic.connect("draw", self.draw_sk_icon, b, SK_ICONS.get(key, "misc"))
            b.connect("state-flags-changed", lambda _b, _f, a=ic: a.queue_draw())
            b.add(ic)
            b.set_tooltip_text(title)            # подпись пункта — подсказкой
            target = key if own else kids[0][0]
            b.connect("clicked", lambda _b, k=target: self.select_page(k))
            tabs.pack_start(b, False, False, 0)
            self.sk_tabs[key] = b
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(tabs)
        rail.pack_start(scroll, True, True, 0)
        # полоса над страницей: слева — вкладки второго уровня или название
        self.sk_left = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=2)
        self.skeet_top.pack_start(self.sk_left, True, True, 0)
        self.nav.connect("row-selected", lambda *_a: self.sync_skeet())
        return rail

    def draw_sk_icon(self, area, cr, button, name):
        """Значок вкладки skeet: маска PNG, залитая цветом состояния — серый,
        светлее под указателем, яркий у выбранной."""
        import cairo
        cache = self.__dict__.setdefault("_sk_masks", {})
        if name not in cache:
            try:
                cache[name] = cairo.ImageSurface.create_from_png(
                    os.path.join(SK_ICON_DIR, name + ".png"))
            except Exception:
                cache[name] = None
        mask = cache[name]
        if mask is None:
            return False
        c = self.__dict__.setdefault("_sk_colors", skeet_colors(self.pal))
        if button.get_style_context().has_class("on"):
            col = c["icon_on"]
        elif button.get_state_flags() & Gtk.StateFlags.PRELIGHT:
            col = c["icon_hover"]
        else:
            col = c["icon"]
        _hex(cr, col)
        cr.mask_surface(mask, (area.get_allocated_width() - mask.get_width()) // 2,
                        (area.get_allocated_height() - mask.get_height()) // 2)
        return False

    def enter_skeet(self):
        if self._skeet_provider is None:
            self._skeet_provider = Gtk.CssProvider()
            self._skeet_provider.load_from_data(self.skeet_css())
            Gtk.StyleContext.add_provider_for_screen(
                Gdk.Screen.get_default(), self._skeet_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        self.outer.get_style_context().add_class("skeet")
        if self.skeet_rail is None:
            self.skeet_rail = self.build_skeet_rail()
            self.root.pack_start(self.skeet_rail, False, False, 0)
            self.root.reorder_child(self.skeet_rail, 0)
        self.rail.set_no_show_all(True)
        self.rail.hide()
        self.skeet_rail.set_no_show_all(False)
        self.skeet_rail.show_all()
        # поиск — из обычной колонки в полосу над страницей, справа
        box = self.search_box
        if box.get_parent() is not None:
            box.get_parent().remove(box)
        box.set_size_request(190, -1)
        self.skeet_top.pack_end(box, False, False, 0)
        self.skeet_top.set_no_show_all(False)
        self.skeet_top.show_all()
        self._search_clear.set_visible(bool(self.search_entry.get_text()))
        self.sync_skeet()

    def leave_skeet(self):
        self.outer.get_style_context().remove_class("skeet")
        if self.skeet_rail is not None:
            self.skeet_rail.set_no_show_all(True)
            self.skeet_rail.hide()
        box = self.search_box
        if box.get_parent() is not None:
            box.get_parent().remove(box)
        box.set_size_request(-1, -1)
        self.rail.pack_start(box, False, False, 0)
        self.rail.reorder_child(box, 0)
        self.skeet_top.set_no_show_all(True)
        self.skeet_top.hide()
        self.rail.set_no_show_all(False)
        self.rail.show_all()
        self._search_clear.set_visible(bool(self.search_entry.get_text()))
        self.show_nav_tree()

    def set_view(self, skin=None, mode=None):
        """Переключить вид и/или режим сразу, без перезапуска окна: стили, левая
        колонка и страницы (у видов разные виджеты — галочки, групповые блоки).
        Режим у Skeet только запоминается; у Beta — одни цвета, без перестройки."""
        skin, mode = view_norm(skin or self.skin, mode or self.mode)
        if (skin, mode) == (self.skin, self.mode):
            return
        view_set(skin, mode)
        new = look_of(skin, mode)
        self.skin, self.mode = skin, mode
        if new == self.look:
            if new == "beta":
                self._beta_provider.load_from_data(self.beta_css())
            if self.mode_seg is not None:
                self.mode_seg.select(mode)
            return
        if self._search_timer:
            GLib.source_remove(self._search_timer)
            self._search_timer = None
        self.search_entry.set_text("")
        self.query = ""
        # Сначала снести построенные страницы, потом менять стили: иначе GTK
        # перестилизует сотни старых виджетов, которые тут же выбросим (было
        # 1,8 с на переключение, стало ~0,2 с).
        cur = self.drop_pages()
        prefetch_start(cur)              # чтения открытой страницы — разом, пока меняются стили
        if self.look == "skeet":
            self.leave_skeet()
        elif self.look == "xp":
            self.leave_xp()
        elif self.look == "beta":
            self.leave_beta()
        self.look = new
        if new == "skeet":
            self.enter_skeet()
        elif new == "xp":
            self.enter_xp()
        elif new == "beta":
            self.enter_beta()
        self.rebuild_pages(cur)
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)

    def forget_page(self, key):
        """Забыть всё, что помнится о виджетах страницы (её сносят)."""
        self._rows = [r for r in self._rows if r[0] != key]
        self._cards = [c for c in self._cards if c.page_key != key]
        for d in (self._page_text, self._page_v, self._sk_runs, self._settings, self._reset_bars):
            d.pop(key, None)
        self._visible_pages.discard(key)
        self._stale.discard(key)
        if self._undo is not None and self._undo[0] == key:
            self._undo = None
        if key == "config":
            self.mode_seg = None

    def drop_pages(self):
        """Снести построенные страницы и всё, что о них помнится. Возвращает ключ
        открытой — её строить первой (rebuild_pages)."""
        cur = self._selected
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_visible_child_name("_empty")
        for child in list(self.stack.get_children()):
            name = self.stack.child_get_property(child, "name")
            if name != "_empty":
                self.forget_page(name)
                self.stack.remove(child)
                child.destroy()
        self._rows, self._cards = [], []
        self._undo = None
        self.mode_seg = None
        return cur

    def set_skin(self, skin):
        """Прежнее имя: вид по старому или новому названию (normal, xp, skeet…)."""
        if skin in SKIN_LEGACY:
            self.set_view(*SKIN_LEGACY[skin])
        else:
            self.set_view(skin=skin)

    def rebuild_pages(self, cur):
        self.ensure_page(cur)
        self.stack.set_visible_child_name(cur)
        self.sync_skeet()
        GLib.idle_add(self.build_bg, _round, priority=GLib.PRIORITY_LOW)

    def skeet_group(self, v):
        """Групповой блок skeet: Gtk.Frame с заголовком в верхней рамке."""
        f = Gtk.Frame()
        f.get_style_context().add_class("skeet-group")
        f.set_label_align(0.03, 0.5)
        f.page_key = self._building
        f.sec_text = ""
        if self._pending_section:
            text, _icon, hint = self._pending_section
            self._pending_section = None
            lbl = Gtk.Label(label=text)
            if hint:
                lbl.set_tooltip_text(hint)
            f.set_label_widget(lbl)
            f.sec_text = "%s %s" % (text, hint or "")
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        inner.set_margin_start(10)
        inner.set_margin_end(10)
        inner.set_margin_top(4)
        inner.set_margin_bottom(8)
        f.add(inner)
        v.pack_start(f, False, False, 0)
        self._cards.append(f)
        return inner

    def skeet_columns(self, key):
        """Разложить группы страницы в две колонки, как у skeet. Широкие (сетки
        плиток) идут во всю ширину; подряд идущие узкие — парой колонок, группы
        между колонками делит skeet_split — так, чтобы колонки вышли вровень.
        Одна узкая группа между широкими остаётся во всю ширину, как была."""
        v = self._page_v.get(key)
        if v is None:
            return
        frames = [c for c in v.get_children() if isinstance(c, Gtk.Frame)]
        if len(frames) < 2:
            return
        blocks, run_ = [], []
        for f in frames:
            if f.get_preferred_width()[0] > SK_COL_W:
                if run_:
                    blocks.append(run_)
                    run_ = []
                blocks.append(f)
            else:
                run_.append(f)
        if run_:
            blocks.append(run_)
        # Высоты меряются, пока группы ещё на странице: без родителя у виджета
        # нет стилей skeet, и высота вышла бы чужой.
        sides = {id(b): self.sk_sides(b) for b in blocks if isinstance(b, list) and len(b) > 1}
        for f in frames:
            v.remove(f)
        runs = []
        for b in blocks:
            if isinstance(b, Gtk.Frame):
                v.pack_start(b, False, False, 0)
                continue
            if len(b) == 1:
                v.pack_start(b[0], False, False, 0)
                continue
            pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=SK_COL_GAP)
            pair.set_homogeneous(True)
            cols = [Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12) for _ in range(2)]
            for f, i in zip(b, sides[id(b)]):
                cols[i].pack_start(f, False, False, 0)
            for col in cols:
                pair.pack_start(col, True, True, 0)
            v.pack_start(pair, False, False, 0)
            runs.append((b, pair, cols))
        self._sk_runs[key] = runs
        v.show_all()

    @staticmethod
    def sk_sides(frames):
        """Колонка (0/1) каждой группе ряда. Считаются только видимые группы
        (поиск прячет несовпавшие) — по высоте при ширине колонки."""
        vis = [f for f in frames if f.get_visible()]
        split = skeet_split([f.get_preferred_height_for_width(SK_COL_W)[1] for f in vis])
        side = dict(zip(vis, split))
        return [side.get(f, 0) for f in frames]

    def skeet_balance(self, key):
        """Высоты групп изменились (поиск спрятал строки, пришёл ответ монитора
        или Razer) — переложить группы по колонкам заново. Ничего не изменилось
        — виджеты не трогаются."""
        if self.look != "skeet":
            return
        for frames, pair, cols in self._sk_runs.get(key, ()):
            # ни одной видимой группы — пара не оставляет лишний просвет
            pair.set_visible(any(f.get_visible() for f in frames))
            sides = self.sk_sides(frames)
            if sides == [0 if f.get_parent() is cols[0] else 1 for f in frames]:
                continue
            for f in frames:
                f.get_parent().remove(f)
            for f, i in zip(frames, sides):
                cols[i].pack_start(f, False, False, 0)

    def sync_skeet(self):
        """Вкладки skeet по меню: выбранная, видимость при поиске, вкладки
        второго уровня (Misc → Экран / Снимки)."""
        if self.look != "skeet" or self.skeet_rail is None:
            return
        sel = self._selected
        top = PAGE_PARENT.get(sel, sel)
        for key, btn in self.sk_tabs.items():
            ctx = btn.get_style_context()
            (ctx.add_class if key == top else ctx.remove_class)("on")
            btn.set_visible(self.nav_parent_row[key].get_visible())
            btn.queue_draw()
        for w in self.sk_left.get_children():
            self.sk_left.remove(w)
            w.destroy()
        item = next(t for t in TREE if t[0] == top)
        group = ([(top, item[2])] if item[3] else []) + list(item[4])
        if len(group) > 1:
            for k, t in group:
                if self.query and not self.nav_rows[k].get_visible():
                    continue
                b = Gtk.Button(label=t)
                b.set_relief(Gtk.ReliefStyle.NONE)
                b.get_style_context().add_class("skeet-sub")
                if k == sel:
                    b.get_style_context().add_class("on")
                b.connect("clicked", lambda _b, kk=k: self.select_page(kk))
                self.sk_left.pack_start(b, False, False, 0)
        else:
            l = Gtk.Label(label=item[2], xalign=0)
            l.get_style_context().add_class("skeet-title")
            self.sk_left.pack_start(l, False, False, 0)
        self.sk_left.show_all()

    # ── поиск ─────────────────────────────────────────────────────────────
    # Ищет по подписям и пояснениям строк во всех разделах: на время поиска
    # достраиваются все разделы, в каждом прячутся несовпавшие строки и пустые
    # карточки, слева — разделы без совпадений. Совпал заголовок раздела или
    # карточки — показывается целиком. Esc очищает, Ctrl+F — в поле поиска.
    def on_key(self, _w, ev):
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if ev.keyval == Gdk.KEY_Escape and self.search_entry.get_text():
            self.search_entry.set_text("")
            self.search_entry.grab_focus()
            return True
        if ctrl and ev.keyval in (Gdk.KEY_f, Gdk.KEY_F, Gdk.KEY_Cyrillic_a, Gdk.KEY_Cyrillic_A):
            self.search_entry.grab_focus()
            return True
        # Alt+← / Alt+→ — назад и вперёд по истории разделов (как «‹ ›» в Beta).
        if ev.state & Gdk.ModifierType.MOD1_MASK and ev.keyval in (Gdk.KEY_Left, Gdk.KEY_Right):
            self.hist_go(-1 if ev.keyval == Gdk.KEY_Left else 1)
            return True
        return False

    def on_search_changed(self, entry):
        self._search_clear.set_visible(bool(entry.get_text()))
        if self._search_timer:
            GLib.source_remove(self._search_timer)
        self._search_timer = GLib.timeout_add(90, self.run_search)

    def run_search(self):
        self._search_timer = None
        q = self.search_entry.get_text().strip().casefold()
        if q and not self.query:
            for key in self.builders:            # поиск идёт по всем разделам
                self.ensure_page(key)
        self.query = q
        self.apply_filter()
        return False

    def apply_filter(self):
        # Выбор раздела самим поиском в историю «‹ ›» не пишется.
        lock, self._hist_lock = self._hist_lock, True
        try:
            self._apply_filter()
        finally:
            self._hist_lock = lock
        for key in self._sk_runs:                # skeet: колонки — по тому, что осталось видно
            self.skeet_balance(key)
        self.sync_skeet()
        self.sync_beta()

    def _apply_filter(self):
        words = self.query.split()

        variants = search_variants(self.query)

        def hit(text):
            return search_hit(text, variants)

        page_hit = {k: bool(words) and hit(t) for k, t in self._page_text.items()}
        card_rows = {}
        cards = set(self._cards)
        for page_key, wrap, text in self._rows:
            anc = wrap.get_parent()
            while anc is not None and anc not in cards:
                anc = anc.get_parent()
            card_rows.setdefault(anc, []).append((wrap, text))
        visible_pages = set()
        for c in self._cards:
            whole = not words or page_hit.get(c.page_key) or hit(c.sec_text)
            any_row = False
            for wrap, text in card_rows.get(c, []):
                # absent — устройства нет (монитор MSI, клавиатура Razer)
                show = (whole or hit(text)) and not getattr(wrap, "absent", False)
                wrap.set_visible(show)
                any_row = any_row or show
            show_card = bool(whole or any_row)
            c.set_visible(show_card)
            if show_card:
                visible_pages.add(c.page_key)
        self._visible_pages = visible_pages
        if words:
            # при поиске дерево раскрыто: видно всё, где есть совпадения
            for key, row in self.nav_rows.items():
                built = self.stack.get_child_by_name(key) is not None
                row.set_visible(built and key in visible_pages)
            for prow, pkey, own, kids in self.nav_items:
                prow.set_visible((own and pkey in visible_pages)
                                 or any(self.nav_rows[k].get_visible() for k in kids))
        else:
            parent = PAGE_PARENT.get(self._selected)
            if parent:
                self.expanded.add(parent)        # открытый подпункт не прячем
            self.show_nav_tree()
        if not words:
            self.ensure_page(self._selected)
            self.stack.set_visible_child_name(self._selected)
            if self.nav.get_selected_row() is not self.nav_rows[self._selected]:
                self.nav.select_row(self.nav_rows[self._selected])
            return
        order = [k for k in PAGE_ORDER if k in visible_pages]
        if not order:
            self.nav.unselect_all()
            self.stack.set_visible_child_name("_empty")
            return
        cur = self.nav.get_selected_row()
        key = (cur.page_key if cur is not None and cur.page_key in visible_pages
               else order[0])
        self.nav.select_row(self.nav_rows[key])
        self.stack.set_visible_child_name(key)
        page = self.stack.get_child_by_name(key)
        page.get_vadjustment().set_value(0)

    # ── строительные блоки ────────────────────────────────────────────────
    def page(self, title, sub=None):
        parent = PAGE_PARENT.get(self._building)
        if self.look == "skeet":
            # Skeet: без заголовка страницы — где мы, видно по вкладке; группы
            # раскладываются в колонки после постройки (skeet_columns).
            v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            for side in ("top", "bottom", "start", "end"):
                getattr(v, "set_margin_" + side)(10)
            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.add(v)
            if self._building:
                self._page_text[self._building] = "%s %s" % (title, PAGE_TITLE.get(parent, ""))
                self._page_v[self._building] = v
            return scroll, v
        # Beta: секции реже (заголовок секции стоит над карточкой, не в ней),
        # заголовок страницы — 32 px (в beta_css), шапка с «‹ ›» — над страницей.
        v = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                    spacing=14 if self.look == "beta" else 10)
        v.set_margin_top(8 if self.look == "beta" else 12)
        v.set_margin_bottom(18)
        v.set_margin_start(PAGE_PAD)
        v.set_margin_end(PAGE_PAD)
        head = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        if parent:
            # над заголовком подпункта — его пункт, мелко акцентом: «где я»
            cr = Gtk.Label(label=PAGE_TITLE[parent], xalign=0)
            cr.get_style_context().add_class("page-crumb")
            head.pack_start(cr, False, False, 0)
        h = Gtk.Label(label=title, xalign=0)
        h.get_style_context().add_class("page-title")
        head.pack_start(h, False, False, 0)
        # Подзаголовок страницы на экран не выводится (просьба пользователя
        # 01.10.2026: «убрать описания») — остаётся подсказкой у заголовка.
        if sub:
            h.set_tooltip_text(sub)
        v.pack_start(head, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.add(v)
        if self._building:
            # Совпало название страницы (или её пункта) — показать её целиком.
            # Пояснение страницы не в счёт: оно перечисляет всё подряд.
            self._page_text[self._building] = "%s %s" % (title, PAGE_TITLE.get(parent, ""))
            self._page_v[self._building] = v         # сюда встанет полоса сброса
        return scroll, v

    def section(self, v, text, icon=None, hint=None):
        """Заголовок секции со значком; ляжет в следующую карточку."""
        self._pending_section = (text, icon or SECTION_ICON_DEFAULT, hint)

    def card(self, v):
        """Карточка секции с тонкой рамкой; сверху — заголовок из section()."""
        if self.look == "skeet":
            return self.skeet_group(v)
        if self.look == "xp":
            return self.xp_group(v)
        if self.look == "beta":
            return self.beta_group(v)
        c = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        c.get_style_context().add_class("card")
        c.page_key = self._building
        c.sec_text = ""
        if self._pending_section:
            text, icon, hint = self._pending_section
            self._pending_section = None
            head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            ic = Gtk.Label(label=icon)
            ic.get_style_context().add_class("sec-icon")
            ic.set_size_request(18, -1)
            t = Gtk.Label(label=text, xalign=0)
            t.get_style_context().add_class("sec-title")
            head.pack_start(ic, False, False, 0)
            head.pack_start(t, False, False, 0)
            head.set_margin_bottom(4)
            # пояснение секции — подсказкой при наведении на заголовок, не текстом
            if hint:
                head.set_tooltip_text(hint)
            c.pack_start(head, False, False, 0)
            c.sec_text = "%s %s" % (text, hint or "")
        v.pack_start(c, False, False, 0)
        self._cards.append(c)
        return c

    def row(self, card, title, control=None, hint=None, below=None, icon=None, default=_NODEF):
        """Строка настройки: значок и подпись слева, управление — у правого края.

        Пояснение — подсказкой при наведении (просьба пользователя 21.09.2026: «много
        текста и мало иконок»); по нему же ищет поиск. `below` — виджет под
        строкой (сетка плиток). Ползунок, переданный в `below`, встаёт в строку
        сам, фиксированной ширины SLIDER_W, а `control` (число) — справа от него.
        Сегменты, которым не хватает места справа от подписи, уходят под неё
        (01.10.2026: считается по ширине строки ROW_W).
        """
        sk = self.look == "skeet"
        bt = self.look == "beta"
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4 if sk else 6)
        if bt:
            # Beta: поля строки и тонкая линия между строками — в beta_css (.brow);
            # у первой строки карточки линии нет.
            wrap.get_style_context().add_class("brow")
            if card.get_style_context().has_class("card") and not card.get_children():
                wrap.get_style_context().add_class("first")
        else:
            wrap.set_margin_top(2 if sk else 4)
            wrap.set_margin_bottom(2 if sk else 4)
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8 if sk else 12)
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        if not sk and not bt:                        # у skeet и beta в строках значков нет
            glyph = icon or next((g for key, g in ROW_ICONS.items() if title.startswith(key)),
                                 ROW_ICON_DEFAULT)
            ic = Gtk.Label(label=glyph)
            ic.get_style_context().add_class("row-icon")
            ic.set_size_request(18, -1)
            ic.set_valign(Gtk.Align.CENTER)
            head.pack_start(ic, False, False, 0)
        t = Gtk.Label(label=title, xalign=0)
        t.get_style_context().add_class("row-title")
        t.set_line_wrap(True)
        leading(t, 14 if sk else 18)
        t.set_valign(Gtk.Align.CENTER)
        head.pack_start(t, True, True, 0)
        line.pack_start(head, True, True, 0)
        if hint:
            wrap.set_tooltip_text(hint)
        words = [title, hint or ""]
        under = []
        # 16 px пиксельного шрифта — 12 px на знак; значок с промежутком — 26 px.
        # У skeet шрифт 12 px (9 px на знак), значков нет, колонка уже.
        title_w = len(title) * 9 if sk else len(title) * 12 + (0 if bt else 26)
        row_w = SK_ROW_W if sk else ROW_W
        if isinstance(below, Gtk.Scale):
            below.set_size_request(SK_SLIDER_W if sk else SLIDER_W, -1)
            below.set_valign(Gtk.Align.CENTER)
            if control is not None:
                control.set_valign(Gtk.Align.CENTER)
                line.pack_end(control, False, False, 0)
            line.pack_end(below, False, False, 0)
        else:
            if control is not None:
                words.append(getattr(control, "search_words", ""))
                need = getattr(control, "est_width", 0)
                if need and title_w + 12 + need > row_w:
                    under.append(control)
                else:
                    control.set_valign(Gtk.Align.CENTER)
                    line.pack_end(control, False, False, 0)
            if below is not None:
                under.append(below)
        wrap.pack_start(line, False, False, 0)
        for w in under:
            w.set_halign(Gtk.Align.START)
            if not isinstance(w, Gtk.Grid) and not sk and not bt:   # плиткам отступ не нужен
                w.set_margin_start(26)
            wrap.pack_start(w, False, False, 0)
        card.pack_start(wrap, False, False, 0)
        self._rows.append((self._building, wrap, " ".join(words)))
        # Сброс страницы: у строки есть умолчание (таблица DEFAULTS или default=)
        # и управление умеет читаться и ставиться (pill, segments, slider, tiles,
        # меню места/шейдера) — в реестр.
        if default is _NODEF:
            default = DEFAULTS.get(self._building, {}).get(title, _NODEF)
        if default is not _NODEF:
            ctl = next((w for w in (control, below) if getattr(w, "rs", None)), None)
            if ctl is not None:
                self.register(wrap, title, ctl, default, **ctl.rs)
        return wrap

    # ── сброс страницы ────────────────────────────────────────────────────
    def fire(self, cb, *args):
        """Единая точка вызова обработчиков настроек: щелчок пользователя, сброс
        страницы и «Вернуть как было» зовут обработчик только отсюда; следом
        пересчитывается «изменено здесь». Проверки подменяют этот метод и
        записывают, что было бы вызвано, — настоящие настройки не трогаются."""
        try:
            return cb(*args)
        finally:
            prefetch_stale()             # чтения, запущенные до этого изменения, устарели
            self.after_change()

    def after_change(self):
        if self._resetting:
            return
        self.reset_bars_idle()          # своё изменение снимает вопрос и отмену

    def register(self, wrap, title, widget, default, get, put, cb, arg=None):
        """Настройка страницы с умолчанием: get() — текущее значение (по виджету),
        put(v) — показать v на виджете, не вызывая обработчик, cb — обработчик,
        тот же, что срабатывает от руки; arg(v) — в каком виде он ждёт значение."""
        self._settings.setdefault(self._building, []).append(dict(
            title=title, wrap=wrap, widget=widget, default=default,
            get=get, put=put, cb=cb, arg=arg or (lambda v: v)))

    @staticmethod
    def setting_live(e):
        """Настройка сейчас в деле: устройство есть, управление не погашено и
        не спрятано в свёрнутом блоке (строки только-для-XP-панели и т. п.)."""
        if getattr(e["wrap"], "absent", False) or not e["widget"].get_sensitive():
            return False
        p = e["wrap"].get_parent()
        while p is not None:
            if isinstance(p, Gtk.Revealer) and not p.get_reveal_child():
                return False
            p = p.get_parent()
        return True

    def changed_settings(self, key):
        """[(запись, текущее значение)] — что на странице отличается от умолчания."""
        out = []
        for e in self._settings.get(key, []):
            if not self.setting_live(e):
                continue
            cur = e["get"]()
            if cur != e["default"]:
                out.append((e, cur))
        return out

    def apply_setting(self, e, value):
        """Поставить значение: виджет — молча, затем обработчик (через fire)."""
        try:
            e["put"](value)
            self.fire(e["cb"], e["arg"](value))
        except Exception as err:                    # одна строка не срывает остальные
            print("settings: «%s» не применилось: %s" % (e["title"], err), file=sys.stderr)

    def add_reset_bar(self, key):
        """Низ страницы: «Сбросить эту страницу» и «изменено здесь: N». В Skeet и
        на страницах без настроек с умолчанием (Cursors, Config) полосы нет."""
        v = self._page_v.get(key)
        if self.look == "skeet" or v is None or not self._settings.get(key):
            return
        stack = Gtk.Stack()
        stack.set_transition_type(Gtk.StackTransitionType.NONE)
        stack.set_hhomogeneous(False)
        stack.get_style_context().add_class("reset-bar")

        def button(glyph, text, cb):
            b = Gtk.Button()
            b.get_style_context().add_class("fontpick")
            b.get_style_context().add_class("reset-btn")
            box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            if glyph:
                ic = Gtk.Label(label=glyph)
                ic.get_style_context().add_class("reset-icon")
                box.pack_start(ic, False, False, 0)
            box.pack_start(Gtk.Label(label=text), False, False, 0)
            b.add(box)
            b.connect("clicked", lambda _b: cb())
            return b

        def note(cls="reset-note"):
            l = Gtk.Label(xalign=0)
            l.get_style_context().add_class(cls)
            return l

        def line(*widgets):
            h = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            for w in widgets:
                w.set_valign(Gtk.Align.CENTER)
                h.pack_start(w, False, False, 0)
            return h
        bar = dict(stack=stack, count=note(), ask=note("reset-ask"), done=note())
        bar["reset"] = button("\U000f099b", "Сбросить эту страницу", lambda: self.reset_ask(key))
        # Защита от случайного нажатия: вопрос на месте кнопки, без диалога.
        yes = button("", "Да", lambda: self.reset_page(key))
        no = button("", "Нет", self.reset_bars_idle)
        undo = button("\U000f054c", "Вернуть как было", self.reset_undo)
        bar["yes"], bar["no"], bar["undo"] = yes, no, undo
        stack.add_named(line(bar["reset"], bar["count"]), "idle")
        stack.add_named(line(bar["ask"], yes, no), "ask")
        stack.add_named(line(undo, bar["done"]), "undo")
        stack.set_halign(Gtk.Align.START)
        stack.set_margin_top(2)
        v.pack_start(stack, False, False, 0)
        self._reset_bars[key] = bar
        self.reset_bar_refresh(key)

    def reset_bar_refresh(self, key):
        bar = self._reset_bars.get(key)
        if bar is None:
            return
        n = len(self.changed_settings(key))
        bar["count"].set_text("изменено здесь: %d" % n if n else "всё по умолчанию")
        bar["reset"].set_sensitive(n > 0)

    def reset_bars_idle(self):
        """Все полосы — в обычное состояние со свежим счётчиком; «Вернуть как
        было» забывается (ушли со страницы или что-то изменили сами)."""
        self._undo = None
        for key, bar in self._reset_bars.items():
            self.reset_bar_refresh(key)
            bar["stack"].set_visible_child_name("idle")

    def reset_ask(self, key):
        n = len(self.changed_settings(key))
        if not n:
            return
        bar = self._reset_bars[key]
        bar["ask"].set_text("Сбросить %s?" % plural_settings(n))
        bar["stack"].set_visible_child_name("ask")

    def reset_page(self, key):
        """«Да»: изменённые настройки страницы — к умолчаниям; прежние значения
        запоминаются для одного шага отмены."""
        todo = self.changed_settings(key)
        self._resetting = True
        try:
            for e, _old in todo:
                self.apply_setting(e, e["default"])
        finally:
            self._resetting = False
        self.reset_bars_idle()
        if todo:
            self._undo = (key, todo)
            bar = self._reset_bars[key]
            bar["done"].set_text("сброшено: %d" % len(todo))
            bar["stack"].set_visible_child_name("undo")

    def reset_undo(self):
        """«Вернуть как было»: значения, что стояли до сброса."""
        if self._undo is None:
            return
        _key, todo = self._undo
        self._resetting = True
        try:
            for e, old in todo:
                self.apply_setting(e, old)
        finally:
            self._resetting = False
        self.reset_bars_idle()

    def pill(self, active, cb):
        """Выключатель настройки. Имя осталось от недолгого опыта с кнопками
        «Вкл/Выкл»; обработчики принимают простое булево."""
        # Skeet: квадратная галочка вместо выключателя (то же свойство active).
        sw = Gtk.CheckButton() if self.look in ("skeet", "xp") else Gtk.Switch()
        sw.set_active(active)
        sw.set_valign(Gtk.Align.CENTER)
        hid = sw.connect("notify::active", lambda s, _p: self.fire(cb, s.get_active()))

        def put(val):                    # показать значение, не вызывая обработчик
            sw.handler_block(hid)
            sw.set_active(bool(val))
            sw.handler_unblock(hid)
        sw.rs = dict(get=sw.get_active, put=put, cb=cb)
        return sw

    def segments(self, items, current, cb):
        """Выбор одного из нескольких — кнопки в ряд, выбранная залита акцентом.

        cb(ключ) зовётся только на щелчок по другому варианту. Возвращает ряд;
        у ряда .select(ключ) — отметить без вызова cb.
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        btns = {}
        state = {"cur": current}

        def mark(key):
            state["cur"] = key
            for k, b in btns.items():
                ctx = b.get_style_context()
                (ctx.add_class if k == key else ctx.remove_class)("on")

        def click(_b, key):
            if key != state["cur"]:
                mark(key)
                self.fire(cb, key)
        for key, title in items:
            b = Gtk.Button(label=title)
            b.get_style_context().add_class("seg")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", click, key)
            box.pack_start(b, False, False, 0)
            btns[key] = b
        mark(current)
        box.select = mark
        box.rs = dict(get=lambda: state["cur"], put=mark, cb=cb)
        box.search_words = " ".join(t for _, t in items)
        # Подписи сегментов — 12 px шрифта, 9 px на знак; поля и рамка — 16 px.
        n = len(items)
        box.est_width = sum(len(t) for _, t in items) * 9 + n * 16 + (n - 1) * 4
        return box

    def slider(self, lo, hi, step, value, cb, suffix="", labels=None):
        """Ползунок и число справа от него. Возвращает (число, ползунок).

        `labels` — словарь {значение: подпись}: для ступеней, у которых число
        ничего не говорит.
        """
        def text(v):
            return labels.get(int(v), str(int(v))) if labels else "%d%s" % (int(v), suffix)

        s = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        s.set_draw_value(False)
        s.set_value(value)
        chip = Gtk.Label(label=text(value), xalign=1)
        chip.get_style_context().add_class("value")
        chip.set_width_chars(5)
        chip.set_valign(Gtk.Align.CENTER)
        pending = {"id": None}
        quiet = {"on": False}

        def changed(sc):
            chip.set_text(text(sc.get_value()))
            if quiet["on"]:
                return
            # Применять после паузы, а не на каждый пиксель движения ползунка.
            if pending["id"]:
                GLib.source_remove(pending["id"])
            pending["id"] = GLib.timeout_add(
                250, lambda: (pending.update(id=None), self.fire(cb, sc.get_value()), False)[2])
        s.connect("value-changed", changed)
        # Колёсико мыши НЕ меняет значение: пользователь листал страницу, курсор
        # проходил над ползунком — и скругление окон случайно уехало в 0
        # (14.09.2026). Прокрутку отдаём странице, чтобы над ползунком она
        # листалась как везде; сам ползунок меняется только перетаскиванием.
        s.connect("scroll-event", self.pass_scroll_to_page)

        def set_quiet(val):
            """Поставить значение, НЕ вызывая cb: для уточнения из фонового чтения."""
            quiet["on"] = True
            s.set_value(val)
            quiet["on"] = False
        s.set_quiet = set_quiet
        s.rs = dict(get=lambda: int(round(s.get_value())), put=set_quiet, cb=cb, arg=float)

        # Ctrl+щелчок по числу или по ползунку — ввести значение вручную (04.10.2026,
        # пользователь). Enter или уход фокуса — применить (с шагом и в пределах ползунка),
        # Esc — отмена. «%», «px», запятая вместо точки не мешают.
        entry = Gtk.Entry()
        entry.set_width_chars(5)
        entry.set_max_width_chars(6)
        entry.set_alignment(1.0)
        entry.get_style_context().add_class("value-edit")
        stack = Gtk.Stack()
        stack.set_valign(Gtk.Align.CENTER)
        stack.add_named(chip, "label")
        stack.add_named(entry, "edit")
        box = Gtk.EventBox()
        box.add(stack)
        box.set_tooltip_text("Ctrl+щелчок — ввести число")
        editing = {"on": False}

        def start_edit():
            editing["on"] = True
            entry.set_text(str(int(round(s.get_value()))))
            stack.set_visible_child_name("edit")
            entry.grab_focus()
            entry.select_region(0, -1)

        def finish(apply):
            if not editing["on"]:
                return
            editing["on"] = False
            if apply:
                raw = entry.get_text().strip().replace(",", ".")
                raw = "".join(ch for ch in raw if ch.isdigit() or ch in ".-")
                try:
                    v = float(raw)
                except ValueError:
                    v = None
                if v is not None:
                    v = round((v - lo) / step) * step + lo if step else v
                    s.set_value(max(lo, min(hi, v)))
            stack.set_visible_child_name("label")

        def on_press(_w, ev):
            if ev.button == 1 and ev.state & Gdk.ModifierType.CONTROL_MASK:
                start_edit()
                return True
            return False

        def on_key(_w, ev):
            if ev.keyval == Gdk.KEY_Escape:
                finish(False)
                return True
            return False

        box.connect("button-press-event", on_press)
        s.connect("button-press-event", on_press)
        entry.connect("activate", lambda _e: finish(True))
        entry.connect("key-press-event", on_key)
        entry.connect("focus-out-event", lambda *_a: (finish(True), False)[1])
        return box, s

    def pass_scroll_to_page(self, widget, event):
        """Переслать прокрутку ближайшему ScrolledWindow и не менять ползунок."""
        page = widget.get_ancestor(Gtk.ScrolledWindow)
        if page is not None:
            page.event(event)
        return True

    def tiles(self, items, current, draw, pick, per_row=4, height=44):
        """Сетка плиток-схем: все одной ширины TILE_W, по per_row в ряд,
        прижаты влево (01.10.2026: раньше растягивались на всю ширину окна)."""
        grid = Gtk.Grid(column_spacing=TILE_GAP, row_spacing=TILE_GAP)
        grid.set_column_homogeneous(True)
        grid.set_margin_top(2)
        grid.set_margin_bottom(2)
        store = {}
        for i, (key, title) in enumerate(items):
            b = Gtk.Button()
            b.get_style_context().add_class("tile")
            b.set_relief(Gtk.ReliefStyle.NONE)
            if key == current:
                b.get_style_context().add_class("tile-active")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            da = Gtk.DrawingArea()
            da.set_size_request(TILE_W, height)
            da.connect("draw", lambda a, cr, k=key: draw(
                cr, a.get_allocated_width(), a.get_allocated_height(), k, self.pal))
            name = Gtk.Label(label=title)
            name.get_style_context().add_class("tile-name")
            name.set_ellipsize(Pango.EllipsizeMode.END)
            name.set_max_width_chars(TILE_W // 9)
            inner.pack_start(da, False, False, 0)
            inner.pack_start(name, False, False, 0)
            b.add(inner)
            b.set_tooltip_text(title)
            b.connect("clicked", lambda _b, k=key: self.pick_tile(store, k, pick))
            grid.attach(b, i % per_row, i // per_row, 1, 1)
            store[key] = b
        grid.search_words = " ".join(t for _, t in items)
        grid.rs = dict(
            get=lambda: next((k for k, b in store.items()
                              if b.get_style_context().has_class("tile-active")), None),
            put=lambda key: self.mark_tile(store, key), cb=pick)
        return grid

    @staticmethod
    def mark_tile(store, key):
        for k, b in store.items():
            ctx = b.get_style_context()
            (ctx.add_class if k == key else ctx.remove_class)("tile-active")

    def pick_tile(self, store, key, pick):
        self.mark_tile(store, key)
        self.fire(pick, key)

    def menu_button(self, width):
        """Кнопка с меню под ней: (кнопка, подпись, меню)."""
        label = Gtk.Label(xalign=0)
        label.set_ellipsize(Pango.EllipsizeMode.END)
        label.set_max_width_chars(max(8, (width - 40) // 9))
        arrow = Gtk.Label(label="\U000f0140")
        arrow.get_style_context().add_class("pick-arrow")
        box = Gtk.Box(spacing=10)
        box.pack_start(label, True, True, 0)
        box.pack_end(arrow, False, False, 0)
        btn = Gtk.MenuButton()
        btn.get_style_context().add_class("fontpick")
        btn.set_direction(Gtk.ArrowType.DOWN)
        btn.add(box)
        menu = Gtk.Menu()
        btn.set_popup(menu)
        btn.set_size_request(width, -1)
        btn.est_width = width
        return btn, label, menu

    def draw_login_look(self, cr, w, h, key, pal):
        """Плитка варианта экрана входа: картинка «с обрезкой по центру»."""
        cache = self.__dict__.setdefault("_login_pix", {})
        if key not in cache:
            path = login_theme.preview(key)
            try:
                # Фоны тем до 3840x2160: для плитки 170x96 хватает 480 px в ширину,
                # полный размер держал бы в памяти десятки мегабайт на 11 плиток.
                cache[key] = (GdkPixbuf.Pixbuf.new_from_file_at_scale(path, 480, -1, True)
                              if path else None)
            except GLib.Error:
                cache[key] = None
        pix = cache[key]
        if pix is None:
            # Нет картинки (встроенная тема SDDM «Как было»): фон палитры и значок.
            cr.set_source_rgb(0.15, 0.17, 0.22)
            cr.rectangle(0, 0, w, h)
            cr.fill()
            cr.set_source_rgba(1, 1, 1, 0.55)
            cr.select_font_face("Sans")
            cr.set_font_size(h * 0.32)
            ext = cr.text_extents("SDDM")
            cr.move_to((w - ext.width) / 2 - ext.x_bearing, (h - ext.height) / 2 - ext.y_bearing)
            cr.show_text("SDDM")
            return
        scale = max(w / pix.get_width(), h / pix.get_height())
        cr.save()
        cr.rectangle(0, 0, w, h)
        cr.clip()
        cr.translate((w - pix.get_width() * scale) / 2, (h - pix.get_height() * scale) / 2)
        cr.scale(scale, scale)
        Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
        cr.paint()
        cr.restore()

    def draw_lock_look(self, cr, w, h, key, pal):
        """Плитка стиля блокировки — схема: «Как сейчас» — тёмный фон, круг
        аватара, часы акцентом и поле; остальные — картинка варианта (как у
        экрана входа), панель, часы и поле."""
        def rgb(hexs, a=1.0):
            hexs = hexs.lstrip("#")
            cr.set_source_rgba(int(hexs[0:2], 16) / 255, int(hexs[2:4], 16) / 255,
                               int(hexs[4:6], 16) / 255, a)
        if key != "current":
            self.draw_login_look(cr, w, h, key, pal)
            rgb(pal["surface"], 0.7)
            pw, ph = w * 0.34, h * 0.86
            cr.rectangle((w - pw) / 2, (h - ph) / 2, pw, ph)
            cr.fill()
            clock_y, clock_col, field_y = h * 0.36, pal["on_surface"], h * 0.66
        else:
            rgb(pal["surface"])
            cr.rectangle(0, 0, w, h)
            cr.fill()
            rgb(pal["primary"])
            cr.arc(w / 2, h * 0.52, h * 0.1, 0, 6.2832)
            cr.set_line_width(1.5)
            cr.stroke()
            clock_y, clock_col, field_y = h * 0.3, pal["primary"], h * 0.74
        rgb(clock_col)
        cr.select_font_face("Sans")
        cr.set_font_size(h * 0.2)
        ext = cr.text_extents("12:00")
        cr.move_to((w - ext.width) / 2 - ext.x_bearing, clock_y - ext.y_bearing - ext.height / 2)
        cr.show_text("12:00")
        rgb(pal["primary"])
        fw, fh = w * 0.26, h * 0.1
        cr.rectangle((w - fw) / 2, field_y, fw, fh)
        cr.set_line_width(1.2)
        cr.stroke()

    # ── страницы ──────────────────────────────────────────────────────────
    # 01.10.2026 разложены по дереву TREE. Удалены совсем (просьба пользователя):
    # «Как раскладывать окна» (лента/классика), «Карта ленты в баре», «Столы
    # значками, а не номерами» — сами скрипты layout_mode.py, ribbon_map.py,
    # ws_labels.py на месте, их просто нет в Настройках.

    # Waybar — одна страница (01.10.2026: «Форма панели» и «Скругления и
    # отступы» были подпунктами, пользователь попросил свести в одну)
    def page_waybar(self):
        scroll, v = self.page("Waybar", "Форма верхней панели, её углы и отступы.")
        self.section(v, "Форма панели", "\U000f1513")
        c = self.card(v)
        self.row(c, "Форма верхней панели", icon="\U000f1513",
                 hint="Щелчок по схемке переключает бар сразу. Свои отступы сверху и снизу — "
                      "ниже, в «Углы и отступы».",
                 below=self.tiles(LOOKS, run("python3", BAR_STYLE, "get"),
                                  popup_theme.draw_bar_look,
                                  lambda k: subprocess.Popen(
                                      ["python3", BAR_STYLE, "set", k],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True),
                                  per_row=4, height=40))

        self.section(v, "Углы и отступы", "\U000f084f",
                     "Свои отступы действуют при любой форме панели. Их смена перезапускает "
                     "бар — он мигнёт.")
        c = self.card(v)
        try:
            bar_r = int(run("python3", BAR_ROUNDING, "get"))
        except ValueError:
            bar_r = 0
        chip, sc = self.slider(0, 16, 1, bar_r,
                               lambda val: run("python3", BAR_ROUNDING, "set", "%d" % val),
                               suffix=" px")
        self.row(c, "Скругление углов бара", chip,
                 "Углы самой панели: 0 — прямые. Значки внутри бара не меняются. "
                 "Применяется сразу к любому виду бара.",
                 below=sc)

        # Отступы сверху и снизу (01.10.2026): bar_margins.py пишет состояние,
        # waybar_niri.py вписывает margin-top/-bottom в config-niri.jsonc, бар
        # перезапускается один раз (barfix) — только на щелчок, не при открытии.
        parts = run("python3", BAR_MARGINS, "get").split()
        try:
            edge, win = int(parts[0]), int(parts[1])
            look = (int(parts[3]), int(parts[4]))
        except (IndexError, ValueError):
            edge, win, look = 0, 0, (0, 0)
        cur = {"edge": edge, "win": win}

        def steps(val):
            return [(str(x), "%d px" % x) for x in sorted({0, 4, 8, 12, 16, val})]

        def put(which, k):
            cur[which] = int(k)
            run_serial(["python3", BAR_MARGINS, "set", str(cur["edge"]), str(cur["win"])])
        edge_seg = self.segments(steps(edge), str(edge), lambda k: put("edge", k))
        win_seg = self.segments(steps(win), str(win), lambda k: put("win", k))
        edge_row = self.row(c, "От края экрана", edge_seg,
                 "Расстояние от бара до края экрана, у которого он стоит (у формы «Снизу» — "
                 "до нижнего). 0 — вплотную. Приклеенные попапы пока считают бар стоящим "
                 "вплотную к краю: при отступе больше 0 они заходят на бар.")
        self.row(c, "До окон", win_seg,
                 "Промежуток между баром и окнами — сверх обычного зазора niri. Обычные "
                 "попапы бара отодвигаются вместе с окнами.")

        def reset():
            run_serial(["python3", BAR_MARGINS, "reset"])
            cur["edge"], cur["win"] = look
            edge_seg.select(str(look[0]))
            win_seg.select(str(look[1]))

        # Для «Сбросить эту страницу» оба отступа — одна настройка: умолчание —
        # как у формы панели (нет файла bar-margins), вернуть его — «reset», а
        # не «set» (тот оставил бы свои отступы, пусть и равные форме).
        def margins_show(val):
            cur["edge"], cur["win"] = val
            edge_seg.select(str(val[0]))
            win_seg.select(str(val[1]))

        def margins_apply(val):
            if tuple(val) == tuple(look):
                run_serial(["python3", BAR_MARGINS, "reset"])
            else:
                run_serial(["python3", BAR_MARGINS, "set", str(val[0]), str(val[1])])
        self.register(edge_row, "Отступы бара", edge_seg, tuple(look),
                      get=lambda: (cur["edge"], cur["win"]), put=margins_show, cb=margins_apply)
        self.row(c, "Отступы — как у формы панели", self.go_button("Сбросить", reset),
                 "Убрать свои отступы: бар встанет так, как задумано в выбранной форме "
                 "панели (сейчас — от края %d px, до окон %d px)." % look)
        self.bar_extras(v)
        self.xp_cards(v)
        return scroll

    # Visuals
    def bar_extras(self, v):
        """Что живёт на панели, попапы и меню (до 01.10.2026 — страница Visuals)."""
        # Верхний бар: всегда / при наведении / выключен, и где список столов (03.10.2026,
        # top_bar.py). Применение перезапускает панели — идёт в фоне, по очереди.
        tb = os.path.join(HERE, "top_bar.py")
        if os.path.exists(tb):
            self.section(v, "Показ панелей", "\U000f06d0")
            c = self.card(v)
            self.row(c, "Верхний бар",
                     self.segments([("always", "Всегда"), ("hover", "При наведении"), ("off", "Выключен")],
                                   (lambda x: x if x in ("always", "hover", "off") else "always")(
                                       run("python3", tb, "get")),
                                   lambda k: run_serial(["python3", tb, "set", k])),
                     "При наведении — бар спрятан и выезжает поверх окон у верхнего края. "
                     "Выключен — бара нет, столы и всё остальное в нижней панели.",
                     icon="\U000f06d0")
            self.row(c, "Список столов",
                     self.segments([("top", "В верхнем баре"), ("bottom", "В нижней панели")],
                                   (lambda x: x if x in ("top", "bottom") else "top")(
                                       run("python3", tb, "ws")),
                                   lambda k: run_serial(["python3", tb, "ws", k])),
                     "В нижней панели — столы между «Пуском» и окнами; нижняя панель при этом "
                     "включается (XP, всегда).",
                     icon="\U000f0570")
            # Плотность фона и размытие верхнего бара (04.10.2026): top_bar.py
            # opacity/blur — пишут стиль бара и правило niri, без перезапуска панелей.
            def tb_num(kind, dflt):
                try:
                    return int(run("python3", tb, "opacity", kind))
                except ValueError:
                    return dflt
            chip, sc = self.slider(20, 100, 2, tb_num("always", 88),
                                   lambda val: run_serial(["python3", tb, "opacity", "always", str(int(val))]),
                                   suffix="%")
            self.row(c, "Плотность фона бара", chip,
                     "Режим «Всегда»: 100% — глухой фон, меньше — сквозь бар видны обои. "
                     "У вида «Прозрачный» фона нет — ползунок его не меняет.",
                     below=sc, icon="\U000f0e8e")
            self.row(c, "Размытие под баром",
                     self.pill(run("python3", tb, "blur") == "on",
                               lambda on: run_serial(["python3", tb, "blur", "on" if on else "off"])),
                     "Только в режиме «Всегда». При наведении niri размывал бы обои и под "
                     "спрятанным баром — сверху висела бы мутная полоса. Сила размытия в niri одна "
                     "на всю систему, отдельно для бара её не задать.",
                     icon="\U000f00b6")
        self.section(v, "В баре", "\U000f0570")
        c = self.card(v)
        # «Пуск» в стиле XP (30.09.2026): start_button.py.
        sb = os.path.join(HERE, "start_button.py")
        self.row(c, "Кнопка «Пуск» — пиксельная",
                 self.pill(run("python3", sb, "get") == "pixel",
                           lambda on: subprocess.run(["python3", sb, "set", "pixel" if on else "nerd"],
                                                     capture_output=True)),
                 "Логотип Arch слева в баре: обычный значок или пиксельный, в духе XP.")
        # Bongo Cat в баре (30.09.2026): bongo_cat.py on|off|status, скрипт сам
        # замечает смену за секунду.
        bongo = os.path.join(HERE, "bongo_cat.py")
        self.row(c, "Bongo Cat в баре",
                 self.pill(run("python3", bongo, "status") == "on",
                           lambda on: subprocess.run(["python3", bongo, "on" if on else "off"],
                                                     capture_output=True)),
                 "Кошка стучит лапами в такт нажатиям клавиш, а без набора — в такт музыке.")
        # Эквалайзер в баре: столбики (как было) или плавная волна в духе Noctalia
        # (30.09.2026). cava_bar.py сам замечает смену за секунду.
        vis_file = os.path.expanduser("~/.config/hypr/state/bar-vis")

        def set_vis(k):
            os.makedirs(os.path.dirname(vis_file), exist_ok=True)
            with open(vis_file, "w") as f:
                f.write("wave\n" if k == "wave" else "blocks\n")
        try:
            vis = "wave" if open(vis_file).read().strip() == "wave" else "blocks"
        except OSError:
            vis = "blocks"
        self.row(c, "Эквалайзер",
                 self.segments([("wave", "Волна"), ("blocks", "Столбики")], vis, set_vis),
                 "Волна — зеркальная плавная волна как в Noctalia, столбики — прежние блоки. "
                 "Переключается сразу, пока играет звук.")

        self.section(v, "Попапы и меню", "\U000f035c")
        c = self.card(v)
        # Значки меню выключения (wlogout): новые, как в power_menu.py, или
        # стандартные — выбор пользователя, 30.09.2026.
        wli = os.path.join(HERE, "wlogout_icons.py")
        self.row(c, "Меню выключения — новые значки",
                 self.pill(run("python3", wli, "status") == "new",
                           lambda on: subprocess.run(["python3", wli, "new" if on else "old"],
                                                     capture_output=True)),
                 "Вкл — значки в стиле системы (Material), выкл — стандартные картинки wlogout.")
        # Попапы «приклеены» к бару с вогнутыми углами (30.09.2026, по образцу
        # Noctalia): popup_theme.attached() читает этот файл при каждом открытии.
        att_file = os.path.expanduser("~/.config/hypr/state/popup-attached")

        def set_attached(on):
            if on:
                open(att_file, "w").close()
            elif os.path.exists(att_file):
                os.remove(att_file)
        self.row(c, "Попапы приклеены к бару", self.pill(os.path.exists(att_file), set_attached),
                 "Плеер, звук, Wi-Fi, Bluetooth, центр управления открываются вплотную "
                 "под баром, его цветом, с вогнутыми углами на стыке — как в Noctalia. "
                 "Действует на следующее открытие попапа.")

    # Niri: всё про окна (01.10.2026 — было Visuals → «Окна»)
    def obsidian_card(self, v):
        """Прозрачность Obsidian (была в «Окнах»)."""
        self.section(v, "Obsidian", "\U000f0354")
        c = self.card(v)
        try:
            obs = int(run("python3", OBSIDIAN_OPACITY, "get"))
        except ValueError:
            obs = 96
        chip, sc = self.slider(70, 100, 1, obs,
                               lambda val: run("python3", OBSIDIAN_OPACITY, "set", "%d" % val),
                               suffix="%")
        self.row(c, "Прозрачность Obsidian", chip,
                 "100 — окно плотное, меньше — сквозь него проступают размытые обои. "
                 "Неактивное окно чуть прозрачнее. Цвета из обоев не меняются. "
                 "Применяется сразу и запоминается.",
                 below=sc)

    def window_cards(self, v):
        """Окна: скругление и фокус (была страница Niri)."""
        self.section(v, "Окна", "\U000f05af")
        c = self.card(v)
        try:
            rounding = int(run("python3", ROUNDING, "get"))
        except ValueError:
            rounding = 4
        chip, sc = self.slider(0, 24, 1, rounding,
                               lambda val: run("python3", ROUNDING, "set", "%d" % val),
                               suffix=" px")
        self.row(c, "Скругление окон", chip,
                 "0 — прямые углы. Применяется сразу ко всем окнам и запоминается. "
                 "Бар, попапы и меню приложений скругляются отдельно.",
                 below=sc)
        self.row(c, "Окно с фокусом — по центру",
                 self.pill(run("python3", RIBBON_CENTER, "get") == "center",
                           lambda on: run("python3", RIBBON_CENTER, "center" if on else "fit")),
                 "Лента ставит окно с фокусом в центр экрана, соседи видны по краям — "
                 "вернулись к окну, и вид тот же. Выкл — лента сдвигается ровно настолько, "
                 "чтобы окно влезло, и вид зависит от того, откуда пришли.")
        self.row(c, "Наведение мыши забирает фокус",
                 self.pill(run("python3", MOUSE, "get") == "follow",
                           lambda on: run("python3", MOUSE, "follow" if on else "detached")),
                 "Выкл — наведение отдаёт окну только мышь, клавиатура остаётся на месте. "
                 "В ленте это важно: иначе задетая мышью соседняя колонка прокручивает "
                 "ленту к себе. Щелчок по окну фокус переводит всегда.")
        # «Затемнять фоновые окна» и «Сила затемнения» убраны 01.10.2026: это
        # dim_inactive Hyprland, под niri они были погашены и не работали.
        # Эффект открытия/закрытия окон (02.10.2026): window_fx.py get|set pixel|off.
        wf = os.path.join(HERE, "window_fx.py")
        self.row(c, "Эффект открытия/закрытия окон", self.segments(
            [("pixel", "Пиксели"), ("off", "Выкл")],
            (lambda x: x if x in ("pixel", "off") else "off")(run("python3", wf, "get")),
            lambda k: subprocess.run(["python3", wf, "set", k], capture_output=True)),
                 "Окна появляются и исчезают, рассыпаясь на пиксели.", icon="\U000f05af")

    def mouse_cards(self, v):
        """Мышь и запись: «встряхни мышь» и авто-DND при записи экрана."""
        self.section(v, "Мышь и запись", "\U000f037d")
        c = self.card(v)
        for title, script, hint in (
                ("Встряхни мышь — найти курсор", "cursor_shake.py",
                 "Быстро подвигать мышью из стороны в сторону — курсор на миг вырастает."),
                ("Авто «Не беспокоить» при записи экрана", "auto_dnd.py",
                 "Пока идёт запись или демонстрация экрана, уведомления не всплывают.")):
            path = os.path.join(HERE, script)
            self.row(c, title,
                     self.pill(run("python3", path, "status") == "on",
                               lambda on, pth=path: subprocess.run(
                                   ["python3", pth, "on" if on else "off"], capture_output=True)),
                     hint, icon="\U000f037d")

    # Misc: снимки экрана и окна (01.10.2026, раунд 3)
    def page_misc(self):
        scroll, v = self.page("Misc", "Снимки, окна, уведомления, питание, мышь и запись.")
        self.shots_cards(v)
        self.window_cards(v)
        self.notify_cards(v)
        self.power_cards(v)
        self.mouse_cards(v)
        return scroll

    # Config: вид самих Настроек
    def page_config(self):
        scroll, v = self.page("Config", "Вид окна Настроек.")
        if self.look == "beta":
            self.quick_card(v)
        # «Стиль системы» (04.10.2026, просьба: «не нравится выбор вида для каждого окна —
        # давай единый стиль для всей системы, разделить можно только мониторы»). Один
        # выбор раздаёт стиль всем окнам (system_style.py: Настройки, буфер обмена,
        # Recorder, «Пуск», виджеты); у виджетов по мониторам — только «Без рамок».
        self.section(v, "Стиль системы", "\U000f08b5")
        c = self.card(v)
        # Смена вида перестраивает страницы — и эту тоже; поэтому не из
        # обработчика щелчка, а следом, в простое.
        seg = self.segments(STYLE_LOOKS, self.skin,
                            lambda k: (run_serial(["python3", SYSSTYLE, "set", k]),
                                       GLib.idle_add(lambda: (self.set_view(skin=k), False)[1])))
        ctl = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        ctl.pack_start(seg, False, False, 0)
        ctl.est_width = seg.est_width
        ctl.search_words = seg.search_words
        # Режим Light/Dark — общий для Default и Beta; у Skeet стиль один, и
        # переключателя режима в нём нет (раунд 6, 02.10.2026).
        self.mode_seg = None
        if self.skin != "skeet":
            self.mode_seg = self.segments(
                MODES, self.mode,
                lambda k: GLib.idle_add(lambda: (self.set_view(mode=k), False)[1]))
            # приписки-значки: солнце перед Light, луна перед Dark
            for b, (k, _t) in zip(self.mode_seg.get_children(), MODES):
                lbl = b.get_child()
                b.remove(lbl)
                pair = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=5)
                ic = Gtk.Label(label=MODE_ICONS[k])
                ic.get_style_context().add_class("seg-icon")
                pair.pack_start(ic, False, False, 0)
                pair.pack_start(lbl, False, False, 0)
                b.add(pair)
            ctl.pack_start(self.mode_seg, False, False, 0)
            ctl.est_width += 12 + self.mode_seg.est_width + 2 * 21
            ctl.search_words += " Light Dark светлый тёмный темный режим"
        # По мониторам (04.10.2026, «сделай раздельные стили для разных мониторов»): у
        # каждого монитора свой стиль; окна в фокусе берут стиль своего монитора (сторож
        # system_style.py watch), виджеты — сразу. Light/Dark — общий для Обычного и Beta.
        if self.mode_seg is not None:
            if self.mode_seg.get_parent() is not None:      # сегмент собран внутри ctl выше
                self.mode_seg.get_parent().remove(self.mode_seg)
            self.row(c, "Режим", self.mode_seg,
                     "Светлый или тёмный — для стилей Обычный и Beta.")
        # Единый стиль (04.10.2026: пользователь сперва попросил стили по мониторам, потом
        # «передумал — стиль системы должен быть единым»). Один выбор — всем окнам и
        # виджетам обоих мониторов (system_style.py set); у виджетов по мониторам — только
        # «Без рамок», отдельной группой, чтобы строки не путались.
        if os.path.exists(SYSSTYLE):
            # текущее значение — вид самого окна: чтение system_style шло раньше, чем очередь
            # run_serial успевала записать новый, и страница показывала прежний стиль (баг 04.10)
            cur = self.skin
            self.row(c, "Стиль окон",
                     self.segments(STYLE_LOOKS, cur if cur in dict(STYLE_LOOKS) else "default",
                                   lambda k: (run_serial(["python3", SYSSTYLE, "set", k]),
                                              GLib.idle_add(lambda: (self.set_view(skin=k), False)[1]))),
                     "Один вид для всей системы: Настройки, буфер обмена, Recorder, меню «Пуск» "
                     "и виджеты. Обычный — в духе Windows XP, Skeet — меню gamesense, Beta — "
                     "новый плоский вид. Цвета — из обоев.")
        # Кнопка «Пуск» в нижней панели (04.10.2026): обычная или квадратная, как у angelOS
        # (start_menu.py button default|square). Само меню «Пуск» — в стиле монитора.
        sm = os.path.join(HERE, "start_menu.py")
        if os.path.exists(sm):
            curb = run("python3", sm, "button", "get")
            # своя группа — не в одном месте со стилем окон (04.10.2026)
            self.section(v, "Нижняя панель", "\U000f035c")
            pc = self.card(v)
            self.row(pc, "Кнопка «Пуск»",
                     self.segments([("default", "Обычная"), ("square", "Квадратная")],
                                   curb if curb in ("default", "square") else "default",
                                   lambda k: run_serial(["python3", sm, "button", k])),
                     "Кнопка «Пуск» в нижней панели. Меню «Пуск» само берёт стиль монитора.",
                     icon="\U000f035c", default="default")
        if os.path.exists(SYSSTYLE):
            self.section(v, "Виджеты на обоях", "\U000f05af")
            wc = self.card(v)
            for o in [l.split("\t") for l in run("python3", BLUR, "outputs").splitlines() if "\t" in l]:
                name, label = o[0], o[1]
                curw = run("python3", SYSSTYLE, "widgets", name)
                self.row(wc, label[:1].upper() + label[1:],
                         self.segments([("system", "Как стиль"), ("classic", "Без рамок")],
                                       curw if curw in ("system", "classic") else "system",
                                       lambda k, n=name: run_serial(["python3", SYSSTYLE, "widgets", n, k])),
                         "Виджеты на этом мониторе: в стиле системы или плашкой без заголовка.",
                         default="system")
        self.section(v, "Окно Настроек", "\U000f0493")
        c = self.card(v)
        # Резидент (раунд 8): состояние — файл RESIDENT_OFF, читается при закрытии окна.
        self.row(c, "Быстрое открытие", self.pill(resident_on(), resident_set),
                 "Вкл — крестик прячет окно, а не закрывает: Настройки остаются в памяти и "
                 "по Super+/ появляются сразу; значения при показе перечитываются. "
                 "Выкл — окно закрывается насовсем, каждый запуск — с нуля.",
                 icon="\U000f04c5")
        return scroll

    def quick_card(self, v):
        """Блок «Частое» (вид Beta, страница Config): плитки со значком и подписью."""
        self.section(v, "Частое", "\U000f04ce")
        c = self.card(v)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_homogeneous(True)
        box.set_margin_top(6)
        box.set_margin_bottom(6)

        def spawn(*args):
            subprocess.Popen(list(args), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)

        def flip():
            GLib.idle_add(lambda: (self.set_view(
                mode="light" if self.mode == "dark" else "dark"), False)[1])
        items = [
            ("\U000f02e9", "Сменить\nобои",
             lambda: spawn("python3", os.path.join(HERE, "wallpaper_picker.py"))),
            ("\U000f050e", "Light/Dark", flip),
            ("\U000f0284", "Шрифты", lambda: self.select_page("fonts")),
            ("\U000f01bf", "Курсор", lambda: self.select_page("cursor")),
            ("\U000f072c", "Расставить\nвиджеты",
             lambda: spawn("python3", os.path.join(HERE, "desktop_widgets.py"), "edit")),
        ]
        self.quick_buttons = {}
        for glyph, title, cb in items:
            b = Gtk.Button()
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.get_style_context().add_class("quick")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            inner.set_valign(Gtk.Align.CENTER)
            ic = Gtk.Label(label=glyph)
            ic.get_style_context().add_class("quick-icon")
            name = Gtk.Label(label=title)
            name.get_style_context().add_class("quick-name")
            name.set_justify(Gtk.Justification.CENTER)
            leading(name, 14)
            inner.pack_start(ic, False, False, 0)
            inner.pack_start(name, False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, f=cb: f())
            box.pack_start(b, True, True, 0)
            self.quick_buttons[title.replace("\n", " ")] = b
        c.pack_start(box, False, False, 0)
        self._rows.append((self._building, box,
                           "Частое " + " ".join(t.replace("\n", " ") for _g, t, _c in items)
                           + " обои режим светлый тёмный шрифт курсор виджеты"))

    def default_apps_card(self, v):
        """Приложения по умолчанию: выбор из установленных .desktop по MIME.
        Текущее — Gio.AppInfo.get_default_for_type, установка —
        set_as_default_for_type для группы связанных типов."""
        self.section(v, "Приложения по умолчанию", "\U000f003b")
        c = self.card(v)
        kinds = [
            ("Браузер", ["x-scheme-handler/https", "x-scheme-handler/http", "text/html"],
             "Чем открываются ссылки и страницы."),
            ("Терминал", ["x-scheme-handler/terminal"],
             "Список — программы категории «терминал». Запоминается как обработчик "
             "x-scheme-handler/terminal; смотрят на него не все программы."),
            ("Файловый менеджер", ["inode/directory"], "Чем открываются папки."),
            ("Просмотр картинок", ["image/png", "image/jpeg", "image/webp", "image/gif"],
             "PNG, JPEG, WebP, GIF."),
            ("Видеоплеер", ["video/mp4", "video/webm", "video/x-matroska"], "MP4, WebM, MKV."),
            ("Текстовый редактор", ["text/plain"], "Обычные текстовые файлы."),
        ]
        for title, mimes, hint in kinds:
            self.row(c, title, self.default_app_combo(mimes), hint, icon="\U000f003b")

    def default_app_combo(self, mimes):
        main = mimes[0]
        if main == "x-scheme-handler/terminal":
            apps = [a for a in Gio.AppInfo.get_all()
                    if "TerminalEmulator" in (getattr(a, "get_categories", lambda: "")() or "")]
        else:
            apps = Gio.AppInfo.get_all_for_type(main)
        apps = sorted((a for a in apps if a.should_show()),
                      key=lambda a: a.get_display_name().casefold())
        cur = Gio.AppInfo.get_default_for_type(main, False)
        btn, label, menu = self.menu_button(200)
        label.set_text(cur.get_display_name() if cur else "не задано")

        def pick(_item, app):
            label.set_text(app.get_display_name())
            for m in mimes:
                try:
                    app.set_as_default_for_type(m)
                except GLib.Error:
                    pass
        for app in apps:
            item = Gtk.MenuItem(label=app.get_display_name())
            item.connect("activate", pick, app)
            menu.append(item)
        menu.show_all()
        btn.search_words = " ".join(a.get_display_name() for a in apps)
        return btn

    # Windows XP: меню рабочего стола и нижняя панель (бывший раздел «Нижняя панель»)
    def xp_cards(self, v):
        """Меню рабочего стола и нижняя панель (была страница Windows XP; с 02.10.2026 — в Waybar)."""
        self.section(v, "Windows XP", "\U000f05b3")
        c = self.card(v)
        # Меню рабочего стола в стиле XP (30.09.2026): desktop_menu.py on|off|state.
        # Строка переименована 01.10.2026, заголовок секции убран (просьба пользователя).
        dm = os.path.join(HERE, "desktop_menu.py")
        self.row(c, "Действие на правый клик",
                 self.pill(run("python3", dm, "state") == "on",
                           lambda on: subprocess.run(["python3", dm, "on" if on else "off"],
                                                     capture_output=True)),
                 "Правый щелчок по пустым обоям — меню как в Windows XP: частые программы, "
                 "создать/открыть, обои, терминал, экранное время. Выкл — убирается совсем.")
        # Вид этого меню (01.10.2026): desktop_menu.py style [xp|classic].
        self.row(c, "Вид меню", self.segments(
            [("xp", "XP"), ("classic", "Прежний")],
            (lambda v: v if v in ("xp", "classic") else "xp")(run("python3", dm, "style")),
            lambda k: subprocess.run(["python3", dm, "style", k], capture_output=True)),
                 "Как выглядит меню по правому щелчку: в духе Windows XP или прежнее.",
                 icon="\U000f035c")

        self.section(v, "Нижняя панель", "\U000f10a9",
                     "Одновременно — только одно из трёх. Щелчок по схеме переключает сразу.")
        c = self.card(v)
        kind = run("python3", BOTTOM_BAR, "get")
        if kind not in ("none", "dock", "xp"):
            kind = "none"
        xp_rev = Gtk.Revealer()
        dock_rev = Gtk.Revealer()

        def pick(k):
            run_serial(["python3", BOTTOM_BAR, "set", k])
            xp_rev.set_reveal_child(k == "xp")
            dock_rev.set_reveal_child(k == "dock")
        self.row(c, "Форма панели", icon="\U000f10a9",
                 hint="Панель у нижнего края. Ничего — низ экрана свободен. Док — значки окон "
                      "по центру, выезжает, если довести курсор до низа экрана. XP-панель — "
                      "полоса во всю ширину: «Пуск» слева, окна, трей и часы справа.",
                 below=self.tiles(BOTTOMS, kind, draw_bottom_look, pick, per_row=4, height=64))

        # Как появляется XP-панель: всегда на месте или выезжает при наведении.
        xcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        show = run("python3", BOTTOM_BAR, "show")
        gap_rev = Gtk.Revealer()

        def pick_show(k):
            run_serial(["python3", BOTTOM_BAR, "show", k])
            gap_rev.set_reveal_child(k != "hover")
        self.row(xcard, "Появление",
                 self.segments([("always", "Всегда"), ("hover", "При наведении"),
                                ("button", "По Super+S")], show, pick_show),
                 "Всегда — панель стоит внизу постоянно. При наведении — прячется и выезжает, "
                 "когда курсор доходит до нижнего края. По Super+S — появляется и прячется "
                 "только по сочетанию клавиш. Super+S работает в любом режиме.")
        # Зазор между окнами и панелью (01.10.2026) — когда панель отодвигает окна:
        # «всегда» и «по Super+S». Выезжающая при наведении окна не двигает.
        gbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.row(gbox, "Окна и панель",
                 self.segments([("on", "С зазором"), ("off", "Вплотную")],
                               run("python3", BOTTOM_BAR, "gap"),
                               lambda k: run_serial(["python3", BOTTOM_BAR, "gap", k])),
                 "С зазором — между низом окон и панелью обычный промежуток, как между окнами. "
                 "Вплотную — окна стоят прямо на панели, без просвета.")
        gap_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        gap_rev.set_transition_duration(140)
        gap_rev.add(gbox)
        gap_rev.set_reveal_child(show != "hover")
        xcard.pack_start(gap_rev, False, False, 0)
        # Тексты песен — только в XP-панели (lyrics_bar.py on|off, флаг lyrics-off).
        lyr = os.path.join(HERE, "lyrics_bar.py")
        self.row(xcard, "Тексты песен",
                 self.pill(not os.path.exists(os.path.expanduser("~/.config/hypr/state/lyrics-off")),
                           lambda on: subprocess.run(["python3", lyr, "on" if on else "off"],
                                                     capture_output=True)),
                 "Пока играет песня (не видео), справа на панели идёт её текст строка за "
                 "строкой, с обложкой; спетое — акцентом. Тексты — с lrclib.net.")
        # Док: все окна или только окна текущего стола (dock.py mode).
        dcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.row(dcard, "Окна в доке",
                 self.segments([("all", "Все окна"), ("workspace", "Текущий стол")],
                               run("python3", DOCK, "mode"),
                               # не через run(): тот запоминает команды для заготовки при
                               # следующем запуске Настроек — и переключение повторилось бы
                               lambda k: subprocess.run(["python3", DOCK, "mode", k],
                                                        capture_output=True)),
                 "Док выезжает, если довести курсор до низа экрана по центру. "
                 "Текущий стол — значки окон только этого стола, все окна — все открытые.")
        for rev, box, on in ((xp_rev, xcard, kind == "xp"), (dock_rev, dcard, kind == "dock")):
            rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
            rev.set_transition_duration(140)
            rev.add(box)
            rev.set_reveal_child(on)
            c.pack_start(rev, False, False, 0)

    # Applications: Neovim, ЭЛТ в Zen, дашборд, карточки на столе
    def page_apps(self):
        scroll, v = self.page("Applications", "Программы: по умолчанию, kitty, Neovim, Obsidian, "
                                              "Zen, дашборд.")
        self.default_apps_card(v)
        self.kitty_cards(v)
        self.section(v, "Редактор", "\U000f05e7")
        c = self.card(v)
        self.row(c, "Neovim: курсор по центру",
                 self.pill(nvim_center_get(), nvim_center_set),
                 "Строка с курсором всегда посередине окна, текст прокручивается под ней. "
                 "Выкл — обычная прокрутка у края (запас 4 строки). "
                 "Открытые Neovim переключаются сразу.")
        self.row(c, "Neovim: тёмный фон",
                 self.pill(nvim_darkbg_get(), nvim_darkbg_set),
                 "Вкл — непрозрачный фон темнее обычного (surface_lowest палитры), текст "
                 "контрастнее. Выкл — прозрачный, сквозь него стекло kitty (как было). "
                 "Открытые Neovim переключаются сразу.")
        # ЭЛТ в Zen (30.09.2026): не шейдер, а CSS-слой поверх окна браузера
        # (chrome/crt.css). Переключается на лету через `zen-crt` — без перезапуска.
        self.section(v, "Браузер Zen", "\U000f059f")
        c = self.card(v)
        self.row(c, "ЭЛТ-монитор в Zen", self.pill(run("zen-crt", "status") == "on",
                                                  lambda on: run("zen-crt", "on" if on else "off")),
                 "Строки развёртки, маска люминофора, виньетка и тёмная кромка поверх "
                 "всего окна Zen — как ЭЛТ у kitty, но без выпуклости (в браузере её не "
                 "сделать). Включается и выключается сразу, без перезапуска браузера.")
        if NIRI:
            self.section(v, "Дашборд", "\U000f056e")
            c = self.card(v)
            self.row(c, "Дашборд при входе",
                     self.pill(dashboard_login_get(), dashboard_login_set),
                     "Восемь плавающих окон на экране ноутбука (часы, дата, таймер, фокус, "
                     "cava, матрица, brrt, ffetch) открываются сами при входе, в сохранённых "
                     "местах. Выкл — не открывать. Вручную: «dashboard restore» открыть, "
                     "«dashboard save» запомнить новую раскладку.")
        self.section(v, "Карточки на столе", "\U000f0639")
        c = self.card(v)
        self.row(c, "Окно памяти", self.place_combo(APPMEM_POPUP),
                 "Кто сколько ест: память, процессор и число процессов по приложениям, "
                 "живой счётчик. Открывается по SUPER+ALT+X, то же в терминале — «appmem».")
        self.obsidian_card(v)
        return scroll

    def page_screen(self):
        scroll, v = self.page("Visuals", "Яркость, тёплый свет по вечерам, размытие обоев, "
                                        "экраны входа и блокировки.")
        # Яркость и подсветка (01.10.2026): экран ноутбука — brightnessctl;
        # MSI — DDC (monitor_brightness.py, ~0,3 с на запрос); клавиатура
        # ноутбука — светодиод tuxedo rgb:kbd_backlight через brightnessctl (пишет
        # через logind, без sudo — так же, как kbdlight); Razer — openrazer
        # (razer_brightness.py). Медленное (DDC, openrazer) читается в фоне: строка
        # рисуется сразу по последнему известному значению и потом уточняется.
        self.section(v, "Яркость и подсветка", "\U000f00df")
        c = self.card(v)
        chip, sc = self.slider(5, 100, 5, brightness_get(),
                               lambda val: run("brightnessctl", "set", "%d%%" % val))
        self.row(c, "Яркость ноутбука", chip,
                 "Экран ноутбука.", below=sc)
        msi_chip, msi_sc = self.slider(0, 100, 5, last_number(MSI_LAST, 50),
                                       lambda val: run_serial(["python3", MON_BRIGHT, "set",
                                                               "%d" % val]))
        msi_row = self.row(c, "Яркость MSI", msi_chip,
                           "Внешний монитор MSI по DDC/CI — как кнопками на самом мониторе. "
                           "Не подключён — строки нет.", below=msi_sc)
        kbd = kbd_light_get()
        if kbd is not None:
            kchip, ksc = self.slider(0, 100, 5, kbd, kbd_light_set, suffix="%")
            self.row(c, "Подсветка клавиатуры ноутбука", kchip,
                     "Встроенная подсветка клавиш. Цвет следует за обоями (kbd_colors.py), "
                     "здесь — только яркость. 0 — погашена.", below=ksc)
        rz_chip, rz_sc = self.slider(0, 100, 5, last_number(RAZER_LAST, 100),
                                     lambda val: run_serial(["python3", RAZER_BRIGHT, "set",
                                                             "%d" % val]),
                                     suffix="%")
        rz_row = self.row(c, "Подсветка Razer", rz_chip,
                          "Яркость подсветки BlackWidow V3 (openrazer). Цвета — профиль "
                          "Polychromatic в гамме обоев, они не меняются.", below=rz_sc)
        rz_btn = self.row(c, "Настройки Razer", self.go_button("Открыть", lambda: subprocess.Popen(
            ["polychromatic-controller"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)),
                          "Polychromatic — эффекты, профили и устройства Razer.")
        # Пока не ответил фон — строк MSI и Razer нет, если про них ничего не
        # известно (нет файла последнего значения).
        for w, known in ((msi_row, os.path.exists(MSI_LAST)),
                         (rz_row, os.path.exists(RAZER_LAST)),
                         (rz_btn, os.path.exists(RAZER_LAST))):
            self.set_absent(w, not known)
        self.read_slow_brightness(msi_row, msi_sc, rz_row, rz_btn, rz_sc)

        night_on, self.warmth = night_state()
        self.section(v, "Тёплый свет", "\U000f0594")
        c = self.card(v)
        self.night_pill = self.pill(night_on, self.on_night)
        self.row(c, "Ночной режим", self.night_pill,
                 "По расписанию включается сам: с 22:00 до 5:00. Здесь — вручную.")
        # Теплота появляется только при включённом режиме: ползунок, который
        # ни на что не влияет, сбивает с толку.
        self.warm_rev = Gtk.Revealer()
        self.warm_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.warm_rev.set_transition_duration(140)
        wcard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        wchip, wsc = self.slider(0, 100, 5, self.warmth, self.on_warmth)
        self.row(wcard, "Теплота", wchip,
                 "0 — обычный свет, 100 — самый тёплый (2800 K).", below=wsc)
        self.warm_rev.add(wcard)
        self.warm_rev.set_reveal_child(night_on)
        c.pack_start(self.warm_rev, False, False, 0)

        # Размытие — по строке на монитор, каждый сам по себе. Работа идёт
        # отдельным процессом: первая картинка размывается ~2 с, и ожидание
        # заморозило бы окно настроек.
        self.section(v, "Размытие обоев", "\U000f00b5",
                     "Палитра считается по исходной картинке — цвета интерфейса не меняются.")
        c = self.card(v)
        for name, text, value in blur_outputs():
            self.row(c, "Размытие — %s" % text,
                     self.pill(value == "on",
                               lambda on, n=name: subprocess.Popen(
                                   ["python3", BLUR, "on" if on else "off", n],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)),
                     "Монитор показывает размытую копию обоев. Палитра считается по "
                     "исходной картинке, поэтому цвета интерфейса не меняются.",
                     default=False)                  # wallpaper_blur.py: нет записи — off
        try:
            blur_level = int(run("python3", BLUR, "level") or 2)
        except ValueError:
            blur_level = 2
        # Три ступени — сегментами, а не ползунком: у ступеней нет «между».
        self.row(c, "Сила размытия",
                 self.segments([("1", "лёгкое"), ("2", "среднее"), ("3", "сильное")],
                               str(blur_level),
                               lambda k: subprocess.Popen(["python3", BLUR, "level", k],
                                                          stdout=subprocess.DEVNULL,
                                                          stderr=subprocess.DEVNULL,
                                                          start_new_session=True)),
                 "Три ступени на оба монитора. Новая сила считается один раз на каждые "
                 "обои — первое применение занимает пару секунд.")

        # Пиксельные обои (03.10.2026): wallpaper_pixel.py get | on | off | level [1..3].
        # Чтение терпит отсутствие скрипта и его падение: пустой или чужой ответ —
        # «выключено» и средний размер. Запись — по очереди (run_serial): копия
        # обоев делается секунду-две, быстрые щелчки не должны идти наперегонки.
        self.section(v, "Пиксельные обои", "\U000f02c1",
                     "Обои показываются как пиксель-арт. Сами файлы не меняются, палитра "
                     "считается по исходной картинке.")
        c = self.card(v)
        self.row(c, "Пиксельные обои",
                 self.pill(run("python3", PIXEL, "get") == "on",
                           lambda on: run_serial(["python3", PIXEL, "on" if on else "off"])),
                 "Любые обои — пиксель-артом: мало цветов, квадратные пиксели. Файлы обоев "
                 "не трогаются, цвета интерфейса не меняются. Применение — секунда-две.",
                 icon="\U000f02c1")
        pixel_level = run("python3", PIXEL, "level")
        self.row(c, "Размер пикселя",
                 self.segments([("1", "мелкий"), ("2", "средний"), ("3", "крупный")],
                               pixel_level if pixel_level in ("1", "2", "3") else "2",
                               lambda k: run_serial(["python3", PIXEL, "level", k])),
                 "Три размера на все мониторы. Копия считается один раз на каждые обои и "
                 "размер — первое применение занимает секунду-две.",
                 icon="\U000f0570")

        # Экран входа (SDDM + sddm-astronaut-theme), 14.09.2026. Переключает
        # login_theme.py через помощника от root; установщик —
        # scripts/login_theme/install.sh.
        # Значки папок и файлов (02.10.2026): icon_theme.py get|set pixel|papirus.
        self.section(v, "Значки", "\U000f024b")
        c = self.card(v)
        it = os.path.join(HERE, "icon_theme.py")
        self.row(c, "Значки папок и файлов", self.segments(
            [("pixel", "Пиксельные"), ("papirus", "Papirus")],
            (lambda x: x if x in ("pixel", "papirus") else "papirus")(run("python3", it, "get")),
            lambda k: subprocess.run(["python3", it, "set", k], capture_output=True)),
                 "Набор значков в файловом менеджере и диалогах: пиксельные или Papirus.",
                 icon="\U000f024b")

        # Виджеты на обоях (02.10.2026): desktop_widgets.py on|off|status, edit — расстановка,
        # peek — показать поверх окон. Поиск: «виджет», «widget», «дашборд».
        dw = os.path.join(HERE, "desktop_widgets.py")
        if os.path.exists(dw):
            self.section(v, "Виджеты на обоях", "\U000f0e2b")
            c = self.card(v)

            def dw_run(*a):
                subprocess.Popen(["python3", dw, *a], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True)
            self.row(c, "Виджеты на обоях",
                     self.pill(run("python3", dw, "status") == "on",
                               lambda on: subprocess.run(["python3", dw, "on" if on else "off"],
                                                         capture_output=True)),
                     "Часы, погода, монитор ресурсов, плеер, осьминог и прочее поверх обоев. "
                     "Новый — ПКМ по обоям → «Создать виджет».",
                     icon="\U000f0e2b")
            # Вид и фон (02.10.2026): desktop_widgets.py style КЛЮЧ [ЗНАЧЕНИЕ]. Сторож сам
            # следит за файлом стиля — перерисовывает на лету, перезапуск не нужен.
            def dw_style(key, val):
                subprocess.run(["python3", dw, "style", key, str(val)], capture_output=True)

            def dw_num(key, default):
                try:
                    return int(run("python3", dw, "style", key))
                except ValueError:
                    return default
            # Вид виджетов по мониторам — в Config → «Стили окон» (03.10.2026).
            self.row(c, "Прозрачный фон виджетов",
                     self.pill(run("python3", dw, "style", "transparent") == "on",
                               lambda on: dw_style("transparent", "on" if on else "off")),
                     "Выкл — сплошной фон. Вкл — сквозь плашку видны обои; насколько — "
                     "«Плотность фона».",
                     icon="\U000f05b0")
            # Тень (03.10.2026): desktop_widgets.py style shadow → on|off, запись — 1|0.
            self.row(c, "Тень у виджетов",
                     self.pill(run("python3", dw, "style", "shadow") == "on",
                               lambda on: dw_style("shadow", 1 if on else 0)),
                     "Маленькая пиксельная тень справа и снизу у виджетов-окон XP.",
                     icon="\U000f0a4d")
            ochip, osc = self.slider(0, 100, 5, dw_num("opacity", 62), lambda v: dw_style("opacity", int(v)),
                                     suffix="%")
            self.row(c, "Плотность фона", ochip,
                     "100 — фон почти сплошной, 0 — обои видны как есть. Работает при прозрачном фоне.",
                     below=osc, icon="\U000f05b0")
            bchip, bsc = self.slider(0, 40, 2, dw_num("blur", 16), lambda v: dw_style("blur", int(v)))
            self.row(c, "Размытие под виджетом", bchip,
                     "Сила размытия обоев под плашкой; 0 — без размытия.",
                     below=bsc, icon="\U000f00b5")
            self.row(c, "Анимация под окнами",
                     self.pill(run("python3", dw, "style", "under") == "on",
                               lambda on: dw_style("under", "on" if on else "off")),
                     "Вкл — виджеты двигаются и под окнами. Выкл — закрытый окном виджет замирает "
                     "(меньше нагрузка).",
                     icon="\U000f040a")
            self.row(c, "Расстановка виджетов", self.go_button("Расставить", lambda: dw_run("edit")),
                     "Двигать, растягивать, убирать и добавлять виджеты мышью; Esc — готово.",
                     icon="\U000f01be")
            # Выключатель, а не кнопка: по кнопке «Показать / убрать» не было видно, включено
            # ли сейчас (02.10.2026). Состояние — desktop_widgets.py peek status.
            self.row(c, "Показать поверх окон",
                     self.pill(run("python3", dw, "peek", "status") == "on",
                               lambda on: subprocess.run(["python3", dw, "peek", "on" if on else "off"],
                                                         capture_output=True)),
                     "Вкл — виджеты всплывают над окнами, выкл — уходят обратно под окна.",
                     icon="\U000f0208")

        self.section(v, "Экран входа", "\U000f0342")
        c = self.card(v)
        if login_theme.installed():
            self.row(c, "Тема экрана входа",
                     hint="Щелчок выбирает сразу, видно при следующем входе. «Как рабочий "
                          "стол» — ваши обои и цвета, обновляется сам при смене обоев. "
                          "«Как было» — прежний экран входа SDDM.",
                     below=self.tiles(login_theme.variants(), login_theme.current(),
                                      self.draw_login_look,
                                      lambda k: subprocess.Popen(
                                          ["python3", LOGIN_THEME, "set", k],
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                          start_new_session=True),
                                      per_row=4, height=64))
            try_btn = self.go_button("Показать", lambda: subprocess.Popen(
                ["python3", LOGIN_THEME, "try"], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, start_new_session=True))
            self.row(c, "Предпросмотр", try_btn,
                     "Открывает выбранный экран входа в тестовом режиме SDDM поверх "
                     "рабочего стола — окна не закрываются. Закроется сам через 30 секунд.")
        else:
            self.row(c, "Тема экрана входа",
                     hint="Тема sddm-astronaut ещё не установлена. Один раз в терминале: "
                          "sudo bash ~/.config/hypr/scripts/login_theme/install.sh")

        # Экран блокировки (hyprlock), 14.09.2026. «Как сейчас» — нынешний
        # hyprlock.conf, выбран по умолчанию; стиль читает scripts/lockscreen.
        self.section(v, "Экран блокировки", "\U000f033e")
        c = self.card(v)
        self.row(c, "Стиль экрана блокировки",
                 hint="Для SUPER+L, блокировки по простою и перед сном. «Как сейчас» — "
                      "размытый рабочий стол и аватар. Остальные — вид вариантов экрана "
                      "входа. У всех наши детали и цвета обоев; у Hyprland фоном кадр. "
                      "Щелчок выбирает сразу, проверить — SUPER+L.",
                 below=self.tiles([tuple(l.split("\t", 1)) for l in
                                   run("python3", LOCK_STYLE, "list").splitlines() if "\t" in l],
                                  run("python3", LOCK_STYLE, "get"),
                                  self.draw_lock_look,
                                  lambda k: run("python3", LOCK_STYLE, "set", k),
                                  per_row=4, height=64))
        # Свой экран блокировки (jarvis_lock.py, 30.09.2026) — кнопки питания с
        # обводкой при наведении. Выкл — hyprlock, как раньше; упал — hyprlock.
        engine_file = os.path.expanduser("~/.config/hypr/state/lock-engine")

        def engine_set(on):
            if on:
                with open(engine_file, "w") as f:
                    f.write("jarvis\n")
            elif os.path.exists(engine_file):
                os.remove(engine_file)
        try:
            engine_on = open(engine_file).read().strip() == "jarvis"
        except OSError:
            engine_on = False
        self.row(c, "Экран блокировки — свой (с обводкой кнопок)", self.pill(engine_on, engine_set),
                 "Свой экран: кнопки питания подсвечиваются под указателем. Пароль — тот же "
                 "PAM, что у hyprlock. Не запустился или упал — сразу hyprlock. Стили выше "
                 "относятся к hyprlock. Выкл — hyprlock, как раньше.")
        return scroll

    def read_slow_brightness(self, msi_row, msi_sc, rz_row, rz_btn, rz_sc):
        """Спросить MSI (DDC) и Razer (openrazer) в отдельном потоке и уточнить
        строки: значение — без записи обратно, нет устройства — строку спрятать."""
        import threading

        def ask(cmd, timeout):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
                return r.returncode, r.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                return 1, ""

        page_key = self._building

        def apply(row, sc, value, extra=()):
            if row.get_parent() is None:        # страницу уже снесли (сменили вид) —
                return False                    # ползунка нет, GTK ругался бы в журнал
            moved = False
            for w in (row,) + tuple(extra):
                was = w.get_visible()
                self.set_absent(w, value is None)
                w.set_visible(value is not None and self.row_matches(w))
                moved = moved or was != w.get_visible()
            if value is not None:
                sc.set_quiet(value)
            if moved:                           # skeet: группа стала выше или ниже
                self.skeet_balance(page_key)
            return False

        def work():
            rc, _ = ask(["python3", MON_BRIGHT, "present"], 5)
            val = None
            if rc == 0:
                rc, out = ask(["python3", MON_BRIGHT, "get"], 10)
                val = int(out) if rc == 0 and out.isdigit() else None
            GLib.idle_add(apply, msi_row, msi_sc, val)
            rc, out = ask(["python3", RAZER_BRIGHT, "get"], 10)
            val = int(out) if rc == 0 and out.isdigit() else None
            GLib.idle_add(apply, rz_row, rz_sc, val, (rz_btn,))
        threading.Thread(target=work, daemon=True).start()

    @staticmethod
    def set_absent(wrap, absent):
        """Строка устройства, которого нет: спрятана и не показывается ни
        show_all(), ни поиском (apply_filter смотрит на .absent)."""
        was = getattr(wrap, "absent", False)
        wrap.absent = absent
        wrap.set_no_show_all(absent)
        if absent:
            wrap.hide()
        elif was:
            wrap.show_all()          # содержимое строки show_all() пропускал

    def row_matches(self, wrap):
        """Совпадает ли строка с текущим поиском (без поиска — да)."""
        if not self.query:
            return True
        text = next((t for _p, w, t in self._rows if w is wrap), "")
        return search_hit(text, search_variants(self.query))

    def on_night(self, on):
        self.warm_rev.set_reveal_child(on)
        night_set(on, self.warmth)

    def on_warmth(self, val):
        self.warmth = val
        if self.night_pill.get_active():
            night_set(True, val)

    def page_cursor(self):
        """Выбор курсора (28.09.2026): Jarvis в цветах обоев, «галька» в четырёх цветах, Breeze."""
        scroll, v = self.page("Cursors", "Щелчок по плитке меняет курсор сразу, везде.")
        spec = importlib.util.spec_from_file_location("cursor_theme", CURSOR_THEME)
        ct = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ct)
        self._cursor_theme = ct
        self.section(v, "Тема курсора", "\U000f01bf")
        c = self.card(v)
        self.row(c, "Какой курсор", hint="Jarvis перекрашивается под обои сам. Галька и Breeze "
                 "держат свой цвет при любых обоях.",
                 below=self.tiles([(k, label) for k, label, _ in ct.THEMES], ct.current(),
                                  self.draw_cursor_look,
                                  lambda k: subprocess.Popen(
                                      ["python3", CURSOR_THEME, "set", k],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                      start_new_session=True),
                                  per_row=4, height=44))
        return scroll

    def draw_cursor_look(self, cr, w, h, key, pal):
        """Плитка темы курсора: стрелка, рука, текст и ожидание из самих файлов темы."""
        cache = self.__dict__.setdefault("_cursor_pix", {})
        if key not in cache:
            base = self._cursor_theme.theme_dir(key)
            cache[key] = [cursor_pixbuf(base / "cursors" / n) if base else None
                          for n in ("left_ptr", "hand2", "xterm", "watch")]
        c = pal.get("surface_container", "#1e1f29").lstrip("#")
        cr.set_source_rgb(*(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)))
        cr.rectangle(0, 0, w, h)
        cr.fill()
        pixs = [p for p in cache[key] if p is not None]
        step = w / (len(pixs) + 1) if pixs else w
        for i, pix in enumerate(pixs):
            x = step * (i + 1) - pix.get_width() / 2
            Gdk.cairo_set_source_pixbuf(cr, pix, x, (h - pix.get_height()) / 2)
            cr.paint()

    # Terminal: шейдеры kitty (бывший раздел «Шейдеры»; ЭЛТ в Zen — в Misc → Приложения)
    def kitty_cards(self, v):
        """Шейдеры kitty (была страница Terminal)."""
        self.section(v, "Шейдеры kitty", "\U000f0e30")
        c = self.card(v)
        self.row(c, "Эффект экрана", self.shader_combo("screen"),
                 "Поверх всего окна kitty. «ЭЛТ-монитор 90-х» — слегка выпуклое стекло, "
                 "строки развёртки, маска люминофора и тёмная рамка. Выпуклость "
                 "подобрана так, чтобы текст у краёв оставался читаемым.")
        self.row(c, "След курсора", self.shader_combo("cursor"),
                 "След текстового курсора — виден при наборе. Цвет берётся из акцента "
                 "обоев и меняется вместе с ними.")
        self.row(c, "Отдача и молнии", self.shader_combo("typing"),
                 "Печать. Отдача — экран вздрагивает; молнии — разряды бьют от курсора. Оба "
                 "эффекта включаются ТОЛЬКО на быстром наборе и сами гаснут на "
                 "спокойном, поэтому в обычной работе экран стоит смирно. Стирание "
                 "не трясёт. В тренажёре jtype при беглой печати горят почти всегда.")

    def power_cards(self, v):
        """Питание (была страница Power; с 02.10.2026 — в Misc)."""
        self.section(v, "Питание", "\U000f0079")
        c = self.card(v)
        self.row(c, "Энергосбережение",
                 self.pill(run("powerprofilesctl", "get") == "power-saver",
                           lambda on: run("powerprofilesctl", "set",
                                          "power-saver" if on else "balanced")),
                 "Процессор работает тише и медленнее — батареи хватает дольше.")
        # Что открывает кнопка питания в баре (01.10.2026): power_view.py get|set.
        pv = os.path.join(HERE, "power_view.py")
        self.row(c, "Меню питания (кнопка в баре)", self.segments(
            [("wlogout", "wlogout"), ("jarvis", "Свой")],
            (lambda v: v if v in ("wlogout", "jarvis") else "wlogout")(run("python3", pv, "get")),
            lambda k: subprocess.run(["python3", pv, "set", k], capture_output=True)),
                 "wlogout — прежнее меню на весь экран. Свой — собственное меню питания.",
                 icon="\U000f0425")

        savage = savage_get()
        self.savage_pill = self.pill(savage, self.on_savage)
        self.row(c, "Savage Mode", self.savage_pill,
                 "Ноутбук не засыпает — для работы 24/7 на зарядке. "
                 "Экран при этом всё равно гаснет и блокируется.")
        self.awake_rev = Gtk.Revealer()
        self.awake_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.awake_rev.set_transition_duration(140)
        acard = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.awake_pill = self.pill(run("python3", SCREEN_AWAKE, "get") == "on",
                                    lambda on: run("python3", SCREEN_AWAKE,
                                                   "on" if on else "off"))
        self.row(acard, "Не отключать экран", self.awake_pill,
                 "Работает только вместе с Savage Mode: экран не гаснет и не "
                 "блокируется. Выключение Savage Mode сбрасывает и это.")
        self.awake_rev.add(acard)
        self.awake_rev.set_reveal_child(savage)
        c.pack_start(self.awake_rev, False, False, 0)

    def on_savage(self, on):
        if on != savage_get():
            run("python3", SAVAGE, "--toggle")
        if not on:
            self.awake_pill.set_active(False)
        self.awake_rev.set_reveal_child(on)

    def notify_cards(self, v):
        """Уведомления (была страница Notifications; с 02.10.2026 — в Misc)."""
        # Звук и микрофон (04.10.2026, просьба: «отдельно настройки звука/микрофона; понравилась
        # фича — нажать кнопку и услышать себя; и чтобы сверху была иконка, что микрофон
        # используется»). mic_monitor.py; значок «микрофон занят» в баре даёт privacy_status.
        mm = os.path.join(HERE, "mic_monitor.py")
        if os.path.exists(mm):
            self.section(v, "Звук и микрофон", "\U000f036c")
            c = self.card(v)
            self.row(c, "Микрофон", self.pill(run("python3", mm, "mute") != "on",
                                             lambda on: run_serial(["python3", mm, "mute", "off" if on else "on"])),
                     "Выключить или включить микрофон (то же — щелчок по значку микрофона в "
                     "нижней панели).", icon="\U000f036c")
            try:
                mv = int(run("python3", mm, "volume"))
            except ValueError:
                mv = 100
            chip, sc = self.slider(0, 150, 5, mv,
                                   lambda val: run_serial(["python3", mm, "volume", str(int(val))]),
                                   suffix="%")
            self.row(c, "Чувствительность", chip,
                     "Громкость микрофона. Больше 100 % — усиление, может появиться шум.",
                     below=sc, icon="\U000f0e3a")
            self.row(c, "Послушать себя", self.pill(run("python3", mm, "status") == "on",
                                                   lambda on: run_serial(["python3", mm, "on" if on else "off"])),
                     "Микрофон слышно в наушниках — понять, как вас слышат. Сверху загорается "
                     "значок «микрофон используется». Само выключится через 5 минут.",
                     icon="\U000f02cb")
            self.row(c, "Микшер", self.go_button("Открыть", lambda: subprocess.Popen(
                ["pavucontrol", "-t", "4"], start_new_session=True)),
                     "Устройства ввода и вывода, громкость программ.", icon="\U000f0d52")
        self.section(v, "Уведомления", "\U000f009c")
        c = self.card(v)

        def dnd(on):
            if on != (run("swaync-client", "--get-dnd") == "true"):
                run("swaync-client", "--toggle-dnd")
        self.row(c, "Не беспокоить",
                 self.pill(run("swaync-client", "--get-dnd") == "true", dnd),
                 "Уведомления копятся в центре уведомлений, но не всплывают.")
        # Смена трека (30.09.2026, по образцу Noctalia): track_notify.py.
        tn = os.path.join(os.path.dirname(os.path.abspath(__file__)), "track_notify.py")
        self.row(c, "Уведомление при смене трека",
                 self.pill(run("python3", tn, "status") == "on",
                           lambda on: subprocess.run(["python3", tn, "on" if on else "off"],
                                                     capture_output=True)),
                 "Когда играющая музыка или видео переключается на новый трек — "
                 "короткое уведомление с обложкой, названием и исполнителем.")
        # Вид карточек как в Noctalia (30.09.2026): глухой тёмный фон, тонкая
        # рамка, картинка квадратом. Переключает ~/.local/bin/notif-look.
        self.row(c, "Вид как в Noctalia",
                 self.pill(run("notif-look", "status") == "on",
                           lambda on: run("notif-look", "on" if on else "off")),
                 "Тёмные карточки с тонкой рамкой, уже — 420 px вместо 500.")
        # Звуки интерфейса (02.10.2026): ui_sound.py status|on|off. Нет скрипта —
        # выключатель погашен.
        us = os.path.join(HERE, "ui_sound.py")
        have = os.path.exists(us)
        # Громкость звука уведомления (04.10.2026): свой звук «пришло
        # уведомление» из Звуков интерфейса — доля от их громкости. Звуки самих
        # программ (Telegram) здесь не регулируются. Сдвиг — сразу проба.
        if have:
            def notify_vol(val):
                subprocess.run(["python3", us, "notify-volume", "%d" % val], capture_output=True)
                subprocess.Popen(["python3", us, "test", "notify"], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
            try:
                nvol = int(run("python3", us, "notify-volume"))
            except ValueError:
                nvol = 100
            chip, sc = self.slider(0, 100, 5, nvol, notify_vol, suffix="%")
            self.row(c, "Громкость уведомлений", chip,
                     "Своя громкость звука «пришло уведомление» — не зависит от громкости звуков интерфейса. "
                     "Звуки самих программ (Telegram) — в их настройках.",
                     below=sc, icon="\U000f009a")
        # Своя группа (04.10.2026, просьба: «набор звуков и уведомления — отдели»)
        self.section(v, "Звуки интерфейса", "\U000f057e")
        c = self.card(v)
        sp = self.pill(have and run("python3", us, "status") == "on",
                       lambda on: subprocess.run(["python3", us, "on" if on else "off"],
                                                 capture_output=True))
        sp.set_sensitive(have)
        self.row(c, "Звуки интерфейса", sp,
                 "Короткие звуки на действия оболочки." + ("" if have else " Скрипт ui_sound.py "
                                                           "ещё не установлен."),
                 icon="\U000f057e")
        if have:
            # Своя громкость и набор (02.10.2026): «отдельно от основного микшера»,
            # «звуки в стиле old tech / retro». Щелчок по набору и сдвиг ползунка
            # сразу проигрывают пробу (ui_sound.py test — в обход «выкл» и DND).
            def us_run(*a):
                subprocess.Popen(["python3", us, *a], stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)

            def us_pack(key):
                subprocess.run(["python3", us, "pack", key], capture_output=True)
                us_run("test", "done")

            def us_vol(val):
                subprocess.run(["python3", us, "volume", "%d" % val], capture_output=True)
                us_run("test", "done")
            self.row(c, "Набор звуков",
                     self.segments([("xp", "Windows XP"), ("retro", "Ретро"), ("classic", "Обычный")],
                                   run("python3", us, "pack") or "xp", us_pack),
                     "Windows XP — настоящие звуки XP; ретро — синтез в духе старого железа; "
                     "обычный — штатные звуки системы.",
                     icon="\U000f075a")
            try:
                uvol = int(run("python3", us, "volume"))
            except ValueError:
                uvol = 75
            chip, sc = self.slider(0, 100, 5, uvol, us_vol, suffix="%")
            self.row(c, "Громкость звуков", chip,
                     "Своя громкость звуков интерфейса — доля от общей громкости системы.",
                     below=sc, icon="\U000f057e")
            # Группы событий (02.10.2026): каждая выключается отдельно — ui_sound.py cat.
            # Включение группы сразу играет её образец.
            samples = {"system": "unlock", "capture": "screenshot", "devices": "usb-in",
                       "menu": "menu", "timer": "timer", "notify": "notify",
                       "windows": "window-open", "mouse": "nav"}
            for line in run("python3", us, "cat").splitlines():
                parts = line.split("\t")
                if len(parts) != 3:
                    continue
                key, title, state = parts

                def cat_set(on, k=key):
                    subprocess.run(["python3", us, "cat", k, "on" if on else "off"], capture_output=True)
                    if on:
                        us_run("test", samples.get(k, "done"))
                self.row(c, "Звук: " + title, self.pill(state == "on", cat_set),
                         "Группа звуков интерфейса: " + title.lower() + ".", icon="\U000f057e",
                         default=UI_SOUND_GROUP_DEFAULTS.get(key, _NODEF))

    def shots_cards(self, v):
        """Редактор снимков экрана (была отдельная страница)."""
        self.section(v, "Снимки", "\U000f0e51")
        c = self.card(v)
        cur = shot_get()
        # Выбор одного из двух — сегментами; чем хорош каждый — подсказкой у его
        # кнопки (раньше — текстом под строкой, убран 01.10.2026).
        self.editor_seg = self.segments([(k, t) for k, t, _h in EDITORS], cur, self.pick_editor)
        for btn, (_k, _t, h) in zip(self.editor_seg.get_children(), EDITORS):
            btn.set_tooltip_text(h)
        self.row(c, "Редактор", self.editor_seg,
                 " ".join("%s — %s" % (t, h) for _k, t, h in EDITORS))

    def page_fonts(self):
        scroll, v = self.page("Fonts", "Список — шрифты с кириллицей, что стоят в системе. Не понравится — верните здесь же.")
        self.section(v, "Система", "\U000f06d6")
        c = self.card(v)
        self.row(c, "Шрифт системы", self.font_combo("system"),
                 "Бар, попапы, лаунчер, экран блокировки, Настройки и программы. Бар "
                 "перезапускается сразу, открытые программы — после перезапуска. "
                 "Значки остаются на месте.")
        self.section(v, "Приложения", "\U000f0614")
        c = self.card(v)
        self.row(c, "Obsidian", self.font_combo("obsidian"),
                 "Заметки и интерфейс темы Jarvis, меняется сразу. «Как в Obsidian» — "
                 "шрифт по умолчанию. Если шрифт выбран в Style Settings, тот главнее.")
        self.row(c, "Терминал kitty", self.font_combo("kitty"),
                 "Шрифт новых окон. «Как было» — Noto Sans Mono: им терминал "
                 "рисовал до Hack. Список — все моноширинные шрифты с кириллицей, "
                 "что стоят в системе.")
        self.row(c, "Менять и в открытых окнах", self.pill(
            run("python3", APP_FONTS, "scope") == "all", self.set_kitty_scope),
                 "Выключено — открытые терминалы остаются как есть, шрифт меняется "
                 "только в новых. Включено — все окна перечитывают конфиг сразу: "
                 "размер шрифта сохраняется, но ширина клетки у другого шрифта своя, "
                 "и подогнанные руками размеры окон съезжают.")
        self.row(c, "LibreWolf: навязывать шрифт сайтам", self.pill(
            run("python3", APP_FONTS, "lwfonts") == "on", self.set_lw_fonts),
                 "То же, что у Zen, только через его собственный overrides.cfg — он "
                 "действует на все профили сразу. Включено — сайты рисуются шрифтом "
                 "системы; выключено — своим. Применяется при следующем запуске браузера.")
        self.row(c, "Helium: навязывать шрифт сайтам", self.pill(
            run("python3", APP_FONTS, "hefonts") == "on", self.set_he_fonts),
                 "В Chromium настройки шрифтов действуют только на страницы без своих "
                 "шрифтов, поэтому здесь работает маленькое расширение (оно всегда "
                 "подключено, а выключенный переключатель просто очищает его стиль). "
                 "Семейства с «icon» в имени не трогаются — иначе вместо значков буквы. "
                 "Применяется при следующем запуске браузера.")
        self.row(c, "Zen: навязывать шрифт сайтам", self.pill(
            run("python3", APP_FONTS, "zenfonts") == "on", self.set_zen_fonts),
                 "Выключено — сайты со своим шрифтом (чат YouTube и прочие рамки) "
                 "рисуют им же. Включено — ваш шрифт встаёт везде, но сайты, у "
                 "которых значки нарисованы шрифтом, покажут вместо них буквы. "
                 "Действует после перезапуска Zen.")
        self.section(v, "Проба", "\U000f018d")
        c = self.card(v)
        self.row(c, "Терминал на Super+`", self.font_combo("termalt"),
                 "Отдельное окно этим шрифтом. Шрифт уходит kitty аргументом — "
                 "ни конфиг, ни открытые терминалы не трогаются. Посмотреть, "
                 "не меняя ничего в системе.")
        return scroll

    def place_combo(self, script):
        """Выбор места карточки на столе — кнопка с меню, как у выбора шрифта.

        Скрипт карточки сам отвечает за своё состояние: «place» без слов —
        прочитать, «place list» — варианты, «place ЗНАЧЕНИЕ» — записать.
        """
        current = run("python3", script, "place")
        btn, label, menu = self.menu_button(190)
        label.set_text(current)
        state = {"cur": current}
        titles = {}

        def apply(key):
            subprocess.run(["python3", script, "place", key],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def show(key):                   # подпись на кнопке, без записи
            state["cur"] = key
            label.set_text(titles.get(key, key))

        def pick(_item, key, _title):
            show(key)
            self.fire(apply, key)

        words = []
        for line in run("python3", script, "place", "list").splitlines():
            key, _, title = line.partition("\t")
            titles[key] = title
            if key == current:
                label.set_text(title)
            item = Gtk.MenuItem(label=title)
            item.connect("activate", pick, key, title)
            menu.append(item)
            words.append(title)
        menu.show_all()
        btn.search_words = " ".join(words)
        if titles:                       # без списка мест сбрасывать нечем
            btn.rs = dict(get=lambda: state["cur"], put=show, cb=apply)
        return btn

    def shader_combo(self, slot):
        """Выбор шейдера kitty для одного слота — сегменты (до 4 вариантов) или меню.

        Слотов два, и они независимы: «screen» — эффект всего окна, «cursor» —
        след текстового курсора. kitty_shader.py собирает из обоих одну строку
        custom_shaders. «Выключен» — первый пункт.
        """
        current = run("python3", KITTY_SHADER, "get", slot)
        items = [("off", "Выключен")]
        for line in run("python3", KITTY_SHADER, "list", slot).splitlines():
            key, _, title = line.partition("\t")
            if key:
                items.append((key, title))

        def apply(key):
            subprocess.run(["python3", KITTY_SHADER, "set", slot, key],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        # До четырёх вариантов — сегментами (30.09.2026), больше — меню.
        if len(items) <= 4:
            keys = [k for k, _t in items]
            return self.segments(items, current if current in keys else "off", apply)

        btn, label, menu = self.menu_button(200)
        label.set_text("Выключен")
        titles = dict(items)
        state = {"cur": current if current in titles else "off"}

        def show(key):                   # подпись на кнопке, без записи
            state["cur"] = key
            label.set_text(titles.get(key, key))

        def pick(_item, key, _title):
            show(key)
            self.fire(apply, key)

        for key, title in items:
            if key == current:
                label.set_text(title)
            item = Gtk.MenuItem(label=title)
            item.connect("activate", pick, key, title)
            menu.append(item)
        menu.show_all()
        btn.search_words = " ".join(t for _k, t in items)
        btn.rs = dict(get=lambda: state["cur"], put=show, cb=apply)
        return btn

    def go_button(self, title, cb):
        btn = Gtk.Button(label=title)
        btn.get_style_context().add_class("fontpick")
        btn.connect("clicked", lambda _b: self.fire(cb))
        return btn

    def set_lw_fonts(self, active):
        subprocess.Popen(["python3", APP_FONTS, "lwfonts", "on" if active else "off"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def set_he_fonts(self, active):
        subprocess.Popen(["python3", APP_FONTS, "hefonts", "on" if active else "off"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def set_zen_fonts(self, active):
        subprocess.Popen(["python3", APP_FONTS, "zenfonts", "on" if active else "off"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def set_kitty_scope(self, active):
        subprocess.Popen(["python3", APP_FONTS, "scope", "all" if active else "new"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def font_combo(self, app):
        """Выбор шрифта для app_fonts.py (system, obsidian, kitty, termalt).

        Кнопка с меню, а не Gtk.ComboBoxText (23.09.2026). Комбобокс раскрывает
        меню так, чтобы ВЫБРАННЫЙ пункт лёг на кнопку: при выбранном
        предпоследнем из двадцати весь список уезжает вверх, а под ним висит
        пустой хвост высотой в экран. Режим «списком» под Wayland не
        открывается вовсе. MenuButton раскрывает меню просто под кнопкой —
        ровно по числу пунктов, без хвоста.
        """
        current = run("python3", APP_FONTS, "get", app)
        btn, label, menu = self.menu_button(240)
        label.set_text(current)

        def pick(_item, key, title):
            label.set_text(title)
            subprocess.Popen(["python3", APP_FONTS, "set", app, key],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)

        for line in run("python3", APP_FONTS, "list", app).splitlines():
            key, _, title = line.partition("\t")
            if key == current:
                label.set_text(title)
            item = Gtk.MenuItem(label=title)
            item.connect("activate", pick, key, title)
            menu.append(item)
        menu.show_all()
        return btn

    def pick_editor(self, key):
        shot_set(key)
        self.editor_seg.select(key)


class App(Gtk.Application):
    def __init__(self):
        # Проверки (рендер вне экрана, тесты) ставят JARVIS_SETTINGS_TEST=1: свой
        # id и без единственности — иначе живой тестовый процесс перехватывал бы
        # настоящий запуск по Super+/ и окно не появлялось (01.10.2026).
        super().__init__(application_id=APP_ID + (".test" if TEST else ""),
                         flags=Gio.ApplicationFlags.NON_UNIQUE if TEST
                         else Gio.ApplicationFlags.FLAGS_NONE)
        self.win = None
        self._sock = None
        self._watch = 0
        self._stamp = None

    def do_startup(self):
        Gtk.Application.do_startup(self)
        self.listen()

    def do_shutdown(self):
        if self._sock is not None:
            # Сначала снять сторожа: закрытый номер дескриптора тут же достаётся
            # другому файлу, и сторож срабатывал бы уже на чужие данные.
            GLib.source_remove(self._watch)
            try:
                self._sock.close()
                os.unlink(SOCK_PATH)
            except OSError:
                pass
            self._sock = None
        Gtk.Application.do_shutdown(self)

    # Сокет быстрого показа: слушает только главный экземпляр (do_startup у
    # второго не зовётся — Gtk.Application передаёт запуск первому и выходит).
    # Файл сокета от прежнего процесса, который уже не отвечает (ask_resident
    # пробовал), снимается. Ждёт главный цикл — опроса и таймеров нет.
    def listen(self):
        import socket
        try:
            if os.path.lexists(SOCK_PATH):
                os.unlink(SOCK_PATH)
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.bind(SOCK_PATH)
            sock.listen(4)
        except OSError:
            return
        self._sock = sock
        self._watch = GLib.io_add_watch(sock.fileno(), GLib.PRIORITY_DEFAULT, GLib.IO_IN,
                                        self.on_client)

    def on_client(self, _fd, _cond):
        if self._sock is None:
            return False
        try:
            conn, _addr = self._sock.accept()
        except OSError:
            return True
        try:
            conn.settimeout(0.3)
            data = conn.recv(4096).decode("utf-8", "replace")
            conn.sendall(b"ok\n")
        except OSError:
            data = None
        finally:
            conn.close()
        if data is not None:
            self.open_request([a for a in data.rstrip("\n").split("\x1f") if a])
        return True

    def open_request(self, argv):
        """Повторный запуск «settings_app.py …» дошёл по сокету."""
        if "--quit" in argv:
            self.quit()
        elif self.win is not None and "--hidden" not in argv:    # --hidden: уже греемся
            page, opts = parse_args(argv)
            self.show_window(page, opts.get("skin"), opts.get("mode"), argv)

    def show_window(self, page=None, skin=None, mode=None, argv=()):
        w = self.win
        if w.get_visible():
            # Окно на экране — поднять; страницу и вид менять, только если просили.
            if skin or mode:
                w.set_view(*w.view_arg(skin, mode))
            if page:
                w.select_page(resolve_page(page))
            w.present()
            return
        if __name__ == "__main__" and self._stamp != look_stamp():
            # Пока окно было спрятано, поменялся код или цвета обоев: этот процесс
            # устарел. Тот же pid запускается с нуля — один раз откроется медленнее.
            os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + list(argv))
        w.revive(page, skin, mode)

    def on_close(self, win, _ev):
        """Крестик, Mod+Q. Резидент включён — окно прячется, процесс остаётся;
        выключен — как раньше: окно уничтожается, приложение выходит."""
        if not resident_on():
            return False
        try:
            win.park()
        except Exception:                # не спряталось — закрыть по-настоящему
            return False
        return True

    def do_activate(self):
        if self.win is not None:         # второй запуск мимо сокета (через D-Bus)
            self.show_window()
            return
        # settings_app.py [страница] [--skin=default|skeet|beta] [--mode=light|dark]
        # (прежние normal и xp тоже понимаются). Вид и режим из аргументов
        # запоминаются; без них — как сохранено. --hidden — построить и не
        # показывать (автозапуск резидента); при выключенном резиденте — выйти.
        argv = sys.argv[1:]
        hidden = "--hidden" in argv
        if hidden and not resident_on():
            return
        page, opts = parse_args(argv)
        self._stamp = look_stamp()
        rnd = prefetch_start(resolve_page(page))
        self.win = SettingsWindow(self, page, skin=opts.get("skin"), mode=opts.get("mode"))
        self.win.connect("delete-event", self.on_close)
        if hidden:
            GLib.idle_add(self.win.build_bg, rnd, priority=GLib.PRIORITY_LOW)
            return
        # Остальные разделы — когда окно уже на экране (после первого кадра).
        self.win.after_frame(self.win.build_bg, rnd)
        self.win.appear()


if __name__ == "__main__":
    # Свой аргумент (раздел) до Gtk.Application не доводим: с FLAGS_NONE она
    # считает лишние слова именами файлов и ругается «can not open files»,
    # а окно открывается на первом разделе. Раздел читается из sys.argv сам.
    sys.exit(App().run(sys.argv[:1]))
