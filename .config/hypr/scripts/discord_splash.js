// Заставка Discord («Checking for updates…») в стиле системы (13.10.2026, Просьба: «можно эту
// часть дискорда тоже сделать пиксельной? Это начальное маленькое окно»). Тема Vencord красит
// только главное окно; заставка — отдельное окно хост-приложения (_app.asar/splash). Этот файл
// грузит прокладка app.asar ПЕРЕД Vencord (вписывает discord_pixel.py) и подкладывает в окно
// заставки CSS из ~/.config/hypr/state/discord-splash.css — его пишет discord_pixel.py в тех
// же цветах и стиле, что и тему. Файла нет или пустой — заставка обычная. Любая ошибка
// глотается: Discord должен запуститься в любом случае.
try {
    const { app } = require("electron");
    const fs = require("fs");
    const path = require("path");
    const CSS = path.join(require("os").homedir(), ".config/hypr/state/discord-splash.css");
    app.on("browser-window-created", (_e, win) => {
        try {
            win.webContents.on("dom-ready", () => {
                try {
                    if (!/[\\/]splash[\\/]index\.html/.test(win.webContents.getURL())) return;
                    const css = fs.readFileSync(CSS, "utf8");
                    if (css.trim()) win.webContents.insertCSS(css);
                } catch (e) { /* нет файла — обычная заставка */ }
            });
        } catch (e) { /* окно без webContents */ }
    });
} catch (e) { /* не electron — ничего */ }
