#!/usr/bin/env python3
"""Новая вкладка Helium — как в Zen. 29.10.2026.

Пользователь (снимок новой вкладки Zen): «и в пустую вкладку helium можешь также добавить
как в Zen». Вид — тот же: пиксельные часы, «Good night, sir» по времени суток, рамка
с датой и полосой дня, обои под вуалью, параллакс с кнопкой слева снизу.

Helium (Chromium) не читает файлы вне расширения, поэтому страница — распакованное
расширение с chrome_url_overrides.newtab, а палитру и миниатюру обоев в него кладёт
этот скрипт (theme_changer.sh зовёт `sync` при каждой смене обоев). Страница сама
перечитывает theme.json раз в 2 с — новые цвета видны без перезапуска браузера.
Стартовую вкладку открывает заново bg.js: при запуске подмена ещё не действует.
Стили берутся из Zen (~/.config/zen-jarvis/newtab/newtab.css) — один источник вида.
Расширение грузится флагом --load-extension в ~/.config/helium-browser-flags.conf.

    helium_newtab.py build    собрать расширение (страница + палитра)
    helium_newtab.py sync     только палитра и обои (после смены обоев)
    helium_newtab.py check    самопроверка
    helium_newtab.py icon [spark|bolt]   значок вкладки: звёздочка или молния
"""
import json
import os
import shutil
import zlib
import sys

HOME = os.path.expanduser("~")
OUT = os.path.join(HOME, ".config/hypr/state/helium-newtab")
ZEN_CSS = os.path.join(HOME, ".config/zen-jarvis/newtab/newtab.css")
COLORS = os.path.join(HOME, ".cache/matugen/colors.json")
THUMB = os.path.join(HOME, ".cache/matugen/wallpaper-thumb.png")
FLAGS = os.path.join(HOME, ".config/helium-browser-flags.conf")
ICON_STATE = os.path.join(HOME, ".config/hypr/state/helium-newtab-icon")
KEYS = {"--accent": "primary", "--surface": "surface",
        "--on-surface": "on_surface", "--on-surface-variant": "on_surface_variant"}

MANIFEST = {
    "manifest_version": 3,
    "name": "Jarvis New Tab",
    "version": "1.0",
    "icons": {"16": "icon16.png", "32": "icon32.png", "48": "icon48.png", "128": "icon128.png"},
    "description": "Новая вкладка как в Zen — пишет helium_newtab.py",
    "chrome_url_overrides": {"newtab": "newtab.html"},
    "permissions": ["tabs"],
    "background": {"service_worker": "bg.js"},
    "content_scripts": [{"matches": ["*://www.youtube.com/*", "*://m.youtube.com/*"],
                         "js": ["yt_keys.js"], "run_at": "document_start", "world": "MAIN"},
                        {"matches": ["<all_urls>"], "js": ["pip_key.js"], "run_at": "document_start",
                         "world": "MAIN", "all_frames": True}],
}

# Картинка в картинке как в Zen (29.10.2026, Просьба: «при Ctrl+T в helium всё ещё открывается
# мини-плеер… пусть открывается на ctrl+shift+] как в zen»). Ctrl+Shift+] (по code — и в русской
# раскладке, бинд niri шлёт её через wtype) открывает/закрывает картинку. Само по себе окно больше
# не всплывает: Chromium открывает его при уходе с вкладки, только если страница повесила обработчик
# mediaSession «enterpictureinpicture» (YouTube сам и расширение «Картинка в картинке» из своего мира).
# Свой мир — подменой setActionHandler, чужой — снимаем обработчик раз в секунду (он общий на страницу).
PIP_JS = r"""// Картинка в картинке по Ctrl+Shift+] — собирает helium_newtab.py
"use strict";
(() => {
  const ms = navigator.mediaSession, proto = window.MediaSession && MediaSession.prototype;
  if (ms && proto && proto.setActionHandler) {
    const set = proto.setActionHandler;
    proto.setActionHandler = function (action, handler) {
      if (action === "enterpictureinpicture") return;
      return set.call(this, action, handler);
    };
    const drop = () => { try { set.call(ms, "enterpictureinpicture", null); } catch (e) {} };
    drop();
    setInterval(drop, 1000);
  }
  const pick = () => {
    let best = null, area = 0;
    for (const v of document.querySelectorAll("video")) {
      if (v.readyState === 0 || v.disablePictureInPicture) continue;
      const r = v.getBoundingClientRect(), a = r.width * r.height + (v.paused ? 0 : 1e7);
      if (a > area) { best = v; area = a; }
    }
    return best;
  };
  window.addEventListener("keydown", (e) => {
    if (!e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey || e.code !== "BracketRight") return;
    e.preventDefault();
    e.stopImmediatePropagation();
    if (document.pictureInPictureElement) {
      document.exitPictureInPicture().catch(() => {});
      return;
    }
    const v = pick();
    if (v) v.requestPictureInPicture().catch(() => {});
  }, true);
})();
"""

