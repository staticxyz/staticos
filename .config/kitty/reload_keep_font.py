"""Перечитать kitty.conf, не сбрасывая размер шрифта окон.

Запуск (из theme_changer.sh при смене обоев, по сокету каждого kitty):
    kitty @ --to unix:/tmp/kitty-PID kitten reload_keep_font.py

Зачем. После заливки палитры theme_changer.sh перечитывал конфиг сигналом
SIGUSR1 — так в окна доезжает ~/.cache/matugen/kitty-opacity.conf
(transparent_background_colors зависит от фона палитры, а `kitty @ set-colors`
на этом ключе падает). Но kitty при перечитывании конфига ставит КАЖДОМУ окну
font_size из kitty.conf без условий (boss.apply_new_options,
os_window_font_size(..., opts.font_size, True)) — размер, уменьшенный вручную
(Ctrl+Shift+−), сбрасывался при каждой смене обоев (15.09.2026).
Проверено на пробном окне: set-colors размер не трогает, SIGUSR1 — сбрасывает.

Этот kitten выполняется внутри процесса kitty: запоминает размер каждого
OS-окна, перечитывает конфиг тем же load_config_file, что и SIGUSR1, и
возвращает размеры тем же путём, каким их меняют сочетания клавиш.

16.09.2026. Возврата размера ПОСЛЕ перечитывания мало: между ним и возвратом
окно успевает пожить с чужим шрифтом, и сетка на это время сжимается. Замер на
двух окнах `timer` (шрифт 6, 65x21): при font_size 11 из kitty.conf остаётся
~35 колонок, и всё, что правее, kitty отрезает навсегда — вернувшаяся ширина
пустые клетки не восстанавливает. Так от надписи над таймером
оставался обрубок (HH — «HI») (скриншот пользователя после смены обоев).
Перерисовывает termdown только цифры, поэтому обрубок держится до конца
минуты, а у приложений, которые рисуют один раз, — до перезапуска.

Поэтому размер теперь не возвращается, а не сбивается вовсе: на время
load_config_file имя os_window_font_size в модуле kitty.boss подменяется
обёрткой, которая на запрос «поставить font_size из конфига» ставит окну его
собственный размер. Сетка не меняется ни на миг, SIGWINCH не рассылается,
резать нечего. Возврат ниже остаётся страховкой на случай, если в новой версии
kitty подмена не сработает: тогда всё ведёт себя как раньше, а не хуже.
"""
from contextlib import contextmanager

from kittens.tui.handler import result_handler


def main(args):
    pass


@contextmanager
def sizes_pinned(sizes):
    """Не дать apply_new_options поставить окнам font_size из конфига.

    boss.py берёт имя себе (`from .fast_data_types import os_window_font_size`),
    поэтому подменять надо именно в kitty.boss, а не в fast_data_types.
    Чтение (один аргумент) и все прочие вызовы уходят в настоящую функцию.
    """
    import kitty.boss as boss_module

    real = boss_module.os_window_font_size

    def pinned(os_window_id, sz=None, force=False):
        if sz is None:
            return real(os_window_id)
        own = sizes.get(os_window_id)
        return real(os_window_id, own or sz, force)

    boss_module.os_window_font_size = pinned
    try:
        yield
    finally:
        boss_module.os_window_font_size = real


def restore(boss, sizes):
    """Вернуть размеры принудительно (force=True) и пересчитать окна.

    Без force и сразу после load_config_file размер не держался: первая проба
    (15.09.2026) запомнила 8, а в окне после перечитывания снова было 11 —
    kitty досчитывает новое оформление позже и затирал возврат. Поэтому
    возврат делается дважды: сразу и ещё раз таймером kitty.

    С подменой выше возвращать обычно уже нечего — размер и так свой, вызов
    проходит вхолостую и сетку не трогает.
    """
    from kitty.fast_data_types import os_window_font_size
    for wid, sz in sizes.items():
        tm = boss.os_window_map.get(wid)
        if tm is not None and sz:
            os_window_font_size(wid, sz, True)
            tm.resize()


@result_handler(no_ui=True)
def handle_result(args, answer, target_window_id, boss):
    from kitty.fast_data_types import add_timer, os_window_font_size
    sizes = {wid: os_window_font_size(wid) for wid in boss.os_window_map}
    with sizes_pinned(sizes):
        boss.load_config_file()
    restore(boss, sizes)
    add_timer(lambda *_: restore(boss, sizes), 0.15, False)
    return "перечитан конфиг, размер шрифта сохранён: %s" % ", ".join(
        "%g" % s for s in sizes.values())
