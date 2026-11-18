# Ubuntu 24.04 LTS x64 — локальный Claude и отдельный Chrome

Версия **1.0.0 — комплект с настройкой вместе с Codex на компьютере получателя**. Собран исполняемый маршрут: user service SSH, bwrap-сеанс, relay socat, локальный Claude Code и отдельный Google Chrome. На сборочном Mac native Linux runtime не проверялся; это список проверок на твоём Ubuntu, а не запрет продолжать установку. Codex устраняет обнаруженные несовместимости и повторяет соответствующую проверку. Fedora, Debian, Arch, ARM64 и headless browser здесь не заявлены.

Финиш: реальный ответ Claude в отдельном Chrome, реальная задача Claude Code с локальным файлом в терминале, повторное открытие обоих приложений с сохранённым входом/историей. Наличие окна, успешный curl или код407 сами по себе не являются финишем.

## Внешняя граница всего сеанса

```text
Обычная среда Ubuntu                  Закрытая среда сеанса
SSH → свой VPS                       Claude + дочерние tools/hooks/MCP
  ↑                                  Chrome + renderer/service workers
файловый proxy.sock ← Unix relay ←    127.0.0.1:48921
                                     только lo; нет NIC/veth/default route
```

CLI и браузер работают **целиком внутри одного netns** (сетевого пространства ядра). Браузер и CLI — соседние процессы общего supervisor, а не Chrome внутри встроенного Bash-sandbox Claude. Удаление proxy env не создаёт сеть: внешнего интерфейса нет. SSH остаётся снаружи и доступен только как файловый Unix-сокет, проксирующий удалённый TCP/48921. Для обычного HTTP-клиента внутри нужен TCP→Unix relay. Смерть relay/SSH даёт отказ, а не direct.

Network namespace не скрывает файловые Unix-сокеты. Поэтому одновременно необходимы mount/PID/IPC/user-границы: нет host DBus/portal, Docker/Podman socket, `SSH_AUTH_SOCK`, чужого `/run/user`, host process namespace, `sudo`, привилегий `CAP_NET_ADMIN`/`CAP_SYS_ADMIN`, унаследованных сетевых FD. Рабочая папка и собственное состояние монтируются адресно. Встроенный `/sandbox` Claude может добавить защиту команд, но не заменяет эту общую границу. Основание: [Linux network_namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html) и [systemd.exec](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html).

## 1. Опись и необходимые компоненты

Из распакованного комплекта выполнить `python3 kit.py doctor`, затем:

```sh
cat /etc/os-release
uname -m
uname -r
python3 --version
ssh -V
systemctl --user status --no-pager
command -v claude
command -v google-chrome-stable
command -v bwrap
```

