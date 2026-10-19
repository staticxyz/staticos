#!/usr/bin/env python3
"""Центрировать колонку, кроме случая «двое заполняют экран». 21.09.2026.

Правило:
    перешли с колонки A на СОСЕДНЮЮ колонку B, и вдвоём они занимают экран
    ЦЕЛИКОМ (третьему выглянуть некуда)  →  не трогаем, обе видны полностью;
    одна из пары УЗКАЯ (≤ трети экрана: чат стрима) и вдвоём они помещаются
    →  тоже не трогаем (05.10.2026);
    во всех прочих случаях  →  center-column.

Направление обязательно. Считать надо именно пару «откуда пришли → куда пришли»,
а не «колонка и любой её сосед». На столе 555 555 936 936 936 переход 2→3 даёт
пару 555 + 936 = 1539: остаётся щель, куда лезет обрезанный третий, значит надо
центрировать. А переход 3→4 даёт 936 + 936 = ровно 1920, и там центрировать
незачем. Без учёта направления обе пары выглядят одинаково — на этом я 21.09.2026
и ошибся: у колонки 3 сосед СПРАВА заполняет экран, служба молчала, а пришли-то
слева.

Почему «заполняют», а не «помещаются». 936 + 936 + зазоры = ровно 1920: третий не
влезет ни пикселем, край чистый. А 555 + 936 = 1539, остаётся 381 px, и в эту щель
лезет следующее окно обрезанным — такое пользователь считает неверным.

Почему службой. У niri три режима центрирования, и ни один этого не делает:
    "always"       всегда по центру — даже когда всё и так помещалось;
    "on-overflow"  держит пару, которая просто ВЛЕЗАЕТ, даже если сбоку осталось
                   место и туда выглядывает обрезанный третий;
    "never"        не центрирует вовсе, окна режутся краем.
Поэтому в конфиге стоит "never" (сама лента не прыгает), а решение принимает этот
скрипт и зовёт center-column, когда пара экран не заполняет.

Работает по смене ФОКУСА, а не по событиям раскладки: center-column сам меняет
раскладку, и реакция на неё зациклила бы службу.

16.10.2026 — у каждого стола свой вид (Super+R → ws_layout.py view, раскладки
Super+Ctrl+T). Режим "always" в конфиге больше не включается: это одна настройка на все
столы, и при каждом её перечитывании niri заново центрировал и чужие столы (просьба: «стол 1
в Подогнать, сходил на стол 2 в Центре, вернулся — стол 1 тоже по центру»). Теперь в
конфиге всегда "never", а «Центр» делает эта служба: на столе с видом center (и раскладкой
peek) — center-column при каждой смене фокуса, при новом окне в фокусе и при смене ширины
колонки в фокусе — как "always" у niri. Столы tiling/three/stacking служба не трогает.
Живёт в хозяине staticOS (staticos_host.py): раньше стартовала один раз из autostart.kdl,
упала — и «Подогнать» молча стал чистым "never" (16.10 её не было в процессах).
"""
import json
import os
import socket
import subprocess
import time

GAPS = 16           # запасное значение; действующее — layout.gaps из cfg/layout.kdl
LAYOUT = os.path.expanduser("~/.config/niri/cfg/layout.kdl")
WS_LAYOUT = os.path.expanduser("~/.config/hypr/state/ws-layout.json")   # раскладки (ws_layout.py)
WS_VIEW = os.path.expanduser("~/.config/hypr/state/ws-view.json")       # Super+R по столам
RIBBON = os.path.expanduser("~/.config/hypr/state/ribbon-center")       # общий вид из Настроек
SLACK = 8           # на столько пара может превысить экран (округление)
ROOM = 48           # меньше этого свободного места — считаем, что третьему не влезть
SETTLE = 0.05       # дать niri дорисовать раскладку перед опросом
NARROW = 0.34       # колонка не шире этой доли экрана — «узкая» (чат, заметки)
# «Подогнать» = чистый niri "never" (16.10.2026, просьба: «раньше не центрировал, просто
# сдвигал экран настолько, сколько влезет второе окно… разницы со вторым режимом нет»).
# Служба долго не работала, и привычным стало именно это; правило пары выключено.
# Вернуть правило пары — True (и VM_PAIR_RULE в desktop_widgets.py).
FIT_PAIR_RULE = False


