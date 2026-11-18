# Windows 11 x64 + отдельная WSL2 Ubuntu 24.04

Версия **1.0.0 — настройка с Codex на твоём компьютере**. `Start-Almaty.ps1` действительно запускает общий Linux engine через явно выбранный WSL2. Native Windows/WSLg при сборке не проверялись: эти проверки выполняются здесь, на компьютере получателя, с исправлением конкретных несовместимостей. Это не повод ждать испытаний автора. Windows10, ARM64, WSL1 и native `claude.exe` этим маршрутом не покрываются.

Финиш: реальный ответ Claude в отдельном Linux Google Chrome через WSLg, задача Claude Code с локальным файлом в терминале WSL и повторное открытие обоих приложений с сохранённой историей. Windows Terminal — терминал этого маршрута; iTerm2 и Agentbelt не переносятся с Mac.

Claude, его инструменты и **Linux Chrome через WSLg** должны находиться внутри одной внешней Linux-границы. Windows Chrome, Edge, Codex Desktop и вся обычная сеть компьютера остаются снаружи. Переменные proxy в PowerShell или правило firewall для одного `.exe` не защищают всё дерево дочерних программ.

## 1. Опись Windows без изменений

В PowerShell (пока без прав администратора):

```powershell
Get-ComputerInfo -Property WindowsProductName,WindowsVersion,OsBuildNumber,OsArchitecture
wsl --version
wsl --status
wsl --list --verbose
Get-Volume | Select-Object DriveLetter,SizeRemaining,Size
```

