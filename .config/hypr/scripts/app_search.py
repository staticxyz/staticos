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


def search_meta(hay):
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
    return " ".join(sorted(out - words))
