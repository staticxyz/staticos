#!/usr/bin/env python3
"""Карта ленты для waybar: сколько колонок на ленте и где ты сейчас.

Раскладка «лента» (scrolling) уводит окна за края экрана, и о них легко
забыть. Этот модуль рисует рядом со столами точки — по одной на колонку
активного стола этого монитора:

    текущая колонка (с фокусом)  — акцентом палитры, в полную силу;
    колонки на экране            — тем же акцентом, полутоном;
    колонки за краем             — едва заметно.

Модуль пуст (и waybar его прячет), когда показывать нечего: раскладка не
лента, колонок меньше двух, или карта выключена. В подсказке — сколько
колонок за краем слева и справа.

Каждый бар (монитор) держит свою копию: имя монитора даёт waybar в
WAYBAR_OUTPUT_NAME. Обновление — по событиям Hyprland (socket2) и раз в
REFRESH_S на случай прокрутки ленты без событий.

    ribbon_map.py            модуль для waybar (бесконечный вывод JSON)
    ribbon_map.py get        on / off
    ribbon_map.py on|off     включить или выключить карту
"""
import json
import os
import select
import socket
import subprocess
import sys
import time

STATE = os.path.expanduser("~/.config/hypr/state/ribbon-map")
PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")
REFRESH_S = 2.0
DOT = "●"
GAP = " "
EVENTS = {"openwindow", "closewindow", "movewindow", "movewindowv2",
          "activewindow", "activewindowv2", "workspace", "workspacev2",
          "focusedmon", "focusedmonv2", "changefloatingmode", "fullscreen",
          "moveworkspace", "moveworkspacev2", "configreloaded"}


def enabled():
    try:
        with open(STATE) as f:
            return f.read().strip() != "off"
    except OSError:
        return True


def set_state(on):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        f.write("on\n" if on else "off\n")
    os.replace(tmp, STATE)


def hypr(what):
    r = subprocess.run(["hyprctl", what, "-j"], capture_output=True, text=True)
    return json.loads(r.stdout or "null")


_pal = {"mtime": None, "primary": "#c0c1ff", "dim": "#e3e1f0"}


def palette():
    try:
        m = os.path.getmtime(PALETTE)
        if m != _pal["mtime"]:
            with open(PALETTE) as f:
                p = json.load(f)
            _pal.update(mtime=m, primary=p.get("primary", _pal["primary"]),
                        dim=p.get("on_surface", _pal["dim"]))
    except (OSError, ValueError):
        pass
    return _pal


def compute(output):
    empty = {"text": "", "tooltip": ""}
    if not enabled():
        return empty
    mons = hypr("monitors") or []
    mon = next((m for m in mons if m["name"] == output), None) \
        or next((m for m in mons if m.get("focused")), None)
    if not mon:
        return empty
    ws_id = mon["activeWorkspace"]["id"]
    ws = next((w for w in hypr("workspaces") or [] if w["id"] == ws_id), None)
    if not ws or ws.get("tiledLayout") != "scrolling":
        return empty
    # Колонка — окна с одинаковым левым краем. Развёрнутое (SUPER+=) окно
    # Hyprland отдаёт с геометрией всего экрана, и его левый край может совпасть
    # с соседней колонкой, оставшейся под ним: на столе 4 три окна давали две
    # точки (14.09.2026). Поэтому развёрнутое окно — всегда своя колонка.
    cols = {}
    for c in hypr("clients") or []:
        if (c["workspace"]["id"] == ws_id and not c.get("floating")
                and c.get("mapped", True) and not c.get("hidden")):
            key = (c["at"][0], c["address"] if c.get("fullscreen") else "")
            cols.setdefault(key, []).append(c)
    xs = sorted(cols)
    if len(xs) < 2:
        return empty
    active = (hypr("activewindow") or {}).get("address")
    left, right = mon["x"], mon["x"] + mon["width"]
    p = palette()
    parts, visible = [], []
    for i, x in enumerate(xs):
        w = max(c["size"][0] for c in cols[x])
        on_screen = x[0] < right - 4 and x[0] + w > left + 4
        focused = any(c["address"] == active for c in cols[x])
        if on_screen:
            visible.append(i)
        if focused:
            parts.append('<span foreground="%s">%s</span>' % (p["primary"], DOT))
        elif on_screen:
            parts.append('<span foreground="%s" fgalpha="55%%">%s</span>' % (p["primary"], DOT))
        else:
            parts.append('<span foreground="%s" fgalpha="28%%">%s</span>' % (p["dim"], DOT))
    n = len(xs)
    lo = visible[0] if visible else 0
    hi = visible[-1] if visible else -1
    tip = "Лента: колонок %d" % n
    if visible:
        tip += "\nНа экране: %s" % (str(lo + 1) if lo == hi else "%d–%d" % (lo + 1, hi + 1))
    tip += "\nЗа краем: слева %d, справа %d" % (lo, n - 1 - hi)
    return {"text": GAP.join(parts), "tooltip": tip, "class": "ribbon"}


def socket_path():
    rt = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if not sig:
        base = os.path.join(rt, "hypr")
        sig = max(os.listdir(base), key=lambda d: os.path.getmtime(os.path.join(base, d)))
    return os.path.join(rt, "hypr", sig, ".socket2.sock")


def run_module():
    output = os.environ.get("WAYBAR_OUTPUT_NAME", "")
    last = [None]

    def emit():
        try:
            out = json.dumps(compute(output), ensure_ascii=False)
        except Exception:
            out = json.dumps({"text": ""})
        if out != last[0]:
            print(out, flush=True)
            last[0] = out

    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(socket_path())
        except OSError:
            emit()
            time.sleep(REFRESH_S)
            continue
        emit()
        buf, next_tick = b"", time.monotonic() + REFRESH_S
        while True:
            r, _, _ = select.select([s], [], [], max(0.05, next_tick - time.monotonic()))
            dirty = False
            if r:
                chunk = s.recv(65536)
                if not chunk:
                    break
                buf += chunk
                *lines, buf = buf.split(b"\n")
                dirty = any(l.split(b">>")[0].decode("utf-8", "replace") in EVENTS for l in lines)
            if time.monotonic() >= next_tick:
                dirty, next_tick = True, time.monotonic() + REFRESH_S
            if dirty:
                emit()
        s.close()
        time.sleep(1)


def main():
    args = sys.argv[1:]
    if args == ["get"]:
        print("on" if enabled() else "off")
    elif args in (["on"], ["off"]):
        set_state(args[0] == "on")
        print("карта ленты:", args[0])
    elif not args:
        run_module()
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
