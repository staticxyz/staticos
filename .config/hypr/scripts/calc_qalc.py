#!/usr/bin/env python3
"""qalc для калькулятора rofi (calc_menu.sh, -qalc-binary).

1. Курсы. rofi-calc при каждом вызове просит qalc «update_exchange_rates 1days»,
   и раз в сутки тот лезет за курсами прямо во время набора. ЕЦБ отдаёт их за
   доли секунды, а coinbase.com (курс биткоина) отсюда не отвечает вовсе: qalc
   ждёт 15 секунд и печатает «Failed to download exchange rates (Bitcoins)», а
   rofi показывает это вместо ответа. Поэтому просьбу заменяем на «не
   обновляй», а курсы освежаем сами — в фоне, не чаще раза в сутки.

2. Русский ввод. qalc не знает «вон» и «тенге», а «in» читает как дюймы.
   Здесь «500 вон в тенге» становится «500 KRW to KZT», «8 usd in kzt» —
   «8 USD to KZT», «20$» — «20 USD».

3. Сразу в тенге. Если написаны только сумма и валюта («20 usd», «20$»,
   «300 юань»), перевод в тенге дописывается сам. Дописали «to rub» или
   «в рублях» — переводится туда.

5. Переводчик (17.09.2026, NLLB и новые языки — 23.09.2026). Если строка — не
   выражение, а текст, вместо ответа qalc показывается перевод. Язык источника
   — по письменности: кириллица → русский, кана/иероглифы → японский, хангыль
   → корейский, латиница → английский, а немецкий узнаётся по умлаутам и
   служебным словам (der, und, nicht…). Куда: русский → английский, остальное
   → русский. Хвост «> de» / «> ja» / «> ko» / «> en» или «на немецкий» —
   принудительно. Офлайн, модель держит translate_server.py (см. его шапку).
   Как отличаем текст — looks_like_text(); числа, валюты и коды идут в qalc.
   Латиница из одной-двух букв тоже текст: пока печатали «hello», qalc
   показывал «h = hour», «ho = hectobyte» (журнал 23.09.2026); исключение —
   константы pi и e.

4. Деньги округляются: «2 277.95 KZT». Enter копирует чистое число
   («2277.95») — его обёртка кладёт в ANSWER, а calc_copy.sh берёт оттуда.
   Через {result} rofi-calc передаёт ответ оболочке, и узкие пробелы разбивки
   по тысячам доезжали битыми байтами: «9�200257111.78».
"""
import json
import os
import re
import subprocess
import sys
import time

RATES_JSON = os.path.expanduser("~/.local/share/qalculate/rates.json")
# Те же источники, что зашиты в libqalculate; оба отвечают отсюда (11.09).
RATES_URLS = ["https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/eur.json",
              "https://latest.currency-api.pages.dev/v1/currencies/eur.json"]
LAST = os.path.expanduser("~/.cache/calc_qalc.last")       # журнал вызовов — для проверки
ANSWER = os.path.expanduser("~/.cache/calc_qalc.answer")   # что скопирует Enter
TRANSLATE_REQ = os.path.expanduser("~/.cache/calc_qalc.translate")  # если это был перевод
NOISE = ("error:", "warning:", "It has been", "Do you wish")
ASK = "Do you wish to update the exchange rates now?"
HOME = "KZT"                                               # валюта «по умолчанию»

# Основа слова -> код. Окончания («рублей», «долларов», «вона») ловит \w*.
RU = [
    (r"тенге|тг|₸", "KZT"),
    (r"вон\w*", "KRW"),
    (r"доллар\w*|бакс\w*", "USD"),
    (r"евро", "EUR"),
    (r"рубл\w*|руб", "RUB"),
    (r"юан\w*", "CNY"),
    (r"[ий]ен\w*", "JPY"),
    (r"фунт\w*", "GBP"),
    (r"лир\w*", "TRY"),
    (r"гривн\w*", "UAH"),
    (r"франк\w*", "CHF"),
    (r"сом\w*", "KGS"),
    (r"сум\w*", "UZS"),
    (r"дирхам\w*", "AED"),
    (r"злот\w*", "PLN"),
]
# Иероглифы и хангыль пишутся вплотную к числу («500円»), границы слова тут нет.
CJK_MONEY = (("円", "JPY"), ("엔", "JPY"), ("원", "KRW"), ("元", "CNY"))
SYMBOL = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "₽": "RUB", "₸": "KZT", "₩": "KRW"}
# Коды, которые узнаём и строчными («usd», «rub»). Список ручной: слепо
# поднимать любые три буквы нельзя — «min», «day» тоже три буквы.
CODES = {"USD", "EUR", "KZT", "RUB", "KRW", "CNY", "JPY", "GBP", "TRY", "UAH", "CHF",
         "KGS", "UZS", "AED", "PLN", "CAD", "AUD", "NZD", "INR", "THB", "GEL", "AMD",
         "AZN", "BYN", "CZK", "SEK", "NOK", "DKK", "HKD", "SGD", "TJS", "MNT", "VND",
         "IDR", "ILS", "SAR", "QAR", "EGP", "BRL", "MXN", "MYR", "PHP", "HUF", "RON"}
