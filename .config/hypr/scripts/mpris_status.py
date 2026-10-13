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
# Пиксельный вид (pixel_look.py, 13.10.2026): бар — PxPlus 16 px, знак 12 px вместо ~7,
# поэтому название короче, иначе правая группа сдвигает середину бара.
PIXEL_MAX_LEN = 11   # было 8; 13.10.2026, просьба: «размер плеера чуть увеличь, по горизонтали»


def max_len():
    try:
        with open(os.path.expanduser("~/.config/hypr/state/pixel-look.json"), encoding="utf-8") as f:
            return PIXEL_MAX_LEN if json.load(f).get("mode") == "pixel" else MAX_LEN
    except (OSError, ValueError):
        return MAX_LEN


# Бегущая строка (13.10.2026, просьба: «чтобы текст двигался справа налево»). Длинное
# название, пока трек ИГРАЕТ, ползёт влево; на паузе — обрезка с «…» (Просьба: «только когда
# плеер играет»). Шаги задаёт wb_persist.py (SCROLL_STEP), он же держит последний pick() и
# между опросами playerctl не зовёт. В начале строка стоит HOLD секунд.
# Плавно, а не по знаку («будто телепортируется, рваные движения»): знак делится на SUB
# долей. Окно — lim знаков, слева и справа пробелы-распорки размером font_size в процентах:
# слева (1 − f), справа f ширины знака. Сумма постоянна, плашка не дёргается, а буквы
# внутри сдвигаются на долю знака за шаг. Шрифты бара моноширинные.
# Скорость — по образцу пользователя (~/Videos/video-2026-10-13_06-47-26.mp4: ~32 px/с, по 1 px
# за кадр, стоит ~2,2 с). Было 60 px/с шагами по 3 px — «слишком быстро». Теперь шаг 2 px:
# в пиксельном шрифте знак 12 px = 6 долей, в JetBrainsMono 13 px знак ~8 px = 4 доли.
PIXEL_SUB, NORMAL_SUB = 6, 4
SUB = NORMAL_SUB        # выбирает window() по виду бара
SCROLL_STEP = 0.0625    # с на долю → ~32 px/с
HOLD = 2.2              # с стоять в начале каждого круга
GAP = "   ·   "
scroll = {"key": None, "pos": 0, "active": False}


def pad(pct):
    return f"<span font_size='{pct}%'> </span>" if pct > 0 else ""


def window(label, lim):
    """Разметка окна lim знаков из кольца «название · название…» со сдвигом scroll["pos"]
    (в долях знака)."""
    global SUB
    SUB = PIXEL_SUB if lim == PIXEL_MAX_LEN else NORMAL_SUB
    if scroll["key"] != label:
        scroll["key"], scroll["pos"] = label, 0
    ring = label + GAP
    hold = int(HOLD / SCROLL_STEP)
    step = max(0, scroll["pos"] - hold)
    if step >= len(ring) * SUB:                      # круг пройден — снова постоять
        scroll["pos"], step = 0, 0
    off, frac = divmod(step, SUB)
    text = html.escape((ring + ring)[off: off + lim], quote=False)
    f = round(frac * 100 / SUB)
    return pad(100 - f) + text + pad(f)


def main(best=None):
    best = mpris_common.pick() if best is None else best
    scroll["active"] = False
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
    if mpris_common.ignored(best):                    # Blanket: пресет «Default» сам по себе ни о чём
        label, title, artist = "Blanket", "Blanket", f"пресет «{title}»"
    lim = max_len()
    # Waybar разбирает text как разметку Pango, а название трека приходит
    # откуда угодно. Один амперсанд в "Rock & Roll" делал разметку
    # невалидной, и модуль пропадал из панели целиком.
    if len(label) > lim and status == "Playing":
        label = window(label, lim)                  # экранирует сама
        scroll["active"] = True
    else:
        if len(label) > lim:
            label = label[: lim - 1].rstrip() + "…"
        label = html.escape(label, quote=False) + pad(100)   # ширина как у бегущей
    body = f"<i>{label}</i>" if status == "Paused" else label
    tip = f"{title}\n{artist}" if artist else title
    print(json.dumps({
        "text": f"{icon}<span font_size='50%'> </span>{body}",   # зазор вдвое уже (13.10.2026)
        "class": status.lower(),
        "tooltip": html.escape(tip, quote=False),
    }))


if __name__ == "__main__":
    main()
