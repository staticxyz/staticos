#!/usr/bin/env python3
"""«Панель задач» в баре под niri — окна текущего стола квадратными кнопками, как в XP. 30.09.2026.

Модуль waybar (custom/taskbar): у каждого монитора свой экземпляр (waybar ставит
WAYBAR_OUTPUT_NAME), он показывает окна АКТИВНОГО стола своего монитора — по кнопке
на окно, слева направо в порядке колонок ленты, плавающие в конце. Окно в фокусе —
кнопка «нажата» (кромки наоборот, «шахматка» 1 px, как у Windows 9x/XP); активное
окно стола на мониторе без фокуса — нажата вполсилы. Окно, требующее внимания, —
красная полоска внизу кнопки.

Waybar рисует модуль только текстом, поэтому кнопки — знаки шрифта JarvisTaskbar
(build_taskbar_font.py), наложенные друг на друга; значки — те же, что у столов,
по правилам window-rewrite из ~/.config/waybar/config.jsonc (разбор правил общий с
~/.config/niri/scripts/niri_bar.py). Окно без своего правила — пиксельное «окошко».

Режим — ~/.config/hypr/state/window-bar-mode:
    titles   (по умолчанию) — модуль пуст и скрыт, в баре заголовок окна
             (bar_window_title.py);
    taskbar  — панель задач, а заголовок должен молчать.

Щелчки. Waybar даёт один on-click на весь модуль, по какой кнопке щёлкнули — не
узнать. Поэтому: левый щелчок — следующее окно стола, правый — предыдущее,
колёсико — листать окна, средний — закрыть окно в фокусе этого стола.

Без опроса: читает поток событий niri (EventStream) и сам ведёт состояние по
событиям, печатает JSON только при изменении. Раз в 10 с сверяет время правки
палитры и файла режима (смена обоев событий niri не порождает).

    taskbar.py                       модуль waybar
    taskbar.py mode taskbar|titles|toggle   переключить режим (и разбудить модули)
    taskbar.py status|get            текущий режим
    taskbar.py next|prev|close       действия для on-click / on-scroll
"""
import html
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys

HOME = os.path.expanduser("~")
MODE_FILE = HOME + "/.config/hypr/state/window-bar-mode"
PALETTE = HOME + "/.cache/matugen/colors.json"
FONT_FILE = HOME + "/.local/share/fonts/JarvisTaskbar-Regular.otf"
FAMILY = "JarvisTaskbar 22px"
MODES = ("titles", "taskbar")

sys.path.insert(0, HOME + "/.config/niri/scripts")
from niri_bar import col_row, request, rewrite_rules  # noqa: E402  один разбор правил на весь бар

FILL, EDGE_TL, EDGE_BR, DITHER, URGENT = "", "", "", "", ""
GAP2, GAP4 = "", ""
GENERIC = ""
DIGITS = {**{str(i): chr(0xE530 + i) for i in range(10)}, "+": ""}

# Окна, которым не место в панели: плитки дашборда (scripts/dashboard, app-id dash-*).
SKIP_APP = re.compile(r"^dash-")

# Сколько кнопок влезает до pomo — тот же расчёт, что у bar_window_title.py
# (замеры по снимку бара, 1920 px): панель стоит там же, где был заголовок.
POMO_LEFT, GAP = 626, 16
WS_W, COL_W, BASE = 42, 14, 332 - 6 * 42 - 3 * 14
BTN_W = 24                           # кнопка 22 + промежуток 2
MIN_BTNS, MAX_BTNS = 4, 14

OUTPUT = os.environ.get("WAYBAR_OUTPUT_NAME")


# ── режим ───────────────────────────────────────────────────────────────────
def mode():
    try:
        v = open(MODE_FILE).read().strip()
        return v if v in MODES else "titles"
    except OSError:
        return "titles"


