#!/usr/bin/env python3
"""Панель «Энергия» — щелчок по значку батареи в баре.

Оформление (переделано 12.09.2026): вместо ряда одинаковых строк с рубленой
рамкой — карточка с кольцом заряда в шапке, сгруппированными строками и
разделителями-волосками. Правила, которых стоит держаться при правках:

* все цвета берутся из палитры обоев (popup_theme.palette) — ни одного
  зашитого цвета, это общее требование ко всему рабочему столу;
* акцент работает точечно: кольцо заряда, включённые переключатели, значения
  ползунков. Если акцентом залить всё, он перестаёт что-либо значить;
* вложенные настройки (яркость ночного режима, «не отключать экран») живут в
  Gtk.Revealer и появляются только когда уместны — так панель остаётся
  короткой, а не превращается в список всего на свете;
* строки — Gtk.EventBox, а не Gtk.Box: подсветка при наведении (:hover) в GTK3
  работает только у виджетов со своим окном.
"""
import subprocess
import os
import sys
import glob
import math
import gi

gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
gi.require_version('Pango', '1.0')
gi.require_version('PangoCairo', '1.0')
from gi.repository import Gtk, Gdk, GLib, GtkLayerShell, Pango, PangoCairo
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

# Второй щелчок по модулю закрывает открытый попап. Раньше здесь были
# `pgrep -f` и `kill -9` по всему найденному — см. popup_theme.single_instance.
popup_theme.single_instance(__file__)

HERE = os.path.dirname(os.path.abspath(__file__))
BAR_STYLE = os.path.join(HERE, "bar_style.py")
SCREEN_AWAKE = os.path.join(HERE, "screen_awake.py")
SAVAGE_SCRIPT = os.path.join(HERE, "savage_battery.py")
NIGHT_MODE = os.path.join(HERE, "night_mode.py")
MONITOR_BRIGHTNESS = os.path.join(HERE, "monitor_brightness.py")
# Ночной режим: включает и выключает hyprsunset (расписание 22:00–5:00 — в
# ~/.config/hypr/hyprsunset.conf). Узнать у hyprsunset, включён ли режим,
# нельзя: запрос температуры отдаёт число и при обычном цвете. Поэтому
# ручное включение/выключение записывается сюда с отметкой времени, а если
# после записи уже прошла граница расписания — верно расписание.
NIGHT_STATE = os.path.expanduser("~/.cache/night-mode")
# Виды бара: имя файла в ~/.config/waybar/looks и подпись под миниатюрой.
# Порядок задан пользователем 14.09.2026 и рассчитан на сетку В ДВА столбца — по
# рядам идут пары: Парящий / Компактный, Во всю ширину / Во всю, компакт,
# Острова / Прозрачный, Снизу. В «Энергии» и «Настройках» сетка одинаковая.
LOOKS = [("floating", "Парящий"), ("compact", "Компактный"),
         ("edge", "Во всю ширину"), ("edge-compact", "Во всю, компакт"),
         ("islands", "Острова"), ("transparent", "Прозрачный"),
         ("bottom", "Снизу")]

PID_FILE = "/tmp/savage_mode.pid"


def get_dnd_state():
    """Включён ли режим тишины у swaync.

    Спрашиваем сам swaync, а не храним своё значение: режим можно
    переключить и из его центра уведомлений, и тогда наш переключатель
    показывал бы неправду.
    """
    try:
        r = subprocess.run(["swaync-client", "--get-dnd"],
                           capture_output=True, text=True, timeout=2)
        return r.stdout.strip() == "true"
    except (OSError, subprocess.TimeoutExpired):
        return False


def is_savage_active():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE, "r") as f:
            pid_val = int(f.read().strip())
        cmdline_path = f"/proc/{pid_val}/cmdline"
        if os.path.exists(cmdline_path):
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().decode("utf-8", errors="ignore")
                if "systemd-inhibit" in cmdline and "24/7 mode" in cmdline:
                    return True
        os.remove(PID_FILE)
    except Exception:
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
            except OSError:
                pass
    return False


def screen_awake_state():
    # Прямо файлом, без запуска screen_awake.py: каждый питон-помощник — это
    # ~30 мс на старт, а их при открытии набиралось пять (30.09.2026, «Энергия»
    # открывалась с задержкой).
    try:
        import screen_awake
        return screen_awake.get()
    except Exception:
        return False


