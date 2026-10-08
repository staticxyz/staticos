#!/usr/bin/env python3
"""Свой синхронный текст песен: запись → голос → Whisper → строки со временем. 06.10.2026.

    lyrics_sync.py daemon        следить за плеерами и записывать песни без синхронного текста
    lyrics_sync.py worker        разобрать очередь (демон зовёт сам, когда видеокарта свободна)
    lyrics_sync.py status        очередь, запись сейчас, последние результаты
    lyrics_sync.py on|off        включить/выключить (флаг state/lyrics-sync-off)
    lyrics_sync.py run ЗАПИСЬ.wav АРТИСТ НАЗВАНИЕ СЕКУНДЫ   разобрать одну запись вручную

Пользователь (06.10.2026): «что мы можем сделать с треками, у которых нет лириксов?» → «делай
пункт 3». Как устроено:
  * демон слушает плееры (тот же D-Bus, что lyrics_bar.App) и, когда песня начинается с
    начала, пишет звук ИМЕННО её потока (pw-record --target <поток плеера>, 44,1 кГц стерео;
    поток ищется по процессу владельца MPRIS-имени) в ~/.cache/jarvis/lyrics-sync/rec;
  * трек доиграл до конца без перемотки, длина записи сходится с длиной трека, а
    синхронного текста у него нет (кэш lyrics_bar) — запись встаёт в очередь, иначе стирается;
  * обработчик (worker) берёт очередь, когда нет игры (cs2, gamescope) и на видеокарте есть
    ≥2 ГБ: demucs отделяет голос (lyrics_sync_sep.py), faster-whisper
    large-v3-turbo даёт слова со временем (lyrics_sync_asr.py);
    оба шага — в своём venv: ~/.local/share/lyrics-sync/venv (pip install demucs faster-whisper);
  * есть обычный текст (plain из lrclib/Яндекса) — его строки подгоняются по словам Whisper
    (совпадения слов → якоря, между ними — по числу слов): source "whisper-aligned"; нет —
    строки из самих распознанных слов: "whisper";
  * результат пишется в кэш lyrics_bar как обычный синхронный текст; панель подхватывает
    его без перезапуска (lyrics_bar.App.want_lyrics перечитывает изменившийся файл).
Текст появляется со ВТОРОГО прослушивания. Ни записи, ни обработки во время игры.
"""
import ctypes
import difflib
import fcntl
import glob
import json
import os
import re
import signal
import subprocess
import sys
import time
import wave

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lyrics_bar as LB  # noqa: E402

DIR = os.path.expanduser("~/.cache/jarvis/lyrics-sync")
REC = os.path.join(DIR, "rec")
QUEUE = os.path.join(DIR, "queue")
LOG = os.path.join(DIR, "log.txt")
LOCK = os.path.join(DIR, "worker.lock")
RETRY = os.path.join(DIR, "retry-after")
FLAG = os.path.expanduser("~/.config/hypr/state/lyrics-sync-off")
VENV = os.path.expanduser(os.environ.get("LYRICS_SYNC_VENV", "~/.local/share/lyrics-sync/venv"))
PY_SEP = PY_ASR = os.path.join(VENV, "bin/python")
GAMES = (b"cs2", b"gamescope", b"gamescope-wl")
START_MAX = 3.0          # запись — только если песня началась с начала (позиция < 3 с)
LEN_TOL = 4.0            # длина записи + начало ≈ длина трека (±4 с)
END_TOL = 6.0            # и доиграна почти до конца
GPU_MIN_MB = 2000
LINE_MAX = 42            # строка из распознанных слов — не длиннее
JUNK = re.compile(r"(субтитр|продолжение следует|редактор субтитров|thank(s)? for watching|"
                  r"подпишись|подписывайтесь|amara\.org|dimatorzok|suscr[ií]bete|subscribe|"
                  r"abonnez|untertitel)", re.I)