Записать версии. До изменения проверить имеющиеся `~/.config/almaty-access`, unit `almaty-tunnel.service`, существующий Chrome-профиль и файл входа Claude **по именам, без значений**. Не переносить Keychain-очистку Mac на Linux: хранилище входа сначала определяется по реальной версии клиента и [authentication docs](https://code.claude.com/docs/en/authentication). MCP, hooks, проекты и историю не удалять.

Транспорт требует `openssh-client`, `python3`; лаборатория — `bubblewrap`, `socat`, для внешнего наблюдения `iproute2` и `tcpdump`. Установка пакетов — отдельное согласованное действие `apt-get -s install ...`, затем `apt-get install ...` после просмотра. Claude и Chrome устанавливаются штатно из официальных источников **до защищённого сеанса**, но без входа. Бинарники доступны внутри read-only. Нельзя разрешать весь host FS ради первого запуска или отключать AppArmor глобально.

## 2. Подготовка локальной конфигурации

Сначала [свой VPS](../../server/README.md): два разных SSH-ключа, restricted user `almaty-tunnel`, loopback gost, `client` + собственный пароль в `proxy.auth`, verified host key. Локальный приватный каталог `~/.config/almaty-access`, права 700; ключ, auth и known_hosts — 600.

`kit.py prepare` на Linux/WSL готовит `deployment.json` и `ssh_config` с Unix-forward в новой папке. После просмотра агент устанавливает ssh_config600 в собственный `~/.config/almaty-access`. Unit вызывает `ssh -F "%h/.config/almaty-access/ssh_config" -NT almaty-access`; `%h` раскрывается systemd в HOME пользователя. При нестандартном CONFIG_DIR адаптировать аргумент с systemd-экранированием: `%` пользовательского пути требует `%%`, кавычки и обратный слеш имеют собственное escaping. OpenSSH-пути внутри ssh_config уже заключены в нужные кавычки генератором. Не использовать shell `eval`/слепую замену. Неиспользованные маркеры — ошибка. Длина пути Unix socket ограничена ОС; предпочтителен короткий CONFIG_DIR. Прототип отвергает путь длиннее 100 байт.

Проверить подготовленный unit **до** установки:

```sh
systemd-analyze --user verify /путь/к/подготовленному/almaty-tunnel.service
```

Нельзя проверять исходный `.template` и выдавать это за проверку готовых путей. Подготовленный unit установить 600 в `~/.config/systemd/user/almaty-tunnel.service`; чужой существующий unit не перезаписывать. На стороне клиента SSH создаёт файловый сокет, серверу запрашивается TCP `127.0.0.1:48921`, поэтому серверный `PermitOpen` продолжает ограничивать назначение.

## 3. Постоянный SSH-транспорт

Перед запуском убедиться, что `proxy.sock` отсутствует либо принадлежит остановленной **своей** службе. Шаблон включает `StreamLocalBindUnlink=yes` для восстановления после аварии; приватный каталог и проверка владельца обязательны. Не разрешать приложению подменять каталог транспорта в рабочем сеансе.

```sh
systemctl --user daemon-reload
systemctl --user enable --now almaty-tunnel.service
systemctl --user status almaty-tunnel.service --no-pager
systemctl --user show almaty-tunnel.service -p MainPID -p ExecStart
stat -c '%a %U %F' "$HOME/.config/almaty-access/proxy.sock"
ss -lxnp
```

Ожидается socket, владелец текущий пользователь, права 600; PID соответствует именно SSH unit. Ни одного TCP listener на `0.0.0.0` не создаётся. Unit стартует при входе пользователя; `linger` не включён. Автостарт до пользовательского входа требует отдельного решения и проверки, а на WSL — ещё проверки systemd/user-session. Пустой/неверный host key, locked key, занятый socket дают отказ. `journalctl --user -u almaty-tunnel.service -n 30 --no-pager` читать локально, без дампа окружения.

## 4. Первая проверка границы без входа

Следовать [experimental/README](experimental/README.md). Скрипт создаёт временную внешнюю границу через bubblewrap и запускает только фиксированный `probe_netns.py`. Передать один собственный SSH socket и контролируемые публичные IPv4/IPv6 endpoint. Он проверяет отдельный netns, только `lo`, нулевые capabilities, отказ direct TCP/UDP/DNS-портов и потомка с `NO_PROXY=*`, затем ответ407 через `TCP → Unix → SSH → gost`.

Если user namespaces запрещены политикой Ubuntu/AppArmor, проба должна отказать. Не отключать политику и не выполнять тот же Python напрямую. Возможный дальнейший путь — root-owned systemd service с `User=<отдельный-непривилегированный-пользователь>`, `PrivateNetwork=yes`, `NoNewPrivileges=yes`, пустым `CapabilityBoundingSet` и адресными bind-mount. Это другой адаптер, **такого launcher пока нет в комплекте**. Codex может разработать этот адаптер на машине получателя с адресными разрешениями и повторной проверкой; до исправления не запускать приложения вне границы. `PrivateNetwork=yes` сам по себе не закрывает host Unix sockets.

## 5. Запустить общий сеанс CLI и Chrome

Исполняемый маршрут — [session_launcher.py и точный запуск](experimental/README.md). Название папки experimental сохранено для совместимости путей; обычный запуск не требует отдельного experimental-флага. Скрипт создаёт общий bwrap-сеанс, relay socat, запускает CLI/Chrome и прекращает сеанс при смене транспорта. `--plan` строит план без запуска. Нативные проверки ниже выполняются на этой машине. Узкая probe проверяет только часть границы; вслед за ней запускается и проверяется весь сеанс.

1. **Проверить supervisor.** Внешний root-owned/неизменяемый launcher создаёт общие netns/mount/PID/IPC-границы, закрывает FD>2 и проверяет FD0–2, затем сбрасывает привилегии. `lo` активен, иных интерфейсов и маршрутов нет; capabilities нулевые. При несовпадении завершение до любого child. Для rootless варианта проверить соответствующую политику user namespaces и отсутствие доступа к host namespace handles. Не использовать именованный netns с свободным `sudo ip netns exec` для агента.
2. **Проверить открытые файлы.** Внутри read-only `/usr` и нужные библиотеки/CA; новый `/proc`, `/dev`, `/tmp`, `/run`; собственный постоянный home состояния и один выбранный `project → /workspace`. Не bind-mount весь `/`, host `/run`, весь home или `/var/run`. Проверить сокеты в доступных папках. `proxy.auth` отдельным файлом600; ключ администратора и туннеля внутри отсутствует. Launcher/transport доступны только read-only либо недоступны.
3. **Испытать relay socat.** Он слушает `127.0.0.1:48921` **внутри** namespace, открывает только один разрешённый Unix socket и не принимает команды/параметры назначения. Должен поддерживать несколько CONNECT, half-close, timeouts, WebSocket и большие ответы, не писать заголовки/тела/пароли в журналы. Relay в старом probe_netns.py рассчитан на одну пробу; новый session_launcher использует socat для нескольких соединений, его CONNECT/half-close нужно испытать. На замене inode SSH socket завершить сеанс/предложить его открыть снова; не подменять это direct route.
4. **Проверить запуск CLI и browser рядом.** До старта supervisor проверяет loopback relay, правильный SSH PID/host key, authenticated IP своего VPS и состояние границы. Секрет считывается внутри из файла и экспортируется только в proxy env CLI; argv его не содержит. Штатная Chrome sandbox остаётся включённой. Для браузера использовать свой профиль и фиксированный HTTP proxy; пароль вводится владельцем в proxy dialog либо отдельным испытанным credential broker, не URL/argv.
5. **Проверить передачу только Wayland.** Для Ubuntu desktop предпочтителен один адресно смонтированный Wayland socket (проверенный путь `XDG_RUNTIME_DIR/WAYLAND_DISPLAY`), а не весь runtime directory; GPU и audio не подключать, пока не нужны. Chrome запускается с `--ozone-platform=wayland`. Не передавать desktop DBus/portal, которые умеют открыть host browser. Сочетание сетевой границы и штатной Chromium sandbox нужно проверить на конкретных AppArmor/seccomp/user namespaces. Ошибка запуска — стоп; `--no-sandbox` и `--disable-setuid-sandbox` запрещены.
6. **Проверить callback внутри.** Браузер и CLI в **том же** netns. Точные bypass только `localhost`, `127.0.0.1`, `[::1]`, без LAN/IP ranges; все внешние URL идут через proxy. Resolver exceptions только для этих имён. Проверить, что локальный callback принадлежит именно CLI, а не другому listener. Резерв: клавиша `c`, ссылка в защищённый Chrome, отображённый код обратно в терминал. Обычный host browser не запускать.
7. **Принять удобный запуск после сетевых испытаний.** Один ярлык создаёт целый сеанс и выполняет реальные проверки при каждом старте; закрытие его терминала/сеанса останавливает только его. После успешной настройки ярлык сохраняется для ежедневной работы. Раздельно: SSH, proxy auth, IP VPS, API reachability, fresh isolation checks. Файл отчёта не должен приниматься как разрешение только по пользовательской галочке. Устаревшая/чужая версия отчёта требует новых проверок. Agentbelt здесь не портирован; допустима отдельная простая локальная панель.

## 6. Проверки на этой машине и реальный результат

У каждого опыта есть версия ОС/ядра/bwrap/CLI/Chrome, kit version, время, действие, ожидаемый и наблюдаемый результат. Тестировать CLI и браузер независимо, с реальным внешним наблюдателем (контролируемый endpoint и захват пакетов на интерфейсе хоста). Не публиковать pcap/headers с токенами.

| Опыт | Что должно произойти |
|---|---|
| Изнутри `ip -brief link`, routes IPv4/IPv6, `/proc/self/status` | Только lo; нет внешнего маршрута; CapEff=0; это другой netns |
| Прямой TCP IPv4/IPv6, LAN, URL IP literal | Отказ, даже при полностью пустом proxy env и `NO_PROXY=*` |
| DNS UDP/TCP53, системный resolver, DoH | Нет прямой отправки; DNS через HTTP proxy обслуживает VPS; DoH возможен лишь через разрешённый proxy |
| UDP/QUIC/WebRTC | Нет прямого внешнего UDP, в том числе IPv6 |
| Child shell, Python, Node, git, hook, MCP, updater | Та же граница; не доступны host socket/host-exec, sudo/namespace escape |
| Чужой/занятый socket или TCP48921 внутри | Launcher останавливается, не доверяет любому listener |
| Остановлен relay/SSH/gost, неверный или пустой пароль | Все новые и текущие сетевые операции отказывают без direct; CLI может сохранить локальный файл |
| Возобновление SSH с новым socket inode | Требуется безопасное переоткрытие сеанса; не бесконечная ложная зелёная плашка |
| Browser | Новый профиль, свежий HTTPS/WebSocket, SW/background, перезапуск, вторая копия; WebRTC/DNS/IPv6 наблюдаются |
| Auth | Manual flow, callback, renewal, logout/login в защищённой среде |
| Wi-Fi/VPN, sleep/wake, reboot | До защиты запросов нет; восстановление даёт IP того же своего VPS |
| Новые версии Chrome/CLI | Результаты прежней версии не переносятся автоматически |

## Отключение и откат

Для согласованного опыта остановить только `systemctl --user stop almaty-tunnel.service`, восстановить `start`. Убивать SSH PID бессмысленно для длительного теста: Restart его поднимет. Production сеанс при возврате socket может требовать перезапуска.

Для отключения автозапуска: `systemctl --user disable --now almaty-tunnel.service`. По описи удалить/переместить **только свой** unit, затем `systemctl --user daemon-reload`. Убедиться по PID, что socket больше не обслуживается; удалить только свой `proxy.sock`, если остался после остановки. Ключи/auth/браузерный профиль не удалять автоматически.

Лабораторный bwrap умирает вместе с тестом, отдельной сетевой конфигурации не оставляет. Если в будущем создан системный адаптер, откат по точному inventory его unit/launcher/mount, без `nft flush ruleset`, `iptables -F`, удаления всех netns и глобального рестарта desktop. Обычная сеть Ubuntu не должна зависеть от этого комплекта.

До исполнения разделов 5–6 реальная готовность остаётся `not-tested/blocked`; ни синтаксис unit, ни probe407, ни успешный IP сами по себе её не меняют.

## Подготовка бинарников и повторяемый запуск

Перед первым сеансом поставь `openssh-client`, `python3`, `bubblewrap`, `socat`, `iproute2`, `tcpdump`, `curl`, `gnupg` штатным пакетным менеджером после просмотра списка изменений. Chrome — официальный Linux `.deb`, не snap/Windows Chrome. Проверь `/opt/google/chrome/chrome`, владельца root и состав дерева. Engine отказывает, если в нём найдены ссылки/специальные файлы: Codex разбирает конкретный пакет и делает точное исправление валидатора, не удаляет файлы Chrome вслепую и не открывает весь host FS.

Для Claude Code выбери официальный подписанный **apt-репозиторий** из [инструкции Anthropic](https://code.claude.com/docs/en/setup#install-with-linux-package-managers): проверить ключ → зарегистрировать stable repository → установить пакет. Это даёт системную установку вместо обязательного ручного переноса бинарника из HOME. До входа определить настоящий путь `readlink -f "$(command -v claude)"`, проверить ELF, root-владельца, отсутствие group/world write и SHA256 файла. Сверить источник пакета/подпись; собственный hash не удостоверяет происхождение. В `--cli` передаётся реальный бинарник, не ссылка/обёртка. Автоматическое обновление изнутри защищённого HOME не настраивать; системные обновления выполняются отдельно, затем сверяются новый hash и протокол.

После успешной команды из [технического запуска](experimental/README.md) Codex сохраняет маленький личный `start-almaty` вне раздатки. В нём остаются проверенные абсолютные пути, IP, hash и fingerprint; **нет пароля или статического PID**. При каждом запуске перед аргументами engine:

```sh
ssh_pid=$(/usr/bin/systemctl --user show almaty-tunnel.service --property=MainPID --value)
case "$ssh_pid" in ''|*[!0-9]*) echo 'Нет PID своей службы SSH' >&2; exit 78;; esac
test "$ssh_pid" -gt 1 || { echo 'Сначала восстанови almaty-tunnel.service' >&2; exit 78; }
```

Дальше используется сохранённая команда `exec /usr/bin/python3 -I -B /свой/путь/session_launcher.py ... --ssh-pid "$ssh_pid"`. Многоточие заменяется всеми реальными аргументами из успешно проверенного запуска; пользователь не исполняет шаблон с многоточием. Не применять `eval`. Этот fresh PID — только кандидат: engine проверяет executable, argv, ключ, socket и время процесса. После рестарта SSH весь старый сеанс закрывается; новый запуск получает новый PID/socket.

Для ярлыка рабочего стола указать этот скрипт и `Terminal=true`: engine требует терминальные fd0–2. Права файла 700. Проверить реальный запуск ярлыком, а не только команду из терминала. Никаких сырых `claude`/обычного Chrome в ярлыке.

После успешных обязательных сетевых проверок своей машины владелец входит в Claude в этом Chrome и отправляет короткий запрос: **должен появиться ответ модели в веб-чате**. Затем ручной вход Claude Code через тот же Chrome и задача прочитать `hello.txt`, создать `answer.txt` в `/workspace`. Подтвердить эти файлы в выбранной папке Ubuntu. Закрыть сеанс, снова открыть ярлыком, проверить историю веб-чата и продолжение CLI-сессии. Только после этих результатов записать установку получателя завершённой. Неизвестная проверка означает следующий конкретный опыт/исправление на этой машине, а не ожидание компьютера автора.
