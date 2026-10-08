#!/usr/bin/env python3
"""Свой экран блокировки на gtk-session-lock — с настоящим наведением. 30.09.2026.

    jarvis_lock.py             заблокировать сеанс
    jarvis_lock.py --dry-run   кнопки питания только печатают команду (для проверок)

Зачем: у hyprlock 0.9.6 наведения нет вовсе (у надписей только onclick), а
Пользователь дважды просил, чтобы кнопки питания подсвечивались под указателем
(«Я хочу обводку»). Здесь экран рисуется своим кодом, поэтому под указателем
у кнопки появляется обводка и подложка.

Включается НЕ сам: scripts/lockscreen зовёт его, только если в
~/.config/hypr/state/lock-engine написано «jarvis». Иначе — hyprlock, как раньше.

БЕЗОПАСНОСТЬ
  * Пароль проверяет только PAM, служба «hyprlock» (/etc/pam.d/hyprlock, та же,
    что у hyprlock): pam_authenticate, затем pam_acct_mgmt. Никаких обходов,
    переменных окружения и тестовых заглушек нет. Разблокировка — только после
    успеха PAM.
  * Пароль не пишется ни в журнал, ни на диск; буфер затирается нулями после
    каждой попытки, поле очищается. Пустой пароль не отправляется (иначе
    случайный Enter засчитался бы faillock-у как ошибка).
  * Протокол ext-session-lock держит сеанс запертым, даже если этот процесс
    умрёт. На этот случай scripts/lockscreen сам запускает hyprlock — он
    подхватывает блокировку. Любая неожиданная ошибка в обработчиках здесь
    нарочно роняет процесс (код 5), чтобы не остаться с экраном, на котором
    нельзя ввести пароль: hyprlock подхватит.

КОДЫ ВЫХОДА (их читает scripts/lockscreen)
    0  разблокирован паролем
    2  не удалось заблокировать (протокол не поддержан, композитор отказал,
       нет ответа) — сеанс НЕ заперт, нужен hyprlock немедленно
    3  уже запущен (второй SUPER+L) — ничего не делать
    4  композитор снял блокировку сам — перестраховка: hyprlock
    5  ошибка в коде, пока экран заперт — hyprlock подхватывает
  (убит сигналом — 128+N, тоже hyprlock)

ВИД — как у hyprlock «Как сейчас» (lock_style.py prepare current): размытый и
затемнённый снимок каждого монитора (grim до блокировки + PIL), часы, дата,
круглый аватар, имя, поле пароля с приветствием, раскладка, Caps Lock, заряд и
сеть в верхних углах. Форма — на MSI (DP-4), если он есть, иначе на мониторе с
фокусом; на остальных — витрина: крупные часы и дата. Шрифт пиксельный
(PxPlus HP 100LX 6x8 Jarvis, только 16/24/32/… px), значки — Nerd Font Propo,
цвета — popup_theme.palette().

КНОПКИ ПИТАНИЯ снизу по центру: Выход, Сон, Перезагрузка, Выключение.
Сон — сразу (сеанс остаётся запертым). Остальные — отсчёт 5 с кольцом, как в
power_menu.py: второй щелчок по той же кнопке — сразу; Esc, любая клавиша или
щелчок мимо — отмена.

Клавиши: Enter — проверить пароль, Esc — очистить поле / отменить отсчёт,
Backspace, Ctrl+Backspace / Ctrl+U — стереть всё.

Мониторы, подключённые при запертом экране, получают свою поверхность
(фон — цвет палитры: снимок уже не сделать); отключённые — убираются; если
ушёл монитор с формой, форма переезжает на другой. Часы — раз в секунду
проверка, перерисовка раз в минуту; заряд и сеть — раз в 30 с.
"""
import ctypes
import ctypes.util
import datetime
import fcntl
import functools
import io
import json
import locale
import os
import pwd
import shlex
import signal
import subprocess
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
DRY_RUN = "--dry-run" in sys.argv

EXIT_OK, EXIT_NOLOCK, EXIT_RUNNING, EXIT_LOST, EXIT_CRASH = 0, 2, 3, 4, 5

PAM_SERVICE = "hyprlock"            # /etc/pam.d/hyprlock — читаем, не меняем
PIXEL = "PxPlus HP 100LX 6x8 Jarvis"
ICONS = "JetBrainsMono Nerd Font Propo"
MIXED = PIXEL + ", " + ICONS         # Pango берёт недостающие глифы из второго
FORM_MONITOR = ("Microstep", "MAG 255XF")   # как FORM_MONITOR в lock_style.py
AVATAR = os.path.join(HOME, ".cache/avatar.png")
GREETING_FILE = os.path.join(HOME, ".cache/hyprlock-greeting.conf")
ICON_DIR = os.path.join(HOME, ".cache/lock-style/icons")
COUNTDOWN = 5
FRAME_MS = 33                        # кольцо отсчёта — ~30 кадров/с, только пока идёт

# (ключ, подпись, значок, с отсчётом?) — порядок слева направо
ACTIONS = [
    ("logout", "Выход", "\U000f0343", True),
    ("suspend", "Сон", "\U000f0904", False),
    ("reboot", "Перезагрузка", "\U000f0709", True),
    ("shutdown", "Выключение", "\U000f0425", True),
]
BTN_D = 64                           # диаметр кнопки, px
BTN_STEP = 88                        # шаг между центрами
BTN_FROM_BOTTOM = 100                # центр кнопок от нижнего края


def log(msg):
    print("jarvis_lock: %s" % msg, file=sys.stderr, flush=True)


def on_niri():
    return bool(os.environ.get("NIRI_SOCKET")) and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")


# ── один экземпляр ────────────────────────────────────────────────────────
def single_instance():
    """flock на файл в XDG_RUNTIME_DIR, свой для каждого WAYLAND_DISPLAY.
    Ядро снимает flock, когда процесс умирает (даже от SIGKILL)."""
    rt = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    path = os.path.join(rt, "jarvis-lock-%s.lock" % os.environ.get("WAYLAND_DISPLAY", "wayland-0"))
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log("уже запущен")
        sys.exit(EXIT_RUNNING)
    return fd


# ── мониторы и снимки (до импорта GTK — идут параллельно с ним) ───────────
def outputs():
    """[{name, make, model, x, y, focused}] — из niri или Hyprland."""
    try:
        if on_niri():
            r = subprocess.run(["niri", "msg", "-j", "outputs"], capture_output=True,
                               text=True, timeout=3)
            focused = ""
            try:
                f = subprocess.run(["niri", "msg", "-j", "focused-output"], capture_output=True,
                                   text=True, timeout=3)
                focused = (json.loads(f.stdout) or {}).get("name", "")
            except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
                pass
            out = []
            for name, o in json.loads(r.stdout).items():
                lg = o.get("logical") or {}
                if not lg:
                    continue            # выключенный выход
                out.append({"name": name, "make": o.get("make") or "", "model": o.get("model") or "",
                            "x": lg.get("x", 0), "y": lg.get("y", 0), "focused": name == focused})
            return out
        r = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=3)
        return [{"name": m["name"], "make": m.get("make", ""), "model": m.get("model", ""),
                 "x": m.get("x", 0), "y": m.get("y", 0), "focused": bool(m.get("focused"))}
                for m in json.loads(r.stdout)]
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return []


