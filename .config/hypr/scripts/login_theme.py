#!/usr/bin/env python3
"""Экран входа SDDM: темы, варианты sddm-astronaut и переключение.

    login_theme.py status        установлена ли тема astronaut и помощник
    login_theme.py list          пункты выбора: ключ<TAB>название
    login_theme.py current       текущий пункт
    login_theme.py set КЛЮЧ      выбрать пункт
    login_theme.py sync          обновить «Как рабочий стол», если он выбран
    login_theme.py preview КЛЮЧ  путь к картинке-превью (или пусто)
    login_theme.py try [СЕК]     показать выбранный экран входа в тестовом режиме
                                 SDDM поверх рабочего стола (закроется сам, 30 с)

Ключи пунктов:
    desktop          — «Как рабочий стол» (вариант astronaut из обоев и палитры);
    <вариант>        — вариант темы astronaut (astronaut, cyberpunk, …);
    sddm:default     — «Как было»: встроенная тема SDDM, какой экран входа был
                       до установки (в журнале «Loaded empty theme configuration»);
    sddm:<тема>      — другая тема из /usr/share/sddm/themes (breeze, maya, …).

Тему и помощника ставит ~/.config/hypr/scripts/login_theme/install.sh (root),
помощника обновляет update_helper.sh. Переключает помощник
/usr/local/bin/sddm-astronaut-set через `sudo -n`: в sudoers без пароля
разрешён только он (выбор пользователя, 14.09.2026). Текущую тему SDDM скрипт читает
сам из /etc/sddm.conf.d/10-sddm-astronaut.conf — файл открыт на чтение всем.

Варианты astronaut — в цветах палитры обоев (15.09.2026, решение пользователя):
помощник собирает Themes/_pal_<вариант>.conf (фон, шрифт, форма от варианта,
цвета из colors.json, затемнение светлого фона по яркости картинки) и
выбирает его; `sync` пересобирает при смене обоев. Родные файлы темы целы.

«Как рабочий стол»: фон — текущие обои (~/.cache/matugen/wallpaper), подрезанные
под 1920x1080 и сохранённые JPEG в ~/.cache/login-theme/desktop.jpg; цвета —
палитра matugen (colors.json). Помощник сам проверяет и файл, и цвета.
theme_changer.sh зовёт `sync` при смене обоев — вариант обновляется, только если
выбран. Плитки — в «Настройках» → «Экран» → «Экран входа».
"""
import json
import os
import re
import subprocess
import sys

THEMES_DIR = "/usr/share/sddm/themes"
ASTRONAUT = "sddm-astronaut-theme"
THEME = os.path.join(THEMES_DIR, ASTRONAUT)
META = os.path.join(THEME, "metadata.desktop")
CONF = "/etc/sddm.conf.d/10-sddm-astronaut.conf"
HELPER = "/usr/local/bin/sddm-astronaut-set"
CACHE = os.path.expanduser("~/.cache/login-theme")
STAGE = os.path.join(CACHE, "desktop.jpg")
PREVIEWS = os.path.join(CACHE, "previews")
WALLPAPER_STATE = os.path.expanduser("~/.cache/matugen/wallpaper")
WALLPAPER_THUMB = os.path.expanduser("~/.cache/matugen/wallpaper-thumb.png")
PALETTE = os.path.expanduser("~/.cache/matugen/colors.json")
COLOR_KEYS = ("primary", "on_primary", "surface", "surface_container",
              "on_surface", "on_surface_variant")

LABELS = {
    "desktop": "Как рабочий стол",
    "astronaut": "Астронавт",
    "black_hole": "Чёрная дыра",
    "cyberpunk": "Киберпанк",
    "hyprland_kath": "Hyprland",
    "jake_the_dog": "Джейк (видео)",
    "japanese_aesthetic": "Японский",
    "pixel_sakura": "Пиксельная сакура (анимация)",
    "pixel_sakura_static": "Пиксельная сакура",
    "post-apocalyptic_hacker": "Хакер",
    "purple_leaves": "Фиолетовые листья",
    "sddm:default": "Как было",
}

