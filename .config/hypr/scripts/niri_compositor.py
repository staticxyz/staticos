#!/usr/bin/env python3
"""Настройки композитора niri для страницы Compositor в Настройках (13.10.2026).

    niri_compositor.py get            все значения, JSON
    niri_compositor.py set КЛЮЧ ЧИСЛО записать, проверить `niri validate`, применить
    niri_compositor.py set island_space N [ВЫХОД…]   добавка к верхнему краю под нить
                                      островка — только этим мониторам (без выходов — нигде)

Отступ от краёв экрана (edge) — не строка конфига, а сумма: в niri gaps стоит и между
окнами, и у края, а struts добавляются к нему снаружи. Поэтому edge пишется как
struts = edge − gaps (может быть отрицательным — niri это принимает), а при смене gaps
struts пересчитываются, чтобы отступ у краёв остался прежним (13.10.2026, просьба: «отступы между окнами и отступы от краёв экрана» отдельно).

Сверху к краю добавляется island_space — зазор между окнами и нитью островка (19.10.2026, просьба: «создать пространство между окном и линией островка»). Его пишет island.py: пока
островок включён — по виду нити, выключен — 0. Ползунки краёв и gaps добавку сохраняют.
Добавка — по мониторам: свой layout { struts } внутри блока output в outputs.kdl (niri 26.04
так умеет); монитор с постоянным верхним waybar её не получает (19.10.2026, просьба: «при
waybar эта линия не должна рисоваться… создалось небольшое пространство между окном и
waybar'ом»). Общий struts в layout.kdl — без добавки.

Значения правятся на месте, в тех файлах, где они и так живут. Если niri конфиг не
принял, файл возвращается как был (rc 1).
"""
import json
import os
import re
import subprocess
import sys

CFG = os.path.expanduser("~/.config/niri/cfg")
MATUGEN_TPL = os.path.expanduser("~/.config/matugen/templates/niri-colors.kdl")
MATUGEN_OUT = os.path.expanduser("~/.cache/matugen/niri-colors.kdl")

# ключ: (файлы, шаблон строки, по умолчанию, мин, макс, целое)
# Ширина рамки: действующее значение — в niri-colors.kdl (include после layout перекрывает
# его width 0); файл пересобирает matugen при смене обоев, поэтому правим и шаблон.
KEYS = {
    "gaps": ([os.path.join(CFG, "layout.kdl")], r"^(    gaps )(\S+)$", 16, 0, 40, True),
    "border": ([MATUGEN_OUT, MATUGEN_TPL], r"^(        width )(\S+)$", 5, 0, 12, True),
    "blur_passes": ([os.path.join(CFG, "blur.kdl")], r"^(    passes )(\S+)$", 3, 1, 6, True),
    "blur_offset": ([os.path.join(CFG, "blur.kdl")], r"^(    offset )(\S+)$", 5.0, 0.5, 10.0, False),
    "blur_noise": ([os.path.join(CFG, "blur.kdl")], r"^(    noise )(\S+)$", 0.01, 0.0, 0.1, False),
    "blur_saturation": ([os.path.join(CFG, "blur.kdl")], r"^(    saturation )(\S+)$", 1.5, 0.0, 3.0, False),
    "slowdown": ([os.path.join(CFG, "animations.kdl")], r"^(    slowdown )(\S+)$", 1.0, 0.25, 3.0, False),
}


LAYOUT = os.path.join(CFG, "layout.kdl")
OUTPUTS = os.path.join(CFG, "outputs.kdl")
OUT_RE = re.compile(r'^output "([^"]+)" \{\n(.*?)^\}\n', re.M | re.S)
ISLAND_RE = re.compile(r"^    // Зазор под нить островка[^\n]*\n    layout \{\n(?:        [^\n]*\n)*?    \}\n", re.M)
EDGE_LO, EDGE_HI = 0, 80
STRUTS_RE = re.compile(r"^    struts \{\n(?:        .*\n)*?    \}\n", re.M)


def read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def get(key):
    files, pat, default, _lo, _hi, is_int = KEYS[key]
    txt = read(files[0]) or ""
    m = re.search(pat, txt, re.M)
    if not m:
        return default
    try:
        return int(float(m.group(2))) if is_int else float(m.group(2))
    except ValueError:
        return default


def struts(txt, side="left"):
    m = STRUTS_RE.search(txt or "")
    v = re.search(r"^\s*%s\s+(-?\d+)" % side, m.group(0), re.M) if m else None
    return int(v.group(1)) if v else 0


def island_space(txt):
    """Добавка сверху (top − left): её держит островок, края её не трогают."""
    return struts(txt, "top") - struts(txt, "left") if STRUTS_RE.search(txt or "") else 0


def island_outs(txt):
    """{выход: добавка} из блоков output (свой layout островка)."""
    out = {}
    for m in OUT_RE.finditer(txt or ""):
        b = ISLAND_RE.search(m.group(2))
        if b:
            top = re.search(r"^\s*top\s+(-?\d+)", b.group(0), re.M)
            left = re.search(r"^\s*left\s+(-?\d+)", b.group(0), re.M)
            if top and left and int(top.group(1)) != int(left.group(1)):
                out[m.group(1)] = int(top.group(1)) - int(left.group(1))
    return out


