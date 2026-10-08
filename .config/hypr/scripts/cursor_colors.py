#!/usr/bin/env python3
"""Курсор Jarvis — MSTCRSR в гамме обоев.

Форма одна (пиксельная тема MSTCRSR, исходники в ~/.local/share/jarvis-cursor/src),
палитра — из matugen. Каждый цвет исходника перекрашивается с сохранением его
светлоты (OKLab L): меняются только оттенок и насыщенность. Поэтому контраст
остаётся ровно таким, каким его нарисовал автор, — чёрная обводка и светлые
блики читаются и на тёмных, и на светлых окнах при любых обоях.

Роли (23.09.2026):
  чёрная обводка                  -> остаётся чёрной
  грифельное тело и блики         -> оттенок secondary (приглушённый тон обоев)
  камень стрелки, мятные акценты,
  бирюзовая анимация загрузки     -> акцент обоев (vivid.txt, иначе primary)
  камень ссылки (синий)           -> tertiary
  камень запрета и ожидания       -> error: красный остаётся красным по смыслу

Файлы XCursor пишутся здесь же, без xcursorgen. Размеры 32/48/64 — увеличение
по соседнему пикселю (48 — это ×1,5, пиксели там неровные: 1 и 2 точки).

niri не перечитывает картинки курсора, пока имя темы не изменилось, поэтому
тема собирается попеременно в два каталога — Jarvis-Cursor-A и -B, — и имя
свежего пишется в ~/.cache/matugen/niri-cursor.kdl (его подключает config.kdl
через include optional=true). Прежний каталог остаётся на месте: запущенные
приложения, которые держат его имя, не теряют курсор.

    cursor_colors.py            собрать по текущей палитре и включить
    cursor_colors.py --sheet F  собрать контактный лист PNG из текущей темы
    cursor_colors.py --off      вернуть breeze_cursors и больше не пересобирать
    cursor_colors.py --on       снова включить
"""
import json
import math
import os
import pathlib
import shutil
import struct
import re
import subprocess
import sys

from PIL import Image

HOME = pathlib.Path.home()
SRC = HOME / ".local/share/jarvis-cursor/src/src"
ICONS = HOME / ".local/share/icons"
PALETTE = HOME / ".cache/matugen/colors.json"
VIVID = HOME / ".cache/matugen/vivid.txt"
NIRI_INC = HOME / ".cache/matugen/niri-cursor.kdl"
XWAYLAND = HOME / ".icons/default/index.theme"
OFF_FLAG = HOME / ".local/share/jarvis-cursor/off"

NAMES = ("Jarvis-Cursor-A", "Jarvis-Cursor-B")
FALLBACK = ("breeze_cursors", 24)
# Размер курсора — ~/.config/hypr/state/cursor-size (cursor_colors.py --size N).
# Рисунок MSTCRSR — сетка 16×16, растянутая вдвое: чётко на 16, 32, 48, 64;
# 24 — полтора пикселя на пиксель, края чуть неровные (30.09.2026, пользователь
# попросил курсор поменьше). 16 и 24 собираются из родной сетки, контур у них
# в один экранный пиксель — как у 32.
SIZE_FILE = HOME / ".config/hypr/state/cursor-size"
ALLOWED = (16, 20, 24, 32, 48)    # 20 — 07.10.2026, «чуть компактнее» 24-го


def chosen_size():
    try:
        v = int(SIZE_FILE.read_text().strip())
        return v if v in ALLOWED else 32
    except (OSError, ValueError):
        return 32


SIZE = chosen_size()
SIZES = (32, 48, 64)
SMALL = (16, 20, 24)      # из родной сетки 16×16 (20 — ×1.25, края чуть неровные)
# Светлый контур в пиксель снаружи чёрной обводки (23.09.2026, просьба пользователя
# сделать курсор заметнее). Окна почти все тёмные, и тёмное тело MSTCRSR с чёрной
# обводкой на них терялось. На светлых окнах курсор держит чёрная обводка.
HALO = True
IMAGE_TYPE = 0xFFFD0002

