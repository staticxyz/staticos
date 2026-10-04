#!/usr/bin/env python3
"""Цвет сегмента пути в приглашении fish (Tide) — из палитры обоев.

Почему понадобилось. Tide красит сегмент пути ANSI-цветом «blue», а наш
генератор палитры (gen_term_colors.py) ПОВОРАЧИВАЕТ все шестнадцать ANSI-слотов
в сторону акцента обоев — иначе fastfetch и подсветка синтаксиса не менялись бы
вовсе. При тёплом акценте «синий» уезжает в розово-сиреневую область: замерено
на генераторе — акцент #ffb07b даёт «синий» #ed91e7, акцент #e06c9a — #ec93c3.
Отсюда и «почему у меня путь всегда розовый» (21.09.2026).

Поэтому сегмент пути больше не берёт ANSI-слот, а красится прямо акцентом
обоев: fish хранит цвета Tide в универсальных переменных, и они действуют сразу
во всех открытых оболочках — перезапускать ничего не нужно.

    tide_colors.py          применить цвета из ~/.cache/matugen/term-facts.sh
    tide_colors.py show     показать, что стоит сейчас
"""
import os
import re
import subprocess
import sys

FACTS = os.path.expanduser("~/.cache/matugen/term-facts.sh")
VARS = ("tide_pwd_bg_color", "tide_pwd_color_dirs",
        "tide_pwd_color_anchors", "tide_pwd_color_truncated_dirs")


def facts():
    out = {}
    try:
        for line in open(FACTS):
            m = re.match(r"^([A-Z_]+)=(.+)$", line.strip())
            if m:
                out[m.group(1)] = m.group(2).strip().strip('"')
    except OSError:
        pass
    return out


def fish(cmd):
    r = subprocess.run(["fish", "-c", cmd], capture_output=True, text=True)
    return (r.stdout + r.stderr).strip()


def apply():
    f = facts()
    accent = (f.get("ACCENT_HEX") or "").lstrip("#")
    on_accent = (f.get("ON_ACCENT") or "").lstrip("#")
    if len(accent) != 6 or len(on_accent) != 6:
        return "в term-facts.sh нет акцента — цвета приглашения не трогаю"
    # С 24.09.2026 — не точные цвета, а слоты палитры: «синий» (color4) —
    # это теперь сам акцент обоев (gen_term_colors.py), «чёрный» (color0) — фон
    # окна. Точный цвет навсегда впечатывается в уже выведенную строку, и после
    # смены обоев старые приглашения оставались в прежней гамме.
    # Слот же терминал перерисовывает сам — старые строки перекрашиваются вместе
    # с палитрой.
    fish("set -U tide_pwd_bg_color blue")
    fish("set -U tide_pwd_color_dirs black")
    fish("set -U tide_pwd_color_anchors black")
    fish("set -U tide_pwd_color_truncated_dirs black")
    return "путь в приглашении: фон — слот blue (акцент #%s), текст — слот black" % accent


def show():
    return fish("for v in %s; echo -n \"$v = \"; echo $$v; end" % " ".join(VARS))


def main():
    args = sys.argv[1:]
    if args and args[0] == "show":
        print(show())
        return 0
    print(apply())
    return 0


if __name__ == "__main__":
    sys.exit(main())
