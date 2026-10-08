#!/usr/bin/env python3
"""Пиксельные обои: любые обои показываются как пиксель-арт. 03.10.2026.

    wallpaper_pixel.py get             -> on | off
    wallpaper_pixel.py on|off|toggle   переключить и применить
    wallpaper_pixel.py level [1..3]    размер пикселя: 1 мелкий, 2 средний, 3 крупный
    wallpaper_pixel.py make ФАЙЛ       сделать копию и напечатать путь (для проверок)

Просьба пользователя: «Можем сделать такую настройку: переключать все обои в пиксельные?
Чтобы это красиво, эстетично выглядело». Настройки → Visuals → «Пиксельные обои».

Как сделано. Сами файлы обоев не трогаются: рядом, в ~/.cache/wallpaper-pixel/, лежит
пиксельная копия, и она показывается вместо оригинала — тем же путём, что и размытая
(wallpaper_blur.py apply: он зовётся после каждой смены обоев, так что новые обои
становятся пиксельными сами). Палитра интерфейса по-прежнему берётся из оригинала.

Как получается «пиксель-арт», а не просто мозаика:
  1. картинка вписывается в экран и уменьшается в PIXEL раз (усреднением — без ряби);
  2. чуть прибавляются насыщенность и контраст — у пиксель-арта чистые цвета;
  3. цвета сводятся к палитре из COLORS оттенков, подобранной под саму картинку;
  4. перед этим добавляется упорядоченный узор 4×4 (Bayer): плавные переходы неба не
     рвутся на полосы, а получают «ретро-штриховку», как на старых приставках;
  5. увеличение обратно — без сглаживания, пиксели остаются квадратными.
Копия делается один раз на обои и размер (~1 с), дальше берётся готовая. Анимированные
обои (gif) не трогаются.
"""
import hashlib
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/wallpaper-pixel")
LEVEL_STATE = os.path.expanduser("~/.config/hypr/state/wallpaper-pixel-level")
CACHE = os.path.expanduser("~/.cache/wallpaper-pixel")
LEVELS = {1: ("мелкий", 3), 2: ("средний", 4), 3: ("крупный", 6)}     # сторона пикселя, px
DEFAULT_LEVEL = 2
COLORS = 40
DITHER = 16          # размах узора в ступенях яркости (0 — без штриховки)
SIZE = (1920, 1080)
KEEP = 40            # сколько копий держать в кэше


def is_on():
    try:
        return open(STATE).read().strip() == "on"
    except OSError:
        return False


def level():
    try:
        n = int(open(LEVEL_STATE).read().strip())
        return n if n in LEVELS else DEFAULT_LEVEL
    except (OSError, ValueError):
        return DEFAULT_LEVEL


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f:
        f.write(text + "\n")
    os.replace(path + ".tmp", path)


def pixelated(path, size=SIZE):
    """Путь к пиксельной копии (делается при первом обращении); None — не вышло."""
    if not path or path.lower().endswith((".gif", ".webm", ".mp4")):
        return None
    # Обои, которые уже пиксель-арт (в имени «pixelart», напр. искорки из
    # sparkle_wallpaper.py), показываются как есть: усреднение и растр съели
    # бы лучи толщиной в 2 px (08.10.2026).
    if "pixelart" in os.path.basename(path).lower():
        return None
    try:
        st = os.stat(path)
    except OSError:
        return None
    k = LEVELS[level()][1]
    key = hashlib.sha1(("%s|%d|%d|%d|%d|%dx%d" % (path, st.st_mtime_ns, k, COLORS, DITHER,
                                                  size[0], size[1])).encode()).hexdigest()[:16]
    out = os.path.join(CACHE, key + ".png")
    if os.path.isfile(out):
        os.utime(out)                              # «недавно нужна» — для уборки кэша
        return out
    try:
        import numpy as np
        from PIL import Image, ImageEnhance, ImageOps
        w, h = size
        im = ImageOps.fit(Image.open(path).convert("RGB"), (w, h), Image.LANCZOS)
        small = im.resize((max(1, w // k), max(1, h // k)), Image.BOX)
        small = ImageEnhance.Color(small).enhance(1.15)
        small = ImageEnhance.Contrast(small).enhance(1.06)
        # палитра — по картинке без узора, иначе в неё попали бы «шумовые» цвета
        pal = small.quantize(colors=COLORS, method=Image.MEDIANCUT, kmeans=2, dither=Image.NONE)
        if DITHER:
            bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
                             dtype=np.float32) / 16 - 0.5
            a = np.asarray(small, dtype=np.float32)
            t = np.tile(bayer, (a.shape[0] // 4 + 1, a.shape[1] // 4 + 1))[:a.shape[0], :a.shape[1], None]
            small = Image.fromarray(np.clip(a + t * DITHER, 0, 255).astype(np.uint8))
        res = small.quantize(palette=pal, dither=Image.NONE).convert("RGB").resize((w, h), Image.NEAREST)
        os.makedirs(CACHE, exist_ok=True)
        tmp = out + ".tmp.png"
        res.save(tmp, optimize=False, compress_level=3)
        os.replace(tmp, out)
        _prune()
        return out
    except Exception as e:
        print("пиксельные обои: %s" % e, file=sys.stderr)
        return None


def _prune():
    try:
        files = sorted((os.path.join(CACHE, n) for n in os.listdir(CACHE) if n.endswith(".png")),
                       key=os.path.getmtime, reverse=True)
        for old in files[KEEP:]:
            os.remove(old)
    except OSError:
        pass


def apply():
    """Показать то, что положено по состоянию (пиксели и размытие решает один скрипт)."""
    r = subprocess.run([sys.executable, os.path.join(HERE, "wallpaper_blur.py"), "apply"],
                       capture_output=True, text=True)
    # Виджеты на обоях рисуют под собой размытый кусок обоев и пересчитывают его, когда
    # меняется их файл стиля, — трогаем его время, чтобы подложка стала пиксельной тоже.
    try:
        os.utime(os.path.expanduser("~/.config/hypr/state/desktop-widgets-style.json"))
    except OSError:
        pass
    return (r.stdout or r.stderr).strip()


def main():
    a = sys.argv[1:] or ["get"]
    if a[0] == "get":
        print("on" if is_on() else "off")
    elif a[0] in ("on", "off", "toggle"):
        want = (not is_on()) if a[0] == "toggle" else a[0] == "on"
        _write(STATE, "on" if want else "off")
        print("%s; %s" % ("пиксельные" if want else "обычные", apply()))
    elif a[0] == "level":
        if len(a) == 1:
            print(level())
        else:
            try:
                n = max(1, min(3, int(a[1])))
            except ValueError:
                return 1
            _write(LEVEL_STATE, str(n))
            print("%s пиксель; %s" % (LEVELS[n][0], apply() if is_on() else "выключено"))
    elif a[0] == "make" and len(a) > 1:
        print(pixelated(os.path.expanduser(a[1])) or "")
    else:
        print(__doc__, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
