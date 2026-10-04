#!/usr/bin/env python3
"""Общая проверка для hypridle: держать ли экран зажжённым.

Экран не гаснет и не блокируется, только если выполнены ОБА условия:
включён Savage Mode и включён его спутник «не отключать экран». Одного флага
мало намеренно: так забытая галочка не оставит машину незапертой навсегда.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(HERE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def keep_screen_on():
    try:
        return bool(_load("savage_battery").is_savage_active()) and bool(_load("screen_awake").get())
    except Exception as e:                      # сомневаешься — блокируй
        print("idle_guard: %s" % e, file=sys.stderr)
        return False
