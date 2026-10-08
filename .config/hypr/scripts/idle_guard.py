#!/usr/bin/env python3
"""Общая проверка для hypridle: держать ли экран зажжённым.

Экран не гаснет и не блокируется, только если выполнены ОБА условия:
включён Savage Mode и включён его спутник «не отключать экран». Одного флага
мало намеренно: так забытая галочка не оставит машину незапертой навсегда.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def keep_screen_on():
    try:
        return bool(_load("savage_battery").is_savage_active()) and bool(_load("screen_awake").get())
    except Exception as e:                      # сомневаешься — блокируй
        print("idle_guard: %s" % e, file=sys.stderr)
        return False


# ── Видео в фокусе (07.10.2026) ───────────────────────────────────────────────
# Просьба: «чтобы при просмотре видео экран не вырубался… именно когда я смотрю видео,
# и это видео в фокусе». Приглушение, блокировка и сон пропускаются, пока в окне в фокусе
# (браузер или видеоплеер) играет видео: плеер MPRIS этой программы в Playing, а для
# браузера ещё и его заголовок есть в заголовке окна — значит, играет вкладка, которая
# открыта, а не музыка в фоне. Музыка (Яндекс Музыка, Spotify) не держит экран.
#
# hypridle срабатывает один раз за простой: если пропустить блокировку, после конца
# видео она сама уже не наступит. Поэтому пропуск ставит флаг и сторожа (wait): тот
# раз в 15 с смотрит, идёт ли ещё видео; кончилось, а пользователь так и не вернулся (флаг
# не снят слушателем on-resume) — перезапускает hypridle, и отсчёт простоя идёт заново:
# через те же 5 минут экран погаснет и запрётся как обычно.
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

RUN = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
HELD = os.path.join(RUN, "jarvis-idle-held")
WAITER = os.path.join(RUN, "jarvis-idle-waiter.pid")
VIDEO_APPS = re.compile(r"zen|firefox|librewolf|helium|chrom|brave|thorium|mercury|mpv|vlc|celluloid|"
                        r"totem|haruna|showtime|clapper|youtube", re.I)
BROWSERS = ("zen", "firefox", "librewolf", "helium", "chrom", "brave", "thorium", "mercury")


def _out(*cmd):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=3).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def video_in_focus():
    """Название видео, если оно играет в окне в фокусе, иначе None."""
    try:
        w = json.loads(_out("niri", "msg", "-j", "focused-window") or "null")
    except ValueError:
        return None
    if not w:
        return None
    app, title = (w.get("app_id") or "").lower(), (w.get("title") or "")
    if not VIDEO_APPS.search(app):
        return None
    browser = any(b in app for b in BROWSERS)
    loose = None
    for line in _out("playerctl", "-a", "metadata", "--format",
                     "{{playerName}}\t{{status}}\t{{title}}\t{{xesam:url}}").splitlines():
        name, st, t, url = (line.split("\t") + ["", "", ""])[:4]
        if st != "Playing":
            continue
        low = name.lower()
        if browser:
            if not any(b in low for b in BROWSERS):
                continue
            if t and t.strip()[:40] in title:
                return t
            # Плеер во встроенном фрейме (wparty, Kodik и т. п.) называет видео по-своему,
            # и в заголовке окна этого названия нет (07.10.2026: экран тускнел на сериале).
            # Тогда видео засчитывается, если это не музыкальный сайт и название не стоит
            # в заголовке ДРУГОГО окна браузера — то есть играет не там.
            if not MUSIC_SITES.search(url) and not _in_other_window(t, w.get("id")):
                loose = t or url or name
        elif VIDEO_APPS.search(low) or low.split(".")[0] in app:
            return t or name
    if loose:
        _log("по адресу, без совпадения заголовка: %r в окне %r" % (loose, title))
    return loose


MUSIC_SITES = re.compile(r"music\.yandex|music\.youtube|soundcloud|spotify|deezer|bandcamp|"
                         r"vk\.com/(audio|music)|zvuk\.com|music\.apple|tidal\.com", re.I)


def _in_other_window(t, focused_id):
    if not t:
        return False
    try:
        wins = json.loads(_out("niri", "msg", "-j", "windows") or "[]")
    except ValueError:
        return False
    return any(x.get("id") != focused_id and t.strip()[:40] in (x.get("title") or "")
               and any(b in (x.get("app_id") or "").lower() for b in BROWSERS) for x in wins)


def _log(msg):
    """Короткий журнал решений — чтобы в следующий раз было видно, почему экран погас."""
    try:
        with open(os.path.join(RUN, "jarvis-idle.log"), "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


def hold(stage):
    """Пропуск ради видео: флаг + сторож, который вернёт отсчёт после конца видео."""
    with open(HELD, "w") as f:
        f.write("%s %d\n" % (stage, time.time()))
    _log("%s пропущено ради видео" % stage)
    try:
        pid = int(open(WAITER).read())
        os.kill(pid, 0)
        return                                   # сторож уже есть
    except (OSError, ValueError):
        pass
    subprocess.Popen([sys.executable, os.path.abspath(__file__), "wait"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)


def restart_hypridle():
    """Главный hypridle (без -c) — заново, по точному PID; таймеры простоя начнутся с нуля."""
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
        except OSError:
            continue
        if argv and os.path.basename(argv[0]) == b"hypridle" and b"-c" not in argv:
            try:
                os.kill(int(pid), 15)
            except OSError:
                pass
    time.sleep(1)
    subprocess.Popen(["hypridle"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)


def wait():
    with open(WAITER, "w") as f:
        f.write(str(os.getpid()))
    quiet = 0
    try:
        while os.path.exists(HELD):
            time.sleep(15)
            if not os.path.exists(HELD):
                break                            # Пользователь вернулся — on-resume снял флаг
            quiet = 0 if video_in_focus() else quiet + 1
            if quiet >= 2:                       # видео нет полминуты — отсчёт заново
                try:
                    os.remove(HELD)
                except OSError:
                    pass
                restart_hypridle()
                break
    finally:
        try:
            os.remove(WAITER)
        except OSError:
            pass


if __name__ == "__main__":
    cmd = (sys.argv[1:] or ["video"])[0]
    if cmd == "wait":
        wait()
    elif cmd == "resume":
        try:
            os.remove(HELD)
        except OSError:
            pass
    else:
        print(video_in_focus() or "нет видео в фокусе")
