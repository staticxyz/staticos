#!/usr/bin/env python3
"""Окно «новая надпись» — «Banner.exe», родня Preset.exe и Timer.exe. 19.10.2026.

    banner_ask.py [ТЕКСТ]   спросить текст и эффекты; напечатать JSON
                            {"text": …, "fx": «флаги», "pace": скорость} (пусто — отмена)

Просьба: «окно создания виджета баннера сделай с рамками стиля Skeet, и он должен
соответствовать выбранной теме системы… я должен иметь возможность создавать просто
статичный текст и все. По дефолту он должен быть. И дополнительно выбрать вот эти
настройки [флаги `text`], можно отдельно, можно все вместе. Можно как галочки».
Прежнее окно — rofi -dmenu (desktop_widgets.py add banner ask=1).

Окно — preset_ask.Dialog: те же рамки трёх стилей (стиль — state/clipboard-style, его
держит system_style.py), заголовок, поле ввода, цвета буфера обмена. Своё: группа
«Эффекты» — девять галочек (флаги banner_fx.LABELS; «Бег ←» и «Бег →» друг друга
снимают) и ряд «Скорость» (-s), группа «Превью» — надпись, как она встанет на обои
(рисует banner_fx.paint — та же функция, что у виджета). Ничего не отмечено —
статичный текст.

Клавиши
    печатать, ←/→, Backspace, Ctrl+W/U/V…   — поле (как у Preset.exe)
    Tab / Shift+Tab, ↓ / ↑                  — поле → галочки → скорость
    стрелки, h/j/k/l                        — по галочкам; в ряду скорости ←/→ — выбор
    Пробел, x                               — отметить галочку
    Alt+1…9                                 — отметить галочку из любого места
    Enter                                   — создать
    Esc, крестик, щелчок мимо окна          — отмена

Проверка без экрана: `import banner_ask; d = banner_ask.Banner(test=True)`; d.render_png(путь),
d.on_key(None, событие), d.result. Переменная JARVIS_PRESET_STYLE — стиль вместо файла.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import cairo  # noqa: E402

import banner_fx as bf  # noqa: E402
import clipboard_win as cw  # noqa: E402
import preset_ask as pa  # noqa: E402
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

T = cw.T
mix = cw.mix
draw_bitmap = cw.draw_bitmap

# буква «T» на табличке 7×9 — значок заголовка
BANNER_BMP = ("#######", "#.....#", "#.###.#", "#..#..#", "#..#..#", "#..#..#", "#.....#",
              "#######", "...#...")
CHECK_BMP = ("......#", ".....##", "#...##.", "##.##..", ".###...", "..#....")
WIN_W = 640
COLS = 3                       # галочек в ряду
PREV_H = 70                    # высота превью
COZETTE = os.path.exists(os.path.expanduser("~/.config/fontconfig/conf.d/61-cozette-trial.conf"))


class Banner(pa.Dialog):
    button = cw.App.button

    def __init__(self, text="", test=False, style=None):
        self.fx, self.pace = set(), 1.0         # по умолчанию — статичный текст
        self.focus = "entry"                    # "entry" | ("cb", i) | ("pace", j)
        self.small, self.small_text = None, None
        self.t0 = time.monotonic()
        self.glitch = {}
        self.anim = None
        pa.TITLE, pa.PLACEHOLDER, pa.ICON_BMP = "Banner.exe", "текст надписи", BANNER_BMP
        pa.EMPTY, pa.OVERWRITE, pa.DATES = "", "", False
        super().__init__([], test=test, style=style)
        if text:
            self.set_entry(text)
        if not test:
            self.anim = GLib.timeout_add(33, self.on_anim)

    # ── размеры ────────────────────────────────────────────────────────────
    def apply_style(self, style):
        super().apply_style(style)
        pa.W = WIN_W
        pa.CW = pa.W - 2 * pa.X0
        X0, CW, PX = pa.X0, pa.CW, pa.PX
        sk = self.style == "skeet"
        self.cell_h = PX + (10 if sk else 14)
        self.pace_h = pa.SEARCH_H
        under = pa.SEARCH_Y + pa.SEARCH_H + 8
        self.fx_y = self.content_top(under)
        inner = 10 if sk else (12 if self.style == "beta" else 0)
        self.gx, self.gw = X0 + inner, CW - 2 * inner
        self.grid_y = self.fx_y + (2 if sk else 8 if self.style == "beta" else 0)
        rows = -(-len(bf.LABELS) // COLS)
        self.pace_y = self.grid_y + rows * self.cell_h + 8
        self.fx_h = self.pace_y + self.pace_h + (4 if sk else 10 if self.style == "beta" else 0) - self.fx_y
        under = self.fx_y + self.fx_h + (8 if sk else 10)
        self.pv_y = self.content_top(under)
        # низ — кнопки «Отмена» и «Создать» (19.10.2026, просьба: «чтобы и с мышки можно
        # было это делать»), слева от них — что выбрано и подсказка клавиш
        pa.FOOT_Y = self.pv_y + PREV_H + (8 + 8 if sk else 10)
        self.btn_h = pa.SEARCH_H
        pa.H = pa.FOOT_Y + self.btn_h + pa.PAD + pa.BORDER
        if getattr(self, "win", None) is not None:
            self.win.area.set_size_request(pa.W + 2 * pa.RING, pa.H + 2 * pa.RING)

    def content_top(self, under):
        """Верх содержимого группы, чья подпись встаёт под `under`."""
        if self.style == "skeet":
            return under + pa.PX // 2 + 8          # подпись — в разрыве рамки
        return under + pa.LINE + 4                 # подпись — строкой над карточкой

    def cell(self, i):
        cw_ = self.gw // COLS
        return (self.gx + (i % COLS) * cw_, self.grid_y + (i // COLS) * self.cell_h, cw_, self.cell_h)

    def pace_zones(self):
        bw, gap = 64, 6
        n = len(bf.PACES)
        x = self.gx + self.gw - n * bw - (n - 1) * gap
        return [(x + j * (bw + gap), self.pace_y, bw, self.pace_h) for j in range(n)]

    def btn_zones(self):
        """(Отмена, Создать) — у правого края низа окна."""
        bw, gap = 120, 10
        x = pa.X0 + pa.CW - 2 * bw - gap
        return (x, pa.FOOT_Y, bw, self.btn_h), (x + bw + gap, pa.FOOT_Y, bw, self.btn_h)

    def pace_index(self):
        return min(range(len(bf.PACES)), key=lambda j: abs(bf.PACES[j] - self.pace))

    # ── итог ───────────────────────────────────────────────────────────────
    def flags(self):
        return bf.clean("".join(self.fx))

    def submit(self):
        text = self.entry.strip()
        if not text:
            self.focus = "entry"
            self.redraw()
            return
        self.finish(json.dumps({"text": text, "fx": self.flags(), "pace": self.pace},
                               ensure_ascii=False))

    def toggle(self, i):
        f = bf.LABELS[i][0]
        if f in self.fx:
            self.fx.discard(f)
        else:
            self.fx.add(f)
            if f in "fR":                       # бег — в одну сторону
                self.fx.discard("R" if f == "f" else "f")
        self.t0 = time.monotonic()              # превью — с начала, чтобы эффект был виден
        self.redraw()

    def set_entry(self, text, pos=None):
        super().set_entry(text, pos)
        self.small = None

    # ── клавиатура ─────────────────────────────────────────────────────────
    def on_key(self, w, ev):
        k, code = ev.keyval, ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        alt = bool(ev.state & Gdk.ModifierType.MOD1_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        G = Gdk
        n = len(bf.LABELS)
        f = self.focus
        if alt and 10 <= code <= 18:                       # Alt+1…9 (клавиши 10…18)
            self.toggle(code - 10)
            return True
        down = k in (G.KEY_Down, G.KEY_KP_Down) or (ctrl and code == 44)   # 44 — J
        up = k in (G.KEY_Up, G.KEY_KP_Up) or (ctrl and code == 45)         # 45 — K
        left = k in (G.KEY_Left, G.KEY_KP_Left)
        right = k in (G.KEY_Right, G.KEY_KP_Right)
        tab = k in (G.KEY_Tab, G.KEY_ISO_Left_Tab)
        back = k == G.KEY_ISO_Left_Tab or (tab and shift)
        if f != "entry" and not ctrl and not alt:          # h/j/k/l — на любой раскладке
            left = left or code == 43
            down = down or code == 44
            up = up or code == 45
            right = right or code == 46
        if k == G.KEY_Escape:
            self.finish("")
            return True
        if k in (G.KEY_Return, G.KEY_KP_Enter):
            self.submit()
            return True
        if tab:
            order = ["entry"] + [("cb", i) for i in range(n)] + [("pace", self.pace_index())]
            cur = next((j for j, o in enumerate(order) if o == f or (
                isinstance(o, tuple) and isinstance(f, tuple) and o[0] == f[0] == "pace")), 0)
            self.focus = order[(cur + (-1 if back else 1)) % len(order)]
        elif f == "entry":
            if down:
                self.focus = ("cb", 0)
            else:
                return super().on_key(w, ev)
        elif f[0] == "cb":
            i = f[1]
            if k in (G.KEY_space, G.KEY_x, G.KEY_X) or code == 53:     # 53 — X
                self.toggle(i)
            elif left and i % COLS:
                self.focus = ("cb", i - 1)
            elif right and i % COLS < COLS - 1 and i + 1 < n:
                self.focus = ("cb", i + 1)
            elif up:
                self.focus = ("cb", i - COLS) if i >= COLS else "entry"
            elif down:
                self.focus = ("cb", i + COLS) if i + COLS < n else ("pace", self.pace_index())
            elif k == G.KEY_BackSpace or (Gdk.keyval_to_unicode(k) and not ctrl and not alt):
                self.focus = "entry"                       # печать — снова в поле
                return super().on_key(w, ev)
            else:
                return False
        else:                                              # ряд скорости
            j = f[1]
            if left or right:
                j = max(0, min(len(bf.PACES) - 1, j + (1 if right else -1)))
                self.focus, self.pace = ("pace", j), bf.PACES[j]
            elif up:
                self.focus = ("cb", (-(-n // COLS) - 1) * COLS)
            elif k == G.KEY_BackSpace or (Gdk.keyval_to_unicode(k) and not ctrl and not alt
                                          and k != G.KEY_space):
                self.focus = "entry"
                return super().on_key(w, ev)
            else:
                return False
        self.redraw()
        return True

    # ── мышь ───────────────────────────────────────────────────────────────
    def hit(self, x, y):
        if self.inside(self.zone_close(), x, y):
            return "close"
        no, ok = self.btn_zones()
        if self.inside(ok, x, y):
            return "ok"
        if self.inside(no, x, y):
            return "no"
        for i in range(len(bf.LABELS)):
            if self.inside(self.cell(i), x, y):
                return ("cb", i)
        for j, z in enumerate(self.pace_zones()):
            if self.inside(z, x, y):
                return ("pace", j)
        if self.inside((pa.X0, pa.SEARCH_Y, pa.CW, pa.SEARCH_H), x, y):
            return "entry"
        return None

    def on_press(self, _w, ev):
        x, y = ev.x - pa.RING, ev.y - pa.RING
        if not (0 <= x < pa.W and 0 <= y < pa.H):
            self.finish("")
            return True
        if ev.button != 1 or ev.type != Gdk.EventType.BUTTON_PRESS:
            return True
        h = self.hit(x, y)
        if h in ("close", "no"):
            self.finish("")
            return True
        if h == "ok":
            self.submit()
        elif h == "entry":
            self.focus = "entry"
        elif h and h[0] == "cb":
            self.focus = h
            self.toggle(h[1])
        elif h and h[0] == "pace":
            self.focus, self.pace = h, bf.PACES[h[1]]
            self.t0 = time.monotonic()
        self.redraw()
        return True

    def on_motion(self, _w, ev):
        h = self.hit(ev.x - pa.RING, ev.y - pa.RING)
        if h != self.hover:
            self.hover = h
            self.redraw()
        return True

    def on_scroll(self, _w, ev):
        return True

    def on_anim(self):
        if bf.animated(self.flags()) and self.win is not None:
            self.win.area.queue_draw_area(pa.RING + pa.X0, pa.RING + self.pv_y, pa.CW, PREV_H)
        return True

    # ── рисование ──────────────────────────────────────────────────────────
    def section(self, cr, label, y, h):
        """Группа: skeet — рамка с подписью в разрыве; Beta — подпись и карточка;
        Default — подпись над полупрозрачной подложкой (как поле ввода)."""
        C, st, X0, CW, PX = self.C, self.style, pa.X0, pa.CW, pa.PX
        if st == "skeet":
            gx, gy, gw, gh = X0, y - 10, CW, h + 18
            self.rect_line(cr, gx, gy, gw, gh, C["gline"])
            self.rect_line(cr, gx + 1, gy + 1, gw - 2, gh - 2, C["gdark"])
            lw = len(label) * pa.ADV
            self.rect_fill(cr, gx + 10, gy - 1, lw + 8, 3, C["bg"])
            if self.dots is not None:
                cr.save()
                cr.rectangle(gx + 10, gy - 1, lw + 8, 3)
                cr.clip()
                cr.set_source(self.dots)
                cr.paint()
                cr.restore()
            self.text(cr, label, gx + 14, gy - PX // 2 - 1, C["text"])
        elif st == "beta":
            self.text(cr, label, X0, y - pa.LINE - 2, C["dim"])
            self.rect_fill(cr, X0, y - 1, CW, h + 2, C["card"])
            self.rect_line(cr, X0, y - 1, CW, h + 2, C["line"])
        else:
            self.text(cr, label, X0, y - pa.LINE - 2, T["on_surface"])

    def checkbox(self, cr, x, y, on, focus):
        C, st = self.C, self.style
        if st == "skeet":                       # как галочка Настроек skeet: квадрат 9 px
            s = 9
            g = cairo.LinearGradient(0, y, 0, y + s)
            a, b = (C["acc_l"], C["acc_d"]) if on else (C["field_l"], C["field"])
            g.add_color_stop_rgb(0, *a)
            g.add_color_stop_rgb(1, *b)
            cr.set_source(g)
            cr.rectangle(x, y, s, s)
            cr.fill()
            self.rect_line(cr, x, y, s, s, C["acc_d"] if focus else C["line3"])
            return s
        if st == "beta":
            s = 14
            self.rect_fill(cr, x, y, s, s, C["acc"] if on else C["field"])
            self.rect_line(cr, x, y, s, s, C["acc"] if (on or focus) else C["line_strong"])
            if on:
                cr.set_source_rgb(*C["on_acc"])
                draw_bitmap(cr, CHECK_BMP, x + 4, y + 4)
            return s
        s = 13                                  # XP: белёсый квадрат и зелёная галочка
        g = cairo.LinearGradient(x, y, x + s, y + s)
        g.add_color_stop_rgb(0, *mix(T["on_surface"], T["bg"], 0.35))
        g.add_color_stop_rgb(1, *T["on_surface"])
        cr.set_source(g)
        cr.rectangle(x, y, s, s)
        cr.fill()
        self.rect_line(cr, x, y, s, s, T["st_hi"] if focus else T["st_dark"])
        if on:
            cr.set_source_rgb(*T["st_mid"])
            draw_bitmap(cr, CHECK_BMP, x + 3, y + 3)
        return s

    def draw_effects(self, cr):
        C, st, PX = self.C, self.style, pa.PX
        self.section(cr, "Эффекты", self.fx_y, self.fx_h)
        for i, (f, label) in enumerate(bf.LABELS):
            x, y, w, h = self.cell(i)
            focus = self.focus == ("cb", i)
            hover = self.hover == ("cb", i)
            on = f in self.fx
            if focus or hover:
                hl = C["sel_bg"] if st != "default" else None
                if hl is not None:
                    self.rect_fill(cr, x, y + 1, w - 6, h - 2, hl, 1.0 if focus else 0.5)
                else:
                    self.rect_fill(cr, x, y + 1, w - 6, h - 2, T["fg"], 0.10 if focus else 0.05)
                if focus and st == "skeet":
                    self.rect_fill(cr, x, y + 1, 2, h - 2, C["acc"])
            cx = x + 8
            s = self.checkbox(cr, cx, y + (h - (9 if st == "skeet" else 14 if st == "beta" else 13)) // 2,
                              on, focus)
            ink = (C["sel_text"] if focus else C["text"]) if st != "default" else T["on_surface"]
            tx = cx + s + 8
            self.text(cr, label, tx, y + (h - PX) // 2, ink, w - (tx - x) - 6)
            fl = "-" + f
            fw = len(fl) * pa.ADV
            dim = C["sel_dim"] if focus and st != "default" else C["dim"]
            if tx + (len(label) + 1) * pa.ADV + fw <= x + w - 10:
                self.text(cr, fl, x + w - 10 - fw, y + (h - PX) // 2, dim, alpha=0.8)
        # ряд «Скорость»
        y = self.pace_y
        lab_ink = C["text"] if st != "default" else T["on_surface"]
        self.text(cr, "Скорость", self.gx + 8, y + (self.pace_h - PX) // 2, lab_ink)
        sel = self.pace_index()
        for j, z in enumerate(self.pace_zones()):
            p = bf.PACES[j]
            label = ("%g" % p).replace(".", ",") + "×"
            self.button(cr, z, on=j == sel, kind="", label=label,
                        hover=self.focus == ("pace", j) or self.hover == ("pace", j))
        if isinstance(self.focus, tuple) and self.focus[0] == "pace":
            fz = self.pace_zones()[self.focus[1]]
            self.rect_line(cr, fz[0] - 2, fz[1] - 2, fz[2] + 4, fz[3] + 4,
                           C["acc"] if st != "default" else T["st_hi"])

    def draw_preview(self, cr):
        C, st = self.C, self.style
        self.section(cr, "Превью", self.pv_y, PREV_H)
        x, y, w, h = pa.X0 + (12 if st == "skeet" else 1), self.pv_y, pa.CW - (24 if st == "skeet" else 2), PREV_H
        if st == "default":
            self.rect_fill(cr, x, y, w, h, T["st_dark"], 0.5)
            self.rect_line(cr, x, y, w, h, T["st_top"])
        text = self.entry.strip() or "banner.exe"
        if self.small is None or self.small_text != text:
            fd = Pango.FontDescription("CozetteVector" if COZETTE else cw.FONT)
            fd.set_absolute_size((13 if COZETTE else 8) * Pango.SCALE)
            self.small, self.small_text = bf.Text(text, fd), text
        pad = 8
        accent = T.get("vivid") or C["accent"]
        cr.save()
        if not self.entry.strip():
            cr.push_group()
        bf.paint(cr, self.small, x + pad, y + pad, w - 2 * pad, h - 2 * pad,
                 time.monotonic() - self.t0, self.flags(), self.pace, accent, 90, self.glitch)
        if not self.entry.strip():                # пример, пока текста нет, — бледно
            cr.pop_group_to_source()
            cr.paint_with_alpha(0.35)
        cr.restore()

    def draw_footer(self, cr):
        C = self.C
        no, ok = self.btn_zones()
        self.button(cr, no, on=False, kind="dlg", label="Отмена", hover=self.hover == "no")
        ready = bool(self.entry.strip())
        self.button(cr, ok, on=ready, kind="dlg", label="Создать", hover=ready and self.hover == "ok")
        if self.hover == "close":
            left, ink = "Закрыть (Esc)", C["text"]
        else:
            ink = C["dim"]
            left = "статичный текст" if not self.fx else " ".join(
                ["-" + self.flags()] + (["-s " + ("%g" % self.pace).replace(".", ",")] if self.pace != 1 else []))
            if self.hover == "ok" and not ready:
                left = "сначала напишите текст"
            else:
                tip = "Tab — к эффектам" if self.focus == "entry" else "Пробел — галочка"
                if (len(left) + 3 + len(tip)) * pa.ADV <= no[0] - pa.X0 - 12:
                    left += " · " + tip
        self.text(cr, left, pa.X0, pa.FOOT_Y + (self.btn_h - pa.PX) // 2, ink, no[0] - pa.X0 - 12)

    def render(self, cr):
        C = self.C
        cr.save()
        cr.rectangle(0, 0, pa.W, pa.H)
        cr.clip()
        cr.set_source_rgba(*C["win_bg"], C["win_alpha"])
        cr.paint()
        if self.style == "skeet" and self.dots is not None:
            cr.set_source(self.dots)
            cr.paint_with_alpha(C["win_alpha"])
        cr.restore()
        getattr(self, "frame_" + self.style)(cr)
        self.draw_entry(cr)
        self.draw_effects(cr)
        self.draw_preview(cr)
        self.draw_footer(cr)

    def render_png(self, path):
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pa.W + 2 * pa.RING, pa.H + 2 * pa.RING)
        self.on_draw(None, cairo.Context(surf))
        surf.write_to_png(path)
        return pa.W, pa.H


def main():
    dlg = Banner(" ".join(sys.argv[1:]).strip())
    pa.sound("menu")
    try:
        from gi.repository import GLibUnix
        add = GLibUnix.signal_add
    except ImportError:
        add = GLib.unix_signal_add
    for sig in (2, 15):
        add(GLib.PRIORITY_DEFAULT, sig, lambda *_a: dlg.finish("") or False)
    Gtk.main()
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
