#!/usr/bin/env python3
"""«Нравится» для плеера в попапе (player_popup.py), 17.09.2026.

    player_like.py state  ИМЯ_MPRIS   → liked | not | unsupported
    player_like.py toggle ИМЯ_MPRIS   → liked | not | unsupported (после нажатия)
    keep — сервер занят (лимит частоты), кнопку оставить как есть

В MPRIS команды «нравится» нет, поэтому кнопка нажимается в самом плеере:

* Яндекс Музыка (приложение yandexmusic, в MPRIS «chromium.instancePID»).
  Приложение запускается с портом отладки 9223 только на 127.0.0.1 — это
  ~/.local/share/applications/yandexmusic.desktop. Через него выполняется JS в
  окне приложения: кнопка [data-test-id=LIKE_BUTTON] внутри панели плеера
  [data-test-id=PLAYERBAR_DESKTOP], состояние — aria-pressed. Без порта
  (приложение открыто не через этот ярлык) — unsupported.

* YouTube Music и YouTube в Zen (в MPRIS «firefox.instance…»). Порта у Zen
  нет, поэтому мост через файлы: запрос ~/.cache/jarvis-like/request.json
  ({id, action}), ответ youtube.json ({id, state}). Читает и нажимает
  ~/.config/zen-jarvis/live-theme.js (раздел «Нравится»): выбирает вкладку, где
  играет звук, и жмёт лайк только в ней. Ответ приходит за ~0,5–1 с.

* YouTube Music Desktop App (ytmdesktop, процесс youtube-music-d). Через его
  Companion server (127.0.0.1:9863, API v1): состояние — GET /state →
  video.likeStatus (2 — нравится), нажатие — POST /command {"command":
  "toggleLike"}. Ключ — ~/.config/hypr/state/ytmd-token, выдаётся один раз
  скриптом ytmd_auth.py.

Клиент WebSocket здесь свой, на сокетах: в системном Python нет ни
websocket-client, ни websockets, а тянуть пакет ради одной команды не стоит.
"""
import base64
import time
import json
import os
import socket
import struct
import sys
import urllib.error
import urllib.request

YM_PORT = 9223
YM_BUTTON = "[data-test-id=PLAYERBAR_DESKTOP] [data-test-id=LIKE_BUTTON]"


def comm(pid):
    try:
        with open("/proc/%d/comm" % pid) as f:
            return f.read().strip()
    except OSError:
        return ""


def ws_eval(ws_url, expression, timeout=4):
    """Runtime.evaluate через CDP: одно сообщение туда, ответ с тем же id обратно."""
    rest = ws_url.split("://", 1)[1]
    hostport, path = rest.split("/", 1)
    host, port = hostport.split(":")
    s = socket.create_connection((host, int(port)), timeout=timeout)
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)).encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = s.recv(4096)
            if not chunk:
                raise OSError("нет ответа на рукопожатие")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise OSError(head.split(b"\r\n", 1)[0].decode(errors="replace"))
        buf = head.split(b"\r\n\r\n", 1)[1]

        payload = json.dumps({"id": 1, "method": "Runtime.evaluate",
                              "params": {"expression": expression, "awaitPromise": True,
                                         "returnByValue": True}}).encode()
        mask = os.urandom(4)
        n = len(payload)
        hdr = bytes([0x81]) + (bytes([0x80 | n]) if n < 126 else
                               bytes([0x80 | 126]) + struct.pack(">H", n) if n < 65536 else
                               bytes([0x80 | 127]) + struct.pack(">Q", n))
        s.sendall(hdr + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

        def need(k):
            nonlocal buf
            while len(buf) < k:
                chunk = s.recv(65536)
                if not chunk:
                    raise OSError("соединение закрыто")
                buf += chunk

        while True:
            need(2)
            op, ln = buf[0] & 0x0F, buf[1] & 0x7F
            off = 2
            if ln == 126:
                need(4)
                ln, off = struct.unpack(">H", buf[2:4])[0], 4
            elif ln == 127:
                need(10)
                ln, off = struct.unpack(">Q", buf[2:10])[0], 10
            need(off + ln)
            data, buf = buf[off:off + ln], buf[off + ln:]
            if op == 1:
                msg = json.loads(data)
                if msg.get("id") == 1:
                    return msg.get("result", {}).get("result", {}).get("value")
            elif op == 8:
                raise OSError("соединение закрыто")
    finally:
        s.close()


def ym_page():
    with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % YM_PORT, timeout=2) as r:
        pages = json.load(r)
    for p in pages:
        if p.get("type") == "page" and p.get("url", "").startswith("music-application://"):
            return p["webSocketDebuggerUrl"]
    return None