# cuBLAS и cuDNN для CTranslate2 — из пакетов nvidia-* того же venv, если они там есть
NV_LIBS = sorted(glob.glob(os.path.join(VENV, "lib/python3*/site-packages/nvidia/*/lib")))


def glib_signal_add(prio, signum, handler):
    """Сигнал в главный цикл GLib. GLib.unix_signal_add устарел (PyGObject 3.52+) и однажды
    исчезнет — тогда программа перестала бы запускаться (08.10.2026). Сначала замена
    GLibUnix.signal_add, без неё — старое имя, без обоих — обычный signal.signal."""
    from gi.repository import GLib
    try:
        from gi.repository import GLibUnix
        return GLibUnix.signal_add(prio, signum, handler)
    except (ImportError, AttributeError):
        pass
    try:
        return GLib.unix_signal_add(prio, signum, handler)
    except AttributeError:
        import signal as _signal
        _signal.signal(signum, lambda *_a: GLib.idle_add(lambda: handler() and False))


def log(msg):
    os.makedirs(DIR, exist_ok=True)
    with open(LOG, "a") as f:
        f.write("%s %s\n" % (time.strftime("%d.%m %H:%M:%S"), msg))


def gaming():
    for p in os.listdir("/proc"):
        if p.isdigit():
            try:
                if open("/proc/%s/comm" % p, "rb").read().strip() in GAMES:
                    return True
            except OSError:
                pass
    return False


def pdeathsig():
    """Запись умирает вместе с демоном (иначе сироты pw-record, см. память)."""
    try:
        ctypes.CDLL("libc.so.6").prctl(1, signal.SIGINT)
    except Exception:
        pass


def entry(artist, title, dur):
    path = os.path.join(LB.CACHE_DIR, LB.cache_key(artist, title, dur) + ".json")
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def wav_seconds(path):
    try:
        with wave.open(path) as w:
            return w.getnframes() / float(w.getframerate())
    except (OSError, EOFError, wave.Error):
        return 0.0


# ─────────────────────────── демон: запись ───────────────────────────