# Из install.sh MSTCRSR: каталог исходника -> имя курсора, плюс синонимы.
CURSOR_MAP = {
    "Arrow_Crossed": "move", "Arrow_Horizontal": "col-resize",
    "Arrow_Vertical": "row-resize", "Bg_Loading": "progress",
    "Crosshair": "cross", "D_Arrow_1": "nw-resize", "D_Arrow_2": "ne-resize",
    # Рука для ссылок — своя (25.09.2026): у MSTCRSR «ссылка» (Hyperlink) —
    # та же стрелка с камнем другого цвета, а пользователь ждал руку. Hand нарисована
    # в той же сетке 16×16 блоками 2×2 и той же палитрой (исходник Hand/).
    "Handwriting": "pencil", "Hand": "pointer", "Idle": "default",
    "Input": "copy", "Loading": "watch", "Prohibition": "not-allowed",
    "Textbar": "text",
}
ALIASES = {
    "default": "left_ptr arrow X_cursor",
    "pointer": "hand hand2",
    "progress": "left_ptr_watch",
    "watch": "wait",
    "cross": "crosshair tcross diamond_cross",
    "copy": "dnd-copy dnd-link alias",
    "not-allowed": "no-drop dnd-none",
    "move": "fleur hand1 all-scroll",
    "nw-resize": "se-resize nwse-resize sizing",
    "ne-resize": "sw-resize nesw-resize",
    "col-resize": "e-resize w-resize ew-resize sb_h_double_arrow",
    "row-resize": "n-resize s-resize ns-resize sb_v_double_arrow",
    "text": "xterm",
}
# Свои синонимы сверх install.sh: имена, которые просят современные приложения.
# Без них при перетаскивании и на краях окон вылезал бы breeze из Inherits.
EXTRA_ALIASES = {
    "move": "grab grabbing openhand closedhand dnd-move",
    "default": "help question_arrow left_ptr_help context-menu",
    "cross": "cell plus",
    "text": "vertical-text",
    "copy": "dnd-ask",
    "row-resize": "top_side bottom_side size_ver",
    "col-resize": "left_side right_side size_hor",
    "nw-resize": "top_left_corner bottom_right_corner size_fdiag",
    "ne-resize": "top_right_corner bottom_left_corner size_bdiag",
}

NEUTRALS = {(0x28, 0x28, 0x3C), (0x50, 0x64, 0x78), (0xB4, 0xA0, 0xB4)}


# ------------------------------------------------------------------ цвет --
def hex_rgb(h):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _lin(c):
    c /= 255
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _unlin(c):
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def to_oklch(rgb):
    r, g, b = (_lin(c) for c in rgb)
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    bb = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(a, bb), math.degrees(math.atan2(bb, a)) % 360


def _oklch_to_linear(L, C, h):
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    return (4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
            -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
            -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s)


def from_oklch(L, C, h):
    """В sRGB; если цвет не помещается, насыщенность снижается до границы."""
    def fits(c):
        return all(-1e-4 <= v <= 1 + 1e-4 for v in _oklch_to_linear(L, c, h))
    if not fits(C):
        lo, hi = 0.0, C
        for _ in range(24):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if fits(mid) else (lo, mid)
        C = lo
    return tuple(max(0, min(255, round(_unlin(max(0.0, min(1.0, v))) * 255)))
                 for v in _oklch_to_linear(L, C, h))


def role_of(rgb, cursor_dir):
    if rgb == (0, 0, 0):
        return None
    if rgb in NEUTRALS:
        return "neutral"
    hue = to_oklch(rgb)[2]
    if hue >= 330 or hue < 40:          # малиновый и красный камень
        return "error"
    # Камень руки — акцентом, как у стрелки: tertiary у matugen розово-сиреневый
    # (313° против 278° у акцента), и на синих обоях рука казалась фиолетовой.
    if cursor_dir == "Hyperlink":
        return "link"
    return "primary"


