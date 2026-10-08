#!/usr/bin/env python3
"""Кто сейчас качает через роутер — для плашки «Сеть» (08.10.2026).

Входит в админку TP-Link EC225-G5 (192.168.0.1) под пользователем static,
пароль — ~/.config/hypr/state/router-pass (600, пишет router_pass.py), и раз в
POLL секунд печатает строку JSON:
    {"ok": true, "devs": [{"name", "mac", "ip", "type", "up", "down"}, …]}
up/down — байт/с по данным роутера (таблица STARTTABLE, id 13), type:
0 кабель, 1 — 2,4 ГГц, 3 — 5 ГГц, 2/4 — гостевая сеть.
Ошибка — {"ok": false, "why": "…"} и выход.

Живёт, только пока жива плашка: закрылся stdout или пришёл SIGTERM — выходит
из админки (code=11) и завершается.

Протокол прошивки (modules/login/localLogin/models.js, main/main.js):
  POST ?code=2&asyn=1        → 401, строки [3] и [4] — ключ и алфавит токена
  POST ?code=16&asyn=0 "get" → RSA ee/nn и seq
  POST ?code=7&asyn=0&user=static&id=ТОКЕН   — вход (ДО регистрации AES-ключа)
  POST ?code=16&asyn=0&id=ТОКЕН "set <RSA(AES)>"
  POST ?code=2&asyn=1&id=ТОКЕН  — чтение, тело sign=…\\r\\ndata=… (AES)
ОСТОРОЖНО: 10 неверных паролей подряд — роутер закрывает вход на 2 часа.
Поэтому: при счётчике неудач ≥ 3 не входим вовсе, после неудачи — пауза
FAIL_PAUSE (файл FAIL_FILE), повторного входа в цикле нет.

Проверка: router_clients.py --once  (один замер и выход).
"""
import json
import os
import signal
import sys
import time
from collections import defaultdict
from urllib.parse import unquote

import requests
from tplinkrouterc6u.client.c80 import TplinkC80Router as C80
from tplinkrouterc6u.common.encryption import EncryptionWrapper

HOST = "http://192.168.0.1"
USER = "static"
PASS_FILE = os.path.expanduser("~/.config/hypr/state/router-pass")
FAIL_FILE = os.path.expanduser("~/.cache/jarvis-router-fail")
FAIL_PAUSE = 30 * 60
LOCK_FILE = os.path.expanduser("~/.cache/jarvis-router.lock")   # одна сессия на обе плашки
POLL = 3.0

stopping = False


def out(obj):
    try:
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (BrokenPipeError, ValueError):
        raise SystemExit(0)


class Router:
    def __init__(self, pw):
        self.pw = pw
        self.c = C80(HOST, pw, timeout=6)       # только шифрование, сеть — своя
        self.s = requests.Session()
        self.h = {"Referer": HOST + "/"}
        self.logged = False

    def req(self, q, data=None, tok=True):
        url = HOST + "/?" + q + ("&id=" + self.c._encryption.token if tok else "")
        return self.s.post(url, data=data, headers=self.h, timeout=6)

    def login(self):
        x = self.req("code=2&asyn=1", tok=False)
        lines = x.text.splitlines()
        if len(lines) < 5:
            return "роутер ответил не так, как ждали"
        try:
            fails = int(lines[2])
        except ValueError:
            fails = 0
        if fails >= 3:
            return "у роутера уже %d неудачных входов — не рискую блокировкой" % fails
        enc = self.c._encryption
        enc.token = C80._encode_token(C80._encrypt_password(self.pw), x)
        k = self.req("code=16&asyn=0", "get", tok=False).text.splitlines()
        if len(k) < 4:
            return "роутер не отдал ключи шифрования"
        enc.ee_rsa, enc.nn_rsa, enc.seq = k[1], k[2], k[3]
        x = self.req("code=7&asyn=0&user=" + USER)
        if not x.text.startswith("00000"):
            mark_fail()
            return "роутер не принял пароль"
        self.logged = True
        aes = EncryptionWrapper.rsa_encrypt(enc.aes._get_aes_string(), enc.nn_rsa, enc.ee_rsa)
        if not self.req("code=16&asyn=0", "set " + aes).text.startswith("00000"):
            return "роутер не принял ключ шифрования"
        return None

    def devices(self):
        x = self.req("code=2&asyn=1", self.c._encrypt_body("13|1,0,0"))
        text = self.c._decrypt_data(x.text)
        if not text.startswith("00000"):
            return None
        d = defaultdict(dict)
        for ln in text.split("\r\n"):
            p = ln.split(" ", 2)
            if len(p) >= 2 and p[1].isdigit():
                d[int(p[1])][p[0]] = unquote(p[2]) if len(p) == 3 else ""
        devs = []
        for e in d.values():
            if e.get("ip", "0.0.0.0") == "0.0.0.0" or e.get("online") != "1":
                continue
            try:
                up, down = int(e.get("up") or 0), int(e.get("down") or 0)
            except ValueError:
                up = down = 0
            devs.append({"name": e.get("name") or e.get("mac", "?"),
                         "mac": e.get("mac", "").lower(), "ip": e.get("ip"),
                         "type": e.get("type"), "up": up, "down": down})
        return devs

    def logout(self):
        if self.logged:
            self.logged = False
            try:
                self.req("code=11&asyn=0")
            except Exception:
                pass


def mark_fail():
    try:
        os.makedirs(os.path.dirname(FAIL_FILE), exist_ok=True)
        with open(FAIL_FILE, "w") as f:
            f.write(str(int(time.time())))
    except OSError:
        pass


def recently_failed():
    try:
        return time.time() - os.path.getmtime(FAIL_FILE) < FAIL_PAUSE
    except OSError:
        return False


def main():
    global stopping
    once = "--once" in sys.argv
    try:
        with open(PASS_FILE) as f:
            pw = f.read().rstrip("\n")
    except OSError:
        out({"ok": False, "why": "нет пароля роутера (router_pass.py)"})
        return
    import fcntl
    os.makedirs(os.path.dirname(LOCK_FILE), exist_ok=True)
    lock = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        out({"ok": False, "why": "админку уже читает другая плашка"})
        return
    if recently_failed():
        out({"ok": False, "why": "недавно не вошёл — пауза 30 мин"})
        return
    r = Router(pw)

    def stop(*_a):
        global stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        try:
            why = r.login()
        except requests.RequestException:
            why = "роутер не отвечает"
        if why:
            out({"ok": False, "why": why})
            return
        bad = 0
        while not stopping:
            try:
                devs = r.devices()
            except requests.RequestException:
                devs = None
            if devs is None:
                bad += 1
                if bad >= 3:     # сессию выбили (вошли из браузера) — не ломимся снова
                    out({"ok": False, "why": "сессию админки закрыли"})
                    return
            else:
                bad = 0
                out({"ok": True, "devs": devs})
            if once:
                return
            t = time.monotonic() + POLL
            while not stopping and time.monotonic() < t:
                time.sleep(0.2)
    finally:
        r.logout()


if __name__ == "__main__":
    main()
