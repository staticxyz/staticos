#!/usr/bin/env python3
"""Лаунчер приложений Super+X — меню как у Omarchy в рамке Recorder.exe. 13.10.2026.

Карточка по центру экрана, разделы по важности (staticOS всегда первым), внутри —
программы. Вид — по стилю системы (Default/Skeet/Beta, exe_frame.py), за меню —
лёгкое затемнение без размытия.

Клавиши: j/k ↑↓ — выбор, l/Enter/→ — открыть, h/Esc/← — назад, g/G — края,
/ или Ctrl+E — поиск (smart_search: синонимы, раскладка, опечатки), jj — из поиска
к списку, q/Esc на верхнем уровне/Ctrl+Q/Super+X — закрыть.
Мышь: наведение выбирает, щелчок открывает, правая кнопка — назад, колесо,
щелчок по заголовку — назад, крестик или щелчок мимо карточки — закрыть.

    app_launcher.py --check                         разделы и проверка поиска
    app_launcher.py --shot ФАЙЛ [style=skeet] [cat=N] [sel=N] [q=ЗАПРОС]
"""
import os
import re
import sys
import shlex
import shutil
import subprocess

sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, GtkLayerShell, Pango, PangoCairo
import cairo

NAMESPACE = "jarvis-launcher"
ICON = 32                  # значки в строках; было 24 (13.10.2026)


KEYS = {}
for _row, _start in (("1234567890-=", 10), ("qwertyuiop[]", 24), ("asdfghjkl;'", 38),
                     ("zxcvbnm,./", 52)):
    for _i, _ch in enumerate(_row):
        KEYS[_start + _i] = _ch
KEYS[65] = " "

STATE_DIR = os.path.expanduser("~/.config/hypr/state")

# ── палитра (тот же код, что в Hub) ──────────────────────────────────────────

def hexrgb(h, d=(0.5, 0.6, 1.0)):
    try:
        h = h.strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return d

def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))

def read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return ""

MATUGEN = os.path.expanduser("~/.cache/matugen")

def palette():
    try:
        sys.path.insert(0, os.path.expanduser("~/.config/niri/scripts"))
        import xpbar_colors
        xc = xpbar_colors.colors()
    except Exception:
        xc = {}
    p = {}
    for k, d in (("primary", "#b4c5ff"), ("secondary", "#c5c2ea"), ("tertiary", "#d2bdf6"),
                 ("on_surface", "#e1e1ef"), ("on_surface_variant", "#c4c6d3"),
                 ("surface", "#10131c"), ("surface_container", "#1d1f29"),
                 ("surface_high", "#272a34"), ("on_primary", "#002979"), ("error", "#ffb4ab"),
                 ("st_hi", "#9fb4f5"), ("st_mid", "#5f74b4"), ("st_bot", "#465a94"),
                 ("st_dark", "#0a0c12")):
        p[k] = hexrgb(xc.get(k) or d, hexrgb(d))
    p["vivid"] = hexrgb(read(os.path.join(MATUGEN, "vivid.txt")), p["primary"])
    return p

def style_name():
    s = read(os.path.join(STATE_DIR, "settings-skin")).lower()
    return s if s in ("skeet", "beta") else "default"

def colors(style):
    p = palette()
    white, black = (1.0, 1.0, 1.0), (0.0, 0.0, 0.0)
    if style == "skeet":
        acc = p["vivid"]
        def g(level, t=0.05):
            return mix((level / 255,) * 3, acc, t)
        return dict(frame="skeet", acc=acc, acc_l=mix(acc, white, 0.22), acc_d=mix(acc, black, 0.40),
                    bg=g(0x13), field=g(0x1b), field_l=g(0x24), sel=g(0x1e),
                    line=g(0x30, 0.08), line_soft=g(0x22, 0.06), gdark=g(0x0e, 0.03),
                    line3=g(0x0a, 0.03),
                    text=mix(hexrgb("#cdcdcd"), p["on_surface"], 0.35), dim=g(0x92, 0.10),
                    faint=g(0x50, 0.10), err=p["error"])
    bg, cont = p["surface"], p["surface_container"]
    acc = p["primary"]
    return dict(frame="round", acc=acc, acc_l=mix(acc, white, 0.15), acc_d=mix(acc, bg, 0.50),
                bg=bg, field=cont, field_l=p["surface_high"], sel=mix(bg, acc, 0.16),
                line=mix(cont, p["on_surface"], 0.16), line_soft=mix(cont, p["on_surface"], 0.08),
                gdark=bg, line3=bg,
                text=p["on_surface"], dim=mix(p["on_surface_variant"], bg, 0.30),
                faint=mix(p["on_surface_variant"], bg, 0.65), err=p["error"])



# ── разделы по важности ──────────────────────────────────────────────────────
# 13.10.2026, Просьба: «деление по приоритетам… лучшее разделение по категориям, но
# вкладка staticOS должна оставаться». Раздел ищется сначала по имени программы
# (ключевые слова), потом по категориям .desktop. Порядок списка — порядок на экране:
# что открывают каждый день — выше, служебное (Qt-утилиты, Java-консоли) — в самом низу.
# Новая программа попала не туда — дописать слово в kw нужного раздела.

