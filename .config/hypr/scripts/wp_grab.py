"""Снимки мониторов для ленты SUPER+W — запускаются раньше всего остального (13.10.2026).

Просьба: «Super+W открывается сейчас чуть медленно». Замер: до окна ~0,45 с, из них 0,15 —
загрузка GTK/numpy и 0,22–0,28 — два grim подряд. Здесь только стандартная библиотека,
поэтому wallpaper_picker.py зовёт start() самой первой строкой: grim по всем мониторам
идут параллельно, пока грузится GTK, и к постройке окна снимки уже готовы.
"""
import json
import os
import subprocess
import threading

SCALE = 0.6                   # снимок монитора: 1920×1080 → 1152×648


def niri_env():
    env = dict(os.environ)
    if not env.get("NIRI_SOCKET"):
        rd = "/run/user/%d" % os.getuid()
        try:
            socks = sorted(n for n in os.listdir(rd) if n.startswith("niri.") and n.endswith(".sock"))
            if socks:
                env["NIRI_SOCKET"] = os.path.join(rd, socks[0])
        except OSError:
            pass
    return env


def outputs():
    """[(имя, x, y, ширина, высота)] слева направо и признак фокуса."""
    env = niri_env()
    try:
        raw = json.loads(subprocess.run(["niri", "msg", "-j", "outputs"], env=env,
                                        capture_output=True, timeout=3).stdout)
        foc = json.loads(subprocess.run(["niri", "msg", "-j", "focused-output"], env=env,
                                        capture_output=True, timeout=3).stdout or "null")
    except (OSError, ValueError, subprocess.SubprocessError):
        return [], None
    mons = []
    for name, o in raw.items():
        lg = o.get("logical") or {}
        if lg:
            mons.append((name, lg["x"], lg["y"], lg["width"], lg["height"]))
    mons.sort(key=lambda m: (m[1], m[2]))
    return mons, (foc or {}).get("name")


def grim_cmd(mon):
    return ["grim", "-t", "ppm", "-s", "%.3f" % SCALE, "-o", mon, "-"]


class Grabs:
    """grim по всем мониторам разом; raw(имя) ждёт свой снимок (байты ppm или None)."""

    def __init__(self):
        self.mons, self.focused = outputs()
        self.data = {}
        self.threads = {}
        env = niri_env()
        for m in self.mons:
            t = threading.Thread(target=self._run, args=(m[0], env), daemon=True)
            t.start()
            self.threads[m[0]] = t

    def _run(self, mon, env):
        try:
            self.data[mon] = subprocess.run(grim_cmd(mon), capture_output=True,
                                            timeout=5, env=env).stdout or None
        except (OSError, subprocess.SubprocessError):
            self.data[mon] = None

    def raw(self, mon):
        t = self.threads.get(mon)
        if t:
            t.join(6)
        return self.data.get(mon)


def start():
    return Grabs()
