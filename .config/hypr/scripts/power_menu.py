#!/usr/bin/env python3
"""Меню питания с отсчётом, как «Session menu» в Noctalia. 30.09.2026.

    power_menu.py              на мониторе с фокусом (бинд с клавиатуры)
    power_menu.py --pointer    на мониторе под указателем (щелчок по бару)
    power_menu.py --dry-run    ничего не выполнять, только напечатать команду

Замена wlogout. У wlogout нет «защиты от промаха»: щелчок по «Выключению» гасит
машину сразу, а его команды в ~/.config/wlogout/layout — от Hyprland (hyprctl),
под niri «Выход» там не работает вовсе.

    ┌ Питание ──────────────────────────────── Работает 3 ч ┐
    │  ( )      ( )      ( )      ( 4 )      ( )            │
    │ Блок.     Сон     Выход   Перезагр.  Выключение       │
    │  1         2        3        4          5             │
    │        Перезагрузка через 4 с · ещё раз — сразу        │
    └───────────────────────────────────────────────────────┘

Блокировка и Сон — сразу: они ничего не теряют. Выход, Перезагрузка и
Выключение — «разрушительные»: первое нажатие запускает отсчёт COUNTDOWN секунд
(кольцо вокруг кнопки тает, в середине — сколько осталось, кнопка красится
цветом ошибки), второе нажатие той же кнопки — выполнить сразу. Esc, щелчок
мимо или по другой кнопке — отмена отсчёта; Esc без отсчёта закрывает меню.

Клавиши: 1–5 — кнопка по номеру, ←→ / h l (и ↑↓ / k j) — выбор, Enter/пробел —
нажать. Второй запуск закрывает меню (single_instance) — так кнопка бара
работает переключателем.

Оформление — общее для попапов (popup_theme: палитра обоев, рамка .popup-box),
шрифт пиксельный и только 12/16/24/32 px (память pixel-font-system), значки —
Nerd Font по чернильной рамке (Glyph из control_center.py: у глифов разные поля).
"""
import os
import shlex
import signal
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

# Второй запуск (повторный щелчок по кнопке бара) закрывает открытое меню.
popup_theme.single_instance(__file__)

import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

# Сколько секунд отсчёта у «разрушительных» действий. 5 — как у Noctalia:
# хватает заметить промах и нажать Esc, и не раздражает, когда нажал нарочно.
COUNTDOWN = 5

DRY_RUN = "--dry-run" in sys.argv

HOME = os.path.expanduser("~")
ICON_FONT = "JetBrainsMono NF"
PIXEL_FONT = "PxPlus HP 100LX 6x8 Jarvis"
RING = 96          # сторона области со значком и кольцом, px
FRAME_MS = 16      # ~60 кадров в секунду: кольцо тает плавно, а не рывками


def lock_cmd():
    # Под niri — через shell-do: он сам выбирает Noctalia или свой hyprlock
    # (тот же путь, что SUPER+O). Под Hyprland — сразу свой экран блокировки.
    if popup_theme.on_niri():
        return [HOME + "/.config/niri/scripts/shell-do", "lock"]
    return [HOME + "/.config/hypr/scripts/lockscreen"]


def commands():
    """Команды действий. Взяты из ~/.config/wlogout/layout, «Выход» — свой для
    каждого композитора: у wlogout там hyprctl, и под niri он молча не работал."""
    lock = lock_cmd()
    if popup_theme.on_niri():
        logout = ["niri", "msg", "action", "quit", "--skip-confirmation"]
    else:
        logout = ["hyprctl", "dispatch", "hl.dsp.exit()"]
    return {
        "lock": lock,
        # Заставка staticOS (03.10.2026): не блокировка — пароль не спрашивает.
        "saver": [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               "screensaver.py")],
        # Сперва блокировка, потом сон — как было у wlogout. Секунда паузы, чтобы
        # экран блокировки успел встать до сна (hypridle тоже блокирует перед
        # сном, но на него одного полагаться не хочется; второй hyprlock
        # lockscreen сам не запустит).
        "suspend": ["sh", "-c", shlex.join(lock) + " & sleep 1; systemctl suspend"],
        "logout": logout,
        "reboot": ["systemctl", "reboot"],
        "shutdown": ["systemctl", "poweroff"],
    }


