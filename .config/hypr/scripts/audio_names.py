#!/usr/bin/env python3
"""Человеческое имя звукового потока — одно на все места, где оно показывается.

application.name недостаточно: Telegram не ставит его вовсе (поток назывался
общим словом «Система»), а любое приложение на Electron представляется
«Chromium» — Яндекс Музыка так и значилась Chromium в плашке громкости
(замечено пользователем 25.09.2026, хотя в попапе микшера имя было правильным:
там этот разбор уже был, и теперь он общий).

Правило: общее имя перебивается именем исполняемого файла, а node.name идёт
в ход, когда application.name нет совсем.
"""

GENERIC = {"chromium", "electron", "chrome", "google-chrome"}


def stream_name(props):
    app = (props.get("application.name") or "").strip()
    binary = (props.get("application.process.binary") or "").strip()
    node = (props.get("node.name") or "").strip()

    if app and app.lower() not in GENERIC:
        return app
    if binary and binary.lower() not in GENERIC:
        # yandexmusic -> Yandexmusic; имена вроде YouTube Music не ломаем
        return binary if binary[:1].isupper() else binary.capitalize()
    return app or node or "Система"
