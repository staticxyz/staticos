#!/usr/bin/env python3
"""Звуки Замка (30.10.2026): всё синтезировано здесь, по-приставочному — квадрат, треугольник, шум.

Файлы собираются один раз в ~/.config/hypr/sounds/castle/. Громкость, тишина при «Не беспокоить»,
записи экрана и игре — как у звуков интерфейса (ui_sound). Клавиша m в окне глушит только Замок.

    castle_sound.py build        собрать заново
    castle_sound.py play ИМЯ     сыграть
"""
import array
import math
import os
import random
import sys
import wave

import ui_sound

DIR = os.path.join(ui_sound.OWN, "castle")
MUTE = os.path.join(ui_sound.STATE, "castle-mute")
RATE = 22050
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def hz(name):
    return 440 * 2 ** ((NOTE[name[0]] + ("#" in name) + 12 * (int(name[-1]) - 4) - 9) / 12)


def blank(sec):
    return [0.0] * int(sec * RATE)


def put(buf, at, sec, freq, kind="square", vol=0.3, slide=0.0, decay=6.0, duty=0.5):
    """Одна нота в буфер: at — начало, slide — на сколько Гц уезжает за ноту."""
    start, n = int(at * RATE), int(sec * RATE)
    phase = 0.0
    rnd = random.Random(int(freq) + start)
    noise = 0.0
    for i in range(n):
        if start + i >= len(buf):
            break
        t = i / n
        f = freq + slide * t
        phase = (phase + f / RATE) % 1
        if kind == "square":
            s = 1.0 if phase < duty else -1.0
        elif kind == "tri":
            s = 4 * abs(phase - 0.5) - 1
        elif kind == "sine":
            s = math.sin(phase * 6.283)
        else:
            if int(phase * 2) != int((phase - f / RATE) % 1 * 2) or i == 0:
                noise = rnd.uniform(-1, 1)
            s = noise
        env = min(1.0, i / 40) * math.exp(-decay * t) * min(1.0, (n - i) / 60)
        buf[start + i] += s * vol * env


def melody(buf, at, notes, step, kind="square", vol=0.28, decay=2.5, duty=0.5):
    for i, n in enumerate(notes):
        if n:
            put(buf, at + i * step, step * 1.15, hz(n), kind, vol, decay=decay, duty=duty)


def sounds():
    out = {}

    b = blank(0.16)                                  # заряд упал в копилку
    put(b, 0, 0.05, hz("E6"), vol=0.28, duty=0.25)
    put(b, 0.05, 0.1, hz("B6"), vol=0.28, duty=0.25, decay=5)
    out["brick"] = b

    b = blank(0.09)                                  # выбор на дорожке
    put(b, 0, 0.07, hz("A5"), "tri", 0.45)
    out["select"] = b

    b = blank(0.1)                                   # удар молотка
    put(b, 0, 0.07, 1700, "noise", 0.45, decay=9)
    put(b, 0, 0.06, 240, "square", 0.25, slide=-120, decay=8)
    out["hammer"] = b

    b = blank(0.4)                                   # деталь встала
    put(b, 0, 0.32, 150, "tri", 0.7, slide=-100, decay=5)
    put(b, 0, 0.18, 500, "noise", 0.4, decay=7)
    out["thump"] = b

    b = blank(0.22)                                  # пока рано: мягко, не наказание
    put(b, 0, 0.09, hz("E4"), "tri", 0.45)
    put(b, 0.09, 0.12, hz("C4"), "tri", 0.45)
    out["soft"] = b

    b = blank(0.5)                                   # сундук прилетел и трясётся
    put(b, 0, 0.3, 110, "tri", 0.7, slide=-40, decay=6)
    put(b, 0.02, 0.1, 400, "noise", 0.3, decay=8)
    put(b, 0.18, 0.2, 90, "tri", 0.5, slide=-20, decay=7)
    out["land"] = b

    b = blank(0.6)                                   # крышка открылась
    for i, n in enumerate(("C5", "E5", "G5", "C6", "E6", "G6")):
        put(b, i * 0.055, 0.14, hz(n), "square", 0.2, duty=0.25, decay=4)
    put(b, 0, 0.3, 1200, "noise", 0.12, slide=3000, decay=4)
    out["open"] = b

    b = blank(1.5)                                   # ступень построена
    melody(b, 0, ("G4", "C5", "E5", "G5", None, "E5", "G5"), 0.11, vol=0.24, duty=0.25)
    melody(b, 0.77, ("C6",), 0.6, vol=0.26, decay=2.2, duty=0.25)
    melody(b, 0, ("C3", None, "G3", None, "C3", None, "G3"), 0.11, "tri", 0.5)
    put(b, 0.77, 0.6, hz("C4"), "tri", 0.5, decay=2)
    put(b, 0.77, 0.6, hz("G5"), "square", 0.12, decay=2.2)
    out["built"] = b

    b = blank(3.0)                                   # победа: собеседование
    lead = ("C5", "C5", "C5", "C5", "G#4", "A#4", "C5", None, "A#4", "C5")
    times = (0, 0.1, 0.2, 0.3, 0.5, 0.7, 0.9, None, 1.1, 1.2)
    for n, at in zip(lead, times):
        if n:
            put(b, at, 0.2, hz(n), "square", 0.24, duty=0.25, decay=3)
    put(b, 1.3, 1.2, hz("E5"), "square", 0.2, duty=0.25, decay=2)
    put(b, 1.3, 1.2, hz("C5"), "square", 0.14, decay=2)
    put(b, 1.3, 1.2, hz("G5"), "square", 0.14, decay=2)
    put(b, 1.3, 1.5, hz("C6"), "tri", 0.3, decay=1.6)
    for at, n in ((0, "C3"), (0.2, "G3"), (0.5, "G#2"), (0.7, "D#3"), (0.9, "A#2"), (1.1, "F3"), (1.3, "C3"), (1.5, "G3"), (1.7, "C4")):
        put(b, at, 0.22, hz(n), "tri", 0.5, decay=2)
    for i in range(12):
        put(b, 1.35 + i * 0.09, 0.08, hz("C6") * (1 + (i % 4) * 0.25), "square", 0.05, duty=0.125, decay=6)
    out["victory"] = b
    return out


def build():
    os.makedirs(DIR, exist_ok=True)
    for name, buf in sounds().items():
        peak = max(1.0, max(abs(x) for x in buf))
        data = array.array("h", (int(x / peak * 30000) for x in buf))
        with wave.open(os.path.join(DIR, name + ".wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(data.tobytes())


def muted():
    return os.path.exists(MUTE)


def set_muted(on):
    if on:
        open(MUTE, "w").close()
    elif muted():
        os.remove(MUTE)


def play(name):
    if muted():
        return False
    path = os.path.join(DIR, name + ".wav")
    if not os.path.exists(path):
        build()
    return ui_sound.play_file(path)


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["build"]:
        build()
    elif a[:1] == ["play"] and a[1:]:
        ui_sound.play_file(os.path.join(DIR, a[1] + ".wav"), wait=True)
