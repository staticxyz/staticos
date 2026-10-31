#!/usr/bin/env python3
"""Замок (30.10.2026): энергия за работу и 12 ступеней постройки на цель «Оффер».

Просьба: «замок должен быть отдельным приложением, и так же в виде виджета… Должна быть своя
внутренняя валюта, которое будет даваться за наши задачи». Своего счёта работы нет: доход выводится
из тех же цифр, что Better (рынок, код, речь, сила, быт, блок дня) и из походов на
собеседования, поэтому отметка откуда угодно сразу становится энергией. В базе лежат только траты:
строка growth kind 'castle', note — ступень, value — цена. Баланс = доход − траты.

Правила против прошлых ошибок: энергия не сгорает, штрафов и таймеров нет, постройка занимает
секунды. Часть ступеней требует походов на собеседования, а корону энергией не купить: она только за
настоящий оффер, иначе замок будет расти без движения к цели (так брошен Skill stats).

Земли (31.10.2026): данные и сюжет — castle_lands.py. Дом — старые ключи без префикса, остальное
`forest:hill`. Земля открыта, когда достроена предыдущая; Шпиль ждёт ещё и оффера. Дары и находки тоже
не хранятся: они выводятся из тех же цифр, поэтому сами считают откат постройки."""
import datetime as dt
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import castle_lands as L  # noqa: E402
import growth as G  # noqa: E402
import hublib as H  # noqa: E402
import interviews as IV  # noqa: E402

KIND = "castle"
CACHE = "g_castle_days"            # закрытые дни: день → {источник: энергия}
SEEN = "g_castle_seen"             # о чём уже сказали: источник → сумма по всем дням
NOTE = os.path.join(G.NOTES, "Замок.md")
BIND = "Super+Shift+B"

ENERGY_SEC = 10 * 60
BLOCK, DAY, OVER, CHORES, VISIT = 5, 2, 3, 3, 40
# (ключ, название, цена, нужно походов); порядок — порядок постройки, картина — castle_art.py
STEPS = (("hill", "Холм", 20, 0), ("base", "Фундамент", 30, 0), ("wall_l", "Стена слева", 40, 0),
         ("wall_r", "Стена справа", 40, 0), ("gate", "Ворота", 50, 1), ("tower_l", "Башня слева", 60, 0),
         ("tower_r", "Башня справа", 60, 0), ("moat", "Ров и мост", 70, 0), ("keep", "Донжон", 90, 0),
         ("merlons", "Зубцы", 90, 3), ("flag", "Знамя", 100, 0))
CROWN = ("crown", "Корона", 0, 0)
SOURCES = (("market", "Рынок"), ("code", "Код"), ("speech", "Речь"), ("lift", "Сила"), ("chores", "Быт"),
           ("block", "Блок дня"), ("over", "Сверх потолка"), ("day", "День засчитан"),
           ("visit", "Собеседование"), ("gift", "Дары земель"), ("find", "Находки"))
NAMES = dict(SOURCES)
TALLY = {"market", "code", "speech", "lift"}
HOME = "home"
LAND = {x["key"]: x for x in L.LANDS}
KEYS = tuple(LAND)
SCRAP = 3                          # редкость «обрывок карты»


def land_steps(land):
    return STEPS if land == HOME else LAND[land]["steps"]


def full(land, part):
    """Ключ ступени в базе: у дома старый, без префикса."""
    return part if land == HOME else "%s:%s" % (land, part)


def land_of(note):
    return note.split(":", 1)[0] if ":" in note else HOME


def local(note):
    return note.split(":", 1)[-1]


def energy(n):
    return "%d энергии" % n


def plural_visit(n):
    return "%d %s" % (n, G.plural(n, "поход", "похода", "походов"))


