#!/usr/bin/env python3
"""App list — список программ, как «Программы и компоненты» в Windows. 06.10.2026.

Просьба: «полный список приложений, удалять, переустанавливать; версии: посмотреть,
откатиться на прошлую, обновить только одно приложение без sudo pacman -Syu; красиво,
минималистично, в теме системы (default, skeet, beta), с иконками; защита от дурака».
Потом: «добавь туда блок информации о системе, все данные».

Вкладки:
  Apps      программы с ярлыком (.desktop) — значок, версия, размер, пакет-владелец;
  Packages  все пакеты, поставленные явно (a — вместе с зависимостями);
  System    сведения о системе: устройство, процессор, графика, экраны, память, диски,
            батарея, сеть, звук, вид, версии программ (y — скопировать всё текстом).
Справа — карточка выбранного: описание, даты, кто от него зависит, кнопки и «Versions»:
  установленная, новая (checkupdates / yay -Qua — без sudo и без -Sy в системную базу),
  старые из кэша pacman и yay, по A — из Arch Linux Archive; история из pacman.log.

Всё, что требует root, — в отдельном маленьком терминале (com.jarvis.applist.term):
там видно команду и вывод, пароль sudo вводит пользователь, pacman ещё раз спросит [Y/n].
Перед этим — своё «точно?» в окне; системные пакеты (ядро, niri, pacman…) — только
после ввода имени пакета. Команды:
  удалить            sudo pacman -Rs ПАКЕТ        (AUR так же; ярлык ~/.local — в корзину кэша)
  переустановить     sudo pacman -S ПАКЕТ         (AUR: yay -S)
  обновить одно      sudo pacman -Sy --needed ПАКЕТ   — частичное обновление: Arch
                     поддерживает только полное -Syu, окно об этом предупреждает
  откат / версия     sudo pacman -U файл_из_кэша|ссылка_архива
  закрепить          sudo app_list.py --hold add|del ПАКЕТ  — IgnorePkg в /etc/pacman.conf,
                     чтобы -Syu не вернул откаченное

Клавиши — как в nvim пользователя (по keycode, раскладка не важна):
  j/k ↓↑ · gg/G · Ctrl+D/U · H/L, Tab, gt/gT, 1 2 3 — вкладки · / — поиск (Enter, jj, оо,
  Ctrl+E — готово, Esc — сброс) · l, Enter — к версиям, h — назад · o — открыть ·
  u — обновить · r — переустановить · D, dd — удалить · p — закрепить · A — архив ·
  s — сортировка · a — все пакеты · R — проверить обновления · y — копировать · ? · q, Esc

    app_list.py [apps|packages|system]   открыть (второй запуск — закрыть/поднять)
    app_list.py --shot F [tab=… sel=N focus=list|versions confirm=remove style=…]
    app_list.py --hold add|del ПАКЕТ     (из терминала, под sudo)
    app_list.py --info                   сведения о системе текстом
"""
import datetime as dt
import html
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
HOME = os.path.expanduser("~")
DB = "/var/lib/pacman/local"
PKGCACHE = "/var/cache/pacman/pkg"
YAYCACHE = os.path.join(HOME, ".cache/yay")
PACLOG = "/var/log/pacman.log"
PACCONF = "/etc/pacman.conf"
CACHE = os.path.join(HOME, ".cache/applist")
APP_ID = "com.jarvis.applist"
TERM_ID = "com.jarvis.applist.term"
TABS = ("apps", "packages", "cleanup", "system")
TAB_NAMES = {"apps": "Apps", "packages": "Packages", "cleanup": "Cleanup", "system": "System"}

# без этих пакетов не загрузится система или сеанс — удалить только после ввода имени
CRITICAL = re.compile(r"^(linux(-lts|-zen)?(-headers)?|linux-firmware.*|base|base-devel|systemd.*|"
                      r"glibc|gcc-libs|pacman|sudo|filesystem|coreutils|util-linux|bash|zsh|fish|"
                      r"niri|sddm|xwayland-satellite|kitty|waybar|pipewire.*|wireplumber|"
                      r"networkmanager|iwd|wpa_supplicant|mesa|vulkan-.*|nvidia.*|lib32-nvidia.*|"
                      r"grub|efibootmgr|mkinitcpio|intel-ucode|amd-ucode|python|gtk3|gtk4|qt6-base|"
                      r"dbus.*|polkit|xdg-desktop-portal.*|btrfs-progs|e2fsprogs|dosfstools|"
                      r"cryptsetup|lvm2|openssh|yay|matugen)$")


# ── мелочи ────────────────────────────────────────────────────────────────────

def sh(*cmd, timeout=10):
    try:
        return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


def human(n):
    n = float(n or 0)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit)).replace(".0 ", " ")
        n /= 1024
    return ""


def short_date(s):
    """«2026-09-28», «28.09.2026», «06-Oct-2026» → «28.09.26»."""
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d-%b-%Y"):
        try:
            return dt.datetime.strptime(s[:11].strip(), fmt).strftime("%d.%m.%y")
        except ValueError:
            pass
    return s


def day(ts):
    try:
        return time.strftime("%d.%m.%Y", time.localtime(float(ts)))
    except (TypeError, ValueError):
        return ""


_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю"
_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
SWAP = {**dict(zip(_RU, _EN)), **dict(zip(_EN, _RU))}


def other_layout(s):
    return "".join(SWAP.get(ch, ch) for ch in s.lower())


def rpmcmp(a, b):
    """Сравнение версий в духе vercmp (pacman): цифры > буквы, числа как числа."""
    if a == b:
        return 0
    pa, pb = re.findall(r"\d+|[A-Za-z]+", a), re.findall(r"\d+|[A-Za-z]+", b)
    for x, y in zip(pa, pb):
        if x.isdigit() and y.isdigit():
            x, y = int(x), int(y)
        elif x.isdigit():
            return 1
        elif y.isdigit():
            return -1
        if x != y:
            return 1 if x > y else -1
    return (len(pa) > len(pb)) - (len(pa) < len(pb))


def vercmp(a, b):
    def split(v):
        ep, rest = (v.split(":", 1) if ":" in v else ("0", v))
        ver, _, rel = rest.rpartition("-") if "-" in rest else (rest, "", "0")
        return int(ep) if ep.isdigit() else 0, ver, rel
    ea, va, ra = split(a)
    eb, vb, rb = split(b)
    if ea != eb:
        return 1 if ea > eb else -1
    return rpmcmp(va, vb) or rpmcmp(ra, rb)


# ── пакеты ────────────────────────────────────────────────────────────────────

def parse_desc(path):
    out, key = {}, None
    try:
        for line in open(path, errors="replace"):
            line = line.rstrip("\n")
            if line.startswith("%") and line.endswith("%"):
                key = line.strip("%")
                out[key] = []
            elif line and key:
                out[key].append(line)
    except OSError:
        pass
    return out


def dep_name(d):
    return re.split(r"[<>=:]", d, maxsplit=1)[0].strip()


def load_local():
    """Пакеты из базы pacman: {имя: сведения}, и какой пакет владеет каким ярлыком."""
    pkgs, desk = {}, {}
    try:
        dirs = os.listdir(DB)
    except OSError:
        dirs = []
    for d in dirs:
        desc = parse_desc(os.path.join(DB, d, "desc"))
        if "NAME" not in desc:
            continue
        g = lambda k, i=0: (desc.get(k) or [""])[i] if desc.get(k) else ""  # noqa: E731
        name = g("NAME")
        pkgs[name] = {"name": name, "version": g("VERSION"), "desc": g("DESC"), "url": g("URL"),
                      "size": int(g("SIZE") or 0), "installed": int(g("INSTALLDATE") or 0),
                      "built": int(g("BUILDDATE") or 0), "packager": g("PACKAGER"),
                      "explicit": g("REASON") != "1", "depends": [dep_name(x) for x in desc.get("DEPENDS", [])],
                      "provides": [dep_name(x) for x in desc.get("PROVIDES", [])],
                      "license": ", ".join(desc.get("LICENSE", [])), "required": [], "foreign": False,
                      "repo": "", "apps": []}
        try:
            for line in open(os.path.join(DB, d, "files"), errors="ignore"):
                if line.startswith("usr/share/applications/") and line.rstrip().endswith(".desktop"):
                    desk["/" + line.strip()] = name
        except OSError:
            pass
    prov = {}
    for p in pkgs.values():
        for x in p["provides"]:
            prov.setdefault(x, p["name"])
    for p in pkgs.values():
        for dname in set(p["depends"]):
            owner = dname if dname in pkgs else prov.get(dname)
            if owner and owner != p["name"]:
                pkgs[owner]["required"].append(p["name"])
    return pkgs, desk


def foreign_and_repos(pkgs):
    """AUR — то, чего нет в репозиториях (pacman -Qqm); репозиторий — из pacman -Sl."""
    for name in sh("pacman", "-Qqm").split():
        if name in pkgs:
            pkgs[name]["foreign"] = True
            pkgs[name]["repo"] = "AUR"
    for line in sh("pacman", "-Sl", timeout=20).splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in pkgs and not pkgs[parts[1]]["foreign"]:
            pkgs[parts[1]]["repo"] = parts[0]


def cache_files():
    """Старые сборки на диске: {имя: [(версия, путь)]} — из кэша pacman и yay."""
    out = {}
    pat = re.compile(r"^(.+)-([^-]+-[^-]+)-([^-]+)\.pkg\.tar\.(zst|xz|gz)$")
    places = [PKGCACHE] + [os.path.join(YAYCACHE, d) for d in (os.listdir(YAYCACHE) if os.path.isdir(YAYCACHE) else [])]
    for place in places:
        try:
            names = os.listdir(place)
        except OSError:
            continue
        for f in names:
            m = pat.match(f)
            if m:
                out.setdefault(m.group(1), []).append((m.group(2), os.path.join(place, f)))
    return out


LOG_RE = re.compile(r"^\[(\S+)\] \[ALPM\] (installed|upgraded|downgraded|reinstalled|removed) (\S+) \((.+)\)$")


def pacman_history():
    out = {}
    try:
        for line in open(PACLOG, errors="replace"):
            m = LOG_RE.match(line.strip())
            if m:
                out.setdefault(m.group(3), []).append((m.group(1)[:10], m.group(2), m.group(4)))
    except OSError:
        pass
    return out


def holds():
    """IgnorePkg из [options] /etc/pacman.conf (читается без root)."""
    out, sect = set(), ""
    for line in read(PACCONF).splitlines():
        s = line.strip()
        if s.startswith("["):
            sect = s
        elif sect == "[options]" and re.match(r"^IgnorePkg\s*=", s):
            out.update(s.split("=", 1)[1].split())
    return out


def hold_edit(action, pkg):
    """--hold add|del ПАКЕТ под sudo: правка строки IgnorePkg (копия .bak-applist один раз)."""
    if os.geteuid() != 0:
        print("нужен root: sudo %s --hold %s %s" % (sys.argv[0], action, pkg))
        return 1
    if not re.fullmatch(r"[A-Za-z0-9@._+-]+", pkg):
        print("странное имя пакета")
        return 1
    lines = open(PACCONF).read().split("\n")
    if not os.path.exists(PACCONF + ".bak-applist"):
        open(PACCONF + ".bak-applist", "w").write("\n".join(lines))
    sect, at, cur = "", None, []
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("["):
            if sect == "[options]" and at is None:
                at = i            # строки не было — вставим в конец [options]
                break
            sect = s
        elif sect == "[options]" and re.match(r"^#?\s*IgnorePkg\s*=", s):
            at = i
            if not s.startswith("#"):
                cur = s.split("=", 1)[1].split()
            break
    cur = [x for x in cur if x != pkg] + ([pkg] if action == "add" else [])
    new = ("IgnorePkg   = " + " ".join(cur)) if cur else "#IgnorePkg   ="
    if at is None:
        lines.append(new)
    elif lines[at].strip().startswith("[") :
        lines.insert(at, new)
    else:
        lines[at] = new
    open(PACCONF, "w").write("\n".join(lines))
    print("IgnorePkg:", " ".join(cur) or "(пусто)")
    return 0


