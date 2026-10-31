#!/usr/bin/env python3
"""Земли Замка (31.10.2026): постройки, природа, погода, карта, портреты и находки.

Модуль ниже castle_art.py и не зависит от него: тот же приём, что у дома, сетка 120×92, y от верха
рисунка, деталь — прямоугольники через r(x, y, w, h, цвет). numpy нужен только карте, поэтому
импортируется внутри world_map: виджет на обоях его не грузит."""
import math

W, H = 120, 92


def rgb(h):
    return tuple(int(h[i:i + 2], 16) / 255 for i in (1, 3, 5))


def mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


HOLE, GOLD, GOLD_D = rgb("#17161d"), rgb("#ffd166"), rgb("#d99a2b")
WHITE = (1, 1, 1)


def theme(grass, grass_l, grass_d, earth, earth_d, far, near, flora, weather=None, haze=None, peak=False,
          stone=None, rise=1.0):
    return dict(grass=rgb(grass), grass_l=rgb(grass_l), grass_d=rgb(grass_d), earth=rgb(earth), earth_d=rgb(earth_d),
                far=rgb(far), near=rgb(near), flora=flora, weather=weather, haze=haze and (rgb(haze[0]), haze[1]),
                peak=peak, stone=rgb(stone or "#b4b2bf"), rise=rise)


THEMES = dict(
    home=theme("#568f48", "#74b35c", "#3e6f3b", "#6c5140", "#533e31", "#4a5a86", "#2f5a58", ("pine", "leaf"), peak=True),
    forest=theme("#3f7a44", "#5a9a52", "#2c5a36", "#4e3d30", "#3a2c24", "#2f5a4e", "#1f4a3a", ("spruce", "pine"), "leaves",
                 ("#2f6a4d", 0.18), stone="#9c7042"),
    steppe=theme("#a39a4c", "#c2b862", "#7f7a3c", "#7a6444", "#5c4a34", "#a08a5c", "#8a7a48", ("tuft", "boulder"), "wind",
                 ("#e0b870", 0.12), stone="#d8c49a", rise=0.5),
    dunes=theme("#d8b468", "#ecd08a", "#b8924c", "#b8924c", "#95733a", "#d0a860", "#b88c48", ("cactus", "boulder"), "sand",
                ("#ff9a4c", 0.2), stone="#d8a868", rise=0.7),
    bay=theme("#6a7a78", "#8a9a96", "#4e5c5a", "#2f5a80", "#3f7aa4", "#4a6480", "#35506a", ("boulder", "boulder"), None,
              ("#6a8aa8", 0.16), stone="#c8ccd4", rise=0.45),
    pass_=theme("#dfe8f2", "#ffffff", "#a8bcd0", "#7f90a6", "#5f7088", "#8fa8c8", "#6a84a8", ("snowpine", "boulder"), "snow",
                ("#c8dcf0", 0.22), peak=True, stone="#e8f0f8", rise=1.35),
    spire=theme("#39334a", "#4e4664", "#262232", "#262232", "#1a1724", "#2e2840", "#1e1a2c", ("deadtree", "boulder"), "ash",
                ("#2a1f4a", 0.72), stone="#6a6084", rise=1.2),
)
THEMES["pass"] = THEMES.pop("pass_")

ORDER = ("hill", "keep", "tower", "wall", "gate", "flag")
# места полотнищ: (x, y, высота древка, ширина, высота ткани); у дома — знамёна замка
FLAGS = dict(home=((60, 0, 15, 13, 7), (27, 16, 11, 6, 4), (93, 16, 11, 6, 4)),
             forest=((60, -6, 15, 13, 7), (15, 3, 10, 6, 4), (105, 3, 10, 6, 4)),
             steppe=((60, -7, 24, 14, 8),),
             dunes=((60, -3, 12, 12, 6), (12, 9, 11, 7, 4), (108, 9, 11, 7, 4)),
             bay=(), spire=(),
             **{"pass": ((60, -8, 11, 12, 6), (20, -8, 11, 7, 4), (100, -8, 11, 7, 4))})
LAMPS = ("bay", "spire")                   # «знамя» этих земель — свет, оно стоит на месте
LAMP_AT = dict(bay=(60, 1), spire=(60, -4))
WINDOWS = dict(home=((48, 24, 3, 6), (69, 24, 3, 6), (58, 21, 4, 7)),
               forest=((46, 38, 4, 5), (70, 38, 4, 5), (58, 24, 4, 5)),
               steppe=((58, 49, 4, 9),),
               dunes=((42, 42, 3, 5), (75, 42, 3, 5), (58, 42, 4, 6)),
               bay=((58, 20, 3, 4), (58, 36, 3, 4)),
               spire=((58, 20, 2, 4), (58, 34, 3, 4), (58, 46, 3, 4)),
               **{"pass": ((48, 22, 3, 6), (69, 22, 3, 6), (58, 18, 4, 7))})