# Скрыты из выбора по решению пользователя (14.09.2026, «не понравились»). Файлы
# тем не удалены: вернуть пункт — убрать ключ отсюда.
HIDDEN = {"sddm:maya", "sddm:maldives", "sddm:elarun", "sddm:default",
          "post-apocalyptic_hacker", "jake_the_dog", "cyberpunk",
          # 15.09.2026: анимированную сакуру убрать, статичная зовётся
          # «Пиксельная сакура».
          "pixel_sakura"}


def installed():
    return os.path.isfile(META) and os.path.isfile(HELPER)


def dm_current():
    """Тема SDDM из нашего файла в /etc/sddm.conf.d ("" — встроенная)."""
    try:
        with open(CONF, encoding="utf-8") as f:
            m = re.search(r"(?m)^Current=(.*)$", f.read())
    except OSError:
        return ""
    return m.group(1).strip() if m else ""


def other_themes():
    names = []
    try:
        for n in sorted(os.listdir(THEMES_DIR)):
            d = os.path.join(THEMES_DIR, n)
            if (n != ASTRONAUT and ".bak-" not in n and not os.path.islink(d)
                    and os.path.isfile(os.path.join(d, "metadata.desktop"))):
                names.append(n)
    except OSError:
        pass
    return names


def variants():
    names = []
    try:
        names = sorted(f[:-5] for f in os.listdir(os.path.join(THEME, "Themes"))
                       if f.endswith(".conf") and f != "desktop.conf"
                       and not f.startswith("_pal_"))
    except OSError:
        pass
    items = [("desktop", LABELS["desktop"])] + [(n, LABELS.get(n, n)) for n in names]
    items.append(("sddm:default", LABELS["sddm:default"]))
    items += [("sddm:" + n, n.capitalize()) for n in other_themes()]
    return [(k, t) for k, t in items if k not in HIDDEN]


def astronaut_variant():
    try:
        with open(META, encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^ConfigFile=Themes/([A-Za-z0-9_-]+)\.conf\s*$", line)
                if m:
                    return m.group(1)
    except OSError:
        pass
    return ""


def current():
    dm = dm_current()
    if dm == ASTRONAUT:
        v = astronaut_variant()
        return v[5:] if v.startswith("_pal_") else v
    return "sddm:" + (dm or "default")


LIGHT_BG = 140   # как в lock_style.py: сакура 201, японский 212, остальные ≤ 77


def dim_for(key):
    """Затемнение фона варианта: светлым — 0.45, иначе палитровый текст не читается."""
    path = preview(key)
    if not path:
        return "0"
    from PIL import Image, ImageStat
    im = Image.open(path)
    im.draft("L", (480, 480))
    im = im.convert("L")
    im.thumbnail((480, 480))
    return "0.45" if ImageStat.Stat(im).mean[0] > LIGHT_BG else "0"


def palette_colors():
    with open(PALETTE, encoding="utf-8") as f:
        pal = json.load(f)
    return [pal[k] for k in COLOR_KEYS]


def recolor(key):
    return helper("recolor", key, dim_for(key), *palette_colors())


def helper(*args):
    r = subprocess.run(["sudo", "-n", HELPER] + list(args),
                       capture_output=True, text=True, timeout=30)
    return r.returncode, (r.stdout + r.stderr).strip()


def build_stage():
    from PIL import Image
    with open(WALLPAPER_STATE, encoding="utf-8") as f:
        src = f.read().strip()
    im = Image.open(src)
    im.draft("RGB", (3840, 2160))
    im = im.convert("RGB")
    tw, th = 1920, 1080
    scale = max(tw / im.width, th / im.height)
    im = im.resize((max(tw, round(im.width * scale)), max(th, round(im.height * scale))),
                   Image.LANCZOS)
    left, top = (im.width - tw) // 2, (im.height - th) // 2
    im = im.crop((left, top, left + tw, top + th))
    os.makedirs(CACHE, exist_ok=True)
    tmp = STAGE + ".tmp"
    im.save(tmp, "JPEG", quality=90)
    os.replace(tmp, STAGE)


def sync_desktop():
    build_stage()
    return helper("desktop", *palette_colors())


def set_variant(key):
    if key.startswith("sddm:"):
        return helper("dm-set", key[5:])
    if key == "desktop":
        return sync_desktop()
    return recolor(key)


def preview(key):
    """Картинка для плитки: превью темы, фон варианта или кадр из анимации/видео."""
    if key == "desktop":
        return WALLPAPER_THUMB if os.path.isfile(WALLPAPER_THUMB) else ""
    if key == "sddm:default":
        return ""   # у встроенной темы SDDM файла-превью нет — плитка без картинки
    if key.startswith("sddm:"):
        d = os.path.join(THEMES_DIR, key[5:])
        try:
            with open(os.path.join(d, "metadata.desktop"), encoding="utf-8") as f:
                m = re.search(r"(?m)^Screenshot=(.+)$", f.read())
        except OSError:
            return ""
        p = os.path.join(d, m.group(1).strip()) if m else ""
        return p if p and os.path.isfile(p) else ""
    shot = os.path.join(THEME, "Previews", key + ".png")
    if os.path.isfile(shot):
        return shot
    conf = os.path.join(THEME, "Themes", key + ".conf")
    try:
        with open(conf, encoding="utf-8") as f:
            m = re.search(r'(?m)^Background="?([^"\n]+)"?', f.read())
    except OSError:
        return ""
    if not m:
        return ""
    bg = os.path.join(THEME, m.group(1))
    ext = os.path.splitext(bg)[1].lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return bg if os.path.isfile(bg) else ""
    os.makedirs(PREVIEWS, exist_ok=True)
    out = os.path.join(PREVIEWS, key + ".png")
    if os.path.isfile(out) and os.path.getmtime(out) >= os.path.getmtime(bg):
        return out
    try:
        if ext == ".gif":
            from PIL import Image
            im = Image.open(bg)
            im.seek(0)
            im.convert("RGB").save(out)
        else:
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "1", "-i", bg,
                            "-frames:v", "1", "-vf", "scale=480:-1", out],
                           capture_output=True, timeout=20)
    except Exception:
        return ""
    return out if os.path.isfile(out) else ""


