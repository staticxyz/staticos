#!/usr/bin/env python3
"""Логический день: после полуночи и до отбоя — ещё вчера (30.10.2026, просьба: «в pomo
время продолжалось записываться в этот день, до отбоя, а не делить строго после полуночи»).

Границы дней считает «Лучше вчера» (growth.boundary: начало самого долгого сна ПК ≥ 90 мин,
сна не видно — 05:00); hubd раз в минуту пишет их в $XDG_RUNTIME_DIR/jarvis-day строками
«ГГГГ-ММ-ДД секунды». Нет строки дня (хаб не запущен, день давний) — граница 05:00.
Тем же правилом пользуется `pomo` (awk в pomo_lday), Clocker и бот (/pomo).

    lday.py               логический сегодня (ГГГГ-ММ-ДД)
    lday.py of СЕКУНДЫ    к какому дню относится момент
    lday.py start [ДАТА]  начало дня (секунды)
"""
import datetime as dt
import os
import sys
import time

FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid()), "jarvis-day")
DAY_START_H = 5
_cache = {"key": None, "b": {}}


def bounds():
    try:
        key = os.stat(FILE).st_mtime_ns
    except OSError:
        return {}
    if key != _cache["key"]:
        b = {}
        try:
            for ln in open(FILE, encoding="utf-8"):
                p = ln.split()
                if len(p) == 2 and p[1].isdigit():
                    b[p[0]] = int(p[1])
        except OSError:
            pass
        _cache.update(key=key, b=b)
    return _cache["b"]


def start(d):
    """Начало дня d — отбой накануне."""
    b = bounds().get(d.isoformat())
    return b if b is not None else int(dt.datetime.combine(d, dt.time(DAY_START_H)).timestamp())


def day_of(ts):
    d = dt.date.fromtimestamp(ts)
    if ts < start(d):
        return d - dt.timedelta(days=1)
    if ts >= start(d + dt.timedelta(days=1)):
        return d + dt.timedelta(days=1)
    return d


def today():
    return day_of(time.time())


def write(b):
    """hubd: {дата: начало} → файл; переписывается только при изменении."""
    text = "".join("%s %d\n" % (d.isoformat(), int(t)) for d, t in sorted(b.items()))
    try:
        if open(FILE, encoding="utf-8").read() == text:
            return False
    except OSError:
        pass
    tmp = FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, FILE)
    return True


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["of"] and len(a) > 1:
        print(day_of(int(a[1])).isoformat())
    elif a[:1] == ["start"]:
        print(start(dt.date.fromisoformat(a[1]) if len(a) > 1 else today()))
    else:
        print(today().isoformat())
