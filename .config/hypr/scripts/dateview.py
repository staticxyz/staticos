#!/usr/bin/env python3
"""Big weekday + date for a terminal window, centred and self-resizing.

Picks the largest figlet font that still fits the current terminal, centres the
result both ways, and redraws on window resize (SIGWINCH) as well as once a
minute so it rolls over at midnight on its own.

Colour is read from ~/.cache/matugen/colors-kitty.conf on every redraw, so it
follows the wallpaper like the rest of the terminal palette.

Usage: dateview.py [-C N] [--fmt-top FMT] [--fmt-bottom FMT] [--plain]
  -C N          use ANSI colour N (0-7) instead of the wallpaper accent
  --fmt-top     strftime for the top line     (default "%A")
  --fmt-bottom  strftime for the bottom line  (default "%d %B")
  --plain       no colour at all
"""
import datetime
import os
import shutil
import signal
import sys
import time

import pyfiglet

# Чистый акцент обоев, а не color4 из палитры терминала: слоты ANSI
# гармонизированы — их оттенок подтянут к акценту, но не равен ему (замерено:
# обои 210°, акцент 200°, color4 222°), и виджет из-за этого заметно
# расходился с гаммой обоев. vivid.txt пишет sensor_colors.py на каждой смене.
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")
CACHE = os.path.expanduser("~/.cache/matugen/colors-kitty.conf")

# tty-clock fills its window by drawing each glyph pixel as a block of kx*ky
# terminal cells, and that is what makes it look the same at any size. Same
# trick here — but a single source font left big gaps: going from one pixel-
# cell to two doubles both dimensions in one jump, and if the window falls
# between those two sizes (very common), a third of it went unfilled — that
# was the actual bug, and it is why the widget still looked small at the
# window size in question, however the earlier scale-search was tuned.
#
# Fixed by keeping four fonts of increasing native resolution (BITMAP_FONTS,
# smallest first) and searching every (font, kx, ky) combination for whichever
# comes closest to filling the window — a font with finer native detail closes
# the gaps a coarser one's integer steps leave behind.
#
# "half" fonts draw two vertical pixels per character using ▀▄█░; "full" fonts
# (blocky-style capitals) draw one pixel per character using █ only.
# min_kx — при каком масштабе штрих буквы получается не тоньше двух ячеек.
# Замерено на исходных глифах: blocky и ansi_regular рисуют штрихи шириной
# 2-6 ячеек уже без всякого масштабирования, а pagga и double_blocky — в одну,
# и им нужно удвоение. Единое правило «минимум x2 для всех» отсекало как раз
# самые чистые шрифты и заставляло брать pagga, буквы которого при удвоении
# выглядят грубее.
# the_edge убран (23.09.2026): у него нет цифр — «23 SEPTEMBER» рисовался как
# «SEPTEMBER», а буквы с диагоналями выбивались из блочного вида (заметил
# пользователь в высоком узком окне, где он и выигрывал по месту).
# pagga и double_blocky при kx=1 дают штрих в одну клетку — грубовато, но это
# ступень перед запасными линейными шрифтами. Те тоже красятся фоном, как
# блоки: попытка печатать их текстом дала мелкие буквы вместо привычных
# крупных в низком широком окне — откачено (23.09.2026).
BITMAP_FONTS = [
    ("blocky", "full", 1),
    ("ansi_regular", "full", 1),
    ("pagga", "half", 1),
    ("double_blocky", "half", 1),
]
FALLBACK = ["small", "mini", "threepoint"]
LINE_GAP = 1
# Растягивать строки по горизонтали пробовали — во всю ширину окна, обе в одну
# (23.09.2026). Буквы от этого раздались вширь и потеряли вид; вернулись к
# природным пропорциям: день недели у́же даты просто потому, что в нём меньше
# букв, и это честно. MAX_STRETCH = 1.0 — растяжения нет, множитель оставлен
# ручкой на случай, если захочется лёгкого (1.1-1.2 читается ещё нормально).
MAX_STRETCH = 1.0

_resized = False


def on_resize(_sig, _frm):
    global _resized
    _resized = True


def accent(color_idx):
    if color_idx is not None:
        return f"\033[3{color_idx}m"
    try:
        h = open(VIVID).read().strip().lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"\033[38;2;{r};{g};{b}m"
    except (OSError, ValueError):
        pass
    try:
        for line in open(CACHE):
            p = line.split()
            if len(p) == 2 and p[0] == "color4":
                h = p[1].lstrip("#")
                r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
                return f"\033[38;2;{r};{g};{b}m"
    except OSError:
        pass
    return "\033[36m"


