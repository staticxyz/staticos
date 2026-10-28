#!/usr/bin/env python3
"""Полоса заголовка как у Настроек — для окон, что рисуют себя cairo. 29.10.2026.

Пользователь (снимок Настроек): «сделай вот такую же полосу всем приложениям как в
настройках, у которых всё ещё такой вариант» — у hub, Clocker, App list и WhatsApp
вместо полосы был одинокий «×» в строке вкладок. Теперь сверху полоса высотой
TITLE_H (как TITLE_H в settings_app.py): значок, название, «развернуть» и «закрыть».
Тона — те же, что у Настроек в каждом стиле: Default — градиент «Пуска» XP-панели
(xpbar_colors), Skeet — тёмная с двойной линией снизу, Beta — плоская. Кнопки —
close_cap (одна кнопка на всю систему), «развернуть» — тот же квадрат со значком.

    height()                                  высота полосы
    draw(cr, style, x, y, w, glyph, title, hover, maxed, active, r=0) → hits
        hits — [((x, y, w, h), "max" | "close" | "title"), …]; r — скругление
        верхних углов (окно со скруглённой рамкой)
    toggle_max(win)                           развернуть / вернуть (в раскладку niri
                                              колонкой во всю ширину / снова плавающим)
    on_title(win, ev)                         щелчок по полосе: двойной — развернуть,
                                              иначе тащить окно

В режиме «стопка» полосу рисует stack_bars.py — окна её тогда не рисуют.
"""
import json
import math
import os
import subprocess

import cairo
import gi

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

import close_cap  # noqa: E402

TITLE_H = 24
ICON_FONT = "JetBrainsMono Nerd Font"


def height():
    return TITLE_H


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _font():
    try:
        from gi.repository import Gtk
        return Gtk.Settings.get_default().get_property("gtk-font-name").rsplit(" ", 1)[0]
    except Exception:
        return "PxPlus HP 100LX 6x8"


_FONT = []


def _text(cr, x, y, s, col, px, family=None, shadow=None, maxw=None):
    if not _FONT:
        _FONT.append(_font())
    lay = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(family or _FONT[0])
    fd.set_absolute_size(px * Pango.SCALE)
    lay.set_font_description(fd)
    lay.set_text(s, -1)
    if maxw:
        lay.set_width(int(max(1, maxw) * Pango.SCALE))
        lay.set_ellipsize(Pango.EllipsizeMode.END)
    w, h = lay.get_pixel_size()
    ty = round(y - h / 2)
    if shadow is not None:
        cr.set_source_rgb(*shadow)
        cr.move_to(round(x) + 1, ty + 1)
        PangoCairo.show_layout(cr, lay)
    cr.set_source_rgb(*col)
    cr.move_to(round(x), ty)
    PangoCairo.show_layout(cr, lay)
    return w


