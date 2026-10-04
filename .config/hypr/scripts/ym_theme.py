#!/usr/bin/env python3
"""Палитра обоев в открытую Яндекс Музыку — без перезапуска (17.09.2026).

    ym_theme.py          положить ~/.cache/matugen/yandex.css в страницу приложения

При загрузке окна CSS вставляет хук в app.asar (см. шапку templates/yandex.css),
но только один раз — на dom-ready. После смены обоев этот скрипт (его зовёт
theme_changer.sh) кладёт свежий CSS в страницу <style id="jarvis-matugen"> через
порт отладки 9223, тот же, что у кнопки «Нравится» (player_like.py). Приложение
не открыто или открыто без порта — тихо выходим, при следующем запуске хук
подхватит новый файл сам.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import player_like  # noqa: E402  (ws_eval, ym_page)

CSS = os.path.expanduser("~/.cache/matugen/yandex.css")


def main():
    try:
        with open(CSS, encoding="utf-8") as f:
            css = f.read()
    except OSError:
        return 0
    expr = ("(()=>{let s=document.getElementById('jarvis-matugen');"
            "if(!s){s=document.createElement('style');s.id='jarvis-matugen';document.head.appendChild(s);}"
            "s.textContent=%s;return getComputedStyle(document.body)"
            ".getPropertyValue('--ym-controls-color-primary-default-enabled').trim();})()" % json.dumps(css))
    try:
        url = player_like.ym_page()
        accent = player_like.ws_eval(url, expr) if url else None
    except (OSError, ValueError):
        return 0
    if accent:
        print("Яндекс Музыка: акцент %s" % accent)
    return 0


if __name__ == "__main__":
    sys.exit(main())
