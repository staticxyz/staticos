#!/usr/bin/env python3
"""Заголовок окна в фокусе для waybar под niri (custom/window-title), 24.09.2026.

Вместо встроенного niri/window: тот обрезает по max-length сам и оставляет пробел
перед «…» («Выравнивание текста в …»), а полного заголовка не показывает нигде.
Здесь обрезка без хвостового пробела и подсказка с полным заголовком.

Монитор модуль узнаёт из WAYBAR_OUTPUT_NAME (waybar ставит его каждому экземпляру):
у каждого монитора — окно в фокусе на его активном столе, как separate-outputs.
Ждёт события niri (EventStream) и перечитывает состояние на каждое — без опроса.
Откат — в ~/.config/niri/scripts/waybar_niri.py вернуть "niri/window".
"""
import html
import json
import os
import re
import socket
import sys

# Предел длины — по замерам бара (07.10.2026, переделано: пользователь попросил «посчитать
# максимум, насколько растут элементы справа»). Правая группа шире половины бара, поэтому
# средняя прижата к ней: всё, на что вырастут средняя и правая, сдвигает левый край
# средней, и заголовок должен кончаться раньше него. Иначе бар уезжает за правый край.
#
# Замеры по снимкам (1920 px): заголовок начинается на LEFT0 + 42 px на значок стола
# в баре + 14 px на точку ленты (лента видна от 2 колонок). Левый край средней группы —
# CENTER0 при: часы показывают время, значков приватности нет, записи нет, Bluetooth
# выключен, трек есть (≤14 знаков), числа двузначные, помидор «44:54».
LEFT0, WS_W, COL_W = 72, 42, 14
CENTER0 = 722               # 688 при одном значке микрофона + его 34 px
CHAR_W, GAP = 10.6, 16
DATE_W = 46                 # дата «07.10.2026» вместо «21:43» (waybar_clock: side-файл)
# Запас на то, что меняется чаще, чем обновляется заголовок: CPU 100% (+2 знака),
# звук «Muted» (+2), помидор дольше часа (+2), значок фокуса у помидора (16 px).
GROW = 21 + 21 + 21 + 16
BT_ICON = 28                # значок Bluetooth с полями, когда он включён
MIN_LEN, MAX_LEN = 15, 90
SIDE_FILE = os.path.expanduser("~/.cache/waybar-calendar-side")
REWRITE = [         # срезаем имя программы: его и так видно по значку стола
    (r"(.*) — Zen Browser$", r"\1"),
    (r"(.*) - Helium$", r"\1"),
    (r"(.*) — LibreWolf$", r"\1"),
    (r"(.*) - Obsidian v[0-9.]+$", r"\1"),
    (r"(.*) — Dolphin$", r"\1"),
]
OUTPUT = os.environ.get("WAYBAR_OUTPUT_NAME")


def request(req):
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data)["Ok"]


def reserve():
    """Место слева от pomo под индикаторы приватности (микрофон/камера/экран) и
    точку записи: они стоят в той же средней группе и растут ВЛЕВО. Без этого
    длинный заголовок и значок вместе не помещались — весь бар сдвигался вправо,
    кнопка питания уезжала за край (01.10.2026, снимок пользователя). Число значков
    пишет privacy_status.py в $XDG_RUNTIME_DIR/jarvis-privacy-n."""
    run = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
    px = 0
    try:
        n = int(open(os.path.join(run, "jarvis-privacy-n")).read().strip() or 0)
    except (OSError, ValueError):
        n = 0
    if n:
        px += 16 + 18 * n          # поля модуля 8+8 и ~18 px на значок
    if os.path.exists(os.path.join(run, "jarvis-rec", "pid")):
        px += 30                   # красная точка записи
    return px


def ws_in_bar():
    """Есть ли столы в верхнем баре ЭТОГО монитора (у каждого свой config-niri-ВЫХОД)."""
    if ws_in_bar.cache is None:
        ws_in_bar.cache = False
        for name in ("config-niri-%s.jsonc" % OUTPUT, "config-niri.jsonc"):
            try:
                txt = open(os.path.expanduser("~/.config/waybar/" + name)).read()
            except OSError:
                continue
            left = re.search(r'"modules-left"\s*:\s*\[(.*?)\]', txt, re.S)
            ws_in_bar.cache = bool(left and "workspaces" in left.group(1))
            break
    return ws_in_bar.cache


