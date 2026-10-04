#!/usr/bin/env python3
"""Лента обоев — SUPER+W (19.09.2026, по эскизу пользователя).

Наклонные кадры-параллелограммы в ряд: выбранный крупнее и полной яркости,
соседние приглушены и обведены тонкой линией. Ничего лишнего — ни карточки, ни
подсказок: под лентой только имя выбранных обоев. Фон размывает Hyprland
(layer_rule «wallpapers-glass» в visuals.lua, слой jarvis-wallpapers).

Клавиши: ←/→, j/k или h/l (j — влево, k — вправо, как SUPER+J/K в Hyprland;
работают и на кириллической раскладке — о/л, р/д), Home/End — к первой и
последней, Enter или щелчок — поставить, Esc/q — закрыть, колесо листает.

Вся лента — один Gtk.DrawingArea: наклон, наложение кадров и плавный переход
(ширина, яркость и сдвиг ленты идут к цели долей пути за кадр) ровнее рисовать
самому, чем собирать из виджетов — у Gtk.ScrolledWindow в центрированной
колонке ширина схлопывалась до одного кадра (проверено 19.09.2026).

Обои ставит waypaper (`--wallpaper`), он же запускает post_command
(scripts/theme_changer.sh) — палитра и приложения перекрашиваются прежним
путём. Прежнее окно waypaper сеткой — SUPER+SHIFT+W.

Миниатюры 480 px кэшируются в ~/.cache/wallpaper-thumbs (имя + время правки),
собираются в фоне от выбранной к краям — окно открывается сразу.
"""
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, GLib, GtkLayerShell  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import popup_theme  # noqa: E402

popup_theme.single_instance(__file__)

WAYPAPER_CONF = os.path.expanduser("~/.config/waypaper/config.ini")
DEFAULT_FOLDER = os.path.expanduser("~/wallpapers/main")


def wallpaper_folder():
    """Папка с обоями — та же, что у waypaper (SHIFT+W).

    Одно место на двоих: сменил папку в waypaper — сменилась и здесь, руками
    править этот файл не нужно (21.09.2026).
    """
    try:
        with open(WAYPAPER_CONF) as f:
            for line in f:
                key, _, value = line.partition("=")
                if key.strip() == "folder" and value.strip():
                    return os.path.expanduser(value.strip())
    except OSError:
        pass
    return DEFAULT_FOLDER


FOLDER = wallpaper_folder()
STATE = os.path.expanduser("~/.cache/matugen/wallpaper")
THUMBS = os.path.expanduser("~/.cache/wallpaper-thumbs")
EXTS = (".jpg", ".jpeg", ".png", ".webp")

NORM_W, NORM_H = 300, 169     # обычный кадр, 16:9
SEL_W, SEL_H = 430, 242       # выбранный
SKEW = 52                     # верх кадра сдвинут вправо от низа на столько
GAP = 26                      # просвет между кадрами
DIM = 0.45                    # яркость невыбранных
ANIM_MS = 16                  # кадр анимации (~60 в секунду)
EASE = 0.22                   # доля пути за кадр: меньше — мягче

# Кириллица на тех же клавишах: j/k/h/l → о/л/р/д, q → й.
LEFT_KEYS = ("Left", "h", "j", "Cyrillic_er", "Cyrillic_o")
RIGHT_KEYS = ("Right", "l", "k", "Cyrillic_de", "Cyrillic_el")
CLOSE_KEYS = ("Escape", "q", "Cyrillic_shorti")
# f / а — выбрать другую папку с обоями (21.09.2026).
FOLDER_KEYS = ("f", "F", "Cyrillic_a", "Cyrillic_A")


def wallpapers(folder=None):
    """Картинки папки: новые слева, старые справа (просьба 21.09.2026).

    Порядок по времени файла, от свежего к старому; при одинаковом времени —
    по имени, чтобы лента не перетасовывалась между запусками.
    """
    folder = folder or FOLDER
    try:
        names = [n for n in os.listdir(folder) if n.lower().endswith(EXTS)]
    except OSError:
        return []
    paths = [os.path.join(folder, n) for n in names]

    def age(path):
        try:
            return -os.stat(path).st_mtime
        except OSError:
            return 0.0

    paths.sort(key=lambda p: (age(p), os.path.basename(p).lower()))
    return paths


