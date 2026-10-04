#!/usr/bin/env python3
"""Общее знание о плеерах MPRIS — для модуля бара и всплывающего плеера.

Зачем отдельный модуль: у бара (mpris_status.py) и попапа (player_popup.py)
была своя, чуть разная логика выбора плеера, и обе спотыкались об одно и то же.

Две ловушки, ради которых всё это написано (проверено 12.09.2026):

1. **`{{playerName}}` у всех хромоподобных — просто "chromium".** Отличить
   helium от Яндекс.Музыки по нему нельзя; PID лежит в `{{playerInstance}}`,
   который выглядит как "chromium.instance885694" — вот это число и есть PID.

2. **Helium публикует метаданные без названия**: в словаре на шине одно поле
   `mpris:length`, title и artist пустые. Поэтому название берём из заголовка
   ОКНА браузера — там настоящее имя вкладки («… - YouTube - Helium»), а
   хвост с именем браузера отрезаем.

Выбор плеера: сначала играющий, потом приостановленный; при равенстве —
чьё окно вы трогали позже (focusHistoryID у Hyprland: 0 — последнее активное).
Так helium перестаёт пропадать из бара, стоит поставить его на паузу.
"""
import json
import subprocess
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402

SEP = "\x1f"
# Приложения, которые вечно висят в «играет/пауза», но музыкой не являются.
IGNORED = ("blanket",)
# Хвосты заголовков окон: браузер дописывает своё имя к названию вкладки.
TAILS = (" - Helium", " — Helium", " - Chromium", " — Chromium",
         " - LibreWolf", " — LibreWolf", " - Mozilla Firefox",
         " - Thorium", " — Thorium", " - Google Chrome")


def _run(args, timeout=3):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _clients():
    """Окна композитора: pid -> (заголовок, позиция в истории фокуса).

    Через scripts/wm.py — одинаково в Hyprland и в Niri (21.09.2026: под Niri
    список был пуст, и попап плеера выбирал окно вслепую).
    """
    res = {}
    for c in wm.windows():
        pid = c.get("pid")
        if pid and pid > 0:
            prev = res.get(pid)
            hist = c.get("focus_order", 999)
            # У браузера несколько окон — берём то, которым пользовались позже.
            if prev is None or hist < prev[1]:
                res[pid] = (c.get("title", ""), hist)
    return res


def _owner_pid(instance):
    """PID плеера. Для хромоподобных он прямо в имени: chromium.instanceNNNN."""
    _, _, tail = instance.partition(".instance")
    if tail.isdigit():
        return int(tail)
    out = _run(["busctl", "--user", "call", "org.freedesktop.DBus", "/",
                "org.freedesktop.DBus", "GetConnectionUnixProcessID", "s",
                "org.mpris.MediaPlayer2." + instance]).split()
    try:
        return int(out[1])
    except (IndexError, ValueError):
        return 0


def _window_of(pid, clients):
    """Окно процесса или его предка: (заголовок, позиция в истории фокуса)."""
    seen = 0
    while pid > 1 and seen < 12:
        if pid in clients:
            return clients[pid]
        try:
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        seen += 1
    return ("", 999)


def _strip_tail(title):
    for t in TAILS:
        if title.endswith(t):
            return title[: -len(t)].strip()
    return title


# ── Чистка названий (30.09.2026, идея из дотфайлов PixelStreetArt, своя реализация).
# YouTube и музыкальные сервисы приклеивают к названию мусор: «(Official Video)»,
# «[4K]», «| Премьера клипа», «- Topic» у исполнителя, «VEVO». В баре и плеере
# это съедает место — остаётся только само название.
import re as _re
_JUNK = (r"official|video|клип|lyric|lyrics|audio|visuali[sz]er|4k|hd|hq|mv|m/v|"
         r"премьера|remaster(ed)?|full album|live|текст|караоке|music video|видео")
_BRACKETS = _re.compile(r"\s*[\(\[【]([^\)\]】]*)[\)\]】]")
_TAIL = _re.compile(r"\s*[|｜/]\s*[^|｜/]*(" + _JUNK + r")[^|｜/]*$", _re.I)


def clean_title(t):
    if not t:
        return t
    out = _BRACKETS.sub(lambda m: "" if _re.search(_JUNK, m.group(1), _re.I) else m.group(0), t)
    out = _TAIL.sub("", out)
    out = _re.sub(r"\s+", " ", out).strip(" -–—|")
    return out or t


def clean_artist(a):
    if not a:
        return a
    out = _re.sub(r"\s*-\s*Topic$", "", a)
    out = _re.sub(r"VEVO$", "", out).strip()
    return out or a


def players():
    """Список плееров: instance, name, status, title, artist, from_window.

    `title` уже подставлен из заголовка окна, если MPRIS его не дал;
    `from_window` говорит, что название взято оттуда, а не из метаданных.
    """
    fmt = SEP.join(("{{playerInstance}}", "{{playerName}}", "{{status}}",
                    "{{title}}", "{{artist}}"))
    rows = []
    raw = _run(["playerctl", "-a", "metadata", "--format", fmt])
    for line in raw.splitlines():
        parts = line.split(SEP)
        if len(parts) != 5:
            continue
        instance, name, status, title, artist = parts
        if any(i in instance.lower() for i in IGNORED):
            continue
        rows.append({"instance": instance, "name": name, "status": status,
                     "title": clean_title(title), "artist": clean_artist(artist), "from_window": False,
                     "hist": 999, "pid": 0})
    if not rows:
        return rows
    # Окна спрашиваем один раз и только если это кому-то нужно: без названия
    # или для разрешения ничьей между одинаковыми статусами.
    clients = _clients()
    for r in rows:
        r["pid"] = _owner_pid(r["instance"])
        wtitle, hist = _window_of(r["pid"], clients) if r["pid"] else ("", 999)
        r["hist"] = hist
        if not r["title"] and wtitle:
            r["title"] = clean_title(_strip_tail(wtitle))
            r["from_window"] = True
        if not r["title"]:
            # Совсем ничего — хотя бы имя приложения по /proc.
            try:
                with open("/proc/%d/comm" % r["pid"]) as f:
                    nm = f.read().strip()
                r["title"] = nm[:1].upper() + nm[1:]
                r["from_window"] = True
            except OSError:
                r["title"] = r["name"][:1].upper() + r["name"][1:]
                r["from_window"] = True
    return rows


def pick(rows=None):
    """Кого показывать: играющий важнее; при равенстве — чьё окно свежее."""
    rows = players() if rows is None else rows
    if not rows:
        return None
    order = {"Playing": 0, "Paused": 1}
    return min(rows, key=lambda r: (order.get(r["status"], 2), r["hist"]))


if __name__ == "__main__":
    for r in players():
        print("%-26s %-8s hist=%-4s %s%s" % (r["instance"], r["status"], r["hist"],
                                             r["title"], "  (из окна)" if r["from_window"] else ""))
    best = pick()
    print("выбран:", best["instance"], "->", best["title"] if best else "никто")
