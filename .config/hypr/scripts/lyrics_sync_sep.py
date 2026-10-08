#!/usr/bin/env python3
"""Отделить вокал от музыки (demucs htdemucs) — шаг lyrics_sync.py. 06.10.2026.

    ~/.local/share/lyrics-sync/venv/bin/python lyrics_sync_sep.py ВХОД.wav ВЫХОД.wav

Вход — запись потока плеера (pw-record: 44,1 кГц, стерео, s16). Выход — только голос,
16 кГц моно s16: то, что ждёт Whisper. Без torchaudio-ввода/вывода: wav читается и
пишется модулем wave, пересэмплирование — torchaudio.functional (чистый torch).
"""
import sys
import wave

import numpy as np
import torch
import torchaudio.functional as AF
from demucs.apply import apply_model
from demucs.pretrained import get_model


def read_wav(path):
    with wave.open(path) as w:
        sr, ch, n = w.getframerate(), w.getnchannels(), w.getnframes()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
    return torch.from_numpy(a.reshape(-1, ch).T.copy()), sr


def write_wav(path, mono, sr):
    a = (np.clip(mono.numpy(), -1, 1) * 32767).astype(np.int16)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(a.tobytes())


def main():
    src, dst = sys.argv[1], sys.argv[2]
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = get_model("htdemucs").to(dev).eval()
    wav, sr = read_wav(src)
    if wav.shape[0] == 1:
        wav = wav.repeat(2, 1)
    wav = wav[:2]
    if sr != model.samplerate:
        wav = AF.resample(wav, sr, model.samplerate)
    ref = wav.mean(0)
    mu, sd = ref.mean(), ref.std() + 1e-8
    with torch.no_grad():
        out = apply_model(model, ((wav - mu) / sd)[None].to(dev), split=True, overlap=0.25,
                          progress=False, device=dev)[0]
    voc = out[model.sources.index("vocals")].cpu() * sd + mu
    mono = AF.resample(voc.mean(0), model.samplerate, 16000)
    write_wav(dst, mono, 16000)
    print("ok %.1f s" % (mono.shape[0] / 16000))


if __name__ == "__main__":
    main()
