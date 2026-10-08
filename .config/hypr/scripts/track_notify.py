#!/usr/bin/env python3
"""Уведомление при смене трека — по образцу Noctalia (media OSD). 30.09.2026.

    track_notify.py                фоновый сторож (автозапуск niri)
    track_notify.py on|off|status  включить/выключить (Настройки → Уведомления)

Слушает `playerctl -a -F metadata` и, когда у ИГРАЮЩЕГО плеера сменилось
название, показывает уведомление swaync: обложка, название, исполнитель.
Название и исполнитель чистятся от «(Official Video)» и прочего тем же
mpris_common.clean_title, что и бар. Не показывает:
  * на паузе и при перемотке (название то же);
  * повтор того же трека в течение DEDUP_S;
  * пока выключено (флаг ~/.config/hypr/state/track-notify-off) — сторож
    при этом живёт, просто молчит: включение действует сразу.
  * видео в браузере (03.10.2026, Просьба: «пусть определяет, когда открываю видос в
    ютубе в браузере, и не показывает их, а только треки»). Песня или видео — как у
    текстов песен (lyrics_bar.py): решает личность плеера (MPRIS Identity), у браузера
    объявляются только вкладки музыкальных сервисов по xesam:url (music.youtube.com,
    music.yandex…). Яндекс Музыка на шине — тоже «chromium.instanceNNN», но Identity
    у неё «YandexMusic», поэтому смотрим именно Identity, а не имя на шине.
Уведомления заменяют друг друга (x-canonical-private-synchronous), а не копятся.
"""
import hashlib
import os
import subprocess
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpris_common  # noqa: E402

OFF = os.path.expanduser("~/.config/hypr/state/track-notify-off")
COVERS = os.path.expanduser("~/.cache/player-covers")
SEP = "\x1f"
FMT = SEP.join(("{{playerInstance}}", "{{status}}", "{{title}}", "{{artist}}", "{{mpris:artUrl}}",
                "{{xesam:url}}"))
# те же списки, что в lyrics_bar.py
BROWSERS = {"firefox", "zen", "librewolf", "chromium", "chrome", "helium", "brave",
            "thorium", "vivaldi", "opera", "edge", "floorp", "waterfox", "epiphany",
            "falkon", "qutebrowser", "mercury", "midori", "browser", "mozilla"}
MUSIC_HOSTS = ("music.youtube.com", "open.spotify.com", "music.yandex.", "soundcloud.com",
               "deezer.com", "music.apple.com", "tidal.com", "bandcamp.com")
_IDENTITY = {}
DEDUP_S = 30
SETTLE_S = 0.9         # сколько ждать, пока плеер досообщит исполнителя и обложку

if sys.argv[1:2] in (["on"], ["off"], ["status"]):
    cmd = sys.argv[1]
    if cmd == "on":
        try:
            os.remove(OFF)
        except OSError:
            pass
    elif cmd == "off":
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
    print("off" if os.path.exists(OFF) else "on")
    sys.exit(0)


def _die_with_parent():
    # playerctl умирает вместе со сторожем (иначе после перезапуска остаётся сиротой)
    import ctypes
    import signal
    ctypes.CDLL("libc.so.6", use_errno=True).prctl(1, signal.SIGTERM)


def cover(url):
    try:
        if url.startswith("file://"):
            return url[7:]
        if url.startswith("http"):
            os.makedirs(COVERS, exist_ok=True)
            path = os.path.join(COVERS, hashlib.sha1(url.encode()).hexdigest())
            if not os.path.exists(path):
                urllib.request.urlretrieve(url, path)
            return path
    except Exception:
        pass
    return ""


def identity(inst):
    """MPRIS Identity плеера («Mozilla Firefox», «YandexMusic»); запоминается."""
    if inst not in _IDENTITY:
        try:
            out = subprocess.run(["busctl", "--user", "get-property", "org.mpris.MediaPlayer2." + inst,
                                  "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2", "Identity"],
                                 capture_output=True, text=True, timeout=2).stdout
            _IDENTITY[inst] = out.strip()[2:].strip().strip('"') if out.startswith("s ") else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return _IDENTITY[inst]


def is_track(inst, url):
    """Трек, а не видео: у браузера — только вкладка музыкального сервиса."""
    import re
    import urllib.parse
    name = identity(inst) or inst
    if not set(re.split(r"[^a-z0-9]+", name.lower())) & BROWSERS:
        return True
    host = urllib.parse.urlsplit(url or "").netloc.lower()
    return bool(host) and any(host == h or host.endswith("." + h) or host.startswith(h)
                              for h in MUSIC_HOSTS)


def notify(title, artist, art):
    args = ["notify-send", "-a", "Music", "-u", "low",
            "-h", "string:x-canonical-private-synchronous:jarvis-track"]
    icon = cover(art) if art else ""
    if icon:
        args += ["-i", icon]
    args += [title, artist or ""]
    subprocess.run(args, capture_output=True)


def main():
    # Единственный сторож: второй экземпляр выходит.
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"track_notify.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                return
    last = {}          # плеер → (название, время)
    shown = ["", 0.0]
    latest = {}        # плеер → последние (status, title, artist, art)
    timers = {}
    lock = threading.Lock()

    def fire(inst):
        """Через SETTLE_S после последнего изменения: данные устоялись — показать."""
        with lock:
            timers.pop(inst, None)
            cur = latest.get(inst)
            if not cur:
                return
            status, title, artist, art, url = cur
            if status != "Playing" or os.path.exists(OFF):
                return
        if not is_track(inst, url):
            return
        with lock:
            key = title + "\x00" + artist
            if shown[0] == key and time.time() - shown[1] < DEDUP_S:
                return
            shown[0], shown[1] = key, time.time()
        notify(title, artist, art)

    while True:
        proc = subprocess.Popen(["playerctl", "-a", "-F", "metadata", "--format", FMT],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                                preexec_fn=_die_with_parent)
        started = time.time()   # первые секунды playerctl пересказывает то, что уже играет
        for line in proc.stdout:
            parts = line.rstrip("\n").split(SEP)
            if len(parts) != 6:
                continue
            inst, status, title, artist, art, url = parts
            if any(i in inst.lower() for i in mpris_common.IGNORED):
                continue
            # Telegram отдаёт в MPRIS голосовые и кружки («today at 4:32 PM» / «You») — это
            # не музыка, уведомлять не нужно (07.10.2026, пользователь)
            if "telegram" in inst.lower() or "telegram" in identity(inst).lower():
                continue
            title = mpris_common.clean_title(title)
            artist = mpris_common.clean_artist(artist)
            if not title:
                continue
            prev = last.get(inst)
            last[inst] = (title, time.time())
            with lock:
                latest[inst] = (status, title, artist, art, url)
            if prev and prev[0] == title:
                continue                 # то же название: пауза, перемотка, догрузилась обложка
            if prev is None and time.time() - started < 2:
                continue                 # не объявлять трек, игравший до запуска сторожа
            # Плеер сообщает о новом треке по частям: сначала название, потом
            # исполнитель и обложка. Раньше уведомление уходило по первому сигналу —
            # выходило новое название со старым исполнителем/обложкой («путается»,
            # 02.10.2026). Теперь ждём SETTLE_S тишины и берём последние данные.
            with lock:
                t = timers.pop(inst, None)
                if t:
                    t.cancel()
                t = threading.Timer(SETTLE_S, fire, args=(inst,))
                t.daemon = True
                timers[inst] = t
                t.start()
        proc.wait()
        time.sleep(3)                    # playerctl упал (нет D-Bus?) — пробуем снова


if __name__ == "__main__":
    main()
