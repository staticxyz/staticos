#!/usr/bin/env python3
"""Айсберг, тающий по дню до конца месяца.

Наглядный счётчик уходящего времени: глыба уменьшается каждый день и к
последнему числу исчезает совсем. На месте растаявшего остаётся тусклый
контур исходного размера — видно не только остаток, но и потраченное.

Форма задана долями, а не числом клеток, поэтому одинаково выглядит в окне
на тридцать колонок и на весь экран. Перерисовка по SIGWINCH.

Цвет берётся из палитры обоев (vivid.txt) и ВХОДИТ в условие перерисовки:
если этого не сделать, после смены обоев виджет держит старый цвет до
полуночи и его приходится перезапускать руками.
"""
import calendar
import datetime
import os
import signal
import sys
import time

VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")

_resized = False


def on_resize(_sig, _frm):
    global _resized
    _resized = True


def accent():
    try:
        h = open(VIVID).read().strip().lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (OSError, ValueError):
        return (120, 180, 230)


def fg(rgb, dim=1.0):
    r, g, b = (max(0, min(255, int(c * dim))) for c in rgb)
    return "\033[38;2;%d;%d;%dm" % (r, g, b)


def shape(w, h):
    """Силуэт айсберга: зубчатая вершина, расширяющееся основание."""
    cells = set()
    if w < 2 or h < 1:
        return cells
    for row in range(h):
        t = (row + 0.5) / h                       # 0 — вершина, 1 — низ
        half = (w / 2) * (0.12 + 0.88 * t ** 0.62)
        # Скол на левой грани и уступ на правой — чтобы глыба не выглядела
        # симметричной пирамидой.
        shift = -0.06 * w if 0.25 < t < 0.55 else 0.0
        if row % 4 == 2:
            half *= 0.94
        c = w / 2 + shift
        lo, hi = int(round(c - half)), int(round(c + half))
        for x in range(max(0, lo), min(w, max(lo + 1, hi))):
            cells.add((x, row))
    return cells


def draw():
    cols, rows = os.get_terminal_size()
    today = datetime.date.today()
    last_day = calendar.monthrange(today.year, today.month)[1]
    total = last_day
    left = last_day - today.day + 1               # включая сегодняшний
    frac = left / total

    col = accent()

    full_h = max(3, min(rows - 1, int(rows * 0.92)))
    full_w = max(6, min(cols - 4, int(full_h * 2.2)))
    # Пока день не прошёл, остаётся хотя бы крупица: при малой доле высота
    # округлялась в ноль, и айсберг пропадал ещё в последний день месяца.
    floor = 1 if left else 0
    cur_h = max(floor, int(round(full_h * frac)))
    cur_w = max(floor * 2, int(round(full_w * frac)))

    grid = [[" "] * cols for _ in range(rows)]
    style = [[None] * cols for _ in range(rows)]

    top_pad = max(0, (rows - full_h) // 2)
    base_row = top_pad + full_h                   # основание не двигается

    def put(cells, w, h, ch, dim):
        left_pad = (cols - w) // 2
        top = base_row - h
        for (x, y) in cells:
            gy, gx = top + y, left_pad + x
            if 0 <= gy < rows and 0 <= gx < cols:
                grid[gy][gx] = ch
                style[gy][gx] = fg(col, dim)

    if frac < 0.995:                              # призрак исходного размера
        put(shape(full_w, full_h), full_w, full_h, "·", 0.20)
    if cur_h and cur_w:
        put(shape(cur_w, cur_h), cur_w, cur_h, "█", 1.0)

    out = []
    for y in range(rows):
        line, cur = [], None
        for x in range(cols):
            st = style[y][x]
            if st != cur:
                line.append(st or "\033[0m")
                cur = st
            line.append(grid[y][x])
        out.append("".join(line).rstrip() + "\033[0m")
    sys.stdout.write("\033[2J\033[H" + "\n".join(out))

    sys.stdout.write("\033[0m")
    sys.stdout.flush()


def main():
    global _resized
    signal.signal(signal.SIGWINCH, on_resize)
    sys.stdout.write("\033[?25l")
    last = None
    try:
        while True:
            key = (datetime.date.today(), accent(), os.get_terminal_size())
            if _resized or key != last:
                draw()
                last, _resized = key, False
            for _ in range(20):
                if _resized:
                    break
                time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[2J\033[H")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
