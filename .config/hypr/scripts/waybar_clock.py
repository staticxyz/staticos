#!/usr/bin/env python3
"""Waybar clock/calendar module — two synced instances, one per monitor.

Each output runs its own copy of this script (waybar sets WAYBAR_OUTPUT_NAME
for custom-module exec/click commands). Exactly one output shows "calendar"
(icon + dd.mm.yyyy) and the other shows "clock" (icon + HH:MM); right-clicking
either one flips which side is which, so the two bars always stay
complementary.

Bindings (wired in waybar config.jsonc):
  poll           periodic: print the {"text","tooltip"} JSON waybar wants
  popup          left-click:  mini calendar as a real window (no hover delay)
  open           right-click: raise/launch the standalone calendar window
  toggleside     middle-click: swap which monitor shows the calendar text
  yeartoggle     (unbound) tooltip flips between month view and year view
  next / prev    scroll: step the tooltip by a month (or a year, in year view)

State lives in ~/.cache/ so both instances (and future waybar restarts) agree:
  waybar-calendar-side    output name currently showing "calendar" text
  waybar-clock-yearmode   "0" | "1"
  waybar-clock-offset     months (or years, scaled by 12) from today
  waybar-clock-touched    mtime = last interaction; poll() auto-resets the
                           offset/year-mode after IDLE_RESET_S of no clicking,
                           so a stale scrolled-to month doesn't linger for the
                           next time you just hover to check today's date.
"""
import calendar
import datetime
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import time

CACHE_DIR = os.path.expanduser("~/.cache")
SIDE_FILE = os.path.join(CACHE_DIR, "waybar-calendar-side")
YEARMODE_FILE = os.path.join(CACHE_DIR, "waybar-clock-yearmode")
OFFSET_FILE = os.path.join(CACHE_DIR, "waybar-clock-offset")
TOUCHED_FILE = os.path.join(CACHE_DIR, "waybar-clock-touched")
FACTS = os.path.expanduser("~/.cache/matugen/term-facts.sh")
CALENDAR_APP = os.path.expanduser("~/.config/hypr/scripts/calendar_app.py")
CALENDAR_POPUP = os.path.expanduser("~/.config/hypr/scripts/calendar_popup.py")

IDLE_RESET_S = 15
# Годовой вид сбрасывается позже обычного: 15 секунд — это меньше, чем уходит
# на разглядывание двенадцати месяцев, и сброс срабатывал прямо под курсором.
# Подсказка при этом меняет размер, GTK пересчитывает её положение, и она
# уезжает — то есть автосброс сам по себе выглядел как "календарь прыгает".
IDLE_RESET_YEAR_S = 60
# Записаны escape-последовательностями, а не самими символами: при прошлых
# правках этого файла глифы Nerd Font потерялись и модуль остался без иконок.
ICON_TIME = "\uf017"   # nf-fa-clock_o
ICON_CAL = "\uf073"    # nf-fa-calendar

FALLBACK = {
    "ACCENT_HEX": "#7aa2f7", "ON_ACCENT": "#00315c",
    "ON_SURFACE": "#c0caf5", "ON_SURFACE_VARIANT": "#a9b1d6",
    "OUTLINE": "#565f89", "PRIMARY_CONTAINER": "#274664",
    "ON_PRIMARY_CONTAINER": "#d4e3ff", "TERTIARY": "#bb9af7",
}


def read_facts():
    facts = dict(FALLBACK)
    try:
        for line in open(FACTS):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                facts[k] = v.strip()
    except OSError:
        pass
    return facts


def read_state(path, default):
    try:
        v = open(path).read().strip()
        return v if v else default
    except OSError:
        return default


def write_state(path, value):
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w") as f:
        f.write(str(value))


def touch():
    write_state(TOUCHED_FILE, str(time.time()))


def maybe_auto_reset():
    """Snap the tooltip back to 'today, month view' after a quiet spell, so
    a preview you scrolled away from days ago doesn't come back stale."""
    last = read_state(TOUCHED_FILE, "0")
    try:
        idle = time.time() - float(last)
    except ValueError:
        idle = 1e9
    year_mode = read_state(YEARMODE_FILE, "0") == "1"
    if idle > (IDLE_RESET_YEAR_S if year_mode else IDLE_RESET_S):
        write_state(OFFSET_FILE, "0")
        write_state(YEARMODE_FILE, "0")


