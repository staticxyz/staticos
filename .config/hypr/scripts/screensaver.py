#!/usr/bin/env python3
"""Заставка staticOS. 03.10.2026.

    screensaver.py                  показать сейчас (меню питания, бинд)
    screensaver.py get              on | off — запуск по бездействию
    screensaver.py on|off           включить / выключить запуск по бездействию
    screensaver.py idle [МИН]       задержка бездействия: напечатать / поставить (1–120)
    screensaver.py lockmode [on|off|get]
                                    заставка поверх экрана блокировки (по умолчанию on;
                                    работает только со своим экраном jarvis_lock)
    screensaver.py cycle [СЕК]      раз во сколько секунд надпись осыпается и собирается
                                    заново (0 — никогда; 10–3600; по умолчанию 60)
    screensaver.py effect [ИМЯ]     как собирается надпись: random | rain | pour | tune
    screensaver.py stop             убрать показанную заставку (плавно)
    screensaver.py arm              для hypridle: ждать задержку, потом показать
    screensaver.py disarm           для hypridle: ввод вернулся — ожидание отменить
    screensaver.py why              почему сейчас заставка НЕ встала бы по бездействию
    screensaver.py bench            замер стоимости кадра (вне экрана)

Не экран блокировки: пароль не спрашивает, сеанс не запирает. Любая клавиша,
щелчок, колесо или заметное движение мыши — плавно гаснет за четверть секунды.

Вид (пользователь прислал образец чужой ОС — взята только идея, код и графика свои):
экран плавно уходит в чёрное, крупная пиксельная надпись staticOS собирается из
пиксельных блоков, за ней по символам подзаголовок «[ТВ] ~ signal through the
static ~ [сигнал]», потом часы и дата. Буквы стоят на медленной «дышащей» волне
и чуть наклонены, у каждой под ней — три ступенчатых контура-эха вниз-вправо.
Градиент по надписи медленно переливается оттенками палитры обоев (matugen).
Над надписью — пиксельный телевизор с «снегом» на экране и шкала сигнала (ник
пользователя static, логотип — телевизор с помехами); по фону мерцают пиксели-помехи.
Изредка — короткая ТВ-помеха по надписи. Сердечек больше нет (просьба: «не по
нашему вайбу»).

Сборка и цикл (04.10.2026, просьба пользователя: «как в Omarchy — плавнее, медленнее,
и чтобы через время снова сыпалось сверху»). Ощущение взято у заставки Omarchy
(github.com/basecamp/omarchy, лицензия MIT, © David Heinemeier Hansson): там
логотип в терминале по кругу проигрывается эффектами terminaltexteffects
(`--random-effect`, 120 к/с) — символы падают по одному в случайном порядке,
медленно, а когда эффект доигран, запускается следующий. Код оттуда не брался
(там вообще bash + чужая программа); взяты идеи: медленное плавное падение,
случайный порядок, эффект по кругу и смена эффекта. Свои эффекты:
  rain     «дождь» — клетки срываются в случайном порядке (нижние строки чуть
           раньше) и плавно опускаются ~2 с; в полёте тусклые, на месте
           загораются цветом надписи (так в tte «rain» символ меняет цвет);
  pour     «насыпание» — строки снизу вверх, внутри строки слева-направо и
           обратно через строку, как «pour» в tte;
  tune     «настройка» — клетки сперва мерцают серым снегом вокруг, потом
           съезжаются в буквы: сигнал проступает сквозь помехи.
Раз в `cycle` секунд: ТВ-помеха, надпись осыпается вниз (или рассыпается в
снег), сигнал на шкале падает до нуля, телевизор шумит — и сборка заново.
Пока сыплется — 60 к/с, в покое — 30, под глубоким приглушением — 10.

Блокировка (`lockmode`, по умолчанию включено; только при state/lock-engine =
jarvis). Заставка на экране, а hypridle запирает сеанс: jarvis_lock.py стартует
сразу в режиме заставки — рисует ТУ ЖЕ сцену (то же время, то же зерно) на
своих поверхностях ext-session-lock, а этот слой, когда блокировка встала,
тихо уходит (он и так под ней). Первая клавиша / щелчок / рывок мыши — заставка
гаснет, видна форма пароля. Снимок рабочего стола для фона формы делается здесь,
ДО показа заставки (иначе jarvis_lock снял бы саму заставку): размытый и
затемнённый, в $XDG_RUNTIME_DIR/jarvis-saver-bg (tmpfs, 0700), удаляется при
выходе. Сеанс уже заперт, а время заставки пришло (`arm`) — jarvis_lock получает
SIGUSR1 и показывает заставку сам. С hyprlock этого нет: заставка уходит при
блокировке, как раньше.

Шрифт — системный пиксельный PxPlus HP 100LX 6x8: его глифы снимаются побитово
(PIL, 8 px, без сглаживания) и рисуются клетками.

Мониторы: на каждом свой слой OVERLAY (namespace jarvis-screensaver). Надпись —
на мониторе с фокусом; на остальных крупные часы, дата и помехи.

Бездействие: hypridle зовёт `arm` через минуту простоя, `arm` ждёт остаток
задержки (state/screensaver-idle, по умолчанию 3 мин) и показывает заставку,
если за это время не было ввода (`disarm` на on-resume). Не встаёт: выключена
(state/screensaver = off), Savage Mode с «не отключать экран», игра, запись или
трансляция экрана, окно в фокусе на весь экран, играет видеоплеер или браузер.
Журнал — $XDG_RUNTIME_DIR/jarvis-screensaver.log.
"""
import fcntl
import json
import math
import os
import random
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.expanduser("~/.config/hypr/state")
STATE = os.path.join(STATE_DIR, "screensaver")            # on | off
IDLE_STATE = os.path.join(STATE_DIR, "screensaver-idle")  # минуты
LOCKMODE_STATE = os.path.join(STATE_DIR, "screensaver-lockmode")   # on | off
CYCLE_STATE = os.path.join(STATE_DIR, "screensaver-cycle")         # секунды
EFFECT_STATE = os.path.join(STATE_DIR, "screensaver-effect")       # random | rain | …
ENGINE_STATE = os.path.join(STATE_DIR, "lock-engine")     # jarvis — свой экран блокировки
RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
LOCK = os.path.join(RUN, "jarvis-screensaver.lock")       # flock + pid показанной
ARM = os.path.join(RUN, "jarvis-screensaver-arm")         # pid ждущего arm
LOG = os.path.join(RUN, "jarvis-screensaver.log")
INFO = os.path.join(RUN, "jarvis-screensaver.json")       # для jarvis_lock: время, зерно
BG_DIR = os.path.join(RUN, "jarvis-saver-bg")             # размытые снимки для формы
LOCK_MARK = os.path.join(RUN, "jarvis-lock-shown")        # pid jarvis_lock, когда заперто
DIM_STATE = os.path.expanduser("~/.cache/screen-dim")     # off | soft | deep (screen_gamma)
MATUGEN = os.path.expanduser("~/.cache/matugen")
PX_FONT = os.path.expanduser("~/.local/share/fonts/PxPlus_HP_100LX_6x8.ttf")

IDLE_DEFAULT = 3       # минут; блокировка в hypridle — на пятой, приглушение — на 4,5
CYCLE_DEFAULT = 60     # секунд между пересборками надписи
ARM_AFTER = 60         # через сколько секунд простоя hypridle зовёт arm (listener)
SLOGAN = "staticOS"
# \x01 — маленький телевизор, \x02 — шкала сигнала (свои глифы, см. CUSTOM)
SUBTITLE = "\x01 ~ signal through the static ~ \x02"
HINT = "press any key or move the mouse"
HINT_LOCK = "press any key to unlock"
EFFECTS = ("rain", "pour", "tune")
FPS = 30               # обычный показ; пока сыплются блоки — вдвое чаще
FADE_IN = 0.5          # экран уходит в чёрное
FADE_OUT = 0.25        # выход
GRACE = 1.0            # первую секунду движение мыши не будит (щелчок по меню)
MOVE_PX = 40           # «заметное» движение: столько пикселей за один рывок
VIDEO_PLAYERS = ("mpv", "vlc", "celluloid", "haruna", "totem", "smplayer", "firefox",
                 "librewolf", "zen", "chromium", "helium", "brave", "vivaldi", "kodi")


def log(msg):
    try:
        if os.path.getsize(LOG) > 200_000:
            os.replace(LOG, LOG + ".old")
    except OSError:
        pass
    try:
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%F %T"), msg))
    except OSError:
        pass


# ── состояние ──────────────────────────────────────────────────────────────
def _read(path):
    try:
        return open(path).read().strip()
    except OSError:
        return None


def _write(path, text):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(text + "\n")


def enabled():
    return _read(STATE) != "off"            # по умолчанию — включено


def set_enabled(on):
    _write(STATE, "on" if on else "off")


def idle_minutes():
    try:
        v = float((_read(IDLE_STATE) or "").replace(",", "."))
        return max(1.0, min(120.0, v))
    except ValueError:
        return float(IDLE_DEFAULT)


def lockmode_on():
    """Заставка поверх экрана блокировки — включено, если не записано off."""
    return _read(LOCKMODE_STATE) != "off"


def lock_engine_jarvis():
    return (_read(ENGINE_STATE) or "").replace(" ", "") == "jarvis"


def lockmode_active():
    """Заставка уйдёт под блокировку целиком: режим включён и экран блокировки свой
    (hyprlock рисовать заставку не умеет — с ним всё как раньше)."""
    return lockmode_on() and lock_engine_jarvis()


def cycle_seconds():
    try:
        v = float((_read(CYCLE_STATE) or "").replace(",", "."))
    except ValueError:
        return float(CYCLE_DEFAULT)
    return 0.0 if v <= 0 else max(10.0, min(3600.0, v))


def effect_name():
    v = (_read(EFFECT_STATE) or "random").lower()
    return v if v in EFFECTS else "random"


def fmt_min(v):
    return str(int(v)) if v == int(v) else ("%g" % v)


def dim_deep():
    """Глубокое приглушение (hypridle, 10 мин): экран почти чёрный — кадры реже."""
    return (_read(DIM_STATE) or "").split()[:1] == ["deep"]


def shown_pid():
    """pid показанной заставки (по flock), иначе None."""
    try:
        fd = os.open(LOCK, os.O_RDONLY)
    except OSError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return None                     # замок свободен — никто не показывает
    except OSError:
        try:
            return int(os.read(fd, 32).decode().strip() or 0) or None
        except ValueError:
            return None
    finally:
        os.close(fd)


