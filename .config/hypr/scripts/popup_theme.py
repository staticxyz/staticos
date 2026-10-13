#!/usr/bin/env python3
"""Общая гамма и общий CSS для GTK-попапов бара.

Попапы писались по одному и каждый нёс собственную зашитую палитру Tokyo Night
(#1a1b26, #7aa2f7 и т.д.). Из-за этого они единственные во всей системе не
следовали за обоями: matugen перекрашивал бар, eww, терминал, GTK, Qt — а
попапы оставались синими на любых обоях.

Здесь палитра читается из ~/.cache/matugen/colors.json (шаблон matugen), а
запасная гамма — ровно та, что была зашита раньше, на случай если файла ещё
нет (первый запуск до первой смены обоев).
"""
import json
import os
import sys

PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")

def is_compact():
    try:
        return "compact" in os.readlink(os.path.expanduser(
            "~/.config/waybar/looks/current.css"))
    except OSError:
        return False

IS_COMPACT = is_compact()

FALLBACK = {
    "surface": "#1a1b26",
    "surface_container": "#24283b",
    "surface_high": "#313751",
    "on_surface": "#c0caf5",
    "on_surface_variant": "#a9b1d6",
    "primary": "#7aa2f7",
    "on_primary": "#1a1b26",
    "outline_variant": "#24283b",
    "error": "#f7768e",
    # Добавлены для попапов с ползунками и вторичными акцентами (громкость,
    # микрофон, плеер): ручка шкалы и подписи не должны быть того же цвета,
    # что и заполненная часть, иначе ползунок не видно на самой шкале.
    "secondary": "#7dcfff",
    "tertiary": "#bb9af7",
    "surface_highest": "#3b4261",
    "on_tertiary": "#1a1b26",
}


def palette():
    try:
        with open(PALETTE, encoding="utf-8") as f:
            p = json.load(f)
        return {k: p.get(k, v) for k, v in FALLBACK.items()}
    except Exception:
        return dict(FALLBACK)


# Общий каркас: подложка, рамка, кнопки списка, активный элемент, поле ввода,
# строка состояния. `item` — класс обычной кнопки списка, `item-active` —
# выбранной; каждому попапу остаётся только повесить их на свои кнопки.
_BORDER = "2px" if IS_COMPACT else "3px"
_RADIUS = "8px" if IS_COMPACT else "12px"
_PAD = "8px" if IS_COMPACT else "14px"
_ITEM_PAD = "4px" if IS_COMPACT else "6px"
_ITEM_RAD = "4px" if IS_COMPACT else "6px"
_ITEM_MB = "2px" if IS_COMPACT else "4px"
_SEP_M = "6px 0" if IS_COMPACT else "10px 0"
PAD = _PAD
BORDER = _BORDER
RADIUS = _RADIUS

BASE_CSS = """
window { background-color: transparent; }
.popup-box {
    background-color: %%(surface)s; color: %%(on_surface)s;
    font-family: sans-serif; font-weight: bold;
    border: %(brd)s solid %%(primary)s; border-radius: %(rad)s; padding: %(pad)s;
    margin: 2px;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
}
button.item {
    background-color: %%(surface_container)s; color: %%(on_surface)s;
    border: 1px solid transparent; border-radius: %(irad)s;
    padding: %(ipad)s; margin-bottom: %(imb)s;
}
button.item:hover { background-color: %%(surface_high)s; }
button.item-active {
    background-color: %%(surface_high)s; color: %%(primary)s;
    border: 1px solid %%(primary)s; border-radius: %(irad)s;
    padding: %(ipad)s; margin-bottom: %(imb)s;
}
button.go {
    background-color: %%(primary)s; color: %%(on_primary)s;
    border: none; border-radius: %(irad)s; padding: 4px 10px;
}
entry.pw {
    background-color: %%(surface_container)s; color: %%(on_surface)s;
    border: 1px solid %%(outline_variant)s; border-radius: %(irad)s; padding: 4px;
}
label.status { color: %%(on_surface_variant)s; font-weight: normal; }
label.err { color: %%(error)s; font-weight: normal; }
separator { background: %%(outline_variant)s; margin: %(sep)s; }
""" % {"brd": _BORDER, "rad": _RADIUS, "pad": _PAD, "ipad": _ITEM_PAD,
       "irad": _ITEM_RAD, "imb": _ITEM_MB, "sep": _SEP_M}

# Шкала громкости/яркости. Заполненная часть — акцент, ручка — вторичный цвет:
# одним и тем же цветом ручка сливается с заполнением и её не видно.
# Цвета `accent`/`knob` задаёт сам попап через css(SCALE_CSS, accent=..., ...),
# передавая ИМЯ роли палитры ("primary", "error", ...).
SCALE_CSS = """
scale trough { background-color: %(surface_container)s; border-radius: 4px; min-height: 8px; }
scale highlight { background-color: %(accent)s; border-radius: 4px; }
scale slider {
    min-width: 14px; min-height: 14px; margin: -3px;
    border-radius: 50%%; background-color: %(knob)s;
    /* Тёмная обводка ручки (14.09.2026): после перехода на scheme-vibrant
       tertiary (ручка) и primary (заливка) почти совпали — #cbbff8 против
       #adc6ff, контраст 1,00:1, ручка сливалась со шкалой. Обводка цветом
       подложки отделяет ручку от заливки при любой палитре. */
    border: 2px solid %(surface)s;
}
"""


# Компактный вариант списка: у попапов-списков (Wi-Fi, Bluetooth) главное —
# сколько строк видно сразу, поэтому кнопки ужимаются, а высвободившееся место
# уходит в список. Класс `icon` — для кнопок-иконок в шапке.
COMPACT_CSS = """
.popup-box { padding: 10px; }
button.item, button.item-active {
    padding: 3px 8px; margin-bottom: 2px; font-size: 12px;
}
button.icon {
    padding: 0 6px; margin: 0; min-width: 24px; min-height: 24px; font-size: 12px;
}
switch { min-width: 38px; min-height: 20px; }
switch slider { min-width: 16px; min-height: 16px; }
"""


def rgba(color, alpha):
    """#rrggbb -> "rgba(r, g, b, a)" — для попапов с полупрозрачными фонами."""
    c = color.lstrip("#")
    r, g, b = (int(c[i:i + 2], 16) for i in (0, 2, 4))
    return "rgba(%d, %d, %d, %s)" % (r, g, b, alpha)


# ── «Приклеенные» попапы (30.09.2026, по образцу Noctalia) ─────────────────
# Попап висит прямо под баром, без зазора, цветом бара, без верхней рамки, а в
# местах стыка — вогнутые «ушки»: бар словно стекает в попап. Включается в
# Настройках → Внешний вид (файл ATTACHED_FILE). Только для попапов, которые
# ставит place_under_cursor, и только когда бар сверху.
ATTACHED_FILE = os.path.expanduser("~/.config/hypr/state/popup-attached")
EAR = 14                 # радиус вогнутого угла, px


def minimal():
    """Вид системы Minimalistic (pixel_look.py set minimal): бар — капсула посередине."""
    try:
        import json
        with open(os.path.expanduser("~/.config/hypr/state/pixel-look.json")) as f:
            return json.load(f).get("mode") == "minimal"
    except (OSError, ValueError):
        return False


def attached():
    # В Minimalistic бара во всю ширину нет — клеиться не к чему: плашки отдельные
    # карточки под капсулой (13.10.2026, Просьба: «и плашки нужно пофиксить»).
    return os.path.exists(ATTACHED_FILE) and bar_position() != "bottom" and not minimal()


