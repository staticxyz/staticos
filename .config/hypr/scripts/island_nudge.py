#!/usr/bin/env python3
"""«Пора к делу» — счётчик прокрастинации для островка. 20.10.2026.

Просьба: «если я просидел долго за просмотром видео в браузере или опять
настраиваю дотфайлы — сверху в островке должна появиться плашка: „Бро, ты слишком
долго сидишь, иди подыши“, „Сэр, пора получать офферы“… Чисто визуально, ничего не
закрывать. Текст печатается слева направо, как в старых терминалах. Приоткрыть —
сколько времени я уже сижу».

Здесь только счёт; рисует island.py (страница nudge, компакт с печатью по буквам).

Что считается
-------------
* video — браузер в фокусе, сайт видео (VIDEO_SITES по заголовку вкладки) или в окне
  играет видео (idle_guard.video_in_focus);
* rice — nvim в терминале в фокусе, и хотя бы один nvim открыт в домашней папке,
  ~/.config, ~/.local или ~/Projects/staticos (то есть снова дотфайлы, а не проект).

Серия идёт, пока окно этого вида в фокусе; отошёл на другое — время стоит, а отошёл
дольше BREAK_S (или экран заблокирован, или машина спала) — серия обнуляется.
Порог — nudge_min минут (настройки островка), потом напоминание каждые nudge_every минут
с другой фразой.

    island_nudge.py           что сейчас в фокусе и к какому виду относится (проверка)
"""
import json
import os
import random
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

BREAK_S = 300            # отошёл дольше — серия с нуля
MAX_STEP = 30            # больше за один шаг не начислять (подвис цикл, скачок часов)
SCREENTIME = os.path.expanduser("~/.local/share/jarvis/screentime")
VIDEO_SITES = ("YouTube", "Twitch", "Netflix", "Кинопоиск", "Rutube", "Kick", "VK Видео", "Anime",
               "Аниме", "HDRezka", "Rezka", "Okko", "IVI", "Иви")
HOME = os.path.expanduser("~")
RICE_DIRS = (os.path.join(HOME, ".config"), os.path.join(HOME, ".local"),
             os.path.join(HOME, "Projects", "staticos"))
NAME = {"video": "Видео", "rice": "Дотфайлы"}

# Фразы: общие и по виду. Первая серия — помягче, дальше — твёрже (уровень = сколько раз
# уже напоминали за эту серию).
PHRASES = {
    "any": [
        "Бро, ты слишком долго сидишь. Иди подыши",
        "Сэр, пора получать офферы",
        "Лимит на прокрастинацию исчерпан. Пора к работе",
        "Встаньте, разомнитесь, сэр. Потом — к делу",
        "Сэр, офферы сами себя не получат",
    ],
    "video": [
        "Ещё одно видео — и ещё час. Хватит, сэр",
        "YouTube подождёт. Работа — нет",
        "Сэр, вы смотрите, как живут другие. Пора жить своё",
    ],
    "rice": [
        "Дотфайлы идеальны, сэр. Резюме — нет",
        "Ещё один бинд не принесёт оффер",
        "Рабочий стол уже красивый. Пора на нём поработать",
    ],
    "hard": [
        "Сэр, это уже не отдых. Закрывайте и к делу",
        "ВНИМАНИЕ: прокрастинация > лимит. Требуется работа",
        "Бро. Серьёзно. Встань и займись делом",
    ],
}


def phrase(kind, level, last=None):
    pool = PHRASES["hard"] + PHRASES.get(kind, []) if level >= 2 else PHRASES["any"] + PHRASES.get(kind, [])
    pool = [p for p in pool if p != last] or pool
    return random.choice(pool)


