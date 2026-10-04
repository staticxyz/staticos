#!/usr/bin/env python3
"""Build the 16 ANSI colours for the terminal from the wallpaper's accent.

Two goals pull against each other:

  * every slot should sit inside the wallpaper's colour family, so things like
    fastfetch (which prints bold cyan) actually change with the wallpaper;
  * the six chromatic slots must stay telling apart, or `ls`, diffs and syntax
    highlighting turn into mush.

So instead of guessing a blend factor, this rotates each canonical ANSI hue
towards the accent as far as it can while every pair of slots stays at least
MIN_DELTA_E apart in CIE Lab, and stops at the strongest setting that still
passes. The chosen strength is printed so it can be checked.
"""
import colorsys, math, os, sys

# Overridable so the palette can be generated into a sandbox for testing
# without repainting every live terminal.
FACTS = os.environ.get("TERM_FACTS",
                       os.path.expanduser("~/.cache/matugen/term-facts.sh"))
OUT = os.environ.get("TERM_COLORS_OUT",
                     os.path.expanduser("~/.cache/matugen/colors-kitty.conf"))

# transparent_background_colors ЖИВЁТ ОТДЕЛЬНО, И ЭТО НЕ КОСМЕТИКА.
# colors-kitty.conf заливается в живые окна через `kitty @ set-colors
# --all --configured`, а этот ключ ломает такую заливку: kitty разбирает его
# значение в пару (цвет, альфа), но patch_options_with_color_spec() всё равно
# гонит значение через color_from_int(), и оно падает —
#   TypeError: unsupported operand type(s) for >>: 'str' and 'int'
#   kitty/colors.py:259
# Замерено: файл со строкой -> трейсбек на всех 16 сокетах, файл без неё ->
# rc=0. Цвета окон при этом всё же доезжают (patch_color_profiles отрабатывает
# ДО падения), а всё, что идёт после, молча пропускается: конфигурированные
# умолчания, цвета таббара, set_os_window_chrome(). В theme_changer.sh ветка
# стоит под 2>/dev/null, поэтому ошибку никто ни разу не увидел.
#
# Поэтому ключ уезжает в отдельный файл, который kitty.conf подключает
# отдельным include и который перечитывается по SIGUSR1 — его theme_changer
# и так шлёт следом за заливкой.
OPACITY_OUT = os.environ.get("TERM_OPACITY_OUT",
                             os.path.expanduser("~/.cache/matugen/kitty-opacity.conf"))

# Canonical ANSI hues (degrees) for slots 1..6.
CANONICAL = {1: 12, 2: 142, 3: 78, 4: 258, 5: 318, 6: 192}
NAMES = {1: "Red", 2: "Green", 3: "Yellow", 4: "Blue", 5: "Magenta", 6: "Cyan"}

# Each slot gets its own lightness. That is what lets the hues be pulled hard
# towards the accent without the slots collapsing into each other: even when
# two hues nearly meet, the lightness gap keeps them apart perceptually.
NORMAL_L = {1: 0.72, 2: 0.80, 3: 0.87, 4: 0.75, 5: 0.67, 6: 0.84}
BRIGHT_BOOST = 0.09
SAT_MIN, SAT_MAX = 0.38, 0.72
MIN_DELTA_E = 12.0            # CIE76 distance below which two slots read alike
MIN_CONTRAST = 4.5            # WCAG AA against the terminal background
WINDOW_OPACITY = "0.85"


def read_facts(path):
    facts = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            facts[k] = v.strip()
    return facts


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb_to_hex(r, g, b):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in (r, g, b))


def lab(rgb):
    def f_inv(c):
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f_inv(c) for c in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = (0.2126 * r + 0.7152 * g + 0.0722 * b)
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(c1, c2):
    a, b = lab(c1), lab(c2)
    return math.dist(a, b)


