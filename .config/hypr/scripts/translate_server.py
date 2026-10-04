#!/usr/bin/env python3
# Needs ctranslate2 + sentencepiece; calc_qalc.py runs it with $TRANSLATE_PYTHON
# (default: ~/.local/share/jarvis-translate/venv/bin/python).
"""Офлайн-переводчик для калькулятора SUPER+C (17.09.2026, NLLB с 23.09.2026).

Держит в памяти одну модель NLLB-200 (distilled 600M, int8) и отвечает через
сокет $XDG_RUNTIME_DIR/jarvis-translate.sock:
    {"text": "...", "src": "rus_Cyrl", "tgt": "eng_Latn"}  →  {"out": "..."}
Старый вид запроса {"dir": "ru_en"} тоже понимается. Запускает службу
calc_qalc.py при первом переводе, сама она выгружается после IDLE секунд без
запросов.

Почему NLLB вместо пар Argos. Argos — маленькие парные модели, и качество
было соответствующее: «нейронная сеть» → «neuralnet», «приве» → «featuring»,
«hello world» → «Адский мир» (журнал ~/.cache/calc_qalc.last). Новых языков
(немецкий, японский, корейский — просьба пользователя) пришлось бы ставить по паре
на направление. NLLB-200 — одна модель на ~200 языков в обе стороны, заметно
точнее, движок тот же ctranslate2. Готовая конвертация: HF
JustFrederik/nllb-200-distilled-600M-ct2-int8 (~600 МБ), лежит в MODEL.
Старые модели Argos оставлены в models/ru_en, models/en_ru на случай отката.

Коды языков — как у NLLB: rus_Cyrl, eng_Latn, deu_Latn, jpn_Jpan, kor_Hang.
Источник кодируется токеном языка в начале, цель — префиксом декодера.

Устройство: процессор (int8, 4 потока) — замер 23.09.2026: 100–300 мс на
фразу, для строки rofi хватает. CUDA — только по JARVIS_TRANSLATE_CUDA=1: в
venv нет библиотек CUDA (libcublas.so.12), а ставить их ради 100 мс и делить
4 ГБ видеопамяти с играми и озвучкой не стоит.
"""
import json
import os
import re
import signal
import socket
import threading
import time

import ctranslate2
import sentencepiece as spm

BASE = os.path.expanduser("~/.local/share/jarvis-translate/models")
MODEL = os.path.join(BASE, "nllb-600M-int8")
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-translate.sock")
IDLE = 600
BEAM = 4
LANGS = {"rus_Cyrl", "eng_Latn", "deu_Latn", "jpn_Jpan", "kor_Hang", "kaz_Cyrl",
         "fra_Latn", "spa_Latn", "ita_Latn", "zho_Hans", "tur_Latn", "ukr_Cyrl"}
# Совместимость со старым протоколом.
DIRS = {"ru_en": ("rus_Cyrl", "eng_Latn"), "en_ru": ("eng_Latn", "rus_Cyrl")}

last_use = time.time()
cache = {}


def load():
    use_cuda = (bool(os.environ.get("JARVIS_TRANSLATE_CUDA"))
                and ctranslate2.get_cuda_device_count() > 0)
    sp = spm.SentencePieceProcessor(model_file=os.path.join(MODEL, "sentencepiece.bpe.model"))
    if use_cuda:
        # Translator на «cuda» создаётся без ошибки и падает только на первом
        # переводе, если нет libcublas (так и было 23.09.2026) — поэтому пробный
        # перевод здесь, а не проверка устройства.
        try:
            tr = ctranslate2.Translator(MODEL, device="cuda", compute_type="int8_float16")
            tr.translate_batch([["eng_Latn"] + sp.encode("hi", out_type=str) + ["</s>"]],
                               target_prefix=[["rus_Cyrl"]], beam_size=1, max_decoding_length=4)
        except Exception:                       # нет библиотек CUDA — тихо на процессор
            use_cuda = False
    if not use_cuda:
        tr = ctranslate2.Translator(MODEL, device="cpu", compute_type="int8", intra_threads=4)
    return tr, sp


def translate(models, src, tgt, text):
    key = (src, tgt, text)
    if key in cache:
        return cache[key]
    tr, sp = models
    tokens = [src] + sp.encode(text, out_type=str) + ["</s>"]
    res = tr.translate_batch([tokens], target_prefix=[[tgt]], beam_size=BEAM,
                             max_decoding_length=256, repetition_penalty=1.1)
    hyp = [t for t in res[0].hypotheses[0] if t not in (tgt, "</s>")]
    out = sp.decode(hyp).strip()
    # Словарь NLLB режет пунктуацию отдельными кусками, и после склейки
    # остаются «Hey , what 's up ?» — прижимаем знаки и апострофы.
    out = re.sub(r"\s+([,.!?;:)\]])", r"\1", out)
    out = re.sub(r"([(\[])\s+", r"\1", out)
    out = re.sub(r"\s*'\s*", "'", out)
    # Модель дописывает точку к любой фразе: «привет» → «Hello.». Если в
    # исходнике знака в конце не было, убираем.
    if out.endswith((".", "。")) and not text.rstrip().endswith((".", "!", "?", "…", "。")):
        out = out[:-1]
    if len(cache) > 2000:
        cache.clear()
    cache[key] = out
    return out


def serve(models, conn):
    global last_use
    with conn:
        data = b""
        while not data.endswith(b"\n"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            data += chunk
        try:
            req = json.loads(data.decode("utf-8"))
            if req.get("dir") in DIRS:
                src, tgt = DIRS[req["dir"]]
            else:
                src, tgt = req.get("src", "rus_Cyrl"), req.get("tgt", "eng_Latn")
            if src not in LANGS or tgt not in LANGS or src == tgt:
                raise ValueError("языки: %s → %s" % (src, tgt))
            out = translate(models, src, tgt, req["text"][:2000])
            reply = {"out": out}
        except Exception as e:                      # плохой запрос — ответить, не падать
            reply = {"error": str(e)}
        last_use = time.time()
        conn.sendall((json.dumps(reply, ensure_ascii=False) + "\n").encode("utf-8"))


def idle_watch(server):
    while True:
        time.sleep(15)
        if time.time() - last_use > IDLE:
            server.close()
            try:
                os.unlink(SOCK)
            except OSError:
                pass
            os._exit(0)


def main():
    # Вторая копия (две буквы подряд, пока первая грузит модель) выходит сразу:
    # иначе она удалила бы сокет первой.
    import fcntl
    lock = open(SOCK + ".lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return
    models = load()
    try:
        os.unlink(SOCK)
    except OSError:
        pass
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(SOCK + ".tmp")
    except OSError:
        pass
    server.bind(SOCK + ".tmp")
    os.chmod(SOCK + ".tmp", 0o600)
    os.rename(SOCK + ".tmp", SOCK)                  # сокет появляется уже готовым
    server.listen(8)
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    threading.Thread(target=idle_watch, args=(server,), daemon=True).start()
    while True:
        try:
            conn, _ = server.accept()
        except OSError:
            break
        serve(models, conn)


if __name__ == "__main__":
    main()
