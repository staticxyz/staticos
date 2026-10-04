#!/usr/bin/env python3
# Needs rembg; rec_area.sh runs it with $REMBG_PYTHON
# (default: ~/.local/share/uv/tools/rembg/bin/python, i.e. `uv tool install rembg`).
"""Убрать фон с кадров — для Recorder (rec_area.sh). 29.09.2026.

    rec_nobg.py ПАПКА_С_PNG ПАПКА_ВЫХОДА

Каждый PNG из первой папки → PNG с прозрачным фоном во вторую (имена те же).
Способ выбирается по первому кадру и держится на весь ролик, чтобы кадры не
«прыгали» между способами:

  по цвету — если края кадра почти одного цвета (окно, чат, сплошная заливка —
      на записи с экрана это самый частый случай). Фоном считается всё, что
      близко к этому цвету И связано с краем кадра: объект того же цвета внутри
      не пострадает. Мгновенно и точно.
  нейросеть — если фон пёстрый. Модель u2net (rembg): из пяти опробованных на
      процессоре она вырезала объект полнее всех, ~0.6 с на кадр. Если на кадре
      она оставила почти всё или почти ничего (первая версия на silueta стирала
      запись пользователя целиком, 29.09.2026), кадр переделывается по цвету.

Запускается питоном из окружения `uv tool install rembg` (строка #! выше).
Потоков — не все ядра, чтобы система не подвисала.
"""
import os
import subprocess
import sys
import time

THREADS = 6
os.environ.setdefault("OMP_NUM_THREADS", str(THREADS))

import numpy as np  # noqa: E402
from PIL import Image, ImageFilter  # noqa: E402
from scipy import ndimage  # noqa: E402

TOL = 38            # насколько цвет может отличаться от фона и всё ещё считаться фоном
UNIFORM = 0.75      # доля краевых пикселей, близких к основному цвету, для «однотонного» фона
MIN_KEEP, MAX_KEEP = 0.03, 0.97   # вне этих долей результат нейросети считается провалом


def say(text):
    subprocess.run(["notify-send", "-a", "Recorder", "-h",
                    "string:x-canonical-private-synchronous:jarvis-rec", "Убираю фон…", text],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def border(a):
    return np.concatenate([a[:2].reshape(-1, 3), a[-2:].reshape(-1, 3),
                           a[:, :2].reshape(-1, 3), a[:, -2:].reshape(-1, 3)])


def bg_color(a):
    """Основной цвет краёв кадра и доля краёв, близких к нему."""
    b = border(a).astype(np.int16)
    c = np.median(b, axis=0)
    near = np.linalg.norm(b - c, axis=1) < TOL
    return c, near.mean()


def key_alpha(a):
    """Маска по цвету: фон — близкие к цвету краёв пиксели, связанные с краем кадра."""
    c, _ = bg_color(a)
    near = np.linalg.norm(a.astype(np.int16) - c, axis=2) < TOL
    lab, _ = ndimage.label(near)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bg = np.isin(lab, edge[edge > 0])
    # Просветы внутри объекта не трогать: «закрыть» маску объекта на пару пикселей и
    # залить дыры. Иначе у картинки из точек (осьминог brrt) фон вырезался и между
    # точками, и от объекта оставалась сетка (проверено 29.09.2026).
    fg = ndimage.binary_closing(~bg, structure=np.ones((5, 5)), iterations=1)
    fg = ndimage.binary_fill_holes(fg)
    alpha = np.where(fg, 255, 0).astype(np.uint8)
    # Кромку чуть смягчить, чтобы не было «лесенки».
    return Image.fromarray(alpha).filter(ImageFilter.GaussianBlur(0.7))


def main():
    src, dst = sys.argv[1], sys.argv[2]
    os.makedirs(dst, exist_ok=True)
    frames = sorted(f for f in os.listdir(src) if f.endswith(".png"))
    if not frames:
        return 1
    first = np.asarray(Image.open(os.path.join(src, frames[0])).convert("RGB"))
    method = "цвет" if bg_color(first)[1] >= UNIFORM else "нейросеть"

    session = None
    if method == "нейросеть":
        import onnxruntime as ort
        from rembg import new_session
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = THREADS
        opts.inter_op_num_threads = 1
        session = new_session("u2net", sess_opts=opts)

    shown, fixed = 0.0, 0
    for i, name in enumerate(frames, 1):
        img = Image.open(os.path.join(src, name)).convert("RGB")
        a = np.asarray(img)
        if session is not None:
            from rembg import remove
            out = remove(img, session=session, post_process_mask=True)
            kept = (np.asarray(out.getchannel("A")) > 128).mean()
            if not MIN_KEEP <= kept <= MAX_KEEP:
                out = img.copy()
                out.putalpha(key_alpha(a))
                fixed += 1
        else:
            out = img.copy()
            out.putalpha(key_alpha(a))
        out.save(os.path.join(dst, name))
        if len(frames) > 1 and time.time() - shown > 1.5:
            say("кадр %d из %d  ·  способ: %s" % (i, len(frames), method))
            shown = time.time()
    print("способ: %s%s" % (method, ", по цвету переделано кадров: %d" % fixed if fixed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
