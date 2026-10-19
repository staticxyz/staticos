#!/usr/bin/env python3
"""Перевод через Google для калькулятора SUPER+C (17.10.2026).

    translate_google.py "текст" rus_Cyrl eng_Latn     -> перевод в stdout, код 1 — нет ответа

Просьба: «переводит посредственно, не так хорошо как google translator». NLLB-600M
(translate_server.py) офлайн и путает смысл. Теперь основной — Google, NLLB — запасной без сети.

Адреса — те же, что у веб-страницы Google Translate и словаря Chrome; ключ
вшит в саму страницу translate.google.com, он не личный (в репозиторий не кладётся, см. PA_KEY). Старый
translate.googleapis.com (client=gtx) отсюда отдаёт «Sorry… automated
queries» (замер 17.10.2026), поэтому он не используется. Ответ ~0,3 с.

Текст уходит в Google — это внешний сервис.
"""
import json
import os
import sys
import urllib.parse
import urllib.request

# Коды NLLB (так их передаёт calc_qalc.py) → коды Google.
CODES = {"rus_Cyrl": "ru", "eng_Latn": "en", "deu_Latn": "de", "jpn_Jpan": "ja",
         "kor_Hang": "ko", "kaz_Cyrl": "kk", "fra_Latn": "fr", "spa_Latn": "es",
         "ita_Latn": "it", "zho_Hans": "zh-CN", "tur_Latn": "tr", "ukr_Cyrl": "uk"}
# Латиницу calc_qalc.py угадывает грубо (английский/немецкий) — пусть Google
# узнаёт язык сам: тогда и французский, и испанский переводятся верно.
AUTO = {"eng_Latn", "deu_Latn"}
PA_URL = "https://translate-pa.googleapis.com/v1/translate"
# Ключ веб-страницы translate.google.com (не личный, виден в её коде) — в репозиторий не
# кладётся: переменная GOOGLE_TRANSLATE_KEY или файл ~/.config/translate-google.key.
# Без ключа сразу идёт запасной адрес (словарь Chrome, ключ не нужен).
PA_KEY = os.environ.get("GOOGLE_TRANSLATE_KEY", "")
if not PA_KEY:
    try:
        PA_KEY = open(os.path.expanduser("~/.config/translate-google.key")).read().strip()
    except OSError:
        pass
DICT_URL = "https://clients5.google.com/translate_a/t"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0"


def _get(url, params, timeout):
    req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def google(text, src, tgt, timeout=2.0):
    """Перевод или None (нет сети, Google не ответил)."""
    sl = "auto" if src in AUTO else CODES.get(src, "auto")
    tl = CODES.get(tgt, "ru")
    try:
        if not PA_KEY:
            raise OSError("нет ключа")
        d = _get(PA_URL, {"params.client": "gtx", "query.source_language": sl,
                          "query.target_language": tl, "query.display_language": "en",
                          "query.text": text, "key": PA_KEY, "data_types": "TRANSLATION"}, timeout)
        out = (d.get("translation") or "").strip()
        if out:
            return out
    except (OSError, ValueError):
        pass
    try:                                       # запасной адрес — словарь Chrome, модель попроще
        d = _get(DICT_URL, {"client": "dict-chrome-ex", "sl": sl, "tl": tl, "q": text}, timeout)
        out = d[0] if isinstance(d, list) and d else ""
        if isinstance(out, list):              # при sl=auto: [перевод, язык]
            out = out[0]
        return out.strip() or None
    except (OSError, ValueError, IndexError, TypeError):
        return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("translate_google.py ТЕКСТ [SRC] [TGT]")
    res = google(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "rus_Cyrl",
                 sys.argv[3] if len(sys.argv) > 3 else "eng_Latn", timeout=8)
    if not res:
        sys.exit(1)
    print(res)