def outputs():
    names = sorted(m["name"] for m in wm.monitors() if m.get("name"))
    return names or ["eDP-1", "DP-4"]


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cell(text, colors, kind="day"):
    """-> (markup, visible_width). Keeping the two together is the whole point:
    padding markup strings with str.ljust counts the tag characters, which is
    exactly how the year view ended up with its columns sheared apart."""
    if kind == "today":
        mk = (f"<span background='{colors['PRIMARY_CONTAINER']}' "
              f"foreground='{colors['ON_PRIMARY_CONTAINER']}'><b>{text}</b></span>")
    elif kind == "wd":
        mk = f"<span foreground='{colors['ON_SURFACE_VARIANT']}'>{text}</span>"
    elif kind == "mon":
        # Основной акцент, а не TERTIARY: третья роль Material You намеренно
        # уходит в дополняющий оттенок и от синих обоев становится тёплой —
        # заголовок месяца выпадал из общей гаммы, хотя цвет был свежий.
        mk = f"<span foreground='{colors['ACCENT_HEX']}'><b>{esc(text)}</b></span>"
    elif kind == "blank":
        mk = text
    else:
        mk = f"<span foreground='{colors['ON_SURFACE']}'>{text}</span>"
    return mk, len(text)


def pad(pair, width):
    """Pad a (markup, visible_width) pair out to `width` visible columns."""
    mk, w = pair
    return mk + " " * max(0, width - w)


def month_block(y, m, colors, today, gap="  ", title=None):
    """One month as a list of (markup, visible_width) rows, all equal width."""
    wd = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
    rows = []

    head = title if title is not None else f"{calendar.month_name[m]} {y}"
    rows.append(cell(head, colors, "mon"))

    parts = [cell(d, colors, "wd") for d in wd]
    rows.append((gap.join(p[0] for p in parts),
                 sum(p[1] for p in parts) + len(gap) * (len(parts) - 1)))

    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(y, m):
        parts = []
        for day in week:
            if day == 0:
                parts.append(cell("  ", colors, "blank"))
            elif (y, m, day) == (today.year, today.month, today.day):
                parts.append(cell(f"{day:2d}", colors, "today"))
            else:
                parts.append(cell(f"{day:2d}", colors, "day"))
        rows.append((gap.join(p[0] for p in parts),
                     sum(p[1] for p in parts) + len(gap) * (len(parts) - 1)))

    width = max(w for _, w in rows)
    # Every month is padded to six week-rows so the year grid stays rectangular.
    while len(rows) < 8:
        rows.append(("", 0))
    return rows, width


def hint_lines(colors, lines):
    body = "\n".join(lines)
    return (f"<span foreground='{colors['OUTLINE']}' size='small'>{body}</span>")


def build_month(offset, colors, hint=True, pad_weeks=False):
    """Сетка месяца разметкой Pango.

    hint=False просит вернуть одну сетку без строки подсказок: попап
    (calendar_popup.py) рисует ту же сетку, но подсказки у него свои —
    в баре они про клики по модулю, а в попапе про колесо и Esc.

    pad_weeks=True добивает сетку до шести недельных строк. В месяце их
    выходит то пять, то шесть (август 2026 — шесть, сентябрь — пять), и окно
    попапа при листании прыгало по высоте. Подсказке это было безразлично:
    она и так появляется заново каждый раз.
    """
    today = datetime.date.today()
    y, m = today.year, today.month + offset
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1

    rows, width = month_block(y, m, colors, today, gap="  ")
    head = cell(f"{calendar.month_name[m]} {y}", colors, "mon")
    week_rows = [r[0] for r in rows[2:] if r[1]]
    if pad_weeks:
        # Пустая строка нужной ширины, иначе выравнивание уедет.
        while len(week_rows) < 6:
            week_rows.append(pad(("", 0), width))
    body_rows = [pad(head, width), "", rows[1][0]] + week_rows
    body = "\n".join(body_rows)

    # Hints are wrapped to roughly the grid width; a single long line was what
    # stretched the tooltip and left that empty gutter on the right.
    grid = f"<tt><span size='large'>{body}</span></tt>"
    if not hint:
        return grid
    # Подсказки под сеткой повторяют раскладку кнопок из config.jsonc.
    # Держать их в согласии обязательно: это единственное место, где видно,
    # какая кнопка что делает.
    tail = hint_lines(colors, ["scroll: month · left: popup",
                               "right: window · middle: swap"])
    return f"{grid}\n{tail}"


