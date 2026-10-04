#!/usr/bin/env python3
"""Шрифт в окне Яндекс Музыки.                                    23.09.2026

    ym_font.py [имя шрифта]        применить (по умолчанию — шрифт системы)
    ym_font.py --wait [шрифт]      дождаться запуска плеера и применить
    ym_font.py --off               убрать, вернуть родной

Почему не через fontconfig. Приложение — это Electron с веб-плеером внутри,
а «YS Text» приходит к нему с сервера по @font-face. Шрифт из файла всегда
главнее подстановки fontconfig, поэтому правило системы до него не достаёт.

Зато приложение запущено с --remote-debugging-port=9223 (так собран пакет
yandex-music), и в окно можно влить свой CSS по протоколу DevTools. Стиль
переопределяет переменные, которыми плеер задаёт шрифт (--ym-font-family-*,
--g-font-family-*), а не `* { font-family }`: последнее сломало бы значки,
которые рисуются шрифтом.

Стиль ставится дважды: сразу в открытую страницу и через
Page.addScriptToEvaluateOnNewDocument — тогда он возвращается сам при каждой
загрузке документа внутри плеера, а не слетает при первом же переходе.
Пережить перезапуск приложения так нельзя (сеанс отладки умирает вместе с
ним), поэтому запуск идёт через ym_launch.sh: он поднимает плеер и вызывает
этот скрипт с --wait. Вызывается ещё и из app_fonts.py при смене шрифта.

Своего клиента WebSocket пришлось написать: в системе нет ни websockets,
ни websocket-client, ни websocat, а тянуть зависимость ради одного вызова
незачем. Кадр здесь всегда один и короткий, поэтому хватает простейшего.
"""
import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
import urllib.request

PORT = 9223
STYLE_ID = "jarvis-font"


def targets():
    with urllib.request.urlopen("http://127.0.0.1:%d/json" % PORT, timeout=3) as r:
        return json.load(r)


def page_ws():
    for t in targets():
        if t.get("type") == "page" and "Музык" in (t.get("title") or ""):
            return t["webSocketDebuggerUrl"]
    for t in targets():
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    return None


def ws_call(url, payload):
    return ws_calls(url, [payload])[-1]


def ws_calls(url, payloads):
    """Несколько команд по одному соединению: рукопожатие, кадры туда, ответы обратно.

    Одним соединением, потому что Page.addScriptToEvaluateOnNewDocument
    действует только там, где перед ним включён домен Page, — разорви связь
    между двумя вызовами, и регистрация пропадёт вместе с сеансом.
    """
    rest = url.split("://", 1)[1]
    hostport, _, path = rest.partition("/")
    host, _, port = hostport.partition(":")
    key = base64.b64encode(os.urandom(16)).decode()
    s = socket.create_connection((host, int(port or 80)), timeout=5)
    s.sendall(("GET /%s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\n"
               "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\n"
               "Sec-WebSocket-Version: 13\r\n\r\n" % (path, hostport, key)).encode())
    head = b""
    while b"\r\n\r\n" not in head:
        chunk = s.recv(4096)
        if not chunk:
            raise RuntimeError("соединение закрыто на рукопожатии")
        head += chunk
    if b"101" not in head.split(b"\r\n", 1)[0]:
        raise RuntimeError("отладочный порт не принял подключение")

    for payload in payloads:
        data = json.dumps(payload).encode()
        mask = os.urandom(4)
        frame = bytearray([0x81])
        n = len(data)
        if n < 126:
            frame.append(0x80 | n)
        elif n < (1 << 16):
            frame.append(0x80 | 126); frame += struct.pack(">H", n)
        else:
            frame.append(0x80 | 127); frame += struct.pack(">Q", n)
        frame += mask
        frame += bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        s.sendall(bytes(frame))

    want = {p["id"] for p in payloads}
    got = {}
    buf = head.split(b"\r\n\r\n", 1)[1]
    while want - set(got):
        while len(buf) < 2:
            buf += s.recv(4096)
        length = buf[1] & 0x7F
        off = 2
        if length == 126:
            while len(buf) < 4:
                buf += s.recv(4096)
            length = struct.unpack(">H", buf[2:4])[0]; off = 4
        elif length == 127:
            while len(buf) < 10:
                buf += s.recv(4096)
            length = struct.unpack(">Q", buf[2:10])[0]; off = 10
        while len(buf) < off + length:
            buf += s.recv(4096)
        msg = buf[off:off + length]
        buf = buf[off + length:]
        try:
            ans = json.loads(msg)
        except ValueError:
            continue
        if ans.get("id") in want:
            got[ans["id"]] = ans
    s.close()
    return [got[p["id"]] for p in payloads]


