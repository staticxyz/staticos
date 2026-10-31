#!/usr/bin/env python3
"""Замок: игра в окне (Super+Shift+B, Пуск, rofi; 30.10.2026). Логика и деньги — hub/castle.py,
рисунок — castle_art.py, звуки — castle_sound.py.

Просьба: «Он должен быть и минималистичным, и похожим на игру… Чем увлекательнее игра — тем больше
мне хочется в нее играть». Правила те же: энергия не теряется, ступени идут по порядку. Сцена рисуется
в маленький холст и растягивается без сглаживания, вокруг неё чёткие рамки и кнопки: «Не хватает рамок
в виде Skeet», «понятный интерфейс с кнопками… управление мышкой и клавиатурой обе должны быть».
Всё, что есть на клавишах, есть и кнопкой, на кнопке написана её клавиша; «Как играть» — памятка.

С 31.10: «Мы не будем ограничиваться одним замком, т.к. игра закончится если его построить». Семь
земель на карте (Tab), у каждой свои ступени и дар; сюжет — реплики после построек, прочитанное лежит
в meta castle_story_seen и перечитывается в хронике (c). Находки падают сами по мере заработка.

Отмеченный поход на собеседование ждёт следующего открытия: сундук, фанфары, энергия летит в счёт
(meta castle_seen — какие походы и сколько энергии уже показаны). Обычный прирост — короткое «+N».

    h l, j k, стрелки   ступень             m                  звук
    Tab                 карта               c                  хроника
    gg, G               первая / последняя  u, Ctrl+Z          отменить постройку
    Enter, b, пробел    построить, открыть  r, Ctrl+R          вернуть постройку
    ?, F1               как играть          Esc, q, Ctrl+Q     закрыть
"""
import json
import math
import os
import random
import sys
import time
import types

import gi
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("PangoCairo", "1.0")
import cairo  # noqa: E402
from gi.repository import Gdk, Gio, GLib, Gtk, Pango, PangoCairo  # noqa: E402

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser("~/.local/share/hub"))

import castle as CS  # noqa: E402
import castle_art as A  # noqa: E402
import castle_biomes as B  # noqa: E402
import castle_lands as L  # noqa: E402
import castle_sound as SND  # noqa: E402
import growth as G  # noqa: E402
import hublib  # noqa: E402
import interviews as IV  # noqa: E402
import routine_app as R  # noqa: E402
import title_strip  # noqa: E402

APP_ID = "com.jarvis.castle"
RUN = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
STATE = os.path.expanduser("~/.config/hypr/state/castle-window.json")
SEEN = "castle_seen"
HELP_SEEN = "castle_help_seen"
STORY = "castle_story_seen"
FONT = "PxPlus HP 100LX 6x8"
GLYPH = "\U000f011a"
PANEL = 200                  # высота нижней панели
PAD = 6                      # от рамки окна до содержимого
ACT_W = 320                  # ширина группы «Действия»
MIN_W, MIN_H = 820, 620
SIZE = (1040, 780)
JOB = 1.9                    # сек на постройку
HITS = 7                     # ударов молотка за постройку
OPEN_MIN = 1.0               # сколько длится вскрытие, пока Enter не закрывает
LOAD_SEC = 5
HEAD_H, FOOT_H = 170, 150    # экран награды: место над сундуком и под ним
CHEST_LH = 44                # сундук с крышкой на холсте, высота
SPARKS_FLY = 14              # сколько пучков энергии летит в счёт
MS = 3                       # масштаб карты: мельче сцены, на ней много мелочи
CPS = 45                     # букв в секунду в диалоге
K_Q, K_R, K_U, K_G, K_H, K_J, K_K, K_L, K_B, K_Z, K_M, K_SLASH = 24, 27, 30, 42, 43, 44, 45, 46, 56, 52, 58, 61
K_C = 54
ENTER = (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_space)
WHITE, INK = (1, 1, 1), (0.05, 0.05, 0.08)
GOLD = A.GOLD
WARM = A.rgb("#ff8a5c")      # не хватает
CONFETTI = (A.GOLD, A.RED, A.WATER_L, A.GRASS_L, WHITE)


def ease_out(t):
    return 1 - (1 - t) ** 3


