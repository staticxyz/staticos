#!/usr/bin/env python3
"""Значки Papirus с папками в цвет обоев — без пароля.

Штатный papirus-folders перекрашивает папки, переставляя ссылки прямо в
/usr/share/icons/Papirus: это требует root при каждой смене обоев. Здесь то
же самое делается в пользовательской теме ~/.local/share/icons/Papirus-Wall:
она наследует всё от Papirus-Dark и подменяет только значки папок —
ссылками на folder-<цвет>*.svg из системного Papirus.

Цвет — ближайший к оттенку обоев (~/.cache/matugen/vivid.txt) из наборов
Papirus. Настоящий цвет каждого набора читается из самого файла значка.
Запускается из theme_changer.sh при смене обоев; если цвет не изменился,
тема не пересобирается.
"""
import colorsys
import os
import re
import shutil
import subprocess

SRC = "/usr/share/icons/Papirus"
DST = os.path.expanduser("~/.local/share/icons/Papirus-Wall")
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")
NEUTRAL = {"black", "white", "grey"}


def colors():
    """{набор: #rrggbb} — только настоящие цветовые наборы папок."""
    places = os.path.join(SRC, "48x48", "places")
    out = {}
    for name in os.listdir(places):
        m = re.fullmatch(r"folder-([a-z]+)\.svg", name)
        if not m or os.path.islink(os.path.join(places, name)):
            continue
        c = m.group(1)
        # Цветовой набор — тот, у которого есть и свои «Документы».
        if not os.path.exists(os.path.join(places, "folder-%s-documents.svg" % c)):
            continue
        svg = open(os.path.join(places, name), encoding="utf-8", errors="replace").read()
        h = re.search(r"#[0-9a-fA-F]{6}", svg)
        if h:
            out[c] = h.group(0)
    return out


def hls(hexs):
    x = hexs.lstrip("#")
    return colorsys.rgb_to_hls(*(int(x[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def pick(target, sets):
    th, tl, ts = hls(target)
    best, score = None, None
    for name, hexs in sets.items():
        h, l, s = hls(hexs)
        if ts > 0.2 and name in NEUTRAL:
            continue
        dh = min(abs(h - th), 1 - abs(h - th))
        # Главное — оттенок: «в цвет обоев» значит того же цвета, а не той же
        # насыщенности. С весом 4 для синевато-фиолетовых обоев выходил
        # голубой adwaita вместо indigo.
        sc = dh * 10 + abs(s - ts) + abs(l - tl) * 0.5
        if score is None or sc < score:
            best, score = name, sc
    return best


def build(color):
    tmp = DST + ".new"
    shutil.rmtree(tmp, ignore_errors=True)
    dirs = []
    # Ссылки на синие папки есть и в Papirus, и в Papirus-Dark (в Dark, к
    # примеру, лежит «Домашняя папка»). Смотрим обе; цветной файл берём из
    # Papirus — там лежат все цветовые наборы.
    for size in sorted(os.listdir(SRC)):
        places = os.path.join(SRC, size, "places")
        if not os.path.isdir(places):
            continue
        made = 0
        for theme_dir in ("/usr/share/icons/Papirus-Dark", SRC):
            tp = os.path.join(theme_dir, size, "places")
            if not os.path.isdir(tp):
                continue
            for name in os.listdir(tp):
                full = os.path.join(tp, name)
                out = os.path.join(tmp, size, "places", name)
                if not os.path.islink(full) or os.path.lexists(out):
                    continue
                # Куда ссылка ведёт В КОНЦЕ цепочки, а не на первом шаге:
                # inode-directory -> folder.svg -> folder-blue.svg. Со старым
                # readlink такие ссылки (936 штук, среди них inode-directory —
                # значок обычной папки в Dolphin) пропускались, и обычные папки
                # оставались синими при фиолетовых «Документах» (17.09.2026).
                base = os.path.basename(os.path.realpath(full))
                # Два семейства синих папок: folder-blue-* (обычные) и
                # user-blue-* («Домашняя папка», «Рабочий стол»).
                m = re.match(r"(folder|user)-blue([-.])", base)
                if not m:
                    continue
                new = os.path.join(places, base.replace(m.group(1) + "-blue", m.group(1) + "-" + color, 1))
                if not os.path.exists(new):
                    continue
                os.makedirs(os.path.dirname(out), exist_ok=True)
                os.symlink(new, out)
                made += 1
        if made:
            dirs.append(size + "/places")
    # Описания каталогов — из index.theme самого Papirus.
    idx = open(os.path.join(SRC, "index.theme"), encoding="utf-8").read()
    sections = []
    for d in dirs:
        m = re.search(r"^\[%s\]\n(.*?)(?=^\[|\Z)" % re.escape(d), idx, re.S | re.M)
        if m:
            sections.append("[%s]\n%s" % (d, m.group(1).strip()))
    with open(os.path.join(tmp, "index.theme"), "w", encoding="utf-8") as f:
        f.write("[Icon Theme]\nName=Papirus-Wall\n"
                "Comment=Papirus-Dark, папки в цвет обоев (folder_colors.py)\n"
                "Inherits=Papirus-Dark,Papirus,breeze-dark,hicolor\n"
                "Directories=%s\n\n%s\n" % (",".join(dirs), "\n\n".join(sections)))
    with open(os.path.join(tmp, ".color"), "w") as f:
        f.write(color + "\n")
    shutil.rmtree(DST, ignore_errors=True)
    os.rename(tmp, DST)
    if shutil.which("gtk-update-icon-cache"):
        subprocess.run(["gtk-update-icon-cache", "-q", "-f", "-t", DST], capture_output=True)
    return len(dirs)


def main():
    try:
        target = open(VIVID).read().strip()
    except OSError:
        target = "#4877b1"
    sets = colors()
    color = pick(target, sets)
    try:
        cur = open(os.path.join(DST, ".color")).read().strip()
    except OSError:
        cur = ""
    if color == cur:
        print("папки уже %s (обои %s) — без изменений" % (color, target))
        return 0
    n = build(color)
    print("папки: %s %s под обои %s, каталогов значков: %d" % (color, sets[color], target, n))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