# Клавиши YouTube как в Zen (29.10.2026, Просьба: «почему в ютуб в хелиуме не работают бинды
# "=/-" для регулировки громкости, как в zen»). В Zen это делает live-theme.js
# (ytRuKeysFrameScript) — здесь то же содержимым расширения: «-»/«=»/«+» — громкость ±5%
# через API плеера (YouTube запоминает её и двигает ползунок), без плеера — элементом video;
# k/j/l/f/t/m/c/i в русской раскладке. world MAIN — чтобы видеть movie_player.getVolume.
YT_JS = r"""// Клавиши YouTube как в Zen — собирает helium_newtab.py
"use strict";
(() => {
  const doc = document, win = window, root = doc.documentElement;
  if (!root || root.hasAttribute("jarvis-ru-keys")) return;
  root.setAttribute("jarvis-ru-keys", "1");
  const RU2EN = { "л": "k", "о": "j", "д": "l", "а": "f", "е": "t", "ь": "m", "с": "c", "ш": "i" };
  const CYRILLIC = /^[\u0400-\u04FF]$/;
  const css = () => {
    const style = doc.createElement("style");
    style.textContent = `
      html.ru-hotkey #movie_player .ytp-chrome-bottom,
      html.ru-hotkey #movie_player .ytp-gradient-bottom,
      html.ru-hotkey #movie_player .ytp-chrome-top,
      html.ru-hotkey #movie_player .ytp-gradient-top { opacity: 0 !important; transition: none !important; }
      html.ru-hotkey .ytp-bezel, html.ru-hotkey .ytp-bezel-text-wrapper,
      html.ru-hotkey .ytp-doubletap-ui-legacy { display: none !important; }`;
    (doc.head || root).appendChild(style);
  };
  if (doc.head) css(); else doc.addEventListener("DOMContentLoaded", css, { once: true });

  const video = () => {
    const all = [...doc.querySelectorAll("video")];
    if (!all.length) return null;
    const playing = all.find(v => !v.paused && !v.ended && v.readyState > 2);
    if (playing) return playing;
    let best = null, area = 0;
    for (const v of all) {
      const r = v.getBoundingClientRect();
      const a = r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < win.innerHeight ? r.width * r.height : 0;
      if (a > area) { best = v; area = a; }
    }
    return best || all[0];
  };
  const click = sel => { const b = doc.querySelector(sel); if (b) b.click(); };
  const ACT = {
    k: () => { const v = video(); if (v) { if (v.paused) v.play(); else v.pause(); } },
    j: () => { const v = video(); if (v) v.currentTime -= 10; },
    l: () => { const v = video(); if (v) v.currentTime += 10; },
    m: () => { const v = video(); if (v) v.muted = !v.muted; },
    f: () => click(".ytp-fullscreen-button"),
    t: () => click(".ytp-size-button"),
    c: () => click(".ytp-subtitles-button"),
    i: () => click(".ytp-miniplayer-button"),
  };

  const STEP = 5;
  let hud = null, hudTimer = null;
  const showVolume = pct => {
    const host = doc.getElementById("movie_player") || doc.body;
    if (!hud || !hud.isConnected) {
      hud = doc.createElement("div");
      hud.setAttribute("style", "position:absolute;top:12%;left:50%;transform:translateX(-50%);" +
        "z-index:2147483647;padding:8px 16px;border-radius:12px;background:rgba(0,0,0,.6);color:#fff;" +
        "font:600 18px/1.2 'JetBrainsMono Nerd Font',monospace;pointer-events:none;transition:opacity .25s;");
      host.appendChild(hud);
    }
    // Значок — SVG, не глиф Nerd Font: Helium не отдаёт сайтам системные шрифты (вместо значка был квадрат).
    // innerHTML на YouTube запрещён Trusted Types — собираем узлы руками.
    const NS = "http://www.w3.org/2000/svg";
    const svg = doc.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 16 16");
    svg.setAttribute("width", "18");
    svg.setAttribute("height", "18");
    svg.setAttribute("style", "vertical-align:-3px;margin-right:10px;fill:#fff;stroke:#fff;");
    const path = (d, st) => { const e = doc.createElementNS(NS, "path"); e.setAttribute("d", d);
      e.setAttribute("style", st); svg.appendChild(e); };
    path("M2 6h3l4-3v10l-4-3H2z", "stroke:none");
    if (pct === 0) path("M11 6l4 4M15 6l-4 4", "fill:none;stroke-width:1.6");
    else {
      path("M11 5.5q2 2.5 0 5", "fill:none;stroke-width:1.4");
      if (pct > 50) path("M13 3.5q3.5 4.5 0 9", "fill:none;stroke-width:1.4");
    }
    hud.replaceChildren(svg, doc.createTextNode(pct + "%"));
    hud.style.opacity = "1";
    win.clearTimeout(hudTimer);
    hudTimer = win.setTimeout(() => { if (hud) hud.style.opacity = "0"; }, 900);
  };
  const changeVolume = delta => {
    const api = doc.getElementById("movie_player");
    if (api && typeof api.getVolume === "function" && typeof api.setVolume === "function") {
      const pct = Math.max(0, Math.min(100, Math.round((api.getVolume() + delta) / STEP) * STEP));
      if (delta > 0 && api.isMuted && api.isMuted()) api.unMute();
      api.setVolume(pct);
      showVolume(api.isMuted && api.isMuted() ? 0 : pct);
      return true;
    }
    const v = video();
    if (!v) return false;
    const pct = Math.max(0, Math.min(100, Math.round((v.volume * 100 + delta) / STEP) * STEP));
    if (delta > 0) v.muted = false;
    v.volume = pct / 100;
    showVolume(v.muted ? 0 : pct);
    return true;
  };
  const VOLUME_KEYS = { "-": -STEP, "=": STEP, "+": STEP };
  let timer = null;
  doc.addEventListener("keydown", e => {
    const el = e.target;
    if (el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.isContentEditable)) return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;
    if (e.key in VOLUME_KEYS) {
      // раньше YouTube: у него «-»/«=» меняют размер субтитров
      if (changeVolume(VOLUME_KEYS[e.key])) { e.preventDefault(); e.stopImmediatePropagation(); }
      return;
    }
    const key = (e.key || "").toLowerCase();
    if (!CYRILLIC.test(key)) return;
    root.classList.add("ru-hotkey");
    win.clearTimeout(timer);
    timer = win.setTimeout(() => root.classList.remove("ru-hotkey"), 2000);
    const act = ACT[RU2EN[key]];
    if (!act) return;
    e.preventDefault();
    e.stopPropagation();
    act();
  }, true);
  doc.addEventListener("mousemove", () => {
    if (root.classList.contains("ru-hotkey")) { win.clearTimeout(timer); root.classList.remove("ru-hotkey"); }
  }, true);
})();
"""

