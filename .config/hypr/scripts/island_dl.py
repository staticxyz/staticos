#!/usr/bin/env python3
"""Загрузки и отправка для островка. 20.10.2026.

Просьба: «показывать загрузки, если что-то скачивается. Вообще всё в системе… в мини-островке
(не раскрывшемся). Отдельный блок делать не нужно». Потом: «не прям все загрузки (видео в
YouTube — нет), а файловые: скачать из интернета к себе на ПК или загрузить что-то в
интернет — в браузере, в Telegram… Или банально загрузки из Steam. Анимация — квадратные
полоски, которые заполняются; название, чтобы знать, что именно; снизу — проценты, сколько
из скольки, скорость и сколько осталось».

Здесь только счёт (опрос в потоке); рисует island.py (paint_dl). Откуда
------------------------------------------------------------------------
* Zen — точно: live-theme.js (installDownloads) пишет список загрузок браузера в
  $XDG_RUNTIME_DIR/jarvis-zen-dl.json: имя, скачано, всего, скорость;
* Steam — steamapps/downloading/<appid> + appmanifest (BytesDownloaded/BytesToDownload);
* папка «Загрузки» (два уровня): растущий файл — Helium (.crdownload), Telegram, торренты;
  всего не знают — только размер и скорость;
* curl, wget, yt-dlp, aria2c, git… в любой папке: растущий файл, открытый ими на запись;
* pacman/paru/yay — свои файлы качает от alpm, их не видно: пока pacman запущен и сеть
  принимает больше DL_NET_MIN — «пакеты»;
* отправка (Telegram, браузер, git push, scp…) — по ss: программа шлёт больше UP_MIN
  два опроса подряд. Что именно шлёт, система не говорит — пишем программу.
Видео и музыка в браузере сюда не попадают: они не пишут файлов и почти ничего не шлют.

    island_dl.py              один замер за 3 с — что сейчас качается (проверка)
"""
import json
import os
import re
import subprocess
import time

HOME = os.path.expanduser("~")
RUN = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
ZEN_DL = os.path.join(RUN, "jarvis-zen-dl.json")
ZEN_FRESH = 6.0          # файл Zen старше — браузер закрыт или завис
GROW_KEEP = 5.0          # столько секунд после последнего роста файл считается качающимся
PART = (".part", ".crdownload", ".download", ".partial", ".aria2", ".ytdl")
DL_COMM = {"curl", "wget", "wget2", "yt-dlp", "youtube-dl", "aria2c", "axel", "gallery-dl",
           "git-remote-http", "git-remote-https", "rsync", "scp", "rclone", "transmission-da",
           "qbittorrent", "qbittorrent-nox"}
PKG_COMM = {"pacman", "paru", "yay"}
DL_NET_MIN = 64 * 1024   # байт/с: столько принимает сеть, пока pacman «качает»
UP_MIN = 150 * 1024      # байт/с: отправка от этого — «выгрузка»
UP_KEEP = 6.0            # столько секунд после последней быстрой отправки она ещё идёт
STEAM_LIBS = (os.path.join(HOME, ".local/share/Steam"),)
APP_NAME = {"zen": "Zen", "zen-bin": "Zen", "firefox": "Firefox", "helium": "Helium", "chromium": "Chromium",
            "chrome": "Chrome", "telegram-deskto": "Telegram", "Telegram": "Telegram", "Discord": "Discord",
            "discord": "Discord", "Vesktop": "Discord", "vesktop": "Discord", "steam": "Steam",
            "git-remote-http": "git push", "git-remote-https": "git push", "ssh": "ssh", "scp": "scp",
            "rsync": "rsync", "rclone": "rclone", "curl": "curl", "obsidian": "Obsidian"}
UP_SKIP = {"node", "sshd"}   # свои службы — не «выгрузка»


def download_dir():
    try:
        d = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        d = ""
    return d if d and d != HOME and os.path.isdir(d) else os.path.join(HOME, "Downloads")


def steam_libs():
    libs = []
    for base in STEAM_LIBS:
        try:
            txt = open(os.path.join(base, "steamapps", "libraryfolders.vdf")).read()
        except OSError:
            continue
        libs += re.findall(r'"path"\s+"([^"]+)"', txt) or [base]
    return list(dict.fromkeys(libs))


def acf_val(txt, key):
    m = re.search(r'"%s"\s+"(\d+)"' % key, txt)
    return int(m.group(1)) if m else 0


def net_rx():
    tot = 0
    try:
        for line in open("/proc/net/dev").read().splitlines()[2:]:
            name, data = line.split(":", 1)
            if name.strip() != "lo":
                tot += int(data.split()[0])
    except (OSError, ValueError, IndexError):
        pass
    return tot


def item(name, cur, total, rate, src, path=None, up=False):
    pr = cur / total if total else None
    return {"name": name, "cur": cur, "total": total or 0, "pr": pr, "rate": rate, "src": src,
            "path": path, "up": up}


