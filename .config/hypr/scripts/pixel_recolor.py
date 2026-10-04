#!/usr/bin/env python3
"""Перекраска пиксель-арта в гамму обоев — по оттенку OKLCH. 01.10.2026.

Просьба: «пиксельную Мику сделай по гамме обоев, чтобы при смене каждый раз
подтягивалось. Как впрочем и всё в системе». Рисунок не перерисовывается:
у выбранных пикселей меняется только оттенок (H в OKLCH), светлота L и
насыщенность C остаются — поэтому свет, тени и контур рисунка сохраняются при
любой палитре. Кто перекрашивается, решает select(r, g, b) → bool.

    target_hue()                 оттенок акцента обоев (primary), градусы
    recolor(img, hue, select, ref=None)
        ref — «опорный» оттенок исходника: пиксели сдвигаются на (hue - ref),
        и разброс оттенков внутри рисунка (блики, тени) сохраняется. Без ref —
        всем выбранным ставится ровно hue.

Используют: xpbar.py (спрайт на «Пуске», надпись static_).
"""
import colorsys
import math


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _gam(c):
    c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
    return max(0, min(255, round(c * 255)))


def to_oklch(r, g, b):
    r, g, b = _lin(r), _lin(g), _lin(b)
    l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l, m, s = (math.copysign(abs(v) ** (1 / 3), v) for v in (l, m, s))
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(A, B), math.degrees(math.atan2(B, A)) % 360


def from_oklch(L, C, H):
    """OKLCH → sRGB 0..255; вне охвата — уменьшать C, пока не влезет."""
    for _ in range(24):
        A, B = C * math.cos(math.radians(H)), C * math.sin(math.radians(H))
        l = (L + 0.3963377774 * A + 0.2158037573 * B) ** 3
        m = (L - 0.1055613458 * A - 0.0638541728 * B) ** 3
        s = (L - 0.0894841775 * A - 1.2914855480 * B) ** 3
        r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        b = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
        if all(-0.001 <= v <= 1.001 for v in (r, g, b)):
            break
        C *= 0.9
    return tuple(_gam(max(0.0, min(1.0, v))) for v in (r, g, b))


def hex_hue(h):
    h = h.lstrip("#")
    return to_oklch(*(int(h[i:i + 2], 16) for i in (0, 2, 4)))[2]


def target_hue():
    import popup_theme
    return hex_hue(popup_theme.palette()["primary"])


def recolor(img, hue, select=lambda r, g, b: True, ref=None):
    """Новая картинка RGBA: у выбранных пикселей оттенок заменён."""
    img = img.convert("RGBA")
    out = img.copy()
    px, po = img.load(), out.load()
    cache = {}
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, a = px[x, y]
            if a == 0 or not select(r, g, b):
                continue
            key = (r, g, b)
            if key not in cache:
                L, C, H = to_oklch(r, g, b)
                nh = (H + hue - ref) % 360 if ref is not None else hue
                cache[key] = from_oklch(L, C, nh)
            po[x, y] = cache[key] + (a,)
    return out


# Готовые правила выбора

def hls(r, g, b):
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    return h * 360, l, s


def miku_select(r, g, b):
    """Бирюза (волосы, галстук, огоньки) и серо-голубая одежда; кожа, красные
    ленты, белки глаз и чёрный контур — нет."""
    h, l, s = hls(r, g, b)
    if l < 0.06 or l > 0.95:
        return False
    if 140 <= h <= 215 and s > 0.25:
        return True
    return 180 <= h <= 240 and s <= 0.25 and l > 0.12      # холодный серый одежды


MIKU_REF = 182.4      # оттенок бирюзы Мику в OKLCH (медиана по кадру, опора для сдвига)


def cool_select(r, g, b):
    """Всё холодное и не чёрное — для рисунков в одной синей гамме (static_)."""
    h, l, s = hls(r, g, b)
    return l >= 0.08 and s > 0.08 and 190 <= h <= 260