# Стартовая вкладка (29.10.2026, Просьба: «стартовая страница Helium тоже должна
# отображаться как и пустая вкладка»): расширения из --load-extension подключаются
# позже, чем открывается первая вкладка, — она остаётся встроенной. При запуске
# браузера пустые вкладки открываются заново — уже нашей страницей.
BG_JS = r"""// Стартовая вкладка Helium — заново, когда подмена новой вкладки уже действует.
"use strict";
const NTP = /^(chrome|helium):\/\/(newtab|new-tab-page)\/?$/;
function fix(left) {
  chrome.tabs.query({}, tabs => {
    const ntp = tabs.filter(t => NTP.test(t.pendingUrl || t.url || ""));
    for (const t of ntp) chrome.tabs.update(t.id, { url: "chrome://newtab/" });
    if (!ntp.length && left > 0) setTimeout(() => fix(left - 1), 500);
  });
}
chrome.runtime.onStartup.addListener(() => fix(6));
chrome.runtime.onInstalled.addListener(() => fix(2));
"""

HTML = """<!DOCTYPE html>
<!-- Новая вкладка Helium — как в Zen; собирает helium_newtab.py -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>New Tab</title>
  <link rel="icon" sizes="16x16" href="icon16.png">
  <link rel="icon" sizes="32x32" href="icon32.png">
  <link rel="stylesheet" href="newtab.css">
  <script src="newtab.js" defer></script>
</head>
<body>
  <div id="bg"></div>
  <div id="veil"></div>
  <main>
    <div id="time">--:--</div>
    <div id="greet"></div>
    <div id="box">
      <div id="date"></div>
      <div id="day"><span id="bar"></span><span id="pct"></span></div>
    </div>
  </main>
  <button id="plx" type="button" title="Parallax">
    <svg viewBox="0 0 16 16" width="16" height="16" shape-rendering="crispEdges" fill="currentColor" aria-hidden="true">
      <path d="M5 1h10v10h-4v-2h2V3H7v2H5Z"/>
      <path d="M1 5h10v10H1Zm2 2v6h6V7Z"/>
    </svg>
  </button>
</body>
</html>
"""

