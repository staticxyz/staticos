#!/usr/bin/env python3
"""Поиск «с защитой от дурака» для шпаргалки Super+Z и карты Super+Shift+Z. 13.10.2026.

Просьба: «ищет по точному совпадению… добавить поиск по похожим словам, по синонимам,
по разной раскладке, например я не смог найти скриншот, а она оказывается называется
снимок».

Каждое слово запроса должно найтись в строке одним из способов (по убыванию веса):
  100  как есть, кусок строки («сним» → «Снимок окна»);
   85  по основе слова без окончания («снимки», «громкости»);
   70  через синоним (SYNONYMS: «скриншот» → «снимок», «volume» → «громкость»);
   50  с опечаткой — одна буква на слово (две для слов от 7 букв): «громкочть»;
и всё это ещё раз в другой раскладке («cybvjr» → «снимок», «ыуеештпы» → «settings»),
с весом чуть ниже. Строки сортируются по сумме весов.

    smart_search.py ЗАПРОС СТРОКА…   проверить руками: вес каждой строки
"""
import functools
import re
import sys

EN = "qwertyuiop[]asdfghjkl;'zxcvbnm,.`" + 'QWERTYUIOP{}ASDFGHJKL:"ZXCVBNM<>~'
RU = "йцукенгшщзхъфывапролджэячсмитьбюё" + "ЙЦУКЕНГШЩЗХЪФЫВАПРОЛДЖЭЯЧСМИТЬБЮЁ"
TO_RU = str.maketrans(EN, RU)
TO_EN = str.maketrans(RU, EN)

# Группы синонимов: слово группы находит все остальные. Короткие основы — без окончаний
# («блокир» найдёт «блокировка», «блокировать»). Новые слова дописывать сюда.
SYNONYMS = [
    "снимок скриншот скрин screenshot shot принтскрин print grim фото",
    "запись записать record recorder видео video gif гиф стикер replay повтор",
    "громкость звук volume audio sound vol",
    "микрофон mic микро",
    "яркость brightness bright",
    "окно окна window win",
    "стол столы workspace ws рабочий",
    "закрыть close убить kill quit",
    "браузер browser zen helium librewolf firefox интернет сайт tor",
    "терминал terminal консоль kitty foot term shell",
    "буфер clipboard clip копировать скопировать вставить paste",
    "блокир блокировка lock замок",
    "обои wallpaper фон wall",
    "пароль пароли password keepass keepassxc",
    "калькулятор calc calculator посчитать",
    "переводчик перевод translate",
    "музыка music трек track песня плеер player играть play пауза pause",
    "файл файлы file files dolphin проводник папка folder",
    "настройки settings параметры опции",
    "конфиг config настройка",
    "меню menu лаунчер launcher программы приложения apps rofi",
    "питание power выключить shutdown перезагрузка reboot сон suspend",
    "уведомления notif notification notify",
    "эмодзи emoji смайл смайлик",
    "клавиши клавиша бинд бинды bind binds hotkey шпаргалка keys сочетание горячие",
    "помидор pomodoro pomo таймер timer",
    "будильник alarm подъем",
    "фокус focus discipline",
    "память memory ram озу",
    "подсветка keyboard razer kbd клавиатура",
    "плавающее float floating",
    "ширина width колонка column",
    "карта map",
    "текст text ocr распознать",
    "заметка заметки блокнот notepad mousepad note",
    "напоминание напоминания remind reminder hub",
    "словарь dict dictionary",
    "курсор cursor мышь mouse",
    "шрифт шрифты font fonts",
    "бар bar панель panel waybar",
    "док dock",
    "цвет цвета color colors тема theme стиль style",
    "лимит лимиты limit limits",
    "картинка pip",
    "полноэкранный fullscreen",
    "раскладка layout",
    "сеть network wifi вайфай lan",
    "bluetooth блютуз bt",
    "батарея battery заряд",
    # клавиши-модификаторы
    "super супер win вин mod мод",
    "ctrl ктрл контрол control",
    "shift шифт",
    "alt альт",
    "enter энтер return ввод",
    "space пробел",
    "tab таб",
]
_GROUPS = [g.split() for g in SYNONYMS]

