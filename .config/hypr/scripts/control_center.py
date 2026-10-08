#!/usr/bin/env python3
"""Центр управления — панель «как в Noctalia». 30.09.2026.

    control_center.py            под точкой щелчка («lan» в баре)
    control_center.py --center   по середине экрана сверху (средние пилюли бара)

Пользователь показал «Главную» Noctalia v5 и попросил такую же для waybar. Её саму
не поднять рядом с waybar: Noctalia — целая оболочка со своим баром, и она
переписывает чужие конфиги (см. память noctalia-shell). Поэтому своя панель на
тех же деталях, что остальные попапы: popup_theme (палитра из обоев), пиксельный
шрифт, слой GTK3 LayerShell.

    ┌──┬──────────────────────────────────────────┬──────┐
    │  │ Главная                        ⚙  ⏻  ✕   │  ▁▃  │
    │ ⌂│ ┌──────────────────────────────────────┐ │ ▃▆█  │
    │ ♪│ │  обои, аватар, имя, аптайм, niri     │ │  ▅▂  │
    │ …│ └──────────────────────────────────────┘ │  ┆   │
    │  │ ┌ плеер ──────────────┐ ┌Wi-Fi┐ ┌ BT ┐   │  ▂▅  │
    │  │ └─────────────────────┘ ┌Коф.─┐ ┌Ночь┐   │ ▃▆█  │
    │  │ ┌ часы, дата ─────────┐ ┌Тиш.─┐ ┌Пит.┐   │  ▃▁  │
    └──┴──────────────────────────────────────────┴──────┘

Справа — зеркальный визуализатор, как в медиа-странице Noctalia: свой cava с
сырым выводом (~/.config/cava/control-center.conf), живёт ровно столько, сколько
панель (PR_SET_PDEATHSIG — умирает и при kill панели).

Значки рисуются не текстом, а по чернильной рамке глифа (Glyph): у глифов Nerd
Font разные поля внутри клетки, и в кнопках они сидели криво (Просьба: «иконки
некоторые плохо центрируются»).

Боковые значки переключают СТРАНИЦЫ внутри панели (Gtk.Stack, как вкладки
Noctalia): Звук, Система, Wi-Fi, Bluetooth, Питание, Календарь, Экранное время,
Уведомления. Страница строится при первом открытии и опрашивает своё состояние,
только пока видна; высота панели — всегда высота «Главной», длинное
прокручивается. Лишь ⚙ внизу закрывает панель и открывает «Настройки».
Переключатели — те же ручки, что у бара и «Настроек»: nmcli, bluetoothctl,
night_mode.py, swaync-client, powerprofilesctl, pactl/pulsectl, brightnessctl,
monitor_brightness.py, Savage Mode + «не отключать экран» (это и есть «кофеин»).
sudo — нигде. Состояния опрашиваются в потоке: окно появляется сразу.
"""
import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

# ── масштаб панели (05.10.2026) ──────────────────────────────────────────
# Пользователь: панель крупновата — три размера на выбор (Настройки → Waybar →
# «Попапы и меню» → «Масштаб центра управления»):
#   compact — компактный, ~72 %;  medium — средний, ~85 % (умолчание);
#   large — «как сейчас», пиксель в пиксель прежний вид (S = 1).
# Все размеры виджетов, поля и отступы CSS — через sc(n); кегли пиксельного
# шрифта — не умножением, а ступенями fs(): PxPlus чёткий только на целых
# кеглях из набора 12/16/24/32 px (память pixel-font-system).
#   control_center.py scale                       — показать режим
#   control_center.py scale compact|medium|large  — выбрать (со следующего открытия)
SCALE_FILE = os.path.expanduser("~/.config/hypr/state/control-center-scale")
SCALE_MODES = {"compact": 0.72, "medium": 0.85, "large": 1.0}
SCALE_DEFAULT = "medium"
FONT_STEPS = {
    "compact": {32: 24, 24: 16, 16: 12, 12: 12},
    "medium": {32: 24, 24: 24, 16: 16, 12: 12},
    "large": {},
}


def scale_mode():
    # CC_SCALE — только для проверок вне экрана (рендер в OffscreenWindow).
    m = os.environ.get("CC_SCALE", "")
    if m not in SCALE_MODES:
        try:
            with open(SCALE_FILE) as f:
                m = f.read().strip()
        except OSError:
            m = ""
    return m if m in SCALE_MODES else SCALE_DEFAULT


if len(sys.argv) > 1 and sys.argv[1] == "scale":
    if len(sys.argv) > 2:
        if sys.argv[2] not in SCALE_MODES:
            sys.exit("режимы: " + " | ".join(SCALE_MODES))
        os.makedirs(os.path.dirname(SCALE_FILE), exist_ok=True)
        with open(SCALE_FILE, "w") as f:
            f.write(sys.argv[2] + "\n")
    print(scale_mode())
    sys.exit(0)

MODE = scale_mode()
S = SCALE_MODES[MODE]


def sc(n):
    """Размер в px под масштаб: целые пиксели; ненулевое не схлопывается в 0."""
    if S == 1 or not n:
        return n
    v = int(abs(n) * S + 0.5) or 1
    return v if n > 0 else -v


def fs(px):
    """Кегль пиксельного шрифта под масштаб — ступенью из 12/16/24/32."""
    return FONT_STEPS[MODE].get(px, px)


def scale_css(text):
    """Числа в px из CSS — под масштаб: font-size ступенями, остальное sc()."""
    import re

    def one(m):
        n = int(m.group(2))
        return m.group(1) + "%dpx" % fs(n) if m.group(1) else "%dpx" % sc(n)
    return re.sub(r"(font-size:\s*)?(?<![\w.-])(-?\d+)px", one, text)


# Второй щелчок по «lan» закрывает панель.
popup_theme.single_instance(__file__)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

import mpris_common  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.expanduser("~/.cache/jarvis/control-center")
COVER_CACHE = os.path.expanduser("~/.cache/player-covers")
AVATAR = os.path.expanduser("~/.cache/avatar.png")
WAYPAPER = os.path.expanduser("~/.config/waypaper/config.ini")
CAVA_CONF = os.path.expanduser("~/.config/cava/control-center.conf")

HERO_W, HERO_H = sc(480), sc(176)  # карточка пользователя
COVER = sc(104)                # обложка в карточке плеера
AVATAR_SIZE = sc(92)
RADIUS = sc(14)
VIS_W = sc(150)                # ширина колонки визуализатора
VIS_BARS = 24                  # полос на половину (всего строк — вдвое больше)
ICON_FONT = "JetBrainsMono NF"

# Значки Nerd Font (Material Design).
I = {
    "home": "\U000f02dc", "sound": "\U000f057e", "system": "\U000f035b",
    "wifi": "\U000f05a9", "wifi_off": "\U000f05aa", "bt": "\U000f00af",
    "bt_off": "\U000f00b2", "battery": "\U000f0079", "calendar": "\U000f00ed",
    "bell": "\U000f009a", "bell_off": "\U000f009b", "gear": "\U000f0493",
    "power": "\U000f0425", "close": "\U000f0156", "coffee": "\U000f0176",
    "night": "\U000f0594", "perf": "\U000f04c5", "balanced": "\U000f0f85",
    "saver": "\U000f0f86", "play": "\U000f040a", "pause": "\U000f03e4",
    "music": "\U000f075a",
    "screentime": "\U000f0128",
    # для страниц
    "vol": "\U000f057e", "vol_off": "\U000f075f", "mic": "\U000f036c", "mic_off": "\U000f036d",
    "radio_on": "\U000f043e", "radio_off": "\U000f043d", "refresh": "\U000f0450",
    "lock": "\U000f033e", "chev_l": "\U000f0141", "chev_r": "\U000f0142",
    "bright": "\U000f00df", "monitor": "\U000f0379", "bat_chg": "\U000f0084",
    "headphones": "\U000f02cb", "magnify": "\U000f0349", "open": "\U000f03cc",
    "sweep": "\U000f05e9", "w1": "\U000f091f", "w2": "\U000f0922", "w3": "\U000f0925",
    "w4": "\U000f0928", "mouse": "\U000f037d", "keyboard": "\U000f030c", "phone": "\U000f011c",
    "laptop": "\U000f0322", "watch": "\U000f0897", "app": "\U000f003b", "check": "\U000f012c",
}
PIX_FONT = "PxPlus HP 100LX 6x8 Jarvis"

PY = sys.executable


def run(*args, timeout=3):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def spawn(*args):
    """Запустить отдельно от панели: она сейчас закроется, запущенное — нет."""
    subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def script(name, *args):
    return (PY, os.path.join(HERE, name), *args)


def fmt_uptime():
    try:
        with open("/proc/uptime") as f:
            sec = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return ""
    d, rest = divmod(sec, 86400)
    h, rest = divmod(rest, 3600)
    m = rest // 60
    parts = []
    if d:
        parts.append("%d д" % d)
    if h or d:
        parts.append("%d ч" % h)
    parts.append("%d мин" % m)
    return " ".join(parts)


