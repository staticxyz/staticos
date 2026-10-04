#!/usr/bin/env python3
"""Мелкие правки в окне Яндекс Музыки: размер текста, его ступени и плашка об оплате.

    ym_tweaks.py            применить к открытому окну
    ym_tweaks.py --wait     дождаться окна (зовётся из ym_launch.sh)

Почему скриптом, а не темой. Текст поднимается обычным CSS, а вот плашку
«Payment for Plus failed» CSS отличить не может: у всех предупреждений клиента
один класс RedAlert и одинаковые data-test-id, разница только в тексте
(проверено 25.09.2026). Поэтому её прячет наблюдатель DOM — по словам об
оплате и картах; остальные предупреждения остаются на месте.

Ступени размера — вместо зума, которого у клиента нет вовсе: ни меню с
ролями Chromium, ни доступа к webFrame (contextIsolation). Ctrl+Shift+«=»
крупнее, Ctrl+Shift+«−» мельче, Ctrl+Shift+0 — обратно к 16 px. Ступени
кратны клетке пиксельного шрифта (8 px), кроме родных 14: на некратном
PxPlus мылит. Выбор запоминается в localStorage плеера.

Меняется ТОЛЬКО размер текста, не zoom: zoom масштабировал и фиксированные
высоты, из-за чего нижняя панель плеера переставала вмещаться (проверено
25.09.2026).

Держится на том же порте отладки 9223, что шрифт и кнопка «Нравится»,
и ставится на каждую загрузку документа: плеер переходит между разделами,
одноразовая правка слетела бы на первом переходе.
"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ym_font  # noqa: E402  (page_ws, ws_calls — одна машинерия на всех)

SCRIPT_ID = "jarvis-ym-tweaks"

# 16 px, а не 14: у пиксельного шрифта системы клетка 8 px, и на кратном
# размере он рисуется чётко, а на 14 подмыливал. Классы клиента хешированы,
# поэтому цепляемся за устойчивые префиксы.
# Классы клиента хешированы, поэтому цепляемся за устойчивые префиксы.
# __SIZE__ подставляется на лету: одна и та же таблица служит всем ступеням.
CSS = """
[class*="Meta_title_"], [class*="Meta_artistCaption_"], [class*="Meta_text_"],
[class*="Tab_title_"], [class*="UserProfile_userName_"], [class*="NavbarDesktop_title"] {
  font-size: __SIZE__ !important;
  line-height: 1.25 !important;
}
"""

JS = r"""
(() => {
  const ID = "jarvis-ym-tweaks";
  const TEMPLATE = %s;
  const STEPS = [14, 16, 24, 32];     // 14 — родной размер клиента, дальше кратные клетке
  const DEFAULT = 16;
  const KEY = "jarvisFontSize";

  let el = document.getElementById(ID);
  if (!el) { el = document.createElement("style"); el.id = ID; document.head.appendChild(el); }

  const saved = () => {
    const v = parseInt(localStorage.getItem(KEY), 10);
    return STEPS.includes(v) ? v : DEFAULT;
  };
  const paint = (px) => {
    el.textContent = TEMPLATE.replace(/__SIZE__/g, px + "px");
    try { localStorage.setItem(KEY, String(px)); } catch (e) {}
  };
  paint(saved());

  // Ступени размера. Вешаем один раз на документ; в полях ввода не мешаем.
  if (!window.__jarvisFontKeys) {
    document.addEventListener("keydown", (e) => {
      if (!e.ctrlKey || !e.shiftKey || e.altKey || e.metaKey) return;
      const t = e.target;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      const now = saved();
      let next = null;
      if (e.code === "Equal" || e.code === "NumpadAdd") {
        next = STEPS[Math.min(STEPS.indexOf(now) + 1, STEPS.length - 1)];
      } else if (e.code === "Minus" || e.code === "NumpadSubtract") {
        next = STEPS[Math.max(STEPS.indexOf(now) - 1, 0)];
      } else if (e.code === "Digit0" || e.code === "Numpad0") {
        next = DEFAULT;
      }
      if (next === null) return;
      paint(next);
      e.preventDefault();
      e.stopPropagation();
    }, true);
    window.__jarvisFontKeys = true;
  }

  if (!window.__jarvisPayHide) {
    const WORDS = /payment for plus|bank card|оплат|карт[ыу]|списать/i;
    const hide = () => {
      let hidden = false;
      document.querySelectorAll('[class*="RedAlert_wrapper"]').forEach(w => {
        const off = WORDS.test(w.textContent || "");
        w.style.display = off ? "none" : "";
        hidden = hidden || off;
      });
      // Под плашку у корня зарезервирован отступ — убираем вместе с ней.
      const root = document.querySelector('[class*="DefaultLayout_root_withBarBelow"]');
      if (root) root.style.paddingBottom = hidden ? "0px" : "";
    };
    hide();
    new MutationObserver(hide).observe(document.body, {childList: true, subtree: true});
    window.__jarvisPayHide = true;
  }
  return "ok";
})()
"""


def apply_once():
    url = ym_font.page_ws()
    if not url:
        return False
    js = JS % json.dumps(CSS)
    calls = [{"id": 1, "method": "Runtime.evaluate",
              "params": {"expression": js, "returnByValue": True}},
             {"id": 2, "method": "Page.enable"},
             {"id": 3, "method": "Page.removeScriptToEvaluateOnNewDocument",
              "params": {"identifier": "2"}},
             {"id": 4, "method": "Page.addScriptToEvaluateOnNewDocument",
              "params": {"source": "document.addEventListener('DOMContentLoaded', () => { %s });" % js}}]
    answers = ym_font.ws_calls(url, calls)
    res = (answers[0].get("result", {}) or {}).get("result", {})
    return res.get("value") == "ok"


def main():
    wait = "--wait" in sys.argv[1:]
    deadline = time.time() + (40 if wait else 0)
    while True:
        try:
            if apply_once():
                print("ym_tweaks: применено")
                if wait:
                    ym_font.keep(apply_once, SCRIPT_ID)   # то же, что у шрифта: заставка при старте
                return 0
        except (OSError, ValueError):
            pass
        if time.time() >= deadline:
            break
        time.sleep(1.5)
    print("ym_tweaks: окно не отвечает", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
