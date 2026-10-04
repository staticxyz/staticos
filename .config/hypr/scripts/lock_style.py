#!/usr/bin/env python3
"""Стиль экрана блокировки (hyprlock).

    lock_style.py get           текущий стиль (current по умолчанию)
    lock_style.py list          стили: ключ<TAB>название
    lock_style.py set КЛЮЧ      выбрать стиль
    lock_style.py prepare КЛЮЧ  собрать конфиг hyprlock для стиля
                                (зовёт scripts/lockscreen прямо перед блокировкой)
    lock_style.py preview КЛЮЧ  путь к картинке для плитки
    lock_style.py hint ПОРТ СТОРОНА ЯЗЫК
                                подсказка витрины (зовёт сам hyprlock раз в 2 с)

Стили:
    current     — «Как сейчас»: выбран по умолчанию; с 15.09.2026 оформлен как
                  остальные (поля со значками, наши детали, палитра), но свои черты
                  прежние — размытый снимок экрана, аватар, JetBrainsMono. Прежний
                  ~/.config/hypr/hyprlock.conf — страховка в scripts/lockscreen;
    desktop     — «Как рабочий стол»: текущие обои, вид варианта «Астронавт»;
    <вариант>   — статичный вариант темы экрана входа sddm-astronaut и Hyprland
                  (у него фоном неподвижный кадр видео — hyprlock не умеет
                  анимацию). Анимированная сакура не входит.

15.09.2026, по скриншотам пользователя: вид как у темы — шрифт варианта, форма слева
или по центру (FormPosition), поля с иконками темы; наши детали — приветствие,
раскладка, заряд и сеть; цвета — палитра обоев (colors.json), при каждой
блокировке свежие. Шаблон — ~/.config/hypr/hyprlock-astronaut.conf, готовый
конфиг — ~/.cache/lock-style/hyprlock.conf. Светлый фон (средняя яркость выше
LIGHT_BG) приглушается и получает панель под формой. Если в шрифте варианта нет
кириллицы (пиксельные шрифты), дата пишется по-английски, как на скриншотах.

Выбор хранится в ~/.config/hypr/state/lock-style; его читает
scripts/lockscreen — через него идут SUPER+L, блокировка по простою и перед
сном. Плитки — «Настройки» → «Экран» → «Экран блокировки».

Два монитора (16.09.2026, просьба: форма в обоих мониторах — «нелепо»): если
подключён MSI (FORM_MONITOR ищется в описании монитора), форма, раскладка, заряд
и сеть рисуются только на нём, а на остальных мониторах — витрина: крупные часы,
дата и подсказка «Пароль — на мониторе справа →» (сторона — по расположению
мониторов). Если MSI отключат, пока экран заблокирован, hyprlock свой конфиг
не перечитает и форма пропадёт вместе с монитором — поэтому подсказка сама
проверяет монитор и тогда просит ввести пароль вслепую. Монитор один (или MSI
нет) — всё как раньше. LOCK_MONITORS_JSON подменяет вывод `hyprctl monitors -j`
для проверок.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import login_theme  # noqa: E402

STATE = os.path.expanduser("~/.config/hypr/state/lock-style")
TEMPLATE = os.path.expanduser("~/.config/hypr/hyprlock-astronaut.conf")
CACHE = os.path.expanduser("~/.cache/lock-style")
OUT = os.path.join(CACHE, "hyprlock.conf")
FRAMES = os.path.join(CACHE, "frames")
ICONS = os.path.join(CACHE, "icons")
ASSETS = os.path.join(login_theme.THEME, "Assets")
LOCK_VARIANTS = ("astronaut", "black_hole", "hyprland_kath", "japanese_aesthetic",
                 "pixel_sakura_static", "purple_leaves")
LIGHT_BG = 140      # средняя яркость 0..255: сакура 201, японский 212, остальные ≤ 77
FORM_LEFT_X = 130   # отступ формы от левого края для FormPosition=left
FORM_MONITOR = "Microstep MAG 255XF"   # форма блокировки — на этом мониторе, если он есть
AVATAR = os.path.expanduser("~/.cache/avatar.png")   # его кладёт avatar_picker.py
# Фон «Как сейчас» — как в прежнем hyprlock.conf: снимок экрана, сильный блюр,
# затемнение «глубокого синего стекла».
CURRENT_BG = {"BLUR_PASSES": "3", "BLUR_SIZE": "8", "NOISE": "0.0117", "BRIGHT": "0.35",
              "CONTRAST": "1.3", "VIBRANCY": "0.21", "VIBRANCY_DARKNESS": "0.3"}
PICTURE_BG = {"BLUR_PASSES": "0", "BLUR_SIZE": "8", "NOISE": "0", "CONTRAST": "1.0",
              "VIBRANCY": "0.1", "VIBRANCY_DARKNESS": "0"}


def styles():
    items = [("current", "Как сейчас"), ("desktop", login_theme.LABELS["desktop"])]
    visible = dict(login_theme.variants())
    items += [(k, visible[k]) for k in LOCK_VARIANTS if k in visible]
    return items


def get():
    try:
        with open(STATE, encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return "current"
    return v if v in dict(styles()) else "current"


def set_style(key):
    if key not in dict(styles()):
        raise ValueError(key)
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(key + "\n")
    os.replace(tmp, STATE)


def variant_conf(key):
    with open(os.path.join(login_theme.THEME, "Themes", key + ".conf"), encoding="utf-8") as f:
        return dict(re.findall(r'(?m)^(\w+)="?([^"\n]*)"?', f.read()))


def background(key, conf):
    """Полноразмерный фон варианта; у видео и gif — первый кадр (кэшируется)."""
    bg = os.path.join(login_theme.THEME, conf.get("Background", ""))
    ext = os.path.splitext(bg)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return bg
    os.makedirs(FRAMES, exist_ok=True)
    out = os.path.join(FRAMES, key + ".png")
    if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(bg):
        return out
    if ext == ".gif":
        from PIL import Image
        im = Image.open(bg)
        im.seek(0)
        im.convert("RGB").save(out)
    else:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", bg,
                        "-frames:v", "1", out], capture_output=True, timeout=30)
    return out


def brightness_of(path):
    from PIL import Image, ImageStat
    im = Image.open(path)
    im.draft("L", (480, 480))
    im = im.convert("L")
    im.thumbnail((480, 480))
    return ImageStat.Stat(im).mean[0]


def font_family(name):
    """Имя шрифта из конфига темы -> семейство fontconfig (регистр как в системе)."""
    fams = {}
    r = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        for fam in line.split(","):
            fams.setdefault(fam.strip().lower(), fam.strip())
    return fams.get((name or "").strip().lower(), "Open Sans")


def has_cyrillic(family):
    family = re.sub(r"\s+(Bold|ExtraBold|Light|Medium|SemiBold)$", "", family)
    r = subprocess.run(["fc-list", ":family=%s:lang=ru" % family, "family"],
                       capture_output=True, text=True)
    return bool(r.stdout.strip())


def icon(name, color):
    """Иконка темы (SVG) -> PNG цвета акцента: рисунок одноцветный, красим по альфе."""
    from PIL import Image
    os.makedirs(ICONS, exist_ok=True)
    out = os.path.join(ICONS, "%s-%s.png" % (name, color))
    if os.path.isfile(out):
        return out
    raw = os.path.join(ICONS, name + "-raw.png")
    subprocess.run(["rsvg-convert", "-w", "64", "-h", "64", "-o", raw,
                    os.path.join(ASSETS, name + ".svg")], check=True, capture_output=True, timeout=15)
    alpha = Image.open(raw).convert("RGBA").split()[3]
    rgb = tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))
    im = Image.new("RGBA", alpha.size, rgb + (0,))
    im.putalpha(alpha)
    im.save(out)
    return out


def hex6(value):
    return value.lstrip("#").lower()


def monitors():
    """Мониторы в формате hyprctl: [{name, description, x, y, …}].

    Под niri hyprctl нет, поэтому список собирается из `niri msg outputs` и
    приводится к тому же виду — остальному коду всё равно, откуда данные
    (21.09.2026: без этого форма входа выводилась на ОБА монитора, потому что
    placement() получал пустой список и считал, что монитор один)."""
    raw = os.environ.get("LOCK_MONITORS_JSON")
    if raw is not None:
        try:
            return json.loads(raw)
        except ValueError:
            return []
    if os.environ.get("NIRI_SOCKET") and not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        try:
            r = subprocess.run(["niri", "msg", "--json", "outputs"],
                               capture_output=True, text=True, timeout=5)
            out = []
            for name, o in json.loads(r.stdout).items():
                log = o.get("logical") or {}
                out.append({
                    "name": name,
                    # Описание — как у Hyprland: изготовитель, модель, серийный
                    # номер. По нему lock_style ищет MSI (FORM_MONITOR).
                    "description": " ".join(str(o.get(k) or "") for k in ("make", "model", "serial")).strip(),
                    "x": log.get("x", 0), "y": log.get("y", 0),
                    "width": log.get("width", 0), "height": log.get("height", 0),
                })
            return out
        except (OSError, subprocess.SubprocessError, ValueError, AttributeError):
            return []
    try:
        r = subprocess.run(["hyprctl", "monitors", "-j"], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def placement():
    """(порт формы, [(порт витрины, сторона формы от неё)]); монитор один — ("", [])."""
    mons = monitors()
    form = next((m for m in mons if FORM_MONITOR in m.get("description", "")), None)
    if form is None or len(mons) < 2:
        return "", []
    others = []
    for m in mons:
        if m is form:
            continue
        dx = form["x"] - m["x"]
        dy = form["y"] - m["y"]
        if abs(dx) >= abs(dy):
            side = "right" if dx > 0 else "left"
        else:
            side = "below" if dy > 0 else "above"
        others.append((m["name"], side))
    return form["name"], others


HINTS = {
    "ru": {"right": "Пароль — на мониторе справа  󰁔", "left": "󰁍  Пароль — на мониторе слева",
           "above": "󰁝  Пароль — на мониторе выше", "below": "󰁅  Пароль — на мониторе ниже",
           "gone": "Введите пароль и нажмите Enter"},
    "en": {"right": "Password on the right  󰁔", "left": "󰁍  Password on the left",
           "above": "󰁝  Password above", "below": "󰁅  Password below",
           "gone": "Type your password and press Enter"},
}


def hint(port, side, lang):
    """Подсказка витрины: где форма; если монитор формы пропал — ввод вслепую."""
    names = [m.get("name") for m in monitors()]
    texts = HINTS.get(lang, HINTS["en"])
    # 16.09.2026, просьба: «Пароль на мониторе справа» убрать — пока монитор формы
    # на месте, строка пустая; видна только просьба ввести пароль вслепую.
    return "" if port in names else texts["gone"]


def companion(others, lang, light, font, pal):
    """Витрина для мониторов без формы: часы, дата, подсказка."""
    blocks = []
    for port, side in others:
        if light:
            blocks.append("shape {\n    monitor = %s\n    size = 620, 330\n    color = rgba(%sb3)\n"
                          "    rounding = 28\n    border_size = 0\n    position = 0, 20\n"
                          "    halign = center\n    valign = center\n}" % (port, hex6(pal["surface"])))
        blocks.append("""# ВИТРИНА (%(port)s): часы, дата, подсказка — форма на другом мониторе