GROUPS = (
    ("staticOS", None, (), ("X-StaticOS",)),
    ("Браузеры", "internet-web-browser",
     ("zen", "helium", "librewolf", "firefox", "torbrowser", "tor browser", "mercury", "chromium"),
     ("WebBrowser",)),
    ("Общение", "internet-chat", ("telegram", "discord", "vesktop", "zapzap", "zoom"),
     ("Chat", "InstantMessaging", "Email")),
    ("Музыка и видео", "applications-multimedia",
     ("yandex", "youtube-music", "spotify", "mpv", "obs studio", "obsproject", "blanket"), ("AudioVideo", "Audio", "Video", "Player")),
    ("Игры", "applications-games", ("steam", "counter-strike", "cs2", "keypunch"), ("Game",)),
    ("Код и заметки", "applications-development",
     ("code", "sublime", "neovim", "nvim", "obsidian", "dbeaver", "postman", "micro", "vim"),
     ("Development", "IDE")),
    ("Офис", "applications-office", ("libreoffice", "calendar"), ("Office",)),
    ("Файлы и терминал", "system-file-manager", ("dolphin", "nautilus", "files", "yazi", "kitty", "foot"),
     ("FileManager", "TerminalEmulator")),
    ("Графика и снимки", "applications-graphics",
     ("gwenview", "pinta", "picker", "ksnip", "spectacle", "image viewer", "imv"), ("Graphics", "Photography")),
    ("Утилиты", "applications-utilities",
     ("keepassxc", "speedcrunch", "copyq", "clocks", "mousepad", "espanso", "waypaper", "seahorse",
      "passwords", "ventoy", "gammastep"), ("Utility", "TextEditor", "Accessories")),
    ("Устройства и сеть", "preferences-system-network",
     ("anydesk", "teamviewer", "kdeconnect", "kde connect", "localsend", "avahi"), ("RemoteAccess", "Network")),
    ("Настройки", "preferences-system",
     ("blueman", "bluetooth", "pavucontrol", "pwvucontrol", "volume control", "noctalia", "polychromatic",
      "nm-connection", "network configuration", "gtk settings", "qt5ct", "qt6ct", "systemsettings",
      "displays", "profile pic"), ("Settings",)),
    ("Система", "utilities-system-monitor",
     ("btop", "jtop", "htop", "system monitor", "sysmontask", "virtualbox", "discover", "lshw", "lstopo"),
     ("System", "Monitor")),
    ("Служебное", "applications-other", (), ()),
)
# Служебное ловится первым, иначе «Qt Designer» уйдёт в «Код», а «Foot Server» — в терминал.
SERVICE = ("qt assistant", "qt d-bus", "qt linguist", "qt widgets", "qt v4l2", "openjdk", "java",
           "xgps", "rofi", "byobu", "foot server", "foot client", "indicator", "kde connect sms",
           "launcher settings", "zapzapnogpu", "crashed processes", "zeroconf", "ssh server",
           "vnc server")


def group_of(a):
    hay = " ".join(x for x in ((a.get_id() or ""), (a.get_display_name() or ""),
                               (a.get_executable() or "")) if x).lower()
    have = set((a.get_categories() or "").split(";"))
    if "X-StaticOS" in have:
        return "staticOS"
    title = (a.get_display_name() or "").lower()
    for text in (title, hay):            # сперва по названию: jtop запускается через kitty
        if any(re.search(r"\b" + re.escape(k), text) for k in SERVICE):   # «rofi» ≠ «profile»
            return "Служебное"
        for name, _i, kw, _x in GROUPS:
            if any(k in text for k in kw):
                return name
    for name, _i, _k, xdg in GROUPS:
        if have & set(xdg):
            return name
    return "Служебное"


def load_apps():
    cats = {name: [] for name, *_ in GROUPS}
    for a in Gio.AppInfo.get_all():
        if a.should_show():
            cats[group_of(a)].append(a)
    for v in cats.values():
        v.sort(key=lambda a: (a.get_display_name() or "").lower())
    return [(n, cats[n]) for n, *_ in GROUPS if cats[n]]


GROUP_ICON = {name: icon for name, icon, *_ in GROUPS}

_icon_cache = {}


def get_icon(gicon=None, size=24, name=None):
    key = (name or str(gicon), size)
    if key in _icon_cache:
        return _icon_cache[key]
    theme = Gtk.IconTheme.get_default()
    pb = None
    try:
        info = theme.lookup_icon(name, size, Gtk.IconLookupFlags.FORCE_SIZE) if name else \
            (theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE) if gicon else None)
        pb = info.load_icon() if info else None
    except Exception:
        pb = None
    _icon_cache[key] = pb
    return pb


# ── меню как у Omarchy ───────────────────────────────────────────────────────
# 13.10.2026, Просьба: «категорию Удалить… Обновить… О системе… Система… Установить…
# Настройки… Действие… Справка» — по меню «Go…» Omarchy (bin/omarchy-menu, v3.1):
# Learn → Справка, Trigger → Действия, Setup → Настройки, Install/Remove/Update →
# Установить/Удалить/Обновить, About → О системе, System → Система. «Оформление»
# (Style) не просили — его нет. Узел: {"name", "icon", "kids": [...]} — подменю;
# {"name", "icon", "run": команда sh, "keys": подсказка справа, "state": команда,
# которая печатает состояние} — действие; {"app": Gio.AppInfo} — программа.
# Терминальные пункты (fzf со списком пакетов, fastfetch) — launcher_term.sh.

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
NIRI_SCRIPTS = os.path.expanduser("~/.config/niri/scripts")


def _py(name, *args):
    return " ".join(["python3", os.path.join(SCRIPTS, name)] + list(args))


