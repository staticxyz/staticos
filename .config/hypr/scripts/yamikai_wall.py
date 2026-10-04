#!/usr/bin/env python3
"""Курсор Yamikai в цветах обоев. 30.09.2026.

    yamikai_wall.py [текущее-имя]   собрать тему в свободный каталог A/B, напечатать имя

Исходник — тема Yamikai (ohaiikate, gnome-look 2365175, Free Art License 1.3) в
~/.local/share/icons/Yamikai. Рисунок — сетка 16 px, растянутая вдвое, как у
MSTCRSR (Jarvis), поэтому размеры те же: из родной сетки собираются 16/24/32/48,
выбранный размер — общий с Jarvis (cursor_colors.chosen_size, --size N).

Перекраска (цвета исходника замерены):
    розовый  #ff6dce  обводка      → vivid — насыщенный акцент (primary у matugen
                                     пастельный и сливался с белой заливкой)
    белый    #ffffff  заливка      → светлый оттенок акцента (как контур у Jarvis)
    фиолет.  #4d23cf  детали       → primary_container (тёмный насыщенный)
    серый    #2d2d2d  тени/детали  → surface_high
В исходнике по краям лежат почти прозрачные пиксели (альфа 1–4) — выбрасываются.
Имя чередуется A/B: niri не перечитывает курсор, если имя темы не изменилось.
"""
import os
import pathlib
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cursor_colors  # noqa: E402
from PIL import Image  # noqa: E402

SRC = pathlib.Path.home() / ".local/share/icons/Yamikai"
NAMES = ("Yamikai-Wall-A", "Yamikai-Wall-B")
SIZES = (16, 24, 32, 48)
IMAGE_TYPE = 0xFFFD0002


def hexrgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def read_xcursor(path):
    """[(nominal, Image, xhot, yhot, delay)] — только картинки."""
    b = path.read_bytes()
    if b[:4] != b"Xcur":
        return None
    n = struct.unpack("<I", b[12:16])[0]
    out = []
    for i in range(n):
        t, _sz, pos = struct.unpack("<III", b[16 + 12 * i:28 + 12 * i])
        if t != IMAGE_TYPE:
            continue
        _, _, nom, _, w, h, xh, yh, dl = struct.unpack("<9I", b[pos:pos + 36])
        im = Image.frombytes("RGBA", (w, h), b[pos + 36:pos + 36 + w * h * 4], "raw", "BGRA")
        out.append((nom, im, xh, yh, dl))
    return out


def largest(images):
    """Кадры самого крупного размера в исходном порядке (анимация сохраняется)."""
    top = max(nom for nom, *_ in images)
    return [(im, xh, yh, dl) for nom, im, xh, yh, dl in images if nom == top]


def is_2x(im):
    px = im.load()
    w, h = im.size
    if w % 2 or h % 2:
        return False
    return all(px[x, y] == px[x - x % 2, y - y % 2] for y in range(h) for x in range(w))


def recolor(im, table):
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    src, dst = im.load(), out.load()
    for y in range(im.height):
        for x in range(im.width):
            r, g, b, a = src[x, y]
            if a < 128:
                continue
            key = min(table, key=lambda c: (c[0] - r) ** 2 + (c[1] - g) ** 2 + (c[2] - b) ** 2)
            dst[x, y] = (*table[key], 255)
    return out


def build(now=""):
    pal = cursor_colors.load_palette()
    table = {
        (255, 109, 206): hexrgb(pal.get("vivid", pal["primary"])),
        (255, 255, 255): cursor_colors.halo_color(pal),
        (77, 35, 207): hexrgb(pal.get("primary_container", pal["primary"])),
        (45, 45, 45): hexrgb(pal.get("surface_container_high", pal.get("surface", "#2d2d2d"))),
    }
    name = NAMES[1] if now == NAMES[0] else NAMES[0]
    dest = cursor_colors.ICONS / name
    tmp = cursor_colors.ICONS / f".{name}.tmp-{os.getpid()}"
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "cursors").mkdir(parents=True)
    (tmp / "index.theme").write_text(
        "[Icon Theme]\nName=%s\nComment=Yamikai в цветах обоев\nInherits=Yamikai\n" % name)
    for f in sorted((SRC / "cursors").iterdir()):
        target = tmp / "cursors" / f.name
        if f.is_symlink():
            target.symlink_to(os.readlink(f))
            continue
        images = read_xcursor(f)
        if not images:
            shutil.copy2(f, target)
            continue
        out = []
        frames = largest(images)
        for s in SIZES:
            for im, xh, yh, dl in frames:
                im = recolor(im, table)
                if is_2x(im):
                    base, bx, by = im.resize((im.width // 2, im.height // 2), Image.NEAREST), xh / 2, yh / 2
                    f_ = s / 16
                else:                       # не по сетке 2×2 — масштаб от 32
                    base, bx, by = im, xh, yh
                    f_ = s / 32
                big = base.resize((max(1, round(base.width * f_)), max(1, round(base.height * f_))),
                                  Image.NEAREST)
                out.append((s, big, int(bx * f_), int(by * f_), dl))
        cursor_colors.write_xcursor(target, out)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    link = pathlib.Path.home() / ".icons" / name
    if not link.exists():
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(dest)
    return name


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else ""))