def check_updates(force=False):
    """{имя: новая версия} — checkupdates (своя копия базы, без root) и yay -Qua (AUR).
    Кэш на 30 минут: сеть не дёргается на каждое открытие окна."""
    f = os.path.join(CACHE, "updates.json")
    try:
        d = json.load(open(f))
        if not force and time.time() - d.get("t", 0) < 1800:
            return d
    except (OSError, ValueError):
        pass
    ups = {}
    for cmd in (["checkupdates", "--nocolor"], ["yay", "-Qua", "--color", "never"]):
        for line in sh(*cmd, timeout=120).splitlines():
            m = re.match(r"^(\S+) (\S+) -> (\S+)", line.strip())
            if m:
                ups[m.group(1)] = m.group(3)
    d = {"t": time.time(), "ups": ups}
    os.makedirs(CACHE, exist_ok=True)
    with open(f + ".tmp", "w") as fh:
        json.dump(d, fh)
    os.replace(f + ".tmp", f)
    return d


def archive_versions(name):
    """Версии из Arch Linux Archive (только репозиторные пакеты): [(версия, ссылка, дата)]."""
    url = "https://archive.archlinux.org/packages/%s/%s/" % (name[0], name)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "applist"})
        page = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
    except Exception as e:
        return "err: %s" % e
    out = {}
    pat = r'href="(%s-([^-"]+-[^-"]+)-(x86_64|any)\.pkg\.tar\.(?:zst|xz))"\s*>[^<]*</a>\s*(\S+)' % re.escape(name)
    for fname, ver, _arch, when in re.findall(pat, page):
        out[ver] = (url + html.unescape(fname), when)
    vers = sorted(out, key=lambda v: __import__("functools").cmp_to_key(vercmp)(v), reverse=True)
    return [(v, out[v][0], out[v][1]) for v in vers[:25]]


# ── программы (ярлыки) ────────────────────────────────────────────────────────

def load_apps(Gio, pkgs, desk):
    apps = []
    local_dir = os.path.join(HOME, ".local/share/applications")
    for a in Gio.AppInfo.get_all():
        try:
            if not a.should_show():
                continue
            fn = a.get_filename() or ""
        except Exception:
            continue
        owner = desk.get(fn)
        if not owner and fn.startswith(local_dir):   # свой ярлык поверх пакетного — владелец тот же
            owner = next((v for k, v in desk.items() if os.path.basename(k) == os.path.basename(fn)), None)
        kind = "pkg" if owner else ("flatpak" if "/flatpak/" in fn else
                                    ("shortcut" if fn.startswith(local_dir) else "other"))
        kw = []
        try:
            kw = list(a.get_keywords() or [])
        except Exception:
            pass
        item = {"kind": kind, "id": a.get_id() or os.path.basename(fn), "name": a.get_display_name() or a.get_name(),
                "comment": a.get_description() or "", "gicon": a.get_icon(), "file": fn, "pkg": owner,
                "keywords": " ".join(kw)}
        apps.append(item)
        if owner:
            pkgs[owner]["apps"].append(item["name"])
    apps.sort(key=lambda x: x["name"].lower())
    return apps


# ── очистка (07.10.2026) ──────────────────────────────────────────────────────
# Просьба: «насчёт очистки можно реализовать — если, конечно, есть что очищать».
# Показывается только то, где есть что освободить. Не предлагается: модели в
# ~/.cache/huggingface (Whisper и demucs — голос и тексты песен), кэш обоев awww.
APP_CACHES = (   # папка в ~/.cache, название, процессы, при которых чистить нельзя
    ("spotify", "Spotify", ("spotify",)), ("uv", "uv (пакеты Python)", ()),
    ("ZapZap", "ZapZap (WhatsApp)", ("zapzap",)), ("net.imput.helium", "Helium", ("helium",)),
    ("zen", "Zen", ("zen", "zen-bin", "zen-browser")), ("phpactor", "phpactor", ("phpactor",)),
    ("thumbnails", "Миниатюры файлов", ()), ("pip", "pip", ()), ("go-build", "Go", ()),
    ("mozilla", "Firefox", ("firefox",)), ("chromium", "Chromium", ("chromium",)),
    ("yandex-music", "Яндекс Музыка", ("yandex-music", "YandexMusic")),
)
MIN_SHOW = 20 * 1048576


def du(path, skip_pkgs=False):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            if skip_pkgs and ".pkg.tar." in f:
                continue
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def running(names):
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if read("/proc/%s/comm" % pid) in names:
                    return True
            except OSError:
                pass
    return False


def paccache_size(*args):
    out = sh("paccache", "-d", *args, timeout=60)
    m = re.search(r"(\d+) candidates \(disk space saved: ([\d.]+) (\w+)\)", out)
    if not m:
        return 0, 0
    mult = {"B": 1, "KiB": 1024, "MiB": 1048576, "GiB": 1073741824}.get(m.group(3), 1)
    return int(m.group(1)), int(float(m.group(2)) * mult)


def cleanup_items():
    """[{key, title, size, note, cmd (root, в терминале) | fn (сразу), block, warn}]"""
    out = []
    n, size = paccache_size("-uk0")
    if size:
        out.append({"key": "pkg-removed", "title": "Кэш удалённых программ", "size": size,
                    "note": "%d файлов пакетов, которых в системе уже нет" % n, "cmd": "sudo paccache -ruk0"})
    n, size = paccache_size("-k1")
    if size:
        out.append({"key": "pkg-old", "title": "Старые версии пакетов", "size": size,
                    "note": "%d файлов; останется только установленная версия" % n, "cmd": "sudo paccache -rk1",
                    "warn": "Откат «из кэша» в Versions станет невозможен (из Arch Archive — можно)."})
    m = re.search(r"take up ([\d.]+)([KMG])", sh("journalctl", "--disk-usage"))
    if m:
        jsize = int(float(m.group(1)) * {"K": 1024, "M": 1048576, "G": 1073741824}[m.group(2)])
        if jsize > 300 * 1048576:
            out.append({"key": "journal", "title": "Журнал системы (journald)", "size": jsize - 200 * 1048576,
                        "note": "сейчас %s, останется 200 МиБ свежих записей" % human(jsize),
                        "cmd": "sudo journalctl --vacuum-size=200M"})
    ysize = du(YAYCACHE, skip_pkgs=True)
    if ysize > MIN_SHOW:
        out.append({"key": "yay", "title": "Исходники сборок AUR (yay)", "size": ysize,
                    "note": "собранные пакеты останутся — откат AUR не пострадает", "fn": "yay"})
    for d, title, procs in APP_CACHES:
        path = os.path.join(HOME, ".cache", d)
        if not os.path.isdir(path):
            continue
        size = du(path)
        if size > MIN_SHOW:
            busy = bool(procs) and running(procs)
            out.append({"key": "cache:" + d, "title": "Кэш: " + title, "size": size,
                        "note": ("закройте %s — тогда можно" % title) if busy else "~/.cache/%s, программа скачает нужное заново" % d,
                        "fn": "cache", "path": path, "block": busy})
    baks = []
    old = time.time() - 7 * 86400
    for root, _dirs, files in os.walk(os.path.join(HOME, ".config")):
        for f in files:
            if ".bak" in f:
                fp = os.path.join(root, f)
                try:
                    st = os.lstat(fp)
                except OSError:
                    continue
                if st.st_mtime < old:
                    baks.append((fp, st.st_size))
    bsize = sum(x[1] for x in baks)
    if baks and bsize > 1048576:
        out.append({"key": "bak", "title": "Старые бэкапы .bak в ~/.config", "size": bsize,
                    "note": "%d файлов старше недели → архив ~/backups/bak-archive-ДАТА.tar.zst" % len(baks),
                    "fn": "bak", "files": [x[0] for x in baks]})
    tr = os.path.join(HOME, ".local/share/Trash")
    tsize = du(tr) if os.path.isdir(tr) else 0
    if tsize > MIN_SHOW:
        out.append({"key": "trash", "title": "Корзина", "size": tsize, "note": "файлы из корзины удалятся насовсем",
                    "fn": "cache", "path": tr, "warn": "Восстановить из корзины после этого будет нельзя."})
    return out


def cleanup_run(item):
    """Очистка без root, сразу. Возвращает текст итога."""
    import shutil
    if item["fn"] == "cache":
        freed = 0
        for n in os.listdir(item["path"]):
            fp = os.path.join(item["path"], n)
            try:
                size = du(fp) if os.path.isdir(fp) else os.lstat(fp).st_size
                shutil.rmtree(fp) if os.path.isdir(fp) and not os.path.islink(fp) else os.remove(fp)
                freed += size
            except OSError:
                pass
        return "освобождено %s" % human(freed)
    if item["fn"] == "yay":
        freed = 0
        for d in os.listdir(YAYCACHE):
            base = os.path.join(YAYCACHE, d)
            if not os.path.isdir(base):
                continue
            for n in os.listdir(base):
                fp = os.path.join(base, n)
                if ".pkg.tar." in n:
                    continue
                try:
                    size = du(fp) if os.path.isdir(fp) else os.lstat(fp).st_size
                    shutil.rmtree(fp) if os.path.isdir(fp) and not os.path.islink(fp) else os.remove(fp)
                    freed += size
                except OSError:
                    pass
        return "освобождено %s" % human(freed)
    if item["fn"] == "bak":
        dest = os.path.join(HOME, "backups")
        os.makedirs(dest, exist_ok=True)
        arch = os.path.join(dest, "bak-archive-%s.tar.zst" % time.strftime("%Y-%m-%d_%H%M"))
        lst = os.path.join(CACHE, "bak-list.txt")
        os.makedirs(CACHE, exist_ok=True)
        with open(lst, "w") as f:
            f.write("\n".join(os.path.relpath(x, HOME) for x in item["files"]))
        r = subprocess.run(["tar", "--zstd", "-cf", arch, "-C", HOME, "-T", lst], capture_output=True, text=True)
        if r.returncode != 0 or not os.path.exists(arch):
            return "архив не создался: %s" % r.stderr.strip()[:80]
        for x in item["files"]:
            try:
                os.remove(x)
            except OSError:
                pass
        return "в архиве %s (%s)" % (arch.replace(HOME, "~"), human(os.path.getsize(arch)))
    return "?"


# ── сведения о системе ────────────────────────────────────────────────────────

def dmi(k):
    return read("/sys/class/dmi/id/" + k)


