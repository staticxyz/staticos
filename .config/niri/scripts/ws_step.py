#!/usr/bin/env python3
"""Шаг по столам мимо пустого кармана (02.11.2026, зовётся из ws-step).

Без MSI карман (Alt+Q, workspaces.kdl) живёт на ноутбуке посреди столов. Он существует
всегда, даже пустой, а его кнопка в баре стоит слева от всех столов (niri_bar.py pocket).
Поэтому шаг вниз попадал на него и выглядел как лишний стол с номером не на своём месте.

Выход 0 — шаг сделан здесь (или идти некуда). Выход 1 — обычный шаг, делает ws-step.
Карман с окнами не пропускается: он виден в баре. Достать пустой — Alt+Q.
"""
import json
import os
import socket
import sys

POCKET = ""
PLAIN = object()


def request(obj):
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.environ["NIRI_SOCKET"])
    s.sendall(json.dumps(obj).encode() + b"\n")
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
    s.close()
    return json.loads(buf)["Ok"]


def target(ws, way):
    """id стола за пустым карманом, None — за ним столов нет, PLAIN — кармана на пути нет."""
    cur = next((w for w in ws if w.get("is_focused")), None)
    if cur is None:
        return PLAIN
    same = sorted((w for w in ws if w.get("output") == cur.get("output")), key=lambda w: w["idx"])
    step = 1 if way == "down" else -1
    at = same.index(cur) + step
    if not 0 <= at < len(same):
        return PLAIN
    if same[at].get("name") != POCKET or same[at].get("active_window_id") is not None:
        return PLAIN
    at += step
    return same[at]["id"] if 0 <= at < len(same) else None


def main():
    to = target(request("Workspaces")["Workspaces"], sys.argv[1])
    if to is PLAIN:
        return 1
    if to is not None:
        request({"Action": {"FocusWorkspace": {"reference": {"Id": to}}}})
    return 0


if __name__ == "__main__":
    sys.exit(main())
