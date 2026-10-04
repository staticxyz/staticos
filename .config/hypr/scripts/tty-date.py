#!/usr/bin/env python3
"""A tty-clock-style widget that shows today's date instead of the time.

Same blocky/segment aesthetic as tty-clock (which this sits next to on
workspace 10), but tty-clock has no mode for "just the date" — it always
draws H:M:S. This draws WEEKDAY on one line and "DD Month" on the next,
in big block glyphs, framed like `tty-clock -x`.

Colour comes from the live palette (~/.cache/matugen/colors-kitty.conf) and
is re-read on every redraw, so it follows the wallpaper the same way the
other terminal colour slots do — no restart needed.

Usage: tty-date.py [-C N] [--ru]
  -C N   ANSI colour 0-7, like tty-clock. Default: palette accent (truecolor).
  --ru   Russian weekday/month names (default: English).
"""
import datetime
import os
import shutil
import sys
import time

# ---- 5-wide x 5-tall block font -------------------------------------------
# Generic geometric block letterforms (not a reproduction of any specific
# copyrighted typeface) — the same kind of minimal pixel font used in LED
# matrix displays and countless open-source TUI tools.
FONT = {
    "A": ["01110", "10001", "11111", "10001", "10001"],
    "B": ["11110", "10001", "11110", "10001", "11110"],
    "C": ["01111", "10000", "10000", "10000", "01111"],
    "D": ["11110", "10001", "10001", "10001", "11110"],
    "E": ["11111", "10000", "11110", "10000", "11111"],
    "F": ["11111", "10000", "11110", "10000", "10000"],
    "G": ["01111", "10000", "10011", "10001", "01111"],
    "H": ["10001", "10001", "11111", "10001", "10001"],
    "I": ["11111", "00100", "00100", "00100", "11111"],
    "J": ["00111", "00010", "00010", "10010", "01100"],
    "K": ["10001", "10010", "11100", "10010", "10001"],
    "L": ["10000", "10000", "10000", "10000", "11111"],
    "M": ["10001", "11011", "10101", "10001", "10001"],
    "N": ["10001", "11001", "10101", "10011", "10001"],
    "O": ["01110", "10001", "10001", "10001", "01110"],
    "P": ["11110", "10001", "11110", "10000", "10000"],
    "Q": ["01110", "10001", "10101", "10010", "01101"],
    "R": ["11110", "10001", "11110", "10010", "10001"],
    "S": ["01111", "10000", "01110", "00001", "11110"],
    "T": ["11111", "00100", "00100", "00100", "00100"],
    "U": ["10001", "10001", "10001", "10001", "01110"],
    "V": ["10001", "10001", "10001", "01010", "00100"],
    "W": ["10001", "10001", "10101", "10101", "01010"],
    "X": ["10001", "01010", "00100", "01010", "10001"],
    "Y": ["10001", "01010", "00100", "00100", "00100"],
    "Z": ["11111", "00010", "00100", "01000", "11111"],
    "0": ["01110", "10011", "10101", "11001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00010", "00100", "11111"],
    "3": ["11110", "00001", "00110", "00001", "11110"],
    "4": ["00010", "00110", "01010", "11111", "00010"],
    "5": ["11111", "10000", "11110", "00001", "11110"],
    "6": ["00110", "01000", "11110", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "00100"],
    "8": ["01110", "10001", "01110", "10001", "01110"],
    "9": ["01110", "10001", "01111", "00010", "01100"],
    " ": ["000", "000", "000", "000", "000"],
    ".": ["00", "00", "00", "00", "10"],
}

# Cyrillic uppercase glyphs needed for Russian weekday/month names
# (ПОНЕДЕЛЬНИК..ВОСКРЕСЕНЬЕ, ЯНВАРЯ..ДЕКАБРЯ). Same generic geometric block
# style as the Latin set above — legibility over typographic fidelity.
FONT.update({
    "А": ["01110", "10001", "11111", "10001", "10001"],
    "Б": ["11111", "10000", "11110", "10001", "11110"],
    "В": ["11110", "10001", "11110", "10001", "11110"],
    "Г": ["11111", "10000", "10000", "10000", "10000"],
    "Д": ["01110", "10001", "10001", "10001", "11111"],
    "Е": ["11111", "10000", "11110", "10000", "11111"],
    "И": ["10001", "10011", "10101", "11001", "10001"],
    "К": ["10001", "10010", "11100", "10010", "10001"],
    "Л": ["00100", "01010", "01010", "10001", "10001"],
    "М": ["10001", "11011", "10101", "10001", "10001"],
    "Н": ["10001", "10001", "11111", "10001", "10001"],
    "О": ["01110", "10001", "10001", "10001", "01110"],
    "П": ["11111", "10001", "10001", "10001", "10001"],
    "Р": ["11110", "10001", "11110", "10000", "10000"],
    "С": ["01111", "10000", "10000", "10000", "01111"],
    "Т": ["11111", "00100", "00100", "00100", "00100"],
    "У": ["10001", "10001", "01010", "00100", "01000"],
    "Ф": ["00100", "01110", "11111", "01110", "00100"],
    "Ц": ["11101", "10001", "10001", "10001", "11101"],
    "Ч": ["10001", "10001", "01111", "00001", "00001"],
    "Ь": ["10000", "10000", "11110", "10001", "11110"],
    "Ю": ["10011", "10101", "11101", "10101", "10011"],
    "Я": ["01111", "10001", "01111", "00101", "10001"],
})

CACHE = os.path.expanduser("~/.cache/matugen/colors-kitty.conf")
GLYPH_GAP = 1
LINE_GAP = 1