# Шрифт системы на страницах (helium-font) сюда не доходит — страницы расширений он
# не трогает, но Chromium без !important отдавал #time свой шрифт (заметка 20.10).
CSS_TAIL = """
/* Helium: шрифт часов и подписей — с !important (helium_newtab.py) */
main, #time, #greet, #date, #day, #bar {
  font-family: "CozetteVectorBold", "CozetteVector", "PxPlus HP 100LX 6x8 Jarvis", monospace !important;
}
"""

JS = r"""// Новая вкладка Helium — как в Zen (newtab.js там же), собирает helium_newtab.py.
// Палитра и миниатюра обоев — theme.json и bg.png рядом, их кладёт `helium_newtab.py sync`.
"use strict";
const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December"];
const CELLS = 16;
const HEX = /^#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?$/;
const $ = id => document.getElementById(id);
const two = n => String(n).padStart(2, "0");

function greeting(h) {
  if (h < 5) return "Good night, sir";
  if (h < 12) return "Good morning, sir";
  if (h < 18) return "Good afternoon, sir";
  if (h < 23) return "Good evening, sir";
  return "Good night, sir";
}

function drawClock() {
  const d = new Date();
  $("time").textContent = (two(d.getHours()) + ":" + two(d.getMinutes())).replace(/0/g, "O");
  $("date").textContent = DAYS[d.getDay()] + " · " + MONTHS[d.getMonth()] + " " + d.getDate();
  $("greet").textContent = greeting(d.getHours());
  drawDay(d);
}

let lastLit = -1;
function drawDay(d) {
  const part = (d.getHours() * 60 + d.getMinutes()) / 1440;
  const lit = Math.floor(part * CELLS);
  if (lit !== lastLit) {
    lastLit = lit;
    const bar = $("bar");
    bar.textContent = "";
    for (let i = 0; i < CELLS; i++) {
      const s = document.createElement("span");
      s.textContent = "■";
      if (i >= lit) s.className = "off";
      bar.appendChild(s);
    }
  }
  $("pct").textContent = "DAY " + Math.floor(part * 100) + "%";
}

let lastStamp = null;
async function refreshTheme() {
  let t;
  try {
    t = await (await fetch("theme.json", { cache: "no-store" })).json();
  } catch (e) { return; }
  if (t.stamp === lastStamp) return;
  lastStamp = t.stamp;
  for (const [cssVar, v] of Object.entries(t.colors || {})) {
    if (HEX.test(v)) document.documentElement.style.setProperty(cssVar, v);
  }
  // значок вкладки — в цветах новых обоев (без ?v Chromium держал бы прежний)
  for (const l of document.querySelectorAll('link[rel="icon"]')) {
    l.href = l.getAttribute("href").split("?")[0] + "?v=" + t.stamp;
  }
  if (t.thumb) {
    const url = "bg.png?v=" + t.thumb;
    const img = new Image();
    img.onload = () => { $("bg").style.backgroundImage = `url("${url}")`; $("bg").classList.add("ready"); };
    img.src = url;
  }
}

let clockTimer = null, themeTimer = null;
function start() {
  drawClock();
  refreshTheme();
  if (!clockTimer) clockTimer = setInterval(drawClock, 1000);
  if (!themeTimer) themeTimer = setInterval(refreshTheme, 2000);
}
function stop() {
  clearInterval(clockTimer); clockTimer = null;
  clearInterval(themeTimer); themeTimer = null;
}
document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));

// Параллакс — как в Zen; вкл/выкл помнит localStorage вместо pref
const PLX_KEY = "jarvis.newtab.parallax";
let plxOn = true, plxTx = 0, plxTy = 0, plxX = 0, plxY = 0, plxRaf = 0;
try { plxOn = localStorage.getItem(PLX_KEY) !== "0"; } catch (e) {}

function plxFrame() {
  plxX += (plxTx - plxX) * 0.08;
  plxY += (plxTy - plxY) * 0.08;
  const root = document.documentElement.style;
  root.setProperty("--px", plxX.toFixed(4));
  root.setProperty("--py", plxY.toFixed(4));
  plxRaf = Math.abs(plxTx - plxX) + Math.abs(plxTy - plxY) > 0.001 ? requestAnimationFrame(plxFrame) : 0;
}
function plxAim(x, y) {
  plxTx = x; plxTy = y;
  if (!plxRaf) plxRaf = requestAnimationFrame(plxFrame);
}
function plxShow() {
  const b = $("plx");
  b.classList.toggle("on", plxOn);
  b.title = plxOn ? "Parallax: on" : "Parallax: off";
}
document.addEventListener("mousemove", e => {
  if (plxOn) plxAim(e.clientX / innerWidth * 2 - 1, e.clientY / innerHeight * 2 - 1);
});
document.documentElement.addEventListener("mouseleave", () => plxAim(0, 0));
$("plx").addEventListener("click", () => {
  plxOn = !plxOn;
  try { localStorage.setItem(PLX_KEY, plxOn ? "1" : "0"); } catch (e) {}
  if (!plxOn) plxAim(0, 0);
  plxShow();
});
plxShow();
start();
"""


