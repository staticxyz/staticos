#!/usr/bin/env python3
"""Подкрасить VS Code палитрой обоев.

VS Code не умеет @import и не читает внешние файлы цветов: единственный вход —
ключ workbench.colorCustomizations в settings.json. Поэтому здесь не шаблон
matugen, а слияние: файл принадлежит пользователю, в нём лежат его собственные
настройки, и переписать его целиком нельзя.

Тема (workbench.colorTheme) НЕ трогается. colorCustomizations накладываются
поверх любой темы, так что выбранная тема остаётся, а поверхности берут цвет
обоев. VS Code перечитывает settings.json сам и применяет цвета без
перезапуска — окно перекрашивается на лету.

Цвета встроенного терминала берутся из colors-kitty.conf, чтобы терминал
внутри VS Code выглядел ровно так же, как отдельное окно kitty.
"""
import json
import os
import re
import sys
import tempfile

PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")
KITTY = os.path.expanduser("~/.cache/matugen/colors-kitty.conf")

# Code, Code - OSS и VSCodium держат настройки в разных каталогах; красим все,
# что есть, — какой из них установлен, скрипт знать не обязан.
SETTINGS = [
    "~/.config/Code/User/settings.json",
    "~/.config/Code - OSS/User/settings.json",
    "~/.config/VSCodium/User/settings.json",
]

# Ключ-маркер: по нему видно, что блок наш и его можно заменить целиком.
MARK = "_generated_by"
MARK_VALUE = "vscode_colors.py (matugen)"


