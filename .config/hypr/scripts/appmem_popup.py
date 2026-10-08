#!/usr/bin/env python3
"""Окно «кто сколько ест»: то же, что команда appmem, но на рабочем столе.

    appmem_popup.py             открыть (второй вызов — закрыть), бинд SUPER+ALT+X
    appmem_popup.py place […]   где показывать окно (выбор — в Настройках → Окна)

Считает не сам: берёт функции из ~/.local/bin/appmem (PSS вместо суммы RSS —
иначе общая память браузера считается по многу раз). Процессорная доля — по
разнице двух снимков, поэтому в терминале команда и ждёт полторы секунды.
Здесь ждать не нужно: окно держит прошлый снимок и обновляет цифры каждые
две секунды на месте — живой счётчик (просьба пользователя 25.09.2026).
"""
import importlib.machinery
import importlib.util
import glob
import os
import sys
import time

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

APPMEM = os.path.expanduser("~/.local/bin/appmem")
PLACE_NAME = "appmem"      # ~/.config/hypr/state/appmem-place
REFRESH_MS = 2000
ROWS = 10
CHROME_H = 150             # шапка, линия, итог, кнопка, поля карточки — сверх списка


def list_max_height():
    """Предел высоты раскрытого списка: вся карточка — не больше половины
    свободной высоты экрана (без верхнего бара и нижней панели). Тогда плашка
    снизу и плашка сверху не перекрывают друг друга,
    даже если программ много; что не влезло — прокручивается (01.10.2026)."""
    try:
        import json
        import subprocess
        out = json.loads(subprocess.run(["niri", "msg", "-j", "focused-output"],
                                        capture_output=True, text=True, timeout=1).stdout)
        screen_h = out["logical"]["height"]
    except Exception:
        screen_h = 1080
    free = screen_h - popup_theme.bar_edge() - popup_theme.bar_height() - 32
    return max(200, free // 2 - CHROME_H)


def appmem():
    """Подгрузить сам appmem: файл без расширения, обычным import не берётся."""
    loader = importlib.machinery.SourceFileLoader("appmem", APPMEM)
    spec = importlib.util.spec_from_loader("appmem", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class MemPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Память приложений")
        self.pal = popup_theme.palette()
        self.mem = appmem()
        self.prev = self.mem.scan()
        self.prev_at = time.time()
        self.first = True     # в первом кадре дельты ещё нет — CPU показывать нечем

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        self.apply_css()

        bg = Gtk.EventBox()
        bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(bg)
        align = Gtk.Box()
        popup_theme.place_side(align, popup_theme.place_get(PLACE_NAME))
        bg.add(align)
        card = Gtk.EventBox()
        card.connect("button-press-event", lambda w, e: True)
        align.add(card)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        box.get_style_context().add_class("card")
        card.add(box)

        self.head = self.label("", "head")
        self.load = self.label("", "subtitle")
        box.pack_start(self.head, False, False, 0)
        box.pack_start(self.load, False, False, 0)
        box.pack_start(self.rule(), False, False, 0)

        # Таблица собирается заново на каждом обновлении: строк то 10, то все.
        self.expanded = False
        self.grid = Gtk.Grid(column_spacing=10, row_spacing=1)
        self.grid.set_hexpand(True)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_propagate_natural_height(True)
        self.max_h = list_max_height()
        self.scroll.set_max_content_height(self.max_h)
        # полоса прокрутки видна всегда: иначе обрезанная строка выглядит поломкой
        self.scroll.set_overlay_scrolling(False)
        self.scroll.add(self.grid)
        box.pack_start(self.scroll, False, False, 0)
        self.total_lab = self.label("", "total")
        self.total_lab.set_no_show_all(True)
        box.pack_start(self.total_lab, False, False, 0)
        # Кнопка «все» (01.10.2026): по умолчанию — только 10 самых прожорливых;
        # по кнопке — все, с итогом «занято = программы + остальное».
        self.more = Gtk.Button(label="▾ all")
        self.more.get_style_context().add_class("more")
        self.more.set_halign(Gtk.Align.END)
        self.more.connect("clicked", self.toggle_all)
        box.pack_start(self.more, False, False, 0)

        self.refresh()
        GLib.timeout_add(REFRESH_MS, self.refresh)

    def toggle_all(self, _b):
        self.expanded = not self.expanded
        self.more.set_label("▴ top %d" % ROWS if self.expanded else "▾ all")
        self.refresh(force=True)

    def label(self, text="", css=None):
        lab = Gtk.Label(label=text)
        lab.set_xalign(0.0)
        if css:
            lab.get_style_context().add_class(css)
        return lab

    def rule(self):
        line = Gtk.Box()
        line.get_style_context().add_class("rule")
        return line

    # ── данные ────────────────────────────────────────────────────────────
    @staticmethod
    def zram_kb():
        """Сколько RAM занимает сжатый своп zram (mm_stat, 3-е поле), КиБ."""
        total = 0
        for path in glob.glob("/sys/block/zram*/mm_stat"):
            try:
                total += int(open(path).read().split()[2])
            except (OSError, ValueError, IndexError):
                pass
        return total // 1024

    @staticmethod
    def tmpfs_kb():
        """Файлы в памяти: занятое на tmpfs (/tmp, /dev/shm, /run…), КиБ."""
        total, seen = 0, set()
        try:
            mounts = open("/proc/self/mounts").read().splitlines()
        except OSError:
            return 0
        for line in mounts:
            parts = line.split()
            if len(parts) < 3 or parts[2] != "tmpfs" or parts[1] in seen:
                continue
            seen.add(parts[1])
            try:
                st = os.statvfs(parts[1])
                total += (st.f_blocks - st.f_bfree) * st.f_frsize
            except OSError:
                pass
        return total // 1024

    def refresh(self, *_a, force=False):
        import collections
        now = self.mem.scan()
        dt = max(0.2, time.time() - self.prev_at)
        by_mem, by_cpu, count = collections.Counter(), collections.Counter(), collections.Counter()
        for pid, p in now.items():
            was = self.prev.get(pid)
            group = self.mem.label_of(p, now)
            kb, _exact = self.mem.pss_kb(pid)
            by_mem[group] += kb
            by_cpu[group] += (p["cpu"] - was["cpu"]) / dt * 100 if was else 0.0
            count[group] += 1
        if not force:
            self.prev, self.prev_at = now, time.time()
        apps_kb = sum(by_mem.values())

        info = self.mem.meminfo()
        total = info["MemTotal"] / 1048576.0
        avail = info["MemAvailable"] / 1048576.0
        swap = (info["SwapTotal"] - info["SwapFree"]) / 1048576.0
        self.head.set_text("Память %.1f / %.1f ГиБ · available %.1f" % (total - avail, total, avail))
        self.load.set_text("%d ядер · загрузка %s · swap %.1f ГиБ"
                           % (os.cpu_count(), open("/proc/loadavg").read().split()[0], swap))

        # zram — как ещё одно «приложение»: сжатый своп живёт в RAM, и без него
        # сумма строк не сходилась с «занято» (01.10.2026).
        special = {"zram": self.zram_kb()}
        used_kb = info["MemTotal"] - info["MemAvailable"]
        if self.expanded:
            special["tmpfs"] = self.tmpfs_kb()
            special["kernel"] = sum(info.get(k, 0) for k in ("SUnreclaim", "KernelStack",
                                                            "PageTables", "VmallocUsed", "Percpu"))
            special["other"] = max(0, used_kb - apps_kb - sum(special.values()))
        for k, v in special.items():
            by_mem[k] += v
        rows = by_mem.most_common(None if self.expanded else ROWS)
        rows = [(n, kb) for n, kb in rows if kb >= 1024 or n in special]

        for child in self.grid.get_children():
            self.grid.remove(child)
        for col, (title, right) in enumerate((("application", False), ("mem", True),
                                              ("CPU", True), ("proc", True))):
            lab = self.label(title, "col")
            lab.set_xalign(1.0 if right else 0.0)
            # колонка названий тянется — таблица во всю ширину карточки, без
            # пустоты справа под шапкой (01.10.2026)
            lab.set_hexpand(col == 0)
            self.grid.attach(lab, col, 0, 1, 1)
        for i, (name, kb) in enumerate(rows):
            sp = name in special
            cpu = by_cpu[name]
            cells = (name[:20], "%.0f МиБ" % (kb / 1024.0),
                     "—" if (self.first or sp) else "%.1f%%" % cpu,
                     "—" if sp else str(count[name]))
            for col, text in enumerate(cells):
                lab = self.label(text, "cell" if col == 0 else "num")
                lab.set_xalign(0.0 if col == 0 else 1.0)
                if col == 2 and not sp and not self.first:
                    if cpu >= 50:
                        lab.get_style_context().add_class("hot")
                    elif cpu >= 20:
                        lab.get_style_context().add_class("warm")
                self.grid.attach(lab, col, i + 1, 1, 1)
        self.grid.show_all()
        # Высота прокрутки — по самому списку, но не выше предела: подсказку
        # «естественной высоты» ScrolledWindow с видимой полосой не держит.
        nat = self.grid.get_preferred_height()[1]
        self.scroll.set_min_content_height(min(nat, self.max_h))

        if self.expanded:
            rest = used_kb - apps_kb
            self.total_lab.set_text("итого занято %.1f ГиБ  =  программы %.1f + остальное %.1f"
                                    % (used_kb / 1048576.0, apps_kb / 1048576.0, rest / 1048576.0))
            self.total_lab.show()
        else:
            self.total_lab.hide()
        self.first = False
        return True

    # ── оформление ────────────────────────────────────────────────────────
    def apply_css(self):
        p = dict(self.pal)
        p["hairline"] = popup_theme.rgba(self.pal["on_surface_variant"], 0.20)
        css = ("""
        window { background-color: transparent; }
        .card {
            background-color: %(surface)s; color: %(on_surface)s;
            font-family: 'JetBrainsMono Nerd Font', sans-serif; font-size: 12px;
            border: 3px solid %(primary)s; border-radius: 18px;
            padding: 10px 11px 8px 11px;
            margin: 2px; box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.60);
        }
        /* Размеры — крупнее обычного (01.10.2026). Строки и шапка 16 px, подписи 12 px.
           05.10.2026: подписи тоже 16 — 12 px у пиксельного шрифта мылится. */
        .head { font-size: 16px; color: %(on_surface)s; }
        .subtitle { font-size: 12px; color: %(on_surface_variant)s; }
        .col { font-size: 12px; color: %(on_surface_variant)s; }
        .cell { font-size: 16px; color: %(on_surface)s; }
        .num { font-size: 16px; color: %(primary)s; }
        .num.warm { color: %(tertiary)s; }
        .num.hot { color: %(error)s; }
        .rule { background-color: %(hairline)s; min-height: 1px; margin: 7px 2px; }
        scrollbar { background: transparent; border: none; margin-left: 6px; }
        scrollbar slider { background-color: alpha(%(primary)s, 0.55); border-radius: 3px;
                           min-width: 5px; border: none; }
        scrollbar slider:hover { background-color: %(primary)s; }
        scrollbar trough { background-color: alpha(%(on_surface)s, 0.08); border-radius: 3px; }
        .total { font-size: 12px; color: %(on_surface)s; margin-top: 5px; }
        button.more {
            background: transparent; background-image: none; border: none; box-shadow: none;
            padding: 0 2px; margin: 3px 0 0 0; min-height: 0; min-width: 0;
            font-family: 'JetBrainsMono Nerd Font', sans-serif; font-size: 12px;
            color: %(on_surface_variant)s;
        }
        button.more:hover { color: %(primary)s; }
        """ % p)
        css = popup_theme.scale_css(css).encode()   # Cozette: поля ×13/16, кегль 13/26

        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


def main():
    args = sys.argv[1:]
    if args and args[0] == "place":
        rest = args[1:]
        if not rest:
            print(popup_theme.place_get(PLACE_NAME))
        elif rest[0] == "list":
            for key, title in popup_theme.PLACES:
                print("%s\t%s" % (key, title))
        else:
            print(popup_theme.place_set(PLACE_NAME, rest[0]))
        return

    # Переключатель окна — только когда его и правда открывают: с командой
    # «place» этот же файл зовут Настройки, и открытое окно закрываться не должно.
    popup_theme.single_instance(__file__)
    win = MemPopup()
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
