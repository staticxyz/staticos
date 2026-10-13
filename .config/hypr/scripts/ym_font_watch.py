#!/usr/bin/env python3
"""Сторож шрифта Яндекс Музыки: ловит (пере)запуск плеера и вливает шрифт. 12.10.2026.

Работает внутри staticos_host.py, цикл бесконечный.
Порт 9223 — отладка Electron; появился → плеер (пере)запустился → вызываем ym_font.py.
"""
import json
import os
import subprocess
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 9223
POLL = 10


def port_alive():
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=2) as r:
            data = json.load(r)
            return bool(data)
    except Exception:
        return False


was_alive = False
while True:
    alive = port_alive()
    if alive and not was_alive:
        time.sleep(3)
        subprocess.run(
            ["python3", os.path.join(HERE, "ym_font.py")],
            capture_output=True, timeout=30)
    was_alive = alive
    time.sleep(POLL)
