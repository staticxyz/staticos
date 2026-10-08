#!/usr/bin/env python3
"""Картинка в картинке встаёт туда, куда её поставили в прошлый раз (07.10.2026).

Просьба: «положил в другой монитор, задал размер, подогнал и поставил в определённом
месте — хочу, чтобы запоминал и в следующий раз сразу вставал туда. И сбрасывалось,
когда перезапускаю браузер».

Сторож слушает события niri. Окно картинки (app-id zen|librewolf, заголовок
«Picture-in-Picture») после каждого перемещения или изменения размера запоминается:
монитор, положение на нём, размер — и PID браузера. Окно картинки принадлежит главному
процессу браузера, поэтому новый PID = браузер перезапускали: запомненное не
применяется, окно открывается по правилу niri (правый нижний угол, 640x360), а
дальше запоминается заново. У Zen и LibreWolf места свои.

Положение и размер ставятся абсолютной командой, потом сверяются с тем, что вышло,
и доводятся относительным сдвигом — так не важно, от какого края niri считает
координаты (с баром и без).

    pip_place.py            сторож (живёт в staticos_host)
    pip_place.py show       что запомнено
    pip_place.py forget     забыть
    pip_place.py check      самопроверка (после обновлений niri)

Файл — ~/.cache/jarvis/pip-place.json. Журнал — ~/.cache/jarvis/pip-place.log.
"""
import json
import os
import socket
import subprocess
import sys
import threading
import time

STATE = os.path.expanduser("~/.cache/jarvis/pip-place.json")
LOG = os.path.expanduser("~/.cache/jarvis/pip-place.log")
APPS = ("zen", "librewolf")
# Заголовок окна картинки. Русский — на случай, если браузер начнёт его переводить
# (в Firefox так бывало); тот же список — в правиле niri cfg/window-rules.kdl.
TITLES = ("Picture-in-Picture", "Картинка в картинке")


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))
    except OSError:
        pass


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(data):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


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


def action(*args):
    subprocess.run(["niri", "msg", "action", *args], capture_output=True, timeout=3)


def is_pip(w):
    return (w.get("app_id") or "").lower() in APPS and (w.get("title") or "") in TITLES