def try_preview(seconds=30):
    """Тестовый режим SDDM: настоящий экран входа окном, без выхода из сессии.

    Для «Как было» тема не указывается — greeter берёт встроенную. Через
    seconds секунд окно закрывается само (его можно закрыть и раньше).
    """
    key = current()
    args = ["sddm-greeter-qt6", "--test-mode"]
    if key.startswith("sddm:"):
        if key != "sddm:default":
            args += ["--theme", os.path.join(THEMES_DIR, key[5:])]
    else:
        args += ["--theme", THEME]
    p = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    subprocess.Popen(["sh", "-c", "sleep %d; kill %d 2>/dev/null" % (int(seconds), p.pid)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    return p.pid


def main():
    args = sys.argv[1:] or ["status"]
    cmd = args[0]
    if cmd == "status":
        print("установлена" if installed() else "не установлена")
        return 0 if installed() else 1
    if cmd == "list":
        for key, title in variants():
            print("%s\t%s" % (key, title))
        return 0
    if cmd == "current":
        print(current())
        return 0
    if cmd == "set" and len(args) == 2:
        code, out = set_variant(args[1])
        print(out)
        return code
    if cmd == "sync":
        # При смене обоев: «Как рабочий стол» и вариант в цветах палитры
        # пересобираются; Breeze и другие темы SDDM не трогаются.
        if not installed():
            return 0
        key = current()
        if key == "desktop":
            code, out = sync_desktop()
        elif not key.startswith("sddm:") and astronaut_variant().startswith("_pal_"):
            code, out = recolor(key)
        else:
            return 0
        print(out)
        return code
    if cmd == "preview" and len(args) == 2:
        print(preview(args[1]))
        return 0
    if cmd == "try" and len(args) <= 2:
        print("предпросмотр экрана входа, pid %d" % try_preview(args[1] if len(args) == 2 else 30))
        return 0
    print(__doc__, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