label {
    monitor = %(port)s
    text = cmd[update:1000] echo "$(date +"%%H:%%M")"
    color = rgb(%(primary)s)
    font_size = 150
    font_family = %(font)s
    position = 0, 80
    halign = center
    valign = center
    shadow_passes = 1
    shadow_size = 3
}
label {
    monitor = %(port)s
    text = cmd[update:60000] %(date_cmd)s
    color = rgb(%(on_surface)s)
    font_size = 26
    font_family = %(font)s
    position = 0, -40
    halign = center
    valign = center
    shadow_passes = 1
}
label {
    monitor = %(port)s
    text = cmd[update:2000] python3 %(script)s hint %(form)s %(side)s %(lang)s
    color = rgb(%(secondary)s)
    font_size = 15
    font_family = JetBrainsMono Nerd Font Bold
    position = 0, -115
    halign = center
    valign = center
    shadow_passes = 1
}""" % {"port": port, "side": side, "lang": lang, "font": font,
       "form": "@@MON_FORM@@", "script": os.path.abspath(__file__),
       "date_cmd": ('echo "$(date +"%A, %-d %B")"' if lang == "ru"
                    else 'echo "$(LC_ALL=C date +"%A %-d")"'),
       "primary": hex6(pal["primary"]), "secondary": hex6(pal["secondary"]),
       "on_surface": hex6(pal["on_surface"])})
    return "\n".join(blocks)


def prepare(key):
    if key not in dict(styles()):
        raise ValueError(key)
    with open(login_theme.PALETTE, encoding="utf-8") as f:
        pal = json.load(f)
    if key == "current":
        conf = {"FormPosition": "center"}
        bg = "screenshot"
        fam = "JetBrainsMono Nerd Font Bold"
        light = False   # снимок затемнён до 0.35 — всегда тёмный
    else:
        if key == "desktop":
            conf = variant_conf("astronaut")
            with open(login_theme.WALLPAPER_STATE, encoding="utf-8") as f:
                bg = f.read().strip()
        else:
            conf = variant_conf(key)
            bg = background(key, conf)
        if not os.path.isfile(bg):
            raise FileNotFoundError(bg)
        light = brightness_of(bg) > LIGHT_BG
        fam = font_family(conf.get("Font"))
    left = conf.get("FormPosition", "center").strip().lower() == "left"
    primary = hex6(pal["primary"])

    if left:
        x = {"HALIGN": "left", "X_CLOCK": FORM_LEFT_X, "X_DATE": FORM_LEFT_X + 4,
             "X_FIELD": FORM_LEFT_X, "X_ICON": FORM_LEFT_X + 16, "X_TEXT": FORM_LEFT_X + 44,
             "X_LAYOUT": FORM_LEFT_X + 4}
        panel_pos = "%d, 60" % (FORM_LEFT_X - 40)
    else:
        x = {"HALIGN": "center", "X_CLOCK": 0, "X_DATE": 0, "X_FIELD": 0, "X_ICON": -136,
             "X_TEXT": 0, "X_LAYOUT": 0}
        panel_pos = "0, 60"
    panel = ""
    if light:
        panel = ("shape {\n    monitor = @@MON_FORM@@\n    size = 440, 480\n    color = rgba(%sb3)\n"
                 "    rounding = 28\n    border_size = 0\n    position = %s\n"
                 "    halign = %s\n    valign = center\n}"
                 % (hex6(pal["surface"]), panel_pos, x["HALIGN"]))
    cyr = has_cyrillic(fam)
    date_cmd = ('echo "$(date +"%A, %-d %B")"' if cyr
                else 'echo "$(LC_ALL=C date +"%A %-d")"')
    form_port, others = placement()

    # Аватар «Как сейчас» — на прежнем месте, как в hyprlock.conf: 130 px точно
    # по центру экрана (15.09.2026, просьба: «верни в прежнее место»). Форма у
    # этого стиля поэтому ниже аватара; у остальных стилей аватара нет.
    avatar = ""
    ys = {"Y_USER": "10", "Y_PASS": "-45", "Y_LAYOUT": "-100"}
    if key == "current" and os.path.isfile(AVATAR):
        avatar = ("image {\n    monitor = @@MON_FORM@@\n    path = %s\n    size = 130\n    rounding = -1\n"
                  "    border_size = 3\n    border_color = rgb(%s)\n    position = 0, 0\n"
                  "    halign = center\n    valign = center\n}" % (AVATAR, primary))
        ys = {"Y_USER": "-100", "Y_PASS": "-155", "Y_LAYOUT": "-210"}
    values = dict(CURRENT_BG if key == "current" else
                  dict(PICTURE_BG, BRIGHT="0.55" if light else "1.0"))
    values.update({
        "BG": bg, "PANEL": panel, "FONT": fam, "AVATAR": avatar, **ys,
        "COMPANION": companion(others, "ru" if cyr else "en", light, fam, pal),
        "DATE_CMD": date_cmd,
        "SURFACE": hex6(pal["surface"]), "PRIMARY": primary,
        "SECONDARY": hex6(pal["secondary"]), "TERTIARY": hex6(pal["tertiary"]),
        "ERROR": hex6(pal["error"]), "ON_SURFACE": hex6(pal["on_surface"]),
        "ON_SURFACE_VARIANT": hex6(pal["on_surface_variant"]),
        "FIELD": hex6(pal["surface_container"]) + "b3",
        "ICON_USER": icon("User", primary), "ICON_PASSWORD": icon("Password2", primary),
    })
    values.update({k: str(v) for k, v in x.items()})
    with open(TEMPLATE, encoding="utf-8") as f:
        text = f.read()
    for k, v in values.items():
        text = text.replace("@@%s@@" % k, v)
    text = text.replace("@@MON_FORM@@", form_port)
    left_over = sorted(set(re.findall(r"@@([A-Z_]+)@@", text)))
    if left_over:
        raise ValueError("не подставлены метки: " + ", ".join(left_over))
    os.makedirs(CACHE, exist_ok=True)
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("# Сгенерировано scripts/lock_style.py prepare %s — не править.\n" % key + text)
    os.replace(tmp, OUT)
    return {"light": light, "left": left, "font": fam, "bg": bg,
            "form": form_port, "others": others}


def preview(key):  # «Как сейчас» — схема в Настройках, картинки нет
    if key == "current":
        return ""
    return login_theme.preview(key)


def main():
    args = sys.argv[1:] or ["get"]
    try:
        if args == ["get"]:
            print(get())
        elif args == ["list"]:
            for k, t in styles():
                print("%s\t%s" % (k, t))
        elif len(args) == 2 and args[0] == "set":
            set_style(args[1])
            print("стиль блокировки: " + args[1])
        elif len(args) == 2 and args[0] == "prepare":
            info = prepare(args[1])
            print("собран %s: шрифт %s, форма %s, фон %s%s" % (
                args[1], info["font"], "слева" if info["left"] else "по центру",
                os.path.basename(info["bg"]), ", светлый — приглушён, с панелью" if info["light"] else ""))
            if info["form"]:
                print("форма на %s, витрина на %s" % (info["form"], ", ".join(
                    "%s (форма: %s)" % o for o in info["others"])))
        elif len(args) == 4 and args[0] == "hint":
            print(hint(*args[1:]))
        elif len(args) == 2 and args[0] == "preview":
            print(preview(args[1]))
        else:
            print(__doc__, file=sys.stderr)
            return 1
    except (ValueError, OSError, KeyError, subprocess.SubprocessError) as e:
        print("lock_style: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
