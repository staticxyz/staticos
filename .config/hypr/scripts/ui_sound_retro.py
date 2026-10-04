#!/usr/bin/env python3
"""Ретро-набор звуков интерфейса: синтез «старого железа» в WAV. 02.10.2026.

    ui_sound_retro.py            собрать набор в ~/.config/hypr/sounds/retro/
    ui_sound_retro.py СОБЫТИЕ    пересобрать один звук

Просьба: «хочу отдельные звуки в стиле old tech / retro». Готовых файлов не
берём — всё считается здесь, как на звуковом чипе 8-битной приставки:
прямоугольная волна с разной скважностью, ступенчатый «треугольник», шум с
выборкой-хранением, громкость 16 ступенями. Сверху — срез верхов и низов, как
у маленького динамика. Играет их ui_sound.py (набор «retro»).

Звуки:
    screenshot  затвор: щелчок, короткий «чк-кшш» шумом
    done        «предмет получен»: четыре ноты вверх, последняя тянется
    error       два низких жужжащих гудка вниз
    unlock      щелчок реле и две ноты вверх
    login       писк самопроверки и короткая заставка с эхом
Поменять звук — правьте ноты в SOUNDS ниже и запустите скрипт заново.
"""
import os
import sys
import wave

import numpy as np

SR = 44100
OUT = os.path.expanduser("~/.config/hypr/sounds/retro")
PEAK = 0.5                     # запас до полной шкалы; громкость задаёт ui_sound.py

NOTE = {n: i for i, n in enumerate(["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"])}


def hz(name):
    """«A5» → 880.0"""
    return 440.0 * 2 ** ((NOTE[name[:-1]] + 12 * (int(name[-1]) - 4) - 9) / 12)


def env(n, attack=0.002, decay=None, hold=1.0):
    """Огибающая: быстрая атака, затем ровно (hold) или спад; 16 ступеней, как у чипа."""
    t = np.arange(n) / SR
    e = np.minimum(1.0, t / attack) * hold
    if decay:
        e *= np.exp(-t / decay)
    e *= np.minimum(1.0, (n - np.arange(n)) / (0.004 * SR))       # без щелчка в конце
    return np.round(e * 15) / 15


def square(freq, dur, duty=0.5, slide=0.0, **kw):
    n = int(dur * SR)
    f = freq * (1 + slide * np.arange(n) / max(1, n))
    ph = np.cumsum(f) / SR
    return np.where(ph % 1.0 < duty, 1.0, -1.0) * env(n, **kw)


def triangle(freq, dur, **kw):
    n = int(dur * SR)
    ph = (freq * np.arange(n) / SR) % 1.0
    tri = 2 * np.abs(2 * ph - 1) - 1
    return np.round(tri * 7.5) / 7.5 * env(n, **kw)               # 16 ступеней


def noise(dur, rate=8000, seed=1, **kw):
    """Шум с выборкой-хранением: чем ниже rate, тем «грубее» шипение."""
    n = int(dur * SR)
    rng = np.random.default_rng(seed)
    vals = rng.choice([-1.0, 1.0], size=int(dur * rate) + 2)
    return vals[(np.arange(n) * rate / SR).astype(int)] * env(n, **kw)


def silence(dur):
    return np.zeros(int(dur * SR))


def seq(*parts):
    return np.concatenate(parts)


def mix(*tracks):
    out = np.zeros(max(len(t) for t in tracks))
    for t in tracks:
        out[:len(t)] += t
    return out


def echo(x, delay=0.11, gain=0.32, taps=3):
    d = int(delay * SR)
    out = np.concatenate([x, np.zeros(d * taps)])
    for i in range(1, taps + 1):
        out[d * i:d * i + len(x)] += x * gain ** i
    return out


