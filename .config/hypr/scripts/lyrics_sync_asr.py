#!/usr/bin/env python3
"""Слова голоса со временем (faster-whisper) — шаг lyrics_sync.py. 06.10.2026.

    ~/.local/share/lyrics-sync/venv/bin/python lyrics_sync_asr.py ГОЛОС.wav ВЫХОД.json [ЯЗЫК]

Вход — голос 16 кГц моно (lyrics_sync_sep.py). Выход — {"language", "segments": [{"start",
"end", "text", "words": [[слово, начало, конец], …]}]}. Модель large-v3-turbo на видеокарте
(int8_float16, ~1 ГБ памяти); без видеокарты — на процессоре, int8 (медленно).
condition_on_previous_text=False: на песнях Whisper иначе зацикливается на припеве.
"""
import json
import sys
import wave

import numpy as np
from faster_whisper import WhisperModel

MODEL = "large-v3-turbo"


def main():
    src, dst = sys.argv[1], sys.argv[2]
    lang = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else None
    with wave.open(src) as w:
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    try:
        model = WhisperModel(MODEL, device="cuda", compute_type="int8_float16")
    except Exception:
        model = WhisperModel(MODEL, device="cpu", compute_type="int8")
    segs, info = model.transcribe(audio, language=lang, beam_size=5, word_timestamps=True,
                                  condition_on_previous_text=False, vad_filter=False,
                                  no_speech_threshold=0.6,
                                  # язык — по нескольким отрезкам, а не по первым 30 с: во
                                  # вступлении голоса нет, и испанская песня шла как английская
                                  language_detection_segments=4)
    out = {"language": info.language, "segments": []}
    for s in segs:
        out["segments"].append({"start": s.start, "end": s.end, "text": s.text.strip(),
                                "logprob": s.avg_logprob, "nospeech": s.no_speech_prob,
                                "words": [[w.word.strip(), w.start, w.end] for w in (s.words or [])]})
    with open(dst, "w") as f:
        json.dump(out, f, ensure_ascii=False)
    print("ok %s, %d отрезков" % (info.language, len(out["segments"])))


if __name__ == "__main__":
    main()