def _top_round(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.move_to(x, y + h)
    cr.line_to(x, y + r)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.line_to(x + w, y + h)
    cr.close_path()


def draw(cr, style, x, y, w, glyph, title, hover=None, maxed=False, active=True, r=0):
    style = style if style in ("skeet", "beta") else "default"
    C = close_cap.colors(style)
    h = TITLE_H
    cr.save()
    if r:
        _top_round(cr, x, y, w, h, r)
        cr.clip()
    shadow = None
    if style == "default":
        g = cairo.LinearGradient(0, y, 0, y + h)
        for at, k in ((0, "st_hi"), (0.12, "st_top"), (0.5, "st_mid"), (0.88, "st_bot"), (1, "line2")):
            g.add_color_stop_rgb(at, *C[k])
        cr.set_source(g)
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgb(*C["st_dark"])
        cr.rectangle(x, y + h - 1, w, 1)
        cr.fill()
        ink = icon = C["on_surface"]
        shadow, px = C["st_dark"], 16
    elif style == "skeet":
        cr.set_source_rgb(*C["line3"])
        cr.rectangle(x, y + h - 1, w, 1)
        cr.fill()
        cr.set_source_rgb(*C["line2"])
        cr.rectangle(x, y + h - 2, w, 1)
        cr.fill()
        ink = C["text"] if active else C["dim"]
        icon = C["icon_on"] if active else C["dim"]
        px = 12
    else:
        cr.set_source_rgb(*C["bar"])
        cr.rectangle(x, y, w, h)
        cr.fill()
        cr.set_source_rgb(*C["line"])
        cr.rectangle(x, y + h - 1, w, 1)
        cr.fill()
        ink, icon, px = C["text"], C["acc_text"], 16
    cr.restore()
    hits = []
    s = close_cap.size(style)
    cy = y + (h - s) // 2
    cx = x + w - 3 - s
    close_cap.draw(cr, style, C, cx, cy, hover == "close")
    hits.append(((cx, cy, s, s), "close"))
    mx = cx - 2 - s
    mg = close_cap.RESTORE_BMP if maxed else close_cap.MAX_BMP
    if style == "default":                  # как button.xp-cap Настроек: нейтральная, не красная
        top, mid, bot = ((C["st_hi"], C["st_top"], C["st_mid"]) if hover == "max"
                         else (C["st_hover"], C["st_mid"], C["st_bot"]))
        g = cairo.LinearGradient(0, cy, 0, cy + s)
        g.add_color_stop_rgb(0, *top)
        g.add_color_stop_rgb(0.6, *mid)
        g.add_color_stop_rgb(1, *bot)
        cr.set_source(g)
        cr.rectangle(mx, cy, s, s)
        cr.fill()
        cr.set_source_rgb(*_mix(C["st_mid"], C["on_surface"], 0.55))
        cr.set_line_width(1)
        cr.rectangle(mx + 0.5, cy + 0.5, s - 1, s - 1)
        cr.stroke()
        cr.set_source_rgb(*C["on_surface"])
        close_cap._bitmap(cr, mg, mx + (s - 7) // 2, cy + (s - 7) // 2)
    else:
        close_cap.draw(cr, style, C, mx, cy, hover == "max", glyph=mg,
                       hover_ink=C.get("acc_l") or C.get("acc"))
    hits.append(((mx, cy, s, s), "max"))
    tx = x + 6
    if glyph:
        tx += _text(cr, tx, y + h / 2, glyph, icon, px, ICON_FONT, shadow) + 6
    _text(cr, tx, y + h / 2, title, ink, px, shadow=shadow, maxw=mx - 6 - tx)
    hits.append(((x, y, mx - x, h), "title"))
    return hits


def _maxed(win):
    try:
        from gi.repository import Gdk
        gw = win.get_window()
        return bool(gw and gw.get_state() & Gdk.WindowState.MAXIMIZED)
    except Exception:
        return False


def _niri(*args):
    return subprocess.run(["niri", "msg", *args], capture_output=True, text=True, timeout=2).stdout


def _niri_win(win):
    """Своё окно в niri: {id, is_floating, …} (в фокусе, иначе первое этого процесса)."""
    try:
        wins = [w for w in json.loads(_niri("--json", "windows")) if w.get("pid") == os.getpid()]
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return next((w for w in wins if w.get("is_focused")), None) or (wins[0] if wins else None)


def is_maxed(win):
    if float_maxed(win):
        return True
    w = _niri_win(win) if os.environ.get("NIRI_SOCKET") else None
    return (not w["is_floating"]) if w else _maxed(win)


def float_maxed(win):
    """Развёрнуто плавающим (toggle_max): помним прежнее место — значит, развёрнуто."""
    return getattr(win, "_ts_rect", None) is not None


def _win_by_id(wid):
    try:
        return next((w for w in json.loads(_niri("--json", "windows")) if w["id"] == wid), None)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _rect(w):
    p = (w.get("layout") or {}).get("tile_pos_in_workspace_view")
    s = (w.get("layout") or {}).get("window_size")
    return [int(p[0]), int(p[1]), int(s[0]), int(s[1])] if p and s else None


def _settle(wid, test, tries=12):
    """Ждать, пока niri применит действие (test(окно) — истина), до ~0.6 с."""
    import time
    w = None
    for _ in range(tries):
        time.sleep(0.05)
        w = _win_by_id(wid)
        if w and test(w):
            break
    return w


def _output_of(w):
    try:
        ws = next(x for x in json.loads(_niri("--json", "workspaces")) if x["id"] == w["workspace_id"])
        return ws.get("output")
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return None


def _max_top(out):
    """Отступ сверху под островок — та же настройка, что у стопки («Развёрнутое окно»)."""
    try:
        import stack_mode
        return int(stack_mode.max_top(out))
    except Exception:
        return 0


def _float_full(wid, out):
    """Плавающее окно wid — на весь экран, как развёрнутое в стопке: от края до края, сверху
    до нижней панели; под островком, если в Настройках «Развёрнутое окно — Под островком»
    (stack_mode.max_top). Поверх всех окон — оно плавающее (Пользователь 29.10).
    Рабочая область — по center-window: niri ставит плитку в центр области без нижней панели,
    значит ширина = 2·x + плитка, высота = 2·y + плитка (29.10: (8, 22) при 1904×1001 → 1920×1045)."""
    _niri("action", "center-window", "--id", str(wid))
    w = _settle(wid, lambda w: False, tries=4)
    lay = (w or {}).get("layout") or {}
    p, ts, ws = lay.get("tile_pos_in_workspace_view"), lay.get("tile_size"), lay.get("window_size")
    if not (p and ts and ws):
        return False
    aw, ah = round(2 * p[0] + ts[0]), round(2 * p[1] + ts[1])
    bw, bh = round(ts[0] - ws[0]), round(ts[1] - ws[1])          # рамка niri вокруг окна
    t = _max_top(out)
    size = [aw - bw, ah - t - bh]
    if size[0] < 200 or size[1] < 200:
        return False
    _niri("action", "set-window-width", "--id", str(wid), str(size[0]))
    _niri("action", "set-window-height", "--id", str(wid), str(size[1]))
    _settle(wid, lambda w: (_rect(w) or [0] * 4)[2:] == size)
    _niri("action", "move-floating-window", "--id", str(wid), "-x", "0", "-y", str(t))
    return True


def toggle_max(win):
    """Развернуть / вернуть. Окна title_strip в niri плавают (open-floating). Плавающее окно
    niri разворачивает до краёв экрана — поверх островка и бара (Пользователь 29.10: «разворачиваются
    вот так»), а развёрнутое в раскладку уходит ПОД плавающие окна (терминал поверх него —
    «всё ещё неправильно»). Поэтому «развернуть» = остаться плавающим, но встать в рабочий
    прямоугольник на весь экран до нижней панели (под островком — по настройке) — поверх всего;
    «вернуть» = прежние размер и место (win._ts_rect)."""
    w = _niri_win(win) if os.environ.get("NIRI_SOCKET") else None
    if w is None:
        (win.unmaximize if _maxed(win) else win.maximize)()
        return
    if getattr(win, "_ts_busy", False):
        return
    win._ts_busy = True
    # В потоке: окно должно успеть принять новый размер (главный цикл GTK не стоит)
    import threading
    threading.Thread(target=_toggle_work, args=(win, w), daemon=True).start()


def _toggle_work(win, w):
    from gi.repository import GLib
    wid = w["id"]
    old = getattr(win, "_ts_rect", None)
    rect = old
    try:
        if old is not None:
            rect = None
            if not w["is_floating"]:
                _niri("action", "toggle-window-floating", "--id", str(wid))
                _settle(wid, lambda x: x["is_floating"])
            _niri("action", "set-window-width", "--id", str(wid), str(old[2]))
            _niri("action", "set-window-height", "--id", str(wid), str(old[3]))
            _niri("action", "move-floating-window", "--id", str(wid), "-x", str(old[0]), "-y", str(old[1]))
        elif not w["is_floating"]:
            _niri("action", "toggle-window-floating", "--id", str(wid))   # развёрнутое по-старому
        else:
            r = _rect(w)
            if r and _float_full(wid, _output_of(w)):
                rect = r
    except (OSError, subprocess.SubprocessError):
        pass
    GLib.idle_add(_toggle_done, win, rect)


def _toggle_done(win, rect):
    win._ts_rect = rect
    win._ts_busy = False
    m = rect is not None
    view = getattr(win, "view", None)
    if view is not None and hasattr(view, "maxed"):
        view.maxed = m
        win.queue_draw()
    hook = getattr(win, "_ts_after_max", None)
    if hook:
        hook(m)
    return False


def on_title(win, ev):
    """Щелчок по полосе (не по кнопкам): двойной — развернуть, одиночный — тащить."""
    from gi.repository import Gdk
    if ev.button != 1:
        return
    if ev.type == getattr(Gdk.EventType, "DOUBLE_BUTTON_PRESS", Gdk.EventType._2BUTTON_PRESS):
        toggle_max(win)
    elif ev.type == Gdk.EventType.BUTTON_PRESS:
        win.begin_move_drag(1, int(ev.x_root), int(ev.y_root), ev.time)


if __name__ == "__main__":
    import sys
    st = sys.argv[1] if len(sys.argv) > 1 else "skeet"
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, 480, TITLE_H)
    cr = cairo.Context(surf)
    cr.set_source_rgb(0.08, 0.08, 0.09)
    cr.paint()
    draw(cr, st, 0, 0, 480, "\U000f0493", "Проверка", hover="close")
    out = sys.argv[2] if len(sys.argv) > 2 else "/tmp/title-strip-%s.png" % st
    surf.write_to_png(out)
    print(out)
