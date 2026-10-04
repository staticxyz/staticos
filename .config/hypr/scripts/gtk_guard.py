#!/usr/bin/env python3
"""Сторож GTK-файлов от kded6/gtkconfig.

Кто ломал. Модуль gtkconfig демона kded6 при каждом своём запуске «применяет»
цветовую схему KDE к GTK. kded6 стартует не с сессией, а по требованию через
D-Bus — например, когда открывается KDE-приложение или диалог. Замерено
10.09.2026 в 14:46:54: kded6 поднялся, и в ту же секунду были переписаны
gtk-3.0/colors.css, gtk-3.0/gtk.css и gtk-4.0/colors.css. Два следствия:

  * gtk-3.0/colors.css становится голым дампом Breeze — пропадают наши три
    слоя и мостик имён (см. gtk_live_colors.py), и строка меню во всех
    GTK3-приложениях замирает на старом цвете;
  * в КОНЕЦ gtk-4.0/gtk.css дописывается `@import 'colors.css';` — после
    matugen.css, так что дамп Breeze перекрывает свежие цвета matugen.

25.09.2026 выяснилось, что тем же заходом он переписывает и ШРИФТ: в 13:07:35
kded6 поднялся (в журнале видно), и gtk-3.0/settings.ini стал
«gtk-font-name=Noto Sans,  10», а в gsettings легли font-name «Noto Sans  10»
и monospace-font-name «Hack  10» — значения из настроек KDE. Mousepad берёт
системный моноширинный (use-default-monospace-font=true) и потому перестал
показывать шрифт системы (просьба: «а чё у меня блокнот перестал показывать
сис. шрифт»). Поэтому сторож возвращает и шрифт — из выбора в Настройках.
Туда же попадает тема курсора (breeze_cursors вместо пиксельной Jarvis-Cursor):
рука над ссылками в GTK-программах стала гладкой — сторож возвращает и её.

Что делает сторож. Убирает этот голый импорт из gtk-4.0/gtk.css (правильный
импорт colors.css там уже есть — первым, через url(file://...)) и
пересобирает gtk-3.0/colors.css через gtk_live_colors.py. Запускается юнитом
systemd gtk-guard.path, когда меняется любой из двух файлов. Всё идемпотентно:
если чинить нечего, ничего не пишется, так что собственная запись сторожа
его же повторно не зацикливает.
"""
import os
import re
import subprocess
import sys

GTK4 = os.path.expanduser("~/.config/gtk-4.0/gtk.css")
LIVE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gtk_live_colors.py")
# Только голая форма, которую дописывает gtkconfig. Наш импорт
# url("file:///.../colors.css") под неё не подходит.
BARE = re.compile(r"""^\s*@import\s+['"]colors\.css['"]\s*;\s*$""")


def fix_gtk4():
    # Если файл — симлинк, это другая беда (nwg-look подменяет его ссылкой на
    # системную тему, см. шапку gtk-4.0/gtk.css). Чинить её тут значило бы
    # переписать чужой файл темы — не трогаем, это ловит theme-doctor.
    if os.path.islink(GTK4):
        return False
    try:
        with open(GTK4, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return False
    keep = [l for l in lines if not BARE.match(l)]
    if keep == lines:
        return False
    tmp = GTK4 + ".new"
    with open(tmp, "w", encoding="utf-8") as f:
        f.writelines(keep)
    os.replace(tmp, GTK4)
    return True


def fix_fonts():
    """Вернуть шрифт системы, если kded6 подменил его своим.

    Источник истины — выбор в Настройках → Шрифты (app_fonts), а не текущее
    значение в gsettings: именно его kded6 и затирает.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    try:
        import app_fonts
    except ImportError:
        return False
    font = app_fonts.get("system")
    family, size = (app_fonts.UI_FONT_DEFAULT if font == "default"
                    else (font, app_fonts.UI_SIZE.get(font, app_fonts.UI_SIZE_DEFAULT)))
    want = "%s %d" % (family, size)
    try:
        now = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "font-name"],
                             capture_output=True, text=True).stdout.strip().strip("'")
        mono = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "monospace-font-name"],
                              capture_output=True, text=True).stdout.strip().strip("'")
    except OSError:
        return False
    # Сравниваем по семейству: kded6 пишет «Noto Sans  10» с двойным пробелом,
    # точное равенство строк здесь ничего не говорит.
    if now.startswith(family) and mono.startswith(family):
        return False
    app_fonts.apply_ui_font(family, size)
    print("шрифт системы возвращён: %s (было «%s» / «%s»)" % (want, now, mono))
    return True


def fix_cursor():
    """Вернуть пиксельный курсор, если kded6 подменил тему на breeze_cursors.

    25.09.2026: рука над ссылками в баре стала гладкой. В нашей теме Jarvis-Cursor
    рука есть (pointer, hand1, hand2), но GTK-программы — waybar в их числе —
    берут тему из gtk settings.ini / gsettings / xsettingsd.conf, а kded6
    тем же заходом, что шрифт, записал туда breeze_cursors. Стрелка при этом
    оставалась пиксельной: её рисует niri по своему include, который kded6 не трогает.

    Источник истины — имя из ~/.cache/matugen/niri-cursor.kdl (его пишет
    cursor_colors.py и чередует A/B). Публикацию делаем его же функцией.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, here)
    try:
        import cursor_colors as cc
    except ImportError:
        return False
    name = cc.current_name()
    if not name:
        return False                       # пиксельный курсор выключен — не вмешиваемся
    try:
        size = int(re.search(r"xcursor-size\s+(\d+)", cc.NIRI_INC.read_text()).group(1))
    except (OSError, AttributeError, ValueError):
        size = 32
    now = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "cursor-theme"],
                         capture_output=True, text=True).stdout.strip().strip("'")
    xs = os.path.expanduser("~/.config/xsettingsd/xsettingsd.conf")
    try:
        xs_text = open(xs, encoding="utf-8").read()
    except OSError:
        xs_text = ""
    ini_ok = all(("gtk-cursor-theme-name=%s" % name) in open(str(f), encoding="utf-8").read()
                 for f in cc.GTK_INI if os.path.exists(str(f)))
    xs_ok = (not xs_text) or ('Gtk/CursorThemeName "%s"' % name) in xs_text
    if now == name and ini_ok and xs_ok:
        return False
    cc.activate(name, size)                # gsettings, settings.ini, .gtkrc-2.0, index.theme
    if xs_text:
        new = re.sub(r'Gtk/CursorThemeName\s+"[^"]*"', 'Gtk/CursorThemeName "%s"' % name, xs_text)
        new = re.sub(r"Gtk/CursorThemeSize\s+\d+", "Gtk/CursorThemeSize %d" % size, new)
        if new != xs_text:
            with open(xs, "w", encoding="utf-8") as f:
                f.write(new)
            subprocess.run(["pkill", "-HUP", "-x", "xsettingsd"], capture_output=True)
    print("курсор возвращён: %s %d (было «%s»)" % (name, size, now))
    return True


def main():
    if fix_gtk4():
        print("gtk-4.0/gtk.css: убран дописанный kded6 импорт colors.css")
    fix_fonts()
    fix_cursor()
    return subprocess.run([sys.executable, LIVE]).returncode


if __name__ == "__main__":
    sys.exit(main())
