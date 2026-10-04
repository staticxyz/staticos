#!/usr/bin/env python3
"""Бар под niri: значки окон в столах и карта ленты (21.09.2026).

Обе вещи в Hyprland жили на hyprctl (scripts/ws_order.py и ribbon_map.py). Здесь —
то же самое на IPC niri. Один файл, два режима:

    niri_bar.py names     служба: вписывает в ИМЯ стола значок ПЕРВОЙ его программы
                          (самая левая колонка ленты). Пустой стол имени не получает и
                          показывает свой номер. Модуль waybar niri/workspaces значков
                          окон не умеет, но умеет показывать имя ({value}) — тот же
                          приём, каким в Hyprland пользовался ws_order.py.
                          Режим «значки/номера» — ~/.config/hypr/scripts/ws_labels.py;
                          в режиме numbers служба снимает свои имена и не мешает.
    niri_bar.py relabel   разово пересчитать подписи (зовётся из ws_labels.py)
    niri_bar.py ribbon    модуль waybar: точки — по одной на колонку активного стола
                          своего монитора (имя монитора даёт waybar в WAYBAR_OUTPUT_NAME).

Значки — из того же места, что и в Hyprland: таблица window-rewrite в
~/.config/waybar/config.jsonc. Новое приложение добавляется там один раз на оба композитора.

Про имена. Именованный стол niri не удаляет, даже пустой, поэтому имя даётся только
столу с окнами, а у опустевшего снимается — и он снова обычный, исчезает сам. Имена в
niri должны быть разными, а «2 » может оказаться на обоих мониторах, поэтому в
начало добавляются невидимые символы (по числу — номер монитора). По ним же служба
отличает СВОИ имена от заданных руками (workspace "magic" в конфиге) — чужие не трогает.

Про карту ленты. В Hyprland у точек было три тона: колонка в фокусе, на экране, за
краем. niri не сообщает, какая часть ленты сейчас на экране (tile_pos_in_workspace_view
у окон ленты пуст), поэтому тонов два: колонка в фокусе и остальные.
"""
import json
import os
import re
import select
import socket
import sys
import time

WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config.jsonc")
LABELS_STATE = os.path.expanduser("~/.config/hypr/state/ws-labels")
PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")
RIBBON_STATE = os.path.expanduser("~/.config/hypr/state/ribbon-map")   # общий с Hyprland выключатель
ZW = "​"          # невидимая метка «это имя поставила служба»
SEP = " "
DOT = "●"
DEBOUNCE = 0.06        # события идут пачками (открытие окна — три-четыре подряд)


# ── IPC niri ────────────────────────────────────────────────────────────────
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
    reply = json.loads(buf or b"{}")
    return reply.get("Ok")


def state():
    ws = (request("Workspaces") or {}).get("Workspaces", [])
    wins = (request("Windows") or {}).get("Windows", [])
    return ws, wins


def events():
    """Бесконечно: отдаёт управление после каждой ПАЧКИ событий niri.

    Сокет читает ОТДЕЛЬНЫЙ поток и ничего больше не делает. Так было не
    всегда: раньше чтение и обработка шли по очереди в одном цикле, и пока
    считались подписи столов, события копились в буфере. niri такого клиента
    отключает — «disconnecting IPC event stream client because it is reading
    events too slowly», 15 разрывов за день 25.09.2026, после чего бар
    застывал и лечился только перезапуском (просьба: «моё драгоценное время»).
    Теперь очередь не растёт: читаем всегда, обрабатываем по флагу.
    """
    import threading

    woke = threading.Event()
    alive = {"ok": True}

    def reader():
        while True:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(os.environ["NIRI_SOCKET"])
                s.sendall(b'"EventStream"\n')
            except OSError:
                time.sleep(1)
                continue
            alive["ok"] = True
            woke.set()                     # первый проход: нарисовать текущее состояние
            try:
                while True:
                    if not s.recv(1 << 16):
                        break              # niri закрыл поток — переподключаемся
                    woke.set()
            except OSError:
                pass
            finally:
                s.close()
            time.sleep(1)

    threading.Thread(target=reader, daemon=True).start()

    while True:
        woke.wait()
        # Пачку событий дочитывает поток; здесь лишь ждём, пока она уляжется,
        # чтобы не перерисовывать бар по три раза на одно действие.
        time.sleep(DEBOUNCE)
        woke.clear()
        yield


def col_row(w):
    pos = (w.get("layout") or {}).get("pos_in_scrolling_layout")
    return tuple(pos) if pos else (10 ** 6, w.get("id", 0))     # плавающие — в конец


# ── значки в именах столов ──────────────────────────────────────────────────
_rules = {"mtime": None, "rules": [], "default": ""}


def rewrite_rules():
    """[(regex, глиф)] из window-rewrite waybar; правила с title< — первыми, как в ws_order.py."""
    try:
        m = os.path.getmtime(WAYBAR_CONFIG)
        if m != _rules["mtime"]:
            raw = open(WAYBAR_CONFIG, encoding="utf-8").read()
            cfg = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M)).get("hyprland/workspaces", {})
            rules = []
            for i, (pat, glyph) in enumerate(cfg.get("window-rewrite", {}).items()):
                prio = (2 if "title<" in pat else 0) + (1 if "class<" in pat else 0)
                try:
                    rules.append((prio, i, re.compile(pat, re.I), glyph))
                except re.error:
                    pass
            rules.sort(key=lambda r: (-r[0], r[1]))
            _rules.update(mtime=m, rules=[(rx, g) for _p, _i, rx, g in rules],
                          default=cfg.get("window-rewrite-default", ""))
    except (OSError, ValueError):
        pass
    return _rules["rules"], _rules["default"]