def build_year(offset_years, colors):
    today = datetime.date.today()
    y = today.year + offset_years

    blocks = []
    for m in range(1, 13):
        rows, width = month_block(y, m, colors, today, gap=" ",
                                  title=calendar.month_abbr[m])
        blocks.append((rows, width))

    col_gap = "   "
    out = [cell(str(y), colors, "mon")[0], ""]
    for r in range(0, 12, 3):
        triplet = blocks[r:r + 3]
        for row_i in range(8):
            pieces = [pad(rows[row_i], width) for rows, width in triplet]
            out.append(col_gap.join(pieces).rstrip())
        out.append("")
    body = "\n".join(out).rstrip()

    hint = hint_lines(colors, ["scroll: year",
                               "left: popup · right: window"])
    return f"<tt><span size='small'>{body}</span></tt>\n{hint}"


def poll():
    maybe_auto_reset()
    colors = read_facts()
    side = read_state(SIDE_FILE, "")
    own = os.environ.get("WAYBAR_OUTPUT_NAME", "")
    if not side:
        # First run ever: pick a stable default deterministically.
        side = sorted(outputs())[-1]
        write_state(SIDE_FILE, side)

    now = datetime.datetime.now()
    if own and own == side:
        text = f"{ICON_CAL} {now:%d.%m.%Y}"
    else:
        text = f"{ICON_TIME} {now:%H:%M}"

    # Ключа "tooltip" здесь больше нет: подсказка по наведению отключена
    # (tooltip: false в config.jsonc), сетку показывает попап по щелчку.
    # build_month()/build_year() остались — ими рисует попап.
    print(json.dumps({"text": text}))


def bump_offset(delta):
    # The offset counter means "months from today" in month view, and "years
    # from this year" in year view — build_month()/build_year() each read it
    # accordingly, so a scroll tick here is always +/-1 of whichever unit the
    # currently visible view actually uses.
    cur = int(read_state(OFFSET_FILE, "0") or 0)
    write_state(OFFSET_FILE, cur + delta)


def refresh_bars():
    subprocess.run(["pkill", "-RTMIN+9", "waybar"], capture_output=True)


def open_app():
    subprocess.Popen(["python3", CALENDAR_APP],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                      start_new_session=True)


def toggle_side():
    names = outputs()
    cur = read_state(SIDE_FILE, "")
    if len(names) <= 1:
        # Один монитор (ноутбук без MSI): «другого» нет, и раньше дата так и
        # оставалась датой (30.09.2026). Тогда переключаем его самого:
        # "none" в файле — дату не показывает никто, то есть здесь время.
        own = names[0] if names else ""
        write_state(SIDE_FILE, "none" if cur == own else own)
        touch()
        refresh_bars()
        return
    other = next((n for n in names if n != cur), names[0] if names else "")
    write_state(SIDE_FILE, other or cur)
    touch()
    refresh_bars()


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "poll"
    if arg == "open":
        touch()
        open_app()
    elif arg == "popup":
        # Мини-календарь окном, а не подсказкой: у GTK-подсказки своя задержка
        # наведения, её нельзя настроить ни из waybar, ни из CSS, и ждать
        # секунду ради взгляда на число было неудобно.
        touch()
        subprocess.Popen(["python3", CALENDAR_POPUP],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    elif arg == "yeartoggle":
        cur = read_state(YEARMODE_FILE, "0")
        write_state(YEARMODE_FILE, "0" if cur == "1" else "1")
        write_state(OFFSET_FILE, "0")
        touch()
        refresh_bars()
    elif arg == "toggleside":
        toggle_side()
    elif arg == "next":
        touch()
        bump_offset(1)
        refresh_bars()
    elif arg == "prev":
        touch()
        bump_offset(-1)
        refresh_bars()
    else:
        poll()


if __name__ == "__main__":
    main()
