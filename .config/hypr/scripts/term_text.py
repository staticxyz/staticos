#!/usr/bin/env python3
"""Подставить настоящий текст терминала вместо распознанного.

    term_text.py < распознанное.txt      -> точный текст или код возврата 1

Зачем. Шрифт терминала — PxPlus HP 100LX 6x8, растровый: буква занимает сетку
6x8 точек, и у «y» с «u», «g» с «a», «/» с «s» в ней просто нет различающих
пикселей. Замерено на образце: сколько ни готовь картинку (7 способов
подготовки x 3 набора языков), tesseract даёт 88 % символов и ни разу не
выдаёт строку, которую можно вставить и выполнить.

Но если текст снят с окна kitty, угадывать его незачем: kitty отдаёт свой
экран дословно по управляющему сокету. Геометрию окна при этом считать не
нужно — распознанного текста хватает как приметы: он сверяется с экранами
всех окон kitty, и побеждает тот, где совпадение строк наибольшее. Дальше
возвращаются НАСТОЯЩИЕ строки в найденном диапазоне.

Подмена происходит, только если окно найдено уверенно: больше половины строк
должны узнаться каждая не хуже 0.6, иначе скрипт молчит и в буфер уходит
распознанный текст как есть. Проверено на постороннем тексте — он набирает
на чужих экранах до 0.45 и порога не берёт.
"""
import difflib
import glob
import json
import subprocess
import sys

GOOD_ENOUGH = 0.80     # столько — и дальше не ищем
# Порог подобран замером: случайный текст набирает на чужом экране до 0.45
# (совпадают пробелы и частые буквы), а честно распознанная строка — 0.85+.
MIN_MATCH = 0.60
TIMEOUT = 3


def kitty(sock, *args):
    try:
        r = subprocess.run(["kitty", "@", "--to", "unix:" + sock, *args],
                           capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def focused_pid():
    """pid процесса, которому принадлежит окно в фокусе (по niri)."""
    try:
        out = subprocess.run(["niri", "msg", "-j", "windows"],
                             capture_output=True, text=True, timeout=TIMEOUT).stdout
        for w in json.loads(out or "[]"):
            if w.get("is_focused"):
                return w.get("pid")
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None


def sockets():
    """Сокеты kitty: окно в фокусе первым — с него совпадение обычно и ловится."""
    found = sorted(glob.glob("/tmp/kitty-*"))
    pid = focused_pid()
    first = "/tmp/kitty-%d" % pid if pid else None
    if first in found:
        found.remove(first)
        found.insert(0, first)
    return found


def screens(sock):
    """[(подпись, строки экрана)] для каждого окна этого процесса kitty."""
    raw = kitty(sock, "ls")
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    out = []
    for osw in data:
        for tab in osw.get("tabs", []):
            for w in tab.get("windows", []):
                text = kitty(sock, "get-text", "--match", "id:%d" % w["id"],
                             "--extent", "screen")
                if text is None:
                    continue
                lines = [ln.rstrip() for ln in text.split("\n")]
                if any(ln.strip() for ln in lines):
                    out.append((w.get("title") or "kitty", lines))
    return out


def score(ocr_lines, screen_lines):
    """Насколько распознанное похоже на этот экран + куда легли края."""
    hits = []
    for line in ocr_lines:
        best, best_i = 0.0, None
        for i, s in enumerate(screen_lines):
            if not s.strip():
                continue
            r = difflib.SequenceMatcher(None, line, s).ratio()
            if r > best:
                best, best_i = r, i
        hits.append((best, best_i))
    if not hits:
        return 0.0, None, None
    mean = sum(h[0] for h in hits) / len(hits)
    rows = [i for r, i in hits if i is not None and r >= MIN_MATCH]
    # Узнаться должно большинство строк, а не одна удачная: иначе случайное
    # совпадение пробелов в длинной строке утащило бы за собой чужое окно.
    if len(rows) * 2 < len(hits) or mean < MIN_MATCH:
        return mean, None, None
    return mean, min(rows), max(rows)


def main():
    ocr = sys.stdin.read()
    ocr_lines = [ln.strip() for ln in ocr.split("\n") if len(ln.strip()) >= 4]
    if not ocr_lines:
        return 1

    best = (0.0, None, None, None)      # оценка, строки, начало, конец
    for sock in sockets():
        for title, lines in screens(sock):
            mean, lo, hi = score(ocr_lines, lines)
            if lo is not None and mean > best[0]:
                best = (mean, lines, lo, hi)
            if best[0] >= GOOD_ENOUGH:
                break
        if best[0] >= GOOD_ENOUGH:
            break

    mean, lines, lo, hi = best
    if lines is None or mean < MIN_MATCH:
        return 1
    chunk = [ln.rstrip() for ln in lines[lo:hi + 1]]
    while chunk and not chunk[0].strip():
        chunk.pop(0)
    while chunk and not chunk[-1].strip():
        chunk.pop()
    if not chunk:
        return 1
    sys.stdout.write("\n".join(chunk))
    sys.stderr.write("совпадение %.0f%%\n" % (mean * 100))
    return 0


if __name__ == "__main__":
    sys.exit(main())
