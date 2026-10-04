#!/usr/bin/env python3
"""Переключатели «Настроек» для сеанса Niri.

    niri_state.py apply     применить состояние к ~/.config/niri/config.kdl
    niri_state.py adopt     наоборот: записать в состояние то, что в конфиге
    niri_state.py show      что сейчас стоит в конфиге

В Hyprland эти настройки меняются на лету одной командой (`hyprctl eval`).
В Niri такой ручки нет вовсе: скругление, центрирование колонки, фокус по
наведению и прозрачность Obsidian живут в конфиге. Поэтому здесь конфиг
правится по строкам и перечитывается — значения берутся из тех же файлов
состояния, что и в Hyprland, так что переключатель один на оба сеанса.

Правится ровно четыре строки, всё остальное не трогается. Перед подменой
конфиг проверяется (`niri validate`) на временной копии: сломанный конфиг
Niri не примет, и лучше узнать об этом до записи, а не после (21.09.2026).

С 29.09.2026 конфиг разложен по файлам: config.kdl подключает cfg/*.kdl.
Строки ищутся по ВСЕМ файлам в порядке подключения — так же, как если бы это
был один текст, — и правится тот файл, где строка нашлась. Проверка идёт на
копии всей папки niri, а записываются только изменённые файлы.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

CONFIG = os.path.expanduser("~/.config/niri/config.kdl")
NIRI_DIR = os.path.dirname(CONFIG)


def config_files():
    """config.kdl и подключённые им файлы из cfg/ — в порядке подключения.

    Порядок важен: niri читает подключённое так, будто текст вставлен на место
    include, поэтому «первая строка в тексте» — это первая по этому порядку.
    """
    files = [CONFIG]
    try:
        text = open(CONFIG, encoding="utf-8").read()
    except OSError:
        return files
    for m in re.finditer(r'^\s*include\s+(?:optional=\S+\s+)?"([^"]+)"', text, re.M):
        path = os.path.expanduser(m.group(1))
        if not os.path.isabs(path):
            path = os.path.join(NIRI_DIR, path)
        # только свои файлы: палитру matugen и правила дашборда пишут другие
        if path.startswith(os.path.join(NIRI_DIR, "cfg") + os.sep) and os.path.exists(path):
            files.append(path)
    return files


def read_all():
    """[(путь, текст)] в порядке подключения и склеенный текст для поиска."""
    parts = []
    for path in config_files():
        try:
            parts.append((path, open(path, encoding="utf-8").read()))
        except OSError:
            pass
    return parts, "\n".join(t for _, t in parts)
STATE = os.path.expanduser("~/.config/hypr/state")


def read_state(name, default):
    try:
        with open(os.path.join(STATE, name)) as f:
            return f.read().strip()
    except OSError:
        return default


def desired():
    """Что должно стоять в конфиге по переключателям «Настроек»."""
    try:
        rounding = max(0, min(24, int(read_state("window-rounding", "4"))))
    except ValueError:
        rounding = 4
    try:
        obsidian = max(50, min(100, int(read_state("obsidian-opacity", "96"))))
    except ValueError:
        obsidian = 96
    return {
        "rounding": rounding,
        "center": read_state("ribbon-center", "fit") == "center",
        "mouse_focus": read_state("mouse-focus", "detached") == "follow",
        "obsidian": obsidian,
    }


def patch(text, want, skip=None):
    """Вернуть текст с новыми значениями (и сколько строк изменилось).

    skip — множество правил, уже найденных в файлах раньше по порядку: их здесь
    не ищем (правило правит первое вхождение во всём конфиге). Найденные сюда же
    и добавляются.
    """
    changed = 0
    skip = set() if skip is None else skip

    def sub(key, pattern, repl, s, flags=re.M):
        nonlocal changed
        if key in skip:
            return s
        new, n = re.subn(pattern, repl, s, count=1, flags=flags)
        if n:
            skip.add(key)
            if new != s:
                changed += 1
        return new

    text = sub("rounding", r"^(\s*geometry-corner-radius\s+)\d+",
               lambda m: m.group(1) + str(want["rounding"]), text)
    text = sub("rounding-note", r"^(\s*//\s*Скругление углов — state/window-rounding = )\d+",
               lambda m: m.group(1) + str(want["rounding"]), text)
    text = sub("center", r'^(\s*center-focused-column\s+)"[a-z-]+"',
               lambda m: m.group(1) + ('"always"' if want["center"] else '"never"'), text)
    text = sub("mouse", r'^(\s*)(?://\s*)?(focus-follows-mouse max-scroll-amount="0%")',
               lambda m: m.group(1) + ("" if want["mouse_focus"] else "// ") + m.group(2), text)

    # Прозрачность Obsidian — строка opacity в правиле сразу после его пометки.
    mark = "// Obsidian — state/obsidian-opacity"
    i = text.find(mark) if "obsidian" not in skip else -1
    if i >= 0:
        skip.add("obsidian")
        head, tail = text[:i], text[i:]
        before = tail
        tail = re.sub(r"^(\s*opacity\s+)[\d.]+",
                      lambda m: m.group(1) + "%.2f" % (want["obsidian"] / 100.0),
                      tail, count=1, flags=re.M)
        tail = re.sub(r"(state/obsidian-opacity = )\d+",
                      lambda m: m.group(1) + str(want["obsidian"]), tail, count=1)
        if tail != before:
            changed += 1
        text = head + tail
    return text, changed


def reload_config():
    r = subprocess.run(["niri", "msg", "action", "load-config-file"],
                       capture_output=True, text=True)
    return (r.stdout + r.stderr).strip() or "конфиг перечитан"


def apply():
    parts, _ = read_all()
    if not parts:
        return "конфиг Niri не читается"
    want = desired()
    # Каждое правило правит ПЕРВОЕ вхождение во всём тексте. Поэтому идём по
    # файлам в порядке подключения и, найдя строку в одном, в следующих её уже
    # не ищем — ровно как было в едином файле.
    done = set()
    changed_files, total = {}, 0
    for path, text in parts:
        new, n = patch(text, want, skip=done)
        if n:
            changed_files[path] = new
            total += n
    if not total:
        return "в конфиге уже то, что нужно"

    tmpdir = tempfile.mkdtemp(prefix="niri-state-")
    try:
        # копия всей папки: include ищет файлы относительно config.kdl
        shutil.copytree(NIRI_DIR, os.path.join(tmpdir, "niri"), symlinks=True,
                        ignore=shutil.ignore_patterns("*.bak*", "backup*"))
        for path, new in changed_files.items():
            rel = os.path.relpath(path, NIRI_DIR)
            with open(os.path.join(tmpdir, "niri", rel), "w", encoding="utf-8") as f:
                f.write(new)
        r = subprocess.run(["niri", "validate", "-c", os.path.join(tmpdir, "niri", "config.kdl")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            return "конфиг не прошёл проверку, ничего не меняю: %s" % \
                (r.stderr or r.stdout).strip().splitlines()[-1:]
        for path, new in changed_files.items():
            tmp = path + ".niri-state.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(new)
            shutil.copystat(path, tmp)
            os.replace(tmp, path)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
    names = ", ".join(os.path.relpath(p, NIRI_DIR) for p in changed_files)
    return "строк изменено: %d (%s); %s" % (total, names, reload_config())


def adopt():
    """Взять за истину конфиг и записать его значения в файлы состояния.

    Нужно один раз при переходе на Niri: конфиг там настроен руками, а файлы
    состояния остались от Hyprland. Без этого первое же применение молча
    переставило бы настройки Niri под старые переключатели.
    """
    parts, text = read_all()
    if not parts:
        return "конфиг Niri не читается"
    got = {}
    m = re.search(r"^\s*geometry-corner-radius\s+(\d+)", text, re.M)
    if m:
        got["window-rounding"] = m.group(1)
    m = re.search(r'^\s*center-focused-column\s+"([a-z-]+)"', text, re.M)
    if m:
        got["ribbon-center"] = "center" if m.group(1) == "always" else "fit"
    m = re.search(r'^(\s*)(//\s*)?focus-follows-mouse', text, re.M)
    if m:
        got["mouse-focus"] = "detached" if m.group(2) else "follow"
    i = text.find("// Obsidian — state/obsidian-opacity")
    if i >= 0:
        m = re.search(r"^\s*opacity\s+([\d.]+)", text[i:], re.M)
        if m:
            got["obsidian-opacity"] = str(int(round(float(m.group(1)) * 100)))
    os.makedirs(STATE, exist_ok=True)
    for name, value in got.items():
        with open(os.path.join(STATE, name), "w") as f:
            f.write(value + "\n")
    return "перенесено из конфига: " + ", ".join("%s=%s" % kv for kv in sorted(got.items()))


def show():
    parts, text = read_all()
    if not parts:
        return "конфиг Niri не читается"
    out = []
    for name, pattern in (("скругление", r"^\s*geometry-corner-radius\s+\d+"),
                          ("центр колонки", r'^\s*center-focused-column\s+"[a-z-]+"'),
                          ("фокус по наведению", r'^\s*(?://\s*)?focus-follows-mouse.*')):
        m = re.search(pattern, text, re.M)
        out.append("%-20s %s" % (name, m.group(0).strip() if m else "не найдено"))
    # Строк opacity в конфиге много — нужна та, что под пометкой Obsidian.
    i = text.find("// Obsidian — state/obsidian-opacity")
    m = re.search(r"^\s*opacity\s+[\d.]+", text[i:], re.M) if i >= 0 else None
    out.append("%-20s %s" % ("Obsidian", m.group(0).strip() if m else "не найдено"))
    return "\n".join(out)


def main():
    args = sys.argv[1:] or ["apply"]
    if args[0] == "apply":
        print(apply())
        return 0
    if args[0] == "adopt":
        print(adopt())
        return 0
    if args[0] == "show":
        print(show())
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
