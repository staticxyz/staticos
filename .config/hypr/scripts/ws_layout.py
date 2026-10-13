#!/usr/bin/env python3
"""Раскладка по столам: scrolling / tiling / stacking (эксперимент, 13.10.2026).

    ws_layout.py              сторож (живёт в staticos_host): держит раскладку столов
    ws_layout.py cycle        стол в фокусе: scrolling → tiling → stacking → scrolling (Super+Ctrl+T)
    ws_layout.py set MODE     стол в фокусе — в MODE (scrolling|tiling|stacking)
    ws_layout.py get          раскладки столов (json)
    ws_layout.py off          все столы — scrolling, ws-layout.kdl пустой
    ws_layout.py check        ws-layout.kdl совпадает с тем, что нужно сейчас; rc 1 — нет

Просьба: «по умолчанию конечно скроллинг, но возможность переключить на конкретный стол
тайлинг или стакинг. Даже если будет имитация. Если будет говно — уберём». Вторая версия
(13.10, после пробы): «окна не должны уходить за предел экрана, а делить его, как в
Hyprland»; «стакинг — можно просто открывать все окна плавающими».
niri умеет только scrolling, поэтому это имитация поверх него:
  tiling   — мастер-стек, как layout master в Hyprland: слева главное окно на половину
             экрана, справа остальные стопкой друг под другом. Колонок всегда не больше
             двух, вместе ровно в экран — ничего не уезжает. Одно окно — во весь экран;
  stacking — как в «плавающих» оконных менеджерах: все окна стола плавающие, каскадом.
             Вернули стол в scrolling — окна, которые сделал плавающими сторож, вернутся
             в раскладку (плавающие по правилам niri, вроде KeePassXC, так и останутся).
Раскладка привязана к id стола: niri_bar.py всё время переименовывает столы, а id живёт,
пока жив стол. Опустел и исчез стол — его раскладка забывается (ws-layout.json).

Подвох: в layout.kdl center-focused-column "always" — колонка в фокусе всегда по центру,
и две половинки уезжали бы на четверть экрана. Поэтому пока в фокусе тайлинговый стол,
сторож пишет в ~/.config/niri/cfg/ws-layout.kdl (подключён последним в config.kdl)
`layout { center-focused-column "never" }`, ушёл фокус — файл снова пустой. Это глобально,
но центрирование действует только на стол в фокусе, так что другие столы этого не видят.

Откат: `ws_layout.py off`, убрать ws_layout.py из ~/.config/hypr/state/staticos-host.json,
строку include "cfg/ws-layout.kdl" из config.kdl и бинд Mod+Ctrl+T из binds.kdl.
"""
import ctypes
import json
import os
import select
import signal
import subprocess
import sys
import time

_libc = ctypes.CDLL(None)    # для PR_SET_PDEATHSIG в дочерних (dlopen после fork небезопасен)

STATE = os.path.expanduser("~/.config/hypr/state/ws-layout.json")
FLOATED = os.path.expanduser("~/.config/hypr/state/ws-layout-floated.json")
KDL = os.path.expanduser("~/.config/niri/cfg/ws-layout.kdl")
MODES = ("scrolling", "tiling", "stacking")
NAMES = {"scrolling": "прокрутка (scrolling)", "tiling": "мастер-стек (tiling)",
         "stacking": "плавающие окна (stacking)"}
MASTER = "50%"
FLOAT_W, FLOAT_H, CASCADE = "50%", "60%", 36
KDL_EMPTY = ("// Пишет ws_layout.py: пусто, пока в фокусе не тайлинговый стол. Руками не править.\n")
KDL_TILING = (KDL_EMPTY + "layout {\n    center-focused-column \"never\"\n}\n")


def niri(*a):
    r = subprocess.run(["niri", "msg", *a], capture_output=True, text=True, timeout=5)
    return r.stdout


def query():
    return json.loads(niri("-j", "workspaces") or "[]"), json.loads(niri("-j", "windows") or "[]")


def act(*a):
    subprocess.run(["niri", "msg", "action", *a], capture_output=True, timeout=5)


def _load(path):
    try:
        d = json.load(open(path))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(path, d):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def load():
    return {str(k): v for k, v in _load(STATE).items() if v in MODES and v != "scrolling"}


def save(d):
    _save(STATE, d)


def write_kdl(text):
    try:
        if open(KDL).read() == text:
            return
    except OSError:
        pass
    tmp = KDL + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, KDL)                 # niri перечитает конфиг сам


def tiles(wins, ws_id):
    """Окна стола в раскладке (без плавающих): [(колонка, ряд, окно)]."""
    out = []
    for w in wins:
        pos = (w.get("layout") or {}).get("pos_in_scrolling_layout")
        if w.get("workspace_id") == ws_id and not w.get("is_floating") and pos:
            out.append((pos[0], pos[1], w))
    return sorted(out, key=lambda t: (t[0], t[1]))