SYM = re.escape("".join(SYMBOL))
NUM = r"-?\d[\d ]*(?:[.,]\d+)?"


def translate(expr):
    # «5k», «5к», «1.5k» — тысячи, «2кк»/«2kk» — миллионы (30.09.2026, просьба: # «5k rub» считалось как «кило» и уходило в доллары мимо перевода в тенге).
    # Только сразу после числа и перед не-буквой: «5 km», «5kg» не задеваются.
    def _thousands(m):
        n = float(m.group(1).replace(",", "."))
        n *= 1_000_000 if len(m.group(2)) == 2 else 1000
        return ("%d" % n) if n == int(n) else ("%g" % n)
    expr = re.sub(r"(\d+(?:[.,]\d+)?)\s?([kк]{1,2})(?![A-Za-zА-Яа-я])", _thousands, expr, flags=re.I)
    for stem, code in RU:
        expr = re.sub(r"(?<!\w)(?:%s)(?!\w)" % stem, code, expr, flags=re.I)
    for sym, code in CJK_MONEY:
        expr = expr.replace(sym, " " + code)
    # «$20» и «20$» -> «20 USD».
    expr = re.sub(r"([%s])\s*(%s)" % (SYM, NUM), lambda m: "%s %s" % (m.group(2), SYMBOL[m.group(1)]), expr)
    expr = re.sub(r"(\d)\s*([%s])" % SYM, lambda m: "%s %s" % (m.group(1), SYMBOL[m.group(2)]), expr)
    expr = re.sub(r"(?<![\w])([A-Za-z]{3})(?![\w])",
                  lambda m: m.group(1).upper() if m.group(1).upper() in CODES else m.group(1), expr)
    # «в»/«во»/«на»/«in» перед единицей или кодом — это перевод, то есть «to».
    # «12 in to cm» не трогаем: после «in» стоит «to», и это дюймы.
    expr = re.sub(r"\s+(?:в|во|на|in)\s+(?!to\b)(?=[A-Za-z])", " to ", expr, flags=re.I)
    # Только сумма и валюта — переводим в тенге. Недописанный хвост перевода
    # («t», «to», «to r», «в», «в р») считаем за пустой: иначе, пока пишешь
    # «to rub», мелькал мусор вроде «20 t*$» и «r$2E28», и Enter копировал бы
    # его. Как только после «to» стоит известный код, считается туда.
    m = re.fullmatch(r"\s*(%s)\s*([A-Z]{3})(?:\s+(?:t|to|i|in|в|во|на)(?:\s+(\w{0,3}))?)?\s*" % NUM,
                     expr, flags=re.I)
    if m and m.group(3) and m.group(3).upper() in CODES:
        m = None
    if m and m.group(2) in CODES and m.group(2) != HOME:
        num = m.group(1).replace(" ", "").replace(",", ".")
        expr = "%s %s to %s" % (num, m.group(2), HOME)
    return expr