def stones(r, x, y, w, h, c, l, s, m):
    """Кладка вразбежку, тот же рисунок, что у дома, в цветах земли."""
    r(x, y, w, h, c)
    for j in range(2, h, 3):
        r(x, y + j, w, 1, s)
        for i in range((j // 3 % 2) * 3, w, 6):
            r(x + i, y + j - 2, 1, 2, s)
    r(x, y, w, 1, l)
    r(x, y, 1, h, l)
    r(x + w - 1, y, 1, h, m)
    r(x, y + h - 1, w, 1, m)


def mound(r, land, spots=True):
    th = THEMES[land]
    for y, (a, b) in enumerate(((20, 100), (15, 105), (10, 110), (6, 114), (3, 117), (1, 119))):
        r(a, 60 + y, b - a, 1, th["grass_l"] if y < 2 else th["grass"])
    r(0, 66, W, 18, th["earth"])
    r(0, 66, W, 2, th["grass_d"])
    for x in range(4, W, 9):
        r(x, 68, 3, 1, th["grass_d"])
        r(x + 4, 73 + x % 5, 2, 1, th["earth_d"])
        r(x + 1, 79 - x % 3, 3, 1, th["earth_d"])
    if spots:
        for x in range(9, 110, 13):
            r(x, 62, 1, 1, th["grass_d"])
            r(x + 5, 64, 2, 1, th["grass_l"])


def roof(r, cx, y, half, h, col, light):
    for j in range(h):
        w = 1 + 2 * half * j // max(1, h - 1)
        r(cx - w // 2, y + j, w, 1, col)
        r(cx - w // 2, y + j, max(1, w // 4), 1, light)


def dome(r, cx, base, rx, ry, col, light, dark):
    for j in range(ry):
        w = max(1, int(rx * math.sqrt(1 - ((ry - j) / ry) ** 2)))
        side = max(1, w // 3)
        r(cx - w, base - ry + j, 2 * w, 1, col)
        r(cx - w, base - ry + j, side, 1, light)
        r(cx + w - side // 2 - 1, base - ry + j, side // 2 + 1, 1, dark)


def pole(r, x, y, tall, w, h, cloth):
    r(x, y, 1, tall, rgb("#6b4524"))
    r(x + 1, y, w, h, cloth)
    r(x + 1, y, w, 1, mix(cloth, WHITE, 0.3))
    r(x + 1, y + h - 1, w, 1, mix(cloth, (0, 0, 0), 0.3))


def poles(r, land, cloth):
    for q in FLAGS[land]:
        pole(r, *q, cloth)


# ── Шепчущий лес: острог из брёвен ───────────────────────────────────────────
LOG, LOG_L, LOG_D = rgb("#7a5230"), rgb("#9c7042"), rgb("#553820")
SHINGLE, SHINGLE_L = rgb("#3f5a3c"), rgb("#5e7c52")


def logs(r, x, y, w, h):
    for i in range(0, w, 3):
        top = y + (1 if i % 6 else 0)
        r(x + i + 1, top - 2, 1, 2, LOG_L)
        r(x + i, top, 3, h - (top - y), LOG)
        r(x + i, top, 1, h - (top - y), LOG_L)
        r(x + i + 2, top, 1, h - (top - y), LOG_D)
    r(x, y + h // 3, w, 1, LOG_D)
    r(x, y + 2 * h // 3, w, 1, LOG_D)


def forest_hill(r, acc):
    mound(r, "forest")
    for x in (24, 92):
        r(x, 58, 5, 2, LOG)
        r(x, 58, 5, 1, LOG_L)
    for x in (38, 76, 84):
        r(x + 1, 58, 1, 2, rgb("#e8dcc8"))
        r(x, 57, 3, 1, rgb("#c0524f"))


def forest_wall(r, acc):
    logs(r, 16, 38, 34, 22)
    logs(r, 70, 38, 34, 22)


def forest_gate(r, acc):
    logs(r, 50, 32, 20, 28)
    r(54, 42, 12, 18, HOLE)
    r(56, 42, 1, 18, LOG_D)
    r(63, 42, 1, 18, LOG_D)
    r(54, 50, 12, 1, LOG_D)
    r(47, 29, 26, 3, LOG_D)
    r(47, 29, 26, 1, LOG_L)


def forest_tower(r, acc):
    for x in (8, 98):
        r(x + 1, 34, 2, 26, LOG_D)
        r(x + 11, 34, 2, 26, LOG_D)
        for j in range(0, 18, 6):
            r(x + 2, 38 + j, 11, 1, LOG_D)
        logs(r, x - 1, 24, 16, 10)
        r(x + 4, 27, 6, 4, HOLE)
        roof(r, x + 7, 13, 10, 11, SHINGLE, SHINGLE_L)


def forest_keep(r, acc):
    for y in range(30, 60, 3):
        r(38, y, 44, 2, LOG)
        r(38, y, 44, 1, LOG_L)
        r(38, y + 2, 44, 1, LOG_D)
    roof(r, 60, 8, 26, 22, SHINGLE, SHINGLE_L)
    r(46, 38, 4, 5, GOLD)
    r(70, 38, 4, 5, GOLD)
    r(58, 24, 4, 5, GOLD)


# ── Степь Ветров: юрты ───────────────────────────────────────────────────────
FELT, FELT_L, FELT_D = rgb("#e4d8c0"), rgb("#f4ecdc"), rgb("#b8aa90")
OCHRE, CRIMSON, TEAL = rgb("#c8922e"), rgb("#a83a2e"), rgb("#2f8a84")
TIMBER, TIMBER_L = rgb("#8a4a24"), rgb("#b06a34")


def yurt(r, cx, base, rx, ry):
    low = ry * 2 // 5
    r(cx - rx, base - low, 2 * rx, low, FELT)
    r(cx - rx, base - low, 3, low, FELT_L)
    r(cx + rx - 3, base - low, 3, low, FELT_D)
    dome(r, cx, base - low, rx, ry - low, FELT, FELT_L, FELT_D)
    r(cx - rx, base - low, 2 * rx, 2, CRIMSON)
    for x in range(cx - rx + 2, cx + rx - 1, 4):
        r(x, base - low, 2, 1, OCHRE)
    r(cx - rx // 3, base - ry - 1, 2 * (rx // 3), 2, TIMBER)
    d = max(2, rx // 6)
    r(cx - d, base - low + 3, 2 * d, low - 3, TIMBER)
    r(cx - d + 1, base - low + 4, 2 * d - 2, low - 4, TIMBER_L)


def steppe_hill(r, acc):
    mound(r, "steppe")
    for x, y in ((26, 58), (34, 59), (86, 59), (94, 58)):
        r(x, y, 4, 2, rgb("#8a8678"))
        r(x, y, 4, 1, rgb("#b0ac9c"))


def lattice(r, x, y, w, h):
    for i in range(0, w + h, 6):
        for j in range(h):
            for p in (i - j, i + j - h):
                if 0 <= p < w:
                    r(x + p, y + j, 1, 1, TIMBER_L if p % 2 else TIMBER)
    r(x, y, w, 1, TIMBER)
    r(x, y + h - 1, w, 1, TIMBER)


def steppe_wall(r, acc):
    lattice(r, 8, 48, 30, 12)
    lattice(r, 82, 48, 30, 12)
    for x in (10, 36, 84, 110):
        r(x, 44, 2, 16, TIMBER)
        r(x - 1, 44, 4, 1, TIMBER_L)


def steppe_gate(r, acc):
    for x in (44, 73):
        r(x, 30, 3, 30, TIMBER)
        r(x, 30, 1, 30, TIMBER_L)
    r(42, 28, 36, 3, TIMBER)
    r(46, 25, 28, 3, CRIMSON)
    r(52, 22, 16, 3, TIMBER)
    for x in range(48, 72, 6):
        r(x, 26, 2, 1, OCHRE)
    r(59, 19, 2, 3, OCHRE)


def steppe_tower(r, acc):
    yurt(r, 24, 60, 13, 20)
    yurt(r, 96, 60, 13, 20)


def steppe_keep(r, acc):
    yurt(r, 60, 60, 31, 42)
    for x in (37, 47, 73, 83):
        r(x, 36, 1, 8, FELT_D)
    r(52, 15, 16, 1, OCHRE)


# ── Стеклянные дюны: город-оазис ─────────────────────────────────────────────
MUD, MUD_L, MUD_S, MUD_D = rgb("#c89860"), rgb("#e4bc84"), rgb("#a87c48"), rgb("#8a6038")
TILE, TILE_L, TILE_D = rgb("#2f8fb0"), rgb("#7cd8e8"), rgb("#1f6480")
PALM, PALM_L = rgb("#3e8a54"), rgb("#62b070")


def palm(r, x, y):
    for j in range(10):
        r(x + j // 4, y + j, 2, 1, rgb("#8a6038"))
    for k in range(5):
        r(x - 6 + k, y - 1 + k // 2, 3, 1, PALM)
        r(x + 3 + k, y + (4 - k) // 2 - 1, 3, 1, PALM_L)
        r(x - 2, y - 3 + k // 2, 1, 2, PALM)
    r(x - 3, y - 2, 8, 1, PALM_L)


def dunes_hill(r, acc):
    mound(r, "dunes", False)
    r(28, 62, 24, 3, rgb("#3b8aad"))
    r(30, 62, 20, 1, rgb("#74c4e0"))
    r(76, 63, 14, 2, rgb("#3b8aad"))
    palm(r, 22, 50)
    palm(r, 94, 50)


def dunes_wall(r, acc):
    for x0, w in ((14, 36), (70, 36)):
        stones(r, x0, 42, w, 18, MUD, MUD_L, MUD_S, MUD_D)
        for x in range(x0, x0 + w - 2, 6):
            r(x, 40, 3, 2, MUD)
            r(x, 40, 3, 1, MUD_L)
        r(x0 + 2, 46, w - 4, 1, TILE)


def dunes_gate(r, acc):
    stones(r, 50, 30, 20, 30, MUD, MUD_L, MUD_S, MUD_D)
    r(54, 42, 12, 18, TILE)
    r(56, 40, 8, 2, TILE)
    r(58, 38, 4, 2, TILE)
    r(55, 43, 10, 17, HOLE)
    r(57, 41, 6, 2, HOLE)
    r(59, 39, 2, 2, HOLE)
    r(52, 33, 16, 2, TILE_L)


def dunes_tower(r, acc):
    for x in (6, 102):
        stones(r, x, 22, 12, 38, MUD, MUD_L, MUD_S, MUD_D)
        r(x - 1, 20, 14, 2, MUD_L)
        for sx in (x + 2, x + 5, x + 8):
            r(sx, 24, 2, 8, HOLE)
        r(x, 36, 12, 1, TILE)


def dunes_keep(r, acc):
    stones(r, 34, 34, 52, 22, MUD, MUD_L, MUD_S, MUD_D)
    r(34, 33, 52, 1, MUD_L)
    dome(r, 60, 34, 20, 24, TILE, TILE_L, TILE_D)
    dome(r, 40, 34, 6, 6, TILE, TILE_L, TILE_D)
    dome(r, 80, 34, 6, 6, TILE, TILE_L, TILE_D)
    for x, w in ((42, 3), (75, 3), (58, 4)):
        r(x, 42, w, 5, GOLD)
        r(x, 41, w, 1, TILE_L)


# ── Бухта Молчания: маяк на скале ────────────────────────────────────────────
ROCK, ROCK_L, ROCK_D = rgb("#3e4650"), rgb("#5c6672"), rgb("#2a3038")
LIME, LIME_D = rgb("#e8e8e4"), rgb("#b8bcc0")
RED_B, RED_D = rgb("#b83a34"), rgb("#8a2a28")
PIER, PIER_D = rgb("#7a5a3c"), rgb("#54402c")


def bay_hill(r, acc):
    mound(r, "bay", False)
    for x, w, y in ((22, 12, 56), (40, 30, 54), (74, 16, 56), (30, 14, 58)):
        r(x, y, w, 60 - y, ROCK)
        r(x, y, w, 1, ROCK_L)
        r(x + w - 2, y, 2, 60 - y, ROCK_D)


def bay_wall(r, acc):
    stones(r, 0, 60, 24, 8, *(rgb(c) for c in ("#7a8490", "#a0aab4", "#5c6672", "#4a525c")))
    stones(r, 96, 60, 24, 8, *(rgb(c) for c in ("#7a8490", "#a0aab4", "#5c6672", "#4a525c")))
    for x in (6, 16, 102, 112):
        r(x, 57, 3, 3, ROCK_L)


def bay_gate(r, acc):
    r(66, 64, 52, 3, PIER)
    r(66, 64, 52, 1, rgb("#a07a54"))
    for x in range(70, 118, 10):
        r(x, 67, 2, 10, PIER_D)
    r(98, 58, 14, 2, rgb("#8a5a3c"))
    r(100, 60, 10, 2, rgb("#6a4228"))
    r(104, 48, 1, 10, PIER_D)
    r(105, 49, 6, 7, LIME)


def bay_tower(r, acc):
    stones(r, 76, 42, 26, 16, LIME, WHITE, LIME_D, rgb("#90949a"))
    roof(r, 89, 29, 16, 13, RED_B, rgb("#d85a50"))
    r(82, 47, 4, 5, GOLD)
    r(92, 47, 5, 11, PIER_D)
    r(96, 31, 3, 7, ROCK_D)


def bay_keep(r, acc):
    for y in range(8, 56):
        half = 6 + (y - 8) * 6 // 48
        col = RED_B if (y - 8) // 10 % 2 else LIME
        r(60 - half, y, 2 * half, 1, col)
        r(60 - half, y, 2, 1, mix(col, WHITE, 0.4))
        r(60 + half - 2, y, 2, 1, mix(col, (0, 0, 0), 0.25))
    r(50, 6, 20, 2, ROCK_D)
    r(50, 6, 20, 1, ROCK_L)
    r(57, 48, 6, 8, PIER_D)
    r(58, 20, 3, 4, GOLD)
    r(58, 36, 3, 4, GOLD)


def bay_flag(r, acc):
    r(53, -1, 14, 7, rgb("#9cc4d8"))
    for x in (53, 58, 62, 66):
        r(x, -1, 1, 7, ROCK_D)
    r(58, 1, 4, 4, GOLD)
    dome(r, 60, -1, 8, 4, RED_B, rgb("#d85a50"), RED_D)


# ── Ледяной перевал: цитадель ────────────────────────────────────────────────
ICE, ICE_L, ICE_S, ICE_D = rgb("#7f94b0"), rgb("#b0c4d8"), rgb("#5f7490"), rgb("#4a5c78")
SNOW, GLINT = rgb("#f0f6fc"), rgb("#9cdcf0")


def snowcap(r, x, y, w):
    r(x, y, w, 2, SNOW)
    for i in range(1, w, 5):
        r(x + i, y + 2, 2, 1 + i % 3, SNOW)


def pass_hill(r, acc):
    mound(r, "pass")
    for x in (14, 34, 82, 100):
        r(x, 56, 2, 4, GLINT)
        r(x + 2, 58, 2, 2, GLINT)


def pass_wall(r, acc):
    stones(r, 18, 38, 84, 20, ICE, ICE_L, ICE_S, ICE_D)
    snowcap(r, 18, 36, 84)


def pass_gate(r, acc):
    stones(r, 50, 30, 20, 30, ICE, ICE_L, ICE_S, ICE_D)
    snowcap(r, 49, 28, 22)
    r(54, 42, 12, 18, HOLE)
    for x in (55, 58, 61, 64):
        r(x, 42, 1, 18, rgb("#8a93a6"))
    for y in (46, 50, 54):
        r(54, y, 12, 1, rgb("#8a93a6"))


def pass_tower(r, acc):
    for x in (14, 94):
        stones(r, x, 14, 12, 44, ICE, ICE_L, ICE_S, ICE_D)
        roof(r, x + 6, 3, 8, 11, SNOW, WHITE)
        r(x + 5, 22, 2, 5, GLINT)
        r(x + 5, 34, 2, 5, GLINT)


def pass_keep(r, acc):
    stones(r, 42, 14, 36, 26, ICE, ICE_L, ICE_S, ICE_D)
    roof(r, 60, 3, 20, 11, SNOW, WHITE)
    for q in ((48, 22, 3, 6), (69, 22, 3, 6), (58, 18, 4, 7)):
        r(*q, GOLD)


# ── Шпиль Морока ─────────────────────────────────────────────────────────────
OBS, OBS_L, OBS_D, SEAM = rgb("#1f1c2c"), rgb("#3e3858"), rgb("#12101a"), rgb("#8f6fe0")


def spire_hill(r, acc):
    mound(r, "spire", False)
    for x, y in ((18, 69), (44, 74), (70, 70), (100, 76)):
        for i in range(8):
            r(x + i, y + (i * 3) % 4, 1, 1, SEAM)


def spire_wall(r, acc):
    stones(r, 20, 42, 80, 18, OBS, OBS_L, OBS_D, OBS_D)
    for x in range(24, 98, 12):
        r(x, 44, 1, 6 + x % 7, SEAM)
    r(20, 40, 80, 2, OBS_D)


def spire_gate(r, acc):
    stones(r, 50, 34, 20, 26, OBS, OBS_L, OBS_D, OBS_D)
    r(54, 42, 12, 18, SEAM)
    r(56, 44, 8, 16, mix(SEAM, WHITE, 0.45))
    r(58, 46, 4, 14, WHITE)


def spire_tower(r, acc):
    for cx in (28, 92):
        roof(r, cx, 8, 7, 52, OBS, OBS_L)
        for y in range(16, 54, 11):
            r(cx - 1, y, 2, 3, SEAM)


def spire_keep(r, acc):
    roof(r, 60, 4, 15, 56, OBS, OBS_L)
    for x, y, w in ((58, 2, 2), (61, 1, 1), (56, 4, 1), (63, 3, 1)):       # обломанный верх: её не достроили
        r(x, y, w, 3, OBS)
    for y in range(12, 58, 3):
        r(60 + (y // 3 % 4) * 2 - 3, y, 2, 1, SEAM)
    for q in ((58, 20, 2, 4), (58, 34, 3, 4), (58, 46, 3, 4)):
        r(*q, GOLD)


def spire_flag(r, acc):
    r(58, 0, 4, 4, ROCK_D)
    r(56, -5, 8, 5, GOLD_D)
    r(57, -4, 6, 3, GOLD)
    r(58, -4, 4, 2, WHITE)
    r(55, -6, 10, 1, GOLD_D)


PARTS = dict(
    forest=dict(hill=forest_hill, wall=forest_wall, gate=forest_gate, tower=forest_tower, keep=forest_keep),
    steppe=dict(hill=steppe_hill, wall=steppe_wall, gate=steppe_gate, tower=steppe_tower, keep=steppe_keep),
    dunes=dict(hill=dunes_hill, wall=dunes_wall, gate=dunes_gate, tower=dunes_tower, keep=dunes_keep),
    bay=dict(hill=bay_hill, wall=bay_wall, gate=bay_gate, tower=bay_tower, keep=bay_keep, flag=bay_flag),
    spire=dict(hill=spire_hill, wall=spire_wall, gate=spire_gate, tower=spire_tower, keep=spire_keep, flag=spire_flag),
    **{"pass": dict(hill=pass_hill, wall=pass_wall, gate=pass_gate, tower=pass_tower, keep=pass_keep)})
CLOTH = dict(forest=rgb("#3f9a54"), steppe=rgb("#c8922e"), dunes=rgb("#2f8fb0"), **{"pass": rgb("#d8e8f8")})


def rects(land, key, acc, top):
    """Деталь земли списком (x, y, w, h, цвет), как castle_art.rects."""
    out = []

    def r(x, y, w, h, col):
        out.append((x, y + top, w, h, col))
    fn = PARTS[land].get(key)
    if fn:
        fn(r, acc)
    else:
        poles(r, land, mix(CLOTH.get(land, acc), acc, 0.25))
    return out


# ── природа ──────────────────────────────────────────────────────────────────
def plant(box, cr, x, g, kind):
    if kind == "spruce":
        box(cr, x + 3, g - 3, 2, 3, rgb("#4a3424"))
        for j, (y, w) in enumerate(((g - 7, 10), (g - 12, 8), (g - 16, 6), (g - 20, 3))):
            for k in range(5):
                box(cr, x + 4 - (w - k) // 2, y + k - 2, w - k, 1, rgb("#1f5240") if (k + j) % 2 else rgb("#2a6a50"))
    elif kind == "snowpine":
        box(cr, x + 3, g - 3, 2, 3, rgb("#4a3f40"))
        for y, w in ((g - 8, 8), (g - 12, 6), (g - 16, 4)):
            for k in range(4):
                box(cr, x + 4 - (w - k) // 2, y + k - 1, w - k, 1, rgb("#3a5a68") if k > 1 else rgb("#f0f6fc"))
    elif kind == "tuft":
        for i, h in enumerate((3, 5, 2, 4, 3)):
            box(cr, x + i, g - h, 1, h, rgb("#d8c872") if i % 2 else rgb("#8a8440"))
    elif kind == "boulder":
        box(cr, x + 1, g - 4, 7, 4, rgb("#7a7a86"))
        box(cr, x + 2, g - 5, 5, 1, rgb("#9a9aa6"))
        box(cr, x + 6, g - 4, 2, 4, rgb("#5a5a66"))
    elif kind == "cactus":
        box(cr, x + 3, g - 12, 3, 12, rgb("#3e8a54"))
        box(cr, x + 3, g - 12, 1, 12, rgb("#62b070"))
        box(cr, x, g - 8, 3, 2, rgb("#3e8a54"))
        box(cr, x, g - 11, 1, 3, rgb("#3e8a54"))
        box(cr, x + 6, g - 6, 3, 2, rgb("#3e8a54"))
        box(cr, x + 8, g - 9, 1, 3, rgb("#3e8a54"))
    elif kind == "deadtree":
        c = rgb("#14121c")
        box(cr, x + 3, g - 13, 2, 13, c)
        for dy, dx, w in ((10, 0, 3), (7, 5, 3), (12, 5, 2), (5, 1, 2)):
            box(cr, x + dx, g - dy, w, 1, c)


def weather(box, cr, t, lw, lh, kind, sky):
    """Погода поверх сцены; кадр дешёвый: не больше полусотни квадратов."""
    if kind == "snow":
        for i in range(42):
            x = (i * 41 + int(t * (3 + i % 3)) + int(3 * math.sin(t + i))) % lw
            y = (i * 29 + int(t * (9 + i % 5))) % lh
            box(cr, x, y, 1 + (i % 4 == 0), 1, WHITE, 0.85)
    elif kind == "ash":
        for i in range(30):
            x = (i * 47 + int(t * 2) + int(4 * math.sin(t * 0.4 + i))) % lw
            y = lh - 1 - (i * 31 + int(t * (3 + i % 4))) % lh
            box(cr, x, y, 1, 1, SEAM if i % 5 == 0 else rgb("#6a6480"), 0.75)
    elif kind == "sand":
        for i in range(26):
            x = (i * 53 + int(t * (34 + i % 7 * 6))) % (lw + 20) - 10
            y = lh // 3 + (i * 37) % (lh * 2 // 3)
            box(cr, x, y, 3 + i % 5, 1, rgb("#f0d8a0"), 0.35)
    elif kind == "wind":
        for i in range(9):
            x = (i * 71 + int(t * (46 + i * 7))) % (lw + 40) - 20
            y = lh // 5 + (i * 23) % (lh // 2)
            box(cr, x, y + int(2 * math.sin(t + i)), 8 + i % 4 * 3, 1, WHITE, 0.14)
    elif kind == "leaves":
        for i in range(12):
            x = (i * 59 + int(t * 5) + int(6 * math.sin(t * 0.8 + i))) % lw
            y = (i * 43 + int(t * (5 + i % 3))) % lh
            box(cr, x, y, 2, 1, rgb("#c8a040") if i % 3 else rgb("#6aaa50"), 0.9)


# ── портреты ─────────────────────────────────────────────────────────────────
FACE = ("..HHHHHHHH..", ".HHHHHHHHHH.", ".HHFFFFFFHH.", ".HFFFFFFFFH.", ".HFEFFFFEFH.", "..FFFFFFFF..",
        "..FFFMMFFF..", "...FFFFFF...", "..CCFFFFCC..", ".CCCCCCCCCC.", "CCCCCCCCCCCC", "CCCCCCCCCCCC")


def portrait(box, sprite, cr, x, y, s, person):
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    sprite(cr, 0, 0, FACE, {k: rgb(person[k]) for k in "HFEMC"})
    cr.restore()


# ── находки ──────────────────────────────────────────────────────────────────
ITEMS = ((".........", "..AAAAA..", ".AALLLAA.", ".ALAAADA.", ".ALAAADA.", ".ALAAADA.", ".AADDDAA.", "..AAAAA..", "........."),
         ("...AAA...", "..ALLAD..", ".ALAAADD.", ".LAAAAAD.", ".AAAAADD.", "..AAADD..", "...AD....", "...AD....", "..AAD...."),
         ("....AA...", "...ALLA..", "...ALDA..", "...AAAA..", "...AD....", "...AAD...", "...AD....", "...AAD...", "........."),
         (".LLLLLLL.", ".ADDDDDA.", ".AAAAAAA.", ".ADDDAAA.", ".AAAAAAA.", ".ADDDDDA.", ".AAAAAAA.", ".DDDDDDD.", "........."),
         ("....L....", "...LAD...", "..LAAAD..", ".LAAAAAD.", "..AAAAD..", "...AAD...", "....D....", ".........", "........."),
         ("......LA.", ".....LAD.", "....LAD..", "...LAD...", "..LAD....", ".LAD.....", ".AD......", "D........", "........."))
SCRAP = ("LLLLLLL..", "LAAAAAALL", "LAADAAAAL", "LAAADDAAL", "LAAAAADAL", ".LAADAAAL", ".LAAADAAL", "..LLLLLLL", ".........")


def item_icon(sprite, cr, x, y, s, index, rarity, palette):
    """Значок находки 9×9: шесть форм по очереди, цвет по редкости."""
    cr.save()
    cr.translate(x, y)
    cr.scale(s, s)
    sprite(cr, 0, 0, SCRAP if rarity == 3 else ITEMS[index % len(ITEMS)], palette)
    cr.restore()


# ── карта ────────────────────────────────────────────────────────────────────
MAP_TONES = dict(home=("#3e7a44", "#568f48", "#74b35c"), forest=("#1f4a38", "#2c5e42", "#3f7a4c"),
                 steppe=("#8a7f3e", "#a89c50", "#c8bc6c"), dunes=("#b88c48", "#d8b468", "#ecd08a"),
                 bay=("#4e5c5a", "#6a7a78", "#8a9a96"), spire=("#1e1a2c", "#2e2840", "#46406a"),
                 **{"pass": ("#8fa4bc", "#c0d0e0", "#f0f6fc")})
DEEP, SHALLOW, FOAM, BEACH = "#1a3a5e", "#2f6a94", "#7cc4dc", "#e0cc90"
FOG = rgb("#14121f")
# замки на карте, 13×11: # стена, A крыша, O окно
MINI = dict(home=("..#...#...#..", "..###.#.###..", "..###AAA###..", "..###A#A###..", ".###########.", ".#.#.###.#.#.",
                  ".###########.", ".#####O#####.", ".####OOO####.", ".####OOO####.", "............."),
            forest=("......A......", ".....AAA.....", "....AAAAA....", "...AAAAAAA...", "...#######...", "...###O###...",
                    "#.#.#####.#.#", "#############", "#####OOO#####", "#####OOO#####", "............."),
            steppe=("......#......", "....#####....", "...#######...", "..#########..", "..AAAAAAAAA..", "..#########..",
                    "..####O####..", "..###OOO###..", "..###OOO###..", ".............", "............."),
            dunes=("......A......", ".....AAA.....", "...AAAAAAA...", "..AAAAAAAAA..", "..AAAAAAAAA..", ".###########.",
                   ".##O##O##O##.", ".###########.", ".####OOO####.", ".####OOO####.", "............."),
            bay=("......O......", ".....OOO.....", ".....###.....", ".....AAA.....", ".....###.....", ".....AAA.....",
                 "....#####....", "....AAAAA....", "...#######...", "..#########..", "............."),
            spire=("......#......", "......#......", ".....###.....", ".....###.....", ".....#O#.....", "....#####....",
                   "....#####....", "...###O###...", "...#######...", "..#########..", "............."),
            **{"pass": ("..A.......A..", ".AAA..A..AAA.", ".###.AAA.###.", ".###.###.###.", ".###.#O#.###.", ".###.###.###.",
                        ".###########.", ".###########.", ".####OOO####.", ".####OOO####.", ".............")})
BUILDER_MARK = ("..LLL..", ".LLLLL.", ".FFFFF.", "..FFF..", ".BBBBB.", "..BBB..", "...B...")


def world_map(lw, lh, lands, lit, beyond, shown):
    """Карта одной картинкой: lands — [(ключ, (x, y))], lit — какие земли открыты, shown — видны ли
    острова за морем. Шум постоянный: земля та же при любом размере окна."""
    import cairo
    import numpy as np

    def noise(cells, seed):
        rng = np.random.default_rng(seed)
        gy, gx = int(cells * lh / lw) + 3, cells + 3
        g = rng.random((gy, gx))
        ys, xs = np.linspace(0, gy - 1.01, lh), np.linspace(0, gx - 1.01, lw)
        y0, x0 = ys.astype(int), xs.astype(int)
        ty, tx = ys - y0, xs - x0
        ty, tx = (ty * ty * (3 - 2 * ty))[:, None], (tx * tx * (3 - 2 * tx))[None, :]
        return ((g[y0][:, x0] * (1 - tx) + g[y0][:, x0 + 1] * tx) * (1 - ty)
                + (g[y0 + 1][:, x0] * (1 - tx) + g[y0 + 1][:, x0 + 1] * tx) * ty)

    def fbm(cells, seed, octaves=4):
        out, amp, norm = 0.0, 1.0, 0.0
        for i in range(octaves):
            out = out + noise(cells * 2 ** i, seed + i) * amp
            norm += amp
            amp *= 0.5
        return out / norm

    Y, X = np.mgrid[0:lh, 0:lw].astype(float)
    X, Y = X / lw, Y / lh
    shape = fbm(4, 11)
    wx, wy = X + (fbm(3, 21) - 0.5) * 0.14, Y + (fbm(3, 31) - 0.5) * 0.14
    e = np.zeros((lh, lw))
    for _k, (cx, cy) in lands:
        e += np.exp(-((X - cx) ** 2 / 0.022 + (Y - cy) ** 2 / 0.05))
    if shown:
        e += 1.3 * np.exp(-((X - beyond[0]) ** 2 / 0.0035 + (Y - beyond[1]) ** 2 / 0.008))
    e = np.minimum(e, 1.15) + (shape - 0.5) * 1.0
    far_d = (X - beyond[0]) ** 2 + (Y - beyond[1]) ** 2
    e -= 1.3 * np.exp(-((X - beyond[0] + 0.075) ** 2 / 0.0022 + (Y - beyond[1] - 0.09) ** 2 / 0.012))     # пролив
    if shown:
        e = np.where(far_d < 0.009, e + 0.9, e)
    th = 0.46
    land = e > th
    dist = np.stack([(wx - c[0]) ** 2 + (wy - c[1]) ** 2 for _k, c in lands])
    idx = dist.argmin(axis=0)
    if shown:
        idx = np.where(far_d < 0.02, len(lands), idx)
    bayer = np.array(((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5)), float) / 16
    bay_t = np.tile(bayer, (lh // 4 + 1, lw // 4 + 1))[:lh, :lw]
    detail = fbm(max(8, lw // 14), 41, 3)
    tone = detail + (bay_t - 0.5) * 0.12
    pick = np.digitize(tone, (0.45, 0.56))
    tones = [MAP_TONES[k] for k, _c in lands] + [("#2f6a5a", "#3f8a70", "#62b090")]
    table = np.array([[rgb(c) for c in t] for t in tones])
    img = table[idx, pick]
    fine = noise(max(10, lw // 3), 51)
    keys = [k for k, _c in lands]

    def region(k):
        return idx == keys.index(k)
    ridges = np.abs(fbm(max(6, lw // 28), 61, 3) - 0.5)
    for k, col in (("pass", "#5f7490"), ("spire", "#0f0d18")):               # горы хребтами
        img[region(k) & (ridges < 0.03)] = rgb(col)
    img[region("forest") & (fine > 0.68)] = rgb("#14362a")
    img[region("home") & (fine > 0.8)] = rgb("#2c5a36")
    band = np.sin(Y * lh * 0.62 + detail * 15) > 0.72
    img[region("dunes") & band] = rgb("#b8924c")
    img[region("steppe") & (np.sin(X * lw * 0.5 + detail * 18) > 0.86)] = rgb("#7f7a3c")
    shift = np.roll(idx, 1, 0) != idx
    shift |= np.roll(idx, 1, 1) != idx
    img[land & shift] = img[land & shift] * 0.62
    coast = land & (e < th + 0.07)
    img[coast] = rgb(BEACH)
    deep = np.array(rgb(DEEP))
    sea = deep + (np.array(rgb(SHALLOW)) - deep) * np.clip(np.floor((e - th + 0.34 + (bay_t - 0.5) * 0.1) * 12) / 4, 0, 1)[..., None]
    img = np.where(land[..., None], img, sea)
    img[~land & (e > th - 0.03) & (bay_t > 0.5)] = rgb(FOAM)
    img[~land & (fine > 0.72) & (e < th - 0.2) & (bay_t < 0.2)] = rgb("#3f7aa4")
    dark = np.array(FOG)
    for i, k in enumerate(keys):                                             # туман над закрытым
        if k not in lit:
            m = (idx == i) & land
            a = np.clip(0.66 + (detail - 0.5) * 1.6 + (bay_t - 0.5) * 0.14, 0.45, 0.86)[..., None]
            img = np.where(m[..., None], img * (1 - a) + dark * a, img)
    if not shown:
        far = np.sqrt((X - beyond[0]) ** 2 + (Y - beyond[1]) ** 2)
        a = np.clip((0.2 - far) * 8 + (detail - 0.5), 0, 0.82)[..., None]
        a = np.where(a > 0.05 + bay_t[..., None] * 0.1, a, 0)
        img = img * (1 - a) + dark * a
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, lw, lh)
    stride = surf.get_stride()
    buf = np.frombuffer(surf.get_data(), dtype=np.uint8).reshape(lh, stride)
    u8 = (np.clip(img, 0, 1) * 255).astype(np.uint8)
    buf[:, 0:lw * 4:4], buf[:, 1:lw * 4:4], buf[:, 2:lw * 4:4] = u8[..., 2], u8[..., 1], u8[..., 0]
    surf.mark_dirty()
    return surf
