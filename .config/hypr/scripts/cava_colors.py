#!/usr/bin/env python3
"""Записать акцент обоев прямо в конфиг cava.

Раньше цвет столбиков возвращал widget_accent.py — он менял foreground у окна
kitty, в котором крутится cava (в конфиге цвет не задан, значит cava рисует
цветом текста терминала). Но widget_accent.py запускается ТОЛЬКО из
theme_changer, то есть в момент смены обоев. Любой cava, запущенный позже,
никто не красил — и он выходил почти белым (on_surface), какими бы ни были
обои. Ровно это и наблюдалось.

Здесь цвет кладётся в сам конфиг, поэтому он верный с первого кадра при любом
запуске. У cava включается live-config, так что уже запущенные экземпляры
перечитывают конфиг сами, без перезапуска.

background намеренно НЕ трогаем: как только он задан явно, cava начинает
заливать фон и в окне пропадает прозрачность.
"""
import os
import re
import sys

CONFIG = os.path.expanduser("~/.config/cava/config")
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")


def set_key(text, section, key, value):
    """Задать key = value внутри [section], раскомментировав строку при нужде."""
    lines = text.split("\n")
    start = None
    for i, line in enumerate(lines):
        if line.strip() == "[%s]" % section:
            start = i + 1
            break
    if start is None:
        return text
    end = len(lines)
    for i in range(start, len(lines)):
        if re.match(r"^\s*\[[a-z]+\]\s*$", lines[i]):
            end = i
            break

    pattern = re.compile(r"^\s*;?\s*%s\s*=" % re.escape(key))
    new = "%s = %s" % (key, value)
    hit = None
    for i in range(start, end):
        if pattern.match(lines[i]):
            hit = i
            break
    if hit is None:
        lines.insert(end, new)
    else:
        if lines[hit] == new:
            return text
        lines[hit] = new
    return "\n".join(lines)


def main():
    try:
        accent = open(VIVID, encoding="utf-8").read().strip()
    except OSError:
        return 0
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", accent):
        return 0
    try:
        text = open(CONFIG, encoding="utf-8").read()
    except OSError:
        return 0

    out = set_key(text, "general", "live-config", "1")
    out = set_key(out, "color", "foreground", "'%s'" % accent)
    if out == text:
        return 0
    with open(CONFIG, "w", encoding="utf-8") as fh:
        fh.write(out)
    print("cava_colors: foreground = %s" % accent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