def set_mode(v):
    os.makedirs(os.path.dirname(MODE_FILE), exist_ok=True)
    with open(MODE_FILE + ".tmp", "w") as f:
        f.write(v + "\n")
    os.replace(MODE_FILE + ".tmp", MODE_FILE)
    wake_modules()


def wake_modules():
    """SIGUSR1 работающим модулям: панели задач и заголовку (перечитать режим).

    bar_window_title.py без своего обработчика от SIGUSR1 завершится, и waybar
    перезапустит его через restart-interval — тоже годится: при старте он
    перечитает режим.
    """
    me = os.getpid()
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            argv = open("/proc/%s/cmdline" % pid, "rb").read().split(b"\0")
        except OSError:
            continue
        args = [a.decode(errors="replace") for a in argv if a]
        if int(pid) == me or len(args) < 2 or not args[0].endswith("python3"):
            continue
        script = os.path.basename(args[1])
        if (script == "taskbar.py" and len(args) == 2) or script == "bar_window_title.py":
            try:
                os.kill(int(pid), signal.SIGUSR1)
            except OSError:
                pass


# ── палитра и шрифт ─────────────────────────────────────────────────────────
_pal = {"mtime": None, "c": {}}


def palette():
    try:
        m = os.path.getmtime(PALETTE)
        if m != _pal["mtime"]:
            _pal.update(mtime=m, c=json.load(open(PALETTE)))
    except (OSError, ValueError):
        pass
    c = _pal["c"]
    return {"primary": c.get("primary", "#b4c5ff"), "fg": c.get("on_surface", "#e1e1ef"),
            "error": c.get("error", "#ffb4ab"), "shadow": "#000000"}


_font = {"mtime": None, "codes": None}


def font_codes():
    """Коды, что есть в JarvisTaskbar; None — не удалось прочесть (тогда верим правилам)."""
    # fc-query, а не fontTools: тот один занимал бы ~13 МБ памяти модуля на весь сеанс.
    try:
        m = os.path.getmtime(FONT_FILE)
        if m != _font["mtime"]:
            out = subprocess.run(["fc-query", "--format", "%{charset}", FONT_FILE],
                                 capture_output=True, text=True, timeout=5).stdout
            codes = set()
            for part in out.split():
                a, _, b = part.partition("-")
                codes.update(range(int(a, 16), int(b or a, 16) + 1))
            _font.update(mtime=m, codes=codes or None)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return _font["codes"]


def glyph_for(win, rules):
    subject = "class<%s> title<%s>" % (win.get("app_id") or "", win.get("title") or "")
    g = next((g for rx, g in rules if rx.search(subject)), None)
    g = (g or "").strip()[:1]
    codes = font_codes()
    if not g or (codes is not None and ord(g) not in codes):
        return GENERIC
    return g


# ── разметка ────────────────────────────────────────────────────────────────
def span(color, alpha, text):
    return '<span foreground="%s" fgalpha="%d%%">%s</span>' % (color, alpha, text)


def button(glyph, state, urgent, p):
    """state: normal | focused (окно в фокусе) | active (активное окно стола на мониторе без фокуса)."""
    if state == "focused":
        parts = [span(p["primary"], 42, FILL), span(p["primary"], 38, DITHER),
                 span(p["shadow"], 60, EDGE_TL), span(p["fg"], 40, EDGE_BR),
                 span(p["fg"], 100, glyph)]
    elif state == "active":
        parts = [span(p["primary"], 24, FILL),
                 span(p["shadow"], 45, EDGE_TL), span(p["fg"], 25, EDGE_BR),
                 span(p["fg"], 90, glyph)]
    else:
        parts = [span(p["primary"], 14, FILL),
                 span(p["fg"], 32, EDGE_TL), span(p["shadow"], 55, EDGE_BR),
                 span(p["fg"], 75, glyph)]
    if urgent:
        parts.insert(-1, span(p["error"], 100, URGENT))
    return "".join(parts)


def chip(n, p):
    return span(p["fg"], 70, "".join(DIGITS[ch] for ch in "+%d" % n))


