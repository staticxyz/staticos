#!/usr/bin/env python3
"""Раскладка по столам (Super+Ctrl+T) и вид ленты по столам (Super+R). 13.10 / 16.10.2026.

    ws_layout.py              сторож (живёт в staticos_host): держит раскладку столов
    ws_layout.py cycle [back] стол в фокусе — следующая раскладка (Super+A, back — Super+Ctrl+A; до 16.10 — Super+Ctrl+T)
    ws_layout.py set MODE     стол в фокусе — в MODE (scrolling|tiling|stacking|peek|three)
    ws_layout.py get          раскладки столов (json)
    ws_layout.py off          все столы — scrolling, ws-layout.kdl пустой
    ws_layout.py view toggle  стол в фокусе: «подогнать» ⇄ «центр» (Super+R, без уведомлений)
    ws_layout.py view fit|center|reset   задать / забыть виды всех столов
    ws_layout.py check        ws-layout.kdl совпадает с тем, что нужно сейчас; rc 1 — нет
    ws_layout.py selftest     проверка планировщика сетки

Раскладки (Super+A по кругу; номера — в уведомлении):
  1 scrolling «Прокрутка»     — обычная лента niri;
  2 tiling    «Плитка-сетка»  — все окна стола вместе ровно в экран, сеткой: колонок
              ⌈√N⌉, окна по колонкам сверху вниз (1 — весь экран, 2 — пополам, 3 — слева
              одно, справа два, 4 — 2×2, 5 — 1+2+2, 6 — 3×2 …). Новое окно встаёт в
              порядок сразу после окна, где был фокус, — «делит окно в фокусе», как dwindle
              в Hyprland (вложенных разбиений у niri нет: только колонки и окна в них).
              Переставили окна руками (Super+Shift+H/L…) — новый порядок запоминается;
  3 peek      «Подглядывание» — колонки по 80 %, фокус посередине, соседи торчат по краям;
  4 three     «Три в ряд»     — колонки по трети экрана, видно ровно три;
  5 stacking  «Плавающие»     — все окна стола плавающие, каскадом.
Пользователь 16.10: «давай сеткой и чтобы делило окно в фокусе»; виды 4 и 6 из списка — сюда,
«старый Super+R вернуть как было, только отдельно на каждый рабочий стол, без уведомления».
peek/three меняют ширину колонок: прежние запоминаются (ws-view-widths.json) и
возвращаются при выходе; новым окнам сторож сразу ставит ширину раскладки.

Вид ленты (Super+R) — fit «подогнать» (правило пары pair_center.py) или center (всегда по
центру — тоже pair_center.py, center-column), по столам (ws-view.json). В конфиге niri всегда
"never": см. want_kdl. Стол без своего выбора живёт по общему
переключателю «Настройки» → «Окна» (state/ribbon-center). Действует на столах scrolling;
у остальных раскладок центрирование своё.

niri умеет только scrolling, поэтому всё это имитация поверх него. Раскладка привязана к
id стола: niri_bar.py всё время переименовывает столы, а id живёт, пока жив стол. Стол
исчез — его раскладка и вид забываются. Центрирование в niri — глобальная настройка
layout: сторож держит в ~/.config/niri/cfg/ws-layout.kdl (подключён последним в config.kdl)
"never" навсегда, центрирование по столам делает pair_center.py.

Откат: `ws_layout.py off`, убрать ws_layout.py из ~/.config/hypr/state/staticos-host.json,
строку include "cfg/ws-layout.kdl" из config.kdl и бинды Mod+Ctrl+T из binds.kdl;
Mod+R — обратно на ribbon_center.py toggle.
"""
import ctypes
import json
import math
import os
import select
import signal
import subprocess
import sys
import time

_libc = ctypes.CDLL(None)    # для PR_SET_PDEATHSIG в дочерних (dlopen после fork небезопасен)

