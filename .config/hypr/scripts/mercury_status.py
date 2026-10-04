#!/usr/bin/env python3
"""Модуль waybar: значок Mercury, пока браузер запущен.

Сама картинка приходит не отсюда, а из CSS (background-image в style.css):
waybar рисует в модуле текст, а не изображения. Поэтому здесь выдаётся пара
пробелов — место, на котором CSS и рисует иконку. Когда браузер закрыт,
текст пустой, и waybar прячет модуль целиком.

Ищем окно, а не процесс: mercury оставляет фоновые процессы после закрытия
последнего окна, и по pgrep значок висел бы в панели впустую.
"""
import json
import subprocess

CLASS = "mercury"


def main():
    try:
        out = subprocess.run(["hyprctl", "clients", "-j"],
                             capture_output=True, text=True, timeout=3).stdout
        clients = json.loads(out)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        print(json.dumps({"text": ""}))
        return

    wins = [c for c in clients
            if CLASS in str(c.get("initialClass", "")).lower()]
    if not wins:
        print(json.dumps({"text": ""}))
        return

    titles = "\n".join(w["title"][:60] for w in wins[:6])
    print(json.dumps({
        "text": "  ",
        "class": "running",
        "tooltip": "Mercury — окон: %d\n%s" % (len(wins), titles),
    }))


if __name__ == "__main__":
    main()