def read_palette():
    colors = {}
    try:
        for line in open(CACHE):
            p = line.split()
            if len(p) == 2 and p[1].startswith("#"):
                colors[p[0]] = p[1]
    except OSError:
        pass
    return colors


def fg(hexcolor):
    h = hexcolor.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"\033[38;2;{r};{g};{b}m"


def render_line(text, sx, sy, block="█"):
    """-> list of strings, one per pixel row, for a whole line of text.

    Each font pixel becomes an sx-wide by sy-tall block of `block` characters
    — the same trick tty-clock uses to grow its digits to fill the window.
    Terminal cells are roughly twice as tall as they are wide, so sy is kept
    smaller than sx by the caller to keep glyphs looking square, not stretched.
    """
    glyphs = [FONT.get(ch, FONT[" "]) for ch in text]
    height = 5
    base_rows = []
    for r in range(height):
        parts = []
        for g in glyphs:
            row = g[r] if r < len(g) else "0" * len(g[0])
            parts.append("".join((block if c == "1" else " ") * sx for c in row))
        base_rows.append((" " * (GLYPH_GAP * sx)).join(parts))
    rows = []
    for row in base_rows:
        rows.extend([row] * sy)
    return rows


def compose(lines, sx, sy):
    """Stack multiple big-text lines, centring each on the widest one."""
    blocks = [render_line(l, sx, sy) for l in lines]
    width = max(len(r) for b in blocks for r in b)
    out = []
    for i, b in enumerate(blocks):
        if i:
            out.extend([" " * width] * (LINE_GAP * sy))   # padded, not empty
        out.extend(row.center(width) for row in b)
    return out, width


def fit_scale(cols, rows, box, base_w, base_h):
    """Largest (sx, sy) that still fits the terminal, sy kept ~half of sx to
    counter the cell aspect ratio so glyphs read as square, not stretched."""
    margin = 4 if box else 0
    avail_w = max(1, cols - margin)
    avail_h = max(1, rows - margin)
    best = (1, 1)
    for sx in range(1, 40):
        sy = max(1, round(sx * 0.5))
        w = base_w * sx + GLYPH_GAP * sx * 8   # rough glyph-count headroom
        h = base_h * sy
        if base_w * sx <= avail_w and h <= avail_h:
            best = (sx, sy)
        else:
            break
    return best


WEEKDAYS_RU = ["Понедельник", "Вторник", "Среда", "Четверг",
               "Пятница", "Суббота", "Воскресенье"]
MONTHS_RU = ["", "Января", "Февраля", "Марта", "Апреля", "Мая", "Июня",
             "Июля", "Августа", "Сентября", "Октября", "Ноября", "Декабря"]


def build(now, use_ru, sx, sy):
    if use_ru:
        weekday = WEEKDAYS_RU[now.weekday()].upper()
        date_line = f"{now.day} {MONTHS_RU[now.month].upper()}"
    else:
        weekday = now.strftime("%A").upper()
        date_line = now.strftime("%d %B").upper()
    return compose([weekday, date_line], sx, sy)


def draw(stdscr_cols, stdscr_rows, box, accent, use_ru):
    now = datetime.datetime.now()

    # Base (sx=sy=1) size of the longest plausible line ("WEDNESDAY"/9 chars)
    # decides how far the glyphs can be scaled up for this terminal size —
    # measuring the actual (usually shorter) text first would make the widget
    # jump in size every time the weekday name's length changes.
    base_w = 9 * (5 + GLYPH_GAP) - GLYPH_GAP
    base_h = 2 * 5 + LINE_GAP
    sx, sy = fit_scale(stdscr_cols, stdscr_rows, box, base_w, base_h)

    art, width = build(now, use_ru, sx, sy)
    height = len(art)

    sys.stdout.write("\033[2J\033[H")  # clear + home
    top = max(0, (stdscr_rows - height - (4 if box else 0)) // 2)
    left = max(0, (stdscr_cols - width - (4 if box else 0)) // 2)

    reset = "\033[0m"
    if box:
        h_line = "─" * (width + 2)
        sys.stdout.write(f"\033[{top};{left}H{accent}╭{h_line}╮{reset}\n")
        for i, row in enumerate(art):
            sys.stdout.write(f"\033[{top+1+i};{left}H{accent}│{reset} "
                              f"{accent}{row}{reset} {accent}│{reset}\n")
        sys.stdout.write(f"\033[{top+1+height};{left}H{accent}╰{h_line}╯{reset}\n")
    else:
        for i, row in enumerate(art):
            sys.stdout.write(f"\033[{top+i};{left}H{accent}{row}{reset}\n")
    sys.stdout.flush()


def main():
    args = sys.argv[1:]
    box = True  # always framed, like the tty-clock it sits next to
    color_idx = None
    use_ru = "--ru" in args
    for i, a in enumerate(args):
        if a == "-C" and i + 1 < len(args):
            color_idx = args[i + 1]

    ansi_basic = {"0": "\033[30m", "1": "\033[31m", "2": "\033[32m",
                  "3": "\033[33m", "4": "\033[34m", "5": "\033[35m",
                  "6": "\033[36m", "7": "\033[37m"}

    sys.stdout.write("\033[?25l")  # hide cursor
    try:
        while True:
            cols, rows = shutil.get_terminal_size(fallback=(80, 24))
            if color_idx is not None:
                accent = ansi_basic.get(color_idx, "\033[36m")
            else:
                palette = read_palette()
                accent = fg(palette.get("color4", "#7aa2f7"))
            draw(cols, rows, box, accent, use_ru)
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\033[?25h\033[0m\033[2J\033[H")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
