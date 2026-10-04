#!/usr/bin/env python3
"""Подсветка Razer BlackWidow V3 — в гамме обоев, по профилю пользователя.

Профиль — пользовательский эффект Polychromatic «static-white»
(~/.config/polychromatic/effects/staticwhite.json): одна карта 6×22 клавиш в
трёх цветах. Раскладка (какие клавиши каким цветом) сохраняется, а сами три
цвета подменяются оттенками из палитры matugen — так подсветка следует за
обоями, но не становится одноцветной (просьба 23.09.2026: «не всё, а гамму,
близкую к акценту, по моему профилю»).

Сопоставление: цвета исходного профиля ранжируются по числу клавиш —
  самый массовый  -> primary (акцент обоев),
  второй          -> tertiary (соседний тон палитры),
  третий          -> светлый оттенок акцента (primary, смешанный с белым).
Если цветов в профиле больше трёх, остальные получают ещё более светлые
оттенки акцента. Порядок стабилен между обоями — раскладка «читается» так же.

Результат пишется в ~/.config/polychromatic/effects/matugen-accent.json
(исходный файл не трогается) и применяется через `polychromatic-cli -e`.

    kbd_colors.py            собрать и применить
    kbd_colors.py --dry      только показать, что во что перекрасится
    KBD_SOURCE=<файл>        другой исходный профиль
"""
import json
import os
import subprocess
import sys
from collections import Counter

HOME = os.path.expanduser("~")
SOURCE = os.environ.get("KBD_SOURCE", os.path.join(
    HOME, ".config/polychromatic/effects/staticwhite.json"))
OUT = os.path.join(HOME, ".config/polychromatic/effects/matugen-accent.json")
PALETTE = os.path.join(HOME, ".cache/matugen/colors.json")
VIVID = os.path.join(HOME, ".cache/matugen/vivid.txt")


def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def mix(a, b, t):
    a, b = hex_to_rgb(a), hex_to_rgb(b)
    return rgb_to_hex(tuple(a[i] * (1 - t) + b[i] * t for i in range(3)))


def load_palette():
    roles = json.load(open(PALETTE))
    accent = roles.get("primary")
    try:
        v = open(VIVID).read().strip()
        if v.startswith("#") and len(v) == 7:
            accent = v          # насыщенный тон обоев — на светодиодах читается лучше
    except OSError:
        pass
    tertiary = roles.get("tertiary") or mix(accent, "#ffffff", 0.35)
    return accent, tertiary


def shift(h, degrees, sat_add=0.0, val_mul=1.0):
    """Тот же цвет, повёрнутый по кругу оттенков на degrees, насыщеннее на sat_add."""
    import colorsys
    r, g, b = (c / 255 for c in hex_to_rgb(h))
    hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
    hue = (hue + degrees / 360.0) % 1.0
    sat = min(1.0, max(0.0, sat + sat_add))
    val = min(1.0, val * val_mul)
    return rgb_to_hex(tuple(int(round(c * 255)) for c in colorsys.hsv_to_rgb(hue, sat, val)))


def targets(n, accent, tertiary):
    # Три цвета должны различаться на глаз, а не только по названию роли:
    # tertiary у жёлтой палитры выходил бледно-зелёным, а «светлый акцент» —
    # тем же жёлтым чуть светлее, и клавиатура казалась одноцветной (# 23.09.2026: «чуть заметнее разницу»). Второй — tertiary, но насыщеннее;
    # третий — акцент, повёрнутый на 40° к соседнему тону (у жёлтого —
    # к оранжевому), а не разбавленный белым.
    out = [accent, shift(tertiary, 0, sat_add=0.25), shift(accent, -40, sat_add=0.05)]
    step = 0.45
    while len(out) < n:
        out.append(mix(accent, "#ffffff", step))
        step = min(0.9, step + 0.12)
    return out[:n]


