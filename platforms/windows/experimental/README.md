# Старый путь Windows launcher

В версии **1.0.0** обычный [Start-Almaty.ps1](../Start-Almaty.ps1) запускает настоящий общий Linux-сеанс в выделенном WSL2. `Start-Almaty-Experimental.ps1` оставлен как перенаправление для старых команд. `-Experimental` принимается для совместимости, но не нужен.

Используй [Windows README](../README.md): установка WSL2 Ubuntu24.04, собственный SSH-транспорт, Linux Claude/Chrome, запрет Windows interop, точный Wayland socket, проверка `-Plan`, затем реальный запуск и обе задачи. Подробные параметры Linux engine — в [техническом README](../../linux/experimental/README.md).

`-Plan` печатает argv без запуска даже WSL. Обычный запуск исполняет engine; пароль не находится в argv. Fresh PID своей SSH-службы нужно получать при каждом запуске, как показано в основном README. Никакого host browser, default distro, `Invoke-Expression` или fallback при ошибке.

Native PowerShell/WSLg проверяются на компьютере получателя с его Codex. Отсутствие авторского Windows-стенда не запрещает эту настройку и не означает, что runtime уже доказан. Итог — реальный ответ веб-чата, локальная задача CLI и повторное открытие обоих приложений с сохранённой историей.