def money(line):
    """(что показать, что скопировать).

    «KZT 2277.946152» -> («2 277.95 KZT», «2277.95»). Два знака после запятой
    и тысячи через узкий пробел; меньше единицы — четыре значащие цифры, иначе
    копейки превратились бы в 0.00. Прочие ответы — как есть.
    """
    m = re.fullmatch(r"(?:([A-Z]{3}) ?|([%s]))(-?\d+(?:\.\d+)?)" % SYM, line)
    if m:
        code, value = m.group(1) or SYMBOL[m.group(2)], float(m.group(3))
    else:
        m = re.fullmatch(r"(-?\d+(?:\.\d+)?) ?([A-Z]{3})", line)
        if not m or m.group(2) not in CODES:
            return line, line
        value, code = float(m.group(1)), m.group(2)
    if abs(value) >= 1 or value == 0:
        plain = "%.2f" % value
        shown = "{:,.2f}".format(value).replace(",", " ")
    else:
        plain = shown = "{:.4g}".format(value)
    return "%s %s" % (shown, code), plain


TRANSLATE_SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-translate.sock")
TRANSLATE_SERVER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translate_server.py")
TRANSLATE_PY = os.environ.get("TRANSLATE_PYTHON") or os.path.expanduser("~/.local/share/jarvis-translate/venv/bin/python")
ICON_TRANSLATE = "\U000f05ca"
WRAP_AT = 38                                   # знаков в строке (панель 520 px, клетка 12 px)
ENTRY_FITS = 42                                # столько строка ввода ещё показывает целиком
ICON_INPUT = "\U000f0417"                      # nf-md-text — строка «что переводим»
CYR = re.compile(r"[а-яё]", re.I)
JPN = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]")
KOR = re.compile(r"[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]")
# Всё, что делает строку выражением: цифры, знаки, символы валют.
MATHY = re.compile(r"[0-9+\-*/^%%=()<>!&|√×÷%s]" % SYM)
# Немецкий от английского — по умлаутам и словам, которых в английском нет
# (нарочно без die/hat/gut/was/bin: это и английские слова).
GERMAN = re.compile(r"[äöüß]|(?<![A-Za-z])(?:der|das|und|ist|nicht|ich|wir|sie|ein|eine|mit|für"
                    r"|auf|von|zu|den|dem|des|im|habe|sind|auch|nach|wie|heute|morgen|danke|bitte"
                    r"|guten|hallo|nein|kein|keine|mein|dein|sehr|schon|noch|aber|oder|wenn|dann"
                    r"|jetzt|hier|dort|über|unter|vor|bei|aus|seit|ohne|gegen|durch)(?![A-Za-z])",
                    re.I)
# Куда переводить: «> de», «-> ja», «на немецкий», «по-японски».
LANG_CODES = {"ru": "rus_Cyrl", "en": "eng_Latn", "de": "deu_Latn", "ja": "jpn_Jpan",
              "jp": "jpn_Jpan", "ko": "kor_Hang", "kr": "kor_Hang", "kz": "kaz_Cyrl",
              "kk": "kaz_Cyrl", "fr": "fra_Latn", "es": "spa_Latn", "it": "ita_Latn",
              "zh": "zho_Hans", "cn": "zho_Hans", "tr": "tur_Latn", "uk": "ukr_Cyrl"}
LANG_WORDS = [("русск", "rus_Cyrl"), ("англ", "eng_Latn"), ("немец", "deu_Latn"),
              ("япон", "jpn_Jpan"), ("корей", "kor_Hang"), ("казах", "kaz_Cyrl"),
              ("франц", "fra_Latn"), ("испан", "spa_Latn"), ("итал", "ita_Latn"),
              ("китай", "zho_Hans"), ("турец", "tur_Latn"), ("украин", "ukr_Cyrl")]
TARGET_TAIL = re.compile(r"^(.*?)\s*(?:>|->|→)\s*([A-Za-z]{0,3})$")
TARGET_WORD = re.compile(r"^(.*\S)\s+(?:на|по)[- ]?([а-яё]+)$", re.I)


def split_target(raw):
    """(текст без хвоста, код языка или None, хвост недописан?)."""
    s = raw.strip()
    m = TARGET_TAIL.match(s)
    if m:
        code = m.group(2).lower()
        if code in LANG_CODES:
            return m.group(1).strip(), LANG_CODES[code], False
        if len(code) <= 2:                       # «> d» — ещё печатают
            return m.group(1).strip(), None, True
        return s, None, False
    m = TARGET_WORD.match(s)
    if m:
        for stem, code in LANG_WORDS:
            if m.group(2).lower().startswith(stem):
                return m.group(1).strip(), code, False
    return s, None, False