def main():
    dry = "--dry" in sys.argv
    try:
        eff = json.load(open(SOURCE))
    except OSError as e:
        print("kbd_colors: нет профиля: %s" % e, file=sys.stderr)
        return 1

    frames = eff.get("frames") or []
    counts = Counter()
    for frame in frames:
        for _x, col in frame.items():
            for _y, c in col.items():
                counts[c.lower()] += 1
    if not counts:
        print("kbd_colors: в профиле нет клавиш с цветом", file=sys.stderr)
        return 1

    accent, tertiary = load_palette()
    order = [c for c, _ in counts.most_common()]
    mapping = dict(zip(order, targets(len(order), accent, tertiary)))

    for src, dst in mapping.items():
        print("  %s (%3d клавиш) -> %s" % (src, counts[src], dst))
    if dry:
        return 0

    new = json.loads(json.dumps(eff))
    for frame in new["frames"]:
        for _x, col in frame.items():
            for y in list(col):
                col[y] = mapping.get(col[y].lower(), col[y])
    new["name"] = "matugen-accent"
    new["summary"] = "static-white в гамме обоев; собирает kbd_colors.py"
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w") as f:
        json.dump(new, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT)

    # Применяем напрямую через python-openrazer, а не `polychromatic-cli -e`:
    # тот запускает polychromatic-helper, который не завершается (играет
    # эффект как процесс) — для одного статичного кадра это лишний демон.
    # Здесь кадр просто рисуется в матрицу клавиатуры один раз.
    try:
        from openrazer.client import DeviceManager
    except Exception as e:
        print("kbd_colors: python-openrazer недоступен: %s" % e, file=sys.stderr)
        return 1
    devs = [d for d in DeviceManager().devices if d.type == "keyboard"]
    if not devs:
        print("kbd_colors: клавиатура Razer не найдена", file=sys.stderr)
        return 1
    dev = devs[0]
    m = dev.fx.advanced.matrix
    rows, cols = dev.fx.advanced.rows, dev.fx.advanced.cols
    frame = new["frames"][0]
    for x, col in frame.items():
        for y, c in col.items():
            r_, c_ = int(y), int(x)
            if 0 <= r_ < rows and 0 <= c_ < cols:
                m[r_, c_] = hex_to_rgb(c)
    dev.fx.advanced.draw()

    # Чтобы при входе трей Polychromatic поднял НАШ профиль, а не прежний
    # static-white: его файл состояния указывает на последний применённый эффект.
    state_dir = os.path.join(HOME, ".config/polychromatic/states")
    try:
        sp = os.path.join(state_dir, "%s.json" % dev.serial)
        st = json.load(open(sp)) if os.path.exists(sp) else {}
        st["effect"] = {"name": new["name"],
                        "icon": (st.get("effect") or {}).get("icon", ""),
                        "path": OUT}
        os.makedirs(state_dir, exist_ok=True)
        json.dump(st, open(sp, "w"))
    except Exception as e:
        print("kbd_colors: состояние Polychromatic не обновлено: %s" % e, file=sys.stderr)

    laptop_led(accent)
    print("kbd_colors: применено, акцент %s" % accent)
    return 0


LAPTOP_LED = "/sys/class/leds/rgb:kbd_backlight/multi_intensity"


def laptop_led(accent):
    """Встроенная подсветка ноутбука (tuxedo_keyboard) — одноцветная, в акцент.

    Меняется только цвет; яркость (вкл/выкл, уровень) остаётся за kbdlight и
    idle_dim. Узел принадлежит root, запись открывает udev-правило
    /etc/udev/rules.d/91-kbd-rgb-color.rules — без него тихо пропускаем.
    """
    if not os.access(LAPTOP_LED, os.W_OK):
        return
    r, g, b = hex_to_rgb(accent)
    try:
        with open(LAPTOP_LED, "w") as f:
            f.write("%d %d %d\n" % (r, g, b))
    except OSError as e:
        print("kbd_colors: подсветка ноутбука: %s" % e, file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
