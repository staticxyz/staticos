#!/usr/bin/env python3
"""Режим «стопка» (как hyprstack) на всех мониторах. 20.10.2026, все мониторы — 21.10.2026.

Просьба: «В стакинге у нас единый рабочий стол …, где все окна имеют плавающий вид, и …
сверху полоска с тремя кнопками: Свернуть, Развернуть, Закрыть». И: «при смене режимов
должны запоминаться все размеры, масштабы, расположения… Все до смены». Виджеты: «надо
разделять мониторы, они не должны смешиваться». 21.10: «я планировал внедрить её в целом.
На все мониторы. А виджеты остаются и работают также как и работали».

    stack_mode.py toggle | on | off   Ctrl+Shift+Super+M
    stack_mode.py status              включена ли, сколько окон, когда снят снимок
    stack_mode.py verify              сверить раскладку со снимком (после off); rc 1 — расхождения
    stack_mode.py restore             ещё раз разложить по последнему снимку
    stack_mode.py unmin ID            вернуть свёрнутое окно (нижняя панель, Alt+Tab)
    stack_mode.py max ID              развернуть ⇄ обратно (меню панели) — с полётом полосы
    stack_mode.py maxmode [full|island]  развёрнутое: на весь экран | под островком
    stack_mode.py topbar [waybar|capsule]  верхний бар в стопке: обычный | капсула Minimalistic
    stack_mode.py key up|down         Super+K/J: в стопке K развернуть / вернуть последнее
                                      свёрнутое, J обычный размер / свернуть; без стопки — столы
    stack_mode.py key fs              Super+F: в стопке — развернуть ⇄ обратно, вне — полный экран
    stack_mode.py superd              Super+D: в стопке свернуть все окна ⇄ вернуть,
                                      без стопки — стол дашборда (dashboard focus)
    stack_mode.py tomon left|right    Ctrl+Alt+H/L: окно на соседний монитор (в стопке — на
                                      его стол стопки, то же место; вне — как в niri)
    stack_mode.py move left|right|up|down  Super+Alt+H/L/K/J: в стопке сдвиг окна на 50 px,
                                      вне — перенос колонки/окна, как в niri
    stack_mode.py daemon              полосы заголовков и порядок на столе (запускает on)
    stack_mode.py check | selftest

Как устроено. niri не умеет ни заголовков с кнопками, ни «свернуть», поэтому:
  * у каждого монитора своя стопка: свой общий стол, свои свёрнутые, свои полосы;
    окна между мониторами не ездят. Общий стол — первый стол монитора, кроме кармана
    (POCKET, Super+Alt+Q): на ноутбуке это стол 1 (стол виджетов), на MSI — первый после
    кармана. Окна кармана тоже едут на общий стол (21.10.2026, просьба: «все окна должны быть
    в одном столе, исключения только на мониторы»), на выходе возвращаются в карман.
  * вход: снимок всей раскладки всех мониторов (столы, их порядок и имена, колонки и
    строки, ширины/высоты, плавающие места, активные окна, раскладки ws_layout) — в
    state/stack-mode.json ДО первого движения; потом окна (кроме dash-*) едут
    на общий стол своего монитора и становятся плавающими.
  * выход: окна возвращаются на свои столы (исчезнувшие столы создаются заново в том же
    порядке), колонки/строки/ширины/плавающие места — по снимку, потом сверка (verify).
    Размеры окон в стопке помнятся (state/stack-geom.json) до следующего входа.
  * полосы рисует daemon: прозрачный слой TOP на рабочей области монитора, над каждым
    окном — полоса по стилю системы (Default/Skeet/Beta). Перекрытие — по очереди
    фокуса (niri поднимает плавающее окно при фокусе). Свернуть — окно уходит на
    скрытый стол «свёрнутые» своего монитора (имя-значок MIN_NAME, у второго монитора
    с невидимым WJ в конце — niri не даёт двух столов с одним именем), его кнопка
    остаётся на нижней панели; щелчок по ней или Alt+Tab возвращает.
  * анимации: niri двигает плавающие окна пружиной (окно догоняет цель 0,2–0,4 с, а
    IPC сразу отдаёт конечное место — полоса бы отрывалась от окна). Пока стопка
    включена, анимации перемещения и размера выключены (cfg/stack-mode.kdl, перечитка
    конфига 4 мс); выход возвращает их.

Факты niri 26.04, проверены пробным окном 20.10.2026: move-floating-window SetFixed
считается от рабочей области (на ноутбуке её верх — 44 px), IPC tile_pos — от угла
экрана и сразу конечный (без анимации); размеры SetFixed — окно без рамки; 100 % —
плитка ровно на рабочую область; вправо/вниз niri оставляет на экране 75 px, влево и
вверх не ограничивает; плавающее место переживает переезд на другой стол.
"""
import glob
import json
import os
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
POCKET = "\uf2c6"                    # карман (scripts/magic, workspaces.kdl): не стол стопки, но окна его — в стопку
STATE = os.path.expanduser("~/.config/hypr/state/stack-mode.json")
GEOM = os.path.expanduser("~/.config/hypr/state/stack-geom.json")
KDL = os.path.expanduser("~/.config/niri/cfg/stack-mode.kdl")
STYLE_FILE = os.path.expanduser("~/.config/hypr/state/system-style")
LOG = os.path.expanduser("~/.cache/stack_mode.log")
# STACK_TEST=1 — проба: стопка видит только окна jv-stacktest, своё состояние в ~/.cache
TEST = os.environ.get("STACK_TEST") == "1"
if TEST:
    STATE = os.path.expanduser("~/.cache/stack-test-state.json")
    GEOM = os.path.expanduser("~/.cache/stack-test-geom.json")
MIN_NAME = "\U000f05b0"              # md-window-minimize: стол свёрнутых окон
WJ = "\u2060"                        # word joiner: свёрнутые второго монитора — MIN_NAME + WJ
HIDDEN_APPS = ("dash-", "jv-stacktest")
# 21.10.2026: −4 px во всех стилях (просьба: «чуть уменьшить эту верхнюю линию… более компактнее,
# а три кнопки справа не трогать» — кнопки задаёт close_cap.CAP, они прежние)
# ещё −4 (21.10.2026, «верхнюю часть окон ещё компактнее»): Skeet 20 (кнопки 14), Default 22 (16);
# Beta 22 — её кнопкам 18 px ниже тесно
BAR_H = {"default": 22, "skeet": 20, "beta": 22}
# Своя рамка окна (рисует stack_bars) — с 21.10.2026 и у развёрнутых (просьба: «добавляй»).
FRAME = {"default": 3, "skeet": 6, "beta": 1}
ZW = "​"                        # имена столов с ним ставит niri_bar.py сам
WSL = [os.path.expanduser("~/.config/hypr/state/" + n) for n in
       ("ws-layout.json", "ws-layout-floated.json", "ws-layout-order.json",
        "ws-view.json", "ws-view-widths.json")]
KDL_BASE = """// Пишет ~/.config/hypr/scripts/stack_mode.py (режим «стопка», Ctrl+Shift+Super+M).
// Пробные окна самопроверки: открываются плавающими, jv-stacktest — на ноутбуке,
// jv-stacktest-msi — на MSI.
window-rule {
    match app-id="^jv-stacktest$"
    open-on-output "eDP-1"
    open-floating true
    open-focused false
}
window-rule {
    match app-id="^jv-stacktest-msi$"
    open-on-output "DP-4"
    open-floating true
    open-focused false
}
"""
KDL_STACK = """// Стопка включена: окна встают и тянутся без пружины, полоса заголовка не отстаёт.
animations {
    window-movement { off; }
    window-resize { off; }
}
// Рамку окна вместе с полосой заголовка рисует stack_bars.py по стилю системы (21.10.2026,
// Просьба: «рамки у окон в режиме stack mode убрать вообще и нарисовать свои, в стиле skeet»).
window-rule {
    // и у записываемых: красная рамка записи легла бы вокруг окна «поверх всех» (его зеркало —
    // запись окна, stack_pin.py); что идёт запись, видно по индикатору «экран» в баре
    match is-floating=true
    border { off; }
    focus-ring { off; }
    shadow { off; }
    geometry-corner-radius 0
}
"""


def log(*a):
    try:
        with open(LOG, "a") as f:
            f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except OSError:
        pass


# ── niri ──────────────────────────────────────────────────────────────────────
def sock_path():
    p = os.environ.get("NIRI_SOCKET")
    if p and os.path.exists(p):
        return p
    c = sorted(glob.glob("/run/user/%d/niri.wayland-*.sock" % os.getuid()))
    if c:
        os.environ["NIRI_SOCKET"] = c[0]
        return c[0]
    return None


def req(obj):
    try:
        s = socket.socket(socket.AF_UNIX)
        s.settimeout(3)
        s.connect(sock_path())
        s.sendall(json.dumps(obj).encode() + b"\n")
        line = s.makefile().readline()
        s.close()
        return json.loads(line or "{}")
    except (OSError, TypeError, ValueError) as e:
        return {"Err": str(e)}


def A(_act, **kw):
    r = req({"Action": {_act: kw}})
    if "Err" in r:
        log("niri", _act, kw, r["Err"])
    return r


def get(kind):
    return (req(kind).get("Ok") or {}).get(kind)


def query():
    return get("Workspaces") or [], get("Windows") or []


def hidden(w):
    a = w.get("app_id") or ""
    return not a.startswith("jv-stacktest") if TEST else a.startswith(HIDDEN_APPS)


def lay(w):
    return w.get("layout") or {}


