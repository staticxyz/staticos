#!/usr/bin/env python3
"""Плашка «Сеть» — щелчок по значку «lan» в верхнем баре (05.10.2026).

Просьба: «не спидтест, а диагностика сети». Поэтому сверху — цепочка
Кабель → Роутер → Интернет → DNS с цветными точками: сразу видно, на каком
звене беда. Ниже — скорость канала, адреса, внешний IP и провайдер, живой
график трафика за минуту, пинг до роутера и до интернета (среднее, разброс,
потери). Замер скорости (speed.cloudflare.com) — только по кнопке, история
последних замеров — в ~/.cache/jarvis-speedtest.json.

Всё живёт, только пока плашка открыта: таймеры и пинги принадлежат процессу
плашки, закрылась — процесс вышел, и всё остановилось. Фоновых служб нет.
Всё, что может задуматься (ping, DNS, HTTP), — в отдельных потоках, чтобы
плашка не замерзала.
"""
import collections
import http.client
import json
import os
import re
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

import gi

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402

# Второй щелчок по значку закрывает открытую плашку.
popup_theme.single_instance(__file__)

# 08.10.2026: тот же файл — плашка Wi-Fi (ПКМ по значку Wi-Fi). Запускается
# через ссылку wifi_net_popup.py → lan_popup.py: режим — по имени, и у
# single_instance свой путь, так что плашки «lan» и «Wi-Fi» не закрывают
# друг друга.
WIFI = os.path.basename(__file__).startswith("wifi")