def speaker(x, low=5200.0, high=180.0):
    """Маленький динамик: однополюсные срезы верхов и низов."""
    a = 1 - np.exp(-2 * np.pi * low / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i, v in enumerate(x):
        acc += a * (v - acc)
        y[i] = acc
    b = 1 - np.exp(-2 * np.pi * high / SR)
    acc = 0.0
    for i, v in enumerate(y):
        acc += b * (v - acc)
        y[i] = v - acc
    return y


def s_screenshot():
    return seq(square(2637, 0.012, 0.5),
               noise(0.022, rate=14000, seed=3, decay=0.012),
               silence(0.030),
               noise(0.090, rate=9000, seed=5, decay=0.030))


def s_done():
    notes = [("G5", 0.055), ("C6", 0.055), ("E6", 0.055)]
    return seq(*[square(hz(n), d, 0.25, hold=0.85) for n, d in notes],
               square(hz("G6"), 0.30, 0.25, decay=0.10))


def s_error():
    return seq(square(hz("G3"), 0.11, 0.5, hold=0.9),
               silence(0.035),
               square(hz("D3"), 0.17, 0.5, hold=0.9, decay=0.25))


def s_unlock():
    return seq(noise(0.008, rate=20000, seed=7),
               silence(0.018),
               square(hz("A5"), 0.060, 0.125, hold=0.85),
               square(hz("D6"), 0.200, 0.125, decay=0.075))


def s_login():
    beep = seq(square(1000, 0.090, 0.5, hold=0.7), silence(0.110))
    lead = seq(*[square(hz(n), d, 0.25, hold=0.8) for n, d in
                 [("C5", 0.075), ("E5", 0.075), ("G5", 0.075), ("C6", 0.075), ("G5", 0.075)]],
               square(hz("C6"), 0.36, 0.25, decay=0.14))
    bass = seq(triangle(hz("C3"), 0.225, hold=0.7), triangle(hz("G3"), 0.150, hold=0.7),
               triangle(hz("C3"), 0.36, hold=0.7, decay=0.20))
    return seq(beep, echo(mix(lead, bass * 0.8)))


# ── вторая пачка (02.10.2026): события добавились вместе с набором Windows XP ──
def s_logout():
    return echo(seq(*[square(hz(n), 0.09, 0.25, hold=0.8) for n in ("C6", "G5", "E5")],
                    square(hz("C5"), 0.30, 0.25, decay=0.12)), delay=0.09, gain=0.25, taps=2)


def s_shutdown():
    lead = seq(*[square(hz(n), 0.11, 0.25, hold=0.8) for n in ("G5", "E5", "C5", "G4")],
               square(hz("C4"), 0.5, 0.25, decay=0.2))
    return echo(mix(lead, seq(silence(0.44), triangle(hz("C3"), 0.5, hold=0.7, decay=0.25))))


def s_usb_in():
    return seq(square(hz("E5"), 0.07, 0.125, hold=0.8), square(hz("B5"), 0.16, 0.125, decay=0.07))


def s_usb_out():
    return seq(square(hz("B5"), 0.07, 0.125, hold=0.8), square(hz("E5"), 0.16, 0.125, decay=0.07))


def s_battery_low():
    return seq(square(hz("A4"), 0.12, 0.5, hold=0.8), silence(0.06), square(hz("A4"), 0.12, 0.5, hold=0.8),
               silence(0.06), square(hz("E4"), 0.25, 0.5, decay=0.15))


def s_battery_critical():
    one = seq(square(hz("A5"), 0.08, 0.5, hold=0.9), silence(0.05))
    return seq(one, one, one, one, square(hz("D4"), 0.3, 0.5, decay=0.2))


def s_menu():
    return seq(noise(0.004, rate=20000, seed=11), square(hz("C6"), 0.035, 0.25, decay=0.02))


def s_click():
    return seq(square(hz("G6"), 0.018, 0.125, decay=0.012))


def s_nav():
    return seq(noise(0.006, rate=16000, seed=13, decay=0.004), square(1800, 0.012, 0.5, decay=0.008))


def s_timer():
    ring = seq(*[seq(square(hz("E6"), 0.045, 0.5, hold=0.9), square(hz("C6"), 0.045, 0.5, hold=0.9))
                 for _ in range(4)])
    return seq(ring, silence(0.18), ring, silence(0.18), ring)


def s_notify():
    return seq(square(hz("D6"), 0.06, 0.25, hold=0.8), silence(0.03), square(hz("A6"), 0.14, 0.25, decay=0.06))


def s_window_open():
    return square(hz("C5"), 0.09, 0.25, slide=0.9, decay=0.06)


def s_window_close():
    return square(hz("C6"), 0.09, 0.25, slide=-0.45, decay=0.06)


SOUNDS = {"screenshot": s_screenshot, "done": s_done, "error": s_error,
          "unlock": s_unlock, "login": s_login,
          "logout": s_logout, "shutdown": s_shutdown, "usb-in": s_usb_in, "usb-out": s_usb_out,
          "battery-low": s_battery_low, "battery-critical": s_battery_critical,
          "menu": s_menu, "click": s_click, "nav": s_nav, "timer": s_timer, "notify": s_notify,
          "window-open": s_window_open, "window-close": s_window_close}


def build(name):
    x = speaker(SOUNDS[name]())
    x = np.concatenate([x, np.zeros(int(0.02 * SR))])
    x = x / max(1e-9, np.max(np.abs(x))) * PEAK
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name + ".wav")
    with wave.open(path + ".tmp", "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())
    os.replace(path + ".tmp", path)
    return path, len(x) / SR


def main():
    names = [a for a in sys.argv[1:] if a in SOUNDS] or list(SOUNDS)
    for name in names:
        path, dur = build(name)
        print("%-11s %.2f с  %s" % (name, dur, path))


if __name__ == "__main__":
    main()
