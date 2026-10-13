#!/usr/bin/env python3
"""Значок kitty в цвет акцента обоев — во всех местах, где он берётся из темы значков
(нижняя панель, док, Alt+Tab, «Пуск», список программ, лаунчер). 13.10.2026, Просьба: «иконку kitty покрасить в акцентный цвет… чтобы при смене обоев она сама красилась везде».

Красится оттенок: у цветных точек тон и насыщенность берутся от акцента
(~/.cache/matugen/vivid.txt, тот же, что у папок), светлота остаётся своя; белое и
серое (глаза, «>_») не трогается. Две темы:
  Papirus-Wall  — SVG из Papirus с заменёнными цветами (вектор, без мыла);
  Jarvis-Pixel  — пиксельный kitty.png из кэша, перекрашенный по точкам.

  kitty_icon.py apply     перекрасить в обеих темах на месте (зовёт theme_changer.sh)
  kitty_icon.py check     совпадает ли цвет значков с акцентом (rc 1 — нет)
  kitty_icon.py off       вернуть исходные значки (Papirus-Wall и Jarvis-Pixel пересобираются)

Пересборка тем (folder_colors.py, icon_theme.py build) сама зовёт paint_* перед
подменой папки, поэтому перекраска не слетает. Бэкапов не нужно: обе темы
генерируются целиком, исходники (Papirus, кэш ~/.cache/jarvis-pixel-apps) не меняются.
"""
import colorsys
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
VIVID = os.path.join(HOME, ".cache/matugen/vivid.txt")
PAPIRUS = "/usr/share/icons/Papirus"
WALL = os.path.join(HOME, ".local/share/icons/Papirus-Wall")
PIXEL = os.path.join(HOME, ".local/share/icons/Jarvis-Pixel")
STATE = os.path.join(HOME, ".config/hypr/state/kitty-icon")   # «off» — не красить
NAMES = ("kitty",)
MIN_SAT = 0.08      # точки бледнее — серые/белые, остаются как есть (лапы Papirus — 0.13)
PAPIRUS_MAIN = (0xc1, 0x6d, 0x35)   # рыжий кот Papirus — его цвет станет ровно акцентом


def enabled():
    try:
        return open(STATE).read().strip() != "off"
    except OSError:
        return True


def accent():
    try:
        v = open(VIVID).read().strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", v):
            return v.lower()
    except OSError:
        pass
    return "#4877b1"


def _hls(hexs):
    x = hexs.lstrip("#")
    return colorsys.rgb_to_hls(*(int(x[i:i + 2], 16) / 255 for i in (0, 2, 4)))


def tint_rgb(r, g, b, acc, ref_l=None):
    """(0..255)*3 -> (0..255)*3: тон и насыщенность акцента. Светлота сдвигается так,
    чтобы основной цвет значка (светлота ref_l) стал ровно акцентом, тени и блики
    остаются темнее/светлее его на столько же."""
    h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    if s < MIN_SAT or l < 0.06 or l > 0.96:
        return r, g, b
    ah, al, as_ = acc
    if ref_l is not None:
        l = min(0.92, max(0.08, l + al - ref_l))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(ah, l, max(as_, 0.45)))


def _tint_hex(m, acc, ref_l=None):
    x = m.group(1)
    if len(x) == 3:
        x = "".join(c * 2 for c in x)
    r, g, b = (int(x[i:i + 2], 16) for i in (0, 2, 4))
    return "#%02x%02x%02x" % tint_rgb(r, g, b, acc, ref_l)


def _ref_l(rgb):
    return colorsys.rgb_to_hls(*(c / 255 for c in rgb))[1]


