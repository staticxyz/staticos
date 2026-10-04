#!/usr/bin/env python3
"""Эквалайзер для waybar поверх обычного cava.

Зачем не встроенный модуль "cava" waybar: у него не работает автоусиление.
Замерено на живом баре — при autosens = 1 модуль замирал во всех попытках,
полоски стояли на потолке и не шевелились; с autosens = 0 громкость ничем не
нормируется, и на громкой музыке они точно так же упираются в верх. Плюс тот
модуль изредка стартовал замороженным: три перезапуска подряд с одними и теми
же настройками дали один мёртвый и два живых.

Здесь запускается настоящий cava с сырым выводом — тот же, что у вас в
терминале, с рабочим autosens, — а его числа переводятся в символы блоков.
Если cava падает, он поднимается заново через RESTART_S секунд.
"""
import os
import subprocess
import threading
import sys
import time

CONFIG = os.path.expanduser("~/.config/cava/waybar.conf")
# Девять ступеней, и ДВЕ первые — пробел (23.09.2026). Раньше вторым стоял
# "▁" — полоска в один пиксель по нижнему краю. На слух это уже тишина, а на
# экране под полосками всё время дрожала строчка точек: «ниже уровня рисует
# пиксели». Теперь самая низкая видимая ступень — "▂".
LEVELS = "  ▂▃▄▅▆▇█"
RESTART_S = 3
# Как часто отдавать кадр панели. 1/30 с вместо 1/25: движение между двумя
# соседними ступенями заметно глазу, и чем чаще кадры, тем оно плавнее.
# Выше 30 смысла нет — waybar не успевает перерисовываться.
SEND_INTERVAL = 0.033


# ── Режим «волна» (30.09.2026, по образцу Noctalia) ─────────────────────────
# Выбор — ~/.config/hypr/state/bar-vis: "blocks" (как было, по умолчанию) или
# "wave". Переключатель в Настройках → Внешний вид. Файл проверяется раз в
# секунду: смена режима подхватывается на лету, бар перезапускать не нужно.
# Волна рисуется шрифтом JarvisWave (build_wave_font.py): 48 столбиков по 2 px,
# зеркально вверх-вниз и влево-вправо (низкие частоты — в середине), края
# сведены на нет. Плавность: своё сглаживание во времени поверх cava — быстрый
# подъём, медленный спад; тихий звук приподнят степенью 0.7, чтобы не
# «пара квадратиков», а маленькая, но цельная волна.
MODE_FILE = os.path.expanduser("~/.config/hypr/state/bar-vis")
WAVE_CONFIG = os.path.expanduser("~/.config/cava/waybar-wave.conf")
WAVE_COLS = 38                                # 76 px — длина прежних блоков (просьба: «как было»)
WAVE_LEVELS = 10
WAVE_BASE = 0xE300
WAVE_OPEN = '<span font="JarvisWave 18" letter_spacing="0">'   # у #custom-cava в CSS разрядка 2px для блоков — у волны она рвала столбики
QUIET_HIDE_S = 1.2        # столько тишины — и модуль прячется


def mode():
    try:
        return "wave" if open(MODE_FILE).read().strip() == "wave" else "blocks"
    except OSError:
        return "blocks"


def wave_text(vals):
    import math
    pts = list(reversed(vals)) + list(vals)          # зеркально: середина — басы
    n = len(pts)
    out = []
    for c in range(WAVE_COLS):
        x = c / (WAVE_COLS - 1) * (n - 1)
        i = int(x)
        j = min(i + 1, n - 1)
        t = (1 - math.cos((x - i) * math.pi)) / 2    # косинусная интерполяция
        v = pts[i] * (1 - t) + pts[j] * t
        v *= math.sin(math.pi * (c + 0.5) / WAVE_COLS) ** 0.6   # края на нет
        k = int(round((max(0.0, v) ** 0.7) * (WAVE_LEVELS - 1)))
        out.append(chr(WAVE_BASE + max(0, min(WAVE_LEVELS - 1, k))))
    return WAVE_OPEN + "".join(out) + "</span>"


def run_wave():
    proc = subprocess.Popen(["cava", "-p", WAVE_CONFIG],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    state = {"vals": None, "alive": True}

    def reader():
        for line in proc.stdout:
            parts = [p for p in line.strip().strip(";").split(";") if p.isdigit()]
            if parts:
                state["vals"] = [min(int(p), 1000) / 1000 for p in parts]
        state["alive"] = False

    threading.Thread(target=reader, daemon=True).start()
    sm = None
    last = None
    loud_at = 0.0
    checked = time.time()
    try:
        while state["alive"]:
            time.sleep(SEND_INTERVAL)
            if time.time() - checked > 1.0:
                checked = time.time()
                if mode() != "wave":
                    return
            target = state["vals"]
            if target is None:
                continue
            if sm is None or len(sm) != len(target):
                sm = [0.0] * len(target)
            sm = [a + (b - a) * (0.55 if b > a else 0.18) for a, b in zip(sm, target)]
            now = time.time()
            if max(sm) > 0.03:
                loud_at = now
            out = wave_text(sm) if now - loud_at < QUIET_HIDE_S else ""
            if out == last:
                continue
            last = out
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
    finally:
        proc.terminate()


def run_once():
    """Читать cava без остановки, а в waybar отдавать ТОЛЬКО свежий кадр.

    Здесь была настоящая причина «лагов». Модуль waybar перерисовывает себя на
    каждой полученной строке и делает это медленнее, чем cava их выдаёт. Когда
    мы писали кадры подряд, труба между нами и панелью заполнялась, наша запись
    начинала блокироваться, за нами вставал сам cava — и на экран попадало то,
    что прозвучало секунду назад. Чем дольше играла музыка, тем сильнее
    расходились звук и картинка.

    Теперь поток-читатель непрерывно вычерпывает cava (он никогда не ждёт нас)
    и держит последний кадр, а основной цикл отдаёт панели этот последний кадр
    строго по таймеру. Устаревшие кадры выбрасываются, очереди не возникает,
    задержка не накапливается.
    """
    proc = subprocess.Popen(
        ["cava", "-p", CONFIG],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    state = {"frame": None, "alive": True}

    def reader():
        for line in proc.stdout:
            parts = [p for p in line.strip().strip(";").split(";") if p.isdigit()]
            if parts:
                state["frame"] = "".join(
                    LEVELS[min(int(p), len(LEVELS) - 1)] for p in parts)
        state["alive"] = False

    t = threading.Thread(target=reader, daemon=True)
    t.start()

    last = None
    checked = time.time()
    try:
        while state["alive"]:
            time.sleep(SEND_INTERVAL)
            if time.time() - checked > 1.0:
                checked = time.time()
                if mode() == "wave":
                    return
            out = state["frame"]
            if out is None or out == last:
                continue
            last = out
            # Пустая строка прячет модуль целиком: waybar не рисует пилюлю,
            # когда текста нет. Так бар не занимает место в тишине.
            sys.stdout.write(("" if out.strip() == "" else out) + "\n")
            sys.stdout.flush()
    finally:
        proc.terminate()


def main():
    while True:
        was = mode()
        try:
            run_wave() if was == "wave" else run_once()
        except Exception:
            pass
        if mode() != was:
            continue       # режим сменился — сразу запустить другой, без паузы
        # cava мог не найти источник звука (например, при выходе из сна) —
        # пробуем снова, а не умираем вместе с ним.
        time.sleep(RESTART_S)


if __name__ == "__main__":
    main()
