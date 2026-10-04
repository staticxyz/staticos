#!/usr/bin/env python3
"""Караоке в баре: текущая строка песни, в такт воспроизведению (30.09.2026).

Запуск без аргументов — модуль waybar в непрерывном режиме: по строке JSON
{"text","tooltip","class"} на каждое ВИДИМОЕ изменение. Пустой text — модуль скрыт.

    lyrics_bar.py                  модуль для waybar (живёт, пока жив бар)
    lyrics_bar.py on|off|toggle    включить/выключить (флаг state/lyrics-off)
    lyrics_bar.py status           включено ли и что играет сейчас
    lyrics_bar.py lookup АРТИСТ НАЗВАНИЕ [СЕКУНДЫ] [АЛЬБОМ]   проверить поиск текста

Как устроено, чтобы не есть процессор:
  * Никаких playerctl в цикле. Плееры слушаем прямо по D-Bus (Gio): сигналы
    PropertiesChanged (статус, метаданные) и Seeked (перемотка) приходят сами.
  * Позицию спрашиваем у плеера один раз при событии и потом раз в 2 с, а между
    опросами досчитываем по монотонным часам. Таймер заводится ровно на момент
    следующего видимого изменения (следующее слово или строка), не чаще 8 раз/с.
    На паузе таймеров нет вовсе, только секундная проверка флага.
  * Тексты — с lrclib.net (только синхронизированные, LRC), в фоновом потоке;
    ответ, включая «текста нет», кладётся в ~/.cache/jarvis/lyrics/<sha1>.json.

Песня или видео — решает личность плеера (MPRIS Identity), а не заголовок:
  * браузеры (zen, firefox, librewolf, helium, chromium, mercury…) пропускаются —
    у YouTube-видео тоже есть «артист» (имя канала), по нему не отличить. Исключение —
    вкладка музыкального сервиса, если браузер отдаёт xesam:url (music.youtube.com,
    open.spotify.com, music.yandex.*, soundcloud…);
  * Яндекс Музыка — Electron, на шине она «chromium.instanceNNN», как helium, но
    Identity у неё «YandexMusic»: по этому и отличаем (проверено 30.09.2026);
  * у любого плеера нужны название, артист и длина от 30 с до 15 мин;
  * и последний фильтр — lrclib: без синхронного текста с длиной ±3 с строка не
    появится.
"""
import hashlib
import html
import json
import os
import re
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

HOME = os.path.expanduser("~")
FLAG = os.path.join(HOME, ".config/hypr/state/lyrics-off")
CACHE_DIR = os.path.join(HOME, ".cache/jarvis/lyrics")
STATUS_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-lyrics.json")
COLORS_CSS = os.path.join(HOME, ".cache/matugen/colors.css")  # @primary = акцент обоев

API = "https://lrclib.net/api"
UA = "jarvis-lyrics-bar/1.0 (personal waybar module; lrclib.net client)"

MAX_LEN = 30          # символов в баре; длинная строка прокручивается окном
                      # (30, а не 48: строка встаёт на место заголовка окна, а до pomo
                      # там всего ~27–40 знаков — замеры в bar_window_title.py)
ACTIVE_FILE = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "jarvis-lyrics-on")
MIN_STEP = 0.125      # не чаще 8 обновлений в секунду
RESYNC = 2.0          # раз в столько секунд сверяем позицию с плеером
LEAD = 0.0            # сдвиг строк раньше звука, с (если покажется, что опаздывают)
DIM_ALPHA = "70%"     # непропетая часть строки
NEG_TTL = 3 * 86400   # «текста нет» перепроверяем через трое суток
GAP_TEXT = "♪"   # ♪ — проигрыш / вступление

BROWSERS = {"firefox", "zen", "librewolf", "chromium", "chrome", "helium", "brave",
            "thorium", "vivaldi", "opera", "edge", "floorp", "waterfox", "epiphany",
            "falkon", "qutebrowser", "mercury", "midori", "browser", "mozilla"}
MUSIC_HOSTS = ("music.youtube.com", "open.spotify.com", "music.yandex.", "soundcloud.com",
               "deezer.com", "music.apple.com", "tidal.com", "bandcamp.com")