def set_wallpaper_folder(folder):
    """Запомнить новую папку в конфиге waypaper — он общий для SUPER+W и SHIFT+W.

    Переписываем одну строку, остальной конфиг не трогаем: там ещё команда
    после смены обоев (theme_changer.sh) и прочие настройки waypaper.
    """
    try:
        with open(WAYPAPER_CONF) as f:
            lines = f.readlines()
    except OSError:
        return False
    out, done = [], False
    for line in lines:
        if line.partition("=")[0].strip() == "folder":
            out.append("folder = %s\n" % folder)
            done = True
        else:
            out.append(line)
    if not done:
        out.append("folder = %s\n" % folder)
    try:
        with open(WAYPAPER_CONF, "w") as f:
            f.writelines(out)
    except OSError:
        return False
    return True


def current():
    try:
        with open(STATE) as f:
            return f.read().strip()
    except OSError:
        return ""


def thumb_path(path):
    st = os.stat(path)
    name = "%s-%d.png" % (os.path.basename(path), int(st.st_mtime))
    return os.path.join(THUMBS, name.replace("/", "_"))


def make_thumb(path):
    out = thumb_path(path)
    if os.path.isfile(out):
        return out
    os.makedirs(THUMBS, exist_ok=True)
    tmp = out + ".tmp.png"
    r = subprocess.run(["magick", "-define", "jpeg:size=960x540", path,
                        "-resize", "480x270^", "-gravity", "center", "-extent", "480x270", tmp],
                       capture_output=True, timeout=60)
    if r.returncode != 0:
        return None
    os.replace(tmp, out)
    return out


def hexrgb(color):
    c = color.lstrip("#")
    return tuple(int(c[i:i + 2], 16) / 255 for i in (0, 2, 4))