def write(name, text):
    path = os.path.join(OUT, name)
    try:
        if open(path).read() == text:
            return
    except OSError:
        pass
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, path)


def palette():
    try:
        j = json.load(open(COLORS))
    except (OSError, ValueError):
        return {}
    src = j.get("colors", j)
    out = {}
    for var, key in KEYS.items():
        v = src.get(key)
        if isinstance(v, dict):
            v = v.get("dark") or v.get("default") or v.get("hex")
        if isinstance(v, str) and v.startswith("#"):
            out[var] = v
    return out


# Значок вкладки (29.10.2026, Просьба: «почему иконка вкладки — J? Добавь нашу фирменную
# иконку в стиле системы»). Без значка Chromium рисует первую букву имени расширения.
# Знак — телевизор static с S на экране (~/Pictures/logo/static-logo, static-tv), заново
# нарисованный по сетке 16×16, чтобы во вкладке пиксели были чёткими; цвета — палитра обоев.
BOLT16 = (                                  # молния staticOS (как на входе и в заставке)
    "........OOOOO...",
    ".......OlbbbO...",
    "......OlbbbO....",
    ".....OlbbbO.....",
    "....OlbbbO......",
    "...OlbbbOOOOOO..",
    "..OlbbbbbbbbbO..",
    "..OOOOOObbbbO...",
    "......ObbbbO....",
    ".....ObbbbO.....",
    "....ObbbO.......",
    "...ObbbO........",
    "...ObbO.........",
    "..ObbO..........",
    "..ObO...........",
    "..OO............",
)
SPARK16 = (                                 # звёздочка с ореолом
    ".......b........",
    ".......b........",
    ".......b........",
    ".....hhbhh......",
    "....hhblbhh.....",
    "...hhgblbghh....",
    "...hbbbWbbbh....",
    "bbbbllWWWllbbbb.",
    "...hbbbWbbbh....",
    "...hhgblbghh....",
    "....hhblbhh.....",
    ".....hhbhh......",
    ".......b........",
    ".......b........",
    ".......b........",
    "................",
)
ICONS = {"spark": SPARK16, "bolt": BOLT16}


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def icon_name():
    try:
        name = open(ICON_STATE).read().strip()
    except OSError:
        name = ""
    return name if name in ICONS else "spark"


