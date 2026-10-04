#!/usr/bin/env python3
"""Звуки интерфейса: короткий звук на событие оболочки. 02.10.2026.

    ui_sound.py play СОБЫТИЕ      сыграть (молча выходит, если нельзя — см. ниже)
    ui_sound.py on|off            включить / выключить все звуки (Настройки → Misc)
    ui_sound.py status            on | off
    ui_sound.py volume [0–100]    своя громкость этих звуков (без числа — показать)
    ui_sound.py notify-volume [0–100]   своя громкость звука уведомления (не зависит от volume)
    ui_sound.py pack [retro|classic|xp]   набор: Windows XP, ретро (синтез) или обычный
    ui_sound.py cat               группы событий и включены ли они
    ui_sound.py cat ГРУППА [on|off]   включить / выключить группу (без on|off — показать)
    ui_sound.py test [СОБЫТИЕ]    сыграть в обход «выкл», групп и DND (проба из Настроек)
    ui_sound.py demo              все звуки набора по очереди
    ui_sound.py list              события, группы и файлы

Идея — из дотфайлов AngelOS, код свой. Просьба: «звуки — если быстро, попробуй,
но чтобы можно было выключить»; затем: «хочу в стиле old tech / retro», «отдельную
громкость»; затем (02.10): «звуков мало… меня интересуют звуки Windows XP, можно
звуки кликов — и обязательно переключатель в настройках».

Группы (каждая выключается отдельно) и события:
    system    login, logout, shutdown, unlock            вход, выход, выключение, разблокировка
    capture   screenshot, done, error                    снимок, запись сохранена / не удалась
    devices   usb-in, usb-out, battery-low, battery-critical
    menu      menu, click                                «Пуск», меню ПКМ, кнопки панели, пункты
    timer     timer                                      таймер-виджет дозвонил
    notify    notify                  (выкл)             пришло уведомление
    windows   window-open, window-close   (выкл)         окно открылось / закрылось
    mouse     nav                     (выкл)             каждый щелчок левой кнопкой
Кто шлёт: ui_sound_watch.py (устройства, батарея, окна, мышь, уведомления), auto_dnd.py
(снимок), rec_area.sh, jarvis_lock.py, power_menu.py, xpbar.py, start_menu.py,
desktop_menu.py, виджет timer.exe, автозапуск niri (login).

Когда звука НЕТ, даже если включено: «Не беспокоить» (кроме таймера), идёт запись
экрана (rec_area) — звук попал бы в ролик, запущена игра (cs2, gamescope).

Наборы. «xp» — настоящие файлы Windows XP из ~/.config/hypr/sounds/xp/ (скачаны
02.10.2026 из github.com/MCPlayer2015/all-windows-sounds; файлы Microsoft — в свои
дотфайлы не выкладывать). «retro» — синтез ui_sound_retro.py. «classic» — штатные
freedesktop, ocean и oxygen. Наборы не смешиваются: нет звука в наборе — тишина. Свой звук поверх любого
набора: ~/.config/hypr/sounds/<событие>.wav|.oga. Наборы не смешиваются: нет звука в наборе — тишина (05.10.2026).

Громкость — свой ползунок 0–100 (state/ui-sound-volume), по той же кубической
шкале, что у системного микшера. Задаётся потоку явно (pw-play --volume) — PipeWire
её не «запоминает», как было с громким таймером на paplay. Общая громкость системы
действует поверх: это доля от неё.

Скорость: pw-play стартует ~20 мс — для щелчков годится. Долгоживущие программы
(панель, меню, сторож) зовут play() прямо из себя, без запуска этого файла; ответы
про DND и игру у них кешируются на 3 секунды.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state")
OFF = os.path.join(STATE, "ui-sound-off")
VOL = os.path.join(STATE, "ui-sound-volume")
# Своя громкость звука уведомления (04.10.2026, Настройки → Уведомления), 0–100, по той же
# кубической шкале, независимо от общей громкости звуков интерфейса. Звуки программ — не здесь.
NOTIFY_VOL = os.path.join(STATE, "ui-sound-notify-volume")
PACK = os.path.join(STATE, "ui-sound-pack")
CATS = os.path.join(STATE, "ui-sound-cats.json")
OWN = os.path.expanduser("~/.config/hypr/sounds")
RETRO = os.path.join(OWN, "retro")
XP_DIR = os.path.join(OWN, "xp")
REC_PID = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-rec", "pid")
VOLUME_DEFAULT = 75
PACKS = ("xp", "retro", "classic")
GAMES = (b"cs2", b"gamescope")
EXTS = (".wav", ".oga", ".ogg", ".flac")
FD = "/usr/share/sounds/freedesktop/stereo/"
OC = "/usr/share/sounds/ocean/stereo/"
OX = "/usr/share/sounds/"                    # Oxygen (KDE): звуки окон

# событие → (группа, файлы Windows XP по порядку предпочтения, файл «обычного» набора)
EVENTS = {
    "login": ("system", ("Windows XP Startup.wav",), OC + "desktop-login.oga"),
    "logout": ("system", ("Windows XP Logoff Sound.wav",), OC + "desktop-logout.oga"),
    "shutdown": ("system", ("Windows XP Shutdown.wav",), OC + "service-logout.oga"),
    "unlock": ("system", ("Windows XP Logon Sound.wav",), FD + "service-login.oga"),
    "screenshot": ("capture", ("Windows XP Balloon.wav",), FD + "screen-capture.oga"),
    "done": ("capture", ("Windows XP Ding.wav", "ding.wav"), OC + "completion-success.oga"),
    "error": ("capture", ("Windows XP Critical Stop.wav", "chord.wav"), OC + "completion-fail.oga"),
    "usb-in": ("devices", ("Windows XP Hardware Insert.wav",), FD + "device-added.oga"),
    "usb-out": ("devices", ("Windows XP Hardware Remove.wav",), FD + "device-removed.oga"),
    "battery-low": ("devices", ("Windows XP Battery Low.wav",), OC + "battery-low.oga"),
    "battery-critical": ("devices", ("Windows XP Battery Critical.wav",), OC + "battery-caution.oga"),
    "menu": ("menu", ("Windows XP Start.wav", "start.wav"), OC + "button-pressed-modifier.oga"),
    "click": ("menu", ("Windows XP Menu Command.wav",), OC + "button-pressed.oga"),
    "timer": ("timer", ("tada.wav", "Windows XP Ringin.wav"), FD + "alarm-clock-elapsed.oga"),
    # 05.10.2026, просьба: в XP — родной Notify, Balloon — в «Обычном» (единственный звук
    # XP в этом наборе — так попросил); наборы на уведомлениях звучат по-разному
    "notify": ("notify", ("Windows XP Notify.wav",),
               os.path.join(XP_DIR, "Windows XP Balloon.wav")),
    "window-open": ("windows", ("Windows XP Restore.wav",), OX + "Oxygen-Window-Maximize.ogg"),
    "window-close": ("windows", ("Windows XP Minimize.wav",), OX + "Oxygen-Window-Minimize.ogg"),
    "nav": ("mouse", ("Windows Navigation Start.wav",), OC + "audio-volume-change.oga"),
}
# группа → (подпись для Настроек, включена ли по умолчанию)
GROUPS = {
    "system": ("Вход, выход, разблокировка", True),
    "capture": ("Снимки и запись экрана", True),
    "devices": ("Флешки и батарея", True),
    "menu": ("«Пуск», меню и панель", True),
    "timer": ("Таймер", True),
    "notify": ("Уведомления", False),
    "windows": ("Открытие и закрытие окон", False),
    "mouse": ("Каждый щелчок мыши", False),
}
ALWAYS = {"timer"}            # звонит и в «Не беспокоить»


def _read(path, default=""):
    try:
        return open(path).read().strip()
    except OSError:
        return default


def _write(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write("%s\n" % value)
    os.replace(path + ".tmp", path)


def get_volume():
    try:
        return max(0, min(100, int(_read(VOL, VOLUME_DEFAULT))))
    except ValueError:
        return VOLUME_DEFAULT


def get_notify_volume():
    try:
        return max(0, min(100, int(_read(NOTIFY_VOL, 100))))
    except ValueError:
        return 100


def get_pack():
    v = _read(PACK, "xp")
    return v if v in PACKS else "xp"


def get_cats():
    cats = {k: d for k, (_t, d) in GROUPS.items()}
    try:
        cats.update({k: bool(v) for k, v in json.load(open(CATS)).items() if k in GROUPS})
    except (OSError, ValueError):
        pass
    return cats


def cat_on(group):
    return get_cats().get(group, False)


def sound_file(event):
    for ext in EXTS:
        p = os.path.join(OWN, event + ext)
        if os.path.exists(p):
            return p
    if event not in EVENTS:
        return ""
    _g, xp, classic = EVENTS[event]
    pack = get_pack()
    if pack == "xp":
        try:
            have = {n.lower(): n for n in os.listdir(XP_DIR)}
        except OSError:
            have = {}
        for name in xp:
            if name.lower() in have:
                return os.path.join(XP_DIR, have[name.lower()])
        return ""
    if pack == "classic":
        return classic if classic and os.path.exists(classic) else ""
    # Каждый набор — только свои звуки (05.10.2026, просьба: «Обычный повторяет Ретро,
    # сделай понятное разделение»): раньше чего не было в XP/«Обычном», бралось из ретро.
    p = os.path.join(RETRO, event + ".wav")
    if not os.path.exists(p):
        subprocess.run([sys.executable, os.path.join(HERE, "ui_sound_retro.py")], capture_output=True)
    return p if os.path.exists(p) else ""


_cache = {}


def _cached(key, fn, ttl=3.0):
    """Для долгоживущих программ: не спрашивать про DND и игру на каждый щелчок."""
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    v = fn()
    _cache[key] = (now, v)
    return v


def gaming():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


def dnd():
    try:
        return subprocess.run(["swaync-client", "-D"], capture_output=True, text=True,
                              timeout=2).stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        return False


def play(event, force=False, wait=False):
    f = sound_file(event)
    vol = get_volume()
    if event == "notify":
        # Своя громкость, НЕ доля от общей (05.10.2026): доля перемножалась до кубической
        # шкалы — при звуках интерфейса 33% и уведомлениях 80% выходило 1,8%, тишина.
        vol = get_notify_volume()
    if not f or vol == 0 or os.path.exists(REC_PID) or _cached("game", gaming):
        return False
    if not force:
        group = EVENTS.get(event, ("",))[0]
        if os.path.exists(OFF) or not _cached("cats", get_cats, 2.0).get(group, True):
            return False
        if group not in ALWAYS and _cached("dnd", dnd):
            return False
    # Своё имя потока: в микшере вместо непонятного «pw-play» — «Звуки интерфейса»
    # (04.10.2026, просьба: «а что за pw-play?»). media.role=Notification — системные звуки.
    # Без media.role и с state.restore-props = false (05.10.2026, просьба: «стало тише,
    # хотя на 100%; и звуки интерфейса тоже»). С ролью Notification WirePlumber ставил
    # каждому потоку громкость каналов, запомненную для этой роли, — 0,0106, и любой
    # звук играл на ~1% поверх --volume; флаг restore-props при роли не помогал
    # (проверено пробами pw-play: без роли 1.0, с ролью 0.0106). Роль была только для
    # вида в микшере; имя «Звуки интерфейса» остаётся.
    props = ('{ application.name = "Звуки интерфейса" node.description = "Звуки интерфейса" '
             'media.name = "Звуки интерфейса" '
             'application.icon-name = "preferences-desktop-sound" state.restore-props = false }')
    # timeout: если выход звука в ошибке, pw-play висит вечно и копится в микшере
    # (04.10.2026 набралось 14 штук «pw-play»)
    p = subprocess.Popen(["timeout", "8", "pw-play", "-P", props, "--volume", "%.4f" % ((vol / 100) ** 3), f],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    if wait:
        p.wait()
    return True


def main():
    a = sys.argv[1:]
    if a[:1] == ["play"] and len(a) > 1:
        play(a[1], wait="--wait" in a)
    elif a[:1] == ["test"]:
        play(a[1] if len(a) > 1 else "done", force=True)
    elif a[:1] == ["demo"]:
        for ev in EVENTS:
            print(ev, flush=True)
            play(ev, force=True, wait=True)
            time.sleep(0.4)
    elif a[:1] in (["on"], ["off"], ["status"]):
        if a[0] == "on":
            try:
                os.remove(OFF)
            except OSError:
                pass
        elif a[0] == "off":
            os.makedirs(STATE, exist_ok=True)
            open(OFF, "w").close()
        print("off" if os.path.exists(OFF) else "on")
    elif a[:1] == ["volume"]:
        if len(a) > 1:
            try:
                _write(VOL, max(0, min(100, int(float(a[1])))))
            except ValueError:
                pass
        print(get_volume())
    elif a[:1] == ["notify-volume"]:
        if len(a) > 1:
            try:
                _write(NOTIFY_VOL, max(0, min(100, int(float(a[1])))))
            except ValueError:
                pass
        print(get_notify_volume())
    elif a[:1] == ["pack"]:
        if len(a) > 1 and a[1] in PACKS:
            _write(PACK, a[1])
        print(get_pack())
    elif a[:1] == ["cat"]:
        cats = get_cats()
        if len(a) == 1:
            for k, (title, _d) in GROUPS.items():
                print("%s\t%s\t%s" % (k, title, "on" if cats[k] else "off"))
        elif a[1] in GROUPS:
            if len(a) > 2 and a[2] in ("on", "off"):
                cats[a[1]] = a[2] == "on"
                os.makedirs(STATE, exist_ok=True)
                with open(CATS + ".tmp", "w") as f:
                    json.dump(cats, f)
                os.replace(CATS + ".tmp", CATS)
            print("on" if cats[a[1]] else "off")
    elif a[:1] == ["list"]:
        print("набор: %s, громкость: %d, всё: %s" % (get_pack(), get_volume(),
                                                     "off" if os.path.exists(OFF) else "on"))
        cats = get_cats()
        for ev, (g, _x, _c) in EVENTS.items():
            print("%-17s %-8s %-3s %s" % (ev, g, "on" if cats[g] else "off",
                                          sound_file(ev).replace(os.path.expanduser("~"), "~") or "— файла нет"))
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
