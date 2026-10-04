#!/usr/bin/env python3
"""Шейдеры kitty — два независимых переключателя. 28.09.2026.

У kitty одна строка `custom_shaders`, но в неё можно перечислить несколько
шейдеров через пробел, и они работают вместе (проверено: ЭЛТ и след курсора
одновременно). Поэтому здесь два «слота», а строка собирается из обоих:

    экран   — эффект поверх всего окна (ЭЛТ-монитор 90-х)
    курсор  — след текстового курсора (разряд или огонь)
    печать  — отдача и молнии на БЫСТРОМ наборе (сигнал подаёт jtype)

Порядок в строке — сначала курсор, потом экран: так ЭЛТ искривляет и след,
и он лежит на стекле вместе с текстом.

    kitty_shader.py get  screen|cursor         текущий выбор или "off"
    kitty_shader.py list screen|cursor         варианты: ключ<TAB>название
    kitty_shader.py set  screen|cursor <ключ>  выбрать ("off" — выключить)

Шейдеры лежат в ~/.config/kitty/shaders/, цвет следа — из обоев
(kitty_shader_colors.py). Нужен пакет shader-slang: без него kitty не соберёт
шейдер и покажет вместо окна ошибку.

Открытые окна получают новый выбор сразу (04.10.2026, просьба: «настройки шейдеров
не применяются»). kitty 0.49 перекомпилирует custom_shaders при перечитывании
конфига (boss.apply_new_options → load_shader_programs.recompile_if_needed).
Перечитывает kitten ~/.config/kitty/reload_keep_font.py — не сбивает размер
шрифта окон; после него заново ставится акцент виджетов (widget_accent.py),
перечитывание его затирает.
"""
import glob
import os
import re
import subprocess
import sys

CONF = os.path.expanduser("~/.config/kitty/kitty.conf")
KEY = "custom_shaders"

SLOTS = {
    "screen": [("crt90", "ЭЛТ-монитор 90-х"), ("susanoo", "Сусаноо")],
    "cursor": [("trail-lightning", "Разряд"), ("trail-blaze", "Огонь")],
    "typing": [("typestorm", "Отдача и молнии"), ("typeshake", "Только отдача"),
               ("speedburst", "Только молнии")],
}
# Порядок в строке важен: тряска двигает картинку, поэтому идёт ПОСЛЕДНЕЙ —
# иначе ЭЛТ искривлял бы уже сдвинутое изображение и края дёргались бы.
ORDER = ("cursor", "screen", "typing")


def current_names():
    try:
        txt = open(CONF, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"^\s*%s\s+(.+)$" % KEY, txt, re.M)
    if not m:
        return []
    return [n for n in m.group(1).split() if n.lower() != "none"]


def get(slot):
    names = current_names()
    for key, _ in SLOTS[slot]:
        if key in names:
            return key
    return "off"


def write(names):
    """Вписать выбор в kitty.conf.

    «Всё выключено» — это ОТСУТСТВИЕ строки, а не `custom_shaders none`:
    kitty понимает none буквально и ищет шейдер с таким именем, а не найдя,
    показывает ошибку при каждом открытии окна. На эти грабли наступили
    28.09.2026 — пользователь выключил всё и получил ругань в каждом новом окне.
    """
    txt = open(CONF, encoding="utf-8").read()
    if not names:
        txt = re.sub(r"^\s*%s\s+.+\n?" % KEY, "", txt, count=1, flags=re.M)
    elif re.search(r"^\s*%s\s+.+$" % KEY, txt, re.M):
        txt = re.sub(r"^\s*%s\s+.+$" % KEY, f"{KEY} " + " ".join(names),
                     txt, count=1, flags=re.M)
    else:
        txt = txt.rstrip("\n") + (
            "\n\n# Шейдеры (kitty 0.49+). Переключаются в «Настройках» → «Шейдеры»,\n"
            "# либо ~/.config/hypr/scripts/kitty_shader.py. Нужен пакет shader-slang.\n"
            f"{KEY} " + " ".join(names) + "\n")
    open(CONF, "w", encoding="utf-8").write(txt)


def set_slot(slot, key):
    choice = {s: get(s) for s in ORDER}
    choice[slot] = key if key in dict(SLOTS[slot]) else "off"
    write([choice[s] for s in ORDER if choice[s] != "off"])
    reload_running()
    return 0


def reload_running():
    procs = [subprocess.Popen(["kitty", "@", "--to", "unix:" + sock, "kitten", "reload_keep_font.py"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for sock in glob.glob("/tmp/kitty-*") if os.path.exists(sock)]
    for p in procs:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            p.kill()
    subprocess.run([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "widget_accent.py")],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in SLOTS:
        print(__doc__)
        return 1
    cmd, slot = sys.argv[1], sys.argv[2]
    if cmd == "get":
        print(get(slot))
    elif cmd == "list":
        for key, title in SLOTS[slot]:
            print(f"{key}\t{title}")
    elif cmd == "set":
        return set_slot(slot, sys.argv[3] if len(sys.argv) > 3 else "off")
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
