#!/usr/bin/env python3
"""Поиск программ: другая раскладка и синонимы — общий для «Пуска» (start_menu.py) и меню
программ rofi (launcher.py). Вынесено 05.10.2026 из start_menu.py, чтобы словарь был один.
Без GTK: модуль лёгкий, его грузит и лаунчер, которому важна скорость.
"""

# ── поиск: другая раскладка и синонимы (02.10.2026) ─────────────────────────
# Просьба: «пусть Пуск тоже понимает синонимы и другую раскладку в поиске приложений»
# (в Настройках это уже есть). «еудупкфь» → telegram, «лшеен» → kitty, «браузер» →
# Zen/LibreWolf, «тг» → Telegram.
_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю"
_LAYOUT = {**dict(zip(_EN, _RU)), **dict(zip(_RU, _EN))}
APP_SYNONYMS = [
    {"браузер", "browser", "интернет", "web", "zen", "librewolf", "firefox", "helium", "chromium"},
    {"терминал", "terminal", "консоль", "kitty", "foot"},
    {"файлы", "проводник", "папки", "file manager", "files", "dolphin", "nautilus", "yazi", "thunar"},
    {"музыка", "music", "плеер", "яндекс", "yandex", "spotify"},
    {"телеграм", "телега", "тг", "telegram"},
    {"заметки", "notes", "обсидиан", "obsidian"},
    {"настройки", "settings", "параметры"},
    {"редактор", "editor", "блокнот", "код", "code", "nvim", "vim", "micro", "mousepad"},
    {"игры", "games", "стим", "steam"},
    # 13.10.2026, просьба: «кс — counter strike»
    {"кс", "кс2", "cs", "cs2", "контра", "контр-страйк", "counter-strike", "counter strike"},
    {"видео", "video", "mpv", "vlc"},
    {"картинки", "фото", "images", "image viewer", "loupe", "gwenview"},
    {"калькулятор", "calculator", "calc"},
    {"диспетчер", "монитор", "процессы", "task manager", "system monitor", "btop", "htop"},
    {"дискорд", "discord"},
    {"почта", "mail", "thunderbird"},
    {"офис", "документы", "office", "libreoffice"},
    {"торрент", "torrent", "qbittorrent"},
    {"запись", "стрим", "obs", "recorder"},
    {"пароли", "ключи", "passwords", "seahorse", "keepass"},
    {"часы", "будильник", "clocks", "clock"},
    {"календарь", "calendar"},
]


def search_forms(query):
    """Для каждого слова запроса: [(форма, вес)] — как набрано (0), в другой
    раскладке (1), синонимы (2). Чем меньше вес, тем выше программа в списке."""
    out = []
    for w in query.split():
        forms = {w: 0}
        sw = "".join(_LAYOUT.get(ch, ch) for ch in w)
        if len(w) >= 3:                      # двухбуквенная «другая раскладка» — мусор («тг» → «nu»)
            forms.setdefault(sw, 1)
        for f in (w, sw):
            for group in APP_SYNONYMS:
                # короткое слово — только целиком («тг»), длинное — и по началу («брауз»)
                if f in group or (len(f) >= 3 and any(m.startswith(f) for m in group)):
                    for m in group:
                        forms.setdefault(m, 2)
        out.append(forms)
    return out


def search_score(hay, forms):
    """None — не подходит; иначе худший вес среди слов запроса."""
    worst = 0
    for word in forms:
        best = min((wt for f, wt in word.items() if f in hay), default=None)
        if best is None:
            return None
        worst = max(worst, best)
    return worst


def swap_layout(text):
    """Тот же текст, набранный в другой раскладке («telegram» ↔ «еудупкфь»)."""
    return "".join(_LAYOUT.get(ch, ch) for ch in text)


# Латиница → кириллица «как слышится» (13.10.2026): «discord» → «дискорд», «kitty» →
# «китти». Точности не нужно — это лишь лишние слова для поиска; для «стим», «кс» есть
# словарь выше. Сначала сочетания, потом буквы.
_PH2 = [("sh", "ш"), ("ch", "ч"), ("zh", "ж"), ("th", "т"), ("ph", "ф"), ("ck", "к"),
        ("ee", "и"), ("ea", "и"), ("oo", "у"), ("ou", "ау"), ("qu", "кв"), ("ce", "се"),
        ("ci", "си"), ("cy", "си"), ("ye", "е"), ("yo", "ё"), ("ya", "я"), ("yu", "ю")]
_PH1 = dict(zip("abcdefghijklmnopqrstuvwxyz",
                ["а", "б", "к", "д", "е", "ф", "г", "х", "и", "дж", "к", "л", "м", "н", "о", "п",
                 "к", "р", "с", "т", "у", "в", "в", "кс", "и", "з"]))


def phonetic(word):
    w, out, i = word.lower(), [], 0
    while i < len(w):
        for a, b in _PH2:
            if w.startswith(a, i):
                out.append(b)
                i += 2
                break
        else:
            out.append(_PH1.get(w[i], w[i]))
            i += 1
    return "".join(out)


def name_words(name):
    """Кириллические «звучания» слов имени и сокращение по первым буквам
    («Counter-Strike 2» → cs, кс, cs2, кс2)."""
    import re
    parts = re.findall(r"[a-z]+|\d+", (name or "").lower())
    out = set()
    for p in parts:
        if p.isalpha() and len(p) >= 3:
            out.add(phonetic(p))
    alpha = [p for p in parts if p.isalpha()]
    if len(alpha) >= 2:
        ini = "".join(p[0] for p in alpha)
        num = "".join(p for p in parts if p.isdigit())
        for v in (ini, ini + num):
            out.update((v, phonetic(v) if len(v) > 1 else v))
        out.add("".join(_PH1.get(c, c)[0] for c in ini))        # «cs» → «кс»
        out.add("".join(_PH1.get(c, c)[0] for c in ini) + num)
    return out


def search_meta(hay, name=None):
    """Невидимые слова для поиска в rofi (row option meta): слова программы в другой
    раскладке, синонимы её групп и они же в другой раскладке. rofi сравнивает набранное с
    именем и с этими словами — так «еудупкфь», «браузер», «тг» находят своё."""
    # пути (/usr/bin/…) не слова: в другой раскладке из них выходит мусор вроде «/гык»
    words = {w for w in hay.lower().replace(";", " ").split() if len(w) >= 2 and "/" not in w}
    out = set()
    for w in words:
        if len(w) >= 3:
            out.add(swap_layout(w))
    for group in APP_SYNONYMS:
        if any(m in words or (" " in m and m in hay.lower()) for m in group):
            for m in group:
                out.add(m)
                if len(m) >= 3:
                    out.add(swap_layout(m))
    out |= name_words(name)
    return " ".join(sorted(out - words))
