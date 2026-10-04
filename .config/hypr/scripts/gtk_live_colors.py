#!/usr/bin/env python3
"""Отдаёт палитру обоев уже запущенным приложениям GTK3.

ЗАЧЕМ. gtk.css с @import matugen.css читается ровно один раз, при старте
приложения: замерено на скрытом пробнике — ни touch, ни перезапись gtk.css,
ни смена gtk-theme-name через gsettings не заставляют GTK3 перечитать
пользовательский CSS. Поэтому блокнот, запущенный до смены обоев, оставался
в старых цветах до перезапуска, а строка `touch gtk.css` в theme_changer не
делала ничего.

КАК. В сессии загружен colorreload-gtk-module (kde-gtk-config, прописан в
gtk-modules в settings.ini, то есть его берёт каждое приложение GTK3). Модуль
держит GFileMonitor на ~/.config/gtk-3.0/colors.css и на изменение файла
заново цепляет его провайдером к экрану — поверх пользовательского gtk.css.
Значит, чтобы перекрасить живые окна, палитру надо класть в colors.css.

ВАЖНО — ПОДМЕНА, А НЕ ЗАПИСЬ. Замерено: перезапись colors.css на месте модуль
не замечает совсем (15 с ожидания, цвет не дрогнул), а подмена через rename
срабатывает меньше чем за полсекунды. Отсюда os.replace, а не открытие файла
на запись.

СОСТАВ ФАЙЛА — три слоя, в CSS побеждает последнее определение:

  1. нетронутый дамп Breeze (colors-breeze-base.css) — только как запасной
     набор имён, значения в нём от тех обоев, при которых nwg-look его снял;
  2. палитра matugen — перекрывает 70 из 84 имён дампа;
  3. мостик BRIDGE ниже — 14 имён, которых matugen не генерирует вовсе.

Третий слой появился не для красоты. Breeze красит строку меню правилом
`menubar { background-color: @theme_header_background_breeze; }`, а этого
имени у matugen нет — значит оно оставалось из дампа и держало цвет старых
обоев. Ровно это и было видно в блокноте: вкладки и поле текста уже #101418
из свежей палитры, а полоса меню — #181210 из дампа, и перезапуск приложения
не помогал, потому что читался тот же залежавшийся файл.
"""
import os
import re
import sys

GTK3 = os.path.expanduser("~/.config/gtk-3.0")
BASE = os.path.join(GTK3, "colors-breeze-base.css")
MATUGEN = os.path.join(GTK3, "matugen.css")
TARGET = os.path.join(GTK3, "colors.css")

HEADER = """/* Собран gtk_live_colors.py — руками не править.
 * base: colors-breeze-base.css, поверх — matugen.css текущих обоев,
 * поверх — мостик для имён, которых matugen не генерирует.
 * Файл существует ради colorreload-gtk-module: он следит именно за ним и
 * перекрашивает уже открытые окна GTK3 без перезапуска.
 */
"""

# Имя Breeze -> имя из палитры matugen, на которое оно ссылается.
# Ссылка через @имя, а не готовый цвет: значение подставляется на месте
# использования, поэтому мостик не надо пересобирать при смене ролей.
# Каждая цель проверяется перед записью — опечатка в имени превратилась бы
# в невидимую поломку темы, а не в ошибку.
BRIDGE = {
    # Строка меню и заголовки окон. Специально @theme_bg_color, а не
    # @headerbar_bg_color: у matugen headerbar на ступень светлее фона
    # (surface_container), и полоса меню стала бы отдельной светлой лентой.
    # В прежнем дампе Breeze она совпадала с фоном окна — сохраняем это,
    # меняется только сама палитра.
    "theme_header_background_breeze": "theme_bg_color",
    "theme_header_background_light_breeze": "theme_bg_color",
    "theme_header_background_backdrop_breeze": "theme_unfocused_bg_color",
    "theme_header_foreground_breeze": "theme_fg_color",
    "theme_header_foreground_backdrop_breeze": "theme_unfocused_fg_color",
    "theme_header_foreground_insensitive_breeze": "insensitive_fg_color_breeze",
    "theme_header_foreground_insensitive_backdrop_breeze":
        "insensitive_unfocused_fg_color_breeze",
    # Кнопки: matugen даёт базовые состояния, но не сочетания
    # «неактивное + под фокусом другого окна» — берём ближайшее базовое.
    "theme_button_decoration_focus_insensitive_breeze":
        "theme_button_decoration_focus_breeze",
    "theme_button_decoration_focus_backdrop_insensitive_breeze":
        "theme_button_decoration_focus_backdrop_breeze",
    "theme_button_decoration_hover_insensitive_breeze":
        "theme_button_decoration_hover_breeze",
    "theme_button_decoration_hover_backdrop_insensitive_breeze":
        "theme_button_decoration_hover_backdrop_breeze",
    "theme_button_foreground_active_backdrop_breeze":
        "theme_button_foreground_active_breeze",
    "theme_button_foreground_active_backdrop_insensitive_breeze":
        "theme_button_foreground_active_insensitive_breeze",
    "theme_button_foreground_backdrop_insensitive_breeze":
        "theme_button_foreground_insensitive_breeze",
}


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def main():
    base = read(BASE)
    mat = read(MATUGEN)
    if mat is None:
        print("gtk_live_colors: нет matugen.css, нечего применять", file=sys.stderr)
        return 1
    if base is None:
        # База не обязательна: без неё пропадут только 14 имён Breeze, а
        # молча оборвать обновление палитры хуже.
        print("gtk_live_colors: нет colors-breeze-base.css, ставлю одну matugen",
              file=sys.stderr)
        base = ""

    defined = set(re.findall(r"@define-color\s+([A-Za-z0-9_]+)", mat))
    bridge, missing = [], []
    for name, target in BRIDGE.items():
        if target in defined:
            bridge.append("@define-color %s @%s;" % (name, target))
        else:
            missing.append("%s -> %s" % (name, target))
    if missing:
        # Молчать нельзя: строка меню уже один раз тихо застряла на цвете
        # старых обоев именно потому, что имя было никем не определено.
        print("gtk_live_colors: нет цели у мостика: " + ", ".join(missing),
              file=sys.stderr)

    out = (HEADER
           + base.rstrip("\n") + "\n\n"
           + mat.rstrip("\n") + "\n\n"
           + "/* Мостик: имена Breeze, которых matugen не генерирует. */\n"
           + "\n".join(bridge) + "\n")

    if read(TARGET) == out:
        # Тот же текст — подменять нечего: лишний rename заставил бы каждое
        # окно GTK3 без нужды пересобрать стили.
        return 0

    tmp = TARGET + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(out)
    os.replace(tmp, TARGET)      # именно rename — см. шапку
    return 0


if __name__ == "__main__":
    sys.exit(main())
