#!/usr/bin/env python3
"""Мини-календарь окном, а не подсказкой waybar.

Раньше сетку месяца показывал tooltip модуля custom/clock. У tooltip'ов GTK
своя задержка наведения; из waybar она не настраивается, в CSS её тоже нет,
и заглянуть в календарь мгновенно было невозможно. Здесь та же самая сетка
(её строит build_month() из waybar_clock.py — рисунок и палитра общие,
чтобы попап не разъехался с подсказкой), но по щелчку и сразу.

Повторный щелчок по модулю закрывает уже открытый попап: вторая копия видит
первую по имени процесса и убивает её вместо того, чтобы открыться поверх.
"""
import calendar
import colorsys
import datetime
import os
import sys

import gi

# Через столько секунд без внимания попап закрывается сам.
IDLE_CLOSE_S = 20

# Свои названия, а не calendar.month_name: тот следует локали, а она в системе
# английская — в русском окне это выглядело чужеродно.
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль",
          "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")
WEEKDAYS = ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")

# Высота одной недельной строки. Дублируется в CSS как min-height у ячейки:
# именно из неё складывается постоянная высота окна (шесть строк в любом
# месяце), поэтому менять эти два числа надо вместе.
ROW_H = 26

# Размер коробки календаря. Высота — по месяцу на ПЯТЬ недель: так окно
# компактнее, а месяц на шесть недель ужимается в ту же высоту (строки делят
# её поровну, см. row_homogeneous). Ширина — по самому длинному названию
# месяца. Менять вместе со шрифтами и полями в CSS.
# Ширина 300 (23.09.2026). По замыслу было 310, но с пиксельным шрифтом окно
# на деле растягивала до 376 подсказка внизу одной строкой; теперь она
# переносится, и ширина снова от сетки. Пропорция — шире, чем выше: при 272
# календарь казался сдавленным. Высота прежняя, 229.
BOX_W = 358
BOX_H = 229

# Переключатель: второй запуск гасит первый и уходит.
#
# Через файл с номером процесса, а НЕ через `pgrep -f calendar_popup.py`, как
# в player_popup.py. Тот приём ловит по строке всю командную строку любого
# процесса — включая оболочку, которая этот самый скрипт запускает: у неё имя
# файла тоже стоит в аргументах. Попап видел её, принимал за прежнюю копию
# себя, убивал (унося с собой запустивший его терминал) и молча выходил.
PIDFILE = os.path.expanduser("~/.cache/waybar-calendar-popup.pid")


def other_instance():
    """Номер живой прежней копии, если она есть."""
    try:
        with open(PIDFILE) as f:
            old_pid = int(f.read().strip())
    except (OSError, ValueError):
        return None
    if old_pid == os.getpid():
        return None
    # Проверяем не только «процесс жив», но и что это именно попап: номера
    # переиспользуются, и по несвежему файлу можно убить чужое.
    try:
        with open("/proc/%d/cmdline" % old_pid, "rb") as f:
            if b"calendar_popup.py" in f.read():
                return old_pid
    except OSError:
        pass
    return None


prev = other_instance()
if prev:
    try:
        os.kill(prev, 9)
    except OSError:
        pass
    try:
        os.unlink(PIDFILE)
    except OSError:
        pass
    sys.exit(0)

try:
    with open(PIDFILE, "w") as f:
        f.write(str(os.getpid()))
except OSError:
    pass

gi.require_version("Gtk", "3.0")
# Gdk просим явно: на этой машине рядом стоит gtk4-layer-shell, и без строки
# ниже gi успевает подтянуть Gdk 4.0 раньше нашего импорта — тогда падает
# с "Requiring namespace 'Gdk' version '3.0', but '4.0' is already loaded".
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402
import waybar_clock  # noqa: E402


def tune(hexcolor, sat=1.0, light=0.0):
    """Тот же оттенок, но насыщеннее или темнее — в пределах гаммы обоев.

    Material отдаёт роли, рассчитанные на подложки и крупный текст; для
    мелких цифр они выходят слишком блёклыми и сливаются с обычным днём.
    Крутим насыщенность и светлоту, а тон не трогаем — поэтому цвет остаётся
    «из тех же обоев».
    """
    c = hexcolor.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, sa = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + light))
    sa = max(0.0, min(1.0, sa * sat))
    r, g, b = colorsys.hls_to_rgb(h, l, sa)
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def mix(a, b, t):
    """a, разбавленный b на долю t — для приглушённых дней соседних месяцев."""
    ca, cb = a.lstrip("#"), b.lstrip("#")
    out = []
    for i in (0, 2, 4):
        va, vb = int(ca[i:i + 2], 16), int(cb[i:i + 2], 16)
        out.append(int(va + (vb - va) * t))
    return "#%02x%02x%02x" % tuple(out)


class CalendarPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Календарь")
        # Отсчёт месяцев свой, а не общий с баром: попап открывают, чтобы
        # посмотреть на сегодня, и он всегда начинается с текущего месяца,
        # даже если в баре кто-то прокрутил подсказку на полгода вперёд.
        self.offset = 0

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        # ON_DEMAND, а не EXCLUSIVE: при исключительном захвате клавиатуры
        # компоновщик не отдаёт фокус чужим окнам, и focus-out-event не
        # приходит — попап оставался висеть, когда работа шла на втором
        # мониторе. По требованию фокус уходит, событие приходит, окно
        # закрывается само.
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.ON_DEMAND)

        # Один в один с подсказкой waybar, которую этот попап заменил:
        # те же 13px жирного JetBrainsMono, те же 6px внутреннего поля, та же
        # рамка в 1px акцентом и радиус 12. Без размера шрифта GTK брал свой
        # системный (крупнее), и одна и та же сетка выходила заметно шире
        # подсказки — расхождение было видно глазом при переключении.
        # Фон плотный, без прозрачности: у подсказки waybar стояло
        # alpha(@background, 0.95) и выглядела она сплошной, но у слоя поверх
        # окон те же 0.95 дали отчётливо просвечивающий текст — сетка
        # читалась поверх чужих букв.
        pal = popup_theme.palette()
        css = popup_theme.css("""
        .cal-box {
            background-color: %(bg)s;
            border: 3px solid %(frame)s;   /* акцент — видно, что открыт; 3px с 14.09.2026, как у всех попапов */
            border-radius: 12px;
            padding: 8px 10px 6px 10px;
            /* Тёмный контур 1px снаружи — рамка видна и на светлых обоях
               (14.09.2026). Без размытой тени: окно обрезало её краем в
               полупрозрачную полосу. */
            margin: 2px;
            box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
        }
        /* Шапка: месяц акцентом и крупнее, год приглушённым рядом — так
           взгляд цепляется за месяц, а год не спорит с ним за внимание. */
        label.cal-month {
            color: %(accent)s; font-size: 15px; font-weight: bold;
            font-family: 'JetBrainsMono Nerd Font', monospace;
        }
        label.cal-year {
            color: %(dim)s; font-size: 15px; font-weight: normal;
            font-family: 'JetBrainsMono Nerd Font', monospace;
        }
        button.cal-arrow {
            background: none; border: none; box-shadow: none;
            color: %(dim)s; padding: 0; min-width: 20px; min-height: 20px;
            border-radius: 999px;
            font-family: 'JetBrainsMono Nerd Font', monospace; font-size: 13px;
        }
        /* Красим и саму кнопку, и её надпись: цвет с button на вложенный
           label GTK не наследует, и без второй строки стрелка при наводке
           оставалась тусклой. */
        /* Под курсором стрелка получает круглую подложку — одного смены
           цвета было мало, кнопка оставалась незаметной. Красим и саму
           кнопку, и её надпись: цвет с button на вложенный label GTK не
           наследует. */
        button.cal-arrow:hover, button.cal-arrow:hover label {
            color: %(accent)s;
        }
        button.cal-arrow:hover {
            background-color: %(hover_bg)s;
            border-radius: 999px;
        }
        /* Заголовки дней недели — мельче и тише чисел: это подписи осей,
           а не данные. */
        /* Шапка дней недели: жирная и в полный цвет текста. Приглушённой
           она читалась хуже самих чисел, хотя должна вести взгляд по
           колонкам. */
        label.cal-wd {
            color: %(fg)s; font-size: 14px; font-weight: 900;
            font-family: 'JetBrainsMono Nerd Font', monospace;
            padding-bottom: 3px;
        }
        label.cal-wd-off { color: %(wknd)s; }
        label.cal-day {
            color: %(fg)s; font-size: 13px;
            font-family: 'JetBrainsMono Nerd Font', monospace;
            padding: 0; min-width: 36px; min-height: 18px;
        }
        /* Выходные — третичной ролью. Пробовал основным акцентом, чтобы не
           выбиваться из гаммы, но он почти совпадает с цветом обычного
           текста (в fidelity-схеме primary светлый), и колонка переставала
           читаться вовсе. Здесь важнее различимость. */
        label.cal-off { color: %(wknd)s; }
        /* Дни соседних месяцев показаны, а не выброшены: сетка всегда шесть
           строк, и пустоты по краям выглядели дырами. */
        label.cal-pad { color: %(pad)s; }
        /* Выходной соседнего месяца: тот же оттенок выходных, но приглушённый
           — иначе суббота и воскресенье в хвосте месяца выглядели буднями. */
        label.cal-pad.cal-off { color: %(wknd_pad)s; }
        /* Сегодня — залитый кружок акцентом. Ради него вся сетка и собрана
           из виджетов: разметкой Pango круглую подложку не нарисовать. */
        label.cal-today {
            background-color: %(accent)s; color: %(on_accent)s;
            font-weight: bold; border-radius: 999px;
            /* Одинаковые ширина и высота при нулевом поле — иначе подложка
               растягивалась в овал. */
            padding: 0; min-width: 36px; min-height: 18px;
        }
        separator.cal-rule { background-color: %(line)s; margin: 2px 0 4px 0; }
        label.cal-hint {
            color: %(pad)s; font-size: 10px; font-weight: normal;
            font-family: 'JetBrainsMono Nerd Font', monospace;
        }
        """ % {
            "bg": pal["surface"],
            "fg": pal["on_surface"],
            "dim": pal["on_surface_variant"],
            "faint": pal["on_surface_variant"],
            "line": pal["surface_high"],
            "frame": pal["primary"],
            "accent": pal["primary"],
            "on_accent": pal["on_primary"],
            "accent3": pal["tertiary"],
            # Выходные: вторичная роль, но насыщеннее и на тон темнее. Как
            # есть она почти совпадает с цветом обычного дня и колонка
            # не читалась; бирюзовая третичная читалась отлично, но выпадала
            # из тёплой гаммы обоев.
            "wknd": tune(pal["secondary"], sat=1.45, light=-0.10),
            # Он же, разбавленный подложкой — для выходных соседних месяцев:
            # они должны отличаться от будних, оставаясь приглушёнными.
            "wknd_pad": mix(tune(pal["secondary"], sat=1.45, light=-0.10),
                            pal["surface"], 0.45),
            "pad": mix(pal["on_surface_variant"], pal["surface"], 0.45),
            "hover_bg": pal["surface_high"],
        })
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # Клик мимо сетки закрывает окно, клик по самой сетке — нет.
        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        align = Gtk.Box()
        align.set_halign(Gtk.Align.END)     # под часами, они в правом углу
        # Бар снизу (вид «Снизу») — календарь над ним. См. popup_theme.bar_position.
        at_bottom = popup_theme.bar_position() == "bottom"
        align.set_valign(Gtk.Align.END if at_bottom else Gtk.Align.START)
        # Слой начинается уже ПОД баром: waybar держит exclusive zone, и
        # компоновщик отдаёт нам прямоугольник с y = 40. Поэтому отступ здесь
        # маленький — это зазор от бара, а не его высота; раньше стояло 34 и
        # попап висел на целую полосу ниже, чем нужно.
        if at_bottom:
            align.set_margin_bottom(6)
        else:
            align.set_margin_top(6)
        # Столько же, сколько margin-right у бара (20 в config.jsonc), — тогда
        # правый край попапа стоит на одной линии с правым краем панели.
        align.set_margin_end(0)   # к самому краю экрана (23.09.2026, просьба пользователя)
        self.bg.add(align)
        popup_theme.add_ears(align)   # «приклеенные» попапы (Настройки → Внешний вид)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        # Колесо листает месяцы прямо в попапе: в баре прокрутка двигает
        # подсказку, а попап её состояния не делит.
        self.popup_event.add_events(Gdk.EventMask.SCROLL_MASK)
        self.popup_event.connect("scroll-event", self.on_scroll)
        align.add(self.popup_event)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        box.get_style_context().add_class("cal-box")
        self.popup_event.add(box)
        self.box = box

        # Шапка: стрелка, месяц с годом, стрелка. Стрелки не только украшают —
        # без них листать можно было лишь колесом, о чём знает только тот,
        # кто прочитал подсказку.
        head = Gtk.Box(spacing=2)
        self.btn_prev = Gtk.Button(label="\uf053")
        self.btn_next = Gtk.Button(label="\uf054")
        for b, step in ((self.btn_prev, -1), (self.btn_next, 1)):
            b.get_style_context().add_class("cal-arrow")
            b.set_relief(Gtk.ReliefStyle.NONE)
            b.connect("clicked", self.step, step)
            # Курсор-рука над стрелками. GTK сам его не ставит: указатель
            # меняет только виджет со своим окном ввода, а кнопке нужно
            # сказать явно.
            b.connect("enter-notify-event", self.set_cursor, "pointer")
            b.connect("leave-notify-event", self.set_cursor, None)
        self.lbl_month = Gtk.Label()
        self.lbl_month.get_style_context().add_class("cal-month")
        self.lbl_year = Gtk.Label()
        self.lbl_year.get_style_context().add_class("cal-year")
        title = Gtk.Box(spacing=6)
        title.set_hexpand(True)
        title.set_halign(Gtk.Align.CENTER)
        title.add(self.lbl_month)
        title.add(self.lbl_year)
        head.add(self.btn_prev)
        head.pack_start(title, True, True, 0)
        head.add(self.btn_next)
        box.add(head)

        rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        rule.get_style_context().add_class("cal-rule")
        box.add(rule)

        # row_homogeneous: строки делят высоту поровну. Вместе с
        # зарезервированной высотой (см. lock_height) это даёт окно одного
        # размера в любом месяце БЕЗ пустой строки: в месяце на пять недель
        # строки просто чуть выше.
        self.grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=True,
                             row_spacing=0, column_spacing=2)
        self.grid.set_vexpand(True)
        box.add(self.grid)

        self.hint = Gtk.Label()
        self.hint.get_style_context().add_class("cal-hint")
        # Подсказка переносится на две строки (23.09.2026): одной строкой она
        # была шире всей сетки — с широким пиксельным шрифтом ~340 px — и
        # именно она, а не BOX_W, задавала ширину окна. Ширина теперь от сетки.
        self.hint.set_line_wrap(True)
        self.hint.set_max_width_chars(34)
        self.hint.set_justify(Gtk.Justification.CENTER)
        self.hint.set_margin_top(4)
        box.add(self.hint)

        self.redraw()
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        # Уход фокуса = работа пошла в другом окне (в том числе на другом
        # мониторе, куда наш слой не дотягивается). Через idle_add, потому что
        # первое focus-out прилетает ещё до того, как окно успеет фокус
        # получить, и попап схлопывался бы сразу после открытия.
        self.connect("focus-out-event", self.on_focus_out)
        self.ready = False
        GLib.timeout_add(400, self.arm)
        # Страховка на случай, если фокус так и не придёт ни к кому: попап
        # гаснет сам, если на него не смотрят. Таймер сбрасывается любым
        # движением мыши над сеткой и любой прокруткой.
        self.idle_id = None
        self.bump_idle()
        self.lock_height()

    def arm(self):
        self.ready = True
        return False

    def on_focus_out(self, *_a):
        if self.ready:
            Gtk.main_quit()
        return False

    def bump_idle(self):
        if self.idle_id:
            GLib.source_remove(self.idle_id)
        self.idle_id = GLib.timeout_add_seconds(IDLE_CLOSE_S, Gtk.main_quit)

    def lock_height(self):
        """Прибить размер окна намертво.

        Раньше он вычислялся замером «худшего» месяца, но спрашивать размеры
        до того, как окно показано, бесполезно: GTK отдаёт заниженные числа,
        и в месяце на шесть недель окно всё равно вырастало. Поэтому просто
        константы — они сняты с настоящего окна (месяц на шесть недель,
        самое длинное название) и держатся, пока не менялись шрифт и поля
        в CSS выше.
        """
        self.box.set_size_request(BOX_W, BOX_H)

    def six_week_offset(self):
        """Смещение до ближайшего месяца, который занимает шесть недель."""
        today = datetime.date.today()
        cal = calendar.Calendar(firstweekday=0)
        for off in range(0, 14):
            y, m = today.year, today.month + off
            y += (m - 1) // 12
            m = (m - 1) % 12 + 1
            if len(cal.monthdatescalendar(y, m)) == 6:
                return off
        return 0

    def set_cursor(self, widget, _event, name):
        win = widget.get_window()
        if not win:
            return False
        cur = None
        if name:
            cur = Gdk.Cursor.new_from_name(widget.get_display(), name)
        win.set_cursor(cur)
        return False

    def step(self, _btn, delta):
        self.offset += delta
        self.redraw()
        self.bump_idle()

    def redraw(self):
        today = datetime.date.today()
        y, m = today.year, today.month + self.offset
        y += (m - 1) // 12
        m = (m - 1) % 12 + 1

        self.lbl_month.set_text(MONTHS[m - 1])
        self.lbl_year.set_text(str(y))

        for child in self.grid.get_children():
            self.grid.remove(child)

        for col, name in enumerate(WEEKDAYS):
            lab = Gtk.Label(label=name)
            ctx = lab.get_style_context()
            ctx.add_class("cal-wd")
            if col >= 5:
                ctx.add_class("cal-wd-off")
            self.grid.attach(lab, col, 0, 1, 1)

        # itermonthdates отдаёт ровно полные недели, включая хвосты соседних
        # месяцев, — из них и берётся постоянная высота сетки.
        weeks = list(calendar.Calendar(firstweekday=0).monthdatescalendar(y, m))
        # Сетка ВСЕГДА пять строк. Месяц изредка ложится на шесть недель —
        # тогда последняя, шестая, переносится в первую строку: её дни встают
        # в те клетки, где до этого стояли числа ПРЕДЫДУЩЕГО месяца. Свои дни
        # при этом не теряются никогда: шестая неделя начинается с понедельника,
        # а свободные клетки в первой строке — как раз первые, до числа 1.
        # Лишнее, что не поместилось, — только дни следующего месяца.
        if len(weeks) == 6:
            head, tail = weeks[0][:], weeks[5]
            free = [c for c, d in enumerate(head) if d.month != m]
            for c, day in zip(free, tail):
                head[c] = day
            weeks = [head] + weeks[1:5]
        # Обратный редкий случай: месяц укладывается ровно в четыре недели
        # (февраль 2027 начинается с понедельника и кончается воскресеньем).
        # Тогда пятая строка дописывается днями следующего месяца — они
        # приглушены, а число строк остаётся тем же.
        while len(weeks) < 5:
            last = weeks[-1][-1]
            weeks.append([last + datetime.timedelta(days=i)
                          for i in range(1, 8)])

        for row, week in enumerate(weeks, start=1):
            for col, day in enumerate(week):
                lab = Gtk.Label(label="%d" % day.day)
                ctx = lab.get_style_context()
                if day == today:
                    ctx.add_class("cal-today")
                else:
                    ctx.add_class("cal-day")
                    if day.month != m:
                        ctx.add_class("cal-pad")
                    if col >= 5:
                        ctx.add_class("cal-off")
                self.grid.attach(lab, col, row, 1, 1)

        self.hint.set_text("колесо — месяц · 0 — сегодня · клавиша — закрыть")
        self.grid.show_all()

    def on_scroll(self, _w, event):
        # Вверх — назад по времени, вниз — вперёд, как прокрутка ленты:
        # раньше было наоборот.
        if event.direction == Gdk.ScrollDirection.UP:
            self.offset -= 1
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.offset += 1
        else:
            return False
        self.redraw()
        self.bump_idle()
        return True

    def on_key(self, _w, event):
        name = Gdk.keyval_name(event.keyval)
        if name == "0":                      # вернуться на текущий месяц
            self.offset = 0
            self.redraw()
            self.bump_idle()
            return True
        if name in ("Left", "Right", "Up", "Down"):
            self.offset += 1 if name in ("Right", "Down") else -1
            self.redraw()
            self.bump_idle()
            return True
        # Всё остальное закрывает. Календарь смотрят мельком, и попадать
        # именно в Esc, чтобы убрать его с дороги, — лишнее условие.
        Gtk.main_quit()
        return True


if __name__ == "__main__":
    win = CalendarPopup()
    win.show_all()
    Gtk.main()