def blur_shot(data):
    """Снимок PPM -> уменьшенный в 4 раза, размытый и затемнённый RGB-кадр PIL.
    Настройки — как у фона «Как сейчас» в hyprlock: blur 3×8, contrast 1.3,
    brightness 0.35, vibrancy ~0.2. Уменьшение перед размытием — в разы быстрее,
    а при растягивании обратно размытый кадр не теряет ничего."""
    from PIL import Image, ImageEnhance, ImageFilter
    im = Image.open(io.BytesIO(data))
    im.load()
    w, h = im.size
    small = im.convert("RGB").reduce(4) if min(w, h) >= 64 else im.convert("RGB")
    small = small.filter(ImageFilter.GaussianBlur(6))
    small = ImageEnhance.Color(small).enhance(1.2)
    small = ImageEnhance.Contrast(small).enhance(1.3)
    small = ImageEnhance.Brightness(small).enhance(0.35)
    return small


class Shots:
    """grim по каждому выходу в фоне; результат — {имя: кадр PIL}."""

    def __init__(self, outs):
        self.result = {}
        self.threads = []
        for o in outs:
            t = threading.Thread(target=self._one, args=(o["name"],), daemon=True)
            t.start()
            self.threads.append(t)

    def _one(self, name):
        try:
            p = subprocess.run(["grim", "-t", "ppm", "-o", name, "-"], capture_output=True, timeout=4)
            if p.returncode == 0 and p.stdout:
                self.result[name] = blur_shot(p.stdout)
        except Exception as e:           # без фона — не беда, будет цвет палитры
            log("снимок %s: %s" % (name, e))

    def wait(self, timeout=5.0):
        end = time.monotonic() + timeout
        for t in self.threads:
            t.join(max(0.0, end - time.monotonic()))
        return dict(self.result)


# ── заставка поверх формы (screensaver.py lockmode, 04.10.2026) ───────────
# Заставка была на экране, когда запирали сеанс, — стартуем в режиме заставки:
# та же сцена (время, зерно) на наших поверхностях, первая клавиша / щелчок /
# рывок мыши её гасит, под ней — форма. Сломалась заставка — показываем форму,
# блокировке это не мешает. По SIGUSR1 (screensaver.py arm, бездействие уже под
# блокировкой) заставка включается сама.
_SS = None


def saver_module():
    global _SS
    if _SS is None:
        try:
            if HERE not in sys.path:
                sys.path.insert(0, HERE)
            import screensaver as m
            _SS = m
        except Exception as e:
            log("screensaver.py недоступен: %s" % e)
            _SS = False
    return _SS or None


def saver_handoff():
    try:
        ss = saver_module()
        return ss.handoff_info() if ss else None
    except Exception as e:
        log("заставка: %s" % e)
        return None


class SavedShots:
    """Фон формы при подхвате заставки: снимки сделала сама заставка ДО показа
    (grim сейчас снял бы её саму), уже размытые и затемнённые."""

    def __init__(self, info):
        self.dir = info.get("bg") or ""

    def wait(self, timeout=0):
        out = {}
        try:
            from PIL import Image
            for n in os.listdir(self.dir):
                if n.endswith(".png") and not n.startswith("."):
                    im = Image.open(os.path.join(self.dir, n))
                    im.load()
                    out[n[:-4]] = im.convert("RGB")
        except Exception as e:
            log("снимки заставки: %s" % e)
        return out


# ── PAM (ctypes, libpam.so.0) ─────────────────────────────────────────────
PAM_SUCCESS, PAM_AUTH_ERR, PAM_MAXTRIES, PAM_NEW_AUTHTOK_REQD = 0, 7, 11, 12
PAM_CONV_ERR, PAM_BUF_ERR = 19, 5
PAM_PROMPT_ECHO_OFF, PAM_PROMPT_ECHO_ON, PAM_ERROR_MSG, PAM_TEXT_INFO = 1, 2, 3, 4


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int,
                             ctypes.POINTER(ctypes.POINTER(PamMessage)),
                             ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV_FUNC), ("appdata_ptr", ctypes.c_void_p)]


_libpam = ctypes.CDLL("libpam.so.0")
_libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
_libc.calloc.restype = ctypes.c_void_p
_libc.calloc.argtypes = [ctypes.c_size_t, ctypes.c_size_t]
_libc.malloc.restype = ctypes.c_void_p
_libc.malloc.argtypes = [ctypes.c_size_t]
_libc.free.argtypes = [ctypes.c_void_p]
_libpam.pam_start.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(PamConv),
                              ctypes.POINTER(ctypes.c_void_p)]
_libpam.pam_start.restype = ctypes.c_int
_libpam.pam_authenticate.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libpam.pam_authenticate.restype = ctypes.c_int
_libpam.pam_acct_mgmt.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libpam.pam_acct_mgmt.restype = ctypes.c_int
_libpam.pam_end.argtypes = [ctypes.c_void_p, ctypes.c_int]
_libpam.pam_end.restype = ctypes.c_int


def _c_strdup(data):
    """Копия байтов в памяти malloc (её освобождает сам PAM)."""
    n = len(data)
    p = _libc.malloc(n + 1)
    if not p:
        return None
    if n:
        view = (ctypes.c_char * n).from_buffer(data)
        ctypes.memmove(p, view, n)
        del view
    ctypes.memset(p + n, 0, 1)
    return p


def pam_check(user, secret):
    """Проверить пароль через PAM. secret — bytearray; вызывающий его затирает.
    Возвращает (успех, код PAM, [сообщения модулей])."""
    msgs = []
    user_b = bytearray(user.encode())

    def conv(n, msg, resp, _data):
        if n <= 0:
            return PAM_CONV_ERR
        arr = _libc.calloc(n, ctypes.sizeof(PamResponse))
        if not arr:
            return PAM_BUF_ERR
        out = ctypes.cast(arr, ctypes.POINTER(PamResponse))
        for i in range(n):
            m = msg[i].contents
            if m.msg_style == PAM_PROMPT_ECHO_OFF:
                out[i].resp = _c_strdup(secret)
            elif m.msg_style == PAM_PROMPT_ECHO_ON:
                out[i].resp = _c_strdup(user_b)
            elif m.msg_style in (PAM_ERROR_MSG, PAM_TEXT_INFO):
                if m.msg:
                    msgs.append(m.msg.decode("utf-8", "replace").strip())
        resp[0] = out
        return PAM_SUCCESS

    cb = CONV_FUNC(conv)
    pconv = PamConv(cb, None)
    handle = ctypes.c_void_p()
    rc = _libpam.pam_start(PAM_SERVICE.encode(), user.encode(), ctypes.byref(pconv),
                           ctypes.byref(handle))
    if rc != PAM_SUCCESS:
        return False, rc, msgs
    rc = _libpam.pam_authenticate(handle, 0)
    if rc == PAM_SUCCESS:
        rc = _libpam.pam_acct_mgmt(handle, 0)
    _libpam.pam_end(handle, rc)
    # Пароль верный, но просрочен (NEW_AUTHTOK_REQD): личность подтверждена —
    # пускаем, иначе запереться можно было бы только до TTY.
    return rc in (PAM_SUCCESS, PAM_NEW_AUTHTOK_REQD), rc, msgs