def css(font):
    """Стиль, который ставится в окно плеера.

    Путь выбран после трёх проб (23.09.2026). Не сработали: подмена
    переменных (--ym-font-family-* и прочие — часть элементов пишет
    font-family напрямую); переобъявление семейства «YS Text» через
    @font-face с src: local(...); то же самое, добавленное скриптом через
    document.fonts. Во всех случаях плеер продолжал рисовать своим
    начертанием — ширина пробной строки не менялась.

    Поэтому правило по площади. Обычно так делать нельзя — сломаются значки,
    нарисованные шрифтом, — но здесь значки векторные: в document.fonts у
    плеера только текстовые семейства (YS Text, YS Text Variable, YSMusic
    Headline), а на странице 82 элемента <svg>. Они и их содержимое из
    правила исключены явно, на случай будущих шрифтовых значков.
    """
    fam = '"%s"' % font
    return ("*:not(svg):not(svg *){font-family:%s!important;}"
            ":root,body{--ym-font-family-text:%s!important;"
            "--ym-font-family-display:%s!important;--g-font-family-sans:%s!important;}"
            % (fam, fam, fam, fam))


def system_font():
    here = os.path.dirname(os.path.abspath(__file__))
    try:
        out = subprocess.run(["python3", os.path.join(here, "app_fonts.py"), "get", "system"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    return "" if out in ("", "default") else out


def main():
    args = sys.argv[1:]
    wait = False
    if args and args[0] == "--wait":
        wait = True
        args = args[1:]
    off = args == ["--off"]
    font = "" if off else (args[0] if args else system_font())
    if not off and not font:
        print("ym_font: шрифт системы не выбран («Как было») — нечего применять")
        return 0
    # --wait: плеер только запускается, порт отладки поднимается не сразу.
    # 60 попыток по секунде — с запасом на холодный старт.
    url = None
    for attempt in range(60 if wait else 1):
        try:
            url = page_ws()
        except OSError:
            url = None
        if url:
            break
        if wait:
            time.sleep(1)
    if not url:
        print("ym_font: плеер не отвечает на порту %d" % PORT, file=sys.stderr)
        return 1
    # Стиль ставится дважды. Обычный <style> в head — для переменных. И тот же
    # текст отдельной «конструируемой» таблицей (adoptedStyleSheets): плеер
    # объявляет свои шрифты именно так, а такие таблицы применяются ПОСЛЕ
    # обычных — из head переопределить @font-face не выходило (проверено
    # 23.09.2026: ширина пробы «YS Text» не менялась).
    rc = apply(url, font, off)
    if wait and rc == 0 and not off:
        keep(lambda: apply(page_ws(), font), STYLE_ID)
    return rc


def apply(url, font, off=False):
    """Влить стиль в страницу url. 0 — вышло, 1 — нет."""
    body = "" if off else css(font)
    js = ("(() => { const id = %s, css = %s;"
          " let el = document.getElementById(id);"
          " if (!el) { el = document.createElement('style'); el.id = id;"
          "   document.head.appendChild(el); }"
          " el.textContent = css;"
          " const rest = document.adoptedStyleSheets.filter(s => !s.__jarvisFont);"
          " if (css) { const sheet = new CSSStyleSheet(); sheet.__jarvisFont = true;"
          "   sheet.replaceSync(css); document.adoptedStyleSheets = [...rest, sheet]; }"
          " else { document.adoptedStyleSheets = rest; }"
          " return css.length; })()"
          % (json.dumps(STYLE_ID), json.dumps(body)))
    # Первая команда красит открытую страницу, вторая — все будущие: плеер
    # переходит между разделами, и без неё стиль слетал бы на первом переходе.
    calls = [{"id": 1, "method": "Runtime.evaluate",
              "params": {"expression": js, "returnByValue": True}},
             {"id": 2, "method": "Page.enable"},
             {"id": 3, "method": "Page.removeScriptToEvaluateOnNewDocument",
              "params": {"identifier": "1"}}]
    if not off:
        calls.append({"id": 4, "method": "Page.addScriptToEvaluateOnNewDocument",
                      "params": {"source": "document.addEventListener('DOMContentLoaded', () => { %s });" % js}})
    answers = ws_calls(url, calls)
    ans = answers[0]
    res = ans.get("result", {}).get("result", {})
    if res.get("type") == "number":
        print("ym_font: %s" % ("родной шрифт возвращён" if off else "применён %s" % font))
        return 0
    print("ym_font: не вышло — %s" % json.dumps(ans)[:200], file=sys.stderr)
    return 1



def present(url, element_id):
    """Есть ли в странице элемент с таким id (наш <style>)."""
    ans = ws_calls(url, [{"id": 1, "method": "Runtime.evaluate",
                          "params": {"expression": "!!document.getElementById(%s)" % json.dumps(element_id),
                                     "returnByValue": True}}])
    return ((ans[0].get("result") or {}).get("result") or {}).get("value") is True


def keep(reapply, element_id, seconds=60, every=2):
    """После запуска следить, что стиль на месте, и ставить заново, если нет.

    Сразу после старта плеер ещё меняет страницу: первая, что откликается по
    порту, — заставка, и стиль, влитый в неё, пропадал вместе с ней (28.09.2026:
    после запуска не было ни шрифта, ни размера текста, ни скрытой плашки).
    """
    end = time.time() + seconds
    while time.time() < end:
        time.sleep(every)
        try:
            url = page_ws()
            if url and not present(url, element_id):
                reapply()
        except (OSError, ValueError):
            pass


if __name__ == "__main__":
    sys.exit(main())