def read_palette(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_kitty(path):
    """color0..15, foreground, background из конфига kitty."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) == 2 and parts[1].startswith("#"):
                out[parts[0]] = parts[1]
    return out


def strip_jsonc(text):
    """Убрать // и /* */ комментарии и висячие запятые, не трогая строки.

    settings.json — это JSONC: VS Code разрешает в нём комментарии, и обычный
    json.loads на таком файле падает. Разбор посимвольный, потому что // может
    оказаться внутри строкового значения (например, в пути или URL), и
    регулярка там ошибается.
    """
    out = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def build(p, k):
    """workbench.colorCustomizations из палитры."""
    a = p["primary"]                 # акцент
    on_a = p["on_primary"]
    surf = p["surface"]              # тот же фон, что у kitty
    low = p["surface_low"]
    cont = p["surface_container"]
    high = p["surface_high"]
    fg = p["on_surface"]
    dim = p["on_surface_variant"]
    line = p["outline"]
    edge = p["outline_variant"]
    sel = p["primary_container"]
    err = p["error"]

    c = {
        MARK: MARK_VALUE,

        # ── каркас окна ──
        "editor.background": surf,
        "editor.foreground": fg,
        "sideBar.background": low,
        "sideBar.foreground": dim,
        "sideBar.border": edge,
        "sideBarSectionHeader.background": cont,
        "sideBarSectionHeader.foreground": fg,
        "activityBar.background": low,
        "activityBar.foreground": a,
        "activityBar.inactiveForeground": line,
        "activityBar.border": edge,
        "activityBarBadge.background": a,
        "activityBarBadge.foreground": on_a,
        "statusBar.background": cont,
        "statusBar.foreground": dim,
        "statusBar.border": edge,
        "statusBar.noFolderBackground": cont,
        "statusBar.debuggingBackground": a,
        "statusBar.debuggingForeground": on_a,
        "titleBar.activeBackground": cont,
        "titleBar.activeForeground": fg,
        "titleBar.inactiveBackground": low,
        "titleBar.inactiveForeground": line,
        "titleBar.border": edge,
        "menu.background": cont,
        "menu.foreground": fg,
        "menu.selectionBackground": sel,

        # ── вкладки ──
        "editorGroupHeader.tabsBackground": low,
        "editorGroup.border": edge,
        "tab.activeBackground": surf,
        "tab.activeForeground": fg,
        "tab.inactiveBackground": low,
        "tab.inactiveForeground": line,
        "tab.border": edge,
        "tab.activeBorderTop": a,
        "tab.hoverBackground": high,

        # ── акценты ──
        "focusBorder": a,
        "editorCursor.foreground": a,
        "editorLineNumber.foreground": edge,
        "editorLineNumber.activeForeground": a,
        "editor.lineHighlightBackground": low,
        "editor.selectionBackground": sel + "66",
        "editor.selectionHighlightBackground": sel + "33",
        "editor.findMatchBackground": a + "55",
        "editor.findMatchHighlightBackground": a + "33",
        "editorIndentGuide.background1": edge,
        "editorIndentGuide.activeBackground1": line,
        "editorWidget.background": cont,
        "editorWidget.border": edge,
        "editorError.foreground": err,
        "button.background": a,
        "button.foreground": on_a,
        "button.hoverBackground": sel,
        "badge.background": a,
        "badge.foreground": on_a,
        "progressBar.background": a,
        "panelTitle.activeBorder": a,
        "textLink.foreground": a,

        # ── списки и поля ввода ──
        "list.activeSelectionBackground": sel,
        "list.activeSelectionForeground": p["on_primary_container"],
        "list.inactiveSelectionBackground": high,
        "list.hoverBackground": high,
        "list.highlightForeground": a,
        "input.background": cont,
        "input.foreground": fg,
        "input.border": edge,
        "inputOption.activeBorder": a,
        "dropdown.background": cont,
        "dropdown.border": edge,
        "quickInput.background": cont,
        "scrollbarSlider.background": line + "33",
        "scrollbarSlider.hoverBackground": line + "55",
        "scrollbarSlider.activeBackground": a + "66",

        # ── панель и встроенный терминал ──
        "panel.background": surf,
        "panel.border": edge,
        "terminal.background": surf,
        "terminal.foreground": k.get("foreground", fg),
        "terminalCursor.foreground": a,
    }

    # ANSI-слоты — те же, что у kitty, чтобы терминал внутри редактора и
    # отдельное окно терминала не расходились.
    ansi = ["Black", "Red", "Green", "Yellow", "Blue", "Magenta", "Cyan", "White"]
    for i, name in enumerate(ansi):
        if f"color{i}" in k:
            c[f"terminal.ansi{name}"] = k[f"color{i}"]
        if f"color{i + 8}" in k:
            c[f"terminal.ansiBright{name}"] = k[f"color{i + 8}"]
    return c


def patch(path, colors):
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    try:
        data = json.loads(strip_jsonc(raw) or "{}")
    except json.JSONDecodeError as e:
        print(f"vscode_colors: {path} не разбирается ({e}) — пропущен",
              file=sys.stderr)
        return False
    if not isinstance(data, dict):
        return False

    old = data.get("workbench.colorCustomizations")
    # Если блок не наш — пользователь настроил цвета сам, и затирать это нельзя.
    if isinstance(old, dict) and old and old.get(MARK) != MARK_VALUE:
        print(f"vscode_colors: в {path} свои colorCustomizations — не трогаю",
              file=sys.stderr)
        return False

    data["workbench.colorCustomizations"] = colors
    if data == json.loads(strip_jsonc(raw) or "{}"):
        return True                     # ничего не изменилось — не трогаем файл

    # Атомарно: VS Code следит за файлом и прочитает его в любой момент,
    # включая середину записи.
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".settings-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise
    return True


def main():
    try:
        p = read_palette(PALETTE)
        k = read_kitty(KITTY)
    except OSError as e:
        print(f"vscode_colors: нет палитры ({e})", file=sys.stderr)
        return 1
    colors = build(p, k)
    done = 0
    for s in SETTINGS:
        if patch(os.path.expanduser(s), colors):
            done += 1
    if done == 0:
        print("vscode_colors: не найдено ни одного settings.json", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
