#!/usr/bin/env python3
"""История буфера обмена с миниатюрами — SUPER+ALT+V (19.09.2026).

Было: `cliphist list | rofi -dmenu`, и картинки показывались строкой
«[[ binary data 1 MiB png 1914x1079 ]]» — разобрать, какая из них какая,
нельзя (просьба пользователя: «сделать отображение скриншотов, а не текста»).

Стало: один список, у картинок — миниатюра. Высота строки в rofi одна на весь
список, поэтому размер значка выбран средним (64 px, clipboard.rasi): картинку
видно, а текстовые строки не раздуваются. Пробовал два списка с переключением
по Tab — пользователь попросил проще: «покажи их одним размером, с балансом
посередине» (19.09.2026). Миниатюры 240x135 лежат в ~/.cache/cliphist-thumbs/<номер>.png и
делаются один раз (0,03 с на штуку); при каждом открытии готовятся только для
первых THUMB_LIMIT записей, чтобы меню открывалось мгновенно даже когда в
истории сотни картинок. Остальные остаются подписью, как раньше.

Выбор возвращается номером строки (`rofi -format i`), а не текстом: подписи
могут повторяться, а номер записи cliphist по ним не восстановить.
Выбранное кладётся обратно в буфер — дальше Ctrl+V, как и было.

Вид — ~/.config/rofi/clipboard.rasi: тот же стиль, что у лаунчера, только
строки чуть выше и значок 64 px.

Клавиши: Ctrl+J / Ctrl+K и Alt+J / Alt+K — вниз и вверх по списку (просьба
пользователя 19.09.2026). Без модификатора нельзя: строка поиска съедает буквы.
С 23.09.2026 они прописаны для всех меню сразу в ~/.config/rofi/config.rasi
(там же — их русские двойники Cyrillic_o / Cyrillic_el), здесь ничего не
переназначается: свой -kb-… перекрыл бы общий список и потерял русскую
раскладку.

Пробел (04.10.2026) — то же, что Enter: скопировать выбранную запись. Backspace — выйти
(как Escape); стирать в поиске — Control+h.

Удаление (28.09.2026): Delete — выделенную запись, меню открывается снова на той же
строке; Shift+Delete — вся история разом, после вопроса «точно?». Одиночный
Backspace остался за строкой поиска — иначе в истории нельзя было бы искать.
Delete для этого снят с «стереть символ справа» (остался Ctrl+D).
"""
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

THUMBS = os.path.expanduser("~/.cache/cliphist-thumbs")
THEME = os.path.expanduser("~/.config/rofi/clipboard.rasi")
THUMB_LIMIT = 60          # для скольких первых записей готовить миниатюры
THUMB_SIZE = "240x135"
# Delete → kb-custom-1 (код 10), Shift+Delete → kb-custom-2 (код 11). Delete снят с
# remove-char-forward, Shift+Delete — со встроенного delete-entry rofi.
# Пробел тоже выбирает запись, Backspace — выход (04.10.2026, просьба пользователя: «Backspace
# выйти, Space копировать»). Цена: в строке поиска нельзя набрать пробел и стереть
# символ Backspace'ом (остался Control+h); искать приходится одним словом, а передумал —
# Control+h или заново. Backspace снят с «стереть символ», иначе две привязки на одну клавишу.
KEYS = ["-kb-accept-entry", "Control+m,Return,KP_Enter,space",
        "-kb-cancel", "Escape,Control+g,Control+bracketleft,BackSpace",
        "-kb-remove-char-back", "Control+h",
        "-kb-remove-char-forward", "Control+d", "-kb-delete-entry", "",
        "-kb-custom-1", "Delete", "-kb-custom-2", "Shift+Delete"]
DELETE_ONE, DELETE_ALL = 10, 11
BINARY = re.compile(r"^\[\[\s*binary data\s+(\S+\s+\S+)\s+(\w+)\s+(\d+x\d+)")