STATE = os.path.expanduser("~/.config/hypr/state/ws-layout.json")
FLOATED = os.path.expanduser("~/.config/hypr/state/ws-layout-floated.json")
ORDER = os.path.expanduser("~/.config/hypr/state/ws-layout-order.json")
VIEW = os.path.expanduser("~/.config/hypr/state/ws-view.json")
VIEW_W = os.path.expanduser("~/.config/hypr/state/ws-view-widths.json")
RIBBON = os.path.expanduser("~/.config/hypr/state/ribbon-center")
KDL = os.path.expanduser("~/.config/niri/cfg/ws-layout.kdl")
MODES = ("scrolling", "tiling", "peek", "three", "stacking")   # 16.10: «Плавающие» с 3 на 5 (Пользователь)
NAMES = {"scrolling": "Прокрутка", "tiling": "Плитка-сетка", "stacking": "Плавающие",
         "peek": "Подглядывание", "three": "Три в ряд"}
WIDTH = {"peek": "80%", "three": "33.3333%"}       # раскладки «ширина колонок»
VIEWS = ("fit", "center")
FLOAT_W, FLOAT_H, CASCADE = "50%", "60%", 36
KDL_EMPTY = ("// Пишет ws_layout.py: всегда \"never\" — центр по столам делает pair_center.py.\n"
             "// Руками не править.\n")
KDL_NEVER = (KDL_EMPTY + "layout {\n    center-focused-column \"never\"\n}\n")
KDL_ALWAYS = (KDL_EMPTY + "layout {\n    center-focused-column \"always\"\n}\n")


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
    # Без изменений — не трогать файл (16.10.2026): сторож переписывал ws-layout.json и
    # ws-view.json на каждое событие niri, а сторож виджетов следит за ними и на каждую
    # запись пересчитывал виджеты — 19 % ядра у него и 30 % у niri, фокус «стал медленнее».
    if os.path.exists(path) and _load(path) == d:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f)
    os.replace(tmp, path)


def load():
    return {str(k): v for k, v in _load(STATE).items() if v in MODES and v != "scrolling"}


def save(d):
    _save(STATE, d)


def load_views():
    return {str(k): v for k, v in _load(VIEW).items() if v in VIEWS}


def global_view():
    try:
        return "center" if open(RIBBON).read().strip() == "center" else "fit"
    except OSError:
        return "fit"


def write_kdl(text):
    """True — файл изменился (niri перечитает конфиг сам и пришлёт ConfigLoaded)."""
    try:
        if open(KDL).read() == text:
            return False
    except OSError:
        pass
    tmp = KDL + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, KDL)
    return True


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


# ── планировщик сетки (без побочных эффектов — его проверяет selftest) ──

def grid(order):
    """Порядок окон → колонки сетки. Колонок ⌈√N⌉, лишние окна — в правые колонки:
    3 → [1][2,3] (как dwindle), 5 → [1][2,3][4,5], 7 → [1,2][3,4][5,6,7]."""
    n = len(order)
    if not n:
        return []
    c = math.ceil(math.sqrt(n))
    base, extra = divmod(n, c)
    counts = [base] * (c - extra) + [base + 1] * extra
    out, i = [], 0
    for k in counts:
        out.append(list(order[i:i + k]))
        i += k
    return out


def next_order(prev, flat, before):
    """Новый порядок окон стола.

    prev   — запомненный порядок; flat — окна сейчас (по колонкам сверху вниз);
    before — окно, где был фокус до появления новых. Состав тот же — окна переставили
    руками, берём как есть. Новые окна встают сразу после before («делят окно в фокусе»),
    без него — в конец; ушедшие выпадают."""
    if set(prev) == set(flat):
        return list(flat)
    order = [w for w in prev if w in flat]
    for w in flat:
        if w in order:
            continue
        at = order.index(before) + 1 if before in order else len(order)
        order.insert(at, w)
        before = w                   # несколько новых разом — друг за другом
    return order


# ── применение ──

