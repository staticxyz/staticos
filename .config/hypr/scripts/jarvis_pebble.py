#!/usr/bin/env python3
"""Курсор Jarvis Pebble — «галька»: скруглённые фигуры без хвостов (28.09.2026).

Нарисован по кадру, который принёс пользователь (белый скруглённый пятиугольник с
тёмной обводкой), но свой: все фигуры векторные, в одной манере, четыре цвета.

Как рисуется. Каждая фигура — набор многоугольников и линий в поле 256×256.
Сначала все части обводятся толстой линией цвета обводки со скруглёнными
стыками, потом те же части заливаются основным цветом с тонкой линией того же
цвета — так углы выходят круглыми, а обводка у слитых частей (рука, двойные
стрелки) идёт одним контуром вокруг всего. Снизу — мягкая тень. Картинки
рендерит rsvg-convert, файлы XCursor пишутся здесь же (с предумножением альфы:
края у векторных фигур полупрозрачные).

    jarvis_pebble.py build [вариант…]   собрать темы (по умолчанию все четыре)
    jarvis_pebble.py wall [ТЕКУЩЕЕ]     «цвета обоев» в свободный из -Wall-A/-Wall-B, имя — в stdout
    jarvis_pebble.py sheet ФАЙЛ         лист со всеми курсорами всех вариантов

Включает тему не он, а cursor_theme.py (или «Настройки» → «Курсор»).
"""
import math
import os
import pathlib
import shutil
import struct
import subprocess
import sys
import tempfile

from PIL import Image

HOME = pathlib.Path.home()
ICONS = HOME / ".local/share/icons"
SIZES = (24, 32, 48, 64)
IMAGE_TYPE = 0xFFFD0002
ANIM_FRAMES = 12
ANIM_DELAY = 55

# вариант: (подпись, заливка, обводка, светлая часть анимации)
VARIANTS = {
    "Blue": ("Синий", "#3366FF", "#FFFFFF", "#9DB8FF"),
    "Navy": ("Тёмно-синий", "#1A2B6D", "#FFFFFF", "#5B74C9"),
    "Sky": ("Голубой", "#7FC8FF", "#0B1B3A", "#E3F3FF"),
    "Black": ("Чёрный", "#121212", "#FFFFFF", "#6E6E6E"),
}
# «Галька · цвета обоев» (28.09.2026): цвета считаются из палитры при каждой смене
# обоев (palette_colors), тема собирается попеременно в -Wall-A / -Wall-B — niri не
# перечитывает картинки, пока имя темы то же (как у Jarvis-Cursor-A/B).
WALL_NAMES = ("Jarvis-Pebble-Wall-A", "Jarvis-Pebble-Wall-B")
PALETTE = HOME / ".cache/matugen/colors.json"
VIVID = HOME / ".cache/matugen/vivid.txt"

OUT_W = 24          # обводка, в единицах поля 256 (снаружи видно OUT_W/2 − IN_W/2)
IN_W = 8            # скругление заливки

# ── фигуры: списки частей. Часть — ("poly", [(x, y), …]) или ("line", [(x, y), …], ширина)
#    или ("circle", cx, cy, r) или ("arc", cx, cy, r, ширина, от°, длина°) ──

PEBBLE = [(40, 36), (40, 168), (58, 186), (118, 178), (144, 130)]   # стрелка: остриё — (40, 36)


def arrow(dx=0, dy=0, k=1.0):
    return ("poly", [(40 + (x - 40) * k + dx, 36 + (y - 36) * k + dy) for x, y in PEBBLE])


def rrect(x, y, w, h, r=None):
    """Прямоугольник как многоугольник: скругление даст обводка."""
    return ("poly", [(x, y), (x + w, y), (x + w, y + h), (x, y + h)])


def head(cx, cy, ang, size=34):
    """Наконечник стрелки: треугольник, смотрящий в сторону ang (градусы)."""
    a = math.radians(ang)
    tip = (cx + math.cos(a) * size, cy + math.sin(a) * size)
    l = (cx + math.cos(a + 2.2) * size * 0.95, cy + math.sin(a + 2.2) * size * 0.95)
    r = (cx + math.cos(a - 2.2) * size * 0.95, cy + math.sin(a - 2.2) * size * 0.95)
    return ("poly", [tip, l, r])


def double_arrow(ang):
    a = math.radians(ang)
    c, d = 128, 70
    p1 = (c + math.cos(a) * d, c + math.sin(a) * d)
    p2 = (c - math.cos(a) * d, c - math.sin(a) * d)
    return [("line", [p1, p2], 18), head(*p1, ang), head(*p2, ang + 180)]