def wsize(w):
    return list(lay(w).get("window_size") or [0, 0])


def tpos(w):
    p = lay(w).get("tile_pos_in_workspace_view")
    return list(p) if p else None


def colrow(w):
    p = lay(w).get("pos_in_scrolling_layout")
    return list(p) if p else None


def border(w):
    return int((lay(w).get("window_offset_in_tile") or [0, 0])[0])


def ts(w):
    t = w.get("focus_timestamp") or {}
    return t.get("secs", 0) + t.get("nanos", 0) / 1e9


def desks(wss, out):
    return sorted([d for d in wss if d.get("output") == out], key=lambda d: d["idx"])


def outputs(wss):
    """Мониторы со столами: ноутбук первым (у него MIN_NAME без WJ)."""
    return sorted({d["output"] for d in wss if d.get("output")}, key=lambda o: (o != "eDP-1", o))


def output_size(out):
    o = ((get("Outputs") or {}).get(out) or {}).get("logical") or {}
    return int(o.get("width", 1920)), int(o.get("height", 1080))


def is_min_name(name):
    return bool(name) and name.rstrip(WJ) == MIN_NAME


def min_desk(wss, out):
    return next((d for d in desks(wss, out) if is_min_name(d.get("name"))), None)


def stack_desk_of(ds):
    """Общий стол монитора: первый, кроме кармана и стола свёрнутых."""
    return next((d for d in ds if d.get("name") != POCKET and not is_min_name(d.get("name"))), None)


def desk_out(wss):
    return {d["id"]: d.get("output") for d in wss}


def tail_desk(wss, wins, out):
    """Пустой безымянный стол в конце монитора (niri держит его всегда)."""
    busy = {w.get("workspace_id") for w in wins}
    for d in reversed(desks(wss, out)):
        if d["id"] not in busy and not d.get("name"):
            return d["id"]
    return None


def pomo_locked():
    try:
        sys.path.insert(0, HERE)
        import pomo_lock
        return pomo_lock.locked() is not None
    except Exception:
        return False


def notify(text):
    subprocess.Popen(["notify-send", "-a", "Стопка", "-t", "2500", "Стопка окон", text],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def style(out):
    try:
        v = json.load(open(STYLE_FILE)).get(out)
    except (OSError, ValueError, AttributeError):
        v = None
    return v if v in BAR_H else "default"


def bar_h(out):
    return BAR_H[style(out)]


# ── файлы ─────────────────────────────────────────────────────────────────────
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
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)


def session():
    p = sock_path()
    return os.path.basename(p) if p else ""


def load_state():
    return _load(STATE)


def active(st=None):
    st = load_state() if st is None else st
    return bool(st.get("active")) and st.get("socket") == session()


def load_geom():
    g = _load(GEOM)
    if g.get("socket") != session():            # окна живут до выхода из niri
        g = {"socket": session(), "app": g.get("app") or {}, "win": {}}
    g.setdefault("app", {})
    g.setdefault("win", {})
    return g


def set_anim(stack):
    """Анимации перемещения и размера: выключены, пока стопка включена."""
    text = KDL_BASE + (KDL_STACK if stack else "")
    try:
        if open(KDL).read() == text:
            return
    except OSError:
        pass
    with open(KDL + ".tmp", "w") as f:
        f.write(text)
    os.replace(KDL + ".tmp", KDL)
    A("LoadConfigFile")


# ── снимок ────────────────────────────────────────────────────────────────────
def take_snapshot(wss, wins):
    outs = outputs(wss)
    size = {o: output_size(o) for o in outs}
    dout = desk_out(wss)
    rows = []
    for w in wins:
        ws = w.get("workspace_id")
        if ws not in dout or hidden(w):
            continue
        cr = colrow(w)
        out = dout[ws]
        rows.append({"id": w["id"], "app_id": w.get("app_id"), "title": w.get("title"),
                     "ws": ws, "out": out, "floating": bool(w.get("is_floating")),
                     "col": cr[0] if cr else None, "row": cr[1] if cr else None,
                     "size": wsize(w), "tile": list(lay(w).get("tile_size") or [0, 0]),
                     "pos": tpos(w), "fullscreen": wsize(w) == list(size[out])})
    tabbed = []
    for d in wss:
        cols = {}
        for r in rows:
            if r["ws"] == d["id"] and not r["floating"]:
                cols.setdefault(r["col"], []).append(r["tile"][1])
        for c, hs in cols.items():
            # вкладки: каждая во всю высоту, вместе выше экрана
            if len(hs) > 1 and sum(hs) > size[d["output"]][1]:
                tabbed.append([d["id"], c])
    sids = {str(d["id"]) for d in wss}
    return {"t": time.time(),
            "desks": [{k: d.get(k) for k in ("id", "idx", "name", "output", "is_active", "active_window_id")}
                      for o in outs for d in desks(wss, o)],
            "windows": rows, "tabbed": tabbed,
            "focused_output": next((d["output"] for d in wss if d.get("is_focused")), None),
            "focused": next((w["id"] for w in wins if w.get("is_focused")), None),
            "ws_layout": {p: {k: v for k, v in _load(p).items() if str(k) in sids} for p in WSL}}


def columns(wins, ws_id, only=None):
    """[[id, …], …] колонки стола слева направо, окна в колонке сверху вниз."""
    cols = {}
    for w in wins:
        if w.get("workspace_id") != ws_id or w.get("is_floating") or not colrow(w):
            continue
        if only is not None and w["id"] not in only:
            continue
        c, r = colrow(w)
        cols.setdefault(c, []).append((r, w["id"]))
    return [[i for _r, i in sorted(v)] for _c, v in sorted(cols.items())]


def snap_columns(rows):
    cols = {}
    for r in rows:
        if not r["floating"]:
            cols.setdefault(r["col"], []).append((r["row"], r["id"]))
    return [[i for _r, i in sorted(v)] for _c, v in sorted(cols.items())]


# ── места в стопке ────────────────────────────────────────────────────────────
def place(wid, x, y, w, h):
    """x, y — от угла рабочей области (как SetFixed), w, h — окно без рамки."""
    A("SetWindowWidth", id=wid, change={"SetFixed": int(w)})
    A("SetWindowHeight", id=wid, change={"SetFixed": int(h)})
    A("MoveFloatingWindow", id=wid, x={"SetFixed": int(x)}, y={"SetFixed": int(y)})


def so(st, out):
    """Стопка монитора: {desk, offset, work}."""
    return (st.get("outs") or {}).get(out) or {}


def offset(st, out):
    return so(st, out).get("offset") or [0, 44]


def work(st, out):
    ow, oh = output_size(out)
    ox, oy = offset(st, out)
    return so(st, out).get("work") or [ow - ox, oh - oy]


def geom_of(w, st, out):
    """[x, y, w, h] окна в координатах place()."""
    p = tpos(w) or [0, 0]
    ox, oy = offset(st, out)
    return [int(p[0] - ox), int(p[1] - oy)] + wsize(w)