def apply_grid(ws, focus_id, before=None, force=False):
    """Довести стол до сетки. Окна переставляются по --id (consume-or-expel), фокус нужен
    только для порядка колонок (move-column-to-index) — поэтому только на столе на экране."""
    _wss, wins = query()
    cols = columns(wins, ws["id"])
    if not cols:
        return
    flat = [w for col in cols for w in col]
    orders = _load(ORDER)
    order = next_order(orders.get(str(ws["id"]), []), flat, before)
    orders[str(ws["id"])] = order
    _save(ORDER, orders)
    want = grid(order)
    if cols != want:
        if not ws.get("is_active"):
            return                   # перестроим, когда стол покажут
        # 1) каждое окно — в свою колонку (снизу вверх: expel ставит окно справа от колонки)
        for col in cols:
            for wid in reversed(col[1:]):
                act("consume-or-expel-window-right", "--id", str(wid))
        # 2) колонки — в нужном порядке
        _wss, wins = query()
        if [c[0] for c in columns(wins, ws["id"])] != order:
            for i, wid in enumerate(order, 1):
                act("focus-window", "--id", str(wid))
                act("move-column-to-index", str(i))
        # 3) собрать колонки сетки: одиночное окно справа уходит в колонку слева, вниз
        for col in want:
            for wid in col[1:]:
                act("consume-or-expel-window-left", "--id", str(wid))
        for wid in order:
            act("reset-window-height", "--id", str(wid))
        force = True
    if not force:
        return
    width = "%.4f%%" % (100.0 / len(want))
    for col in want:
        act("set-window-width", "--id", str(col[0]), width)
    if ws.get("is_active") and focus_id:
        # показать стол с первой колонки: при «never» вид потом не сдвинется
        act("focus-window", "--id", str(want[0][0]))
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


def apply_width(ws_id, mode, wins=None):
    """Колонки стола — под ширину раскладки (peek/three). Прежние ширины запомнить один раз."""
    if wins is None:
        _wss, wins = query()
    saved = _load(VIEW_W)
    mine = saved.setdefault(str(ws_id), {})
    for _c, r, w in tiles(wins, ws_id):
        if r == 1 and str(w["id"]) not in mine:
            # ширина в пикселях у niri — ширина самого окна, без рамки (tile_size больше на неё)
            mine[str(w["id"])] = int(((w.get("layout") or {}).get("window_size") or [0])[0])
    _save(VIEW_W, saved)
    for col in columns(wins, ws_id):
        act("set-window-width", "--id", str(col[0]), WIDTH[mode])


def restore_widths(ws_id):
    saved = _load(VIEW_W)
    mine = saved.pop(str(ws_id), None)
    _save(VIEW_W, saved)
    if mine is None:
        return
    _wss, wins = query()
    for col in columns(wins, ws_id):
        px = mine.get(str(col[0]))
        act("set-window-width", "--id", str(col[0]), str(px) if px else "50%")


def want_kdl(wss, modes, views):
    """Всегда "never" (16.10.2026). center-focused-column — одна настройка на все столы:
    переключать её по столу в фокусе нельзя — при каждом перечитывании niri заново
    центрировал и остальные столы (стол в «Подогнать» после визита на стол в «Центре»
    оказывался по центру). «Центр» и peek делает pair_center.py через center-column."""
    return KDL_NEVER


def sync_kdl(wss, modes, views=None):
    return write_kdl(want_kdl(wss, modes, load_views() if views is None else views))


def wait_config(change, limit=0.6):
    """Сделать change() и дождаться ConfigLoaded: настройка вступает в силу позже записи
    файла (то же, что ribbon_center.apply_and_wait). change() → False — ждать нечего."""
    import socket
    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(os.environ["NIRI_SOCKET"])
        sock.sendall(b'"EventStream"\n')
    except (OSError, KeyError):
        if change():
            time.sleep(0.25)
        return
    buf = b""

    def got_loaded(deadline):
        nonlocal buf
        while time.time() < deadline:
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if b"ConfigLoaded" in line:
                    return True
            r, _, _ = select.select([sock], [], [], max(0.0, deadline - time.time()))
            if not r:
                return False
            chunk = sock.recv(65536)
            if not chunk:
                return False
            buf += chunk
        return False

    got_loaded(time.time() + 0.15)        # начальное состояние потока — пропустить
    if change():
        got_loaded(time.time() + limit)
    sock.close()


# ── команды ──