def with_island_outs(txt, base, want):
    """Блоки островка в outputs.kdl: у выходов из want — struts с добавкой сверху, у прочих
    блока нет. base — struts без добавки (как в layout.kdl)."""
    def one(m):
        name, body = m.group(1), ISLAND_RE.sub("", m.group(2))
        n = want.get(name, 0)
        if n:
            body += ("    // Зазор под нить островка (пишет niri_compositor.py, руками не править)\n"
                     "    layout {\n        struts {\n" +
                     "".join("            %s %d\n" % (k, base + (n if k == "top" else 0))
                             for k in ("left", "right", "top", "bottom")) +
                     "        }\n    }\n")
        return 'output "%s" {\n%s}\n' % (name, body)
    return OUT_RE.sub(one, txt)


def get_edge():
    return get("gaps") + struts(read(LAYOUT))


def with_struts(txt, value, extra=None):
    """Блок struts внутри layout: заменить или поставить сразу после строки gaps. Сверху —
    value + extra (добавка островка; None — оставить прежнюю)."""
    if extra is None:
        extra = island_space(txt)
    block = ("    // Отступ от краёв экрана = gaps + struts. Пишет niri_compositor.py\n"
             "    // (Настройки → Compositor → «Отступы от краёв экрана»), руками не править.\n"
             if not STRUTS_RE.search(txt) else "")
    body = "    struts {\n" + "".join("        %s %d\n" % (k, value + (extra if k == "top" else 0))
                                    for k in ("left", "right", "top", "bottom")) + "    }\n"
    if STRUTS_RE.search(txt):
        return STRUTS_RE.sub(lambda m: body, txt, count=1)
    return re.sub(r"^(    gaps \S+\n)", lambda m: m.group(1) + "\n" + block + body, txt, count=1, flags=re.M)


def apply(old):
    """niri validate; не принял — вернуть файлы как были."""
    r = subprocess.run(["niri", "validate"], capture_output=True, text=True)
    if r.returncode != 0:
        for path, txt in old.items():
            write_atomic(path, txt)
        print("niri не принял конфиг, вернул как было", file=sys.stderr)
        return False
    subprocess.run(["niri", "msg", "action", "load-config-file"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def keep_outs(base, old):
    """Добавку островка у мониторов — к новому краю (base)."""
    ot = read(OUTPUTS)
    if ot is not None and island_outs(ot):
        old[OUTPUTS] = ot
        write_atomic(OUTPUTS, with_island_outs(ot, base, island_outs(ot)))


def set_edge(raw):
    val = int(round(max(EDGE_LO, min(EDGE_HI, float(raw)))))
    txt = read(LAYOUT)
    if txt is None:
        return 1
    write_atomic(LAYOUT, with_struts(txt, val - get("gaps")))
    old = {LAYOUT: txt}
    keep_outs(val - get("gaps"), old)
    if not apply(old):
        return 1
    print(val)
    return 0


def set_island_space(raw, outs=()):
    val = int(round(max(0, min(40, float(raw)))))
    txt, ot = read(LAYOUT), read(OUTPUTS)
    if txt is None or ot is None:
        return 1
    want = {o: val for o in outs} if val else {}
    base = struts(txt)
    new_l = with_struts(txt, base, 0) if island_space(txt) else txt   # общий край — без добавки
    new_o = with_island_outs(ot, base, want)
    if new_l == txt and new_o == ot:
        print(val)
        return 0
    write_atomic(LAYOUT, new_l)
    write_atomic(OUTPUTS, new_o)
    if not apply({LAYOUT: txt, OUTPUTS: ot}):
        return 1
    print(val)
    return 0


def fmt(val, is_int):
    return "%d" % val if is_int else ("%.3f" % val).rstrip("0").rstrip(".") if val % 1 else "%.1f" % val


def write_atomic(path, txt):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(txt)
    os.replace(tmp, path)


def set_value(key, raw):
    files, pat, _default, lo, hi, is_int = KEYS[key]
    val = max(lo, min(hi, float(raw)))
    val = int(round(val)) if is_int else round(val, 3)
    text = fmt(val, is_int)
    edge = get_edge() if key == "gaps" else None
    old = {}
    for path in files:
        txt = read(path)
        if txt is None:
            continue
        old[path] = txt
        if re.search(pat, txt, re.M):
            new = re.sub(pat, lambda m: m.group(1) + text, txt, count=1, flags=re.M)
        elif key == "slowdown":
            # строки нет — первой в блоке animations
            new = re.sub(r"^animations \{\n", "animations {\n    slowdown %s\n" % text, txt,
                         count=1, flags=re.M)
        else:
            continue
        if edge is not None and path == LAYOUT and (STRUTS_RE.search(new) or edge != val):
            new = with_struts(new, edge - val)     # край экрана остаётся на месте
        write_atomic(path, new)
    if edge is not None:
        keep_outs(edge - val, old)
    if not apply(old):
        return 1
    print(text)
    return 0


def main(argv):
    if len(argv) >= 2 and argv[1] == "get":
        out = {k: get(k) for k in KEYS}
        out["edge"] = get_edge()
        out["island_space"] = island_space(read(LAYOUT))     # старая общая добавка (должна быть 0)
        out["island_outs"] = island_outs(read(OUTPUTS))
        print(json.dumps(out))
        return 0
    if len(argv) == 4 and argv[1] == "set" and argv[2] == "edge":
        return set_edge(argv[3])
    if len(argv) >= 4 and argv[1] == "set" and argv[2] == "island_space":
        return set_island_space(argv[3], argv[4:])
    if len(argv) == 4 and argv[1] == "set" and argv[2] in KEYS:
        return set_value(argv[2], argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
