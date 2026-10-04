#!/usr/bin/env python3
import sys, os, subprocess, gi, pulsectl


gi.require_version('Gtk', '3.0')
gi.require_version('GtkLayerShell', '0.1')
from gi.repository import Gtk, Gdk, GtkLayerShell
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402
# Второй щелчок по модулю закрывает открытый попап. Раньше здесь были
# `pgrep -f` и `kill -9` по всему найденному — см. popup_theme.single_instance.
popup_theme.single_instance(__file__)

# Имя потока — общий разбор для всех мест: см. audio_names.py.
from audio_names import stream_name  # noqa: E402,F401


class VolumePopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Микшер")

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.TOP, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.BOTTOM, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.LEFT, True)
        GtkLayerShell.set_anchor(self, GtkLayerShell.Edge.RIGHT, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        # Гамма и каркас CSS — общие для попапов бара, см. popup_theme.py.
        # Ручка шкалы — tertiary, а не secondary: в scheme-fidelity secondary
        # обычно совпадает с primary, и ручка сливалась бы с заполнением.
        css = popup_theme.css(
            popup_theme.SCALE_CSS + """
        /* Компактнее (30.09.2026, просьба: «слишком крупно»): пиксельный шрифт
           12 px (он чёткий на 12/16/24), тонкая шкала, маленькая ручка. */
        .popup-box { font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
                     font-size: 12px; padding: 12px 18px 22px 18px; }
        label { font-weight: normal; font-size: 12px; }
        label.section { color: %(on_surface_variant)s; }
        scale { padding: 0; margin: 0; min-height: 0; }
        scale value { font-size: 12px; min-width: 28px; margin-left: 8px; }
        scale trough { min-height: 5px; }
        scale slider { min-width: 11px; min-height: 11px; margin: -4px; }
        separator { margin: 2px 0; }
        """,
            accent="primary", knob="tertiary")
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        self.align = Gtk.Box()
        # Прямо под баром и серединой под точкой щелчка — общая логика всех
        # попапов бара, см. popup_theme.place_under_cursor. Раньше здесь были
        # отступ 34 сверху (слой и так начинается под панелью, так что попап
        # висел на полосу ниже) и жёсткий отступ от правого края.
        popup_theme.place_under_cursor(self.align)
        self.bg.add(self.align)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=9)
        vbox.get_style_context().add_class("popup-box")
        vbox.set_size_request(300, -1)
        self.popup_event.add(vbox)

        self.pulse = pulsectl.Pulse('gtk-volume-mixer')

        # Общая громкость
        try:
            srv = self.pulse.server_info()
            default_sink = next((s for s in self.pulse.sink_list() if s.name == srv.default_sink_name), self.pulse.sink_list()[0])
            self.build_slider(vbox, "󰕾  Общая громкость", [default_sink.index], default_sink.volume.value_flat, True)
        except Exception:
            pass

        # Фильтрация потоков: системные звуки, Blanket и приостановленные.
        # Corked — это открытый, но не играющий поток: так gnome-clocks держит
        # канал для звука будильника, и он висел в списке как "Clocks" со своим
        # ползунком, хотя звука не издаёт. Проверка общая, а не по имени, так
        # что любое другое приложение с таким же поведением тоже не засорит
        # список (Blanket сюда же попадает на паузе).
        def is_active(inp):
            if inp.proplist.get('media.role') == 'event':
                return False
            if str(inp.proplist.get('pulse.corked', '')).lower() == 'true':
                return False
            fields = ('application.name', 'application.process.binary', 'media.name')
            # служебные петли (module-loopback записи экрана и т. п.) — не программы
            if 'loopback' in str(inp.proplist.get('media.name', '')).lower() \
                    or 'loopback' in str(inp.proplist.get('node.name', '')).lower():
                return False
            return not any('blanket' in str(inp.proplist.get(f, '')).lower()
                           for f in fields)

        inputs = [inp for inp in self.pulse.sink_input_list() if is_active(inp)]

        # Одна строка на программу, а не на поток (23.09.2026). Яндекс Музыка при
        # игре держала четыре потока разом, и в списке стояли четыре одинаковых
        # «Yandexmusic». Теперь ползунок программы двигает все её потоки вместе,
        # а показывает самый громкий из них.
        groups = {}
        for inp in inputs:
            groups.setdefault(stream_name(inp.proplist), []).append(inp)

        if groups:
            vbox.pack_start(Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL), False, False, 0)
            sec = Gtk.Label(label="Активные источники", xalign=0)
            sec.get_style_context().add_class("section")
            vbox.pack_start(sec, False, False, 0)
            for app_name, streams in groups.items():
                media_name = streams[0].proplist.get('media.name', '')
                if (len(streams) == 1 and media_name
                        and media_name not in ["AudioStream", "Playback Stream", "Playback", "ALSA Playback"]):
                    # значок — нота, а не «лиса» Firefox: он стоял у любого одиночного
                    # потока, и Zen подписывался Firefox-ом (01.10.2026)
                    disp = f"󰎈  {app_name}: {media_name}"
                else:
                    disp = f"󰎈  {app_name}"
                vol = max(inp.volume.value_flat for inp in streams)
                self.build_slider(vbox, disp, [inp.index for inp in streams], vol, False)

        self.connect("key-press-event", lambda w, e: sys.exit(0))

    def build_slider(self, box, title, obj_ids, current_vol, is_sink):
        hbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 150, 1)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_value(round(current_vol * 100))
        scale.connect("value-changed", self.on_volume_changed, obj_ids, is_sink)
        lab = Gtk.Label(label=title, xalign=0)
        # Длинное имя не растягивает окно: ширина постоянная, хвост — «…»
        lab.set_ellipsize(3)
        lab.set_max_width_chars(30)
        lab.set_tooltip_text(title)
        hbox.pack_start(lab, False, False, 0)
        hbox.pack_start(scale, False, False, 0)
        box.pack_start(hbox, False, False, 0)

    def on_volume_changed(self, scale, obj_ids, is_sink):
        vol = scale.get_value() / 100.0
        for obj_idx in obj_ids:
            # Поток мог закончиться, пока попап открыт — остальные всё равно двигаем
            try:
                target = self.pulse.sink_info(obj_idx) if is_sink else self.pulse.sink_input_info(obj_idx)
                self.pulse.volume_set_all_chans(target, vol)
            except Exception:
                pass

if __name__ == "__main__":
    win = VolumePopup()
    win.show_all()
    Gtk.main()