def columns(wins, ws_id):
    """[[id окна, …] по колонкам слева направо]."""
    cols = {}
    for c, _r, w in tiles(wins, ws_id):
        cols.setdefault(c, []).append(w["id"])
    return [cols[c] for c in sorted(cols)]


def signature(wins, ws_id):
    return tuple((t[2]["id"], t[0]) for t in tiles(wins, ws_id))


def focused_ws(wss):
    return next((w for w in wss if w.get("is_focused")), None)


def focused_window(wins):
    return next((w["id"] for w in wins if w.get("is_focused")), None)


# ── планировщик мастер-стека (без побочных эффектов — его проверяет selftest) ──

def plan_master(cols):
    """Следующий шаг к виду [[главное], [остальные…]]: ("expel", id) — в первой колонке
    больше одного окна; ("consume", id) — колонок больше двух, дозабрать в колонку id;
    None — уже готово."""
    if not cols:
        return None
    if len(cols[0]) > 1:
        return ("expel", cols[0][0])
    if len(cols) > 2:
        return ("consume", cols[1][0])
    return None


def master_widths(cols):
    if len(cols) == 1:
        return [(cols[0][0], "100%")]
    return [(cols[0][0], MASTER), (cols[1][0], "%g%%" % (100 - float(MASTER.rstrip("%"))))]


# ── применение ──

def apply_tiling(ws, focus_id, force=False):
    """Довести стол до мастер-стека. Перестройка колонок — через фокус (expel/consume
    в niri работают с колонкой в фокусе), поэтому только на столе, что на экране."""
    _wss, wins = query()
    cols = columns(wins, ws["id"])
    if not cols:
        return
    changed = force
    if ws.get("is_active"):
        for _ in range(40):
            step = plan_master(cols)
            if not step:
                break
            changed = True
            act("focus-window", "--id", str(step[1]))
            act("set-column-display", "normal")
            act("expel-window-from-column" if step[0] == "expel" else "consume-window-into-column")
            _wss, wins = query()
            cols = columns(wins, ws["id"])
    if not changed:
        return
    for wid, width in master_widths(cols):
        act("set-window-width", "--id", str(wid), width)
    if ws.get("is_active") and focus_id:
        # показать стол с первой колонки: при «never» вид потом не сдвинется
        act("focus-window", "--id", str(cols[0][0]))
        act("focus-window", "--id", str(focus_id))


def float_window(wid, k):
    act("move-window-to-floating", "--id", str(wid))
    act("set-window-width", "--id", str(wid), FLOAT_W)
    act("set-window-height", "--id", str(wid), FLOAT_H)
    off = CASCADE * (1 + k % 8)
    act("move-floating-window", "--id", str(wid), "-x", str(off * 2), "-y", str(off))


def apply_stacking(ws, focus_id):
    _wss, wins = query()
    t = tiles(wins, ws["id"])
    if not t:
        return
    fl = _load(FLOATED)
    mine = fl.setdefault(str(ws["id"]), [])
    for _c, _r, w in t:
        float_window(w["id"], len(mine))
        mine.append(w["id"])
    _save(FLOATED, fl)
    if focus_id:
        act("focus-window", "--id", str(focus_id))


def unfloat(ws, focus_id):
    """Вернуть в раскладку окна, которые сделал плавающими сторож."""
    fl = _load(FLOATED)
    ids = fl.pop(str(ws["id"]), [])
    _save(FLOATED, fl)
    _wss, wins = query()
    here = {w["id"] for w in wins if w.get("workspace_id") == ws["id"] and w.get("is_floating")}
    for wid in ids:
        if wid in here:
            act("move-window-to-tiling", "--id", str(wid))
            act("set-window-width", "--id", str(wid), "50%")
    if focus_id:
        act("focus-window", "--id", str(focus_id))


def untile(ws, focus_id):
    _wss, wins = query()
    for col in columns(wins, ws["id"]):
        act("set-window-width", "--id", str(col[0]), "50%")
    if ws.get("is_active") and focus_id:
        act("focus-window", "--id", str(focus_id))


def sync_kdl(wss, modes):
    f = focused_ws(wss)
    write_kdl(KDL_TILING if f and modes.get(str(f["id"])) == "tiling" else KDL_EMPTY)


# ── команды ──

def set_mode(mode, ws=None):
    wss, wins = query()
    ws = ws or focused_ws(wss)
    if not ws:
        return 1
    modes = load()
    old = modes.get(str(ws["id"]), "scrolling")
    if mode == "scrolling":
        modes.pop(str(ws["id"]), None)
    else:
        modes[str(ws["id"])] = mode
    save(modes)
    sync_kdl(wss, modes)
    fid = focused_window(wins)
    if old == "stacking" and mode != "stacking":
        unfloat(ws, fid)
    if mode == "tiling":
        time.sleep(0.5)                  # niri перечитал ws-layout.kdl
        apply_tiling(ws, fid, force=True)
    elif mode == "stacking":
        apply_stacking(ws, fid)
    elif old == "tiling":
        untile(ws, fid)
    subprocess.run(["notify-send", "-a", "Раскладка стола", "-t", "1800",
                    "Стол %s: %s" % (ws.get("idx"), NAMES[mode])], capture_output=True)
    print(mode)
    return 0


