#!/usr/bin/env python3
"""Калькулятор и переводчик SUPER+C — своё окно вместо rofi-calc (23.09.2026).

Зачем. rofi-calc показывает ответ в однострочном поле сообщения и берёт из
вывода одну строку: длинный перевод обрезался, а растянуть поле вниз нельзя
ничем («покажи мне 2 строки, не одну» — пользователь). Здесь и ввод, и ответ
переносятся по строкам, окно растёт по тексту.

Считает то же, что и раньше: calc_qalc.py (qalc с валютами по-русски, живой
перевод NLLB) вызывается на каждый ввод с теми же аргументами, что давал
rofi-calc, — поведение один в один. Enter — calc_copy.sh: число в буфер, а
текст — перевод (уточнённый своим translate_refine.sh, если он есть), после
чего окно закрывается. Esc — закрыть. Повторное SUPER+C закрывает окно
(popup_theme.single_instance).

Вид — как у панели rofi: 520 px, стекло на 85 %, рамка @outline, строка
ввода на @surface_high; цвета из палитры обоев (popup_theme.palette).
Это слой (layer-shell) поверх окон с именем jarvis-calc — размытие под ним
даёт layer-rule niri, как у rofi.
"""
import os
import subprocess
import sys
import threading

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CALC = os.path.join(HERE, "calc_qalc.py")
COPY = os.path.join(HERE, "calc_copy.sh")
WIDTH = 520
DEBOUNCE_MS = 120
ICON_CALC = "\U000f00ec"       # nf-md-calculator
ICON_TRANSLATE = "\U000f05ca"  # nf-md-translate


def compute(text):
    """(ответ, это перевод?) — тот же calc_qalc.py, что звал rofi-calc."""
    env = dict(os.environ, CALC_RAW="1")
    r = subprocess.run([sys.executable, CALC, "-u8", "-set", "update_exchange_rates 1days", text],
                       capture_output=True, text=True, env=env, timeout=20)
    out = r.stdout.rstrip("\n")
    if out.startswith(ICON_TRANSLATE):
        return out[len(ICON_TRANSLATE):].strip(), True
    return out.strip(), False