def stream_serial(pid):
    """object.serial играющего потока процесса pid (или его исполняемого файла)."""
    names = set()
    for f in ("comm",):
        try:
            names.add(open("/proc/%d/%s" % (pid, f)).read().strip())
        except OSError:
            pass
    try:
        names.add(os.path.basename(os.readlink("/proc/%d/exe" % pid)))
    except OSError:
        pass
    try:
        dump = json.loads(subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    best = None
    for o in dump:
        info = o.get("info") or {}
        pr = info.get("props") or {}
        if pr.get("media.class") != "Stream/Output/Audio":
            continue
        if str(pr.get("application.process.id")) != str(pid) and \
                pr.get("application.process.binary") not in names:
            continue
        if info.get("state") == "running":
            return pr.get("object.serial")
        best = best or pr.get("object.serial")
    return best


def run_daemon():
    import gi
    gi.require_version("Gio", "2.0")
    from gi.repository import GLib

    class SyncApp(LB.App):
        def __init__(self):
            self.rec = None
            super().__init__()
            GLib.timeout_add_seconds(2, self.tick)

        def write_status(self):          # строку в бар пишет xpbar, не мы
            pass

        def update(self):
            try:
                self.check()
            except Exception as e:
                log("демон: %r" % e)

        def jumped(self, sender, new_us):
            """Перемотка — только настоящий скачок позиции (>2 с от ожидаемой): Яндекс шлёт
            Seeked/Position и без перемотки — запись «По тропам» (174 из 174 с) из-за этого
            выбросилась (06.10.2026)."""
            p = self.by_owner.get(sender)
            if not (self.rec and p is not None and p.name == self.rec["player"]
                    and p.track_key() == self.rec["key"]):
                return
            try:
                new = int(new_us or 0) / 1e6
            except (TypeError, ValueError):
                return
            if abs(new - p.position()) > 2.0:
                self.rec["seek"] = True
                log("перемотка: %.1f → %.1f с" % (p.position(), new))

        def on_seeked(self, conn, sender, path, iface, signal_, params):
            self.jumped(sender, params.unpack()[0])
            super().on_seeked(conn, sender, path, iface, signal_, params)

        def on_props(self, conn, sender, path, iface, signal_, params):
            changed = params.unpack()[1]
            if "Position" in changed and "Metadata" not in changed:    # смена трека — не перемотка
                self.jumped(sender, changed["Position"])
            super().on_props(conn, sender, path, iface, signal_, params)

        def playing(self):
            p = self.active()
            return p if p and p.status == "Playing" else None

        def check(self):
            p = self.active()
            r = self.rec
            if r and (p is None or p.name != r["player"] or p.track_key() != r["key"]):
                self.finish()
            if self.rec or os.path.exists(FLAG):
                return
            p = self.playing()
            if not p or not p.is_song() or p.position() > START_MAX or gaming():
                return
            k = p.track_key()
            d = entry(*k)
            if d and (d.get("found") or d.get("instrumental")):
                return                              # синхронный текст уже есть
            # Только когда текст ЕСТЬ (обычный, без таймингов): музыку без слов и песни, чьих
            # слов нет нигде, не пишем (06.10.2026, пользователь). Записи ещё нет — поиск текста
            # мог не закончиться: пишем, а решаем в конце (finish).
            if d and not d.get("plain"):
                return
            if glob.glob(os.path.join(QUEUE, LB.cache_key(*k) + ".json")):
                return
            self.start(p, k)

        def start(self, p, k):
            try:
                pid = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus",
                                "org.freedesktop.DBus", "GetConnectionUnixProcessID",
                                GLib.Variant("(s)", (p.owner,)), "(u)")[0]
            except Exception:
                return
            serial = stream_serial(pid)
            if not serial:
                return
            os.makedirs(REC, exist_ok=True)
            path = os.path.join(REC, LB.cache_key(*k) + ".wav")
            pos = p.position()
            proc = subprocess.Popen(["pw-record", "--target", str(serial), "--rate", "44100",
                                     "--channels", "2", "--format", "s16", path],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    preexec_fn=pdeathsig)
            # pw-record начинает писать через ~0,1–0,2 с после запуска
            self.rec = {"player": p.name, "key": k, "proc": proc, "path": path, "seek": False,
                        "start_pos": pos + 0.15, "last_pos": pos}

        def finish(self):
            r, self.rec = self.rec, None
            try:
                r["proc"].send_signal(signal.SIGINT)
                r["proc"].wait(timeout=3)
            except Exception:
                r["proc"].kill()
            artist, title, dur = r["key"]
            got = wav_seconds(r["path"]) + r["start_pos"]
            d = entry(artist, title, dur)
            ok = (not r["seek"] and abs(got - dur) <= LEN_TOL and r["last_pos"] >= dur - END_TOL
                  and bool(d and d.get("plain"))
                  and not (d.get("found") or d.get("instrumental")))
            if not ok:
                try:
                    os.remove(r["path"])
                except OSError:
                    pass
                if got > 30:
                    log("запись не годится: %s — %s (перемотка %s, записано %.0f из %d с, до %.0f с)"
                        % (artist, title, r["seek"], got, dur, r["last_pos"]))
                return
            os.makedirs(QUEUE, exist_ok=True)
            job = {"artist": artist, "title": title, "dur": dur, "wav": r["path"],
                   "offset": r["start_pos"], "ts": int(time.time())}
            with open(os.path.join(QUEUE, LB.cache_key(artist, title, dur) + ".json"), "w") as f:
                json.dump(job, f, ensure_ascii=False)
            log("в очереди: %s — %s" % (artist, title))
            self.kick()

        def tick(self):
            try:
                if self.rec:
                    p = self.players.get(self.rec["player"])
                    if p and p.track_key() == self.rec["key"]:
                        self.rec["last_pos"] = max(self.rec["last_pos"], p.position())
                    if gaming() or os.path.exists(FLAG):
                        self.rec["seek"] = True           # не годится — сотрётся
                        self.finish()
                self.kick()
            except Exception as e:
                log("демон tick: %r" % e)
            return True

        def kick(self):
            if not glob.glob(os.path.join(QUEUE, "*.json")) or gaming() or os.path.exists(FLAG):
                return
            try:
                if time.time() < float(open(RETRY).read()):
                    return
            except (OSError, ValueError):
                pass
            if worker_busy():
                return
            subprocess.Popen([sys.executable, os.path.abspath(__file__), "worker"],
                             stdout=subprocess.DEVNULL, stderr=open(LOG, "a"), start_new_session=True)

    SyncApp()
    loop = GLib.MainLoop()
    glib_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGTERM, loop.quit)
    loop.run()