def shapes():
    """{имя: (части или функция кадра, горячая точка в поле 256, анимация?)}"""
    s = {}
    s["default"] = ([arrow()], (36, 32), False)
    # Рука — из капсул и скруглённой ладони, как в играх (28.09.2026, просьба: палец
    # короче, «менее квадратно, в сторону человеческой руки»). Указательный — у ЛЕВОГО
    # края рядом с большим: первый вариант с пальцем ближе к середине читался как
    # средний палец. Согнутые — три круглые костяшки справа, большой — под наклоном.
    hand = [("line", [(104, 72), (104, 128)], 30),                 # указательный
            ("poly", [(104, 132), (170, 126), (174, 176), (156, 196), (112, 196), (98, 178)], 22),   # ладонь
            ("line", [(128, 118), (128, 132)], 26),                # согнутые
            ("line", [(150, 122), (150, 136)], 24),
            ("line", [(170, 128), (170, 142)], 22),
            ("line", [(96, 170), (72, 146)], 26)]                  # большой
    s["pointer"] = (hand, (104, 50), False)
    s["text"] = ([("line", [(128, 58), (128, 198)], 14),
                  ("line", [(104, 58), (152, 58)], 12), ("line", [(104, 198), (152, 198)], 12)],
                 (128, 128), False)
    s["cross"] = ([("line", [(128, 64), (128, 110)], 14), ("line", [(128, 146), (128, 192)], 14),
                   ("line", [(64, 128), (110, 128)], 14), ("line", [(146, 128), (192, 128)], 14),
                   ("circle", 128, 128, 9)], (128, 128), False)
    s["not-allowed"] = ([("ring", 128, 128, 58, 18), ("line", [(88, 88), (168, 168)], 18)],
                        (128, 128), False)
    s["move"] = (double_arrow(0) + double_arrow(90), (128, 128), False)
    s["col-resize"] = (double_arrow(0), (128, 128), False)
    s["row-resize"] = (double_arrow(90), (128, 128), False)
    s["nw-resize"] = (double_arrow(45), (128, 128), False)
    s["ne-resize"] = (double_arrow(-45), (128, 128), False)
    s["copy"] = ([arrow(), ("line", [(170, 172), (218, 172)], 14), ("line", [(194, 148), (194, 196)], 14)],
                 (36, 32), False)
    s["pencil"] = ([("poly", [(70, 190), (80, 150), (172, 58), (206, 92), (114, 184)])], (72, 188), False)
    s["watch"] = (lambda i: [("ring", 128, 128, 56, 22), ("arc", 128, 128, 56, 22, i * 30, 110)],
                  (128, 128), True)
    s["progress"] = (lambda i: [arrow(), ("ring", 186, 186, 30, 14), ("arc", 186, 186, 30, 14, i * 30, 110)],
                     (36, 32), True)
    return s


# Имена, которые программы спрашивают, — ссылки на нарисованные (как в cursor_colors.py).
ALIASES = {
    "default": "left_ptr arrow X_cursor top_left_arrow help question_arrow left_ptr_help context-menu",
    "pointer": "hand hand1 hand2 grab grabbing openhand closedhand pointing_hand",
    "progress": "left_ptr_watch half-busy",
    "watch": "wait",
    "cross": "crosshair tcross diamond_cross cell plus",
    "copy": "dnd-copy dnd-link alias dnd-ask",
    "not-allowed": "no-drop dnd-none crossed_circle forbidden",
    "move": "fleur all-scroll dnd-move size_all",
    "nw-resize": "se-resize nwse-resize sizing top_left_corner bottom_right_corner size_fdiag bd_double_arrow",
    "ne-resize": "sw-resize nesw-resize top_right_corner bottom_left_corner size_bdiag fd_double_arrow",
    "col-resize": "e-resize w-resize ew-resize sb_h_double_arrow left_side right_side size_hor h_double_arrow split_h",
    "row-resize": "n-resize s-resize ns-resize sb_v_double_arrow top_side bottom_side size_ver v_double_arrow split_v",
    "text": "xterm ibeam vertical-text",
    "pencil": "draft",
}


