#!/usr/bin/env python3
"""Не давать окнам разворачиваться самим при запуске (21.09.2026).

Зачем. Браузеры и прочие Electron-программы помнят, что в
прошлый раз были развёрнуты, и требуют того же. Правила окон тут не спасают:
niri применяет open-maximized / open-maximized-to-edges в момент ПЕРВОГО
запроса конфигурации (так написано в вики), а программа просит развернуть себя
ПОСЛЕ появления — проверено по потоку событий: окно рождается шириной 936, а
через ~1 с становится 1920. Такой запрос niri выполняет всегда
(handlers/xdg_shell.rs, maximize_request → set_maximized), правилами он не
перекрывается. В Hyprland то же самое глушило suppress_event = "maximize";
в niri аналога нет.

Что делает. Смотрит поток событий. Если окно в первые SPAN секунд своей жизни
растянулось ровно на ШИРИНУ ЭКРАНА (1920, «развернуть до краёв») — возвращает
обычную ширину. Одно окно правится один раз.

Важно: о смене размера niri сообщает событием WindowLayoutsChanged, а НЕ
WindowOpenedOrChanged (проверено 21.09.2026: окно родилось шириной 936 и через
44 мс пришёл WindowLayoutsChanged с 1920). Слушать нужно именно его.

Почему именно ширина экрана, а не «во всю ширину» (1888): 1888 даёт ваш
SUPER+SHIFT+F, и его трогать нельзя. До краёв (1920) в конфиге не повешено ни
на одну клавишу, так что это всегда программа, а не вы.

Ширину меняет niri msg action set-column-width — она действует на окно в
фокусе, поэтому правим только окно, которое сейчас в фокусе (новое окно им и
становится). Чужие окна не трогаем.

Заодно (28.09.2026) — исходный размер для SUPER+0 (scripts/winreset): размер,
с которым окно устоялось за первые SPAN секунд, пишется в ORIGIN. Самовольный
разворот туда не попадает — после отката записывается уже обычная ширина.
"""
import json
import os
import socket
import subprocess
import time

SPAN = 4.0          # столько секунд после появления окна следим за ним
BACK = "50%"        # к чему возвращаем (layout.default-column-width = proportion 0.5)
QUIET = 2.5         # столько секунд не вмешиваемся после того, как ширину менял человек
TOUCH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "niri-colwidth-touch")
ORIGIN = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "niri-window-origin.json")


def user_just_resized():
    """Ширину только что менял человек (scripts/colwidth оставляет отметку).

    Без этой проверки сторож принимал за самовольный разворот последнюю ступень
    лестницы SUPER+= (2078 px — шире экрана) и откатывал её на 50 %: окно на
    пустом столе росло, сбрасывалось и росло снова (21.09.2026)."""
    try:
        return time.time() - os.path.getmtime(TOUCH) < QUIET
    except OSError:
        return False


def ask(what):
    r = subprocess.run(["niri", "msg", "--json", what], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def widths():
    outs = ask("outputs") or {}
    return {n: o["logical"]["width"] for n, o in outs.items() if o.get("logical")}


def ws_outputs():
    return {w["id"]: w.get("output") for w in (ask("workspaces") or [])}


def load_origin():
    try:
        with open(ORIGIN) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_origin(origin):
    tmp = ORIGIN + ".tmp"
    with open(tmp, "w") as f:
        json.dump(origin, f)
    os.replace(tmp, ORIGIN)


def main():
    out_w, ws_out = widths(), ws_outputs()
    wins, born, fixed, focused = {}, {}, set(), None
    origin = load_origin()          # {id окна: {"window": [w, h], "floating": bool}}

    def record(wid, layout):
        """Исходный размер: пока окну меньше SPAN секунд и ширину не трогал человек."""
        w = wins.get(wid)
        size = (layout or {}).get("window_size")
        if (w is None or not size or time.monotonic() - born.get(wid, 0.0) > SPAN
                or user_just_resized()):
            return
        rec = {"window": size, "floating": bool(w.get("is_floating"))}
        if origin.get(str(wid)) != rec:
            origin[str(wid)] = rec
            save_origin(origin)

    def remember(w, fresh):
        wid = w["id"]
        wins[wid] = w
        if wid not in born:
            born[wid] = time.monotonic() if fresh else 0.0
        if w.get("is_focused"):
            return wid
        return None

    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(os.environ["NIRI_SOCKET"])
            s.sendall(b'"EventStream"\n')
            f = s.makefile("rb")
        except OSError:
            time.sleep(1)
            continue

        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = next(iter(ev), "")
            data = ev[kind]

            if kind == "WindowsChanged":
                wins.clear()
                born.clear()
                for w in data["windows"]:                  # окна, бывшие до нас, не трогаем
                    got = remember(w, fresh=False)
                    focused = got or focused
                alive = {str(w["id"]) for w in data["windows"]}
                if set(origin) - alive:
                    origin = {k: v for k, v in origin.items() if k in alive}
                    save_origin(origin)
            elif kind == "WindowOpenedOrChanged":
                got = remember(data["window"], fresh=True)
                focused = got or focused
                record(data["window"]["id"], data["window"].get("layout"))
            elif kind == "WindowFocusChanged":
                focused = data.get("id")
            elif kind == "WorkspacesChanged":
                ws_out = ws_outputs()
            elif kind == "WindowClosed":
                wid = data["id"]
                wins.pop(wid, None)
                born.pop(wid, None)
                fixed.discard(wid)
                if origin.pop(str(wid), None) is not None:
                    save_origin(origin)
            elif kind == "WindowLayoutsChanged":
                now = time.monotonic()
                for wid, layout in data.get("changes", []):
                    record(wid, layout)
                    w = wins.get(wid)
                    if (w is None or wid in fixed or wid != focused
                            or w.get("is_floating") or now - born.get(wid, 0.0) > SPAN):
                        continue
                    size = layout.get("tile_size")
                    out = ws_out.get(w.get("workspace_id"))
                    if out not in out_w:
                        ws_out, out_w = ws_outputs(), widths()
                        out = ws_out.get(w.get("workspace_id"))
                    full = out_w.get(out)
                    # Ровно ширина экрана — это «развернуть до краёв», так умеет
                    # только программа: ни один бинд в конфиге такого не даёт
                    # (SUPER+SHIFT+F даёт 1888, лестница SUPER+= — 1888 и 2078).
                    if not size or full is None or abs(size[0] - full) > 2:
                        continue
                    if user_just_resized():
                        continue
                    fixed.add(wid)
                    subprocess.run(["niri", "msg", "action", "set-column-width", BACK],
                                   capture_output=True)

        s.close()
        time.sleep(1)


if __name__ == "__main__":
    main()