def fit(n_ws, n_cols):
    start = BASE + WS_W * n_ws + COL_W * max(n_cols, 1)
    return max(MIN_BTNS, min(MAX_BTNS, (POMO_LEFT - GAP - start) // BTN_W))


def window_order(ws, wins):
    return sorted((w for w in wins.values()
                   if w.get("workspace_id") == ws["id"] and not SKIP_APP.match(w.get("app_id") or "")),
                  key=col_row)


def render(wss, wins, output):
    empty = {"text": "", "tooltip": "", "class": "off"}
    if mode() != "taskbar":
        return empty
    mine_ws = [w for w in wss.values() if output is None or w.get("output") == output]
    ws = next((w for w in mine_ws if w.get("is_active")), None)
    if not ws:
        return empty
    mine = window_order(ws, wins)
    if not mine:
        return {"text": "", "tooltip": "", "class": "empty"}
    p = palette()
    rules, _ = rewrite_rules()
    here = ws.get("active_window_id")
    cols = len({(w.get("layout") or {}).get("pos_in_scrolling_layout", [0])[0]
                for w in mine if (w.get("layout") or {}).get("pos_in_scrolling_layout")})

    limit, n = fit(len(mine_ws), cols), len(mine)
    at = next((i for i, w in enumerate(mine) if w["id"] == here), 0)
    start, shown = 0, n
    if n > limit:
        shown = max(1, limit - 1)                       # одно место — под «+N»
        start = max(0, min(at - shown // 2, n - shown))
        if 0 < start and start + shown < n:             # скрытые с обеих сторон — два «+N»
            shown = max(1, limit - 2)
            start = max(0, min(at - shown // 2, n - shown))
    left, right = start, n - start - shown

    parts = []
    if left:
        parts.append(chip(left, p) + GAP4)
    for w in mine[start:start + shown]:
        state = "focused" if w.get("is_focused") else ("active" if w["id"] == here else "normal")
        parts.append(button(glyph_for(w, rules), state, w.get("is_urgent"), p))
    text = GAP2.join(parts)
    if right:
        text += GAP4 + chip(right, p)

    lines = []
    for w in mine:
        mark = "▸ " if w["id"] == here else "   "
        title = (w.get("title") or w.get("app_id") or "?").strip()
        if len(title) > 70:
            title = title[:69] + "…"
        lines.append(mark + html.escape(title) + ("  ⚑" if w.get("is_urgent") else ""))
    tip = "Панель задач — окон: %d\n%s\n\n<small>ЛКМ/колёсико — следующее окно, ПКМ — предыдущее,\nсредняя — закрыть окно в фокусе</small>" % (n, "\n".join(lines))
    cls = ["taskbar"] + (["overflow"] if n > shown else [])
    return {"text": '<span font="%s" weight="normal">%s</span>' % (FAMILY, text), "tooltip": tip, "class": cls}


# ── состояние по событиям niri ──────────────────────────────────────────────
def apply(ev, wss, wins):
    """Обновить wss/wins по событию. False — событие панели не касается."""
    (kind, v), = ev.items()
    if kind == "WorkspacesChanged":
        wss.clear()
        wss.update({w["id"]: w for w in v["workspaces"]})
    elif kind == "WorkspaceActivated":
        ws = wss.get(v["id"])
        if ws:
            for w in wss.values():
                if w.get("output") == ws.get("output"):
                    w["is_active"] = w["id"] == v["id"]
                if v.get("focused"):
                    w["is_focused"] = w["id"] == v["id"]
    elif kind == "WorkspaceActiveWindowChanged":
        if v["workspace_id"] in wss:
            wss[v["workspace_id"]]["active_window_id"] = v["active_window_id"]
    elif kind == "WindowsChanged":
        wins.clear()
        wins.update({w["id"]: w for w in v["windows"]})
    elif kind == "WindowOpenedOrChanged":
        w = v["window"]
        if w.get("is_focused"):
            for x in wins.values():
                x["is_focused"] = False
        wins[w["id"]] = w
    elif kind == "WindowClosed":
        wins.pop(v["id"], None)
    elif kind == "WindowFocusChanged":
        for x in wins.values():
            x["is_focused"] = x["id"] == v["id"]
    elif kind == "WindowUrgencyChanged":
        if v["id"] in wins:
            wins[v["id"]]["is_urgent"] = v["urgent"]
    elif kind == "WindowLayoutsChanged":
        for wid, layout in v["changes"]:
            if wid in wins:
                wins[wid]["layout"] = layout
    else:
        return False
    return True


def run_module():
    if not os.environ.get("NIRI_SOCKET"):           # не niri (Hyprland) — молчим
        print(json.dumps({"text": ""}), flush=True)
        signal.pause()
        return 0
    wss, wins, last = {}, {}, [None]

    def emit():
        try:
            out = json.dumps(render(wss, wins, OUTPUT), ensure_ascii=False)
        except Exception as e:                       # сломанная палитра/правило — не ронять модуль
            out = json.dumps({"text": "", "tooltip": "taskbar.py: %s" % html.escape(str(e))})
        if out != last[0]:
            last[0] = out
            print(out, flush=True)

    # SIGUSR1 (смена режима) будит select через self-pipe.
    rfd, wfd = os.pipe()
    os.set_blocking(wfd, False)
    signal.set_wakeup_fd(wfd)
    signal.signal(signal.SIGUSR1, lambda *_: None)

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall(b'"EventStream"\n')
    buf, stamp = b"", None
    while True:
        r, _, _ = select.select([s, rfd], [], [], 10)
        if rfd in r:
            os.read(rfd, 512)
            emit()
        if s in r:
            chunk = s.recv(1 << 16)
            if not chunk:
                return 1                              # niri закрыл поток — waybar перезапустит
            buf += chunk
            *lines, buf = buf.split(b"\n")
            changed = False
            for line in lines:
                if line.strip():
                    try:
                        changed |= apply(json.loads(line), wss, wins)
                    except (ValueError, KeyError, TypeError):
                        pass
            if changed:
                emit()
        if not r:                                     # тишина 10 с: не сменились ли обои или режим
            try:
                now = (os.path.getmtime(PALETTE), os.path.getmtime(MODE_FILE) if os.path.exists(MODE_FILE) else 0)
            except OSError:
                now = None
            if now != stamp:
                stamp = now
                emit()


# ── действия по щелчку ──────────────────────────────────────────────────────
def my_workspace():
    wss = request("Workspaces")["Workspaces"]
    out = OUTPUT or (request("FocusedOutput").get("FocusedOutput") or {}).get("name")
    return next((w for w in wss if w.get("output") == out and w.get("is_active")), None)


def action(cmd):
    ws = my_workspace()
    if not ws:
        return 1
    wins = {w["id"]: w for w in request("Windows")["Windows"]}
    mine = window_order(ws, wins)
    here = ws.get("active_window_id")
    if cmd == "close":
        if here is not None:
            request({"Action": {"CloseWindow": {"id": here}}})
        return 0
    if not mine:
        return 0
    at = next((i for i, w in enumerate(mine) if w["id"] == here), -1)
    step = 1 if cmd == "next" else -1
    target = mine[(at + step) % len(mine)] if at >= 0 else mine[0]
    request({"Action": {"FocusWindow": {"id": target["id"]}}})
    return 0


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cmd:
        return run_module()
    if cmd in ("status", "get"):
        print(mode())
        return 0
    if cmd == "mode":
        v = sys.argv[2] if len(sys.argv) > 2 else ""
        if v == "toggle":
            v = "titles" if mode() == "taskbar" else "taskbar"
        if v not in MODES:
            print("режимы: " + ", ".join(MODES) + ", toggle", file=sys.stderr)
            return 2
        set_mode(v)
        print(v)
        return 0
    if cmd in ("next", "prev", "close"):
        return action(cmd)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
