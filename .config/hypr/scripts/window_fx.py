#!/usr/bin/env python3
"""Эффект открытия и закрытия окон в niri — «пиксельная мозаика». 02.10.2026.

    window_fx.py get              pixel | off
    window_fx.py set pixel|off    включить / выключить (niri перечитывает конфиг сам)

Идея подсмотрена в дотфайлах AngelOS (там лицензии нет — взята только идея,
шейдеры написаны свои). niri умеет свой GLSL-шейдер для window-open/window-close
(animations → custom-shader). Наш эффект под пиксельный стиль стола:
  * открытие — окно проявляется крупными квадратами в случайном порядке, а сама
    картинка сначала грубая мозаика, которая быстро становится чёткой;
  * закрытие — окно так же рассыпается на квадраты и гаснет.
Шейдер лёгкий (одна выборка текстуры на пиксель), идёт долю секунды.

Пишется отдельный файл ~/.config/niri/cfg/window-fx.kdl (подключён в config.kdl
ПОСЛЕ cfg/animations.kdl, поэтому перекрывает только window-open/window-close).
off — в файле одни комментарии, действуют прежние анимации из animations.kdl.
Состояние — сам файл (первая строка-метка).
"""
import os
import subprocess
import sys

KDL = os.path.expanduser("~/.config/niri/cfg/window-fx.kdl")
BLOCK = 18          # сторона квадрата мозаики, px

OPEN = """
            float jhash(vec2 p) {
                return fract(sin(dot(p, vec2(127.1, 311.7)) + niri_random_seed * 43.0) * 43758.5453);
            }
            vec4 open_color(vec3 coords_geo, vec3 size_geo) {
                if (coords_geo.x < 0.0 || coords_geo.x > 1.0 || coords_geo.y < 0.0 || coords_geo.y > 1.0)
                    return vec4(0.0);
                float p = niri_clamped_progress;
                vec2 px = coords_geo.xy * size_geo.xy;
                float cell = max(1.0, mix(%(coarse).1f, 1.0, smoothstep(0.0, 0.85, p)));
                vec2 snapped = (floor(px / cell) + 0.5) * cell / size_geo.xy;
                vec3 ct = niri_geo_to_tex * vec3(snapped, 1.0);
                vec4 color = texture2D(niri_tex, ct.st);
                float r = jhash(floor(px / %(block).1f));
                float vis = step(r, p * 1.35);
                return color * vis;
            }
"""

CLOSE = """
            float jhash(vec2 p) {
                return fract(sin(dot(p, vec2(127.1, 311.7)) + niri_random_seed * 43.0) * 43758.5453);
            }
            vec4 close_color(vec3 coords_geo, vec3 size_geo) {
                if (coords_geo.x < 0.0 || coords_geo.x > 1.0 || coords_geo.y < 0.0 || coords_geo.y > 1.0)
                    return vec4(0.0);
                float p = niri_clamped_progress;
                vec2 px = coords_geo.xy * size_geo.xy;
                float cell = max(1.0, mix(1.0, %(coarse).1f, smoothstep(0.1, 1.0, p)));
                vec2 snapped = (floor(px / cell) + 0.5) * cell / size_geo.xy;
                vec3 ct = niri_geo_to_tex * vec3(snapped, 1.0);
                vec4 color = texture2D(niri_tex, ct.st);
                float r = jhash(floor(px / %(block).1f));
                float vis = step(p * 1.35, r);
                return color * vis;
            }
"""


def text(mode):
    head = "// window-fx: %s — пишет ~/.config/hypr/scripts/window_fx.py, руками не править\n" % mode
    if mode != "pixel":
        return head + "// выключено: действуют анимации из cfg/animations.kdl\n"
    v = {"block": float(BLOCK), "coarse": float(BLOCK)}
    return head + """animations {
    window-open {
        duration-ms 260
        curve "ease-out-quad"
        custom-shader r"
%s        "
    }
    window-close {
        duration-ms 220
        curve "linear"
        custom-shader r"
%s        "
    }
}
""" % (OPEN % v, CLOSE % v)


def get():
    try:
        return "pixel" if "window-fx: pixel" in open(KDL).readline() else "off"
    except OSError:
        return "off"


def main():
    a = sys.argv[1:]
    if not a or a[0] == "get":
        print(get())
        return 0
    if a[0] == "set" and len(a) > 1 and a[1] in ("pixel", "off"):
        old = None
        try:
            old = open(KDL).read()
        except OSError:
            pass
        with open(KDL, "w") as f:
            f.write(text(a[1]))
        r = subprocess.run(["niri", "validate"], capture_output=True, text=True)
        if r.returncode != 0:
            # конфиг не прошёл проверку — вернуть как было, окна не ломаем
            with open(KDL, "w") as f:
                f.write(old if old is not None else text("off"))
            print("niri validate: ошибка — эффект не включён\n" + (r.stderr or r.stdout)[-400:], file=sys.stderr)
            return 1
        subprocess.run(["niri", "msg", "action", "load-config-file"], capture_output=True)
        print(a[1])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