def worker_busy():
    os.makedirs(DIR, exist_ok=True)
    try:
        fd = os.open(LOCK, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
        return False
    except OSError:
        return True


# ─────────────────────────── обработка ───────────────────────────

def gpu_free_mb():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def norm(w):
    return re.sub(r"[^\w]+", "", w.lower().replace("ё", "е"))


def plain_rows(plain):
    rows = []
    for r in (plain or "").splitlines():
        r = " ".join(r.split())
        if r and not LB._SECTION.match(r):
            rows.append(r)
    return rows


def word_sim(a, b):
    if a == b:
        return 1.0
    if abs(len(a) - len(b)) > 3 or (a[:1] != b[:1] and a[-1:] != b[-1:]):
        return 0.0
    r = difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()
    return r if r >= 0.7 else 0.0


def dp_pairs(xs, ys):
    """Выравнивание двух рядов слов по порядку (как LCS, но слова сравниваются нечётко):
    [(i, j)] пары совпавших. SequenceMatcher тут не годится — он хватает самый длинный
    кусок и склеивает первый припев текста с третьим припевом распознанного."""
    n, m = len(xs), len(ys)
    sim = {}
    S = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n - 1, -1, -1):
        Si, Si1, xi = S[i], S[i + 1], xs[i]
        for j in range(m - 1, -1, -1):
            v = word_sim(xi, ys[j])
            if v:
                sim[i, j] = v
            best = Si1[j] if Si1[j] >= Si[j + 1] else Si[j + 1]
            if v and Si1[j + 1] + v > best:
                best = Si1[j + 1] + v
            Si[j] = best
    out, i, j = [], 0, 0
    while i < n and j < m:
        v = sim.get((i, j), 0.0)
        if v and S[i][j] == S[i + 1][j + 1] + v:
            out.append((i, j))
            i, j = i + 1, j + 1
        elif S[i + 1][j] >= S[i][j + 1]:
            i += 1
        else:
            j += 1
    return out