def looks_like_text(body, expr, tgt=None):
    """Перевод или калькулятор → (src, tgt) либо None.

    body — ввод без хвоста «> de», expr — он же после translate().
    Калькулятор, если:
      * в строке есть цифры, знаки или символы валют («2*17%», «20$», «5 km to miles»);
      * после разбора валют не осталось букв чужой письменности («тенге в рублях», «500円»);
      * латиница, но в ней код валюты («usd to kzt») или это константа qalc («pi», «e»).
    Иначе — текст; язык источника по письменности, немецкий — по GERMAN.
    """
    s = body.strip()
    if not s:
        return None
    if JPN.search(s):
        src, left = "jpn_Jpan", JPN.search(expr)
    elif KOR.search(s):
        src, left = "kor_Hang", KOR.search(expr)
    elif CYR.search(s):
        src, left = "rus_Cyrl", CYR.search(expr)
    else:
        src, left = None, None
    if src:
        if not left:
            return None
        if src == "rus_Cyrl" and MATHY.search(s):
            return None
        return src, (tgt or ("eng_Latn" if src == "rus_Cyrl" else "rus_Cyrl"))
    if MATHY.search(s):
        return None
    words = re.findall(r"[A-Za-z]+", s)
    if not words:
        return None
    if any(w.upper() in CODES for w in re.findall(r"[A-Za-z]{3}", expr)):
        return None
    if len(words) == 1 and words[0].lower() in ("pi", "e"):
        return None
    src = "deu_Latn" if GERMAN.search(s) else "eng_Latn"
    if tgt == src:
        tgt = "rus_Cyrl" if src != "rus_Cyrl" else "eng_Latn"
    return src, (tgt or "rus_Cyrl")


