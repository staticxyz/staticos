"""Переменные сеанса для служб systemd --user, запущенных раньше, чем niri отдал их systemd
(12.10.2026: будильник и hub остались без экрана — окна и снимки падали)."""
import glob
import os
import re


def fill():
    run = os.environ.get("XDG_RUNTIME_DIR") or "/run/user/%d" % os.getuid()
    niri = os.environ.get("NIRI_SOCKET", "")
    if not niri or not os.path.exists(niri):
        socks = glob.glob(os.path.join(run, "niri.wayland-*.sock"))
        if socks:
            os.environ["NIRI_SOCKET"] = niri = max(socks, key=os.path.getmtime)
    if not os.environ.get("WAYLAND_DISPLAY"):
        # «niri.wayland-1.10191.sock» → wayland-1; рядом лежат чужие wayland-1-*.sock
        m = re.match(r"niri\.(wayland-\d+)\.", os.path.basename(niri))
        socks = sorted(os.path.basename(x) for x in glob.glob(os.path.join(run, "wayland-*"))
                       if re.fullmatch(r"wayland-\d+", os.path.basename(x)))
        name = m.group(1) if m else (socks[0] if socks else None)
        if name:
            os.environ["WAYLAND_DISPLAY"] = name
