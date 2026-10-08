#!/usr/bin/env python3
"""Окно проверки «не спите?» и окно звонка будильника — во весь экран, на всех мониторах.

08.10.2026, Просьба: «выключить будильник кнопкой можно в полусне — пусть надо набрать текст,
чтобы чуть задумался. Раскладку менять самому, но она должна быть видна. Один неверный
символ — дальше не пускать». Поэтому:
  * фраза из набора (русские, английские и смешанные — раскладку иногда надо переключить),
    текущая раскладка крупно рядом (niri msg keyboard-layouts);
  * неверный символ не принимается: клетка вспыхивает красным, курсор стоит, пока не
    набран верный; Backspace не нужен;
  * Escape и закрытие окна ничего не делают — окно уходит само, когда проверка пройдена,
    подтверждена кодом в Telegram или вышло время.

Всё рисует cairo; `wake_overlay.py --shot F.png [mode=check|ring] [typed=N] [err=1] [w= h=]`
— снимок без окна (для проверок).
"""
import os
import subprocess
import sys
import time

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

FONT = "PxPlus HP 100LX 6x8 Jarvis"
LAYOUT_SHORT = {"English (US)": "EN", "Russian": "RU"}


def theme():
    """Цвета и стиль — как у Discipline (state/settings-skin)."""
    try:
        import routine_app as ra
        return ra.colors(ra.style_name())
    except Exception:
        w = (0.88, 0.88, 0.94)
        a = (0.71, 0.77, 1.0)
        return dict(acc=a, acc_l=a, acc_d=(0.35, 0.4, 0.6), bg=(0.06, 0.07, 0.1), text=w,
                    dim=(0.6, 0.6, 0.68), faint=(0.35, 0.36, 0.42), field=(0.11, 0.12, 0.16),
                    line=(0.2, 0.21, 0.27), err=(1.0, 0.7, 0.67), frame="round")


def keyboard_layout():
    try:
        import json
        r = subprocess.run(["niri", "msg", "-j", "keyboard-layouts"], capture_output=True,
                           text=True, timeout=2)
        d = json.loads(r.stdout)
        name = d["names"][d["current_idx"]]
        return LAYOUT_SHORT.get(name, name[:2].upper())
    except Exception:
        return "?"


# ── рисунок ───────────────────────────────────────────────────────────────────

class Paint:
    def __init__(self, cr):
        self.cr = cr

    def rgb(self, c, a=1.0):
        self.cr.set_source_rgba(c[0], c[1], c[2], a)

    def rect(self, x, y, w, h, c, a=1.0):
        self.rgb(c, a)
        self.cr.rectangle(x, y, w, h)
        self.cr.fill()

    def box(self, x, y, w, h, c, lw=1):
        self.rgb(c)
        self.cr.set_line_width(lw)
        self.cr.rectangle(x + lw / 2, y + lw / 2, w - lw, h - lw)
        self.cr.stroke()

    def lay(self, s, px):
        lay = PangoCairo.create_layout(self.cr)
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(s, -1)
        return lay

    def size(self, s, px):
        return self.lay(s, px).get_pixel_size()

    def text(self, x, y, s, c, px, align="l", a=1.0):
        lay = self.lay(s, px)
        w, _h = lay.get_pixel_size()
        if align == "c":
            x -= w / 2
        elif align == "r":
            x -= w
        self.rgb(c, a)
        self.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(self.cr, lay)
        return w


DOT_COL = {"ok": "acc", "fail": "err", "off": "faint", "wait": "faint"}