def ym(action):
    js_state = "document.querySelector(%r)" % YM_BUTTON
    if action == "toggle":
        expr = ("(async()=>{const b=%s; if(!b) return null; b.click();"
                " await new Promise(r=>setTimeout(r,450));"
                " return %s.getAttribute('aria-pressed');})()" % (js_state, js_state))
    else:
        expr = "(()=>{const b=%s; return b ? b.getAttribute('aria-pressed') : null;})()" % js_state
    try:
        url = ym_page()
        val = ws_eval(url, expr) if url else None
    except (OSError, ValueError):
        return "unsupported"
    return {"true": "liked", "false": "not"}.get(val, "unsupported")


LIKE_DIR = os.path.expanduser("~/.cache/jarvis-like")
YTMD_API = "http://127.0.0.1:9863/api/v1"
YTMD_TOKEN = os.path.expanduser("~/.config/hypr/state/ytmd-token")


def ytmd(action, instance=""):
    """Лайк в YouTube Music Desktop.

    Сервер пускает запрос состояния не чаще раза в 5 с (иначе 429 «Too Many
    Requests», замер 17.09.2026). Поэтому последнее известное состояние лежит в
    кэше: после нажатия отвечаем перевёрнутым кэшем, не спрашивая сервер, а
    при 429 — кэшем или «keep» (попап оставляет кнопку как есть, не прячет).
    """
    try:
        with open(YTMD_TOKEN) as f:
            token = f.read().strip()
    except OSError:
        return "unsupported"
    cache_path = os.path.join(LIKE_DIR, "ytmd-state.json")
    try:
        with open(cache_path) as f:
            cache = json.load(f)
    except (OSError, ValueError):
        cache = {}

    def save(state, title):
        os.makedirs(LIKE_DIR, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump({"state": state, "title": title, "at": time.time()}, f)

    def call(path, body=None):
        req = urllib.request.Request(YTMD_API + path, method="POST" if body else "GET",
                                     data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": token, "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=3) as r:
            data = r.read()
        return json.loads(data) if data else {}

    if action == "toggle":
        try:
            call("/command", {"command": "toggleLike"})
        except urllib.error.HTTPError as e:
            return "keep" if e.code == 429 else "unsupported"
        except (OSError, ValueError):
            return "unsupported"
        flipped = {"liked": "not", "not": "liked"}.get(cache.get("state"))
        if flipped:
            save(flipped, cache.get("title"))
            return flipped
        return "keep"

    # Кэш годится, только пока играет тот же трек (название из MPRIS).
    import subprocess
    title = subprocess.run(["playerctl", "-p", instance, "metadata", "title"], capture_output=True,
                           text=True, timeout=3).stdout.strip() if instance else None
    same = not title or title == cache.get("title")
    if same and time.time() - cache.get("at", 0) < 5:
        return cache.get("state", "keep")
    try:
        video = call("/state").get("video") or {}
    except urllib.error.HTTPError as e:
        return (cache.get("state", "keep") if same else "keep") if e.code == 429 else "unsupported"
    except (OSError, ValueError):
        return "unsupported"
    state = {2: "liked", 1: "not", 0: "not"}.get(video.get("likeStatus"), "unsupported")
    if state != "unsupported":
        save(state, video.get("title"))
    return state




def zen(action):
    os.makedirs(LIKE_DIR, exist_ok=True)
    rid = "%d-%d" % (time.time_ns(), os.getpid())
    tmp = os.path.join(LIKE_DIR, "request.json.tmp")
    with open(tmp, "w") as f:
        json.dump({"id": rid, "action": action}, f)
    os.replace(tmp, os.path.join(LIKE_DIR, "request.json"))
    deadline = time.time() + 5
    while time.time() < deadline:
        time.sleep(0.1)
        try:
            with open(os.path.join(LIKE_DIR, "youtube.json")) as f:
                res = json.load(f)
        except (OSError, ValueError):
            continue
        if res.get("id") == rid:
            return res.get("state", "unsupported")
    return "unsupported"


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("state", "toggle"):
        print(__doc__, file=sys.stderr)
        return 2
    action, instance = sys.argv[1], sys.argv[2]
    _, _, tail = instance.partition(".instance")
    pid = int(tail) if tail.isdigit() else 0
    if pid and comm(pid) == "yandexmusic":
        print(ym(action))
    elif pid and comm(pid).startswith("youtube-music"):
        print(ytmd(action, instance))
    elif instance.startswith("firefox.instance"):
        print(zen(action))
    else:
        print("unsupported")
    return 0


if __name__ == "__main__":
    sys.exit(main())