gi.require_version("Gtk", "3.0")
# Gdk явно: иначе gi может успеть подтянуть Gdk 4.0 от gtk4-layer-shell.
gi.require_version("Gdk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, GtkLayerShell, Pango, PangoCairo  # noqa: E402

WIDTH = 344          # 08.10.2026: компактнее (было 380)
TICK_MS = 1000          # трафик и состояние кабеля
PING_MS = 2000          # пинг роутера и интернета
DNS_MS = 10000          # проверка DNS
INFO_MS = 10000         # маршрут, адрес, DNS-серверы
GRAPH_SEC = 60          # окно графика, с
PING_WIN = 30           # по скольким последним пингам считать статистику
NET_HOST = "1.1.1.1"    # «интернет» для пинга
DNS_NAMES = ("example.com", "wikipedia.org", "cloudflare.com")

IP_CACHE = os.path.expanduser("~/.cache/jarvis-lan-ipinfo.json")
IP_TTL = 600            # внешний IP и провайдер — не чаще раза в 10 минут
SPEED_FILE = os.path.expanduser("~/.cache/jarvis-speedtest.json")
SPEED_KEEP = 20          # замеры кабеля и Wi-Fi вместе
SPEED_SHOW = 4

# Замер скорости: время фазы, потоки, предел объёма (на гигабите упрёмся в
# объём раньше времени — незачем качать гигабайт ради одной цифры).
ST_HOST = "speed.cloudflare.com"
ST_DOWN = (8.0, 4, 100_000_000)       # 05.10.2026: не больше 100 МБ на замер
ST_UP = (8.0, 3, 50_000_000)
ST_WARM = 1.0           # первую секунду не считаем — TCP ещё разгоняется
ST_HDR = {"User-Agent": "jarvis-lan/1.0"}

# Светофор. В палитре обоев зелёного и жёлтого нет — берём мягкие свои,
# красный — error из палитры.
# Простой вид (08.10.2026, Просьба: «глаза теряются»): сверху вывод крупно,
# трафик свой и других, кнопка замера; остальное — под «Подробнее».
DETAILS_FILE = os.path.expanduser("~/.config/hypr/state/lan-popup-details")
WIFI_MS = 2000          # сигнал Wi-Fi (iw) — плашка Wi-Fi
OK_COLOR = "#9ece6a"
WARN_COLOR = "#e0af68"

EXTRA_CSS = """
/* Пиксельный шрифт кеглем 16 — кратно его сетке 8 px, иначе мылится (12 тоже мылится, замер 05.10.2026). */
.popup-box { font-family: 'PxPlus HP 100LX 6x8 Jarvis', 'JetBrainsMono NF', sans-serif;
             font-size: 12px; padding: 10px 12px 10px 12px; }
label { font-weight: normal; font-size: 12px; }
label.title { font-size: 16px; }
label.big { font-size: 16px; }
label.dim { color: %(on_surface_variant)s; }
label.sec { color: %(primary)s; }
label.ok { color: %(ok)s; }
label.warn { color: %(warn)s; }
label.bad { color: %(error)s; }
label.down { color: %(primary)s; }
label.up { color: %(tertiary)s; }
label.oth { color: %(secondary)s; }
separator { margin: 3px 0; }
button.go { font-size: 12px; font-weight: normal; padding: 6px 12px; }
label.verdict { font-size: 16px; }
button.more { font-size: 12px; font-weight: normal; padding: 2px 8px; min-height: 0;
              background: none; border: none; box-shadow: none;
              color: %(on_surface_variant)s; }
button.more:hover { color: %(primary)s; }
button.go:disabled { background-color: %(surface_high)s; color: %(on_surface_variant)s; }
progressbar trough { min-height: 6px; border: none; border-radius: 3px;
                     background-color: %(surface_container)s; }
progressbar progress { min-height: 6px; border: none; border-radius: 3px;
                       background-color: %(primary)s; }
"""


# ── данные о сети ─────────────────────────────────────────────────────────
def sysfs(iface, name):
    try:
        with open(f"/sys/class/net/{iface}/{name}") as f:
            return f.read().strip()
    except OSError:
        return None


def run(cmd, timeout=3):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def default_route():
    """(интерфейс, шлюз) маршрута по умолчанию с наименьшей метрикой."""
    try:
        routes = json.loads(run(["ip", "-j", "route", "show", "default"]) or "[]")
    except ValueError:
        routes = []
    routes = [r for r in routes if r.get("dev")]
    if not routes:
        return None, None
    r = min(routes, key=lambda r: r.get("metric", 0))
    return r["dev"], r.get("gateway")


def wired_iface():
    """Проводной интерфейс на случай, если маршрута нет (кабель выдернут)."""
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return None
    for n in names:
        if (os.path.exists(f"/sys/class/net/{n}/device")
                and not os.path.exists(f"/sys/class/net/{n}/wireless")):
            return n
    return None


def local_addr(iface):
    try:
        data = json.loads(run(["ip", "-j", "-4", "addr", "show", "dev", iface]) or "[]")
        for a in data[0].get("addr_info", []):
            return "%s/%s" % (a["local"], a["prefixlen"])
    except (ValueError, IndexError, KeyError):
        pass
    return None


def dns_servers(iface):
    """DNS-серверы: systemd-resolved, затем NetworkManager, затем resolv.conf."""
    out = run(["resolvectl", "dns", iface])
    found = re.findall(r"[\d.]+\d|[0-9a-f:]+:[0-9a-f:]+", out.split(":", 1)[-1]) if out else []
    if found:
        return found
    out = run(["nmcli", "-g", "IP4.DNS", "device", "show", iface])
    found = [s.strip() for s in out.replace("|", "\n").splitlines() if s.strip()]
    if found:
        return found
    try:
        with open("/etc/resolv.conf") as f:
            return [ln.split()[1] for ln in f if ln.startswith("nameserver")]
    except (OSError, IndexError):
        return []


def ext_info(gw):
    """Внешний IP, провайдер, город — ip-api.com, с кэшем на IP_TTL.

    Кэш привязан к шлюзу: сменилась сеть — спрашиваем заново.
    """
    try:
        with open(IP_CACHE) as f:
            c = json.load(f)
        if time.time() - c.get("t", 0) < IP_TTL and c.get("gw") == gw:
            return c
    except (OSError, ValueError):
        pass
    try:
        url = ("http://ip-api.com/json/?lang=ru"
               "&fields=status,query,isp,org,country,countryCode,city")
        with urllib.request.urlopen(url, timeout=5) as r:
            d = json.load(r)
        if d.get("status") != "success":
            return None
        d.update(t=time.time(), gw=gw)
        os.makedirs(os.path.dirname(IP_CACHE), exist_ok=True)
        with open(IP_CACHE + ".tmp", "w") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(IP_CACHE + ".tmp", IP_CACHE)
        return d
    except Exception:
        return None


def ping_once(host):
    """Время ответа, мс, или None — нет ответа за секунду."""
    out = run(["ping", "-n", "-c1", "-W1", host], timeout=3)
    m = re.search(r"time[=<]([\d.]+)", out)
    return float(m.group(1)) if m else None


def dns_probe(name, timeout=3.0):
    """Время разрешения имени, мс, или None. getaddrinfo не умеет таймаут —
    поэтому он в своём потоке, а мы ждём не дольше timeout."""
    res = {}

    def work():
        t = time.monotonic()
        try:
            socket.getaddrinfo(name, 443, proto=socket.IPPROTO_TCP)
            res["ms"] = (time.monotonic() - t) * 1000
        except OSError:
            pass
    th = threading.Thread(target=work, daemon=True)
    th.start()
    th.join(timeout)
    return res.get("ms")


def ping_stats(samples):
    """(среднее, разброс, потери %) по списку времён (None — потеря)."""
    if not samples:
        return None, None, None
    ok = [s for s in samples if s is not None]
    loss = 100.0 * (len(samples) - len(ok)) / len(samples)
    avg = statistics.mean(ok) if ok else None
    pairs = [abs(a - b) for a, b in zip(samples, samples[1:])
             if a is not None and b is not None]
    jitter = statistics.mean(pairs) if pairs else None
    return avg, jitter, loss


def fmt_rate(bps):
    """Бит/с -> «94.3 Мбит/с»."""
    if bps is None:
        return "—"
    for div, unit in ((1e9, "Гбит/с"), (1e6, "Мбит/с"), (1e3, "Кбит/с")):
        if bps >= div:
            v = bps / div
            return ("%.0f %s" if v >= 100 else "%.1f %s") % (v, unit)
    return "%.0f бит/с" % bps


def fmt_ms(ms):
    if ms is None:
        return "—"
    return "%.1f мс" % ms if ms < 10 else "%.0f мс" % ms


def fmt_link(mbit):
    if mbit >= 1000 and mbit % 1000 == 0:
        return "%d Гбит/с" % (mbit // 1000)
    return "%d Мбит/с" % mbit


# ── Wi-Fi ─────────────────────────────────────────────────────────────────
def wireless_iface():
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        return None
    for n in names:
        if os.path.exists(f"/sys/class/net/{n}/wireless"):
            return n
    return None


def wifi_radio_on():
    return "enabled" in run(["nmcli", "radio", "wifi"])


def wifi_link(iface):
    """Связь с точкой доступа по `iw` (без root): сигнал, частота, скорость.
    None — не подключён."""
    out = run(["iw", "dev", iface, "link"])
    if not out or "Not connected" in out:
        return None
    d = {}
    for key, rx in (("ssid", r"SSID: (.+)"), ("freq", r"freq: ([\d.]+)"),
                    ("signal", r"signal: (-?\d+)"),
                    ("rx", r"rx bitrate: ([\d.]+) MBit/s(.*)"),
                    ("tx", r"tx bitrate: ([\d.]+) MBit/s(.*)")):
        m = re.search(rx, out)
        if m:
            d[key] = m.groups() if key in ("rx", "tx") else m.group(1).strip()
    info = run(["iw", "dev", iface, "info"])
    m = re.search(r"channel (\d+) \((\d+) MHz\), width: (\d+) MHz(?:, center1: (\d+))?", info)
    if m:
        d["chan"], d["width"] = int(m.group(1)), int(m.group(3))
        d["center"] = int(m.group(4) or m.group(2))
    try:
        d["signal"] = int(d["signal"])
        d["freq"] = float(d["freq"])
    except (KeyError, ValueError):
        pass
    return d


def wifi_neighbours(link):
    """Чужие сети, чей канал перекрывает наш: [(имя, сигнал %), …].

    Без пересканирования — список NetworkManager, который он и так держит.
    Соседская сеть считается 20-мегагерцевой; перекрытие — если её частота
    ближе к середине нашей полосы, чем половина нашей ширины плюс 10 МГц.
    """
    if not link or "center" not in link:
        return None
    out = run(["nmcli", "-t", "-f", "IN-USE,SSID,FREQ,SIGNAL", "dev", "wifi",
               "list", "--rescan", "no"], timeout=4)
    res = []
    for ln in out.splitlines():
        parts = re.split(r"(?<!\\):", ln)
        if len(parts) < 4 or parts[0] == "*":
            continue
        name = parts[1].replace("\\:", ":")
        if name == link.get("ssid"):
            continue
        try:
            f, sig = int(parts[2].split()[0]), int(parts[3])
        except ValueError:
            continue
        if abs(f - link["center"]) < link.get("width", 20) / 2 + 10:
            res.append((name or "скрытая", sig))
    return sorted(res, key=lambda x: -x[1])


def signal_word(dbm):
    """(слово, класс) для силы сигнала, дБм."""
    for lim, word, cls in ((-50, "отличный", "ok"), (-60, "хороший", "ok"),
                           (-67, "нормальный", None), (-75, "слабый", "warn")):
        if dbm >= lim:
            return word, cls
    return "очень слабый", "bad"


def wifi_gen(mods):
    """Поколение Wi-Fi по строке скорости iw."""
    for key, gen in (("EHT", "Wi-Fi 7"), ("HE", "Wi-Fi 6"), ("VHT", "Wi-Fi 5"),
                     ("MCS", "Wi-Fi 4")):
        if key in mods:
            return gen
    return ""


# ── «другие» в сети: счётчики роутера минус свои ──────────────────────────
# 07.10.2026: пользователь хотел видеть, что интернет тормозит из-за соседа по
# квартире, а не из-за роутера или провайдера. Роутер (TP-Link EC225-G5) по
# UPnP отдаёт общие счётчики байт своего WAN раз в секунду, ответ за 2 мс.
# Роутер минус этот ноутбук = все остальные устройства: сосед, телефоны, ТВ.
# Сверено: когда сеть больше никто не грузит, оба счётчика совпадают.
UPNP_CACHE = os.path.expanduser("~/.cache/jarvis-lan-upnp.json")
WANCFG = "urn:schemas-upnp-org:service:WANCommonInterfaceConfig:1"
OTHERS_AVG = 5          # вердикт — по среднему за столько секунд
OTHERS_BUSY = 0.5       # другие заняли полканала — тормозит у всех
OTHERS_BLAME = 0.25     # при задержках до интернета: виноваты другие


def upnp_find(gw):
    """Адрес управления WANCommonInterfaceConfig роутера или None.

    SSDP-поиск шлюза, затем его описание igd.xml. Кэш по адресу шлюза.
    """
    try:
        with open(UPNP_CACHE) as f:
            c = json.load(f)
        if c.get("gw") == gw and c.get("url"):
            return c["url"]
    except (OSError, ValueError):
        pass
    loc = None
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(2)
    try:
        for st in ("urn:schemas-upnp-org:device:InternetGatewayDevice:1",
                   "urn:schemas-upnp-org:device:InternetGatewayDevice:2"):
            msg = ("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n"
                   'MAN: "ssdp:discover"\r\nMX: 1\r\nST: %s\r\n\r\n' % st)
            s.sendto(msg.encode(), ("239.255.255.250", 1900))
            end = time.monotonic() + 2
            while time.monotonic() < end and not loc:
                try:
                    data, addr = s.recvfrom(4096)
                except socket.timeout:
                    break
                if addr[0] != gw:
                    continue
                m = re.search(r"(?im)^location:\s*(\S+)", data.decode(errors="replace"))
                loc = m and m.group(1)
            if loc:
                break
    except OSError:
        return None
    finally:
        s.close()
    if not loc:
        return None
    try:
        with urllib.request.urlopen(loc, timeout=3) as r:
            xml = r.read().decode(errors="replace")
    except Exception:
        return None
    for svc in re.findall(r"<service>(.*?)</service>", xml, re.S):
        if "WANCommonInterfaceConfig" in svc:
            m = re.search(r"<controlURL>\s*([^<\s]+)", svc)
            if m:
                url = urllib.parse.urljoin(loc, m.group(1))
                try:
                    os.makedirs(os.path.dirname(UPNP_CACHE), exist_ok=True)
                    with open(UPNP_CACHE, "w") as f:
                        json.dump({"gw": gw, "url": url}, f)
                except OSError:
                    pass
                return url
    return None


def upnp_bytes(url):
    """(принято, отправлено) байт через WAN роутера — 32-битные счётчики."""
    out = []
    for act, tag in (("GetTotalBytesReceived", "NewTotalBytesReceived"),
                     ("GetTotalBytesSent", "NewTotalBytesSent")):
        body = ('<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/'
                'soap/envelope/" s:encodingStyle="http://schemas.xmlsoap.org/soap/'
                'encoding/"><s:Body><u:%s xmlns:u="%s"/></s:Body></s:Envelope>' % (act, WANCFG))
        req = urllib.request.Request(url, body.encode(), {
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"%s#%s"' % (WANCFG, act)})
        with urllib.request.urlopen(req, timeout=2) as r:
            m = re.search(r"<%s>(\d+)<" % tag, r.read().decode(errors="replace"))
        if not m:
            raise ValueError(act)
        out.append(int(m.group(1)))
    return out


ROUTER_HELPER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "router_clients.py")
ROUTER_PASS = os.path.expanduser("~/.config/hypr/state/router-pass")
OTHER_NAME_SHARE = 0.75     # одно устройство — столько от чужого трафика → пишем его имя
OTHER_NAME_MIN = 200e3      # бит/с: тише — не называем никого
RADIO = {"0": "кабель", "1": "2,4 ГГц", "2": "гость 2,4", "3": "5 ГГц", "4": "гость 5"}


def own_macs():
    """MAC-адреса всех сетевых карт ноутбука, в виде роутера: aa-bb-…"""
    out = set()
    for n in os.listdir("/sys/class/net"):
        try:
            with open("/sys/class/net/%s/address" % n) as f:
                out.add(f.read().strip().replace(":", "-").lower())
        except OSError:
            pass
    return out


def own_bytes():
    """(принято, отправлено) байт всеми физическими картами ноутбука —
    кабель и Wi-Fi могут быть подключены к роутеру одновременно."""
    rx = tx = 0
    try:
        names = os.listdir("/sys/class/net")
    except OSError:
        names = []
    for n in names:
        if not os.path.exists(f"/sys/class/net/{n}/device"):
            continue
        try:
            rx += int(sysfs(n, "statistics/rx_bytes") or 0)
            tx += int(sysfs(n, "statistics/tx_bytes") or 0)
        except ValueError:
            pass
    return rx, tx


# ── замер скорости ────────────────────────────────────────────────────────
class _Count:
    def __init__(self):
        self.n = 0
        self.lock = threading.Lock()

    def add(self, k):
        with self.lock:
            self.n += k


def _conn():
    return http.client.HTTPSConnection(ST_HOST, timeout=10)


def st_ping(n=6):
    """Пинг до сервера замера, мс: медиана времени TCP-соединения (SYN —
    SYN-ACK). Пустые HTTP-запросы давали 33 мс при 3 мс настоящего пинга —
    в них сидит обработка на сервере."""
    addr = socket.getaddrinfo(ST_HOST, 443, proto=socket.IPPROTO_TCP)[0][4]
    times = []
    for _ in range(n):
        t = time.monotonic()
        with socket.create_connection(addr[:2], timeout=3):
            times.append((time.monotonic() - t) * 1000)
    return statistics.median(times)


def _down_worker(stop, cnt):
    c = _conn()
    try:
        while not stop.is_set():
            c.request("GET", "/__down?bytes=25000000", headers=ST_HDR)
            r = c.getresponse()
            while not stop.is_set():
                b = r.read(65536)
                if not b:
                    break
                cnt.add(len(b))
    finally:
        c.close()


def _up_worker(stop, cnt):
    chunk = os.urandom(65536)          # случайные байты — не сожмутся по дороге
    body = 128 * len(chunk)            # 8 МБ на запрос
    c = _conn()
    try:
        while not stop.is_set():
            c.putrequest("POST", "/__up")
            c.putheader("Content-Type", "application/octet-stream")
            c.putheader("Content-Length", str(body))
            c.putheader("User-Agent", ST_HDR["User-Agent"])
            c.endheaders()
            sent = 0
            while sent < body and not stop.is_set():
                c.send(chunk)
                sent += len(chunk)
                cnt.add(len(chunk))
            if sent < body:
                break
            c.getresponse().read()
    finally:
        c.close()


def st_phase(worker, spec, on_tick):
    """Несколько потоков качают, пока не выйдет время или объём.
    Скорость — по байтам после разгона (ST_WARM). Возвращает бит/с."""
    max_s, n, cap = spec
    stop, cnt, errs = threading.Event(), _Count(), []

    def safe():
        try:
            worker(stop, cnt)
        except Exception as e:  # обрыв одного потока — не повод бросать замер
            errs.append(e)
    ths = [threading.Thread(target=safe, daemon=True) for _ in range(n)]
    t0 = time.monotonic()
    for t in ths:
        t.start()
    mark, rate = None, 0.0
    while True:
        time.sleep(0.25)
        el, b = time.monotonic() - t0, cnt.n
        if mark is None and el >= ST_WARM:
            mark = (el, b)
        if mark and el > mark[0] + 0.2:
            rate = (b - mark[1]) * 8 / (el - mark[0])
        else:
            rate = b * 8 / el
        on_tick(min(el / max_s, 1.0), rate)
        if el >= max_s or b >= cap or not any(t.is_alive() for t in ths):
            break
    stop.set()
    if cnt.n == 0:
        raise RuntimeError(str(errs[0]) if errs else "нет данных")
    return rate


def load_history():
    try:
        with open(SPEED_FILE) as f:
            h = json.load(f)
        return h if isinstance(h, list) else []
    except (OSError, ValueError):
        return []


def save_history(h):
    try:
        os.makedirs(os.path.dirname(SPEED_FILE), exist_ok=True)
        with open(SPEED_FILE + ".tmp", "w") as f:
            json.dump(h[-SPEED_KEEP:], f, ensure_ascii=False, indent=1)
        os.replace(SPEED_FILE + ".tmp", SPEED_FILE)
    except OSError:
        pass


# ── плашка ────────────────────────────────────────────────────────────────
def _rgb(hexcolor):
    h = hexcolor.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


class LanPopup(Gtk.Window):
    def __init__(self):
        super().__init__(title="Сеть")
        self.pal = popup_theme.palette()
        self.iface, self.gw = None, None
        self.wireless = False
        self.pings = {"gw": collections.deque(maxlen=PING_WIN),
                      "net": collections.deque(maxlen=PING_WIN)}
        self.dns_ms, self.dns_done = None, False
        self.pinging = self.dns_busy = self.speed_busy = False
        # Замер скорости сам забивает канал, и пинг на это время растёт.
        # Такие пинги в статистику не берём — иначе вывод винил провайдера
        # (08.10.2026, снимок пользователя: 73 мс во время отдачи 94 Мбит/с).
        self.ping_quiet = 0.0     # monotonic: до этого момента пинги не считаем
        self.rx = collections.deque([0.0] * GRAPH_SEC, maxlen=GRAPH_SEC)
        self.tx = collections.deque([0.0] * GRAPH_SEC, maxlen=GRAPH_SEC)
        self.prev = None          # (время, rx_bytes, tx_bytes)
        # Другие устройства: со знаком (среднее не смещается от обрезки
        # шума в ноль), рисуем и пишем — обрезанным.
        self.orx = collections.deque([0.0] * GRAPH_SEC, maxlen=GRAPH_SEC)
        self.otx = collections.deque([0.0] * GRAPH_SEC, maxlen=GRAPH_SEC)
        self.others_ok = None     # None — ещё не знаем, False — роутер не отдаёт
        self.st_others = None     # во время замера скорости: [(rx, tx), …]
        self.chain = ["wait"] * 4
        # Пока маршрут не прочитан, судить не о чем: 08.10.2026 DNS отвечал
        # раньше и на секунду мигало «DHCP не ответил».
        self.info_done = False
        self.wifi = None          # плашка Wi-Fi: данные iw link
        self.view = None          # плашка Wi-Fi: "wifi" | "cable" | "off" | "none"
        self.cap = self.capacity()

        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.TOP)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.EXCLUSIVE)

        provider = Gtk.CssProvider()
        provider.load_from_data(popup_theme.css(EXTRA_CSS, ok=OK_COLOR, warn=WARN_COLOR))
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.bg = Gtk.EventBox()
        self.bg.connect("button-press-event", lambda w, e: sys.exit(0))
        self.add(self.bg)

        self.align = Gtk.Box()
        self.bg.add(self.align)
        # Прямо под баром, серединой под точкой щелчка — см. popup_theme.
        popup_theme.place_under_cursor(self.align)

        self.popup_event = Gtk.EventBox()
        self.popup_event.connect("button-press-event", lambda w, e: True)
        self.align.add(self.popup_event)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.get_style_context().add_class("popup-box")
        vbox.set_size_request(WIDTH, -1)
        self.popup_event.add(vbox)

        # ── шапка ──
        head = Gtk.Box(spacing=8)
        head.pack_start(self.label("󰤨  Wi-Fi" if WIFI else "󰈀  Сеть", "title"),
                        False, False, 0)
        self.iface_lbl = self.label("", "dim", xalign=1)
        head.pack_end(self.iface_lbl, False, False, 0)
        vbox.pack_start(head, False, False, 0)

        # Плашка Wi-Fi, когда интернет идёт не через неё: одна понятная
        # фраза вместо всей статистики (08.10.2026).
        self.note = self.label("", xalign=0.5)
        self.note.set_line_wrap(True)
        self.note.set_max_width_chars(34)
        self.note.set_justify(Gtk.Justification.CENTER)
        self.note.set_no_show_all(True)
        vbox.pack_start(self.note, False, False, 6)
        self.body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        self.body.set_no_show_all(WIFI)   # покажем, когда узнаем, куда идёт сеть
        vbox.pack_start(self.body, False, False, 0)
        vbox = self.body

        # ── цепочка: кабель → роутер → интернет → DNS ──
        self.chain_da = Gtk.DrawingArea()
        self.chain_da.set_size_request(-1, 18)
        self.chain_da.connect("draw", self.draw_chain)
        vbox.pack_start(self.chain_da, False, False, 4)
        names = Gtk.Box(homogeneous=True)
        vals = Gtk.Box(homogeneous=True)
        self.chain_names, self.chain_vals = [], []
        for n in ("Кабель", "Роутер", "Интернет", "DNS"):
            a = self.label(n, xalign=0.5)
            b = self.label("…", "dim", xalign=0.5)
            # Колонки равной ширины: длинное значение не должно раздвигать окно.
            b.set_ellipsize(Pango.EllipsizeMode.END)
            names.pack_start(a, True, True, 0)
            vals.pack_start(b, True, True, 0)
            self.chain_names.append(a)
            self.chain_vals.append(b)
        vbox.pack_start(names, False, False, 0)
        vbox.pack_start(vals, False, False, 0)
        self.verdict = self.label("Проверяю…", xalign=0.5)
        self.verdict.set_line_wrap(True)
        # Переносимая строка иначе просит ширину под весь текст и раздувает окно.
        self.verdict.set_max_width_chars(28)     # 16 px: 12 px на знак
        self.verdict.get_style_context().add_class("verdict")
        self.verdict.set_justify(Gtk.Justification.CENTER)
        vbox.pack_start(self.verdict, False, False, 6)

        # ── подключение ──
        vbox.pack_start(Gtk.Separator(), False, False, 0)
        grid = Gtk.Grid(column_spacing=14, row_spacing=4)
        self.info = {}
        rows = ((("ssid", "Сеть"), ("signal", "Сигнал"), ("band", "Диапазон"),
                 ("rate", "Связь"), ("air", "Соседи"), ("addr", "Адрес"),
                 ("gw", "Шлюз"), ("ext", "Внешний IP"), ("isp", "Провайдер"))
                if WIFI else
                (("link", "Канал"), ("addr", "Адрес"), ("gw", "Шлюз"), ("dns", "DNS"),
                 ("ext", "Внешний IP"), ("isp", "Провайдер"), ("geo", "Где")))
        tips = {"signal": "Сила сигнала у ноутбука, дБм: ближе к нулю — лучше.\n"
                          "−50 и выше отлично, до −67 нормально, ниже −75 плохо.",
                "rate": "Скорость связи с роутером по воздуху.\n"
                        "Настоящая скорость интернета примерно вдвое ниже.",
                "air": "Чужие сети на том же канале: они делят с вами эфир.\n"
                       "Процент — сила их сигнала у вас.",
                "band": "5 ГГц быстрее и чище, 2.4 ГГц дальше бьёт сквозь стены."}
        for i, (key, title) in enumerate(rows):
            t = self.label(title, "dim")
            t.set_tooltip_text(tips.get(key) if WIFI else None)
            grid.attach(t, 0, i, 1, 1)
            v = self.label("…")
            v.set_hexpand(True)
            v.set_ellipsize(Pango.EllipsizeMode.END)
            grid.attach(v, 1, i, 1, 1)
            self.info[key] = v
        vbox.pack_start(grid, False, False, 0)
        self.info.setdefault("dns", Gtk.Label())   # в плашке Wi-Fi строк нет —
        self.info.setdefault("geo", Gtk.Label())   # пишем в невидимые
        self.info.setdefault("link", Gtk.Label())

        # ── трафик ──
        vbox.pack_start(Gtk.Separator(), False, False, 0)
        th = Gtk.Box(spacing=10)
        th.pack_start(self.label("Трафик", "sec"), False, False, 0)
        self.up_lbl = self.label("↑ —", "up", xalign=1)
        self.down_lbl = self.label("↓ —", "down", xalign=1)
        self.up_lbl.set_width_chars(13)
        self.down_lbl.set_width_chars(13)
        th.pack_end(self.up_lbl, False, False, 0)
        th.pack_end(self.down_lbl, False, False, 0)
        vbox.pack_start(th, False, False, 0)
        # Строка «Другие» — всё, что идёт через роутер не с этого ноутбука.
        self.oth_row = Gtk.Box(spacing=10)
        self.oth_row.set_no_show_all(True)
        self.oth_row.set_tooltip_text(
            "Все остальные устройства на роутере: сосед, телефоны, ТВ.\n"
            "Счётчики роутера (UPnP) минус трафик этого ноутбука.")
        self.oth_name = self.label("Другие", "oth")
        self.oth_name.set_max_width_chars(11)
        self.oth_name.set_ellipsize(Pango.EllipsizeMode.END)
        self.oth_row.pack_start(self.oth_name, False, False, 0)
        self.oth_up = self.label("↑ —", "up", xalign=1)
        self.oth_down = self.label("↓ —", "oth", xalign=1)
        self.oth_up.set_width_chars(13)
        self.oth_down.set_width_chars(13)
        self.oth_row.pack_end(self.oth_up, False, False, 0)
        self.oth_row.pack_end(self.oth_down, False, False, 0)
        for w in self.oth_row.get_children():
            w.show()
        vbox.pack_start(self.oth_row, False, False, 0)
        self.graph = Gtk.DrawingArea()
        self.graph.set_size_request(-1, 80)
        self.graph.connect("draw", self.draw_graph)
        self.graph.set_tooltip_text("Трафик за последние %d с. Сплошные линии — этот ноутбук («система»: ↓ загрузка, ↑ отдача), пунктир — другие устройства на роутере." % GRAPH_SEC)
        vbox.pack_start(self.graph, False, False, 2)

        # ── пинг ──
        vbox.pack_start(Gtk.Separator(), False, False, 0)
        pg = Gtk.Grid(column_spacing=10, row_spacing=4)
        pg.attach(self.label("Пинг", "sec"), 0, 0, 1, 1)
        for c, t in enumerate(("среднее", "разброс", "потери"), 1):
            lb = self.label(t, "dim", xalign=1)
            lb.set_hexpand(True)
            pg.attach(lb, c, 0, 1, 1)
        self.ping_cells = {}
        for r, (key, title) in enumerate((("gw", "Роутер"), ("net", "Интернет")), 1):
            pg.attach(self.label(title), 0, r, 1, 1)
            cells = []
            for c in range(1, 4):
                lb = self.label("…", xalign=1)
                pg.attach(lb, c, r, 1, 1)
                cells.append(lb)
            self.ping_cells[key] = cells
        vbox.pack_start(pg, False, False, 0)

        # ── замер скорости ──
        vbox.pack_start(Gtk.Separator(), False, False, 0)
        self.speed_btn = Gtk.Button(label="Проверить скорость")
        self.speed_btn.get_style_context().add_class("go")
        self.speed_btn.connect("clicked", self.start_speedtest)
        vbox.pack_start(self.speed_btn, False, False, 0)
        self.progress = Gtk.ProgressBar()
        self.progress.set_no_show_all(True)
        vbox.pack_start(self.progress, False, False, 2)
        self.speed_msg = self.label("", "dim", xalign=0.5)
        self.speed_msg.set_no_show_all(True)
        self.speed_msg.set_line_wrap(True)
        self.speed_msg.set_max_width_chars(34)
        vbox.pack_start(self.speed_msg, False, False, 0)
        self.hist_grid = Gtk.Grid(column_spacing=10, row_spacing=4)
        vbox.pack_start(self.hist_grid, False, False, 2)
        self.fill_history()

        # ── простой вид: перекладываем блоки, подробности — в раскрывашку ──
        for w in vbox.get_children():
            vbox.remove(w)

        def sep(box):
            box.pack_start(Gtk.Separator(), False, False, 0)
        for w, pad in ((self.chain_da, 2), (names, 0), (vals, 0), (self.verdict, 3)):
            vbox.pack_start(w, False, False, pad)
        sep(vbox)
        vbox.pack_start(th, False, False, 0)
        vbox.pack_start(self.oth_row, False, False, 0)
        sep(vbox)
        for w, pad in ((self.speed_btn, 0), (self.progress, 2), (self.speed_msg, 0)):
            vbox.pack_start(w, False, False, pad)
        self.more_btn = Gtk.Button()
        self.more_btn.get_style_context().add_class("more")
        self.more_btn.connect("clicked", lambda *_a: self.set_details(not self.details_on))
        vbox.pack_start(self.more_btn, False, False, 0)
        self.details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        for w, pad in ((self.graph, 2), (None, 0), (pg, 0), (None, 0), (grid, 0),
                       (None, 0), (self.hist_grid, 2)):
            if w is None:
                sep(self.details)
            else:
                self.details.pack_start(w, False, False, pad)
        vbox.pack_start(self.details, False, False, 0)
        try:
            with open(DETAILS_FILE) as f:
                on = f.read().strip() == "on"
        except OSError:
            on = False
        self.set_details(on, save=False)

        self.connect("key-press-event", self.on_key)

        # Первые данные — сразу, дальше по таймерам. Таймеры живут, пока жив
        # процесс плашки.
        self.refresh_info()
        self.tick()
        self.ping_round()
        self.dns_round()
        GLib.timeout_add(TICK_MS, self.tick)
        GLib.timeout_add(PING_MS, self.ping_round)
        GLib.timeout_add(DNS_MS, self.dns_round)
        GLib.timeout_add(INFO_MS, self.refresh_info)
        if WIFI:
            GLib.timeout_add(WIFI_MS, self.wifi_round)
        threading.Thread(target=self.others_loop, daemon=True).start()
        # Кто именно из других качает — из админки роутера (08.10.2026).
        self.router, self.router_why = None, None
        threading.Thread(target=self.router_loop, daemon=True).start()

    def set_details(self, on, save=True):
        self.details_on = on
        self.more_btn.set_label("Скрыть подробности ▴" if on else "Подробнее ▾")
        # no_show_all: show_all() у тела (плашка Wi-Fi) не раскроет свёрнутое.
        self.details.set_no_show_all(not on)
        if on:
            self.details.show_all()
        else:
            self.details.hide()
        if save:
            try:
                os.makedirs(os.path.dirname(DETAILS_FILE), exist_ok=True)
                with open(DETAILS_FILE, "w") as f:
                    f.write("on" if on else "off")
            except OSError:
                pass

    def label(self, text, cls=None, xalign=0):
        lb = Gtk.Label(label=text, xalign=xalign)
        if cls:
            lb.get_style_context().add_class(cls)
        return lb

    @staticmethod
    def set_cls(lb, cls):
        ctx = lb.get_style_context()
        for c in ("ok", "warn", "bad", "dim"):
            if c != cls and ctx.has_class(c):
                ctx.remove_class(c)
        if cls and not ctx.has_class(cls):
            ctx.add_class(cls)

    def on_key(self, _w, event):
        if event.keyval == Gdk.KEY_Escape:
            sys.exit(0)
        return False

    # ── сведения о подключении ────────────────────────────────────────────
    def refresh_info(self):
        def work():
            iface, gw = default_route()
            if WIFI:
                # Своя карта — всегда Wi-Fi; шлюз — только если маршрут
                # по умолчанию идёт через неё (кабель в приоритете).
                wif = wireless_iface()
                link = wifi_link(wif) if wif else None
                data = {"iface": wif, "gw": gw if iface == wif else None,
                        "route": iface, "link": link,
                        "radio": wifi_radio_on() if wif and not link else True,
                        "air": wifi_neighbours(link)}
                if wif:
                    data["addr"] = local_addr(wif)
                GLib.idle_add(self.apply_info, data)
                if data["gw"]:
                    GLib.idle_add(self.apply_ext, ext_info(gw))
                return
            iface = iface or wired_iface()
            data = {"iface": iface, "gw": gw}
            if iface:
                data["addr"] = local_addr(iface)
                data["dns"] = dns_servers(iface)
            GLib.idle_add(self.apply_info, data)
            if gw:
                GLib.idle_add(self.apply_ext, ext_info(gw))
            else:
                GLib.idle_add(self.apply_ext, None)
        threading.Thread(target=work, daemon=True).start()
        return True

    def apply_info(self, d):
        if d["iface"] != self.iface:
            self.prev = None          # другой интерфейс — счётчики байт другие
        self.iface, self.gw = d["iface"], d["gw"]
        self.info_done = True
        if WIFI:
            self.apply_wifi(d)
        self.wireless = bool(self.iface) and os.path.exists(
            f"/sys/class/net/{self.iface}/wireless")
        self.chain_names[0].set_text("Wi-Fi" if self.wireless else "Кабель")
        self.iface_lbl.set_text(self.iface or "нет интерфейса")
        self.info["addr"].set_text(d.get("addr") or "нет адреса")
        self.info["gw"].set_text(self.gw or "нет маршрута")
        self.info["dns"].set_text(", ".join(d.get("dns") or []) or "—")
        self.update_link()
        self.judge()
        return False

    def apply_ext(self, e):
        if not e:
            for k in ("ext", "isp", "geo"):
                self.info[k].set_text("нет ответа" if self.gw else "—")
            return False
        self.info["ext"].set_text(e.get("query") or "—")
        self.info["isp"].set_text(e.get("isp") or e.get("org") or "—")
        self.info["isp"].set_tooltip_text(e.get("org") or None)
        geo = ", ".join(x for x in (e.get("city"), e.get("country")) if x)
        self.info["geo"].set_text(geo or "—")
        return False

    def update_link(self):
        """Кабель: есть ли линк, и на какой скорости он поднялся."""
        if not self.iface:
            self.chain[0] = "bad"
            self.chain_vals[0].set_text("нет")
            self.info["link"].set_text("—")
            return
        carrier = sysfs(self.iface, "carrier") == "1"
        oper = sysfs(self.iface, "operstate")
        try:
            speed = int(sysfs(self.iface, "speed") or -1)
        except ValueError:
            speed = -1
        duplex = {"full": "дуплекс", "half": "полудуплекс"}.get(
            sysfs(self.iface, "duplex") or "", "")
        up = carrier and oper in ("up", "unknown")
        if WIFI:
            sig = (self.wifi or {}).get("signal")
            if not self.wifi or not isinstance(sig, int):
                self.chain[0] = "bad" if not self.wifi else "ok"
                self.chain_vals[0].set_text("нет связи" if not self.wifi else "есть")
                return
            self.chain[0] = "warn" if sig < -75 else "ok"
            self.chain_vals[0].set_text("%d дБм" % sig)
            return
        if not up:
            self.chain[0] = "bad"
            self.chain_vals[0].set_text("нет линка")
            self.info["link"].set_text("нет линка")
        else:
            # Полудуплекс или 10/100 на гигабитной карте — кабель или порт
            # не тянут: связь есть, но это повод присмотреться.
            slow = (not self.wireless and 0 < speed < 1000) or duplex == "полудуплекс"
            self.chain[0] = "warn" if slow else "ok"
            self.chain_vals[0].set_text(fmt_link(speed) if speed > 0 else "есть")
            parts = [fmt_link(speed)] if speed > 0 else []
            if duplex:
                parts.append(duplex)
            self.info["link"].set_text(" · ".join(parts) or "есть")

    # ── трафик ────────────────────────────────────────────────────────────
    def tick(self):
        if self.iface:
            rx, tx = sysfs(self.iface, "statistics/rx_bytes"), sysfs(self.iface, "statistics/tx_bytes")
            now = time.monotonic()
            if rx and tx:
                rx, tx = int(rx), int(tx)
                if self.prev:
                    dt = max(now - self.prev[0], 0.001)
                    self.rx.append(max(rx - self.prev[1], 0) * 8 / dt)
                    self.tx.append(max(tx - self.prev[2], 0) * 8 / dt)
                    self.down_lbl.set_text("↓ " + fmt_rate(self.rx[-1]))
                    self.up_lbl.set_text("↑ " + fmt_rate(self.tx[-1]))
                self.prev = (now, rx, tx)
            self.update_link()
            self.judge()
        self.graph.queue_draw()
        return True

    def wifi_round(self):
        """Сигнал и скорость связи — чаще, чем остальные сведения."""
        iface = self.iface
        if not iface or self.view != "wifi":
            return True

        def work():
            link = wifi_link(iface)
            GLib.idle_add(self.apply_link, link)
        threading.Thread(target=work, daemon=True).start()
        return True

    def apply_wifi(self, d):
        """Что показать: статистику или одну фразу."""
        link, route = d.get("link"), d.get("route")
        if not d["iface"]:
            view, note = "none", "На этом ноутбуке не найден Wi-Fi адаптер"
        elif not d.get("radio"):
            view, note = "off", "Wi-Fi выключен.\n\nВключить — левой кнопкой по значку Wi-Fi."
        elif route and route != d["iface"]:
            view = "cable"
            note = ("Весь интернет идёт через кабель.\n\n" +
                    ("Wi-Fi «%s» подключён про запас: выдернете кабель — "
                     "сеть сама перейдёт на него." % link.get("ssid", "?") if link else
                     "Wi-Fi ни к чему не подключён.") +
                    "\n\nПодробности — щелчок по «lan».")
        elif not link:
            view, note = "none", ("Wi-Fi включён, но ни к одной сети не подключён.\n\n"
                                  "Список сетей — левой кнопкой по значку Wi-Fi.")
        else:
            view, note = "wifi", ""
        if view != self.view:
            self.view = view
            self.note.set_text(note)
            self.note.set_visible(view != "wifi")
            self.body.set_no_show_all(False)
            if view == "wifi":
                self.body.show_all()
                self.oth_row.set_visible(bool(self.others_ok))
                self.progress.set_visible(self.speed_busy)
                self.speed_msg.set_visible(bool(self.speed_msg.get_text()))
            else:
                self.body.hide()
        elif view != "wifi":
            self.note.set_text(note)
        self.air = d.get("air")
        self.apply_link(link)

    def crowded(self):
        air = getattr(self, "air", None) or []
        return len([1 for _n, s in air if s >= 50]) >= 2 or len(air) >= 5

    def apply_link(self, link):
        self.wifi = link
        if not WIFI or not link:
            return False
        i = self.info
        i["ssid"].set_text(link.get("ssid", "—"))
        sig = link.get("signal")
        if isinstance(sig, int):
            word, cls = signal_word(sig)
            i["signal"].set_text("%d дБм · %s" % (sig, word))
            self.set_cls(i["signal"], cls if cls != "ok" else None)
        f = link.get("freq") or 0
        band = "6 ГГц" if f > 5925 else "5 ГГц" if f > 4900 else "2.4 ГГц"
        parts = [band]
        if "chan" in link:
            parts.append("канал %d" % link["chan"])
        i["band"].set_text(" · ".join(parts))
        # Ширина полосы — в подсказке: в строку при ширине 344 не влезает.
        i["band"].set_tooltip_text("Ширина полосы %d МГц" % link["width"]
                                   if "width" in link else None)
        rx, tx = link.get("rx"), link.get("tx")
        if rx:
            rate = "%.0f" % float(rx[0])
            if tx and abs(float(tx[0]) - float(rx[0])) >= 1:
                rate = "↓%.0f ↑%.0f" % (float(rx[0]), float(tx[0]))
            gen = wifi_gen(rx[1])
            i["rate"].set_text(rate + " Мбит/с" + (" · " + gen if gen else ""))
        air = getattr(self, "air", None)
        if air is None:
            i["air"].set_text("—")
        elif not air:
            i["air"].set_text("никого")
            self.set_cls(i["air"], None)
        else:
            strong = [n for n, s in air if s >= 50]
            n = len(air)
            word = "сеть" if n % 10 == 1 and n % 100 != 11 else \
                   "сети" if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14 else "сетей"
            i["air"].set_text("%d %s%s" % (
                n, word, ", %d сильн." % len(strong) if strong else ", слабые"))
            i["air"].set_tooltip_text("\n".join("%s — %d%%" % a for a in air))
            self.set_cls(i["air"], "warn" if self.crowded() else None)
        self.update_link()
        return False

    def others_loop(self):
        """Поток: раз в секунду счётчики роутера и свои, разница — другие."""
        url, prev, fails = None, None, 0
        while True:
            if not url:
                gw = self.gw
                url = upnp_find(gw) if gw else None
                if not url:
                    if gw:
                        GLib.idle_add(self.apply_others, None)
                    time.sleep(1 if not gw else 30)
                    continue
            try:
                wr, wt = upnp_bytes(url)
                orx, otx = own_bytes()
                now = time.monotonic()
                fails = 0
            except Exception:
                fails += 1
                prev = None
                if fails >= 3:
                    GLib.idle_add(self.apply_others, None)
                    url = None    # сменился роутер или отключили UPnP
                    try:
                        os.remove(UPNP_CACHE)
                    except OSError:
                        pass
                time.sleep(1)
                continue
            if prev:
                dt = max(now - prev[0], 0.001)
                # Счётчики роутера 32-битные — переполняются раз в 4 ГиБ.
                drx = (wr - prev[1]) % 2 ** 32 - (orx - prev[3])
                dtx = (wt - prev[2]) % 2 ** 32 - (otx - prev[4])
                # Больше гигабайта за секунду — роутер перезагрузился.
                if max(abs(drx), abs(dtx)) < 1e9:
                    GLib.idle_add(self.apply_others, (drx * 8 / dt, dtx * 8 / dt))
            prev = (now, wr, wt, orx, otx)
            time.sleep(TICK_MS / 1000)

    def router_loop(self):
        """Поток: помощник router_clients.py входит в админку роутера и раз в
        3 с печатает устройства со скоростями. Живёт, пока жива плашка
        (PDEATHSIG), при выходе сам выходит из админки."""
        if not os.path.exists(ROUTER_PASS) or not os.access(ROUTER_HELPER, os.X_OK):
            return
        import ctypes
        import signal

        def pdeath():
            ctypes.CDLL("libc.so.6").prctl(1, signal.SIGTERM)   # PR_SET_PDEATHSIG
        try:
            p = subprocess.Popen([ROUTER_HELPER], stdout=subprocess.PIPE,
                                 stderr=subprocess.DEVNULL, text=True, preexec_fn=pdeath)
        except OSError:
            return
        for line in p.stdout:
            try:
                d = json.loads(line)
            except ValueError:
                continue
            GLib.idle_add(self.apply_router, d)

    def apply_router(self, d):
        if not d.get("ok"):
            self.router, self.router_why = None, d.get("why")
        else:
            own = own_macs()
            devs = [x for x in d["devs"] if x["mac"] not in own]
            self.router = {"t": time.monotonic(), "devs": devs}
        self.show_router()
        return False

    def top_other(self):
        """Имя устройства, которое занимает почти весь чужой трафик, или None."""
        r = self.router
        if not r or time.monotonic() - r["t"] > 10:
            return None
        rate = [(x["down"] + x["up"], x) for x in r["devs"]]
        total = sum(v for v, _ in rate)
        if total * 8 < OTHER_NAME_MIN:
            return None
        v, top = max(rate, key=lambda t: t[0])
        return top["name"] if v >= OTHER_NAME_SHARE * total else None

    def show_router(self):
        name = self.top_other()
        self.oth_name.set_text(name or "Другие")
        tip = ("Все остальные устройства на роутере: сосед, телефоны, ТВ.\n"
               "Счётчики роутера (UPnP) минус трафик этого ноутбука.")
        r = self.router
        if r:
            busy = sorted((x for x in r["devs"] if x["down"] + x["up"] > 0),
                          key=lambda x: -(x["down"] + x["up"]))
            lines = ["%s (%s)  ↓ %s  ↑ %s" % (x["name"], RADIO.get(x["type"], "?"),
                                              fmt_rate(x["down"] * 8), fmt_rate(x["up"] * 8))
                     for x in busy[:8]]
            tip += "\n\nПо админке роутера, сейчас:\n" + ("\n".join(lines) or "никто не качает")
            if name:
                tip += "\n\nВместо «Другие» — имя, если одно устройство даёт ≥ %d %% чужого трафика." \
                    % round(OTHER_NAME_SHARE * 100)
        elif self.router_why:
            tip += "\n\nАдминка роутера: %s." % self.router_why
        if self.oth_row.get_tooltip_text() != tip:
            self.oth_row.set_tooltip_text(tip)

    def apply_others(self, v):
        if v is None:
            self.others_ok = False
            self.oth_row.hide()
            return False
        self.others_ok = True
        self.oth_row.show()
        self.orx.append(v[0])
        self.otx.append(v[1])
        if self.st_others is not None:
            self.st_others.append(v)
        self.oth_down.set_text("↓ " + fmt_rate(max(v[0], 0)))
        self.oth_up.set_text("↑ " + fmt_rate(max(v[1], 0)))
        return False

    def others_load(self):
        """(↓, ↑) других за последние OTHERS_AVG с, бит/с, или None."""
        if not self.others_ok:
            return None
        n = OTHERS_AVG
        return (max(statistics.mean(list(self.orx)[-n:]), 0),
                max(statistics.mean(list(self.otx)[-n:]), 0))

    @staticmethod
    def capacity():
        """Тариф (↓, ↑), бит/с — по лучшему из последних замеров, иначе 100."""
        h = load_history()
        down = max([x.get("down", 0) for x in h] + [10]) if h else 100
        up = max([x.get("up", 0) for x in h] + [10]) if h else 100
        return down * 1e6, up * 1e6

    @staticmethod
    def nice_max(v):
        """Верх шкалы графика: 1, 2 или 5 × 10^n, не меньше 100 Кбит/с."""
        v = max(v, 1e5)
        p = 10 ** len(str(int(v))) / 10
        for m in (1, 2, 5, 10):
            if v <= m * p:
                return m * p
        return 10 * p

    def draw_graph(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        pal = self.pal
        # подложка
        r = 6
        cr.new_sub_path()
        cr.arc(W - r, r, r, -1.5708, 0)
        cr.arc(W - r, H - r, r, 0, 1.5708)
        cr.arc(r, H - r, r, 1.5708, 3.1416)
        cr.arc(r, r, r, 3.1416, 4.7124)
        cr.close_path()
        cr.set_source_rgb(*_rgb(pal["surface_container"]))
        cr.fill()
        orx = [max(v, 0) for v in self.orx] if self.others_ok else []
        top = self.nice_max(max(max(self.rx), max(self.tx), max(orx or [0])))
        pad = 4
        gh = H - 2 * pad
        # сетка: середина шкалы
        cr.set_source_rgba(*_rgb(pal["on_surface_variant"]), 0.18)
        cr.set_line_width(1)
        cr.move_to(pad, int(pad + gh / 2) + 0.5)
        cr.line_to(W - pad, int(pad + gh / 2) + 0.5)
        cr.stroke()
        step = (W - 2 * pad) / (GRAPH_SEC - 1)

        def series(vals, color, fill, dash=None):
            pts = [(pad + i * step, pad + gh - min(v / top, 1) * gh) for i, v in enumerate(vals)]
            rgb = _rgb(color)
            cr.move_to(pts[0][0], pad + gh)
            for x, y in pts:
                cr.line_to(x, y)
            cr.line_to(pts[-1][0], pad + gh)
            cr.close_path()
            cr.set_source_rgba(*rgb, fill)
            cr.fill()
            cr.move_to(*pts[0])
            for x, y in pts[1:]:
                cr.line_to(x, y)
            cr.set_source_rgba(*rgb, 1)
            cr.set_line_width(1.5)
            if dash:
                cr.set_dash(dash)
            cr.stroke()
            cr.set_dash([])
        if orx:
            # Другие — пунктиром: в палитре обоев secondary близок к primary.
            series(orx, pal["secondary"], 0.14, (4, 3))
        series(self.rx, pal["primary"], 0.22)
        series(self.tx, pal["tertiary"], 0.12)
        # подпись шкалы — тем же пиксельным шрифтом
        lay = w.create_pango_layout(fmt_rate(top).replace(".0 ", " "))
        cr.set_source_rgba(*_rgb(pal["on_surface_variant"]), 0.9)
        cr.move_to(pad + 4, pad + 2)
        PangoCairo.show_layout(cr, lay)
        scale_end = pad + 4 + lay.get_pixel_size()[0]
        # Подписи линий — справа сверху, «60 с» ушло в подсказку графика (Пользователь,
        # 08.10.2026: «а эти графики что означают?» — пунктир соседа не читался).
        # Не влезают рядом со шкалой — не рисуются (подсказка графика остаётся).
        # «система ↓↑» — стрелки цветом своих линий; «-- другие» — образец пунктира.
        # (Просьба: «а что за я?», потом «не ноут, а система».)
        segs = [("система ", pal["on_surface_variant"], None, 0), ("↓", pal["primary"], None, 0),
                ("↑", pal["tertiary"], None, 10)]
        if orx:
            segs.append(("другие", pal["secondary"], (3, 2), 0))
        sample = 10                      # образец пунктира перед «другие»
        lays = [(w.create_pango_layout(t), c, d, g) for t, c, d, g in segs]
        total = sum(l.get_pixel_size()[0] + g + (sample + 3 if d else 0) for l, _, d, g in lays)
        x = W - pad - 4 - total
        if x < scale_end + 12:
            lays = []
        for l, c, d, g in lays:
            th = l.get_pixel_size()[1]
            if d:
                cr.set_source_rgba(*_rgb(c), 1)
                cr.set_line_width(1.5)
                cr.set_dash(d)
                cr.move_to(x, pad + 2 + th / 2)
                cr.line_to(x + sample, pad + 2 + th / 2)
                cr.stroke()
                cr.set_dash([])
                x += sample + 3
            cr.set_source_rgba(*_rgb(c), 0.95)
            cr.move_to(x, pad + 2)
            PangoCairo.show_layout(cr, l)
            x += l.get_pixel_size()[0] + g
        return False

    # ── пинг и DNS ────────────────────────────────────────────────────────
    def ping_round(self):
        if self.pinging or not self.iface or (WIFI and self.view != "wifi"):
            return True
        self.pinging = True
        gw = self.gw

        def work():
            res = {}

            def one(key, host):
                res[key] = ping_once(host) if host else None
            ths = [threading.Thread(target=one, args=("gw", gw), daemon=True),
                   threading.Thread(target=one, args=("net", NET_HOST), daemon=True)]
            for t in ths:
                t.start()
            for t in ths:
                t.join(4)
            GLib.idle_add(self.apply_ping, res)
        threading.Thread(target=work, daemon=True).start()
        return True

    def apply_ping(self, res):
        self.pinging = False
        if self.speed_busy or time.monotonic() < self.ping_quiet:
            return False
        for key in ("gw", "net"):
            self.pings[key].append(res.get(key))
            avg, jit, loss = ping_stats(list(self.pings[key]))
            a, j, l = self.ping_cells[key]
            a.set_text(fmt_ms(avg))
            j.set_text("±" + fmt_ms(jit) if jit is not None else "—")
            l.set_text("%.0f%%" % loss)
            self.set_cls(l, "bad" if loss >= 20 else "warn" if loss > 0 else None)
        self.judge()
        return False

    def dns_round(self):
        if self.dns_busy:
            return True
        self.dns_busy = True
        name = DNS_NAMES[int(time.time() / 10) % len(DNS_NAMES)]

        def work():
            ms = dns_probe(name)
            GLib.idle_add(self.apply_dns, ms)
        threading.Thread(target=work, daemon=True).start()
        return True

    def apply_dns(self, ms):
        self.dns_busy = False
        self.dns_ms, self.dns_done = ms, True
        self.judge()
        return False

    # ── вердикт ───────────────────────────────────────────────────────────
    def link_state(self, key, warn_ms):
        """Состояние звена по последним пингам: wait/ok/warn/bad."""
        s = list(self.pings[key])
        if not s:
            return "wait"
        if all(v is None for v in s[-3:]):
            return "bad"
        recent = s[-10:]
        ok = [v for v in recent if v is not None]
        if len(ok) < len(recent) or statistics.mean(ok) > warn_ms:
            return "warn"
        return "ok"

    def judge(self):
        if not self.info_done:
            return
        ch, vals = self.chain, self.chain_vals
        gw_s = self.link_state("gw", 30) if self.gw else "bad"
        net_s = self.link_state("net", 100)
        if not self.dns_done:
            dns_s = "wait"
        elif self.dns_ms is None:
            dns_s = "bad"
        else:
            dns_s = "warn" if self.dns_ms > 300 else "ok"
        # Роутер может просто не отвечать на ping, а интернет через него идёт:
        # тогда это не обрыв, а особенность роутера — жёлтый, не красный.
        gw_mute = gw_s == "bad" and self.gw and net_s in ("ok", "warn")
        if gw_mute:
            gw_s = "warn"
        if ch[0] == "bad":
            gw_s = net_s = dns_s = "wait"
        ch[1:] = [gw_s, net_s, dns_s]

        def last(key):
            s = [v for v in self.pings[key] if v is not None]
            return s[-1] if s else None
        vals[1].set_text("—" if ch[1] == "wait" and ch[0] == "bad" else
                         "нет шлюза" if not self.gw else
                         "молчит" if gw_mute else
                         "обрыв" if gw_s == "bad" else
                         fmt_ms(last("gw")) if self.pings["gw"] else "…")
        vals[2].set_text("—" if ch[0] == "bad" else
                         "обрыв" if net_s == "bad" else
                         fmt_ms(last("net")) if self.pings["net"] else "…")
        vals[3].set_text("—" if ch[0] == "bad" else
                         "…" if dns_s == "wait" else
                         "сбой" if dns_s == "bad" else fmt_ms(self.dns_ms))
        for st, lb in zip(ch, vals):
            self.set_cls(lb, {"ok": "dim", "wait": "dim"}.get(st, st))

        if WIFI and self.view != "wifi":
            return
        wired = not self.wireless
        load = self.others_load()
        cap = self.cap
        name = self.top_other()
        if name and len(name) > 10:
            name = name[:9] + "…"
        who = ""
        if load:
            who = " ".join(("↓ " if i == 0 else "↑ ") + fmt_rate(load[i])
                           for i in (0, 1) if load[i] >= 0.1 * cap[i]) or ""

        # Свой трафик тоже забивает канал: качается игра — пинг растёт.
        own = (statistics.mean(list(self.rx)[-OTHERS_AVG:]),
               statistics.mean(list(self.tx)[-OTHERS_AVG:]))
        mine_busy = own[0] >= OTHERS_BLAME * cap[0] or own[1] >= OTHERS_BLAME * cap[1]
        mine = " ".join(("↓ " if i == 0 else "↑ ") + fmt_rate(own[i])
                        for i in (0, 1) if own[i] >= 0.1 * cap[i])

        def busy(share):
            return bool(load) and (load[0] >= share * cap[0] or load[1] >= share * cap[1])
        if ch[0] == "bad":
            text, cls = ("Кабель не подключён или нет линка" if wired
                         else "Wi-Fi не подключён"), "bad"
        elif not self.gw:
            text, cls = "Линк есть, а адреса и шлюза нет — DHCP не ответил", "bad"
        elif gw_s == "bad":
            text, cls = "Роутер не отвечает — проверьте роутер и кабель до него", "bad"
        elif net_s == "bad":
            text, cls = "До роутера связь есть, дальше нет — роутер или провайдер", "bad"
        elif dns_s == "bad":
            text, cls = "Интернет есть, но имена не разрешаются — DNS", "bad"
        elif self.speed_busy:
            text, cls = "Идёт замер скорости — он сам занимает весь канал", "dim"
        elif "wait" in ch:
            text, cls = "Проверяю…", "dim"
        elif ch[0] == "warn" and WIFI:
            text, cls = "Слабый сигнал Wi-Fi — подойдите ближе к роутеру", "warn"
        elif ch[0] == "warn":
            text, cls = "Линк поднялся не на полной скорости — кабель или порт", "warn"
        elif gw_s == "warn" and not gw_mute and WIFI:
            text, cls = ("Wi-Fi до роутера теряет пакеты — %s" % (
                "канал забит соседними сетями" if self.crowded()
                else "стены, расстояние или помехи")), "warn"
        elif gw_s == "warn" and not gw_mute:
            text, cls = "Связь есть, но до роутера потери или задержки", "warn"
        elif net_s == "warn":
            # До роутера чисто, дальше хуже: канал забили другие — или это
            # роутер/провайдер. Счётчики роутера отличают одно от другого.
            text, cls = "Связь есть, но до интернета потери или задержки", "warn"
            if load:
                if busy(OTHERS_BLAME):
                    text = ("Задержки из-за «%s»:\nкачает %s" % (name, who) if name else
                            "Задержки из-за других устройств: они грузят канал %s" % who)
                elif mine_busy:
                    text = "Задержки, потому что этот ноутбук сам грузит канал %s" % mine
                else:
                    text = "Задержки до интернета, а канал свободен — роутер или провайдер"
            elif mine_busy:
                text = "Задержки, потому что этот ноутбук сам грузит канал %s" % mine
        elif busy(OTHERS_BUSY):
            text, cls = ("Канал занял «%s»:\nкачает %s" % (name, who) if name else
                         "Работает, но канал заняли другие устройства: %s" % who), "warn"
        elif dns_s == "warn":
            text, cls = "Всё работает, но DNS отвечает медленно", "warn"
        else:
            text, cls = "Всё в порядке", "ok"
        if self.verdict.get_text() != text:
            self.verdict.set_text(text)
        self.set_cls(self.verdict, cls)
        self.chain_da.queue_draw()

    def draw_chain(self, w, cr):
        W, H = w.get_allocated_width(), w.get_allocated_height()
        colors = {"ok": _rgb(OK_COLOR), "warn": _rgb(WARN_COLOR),
                  "bad": _rgb(self.pal["error"]),
                  "wait": _rgb(self.pal["on_surface_variant"])}
        xs = [(i + 0.5) * W / 4 for i in range(4)]
        y, r = H / 2, 6
        # Отрезок к звену — цветом этого звена: где цепочка «рвётся», видно сразу.
        for i in range(3):
            st = self.chain[i + 1]
            cr.set_source_rgba(*colors[st], 0.35 if st == "wait" else 0.8)
            cr.set_line_width(2)
            cr.move_to(xs[i] + r + 3, y)
            cr.line_to(xs[i + 1] - r - 3, y)
            cr.stroke()
        for x, st in zip(xs, self.chain):
            cr.arc(x, y, r, 0, 6.2832)
            if st == "wait":
                cr.set_source_rgba(*colors[st], 0.6)
                cr.set_line_width(1.5)
                cr.stroke()
            else:
                cr.set_source_rgb(*colors[st])
                cr.fill()
        return False

    # ── замер скорости ────────────────────────────────────────────────────
    def fill_history(self):
        for c in self.hist_grid.get_children():
            self.hist_grid.remove(c)
        hist = [h for h in load_history()
                if os.path.exists("/sys/class/net/%s/wireless" % h.get("iface")) == WIFI]
        hist = hist[-SPEED_SHOW:][::-1]
        if not hist:
            self.hist_grid.attach(self.label("Замеров ещё не было", "dim"), 0, 0, 4, 1)
        for r, h in enumerate(hist):
            when = time.strftime("%d.%m %H:%M", time.localtime(h.get("t", 0)))
            cells = ((when, "dim", 0), ("↓ %.0f" % h.get("down", 0), "down", 1),
                     ("↑ %.0f" % h.get("up", 0), "up", 1),
                     (fmt_ms(h.get("ping")), "dim", 1))
            busy_st = h.get("others", 0) >= 5
            for c, (t, cls, xa) in enumerate(cells):
                if c == 1 and busy_st:
                    t, cls = t + "*", "warn"
                lb = self.label(t, cls, xalign=xa)
                if c == 1 and busy_st:
                    lb.set_tooltip_text("Во время замера другие качали ~%.0f Мбит/с"
                                        % h["others"])
                lb.set_hexpand(c > 0)
                self.hist_grid.attach(lb, c, r, 1, 1)
        if hist:
            note = self.label("Мбит/с, последние замеры", "dim", xalign=1)
            self.hist_grid.attach(note, 0, len(hist), 4, 1)
        self.hist_grid.show_all()

    def start_speedtest(self, *_a):
        if self.speed_busy:
            return
        self.speed_busy = True
        self.speed_btn.set_sensitive(False)
        self.speed_btn.set_label("Идёт замер…")
        self.progress.set_fraction(0)
        self.progress.show()
        self.say("Пинг до сервера…")
        iface = self.iface
        self.st_others = []

        def ui(frac, text):
            GLib.idle_add(self.speed_progress, frac, text)

        def work():
            try:
                ping = st_ping()
                ui(0.06, "Пинг %s · загрузка…" % fmt_ms(ping))
                down = st_phase(_down_worker, ST_DOWN, lambda f, v: ui(
                    0.06 + 0.47 * f, "↓ загрузка  " + fmt_rate(v)))
                up = st_phase(_up_worker, ST_UP, lambda f, v: ui(
                    0.53 + 0.47 * f, "↑ отдача  " + fmt_rate(v)))
                res = {"t": time.time(), "down": round(down / 1e6, 1),
                       "up": round(up / 1e6, 1), "ping": round(ping, 1), "iface": iface}
                save_history(load_history() + [res])
                GLib.idle_add(self.speed_done, res, None)
            except Exception as e:
                GLib.idle_add(self.speed_done, None, str(e) or e.__class__.__name__)
        threading.Thread(target=work, daemon=True).start()

    def say(self, text, cls="dim"):
        self.speed_msg.set_text(text)
        self.set_cls(self.speed_msg, cls)
        self.speed_msg.set_visible(bool(text))

    def speed_progress(self, frac, text):
        self.progress.set_fraction(frac)
        self.say(text)
        return False

    def speed_done(self, res, err):
        self.speed_busy = False
        self.ping_quiet = time.monotonic() + 4   # очереди в роутере рассасываются
        # Сколько качали другие, пока шёл замер: заметно — цифра занижена.
        oth, self.st_others = self.st_others, None
        if res and oth:
            res["others"] = round(max(statistics.mean(v[0] for v in oth), 0) / 1e6, 1)
            h = load_history()
            if h and h[-1].get("t") == res["t"]:
                h[-1]["others"] = res["others"]
                save_history(h)
        self.cap = self.capacity()
        self.progress.hide()
        self.speed_btn.set_sensitive(True)
        self.speed_btn.set_label("Проверить ещё раз")
        if err:
            self.say("Замер не удался: %s" % err, "bad")
        else:
            msg = "↓ %.0f  ↑ %.0f Мбит/с · пинг %s" % (
                res["down"], res["up"], fmt_ms(res["ping"]))
            if res.get("others", 0) >= 5:
                msg += "\nДругие качали ~%.0f Мбит/с — замер занижен" % res["others"]
            self.say(msg, None)
            self.fill_history()
        return False


if __name__ == "__main__":
    win = LanPopup()
    win.show_all()
    Gtk.main()
