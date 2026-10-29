#!/usr/bin/env python3
"""Уведомления не всплывают на заставке и экране блокировки. 29.10.2026.

    notif_quiet.py          сторож (в хозяине staticOS)
    notif_quiet.py check    тихо ли сейчас и почему

Просьба: «приходят уведомления в режиме Заставки… в режиме блокировки тоже не должны быть
видны. Пусть приходят, но не показываются».

Пока показана заставка (screensaver.py держит flock на jarvis-screensaver.lock) или сеанс
заперт (jarvis_lock.py / hyprlock своего Wayland) — у swaync стоит inhibitor «jarvis-quiet»:
уведомление сразу ложится в центр без всплывашки. Это не DND: «Не беспокоить» самого
пользователя, pomo и очередь dnd_queue не трогаются. critical и SWAYNC_BYPASS_DND inhibitor
пробивают (swaync 0.12.6, notiDaemon.vala:224), их прячет `swaync-client --hide-all` по
событию подписки -s — в центре они остаются. Заставка ушла — inhibitor снят, уже пришедшие
не всплывают заново.
"""
import ctypes
import json
import os
import signal
import subprocess
import sys
import threading
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
SAVER_LOCK = os.path.join(RUN, "jarvis-screensaver.lock")
INHIBITOR = "jarvis-quiet"
POLL = 1.0
_libc = ctypes.CDLL(None, use_errno=True)
st = {"quiet": False}


def _pdeath():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)


def saver_shown():
    """Заставка на экране — её замок занят (как screensaver.shown_pid)."""
    import fcntl
    try:
        fd = os.open(SAVER_LOCK, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    except OSError:
        return True
    finally:
        os.close(fd)


def locked():
    """Сеанс заперт: hyprlock или jarvis_lock (имя потока jv:jarvis_lock) этого Wayland.
    Читается только /proc/*/comm — дёшево раз в секунду; environ — лишь у найденного,
    чтобы осиротевший hyprlock прошлого сеанса не глушил уведомления навсегда."""
    disp = ("WAYLAND_DISPLAY=" + os.environ.get("WAYLAND_DISPLAY", "wayland-1")).encode()
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            comm = open("/proc/%s/comm" % d, "rb").read().strip()
        except OSError:
            continue
        if comm not in (b"hyprlock", b"jv:jarvis_lock"):
            continue
        try:
            if disp in open("/proc/%s/environ" % d, "rb").read().split(b"\0"):
                return comm.decode()
        except OSError:
            continue
    return None


def why():
    if saver_shown():
        return "заставка"
    return locked()


def client(*args):
    try:
        subprocess.run(["swaync-client", "-sw", *args], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


def set_quiet(on):
    st["quiet"] = on
    if on:
        client("-Ia", INHIBITOR)
        client("--hide-all")          # то, что всплыло за секунду до заставки
    else:
        client("-Ir", INHIBITOR)


def watch_new():
    """Новое уведомление в тишине (critical / bypass пробили inhibitor) — спрятать."""
    while True:
        try:
            p = subprocess.Popen(["swaync-client", "-s"], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, preexec_fn=_pdeath)
            last = None
            for line in p.stdout:
                try:
                    n = int(json.loads(line).get("count") or 0)
                except (ValueError, AttributeError):
                    continue
                if st["quiet"] and last is not None and n > last:
                    client("--hide-all")
                last = n
        except OSError:
            pass
        time.sleep(3)


def main():
    if sys.argv[1:2] == ["check"]:
        w = why()
        print("тихо: %s" % w if w else "не тихо")
        return 0
    client("-Ir", INHIBITOR)            # хвост от прошлого запуска (упал в тишине)
    threading.Thread(target=watch_new, daemon=True).start()
    while True:
        q = bool(why())
        if q != st["quiet"]:
            set_quiet(q)
        time.sleep(POLL)


if __name__ == "__main__":
    sys.exit(main())
