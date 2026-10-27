#!/usr/bin/env python3
"""Микрофон собеседника в звонке Telegram — для капсулы островка (26.10.2026, Просьба: «иконку
выключенного микрофона, если он у собеседника выключен… сразу сверху видеть»).

API у Telegram для этого нет; окно звонка показывает надпись «<имя>'s microphone is off», и её
видно в дереве специальных возможностей (AT-SPI). Telegram попадает в это дерево, только если
запущен с QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1 (обёртка ~/.local/share/dbus-1/services/
org.telegram.desktop.service) или включён общий флаг a11y.

Островок запускает его на время звонка; раз в секунду печатает строку при смене:
1 — микрофон собеседника выключен, 0 — включён, na — окна звонка в дереве нет.

  island_tgmute.py          следить (для островка)
  island_tgmute.py --dump   надписи окна звонка один раз (проверка)"""
import os
import re
import sys
import time

try:
    import usercustomize  # noqa: F401  имя процесса jv:
except ImportError:
    pass

import gi
gi.require_version("Atspi", "2.0")
from gi.repository import Atspi  # noqa: E402

MUTED_RE = re.compile(r"microphone is off|микрофон.*выключ|выключ.*микрофон", re.I)
DUR_RE = re.compile(r"^\d{1,2}:\d{2}(:\d{2})?$")     # длительность звонка — признак окна звонка
MAX_NODES = 200


def walk(o, depth=0, out=None, budget=None):
    """[(роль, имя, видна)] поддерева, не глубже 6 и не больше MAX_NODES узлов."""
    out = [] if out is None else out
    budget = budget if budget is not None else [MAX_NODES]
    if depth > 6 or budget[0] <= 0:
        return out
    budget[0] -= 1
    try:
        out.append((o.get_role_name(), o.get_name() or "",
                    o.get_state_set().contains(Atspi.StateType.SHOWING)))
        for i in range(o.get_child_count()):
            c = o.get_child_at_index(i)
            if c:
                walk(c, depth + 1, out, budget)
    except Exception:
        pass
    return out


def is_call(nodes):
    return any(r == "label" and s and DUR_RE.match(n) for r, n, s in nodes)


def call_window():
    d = Atspi.get_desktop(0)
    for i in range(d.get_child_count()):
        a = d.get_child_at_index(i)
        try:
            if not a or a.get_name() != "TelegramDesktop":
                continue
            for j in range(a.get_child_count()):
                w = a.get_child_at_index(j)
                if w and is_call(walk(w)):
                    return w
        except Exception:
            continue
    return None


def state(w):
    nodes = walk(w)
    if not is_call(nodes):
        return None
    return any(s and MUTED_RE.search(n) for _r, n, s in nodes)


def main():
    if "--dump" in sys.argv:
        w = call_window()
        if not w:
            print("окна звонка Telegram в дереве нет")
            return
        for r, n, s in walk(w):
            if n:
                print("%s%-8s %s" % ("" if s else "(скрыто) ", r, n))
        return
    w, last, miss = None, "", 0
    while True:
        st = None
        if w is not None:
            st = state(w)
            if st is None:
                w = None
        if w is None and miss % 3 == 0:        # окна нет — ищем раз в 3 с, не каждую секунду
            w = call_window()
            st = state(w) if w else None
        miss = miss + 1 if w is None else 0
        out = "na" if st is None else "1" if st else "0"
        if out != last:
            last = out
            try:
                print(out, flush=True)
            except BrokenPipeError:
                return
        if os.getppid() == 1:                  # островок умер
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