def _write(path, data, binary=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb" if binary else "w", **({} if binary else {"encoding": "utf-8"})) as f:
        f.write(data)
    os.replace(tmp, path)     # жёсткая ссылка на кэш (Jarvis-Pixel) так не портится


# ---------------------------------------------------------------- Papirus-Wall --

def papirus_dirs():
    """[(«48x48/apps», путь к SVG)] — размеры, где у Papirus есть kitty."""
    out = []
    for size in sorted(os.listdir(PAPIRUS)):
        for n in NAMES:
            p = os.path.join(PAPIRUS, size, "apps", n + ".svg")
            if os.path.isfile(p):
                out.append((size + "/apps", n, os.path.realpath(p)))
    return out


def paint_papirus(root, acc_hex=None):
    """Положить перекрашенные SVG в тему root. -> список каталогов («48x48/apps»)."""
    if not enabled():
        return []
    acc = _hls(acc_hex or accent())
    dirs = []
    for sub, n, src in papirus_dirs():
        svg = open(src, encoding="utf-8").read()
        ref = _ref_l(PAPIRUS_MAIN)
        svg = re.sub(r"#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", lambda m: _tint_hex(m, acc, ref), svg)
        _write(os.path.join(root, sub, n + ".svg"), svg)
        sub not in dirs and dirs.append(sub)
    return dirs


def papirus_sections(dirs):
    """Описания каталогов из index.theme самого Papirus."""
    idx = open(os.path.join(PAPIRUS, "index.theme"), encoding="utf-8").read()
    out = []
    for d in dirs:
        m = re.search(r"^\[%s\]\n(.*?)(?=^\[|\Z)" % re.escape(d), idx, re.S | re.M)
        if m:
            out.append("[%s]\n%s" % (d, m.group(1).strip()))
    return out


def _add_dirs(index_path, dirs, sections):
    """Дописать каталоги в готовый index.theme (если их там ещё нет)."""
    text = open(index_path, encoding="utf-8").read()
    m = re.search(r"^Directories=(.*)$", text, re.M)
    have = [d for d in m.group(1).split(",") if d] if m else []
    new = [d for d in dirs if d not in have]
    if not new:
        return False
    text = text.replace(m.group(0), "Directories=" + ",".join(have + new), 1)
    text = text.rstrip("\n") + "\n\n" + "\n\n".join(s for s in sections
                                                    if s.split("]")[0][1:] in new) + "\n"
    _write(index_path, text)
    return True


# ---------------------------------------------------------------- Jarvis-Pixel --

def paint_pixel(root, acc_hex=None):
    """Перекрасить пиксельный kitty.png во всех размерах темы root. -> число файлов."""
    if not enabled():
        return 0
    from PIL import Image
    acc = _hls(acc_hex or accent())
    cache = os.path.join(HOME, ".cache/jarvis-pixel-apps")
    done = 0
    for size in os.listdir(root) if os.path.isdir(root) else ():
        for n in NAMES:
            p = os.path.join(root, size, "apps", n + ".png")
            if not os.path.isfile(p):
                continue
            src = os.path.join(cache, size.split("x")[0], n + ".png")     # исходник — не перекрашенный
            im = Image.open(src if os.path.isfile(src) else p).convert("RGBA")
            px = im.load()
            # основной цвет — самый частый цветной (у пиксельного kitty — фон)
            counts = {}
            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, a = px[x, y]
                    if a > 200 and colorsys.rgb_to_hls(r / 255, g / 255, b / 255)[2] >= MIN_SAT:
                        counts[(r, g, b)] = counts.get((r, g, b), 0) + 1
            ref = _ref_l(max(counts, key=counts.get)) if counts else None
            memo = {}
            for y in range(im.height):
                for x in range(im.width):
                    r, g, b, a = px[x, y]
                    if a:
                        k = (r, g, b)
                        if k not in memo:
                            memo[k] = tint_rgb(r, g, b, acc, ref)
                        px[x, y] = memo[k] + (a,)
            tmp = p + ".tmp"
            im.save(tmp, format="PNG")
            os.replace(tmp, p)
            done += 1
    return done


# -------------------------------------------------------------------- команды --

def _cache_refresh(root):
    if os.path.isdir(root):
        subprocess.run(["gtk-update-icon-cache", "-q", "-f", "-t", root], capture_output=True)


def apply():
    acc = accent()
    msg = []
    if os.path.isfile(os.path.join(WALL, "index.theme")):
        dirs = paint_papirus(WALL, acc)
        _add_dirs(os.path.join(WALL, "index.theme"), dirs, papirus_sections(dirs))
        _cache_refresh(WALL)
        msg.append("Papirus-Wall: %d размеров" % len(dirs))
    n = paint_pixel(PIXEL, acc)
    if n:
        _cache_refresh(PIXEL)
        msg.append("Jarvis-Pixel: %d файлов" % n)
    print("kitty в цвет %s — %s" % (acc, ", ".join(msg) or "тем не найдено"))
    return 0


def check():
    if not enabled():
        print("kitty_icon: выключено (state/kitty-icon = off)")
        return 0
    acc = accent()
    want = "#%02x%02x%02x" % tint_rgb(*PAPIRUS_MAIN, _hls(acc), _ref_l(PAPIRUS_MAIN))
    p = os.path.join(WALL, "48x48/apps/kitty.svg")
    try:
        ok = want in open(p, encoding="utf-8").read().lower()
    except OSError:
        ok = False
    print("kitty_icon: %s (акцент %s)" % ("в цвет акцента" if ok else "НЕ перекрашен", acc))
    return 0 if ok else 1


def off():
    _write(STATE, "off\n")
    here = os.path.dirname(os.path.abspath(__file__))
    # Пересобрать обе темы без перекраски
    try:
        os.remove(os.path.join(WALL, ".color"))
    except OSError:
        pass
    subprocess.run([sys.executable, os.path.join(here, "folder_colors.py")], capture_output=True)
    subprocess.run([sys.executable, os.path.join(here, "icon_theme.py"), "build", "--force"],
                   capture_output=True)
    print("kitty_icon: выключено, исходные значки возвращены; включить — kitty_icon.py on")
    return 0


def on():
    try:
        os.remove(STATE)
    except OSError:
        pass
    return apply()


def main(argv):
    cmd = argv[1] if len(argv) > 1 else "apply"
    fn = {"apply": apply, "check": check, "off": off, "on": on}.get(cmd)
    if not fn:
        print(__doc__)
        return 2
    return fn()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