def fmt_time(sec):
    sec = int(max(0, sec))
    h, rest = divmod(sec, 3600)
    m, s = divmod(rest, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%d:%02d" % (m, s)


def wallpaper_path():
    try:
        with open(WAYPAPER, encoding="utf-8") as f:
            for line in f:
                k, _, v = line.partition("=")
                if k.strip() == "wallpaper":
                    return os.path.expanduser(v.strip())
    except OSError:
        pass
    return None


def hero_image(scale):
    """Обои, обрезанные по центру под карточку и чуть затемнённые. Кэшируется."""
    src = wallpaper_path()
    if not src or not os.path.exists(src):
        return None
    w, h = HERO_W * scale, HERO_H * scale
    key = hashlib.sha1(("%s:%s:%dx%d:v1" % (src, os.path.getmtime(src), w, h)).encode()).hexdigest()
    out = os.path.join(CACHE, key + ".png")
    if not os.path.exists(out):
        from PIL import Image, ImageEnhance
        os.makedirs(CACHE, exist_ok=True)
        im = Image.open(src).convert("RGB")
        ratio = w / h
        iw, ih = im.size
        if iw / ih > ratio:
            cw = int(ih * ratio)
            im = im.crop(((iw - cw) // 2, 0, (iw - cw) // 2 + cw, ih))
        else:
            ch = int(iw / ratio)
            im = im.crop((0, (ih - ch) // 2, iw, (ih - ch) // 2 + ch))
        im = im.resize((w, h), Image.LANCZOS)
        im = ImageEnhance.Brightness(im).enhance(0.80)
        im.save(out)
    return out


def rounded(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def rgba(hexcolor, alpha=1.0):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return c.red, c.green, c.blue, alpha


# ── состояния переключателей ─────────────────────────────────────────────
# Каждое: get() -> (включено, подпись-или-None); toggle() — сделать шаг.

def wifi_get():
    return run("nmcli", "radio", "wifi") == "enabled", None


def wifi_toggle(on):
    run("nmcli", "radio", "wifi", "off" if on else "on")


def bt_get():
    out = run("bluetoothctl", "show")
    return "Powered: yes" in out, None


def bt_toggle(on):
    if not on:
        # Выключенный через rfkill адаптер bluetoothctl не включит.
        run("rfkill", "unblock", "bluetooth")
    run("bluetoothctl", "power", "off" if on else "on", timeout=5)


def caffeine_get():
    """(вкл, "taurine" | None). Кофеин = Savage Mode; «Таурин» — вдобавок экран
    не гаснет и не запирается (screen_awake). 01.10.2026, пользователь: ЛКМ — просто
    Savage, ПКМ — Savage и «не выключать экран», надпись «Кофеин + Таурин»."""
    sys.path.insert(0, HERE)
    import savage_battery
    import screen_awake
    on = savage_battery.is_savage_active()
    return on, ("taurine" if on and screen_awake.get() else None)


def _savage_on():
    import savage_battery
    if not savage_battery.is_savage_active():
        # systemd-inhibit должен пережить панель — отдельной сессией.
        spawn(*script("savage_battery.py", "--toggle"))
        time.sleep(0.4)


def caffeine_toggle(on):
    """ЛКМ: вкл — только Savage; выкл — всё (выключение Savage гасит и экран)."""
    import savage_battery
    if on:
        if savage_battery.is_savage_active():
            run(*script("savage_battery.py", "--toggle"))
    else:
        _savage_on()


def caffeine_taurine(extra):
    """ПКМ: «Таурин» вкл/выкл — Savage + экран не гаснет; выкл оставляет Savage."""
    if extra == "taurine":
        run(*script("screen_awake.py", "off"))
    else:
        _savage_on()
        run(*script("screen_awake.py", "on"))


def night_get():
    return run(*script("night_mode.py", "get")).startswith("on"), None


def night_toggle(on):
    run(*script("night_mode.py", "off" if on else "on"), timeout=6)


def dnd_get():
    return run("swaync-client", "-D") == "true", None


def dnd_toggle(on):
    run("swaync-client", "-df" if on else "-dn")


PROFILES = ["power-saver", "balanced", "performance"]
PROFILE_NAME = {"power-saver": ("Экономия", "saver"), "balanced": ("Баланс", "balanced"),
                "performance": ("Мощность", "perf")}


def power_get():
    # busctl — 3 мс; powerprofilesctl сам питон-скрипт, 140 мс.
    p = run("busctl", "get-property", "net.hadess.PowerProfiles", "/net/hadess/PowerProfiles",
            "net.hadess.PowerProfiles", "ActiveProfile").removeprefix("s ").strip('"')
    return p != "balanced" and p in PROFILES, p or None


def power_toggle(_on):
    """ЛКМ — только «Баланс» ↔ «Мощность» (из «Экономии» — в «Баланс»)."""
    _on, cur = power_get()
    run("powerprofilesctl", "set", "performance" if cur == "balanced" else "balanced")


def power_saver(_extra):
    """ПКМ — «Экономия» (повторно — обратно в «Баланс»)."""
    _on, cur = power_get()
    run("powerprofilesctl", "set", "balanced" if cur == "power-saver" else "power-saver")




class Glyph(Gtk.DrawingArea):
    """Значок, выровненный по своей чернильной рамке, а не по клетке шрифта.

    Цвет берётся из CSS родителя (color наследуется), поэтому :hover и
    «включено» у кнопки перекрашивают значок так же, как текст.
    """

    def __init__(self, char, px=18, box=None):
        super().__init__()
        self.char, self.px = char, sc(px)
        side = sc(box or px + 6)
        self.set_size_request(side, side)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.connect("draw", self.on_draw)
        self.connect("state-flags-changed", lambda *_: self.queue_draw())

    def set_char(self, char):
        if char != self.char:
            self.char = char
            self.queue_draw()

    def on_draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        ctx = widget.get_style_context()
        c = ctx.get_color(ctx.get_state())
        layout = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string(ICON_FONT)
        fd.set_absolute_size(self.px * Pango.SCALE)
        layout.set_font_description(fd)
        layout.set_text(self.char, -1)
        ink, _log = layout.get_pixel_extents()
        cr.move_to(round((w - ink.width) / 2 - ink.x), round((h - ink.height) / 2 - ink.y))
        cr.set_source_rgba(c.red, c.green, c.blue, c.alpha)
        PangoCairo.show_layout(cr, layout)
        return True


def icon_button(char, css, px=18, box=None, tip=None):
    b = Gtk.Button()
    for cls in css.split():
        b.get_style_context().add_class(cls)
    b.add(Glyph(char, px, box))
    if tip:
        b.set_tooltip_text(tip)
    return b


class Tile(Gtk.Button):
    """Плитка-переключатель: значок над подписью; включённая — залита акцентом."""

    def __init__(self, icon, label, icon_off, getter, toggler, kind=None, right=None):
        super().__init__()
        self.icon_on, self.icon_off = icon, icon_off
        self.getter, self.toggler, self.kind = getter, toggler, kind
        self.label0 = label
        self.extra = None
        # right(tile, event) — своё действие на ПКМ (01.10.2026)
        self.right = right
        self.connect("button-press-event", self.on_press)
        self.on = False
        self.get_style_context().add_class("tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(6))
        box.set_valign(Gtk.Align.CENTER)
        self.ic = Glyph(icon_off, 20, 26)
        self.lb = Gtk.Label(label=label)
        self.lb.get_style_context().add_class("tile-label")
        self.lb.set_ellipsize(3)
        self.lb.set_max_width_chars(11)
        if S < 1:
            # Меньший масштаб: плитка уже, а подпись — тот же 12 px (мельче
            # PxPlus не читается). Вместо «Ночной св…» — перенос по словам в
            # две строки; самое длинное слово («Bluetooth») задаёт ширину плитки.
            self.lb.set_ellipsize(0)
            self.lb.set_line_wrap(True)
            self.lb.set_line_wrap_mode(Pango.WrapMode.WORD)
            self.lb.set_justify(Gtk.Justification.CENTER)
        box.pack_start(self.ic, False, False, 0)
        box.pack_start(self.lb, False, False, 0)
        self.add(box)
        self.connect("clicked", self.on_click)
        self.busy = False
        self.poll()

    def poll(self):
        threading.Thread(target=self._poll, daemon=True).start()

    def _poll(self):
        try:
            state = self.getter()
        except Exception:
            state = (False, None)
        GLib.idle_add(self.show_state, *state)

    def show_state(self, on, extra):
        self.on, self.extra = on, extra
        ctx = self.get_style_context()
        (ctx.add_class if on else ctx.remove_class)("on")
        if self.kind == "coffee":
            taurine = on and extra == "taurine"
            (ctx.add_class if taurine else ctx.remove_class)("taurine")
            # в две строки: в ширину плитки «Кофеин + Таурин» пиксельным шрифтом не
            # влезает даже слитно
            self.lb.set_text("Кофеин\n+ Таурин" if taurine else self.label0)
            self.lb.set_justify(Gtk.Justification.CENTER)
            self.lb.set_ellipsize(0 if taurine or S < 1 else 3)
            # значок кофе остаётся и у «Кофеин + Таурин» (просьба 01.10.2026);
            # чтобы две строки и значок влезли в плитку — промежуток меньше
            self.ic.set_visible(True)
            self.ic.get_parent().set_spacing(sc(2) if taurine else sc(6))
        if self.kind == "power" and extra in PROFILE_NAME:
            name, ic = PROFILE_NAME[extra]
            self.lb.set_text(name)
            self.ic.set_char(I[ic])
        else:
            self.ic.set_char(self.icon_on if on else self.icon_off)
        self.ic.queue_draw()
        self.busy = False
        return False

    def on_press(self, _w, e):
        if e.button != 3 or self.right is None:
            return False
        self.right(self, e)
        return True

    def run_bg(self, fn, *args):
        """Действие в фоне, потом — перечитать состояние."""
        if self.busy:
            return
        self.busy = True

        def work():
            try:
                fn(*args)
            except Exception:
                pass
            self._poll()
        threading.Thread(target=work, daemon=True).start()

    def on_click(self, _b):
        if self.busy:
            return
        was = self.on
        # Отклик сразу, настоящее состояние — после команды.
        if self.kind not in ("power", "coffee"):
            self.show_state(not was, None)
        elif self.kind == "coffee":
            self.show_state(not was, None)      # ЛКМ: вкл — только кофеин, выкл — всё
        self.busy = True

        def work():
            try:
                self.toggler(was)
            except Exception:
                pass
            self._poll()
        threading.Thread(target=work, daemon=True).start()


class Visualizer(Gtk.DrawingArea):
    """Зеркальный спектр, как у Noctalia: полосы растут в обе стороны от
    вертикальной оси; от середины высоты вверх и вниз — одни и те же частоты
    (низкие у середины). В тишине остаётся пунктирная ось."""

    def __init__(self, pal):
        super().__init__()
        self.pal = pal
        self.vals = [0.0] * VIS_BARS
        self.proc = None
        self.fresh = False
        self.set_size_request(VIS_W - sc(20), -1)
        self.connect("draw", self.on_draw)
        self.start()
        GLib.timeout_add(33, self.frame)

    def start(self):
        if not os.path.exists(CAVA_CONF):
            return
        libc = ctypes.CDLL("libc.so.6", use_errno=True)

        def die_with_parent():
            libc.prctl(1, signal.SIGTERM)       # PR_SET_PDEATHSIG
        try:
            self.proc = subprocess.Popen(["cava", "-p", CAVA_CONF], stdout=subprocess.PIPE,
                                         stderr=subprocess.DEVNULL, text=True,
                                         preexec_fn=die_with_parent)
        except OSError:
            self.proc = None
            return
        threading.Thread(target=self.reader, daemon=True).start()

    def reader(self):
        for line in self.proc.stdout:
            parts = [p for p in line.strip().strip(";").split(";") if p.isdigit()]
            if len(parts) >= VIS_BARS:
                self.vals = [min(int(p), 1000) / 1000 for p in parts[:VIS_BARS]]
                self.fresh = True

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()

    def frame(self):
        if self.fresh:
            self.fresh = False
            self.queue_draw()
        return True

    def on_draw(self, widget, cr):
        import cairo
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        mid_x, mid_y = w / 2, h / 2
        rows = VIS_BARS * 2
        pitch = (h - 8) / rows
        bar_h = max(2.0, round(pitch * 0.62))
        g = cairo.LinearGradient(0, 0, 0, h)
        top = rgba(self.pal["primary"])
        bottom = rgba(self.pal["tertiary"])
        g.add_color_stop_rgba(0.0, *bottom)
        g.add_color_stop_rgba(0.5, *top)
        g.add_color_stop_rgba(1.0, *bottom)
        # пунктирная ось
        cr.set_source_rgba(*rgba(self.pal["primary"], 0.55))
        cr.set_line_width(1)
        cr.set_dash([3, 3])
        cr.move_to(round(mid_x) + 0.5, 4)
        cr.line_to(round(mid_x) + 0.5, h - 4)
        cr.stroke()
        cr.set_dash([])
        cr.set_source(g)
        maxw = w - 12
        for i, v in enumerate(self.vals):
            bw = round(maxw * 0.9 * v ** 1.4 / 2) * 2    # степень — «острее» пики, как у Noctalia
            if bw < 2:
                continue
            off = (i + 0.5) * pitch
            for yc in (mid_y - off, mid_y + off):
                cr.rectangle(round(mid_x - bw / 2), round(yc - bar_h / 2), bw, bar_h)
        cr.fill()
        return True


# ══ Страницы ═════════════════════════════════════════════════════════════
# 30.09.2026, пользователь: боковые кнопки должны открывать СВОИ страницы внутри
# панели, как вкладки Noctalia, а не закрывать её и звать отдельный попап.
# Каждая страница строится при первом открытии (запуск панели не дорожает) и
# опрашивает своё состояние в потоке, только пока она на экране. Страницы с
# длинными списками сидят в ScrolledWindow: высота панели всегда равна высоте
# «Главной» и между вкладками не прыгает.

def lbl(text="", cls=None, xalign=0.0, chars=None):
    w = Gtk.Label(label=text, xalign=xalign)
    for c in (cls or "").split():
        w.get_style_context().add_class(c)
    if chars:
        w.set_ellipsize(Pango.EllipsizeMode.END)
        w.set_max_width_chars(chars)
    return w


def vbox(spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(spacing))


def hbox(spacing=8):
    return Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=sc(spacing))


def tight(box):
    """Карточка с полями поуже (.pcard.tight) — для плотных страниц."""
    box.get_style_context().add_class("tight")
    return box


def card(spacing=8, vertical=True):
    """Карточка страницы — тот же .card, что на «Главной», с полями внутри."""
    box = vbox(spacing) if vertical else hbox(spacing)
    ctx = box.get_style_context()
    ctx.add_class("card")
    ctx.add_class("pcard")
    return box


def text_button(text, cls="act", cb=None, tip=None):
    b = Gtk.Button()
    for c in cls.split():
        b.get_style_context().add_class(c)
    b.add(lbl(text, xalign=0.5))
    if cb:
        b.connect("clicked", lambda _b: cb())
    if tip:
        b.set_tooltip_text(tip)
    return b


def set_cls(widget, cls, on):
    ctx = widget.get_style_context()
    (ctx.add_class if on else ctx.remove_class)(cls)


def clear(box):
    for ch in box.get_children():
        box.remove(ch)
        ch.destroy()


def draw_text(cr, text, px, x, y, color, center=True):
    """Надпись пиксельным шрифтом на cairo; позиция — по целым пикселям,
    иначе PxPlus мылится (память pixel-font-system)."""
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(PIX_FONT)
    fd.set_absolute_size(fs(px) * Pango.SCALE)
    layout.set_font_description(fd)
    layout.set_text(text, -1)
    _ink, log = layout.get_pixel_extents()
    if center:
        x, y = x - log.width / 2, y - log.height / 2
    cr.move_to(round(x), round(y))
    cr.set_source_rgba(*color)
    PangoCairo.show_layout(cr, layout)


def tune(hexcolor, sat=1.0, light=0.0):
    """Тот же оттенок насыщеннее/темнее — как в calendar_popup (выходные)."""
    import colorsys
    c = hexcolor.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, l + light)), max(0.0, min(1.0, s * sat)))
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


class Pill(Gtk.EventBox):
    """Выключатель-«пилюля», нарисованный cairo в цветах палитры.

    Не Gtk.Switch: у того вид зависит от темы GTK, а первый Switch в процессе
    однажды стоил 0,6 с (память settings-app-speed). Колбэк зовётся только от
    щелчка; set_on из опроса его не дёргает."""

    W, H = 44, 24

    def __init__(self, pal, on_toggle):
        super().__init__()
        self.pal, self.cb, self.on = pal, on_toggle, False
        self.area = Gtk.DrawingArea()
        self.area.set_size_request(sc(self.W), sc(self.H))
        self.area.connect("draw", self.draw)
        self.add(self.area)
        self.set_valign(Gtk.Align.CENTER)
        self.set_halign(Gtk.Align.END)
        self.connect("button-press-event", self.click)

    def set_on(self, on):
        if bool(on) != self.on:
            self.on = bool(on)
            self.area.queue_draw()

    def click(self, _w, event):
        if event.button != 1 or not self.get_sensitive():
            return True
        self.set_on(not self.on)
        self.cb(self.on)
        return True

    def draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        dim = not self.get_sensitive()
        rounded(cr, 0.5, 0.5, w - 1, h - 1, (h - 1) / 2)
        if self.on:
            cr.set_source_rgba(*rgba(self.pal["primary"], 0.5 if dim else 1.0))
            cr.fill()
        else:
            cr.set_source_rgba(*rgba(self.pal["surface_high"]))
            cr.fill_preserve()
            cr.set_source_rgba(*rgba(self.pal["primary"], 0.40))
            cr.set_line_width(1)
            cr.stroke()
        r = h / 2 - sc(4)
        cx = w - h / 2 if self.on else h / 2
        cr.arc(cx, h / 2, r, 0, 6.2832)
        cr.set_source_rgba(*rgba(self.pal["on_primary" if self.on else "on_surface_variant"],
                                 0.6 if dim else 1.0))
        cr.fill()
        return True


class Ring(Gtk.DrawingArea):
    """Кольцо-датчик: дуга доли и число в середине пиксельным шрифтом."""

    def __init__(self, pal, size=72, line=6, px=16):
        super().__init__()
        self.pal, self.line, self.px = pal, sc(line), px
        self.frac, self.text, self.warn = 0.0, "…", False
        self.set_size_request(sc(size), sc(size))
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self.draw)

    def set(self, frac, text, warn=False):
        self.frac, self.text, self.warn = max(0.0, min(1.0, frac)), text, warn
        self.queue_draw()

    def draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - self.line / 2 - 1
        cr.set_line_width(self.line)
        cr.arc(cx, cy, r, 0, 6.2832)
        cr.set_source_rgba(*rgba(self.pal["on_surface"], 0.14))
        cr.stroke()
        if self.frac > 0:
            import math
            cr.set_line_cap(1)          # ROUND
            cr.arc(cx, cy, r, -math.pi / 2, -math.pi / 2 + 2 * math.pi * self.frac)
            cr.set_source_rgba(*rgba(self.pal["error" if self.warn else "primary"]))
            cr.stroke()
        draw_text(cr, self.text, self.px, cx, cy, rgba(self.pal["on_surface"]))
        return True


class Bar(Gtk.DrawingArea):
    """Тонкая полоска доли — как прогресс трека в карточке плеера."""

    def __init__(self, pal, height=6):
        super().__init__()
        self.pal, self.frac = pal, 0.0
        self.set_size_request(-1, sc(height))
        self.set_valign(Gtk.Align.CENTER)
        self.set_hexpand(True)
        self.connect("draw", self.draw)

    def set(self, frac):
        self.frac = max(0.0, min(1.0, frac))
        self.queue_draw()

    def draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        rounded(cr, 0, 0, w, h, h / 2)
        cr.set_source_rgba(*rgba(self.pal["on_surface"], 0.14))
        cr.fill()
        if self.frac > 0:
            rounded(cr, 0, 0, max(h, w * self.frac), h, h / 2)
            cr.set_source_rgba(*rgba(self.pal["primary"]))
            cr.fill()
        return True


class Slider(Gtk.Box):
    """Строка «значок-кнопка · шкала · число».

    Пока ползунок тянут (и 1,5 с после), опрос его не двигает, иначе он
    прыгал бы назад к старому значению. Запись — с паузой в движении и в
    потоке: pactl/brightnessctl не должны морозить панель."""

    def __init__(self, icon, icon_off, on_value, on_mute=None, lo=0, hi=100, step=1,
                 delay=60, tip=None):
        super().__init__(spacing=sc(8))
        self.icon, self.icon_off = icon, icon_off
        self.on_value, self.on_mute = on_value, on_mute
        self.delay, self.muted, self.touched, self.timer = delay, False, 0.0, None
        if on_mute:
            self.btn = icon_button(icon, "flat", 16, 22, tip or "Выключить / включить звук")
            self.btn.connect("clicked", lambda _b: self.on_mute(not self.muted))
            self.glyph = self.btn.get_child()
            self.pack_start(self.btn, False, False, 0)
        else:
            self.btn = None
            self.glyph = Glyph(icon, 16, 22)
            self.glyph.get_style_context().add_class("gl-dim")
            box = Gtk.Box()
            box.set_size_request(sc(30), sc(30))
            box.pack_start(self.glyph, True, False, 0)
            self.pack_start(box, False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        self.scale.set_draw_value(False)
        self.scale.set_hexpand(True)
        self.scale.set_valign(Gtk.Align.CENTER)
        self.val = lbl("", "val", 1.0)
        self.val.set_width_chars(4)
        self.pack_start(self.scale, True, True, 0)
        self.pack_start(self.val, False, False, 0)
        self.hid = self.scale.connect("value-changed", self.changed)

    def changed(self, scale):
        v = int(round(scale.get_value()))
        self.val.set_text("%d%%" % v)
        self.touched = time.time()
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(self.delay, self.flush)

    def flush(self):
        self.timer = None
        v = int(round(self.scale.get_value()))
        threading.Thread(target=self.on_value, args=(v,), daemon=True).start()
        return False

    def set_state(self, value, muted=None):
        if value is not None and time.time() - self.touched > 1.5:
            self.scale.handler_block(self.hid)
            self.scale.set_value(value)
            self.scale.handler_unblock(self.hid)
            self.val.set_text("%d%%" % round(value))
        if muted is not None:
            self.muted = muted
            self.glyph.set_char(self.icon_off if muted else self.icon)
            set_cls(self.btn or self.glyph, "muted", muted)


class Page:
    """Страница панели. build() — виджеты, refresh() — опрос состояния.

    Опрос идёт раз в interval мс, пока страница на экране; сами команды —
    в потоках (fetch), в главный поток попадает только готовый результат."""

    interval = 0
    scroll = True

    def __init__(self, cc, key):
        self.cc, self.key, self.pal = cc, key, cc.pal
        self.timer = None
        self.loading = set()
        body = self.build()
        if self.scroll:
            sw = Gtk.ScrolledWindow()
            sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            sw.add(body)
            self.widget = sw
        else:
            self.widget = body

    def build(self):
        return vbox()

    def shown(self):
        self.refresh()
        if self.interval and self.timer is None:
            self.timer = GLib.timeout_add(self.interval, self.tick)

    def tick(self):
        if self.cc.current_key != self.key:
            self.timer = None
            return False
        self.refresh()
        return True

    def refresh(self):
        pass

    def fetch(self, work, done, key="main"):
        if key in self.loading:
            return
        self.loading.add(key)

        def th():
            try:
                res = work()
            except Exception:
                res = None
            GLib.idle_add(self._done, done, res, key)
        threading.Thread(target=th, daemon=True).start()

    def _done(self, done, res, key):
        self.loading.discard(key)
        done(res)
        return False

    def later(self, work, then=None):
        """Действие в потоке, потом (по желанию) функция в главном потоке."""
        def th():
            try:
                res = work()
            except Exception:
                res = None
            if then:
                GLib.idle_add(lambda: (then(res), False)[1])
        threading.Thread(target=th, daemon=True).start()


def switch_row(pal, icon, text, cb, sub=None):
    """Строка «значок · подпись (· пояснение) · пилюля». Возвращает (строка, пилюля)."""
    row = hbox(10)
    g = Glyph(icon, 18, 24)
    g.get_style_context().add_class("gl-acc")
    row.pack_start(g, False, False, 0)
    col = vbox(2)
    col.set_valign(Gtk.Align.CENTER)
    col.pack_start(lbl(text, "name", chars=24), False, False, 0)
    if sub:
        col.pack_start(lbl(sub, "cap", chars=34), False, False, 0)
    row.pack_start(col, True, True, 0)
    pill = Pill(pal, cb)
    row.pack_end(pill, False, False, 0)
    return row, pill


# ── Звук ─────────────────────────────────────────────────────────────────
class SoundPage(Page):
    interval = 1000

    def build(self):
        self.pulse = None
        self.lock = threading.Lock()
        self.sink_idx = self.src_idx = None
        self.dev_rows = {}
        self.app_rows = {}
        box = vbox(10)

        c = card(4)
        self.out_cap = lbl("Выход", "cap", chars=40)
        self.out = Slider(I["vol"], I["vol_off"], self.set_sink_vol, self.set_sink_mute)
        self.mic_cap = lbl("Микрофон", "cap", chars=40)
        self.mic = Slider(I["mic"], I["mic_off"], self.set_src_vol, self.set_src_mute,
                          tip="Выключить / включить микрофон")
        for w in (self.out_cap, self.out, self.mic_cap, self.mic):
            c.pack_start(w, False, False, 0)
        self.mic_cap.set_margin_top(sc(6))
        box.pack_start(c, False, False, 0)

        c = card(4)
        c.pack_start(lbl("Устройство вывода", "cap"), False, False, 0)
        self.dev_box = vbox(2)
        c.pack_start(self.dev_box, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(6)
        c.pack_start(lbl("Программы", "cap"), False, False, 0)
        self.app_box = vbox(6)
        self.app_empty = lbl("Сейчас ничего не звучит", "dim")
        c.pack_start(self.app_box, False, False, 0)
        c.pack_start(self.app_empty, False, False, 0)
        box.pack_start(c, False, False, 0)
        return box

    # pulsectl не потокобезопасен: одно соединение, все вызовы — под замком.
    def pa(self):
        if self.pulse is None:
            import pulsectl
            self.pulse = pulsectl.Pulse("jarvis-control-center")
        return self.pulse

    def call(self, fn):
        def th():
            with self.lock:
                try:
                    fn(self.pa())
                except Exception:
                    self.pulse = None
        threading.Thread(target=th, daemon=True).start()

    def snapshot(self):
        from audio_names import stream_name
        with self.lock:
            try:
                p = self.pa()
                srv = p.server_info()
                sinks, sources, inputs = p.sink_list(), p.source_list(), p.sink_input_list()
            except Exception:
                self.pulse = None
                raise

        def desc(d):
            s = d.description or d.name
            for tail in (" Analog Stereo", " Digital Stereo (HDMI)", " Stereo"):
                s = s.replace(tail, "")
            # «Razer … (микрофон, громкость закреплена)» — пояснение в скобках
            # не помещается и ничего не даёт.
            return s.split(" (")[0].strip() or s
        out = {"sinks": [], "sink": None, "src": None, "apps": {}}
        for s in sinks:
            item = {"name": s.name, "desc": desc(s), "idx": s.index,
                    "vol": s.volume.value_flat, "mute": bool(s.mute)}
            out["sinks"].append(item)
            if s.name == srv.default_sink_name:
                out["sink"] = item
        mics = [s for s in sources if not s.name.endswith(".monitor")]
        for s in mics:
            if s.name == srv.default_source_name:
                out["src"] = {"desc": desc(s), "idx": s.index,
                              "vol": s.volume.value_flat, "mute": bool(s.mute)}
        if out["src"] is None and mics:
            s = mics[0]
            out["src"] = {"desc": desc(s), "idx": s.index,
                          "vol": s.volume.value_flat, "mute": bool(s.mute)}
        # Те же правила, что в volume_popup: без системных звуков, без
        # «приостановленных» потоков (corked — открыт, но молчит) и по строке
        # на программу, а не на поток.
        for inp in inputs:
            pl = inp.proplist
            if pl.get("media.role") == "event":
                continue
            if str(pl.get("pulse.corked", "")).lower() == "true":
                continue
            if any("blanket" in str(pl.get(f, "")).lower()
                   for f in ("application.name", "application.process.binary", "media.name")):
                continue
            name = stream_name(pl)
            g = out["apps"].setdefault(name, {"idx": [], "vol": 0.0, "mute": True, "icons": []})
            g["idx"].append(inp.index)
            g["vol"] = max(g["vol"], inp.volume.value_flat)
            g["mute"] = g["mute"] and bool(inp.mute)
            for k in ("application.icon_name", "application.process.binary"):
                if pl.get(k):
                    g["icons"].append(pl[k].lower())
            g["icons"].append(name.lower().replace(" ", ""))
        return out

    def refresh(self):
        self.fetch(self.snapshot, self.apply)

    def apply(self, st):
        if st is None:
            self.out_cap.set_text("PipeWire не отвечает")
            return
        sink = st["sink"]
        if sink:
            self.sink_idx = sink["idx"]
            self.out_cap.set_text("Выход · " + sink["desc"])
            self.out.set_state(sink["vol"] * 100, sink["mute"])
        src = st["src"]
        self.mic.set_sensitive(src is not None)
        if src:
            self.src_idx = src["idx"]
            self.mic_cap.set_text("Микрофон · " + src["desc"])
            self.mic.set_state(src["vol"] * 100, src["mute"])

        names = [s["name"] for s in st["sinks"]]
        if names != list(self.dev_rows):
            clear(self.dev_box)
            self.dev_rows = {}
            for s in st["sinks"]:
                b = Gtk.Button()
                b.get_style_context().add_class("row")
                row = hbox(10)
                g = Glyph(I["radio_off"], 16, 22)
                row.pack_start(g, False, False, 0)
                row.pack_start(lbl(s["desc"], "name", chars=30), True, True, 0)
                b.add(row)
                b.connect("clicked", lambda _b, n=s["name"]: self.set_default(n))
                self.dev_box.pack_start(b, False, False, 0)
                self.dev_rows[s["name"]] = (b, g)
            self.dev_box.show_all()
        for name, (b, g) in self.dev_rows.items():
            cur = sink is not None and name == sink["name"]
            set_cls(b, "cur", cur)
            g.set_char(I["radio_on"] if cur else I["radio_off"])

        apps = st["apps"]
        if list(apps) != list(self.app_rows):
            clear(self.app_box)
            self.app_rows = {}
            for name, g in apps.items():
                row = hbox(8)
                row.pack_start(self.app_icon(g["icons"]), False, False, 0)
                nl = lbl(name, "name", chars=9)
                nl.set_width_chars(9)          # шкалы всех программ — ровно друг под другом
                row.pack_start(nl, False, False, 0)
                sl = Slider(I["vol"], I["vol_off"], lambda v, n=name: self.set_app_vol(n, v),
                            lambda m, n=name: self.set_app_mute(n, m))
                row.pack_start(sl, True, True, 0)
                self.app_box.pack_start(row, False, False, 0)
                self.app_rows[name] = [sl, g["idx"]]
            self.app_box.show_all()
        for name, g in apps.items():
            self.app_rows[name][1] = g["idx"]
            self.app_rows[name][0].set_state(g["vol"] * 100, g["mute"])
        self.app_empty.set_visible(not apps)

    def app_icon(self, names):
        theme = Gtk.IconTheme.get_default()
        img = None
        for n in names:
            if n and theme.has_icon(n):
                img = Gtk.Image.new_from_icon_name(n, Gtk.IconSize.BUTTON)
                break
        if img is None:
            # Значка с именем программы в теме нет (Zen — «app.zen_browser.zen»):
            # ищем её .desktop и берём значок оттуда.
            import warnings
            from gi.repository import Gio
            warnings.filterwarnings("ignore", category=DeprecationWarning)   # Gio → GioUnix
            for n in names:
                for group in (Gio.DesktopAppInfo.search(n) if n else []):
                    info = Gio.DesktopAppInfo.new(group[0]) if group else None
                    icon = info.get_icon() if info else None
                    if icon is not None:
                        img = Gtk.Image.new_from_gicon(icon, Gtk.IconSize.BUTTON)
                        break
                if img is not None:
                    break
        if img is not None:
            img.set_pixel_size(sc(22))
            img.set_size_request(sc(30), sc(30))
            return img
        g = Glyph(I["app"], 18, 30)
        g.get_style_context().add_class("gl-dim")
        return g

    # запись
    def set_sink_vol(self, v):
        idx = self.sink_idx
        if idx is not None:
            self.call(lambda p: p.volume_set_all_chans(p.sink_info(idx), v / 100))

    def set_sink_mute(self, m):
        idx = self.sink_idx
        self.out.set_state(None, m)
        if idx is not None:
            self.call(lambda p: p.mute(p.sink_info(idx), m))

    def set_src_vol(self, v):
        idx = self.src_idx
        if idx is not None:
            self.call(lambda p: p.volume_set_all_chans(p.source_info(idx), v / 100))

    def set_src_mute(self, m):
        idx = self.src_idx
        self.mic.set_state(None, m)
        if idx is not None:
            self.call(lambda p: p.mute(p.source_info(idx), m))

    def set_app_vol(self, name, v):
        ids = list(self.app_rows.get(name, [None, []])[1])

        def fn(p):
            for i in ids:
                # поток мог закончиться, пока панель открыта — остальные двигаем
                try:
                    p.volume_set_all_chans(p.sink_input_info(i), v / 100)
                except Exception:
                    pass
        self.call(fn)

    def set_app_mute(self, name, m):
        row = self.app_rows.get(name)
        if not row:
            return
        row[0].set_state(None, m)
        ids = list(row[1])

        def fn(p):
            for i in ids:
                try:
                    p.mute(p.sink_input_info(i), m)
                except Exception:
                    pass
        self.call(fn)

    def set_default(self, name):
        for n, (b, g) in self.dev_rows.items():
            set_cls(b, "cur", n == name)
            g.set_char(I["radio_on"] if n == name else I["radio_off"])
        self.later(lambda: run("pactl", "set-default-sink", name), lambda _r: self.refresh())


# ── Система ──────────────────────────────────────────────────────────────
def read_cpu():
    with open("/proc/stat") as f:
        v = [int(x) for x in f.readline().split()[1:]]
    idle = v[3] + (v[4] if len(v) > 4 else 0)
    return sum(v), idle


def cpu_temp():
    """Температура пакета CPU: hwmon coretemp (Package id 0), иначе x86_pkg_temp."""
    import glob
    for d in glob.glob("/sys/class/hwmon/hwmon*"):
        try:
            with open(d + "/name") as f:
                if f.read().strip() not in ("coretemp", "k10temp", "zenpower"):
                    continue
            with open(d + "/temp1_input") as f:
                return int(f.read()) / 1000
        except (OSError, ValueError):
            continue
    for z in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            with open(z + "/type") as f:
                if f.read().strip() == "x86_pkg_temp":
                    with open(z + "/temp") as t:
                        return int(t.read()) / 1000
        except (OSError, ValueError):
            continue
    return None


def gib(kb):
    return "%.1f ГиБ" % (kb / 1048576.0) if kb >= 1048576 * 0.95 else "%d МиБ" % (kb / 1024)


class SystemPage(Page):
    interval = 1500

    def build(self):
        self.prev_cpu = None
        self.mem_mod = None
        self.mem_tick = 0
        box = vbox(10)

        c = card(6)
        rings = Gtk.Box(spacing=sc(6), homogeneous=True)
        self.gauges = {}
        disks = [("/", "Диск /")]
        try:
            if os.stat("/home").st_dev != os.stat("/").st_dev:
                disks.append(("/home", "/home"))
        except OSError:
            pass
        self.disks = disks
        items = [("cpu", "Процессор"), ("mem", "Память"), ("temp", "Темп.")] + \
                [("disk:" + p, t) for p, t in disks]
        for key, title in items:
            col = vbox(4)
            ring = Ring(self.pal, 72, 6, 16)
            col.pack_start(ring, False, False, 0)
            col.pack_start(lbl(title, "cap", 0.5), False, False, 0)
            sub = lbl("", "dim", 0.5, chars=10)
            col.pack_start(sub, False, False, 0)
            rings.pack_start(col, True, True, 0)
            self.gauges[key] = (ring, sub)
        c.pack_start(rings, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(6)
        c.pack_start(lbl("Больше всего памяти", "cap"), False, False, 0)
        grid = Gtk.Grid(column_spacing=sc(10), row_spacing=sc(6))
        self.top = []
        for i in range(5):
            n, b, v = lbl("", "name", chars=12), Bar(self.pal), lbl("", "val", 1.0)
            n.set_width_chars(12)
            v.set_width_chars(8)
            grid.attach(n, 0, i, 1, 1)
            grid.attach(b, 1, i, 1, 1)
            grid.attach(v, 2, i, 1, 1)
            self.top.append((n, b, v))
        c.pack_start(grid, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(10, vertical=False)
        info = Gtk.Grid(column_spacing=sc(12), row_spacing=sc(4))
        self.lbl_uptime = lbl(fmt_uptime(), "cap-hi")
        rows = (("Ядро", lbl(os.uname().release, "cap-hi", chars=20)),
                ("niri", lbl(self.cc.niri_ver.replace("niri ", ""), "cap-hi", chars=20)),
                ("Работает", self.lbl_uptime))
        for i, (k, w) in enumerate(rows):
            info.attach(lbl(k, "cap"), 0, i, 1, 1)
            info.attach(w, 1, i, 1, 1)
        c.pack_start(info, True, True, 0)
        more = text_button("Подробнее", "act", lambda: self.cc.launch(("kitty", "--title", "btop", "btop")),
                           "btop в терминале")
        more.set_valign(Gtk.Align.CENTER)
        c.pack_end(more, False, False, 0)
        box.pack_start(c, False, False, 0)
        return box

    def stats(self):
        now = read_cpu()
        if self.prev_cpu is None:
            time.sleep(0.25)
            prev, now = now, read_cpu()
        else:
            prev = self.prev_cpu
        self.prev_cpu = now
        dt, di = now[0] - prev[0], now[1] - prev[1]
        cpu = 100.0 * (1 - di / dt) if dt > 0 else 0.0
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                mem[k] = int(v.split()[0])
        disks = []
        for path, _t in self.disks:
            st = os.statvfs(path)
            total = st.f_blocks * st.f_frsize
            free = st.f_bavail * st.f_frsize
            used = total - st.f_bfree * st.f_frsize
            disks.append((used / max(1, used + free), used, total))
        return cpu, mem, cpu_temp(), disks

    def top_apps(self):
        import collections
        import importlib.machinery
        import importlib.util
        if self.mem_mod is None:
            # appmem — файл без расширения; грузится так же, как в appmem_popup.
            path = os.path.expanduser("~/.local/bin/appmem")
            loader = importlib.machinery.SourceFileLoader("appmem", path)
            spec = importlib.util.spec_from_loader("appmem", loader)
            mod = importlib.util.module_from_spec(spec)
            loader.exec_module(mod)
            self.mem_mod = mod
        m = self.mem_mod
        now = m.scan()
        by = collections.Counter()
        for pid, p in now.items():
            by[m.label_of(p, now)] += m.pss_kb(pid)[0]
        return by.most_common(5)

    def refresh(self):
        self.fetch(self.stats, self.apply)
        # Память по программам — дороже (≈0,1 с): раз в два опроса.
        if self.mem_tick % 2 == 0:
            self.fetch(self.top_apps, self.apply_top, key="top")
        self.mem_tick += 1
        self.lbl_uptime.set_text(fmt_uptime())

    def apply(self, res):
        if not res:
            return
        cpu, mem, temp, disks = res
        ring, sub = self.gauges["cpu"]
        ring.set(cpu / 100, "%d%%" % round(cpu), cpu >= 90)
        sub.set_text("%d ядер" % (os.cpu_count() or 1))
        total, avail = mem.get("MemTotal", 1), mem.get("MemAvailable", 0)
        ring, sub = self.gauges["mem"]
        ring.set((total - avail) / total, "%d%%" % round(100 * (total - avail) / total),
                 avail / total < 0.08)
        sub.set_text("%.1f/%.0f Г" % ((total - avail) / 1048576, total / 1048576))
        ring, sub = self.gauges["temp"]
        if temp is None:
            ring.set(0, "—")
            sub.set_text("")
        else:
            ring.set(temp / 100, "%d°" % round(temp), temp >= 85)
            sub.set_text("пакет CPU")
        for (path, _t), (frac, used, tot) in zip(self.disks, disks):
            ring, sub = self.gauges["disk:" + path]
            ring.set(frac, "%d%%" % round(frac * 100), frac >= 0.92)
            sub.set_text("%d/%d Г" % (used / 1e9, tot / 1e9))

    def apply_top(self, top):
        if not top:
            return
        biggest = top[0][1] or 1
        for (n, b, v), item in zip(self.top, top + [None] * 5):
            if item is None:
                n.set_text("")
                v.set_text("")
                b.set(0)
                continue
            n.set_text(item[0])
            b.set(item[1] / biggest)
            v.set_text(gib(item[1]))


# ── Wi-Fi ────────────────────────────────────────────────────────────────
def nmcli(*args, timeout=45):
    """(успех, текст) — как в wifi_popup: stderr нужен, в нём ошибка NM."""
    try:
        r = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, "истекло время ожидания"
    except OSError as e:
        return False, str(e)


def wifi_state():
    """Радио, видимые сети (без пересканирования) и сохранённые профили.
    Разбор строк nmcli — из wifi_popup.list_networks: SSID с «\\:» и одна
    строка на имя (самая сильная точка доступа)."""
    import re
    on = run("nmcli", "radio", "wifi") == "enabled"
    known = set()
    ok, out = nmcli("-t", "-f", "NAME,TYPE", "connection", "show", timeout=5)
    for line in out.splitlines() if ok else ():
        name, _, kind = line.rpartition(":")
        if kind == "802-11-wireless":
            known.add(name.replace("\\:", ":"))
    nets = {}
    if on:
        ok, out = nmcli("-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list",
                        "--rescan", "no", timeout=5)
        for line in out.splitlines() if ok else ():
            parts = [p.replace("\\:", ":") for p in re.split(r"(?<!\\):", line)]
            if len(parts) < 4 or not parts[1]:
                continue
            try:
                sig = int(parts[2])
            except ValueError:
                sig = 0
            ssid, use = parts[1], parts[0] == "*"
            cur = nets.get(ssid)
            if cur is None or sig > cur["signal"]:
                nets[ssid] = {"ssid": ssid, "signal": sig,
                              "secured": bool(parts[3]) and parts[3] != "--",
                              "in_use": use or bool(cur and cur["in_use"])}
            elif use:
                cur["in_use"] = True
    order = sorted(nets.values(), key=lambda n: (not n["in_use"], -n["signal"], n["ssid"].lower()))
    return on, order[:14], known


def wifi_iface():
    ok, out = nmcli("-t", "-f", "DEVICE,TYPE", "device", timeout=5)
    for line in out.splitlines() if ok else ():
        dev, _, kind = line.rpartition(":")
        if kind == "wifi":
            return dev
    return None


def sig_glyph(sig):
    return I["w4"] if sig >= 75 else I["w3"] if sig >= 50 else I["w2"] if sig >= 25 else I["w1"]


class WifiPage(Page):
    interval = 4000

    def build(self):
        self.rows = {}
        self.nets = {}
        self.known = set()
        self.open_ssid = None
        self.busy = False
        box = vbox(10)

        c = card(6)
        top = hbox(10)
        self.head_glyph = Glyph(I["wifi"], 20, 26)
        self.head_glyph.get_style_context().add_class("gl-acc")
        top.pack_start(self.head_glyph, False, False, 0)
        col = vbox(2)
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(lbl("Wi-Fi", "name"), False, False, 0)
        self.cur = lbl("…", "cap", chars=30)
        col.pack_start(self.cur, False, False, 0)
        top.pack_start(col, True, True, 0)
        self.pill = Pill(self.pal, self.toggle)
        top.pack_end(self.pill, False, False, 0)
        self.scan_btn = icon_button(I["refresh"], "flat", 16, 22, "Искать сети заново")
        self.scan_btn.set_valign(Gtk.Align.CENTER)
        self.scan_btn.connect("clicked", lambda _b: self.rescan())
        top.pack_end(self.scan_btn, False, False, 0)
        c.pack_start(top, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(4)
        c.pack_start(lbl("Сети рядом", "cap"), False, False, 0)
        self.list = vbox(2)
        c.pack_start(self.list, False, False, 0)
        self.empty = lbl("Ищу сети…", "dim")
        c.pack_start(self.empty, False, False, 0)
        box.pack_start(c, False, False, 0)
        return box

    def refresh(self):
        self.fetch(wifi_state, self.apply)

    def apply(self, res):
        if res is None:
            self.cur.set_text("nmcli не ответил — NetworkManager запущен?")
            return
        on, nets, known = res
        self.known = known
        self.pill.set_on(on)
        self.scan_btn.set_sensitive(on)
        self.head_glyph.set_char(I["wifi"] if on else I["wifi_off"])
        self.nets = {n["ssid"]: n for n in nets}
        conn = next((n for n in nets if n["in_use"]), None)
        if not on:
            self.cur.set_text("Выключен")
        elif conn:
            self.cur.set_text("%s · %d%%" % (conn["ssid"], conn["signal"]))
        else:
            self.cur.set_text("Не подключено")
        order = [n["ssid"] for n in nets]
        # Пока под строкой открыто поле пароля, список не перестраивается:
        # иначе набранное пропало бы на следующем опросе.
        if order != list(self.rows) and self.open_ssid is None:
            clear(self.list)
            self.rows = {}
            for n in nets:
                self.rows[n["ssid"]] = self.make_row(n)
            self.list.show_all()
            for r in self.rows.values():
                r["rev"].set_reveal_child(False)
        for ssid, r in self.rows.items():
            n = self.nets.get(ssid)
            if n:
                self.update_row(r, n)
        self.empty.set_visible(not self.rows)
        self.empty.set_text("Wi-Fi выключен" if not on else "Сетей не видно — нажмите поиск")
        self.list.set_visible(on)

    def make_row(self, n):
        r = {"ssid": n["ssid"]}
        b = Gtk.Button()
        b.get_style_context().add_class("row")
        row = hbox(10)
        r["sig"] = Glyph(sig_glyph(n["signal"]), 16, 22)
        row.pack_start(r["sig"], False, False, 0)
        row.pack_start(lbl(n["ssid"], "name", chars=20), True, True, 0)
        r["tail"] = lbl("", "cap", 1.0)
        row.pack_start(r["tail"], False, False, 0)
        r["lock"] = Glyph(I["lock"], 14, 20)
        r["lock"].get_style_context().add_class("gl-dim")
        row.pack_start(r["lock"], False, False, 0)
        b.add(row)
        b.connect("clicked", lambda _b: self.on_row(r["ssid"]))
        r["btn"] = b
        r["rev"] = Gtk.Revealer()
        r["rev"].set_transition_duration(150)
        r["detail"] = hbox(8)
        r["detail"].set_margin_start(sc(8))
        r["detail"].set_margin_end(sc(8))
        r["detail"].set_margin_top(sc(4))
        r["detail"].set_margin_bottom(sc(6))
        r["rev"].add(r["detail"])
        self.list.pack_start(b, False, False, 0)
        self.list.pack_start(r["rev"], False, False, 0)
        return r

    def update_row(self, r, n):
        r["sig"].set_char(sig_glyph(n["signal"]))
        set_cls(r["btn"], "cur", n["in_use"])
        r["tail"].set_text("подключено" if n["in_use"] else ("%d%%" % n["signal"]))
        # Место под замок есть всегда (пустой глиф) — проценты стоят столбиком.
        need_pw = n["secured"] and n["ssid"] not in self.known
        r["lock"].set_char(I["lock"] if need_pw else "")

    def detail(self, r, widgets, msg=""):
        clear(r["detail"])
        for w in widgets:
            r["detail"].pack_start(w, w is widgets[0] and isinstance(w, Gtk.Entry), True, 0)
        r["msg"] = lbl(msg, "cap", chars=18)
        r["detail"].pack_end(r["msg"], True, True, 0)
        r["detail"].show_all()
        for other in self.rows.values():
            if other is not r:
                other["rev"].set_reveal_child(False)
        r["rev"].set_reveal_child(True)
        self.open_ssid = r["ssid"]

    def close_detail(self):
        for r in self.rows.values():
            r["rev"].set_reveal_child(False)
        self.open_ssid = None

    def on_row(self, ssid):
        r, n = self.rows.get(ssid), self.nets.get(ssid)
        if not r or not n or self.busy:
            return
        if self.open_ssid == ssid:
            self.close_detail()
            return
        if n["in_use"]:
            self.detail(r, [text_button("Отключиться", "act", lambda: self.disconnect(r))])
        elif n["secured"] and ssid not in self.known:
            entry = Gtk.Entry()
            entry.get_style_context().add_class("pw")
            entry.set_visibility(False)
            entry.set_placeholder_text("Пароль")
            entry.set_width_chars(14)
            entry.connect("activate", lambda e: self.connect_to(r, e.get_text()))
            self.detail(r, [entry, text_button("Подключить", "act go",
                                               lambda: self.connect_to(r, entry.get_text()))])
            entry.grab_focus()
        else:
            self.detail(r, [], "Подключение…")
            self.connect_to(r, None)

    def set_msg(self, r, text, err=False):
        if "msg" in r:
            r["msg"].set_text(text)
            set_cls(r["msg"], "bad", err)

    def connect_to(self, r, pw):
        ssid = r["ssid"]
        if pw is not None and not pw:
            self.set_msg(r, "Введите пароль", True)
            return
        self.busy = True
        self.set_msg(r, "Подключение…")

        def work():
            if ssid in self.known:
                return nmcli("connection", "up", "id", ssid)
            if pw:
                return nmcli("device", "wifi", "connect", ssid, "password", pw)
            return nmcli("device", "wifi", "connect", ssid)
        self.later(work, lambda res: self.finished(r, res, "Подключено"))

    def disconnect(self, r):
        self.busy = True
        self.set_msg(r, "Отключение…")

        def work():
            dev = wifi_iface()
            return nmcli("device", "disconnect", dev) if dev else (False, "нет Wi-Fi адаптера")
        self.later(work, lambda res: self.finished(r, res, "Отключено"))

    def finished(self, r, res, ok_text):
        self.busy = False
        ok, out = res or (False, "")
        if ok:
            self.set_msg(r, ok_text)
            GLib.timeout_add(900, lambda: (self.close_detail(), self.refresh(), False)[2])
        else:
            line = (out.splitlines() or ["не удалось"])[-1]
            self.set_msg(r, line.replace("Error: ", ""), True)

    def toggle(self, on):
        self.cur.set_text("Включаю…" if on else "Выключаю…")
        self.later(lambda: run("nmcli", "radio", "wifi", "on" if on else "off", timeout=8),
                   lambda _r: GLib.timeout_add(1200, lambda: (self.refresh(), False)[1]))

    def rescan(self):
        self.scan_btn.set_sensitive(False)
        self.empty.set_text("Ищу сети…")
        # `list --rescan yes` ждёт конца поиска (≈3 с) — в потоке.
        self.later(lambda: nmcli("-t", "-f", "SSID", "device", "wifi", "list", "--rescan", "yes",
                                 timeout=20),
                   lambda _r: (self.scan_btn.set_sensitive(True), self.refresh()))


# ── Bluetooth ────────────────────────────────────────────────────────────
def bt(*args, timeout=45):
    """bluetoothctl → (успех, текст); как в bluetooth_popup: код возврата
    у него не всегда честный, неудача — ещё и по «Failed» в выводе."""
    try:
        r = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout)
        out = (r.stdout + r.stderr).strip()
        return r.returncode == 0 and "Failed" not in out and "not available" not in out, out
    except subprocess.TimeoutExpired:
        return False, "истекло время ожидания"
    except OSError as e:
        return False, str(e)


def bt_state():
    _ok, show = bt("show", timeout=5)
    powered = "Powered: yes" in show
    alias = ""
    for line in show.splitlines():
        if line.strip().startswith("Alias:"):
            alias = line.split(":", 1)[1].strip()
    ok, out = bt("devices", timeout=8)
    devs = []
    for line in out.splitlines() if ok else ():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        mac, name = parts[1], parts[2]
        _i, info = bt("info", mac, timeout=8)
        kind = batt = ""
        for l in info.splitlines():
            l = l.strip()
            if l.startswith("Icon:"):
                kind = l.split(":", 1)[1].strip()
            elif l.startswith("Battery Percentage:") and "(" in l:
                batt = l.split("(", 1)[1].rstrip(")").strip()
        devs.append({"mac": mac, "name": name, "conn": "Connected: yes" in info,
                     "pair": "Paired: yes" in info, "kind": kind, "batt": batt})
    devs.sort(key=lambda d: (not d["conn"], not d["pair"], d["name"].lower()))
    return powered, alias, devs[:12]


def dev_glyph(kind):
    k = (kind or "").lower()
    for keys, g in ((("headset", "headphone", "audio"), "headphones"), (("mouse",), "mouse"),
                    (("keyboard",), "keyboard"), (("phone",), "phone"),
                    (("computer",), "laptop"), (("watch",), "watch")):
        if any(x in k for x in keys):
            return I[g]
    return I["bt"]


class BluetoothPage(Page):
    interval = 3000

    def build(self):
        self.rows = {}
        self.powered = False
        self.busy = False
        self.scanning = False
        box = vbox(10)

        c = card(6)
        top = hbox(10)
        self.head_glyph = Glyph(I["bt"], 20, 26)
        self.head_glyph.get_style_context().add_class("gl-acc")
        top.pack_start(self.head_glyph, False, False, 0)
        col = vbox(2)
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(lbl("Bluetooth", "name"), False, False, 0)
        self.status = lbl("…", "cap", chars=30)
        col.pack_start(self.status, False, False, 0)
        top.pack_start(col, True, True, 0)
        self.pill = Pill(self.pal, self.toggle)
        top.pack_end(self.pill, False, False, 0)
        self.scan_btn = icon_button(I["magnify"], "flat", 16, 22, "Искать новые устройства (8 с)")
        self.scan_btn.set_valign(Gtk.Align.CENTER)
        self.scan_btn.connect("clicked", lambda _b: self.scan())
        top.pack_end(self.scan_btn, False, False, 0)
        c.pack_start(top, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(4)
        c.pack_start(lbl("Устройства", "cap"), False, False, 0)
        self.list = vbox(10)
        c.pack_start(self.list, False, False, 0)
        self.empty = lbl("Нет сопряжённых устройств", "dim")
        c.pack_start(self.empty, False, False, 0)
        box.pack_start(c, False, False, 0)
        return box

    def refresh(self):
        self.fetch(bt_state, self.apply)

    def apply(self, res):
        if res is None:
            self.status.set_text("bluetoothctl не ответил")
            return
        powered, alias, devs = res
        self.powered = powered
        self.pill.set_on(powered)
        self.scan_btn.set_sensitive(powered and not self.scanning)
        self.head_glyph.set_char(I["bt"] if powered else I["bt_off"])
        if not self.busy:
            n = sum(d["conn"] for d in devs)
            self.status.set_text(("Включён · " + alias + (" · подключено: %d" % n if n else ""))
                                 if powered else "Выключен")
        macs = [d["mac"] for d in devs]
        if macs != list(self.rows):
            clear(self.list)
            self.rows = {}
            for d in devs:
                self.rows[d["mac"]] = self.make_row(d)
            self.list.show_all()
        for d in devs:
            self.update_row(self.rows[d["mac"]], d)
        self.empty.set_visible(not devs)

    def make_row(self, d):
        r = {"mac": d["mac"]}
        row = hbox(10)
        r["box"] = row
        r["glyph"] = Glyph(dev_glyph(d["kind"]), 18, 26)
        row.pack_start(r["glyph"], False, False, 0)
        col = vbox(2)
        col.set_valign(Gtk.Align.CENTER)
        col.pack_start(lbl(d["name"], "name", chars=18), False, False, 0)
        r["sub"] = lbl("", "cap", chars=24)
        col.pack_start(r["sub"], False, False, 0)
        row.pack_start(col, True, True, 0)
        r["act"] = text_button("…", "act", lambda: self.act(r))
        r["act"].set_valign(Gtk.Align.CENTER)
        row.pack_end(r["act"], False, False, 0)
        self.list.pack_start(row, False, False, 0)
        return r

    def update_row(self, r, d):
        r["dev"] = d
        set_cls(r["glyph"], "gl-acc", d["conn"])
        parts = ["подключено" if d["conn"] else ("сопряжено" if d["pair"] else "найдено")]
        if d["batt"]:
            parts.append("заряд %s%%" % d["batt"])
        if not r.get("msg"):
            r["sub"].set_text(" · ".join(parts))
        r["act"].get_child().set_text("Отключить" if d["conn"] else
                                      ("Подключить" if d["pair"] else "Сопрячь"))
        set_cls(r["act"], "go", not d["conn"])
        r["act"].set_sensitive(self.powered and not self.busy)

    def act(self, r):
        d = r.get("dev")
        if not d or self.busy:
            return
        self.busy = True
        mac = d["mac"]
        for x in self.rows.values():
            x["act"].set_sensitive(False)
        r["msg"] = True
        r["sub"].set_text("Отключение…" if d["conn"] else "Подключение…")

        def work():
            if d["conn"]:
                return bt("disconnect", mac)
            if not d["pair"]:
                ok, out = bt("pair", mac)
                if not ok:
                    return ok, out
                bt("trust", mac, timeout=10)
            return bt("connect", mac)

        def done(res):
            self.busy = False
            ok, out = res or (False, "")
            r["msg"] = False
            if not ok:
                lines = [l for l in out.splitlines() if "Failed" in l or "Error" in l]
                r["msg"] = True
                r["sub"].set_text((lines[-1] if lines else "не удалось").strip())
                set_cls(r["sub"], "bad", True)
                GLib.timeout_add(4000, lambda: (r.update(msg=False), set_cls(r["sub"], "bad", False),
                                                False)[2])
            self.refresh()
        self.later(work, done)

    def toggle(self, on):
        self.status.set_text("Включаю…" if on else "Выключаю…")
        self.busy = True

        def work():
            if on:
                # Сначала снять блокировку rfkill: у заблокированного адаптера
                # power on молча не срабатывает (см. bluetooth_popup).
                run("rfkill", "unblock", "bluetooth", timeout=10)
                for _ in range(6):
                    ok, _out = bt("power", "on", timeout=10)
                    if ok:
                        break
                    time.sleep(0.3)
            else:
                bt("power", "off", timeout=10)
                run("rfkill", "block", "bluetooth", timeout=10)

        def done(_r):
            self.busy = False
            self.refresh()
        self.later(work, done)

    def scan(self):
        if not self.powered or self.scanning:
            return
        self.scanning = True
        self.scan_btn.set_sensitive(False)
        self.status.set_text("Поиск устройств…")

        def done(_r):
            self.scanning = False
            self.refresh()
        self.later(lambda: bt("--timeout", "8", "scan", "on", timeout=25), done)
        # найденное подтягивается обычным опросом, пока идёт поиск


# ── Питание ──────────────────────────────────────────────────────────────
def backlight():
    import glob
    for d in glob.glob("/sys/class/backlight/*"):
        try:
            with open(d + "/brightness") as f:
                cur = int(f.read())
            with open(d + "/max_brightness") as f:
                mx = int(f.read())
            return round(100 * cur / mx) if mx else None
        except (OSError, ValueError):
            continue
    return None


class PowerPage(Page):
    interval = 3000

    def build(self):
        # Плотнее остальных страниц (08.10, «чуть компактнее»): промежутки 6,
        # карточки .tight, кольцо 60 — иначе с третьим ползунком не влезало.
        box = vbox(6)
        self.bl_lock = threading.Lock()
        self.mon_proc = None
        self.mon_pending = None
        self.mon_timer = None

        c = tight(card(12, vertical=False))
        self.ring = Ring(self.pal, 60, 5, 16)
        c.pack_start(self.ring, False, False, 0)
        col = vbox(4)
        col.set_valign(Gtk.Align.CENTER)
        self.bat_status = lbl("…", "big")
        self.bat_sub = lbl("", "cap", chars=40)
        for w in (self.bat_status, self.bat_sub):
            col.pack_start(w, False, False, 0)
        c.pack_start(col, True, True, 0)
        box.pack_start(c, False, False, 0)

        c = tight(card(8))
        segs = Gtk.Box(spacing=sc(8), homogeneous=True)
        self.segs = {}
        for p in PROFILES:
            name, ic = PROFILE_NAME[p]
            b = Gtk.Button()
            b.get_style_context().add_class("seg")
            inner = hbox(8)
            inner.set_halign(Gtk.Align.CENTER)
            inner.pack_start(Glyph(I[ic], 16, 22), False, False, 0)
            inner.pack_start(lbl(name, "seg-label"), False, False, 0)
            b.add(inner)
            b.connect("clicked", lambda _b, p=p: self.set_profile(p))
            b.set_tooltip_text("Профиль питания: " + name.lower())
            segs.pack_start(b, True, True, 0)
            self.segs[p] = b
        c.pack_start(segs, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = tight(card(4))
        self.bright = Slider(I["bright"], I["bright"], self.set_bright, lo=5, hi=100, step=5,
                             delay=80)
        self.bright.set_tooltip_text("Яркость экрана ноутбука")
        c.pack_start(self.bright, False, False, 0)
        # MSI по DDC: строка появляется, только когда монитор подключён
        # (как в «Энергии»); значение — сразу из запомненного, уточняется в фоне.
        self.mon_rev = Gtk.Revealer()
        self.mon = Slider(I["monitor"], I["monitor"], self.set_mon, lo=0, hi=100, step=5, delay=200)
        self.mon.set_tooltip_text("Яркость монитора MSI (DDC)")
        self.mon.set_margin_top(sc(4))
        self.mon_rev.add(self.mon)
        c.pack_start(self.mon_rev, False, False, 0)
        # Теплота ночного света — третьей строкой, только пока он включён
        # (08.10, просьба пользователя). Тот же night_mode.py on N, что у ПКМ плитки.
        self.warm_rev = Gtk.Revealer()
        self.warm = Slider(I["night"], I["night"], self.set_warmth, lo=0, hi=100, step=5,
                           delay=200)
        self.warm.set_tooltip_text("Теплота ночного света")
        self.warm.set_margin_top(sc(4))
        self.warm_rev.add(self.warm)
        c.pack_start(self.warm_rev, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = tight(card(4))
        row, self.night = switch_row(self.pal, I["night"], "Ночной свет", self.set_night,
                                     "вручную — до 22:00 / 5:00")
        c.pack_start(row, False, False, 0)
        row, self.savage = switch_row(self.pal, I["perf"], "Savage Mode", self.set_savage,
                                      "без сна, машина всегда бодрая")
        c.pack_start(row, False, False, 0)
        # Спутник Savage (30.09.2026, просьба пользователя): экран не гаснет и не
        # запирается. Без Savage не работает (screen_awake.py) — поэтому
        # включение здесь включает и Savage, а горит строка, только когда оба.
        row, self.awake = switch_row(self.pal, "\U000f0208", "Не отключать экран", self.set_awake,
                                     "экран не гаснет и не блокируется")
        c.pack_start(row, False, False, 0)
        box.pack_start(c, False, False, 0)

        self.later(self.probe_monitor, self.show_monitor)
        return box

    # монитор MSI
    def probe_monitor(self):
        sys.path.insert(0, HERE)
        import monitor_brightness
        if not monitor_brightness.hypr_has_monitor():
            return None
        try:
            with open(monitor_brightness.LAST) as f:
                return int(f.read().strip())
        except (OSError, ValueError):
            return -1

    def show_monitor(self, known):
        if known is None:
            return
        if known >= 0:
            self.mon.set_state(known)
        self.mon_rev.set_reveal_child(True)
        # Точное значение — у самого монитора (ddcutil ≈0,3 с).
        self.later(lambda: int(run(*script("monitor_brightness.py", "get"), timeout=25)),
                   lambda v: v is not None and self.mon.set_state(v))

    def set_mon(self, v):
        # Запросы по шине DDC — по одному: одновременные мешают друг другу.
        self.mon_pending = v
        GLib.idle_add(self.flush_mon)

    def flush_mon(self):
        if self.mon_proc is not None and self.mon_proc.poll() is None:
            GLib.timeout_add(120, self.flush_mon)
            return False
        if self.mon_pending is not None:
            v, self.mon_pending = self.mon_pending, None
            self.mon_proc = subprocess.Popen(script("monitor_brightness.py", "set", str(v)),
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
        return False

    def set_bright(self, v):
        with self.bl_lock:
            run("brightnessctl", "set", "%d%%" % v)

    # опрос
    def state(self):
        sys.path.insert(0, HERE)
        import night_mode
        import savage_battery
        import screen_awake
        return {"bat": savage_battery.battery(), "profile": power_get()[1],
                "awake": savage_battery.is_savage_active() and screen_awake.get(),
                "night": night_mode.read_state()[0], "warmth": night_mode.read_state()[2],
                "savage": savage_battery.is_savage_active(),
                "bright": backlight()}

    def refresh(self):
        self.fetch(self.state, self.apply)

    def apply(self, st):
        if not st:
            return
        b = st["bat"]
        if b:
            cap, status = b["cap"], b["status"]
            self.ring.set(cap / 100, "%d%%" % cap, cap <= 15 and not b["on_ac"])
            word = {"Charging": "Заряжается", "Full": "Заряжено", "Discharging": "От батареи"}
            text = word.get(status, "От сети" if b["on_ac"] else status)
            if status == "Not charging" and cap >= 99:
                text = "Заряжено"
            self.bat_status.set_text(text)
            parts = []
            if b["hours"]:
                import savage_battery
                parts.append(("до полного " if status == "Charging" else "осталось ")
                             + savage_battery.span(b["hours"]))
            elif status == "Not charging":
                parts.append("заряд бережётся")
            if b["limit"]:
                parts.append("лимит %d–%d%%" % b["limit"])
            sub = " · ".join(parts)
            self.bat_sub.set_text(sub[:1].upper() + sub[1:])
        else:
            self.ring.set(1, "—")
            self.bat_status.set_text("Батареи нет")
        for p, btn in self.segs.items():
            set_cls(btn, "on", p == st["profile"])
        self.night.set_on(st["night"])
        self.warm_rev.set_reveal_child(st["night"])
        if st.get("warmth") is not None:
            self.warm.set_state(st["warmth"])
        self.savage.set_on(st["savage"])
        self.awake.set_on(st["awake"])
        if st["bright"] is not None:
            self.bright.set_state(st["bright"])

    # действия
    def set_profile(self, p):
        for q, btn in self.segs.items():
            set_cls(btn, "on", q == p)
        self.later(lambda: run("powerprofilesctl", "set", p), lambda _r: self.refresh())

    def set_warmth(self, v):
        run(*script("night_mode.py", "on", str(v)), timeout=6)

    def set_night(self, on):
        self.warm_rev.set_reveal_child(on)
        self.later(lambda: run(*script("night_mode.py", "on" if on else "off"), timeout=6),
                   lambda _r: self.refresh())

    def set_savage(self, on):
        def work():
            import savage_battery
            if on == savage_battery.is_savage_active():
                return
            if on:
                # systemd-inhibit должен пережить панель — отдельной сессией.
                spawn(*script("savage_battery.py", "--toggle"))
                time.sleep(0.5)
            else:
                run(*script("savage_battery.py", "--toggle"))
        self.later(work, lambda _r: self.refresh())

    def set_awake(self, on):
        def work():
            import savage_battery
            if on and not savage_battery.is_savage_active():
                spawn(*script("savage_battery.py", "--toggle"))
                time.sleep(0.5)
            run(*script("screen_awake.py", "on" if on else "off"))
        self.later(work, lambda _r: self.refresh())


# ── Календарь ────────────────────────────────────────────────────────────
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
          "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
MONTHS_GEN = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля",
              "августа", "сентября", "октября", "ноября", "декабря")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")
DAYS_FULL = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")


class CalendarPage(Page):
    scroll = False

    def build(self):
        import datetime
        self.offset = 0
        ev = Gtk.EventBox()
        ev.add_events(Gdk.EventMask.SCROLL_MASK)
        ev.connect("scroll-event", self.on_scroll)
        box = vbox(10)
        ev.add(box)

        c = card(6)
        head = hbox(6)
        prev = icon_button(I["chev_l"], "flat", 16, 22, "Прошлый месяц")
        nxt = icon_button(I["chev_r"], "flat", 16, 22, "Следующий месяц")
        prev.connect("clicked", lambda _b: self.step(-1))
        nxt.connect("clicked", lambda _b: self.step(1))
        title = hbox(12)
        title.set_halign(Gtk.Align.CENTER)
        self.lbl_month = lbl("", "cal-month")
        self.lbl_year = lbl("", "cal-year")
        title.pack_start(self.lbl_month, False, False, 0)
        title.pack_start(self.lbl_year, False, False, 0)
        head.pack_start(prev, False, False, 0)
        head.pack_start(title, True, True, 0)
        head.pack_start(nxt, False, False, 0)
        c.pack_start(head, False, False, 0)

        self.grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                             row_spacing=sc(2), column_spacing=sc(2))
        c.pack_start(self.grid, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(4, vertical=False)
        t = datetime.date.today()
        today = lbl("Сегодня %d %s, %s" % (t.day, MONTHS_GEN[t.month - 1], DAYS_FULL[t.weekday()]),
                    "name", chars=32)
        c.pack_start(today, True, True, 0)
        wk = lbl("неделя %d" % t.isocalendar()[1], "cap", 1.0)
        c.pack_end(wk, False, False, 0)
        back = Gtk.EventBox()
        back.add(c)
        back.set_tooltip_text("Вернуться к сегодняшнему месяцу")
        back.connect("button-press-event", lambda *_: (self.step(-self.offset), True)[1])
        box.pack_start(back, False, False, 0)
        self.redraw()
        return ev

    def step(self, d):
        self.offset += d
        self.redraw()

    def on_scroll(self, _w, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.step(-1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.step(1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            dy = event.get_scroll_deltas()[2]
            if abs(dy) >= 0.5:
                self.step(1 if dy > 0 else -1)
        return True

    def redraw(self):
        import calendar
        import datetime
        today = datetime.date.today()
        y, m = today.year, today.month + self.offset
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1
        self.lbl_month.set_text(MONTHS[m - 1])
        self.lbl_year.set_text(str(y))
        clear(self.grid)
        for col, name in enumerate(WEEKDAYS):
            w = lbl(name, "cal-wd" + (" cal-off" if col >= 5 else ""), 0.5)
            self.grid.attach(w, col, 0, 1, 1)
        weeks = calendar.Calendar(0).monthdatescalendar(y, m)
        # Всегда шесть строк — высота карточки не меняется от месяца к месяцу.
        while len(weeks) < 6:
            last = weeks[-1][-1]
            weeks.append([last + datetime.timedelta(days=i) for i in range(1, 8)])
        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                cls = "cal-today" if day == today else "cal-day"
                if day != today:
                    if day.month != m:
                        cls += " cal-pad"
                    if col >= 5:
                        cls += " cal-off"
                w = lbl(str(day.day), cls, 0.5)
                w.set_halign(Gtk.Align.CENTER)
                self.grid.attach(w, col, row, 1, 1)
        self.grid.show_all()


# ── Уведомления ──────────────────────────────────────────────────────────
TRACK_OFF = os.path.expanduser("~/.config/hypr/state/track-notify-off")


def when_str(t):
    """«12:05» сегодня, «вчера 12:05», иначе «03.10 12:05»."""
    lt, now = time.localtime(t), time.localtime()
    hm = time.strftime("%H:%M", lt)
    if lt[:3] == now[:3]:
        return hm
    y = time.localtime(time.time() - 86400)
    return ("вчера " if lt[:3] == y[:3] else time.strftime("%d.%m ", lt)) + hm


NOTIF_LOG = os.path.expanduser("~/.cache/jarvis-notif-log.json")
NOTIF_SHOWN = 50


def read_notif_log():
    try:
        with open(NOTIF_LOG) as f:
            data = json.load(f)
        return data[:NOTIF_SHOWN] if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


class NotifyPage(Page):
    interval = 2000
    scroll = False          # список внизу сам занимает остаток высоты и сам прокручивается

    def build(self):
        self.armed = None
        self.shown_log = None
        box = vbox(10)

        c = card(14, vertical=False)
        g = Glyph(I["bell"], 28, 40)
        g.get_style_context().add_class("gl-acc")
        c.pack_start(g, False, False, 0)
        col = vbox(2)
        col.set_valign(Gtk.Align.CENTER)
        self.count = lbl("…", "big")
        self.count_sub = lbl("в истории центра уведомлений", "cap")
        col.pack_start(self.count, False, False, 0)
        col.pack_start(self.count_sub, False, False, 0)
        c.pack_start(col, True, True, 0)
        box.pack_start(c, False, False, 0)

        c = card(10)
        row, self.dnd = switch_row(self.pal, I["bell_off"], "Не беспокоить", self.set_dnd,
                                   "уведомления копятся молча")
        c.pack_start(row, False, False, 0)
        row, self.track = switch_row(self.pal, I["music"], "Смена трека", self.set_track,
                                     "уведомление с обложкой при новом треке")
        c.pack_start(row, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(8)
        btns = Gtk.Box(spacing=sc(8), homogeneous=True)
        btns.pack_start(text_button("Открыть центр", "act go", self.open_center,
                                    "Центр уведомлений swaync"), True, True, 0)
        self.clear_btn = text_button("Очистить историю", "act danger", self.clear_all,
                                     "Стирает ВСЕ уведомления из центра — без возврата")
        btns.pack_start(self.clear_btn, True, True, 0)
        c.pack_start(btns, False, False, 0)
        self.hint = lbl("", "cap", 0.5, chars=40)
        self.hint.set_no_show_all(True)
        c.pack_start(self.hint, False, False, 0)
        box.pack_start(c, False, False, 0)

        # Последние уведомления (04.10.2026, просьба пользователя): их пишет notif_log.py,
        # потому что swaync текст по D-Bus не отдаёт. Остаток высоты — под список.
        c = card(6)
        c.set_vexpand(True)
        c.pack_start(lbl("Последние уведомления", "cap-hi"), False, False, 0)
        self.sw = Gtk.ScrolledWindow()
        self.sw.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.sw.set_vexpand(True)
        self.sw.set_min_content_height(sc(60))
        self.list = vbox(0)
        self.sw.add(self.list)
        c.pack_start(self.sw, True, True, 0)
        box.pack_start(c, True, True, 0)
        return box

    def state(self):
        cnt = run("swaync-client", "-c")
        return (int(cnt) if cnt.isdigit() else None, run("swaync-client", "-D") == "true",
                not os.path.exists(TRACK_OFF), read_notif_log())

    def fill_log(self, items):
        key = [(e.get("t"), e.get("summary"), e.get("body")) for e in items]
        if key == self.shown_log:
            return
        self.shown_log = key
        clear(self.list)
        if not items:
            w = lbl("Пока пусто — журнал пишется с запуска сторожа", "dim")
            w.set_margin_top(sc(6))
            self.list.pack_start(w, False, False, 0)
        for e in items:
            row = vbox(1)
            row.get_style_context().add_class("nrow")
            top = hbox(6)
            top.pack_start(lbl(e.get("app") or "—", "napp", chars=22), False, False, 0)
            top.pack_end(lbl(when_str(e.get("t", 0)), "dim", 1.0), False, False, 0)
            row.pack_start(top, False, False, 0)
            if e.get("summary"):
                row.pack_start(lbl(e["summary"], "cap-hi", chars=48), False, False, 0)
            body = " ".join((e.get("body") or "").split())
            if body:
                w = lbl(body, "cap")
                w.set_line_wrap(True)
                w.set_lines(2)
                w.set_max_width_chars(52)
                w.set_ellipsize(Pango.EllipsizeMode.END)
                row.pack_start(w, False, False, 0)
            self.list.pack_start(row, False, False, 0)
        self.list.show_all()

    def refresh(self):
        self.fetch(self.state, self.apply)

    def apply(self, st):
        if not st:
            return
        cnt, dnd, track, log = st
        self.fill_log(log)
        if cnt is None:
            self.count.set_text("—")
            self.count_sub.set_text("swaync не отвечает")
        else:
            self.count.set_text(str(cnt) if cnt else "Пусто")
            self.count_sub.set_text("в истории центра уведомлений" if cnt else "уведомлений нет")
        self.clear_btn.set_sensitive(bool(cnt))
        self.dnd.set_on(dnd)
        self.track.set_on(track)

    def set_dnd(self, on):
        self.later(lambda: run("swaync-client", "-dn" if on else "-df"), lambda _r: self.refresh())

    def set_track(self, on):
        self.later(lambda: run(*script("track_notify.py", "on" if on else "off")),
                   lambda _r: self.refresh())

    def open_center(self):
        self.cc.launch(("swaync-client", "-t", "-sw"))

    def clear_all(self):
        # -C стирает ВСЮ историю без возврата (память notif-look), поэтому
        # второй щелчок: первый только «взводит» кнопку на 3 секунды.
        if not self.armed:
            self.clear_btn.get_child().set_text("Точно стереть?")
            set_cls(self.clear_btn, "armed", True)
            self.hint.set_text("Щёлкните ещё раз — история удалится без возврата")
            self.hint.show()
            self.armed = GLib.timeout_add(3000, self.disarm)
            return
        GLib.source_remove(self.armed)
        self.disarm()
        def wipe():
            run(*script("notif_log.py", "clear"))
            return run("swaync-client", "-C")
        self.later(wipe, lambda _r: self.refresh())

    def disarm(self):
        self.armed = None
        self.clear_btn.get_child().set_text("Очистить историю")
        set_cls(self.clear_btn, "armed", False)
        self.hint.hide()
        return False


# ── Экранное время ───────────────────────────────────────────────────────
def fmt_dur(sec):
    h, m = divmod(int(sec) // 60, 60)
    return ("%d ч %d мин" % (h, m)) if h else ("%d мин" % m)


class HoursChart(Gtk.DrawingArea):
    """24 столбика «сколько минут за час» — как вкладка «Сегодня» в screentime.py."""

    def __init__(self, pal):
        super().__init__()
        self.pal, self.hours = pal, {}
        self.set_size_request(-1, sc(64))
        self.connect("draw", self.draw)

    def set(self, hours):
        self.hours = {int(k): v for k, v in (hours or {}).items()}
        self.queue_draw()

    def draw(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        chart_h = h - sc(16)
        pitch = w / 24
        bw = max(2, int(pitch * 0.62))
        now = time.localtime().tm_hour
        for i in range(24):
            v = min(3600, self.hours.get(i, 0)) / 3600
            x = round(i * pitch + (pitch - bw) / 2)
            bh = max(2, round(chart_h * v))
            rounded(cr, x, chart_h - bh, bw, bh, min(3, bw / 2))
            role, a = ("primary", 1.0) if v > 0 else ("on_surface", 0.14)
            if i > now:
                role, a = "on_surface", 0.07
            cr.set_source_rgba(*rgba(self.pal[role], a))
            cr.fill()
        for i in (0, 6, 12, 18):
            draw_text(cr, str(i), 12, i * pitch + pitch / 2, h - sc(6),
                      rgba(self.pal["on_surface_variant"], 0.8))
        return True


class ScreenTimePage(Page):
    interval = 60000

    def build(self):
        box = vbox(10)
        c = card(8)
        top = hbox(10)
        col = vbox(2)
        col.pack_start(lbl("Сегодня за экраном", "cap"), False, False, 0)
        self.total = lbl("…", "big")
        col.pack_start(self.total, False, False, 0)
        top.pack_start(col, True, True, 0)
        more = text_button("Подробнее", "act", lambda: self.cc.launch(script("screentime.py")),
                           "Окно экранного времени: день и неделя")
        more.set_valign(Gtk.Align.CENTER)
        top.pack_end(more, False, False, 0)
        c.pack_start(top, False, False, 0)
        self.chart = HoursChart(self.pal)
        c.pack_start(self.chart, False, False, 0)
        box.pack_start(c, False, False, 0)

        c = card(6)
        c.pack_start(lbl("Программы", "cap"), False, False, 0)
        grid = Gtk.Grid(column_spacing=sc(10), row_spacing=sc(6))
        self.rows = []
        for i in range(6):
            n, b, v = lbl("", "name", chars=12), Bar(self.pal), lbl("", "val", 1.0)
            n.set_width_chars(12)
            v.set_width_chars(9)
            grid.attach(n, 0, i, 1, 1)
            grid.attach(b, 1, i, 1, 1)
            grid.attach(v, 2, i, 1, 1)
            self.rows.append((n, b, v))
        c.pack_start(grid, False, False, 0)
        self.empty = lbl("Пока пусто — счётчик screentime_daemon не запущен?", "dim", chars=40)
        c.pack_start(self.empty, False, False, 0)
        box.pack_start(c, False, False, 0)
        return box

    def load(self):
        import json
        out = subprocess.run(script("screentime.py", "--json", "today"),
                             capture_output=True, text=True, timeout=5).stdout
        return json.loads(out)

    def refresh(self):
        self.fetch(self.load, self.apply)

    def apply(self, data):
        if not data:
            self.total.set_text("нет данных")
            return
        self.total.set_text(fmt_dur(data.get("total", 0)))
        self.chart.set(data.get("hours"))
        apps = data.get("apps", [])[:6]
        top = apps[0]["seconds"] if apps else 1
        for i, (n, b, v) in enumerate(self.rows):
            if i < len(apps):
                a = apps[i]
                n.set_text(a.get("name") or a.get("app_id", ""))
                b.set(a["seconds"] / top)
                v.set_text(fmt_dur(a["seconds"]) if a["seconds"] >= 60 else "<1 мин")
            else:
                n.set_text("")
                v.set_text("")
                b.set(0)
            for w in (n, b, v):
                w.set_visible(i < len(apps))
        self.empty.set_visible(not apps)


PAGES = {
    "sound": ("Звук", SoundPage),
    "system": ("Система", SystemPage),
    "wifi": ("Wi-Fi", WifiPage),
    "bt": ("Bluetooth", BluetoothPage),
    "battery": ("Питание", PowerPage),
    "calendar": ("Календарь", CalendarPage),
    "screentime": ("Экранное время", ScreenTimePage),
    "bell": ("Уведомления", NotifyPage),
}


class ControlCenter(Gtk.Window):
    def __init__(self):
        super().__init__(title="Центр управления")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_namespace(self, "jarvis-control-center")
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        self.pal = pal = popup_theme.palette()
        css = popup_theme.css(scale_css("""
        .popup-box {
            /* Пиксельный шрифт — только кратно 8 px: так он чёткий (память pixel-font-system).
               Рамка — общая для всех попапов (popup_theme.BASE_CSS: 3 px акцента и тёмный
               контур); здесь её не переопределяем: пользователь попросил «как в остальных
               плашках», 30.09.2026. Скругление — как у плеера. */
            font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
            font-size: 16px; font-weight: normal;
            border-radius: 14px; padding: 12px;
        }
        .side { background-color: %(card_bg)s; border: 1px solid %(line)s;
                border-radius: 14px; padding: 8px 6px; }
        button.nav, button.head {
            background: transparent; background-image: none; border: none; box-shadow: none;
            color: %(on_surface_variant)s; border-radius: 10px; padding: 0;
            min-width: 38px; min-height: 38px;
        }
        button.nav:hover, button.head:hover { background-color: %(surface_high)s; color: %(primary)s; }
        button.nav.active, button.nav.active:hover { background-color: %(primary)s; color: %(on_primary)s; }
        button.head { background-color: %(card_bg)s; border: 1px solid %(line)s;
                      min-width: 34px; min-height: 34px; }
        button.head.close:hover { color: %(error)s; border-color: %(error)s; }
        label.page { color: %(primary)s; font-size: 16px; }
        .card { background-color: %(card_bg)s; border: 1px solid %(line)s; border-radius: 14px; }
        .hero { border: 1px solid %(line)s; border-radius: 14px; }
        label.user { font-size: 24px; color: %(on_surface)s;
                     text-shadow: 1px 1px 0 alpha(black, 0.8), 0 0 4px alpha(black, 0.7); }
        label.hero-line { font-size: 16px; color: %(on_surface)s;
                          text-shadow: 1px 1px 0 alpha(black, 0.8), 0 0 4px alpha(black, 0.7); }
        label.hero-st { color: %(primary)s; }
        label.m-title { font-size: 16px; color: %(on_surface)s; }
        label.m-sub { font-size: 16px; color: %(on_surface_variant)s; }
        label.m-dim { font-size: 12px; color: alpha(%(on_surface_variant)s, 0.8); }
        label.clock { font-size: 32px; color: %(primary)s; }
        label.date { font-size: 16px; color: %(on_surface)s; }
        label.date-dim { font-size: 16px; color: %(on_surface_variant)s; }
        button.media { background: transparent; background-image: none; border: none;
                       box-shadow: none; padding: 0; border-radius: 14px; }
        button.media:hover .card { border-color: %(primary)s; }
        button.tile {
            background-color: %(card_bg)s; background-image: none; box-shadow: none;
            border: 1px solid %(line)s; border-radius: 14px; padding: 6px 4px;
            color: %(on_surface)s; min-width: 108px; min-height: 60px;
        }
        button.tile:hover { border-color: %(primary)s; }
        button.tile.on { background-color: %(primary)s; color: %(on_primary)s; border-color: %(primary)s; }
        label.tile-label { font-size: 12px; }
        /* «Кофеин + Таурин» — третий цвет палитры (не выбивается из гаммы). */
        button.tile.on.taurine { background-color: %(tertiary)s; color: %(on_tertiary)s;
                                 border-color: %(tertiary)s; }
        scale.warmth { min-width: 220px; }
        label.warmth-val { font-size: 16px; color: %(primary)s; min-width: 44px; }

        /* ── страницы ── */
        .pcard { padding: 10px 12px; }
        .pcard.tight { padding: 6px 12px; }
        scrolledwindow, viewport { background: transparent; border: none; box-shadow: none; }
        /* 08.10.2026, Просьба: «прокрутчик намного тоньше». Тема GTK под мышью раздувала
           полосу до ~10 px — ширина зажата во всех состояниях (наведение, перетаскивание). */
        scrollbar, scrollbar.hovering, scrollbar.dragging, scrollbar trough {
            background: transparent; border: none; box-shadow: none;
            padding: 0; margin: 0; min-width: 0; }
        scrollbar slider, scrollbar.hovering slider, scrollbar.dragging slider,
        scrollbar.overlay-indicator:not(.dragging):not(.hovering) slider {
            min-width: 2px; min-height: 24px; margin: 0 1px; border-radius: 1px;
            background-color: alpha(%(primary)s, 0.45); border: none; }
        scrollbar.hovering slider, scrollbar.dragging slider {
            background-color: alpha(%(primary)s, 0.75); }
        label.cap { font-size: 12px; color: %(on_surface_variant)s; }
        label.cap-hi { font-size: 12px; color: %(on_surface)s; }
        label.napp { font-size: 12px; color: %(primary)s; }
        .nrow { padding: 5px 2px 6px 2px; border-bottom: 1px solid alpha(%(line)s, 0.6); }
        label.dim { font-size: 12px; color: alpha(%(on_surface_variant)s, 0.8); }
        label.name { font-size: 16px; color: %(on_surface)s; }
        label.val { font-size: 16px; color: %(primary)s; }
        label.big { font-size: 24px; color: %(on_surface)s; }
        label.bad { color: %(error)s; }
        .gl-acc { color: %(primary)s; }
        .gl-dim { color: %(on_surface_variant)s; }
        .muted { color: %(error)s; }
        button.flat {
            background: transparent; background-image: none; border: none; box-shadow: none;
            color: %(on_surface_variant)s; border-radius: 10px; padding: 0;
            min-width: 30px; min-height: 30px;
        }
        button.flat:hover { background-color: %(surface_high)s; color: %(primary)s; }
        button.flat:disabled { color: alpha(%(on_surface_variant)s, 0.35); }
        button.flat.muted { color: %(error)s; }
        button.row {
            background: transparent; background-image: none; box-shadow: none;
            border: 1px solid transparent; border-radius: 10px; padding: 4px 8px;
            color: %(on_surface)s;
        }
        button.row:hover { background-color: %(surface_high)s; }
        button.row.cur { background-color: alpha(%(primary)s, 0.16); border-color: %(line)s;
                         color: %(primary)s; }
        button.row.cur label.name { color: %(primary)s; }
        button.act {
            background-color: %(surface_high)s; background-image: none; box-shadow: none;
            border: 1px solid %(line)s; border-radius: 10px; padding: 5px 12px;
            color: %(on_surface)s; min-height: 0;
        }
        button.act label { font-size: 12px; }
        button.act:hover { border-color: %(primary)s; color: %(primary)s; }
        button.act.go { background-color: %(primary)s; color: %(on_primary)s; border-color: %(primary)s; }
        button.act.go:hover { background-color: alpha(%(primary)s, 0.85); color: %(on_primary)s; }
        button.act.danger { color: %(error)s; }
        button.act.danger:hover { border-color: %(error)s; }
        button.act.danger.armed { background-color: %(error)s; color: %(surface)s; border-color: %(error)s; }
        button.act:disabled { color: alpha(%(on_surface_variant)s, 0.45); border-color: alpha(%(primary)s, 0.15);
                              background-color: transparent; }
        button.seg {
            background-color: %(surface_high)s; background-image: none; box-shadow: none;
            border: 1px solid %(line)s; border-radius: 10px; padding: 8px 4px; color: %(on_surface)s;
        }
        button.seg:hover { border-color: %(primary)s; }
        button.seg.on { background-color: %(primary)s; color: %(on_primary)s; border-color: %(primary)s; }
        label.seg-label { font-size: 12px; }
        entry.pw { font-family: 'PxPlus HP 100LX 6x8 Jarvis', monospace; font-size: 16px;
                   font-weight: normal; padding: 4px 8px; min-height: 0; border-radius: 8px;
                   border-color: %(line)s; }
        entry.pw:focus { border-color: %(primary)s; }
        label.cal-month { font-size: 16px; color: %(primary)s; }
        label.cal-year { font-size: 16px; color: %(on_surface_variant)s; }
        label.cal-wd { font-size: 12px; color: %(on_surface)s; padding: 4px 0; }
        label.cal-day, label.cal-today { font-size: 16px; color: %(on_surface)s;
                                         min-width: 32px; min-height: 32px; padding: 0; }
        label.cal-off { color: %(wknd)s; }
        label.cal-pad { color: alpha(%(on_surface_variant)s, 0.40); }
        label.cal-pad.cal-off { color: alpha(%(wknd)s, 0.45); }
        label.cal-today { background-color: %(primary)s; color: %(on_primary)s; border-radius: 999px; }
        """ + popup_theme.SCALE_CSS + """
        /* Тема GTK красит заполнение шкалы своим градиентом (background-image),
           и цвет из палитры под ним не виден — снимаем его явно. */
        scale trough { background-image: none; border: none; background-color: alpha(%(on_surface)s, 0.14); }
        scale highlight { background-image: none; border: none; background-color: %(primary)s; }
        scale:disabled highlight { background-color: alpha(%(primary)s, 0.4); }
        """), card_bg=popup_theme.rgba(pal["surface_container"], "0.80"),
            line=popup_theme.rgba(pal["primary"], "0.40"),
            frame=popup_theme.rgba(pal["primary"], "0.85"),
            accent="primary", knob="tertiary",
            wknd=tune(pal["secondary"], sat=1.45, light=-0.10))
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: self.quit())
        self.add(self.bg)
        self.align = Gtk.Box()
        self.bg.add(self.align)
        if "--center" in sys.argv:
            # Средние пилюли бара: всегда по середине экрана сверху (30.09.2026).
            mon = popup_theme.pointer_monitor()
            if mon is not None:
                GtkLayerShell.set_monitor(self, mon)
            self.align.set_halign(Gtk.Align.CENTER)
            if popup_theme.add_ears(self.align):
                self.align.set_valign(Gtk.Align.START)      # приклеена к бару: без зазора
            elif popup_theme.bar_position() == "bottom":
                self.align.set_valign(Gtk.Align.END)
                self.align.set_margin_bottom(6)
            else:
                self.align.set_valign(Gtk.Align.START)
                self.align.set_margin_top(6)
        else:
            popup_theme.place_under_cursor(self.align)
        stop = Gtk.EventBox()
        stop.connect("button-press-event", lambda w, e: True)
        self.align.add(stop)

        root = Gtk.Box(spacing=sc(12))
        root.get_style_context().add_class("popup-box")
        stop.add(root)
        root.pack_start(self.build_side(), False, False, 0)
        root.pack_start(self.build_main(), True, True, 0)
        root.pack_start(self.build_vis(), False, False, 0)

        self.connect("key-press-event", self.on_key)
        GLib.timeout_add(1000, self.tick)

    # ── боковая колонка ───────────────────────────────────────────────────
    def build_side(self):
        # Кнопки переключают страницы в самой панели (PAGES); только ⚙ внизу
        # по-прежнему закрывает панель и открывает «Настройки».
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(6))
        side.get_style_context().add_class("side")
        self.nav = {}
        for key in ("home", "sound", "system", "wifi", "bt", "battery", "calendar",
                    "screentime", "bell", "gear"):
            tip = "Главная" if key == "home" else ("Настройки" if key == "gear" else PAGES[key][0])
            b = icon_button(I[key], "nav" + (" active" if key == "home" else ""), 18, 26, tip)
            if key == "gear":
                b.connect("clicked", lambda _b: self.launch(script("settings_app.py")))
            else:
                b.connect("clicked", lambda _b, k=key: self.show_page(k))
            side.pack_start(b, False, False, 0)
            self.nav[key] = b
        return side

    def show_page(self, key):
        if key == self.current_key:
            return
        if key != "home" and key not in self.pages:
            title, cls = PAGES[key]
            page = cls(self, key)
            page.widget.show_all()
            self.stack.add_named(page.widget, key)
            self.pages[key] = page
        self.current_key = key
        self.stack.set_visible_child_name(key)
        self.page_lbl.set_text("Главная" if key == "home" else PAGES[key][0])
        for k, b in self.nav.items():
            set_cls(b, "active", k == key)
        if key == "home":
            # На страницах могли переключить Wi-Fi, ночной свет и т.п.
            for t in self.tiles:
                t.poll()
        else:
            self.pages[key].shown()

    def launch(self, cmd):
        # Сначала закрыть себя: попапы ставят свой слой под указатель,
        # и два слоя с EXCLUSIVE-клавиатурой друг другу мешают.
        self.hide()
        spawn(*cmd)
        GLib.timeout_add(150, self.quit)

    # ── основная часть ────────────────────────────────────────────────────
    def build_main(self):
        main = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(10))

        head = Gtk.Box(spacing=sc(8))
        page = Gtk.Label(label="Главная", xalign=0)
        page.get_style_context().add_class("page")
        self.page_lbl = page
        head.pack_start(page, True, True, sc(4))
        for icon, tip, cmd, extra in (
                ("gear", "Настройки", script("settings_app.py"), ""),
                # какое меню питания — решает power_view.py (Настройки → Power)
                ("power", "Выключение", script("power_view.py", "open"), ""),
                ("close", "Закрыть", None, " close")):
            b = icon_button(I[icon], "head" + extra, 16, 22, tip)
            b.connect("clicked", (lambda _b, c=cmd: self.launch(c)) if cmd else (lambda _b: self.quit()))
            head.pack_start(b, False, False, 0)
        main.pack_start(head, False, False, 0)

        home = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(10))
        home.pack_start(self.build_hero(), False, False, 0)
        low = Gtk.Box(spacing=sc(10))
        left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(10))
        left.pack_start(self.build_media(), True, True, 0)
        left.pack_start(self.build_clock(), False, False, 0)
        low.pack_start(left, True, True, 0)
        low.pack_start(self.build_tiles(), False, False, 0)
        home.pack_start(low, True, True, 0)

        # Стек страниц. Размер задаёт «Главная» (homogeneous), остальные
        # страницы прокручиваются внутри — панель между вкладками не прыгает.
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_UP_DOWN)
        self.stack.set_transition_duration(150)
        self.stack.add_named(home, "home")
        self.pages = {}
        self.current_key = "home"
        main.pack_start(self.stack, True, True, 0)
        return main

    # визуализатор
    def build_vis(self):
        box = Gtk.Box()
        box.get_style_context().add_class("card")
        box.set_size_request(VIS_W, -1)
        self.vis = Visualizer(self.pal)
        self.vis.set_margin_top(sc(10))
        self.vis.set_margin_bottom(sc(10))
        self.vis.set_margin_start(sc(10))
        self.vis.set_margin_end(sc(10))
        box.pack_start(self.vis, True, True, 0)
        return box

    # карточка пользователя
    def build_hero(self):
        self.hero_pix = None
        self.avatar_pix = None
        area = Gtk.DrawingArea()
        area.set_size_request(HERO_W, HERO_H)
        area.connect("draw", self.draw_hero)
        self.hero = area

        ov = Gtk.Overlay()
        ov.add(area)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(6))
        text.set_valign(Gtk.Align.CENTER)
        text.set_halign(Gtk.Align.START)
        text.set_margin_start(sc(26) + AVATAR_SIZE + sc(24))
        user = os.environ.get("USER") or "user"
        try:
            with open("/etc/hostname") as f:
                host = f.read().strip()
        except OSError:
            host = "localhost"
        # Отображаемое имя — своё (05.10.2026, Просьба: «сюда — staticxyzz»), строка
        # user@host ниже остаётся системной. Файл state/display-name.
        try:
            shown = open(os.path.expanduser("~/.config/hypr/state/display-name")).read().strip() or user
        except OSError:
            shown = user
        lu = Gtk.Label(label=shown, xalign=0)
        lu.get_style_context().add_class("user")
        lu.set_margin_bottom(sc(4))
        self.lbl_up = Gtk.Label(label="Работает: " + fmt_uptime(), xalign=0)
        ver = run("niri", "--version").split(" (")[0] or "niri"
        self.niri_ver = ver
        text.pack_start(lu, False, False, 0)
        # Экранное время за сегодня; щелчок по карточке открывает подробности
        # (Просьба: «положи экранное время куда-нибудь в этой плашке», 30.09.2026).
        self.lbl_st = Gtk.Label(label="\U000f0128  Экранное время: …", xalign=0)
        for w in (Gtk.Label(label="%s@%s" % (user, host), xalign=0), self.lbl_up,
                  Gtk.Label(label="Arch Linux · " + ver, xalign=0), self.lbl_st):
            w.get_style_context().add_class("hero-line")
            text.pack_start(w, False, False, 0)
        self.lbl_st.get_style_context().add_class("hero-st")
        ov.add_overlay(text)
        ov.get_style_context().add_class("hero")
        threading.Thread(target=self.load_hero, daemon=True).start()
        threading.Thread(target=self.load_screentime, daemon=True).start()
        eb = Gtk.EventBox()
        eb.add(ov)
        # Щелчок открывает страницу «Экранное время» здесь же; полное окно
        # screentime.py — кнопкой «Подробнее» на ней.
        eb.set_tooltip_text("Щелчок — экранное время за сегодня")
        eb.connect("button-release-event",
                   lambda *_: (self.show_page("screentime"), True)[1])
        return eb

    def load_screentime(self):
        import json as _json
        try:
            out = subprocess.run([PY, os.path.join(HERE, "screentime.py"), "--json", "today"],
                                 capture_output=True, text=True, timeout=4).stdout
            total = int(_json.loads(out).get("total", 0))
        except Exception:
            total = None
        if total is None:
            txt = "нет данных"
        else:
            h, m = divmod(total // 60, 60)
            txt = ("%d ч %d мин" % (h, m)) if h else ("%d мин" % m)
        GLib.idle_add(self.lbl_st.set_text, "\U000f0128  Экранное время: " + txt)

    def load_hero(self):
        scale = self.get_scale_factor() or 1
        hero = avatar = None
        try:
            p = hero_image(scale)
            if p:
                hero = GdkPixbuf.Pixbuf.new_from_file(p)
        except Exception:
            hero = None
        try:
            if os.path.exists(AVATAR):
                s = AVATAR_SIZE * scale
                avatar = GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR, s, s, False)
        except Exception:
            avatar = None
        GLib.idle_add(self.set_hero, hero, avatar)

    def set_hero(self, hero, avatar):
        self.hero_pix, self.avatar_pix = hero, avatar
        self.hero.queue_draw()
        return False

    def draw_hero(self, widget, cr):
        import cairo
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        rounded(cr, 0, 0, w, h, RADIUS)
        cr.clip()
        if self.hero_pix is not None:
            cr.save()
            cr.scale(w / self.hero_pix.get_width(), h / self.hero_pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, self.hero_pix, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgba(*rgba(self.pal["surface_container"]))
            cr.paint()
        # Вуаль слева направо: текст читается на любых обоях, справа видно картинку.
        # Цвет вуали — поверхность палитры обоев, а не зашитый тёмно-синий.
        g = cairo.LinearGradient(0, 0, w, 0)
        sr, sg, sb, _ = rgba(self.pal["surface"])
        # 01.10.2026: плотнее под текстом (Просьба: «текст на фоне не читаемый») —
        # текст занимает почти всю ширину, прежняя вуаль к его середине была ~30 %.
        g.add_color_stop_rgba(0.0, sr, sg, sb, 0.86)
        g.add_color_stop_rgba(0.62, sr, sg, sb, 0.74)
        g.add_color_stop_rgba(0.88, sr, sg, sb, 0.42)
        g.add_color_stop_rgba(1.0, sr, sg, sb, 0.22)
        cr.set_source(g)
        cr.paint()
        # Аватар — круг с кольцом акцента.
        a = AVATAR_SIZE
        x, y = sc(26), (h - a) / 2
        cr.save()
        cr.arc(x + a / 2, y + a / 2, a / 2, 0, 6.2832)
        cr.clip()
        if self.avatar_pix is not None:
            cr.translate(x, y)
            cr.scale(a / self.avatar_pix.get_width(), a / self.avatar_pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, self.avatar_pix, 0, 0)
            cr.paint()
        else:
            cr.set_source_rgba(*rgba(self.pal["surface_high"]))
            cr.paint()
        cr.restore()
        cr.arc(x + a / 2, y + a / 2, a / 2 + 1.5 * S, 0, 6.2832)
        cr.set_source_rgba(*rgba(self.pal["primary"]))
        cr.set_line_width(2.5 * S)
        cr.stroke()
        return True

    # карточка плеера
    def build_media(self):
        self.cover_pix = None
        self.cover_url = None
        self.player = None
        btn = Gtk.Button()
        btn.get_style_context().add_class("media")
        btn.set_tooltip_text("Щелчок — пауза / продолжить, правой — плеер")
        btn.connect("clicked", self.on_media)
        btn.connect("button-press-event", self.on_media_press)
        box = Gtk.Box()
        box.get_style_context().add_class("card")
        inner = Gtk.Box(spacing=sc(14))
        inner.set_margin_top(sc(12))
        inner.set_margin_bottom(sc(10))
        inner.set_margin_start(sc(12))
        inner.set_margin_end(sc(14))
        self.cover = Gtk.DrawingArea()
        self.cover.set_size_request(COVER, COVER)
        self.cover.set_valign(Gtk.Align.CENTER)
        self.cover.connect("draw", self.draw_cover)
        inner.pack_start(self.cover, False, False, 0)
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(6))
        col.set_valign(Gtk.Align.CENTER)
        self.m_title = Gtk.Label(xalign=0)
        self.m_artist = Gtk.Label(xalign=0)
        self.m_state = Gtk.Label(xalign=0)
        for w, cls in ((self.m_title, "m-title"), (self.m_artist, "m-sub"), (self.m_state, "m-dim")):
            w.get_style_context().add_class(cls)
            w.set_ellipsize(3)
            w.set_max_width_chars(12)
            col.pack_start(w, False, False, 0)
        inner.pack_start(col, True, True, 0)
        # Полоска «сколько прошло / осталось» под обложкой и названием (30.09.2026).
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        outer.pack_start(inner, True, True, 0)
        self.progress = Gtk.DrawingArea()
        self.progress.set_size_request(-1, sc(6))
        self.progress.set_margin_start(sc(14))
        self.progress.set_margin_end(sc(14))
        self.progress.set_margin_bottom(sc(12))
        self.progress.connect("draw", self.draw_progress)
        self.prog = (0.0, 0.0, False)          # позиция, длина, играет ли
        self.prog_at = time.time()
        outer.pack_start(self.progress, False, False, 0)
        box.pack_start(outer, True, True, 0)
        btn.add(box)
        # Между опросами (раз в секунду) полоска едет сама — плавно.
        GLib.timeout_add(100, self.progress_tick)
        self.m_title.set_text("Ничего не играет")
        threading.Thread(target=self.poll_media, daemon=True).start()
        return btn

    def poll_media(self):
        r = mpris_common.pick()
        info = None
        if r:
            sep = "\x1f"
            raw = run("playerctl", "-p", r["instance"], "metadata", "--format",
                      sep.join(("{{mpris:artUrl}}", "{{mpris:length}}", "{{position}}")))
            parts = raw.split(sep) if raw else ["", "", ""]
            parts += [""] * (3 - len(parts))
            try:
                length = int(parts[1] or 0) / 1e6
                pos = int(parts[2] or 0) / 1e6
            except ValueError:
                length = pos = 0
            info = dict(r, art=parts[0], length=length, pos=pos)
        GLib.idle_add(self.show_media, info)

    def show_media(self, info):
        if not info:
            self.player = None
            self.m_title.set_text("Ничего не играет")
            self.m_artist.set_text("")
            self.m_state.set_text("")
            self.cover_pix = None
            self.cover.queue_draw()
            self.prog = (0.0, 0.0, False)
            self.progress.queue_draw()
            return False
        self.player = info["instance"]
        self.prog = (info["pos"], info["length"], info["status"] == "Playing")
        self.prog_at = time.time()
        self.progress.queue_draw()
        self.m_title.set_text(info["title"] or "Без названия")
        self.m_artist.set_text(info["artist"] or "")
        st = {"Playing": "Играет", "Paused": "Пауза"}.get(info["status"], info["status"])
        tm = fmt_time(info["pos"]) + (" / " + fmt_time(info["length"]) if info["length"] else "")
        self.m_state.set_text(st + " · " + tm)
        if info["art"] != self.cover_url:
            self.cover_url = info["art"]
            threading.Thread(target=self.load_cover, args=(info["art"],), daemon=True).start()
        return False

    def load_cover(self, url):
        pix = None
        try:
            path = None
            if url.startswith("file://"):
                path = url[len("file://"):]
            elif url.startswith("http"):
                os.makedirs(COVER_CACHE, exist_ok=True)
                path = os.path.join(COVER_CACHE, hashlib.sha1(url.encode()).hexdigest())
                if not os.path.exists(path):
                    urllib.request.urlretrieve(url, path)
            if path:
                s = COVER * (self.get_scale_factor() or 1)
                full = GdkPixbuf.Pixbuf.new_from_file(path)
                w, h = full.get_width(), full.get_height()
                side = min(w, h)
                pix = full.new_subpixbuf((w - side) // 2, (h - side) // 2, side, side) \
                          .scale_simple(s, s, GdkPixbuf.InterpType.HYPER)
        except Exception:
            pix = None
        GLib.idle_add(self.set_cover, pix)

    def set_cover(self, pix):
        self.cover_pix = pix
        self.cover.queue_draw()
        return False

    def draw_cover(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        rounded(cr, 0, 0, w, h, sc(10))
        if self.cover_pix is not None:
            cr.save()
            cr.clip()
            cr.scale(w / self.cover_pix.get_width(), h / self.cover_pix.get_height())
            Gdk.cairo_set_source_pixbuf(cr, self.cover_pix, 0, 0)
            cr.paint()
            cr.restore()
        else:
            cr.set_source_rgba(*rgba(self.pal["surface_high"]))
            cr.fill()
            layout = PangoCairo.create_layout(cr)
            fd = Pango.FontDescription.from_string(ICON_FONT)
            fd.set_absolute_size(sc(34) * Pango.SCALE)
            layout.set_font_description(fd)
            layout.set_text(I["music"], -1)
            ink, _ = layout.get_pixel_extents()
            cr.move_to((w - ink.width) / 2 - ink.x, (h - ink.height) / 2 - ink.y)
            cr.set_source_rgba(*rgba(self.pal["primary"], 0.7))
            PangoCairo.show_layout(cr, layout)
        return True

    def progress_tick(self):
        if self.prog[2] and self.prog[1]:
            self.progress.queue_draw()
        return True

    def draw_progress(self, widget, cr):
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        pos, length, playing = self.prog
        if playing:
            pos += time.time() - self.prog_at
        frac = max(0.0, min(1.0, pos / length)) if length else 0.0
        r = h / 2
        rounded(cr, 0, 0, w, h, r)
        cr.set_source_rgba(*rgba(self.pal["on_surface"], 0.14))
        cr.fill()
        if frac > 0:
            fw = max(h, w * frac)
            rounded(cr, 0, 0, fw, h, r)
            cr.set_source_rgba(*rgba(self.pal["primary"]))
            cr.fill()
        return True

    def on_media(self, _b):
        if self.player:
            run("playerctl", "-p", self.player, "play-pause")
            GLib.timeout_add(300, lambda: (threading.Thread(target=self.poll_media, daemon=True).start(), False)[1])

    def on_media_press(self, _w, event):
        if event.button == 3:
            self.launch(script("player_popup.py"))
            return True
        return False

    # часы
    def build_clock(self):
        box = Gtk.Box()
        box.get_style_context().add_class("card")
        inner = Gtk.Box(spacing=sc(18))
        inner.set_margin_top(sc(14))
        inner.set_margin_bottom(sc(14))
        inner.set_margin_start(sc(18))
        inner.set_margin_end(sc(18))
        self.lbl_clock = Gtk.Label()
        self.lbl_clock.get_style_context().add_class("clock")
        col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=sc(4))
        col.set_valign(Gtk.Align.CENTER)
        self.lbl_day = Gtk.Label(xalign=0)
        self.lbl_day.get_style_context().add_class("date")
        self.lbl_date = Gtk.Label(xalign=0)
        self.lbl_date.get_style_context().add_class("date-dim")
        col.pack_start(self.lbl_day, False, False, 0)
        col.pack_start(self.lbl_date, False, False, 0)
        inner.pack_start(self.lbl_clock, False, False, 0)
        inner.pack_start(col, True, True, 0)
        box.pack_start(inner, True, True, 0)
        self.update_clock()
        return box

    def update_clock(self):
        days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля",
                  "августа", "сентября", "октября", "ноября", "декабря"]
        t = time.localtime()
        self.lbl_clock.set_text(time.strftime("%H:%M", t))
        self.lbl_day.set_text(days[t.tm_wday])
        self.lbl_date.set_text("%d %s" % (t.tm_mday, months[t.tm_mon - 1]))

    # плитки
    def warmth_popover(self, tile):
        """ПКМ по «Ночному свету» — ползунок теплоты (night_mode.py on N: заодно и
        включает). 0 — почти нейтрально, 100 — самый тёплый (2800 K)."""
        sys.path.insert(0, HERE)
        import night_mode
        st = night_mode.read_state()           # (вкл, время, теплота)
        cur = st[2] if len(st) > 2 and st[2] is not None else 65
        pop = Gtk.Popover.new(tile)
        pop.set_position(Gtk.PositionType.TOP)
        box = Gtk.Box(spacing=sc(10))
        box.set_margin_start(sc(12))
        box.set_margin_end(sc(12))
        box.set_margin_top(sc(10))
        box.set_margin_bottom(sc(10))
        ic = Gtk.Label(label=I["night"])
        # не «sc»: так зовётся функция масштаба, локальное имя её перекрывало
        # (UnboundLocalError на sc(12) — ПКМ молча не открывал ползунок, 08.10)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        scale.get_style_context().add_class("warmth")
        scale.set_draw_value(False)
        scale.set_value(int(cur or 65))
        val = Gtk.Label(label="%d%%" % int(cur or 65))
        val.get_style_context().add_class("warmth-val")
        pend = {"id": None}

        def apply():
            pend["id"] = None
            v = int(scale.get_value())

            def work():
                run(*script("night_mode.py", "on", str(v)), timeout=6)
                tile._poll()
            threading.Thread(target=work, daemon=True).start()
            return False

        def changed(_s):
            val.set_text("%d%%" % int(scale.get_value()))
            if pend["id"]:
                GLib.source_remove(pend["id"])
            pend["id"] = GLib.timeout_add(200, apply)
        scale.connect("value-changed", changed)
        box.pack_start(ic, False, False, 0)
        box.pack_start(scale, True, True, 0)
        box.pack_start(val, False, False, 0)
        pop.add(box)
        box.show_all()
        pop.popup()

    def build_tiles(self):
        grid = Gtk.Grid(row_spacing=sc(10), column_spacing=sc(10))
        grid.set_row_homogeneous(True)
        grid.set_column_homogeneous(True)
        self.tiles = [
            Tile(I["wifi"], "Wi-Fi", I["wifi_off"], wifi_get, wifi_toggle),
            Tile(I["bt"], "Bluetooth", I["bt_off"], bt_get, bt_toggle),
            Tile(I["coffee"], "Кофеин", I["coffee"], caffeine_get, caffeine_toggle, kind="coffee",
                 right=lambda t, e: t.run_bg(caffeine_taurine, t.extra)),
            Tile(I["night"], "Ночной свет", I["night"], night_get, night_toggle,
                 right=lambda t, e: self.warmth_popover(t)),
            Tile(I["bell_off"], "Не беспок.", I["bell"], dnd_get, dnd_toggle),
            Tile(I["balanced"], "Баланс", I["balanced"], power_get, power_toggle, kind="power",
                 right=lambda t, e: t.run_bg(power_saver, None)),
        ]
        tips = ["Wi-Fi вкл/выкл", "Bluetooth вкл/выкл",
                "ЛКМ — кофеин: Savage Mode, без сна.\n"
                "ПКМ — кофеин + таурин: ещё и экран не гаснет и не запирается",
                "ЛКМ — ночной свет вкл/выкл.\nПКМ — теплота", "Не беспокоить (swaync)",
                "ЛКМ — баланс ↔ мощность.\nПКМ — экономия"]
        for i, (t, tip) in enumerate(zip(self.tiles, tips)):
            t.set_tooltip_text(tip)
            grid.attach(t, i % 2, i // 2, 1, 1)
        return grid

    # ── общее ─────────────────────────────────────────────────────────────
    def tick(self):
        self.update_clock()
        self.lbl_up.set_text("Работает: " + fmt_uptime())
        threading.Thread(target=self.poll_media, daemon=True).start()
        return True

    def on_key(self, _w, event):
        k = event.keyval
        if k == Gdk.KEY_Escape:
            self.quit()
            return True
        # Поле пароля Wi-Fi и ползунки забирают свои клавиши себе; остальное,
        # как и раньше, закрывает панель.
        focus = self.get_focus()
        if isinstance(focus, Gtk.Entry):
            return False
        if isinstance(focus, Gtk.Scale) and k in (
                Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down,
                Gdk.KEY_Page_Up, Gdk.KEY_Page_Down, Gdk.KEY_Home, Gdk.KEY_End):
            return False
        if k == Gdk.KEY_space and self.player and self.current_key == "home":
            self.on_media(None)
            return True
        self.quit()
        return True

    def quit(self, *_a):
        self.vis.stop()
        Gtk.main_quit()
        return False


if __name__ == "__main__":
    # SIGTERM (второй щелчок по пилюле, single_instance): погасить cava и выйти
    # СРАЗУ, через os._exit. Раньше здесь был Gtk.main_quit — и цикл GTK иногда
    # не завершался: панель висела, перехватывала щелчки, и закрывалась только
    # третьим щелчком, когда второй SIGTERM добивал процесс (30.09.2026;
    # воспроизведено: «QUIT called», а Gtk.main не вернулся).
    def on_term(*_a):
        try:
            win.vis.stop()
        finally:
            os._exit(0)
    signal.signal(signal.SIGTERM, on_term)
    win = ControlCenter()
    win.show_all()
    Gtk.main()