def get_target_monitor():
    display = Gdk.Display.get_default()
    if not display:
        return None
    # Общий способ для Hyprland и niri (у niri нет hyprctl cursorpos) — popup_theme.
    mon = popup_theme.pointer_monitor()
    if mon is not None:
        return mon
    try:
        out = subprocess.check_output(["hyprctl", "cursorpos"], text=True).strip()
        cx, cy = [int(v.strip()) for v in out.split(",")]
        for i in range(display.get_n_monitors()):
            mon = display.get_monitor(i)
            geom = mon.get_geometry()
            if geom.x <= cx < geom.x + geom.width and geom.y <= cy < geom.y + geom.height:
                return mon
    except Exception:
        pass
    return display.get_primary_monitor() or (display.get_monitor(0) if display.get_n_monitors() > 0 else None)


def current_look():
    # То же, что `bar_style.py get`, но без отдельного питона.
    try:
        link = os.path.expanduser("~/.config/waybar/looks/current.jsonc")
        return os.path.basename(os.readlink(link))[:-6]
    except OSError:
        return ""


class BatteryPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Панель питания")
        self.has_entered = False

        GtkLayerShell.init_for_window(self)
        target_mon = get_target_monitor()
        if target_mon:
            GtkLayerShell.set_monitor(self, target_mon)

        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        # Окно — на весь экран и прозрачное, как у Wi-Fi, Bluetooth и
        # микшеров: щелчок по прозрачной части закрывает панель. Раньше окно
        # было размером с карточку, и щелчок мимо до него просто не доходил.
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)

        self.pal = popup_theme.palette()
        self.apply_css()

        # Прозрачная подложка на весь экран: щелчок по ней закрывает панель.
        bg = Gtk.EventBox()
        bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(bg)
        # Карточка — в правом углу: под баром, а если бар снизу — над ним.
        align = Gtk.Box()
        align.set_halign(Gtk.Align.END)
        align.set_margin_end(20)
        if popup_theme.bar_position() == "bottom":
            align.set_valign(Gtk.Align.END)
            align.set_margin_bottom(6)
        else:
            align.set_valign(Gtk.Align.START)
            align.set_margin_top(6)
        bg.add(align)
        popup_theme.add_ears(align)   # «приклеенные» попапы (Настройки → Внешний вид)
        card = Gtk.EventBox()
        card.connect("button-press-event", lambda w, e: True)   # щелчок внутри — не закрывать
        align.add(card)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        vbox.get_style_context().add_class("card")
        vbox.set_size_request(340, -1)
        card.add(vbox)

        vbox.pack_start(self.build_header(), False, False, 0)
        vbox.pack_start(self.rule(), False, False, 0)
        vbox.pack_start(self.build_brightness(), False, False, 0)
        vbox.pack_start(self.build_night(), False, False, 0)
        vbox.pack_start(self.rule(), False, False, 0)
        vbox.pack_start(self.build_toggles(), False, False, 0)
        vbox.pack_start(self.rule(), False, False, 0)
        vbox.pack_start(self.build_look(), False, False, 0)

        # События наведения и ухода курсора
        self.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.connect("enter-notify-event", self.on_mouse_enter)
        # Закрытие при уходе курсора временно отключено по просьбе пользователя
        # (11.09.2026). Вернуть — раскомментировать строку ниже.
        # self.connect("leave-notify-event", self.on_mouse_leave)

    # ── оформление ────────────────────────────────────────────────────────
    def apply_css(self):
        p = self.pal
        css = ("""
        window { background-color: transparent; }
        .card {
            background-color: %(surface)s;
            color: %(on_surface)s;
            font-family: 'JetBrainsMono Nerd Font', 'Noto Sans', sans-serif;
            font-size: 12px;
            font-weight: normal;
            /* Рамка акцентом — как у остальных попапов бара: у них она
               приходит из popup_theme.BASE_CSS (3px solid primary с 14.09.2026), а
               «Энергия» рисует свой CSS сама и до 12.09.2026 выбивалась из
               ряда тонким волоском. Тень оставлена: она отделяет карточку от
               окон под ней. */
            border: 3px solid %(primary)s;
            border-radius: 18px;
            padding: 13px 12px 11px 12px;
            /* 14.09.2026: тёмный контур 1px снаружи рамки, как у всех попапов.
               Размытую тень убрали: край окна обрезал её в серую полосу. */
            margin: 2px;
            box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
        }
        .title { font-size: 14px; font-weight: bold; color: %(on_surface)s; }
        .subtitle { font-size: 11px; color: %(on_surface_variant)s; }
        .row { border-radius: 14px; padding: 9px 10px; min-height: 22px; }
        .row:hover { background-color: %(hover)s; }
        .icon { color: %(primary)s; font-size: 14px; }
        .name { color: %(on_surface)s; font-size: 13px; }
        .value {
            color: %(primary)s; font-size: 11px; font-weight: bold;
            background-color: %(surface_container)s;
            border-radius: 8px; padding: 1px 8px;
        }
        .rule { background-color: %(hairline)s; min-height: 1px; margin: 10px 6px; }
        .sub .name { color: %(on_surface_variant)s; font-size: 12px; }
        .sub .icon { font-size: 12px; }

        /* Тумблер: без рамок и обводок, дорожка из палитры, включённый —
           акцент. Крупнее стандартного, чтобы попадать мышью без прицела. */
        switch {
            min-width: 34px; min-height: 18px;
            border: none; box-shadow: none; border-radius: 9px;
            background-color: %(surface_high)s; background-image: none;
        }
        switch:hover { background-color: %(hover_strong)s; }
        switch:checked {
            background-color: %(primary)s; background-image: none;
        }
        switch slider {
            min-width: 13px; min-height: 13px; margin: 2px;
            border: none; box-shadow: none; border-radius: 7px;
            background-color: %(on_surface_variant)s; background-image: none;
        }
        switch:checked slider { background-color: %(surface)s; }

        scale { margin: 0 2px; }
        scale trough {
            min-height: 4px; border: none;
            border-radius: 2px; background-color: %(surface_high)s;
        }
        scale highlight { background-color: %(primary)s; border-radius: 2px; border: none; }
        scale slider {
            min-width: 13px; min-height: 13px; margin: -6px;
            border-radius: 7px; border: none; box-shadow: none;
            background-color: %(primary)s; background-image: none;
        }

        button.ghost {
            background: transparent; background-image: none;
            border: none; box-shadow: none;
            color: %(on_surface_variant)s; padding: 2px 4px;
            /* Шестерёнка — единственная кнопка в шапке, её видно первой:
               мелкой она теряется рядом с кольцом заряда. */
            font-size: 24px;
        }
        button.ghost:hover { color: %(primary)s; }
        button.row-btn {
            background: transparent; background-image: none;
            border: none; box-shadow: none; padding: 0;
        }
        label.chev { color: %(on_surface_variant)s; font-size: 11px; }

        button.look-tile {
            background: transparent; background-image: none; box-shadow: none;
            border: 1px solid %(hairline)s; border-radius: 12px; padding: 6px;
        }
        button.look-tile:hover { border-color: %(primary)s; }
        button.look-tile.look-active { border: 1px solid %(primary)s; background-color: %(hover)s; }
        label.look-name { font-size: 10px; color: %(on_surface_variant)s; }
        button.look-tile.look-active label.look-name { color: %(primary)s; font-weight: bold; }
        """ % dict(p,
                   hairline=popup_theme.rgba(p["outline_variant"], 0.55),
                   hover=popup_theme.rgba(p["primary"], 0.08),
                   hover_strong=popup_theme.rgba(p["primary"], 0.16),
                   shade="rgba(0,0,0,0.45)")).encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def rule(self):
        """Разделитель-волосок между группами настроек.

        Поля задаются виджету, а не через CSS: у Gtk.EventBox и голых Gtk.Box
        в GTK3 CSS-отступы на высоту строки почти не влияют — проверено
        снимками, padding в .row менялся, а строки оставались той же высоты.
        """
        sep = Gtk.Box()
        sep.get_style_context().add_class("rule")
        sep.set_margin_top(5)
        sep.set_margin_bottom(5)
        sep.set_margin_start(6)
        sep.set_margin_end(6)
        return sep

    def pill(self, active, cb):
        """Тумблер настройки.

        Имя осталось от недолгого опыта с кнопками «Вкл/Выкл» — пользователю они не
        подошли (12.09.2026), вернулись тумблеры. Обработчики принимают простое
        булево, поэтому переключатель заворачивается здесь, а не наружу.
        """
        sw = Gtk.Switch()
        sw.set_active(active)
        sw.set_valign(Gtk.Align.CENTER)
        sw.connect("notify::active", lambda s, _p: cb(s.get_active()))
        return sw

    def row(self, icon, text, control=None, sub=False):
        """Строка «значок — название — управление» с подсветкой при наведении."""
        box = Gtk.EventBox()
        ctx = box.get_style_context()
        ctx.add_class("row")
        if sub:
            ctx.add_class("sub")
        inner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        # Воздух между строками: раньше его держала высокая кнопка-таблетка, а
        # тумблер ниже — без этих полей панель снова слипается (12.09.2026).
        inner.set_margin_top(5)
        inner.set_margin_bottom(5)
        ico = Gtk.Label(label=icon, xalign=0)
        ico.get_style_context().add_class("icon")
        name = Gtk.Label(label=text, xalign=0)
        name.get_style_context().add_class("name")
        if sub:
            inner.set_margin_start(16)
        inner.pack_start(ico, False, False, 0)
        inner.pack_start(name, True, True, 0)
        if control is not None:
            inner.pack_start(control, False, False, 0)
        box.add(inner)
        return box

    # ── шапка: кольцо заряда ──────────────────────────────────────────────
    def build_header(self):
        cap, status = self.get_battery_info()
        self.cap = cap
        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        head.set_margin_start(4)
        head.set_margin_end(2)
        head.set_margin_bottom(2)

        ring = Gtk.DrawingArea()
        ring.set_size_request(58, 58)
        ring.connect("draw", self.draw_ring)
        head.pack_start(ring, False, False, 0)

        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        texts.set_valign(Gtk.Align.CENTER)
        title = Gtk.Label(label="Энергия", xalign=0)
        title.get_style_context().add_class("title")
        sub = Gtk.Label(label=self.status_text(cap, status), xalign=0)
        sub.get_style_context().add_class("subtitle")
        texts.pack_start(title, False, False, 0)
        texts.pack_start(sub, False, False, 0)
        head.pack_start(texts, True, True, 0)

        bell = Gtk.Button(label=self.bell_glyph())
        bell.get_style_context().add_class("ghost")
        bell.set_valign(Gtk.Align.CENTER)
        bell.set_tooltip_text(self.bell_hint())
        bell.connect("clicked", self.open_notifications)
        head.pack_start(bell, False, False, 0)

        gear = Gtk.Button(label="\U000f0493")
        gear.get_style_context().add_class("ghost")
        gear.set_valign(Gtk.Align.CENTER)
        gear.set_tooltip_text("Настройки")
        # Отступ от правого края: вплотную к рамке шестерёнка смотрелась
        # приклеенной, а её увеличение это только подчеркнуло.
        gear.set_margin_end(6)
        gear.connect("clicked", self.open_settings)
        head.pack_start(gear, False, False, 0)
        return head

    def draw_ring(self, area, cr):
        """Кольцо заряда: дуга акцентом по фону из палитры, процент внутри."""
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        cx, cy = w / 2.0, h / 2.0
        radius = min(w, h) / 2.0 - 3.5
        frac = max(0.0, min(1.0, self.cap / 100.0))

        def rgb(name):
            c = self.pal[name].lstrip("#")
            return tuple(int(c[i:i + 2], 16) / 255.0 for i in (0, 2, 4))

        cr.set_line_width(5)
        cr.set_line_cap(1)  # ROUND
        cr.set_source_rgb(*rgb("surface_high"))
        cr.arc(cx, cy, radius, 0, 2 * math.pi)
        cr.stroke()
        if frac > 0:
            cr.set_source_rgb(*rgb("primary"))
            start = -math.pi / 2
            cr.arc(cx, cy, radius, start, start + frac * 2 * math.pi)
            cr.stroke()

        # В кольце всегда процент, и при зарядке тоже (27.09.2026: молния вместо
        # числа не давала увидеть заряд). Через Pango, а не cr.show_text: имя
        # «JetBrainsMono Nerd Font» у нас подменено пиксельным шрифтом системы
        # (fontconfig prepend), а игрушечный API Cairo запасного шрифта не ищет.
        text = str(self.cap)
        layout = PangoCairo.create_layout(cr)
        font = Pango.FontDescription.from_string("JetBrainsMono Nerd Font")
        font.set_absolute_size(16 * Pango.SCALE)
        layout.set_font_description(font)
        layout.set_text(text, -1)
        ink, _ = layout.get_pixel_extents()
        cr.set_source_rgb(*rgb("on_surface"))
        cr.move_to(cx - ink.x - ink.width / 2, cy - ink.y - ink.height / 2)
        PangoCairo.show_layout(cr, layout)
        return False

    def status_text(self, cap, status):
        # Одно слово, без « · N%» (27.09.2026): процент крупно в кольце рядом, а
        # разделители в пиксельном шрифте давали пустоты. Остаток времени от
        # батареи — в подсказке значка в баре.
        if status == "Charging":
            return "Заряжается"
        if status == "Full" or (status == "Not charging" and cap >= 99):
            return "Заряжено"
        if status == "Not charging":
            return "От сети"
        return "От батареи"

    # ── яркость ───────────────────────────────────────────────────────────
    def build_brightness(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        value = int(self.get_brightness())
        self.bright_value = Gtk.Label(label="%d" % value)
        self.bright_value.get_style_context().add_class("value")
        box.pack_start(self.row("󰃠", "Экран ноутбука", self.bright_value), False, False, 0)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 5)
        self.scale.set_draw_value(False)
        self.scale.set_value(value)
        self.scale.connect("value-changed", self.on_brightness_changed)
        self.scale.set_margin_start(8)
        self.scale.set_margin_end(8)
        box.pack_start(self.scale, False, False, 0)
        box.pack_start(self.build_monitor_brightness(), False, False, 0)
        return box

    # ── яркость монитора MSI (DDC/CI, 19.09.2026) ─────────────────────────
    # Строка появляется, только когда MSI подключён и ответил: значение читается
    # в фоне (ddcutil ~0,3 с), чтобы панель открывалась без задержки. Запись —
    # после паузы в движении ползунка и по одной за раз: одновременные запросы
    # по шине DDC мешают друг другу. Сам обмен — scripts/monitor_brightness.py.
    def build_monitor_brightness(self):
        self.mon_rev = Gtk.Revealer()
        self.mon_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.mon_rev.set_transition_duration(180)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.mon_value = Gtk.Label(label="…")
        self.mon_value.get_style_context().add_class("value")
        inner.pack_start(self.row("󰍹", "Монитор MSI", self.mon_value), False, False, 0)
        self.mon_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.mon_scale.set_draw_value(False)
        self.mon_scale.set_margin_start(8)
        self.mon_scale.set_margin_end(8)
        inner.pack_start(self.mon_scale, False, False, 0)
        self.mon_rev.add(inner)
        # Строка рисуется СРАЗУ, если MSI на месте и есть запомненное значение:
        # проверка монитора — 0,03 с, а опрос по DDC — 0,3 с, и раньше строка
        # выезжала уже после открытия панели (21.09.2026). Ответ монитора придёт
        # следом и уточнит цифру; если MSI отключён — строки не будет вовсе.
        known = None
        try:
            # Те же проверки, что `monitor_brightness.py present` и `last`, но в
            # этом процессе — минус два запуска питона.
            import monitor_brightness
            if monitor_brightness.hypr_has_monitor():
                with open(monitor_brightness.LAST) as f:
                    known = int(f.read().strip())
        except (OSError, subprocess.SubprocessError, ValueError, ImportError):
            known = None
        if known is not None:
            self.mon_value.set_text("%d" % known)
            self.mon_scale.set_value(known)
            self.mon_scale.connect("value-changed", self.on_monitor_brightness_changed)
            self.mon_rev.set_transition_duration(0)        # без выезда: строка уже на месте
            self.mon_rev.set_reveal_child(True)
            GLib.timeout_add(50, lambda: (self.mon_rev.set_transition_duration(180), False)[1])
        else:
            self.mon_rev.set_reveal_child(False)
        self.mon_pending = None    # значение, которое ещё надо отправить
        self.mon_proc = None       # идущий ddcutil
        self.mon_timer = None
        import threading
        threading.Thread(target=self.read_monitor_brightness, daemon=True).start()
        return self.mon_rev

    def read_monitor_brightness(self):
        try:
            out = subprocess.run(["python3", MONITOR_BRIGHTNESS, "get"],
                                 capture_output=True, text=True, timeout=25)
            val = int(out.stdout.strip()) if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError):
            val = None
        GLib.idle_add(self.show_monitor_brightness, val)

    def show_monitor_brightness(self, val):
        if val is None:
            self.mon_rev.set_reveal_child(False)   # MSI отключили — убрать строку
            return False
        if self.mon_rev.get_reveal_child():
            # Строка уже нарисована из запомненного значения — только уточняем
            # цифру. Ползунок не трогаем, если его в этот миг тянут.
            self.mon_value.set_text("%d" % val)
            if self.mon_pending is None:
                self.mon_scale.set_value(val)
            return False
        self.mon_value.set_text("%d" % val)
        self.mon_scale.set_value(val)
        self.mon_scale.connect("value-changed", self.on_monitor_brightness_changed)
        self.mon_rev.set_reveal_child(True)
        return False

    def on_monitor_brightness_changed(self, scale):
        val = int(scale.get_value())
        self.mon_value.set_text("%d" % val)
        self.mon_pending = val
        if self.mon_timer:
            GLib.source_remove(self.mon_timer)
        self.mon_timer = GLib.timeout_add(200, self.flush_monitor_brightness)

    def flush_monitor_brightness(self):
        self.mon_timer = None
        if self.mon_proc is not None and self.mon_proc.poll() is None:
            self.mon_timer = GLib.timeout_add(120, self.flush_monitor_brightness)
            return False
        if self.mon_pending is not None:
            val, self.mon_pending = self.mon_pending, None
            self.mon_proc = subprocess.Popen(["python3", MONITOR_BRIGHTNESS, "set", str(val)],
                                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                             start_new_session=True)
        return False

    # ── ночной режим ──────────────────────────────────────────────────────
    def build_night(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        on = self.get_night_shift_state()
        self.night_switch = self.pill(on, self.on_night_shift_toggled)
        box.pack_start(self.row("󰖔", "Ночной режим", self.night_switch), False, False, 0)

        # Теплота прячется, пока режим выключен: ползунок, который ни на что
        # не влияет, только сбивает с толку.
        self.night_rev = Gtk.Revealer()
        self.night_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.night_rev.set_transition_duration(180)
        warm = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        warmth = self.saved_warmth()
        self.night_value = Gtk.Label(label="%d" % warmth)
        self.night_value.get_style_context().add_class("value")
        warm.pack_start(self.row("󰔎", "Теплота", self.night_value, sub=True), False, False, 0)
        self.night_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 5)
        self.night_scale.set_draw_value(False)
        self.night_scale.set_value(warmth)
        self.night_scale.connect("value-changed", self.on_night_temp_changed)
        self.night_scale.set_margin_start(24)
        self.night_scale.set_margin_end(8)
        warm.pack_start(self.night_scale, False, False, 0)
        self.night_rev.add(warm)
        self.night_rev.set_reveal_child(on)
        box.pack_start(self.night_rev, False, False, 0)
        return box

    # ── переключатели ─────────────────────────────────────────────────────
    def build_toggles(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)

        self.power_switch = self.pill(self.get_power_saver_state(), self.on_power_saver_toggled)
        box.pack_start(self.row("󰌪", "Энергосбережение", self.power_switch), False, False, 0)

        savage = is_savage_active()
        self.awake_switch = self.pill(savage, self.on_savage_toggled)
        box.pack_start(self.row("󰓅", "Savage Mode", self.awake_switch), False, False, 0)

        # Спутник Savage Mode: пока он выключен, строки просто нет — она
        # ничего не делала бы (см. scripts/idle_guard.py, где требуются оба
        # условия сразу).
        self.screen_rev = Gtk.Revealer()
        self.screen_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.screen_rev.set_transition_duration(180)
        self.screen_switch = self.pill(screen_awake_state(), self.on_screen_awake_toggled)
        self.screen_rev.add(self.row("󰍹", "Не отключать экран",
                                     self.screen_switch, sub=True))
        self.screen_rev.set_reveal_child(savage)
        box.pack_start(self.screen_rev, False, False, 0)

        # Подсказка о смене раскладки сюда не попадает: она рисуется окном
        # eww, а не уведомлением, поэтому тишина её не глушит.
        self.dnd_switch = self.pill(get_dnd_state(), self.on_dnd_toggled)
        box.pack_start(self.row("", "Не беспокоить", self.dnd_switch), False, False, 0)
        return box

    # ── вид бара ──────────────────────────────────────────────────────────
    def build_look(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.look_chev = Gtk.Label(label="\U000f0140")
        self.look_chev.get_style_context().add_class("chev")
        self.look_chev.set_valign(Gtk.Align.CENTER)
        btn = Gtk.Button()
        btn.get_style_context().add_class("row-btn")
        btn.add(self.row("", "Вид бара", self.look_chev))
        btn.connect("clicked", self.on_look_toggle)
        box.pack_start(btn, False, False, 0)

        self.look_rev = Gtk.Revealer()
        self.look_rev.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.look_rev.set_transition_duration(200)
        # Сетка в два столбца: семь видов в строку не помещаются.
        tiles = Gtk.Grid(column_spacing=8, row_spacing=8)
        tiles.set_column_homogeneous(True)
        tiles.set_margin_top(6)
        tiles.set_margin_start(4)
        tiles.set_margin_end(4)
        tiles.set_margin_bottom(2)
        self.look_tiles = {}
        cur = current_look()
        for i, (key, title) in enumerate(LOOKS):
            tile = Gtk.Button()
            tile.get_style_context().add_class("look-tile")
            if key == cur:
                tile.get_style_context().add_class("look-active")
            inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            area = Gtk.DrawingArea()
            area.set_size_request(110, 40)
            area.connect("draw", self.draw_look, key)
            name = Gtk.Label(label=title)
            name.get_style_context().add_class("look-name")
            inner.pack_start(area, False, False, 0)
            inner.pack_start(name, False, False, 0)
            tile.add(inner)
            tile.connect("clicked", self.on_look_pick, key)
            tiles.attach(tile, i % 2, i // 2, 1, 1)
            self.look_tiles[key] = tile
        self.look_rev.add(tiles)
        box.pack_start(self.look_rev, False, False, 0)
        return box

    def notification_count(self):
        """Сколько уведомлений лежит в центре swaync (0 — если не ответил)."""
        try:
            out = subprocess.run(["swaync-client", "-c"], capture_output=True,
                                 text=True, timeout=2).stdout.strip()
            return int(out)
        except (OSError, ValueError, subprocess.SubprocessError):
            return 0

    def bell_glyph(self):
        """Колокольчик с точкой, когда есть непрочитанные, и пустой, когда нет."""
        return "\U000f0178" if self.notification_count() else "\U000f009c"

    def bell_hint(self):
        n = self.notification_count()
        return "Уведомления — %d" % n if n else "Уведомлений нет"

    def open_notifications(self, _btn):
        """Открыть центр уведомлений: там лежит всё, в том числе пойманное
        в режиме «не беспокоить», и читать можно не открывая программу."""
        subprocess.Popen(["swaync-client", "-t", "-sw"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        sys.exit(0)

    def open_settings(self, _btn):
        subprocess.Popen(["python3", os.path.join(HERE, "settings_app.py")],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        sys.exit(0)

    def on_look_toggle(self, _btn):
        show = not self.look_rev.get_reveal_child()
        self.look_rev.set_reveal_child(show)
        self.look_chev.set_text("\U000f0143" if show else "\U000f0140")

    def on_look_pick(self, _btn, key):
        for k, tile in self.look_tiles.items():
            ctx = tile.get_style_context()
            if k == key:
                ctx.add_class("look-active")
            else:
                ctx.remove_class("look-active")
        subprocess.Popen(["python3", BAR_STYLE, "set", key],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)

    def draw_look(self, area, cr, key):
        """Схемка вида — общая с «Настройками», см. popup_theme.draw_bar_look."""
        return popup_theme.draw_bar_look(cr, area.get_allocated_width(),
                                         area.get_allocated_height(), key, self.pal)

    def on_mouse_enter(self, widget, event):
        self.has_entered = True

    def on_mouse_leave(self, widget, event):
        if self.has_entered and event.detail != Gdk.NotifyType.INFERIOR:
            sys.exit(0)

    # ── состояние системы ─────────────────────────────────────────────────
    def get_battery_info(self):
        bats = glob.glob("/sys/class/power_supply/BAT*")
        if not bats:
            return 100, "Full"
        bat_path = bats[0]
        try:
            with open(f"{bat_path}/capacity", "r") as f:
                cap = int(f.read().strip())
            with open(f"{bat_path}/status", "r") as f:
                status = f.read().strip()
            return cap, status
        except Exception:
            return 100, "Unknown"

    def get_night_shift_state(self):
        import datetime
        now = datetime.datetime.now()
        # Последняя граница расписания: 22:00 или 5:00, какая была позже.
        today = now.replace(second=0, microsecond=0)
        marks = [today.replace(hour=5, minute=0), today.replace(hour=22, minute=0),
                 (today - datetime.timedelta(days=1)).replace(hour=22, minute=0)]
        boundary = max(m for m in marks if m <= now)
        # split() с индексами, а не распаковка в две переменные: в файле три
        # поля («on|off <время> <теплота>»), третье появилось позже, и жёсткая
        # распаковка на нём падала. Из-за этого включённый вручную ночной режим
        # днём показывался выключенным, хотя работал (19.09.2026).
        # В «Настройках» это место уже было исправлено, здесь — нет.
        try:
            with open(NIGHT_STATE) as f:
                parts = f.read().split()
            if len(parts) > 1 and float(parts[1]) >= boundary.timestamp():
                return parts[0] == "on"
        except (OSError, ValueError, IndexError):
            pass
        return now.hour >= 22 or now.hour < 5

    def saved_warmth(self):
        """Прошлая теплота из ~/.cache/night-mode (третье поле)."""
        try:
            with open(NIGHT_STATE) as f:
                parts = f.read().split()
            return max(0, min(100, int(float(parts[2]))))
        except (OSError, ValueError, IndexError):
            return 65

    def remember_night(self, on):
        import time
        try:
            with open(NIGHT_STATE, "w") as f:
                f.write("%s %f\n" % ("on" if on else "off", time.time()))
        except OSError:
            pass

    def apply_night_temp(self):
        """Включить ночной свет с нынешней теплотой (scripts/night_mode.py).

        Скрипт сам поднимает hyprsunset, если демон не работает: именно
        мёртвый демон 12.09.2026 сделал вид, будто режим «не включается».
        """
        subprocess.run(["python3", NIGHT_MODE, "on",
                        str(int(self.night_scale.get_value()))], capture_output=True)

    def on_night_shift_toggled(self, on):
        self.night_rev.set_reveal_child(on)
        if on:
            self.apply_night_temp()
        else:
            subprocess.run(["python3", NIGHT_MODE, "off"], capture_output=True)

    def on_night_temp_changed(self, scale):
        self.night_value.set_text("%d" % int(scale.get_value()))
        if self.night_switch.get_active():
            self.apply_night_temp()

    def get_brightness(self):
        try:
            res = subprocess.check_output(["brightnessctl", "g"], text=True).strip()
            max_b = subprocess.check_output(["brightnessctl", "m"], text=True).strip()
            return int((int(res) / int(max_b)) * 100)
        except Exception:
            return 50

    def on_brightness_changed(self, scale):
        val = int(scale.get_value())
        self.bright_value.set_text("%d" % val)
        subprocess.run(["brightnessctl", "set", f"{val}%"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def get_power_saver_state(self):
        try:
            # busctl — 3 мс; powerprofilesctl сам питон-скрипт и отвечал 140 мс.
            res = subprocess.check_output(
                ["busctl", "get-property", "net.hadess.PowerProfiles",
                 "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles",
                 "ActiveProfile"], text=True, timeout=3).strip()
            return res == 's "power-saver"'
        except Exception:
            return False

    def on_power_saver_toggled(self, on):
        mode = "power-saver" if on else "balanced"
        subprocess.run(["powerprofilesctl", "set", mode],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def on_dnd_toggled(self, want):
        if want != get_dnd_state():
            subprocess.run(["swaync-client", "--toggle-dnd"], capture_output=True)

    def on_savage_toggled(self, want):
        if want != is_savage_active():
            subprocess.run(["python3", SAVAGE_SCRIPT, "--toggle"])
        # Выключенный Savage Mode сбрасывает и спутника (savage_battery.py),
        # поэтому переключатель заодно возвращаем в исходное положение.
        if not want:
            self.screen_switch.set_active(False)
        self.screen_rev.set_reveal_child(want)

    def on_screen_awake_toggled(self, on):
        subprocess.run(["python3", SCREEN_AWAKE, "on" if on else "off"],
                       capture_output=True)


if __name__ == "__main__":
    win = BatteryPopup()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()