def set_mode(mode, ws=None):
    wss, wins = query()
    ws = ws or focused_ws(wss)
    if not ws:
        return 1
    key = str(ws["id"])
    modes = load()
    old = modes.get(key, "scrolling")
    if mode == "scrolling":
        modes.pop(key, None)
    else:
        modes[key] = mode
    save(modes)
    wait_config(lambda: sync_kdl(wss, modes))
    fid = focused_window(wins)
    if old == "stacking" and mode != "stacking":
        unfloat(ws, fid)
    if old in WIDTH and mode not in WIDTH:
        restore_widths(ws["id"])
    if old == "tiling" and mode != "tiling":
        untile(ws, fid)
    if mode == "tiling":
        orders = _load(ORDER)
        orders.pop(key, None)            # порядок — с того, как окна стоят сейчас
        _save(ORDER, orders)
        apply_grid(ws, fid, force=True)
    elif mode == "stacking":
        apply_stacking(ws, fid)
    elif mode in WIDTH:
        apply_width(ws["id"], mode)
        if fid:
            act("focus-window", "--id", str(fid))
            act("center-column")
    subprocess.run(["notify-send", "-a", "Раскладка стола", "-t", "1800",
                    "-h", "string:x-canonical-private-synchronous:ws-layout",
                    "Стол %s — %d: %s" % (ws.get("idx"), MODES.index(mode) + 1, NAMES[mode])],
                   capture_output=True)
    print(mode)
    return 0


def set_view(arg):
    """Super+R: «подогнать» ⇄ «центр» для стола в фокусе — как прежний ribbon_center.py
    toggle (вид сразу, без уведомлений), только выбор у каждого стола свой."""
    wss, _wins = query()
    ws = focused_ws(wss)
    if not ws:
        return 1
    key = str(ws["id"])
    modes = load()
    views = load_views()
    old = views.get(key) or global_view()
    new = ("center" if old == "fit" else "fit") if arg == "toggle" else arg
    views[key] = new
    _save(VIEW, views)
    if modes.get(key, "scrolling") != "scrolling":
        print(new, "(запомнил; у этого стола своя раскладка)")
        return 0
    sync_kdl(wss, modes, views)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import ribbon_center
    ribbon_center.niri_view(new)
    print(new)
    return 0


def stack_desk():
    """Столы режима «стопка», пока он включён (stack_mode.py; с 21.10.2026 — по одному на
    монитор): там окна плавающие по её правилам, раскладка стола не применяется."""
    try:
        import stack_mode
        st = stack_mode.load_state()
        if not stack_mode.active(st):
            return set()
        return {v.get("desk") for v in (st.get("outs") or {}).values()}
    except Exception:
        return set()


def watch():
    last = {}
    prev_focus = {}                      # стол → окно, где был фокус на прошлом проходе
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
                views = load_views()
                wss, wins = query()
                alive = {str(w["id"]) for w in wss}
                if any(k not in alive for k in modes) or any(k not in alive for k in views):
                    modes = {k: v for k, v in modes.items() if k in alive}   # стол исчез — забыть
                    save(modes)
                    views = {k: v for k, v in views.items() if k in alive}
                    _save(VIEW, views)
                    for path in (FLOATED, ORDER, VIEW_W):
                        _save(path, {k: v for k, v in _load(path).items() if k in alive})
                sync_kdl(wss, modes, views)
                fid = focused_window(wins)
                stack = stack_desk()
                for ws in wss:
                    mode = modes.get(str(ws["id"]))
                    if not mode or ws["id"] in stack:      # стол «стопки» — её порядки
                        last.pop(ws["id"], None)
                        continue
                    sig = (mode, signature(wins, ws["id"]), bool(ws.get("is_active")))
                    if last.get(ws["id"]) == sig:
                        continue
                    if mode == "tiling":
                        apply_grid(ws, fid, before=prev_focus.get(ws["id"]))
                    elif mode == "stacking":
                        apply_stacking(ws, fid)
                    else:
                        apply_width(ws["id"], mode, wins)
                    _w, wins = query()
                    last[ws["id"]] = (mode, signature(wins, ws["id"]), bool(ws.get("is_active")))
                for w in wins:
                    if w.get("is_focused") and not w.get("is_floating"):
                        prev_focus[w.get("workspace_id")] = w["id"]
        finally:
            p.kill()
        time.sleep(2)


