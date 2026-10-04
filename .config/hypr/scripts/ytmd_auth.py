#!/usr/bin/env python3
"""Выдать доступ к YouTube Music Desktop App (Companion server) — один раз.

    ytmd_auth.py

Перед запуском в приложении: Settings → Integrations → Companion server = вкл и
«Enable companion authorization» = вкл (окно на 5 минут). Скрипт просит код,
приложение показывает окно с этим кодом — подтвердить. Ключ пишется в
~/.config/hypr/state/ytmd-token (права 600); им пользуется player_like.py.
17.09.2026.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "http://127.0.0.1:9863/api/v1"
TOKEN = os.path.expanduser("~/.config/hypr/state/ytmd-token")
APP = {"appId": "jarvisdesktop", "appName": "Jarvis Desktop", "appVersion": "1.0.0"}


def post(path, body, timeout):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def main():
    try:
        code = post("/auth/requestcode", APP, 10)["code"]
    except urllib.error.HTTPError as e:
        print("приложение отказало в коде: %s %s" % (e.code, e.read().decode(errors="replace")[:200]))
        return 1
    except OSError as e:
        print("Companion server не отвечает: %s" % e)
        return 1
    print("Код: %s — подтвердите его в окне YouTube Music (жду до 60 с)" % code, flush=True)
    try:
        token = post("/auth/request", dict(APP, code=code), 65)["token"]
    except urllib.error.HTTPError as e:
        print("доступ не выдан: %s %s" % (e.code, e.read().decode(errors="replace")[:200]))
        return 1
    except OSError as e:
        print("не дождался подтверждения: %s" % e)
        return 1
    os.makedirs(os.path.dirname(TOKEN), exist_ok=True)
    fd = os.open(TOKEN, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(token)
    print("доступ выдан, ключ сохранён")
    return 0


if __name__ == "__main__":
    sys.exit(main())
