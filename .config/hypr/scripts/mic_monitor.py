#!/usr/bin/env python3
"""Микрофон: «послушать себя», чувствительность, выкл/вкл. 04.10.2026.

    mic_monitor.py status            on | off — идёт ли «послушать себя»
    mic_monitor.py on|off|toggle     включить / выключить петлю микрофон → наушники
    mic_monitor.py volume [0..150]   чувствительность микрофона, %
    mic_monitor.py mute [on|off|toggle|get]

Просьба: «мне понравилась фича, где можно зайти, нажать кнопку и услышать себя — понять, как
меня слышно; и главное, чтобы сверху была иконка, что микрофон используется». Петля —
pw-loopback от источника по умолчанию к выходу по умолчанию; значок «микрофон занят» в баре
даёт privacy_status.py сам — он видит запись с микрофона. Петля живёт отдельным процессом
(pid в $XDG_RUNTIME_DIR), Настройки можно закрыть. Чтобы не забыть её включённой, она сама
выключается через LIMIT секунд.
"""
import os
import signal
import subprocess
import sys
import time

RUN = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
PID = os.path.join(RUN, "jarvis-mic-monitor.pid")
LIMIT = 300                 # петля сама гаснет через 5 минут
SRC = "@DEFAULT_AUDIO_SOURCE@"


def pid():
    try:
        p = int(open(PID).read().strip())
        if b"pw-loopback" in open("/proc/%d/cmdline" % p, "rb").read():
            return p
    except (OSError, ValueError):
        pass
    return None


def bt_card_a2dp():
    """(карта, профиль), если микрофон по умолчанию — Bluetooth-гарнитура в режиме музыки.

    У AirPods и других гарнитур микрофон работает только в режиме «гарнитура» (HFP);
    в режиме музыки (A2DP) источник есть, но молчит — «Послушать себя» ничего не давал
    (04.10.2026). Тогда на время петли гарнитура переводится в HFP и потом обратно."""
    try:
        src = subprocess.run(["pactl", "get-default-source"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return None
    if not src.startswith("bluez_input."):
        return None
    mac = src.split(".", 1)[1].split(":capture")[0].replace(":", "_")
    card = "bluez_card." + mac
    out = subprocess.run(["pactl", "list", "cards"], capture_output=True, text=True).stdout
    for blk in out.split("Card #"):
        if "Name: %s" % card in blk:
            for line in blk.splitlines():
                if line.strip().startswith("Active Profile:"):
                    prof = line.split(":", 1)[1].strip()
                    return (card, prof) if prof.startswith("a2dp") else None
    return None


def start():
    if pid():
        return
    restore = ""
    bt = bt_card_a2dp()
    if bt:
        card, prof = bt
        subprocess.run(["pactl", "set-card-profile", card, "headset-head-unit"], capture_output=True)
        time.sleep(1.0)                               # дать гарнитуре переключиться
        # Назад — через «off»: прямой переход headset-head-unit → a2dp оставлял выход
        # AirPods в ошибке «Start error: Input/output error», звук пропадал (04.10.2026).
        restore = "; pactl set-card-profile %s off; sleep 1; pactl set-card-profile %s %s" % (card, card, prof)
    # setsid + timeout: петля не зависит от Настроек и не живёт вечно; после неё —
    # вернуть гарнитуре режим музыки (если переключали)
    loop = ("timeout %d pw-loopback --latency 40ms -n jarvis-mic-monitor "
            "--capture-props '{ node.description = \"Послушать себя (микрофон)\" }' "
            "--playback-props '{ node.description = \"Послушать себя\" }'" % LIMIT)
    p = subprocess.Popen(["sh", "-c", loop + restore],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(40):                               # pid самого pw-loopback (sh → timeout → он)
        time.sleep(0.05)
        for line in subprocess.run(["pgrep", "-a", "-x", "pw-loopback"], capture_output=True,
                                   text=True).stdout.splitlines():
            if "jarvis-mic-monitor" in line:
                with open(PID, "w") as f:
                    f.write(line.split()[0])
                return


def stop():
    p = pid()
    if p:
        try:
            os.kill(p, signal.SIGTERM)
        except OSError:
            pass
    try:
        os.remove(PID)
    except OSError:
        pass


def wp(*args):
    return subprocess.run(["wpctl", *args], capture_output=True, text=True).stdout


def main():
    a = sys.argv[1:] or ["status"]
    if a[0] == "status":
        print("on" if pid() else "off")
    elif a[0] in ("on", "off", "toggle"):
        want = (not pid()) if a[0] == "toggle" else a[0] == "on"
        start() if want else stop()
        print("on" if pid() else "off")
    elif a[0] == "volume":
        if len(a) > 1:
            v = max(0, min(150, int(float(a[1]))))
            wp("set-volume", SRC, "%d%%" % v)
        out = wp("get-volume", SRC)
        try:
            print(int(round(float(out.split("Volume:")[1].split()[0]) * 100)))
        except (IndexError, ValueError):
            print(100)
    elif a[0] == "mute":
        arg = a[1] if len(a) > 1 else "get"
        if arg in ("on", "off", "toggle"):
            wp("set-mute", SRC, {"on": "1", "off": "0", "toggle": "toggle"}[arg])
        print("on" if "MUTED" in wp("get-volume", SRC) else "off")
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