ws_in_bar.cache = None


def bluetooth_px(cache={"t": 0, "px": 0}):
    """Ширина Bluetooth в баре: выключен — 0, включён — значок, подключён — значок и
    «имя NN%». Опрос bluetoothctl не чаще раза в 10 с."""
    import subprocess
    import time
    if time.monotonic() - cache["t"] < 10:
        return cache["px"]
    cache["t"], px = time.monotonic(), 0
    try:
        run = lambda *a: subprocess.run(["bluetoothctl", *a], capture_output=True, text=True,
                                        timeout=2).stdout
        if "Powered: yes" in run("show"):
            px = BT_ICON
            for line in run("devices", "Connected").splitlines():
                alias = line.split(" ", 2)[2] if line.count(" ") >= 2 else ""
                px += round((len(alias) + 5) * CHAR_W)      # « имя 85%»
    except (OSError, subprocess.SubprocessError):
        pass
    cache["px"] = px
    return px


def shows_date():
    try:
        return open(SIDE_FILE).read().strip() == OUTPUT
    except OSError:
        return False


def current_title():
    """(заголовок, сколько знаков влезает до средней группы)"""
    wss = request("Workspaces")["Workspaces"]
    mine = [w for w in wss if OUTPUT is None or w["output"] == OUTPUT]
    ws = next((w for w in mine if w["is_active"]), None)
    if not ws or ws.get("active_window_id") is None:
        return "", MIN_LEN
    wins = request("Windows")["Windows"]
    win = next((w for w in wins if w["id"] == ws["active_window_id"]), None)
    cols = max([(w.get("layout") or {}).get("pos_in_scrolling_layout") or [0] for w in wins
                if w["workspace_id"] == ws["id"] and not w["is_floating"]] or [[0]])[0]
    start = LEFT0 + (WS_W * len(mine) if ws_in_bar() else 0) + (COL_W * cols if cols >= 2 else 0)
    center = CENTER0 - reserve() - (DATE_W if shows_date() else 0) - bluetooth_px() - GROW
    fit = int((center - GAP - start) // CHAR_W)
    return (win or {}).get("title") or "", max(MIN_LEN, min(MAX_LEN, fit))


def ws_place():
    st = os.path.expanduser("~/.config/hypr/state")
    try:
        if open(os.path.join(st, "top-bar")).read().strip() == "off":
            return "bottom"
    except OSError:
        pass
    try:
        return open(os.path.join(st, "ws-place")).read().strip() or "top"
    except OSError:
        return "top"


def render(title, limit=MAX_LEN):
    shown = title
    for pat, rep in REWRITE:
        shown = re.sub(pat, rep, shown)
    if len(shown) > limit:
        shown = shown[:limit - 1].rstrip() + "…"
    return {"text": html.escape(shown), "tooltip": html.escape(title)}


LYRICS_ON = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-lyrics-on")
# Режим «панель задач» (taskbar.py, 30.09.2026): вместо заголовка — кнопки окон.
MODE_FILE = os.path.expanduser("~/.config/hypr/state/window-bar-mode")


def taskbar_mode():
    try:
        return open(MODE_FILE).read().strip() == "taskbar"
    except OSError:
        return False


def emit(last=[None]):
    # Играет песня с текстом (lyrics_bar.py) — её строка встаёт на это место,
    # заголовок прячется (30.09.2026): рядом им до pomo места не хватает.
    if os.path.exists(LYRICS_ON) or taskbar_mode():
        out = json.dumps({"text": "", "tooltip": ""})
    else:
        out = json.dumps(render(*current_title()), ensure_ascii=False)
    if out != last[0]:
        last[0] = out
        print(out, flush=True)


def main():
    import signal
    signal.signal(signal.SIGUSR1, lambda *_: emit())   # taskbar.py mode … — сразу
    emit()
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall(b'"EventStream"\n')
    buf = b""
    s.settimeout(1.0)          # раз в секунду — проверить флаг строки песни
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            emit()
            continue
        if not chunk:
            return 1            # niri закрылся — waybar перезапустит модуль
        buf += chunk
        if b"\n" in buf:
            buf = buf.rsplit(b"\n", 1)[1]
            emit()


if __name__ == "__main__":
    sys.exit(main())