IGNORED = ("blanket", "playerctld")  # playerctld — зеркало другого плеера


# ─────────────────────────── тексты: lrclib и кэш ───────────────────────────

def _norm(s):
    s = unicodedata.normalize("NFKC", s or "").lower().replace("ё", "е")
    s = re.sub(r"[\(\[].*?[\)\]]", " ", s)          # (feat. …), [Remastered]
    s = re.sub(r"\b(feat|ft|featuring)\b.*", " ", s)
    s = re.sub(r"[^\w]+", " ", s)
    return " ".join(s.split())


def split_artists(artist):
    parts = re.split(r"\s*(?:,|&|/|;| и | x | feat\.? | ft\.? | featuring )\s*", artist or "",
                     flags=re.I)
    return [p.strip() for p in parts if p.strip()]


def cache_key(artist, title, dur):
    raw = "%s\n%s\n%d" % (_norm(artist), _norm(title), int(round(dur or 0)))
    return hashlib.sha1(raw.encode()).hexdigest()


def _http_json(path, params):
    url = "%s/%s?%s" % (API, path, urllib.parse.urlencode(params))
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Lrclib-Client": UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


# Транслит (01.10.2026): Яндекс Музыка отдаёт русские названия латиницей
# («Skazhi mne/Asa du»), а в lrclib они кириллицей («Скажи мне/Asa du») — и
# текст не находился. Сравнение идёт ещё и по «грубому ключу»: кириллица
# переведена в латиницу, похожие буквы и сочетания склеены (y/j/i, kh/h…).
_TR = dict(zip("абвгдежзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "i", "k", "l", "m", "n", "o", "p",
                "r", "s", "t", "u", "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _loose(s):
    s = "".join(_TR.get(c, c) for c in _norm(s))
    for a, b in (("shch", "sch"), ("kh", "h"), ("ks", "x"), ("iy", "i"), ("yi", "i"),
                 ("y", "i"), ("j", "i"), ("w", "v"), ("ts", "c"), ("tz", "c")):
        s = s.replace(a, b)
    return " ".join(s.split())


def _title_ok(ours, theirs):
    for a, b in ((_norm(ours), _norm(theirs)), (_loose(ours), _loose(theirs))):
        if a and (a == b or (len(a) > 3 and (a in b or b in a))):
            return True
    return False


def _artist_ok(ours, theirs):
    t, tl = _norm(theirs), _loose(theirs)
    return any((_norm(x) and _norm(x) in t) or (_loose(x) and _loose(x) in tl)
               for x in split_artists(ours))


# Запасной источник — Яндекс Музыка (приложение с портом отладки 9223, тем же, что
# у кнопки «Нравится», см. player_like.py). Запросы идут ИЗНУТРИ приложения: поиск
# трека и текст в формате LRC через API плеера; ключ входа берётся из его хранилища
# и наружу не выходит (в этот процесс возвращается только текст). Подпись запроса —
# как у клиентов Яндекс Музыки (HMAC-SHA256 от «номер трека + время»). Приложение
# закрыто или запущено без порта — источника просто нет.
_YA_JS = """(async()=>{
 try{
  const tok=JSON.parse(localStorage.getItem('oauth')).value;
  const H={'Authorization':'OAuth '+tok,'X-Yandex-Music-Client':'YandexMusicAndroid/24023621'};
  const q=%s, dur=%s;
  const s=await (await fetch('https://api.music.yandex.net/search?type=track&page=0&text='+encodeURIComponent(q),{headers:H})).json();
  const list=(s.result&&s.result.tracks&&s.result.tracks.results||[]).slice(0,8)
     .filter(t=>t.lyricsInfo&&t.lyricsInfo.hasAvailableSyncLyrics);
  const out=[];
  for(const tr of list){
    if(dur && Math.abs(tr.durationMs/1000-dur)>3) continue;
    const id=String(tr.id), ts=Math.floor(Date.now()/1000), enc=new TextEncoder();
    const key=await crypto.subtle.importKey('raw',enc.encode('p93jhgh689SBReK6ghtw62'),{name:'HMAC',hash:'SHA-256'},false,['sign']);
    const sig=btoa(String.fromCharCode(...new Uint8Array(await crypto.subtle.sign('HMAC',key,enc.encode(id+ts)))));
    const r=await fetch('https://api.music.yandex.net/tracks/'+id+'/lyrics?format=LRC&timeStamp='+ts+'&sign='+encodeURIComponent(sig),{headers:H});
    if(!r.ok) continue;
    const j=await r.json();
    if(!(j.result&&j.result.downloadUrl)) continue;
    const lrc=await (await fetch(j.result.downloadUrl)).text();
    return JSON.stringify({id:id,title:tr.title,artists:tr.artists.map(a=>a.name),lrc:lrc});
  }
  return JSON.stringify(null);
 }catch(e){return JSON.stringify({err:String(e)});}
})()"""


def yandex_lyrics(artists, titles, dur):
    try:
        import player_like
        url = player_like.ym_page()
        if not url:
            return None
        for t in titles:
            js = _YA_JS % (json.dumps("%s %s" % (artists[0], t), ensure_ascii=False),
                           json.dumps(float(dur or 0)))
            raw = player_like.ws_eval(url, js, timeout=15)
            d = json.loads(raw) if raw else None
            if not d or d.get("err") or not d.get("lrc"):
                continue
            if not any(_title_ok(x, d.get("title", "")) for x in titles):
                continue
            return {"found": True, "instrumental": False, "synced": d["lrc"],
                    "source": "yandex:%s" % d.get("id")}
    except Exception as e:
        print("lyrics_bar: yandex: %r" % e, file=sys.stderr)
    return None


def fetch_lyrics(artist, title, dur, album=""):
    """-> {"found", "instrumental", "synced", "source"}; сетевые ошибки — исключение."""
    import mpris_common  # чистка «(Official Video)» и « - Topic»
    titles = [title]
    ct = mpris_common.clean_title(title)
    if ct and ct != title:
        titles.append(ct)
    artists = split_artists(artist) or [artist]

    if dur:
        for t in titles:
            params = {"artist_name": artist, "track_name": t, "duration": int(round(dur))}
            if album:
                params["album_name"] = album
            r = _http_json("get", params)
            if r:
                if r.get("instrumental"):
                    return {"found": False, "instrumental": True, "synced": "",
                            "source": "get:%s" % r.get("id")}
                if r.get("syncedLyrics"):
                    return {"found": True, "instrumental": False,
                            "synced": r["syncedLyrics"], "source": "get:%s" % r.get("id")}

    queries = []
    for t in titles:
        queries.append({"track_name": t, "artist_name": artists[0]})
    queries.append({"q": "%s %s" % (artists[0], titles[-1])})
    # Части составного названия («Skazhi mne/Asa du» → «Asa du»): латинская часть
    # находит трек, записанный кириллицей. И последним — все песни исполнителя,
    # отбор по названию (с транслитом) и длительности.
    for part in re.split(r"\s*[/,|]\s*", titles[-1]):
        if len(part) > 2 and part != titles[-1]:
            queries.append({"q": "%s %s" % (artists[0], part)})
    queries.append({"q": artists[0]})
    seen = set()
    best = None
    for q in queries:
        res = _http_json("search", q) or []
        for r in res:
            if r.get("id") in seen:
                continue
            seen.add(r.get("id"))
            if not r.get("syncedLyrics") or r.get("instrumental"):
                continue
            if not any(_title_ok(t, r.get("trackName", "")) for t in titles):
                continue
            if not _artist_ok(artist, r.get("artistName", "")):
                continue
            d = abs((r.get("duration") or 0) - dur) if dur else 0
            if dur and d > 3:
                continue
            score = (d, 0 if _norm(r.get("trackName")) in map(_norm, titles) else 1)
            if best is None or score < best[0]:
                best = (score, r)
        if best and best[0][0] <= 1:
            break
    if best:
        r = best[1]
        return {"found": True, "instrumental": False, "synced": r["syncedLyrics"],
                "source": "search:%s" % r.get("id")}
    # В lrclib нет — спросить у самой Яндекс Музыки (02.10.2026): у неё своя база
    # текстов с таймингами, и многие русские треки есть только там.
    ya = yandex_lyrics(artists, titles, dur)
    if ya:
        return ya
    return {"found": False, "instrumental": False, "synced": "", "source": ""}


def cached_lyrics(artist, title, dur):
    path = os.path.join(CACHE_DIR, cache_key(artist, title, dur) + ".json")
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if not d.get("found") and not d.get("instrumental") and time.time() - d.get("ts", 0) > NEG_TTL:
        return None
    return d


def store_lyrics(artist, title, dur, d):
    os.makedirs(CACHE_DIR, exist_ok=True)
    d = dict(d, artist=artist, title=title, duration=dur, ts=int(time.time()))
    path = os.path.join(CACHE_DIR, cache_key(artist, title, dur) + ".json")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, path)
    return d


_TS = re.compile(r"\[(\d+):(\d+(?:[.:]\d+)?)\]")
_OFFSET = re.compile(r"^\[offset:\s*([+-]?\d+)\s*\]", re.I | re.M)
_WORDTAG = re.compile(r"<\d+:\d+(?:[.:]\d+)?>")


def parse_lrc(text):
    """LRC -> отсортированный список (секунды, строка). Пустая строка = проигрыш."""
    offset = 0.0
    m = _OFFSET.search(text or "")
    if m:
        offset = int(m.group(1)) / 1000.0
    out = []
    for raw in (text or "").splitlines():
        raw = raw.strip()
        stamps = []
        while True:
            m = _TS.match(raw)
            if not m:
                break
            sec = m.group(2).replace(":", ".")
            stamps.append(int(m.group(1)) * 60 + float(sec) - offset)
            raw = raw[m.end():]
        if not stamps:
            continue
        line = " ".join(_WORDTAG.sub("", raw).split())
        for s in stamps:
            out.append((max(0.0, s), line))
    out.sort(key=lambda x: x[0])
    return out


# ─────────────────────────── отрисовка строки ───────────────────────────

def line_index(lines, pos):
    lo, hi = 0, len(lines)
    while lo < hi:
        mid = (lo + hi) // 2
        if lines[mid][0] <= pos:
            lo = mid + 1
        else:
            hi = mid
    return lo - 1


def word_starts(text):
    return [m.start() for m in re.finditer(r"\S+", text)]


def line_timing(lines, i, song_len):
    """Сколько длится пропевание строки i: не дольше разрыва до следующей."""
    start, text = lines[i]
    nxt = lines[i + 1][0] if i + 1 < len(lines) else (song_len or start + 6.0)
    gap = max(0.3, nxt - start)
    sing = max(1.0, 0.085 * len(text))
    return start, min(max(0.3, gap - 0.25), sing), nxt


def sung_chars(text, elapsed, dur):
    """Сколько символов подсвечено: по словам, слово загорается, когда начинается."""
    if not text:
        return 0
    starts = word_starts(text)
    frac = max(0.0, elapsed) / dur if dur > 0 else 1.0
    done = 0
    for k, s in enumerate(starts):
        if s <= frac * len(text):
            m = re.match(r"\S+", text[s:])
            done = s + (m.end() if m else 0)
        else:
            break
    return done


def next_word_time(text, start, elapsed, dur):
    """Когда загорится следующее слово (абсолютная позиция), или None."""
    if not text or dur <= 0:
        return None
    for s in word_starts(text):
        t = start + dur * s / len(text)
        if t > start + elapsed + 1e-6:
            return t
    return None


def _esc(s):
    return html.escape(s, quote=False)


def render(text, done, accent):
    """Pango-разметка: пропетое — акцентом, остальное приглушено; окно в MAX_LEN."""
    n = len(text)
    flags = [i < done for i in range(n)]
    if n <= MAX_LEN:
        chars = list(zip(text, flags))
    else:
        keep = int(MAX_LEN * 0.6)
        w = 0 if done <= keep else done - keep
        # начало окна — на границе слова
        if w:
            starts = [s for s in word_starts(text) if s <= w]
            w = starts[-1] if starts else w
        if w == 0:
            span = MAX_LEN - 1
            chars = list(zip(text[:span].rstrip(), flags[:span])) + [("…", flags[span])]
        elif w + MAX_LEN - 1 >= n:
            w = n - (MAX_LEN - 1)
            chars = [("…", flags[w])] + list(zip(text[w:], flags[w:]))
        else:
            span = MAX_LEN - 2
            seg = text[w:w + span]
            chars = [("…", flags[w])] + list(zip(seg, flags[w:w + span]))
            chars = chars[:1 + len(seg.rstrip())] + [("…", flags[w + span])]
    out, run, cur = [], "", None
    for ch, f in chars + [(None, None)]:
        if f != cur or ch is None:
            if run:
                if cur:
                    out.append('<span color="%s">%s</span>' % (accent, _esc(run))
                               if accent else _esc(run))
                else:
                    out.append('<span alpha="%s">%s</span>' % (DIM_ALPHA, _esc(run)))
            run, cur = "", f
        if ch is not None:
            run += ch
    return "".join(out)


def tooltip(lines, i, artist, title):
    head = "<b>%s</b> — %s" % (_esc(artist), _esc(title))

    def at(k):
        if 0 <= k < len(lines):
            return lines[k][1] or GAP_TEXT
        return ""
    prev, cur, nxt = at(i - 1), at(i) if i >= 0 else GAP_TEXT, at(i + 1)
    body = []
    if prev:
        body.append('<span alpha="60%%">%s</span>' % _esc(prev))
    body.append("<b>%s</b>" % _esc(cur))
    if nxt:
        body.append('<span alpha="60%%">%s</span>' % _esc(nxt))
    return head + "\n\n" + "\n".join(body)


# ─────────────────────────── плееры по D-Bus ───────────────────────────

class Player:
    def __init__(self, name):
        self.name = name              # org.mpris.MediaPlayer2.xxx
        self.owner = ""
        self.identity = ""
        self.status = "Stopped"
        self.meta = {}
        self.rate = 1.0
        self.pos = 0.0
        self.pos_t = time.monotonic()
        self.synced_at = 0.0

    def position(self):
        if self.status == "Playing":
            return self.pos + (time.monotonic() - self.pos_t) * (self.rate or 1.0)
        return self.pos

    def set_pos(self, sec):
        self.pos, self.pos_t = sec, time.monotonic()
        self.synced_at = self.pos_t

    @property
    def title(self):
        return str(self.meta.get("xesam:title") or "").strip()

    @property
    def artist(self):
        a = self.meta.get("xesam:artist") or ""
        if isinstance(a, (list, tuple)):
            a = ", ".join(str(x) for x in a if x)
        return str(a).strip()

    @property
    def album(self):
        return str(self.meta.get("xesam:album") or "").strip()

    @property
    def length(self):
        try:
            return int(self.meta.get("mpris:length") or 0) / 1e6
        except (TypeError, ValueError):
            return 0.0

    @property
    def url(self):
        return str(self.meta.get("xesam:url") or "")

    def is_browser(self):
        toks = set(re.split(r"[^a-z0-9]+", self.identity.lower()))
        return bool(toks & BROWSERS)

    def ignored(self):
        low = (self.name + " " + self.identity).lower()
        return any(x in low for x in IGNORED)

    def is_song(self):
        if self.ignored():
            return False
        if not self.title or not self.artist:
            return False
        if not (30 <= self.length <= 15 * 60):
            return False
        if self.is_browser():
            host = urllib.parse.urlsplit(self.url).netloc.lower()
            return bool(host) and any(host == h or host.endswith("." + h) or host.startswith(h)
                                      for h in MUSIC_HOSTS)
        return True

    def track_key(self):
        return (self.artist, self.title, int(round(self.length)))


def read_accent():
    try:
        with open(COLORS_CSS) as f:
            m = re.search(r"@define-color\s+primary\s+(#[0-9a-fA-F]{6})", f.read())
            return m.group(1) if m else ""
    except OSError:
        return ""


class App:
    MPRIS = "org.mpris.MediaPlayer2."
    PATH = "/org/mpris/MediaPlayer2"
    IFACE = "org.mpris.MediaPlayer2.Player"

    def __init__(self):
        from gi.repository import Gio, GLib
        self.Gio, self.GLib = Gio, GLib
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.players = {}
        self.by_owner = {}
        self.lyrics = {}          # track_key -> list (пустой = нет текста) | None (грузится)
        self.failed = {}          # track_key -> monotonic время сетевой ошибки
        self.timer = 0
        self.last_out = None
        self.active_key = None
        try:
            self.accent_mtime = os.stat(COLORS_CSS).st_mtime
        except OSError:
            self.accent_mtime = 0
        self.accent = read_accent()
        self.off = os.path.exists(FLAG)
        self.last_resync = 0.0

        self.bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus",
                                  "NameOwnerChanged", "/org/freedesktop/DBus", None,
                                  Gio.DBusSignalFlags.NONE, self.on_owner_changed)
        self.bus.signal_subscribe(None, "org.freedesktop.DBus.Properties",
                                  "PropertiesChanged", self.PATH, None,
                                  Gio.DBusSignalFlags.NONE, self.on_props)
        self.bus.signal_subscribe(None, self.IFACE, "Seeked", self.PATH, None,
                                  Gio.DBusSignalFlags.NONE, self.on_seeked)
        for name in self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                              "org.freedesktop.DBus", "ListNames", None, "(as)")[0]:
            if name.startswith(self.MPRIS):
                self.add_player(name)
        GLib.timeout_add(1000, self.housekeeping)
        self.write_status()
        self.update()

    # — D-Bus обёртки —
    def call(self, dest, path, iface, method, args, rtype, timeout=800):
        V = self.GLib.Variant
        r = self.bus.call_sync(dest, path, iface, method, args,
                               self.GLib.VariantType.new(rtype) if rtype else None,
                               self.Gio.DBusCallFlags.NONE, timeout, None)
        return r.unpack() if r else None

    def add_player(self, name, owner=None):
        p = Player(name)
        try:
            p.owner = owner or self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                         "org.freedesktop.DBus", "GetNameOwner",
                                         self.GLib.Variant("(s)", (name,)), "(s)")[0]
            props = self.call(name, self.PATH, "org.freedesktop.DBus.Properties", "GetAll",
                              self.GLib.Variant("(s)", (self.IFACE,)), "(a{sv})")[0]
            ident = self.call(name, self.PATH, "org.freedesktop.DBus.Properties", "Get",
                              self.GLib.Variant("(ss)", ("org.mpris.MediaPlayer2", "Identity")),
                              "(v)")[0]
            p.identity = str(ident or "")
        except Exception:
            props = {}
        self.apply_props(p, props)
        if "Position" in props:
            p.set_pos(int(props["Position"] or 0) / 1e6)
        self.players[name] = p
        self.by_owner[p.owner] = p

    def apply_props(self, p, props):
        if "PlaybackStatus" in props:
            p.status = str(props["PlaybackStatus"])
        if "Metadata" in props:
            p.meta = dict(props["Metadata"] or {})
        if "Rate" in props:
            try:
                p.rate = float(props["Rate"]) or 1.0
            except (TypeError, ValueError):
                p.rate = 1.0

    def resync(self, p):
        """Асинхронно спросить позицию; ответ поправит экстраполяцию."""
        def done(bus, res):
            try:
                v = bus.call_finish(res).unpack()[0]
                p.set_pos(int(v or 0) / 1e6)
            except Exception:
                return
            self.update()
        self.bus.call(p.name, self.PATH, "org.freedesktop.DBus.Properties", "Get",
                      self.GLib.Variant("(ss)", (self.IFACE, "Position")),
                      self.GLib.VariantType.new("(v)"), self.Gio.DBusCallFlags.NONE,
                      800, None, done)

    # — сигналы —
    def on_owner_changed(self, conn, sender, path, iface, signal, params):
        name, old, new = params.unpack()
        if not name.startswith(self.MPRIS):
            return
        old_p = self.players.pop(name, None)
        if old_p:
            self.by_owner.pop(old_p.owner, None)
        if new:
            self.add_player(name, new)
        self.update()

    def on_props(self, conn, sender, path, iface, signal, params):
        ifname, changed, invalidated = params.unpack()
        p = self.by_owner.get(sender)
        if not p or ifname != self.IFACE:
            return
        before = (p.status, p.track_key())
        now_pos = p.position()          # досчитано по старому статусу
        self.apply_props(p, changed)
        if (p.status, p.track_key()) != before or "Position" in changed:
            if "Position" in changed:
                p.set_pos(int(changed["Position"] or 0) / 1e6)
            else:
                # на смене статуса позицию фиксируем сразу, потом сверяем с плеером
                p.pos, p.pos_t = now_pos, time.monotonic()
                if before[1] != p.track_key():
                    p.set_pos(0.0)
                self.resync(p)
        self.update()

    def on_seeked(self, conn, sender, path, iface, signal, params):
        p = self.by_owner.get(sender)
        if p:
            p.set_pos(int(params.unpack()[0] or 0) / 1e6)
            self.update()

    def housekeeping(self):
        try:
            off = os.path.exists(FLAG)
            if off != self.off:
                self.off = off
                self.update()
            try:
                mt = os.stat(COLORS_CSS).st_mtime
            except OSError:
                mt = 0
            if mt != self.accent_mtime:
                self.accent_mtime, self.accent = mt, read_accent()
                self.update()
            p = self.active()
            if p and p.status == "Playing" and time.monotonic() - p.synced_at >= RESYNC:
                self.resync(p)
            if p:
                k = p.track_key()
                if k in self.failed and time.monotonic() - self.failed[k] > 30:   # 503 у lrclib бывает минутами
                    self.failed.pop(k)
                    self.lyrics.pop(k, None)
                    self.update()
        except Exception as e:
            print("lyrics_bar: %r" % e, file=sys.stderr)
        return True

    # — кого показываем —
    def active(self):
        songs = [p for p in self.players.values() if p.is_song()]
        playing = [p for p in songs if p.status == "Playing"]
        if playing:
            return playing[0]
        others_playing = any(p.status == "Playing" and not p.ignored()
                             for p in self.players.values())
        paused = [p for p in songs if p.status == "Paused"]
        return paused[0] if paused and not others_playing else None

    def want_lyrics(self, p):
        k = p.track_key()
        if k in self.lyrics:
            return self.lyrics[k]
        d = cached_lyrics(*k)
        if d is not None:
            self.lyrics[k] = parse_lrc(d.get("synced", "")) if d.get("found") else []
            return self.lyrics[k]
        self.lyrics[k] = None
        artist, title, dur, album = p.artist, p.title, p.length, p.album

        def work():
            try:
                d = store_lyrics(artist, title, int(round(dur)),
                                 fetch_lyrics(artist, title, dur, album))
                res = parse_lrc(d["synced"]) if d.get("found") else []
            except Exception as e:
                print("lyrics_bar: fetch %s — %s: %r" % (artist, title, e), file=sys.stderr)
                res = "fail"
            self.GLib.idle_add(self.got_lyrics, k, res)
        threading.Thread(target=work, daemon=True).start()
        return None

    def got_lyrics(self, k, res):
        if res == "fail":
            self.failed[k] = time.monotonic()
            self.lyrics[k] = []
        else:
            self.lyrics[k] = res
        self.write_status()
        self.update()
        return False

    def write_status(self):
        p = self.active()
        st = {"off": self.off}
        if p:
            lines = self.lyrics.get(p.track_key())
            st.update(player=p.name[len(self.MPRIS):], identity=p.identity,
                      artist=p.artist, title=p.title, length=round(p.length),
                      lyrics=("loading" if lines is None else len(lines)))
        try:
            with open(STATUS_FILE, "w") as f:
                json.dump(st, f, ensure_ascii=False)
        except OSError:
            pass

    # — главный шаг —
    def emit(self, obj):
        s = json.dumps(obj, ensure_ascii=False)
        if s != self.last_out:
            self.last_out = s
            try:
                sys.stdout.write(s + "\n")
                sys.stdout.flush()
            except BrokenPipeError:
                os._exit(0)
            # Флаг для bar_window_title.py: пока строка песни в баре, заголовок
            # окна прячется — вдвоём им до pomo не хватает места (30.09.2026).
            try:
                if obj.get("text"):
                    open(ACTIVE_FILE, "w").close()
                elif os.path.exists(ACTIVE_FILE):
                    os.remove(ACTIVE_FILE)
            except OSError:
                pass

    def update(self):
        if self.timer:
            self.GLib.source_remove(self.timer)
            self.timer = 0
        try:
            nxt = self.step()
        except Exception as e:
            print("lyrics_bar: %r" % e, file=sys.stderr)
            nxt = None
        if nxt is not None:
            ms = int(max(MIN_STEP, nxt) * 1000)
            self.timer = self.GLib.timeout_add(ms, self._tick)
        return False

    def _tick(self):
        self.timer = 0
        self.update()
        return False

    def step(self):
        """Выводит строку; возвращает, через сколько секунд смотреть снова (или None)."""
        p = None if self.off else self.active()
        key = p.track_key() if p else None
        if key != self.active_key:
            self.active_key = key
            self.write_status()
        if not p:
            self.emit({"text": ""})
            return None
        lines = self.want_lyrics(p)
        if not lines or not any(t for _, t in lines):
            self.emit({"text": ""})
            return None
        pos = p.position() + LEAD
        i = line_index(lines, pos)
        cls = ["lyrics"] + (["paused"] if p.status != "Playing" else [])
        if i < 0 or not lines[i][1]:
            text, nxt_t = GAP_TEXT, (lines[i + 1][0] if i + 1 < len(lines) else None)
            cls.append("gap")
        else:
            start, dur, line_end = line_timing(lines, i, p.length)
            elapsed = pos - start
            done = sung_chars(lines[i][1], elapsed, dur)
            text = render(lines[i][1], done, self.accent)
            nw = next_word_time(lines[i][1], start, elapsed, dur)
            nxt_t = min(nw, line_end) if nw else (line_end if i + 1 < len(lines) else None)
        # Нота перед строкой (30.09.2026, просьба: «забыли иконку ноты»): сразу
        # видно, что это текст песни, а не заголовок окна. В проигрыше — только нота.
        note = '<span foreground="%s">\U000f075a</span>' % self.accent
        text = note if "gap" in cls else note + "  " + text
        self.emit({"text": text, "tooltip": tooltip(lines, i, p.artist, p.title),
                   "class": cls})
        if p.status != "Playing" or nxt_t is None:
            return None
        return (nxt_t - pos) / (p.rate or 1.0) + 0.01


