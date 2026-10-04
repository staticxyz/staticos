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

# Предел длины считается по месту, а не одним числом (24.09.2026): заголовок начинается
# тем правее, чем больше столов в баре и колонок на карте ленты, а pomo стоит на месте.
# Замеры по снимку бара (пиксельный шрифт, 1920 px): значок стола 42 px, точка ленты
# 14 px, знак заголовка 10 px; при 6 столах и 3 колонках заголовок начинается на 332,
# pomo — на 626. Зазор до pomo — не меньше 16 px.
# 30.09.2026: pomo сдвинут правее (отступ 126 → 60 px), левый край идущего таймера
# «00:00» — на ~702 по снимку; предел длины поднят 40 → 55 («лимиты чуть поднять»).
POMO_LEFT, GAP, CHAR_W = 702, 16, 10
WS_W, COL_W, BASE = 42, 14, 332 - 6 * 42 - 3 * 14
MIN_LEN, MAX_LEN = 15, 55
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


def current_title():
    """(заголовок, сколько знаков влезает до pomo)"""
    wss = request("Workspaces")["Workspaces"]
    mine = [w for w in wss if OUTPUT is None or w["output"] == OUTPUT]
    ws = next((w for w in mine if w["is_active"]), None)
    if not ws or ws.get("active_window_id") is None:
        return "", MAX_LEN
    wins = request("Windows")["Windows"]
    win = next((w for w in wins if w["id"] == ws["active_window_id"]), None)
    cols = max([(w.get("layout") or {}).get("pos_in_scrolling_layout") or [0] for w in wins
                if w["workspace_id"] == ws["id"] and not w["is_floating"]] or [[0]])[0]
    start = BASE + WS_W * len(mine) + COL_W * max(cols, 1)
    fit = (POMO_LEFT - reserve() - GAP - start) // CHAR_W
    return (win or {}).get("title") or "", max(MIN_LEN, min(MAX_LEN, fit))


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