def render(text, font):
    art = pyfiglet.Figlet(font=font, width=10000).renderText(text)
    rows = [r.rstrip() for r in art.split("\n")]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


HALF_MAP = {"█": (1, 1), "▀": (1, 0), "▄": (0, 1), "░": (0, 0), " ": (0, 0)}


def to_bitmap(rows, kind):
    """Figlet art -> list of pixel rows (each a list of 0/1).

    "half" fonts draw two vertical pixels per character (pagga: ▀▄█░), doubling
    the vertical resolution over a plain per-character reading. "full" fonts
    (ansi_regular, blocky) draw one pixel per character using only █, so each
    text row is already exactly one pixel row.
    """
    out = []
    if kind == "half":
        for r in rows:
            top, bottom = [], []
            for ch in r:
                t, b = HALF_MAP.get(ch, (0, 0))
                top.append(t)
                bottom.append(b)
            out.append(top)
            out.append(bottom)
    else:
        for r in rows:
            out.append([1 if ch != " " else 0 for ch in r])
    while out and not any(out[0]):
        out.pop(0)
    while out and not any(out[-1]):
        out.pop()
    # render() rstrips each text row, so rows arrive at different lengths —
    # pad to a rectangle or indexing by column blows up.
    if out:
        width = max(len(r) for r in out)
        out = [r + [0] * (width - len(r)) for r in out]
    return out


