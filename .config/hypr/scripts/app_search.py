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
    # 29.10.2026, просьба: «почему better в пуске и в rofi не находятся? … с текстом вроде
    # "беттер"… это касается всех приложений»
    {"better", "беттер", "бетер", "лучше", "лучше вчера", "рост", "growth", "прогресс",
     "progress", "привычки", "habits"},
    {"напоминания", "напоминалка", "reminders", "reminder", "задачи", "tasks", "todo", "дела"},
    {"словарь", "dictionary", "слова", "words", "перевод слов"},
    {"помидор", "pomodoro", "pomo", "таймер", "timer", "секундомер", "stopwatch", "clocker", "фокус"},
    {"снимок", "скриншот", "скрин", "screenshot"},
    {"буфер", "clipboard", "копировать"},
    {"ватсап", "вотсап", "whatsapp", "wa"},
    {"чат", "чаты", "chat", "jchat", "мессенджер", "messenger"},
    {"приложения", "программы", "apps", "app list", "пакеты", "packages"},
    # 29.10.2026, просьба: «поиск по ключевым словам не работает полностью» — слов, которых
    # не было (обои, тема, сеть…), находились случайные программы по опечаткам и звучанию
    {"обои", "фон", "wallpaper", "waypaper"},
    {"тема", "оформление", "внешний вид", "appearance", "theme", "nwg-look", "qt5ct", "qt6ct"},
    {"сеть", "интернет", "вайфай", "wifi", "wi-fi", "network", "nm-connection-editor"},
    {"блютуз", "bluetooth", "blueman", "наушники"},
    {"звук", "громкость", "микшер", "volume", "pavucontrol", "pwvucontrol", "шум", "blanket"},
    {"мониторы", "экраны", "дисплеи", "displays", "wdisplays"},
    {"архив", "архивы", "zip", "rar", "archive", "ark", "file-roller"},
    {"pdf", "пдф", "читалка", "okular", "zathura", "evince", "draw", "librewolf", "zen"},
    {"рисовалка", "рисовать", "редактор картинок", "paint", "pinta", "gimp", "krita"},
    {"таблицы", "excel", "эксель", "calc"},
    {"текст", "ворд", "word", "writer", "документ"},
    {"презентация", "презентации", "powerpoint", "impress"},
    {"удалённый доступ", "удаленка", "remote", "anydesk", "teamviewer"},
    {"телефон", "phone", "kde connect", "kdeconnect", "localsend", "передать файлы"},
    {"флешка", "загрузочная", "ventoy", "usb"},
    {"база данных", "бд", "sql", "database", "dbeaver"},
    {"api", "postman", "запросы"},
    {"виртуалка", "виртуальная машина", "vm", "virtualbox"},
    {"печать", "набор", "тренажёр", "тренажер", "typing", "keypunch", "jtype"},
    {"тетрис", "tetris", "jtetris"},
    {"подсветка", "клавиатура", "razer", "polychromatic"},
    {"экранное время", "screen time", "screentime", "статистика"},
    {"звонки", "созвон", "zoom", "видеозвонок"},
    {"ночной свет", "gammastep", "night light"},
    {"пипетка", "цвет", "picker", "color picker"},
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
                    # слово группы целиком (набрано как есть) — вес как у набранного: «кс» —
                    # это Counter-Strike, а не ksnip по звучанию «кснип» (29.10.2026)
                    wt = 0 if f == w and f in group else 2
                    for m in group:
                        if forms.get(m, 9) > wt:
                            forms[m] = wt
        out.append(forms)
    return out


_WORDS = {}


def _starts(f, hay):
    """f — начало какого-нибудь слова hay. Синонимы и другая раскладка ищутся только так
    (29.10.2026): иначе «рост» находил «простой», а «тг» — «ьштгеу» (minute в раскладке)."""
    words = _WORDS.get(hay)
    if words is None:
        import re
        if len(_WORDS) > 4000:
            _WORDS.clear()
        words = _WORDS[hay] = re.findall(r"\w[\w+-]*", hay)
    if " " in f:
        return any(hay[i:].startswith(f) for i in range(len(hay)) if i == 0 or not hay[i - 1].isalnum())
    return any(w.startswith(f) for w in words)


