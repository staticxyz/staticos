#!/usr/bin/env python3
"""Вид системы: пиксельный или обычный — один переключатель на всё (13.10.2026).

    pixel_look.py get            pixel | normal | minimal | mixed
    pixel_look.py set pixel|normal|minimal
    pixel_look.py check          по строке на часть: имя, сейчас, нужно; rc 1 — не всё встало

Просьба: «переключатель должен менять все, а то в прошлый раз где то осталось где то не
поменялось». Поэтому части перечислены в PARTS одним списком, и set после применения
сам проверяет каждую (check). «Обычный» — не прибитые значения: при переходе в пиксельный
текущие запоминаются в state/pixel-look.json и при возврате ставятся обратно.

Части: шрифт системы, Obsidian, Zen, «Пуск», значки, кнопка «Пуск», подсказка раскладки,
микшеры, rofi, уведомления (notif_style.py), Discord (discord_pixel.py), шрифт mpv, курсор.
Сбой одной части не прерывает остальные — check в конце назовёт её. Новая программа со своим
шрифтом/видом = новая строка в PARTS, иначе переключатель её «забудет».

Не меняются (сказать, если спросят): kitty (PxPlus в обоих видах), обои (wallpaper_pixel), Telegram
(шрифт выбирается в его настройках чатов), заставка (рисунок PxPlus), Spotify/spicetify (не
установлен; тема Jarvis держит PxPlus). Discord, Steam и mpv подхватят шрифт после перезапуска. pixel_mode.py держится выключенным: его
подмена поверх шрифта системы дала бы двойную замену.

Minimalistic (13.10.2026, Просьба: «верхний бар — маленькая парящая капсула: столы, время,
Wi-Fi, батарея; углы окон скруглены, слева и справа отступ; остальное как в Гладком»):
части — как в normal, плюс капсула бара (waybar_niri.py читает mode из pixel-look.json),
отступ от краёв MINI_EDGE и скругление MINI_RADIUS через niri_compositor.py/window_rounding.py
(прежние значения — в before_minimal, ставятся обратно при выходе) и cfg/look.kdl без
размытия под прозрачным баром. Потребители проверяют mode == "pixel", для них minimal — обычный.
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.expanduser("~/.config/hypr/state/pixel-look.json")
OSD = os.path.expanduser("~/.config/hypr/state/layout-osd-look")
KEEP = os.path.expanduser("~/.config/fontconfig/conf.d/62-pxplus-keep.conf")
PIXEL_MODE_CONF = os.path.expanduser("~/.config/fontconfig/conf.d/65-pixel-mode.conf")
PX = "PxPlus HP 100LX 6x8 Jarvis"
NORMAL_FONT = "JetBrainsMono Nerd Font"


def py(script, *args, timeout=90):
    r = subprocess.run(["python3", os.path.join(HERE, script), *args], capture_output=True,
                       text=True, timeout=timeout, env=dict(os.environ, FONTSWAP_KEEP_SETTINGS="1"))
    return r.stdout.strip()


def read(path, default=""):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return default


def read_bytes(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def write_atomic(path, txt):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(txt)
    os.replace(tmp, path)


def keep_get():
    m = re.search(r'mode="prepend"[^>]*><string>([^<]+)</string>', read(KEEP))
    return m.group(1) if m else ""


def keep_set(fam):
    txt = read(KEEP)
    if txt:
        write_atomic(KEEP, re.sub(r'(mode="prepend"[^>]*><string>)[^<]+(</string>)',
                                  lambda m: m.group(1) + fam + m.group(2), txt, count=1) + "\n")


def osd_set(v):
    write_atomic(OSD, v + "\n")


# Микшеры eww — боковой и громкость приложения (13.10.2026, Просьба: «тоже ещё не пиксельный»).
# Пиксельные правила — в eww/mixer-pixel.scss; eww.scss последней строкой подключает
# mixer-look.scss, который собирает mixer_style.py (пусто / основа + стиль системы).
MIXER_LOOK = os.path.expanduser("~/.config/eww/mixer-look.scss")


def mixer_get():
    return py("mixer_style.py", "get") or "normal"


def mixer_set(v):
    # стиль системы (Default/Skeet/Beta) и цвета обоев подставляет mixer_style.py
    py("mixer_style.py", "set", v)


# mpv: шрифт подписей поверх видео и панели управления прописан в его конфигах (13.10.2026,
# Просьба: «переключить абсолютно весь стиль… ничего не должно забыться»).
MPV_FILES = ((os.path.expanduser("~/.config/mpv/mpv.conf"), r"^(osd-font=')([^']*)(')"),
             (os.path.expanduser("~/.config/mpv/script-opts/osc.conf"), r"^(font=)(.*)()$"))


def mpv_get():
    m = re.search(MPV_FILES[0][1], read(MPV_FILES[0][0]), flags=re.M)
    return m.group(2) if m else ""


def mpv_set(fam):
    for path, rx in MPV_FILES:
        txt = read(path)
        if txt:
            write_atomic(path, re.sub(rx, lambda m: m.group(1) + fam + m.group(3), txt,
                                      count=1, flags=re.M) + "\n")


def discord_get():
    return "on" if py("discord_pixel.py", "status").startswith("вкл") else "off"


# имя: (как прочесть, как поставить, значение в пиксельном виде, в обычном по умолчанию)
PARTS = [
    ("Шрифт системы", lambda: py("app_fonts.py", "get", "system"),
     lambda v: py("app_fonts.py", "set", "system", v), PX, NORMAL_FONT),
    ("Шрифт Obsidian", lambda: py("app_fonts.py", "get", "obsidian"),
     lambda v: py("app_fonts.py", "set", "obsidian", v), PX, NORMAL_FONT),
    ("Шрифт Zen", lambda: py("app_fonts.py", "get", "zen"),
     lambda v: py("app_fonts.py", "set", "zen", v), PX, NORMAL_FONT),
    ("«Пуск» нижней панели", keep_get, keep_set, PX, NORMAL_FONT),
    ("Значки", lambda: py("icon_theme.py", "get"),
     lambda v: py("icon_theme.py", "set", v, timeout=180), "pixel-all", "papirus"),
    ("Кнопка «Пуск» в баре", lambda: py("start_button.py", "get"),
     lambda v: py("start_button.py", "set", v), "pixel", "nerd"),
    ("Подсказка раскладки", lambda: read(OSD, "normal") or "normal", osd_set, "pixel", "normal"),
    ("Микшеры", mixer_get, mixer_set, "pixel", "normal"),
    ("Меню rofi", lambda: py("rofi_style.py", "get") or "normal",       # 13.10.2026: все меню rofi
     lambda v: py("rofi_style.py", "set", v), "pixel", "normal"),
    ("Уведомления", lambda: py("notif_style.py", "get") or "normal",   # 13.10.2026 П9: swaync
     lambda v: py("notif_style.py", "set", v), "pixel", "normal"),
    # 13.10.2026, Просьба: «пусть курсор тоже меняется». Jarvis — пиксельный MSTCRSR в цветах
    # обоев; в обычном по умолчанию гладкая «Галька» тоже в цветах обоев.
    # Discord: тема Vencord pixel.css — пиксельный шрифт и прямые углы в стиле системы;
    # в обычном виде снимается целиком (discord_pixel.py off). Шрифт Discord видит после перезапуска.
    ("Discord", discord_get, lambda v: py("discord_pixel.py", v), "on", "off"),
    ("Шрифт mpv", mpv_get, mpv_set, PX, NORMAL_FONT),
    # С 13.10.2026 (позже) в пиксельном виде — «Стрелка» (tri_cursor.py): пользователь выбрал её
    # и попросил «сделай более пиксельным, чтобы заметно было».
    ("Курсор", lambda: py("cursor_theme.py"), lambda v: py("cursor_theme.py", "set", v, timeout=180),
     "tri-wall", "pebble-wall"),
]


# Бар в пиксельном виде (13.10.2026). Перепробованы: PxPlus 8 px без сглаживания («как будто
# смотрю в 144p»), 12 px без сглаживания (буквы рвутся) и со сглаживанием («не читаемо»),
# CozetteVector 13 px («тоже не читаем»), PxPlus 16 px. Итог пользователя: «шрифт в баре должен
# быть такой же, как в терминале» — kitty рисует PxPlus 13 px (9.75 pt) системным
# сглаживанием (grayscale, hintslight), без жирного. Так и здесь: 13 px, без своих правил
# fontconfig (64-pxplus-crisp.conf удаляется), жирный выключен — синтетический мажет.
# Знак ~10 px, поэтому название трека в пиксельном виде короче (mpris_status.PIXEL_MAX_LEN).
BAR_CSS = os.path.expanduser("~/.config/waybar/looks/pixel-font.css")
CRISP_CONF = os.path.expanduser("~/.config/fontconfig/conf.d/64-pxplus-crisp.conf")
BAR_FONT = PX
BAR_TEXT = ("#custom-clock", "#cpu", "#memory", "#temperature", "#network", "#bluetooth",
            "#language", "#custom-language", "#pulseaudio", "#custom-volume", "#custom-battery", "#custom-pomo",
            "#custom-mpris", "#custom-window-title", "#custom-privacy", "#custom-rec",
            "#custom-taskbar", "#mpris", "#window", "#clock")
CRISP_XML = """<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd">
<!-- pixel_look.py: PxPlus в waybar без сглаживания — на 16 px (×2) пиксель в пиксель
     (13.10.2026). Только waybar. -->