def watch():
    last = {}
    while True:
        # PDEATHSIG: живёт в хозяине staticOS — без него поток событий оставался
        # сиротой после каждого перезапуска хозяина (13.10.2026).
        p = subprocess.Popen(["niri", "msg", "-j", "event-stream"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True,
                             preexec_fn=lambda: _libc.prctl(1, signal.SIGTERM, 0, 0, 0))
        try:
            dirty = True
            while True:
                r, _, _ = select.select([p.stdout], [], [], 0.12 if dirty else None)
                if r:
                    line = p.stdout.readline()
                    if not line:
                        break
                    dirty = True
                    continue
                dirty = False
                modes = load()
                wss, wins = query()
                alive = {str(w["id"]) for w in wss}
                if any(k not in alive for k in modes):          # стол исчез — забыть
                    modes = {k: v for k, v in modes.items() if k in alive}
                    save(modes)
                    fl = _load(FLOATED)
                    _save(FLOATED, {k: v for k, v in fl.items() if k in alive})
                sync_kdl(wss, modes)
                fid = focused_window(wins)
                for ws in wss:
                    mode = modes.get(str(ws["id"]))
                    if not mode:
                        last.pop(ws["id"], None)
                        continue
                    sig = (mode, signature(wins, ws["id"]), bool(ws.get("is_active")))
                    if last.get(ws["id"]) == sig:
                        continue
                    if mode == "tiling":
                        apply_tiling(ws, fid)
                    else:
                        apply_stacking(ws, fid)
                    _w, wins = query()
                    last[ws["id"]] = (mode, signature(wins, ws["id"]), bool(ws.get("is_active")))
        finally:
            p.kill()
        time.sleep(2)


def check():
    wss, _wins = query()
    f = focused_ws(wss)
    want = KDL_TILING if f and load().get(str(f["id"])) == "tiling" else KDL_EMPTY
    try:
        have = open(KDL).read()
    except OSError:
        have = None
    inc = 'include "cfg/ws-layout.kdl"' in open(os.path.expanduser("~/.config/niri/config.kdl")).read()
    print(json.dumps({"modes": load(), "kdl_ok": have == want, "included": inc}, ensure_ascii=False))
    return 0 if have == want and inc else 1


def selftest():
    def run(cols):
        """Прогнать планировщик на модели niri: expel — нижнее окно колонки уходит в новую
        колонку справа; consume — верхнее окно следующей колонки — вниз в эту."""
        cols = [list(c) for c in cols]
        for _ in range(40):
            step = plan_master(cols)
            if not step:
                return cols
            i = next(n for n, c in enumerate(cols) if step[1] in c)
            if step[0] == "expel":
                cols.insert(i + 1, [cols[i].pop()])
            else:
                cols[i].append(cols[i + 1].pop(0))
                if not cols[i + 1]:
                    cols.pop(i + 1)
        raise AssertionError("не сошлось: %r" % cols)
    assert run([[1]]) == [[1]]
    assert run([[1], [2]]) == [[1], [2]]
    assert run([[1], [2], [3], [4]]) == [[1], [2, 3, 4]]
    assert run([[1, 2, 3]]) == [[1], [2, 3]]
    assert run([[1], [2, 3], [4]]) == [[1], [2, 3, 4]]
    assert run([[1], [5], [2, 3]]) == [[1], [5, 2, 3]]
    assert master_widths([[1]]) == [(1, "100%")]
    assert master_widths([[1], [2, 3]]) == [(1, "50%"), (2, "50%")]
    print("selftest ok")
    return 0


def main(a):
    if not a:
        watch()
        return 0
    if a == ["cycle"]:
        wss, _ = query()
        f = focused_ws(wss)
        cur = load().get(str(f["id"]), "scrolling") if f else "scrolling"
        return set_mode(MODES[(MODES.index(cur) + 1) % len(MODES)])
    if len(a) == 2 and a[0] == "set" and a[1] in MODES:
        return set_mode(a[1])
    if a == ["get"]:
        print(json.dumps(load()))
        return 0
    if a == ["off"]:
        wss, wins = query()
        fid = focused_window(wins)
        for ws in wss:
            if str(ws["id"]) in _load(FLOATED):
                unfloat(ws, fid)
        save({})
        write_kdl(KDL_EMPTY)
        return 0
    if a == ["check"]:
        return check()
    if a == ["selftest"]:
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
