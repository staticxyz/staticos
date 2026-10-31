#!/usr/bin/env python3
"""Рисунок Замка (30.10.2026): пиксельная картина из прямоугольников, общая для окна и виджета.

Сетка 120×92, масштаб целый. Каждая ступень — своя деталь; порядок ORDER — кто кого загораживает, он
не зависит от порядка постройки. Цвета постоянные, знамя и небо берут акцент обоев.

Окно-игра (вторая часть файла) рисует в маленький холст логическими пикселями и растягивает его без
сглаживания: так весь кадр в одной сетке и стоит дешевле, чем рисовать каждый квадрат крупно."""
import math
import random

import cairo

import castle_biomes as B

W, H = 120, 92
TOP = 8                                     # над знаменем место для короны
ORDER = ("hill", "moat", "keep", "tower_l", "tower_r", "wall_l", "wall_r", "base", "gate", "merlons",
         "flag", "crown")


def order(land):
    return ORDER if land == "home" else B.ORDER


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


LIGHT, STONE, SHADE, MORTAR = rgb("#b4b2bf"), rgb("#8f8d9c"), rgb("#6a6878"), rgb("#585664")
HOLE, WOOD, WOOD_D = rgb("#17161d"), rgb("#8f5f33"), rgb("#6b4524")
GRASS, GRASS_L, GRASS_D = rgb("#568f48"), rgb("#74b35c"), rgb("#3e6f3b")
EARTH, EARTH_D = rgb("#6c5140"), rgb("#533e31")
WATER, WATER_L = rgb("#3b77ad"), rgb("#74b4e0")
GOLD, GOLD_D = rgb("#ffd166"), rgb("#d99a2b")


