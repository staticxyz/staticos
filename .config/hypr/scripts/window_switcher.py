#!/usr/bin/env python3
"""Переключатель окон (SUPER+Tab), в два шага.

1. Приложения: по строке на приложение — значок, название полужирным и число
   окон, если их больше одного. Порядок — по последнему использованию: первым
   стоит и уже выделено приложение, где было ПРЕДЫДУЩЕЕ окно. Поиск ищет и по
   заголовкам окон: «btop» найдёт Kitty.
2. Окна выбранного приложения: заголовок и номер стола. Если окно у
   приложения одно, второго шага нет — сразу переход.

Tab/стрелки листают, Enter или щелчок — выбор, Escape или щелчок мимо панели —
закрыть. Текущее окно в списки не входит. Вид — тот же, что у лаунчера
(config.rasi): стекло, та же панель.

Почему так, а не иначе:
  * rofi -show window перечисляет окна в порядке создания, а не использования;
  * hyprswitch шлёт Hyprland команды старого синтаксиса, Lua-конфиг их не
    принимает;
  * «держи SUPER — отпусти — выбор» rofi на Wayland не ловит (проверено);
  * bash не хранит нулевой байт, а на нём держится пометка значка в rofi
    (\\0icon\\x1f) — поэтому Python, и строки уходят в rofi байтами.
Название и значок берутся из ярлыка приложения (.desktop), а не из
технического имени окна: «Telegram», а не «org.telegram.desktop».
"""
import configparser
import glob
import json
import os
import subprocess
from html import escape

PROMPT = "\U000f0570"   # md view-grid — «приложения», ровный, как лупа и калькулятор
DIRS = [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications",
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications")]
LOG = os.path.expanduser("~/.cache/window_switcher.log")
# Каждый блок темы — с НОВОЙ СТРОКИ: в пределах одной строки rofi хватает
# строку в кавычках жадно, от первой кавычки до последней, и всё, что между
# ними, молча становится значением placeholder.
THEME = 'entry { placeholder: ""; }\nelement-icon { size: 28px; }'


def hypr(*args):
    return json.loads(subprocess.run(["hyprctl", *args, "-j"], capture_output=True, text=True).stdout)


def desktop_index():
    """{ключ: (название, значок)} по имени файла ярлыка и StartupWMClass."""
    idx = {}
    for d in DIRS:
        for f in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("NoDisplay", "").lower() == "true" and not e.get("StartupWMClass"):
                continue
            # Основное имя, а не Name[ru]: русское у браузеров — описание
            # («Веб-браузер LibreWolf»), а нужно короткое «LibreWolf».
            name = e.get("Name") or e.get("Name[ru]") or ""
            if name[:1].islower():
                name = name[:1].upper() + name[1:]        # kitty -> Kitty
            entry = (name, e.get("Icon", ""))
            keys = {os.path.basename(f)[:-8].lower()}
            if e.get("StartupWMClass"):
                keys.add(e["StartupWMClass"].lower())
            for k in keys:
                idx.setdefault(k, entry)
    return idx


def app_of(cls, idx):
    c = (cls or "").lower()
    for key in (c, c.rsplit(".", 1)[-1]):
        if key in idx and idx[key][0]:
            return idx[key][0], idx[key][1] or c
    short = (cls or "?").rsplit(".", 1)[-1]
    return short[:1].upper() + short[1:], c


def title_of(c):
    return " ".join((c.get("title") or "").split())


def row(text, icon, meta=""):
    r = text.encode() + b"\0icon\x1f" + icon.encode()
    if meta:
        r += b"\x1fmeta\x1f" + meta.replace("\n", " ").encode()
    return r


# Щелчок мимо панели. В лаунчере он равен Escape (kb-cancel, см. config.rasi),
# но на втором шаге Escape значит «назад к приложениям», а щелчок мимо должен
# закрывать совсем. Поэтому там полям вокруг панели дано своё действие:
# rofi выходит с кодом 10 + (19 - 1) = 28.
OUTSIDE = ('\nbutton-gap-top, button-gap-bottom, button-gap-left, button-gap-right'
           ' { action: "kb-custom-19"; }')
CLOSE = 28


def pick(rows, prompt, extra_theme="", selected=0):
    """Показать список в rofi; вернуть (код выхода, номер строки или None)."""
    r = subprocess.run(
        ["rofi", "-dmenu", "-i", "-markup-rows", "-show-icons", "-format", "i",
         "-p", prompt, "-selected-row", str(selected),
         "-kb-row-down", "Tab,Down", "-kb-row-up", "ISO_Left_Tab,Up",
         "-kb-element-next", "", "-kb-element-prev", "",
         "-theme-str", THEME + extra_theme],
        input=b"\n".join(rows) + b"\n", capture_output=True)
    choice = r.stdout.decode().strip()
    with open(LOG, "a") as f:
        f.write("rofi «%s»: строк %d, код %d, выбор %r\n" % (prompt, len(rows), r.returncode, choice))
    if r.returncode != 0 or not choice.isdigit():
        return r.returncode, None
    return 0, int(choice)


def focus(addr):
    out = subprocess.run(["hyprctl", "dispatch", 'hl.dsp.focus({ window = "address:%s" })' % addr],
                         capture_output=True, text=True).stdout.strip()
    with open(LOG, "a") as f:
        f.write("переход на %s: %s\n" % (addr, out))


def main():
    open(LOG, "w").close()
    active = hypr("activewindow").get("address")
    wins = [c for c in hypr("clients")
            if c.get("mapped") and c["workspace"]["id"] > 0 and c["address"] != active]
    if not wins:
        return 0
    wins.sort(key=lambda c: c["focusHistoryID"])
    idx = desktop_index()

    # Приложения в порядке их самого свежего окна: wins уже отсортирован,
    # поэтому первое появление приложения и есть его место в списке.
    apps = {}
    for c in wins:
        apps.setdefault(app_of(c["class"], idx), []).append(c)
    groups = list(apps.items())

    app_rows = []
    for (name, icon), cs in groups:
        text = "<b>%s</b>" % escape(name)
        if len(cs) > 1:
            text += "   <span alpha='45%%'>%d</span>" % len(cs)
        app_rows.append(row(text, icon, " ".join(title_of(c) for c in cs)))

    # Escape на втором шаге возвращает сюда, на то же приложение; Escape здесь
    # закрывает переключатель.
    selected = 0
    while True:
        _, i = pick(app_rows, PROMPT, selected=selected)
        if i is None:
            return 0
        (name, icon), cs = groups[i]
        if len(cs) == 1:
            focus(cs[0]["address"])
            return 0

        rows = []
        for c in cs:
            title = title_of(c) or name
            text = "%s   <span alpha='38%%'>%d</span>" % (escape(title[:80]), c["workspace"]["id"])
            rows.append(row(text, icon))
        code, j = pick(rows, name, OUTSIDE)
        if j is not None:
            focus(cs[j]["address"])
            return 0
        if code == CLOSE:
            return 0
        selected = i


if __name__ == "__main__":
    raise SystemExit(main())