def search_score(hay, forms):
    """None — не подходит; иначе худший вес среди слов запроса. Набранное как есть (от 4
    букв) ищется где угодно в строке, короче — и все остальные формы — с начала слова."""
    worst = 0
    for word in forms:
        best = min((wt for f, wt in word.items()
                    if (f in hay if wt == 0 and len(f) >= 4 else _starts(f, hay))), default=None)
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


# ── звучание (29.10.2026) ───────────────────────────────────────────────────
# Просьба: «вацап» не находил WhatsApp — «надо прям всё». Любое слово (кириллица или
# латиница) сводится к грубому «ключу звучания»: кириллица → латиница, wh/w → v, c → k/s,
# o → a (аканье), e → i, двойные буквы — одной. «вацап», «ватсап», «вотсап», «whatsapp»
# → vatsap; «ютуб» = «youtube», «стим» = «steam», «китти» = «kitty», «дискорд» = «discord».
_CYR = dict(zip("абвгдеёзийклмнопрстуфхыэ", "abvgdeeziiklmnoprstufhiie"))
_CYR.update({"ж": "zh", "ц": "ts", "ч": "ch", "ш": "sh", "щ": "sh", "ъ": "", "ь": "",
             "ю": "iu", "я": "ia"})
_SND = [("wh", "v"), ("ph", "f"), ("ck", "k"), ("qu", "kv"), ("th", "t"), ("tz", "ts"),
        ("ee", "i"), ("ea", "i"), ("oo", "u"), ("ou", "u"), ("ow", "au"), ("gh", "g"),
        ("ce", "se"), ("ci", "si"), ("cy", "si"), ("c", "k"), ("q", "k"), ("x", "ks"),
        ("w", "v"), ("j", "dzh"), ("y", "i"), ("o", "a"), ("e", "i"), ("z", "s")]


def sound_key(word):
    import re
    w = "".join(_CYR.get(ch, ch) for ch in word.lower())
    w = re.sub(r"[^a-z0-9]", "", w)
    if len(w) > 3 and w.endswith("e") and w[-2] not in "aeiouy":
        w = w[:-1]                                   # немая «e»: tube, cube
    for a, b in _SND:
        w = w.replace(a, b)
    return re.sub(r"(.)\1+", r"\1", w)


def _dist(a, b, cap):
    """Расстояние Левенштейна, не больше cap+1 (дальше не считаем)."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


_KEYS = {}


def sound_match(query, text):
    """0 — каждое слово запроса звучит как начало слова text; 1 — с одной-двумя
    ошибками; None — не похоже. text — имя, ключевые слова, программа (не описание:
    там слишком много слов для нечёткого сравнения)."""
    import re
    keys = _KEYS.get(text)
    if keys is None:
        if len(_KEYS) > 4000:
            _KEYS.clear()
        keys = _KEYS[text] = {k for k in map(sound_key, re.findall(r"\w+", text.lower())) if len(k) >= 2}
    worst = 0
    for qw in query.lower().split():
        q = sound_key(qw)
        if len(q) < 3:
            return None
        if any(k.startswith(q) for k in keys):
            continue
        cap = 1 if len(q) < 7 else 2
        if len(q) >= 4 and any(_dist(q, k, cap) <= cap or (len(k) > len(q) and _dist(q, k[:len(q)], 1) <= 1
                                                         and len(q) >= 5) for k in keys):
            worst = 1
            continue
        return None
    return worst


_CYR_BACK = [("dzh", "дж"), ("zh", "ж"), ("ch", "ч"), ("sh", "ш"), ("iu", "ю"), ("ia", "я"),
             ("ts", "ц")]
_LAT_RU = dict(zip("abvgdzijklmnoprstufh", "абвгдзийклмнопрстуфх"))


def sound_spellings(word):
    """Как латинское слово пишут по-русски на слух: «whatsapp» → «вацап», «ватсап»
    (для rofi: он сравнивает набранное только с готовыми словами)."""
    k = sound_key(word)
    out = set()
    for ts in ("ц", "тс"):
        w, r, i = k, [], 0
        while i < len(w):
            for a, b in _CYR_BACK:
                if w.startswith(a, i):
                    r.append(ts if a == "ts" else b)
                    i += len(a)
                    break
            else:
                r.append(_LAT_RU.get(w[i], w[i]))
                i += 1
        out.add("".join(r))
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
    import re
    for p in re.findall(r"[a-z]{3,}", (name or "").lower()):
        out |= sound_spellings(p)
    return " ".join(sorted(out - words))