def _minimal_monitor(align):
    """Слой плашки — на монитор под указателем (капсула есть на каждом мониторе)."""
    if not on_niri() or pointer_monitor() is None:
        return
    from gi.repository import Gtk
    top = align.get_toplevel()
    if isinstance(top, Gtk.Window):
        try:
            import gi
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import GtkLayerShell
            GtkLayerShell.set_monitor(top, pointer_monitor())
        except Exception:
            pass


def minimal_center(align, gap=8):
    """Minimalistic: карточка по центру под капсулой, вид — MINIMAL_CSS (и для плашек со
    своим CSS: календарь .cal-box)."""
    from gi.repository import Gtk, Gdk
    align.set_valign(Gtk.Align.START)
    align.set_halign(Gtk.Align.CENTER)
    align.set_margin_top(gap)
    align.set_margin_start(0)
    align.set_margin_end(0)
    align._jarvis_minimal = True
    prov = Gtk.CssProvider()
    prov.load_from_data(MINIMAL_CSS.replace(".popup-box {", ".popup-box, .cal-box {").encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)


# Плашки в виде Minimalistic — как капсула бара: чёрные, тонкая рамка, крупное скругление.
MINIMAL_CSS = """
.popup-box {
    background-color: #000000;
    border: 1px solid alpha(#ffffff, 0.10);
    border-radius: 18px;
    box-shadow: 0 6px 18px rgba(0, 0, 0, 0.45);
}
"""


def bottom_overlap():
    """На сколько px нижняя XP-панель (xpbar.py) залезает за свою зону.

    В режиме «вплотную» панель отнимает у окон меньше своей высоты — окна
    садятся на неё. Слой на весь экран, уважающий зоны (выбор обоев), без
    поправки накрыл бы низ панели; эту величину ставить ему отступом снизу.
    Панель спрятана или её нет — 0. В режиме «при наведении» — 0 (она сама
    выезжает поверх всего)."""
    try:
        with open(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "xpbar-visible")) as f:
            return max(0, int(f.read().strip() or 0))
    except (OSError, ValueError):
        return 0


def bar_bg():
    """Цвет фона бара: @bar-bg из ~/.cache/matugen/sensor-colors.css."""
    import re
    try:
        m = re.search(r"@define-color\s+bar-bg\s+(#[0-9a-fA-F]{6})",
                      open(os.path.expanduser("~/.cache/matugen/sensor-colors.css")).read())
        if m:
            return m.group(1)
    except OSError:
        pass
    return palette()["surface"]


ATTACHED_CSS = """
/* Приклеенный попап рисует свою фигуру сам (draw_attached): фон и рамка —
   одним контуром вместе с вогнутыми углами. У самой коробки попапа фона и
   рамки нет, иначе поверх фигуры легли бы прежние линии. */
/* > * > * > — Центр управления: align > Revealer > EventBox > коробка (13.10.2026:
   без этого у него оставалась своя рамка — линия поверх стыка с баром). */
.popup-attached > * > .popup-box, .popup-attached > * > * > .popup-box,
.popup-attached > * > .card, .popup-attached .cal-box {
    background-color: transparent; background-image: none;
    border-width: 0; box-shadow: none; margin: 0;
}
"""
RADIUS_ATTACHED = 14      # скругление нижних углов приклеенного попапа
BORDER_ATTACHED = 3       # рамка — как у остальных попапов


def draw_attached(widget, cr, bottom=False):
    """Фигура приклеенного попапа на всю ширину align: сверху — во всю ширину
    (вплотную к бару), по краям — вогнутые углы радиусом EAR, дальше бока и
    скруглённое дно. Заливка — цвет бара, рамка акцентом по контуру, кроме
    верхней кромки (там стык с баром). Рисуется ДО детей (сигнал draw идёт
    раньше обработчика класса), содержимое попапа ложится сверху."""
    import math
    import cairo
    alloc = widget.get_allocation()
    W, H = alloc.width, alloc.height
    E, R, B = EAR, RADIUS_ATTACHED, BORDER_ATTACHED
    # Выезд из бара (13.10.2026, «как в Центре управления»): фигура высотой H·p
    # растёт от бара, содержимое съезжает следом и обрезано по ней. Размер align
    # при этом не меняется — snap_to_pill и слой стоят на месте (Revealer SLIDE
    # менял размер, отсюда и были лишние ушки над плашкой).
    p = getattr(widget, "_reveal_p", 1.0)
    full = H
    H = int(round(full * p))
    if p < 1:
        # clip и сдвиг остаются на cr и после этого обработчика — ими рисуются дети
        if bottom:
            cr.rectangle(0, full - H, W, H)
            cr.clip()
            cr.translate(0, full - H)
        else:
            cr.rectangle(0, 0, W, H)
            cr.clip()
            cr.translate(0, H - full)
    if W < 2 * E + 2 * R or H < E + R:
        return False

    def path(close):
        cr.new_path()
        cr.move_to(W, 0)
        cr.arc_negative(W, E, E, -math.pi / 2, -math.pi)          # правый вогнутый угол
        cr.line_to(W - E, H - R)
        cr.arc(W - E - R, H - R, R, 0, math.pi / 2)                # правый нижний
        cr.line_to(E + R, H)
        cr.arc(E + R, H - R, R, math.pi / 2, math.pi)              # левый нижний
        cr.line_to(E, E)
        cr.arc_negative(0, E, E, 0, -math.pi / 2)                  # левый вогнутый угол
        if close:
            cr.close_path()

    bg = bar_bg().lstrip("#")
    ac = palette()["primary"].lstrip("#")
    rgb = lambda h: tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    cr.save()
    if p < 1:
        cr.translate(0, -(full - H) if bottom else full - H)
    if bottom:                    # у нижнего края экрана — та же фигура вверх ногами
        cr.translate(0, full)
        cr.scale(1, -1)
    path(True)
    cr.set_source_rgba(*rgb(bg), 1.0)      # без прозрачности (05.10.2026: было 0.96 — сквозь плашку просвечивало)
    cr.fill_preserve()
    cr.clip()                     # рамка — только внутрь фигуры: ровно B пикселей
    path(False)
    cr.set_line_width(2 * B)
    cr.set_source_rgba(*rgb(ac), 1)
    cr.stroke()
    # Ушки — сужающиеся (13.10.2026, просьба: «плашки приклеиваются всё ещё не идеально»).
    # У кончика ушко продолжает нижнюю линию бара: та же толщина и тот же бледный цвет,
    # к боку плашки плавно растёт до рамки B акцентом. Раньше ушко было сразу 3 px яркое,
    # а линия бара — 1 px на 45 %, и на стыке была ступенька.
    w0, la = bar_line()
    tip = tuple(c1 * la + c0 * (1 - la) for c1, c0 in zip(rgb(ac), rgb(bg)))
    for cx, sgn in ((0, 1), (W, -1)):
        cr.new_path()                              # стереть ровную рамку на ушке
        cr.arc(cx, E, E + B + 1, -math.pi, 0)
        cr.arc_negative(cx, E, E - 0.5, 0, -math.pi)
        cr.close_path()
        cr.set_source_rgba(*rgb(bg), 1.0)
        cr.fill()
        N = 48
        outer, inner = [], []
        for i in range(N + 1):
            t = i / N                              # 0 — кончик у бара, 1 — бок плашки
            th = -math.pi / 2 + sgn * t * math.pi / 2
            w = w0 + (B - w0) * (1 - math.cos(t * math.pi)) / 2
            outer.append((cx + (E + w) * math.cos(th), E + (E + w) * math.sin(th)))
            inner.append((cx + E * math.cos(th), E + E * math.sin(th)))
        cr.new_path()
        cr.move_to(*inner[0])
        for pt in outer + inner[::-1]:
            cr.line_to(*pt)
        cr.close_path()
        g = cairo.LinearGradient(0, 0, 0, E)
        g.add_color_stop_rgba(0, *tip, 1)
        g.add_color_stop_rgba(1, *rgb(ac), 1)
        cr.set_source(g)
        cr.fill()
    cr.restore()
    return False