# (ключ, подпись, значок Material Design из Nerd Font, разрушительное ли)
ACTIONS = [
    ("lock", "Блокировка", "\U000f033e", False),
    ("saver", "Заставка", "\U000f07f4", False),
    ("suspend", "Сон", "\U000f0904", False),
    ("logout", "Выход", "\U000f0343", True),
    ("reboot", "Перезагрузка", "\U000f0709", True),
    ("shutdown", "Выключение", "\U000f0425", True),
]

# --only <ключ>: одна кнопка, отсчёт идёт сразу. Так зовёт wlogout (его вид
# пользователь оставил, 30.09.2026), чтобы у выхода, перезагрузки и выключения был
# тот же отсчёт: ещё щелчок — сразу, Esc — отмена (и окно закрывается).
ONLY = None
if "--only" in sys.argv:
    _i = sys.argv.index("--only")
    if _i + 1 < len(sys.argv):
        ONLY = sys.argv[_i + 1]
        ACTIONS = [a for a in ACTIONS if a[0] == ONLY] or ACTIONS


def rgba(hexcolor, alpha=1.0):
    c = Gdk.RGBA()
    c.parse(hexcolor)
    return c.red, c.green, c.blue, alpha


def fmt_uptime():
    try:
        with open("/proc/uptime") as f:
            sec = int(float(f.read().split()[0]))
    except (OSError, ValueError):
        return ""
    d, rest = divmod(sec, 86400)
    h, m = rest // 3600, rest % 3600 // 60
    parts = (["%d д" % d] if d else []) + (["%d ч" % h] if h or d else []) + ["%d мин" % m]
    return "Работает " + " ".join(parts)


def text_layout(cr, text, family, px):
    layout = PangoCairo.create_layout(cr)
    fd = Pango.FontDescription.from_string(family)
    fd.set_absolute_size(px * Pango.SCALE)
    layout.set_font_description(fd)
    layout.set_text(text, -1)
    return layout


def show_centered(cr, layout, cx, cy):
    """Поставить текст серединой ЧЕРНИЛ в (cx, cy): у глифов Nerd Font и у цифр
    пиксельного шрифта разные поля в клетке, по логической рамке они съезжают."""
    ink, _log = layout.get_pixel_extents()
    cr.move_to(round(cx - ink.width / 2 - ink.x), round(cy - ink.height / 2 - ink.y))
    PangoCairo.show_layout(cr, layout)


class Ring(Gtk.DrawingArea):
    """Круг со значком. Во время отсчёта — тающее кольцо и число секунд."""

    def __init__(self, menu, idx, icon):
        super().__init__()
        self.menu, self.idx, self.icon = menu, idx, icon
        self.set_size_request(RING, RING)
        self.set_halign(Gtk.Align.CENTER)
        self.connect("draw", self.on_draw)

    def on_draw(self, widget, cr):
        import cairo
        pal = self.menu.pal
        w, h = widget.get_allocated_width(), widget.get_allocated_height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 5
        left = self.menu.remaining() if self.menu.pending == self.idx else None
        selected = self.menu.sel == self.idx
        cr.set_line_cap(cairo.LINE_CAP_ROUND)

        if left is None:
            # Покой: подложка-круг и значок; выбранная — в акценте.
            cr.arc(cx, cy, r, 0, 6.2832)
            cr.set_source_rgba(*rgba(pal["primary"], 0.16) if selected
                               else rgba(pal["surface_high"]))
            cr.fill()
            if selected:
                cr.arc(cx, cy, r, 0, 6.2832)
                cr.set_line_width(2)
                cr.set_source_rgba(*rgba(pal["primary"], 0.9))
                cr.stroke()
            cr.set_source_rgba(*rgba(pal["primary"] if selected else pal["on_surface"]))
            show_centered(cr, text_layout(cr, self.icon, ICON_FONT, 36), cx, cy)
            return True

        # Отсчёт: бледная дорожка, поверх — дуга оставшегося времени от «12 часов»
        # по часовой стрелке; она укорачивается к нулю.
        err = pal["error"]
        cr.arc(cx, cy, r - 3, 0, 6.2832)
        cr.set_source_rgba(*rgba(err, 0.12))
        cr.fill()
        cr.set_line_width(6)
        cr.arc(cx, cy, r - 3, 0, 6.2832)
        cr.set_source_rgba(*rgba(err, 0.22))
        cr.stroke()
        frac = max(0.0, min(1.0, left / COUNTDOWN))
        if frac > 0:
            start = -1.5708
            cr.arc(cx, cy, r - 3, start, start + frac * 6.2832)
            cr.set_source_rgba(*rgba(err))
            cr.stroke()
        secs = max(1, int(left + 0.999))
        cr.set_source_rgba(*rgba(err))
        show_centered(cr, text_layout(cr, str(secs), PIXEL_FONT, 32), cx, cy)
        return True


