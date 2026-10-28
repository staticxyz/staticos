#!/usr/bin/env python3
"""Окно звонка Telegram — сразу в карман (Alt+Q / Alt+E), 28.10.2026.

Просьба: «пусть звонки телеграмм появляются в карманном столе Alt+E / Alt+Q».

У окна звонка нет своего заголовка: Telegram Desktop называет его именем собеседника
(calls_panel.cpp: setTitle(_user->name())), как и отдельное окно чата, — правилом niri
его не узнать. Сторож слушает события niri: новое окно org.telegram.desktop (кроме
просмотрщика медиа) открылось, а Telegram в этот момент играет звук или слушает
микрофон (звонок, гудки) — это звонок, окно уезжает на стол «» (карман).
Отдельное окно чата открывается без звука и остаётся, где открыто.

Если в кармане и так стоишь — фокус идёт за окном; если нет — остаёшься, где был:
звонок слышно, а взять его — Alt+Q.

    tg_call_pocket.py          сторож (живёт в staticos_host)
    tg_call_pocket.py check    самопроверка (jarvis-doctor)
    tg_call_pocket.py off|on   выключить / включить (файл state/tg-call-pocket-off)

Журнал — ~/.cache/jarvis/tg-call-pocket.log.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

POCKET = ""                       # имя кармана, как в niri cfg/workspaces.kdl
APP = "org.telegram.desktop"
VIEWER = ("Media viewer", "Просмотр медиа", "Медиапросмотр")
OFF = os.path.expanduser("~/.config/hypr/state/tg-call-pocket-off")
LOG = os.path.expanduser("~/.cache/jarvis/tg-call-pocket.log")
WAIT = 3.0                              # сколько ждать звука после открытия окна, с


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


def request(req):
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(1 << 20)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data).get("Ok")


def tg_audio(pid):
    """Telegram сейчас играет звук или пишет микрофон?"""
    for what in ("sink-inputs", "source-outputs"):
        try:
            r = subprocess.run(["pactl", "-f", "json", "list", what], capture_output=True,
                               text=True, timeout=3)
            streams = json.loads(r.stdout or "[]")
        except (OSError, ValueError, subprocess.SubprocessError):
            continue
        for s in streams:
            p = s.get("properties") or {}
            if str(p.get("application.process.id")) == str(pid) or "telegram" in (
                    "%s %s" % (p.get("application.name"), p.get("application.process.binary"))).lower():
                return True
    return False


class Watcher:
    def __init__(self):
        self.known = set()              # окна, что уже видели
        self.pocket_id = None
        self.focused_ws = None

    def is_candidate(self, w):
        return w.get("app_id") == APP and (w.get("title") or "") not in VIEWER

    def judge(self, w):
        try:
            self._judge(w)
        except Exception as e:
            log("ОШИБКА: %r — проверь `tg_call_pocket.py check`" % (e,))

    def _judge(self, w):
        if os.path.exists(OFF):
            return
        wid = w["id"]
        # главное окно Telegram при запуске — первое окно; звонок открывается вторым
        others = [x for x in request("Windows")["Windows"] if x.get("app_id") == APP and x["id"] != wid]
        if not others:
            return
        end = time.monotonic() + WAIT
        while time.monotonic() < end:
            if tg_audio(w.get("pid")):
                break
            time.sleep(0.25)
        else:
            log("окно %s «%s» без звука — не звонок, не трогаю" % (wid, w.get("title")))
            return
        if self.pocket_id is not None and w.get("workspace_id") == self.pocket_id:
            log("звонок %s уже в кармане" % wid)
            return
        follow = self.focused_ws is not None and self.focused_ws == self.pocket_id
        r = subprocess.run(["niri", "msg", "action", "move-window-to-workspace", "--window-id", str(wid),
                            "--focus", "true" if follow else "false", POCKET],
                           capture_output=True, text=True, timeout=3)
        log("звонок %s «%s» → карман%s" % (wid, w.get("title"),
                                            "" if r.returncode == 0 else " — ошибка: " + r.stderr.strip()))

    def handle(self, ev):
        if "WorkspacesChanged" in ev:
            for x in ev["WorkspacesChanged"]["workspaces"]:
                if x.get("name") == POCKET:
                    self.pocket_id = x["id"]
                if x.get("is_focused"):
                    self.focused_ws = x["id"]
        elif "WorkspaceActivated" in ev:
            if ev["WorkspaceActivated"].get("focused"):
                self.focused_ws = ev["WorkspaceActivated"]["id"]
        elif "WindowsChanged" in ev:
            self.known = {w["id"] for w in ev["WindowsChanged"]["windows"]}  # открытые до сторожа не трогать
        elif "WindowOpenedOrChanged" in ev:
            w = ev["WindowOpenedOrChanged"]["window"]
            if w["id"] in self.known:
                return
            self.known.add(w["id"])
            if self.is_candidate(w):
                threading.Thread(target=self.judge, args=(w,), daemon=True).start()
        elif "WindowClosed" in ev:
            self.known.discard(ev["WindowClosed"]["id"])

    def run(self):
        s = socket.socket(socket.AF_UNIX)
        s.connect(os.environ["NIRI_SOCKET"])
        s.sendall(b'"EventStream"\n')
        for line in s.makefile("rb"):
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                try:
                    self.handle(ev)
                except Exception as e:
                    log("ОШИБКА в событии %s: %r" % (next(iter(ev), "?"), e))
        return 1                        # niri закрылся — хозяин перезапустит


def check():
    bad = []
    try:
        ws = request("Workspaces")["Workspaces"]
        if not any(x.get("name") == POCKET for x in ws):
            bad.append("нет стола-кармана «%s» (cfg/workspaces.kdl)" % POCKET)
        wins = request("Windows")["Windows"]
        for w in wins[:1]:
            for k in ("id", "app_id", "title", "pid", "workspace_id"):
                if k not in w:
                    bad.append("niri: у окна нет поля %s" % k)
    except Exception as e:
        bad.append("niri IPC: %r" % (e,))
    r = subprocess.run(["niri", "msg", "action", "move-window-to-workspace", "--help"],
                       capture_output=True, text=True)
    if "--window-id" not in r.stdout or "--focus" not in r.stdout:
        bad.append("niri: у move-window-to-workspace нет --window-id/--focus")
    r = subprocess.run(["pactl", "-f", "json", "list", "sink-inputs"], capture_output=True, text=True)
    try:
        json.loads(r.stdout or "x")
    except ValueError:
        bad.append("pactl -f json не отвечает")
    for p in bad:
        print("✗", p)
    print("tg_call_pocket: %s" % ("в порядке" + (" (выключен)" if os.path.exists(OFF) else "")
                                  if not bad else "проблем %d" % len(bad)))
    return 1 if bad else 0


def main():
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd == "check":
        return check()
    if cmd == "off":
        os.makedirs(os.path.dirname(OFF), exist_ok=True)
        open(OFF, "w").close()
        print("выключено")
        return 0
    if cmd == "on":
        try:
            os.remove(OFF)
        except OSError:
            pass
        print("включено")
        return 0
    return Watcher().run()


if __name__ == "__main__":
    sys.exit(main())
