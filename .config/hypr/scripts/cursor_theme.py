#!/usr/bin/env python3
"""Выбор курсора (28.09.2026): Jarvis в цветах обоев, «галька» Jarvis Pebble, Breeze.

    cursor_theme.py                 какой выбран
    cursor_theme.py list            что можно выбрать
    cursor_theme.py set <ключ>      включить (jarvis | pebble-wall | Jarvis-Pebble-Blue | … | breeze_cursors)
    cursor_theme.py refresh         после смены обоев — пересобрать курсор, если он от них зависит

Выбор хранится в ~/.config/hypr/state/cursor-theme. Пока выбран Jarvis, курсор, как
и раньше, пересобирается под обои (cursor_colors.py из theme_changer.sh); при любом
другом выборе cursor_colors.py его не трогает. Включается тема тем же путём, что и
Jarvis: include niri, gsettings, settings.ini GTK, .gtkrc-2.0 и index.theme XWayland
(cursor_colors.activate). Страница «Настройки» → «Курсор» вызывает этот же скрипт.
"""
import os
import pathlib
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import cursor_colors  # noqa: E402

STATE = pathlib.Path.home() / ".config/hypr/state/cursor-theme"
JARVIS = "jarvis"
# ключ, подпись, xcursor-size
THEMES = [
    (JARVIS, "Jarvis · цвета обоев", cursor_colors.SIZE),
    ("bit-wall", "Jarvis Bit · цвета обоев", cursor_colors.SIZE),   # свой пиксельный, bit_cursor.py (07.10.2026)
    ("pebble-wall", "Галька · цвета обоев", 32),
    # Гальки синий/тёмно-синий/голубой/чёрный и Yamikai розовый убраны 07.10.2026 (Пользователь:
    # «убери все, что не берут из акцента») — файлы тем в ~/.local/share/icons остались.
    # Пиксельные курсоры из поиска 30.09.2026 (~/.local/share/icons, ссылки в ~/.icons
    # для Steam). Размер — родной или кратный: там они чёткие.
    # Retrosmart-Win убран из списка 02.10.2026: почти не отличается от Chicago95, а
    # Пользователь попросил оставить одну из двух (выбрана у него Chicago95, и набор у неё
    # полнее). Файлы темы лежат в ~/.local/share/icons — вернуть строку, если понадобится.
    ("Retrosmart-Mac", "Retrosmart · классический Mac", 32),
    ("Chicago95", "Chicago95 · Windows 95", 32),
    ("Pixel-MacOS", "Pixel MacOS · чёрно-белый", 24),
    # Пиксельные из AUR (07.10.2026, пользователь поставил на пробу): xcursor-hackneyed-light/-dark,
    # xcursor-pixelfun-all, xcursor-openzone — в /usr/share/icons. Размеры — родные.
    # Оставлены только PixelFun 3 и Eclipse (остальные отвергнуты); у них нет имени default —
    # исправленные копии в ~/.local/share/icons (ссылки default→left_ptr и др.).
    ("pixelfun3", "PixelFun 3", 32),
    ("pixelfun3-eclipse", "PixelFun 3 · Eclipse", 32),
    ("yamikai-wall", "Yamikai · цвета обоев", cursor_colors.SIZE),
    ("breeze_cursors", "Breeze", 24),
]


def current():
    try:
        key = STATE.read_text().strip()
    except OSError:
        return JARVIS
    return key if any(k == key for k, _, _ in THEMES) else JARVIS


WALL = "pebble-wall"
YAMIKAI_WALL = "yamikai-wall"   # yamikai_wall.py: размер общий с Jarvis, перекраска по обоям


def theme_dir(key):
    """Каталог темы, откуда брать картинки для предпросмотра."""
    now = cursor_colors.current_name() or ""
    if key == JARVIS:
        name = now if now.startswith("Jarvis-Cursor") else cursor_colors.NAMES[0]
    elif key == WALL:
        name = now if now.startswith("Jarvis-Pebble-Wall") else "Jarvis-Pebble-Wall-A"
    elif key == YAMIKAI_WALL:
        name = now if now.startswith("Yamikai-Wall") else "Yamikai-Wall-A"
    elif key == "bit-wall":
        name = now if now.startswith("Jarvis-Bit") else "Jarvis-Bit-A"
    else:
        name = key
    for base in (pathlib.Path.home() / ".local/share/icons", pathlib.Path("/usr/share/icons")):
        if (base / name / "cursors").is_dir():
            return base / name
    return None


def set_theme(key):
    size = next((s for k, _, s in THEMES if k == key), None)
    if size is None:
        print("нет такого курсора:", key)
        return 1
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(key + "\n")
    if key == JARVIS:
        # Собрать по нынешней палитре и включить — обычный путь cursor_colors.py.
        subprocess.run(["python3", os.path.join(HERE, "cursor_colors.py"), "--on"], check=False)
    elif key == WALL:
        cursor_colors.activate(build_wall(), size)
    elif key == YAMIKAI_WALL:
        import yamikai_wall
        cursor_colors.activate(yamikai_wall.build(cursor_colors.current_name() or ""), size)
    elif key == "bit-wall":
        import bit_cursor
        cursor_colors.activate(bit_cursor.build(cursor_colors.current_name() or ""), size)
    else:
        cursor_colors.activate(key, size)
    print("курсор:", key)
    return 0


def build_wall():
    """Собрать «гальку в цветах обоев» в свободный каталог A/B; вернуть его имя."""
    r = subprocess.run(["python3", os.path.join(HERE, "jarvis_pebble.py"), "wall",
                        cursor_colors.current_name() or ""], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1]


def refresh():
    """После смены обоев (theme_changer.sh): пересобрать то, что зависит от палитры."""
    key = current()
    if key == JARVIS:
        subprocess.run(["python3", os.path.join(HERE, "cursor_colors.py")], check=False)
    elif key == WALL:
        name = build_wall()
        cursor_colors.activate(name, 32)
        print("курсор:", name)
    elif key == "bit-wall":
        import bit_cursor
        name = bit_cursor.build(cursor_colors.current_name() or "")
        cursor_colors.activate(name, cursor_colors.SIZE)
        print("курсор:", name)
    elif key == YAMIKAI_WALL:
        import yamikai_wall
        name = yamikai_wall.build(cursor_colors.current_name() or "")
        cursor_colors.activate(name, cursor_colors.SIZE)
        print("курсор:", name)
    else:
        print("курсор", key, "от обоев не зависит")


def main():
    args = sys.argv[1:]
    if not args:
        print(current())
        return 0
    if args[0] == "refresh":
        refresh()
        return 0
    if args[0] == "list":
        cur = current()
        for k, label, _ in THEMES:
            print("%s %-22s %s" % ("●" if k == cur else " ", k, label))
        return 0
    if args[0] == "set" and len(args) > 1:
        return set_theme(args[1])
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