def labels_mode():
    """icons — значок первой программы, numbers — обычные номера."""
    try:
        with open(LABELS_STATE) as f:
            v = f.read().strip()
        return v if v in ("icons", "numbers") else "icons"
    except OSError:
        return "icons"


def wanted_names(ws, wins):
    """{id стола: имя или None}. None — снять имя, стол покажет свой номер."""
    if labels_mode() == "numbers":
        return {w["id"]: None for w in ws}

    rules, _ = rewrite_rules()
    outputs = sorted({w["output"] for w in ws if w.get("output")})
    want = {}
    for w in ws:
        # Первая программа стола — самая левая колонка ленты (не самая ранняя по
        # времени: окно могли открыть позже, а стоит оно первым).
        mine = sorted((x for x in wins if x.get("workspace_id") == w["id"]), key=col_row)
        # У программы без своего правила в window-rewrite значка нет, и стол
        # показывает номер. Раньше сюда подставлялся window-rewrite-default (круг),
        # но безликий круг говорит меньше, чем цифра (просьба пользователя 21.09.2026).
        # Следующие окна стола не смотрим: значок означает «первая программа»,
        # и значок второй на её месте вводил бы в заблуждение.
        glyph = None
        if mine:
            x = mine[0]
            subject = "class<%s> title<%s>" % (x.get("app_id") or "", x.get("title") or "")
            glyph = next((g for rx, g in rules if rx.search(subject)), None)
        if glyph and w.get("output"):
            # Имена столов в niri должны быть РАЗНЫМИ, а значок у двух столов
            # легко совпадёт (два стола с kitty). Поэтому впереди невидимые
            # символы: их число уникально для пары «монитор + место стола».
            uniq = ZW * (outputs.index(w["output"]) * 100 + w["idx"] + 1)
            want[w["id"]] = uniq + glyph
        else:
            want[w["id"]] = None                        # пусто — пусть покажет номер
    return want


def relabel():
    """Разово пересчитать подписи (после смены режима в «Настройках»)."""
    ws, wins = state()
    apply_names(ws, wins)


def apply_names(ws, wins):
    want = wanted_names(ws, wins)
    for w in ws:
        cur, new = w.get("name"), want.get(w["id"])
        if cur is not None and ZW not in cur:
            continue                                    # имя задано руками — не наше дело
        if cur == new:
            continue
        if new is None:
            request({"Action": {"UnsetWorkspaceName": {"reference": {"Id": w["id"]}}}})
        else:
            request({"Action": {"SetWorkspaceName": {"name": new, "workspace": {"Id": w["id"]}}}})


def run_names():
    for _ in events():
        try:
            ws, wins = state()
            apply_names(ws, wins)
        except Exception:
            time.sleep(0.5)


def clear_names():
    ws, _ = state()
    for w in ws:
        if w.get("name") and ZW in w["name"]:
            request({"Action": {"UnsetWorkspaceName": {"reference": {"Id": w["id"]}}}})


# ── карта ленты ─────────────────────────────────────────────────────────────
_pal = {"mtime": None, "primary": "#c0c1ff"}


def primary():
    try:
        m = os.path.getmtime(PALETTE)
        if m != _pal["mtime"]:
            with open(PALETTE) as f:
                _pal.update(mtime=m, primary=json.load(f).get("primary", _pal["primary"]))
    except (OSError, ValueError):
        pass
    return _pal["primary"]


def ribbon(output):
    empty = {"text": "", "tooltip": ""}
    try:
        if open(RIBBON_STATE).read().strip() == "off":
            return empty
    except OSError:
        pass
    ws, wins = state()
    cur = next((w for w in ws if w.get("output") == output and w.get("is_active")), None)
    if not cur:
        return empty
    cols = {}
    for x in wins:
        pos = (x.get("layout") or {}).get("pos_in_scrolling_layout")
        if x.get("workspace_id") == cur["id"] and pos and not x.get("is_floating"):
            cols.setdefault(pos[0], []).append(x)
    if len(cols) < 2:
        return empty
    here = cur.get("active_window_id")
    parts, at = [], 0
    for n, c in enumerate(sorted(cols), 1):
        if any(x["id"] == here for x in cols[c]):
            at = n
            parts.append('<span foreground="%s">%s</span>' % (primary(), DOT))
        else:
            parts.append('<span foreground="%s" fgalpha="40%%">%s</span>' % (primary(), DOT))
    return {"text": " ".join(parts), "class": "ribbon",
            "tooltip": "Лента: колонок %d\nВы на %d-й" % (len(cols), at)}


def run_ribbon():
    output, last = os.environ.get("WAYBAR_OUTPUT_NAME", ""), None
    for _ in events():
        try:
            out = json.dumps(ribbon(output), ensure_ascii=False)
        except Exception:
            out = json.dumps({"text": ""})
        if out != last:
            print(out, flush=True)
            last = out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    if mode == "names":
        run_names()
    elif mode == "relabel":
        relabel()
    elif mode == "clear-names":
        clear_names()
    elif mode == "ribbon":
        run_ribbon()
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
