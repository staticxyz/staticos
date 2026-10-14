#!/usr/bin/env python3
"""Свои бинды: правка клавиш в ~/.config/niri/cfg/binds.kdl (Настройки → Binds).

14.10.2026, Просьба: «В Настройки добавь раздел для настроек биндов… Чтобы каждый
пользователь мог настроить свои бинды. По умолчанию мои».

Меняется только имя клавиши в начале строки бинда — подписи, действия и комментарии
остаются как были. Перед записью новый текст проверяется `niri validate` на копии
конфига; не прошёл — файл не трогается. niri сам перечитывает binds.kdl.

Умолчание — binds.default.kdl рядом (бинды пользователя на 14.10.2026). Бинд узнаётся
там по «телу» — всему, что после клавиши (подпись + действие), и по номеру среди
одинаковых тел: Mod+H и Mod+Left оба «focus-column-left», первый к первому.
Бинд, которого в умолчании нет (добавлен позже), сбросить нельзя — он и так «свой».

    binds_edit.py list            все бинды: клавиша ⇥ умолчание ⇥ подпись
    binds_edit.py set OLD NEW     сменить клавишу (Mod+E Mod+Shift+E)
    binds_edit.py reset KEY|all   вернуть умолчание одному бинду или всем
    binds_edit.py check           самопроверка
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

NIRI_DIR = os.path.expanduser("~/.config/niri")
BINDS = os.path.join(NIRI_DIR, "cfg", "binds.kdl")
DEFAULT = os.path.join(NIRI_DIR, "cfg", "binds.default.kdl")
HERE = os.path.dirname(os.path.abspath(__file__))

# строка бинда: отступ, клавиша, тело «подпись { действие }» до конца строки
RE_LINE = re.compile(r'^(\s*)([A-Za-z0-9_+]+)(\s+[^{\n]*\{[ \t]*[^}\n]*\}.*)$')
RE_TITLE = re.compile(r'hotkey-overlay-title="([^"]*)"')
RE_ACTION = re.compile(r'\{[ \t]*([^}\n]*)\}')

MOD_ALIASES = {"mod": "Mod", "super": "Super", "win": "Super", "ctrl": "Ctrl",
               "control": "Ctrl", "alt": "Alt", "shift": "Shift", "mod3": "Mod3",
               "mod5": "Mod5", "iso_level3_shift": "Mod5", "iso_level5_shift": "Mod3"}
MOD_ORDER = ["Mod", "Super", "Ctrl", "Alt", "Shift", "Mod3", "Mod5"]


def norm(key):
    """Сочетание в одном виде для сравнения: регистр и порядок модификаторов не важны."""
    parts = [p for p in key.split("+") if p]
    if not parts:
        return ""
    mods = {MOD_ALIASES.get(p.lower(), p) for p in parts[:-1]}
    # niri: Mod — это Super (Alt только во вложенном niri, а он у нас не живёт)
    mods = {"Super" if m == "Mod" else m for m in mods}
    return "+".join(sorted(m.lower() for m in mods) + [parts[-1].lower()])


def tidy(key):
    """Сочетание в виде binds.kdl: Mod+Ctrl+Alt+Shift+Клавиша."""
    parts = [p.strip() for p in key.replace(" ", "").split("+") if p.strip()]
    if not parts:
        return ""
    mods = []
    for p in parts[:-1]:
        m = MOD_ALIASES.get(p.lower())
        if m is None:
            return ""
        m = "Mod" if m == "Super" else m
        if m not in mods:
            mods.append(m)
    mods.sort(key=MOD_ORDER.index)
    k = parts[-1]
    if MOD_ALIASES.get(k.lower()):                      # одни модификаторы — не сочетание
        return ""
    # как в binds.kdl: «E», «Grave», «Page_Up»; смешанный регистр (XF86…) — как есть
    k = k.upper() if len(k) == 1 else (k[0].upper() + k[1:] if k[0].islower() and not
                                       any(ch.isupper() for ch in k) else k)
    return "+".join(mods + [k])


def parse(text):
    """[{line, key, body, title, action, nth}] — по строкам файла, комментарии мимо."""
    out, seen = [], {}
    inside = False
    for i, ln in enumerate(text.split("\n")):
        s = ln.strip()
        if not inside:
            inside = s.startswith("binds") and s.endswith("{")
            continue
        if s.startswith("//"):
            continue
        m = RE_LINE.match(ln)
        if not m:
            continue
        body = m.group(3).strip()
        t = RE_TITLE.search(body)
        a = RE_ACTION.search(body)
        n = seen.get(body, 0)
        seen[body] = n + 1
        out.append(dict(line=i, key=m.group(2), body=body, nth=n,
                        title=t.group(1) if t else "",
                        action=(a.group(1).strip().rstrip(";").strip() if a else "")))
    return out


def read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def ensure_default():
    """Нет умолчания — им становится нынешний binds.kdl (первый запуск у нового
    пользователя: «по умолчанию» — то, что пришло с дотфайлами)."""
    if not os.path.exists(DEFAULT) and os.path.exists(BINDS):
        shutil.copy2(BINDS, DEFAULT)


def load():
    """Бинды с умолчанием: к каждому — default (клавиша из binds.default.kdl или None)."""
    ensure_default()
    cur = parse(read(BINDS))
    dflt = {(b["body"], b["nth"]): b["key"] for b in parse(read(DEFAULT))}
    for b in cur:
        b["default"] = dflt.get((b["body"], b["nth"]))
    return cur


def describe(b):
    """(подпись, категория) — как в шпаргалке Super+Z; неподписанные — по действию."""
    try:
        import keybinds_sheet as ks
    except Exception:
        return (b["title"] or b["action"], "Прочее")
    if b["title"]:
        return (b["title"], ks.category(b["title"]))
    name, _, arg = b["action"].partition(" ")
    if name in ("focus-workspace", "move-column-to-workspace") and arg.isdigit():
        what = "Стол " if name == "focus-workspace" else "Колонку на стол "
        return (what + arg + (" (цифр. блок)" if "KP_" in b["key"] else ""), ks.WIN)
    u = ks.untitled(b["key"], b["action"])
    if u:
        return (u[0], u[1])
    act = b["action"]
    if act.startswith("spawn"):
        act = "запуск: " + " ".join(os.path.basename(w.strip('"'))
                                    for w in act.split()[1:3])
    return (act, "Прочее")


def conflict(binds, key, skip_line=None):
    """Бинд с тем же сочетанием (кроме строки skip_line) или None."""
    k = norm(key)
    return next((b for b in binds if norm(b["key"]) == k and b["line"] != skip_line), None)


def validate(text):
    """Проверить конфиг niri с этим binds.kdl на копии. → (ok, сообщение)."""
    niri = shutil.which("niri")
    if not niri:
        return True, ""                                  # проверить нечем — niri сам откажет
    with tempfile.TemporaryDirectory(prefix="binds-check-") as tmp:
        shutil.copy2(os.path.join(NIRI_DIR, "config.kdl"), tmp)
        shutil.copytree(os.path.join(NIRI_DIR, "cfg"), os.path.join(tmp, "cfg"))
        with open(os.path.join(tmp, "cfg", "binds.kdl"), "w", encoding="utf-8") as f:
            f.write(text)
        r = subprocess.run([niri, "validate", "-c", os.path.join(tmp, "config.kdl")],
                           capture_output=True, text=True, timeout=20)
    # из рамок miette — последняя причина «├─▶ …» / «╰─▶ …»: «invalid key: Blorp»
    why = re.findall(r"\u25b6\s*(.+)", r.stderr or r.stdout or "")
    msg = why[-1].strip() if why else "ошибка в конфиге"
    msg = re.sub(r"^invalid key: ", "нет такой клавиши: ", msg)
    return r.returncode == 0, msg


def write(changes):
    """changes: {номер строки: новая клавиша}. → (ok, сообщение). Пишет через
    временный файл и только после niri validate; прежний файл — рядом, binds.kdl.bak."""
    text = read(BINDS)
    lines = text.split("\n")
    for i, new in changes.items():
        m = RE_LINE.match(lines[i])
        if not m:
            return False, "строка %d не похожа на бинд" % (i + 1)
        lines[i] = m.group(1) + new + m.group(3)
    new_text = "\n".join(lines)
    if new_text == text:
        return True, ""
    ok, msg = validate(new_text)
    if not ok:
        return False, "niri не принял: " + msg
    shutil.copy2(BINDS, BINDS + ".bak")
    tmp = BINDS + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(new_text)
    os.replace(tmp, BINDS)
    return True, ""


def set_key(old, new):
    """Сменить сочетание бинда old на new. → (ok, сообщение)."""
    binds = load()
    new = tidy(new)
    if not new:
        return False, "не похоже на сочетание (пример: Mod+Shift+E)"
    b = next((b for b in binds if norm(b["key"]) == norm(old)), None)
    if b is None:
        return False, "нет бинда %s" % old
    other = conflict(binds, new, b["line"])
    if other:
        return False, "%s уже занято: %s" % (new, describe(other)[0])
    return write({b["line"]: new})


def reset(which="all"):
    """Вернуть умолчание: одному бинду (по его клавише) или всем. → (ok, сообщение, n)."""
    binds = load()
    pick = binds if which == "all" else [b for b in binds if norm(b["key"]) == norm(which)]
    changes = {b["line"]: b["default"] for b in pick
               if b["default"] and b["default"] != b["key"]}
    if not changes:
        return True, "", 0
    # после сброса сочетания не должны совпасть (своё сочетание могло занять чужое умолчание)
    after = {b["line"]: changes.get(b["line"], b["key"]) for b in binds}
    for line, key in changes.items():
        clash = next((l for l, k in after.items() if l != line and norm(k) == norm(key)), None)
        if clash is not None:
            other = next(b for b in binds if b["line"] == clash)
            return False, "%s сейчас занято: %s — смените его сначала" % (
                key, describe(other)[0]), 0
    ok, msg = write(changes)
    return ok, msg, (len(changes) if ok else 0)


def check():
    """Самопроверка: оба файла читаются, в binds.kdl нет повторов сочетаний."""
    rc = 0
    binds = parse(read(BINDS))
    if not binds:
        print("binds_edit: binds.kdl не прочитан или пуст")
        return 1
    seen = {}
    for b in binds:
        k = norm(b["key"])
        if k in seen:
            print("binds_edit: %s повторяется (строки %d и %d)" % (b["key"], seen[k] + 1, b["line"] + 1))
            rc = 1
        seen[k] = b["line"]
    if not os.path.exists(DEFAULT):
        print("binds_edit: нет %s — «по умолчанию» создастся при первом открытии" % DEFAULT)
    else:
        changed = sum(1 for b in load() if b["default"] and b["default"] != b["key"])
        print("binds_edit: %d биндов, своих сочетаний: %d" % (len(binds), changed))
    return rc


def main(argv):
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for b in load():
            print("%s\t%s\t%s" % (b["key"], b["default"] or "-", describe(b)[0]))
        return 0
    if cmd == "set" and len(argv) == 3:
        ok, msg = set_key(argv[1], argv[2])
        print(msg or "ok")
        return 0 if ok else 1
    if cmd == "reset":
        ok, msg, n = reset(argv[1] if len(argv) > 1 else "all")
        print(msg or "сброшено: %d" % n)
        return 0 if ok else 1
    if cmd == "check":
        return check()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