def bar_line():
    """Нижняя линия бара текущего вида: (толщина px, прозрачность акцента). Без линии — (0, 0).
    Читается из looks/current.css: border-bottom: Npx solid alpha(@primary, A)."""
    import re
    try:
        css = open(os.path.expanduser("~/.config/waybar/looks/current.css"), encoding="utf-8").read()
    except OSError:
        return 0, 0.0
    m = re.search(r"border-bottom:\s*(\d+)px\s+solid\s+(?:alpha\(@primary,\s*([0-9.]+)\)|@primary)", css)
    if not m:
        return 0, 0.0
    return int(m.group(1)), float(m.group(2) or 1.0)


def add_ears(align, bottom=False):
    """Если попапы «приклеены» — пометить align, положить по краям пустые
    отступы под вогнутые углы и рисовать фигуру (draw_attached). Слой попапа
    заходит на пиксель под бар (exclusive zone −1, отступ = высота бара − 1):
    так нижняя линия бара над попапом закрыта, и стыка не видно.
    Возвращает True, если режим включён.

    Вид Minimalistic (13.10.2026, Просьба: «они открываются не в том месте»): бар — капсула
    посередине, поэтому плашка бара встаёт по центру под ней отдельной карточкой. Сюда
    приходят все плашки бара (place_under_cursor, календарь, батарея), так что место и вид
    ставятся здесь одним разом; place_side после этого сам ставит свою сторону."""
    if minimal() and not bottom:
        minimal_center(align)
        return False
    if not attached():
        return False
    from gi.repository import Gtk
    align.get_style_context().add_class("popup-attached")
    # Свой провайдер стилей, повыше приоритетом: у «Энергии» и календаря CSS
    # собственный, не через css() — а сбросить фон их коробки нужно и им.
    from gi.repository import Gdk
    prov = Gtk.CssProvider()
    prov.load_from_data(ATTACHED_CSS.encode())
    Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), prov,
                                             Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
    for cls, pack in (("ear-l", align.pack_start), ("ear-r", align.pack_end)):
        ear = Gtk.Box()
        ear.get_style_context().add_class(cls)
        ear.set_size_request(EAR, 1)
        pack(ear, False, False, 0)
    align.set_app_paintable(True)
    align.connect("draw", lambda w, cr: draw_attached(w, cr, bottom))
    if bottom:
        # Снизу верхнего бара нет: попап стоит вплотную к нижнему краю — или к
        # XP-панели, если она видна. «Вплотную» она выступает над своей зоной, и без
        # поправки попап заезжал на неё (01.10.2026, Super+Alt+X).
        align.set_margin_bottom(bottom_overlap())
        return True
    def under_bar(*_a):
        # Заходим под бар, только когда align уже в окне-слое: у части попапов
        # (appmem) место ставится ДО того, как align попал в окно.
        top = align.get_toplevel()
        if not isinstance(top, Gtk.Window):
            return
        try:
            import gi
            gi.require_version("GtkLayerShell", "0.1")
            from gi.repository import GtkLayerShell
            if GtkLayerShell.is_layer_window(top):
                GtkLayerShell.set_exclusive_zone(top, -1)
                align.set_margin_top(max(0, bar_edge() + bar_height() - 1))
        except Exception:
            pass
    align.set_margin_top(0)
    under_bar()
    align.connect("hierarchy-changed", under_bar)
    return True


# Масштаб под системный шрифт (08.10.2026). Плашки рисовались под PxPlus 16 px; Cozette
# чёткий только на 13 px — текст стал в 13/16 меньше, а кнопки, поля и ползунки остались
# прежними («шрифт меньше стал, поэтому не сочетаются»). Пока действует правило fontswap
# (61-cozette-trial.conf), CSS и явные размеры ужимаются в 13/16; под PxPlus — 1, всё как было.
COZETTE_RULE = os.path.expanduser("~/.config/fontconfig/conf.d/61-cozette-trial.conf")
FIT_FLAG = os.path.expanduser("~/.config/hypr/state/cozette-fit")   # cozette_fit.py on|off
SCALE = 13 / 16 if os.path.exists(COZETTE_RULE) and os.path.exists(FIT_FLAG) else 1.0


def px(n):
    """Размер в пикселях под текущий шрифт. 1–3 px (рамки, волоски) не трогаются."""
    if SCALE == 1 or not isinstance(n, (int, float)) or abs(n) <= 3:
        return n
    return int(round(n * SCALE))


def scale_css(text):
    """Ужимает px в CSS под шрифт, кроме font-size (кегль подравнивает правило fontconfig)
    и значений до 3 px. Под PxPlus возвращает текст как есть."""
    if SCALE == 1:
        return text
    import re

    def decl(m):
        prop = m.group(1).strip().lower()
        if prop == "font-size":
            # Cozette чёткий только на 13/26/39 px — 12 и 16 мылились (12 px подписи рядом
            # с 13 px заголовками — «вид пока ужас»). Правило 61 ровняет кегль лишь у
            # запросов к PxPlus, а плашки просят шрифт системы — ровняем здесь.
            def snap(v):
                n = float(v.group(1))
                return "%dpx" % (13 if n < 20 else 26 if n < 33 else 39) if n > 3 else v.group(0)
            return m.group(1) + ":" + re.sub(r"(\d+(?:\.\d+)?)px", snap, m.group(2))
        if prop == "letter-spacing":
            return m.group(0)
        val = re.sub(r"(-?\d+(?:\.\d+)?)px",
                     lambda v: "%dpx" % px(float(v.group(1))) if abs(float(v.group(1))) > 3
                     else v.group(0), m.group(2))
        return m.group(1) + ":" + val
    return re.sub(r"([\w-]+)\s*:([^;{}]*)", decl, text)


def css(extra="", scale=True, **over):
    """Готовый CSS: общий каркас + `extra`, подстановка ролей палитры.

    `over` добавляет свои имена в подстановку — так попап задаёт, какой ролью
    красить шкалу, не заводя собственной палитры (см. SCALE_CSS).
    """
    p = palette()
    # Значение из `over` — это имя роли ("primary"), если такая роль есть,
    # иначе строка подставляется как есть (можно передать готовый #rrggbb).
    p.update({k: p.get(v, v) for k, v in over.items()})
    out = BASE_CSS + extra
    if scale:
        out = scale_css(out)
    out = out % p
    if minimal():
        out += MINIMAL_CSS
    return out.encode()


def on_niri():
    """Сеанс niri, а не Hyprland. Скрипты попапов общие для обоих композиторов."""
    return bool(os.environ.get("NIRI_SOCKET")) and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")


_SPOT = None


def pointer_spot():
    """Где сейчас указатель: {"mon": GdkMonitor, "x": X внутри монитора, "w": ширина}.
    None, если узнать не удалось. Считается один раз за запуск попапа.

    Hyprland отдаёт положение курсора командой (hyprctl cursorpos). У niri такой
    команды нет вовсе, поэтому там — проба: на каждый монитор кладётся прозрачный
    слой, и композитор сам сообщает, в какой из них попал указатель и в какой
    точке (событие enter). Это те же ~50 мс, что уходили на hyprctl.

    Зачем это нужно (21.09.2026): без явного монитора слой попапа встаёт на
    монитор с КЛАВИАТУРНЫМ фокусом. В Hyprland фокус монитора ходит за мышью, и
    всё совпадало само; в niri щелчок по бару фокус не переносит — «Энергия»,
    открытая с бара второго монитора, появлялась на первом.
    """
    global _SPOT
    if _SPOT is None:
        _SPOT = (_spot_niri() if on_niri() else _spot_hyprland()) or False
    return _SPOT or None


