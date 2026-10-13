#!/usr/bin/env python3
"""Батарейка Font Awesome с маленьким знаком внутри — шрифт JarvisBattery. 13.10.2026.

Просьба: «идея с розеткой мне не нравится, сделай это внутри иконки батареи, чтобы
иконка только одна была», а после пиксельной батарейки своей рисовки: «иконка мне
твоя не нравится… верни иконку до этого и просто нарисуй маленькую иконку заряда
внутри». Поэтому корпус и заливка — ровно те же fa-battery U+F240…F244 из
JetBrainsMono Nerd Font, а сверху — маленькая молния (заряжается) или вилка (от сети,
зарядка на паузе: лимит FlexiCharger). На заливке знак отделён от неё тёмным зазором
той же ширины, что зазор между заливкой и корпусом у самого FA.

Как собирается: глиф FA рисуется в растр 1 единица = 1 пиксель (кегль 1000), на нём
рисуется знак, потом potrace обратно в контуры. Метрики — как у Nerd Font (upm 1000,
ascent 1020, descent −300, ширина 600 с вылетом рисунка, как у оригинала), поэтому
при том же size="12288" значок того же размера и на том же месте, что прежний.

Коды (в span стоит font_family, поэтому совпадение с FA Extension U+E200… не мешает):
    U+E210 + i   заряжается, i = 0 пустая … 4 полная (как F244 … F240)
    U+E220 + i   от сети, на паузе

    build_battery_font.py            собрать в ~/.local/share/fonts
    build_battery_font.py --preview  PNG-лист в путь из аргумента
Пиксельный вариант своей рисовки (отвергнут) — build_battery_font.py.bak-pixel.
"""
import os
import sys
import tempfile

from PIL import Image, ImageDraw, ImageFont, ImageChops

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_wolf_font import parse_paths, trace  # noqa: E402  PNG → контуры, как у волка

NERD = "/usr/share/fonts/TTF/JetBrainsMonoNerdFont-Regular.ttf"
FAMILY = "JarvisBattery"
OUT = os.path.expanduser("~/.local/share/fonts/JarvisBattery-Regular.otf")
UPM, ASCENT, DESCENT, ADV = 1000, 1020, -300, 600
FA = [0xF244, 0xF243, 0xF242, 0xF241, 0xF240]      # пустая → полная
CHARGING, PLUGGED = 0xE210, 0xE220
IMG_W, IMG_H, OX = 1200, 1400, 50                  # холст, отступ слева
# Геометрия FA (замер растра, единицы шрифта от левого края рисунка): корпус 0…865,
# стенка 115, полость по высоте 486…832 от верха холста, заливка 544…776, зазор 58.
CX, CY = OX + 490, 659                             # центр полости
INNER = (OX + 115, 486, OX + 865, 832)
GAP = 58


def bolt(d, g=0):
    """На всю полость: при 16 px полость ~5 px, и маленький знак на заливке сливался в
    пятно (замер на экране 13.10.2026). Уровень и так показан числом рядом."""
    pts = [(CX + 85, CY - 145), (CX - 175, CY + 28), (CX - 15, CY + 28),
           (CX - 85, CY + 145), (CX + 175, CY - 28), (CX + 15, CY - 28)]
    d.polygon(pts, fill=255)
    if g:
        d.line(pts + pts[:2], fill=255, width=2 * g, joint="curve")


def plug(d, g=0):
    """Вилка лёжа, штырями вправо — по ширине полости места больше, чем по высоте."""
    d.rounded_rectangle([CX - 80 - g, CY - 110 - g, CX + 40 + g, CY + 110 + g],
                        radius=40 + g, fill=255)                       # корпус
    d.rectangle([CX + 30, CY - 75 - g, CX + 140 + g, CY - 30 + g], fill=255)    # штыри
    d.rectangle([CX + 30, CY + 30 - g, CX + 140 + g, CY + 75 + g], fill=255)
    d.rectangle([CX - 190 - g, CY - 28 - g, CX - 70, CY + 28 + g], fill=255)    # провод