def wipe(buf):
    if buf:
        view = (ctypes.c_char * len(buf)).from_buffer(buf)
        ctypes.memset(view, 0, len(buf))
        del view


# ── запуск ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    _INSTANCE_FD = single_instance()
    OUTS = outputs()
    SAVER = saver_handoff()
    SHOTS = SavedShots(SAVER) if SAVER else Shots(OUTS)

try:
    import cairo
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GdkPixbuf", "2.0")
    gi.require_version("Pango", "1.0")
    gi.require_version("PangoCairo", "1.0")
    gi.require_version("GtkSessionLock", "0.1")
    from gi.repository import Gdk, GdkPixbuf, GLib, Gtk, GtkSessionLock, Pango, PangoCairo
except (ImportError, ValueError) as e:
    log("нет GTK/gtk-session-lock: %s" % e)
    sys.exit(EXIT_NOLOCK)

sys.path.insert(0, HERE)
import popup_theme  # noqa: E402


def guarded(fn):
    """Необработанная ошибка в обработчике — выйти с кодом 5: сеанс остаётся
    запертым протоколом, lockscreen запустит hyprlock. Лучше так, чем экран,
    на котором не работает ввод пароля."""
    @functools.wraps(fn)
    def wrap(*a, **k):
        try:
            return fn(*a, **k)
        except Exception:
            traceback.print_exc()
            sys.stderr.flush()
            os._exit(EXIT_CRASH)
    return wrap


def rgba(hexcolor, a=1.0):
    c = hexcolor.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)


# Cozette вместо PxPlus (08.10.2026): правило 61-cozette-trial.conf режет любой запрос
# PxPlus крупнее 35 px до 39 px — часы 128/160 px сжимались втрое. Здесь просим
# CozetteVector напрямую, кратно 13 (чёткие размеры): 16 → 13, 32 → 26, 128 → 130, 160 → 156.
COZETTE = os.path.exists(os.path.join(HOME, ".config/fontconfig/conf.d/61-cozette-trial.conf"))
# Подгонка (cozette_fit.py): поля ввода в меру 13-px текста — 320×40 → 288×34
FIT = COZETTE and os.path.exists(os.path.join(HOME, ".config/hypr/state/cozette-fit"))


def cozette_px(px):
    return 13 * max(1, int(px / 13 + 0.5)) if px > 16 else 13


def layout(cr, text, family, px, bold=False):
    if COZETTE and PIXEL in family:
        family, px = family.replace(PIXEL, "CozetteVector"), cozette_px(px)
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(family)
    fd.set_absolute_size(px * Pango.SCALE)
    if bold:
        fd.set_weight(Pango.Weight.BOLD)
    lay.set_font_description(fd)
    lay.set_text(text, -1)
    return lay


def show(cr, lay, x, y, anchor="center", shadow=False):
    """Текст по логической рамке: anchor center / left / right, y — середина строки."""
    _ink, lg = lay.get_pixel_extents()
    if anchor == "center":
        tx = x - lg.width / 2
    elif anchor == "right":
        tx = x - lg.width
    else:
        tx = x
    ty = y - lg.height / 2
    if shadow:
        cr.save()
        cr.set_source_rgba(0, 0, 0, 0.45)
        cr.move_to(round(tx) + 2, round(ty) + 3)
        PangoCairo.show_layout(cr, lay)
        cr.restore()
    cr.move_to(round(tx), round(ty))
    PangoCairo.show_layout(cr, lay)
    cr.new_path()      # иначе следующая дуга потянет линию от точки текста
    return lg.width


SPEEDO = "\U000f04c5"          # спидометр Savage Mode — первым в строке заряда (lock_battery.sh)


def vivid_hex(pal):
    """Насыщенный оттенок обоев — им светится значок в баре."""
    try:
        v = open(os.path.join(HOME, ".cache/matugen/vivid.txt")).read().strip()
        if len(v.lstrip("#")) == 6:
            return v
    except OSError:
        pass
    return pal["primary"]


def show_battery(cr, text, right, y, pal, awake):
    """Заряд в правом углу. Включено «Не отключать экран» — спидометр светится, как
    в баре (02.10.2026: «в экран блокировки такое же, чтобы было понятно»).
    Размытия у cairo нет, свечение — значок, отпечатанный кольцами вокруг себя."""
    import math
    lay = layout(cr, text, MIXED, 16)
    _ink, lg = lay.get_pixel_extents()
    tx, ty = round(right - lg.width), round(y - lg.height / 2)
    glow = awake and text.startswith(SPEEDO)
    if glow:
        g = layout(cr, SPEEDO, MIXED, 16)
        r_, g_, b_, _a = rgba(vivid_hex(pal))
        for rad, alpha in ((7, 0.03), (5, 0.045), (3.2, 0.06)):   # слабее — значок должен читаться
            cr.set_source_rgba(r_, g_, b_, alpha)
            for k in range(14):
                ang = 2 * math.pi * k / 14
                cr.move_to(tx + rad * math.cos(ang), ty + rad * math.sin(ang))
                PangoCairo.show_layout(cr, g)
    cr.set_source_rgba(*rgba(pal["secondary"]))
    cr.move_to(tx, ty)
    PangoCairo.show_layout(cr, lay)
    if glow:                               # сам значок — светлым акцентом поверх ореола
        cr.set_source_rgba(*rgba(pal["primary"]))
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, g)
    cr.new_path()


def show_ink_centered(cr, lay, cx, cy):
    """Серединой ЧЕРНИЛ в точку — для значков Nerd Font (у глифов разные поля)."""
    ink, _lg = lay.get_pixel_extents()
    cr.move_to(round(cx - ink.width / 2 - ink.x), round(cy - ink.height / 2 - ink.y))
    PangoCairo.show_layout(cr, lay)
    cr.new_path()


def rounded(cr, x, y, w, h, r):
    r = min(r, h / 2, w / 2)
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -1.5708, 0)
    cr.arc(x + w - r, y + h - r, r, 0, 1.5708)
    cr.arc(x + r, y + h - r, r, 1.5708, 3.1416)
    cr.arc(x + r, y + r, r, 3.1416, 4.7124)
    cr.close_path()