def _spot_hyprland():
    import subprocess
    from gi.repository import Gdk
    try:
        pos = subprocess.check_output(["hyprctl", "cursorpos"], text=True)
        cx, cy = (int(v) for v in pos.strip().split(","))
    except Exception:
        return None
    d = Gdk.Display.get_default()
    for i in range(d.get_n_monitors()):
        g = d.get_monitor(i).get_geometry()
        if g.x <= cx < g.x + g.width and g.y <= cy < g.y + g.height:
            return {"mon": d.get_monitor(i), "x": cx - g.x, "w": g.width}
    return None


def _spot_niri(timeout_ms=220):
    import gi
    gi.require_version("GtkLayerShell", "0.1")
    from gi.repository import Gtk, Gdk, GLib, GtkLayerShell
    d = Gdk.Display.get_default()
    if d is None:
        return None
    found, probes = {}, []
    loop = GLib.MainLoop()

    def hit(_w, ev, mon):
        if not found:
            found.update(mon=mon, x=int(ev.x), w=mon.get_geometry().width)
        loop.quit()
        return False

    for i in range(d.get_n_monitors()):
        mon = d.get_monitor(i)
        w = Gtk.Window()
        GtkLayerShell.init_for_window(w)
        GtkLayerShell.set_namespace(w, "jarvis-pointer-probe")
        GtkLayerShell.set_layer(w, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_monitor(w, mon)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(w, edge, True)
        GtkLayerShell.set_exclusive_zone(w, -1)        # и поверх бара: щёлкали-то по нему
        GtkLayerShell.set_keyboard_mode(w, GtkLayerShell.KeyboardMode.NONE)
        w.set_app_paintable(True)                      # ничего не рисуем — слой прозрачен
        visual = w.get_screen().get_rgba_visual()
        if visual:
            w.set_visual(visual)
        w.add_events(Gdk.EventMask.ENTER_NOTIFY_MASK | Gdk.EventMask.POINTER_MOTION_MASK)
        w.connect("enter-notify-event", hit, mon)
        w.connect("motion-notify-event", hit, mon)
        w.show_all()
        probes.append(w)
    GLib.timeout_add(timeout_ms, lambda: (loop.quit(), False)[1])
    loop.run()
    for w in probes:
        w.destroy()
    while Gtk.events_pending():
        Gtk.main_iteration()
    return found or None


def pointer_monitor():
    """GdkMonitor под указателем или None."""
    spot = pointer_spot()
    return spot["mon"] if spot else None


def cursor_local_x():
    """X курсора в координатах своего монитора и ширина монитора, или None."""
    spot = pointer_spot()
    return (spot["x"], spot["w"]) if spot else None


# Попап открыт из нижней XP-панели (xpbar.py ставит JARVIS_POPUP_FROM=xpbar, 05.10.2026:
# «ПКМ по звуку внизу — плашка открывается сверху, прилепленная к верхнему бару, криво»):
# для него «бар снизу» — встаёт над нижней панелью, отдельной плашкой, без ушек.
FROM_XPBAR = os.environ.get("JARVIS_POPUP_FROM") == "xpbar"


def bar_position():
    """Где стоит бар: "top" или "bottom" — по текущему виду (looks/current.jsonc).

    Вид «Снизу» ставит бар у нижнего края; тогда попапы должны открываться
    НАД ним, а не у верхнего края экрана, где бара нет.
    """
    import re
    if FROM_XPBAR:
        return "bottom"
    try:
        raw = open(os.path.expanduser("~/.config/waybar/looks/current.jsonc"),
                   encoding="utf-8").read()
    except OSError:
        return "top"
    m = re.search(r'"position"\s*:\s*"(\w+)"', raw)
    return m.group(1) if m else "top"


def pill_span_at(mon, x, bar_h=32, gap_px=4):
    """Пилюля под точкой x — см. pill_runs."""
    for a, b in pill_runs(mon, bar_h, gap_px) or []:
        if a - 2 <= x <= b + 2:
            return a, b
    return None


def pill_runs(mon, bar_h=32, gap_px=4, tight=False):
    """Границы пилюли бара под точкой x на мониторе mon: (left, right) или None.

    Waybar геометрию модулей не отдаёт, а попапу нужно встать ровно под
    пилюлей, а не под курсором (щёлкнули по краю — попап уехал в сторону,
    23.09.2026). Поэтому пилюля находится по картинке: grim снимает полосу
    бара этого монитора, и в средних строках ищется светлый участок фона
    вокруг x — пилюли светлее подложки бара. Соседние пилюли разделены
    полями (margin 3 px с каждой стороны), их и считаем разрывом.

    Возвращает None, если снять экран не удалось, под x ничего нет или
    участок подозрительно широк (слиплось несколько модулей) — тогда
    вызывающий центрирует под курсором, как раньше.
    """
    import subprocess
    import tempfile
    try:
        geo = mon.get_geometry()
        top = geo.y if bar_position() != "bottom" else geo.y + geo.height - bar_h
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            path = f.name
        subprocess.run(["grim", "-g", "%d,%d %dx%d" % (geo.x, top, geo.width, bar_h), path],
                       capture_output=True, timeout=2)
        import numpy as np
        from PIL import Image
        im = np.array(Image.open(path).convert("L")).astype(float)
        os.unlink(path)
        band = im[bar_h // 4: bar_h - bar_h // 4, :]
        col = band.mean(axis=0)
        lit = col > np.percentile(col, 20) + 6
        xs = np.where(lit)[0]
        if len(xs) == 0:
            return None
        runs, start, prev = [], xs[0], xs[0]
        for v in xs[1:]:
            if v - prev >= gap_px:
                runs.append((int(start), int(prev)))
                start = v
            prev = v
        runs.append((int(start), int(prev)))
        if tight:
            # Между пилюлями бывает не тёмная подложка, а полупрозрачная полоса чуть
            # светлее (08.10.2026: плеер и группа сети слиплись — щель 20 при фоне 14
            # и пилюлях 37). Делим участок там, где ≥ 4 px заметно темнее фона пилюли.
            out = []
            for a, b in runs:
                seg = col[a:b + 1]
                dark = seg < np.percentile(seg, 25) - 8
                cut, i = a, 0
                while i < len(seg):
                    if dark[i]:
                        j = i
                        while j < len(seg) and dark[j]:
                            j += 1
                        if j - i >= 4 and i > 0 and j < len(seg):
                            out.append((cut, a + i - 1))
                            cut = a + j
                        i = j
                    else:
                        i += 1
                out.append((cut, b))
            runs = out
        return runs
    except Exception:
        return None


def bar_height(default=32):
    """Высота бара из looks/current.jsonc — для среза полосы бара в pill_span_at."""
    import re
    try:
        raw = open(os.path.expanduser("~/.config/waybar/looks/current.jsonc"),
                   encoding="utf-8").read()
        m = re.search(r'"height"\s*:\s*(\d+)', raw)
        return int(m.group(1)) if m else default
    except OSError:
        return default


def bar_edge():
    """Отступ верхнего бара от края экрана, px: свой (bar_margins.py) или формы
    панели («Парящий» — 8). Приклеенный попап встаёт под бар с учётом его
    (01.10.2026: без этого при отступе сверху попапы наезжали на бар)."""
    try:
        import bar_margins
        return (bar_margins.custom() or bar_margins.look_values())[0]
    except Exception:
        return 0


# Попапы правой группы бара (network + bluetooth, затем раскладка, громкость):
# откуда считать место, если курсор неизвестен — край пилюли группы и отступ, px.
GROUP_ANCHOR = {"bluetooth_popup.py": ("left", 65),
                "bt_stats_popup.py": ("left", 65),   # анализ Bluetooth — тот же значок
                "wifi_popup.py": ("right", 174),
                "volume_popup.py": ("right", 52),
                # микрофон — в выдвижной группе звука, левее громкости (когда группа
                # раскрыта); без курсора плашка уезжала к правому краю экрана
                "mic_popup.py": ("right", 120),
                # «lan» — первый модуль группы, у её левого края (05.10.2026)
                "lan_popup.py": ("left", 32)}


# Попапы, чьё место надёжнее взять по пилюле бара, чем по курсору:
# (номер пилюли в снимке бара, отступ середины попапа от её левого края, px).
# lan_popup.py отсюда убран 13.10.2026: пилюль в баре больше нет (вид edge), его место —
# по значку, см. ICON_PICK.
PILL_PICK = {}

# Попапы, которые встают ровно под своим значком в баре (13.10.2026, Просьба: «плашка
# иногда открывается по-разному. Нужно, чтобы всегда открывалась прямо под иконкой в
# баре. Не левее, не правее, всегда»). Курсору здесь не верим: проба niri узнаёт, где
# мышь, через ~0,3 с после щелчка, и если рука уже повела мышь, x уезжал на 130–180 px
# (журнал: 1437 и 1490 при значке на 1622). Значок ищется на снимке полосы бара: столбцы
# с «чернилами» (заметно отличны от фона) собираются в кучки, кучка сверяется с
# запомненной маской значка (ICON_DIR/<имя>.json, цвет не важен — только форма).
#   имя попапа → (маски значка, сосед: искать справа от значка этого попапа, если своей
#                 маски нет, — Wi-Fi меняет вид: подключён / нет сети / выключен)
ICON_PICK = {"lan_popup.py": ("lan", None),
             "wifi_net_popup.py": ("wifi", "lan")}
ICON_DIR = os.path.expanduser("~/.local/share/jarvis/bar-icons")


def bar_ink(mon, bar_h=None):
    """Снимок полосы бара монитора mon → (маска чернил строки×столбцы, кучки [(a, b)])."""
    import subprocess
    import tempfile
    import numpy as np
    from PIL import Image
    bar_h = bar_h or bar_height()
    geo = mon.get_geometry()
    top = geo.y + bar_edge() if bar_position() != "bottom" else geo.y + geo.height - bar_h
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        path = f.name
    try:
        subprocess.run(["grim", "-g", "%d,%d %dx%d" % (geo.x, top, geo.width, bar_h), path],
                       capture_output=True, timeout=2)
        im = np.array(Image.open(path).convert("RGB")).astype(int)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    im = im[3:bar_h - 3]                          # без полосок-отметок у краёв бара
    bg = np.median(im, axis=1, keepdims=True)     # фон — свой у каждой строки
    ink = np.abs(im - bg).max(axis=2) > 48
    cols = np.where(ink.any(axis=0))[0]
    runs = []
    for v in cols:
        if runs and v - runs[-1][1] <= 3:
            runs[-1][1] = int(v)
        else:
            runs.append([int(v), int(v)])
    return ink, [tuple(r) for r in runs]


def _crop(ink, a, b):
    m = ink[:, a:b + 1]
    rows = [i for i in range(m.shape[0]) if m[i].any()]
    return m[rows[0]:rows[-1] + 1] if rows else m


def _same(m, t):
    """Похожа ли маска кучки на запомненную маску значка (IoU ≥ 0,75)."""
    import numpy as np
    if abs(m.shape[0] - len(t)) > 1 or abs(m.shape[1] - len(t[0])) > 1:
        return False
    tm = np.array([[c == "#" for c in row] for row in t])
    h, w = min(m.shape[0], tm.shape[0]), min(m.shape[1], tm.shape[1])
    a, b = m[:h, :w], tm[:h, :w]
    union = (a | b).sum()
    return union > 0 and (a & b).sum() / union >= 0.75


def icon_masks(name):
    try:
        return json.load(open(os.path.join(ICON_DIR, name + ".json")))
    except (OSError, ValueError):
        return []


def learn_icon(name, mask):
    """Запомнить ещё один вид значка (до 4: у Wi-Fi их три)."""
    t = ["".join("#" if c else "." for c in row) for row in mask]
    have = icon_masks(name)
    if any(_same(mask, h) for h in have):
        return
    os.makedirs(ICON_DIR, exist_ok=True)
    with open(os.path.join(ICON_DIR, name + ".json.tmp"), "w") as f:
        json.dump((have + [t])[-4:], f)
    os.replace(os.path.join(ICON_DIR, name + ".json.tmp"), os.path.join(ICON_DIR, name + ".json"))


def icon_center(mon, popup, hint=None):
    """Середина значка попапа popup в баре монитора mon (x внутри монитора) или None.

    hint — x курсора, если известен: из нескольких одинаковых значков берётся ближний.
    """
    name, after = ICON_PICK[popup]
    try:
        ink, runs = bar_ink(mon)
    except Exception:
        return None

    def find(nm):
        hits = [(a, b) for a, b in runs if b - a <= 40
                and any(_same(_crop(ink, a, b), t) for t in icon_masks(nm))]
        if hint is not None and hits:
            hits.sort(key=lambda r: abs((r[0] + r[1]) / 2 - hint))
        return hits[0] if hits else None
    hit = find(name)
    if not hit and after:
        # Своей маски нет (новый вид значка) — следующая кучка справа от соседа; её вид
        # запоминается, в следующий раз найдётся сразу.
        prev = find(after)
        nxt = [r for r in runs if prev and r[0] > prev[1]]
        if nxt and nxt[0][1] - nxt[0][0] <= 30:
            hit = nxt[0]
            learn_icon(name, _crop(ink, *hit))
    if not hit and hint is not None:
        # Маски нет совсем (первый запуск) — кучка, в которую попал курсор, если она
        # размером со значок. Запоминается только такая — с текстом не спутать.
        inside = [r for r in runs if r[0] - 2 <= hint <= r[1] + 2 and 8 <= r[1] - r[0] <= 24]
        if inside:
            hit = inside[0]
            learn_icon(name, _crop(ink, *hit))
    return (hit[0] + hit[1] + 1) / 2 if hit else None


def place_under_cursor(align, gap=6, edge=20, snap_to_pill=False, pill_width=None):
    """Поставить попап прямо под баром, серединой под точкой щелчка.

    Для попапов, чей слой прибит ко всем четырём краям (невидимый оверлей,
    закрывающий попап щелчком мимо). Такой слой начинается уже ПОД панелью —
    у waybar своя exclusive zone, — поэтому сверху нужен лишь зазор `gap`, а не
    высота бара: прежние 34 опускали попапы на целую полосу ниже.

    По горизонтали окно центрируется под курсором — в момент щелчка он внутри
    модуля, — и не свисает за поля бара (`edge`, как margin-left/right в
    config.jsonc). Ширину окна до раскладки не знает никто, поэтому отступ
    ставится в size-allocate. Если курсор узнать не удалось — к правому краю.
    """
    from gi.repository import Gtk
    attached_now = add_ears(align)
    # Бар снизу (вид «Снизу») — попап над ним, у нижнего края слоя.
    if bar_position() == "bottom":
        align.set_valign(Gtk.Align.END)
        # над XP-панелью: слой кончается у её зоны, а панель заходит выше на bottom_overlap
        align.set_margin_bottom(gap + (bottom_overlap() if FROM_XPBAR else 0))
    else:
        align.set_valign(Gtk.Align.START)
        if not attached_now:
            align.set_margin_top(gap)
    if getattr(align, "_jarvis_minimal", False):     # Minimalistic: по центру под капсулой
        _minimal_monitor(align)
        return
    cur = cursor_local_x()
    placed_by_pill = False
    # Слой — на монитор под указателем. Нужно для niri (см. pointer_spot); в
    # Hyprland монитор и так совпадает, там ничего не трогаем.
    if on_niri() and pointer_monitor() is not None:
        top = align.get_toplevel()
        if isinstance(top, Gtk.Window):
            try:
                import gi
                gi.require_version("GtkLayerShell", "0.1")
                from gi.repository import GtkLayerShell
                GtkLayerShell.set_monitor(top, pointer_monitor())
            except Exception:
                pass
    # Где курсор, niri говорит только после движения мыши. Касание тачпада — без движения,
    # и попап вставал у правого края экрана (04.10.2026: «с ноутбука плашки
    # открываются не на своих местах, правее»). Поэтому каждый попап помнит, где открылся
    # в прошлый раз (пилюли бара на месте), и без курсора встаёт туда же.
    key = "%s:%s" % (os.path.basename(sys.argv[0] or "popup"), bar_position())
    cache = os.path.expanduser("~/.cache/jarvis/popup-last-x.json")
    if not cur:
        try:
            import json as _j
            last = _j.load(open(cache)).get(key)
        except (OSError, ValueError):
            last = None
        if not last and GROUP_ANCHOR.get(key.split(":")[0]):
            last = [0, 1920]                      # группа: место считается ниже от пилюли
        if last:
            cur = (int(last[0]), int(last[1]))
            # Модули правой группы бара двигаются: группа прижата вправо, а Bluetooth
            # появляется слева в ней, только когда что-то подключено («✱ AirPods 40%»).
            # Поэтому место считается от края пилюли группы, найденной по снимку бара:
            # Bluetooth — от левого края, Wi-Fi и громкость — от правого (04.10.2026:
            # «посмотри, где настройка Bluetooth и где открывается плашка»).
            anchor = GROUP_ANCHOR.get(key.split(":")[0])
            if anchor:
                # Монитор: под указателем, а если он неизвестен (тот самый случай) — первый.
                from gi.repository import Gdk
                mon = pointer_monitor() or Gdk.Display.get_default().get_monitor(0)
                runs = pill_runs(mon, bar_h=bar_height()) or []
                # Группа сети — пилюля справа, перед датой; её правый край на месте.
                # Запомненное x тут не опора: оно бывает «чужим» (04.10.2026 — попап
                # открыли руками, когда мышь была в стороне, и он запомнил 1244).
                probe = cur[1] - 220
                run = min(runs, key=lambda r: 0 if r[0] <= probe <= r[1]
                          else min(abs(probe - r[0]), abs(probe - r[1])), default=None)
                if run:
                    side, off = anchor
                    cur = (run[0] + off if side == "left" else run[1] - off, cur[1])
    # «lan» — первый модуль группы, а группа — третья пилюля с конца (за ней часы и
    # питание). Курсору тут не верим: niri отдаёт положение мыши только после движения,
    # и плашка вставала на 50–150 px левее (журнал 08.10.2026: «щелчок» 1321 при lan
    # на 1440–1490; Просьба: «иногда чуть левее»). Место — от левого края пилюли группы.
    pick = PILL_PICK.get(key.split(":")[0])
    if pick:
        from gi.repository import Gdk
        mon = pointer_monitor() or Gdk.Display.get_default().get_monitor(0)
        runs = [r for r in (pill_runs(mon, bar_h=bar_height(), tight=True) or []) if r[1] - r[0] >= 10]
        idx, off = pick
        if len(runs) >= abs(idx) and 120 <= runs[idx][1] - runs[idx][0] <= 900:
            cur = (runs[idx][0] + off, mon.get_geometry().width)
            placed_by_pill = True
    if ICON_PICK.get(key.split(":")[0]) and bar_position() != "bottom":
        from gi.repository import Gdk
        mon = pointer_monitor() or Gdk.Display.get_default().get_monitor(0)
        real = cursor_local_x()
        ic = icon_center(mon, key.split(":")[0], real[0] if real else None)
        if ic is not None:
            cur = (ic, mon.get_geometry().width)
            placed_by_pill = "значок"
    if not cur:
        align.set_halign(Gtk.Align.END)
        align.set_margin_end(edge)
        return
    align.set_halign(Gtk.Align.START)
    src_mem = cursor_local_x() is None
    x, mon_w = cur
    # snap_to_pill: середина попапа — под серединой пилюли, а не под курсором.
    if snap_to_pill and pointer_monitor() is not None:
        runs = pill_runs(pointer_monitor(), bar_h=bar_height()) or []
        span = next(((a, b) for a, b in runs if a - 2 <= x <= b + 2), None)
        found = span
        by_width = False
        if pill_width and runs:
            # Точке «щелчка» верить нельзя: niri сообщает положение указателя
            # только после первого движения мыши, и если после щелчка рука уже
            # повела мышь, x уезжает на 100–200 px (журнал 30.09.2026: пилюля
            # плеера 1250–1425, а «щелчок» записан на 1439 и 1530). Поэтому,
            # когда ширина пилюли известна, ищем пилюлю ЭТОЙ ширины — отдельную
            # или край слипшегося участка — ближайшую к указателю.
            # Сначала — отдельные пилюли точно этой ширины; края слипшихся
            # участков — только если таких нет (иначе край соседней группы
            # «lan» той же ширины перехватывал бы выбор).
            exact = [(a, b) for a, b in runs if abs((b - a) - pill_width) <= 8]
            merged = []
            for a, b in runs:
                if (b - a) > pill_width + 12:
                    merged += [(a, a + pill_width), (b - pill_width, b)]

            def dist(c):
                return 0 if c[0] <= x <= c[1] else min(abs(x - c[0]), abs(x - c[1]))
            for cands in (exact, merged):
                best = min(cands, key=dist) if cands else None
                # 100px, не 260: 260 давало «не ту» пилюлю шириной 148 —
                # например, lan вместо плеера (12.10.2026: клик 1544, пилюля
                # (1220,1368) ошибочно выбрана). Больше 100 — ошибка не курсора.
                if best and dist(best) <= 100:
                    span = found = best
                    by_width = True
                    break
        if span and not by_width and not pill_width and span[1] - span[0] > 260:
            # Ширину пилюли узнать не вышло, а участок подозрительно широк —
            # значит, слиплось с соседом. Раньше попап вставал по середине
            # слипшегося участка: плеер + группа «lan» → на 180 px правее
            # пилюли (30.09.2026, «иногда не прямо под плеером»).
            # Лучше уж под точкой щелчка.
            span = None
        if span and not by_width and pill_width and span[1] - span[0] > pill_width + 12:
            # Слиплось с соседом. Раньше всегда брался ЛЕВЫЙ край — и если сосед
            # прилип слева, попап уезжал далеко вправо (30.09.2026: «иногда
            # чуть правее, иногда вообще далеко»). Теперь из двух вариантов — от
            # левого края и от правого — берётся тот, что накрывает точку щелчка.
            left = (span[0], span[0] + pill_width)
            right = (span[1] - pill_width, span[1])
            hits = [c for c in (left, right) if c[0] - 4 <= x <= c[1] + 4]
            span = hits[0] if len(hits) == 1 else None
        if span and (by_width or span[0] - 4 <= x <= span[1] + 4):
            x_click, x = x, (span[0] + span[1]) / 2
        else:
            x_click = x
        # Журнал раскладки: если попап снова встанет криво — видно, почему.
        try:
            import time as _t
            with open(os.path.expanduser("~/.cache/jarvis/popup-place.log"), "a") as f:
                f.write("%s click=%d found=%s pill_w=%s -> center=%d\n" % (
                    _t.strftime("%m-%d %H:%M:%S"), x_click, found, pill_width, x))
        except OSError:
            pass

    try:                                          # запомнить место этого попапа
        if src_mem or GROUP_ANCHOR.get(key.split(":")[0]):
            raise OSError                         # из памяти — не переписывать; группа — считается
        import json as _j
        try:
            data = _j.load(open(cache))
        except (OSError, ValueError):
            data = {}
        if data.get(key) != [int(x), int(mon_w)]:
            data[key] = [int(x), int(mon_w)]
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            with open(cache + ".tmp", "w") as f:
                _j.dump(data, f)
            os.replace(cache + ".tmp", cache)
    except OSError:
        pass

    src = placed_by_pill if isinstance(placed_by_pill, str) else "пилюля" if placed_by_pill else "курсор" if cursor_local_x() else "память"

    def on_alloc(widget, alloc):
        left = int(x - alloc.width / 2)
        left = max(edge, min(left, mon_w - alloc.width - edge))
        if widget.get_margin_start() != left:            # журнал: откуда место и куда встал
            try:
                import time as _t
                with open(os.path.expanduser("~/.cache/jarvis/popup-place.log"), "a") as f:
                    f.write("%s %s x=%d (%s) ширина=%d -> левый край %d\n" % (
                        _t.strftime("%m-%d %H:%M:%S"), key, x, src, alloc.width, left))
            except OSError:
                pass
        if widget.get_margin_start() != left:
            widget.set_margin_start(left)
    align.connect("size-allocate", on_alloc)


def single_instance(path):
    """Переключатель попапа: если этот же попап уже открыт — закрыть его и выйти.

    Так второй щелчок по модулю бара закрывает попап. Раньше в попапах
    громкости и микрофона это делалось через `pgrep -f имя.py` и `kill -9` по
    всем найденным процессам. pgrep -f ищет имя в ПОЛНОЙ командной строке
    ЛЮБОГО процесса, поэтому под kill -9 попадал всякий, у кого имя файла
    просто встречается в аргументах: терминал, где набрана команда с этим
    именем, редактор с открытым файлом, grep по скриптам. Проверено на себе:
    тестовый запуск с именем файла в командной строке убил сам себя.

    Здесь процесс засчитывается, только если по /proc видно, что это питон,
    запустивший ИМЕННО этот файл. И закрывается он обычным SIGTERM, а не
    kill -9, который не даёт процессу завершиться по-человечески.
    """
    import sys
    target = os.path.abspath(path)
    me = os.getpid()
    closed = False
    for p in os.listdir("/proc"):
        if not p.isdigit() or int(p) == me:
            continue
        try:
            with open(f"/proc/{p}/cmdline", "rb") as f:
                argv = [a.decode("utf-8", "replace") for a in f.read().split(b"\0") if a]
        except OSError:
            continue
        if (len(argv) >= 2 and "python" in os.path.basename(argv[0])
                and os.path.abspath(argv[1]) == target):
            try:
                os.kill(int(p), 15)
                closed = True
            except OSError:
                pass
    if closed:
        sys.exit(0)


def draw_bar_look(cr, w, h, key, pal):
    """Миниатюра вида бара: «экран», бар и два окна, в цветах палитры.

    Общая для панели «Энергия» и приложения «Настройки»: одна схемка —
    одинаковые миниатюры в обоих местах.
    """
    import math

    def color(hexs, a=1.0):
        x = hexs.lstrip("#")
        cr.set_source_rgba(int(x[0:2], 16) / 255, int(x[2:4], 16) / 255,
                           int(x[4:6], 16) / 255, a)

    def rrect(x, y, ww, hh, r):
        cr.new_sub_path()
        cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def bar(x, y, ww, hh, r):
        color(pal["primary"], 0.30)
        rrect(x, y, ww, hh, r)
        cr.fill()
        color(pal["primary"], 0.85)
        cr.set_line_width(1)
        rrect(x + 0.5, y + 0.5, ww - 1, hh - 1, r)
        cr.stroke()

    cr.save()
    rrect(0, 0, w, h, 6)
    cr.clip()
    color(pal["surface_container"])
    cr.paint()
    wy = 5 if key == "bottom" else 17
    color(pal["surface_high"], 0.9)
    left_w = (w - 21) * 0.5
    rrect(8, wy, left_w, h - 24, 3)
    cr.fill()
    rrect(8 + left_w + 5, wy, w - 16 - left_w - 5, h - 24, 3)
    cr.fill()
    if key in ("edge", "edge-compact"):
        # Разница «обычный / компакт» на миниатюре намеренно преувеличена:
        # в жизни это 32 px против 26, и на схемке в палец шириной два пикселя
        # разницы не видны вовсе (замечено пользователем 21.09.2026).
        hh = 6 if key == "edge-compact" else 12
        color(pal["primary"], 0.30)
        cr.rectangle(0, 0, w, hh)
        cr.fill()
        # Линия акцента снизу — у обоих (12.09.2026 её убирали у компактного,
        # 13.10.2026 пользователь спросил, почему она пропадает, — вернули).
        if True:
            color(pal["primary"], 0.85)
            cr.rectangle(0, hh, w, 1)
            cr.fill()
    elif key == "islands":
        bar(8, 4, w * 0.24, 8, 3)
        bar(w * 0.38, 4, w * 0.24, 8, 3)
        bar(w * 0.70, 4, w * 0.30 - 8, 8, 3)
    elif key == "transparent":
        for x, ww in ((10, 10), (24, 8), (w * 0.42, 16), (w - 42, 12), (w - 26, 16)):
            color(pal["primary"], 0.55)
            rrect(x, 5, ww, 6, 3)
            cr.fill()
    elif key == "compact":
        bar(8, 5, w - 16, 5, 2)
    elif key == "bottom":
        bar(8, h - 13, w - 16, 10, 3)
    else:
        bar(8, 3, w - 16, 10, 3)
    cr.restore()
    return False


def draw_layout_look(cr, w, h, key, pal):
    """Миниатюра раскладки окон для «Настроек»: «классика» или «лента».

    dwindle   — окна делят экран: одно слева, два друг над другом справа.
    scrolling — окна-колонки на ленте, последняя уходит за правый край:
                видно, что лента продолжается. Активная колонка обведена.
    """
    import math

    def color(hexs, a=1.0):
        x = hexs.lstrip("#")
        cr.set_source_rgba(int(x[0:2], 16) / 255, int(x[2:4], 16) / 255,
                           int(x[4:6], 16) / 255, a)

    def rrect(x, y, ww, hh, r):
        cr.new_sub_path()
        cr.arc(x + ww - r, y + r, r, -math.pi / 2, 0)
        cr.arc(x + ww - r, y + hh - r, r, 0, math.pi / 2)
        cr.arc(x + r, y + hh - r, r, math.pi / 2, math.pi)
        cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cr.close_path()

    def window(x, y, ww, hh, active=False):
        color(pal["surface_high"], 0.95)
        rrect(x, y, ww, hh, 3)
        cr.fill()
        if active:
            color(pal["primary"], 0.9)
            cr.set_line_width(1.5)
            rrect(x + 0.75, y + 0.75, ww - 1.5, hh - 1.5, 3)
            cr.stroke()

    cr.save()
    rrect(0, 0, w, h, 6)
    cr.clip()
    color(pal["surface_container"])
    cr.paint()
    color(pal["primary"], 0.30)                 # бар сверху, как на миниатюрах вида
    rrect(8, 4, w - 16, 6, 3)
    cr.fill()
    top, bottom, gap = 14, h - 6, 5
    hh = bottom - top
    if key == "dwindle":
        lw = (w - 16 - gap) * 0.5
        window(8, top, lw, hh, active=True)
        rw = w - 16 - gap - lw
        half = (hh - gap) / 2
        window(8 + lw + gap, top, rw, half)
        window(8 + lw + gap, top + half + gap, rw, half)
    else:
        col = (w - 16 - gap) * 0.42
        x = 8
        for i in range(4):                       # четвёртая колонка — за краем
            window(x, top, col, hh, active=(i == 1))
            x += col + gap
    cr.restore()
    return False

PLACES = [
    ("top-left", "сверху слева"),
    ("top-center", "сверху по центру"),
    ("top-right", "сверху справа"),
    ("bottom-left", "снизу слева"),
    ("bottom-center", "снизу по центру"),
    ("bottom-right", "снизу справа"),
]
PLACE_DEFAULT = "top-right"
PLACE_DIR = os.path.expanduser("~/.config/hypr/state")


def place_get(name, default=PLACE_DEFAULT, extra=()):
    """Где показывать карточку `name`. `extra` — свои значения сверх общих
    (у окна лимитов есть ещё «под курсором»)."""
    allowed = [k for k, _ in PLACES] + list(extra)
    try:
        with open(os.path.join(PLACE_DIR, name + "-place")) as f:
            value = f.read().strip()
    except OSError:
        return default
    # Старые значения без вертикали: раньше карточки вставали только под баром.
    if value in ("left", "center", "right"):
        value = "top-" + value
    return value if value in allowed else default


def place_set(name, value, extra=()):
    if value not in [k for k, _ in PLACES] + list(extra):
        return place_get(name)
    os.makedirs(PLACE_DIR, exist_ok=True)
    path = os.path.join(PLACE_DIR, name + "-place")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(value + "\n")
    os.replace(tmp, path)
    return value


def top_bar_hover():
    """Верхний бар в режиме «при наведении» (top_bar.py): спрятан, пока мышь не у верхнего края."""
    try:
        return open(os.path.expanduser("~/.config/hypr/state/top-bar")).read().strip() == "hover"
    except OSError:
        return False


def place_side(align, spot=PLACE_DEFAULT, gap=6, edge=20, detach_in_hover=False):
    """Поставить карточку у края экрана: «<верх|низ>-<лево|центр|право>».

    Для окон, которые зовут с клавиши: под курсором они «прыгали» бы по
    экрану — мышь в этот момент где угодно (24.09.2026). «cursor»
    остаётся у попапов бара, его ставит place_under_cursor.

    Зазор считается от края слоя, а слой начинается уже под панелью (у бара
    своя exclusive zone), поэтому высоту бара прибавлять не нужно — где бы он
    ни стоял.

    detach_in_hover (04.10.2026, пользователь про приклеенную плашку): при верхнем баре
    «при наведении» бара на экране нет, и приклеенная к нему плашка висела у края
    ни к чему — тогда она открывается отдельно: с зазором и со своей рамкой.
    """
    from gi.repository import Gtk
    glue = not (detach_in_hover and top_bar_hover())
    vert, _, horiz = spot.partition("-")
    if vert == "bottom":
        align.set_valign(Gtk.Align.END)
        if not add_ears(align, bottom=True):
            align.set_margin_bottom(gap + bottom_overlap())
    else:
        align.set_valign(Gtk.Align.START)
        if not (glue and add_ears(align)):
            # отдельная плашка при баре «при наведении»: бар выезжает поверх окон и не
            # резервирует место — ставим плашку НИЖЕ его места, чтобы не закрывала бар,
            # который можно вызвать, пока она открыта (04.10.2026)
            align.set_margin_top(gap + (bar_edge() + bar_height() if not glue else 0))
    if horiz == "left":
        align.set_halign(Gtk.Align.START)
        align.set_margin_start(edge)
    elif horiz == "center":
        align.set_halign(Gtk.Align.CENTER)
    else:
        align.set_halign(Gtk.Align.END)
        align.set_margin_end(edge)


# ── Анимация появления/закрытия (12.10.2026) ─────────────────────────────
# Любой попап бара можно открыть «проявлением»: обернуть его содержимое в
# Gtk.Revealer, направление определить по положению бара. Закрывается
# симметрично: сначала откатить revealer, после — Gtk.main_quit().
#
# Применение в попапе:
#   window = Gtk.Window(...); window.add(align); align.add(root_box)
# заменить на:
#   revealer = animate_open(window, align, root_box)   # root_box уже внутри
#   def quit(*_a):
#       animate_close(revealer, Gtk.main_quit)
#   window.connect("button-press-event", lambda *_: (quit(), True)[1])
def animate_open(window, align, root, duration=200):
    """Вставляет Gtk.Revealer между align и root. Запускает проявление после
    первой отрисовки окна (обработчик map).

    Возвращает Revealer — его нужен для animate_close.
    """
    try:
        from gi.repository import Gtk, GLib
    except Exception:
        return None
    # Если root уже сидит в align, снять его оттуда.
    parent = root.get_parent() if hasattr(root, "get_parent") else None
    if parent is not None:
        parent.remove(root)
    # Приклеенные плашки (add_ears → draw_attached по сигналу draw самого align)
    # не оборачиваем в Revealer: draw рисует фигуру по размеру align, а Revealer
    # добавляет свою область геометрии, из-за которой align вытягивается и над
    # попапом видна лишняя линия/ушки (12.10.2026). В «приклеенном» режиме попап
    # прилегает к бару — анимации почти не видно, можно без неё.
    try:
        if "popup-attached" in align.get_style_context().list_classes():
            align.add(root)
            return _AttachedReveal(window, align, duration + 20)
    except Exception:
        pass
    rev = Gtk.Revealer()
    # CROSSFADE, не SLIDE: SLIDE меняет размер и ломает позиционирование у
    # snap_to_pill (margin_start посчитан под фиксированную ширину).
    rev.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
    rev.set_transition_duration(duration)
    rev.set_reveal_child(False)
    rev.add(root)
    align.add(rev)
    rev.show()
    window.connect("map", lambda _w: GLib.timeout_add(
        10, lambda: (rev.set_reveal_child(True), False)[1]))
    return rev


class _AttachedReveal:
    """Выезд приклеенной плашки из бара (13.10.2026): draw_attached рисует фигуру
    высотой H·align._reveal_p, здесь p идёт 0→1 по кадрам с замедлением в конце
    (ease-out, как SLIDE у Revealer в Центре управления). Для animate_close
    выглядит как Revealer: set_reveal_child / get_transition_duration."""

    def __init__(self, window, align, duration):
        from gi.repository import GLib
        self.align, self.duration = align, duration
        self._target, self._from, self._t0, self._tick = 0.0, 0.0, None, None
        align._reveal_p = 0.0
        window.connect("map", lambda _w: GLib.timeout_add(
            10, lambda: (self.set_reveal_child(True), False)[1]))

    def get_transition_duration(self):
        return self.duration

    def set_reveal_child(self, on):
        self._from = getattr(self.align, "_reveal_p", 1.0)
        self._target = 1.0 if on else 0.0
        self._t0 = None
        if self._tick is None:
            try:
                self._tick = self.align.add_tick_callback(self._step)
            except Exception:           # нет часов кадров — сразу конечный вид
                self.align._reveal_p = self._target
                self.align.queue_draw()

    def _step(self, widget, clock):
        now = clock.get_frame_time() / 1000.0          # мс
        if self._t0 is None:
            self._t0 = now
        t = min(1.0, (now - self._t0) / max(1, self.duration))
        k = 1 - (1 - t) ** 3                           # ease-out cubic
        widget._reveal_p = self._from + (self._target - self._from) * k
        widget.queue_draw()
        if t >= 1:
            self._tick = None
            return False
        return True


def animate_close(revealer, on_done):
    """Откатывает revealer, затем вызывает on_done (обычно Gtk.main_quit).
    Повторный вызов во время анимации игнорируется.
    """
    try:
        from gi.repository import GLib
    except Exception:
        on_done()
        return
    if revealer is None:
        on_done()
        return
    if getattr(revealer, "_closing", False):
        return
    revealer._closing = True
    try:
        revealer.set_reveal_child(False)
        GLib.timeout_add(revealer.get_transition_duration() + 20, lambda: (on_done(), False)[1])
    except Exception:
        on_done()