def icons(colors):
    from PIL import Image
    acc = _hex(colors.get("--accent", "#a6c8ff"))
    sur = _hex(colors.get("--surface", "#0e141c"))
    ink = _hex(colors.get("--on-surface", "#dee2ef"))
    pal = {"O": _mix(acc, sur, 0.7) + (255,), "b": acc + (255,), "l": _mix(acc, ink, 0.6) + (255,),
           "W": ink + (255,), "g": acc + (110,), "h": acc + (50,)}
    im = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    for y, row in enumerate(ICONS.get(icon_name(), SPARK16)):
        for x, ch in enumerate(row):
            if ch in pal:
                im.putpixel((x, y), pal[ch])
    for n in (16, 32, 48, 128):
        tmp = os.path.join(OUT, "icon%d.png.tmp" % n)
        im.resize((n, n), Image.NEAREST).save(tmp, "PNG")
        os.replace(tmp, os.path.join(OUT, "icon%d.png" % n))


def sync():
    os.makedirs(OUT, exist_ok=True)
    thumb = 0
    try:
        thumb = int(os.path.getmtime(THUMB))
        shutil.copyfile(THUMB, os.path.join(OUT, "bg.png.tmp"))
        os.replace(os.path.join(OUT, "bg.png.tmp"), os.path.join(OUT, "bg.png"))
    except OSError:
        pass
    colors = palette()
    try:
        icons(colors)
    except Exception as e:                  # без значка страница всё равно работает
        print("значок не собран: %r" % (e,), file=sys.stderr)
    try:                                    # значок в метке: Chromium кэширует его по адресу
        ico = zlib.crc32(open(os.path.join(OUT, "icon16.png"), "rb").read())
    except OSError:
        ico = 0
    stamp = "%s-%s-%s" % (thumb, zlib.crc32(json.dumps(colors, sort_keys=True).encode()), ico)
    write("newtab.html", HTML.replace('.png">', '.png?v=%s">' % ico))  # стартовые вкладки — сразу новый
    write("theme.json", json.dumps({"stamp": stamp, "thumb": thumb, "colors": colors}, indent=1) + "\n")


def build():
    os.makedirs(OUT, exist_ok=True)
    write("manifest.json", json.dumps(MANIFEST, indent=2, ensure_ascii=False) + "\n")
    write("newtab.js", JS)
    write("bg.js", BG_JS)
    write("yt_keys.js", YT_JS)
    write("pip_key.js", PIP_JS)
    try:
        css = open(ZEN_CSS).read()
    except OSError:
        css = ""
    write("newtab.css", css + CSS_TAIL)
    sync()


def check():
    bad = []
    for name in ("manifest.json", "newtab.html", "newtab.css", "newtab.js", "bg.js", "yt_keys.js",
                 "pip_key.js", "theme.json", "icon16.png"):
        if not os.path.exists(os.path.join(OUT, name)):
            bad.append("нет %s — `helium_newtab.py build`" % name)
    if not os.path.exists(ZEN_CSS):
        bad.append("нет стилей Zen %s" % ZEN_CSS)
    try:
        if OUT not in open(FLAGS).read():
            bad.append("расширение не в --load-extension (%s)" % FLAGS)
    except OSError:
        bad.append("нет %s" % FLAGS)
    try:
        t = json.load(open(os.path.join(OUT, "theme.json")))
        if len(t.get("colors") or {}) != len(KEYS):
            bad.append("в theme.json не все цвета")
    except (OSError, ValueError):
        pass
    for p in bad:
        print("✗", p)
    print("helium_newtab: %s" % ("в порядке" if not bad else "проблем %d" % len(bad)))
    return 1 if bad else 0


def main():
    cmd = (sys.argv[1:] or ["build"])[0]
    if cmd == "check":
        return check()
    if cmd == "sync":
        sync()
        return 0
    if cmd == "icon":
        if len(sys.argv) > 2:
            if sys.argv[2] not in ICONS:
                print("значки: %s" % " ".join(ICONS), file=sys.stderr)
                return 2
            with open(ICON_STATE, "w") as f:
                f.write(sys.argv[2] + "\n")
            sync()
        print(icon_name())
        return 0
    build()
    return 0


if __name__ == "__main__":
    sys.exit(main())
