#!/usr/bin/env python3
"""SpaceTheme для Steam в палитре обоев и с шрифтом системы (28.09.2026).

Тема — SpaceTheme/Steam (Millennium), стоит клоном git в
~/.local/share/Steam/millennium/themes/SpaceTheme, чтобы у неё оставались
обновления. Поверх неё здесь две правки, обе повторяются при каждой смене обоев
(зовётся из theme_changer.sh), так что обновление темы их не теряет надолго:

  • src/css/root.css — цвета темы (Millennium берёт из него RootColors).
    Фоны и акцент — прямо из палитры matugen; у «красного/зелёного/синего/
    жёлтого» кнопок оттенок из палитры, а светлота и насыщенность — как в
    оригинале SpaceTheme, иначе светлые цвета палитры давали нечитаемые кнопки.
  • шрифт системы — вариант «Jarvis Pixel» в настройке темы Font (он же
    выбран по умолчанию; выбор в настройках Millennium главнее).

    steam_space.py apply     применить (цвета + шрифт)
    steam_space.py on|off    включить SpaceTheme | вернуть прежнюю JarvisPixel

Откат целиком: steam_space.py off и перезапуск Steam.
"""
import colorsys
import json
import os
import sys

THEME = os.path.expanduser("~/.local/share/Steam/millennium/themes/SpaceTheme")
COLORS = os.path.expanduser("~/.cache/matugen/colors.json")
VIVID = os.path.expanduser("~/.cache/matugen/vivid.txt")
MCONF = os.path.expanduser("~/.config/millennium/config.json")
FONT_NAME = "Jarvis Pixel"
FONT_FILE = "options/fonts/jarvisPixel.css"
FONT_CSS = ('/* Шрифт системы (Jarvis). Пишет ~/.config/hypr/scripts/steam_space.py */\n'
            '* {\n    font-family: "PxPlus HP 100LX 6x8 Jarvis", "PxPlus HP 100LX 6x8", monospace !important;\n}\n')


def rgb(hexstr):
    h = hexstr.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def retone(hexstr, ref):
    """Оттенок из палитры, светлота и насыщенность — как у ref (цвет SpaceTheme)."""
    h, _, _ = colorsys.rgb_to_hls(*(c / 255 for c in rgb(hexstr)))
    _, l, s = colorsys.rgb_to_hls(*(c / 255 for c in ref))
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, l, s))


def mix(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def palette():
    with open(COLORS) as f:
        d = json.load(f)
    c = d.get("colors", d)
    p = {k: (v.get("dark", v) if isinstance(v, dict) else v) for k, v in c.items()}
    try:
        with open(VIVID) as f:
            p["vivid"] = f.read().strip()
    except OSError:
        p["vivid"] = p["primary"]
    return p


def root_css(p):
    lines = ["    %s: %d, %d, %d;" % (k, *c) for k, c in colors(p).items()]
    return ":root {\n" + "\n".join(lines) + "\n}\n"


def save_colors(p):
    """Цвета и в настройки Millennium (themes.themeColors.SpaceTheme).

    Millennium читает root.css только пока у темы нет сохранённых цветов, а потом
    берёт свои из config.json — и они застряли на обоях 28.09 (07.10.2026). Поэтому
    те же значения пишутся и туда; правка цветов руками в Millennium до смены обоев.
    """
    with open(MCONF) as f:
        conf = json.load(f)
    want = {k: "%d, %d, %d" % c for k, c in colors(p).items()}
    tc = conf.setdefault("themes", {}).setdefault("themeColors", {})
    if tc.get("SpaceTheme") == want:
        return False
    tc["SpaceTheme"] = want
    return write(MCONF, json.dumps(conf, ensure_ascii=False, indent=2) + "\n")


def colors(p):
    vivid = rgb(p["vivid"])
    v = {
        "--st-accent-1": vivid,
        "--st-accent-2": retone(p["vivid"], (135, 140, 255)),
        "--st-color-1": rgb(p["surface"]),
        "--st-color-2": rgb(p["surface_high"]),
        "--st-color-3": rgb(p["surface_low"]),
        "--st-color-4": rgb(p["surface_container"]),
        "--st-color-5": mix(rgb(p["surface_highest"]), rgb(p["on_surface"]), 0.04),
        "--st-color-6": rgb(p["surface_highest"]),
        "--st-background": rgb(p["surface_lowest"]),
        "--st-red": retone(p["error"], (240, 74, 74)),
        "--st-red-hover": retone(p["error"], (242, 99, 99)),
        "--st-green": retone(p["vivid"], (36, 166, 90)),
        "--st-green-hover": retone(p["vivid"], (39, 185, 100)),
        "--st-blue": retone(p["secondary"], (75, 137, 239)),
        "--st-blue-hover": retone(p["secondary"], (100, 154, 242)),
        "--st-yellow": retone(p["tertiary"], (239, 141, 75)),
        "--st-yellow-hover": retone(p["tertiary"], (239, 141, 75)),
    }
    # Формат — как в оригинале: Millennium разбирает root.css для своих настроек цвета.
    return v


def write(path, text):
    try:
        with open(path) as f:
            if f.read() == text:
                return False
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)
    return True


def add_font():
    """Вариант «Jarvis Pixel» в настройке Font; он же по умолчанию."""
    write(os.path.join(THEME, FONT_FILE), FONT_CSS)
    path = os.path.join(THEME, "skin.json")
    with open(path) as f:
        skin = json.load(f)
    font = skin["Conditions"]["Font"]
    want = {"TargetCss": {"affects": [".*"], "src": FONT_FILE}}
    if font["values"].get(FONT_NAME) == want and font.get("default") == FONT_NAME:
        return False
    font["values"][FONT_NAME] = want
    font["default"] = FONT_NAME
    return write(path, json.dumps(skin, ensure_ascii=False, indent=4) + "\n")


def set_active(name):
    with open(MCONF) as f:
        conf = json.load(f)
    conf.setdefault("themes", {})["activeTheme"] = name
    write(MCONF, json.dumps(conf, ensure_ascii=False, indent=4) + "\n")


def main():
    cmd = (sys.argv[1:] or ["apply"])[0]
    if not os.path.isdir(THEME):
        print("SpaceTheme не установлена: %s" % THEME)
        return 1
    if cmd == "apply":
        changed = write(os.path.join(THEME, "src/css/root.css"), root_css(palette()))
        changed = add_font() or changed
        changed = save_colors(palette()) or changed
        print("SpaceTheme: %s" % ("обновлена (Steam подхватит после перезапуска)" if changed else "без изменений"))
        return 0
    if cmd in ("on", "off"):
        set_active("SpaceTheme" if cmd == "on" else "JarvisPixel")
        print("тема Steam: %s — перезапустите Steam" % ("SpaceTheme" if cmd == "on" else "JarvisPixel"))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