def wall(r, x, y, w, h):
    """Кладка: швы рядами вразбежку, свет слева и сверху."""
    r(x, y, w, h, STONE)
    for j in range(2, h, 3):
        r(x, y + j, w, 1, SHADE)
        for i in range((j // 3 % 2) * 3, w, 6):
            r(x + i, y + j - 2, 1, 2, SHADE)
    r(x, y, w, 1, LIGHT)
    r(x, y, 1, h, LIGHT)
    r(x + w - 1, y, 1, h, MORTAR)
    r(x, y + h - 1, w, 1, MORTAR)


def teeth(r, x0, x1, y):
    for x in range(x0, x1 - 1, 4):
        r(x, y, 2, 2, STONE)
        r(x, y, 2, 1, LIGHT)
        r(x + 1, y + 1, 1, 1, SHADE)


def part_hill(r):
    for y, (a, b) in enumerate(((20, 100), (15, 105), (10, 110), (6, 114), (3, 117), (1, 119))):
        r(a, 60 + y, b - a, 1, GRASS_L if y < 2 else GRASS)
    r(0, 66, W, 18, EARTH)
    r(0, 66, W, 2, GRASS_D)
    for x in range(4, W, 9):
        r(x, 68, 3, 1, GRASS_D)
        r(x + 4, 73 + x % 5, 2, 1, EARTH_D)
        r(x + 1, 79 - x % 3, 3, 1, EARTH_D)
    for x in range(9, 110, 13):
        r(x, 62, 1, 1, GRASS_D)
        r(x + 5, 64, 2, 1, GRASS_L)


def part_base(r):
    wall(r, 24, 56, 72, 6)
    r(24, 60, 72, 2, SHADE)


def part_wall_l(r):
    wall(r, 32, 41, 24, 15)


def part_wall_r(r):
    wall(r, 64, 41, 24, 15)


def part_gate(r):
    wall(r, 52, 35, 16, 25)
    r(56, 47, 8, 13, HOLE)
    r(57, 46, 6, 1, HOLE)
    r(55, 45, 10, 1, LIGHT)
    r(55, 46, 1, 14, LIGHT)
    r(64, 46, 1, 14, LIGHT)
    for x in (58, 61):
        r(x, 47, 1, 8, WOOD)
    r(56, 50, 8, 1, WOOD_D)
    r(56, 54, 8, 1, WOOD_D)


def tower(r, x):
    wall(r, x, 29, 14, 27)
    r(x - 1, 28, 16, 2, LIGHT)
    r(x + 6, 37, 2, 5, HOLE)
    r(x + 6, 46, 2, 4, HOLE)


def part_tower_l(r):
    tower(r, 20)


def part_tower_r(r):
    tower(r, 86)


def part_moat(r):
    r(5, 69, 110, 5, WATER)
    r(5, 69, 110, 1, EARTH_D)
    for x in range(9, 108, 11):
        r(x, 71, 4, 1, WATER_L)
        r(x + 6, 72, 2, 1, WATER_L)
    r(53, 62, 14, 13, WOOD)
    for y in range(63, 75, 2):
        r(53, y, 14, 1, WOOD_D)
    r(52, 62, 1, 13, WOOD_D)
    r(67, 62, 1, 13, WOOD_D)


def part_keep(r):
    wall(r, 42, 16, 36, 26)
    r(41, 15, 38, 2, LIGHT)
    for x in (48, 69):
        r(x, 24, 3, 6, GOLD)
        r(x, 24, 3, 1, GOLD_D)
    r(58, 21, 4, 7, GOLD)
    r(59, 20, 2, 1, GOLD)
    r(58, 24, 4, 1, GOLD_D)


def part_merlons(r):
    teeth(r, 32, 52, 39)
    teeth(r, 68, 88, 39)
    teeth(r, 52, 68, 33)
    teeth(r, 19, 35, 26)
    teeth(r, 85, 101, 26)
    teeth(r, 41, 79, 13)


def flag(r, x, y, tall, w, h, acc):
    r(x, y, 1, tall, WOOD_D)
    r(x + 1, y, w, h, acc)
    r(x + 1, y, w, 1, mix(acc, (1, 1, 1), 0.3))
    r(x + 1, y + h - 1, w, 1, mix(acc, (0, 0, 0), 0.3))


def part_flag(r, acc):
    flag(r, 60, 0, 15, 13, 7, acc)
    flag(r, 27, 16, 11, 6, 4, acc)
    flag(r, 93, 16, 11, 6, 4, acc)


CROWN = ("...#...#...#...", ".#.#.#.#.#.#.#.", ".#############.", ".#############.", ".#############.",
         ".=============.")


def part_crown(r):
    for j, line in enumerate(CROWN):
        for i, ch in enumerate(line):
            if ch != ".":
                r(53 + i, j - 7, 1, 1, GOLD_D if ch == "=" else GOLD)
    r(60, -5, 1, 1, rgb("#e0524f"))
    r(57, -5, 1, 1, rgb("#4f9de0"))
    r(63, -5, 1, 1, rgb("#4f9de0"))
    for x, y in ((49, -6), (71, -5), (46, -2), (74, -1)):
        r(x, y, 1, 1, GOLD)


PARTS = dict(hill=part_hill, base=part_base, wall_l=part_wall_l, wall_r=part_wall_r, gate=part_gate,
             tower_l=part_tower_l, tower_r=part_tower_r, moat=part_moat, keep=part_keep,
             merlons=part_merlons, crown=part_crown)


def rects(key, acc, land="home"):
    if land != "home":
        return B.rects(land, key, acc, TOP)
    out = []
    def r(x, y, w, h, col):
        out.append((x, y + TOP, w, h, col))
    if key == "flag":
        part_flag(r, acc)
    else:
        PARTS[key](r)
    return out


STARS = ((7, 6), (19, 15), (31, 4), (43, 19), (84, 7), (98, 17), (111, 5), (114, 27), (5, 30), (36, 31),
         (74, 3), (104, 34), (13, 41))


def sky(cr, x, y, s, acc, bg):
    for i in range(6):                        # полосами, как в играх той поры
        cr.set_source_rgb(*mix(bg, acc, 0.03 + 0.042 * i))
        cr.rectangle(x, y + i * 12 * s, W * s, 12 * s)
        cr.fill()
    cr.set_source_rgb(*mix(bg, acc, 0.34))
    cr.rectangle(x, y + 72 * s, W * s, 20 * s)
    cr.fill()
    cr.set_source_rgba(1, 1, 1, 0.5)
    for a, b in STARS:
        cr.rectangle(x + a * s, y + b * s, s, s)
    cr.fill()


def lay(cr, q, x, y, s, col=None):
    cr.set_source_rgb(*(col or q[4]))
    cr.rectangle(x + q[0] * s, y + q[1] * s, q[2] * s, q[3] * s)
    cr.fill()


def paint(cr, x, y, s, built, ghost=None, grow=None, acc=(0.5, 0.6, 1), bg=(0.07, 0.07, 0.1), land="home"):
    """built — готовые ступени; ghost — контур следующей; grow (ключ, 0…1) — деталь встаёт из земли."""
    cr.save()
    cr.rectangle(x, y, W * s, H * s)
    cr.clip()
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    sky(cr, x, y, s, acc, bg)
    for key in order(land):
        if key == ghost:
            cr.push_group()
            for q in rects(key, acc, land):
                lay(cr, q, x, y, s, (1, 1, 1))
            cr.pop_group_to_source()
            cr.paint_with_alpha(0.16)
        if key not in built:
            continue
        qs = rects(key, acc, land)
        if grow and grow[0] == key and grow[1] < 1:
            top = min(q[1] for q in qs)
            low = max(q[1] + q[3] for q in qs)
            cr.save()
            cr.rectangle(x, y + top * s, W * s, (low - top) * s)
            cr.clip()
            cr.translate(0, round((1 - grow[1]) * (low - top)) * s)
            for q in qs:
                lay(cr, q, x, y, s)
            cr.restore()
        else:
            for q in qs:
                lay(cr, q, x, y, s)
    cr.restore()


# ── мир окна-игры ─────────────────────────────────────────────────────────────
# Небо, горы и земля живут по настоящему времени суток. Тяжёлое (небо, земля, замок) лежит в готовых
# холстах и меняется раз в несколько минут, в кадре рисуется только то, что движется.

# час: верх неба, середина, у горизонта, чем затемнить землю, сила затемнения, яркость звёзд
NIGHT = ("#070a1e", "#121a3c", "#2c2f5e", "#0a1030", 0.55, 1.0)
DAWN = ("#2f3a78", "#c0607e", "#ffb27a", "#5a2a40", 0.22, 0.15)
DAY = ("#3a86d8", "#78bdf0", "#d2effa", "#000000", 0.0, 0.0)
DUSK = ("#2a2466", "#c24f70", "#ffb35e", "#4a1f48", 0.30, 0.25)
HOURS = ((0, NIGHT), (5, NIGHT), (6.5, DAWN), (8.5, DAY), (16.5, DAY), (18.5, DUSK), (20.5, NIGHT), (24, NIGHT))
BAYER = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
PINE, PINE_D, TRUNK = rgb("#2f6a4d"), rgb("#234f3c"), rgb("#5c4030")
LEAF, LEAF_L, LEAF_D = rgb("#4e9a4c"), rgb("#6dbb5c"), rgb("#3a7a3f")
ROCK, ROCK_D = rgb("#8a8a96"), rgb("#62626e")
ENERGY, ENERGY_L, ENERGY_W, ENERGY_D = rgb("#8fb4ff"), rgb("#b1cbff"), rgb("#d9e5ff"), rgb("#566c99")
FIRE = (rgb("#ffd166"), rgb("#ff9a3c"), rgb("#e0522e"))
SKIN, OVERALL = rgb("#f0c090"), rgb("#3f6fb5")
RED = rgb("#e0524f")


def sky_at(hour):
    """Цвета часа: плавно между опорными часами."""
    hour %= 24
    for (h0, a), (h1, b) in zip(HOURS, HOURS[1:]):
        if h0 <= hour <= h1:
            t = (hour - h0) / (h1 - h0) if h1 > h0 else 0
            cols = [mix(rgb(a[i]), rgb(b[i]), t) for i in range(4)]
            return dict(top=cols[0], mid=cols[1], low=cols[2], tint=cols[3], shade=a[4] + (b[4] - a[4]) * t,
                        stars=a[5] + (b[5] - a[5]) * t)
    return sky_at(0)


def box(cr, x, y, w, h, col, a=1.0):
    cr.set_source_rgba(col[0], col[1], col[2], a)
    cr.rectangle(x, y, w, h)
    cr.fill()


def sprite(cr, x, y, rows, pal, flip=False, a=1.0):
    """Спрайт строками: буква — цвет из pal, точка — пусто."""
    w = max(len(r) for r in rows)
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch != ".":
                box(cr, x + (w - 1 - i if flip else i), y + j, 1, 1, pal[ch], a)


PAL = dict(H=GOLD, h=GOLD_D, F=SKIN, B=OVERALL, D=HOLE, W=WOOD, G=STONE, g=LIGHT)
HEAD = ("..HHHH....", ".HHHHHH...", ".hhhhhh...", "..FFFF....")
BODY = ("..BBBB....", ".FBBBBF...", "..BBBB....")
STAND = HEAD + BODY + ("..B..B....", "..D..D....")
WALK = HEAD + BODY + (".B....B...", ".D....D...")
SWING_UP = ("..HHHH..gG", ".HHHHHH.GG", ".hhhhhh.W.", "..FFFF..W.", "..BBBBFF..", ".FBBBB....", "..BBBB....",
            "..B..B....", "..D..D....")
SWING_DOWN = HEAD + ("..BBBB....", ".FBBBBFWWG", "..BBBB..gG", "..B..B....", "..D..D....")


def builder(cr, x, y, frame, flip=False):
    """Строитель: ноги на y (низ спрайта)."""
    rows = {"stand": STAND, "walk": WALK, "up": SWING_UP, "down": SWING_DOWN}[frame]
    sprite(cr, x, y - len(rows), rows, PAL, flip)


BOLT = (".....LL..", "....LW...", "...LA....", "..LA.....", ".LAAAAA..", "....AAD..", "...AAD...",
        "..AAD....", "..AD.....", ".AD......", ".D.......")   # молния staticOS, как в start_glyphs.py
SPARK = (".LL", "LA.", "AAD", ".AD", "A..")


def set_energy(acc):
    """Цвет энергии — акцент обоев, но всегда яркий: тёмный акцент на ночном небе не виден."""
    global ENERGY, ENERGY_L, ENERGY_W, ENERGY_D
    lum = 0.3 * acc[0] + 0.59 * acc[1] + 0.11 * acc[2]
    ENERGY = mix(acc, (1, 1, 1), max(0.0, 0.62 - lum))
    ENERGY_L, ENERGY_W, ENERGY_D = mix(ENERGY, (1, 1, 1), 0.3), mix(ENERGY, (1, 1, 1), 0.65), mix(ENERGY, (0, 0, 0), 0.4)


def energy_pal():
    return {"L": ENERGY_L, "W": ENERGY_W, "A": ENERGY, "D": ENERGY_D}


def energy_icon(cr, x, y, s=1):
    """Молния 9×11: значок валюты."""
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    sprite(cr, 0, 0, BOLT, energy_pal())
    cr.restore()


def spark(cr, x, y):
    """Пучок энергии 3×5: в запасе у подножия, в сундуке и в полёте к счёту."""
    sprite(cr, x, y, SPARK, energy_pal())


def medal(cr, x, y, s=1):
    """Медаль 9×12: сколько собеседований уже позади."""
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    box(cr, 2, 0, 2, 4, RED)
    box(cr, 5, 0, 2, 4, OVERALL)
    box(cr, 2, 3, 5, 1, GOLD_D)
    box(cr, 1, 4, 7, 7, GOLD)
    box(cr, 2, 11, 5, 1, GOLD_D)
    box(cr, 0, 5, 9, 5, GOLD)
    box(cr, 3, 5, 3, 1, (1, 1, 0.8))
    box(cr, 8, 6, 1, 4, GOLD_D)
    box(cr, 3, 7, 3, 3, GOLD_D)
    box(cr, 4, 7, 1, 2, GOLD)
    cr.restore()


# Значки ступеней для дорожки, 9×9
ICONS = dict(
    hill=(".........", ".........", "...GGG...", "..GGGGG..", ".GGGGGGG.", "GGGGGGGGG", "EEEEEEEEE", "EEEEEEEEE", "........."),
    base=(".........", ".........", ".........", "SSSSSSSSS", "S...S...S", "SSSSSSSSS", "..S...S..", "SSSSSSSSS", "........."),
    wall_l=("S.S.S.S..", "SSSSSSS..", "S..S..S..", "SSSSSSS..", "..S..S...", "SSSSSSS..", "S..S..S..", "SSSSSSS..", "........."),
    wall_r=("..S.S.S.S", "..SSSSSSS", "..S..S..S", "..SSSSSSS", "...S..S..", "..SSSSSSS", "..S..S..S", "..SSSSSSS", "........."),
    gate=("S.S.S.S.S", "SSSSSSSSS", "SSSSSSSSS", "SS.....SS", "SS.WWW.SS", "SS.WWW.SS", "SS.WWW.SS", "SS.WWW.SS", "........."),
    tower_l=(".S.S.S.S.", ".SSSSSSS.", "..SSSSS..", "..SS.SS..", "..SS.SS..", "..SSSSS..", "..SS.SS..", "..SSSSS..", "........."),
    tower_r=(".S.S.S.S.", ".SSSSSSS.", "..SSSSS..", "..SS.SS..", "..SS.SS..", "..SSSSS..", "..SS.SS..", "..SSSSS..", "........."),
    moat=(".........", ".........", ".LL...LL.", "WWWWWWWWW", "WWWWWWWWW", ".WLLWWLL.", "WWWWWWWWW", "WWWWWWWWW", "........."),
    keep=("S.S.S.S.S", "SSSSSSSSS", "SSSYSYSSS", "SSSSSSSSS", "SSYSSSYSS", "SSYSSSYSS", "SSSSSSSSS", "SSSSSSSSS", "........."),
    merlons=(".........", "SS.SS.SS.", "SS.SS.SS.", "SSSSSSSSS", "SSSSSSSSS", "S..S..S..", "SSSSSSSSS", ".........", "........."),
    flag=("KAAAAAA..", "KAAAAAAA.", "KAAAAAAA.", "KAAAAA...", "K........", "K........", "K........", "K........", "K........"),
    crown=(".........", "Y..Y.Y..Y", "Y..Y.Y..Y", "YY.YYY.YY", "YYYYYYYYY", "YYYRYRYYY", "YYYYYYYYY", "ddddddddd", "........."))


def icon(cr, key, x, y, s, acc, dim=False, land="home"):
    th = B.THEMES[land]
    pal = dict(G=th["grass_l"], E=th["earth"], S=th["stone"], W=WATER if key == "moat" else WOOD, L=WATER_L, Y=GOLD,
               d=GOLD_D, R=RED, A=acc, K=WOOD)
    if land != "home":                         # у земель одна пара башен и одна стена
        key = dict(wall="wall_l", tower="tower_l").get(key, key)
    if dim:
        pal = {k: (0.42, 0.43, 0.5) for k in pal}
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    sprite(cr, 0, 0, ICONS[key], pal)
    cr.restore()


def chest(cr, x, y, opened, acc, glow=0.0):
    """Сундук 20×16 (+6 сверху под открытую крышку); x, y — левый верх корпуса."""
    if opened:
        box(cr, x + 1, y - 7, 18, 6, WOOD_D)
        box(cr, x + 2, y - 6, 16, 4, WOOD)
        box(cr, x + 1, y - 7, 18, 1, GOLD)
        box(cr, x, y - 1, 20, 6, WOOD_D)
        box(cr, x + 2, y, 16, 5, GOLD)
        box(cr, x + 2, y, 16, 5, (1, 1, 0.8), glow)
        for i in range(4):
            spark(cr, x + 3 + i * 4, y - i % 2)
    else:
        box(cr, x, y - 1, 20, 6, WOOD)
        box(cr, x + 1, y - 2, 18, 1, WOOD)
        box(cr, x, y - 1, 20, 1, mix(WOOD, (1, 1, 1), 0.2))
        box(cr, x, y + 4, 20, 1, WOOD_D)
    box(cr, x, y + 5, 20, 10, WOOD)
    box(cr, x, y + 5, 20, 1, WOOD_D)
    box(cr, x, y + 14, 20, 1, WOOD_D)
    top = y + 5 if opened else y - 2
    for gx in (x + 2, x + 16):
        box(cr, gx, top, 2, y + 15 - top, GOLD_D)
        box(cr, gx, top, 1, y + 15 - top, GOLD)
    box(cr, x + 8, y + 3, 4, 5, GOLD)
    box(cr, x + 9, y + 5, 2, 2, HOLE)


def portrait(cr, x, y, s, who, person):
    """Лицо 12×12; Искра — сама молния."""
    if who == "spark":
        energy_icon(cr, x + s // 2, y + s, s)
    else:
        B.portrait(box, sprite, cr, x, y, s, person)


RARE_PAL = (dict(L=rgb("#e4e6ee"), A=rgb("#a4a6b4"), D=rgb("#6a6878")),
            dict(L=rgb("#a8e0ff"), A=rgb("#4aa8e8"), D=rgb("#2a6aa8")),
            dict(L=rgb("#ffe8a0"), A=rgb("#ffb84a"), D=rgb("#c8742a")),
            dict(L=rgb("#f4e4c0"), A=rgb("#d8c090"), D=rgb("#8a6a44")))


def find_icon(cr, index, rarity, x, y, s):
    B.item_icon(sprite, cr, x, y, s, index, rarity, RARE_PAL[rarity])


def mini_castle(cr, land, x, y, built, done, lit, t):
    """Замок на карте: чем больше построено, тем он плотнее; пустая земля — табличка."""
    th = B.THEMES[land]
    if not built:
        if lit:
            box(cr, x + 6, y + 6, 1, 4, WOOD_D)
            box(cr, x + 3, y + 3, 7, 4, WOOD)
            box(cr, x + 3, y + 3, 7, 1, mix(WOOD, (1, 1, 1), 0.25))
        return
    cold = (0.5, 0.5, 0.58)
    pal = {"#": th["stone"] if lit else cold, "A": mix(th["stone"], RED, 0.45) if land != "spire" else B.SEAM,
           "O": GOLD if done or lit else HOLE}
    sprite(cr, x, y, B.MINI[land], pal)
    if done:                                   # достроенная земля светится
        a = 0.5 + 0.5 * math.sin(t * 2.5)
        box(cr, x + 6, y + 8, 1, 2, (1, 1, 1), a)


def part_surface(key, acc, land="home"):
    """Ступень отдельным холстом: и для статичного слоя, и для стройки по рядам."""
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    cr.set_antialias(cairo.ANTIALIAS_NONE)
    for q in rects(key, acc, land):
        lay(cr, q, 0, 0, 1)
    return surf


def part_box(key, acc, land="home"):
    """Ступень: границы (x0, y0, x1, y1) на сетке рисунка."""
    qs = rects(key, acc, land)
    return (min(q[0] for q in qs), min(q[1] for q in qs), max(q[0] + q[2] for q in qs),
            max(q[1] + q[3] for q in qs))


class World:
    """Готовые слои картины для размера холста lw×lh; низ рисунка — на строке floor."""
    def __init__(self, lw, lh, floor, acc, land="home"):
        self.lw, self.lh, self.acc, self.land = lw, lh, acc, land
        self.th = B.THEMES[land]
        self.ax, self.ay = (lw - W) // 2, floor - H
        self.ground = self.ay + TOP + 66            # верх земли вне холма
        self.parts = {}
        self.back, self.front = None, None
        self.key_back, self.key_front = None, None
        self.sky = None
        rnd = random.Random(7)
        self.stars = [(rnd.randrange(lw), rnd.randrange(max(1, self.ground - 34)), rnd.random() * 6.28,
                       rnd.random() < 0.2) for _ in range(lw // 2)]
        self.clouds = [(rnd.randrange(lw), rnd.randrange(4, max(5, self.ground // 2)), rnd.randrange(3),
                        0.6 + rnd.random()) for _ in range(5)]
        if land in ("dunes", "spire"):
            self.clouds = []
        self.trees = self.plant(rnd)
        self.tent_x = max(0, min(3, self.ax - 22))
        self.fire_x = self.tent_x + 22

    def plant(self, rnd):
        """Деревья по бокам: вокруг холма свободно, в широком окне их больше."""
        out = []
        for x in (*range(-2, self.ax - 2, 9), *range(self.ax + W + 2, self.lw + 8, 9)):
            first, second = self.th["flora"]
            out.append((x + rnd.randrange(3), first if rnd.random() < 0.6 else second))
        return out

    def surf(self, key):
        if key not in self.parts:
            self.parts[key] = part_surface(key, self.acc, self.land)
        return self.parts[key]

    def backdrop(self, hour):
        """Небо, светило и горы: по пикселям, поэтому раз в несколько минут."""
        key = int(hour * 12)
        if key == self.key_back:
            return self.back
        self.key_back = key
        sky = self.sky = sky_at(hour)
        lw, lh = self.lw, self.lh
        surf = cairo.ImageSurface(cairo.FORMAT_RGB24, lw, lh)
        data = surf.get_data()
        stride = surf.get_stride()
        fall = max(1, self.ground)
        for y in range(lh):
            t = min(1, y / fall)
            for x in range(lw):
                v = (t + (BAYER[y & 3][x & 3] / 16 - 0.5) / 7) * 2
                v = min(2.0, max(0.0, round(v * 7) / 7))
                c = mix(sky["top"], sky["mid"], v) if v < 1 else mix(sky["mid"], sky["low"], v - 1)
                o = y * stride + x * 4
                data[o], data[o + 1], data[o + 2] = int(c[2] * 255), int(c[1] * 255), int(c[0] * 255)
        surf.mark_dirty()
        cr = cairo.Context(surf)
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        th = self.th
        if th["haze"]:                              # свой воздух у каждой земли
            cr.set_source_rgba(*th["haze"][0], th["haze"][1])
            cr.paint()
        self.orb(cr, hour)
        k = th["rise"]
        self.ridge(cr, int(22 * k), int(9 * k), 0.045, mix(mix(sky["low"], th["far"], 0.5), sky["tint"], sky["shade"] * 0.3),
                   snow=th["peak"])
        self.ridge(cr, int(13 * k), int(6 * k), 0.08, mix(mix(sky["low"], th["near"], 0.72), sky["tint"], sky["shade"]),
                   phase=2.1)
        self.back = surf
        return surf

    def ridge(self, cr, tall, swing, freq, col, phase=0.0, snow=False):
        base = self.ground
        for x in range(self.lw):
            n = math.sin(x * freq + phase) + 0.5 * math.sin(x * freq * 2.3 + phase * 2) + 0.25 * math.sin(x * freq * 5.1)
            h = int(tall + swing * n)
            box(cr, x, base - h, 1, h + 2, col)
            if snow and h > tall + swing * 0.7:
                box(cr, x, base - h, 1, 2 + (x & 1), mix(col, (1, 1, 1), 0.55 - self.sky["shade"] * 0.5))

    def orb(self, cr, hour):
        """Солнце с 6 до 19, луна в остальное время: дуга над горизонтом."""
        day = 6 <= hour < 19
        p = (hour - 6) / 13 if day else ((hour - 19) % 24) / 11
        x = int(self.lw * (0.12 + 0.76 * p))
        y = int(self.ground * 0.72 - math.sin(p * math.pi) * self.ground * 0.62)
        r = 6 if day else 5
        col = rgb("#fff1b0") if day else rgb("#e8e8f4")
        for j in range(-r, r + 1):
            w = int(math.sqrt(r * r - j * j) + 0.5)
            box(cr, x - w, y + j, 2 * w + 1, 1, col)
        if day:
            box(cr, x - r - 2, y, 1, 1, col)
            box(cr, x + r + 2, y, 1, 1, col)
            box(cr, x, y - r - 2, 1, 1, col)
            box(cr, x, y + r + 2, 1, 1, col)
        else:
            box(cr, x - 2, y - 2, 2, 2, rgb("#c2c3d6"))
            box(cr, x + 1, y + 1, 2, 1, rgb("#c2c3d6"))
            box(cr, x - 1, y + 2, 1, 1, rgb("#c2c3d6"))

    def tree(self, cr, x, kind):
        g = self.ground
        if kind not in ("pine", "leaf"):
            B.plant(box, cr, x, g, kind)
        elif kind == "pine":
            box(cr, x + 3, g - 3, 2, 3, TRUNK)
            for i, (y, w) in enumerate(((g - 8, 8), (g - 12, 6), (g - 16, 4))):
                for k in range(5):
                    box(cr, x + 4 - (w - k) // 2 - 0, y + k - 1, w - k, 1, PINE if k % 2 or i else PINE_D)
        else:
            box(cr, x + 3, g - 5, 2, 5, TRUNK)
            box(cr, x, g - 12, 8, 7, LEAF)
            box(cr, x + 1, g - 14, 6, 2, LEAF)
            box(cr, x + 1, g - 13, 3, 2, LEAF_L)
            box(cr, x, g - 7, 8, 2, LEAF_D)

    def tent(self, cr, x):
        g = self.ground
        for j in range(13):
            w = 3 + j * 2
            box(cr, x + 9 - w // 2, g - 13 + j, w, 1, mix(self.acc, (1, 1, 1), 0.12 if j % 3 else 0.28))
        for j in range(7):
            box(cr, x + 8 - j // 2, g - 7 + j, 2 + j, 1, HOLE)
        box(cr, x + 8, g - 15, 2, 3, WOOD_D)

    def pile(self, cr, count):
        """Запас энергии у подножия: растёт вместе со счётом, видно, что накоплено."""
        n = min(18, (count + 9) // 10)
        x0, y0 = self.ax + 6, self.ay + 87
        row, left = 0, n
        while left > 0 and row < 3:
            cap = 7 - row
            for i in range(min(cap, left)):
                spark(cr, x0 + i * 7 + row * 3, y0 - row * 5)
            left -= cap
            row += 1

    def foreground(self, hour, built, balance, skip=None):
        """Земля, деревья, лагерь и готовые ступени; затемнение суток — одним мазком поверх."""
        key = (int(hour * 12), tuple(sorted(built)), balance // 10, skip)
        if key == self.key_front:
            return self.front
        self.key_front = key
        sky = sky_at(hour)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.lw, self.lh)
        cr = cairo.Context(surf)
        cr.set_antialias(cairo.ANTIALIAS_NONE)
        g = self.ground
        th = self.th
        for x, kind in self.trees:
            if not -8 < x - self.ax < W:
                self.tree(cr, x, kind)
        box(cr, 0, g, self.lw, self.lh - g, th["earth"])
        box(cr, 0, g - 1, self.lw, 2, th["grass"])
        box(cr, 0, g + 1, self.lw, 1, th["grass_d"])
        for x in range(1, self.lw, 7):
            box(cr, x, g - 2 - x % 2, 1, 1 + x % 2, th["grass_l"])
            box(cr, x + 3, g + 5 + x % 9, 3, 1, th["earth_d"])
            box(cr, x + 1, g + 11 + x % 5, 2, 1, th["earth_d"])
        self.tent(cr, self.tent_x)
        cr.save()
        cr.translate(self.ax, self.ay)
        cr.push_group()                             # чертёж: что ещё встанет на этом месте
        for k in order(self.land):
            if k not in built and k != skip:
                cr.set_source_surface(self.surf(k), 0, 0)
                cr.paint()
        cr.pop_group_to_source()
        cr.paint_with_alpha(0.07)
        for k in order(self.land):
            if k in built and (k != "flag" or self.land in B.LAMPS) and k != skip:
                cr.set_source_surface(self.surf(k), 0, 0)
                cr.paint()
        cr.restore()
        if not {"hill", "base"} & set(built):
            self.sign(cr)
        if sky["shade"] > 0:
            cr.set_operator(cairo.OPERATOR_ATOP)
            cr.set_source_rgba(sky["tint"][0], sky["tint"][1], sky["tint"][2], sky["shade"])
            cr.paint()
            cr.set_operator(cairo.OPERATOR_OVER)
        self.pile(cr, balance)                       # энергия светится сама, ночь её не гасит
        self.front = surf
        return surf

    def sign(self, cr):
        """Табличка на пустом месте: тут будет замок."""
        x, g = self.ax + W // 2 - 8, self.ground
        box(cr, x + 7, g - 8, 2, 8, WOOD_D)
        box(cr, x, g - 18, 16, 11, WOOD)
        box(cr, x, g - 18, 16, 1, mix(WOOD, (1, 1, 1), 0.25))
        box(cr, x, g - 8, 16, 1, WOOD_D)
        sprite(cr, x + 3, g - 16, ("#.#.#.#.#", "#########", "###...###", "###...###", "###...###", "###...###"),
               {"#": HOLE})

    def stars_at(self, cr, t, sky):
        if sky["stars"] <= 0.02:
            return
        for x, y, ph, big in self.stars:
            a = sky["stars"] * (0.35 + 0.65 * (0.5 + 0.5 * math.sin(t * 1.7 + ph)))
            box(cr, x, y, 1, 1, (1, 1, 1), a)
            if big and a > 0.8:
                box(cr, x - 1, y, 3, 1, (1, 1, 1), a * 0.5)
                box(cr, x, y - 1, 1, 3, (1, 1, 1), a * 0.5)

    def clouds_at(self, cr, t, sky):
        col = mix((1, 1, 1), sky["top"], sky["shade"] * 0.9 + 0.08)
        for x0, y, kind, speed in self.clouds:
            x = int((x0 + t * speed * 1.6) % (self.lw + 40)) - 30
            w = 18 + kind * 6
            box(cr, x, y + 2, w, 3, col, 0.9)
            box(cr, x + 3, y, w - 9, 2, col, 0.9)
            box(cr, x + 7, y - 2, 6 + kind, 2, col, 0.9)
            box(cr, x + 1, y + 5, w - 3, 1, mix(col, sky["mid"], 0.4), 0.9)

    def birds_at(self, cr, t, sky):
        if sky["stars"] > 0.3 or self.land in ("dunes", "pass", "spire"):
            return
        ink = rgb("#20263a")
        for i in range(3):
            x = int((t * (5 + i) + i * 57) % (self.lw + 60)) - 30
            y = 14 + i * 7 + int(2 * math.sin(t * 0.7 + i))
            flap = int(t * 5 + i) % 2
            box(cr, x, y, 1, 1, ink)
            box(cr, x - 2, y - flap, 2, 1, ink)
            box(cr, x + 1, y - flap, 2, 1, ink)

    def fireflies(self, cr, t, sky):
        if sky["stars"] < 0.4 or self.land not in ("home", "forest"):
            return
        for i in range(7):
            x = self.ax + (i * 37) % 120 + int(6 * math.sin(t * 0.5 + i * 2))
            y = self.ground - 8 - (i * 5) % 12 + int(3 * math.cos(t * 0.8 + i))
            if math.sin(t * 2 + i * 1.7) > 0:
                box(cr, x, y, 1, 1, rgb("#e8f77a"))

    def weather(self, cr, t, sky):
        B.weather(box, cr, t, self.lw, self.lh, self.th["weather"], sky)

    def water(self, cr, t, sky):
        y = self.ay + TOP + 71
        col = mix(WATER_L, sky["tint"], sky["shade"])
        if self.land == "bay":                       # у бухты вода вместо земли, всегда
            room = max(1, self.lh - self.ground - 3)
            for i in range(self.lw // 6):
                box(cr, (i * 13 + int(t * (3 + i % 3))) % self.lw, self.ground + 3 + i * 7 % room, 3 + i % 4, 1, col, 0.7)
            return
        for i in range(12):
            x = (9 + i * 9 + int(t * 5)) % 104 + 8
            if not 50 < x < 69:
                box(cr, self.ax + x, y + i % 2, 3 + i % 3, 1, col)

    def flags(self, cr, t, sky):
        """Знамёна: столбики ткани качаются волной. У маяка и Шпиля вместо них свет."""
        if self.land in B.LAMPS:
            self.lamp(cr, t)
            return
        cloth = self.acc if self.land == "home" else mix(B.CLOTH[self.land], self.acc, 0.25)
        acc, wood = mix(cloth, sky["tint"], sky["shade"]), mix(WOOD_D, sky["tint"], sky["shade"])
        for fx, fy, tall, w, h in B.FLAGS[self.land]:
            x0, y0 = self.ax + fx, self.ay + TOP + fy
            box(cr, x0, y0, 1, tall, wood)
            for i in range(w):
                d = round(math.sin(t * 5 - i * 0.7) * min(1.4, 0.3 + i * 0.2))
                box(cr, x0 + 1 + i, y0 + d, 1, h, acc)
                box(cr, x0 + 1 + i, y0 + d, 1, 1, mix(acc, (1, 1, 1), 0.3))
                box(cr, x0 + 1 + i, y0 + d + h - 1, 1, 1, mix(acc, (0, 0, 0), 0.3))

    def lamp(self, cr, t):
        lx, ly = B.LAMP_AT[self.land]
        x0, y0 = self.ax + lx, self.ay + TOP + ly
        for r, al in ((17, 0.05), (11, 0.08), (6, 0.14)):
            for j in range(-r, r + 1):
                w = int(math.sqrt(r * r - j * j))
                box(cr, x0 - w, y0 + j, 2 * w, 1, GOLD, al * (0.8 + 0.2 * math.sin(t * 2.2)))
        if self.land == "bay":                       # луч ходит над морем
            reach = self.lw * 0.7 * math.cos(t * 0.6)
            cr.set_source_rgba(1, 0.95, 0.7, 0.13)
            cr.move_to(x0, y0)
            cr.line_to(x0 + reach, y0 - 9)
            cr.line_to(x0 + reach, y0 + 9)
            cr.close_path()
            cr.fill()

    def lights(self, cr, t, sky, built):
        """Окна донжона ночью светятся поверх затемнения."""
        a = min(1, sky["stars"] * 1.3)
        if a < 0.05 or "keep" not in built:
            return
        for x, y, w, h in B.WINDOWS[self.land]:
            xx, yy = self.ax + x, self.ay + TOP + y
            box(cr, xx - 1, yy - 1, w + 2, h + 2, GOLD, a * 0.18)
            box(cr, xx, yy, w, h, GOLD, a * (0.85 + 0.15 * math.sin(t * 3 + x)))

    def camp(self, cr, t, x, sky):
        """Костёр: языки меняются, ночью вокруг него круг света."""
        g = self.ground
        if sky["stars"] > 0.1:
            flick = int(t * 6) % 2
            for r, al in ((19 + flick, 0.035), (13, 0.05), (8 + flick, 0.08)):
                for j in range(r):
                    w = int(math.sqrt(r * r - j * j))
                    box(cr, x + 2 - w, g - j, 2 * w, 1, FIRE[1], al * min(1, sky["stars"] * 1.4))
        box(cr, x - 2, g - 1, 8, 1, WOOD_D)
        box(cr, x - 1, g - 2, 6, 1, WOOD)
        n = int(t * 8)
        for i, tall in enumerate((3, 5, 6, 4)):
            h = tall - (n + i * 3) % 3
            box(cr, x + i, g - 2 - h, 1, h, FIRE[(n + i) % 2 + (0 if i in (1, 2) else 1)])
        box(cr, x + 1, g - 4, 2, 2, FIRE[0])
        for i in range(4):
            p = (t * 0.5 + i * 0.25) % 1
            box(cr, x + 2 + int(math.sin(p * 6 + i) * 2 * p), g - 8 - int(p * 18), 1 + (i & 1), 1, (0.75, 0.75, 0.8), 0.4 * (1 - p))

