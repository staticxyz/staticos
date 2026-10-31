#!/usr/bin/env python3
"""Наблюдатель значков трея (org.kde.StatusNotifierWatcher). 30.10.2026.

    sni_watcher.py          работать (служба sni-watcher, поднимается раньше программ)
    sni_watcher.py check    занято ли имя и какие значки записаны

Пользователь, 30.10: «Почему у меня в трее пусто?». Программы записывают значки у наблюдателя, а
плашка трея в xpbar читает список у него же. Наблюдателя держал kded6, но он запускается не
с сессией, а по случайному обращению какой-нибудь программы KDE: 30.10 после перезагрузки его
не было, и плашка показывала «пусто», хотя программы работали. Здесь наблюдатель свой и
постоянный. Поднимется kded6 — его модуль просто не получит имя и ни на что не повлияет.

Если имя уже занято, GDBus ставит в очередь: освободится — займём его сами.
IsStatusNotifierHostRegistered всегда да: хост (плашка) читает список по щелчку и на шине не
записывается, а без этого часть программ значок не показывает.
"""
import json
import sys

import gi
gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib

NAME = "org.kde.StatusNotifierWatcher"
PATH = "/StatusNotifierWatcher"
XML = """<node><interface name="%s">
  <method name="RegisterStatusNotifierItem"><arg name="service" type="s" direction="in"/></method>
  <method name="RegisterStatusNotifierHost"><arg name="service" type="s" direction="in"/></method>
  <property name="RegisteredStatusNotifierItems" type="as" access="read"/>
  <property name="IsStatusNotifierHostRegistered" type="b" access="read"/>
  <property name="ProtocolVersion" type="i" access="read"/>
  <signal name="StatusNotifierItemRegistered"><arg type="s"/></signal>
  <signal name="StatusNotifierItemUnregistered"><arg type="s"/></signal>
  <signal name="StatusNotifierHostRegistered"/>
  <signal name="StatusNotifierHostUnregistered"/>
</interface></node>""" % NAME
items = []


def emit(bus, signal, ref):
    bus.emit_signal(None, PATH, NAME, signal, GLib.Variant("(s)", (ref,)))


def on_call(bus, sender, path, iface, method, args, inv):
    service = args.unpack()[0]
    if method == "RegisterStatusNotifierItem":
        # имя шины → объект по умолчанию; путь → служба та, что позвонила (libappindicator)
        ref = sender + service if service.startswith("/") else service + "/StatusNotifierItem"
        if ref not in items:
            items.append(ref)
            emit(bus, "StatusNotifierItemRegistered", ref)
    else:
        bus.emit_signal(None, PATH, NAME, "StatusNotifierHostRegistered", None)
    inv.return_value(None)


def on_get(bus, sender, path, iface, prop):
    if prop == "RegisteredStatusNotifierItems":
        return GLib.Variant("as", items)
    if prop == "IsStatusNotifierHostRegistered":
        return GLib.Variant("b", True)
    return GLib.Variant("i", 0)


def on_owner(bus, sender, path, iface, signal, args):
    name, _old, new = args.unpack()
    if new:
        return
    for ref in [r for r in items if r.split("/", 1)[0] == name]:
        items.remove(ref)
        emit(bus, "StatusNotifierItemUnregistered", ref)


def check():
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    try:
        r = bus.call_sync(NAME, PATH, "org.freedesktop.DBus.Properties", "Get", GLib.Variant("(ss)", (NAME, "RegisteredStatusNotifierItems")),
                          GLib.VariantType.new("(v)"), Gio.DBusCallFlags.NO_AUTO_START, 1000, None)
    except GLib.Error as e:
        print(json.dumps({"watcher": False, "error": e.message}, ensure_ascii=False))
        return 1
    print(json.dumps({"watcher": True, "items": r.unpack()[0]}, ensure_ascii=False))
    return 0


def main():
    if sys.argv[1:] == ["check"]:
        return check()
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    info = Gio.DBusNodeInfo.new_for_xml(XML).interfaces[0]
    bus.register_object(PATH, info, on_call, on_get, None)
    bus.signal_subscribe("org.freedesktop.DBus", "org.freedesktop.DBus", "NameOwnerChanged",
                         "/org/freedesktop/DBus", None, Gio.DBusSignalFlags.NONE, on_owner)
    Gio.bus_own_name_on_connection(bus, NAME, Gio.BusNameOwnerFlags.NONE, None, None)
    GLib.MainLoop().run()


if __name__ == "__main__":
    sys.exit(main())