class Watcher:
    def __init__(self):
        self.windows = {}          # id → окно
        self.ws_output = {}        # id стола → монитор
        self.seen = set()          # окна картинки, которые уже видели
        self.busy = set()          # окна, которые сейчас ставим сами — не запоминать
        self.timers = {}

    # ── запомнить ────────────────────────────────────────────────────────────
    def remember_later(self, wid):
        """Запись с паузой 0,7 с: перетаскивание шлёт десятки событий подряд."""
        t = self.timers.pop(wid, None)
        if t:
            t.cancel()
        t = threading.Timer(0.7, self.remember, (wid,))
        t.daemon = True
        self.timers[wid] = t
        t.start()

    def remember(self, wid):
        try:
            self._remember(wid)
        except Exception as e:
            log("ОШИБКА при записи: %r — проверь `pip_place.py check`" % (e,))

    def _remember(self, wid):
        self.timers.pop(wid, None)
        if wid in self.busy:
            return
        w = self.fresh(wid)
        if not w or not is_pip(w) or not w.get("is_floating"):
            return
        lay = w.get("layout") or {}
        pos, size = lay.get("tile_pos_in_workspace_view"), lay.get("window_size")
        out = self.output_of(w)
        if not pos or not size or not out:
            return
        rec = {"pid": w.get("pid"), "output": out, "x": round(pos[0]), "y": round(pos[1]),
               "w": size[0], "h": size[1]}
        data = load()
        if data.get(w["app_id"]) != rec:
            data[w["app_id"]] = rec
            save(data)
            log("запомнено %s: %s" % (w["app_id"], rec))

    # ── поставить ────────────────────────────────────────────────────────────
    def fresh(self, wid):
        try:
            for w in request("Windows")["Windows"]:
                if w["id"] == wid:
                    return w
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def output_of(self, w):
        out = self.ws_output.get(w.get("workspace_id"))
        if out is None:                       # стол новый, событие ещё не дошло
            try:
                self.ws_output = {x["id"]: x.get("output") for x in request("Workspaces")["Workspaces"]}
            except (OSError, ValueError, KeyError, TypeError):
                pass
            out = self.ws_output.get(w.get("workspace_id"))
        return out

    def settle(self, wid, rec):
        """Довести окно до записи: монитор, размер, место. Вернуть, что вышло."""
        state = None
        for _ in range(4):
            cur = self.fresh(wid)
            if not cur:
                return None
            lay = cur.get("layout") or {}
            pos, size = lay.get("tile_pos_in_workspace_view"), lay.get("window_size")
            out = self.output_of(cur)
            state = (out, pos and round(pos[0]), pos and round(pos[1]), size and size[0], size and size[1])
            if out != rec["output"]:
                action("move-window-to-monitor", "--id", str(wid), rec["output"])
                time.sleep(0.15)
                continue
            if not pos or not size:
                break
            dw, dh = rec["w"] - size[0], rec["h"] - size[1]
            dx, dy = rec["x"] - round(pos[0]), rec["y"] - round(pos[1])
            if not (dw or dh or dx or dy):
                break
            if dw:
                action("set-window-width", "--id", str(wid), "%+d" % dw)
            if dh:
                action("set-window-height", "--id", str(wid), "%+d" % dh)
            if dx or dy:
                action("move-floating-window", "--id", str(wid), "-x", "%+d" % dx, "-y", "%+d" % dy)
            time.sleep(0.12)
        return state

    def place(self, w):
        try:
            self._place(w)
        except Exception as e:                 # niri сменил формат и т.п. — окно просто остаётся по умолчанию
            self.busy.discard(w.get("id"))
            log("ОШИБКА при установке: %r — проверь `pip_place.py check`" % (e,))

    def _place(self, w):
        rec = load().get(w["app_id"])
        wid = w["id"]
        if not rec:
            log("открыто %s — места ещё нет" % w["app_id"])
            return
        if rec.get("pid") != w.get("pid"):
            log("браузер перезапущен (PID %s → %s) — место по умолчанию" % (rec.get("pid"), w.get("pid")))
            return
        outputs = (request("Outputs") or {}).get("Outputs") or {}
        if rec["output"] not in outputs:
            log("монитора %s нет — место по умолчанию" % rec["output"])
            return
        self.busy.add(wid)
        try:
            action("set-window-width", "--id", str(wid), str(rec["w"]))
            action("set-window-height", "--id", str(wid), str(rec["h"]))
            time.sleep(0.15)
            got = self.settle(wid, rec)
            # браузер после открытия может сам поменять размер окна — проверить ещё дважды
            for pause in (0.6, 1.2):
                time.sleep(pause)
                got = self.settle(wid, rec)
            want = (rec["output"], rec["x"], rec["y"], rec["w"], rec["h"])
            log("поставлено %s: %s%s" % (w["app_id"], rec,
                "" if got == want else " — вышло %s" % (got,)))
        finally:
            time.sleep(0.3)
            self.busy.discard(wid)

    # ── события ──────────────────────────────────────────────────────────────
    def on_window(self, w):
        self.windows[w["id"]] = w
        if not is_pip(w):
            return
        lay = w.get("layout") or {}
        log("  событие окна %s: стол %s, плавает %s, место %s, размер %s" % (
            w["id"], w.get("workspace_id"), w.get("is_floating"),
            lay.get("tile_pos_in_workspace_view"), lay.get("window_size")))
        if w["id"] not in self.seen:
            self.seen.add(w["id"])
            threading.Thread(target=self.place, args=(w,), daemon=True).start()
        else:
            self.remember_later(w["id"])          # переехало на другой монитор/стол

    def handle(self, ev):
        if "WorkspacesChanged" in ev:
            self.ws_output = {x["id"]: x.get("output") for x in ev["WorkspacesChanged"]["workspaces"]}
        elif "WindowsChanged" in ev:
            self.windows = {}
            for w in ev["WindowsChanged"]["windows"]:
                self.windows[w["id"]] = w
                if is_pip(w):
                    self.seen.add(w["id"])          # открыто до запуска сторожа — не трогать
        elif "WindowOpenedOrChanged" in ev:
            self.on_window(ev["WindowOpenedOrChanged"]["window"])
        elif "WindowClosed" in ev:
            wid = ev["WindowClosed"]["id"]
            self.windows.pop(wid, None)
            self.seen.discard(wid)
        elif "WindowLayoutsChanged" in ev:
            for wid, _lay in ev["WindowLayoutsChanged"]["changes"]:
                if wid in self.seen and wid not in self.busy:
                    self.remember_later(wid)

    def run(self):
        s = socket.socket(socket.AF_UNIX)
        s.connect(os.environ["NIRI_SOCKET"])
        s.sendall(b'"EventStream"\n')
        f = s.makefile("rb")
        for line in f:
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                try:
                    self.handle(ev)
                except Exception as e:          # одно странное событие не роняет сторожа
                    log("ОШИБКА в событии %s: %r" % (next(iter(ev), "?"), e))
        return 1                                    # niri закрылся — хозяин перезапустит


def check():
    """Самопроверка: всё ли, на что опирается сторож, на месте. Для jarvis-doctor."""
    bad = []
    try:
        wins = request("Windows")["Windows"]
        for w in wins[:1]:
            for k in ("id", "app_id", "title", "pid", "workspace_id", "is_floating", "layout"):
                if k not in w:
                    bad.append("niri: у окна нет поля %s" % k)
            for k in ("tile_pos_in_workspace_view", "window_size"):
                if k not in (w.get("layout") or {}):
                    bad.append("niri: в layout нет поля %s" % k)
        ws = request("Workspaces")["Workspaces"]
        if ws and "output" not in ws[0]:
            bad.append("niri: у стола нет поля output")
        if not isinstance(request("Outputs")["Outputs"], dict):
            bad.append("niri: Outputs не словарь")
    except Exception as e:
        bad.append("niri IPC: %r" % (e,))
    for act in ("move-window-to-monitor", "set-window-width", "set-window-height", "move-floating-window"):
        r = subprocess.run(["niri", "msg", "action", act, "--help"], capture_output=True, text=True)
        if r.returncode != 0 or "--id" not in r.stdout:
            bad.append("niri: нет действия %s --id" % act)
    rules = os.path.expanduser("~/.config/niri/cfg/window-rules.kdl")
    try:
        if "Picture-in-Picture" not in open(rules).read():
            bad.append("правило niri для картинки пропало из window-rules.kdl")
    except OSError:
        bad.append("нет window-rules.kdl")
    for p in bad:
        print("✗", p)
    print("pip_place: в порядке" if not bad else "pip_place: проблем %d" % len(bad))
    return 1 if bad else 0


def main():
    cmd = (sys.argv[1:] or ["run"])[0]
    if cmd == "show":
        d = load()
        print(json.dumps(d, ensure_ascii=False, indent=1) if d else "ничего не запомнено")
        return 0
    if cmd == "check":
        return check()
    if cmd == "forget":
        try:
            os.remove(STATE)
        except OSError:
            pass
        print("забыто")
        return 0
    return Watcher().run()


if __name__ == "__main__":
    sys.exit(main())