def check():
    wss, _wins = query()
    f = focused_ws(wss)
    want = want_kdl(wss, load(), load_views())
    try:
        have = open(KDL).read()
    except OSError:
        have = None
    inc = 'include "cfg/ws-layout.kdl"' in open(os.path.expanduser("~/.config/niri/config.kdl")).read()
    print(json.dumps({"modes": load(), "views": load_views(), "global_view": global_view(),
                      "focused": f and f["id"], "kdl_ok": have == want, "included": inc},
                     ensure_ascii=False))
    return 0 if have == want and inc else 1


def selftest():
    def model(cols, order):
        """Прогнать шаги apply_grid на модели niri и вернуть итоговые колонки."""
        cols = [list(c) for c in cols]
        where = lambda w: next(i for i, c in enumerate(cols) if w in c)
        for col in [list(c) for c in cols]:                 # 1) expel вправо, снизу вверх
            for wid in reversed(col[1:]):
                i = where(wid)
                cols[i].remove(wid)
                cols.insert(i + 1, [wid])
        for n, wid in enumerate(order):                      # 2) move-column-to-index
            i = where(wid)
            cols.insert(n, cols.pop(i))
        for col in grid(order):                              # 3) consume влево
            for wid in col[1:]:
                i = where(wid)
                assert cols[i] == [wid], "consume не одиночного окна"
                cols.pop(i)
                cols[i - 1].append(wid)
        return cols
    g = lambda n: [len(c) for c in grid(list(range(n)))]
    assert g(1) == [1] and g(2) == [1, 1] and g(3) == [1, 2] and g(4) == [2, 2]
    assert g(5) == [1, 2, 2] and g(6) == [2, 2, 2] and g(7) == [2, 2, 3] and g(10) == [2, 2, 3, 3]
    # новое окно встаёт после окна в фокусе
    assert next_order([1, 2, 3], [1, 2, 3, 9], 1) == [1, 9, 2, 3]
    assert next_order([1, 2, 3], [1, 9, 2, 3], 3) == [1, 2, 3, 9]
    assert next_order([1, 2, 3], [1, 3, 9], 2) == [1, 3, 9]          # ушедшее выпало, фокус пропал
    assert next_order([1, 2, 3], [3, 1, 2], 1) == [3, 1, 2]          # переставили руками
    assert next_order([], [5, 6], None) == [5, 6]
    assert next_order([1, 2], [1, 2, 8, 9], 1) == [1, 8, 9, 2]       # два новых разом
    for cols, order in (([[1], [2, 3]], [1, 3, 2]),
                        ([[1], [2, 3], [4]], [1, 4, 2, 3]),
                        ([[1, 2, 3, 4, 5]], [5, 4, 3, 2, 1]),
                        ([[3], [1, 2]], [1, 2, 3]),
                        ([[1], [2], [3], [4], [5], [6], [7]], [1, 2, 3, 4, 5, 6, 7])):
        allw = sorted(w for c in cols for w in c)
        assert sorted(order) == allw
        got = model(cols, order)
        assert got == grid(order), (cols, order, got)
    print("selftest ok")
    return 0


def main(a):
    if not a:
        watch()
        return 0
    if a and a[0] == "cycle":
        wss, _ = query()
        f = focused_ws(wss)
        cur = load().get(str(f["id"]), "scrolling") if f else "scrolling"
        step = -1 if a[1:] == ["back"] else 1
        return set_mode(MODES[(MODES.index(cur) + step) % len(MODES)])
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
            if str(ws["id"]) in _load(VIEW_W):
                restore_widths(ws["id"])
        save({})
        write_kdl(want_kdl(wss, {}, load_views()))
        return 0
    if a == ["view"]:
        print(json.dumps(load_views()))
        return 0
    if a == ["view", "reset"]:
        wss, _ = query()
        _save(VIEW, {})
        sync_kdl(wss, load(), {})
        return 0
    if len(a) == 2 and a[0] == "view" and a[1] in VIEWS + ("toggle",):
        return set_view(a[1])
    if a == ["check"]:
        return check()
    if a == ["selftest"]:
        return selftest()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
