#!/usr/bin/env python3
"""Запомнить, где стоят окна блокнота, и вернуть их туда после перезапуска.

Зачем (24.09.2026). mousepad_retheme.sh перезапускает блокнот при каждой смене
обоев — иначе поле текста остаётся в старой палитре. Восстановленное окно niri
открывал по правилу: плавающим 900x600 по центру ТЕКУЩЕГО стола. пользователь убирал
блокнот на другой стол, а после смены обоев он снова выскакивал перед глазами.

    mousepad_place.py snapshot FILE   — записать окна блокнота и окно в фокусе
    mousepad_place.py restore FILE    — дождаться новых окон и расставить по местам

Стол задаётся номером (id) через сокет niri, а не именем: имена столов у пользователя
собраны из невидимых символов и значков, а номер по порядку (idx) в CLI
относится к текущему монитору.
"""
import json
import os
import socket
import sys
import time

CLASS = "org.xfce.mousepad"
WAIT_S = 6.0


def niri(req):
    s = socket.socket(socket.AF_UNIX)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall((json.dumps(req) + "\n").encode())
    data = b""
    while not data.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        data += chunk
    s.close()
    return json.loads(data)


def windows():
    return niri("Windows")["Ok"]["Windows"]


def action(name, **args):
    return niri({"Action": {name: args}})


def snapshot(path):
    wins = windows()
    focused = next((w["id"] for w in wins if w.get("is_focused")), None)
    pads = [{"id": w["id"], "title": w.get("title") or "", "workspace_id": w["workspace_id"],
             "floating": w["is_floating"],
             "pos": (w.get("layout") or {}).get("tile_pos_in_workspace_view")}
            for w in wins if w.get("app_id") == CLASS]
    with open(path, "w") as f:
        json.dump({"focused": focused, "pads": pads}, f)


def restore(path):
    with open(path) as f:
        snap = json.load(f)
    old_ids = {p["id"] for p in snap["pads"]}
    want = len(snap["pads"])
    fresh = []
    deadline = time.time() + WAIT_S
    while time.time() < deadline:
        fresh = [w for w in windows() if w.get("app_id") == CLASS and w["id"] not in old_ids]
        if len(fresh) >= want:
            break
        time.sleep(0.05)
    left = list(snap["pads"])
    for w in fresh:
        # Сначала по заголовку (в нём имя открытого файла), иначе — по порядку.
        match = next((p for p in left if p["title"] == (w.get("title") or "")), None)
        if match is None and left:
            match = left[0]
        if match is None:
            continue
        left.remove(match)
        if w["workspace_id"] != match["workspace_id"]:
            action("MoveWindowToWorkspace", window_id=w["id"],
                   reference={"Id": match["workspace_id"]}, focus=False)
        if not match["floating"]:
            action("MoveWindowToTiling", id=w["id"])
        elif match.get("pos"):
            x, y = match["pos"]
            action("MoveFloatingWindow", id=w["id"],
                   x={"SetFixed": float(x)}, y={"SetFixed": float(y)})
    # Новое окно забирает фокус себе — возвращаем туда, где был пользователь.
    focused = snap.get("focused")
    if focused and focused not in old_ids and any(w["id"] == focused for w in windows()):
        action("FocusWindow", id=focused)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] not in ("snapshot", "restore"):
        sys.exit(__doc__)
    (snapshot if sys.argv[1] == "snapshot" else restore)(sys.argv[2])
