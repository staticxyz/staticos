#!/usr/bin/env python3
"""Идёт ли сейчас игра из Steam.

Steam запускает любую игру — родную (CS2) и через Proton — под своим процессом
reaper с аргументами `SteamLaunch AppId=<id>`. Он живёт ровно столько, сколько
игра, поэтому его наличие и есть ответ. Используют hypridle (не приглушать,
не блокировать, не усыплять посреди матча) и mem-guard (не трогать игру).

    game_guard.py      печатает «игра идёт: AppId=730» или «игры нет»
"""
import os
import sys


def running_app_id():
    for d in os.listdir("/proc"):
        if not d.isdigit():
            continue
        try:
            argv = open("/proc/%s/cmdline" % d, "rb").read().split(b"\0")
        except OSError:
            continue
        if b"SteamLaunch" in argv:
            for a in argv:
                if a.startswith(b"AppId="):
                    return a[6:].decode(errors="ignore") or "?"
    return None


def game_running():
    try:
        return running_app_id() is not None
    except Exception as e:                  # сомневаешься — ведём себя как без игры
        print("game_guard: %s" % e, file=sys.stderr)
        return False


if __name__ == "__main__":
    app = running_app_id()
    print("игра идёт: AppId=%s" % app if app else "игры нет")