def translate_text(text, src, tgt):
    """Перевод через translate_server.py; нет службы — запустить и подождать."""
    import socket

    def ask():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(5)
            c.connect(TRANSLATE_SOCK)
            c.sendall((json.dumps({"text": text, "src": src, "tgt": tgt},
                                  ensure_ascii=False) + "\n").encode())
            data = b""
            while not data.endswith(b"\n"):
                chunk = c.recv(65536)
                if not chunk:
                    break
                data += chunk
        return json.loads(data.decode()).get("out")

    try:
        return ask()
    except (OSError, ValueError):
        pass
    try:
        subprocess.Popen([TRANSLATE_PY, TRANSLATE_SERVER], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    except OSError:                          # нет службы или venv — не ронять rofi-calc
        return None
    deadline = time.time() + 4
    while time.time() < deadline:            # первый запуск: модели грузятся ~1 с
        time.sleep(0.1)
        try:
            return ask()
        except (OSError, ValueError):
            continue
    return None


def refresh_rates_in_background():
    try:
        fresh = time.time() - os.path.getmtime(RATES_JSON) < 86400
    except OSError:
        fresh = False
    if not fresh:
        subprocess.Popen([sys.executable, os.path.abspath(__file__), "--refresh"],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def refresh():
    """Скачать свежие курсы. Запускается в фоне, ответа никто не ждёт.

    Тенге, вона, рубль и прочие не из списка ЕЦБ qalc берёт из rates.json. Сам
    он этот файл не обновляет (проверено 11.09: лежала системная копия от
    06.07, и qalc честно писал «It has been 67 days…»), хотя источник доступен.
    Кладём копию в каталог пользователя — qalc читает её вместо системной.
    """
    import urllib.request
    for url in RATES_URLS:
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                data = r.read()
            d = json.loads(data)
            if "kzt" in d.get("eur", {}):
                tmp = RATES_JSON + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, RATES_JSON)
                break
        except Exception:
            continue
    # Курсы ЕЦБ. Попытка coinbase при этом повиснет на 15 с — но уже в фоне.
    subprocess.run(["qalc", "-e", "1"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=60)


def log(line):
    try:
        if os.path.getsize(LAST) > 200_000:        # журнал не растёт бесконечно
            os.replace(LAST, LAST + ".old")
    except OSError:
        pass
    with open(LAST, "a") as f:
        f.write(line)


def main():
    if sys.argv[1:] == ["--refresh"]:
        return refresh()
    refresh_rates_in_background()
    args, rest = [], sys.argv[1:]
    while rest:
        a = rest.pop(0)
        if a in ("-s", "-set") and rest and rest[0].startswith("update_exchange_rates"):
            # Не просто выкинуть, а сказать «сам не обновляй» (0). Без явного
            # значения qalc брал его из qalc.cfg, а там -1 = «спрашивать»: в rofi
            # он писал «Do you wish to update the exchange rates now?» и
            # приклеивал ответ к вопросу.
            rest.pop(0)
            args += ["-s", "update_exchange_rates 0"]
            continue
        args.append(a)
    if args and not args[-1].startswith(("-", "+")):
        raw = args[-1]
        body, tgt, _pending = split_target(raw)
        pair = looks_like_text(body, translate(body), tgt)
        args[-1] = translate(raw)          # выражение rofi-calc передаёт последним
        if pair:
            src, tgt = pair
            out = translate_text(body, src, tgt)
            with open(ANSWER, "w") as f:
                f.write(out or "")
            # Для Enter: calc_copy.sh увидит, что это перевод, и (если есть
            # translate_refine.sh) попросит уточнённый, а черновик NLLB —
            # запасной. Файл живёт ровно до следующего ввода.
            with open(TRANSLATE_REQ, "w") as f:
                json.dump({"text": body, "src": src, "tgt": tgt}, f, ensure_ascii=False)
            log("%s %r -> перевод %s→%s %r\n" % (time.strftime("%T"), [raw], src[:3], tgt[:3], out))
            # Пустой вывод роняет rofi-calc (см. ниже), поэтому хотя бы пробел.
            # Длинный перевод — в несколько строк: сам rofi строку message не
            # переносит, и хвост обрезался (23.09.2026).
            if out and os.environ.get("CALC_RAW"):
                # Своё окно (translate_popup.py) переносит строки само: ему —
                # значок и перевод одной строкой, без эха ввода.
                print("%s  %s" % (ICON_TRANSLATE, out))
                return
            if out:
                import textwrap
                block = []
                # Сама фраза, если строка ввода её уже не вмещает: rofi сжимает
                # длинный ввод многоточием посередине, а растянуть вниз его
                # нельзя — поэтому она печатается строками над переводом.
                if len(body) > ENTRY_FITS:
                    src_lines = textwrap.wrap(body, WRAP_AT)
                    block += [ICON_INPUT + "  " + src_lines[0]] + [" " * 4 + l for l in src_lines[1:]]
                shown_lines = textwrap.wrap(out, WRAP_AT) or [out]
                block += [ICON_TRANSLATE + "  " + shown_lines[0]] + [" " * 4 + l for l in shown_lines[1:]]
                print("\n".join(block))
            else:
                print("Переводчик не ответил")
            return
    # Показываем только ответ. Предупреждения и ошибки («Misplaced operator»,
    # «is not a valid unit», «It has been 67 days since the exchange rates…»)
    # сыпались красным на каждом недописанном символе — их нет.
    r = subprocess.run(["qalc"] + args, stdin=subprocess.DEVNULL, capture_output=True, text=True)
    lines = [l.strip() for l in r.stdout.splitlines() if l.strip()]
    # Если вопрос всё же прозвучал, ответ стоит в конце той же строки. И вообще
    # у приближённых ответов («5 USD = approx. KZT 2277.9») оставляем только
    # сам ответ.
    clean = []
    for l in lines:
        if ASK in l:
            l = l.split(ASK, 1)[1].strip()
        if " approx. " in l or " ≈ " in l:
            l = re.split(r"\s(?:=|≈)\s(?:approx\.\s)?", l)[-1]
        clean.append(l)
    answers = [money(l) for l in clean if l and not l.startswith(NOISE)]
    shown, plain = answers[-1] if answers else (" ", "")
    with open(ANSWER, "w") as f:
        f.write(plain)
    try:
        os.unlink(TRANSLATE_REQ)               # это калькулятор, не перевод
    except OSError:
        pass
    log("%s %r -> %r\n" % (time.strftime("%T"), args[-1:], lines))
    # Молчать НЕЛЬЗЯ: на пустом выводе rofi-calc разыменовывает пустой указатель
    # и падает целиком (SIGSEGV в libcalc.so, 11.09) — окно «само закрывалось».
    # Пробел не виден, а пустой ANSWER calc_copy.sh в буфер не кладёт.
    print(shown)


if __name__ == "__main__":
    main()