def _term(cmd, title):
    return "TITLE=%s %s open %s" % (shlex.quote(title), os.path.join(SCRIPTS, "launcher_term.sh"), cmd)


def _web(url):
    return "xdg-open " + shlex.quote(url)


def _edit(path):
    return "xdg-open " + shlex.quote(os.path.expanduser(path))


def act(name, icon, run, keys=None, state=None):
    return {"name": name, "icon": icon, "run": run, "keys": keys, "state": state}


def sub(name, icon, kids):
    return {"name": name, "icon": icon, "kids": kids}


def menu_tree(cats):
    apps = sub("Приложения", ("applications-all", "start-here"),
               [{"name": n, "icon": GROUP_ICON.get(n), "group": True, "kids": [{"app": a} for a in lst]}
                for n, lst in cats])
    toggle = lambda get, on, off: "if %s; then %s; else %s; fi" % (get, off, on)
    return sub("Меню", None, [
        apps,
        sub("Справка", ("help-contents", "system-help"), [
            act("Шпаргалка клавиш", ("preferences-desktop-keyboard-shortcuts", "input-keyboard"),
                _py("keybinds_sheet.py"), "Super+Z"),
            act("Карта staticOS", ("gnome-maps", "document-properties"), _py("config_map.py"), "Super+Shift+Z"),
            act("Клавиши niri (встроенный список)", ("input-keyboard",),
                "niri msg action show-hotkey-overlay", "Super+Shift+/"),
            act("Вики niri", ("help-browser",), _web("https://github.com/YaLTeR/niri/wiki")),
            act("Arch Wiki", ("distributor-logo-archlinux",), _web("https://wiki.archlinux.org/")),
            act("Fish — справка", ("utilities-terminal",), _web("https://fishshell.com/docs/current/")),
            act("Bash — шпаргалка", ("text-x-script",), _web("https://devhints.io/bash")),
            act("Дотфайлы на GitHub", ("github", "folder-github"), _web("https://github.com/staticxyz/staticos")),
        ]),
        sub("Действия", ("system-run", "media-playback-start"), [
            sub("Снимок", ("applets-screenshooter", "accessories-screenshot"), [
                act("Область", ("applets-screenshooter",), "niri msg action screenshot", "Print"),
                act("Весь экран", ("video-display",), "niri msg action screenshot-screen", "Ctrl+Print"),
                act("Окно в фокусе", ("view-restore",), "sleep 0.3; niri msg action screenshot-window",
                    "Super+Ctrl+S"),
                act("С пометками", ("accessories-text-editor",), os.path.join(SCRIPTS, "screenshot_annotate.sh"),
                    "Super+Print"),
                act("Текст с экрана", ("gscan2pdf",), os.path.join(SCRIPTS, "ocr_copy.sh"), "Shift+Print"),
                act("Пипетка: цвет в буфер", ("color-picker", "gcolor3"),
                    "hyprpicker -a -f hex >/dev/null && notify-send -a staticOS 'Цвет скопирован' \"$(wl-paste)\""),
            ]),
            act("Запись экрана", ("media-record", "simplescreenrecorder"),
                os.path.join(SCRIPTS, "rec_area.sh"), "Super+Shift+Print"),
            sub("Переключить", ("preferences-system", "view-refresh"), [
                act("Не беспокоить", ("notification-disabled", "preferences-system-notifications"),
                    "swaync-client -d >/dev/null",
                    state="[ \"$(swaync-client -D)\" = true ] && echo вкл || echo выкл"),
                act("Ночной режим", ("weather-clear-night",),
                    toggle(_py("night_mode.py", "get") + " | grep -q ^on",
                           _py("night_mode.py", "on"), _py("night_mode.py", "off")),
                    state=_py("night_mode.py", "get") + " | grep -q ^on && echo вкл || echo выкл"),
                act("Заставка по бездействию", ("screensaver",),
                    toggle(_py("screensaver.py", "get") + " | grep -q ^on",
                           _py("screensaver.py", "on"), _py("screensaver.py", "off")),
                    state=_py("screensaver.py", "get") + " | grep -q ^on && echo вкл || echo выкл"),
                sub("Верхний бар", ("preferences-desktop",), [
                    act("Всегда", ("preferences-desktop",), _py("top_bar.py", "set", "always")),
                    act("При наведении", ("preferences-desktop",), _py("top_bar.py", "set", "hover")),
                    act("Скрыт", ("preferences-desktop",), _py("top_bar.py", "set", "off")),
                ]),
            ]),
            act("Эмодзи", ("face-smile", "preferences-desktop-emoticons"), "bemoji -t", "Super+F6"),
            act("Буфер обмена", ("edit-paste",), os.path.join(NIRI_SCRIPTS, "clipboard-toggle"), "Super+Alt+V"),
            act("Напоминания", ("alarm-clock", "x-office-calendar"),
                os.path.expanduser("~/.local/bin/hub-open") + " --toggle", "Super+M"),
        ]),
        sub("Настройки", ("preferences-system",), [
            act("Настройки staticOS", ("preferences-system",), os.path.join(NIRI_SCRIPTS, "settings-open"),
                "Super+/"),
            act("Звук", ("audio-volume-high",), "pwvucontrol || pavucontrol"),
            act("Wi-Fi", ("network-wireless",), _py("wifi_popup.py")),
            act("Bluetooth", ("bluetooth",), _py("bluetooth_popup.py")),
            act("Сеть", ("preferences-system-network",), _py("lan_popup.py")),
            act("Центр управления", ("preferences-system-notifications",), _py("control_center.py")),
            act("Обои", ("preferences-desktop-wallpaper",), _py("wallpaper_picker.py"), "Super+W"),
            act("Мониторы (outputs.kdl)", ("video-display", "preferences-desktop-display"),
                _edit("~/.config/niri/cfg/outputs.kdl")),
            act("Клавиши (binds.kdl)", ("preferences-desktop-keyboard-shortcuts",),
                _edit("~/.config/niri/cfg/binds.kdl")),
            act("Ввод: клавиатура и мышь (input.kdl)", ("input-keyboard",), _edit("~/.config/niri/cfg/input.kdl")),
            act("Папка конфига niri", ("folder",), _edit("~/.config/niri")),
        ]),
        sub("Установить", ("system-software-install", "package-x-generic"), [
            act("Пакет", ("package-x-generic",), _term("install", "Установить пакет")),
            act("Пакет из AUR", ("package-x-generic",), _term("aur", "Установить из AUR")),
            act("Шрифт", ("font-x-generic",), _term("font", "Установить шрифт")),
        ]),
        sub("Удалить", ("edit-delete", "user-trash"), [
            act("Пакет", ("package-x-generic",), _term("remove", "Удалить пакет")),
            act("Пакет из AUR", ("package-x-generic",), _term("remove-aur", "Удалить пакет AUR")),
            act("Ненужные зависимости", ("edit-clear-all", "user-trash"), _term("orphans", "Ненужные зависимости")),
            act("Старый кэш пакетов", ("user-trash",), _term("cache", "Кэш пакетов")),
        ]),
        sub("Обновить", ("system-software-update", "update-manager"), [
            act("Систему (пакеты и AUR)", ("system-software-update",), _term("update", "Обновление системы")),
            act("Только пакеты pacman", ("package-x-generic",), _term("update-repo", "Обновление pacman")),
            sub("Перезапустить", ("view-refresh",), [
                act("Верхний бар", ("preferences-desktop",), os.path.expanduser("~/.local/bin/barfix")),
                act("Звук (PipeWire)", ("audio-volume-high",), os.path.join(SCRIPTS, "audio_repair")),
                act("Конфиг niri", ("view-refresh",), "niri msg action load-config-file"),
                act("Напоминания (hub)", ("alarm-clock",), "systemctl --user restart hub.service"),
            ]),
            act("Пароль", ("dialog-password",), _term("passwd", "Смена пароля")),
            act("Часовой пояс", ("preferences-system-time",), _term("timezone", "Часовой пояс")),
        ]),
        act("О системе", ("computer", "help-about"), _term("about", "О системе")),
        sub("Система", ("system-shutdown",), [
            act("Блокировка", ("system-lock-screen",), os.path.join(NIRI_SCRIPTS, "shell-do") + " lock", "Super+O"),
            act("Заставка", ("screensaver",), _py("screensaver.py")),
            act("Сон", ("system-suspend",), _py("power_menu.py", "--only", "suspend")),
            act("Выход", ("system-log-out",), _py("power_menu.py", "--only", "logout")),
            act("Перезагрузка", ("system-reboot",), _py("power_menu.py", "--only", "reboot")),
            act("Выключение", ("system-shutdown",), _py("power_menu.py", "--only", "shutdown")),
        ]),
    ])