def ask(what):
    r = subprocess.run(["niri", "msg", "--json", what], capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def screen_width():
    foc = ask("focused-output") or {}
    width = (foc.get("logical") or {}).get("width")
    if width is None:
        for o in (ask("outputs") or {}).values():
            width = (o.get("logical") or {}).get("width")
            break
    return float(width or 1920)


def gaps():
    """Зазор читается при каждом решении: его меняет ползунок «Отступы» в Настройках →
    Compositor. Прибитые 16 при зазоре 8 (13.10.2026) давали «пара не заполняет экран»,
    и две половины центрировались при каждом переходе."""
    import re
    try:
        with open(LAYOUT) as f:
            m = re.search(r"^    gaps (\d+(?:\.\d+)?)\s*$", f.read(), re.M)
        return float(m.group(1)) if m else GAPS
    except OSError:
        return GAPS


def edges():
    """Отступы у левого и правого края экрана: gaps + struts (left/right). niri_compositor.py
    edge пишет отрицательные struts — 13.10.2026 край стал 16−8 = 8, половины выросли до
    944, а счёт «три зазора по 16» давал 1936 > 1920: пара из двух половин считалась
    невлезшей и центрировалась при каждом переходе (просьба: «окна двигаются, хотя не должны»)."""
    import re
    g = gaps()
    try:
        with open(LAYOUT) as f:
            txt = f.read()
    except OSError:
        return g, g
    st = re.search(r"struts\s*\{([^}]*)\}", txt)
    side = {}
    if st:
        for k in ("left", "right"):
            m = re.search(r"^\s*%s\s+(-?\d+(?:\.\d+)?)" % k, st.group(1), re.M)
            side[k] = float(m.group(1)) if m else 0.0
    return g + side.get("left", 0.0), g + side.get("right", 0.0)


def center():
    # Сразу через сокет (16.10.2026): `niri msg` — отдельный процесс, плюс пауза SETTLE, и
    # niri успевал начать свой сдвиг ленты, а потом center-column перехватывал его вторым —
    # переход фокуса казался медленнее (Пользователь).
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(1)
            c.connect(os.environ["NIRI_SOCKET"])
            c.sendall(b'{"Action":{"CenterColumn":{}}}\n')
            if b"Ok" in c.makefile("rb").readline():
                return
    except (OSError, KeyError):
        pass
    subprocess.run(["niri", "msg", "action", "center-column"], capture_output=True)


_view_cache = [None, None]


def view_of(ws_id):
    """Вид стола: "center" (всегда по центру), "fit" (правило пары) или None (не трогать —
    у стола своя раскладка: сетка, три в ряд, плавающие). Как want_kdl в ws_layout.py."""
    key = []
    for path in (WS_LAYOUT, WS_VIEW, RIBBON):
        try:
            key.append(os.stat(path).st_mtime_ns)
        except OSError:
            key.append(None)
    if _view_cache[0] != key:
        maps = []
        for path in (WS_LAYOUT, WS_VIEW):
            try:
                with open(path) as f:
                    d = json.load(f)
                maps.append(d if isinstance(d, dict) else {})
            except (OSError, ValueError):
                maps.append({})
        try:
            with open(RIBBON) as f:
                glob = "center" if f.read().strip() == "center" else "fit"
        except OSError:
            glob = "fit"
        _view_cache[:] = [key, (maps[0], maps[1], glob)]
    modes, views, glob = _view_cache[1]
    mode = modes.get(str(ws_id), "scrolling")
    if mode == "peek":
        return "center"
    if mode != "scrolling":
        return None
    v = views.get(str(ws_id))
    return v if v in ("fit", "center") else glob


def decide(prev):
    """prev — (колонка, стол), откуда ушёл фокус. Возвращает то же для нового окна."""
    win = ask("focused-window")
    if not win or win.get("is_floating"):
        return prev
    layout = win.get("layout") or {}
    pos = layout.get("pos_in_scrolling_layout")
    if not pos:
        return prev

    mine, ws = pos[0], win.get("workspace_id")
    here = (mine, ws)
    view = view_of(ws)
    if view is None:
        return here
    if view == "center":
        center()                    # как "always": колонка с фокусом всегда по центру
        return here
    if not FIT_PAIR_RULE:
        return here                 # «Подогнать»: ленту доворачивает сам niri

    # Ширины колонок стола: {номер: ширина}. Окна одной колонки стоят друг под
    # другом и ширину делят, поэтому колонка считается один раз.
    cols = {}
    for w in ask("windows") or []:
        if w.get("workspace_id") != ws or w.get("is_floating"):
            continue
        q = (w.get("layout") or {}).get("pos_in_scrolling_layout")
        sz = (w.get("layout") or {}).get("tile_size")
        if q and sz:
            cols[q[0]] = max(cols.get(q[0], 0), sz[0])
    if len(cols) < 2:
        return here                 # одна колонка — ею ведает always-center-single-column

    prev_col, prev_ws = prev if prev else (None, None)

    # Пришли с другого стола или переехали внутри одной колонки (стопка) —
    # прежней пары нет, решать нечего.
    if prev_ws != ws or prev_col is None or prev_col == mine:
        return here

    if abs(prev_col - mine) != 1:   # прыжок через колонку (цифры, мышь) — центрируем
        center()
        return here

    came_from = cols.get(prev_col)
    total = cols.get(mine, 0) + (came_from or 0) + gaps() + sum(edges())
    screen = screen_width()
    fills = came_from is not None and total <= screen + SLACK and screen - total < ROOM
    # Узкая колонка рядом — чат стрима, заметки (05.10.2026: «переключаюсь на окно
    # с чатом справа — не центрируй, окна остаются на местах, фокус на уменьшенном окне»).
    # Одна из пары не шире трети экрана и вдвоём они помещаются — вид не трогаем, в обе
    # стороны (на чат и обратно). niri с "never" сам лишь довернёт, если что-то обрезано.
    narrow = came_from is not None and min(cols.get(mine, 0), came_from) <= screen * NARROW
    fits = came_from is not None and total <= screen + SLACK
    if not fills and not (narrow and fits):
        center()
    return here


def focused_center_ws():
    """Окно в фокусе стоит в ленте на столе с видом «Центр» — его id и ширина, иначе None."""
    win = ask("focused-window")
    if not win or win.get("is_floating"):
        return None
    lay = win.get("layout") or {}
    if not lay.get("pos_in_scrolling_layout") or view_of(win.get("workspace_id")) != "center":
        return None
    return win["id"], (lay.get("tile_size") or [0])[0]


def main():
    last = None                     # id окна, на котором был фокус
    prev = None                     # (колонка, стол), откуда ушёл фокус
    known = set()                   # окна, о которых уже знаем (новое = не было здесь)
    place = {}                      # окно → (стол, плавающее) — «Центр» решается без опроса
    tilew = {}                      # окно → ширина плитки (для смены ширины в «Центре»)
    width = {}                      # окно в фокусе → его ширина (для «Центра» при смене ширины)
    while True:
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(os.environ["NIRI_SOCKET"])
            s.sendall(b'"EventStream"\n')
            f = s.makefile("rb")
        except (OSError, KeyError):
            time.sleep(1)
            continue
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = next(iter(ev), "")
            if kind == "WindowFocusChanged":
                wid = ev[kind].get("id")
                if wid is None or wid == last:
                    continue
                last = wid
                ws, flt = place.get(wid, (None, True))
                if ws is not None and not flt and view_of(ws) == "center":
                    center()                # «Центр» — сразу, без паузы и опроса niri
                    width = {wid: tilew.get(wid)} if tilew.get(wid) else {}
                    prev = None
                    continue
                time.sleep(SETTLE)
                try:
                    prev = decide(prev)
                    got = focused_center_ws()
                    width = {got[0]: got[1]} if got else {}
                except Exception:
                    prev = None
            elif kind == "WorkspaceActivated":
                last = prev = None  # на новом столе решаем заново
            elif kind == "WindowsChanged":
                known = {w["id"] for w in ev[kind].get("windows", [])}
                place = {w["id"]: (w.get("workspace_id"), w.get("is_floating"))
                         for w in ev[kind].get("windows", [])}
                tilew = {w["id"]: ((w.get("layout") or {}).get("tile_size") or [0])[0]
                         for w in ev[kind].get("windows", [])}
            elif kind == "WindowOpenedOrChanged":
                # Новое окно в фокусе: WindowFocusChanged niri для него не шлёт. «Подогнать» —
                # niri сам доворачивает его на экран; «Центр» — по центру, как "always".
                w = ev[kind].get("window") or {}
                place[w.get("id")] = (w.get("workspace_id"), w.get("is_floating"))
                tilew[w.get("id")] = ((w.get("layout") or {}).get("tile_size") or [0])[0]
                new = w.get("id") not in known
                known.add(w.get("id"))
                if new and w.get("is_focused"):
                    last = w.get("id")
                    time.sleep(SETTLE)
                    if focused_center_ws():
                        center()
            elif kind == "WindowClosed":
                known.discard(ev[kind].get("id"))
                place.pop(ev[kind].get("id"), None)
                tilew.pop(ev[kind].get("id"), None)
            elif kind == "WindowLayoutsChanged":
                for c in ev[kind].get("changes", []):
                    tilew[c[0]] = ((c[1] or {}).get("tile_size") or [0])[0]
                # Сменилась ширина колонки в фокусе (Super+−/=) — «Центр» снова по центру.
                if last is None or not any(c[0] == last for c in ev[kind].get("changes", [])):
                    continue
                try:
                    got = focused_center_ws()
                except Exception:
                    got = None
                if got and got[0] == last:
                    if width.get(last) not in (None, got[1]):
                        center()
                    width = {last: got[1]}
        s.close()
        time.sleep(1)


if __name__ == "__main__":
    main()
