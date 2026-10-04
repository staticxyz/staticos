#!/usr/bin/env python3
"""Вернуть акцент обоев окнам-виджетам после общей заливки палитры.

tty-clock и termdown не умеют брать произвольный цвет: первый выбирает слот
ANSI (-C 0..7, по умолчанию зелёный), второй не красит вообще ничем и рисует
цветом текста по умолчанию. Приём один — подменить в этом окне тот ключ, из
которого программа берёт цвет, на чистый акцент (vivid.txt), а не в общей
палитре.

Какой именно ключ — зависит от программы, и это проверено запуском в
псевдотерминале, а не на глаз:
  tty-clock  -> ESC[42m, то есть слот 2 (или тот, что задан через -C N)
  termdown   -> ни одного цветового кода, только ESC[m и ESC[39;49m,
                значит цвет берётся из foreground
  cava       -> то же самое: в конфиге цвета не заданы (foreground = default),
                и столбики рисуются цветом текста терминала

Скрипты tclock и tdown делают это через `kitty -o color4=...` при запуске, но
подмена НЕ переживает смену обоев: theme_changer заливает в каждое окно полную
палитру через `kitty @ set-colors --all`, и переопределённый слот возвращается
к гармонизированному значению. Поэтому подмена восстанавливается здесь, сразу
после заливки.

Слот определяется по самой команде окна, так что работает и для окон,
запущенных голым `tty-clock` мимо tclock.
"""
import json
import os
import subprocess
import sys

VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")


def key_for(cmdline):
    """Какой ключ палитры красит эту программу, или None."""
    if not cmdline:
        return None
    exe = os.path.basename(cmdline[0])
    # termdown ставится как python-скрипт, поэтому имя может быть в argv[1].
    if exe.startswith("python"):
        exe = os.path.basename(cmdline[1]) if len(cmdline) > 1 else exe
    if exe == "tty-clock":
        if "-C" in cmdline:
            i = cmdline.index("-C")
            if i + 1 < len(cmdline) and cmdline[i + 1].isdigit():
                return "color%d" % int(cmdline[i + 1])
        return "color2"                # умолчание tty-clock — зелёный слот
    if exe == "termdown":
        return "foreground"            # цветовых кодов не шлёт вовсе
    if exe == "cava":
        # cava в ncurses-выводе рисует столбики цветом текста по умолчанию:
        # в конфиге все настройки цвета закомментированы, то есть
        # foreground = default. Поэтому столбики были одного цвета при любых
        # обоях — цвета текста терминала (почти белого on_surface). Меняем
        # foreground этого окна, как у termdown.
        return "foreground"
    return None


def main():
    try:
        accent = open(VIVID, encoding="utf-8").read().strip()
    except OSError:
        return 0
    if not accent.startswith("#"):
        return 0

    touched = 0
    for name in os.listdir("/tmp"):
        if not name.startswith("kitty-"):
            continue
        sock = "unix:/tmp/" + name
        try:
            out = subprocess.run(["kitty", "@", "--to", sock, "ls"],
                                 capture_output=True, timeout=5)
            if out.returncode != 0:
                continue
            data = json.loads(out.stdout)
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        for osw in data:
            for tab in osw.get("tabs", []):
                for win in tab.get("windows", []):
                    for proc in win.get("foreground_processes", []):
                        key = key_for(proc.get("cmdline"))
                        if key is None:
                            continue
                        # --configured ОБЯЗАТЕЛЕН, и это не мелочь.
                        # Без него подмена ложится только в живой профиль
                        # окна, а конфигурированные умолчания остаются
                        # прежними. Любое событие, которое заставляет kitty
                        # перечитать цвета из умолчаний, сбрасывает акцент —
                        # проще всего это ловится изменением кегля
                        # (CTRL+SHIFT+plus): замерено, color2 мгновенно
                        # возвращается с акцента на палитровый слот. С
                        # --configured подмена переживает и ресайз шрифта,
                        # и туда-обратно. Каждое окно-виджет — отдельный
                        # процесс kitty со своим сокетом, поэтому правка
                        # умолчаний не задевает остальные окна.
                        subprocess.run(
                            ["kitty", "@", "--to", sock, "set-colors",
                             "--configured", f"{key}={accent}"],
                            capture_output=True, timeout=5)
                        touched += 1
    if touched:
        print(f"widget_accent: акцент {accent} возвращён в {touched} окн(о/а)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
