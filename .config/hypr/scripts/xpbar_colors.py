#!/usr/bin/env python3
"""Цвета XP-панели и меню «Пуск» из палитры обоев — общий модуль. 01.10.2026.

Вынесено из xpbar.py: меню «Пуск» (start_menu.py) должно быть в тех же тонах,
а сам xpbar.py импортировать нельзя — при загрузке он разбирает argv и
запускается как панель.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import popup_theme  # noqa: E402


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))


def rgb2hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v * 255))) for v in c)


def mix(a, b, t):
    """Смесь двух #rrggbb: t=0 — a, t=1 — b."""
    x, y = hex2rgb(a), hex2rgb(b)
    return rgb2hex(tuple(x[i] + (y[i] - x[i]) * t for i in range(3)))


def colors():
    pal = popup_theme.palette()
    base = popup_theme.bar_bg()
    p = pal["primary"]
    c = dict(pal)
    c.update(
        base=base,
        # полоса: «особая линия» сверху, полутон, градиент вниз
        line1=mix(base, p, 0.62), line2=mix(base, p, 0.30),
        g_top=mix(base, p, 0.20), g_mid=mix(base, p, 0.11), g_bot=mix(base, p, 0.05),
        # «Пуск»
        st_top=mix(base, p, 0.62), st_mid=mix(base, p, 0.44), st_bot=mix(base, p, 0.30),
        st_hi=mix(base, p, 0.85), st_dark=mix(base, "#000000", 0.35),
        st_hover=mix(base, p, 0.70),
        st_press_top=mix(base, p, 0.14), st_press_bot=mix(base, p, 0.30),
        # кнопки окон
        t_top=mix(base, p, 0.34), t_bot=mix(base, p, 0.22), t_hi=mix(base, p, 0.52),
        t_border=mix(base, p, 0.46), t_hover_top=mix(base, p, 0.44), t_hover_bot=mix(base, p, 0.30),
        f_top=mix(base, p, 0.08), f_bot=mix(base, p, 0.15), f_border=mix(base, "#000000", 0.4),
        # трей
        tr_top=mix(base, p, 0.30), tr_bot=mix(base, p, 0.16), tr_light=mix(base, p, 0.50),
        tr_dark=mix(base, "#000000", 0.45),
        text=pal["on_surface"], dim=pal["on_surface_variant"],
    )
    return c


