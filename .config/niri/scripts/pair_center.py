#!/usr/bin/env python3
"""Центрировать колонку, кроме случая «двое заполняют экран». 21.09.2026.

Правило:
    перешли с колонки A на СОСЕДНЮЮ колонку B, и вдвоём они занимают экран
    ЦЕЛИКОМ (третьему выглянуть некуда)  →  не трогаем, обе видны полностью;
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
"""
import json
import os
import socket
import subprocess
import time

GAPS = 16           # layout.gaps из config.kdl: зазор по краям и между колонками
SLACK = 8           # на столько пара может превысить экран (округление)
ROOM = 48           # меньше этого свободного места — считаем, что третьему не влезть
SETTLE = 0.05       # дать niri дорисовать раскладку перед опросом


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


def center():
    subprocess.run(["niri", "msg", "action", "center-column"], capture_output=True)


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
    total = cols.get(mine, 0) + (came_from or 0) + GAPS * 3
    screen = screen_width()
    fills = came_from is not None and total <= screen + SLACK and screen - total < ROOM
    if not fills:
        center()
    return here


def main():
    last = None                     # id окна, на котором был фокус
    prev = None                     # (колонка, стол), откуда ушёл фокус
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
                time.sleep(SETTLE)
                try:
                    prev = decide(prev)
                except Exception:
                    prev = None
            elif kind == "WorkspaceActivated":
                last = prev = None  # на новом столе решаем заново
        s.close()
        time.sleep(1)


if __name__ == "__main__":
    main()
