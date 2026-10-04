#!/usr/bin/env python3
"""Сторож звуков интерфейса: события, у которых нет своего «хозяина». 02.10.2026.

    ui_sound_watch.py        сторож (автозапуск niri; второй экземпляр выходит)
    ui_sound_watch.py now    что он сейчас слушает (для проверки)

Сам ничего не решает про громкость и «можно ли» — всё через ui_sound.play():
там группы (Настройки → Misc), «Не беспокоить», запись экрана и игра.

Что слушает:
    usb-in / usb-out          `udevadm monitor` — подключили или вынули USB-устройство
    battery-low / -critical   раз в минуту заряд BAT*: ≤ 20 % и ≤ 8 % на разряде, по разу
    window-open / -close      поток событий niri (группа «окна», по умолчанию выключена)
    nav                       левая кнопка мыши, /dev/input (группа «мышь», выключена)
    notify                    пришло уведомление, dbus-monitor (группа «уведомления», выключена)
Выключенную группу сторож не слушает вовсе: мышь и dbus-monitor открываются,
только когда их группа включена (проверка раз в 3 с). Все дочерние процессы — с
PDEATHSIG. Процессор: спит в select; в покое ноль.
"""
import ctypes
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ui_sound  # noqa: E402

_libc = ctypes.CDLL(None, use_errno=True)
FMT = "llHHi"
SIZE = struct.calcsize(FMT)
EV_KEY, BTN_LEFT = 1, 0x110
BOOT_QUIET_S = 6                 # при входе окна открываются пачкой — молчим


def _pdeathsig():
    _libc.prctl(1, signal.SIGTERM, 0, 0, 0)      # PR_SET_PDEATHSIG


def enabled(group):
    return not os.path.exists(ui_sound.OFF) and ui_sound.cat_on(group)


def spawn(argv):
    return subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            preexec_fn=_pdeathsig)


# ── USB ─────────────────────────────────────────────────────────────────────
def watch_usb():
    last = {"add": 0.0, "remove": 0.0}
    while True:
        try:
            p = spawn(["udevadm", "monitor", "--udev", "--subsystem-match=usb/usb_device"])
            for line in p.stdout:
                m = re.match(rb"^UDEV\s+\[[\d.]+\]\s+(add|remove)\s", line)
                if not m:
                    continue
                kind = m.group(1).decode()
                now = time.monotonic()
                if now - last[kind] > 1.5:        # хаб с устройством даёт несколько событий
                    last[kind] = now
                    ui_sound.play("usb-in" if kind == "add" else "usb-out")
            p.wait()
        except OSError:
            pass
        time.sleep(5)


# ── батарея ─────────────────────────────────────────────────────────────────
def battery():
    base = "/sys/class/power_supply"
    try:
        for n in sorted(os.listdir(base)):
            if n.startswith("BAT"):
                cap = int(open("%s/%s/capacity" % (base, n)).read())
                st = open("%s/%s/status" % (base, n)).read().strip()
                return cap, st
    except (OSError, ValueError):
        pass
    return None


def watch_battery():
    said = set()
    while True:
        b = battery()
        if b:
            cap, st = b
            if st != "Discharging" or cap > 25:
                said.clear()
            elif cap <= 8 and "critical" not in said:
                said.update(("low", "critical"))
                ui_sound.play("battery-critical")
            elif cap <= 20 and "low" not in said:
                said.add("low")
                ui_sound.play("battery-low")
        time.sleep(60)


# ── зарядка (03.10.2026) ────────────────────────────────────────────────────
# Просьба: «добавь уведомления, когда втыкаю зарядку и когда отключаю». udev сообщает о
# смене power_supply; состояние читаем из AC*/ADP*/online и шлём уведомление только при
# настоящей смене (udev даёт пачку событий, батарея меняется каждые полминуты).
def ac_online():
    base = "/sys/class/power_supply"
    try:
        for n in sorted(os.listdir(base)):
            try:
                if open("%s/%s/type" % (base, n)).read().strip() == "Mains":
                    return open("%s/%s/online" % (base, n)).read().strip() == "1"
            except OSError:
                continue
    except OSError:
        pass
    return None


def watch_ac():
    was = ac_online()
    while True:
        try:
            p = spawn(["udevadm", "monitor", "--udev", "--subsystem-match=power_supply"])
            for line in p.stdout:
                if b"change" not in line:
                    continue
                time.sleep(0.3)
                now = ac_online()
                if now is None or now == was:
                    continue
                was = now
                b = battery()
                cap = (" · заряд %d %%" % b[0]) if b else ""
                subprocess.run(["notify-send", "-a", "System", "-u", "low",
                                "-i", "battery-good-charging" if now else "battery-good",
                                "-h", "string:x-canonical-private-synchronous:jarvis-ac",
                                "Зарядка подключена" if now else "Зарядка отключена",
                                ("Питание от сети" if now else "Работа от батареи") + cap],
                               capture_output=True)
            p.wait()
        except OSError:
            pass
        time.sleep(5)