class Popup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Калькулятор")
        self.set_decorated(False)
        self.set_resizable(False)              # окно всегда по содержимому
        self.set_default_size(WIDTH, -1)
        # Слой поверх окон (layer-shell), как у rofi, а не обычное окно: размер
        # плавающего окна niri фиксирует при открытии, и ответ, появившийся
        # ниже, не помещался — «не вижу результат» (23.09.2026). Слой
        # растёт сам; без якорей — по центру; размытие под ним — layer-rule
        # niri по имени jarvis-calc, как у rofi.
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_namespace(self, "jarvis-calc")
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.serial = 0
        self.timer = None
        self.final = None                      # None — нет; False — ждём уточнение; True — показан
        self.build()
        self.apply_css()
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)

    def build(self):
        self.panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.panel.get_style_context().add_class("panel")
        self.panel.set_size_request(WIDTH, -1)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        row.get_style_context().add_class("inputbar")
        icon = Gtk.Label(label=ICON_CALC)
        icon.get_style_context().add_class("prompt")
        icon.set_valign(Gtk.Align.START)
        self.entry = Gtk.TextView()
        self.entry.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.entry.set_accepts_tab(False)
        self.entry.get_style_context().add_class("entry")
        self.entry.set_hexpand(True)
        self.entry.get_buffer().connect("changed", self.on_changed)
        row.pack_start(icon, False, False, 0)
        row.pack_start(self.entry, True, True, 0)
        self.panel.pack_start(row, False, False, 0)

        res = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        res.get_style_context().add_class("result")
        self.res_icon = Gtk.Label(label=ICON_CALC)
        self.res_icon.get_style_context().add_class("result-icon")
        self.res_icon.set_valign(Gtk.Align.START)
        self.answer = Gtk.Label(label="")
        self.answer.set_line_wrap(True)
        self.answer.set_line_wrap_mode(2)     # Pango.WrapMode.WORD_CHAR
        self.answer.set_xalign(0.0)
        self.answer.set_max_width_chars(38)
        self.answer.set_hexpand(True)
        self.answer.get_style_context().add_class("answer")
        res.pack_start(self.res_icon, False, False, 0)
        res.pack_start(self.answer, True, True, 0)
        self.result_row = res
        self.panel.pack_start(res, False, False, 0)
        res.set_no_show_all(True)              # пока нечего показывать
        self.add(self.panel)

    def apply_css(self):
        p = popup_theme.palette()
        css = """
        window { background-color: transparent; }
        .panel {
            background-color: %(glass)s; border: 1px solid %(outline)s;
            border-radius: 12px; padding: 12px;
        }
        .inputbar { background-color: %(bar)s; border-radius: 10px; padding: 10px 14px; }
        .prompt { color: %(primary)s; }
        textview.entry, textview.entry text { background-color: transparent; color: %(on_surface)s; caret-color: %(primary)s; }
        .result { padding: 4px 14px 2px 14px; }
        .result-icon { color: %(on_surface_variant)s; }
        .answer { color: %(on_surface)s; }
        """ % dict(p, glass=popup_theme.rgba(p["surface"], 0.85), bar=p["surface_high"],
                   outline=p["outline_variant"])
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

    # ── ввод ────────────────────────────────────────────────────────────
    def text(self):
        b = self.entry.get_buffer()
        return b.get_text(b.get_start_iter(), b.get_end_iter(), True)

    def on_changed(self, _buf):
        self.final = None
        if self.timer:
            GLib.source_remove(self.timer)
        self.timer = GLib.timeout_add(DEBOUNCE_MS, self.recalc)

    def recalc(self):
        self.timer = None
        text = self.text().strip()
        self.serial += 1
        serial = self.serial
        if not text:
            self.show_answer("", False)
            return False
        threading.Thread(target=self.worker, args=(text, serial), daemon=True).start()
        return False

    def worker(self, text, serial):
        try:
            answer, is_translation = compute(text)
        except Exception as e:                  # noqa: BLE001 — ответ важнее причины
            answer, is_translation = "ошибка: %s" % e, False
        GLib.idle_add(self.deliver, serial, answer, is_translation)

    def deliver(self, serial, answer, is_translation):
        if serial == self.serial:
            self.show_answer(answer, is_translation)
        return False

    def show_answer(self, answer, is_translation):
        if answer.strip():
            self.res_icon.set_text(ICON_TRANSLATE if is_translation else ICON_CALC)
            self.answer.set_text(answer)
            self.result_row.set_no_show_all(False)
            self.result_row.show_all()
        else:
            self.result_row.hide()
        self.resize(WIDTH, 1)                  # ужаться, если текста стало меньше

    # ── клавиши ─────────────────────────────────────────────────────────
    def on_key(self, _w, ev):
        key = ev.keyval
        if key == Gdk.KEY_Escape:
            self.close()
            return True
        if key in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not ev.state & Gdk.ModifierType.SHIFT_MASK:
            self.accept()
            return True
        return False

    def accept(self):
        """Enter. Число — в буфер и закрыть. Текст — перевод прямо
        здесь: строка «Перевожу…», потом сам перевод (он же в буфере); окно
        остаётся, чтобы его прочитать, — второй Enter или Esc закрывают
        («после Enter тупо копируется, я даже не вижу, что перевёл» — пользователь)."""
        if self.timer:                          # ответ ещё не досчитан — досчитать сейчас
            GLib.source_remove(self.timer)
            self.timer = None
            text = self.text().strip()
            if text:
                try:
                    answer, is_tr = compute(text)
                    self.show_answer(answer, is_tr)
                except Exception:
                    pass
        if getattr(self, "final", None) is not None:   # перевод уже показан — закрыть
            self.close()
            return
        if self.res_icon.get_text() == ICON_TRANSLATE and self.answer.get_text():
            draft = self.answer.get_text()
            req = os.path.expanduser("~/.cache/calc_qalc.translate")
            try:
                import json
                with open(req) as f:
                    d = json.load(f)
            except (OSError, ValueError):
                d = None
            self.answer.set_text(draft + "\n\nУточняю перевод…")
            self.final = False
            threading.Thread(target=self.best_worker, args=(d, draft), daemon=True).start()
            return
        subprocess.Popen([COPY], start_new_session=True)
        self.close()

    def best_worker(self, req, draft):
        best = None
        refine = os.path.join(HERE, "translate_refine.sh")   # необязательный, свой
        if req and os.access(refine, os.X_OK):
            try:
                r = subprocess.run([refine, req["text"], req["src"], req["tgt"]],
                                   capture_output=True, text=True, timeout=40)
                best = r.stdout.strip() if r.returncode == 0 else None
            except (OSError, subprocess.SubprocessError):
                best = None
        GLib.idle_add(self.show_best, best, draft)

    def show_best(self, best, draft):
        text = best or draft
        try:
            subprocess.run(["wl-copy"], input=text, text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            pass
        self.answer.set_text(text + "\n\n— скопировано")
        self.final = True
        return False


def main():
    popup_theme.single_instance(__file__)
    GLib.set_prgname("jarvis-calc")            # app-id для правила niri
    win = Popup()
    win.show_all()
    win.entry.grab_focus()
    if len(sys.argv) > 1:                      # начальный текст (и для проверок без рук)
        win.entry.get_buffer().set_text(" ".join(sys.argv[1:]))
    if os.environ.get("CALC_PROBE"):           # проверка без рук: размер через 3 с
        def probe():
            a = win.get_allocation()
            print("размер слоя: %dx%d, ответ: %r" % (a.width, a.height, win.answer.get_text()), flush=True)
            if os.environ["CALC_PROBE"] == "enter" and win.final is None:
                win.accept()
                GLib.timeout_add(12000, probe)
                return
            Gtk.main_quit()
        GLib.timeout_add(3000, probe)
    Gtk.main()


if __name__ == "__main__":
    main()