def svg(parts, fill, out, light):
    """Две прохода: толстая обводка у всех частей, потом заливка поверх."""
    def draw(part, color, width, role):
        kind = part[0]
        if kind == "poly":
            pts = " ".join("%.1f,%.1f" % p for p in part[1])
            extra = part[2] if len(part) > 2 else 0     # своё скругление углов (ладонь руки)
            return ('<polygon points="%s" fill="%s" stroke="%s" stroke-width="%s" '
                    'stroke-linejoin="round"/>' % (pts, color, color, width + extra))
        if kind == "line":
            pts = " ".join("%.1f,%.1f" % p for p in part[1])
            w = part[2] + (width if role == "out" else 0)
            return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s" '
                    'stroke-linecap="round" stroke-linejoin="round"/>' % (pts, color, w))
        if kind == "circle":
            _, cx, cy, r = part
            return '<circle cx="%s" cy="%s" r="%s" fill="%s"/>' % (cx, cy, r + (width / 2 if role == "out" else 0), color)
        if kind == "ring":
            _, cx, cy, r, w = part
            return ('<circle cx="%s" cy="%s" r="%s" fill="none" stroke="%s" stroke-width="%s"/>'
                    % (cx, cy, r, color, w + (width if role == "out" else 0)))
        if kind == "arc":
            if role == "out":
                return ""
            _, cx, cy, r, w, start, length = part
            a0, a1 = math.radians(start), math.radians(start + length)
            x0, y0 = cx + r * math.cos(a0), cy + r * math.sin(a0)
            x1, y1 = cx + r * math.cos(a1), cy + r * math.sin(a1)
            return ('<path d="M %.1f %.1f A %s %s 0 %d 1 %.1f %.1f" fill="none" stroke="%s" '
                    'stroke-width="%s" stroke-linecap="round"/>'
                    % (x0, y0, r, r, 1 if length > 180 else 0, x1, y1, light, w - 4))
        return ""

    outline = "".join(draw(p, out, OUT_W, "out") for p in parts)
    body = "".join(draw(p, fill, IN_W, "in") for p in parts)
    return ('<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">'
            '<defs><filter id="sh" x="-20%%" y="-20%%" width="150%%" height="150%%">'
            '<feGaussianBlur in="SourceAlpha" stdDeviation="5"/><feOffset dx="3" dy="5"/>'
            '<feComponentTransfer><feFuncA type="linear" slope="0.45"/></feComponentTransfer>'
            '</filter></defs>'
            '<g filter="url(#sh)">%s</g><g>%s%s</g></svg>' % (outline, outline, body))


def render(svg_text, size, tmpdir):
    src = pathlib.Path(tmpdir) / "f.svg"
    dst = pathlib.Path(tmpdir) / "f.png"
    src.write_text(svg_text)
    subprocess.run(["rsvg-convert", "-w", str(size), "-h", str(size), str(src), "-o", str(dst)], check=True)
    return Image.open(dst).convert("RGBA")