def pil_to_surface(im):
    w, h = im.size
    data = bytearray(im.convert("RGBA").tobytes("raw", "BGRA"))
    stride = cairo.ImageSurface.format_stride_for_width(cairo.FORMAT_RGB24, w)
    if stride != w * 4:
        return None
    return cairo.ImageSurface.create_for_data(data, cairo.FORMAT_RGB24, w, h, stride)


def run_text(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def greeting():
    try:
        with open(GREETING_FILE, encoding="utf-8") as f:
            for line in f:
                if line.startswith("$GREETING"):
                    return line.split("=", 1)[1].strip()
    except OSError:
        pass
    h = datetime.datetime.now().hour
    return ("Good night, Sir" if h < 6 else "Good morning, Sir" if h < 12
            else "Good afternoon, Sir" if h < 18 else "Good evening, Sir")


def power_command(key):
    if key == "logout":
        if on_niri():
            return ["niri", "msg", "action", "quit", "--skip-confirmation"]
        return ["hyprctl", "dispatch", "hl.dsp.exit()"]
    return {"suspend": ["systemctl", "suspend"], "reboot": ["systemctl", "reboot"],
            "shutdown": ["systemctl", "poweroff"]}[key]


class LockWindow(Gtk.Window):
    """Поверхность блокировки одного монитора. Рисует всё сама (DrawingArea)."""

    def __init__(self, app, monitor, out_name, shot):
        super().__init__()
        self.app, self.monitor, self.out_name = app, monitor, out_name
        self.shot = shot                         # кадр PIL или None
        self.bg_small = pil_to_surface(shot) if shot is not None else None
        self.bg_cache = None                     # (w, h, scale, surface)
        self.hover = None                        # индекс кнопки под указателем
        self.cursor_name = None
        self.set_app_paintable(True)
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.ENTER_NOTIFY_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", self.on_leave)
        self.area.connect("button-press-event", self.on_press)
        self.area.connect("realize", self.on_realize)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)

    @property
    def is_form(self):
        return self.app.form is self

    # ── геометрия ─────────────────────────────────────────────────────────
    def size(self):
        return self.area.get_allocated_width(), self.area.get_allocated_height()

    def buttons(self):
        """[(cx, cy)] центров кнопок питания."""
        w, h = self.size()
        n = len(ACTIONS)
        x0 = w / 2 - BTN_STEP * (n - 1) / 2
        return [(round(x0 + i * BTN_STEP), h - BTN_FROM_BOTTOM) for i in range(n)]

    def hit(self, x, y):
        if not self.is_form:
            return None
        r = BTN_D / 2 + 4
        for i, (cx, cy) in enumerate(self.buttons()):
            if (x - cx) ** 2 + (y - cy) ** 2 <= r * r:
                return i
        return None

    def queue_buttons(self):
        """Перерисовать только полосу кнопок и подсказку под ними."""
        w, h = self.size()
        top = h - BTN_FROM_BOTTOM - BTN_D
        self.area.queue_draw_area(0, max(0, top), w, h - top)

    # ── ввод ──────────────────────────────────────────────────────────────
    @guarded
    def on_realize(self, _w):
        if self.app.saver is not None:
            self.set_blank(True)

    def set_blank(self, blank):
        """Курсор под заставкой прячем, после — обычный."""
        gw = self.area.get_window()
        if gw is None:
            return
        if blank:
            gw.set_cursor(Gdk.Cursor.new_for_display(self.get_display(), Gdk.CursorType.BLANK_CURSOR))
            self.cursor_name = "blank"
        else:
            self.cursor_name = "default"
            gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), "default"))

    @guarded
    def on_motion(self, _w, ev):
        if self.app.saver is not None:
            self.app.saver_motion(ev.x_root, ev.y_root)
            return False
        self.set_hover(self.hit(ev.x, ev.y))
        return False

    @guarded
    def on_leave(self, _w, _ev):
        self.set_hover(None)
        return False

    def set_hover(self, idx):
        if self.app.saver is not None:
            return
        if idx != self.hover:
            self.hover = idx
            self.queue_buttons()
        name = "pointer" if idx is not None else "default"
        gw = self.area.get_window()
        if gw is not None and name != self.cursor_name:
            self.cursor_name = name
            gw.set_cursor(Gdk.Cursor.new_from_name(self.get_display(), name))

    @guarded
    def on_press(self, _w, ev):
        if self.app.saver is not None and self.app.saver["leaving"] is None:
            self.app.saver_wake()             # щелчок только будит
            return True
        if ev.type != Gdk.EventType.BUTTON_PRESS or ev.button != 1:
            return True
        idx = self.hit(ev.x, ev.y)
        if idx is not None:
            self.app.activate(idx)
        elif self.app.pending is not None:
            self.app.cancel()                 # щелчок мимо — отмена отсчёта
        return True

    @guarded
    def on_key(self, _w, ev):
        self.app.on_key(ev)
        return True

    # ── рисование ─────────────────────────────────────────────────────────
    def background(self, cr, w, h):
        pal = self.app.pal
        if self.bg_small is None:
            cr.set_source_rgba(*rgba(pal["surface"]))
            cr.paint()
            return
        s = self.get_scale_factor()
        if not self.bg_cache or self.bg_cache[:3] != (w, h, s):
            surf = cairo.ImageSurface(cairo.FORMAT_RGB24, w * s, h * s)
            c2 = cairo.Context(surf)
            sw, sh = self.bg_small.get_width(), self.bg_small.get_height()
            c2.scale(w * s / sw, h * s / sh)
            c2.set_source_surface(self.bg_small, 0, 0)
            pat = c2.get_source()
            pat.set_filter(cairo.FILTER_BILINEAR)
            pat.set_extend(cairo.EXTEND_PAD)
            c2.paint()
            surf.set_device_scale(s, s)
            self.bg_cache = (w, h, s, surf)
        cr.set_source_surface(self.bg_cache[3], 0, 0)
        cr.paint()

    @guarded
    def on_draw(self, _w, cr):
        w, h = self.size()
        if self.app.saver is not None and self.app.draw_saver(self, cr, w, h):
            return True
        self.draw_lock(cr, w, h)
        return True

    def draw_lock(self, cr, w, h):
        self.background(cr, w, h)
        if self.is_form:
            self.draw_form(cr, w, h)
        else:
            self.draw_showcase(cr, w, h)

    def draw_showcase(self, cr, w, h):
        pal, a = self.app.pal, self.app
        cx, cy = w / 2, h / 2
        cr.set_source_rgba(*rgba(pal["primary"]))
        show(cr, layout(cr, a.clock, PIXEL, 160), cx, cy - 80, shadow=True)
        cr.set_source_rgba(*rgba(pal["on_surface"]))
        show(cr, layout(cr, a.date, PIXEL, 32), cx, cy + 40, shadow=True)

    def draw_form(self, cr, w, h):
        pal, a = self.app.pal, self.app
        cx, cy = w / 2, h / 2

        # Часы и дата
        cr.set_source_rgba(*rgba(pal["primary"]))
        show(cr, layout(cr, a.clock, PIXEL, 128), cx, cy - 230, shadow=True)
        cr.set_source_rgba(*rgba(pal["on_surface"]))
        show(cr, layout(cr, a.date, PIXEL, 32), cx, cy - 140, shadow=True)

        # Аватар — круг 130 px с рамкой акцента, точно по центру (как в hyprlock)
        if a.avatar is not None:
            r = 65
            cr.new_path()
            cr.save()
            cr.arc(cx, cy, r, 0, 6.2832)
            cr.clip()
            Gdk.cairo_set_source_pixbuf(cr, a.avatar, cx - r, cy - r)
            cr.paint()
            cr.restore()
            cr.arc(cx, cy, r - 1.5, 0, 6.2832)
            cr.set_line_width(3)
            cr.set_source_rgba(*rgba(pal["primary"]))
            cr.stroke()

        field_bg = rgba(pal["surface_container"], 0.70)
        # Поле пользователя
        fw, fh = (288, 34) if FIT else (320, 40)
        fx, ix = cx - fw / 2, cx - fw / 2 + 24      # ix — центр значка в поле
        uy = cy + 100
        rounded(cr, fx, uy - fh / 2, fw, fh, fh / 2)
        cr.set_source_rgba(*field_bg)
        cr.fill()
        self.field_icon(cr, a.icon_user, "\U000f0004", ix, uy)
        cr.set_source_rgba(*rgba(pal["on_surface"]))
        show(cr, layout(cr, a.user, PIXEL, 16), cx, uy)

        # Поле пароля: рамка — акцент; проверка — secondary; ошибка — error;
        # Caps Lock — tertiary (как check/fail/capslock_color у hyprlock)
        py = cy + 155
        if a.checking:
            ring = rgba(pal["secondary"])
        elif a.failed and not a.pw:
            ring = rgba(pal["error"])
        elif a.caps:
            ring = rgba(pal["tertiary"])
        else:
            ring = rgba(pal["primary"], 0.6)
        rounded(cr, fx, py - fh / 2, fw, fh, fh / 2)
        cr.set_source_rgba(*field_bg)
        cr.fill_preserve()
        cr.set_line_width(2)
        cr.set_source_rgba(*ring)
        cr.stroke()
        self.field_icon(cr, a.icon_pass, "\U000f033e", ix, py)
        if a.checking:
            cr.set_source_rgba(*rgba(pal["secondary"]))
            show(cr, layout(cr, "Проверка…", PIXEL, 16), cx, py)
        elif a.pw:
            n = min(len(a.pw), 22)
            d, gap = 8, 5
            total = n * d + (n - 1) * gap
            x = cx - total / 2 + d / 2
            cr.set_source_rgba(*rgba(pal["on_surface"]))
            for i in range(n):
                cr.new_path()
                cr.arc(x + i * (d + gap), py, d / 2, 0, 6.2832)
                cr.fill()
        elif a.failed:
            cr.set_source_rgba(*rgba(pal["error"]))
            show(cr, layout(cr, "Неверный пароль (%d)" % a.failed, PIXEL, 16), cx, py)
        else:
            cr.set_source_rgba(*rgba(pal["on_surface_variant"]))
            show(cr, layout(cr, a.greeting, PIXEL, 16), cx, py)

        # Раскладка и Caps Lock под полем
        ly = cy + 210
        parts = [("\U000f030c " + a.layout, pal["secondary"])]
        if a.caps:
            parts.append(("\U000f0a9b Caps Lock", pal["tertiary"]))
        lays = [(layout(cr, t, MIXED, 16), c) for t, c in parts]
        gap = 32
        widths = [l.get_pixel_extents()[1].width for l, _c in lays]
        x = cx - (sum(widths) + gap * (len(lays) - 1)) / 2
        for (l, c), wd in zip(lays, widths):
            cr.set_source_rgba(*rgba(c))
            show(cr, l, x, ly, anchor="left")
            x += wd + gap
        # Сообщения PAM (например, faillock: «учётная запись заблокирована…»)
        if a.pam_note:
            cr.set_source_rgba(*rgba(pal["error"]))
            show(cr, layout(cr, a.pam_note, MIXED, 16), cx, ly + 36)

        # Углы: сеть слева, заряд справа
        cr.set_source_rgba(*rgba(pal["secondary"]))
        if a.net:
            show(cr, layout(cr, a.net, MIXED, 16), 36, 40, anchor="left")
        if a.battery:
            show_battery(cr, a.battery, w - 36, 40, pal, getattr(a, "awake", False))

        self.draw_buttons(cr, w, h)

    def field_icon(self, cr, pixbuf, glyph, x, y):
        if pixbuf is not None:
            Gdk.cairo_set_source_pixbuf(cr, pixbuf, x - pixbuf.get_width() / 2,
                                        y - pixbuf.get_height() / 2)
            cr.paint()
        else:
            cr.set_source_rgba(*rgba(self.app.pal["primary"]))
            show_ink_centered(cr, layout(cr, glyph, ICONS, 16), x, y)

    def draw_buttons(self, cr, w, h):
        pal, a = self.app.pal, self.app
        r = BTN_D / 2
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        for i, (cx, cy) in enumerate(self.buttons()):
            icon = ACTIONS[i][2]
            cr.new_path()      # каждая кнопка — с чистого пути, без хвоста от соседней
            if a.pending == i:
                left = a.remaining()
                err = pal["error"]
                cr.arc(cx, cy, r, 0, 6.2832)
                cr.set_source_rgba(*rgba(err, 0.16))
                cr.fill()
                cr.set_line_width(4)
                cr.arc(cx, cy, r - 2, 0, 6.2832)
                cr.set_source_rgba(*rgba(err, 0.25))
                cr.stroke()
                frac = max(0.0, min(1.0, left / COUNTDOWN))
                if frac > 0:
                    cr.new_path()
                    cr.arc(cx, cy, r - 2, -1.5708, -1.5708 + frac * 6.2832)
                    cr.set_source_rgba(*rgba(err))
                    cr.stroke()
                cr.set_source_rgba(*rgba(err))
                show_ink_centered(cr, layout(cr, str(max(1, int(left + 0.999))), PIXEL, 32), cx, cy)
                continue
            hover = self.hover == i
            if hover:
                # Наведение: подложка акцента, толстая обводка и мягкий ореол
                cr.arc(cx, cy, r + 5, 0, 6.2832)
                cr.set_line_width(4)
                cr.set_source_rgba(*rgba(pal["primary"], 0.28))
                cr.stroke()
                cr.arc(cx, cy, r, 0, 6.2832)
                cr.set_source_rgba(*rgba(pal["primary"], 0.22))
                cr.fill()
                cr.arc(cx, cy, r - 1.5, 0, 6.2832)
                cr.set_line_width(3)
                cr.set_source_rgba(*rgba(pal["primary"]))
                cr.stroke()
                cr.set_source_rgba(*rgba(pal["primary"]))
            else:
                cr.arc(cx, cy, r, 0, 6.2832)
                cr.set_source_rgba(0, 0, 0, 0.20)
                cr.fill()
                cr.arc(cx, cy, r - 1, 0, 6.2832)
                cr.set_line_width(2)
                cr.set_source_rgba(*rgba(pal["secondary"], 0.53))
                cr.stroke()
                cr.set_source_rgba(*rgba(pal["secondary"]))
            show_ink_centered(cr, layout(cr, icon, ICONS, 26), cx, cy)

        # Подсказка под кнопками: отсчёт — или имя кнопки под указателем
        hy = h - BTN_FROM_BOTTOM + BTN_D / 2 + 28
        if a.pending is not None:
            secs = max(1, int(a.remaining() + 0.999))
            text = "%s через %d с · ещё раз — сразу · Esc — отмена" % (ACTIONS[a.pending][1], secs)
            cr.set_source_rgba(*rgba(pal["error"]))
            show(cr, layout(cr, text, PIXEL, 16), w / 2, hy)
        elif self.hover is not None:
            cr.set_source_rgba(*rgba(pal["primary"]))
            show(cr, layout(cr, ACTIONS[self.hover][1], PIXEL, 16), w / 2, hy)