def align(plain, asr, dur):
    """Строки обычного текста → [(время, строка)] по словам Whisper; None — не сошлось."""
    rows = plain_rows(plain)
    pw = [(norm(w), i) for i, r in enumerate(rows) for w in r.split() if norm(w)]
    ww = [(norm(w[0]), w[1], w[2]) for s in asr["segments"] for w in s["words"] if norm(w[0])]
    if len(pw) < 8 or len(ww) < 8:
        return None
    t_of, end_of = {}, {}
    for a, b in dp_pairs([a for a, _ in pw], [b for b, _, _ in ww]):
        t_of[a], end_of[a] = ww[b][1], ww[b][2]
    if len(t_of) < 0.25 * len(pw):
        return None
    # время начала каждой строки: первое совпавшее слово (минус слова до него по 0,3 с),
    # иначе — между соседними якорями по числу слов
    first = {}
    for k, (_, i) in enumerate(pw):
        first.setdefault(i, k)
    idx = sorted(t_of)
    out = []
    for i in range(len(rows)):
        if i not in first:
            continue
        k0 = first[i]
        ks = [k for k in range(k0, len(pw)) if pw[k][1] == i]
        hit = next((k for k in ks if k in t_of), None)
        if hit is not None:
            t = t_of[hit] - 0.3 * (hit - k0)
        else:
            prev = max((k for k in idx if k < k0), default=None)
            nxt = min((k for k in idx if k > k0), default=None)
            if prev is not None and nxt is not None:
                t = t_of[prev] + (t_of[nxt] - t_of[prev]) * (k0 - prev) / float(nxt - prev)
            elif prev is not None:
                t = end_of[prev] + 0.35 * (k0 - prev)
            elif nxt is not None:
                t = t_of[nxt] - 0.35 * (nxt - k0)
            else:
                continue
        out.append([max(0.0, t), rows[i], ks])
    # по порядку; конец строки — конец её последнего совпавшего слова: длинная тишина после —
    # проигрыш (пустая строка)
    res = []
    last = -1.0
    for n, (t, row, ks) in enumerate(out):
        t = max(t, last + 0.2)
        if t > dur:
            break
        res.append((t, row))
        last = t
        ends = [end_of[k] for k in ks if k in end_of]
        nxt = out[n + 1][0] if n + 1 < len(out) else None
        if ends and nxt is not None and nxt - max(ends) > 6:
            res.append((max(ends) + 0.6, ""))
            last = max(ends) + 0.6
    return res


def from_words(asr, dur):
    """Строки из самих распознанных слов: отрезки Whisper, длинные — по LINE_MAX знаков."""
    res, prev_end = [], None
    for s in asr["segments"]:
        text = s["text"].strip()
        if not text or JUNK.search(text) or not s["words"]:
            continue
        # Whisper сам не уверен, что это речь, — на музыке это обычно выдумка
        if s.get("nospeech", 0) > 0.6 or s.get("logprob", 0) < -1.0:
            continue
        if prev_end is not None and s["start"] - prev_end > 5:
            res.append((prev_end + 0.6, ""))
        line, t0 = "", None
        for w, a, _b in s["words"]:
            if line and len(line) + 1 + len(w) > LINE_MAX:
                res.append((t0, line))
                line, t0 = "", None
            line = (line + " " + w).strip()
            t0 = a if t0 is None else t0
        if line:
            res.append((t0, line))
        prev_end = s["end"]
    # Whisper на музыке повторяет одну фразу — больше 3 одинаковых строк подряд не берём
    out, rep = [], 0
    for t, line in res:
        rep = rep + 1 if out and line and line == out[-1][1] else 0
        if rep < 3 and t <= dur:
            out.append((t, line))
    return out


