#!/usr/bin/env python3
"""Сдвинуть текущий рабочий стол вместе со всеми, что идут за ним.

Не «перенести окна на соседний стол», а именно РАЗДВИНУТЬ: если сейчас стол 4,
а 5 занят, то 4 уезжает на 5, а бывший 5 — на 6. Прошлая версия просто
сваливала окна в соседний стол поверх тех, что там уже жили.

Два момента, без которых это ломается:

  * Двигать надо начиная с ДАЛЬНЕГО стола. Если пойти от текущего вверх, то
    окна с 4 приедут на 5 раньше, чем 5 успеет освободиться, и оба набора
    смешаются — ровно то, чего мы избегаем.

  * Сдвигается только непрерывная цепочка занятых столов. Если заняты 4, 5 и
    9, то 5 уезжает на свободный 6, и трогать 9 незачем.

Режим insert — вставить пустой стол сразу после текущего. Логика сдвига та же,
только цепочка начинается не с текущего стола, а со следующего: 3 и всё, что за
ним, уезжает на +1, освободившийся слот становится новым пустым столом.

  было:  1 2 3 4      стоим на 2, жмём insert
  стало: 1 2 [3] 4 5  где [3] — новый пустой, бывший 3 стал 4

Режим collapse — обратная операция: убрать пустой стол, на котором стоим, и
стянуть всё, что за ним, обратно на -1. Вставка и схлопывание взаимно обратны:

  1 2 [3] 4 5   стоим на пустом 3, жмём collapse
  1 2 3 4       бывший 4 вернулся на 3

Стягивать можно только с ПУСТОГО стола. Если на нём есть окна, окна со
следующего приехали бы поверх — та самая беда, ради которой сдвиг идёт с
дальнего конца. В этом случае режим ничего не делает.

Порядок столов в баре — всегда по возрастанию номера (у waybar sort-by умеет
только number/name/id, режима «в порядке создания» нет). Поэтому вставить стол
с НОВЫМ номером между старыми нельзя: 4 всегда отрисуется после 3. Единственный
способ получить пустой стол именно на этом месте — сдвинуть номера, что и
делается.

Диспетчеры вызываются Lua-выражениями: конфиг Hyprland здесь на Lua, и старый
"hyprctl dispatch movetoworkspacesilent N,address:0x..." парсер отвергает.
"""
import json
import subprocess
import sys


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


LOG = "/tmp/move_all.log"


def log(msg):
    # Временная диагностика: по биндy скрипт запускается без терминала, и
    # ошибки диспетчеров иначе уходят в никуда.
    with open(LOG, "a") as f:
        f.write(msg + "\n")


def dispatch(expr):
    r = subprocess.run(["hyprctl", "dispatch", expr], capture_output=True, text=True)
    out = (r.stdout or "").strip()
    if out != "ok":
        log("  ОТВЕТ НЕ ok: %s -> %r" % (expr[:70], out[:90]))
    return out


def windows_by_workspace():
    grouped = {}
    for c in json.loads(hypr("clients", "-j")):
        grouped.setdefault(c["workspace"]["id"], []).append(c["address"])
    return grouped


def shift_chain(start, occupied, step):
    """Сдвинуть непрерывную цепочку занятых столов, начиная со start, на step.

    Двигаем с дальнего конца — иначе стол-приёмник ещё занят, и два набора окон
    смешаются.
    """
    chain = []
    ws = start
    while ws in occupied:
        chain.append(ws)
        ws += 1

    order = list(reversed(chain)) if step > 0 else list(chain)
    for ws in order:
        for addr in occupied[ws]:
            dispatch('hl.dsp.window.move({ workspace = %d, window = "address:%s",'
                     ' silent = true })' % (ws + step, addr))
    return chain


def insert_after_current():
    """Освободить стол сразу за текущим и перейти на него."""
    current = json.loads(hypr("activeworkspace", "-j"))["id"]
    if current < 1:          # спецстол — вставлять некуда
        return 0

    target = current + 1
    occupied = windows_by_workspace()

    if target not in occupied:
        # Слот и так свободен: достаточно перейти, стол создастся сам.
        log("=== insert | стол %d уже пуст" % target)
        dispatch("hl.dsp.focus({ workspace = %d })" % target)
        return 0

    chain = shift_chain(target, occupied, 1)
    log("=== insert | текущий %d | сдвинуты %s" % (current, chain))
    dispatch("hl.dsp.focus({ workspace = %d })" % target)
    return 0


def collapse_at_current():
    """Убрать пустой стол под курсором: цепочка за ним съезжает на -1."""
    current = json.loads(hypr("activeworkspace", "-j"))["id"]
    if current < 1:          # спецстол
        return 0

    occupied = windows_by_workspace()

    if current in occupied:
        # Тут есть окна. Стянуть следующий стол сюда — значит свалить два
        # набора окон в один, ровно то, чего избегает весь этот скрипт.
        log("=== collapse | стол %d не пуст, ничего не делаю" % current)
        return 0

    if current + 1 not in occupied:
        log("=== collapse | за столом %d ничего нет, стягивать нечего" % current)
        return 0

    chain = shift_chain(current + 1, occupied, -1)
    log("=== collapse | стол %d | стянуты %s" % (current, chain))
    return 0


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("next", "prev", "insert", "collapse"):
        print("использование: move_all_windows.sh next|prev|insert|collapse",
              file=sys.stderr)
        return 1

    if sys.argv[1] == "insert":
        return insert_after_current()
    if sys.argv[1] == "collapse":
        return collapse_at_current()

    step = 1 if sys.argv[1] == "next" else -1
    current = json.loads(hypr("activeworkspace", "-j"))["id"]

    # Спецстолы (скретчпад и прочие) имеют отрицательные id и в нумерацию
    # обычных столов не входят — сдвигать их бессмысленно.
    if current < 1:
        return 0

    target = current + step
    if target < 1:
        return 0

    occupied = windows_by_workspace()
    if current not in occupied:
        # Пустой стол двигать нечего — просто переходим.
        dispatch("hl.dsp.focus({ workspace = %d })" % target)
        return 0

    # Непрерывная цепочка занятых столов, начиная с текущего и вверх.
    chain = []
    ws = current
    while ws in occupied:
        chain.append(ws)
        ws += 1

    # next — с дальнего конца, prev — с ближнего: в обоих случаях стол-приёмник
    # к моменту переезда уже пуст.
    order = list(reversed(chain)) if step > 0 else list(chain)
    log("=== %s | текущий стол %d -> %d | цепочка %s | окон %d"
        % (sys.argv[1], current, target, order,
           sum(len(occupied[w]) for w in chain)))

    for ws in order:
        for addr in occupied[ws]:
            dispatch('hl.dsp.window.move({ workspace = %d, window = "address:%s",'
                     ' silent = true })' % (ws + step, addr))

    dispatch("hl.dsp.focus({ workspace = %d })" % target)
    log("=== готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