# ── окна ────────────────────────────────────────────────────────────────────
def watch_windows():
    started = time.monotonic()
    while True:
        known, primed = set(), False
        try:
            p = spawn(["niri", "msg", "-j", "event-stream"])
            for line in p.stdout:
                if line.startswith(b'{"WindowsChanged"'):
                    known = {w["id"] for w in json.loads(line)["WindowsChanged"]["windows"]}
                    primed = True
                elif line.startswith(b'{"WindowOpenedOrChanged"'):
                    wid = json.loads(line)["WindowOpenedOrChanged"]["window"]["id"]
                    if wid not in known:
                        known.add(wid)
                        if primed and time.monotonic() - started > BOOT_QUIET_S:
                            ui_sound.play("window-open")
                elif line.startswith(b'{"WindowClosed"'):
                    wid = json.loads(line)["WindowClosed"]["id"]
                    if wid in known:
                        known.discard(wid)
                        ui_sound.play("window-close")
            p.wait()
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(3)


# ── мышь ────────────────────────────────────────────────────────────────────
def mice():
    out = []
    try:
        for b in open("/proc/bus/input/devices").read().split("\n\n"):
            h = next((l for l in b.splitlines() if l.startswith("H: Handlers=")), "")
            if "mouse" in h:
                out += ["/dev/input/" + e for e in re.findall(r"\bevent\d+", h)]
    except OSError:
        pass
    return out


def watch_mouse():
    fds, next_scan = {}, 0.0
    while True:
        now = time.monotonic()
        if now >= next_scan:
            next_scan = now + 3
            want = set(mice()) if enabled("mouse") else set()
            if want != set(fds.values()):
                for fd in fds:
                    try:
                        os.close(fd)
                    except OSError:
                        pass
                fds = {}
                for path in want:
                    try:
                        fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = path
                    except OSError:
                        pass
        if not fds:
            time.sleep(3)
            continue
        try:
            r, _, _ = select.select(list(fds), [], [], 3)
        except (OSError, ValueError):
            next_scan = 0
            continue
        click = False
        for fd in r:
            try:
                data = os.read(fd, SIZE * 128)
            except BlockingIOError:
                continue
            except OSError:
                next_scan = 0
                continue
            for i in range(0, len(data) - SIZE + 1, SIZE):
                _s, _us, typ, code, val = struct.unpack_from(FMT, data, i)
                if typ == EV_KEY and code == BTN_LEFT and val == 1:
                    click = True
        if click:
            ui_sound.play("nav")


# ── уведомления ─────────────────────────────────────────────────────────────
def watch_notify():
    last = 0.0
    while True:
        if not enabled("notify"):
            time.sleep(5)
            continue
        try:
            p = spawn(["dbus-monitor", "--session",
                       "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"])
            # Звук — по строке ПОСЛЕ member=Notify: первым аргументом идёт имя программы.
            # Уведомление niri о снимке — без своего звука (05.10.2026): у снимка
            # уже есть свой (auto_dnd.py → screenshot), два подряд лишние.
            want = False
            for line in p.stdout:
                if b"member=Notify" in line:
                    want = True
                    continue
                if want:
                    want = False
                    app = line.strip()
                    # Без системного звука: снимок niri (свой звук у снимка) и сообщения
                    # Telegram (05.10.2026, просьба: «системного звука в сообщениях Telegram
                    # быть не должно — пусть звучит сам Telegram»).
                    if app not in (b'string "niri"', b'string "Telegram Desktop"') \
                            and time.monotonic() - last > 1.0:
                        last = time.monotonic()
                        ui_sound.play("notify")
                if not enabled("notify"):
                    break
            p.terminate()
            p.wait()
        except OSError:
            pass
        time.sleep(3)


def main():
    if sys.argv[1:2] == ["now"]:
        print("звуки:", "off" if os.path.exists(ui_sound.OFF) else "on", "| набор:", ui_sound.get_pack())
        for k, (title, _d) in ui_sound.GROUPS.items():
            print("  %-8s %-3s %s" % (k, "on" if ui_sound.cat_on(k) else "off", title))
        print("батарея:", battery(), "| мышей:", len(mice()))
        return
    me = os.getpid()
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != me:
            try:
                argv = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if len(argv) >= 2 and os.path.basename(argv[1]) == b"ui_sound_watch.py" \
                    and (len(argv) == 2 or argv[2] == b""):
                return
    for fn in (watch_usb, watch_battery, watch_windows, watch_mouse, watch_ac):
        threading.Thread(target=fn, daemon=True).start()
    watch_notify()


if __name__ == "__main__":
    main()