class Game:
    """Вся игра без окна: draw рисует в любой cairo, поэтому снимки и проверка не трогают экран."""
    def __init__(self, conn, test=False):
        self.conn, self.test = conn, test
        self.st, self.rows, self.sel, self.C = None, [], 0, None
        self.style, self.acc = None, None
        self.t, self.last_load, self.stamp = 0.0, 0.0, None
        self.hits, self.hover, self.maxed, self.active = [], None, False, True
        self.world, self.canvas, self.geo = None, None, None
        self.S, self.w, self.h = 5, *SIZE
        self.f, self.top, self.skeet, self.view = 0, 0, False, (0, 0, *SIZE)
        self.back, self.back_key = None, None
        self.help = False
        self.shown = 0.0
        self.parts, self.flies, self.floats = [], [], []
        self.flash, self.shake, self.nudge = 0.0, 0.0, -9.0
        self.pop, self.beat = -9.0, 0    # счёт только что вырос
        self.job, self.banner, self.reward = None, None, None
        self.undos, self.redos, self.chord = [], [], ""
        self.bx, self.goal, self.frame, self.flip, self.wander = None, None, "stand", False, 3.0
        self.fixed_hour = None
        self.land, self.screen, self.map_sel = None, "land", 0
        self.map_surf, self.map_key, self.map_cv = None, None, None
        self.talk, self.talk_t0 = [], 0.0
        self.book, self.book_y, self.book_h, self.find_sel = None, 0, 0, 0
        self.story = self.read_story()
        self.rnd = random.Random()
        self.close = lambda: None
        self.load()
        self.shown = float(self.st["balance"])
        self.to_next()

    # ── данные ────────────────────────────────────────────────────────────
    def load(self):
        self.st = CS.state(self.conn, self.land)
        self.land = self.st["land"]
        self.rows = CS.step_rows(self.st)
        self.stamp = G.stamp()
        self.style = R.style_name()
        self.C = R.colors(self.style)
        self.acc = tuple(self.C["acc"])
        A.set_energy(self.acc)

    def to_next(self):
        n = self.st["next"]
        self.sel = [r[0] for r in self.rows].index(n["key"]) if n else len(self.rows) - 1

    def seen(self):
        try:
            return json.loads(hublib.meta_get(self.conn, SEEN) or "")
        except ValueError:
            return None

    def mark_seen(self):
        if not self.test:
            hublib.meta_set(self.conn, SEEN, json.dumps(dict(
                ids=[r["id"] for r in IV.visits(self.conn)], total=self.st["total"], offer=self.st["offer"],
                finds=self.st["found"])))

    def news(self):
        """Что случилось, пока окно было закрыто: поход и оффер — сундук, остальное — короткое «+N»."""
        seen = self.seen()
        if seen is None:                             # самый первый запуск: прошлое наградами не считаем
            self.mark_seen()
            return
        rows = IV.visits(self.conn)
        fresh = [r for r in rows if r["id"] not in seen["ids"]]
        gain = self.st["total"] - seen["total"]
        offer = self.st["offer"] and not seen.get("offer")
        items = [(i, CS.find_item(i)) for i in range(seen.get("finds", 0), self.st["found"])]
        if fresh or offer or items:
            opened = [s[1] for s in CS.land_steps(self.land) if len(rows) - len(fresh) < s[3] <= len(rows)]
            self.start_reward([r["note"] for r in fresh], max(gain, 0), opened, offer, items)
        elif gain > 0:
            self.shown = float(self.st["balance"] - gain)
            self.income(gain)
            self.mark_seen()
        elif gain < 0:
            self.mark_seen()

    # ── сюжет ─────────────────────────────────────────────────────────────
    def read_story(self):
        try:
            return set(json.loads(hublib.meta_get(self.conn, STORY) or "[]"))
        except ValueError:
            return set()

    def story_of(self, key):
        if key == "prologue":
            return L.PROLOGUE
        if key.startswith("arrive:"):
            return L.ARRIVE.get(key[7:], ())
        if key.startswith("done:"):
            return L.DONE.get(key[5:], ())
        return L.LINES.get(key, ())

    def tell(self, key):
        """Реплики один раз: сказанное остаётся в хронике."""
        lines = self.story_of(key)
        if key in self.story or not lines:
            return
        self.story.add(key)
        if not self.test:
            hublib.meta_set(self.conn, STORY, json.dumps(sorted(self.story)))
        if not self.talk:
            self.talk_t0 = self.t + 0.4
        self.talk.extend(lines)

    def typed(self):
        return int((self.t - self.talk_t0) * CPS)

    def talk_next(self):
        """Первое нажатие дописывает реплику, второе переходит к следующей."""
        if self.typed() < len(self.talk[0][1]):
            self.talk_t0 = -1e6
            return
        self.talk.pop(0)
        self.talk_t0 = self.t
        self.snd("select")
        if not self.talk:
            self.first_help()

    def talk_skip(self):
        self.talk = []
        self.first_help()

    # ── карта ─────────────────────────────────────────────────────────────
    def open_map(self):
        if not self.job:
            self.screen = "map"
            self.map_sel = CS.KEYS.index(self.land)
            self.snd("select")

    def close_map(self):
        self.screen = "land"
        self.snd("select")

    def map_pick(self, i):
        i = max(0, min(len(L.LANDS), i))
        if i != self.map_sel:
            self.map_sel = i
            self.snd("select")

    def enter(self):
        """Войти в выбранную землю; закрытая только качнёт кнопку."""
        if self.map_sel >= len(L.LANDS) or not self.st["lands"][self.map_sel]["open"]:
            self.snd("soft")
            self.nudge = self.t
            return
        k = L.LANDS[self.map_sel]["key"]
        if k != self.land:
            self.land = k
            self.undos.clear()
            self.redos.clear()
            self.load()
            self.to_next()
        self.close_map()
        self.tell("arrive:" + k)

    # ── звуки и частицы ───────────────────────────────────────────────────
    def snd(self, name):
        if not self.test:
            SND.play(name)

    def burst(self, x, y, n, cols, speed=30, up=20, life=0.8, grav=70, size=1):
        room = 320 - len(self.parts)
        for _ in range(min(n, room)):
            ang = self.rnd.uniform(0, 6.283)
            v = self.rnd.uniform(0.25, 1) * speed
            ttl = self.rnd.uniform(0.5, 1) * life
            self.parts.append([x, y, math.cos(ang) * v, math.sin(ang) * v - up, ttl, ttl, self.rnd.choice(cols),
                               size + self.rnd.randrange(2), grav])

    def throw(self, n, gain, x, y, dest, delay=0.0, dur=0.7):
        """Энергия разлетается из (x, y) и садится в dest; gain — на сколько вырастет счёт."""
        for i in range(n):
            self.flies.append(dict(x=x + self.rnd.uniform(-6, 6), y=y + self.rnd.uniform(-4, 4), dest=dest,
                                   t0=self.t + delay + i * 0.05, dur=dur + self.rnd.uniform(0, 0.2),
                                   arc=self.rnd.uniform(14, 34), value=gain / n))

    def income(self, gain):
        """Обычный прирост: энергия выходит из земли и летит в счёт."""
        W = self.world_ready()
        self.floats.append(dict(text="+%d" % gain, x=self.view[0] + 170, y=self.view[1] + 100,
                                t0=self.t + 0.1, dur=1.8))
        self.throw(min(SPARKS_FLY, max(4, gain)), gain, W.ax + 40, W.ground + 6, "count", delay=0.15)

    def world_ready(self):
        self.layout(self.w, self.h)
        return self.world

    # ── постройка ─────────────────────────────────────────────────────────
    def press(self):
        """Enter и большая кнопка: дальше по награде; стоим не на очередной ступени — вернуться к ней."""
        if self.reward:
            self.advance()
        elif self.talk:
            self.talk_next()
        elif self.screen == "map":
            self.enter()
        elif not self.job:
            if not self.st["next"]:                  # земля достроена: дальше на карту
                self.open_map()
            elif self.rows[self.sel][0] != self.st["next"]["key"]:
                self.to_next()
                self.snd("select")
            else:
                self.build()

    def build(self):
        n = self.st["next"]
        if not n or not n["ready"]:
            self.snd("soft")
            self.nudge = self.t
            return
        gid, _said = CS.build(self.conn, land=self.land)
        if gid:
            row = G.get(self.conn, gid)
            self.undos.append(row)
            self.redos.clear()
            self.start_job(CS.local(row["note"]))

    def start_job(self, key):
        self.load()
        self.to_next()
        W = self.world_ready()
        x0, y0, x1, y1 = A.part_box(key, self.acc, self.land)
        self.job = dict(key=key, t0=self.t, hits=0, box=(x0, y0, x1, y1))
        self.goal = W.ax + (x0 + x1) // 2 - 12
        self.flip = self.goal < (self.bx or 0)
        self.throw(8, 0, *self.count_dest(), (W.ax + (x0 + x1) // 2, W.ay + (y0 + y1) // 2), dur=0.5)

    def job_tick(self):
        job, W = self.job, self.world
        p = (self.t - job["t0"]) / JOB
        x0, y0, x1, y1 = job["box"]
        due = min(HITS, int(p * HITS))
        if due > job["hits"]:
            job["hits"] = due
            self.snd("hammer")
            ry = W.ay + y1 - (y1 - y0) * due / HITS
            self.burst(W.ax + self.rnd.randint(x0, x1), ry, 8, (A.LIGHT, A.GOLD, A.STONE), speed=26, up=14, life=0.45)
            self.shake = max(self.shake, 0.6)
        self.frame = "down" if (p * HITS) % 1 < 0.35 else "up"
        if p >= 1:
            self.finish_job()

    def finish_job(self):
        job, W = self.job, self.world
        x0, y0, x1, y1 = job["box"]
        self.job = None
        self.frame = "stand"
        self.snd("thump")
        self.snd("built")
        self.flash, self.shake = 0.55, 2.0
        for x in range(x0, x1, 3):
            self.burst(W.ax + x, W.ay + y1, 2, (A.LIGHT, A.STONE, A.EARTH), speed=18, up=10, life=0.8, grav=30)
        self.burst(W.ax + (x0 + x1) // 2, W.ay + (y0 + y1) // 2, 50, CONFETTI + (self.acc,), speed=60, up=30, life=1.4)
        self.banner = dict(head="ПОСТРОЕНО", text=self.name_of(job["key"]), t0=self.t, dur=2.6)
        self.tell(CS.full(self.land, job["key"]))
        if not self.st["next"]:
            self.tell("done:" + self.land)

    def name_of(self, key):
        return next((r[1] for r in self.rows if r[0] == key), key)

    def undo(self):
        if self.undos and not self.job:
            r = self.undos.pop()
            G.remove(self.conn, r["id"])
            self.redos.append(r)
            self.load()
            self.to_next()

    def redo(self):
        if self.redos and not self.job:
            r = self.redos.pop()
            G.put_back(self.conn, r)
            self.undos.append(r)
            self.start_job(CS.local(r["note"]))

    # ── награда ───────────────────────────────────────────────────────────
    def start_reward(self, names, gain, opened, offer=False, items=()):
        self.shown = float(self.st["balance"] - gain)
        if offer:
            head, sub = "ОФФЕР!", "Замок коронован"
        elif names:
            head = "СОБЕСЕДОВАНИЕ ЗАСЧИТАНО" if len(names) < 2 else "ЗАСЧИТАНО ПОХОДОВ: %d" % len(names)
            sub = " · ".join(names)
        else:
            head, sub = "НАХОДКА" if len(items) < 2 else "НАХОДОК: %d" % len(items), "Земля отдаёт то, что прятала"
        self.reward = dict(head=head, sub=sub, gain=gain, opened=opened, items=list(items), offer=offer, phase="fall",
                           t0=self.t, at=0.0)
        self.parts, self.flies = [], []

    def chest_pos(self):
        """Левый верх сундука на холсте: заголовок, сундук и счёт стоят одним блоком по центру окна."""
        W, S = self.world_ready(), self.S
        room = self.view[3]
        block = HEAD_H + CHEST_LH * S + FOOT_H
        return W.lw // 2 - 20, (max(16, (room - block) // 2) + HEAD_H) // S + 14

    def advance(self):
        r = self.reward
        if r["phase"] == "wait":
            self.open_chest()
        elif r["phase"] == "open" and self.t - r["at"] > OPEN_MIN:
            offer = r["offer"]
            self.reward = None
            self.shown = float(self.st["balance"])
            self.flies = []
            self.to_next()
            if offer:
                self.tell("crown")
            self.first_help()

    def first_help(self):
        """Пролог и памятка сами открываются один раз: дальше они в хронике и на кнопке «Как играть»."""
        if self.test or self.reward:
            return
        self.tell("prologue")
        if not self.talk and not hublib.meta_get(self.conn, HELP_SEEN):
            hublib.meta_set(self.conn, HELP_SEEN, "1")
            self.help = True

    def open_chest(self):
        r = self.reward
        r["phase"], r["at"] = "open", self.t
        self.snd("open")
        self.snd("victory")
        self.flash, self.shake = 1.0, 3.0
        x, y = self.chest_pos()
        self.burst(x + 20, y + 4, 160, CONFETTI + (self.acc,), speed=95, up=55, life=2.6, grav=46)
        self.throw(SPARKS_FLY, r["gain"], x + 20, y, "count", delay=0.3, dur=0.9)
        self.mark_seen()

    def reward_tick(self):
        r = self.reward
        if r["phase"] == "fall" and self.t - r["t0"] >= 0.55:
            r["phase"] = "wait"
            self.snd("land")
            self.shake = 2.5
            x, y = self.chest_pos()
            self.burst(x + 20, y + 30, 26, (A.LIGHT, A.EARTH, A.STONE), speed=32, up=8, life=0.7, grav=40)

    # ── шаг времени ───────────────────────────────────────────────────────
    def animating(self):
        return bool(self.job or self.reward or self.flies or self.parts or self.banner or self.flash > 0
                    or self.floats or abs(self.shown - self.st["balance"]) > 0.5
                    or (self.talk and self.typed() < len(self.talk[0][1])))

    def tick(self, dt):
        dt = min(dt, 0.1)
        self.t += dt
        if self.t - self.last_load >= LOAD_SEC and not self.job and not self.reward:
            self.last_load = self.t
            self.load()
            if not self.test:
                self.news()
        if self.job:
            self.job_tick()
        if self.reward:
            self.reward_tick()
        self.flash = max(0.0, self.flash - dt * 2.2)
        self.shake = max(0.0, self.shake - dt * 7)
        for p in self.parts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += p[8] * dt
            p[4] -= dt
        self.parts = [p for p in self.parts if p[4] > 0]
        self.fly_tick()
        self.floats = [f for f in self.floats if self.t - f["t0"] < f["dur"]]
        if self.banner and self.t - self.banner["t0"] > self.banner["dur"]:
            self.banner = None
        if not self.flies and not self.reward:      # счёт докручивается до настоящего числа
            d = self.st["balance"] - self.shown
            self.shown += d * min(1, dt * 9) if abs(d) > 0.5 else d
        self.walk(dt)

    def fly_tick(self):
        for f in self.flies:
            if self.t >= f["t0"] + f["dur"]:
                f["done"] = True
                if f["value"] > 0:
                    self.shown += f["value"]
                    self.pop = self.t
                    if int(self.t * 12) != self.beat:      # по одному щелчку на кадр, а не на пучок
                        self.beat = int(self.t * 12)
                        self.snd("brick")
        self.flies = [f for f in self.flies if not f.get("done")]

    def walk(self, dt):
        W = self.world
        if W is None:
            return
        if self.bx is None:
            self.bx, self.goal = float(W.fire_x + 10), float(W.fire_x + 10)
        if self.job is None and self.t > self.wander:
            self.wander = self.t + self.rnd.uniform(5, 11)
            self.goal = self.rnd.choice((W.fire_x + 8, W.ax + 16, W.ax + 44, W.ax + 88))
        d = self.goal - self.bx
        if abs(d) > 1:
            self.bx += math.copysign(min(abs(d), dt * (46 if self.job else 16)), d)
            self.flip = d < 0
            if not self.job:
                self.frame = "walk" if int(self.t * 7) % 2 else "stand"
        elif not self.job:
            self.frame = "stand"

    # ── ввод ──────────────────────────────────────────────────────────────
    def pick(self, i):
        i = max(0, min(len(self.rows) - 1, i))
        if i != self.sel:
            self.sel = i
            self.snd("select")

    def toggle_sound(self):
        SND.set_muted(not SND.muted())
        self.snd("select")

    def toggle_help(self):
        self.help = not self.help
        self.snd("select")

    def toggle_book(self):
        self.book = None if self.book is not None else CS.KEYS.index(self.land)
        self.book_y = 0
        self.snd("select")

    def book_turn(self, d):
        pages = len(L.LANDS) + 1
        self.book = (self.book + d) % pages
        self.book_y = 0
        self.snd("select")

    def scroll(self, d):
        if self.book is not None:
            self.book_y = max(0, min(self.book_h, self.book_y + d * 40))

    def book_key(self, code, val):
        if val in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter) or code in (K_Q, K_C):
            self.toggle_book()
        elif val == Gdk.KEY_Left or code == K_H:
            self.book_turn(-1)
        elif val == Gdk.KEY_Right or code == K_L:
            self.book_turn(1)
        elif val == Gdk.KEY_Down or code == K_J:
            if self.book == len(L.LANDS):
                self.find_sel = min(len(L.FINDS) - 1, self.find_sel + 1)
            else:
                self.scroll(1)
        elif val == Gdk.KEY_Up or code == K_K:
            if self.book == len(L.LANDS):
                self.find_sel = max(0, self.find_sel - 1)
            else:
                self.scroll(-1)
        return True

    def map_press(self, code, val):
        if val in ENTER or code == K_B:
            self.enter()
        elif val == Gdk.KEY_Tab:
            self.close_map()
        elif val in (Gdk.KEY_Left, Gdk.KEY_Up) or code in (K_H, K_K):
            self.map_pick(self.map_sel - 1)
        elif val in (Gdk.KEY_Right, Gdk.KEY_Down) or code in (K_L, K_J):
            self.map_pick(self.map_sel + 1)
        elif val == Gdk.KEY_F1 or code == K_SLASH:
            self.toggle_help()
        elif code == K_C:
            self.toggle_book()
        elif code == K_M:
            self.toggle_sound()
        else:
            return False
        return True

    def key(self, code, val, ctrl):
        chord, self.chord = self.chord, ""
        if self.help:
            if val in (Gdk.KEY_Escape, Gdk.KEY_F1) or val in ENTER or code in (K_Q, K_SLASH):
                self.toggle_help()
            return True
        if self.book is not None:
            return self.book_key(code, val)
        if self.talk and not self.reward:
            if val in ENTER or code == K_B:
                self.talk_next()
            elif val == Gdk.KEY_Escape or code == K_Q:
                self.talk_skip()
            return True
        if val == Gdk.KEY_Escape or code == K_Q:
            if self.screen == "map" and not self.reward:
                self.close_map()
            else:
                self.close()
        elif self.reward:
            if val in ENTER or code == K_B:
                self.press()
        elif self.screen == "map":
            return self.map_press(code, val)
        elif val in ENTER or code == K_B:
            self.press()
        elif val == Gdk.KEY_Tab:
            self.open_map()
        elif code == K_C:
            self.toggle_book()
        elif ctrl and code == K_Z:
            self.undo()
        elif code == K_R:
            self.redo()
        elif code == K_U:
            self.undo()
        elif val == Gdk.KEY_F1 or code == K_SLASH:
            self.toggle_help()
        elif code == K_M:
            self.toggle_sound()
        elif val in (Gdk.KEY_Left, Gdk.KEY_Up) or code in (K_H, K_K):
            self.pick(self.sel - 1)
        elif val in (Gdk.KEY_Right, Gdk.KEY_Down) or code in (K_L, K_J):
            self.pick(self.sel + 1)
        elif code == K_G:
            if val == Gdk.KEY_G or val == 0x6cf:     # Shift+G, в том числе в русской раскладке
                self.pick(len(self.rows) - 1)
            elif chord == "g":
                self.pick(0)
            else:
                self.chord = "g"
        else:
            return False
        return True

    def hit(self, x, y):
        for (hx, hy, hw, hh), name in reversed(self.hits):
            if hx <= x < hx + hw and hy <= y < hy + hh:
                return name
        return None

    def click(self, name):
        if self.help:
            self.toggle_help()
        elif self.book is not None:
            self.book_click(name)
        elif self.talk and not self.reward:
            self.talk_next()
        elif name == "build" or self.reward:
            self.press()
        elif name == "map":
            self.close_map() if self.screen == "map" else self.open_map()
        elif name == "book":
            self.toggle_book()
        elif isinstance(name, tuple):                # земля на карте: выбрать, щелчок по выбранной — войти
            if name[1] == self.map_sel:
                self.enter()
            else:
                self.map_pick(name[1])
        elif name == "map_prev":
            self.map_pick(self.map_sel - 1)
        elif name == "map_next":
            self.map_pick(self.map_sel + 1)
        elif name == "mute":
            self.toggle_sound()
        elif name == "help":
            self.toggle_help()
        elif name == "undo":
            self.undo()
        elif name == "redo":
            self.redo()
        elif name in ("prev", "next"):
            self.pick(self.sel + (1 if name == "next" else -1))
        elif isinstance(name, int):
            self.pick(name)

    def book_click(self, name):
        if name == "book_prev":
            self.book_turn(-1)
        elif name == "book_next":
            self.book_turn(1)
        elif isinstance(name, tuple) and name[0] == "find":
            self.find_sel = name[1]
        elif name == "book_close":
            self.toggle_book()

    # ── рисование ─────────────────────────────────────────────────────────
    def hour(self):
        if self.fixed_hour is not None:
            return self.fixed_hour
        now = time.localtime()
        return now.tm_hour + now.tm_min / 60

    def layout(self, w, h):
        self.w, self.h = w, h
        self.skeet = self.C["frame"] == "skeet"
        bare = R.stack_on()                          # в стопке полосу и рамку рисует stack_bars.py
        self.f = 0 if bare else 6 if self.skeet else 1
        self.top = 0 if bare else self.f + title_strip.height()
        vx, vy = self.f + PAD, self.top + PAD
        vw, vh = w - 2 * vx, h - vy - self.f - PAD - PANEL
        self.view = (vx, vy, vw, vh)
        S = max(2, min(vw // 172, vh // (A.H + 14)))
        lw, lh = math.ceil(vw / S), math.ceil(vh / S)
        geo = (lw, lh, vh // S, self.acc, self.land)
        if geo != self.geo:
            self.geo, self.S = geo, S
            self.world = A.World(*geo)
            self.canvas = cairo.ImageSurface(cairo.FORMAT_RGB24, lw, lh)
            self.bx = None

    def scene(self):
        W, t, cv = self.world, self.t, cairo.Context(self.canvas)
        hour = self.hour()
        sky = A.sky_at(hour)
        built = self.st["built"]
        job = self.job
        cv.set_antialias(cairo.ANTIALIAS_NONE)
        cv.set_source_surface(W.backdrop(hour), 0, 0)
        cv.paint()
        W.stars_at(cv, t, sky)
        W.clouds_at(cv, t, sky)
        W.birds_at(cv, t, sky)
        cv.set_source_surface(W.foreground(hour, built, self.st["balance"], job["key"] if job else None), 0, 0)
        cv.paint()
        if W.land == "bay" or ("moat" in built and not (job and job["key"] == "moat")):
            W.water(cv, t, sky)
        if "flag" in built and not (job and job["key"] == "flag"):
            W.flags(cv, t, sky)
        W.lights(cv, t, sky, built)
        key = self.rows[self.sel][0]
        if key not in built and not self.reward:      # выбранная ступень проступает на чертеже
            cv.set_source_surface(W.surf(key), W.ax, W.ay)
            cv.paint_with_alpha(0.28 + 0.14 * math.sin(t * 3.5))
        if job:
            x0, y0, x1, y1 = job["box"]
            cut = y1 - (y1 - y0) * job["hits"] / HITS
            cv.save()
            cv.rectangle(W.ax + x0, W.ay + cut, x1 - x0, y1 - cut)
            cv.clip()
            cv.set_source_surface(W.surf(job["key"]), W.ax, W.ay)
            cv.paint()
            cv.restore()
        W.camp(cv, t, W.fire_x, sky)
        W.fireflies(cv, t, sky)
        if self.bx is not None:
            A.builder(cv, int(self.bx), W.ground + 15, self.frame, self.flip)
        W.weather(cv, t, sky)
        if self.reward:
            self.reward_scene(cv)
        for p in self.parts:
            A.box(cv, int(p[0]), int(p[1]), p[7], p[7], p[6], min(1, p[4] / p[5] * 2.5))
        self.draw_flies(cv)

    def map_point(self, at):
        return int(at[0] * (self.view[2] / MS)), int(at[1] * (self.view[3] / MS))

    def map_scene(self):
        """Карта на своём холсте: картинка берётся из кэша, сверху тропы, замки и Строитель."""
        vw, vh = self.view[2:]
        mw, mh = vw // MS + 1, vh // MS + 1
        lands = self.st["lands"]
        lit = tuple(x["key"] for x in lands if x["open"])
        shown = self.st["scraps"] >= L.SCRAPS
        key = (mw, mh, lit, shown)
        if key != self.map_key:
            self.map_key = key
            self.map_surf = B.world_map(mw, mh, [(x["key"], x["at"]) for x in L.LANDS], set(lit), L.BEYOND, shown)
            self.map_cv = cairo.ImageSurface(cairo.FORMAT_RGB24, mw, mh)
        cv = cairo.Context(self.map_cv)
        cv.set_antialias(cairo.ANTIALIAS_NONE)
        cv.set_source_surface(self.map_surf, 0, 0)
        cv.paint()
        for i in range(len(L.LANDS) - 1):
            self.trail(cv, L.LANDS[i]["at"], L.LANDS[i + 1]["at"], GOLD if lands[i]["done"] else WHITE, 0.95 if lands[i]["done"] else 0.4)
        for i, x in enumerate(lands):
            px, py = self.map_point(L.LANDS[i]["at"])
            A.mini_castle(cv, x["key"], px - 6, py - 6, x["built"], x["done"], x["open"], self.t)
        px, py = self.map_point(L.LANDS[CS.KEYS.index(self.land)]["at"])
        A.builder(cv, px - 5, py - 18 + int(math.sin(self.t * 3) * 1.5), "stand")

    def trail(self, cv, a, b, col, alpha):
        (x0, y0), (x1, y1) = self.map_point(a), self.map_point(b)
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 5))
        nx, ny = (y0 - y1) / (n * 5), (x1 - x0) / (n * 5)
        for i in range(2, n - 1):
            p = i / n
            bend = math.sin(p * math.pi) * 7
            A.box(cv, int(x0 + (x1 - x0) * p + nx * bend), int(y0 + (y1 - y0) * p + ny * bend), 2, 2, col, alpha)

    def draw_flies(self, cv):
        for f in self.flies:
            p = (self.t - f["t0"]) / f["dur"]
            if p < 0:
                continue
            dest = self.count_dest() if f["dest"] == "count" else f["dest"]
            e = ease_out(p) if f["value"] <= 0 else p * p
            x = f["x"] + (dest[0] - f["x"]) * e
            y = f["y"] + (dest[1] - f["y"]) * e - math.sin(min(p, 1) * math.pi) * f["arc"]
            A.spark(cv, int(x), int(y))

    def count_dest(self):
        return 33 / self.S, 34 / self.S              # значок молнии в счёте, в клетках холста

    def reward_scene(self, cv):
        r = self.reward
        x, y = self.chest_pos()
        since = self.t - r["t0"]
        A.box(cv, 0, 0, self.world.lw, self.world.lh, (0.02, 0.02, 0.07), min(0.72, since * 2))
        cx, cy = x + 20, y + 10
        if r["phase"] == "open":
            self.rays(cv, cx, cy, self.t - r["at"])
        elif r["phase"] == "fall":
            y = int(-34 + (y + 34) * min(1, since / 0.55) ** 2)
        else:
            beat = (self.t - r["t0"]) % 1.1
            if beat < 0.4:
                x += round(math.sin(beat * 42) * 1.5)
        cv.save()
        cv.translate(x, y)
        cv.scale(2, 2)
        A.chest(cv, 0, 0, r["phase"] == "open", self.acc, 0.5 + 0.5 * math.sin(self.t * 6))
        cv.restore()

    def rays(self, cv, cx, cy, t):
        cv.save()
        cv.translate(cx, cy)
        cv.rotate(t * 0.5)
        reach = self.world.lw
        cv.set_source_rgba(GOLD[0], GOLD[1], GOLD[2], 0.16 + 0.05 * math.sin(t * 4))
        for i in range(10):
            a = i * 6.2832 / 10
            cv.move_to(0, 0)
            cv.line_to(math.cos(a - 0.14) * reach, math.sin(a - 0.14) * reach)
            cv.line_to(math.cos(a + 0.14) * reach, math.sin(a + 0.14) * reach)
            cv.close_path()
        cv.fill()
        cv.restore()

    def backing(self):
        """Рамка окна и фон в точку: тысячи прямоугольников, поэтому один раз, пока окно не изменилось."""
        key = (self.w, self.h, self.active, self.style, self.f, self.maxed, self.acc)
        if key != self.back_key:
            self.back_key = key
            self.back = cairo.ImageSurface(cairo.FORMAT_RGB24, self.w, self.h)
            cr = cairo.Context(self.back)
            p = R.Painter(cr)
            if self.skeet or not self.f:
                R.View.draw_frame(types.SimpleNamespace(c=self.C, active=self.active), p, self.w, self.h)
            else:
                p.rect(0, 0, self.w, self.h, self.C["bg"])
                if not self.maxed:
                    p.box(0, 0, self.w, self.h, self.C["acc"] if self.active else self.C["line"])
        return self.back

    def draw(self, cr, w, h):
        self.layout(w, h)
        self.hits = []
        vx, vy, vw, vh = self.view
        on_map = self.screen == "map"
        if on_map:
            self.map_scene()
        else:
            self.scene()
        S = MS if on_map else self.S
        d = round(self.rnd.uniform(-self.shake, self.shake)) if self.shake > 0.05 else 0
        e = round(self.rnd.uniform(-self.shake, self.shake)) if self.shake > 0.05 else 0
        cr.set_source_surface(self.backing(), 0, 0)
        cr.paint()
        cr.save()
        cr.rectangle(vx, vy, vw, vh)
        cr.clip()
        cr.set_source_rgb(*INK)
        cr.paint()
        cr.translate(vx + d * S, vy + e * S)
        cr.scale(S, S)
        cr.set_source_surface(self.map_cv if on_map else self.canvas, 0, 0)
        cr.get_source().set_filter(cairo.FILTER_NEAREST)
        cr.paint()
        cr.restore()
        self.edge(cr, vx - 2, vy - 2, vw + 4, vh + 4)
        if on_map:
            self.draw_map_marks(cr)
            self.draw_map_panel(cr)
        else:
            self.draw_panel(cr)
        self.draw_score(cr)
        if not self.reward:
            self.draw_tools(cr)
        if self.banner:
            self.draw_banner(cr)
        for f in self.floats:
            p = (self.t - f["t0"]) / f["dur"]
            if p >= 0:
                self.say(cr, f["x"], f["y"] - 30 * ease_out(p), f["text"], A.ENERGY_L, 24, a=min(1, (1 - p) * 3))
        if self.reward:
            self.draw_reward(cr)
        if self.flash > 0:
            cr.rectangle(vx, vy, vw, vh)
            cr.set_source_rgba(1, 1, 1, min(0.9, self.flash))
            cr.fill()
        if self.top:
            self.hits.extend(title_strip.draw(cr, self.style, self.f, self.f, w - 2 * self.f, GLYPH, "Castle.exe",
                                              hover=self.hover, maxed=self.maxed, active=self.active,
                                              r=0 if self.skeet else 9))
        if self.talk and not self.reward:
            self.draw_talk(cr)
        if self.book is not None:
            self.draw_book(cr)
        if self.help:
            self.draw_help(cr)

    # ── кирпичики интерфейса ──────────────────────────────────────────────
    def layout_of(self, cr, s, px):
        lay = PangoCairo.create_layout(cr)
        fd = Pango.FontDescription.from_string(FONT)
        fd.set_absolute_size(px * Pango.SCALE)
        lay.set_font_description(fd)
        lay.set_text(s, -1)
        return lay

    def text_w(self, cr, s, px):
        return self.layout_of(cr, s, px).get_pixel_size()[0]

    def say(self, cr, x, y, s, col, px, align="l", a=1.0, shadow=True):
        """Строка пиксельным шрифтом, y — середина; ⚡ — наш значок. Возвращает ширину."""
        if "⚡" in s:
            return self.say_bolt(cr, x, y, s, col, px, align, a, shadow)
        lay = self.layout_of(cr, s, px)
        tw, th = lay.get_pixel_size()
        tx = round(x - (tw if align == "r" else tw / 2 if align == "c" else 0))
        ty = round(y - th / 2)
        if shadow:
            cr.set_source_rgba(0, 0, 0, 0.75 * a)
            cr.move_to(tx + max(2, px // 12), ty + max(2, px // 12))
            PangoCairo.show_layout(cr, lay)
        cr.set_source_rgba(col[0], col[1], col[2], a)
        cr.move_to(tx, ty)
        PangoCairo.show_layout(cr, lay)
        return tw

    def say_bolt(self, cr, x, y, s, col, px, align, a, shadow):
        k = max(1, px // 16)
        bits = s.split("⚡")
        total = sum(self.text_w(cr, b, px) for b in bits) + (len(bits) - 1) * 9 * k
        cx = round(x - (total if align == "r" else total / 2 if align == "c" else 0))
        start = cx
        for i, b in enumerate(bits):
            cx += self.say(cr, cx, y, b, col, px, "l", a, shadow)
            if i < len(bits) - 1:
                A.energy_icon(cr, cx, round(y - 4.5 * k), k)
                cx += 9 * k
        return cx - start

    def para(self, cr, x, y, w, s, col, px=16):
        """Абзац с переносом по словам. Возвращает нижний край."""
        lay = self.layout_of(cr, s.replace("⚡", "энергии"), px)
        lay.set_width(w * Pango.SCALE)
        lay.set_wrap(Pango.WrapMode.WORD)
        lay.set_spacing(3 * Pango.SCALE)
        cr.set_source_rgb(*col[:3])
        cr.move_to(x, y)
        PangoCairo.show_layout(cr, lay)
        return y + lay.get_pixel_size()[1]

    def stroke(self, cr, x, y, w, h, col):
        cr.set_source_rgb(*col[:3])
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, h - 1)
        cr.stroke()

    def edge(self, cr, x, y, w, h):
        """Двойная грань, как у групп Skeet: чёрная снаружи, серая внутри."""
        self.stroke(cr, x, y, w, h, self.C["gdark"])
        self.stroke(cr, x + 1, y + 1, w - 2, h - 2, self.C["line"])

    def fill_grad(self, cr, x, y, w, h, top, low):
        g = cairo.LinearGradient(0, y, 0, y + h)
        g.add_color_stop_rgb(0, *top[:3])
        g.add_color_stop_rgb(1, *low[:3])
        cr.set_source(g)
        cr.rectangle(x, y, w, h)
        cr.fill()

    def group(self, cr, x, y, w, h, title, right="", right_col=None):
        """Группа с заголовком на рамке, как в Clocker."""
        C = self.C
        self.edge(cr, x, y, w, h)
        tw = self.text_w(cr, title, 16)
        A.box(cr, x + 10, y - 1, tw + 8, 3, C["bg"])
        self.say(cr, x + 14, y + 1, title, C["text"], 16, shadow=False)
        if right:
            rw = self.text_w(cr, right, 16)
            A.box(cr, x + w - 18 - rw, y - 1, rw + 8, 3, C["bg"])
            self.say(cr, x + w - 14, y + 1, right, right_col or C["dim"], 16, "r", shadow=False)

    def keycap(self, cr, x, cy, s, col):
        """Клавиша на кнопке. Возвращает ширину."""
        w = self.text_w(cr, s, 8) + 8
        y = round(cy) - 7
        cr.set_source_rgba(col[0], col[1], col[2], 0.65)
        cr.set_line_width(1)
        cr.rectangle(x + 0.5, y + 0.5, w - 1, 13)
        cr.stroke()
        self.say(cr, x + 4, y + 7, s, col, 8, shadow=False)
        return w

    def button(self, cr, x, y, w, h, name, label, key=None, px=16, kind=""):
        """Кнопка с подписью и своей клавишей. kind: hot — главное действие, off — пока нельзя
        (нажать можно: кнопка качнёт полосу и объяснит, чего не хватает)."""
        C, hov = self.C, self.hover == name
        self.hits.append(((x, y, w, h), name))
        lit = hov and kind != "off"
        A.box(cr, x, y, w, h, C["line3"] if self.skeet else C["gdark"])
        A.box(cr, x + 1, y + 1, w - 2, h - 2, C["acc"] if lit else C["line"])
        if kind == "hot":
            pulse = 0.5 + 0.5 * math.sin(self.t * 4.5)
            hi = A.mix(self.acc, WHITE, 0.3 + 0.14 * pulse + (0.12 if hov else 0))
            self.fill_grad(cr, x + 2, y + 2, w - 4, h - 4, hi, tuple(C["acc_d"]))
            col = INK if sum(hi) > 1.5 else WHITE
        elif kind == "off":
            self.fill_grad(cr, x + 2, y + 2, w - 4, h - 4, C["field"], C["field"])
            col = C["faint"]
        else:
            self.fill_grad(cr, x + 2, y + 2, w - 4, h - 4,
                           A.mix(C["field_l"], C["text"], 0.08) if hov else C["field_l"], C["field"])
            col = C["text"]
        cy = y + h / 2
        cap = self.text_w(cr, key, 8) + 16 if key else 0
        self.say(cr, x + (w - cap) / 2, cy, label, col, px, "c", shadow=False)
        if key:
            self.keycap(cr, x + w - cap + 2, cy, key, col)

    def chevron(self, cr, cx, cy, side, col):
        for i in range(5):
            A.box(cr, cx + side * (i - 2) * 2 - 1, cy - 8 + i * 2, 2, 16 - i * 4, col)

    # ── счёт и кнопки над сценой ──────────────────────────────────────────
    def need_for(self):
        """Сколько энергии нужно до выбранной ступени: все непостроенные до неё и она сама."""
        return sum(r[2] for r in self.rows[:self.sel + 1] if r[0] not in self.st["built"])

    def draw_score(self, cr):
        """Только счётчики (31.10.2026, просьба: «просто счётчик валюты и всё»): чего не хватает — в панели ступени."""
        x, y = self.view[0] + 8, self.view[1] + 8
        C, vis = self.C, self.st["visits"]
        text = "{:,}".format(round(self.shown)).replace(",", " ")
        mx = x + 54 + self.text_w(cr, text, 32) + 16
        w, h = mx - x + (22 + self.text_w(cr, str(vis), 24) + 12 if vis else 0), 48
        self.edge(cr, x, y, w, h)
        A.box(cr, x + 2, y + 2, w - 4, h - 4, C["bg"], 0.88)
        A.energy_icon(cr, x + 12, y + 8, 3)
        hot = self.t - self.pop < 0.18
        self.say(cr, x + 54, y + 24, text, A.ENERGY_W if hot else WHITE, 32)
        if vis:
            A.medal(cr, mx, y + 12, 2)
            self.say(cr, mx + 22, y + 24, str(vis), GOLD, 24)

    def draw_tools(self, cr):
        vx, vy, vw = self.view[:3]
        on_map = self.screen == "map"
        wide = vw >= 960                             # в узком окне кнопки встают в два ряда
        x, y = vx + vw - 8, vy + 8
        x -= 152
        self.button(cr, x, y, 152, 30, "mute", "Звук: выкл" if SND.muted() else "Звук: вкл", "m")
        x -= 176
        self.button(cr, x, y, 168, 30, "help", "Как играть", "?")
        if wide:
            x -= 8
        else:
            x, y = vx + vw, y + 38
        x -= 138
        self.button(cr, x, y, 130, 30, "book", "Хроника", "c")
        x -= 138
        self.button(cr, x, y, 130, 30, "map", "К земле" if on_map else "Карта", "Tab")

    # ── нижняя панель ─────────────────────────────────────────────────────
    def draw_panel(self, cr):
        vx, vy, vw, vh = self.view
        y = vy + vh
        done = sum(1 for r in self.rows if r[0] in self.st["built"])
        self.group(cr, vx, y + 12, vw, 62, "%s · %s" % (self.st["name"], CS.LAND[self.land]["kind"]),
                   "%d из %d" % (done, len(self.rows)))
        self.draw_track(cr, vx, y + 24, vw)
        low, h = y + 88, 112
        step_w = vw - ACT_W - 8
        self.group(cr, vx, low, step_w, h, "Ступень %d из %d" % (self.sel + 1, len(self.rows)))
        self.draw_step(cr, vx, low, step_w, h)
        self.group(cr, vx + step_w + 8, low, ACT_W, h, "Действия")
        self.draw_actions(cr, vx + step_w + 8, low, ACT_W)

    def draw_track(self, cr, gx, y, gw):
        """Дорожка ступеней: стрелки по краям, пройденные соединены золотой нитью, очередная дышит."""
        n, node = len(self.rows), 38
        arrow = 38
        cell = min(78, (gw - 2 * arrow - 36) // n)
        x0 = gx + (gw - cell * n) // 2
        C, built = self.C, self.st["built"]
        nxt = self.st["next"]["key"] if self.st["next"] else None
        total = 0
        for name, ax, side, letter in (("prev", gx + 12, -1, "h"), ("next", gx + gw - 12 - arrow, 1, "l")):
            self.button(cr, ax, y, arrow, node, name, "")
            self.chevron(cr, ax + 12, y + node // 2, side, C["text"])
            self.say(cr, ax + 27, y + node // 2, letter, C["dim"], 8, "c", shadow=False)
        cy = y + node // 2
        for i in range(n - 1):
            ok = self.rows[i][0] in built and self.rows[i + 1][0] in built
            near = self.rows[i][0] in built and self.rows[i + 1][0] == nxt
            A.box(cr, x0 + cell * i + cell // 2, cy - 1, cell, 2,
                  GOLD if ok else A.mix(GOLD, C["line"], 0.5) if near else C["line"])
        for i, row in enumerate(self.rows):
            key = row[0]
            x = x0 + cell * i + (cell - node) // 2
            on = key in built
            self.hits.append(((x, y, node, node), i))
            self.edge(cr, x, y, node, node)
            top = A.mix(C["field_l"], GOLD, 0.3) if on else C["field_l"]
            low = A.mix(C["field"], GOLD, 0.22) if on else C["field"]
            self.fill_grad(cr, x + 2, y + 2, node - 4, node - 4, top, low)
            A.icon(cr, key, x + 5, y + 5, 3, self.acc, dim=not on and key != nxt, land=self.land)
            if not on and key != "crown":             # цена под ступенью: цвет энергии, если уже хватает
                total += row[2]
                self.say(cr, x + node // 2, y + node + 6, str(row[2]),
                         A.ENERGY_L if total <= self.st["balance"] else C["dim"], 8, "c", shadow=False)
            if key == nxt:
                self.frame_box(cr, x - 1, y - 1, node + 2, node + 2, GOLD, 0.6 + 0.4 * math.sin(self.t * 4))
            if i == self.sel:
                self.frame_box(cr, x - 3, y - 3, node + 6, node + 6, WHITE, 1)
            elif self.hover == i:
                self.frame_box(cr, x - 3, y - 3, node + 6, node + 6, WHITE, 0.45)

    def frame_box(self, cr, x, y, w, h, col, a):
        for q in ((x, y, w, 2), (x, y + h - 2, w, 2), (x, y, 2, h), (x + w - 2, y, 2, h)):
            A.box(cr, *q, col, a)

    def work(self, n):
        mins = n * CS.ENERGY_SEC // 60
        return "%d ч %d мин" % (mins // 60, mins % 60) if mins >= 60 else "%d мин" % mins

    def hint(self):
        """Что делать прямо сейчас, одной строкой: (текст, цвет)."""
        key, _name, _price, need = self.rows[self.sel][:4]
        st, n, C = self.st, self.st["next"], self.C
        if key == "crown":
            return ("Оффер получен", GOLD) if st["offer"] else ("Надевается сама в день оффера", C["dim"])
        if key in st["built"]:
            return "Уже построено", GOLD
        short = max(0, self.need_for() - st["balance"])
        visits = 0 if st["offer"] else max(0, need - st["visits"])
        if n["key"] != key:
            if short:
                return "До неё копить ещё %d ⚡: %s работы" % (short, self.work(short)), WARM
            return "Энергии хватит, сначала: " + n["name"], C["dim"]
        if visits:
            return "Откроется, когда будет ещё %s" % CS.plural_visit(visits), GOLD
        if short:
            return "Не хватает %d ⚡: это %s работы" % (short, self.work(short)), WARM
        return "Хватает. После постройки останется %d ⚡" % (st["balance"] - self.need_for()), A.ENERGY_L

    def draw_step(self, cr, gx, gy, gw, gh):
        """Выбранная ступень: значок, название, сколько собрано и что делать."""
        key, name, price = self.rows[self.sel][:3]
        C, st = self.C, self.st
        built = key in st["built"]
        nxt = bool(st["next"] and st["next"]["key"] == key)
        x, y, tile = gx + 14, gy + 16, 66
        self.edge(cr, x, y, tile, tile)
        self.fill_grad(cr, x + 2, y + 2, tile - 4, tile - 4, C["field_l"], C["field"])
        A.icon(cr, key, x + 6, y + 6, 6, self.acc, dim=not built and not nxt, land=self.land)
        tx = x + tile + 14
        rw = gx + gw - 14 - tx
        self.say(cr, tx, gy + 26, name, WHITE, 24, shadow=False)
        if not built and key != "crown":
            shift = round(math.sin((self.t - self.nudge) * 30) * 3) if self.t - self.nudge < 0.3 else 0
            price = self.need_for()
            have = min(price, st["balance"])
            value = "%d из %d" % (have, price)
            vw = self.text_w(cr, value, 16)
            bw = rw - vw - 34
            bx, by = tx + shift, gy + 46
            self.edge(cr, bx, by, bw, 16)
            A.box(cr, bx + 2, by + 2, bw - 4, 12, C["field"])
            full = int((bw - 4) * have / price)
            A.box(cr, bx + 2, by + 2, full, 12, A.ENERGY)
            A.box(cr, bx + 2, by + 2, full, 3, A.ENERGY_L)
            A.energy_icon(cr, bx + bw + 8, by + 3, 1)
            self.say(cr, bx + bw + 22, by + 8, value, WHITE, 16, shadow=False)
        text, col = self.hint()
        px = 16 if self.text_w(cr, text, 16) <= rw else 8
        self.say(cr, tx, gy + 86, text, col, px, shadow=False)

    def draw_actions(self, cr, gx, gy, gw):
        st, n = self.st, self.st["next"]
        x, w, y = gx + 12, gw - 24, gy + 12
        if self.job:
            label, key, kind = "СТРОИТСЯ", None, "off"
        elif not n:
            label, key, kind = "НА КАРТУ", "Enter", "hot"
        elif self.rows[self.sel][0] != n["key"]:
            label, key, kind = "К ОЧЕРЕДНОЙ", "Enter", ""
        elif n["ready"]:
            label, key, kind = "ПОСТРОИТЬ", "Enter", "hot"
        elif n["visits_short"]:
            label, key, kind = "НУЖЕН ПОХОД", None, "off"
        else:
            label, key, kind = "ПОСТРОИТЬ", None, "off"
        self.button(cr, x, y, w, 52, "build", label, key, 24, kind)
        half = (w - 8) // 2
        self.button(cr, x, y + 60, half, 30, "undo", "Отменить", "u", kind="" if self.undos else "off")
        self.button(cr, x + half + 8, y + 60, w - half - 8, 30, "redo", "Вернуть", "r", kind="" if self.redos else "off")

    # ── наложения ─────────────────────────────────────────────────────────
    def plate(self, cr, x, y, w, h, a=0.72):
        A.box(cr, x, y, w, h, self.C["bg"], a)
        self.edge(cr, x, y, w, h)

    def draw_banner(self, cr):
        b = self.banner
        vx, vy, vw = self.view[:3]
        p = (self.t - b["t0"]) / b["dur"]
        a = min(1, p * 8, (1 - p) * 5)
        y = vy + 110 + (1 - ease_out(min(1, p * 5))) * -40
        cx = vx + vw / 2
        A.box(cr, cx - 220, y - 30, 440, 96, self.C["bg"], 0.86 * a)
        self.frame_box(cr, cx - 220, y - 30, 440, 96, GOLD, a)
        self.say(cr, cx, y + 2, b["head"], GOLD, 32, "c", a)
        self.say(cr, cx, y + 42, b["text"], WHITE, 24, "c", a)

    def draw_reward(self, cr):
        r, S = self.reward, self.S
        vx, vy, vw, vh = self.view
        cx = vx + vw / 2
        x, y = self.chest_pos()
        since = self.t - r["t0"]
        cr.rectangle(self.f, vy + vh + 2, self.w - 2 * self.f, self.h - self.f - vy - vh - 2)
        cr.set_source_rgba(0.02, 0.02, 0.07, min(0.93, since * 2.2))
        cr.fill()
        if r["phase"] == "fall":
            return
        head_y = vy + (y - 14) * S - 84
        a = min(1, (since - 0.5) * 4)
        self.say(cr, cx, head_y, r["head"], GOLD, 40 if self.w > 900 else 32, "c", a)
        if r["sub"]:
            self.say(cr, cx, head_y + 44, r["sub"], WHITE, 24, "c", a)
        low = vy + (y + 30) * S + 42
        by = self.h - self.f - PAD - 62              # кнопка на тёмной панели: одно место, какого бы размера ни было окно
        if r["phase"] == "wait":
            self.button(cr, round(cx) - 130, by, 260, 52, "build", "ОТКРЫТЬ", "Enter", 24, "hot")
            return
        since = self.t - r["at"]
        if since > 0.3:
            k = ease_out(min(1, (since - 0.3) / 0.5))
            self.say(cr, cx, low, "+%d" % round(r["gain"] * k), A.ENERGY_L, 56, "c")
            self.say(cr, cx, low + 44, "энергии", WHITE, 24, "c", min(1, since - 0.3))
        line = low + 74
        if since > 1.4 and r["opened"]:
            self.say(cr, cx, line, "Теперь можно строить: " + ", ".join(r["opened"]), GOLD, 24, "c", min(1, since - 1.4))
            line += 30
        if since > 1.0:
            for i, it in r["items"][:3]:
                self.draw_find(cr, cx, line, i, it)
                line += 28
            if len(r["items"]) > 3:
                self.say(cr, cx, line, "и ещё %d: они в хронике" % (len(r["items"]) - 3), self.C["dim"], 16, "c")
        if since > 2.2:
            self.button(cr, round(cx) - 130, by, 260, 52, "build", "ДАЛЬШЕ", "Enter", 24, "hot")

    def find_col(self, rarity):
        return A.RARE_PAL[rarity]["L"]

    def draw_find(self, cr, cx, y, i, it, left=False):
        """Находка строкой: значок, название, редкость и прибавка."""
        rar = "обрывок карты" if it[1] == CS.SCRAP else L.RARE[it[1]][0]
        text = "%s · %s · +%d ⚡" % (it[0], rar, CS.find_value(it))
        tw = self.text_w(cr, text.replace("⚡", ""), 16) + 18
        x = cx if left else cx - (tw + 26) / 2
        A.find_icon(cr, i, it[1], x, y - 9, 2)
        self.say(cr, x + 26, y, text, self.find_col(it[1]), 16)

    def draw_talk(self, cr):
        """Диалог снизу сцены: портрет, имя, текст печатается по буквам."""
        who, text = self.talk[0]
        C = self.C
        vx, vy, vw, vh = self.view
        h, x, w = 124, vx + 24, vw - 48
        y = vy + vh - h - 12
        self.plate(cr, x, y, w, h, 0.95)
        self.hits.append(((x, y, w, h), "talk"))
        self.edge(cr, x + 12, y + 14, 96, 96)
        A.box(cr, x + 14, y + 16, 92, 92, C["field"])
        A.portrait(cr, x + 18, y + 20, 7, who, L.PEOPLE[who])
        self.say(cr, x + 124, y + 24, L.PEOPLE[who]["name"], GOLD, 16, shadow=False)
        n = self.typed()
        self.para(cr, x + 124, y + 42, w - 144, text[:max(0, n)], WHITE)
        tip = "Enter дальше · Esc пропустить" if n >= len(text) else "Enter показать сразу"
        self.say(cr, x + w - 12, y + h - 12, tip, C["dim"], 8, "r", shadow=False)

    def land_title(self, i):
        """Шпиль скрыт, пока к нему не подошли."""
        if L.LANDS[i].get("offer") and not self.st["lands"][i - 1]["done"]:
            return "???"
        return L.LANDS[i]["name"]

    def draw_map_marks(self, cr):
        C = self.C
        vx, vy = self.view[:2]
        for i, x in enumerate(self.st["lands"]):
            px, py = self.map_point(L.LANDS[i]["at"])
            sx, sy = vx + px * MS, vy + py * MS
            self.hits.append(((sx - 60, sy - 36, 120, 90), ("land", i)))
            self.say(cr, sx, sy + 34, self.land_title(i), WHITE if x["open"] else C["dim"], 16, "c")
            if x["done"]:
                self.say(cr, sx, sy + 48, "достроено", GOLD, 8, "c")
            elif x["built"]:
                self.say(cr, sx, sy + 48, "%d из %d" % (x["built"], x["steps"]), A.ENERGY_L, 8, "c")
            if i == self.map_sel:
                self.frame_box(cr, sx - 56, sy - 34, 112, 90, WHITE, 0.65 + 0.35 * math.sin(self.t * 4))
        px, py = self.map_point(L.BEYOND)
        sx, sy = vx + px * MS, vy + py * MS
        self.hits.append(((sx - 30, sy - 30, 60, 60), ("land", len(L.LANDS))))
        shown = self.st["scraps"] >= L.SCRAPS
        self.say(cr, sx, sy, "?" if not shown else "»", GOLD, 32, "c")
        if self.map_sel == len(L.LANDS):
            self.frame_box(cr, sx - 30, sy - 30, 60, 60, WHITE, 0.65 + 0.35 * math.sin(self.t * 4))

    def draw_map_panel(self, cr):
        vx, vy, vw, vh = self.view
        C, y = self.C, vy + vh + 12
        h = PANEL - 16
        w = vw - ACT_W - 8
        ax = vx + w + 8
        self.group(cr, ax, y, ACT_W, h, "Действия")
        bx, bw = ax + 12, ACT_W - 24
        half = (bw - 8) // 2
        sel = self.map_sel
        if sel >= len(L.LANDS):
            self.draw_beyond(cr, vx, y, w, h)
            self.button(cr, bx, y + 14, bw, 52, "build", "ЕЩЁ НЕ ПЛЫТЬ", None, 24, "off")
        else:
            x = self.st["lands"][sel]
            self.draw_land_card(cr, vx, y, w, h, sel, x)
            if x["open"]:
                self.button(cr, bx, y + 14, bw, 52, "build", "ВОЙТИ", "Enter", 24, "hot")
            else:
                self.button(cr, bx, y + 14, bw, 52, "build", "ЗАКРЫТО", None, 24, "off")
        self.button(cr, bx, y + 74, half, 30, "map_prev", "Назад", "h")
        self.button(cr, bx + half + 8, y + 74, bw - half - 8, 30, "map_next", "Дальше", "l")
        self.button(cr, bx, y + 112, bw, 30, "map", "Вернуться к земле", "Tab")

    def draw_land_card(self, cr, gx, gy, gw, gh, i, x):
        land, C = L.LANDS[i], self.C
        title = self.land_title(i)
        self.group(cr, gx, gy, gw, gh, title, land["kind"] if title != "???" else "")
        px, ty = gx + 14, gy + 18
        low = self.para(cr, px, ty, gw - 28, land["blurb"] if title != "???" else "Никто не возвращался, чтобы рассказать.", C["text"])
        by = low + 10
        bw = gw - 28 - 150
        self.edge(cr, px, by, bw, 16)
        A.box(cr, px + 2, by + 2, bw - 4, 12, C["field"])
        put = x["price"] - x["left"]
        fill = int((bw - 4) * put / x["price"])
        A.box(cr, px + 2, by + 2, fill, 12, A.ENERGY)
        A.box(cr, px + 2, by + 2, fill, 3, A.ENERGY_L)
        self.say(cr, px + bw + 10, by + 8, "%d из %d ⚡" % (put, x["price"]), WHITE, 16, shadow=False)
        self.say(cr, px, by + 34, "Ступеней: %d из %d" % (x["built"], x["steps"]), C["dim"], 16, shadow=False)
        gift = "Дар: " + land["gift_text"]
        self.say(cr, px, by + 56, gift, GOLD if x["done"] else C["text"], 16, shadow=False)
        if not x["open"]:
            last = self.st["lands"][i - 1]
            why = "Откроется после оффера" if last["done"] else "Сначала достройте: " + self.land_title(i - 1)
            self.say(cr, gx + gw - 14, by + 34, why, WARM, 16, "r", shadow=False)
        elif x["left"]:
            self.say(cr, gx + gw - 14, by + 34, "Осталось %d ⚡" % x["left"], A.ENERGY_L, 16, "r", shadow=False)

    def draw_beyond(self, cr, gx, gy, gw, gh):
        C, have = self.C, self.st["scraps"]
        self.group(cr, gx, gy, gw, gh, "За морем" if have < L.SCRAPS else "Острова за морем", "%d из %d" % (have, L.SCRAPS))
        text = ("Обрывки сложились. За проливом острова, которых нет ни на одной старой карте. Искра молчит и смотрит туда."
                if have >= L.SCRAPS else
                "На старых картах здесь пусто, но края у них оборваны. Обрывки находятся сами, пока вы работаете.")
        self.para(cr, gx + 14, gy + 18, gw - 28, text, C["text"])

    def book_lines(self, i):
        """Что уже было сказано в этой земле, по порядку: несказанное не подсмотреть."""
        k = L.LANDS[i]["key"]
        keys = ["arrive:" + k] + [CS.full(k, s[0]) for s in CS.land_steps(k)] + ["done:" + k]
        if k == CS.HOME:
            keys = ["prologue"] + keys + ["crown"]
        return [q for key in keys if key in self.story for q in self.story_of(key)]

    def draw_book(self, cr):
        """Хроника: страница на землю и страница находок."""
        C, f, top = self.C, self.f, self.top
        w, h = self.w, self.h
        cr.rectangle(f, top, w - 2 * f, h - top - f)
        cr.set_source_rgba(0, 0, 0, 0.62)
        cr.fill()
        self.hits.append(((f, top, w - 2 * f, h - top - f), "book_shade"))
        cw, ch = min(w - 2 * f - 24, 900), min(h - top - f - 16, 620)
        x, y = (w - cw) // 2, top + (h - top - f - ch) // 2
        R.View.card(R.Painter(cr), C, x, y, cw, ch)
        self.hits.append(((x, y, cw, ch), "book_card"))
        ix, iy, bw = x + 18, y + 16, cw - 36
        pages = len(L.LANDS) + 1
        finds = self.book == len(L.LANDS)
        self.say(cr, ix, iy + 12, "Находки" if finds else self.land_title(self.book), WHITE, 24, shadow=False)
        self.say(cr, ix + bw, iy + 12, "страница %d из %d" % (self.book + 1, pages), C["dim"], 16, "r", shadow=False)
        body = iy + 40
        low = y + ch - 56
        if finds:
            self.draw_finds(cr, ix, body, bw, low)
        else:
            self.draw_page(cr, ix, body, bw, low)
        by = y + ch - 44
        self.button(cr, ix, by, 130, 30, "book_prev", "Назад", "h")
        self.button(cr, ix + 138, by, 140, 30, "book_next", "Вперёд", "l")
        self.button(cr, ix + bw - 150, by, 150, 30, "book_close", "Закрыть", "c")

    def draw_page(self, cr, x, top, w, low):
        C = self.C
        lines = self.book_lines(self.book)
        if not lines:
            self.para(cr, x, top + 8, w, "Страница пустая: здесь ещё ничего не случилось." if self.st["lands"][self.book]["open"]
                      else "Эта земля ещё спит.", C["dim"])
            self.book_h = 0
            return
        cr.save()
        cr.rectangle(x, top, w, low - top)
        cr.clip()
        y = top + 6 - self.book_y
        for who, text in lines:
            A.box(cr, x, y, 40, 40, C["field"])
            A.portrait(cr, x + 2, y + 4, 3, who, L.PEOPLE[who])
            self.say(cr, x + 52, y + 8, L.PEOPLE[who]["name"], GOLD, 16, shadow=False)
            y = max(y + 48, self.para(cr, x + 52, y + 20, w - 60, text, C["text"]) + 12)
        cr.restore()
        self.book_h = max(0, y + self.book_y - low)
        self.book_y = min(self.book_y, self.book_h)
        if self.book_h and self.book_y < self.book_h:
            self.say(cr, x + w // 2, low - 4, "▼", C["acc"], 16, "c")

    def draw_finds(self, cr, x, top, w, low):
        C, st = self.C, self.st
        n, cols = len(L.FINDS), 12
        cell = w // cols
        for i in range(n):
            cx, cy = x + (i % cols) * cell, top + (i // cols) * cell
            self.hits.append(((cx, cy, cell - 4, cell - 4), ("find", i)))
            self.edge(cr, cx, cy, cell - 4, cell - 4)
            A.box(cr, cx + 2, cy + 2, cell - 8, cell - 8, C["field"])
            if i < st["found"]:
                A.find_icon(cr, i, L.FINDS[i][1], cx + (cell - 31) // 2, cy + (cell - 31) // 2, 3)
            else:
                self.say(cr, cx + (cell - 4) // 2, cy + (cell - 4) // 2, "?", C["faint"], 16, "c", shadow=False)
            if i == self.find_sel:
                self.frame_box(cr, cx - 1, cy - 1, cell - 2, cell - 2, WHITE, 0.9)
        y = top + 3 * cell + 14
        sel = self.hover[1] if isinstance(self.hover, tuple) and self.hover[0] == "find" else self.find_sel
        if sel < st["found"]:
            it = L.FINDS[sel]
            self.draw_find(cr, x, y + 8, sel, it, True)
            self.para(cr, x, y + 26, w, it[2], C["text"])
        else:
            self.say(cr, x, y + 8, "Ещё не найдено", C["dim"], 16, shadow=False)
        self.say(cr, x, low - 8, "Найдено %d из %d · обрывков карты %d из %d · до следующей %d ⚡" % (
            st["found"], n, st["scraps"], L.SCRAPS, st["find_mark"] - st["earned"]), C["dim"], 16, shadow=False)

    def rows_help(self):
        return (("Код, рынок, речь, сила", "%d мин = 1" % (CS.ENERGY_SEC // 60)), ("Быт", "%d дела = 1" % CS.CHORES),
                ("Блок дня", "+%d" % CS.BLOCK), ("Сверх потолка", "+%d" % CS.OVER),
                ("День засчитан", "+%d" % CS.DAY), ("Поход на собеседование", "+%d" % CS.VISIT),
                ("Дары земель, находки", "сверху"))

    KEYS_HELP = (("Enter", "построить, войти"), ("Tab", "карта"), ("c", "хроника и находки"), ("h l", "выбрать"),
                 ("u r", "отменить, вернуть"), ("m", "звук"), ("?", "эта памятка"), ("Esc", "назад, закрыть"))

    def draw_help(self, cr):
        """Памятка поверх всего: зачем играть, откуда энергия, какие клавиши."""
        C, f, top = self.C, self.f, self.top
        w, h = self.w, self.h
        cr.rectangle(f, top, w - 2 * f, h - top - f)
        cr.set_source_rgba(0, 0, 0, 0.62)
        cr.fill()
        self.hits.append(((f, top, w - 2 * f, h - top - f), "help"))
        cw, ch = min(w - 2 * f - 24, 900), min(h - top - f - 16, 520)
        x, y = (w - cw) // 2, top + (h - top - f - ch) // 2
        p = R.Painter(cr)
        R.View.card(p, C, x, y, cw, ch)
        ix, iy = x + 18, y + 16
        self.say(cr, ix, iy + 12, "Как играть", WHITE, 24, shadow=False)
        col = (cw - 36 - 12) // 2
        lx, rx, gy = ix, ix + col + 12, iy + 44
        foot = y + ch - 62
        goal_h = 104
        self.group(cr, lx, gy, col, goal_h, "Цель")
        self.para(cr, lx + 12, gy + 18, col - 24, "Отстроить семь земель и дойти до Шпиля Морока. Дар каждой земли "
                  "навсегда прибавляет к настоящей работе.", C["text"])
        ly = gy + goal_h + 16
        self.group(cr, lx, ly, col, foot - ly, "Как строить")
        self.para(cr, lx + 12, ly + 18, col - 24, "1. Работайте: энергия приходит сама.\n"
                  "2. Хватает на ступень: «Построить» загорается.\n3. Земля достроена: откройте карту.\n"
                  "Энергия не сгорает и не отнимается. Находки падают сами, сундуком.", C["text"])
        rows = self.rows_help()
        src_h = 28 + 22 * len(rows)
        self.group(cr, rx, gy, col, src_h, "Откуда энергия")
        for i, (name, val) in enumerate(rows):
            ry = gy + 24 + 22 * i
            vw = self.say(cr, rx + col - 12, ry, val, A.ENERGY_L, 16, "r", shadow=False)
            px = 16 if self.text_w(cr, name, 16) + vw + 36 <= col else 8
            self.say(cr, rx + 12, ry, name, C["text"], px, shadow=False)
        ky = gy + src_h + 16
        self.group(cr, rx, ky, col, foot - ky, "Управление: мышь или клавиши")
        step = (foot - ky - 12) // len(self.KEYS_HELP)
        for i, (key, what) in enumerate(self.KEYS_HELP):
            ry = ky + 14 + step * i + step // 2 - 4
            self.keycap(cr, rx + 12, ry, key, C["text"])
            self.say(cr, rx + 72, ry, what, C["dim"], 16, shadow=False)
        self.button(cr, x + cw // 2 - 110, y + ch - 50, 220, 36, "help", "Понятно", "Enter", 16, "hot")


class Win(Gtk.ApplicationWindow):
    EDGES = {"nw": Gdk.WindowEdge.NORTH_WEST, "n": Gdk.WindowEdge.NORTH, "ne": Gdk.WindowEdge.NORTH_EAST,
             "w": Gdk.WindowEdge.WEST, "e": Gdk.WindowEdge.EAST, "sw": Gdk.WindowEdge.SOUTH_WEST,
             "s": Gdk.WindowEdge.SOUTH, "se": Gdk.WindowEdge.SOUTH_EAST}

    def __init__(self, app):
        super().__init__(application=app, title="Castle")
        self.set_decorated(False)
        self.set_resizable(True)
        self.set_size_request(MIN_W, MIN_H)
        self.set_default_size(*saved_size())
        self.cursor_name, self.saving, self.timer, self.fps = None, 0, 0, 0
        self.conn = hublib.connect()
        try:
            IV.sync(self.conn)                       # поход из журнала виден сразу, не через 15 с
        except Exception:
            pass
        self.game = Game(self.conn)
        self.game.close = self.close
        self.game.world_ready()
        self.game.news()
        self.game.first_help()
        self.area = Gtk.DrawingArea()
        self.area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK | Gdk.EventMask.POINTER_MOTION_MASK
                             | Gdk.EventMask.LEAVE_NOTIFY_MASK | Gdk.EventMask.SCROLL_MASK)
        self.area.connect("draw", self.on_draw)
        self.area.connect("button-press-event", self.on_click)
        self.area.connect("motion-notify-event", self.on_motion)
        self.area.connect("leave-notify-event", self.on_leave)
        self.area.connect("scroll-event", self.on_scroll)
        self.add(self.area)
        self.connect("key-press-event", self.on_key)
        self.connect("notify::is-active", self.on_active)
        self.connect("window-state-event", self.on_wstate)
        self.connect("configure-event", self.on_configure)
        self.connect("destroy", self.on_destroy)
        self.prev = time.monotonic()
        self.pace()
        self.area.show()

    def pace(self):
        """Кадров в секунду: эффекты 30, просто сцена 12, окно не в фокусе 3."""
        g = self.game
        fps = 30 if g.animating() else 12 if g.active else 3
        if fps != self.fps:
            if self.timer:
                GLib.source_remove(self.timer)
            self.fps = fps
            self.timer = GLib.timeout_add(1000 // fps, self.on_tick)

    def on_tick(self):
        now = time.monotonic()
        self.game.tick(now - self.prev)
        self.prev = now
        self.area.queue_draw()
        self.pace()
        return GLib.SOURCE_CONTINUE

    def on_draw(self, _w, cr):
        a = self.area.get_allocation()
        self.game.draw(cr, a.width, a.height)

    def on_key(self, _w, ev):
        ctrl = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
        done = self.game.key(ev.hardware_keycode, ev.keyval, ctrl)
        self.area.queue_draw()
        return done

    def edge_at(self, x, y):
        a = self.area.get_allocation()
        w, h, m = a.width, a.height, 6
        if x >= w - 18 and y >= h - 18:
            return "se"
        v = "n" if y < m else "s" if y >= h - m else ""
        hz = "w" if x < m else "e" if x >= w - m else ""
        return (v + hz) or None

    def set_cursor(self, name):
        if name != self.cursor_name:
            self.cursor_name = name
            gw = self.area.get_window()
            if gw:
                gw.set_cursor(Gdk.Cursor.new_from_name(gw.get_display(), name) if name else None)

    def on_motion(self, _w, ev):
        edge = None if self.game.maxed else self.edge_at(ev.x, ev.y)
        self.set_cursor((edge + "-resize") if edge else None)
        hover = None if edge else self.game.hit(ev.x, ev.y)
        if hover != self.game.hover:
            self.game.hover = hover
            self.area.queue_draw()

    def on_scroll(self, _w, ev):
        ok, _dx, dy = ev.get_scroll_deltas()
        d = dy if ok else {Gdk.ScrollDirection.UP: -1, Gdk.ScrollDirection.DOWN: 1}.get(ev.direction, 0)
        self.game.scroll(d)
        self.area.queue_draw()
        return True

    def on_leave(self, _w, _ev):
        self.game.hover = None

    def on_click(self, _w, ev):
        if ev.button != 1:
            return False
        edge = None if self.game.maxed else self.edge_at(ev.x, ev.y)
        name = self.game.hit(ev.x, ev.y)
        if name == "close":
            self.close()
        elif name == "max":
            title_strip.toggle_max(self)
        elif name == "title":
            title_strip.on_title(self, ev)
        elif edge:
            self.begin_resize_drag(self.EDGES[edge], ev.button, int(ev.x_root), int(ev.y_root), ev.time)
        else:
            self.game.click(name)
            self.area.queue_draw()
        return True

    def on_active(self, *_a):
        self.game.active = self.is_active()

    def on_wstate(self, _w, ev):
        self.game.maxed = bool(ev.new_window_state & Gdk.WindowState.MAXIMIZED) or title_strip.float_maxed(self)
        return False

    def on_configure(self, _w, ev):
        if not self.game.maxed and ev.width >= MIN_W and ev.height >= MIN_H:
            if self.saving:
                GLib.source_remove(self.saving)
            self.saving = GLib.timeout_add(600, self.save_size, ev.width, ev.height)
        return False

    def save_size(self, w, h):
        self.saving = 0
        try:
            with open(STATE, "w") as f:
                json.dump(dict(w=w, h=h), f)
        except OSError:
            pass
        return False

    def on_destroy(self, *_a):
        if self.timer:
            GLib.source_remove(self.timer)
            self.timer = 0


def saved_size():
    try:
        d = json.load(open(STATE))
        return max(MIN_W, int(d["w"])), max(MIN_H, int(d["h"]))
    except (OSError, ValueError, KeyError, TypeError):
        return SIZE


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self.win = None

    def do_command_line(self, cl):
        toggle = "--toggle" in cl.get_arguments()[1:]
        if toggle and self.win is not None and self.win.is_active():
            self.win.close()
            return 0
        if self.win is None:
            self.win = Win(self)
            self.win.connect("destroy", lambda *_a: setattr(self, "win", None))
        R.present_unmin(self.win)
        return 0


def main():
    if sys.argv[1:] == ["check"]:                    # самопроверка: база, расчёт и рисунок живы
        game = Game(hublib.connect(), test=True)
        surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, *SIZE)
        game.draw(cairo.Context(surf), *SIZE)
        surf.write_to_png(os.path.join(RUN, "jarvis-castle-check.png"))
        print("ok")
        return 0
    GLib.set_prgname(APP_ID)
    return App().run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