def premultiplied_bgra(im):
    out = bytearray()
    for r, g, b, a in im.getdata():
        out += bytes((b * a // 255, g * a // 255, r * a // 255, a))
    return bytes(out)


def write_xcursor(dest, images):
    """images: [(номинал, картинка RGBA, xhot, yhot, задержка)]."""
    header = 16 + 12 * len(images)
    toc, chunks, pos = [], [], header
    for nominal, im, xh, yh, delay in images:
        data = struct.pack("<9I", 36, IMAGE_TYPE, nominal, 1, im.width, im.height, xh, yh, delay) \
            + premultiplied_bgra(im)
        toc.append(struct.pack("<III", IMAGE_TYPE, nominal, pos))
        chunks.append(data)
        pos += len(data)
    dest.write_bytes(struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(images)) + b"".join(toc) + b"".join(chunks))


def theme_name(variant):
    return "Jarvis-Pebble-" + variant


def _hex(rgb):
    return "#%02X%02X%02X" % tuple(rgb)


def palette_colors():
    """Цвета гальки из обоев — так, чтобы курсор НЕ сливался с интерфейсом.

    Оттенок — насыщенный цвет обоев (vivid.txt): курсор в гамме стола. Светлота и
    насыщенность подбираются перебором: берётся цвет, который ДАЛЬШЕ ВСЕГО (OKLab) от
    ближайшего цвета палитры — фонов, акцентов, текста. Прямой «светлый акцент»
    (L 0.80) оказался почти цветом primary (0,035), и на кнопках и выделениях курсор
    держался только обводкой; подбор дал 0,117 (28.09.2026). На тёмной теме ищем среди
    светлых (L 0.62–0.95), на светлой — среди тёмных. Обводка — почти чёрная с тем же
    оттенком (к светлой заливке) или белая: как на кадре, что приносил пользователь.
    """
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import cursor_colors as cc
    import json
    d = json.loads(PALETTE.read_text())
    c = d.get("colors", d)
    pal = {k: (v.get("dark", v) if isinstance(v, dict) else v) for k, v in c.items()}
    try:
        pal["vivid"] = VIVID.read_text().strip()
    except OSError:
        pal["vivid"] = pal["primary"]
    rgb = lambda h: tuple(int(h.strip().lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
    def lab(col):
        L, C, h = cc.to_oklch(col)
        return (L, C * math.cos(math.radians(h)), C * math.sin(math.radians(h)))
    refs = [lab(rgb(v)) for v in pal.values() if isinstance(v, str) and v.strip().startswith("#")]
    hue = cc.to_oklch(rgb(pal["vivid"]))[2]
    dark_ui = cc.to_oklch(rgb(pal["surface"]))[0] < 0.5
    Ls = [x / 100 for x in (range(62, 96, 2) if dark_ui else range(30, 56, 2))]
    best = None
    for L in Ls:
        for C in (x / 100 for x in range(10, 25, 2)):
            col = cc.from_oklch(L, C, hue)
            gap = min(math.dist(lab(col), r) for r in refs)
            if best is None or gap > best[0] + 1e-9:
                best = (gap, col, L, cc.to_oklch(col)[1])
    _, fill, L, C = best
    out = cc.from_oklch(0.17, 0.035, hue) if L > 0.6 else (255, 255, 255)
    light = cc.from_oklch(min(0.96, L + 0.12), C * 0.55, hue) if L > 0.6 else cc.from_oklch(0.72, C, hue)
    return ("Цвета обоев", _hex(fill), _hex(out), _hex(light))


def build(variant, name=None, colors=None):
    label, fill, out, light = colors or VARIANTS[variant]
    name = name or theme_name(variant)
    tmp = ICONS / (".%s.tmp-%d" % (name, os.getpid()))
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "cursors").mkdir(parents=True)
    (tmp / "index.theme").write_text("[Icon Theme]\nName=%s\nComment=Jarvis Pebble — %s\n"
                                     "Inherits=breeze_cursors\n" % (name, label))
    with tempfile.TemporaryDirectory() as td:
        for base, (parts, hot, anim) in shapes().items():
            frames = [parts(i) for i in range(ANIM_FRAMES)] if anim else [parts]
            images = []
            for size in SIZES:
                k = size / 256
                for fr in frames:
                    im = render(svg(fr, fill, out, light), size, td)
                    images.append((size, im, round(hot[0] * k), round(hot[1] * k), ANIM_DELAY if anim else 0))
            write_xcursor(tmp / "cursors" / base, images)
    for src, names in ALIASES.items():
        for alias in names.split():
            link = tmp / "cursors" / alias
            if not link.exists():
                link.symlink_to(src)
    target = ICONS / name
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return target


def sheet(dest, size=48):
    names = list(shapes())
    cell = size + 24
    img = Image.new("RGBA", (cell * len(names), cell * len(VARIANTS) * 2), (0, 0, 0, 255))
    with tempfile.TemporaryDirectory() as td:
        for vi, (variant, (label, fill, out, light)) in enumerate(VARIANTS.items()):
            for band, bg in ((0, (24, 26, 34, 255)), (1, (232, 232, 226, 255))):
                y = (vi * 2 + band) * cell
                for ni, n in enumerate(names):
                    parts, hot, anim = shapes()[n]
                    im = render(svg(parts(2) if anim else parts, fill, out, light), size, td)
                    tile = Image.new("RGBA", (cell, cell), bg)
                    tile.alpha_composite(im, (12, 12))
                    img.paste(tile, (ni * cell, y))
    img.save(dest)


def main():
    args = sys.argv[1:] or ["build"]
    if args[0] == "sheet":
        sheet(args[1])
        print("лист:", args[1])
        return 0
    if args[0] == "build":
        for v in (args[1:] or list(VARIANTS)):
            print("собрана:", build(v))
        return 0
    if args[0] == "wall":
        # Собрать «цвета обоев» в тот каталог A/B, что сейчас НЕ включён; имя — в stdout.
        name = WALL_NAMES[0] if (len(args) < 2 or args[1] != WALL_NAMES[0]) else WALL_NAMES[1]
        colors = palette_colors()
        build(None, name, colors)
        print(name)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