# ─────────────────────────── команды ───────────────────────────

def cmd_toggle(arg):
    if arg == "toggle":
        arg = "on" if os.path.exists(FLAG) else "off"
    if arg == "off":
        os.makedirs(os.path.dirname(FLAG), exist_ok=True)
        open(FLAG, "w").close()
    elif os.path.exists(FLAG):
        os.remove(FLAG)
    print(arg)


def cmd_status():
    print("выключено" if os.path.exists(FLAG) else "включено")
    try:
        with open(STATUS_FILE) as f:
            st = json.load(f)
    except (OSError, ValueError):
        print("модуль не запущен или ещё ничего не играл")
        return
    if st.get("title"):
        ly = st.get("lyrics")
        ly = {"loading": "ищу текст"}.get(ly, "строк: %s" % ly if ly else "текста нет")
        print("%s — %s (%s с), плеер %s [%s]; %s" % (st["artist"], st["title"], st["length"],
                                                      st["player"], st["identity"], ly))
    else:
        print("песня не играет")


def cmd_lookup(args):
    artist, title = args[0], args[1]
    dur = float(args[2]) if len(args) > 2 else 0
    album = args[3] if len(args) > 3 else ""
    d = fetch_lyrics(artist, title, dur, album)
    lines = parse_lrc(d.get("synced", ""))
    print("найдено: %s, источник %s, строк %d" % (d["found"], d["source"] or "—", len(lines)))
    for t, s in lines[:12]:
        print("  [%02d:%05.2f] %s" % (t // 60, t % 60, s))


def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    a = sys.argv[1:]
    if a and a[0] in ("on", "off", "toggle"):
        return cmd_toggle(a[0])
    if a and a[0] == "status":
        return cmd_status()
    if a and a[0] == "lookup" and len(a) >= 3:
        return cmd_lookup(a[1:])
    if a:
        print(__doc__)
        return
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import GLib
    App()
    GLib.MainLoop().run()


if __name__ == "__main__":
    main()