class PowerButton(Gtk.Button):
    def __init__(self, menu, idx, label, icon):
        super().__init__()
        self.get_style_context().add_class("pw")
        # Фокус GTK не нужен: выбор ведёт само меню (стрелки, hjkl, наведение),
        # иначе стрелки двигали бы фокус GTK мимо нашего выделения.
        self.set_can_focus(False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.ring = Ring(menu, idx, icon)
        self.label = Gtk.Label(label=label)
        self.label.get_style_context().add_class("pw-label")
        self.key = Gtk.Label(label=str(idx + 1))
        self.key.get_style_context().add_class("pw-key")
        box.pack_start(self.ring, False, False, 0)
        box.pack_start(self.label, False, False, 0)
        box.pack_start(self.key, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda _b: menu.activate(idx))
        self.connect("enter-notify-event", lambda *_a: menu.select(idx))


class PowerMenu(Gtk.Window):
    def __init__(self):
        super().__init__(title="Питание")
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-power-menu")
        # OVERLAY и exclusive_zone -1: затемнение ложится и на бар, меню — поверх всего.
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_exclusive_zone(self, -1)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        if "--pointer" in sys.argv:
            # Щелчок по бару в niri не переносит фокус монитора (см.
            # popup_theme.pointer_spot) — без этого меню встало бы на другом экране.
            mon = popup_theme.pointer_monitor()
            if mon is not None:
                GtkLayerShell.set_monitor(self, mon)
        # Без явного монитора слой встаёт на монитор с фокусом — то, что нужно
        # для бинда с клавиатуры.
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.cmds = commands()
        self.sel = 0
        self.pending = None          # индекс кнопки, у которой идёт отсчёт
        self.deadline = 0.0
        self.timer = None
        self.done = False

        self.pal = pal = popup_theme.palette()
        css = popup_theme.css("""
        .popup-box {
            font-family: '%(pixel)s', 'JetBrainsMono NF', sans-serif;
            font-size: 16px; font-weight: normal;
            border-radius: 14px; padding: 16px 18px 14px 18px;
        }
        label.title { color: %(primary)s; font-size: 24px; }
        label.uptime { color: %(on_surface_variant)s; font-size: 12px; }
        button.pw {
            background-color: %(card_bg)s; background-image: none; box-shadow: none;
            border: 2px solid %(line)s; border-radius: 14px;
            padding: 16px 8px 10px 8px; min-width: 164px;
            color: %(on_surface)s;
        }
        button.pw.sel { border-color: %(primary)s; background-color: %(surface_high)s;
                        color: %(primary)s; }
        button.pw.armed, button.pw.armed.sel {
            border-color: %(error)s; background-color: %(armed_bg)s; color: %(error)s;
        }
        label.pw-label { font-size: 16px; }
        label.pw-key { font-size: 12px; color: %(on_surface_variant)s; }
        button.pw.sel label.pw-key { color: %(primary)s; }
        button.pw.armed label.pw-key { color: %(error)s; }
        /* Подсказка всегда 16 px: с 12 px в покое карточка подпрыгивала на 2 px,
           когда начинался отсчёт и подсказка становилась крупной. */
        label.hint { font-size: 16px; color: %(on_surface_variant)s; }
        label.hint.armed { color: %(error)s; }
        """, pixel=PIXEL_FONT,
            card_bg=popup_theme.rgba(pal["surface_container"], "0.80"),
            line=popup_theme.rgba(pal["primary"], "0.25"),
            armed_bg=popup_theme.rgba(pal["error"], "0.14"))
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Подложка на весь экран: полупрозрачный цвет поверхности. Рисуется в
        # обработчике draw до детей (EventBox без своего окна сам ничего не красит).
        self.backdrop = Gtk.EventBox()
        self.backdrop.set_visible_window(False)
        self.backdrop.set_app_paintable(True)
        self.backdrop.connect("draw", self.draw_backdrop)
        self.backdrop.connect("button-press-event", self.on_backdrop)
        self.add(self.backdrop)

        # Щелчок по самой карточке мимо кнопок: во время отсчёта — отмена, иначе
        # ничего (меню не должно закрываться от промаха по полю карточки).
        card_ev = Gtk.EventBox()
        card_ev.set_visible_window(False)
        card_ev.set_halign(Gtk.Align.CENTER)
        card_ev.set_valign(Gtk.Align.CENTER)
        card_ev.connect("button-press-event", self.on_card)
        self.backdrop.add(card_ev)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        card.get_style_context().add_class("popup-box")
        card_ev.add(card)

        head = Gtk.Box(spacing=12)
        title = Gtk.Label(label="Питание", xalign=0)
        title.get_style_context().add_class("title")
        up = Gtk.Label(label=fmt_uptime(), xalign=1)
        up.get_style_context().add_class("uptime")
        up.set_valign(Gtk.Align.CENTER)
        head.pack_start(title, True, True, 2)
        head.pack_start(up, False, False, 2)
        card.pack_start(head, False, False, 0)

        row = Gtk.Box(spacing=10)
        row.set_homogeneous(True)
        self.buttons = []
        for i, (_key, label, icon, _destr) in enumerate(ACTIONS):
            b = PowerButton(self, i, label, icon)
            self.buttons.append(b)
            row.pack_start(b, True, True, 0)
        card.pack_start(row, False, False, 0)

        self.hint = Gtk.Label()
        self.hint.get_style_context().add_class("hint")
        card.pack_start(self.hint, False, False, 0)

        self.connect("key-press-event", self.on_key)
        self.refresh()
        if ONLY:
            GLib.idle_add(lambda: (self.activate(0), False)[1])

    # ── состояние ─────────────────────────────────────────────────────────
    def remaining(self):
        return max(0.0, self.deadline - time.monotonic())

    def refresh(self):
        for i, b in enumerate(self.buttons):
            ctx = b.get_style_context()
            (ctx.add_class if i == self.sel else ctx.remove_class)("sel")
            (ctx.add_class if i == self.pending else ctx.remove_class)("armed")
            b.ring.queue_draw()
        self.update_hint()

    def update_hint(self):
        ctx = self.hint.get_style_context()
        if self.pending is None:
            ctx.remove_class("armed")
            self.hint.set_text("1–6 или стрелки · Z — заставка · Enter — выбрать · Esc или ⌫ — закрыть")
            return
        ctx.add_class("armed")
        name = ACTIONS[self.pending][1]
        secs = max(1, int(self.remaining() + 0.999))
        self.hint.set_text("%s через %d с · ещё раз — сразу · Esc — отмена" % (name, secs))

    def select(self, idx):
        idx %= len(ACTIONS)
        if idx != self.sel:
            self.sel = idx
            self.refresh()
        return False

    def activate(self, idx):
        if self.done or idx >= len(ACTIONS):
            return
        if self.pending is not None:
            if self.pending == idx:
                self.execute(idx)          # второе нажатие той же кнопки — сразу
            else:
                self.cancel()              # другая кнопка — только отмена
            return
        if not ACTIONS[idx][3]:
            self.execute(idx)
            return
        self.pending = idx
        self.sel = idx
        self.deadline = time.monotonic() + COUNTDOWN
        self.timer = GLib.timeout_add(FRAME_MS, self.frame)
        self.refresh()

    def frame(self):
        if self.pending is None:
            self.timer = None
            return False
        if self.remaining() <= 0:
            self.timer = None
            self.execute(self.pending)
            return False
        self.buttons[self.pending].ring.queue_draw()
        self.update_hint()
        return True

    def cancel(self):
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        self.pending = None
        if ONLY:                          # из wlogout: отмена — значит закрыть
            self.quit()
            return
        self.refresh()

    def execute(self, idx):
        if self.done:
            return
        self.done = True
        if self.timer is not None:
            GLib.source_remove(self.timer)
            self.timer = None
        key = ACTIONS[idx][0]
        cmd = self.cmds[key]
        if DRY_RUN:
            print("DRY-RUN %s: %s" % (key, shlex.join(cmd)), flush=True)
        else:
            # Сперва убрать слой: экран блокировки и сон не должны застать
            # затемнение с EXCLUSIVE-клавиатурой поверх себя.
            self.hide()
            while Gtk.events_pending():
                Gtk.main_iteration()
            # Звук выхода/выключения, как в Windows XP (02.10.2026): сперва мелодия до
            # конца (2–3 с), потом само действие. Звуки выключены или «Не беспокоить» —
            # ui_sound.py выходит сразу, задержки нет.
            ev = {"logout": "logout", "reboot": "shutdown", "shutdown": "shutdown"}.get(key)
            snd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_sound.py")
            if ev and os.path.exists(snd):
                cmd = ["sh", "-c", 'timeout 5 python3 "$0" play "$1" --wait; shift; exec "$@"',
                       snd, ev] + cmd
            subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
        self.quit()

    # ── ввод ──────────────────────────────────────────────────────────────
    def on_key(self, _w, event):
        k = event.keyval
        if k in (Gdk.KEY_Escape, Gdk.KEY_BackSpace):     # Backspace — как Esc (04.10.2026)
            if self.pending is not None:
                self.cancel()
            else:
                self.quit()
        # h/j/k/l — и в русской раскладке (р/о/л/д): по месту клавиши, keycode 43/44/45/46
        # (04.10.2026, «в меню питания на русской раскладке h/l не работают»)
        elif k in (Gdk.KEY_Left, Gdk.KEY_h, Gdk.KEY_Up, Gdk.KEY_k, Gdk.KEY_ISO_Left_Tab) or \
                event.hardware_keycode in (43, 45):
            self.select(self.sel - 1)
        elif k in (Gdk.KEY_Right, Gdk.KEY_l, Gdk.KEY_Down, Gdk.KEY_j, Gdk.KEY_Tab) or \
                event.hardware_keycode in (44, 46):
            self.select(self.sel + 1)
        elif k in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space):
            self.activate(self.sel)
        elif Gdk.KEY_1 <= k <= Gdk.KEY_6:
            self.activate(k - Gdk.KEY_1)
        elif Gdk.KEY_KP_1 <= k <= Gdk.KEY_KP_6:
            self.activate(k - Gdk.KEY_KP_1)
        elif k in (Gdk.KEY_z, Gdk.KEY_Z, Gdk.KEY_Cyrillic_ya, Gdk.KEY_Cyrillic_YA):
            keys = [a[0] for a in ACTIONS]
            if "saver" in keys:
                self.activate(keys.index("saver"))
        return True

    def on_backdrop(self, _w, event):
        if event.button != 1 and event.button != 3:
            return True
        if self.pending is not None:
            self.cancel()
        else:
            self.quit()
        return True

    def on_card(self, _w, _event):
        if self.pending is not None:
            self.cancel()
        return True                        # не пускать щелчок дальше, к подложке

    def draw_backdrop(self, widget, cr):
        import cairo
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(*rgba(self.pal["surface"], 0.45))
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        return False                       # дальше GTK рисует карточку поверх

    def quit(self, *_a):
        Gtk.main_quit()
        return False


if __name__ == "__main__":
    # SIGTERM от второго запуска — выйти сразу, не дожидаясь цикла GTK
    # (у центра управления Gtk.main_quit из сигнала иногда не срабатывал).
    # Через GLib, а не signal.signal: питоновский обработчик ждёт, пока цикл GTK
    # вернёт управление интерпретатору, а это может не случиться до события.
    try:
        from gi.repository import GLibUnix
        GLibUnix.signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, lambda *_a: os._exit(0))
    except ImportError:                    # старый PyGObject без GLibUnix
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, lambda *_a: os._exit(0))
    win = PowerMenu()
    win.show_all()
    Gtk.main()