class Locker:
    def __init__(self, outs, shots):
        self.outs, self.shots = outs, shots
        self.pal = popup_theme.palette()
        self.user = pwd.getpwuid(os.getuid()).pw_name
        self.greeting = greeting()
        self.pw = []                   # символы пароля; не пишется никуда
        self.checking = False
        self.failed = 0
        self.pam_note = ""
        self.caps = False
        self.layout_names = []
        self.layout = "US"
        self.layout_query = None
        self.net = self.battery = ""
        self.pending = None
        self.deadline = 0.0
        self.timer = None
        self.windows = {}              # Gdk.Monitor -> LockWindow
        self.form = None
        self.locked = False
        self.exit_code = EXIT_NOLOCK
        self.saver = None              # заставка поверх формы (dict) или None
        self.saver_gen = 0
        self.saver_dead = False        # сломалась — больше не включать
        try:
            locale.setlocale(locale.LC_TIME, "")
        except locale.Error:
            pass
        self.clock, self.date = self.now()
        self.avatar = self.load_avatar()
        prim = self.pal["primary"].lstrip("#").lower()
        self.icon_user = self.load_icon("User-%s.png" % prim)
        self.icon_pass = self.load_icon("Password2-%s.png" % prim)

    # ── данные ────────────────────────────────────────────────────────────
    @staticmethod
    def now():
        t = time.localtime()
        return time.strftime("%H:%M", t), time.strftime("%A, %-d %B", t)

    @staticmethod
    def load_avatar():
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(AVATAR, 130, 130, False)
        except GLib.Error:
            return None

    @staticmethod
    def load_icon(name):
        try:
            return GdkPixbuf.Pixbuf.new_from_file_at_scale(os.path.join(ICON_DIR, name), 16, 16, True)
        except GLib.Error:
            return None

    def out_for(self, monitor):
        """Выход niri/Hyprland для монитора GDK — по положению (оно одинаковое)."""
        g = monitor.get_geometry()
        for o in self.outs:
            if o["x"] == g.x and o["y"] == g.y:
                return o
        return None

    def redraw(self):
        for win in self.windows.values():
            win.area.queue_draw()

    # ── монитор с формой ──────────────────────────────────────────────────
    def pick_form(self):
        wins = list(self.windows.values())
        if not wins:
            self.form = None
            return
        def is_msi(win):
            m = win.monitor
            return (m.get_manufacturer() or "") == FORM_MONITOR[0] and (m.get_model() or "") == FORM_MONITOR[1]
        msi = next((w for w in wins if is_msi(w)), None)
        if msi is not None:
            new = msi
        elif self.form in wins:
            new = self.form
        else:
            focused = {o["name"] for o in self.outs if o.get("focused")}
            new = next((w for w in wins if w.out_name in focused), wins[0])
        if new is not self.form:
            self.form = new
            self.redraw()

    def add_monitor(self, lock, monitor):
        if monitor in self.windows:
            return
        o = self.out_for(monitor)
        name = o["name"] if o else ""
        win = LockWindow(self, monitor, name, self.shots.get(name))
        self.windows[monitor] = win
        lock.new_surface(win, monitor)
        win.show_all()
        log("монитор добавлен: %s" % (name or monitor.get_model()))
        self.pick_form()

    def remove_monitor(self, monitor):
        win = self.windows.pop(monitor, None)
        if win is None:
            return
        try:
            GtkSessionLock.unmap_lock_window(win)
        except Exception as e:
            log("unmap: %s" % e)
        win.destroy()
        log("монитор убран: %s" % (win.out_name or monitor.get_model()))
        self.pick_form()

    # ── таймеры ───────────────────────────────────────────────────────────
    @guarded
    def tick(self):
        clock, date = self.now()
        if (clock, date) != (self.clock, self.date):
            self.clock, self.date = clock, date
            self.redraw()
        return True

    def refresh_corners(self):
        def work():
            bat = run_text([os.path.join(HERE, "lock_battery.sh")])
            net = run_text([os.path.join(HERE, "lock_net.sh")])
            try:                       # «Не отключать экран» — значок режима будет светиться
                awake = open(os.path.join(HOME, ".config/hypr/state/screen-awake")).read().strip() == "on"
            except OSError:
                awake = False
            GLib.idle_add(self.set_corners, bat, net, awake)
        threading.Thread(target=work, daemon=True).start()
        return True

    @guarded
    def set_corners(self, bat, net, awake=False):
        if (bat, net, awake) != (self.battery, self.net, getattr(self, "awake", False)):
            self.battery, self.net, self.awake = bat, net, awake
            if self.form is not None:
                self.form.area.queue_draw()
        return False

    def refresh_layout(self):
        self.layout_query = None

        def work():
            names, idx = [], 0
            try:
                if on_niri():
                    d = json.loads(run_text(["niri", "msg", "-j", "keyboard-layouts"]) or "{}")
                    names, idx = d.get("names", []), d.get("current_idx", 0)
                else:
                    d = json.loads(run_text(["hyprctl", "devices", "-j"]) or "{}")
                    kb = next((k for k in d.get("keyboards", []) if k.get("main")), None)
                    if kb:
                        names, idx = [kb.get("active_keymap", "")], 0
            except (ValueError, AttributeError):
                pass
            GLib.idle_add(self.set_layout, names, idx)
        threading.Thread(target=work, daemon=True).start()
        return False

    @staticmethod
    def short(name):
        n = (name or "").lower()
        if n.startswith("english"):
            return "US"
        if n.startswith("russian"):
            return "RU"
        return (name or "??")[:2].upper()

    @guarded
    def set_layout(self, names, idx):
        if names:
            self.layout_names = names
            self.set_group(idx)
        return False

    def set_group(self, idx):
        if self.layout_names and 0 <= idx < len(self.layout_names):
            text = self.short(self.layout_names[idx])
            if text != self.layout:
                self.layout = text
                if self.form is not None:
                    self.form.area.queue_draw()

    @guarded
    def on_keymap_state(self, keymap):
        caps = bool(keymap.get_caps_lock_state())
        if caps != self.caps:
            self.caps = caps
            if self.form is not None:
                self.form.area.queue_draw()
        # Могла смениться группа (раскладка) — спросить композитор; не чаще
        # одного запроса на пачку событий (Shift при наборе дёргает сигнал).
        if not self.layout_query:
            self.layout_query = GLib.timeout_add(150, self.refresh_layout)

    # ── пароль ────────────────────────────────────────────────────────────
    def on_key(self, ev):
        k = ev.keyval
        self.set_group(ev.group)
        if self.saver is not None and self.saver["leaving"] is None:
            self.saver_wake()             # клавиша только будит, в поле не идёт
            return
        if self.pending is not None:
            self.cancel()                 # любая клавиша — отмена отсчёта
            if k == Gdk.KEY_Escape:
                return
        if self.checking:
            return
        ctrl = ev.state & Gdk.ModifierType.CONTROL_MASK
        if k == Gdk.KEY_Escape or (ctrl and k in (Gdk.KEY_u, Gdk.KEY_U, Gdk.KEY_BackSpace)):
            self.clear()
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            self.submit()
        elif k == Gdk.KEY_BackSpace:
            if self.pw:
                self.pw.pop()
        else:
            u = Gdk.keyval_to_unicode(k)
            if u >= 32 and u != 127 and not ctrl and not (ev.state & Gdk.ModifierType.MOD1_MASK):
                if len(self.pw) < 512:
                    self.pw.append(chr(u))
            else:
                return
        if self.form is not None:
            self.form.area.queue_draw()

    def clear(self):
        for i in range(len(self.pw)):
            self.pw[i] = "\0"
        self.pw.clear()

    def submit(self):
        if not self.pw or self.checking:
            return                        # пустой Enter не тратит попытку faillock
        secret = bytearray()
        for ch in self.pw:
            secret += ch.encode("utf-8")
        self.clear()
        self.checking = True
        self.pam_note = ""

        def work():
            try:
                ok, rc, msgs = pam_check(self.user, secret)
            except Exception as e:        # сломался сам вызов — не пускаем
                log("PAM: %s" % e)
                ok, rc, msgs = False, -1, []
            finally:
                wipe(secret)
            GLib.idle_add(self.auth_done, ok, rc, msgs)
        threading.Thread(target=work, daemon=True).start()

    @guarded
    def auth_done(self, ok, rc, msgs):
        self.checking = False
        if ok:
            self.unlock()
            return False
        self.failed += 1
        self.pam_note = " ".join(m for m in msgs if m)[:120]
        log("пароль не принят (PAM %d)" % rc)
        if self.form is not None:
            self.form.area.queue_draw()
        return False

    def unlock(self):
        self.exit_code = EXIT_OK
        try:    # звук разблокировки (ui_sound.py сам молчит, если выключено/DND/игра)
            subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                           "ui_sound.py"), "play", "unlock"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except Exception:
            pass
        self.lock.unlock_and_destroy()
        Gdk.Display.get_default().sync()
        Gtk.main_quit()

    # ── питание ───────────────────────────────────────────────────────────
    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def activate(self, idx):
        if self.pending is not None:
            if self.pending == idx:
                self.execute(idx)          # второй щелчок той же кнопки — сразу
            else:
                self.cancel()              # другая кнопка — только отмена
            return
        if not ACTIONS[idx][3]:
            self.execute(idx)
            return
        self.pending = idx
        self.deadline = time.monotonic() + COUNTDOWN
        self.timer = GLib.timeout_add(FRAME_MS, self.frame)
        self.form_buttons_redraw()

    def form_buttons_redraw(self):
        if self.form is not None:
            self.form.queue_buttons()

    @guarded
    def frame(self):
        if self.pending is None:
            self.timer = None
            return False
        if self.remaining() <= 0:
            self.timer = None
            self.execute(self.pending)
            return False
        self.form_buttons_redraw()
        return True

    def cancel(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        self.pending = None
        self.form_buttons_redraw()

    def execute(self, idx):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        self.pending = None
        key = ACTIONS[idx][0]
        cmd = power_command(key)
        if DRY_RUN:
            print("DRY-RUN %s: %s" % (key, shlex.join(cmd)), flush=True)
        else:
            log("питание: %s" % key)
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        self.form_buttons_redraw()

    # ── заставка ───────────────────────────────────────────────────────────
    SAVER_IN, SAVER_OUT = 0.6, 0.3

    def saver_begin(self, info=None):
        """info — подхват показанной заставки (без появления); None — своя, плавно."""
        ss = saver_module()
        if ss is None or self.saver is not None or self.saver_dead:
            return
        now = time.monotonic()
        try:
            theme = ss.load_theme()
            if info:
                t0, seed, main = float(info["t0"]), int(info["seed"]), info.get("main")
            else:
                g = self.form.monitor.get_geometry() if self.form is not None else None
                t0, seed, main = now, int.from_bytes(os.urandom(4), "little") & 0x7FFFFFFF, \
                    ([g.x, g.y] if g else None)
            self.saver = dict(ss=ss, theme=theme, t0=t0, seed=seed, main=main, start=now,
                              fade=info is None, leaving=None, scenes={}, pacers={}, anchor=None,
                              cycle=ss.cycle_seconds(), effect=ss.effect_name())
        except Exception:
            traceback.print_exc()
            self.saver = None
            return
        if self.pending is not None:
            self.cancel()
        self.clear()
        for win in self.windows.values():
            win.hover = None
            win.set_blank(True)
        self.saver_gen += 1
        GLib.timeout_add(16, self.saver_tick, self.saver_gen)
        self.redraw()
        log("заставка поверх формы (%s)" % ("подхват" if info else "бездействие"))

    def saver_end(self, broken=False):
        self.saver = None
        self.saver_gen += 1
        if broken:
            self.saver_dead = True
        for win in self.windows.values():
            win.set_blank(False)
        self.redraw()

    def saver_wake(self):
        if self.saver is not None and self.saver["leaving"] is None:
            self.saver["leaving"] = time.monotonic()

    def saver_motion(self, x, y):
        sv = self.saver
        ss = sv["ss"]
        now = time.monotonic()
        if sv["leaving"] is not None or now - sv["start"] < ss.GRACE:
            sv["anchor"] = None
            return
        a = sv["anchor"]
        if a is None or now - a[2] > 1.5:
            sv["anchor"] = (x, y, now)
            return
        sv["anchor"] = (a[0], a[1], now)
        if (x - a[0]) ** 2 + (y - a[1]) ** 2 >= ss.MOVE_PX ** 2:
            self.saver_wake()

    def saver_alpha(self):
        sv, now = self.saver, time.monotonic()
        if sv["leaving"] is not None:
            return 1.0 - (now - sv["leaving"]) / self.SAVER_OUT
        if sv["fade"]:
            return min(1.0, (now - sv["start"]) / self.SAVER_IN)
        return 1.0

    def saver_scene(self, win, w, h):
        sv = self.saver
        sc = sv["scenes"].get(win)
        if sc is None or (sc.w, sc.h) != (w, h):
            main_win = None
            for other in self.windows.values():
                g = other.monitor.get_geometry()
                if sv["main"] and [g.x, g.y] == list(sv["main"]):
                    main_win = other
            main = win is (main_win or self.form)
            sc = sv["ss"].Scene(w, h, sv["theme"], main=main, seed=sv["seed"] + (0 if main else 1),
                                hint=sv["ss"].HINT_LOCK, cycle=sv["cycle"], effect=sv["effect"])
            sv["scenes"][win] = sc
            sv["pacers"][win] = sv["ss"].Pacer()
        return sc

    def draw_saver(self, win, cr, w, h):
        """Заставка на поверхности блокировки. True — нарисовано; False — заставка
        сломалась (выключена), рисуй форму. Ошибки формы сюда не прячутся."""
        sv = self.saver
        a = self.saver_alpha()
        pushed = False
        try:
            sc = self.saver_scene(win, w, h)
            t = time.monotonic() - sv["t0"]
            if a >= 0.999:
                ok, rect = Gdk.cairo_get_clip_rectangle(cr)
                sc.draw(cr, t, (rect.x, rect.y, rect.width, rect.height) if ok else None)
                return True
            cr.push_group()
            pushed = True
            sc.draw(cr, t)
            pat = cr.pop_group()
            pushed = False
        except Exception:
            traceback.print_exc()
            if pushed:
                cr.pop_group()
            log("заставка сломалась — показываю форму")
            self.saver_end(broken=True)
            return False
        win.draw_lock(cr, w, h)              # форма снизу, заставка сверху
        cr.set_source(pat)
        cr.paint_with_alpha(max(0.0, a))
        return True

    def saver_tick(self, gen):
        if gen != self.saver_gen or self.saver is None:
            return False
        sv = self.saver
        try:
            now = time.monotonic()
            if sv["leaving"] is not None:
                if now - sv["leaving"] >= self.SAVER_OUT:
                    self.saver_end()
                    return False
                self.redraw()
                return True
            if sv["fade"] and now - sv["start"] < self.SAVER_IN + 0.05:
                self.redraw()
                return True
            t = now - sv["t0"]
            for win in list(self.windows.values()):
                sc = sv["scenes"].get(win)
                if sc is None:
                    win.area.queue_draw()
                    continue
                r = sv["pacers"][win].plan(sc, t)
                if r is False:
                    continue
                if r is None:
                    win.area.queue_draw()
                else:
                    for x, y, rw, rh in r:
                        win.area.queue_draw_area(int(x), int(y), int(rw), int(rh))
            return True
        except Exception:
            traceback.print_exc()
            log("заставка сломалась (кадр) — показываю форму")
            self.saver_end(broken=True)
            return False

    def on_usr1(self, *_a):
        """screensaver.py arm: бездействие уже под блокировкой — показать заставку."""
        try:
            if self.locked and self.saver is None and not self.checking:
                ss = saver_module()
                if ss and ss.saver_in_lock_allowed():
                    self.saver_begin()
        except Exception:
            traceback.print_exc()
        return True

    # ── блокировка ────────────────────────────────────────────────────────
    def run(self, handoff=None):
        if not GtkSessionLock.is_supported():
            log("композитор не поддерживает ext-session-lock")
            return EXIT_NOLOCK
        display = Gdk.Display.get_default()
        self.lock = lock = GtkSessionLock.prepare_lock()
        lock.connect("locked", self.on_locked)
        lock.connect("finished", self.on_finished)
        # SIGUSR1 по умолчанию убивает процесс — обработчик ставим до блокировки,
        # а arm шлёт сигнал только после метки (on_locked).
        try:
            from gi.repository import GLibUnix
            GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.on_usr1)
        except ImportError:
            GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.on_usr1)
        if handoff:
            self.saver_begin(handoff)
        lock.lock_lock()
        for i in range(display.get_n_monitors()):
            self.add_monitor(lock, display.get_monitor(i))
        display.connect("monitor-added", guarded(lambda _d, m: self.add_monitor(lock, m)))
        display.connect("monitor-removed", guarded(lambda _d, m: self.remove_monitor(m)))
        keymap = Gdk.Keymap.get_for_display(display)
        keymap.connect("state-changed", self.on_keymap_state)
        self.caps = bool(keymap.get_caps_lock_state())
        GLib.timeout_add_seconds(10, self.watchdog)
        GLib.timeout_add_seconds(1, self.tick)
        GLib.timeout_add_seconds(30, self.refresh_corners)
        self.refresh_corners()
        self.refresh_layout()
        Gtk.main()
        ss = saver_module()
        if ss:
            ss.clear_lock_mark(os.getpid())
        return self.exit_code

    @guarded
    def on_locked(self, _lock):
        self.locked = True
        log("сеанс заблокирован%s" % (" (dry-run)" if DRY_RUN else ""))
        ss = saver_module()
        if ss:      # слою-заставке можно уходить; arm может слать SIGUSR1
            ss.mark_lock_shown(os.getpid())

    @guarded
    def on_finished(self, _lock):
        # До «locked» — композитор отказал (уже заперт другим и т. п.).
        # После — снял блокировку сам: перестраховка, пусть lockscreen запрёт hyprlock.
        self.exit_code = EXIT_LOST if self.locked else EXIT_NOLOCK
        log("композитор завершил блокировку (%s)" % ("после locked" if self.locked else "отказ"))
        Gtk.main_quit()

    @guarded
    def watchdog(self):
        if not self.locked:
            log("нет ответа locked за 10 с")
            self.exit_code = EXIT_NOLOCK
            Gtk.main_quit()
        return False


if __name__ == "__main__":
    shots = SHOTS.wait(5.0)
    sys.exit(Locker(OUTS, shots).run(SAVER))
