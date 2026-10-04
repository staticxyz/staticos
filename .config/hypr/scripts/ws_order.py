#!/usr/bin/env python3
"""Свой порядок рабочих столов в баре — без перемещения окон.

ЗАЧЕМ
Прошлый механизм «вставить стол» физически переносил окна на соседний стол.
Hyprland раскладывает пришедшие окна заново, поэтому выверенные вручную размеры
и структура сплитов терялись при каждом нажатии. Здесь окна не двигаются вообще.

КАК
У стола в Hyprland две разные вещи: НОМЕР (id) и ПОДПИСЬ (name). Подпись
целиком собирается здесь, и waybar показывает её как есть (format: {name}):

    <N символов нулевой ширины> <номер> <значки приложений>

Символы U+200B невидимы — это метка места. Waybar сортирует столы по подписи
(sort-by: name), и подпись с одним таким символом встаёт раньше подписи с
двумя. Так порядок в баре меняется, не трогая ни номера, ни окна. (Раньше
метка была видимыми цифрами "0010", "0020"… и пряталась за format: {id}.)

Значки — по ОДНОМУ на приложение, без повторов: пять окон kitty дают один
значок kitty, а не пять. Правила берутся из window-rewrite в config.jsonc
waybar — таблица одна на всё — и применяются так же, как у waybar: поиск по
строке "class<КЛАСС> title<ЗАГОЛОВОК>" без учёта регистра; правило с классом
и заголовком главнее правила только с заголовком, а то — главнее правила
только с классом. Подпись переписывается, только когда её вид изменился.

Порядок хранится списком номеров в ~/.local/state/hypr/ws-order.json. Он и есть
источник истины; подписи каждый раз пересчитываются из него заново. Так метки
не «разъезжаются» после ручных правок и не нужна арифметика с дробными ключами.

Метки живут только в памяти Hyprland и после его перезапуска пропадают —
поэтому режим watch применяет их при старте и следит за появлением новых столов.

Режимы:
  apply              пересчитать и проставить подписи по сохранённому порядку
  insert [left|right] новый стол рядом с текущим, по умолчанию справа
                     (получает наименьший свободный номер)
  move left|right    подвинуть текущий стол в порядке
  remove             убрать текущий стол (только если он пуст)
  go prev|next       перейти на соседний стол ПО ВИДИМОМУ порядку, не по номеру
  send prev|next     перенести текущее окно на соседний стол по тому же порядку
  watch              применить и следить за событиями Hyprland (для автозапуска)
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading

STATE_DIR = os.path.expanduser("~/.local/state/hypr")
STATE = os.path.join(STATE_DIR, "ws-order.json")

# Метка места — N символов нулевой ширины в начале подписи (см. шапку).
ZW = "\u200b"
# Значки одного стола стоят вплотную — один пробел: совсем без пробела значки
# Nerd Font налезут друг на друга, они рисуются шире своей ячейки. Цифра стола
# отделена от них обычным пробелом: без него лента выглядит хуже (проверено
# 20.09.2026).
SEP = " "
# У пустого стола подпись — пробел, цифра и пустая ячейка Nerd Font (U+2800,
# брайлевский пробел). Ячейка нужна для высоты: без знака Nerd Font строку
# рисует один Hack, она на 1 px ниже, и цифра сидела выше соседей. Пробел
# слева возвращает цифру в середину кнопки. Слева именно пробел, а не такая
# же ячейка: подписи сортируются как строки, и U+2800 в начале уводил пустой
# стол в конец ленты (замечено 20.09.2026).
BLANK = "\u2800"
# Правила значков окон — те же, что у waybar, прямо из его конфига.
WAYBAR_CONFIG = os.path.expanduser("~/.config/waybar/config.jsonc")
# События, после которых подписи пересчитываются: столы появляются и исчезают
# (метка места), окна открываются, закрываются, переезжают и меняют заголовок
# (значки: у kitty значок зависит от заголовка).
WATCH_EVENTS = {"createworkspace", "createworkspacev2", "destroyworkspace",
                "destroyworkspacev2", "openwindow", "closewindow",
                "movewindow", "movewindowv2", "windowtitle", "windowtitlev2"}


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def dispatch(expr):
    r = subprocess.run(["hyprctl", "dispatch", expr], capture_output=True, text=True)
    return (r.stdout or "").strip()


def lua_call(call, fallback):
    """Вызвать глобальную Lua-функцию конфига (ws_goto / ws_send из ws_anim.lua):
    она ставит направление сдвига по НАШЕМУ порядку столов, а не по номерам.
    Если функции нет (конфиг без ws_anim.lua) — прежний диспетчер."""
    r = subprocess.run(["hyprctl", "eval", call], capture_output=True, text=True)
    if (r.stdout or "").strip() != "ok":
        dispatch(fallback)


def notify(text):
    """Короткое уведомление.

    Отказ без единого признака выглядит как «бинд сломан» — этой ошибки в
    прошлом уже хватило. Низкий приоритет, чтобы не лезть поверх важного.
    """
    subprocess.run(["notify-send", "-u", "low", "-t", "2500",
                    "Рабочие столы", text], capture_output=True)


def workspace_window_count(ws):
    try:
        for w in json.loads(hypr("workspaces", "-j")):
            if w["id"] == ws:
                return w.get("windows", 0)
    except (ValueError, KeyError):
        pass
    return 0


def workspace_monitors():
    """Какому монитору принадлежит каждый стол."""
    try:
        return {w["id"]: w["monitor"]
                for w in json.loads(hypr("workspaces", "-j")) if w["id"] > 0}
    except (ValueError, KeyError):
        return {}


def same_monitor_slice(order, current):
    """Позиции в общем порядке, относящиеся к монитору текущего стола.

    Порядок один на всю систему, а бары показывают каждый свои столы
    (all-outputs: false). Столы двух мониторов в общем списке чередуются:
    у нас, например, DP-4 держит 1,3,4,5,6,7, а eDP-1 — 2,8,9,10,11. Поэтому
    «следующий по порядку» без этого фильтра уводил на соседний экран, и со
    стороны выглядело как переход по номерам.
    """
    mons = workspace_monitors()
    mine = mons.get(current)
    if mine is None:
        return [i for i, _ in enumerate(order)]
    return [i for i, ws in enumerate(order) if mons.get(ws) == mine]


def existing_workspaces():
    """Номера обычных столов. Спецстолы (id < 0) в порядок не входят."""
    try:
        return sorted(w["id"] for w in json.loads(hypr("workspaces", "-j"))
                      if w["id"] > 0)
    except (ValueError, KeyError):
        return []


def current_workspace():
    try:
        return json.loads(hypr("activeworkspace", "-j"))["id"]
    except (ValueError, KeyError):
        return 0


def load_order():
    try:
        with open(STATE) as f:
            return [int(x) for x in json.load(f)["order"]]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def save_order(order):
    os.makedirs(STATE_DIR, exist_ok=True)
    if load_order() == order:
        return      # не переписывать файл на каждое событие окна
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"order": order}, f)
    os.replace(tmp, STATE)      # атомарно: не оставит обрезанный файл


def reconcile(order, existing):
    """Согласовать сохранённый порядок с тем, что реально есть.

    Исчезнувшие столы выпадают, новые (созданные мимо этого скрипта — SUPER+5,
    перенос окна на новый стол) дописываются в конец. Порядок остальных
    сохраняется.
    """
    seen = set()
    result = []
    for ws in order:
        if ws in existing and ws not in seen:
            result.append(ws)
            seen.add(ws)
    for ws in existing:
        if ws not in seen:
            result.append(ws)
            seen.add(ws)
    return result


def rewrite_rules():
    """Правила значков из window-rewrite waybar: [(приоритет, №, regex, глиф)]."""
    try:
        raw = open(WAYBAR_CONFIG, encoding="utf-8").read()
        ws = json.loads(re.sub(r"^\s*//.*$", "", raw, flags=re.M)).get(
            "hyprland/workspaces", {})
    except (OSError, ValueError):
        return [], ""
    rules = []
    for i, (pat, glyph) in enumerate(ws.get("window-rewrite", {}).items()):
        prio = (2 if "title<" in pat else 0) + (1 if "class<" in pat else 0)
        try:
            rules.append((prio, i, re.compile(pat, re.I), glyph))
        except re.error:
            continue
    rules.sort(key=lambda r: (-r[0], r[1]))
    return rules, ws.get("window-rewrite-default", "")


def workspace_icons():
    """{номер стола: [глифы]} — по одному на приложение, СЛЕВА НАПРАВО.

    Порядок по положению окна, а не по времени открытия: hyprctl clients
    отдаёт окна в порядке создания, и позже открытый браузер, стоящий в ленте
    первым, оказывался в баре последним (20.09.2026: «считаю это
    нечестным»). Сортировка по x, затем по y — как окна и стоят на экране.
    """
    rules, default = rewrite_rules()
    try:
        clients = json.loads(hypr("clients", "-j"))
    except ValueError:
        return {}
    clients.sort(key=lambda c: (c.get("at", [0, 0])[0], c.get("at", [0, 0])[1]))
    icons = {}
    for c in clients:
        ws = c.get("workspace", {}).get("id", 0)
        if ws < 1:
            continue
        subject = "class<%s> title<%s>" % (c.get("class", ""), c.get("title", ""))
        glyph = next((g for _p, _i, rx, g in rules if rx.search(subject)), default)
        seen = icons.setdefault(ws, [])
        if glyph and glyph not in seen:
            seen.append(glyph)
    return icons


def apply_names(order):
    """Проставить подписи: метка места, номер, значки. Только изменившиеся."""
    icons = workspace_icons()
    try:
        current = {w["id"]: w["name"] for w in json.loads(hypr("workspaces", "-j"))}
    except (ValueError, KeyError):
        current = {}
    for i, ws in enumerate(order):
        if icons.get(ws):
            text = "%d %s" % (ws, SEP.join(icons[ws]))
        else:
            text = " %d%s" % (ws, BLANK)
        name = ZW * (i + 1) + text
        if current.get(ws) == name:
            continue
        dispatch('hl.dsp.workspace.rename({ workspace = %d, name = "%s" })'
                 % (ws, name))


def resolve():
    """Согласовать со списком существующих столов и сохранить. БЕЗ подписей.

    Отдельно от sync() намеренно: подпись каждого стола — это отдельный вызов
    hyprctl, и делать их на каждое переключение стола незачем. Переходу нужен
    только порядок, а не проставленные метки.
    """
    order = reconcile(load_order(), existing_workspaces())
    save_order(order)
    return order


def sync():
    """Согласовать, сохранить и проставить подписи. Возвращает порядок."""
    order = resolve()
    apply_names(order)
    return order


def create_beside(order, current, side="after"):
    """Создать стол рядом с current: наименьший свободный номер, своя позиция.

    Номера существующих столов не меняются, двигается только позиция нового в
    списке. Поэтому «стол слева» получает наименьший СВОБОДНЫЙ номер, а не
    обязательно на единицу меньше соседа: если свободна единица — будет 1,
    если нет — первый незанятый.
    """
    taken = set(order)
    new = 1
    while new in taken:
        new += 1

    if current in order:
        pos = order.index(current) + (1 if side == "after" else 0)
    else:
        pos = len(order) if side == "after" else 0
    order.insert(pos, new)

    # Стол не существует, пока на него не перейдёшь, а переименовать
    # несуществующий нельзя — поэтому сначала переход, потом подписи.
    dispatch("hl.dsp.focus({ workspace = %d })" % new)
    save_order(order)
    apply_names(order)
    return 0


def cmd_insert(side="after"):
    """Новый стол рядом с текущим: справа ("after") или слева ("before").

    Номер — наименьший свободный: существующие столы своих номеров не меняют,
    меняется только позиция нового в списке.
    """
    order = reconcile(load_order(), existing_workspaces())
    current = current_workspace()
    if current < 1:
        return 0
    return create_beside(order, current, side)


def cmd_move(direction):
    """Подвинуть текущий стол влево или вправо — обмен метками с соседом."""
    order = resolve()
    current = current_workspace()
    if current not in order:
        return 0

    slots = same_monitor_slice(order, current)
    i = order.index(current)
    k = slots.index(i)
    k = k - 1 if direction == "left" else k + 1
    if not 0 <= k < len(slots):
        return 0                # уже с краю своего бара
    j = slots[k]

    order[i], order[j] = order[j], order[i]
    save_order(order)
    apply_names(order)
    return 0


def cmd_remove():
    """Убрать текущий стол из порядка и уйти с него.

    Только если он ПУСТ. Стол в Hyprland исчезает сам, когда на нём нет окон и
    с него ушли, — поэтому «удаление» здесь это выкинуть его из порядка и
    перейти к соседу.

    Непустой стол не трогаем намеренно. Деть его окна можно лишь двумя
    способами: закрыть (потеря работы) или перенести на соседний стол — а
    перенос заново раскладывает окна, ровно то, из-за чего весь этот механизм
    и переписывался. Молча делать ни то ни другое нельзя.
    """
    order = resolve()
    current = current_workspace()
    if current < 1 or current not in order:
        return 0

    if len(order) < 2:
        notify("Это единственный стол")
        return 0

    n = workspace_window_count(current)
    if n:
        notify("На столе %d ещё %d окно(а) — сначала освободи его" % (current, n))
        return 0

    slots = same_monitor_slice(order, current)
    k = slots.index(order.index(current))
    neighbour = order[slots[k - 1]] if k > 0 else (
        order[slots[k + 1]] if k + 1 < len(slots) else None)
    if neighbour is None:
        notify("Это единственный стол на экране")
        return 0

    order.remove(current)
    dispatch("hl.dsp.focus({ workspace = %d })" % neighbour)
    save_order(order)
    apply_names(order)
    return 0


def cmd_go(direction):
    """Переход на соседний стол ПО ВИДИМОМУ порядку.

    Штатные e+1/r+1 у Hyprland идут по номерам: он про порядок в баре не знает.
    При своём порядке это выглядело бы как прыжок назад.
    """
    order = resolve()
    current = current_workspace()
    # len(order) < 2 здесь раньше тоже стояло, но оно глушило край при
    # единственном столе: слева и справа не создавалось ничего.
    if current not in order:
        return 0

    slots = same_monitor_slice(order, current)
    k = slots.index(order.index(current))
    k = k - 1 if direction == "prev" else k + 1
    if not 0 <= k < len(slots):
        # Упёрлись в край — создаём стол с этой стороны.
        #
        # Раньше влево не создавалось: я повторил поведение штатного r-1,
        # который с первого стола ничего не делает. На практике это выглядело
        # тупиком — вправо стол появляется, влево упираешься в стену. Края
        # теперь симметричны.
        return create_beside(order, current,
                             "after" if direction == "next" else "before")
    lua_call("ws_goto(%d)" % order[slots[k]], "hl.dsp.focus({ workspace = %d })" % order[slots[k]])
    return 0


def cmd_send(direction):
    """Перенести текущее окно на соседний стол ПО ВИДИМОМУ порядку.

    Ровно та же беда, что была у перехода: штатный r+1/r-1 идёт по НОМЕРАМ
    столов, а номера при своём порядке не совпадают с тем, что видно в баре.
    Со стороны это выглядит как перенос окна «куда-то не туда» — например с
    первого стола вправо окно уезжало на второй по номеру, а он в баре может
    стоять пятым.

    Края обрабатываются как в cmd_go: если соседа нет, создаётся новый стол с
    этой стороны и окно уезжает туда. Иначе на крайнем столе бинд молчал бы.
    """
    order = resolve()
    current = current_workspace()
    if current not in order:
        return 0

    slots = same_monitor_slice(order, current)
    k = slots.index(order.index(current))
    k = k - 1 if direction == "prev" else k + 1

    if 0 <= k < len(slots):
        target = order[slots[k]]
    else:
        # Свободный номер и своя позиция в порядке — как в create_beside,
        # но стол не создаётся переходом: его создаст сам перенос окна.
        taken = set(order)
        target = 1
        while target in taken:
            target += 1
        pos = order.index(current) + (1 if direction == "next" else 0)
        order.insert(pos, target)

    lua_call("ws_send(%d)" % target, "hl.dsp.window.move({ workspace = %d })" % target)
    save_order(order)
    apply_names(order)
    return 0


def cmd_watch():
    """Применить порядок и следить за событиями Hyprland.

    Нужен по двум причинам: подписи не переживают перезапуск Hyprland, и столы,
    созданные мимо этого скрипта, иначе остались бы без метки и уехали в конец
    бара.
    """
    lock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    try:
        lock.bind("\0hypr-ws-order")     # абстрактный сокет, файла не создаёт
    except OSError:
        print("уже запущено", file=sys.stderr)
        return 0

    sync()

    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    rt = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    if not sig:
        base = os.path.join(rt, "hypr")
        try:
            sig = max(os.listdir(base),
                      key=lambda d: os.path.getmtime(os.path.join(base, d)))
        except (OSError, ValueError):
            print("Hyprland не найден", file=sys.stderr)
            return 1

    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(os.path.join(rt, "hypr", sig, ".socket2.sock"))

    timer = [None]

    def later():
        # Гасим дребезг: создание стола с окном даёт несколько событий подряд,
        # а переименование каждого стола — это отдельный вызов hyprctl.
        if timer[0] is not None:
            timer[0].cancel()
        timer[0] = threading.Timer(0.25, sync)
        timer[0].daemon = True
        timer[0].start()

    buf = b""
    while True:
        chunk = s.recv(4096)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            ev = line.decode("utf-8", "replace").split(">>")[0]
            if ev in WATCH_EVENTS:
                later()
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__, file=sys.stderr)
        return 1

    cmd = args[0]
    if cmd == "apply":
        sync()
    elif cmd == "insert" and len(args) == 1:
        return cmd_insert()
    elif cmd == "insert" and len(args) == 2 and args[1] in ("left", "right"):
        return cmd_insert("before" if args[1] == "left" else "after")
    elif cmd == "remove":
        return cmd_remove()
    elif cmd == "move" and len(args) == 2 and args[1] in ("left", "right"):
        return cmd_move(args[1])
    elif cmd == "go" and len(args) == 2 and args[1] in ("prev", "next"):
        return cmd_go(args[1])
    elif cmd == "send" and len(args) == 2 and args[1] in ("prev", "next"):
        return cmd_send(args[1])
    elif cmd == "watch":
        return cmd_watch()
    else:
        print("использование: ws_order.py apply|insert [left|right]|remove|"
              "move left|right|go prev|next|send prev|next|watch",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