def to_lrc(lines, offset):
    return "\n".join("[%02d:%05.2f]%s" % (int((t + offset) // 60), (t + offset) % 60, s)
                     for t, s in lines)


def process(job):
    artist, title, dur, wav_path = job["artist"], job["title"], job["dur"], job["wav"]
    d = entry(artist, title, dur) or {}
    if d.get("found") and not str(d.get("source", "")).startswith("whisper"):
        return "уже есть синхронный текст"
    plain = d.get("plain") or ""
    if not plain:
        return "нет обычного текста — пропуск"
    voc = wav_path[:-4] + "-voc.wav"
    js = wav_path[:-4] + "-asr.json"
    nice = ["nice", "-n", "15", "ionice", "-c", "3"]
    r = subprocess.run(nice + [PY_SEP, os.path.join(HERE, "lyrics_sync_sep.py"), wav_path, voc],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not os.path.exists(voc):
        raise RuntimeError("голос не отделился: %s" % r.stderr.strip()[-300:])
    lang = "ru" if re.search(r"[а-яё]", (plain + " " + title + " " + artist).lower()) else ""
    env = dict(os.environ, LD_LIBRARY_PATH=":".join(
        NV_LIBS + [x for x in os.environ.get("LD_LIBRARY_PATH", "").split(":") if x]))
    r = subprocess.run(nice + [PY_ASR, os.path.join(HERE, "lyrics_sync_asr.py"), voc, js, lang],
                       capture_output=True, text=True, timeout=900, env=env)
    if r.returncode != 0 or not os.path.exists(js):
        raise RuntimeError("Whisper не отработал: %s" % r.stderr.strip()[-300:])
    asr = json.load(open(js))
    lines = align(plain, asr, dur) if plain else None
    src = "whisper-aligned"
    if not lines:
        # слова не сошлись с текстом (другая песня, другой язык) — свои строки из
        # распознанного НЕ сочиняем: Whisper на музыке выдумывает (06.10.2026)
        for f in (voc, js):
            _rm(f)
        return "текст не сошёлся с голосом — пропуск"
    if len([1 for _t, s in lines if s]) < 4:
        for f in (voc, js):
            _rm(f)
        return "слов почти нет (%s)" % src
    d.update(found=True, instrumental=False, synced=to_lrc(lines, job.get("offset", 0.0)),
             source=src, plain=plain)
    LB.store_lyrics(artist, title, dur, d)
    for f in (voc, js):
        _rm(f)
    return "готово (%s, %d строк)" % (src, len(lines))


def _rm(path):
    try:
        os.remove(path)
    except OSError:
        pass


def run_worker():
    os.makedirs(DIR, exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0
    for jp in sorted(glob.glob(os.path.join(QUEUE, "*.json")), key=os.path.getmtime):
        if gaming() or os.path.exists(FLAG):
            break
        free = gpu_free_mb()
        if free is not None and free < GPU_MIN_MB:
            with open(RETRY, "w") as f:
                f.write(str(time.time() + 300))       # видеокарта занята — через 5 минут
            log("видеокарта занята (%d МБ свободно) — позже" % free)
            break
        try:
            job = json.load(open(jp))
        except (OSError, ValueError):
            _rm(jp)
            continue
        t = time.time()
        try:
            res = process(job)
        except Exception as e:
            res = "ошибка: %s" % e
            job["fails"] = job.get("fails", 0) + 1
            if job["fails"] < 3:
                with open(jp, "w") as f:
                    json.dump(job, f, ensure_ascii=False)
                log("%s — %s: %s (%.0f с)" % (job.get("artist"), job.get("title"), res, time.time() - t))
                continue
        log("%s — %s: %s (%.0f с)" % (job.get("artist"), job.get("title"), res, time.time() - t))
        _rm(jp)
        _rm(job.get("wav", ""))
    return 0


def cmd_run(a):
    path, artist, title, dur = a[0], a[1], a[2], int(a[3])
    print(process({"artist": artist, "title": title, "dur": dur, "wav": path, "offset": 0.0}))


def cmd_status():
    print("включено" if not os.path.exists(FLAG) else "выключено")
    q = sorted(glob.glob(os.path.join(QUEUE, "*.json")), key=os.path.getmtime)
    print("в очереди: %d" % len(q))
    for jp in q:
        try:
            j = json.load(open(jp))
            print("  %s — %s" % (j["artist"], j["title"]))
        except (OSError, ValueError, KeyError):
            pass
    print("обработчик: %s" % ("работает" if worker_busy() else "нет"))
    try:
        print("".join(open(LOG).readlines()[-8:]), end="")
    except OSError:
        pass


def main():
    a = sys.argv[1:]
    if a == ["daemon"]:
        run_daemon()
    elif a == ["worker"]:
        return run_worker()
    elif a == ["status"]:
        cmd_status()
    elif a in (["on"], ["off"]):
        if a[0] == "on":
            _rm(FLAG)
        else:
            os.makedirs(os.path.dirname(FLAG), exist_ok=True)
            open(FLAG, "w").close()
        print(a[0])
    elif a and a[0] == "run" and len(a) == 5:
        cmd_run(a[1:])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
