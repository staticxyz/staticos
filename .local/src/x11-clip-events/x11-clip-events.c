/* Печатает строку при каждой смене владельца CLIPBOARD на X11-дисплее ($DISPLAY).
 * Нужен x11-clip-bridge: мост xwayland-satellite отдаёт Wayland текст из X11-программ
 * (Tor Browser) только пока X11-окно в фокусе — здесь фокус не нужен.
 * Сборка: gcc -O2 -o ~/.local/bin/x11-clip-events x11-clip-events.c -lX11 -lXfixes */
#include <stdio.h>
#include <X11/Xlib.h>
#include <X11/extensions/Xfixes.h>

int main(void) {
    Display *d = XOpenDisplay(NULL);
    if (!d) { fprintf(stderr, "нет X11-дисплея\n"); return 1; }
    int ev, err;
    if (!XFixesQueryExtension(d, &ev, &err)) { fprintf(stderr, "нет XFixes\n"); return 1; }
    Atom clip = XInternAtom(d, "CLIPBOARD", False);
    XFixesSelectSelectionInput(d, DefaultRootWindow(d), clip,
                               XFixesSetSelectionOwnerNotifyMask);
    setvbuf(stdout, NULL, _IOLBF, 0);
    for (XEvent e;;) {
        XNextEvent(d, &e);   /* дисплей закрылся — Xlib сам завершит процесс */
        if (e.type == ev + XFixesSelectionNotify)
            printf("%lu\n", ((XFixesSelectionNotifyEvent *)&e)->owner);
    }
}