def draw(cr, w, h, st, c):
    """st: mode (check|ring), head, title, sub, phrase, typed, err (символ или ""),
    err_on (bool), caps (bool), layout, left (с), steps [(state, метка)], cur, tg (строка),
    clock."""
    p = Paint(cr)
    ring = st["mode"] == "ring"
    p.rect(0, 0, w, h, c["bg"], 0.96 if not ring else 0.985)
    cx = w / 2
    # крупные часы: при звонке — акцент, на проверке — спокойнее
    big = 96 if h >= 700 else 64
    y = h * 0.16
    p.text(cx, y, st["head"], c["acc"] if not ring else c["err"], 16, "c")
    y += 32
    p.text(cx, y, st["clock"], c["acc_l"] if ring else c["text"], big, "c")
    y += big + 28
    p.text(cx, y, st["title"], c["text"], 24, "c")
    y += 40
    if st.get("sub"):
        p.text(cx, y, st["sub"], c["dim"], 16, "c")
    y += 52

    # фраза: по клеткам, набранное — акцентом, курсор — рамка, ошибка — красная клетка
    phrase, typed = st["phrase"], st["typed"]
    px = 32
    cw, chh = p.size("M", px)
    if cw * len(phrase) > w - 120:
        px = 24
        cw, chh = p.size("M", px)
    pad = 10
    total = cw * len(phrase)
    x0 = round(cx - total / 2)
    p.rect(x0 - 24, y - pad, total + 48, chh + pad * 2, c["field"])
    for i, ch in enumerate(phrase):
        x = x0 + i * cw
        if i < typed:
            col = c["acc_l"]
        elif i == typed:
            col = c["text"]
        else:
            col = c["dim"]
        if i == typed:
            if st.get("err_on"):
                p.rect(x - 1, y - 4, cw + 2, chh + 8, c["err"], 0.35)
                p.box(x - 1, y - 4, cw + 2, chh + 8, c["err"], 2)
            elif int(time.monotonic() * 2) % 2 == 0 or st.get("still"):
                p.box(x - 1, y - 4, cw + 2, chh + 8, c["acc"], 2)
            if ch == " ":
                p.rect(x + 3, y + chh - 6, cw - 6, 2, c["dim"])
        p.text(x, y, ch, col, px)
    y += chh + pad * 2 + 18
    # строка под фразой: что набрано не так, Caps Lock
    if st.get("err_on") and st.get("err"):
        msg = "набрано «%s» — нужно «%s»" % (st["err"], "пробел" if phrase[typed] == " " else phrase[typed])
        if st.get("caps"):
            msg += " · Caps Lock?"
        p.text(cx, y, msg, c["err"], 16, "c")
    else:
        p.text(cx, y, "%d из %d" % (typed, len(phrase)), c["faint"], 16, "c")
    y += 44

    # раскладка — крупно, видно во время набора
    lay = st.get("layout") or "?"
    lw, lh = p.size(lay, 24)
    tw = p.size("раскладка", 16)[0]
    bx = round(cx - (tw + 16 + lw + 24) / 2)
    p.text(bx, y + 4, "раскладка", c["dim"], 16)
    px0 = bx + tw + 16
    p.rect(px0, y - 4, lw + 24, lh + 8, c["acc"] if lay == "RU" else c["acc_d"])
    p.text(px0 + 12, y, lay, c["bg"] if lay == "RU" else c["text"], 24)
    y += lh + 44

    # точки шагов серии: ● пройден · ✗ проспал · ◻ текущий · ○ впереди
    steps = st.get("steps") or []
    if steps:
        gap = 112
        sx = cx - gap * (len(steps) - 1) / 2
        for i, (state, label) in enumerate(steps):
            x = sx + i * gap
            col = c[DOT_COL.get(state, "faint")]
            if i == st.get("cur"):
                col = c["err"] if ring else c["acc"]
                p.box(x - 9, y - 9, 18, 18, col, 2)
            elif state == "ok":
                p.rect(x - 6, y - 6, 12, 12, col)
            elif state == "fail":
                p.text(x, y - 9, "×", col, 16, "c")
            else:
                p.box(x - 5, y - 5, 10, 10, col)
            p.text(x, y + 16, label, c["text"] if i == st.get("cur") else c["faint"], 16, "c")
        y += 64
    # низ: сколько осталось и про Telegram
    left = st.get("left")
    if left is not None:
        m, s = divmod(max(0, int(left)), 60)
        tail = st.get("tail") or ("потом звонок" if not ring else "до следующей проверки")
        p.text(cx, y, "осталось %d:%02d — %s" % (m, s, tail), c["acc"] if not ring else c["dim"], 16, "c")
        y += 30
    if st.get("tg"):
        p.text(cx, y, st["tg"], c["faint"], 16, "c")


# ── окна ──────────────────────────────────────────────────────────────────────