def leaves(node, path=()):
    """Все программы и действия дерева: [(узел, «Раздел › Подраздел»)] — для поиска."""
    out = []
    for k in node.get("kids", ()):
        if "kids" in k:
            out += leaves(k, path + (k["name"],))
        else:
            out.append((k, " › ".join(path)))
    return out


def node_label(k):
    return k["app"].get_display_name() or "?" if "app" in k else k["name"]


def node_icon(k, size):
    if "app" in k:
        return get_icon(k["app"].get_icon(), size)
    names = k.get("icon") or ()
    for n in (names,) if isinstance(names, str) else names:
        pb = get_icon(name=n, size=size)
        if pb is not None:
            return pb
    if k.get("group") and k.get("kids"):
        return get_icon(k["kids"][0]["app"].get_icon(), size)
    return None


# ── окно ─────────────────────────────────────────────────────────────────────
# Вид — как меню Omarchy (13.10.2026, Просьба: «максимально похоже»): узкая карточка по
# центру экрана, сверху поле поиска, ниже строки «значок + название»; выбранная —
# подложкой. Рамка, цвета и крестик — Recorder (exe_frame.py) по стилю системы.
# За окном — лёгкое затемнение, без размытия (размытие всего экрана убрано из
# layer-rules.kdl: «у меня не видно ничего за этим меню»).

CW = 460                 # ширина карточки
INPUT_H = 36
MAX_ROWS = 12
SCRIM = 0.22             # затемнение экрана за меню
LAUNCH_BMP = ("#######", "#.#.#.#", "#######", "#.#.#.#", "#######", "#.#.#.#", "#######")
BACK = "Назад"


