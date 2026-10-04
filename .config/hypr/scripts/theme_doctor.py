#!/usr/bin/env python3
"""Проверка всей цветовой цепочки: где палитра обоев и где она застряла.

ЗАЧЕМ ЭТО ЕСТЬ. Каждая поломка в этом пайплайне была тихой. Правило waybar
искало класс окна ZapZap, приложение переименовалось в com.rtosta.zapzap —
иконка молча стала кружком. Строка `touch gtk.css` не делала ничего — окна
GTK3 молча оставались в старых цветах. Имя theme_header_background_breeze
никто не определял — полоса меню молча держала цвет прежних обоев. Ни одна
из них не давала ошибки: всё «работало», просто цвет был не тот.

Поэтому скрипт не чинит, а ДОКАЗЫВАЕТ: сравнивает то, что должно было
доехать, с тем, что реально лежит в файлах и висит в окнах. Запускается сам
в конце theme_changer.sh, и его же можно позвать руками:

    python3 ~/.config/hypr/scripts/theme_doctor.py          # таблица
    python3 ~/.config/hypr/scripts/theme_doctor.py --quiet   # только проблемы

Код возврата 1, если хоть одна проверка провалилась.
"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import wm  # noqa: E402
import time

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".cache/matugen")
SCRIPTS = os.path.join(HOME, ".config/hypr/scripts")
MATUGEN_CONF = os.path.join(HOME, ".config/matugen/config.toml")

# Опорные часы всей цепочки: matugen пишет colors.json первым делом, значит
# всё, что заметно старше него, на последней смене обоев не пересобралось.
CLOCK = os.path.join(CACHE, "colors.json")
STALE_S = 120

results = []          # (уровень, раздел, текст)
OK, WARN, BAD = "ок", "!!", "СЛОМАНО"


def add(level, section, text):
    results.append((level, section, text))


def mtime(path):
    try:
        return os.path.getmtime(path)
    except OSError:
        return None


def read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return None


def palette():
    txt = read(CLOCK)
    if txt is None:
        return {}
    try:
        return json.loads(txt)
    except ValueError:
        return {}


def expand(p):
    return os.path.expanduser(p.strip().strip('"').strip("'"))


# ------------------------------------------------------------ 1. генерация --
def check_generation(clock_t):
    wall_state = os.path.join(CACHE, "wallpaper")
    wall = (read(wall_state) or "").strip()
    if not wall:
        add(BAD, "обои", "не записан текущий файл обоев (%s)" % wall_state)
    elif not os.path.isfile(wall):
        add(BAD, "обои", "файл обоев не существует: %s" % wall)
    else:
        add(OK, "обои", os.path.basename(wall))

    conf = read(MATUGEN_CONF)
    if conf is None:
        add(BAD, "matugen", "нет config.toml")
        return
    outs = [expand(m) for m in re.findall(r"^output_path\s*=\s*(.+)$", conf, re.M)]
    missing, stale = [], []
    for o in outs:
        t = mtime(o)
        if t is None:
            missing.append(o)
        elif clock_t and clock_t - t > STALE_S:
            stale.append("%s (на %d мин старше палитры)"
                         % (os.path.basename(o), (clock_t - t) / 60))
    if missing:
        add(BAD, "matugen", "не создались: " + ", ".join(missing))
    if stale:
        add(BAD, "matugen", "не пересобрались: " + "; ".join(stale))
    if not missing and not stale:
        add(OK, "matugen", "все %d выходных файла свежие" % len(outs))


def check_scripts():
    changer = read(os.path.join(SCRIPTS, "theme_changer.sh"))
    if changer is None:
        add(BAD, "скрипты", "нет theme_changer.sh")
        return
    names = sorted(set(re.findall(r"scripts/([a-z_]+\.(?:py|sh))", changer)))
    broken = []
    for n in names:
        p = os.path.join(SCRIPTS, n)
        if not os.path.isfile(p):
            broken.append(n + ": нет файла")
            continue
        if n.endswith(".py"):
            r = subprocess.run([sys.executable, "-m", "py_compile", p],
                               capture_output=True)
        else:
            r = subprocess.run(["bash", "-n", p], capture_output=True)
        if r.returncode != 0:
            broken.append(n + ": не компилируется")
    if broken:
        add(BAD, "скрипты", "; ".join(broken))
    else:
        add(OK, "скрипты", "%d вызываемых скриптов на месте и разбираются" % len(names))


# ---------------------------------------------------------------- 2. GTK3 --
BRIDGE_NAMES = [
    "theme_header_background_breeze",
    "theme_header_foreground_breeze",
    "theme_header_background_backdrop_breeze",
]


def check_gtk():
    ini = read(os.path.join(HOME, ".config/gtk-3.0/settings.ini")) or ""
    if "colorreload-gtk-module" not in ini:
        add(BAD, "gtk3",
            "colorreload-gtk-module не прописан в gtk-modules — живые окна "
            "перекрашиваться перестанут")
    colors = read(os.path.join(HOME, ".config/gtk-3.0/colors.css"))
    if colors is None:
        add(BAD, "gtk3", "нет colors.css")
        return
    if "gtk_live_colors.py" not in colors:
        add(BAD, "gtk3", "colors.css собран не нашим скриптом — мостик имён потерян")
    defined = set(re.findall(r"@define-color\s+([A-Za-z0-9_]+)", colors))
    lost = [n for n in BRIDGE_NAMES if n not in defined]
    if lost:
        add(BAD, "gtk3", "не определены имена Breeze: " + ", ".join(lost))

    # Ссылки @имя должны вести на что-то определённое в этом же файле:
    # неразрешённая ссылка не даёт ошибки, элемент просто остаётся без цвета.
    refs = set(re.findall(r"@define-color\s+[A-Za-z0-9_]+\s+@([A-Za-z0-9_]+)\s*;", colors))
    dangling = sorted(refs - defined)
    if dangling:
        add(BAD, "gtk3", "ссылки в никуда: " + ", ".join(dangling))

    surface = palette().get("surface")
    if surface:
        # Именно этим именем Breeze красит строку меню.
        chain, name, seen = None, "theme_header_background_breeze", set()
        while name and name not in seen:
            seen.add(name)
            # ПОСЛЕДНЕЕ определение, а не первое: файл слоёный, и то же имя
            # объявлено сначала в дампе Breeze со старым цветом, а потом в
            # палитре или мостике — в CSS побеждает нижнее.
            found = re.findall(r"@define-color\s+%s\s+(@?[A-Za-z0-9_#]+)\s*;" % name,
                               colors)
            if not found:
                break
            val = found[-1]
            if val.startswith("@"):
                name = val[1:]
            else:
                chain = val
                break
        if chain and chain.lower() != surface.lower():
            add(WARN, "gtk3", "полоса меню -> %s, а surface обоев %s" % (chain, surface))
        elif chain:
            add(OK, "gtk3", "полоса меню -> %s, мостик и модуль на месте" % chain)
    if not lost and not dangling and surface is None:
        add(OK, "gtk3", "мостик имён на месте")


# ----------------------------------------------------------------- 3. cava --
def check_cava():
    cfg = read(os.path.join(HOME, ".config/cava/config"))
    if cfg is None:
        add(WARN, "cava", "нет конфига — пропускаю")
        return
    vivid = (read(os.path.join(CACHE, "vivid.txt")) or "").strip()
    m = re.search(r"^\s*foreground\s*=\s*(.+)$", cfg, re.M)
    if not m:
        add(BAD, "cava", "нет ключа foreground")
        return
    val = m.group(1).strip()
    if not (val.startswith("'") and val.endswith("'")):
        # Проверено в псевдотерминале: без кавычек cava молча игнорирует hex.
        add(BAD, "cava", "foreground без кавычек (%s) — цвет молча не применится" % val)
    elif val.strip("'").lower() != vivid.lower():
        add(BAD, "cava", "foreground %s, а акцент обоев %s" % (val, vivid))
    elif not re.search(r"^\s*live-config\s*=\s*1", cfg, re.M):
        add(WARN, "cava", "live-config не 1 — запущенный cava не перечитает конфиг")
    else:
        add(OK, "cava", "foreground %s, live-config включён" % val)


# --------------------------------------------------------------- 4. waybar --
def check_waybar():
    src = read(os.path.join(HOME, ".config/waybar/config.jsonc"))
    if src is None:
        add(BAD, "waybar", "нет config.jsonc")
        return
    out, in_str, esc, i = [], False, False, 0
    while i < len(src):
        c = src[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
        elif c == '"':
            in_str = True
            out.append(c)
            i += 1
        elif src.startswith("//", i):
            while i < len(src) and src[i] != "\n":
                i += 1
        else:
            out.append(c)
            i += 1
    try:
        cfg = json.loads("".join(out))
    except ValueError as e:
        add(BAD, "waybar", "config.jsonc не разбирается: %s" % e)
        return
    ws = cfg.get("hyprland/workspaces", {})
    rules = ws.get("window-rewrite", {})
    default = ws.get("window-rewrite-default", "")

    # Список окон — через wm.py: в сеансе Niri hyprctl не отвечает, и проверка
    # значков молча превращалась в предупреждение (21.09.2026).
    clients = [{"class": w["app"], "initialClass": w["app"], "title": w["title"]}
               for w in wm.windows()]
    if not clients:
        add(WARN, "waybar", "список окон пуст — иконки окон не проверил")
        return

    def prio(k):
        return (2 if "title" in k else 0) + (1 if "class" in k else 0)

    ordered = sorted(rules.items(), key=lambda kv: -prio(kv[0]))
    orphans = set()
    for c in clients:
        value = "class<%s> title<%s>" % (c.get("class", ""), c.get("title", ""))
        for k, _ in ordered:
            try:
                if re.search(k, value, re.IGNORECASE):
                    break
            except re.error:
                add(BAD, "waybar", "правило не компилируется как регулярка: %s" % k)
                return
        else:
            orphans.add(c.get("class", "?"))
    if orphans:
        # Ровно так пропала иконка WhatsApp: приложение сменило класс окна.
        add(WARN, "waybar",
            "без своей иконки (рисуется кружок): " + ", ".join(sorted(orphans)))
    else:
        add(OK, "waybar", "у всех %d окон своя иконка" % len(clients))
    if not default:
        add(WARN, "waybar", "window-rewrite-default пуст")


# ------------------------------------------------------------ 5. librewolf --
def check_librewolf():
    conf = read(MATUGEN_CONF) or ""
    m = re.search(r"output_path\s*=\s*\"([^\"]*librewolf[^\"]*)\"", conf)
    if not m:
        add(WARN, "librewolf", "в matugen нет шаблона браузера — пропускаю")
        return
    target = expand(m.group(1))
    profile = os.path.dirname(os.path.dirname(target))

    root = os.path.dirname(profile)
    active = [d for d in (os.path.join(root, x) for x in os.listdir(root))
              if os.path.isdir(d) and os.path.exists(os.path.join(d, ".parentlock"))]
    if active and os.path.normpath(active[0]) != os.path.normpath(profile):
        # Профиль сменился -> matugen пишет цвета в чужой каталог, и браузер
        # об этом никак не сообщит.
        add(BAD, "librewolf", "matugen пишет в %s, а открыт профиль %s"
            % (os.path.basename(profile), os.path.basename(active[0])))
    else:
        add(OK, "librewolf", "профиль %s" % os.path.basename(profile))

    ext = os.path.join(profile, "extensions", "matugen-theme@local.xpi")
    host = os.path.join(HOME, ".librewolf/native-messaging-hosts/matugen_colors.json")
    if not os.path.exists(ext):
        add(BAD, "librewolf", "нет расширения matugen-theme@local.xpi")
    if not os.path.exists(host):
        add(BAD, "librewolf", "нет манифеста native messaging")
    hostpath = None
    hj = read(host)
    if hj:
        try:
            hostpath = json.loads(hj).get("path")
        except ValueError:
            add(BAD, "librewolf", "манифест native messaging не разбирается")
    if hostpath and not os.path.exists(hostpath):
        add(BAD, "librewolf", "помощник по пути %s отсутствует" % hostpath)

    uc = read(os.path.join(profile, "chrome", "userContent.css")) or ""
    first = uc.split("@-moz-document")[1] if "@-moz-document" in uc else ""
    if "about:newtab" in first:
        add(BAD, "librewolf",
            "userContent.css снова красит about:newtab — она замёрзнет на старой палитре")
    mat = read(target) or ""
    frozen = [ln.strip() for ln in mat.splitlines()
              if ln.strip().startswith("--zproger") and "var(" not in ln]
    if frozen:
        add(BAD, "librewolf", "цвета без var() (замёрзнут до перезапуска): "
            + "; ".join(frozen))


# ------------------------------------------------------------- 6. симлинки --
def check_bin():
    missing = []
    for n in ("tclock", "tdown", "ffetch"):
        p = os.path.join(HOME, ".local/bin", n)
        if not os.path.exists(p):          # os.path.exists идёт по ссылке
            missing.append(n)
    if missing:
        add(BAD, "команды", "не разрешаются: " + ", ".join(missing))
    else:
        add(OK, "команды", "tclock, tdown, ffetch на месте")


# --------------------------------------------------- 7. отставшие процессы --
# Что именно у приложения не обновится, если оно старше текущей палитры.
NEEDS_RESTART = {
    # Qt/KDE: палитру qt6ct приложение читает при запуске. Проверено
    # 21.09.2026 на пробном Qt-окне: подмена файла палитры и касание
    # qt6ct.conf живое окно не перекрашивают. Рассылку KDE о смене настроек
    # не шлём намеренно — от неё Dolphin раздувался до 2 ГБ и его убивал OOM.
    "dolphin": "палитра Qt читается при запуске",
    "ark": "палитра Qt читается при запуске",
    "okular": "палитра Qt читается при запуске",
    "mousepad": "поле текста (схема GtkSourceView читается один раз)",
    "librewolf": "userChrome/userContent (chrome-стили читаются один раз)",
    "telegram-desktop": "тема лежит в tdata, файлы не перечитываются",
    "blanket": "GTK4 без colorreload-модуля",
    "obsidian": "сниппет подхватится, но окно надо переоткрыть",
}


def palette_changed_at():
    """Когда цвета менялись НА САМОМ ДЕЛЕ, а не когда их пересобирали.

    По mtime colors.json судить нельзя: theme_changer переписывает его при
    каждом запуске, в том числе на тех же обоях, и тогда «отставшими» разом
    объявляются все окна, хотя цвет у них верный. Поэтому рядом лежит метка с
    хешом палитры; её время обновляется, только если хеш изменился.
    """
    import hashlib

    body = read(CLOCK)
    if body is None:
        return None
    digest = hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()
    mark = os.path.join(CACHE, "palette-id")

    # В метке лежат хеш и время — не полагаемся на mtime самого файла: его
    # сдвинет любое копирование кеша, и отсчёт молча уедет.
    prev = (read(mark) or "").split()
    if len(prev) == 2 and prev[0] == digest:
        try:
            return float(prev[1])
        except ValueError:
            pass

    # Первое создание метки: взять время сборки colors.json, а не «сейчас».
    # Это оценка (пересборка на тех же обоях тоже двигает colors.json), зато
    # она не объявляет отставшими разом все окна. Со следующей настоящей
    # смены обоев отсчёт становится точным.
    when = mtime(CLOCK) or time.time()
    try:
        with open(mark, "w", encoding="utf-8") as f:
            f.write("%s %.6f\n" % (digest, when))
    except OSError:
        pass
    return when


def check_running(_clock_t):
    clock_t = palette_changed_at()
    if not clock_t:
        return
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid=,etimes=,comm="], text=True)
    except Exception:
        return
    now = time.time()
    late = []
    for line in out.splitlines():
        parts = line.split(None, 2)
        if len(parts) < 3:
            continue
        pid, etimes, comm = parts
        try:
            started = now - int(etimes)
        except ValueError:
            continue
        key = comm.strip().lower()
        for name, why in NEEDS_RESTART.items():
            if name.startswith(key) or key.startswith(name[:12]):
                if started < clock_t:
                    late.append("%s: %s" % (comm.strip(), why))
                break
    if late:
        add(WARN, "окна", "запущены раньше текущей палитры — " + "; ".join(sorted(set(late))))
    else:
        add(OK, "окна", "приложений, отставших от палитры, нет")


def main():
    quiet = "--quiet" in sys.argv
    clock_t = mtime(CLOCK)
    if clock_t is None:
        print("theme_doctor: нет %s — палитра ни разу не собиралась" % CLOCK,
              file=sys.stderr)
        return 1

    for fn in (lambda: check_generation(clock_t), check_scripts, check_gtk,
               check_cava, check_waybar, check_librewolf, check_bin,
               lambda: check_running(clock_t)):
        try:
            fn()
        except Exception as e:                      # noqa: BLE001
            # Упавшая проверка — это тоже находка, а не повод молча выйти.
            add(BAD, getattr(fn, "__name__", "проверка"), "проверка упала: %r" % e)

    bad = [r for r in results if r[0] == BAD]
    warn = [r for r in results if r[0] == WARN]
    shown = results if not quiet else bad + warn

    if shown:
        width = max(len(r[1]) for r in shown)
        for level, section, text in shown:
            mark = {OK: "  ", WARN: "! ", BAD: "X "}[level]
            print("%s%-*s  %s" % (mark, width, section, text))
    if quiet and not shown:
        return 0
    print()
    print("палитра собрана: %s" % time.strftime("%d.%m %H:%M", time.localtime(clock_t)))
    print("итог: %d проблем, %d предупреждений" % (len(bad), len(warn)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