def build_recolor(pal, colors_by_dir):
    """Словарь исходный цвет -> новый, для всех цветов всех кадров."""
    # Тело курсора: светлота и насыщенность — от secondary (приглушённый тон),
    # а ОТТЕНОК — от акцента обоев. У matugen secondary уводит в лаванду: на
    # тёмно-синих обоях 25.09.2026 он был 300°, акцент 278°, и рука выглядела
    # фиолетовой (Просьба: «хотя гамма обоев синяя»). Серость тела сохраняется.
    sec, viv = to_oklch(hex_rgb(pal["secondary"])), to_oklch(hex_rgb(pal["vivid"]))
    targets = {
        "neutral": (sec[0], sec[1], viv[2]),
        "primary": to_oklch(hex_rgb(pal["vivid"])),
        "link": to_oklch(hex_rgb(pal["tertiary"])),
        "error": to_oklch(hex_rgb(pal["error"])),
    }
    families = {}
    for d, cols in colors_by_dir.items():
        for rgb in cols:
            role = role_of(rgb, d)
            if role:
                families.setdefault(role, set()).add(rgb)
    # Насыщенность семейства растягивается так, чтобы самый насыщенный цвет
    # исходника получил насыщенность роли; не слабее 60 % исходной, иначе на
    # серых обоях камень выцветал бы в серый. У error — насыщенность исходника:
    # у matugen он в тёмной теме бледно-розовый, а камень должен быть красным.
    fmax = {r: max(to_oklch(c)[1] for c in cs) for r, cs in families.items()}
    # Мятный исходник очень светлый (L 0.91): на такой светлоте насыщенный синий
    # в sRGB не помещается, и на синих обоях акцент выцветал почти в белый.
    # Поэтому у акцентов всё семейство сдвигается вниз, пока самый светлый тон
    # не встанет на светлоту цвета роли. Сдвиг общий — ступени анимации
    # сохраняют свой порядок. Вверх не сдвигается, тело и error не трогаются.
    lmax = {r: max(to_oklch(c)[0] for c in cs) for r, cs in families.items()}
    table = {}
    for d, cols in colors_by_dir.items():
        for rgb in cols:
            role = role_of(rgb, d)
            if role is None:
                table[(d, rgb)] = rgb
                continue
            L, C, _ = to_oklch(rgb)
            Lt, Ct, ht = targets[role]
            # Порог 60 % — только у акцентов и только если у роли вообще есть
            # оттенок: у почти серой цели (C < 0.02) угол оттенка случаен, и с
            # порогом курсор получал бы цвет, которого в обоях нет.
            if role == "error" or not fmax[role]:
                k = 1.0
            elif role == "neutral" or Ct < 0.02:
                k = Ct / fmax[role]
            else:
                k = max(Ct / fmax[role], 0.6)
            if role in ("primary", "link"):
                L = max(0.2, L - max(0.0, lmax[role] - Lt))
            table[(d, rgb)] = from_oklch(L, C * k, ht)
    return table


def load_palette():
    pal = json.loads(PALETTE.read_text())
    try:
        pal["vivid"] = VIVID.read_text().strip() or pal["primary"]
    except OSError:
        pal["vivid"] = pal["primary"]
    return pal


# --------------------------------------------------------------- XCursor --
def read_xcg(d):
    frames = []
    for line in (d / "cursor.xcg").read_text().splitlines():
        p = line.split()
        if len(p) >= 4:
            frames.append((int(p[1]), int(p[2]), p[3], int(p[4]) if len(p) > 4 else 0))
    return frames


def write_xcursor(dest, images):
    """images: [(nominal, Image RGBA, xhot, yhot, delay)] в нужном порядке."""
    header = 16 + 12 * len(images)
    toc, chunks, pos = [], [], header
    for nominal, im, xh, yh, delay in images:
        alpha = im.getchannel("A")
        pre = Image.new("RGBA", im.size, (0, 0, 0, 0))
        pre.paste(im, mask=alpha)   # альфа только 0/255 — это и есть предумножение
        data = struct.pack("<9I", 36, IMAGE_TYPE, nominal, 1, im.width, im.height,
                           xh, yh, delay) + pre.tobytes("raw", "BGRA")
        toc.append(struct.pack("<III", IMAGE_TYPE, nominal, pos))
        chunks.append(data)
        pos += len(data)
    dest.write_bytes(struct.pack("<4sIII", b"Xcur", 16, 0x10000, len(images))
                     + b"".join(toc) + b"".join(chunks))


def read_xcursor(path, want=32):
    data = pathlib.Path(path).read_bytes()
    _, _, ntoc = struct.unpack_from("<III", data, 4)
    toc = [struct.unpack_from("<III", data, 16 + i * 12) for i in range(ntoc)]
    frames = []
    for typ, sub, pos in toc:
        if typ != IMAGE_TYPE or sub != want:
            continue
        _, _, _, _, w, h, xh, yh, delay = struct.unpack_from("<9I", data, pos)
        im = Image.frombytes("RGBA", (w, h), data[pos + 36:pos + 36 + w * h * 4], "raw", "BGRA")
        frames.append((im, delay))
    return frames


# ----------------------------------------------------------------- сборка --
def halo_color(pal):
    """Почти белый с оттенком secondary: светлый, но в тон остальной системе."""
    _, C, h = to_oklch(hex_rgb(pal["secondary"]))
    return from_oklch(0.95, min(C, 0.035), h)