def entries():
    """[(номер, подпись)] — как отдаёт cliphist, новое сверху."""
    out = subprocess.run(["cliphist", "list"], capture_output=True, text=True).stdout
    items = []
    for line in out.splitlines():
        cid, _, preview = line.partition("\t")
        if cid:
            items.append((cid, preview))
    return items


def thumb(cid):
    """Миниатюра записи; None — если это не картинка или не вышло."""
    path = os.path.join(THUMBS, cid + ".png")
    if os.path.isfile(path):
        return path
    os.makedirs(THUMBS, exist_ok=True)
    tmp = path + ".tmp.png"
    try:
        raw = subprocess.run(["cliphist", "decode", cid], capture_output=True, timeout=10).stdout
        if not raw:
            return None
        r = subprocess.run(["magick", "-", "-thumbnail", THUMB_SIZE, "-background", "none",
                            "-gravity", "center", "-extent", THUMB_SIZE, "png:" + tmp],
                           input=raw, capture_output=True, timeout=20)
        if r.returncode != 0:
            return None
        os.replace(tmp, path)
        return path
    except (OSError, subprocess.SubprocessError):
        return None


def prune(keep):
    """Убрать миниатюры записей, которых в истории уже нет."""
    try:
        for name in os.listdir(THUMBS):
            if name.endswith(".png") and name[:-4] not in keep:
                os.remove(os.path.join(THUMBS, name))
    except OSError:
        pass


def label(preview):
    m = BINARY.match(preview)
    if m:
        size, kind, dims = m.groups()
        return "\U000f02e9  %s · %s · %s" % (dims, kind, size)   # nf-md-image
    return preview


def rows_for(items):
    """Строки меню: у картинок значок-миниатюра (для первых THUMB_LIMIT)."""
    icons = {}
    todo = [cid for cid, preview in items[:THUMB_LIMIT] if BINARY.match(preview)]
    if todo:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for cid, path in zip(todo, pool.map(thumb, todo)):
                if path:
                    icons[cid] = path
    rows = []
    for cid, preview in items:
        icon = icons.get(cid)
        rows.append(label(preview) + ("\0icon\x1f" + icon if icon else ""))
    return rows


def delete(cid, preview):
    subprocess.run(["cliphist", "delete"], input=cid + "\t" + preview + "\n", text=True)
    try:
        os.remove(os.path.join(THUMBS, cid + ".png"))
    except OSError:
        pass


def confirm_wipe():
    """Спросить перед очисткой всей истории: её не вернуть."""
    r = subprocess.run(["rofi", "-dmenu", "-i", "-p", "Очистить всю историю?", "-format", "i",
                        "-theme", THEME, "-no-custom"],
                       input="Нет\nДа, очистить всё", capture_output=True, text=True)
    return r.stdout.strip() == "1"


def main():
    row = 0
    while True:
        items = entries()
        if not items:
            return 0
        prune({cid for cid, _ in items})

        rows = rows_for(items)
        if "--dry-run" in sys.argv:            # проверка без окна
            print("строк: %d" % len(rows))
            print("\n".join(rows[:6]))
            return 0

        r = subprocess.run(["rofi", "-dmenu", "-i", "-p", "\U000f014c", "-format", "i",
                            "-show-icons", "-theme", THEME,
                            "-selected-row", str(min(row, len(rows) - 1))] + KEYS,
                           input="\n".join(rows), capture_output=True, text=True)
        sel = r.stdout.strip()
        if r.returncode == DELETE_ALL:
            if confirm_wipe():
                subprocess.run(["cliphist", "wipe"])
                prune(set())
                return 0
            continue
        if not sel.isdigit():
            return 0
        row = int(sel)
        if r.returncode == DELETE_ONE:
            delete(*items[row])
            continue
        data = subprocess.run(["cliphist", "decode", items[row][0]], capture_output=True).stdout
        if data:
            subprocess.run(["wl-copy"], input=data)
        return 0


if __name__ == "__main__":
    sys.exit(main())
