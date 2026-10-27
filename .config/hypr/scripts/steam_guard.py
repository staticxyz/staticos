#!/usr/bin/env python3
"""Steam: правильное выключение и самолечение зависшего клиента.

27.10.2026, Просьба: «у меня не запускается steam… я его ранее закрывал через команду
kill steam, чтобы на фоне он не кушал оперативную память». Причина: `kill steam` (util-linux
kill по имени) шлёт SIGTERM всем процессам «steam»; клиент начал выход (в console-linux.txt
«Shutdown» в 18:45:50) и завис в нём — главный процесс жил ещё 2 часа без steamwebhelper.
Новый запуск (steam.sh) видит живой ~/.steam/steam.pid и только передаёт команду в
~/.steam/steam.pipe зависшему клиенту — окно не появляется.

    steam_guard.py off     выключить как надо: steam -shutdown, после «Shutdown» в журнале — KILL (~4 с)
    steam_guard.py heal    клиент завис — добить (зовёт обёртка ~/.local/bin/steam перед запуском)
    steam_guard.py check   для самопроверки: 0 — порядок, 1 — клиент завис
    steam_guard.py status  что сейчас с клиентом

Завис = главный процесс жив, а steamwebhelper нет, и при этом либо после его старта в журнале
уже был «Shutdown» (выход начат и не закончен) больше 20 с назад, либо он живёт больше 5 мин,
а журнал молчит больше 2 мин (на случай, если «Shutdown» не записался).
"""
import os
import re
import signal
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
STEAM_DIR = os.path.join(HOME, ".local/share/Steam")
PIDFILE = os.path.join(HOME, ".steam/steam.pid")
CONSOLE = os.path.join(STEAM_DIR, "logs/console-linux.txt")
STEAM_BIN = "/usr/bin/steam"
SHUTDOWN_GRACE = 20        # с: столько после «Shutdown» клиент имеет право выходить
QUIET_AGE = 300            # с: без webhelper и без журнала дольше — завис
QUIET_LOG = 120
HZ = os.sysconf("SC_CLK_TCK")


def boot_time():
    for line in open("/proc/stat"):
        if line.startswith("btime "):
            return int(line.split()[1])
    return 0


def started(pid):
    """Время старта процесса (unix), None — процесса нет."""
    try:
        st = open("/proc/%d/stat" % pid).read()
    except OSError:
        return None
    return boot_time() + int(st[st.rindex(")") + 2:].split()[19]) / HZ


def comm(pid):
    try:
        return open("/proc/%d/comm" % pid).read().strip()
    except OSError:
        return ""


def cmdline(pid):
    try:
        return open("/proc/%d/cmdline" % pid, "rb").read().split(b"\0")
    except OSError:
        return []


def mine():
    uid = os.getuid()
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if os.stat("/proc/" + p).st_uid == uid:
                    yield int(p)
            except OSError:
                pass


def client_pid():
    """Главный процесс клиента: из steam.pid, если он жив и это steam."""
    try:
        pid = int(open(PIDFILE).read().strip())
    except (OSError, ValueError):
        return None
    if comm(pid) == "steam" and started(pid):
        return pid
    return None


def webhelpers():
    return [p for p in mine() if comm(p) == "steamwebhelper"]


def last_shutdown():
    """Время последнего «Shutdown» в журнале клиента (unix) или None."""
    try:
        with open(CONSOLE, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            tail = f.read().decode("utf-8", "ignore").splitlines()
    except OSError:
        return None
    for line in reversed(tail):
        m = re.search(r"\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] Shutdown\s*$", line)  # в console-linux.txt штамп двойной
        if m:
            return time.mktime(time.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"))
    return None


def hung():
    """(завис?, пояснение)."""
    pid = client_pid()
    if not pid:
        return False, "клиент не запущен"
    if webhelpers():
        return False, "клиент работает (pid %d)" % pid
    now = time.time()
    t0 = started(pid) or now
    sd = last_shutdown()
    if sd and sd >= t0 - 1 and now - sd > SHUTDOWN_GRACE:
        return True, "выход начат в %s и не закончен (pid %d)" % (time.strftime("%H:%M:%S", time.localtime(sd)), pid)
    try:
        log_age = now - os.path.getmtime(CONSOLE)
    except OSError:
        log_age = now - t0
    if now - t0 > QUIET_AGE and log_age > QUIET_LOG:
        return True, "нет окна и webhelper %d мин, журнал молчит (pid %d)" % ((now - t0) // 60, pid)
    return False, "клиент запускается (pid %d)" % pid


def steam_procs():
    """Процессы клиента: всё, что запущено из ~/.local/share/Steam или /usr/lib/steam,
    кроме игры (дерево reaper SteamLaunch — её mem-guard/сама игра закрывают отдельно)."""
    out = []
    for p in mine():
        if p == os.getpid():
            continue
        a = cmdline(p)
        head = b" ".join(a[:2]).decode("utf-8", "ignore")
        if b"SteamLaunch" in a or "/steamapps/" in head:
            continue
        if STEAM_DIR in head or "/usr/lib/steam/" in head or comm(p) in ("steam", "steamwebhelper"):
            out.append(p)
    return out


def kill_all(sig=signal.SIGKILL):
    n = 0
    for p in steam_procs():
        try:
            os.kill(p, sig)
            n += 1
        except OSError:
            pass
    return n


def notify(body):
    subprocess.run(["notify-send", "-a", "Steam", "Steam", body], capture_output=True)


def heal(quiet=False):
    bad, why = hung()
    if not bad:
        if not quiet:
            print(why)
        return 0
    n = kill_all()
    for _ in range(30):
        if not client_pid():
            break
        time.sleep(0.1)
    msg = "Зависший Steam снят: %s; процессов %d" % (why, n)
    print(msg)
    notify(msg)
    return 0


def off():
    pid = client_pid()
    if not pid:
        left = kill_all()
        print("Steam не запущен" + (" (добил остатков: %d)" % left if left else ""))
        return 0
    # Правильный выход: клиент сам закрывает webhelper, оверлей, игры и пишет настройки.
    # 27.10: на этой машине он делает всё нужное за ~3 с (LogOff, Flushed store, webhelper,
    # «Shutdown» в журнале) и после «Shutdown» виснет — ждать дальше бессмысленно, добиваем.
    t0 = time.time()
    subprocess.Popen([STEAM_BIN, "-shutdown"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    done_at = None
    while started(pid) and time.time() - t0 < 25:
        if done_at is None:
            sd = last_shutdown()
            if sd and sd >= int(t0) - 1 and not webhelpers():
                done_at = time.time()
        elif time.time() - done_at > 1:
            break
        time.sleep(0.2)
    time.sleep(0.3 if not started(pid) else 0)
    n = kill_all()
    took = time.time() - t0
    if done_at is None and n:
        print("Steam не вышел за %d с — добит (процессов %d)" % (took, n))
    else:
        print("Steam выключен за %.0f с" % max(1, took))
    return 0


def check():
    bad, why = hung()
    print(("steam: ЗАВИС — " if bad else "steam: ок — ") + why)
    return 1 if bad else 0


def main(a):
    cmd = a[0] if a else "status"
    if cmd == "off":
        return off()
    if cmd == "heal":
        return heal(quiet="-q" in a)
    if cmd == "check":
        return check()
    if cmd == "status":
        print(hung()[1])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