def make_view(test=False, style=None):
    import rec_menu as R
    import exe_frame
    from smart_search import search

    class View(R.App):
        def __init__(self):                    # App.__init__ не зовём: там окно Recorder
            self.test = test
            exe_frame.look(self, style or style_name())
            self.G["ROW"] = max(self.G["ROW"], 42)   # под значки 32px (Пользователь 13.10: «чуть крупнее»)
            self.cats = load_apps()
            self.root = menu_tree(self.cats)
            self.all = leaves(self.root)
            self.mode, self.buf = "normal", ""
            self.path = []                     # номера подменю от корня; [] — верхний уровень
            self.sel, self.scroll = 0, 0
            self.pos = {}                      # (путь) -> (выбор, прокрутка): куда вернуться
            self.states = {}                   # id(узла) -> «вкл»/«выкл» у переключателей
            self.pending_t = 0.0
            self.hover = None
            self.SW, self.SH = 1920, 1080      # размер экрана — из окна
            self.top = None                    # верх карточки: по центру при открытии
            self.win = None

        # ── данные ─────────────────────────────────────────────────────────
        def node(self):
            n = self.root
            for i in self.path:
                n = n["kids"][i]
            return n

        def rows(self):
            """[("back",)] (не на верхнем уровне) + [("node", узел)]; поиск — по всем
            программам и действиям сразу."""
            ck = (self.buf, tuple(self.path))            # кадр зовёт rows() раз пять — искать один
            if getattr(self, "_rows_key", None) == ck:
                return self._rows
            self._rows_key, self._rows = ck, self._rows_calc()
            return self._rows

        def _rows_calc(self):
            if self.buf:
                def key(x):
                    k = x[0]
                    if "app" in k:
                        return (k["app"].get_display_name() or "", k["app"].get_name() or "")
                    return (k["name"],)

                def weak(x):
                    k = x[0]
                    if "app" in k:
                        a = k["app"]
                        return (x[1], a.get_description() or "",
                                " ".join(getattr(a, "get_keywords", lambda: [])() or []))
                    return (x[1], k.get("keys") or "")
                q = self.buf.strip().lower()
                if len(q) == 1:                       # одна буква — всё, что на неё начинается
                    from smart_search import TO_RU, TO_EN
                    starts = {q, q.translate(TO_RU), q.translate(TO_EN)}
                    return [("node", k, p) for k, p in self.all
                            if any(w[:1].lower() in starts for w in key((k, p))[0].split()[:1])]
                return [("node", k, p) for k, p in search(self.buf, self.all, key, weak=weak)]
            kids = [("node", k) for k in self.node()["kids"]]
            return ([("back",)] + kids) if self.path else kids

        def current(self):
            rows = self.rows()
            return rows[self.sel] if rows and 0 <= self.sel < len(rows) else None

        def title_text(self):
            if self.buf:
                return "Меню » Поиск"
            names, n = ["Меню"], self.root
            for i in self.path:
                n = n["kids"][i]
                names.append(n["name"])
            return " » ".join(names[-3:])

        # ── размеры ────────────────────────────────────────────────────────
        def list_y(self):
            G = self.G
            return G["TOP"] + G["TB"] + G["PAD"] + INPUT_H + G["PAD"] + (G["GROUP"] + 4 if G["GROUP"] else 0)

        def visible(self, n=None):
            n = len(self.rows()) if n is None else n
            fit = max(3, (self.SH - 80 - self.list_y()) // self.G["ROW"])
            return max(1, min(n, MAX_ROWS, fit))

        def card_h(self, n=None):
            G = self.G
            extra = 8 if G["GROUP"] else (4 if self.style == "beta" else 0)
            return self.list_y() + self.visible(n) * G["ROW"] + extra + G["PAD"] + G["BORDER"]

        def panel_rect(self):
            """Карточка: по центру экрана по высоте списка разделов; дальше верх стоит на
            месте, а карточка растёт вниз — как у Omarchy, не прыгает при поиске."""
            h = self.card_h()
            if self.top is None:
                self.top = max(20, (self.SH - self.card_h(MAX_ROWS)) // 2)
            y = min(self.top, max(0, self.SH - h - 20))
            return (self.SW - CW) // 2, y, CW, h

        def input_rect(self):
            G = self.G
            x = G["BORDER"] + G["PAD"] + (8 if self.style == "skeet" else 0)
            return x, G["TOP"] + G["TB"] + G["PAD"], CW - 2 * x, INPUT_H

        def list_box(self):
            x = self.input_rect()[0] + (2 if self.style == "skeet" else 0)
            return x, CW - 2 * x

        # ── рисование ──────────────────────────────────────────────────────
        def on_draw(self, _a, cr):
            if self.win is not None:
                a = self.win.area
                self.SW, self.SH = a.get_allocated_width(), a.get_allocated_height()
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, SCRIM if not self.test else 0)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_font_options(self.fo)
            px, py, w, h = self.panel_rect()
            cr.save()
            cr.translate(px, py)
            try:
                self.render(cr, w, h)
            except Exception as err:
                print("app_launcher: кадр: %s" % err, file=sys.stderr)
            cr.restore()
            return True

        def render(self, cr, W_, H_):
            C, G = self.C, self.G
            exe_frame.background(self, cr, W_, H_)
            exe_frame.frame(self, cr, W_, H_, LAUNCH_BMP)
            self.close_btn(cr)
            self.draw_input(cr)
            lx, lw = self.list_box()
            top = self.list_y()
            rows = self.rows()
            vis = self.visible()
            if self.style == "skeet":
                label = "Поиск" if self.buf else (self.node()["name"] if self.path else "Разделы")
                gx, gy, gw, gh = lx - 10, top - 12, lw + 20, vis * G["ROW"] + 22
                self.rect_line(cr, gx, gy, gw, gh, C["gline"])
                self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
                tw = self.layout(cr, label).get_pixel_size()[0]
                self.rect_fill(cr, gx + 10, gy - 1, tw + 8, 3, C["bg"])
                self.text(cr, label, gx + 14, gy - G["PX"] // 2 - 1, C["text"])
            elif self.style == "beta":
                self.rect_fill(cr, lx - 1, top - 1, lw + 2, vis * G["ROW"] + 2, C["card"])
                self.rect_line(cr, lx - 1, top - 1, lw + 2, vis * G["ROW"] + 2, C["line"])
            if not rows:
                self.text(cr, "Ничего не найдено", lx + 16, top + (G["ROW"] - self.LH) // 2, self.faint)
                return
            sel = max(0, min(self.sel, len(rows) - 1))
            off = min(self.scroll, sel)
            if sel >= off + vis:
                off = sel - vis + 1
            off = max(0, min(off, len(rows) - vis))
            self.sel, self.scroll = sel, off
            for i in range(off, min(off + vis, len(rows))):
                self.draw_row(cr, rows[i], i == sel, lx, top + (i - off) * G["ROW"], lw)
            if len(rows) > vis:
                avail = vis * G["ROW"]
                bh = max(14, avail * vis / len(rows))
                by = top + (avail - bh) * off / max(1, len(rows) - vis)
                self.rect_fill(cr, lx + lw - 3, by, 3, bh, self.faint)

        def draw_input(self, cr):
            C = self.C
            x, y, w, h = self.input_rect()
            on = self.mode == "search"
            hov = self.hover == ("input",)
            self.rect_fill(cr, x, y, w, h, self.field)
            self.rect_line(cr, x, y, w, h, self.acc if on or hov else self.soft)
            ty = y + (h - self.LH) // 2 + 1
            badge = "Esc" if on else "/ поиск"
            bw = self.text(cr, badge, x + w - 10 - self.layout(cr, badge).get_pixel_size()[0], ty, self.faint)[0]
            if on or self.buf:
                tw = self.text(cr, self.buf, x + 12, ty, C["text"], w - bw - 36)[0]
                if on:
                    self.rect_fill(cr, x + 12 + tw + 1, y + 8, 2, h - 16, self.acc)
            else:
                self.text(cr, "Найти…", x + 12, ty, self.faint, w - bw - 36)

        def draw_row(self, cr, r, on, x, y, w):
            C, G, st = self.C, self.G, self.style
            R_ = G["ROW"]
            ry, rh = y + 1, R_ - 2
            if on:
                self.rect_fill(cr, x, ry, w, rh, C["sel_bg"])
                if st == "skeet":
                    self.rect_line(cr, x, ry, w, rh, C["gline"])
                if st != "default":
                    self.rect_fill(cr, x, ry, 3, rh, self.acc)
            elif st == "default":
                self.rect_fill(cr, x, ry, w, rh, C["row"], 0.045)
            fg = C["sel_text"] if on else C["text"]
            ty = ry + (rh - self.LH) // 2 + 1
            isz = ICON
            iy = ry + (rh - isz) // 2
            if r[0] == "back":
                cr.set_source_rgb(*(fg if on else C["dim"]))
                cr.save()                                   # стрелка влево — зеркальная ARROW_BMP
                cr.translate(x + 16 + 8, 0)
                cr.scale(-1, 1)
                R.draw_bitmap(cr, R.ARROW_BMP, 0, ry + (rh - 14) // 2, 2)
                cr.restore()
                self.text(cr, BACK, x + 16 + isz + 10, ty, fg if on else C["dim"])
                return
            k = r[1]
            pb = node_icon(k, isz)
            label = node_label(k)
            if pb is not None:
                Gdk.cairo_set_source_pixbuf(cr, pb, x + 14, iy)
                cr.paint_with_alpha(1.0 if on else 0.85)
            right = 0
            if "kids" in k:                           # подменю: число (у разделов программ) и стрелка
                count = str(len(k["kids"])) if k.get("group") else ""
                cw = self.layout(cr, count).get_pixel_size()[0] if count else 0
                if count:
                    self.text(cr, count, x + w - 34 - cw, ty, C["sel_text"] if on else C["dim"])
                cr.set_source_rgb(*(C["sel_text"] if on else C["arrow"]))
                R.draw_bitmap(cr, R.ARROW_BMP, x + w - 22, ry + (rh - 14) // 2, 2)
                right = 44 + cw
            else:                                     # действие: состояние или клавиши справа
                hint = self.states.get(id(k)) or (                # в поиске — откуда пункт:
                    (r[2].split(" › ")[-1] if "app" not in k else "") if len(r) > 2 and r[2]
                    else k.get("keys"))                               # «Пакет» есть и в «Удалить»
                hw = self.layout(cr, hint).get_pixel_size()[0] if hint else 0
                lw_ = self.layout(cr, label).get_pixel_size()[0]
                if hint and 14 + isz + 12 + lw_ + 24 + hw + 14 > w:  # не влезает — название важнее
                    hint = None
                if hint:
                    hot = hint == "вкл"
                    self.text(cr, hint, x + w - 14 - hw, ty,
                              C["sel_text"] if on else (self.acc if hot else C["dim"]))
                    right = hw + 16
            self.text(cr, label, x + 14 + isz + 12, ty, fg, w - 14 - isz - 12 - right - 12)

        # ── действия ───────────────────────────────────────────────────────
        def redraw(self):
            if self.win is not None:
                self.win.area.queue_draw()

        def close(self):
            if not self.test:
                os._exit(0)

        def enter(self, idx):
            self.pos[tuple(self.path)] = (self.sel, self.scroll)
            self.path.append(idx)
            self.sel, self.scroll = self.pos.get(tuple(self.path), (1, 0))   # 1 — первая строка, не «Назад»
            self.load_states()

        def load_states(self):
            """Состояние переключателей подменю («вкл»/«выкл») — при входе в него."""
            for k in self.node()["kids"]:
                if k.get("state") and not self.test:
                    try:
                        out = subprocess.run(k["state"], shell=True, capture_output=True,
                                             text=True, timeout=2).stdout.strip()
                    except Exception:
                        out = ""
                    self.states[id(k)] = out

        def back(self):
            if self.buf:
                self.buf, self.mode, self.sel, self.scroll = "", "normal", 0, 0
                if self.path:
                    self.sel = 1
                return
            if not self.path:
                self.close()
                return
            self.pos[tuple(self.path)] = (self.sel, self.scroll)
            idx = self.path.pop()
            self.sel = idx + (1 if self.path else 0)      # строка подменю, из которого вышли
            self.scroll = self.pos.get(tuple(self.path), (0, 0))[1]

        def activate(self):
            r = self.current()
            if not r:
                return
            if r[0] == "back":
                self.back()
            elif "kids" in r[1]:
                self.enter(next(i for i, k in enumerate(self.node()["kids"]) if k is r[1]))
            elif "app" in r[1]:
                self.launch(r[1]["app"])
            else:
                self.run(r[1]["run"])
            self.redraw()

        def run(self, cmd):
            if self.test:
                return
            subprocess.Popen(["sh", "-c", cmd], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.close()

        def launch(self, a):
            if self.test:
                return
            try:                       # как «Пуск»: терминальные — в kitty, обычные — через niri
                import start_menu
                start_menu.launch_app(a)
            except Exception:
                try:
                    a.launch(None, None)
                except Exception:
                    cmd = a.get_commandline()
                    if cmd:
                        subprocess.Popen(cmd, shell=True, start_new_session=True,
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.close()

        def move(self, d, to=None):
            n = len(self.rows())
            if n:
                self.sel = max(0, min(n - 1, to if to is not None else self.sel + d))
            self.redraw()

        # ── мышь ───────────────────────────────────────────────────────────
        def zone_at(self, x, y):
            px, py, w, h = self.panel_rect()
            x, y = x - px, y - py
            if not (0 <= x < w and 0 <= y < h):
                return ("outside",)
            if exe_frame.in_cap(self, x, y):
                return ("close",)
            G = self.G
            if y < G["TOP"] + G["TB"]:
                return ("title",)
            ix, iy, iw, ih = self.input_rect()
            if ix <= x < ix + iw and iy <= y < iy + ih:
                return ("input",)
            lx, lw = self.list_box()
            top = self.list_y()
            if lx <= x < lx + lw and top <= y < top + self.visible() * G["ROW"]:
                i = self.scroll + int((y - top) // G["ROW"])
                if i < len(self.rows()):
                    return ("row", i)
            return None

        def click(self, z, button=1):
            if not z:
                return
            if button == 3:                           # правая — назад
                if z[0] != "outside":
                    self.back()
                    self.redraw()
                return
            kind = z[0]
            if kind in ("outside", "close"):
                self.close()
            elif kind == "title" and (self.path or self.buf):
                self.back()
            elif kind == "input":
                self.mode = "search"
            elif kind == "row":
                self.sel = z[1]
                self.activate()
            self.redraw()

        def motion(self, x, y):
            z = self.zone_at(x, y)
            if z == self.hover:
                return
            self.hover = z
            self.hover_cap = z == ("close",)
            if z and z[0] == "row":                   # наведение выбирает строку, как у Omarchy
                self.sel = z[1]
            self.redraw()

        # ── клавиши ────────────────────────────────────────────────────────
        def key(self, ch, name, ctrl, shift, uni, mod=False):
            import time
            if (mod and ch == "x") or (ctrl and ch == "q"):
                self.close()
                return
            if ctrl and ch == "e":
                self.mode = "normal" if self.mode == "search" else "search"
            elif name in ("Down", "Up") or (ctrl and ch in ("j", "k", "n", "p")):
                self.move(1 if name == "Down" or ch in ("j", "n") else -1)
            elif ctrl and ch in ("d", "u"):
                self.move(max(1, self.visible() // 2) * (1 if ch == "d" else -1))
            elif self.mode == "search":
                now = time.monotonic()
                if name == "Escape":
                    if self.buf:
                        self.back()
                    else:
                        self.mode = "normal"
                elif name in ("Return", "KP_Enter"):
                    self.activate()
                elif name == "BackSpace":
                    self.buf = self.buf[:-1]
                    self.sel = self.scroll = 0
                elif ch == "j" and self.buf.endswith(uni or "j") and now - self.pending_t < 0.4:
                    self.buf = self.buf[:-1]               # jj — к списку
                    self.mode = "normal"
                elif uni and uni.isprintable() and len(self.buf) < 60:
                    self.buf += uni
                    self.sel = self.scroll = 0
                    self.pending_t = now if ch == "j" else 0.0
            else:
                if name == "Escape" or ch == "q":
                    self.close()
                elif name in ("BackSpace", "Left") or ch == "h":
                    self.back()
                elif ch == "j":
                    self.move(1)
                elif ch == "k":
                    self.move(-1)
                elif ch == "g" or name in ("Home", "End"):
                    self.move(0, len(self.rows()) - 1 if shift or name == "End" else 0)
                elif name in ("Return", "KP_Enter", "Right") or ch == "l":
                    self.activate()
                elif ch == "/":
                    self.mode = "search"
            self.redraw()

    return View


def shot(path, style=None, at=(), sel=0, mode="normal", buf=""):
    v = make_view(test=True, style=style)()
    v.SW, v.SH = 900, 900
    for i in at:
        v.enter(i)
    v.sel, v.mode, v.buf = sel if not at or sel else v.sel, mode, buf
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, v.SW, v.SH)
    cr = cairo.Context(surf)
    v.on_draw(None, cr)
    px, py, w, h = v.panel_rect()
    out = surf.create_for_rectangle(px, py, w, h)
    s2 = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    c2 = cairo.Context(s2)
    c2.set_source_surface(out, 0, 0)
    c2.paint()
    s2.write_to_png(path)


def check():
    View = make_view(test=True)
    v = View()
    names = [n for n, _ in v.cats]
    assert "staticOS" in names, "нет staticOS"
    total = sum(len(a) for _, a in v.cats)
    top = [k["name"] for k in v.root["kids"]]
    acts = [k for k, _p in v.all if "run" in k]
    bad = []                                          # первое слово команды должно существовать
    for k in acts:
        words = [w for w in shlex.split(k["run"]) if not re.match(r"^\w+=", w)]
        w = words[0] if words else ""
        if w not in ("if", "sleep", "[") and not (os.path.isfile(w) or shutil.which(w)):
            bad.append("%s: %s" % (k["name"], w))
    v.buf = "браузер"
    found = len(v.rows())
    v.buf = "удалить"
    rm = len(v.rows())
    print("check: меню %s; %d разделов программ, %d программ, %d действий; «браузер» → %d, «удалить» → %d"
          % (" / ".join(top), len(names), total, len(acts), found, rm))
    for b in bad:
        print("  нет команды —", b)
    return 0 if found and rm and not bad else 1


def window():
    View = make_view()
    v = View()

    class Win(Gtk.Window):
        def __init__(self):
            super().__init__(title="Launcher")
            self.set_decorated(False)
            self.set_app_paintable(True)
            vis = self.get_screen().get_rgba_visual()
            if vis:
                self.set_visual(vis)
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, NAMESPACE)
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
            GtkLayerShell.set_exclusive_zone(self, -1)
            for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                         GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(self, edge, True)
            self.area = Gtk.DrawingArea()
            self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                                 | Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.SCROLL_MASK)
            self.area.connect("draw", v.on_draw)
            self.area.connect("button-press-event", self.on_press)
            self.area.connect("button-release-event", self.on_release)
            self.area.connect("motion-notify-event", lambda _w, ev: v.motion(ev.x, ev.y) or True)
            self.area.connect("scroll-event", self.on_scroll)
            self.add(self.area)
            self.connect("key-press-event", self.on_key)
            self.press = None

        def on_key(self, _w, ev):
            u = Gdk.keyval_to_unicode(ev.keyval)
            v.key(KEYS.get(ev.hardware_keycode, ""), Gdk.keyval_name(ev.keyval) or "",
                  bool(ev.state & Gdk.ModifierType.CONTROL_MASK),
                  bool(ev.state & Gdk.ModifierType.SHIFT_MASK), chr(u) if u else "",
                  bool(ev.state & Gdk.ModifierType.MOD4_MASK))
            return True

        def on_press(self, _w, ev):
            if ev.type == Gdk.EventType.BUTTON_PRESS:
                self.press = (ev.button, v.zone_at(ev.x, ev.y))
            return True

        def on_release(self, _w, ev):
            if self.press and self.press[0] == ev.button:
                z = v.zone_at(ev.x, ev.y)
                if z == self.press[1]:            # отпустили там же, где нажали
                    v.click(z, ev.button)
            self.press = None
            return True

        def on_scroll(self, _w, ev):
            if ev.direction == Gdk.ScrollDirection.UP:
                v.move(-1)
            elif ev.direction == Gdk.ScrollDirection.DOWN:
                v.move(1)
            return True

    w = Win()
    v.win = w
    w.show_all()
    Gtk.main()
    os._exit(0)


def toggle_pidfile():
    return os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-launcher.pid")


def main():
    a = sys.argv[1:]
    if "--check" in a:
        return check()
    if "--shot" in a:
        i = a.index("--shot")
        p = a[i + 1] if i + 1 < len(a) else "/tmp/launcher.png"
        opts = dict(x.split("=", 1) for x in a if "=" in x)
        at = [int(x) for x in opts.get("at", "").split(",") if x != ""]
        if "cat" in opts:                          # прежний ключ: раздел программ
            at = [0, int(opts["cat"])]
        shot(p, style=opts.get("style"), at=at, sel=int(opts.get("sel", 0)),
             mode="search" if opts.get("q") else "normal", buf=opts.get("q", ""))
        print("saved", p)
        return 0
    pf = toggle_pidfile()                          # второй Super+X закрывает меню
    try:
        pid = int(open(pf).read())
        if pid != os.getpid() and b"app_launcher" in open("/proc/%d/cmdline" % pid, "rb").read():
            os.kill(pid, 15)
            return 0
    except (OSError, ValueError):
        pass
    with open(pf, "w") as f:
        f.write(str(os.getpid()))
    window()
    return 0


if __name__ == "__main__":
    sys.exit(main())
