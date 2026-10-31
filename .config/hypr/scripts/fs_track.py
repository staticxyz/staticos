#!/usr/bin/env python3
"""Монитор, занятый окном во весь экран, — по событиям niri, без запросов (30.10.2026).

Просьба: «при переключении на такое окно островок и панелька не должны мелькать даже на секунду».
Причина: niri рисует полноэкранное окно выше слоя TOP, только когда вид неподвижен; пока едет
смена стола или прокрутка, TOP виден поверх. Поэтому панели, которым это мешает, стоят на
таком мониторе в слое BOTTOM: он всегда под окнами. Скрывать их нельзя: панель держит зону
у края экрана, и окна перестраивались бы. Смена слоя идёт по первому же событию, до анимации.
Общая для xpbar.py и island.py, чтобы признак полного экрана у них не разошёлся.
"""
import ctypes
import sys


class FsTrack:
    def __init__(self):
        self.windows, self.workspaces = {}, {}
        self.overview = False

    def feed(self, ev):
        """Учесть событие niri. True — признак полного экрана мог измениться."""
        kind = next(iter(ev), None)
        d = ev.get(kind) or {}
        if kind == "WorkspacesChanged":
            self.workspaces = {w["id"]: w for w in d["workspaces"]}
        elif kind == "WorkspaceActivated":
            ws = self.workspaces.get(d["id"])
            if ws is None:
                return False
            for w in self.workspaces.values():
                if w.get("output") == ws.get("output"):
                    w["is_active"] = w is ws
        elif kind == "WorkspaceActiveWindowChanged":
            ws = self.workspaces.get(d["workspace_id"])
            if ws is None:
                return False
            ws["active_window_id"] = d.get("active_window_id")
        elif kind == "WindowsChanged":
            self.windows = {w["id"]: w for w in d["windows"]}
        elif kind == "WindowOpenedOrChanged":
            self.windows[d["window"]["id"]] = d["window"]
        elif kind == "WindowClosed":
            self.windows.pop(d["id"], None)
        elif kind == "WindowLayoutsChanged":
            for wid, lay in d.get("changes", []):
                if wid in self.windows:
                    self.windows[wid]["layout"] = lay
        elif kind == "OverviewOpenedOrClosed":
            self.overview = bool(d.get("is_open"))
        else:
            return False
        return True

    def on(self, output, width, height):
        """Активное окно стола на output — во весь экран. Плавающее в фокусе не считается: что
        niri рисует в этом случае, не проверено, и панель остаётся как была. В обзоре — False:
        в слое BOTTOM панель уехала бы в миниатюры столов."""
        if self.overview:
            return False
        ws = next((w for w in self.workspaces.values()
                   if w.get("output") == output and w.get("is_active")), None)
        win = self.windows.get(ws.get("active_window_id")) if ws else None
        if win is None or win.get("is_floating"):
            return False
        size = (win.get("layout") or {}).get("window_size") or [0, 0]
        return size[0] >= width and size[1] >= height


def commit_now(win):
    """wl_surface.commit сразу. Слой (и другое состояние layer-shell) применяется только с коммитом,
    а GTK рисует по кадровому сигналу niri, который окну под полноэкранным приходит раз в ~секунду:
    панель поднималась через пару секунд после меню (27.10.2026, просьба: «надо вместе, синхронно,
    моментально»). Коммит без нового буфера — только применяет ждущее состояние."""
    try:
        gw = win.get_window()
        if gw is None:
            return
        cap = ctypes.pythonapi.PyCapsule_GetPointer
        cap.restype, cap.argtypes = ctypes.c_void_p, [ctypes.py_object, ctypes.c_char_p]
        gdk = ctypes.CDLL("libgdk-3.so.0")
        gdk.gdk_wayland_window_get_wl_surface.restype = ctypes.c_void_p
        gdk.gdk_wayland_window_get_wl_surface.argtypes = [ctypes.c_void_p]
        gdk.gdk_wayland_display_get_wl_display.restype = ctypes.c_void_p
        gdk.gdk_wayland_display_get_wl_display.argtypes = [ctypes.c_void_p]
        surf = gdk.gdk_wayland_window_get_wl_surface(cap(gw.__gpointer__, None))
        dpy = gdk.gdk_wayland_display_get_wl_display(cap(gw.get_display().__gpointer__, None))
        if not surf or not dpy:
            return
        wl = ctypes.CDLL("libwayland-client.so.0")
        wl.wl_proxy_marshal(ctypes.c_void_p(surf), ctypes.c_uint32(6))   # 6 = wl_surface.commit
        wl.wl_display_flush(ctypes.c_void_p(dpy))
    except Exception as e:
        print("commit_now:", e, file=sys.stderr)