def own_cmdline(pid, word=None):
    """Это питон с нашим файлом (и словом word в аргументах)?"""
    try:
        argv = [a.decode("utf-8", "replace") for a in
                open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0") if a]
    except OSError:
        return False
    if len(argv) < 2 or "python" not in os.path.basename(argv[0]):
        return False
    if os.path.abspath(argv[1]) != os.path.abspath(__file__):
        return False
    return word is None or word in argv[2:]


# ── связка с jarvis_lock ───────────────────────────────────────────────────
def handoff_info():
    """Для jarvis_lock при старте: заставка на экране и готова уйти под
    блокировку → {pid, t0, seed, main, bg}, иначе None. t0 — CLOCK_MONOTONIC
    показа (часы общие для всех процессов), так сцена продолжается без скачка."""
    if not lockmode_on():
        return None
    try:
        info = json.load(open(INFO))
        pid = int(info.get("pid") or 0)
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    if not pid or shown_pid() != pid or not own_cmdline(pid):
        return None
    if info.get("display") != os.environ.get("WAYLAND_DISPLAY", ""):
        return None
    return info


def saver_in_lock_allowed():
    """Можно ли jarvis_lock показывать заставку (по SIGUSR1 от arm)."""
    if not (enabled() and lockmode_on()):
        return False
    sys.path.insert(0, HERE)
    try:
        from idle_guard import keep_screen_on
        if keep_screen_on():
            return False
    except Exception:
        pass
    return True


def mark_lock_shown(pid):
    """jarvis_lock: блокировка встала (locked) — заставке-слою можно уходить."""
    try:
        with open(LOCK_MARK, "w") as f:
            f.write("%d\n" % pid)
    except OSError:
        pass


def clear_lock_mark(pid=None):
    try:
        if pid is None or int(_read(LOCK_MARK) or 0) == pid:
            os.unlink(LOCK_MARK)
    except (OSError, ValueError):
        pass


def lock_pid():
    """pid запертого jarvis_lock этого сеанса (метка + проверка процесса) или None."""
    try:
        pid = int(_read(LOCK_MARK) or 0)
        argv = open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
        env = open("/proc/%d/environ" % pid, "rb").read().split(b"\0")
    except (OSError, ValueError):
        return None
    if len(argv) < 2 or not argv[1].endswith(b"jarvis_lock.py"):
        return None
    if ("WAYLAND_DISPLAY=" + os.environ.get("WAYLAND_DISPLAY", "")).encode() not in env:
        return None
    return pid


def drop_info():
    try:
        if json.load(open(INFO)).get("pid") == os.getpid():
            os.unlink(INFO)
    except (OSError, ValueError, AttributeError):
        pass


def clear_backgrounds():
    try:
        for n in os.listdir(BG_DIR):
            os.unlink(os.path.join(BG_DIR, n))
    except OSError:
        pass


def save_backgrounds(outs):
    """Снимок каждого монитора ДО показа — фон формы jarvis_lock (тот иначе снял бы
    саму заставку). Сразу размыт и затемнён, как blur_shot() в jarvis_lock.py
    (уменьшение ×4, blur 6, цвет 1.2, контраст 1.3, яркость 0.35): прочесть по
    нему ничего нельзя. tmpfs, папка 0700, файлы 0600, стираются при выходе."""
    import io
    import threading
    try:
        from PIL import Image, ImageEnhance, ImageFilter
    except ImportError:
        return
    old = os.umask(0o077)
    try:
        os.makedirs(BG_DIR, mode=0o700, exist_ok=True)
        os.chmod(BG_DIR, 0o700)
    except OSError:
        os.umask(old)
        return
    clear_backgrounds()

    def one(name):
        try:
            p = subprocess.run(["grim", "-t", "ppm", "-o", name, "-"], capture_output=True, timeout=4)
            if p.returncode != 0 or not p.stdout:
                return
            im = Image.open(io.BytesIO(p.stdout)).convert("RGB")
            if min(im.size) >= 64:
                im = im.reduce(4)
            im = im.filter(ImageFilter.GaussianBlur(6))
            im = ImageEnhance.Color(im).enhance(1.2)
            im = ImageEnhance.Contrast(im).enhance(1.3)
            im = ImageEnhance.Brightness(im).enhance(0.35)
            tmp = os.path.join(BG_DIR, ".%s.png" % name)
            im.save(tmp, "PNG", compress_level=1)
            os.replace(tmp, os.path.join(BG_DIR, name + ".png"))
        except Exception as e:
            log("снимок %s: %s" % (name, e))
    try:
        names = [n for n, o in (outs or {}).items() if (o or {}).get("logical")]
        ths = [threading.Thread(target=one, args=(n,), daemon=True) for n in names]
        for t in ths:
            t.start()
        end = time.monotonic() + 4.5
        for t in ths:
            t.join(max(0.0, end - time.monotonic()))
    finally:
        os.umask(old)


# ── почему не вставать по бездействию ──────────────────────────────────────
def _niri_json(*what):
    try:
        out = subprocess.run(["niri", "msg", "-j", *what], capture_output=True, text=True,
                             timeout=2).stdout
        return json.loads(out) if out.strip() else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def session_locked():
    """Кто запер этот сеанс: "jarvis" (jarvis_lock.py), "hyprlock" или None.

    Как в scripts/lockscreen: считаем только процессы СВОЕГО Wayland-сокета —
    от закрытого сеанса однажды остался осиротевший hyprlock (21.09.2026)."""
    disp = ("WAYLAND_DISPLAY=" + os.environ.get("WAYLAND_DISPLAY", "")).encode()
    found = None
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        name = os.path.basename(argv[0]) if argv else b""
        kind = None
        if name == b"hyprlock":
            kind = "hyprlock"
        elif len(argv) > 1 and argv[1].endswith(b"jarvis_lock.py"):
            kind = "jarvis"
        if kind:
            try:
                if disp in open("/proc/%s/environ" % d, "rb").read().split(b"\0"):
                    if kind == "hyprlock":
                        return kind           # hyprlock поверх всего — он главнее
                    found = kind
            except OSError:
                continue
    return found


def fullscreen_window():
    """Окно в фокусе закрывает весь монитор (видео, игра). В niri 26.04 у окна нет
    is_fullscreen — сравниваем размер окна с логическим размером монитора, как
    hot_corners.py."""
    win = _niri_json("focused-window")
    if not win:
        return False
    wss = _niri_json("workspaces") or []
    outs = _niri_json("outputs") or {}
    out = next((w.get("output") for w in wss if w.get("id") == win.get("workspace_id")), None)
    lg = (outs.get(out) or {}).get("logical") or {}
    size = (win.get("layout") or {}).get("window_size") or [0, 0]
    return bool(lg) and size[0] >= lg.get("width", 1 << 30) and size[1] >= lg.get("height", 1 << 30)


def video_playing():
    """Играет видеоплеер или браузер (MPRIS). Музыкальные плееры не мешают."""
    try:
        out = subprocess.run(["playerctl", "-a", "metadata", "--format",
                              "{{playerName}}\t{{status}}"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        name, _t, status = line.partition("\t")
        if status.strip() == "Playing" and name.lower().startswith(VIDEO_PLAYERS):
            return name
    return None


def blocker(for_lock=False):
    """Почему заставке сейчас НЕ вставать по бездействию (строка) или None.

    for_lock — сеанс уже заперт и речь о заставке внутри экрана блокировки:
    окно на весь экран и видео за блокировкой никто не смотрит, их не считаем."""
    if not enabled():
        return "выключена (state/screensaver)"
    sys.path.insert(0, HERE)
    try:
        from idle_guard import keep_screen_on
        if keep_screen_on():
            return "Savage Mode + «не отключать экран»"
    except Exception:
        pass
    try:
        from game_guard import game_running
        if game_running():
            return "идёт игра (Steam)"
    except Exception:
        pass
    for proc in ("cs2", "gamescope", "gamescope-wl"):
        if subprocess.run(["pgrep", "-x", proc], stdout=subprocess.DEVNULL).returncode == 0:
            return "идёт игра (%s)" % proc
    if os.path.exists(os.path.join(RUN, "jarvis-rec", "pid")):
        return "идёт запись экрана"
    casts = _niri_json("casts") or []
    if any(c.get("is_active", True) for c in casts if isinstance(c, dict)):
        return "идёт трансляция экрана"
    if for_lock:
        return None
    if session_locked():
        return "сеанс заперт"
    if fullscreen_window():
        return "окно в фокусе на весь экран"
    v = video_playing()
    if v:
        return "играет видео (%s)" % v
    return None


# ── командная строка (до GTK: arm/get/on/off не должны грузить его) ─────────
def cli():
    a = sys.argv[1:]
    cmd = a[0] if a else "show"
    if cmd == "get":
        print("on" if enabled() else "off")
    elif cmd in ("on", "off"):
        set_enabled(cmd == "on")
        print(cmd)
    elif cmd == "idle":
        if len(a) > 1:
            try:
                v = max(1.0, min(120.0, float(a[1].replace(",", "."))))
            except ValueError:
                print("idle: нужно число минут", file=sys.stderr)
                return 2
            _write(IDLE_STATE, fmt_min(v))
        print(fmt_min(idle_minutes()))
    elif cmd == "lockmode":
        v = a[1] if len(a) > 1 else "get"
        if v in ("on", "off"):
            _write(LOCKMODE_STATE, v)
        elif v != "get":
            print("lockmode: on | off | get", file=sys.stderr)
            return 2
        print("on" if lockmode_on() else "off")
    elif cmd == "cycle":
        if len(a) > 1:
            try:
                v = float(a[1].replace(",", "."))
            except ValueError:
                print("cycle: нужно число секунд (0 — не повторять)", file=sys.stderr)
                return 2
            _write(CYCLE_STATE, fmt_min(0.0 if v <= 0 else max(10.0, min(3600.0, v))))
        print(fmt_min(cycle_seconds()))
    elif cmd == "effect":
        if len(a) > 1:
            v = a[1].lower()
            if v not in EFFECTS + ("random",):
                print("effect: random | " + " | ".join(EFFECTS), file=sys.stderr)
                return 2
            _write(EFFECT_STATE, v)
        print(effect_name())
    elif cmd == "stop":
        pid = shown_pid()
        if pid and own_cmdline(pid):
            os.kill(pid, signal.SIGTERM)
    elif cmd == "why":
        print(blocker() or "ничто не мешает")
    elif cmd == "arm":
        return arm()
    elif cmd == "disarm":
        disarm()
    elif cmd == "bench":
        return bench()
    elif cmd == "show":
        return None                     # дальше — показ
    else:
        print(__doc__)
        return 2
    return 0


def arm():
    """hypridle: минута простоя прошла. Ждём остаток задержки; если за это время
    пришёл disarm (ввод) — метка ARM уже не наша, тихо выходим."""
    if not enabled():
        return 0
    me = str(os.getpid())
    with open(ARM, "w") as f:
        f.write(me)
    wait = idle_minutes() * 60 - ARM_AFTER
    end = time.monotonic() + max(0.0, wait)
    while time.monotonic() < end:
        time.sleep(min(1.0, max(0.05, end - time.monotonic())))
        try:
            if open(ARM).read().strip() != me:
                return 0
        except OSError:
            return 0
    try:
        os.unlink(ARM)
    except OSError:
        pass
    locked = session_locked()
    if not locked and blocker() == "сеанс заперт":
        # Гонка: блокировка встала в те же секунды (04.10.2026 — «заставка не появляется
        # вместе с блокировкой»: arm видел «не заперто», а проверка помех уже «заперто»
        # и пропускала). Дать jarvis_lock подняться и идти путём «под блокировкой».
        time.sleep(1.5)
        locked = session_locked()
    if locked:
        # Сеанс уже заперт (блокировка раньше заставки, или пользователь подошёл, не
        # ввёл пароль и снова отошёл) — заставку покажет сам jarvis_lock.
        why = blocker(for_lock=True)
        if why:
            log("бездействие под блокировкой — пропуск: %s" % why)
            return 0
        if locked != "jarvis" or not lockmode_on():
            log("бездействие под блокировкой (%s, lockmode %s) — пропуск"
                % (locked, "on" if lockmode_on() else "off"))
            return 0
        pid = lock_pid()
        if not pid:
            log("бездействие под блокировкой — jarvis_lock ещё не запер сеанс, пропуск")
            return 0
        os.kill(pid, signal.SIGUSR1)
        log("бездействие %s мин под блокировкой — заставка в jarvis_lock" % fmt_min(idle_minutes()))
        return 0
    why = blocker()
    if why:
        log("бездействие %s мин — пропуск: %s" % (fmt_min(idle_minutes()), why))
        return 0
    if shown_pid():
        return 0
    log("бездействие %s мин — показ" % fmt_min(idle_minutes()))
    return run_show()


def disarm():
    try:
        pid = int(open(ARM).read().strip())
    except (OSError, ValueError):
        return
    try:
        os.unlink(ARM)
    except OSError:
        pass
    if own_cmdline(pid, "arm"):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


# ── палитра ────────────────────────────────────────────────────────────────
def hex2rgb(h):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def mix(a, b, t):
    return tuple(x + (y - x) * t for x, y in zip(a, b))


def load_theme(colors=None, vivid=None):
    """Цвета заставки из обоев. colors — словарь colors.json, vivid — '#rrggbb'
    (для проверок можно подсунуть свои; по умолчанию — ~/.cache/matugen)."""
    import colorsys
    if colors is None:
        try:
            colors = json.load(open(os.path.join(MATUGEN, "colors.json")))
        except (OSError, ValueError):
            colors = {}
    if vivid is None:
        try:
            vivid = open(os.path.join(MATUGEN, "vivid.txt")).read().strip()
        except OSError:
            vivid = ""
    vivid = vivid or colors.get("primary", "#7aa2f7")

    def get(k, d):
        try:
            return hex2rgb(colors.get(k, d))
        except ValueError:
            return hex2rgb(d)
    acc = hex2rgb(vivid)
    ha, _la, sa = colorsys.rgb_to_hls(*acc)
    ht, _lt, st = colorsys.rgb_to_hls(*get("tertiary", "#bb9af7"))
    # Сторона перелива — к третичному цвету палитры (у обоев он «соседний»). Если
    # третичный почти серый или совпадает с акцентом — шаг 40° в ту же сторону.
    d = ((ht - ha + 0.5) % 1.0) - 0.5
    if st < 0.15 or abs(d) < 20 / 360:
        d = 40 / 360 if d >= 0 else -40 / 360
    sgn = 1 if d >= 0 else -1
    # Пять опорных оттенков: два соседних «до» акцента, акцент, третичный и шаг
    # за ним. Насыщенность и светлота — пастельно-яркие, как надпись на образце;
    # у почти серых обоев насыщенность пропорционально ниже.
    sat = 0.72 * min(1.0, max(0.25, sa / 0.55))
    hues = [ha - sgn * 48 / 360, ha - sgn * 22 / 360, ha, ha + d, ha + d + sgn * 34 / 360]
    # Перелив идёт по оттенку (HLS), не по RGB: между зелёным и розовым RGB-смесь
    # давала грязно-оливковую середину (проверка на зелёной палитре).
    ramp = [(h, 0.68, sat) for h in hues]
    on_s = get("on_surface", "#e1e1ef")
    on_v = get("on_surface_variant", "#c4c6d3")
    return {
        "ramp": ramp,
        "fg": on_s,
        "dim": on_v,
        # серые пиксели-помехи фона — чуть подкрашены акцентом
        "star": mix(mix(on_v, (0, 0, 0), 0.62), acc, 0.10),
        # «снег»: блоки в полёте, шум телевизора, осыпание
        "static": mix(mix(on_v, (0, 0, 0), 0.30), acc, 0.08),
        "hint": mix(on_v, (0, 0, 0), 0.45),
        "error": get("error", "#ffb4ab"),
    }


def ramp_color(theme, u):
    """Цвет перелива в точке u (любое число): маятник по пяти опорным цветам —
    0→1→0→…, поэтому перелив идёт туда-обратно без скачка на стыке."""
    r = theme["ramp"]
    v = u % 2.0
    v = v if v <= 1.0 else 2.0 - v
    x = v * (len(r) - 1)
    i = min(int(x), len(r) - 2)
    t = x - i
    t = t * t * (3 - 2 * t)
    import colorsys
    (h1, l1, s1), (h2, l2, s2) = r[i], r[i + 1]
    return colorsys.hls_to_rgb((h1 + (h2 - h1) * t) % 1.0, l1 + (l2 - l1) * t, s1 + (s2 - s1) * t)


# ── пиксельный шрифт и значки ──────────────────────────────────────────────
# Мотив — «сигнал сквозь помехи»: телевизор с антенной (логотип static), шкала
# сигнала, пиксели-снежинки. Сердечки убраны 04.10.2026.
TV = ["...#.....#...",
      "....#...#....",
      ".....#.#.....",
      "#############",
      "#...........#",
      "#...........#",
      "#...........#",
      "#...........#",
      "#############",
      ".##.......##."]
TV_SCREEN = (1, 4, 11, 4)          # экран телевизора в клетках: x, y, ширина, высота
TV_MINI = [".#...#.", "..#.#..", "#######", "#.#.#.#", "##.#.##", "#######"]
SIG_MINI = ["......#", "....#.#", "..#.#.#", "#.#.#.#"]
PLUS = ["..#..", "..#..", "#####", "..#..", "..#.."]
SPARK = ["...#...", "...#...", "..###..", "#######", "..###..", "...#...", "...#..."]
TWINKLE = [".#.", "###", ".#."]
DOT = ["#"]
DASH = ["####"]                    # обрывок строки развёртки
SNOW = ["#.#.", ".#.#"]
SNOW2 = ["#..", ".#.", "..#", ".#."]
# свои «символы» подзаголовка: (ширина клетки, картинка, сдвиг вниз)
CUSTOM = {"\x01": (8, TV_MINI, 1), "\x02": (8, SIG_MINI, 3)}

_GLYPHS = {}
_FONT = None


def glyph(ch):
    """Клетки символа: (ширина, [(x, y), …]) в сетке 6×8 PxPlus HP 100LX."""
    global _FONT
    if ch in _GLYPHS:
        return _GLYPHS[ch]
    if ch in CUSTOM:
        adv, rows, dy = CUSTOM[ch]
        g = (adv, [(x, y + dy) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"])
        _GLYPHS[ch] = g
        return g
    from PIL import Image, ImageDraw, ImageFont
    if _FONT is None:
        _FONT = ImageFont.truetype(PX_FONT, 8)
    im = Image.new("1", (8, 9), 0)
    dr = ImageDraw.Draw(im)
    dr.fontmode = "1"
    dr.text((0, 0), ch, font=_FONT, fill=1)
    px = im.load()
    cells = [(x, y) for y in range(9) for x in range(8) if px[x, y]]
    adv = int(round(_FONT.getlength(ch))) or 6
    g = (adv, cells)
    _GLYPHS[ch] = g
    return g


def a8_from_cells(cells, scale, w, h, ox=0, oy=0):
    """Маска A8 из клеток: каждая клетка — квадрат scale×scale."""
    import cairo
    s = cairo.ImageSurface(cairo.FORMAT_A8, max(1, w), max(1, h))
    cr = cairo.Context(s)
    cr.set_source_rgba(0, 0, 0, 1)
    for x, y in cells:
        cr.rectangle(ox + x * scale, oy + y * scale, scale, scale)
    cr.fill()
    s.flush()
    return s


def text_mask(text, scale):
    """Строка целиком в маску A8 (часы, дата, подсказка). → (маска, ширина, высота)."""
    cells, x = [], 0
    for ch in text:
        adv, cs = glyph(ch)
        cells += [(x + cx, cy) for cx, cy in cs]
        x += adv
    return a8_from_cells(cells, scale, x * scale, 9 * scale), x * scale, 9 * scale


def bitmap_cells(rows):
    return [(x, y) for y, row in enumerate(rows) for x, c in enumerate(row) if c == "#"]


# ── буквы надписи ──────────────────────────────────────────────────────────
class Letter:
    """Буква надписи: глиф PxPlus ×2 (штрих в две клетки), под ним три контура-эха
    вниз-вправо. Всё в ОДНОЙ маске A8: эхо — 42/60/82 % (на чёрном это и есть
    «темнее»), заливка — 100 % поверх. На кадр — одна операция с маской."""

    ECHO = (0.42, 0.60, 0.82)           # дальнее → ближнее

    def __init__(self, ch, cell):
        import cairo
        _adv, cs = glyph(ch)
        # ×2 и ещё клетка вправо: вертикальный штрих — три клетки, горизонтальный —
        # две. Тоньше PxPlus ×2 надпись выходила «воздушной», образец — плотнее.
        cells = set()
        for x, y in cs:
            for dx in (0, 1, 2):
                for dy in (0, 1):
                    cells.add((2 * x + dx, 2 * y + dy))
        xs = [c[0] for c in cells] or [0]
        x0 = min(xs)
        cells = {(x - x0, y) for x, y in cells}
        self.cells = sorted(cells)
        self.cols = max(xs) - x0 + 1
        self.rows = 18
        self.cell = cell
        self.step = max(2, round(cell * 0.58))      # сдвиг одного эха
        self.lw = max(2, round(cell * 0.26))        # толщина линии контура
        pad = self.lw + 2
        far = self.step * len(self.ECHO)
        self.w = self.cols * cell
        self.h = self.rows * cell
        self.pad = pad
        mw, mh = self.w + far + 2 * pad, self.h + far + 2 * pad
        s = cairo.ImageSurface(cairo.FORMAT_A8, mw, mh)
        cr = cairo.Context(s)
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        edges = self.edges(cells)
        for k, a in zip(range(len(self.ECHO), 0, -1), self.ECHO):
            off = pad + k * self.step
            cr.set_operator(cairo.OPERATOR_SOURCE)
            cr.set_source_rgba(0, 0, 0, a)
            for (x1, y1, x2, y2) in edges:
                # линия по границе клетки, целиком внутри «тени» буквы
                X1, Y1 = off + x1 * cell, off + y1 * cell
                X2, Y2 = off + x2 * cell, off + y2 * cell
                if Y1 == Y2:
                    cr.rectangle(min(X1, X2), Y1 - self.lw // 2, abs(X2 - X1) + self.lw // 2, self.lw)
                else:
                    cr.rectangle(X1 - self.lw // 2, min(Y1, Y2), self.lw, abs(Y2 - Y1) + self.lw // 2)
            cr.fill()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 1)
        for x, y in cells:
            cr.rectangle(pad + x * cell, pad + y * cell, cell, cell)
        cr.fill()
        s.flush()
        self.mask = s
        self.mw, self.mh = mw, mh
        self.pat = cairo.SurfacePattern(s)
        self.pat.set_filter(cairo.FILTER_NEAREST)
        self.turned = {}

    TILT_STEP = 0.5 * math.pi / 180     # наклон — ступенями по полградуса

    def turned_mask(self, ang):
        """Маска, заранее повёрнутая на ближайшую ступень наклона: (маска, dx, dy).

        Поворот маски прямо в кадре (cairo, NEAREST) стоил 2,3 мс из 2,6 на всю
        надпись — 12 % ядра при 30 к/с. Ступени по 0,5° готовятся один раз (на
        ±3° их 13 на букву, ~5 МБ на всё), в кадре — простое наложение."""
        import cairo
        k = int(round(ang / self.TILT_STEP))
        got = self.turned.get(k)
        if got is None:
            r = int(math.ceil(math.hypot(self.mw, self.mh))) + 2
            surf = cairo.ImageSurface(cairo.FORMAT_A8, r, r)
            cr = cairo.Context(surf)
            cr.translate(r // 2, r // 2)
            cr.rotate(k * self.TILT_STEP)
            self.pat.set_matrix(cairo.Matrix(x0=self.w / 2 + self.pad, y0=self.h / 2 + self.pad))
            cr.set_source_rgba(0, 0, 0, 1)
            cr.mask(self.pat)
            surf.flush()
            got = self.turned[k] = self.crop(surf, r // 2, r // 2)
        return got

    @staticmethod
    def crop(surf, px, py):
        """Обрезать маску по чернилам: повёрнутый холст вдвое больше буквы, а
        градиент считается на каждый пиксель маски. → (маска, dx, dy) — где
        в ней точка опоры."""
        import cairo
        try:
            import numpy as np
        except ImportError:
            return surf, px, py
        w, h, st = surf.get_width(), surf.get_height(), surf.get_stride()
        a = np.frombuffer(surf.get_data(), np.uint8).reshape(h, st)[:, :w]
        ys, xs = np.nonzero(a.any(axis=1))[0], np.nonzero(a.any(axis=0))[0]
        if not len(ys):
            return surf, px, py
        y0, y1, x0, x1 = int(ys[0]), int(ys[-1]) + 1, int(xs[0]), int(xs[-1]) + 1
        out = cairo.ImageSurface(cairo.FORMAT_A8, x1 - x0, y1 - y0)
        cr = cairo.Context(out)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_surface(surf, -x0, -y0)
        cr.paint()
        out.flush()
        return out, px - x0, py - y0

    @staticmethod
    def edges(cells):
        out = []
        for x, y in cells:
            if (x, y - 1) not in cells:
                out.append((x, y, x + 1, y))
            if (x, y + 1) not in cells:
                out.append((x, y + 1, x + 1, y + 1))
            if (x - 1, y) not in cells:
                out.append((x, y, x, y + 1))
            if (x + 1, y) not in cells:
                out.append((x + 1, y, x + 1, y + 1))
        return out


# ── сцена одного монитора ──────────────────────────────────────────────────
def ease_out(p):
    p = max(0.0, min(1.0, p))
    return 1 - (1 - p) ** 3


def ease_sine(p):
    """Плавно в обе стороны: блок трогается и садится без рывка."""
    p = max(0.0, min(1.0, p))
    return 0.5 - 0.5 * math.cos(math.pi * p)


def ease_cubic(p):
    p = max(0.0, min(1.0, p))
    return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2


class _Rects:
    """Квадраты одного размера, сгруппированные по цвету: один fill на цвет, а
    не на каждую из ~900 клеток надписи."""

    def __init__(self):
        self.g = {}

    def add(self, rgb, a, x, y):
        a = round(a * 20) / 20
        if a > 0:
            self.g.setdefault((rgb, a), []).append((x, y))

    def flush(self, cr, s):
        for (rgb, a), pts in self.g.items():
            cr.set_source_rgba(*rgb, a)
            for x, y in pts:
                cr.rectangle(x, y, s, s)
            cr.fill()


RU_DAYS = ("понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье")
RU_MONTHS = ("января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа",
             "сентября", "октября", "ноября", "декабря")


def ru_date(t=None):
    lt = time.localtime(t)
    return "%s, %d %s" % (RU_DAYS[lt.tm_wday], lt.tm_mday, RU_MONTHS[lt.tm_mon - 1])


class Scene:
    """Всё, что рисуется на одном мониторе. Чистая отрисовка cairo по времени t
    (секунды с показа), без GTK — её же зовут проверки, замер и jarvis_lock.

    Всё, что видно, — функция (seed, t): сборки и осыпания планируются своим
    генератором на каждый номер цикла, поэтому jarvis_lock, создав сцену с тем же
    зерном посреди показа, рисует ровно то же, что слой-заставка (случайны только
    мелочи: помехи, мерцание снега)."""

    T_LETTERS = 0.55        # начало первой сборки
    SETTLE = 0.35           # буква собрана — проступает эхо
    LAND = 0.45             # клетка на месте — из «снега» в цвет надписи
    DT_CHAR = 0.032         # шаг подзаголовка
    WAVE_T = 7.0            # период «дыхания» волны, с
    DRIFT = 9.0             # за столько секунд перелив проходит всю гамму
    OUT_GLITCH = 0.45       # помеха перед осыпанием
    OUT_FADE = 0.25         # маски букв гаснут, остаются клетки
    GAP = 0.8               # пустота между осыпанием и новой сборкой

    def __init__(self, w, h, theme, main=True, seed=None, hint=None, cycle=None, effect=None):
        self.w, self.h, self.theme, self.main = w, h, theme, main
        self.seed = (int(seed) if seed is not None else random.getrandbits(31)) & 0x7FFFFFFF
        self.rnd = random.Random(self.seed)
        self.hint = HINT if hint is None else hint
        self.cycle = cycle_seconds() if cycle is None else float(cycle)
        self.effect = effect_name() if effect is None else effect
        self.clock_text = None
        self.clock_mask = None
        self.glitch = None
        self.force_glitch = None
        self.next_glitch = 0.0
        self.roll_at = 0.0
        # сборки и осыпания
        self.k = -1
        self.fx = None
        self.blocks = []
        self.letter_done = []
        self.build_t = self.build_end = 0.0
        self.first_landed = 0.0
        self.next_cycle = float("inf")
        self.outro, self.outro_t, self.outro_end, self.outro_kind = [], None, 0.0, None
        self._tv = (None, [])
        if main:
            self.build_main()
        else:
            self.build_side()
        self.next_glitch = self.t_clock() + 4.0 + self.rnd.uniform(0, 4)
        self.roll_at = self.t_clock() + 2.0 + self.rnd.uniform(0, 3)
        self.build_stars()

    # ── раскладка ────────────────────────────────────────────────────────
    def build_main(self):
        w, h = self.w, self.h
        probe = [Letter(c, 1) for c in SLOGAN]
        gap = 3
        cols = sum(l.cols for l in probe) + gap * (len(probe) - 1)
        cell = max(4, int(w * 0.60 / cols))
        self.cell = cell
        self._cb = cell * 2                           # шаг кэша цвета клеток
        self.letters = [Letter(c, cell) for c in SLOGAN]
        steps = int(math.ceil(0.05 / Letter.TILT_STEP))
        for l in self.letters:
            for k in range(-steps, steps + 1):
                l.turned_mask(k * Letter.TILT_STEP)
        tw = cols * cell
        self.tx0 = (w - tw) // 2
        self.tw = tw
        x = self.tx0
        self.lx = []
        for l in self.letters:
            self.lx.append(x)
            x += (l.cols + gap) * cell
        th = 18 * cell
        self.th = th
        self.ty0 = int(h * 0.40 - th / 2)
        self.amp = cell * 0.75                        # размах волны
        self.tilt = 0.05                              # наклон, рад (~3°)
        m = int(self.amp + cell * 3 + self.letters[0].step * 3 + self.letters[0].pad)
        self.title_rect = (self.tx0 - m - cell * 3, self.ty0 - m,
                           tw + 2 * m + cell * 6, th + 2 * m)
        # первая сборка — от неё отсчитываются подзаголовок, часы, помехи
        self.start_build(self.T_LETTERS)
        self.first_landed = max(self.letter_done)
        # подзаголовок
        self.sub_scale = max(2, cell // 3)
        s = self.sub_scale
        self.sub = []
        x = 0
        for ch in SUBTITLE:
            adv, cs = glyph(ch)
            if cs:
                xs = [c[0] for c in cs]
                ys = [c[1] for c in cs]
                ox, oy = min(xs), min(ys)
                mw = (max(xs) - ox + 1) * s
                mh = (max(ys) - oy + 1) * s
                mask = a8_from_cells([(cx - ox, cy - oy) for cx, cy in cs], s, mw, mh)
                self.sub.append((x + ox * s, oy * s, mask, mw, mh))
            else:
                self.sub.append(None)
            x += adv * s
        self.sub_w = x
        self.sx0 = (w - x) // 2
        self.sy0 = self.ty0 + th + int(cell * 2.6)
        self.sub_amp = s * 1.6
        self.sub_rect = (self.sx0 - s * 2, self.sy0 - int(self.sub_amp) - s * 4,
                         x + s * 4, 9 * s + int(2 * self.sub_amp) + s * 8)
        # часы, дата, подсказка
        self.clock_scale = max(3, cell // 2 - 1)
        self.date_scale = max(2, cell // 6)
        self.cy0 = self.sy0 + 9 * s + int(cell * 2.0)
        self.hint_scale = 2 if h >= 900 else 1
        self.hint_mask, self.hint_w, self.hint_h = text_mask(self.hint, self.hint_scale)
        # Над надписью: телевизор с «снегом», шкала сигнала и пара искр.
        cx = w // 2
        top = self.ty0 - int(cell * 1.6)
        ts = max(2, int(cell * 0.40))
        tvw, tvh = len(TV[0]) * ts, len(TV) * ts
        tvx, tvy = cx - tvw // 2, int(top - cell * 1.2 - tvh / 2)
        sx, sy, sw, sh = TV_SCREEN
        self.tv = dict(x=tvx, y=tvy, w=tvw, h=tvh, s=ts,
                       mask=a8_from_cells(bitmap_cells(TV), ts, tvw, tvh),
                       screen=(tvx + sx * ts, tvy + sy * ts, sw, sh))
        gs = max(2, int(cell * 0.36))
        self.sig = dict(x=int(cx + cell * 4.6), y=int(tvy + tvh - 5 * gs - ts * 1.5), s=gs,
                        w=7 * gs, h=4 * gs)
        self.cluster = []
        for dx, dy, bm, sc in ((-7.6, -0.4, PLUS, 0.30), (-4.9, -1.8, TWINKLE, 0.34),
                               (7.4, -0.5, DOT, 0.42), (9.0, -1.9, TWINKLE, 0.30)):
            scale = max(2, int(cell * sc))
            bw = len(bm[0]) * scale
            bh = len(bm) * scale
            x0 = int(cx + dx * cell - bw / 2)
            y0 = int(top + dy * cell - bh / 2)
            self.cluster.append(dict(x=x0, y=y0, w=bw, h=bh,
                                     mask=a8_from_cells(bitmap_cells(bm), scale, bw, bh),
                                     per=self.rnd.uniform(1.6, 3.2), ph=self.rnd.uniform(0, 6.28)))
        boxes = [(c["x"], c["y"], c["w"], c["h"]) for c in self.cluster]
        boxes += [(tvx, tvy, tvw, tvh), (self.sig["x"], self.sig["y"], self.sig["w"], self.sig["h"])]
        x0 = min(b[0] for b in boxes)
        y0 = min(b[1] for b in boxes)
        self.cluster_rect = (x0 - 2, y0 - 2, max(b[0] + b[2] for b in boxes) - x0 + 4,
                             max(b[1] + b[3] for b in boxes) - y0 + 4)
        # Надпись, гроздь и подзаголовок перекрываются — в кадре это ОДНА область,
        # иначе пересечение рисовалось дважды (замер: 2,3 мс вместо 1,2).
        rs = (self.title_rect, self.sub_rect, self.cluster_rect)
        x0 = min(r[0] for r in rs)
        y0 = min(r[1] for r in rs)
        self.text_rect = (x0, y0, max(r[0] + r[2] for r in rs) - x0, max(r[1] + r[3] for r in rs) - y0)
        self.avoid = (self.title_rect[0], self.cluster_rect[1] - cell,
                      self.title_rect[2], self.cy0 + 12 * self.clock_scale + 12 * self.date_scale - self.cluster_rect[1] + cell * 2)

    def build_side(self):
        w, h = self.w, self.h
        self.cell = max(4, w // 160)
        # ×1,5 к прежнему (просьба: «надо увеличить немного»)
        self.clock_scale = max(9, w * 3 // 300)
        self.date_scale = max(3, self.clock_scale // 4)
        self.cy0 = int(h * 0.40)
        self.hint_scale = 2 if h >= 900 else 1
        self.hint_mask, self.hint_w, self.hint_h = text_mask(self.hint, self.hint_scale)
        cw = 5 * 6 * self.clock_scale
        self.avoid = ((w - cw) // 2 - 60, self.cy0 - 60, cw + 120, 12 * self.clock_scale + 140)

    def build_stars(self):
        """Фон — пиксели-помехи: искры, обрывки строк развёртки, снежинки, мелкие
        телевизоры и шкалы сигнала. Мерцают, как «снег» на ЭЛТ."""
        w, h = self.w, self.h
        unit = max(3, min(w, h) // 270)
        kinds = [(PLUS, 1.0), (PLUS, 1.0), (TWINKLE, 1.3), (SPARK, 0.8), (DOT, 1.5),
                 (DASH, 1.0), (SNOW, 1.0), (SNOW2, 1.0), (SIG_MINI, 0.9), (TV_MINI, 0.9)]
        ax, ay, aw, ah = self.avoid
        self.stars = []
        tries = 0
        while len(self.stars) < 16 and tries < 600:
            tries += 1
            bm, k = self.rnd.choice(kinds)
            scale = max(2, int(unit * k * self.rnd.choice((0.7, 1.0, 1.0, 1.4))))
            bw, bh = len(bm[0]) * scale, len(bm) * scale
            x = self.rnd.randint(30, w - 30 - bw)
            y = self.rnd.randint(30, h - 60 - bh)
            if ax - 20 < x + bw and x < ax + aw + 20 and ay - 20 < y + bh and y < ay + ah + 20:
                continue
            if any(abs(x - s["x"]) < 120 and abs(y - s["y"]) < 100 for s in self.stars):
                continue
            self.stars.append(dict(x=x, y=y, w=bw, h=bh,
                                   mask=a8_from_cells(bitmap_cells(bm), scale, bw, bh),
                                   per=self.rnd.uniform(3.5, 8.0), ph=self.rnd.uniform(0, 6.28),
                                   base=self.rnd.uniform(0.45, 1.0)))

    # ── сборка, осыпание, цикл ───────────────────────────────────────────
    def pick_fx(self, rng):
        if self.effect in EFFECTS:
            return self.effect
        if self.k == 0:
            return "rain"                   # первая — всегда «дождь», как в Omarchy
        return rng.choice([e for e in EFFECTS if e != self.fx])

    def start_build(self, ep):
        """Спланировать сборку надписи с момента ep. Каждая клетка глифа — блок:
        (буква, x, y, появился, тронулся, длительность, старт x, старт y)."""
        self.k += 1
        rng = random.Random(self.seed * 7919 + self.k)
        fx = self.pick_fx(rng)
        c, th = self.cell, self.th
        blocks = []
        done = [0.0] * len(self.letters)
        for i, l in enumerate(self.letters):
            for x, y in l.cells:
                low = (l.rows - 1 - y) / l.rows          # 0 — нижняя строка
                sx = None
                if fx == "rain":
                    # Случайный порядок, нижние строки немного раньше — надпись
                    # не «висит» дырявой сверху. Падение медленное, ~2 с.
                    t0 = ep + (0.35 * low + 0.65 * rng.random()) * 3.2
                    dur = rng.uniform(1.8, 2.7)
                    sy = rng.uniform(-3 * c, self.ty0 * 0.35)
                    ap = t0
                elif fx == "pour":
                    r = l.rows - 1 - y
                    fr = (self.lx[i] + x * c - self.tx0) / max(1, self.tw)
                    if r % 2:
                        fr = 1 - fr
                    t0 = ep + r * 0.2 + fr * 0.6
                    dur = rng.uniform(1.2, 1.45)
                    sy = -2 * c
                    ap = t0
                else:                                    # tune
                    ap = ep
                    t0 = ep + 0.6 + rng.uniform(0, 1.4)
                    dur = rng.uniform(1.5, 2.3)
                    sx = rng.uniform(self.tx0 - self.tw * 0.12, self.tx0 + self.tw * 1.12)
                    sy = rng.uniform(max(c, self.ty0 - th * 1.6), min(self.h - 4 * c, self.ty0 + th * 2.4))
                blocks.append((i, x, y, ap, t0, dur, sx, sy))
                done[i] = max(done[i], t0 + dur)
        self.blocks, self.letter_done, self.fx = blocks, done, fx
        self.build_t = ep
        self.build_end = max(done) + self.SETTLE + self.LAND
        self.next_cycle = self.build_end + self.cycle if self.cycle > 0 else float("inf")

    def start_outro(self, ts):
        """Осыпание надписи с момента ts: «crumble» — клетки падают вниз за экран,
        «dissolve» — рассыпаются в снег на месте."""
        rng = random.Random(self.seed * 104729 + self.k)
        kind = "dissolve" if rng.random() < 0.35 else "crumble"
        c = self.cell
        out, end = [], ts
        for i, l in enumerate(self.letters):
            for x, y in l.cells:
                if kind == "crumble":
                    t0 = ts + self.OUT_FADE * 0.5 + rng.uniform(0, 1.5)
                    dur = rng.uniform(1.3, 1.9)
                    dx = rng.uniform(-1.5, 1.5) * c
                else:
                    t0 = ts + rng.uniform(0, 1.6)
                    dur = rng.uniform(0.35, 0.6)
                    dx = 0.0
                out.append((i, x, y, t0, dur, dx))
                end = max(end, t0 + dur)
        self.outro, self.outro_t, self.outro_end, self.outro_kind = out, ts, end, kind

    def advance(self, t):
        """Довести цикл до момента t (можно прыжком: jarvis_lock подхватывает
        сцену посреди показа)."""
        if not self.main:
            return
        for _ in range(10000):
            if self.outro_t is None:
                if t >= self.next_cycle:
                    start = self.next_cycle
                    self.force_glitch = (start, start + self.OUT_GLITCH)
                    self.next_cycle = float("inf")
                    self.start_outro(start + self.OUT_GLITCH)
                    continue
                return
            if t >= self.outro_end:
                ep = self.outro_end + self.GAP
                self.outro, self.outro_t = [], None
                self.start_build(ep)
                continue
            return

    def steady(self, t):
        """Ничего не сыплется: можно рисовать 30 к/с и только изменившееся."""
        if t <= self.t_clock() + 1.2:
            return False
        if not self.main:
            return True
        if t < self.build_end:
            return False
        return self.outro_t is None or t < self.outro_t - self.OUT_GLITCH

    # ── что меняется во времени ──────────────────────────────────────────
    def poses(self, t):
        """[(центр x, центр y, cos, sin)] букв в момент t: волна + наклон."""
        out = []
        for i, l in enumerate(self.letters):
            ph = 2 * math.pi * t / self.WAVE_T + i * 0.62
            ang = self.tilt * math.cos(ph + 0.5)
            out.append((self.lx[i] + l.w / 2, self.ty0 + self.amp * math.sin(ph) + l.h / 2,
                        math.cos(ang), math.sin(ang)))
        return out

    def cell_at(self, P, i, x, y):
        """Где в момент кадра стоит клетка (x, y) буквы i — с волной и наклоном."""
        cx, cy, ca, sa = P[i]
        l, c = self.letters[i], self.cell
        ox, oy = (x + 0.5) * c - l.w / 2, (y + 0.5) * c - l.h / 2
        return cx + ox * ca - oy * sa, cy + ox * sa + oy * ca

    def letter_pose(self, i, t):
        """(x, y, угол, прозрачность) буквы i, или None — буквы сейчас нет
        (её ещё собирают блоки или она уже осыпалась)."""
        l = self.letters[i]
        t_done = self.letter_done[i]
        if t < t_done:
            return None
        a = min(1.0, (t - t_done) / self.SETTLE)
        if self.outro_t is not None and t >= self.outro_t:
            a *= 1.0 - (t - self.outro_t) / self.OUT_FADE
            if a <= 0:
                return None
        ph = 2 * math.pi * t / self.WAVE_T + i * 0.62
        y = self.ty0 + self.amp * math.sin(ph)
        ang = self.tilt * math.cos(ph + 0.5)
        return round(self.lx[i] + l.w / 2), round(y + l.h / 2), ang, a

    def _col(self, cache, x, t, grey=0.0):
        b = int(x // self._cb)
        g = round(grey * 8) / 8
        v = cache.get((b, g))
        if v is None:
            base = self.color_at((b + 0.5) * self._cb, t)
            v = cache[(b, g)] = mix(base, self.theme["static"], g) if g else base
        return v

    def draw_blocks(self, cr, t):
        """Сборка: клетки в полёте и уже севшие (пока буква не собрана целиком)."""
        P = self.poses(t)
        c = self.cell
        half = c / 2
        cache, R = {}, _Rects()
        tune = self.fx == "tune"
        for i, x, y, ap, t0, dur, sx, sy in self.blocks:
            if t < ap or t >= self.letter_done[i] + self.SETTLE:
                continue
            p = (t - t0) / dur
            if p < 0:                               # «tune»: снег на месте старта
                a = (0.25 + 0.6 * self.rnd.random()) * min(1.0, (t - ap) / 0.3)
                R.add(self.theme["static"], a, round(sx - half), round(sy - half))
                continue
            tx, ty = self.cell_at(P, i, x, y)
            if p < 1:
                if tune:
                    e = ease_cubic(p)
                    xx, yy = sx + (tx - sx) * e, sy + (ty - sy) * e
                    grey, a = 1.0 - e, 0.55 + 0.45 * e
                else:
                    e = ease_sine(p)
                    xx, yy = tx, sy + (ty - sy) * e
                    grey, a = 0.55, 0.5 + 0.35 * e
            else:
                xx, yy = tx, ty
                q = min(1.0, (t - t0 - dur) / self.LAND)
                grey = 0.0 if tune else 0.55 * (1 - q)
                a = 1.0 if tune else 0.85 + 0.15 * q
            R.add(self._col(cache, xx, t, grey), a, round(xx - half), round(yy - half))
        R.flush(cr, c)

    def draw_outro(self, cr, t):
        P = self.poses(t)
        c = self.cell
        half = c / 2
        cache, R = {}, _Rects()
        crumble = self.outro_kind == "crumble"
        for i, x, y, t0, dur, dx in self.outro:
            if t >= t0 + dur:
                continue
            tx, ty = self.cell_at(P, i, x, y)
            if t < t0:
                R.add(self._col(cache, tx, t), 1.0, round(tx - half), round(ty - half))
                continue
            q = (t - t0) / dur
            if crumble:
                xx, yy = tx + dx * q, ty + (self.h + 2 * c - ty) * q * q
                a = 1.0 if q < 0.6 else (1 - q) / 0.4
                grey = 0.5 * q
            else:
                xx, yy = tx, ty
                a = (1 - q) * (0.3 + 0.7 * self.rnd.random())
                grey = min(1.0, q * 2.5)
            R.add(self._col(cache, xx, t, grey), a, round(xx - half), round(yy - half))
        R.flush(cr, c)

    def t_subtitle(self):
        return self.first_landed + 0.2

    def t_clock(self):
        if not self.main:
            return 0.5
        return self.t_subtitle() + len(SUBTITLE) * self.DT_CHAR + 0.15

    def intro_done(self, t):
        return t > self.t_clock() + 1.2

    def update_glitch(self, t):
        """ТВ-помеха: раз в 7–15 с на 0,2–0,4 с, и обязательно — перед осыпанием.
        Полосы сбиваются вбок, рядом — цветная тень, по одной строке — шум.
        Полосы меняются каждые 2 кадра."""
        g = self.glitch
        if g and t > g["end"]:
            self.glitch = g = None
        if not g and self.main:
            fg = self.force_glitch
            if fg and fg[0] <= t < fg[1]:
                self.glitch = g = dict(end=fg[1], roll=-1)
                self.force_glitch = None
            elif fg and t >= fg[1]:
                self.force_glitch = None
            elif self.steady(t) and t >= self.next_glitch:
                dur = self.rnd.uniform(0.18, 0.38)
                self.glitch = g = dict(end=t + dur, roll=-1)
                self.next_glitch = t + self.rnd.uniform(7.0, 15.0)
        if g:
            k = int(t * FPS / 2)
            if k != g["roll"]:
                g["roll"] = k
                c = self.cell
                th = 18 * c
                g["bands"] = [(self.ty0 + self.rnd.randint(0, 16) * c - c,
                               self.rnd.randint(1, 3) * c,
                               self.rnd.choice((-1, 1)) * self.rnd.randint(c // 2, int(c * 2.6)))
                              for _ in range(self.rnd.randint(2, 4))]
                g["ghost"] = self.rnd.choice((-1, 1)) * max(2, c // 2)
                ny = self.ty0 + self.rnd.randint(0, th)
                g["noise"] = [(self.tx0 + self.rnd.randint(0, self.tw), ny + self.rnd.randint(-c, c))
                              for _ in range(self.rnd.randint(20, 46))]
        return g

    # ── отрисовка ────────────────────────────────────────────────────────
    def draw(self, cr, t, clip=None):
        import cairo
        self.advance(t)
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        if clip is None:
            clip = (0, 0, self.w, self.h)

        def hit(r):
            return (r[0] < clip[0] + clip[2] and clip[0] < r[0] + r[2]
                    and r[1] < clip[1] + clip[3] and clip[1] < r[1] + r[3])

        star_in = max(0.0, min(1.0, (t - 0.4) / 1.2))
        for s in self.stars:
            if hit((s["x"], s["y"], s["w"], s["h"])):
                tw = 0.5 + 0.5 * math.sin(2 * math.pi * t / s["per"] + s["ph"])
                a = s["base"] * (0.18 + 0.82 * tw * tw) * star_in
                if a > 0.01:
                    cr.set_source_rgba(*self.theme["star"], a)
                    cr.mask_surface(s["mask"], s["x"], s["y"])
        if self.main:
            # Осыпание идёт до низа экрана, сборка — от верха: тогда весь экран
            # перерисовывается (dirty → None), клип — целиком.
            if hit(self.title_rect) or not self.steady(t):
                self.draw_title(cr, t)
            if hit(self.cluster_rect):
                self.draw_cluster(cr, t)
            if hit(self.sub_rect):
                self.draw_subtitle(cr, t)
        r = self.clock_rect()
        if hit(r):
            self.draw_clock(cr, t)
        r = self.hint_rect()
        if hit(r):
            a = max(0.0, min(1.0, (t - self.t_clock() - 0.5) / 0.6))
            if a > 0:
                cr.set_source_rgba(*self.theme["hint"], a)
                cr.mask_surface(self.hint_mask, r[0], r[1])

    def color_at(self, x, t):
        u = (x - self.tx0) / max(1, self.tw) * 0.85 + t / self.DRIFT
        return ramp_color(self.theme, u)

    def paint_letters(self, cr, t, dx=0, color=None, alpha=1.0):
        import cairo
        for i, l in enumerate(self.letters):
            pose = self.letter_pose(i, t)
            if pose is None:
                continue
            cx, cy, ang, a = pose
            mask, hx, hy = l.turned_mask(ang)
            if color is None:
                gx = self.lx[i] + dx
                span = l.w + l.step * 3
                g = cairo.LinearGradient(gx, 0, gx + span, 0)
                for stop in (0.0, 0.5, 1.0):
                    g.add_color_stop_rgba(stop, *self.color_at(gx - dx + stop * span, t), a * alpha)
                cr.set_source(g)
            else:
                cr.set_source_rgba(*color, a * alpha)
            cr.mask_surface(mask, cx + dx - hx, cy - hy)

    def draw_title(self, cr, t):
        import cairo
        g = self.update_glitch(t)
        if self.outro_t is not None and t >= self.outro_t:
            self.draw_outro(cr, t)                  # клетки под гаснущими масками
        if not g:
            self.paint_letters(cr, t)
        else:
            # Кадр помехи: надпись — в отдельную картинку, потом полосы со сдвигом.
            x0, y0, rw, rh = self.title_rect
            surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, rw, rh)
            c2 = cairo.Context(surf)
            c2.translate(-x0, -y0)
            ghost = ramp_color(self.theme, t / self.DRIFT + 1.0)
            self.paint_letters(c2, t, dx=g["ghost"], color=ghost, alpha=0.45)
            self.paint_letters(c2, t)
            surf.flush()
            cr.set_source_surface(surf, x0, y0)
            cr.get_source().set_filter(cairo.FILTER_NEAREST)
            cr.paint()
            for by, bh, bdx in g["bands"]:
                cr.save()
                cr.rectangle(x0, by, rw, bh)
                cr.clip()
                cr.set_source_rgb(0, 0, 0)
                cr.paint()
                cr.set_source_surface(surf, x0 + bdx, y0)
                cr.get_source().set_filter(cairo.FILTER_NEAREST)
                cr.paint()
                cr.restore()
            sq = max(2, self.cell // 3)
            for nx, ny in g["noise"]:
                v = self.rnd.uniform(0.25, 0.8)
                cr.set_source_rgba(v, v, v, 0.75)
                cr.rectangle(nx - nx % sq, ny - ny % sq, sq * self.rnd.randint(1, 3), sq)
                cr.fill()
        if self.build_t <= t < self.build_end:
            self.draw_blocks(cr, t)
        # Едва заметная «прокатка» ЭЛТ: тёмная полоса раз в несколько секунд
        # медленно проходит сверху вниз по надписи.
        if self.steady(t):
            if t > self.roll_at + 1.4:
                self.roll_at = t + self.rnd.uniform(4.0, 9.0)
            p = (t - self.roll_at) / 1.4
            if 0 <= p <= 1:
                y = self.ty0 - self.amp + p * (self.th + 2 * self.amp)
                cr.set_source_rgba(0, 0, 0, 0.32)
                cr.rectangle(self.title_rect[0], int(y), self.title_rect[2], self.cell)
                cr.fill()

    def signal(self, t):
        """(делений шкалы 0–4, густота снега в телевизоре) — по фазе цикла:
        перед осыпанием и в паузе сигнал пропадает, при сборке — возвращается."""
        if self.outro_t is not None and t >= self.outro_t - self.OUT_GLITCH:
            return 0, 0.75
        if self.k > 0 and self.build_t - self.GAP <= t < self.build_end:
            p = max(0.0, min(1.0, (t - self.build_t) / max(0.1, self.build_end - self.build_t)))
            return min(4, int(p * 5)), 0.75 - 0.5 * p
        return (4, 4, 3, 4, 4, 4, 2, 3, 4, 4)[int(t / 1.3) % 10], 0.22

    def draw_cluster(self, cr, t):
        t0 = self.first_landed - 0.3
        if t < t0:
            return
        k = min(1.0, (t - t0) / 0.8)
        for c in self.cluster:
            tw = 0.5 + 0.5 * math.sin(2 * math.pi * t / c["per"] + c["ph"])
            cr.set_source_rgba(*self.color_at(c["x"], t), k * (0.35 + 0.65 * tw))
            cr.mask_surface(c["mask"], c["x"], c["y"])
        level, dens = self.signal(t)
        # телевизор: корпус в цвет надписи, на экране — снег
        tv = self.tv
        cr.set_source_rgba(*self.color_at(tv["x"] + tv["w"] / 2, t), k)
        cr.mask_surface(tv["mask"], tv["x"], tv["y"])
        roll = (int(t * 12), round(dens, 2))
        if roll != self._tv[0]:
            rng = random.Random(roll[0] * 31 + self.seed)
            sx, sy, sw, sh = tv["screen"]
            s = tv["s"]
            self._tv = (roll, [(sx + x * s, sy + y * s, round(rng.uniform(0.3, 1.0) * 4) / 4)
                               for y in range(sh) for x in range(sw) if rng.random() < dens])
        st = self.theme["static"]
        for x, y, v in self._tv[1]:
            cr.set_source_rgba(*mix(st, (1, 1, 1), v * 0.5), k * (0.35 + 0.55 * v))
            cr.rectangle(x, y, tv["s"], tv["s"])
            cr.fill()
        # шкала сигнала: горящие деления — цветом надписи, пустые — тусклые;
        # без сигнала мигает первое деление
        sg = self.sig
        s = sg["s"]
        lit = self.color_at(sg["x"], t)
        for j in range(4):
            on = j < level or (level == 0 and j == 0 and int(t * 2.5) % 2 == 0)
            if on:
                cr.set_source_rgba(*(lit if level else st), k)
            else:
                cr.set_source_rgba(*st, k * 0.18)
            bh = (j + 1) * s
            cr.rectangle(sg["x"] + j * 2 * s, sg["y"] + 4 * s - bh, s, bh)
            cr.fill()

    def draw_subtitle(self, cr, t):
        t0 = self.t_subtitle()
        s = self.sub_scale
        for j, item in enumerate(self.sub):
            if item is None:
                continue
            tj = t0 + j * self.DT_CHAR
            if t < tj:
                break
            x, oy, mask, _mw, _mh = item
            ph = 2 * math.pi * t / self.WAVE_T + (self.sx0 + x) / max(1, self.tw) * 2 * math.pi * 0.85
            y = self.sy0 + oy + self.sub_amp * math.sin(ph + 1.3)
            p = (t - tj) / 0.18
            a = 1.0
            if p < 1:
                y -= math.sin(math.pi * p) * s * 2
                a = min(1.0, p * 3)
            cr.set_source_rgba(*self.color_at(self.sx0 + x, t - 0.8), a)
            cr.mask_surface(mask, self.sx0 + x, round(y))

    def clock_rect(self):
        cs, ds = self.clock_scale, self.date_scale
        cw = 5 * 6 * cs
        dw = 34 * 6 * ds
        wmax = max(cw, dw)
        return ((self.w - wmax) // 2 - 4, self.cy0 - 4, wmax + 8, 9 * cs + int(ds * 4) + 9 * ds + 8)

    def hint_rect(self):
        return ((self.w - self.hint_w) // 2, self.h - self.hint_h - max(24, self.h // 36),
                self.hint_w, self.hint_h)

    def clock_strings(self, now=None):
        return time.strftime("%H:%M", time.localtime(now)), ru_date(now)

    def draw_clock(self, cr, t, now=None):
        a = max(0.0, min(1.0, (t - self.t_clock()) / 0.5))
        if a <= 0:
            return
        txt = self.clock_strings(now)
        if txt != self.clock_text:
            self.clock_text = txt
            self.clock_mask = (text_mask(txt[0], self.clock_scale), text_mask(txt[1], self.date_scale))
        (cm, cw, ch), (dm, dw, _dh) = self.clock_mask
        x = (self.w - cw) // 2
        if self.main:
            cr.set_source_rgba(*self.theme["fg"], a)
        else:
            import cairo
            g = cairo.LinearGradient(x, 0, x + cw, 0)
            g.add_color_stop_rgba(0, *ramp_color(self.theme, 0.15), a)
            g.add_color_stop_rgba(1, *ramp_color(self.theme, 0.85), a)
            cr.set_source(g)
        cr.mask_surface(cm, x, self.cy0)
        cr.set_source_rgba(*self.theme["dim"], a * 0.8)
        cr.mask_surface(dm, (self.w - dw) // 2, self.cy0 + ch + self.date_scale * 4)

    def dirty(self, t, frame):
        """Прямоугольники, которые надо перерисовать в этом кадре; None — весь экран."""
        self.advance(t)
        if not self.steady(t):
            return None                                   # сборка/осыпание: весь экран
        out = []
        if self.main and (frame % 2 == 0 or self.glitch):
            # В покое волна сдвигает букву меньше чем на полпикселя за кадр
            # (координаты целые), так что надпись — 15 к/с, помеха — все 30.
            out.append(self.text_rect)
        if frame % 3 == 0:
            out += [(s["x"], s["y"], s["w"], s["h"]) for s in self.stars]
        if self.clock_strings() != self.clock_text:
            out.append(self.clock_rect())
        return out


class Pacer:
    """Темп кадров одной сцены при таймере 60 Гц: пока сыплется — каждый тик
    (60 к/с, просьба: «плавнее»), в покое — через тик (30), под глубоким
    приглушением hypridle — каждый шестой (10: экран почти чёрный)."""

    def __init__(self):
        self.tick = 0
        self.frame = 0
        self.dim_at = 0.0
        self.deep = False

    def plan(self, scene, t):
        """False — в этом тике ничего; None — весь экран; иначе список областей."""
        self.tick += 1
        now = time.monotonic()
        if now - self.dim_at > 2.0:
            self.dim_at = now
            self.deep = dim_deep()
        fast = not scene.steady(t)
        step = 6 if self.deep else (1 if fast else 2)
        if self.tick % step:
            return False
        self.frame += 1
        return scene.dirty(t, self.frame)


# ── показ (GTK) ────────────────────────────────────────────────────────────
def run_show():
    # Второй экземпляр не плодим: замок держит показанная заставка.
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("заставка уже на экране")
        return 0
    os.ftruncate(fd, 0)
    os.write(fd, str(os.getpid()).encode())
    disarm()                                # ждущий arm больше не нужен

    # Уйдём под блокировку целиком? Тогда снимок рабочего стола для формы
    # jarvis_lock — сейчас, пока заставки ещё нет на экране.
    handoff = lockmode_active()
    if handoff:
        save_backgrounds(_niri_json("outputs"))

    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gdk, Gio, GLib, Gtk, GtkLayerShell
    import cairo

    theme = load_theme()
    seed = random.getrandbits(31)
    cycle, effect = cycle_seconds(), effect_name()

    class SaverWindow(Gtk.Window):
        def __init__(self, app, monitor, main):
            super().__init__(title="staticOS")
            self.app, self.monitor, self.main = app, monitor, main
            GtkLayerShell.init_for_window(self)
            GtkLayerShell.set_namespace(self, "jarvis-screensaver")
            GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
            for e in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                      GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
                GtkLayerShell.set_anchor(self, e, True)
            GtkLayerShell.set_exclusive_zone(self, -1)
            if monitor is not None:
                GtkLayerShell.set_monitor(self, monitor)
            # Клавиатура — только у главного: два EXCLUSIVE-слоя спорили бы за неё.
            GtkLayerShell.set_keyboard_mode(
                self, GtkLayerShell.KeyboardMode.EXCLUSIVE if main else GtkLayerShell.KeyboardMode.NONE)
            self.set_app_paintable(True)
            vis = self.get_screen().get_rgba_visual()
            if vis:
                self.set_visual(vis)
            g = monitor.get_geometry() if monitor is not None else None
            w, h = (g.width, g.height) if g else (1920, 1080)
            self.set_default_size(w, h)
            # то же зерно, что получит jarvis_lock (главный — seed, остальные — seed+1)
            self.scene = Scene(w, h, theme, main=main, seed=seed if main else seed + 1,
                               cycle=cycle, effect=effect)
            self.pacer = Pacer()
            self.area = Gtk.DrawingArea()
            self.area.set_size_request(w, h)
            self.area.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.BUTTON_PRESS_MASK
                                 | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
                                 | Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.KEY_PRESS_MASK)
            self.area.connect("draw", self.on_draw)
            self.area.connect("motion-notify-event", lambda _w, e: app.on_motion(self, e.x_root, e.y_root))
            self.area.connect("enter-notify-event", lambda _w, e: app.on_motion(self, e.x_root, e.y_root))
            self.area.connect("button-press-event", lambda *_a: app.wake("щелчок"))
            self.area.connect("scroll-event", lambda *_a: app.wake("колесо"))
            self.area.connect("realize", self.on_realize)
            self.connect("key-press-event", lambda *_a: app.wake("клавиша"))
            self.add(self.area)

        def on_realize(self, area):
            # курсор прячем: заставке он ни к чему
            win = area.get_window()
            if win is not None:
                win.set_cursor(Gdk.Cursor.new_for_display(win.get_display(), Gdk.CursorType.BLANK_CURSOR))

        def on_draw(self, _w, cr):
            t = self.app.t()
            fade = self.app.fade(t)
            ok, rect = Gdk.cairo_get_clip_rectangle(cr)
            clip = (rect.x, rect.y, rect.width, rect.height) if ok else None
            if fade >= 0.999:
                self.scene.draw(cr, t, clip)
                return True
            cr.push_group()
            self.scene.draw(cr, t, clip)
            pat = cr.pop_group()
            cr.set_operator(cairo.OPERATOR_CLEAR)
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
            cr.set_source(pat)
            cr.paint_with_alpha(max(0.0, fade))
            return True

    class App:
        def __init__(self):
            self.t0 = time.monotonic()
            self.started = time.time()
            self.leaving = None             # время начала гашения
            self.anchor = None              # (x, y, когда) — начало рывка мыши
            self.handoff = handoff
            self.lock_seen = None           # когда заметили, что сеанс запирают
            self.windows = []
            disp = Gdk.Display.get_default()
            focused = self.focused_monitor(disp)
            mons = [disp.get_monitor(i) for i in range(disp.get_n_monitors())] or [None]
            if focused is None or focused not in mons:
                focused = mons[0]
            for m in mons:
                self.windows.append(SaverWindow(self, m, m is focused))
            if handoff:
                g = focused.get_geometry() if focused is not None else None
                self.write_info([g.x, g.y] if g else None)
            for w in self.windows:
                w.show_all()
            GLib.timeout_add(16, self.tick)
            GLib.timeout_add(500, self.watch_lock)
            self.watch_logind()

        def write_info(self, main_xy):
            """Для jarvis_lock: с какого момента и с каким зерном идёт показ."""
            try:
                tmp = INFO + ".tmp"
                with open(tmp, "w") as f:
                    json.dump({"pid": os.getpid(), "t0": self.t0, "seed": seed, "main": main_xy,
                               "bg": BG_DIR, "display": os.environ.get("WAYLAND_DISPLAY", "")}, f)
                os.replace(tmp, INFO)
            except OSError as e:
                log("info: %s" % e)

        def t(self):
            return time.monotonic() - self.t0

        def fade(self, t):
            if self.leaving is not None:
                return 1.0 - (time.monotonic() - self.leaving) / FADE_OUT
            return min(1.0, ease_out(t / FADE_IN))

        @staticmethod
        def focused_monitor(disp):
            """Монитор с фокусом niri — по совпадению логического положения."""
            fo = _niri_json("focused-output") or {}
            lg = fo.get("logical") or {}
            for i in range(disp.get_n_monitors()):
                m = disp.get_monitor(i)
                g = m.get_geometry()
                if lg and g.x == lg.get("x") and g.y == lg.get("y"):
                    return m
            return None

        def tick(self):
            t = self.t()
            if self.leaving is not None:
                if time.monotonic() - self.leaving >= FADE_OUT:
                    self.quit()
                    return False
                for w in self.windows:
                    w.area.queue_draw()
                return True
            for w in self.windows:
                if t < FADE_IN + 0.05:
                    w.area.queue_draw()
                    continue
                rects = w.pacer.plan(w.scene, t)
                if rects is False:
                    continue
                if rects is None:
                    w.area.queue_draw()
                else:
                    for x, y, rw, rh in rects:
                        w.area.queue_draw_area(int(x), int(y), int(rw), int(rh))
            return True

        def on_motion(self, win, x, y):
            now = time.monotonic()
            if now - self.t0 < GRACE:
                self.anchor = None
                return False
            # Рывок — движение без пауз дольше 1,5 с; дрожь мыши копится медленно
            # и в 40 px за один рывок не складывается.
            if self.anchor is None or now - self.anchor[2] > 1.5:
                self.anchor = (x, y, now)
                return False
            ax, ay, _ = self.anchor
            self.anchor = (ax, ay, now)
            if math.hypot(x - ax, y - ay) >= MOVE_PX:
                self.wake("мышь")
            return False

        def wake(self, why=""):
            if self.leaving is None:
                self.leaving = time.monotonic()
                drop_info()                 # уходим — jarvis_lock не должен нас подхватывать
            return True

        def lock_marked(self):
            """jarvis_lock запер сеанс после нашего показа и жив."""
            try:
                st = os.stat(LOCK_MARK)
            except OSError:
                return False
            return st.st_mtime >= self.started - 1 and lock_pid() is not None

        def watch_lock(self):
            kind = session_locked()
            if not self.handoff:
                if kind:
                    log("сеанс заперт — заставка убрана")
                    self.quit()
                    return False
                return True
            # Под блокировку: держимся, пока jarvis_lock не встал (он рисует ту же
            # сцену поверх), иначе между нами мелькнул бы рабочий стол.
            now = time.monotonic()
            if kind or self.lock_seen is not None:
                if self.lock_seen is None:
                    self.lock_seen = now
                if self.lock_marked():
                    log("экран блокировки подхватил заставку — слой убран")
                    self.quit()
                    return False
                if kind == "hyprlock" and now - self.lock_seen > 2.0:
                    log("заперто hyprlock — заставка убрана")
                    self.quit()
                    return False
                if now - self.lock_seen > 25.0:
                    if kind:
                        log("блокировка без метки jarvis_lock — заставка убрана")
                        self.quit()
                        return False
                    self.lock_seen = None   # ложная тревога: блокировка так и не встала
            return True

        def on_logind_lock(self, *_a):
            if self.handoff:
                if self.lock_seen is None:
                    self.lock_seen = time.monotonic()
            else:
                self.quit()

        def watch_logind(self):
            """Блокировка по простою и перед сном идёт через `loginctl lock-session`:
            сигнал Lock logind. Без lockmode — сразу уходим, не рисуем под экраном
            блокировки; с lockmode — ждём, пока jarvis_lock подхватит сцену."""
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                bus.signal_subscribe("org.freedesktop.login1", "org.freedesktop.login1.Session",
                                     "Lock", None, None, Gio.DBusSignalFlags.NONE,
                                     self.on_logind_lock, None)
                self.bus = bus
            except Exception:
                pass

        def quit(self, *_a):
            Gtk.main_quit()
            return False

    app = App()

    def on_term(*_a):
        app.wake("stop")
        return True

    try:
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, on_term)
    except ImportError:
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, on_term)
    try:
        Gtk.main()
    finally:
        drop_info()
        if handoff:
            clear_backgrounds()
    return 0


# ── замер стоимости кадра (вне экрана) ─────────────────────────────────────
def bench():
    import cairo
    theme = load_theme()
    sc = Scene(1920, 1080, theme, main=True, seed=1, cycle=60, effect="rain")
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 1920, 1080)
    cr = cairo.Context(surf)
    t = sc.t_clock() + 2.0
    sc.draw(cr, t)
    n, t_all = 0, 0.0
    for frame in range(300):
        t += 1 / FPS
        rects = sc.dirty(t, frame)
        if rects is None:
            continue
        t1 = time.perf_counter()
        for r in rects:
            c2 = cairo.Context(surf)
            c2.rectangle(*r)
            c2.clip()
            sc.draw(c2, t, r)
        t_all += time.perf_counter() - t1
        n += 1
    ms = t_all / max(1, n) * 1000
    print("кадр в покое (только изменившееся): %.2f мс → %.1f %% ядра при %d к/с" % (ms, ms * FPS / 10, FPS))
    for name, fx in (("дождь", "rain"), ("насыпание", "pour"), ("настройка", "tune")):
        s2 = Scene(1920, 1080, theme, main=True, seed=2, cycle=60, effect=fx)
        mid = (s2.build_t + s2.build_end) / 2
        t1 = time.perf_counter()
        for i in range(30):
            s2.draw(cairo.Context(surf), mid + i / 60)
        full = (time.perf_counter() - t1) / 30
        print("кадр сборки «%s» целиком: %.2f мс → %.1f %% ядра при 60 к/с" % (name, full * 1000, full * 6000))
    s3 = Scene(1920, 1080, theme, main=True, seed=3, cycle=60)
    s3.advance(s3.next_cycle + 1.0)
    mid = s3.outro_t + 0.8
    t1 = time.perf_counter()
    for i in range(30):
        s3.draw(cairo.Context(surf), mid + i / 60)
    full = (time.perf_counter() - t1) / 30
    print("кадр осыпания целиком: %.2f мс" % (full * 1000))
    return 0


if __name__ == "__main__":
    rc = cli()
    if rc is not None:
        sys.exit(rc)
    sys.exit(run_show())
