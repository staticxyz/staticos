#!/usr/bin/env python3
"""Шейдеры kitty в цвете обоев. 28.09.2026.

Пересобирает конвейеры в ~/.config/kitty/shaders/*.pipeline, подставляя акцент
обоев в переменную ACCENT. Конвейер kitty подменяет ею строку
`static const float3 ACCENT = ...;` внутри шейдера. Подстановка ТЕКСТОВАЯ,
поэтому значение пишется готовым кодом slang — float3(r, g, b).

Почему скриптом, а не шаблоном matugen. Шаблоны matugen дают цвет строкой
#b4c5ff, а шейдеру нужны три числа 0..1. Разбирать hex в slang негде.

Акцент не берётся буквально: блёклый или слишком тёмный цвет на тёмном фоне
терминала почти не виден. Насыщенность и светлота поднимаются до разумного
низа — пользователь просил, чтобы след был ярче и заметнее.

Вызывается из theme_changer.sh. Уже открытые окна kitty подхватывают новый
цвет только после перезапуска: шейдеры собираются при старте kitty.
"""
import colorsys
import json
import os
import sys

COLORS = os.path.expanduser("~/.cache/matugen/colors.json")
DIR = os.path.expanduser("~/.config/kitty/shaders")

MIN_SAT = 0.70
MIN_LIGHT = 0.60
MAX_LIGHT = 0.74

HEADER = """# СОБРАН АВТОМАТИЧЕСКИ скриптом ~/.config/hypr/scripts/kitty_shader_colors.py
# при каждой смене обоев. Правки здесь пропадут — правьте скрипт.
# Включается в «Настройках» → «Шейдеры» (kitty_shader.py).
"""

TRAIL = """{header}
# {title}

startgroup
    animation_start cursor-trail-move
    animation_stop cursor-trail-stop
    var float3 ACCENT = float3({r:.4f}, {g:.4f}, {b:.4f})
    shaders {name}
endgroup
"""

CRT = """{header}
# ЭЛТ-монитор 90-х.

startgroup
    # БЕЗ animation_start: группа с событиями работает только пока идёт
    # анимация, и шейдер пропадал, стоило увести фокус на другое окно
    # (замечание пользователя 28.09.2026). Здесь эффект статичный и держится всегда.
    # animation_step 0 — рисовать только когда меняется содержимое. Без него
    # группа без animation_start крутится каждые 50 мс, ВСЕГДА: одно окно с ЭЛТ
    # держало niri на 25 % CPU, девять — на 38 %, а сами kitty — по 3,5 % каждое
    # (замер 30.09.2026: без ЭЛТ niri 1–2 %). Шейдер от времени не зависит,
    # так что лишние кадры были одинаковыми.
    animation_step 0
    shaders crt90
endgroup
"""


SHAKE = """{header}
# Отдача на скорости: экран вздрагивает, когда набор ускоряется.

startgroup
    # На движение текстового курсора. «Только в тренажёре» обеспечивается не
    # здесь, а тем, что jtype открывает своё окно kitty с этим шейдером:
    # событие bell-in-window, которым я пробовал это сделать, в kitty 0.49.1
    # не возникает вовсе (проверено пробным шейдером).
    animation_start cursor-trail-move
    animation_stop 190
    animation_curve linear
    animation_step 8
    shaders typeshake
endgroup
"""


SUSANOO = """{header}
# Сусаноо: обводка с кадра аниме, хранится отрезками.

startgroup
    # Без animation_start: группа с событиями работает только пока идёт
    # анимация, и шейдер пропадал при уходе фокуса. Дыхание идёт по timestamp,
    # перерисовки случаются вместе с обычными.
    var float3 ACCENT = float3({r:.4f}, {g:.4f}, {b:.4f})
    shaders susanoo
endgroup
"""


BURST = """{header}
# Молнии от курсора на быстрой печати. Срабатывают на каждое движение
# текстового курсора, но силу даёт скорость: шейдер сам меряет её по отставанию
# следа, и в спокойной работе разрядов нет.

startgroup
    animation_start cursor-trail-move
    animation_stop 380
    animation_curve linear
    animation_step 8
    var float3 ACCENT = float3({r:.4f}, {g:.4f}, {b:.4f})
    shaders speedburst
endgroup
"""


STORM = """{header}
# Отдача и молнии вместе. Оба эффекта сами гаснут на спокойном наборе, поэтому
# их можно держать включёнными всегда: в обычной работе экран стоит смирно,
# а в тренажёре jtype, где печатают быстро, они горят почти постоянно.

startgroup
    animation_start cursor-trail-move
    animation_stop 190
    animation_curve linear
    animation_step 8
    shaders typeshake
endgroup

startgroup
    animation_start cursor-trail-move
    animation_stop 380
    animation_curve linear
    animation_step 8
    var float3 ACCENT = float3({r:.4f}, {g:.4f}, {b:.4f})
    shaders speedburst
endgroup
"""


def accent():
    try:
        with open(COLORS) as f:
            hexval = json.load(f).get("primary", "#b4c5ff")
    except (OSError, ValueError):
        hexval = "#b4c5ff"
    h = hexval.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    hh, ll, ss = colorsys.rgb_to_hls(r, g, b)
    return colorsys.hls_to_rgb(hh, min(max(ll, MIN_LIGHT), MAX_LIGHT), max(ss, MIN_SAT))


def main():
    r, g, b = accent()
    os.makedirs(DIR, exist_ok=True)
    for name, title in (("trail-blaze", "Огненный след текстового курсора."),
                        ("trail-lightning", "Разряд за текстовым курсором.")):
        with open(os.path.join(DIR, name + ".pipeline"), "w") as f:
            f.write(TRAIL.format(header=HEADER, title=title, name=name, r=r, g=g, b=b))
    with open(os.path.join(DIR, "crt90.pipeline"), "w") as f:
        f.write(CRT.format(header=HEADER))
    with open(os.path.join(DIR, "typeshake.pipeline"), "w") as f:
        f.write(SHAKE.format(header=HEADER))
    with open(os.path.join(DIR, "susanoo.pipeline"), "w") as f:
        f.write(SUSANOO.format(header=HEADER, r=r, g=g, b=b))
    with open(os.path.join(DIR, "speedburst.pipeline"), "w") as f:
        f.write(BURST.format(header=HEADER, r=r, g=g, b=b))
    with open(os.path.join(DIR, "typestorm.pipeline"), "w") as f:
        f.write(STORM.format(header=HEADER, r=r, g=g, b=b))
    print(f"шейдеры kitty: акцент rgb({r:.3f}, {g:.3f}, {b:.3f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
