#!/usr/bin/env python3
"""Запечь Сусаноо в шейдер: контур тела и внутренние линии. 28.09.2026.

Итог долгого пути. Показать НАСТОЯЩУЮ картинку kitty не даёт: внешние текстуры
шейдеру недоступны, а `background_image` в 0.49.1 не рисуется вовсе. Данные в
коде шейдера стоят времени открытия окна (замер: ~1000 примитивов ≈ +1 с),
поэтому их должно быть немного — и тратить их надо с умом.

Первые заходы тратили их неправильно: растровая маска (мазня и тормоза), потом
проволочный каркас из 926 отрезков (лаги, и не похоже — в оригинале фигура
ЗАЛИТАЯ). Здесь примитивов втрое меньше, а сходства больше, потому что они
разложены по ролям:

    многоугольник ~126 точек  — граница тела, обведена по сплошному силуэту
                                 кадра (заливка + светящаяся кромка);
    ~190 отрезков             — главные внутренние линии: рёбра, руки, череп.

Исходник — кадр аниме с вики Naruto (`File:Madara incomplete ep368.png`).
Силуэт вырезан по синеве кадра, дыры залиты, граница обойдена по соседям Мура
и упрощена; линии — прежней обводкой (vectorise.py). Сборка хранится в
~/.local/share/jarvis/susanoo-shape.json.

Запуск: susanoo_bake.py [shape.json]
"""
import json
import os
import sys

SHAPE = os.path.expanduser("~/.local/share/jarvis/susanoo-shape.json")
DST = os.path.expanduser("~/.config/kitty/shaders/susanoo.slang")


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SHAPE
    d = json.load(open(src))
    poly, inner = d["poly"], d["inner"]

    lines = [f"static const int POLY_N = {len(poly)};",
             f"static const float2 POLY[{len(poly)}] = {{"]
    for i in range(0, len(poly), 4):
        lines.append("    " + ", ".join("float2(%.4f, %.4f)" % (x, y)
                                        for x, y in poly[i:i + 4]) + ",")
    lines.append("};")
    lines.append(f"static const int INNER_N = {len(inner)};")
    lines.append(f"static const float4 INNER[{len(inner)}] = {{")
    for i in range(0, len(inner), 2):
        lines.append("    " + ", ".join("float4(%.4f, %.4f, %.4f, %.4f)" % tuple(s)
                                        for s in inner[i:i + 2]) + ",")
    lines.append("};")

    s = open(DST, encoding="utf-8").read()
    a = s.index("// SHAPE-BEGIN")
    b = s.index("// SHAPE-END")
    s = s[:a] + "// SHAPE-BEGIN (собрано susanoo_bake.py — не править руками)\n" + \
        "\n".join(lines) + "\n" + s[b:]
    open(DST, "w", encoding="utf-8").write(s)
    print(f"запечено: контур {len(poly)} точек, внутренних линий {len(inner)} → {DST}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