def uptime():
    try:
        s = int(float(read("/proc/uptime").split()[0]))
    except (ValueError, IndexError):
        return ""
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    return ("%d д " % d if d else "") + "%d ч %d мин" % (h, s // 60)


def system_info(pkgs=None):
    """[(группа, [(ключ, значение)])] — всё, что удаётся узнать без root."""
    G = []
    osr = dict(re.findall(r'^(\w+)="?([^"\n]*)"?', read("/etc/os-release"), re.M))
    first = read(PACLOG).split("\n", 1)[0]
    inst = re.match(r"^\[(\d{4}-\d{2}-\d{2})", first)
    pk = pkgs or {}
    n_all = len(pk) or len(sh("pacman", "-Qq").split())
    n_exp = sum(1 for p in pk.values() if p["explicit"]) if pk else len(sh("pacman", "-Qqe").split())
    n_aur = sum(1 for p in pk.values() if p["foreign"]) if pk else len(sh("pacman", "-Qqm").split())
    n_flat = len([x for x in sh("flatpak", "list", "--app", "--columns=application").split() if x])
    G.append(("System", [
        ("OS", osr.get("PRETTY_NAME", "Linux")),
        ("Kernel", os.uname().release),
        ("Host", socket.gethostname()), ("User", os.environ.get("USER", "")),
        ("Uptime", uptime()),
        ("Installed", inst.group(1) if inst else ""),
        ("Packages", "%d (explicit %d, AUR %d%s)" % (n_all, n_exp, n_aur, ", flatpak %d" % n_flat if n_flat else "")),
        ("Session", (sh("niri", "--version").strip() or "niri") + " · Wayland"),
        ("Init", sh("systemctl", "--version").split("\n")[0].split("(")[0].strip()),
        ("Shell", os.path.basename(__import__("pwd").getpwuid(os.getuid()).pw_shell)),
        ("Locale", os.environ.get("LANG", "")),
        ("Time zone", os.path.realpath("/etc/localtime").split("zoneinfo/")[-1]),
    ]))
    G.append(("Device", [
        ("Model", (dmi("sys_vendor") + " " + dmi("product_name")).strip()),
        ("Version", dmi("product_version")), ("Board", dmi("board_name")),
        ("BIOS", " ".join(x for x in (dmi("bios_vendor"), dmi("bios_version"), dmi("bios_date")) if x)),
        ("Chassis", {"9": "laptop", "10": "notebook", "3": "desktop", "31": "convertible"}.get(dmi("chassis_type"), dmi("chassis_type"))),
    ]))
    cpu = dict(re.findall(r"^(model name|cpu cores|siblings)\s*:\s*(.+)$", read("/proc/cpuinfo"), re.M))
    mx = read("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq")
    freqs = []
    for i in range(os.cpu_count() or 1):
        f = read("/sys/devices/system/cpu/cpu%d/cpufreq/scaling_cur_freq" % i)
        if f.isdigit():
            freqs.append(int(f))
    temp = ""
    for hw in sorted(os.listdir("/sys/class/hwmon")) if os.path.isdir("/sys/class/hwmon") else []:
        base = "/sys/class/hwmon/" + hw
        if read(base + "/name") in ("coretemp", "k10temp", "zenpower"):
            t = read(base + "/temp1_input")
            if t.isdigit():
                temp = "%d °C" % (int(t) // 1000)
                break
    G.append(("Processor", [
        ("Model", re.sub(r"\s+", " ", cpu.get("model name", ""))),
        ("Cores", "%s cores, %d threads" % (cpu.get("cpu cores", "?"), os.cpu_count() or 0)),
        ("Max clock", "%.2f GHz" % (int(mx) / 1e6) if mx.isdigit() else ""),
        ("Now", "%.2f GHz avg" % (sum(freqs) / len(freqs) / 1e6) if freqs else ""),
        ("Governor", read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor")),
        ("Temperature", temp),
        ("Load", " ".join(read("/proc/loadavg").split()[:3])),
    ]))
    gpus = []
    for line in sh("lspci", "-mm").splitlines():
        if re.search(r'"(VGA compatible controller|3D controller|Display controller)"', line):
            parts = re.findall(r'"([^"]*)"', line)
            if len(parts) >= 3:
                gpus.append(re.sub(r"\s*Corporation", "", parts[1]) + " " + parts[2])
    rows = [("GPU %d" % (i + 1), g) for i, g in enumerate(gpus)]
    nv = read("/proc/driver/nvidia/version")
    m = re.search(r"Kernel Module(?: for x86_64)?\s+([\d.]+)", nv)
    if m:
        rows.append(("NVIDIA driver", m.group(1)))
        q = sh("nvidia-smi", "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
               "--format=csv,noheader,nounits").strip().split(", ")
        if len(q) == 4:
            rows.append(("NVIDIA now", "%s / %s MiB · %s °C · %s %%" % tuple(q)))
    if pk.get("mesa"):
        rows.append(("Mesa", pk["mesa"]["version"]))
    for v in ("vulkan-intel", "vulkan-radeon", "nvidia-utils"):
        if pk.get(v):
            rows.append((v, pk[v]["version"]))
    G.append(("Graphics", rows))
    outs = []
    try:
        od = json.loads(sh("niri", "msg", "-j", "outputs") or "{}")
    except ValueError:
        od = {}
    for name, o in sorted(od.items()):
        mode = (o.get("modes") or [{}])[o.get("current_mode") or 0] if o.get("modes") else {}
        lg = o.get("logical") or {}
        phys = o.get("physical_size") or [0, 0]
        inch = ((phys[0] ** 2 + phys[1] ** 2) ** 0.5 / 25.4) if phys and phys[0] else 0
        outs.append((name, "%s %s · %dx%d @ %.0f Hz · scale %s%s" % (
            o.get("make", ""), o.get("model", ""), mode.get("width", 0), mode.get("height", 0),
            (mode.get("refresh_rate") or 0) / 1000, lg.get("scale", 1),
            ' · %.1f"' % inch if inch else "")))
    G.append(("Displays", outs or [("—", "niri не ответил")]))
    mem = dict((k, int(v.split()[0])) for k, v in re.findall(r"^(\w+):\s*(.+)$", read("/proc/meminfo"), re.M))
    zr = read("/sys/block/zram0/mm_stat").split()
    rows = [("RAM", "%s used of %s (%s available)" % (
        human((mem.get("MemTotal", 0) - mem.get("MemAvailable", 0)) * 1024), human(mem.get("MemTotal", 0) * 1024),
        human(mem.get("MemAvailable", 0) * 1024))),
        ("Swap", "%s of %s" % (human((mem.get("SwapTotal", 0) - mem.get("SwapFree", 0)) * 1024),
                               human(mem.get("SwapTotal", 0) * 1024)))]
    if len(zr) >= 3:
        rows.append(("zram", "%s stored in %s RAM (algorithm %s)" % (
            human(int(zr[0])), human(int(zr[2])),
            re.sub(r".*\[(\w+)\].*", r"\1", read("/sys/block/zram0/comp_algorithm")))))
    rows.append(("Cached", human(mem.get("Cached", 0) * 1024)))
    G.append(("Memory", rows))
    rows = []
    try:
        bl = json.loads(sh("lsblk", "-J", "-b", "-o", "NAME,MODEL,SIZE,TYPE,TRAN,ROTA") or "{}")
        for d in bl.get("blockdevices", []):
            if d.get("type") == "disk" and not d["name"].startswith(("zram", "loop")):
                rows.append((d["name"], "%s · %s · %s" % ((d.get("model") or "").strip(), human(d.get("size")),
                                                         "HDD" if d.get("rota") else (d.get("tran") or "SSD").upper())))
    except ValueError:
        pass
    for mp in ("/", "/home", "/boot", "/efi"):
        if os.path.ismount(mp):
            st = os.statvfs(mp)
            tot, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
            rows.append((mp, "%s free of %s (%d%% used)" % (human(free), human(tot), round(100 - free * 100 / max(tot, 1)))))
    rows.append(("Package cache", sh("du", "-sh", PKGCACHE, timeout=20).split("\t")[0] or "?"))
    G.append(("Storage", rows))
    rows = []
    for ps in sorted(os.listdir("/sys/class/power_supply")) if os.path.isdir("/sys/class/power_supply") else []:
        b = "/sys/class/power_supply/" + ps
        if read(b + "/type") == "Battery":
            full = read(b + "/energy_full") or read(b + "/charge_full")
            design = read(b + "/energy_full_design") or read(b + "/charge_full_design")
            health = "%d%%" % (int(full) * 100 // int(design)) if full.isdigit() and design.isdigit() and int(design) else ""
            rows += [(ps, "%s%% · %s" % (read(b + "/capacity"), read(b + "/status"))),
                     ("Health", health + (" of design" if health else "")),
                     ("Cycles", read(b + "/cycle_count")),
                     ("Model", " ".join(x for x in (read(b + "/manufacturer"), read(b + "/model_name"), read(b + "/technology")) if x))]
        elif read(b + "/type") == "Mains":
            rows.append(("Charger", "connected" if read(b + "/online") == "1" else "not connected"))
    if rows:
        G.append(("Battery", rows))
    rows = []
    for line in sh("nmcli", "-t", "-f", "NAME,TYPE,DEVICE", "connection", "show", "--active").splitlines():
        p = line.split(":")
        if len(p) >= 3 and p[1] not in ("loopback",):
            rows.append((p[2] or p[1], "%s (%s)" % (p[0], p[1].replace("802-11-wireless", "Wi-Fi").replace("802-3-ethernet", "Ethernet"))))
    for line in sh("nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL,CHAN", "device", "wifi").splitlines():
        p = line.split(":")
        if p[0] == "yes" and len(p) >= 4:
            rows.append(("Wi-Fi signal", "%s%% · channel %s" % (p[2], p[3])))
    for line in sh("ip", "-4", "-o", "addr").splitlines():
        p = line.split()
        if len(p) > 3 and p[1] != "lo":
            rows.append(("IPv4 " + p[1], p[3]))
    gw = re.search(r"default via (\S+)", sh("ip", "route"))
    if gw:
        rows.append(("Gateway", gw.group(1)))
    bt = sh("bluetoothctl", "show", timeout=3)
    if bt:
        rows.append(("Bluetooth", "on" if "Powered: yes" in bt else "off"))
    G.append(("Network", rows))
    def pretty(kind, name):                 # имя устройства по-человечески (description)
        try:
            for d in json.loads(sh("pactl", "-f", "json", "list", kind) or "[]"):
                if d.get("name") == name:
                    return d.get("description") if d.get("description") not in (None, "", "(null)") else name
        except ValueError:
            pass
        return name
    rows = [("Output", pretty("sinks", sh("pactl", "get-default-sink").strip())),
            ("Input", pretty("sources", sh("pactl", "get-default-source").strip()))]
    srv = re.search(r"Server Name: (.+)", sh("pactl", "info"))
    if srv:
        rows.append(("Server", srv.group(1)))
    G.append(("Audio", rows))
    gs = lambda k: sh("gsettings", "get", "org.gnome.desktop.interface", k).strip().strip("'")  # noqa: E731
    style = read(os.path.join(HOME, ".config/hypr/state/system-style"))
    G.append(("Look", [
        ("System style", ", ".join("%s: %s" % kv for kv in (json.loads(style).items() if style.startswith("{") else []))),
        ("GTK theme", gs("gtk-theme")), ("Icons", gs("icon-theme")),
        ("Cursor", "%s %s" % (gs("cursor-theme"), gs("cursor-size"))), ("Font", gs("font-name")),
        ("Color scheme", gs("color-scheme")),
    ]))
    vers = []
    for name in ("niri", "kitty", "waybar", "pipewire", "python", "gtk3", "gtk4", "qt6-base", "mesa",
                 "systemd", "pacman", "yay", "zen-browser-bin", "telegram-desktop"):
        if pk.get(name):
            vers.append((name, pk[name]["version"]))
    if vers:
        G.append(("Versions", vers))
    junk = ("Not Applicable", "To be filled by O.E.M.", "Default string", "System Product Name")
    return [(g, [(k, v) for k, v in rows if v and v.strip() not in junk]) for g, rows in G]


def info_text(groups):
    out = []
    for g, rows in groups:
        out.append("[%s]" % g)
        out += ["  %-16s %s" % (k, v) for k, v in rows]
        out.append("")
    return "\n".join(out)


# ── окно ──────────────────────────────────────────────────────────────────────

sys.path.insert(0, HERE)
import routine_app as R  # noqa: E402  (рамки, цвета стилей, шрифт — как у Routine)
import gi  # noqa: E402
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GdkPixbuf, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402
import cairo  # noqa: E402

W, H = 980, 640
PAD = 14
ROW = 22
LIST_W = 430
PX = R.PX
mix = R.mix


class Data:
    """Всё о пакетах. Быстрое — сразу, медленное (сеть, -Sl) — в потоке."""

    def __init__(self, background=True):
        self.lock = threading.Lock()
        self.ups, self.ups_t, self.ups_busy = {}, 0, False
        self.archive = {}            # имя → список или "loading" / "err: …"
        self.info, self.info_busy = None, False
        self.load()
        try:
            d = json.load(open(os.path.join(CACHE, "updates.json")))
            self.ups, self.ups_t = d.get("ups", {}), d.get("t", 0)
        except (OSError, ValueError):
            pass
        if background:
            threading.Thread(target=self.slow, daemon=True).start()

    def load(self):
        self.pkgs, desk = load_local()
        self.apps = load_apps(Gio, self.pkgs, desk)
        self.cache = cache_files()
        self.hist = pacman_history()
        self.held = holds()
        self.stamp = self.db_stamp()
        self.on_change = getattr(self, "on_change", None)
        if getattr(self, "_repos", None):
            for n, r in self._repos.items():
                if n in self.pkgs:
                    self.pkgs[n]["repo"] = r
                    self.pkgs[n]["foreign"] = r == "AUR"

    @staticmethod
    def db_stamp():
        st = []
        for p in (DB, PACLOG, PACCONF):
            try:
                st.append(os.stat(p).st_mtime)
            except OSError:
                st.append(0)
        return tuple(st)

    def slow(self, force=False):
        foreign_and_repos(self.pkgs)
        self._repos = {n: p["repo"] for n, p in self.pkgs.items() if p["repo"]}
        self.notify()
        self.updates(force)

    def updates(self, force=False):
        if self.ups_busy:
            return
        self.ups_busy = True
        self.notify()
        try:
            d = check_updates(force)
            self.ups, self.ups_t = d.get("ups", {}), d.get("t", 0)
        finally:
            self.ups_busy = False
            self.notify()

    def fetch_archive(self, name):
        if self.archive.get(name) == "loading":
            return
        self.archive[name] = "loading"
        self.notify()

        def job():
            self.archive[name] = archive_versions(name)
            self.notify()
        threading.Thread(target=job, daemon=True).start()

    def fetch_cleanup(self):
        if getattr(self, "clean_busy", False):
            return
        self.clean_busy = True
        self.notify()

        def job():
            try:
                self.clean = cleanup_items()
                self.clean_t = time.time()
            finally:
                self.clean_busy = False
                self.notify()
        threading.Thread(target=job, daemon=True).start()

    def fetch_info(self):
        if self.info_busy:
            return
        self.info_busy = True

        def job():
            try:
                self.info = system_info(self.pkgs)
            finally:
                self.info_busy = False
                self.notify()
        threading.Thread(target=job, daemon=True).start()

    def notify(self):
        cb = getattr(self, "on_change", None)
        if cb:
            GLib.idle_add(cb)

    def versions(self, name):
        """Строки «Versions»: (версия, откуда, дата, путь|ссылка|None, что делать)."""
        p = self.pkgs.get(name)
        if not p:
            return []
        cur = p["version"]
        rows = {}
        new = self.ups.get(name)
        if new and vercmp(new, cur) > 0:
            rows[new] = (new, "update", "", None, "update")
        rows[cur] = (cur, "installed", day(p["installed"]), None, "")
        when = {}
        for d, act, txt in self.hist.get(name, []):
            v = txt.split(" -> ")[-1]
            when.setdefault(v, d)
        for v, path in self.cache.get(name, []):
            if v not in rows:
                rows[v] = (v, "cache", when.get(v, ""), path, "install")
        arch = self.archive.get(name)
        if isinstance(arch, list):
            for v, url, d in arch:
                if v not in rows:
                    rows[v] = (v, "archive", d, url, "install")
        import functools
        return sorted(rows.values(), key=functools.cmp_to_key(lambda a, b: vercmp(a[0], b[0])), reverse=True)


class Icons:
    """Значки темы (Jarvis-Pixel и наследники), без окна тоже работают."""

    def __init__(self):
        self.theme = Gtk.IconTheme.new()
        name = (sh("gsettings", "get", "org.gnome.desktop.interface", "icon-theme").strip().strip("'")
                or "Papirus-Dark")
        self.theme.set_custom_theme(name)
        self.memo = {}

    def get(self, gicon, size, fallback="application-x-executable"):
        key = (gicon.to_string() if gicon else fallback, size)
        if key in self.memo:
            return self.memo[key]
        pb = None
        try:
            info = self.theme.lookup_by_gicon(gicon, size, Gtk.IconLookupFlags.FORCE_SIZE) if gicon else None
            if info is None:
                info = self.theme.lookup_icon(fallback, size, Gtk.IconLookupFlags.FORCE_SIZE)
            pb = info.load_icon() if info else None
        except Exception:
            pb = None
        self.memo[key] = pb
        return pb


class View:
    # рамки, кнопки, группы и строки — как у Routine (одни и те же функции)
    draw_frame = R.View.draw_frame
    group = R.View.group
    button = R.View.button
    row_bg = R.View.row_bg

    def __init__(self, data):
        self.d = data
        self.icons = Icons()
        self.tab = "apps"
        self.sel = {t: 0 for t in TABS}
        self.scroll = {t: 0 for t in TABS}
        self.vsel = 0
        self.focus = "list"            # list | versions
        self.mode = "normal"           # normal | search | confirm | help
        self.query = ""
        self.sort = "name"             # name | size | date
        self.all_pkgs = False
        self.only_ups = False              # показать только то, что можно обновить (щелчок по «↑ N»)
        self.confirm = None            # dict: title, lines, cmd, action, need (что ввести), danger
        self.typed = ""
        self.msg, self.msg_until = "", 0
        self.hover = None
        self.hits = []
        self.active = True
        self.w, self.h = W, H              # размер окна (его можно растягивать, 07.10.2026)
        self.free_scroll = False           # полосу тянут мышью: прокрутка ведёт, выбор подстраивается
        self.reload_style()

    def reload_style(self):
        self.style = R.style_name()
        self.c = R.colors(self.style)

    def flash(self, s, secs=3.0):
        self.msg, self.msg_until = s, time.monotonic() + secs

    # ── что в списке ──
    def items(self):
        q = self.query.lower().strip()
        alt = other_layout(q)
        if self.tab == "apps":
            src = []
            for a in self.d.apps:
                p = self.d.pkgs.get(a["pkg"]) if a["pkg"] else None
                src.append({"name": a["name"], "app": a, "pkg": p,
                            "hay": " ".join((a["name"], a["comment"], a["keywords"], a["pkg"] or "", a["id"])).lower()})
        else:
            src = []
            for p in self.d.pkgs.values():
                if self.all_pkgs or p["explicit"]:
                    src.append({"name": p["name"], "app": None, "pkg": p,
                                "hay": (p["name"] + " " + p["desc"]).lower()})
        if q:
            src = [x for x in src if q in x["hay"] or alt in x["hay"]]
        if self.only_ups:
            src = [x for x in src if x["pkg"] and self.d.ups.get(x["pkg"]["name"])]
        if self.sort == "size":
            src.sort(key=lambda x: -(x["pkg"]["size"] if x["pkg"] else 0))
        elif self.sort == "date":
            src.sort(key=lambda x: -(self.last_change(x["pkg"]) if x["pkg"] else 0))
        else:
            src.sort(key=lambda x: x["name"].lower())
        return src

    def last_change(self, p):
        h = self.d.hist.get(p["name"])
        if h:
            try:
                return dt.datetime.fromisoformat(h[-1][0]).timestamp()
            except ValueError:
                pass
        return p["installed"]

    def current(self):
        if self.tab in ("system", "cleanup"):
            return None
        it = self.items()
        if not it:
            return None
        i = max(0, min(self.sel[self.tab], len(it) - 1))
        self.sel[self.tab] = i
        return it[i]

    # ── раскладка ──
    def frame(self):
        return 6 if self.c["frame"] == "skeet" else 1

    def body(self):
        f = self.frame()
        top = f + 2 + 10 + 18 + 22
        foot = self.h - f - 8 - 18
        return top, foot - 14, foot

    def list_rows(self):
        top, bottom, _ = self.body()
        return max(1, (bottom - top - 16) // ROW)

    # ── рисунок ──
    def list_w(self):
        return max(380, min(560, int((self.w - 2 * PAD) * 0.45)))

    def draw(self, cr, w, h):
        self.w, self.h = w, h
        self.hits = []
        p = R.Painter(cr)
        self.draw_frame(p, w, h)
        f = self.frame()
        x0, x1 = PAD + f, w - PAD - f
        self.draw_header(p, x0, x1, f + 2 + 10)
        top, bottom, foot = self.body()
        if self.tab == "system":
            self.draw_system(p, x0, x1, top, bottom)
        elif self.tab == "cleanup":
            self.draw_cleanup(p, x0, x1, top, bottom)
        else:
            lw = self.list_w()
            self.draw_list(p, x0, x0 + lw, top, bottom)
            self.draw_details(p, x0 + lw + 14, x1, top, bottom)
        self.draw_footer(p, x0, x1, foot)
        if self.mode == "confirm" and self.confirm:
            self.draw_confirm(p, w, h)
        elif self.mode == "help":
            self.draw_help(p, w, h)

    def draw_header(self, p, x0, x1, y):
        c = self.c
        x = x0
        cl = getattr(self.d, "clean", None)
        counts = {"cleanup": human(sum(x["size"] for x in cl)) if cl else None,
                  "apps": len(self.d.apps),
                  "packages": sum(1 for q in self.d.pkgs.values() if self.all_pkgs or q["explicit"]),
                  "system": None}
        for t in TABS:
            on = t == self.tab
            label = TAB_NAMES[t]
            tw = p.text(x, y, label, (c["acc_l"] if self.active else c["text"]) if on else
                        (c["text"] if self.hover == ("tab", t) else c["dim"]))
            if counts[t] is not None:
                tw += 6 + p.text(x + tw + 6, y, str(counts[t]), c["acc"] if on else c["faint"])
            if on:
                p.rect(x, y + 17, tw, 2, c["acc"] if self.active else c["line"])
            self.hits.append(((x - 4, y - 6, tw + 8, 26), ("tab", t)))
            x += tw + 22
        # поиск справа
        sw = 230
        sx = x1 - 22 - sw
        searching = self.mode == "search"
        if self.tab not in ("system", "cleanup"):
            p.rect(sx, y - 3, sw, 20, c["field"])
            p.box(sx, y - 3, sw, 20, c["acc"] if searching else c["line"])
            txt = self.query if (self.query or searching) else "/ search"
            tw = p.text(sx + 8, y, txt, c["text"] if (self.query or searching) else c["faint"], maxw=sw - 16)
            if searching and int(time.monotonic() * 2) % 2 == 0:
                p.rect(sx + 8 + tw + 1, y + 1, 6, 13, c["acc_l"])
            self.hits.append(((sx, y - 3, sw, 20), "search"))
        p.text(x1, y, "×", c["text"] if self.hover == "close" else c["dim"], align="r")
        self.hits.append(((x1 - 12, y - 4, 16, 20), "close"))

    def draw_icon(self, p, gicon, x, y, size, fallback="package-x-generic"):
        pb = self.icons.get(gicon, size, fallback)
        if not pb:
            return
        cr = p.cr
        cr.save()
        Gdk.cairo_set_source_pixbuf(cr, pb, x, y)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()

    def draw_list(self, p, x0, x1, top, bottom):
        c = self.c
        it = self.items()
        title = {"apps": "Applications", "packages": "Packages · all" if self.all_pkgs else "Packages · explicit"}[self.tab]
        if self.only_ups:
            title += " · updates"
        n_up = sum(1 for x in it if x["pkg"] and self.d.ups.get(x["pkg"]["name"]))
        sort_txt = "sort: %s" % self.sort
        up_txt = ("  ↑ %d" % n_up) if (self.d.ups and (n_up or self.only_ups)) else ""
        self.group(p, x0, top, x1 - x0, bottom - top, title, sort_txt + up_txt)
        # подписи справа на рамке — кнопки: «sort» листает сортировку, «↑ N» — только обновления
        end = x1 - x0 - 14 + x0
        uw = p.text_w(up_txt) if up_txt else 0
        sw = p.text_w(sort_txt)
        if self.hover == ("hdr", "sort"):
            p.text(end - uw, top - 7, sort_txt, c["acc_l"], align="r")
        if up_txt and (self.hover == ("hdr", "ups") or self.only_ups):
            p.text(end, top - 7, up_txt, c["acc_l"], align="r")
        self.hits.append(((end - uw - sw - 4, top - 9, sw + 6, 18), ("hdr", "sort")))
        if up_txt:
            self.hits.append(((end - uw + 8, top - 9, uw - 6, 18), ("hdr", "ups")))
        n = self.list_rows()
        sel = self.sel[self.tab]
        sc = self.scroll[self.tab]
        if self.free_scroll:                     # тянут полосу: выбор держим в видимой части
            sc = max(0, min(sc, max(0, len(it) - n)))
            sel = self.sel[self.tab] = max(sc, min(sel, sc + n - 1, len(it) - 1))
        elif sel < sc:
            sc = sel
        elif sel >= sc + n:
            sc = sel - n + 1
        sc = max(0, min(sc, max(0, len(it) - n)))
        self.scroll[self.tab] = sc
        y = top + 10
        for i in range(sc, min(len(it), sc + n)):
            x = it[i]
            key = ("row", i)
            on = i == sel
            self.row_bg(p, x0 + 2, x1 - 2, y, on, key, h=ROW)
            pk = x["pkg"]
            gicon = x["app"]["gicon"] if x["app"] else None
            if not gicon and pk and pk["apps"]:
                a = next((a for a in self.d.apps if a["pkg"] == pk["name"]), None)
                gicon = a["gicon"] if a else None
            self.draw_icon(p, gicon, x0 + 10, y + 3, 16)
            right = x1 - 12
            size = human(pk["size"]) if pk else ("shortcut" if x["app"] and x["app"]["kind"] == "shortcut" else "")
            p.text(right, y + 4, size, c["faint"], align="r")
            vx = right - 84
            ver = pk["version"] if pk else ""
            up = pk and self.d.ups.get(pk["name"])
            held = pk and pk["name"] in self.d.held
            vw = min(p.text_w(ver), 104)
            p.text(vx - vw, y + 4, ver, c["dim"], maxw=104)
            if up:
                p.text(vx - vw - 8, y + 4, "↑", c["acc_l"], align="r")
            if held:
                p.text(vx - vw - (20 if up else 8), y + 4, "⚓", c["dim"], align="r")
            col = c["acc_l"] if on and self.focus == "list" else c["text"]
            p.text(x0 + 34, y + 4, x["name"], col, maxw=max(40, vx - vw - 26 - x0 - 34))
            y += ROW
        if not it:
            p.text((x0 + x1) / 2, top + 40, "ничего не найдено" if self.query else "пусто", c["faint"], align="c")
        # полоса прокрутки
        if len(it) > n:
            th = max(16, (bottom - top - 20) * n // len(it))
            ty = top + 10 + (bottom - top - 20 - th) * sc // max(1, len(it) - n)
            hot = self.free_scroll or self.hover == ("sbar", "list")
            p.rect(x1 - 6 if hot else x1 - 5, ty, 4 if hot else 2, th, c["acc"] if (self.focus == "list" or hot) else c["line"])
            # область захвата шире самой полосы; (верх дорожки, высота дорожки, высота ползунка, строк)
            self.sb = {"list": (top + 10, bottom - top - 20, th, len(it) - n)}
            self.hits.append(((x1 - 12, top + 8, 12, bottom - top - 16), ("sbar", "list")))

    def wrap(self, p, x, y, s, col, maxw, lines=2, px=PX):
        lay = p.layout(s, px)
        lay.set_width(int(maxw * Pango.SCALE))
        lay.set_wrap(Pango.WrapMode.WORD_CHAR)
        lay.set_height(-lines)
        lay.set_ellipsize(Pango.EllipsizeMode.END)
        p.rgb(col)
        p.cr.move_to(round(x), round(y))
        PangoCairo.show_layout(p.cr, lay)
        return lay.get_pixel_size()[1]

    def actions_for(self, x):
        """Кнопки карточки: (подпись, ключ, акцент, доступна)."""
        pk, app = x["pkg"], x["app"]
        out = []
        if app:
            out.append(("Open", "open", False, True))
        if pk:
            up = self.d.ups.get(pk["name"])
            out.append(("Update ↑" if up else "Up to date", "update", bool(up), bool(up)))   # новая версия — в «Versions»
            out.append(("Reinstall", "reinstall", False, True))
            out.append(("Unhold" if pk["name"] in self.d.held else "Hold", "hold", False, True))
            out.append(("Uninstall", "remove", False, True))
        elif app and app["kind"] == "shortcut":
            out.append(("Delete shortcut", "remove", False, True))
        return out

    def draw_details(self, p, x0, x1, top, bottom):
        c = self.c
        x = self.current()
        if not x:
            self.group(p, x0, top, x1 - x0, bottom - top, "Details")
            return
        pk, app = x["pkg"], x["app"]
        self.group(p, x0, top, x1 - x0, bottom - top, "Details", pk["repo"] if pk and pk["repo"] else "")
        ix, iy = x0 + 14, top + 16
        gicon = app["gicon"] if app else None
        if not gicon and pk:
            a = next((a for a in self.d.apps if a["pkg"] == pk["name"]), None)
            gicon = a["gicon"] if a else None
        self.draw_icon(p, gicon, ix, iy, 48)
        tx = ix + 62
        p.text(tx, iy + 2, x["name"], c["text"], px=16, maxw=x1 - tx - 14)
        sub = []
        if pk:
            sub.append("%s %s" % (pk["name"], pk["version"]))
            if pk["name"] in self.d.held:
                sub.append("held ⚓")
        elif app:
            sub.append({"shortcut": "local shortcut", "flatpak": "flatpak", "other": "no package"}.get(app["kind"], ""))
        p.text(tx, iy + 22, "  ·  ".join(sub), c["dim"], maxw=x1 - tx - 14)
        desc = (app["comment"] if app and app["comment"] else "") or (pk["desc"] if pk else "")
        y = iy + 58
        if desc:
            y += self.wrap(p, ix, y, desc, c["text"], x1 - ix - 14, lines=2) + 8
        # факты
        facts = []
        if pk:
            h = self.d.hist.get(pk["name"], [])
            upd = next((d for d, a, _t in reversed(h) if a in ("upgraded", "downgraded", "reinstalled")), "")
            facts += [("Installed", day(pk["installed"])), ("Updated", ".".join(reversed(upd.split("-"))) if upd else "—"),
                      ("Size", human(pk["size"])), ("Built", day(pk["built"])),
                      ("Reason", "installed by you" if pk["explicit"] else "dependency"),
                      ("Source", pk["repo"] or "…")]
            req = pk["required"]
            facts.append(("Needed by", ("%d: " % len(req) + ", ".join(sorted(req)[:6]) + (" …" if len(req) > 6 else "")) if req else "nothing"))
            if len(pk["apps"]) > 1:
                facts.append(("Apps", ", ".join(pk["apps"])))
            if pk["url"]:
                facts.append(("Web", pk["url"]))
        elif app:
            facts.append(("File", app["file"].replace(HOME, "~")))
        colw = (x1 - ix - 14) // 2
        for k, (key, val) in enumerate(facts):
            full = key in ("Needed by", "Web", "Apps", "File")
            if full and k % 2 == 1:
                pass
            cx = ix if (full or k % 2 == 0) else ix + colw
            p.text(cx, y, key, c["faint"])
            p.text(cx + 92, y, val, c["text"], maxw=(x1 - cx - 106) if full else colw - 100)
            if full or k % 2 == 1 or k == len(facts) - 1:
                y += 17
        y += 8
        # кнопки
        acts = self.actions_for(x)
        if acts:
            gap = 6
            bw = (x1 - ix - 14 - gap * (len(acts) - 1)) / len(acts)
            for k, (lab, key, acc, ok) in enumerate(acts):
                bx = round(ix + k * (bw + gap))
                if ok:
                    self.button(p, bx, y, round(bw), lab, ("act", key), accent=acc)
                else:
                    self.button(p, bx, y, round(bw), lab, ("noop", key), dim=True)
            y += 24 + 18
        # версии
        if pk:
            rows = self.d.versions(pk["name"])
            arch = self.d.archive.get(pk["name"])
            right = ("archive: loading…" if arch == "loading" else
                     "archive: error" if isinstance(arch, str) else
                     "" if isinstance(arch, list) or pk["foreign"] else "A — older online")
            gy, gh = y, bottom - 10 - y
            if gh > 40:
                self.group(p, ix - 4, gy, x1 - ix - 6, gh, "Versions", right)
                vy = gy + 10
                n = max(1, (gh - 16) // 20)
                vs = self.vsel = max(0, min(self.vsel, len(rows) - 1)) if rows else 0
                start = max(0, min(vs - n + 1, len(rows) - n)) if vs >= n else 0
                for j in range(start, min(len(rows), start + n)):
                    ver, src, date, _path, what = rows[j]
                    on = self.focus == "versions" and j == vs
                    self.row_bg(p, ix - 2, x1 - 12, vy, on, ("ver", j), h=20)
                    mark = {"installed": "●", "update": "↑", "cache": "○", "archive": "☁"}[src]
                    mc = c["acc_l"] if src in ("installed", "update") else c["dim"]
                    p.text(ix + 8, vy + 3, mark, mc)
                    p.text(ix + 24, vy + 3, ver, c["acc_l"] if on else c["text"], maxw=160)
                    p.text(ix + 192, vy + 3, src, c["dim"])
                    p.text(ix + 284, vy + 3, short_date(date), c["faint"])
                    if what:
                        lab = {"update": "update", "install": "roll back" if vercmp(ver, pk["version"]) < 0 else "install"}[what]
                        p.text(x1 - 20, vy + 3, lab, c["acc_l"] if (on or self.hover == ("ver", j)) else c["faint"], align="r")
                    vy += 20
                hist = self.d.hist.get(pk["name"], [])
                if hist and vy + 18 < gy + gh - 4:
                    last = hist[-3:]
                    line = "   ".join("%s %s %s" % (d[8:10] + "." + d[5:7], a, t.split(" -> ")[-1]) for d, a, t in reversed(last))
                    p.text(ix + 8, gy + gh - 22, "history: " + line, c["faint"], maxw=x1 - ix - 30)

    def draw_cleanup(self, p, x0, x1, top, bottom):
        c = self.c
        items = getattr(self.d, "clean", None)
        busy = getattr(self.d, "clean_busy", False)
        if items is None:
            if not busy:
                self.d.fetch_cleanup()
            p.text((x0 + x1) / 2, (top + bottom) / 2, "считаю, что можно освободить…", c["dim"], align="c")
            return
        total = sum(x["size"] for x in items)
        right = ("пересчитываю…" if busy else "R — пересчитать")
        self.group(p, x0, top, x1 - x0, bottom - top,
                   "Место на диске — можно освободить: %s" % human(total) if items else "Cleanup", right)
        if not items:
            p.text((x0 + x1) / 2, (top + bottom) / 2, "Чистить нечего — всё и так в порядке", c["dim"], align="c")
            return
        sel = self.sel["cleanup"] = max(0, min(self.sel["cleanup"], len(items) - 1))
        rh = 40
        fit = max(1, (bottom - top - 18) // rh)
        first = max(0, sel - fit + 1)                # выбранная строка всегда видна
        y = top + 12
        for i, it in enumerate(items):
            if i < first:
                continue
            if y + rh > bottom - 6:
                break
            on = i == sel
            self.row_bg(p, x0 + 2, x1 - 2, y, on, ("crow", i), h=rh - 4)
            p.text(x0 + 16, y + 4, it["title"], c["acc_l"] if on else c["text"])
            p.text(x0 + 16, y + 20, it["note"], c["err"] if it.get("block") else c["dim"], maxw=x1 - x0 - 300)
            p.text(x1 - 166, y + 12, human(it["size"]), c["text"], align="r")
            if it.get("block"):
                self.button(p, x1 - 146, y + 6, 126, "Busy", ("noop", i), dim=True)
            else:
                self.button(p, x1 - 146, y + 6, 126, "Clean" + (" · sudo" if it.get("cmd") else ""), ("clean", i))
            y += rh

    def draw_system(self, p, x0, x1, top, bottom):
        c = self.c
        info = self.d.info
        if info is None:
            self.d.fetch_info()
            p.text((x0 + x1) / 2, (top + bottom) / 2, "собираю сведения…", c["dim"], align="c")
            return
        colw = (x1 - x0 - 14) // 2
        vw = colw - 150

        def row_h(v):                       # значение — до двух строк с переносом
            lay = p.layout(v, PX)
            lay.set_width(int(vw * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            return 17 if lay.get_line_count() < 2 else 32
        # раскладка в две колонки: группы по очереди в более короткую
        heights = [0, 0]
        place = []
        for g, rows in info:
            rh = [row_h(v) for _k, v in rows]
            hgt = 22 + sum(rh) + 14
            col = 0 if heights[0] <= heights[1] else 1
            place.append((col, heights[col], g, list(zip(rows, rh)), hgt))
            heights[col] += hgt + 14
        total = max(heights)
        view = bottom - top
        sc = self.scroll["system"] = max(0, min(self.scroll["system"], max(0, total - view)))
        p.cr.save()
        p.cr.rectangle(x0 - 2, top - 10, x1 - x0 + 4, view + 12)
        p.cr.clip()
        for col, y, g, rows, hgt in place:
            gx = x0 + col * (colw + 14)
            gy = top + y - sc
            if gy + hgt < top - 10 or gy > bottom:
                continue
            self.group(p, gx, gy, colw, hgt, g)
            ry = gy + 12
            for (k, v), rh in rows:
                p.text(gx + 12, ry, k, c["faint"], maxw=128)
                self.wrap(p, gx + 144, ry, v, c["text"], vw, lines=2)
                ry += rh
        p.cr.restore()
        if total > view:
            th = max(16, view * view // total)
            ty = top + (view - th) * sc // max(1, total - view)
            hot = self.free_scroll or self.hover == ("sbar", "system")
            p.rect(x1 - 4 if hot else x1 - 3, ty, 4 if hot else 2, th, c["acc"])
            self.sb = {"system": (top, view, th, total - view)}
            self.hits.append(((x1 - 10, top, 12, view), ("sbar", "system")))

    def draw_footer(self, p, x0, x1, y):
        c = self.c
        p.rect(x0, y - 8, x1 - x0, 1, c["line_soft"])
        badge = {"normal": "NORMAL", "search": "SEARCH", "confirm": "CONFIRM", "help": "HELP"}[self.mode]
        bw = p.text_w(badge) + 10
        hot = self.mode != "normal"
        p.rect(x0, y - 1, bw, 16, c["acc"] if hot else c["field_l"])
        p.text(x0 + 5, y, badge, c["bg"] if hot else c["acc_l"])
        x = x0 + bw + 10
        if self.msg and time.monotonic() < self.msg_until:
            p.text(x, y, self.msg, c["text"], maxw=x1 - x)
            return
        status = ""
        if self.d.ups_busy:
            status = "checking updates…"
        elif self.d.ups_t:
            n = sum(1 for k in self.d.ups if k in self.d.pkgs)
            status = "%d update%s · checked %s" % (n, "" if n == 1 else "s", time.strftime("%H:%M", time.localtime(self.d.ups_t)))
        hint = {"system": "j/k scroll · y copy all · R refresh · ? keys",
                "cleanup": "j/k choose · Enter clean (asks first) · R recount · ? keys",
                }.get(self.tab, "o open · u update · r reinstall · D remove · l versions · ? keys")
        p.text(x, y, hint, c["dim"], maxw=x1 - x - p.text_w(status) - 20)
        p.text(x1, y, status, c["faint"], align="r")

    def draw_overlay_card(self, p, w, h, cw, ch):
        c = self.c
        p.rect(0, 0, w, h, c["bg"], 0.55)
        x, y = (w - cw) // 2, (h - ch) // 2
        R.View.card(p, c, x, y, cw, ch)
        return x, y

    def draw_confirm(self, p, w, h):
        c, cf = self.c, self.confirm
        cw = 640
        lines = cf["lines"]
        lh = []
        for line in lines:                      # высота каждой строки с переносом
            lay = p.layout(line, PX)
            lay.set_width(int((cw - 44) * Pango.SCALE))
            lay.set_wrap(Pango.WrapMode.WORD_CHAR)
            lh.append(lay.get_pixel_size()[1] + 3)
        ch = 70 + sum(lh) + (24 if cf.get("cmd") else 0) + (34 if cf.get("need") else 0) + 44
        x, y = self.draw_overlay_card(p, w, h, cw, ch)
        ix = x + 22
        yy = y + 20
        p.text(ix, yy, cf["title"], c["err"] if cf.get("danger") else c["acc_l"], px=16, maxw=cw - 44)
        yy += 30
        for k, line in enumerate(lines):
            self.wrap(p, ix, yy, line, c["err"] if line.startswith("ЭТО") else c["text"], cw - 44, lines=4)
            yy += lh[k]
        if cf.get("cmd"):
            yy += 4
            p.text(ix, yy, "$ " + cf["cmd"], c["dim"], maxw=cw - 44)
            yy += 20
        if cf.get("need"):
            yy += 4
            p.rect(ix, yy, cw - 44, 22, c["field"])
            p.box(ix, yy, cw - 44, 22, c["acc"])
            shown = self.typed or "type: %s" % cf["need"]
            tw = p.text(ix + 8, yy + 4, shown, c["text"] if self.typed else c["faint"])
            if self.typed and int(time.monotonic() * 2) % 2 == 0:
                p.rect(ix + 8 + tw + 1, yy + 5, 6, 13, c["acc_l"])
            yy += 30
        yy += 8
        bw = 170
        ok = not cf.get("need") or self.typed.strip() == cf["need"]
        self.button(p, x + cw - 22 - bw * 2 - 8, yy, bw, "Cancel · n", ("cf", "no"))
        self.button(p, x + cw - 22 - bw, yy, bw, cf["yes"] + (" · Enter" if cf.get("need") else " · y"),
                    ("cf", "yes") if ok else ("noop", "cf"), accent=ok, dim=not ok)

    HELP = (("j k  ↓ ↑", "move"), ("gg  G  Ctrl+D/U", "top · bottom · half page"),
            ("H L  Tab  gt gT  1–4", "tabs"), ("/", "search (Enter, jj, оо, Ctrl+E — done)"),
            ("l  Enter  ·  h", "to versions · back"), ("Enter on a version", "roll back / install it"),
            ("o", "open the app"), ("u", "update only this app"), ("r", "reinstall"),
            ("D  dd", "uninstall (asks first)"), ("p", "hold: -Syu won't touch it"),
            ("A", "older versions from Arch archive"), ("s  a  U", "sort · all packages · only updates"),
            ("R", "check for updates now"), ("y", "copy name / system info"), ("q  Esc", "close"))

    def draw_help(self, p, w, h):
        c = self.c
        cw, ch = 520, 50 + len(self.HELP) * 17 + 20
        x, y = self.draw_overlay_card(p, w, h, cw, ch)
        p.text(x + 22, y + 18, "Keys", c["acc_l"], px=16)
        yy = y + 46
        for k, d in self.HELP:
            p.text(x + 22, yy, k, c["acc_l"])
            p.text(x + 220, yy, d, c["text"])
            yy += 17


# ── действия ──────────────────────────────────────────────────────────────────

def run_in_term(title, cmd):
    """Команда в маленьком терминале: видно, что делается; пароль sudo — от пользователя."""
    script = ("printf '\\033]2;%s\\007'; echo \"$ %s\"; echo; %s; s=$?; echo; "
              "if [ $s -eq 0 ]; then echo '✓ готово'; else echo \"✗ не вышло (код $s)\"; fi; "
              "echo; printf 'Enter — закрыть '; read _" % (title.replace("'", ""), cmd.replace('"', '\\"'), cmd))
    subprocess.Popen(["kitty", "--class", TERM_ID, "--title", title, "-e", "sh", "-c", script],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)


def plan_cleanup(it):
    lines = [it["note"] + ".", "Освободится около %s." % human(it["size"])]
    if it.get("warn"):
        lines.append(it["warn"])
    if it.get("cmd"):
        lines.append("Нужен root: команда откроется в терминале, пароль sudo — ваш.")
        return {"title": "Очистить: %s?" % it["title"], "yes": "Clean", "lines": lines, "cmd": it["cmd"],
                "do": ("term", "Очистка: " + it["title"], it["cmd"]), "danger": bool(it.get("warn"))}
    return {"title": "Очистить: %s?" % it["title"], "yes": "Clean", "lines": lines,
            "do": ("clean", it), "danger": bool(it.get("warn"))}


def plan(view, action, item, version_row=None):
    """Что сделать и как спросить «точно?»: dict для окна подтверждения или None."""
    d = view.d
    pk, app = item["pkg"], item["app"]
    name = pk["name"] if pk else None
    q = shlex.quote(name) if name else ""
    aur = pk and pk["foreign"]
    if action == "remove":
        if not pk:
            if app and app["kind"] == "shortcut":
                return {"title": "Delete shortcut «%s»?" % app["name"], "yes": "Delete",
                        "lines": ["Удалится только ярлык (файл .desktop), программа останется.",
                                  "Копия ляжет в ~/.cache/applist/removed — можно вернуть."],
                        "do": ("shortcut", app["file"]), "danger": True}
            return None
        crit = bool(CRITICAL.match(name))
        lines = ["Пакет %s %s, освободится около %s." % (name, pk["version"], human(pk["size"]))]
        if len(pk["apps"]) > 1:
            lines.append("Вместе с ним пропадут: %s." % ", ".join(pk["apps"]))
        if pk["required"]:
            lines.append("Он нужен пакетам: %s — pacman откажет, пока они стоят." % ", ".join(sorted(pk["required"])[:5]))
        lines.append("Зависимости, которые больше никому не нужны, тоже удалятся (-s).")
        lines.append("Настройки в домашней папке останутся.")
        if crit:
            lines.insert(0, "ЭТО ЧАСТЬ СИСТЕМЫ: без него может не загрузиться система или сеанс.")
        cmd = "sudo pacman -Rs %s" % q
        return {"title": "Uninstall %s?" % item["name"], "yes": "Uninstall", "lines": lines, "cmd": cmd,
                "do": ("term", "Удаление " + name, cmd), "danger": True, "need": name if crit else None}
    if not pk:
        return None
    if action == "reinstall":
        cmd = ("yay -S %s" if aur else "sudo pacman -S %s") % q
        return {"title": "Reinstall %s?" % item["name"], "yes": "Reinstall", "cmd": cmd,
                "lines": ["Та же версия %s поставится заново поверх." % pk["version"],
                          "Помогает, если файлы программы повреждены или удалены вручную.",
                          "Настройки не трогаются."], "do": ("term", "Переустановка " + name, cmd)}
    if action == "update":
        new = d.ups.get(name)
        if not new:
            return None
        cmd = ("yay -S %s" if aur else "sudo pacman -Sy --needed %s") % q
        lines = ["%s → %s, только эта программа (без полного -Syu)." % (pk["version"], new)]
        if not aur:
            lines += ["Это частичное обновление: Arch официально поддерживает только полное.",
                      "Если программе нужны новые библиотеки, pacman подтянет их сам;",
                      "если что-то другое после этого сломается — сделайте полное sudo pacman -Syu."]
        return {"title": "Update %s?" % item["name"], "yes": "Update", "cmd": cmd, "lines": lines,
                "do": ("term", "Обновление " + name, cmd)}
    if action == "hold":
        on = name not in d.held
        cmd = "sudo python3 %s --hold %s %s" % (shlex.quote(os.path.abspath(__file__)), "add" if on else "del", q)
        lines = (["-Syu перестанет обновлять %s (IgnorePkg в /etc/pacman.conf)." % name,
                  "Нужно, чтобы откат не отменился следующим полным обновлением.",
                  "Снять — той же кнопкой (Unhold)."] if on else
                 ["%s снова будет обновляться вместе со всей системой." % name])
        return {"title": ("Hold %s?" if on else "Unhold %s?") % name, "yes": "Hold" if on else "Unhold",
                "cmd": cmd, "lines": lines, "do": ("term", ("Закрепить " if on else "Открепить ") + name, cmd)}
    if action == "version" and version_row:
        ver, src, _date, where, what = version_row
        if not what:
            return None
        if what == "update":
            return plan(view, "update", item)
        older = vercmp(ver, pk["version"]) < 0
        cmd = "sudo pacman -U %s" % shlex.quote(where)
        lines = ["%s %s → %s (%s)." % (name, pk["version"], ver, "из кэша на диске" if src == "cache" else "из Arch Archive, скачается")]
        if older:
            lines += ["Откат: старая версия встанет вместо текущей.",
                      "Следующее полное -Syu вернёт новую — чтобы не вернуло, после отката Hold (p)."]
            if pk["required"]:
                lines.append("Если ей не подойдут нынешние библиотеки, pacman откажет — это нормально.")
        return {"title": ("Roll back %s to %s?" if older else "Install %s %s?") % (name, ver),
                "yes": "Roll back" if older else "Install", "cmd": cmd, "lines": lines,
                "do": ("term", ("Откат " if older else "Установка ") + name, cmd), "danger": older}
    return None


# ── окно GTK ──────────────────────────────────────────────────────────────────

class AppListWindow(Gtk.ApplicationWindow):
    def __init__(self, app, tab="apps"):
        super().__init__(application=app, title="App list")
        self.data = Data()
        self.data.on_change = self.redraw
        self.view = View(self.data)
        self.view.tab = tab if tab in TABS else "apps"
        self.pending, self.pending_t, self.last_j = "", 0, 0
        self.set_decorated(False)
        self.set_resizable(True)                 # тянуть за края (07.10.2026)
        self.set_size_request(760, 520)
        self.drag_sb = None
        self.set_default_size(W, H)
        self.set_app_paintable(True)
        vis = self.get_screen().get_rgba_visual()
        if vis:
            self.set_visual(vis)
        self.area = Gtk.DrawingArea()
        self.area.connect("draw", self.on_draw)
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.SCROLL_MASK | Gdk.EventMask.SMOOTH_SCROLL_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.BUTTON_RELEASE_MASK
                             | Gdk.EventMask.BUTTON1_MOTION_MASK)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("button-release-event", self.on_release)
        self.area.connect("leave-notify-event", lambda *_: self.set_hover(None))
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("notify::is-active", self.on_active)
        GLib.timeout_add(1000, self.tick)

    def on_active(self, *_a):
        self.view.active = self.is_active()
        self.redraw()

    def redraw(self, *_a):
        self.area.queue_draw()
        return False

    def tick(self):
        if Data.db_stamp() != self.data.stamp:          # pacman что-то поменял — перечитать
            self.data.load()
            self.view.flash("список обновлён")
        if R.style_name() != self.view.style:
            self.view.reload_style()
        self.redraw()
        return True

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        cr.set_operator(cairo.OPERATOR_SOURCE)
        cr.set_source_rgba(0, 0, 0, 0)
        cr.paint()
        cr.set_operator(cairo.OPERATOR_OVER)
        self.view.draw(cr, a.width, a.height)

    def hit(self, x, y):
        for (hx, hy, hw, hh), key in reversed(self.view.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return key
        return None

    def set_hover(self, key):
        if key != self.view.hover:
            self.view.hover = key
            self.redraw()

    EDGE = 6

    def edge_at(self, x, y):
        a = self.area.get_allocation()
        e = self.EDGE
        l, r, t, b = x < e, x > a.width - e, y < e, y > a.height - e
        E = Gdk.WindowEdge
        return {(1, 0, 1, 0): E.NORTH_WEST, (0, 1, 1, 0): E.NORTH_EAST, (1, 0, 0, 1): E.SOUTH_WEST,
                (0, 1, 0, 1): E.SOUTH_EAST, (1, 0, 0, 0): E.WEST, (0, 1, 0, 0): E.EAST,
                (0, 0, 1, 0): E.NORTH, (0, 0, 0, 1): E.SOUTH}.get((l, r, t, b))

    def sb_drag(self, y):
        """Позиция мыши на дорожке полосы → прокрутка."""
        v = self.view
        which = self.drag_sb
        top, track, th, span = getattr(v, "sb", {}).get(which, (0, 1, 1, 0))
        frac = max(0.0, min(1.0, (y - self.drag_off - top) / max(1, track - th)))
        if which == "list":
            v.scroll[v.tab] = round(frac * span)
        else:
            v.scroll["system"] = round(frac * span)
        self.redraw()

    def on_motion(self, _w, ev):
        if self.drag_sb:
            self.sb_drag(ev.y)
            return True
        self.set_hover(self.hit(ev.x, ev.y))
        return True

    def on_release(self, _w, ev):
        if self.drag_sb:
            self.drag_sb = None
            self.view.free_scroll = False
            self.redraw()
        return True

    def on_click(self, _w, ev):
        edge = self.edge_at(ev.x, ev.y) if self.view.mode == "normal" and ev.button == 1 else None
        if edge is not None:
            self.begin_resize_drag(edge, ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        key = self.hit(ev.x, ev.y)
        if isinstance(key, tuple) and key[0] == "sbar" and ev.button == 1:
            v = self.view
            self.drag_sb = key[1]
            top, track, th, span = v.sb.get(key[1], (0, 1, 1, 0))
            cur = v.scroll[v.tab] if key[1] == "list" else v.scroll["system"]
            ty = top + (track - th) * cur / max(1, span)
            # схватили ползунок — держим за ту же точку; мимо — ползунок встаёт центром под мышь
            self.drag_off = ev.y - ty if ty <= ev.y <= ty + th else th / 2
            v.free_scroll = True
            self.sb_drag(ev.y)
            return True
        if key is None and ev.button == 1 and self.view.mode == "normal" and ev.y < self.view.body()[0] - 8:
            # пустое место шапки — перетащить окно, как у Настроек
            self.begin_move_drag(ev.button, int(ev.x_root), int(ev.y_root), ev.time)
            return True
        v = self.view
        if v.mode == "confirm":
            if key == ("cf", "yes"):
                self.confirm_yes()
            elif key == ("cf", "no") or key is None:
                self.confirm_no()
            self.redraw()
            return True
        if v.mode == "help":
            v.mode = "normal"
        elif key == "close":
            self.close()
        elif key == "search":
            v.mode = "search"
        elif isinstance(key, tuple):
            kind, val = key
            if kind == "tab":
                self.set_tab(val)
            elif kind == "row":
                v.sel[v.tab], v.focus = val, "list"
                v.vsel = 0
                if ev.type == Gdk.EventType._2BUTTON_PRESS:
                    self.do("open")
            elif kind == "act":
                self.do(val)
            elif kind == "crow":
                v.sel["cleanup"] = val
            elif kind == "clean":
                v.sel["cleanup"] = val
                self.clean_selected()
            elif kind == "hdr" and val == "sort":
                self.cycle_sort()
            elif kind == "hdr" and val == "ups":
                self.toggle_ups()
            elif kind == "ver":
                if v.focus == "versions" and v.vsel == val:
                    self.do("version")
                v.focus, v.vsel = "versions", val
        self.redraw()
        return True

    def on_scroll(self, _w, ev):
        v = self.view
        dy = ev.delta_y if ev.direction == Gdk.ScrollDirection.SMOOTH else (
            -1 if ev.direction == Gdk.ScrollDirection.UP else 1)
        step = 1 if dy > 0 else -1
        if v.tab == "system":
            v.scroll["system"] += step * 34
        elif v.tab == "cleanup":
            v.sel["cleanup"] = max(0, v.sel["cleanup"] + step)
        elif v.focus == "versions":
            v.vsel = max(0, v.vsel + step)
        else:
            self.move(step)
        self.redraw()
        return True

    def set_tab(self, t):
        v = self.view
        v.tab, v.focus = t, "list"
        if t == "system" and v.d.info is None:
            v.d.fetch_info()

    def clean_selected(self):
        v = self.view
        items = getattr(v.d, "clean", None) or []
        if not items:
            return
        it = items[max(0, min(v.sel["cleanup"], len(items) - 1))]
        if it.get("block"):
            v.flash(it["note"])
            return
        v.confirm, v.typed, v.mode = plan_cleanup(it), "", "confirm"

    def cycle_sort(self):
        v = self.view
        v.sort = {"name": "size", "size": "date", "date": "name"}[v.sort]
        v.sel[v.tab], v.scroll[v.tab] = 0, 0
        v.flash("сортировка: " + {"name": "по имени", "size": "по размеру (крупные сверху)",
                                  "date": "по дате изменения (свежие сверху)"}[v.sort])

    def toggle_ups(self):
        v = self.view
        v.only_ups = not v.only_ups
        v.sel[v.tab], v.scroll[v.tab] = 0, 0
        v.flash("только с обновлениями" if v.only_ups else "все программы")

    def move(self, step, to=None):
        v = self.view
        if v.focus == "versions":
            v.vsel = max(0, v.vsel + step) if to is None else (0 if to == 0 else 10 ** 6)
            return
        n = len(v.items())
        cur = v.sel[v.tab]
        v.sel[v.tab] = max(0, min(n - 1, (cur + step) if to is None else (0 if to == 0 else n - 1)))
        v.vsel = 0

    # ── действия ──
    def do(self, action):
        v = self.view
        if v.tab == "system":
            return
        item = v.current()
        if not item:
            return
        if action == "open":
            app = item["app"]
            if not app and item["pkg"]:
                app = next((a for a in v.d.apps if a["pkg"] == item["pkg"]["name"]), None)
            if not app:
                v.flash("у пакета нет ярлыка — это не программа с окном")
                return
            try:
                Gio.DesktopAppInfo.new_from_filename(app["file"]).launch([], None)
                v.flash("запускаю %s" % app["name"])
            except Exception as e:
                v.flash("не открылось: %s" % e)
            return
        if action == "archive":
            pk = item["pkg"]
            if not pk or pk["foreign"]:
                v.flash("в Arch Archive только пакеты из репозиториев")
                return
            v.d.fetch_archive(pk["name"])
            v.focus = "versions"
            return
        row = None
        if action == "version":
            rows = v.d.versions(item["pkg"]["name"]) if item["pkg"] else []
            if not rows:
                return
            row = rows[max(0, min(v.vsel, len(rows) - 1))]
            if not row[4]:
                v.flash("эта версия уже стоит")
                return
        cf = plan(v, action, item, row)
        if cf is None:
            v.flash({"update": "обновлений нет — проверить: R"}.get(action, "нечего делать"))
            return
        v.confirm, v.typed, v.mode = cf, "", "confirm"

    def confirm_yes(self):
        v = self.view
        cf = v.confirm
        if cf.get("need") and v.typed.strip() != cf["need"]:
            v.flash("введите имя пакета точно: %s" % cf["need"])
            return
        v.mode, v.confirm, v.typed = "normal", None, ""
        what = cf["do"]
        if what[0] == "term":
            run_in_term(what[1], what[2])
            v.flash("открыл терминал: %s" % what[2])
            if v.tab == "cleanup":                    # после терминала — пересчитать
                GLib.timeout_add_seconds(20, lambda: (v.d.fetch_cleanup(), False)[1])
        elif what[0] == "clean":
            it = what[1]

            def job():
                msg = cleanup_run(it)
                GLib.idle_add(lambda: (v.flash("%s: %s" % (it["title"], msg), 5), v.d.fetch_cleanup(), self.redraw()))
            threading.Thread(target=job, daemon=True).start()
            v.flash("чищу: %s…" % it["title"])
        elif what[0] == "shortcut":
            os.makedirs(os.path.join(CACHE, "removed"), exist_ok=True)
            try:
                os.replace(what[1], os.path.join(CACHE, "removed", os.path.basename(what[1])))
                v.flash("ярлык убран, копия в ~/.cache/applist/removed")
                v.d.load()
            except OSError as e:
                v.flash("не вышло: %s" % e)

    def confirm_no(self):
        v = self.view
        v.mode, v.confirm, v.typed = "normal", None, ""
        v.flash("отменено")

    def copy(self, text):
        try:
            subprocess.run(["wl-copy"], input=text, text=True, timeout=3)
            self.view.flash("скопировано")
        except (OSError, subprocess.SubprocessError):
            self.view.flash("wl-copy не сработал")

    # ── клавиши ──
    def on_key(self, _w, ev):
        v = self.view
        kc = ev.hardware_keycode
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(ev.state & Gdk.ModifierType.SHIFT_MASK)
        ch = R.KEYS.get(kc, "")
        if shift and ch:
            ch = ch.upper() if ch.isalpha() else {"/": "?", ";": ":", "1": "!"}.get(ch, ch)
        name = Gdk.keyval_name(ev.keyval) or ""
        uni = chr(Gdk.keyval_to_unicode(ev.keyval)) if Gdk.keyval_to_unicode(ev.keyval) else ""
        if v.mode == "help":
            v.mode = "normal"
        elif v.mode == "confirm":
            self.key_confirm(ch, name, uni, ctrl)
        elif v.mode == "search":
            self.key_search(ch, name, uni, ctrl)
        else:
            self.key_normal(ch, name, ctrl, shift)
        self.redraw()
        return True

    def key_confirm(self, ch, name, uni, ctrl):
        v = self.view
        cf = v.confirm
        if name == "Escape":
            self.confirm_no()
        elif cf.get("need"):                          # системный пакет: ввести имя
            if name in ("Return", "KP_Enter"):
                self.confirm_yes()
            elif name == "BackSpace":
                v.typed = v.typed[:-1]
            elif uni and uni.isprintable():
                v.typed += uni
        elif ch == "y" or name in ("Return", "KP_Enter"):
            self.confirm_yes()
        elif ch == "n" or ch == "q":
            self.confirm_no()

    def key_search(self, ch, name, uni, ctrl):
        v = self.view
        now = time.monotonic()
        if name == "Escape":
            v.query, v.mode = "", "normal"
            v.flash("поиск сброшен")
            return
        done = name in ("Return", "KP_Enter") or (ctrl and ch == "e")
        if ch == "j" and v.query[-1:] in ("j", "о") and now - self.last_j < 0.6:
            v.query, done = v.query[:-1], True
        if done:
            v.mode = "normal"
            return
        if name == "BackSpace":
            v.query = v.query[:-1]
        elif ctrl and ch == "w":
            v.query = v.query.rstrip().rpartition(" ")[0]
        elif uni and uni.isprintable():
            v.query += uni
            if ch == "j":
                self.last_j = now
        v.sel[v.tab], v.scroll[v.tab], v.vsel = 0, 0, 0

    def key_normal(self, ch, name, ctrl, shift):
        v = self.view
        now = time.monotonic()
        pend = self.pending if now - self.pending_t < 0.8 else ""
        self.pending = ""
        page = max(1, v.list_rows() // 2)
        if v.tab == "cleanup":
            n = len(getattr(v.d, "clean", None) or [])
            if ch == "j" or name == "Down":
                v.sel["cleanup"] = min(max(0, n - 1), v.sel["cleanup"] + 1)
                return
            if ch == "k" or name == "Up":
                v.sel["cleanup"] = max(0, v.sel["cleanup"] - 1)
                return
            if name in ("Return", "KP_Enter") or ch == "c":
                self.clean_selected()
                return
            if ch == "R":
                v.d.fetch_cleanup()
                return
        if v.tab == "system":
            step = 34
            if ch == "j" or name == "Down":
                v.scroll["system"] += step
            elif ch == "k" or name == "Up":
                v.scroll["system"] -= step
            elif ctrl and ch == "d":
                v.scroll["system"] += 300
            elif ctrl and ch == "u":
                v.scroll["system"] -= 300
            elif ch == "G":
                v.scroll["system"] = 10 ** 6
            elif pend == "g" and ch == "g":
                v.scroll["system"] = 0
            elif ch == "y":
                if v.d.info:
                    self.copy(info_text(v.d.info))
                return
            elif ch == "R":
                v.d.info = None
                v.d.fetch_info()
                return
            elif ch in ("g",):
                self.pending, self.pending_t = ch, now
                return
        if pend == "g" and ch == "t":
            self.set_tab(TABS[(TABS.index(v.tab) + 1) % len(TABS)])
        elif pend == "g" and ch == "T":
            self.set_tab(TABS[(TABS.index(v.tab) - 1) % len(TABS)])
        elif pend == "g" and ch == "g":
            self.move(0, to=0)
        elif pend == "d" and ch == "d":
            self.do("remove")
        elif ch in ("g", "d") and not ctrl and v.tab != "system":
            self.pending, self.pending_t = ch, now
        elif ch == "g":
            self.pending, self.pending_t = ch, now
        elif name in ("Tab", "ISO_Left_Tab") or ch in ("L", "H"):
            d = -1 if (name == "ISO_Left_Tab" or ch == "H") else 1
            self.set_tab(TABS[(TABS.index(v.tab) + d) % len(TABS)])
        elif ch in ("1", "2", "3", "4"):
            self.set_tab(TABS[int(ch) - 1])
        elif v.tab in ("system", "cleanup"):
            if ch in ("q",) or name == "Escape":
                self.close()
            elif ch == "?":
                v.mode = "help"
        elif ch == "j" or name == "Down":
            self.move(1)
        elif ch == "k" or name == "Up":
            self.move(-1)
        elif ctrl and ch == "d":
            self.move(page)
        elif ctrl and ch == "u":
            self.move(-page)
        elif ch == "G" or name == "End":
            self.move(0, to=-1)
        elif name == "Home":
            self.move(0, to=0)
        elif ch == "l" or name in ("Right",):
            if v.current() and v.current()["pkg"]:
                v.focus = "versions"
        elif name in ("Return", "KP_Enter"):
            if v.focus == "versions":
                self.do("version")
            elif v.current() and v.current()["pkg"]:
                v.focus = "versions"
            else:
                self.do("open")
        elif ch == "h" or name == "Left":
            v.focus = "list"
        elif ch == "/":
            v.mode = "search"
        elif ch == "o":
            self.do("open")
        elif ch == "u":
            self.do("update")
        elif ch == "r":
            self.do("reinstall")
        elif ch == "D":
            self.do("remove")
        elif ch == "p":
            self.do("hold")
        elif ch == "A":
            self.do("archive")
        elif ch == "R":
            threading.Thread(target=v.d.updates, args=(True,), daemon=True).start()
            v.flash("проверяю обновления…")
        elif ch == "s":
            self.cycle_sort()
        elif ch == "U":
            self.toggle_ups()
        elif ch == "a" and v.tab == "packages":
            v.all_pkgs = not v.all_pkgs
            v.sel["packages"] = 0
        elif ch == "y":
            it = v.current()
            if it:
                self.copy(it["pkg"]["name"] if it["pkg"] else it["name"])
        elif ch == "?":
            v.mode = "help"
        elif name == "Escape":
            if v.focus == "versions":
                v.focus = "list"
            elif v.query:
                v.query = ""
                v.flash("поиск сброшен")
            else:
                self.close()
        elif ch == "q":
            self.close()


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        args = cl.get_arguments()[1:]
        tab = args[0] if args and args[0] in TABS else None
        if self.win is None:
            self.win = AppListWindow(self, tab or "apps")
            self.win.connect("destroy", lambda *_: setattr(self, "win", None))
            self.win.show_all()
        elif self.win.is_active() and not tab:      # бинд — переключатель: второй раз закрывает
            self.win.close()
            return 0
        else:
            self.win.view.reload_style()
            if tab:
                self.win.set_tab(tab)
        if self.win:
            self.win.present()
        return 0


def shot(path, tab="apps", sel=0, focus="list", confirm=None, style=None, query="", mode=None, scroll=0):
    """PNG без окна — для проверок вида."""
    d = Data(background=False)
    foreign_and_repos(d.pkgs)
    v = View(d)
    if style:
        v.style, v.c = style, R.colors(style)
    v.tab, v.focus, v.query = tab, focus, str(query)
    v.sel[tab] = int(sel)
    v.scroll["system"] = int(scroll)
    if tab == "system":
        d.info = system_info(d.pkgs)
    if tab == "cleanup":
        d.clean = cleanup_items()
    if confirm:
        cf = plan(v, confirm, v.current())
        if cf:
            v.confirm, v.mode = cf, "confirm"
    if mode:
        v.mode = mode
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(surf)
    v.draw(cr, W, H)
    surf.write_to_png(path)
    return W, H


if __name__ == "__main__":
    a = sys.argv[1:]
    if a[:1] == ["--hold"] and len(a) == 3 and a[1] in ("add", "del"):
        sys.exit(hold_edit(a[1], a[2]))
    if a[:1] == ["--info"]:
        print(info_text(system_info()))
        sys.exit(0)
    if len(a) > 1 and a[0] == "--shot":
        kw = {}
        for x in a[2:]:
            k, _, val = x.partition("=")
            kw[k] = val
        print(shot(a[1], **kw))
        sys.exit(0)
    GLib.set_prgname(APP_ID)
    sys.exit(App().run(sys.argv))