class Downloads:
    """scan() раз в несколько секунд → список [{"name", "cur", "total", "pr", "rate", "src", "path", "up"}]."""

    def __init__(self):
        self.dl_dir = download_dir()
        self.libs = steam_libs()
        self.uid = os.getuid()
        self.size = {}           # путь → (размер, когда последний раз рос, скорость)
        self.steam = {}          # appid → (скачано, когда менялось, скорость)
        self.socks = {}          # сокет → отправлено (bytes_acked)
        self.up = {}             # программа → {"sent", "last", "rate", "hits"}
        self.rx = None           # (байты сети, время)
        self.t = None

    def grow(self, path, size, now, part):
        """Файл качается: вырос с прошлого замера (или .part, тронутый только что)."""
        old = self.size.get(path)
        if old is None:
            try:
                fresh = part and now - os.stat(path).st_mtime < GROW_KEEP
            except OSError:
                fresh = False
            self.size[path] = (size, now if fresh else 0.0, 0.0)
            return fresh, 0.0
        osize, last, rate = old
        if size > osize:
            rate = (size - osize) / max(0.5, now - (self.t or now))
            last = now
        elif now - last >= GROW_KEEP:
            rate = 0.0
        self.size[path] = (size, last, rate)
        return now - last < GROW_KEEP, rate

    def zen(self, now, seen, out):
        try:
            if now - os.stat(ZEN_DL).st_mtime > ZEN_FRESH:
                return
            d = json.load(open(ZEN_DL))
        except (OSError, ValueError):
            return
        for z in d.get("items") or ():
            path = z.get("path") or ""
            seen.update((path, path + ".part"))
            out.append(item(os.path.basename(path) or "Zen", int(z.get("cur") or 0), int(z.get("total") or 0),
                            float(z.get("speed") or 0), "zen", path))

    def files(self, now, seen, out):
        stack = [(self.dl_dir, 0)]
        while stack:
            d, depth = stack.pop()
            try:
                it = list(os.scandir(d))
            except OSError:
                continue
            for e in it:
                if e.name.startswith(".") or e.path in seen:
                    continue
                try:
                    if e.is_dir(follow_symlinks=False):
                        if depth < 1:
                            stack.append((e.path, depth + 1))
                        continue
                    if not e.is_file(follow_symlinks=False):
                        continue
                    size = e.stat().st_size
                except OSError:
                    continue
                seen.add(e.path)
                live, rate = self.grow(e.path, size, now, e.name.endswith(PART))
                if live:
                    name = e.name
                    for s in PART:
                        if name.endswith(s):
                            name = name[:-len(s)]
                    out.append(item(name, size, 0, rate, "file", e.path))

    def procs(self, now, seen, out):
        """curl/wget/yt-dlp…: растущие файлы, открытые ими на запись; pacman — по сети."""
        pkg = False
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                comm = open("/proc/%s/comm" % pid).read().strip()
            except OSError:
                continue
            if comm in PKG_COMM:
                pkg = pkg or comm
                continue
            if comm not in DL_COMM:
                continue
            try:
                if os.stat("/proc/" + pid).st_uid != self.uid:
                    continue
                fds = os.listdir("/proc/%s/fd" % pid)
            except OSError:
                continue
            for fd in fds:
                try:
                    path = os.readlink("/proc/%s/fd/%s" % (pid, fd))
                    if not path.startswith("/") or path.startswith(("/dev/", "/proc/", "/sys/")) or path in seen:
                        continue
                    flags = 0
                    for line in open("/proc/%s/fdinfo/%s" % (pid, fd)):
                        if line.startswith("flags:"):
                            flags = int(line.split()[1], 8)
                            break
                    if not flags & 3:            # только на чтение
                        continue
                    st = os.stat(path)
                except (OSError, ValueError):
                    continue
                if not os.path.isfile(path):
                    continue
                seen.add(path)
                live, rate = self.grow(path, st.st_size, now, False)
                if live:
                    out.append(item(os.path.basename(path), st.st_size, 0, rate, comm, path))
        return pkg

    def steam_dl(self, now, out):
        for lib in self.libs:
            dd = os.path.join(lib, "steamapps", "downloading")
            try:
                apps = [a for a in os.listdir(dd) if a.isdigit()]
            except OSError:
                continue
            for app in apps:
                try:
                    txt = open(os.path.join(lib, "steamapps", "appmanifest_%s.acf" % app)).read()
                except OSError:
                    continue
                got, need = acf_val(txt, "BytesDownloaded"), acf_val(txt, "BytesToDownload")
                old = self.steam.get(app)
                if old is None or got != old[0]:
                    rate = 0.0 if old is None else max(0.0, (got - old[0]) / max(0.5, now - old[1]))
                    self.steam[app] = (got, now if old is not None else 0.0, rate)
                _g, last, rate = self.steam[app]
                if need and got < need and now - last < 60:
                    m = re.search(r'"name"\s+"([^"]+)"', txt)
                    out.append(item(m.group(1) if m else "Steam " + app, got, need, rate, "steam",
                                    os.path.join(lib, "steamapps", "common")))

    def uploads(self, now, out):
        """Отправка: сумма bytes_acked по TCP-сокетам программы (ss), без своих локальных."""
        try:
            txt = subprocess.run(["ss", "-tinpH", "state", "established"], capture_output=True, text=True,
                                 timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return
        sent, socks, key, app = {}, {}, None, None
        for line in txt.splitlines():
            if not line.startswith(("\t", " ")):
                f = line.split()
                m = re.search(r'users:\(\("([^"]+)"', line)
                peer = f[3] if len(f) > 3 else ""
                local = peer.startswith(("127.", "[::1]", "[::ffff:127.")) or peer.startswith("192.168.") \
                    and f[2].startswith("192.168.")
                key, app = (f[2] + ">" + peer, m.group(1)) if m and not local else (None, None)
                continue
            m = re.search(r"bytes_acked:(\d+)", line)
            if key and m and app not in UP_SKIP:
                b = int(m.group(1))
                socks[key] = b
                old = self.socks.get(key)
                if old is not None and b > old:
                    sent[app] = sent.get(app, 0) + b - old
        self.socks = socks
        dt = max(0.5, now - (self.t or now))
        for app, b in sent.items():
            u = self.up.setdefault(app, {"sent": 0, "last": 0.0, "rate": 0.0, "hits": 0})
            rate = b / dt
            if rate >= UP_MIN:
                u["hits"] += 1
                u["last"] = now
                u["sent"] += b
                u["rate"] = rate
            elif u["hits"]:
                u["sent"] += b
                u["rate"] = rate
        for app in list(self.up):
            u = self.up[app]
            if now - u["last"] >= UP_KEEP:
                del self.up[app]
            elif u["hits"] >= 2:
                out.append(item(APP_NAME.get(app, app), u["sent"], 0, u["rate"], app, None, up=True))

    def scan(self, now=None):
        now = time.time() if now is None else now
        out, seen = [], set()
        self.zen(now, seen, out)
        self.steam_dl(now, out)
        self.files(now, seen, out)
        pkg = self.procs(now, seen, out)
        rx = net_rx()
        net = 0.0
        if self.rx and now > self.rx[1]:
            net = max(0.0, (rx - self.rx[0]) / (now - self.rx[1]))
        self.rx = (rx, now)
        if pkg and net >= DL_NET_MIN:
            out.append(item("пакеты %s" % pkg, 0, 0, net, "pkg"))
        self.uploads(now, out)
        for p in [p for p in self.size if p not in seen]:
            del self.size[p]
        self.t = now
        return out


def summary(items):
    """Сводка для островка: первая загрузка с процентами (иначе первая), сколько ещё."""
    if not items:
        return None
    main = next((i for i in items if i["pr"] is not None and not i["up"]), None) or items[0]
    return dict(main, n=len(items))


def human(n):
    for u in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024 or u == "ГБ":
            return (("%.0f %s" if n >= 100 or u == "Б" else "%.1f %s") % (n, u)).replace(".", ",")
        n /= 1024.0
    return ""


def dur(s):
    s = int(s)
    if s >= 3600:
        return "%d ч %02d мин" % (s // 3600, s % 3600 // 60)
    if s >= 600:
        return "%d мин" % (s // 60)
    if s >= 60:
        return "%d мин %02d с" % (s // 60, s % 60)
    return "%d с" % s


def stats(d):
    """Строка под полосой: «72% · 1 КБ из 1 КБ · 0 КБ/с · ещё 4 с»."""
    parts = []
    if d.get("up"):
        parts.append("отправлено %s" % human(d["cur"]))
    elif d.get("total"):
        parts.append("%d%%" % int(100 * min(1.0, d["cur"] / d["total"])))
        parts.append("%s из %s" % (human(d["cur"]), human(d["total"])))
    elif d.get("cur"):
        parts.append(human(d["cur"]))
    parts.append(human(d.get("rate") or 0) + "/с")
    if d.get("total") and d.get("rate", 0) > 1:
        parts.append("ещё " + dur((d["total"] - d["cur"]) / d["rate"]))
    return " · ".join(parts)


if __name__ == "__main__":
    D = Downloads()
    D.scan()
    time.sleep(3)
    items = D.scan()
    print("папка:", D.dl_dir, "| Steam:", D.libs, "| Zen:", ZEN_DL, os.path.exists(ZEN_DL))
    for i in items:
        print(" ", "↑" if i["up"] else "↓", i["src"], i["name"], "—", stats(i))
    print("сводка:", summary(items) or "ничего не качается")