class Overlay:
    """Окна на всех мониторах. Набор общий: печатать можно в любом."""

    def __init__(self, on_done):
        gi.require_version("GtkLayerShell", "0.1")
        from gi.repository import GtkLayerShell
        self.LS = GtkLayerShell
        self.on_done = on_done
        self.c = theme()
        self.wins = []
        self.st = None
        self.err_t = 0
        self.layout = keyboard_layout()
        self.lay_t = 0

    def show(self, st):
        """st — как в draw(); phrase/typed хранятся здесь между обновлениями."""
        same = self.st and self.st.get("key") == st.get("key")
        if same:
            st["typed"] = self.st["typed"]
            st["err"] = self.st.get("err", "")
            st["caps"] = self.st.get("caps", False)
        else:
            st.setdefault("typed", 0)
            self.err_t = 0
        self.st = st
        if not self.wins:
            self.open()
        for win, area in self.wins:
            area.queue_draw()

    def open(self):
        LS = self.LS
        display = Gdk.Display.get_default()
        mons = [display.get_monitor(i) for i in range(display.get_n_monitors())] or [None]
        for mon in mons:
            win = Gtk.Window(title="Будильник")
            LS.init_for_window(win)
            LS.set_namespace(win, "jarvis-wake-alarm")
            LS.set_layer(win, LS.Layer.OVERLAY)
            if mon is not None:
                LS.set_monitor(win, mon)
            for e in (LS.Edge.TOP, LS.Edge.BOTTOM, LS.Edge.LEFT, LS.Edge.RIGHT):
                LS.set_anchor(win, e, True)
            LS.set_exclusive_zone(win, -1)
            LS.set_keyboard_mode(win, LS.KeyboardMode.EXCLUSIVE)
            win.set_app_paintable(True)
            area = Gtk.DrawingArea()
            area.connect("draw", self.on_draw)
            win.add(area)
            win.connect("key-press-event", self.on_key)
            win.connect("delete-event", lambda *_: True)    # закрыть нельзя
            win.show_all()
            self.wins.append((win, area))
        GLib.timeout_add(250, self.tick)

    def hide(self):
        for win, _a in self.wins:
            win.destroy()
        self.wins = []
        self.st = None

    def tick(self):
        if not self.wins:
            return False
        now = time.monotonic()
        if now - self.lay_t > 0.4:
            self.lay_t = now
            self.layout = keyboard_layout()
        for _w, area in self.wins:
            area.queue_draw()
        return True

    def on_draw(self, area, cr):
        if not self.st:
            return
        st = dict(self.st)
        st["layout"] = self.layout
        st["err_on"] = time.monotonic() < self.err_t
        st["clock"] = time.strftime("%H:%M")
        if st.get("until"):
            st["left"] = st["until"] - time.time()
        draw(cr, area.get_allocated_width(), area.get_allocated_height(), st, self.c)

    def on_key(self, _w, ev):
        st = self.st
        if not st or st["typed"] >= len(st["phrase"]):
            return True
        if ev.state & (Gdk.ModifierType.CONTROL_MASK | Gdk.ModifierType.MOD1_MASK |
                       Gdk.ModifierType.SUPER_MASK):
            return True
        u = Gdk.keyval_to_unicode(ev.keyval)
        if not u:
            return True                     # Shift, смена раскладки и прочие без знака
        ch = chr(u)
        want = st["phrase"][st["typed"]]
        if ch == want:
            st["typed"] += 1
            self.err_t = 0
            if st["typed"] >= len(st["phrase"]):
                self.on_done()
        else:
            st["err"] = "пробел" if ch == " " else ch
            st["caps"] = ch.lower() == want and ch != want
            self.err_t = time.monotonic() + 0.9
        self.layout = keyboard_layout()
        for _w, area in self.wins:
            area.queue_draw()
        return True


# ── снимок для проверок ──────────────────────────────────────────────────────

def shot(path, args):
    import cairo
    kv = dict(a.split("=", 1) for a in args if "=" in a)
    w, h = int(kv.get("w", 1920)), int(kv.get("h", 1080))
    mode = kv.get("mode", "check")
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    cr = cairo.Context(surf)
    phrase = kv.get("phrase", "доброе утро sir пора вставать")
    typed = int(kv.get("typed", 9))
    st = dict(mode=mode, phrase=phrase, typed=typed, still=True,
              head="ПРОВЕРКА · ПОВТОР 1 ИЗ 3" if mode == "check" else "БУДИЛЬНИК · 11:10",
              title="Не спите, сэр? Наберите фразу." if mode == "check"
              else "Доброе утро, сэр. Наберите фразу — звонок замолчит.",
              sub="подтвердите, что встали: звонок в 11:10 не прозвучит" if mode == "check"
              else "раскладку переключайте сами",
              err="а" if kv.get("err") else "", err_on=bool(kv.get("err")), caps=False,
              layout=kv.get("layout", "RU"), left=95 if mode == "check" else 412,
              steps=[("ok", "10:55"), ("wait" if mode == "check" else "fail", "11:10"),
                     ("wait", "11:20"), ("wait", "11:30")],
              cur=1, clock=kv.get("clock", "11:08"),
              tg="или ответом на пример в Telegram")
    draw(cr, w, h, st, theme())
    surf.write_to_png(path)
    print(path)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--shot":
        shot(sys.argv[2], sys.argv[3:])
    else:
        print(__doc__)
