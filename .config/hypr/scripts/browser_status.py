#!/usr/bin/env python3
"""Модуль waybar: значок браузера, пока он запущен.

Вызов:  browser_status.py <класс окна> [подпись]

Общий на все браузеры — раньше под Mercury лежал отдельный скрипт, и на
каждый следующий браузер пришлось бы плодить копии.

Отдаёт одноцветный глиф браузера — тот же, что у него в списке столов
(window-rewrite в config.jsonc); цвет задаёт style.css из палитры обоев.
Раньше здесь были пробелы, на которых CSS рисовал цветной логотип-картинку,
и он выбивался из гаммы. Когда браузер закрыт, текст пустой, и waybar прячет
модуль целиком.

Ищем ОКНО, а не процесс: браузеры оставляют фоновые процессы после закрытия
последнего окна, и по pgrep значок висел бы в панели впустую. Список окон
берём через wm.py — он одинаково отвечает в Hyprland и в Niri.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402

# Глифы — те же, что у этих браузеров в window-rewrite: U+E100 из
# собственного шрифта WolfGlyph (LibreWolf), U+F269 из Nerd Font (Mercury).
# Zen — U+E101 из шрифта ZenGlyph (scripts/build_zen_font.py, 15.09.2026).
GLYPHS = {"librewolf": "\ue100", "mercury": "\uf269", "zen": "\ue101"}


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"text": ""}))
        return
    want = sys.argv[1].lower()
    label = sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]

    wins = wm.find(app=want)
    if not wins:
        print(json.dumps({"text": ""}))
        return

    titles = "\n".join(w["title"][:60] for w in wins[:6])
    print(json.dumps({
        "text": GLYPHS.get(want, "\uf0ac"),
        "class": "running",
        "tooltip": "%s — окон: %d\n%s" % (label, len(wins), titles),
    }))


if __name__ == "__main__":
    main()
