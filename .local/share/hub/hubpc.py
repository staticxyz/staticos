#!/usr/bin/env python3
"""hub — управление ПК заранее прописанными действиями (белый список, без оболочки).

Уровни: 0 — сразу; 1 — после подтверждения кнопкой (60 с); 2 — то же, чувствительные.
Каждое действие возвращает (текст, png-путь | None)."""
import json
import os
import subprocess
import tempfile
import time

LEVEL = {"status": 0, "apps": 0, "shot": 0, "mute": 0, "unmute": 0, "vol": 0,
         "lock": 1, "dark": 1, "close": 1, "sleep": 2, "reboot": 2, "off": 2}
HELP = {"status": "состояние системы", "apps": "список окон", "shot": "скриншот",
        "mute": "выключить звук", "unmute": "включить звук", "vol N": "громкость 0–100",
        "lock": "заблокировать", "dark": "погасить мониторы (чёрный экран)",
        "close N": "закрыть окно по номеру из apps", "sleep": "сон",
        "reboot": "перезагрузка", "off": "выключение"}


def _run(cmd, t=10):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=t).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def windows():
    try:
        return json.loads(_run(["niri", "msg", "-j", "windows"]) or "[]")
    except ValueError:
        return []


def status():
    up = float(open("/proc/uptime").read().split()[0])
    mem = {l.split(":")[0]: int(l.split()[1]) for l in open("/proc/meminfo")}
    used = (mem["MemTotal"] - mem["MemAvailable"]) / 1048576
    load = os.getloadavg()[0]
    bat = ""
    for p in ("BAT0", "BAT1"):
        d = "/sys/class/power_supply/" + p
        if os.path.exists(d + "/capacity"):
            bat = "\nБатарея: %s%% (%s)" % (open(d + "/capacity").read().strip(),
                                           open(d + "/status").read().strip())
            break
    vol = _run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
    return ("Работает %dч %dмин\nПамять: %.1f из %.1f ГиБ\nЗагрузка: %.2f\nЗвук: %s%s\nОкон: %d"
            % (up // 3600, up % 3600 // 60, used, mem["MemTotal"] / 1048576, load, vol or "—", bat,
               len(windows())))


def apps():
    ws = windows()
    if not ws:
        return "Окон нет."
    return "\n".join("%d. %s — %s" % (i + 1, w.get("app_id") or "?", (w.get("title") or "")[:50])
                     for i, w in enumerate(ws[:40]))


def shot():
    p = os.path.join(tempfile.gettempdir(), "hub-shot-%d.png" % int(time.time()))
    subprocess.run(["grim", p], timeout=15)
    return ("Снимок экрана.", p) if os.path.exists(p) else ("Не удалось снять экран.", None)


def close(n):
    ws = windows()
    try:
        w = ws[int(n) - 1]
    except (ValueError, IndexError):
        return "Нет окна с таким номером. Сначала /pc apps."
    subprocess.run(["niri", "msg", "action", "close-window", "--id", str(w["id"])], timeout=5)
    return "Закрыто: %s" % (w.get("app_id") or w.get("title"))


def run(action, arg=""):
    a = action.lower()
    if a == "status":
        return status(), None
    if a == "apps":
        return apps(), None
    if a == "shot":
        return shot()
    if a in ("mute", "unmute"):
        _run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if a == "mute" else "0"])
        return ("Звук выключен." if a == "mute" else "Звук включён."), None
    if a == "vol":
        try:
            v = max(0, min(100, int(arg)))
        except ValueError:
            return "Нужно число 0–100.", None
        _run(["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "%d%%" % v])
        return "Громкость %d%%." % v, None
    if a == "lock":
        _run(["loginctl", "lock-session"])
        return "Заблокировано.", None
    if a == "dark":
        idle = os.path.expanduser("~/.config/hypr/scripts/idle_dim")
        subprocess.Popen([idle, "deep"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "Мониторы гаснут.", None
    if a == "close":
        return close(arg), None
    if a == "sleep":
        subprocess.Popen(["systemctl", "suspend"])
        return "Ухожу в сон. Бот замолчит до пробуждения.", None
    if a == "reboot":
        subprocess.Popen(["systemctl", "reboot"])
        return "Перезагружаюсь.", None
    if a == "off":
        subprocess.Popen(["systemctl", "poweroff"])
        return "Выключаюсь.", None
    return "Неизвестное действие.", None
