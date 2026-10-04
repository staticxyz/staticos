#!/usr/bin/env python3
"""Общий слой над композитором: одно и то же для Hyprland и Niri.

Из Python:  import wm;  wm.which(), wm.windows(), wm.focus(id), wm.monitors()
Из шелла:   wm.py which | windows | monitors | focus <id> | focused

Зачем. Скрипты рабочего стола писались под Hyprland и звали hyprctl напрямую.
В сеансе Niri такой вызов ничего не делает и НЕ ругается — значок браузера не
появлялся, «открыть источник» в плеере молчал, и понять это со стороны нельзя
(21.09.2026, переезд на Niri). Здесь оба композитора приведены к одному виду,
и скрипту не нужно знать, в каком сеансе он работает.

Окно наружу — словарь с ключами: id (строка: адрес в Hyprland, номер в Niri),
app (класс окна), title, pid, focused, floating, workspace, x, y, w, h и
focus_order (0 — последнее активное окно). Координат в Niri нет — там None;
размер есть.
"""
import json
import os
import subprocess
import sys

_which = None


def _run(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def which():
    """"hyprland", "niri" или None. Определяется один раз за запуск."""
    global _which
    if _which is None:
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") or \
                subprocess.run(["pidof", "Hyprland"], capture_output=True).returncode == 0:
            _which = "hyprland"
        elif os.environ.get("NIRI_SOCKET") or \
                subprocess.run(["pidof", "niri"], capture_output=True).returncode == 0:
            _which = "niri"
        else:
            _which = "none"
    return None if _which == "none" else _which


def windows():
    w = which()
    if w == "hyprland":
        out = _run(["hyprctl", "clients", "-j"])
        act = _run(["hyprctl", "activewindow", "-j"])
        try:
            clients = json.loads(out or "[]")
            focused = (json.loads(act or "{}") or {}).get("address")
        except ValueError:
            return []
        res = []
        for c in clients:
            at, size = c.get("at") or [None, None], c.get("size") or [None, None]
            res.append({
                "id": c.get("address"),
                "app": c.get("initialClass") or c.get("class") or "",
                "title": c.get("title") or "",
                "pid": c.get("pid"),
                "focused": c.get("address") == focused,
                "floating": bool(c.get("floating")),
                "workspace": (c.get("workspace") or {}).get("id"),
                "x": at[0], "y": at[1], "w": size[0], "h": size[1],
                "focus_order": c.get("focusHistoryID", 999),
            })
        return res
    if w == "niri":
        try:
            wins = json.loads(_run(["niri", "msg", "-j", "windows"]) or "[]")
        except ValueError:
            return []
        res = []
        for c in wins:
            size = ((c.get("layout") or {}).get("window_size")) or [None, None]
            res.append({
                "id": str(c.get("id")),
                "app": c.get("app_id") or "",
                "title": c.get("title") or "",
                "pid": c.get("pid"),
                "focused": bool(c.get("is_focused")),
                "floating": bool(c.get("is_floating")),
                "workspace": c.get("workspace_id"),
                "x": None, "y": None, "w": size[0], "h": size[1],
                # Порядок заполним ниже: у Niri есть отметка времени фокуса.
                "focus_order": 999,
                "_ts": ((c.get("focus_timestamp") or {}).get("secs") or 0),
            })
        for order, w in enumerate(sorted(res, key=lambda w: -w["_ts"])):
            w["focus_order"] = order
        for w in res:
            w.pop("_ts", None)
        return res
    return []


def find(app=None, title=None):
    """Окна, у которых класс и/или заголовок содержат подстроку (без регистра)."""
    res = windows()
    if app:
        a = app.lower()
        res = [w for w in res if a in w["app"].lower()]
    if title:
        t = title.lower()
        res = [w for w in res if t in w["title"].lower()]
    return res


def focused():
    for w in windows():
        if w["focused"]:
            return w
    return None


def focus(win):
    """Перевести фокус на окно: словарь из windows() или его id."""
    wid = win["id"] if isinstance(win, dict) else str(win)
    w = which()
    if w == "hyprland":
        return _run(["hyprctl", "dispatch",
                     'hl.dsp.focus({ window = "address:%s" })' % wid]) is not None
    if w == "niri":
        return _run(["niri", "msg", "action", "focus-window", "--id", wid]) is not None
    return False


def monitors():
    w = which()
    if w == "hyprland":
        try:
            mons = json.loads(_run(["hyprctl", "monitors", "-j"]) or "[]")
        except ValueError:
            return []
        return [{"name": m.get("name"), "x": m.get("x"), "y": m.get("y"),
                 "w": m.get("width"), "h": m.get("height"),
                 "scale": m.get("scale"), "focused": bool(m.get("focused"))} for m in mons]
    if w == "niri":
        try:
            outs = json.loads(_run(["niri", "msg", "-j", "outputs"]) or "{}")
            cur = json.loads(_run(["niri", "msg", "-j", "focused-output"]) or "{}") or {}
        except ValueError:
            return []
        res = []
        for name, o in outs.items():
            lg = o.get("logical") or {}
            res.append({"name": name, "x": lg.get("x"), "y": lg.get("y"),
                        "w": lg.get("width"), "h": lg.get("height"),
                        "scale": lg.get("scale"),
                        "focused": name == cur.get("name")})
        return res
    return []


def main():
    args = sys.argv[1:] or ["which"]
    if args[0] == "which":
        print(which() or "не опознан")
        return 0
    if args[0] == "windows":
        print(json.dumps(windows(), ensure_ascii=False))
        return 0
    if args[0] == "monitors":
        print(json.dumps(monitors(), ensure_ascii=False))
        return 0
    if args[0] == "focused":
        print(json.dumps(focused(), ensure_ascii=False))
        return 0
    if args[0] == "focus" and len(args) == 2:
        return 0 if focus(args[1]) else 1
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
