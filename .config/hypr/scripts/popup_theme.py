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
BASE_CSS = """
window { background-color: transparent; }
.popup-box {
    background-color: %(surface)s; color: %(on_surface)s;
    font-family: sans-serif; font-weight: bold;
    /* Рамка цвета акцента: сразу видно, что попап открыт (была приглушённая).
       14.09.2026: 2px -> 3px, пользователь попросил рамку чуть толще. */
    border: 3px solid %(primary)s; border-radius: 12px; padding: 14px;
    /* Тёмный контур 1px снаружи рамки (14.09.2026): на светлых обоях светлая
       рамка акцента сливалась с фоном (календарь поверх #85a8e2). Мягкую тень
       с размытием убрали: окно обрезало её краем, и вокруг попапа стояла
       полупрозрачная серая полоса (просьба: «некрасивая рамка»). Контуру
       хватает поля 2px. */
    margin: 2px;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
}
button.item {
    background-color: %(surface_container)s; color: %(on_surface)s;
    border: 1px solid transparent; border-radius: 6px;
    padding: 6px; margin-bottom: 4px;
}
button.item:hover { background-color: %(surface_high)s; }
button.item-active {
    background-color: %(surface_high)s; color: %(primary)s;
    border: 1px solid %(primary)s; border-radius: 6px;
    padding: 6px; margin-bottom: 4px;
}
button.go {
    background-color: %(primary)s; color: %(on_primary)s;
    border: none; border-radius: 6px; padding: 4px 10px;
}
entry.pw {
    background-color: %(surface_container)s; color: %(on_surface)s;
    border: 1px solid %(outline_variant)s; border-radius: 6px; padding: 4px;
}
label.status { color: %(on_surface_variant)s; font-weight: normal; }
label.err { color: %(error)s; font-weight: normal; }
separator { background: %(outline_variant)s; margin: 10px 0; }
"""

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


def attached():
    return os.path.exists(ATTACHED_FILE) and bar_position() != "bottom"


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
.popup-attached > * > .popup-box, .popup-attached > * > .card, .popup-attached .cal-box {
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
    alloc = widget.get_allocation()
    W, H = alloc.width, alloc.height
    E, R, B = EAR, RADIUS_ATTACHED, BORDER_ATTACHED
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
    if bottom:                    # у нижнего края экрана — та же фигура вверх ногами
        cr.translate(0, H)
        cr.scale(1, -1)
    path(True)
    cr.set_source_rgba(*rgb(bg), 1.0)      # без прозрачности (05.10.2026: было 0.96 — сквозь плашку просвечивало)
    cr.fill_preserve()
    cr.clip()                     # рамка — только внутрь фигуры: ровно B пикселей
    path(False)
    cr.set_line_width(2 * B)
    cr.set_source_rgba(*rgb(ac), 1)
    cr.stroke()
    cr.restore()
    return False


def add_ears(align, bottom=False):
    """Если попапы «приклеены» — пометить align, положить по краям пустые
    отступы под вогнутые углы и рисовать фигуру (draw_attached). Слой попапа
    заходит на пиксель под бар (exclusive zone −1, отступ = высота бара − 1):
    так нижняя линия бара над попапом закрыта, и стыка не видно.
    Возвращает True, если режим включён."""
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
        # (appmem и т. п.) место ставится ДО того, как align попал в окно.
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


def css(extra="", **over):
    """Готовый CSS: общий каркас + `extra`, подстановка ролей палитры.

    `over` добавляет свои имена в подстановку — так попап задаёт, какой ролью
    красить шкалу, не заводя собственной палитры (см. SCALE_CSS).
    """
    p = palette()
    # Значение из `over` — это имя роли ("primary"), если такая роль есть,
    # иначе строка подставляется как есть (можно передать готовый #rrggbb).
    p.update({k: p.get(v, v) for k, v in over.items()})
    out = BASE_CSS + extra
    return (out % p).encode()


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


def bar_position():
    """Где стоит бар: "top" или "bottom" — по текущему виду (looks/current.jsonc).

    Вид «Снизу» ставит бар у нижнего края; тогда попапы должны открываться
    НАД ним, а не у верхнего края экрана, где бара нет.
    """
    import re
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


def pill_runs(mon, bar_h=32, gap_px=4):
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
                "wifi_popup.py": ("right", 174),
                "volume_popup.py": ("right", 52),
                # микрофон — в выдвижной группе звука, левее громкости (когда группа
                # раскрыта); без курсора плашка уезжала к правому краю экрана
                "mic_popup.py": ("right", 120)}


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
        align.set_margin_bottom(gap)
    else:
        align.set_valign(Gtk.Align.START)
        if not attached_now:
            align.set_margin_top(gap)
    cur = cursor_local_x()
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
                if best and dist(best) <= 260:
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

    src = "курсор" if cursor_local_x() else "память"

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
        # Линия акцента снизу осталась только у «во всю ширину»: у компактного
        # вида её убрали 12.09.2026 — черта по краю экрана мешала.
        if key == "edge":
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
    экрану — мышь в этот момент где угодно (пользователь 24.09.2026). «cursor»
    остаётся у попапов бара, его ставит place_under_cursor.

    Зазор считается от края слоя, а слой начинается уже под панелью (у бара
    своя exclusive zone), поэтому высоту бара прибавлять не нужно — где бы он
    ни стоял.

    detach_in_hover (04.10.2026): при верхнем баре
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