def add_halo(im, rgb):
    """Пиксель светлого цвета вокруг силуэта, только по четырём соседям:
    по диагонали контур дал бы углам лишнюю толщину и размыл бы пиксель-арт.
    Картинка расширяется на пиксель с каждой стороны: часть курсоров MSTCRSR
    упирается в край, и контур там обрезался бы. Точку касания вызывающий
    сдвигает на +1."""
    padded = Image.new("RGBA", (im.width + 2, im.height + 2), (0, 0, 0, 0))
    padded.paste(im, (1, 1))
    im = padded
    w, h = im.size
    a = im.getchannel("A").load()
    out = im.copy()
    px = out.load()
    for y in range(h):
        for x in range(w):
            if a[x, y]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and a[nx, ny]:
                    px[x, y] = (*rgb, 255)
                    break
    return out


def pixels(im):
    # getdata() в Pillow 12 объявлен устаревшим и сыплет предупреждениями в журнал
    return im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()


def build(name):
    pal = load_palette()
    frames_by_dir, colors_by_dir = {}, {}
    for d in CURSOR_MAP:
        frames = [(Image.open(SRC / d / f).convert("RGBA"), xh, yh, delay)
                  for xh, yh, f, delay in read_xcg(SRC / d)]
        frames_by_dir[d] = frames
        colors_by_dir[d] = {px[:3] for im, *_ in frames
                            for px in pixels(im) if px[3]}
    table = build_recolor(pal, colors_by_dir)
    halo = halo_color(pal)

    tmp = ICONS / f".{name}.tmp-{os.getpid()}"
    shutil.rmtree(tmp, ignore_errors=True)
    (tmp / "cursors").mkdir(parents=True)
    (tmp / "index.theme").write_text(
        "[Icon Theme]\n"
        f"Name={name}\n"
        "Comment=MSTCRSR в палитре обоев — только для личного использования\n"
        "Inherits=breeze_cursors\n")

    for d, frames in frames_by_dir.items():
        recolored = []
        small = []
        for im, xh, yh, delay in frames:
            out = im.copy()
            out.putdata([(*table[(d, px[:3])], 255) if px[3] else (0, 0, 0, 0)
                         for px in pixels(im)])
            native = out.resize((out.width // 2, out.height // 2), Image.NEAREST)
            for s in SMALL:
                f = s / 16
                sm = native.resize((round(native.width * f), round(native.height * f)), Image.NEAREST)
                sx, sy = int(xh / 2 * f), int(yh / 2 * f)
                if HALO:
                    sm = add_halo(sm, halo)
                    sx, sy = sx + 1, sy + 1
                small.append((s, sm, sx, sy, delay))
            if HALO:
                out = add_halo(out, halo)
                xh, yh = xh + 1, yh + 1      # картинка сдвинулась на пиксель запаса
            recolored.append((out, xh, yh, delay))
        images = list(small)
        for size in SIZES:
            f = size / 32
            for im, xh, yh, delay in recolored:
                big = im.resize((round(im.width * f), round(im.height * f)), Image.NEAREST)
                images.append((size, big, int(xh * f), int(yh * f), delay))
        write_xcursor(tmp / "cursors" / CURSOR_MAP[d], images)

    for table_ in (ALIASES, EXTRA_ALIASES):
        for src, names in table_.items():
            for alias in names.split():
                link = tmp / "cursors" / alias
                if not link.exists():
                    link.symlink_to(src)

    target = ICONS / name
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    return target


def current_name():
    try:
        for line in NIRI_INC.read_text().splitlines():
            if "xcursor-theme" in line:
                return line.split('"')[1]
    except (OSError, IndexError):
        pass
    return None


# Файлы GTK для X11-программ. Под Wayland GTK читает gsettings, а под Xwayland
# без xsettingsd — только эти файлы; Steam (GTK2) 24.09.2026 из-за этого показывал
# breeze, пока всё остальное уже было Jarvis. app_fonts.py пишет сюда же шрифт.
GTK_INI = [HOME / ".config/gtk-3.0/settings.ini", HOME / ".config/gtk-4.0/settings.ini"]
GTKRC2 = HOME / ".gtkrc-2.0"


def _set_keys(path, pairs):
    """Подменяет строки key=value в ini-подобном файле; отсутствующие дописывает."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return
    for key, val in pairs:
        pat = re.compile(rf"^\s*{re.escape(key)}\s*=")
        hit = [i for i, l in enumerate(lines) if pat.match(l)]
        if hit:
            lines[hit[0]] = f"{key}={val}"
        else:
            lines.append(f"{key}={val}")
    path.write_text("\n".join(lines) + "\n")


def set_gtk_files(name, size):
    for ini in GTK_INI:
        _set_keys(ini, [("gtk-cursor-theme-name", name), ("gtk-cursor-theme-size", str(size))])
    # GTK2 хочет имя в кавычках.
    _set_keys(GTKRC2, [("gtk-cursor-theme-name", f'"{name}"'), ("gtk-cursor-theme-size", str(size))])


def activate(name, size):
    """niri (через include), GTK (gsettings + settings.ini + .gtkrc-2.0) и Xwayland (index.theme)."""
    NIRI_INC.parent.mkdir(parents=True, exist_ok=True)
    tmp = NIRI_INC.with_suffix(".tmp")
    tmp.write_text(
        "// Generated by ~/.config/hypr/scripts/cursor_colors.py — included from\n"
        "// ~/.config/niri/config.kdl. Имя чередуется A/B: иначе niri не перечитает курсор.\n"
        "cursor {\n"
        f'    xcursor-theme "{name}"\n'
        f"    xcursor-size {size}\n"
        "}\n")
    tmp.replace(NIRI_INC)
    for key, val in (("cursor-theme", name), ("cursor-size", str(size))):
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", key, val],
                       check=False, timeout=10)
    XWAYLAND.parent.mkdir(parents=True, exist_ok=True)
    XWAYLAND.write_text("[Icon Theme]\nName=Default\nComment=Default Cursor Theme\n"
                        f"Inherits={name}\n")
    set_gtk_files(name, size)


def contact_sheet(dest, name):
    cursors = ICONS / name / "cursors"
    names = list(CURSOR_MAP.values())
    cell, cols = 200, 7
    rows = math.ceil(len(names) / cols) * 2
    sheet = Image.new("RGBA", (cols * cell, rows * cell), (255, 255, 255, 255))
    for i, n in enumerate(names):
        im = read_xcursor(cursors / n)[0][0]
        big = im.resize((im.width * 5, im.height * 5), Image.NEAREST)
        for band, bg in ((0, (22, 24, 28, 255)), (1, (238, 238, 232, 255))):
            x = (i % cols) * cell
            y = ((i // cols) * 2 + band) * cell
            tile = Image.new("RGBA", (cell, cell), bg)
            tile.alpha_composite(big, ((cell - big.width) // 2, (cell - big.height) // 2))
            sheet.paste(tile, (x, y))
    sheet.save(dest)


def main():
    args = sys.argv[1:]
    if args[:1] == ["--off"]:
        OFF_FLAG.parent.mkdir(parents=True, exist_ok=True)
        OFF_FLAG.touch()
        activate(*FALLBACK)
        print("курсор Jarvis выключен, стоит", FALLBACK[0])
        return
    if args[:1] == ["--on"]:
        OFF_FLAG.unlink(missing_ok=True)
        args = []
    if args[:1] == ["--size"] and len(args) > 1:
        n = int(args[1])
        if n not in ALLOWED:
            print("размер: один из", ALLOWED)
            return
        SIZE_FILE.parent.mkdir(parents=True, exist_ok=True)
        SIZE_FILE.write_text(str(n))
        name = current_name() or NAMES[0]
        activate(name, n)
        print("размер курсора:", n)
        return
    if args[:1] == ["--sheet"]:
        name = current_name() or NAMES[0]
        contact_sheet(args[1], name)
        print("лист:", args[1], "из", name)
        return
    if OFF_FLAG.exists():
        return
    # Выбран другой курсор (cursor_theme.py, «Настройки» → «Курсор») — смена обоев
    # его не трогает; Jarvis собирается, только пока выбран он (28.09.2026).
    chosen = HOME / ".config/hypr/state/cursor-theme"
    if chosen.exists() and chosen.read_text().strip() not in ("", "jarvis"):
        print("выбран курсор", chosen.read_text().strip(), "— Jarvis не пересобираю")
        return
    now = current_name()
    name = NAMES[1] if now == NAMES[0] else NAMES[0]
    build(name)
    activate(name, SIZE)
    print("курсор:", name)


if __name__ == "__main__":
    main()
