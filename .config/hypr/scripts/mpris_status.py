#!/usr/bin/env python3
"""Waybar module: what is actually playing, or nothing at all.

Waybar's built-in `mpris` module keeps its widget on screen even when the
format renders to an empty string, which leaves a bare pill in the bar. Custom
modules are hidden when their text is empty, so this reimplements the same
label with that behaviour.

One `playerctl` call per tick, not one per player per field — this runs every
two seconds forever.
"""
import html
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mpris_common  # noqa: E402

# Обрезка по числу символов. 30 было мало на длинных названиях: строка
# всё равно упиралась в ширину и распирала панель, потому что у широких
# букв символ занимает больше места. 24 всё ещё давало заметно широкую
# плашку, поэтому 18: короче, но название пока читается.
# 14, а не 18 (23.09.2026). Waybar держит среднюю группу по центру, только
# пока боковые помещаются в свои половины: при панели шириной ~210 px на
# каждую сторону приходится 855 px. Правая группа упиралась в эту границу и
# толкала панель с температурой при каждой смене трека. Четыре знака — это
# примерно 40 px запаса. Длинное название режется с многоточием, так что
# ширина пилюли ограничена сверху при любом треке.
MAX_LEN = 14


def main():
    best = mpris_common.pick()
    if not best:
        print(json.dumps({"text": ""}))
        return

    status, title, artist = best["status"], best["title"], best["artist"]
    # Иконка показывает ДЕЙСТВИЕ по клику, а не текущее состояние: играет —
    # значит клик поставит на паузу. Записаны escape-последовательностями,
    # а не самими глифами: literal-символы Nerd Font уже терялись при
    # редактировании этого файла, и иконка Playing стала пустой строкой.
    icon = "\uf04c" if status == "Playing" else "\uf04b"  # nf-fa-pause / nf-fa-play
    label = f"{title} - {artist}" if artist else title
    if len(label) > MAX_LEN:
        label = label[: MAX_LEN - 1].rstrip() + "…"

    # Waybar разбирает text как разметку Pango, а название трека приходит
    # откуда угодно. Один амперсанд в "Rock & Roll" делал разметку
    # невалидной, и модуль пропадал из панели целиком.
    label = html.escape(label, quote=False)
    body = f"<i>{label}</i>" if status == "Paused" else label
    tip = f"{title}\n{artist}" if artist else title
    print(json.dumps({
        "text": f"{icon} {body}",
        "class": status.lower(),
        "tooltip": html.escape(tip, quote=False),
    }))


if __name__ == "__main__":
    main()