_ENDINGS = sorted("""ами ями ого его ему ому ыми ими иях ах ях ой ей ий ый ая яя ое ее ые ие ую юю
    ов ев ом ем ам ям ать ять ить еть ки ка ку а я о е ы и у ю ь й ing ed es s""".split(),
                  key=len, reverse=True)
_WORD = re.compile(r"\w+")


def norm(s):
    return s.lower().replace("ё", "е")


@functools.lru_cache(maxsize=8192)
def stem(w):
    """Основа без окончания (грубо, зато без словарей): «снимки» → «сним»."""
    for e in _ENDINGS:
        if w.endswith(e) and len(w) - len(e) >= 3:
            return w[:-len(e)]
    return w


def _dist(a, b, limit):
    """Расстояние Левенштейна с перестановкой соседних; дальше limit — limit+1."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            if prev2 is not None and i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1]


def _in(term, hay, words):
    """term в строке: длинное (от 5 букв) — кусок строки; короткое — начало слова,
    чтобы «фон» не находил «микрофон», а «s» — всё подряд; одна буква — целое слово."""
    if len(term) == 1:
        return term in words
    if len(term) <= 4:
        return any(x.startswith(term) for x in words)
    return term in hay


@functools.lru_cache(maxsize=1024)
def _syn_terms(w, st):
    """Синонимы слова запроса. Зависят только от запроса — считаются один раз на
    слово, а не на каждую строку (13.10.2026: было ~180 мс на запрос в Super+X)."""
    out = []
    for g in _GROUPS:
        for t in g:
            if t == w or (len(st) >= 3 and t.startswith(st)) or (len(t) >= 4 and w.startswith(stem(t))):
                out += [x for x in g if x != t]
                break
    return tuple(out)


def word_score(w, hay, words):
    if _in(w, hay, words):
        return 100
    st = stem(w)
    if len(st) >= 3 and (st in hay or any(stem(x).startswith(st) for x in words)):
        return 85
    for t in _syn_terms(w, st):
        if _in(t, hay, words) or (len(t) >= 5 and _in(stem(t), hay, words)):
            return 70
    if len(w) >= 4:
        lim = 1 if len(w) < 9 else 2
        for x in words:
            if len(x) >= 4 and (_dist(w, x, lim) <= lim or
                                (len(x) > len(w) and _dist(w, x[:len(w)], lim) <= lim)):
                return 50
    return 0


def _score_one(q, hay, words):
    total = 0
    for w in _WORD.findall(q) or [q.strip()]:
        s = word_score(w, hay, words)
        if not s:
            return 0
        total += s
    return total


def variants(query):
    q = norm(query).strip()
    out = [(q, 0)]
    for v in (norm(query.translate(TO_RU)), norm(query.translate(TO_EN))):
        if v.strip() != q and v.strip() not in [x for x, _ in out]:
            out.append((v.strip(), 5))
    return out


def score(query, *texts):
    """Вес совпадения запроса со строками texts (0 — не подходит)."""
    hay = norm(" ".join(t for t in texts if t))
    words = set(_WORD.findall(hay))
    best = 0
    for q, minus in variants(query):
        if q:
            best = max(best, _score_one(q, hay, words) - minus)
    return max(best, 0)


def search(query, items, key, weak=None):
    """Отобрать и отсортировать items по запросу; key(item) -> список строк.
    weak(item) -> строки второго плана (категория, путь): совпадение там весит вдвое
    меньше и ставит строку ниже прямых совпадений."""
    if not query.strip():
        return list(items)

    def sc(it):
        s = score(query, *key(it))
        if not s and weak:
            s = score(query, *(list(key(it)) + list(weak(it)))) // 2
        return s
    scored = [(sc(it), i, it) for i, it in enumerate(items)]
    return [it for s, i, it in sorted((x for x in scored if x[0] > 0), key=lambda x: (-x[0], x[1]))]


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(2)
    for t in sys.argv[2:]:
        print(score(sys.argv[1], t), t)