def _niri(*what):
    try:
        out = subprocess.run(["niri", "msg", "-j", *what], capture_output=True, text=True, timeout=2).stdout
        return json.loads(out or "null")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def rice_session():
    """Есть ли nvim в домашней папке или в папках дотфайлов (cwd процесса)."""
    try:
        out = subprocess.run(["ps", "-u", str(os.getuid()), "-o", "pid=,comm="], capture_output=True,
                             text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        parts = line.split(None, 1)
        if len(parts) != 2 or parts[1].strip() not in ("nvim", "vim"):
            continue
        try:
            cwd = os.readlink("/proc/%s/cwd" % parts[0])
        except OSError:
            continue
        if cwd == HOME or any(cwd == d or cwd.startswith(d + os.sep) for d in RICE_DIRS):
            return True
    return False


def classify(w):
    """Окно в фокусе → (вид, что, app, подробность для экранного времени) или None."""
    if not w:
        return None
    import screentime_daemon as SD
    app = SD.app_key(w)
    title = w.get("title") or ""
    if app in SD.BROWSERS:
        site = SD.detail_of(app, title)
        if site in VIDEO_SITES:
            return ("video", site, app, site)
        try:
            import idle_guard
            if idle_guard.video_in_focus() is not None:
                return ("video", site or "Видео", app, site)
        except Exception:
            pass
        return None
    if app in SD.TERMINALS and SD.detail_of(app, title) == "nvim" and rice_session():
        return ("rice", "nvim · дотфайлы", app, "nvim")
    return None


def locked():
    try:
        import screentime_daemon as SD
        return SD.screen_locked()
    except Exception:
        return False


def today_sec(app, detail):
    """Сколько за сегодня по экранному времени (счётчик пишет раз в 30 с)."""
    try:
        d = json.load(open(os.path.join(SCREENTIME, time.strftime("%Y-%m-%d") + ".json")))
    except (OSError, ValueError):
        return None
    if detail:
        v = (d.get("details") or {}).get(app, {}).get(detail)
    else:
        v = (d.get("apps") or {}).get(app)
    return int(v) if v else None


def sample():
    """Один опрос (в потоке): что в фокусе, заблокирован ли экран, сколько за день."""
    if locked():
        return {"locked": True}
    c = classify(_niri("focused-window"))
    if not c:
        return {"locked": False, "kind": None}
    kind, what, app, detail = c
    return {"locked": False, "kind": kind, "what": what, "today": today_sec(app, detail)}


class Streaks:
    """Серии по видам. tick() → вид, по которому пора напомнить, или None."""

    def __init__(self):
        self.s = {}              # вид → {"sec", "away", "what", "level", "next", "start", "today", "text"}
        self.mono = self.wall = None

    def tick(self, smp, min_s, every_s, now_mono=None, now_wall=None):
        now_mono = time.monotonic() if now_mono is None else now_mono
        now_wall = time.time() if now_wall is None else now_wall
        dt = 0.0 if self.mono is None else now_mono - self.mono
        slept = self.wall is not None and (now_wall - self.wall) - dt > 60
        self.mono, self.wall = now_mono, now_wall
        if slept or smp.get("locked"):
            self.s.clear()
            return None
        dt = max(0.0, min(MAX_STEP, dt))
        kind = smp.get("kind")
        for k in list(self.s):
            if k != kind:
                st = self.s[k]
                st["away"] += dt
                if st["away"] >= BREAK_S:
                    del self.s[k]
        if not kind:
            return None
        st = self.s.setdefault(kind, {"sec": 0.0, "away": 0.0, "level": 0, "next": min_s,
                                      "start": now_wall, "text": None})
        st["sec"] += dt
        st["away"] = 0.0
        st["what"] = smp.get("what") or NAME.get(kind, kind)
        st["today"] = smp.get("today")
        st["t"] = now_mono
        if st["sec"] >= st["next"]:
            st["text"] = phrase(kind, st["level"], st["text"])
            st["level"] += 1
            st["next"] = st["sec"] + every_s
            return kind
        return None

    def active(self, min_s):
        """Вид с самой длинной серией за порогом (для страницы и нити), или None."""
        ks = [k for k, st in self.s.items() if st["sec"] >= min_s and st["level"] > 0]
        return max(ks, key=lambda k: self.s[k]["sec"]) if ks else None


if __name__ == "__main__":
    w = _niri("focused-window")
    print("окно:", (w or {}).get("app_id"), "|", (w or {}).get("title"))
    print("вид:", classify(w))
    print("nvim в дотфайлах:", rice_session())
    print("опрос:", sample())