def render(fa, sign):
    font = ImageFont.truetype(NERD, 1000)
    base = Image.new("L", (IMG_W, IMG_H), 0)
    ImageDraw.Draw(base).text((OX, 0), chr(fa), font=font, fill=255)
    if sign is None:
        return base
    sym = Image.new("L", base.size, 0)
    sign(ImageDraw.Draw(sym))
    halo = Image.new("L", base.size, 0)
    sign(ImageDraw.Draw(halo), GAP)
    inner = Image.new("L", base.size, 0)
    ImageDraw.Draw(inner).rectangle(INNER, fill=255)
    cut = ImageChops.multiply(halo, inner)                # зазор — только внутри корпуса
    out = ImageChops.subtract(base, cut)
    return ImageChops.lighter(out, sym)


def glyphs():
    """Знак — на ПУСТОЙ батарейке при любом уровне (коды +0…+4 одинаковые, оставлены,
    чтобы скрипт бара не зависел от того, рисуется ли заливка)."""
    for kind, sign in ((CHARGING, bolt), (PLUGGED, plug)):
        for i, fa in enumerate(FA):
            yield kind + i, render(FA[0], sign)


def preview(path):
    S = 40
    tiles = list(glyphs())
    im = Image.new("L", (len(FA) * S * 2, 2 * S), 20)
    for n, (code, big) in enumerate(tiles):
        r, c = divmod(n, len(FA))
        small = big.crop((0, 200, IMG_W, IMG_H - 100)).resize((S * 2, int(S * 2 * 1100 / IMG_W)),
                                                               Image.LANCZOS)
        im.paste(small, (c * S * 2, r * S))
    im.save(path)


def contours_of(img):
    with tempfile.TemporaryDirectory() as tmp:
        pbm = os.path.join(tmp, "g.pbm")
        img.point(lambda v: 0 if v > 127 else 255).convert("1").save(pbm)
        return parse_paths(trace(pbm))


def build():
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.t2CharStringPen import T2CharStringPen
    # potrace: 1/10 px, начало внизу слева, y вверх. Базовая линия на холсте — y=ASCENT.
    def P(pt):
        return (pt[0] / 10 - OX, pt[1] / 10 - (IMG_H - ASCENT))
    names, cmap, chars = [".notdef", "space"], {0x20: "space"}, {}
    metrics = {".notdef": (ADV, 0), "space": (ADV, 0)}
    chars[".notdef"] = T2CharStringPen(ADV, None).getCharString()
    chars["space"] = T2CharStringPen(ADV, None).getCharString()
    for code, img in glyphs():
        pen = T2CharStringPen(ADV, None)
        for c in contours_of(img):
            for kind, val in c:
                if kind == "move":
                    pen.moveTo(P(val))
                elif kind == "line":
                    pen.lineTo(P(val))
                else:
                    pen.curveTo(*[P(v) for v in val])
            pen.closePath()
        name = "bat%04X" % code
        names.append(name)
        cmap[code] = name
        chars[name] = pen.getCharString()
        metrics[name] = (ADV, 0)
    fb = FontBuilder(UPM, isTTF=False)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap(cmap)
    fb.setupCFF(FAMILY + "-Regular", {"FullName": FAMILY}, chars, {})
    fb.setupHorizontalMetrics(metrics)
    fb.setupHorizontalHeader(ascent=ASCENT, descent=DESCENT)
    fb.setupNameTable({"familyName": FAMILY, "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=ASCENT, sTypoDescender=DESCENT, sTypoLineGap=0,
                usWinAscent=ASCENT, usWinDescent=-DESCENT)
    fb.setupPost()
    fb.save(OUT)
    print(OUT)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--preview":
        preview(sys.argv[2])
    else:
        build()