def day_income(c, day, closed):
    """{источник: энергия} за день. «День засчитан» — только у закрытого дня: энергия не убывает,
    а сегодняшний счёт ещё может упасть."""
    st = G.status(c) if day == G.today(c) else G.evaluate(c, day)
    T, R = st["today"], st["rows"]
    out = {k: T[k] // ENERGY_SEC for k in TALLY if T[k] >= ENERGY_SEC}
    if T["chores"] >= CHORES:
        out["chores"] = T["chores"] // CHORES
    if st["block"]["done"]:
        out["block"] = BLOCK
    n = sum(1 for k in TALLY if R[k].get("over"))
    if n:
        out["over"] = n * OVER
    if closed and st["counted"]:
        out["day"] = DAY
    return out


def income(c):
    """Доход по дням. Позавчера и раньше — из кэша: цифры уже не меняются, а считать их долго.
    Что в кэше, то не пересчитывается: энергия не убывает, даже если правила дня поменялись."""
    now = G.today(c)
    try:
        cache = json.loads(H.meta_get(c, CACHE, "{}") or "{}")
    except ValueError:
        cache = {}
    out, changed = {}, False
    d = G.FIRST
    while d <= now:
        key = d.isoformat()
        if key in cache or (now - d).days >= 2:
            if key not in cache:
                cache[key] = day_income(c, d, True)
                changed = True
            out[key] = dict(cache[key])
        else:
            out[key] = day_income(c, d, d < now)
        d += dt.timedelta(days=1)
    if changed:
        H.meta_set(c, CACHE, json.dumps(cache))
    for r in IV.visits(c):
        day = out.setdefault(r["day"], {})
        day["visit"] = day.get("visit", 0) + VISIT
    return out


def gifts(days, done):
    """Дары: законченная земля прибавляет к настоящей работе со дня, когда её достроили."""
    for land, since in done.items():
        gift = LAND[land]["gift"]
        if gift:
            src, per, plus = gift
            for day, v in days.items():
                if day >= since and v.get(src, 0) >= per:
                    v["gift"] = v.get("gift", 0) + v[src] // per * plus


def finished(rows):
    """Достроенные земли: ключ → день последней ступени."""
    got = {}
    for r in rows:
        got.setdefault(land_of(r["note"]), []).append(r)
    return {k: max(r["day"] for r in v) for k, v in got.items() if len(v) >= len(land_steps(k))}


def is_open(land, done, has_offer):
    i = KEYS.index(land)
    return not i or KEYS[i - 1] in done and (has_offer or not LAND[land].get("offer"))


def current(rows, has_offer):
    """Земля, которую сейчас строят. Шпиль закрыт до оффера: тогда остаёмся на последней открытой."""
    done = finished(rows)
    last = HOME
    for k in KEYS:
        if not is_open(k, done, has_offer):
            break
        last = k
        if k not in done:
            break
    return last


def find_item(i):
    return L.FINDS[i] if i < len(L.FINDS) else L.EXTRA


def find_value(item):
    return L.SCRAP_BONUS if item[1] == SCRAP else L.RARE[item[1]][1]


def find_count(earned):
    """Сколько находок открыто и при каком заработке следующая: шаг растёт, 15, 19, 23…"""
    n, mark = 0, 15
    while mark <= earned:
        n += 1
        mark += 15 + 4 * n
    return n, mark


def offer():
    return any(i["status"] == "оффер" for i in IV._read(("Офферы",)))


def spent(c):
    G.ensure(c)
    return c.execute("SELECT * FROM growth WHERE kind=? ORDER BY id", (KIND,)).fetchall()


def state(c, land=None):
    """Земля land или та, что строится сейчас. built и next — её части, без префикса."""
    days = income(c)
    rows = spent(c)
    has_offer = offer()
    done = finished(rows)
    gifts(days, done)
    land = land or current(rows, has_offer)
    built = [local(r["note"]) for r in rows if land_of(r["note"]) == land]
    earned = sum(sum(v.values()) for v in days.values())
    found, mark = find_count(earned)
    bonus = sum(find_value(find_item(i)) for i in range(found))
    total = earned + bonus
    balance = total - sum(int(r["value"]) for r in rows)
    visits = len(IV.visits(c))
    opened = is_open(land, done, has_offer)
    nxt = next((s for s in land_steps(land) if s[0] not in built), None) if opened else None
    crown = ["crown"] if has_offer and land == HOME else []
    lands = []
    for x in L.LANDS:
        k = x["key"]
        have = {local(r["note"]) for r in rows if land_of(r["note"]) == k}
        steps = land_steps(k)
        lands.append(dict(key=k, name=x["name"], open=is_open(k, done, has_offer), done=k in done, built=len(have),
                          have=sorted(have),
                          steps=len(steps), price=sum(s[2] for s in steps),
                          left=sum(s[2] for s in steps if s[0] not in have)))
    st = dict(total=total, balance=balance, built=built + crown, visits=visits, offer=has_offer,
              today=days.get(G.today(c).isoformat(), {}), days=days, next=None, land=land, lands=lands,
              name=LAND[land]["name"], opened=opened, found=found, find_bonus=bonus, earned=earned, find_mark=mark,
              scraps=sum(1 for i in range(found) if find_item(i)[1] == SCRAP))
    if nxt:
        key, name, price, need = nxt
        st["next"] = dict(key=key, name=name, price=price, need=need, short=max(0, price - balance),
                          visits_short=0 if has_offer else max(0, need - visits))
        st["next"]["ready"] = not st["next"]["short"] and not st["next"]["visits_short"]
    return st


def blocked(n):
    """Почему следующую ступень пока нельзя, одной строкой; None — можно."""
    if not n or n["ready"]:
        return None
    if n["visits_short"]:
        return "нужно сходить на собеседование: ещё %s" % plural_visit(n["visits_short"])
    return "ещё %s" % energy(n["short"])


def build(c, src="pc", land=None):
    """Следующая ступень → (id строки или None, что сказать)."""
    st = state(c, land)
    n = st["next"]
    if not n:
        return None, "Здесь пока нечего строить." if st["built"] else "Эта земля ещё закрыта."
    why = blocked(n)
    if why:
        return None, "%s: %s." % (n["name"], why)
    gid = G.add(c, KIND, n["price"], full(st["land"], n["key"]), src)
    return gid, "Готово: %s. Осталось %s." % (n["name"], energy(st["balance"] - n["price"]))


def step_rows(st):
    """Ступени земли для списков: (ключ, название, цена, нужно, готова ли). Корона только у дома."""
    out = [(k, name, price, need, k in st["built"]) for k, name, price, need in land_steps(st["land"])]
    return out + ([(CROWN[0], CROWN[1], 0, 0, st["offer"])] if st["land"] == HOME else [])


# ── заметка Obsidian: видна с телефона, галочка следующей ступени строит её ─────────────────
LINE_RE = re.compile(r"^- \[[xXхХ]\] (.+?) — ", re.M)
HEAD = "---\ntags: [замок]\n---\n"


def note_text(st):
    out = [HEAD, "# Замок: %s\n" % G.GOAL_NAME,
           "Энергия: **%d** · всего заработано %d · походов на собеседования %d · находок %d\n" % (
               st["balance"], st["total"], st["visits"], st["found"]),
           "Заметку пишет hub. Поставьте галочку у следующей ступени, и она построится.\n"]
    for land in st["lands"]:
        if not land["open"]:
            continue
        out.append("## %s\n" % land["name"])
        for key, name, price, need, done in step_rows(dict(st, land=land["key"], built=land["have"])):
            cost = "только за оффер" if key == "crown" else "%d ⚡" % price
            if need:
                cost += ", нужно походов: %d" % need
            out.append("- [%s] %s — %s" % ("x" if done else " ", name, cost))
        out.append("")
    out += ["## Доход по дням\n", "| День | Всего | Откуда |", "|---|---|---|"]
    for day, v in sorted(st["days"].items(), reverse=True):
        if v:
            parts = ", ".join("%s %d" % (NAMES[k], v[k]) for k, _n in SOURCES if k in v)
            out.append("| %s | %d | %s |" % (day, sum(v.values()), parts))
    return "\n".join(out) + "\n"


def gains(c, st):
    """Что прибавилось с прошлого раза: [(источник, +энергия)]. Копим суммы по всем дням: если счёт
    упал (отменили запись), база молча опускается, а уведомление будет только за новое."""
    now = {}
    for v in st["days"].values():
        for k, n in v.items():
            now[k] = now.get(k, 0) + n
    if st["find_bonus"]:
        now["find"] = st["find_bonus"]
    try:
        seen = json.loads(H.meta_get(c, SEEN, "") or "null")
    except ValueError:
        seen = None
    if now != seen:
        H.meta_set(c, SEEN, json.dumps(now))
    if seen is None:                                # первый запуск — только запомнить
        return []
    return [(k, now[k] - seen.get(k, 0)) for k, _n in SOURCES if now.get(k, 0) > seen.get(k, 0)]


def note_tick(c):
    """Заметка и галочки из Obsidian. → прирост энергии для уведомления."""
    st = state(c)
    n = st["next"]
    if n:
        try:
            ticked = LINE_RE.findall(open(NOTE, encoding="utf-8").read())
        except OSError:
            ticked = []
        if n["name"] in ticked and build(c, "obsidian")[0]:
            st = state(c)
    G._write_if_changed(NOTE, note_text(st))
    return gains(c, st), st["balance"]


# ── бот ──────────────────────────────────────────────────────────────────────────────────
def tg(c, note=None):
    import hubtg as T
    st = state(c)
    done = sum(1 for k in st["built"] if k != "crown")
    out = ["<b>◆ ЗАМОК: %s</b>" % T.esc(G.GOAL_NAME)] + (["<i>%s</i>" % T.esc(note)] if note else [])
    out.append("🗺 %s" % T.esc(st["name"]))
    out.append("⚡ Энергия: <b>%d</b> · построено %d из %d" % (st["balance"], done, len(land_steps(st["land"]))))
    today = sum(st["today"].values())
    if today:
        out.append("Сегодня +%d: %s" % (today, ", ".join("%s %d" % (NAMES[k], st["today"][k])
                                                         for k, _n in SOURCES if k in st["today"])))
    n = st["next"]
    kb = None
    if n:
        out.append("Дальше: %s, %d ⚡" % (T.esc(n["name"]), n["price"]))
        why = blocked(n)
        if why:
            out.append("Пока нельзя: " + T.esc(why))
        else:
            kb = [[T.btn("⚡ Построить: %s" % n["name"], "g:castle")]]
    else:
        out.append("Дальше Шпиль Морока: его ворота открывает только настоящий оффер." if not st["offer"]
                   else "Все земли зажжены.")
    return T.Html("\n".join(out)), kb


def tg_build(c):
    gid, said = build(c, "tg")
    if gid:
        G._undo_set(c, "Замок: ступень", [gid])
    return ("⚡ Построено" if gid else "Пока нельзя"), tg(c, said)


# ── виджет ──────────────────────────────────────────────────────────────────────────────
def widget_json(c):
    st = state(c)
    near = IV.nearest()
    return dict(balance=st["balance"], built=st["built"], next=st["next"], today=sum(st["today"].values()),
                visits=st["visits"], steps=len(land_steps(st["land"])), why=blocked(st["next"]), land=st["land"],
                land_name=st["name"],
                near="%s, %s" % (near["name"], IV.when_text(near["when"], near["timed"])) if near else "")


if __name__ == "__main__":
    con = H.connect()
    if sys.argv[1:] == ["--json"]:
        print(json.dumps(widget_json(con), ensure_ascii=False))
    elif sys.argv[1:] == ["note"]:
        note_tick(con)
    else:
        s = state(con)
        print("Энергия: %d, всего %d, походов %d" % (s["balance"], s["total"], s["visits"]))
        print("Построено:", ", ".join(s["built"]) or "ничего")
        print("Дальше:", s["next"])