Если WSL нет, сохранить этот факт; это не повод автоматически устанавливать компоненты и перезагружаться. Проверить аппаратную виртуализацию и политику организации. Для стенда желательны 8–16 ГБ RAM компьютера и десятки ГБ свободного диска; это ориентир для Windows+WSL+Chrome, не официальный минимум Claude. Сам Claude требует отдельной сверки [системных требований](https://code.claude.com/docs/en/setup).

Составить список существующих дистрибутивов. **Не использовать рабочую Ubuntu человека**, не экспортировать/клонировать её и не менять глобальную default distro. Прочитать наличие `%UserProfile%\.wslconfig` без вывода возможных чужих секретов/сетевых данных. Записать NAT/mirrored, DNS tunneling, autoProxy и версию WSLg. Изменения глобального файла затрагивают другие дистрибутивы.

Человек отдельно подтверждает установку WSL/образа с указанным размером и местом, а также перезагрузку, если она нужна. Согласно [Microsoft](https://learn.microsoft.com/en-us/windows/wsl/reference), новый WSL можно поставить без default distro:

```powershell
wsl --install --no-distribution
```

Только если WSL ещё не установлен. После предложенного системой reboot повторить опись. Не менять BIOS/корпоративные политики без владельца.

## 2. Отдельный дистрибутив

Первый стенд называется `AlmatyAccess`. Сначала проверить отсутствие такого имени и выбрать **пустую новую** папку, например `C:\WSL\AlmatyAccess`. Из [официальной Ubuntu WSL-инструкции](https://ubuntu.com/wsl/docs/latest/howto/install-ubuntu-wsl2/) перейти к архиву Ubuntu **24.04** и скачать amd64 WSL image, SHA256SUMS и подпись. Не брать Desktop ISO или текущую версию Ubuntu по умолчанию: она может быть новее24.04.

Образ нового tar-based формата `.wsl` — исходный установочный архив, не копия чьей-либо системы. Проверить его SHA256 (`Get-FileHash`) по подписанным SHA256SUMS и версию/архитектуру manifest. Записать URL, размер и hash. Сначала `tar -tf` только просматривает содержимое; не распаковывать сотни МБ вручную и не делать VHD export. Если установленный WSL не принимает этот формат, обновление WSL требует отдельного согласования; не подменять образ случайным GitHub-архивом.

В PowerShell задать реальные пути (пример без личных данных):

```powershell
$Distro = 'AlmatyAccess'
$InstallDir = 'C:\WSL\AlmatyAccess'
$Image = 'C:\Downloads\ubuntu-24.04-wsl-amd64.wsl'
wsl --import $Distro $InstallDir $Image --version 2
wsl --list --verbose
wsl --distribution $Distro --user root
```

`$Image` — имя **действительно скачанного** и проверенного tar-based WSL image; файл с таким примерным именем в раздатку не включён. Если `--import` сообщает несовместимость — остановиться на этом шаге, не использовать чужую установленную Ubuntu. Импорт описан [Microsoft](https://learn.microsoft.com/en-us/windows/wsl/use-custom-distro). Дальше команды выполняются внутри нового Linux, не в PowerShell.

```sh
cat /etc/os-release
uname -m
adduser learner
usermod -aG sudo learner
```

`learner` — пример нового пользователя этого стенда; при существовании имени сначала проверить его. Пароль вводит владелец интерактивно. Административный пользователь нужен для установки **снаружи защищённого сеанса**. Внутри будущей границы `sudo` не работает: привилегии сняты, host systemd/DBus и namespace handles недоступны.

## 3. Подготовить зависимости до закрытия interop

Из PowerShell открыть Linux пользователя: `wsl --distribution AlmatyAccess --user learner --cd ~`. Перенести **небольшую раздатку**, а не всю домашнюю папку, в Linux home через Windows путь `\\wsl.localhost\AlmatyAccess\home\learner`. Рабочий тестовый проект создать там же; `/mnt/c` не использовать как общий доступ ко всем файлам компьютера.

Выполнить опись и подготовку из [Ubuntu README](../linux/README.md): `openssh-client`, Python, bubblewrap, инструменты диагностики; штатный Linux Claude и Linux Google Chrome stable, без аккаунта. Сохранить версии и результаты проверки пакетов. Настроить [собственный сервер](../../server/README.md), ключи и user service SSH внутри WSL. Не брать ключ администратора Windows в protected home и не передавать весь Windows SSH-agent.

На этом шаге подтвердить, что WSLg доступен и существует конкретный Wayland socket: посмотреть только `XDG_RUNTIME_DIR`, `WAYLAND_DISPLAY` и тип соответствующего файла. Не выводить всё окружение. Простая GUI-проба ещё не является защищённым Chrome; вход не выполнять.

## 4. Выключить Windows interop именно в новой distro

Прочитать существующий `/etc/wsl.conf`; для новой distro адаптировать `wsl.conf.template`. Если файл появился при импорте, объединить именно нужные секции, не потерять его конфигурацию. Добавить:

```ini
[user]
default=learner
```

Шаблон включает systemd, отключает запуск Windows `.exe` и добавление Windows PATH, automount Windows-дисков и автоматическую генерацию `resolv.conf`. Эти настройки применяются только к выбранному дистрибутиву; [области действия WSL config](https://learn.microsoft.com/en-us/windows/wsl/wsl-config).

Для первого закрытого стенда после загрузки зависимостей записать собственный `/etc/resolv.conf` с `nameserver 127.0.0.1`, `options timeout:1 attempts:1`. Сначала проверить, обычный ли это файл или symlink; удалить только прежнюю ссылку `resolv.conf` после сохранения её цели в журнал, не файл-цель. Это сознательно выключает обычное разрешение имён в этой distro; SSH использует числовой IP, а proxy разрешает имена на VPS. Установка обновлений позже делается отдельным контролируемым этапом с восстановлением прежнего resolver и повторным закрытием/проверкой. Будущему protected namespace не передавать host resolver/службу resolved вообще.

Закрыть работу именно этой distro, сохранить файлы, затем из PowerShell:

```powershell
wsl --terminate AlmatyAccess
wsl --distribution AlmatyAccess --user learner --cd ~
```

Не `wsl --shutdown`: он останавливает также другие рабочие дистрибутивы. После старта проверить `/etc/wsl.conf`, PID1/systemd и фактическое отсутствие Windows executables в PATH. `appendWindowsPath=false` без `enabled=false` недостаточно.

Проверка interop должна включать попытку запуска тестового Windows executable **по абсолютному пути**, а не только `command -v`. Прежде чем отключать automount, можно в изолированную тестовую папку положить один заведомо безвредный тестовый PE executable или сохранить отдельный управляемый read-only mount к нему; после проверки убрать ровно этот mount. Попытка должна вернуть `Exec format error`/отказ, не запустить Windows-процесс. Проверить также отсутствие `/init`/WSLInterop сокетов, `wslview`, `powershell.exe`, `cmd.exe`, Windows `curl.exe` и host-exec helpers внутри будущей mount-границы. Отсутствие `/mnt/c` само по себе не доказывает запрет interop.

## 5. DNS tunneling, NAT и сеть Windows

Первый стенд — NAT. Mirrored не объявлять эквивалентным. WSL DNS tunneling может обращаться к Windows resolver без обычного UDP-пакета; поэтому пустой tcpdump не доказывает отсутствие DNS-утечки. Сначала проверить фактическое состояние и системное разрешение имён, в том числе DNS через библиотеки/API. Основание: [Microsoft WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking).

Глобальные `.wslconfig` `dnsTunneling=false`, `autoProxy=false`, `networkingMode=NAT` не записываются комплектом автоматически. На выделенной тестовой Windows, где других рабочих distro нет, владелец может согласовать именно эти три значения и необходимый restart WSL. Сохранить прежние строки, а не полную копию системы. На общей Windows сначала оценить влияние: не ломать VPN/DNS других distro. Если проверка выявляет выход через Windows DNS, Codex исправляет конкретную границу на этой машине и повторяет опыт; к входу переходят после устранения этой ошибки.

В защищённом namespace нет NIC и host resolver sockets; proxy hostname resolution происходит на VPS. Проверить попытки IPv4/IPv6 к адресу Windows gateway, localhost Windows, LAN и mirrored shortcuts. Hyper-V firewall — возможный дополнительный слой; правила VM-class WSL затрагивают другие distro и не входят в автоматическую установку. Не отключать Windows Firewall и не применять глобальные Block/Allow правила ради пробы.

## 6. Один защищённый CLI + WSLg Chrome

Сначала выполнить узкую [rootless-пробу](../linux/experimental/README.md). После неё выполнить **весь контракт полного Linux-сеанса**, раздел5 [Ubuntu README](../linux/README.md). Результат probe не разрешает login. Исполняемый [Start-Almaty.ps1](Start-Almaty.ps1) запускает общий Linux-сеанс. Его `-Plan` не запускает даже WSL. `-Experimental` больше не требуется; старый путь `experimental/Start-Almaty-Experimental.ps1` перенаправляет сюда. Runtime проверяется на этой Windows в процессе настройки.

Дополнения WSL:

- Монтировать адресно только реальный Wayland socket WSLg; не весь `/mnt/wslg`, `/mnt/c`, `/run` или `/run/user`. Использовать Linux Chrome `--ozone-platform=wayland`, собственный профиль и штатную Chromium sandbox. Если понадобился дополнительный GUI-ресурс, сначала определить его назначение и влияние; не выдавать широкий host-exec канал ради окна.
- Chrome и CLI стартуют **соседями в одном netns**: раздельные независимые `bwrap` создадут разные loopback и сломают callback. Встроенный Claude Bash-sandbox может запрещать нужные Chrome user namespaces; запускать весь браузер через Bash tool для обхода не надо.
- Локальный OAuth callback доступен лишь на loopback того же namespace. Внешние direct URL запрещены. При ручном flow скопировать ссылку через `c`, открыть в защищённом Linux Chrome, вставить показанный код обратно. Windows Chrome/Edge для входа не использовать.
- Если clipboard внутри границы недоступен, использовать обычное выделение текста и ручную вставку через терминал. Не включать interop/`wslview`/`powershell.exe` и не открывать широкий desktop portal ради удобства clipboard.
- Ошибка `No usable sandbox`, AppArmor/seccomp или отсутствие окна — блокер WSLg-адаптера. Не применять `--no-sandbox`/`--disable-setuid-sandbox`. Альтернативный браузер/VM требует нового проверяемого решения, не тихой подмены.

## 7. Приёмка Windows

Пройти всю таблицу Ubuntu, затем дополнительно:

| Проверка | Условие приёмки |
|---|---|
| `wsl --list --verbose` | Только выбранный стенд используется, именно WSL2; чужая distro не изменена |
| Запуск Windows PE по абсолютному пути из protected child | Отказ; в Windows не возник процесс вне границы |
| PowerShell/CMD/curl.exe/обычный browser helper | Нет автоматического host-exec; не спасает Windows PATH |
| DNS tunneling/system resolver | Независимая проверка Windows DNS и controlled endpoint, не один tcpdump |
| WSLg fresh Chrome, renderer, WebRTC/UDP/QUIC/IPv6 | Нет прямого выхода; native Chrome sandbox включена |
| OAuth/renewal/logout/manual code | Всё в одном защищённом Linux сеансе |
| `wsl --terminate AlmatyAccess`, reboot Windows | До повторной проверки границы запросов нет; нет незаметного Windows fallback |
| Вторая рабочая distro | Её сеть/данные/настройки сохранены; исходный default не заменён |
| Файл проекта и clipboard | Файл читается/сохраняется внутри выбранной папки; нет доступа ко всему Windows home |
| Панель/ярлык | Вызывает защищённый supervisor именно AlmatyAccess; сырой `wsl ... claude` не считается launcher |

Сохранить версии Windows build/WSL kernel/WSLg/Ubuntu/Chrome/CLI, протокол, время, safe evidence. Статус панели отдельно показывает транспорт, proxy, API и свежую проверку изоляции. Agentbelt полного порта Windows не имеет; разрешена отдельная простая панель. Обычный `Start-Almaty.ps1` выполняет запуск и реальные проверки; автоматического обхода отказов нет.

## Отключение и откат

1. Закрыть сеанс, из Linux `systemctl --user disable --now almaty-tunnel.service`; из PowerShell при необходимости `wsl --terminate AlmatyAccess`. Другие distro не трогать.
2. Внутри нового стенда восстановить **только изменённые** значения `wsl.conf`/resolver из описи. Если согласованно менялся `.wslconfig`, восстановить его конкретные прежние строки; изменение вступит после отдельно согласованного restart WSL. Не сбрасывать весь файл и Windows Firewall.
3. Перенести созданные пользователем рабочие файлы из distro адресно, сохранить Git; не создавать полный экспорт/клон VHD как «страховку» по умолчанию. Секреты не включать в архив поддержки.
4. Удаление distro — отдельное необратимое действие владельца: `wsl --unregister AlmatyAccess` уничтожает **все её файлы**. Никогда не подставлять чужое имя, не выполнять автоматически, не удалять другие Ubuntu и не выключать весь WSL-компонент.

Отсутствие Windows-стенда при сборке прямо записано в статусе 1.0.0. Это граница сборочных доказательств; документация и shell-проверка на Mac не подтверждают runtime Windows. Установка завершается по результатам получателя на его машине.


## Настроить запуск и открыть его завтра

Все параметры ниже — **проверенные собственные** Linux-ресурсы. Codex сначала настраивает зависимости/бинарники по [Ubuntu README](../linux/README.md#подготовка-бинарников-и-повторяемый-запуск), получает настоящий путь root-owned ELF Claude и его SHA256, проверяет host-key fingerprint через независимую консоль своего VPS. Пароль не передаётся аргументом.

Сначала из PowerShell проверить синтаксис просмотренного файла штатным parser. Не выключать глобальный ExecutionPolicy. Если политика организации не разрешает скрипты, выбрать допустимый ею способ запуска, не обходить запрет.

```powershell
$Tokens = $null
$ParseErrors = $null
[System.Management.Automation.Language.Parser]::ParseFile(
  (Resolve-Path .\Start-Almaty.ps1), [ref]$Tokens, [ref]$ParseErrors) | Out-Null
$ParseErrors
```

Для плана без запуска WSL:

```powershell
.\Start-Almaty.ps1 -Plan -Distro AlmatyAccess -LinuxUser learner `
  -LinuxLauncher /home/learner/almaty-kit/platforms/linux/experimental/session_launcher.py `
  -Project /home/learner/work/test-project -State /home/learner/.local/state/almaty-session `
  -Cli /проверенный/настоящий/путь/claude -CliSha256 $CliHash `
  -ChromeDir /opt/google/chrome `
  -SshSocket /home/learner/.config/almaty-access/proxy.sock -SshPid $SshProcessId `
  -ServerIp $VpsIp -KnownHosts /home/learner/.config/almaty-access/known_hosts `
  -HostKeySha256 $HostFingerprint -AuthFile /home/learner/.config/almaty-access/proxy.auth `
  -WaylandSocket /фактический/путь/wayland-0 -Apps both
```

Примеры путей и переменные Codex заменяет реальными значениями после описи. Для планирования PID — текущее число своей SSH-службы; `-Plan` сам не вызывает `wsl.exe`. Для запуска повторить команду **без `-Plan`** в интерактивном Windows Terminal. Сначала появляются Linux Chrome и CLI в общей границе; это начало проверок, не окончательный результат.

В личном ежедневном `.ps1` перед вызовом `Start-Almaty.ps1` заново получать PID:

```powershell
$PidText = & wsl.exe --distribution AlmatyAccess --user learner --exec /usr/bin/systemctl --user show almaty-tunnel.service --property=MainPID --value
if ($LASTEXITCODE -ne 0) { throw 'Не удалось получить PID своей SSH-службы' }
$SshProcessId = 0
if (-not [int]::TryParse(($PidText -join '').Trim(), [ref]$SshProcessId) -or $SshProcessId -le 1) {
    throw 'Сначала восстанови almaty-tunnel.service в выбранной distro'
}
```

Далее идёт сохранённая полная команда с `-SshPid $SshProcessId`, без `-Plan`. Поля путей/hash/IP/fingerprint хранятся локально без секретов. PID не сохраняется как константа. Wrapper проверяет выбранную distro; Linux engine проверяет SSH executable/argv/socket/host key и ловит смену PID/socket. Старый сеанс после рестарта SSH закрывается; новый ярлык получает новое состояние.

Codex создаёт обычный ярлык Windows Terminal на этот личный `.ps1` и проверяет его запуск. Не запускать без терминала: fd0–2 должны быть TTY. Нельзя подменять ярлык командой `wsl ... claude`, Windows Chrome/Edge или файлом, который лишь печатает статус.

После обязательных сетевых проверок владелец входит через этот Linux Chrome и получает **реальный ответ Claude в веб-чате**. Затем авторизация CLI через тот же браузер и локальная задача `hello.txt` → `answer.txt` в `/workspace`. Эти файлы находятся в выбранном Linux-проекте на этом компьютере, доступны владельцу через `\\wsl.localhost\AlmatyAccess\home\learner\work`. Закрыть общий сеанс, снова открыть личный ярлык, убедиться в сохранении веб-чата и продолжении CLI-сессии. `auth_route`, ответ веб-чата, локальная задача и оба resume завершают настройку.