def default_geom(app_id, size, k, st, geo, out, taken=()):
    """Новое окно — по центру рабочей области вместе со своей полосой; занято (taken — углы
    окон стола) или k-е при включении стопки — каскадом +32 вниз-вправо, как в Windows
    (21.10.2026, просьба: «окна открываются слева сверху, пусть по центру, как в Windows»)."""
    ww, wh = work(st, out)
    a = geo["app"].get(app_id or "")
    w, h = a if a else (min(size[0] or 900, int(ww * 0.6)), min(size[1] or 600, int(wh * 0.66)))
    bh = bar_h(out)
    x0, y0 = max(8, (ww - w) // 2), max(bh + 8, (wh - h - bh) // 2 + bh)
    x, y = x0 + 32 * (k % 10), y0 + 32 * (k % 10)
    for _ in range(10):
        if not any(abs(x - tx) < 16 and abs(y - ty) < 16 for tx, ty in taken):
            break
        x, y = x + 32, y + 32
    if x + w > ww - 8 or y + h > wh - 8:     # каскад упёрся в край — назад к центру со сдвигом
        x, y = x0 - 32, y0 - 32 if y0 - 32 >= bh + 8 else y0
    return [max(8, x), max(bh + 8, y), w, h]


def float_into_stack(w, st, geo, k, out, avoid=False):
    """Окно — плавающим на общий стол своего монитора, на прошлое место или по центру
    (avoid — обойти углы окон, что уже стоят на столе: новое окно при живой стопке)."""
    wid, S = w["id"], so(st, out)["desk"]
    taken = ()
    if avoid and str(wid) not in geo["win"]:
        taken = [geom_of(x, st, out)[:2] for x in query()[1] if x["id"] != wid
                 and x.get("workspace_id") == S and x.get("is_floating") and tpos(x)]
        k = 0
    if w.get("workspace_id") != S:
        A("MoveWindowToWorkspace", window_id=wid, reference={"Id": S},
          focus=bool(w.get("is_focused")))
    if not w.get("is_floating"):
        A("MoveWindowToFloating", id=wid)
    g = geo["win"].get(str(wid)) or default_geom(w.get("app_id"), wsize(w), k, st, geo, out, taken)
    place(wid, *g)


def window_out(wid, wss=None, wins=None):
    if wss is None or wins is None:
        wss, wins = query()
    w = next((x for x in wins if x["id"] == wid), None)
    return w, (desk_out(wss).get(w.get("workspace_id")) if w else None)


# ── вход ──────────────────────────────────────────────────────────────────────
def turn_on():
    st = load_state()
    if active(st):
        notify("Уже включена")
        return 0
    if pomo_locked():
        notify("Идёт помидор — столы заперты, стопка не включается")
        return 1
    wss, wins = query()
    old = st.get("outs") or {}
    if "eDP-1" not in old and st.get("offset"):          # состояние до 21.10 — только ноутбук
        old = {"eDP-1": {"offset": st.get("offset"), "work": st.get("work")}}
    outs = {}
    for o in outputs(wss):
        d = stack_desk_of(desks(wss, o))
        if d:
            outs[o] = {"desk": d["id"], "offset": (old.get(o) or {}).get("offset"),
                       "work": (old.get(o) or {}).get("work")}
    if not outs:
        notify("Мониторы не найдены")
        return 1
    snap = take_snapshot(wss, wins)
    snap["windows"] = [r for r in snap["windows"] if r["out"] in outs]
    st = {"active": True, "socket": session(), "outs": outs, "snap": snap,
          "max": {}, "min": {}, "t": time.time()}
    _save(STATE, st)                     # снимок — до первого движения
    set_anim(True)
    log("on: окон", len(snap["windows"]), "столы стопки", {o: v["desk"] for o, v in outs.items()})
    geo = load_geom()
    idx = {d["id"]: d["idx"] for d in wss}
    order = sorted(snap["windows"], key=lambda r: (
        r["out"], idx.get(r["ws"], 0), r["floating"], r["col"] or 0, r["row"] or 0))
    cur = {w["id"]: w for w in wins}
    k, calib = {}, {}
    for r in order:
        o, S = r["out"], outs[r["out"]]["desk"]
        if r["floating"]:                # плавающее — остаётся на своём месте экрана
            if r["ws"] != S:
                A("MoveWindowToWorkspace", window_id=r["id"], reference={"Id": S}, focus=False)
            continue
        if r["fullscreen"]:
            A("FullscreenWindow", id=r["id"])           # из полноэкранного — в окно
        float_into_stack(dict(cur[r["id"]], is_focused=False), st, geo, k.get(o, 0), o)
        if str(r["id"]) not in geo["win"]:
            k[o] = k.get(o, 0) + 1
        calib.setdefault(o, r["id"])
    if calib:                            # где SetFixed(0, 0) на самом деле — у каждого монитора
        _w, wins2 = query()
        for o, wid in calib.items():
            w2 = next((x for x in wins2 if x["id"] == wid), None)
            if not (w2 and tpos(w2)):
                continue
            g = geo["win"].get(str(wid))
            want = g[:2] if g else default_geom(w2.get("app_id"), wsize(w2), 0, st, geo, o)[:2]
            p = tpos(w2)
            outs[o]["offset"] = [int(p[0] - want[0]), int(p[1] - want[1])]
        _save(STATE, st)
    hid = resume(geo, cur, outs)
    fo = snap["focused_output"]
    for o in sorted(outs, key=lambda o: o == fo):      # монитор фокуса — последним
        A("FocusWorkspace", reference={"Id": outs[o]["desk"]})
    if snap["focused"] and snap["focused"] not in hid:
        A("FocusWindow", id=snap["focused"])
    elif fo:
        A("FocusMonitor", output=fo)
    start_daemon()
    panel(True)
    top_hover(True)
    zen_buttons(True)
    csd_buttons(True)
    app_buttons(True)
    ym_buttons()
    notify("Включена: окон %d, мониторов %d" % (len(snap["windows"]), len(outs)))
    return 0


def xpbar_layer(out):
    return any(l.get("output") == out and l.get("namespace") == "jarvis-xpbar"
               for l in get("Layers") or [])


def panel(on):
    """Нижняя панель на время стопки (там кнопки свёрнутых окон) — на каждом мониторе
    стопки. Где её нет (Панели по мониторам: «нет»), panels.py показывает её, пока монитор
    в st["panel"]; выход убирает и ждёт, пока рабочая область вернётся, — до раскладки по
    снимку."""
    if TEST:
        return
    st = load_state()
    if on:
        sys.path.insert(0, HERE)
        import panels
        need = [o for o in st.get("outs") or {} if panels.bottom_for(o) not in ("always", "hover")]
        if not need:
            return
        st["panel"] = need
        _save(STATE, st)
        subprocess.Popen([sys.executable, os.path.join(HERE, "panels.py"), "apply", "bottom"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    need = st.pop("panel", None)
    if not need:
        return
    if need is True:                     # состояние до 21.10
        need = ["eDP-1"]
    _save(STATE, st)
    subprocess.run([sys.executable, os.path.join(HERE, "panels.py"), "apply", "bottom"],
                   capture_output=True, timeout=60)
    for _ in range(40):
        if not any(xpbar_layer(o) for o in need):
            break
        time.sleep(0.05)
    time.sleep(0.15)                     # niri пересчитал рабочую область


ZEN_UI = os.path.expanduser("~/.config/zen-jarvis/zen-ui.css")
ZEN_BEGIN = "/* ZEN-STACK BEGIN — пишет stack_mode.py, руками не править */"
ZEN_END = "/* ZEN-STACK END */"


def zen_buttons(hide):
    """Кнопки окна Zen (свернуть/развернуть/закрыть) в стопке не нужны — они есть в полосе
    stack_bars (21.10.2026, просьба: «не нужны и вот эти кнопки в браузере»). zen-ui.css
    live-theme.js перечитывает на лету, перезапуск Zen не нужен."""
    try:
        text = open(ZEN_UI, encoding="utf-8").read()
    except OSError:
        return
    i = text.find(ZEN_BEGIN)
    if i >= 0:
        j = text.find(ZEN_END, i)
        tail = text[j + len(ZEN_END):] if j >= 0 else ""
        new = text[:i].rstrip("\n") + "\n" + tail.lstrip("\n")
    else:
        new = text
    if hide:
        new = new.rstrip("\n") + "\n\n%s\n.titlebar-buttonbox-container { display: none !important; }\n%s\n" % (
            ZEN_BEGIN, ZEN_END)
    if new != text:
        with open(ZEN_UI + ".tmp", "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(ZEN_UI + ".tmp", ZEN_UI)


def css_block(path, begin, end, css):
    """Свой блок между begin и end в конце CSS-файла: css — вписать, None — убрать."""
    try:
        text = open(path, encoding="utf-8").read()
    except FileNotFoundError:
        text = ""
    except OSError:
        return
    i = text.find(begin)
    if i >= 0:
        j = text.find(end, i)
        tail = text[j + len(end):] if j >= 0 else ""
        new = text[:i].rstrip("\n") + ("\n" if text[:i].strip() else "") + tail.lstrip("\n")
    else:
        new = text
    if css:
        new = (new.rstrip("\n") + "\n\n" if new.strip() else "") + "%s\n%s\n%s\n" % (begin, css, end)
    if new != text:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.write(new)
        os.replace(path + ".tmp", path)


VSCODE_SETTINGS = os.path.expanduser("~/.config/Code/User/settings.json")
VENCORD_CSS = os.path.expanduser("~/.config/Vencord/settings/quickCss.css")
OBSIDIAN_VAULT = os.path.expanduser("~/Documents/PersonalOS/.obsidian")
OBSIDIAN_SNIPPET = "stack-buttons"
STEAM_CSS = [os.path.expanduser("~/.local/share/Steam/millennium/themes/" + p) for p in
             ("JarvisPixel/libraryroot.custom.css", "SpaceTheme/src/css/libraryroot.custom.css")]
APP_BEGIN = "/* STACK-BUTTONS BEGIN — пишет stack_mode.py, руками не править */"
APP_END = "/* STACK-BUTTONS END */"


def app_buttons(hide):
    """Свои кнопки окна у Electron-программ — в стопке лишние, они есть в полосе
    (21.10.2026, просьба: «в vscode тоже дублируются кнопки… пройдись по приложениям»).
    Discord (quickCss Vencord) и Obsidian (сниппет) перечитывают CSS на лету; VS Code —
    window.controlsStyle, сам просит перезапуск. Telegram — csd_buttons, Zen — zen_buttons,
    Яндекс Музыка — ym_buttons. Steam — CSS тем Millennium (STEAM_CSS), подхватит после
    перезапуска Steam; значок Big Picture не трогаем — в полосе его нет. Postman — настройки нет."""
    if TEST:
        return
    for path in STEAM_CSS:
        if os.path.isfile(path):
            css_block(path, APP_BEGIN, APP_END,
                      ".title-area .title-area-icon.minimizeButton, .title-area .title-area-icon.maximizeButton,"
                      " .title-area .title-area-icon.closeButton { display: none !important; }" if hide else None)
    css_block(VENCORD_CSS, APP_BEGIN, APP_END,
              '[class^="winButtons_"], [class^="winButton_"] { display: none !important; }' if hide else None)
    if os.path.isdir(OBSIDIAN_VAULT):
        snip = os.path.join(OBSIDIAN_VAULT, "snippets", OBSIDIAN_SNIPPET + ".css")
        os.makedirs(os.path.dirname(snip), exist_ok=True)
        css_block(snip, APP_BEGIN, APP_END,
                  ".titlebar-button-container.mod-right { display: none !important; }" if hide else None)
        app = os.path.join(OBSIDIAN_VAULT, "appearance.json")
        try:
            d = json.load(open(app, encoding="utf-8"))
            if OBSIDIAN_SNIPPET not in d.setdefault("enabledCssSnippets", []):
                d["enabledCssSnippets"].append(OBSIDIAN_SNIPPET)    # раз навсегда; включает и выключает содержимое
                with open(app + ".tmp", "w", encoding="utf-8") as f:
                    json.dump(d, f, ensure_ascii=False, indent=2)
                os.replace(app + ".tmp", app)
        except (OSError, ValueError) as e:
            log("obsidian appearance.json", e)
    try:
        d = json.load(open(VSCODE_SETTINGS, encoding="utf-8"))
    except FileNotFoundError:
        return
    except (OSError, ValueError) as e:                  # комментарии в settings.json — не трогаем
        log("vscode settings.json", e)
        return
    if (d.get("window.controlsStyle") == "hidden") != hide:
        if hide:
            d["window.controlsStyle"] = "hidden"
        else:
            d.pop("window.controlsStyle", None)
        with open(VSCODE_SETTINGS + ".tmp", "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=4)
        os.replace(VSCODE_SETTINGS + ".tmp", VSCODE_SETTINGS)


def ym_buttons():
    """Кнопки окна Яндекс Музыки (Electron, рисует их сама) — ym_tweaks.py сам читает
    режим из состояния и прячет или возвращает их в открытом окне (21.10.2026)."""
    if TEST:
        return
    subprocess.Popen([sys.executable, os.path.join(HERE, "ym_tweaks.py")],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


CSD_KEY = ("org.gnome.desktop.wm.preferences", "button-layout")
CSD_SAVED = os.path.expanduser("~/.config/hypr/state/stack-button-layout")


def csd_buttons(hide):
    """Свои кнопки окна у Telegram (окно просмотра медиа) и других программ, что рисуют их
    сами, — в стопке лишние (21.10.2026, просьба: «здесь тоже дублируются кнопки»). Telegram
    (lib_ui) берёт набор из button-layout через портал и следит за ним на лету; пустая правая
    часть — кнопок нет. Прежнее значение — в CSD_SAVED, выход возвращает его."""
    if TEST:
        return
    cur = subprocess.run(["gsettings", "get", *CSD_KEY], capture_output=True, text=True).stdout.strip()
    if hide:
        if not os.path.exists(CSD_SAVED) and cur:
            with open(CSD_SAVED, "w", encoding="utf-8") as f:
                f.write(cur.strip("'"))
        subprocess.run(["gsettings", "set", *CSD_KEY, "icon:"])
        return
    try:
        old = open(CSD_SAVED, encoding="utf-8").read().strip()
    except OSError:
        return
    subprocess.run(["gsettings", "set", *CSD_KEY, old or "icon:minimize,maximize,close"])
    os.remove(CSD_SAVED)


# Верхний бар в стопке (21.10.2026, просьба: «можно как вариант заменить ею [Minimalistic]
# waybar, но режим также останется При наведении. Это только в stack mode такая настройка
# будет»): waybar — обычный бар; capsule — капсула по центру (время, Wi-Fi, батарея, без
# точек столов: стол в стопке один). Собирает waybar_niri.py по panels.stack_capsule().
TOP_BAR_FILE = os.path.expanduser("~/.config/hypr/state/stack-top-bar")


def top_bar_kind():
    try:
        k = open(TOP_BAR_FILE).read().strip()
    except OSError:
        return "waybar"
    return k if k in ("waybar", "capsule") else "waybar"


def set_top_bar_kind(kind):
    with open(TOP_BAR_FILE + ".tmp", "w") as f:
        f.write(kind + "\n")
    os.replace(TOP_BAR_FILE + ".tmp", TOP_BAR_FILE)
    st = load_state()
    if not active(st) or TEST or bool(st.get("capsule")) == (kind == "capsule"):
        return
    st["capsule"] = kind == "capsule"
    _save(STATE, st)
    subprocess.Popen([sys.executable, os.path.join(HERE, "panels.py"), "apply", "top"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def top_swap(frm, to):
    """Режим верхнего бара frm → to на всех мониторах (panels.json) или в общем (state/top-bar);
    без применения."""
    import panels
    d = panels.load()
    if panels.per_monitor(d):
        for out in panels.top_outputs(d):
            if (d["mon"].get(out) or {}).get("top", panels.global_top()) == frm:
                panels.set_value(out, "top", to)
    elif panels.global_top() == frm:
        with open(panels.TOP_FILE + ".tmp", "w") as f:
            f.write(to + "\n")
        os.replace(panels.TOP_FILE + ".tmp", panels.TOP_FILE)


def top_hover(on):
    """Верхний бар на время стопки: остаётся как был, но без столов — в стопке все окна на
    одном столе, переход на другой её ломает (22.10.2026, просьба: «можно оставить бар если
    он там был, но убрать столы»; 21.10 «всегда» уходил в «при наведении»). Мониторы, где
    столы убираются на всех мониторах (panels.stack_top); выбор в panels.json не трогается —
    его можно менять и в стопке (Настройки → «Показ панелей»). Выход возвращает
    столы и ждёт бар, пока рабочая область вернётся, — до раскладки по снимку."""
    if TEST:
        return
    st = load_state()
    sys.path.insert(0, HERE)
    import panels
    # Вход в стопку: «всегда» → «при наведении», выход: «при наведении» → «всегда»; это
    # обычный выбор в Настройках, его можно сменить и в стопке, «выключен» не трогается
    # (22.10.2026, просьба: «при переключении на stack mode пусть бар сверху становится При
    # наведении по умолчанию, а если обратно в scroll mode то на Всегда»)
    top_swap(*(("always", "hover") if on else ("hover", "always")))
    if on:
        st["capsule"] = top_bar_kind() == "capsule"
        _save(STATE, st)
        subprocess.Popen([sys.executable, os.path.join(HERE, "panels.py"), "apply", "top"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    for k in ("top_desks", "top_hover", "capsule"):   # top_desks/top_hover — ключи до 22.10
        st.pop(k, None)
    # «active» снимется позже, в конце turn_off, — без отметки бар собрался бы снова без
    # столов (22.10.2026: стопку выключили, а столы наверху так и не вернулись)
    st["top_off"] = True
    _save(STATE, st)                     # apply ниже перезапускает только изменённые бары
    subprocess.run([sys.executable, os.path.join(HERE, "panels.py"), "apply", "top"],
                   capture_output=True, timeout=60)
    need = [o for o in st.get("outs") or {} if panels.top_for(o) == "always"]  # место — только «всегда»
    for _ in range(60):                  # бар снова резервирует место
        if all(any(l.get("output") == o and l.get("namespace") == "tb-always" for l in get("Layers") or [])
               for o in need):
            break
        time.sleep(0.05)
    time.sleep(0.4)                      # niri пересчитал рабочую область


def start_daemon():
    stop_daemon()
    with open(LOG, "a") as lf:
        p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "daemon"],
                             stdout=lf, stderr=lf, stdin=subprocess.DEVNULL,
                             start_new_session=True)
    st = load_state()
    st["daemon"] = p.pid
    _save(STATE, st)


def daemon_pids():
    out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,args="],
                         capture_output=True, text=True).stdout
    me = os.getpid()
    pids = []
    for line in out.splitlines():
        pid, _s, args = line.strip().partition(" ")
        if args.rstrip().endswith("stack_mode.py daemon") and int(pid) != me:
            pids.append(int(pid))
    return pids


def anim_request(cmd, wid):
    """Свернуть/вернуть через демон полос — с полётом к кнопке панели (stack_bars.Ghost).
    Демона нет — False, делать самим."""
    pids = daemon_pids()
    if not pids:
        return False
    try:
        with open(os.path.expanduser("~/.cache/stack-anim-req"), "a") as f:
            f.write("%s %d\n" % (cmd, wid))
        os.kill(pids[0], signal.SIGUSR2)
    except OSError:
        return False
    return True


def stop_daemon():
    for pid in daemon_pids():
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    for _ in range(20):
        if not daemon_pids():
            break
        time.sleep(0.05)


# ── выход ─────────────────────────────────────────────────────────────────────
def remember(st, wss, wins):
    """Размеры и места окон в стопке — на следующий вход."""
    geo = load_geom()
    snapf = {r["id"] for r in st["snap"]["windows"] if r["floating"]}
    dout = desk_out(wss)
    mins = {d["id"] for d in wss if is_min_name(d.get("name"))}
    for w in wins:
        if hidden(w) or w["id"] in snapf:
            continue
        key, ws = str(w["id"]), w.get("workspace_id")
        o = dout.get(ws)
        if o in (st.get("outs") or {}) and ws == so(st, o)["desk"] and w.get("is_floating"):
            g = st.get("max", {}).get(key) or geom_of(w, st, o)
        elif ws in mins:
            g = st.get("min", {}).get(key)
        else:
            continue
        if g:
            geo["win"][key] = g
            if w.get("app_id"):
                geo["app"][w["app_id"]] = g[2:]
    # что было свёрнуто и развёрнуто — тоже на следующий вход (21.10.2026, просьба: «пусть
    # запоминает также были ли свёрнуты окна, какие были свёрнуты и т.д.»). Свёрнутые — в
    # порядке сворачивания (Super+K возвращает последнее).
    have = {w["id"] for w in wins if w.get("workspace_id") in mins}
    order = [k for k in (st.get("min") or {}) if int(k) in have]
    order += [str(i) for i in sorted(have) if str(i) not in order]
    geo["last"] = {"min": order,
                   "max": {k: g for k, g in (st.get("max") or {}).items()
                           if any(w["id"] == int(k) for w in wins)}}
    _save(GEOM, geo)


def resume(geo, cur, outs):
    """Вход: вернуть свёрнутое и развёрнутое прошлой стопки (remember → geo["last"])."""
    last = geo.get("last") or {}
    if not last:
        return []
    wss, wins = query()
    dout = desk_out(wss)
    out_of = {w["id"]: dout.get(w.get("workspace_id")) for w in wins if w["id"] in cur}
    for key, g in (last.get("max") or {}).items():
        if out_of.get(int(key)) in outs:
            toggle_max(int(key), g)
    done = []
    for key in last.get("min") or []:
        if out_of.get(int(key)) in outs:
            minimize(int(key))
            done.append(int(key))
    return done


def turn_off():
    st = load_state()
    if not active(st):
        notify("Уже выключена")
        return 0
    stop_daemon()
    panel(False)
    top_hover(False)
    zen_buttons(False)
    csd_buttons(False)
    app_buttons(False)
    st = load_state()
    wss, wins = query()
    remember(st, wss, wins)
    for o, v in (st.get("outs") or {}).items():
        M = min_desk(wss, o)
        if not M:
            continue
        for w in wins:
            if w.get("workspace_id") == M["id"]:
                A("MoveWindowToWorkspace", window_id=w["id"], reference={"Id": v["desk"]}, focus=False)
        A("UnsetWorkspaceName", reference={"Id": M["id"]})
    for key, g in (st.get("max") or {}).items():         # развёрнутые — обратно (снимок их не знает)
        place(int(key), *g)
    st["active"] = False
    st["max"], st["min"] = {}, {}
    _save(STATE, st)
    ym_buttons()                         # состояние уже «выключено» — кнопки вернутся
    restore(st)
    set_anim(False)
    diffs, gone = verify(st["snap"])
    log("off: расхождений", len(diffs), "закрыто окон", gone, *diffs)
    notify("Выключена, всё на местах" if not diffs else
           "Выключена; не сошлось: %d (stack_mode.py verify)" % len(diffs))
    return 0


def restore(st):
    snap = st["snap"]
    wss, wins = query()
    cur = {w["id"]: w for w in wins}
    live = {d["id"] for d in wss}
    louts = outputs(wss)
    rows = [r for r in snap["windows"] if r["id"] in cur]
    odesks = sorted(snap["desks"], key=lambda d: (d.get("output") or "", d["idx"]))
    idmap = {d["id"]: d["id"] for d in odesks if d["id"] in live}

    def home(d):                         # монитор стола; отключённый — первый живой
        return d.get("output") if d.get("output") in louts else (louts[0] if louts else None)

    # 1) по столам: исчезнувший стол — новый в конце своего монитора, окна в том же порядке
    for d in odesks:
        rs = [r for r in rows if r["ws"] == d["id"]]
        if not rs:
            continue
        if d["id"] not in idmap:
            wss, wins = query()
            t = tail_desk(wss, wins, home(d))
            if t is None:
                log("restore: нет пустого стола для", d["id"])
                continue
            idmap[d["id"]] = t
            if d.get("name") and ZW not in d["name"]:
                A("SetWorkspaceName", name=d["name"], workspace={"Id": t})
        T = idmap[d["id"]]
        tiled = sorted([r for r in rs if not r["floating"]], key=lambda r: (r["col"], r["row"]))
        for r in tiled:
            if cur[r["id"]].get("workspace_id") != T:
                A("MoveWindowToWorkspace", window_id=r["id"], reference={"Id": T}, focus=False)
            A("MoveWindowToTiling", id=r["id"])
        for r in rs:
            if r["floating"]:
                if cur[r["id"]].get("workspace_id") != T:
                    A("MoveWindowToWorkspace", window_id=r["id"], reference={"Id": T}, focus=False)
                if not cur[r["id"]].get("is_floating"):
                    A("MoveWindowToFloating", id=r["id"])
        # строки: окно под первым в колонке — в его колонку
        for col in snap_columns(rs):
            for wid in col[1:]:
                A("ConsumeOrExpelWindowLeft", id=wid)
        fix_columns(T, rs)
    # 2) окна, открытые в стопке, — на новый стол в конце своего монитора (столы снимка не трогаем)
    snap_ids = {r["id"] for r in snap["windows"]}
    for o, v in (st.get("outs") or {}).items():
        wss, wins = query()
        extra = [w for w in wins if w.get("workspace_id") == v["desk"] and w["id"] not in snap_ids
                 and not hidden(w)]
        if not extra:
            continue
        t = tail_desk(wss, wins, o)
        for w in extra:
            A("MoveWindowToWorkspace", window_id=w["id"], reference={"Id": t}, focus=False)
            A("MoveWindowToTiling", id=w["id"])
    # 3) ширины, высоты, вкладки, полный экран, плавающие места
    for _round in range(2):
        _wss, wins = query()
        cur = {w["id"]: w for w in wins}
        for r in rows:
            w = cur.get(r["id"])
            if not w:
                continue
            got = wsize(w)
            if r["floating"]:
                if any(abs(got[i] - r["size"][i]) > 1 for i in (0, 1)):
                    A("SetWindowWidth", id=r["id"], change={"SetFixed": r["size"][0]})
                    A("SetWindowHeight", id=r["id"], change={"SetFixed": r["size"][1]})
                p = tpos(w)
                if p and r["pos"] and (abs(p[0] - r["pos"][0]) > 0.5 or abs(p[1] - r["pos"][1]) > 0.5):
                    A("MoveFloatingWindow", id=r["id"], x={"AdjustFixed": r["pos"][0] - p[0]},
                      y={"AdjustFixed": r["pos"][1] - p[1]})
                continue
            if r["fullscreen"]:
                continue
            if abs(got[0] - r["size"][0]) > 1:
                A("SetWindowWidth", id=r["id"], change={"SetFixed": r["size"][0]})
            col = [x for x in rows if not x["floating"] and x["ws"] == r["ws"] and x["col"] == r["col"]]
            tab = [r["ws"], r["col"]] in snap["tabbed"]
            last = len(col) > 1 and r["row"] == max(x["row"] for x in col)   # нижнее берёт остаток
            if len(col) == 1 and not tab:
                # Одно окно в колонке — авто-высота, не SetFixed: с жёсткой высотой окно не
                # растягивалось, когда Super+S убирал нижнюю панель (22.10.2026, просьба:
                # «раз нижняя панель ушла… это пространство окна должны были сами заполнить»).
                if not _round:
                    A("ResetWindowHeight", id=r["id"])
                continue
            if not tab and not last and abs(got[1] - r["size"][1]) > 1:
                A("SetWindowHeight", id=r["id"], change={"SetFixed": r["size"][1]})
        time.sleep(0.15)
    for ws_id, c in snap["tabbed"]:
        head = next((r for r in rows if r["ws"] == ws_id and r["col"] == c and r["row"] == 1), None)
        if head:
            A("FocusWindow", id=head["id"])
            A("SetColumnDisplay", display="Tabbed")
    sizes = {o: output_size(o) for o in louts}
    for r in rows:
        o = r.get("out", "eDP-1")
        if r["fullscreen"] and r["id"] in cur and o in sizes and wsize(cur[r["id"]]) != list(sizes[o]):
            A("FullscreenWindow", id=r["id"])
    # 4) порядок столов — на каждом мониторе свой
    for o in louts:
        want = [idmap[d["id"]] for d in odesks if d["id"] in idmap and home(d) == o]
        for i, wid in enumerate(want, 1):
            wss, _w = query()
            now = {d["id"]: d["idx"] for d in desks(wss, o)}
            if now.get(wid) not in (None, i):
                A("MoveWorkspaceToIndex", index=i, reference={"Id": wid})
    # 5) раскладки ws_layout — к новым id столов
    for p, entries in ({} if TEST else snap.get("ws_layout") or {}).items():
        d = _load(p)
        n = dict(d)
        for k, v in entries.items():
            new = idmap.get(int(k))
            if new is not None:
                n[str(new)] = v
        if n != d:
            _save(p, n)
    # 6) активные окна столов, активные столы мониторов, фокус
    wss, wins = query()
    alive = {w["id"] for w in wins}
    now = {d["id"]: d.get("active_window_id") for d in wss}
    used = {r["ws"] for r in rows}
    for d in odesks:                     # активное окно стола — через его фокус, если сбилось
        aw = d.get("active_window_id")
        if not d.get("is_active") and d["id"] in used and aw in alive \
                and now.get(idmap.get(d["id"])) != aw:
            A("FocusWindow", id=aw)
    for act in [d for d in odesks if d.get("is_active")]:
        aw = act.get("active_window_id")
        if aw in alive:
            A("FocusWindow", id=aw)
        else:
            wss, wins = query()
            t = idmap.get(act["id"]) or tail_desk(wss, wins, home(act))
            if t is not None:
                A("FocusWorkspace", reference={"Id": t})
    if snap.get("focused") in alive:
        A("FocusWindow", id=snap["focused"])
    elif snap.get("focused_output"):
        A("FocusMonitor", output=snap["focused_output"])
    st["idmap"] = {str(k): v for k, v in idmap.items()}
    _save(STATE, dict(load_state(), idmap=st["idmap"]))


def fix_columns(T, rs):
    """Колонки стола T — как в снимке; если niri поставил иначе — переставить фокусом."""
    want = snap_columns(rs)
    if not want:
        return
    ids = {i for c in want for i in c}
    _wss, wins = query()
    if columns(wins, T, ids) == want:
        return
    log("restore: колонки стола", T, "перестраиваю", columns(wins, T, ids), "→", want)
    for col in columns(wins, T, ids):                    # каждое окно — своей колонкой
        for wid in col[1:]:
            A("ConsumeOrExpelWindowRight", id=wid)
    # место среди всех колонок стола: колонки чужих окон (новых) — правее
    for ci, col in enumerate(want, 1):
        A("FocusWindow", id=col[0])
        A("MoveColumnToIndex", index=ci)
        for wid in col[1:]:
            A("FocusWindow", id=wid)
            A("MoveColumnToIndex", index=ci + 1)
            A("ConsumeOrExpelWindowLeft", id=wid)


# ── сверка ────────────────────────────────────────────────────────────────────
def verify(snap):
    wss, wins = query()
    cur = {w["id"]: w for w in wins}
    pos = {d["id"]: d["idx"] for d in wss}
    dout = desk_out(wss)
    rows = [r for r in snap["windows"] if r["id"] in cur]
    gone = len(snap["windows"]) - len(rows)
    diffs = []
    where = {}
    for r in rows:
        where.setdefault(r["ws"], set()).add(cur[r["id"]].get("workspace_id"))
    for od, s in where.items():
        if len(s) > 1:
            diffs.append("окна стола %s разъехались по столам %s" % (od, sorted(s)))
    sdesks = sorted(snap["desks"], key=lambda d: d["idx"])
    for o in sorted({d.get("output") for d in sdesks if d.get("output")}):
        seq = [next(iter(where[d["id"]])) for d in sdesks if d.get("output") == o and d["id"] in where]
        if any(dout.get(x) != o for x in seq):
            diffs.append("окна ушли с монитора %s" % o)
            continue
        idxs = [pos.get(x) for x in seq]
        if idxs != sorted(idxs):
            diffs.append("порядок столов %s: %s" % (o, idxs))
    names = {d["id"]: d.get("name") for d in wss}
    for d in snap["desks"]:
        if d.get("name") and ZW not in d["name"] and d["id"] in where:
            if names.get(next(iter(where[d["id"]]))) != d["name"]:
                diffs.append("имя стола %r" % d["name"])
    for od in where:
        rs = [r for r in rows if r["ws"] == od]
        T = next(iter(where[od]))
        want = snap_columns(rs)
        got = columns(wins, T, {i for c in want for i in c})
        if want != got:
            diffs.append("колонки стола %s %d: было %s, стало %s" % (dout.get(T), pos.get(T, 0), want, got))
    # Все плитки монитора выше/ниже на одно и то же — сменилась высота рабочей области (бар,
    # островок, отступы), раскладка ни при чём. 22.10.2026: снимок снят, когда бар был на 2 px
    # выше, — на выходе шесть «не сошлось» при окнах на своих местах.
    shift = {}
    for r in rows:
        w = cur[r["id"]]
        if not r["floating"] and not w.get("is_floating"):
            g = wsize(w)
            shift.setdefault(dout.get(w.get("workspace_id")), []).append(
                (g[0] - r["size"][0], g[1] - r["size"][1]))
    area = {o: s[0][1] for o, s in shift.items()
            if len(s) > 1 and len(set(s)) == 1 and s[0][0] == 0 and 0 < abs(s[0][1]) <= 80}
    for o, dy in area.items():
        log("verify: рабочая область %s выше на %d px — плитки этого монитора не в счёт" % (o, dy))
    for r in rows:
        w = cur[r["id"]]
        nm = "%s (%s)" % (r["app_id"], r["id"])
        if bool(w.get("is_floating")) != r["floating"]:
            diffs.append("%s: %s" % (nm, "плавающее" if w.get("is_floating") else "в мозаике"))
            continue
        g = wsize(w)
        if not r["floating"] and dout.get(w.get("workspace_id")) in area:
            g = [g[0], g[1] - area[dout.get(w.get("workspace_id"))]]
        if any(abs(g[i] - r["size"][i]) > 1 for i in (0, 1)):
            diffs.append("%s: размер %s, был %s" % (nm, g, r["size"]))
        if r["floating"] and r["pos"]:
            p = tpos(w)
            if not p or any(abs(p[i] - r["pos"][i]) > 1 for i in (0, 1)):
                diffs.append("%s: место %s, было %s" % (nm, p, r["pos"]))
    return diffs, gone


# ── свернуть / развернуть ─────────────────────────────────────────────────────
def is_minimized(w, wss=None):
    wss = get("Workspaces") if wss is None else wss
    return any(d["id"] == w.get("workspace_id") and is_min_name(d.get("name")) for d in wss or [])


def heal(st, wss, wins):
    """Стол стопки пропал — niri убирает пустой неактивный стол (21.10.2026: Super+Ctrl+колесо
    увело на стол свёрнутых, Super+D свернул всё — стол 314 исчез, окна некуда вернуть).
    Новый стол — первый обычный стол монитора, встаёт перед столом свёрнутых; окна со стола
    свёрнутых без записи «min» (их возвращали в исчезнувший стол) — туда же. True — чинил."""
    live = {d["id"] for d in wss}
    fixed = False
    for o, v in (st.get("outs") or {}).items():
        if v.get("desk") in live or not desks(wss, o):
            continue
        d = stack_desk_of(desks(wss, o))
        if d is None:
            continue
        log("heal:", o, "стол стопки", v.get("desk"), "пропал →", d["id"])
        v["desk"] = d["id"]
        fixed = True
        M = min_desk(wss, o)
        mins = st.get("min") or {}
        stray = [w for w in wins if M and w.get("workspace_id") == M["id"] and str(w["id"]) not in mins]
        # сперва окна, потом место: пустой стол не в конце niri сразу убирает (лечение
        # крутилось по кругу, 415 столов за секунду)
        for w in stray:
            A("MoveWindowToWorkspace", window_id=w["id"], reference={"Id": d["id"]}, focus=False)
        if stray and d["idx"] > M["idx"]:
            A("MoveWorkspaceToIndex", index=M["idx"], reference={"Id": d["id"]})
        if stray and any(x.get("is_active") and x["id"] == M["id"] for x in wss):
            A("FocusWorkspace", reference={"Id": d["id"]})
    if fixed:
        _save(STATE, st)
    return fixed


GAMES = ("steam_app_", "gamescope", "cs2")


def is_game(w):
    return (w.get("app_id") or "").startswith(GAMES)


def game_tap():
    """Одиночный Super (super_tap.py) в стопке при игре в фокусе — свернуть игру (22.10.2026, просьба: «во время запуска игры кс можно его сворачивать на super? в режиме stack mode
    только»). Вернуть — кнопкой панели или Super+K. True — свернул, «Пуск» не открывать."""
    if not active():
        return False
    f = get("FocusedWindow")
    if not f or not is_game(f) or hidden(f):
        return False
    log("super: свернуть игру", f.get("app_id"), f["id"])
    minimize(f["id"])
    return True


def minimize(wid):
    st = load_state()
    if not active(st):
        return
    wss, wins = query()
    if heal(st, wss, wins):
        wss, wins = query()
    w, o = window_out(wid, wss, wins)
    if not w or o not in (st.get("outs") or {}):
        return
    # игра во весь экран может стоять и не на столе стопки; места не помним — она в ленте,
    # вернётся на стол стопки во весь экран (демон полный экран не трогает)
    game = is_game(w) and not w.get("is_floating")
    if w.get("workspace_id") != so(st, o)["desk"] and not game:
        return
    M = min_desk(wss, o)
    if M:
        mid = M["id"]
    else:
        mid = tail_desk(wss, wins, o)
        if mid is None:
            return
        taken = {d.get("name") for d in wss}
        name = next(MIN_NAME + WJ * i for i in range(8) if MIN_NAME + WJ * i not in taken)
        A("SetWorkspaceName", name=name, workspace={"Id": mid})
    st.setdefault("min", {})[str(wid)] = None if game else geom_of(w, st, o)
    _save(STATE, st)
    A("MoveWindowToWorkspace", window_id=wid, reference={"Id": mid}, focus=False)


def unminimize(wid, focus=True):
    st = load_state()
    if not active(st):
        A("FocusWindow", id=wid)
        return
    wss, wins = query()
    heal(st, wss, wins)
    w, o = window_out(wid)
    if o not in (st.get("outs") or {}):
        A("FocusWindow", id=wid)
        return
    S = so(st, o)["desk"]
    g = st.setdefault("min", {}).pop(str(wid), None)
    _save(STATE, st)
    A("MoveWindowToWorkspace", window_id=wid, reference={"Id": S}, focus=focus)
    if g:
        A("MoveFloatingWindow", id=wid, x={"SetFixed": g[0]}, y={"SetFixed": g[1]})
    if focus:
        A("FocusWorkspace", reference={"Id": S})
        A("FocusWindow", id=wid)
    wss, wins = query()
    M = min_desk(wss, o)
    if M and not any(w.get("workspace_id") == M["id"] for w in wins):
        A("UnsetWorkspaceName", reference={"Id": M["id"]})


WS_STEP = os.path.expanduser("~/.config/niri/scripts/ws-step")


def stack_key(st, d):
    """Как Win+↑/↓ в Windows. K (up): окно в фокусе — развернуть; на столе нет окна в фокусе
    (всё свёрнуто) — вернуть последнее свёрнутое этого монитора. J (down): свернуть, и
    развёрнутое тоже — вернётся развёрнутым (21.10.2026, просьба: «для возвращения из
    полноэкранного у нас и так есть super+f»)."""
    wss, wins = query()
    f = next((w for w in wins if w.get("is_focused")), None)
    o = window_out(f["id"], wss, wins)[1] if f else None
    mine = bool(f and o in (st.get("outs") or {}) and f.get("workspace_id") == so(st, o)["desk"]
                and f.get("is_floating") and not hidden(f))
    maxed = mine and str(f["id"]) in (st.get("max") or {})
    if d == "fs":
        # Super+F в стопке = кнопка «Развернуть» (туда и обратно): полный экран niri закрыл бы
        # полосу и панель, а демон снимал его по размеру — окно мигало (21.10.2026). Игры —
        # настоящий полный экран, как и вне стопки.
        if mine and not is_game(f):
            main(["max", str(f["id"])])
        else:
            A("FullscreenWindow", **({"id": f["id"]} if f else {}))
        return 0
    if d == "down":
        if mine:
            main(["min", str(f["id"])])
        return 0
    if mine:
        if not maxed:
            main(["max", str(f["id"])])
        return 0
    fo = (get("FocusedOutput") or {}).get("name")
    mins = list(st.get("min") or {})
    pick = [k for k in mins if window_out(int(k), wss, wins)[1] == fo] or mins
    if pick:
        main(["unmin", pick[-1]])
    return 0


def stack_hl(st, d):
    """Super+H/L в стопке (21.10.2026, просьба: «переходили влево вправо по окнам, даже если
    они свернуты; если на столе 2 и более окон — как раньше»; «и дальше проходится по
    свёрнутым, если левее уже ничего нет, и правее»). Есть окно на столе в ту сторону —
    фокус на ближайшее; дальше нет — ближайшее свёрнутое по порядку нижней панели (по кругу),
    оно возвращается."""
    wss, wins = query()
    fo = (get("FocusedOutput") or {}).get("name")
    if fo not in (st.get("outs") or {}):
        A("FocusColumnLeft" if d == "left" else "FocusColumnRight")
        return 0
    S = so(st, fo)["desk"]
    M = min_desk(wss, fo)
    shown = [w for w in wins if w.get("workspace_id") == S and not hidden(w)]
    mins = [w for w in wins if M and w.get("workspace_id") == M["id"] and not hidden(w)]
    sign = -1 if d == "left" else 1
    f = next((w for w in shown if w.get("is_focused")), None)

    def cx(w):
        p, ts = tpos(w), lay(w).get("tile_size")
        return (p[0] + ts[0] / 2) if p and ts else 0
    if f:
        side = [w for w in shown if w is not f and (cx(w) - cx(f)) * sign > 0]
        if side:
            A("FocusWindow", id=min(side, key=lambda w: abs(cx(w) - cx(f)))["id"])
            return 0
    if not mins:
        return 0
    try:
        btns = json.load(open(os.path.expanduser("~/.cache/xpbar-buttons-%s.json" % fo)))["btns"]
    except (OSError, ValueError, KeyError):
        btns = {}
    order = sorted(shown + mins, key=lambda w: (str(w["id"]) not in btns,
                                                (btns.get(str(w["id"])) or [0])[0], w["id"]))
    ids = [w["id"] for w in order]
    mids = {w["id"] for w in mins}
    if f is None:
        nxt = next(i for i in (ids[::-1] if d == "left" else ids) if i in mids)
    else:
        k = ids.index(f["id"])
        nxt = next(ids[(k + sign * j) % len(ids)] for j in range(1, len(ids) + 1)
                   if ids[(k + sign * j) % len(ids)] in mids)
    main(["unmin", str(nxt)])
    return 0


# Как разворачивать (21.10.2026, просьба: «раскрывать полностью и раскрывать, чтобы было видно
# островок»): full — на всю рабочую область; island — сверху место под островок, на том
# мониторе, где он есть (state/island.json monitor: имя | focus | all). Настройки →
# Compositor → «Развёрнутое окно»; stack_mode.py maxmode full|island.
MAX_MODE_FILE = os.path.expanduser("~/.config/hypr/state/stack-max-mode")
ISLAND_CONF = os.path.expanduser("~/.config/hypr/state/island.json")
ISLAND_CLEAR = 40             # низ капсулы островка — 35 px от края (снимок 21.10), и зазор


def max_mode():
    try:
        m = open(MAX_MODE_FILE).read().strip()
    except OSError:
        return "full"
    return m if m in ("full", "island") else "full"


def max_top(o):
    if max_mode() != "island":
        return 0
    try:
        c = json.load(open(ISLAND_CONF))
    except (OSError, ValueError):
        return 0
    if not c.get("on", True):
        return 0
    m = c.get("monitor") or "focus"
    return ISLAND_CLEAR if m in ("focus", "all") or m == o else 0


def max_rect(st, o, w):
    """Где стоит развёрнутое окно: рабочая область минус полоса и своя рамка вокруг (и
    место под островок — max_top)."""
    ww, wh = work(st, o)
    b, bh, F, t = border(w), bar_h(o), FRAME.get(style(o), 3), max_top(o)
    return F, t + bh + F, ww - 2 * F - 2 * b, wh - t - bh - 2 * F - 2 * b


def set_max_mode(mode):
    """Записать вид и переставить уже развёрнутые окна."""
    with open(MAX_MODE_FILE, "w") as f:
        f.write(mode + "\n")
    st = load_state()
    if not active(st):
        return
    for key in st.get("max") or {}:
        w, o = window_out(int(key))
        if w and o in (st.get("outs") or {}):
            place(int(key), *max_rect(st, o, w))


def toggle_max(wid, geom=None):
    """Развернуть на рабочую область под полосой ⇄ обратно. geom — куда возвращать, если
    окно сейчас не на своём месте (было «во весь экран»)."""
    st = load_state()
    if not active(st):
        return
    w, o = window_out(wid)
    if not w or o not in (st.get("outs") or {}):
        return
    mx = st.setdefault("max", {})
    key = str(wid)
    if key in mx:
        place(wid, *mx.pop(key))
    else:
        mx[key] = geom or geom_of(w, st, o)
        place(wid, *max_rect(st, o, w))
    _save(STATE, st)


def fit_geom(g, ww, wh, bh):
    """[x, y, w, h] влезть в рабочую область ww×wh другого монитора (полоса bh сверху)."""
    w, h = min(g[2], ww - 16), min(g[3], wh - bh - 16)
    x = min(max(8, g[0]), ww - w - 8)
    y = min(max(bh + 8, g[1]), wh - h - 8)
    return [int(x), int(y), int(w), int(h)]


def neighbor_out(order, o, d):
    """Монитор слева/справа от o (order — по x) или None у края."""
    if o not in order:
        return None
    i = order.index(o) + (-1 if d == "left" else 1)
    return order[i] if 0 <= i < len(order) else None


def to_monitor(d):
    """Ctrl+Alt+H/L. niri кладёт окно на активный стол соседа как есть; в стопке там может
    оказаться стол свёрнутых или место за краем, а развёрнутое — с размером чужого
    монитора (21.10.2026, «Делай тоже» — дыра nostack). Окно — на стол стопки соседа, на
    то же место от угла рабочей области; развёрнутое там разворачивается заново."""
    st = load_state()
    if not active(st):
        A("MoveWindowToMonitorLeft" if d == "left" else "MoveWindowToMonitorRight")
        return 0
    wss, wins = query()
    w = next((x for x in wins if x.get("is_focused")), None)
    if not w or hidden(w):
        return 0
    outs = st.get("outs") or {}
    o = desk_out(wss).get(w.get("workspace_id"))
    info = get("Outputs") or {}
    order = sorted(outs, key=lambda n: ((info.get(n) or {}).get("logical") or {}).get("x", 0))
    t = neighbor_out(order, o, d)
    if t is None:
        return 0
    wid, key = w["id"], str(w["id"])
    mx = st.setdefault("max", {})
    ww, wh = work(st, t)
    g = fit_geom(mx.get(key) or geom_of(w, st, o), ww, wh, bar_h(t))
    A("MoveWindowToWorkspace", window_id=wid, reference={"Id": outs[t]["desk"]}, focus=True)
    if not w.get("is_floating"):
        A("MoveWindowToFloating", id=wid)
    if key in mx:
        mx[key] = g
        place(wid, *max_rect(st, t, w))
        _save(STATE, st)
    else:
        place(wid, *g)
    A("FocusWindow", id=wid)
    return 0


NUDGE = 50                               # шаг Super+Alt+H/J/K/L в стопке, px
NIRI_MOVE = {"left": "MoveColumnLeft", "right": "MoveColumnRight",
             "up": "MoveWindowUp", "down": "MoveWindowDown"}


def nudge(d):
    """Super+Alt+H/J/K/L (21.10.2026, просьба: вариант «сдвиг окна шагом»). В стопке окно в
    фокусе сдвигается на NUDGE; полоса заголовка не уходит за верх рабочей области, окно —
    не дальше 80 px от края. Развёрнутое не двигается. Без стопки — как раньше в niri."""
    st = load_state()
    if not active(st):
        A(NIRI_MOVE[d])
        return 0
    wss, wins = query()
    w = next((x for x in wins if x.get("is_focused")), None)
    if not w or hidden(w) or str(w["id"]) in (st.get("max") or {}):
        return 0
    o = desk_out(wss).get(w.get("workspace_id"))
    if o not in (st.get("outs") or {}) or w.get("workspace_id") != so(st, o)["desk"]:
        return 0
    x, y, ww_, wh_ = geom_of(w, st, o)
    dx, dy = {"left": (-NUDGE, 0), "right": (NUDGE, 0), "up": (0, -NUDGE), "down": (0, NUDGE)}[d]
    W, H = work(st, o)
    x = min(max(x + dx, 80 - ww_), W - 80)
    y = min(max(y + dy, bar_h(o)), H - 80)
    A("MoveFloatingWindow", id=w["id"], x={"SetFixed": int(x)}, y={"SetFixed": int(y)})
    return 0

# ── команды ───────────────────────────────────────────────────────────────────
def status():
    st = load_state()
    on = active(st)
    snap = st.get("snap") or {}
    print("стопка:", "включена" if on else "выключена")
    if snap:
        print("снимок: %s, окон %d, столов %d" % (
            time.strftime("%d.%m %H:%M", time.localtime(snap.get("t", 0))),
            len(snap.get("windows", [])), len(snap.get("desks", []))))
    if on:
        for o, v in (st.get("outs") or {}).items():
            print("%s: стол стопки %s, смещение %s" % (o, v.get("desk"), v.get("offset")))
        print("полосы:", "работают" if daemon_pids() else "НЕ ЗАПУЩЕНЫ")
        print("свёрнуто:", len(st.get("min") or {}), "развёрнуто:", len(st.get("max") or {}))
    return 0


def check():
    bad = []
    st = load_state()
    if os.path.exists(STATE) and not st:
        bad.append("state/stack-mode.json не читается")
    wss, _w = query()
    if active(st):
        if not daemon_pids():
            bad.append("стопка включена, а полосы (daemon) не запущены")
        if not st.get("outs"):
            bad.append("стопка включена по старому состоянию (без outs) — выключить и включить")
        for o, v in (st.get("outs") or {}).items():
            if wss and o in outputs(wss) and v.get("desk") not in {d["id"] for d in desks(wss, o)}:
                bad.append("стола стопки нет на %s" % o)
    else:
        if daemon_pids():
            bad.append("стопка выключена, а daemon жив")
        try:
            if KDL_STACK.strip() in open(KDL).read():
                bad.append("анимация перемещения осталась выключенной (cfg/stack-mode.kdl)")
        except OSError:
            bad.append("нет cfg/stack-mode.kdl")
        left = [d["id"] for d in wss or [] if is_min_name(d.get("name"))]
        if left:
            bad.append("стопка выключена, а стол свёрнутых остался: %s" % left)
    for b in bad:
        print("stack_mode:", b)
    if not bad:
        print("stack_mode: ок (%s)" % ("включена" if active(st) else "выключена"))
    return 1 if bad else 0


def selftest():
    """Снимок, столы стопки и колонки на выдуманных данных — без niri."""
    W = lambda i, ws, c, r, fl=False, s=(900, 1000): {   # noqa: E731
        "id": i, "app_id": "a%d" % i, "title": "t", "workspace_id": ws, "is_floating": fl,
        "layout": {"pos_in_scrolling_layout": None if fl else [c, r], "tile_size": [s[0] + 8, s[1] + 8],
                   "window_size": list(s), "tile_pos_in_workspace_view": [10, 60] if fl else None}}
    wss = [{"id": 1, "idx": 1, "name": "\U000f072c", "output": "eDP-1", "is_active": True},
           {"id": 2, "idx": 2, "name": ZW + "x", "output": "eDP-1"},
           {"id": 4, "idx": 1, "name": POCKET, "output": "DP-4"},
           {"id": 3, "idx": 2, "name": None, "output": "DP-4", "is_focused": True, "is_active": True},
           {"id": 5, "idx": 3, "name": MIN_NAME + WJ, "output": "DP-4"}]
    wins = [W(10, 2, 1, 1), W(11, 2, 2, 1, s=(900, 494)), W(12, 2, 2, 2, s=(900, 494)),
            W(13, 2, 0, 0, fl=True), W(14, 3, 1, 1), dict(W(15, 1, 1, 1, fl=True), app_id="dash-x"),
            W(16, 2, 3, 1, s=(900, 1000)), W(17, 2, 3, 2, s=(900, 1000)), W(18, 4, 1, 1),
            dict(W(19, 3, 2, 1), is_focused=True), W(20, 5, 0, 0, fl=True)]
    ok = True
    global output_size
    keep = output_size
    output_size = lambda out: (1920, 1080)   # noqa: E731
    try:
        s = take_snapshot(wss, wins)
    finally:
        output_size = keep
    ids = [r["id"] for r in s["windows"]]
    outs = {r["id"]: r["out"] for r in s["windows"]}
    for cond, msg in ((ids == [10, 11, 12, 13, 14, 16, 17, 18, 19, 20],
                       "в снимке оба монитора и карман, без dash (забытые свёрнутые — берём): %s" % ids),
                      (outs.get(10) == "eDP-1" and outs.get(14) == "DP-4", "монитор окна в снимке"),
                      ([d["id"] for d in s["desks"]] == [1, 2, 4, 3, 5], "столы снимка: %s" % [d["id"] for d in s["desks"]]),
                      (stack_desk_of(desks(wss, "eDP-1"))["id"] == 1, "стол стопки ноутбука — 1"),
                      (stack_desk_of(desks(wss, "DP-4"))["id"] == 3, "стол стопки MSI — первый после кармана"),
                      ((min_desk(wss, "DP-4") or {}).get("id") == 5 and min_desk(wss, "eDP-1") is None,
                       "свёрнутые по мониторам (MIN_NAME + WJ)"),
                      (outputs(wss)[0] == "eDP-1", "ноутбук первым"),
                      (snap_columns([r for r in s["windows"] if r["ws"] == 2]) == [[10], [11, 12], [16, 17]],
                       "колонки снимка"),
                      (s["tabbed"] == [[2, 3]], "вкладки распознаны: %s" % s["tabbed"]),
                      (s["focused_output"] == "DP-4" and s["focused"] == 19, "фокус: монитор и окно"),
                      (columns(wins, 2) == [[10], [11, 12], [16, 17]], "колонки живых окон"),
                      (outs.get(18) == "DP-4", "окна кармана — в стопку своего монитора"),
                      (neighbor_out(["eDP-1", "DP-4"], "eDP-1", "right") == "DP-4"
                       and neighbor_out(["eDP-1", "DP-4"], "eDP-1", "left") is None,
                       "Ctrl+Alt+L/H: сосед справа, у края — никуда"),
                      (fit_geom([1700, 900, 1200, 900], 1920, 1036, 22) == [712, 128, 1200, 900]
                       and fit_geom([-50, 0, 600, 400], 1920, 1036, 22) == [8, 30, 600, 400],
                       "окно на другом мониторе влезает в рабочую область")):
        print(("ок  " if cond else "НЕТ ") + msg)
        ok &= cond
    return 0 if ok else 1


def main(a):
    cmd = a[0] if a else "status"
    if cmd == "toggle":
        return turn_off() if active() else turn_on()
    if cmd == "on":
        return turn_on()
    if cmd == "off":
        return turn_off()
    if cmd == "status":
        return status()
    if cmd == "verify":
        snap = load_state().get("snap")
        if not snap:
            print("снимка нет")
            return 1
        diffs, gone = verify(snap)
        print("закрыто с тех пор окон:", gone)
        for d in diffs:
            print(" -", d)
        print("всё на местах" if not diffs else "расхождений: %d" % len(diffs))
        return 1 if diffs else 0
    if cmd == "restore":
        st = load_state()
        if active(st) or not st.get("snap"):
            print("стопка включена или снимка нет")
            return 1
        restore(st)
        return main(["verify"])
    if cmd in ("min", "unmin") and len(a) > 1:
        if not anim_request(cmd, int(a[1])):
            (minimize if cmd == "min" else unminimize)(int(a[1]))
        return 0
    if cmd == "topbar":
        if len(a) > 1 and a[1] in ("waybar", "capsule"):
            set_top_bar_kind(a[1])
        else:
            print(top_bar_kind())
        return 0
    if cmd == "maxmode":
        if len(a) > 1 and a[1] in ("full", "island"):
            set_max_mode(a[1])
        else:
            print(max_mode())
        return 0
    if cmd == "max" and len(a) > 1:
        if not anim_request("max", int(a[1])):
            toggle_max(int(a[1]))
        return 0
    if cmd == "key" and len(a) > 1 and a[1] == "fs":
        st = load_state()
        if not active(st):
            A("FullscreenWindow")
            return 0
        return stack_key(st, "fs")
    if cmd == "key" and len(a) > 1 and a[1] in ("up", "down"):
        # Super+K/J (21.10.2026, просьба: «убери в режиме стакинга переключение столов
        # super+j/k и сделай на эти бинды свернуть/развернуть окно»). Без стопки — шаг по
        # столам, как было (ws-step).
        st = load_state()
        if not active(st):
            os.execv(WS_STEP, [WS_STEP, a[1]])
        return stack_key(st, a[1])
    if cmd == "key" and len(a) > 1 and a[1] in ("left", "right"):
        st = load_state()
        if not active(st):
            A("FocusColumnLeft" if a[1] == "left" else "FocusColumnRight")
            return 0
        return stack_hl(st, a[1])
    if cmd == "superd":
        # Super+D как в Windows, но по режиму (21.10.2026, просьба: «если stack mode — свернуть
        # окна, если scrolling — перейти в стол дашборда»)
        if active() and anim_request("desktop", 0):
            return 0
        os.execv(os.path.expanduser("~/.config/niri/scripts/dashboard"),
                 ["dashboard", "focus"])
    if cmd == "move" and len(a) > 1 and a[1] in NIRI_MOVE:
        return nudge(a[1])
    if cmd == "tomon" and len(a) > 1 and a[1] in ("left", "right"):
        return to_monitor(a[1])
    if cmd == "daemon":
        import stack_bars
        return stack_bars.run()
    if cmd == "check":
        return check()
    if cmd == "selftest":
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