def relative_luminance(rgb):
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (f(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(rgb, other):
    l1, l2 = sorted((relative_luminance(rgb), relative_luminance(other)), reverse=True)
    return (l1 + 0.05) / (l2 + 0.05)


def ensure_contrast(h, l, s, bg_rgb):
    """Push lightness away from the background until the colour is readable.

    Wallpapers can be any colour, so a fixed lightness table is not enough:
    whatever hue comes out, the text still has to be legible on this
    background.
    """
    bg_light = relative_luminance(bg_rgb) > 0.18
    for _ in range(40):
        rgb = colorsys.hls_to_rgb(h, l, s)
        if contrast(rgb, bg_rgb) >= MIN_CONTRAST:
            return rgb, l
        l = max(0.05, l - 0.02) if bg_light else min(0.97, l + 0.02)
    return colorsys.hls_to_rgb(h, l, s), l


def rotate_towards(hue, target, mix):
    """Move `hue` a fraction `mix` of the shortest way round to `target`."""
    d = (target - hue + 180) % 360 - 180
    return (hue + d * mix) % 360


# Слот 4 («синий») при тёплом акценте. Кратчайший поворот от 258° к жёлтому
# (60°) идёт через маджента и красный, и «синий» превращался в розовый
# (#ed91be при жёлтых обоях, 22.09.2026): розовыми становились папки в ls,
# ключевые слова в nvim, рамки brrt — всё, что по традиции «синее». Для
# слота 4 поворот идёт другой дорогой, через бирюзу, и не заходит дальше
# BLUE_FLOOR: остаётся холодным, читается как «синий», но лежит в семье обоев.
BLUE_FLOOR = 190.0


def rotate_blue(hue, target, mix):
    d = (target - hue + 180) % 360 - 180
    if d > 0:                       # путь через маджента — идём в обход
        d -= 360
    return max(BLUE_FLOOR, (hue + d * mix)) if hue + d * mix > 0 else BLUE_FLOOR


def build(accent_hue, sat, mix, bg_rgb):
    """-> {slot: (r,g,b)} for slots 1..6 and their bright counterparts."""
    out = {}
    for slot, canon in CANONICAL.items():
        if slot == 4:
            h = rotate_blue(canon, accent_hue, mix) / 360
        else:
            h = rotate_towards(canon, accent_hue, mix) / 360
        rgb, nl = ensure_contrast(h, NORMAL_L[slot], sat, bg_rgb)
        out[slot] = rgb
        out[slot + 8], _ = ensure_contrast(h, min(0.93, nl + BRIGHT_BOOST),
                                           min(1.0, sat + 0.14), bg_rgb)
    return out


def worst_pair(colors):
    slots = sorted(CANONICAL)
    worst, pair = 1e9, None
    for i, a in enumerate(slots):
        for b in slots[i + 1:]:
            d = delta_e(colors[a], colors[b])
            if d < worst:
                worst, pair = d, (a, b)
    return worst, pair


def main():
    if not os.path.exists(FACTS):
        print("gen_term_colors: нет term-facts.sh", file=sys.stderr)
        return 1
    f = read_facts(FACTS)
    accent_hue = float(f["ACCENT_HUE"])
    sat = max(SAT_MIN, min(SAT_MAX, float(f["ACCENT_SAT"]) / 100))
    bg_rgb = hex_to_rgb(f["SURFACE"])

    # Strongest harmonisation that keeps every pair distinguishable.
    chosen, colors, worst, pair = 0.0, None, 0.0, None
    for step in range(90, -1, -5):
        mix = step / 100
        cand = build(accent_hue, sat, mix, bg_rgb)
        w, p = worst_pair(cand)
        if w >= MIN_DELTA_E:
            chosen, colors, worst, pair = mix, cand, w, p
            break
    if colors is None:                      # cannot happen with mix=0, but be safe
        chosen = 0.0
        colors = build(accent_hue, sat, 0.0, bg_rgb)
        worst, pair = worst_pair(colors)

    # «Синий» слот — это акцент обоев, а не повёрнутый к нему синий (24.09.2026).
    # Им пользуются: путь в приглашении fish (tide_colors.py) — так он
    # перекрашивается при смене обоев даже в уже напечатанных строках, чего
    # точный цвет не умеет; TUI-программы в ANSI-теме — их выделения
    # синие; часы и таймер (widget_accent.py) и так ставили сюда акцент.
    # Цена: всё, что терминал красит синим (папки в ls и т. п.), — цветом акцента.
    colors[4] = hex_to_rgb(f["ACCENT_HEX"])
    colors[12] = hex_to_rgb(f["ON_PRIMARY_CONTAINER"])

    lines = [
        "# Generated by gen_term_colors.py — do not edit.",
        f"# accent hue {accent_hue:.0f}°, saturation {sat*100:.0f}%,"
        f" harmonisation {chosen*100:.0f}%, worst pair ΔE {worst:.1f}"
        f" ({NAMES[pair[0]]}/{NAMES[pair[1]]}),"
        f" worst contrast {min(contrast(colors[s_], bg_rgb) for s_ in colors):.2f}:1",
        "",
        f"foreground {f['ON_SURFACE']}",
        f"background {f['SURFACE']}",
        f"cursor {f['ACCENT_HEX']}",
        f"cursor_text_color {f['ON_ACCENT']}",
        f"selection_background {f['PRIMARY_CONTAINER']}",
        f"selection_foreground {f['ON_PRIMARY_CONTAINER']}",
        f"url_color {f['TERTIARY']}",
        "",
        # color0 must equal the window background, not a darker shade: ncurses
        # apps (cmatrix, calcurse…) paint every cell with SGR 40, and if that
        # colour differs from the default background the whole grid shows up as
        # a darker rectangle inside the translucent padding — the "frame".
        f"color0 {f['SURFACE']}",
        f"color8 {f['OUTLINE']}",
    ]
    for slot in sorted(CANONICAL):
        lines.append("")
        lines.append(f"# {NAMES[slot]}")
        lines.append(f"color{slot} {rgb_to_hex(*colors[slot])}")
        lines.append(f"color{slot + 8} {rgb_to_hex(*colors[slot + 8])}")
    lines += [
        "",
        f"color7 {f['ON_SURFACE_VARIANT']}",
        f"color15 {f['ON_SURFACE']}",
        "",
    ]
    open(OUT, "w").write("\n".join(lines))

    # Отдельным файлом — см. комментарий у OPACITY_OUT.
    open(OPACITY_OUT, "w").write("\n".join([
        "# Generated by gen_term_colors.py — do not edit.",
        "# Подключается из kitty.conf отдельным include и НАМЕРЕННО не лежит",
        "# в colors-kitty.conf: этот ключ роняет `kitty @ set-colors`.",
        "",
        "# ncurses apps fill the grid with an explicit background colour, which",
        "# kitty draws opaque; declaring those colours transparent removes the",
        "# solid rectangle inside the translucent window padding.",
        f"transparent_background_colors {f['SURFACE']}@{WINDOW_OPACITY}"
        f" {f['SURFACE_LOWEST']}@{WINDOW_OPACITY}",
        "",
    ]))
    worst_c = min(contrast(colors[s_], bg_rgb) for s_ in colors)
    print(f"гармонизация {chosen*100:.0f}%, худшая пара ΔE {worst:.1f} "
          f"({NAMES[pair[0]]}/{NAMES[pair[1]]}), худший контраст {worst_c:.2f}:1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