class Picker(Gtk.Window):
    def __init__(self):
        super().__init__()
        self.pal = popup_theme.palette()
        self.folder = FOLDER
        self.items = wallpapers(self.folder)
        cur = current()
        self.index = next((i for i, p in enumerate(self.items) if p == cur), 0)
        self.tiles = [{"path": p, "pix": None, "w": float(NORM_W), "h": float(NORM_H),
                       "dim": DIM, "x": 0.0} for p in self.items]
        if self.tiles:
            t = self.tiles[self.index]
            t["w"], t["h"], t["dim"] = float(SEL_W), float(SEL_H), 1.0
        self.offset = None
        self.anim_id = None

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-wallpapers")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        # Нижняя XP-панель «вплотную» выступает над своей зоной — не накрывать её
        # (01.10.2026: при открытом Super+W низ панели прятался под выбором обоев).
        GtkLayerShell.set_margin(self, GtkLayerShell.Edge.BOTTOM, popup_theme.bottom_overlap())
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        self.set_app_paintable(True)
        visual = self.get_screen().get_rgba_visual()
        if visual:
            self.set_visual(visual)

        self.apply_css()
        self.add(self.build())
        self.connect("key-press-event", self.on_key)
        self.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.SCROLL_MASK)
        self.connect("scroll-event", self.on_scroll)
        threading.Thread(target=self.load_thumbs, daemon=True).start()

    # ── оформление ────────────────────────────────────────────────────────
    def apply_css(self):
        p = self.pal
        css = ("""
        window { background-color: %(veil)s; }
        .name {
            color: %(on_surface)s; font-size: 13px; letter-spacing: 1px;
            font-family: 'JetBrainsMono Nerd Font', 'Noto Sans', sans-serif;
        }
        """ % dict(p, veil=popup_theme.rgba(p["surface"], 0.72))).encode()
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    def build(self):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=22)
        outer.set_valign(Gtk.Align.CENTER)

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_size_request(-1, SEL_H + 90)
        self.canvas.connect("draw", self.draw)
        self.canvas.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.canvas.connect("button-press-event", self.on_click)
        outer.pack_start(self.canvas, True, True, 0)

        self.title = Gtk.Label(label="")
        self.title.get_style_context().add_class("name")
        outer.pack_start(self.title, False, False, 0)
        self.update_title()
        return outer

    # ── лента ─────────────────────────────────────────────────────────────
    def layout(self):
        x = 0.0
        for t in self.tiles:
            t["x"] = x
            x += t["w"] + GAP

    def target_offset(self, width):
        t = self.tiles[self.index]
        return width / 2 - (t["x"] + t["w"] / 2)

    def draw(self, area, cr):
        if not self.tiles:
            return False
        w = area.get_allocated_width()
        h = area.get_allocated_height()
        self.layout()
        if self.offset is None:
            self.offset = self.target_offset(w)
        cr.translate(self.offset, 0)
        order = [i for i in range(len(self.tiles)) if i != self.index] + [self.index]
        for i in order:
            self.draw_tile(cr, i, h)
        return False

    def tile_path(self, cr, t, h):
        """Параллелограмм: верх сдвинут вправо, низ на месте (эскиз пользователя)."""
        x, tw, th = t["x"], t["w"], t["h"]
        top, bottom = (h - th) / 2, (h + th) / 2
        k = SKEW * (th / SEL_H)
        cr.move_to(x + k, top)
        cr.line_to(x + tw + k, top)
        cr.line_to(x + tw, bottom)
        cr.line_to(x, bottom)
        cr.close_path()

    def draw_tile(self, cr, i, h):
        t = self.tiles[i]
        cr.save()
        self.tile_path(cr, t, h)
        cr.save()
        cr.clip()
        pix = t["pix"]
        if pix is None:
            cr.set_source_rgba(*hexrgb(self.pal["surface_container"]), 0.85)
            cr.paint()
        else:
            tw, th = t["w"], t["h"]
            k = SKEW * (th / SEL_H)
            scale = max((tw + k) / pix.get_width(), th / pix.get_height())
            cr.translate(t["x"] - (pix.get_width() * scale - tw - k) / 2,
                         (h - th) / 2 - (pix.get_height() * scale - th) / 2)
            cr.scale(scale, scale)
            Gdk.cairo_set_source_pixbuf(cr, pix, 0, 0)
            cr.paint_with_alpha(t["dim"])
        cr.restore()
        self.tile_path(cr, t, h)
        if i == self.index:
            cr.set_source_rgba(*hexrgb(self.pal["primary"]), 0.95)
            cr.set_line_width(2.5)
        else:
            cr.set_source_rgba(*hexrgb(self.pal["on_surface"]), 0.25)
            cr.set_line_width(1.2)
        cr.stroke()
        cr.restore()

    # ── миниатюры ─────────────────────────────────────────────────────────
    def load_thumbs(self):
        for i in sorted(range(len(self.tiles)), key=lambda k: abs(k - self.index)):
            out = None
            try:
                out = make_thumb(self.tiles[i]["path"])
            except (OSError, subprocess.SubprocessError):
                pass
            if out:
                GLib.idle_add(self.set_thumb, i, out)

    def set_thumb(self, i, file):
        try:
            self.tiles[i]["pix"] = GdkPixbuf.Pixbuf.new_from_file(file)
        except GLib.Error:
            return False
        self.canvas.queue_draw()
        return False

    # ── переход ───────────────────────────────────────────────────────────
    def animate(self):
        if self.anim_id is None:
            self.anim_id = GLib.timeout_add(ANIM_MS, self.tick)

    def tick(self):
        moving = False
        for i, t in enumerate(self.tiles):
            tw, th = (SEL_W, SEL_H) if i == self.index else (NORM_W, NORM_H)
            td = 1.0 if i == self.index else DIM
            if abs(t["w"] - tw) > 0.4 or abs(t["dim"] - td) > 0.005:
                t["w"] += (tw - t["w"]) * EASE
                t["h"] += (th - t["h"]) * EASE
                t["dim"] += (td - t["dim"]) * EASE
                moving = True
            else:
                t["w"], t["h"], t["dim"] = float(tw), float(th), td
        self.layout()
        target = self.target_offset(self.canvas.get_allocated_width())
        if self.offset is None:
            self.offset = target
        elif abs(self.offset - target) > 0.4:
            self.offset += (target - self.offset) * EASE
            moving = True
        else:
            self.offset = target
        self.canvas.queue_draw()
        if moving:
            return True
        self.anim_id = None
        return False

    # ── выбор ─────────────────────────────────────────────────────────────
    def update_title(self):
        folder = os.path.basename(self.folder.rstrip("/")) or self.folder
        if not self.items:
            self.title.set_text("%s — пусто" % folder)
            return
        name = os.path.splitext(os.path.basename(self.items[self.index]))[0]
        self.title.set_text("%s · %s" % (folder, name))

    def move(self, delta):
        if not self.items:
            return
        i = max(0, min(len(self.items) - 1, self.index + delta))
        if i == self.index:
            return
        self.index = i
        self.update_title()
        self.animate()

    def choose(self):
        if not self.items:
            return
        subprocess.Popen(["waypaper", "--wallpaper", self.items[self.index]],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        self.close()

    def hit(self, x, y):
        """Какой кадр под точкой — с учётом наклона граней."""
        h = self.canvas.get_allocated_height()
        for i in reversed(range(len(self.tiles))):
            t = self.tiles[i]
            th = t["h"]
            top, bottom = (h - th) / 2, (h + th) / 2
            if not (top <= y <= bottom):
                continue
            k = SKEW * (th / SEL_H)
            left = self.offset + t["x"] + k * (bottom - y) / max(1.0, th)
            if left <= x <= left + t["w"]:
                return i
        return None

    def on_click(self, _w, event):
        i = self.hit(event.x, event.y)
        if i is None:
            self.close()
        elif i == self.index:
            self.choose()
        else:
            self.move(i - self.index)
        return True

    def on_scroll(self, _w, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.move(-1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.move(1)
        else:
            ok, dx, dy = event.get_scroll_deltas()
            if ok and (dx or dy):
                self.move(1 if (dx + dy) > 0 else -1)
        return True

    def pick_folder(self):
        """Диалог выбора папки.

        Ленту на это время прячем целиком: она лежит слоем OVERLAY во весь
        экран и забирает себе и клавиши, и щелчки — диалог под ней был бы
        недоступен.
        """
        self.hide()
        while Gtk.events_pending():
            Gtk.main_iteration()
        dialog = Gtk.FileChooserDialog(
            title="Папка с обоями", parent=None,
            action=Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL,
                           "Выбрать", Gtk.ResponseType.ACCEPT)
        dialog.set_current_folder(self.folder)
        dialog.set_keep_above(True)
        answer = dialog.run()
        chosen = dialog.get_filename() if answer == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        self.show_all()
        if chosen and chosen != self.folder:
            set_wallpaper_folder(chosen)
            self.load_folder(chosen)

    def load_folder(self, folder):
        """Переложить ленту на другую папку, не закрывая окно."""
        self.folder = folder
        self.items = wallpapers(folder)
        cur = current()
        self.index = next((i for i, p in enumerate(self.items) if p == cur), 0)
        self.tiles = [{"path": p, "pix": None, "w": float(NORM_W), "h": float(NORM_H),
                       "dim": DIM, "x": 0.0} for p in self.items]
        if self.tiles:
            t = self.tiles[self.index]
            t["w"], t["h"], t["dim"] = float(SEL_W), float(SEL_H), 1.0
        self.offset = None
        self.update_title()
        self.canvas.queue_draw()
        threading.Thread(target=self.load_thumbs, daemon=True).start()

    def on_key(self, _w, event):
        key = Gdk.keyval_name(event.keyval)
        if key in CLOSE_KEYS:
            self.close()
        elif key in LEFT_KEYS:
            self.move(-1)
        elif key in RIGHT_KEYS:
            self.move(1)
        elif key == "Home":
            self.move(-self.index)
        elif key == "End":
            self.move(len(self.items) - 1 - self.index)
        elif key in FOLDER_KEYS:
            self.pick_folder()
        elif key in ("Return", "KP_Enter", "space"):
            self.choose()
        return True

    def close(self):
        Gtk.main_quit()


def main():
    Picker().show_all()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