<fontconfig>
  <match target="font">
    <test name="prgname" compare="eq"><string>waybar</string></test>
    <test name="family" compare="contains"><string>PxPlus</string></test>
    <edit name="antialias" mode="assign"><bool>false</bool></edit>
    <edit name="hintstyle" mode="assign"><const>hintfull</const></edit>
  </match>
</fontconfig>
"""


def bar_compact():
    try:
        return "compact" in os.readlink(os.path.expanduser("~/.config/waybar/looks/current.css"))
    except OSError:
        return False


def bar_px():
    """Кегль текста бара в пиксельном виде — как у текста Настроек (Skeet, 12 px)."""
    return 12


def bar_css(mode=None):
    """looks/pixel-font.css: в обычном виде пустой. Зовётся из set и из bar_style.py."""
    mode = mode or load().get("mode", "normal")
    if mode != "pixel":
        write_atomic(BAR_CSS, "/* pixel_look.py: обычный вид — ничего */\n")
        return
    # 13.10.2026, Просьба: «примени такой же масштаб и шрифт в waybar, как в Настройках» —
    # там (вид Skeet) PxPlus 12 px, normal, обычное сглаживание. Кегль — bar_px().
    sel = ",\n".join("window#waybar " + s for s in BAR_TEXT)
    write_atomic(BAR_CSS, (
        "/* pixel_look.py: пиксельный вид — %s %d px, как в Настройках. Не править:\n"
        "   пересобирается при смене вида бара (bar_style.py). */\n"
        "window#waybar *, tooltip label:not(#pixel-look) { font-weight: normal; }\n"
        "%s,\ntooltip label:not(#pixel-look) { font-family: \"%s\"; font-size: %dpx; "
        "font-weight: normal; }\n"
    ) % (BAR_FONT, bar_px(), sel, BAR_FONT, bar_px()))


def crisp_conf(mode):
    # с 13.10.2026 бар рисуется как терминал — своё правило не нужно ни в одном виде
    mode = "normal"
    if mode == "pixel":
        os.makedirs(os.path.dirname(CRISP_CONF), exist_ok=True)
        write_atomic(CRISP_CONF, CRISP_XML)
    else:
        try:
            os.remove(CRISP_CONF)
        except FileNotFoundError:
            pass


NIRI_LOOK = os.path.expanduser("~/.config/niri/cfg/look.kdl")
MINI_EDGE, MINI_RADIUS = 20, 22       # по образцу пользователя (13.10, Image #17): скругление ~22
LOOK_OFF = "// pixel_look.py: вид не Minimalistic — ничего\n"
LOOK_MINI = """// pixel_look.py: вид Minimalistic — бар прозрачный, видна только капсула, размытие под ним
// дало бы мутную полосу во всю ширину. Не править: пишется при смене вида.
layer-rule {
    match namespace=r#"^waybar$"#
    background-effect {
        blur false
    }
}
// Рамка окон — тонкая и нейтральная, без акцента (как в образце). Перекрывает matugen:
// этот файл подключён после layout.kdl.
layout {
    border {
        on
        width 3
        active-color "#ffffffb3"
        inactive-color "#ffffff66"
    }
}
"""


def look_kdl(mode):
    want = LOOK_MINI if mode == "minimal" else LOOK_OFF
    if read(NIRI_LOOK) != want.strip():
        write_atomic(NIRI_LOOK, want)
        subprocess.run(["niri", "msg", "action", "load-config-file"], capture_output=True)


def win_get():
    try:
        edge = json.loads(subprocess.run(["python3", os.path.join(HERE, "niri_compositor.py"), "get"],
                                         capture_output=True, text=True).stdout)["edge"]
    except (ValueError, KeyError):
        edge = None
    r = subprocess.run(["python3", os.path.join(HERE, "window_rounding.py"), "get"],
                       capture_output=True, text=True).stdout.strip()
    return {"edge": edge, "rounding": int(r) if r.isdigit() else None}


def win_set(edge, rounding):
    if edge is not None:
        py("niri_compositor.py", "set", "edge", str(edge))
    if rounding is not None:
        py("window_rounding.py", "set", str(rounding))


def minimal_windows(st, mode):
    """Отступы и скругление окон: в minimal — свои, при выходе — те, что были до него."""
    if mode == "minimal":
        if "before_minimal" not in st:
            st["before_minimal"] = win_get()
        win_set(MINI_EDGE, MINI_RADIUS)
    elif "before_minimal" in st:
        b = st.pop("before_minimal")
        win_set(b.get("edge"), b.get("rounding"))


def minimal_check():
    """Строки check() для Minimalistic: (имя, сейчас, нужно)."""
    bar = read(os.path.expanduser("~/.config/waybar/config-niri.jsonc"))
    w = win_get()
    return [("Бар-капсула", "да" if "niri/workspaces#mini" in bar else "нет", "да"),
            ("Без размытия бара", "да" if read(NIRI_LOOK) == LOOK_MINI.strip() else "нет", "да"),
            ("Отступ от краёв", str(w["edge"]), str(MINI_EDGE)),
            ("Скругление окон", str(w["rounding"]), str(MINI_RADIUS))]


def load():
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    write_atomic(STATE, json.dumps(st, ensure_ascii=False, indent=1) + "\n")


def targets(mode):
    if mode == "pixel":
        return {n: px for n, _g, _s, px, _no in PARTS}
    snap = load().get("normal", {})
    return {n: snap.get(n, no) for n, _g, _s, _px, no in PARTS}


def current():
    out = {}
    for n, g, _s, _px, _no in PARTS:
        try:
            out[n] = g()
        except Exception:                   # noqa: BLE001
            out[n] = "?"
    return out


def mode_of(cur):
    if all(cur[n] == px for n, _g, _s, px, _no in PARTS):
        return "pixel"
    if all(cur[n] != px for n, _g, _s, px, _no in PARTS):
        return "normal"
    return "mixed"


def script_pids(name):
    out = []
    for p in os.listdir("/proc"):
        if p.isdigit() and int(p) != os.getpid():
            try:
                cmd = open("/proc/%s/cmdline" % p, "rb").read().split(b"\0")
            except OSError:
                continue
            if any(a.endswith(name.encode()) for a in cmd[:3]) and b"python3" in cmd[0]:
                out.append(int(p))
    return out


def spawn(*cmd):
    subprocess.Popen(list(cmd), cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, start_new_session=True)


def refresh():
    """Как refresh() в ~/.local/bin/fontswap: всё, что берёт шрифт при старте."""
    subprocess.run(["fc-cache", "-f"], capture_output=True)
    subprocess.run(["python3", os.path.expanduser("~/.config/niri/scripts/waybar_niri.py")],
                   capture_output=True)
    spawn(os.path.expanduser("~/.local/bin/barfix"))
    spawn("python3", os.path.join(HERE, "xpbar.py"), "restart")
    # виджеты: clock.exe решает при старте, растить ли текст пикселями (PIXEL_UI)
    for p in script_pids("desktop_widgets.py"):
        try:
            os.kill(p, 15)
        except OSError:
            pass
    time.sleep(2)
    if not os.path.exists(os.path.expanduser("~/.config/hypr/state/desktop-widgets-off")):
        spawn("python3", os.path.join(HERE, "desktop_widgets.py"))
    pid = read(os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-alttab.pid"))
    if pid.isdigit() and b"alt_tab.py" in read_bytes("/proc/%s/cmdline" % pid):
        os.kill(int(pid), 15)
        time.sleep(0.5)
        spawn("python3", os.path.join(HERE, "alt_tab.py"), "daemon")


def check(mode=None):
    cur = current()
    mode = mode or load().get("mode") or mode_of(cur)
    want = targets(mode)
    bad = 0
    for n, *_ in PARTS:
        ok = cur[n] == want[n]
        bad += not ok
        print("%s\t%s\t%s%s" % (n, cur[n], want[n], "" if ok else "\t← не встало"))
    if mode == "minimal":
        for n, now, need in minimal_check():
            bad += now != need
            print("%s\t%s\t%s%s" % (n, now, need, "" if now == need else "\t← не встало"))
    if os.path.exists(PIXEL_MODE_CONF):
        print("pixel_mode\ton\toff\t← не встало")
        bad += 1
    return 1 if bad else 0


def set_mode(mode):
    st = load()
    cur = current()
    if mode == "pixel" and mode_of(cur) != "pixel":
        # запомнить «обычный» как он есть; часть, уже стоящую пиксельной, — по умолчанию
        st["normal"] = {n: (cur[n] if cur[n] != px else no) for n, _g, _s, px, no in PARTS}
    want = targets(mode)
    if os.path.exists(PIXEL_MODE_CONF):
        py("pixel_mode.py", "set", "off")
    for n, _g, s, _px, _no in PARTS:
        if cur[n] != want[n]:
            # Сбой одной части не должен оставлять остальные в старом виде: идём дальше,
            # а check() ниже покажет, что именно не встало.
            try:
                s(want[n])
            except Exception as e:          # noqa: BLE001 — таймаут, нет программы и т.п.
                print("%s: ошибка — %s" % (n, e), file=sys.stderr)
    minimal_windows(st, mode)
    look_kdl(mode)
    st["mode"] = mode
    save(st)
    crisp_conf(mode)
    bar_css(mode)
    refresh()
    return check(mode)


def main(a):
    if a == ["get"]:
        m = mode_of(current())
        print("minimal" if m == "normal" and load().get("mode") == "minimal" else m)
        return 0
    if a == ["check"]:
        return check()
    if a == ["barcss"]:
        bar_css()
        crisp_conf(load().get("mode", "normal"))
        return 0
    if len(a) == 2 and a[0] == "set" and a[1] in ("pixel", "normal", "minimal"):
        return set_mode(a[1])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