def bitmap_to_rows(bmp, target_w, target_h, block="\u2588"):
    """Draw a bitmap resampled to exactly target_w x target_h cells.

    Integer replication (each pixel becoming an exact kx by ky block) is what
    kept this from filling the window: at a given window size the next integer
    step up usually does not fit, so it settled for the step below and left a
    third of the height empty. Nearest-neighbour resampling has no such steps
    — some pixels come out one cell wider than their neighbours, which is
    invisible on block glyphs, and the art fills the space it was given.
    """
    src_h = len(bmp)
    src_w = len(bmp[0]) if src_h else 0
    if not src_h or not src_w:
        return []
    out = []
    for y in range(target_h):
        sy = min(src_h - 1, y * src_h // target_h)
        row = bmp[sy]
        line = "".join(block if row[min(src_w - 1, x * src_w // target_w)] else " "
                       for x in range(target_w))
        out.append(line.rstrip())
    return out


def trim_bitmap(bmp):
    """Drop all-blank columns at both ends so centring is on the real ink."""
    if not bmp:
        return bmp
    cols = len(bmp[0])
    first, last = 0, cols - 1
    while first < cols and not any(r[first] for r in bmp):
        first += 1
    while last > first and not any(r[last] for r in bmp):
        last -= 1
    return [r[first:last + 1] for r in bmp]


def scale(rows, k):
    """Blow up block art k times in both axes.

    A glyph pixel in these fonts is 2 cells wide and 1 tall, which is roughly
    square on screen (cells are about twice as tall as wide), so scaling both
    axes by the same k keeps the proportions.
    """
    if k <= 1:
        return rows
    out = []
    for r in rows:
        wide = "".join(c * k for c in r)
        out.extend([wide] * k)
    return out


def dims(top, bot):
    w = max([len(r) for r in top + bot] or [0])
    return w, len(top) + LINE_GAP + len(bot)


def fit(top_text, bottom_text, cols, rows_avail):
    """Largest whole-number scale that fits, keeping the glyphs' proportions.

    Copies tty-clock's actual mechanic, which is simpler than it looks: its
    digits are a FIXED size (measured — always 11 rows tall and ~58 columns
    wide whether the terminal is 60x18 or 140x44) and it merely centres them.
    Nothing is ever stretched, so the glyphs always keep their shape and there
    is always breathing room at the edges. That is exactly why it looks right
    and why the earlier stretch-to-fill version looked wrong.

    The one thing added on top: if the window is big enough for the art at
    double (or triple) size, step up — but only by whole numbers, so pixels
    stay square and nothing is ever distorted.
    """
    for font, kind, min_kx in BITMAP_FONTS:
        try:
            top_bmp = trim_bitmap(to_bitmap(render(top_text, font), kind))
            bot_bmp = trim_bitmap(to_bitmap(render(bottom_text, font), kind))
        except Exception:
            continue
        if not top_bmp or not bot_bmp:
            continue

        src_w = max(len(top_bmp[0]), len(bot_bmp[0]))
        src_h = len(top_bmp) + len(bot_bmp) + LINE_GAP

        # Whole-number steps only. ky is half of kx because a terminal cell is
        # about twice as tall as it is wide, so this keeps pixels square.
        # Stop at this font's min_kx so strokes never come out a single cell
        # wide; if even that will not fit, the next (smaller) font is tried.
        for kx in range(8, min_kx - 1, -1):
            ky = max(1, kx // 2)
            if src_w * kx <= cols and src_h * ky <= rows_avail:
                top_w, bot_w = len(top_bmp[0]) * kx, len(bot_bmp[0]) * kx
                common = min(cols, int(top_w * MAX_STRETCH), int(bot_w * MAX_STRETCH))
                # у́же природной ширины строку не делаем, шире потолка — тоже
                tw = max(top_w, min(common, int(top_w * MAX_STRETCH)))
                bw = max(bot_w, min(common, int(bot_w * MAX_STRETCH)))
                return (bitmap_to_rows(top_bmp, tw, len(top_bmp) * ky),
                        bitmap_to_rows(bot_bmp, bw, len(bot_bmp) * ky))

    for font in FALLBACK:
        try:
            top, bot = render(top_text, font), render(bottom_text, font)
        except Exception:
            continue
        w, h = dims(top, bot)
        if w <= cols and h <= rows_avail:
            return top, bot
    return [top_text], [bottom_text]


def paint(row, fg_escape):
    """Draw a row of block art as coloured *background* on spaces.

    This is exactly how tty-clock gets its perfectly smooth digits: it never
    prints a glyph, it prints spaces with a background colour set. Block
    characters like U+2588 leave hairline seams between rows and columns
    because the glyph does not quite fill its cell in every font; painted
    background has no seams at all.
    """
    bg = fg_escape.replace("\033[38;2;", "\033[48;2;").replace("\033[3", "\033[4")
    out, run_on, run_len = [], False, 0

    def flush():
        if not run_len:
            return
        out.append((bg if run_on else "") + " " * run_len + ("\033[0m" if run_on else ""))

    for ch in row:
        on = ch != " "
        if on != run_on and run_len:
            flush()
            run_len = 0
        run_on = on
        run_len += 1
    flush()
    return "".join(out) + "\033[0m"


def draw(color, fmt_top, fmt_bottom):
    cols, rows = shutil.get_terminal_size(fallback=(80, 24))
    now = datetime.datetime.now()
    top, bot = fit(now.strftime(fmt_top), now.strftime(fmt_bottom), cols - 2, rows - 2)

    # Figlet rows share one origin, so they must be shifted as a unit. Centring
    # them individually tears the glyphs apart — each row would slide by its own
    # amount. So each of the two text blocks is centred as a whole instead.
    width = max([len(r) for r in top + bot] or [1])
    block = []
    for rows_of in (top, bot):
        bw = max([len(r) for r in rows_of] or [1])
        pad = " " * ((width - bw) // 2)
        block.extend(pad + r for r in rows_of)
        if rows_of is top:
            block.extend([""] * LINE_GAP)

    left = max(0, (cols - width) // 2)
    top_pad = max(0, (rows - len(block)) // 2)

    out = ["\033[2J\033[H"]
    for i, row in enumerate(block):
        out.append(f"\033[{top_pad + i + 1};1H")
        # Bold mostly matters for the line-art fallback fonts — the block
        # fonts are already solid ink and barely change — but it's free.
        out.append(" " * left + paint(row, color))
    sys.stdout.write("".join(out))
    sys.stdout.flush()


def main():
    args = sys.argv[1:]
    color_idx = None
    fmt_top, fmt_bottom = "%A", "%d %B"
    plain = "--plain" in args
    for i, a in enumerate(args):
        if a == "-C" and i + 1 < len(args):
            color_idx = args[i + 1]
        elif a == "--fmt-top" and i + 1 < len(args):
            fmt_top = args[i + 1]
        elif a == "--fmt-bottom" and i + 1 < len(args):
            fmt_bottom = args[i + 1]

    signal.signal(signal.SIGWINCH, on_resize)
    sys.stdout.write("\033[?25l")           # hide cursor
    global _resized
    try:
        last, last_color = None, None
        while True:
            color = "" if plain else accent(color_idx)
            stamp = datetime.datetime.now().strftime("%Y%m%d")
            # Цвет тоже входит в условие перерисовки. Раньше его читали каждый
            # виток, но рисовали только при смене даты или размера — поэтому
            # после смены обоев виджет держал старый цвет до полуночи, и его
            # приходилось перезапускать вручную.
            if _resized or stamp != last or color != last_color:
                draw(color, fmt_top, fmt_bottom)
                last, last_color, _resized = stamp, color, False
            # Short sleep so a resize repaints promptly; the date itself only
            # ever changes at midnight.
            for _ in range(20):
                if _resized:
                    break
                time.sleep(0.15)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[2J\033[H")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
