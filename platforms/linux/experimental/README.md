# Технический запуск Ubuntu/WSL2: диагностическая проба и рабочий сеанс

`probe_netns.py` запускает только фиксированную диагностику. Он не принимает произвольные команды, не читает proxy.auth/аккаунты/проекты и не может открыть Claude/Chrome. По умолчанию код 78. Даже результат `passed: true` означает только успех узкой проверки, всегда `production_ready: false`.

Стена: bubblewrap создаёт новый user/network/PID/mount/IPC namespace, оставляет только `lo`, сбрасывает capabilities и не монтирует домашнюю папку, `/run/user`, Docker socket или desktop DBus. Единственный файловый Unix socket — адресно переданный SSH forward. `/usr` доступен read-only для Python и библиотек. Библиотека Python поднимает временный TCP→Unix relay внутри namespace, отправляет запрос без пароля и требует ответ proxy407. После завершения процесса listener/namespace исчезают; хостовый firewall не меняется.

На выделенной Ubuntu 24.04 x64 после [настройки транспорта](../README.md):

```sh
python3 probe_netns.py --experimental-probe \
  --ssh-socket "$HOME/.config/almaty-access/proxy.sock" \
  --ipv4 <IPv4-своего-контрольного-endpoint> \
  --ipv6 <IPv6-своего-контрольного-endpoint> --port 443
```

Угловые скобки — объяснение, не буквальная shell-команда: Codex подставляет реальные контролируемые публичные адреса. До опыта **снаружи** подтвердить, что endpoint доступен по IPv4 и IPv6 и порт слушает. Иначе отрицательный результат не проверяет защиту. Запросы UDP и DNS TCP/UDP53 направлены тем же контролируемым адресам; endpoint должен уметь наблюдать их. Незнакомый чужой IP не использовать как стенд.

Предпосылки: обычный пользователь, `python3`, `bubblewrap`, работоспособные user namespaces по штатной политике Ubuntu, уже поднятая отдельная SSH-служба. Если AppArmor/политика запрещает user namespace, скрипт завершается с ошибкой. **Не отключать AppArmor, не менять sysctl глобально и не запускать через sudo ради зелёного теста.** На такой машине нужен отдельно проверяемый системный launcher с `PrivateNetwork`, которого в комплекте пока нет; Codex может реализовать его адресно на этой машине и повторить проверки.

Ожидается `boundary:true`, interfaces только `lo`, все `direct.*.blocked:true`, `child_direct_blocked:true`, `proxy_407_via_tcp_unix_ssh:true`. UDP send без ошибки означает провал даже если сервер ничего не получил. Остановка SSH даёт ожидаемый провал proxy407, но прямые тесты остаются запрещёнными. Это отрицательная проверка; скрипт тогда возвращает 1, а не зелёную готовность.

Параллельно контролировать сеть снаружи namespace и журналы собственного endpoint. Не считать этот тест доказательством системного DNS, WSL DNS tunneling, Chrome sandbox, WebRTC, GUI, OAuth, долгих соединений и сохранения границы у произвольных hooks/MCP: их здесь нет. Прототип не испытан на Ubuntu/WSL в ходе сборки на Mac.

Особенность SSH restart: файловый Unix socket, bind-mounted в уже созданный namespace, может остаться ссылкой на старый inode. После перезапуска SSH **перезапусти тест**; это ожидаемый закрытый отказ, не повод добавить второй сетевой маршрут. session_launcher.py закрывает старый сеанс при замене сокета; запусти его снова с актуальным PID своей службы.

Откат теста: дождаться его завершения/`Ctrl+C`. Если остался процесс, завершить только его PID из запуска, не все `bwrap` или `python3`. Туннель отключается отдельно по README. Никаких именованных netns, firewall rules или системных файлов этот скрипт не создаёт.

## Общий сеанс Claude Code и Google Chrome — версия 1.0.0

`session_launcher.py` запускает **CLI + Chrome + socat внутри одного bwrap**. Папка experimental сохраняет прежний путь; `--experimental` теперь необязательный устаревший флаг. Версия 1.0.0 означает готовый маршрут настройки с Codex, а не доказанную совместимость со всеми компьютерами. На Ubuntu/WSL сборочный runtime не проверен: получатель и его Codex выполняют проверки, исправляют конкретные несовместимости и доходят до ответа веб-чата, локальной задачи CLI и повторного открытия обоих приложений.

Файлы не устанавливают WSL, пакеты, SSH service или firewall. Это обычный этап заказанной настройки получателя; отдельное разрешение автора на запуск не нужно. Runtime открывает HTTPS `api.ipify.org` через authenticated proxy перед стартом приложений; браузер может выполнять фоновые запросы. `--plan`/`--dry-run` этого не делает и не читает секреты.

### Предпосылки до запуска

1. Ubuntu **24.04 x64**, обычный пользователь, rootless bubblewrap и разрешённые штатной политикой user namespaces. Системные `bwrap`, Python 3, `socat`, OpenSSH — root-owned, без setuid. Не отключать AppArmor/защиту ОС ради прохождения.
2. **Отдельный** проект без symlink, hardlink, socket, FIFO и device; не весь HOME. Launcher консервативно откажет при таких объектах, недоступном для описи подкаталоге и при описи свыше 200 000 объектов. Недоступные каталоги не пропускаются молча. Это ограничение стенда, не команда удалить мешающие файлы. Проект передаётся read-write: CLI реально может его менять.
3. Новый **ещё не существующий** путь state вне проекта и раздатки; существующий родитель принадлежит пользователю и не допускает записи группы/других. Только после всех предусловий launcher создаёт state с правами 700 и пустой постоянный `home`. Повторный запуск принимает только `session.json` своей схемы с тем же владельцем, project, CLI path/hash и Chrome path. Чужая/пустая существующая папка, hardlink, незавершённый state после аварии — отказ до записи и адресный разбор, не автоматическое усыновление. Одновременно работает один сеанс. Существующий чужой HOME/профиль/credentials туда не переносить.
4. Штатный Linux native Claude **ELF**, root-owned, executable, закреплён по SHA256. Установка из официального подписанного apt-репозитория описана в [основном README](../README.md#подготовка-бинарников-и-повторяемый-запуск). Источник задаётся явно; внутри он доступен read-only как `/opt/claude/claude`. npm/shell launcher или симлинк не поддерживается. SHA256 должен происходить из отдельно проверенной установки: собственное вычисление hash не удостоверяет источник программы.
5. Штатный Chrome из root-owned `/opt/google/chrome`, без group/world write и специальных файлов/симлинков в его дереве. Внутри остаётся обычная Chromium sandbox. Любая ошибка sandbox/Wayland завершает стенд; `--no-sandbox` и `--disable-setuid-sandbox` не используются.
6. Точный Wayland socket текущего владельца, обнаруженный через XDG_RUNTIME_DIR/WAYLAND_DISPLAY; в WSL это часто ссылка на `/mnt/wslg/runtime-dir/wayland-0`. Launcher разрешает ссылку в один реальный socket, проверяет тип, владельца и защищённость его родительского каталога от подмены. Режим socket 0777 допустим: это права подключения, не права замены файла. Не меняй chmod WSLg и не копируй socket. Эти варианты наблюдаются в [upstream WSL](https://github.com/microsoft/WSL/issues/11261). Передаётся только он, не каталог runtime или `/mnt/wslg`. X11, host DBus/portal, GPU/audio и Windows clipboard helpers не открываются. Для `--apps cli` Wayland необязателен; такой режим **ничего не подтверждает о браузере**.
7. Рабочий SSH **Unix socket** из user service. Нужны PID именно обслуживающего SSH, числовой IP VPS, один публичный ed25519 host key в отдельном `known_hosts` и его SHA256 fingerprint из независимой консоли провайдера. `proxy.auth` — отдельный файл 600 с `client`, пробелом, 64 hex-символами и переводом строки. Приватный SSH-ключ находится снаружи проекта/state и никогда не монтируется внутрь.
8. SSH argv должен точно соответствовать текущему `almaty-tunnel.service.template`: `/usr/bin/ssh -F /абсолютный/ssh_config -NT almaty-access`. Config генерируется `kit.py prepare` внутри Linux/WSL. Он содержит **GlobalKnownHostsFile /dev/null**, свой UserKnownHostsFile, StrictHostKeyChecking yes, запрет password/keyboard-interactive, UpdateHostKeys no и VerifyHostKeyDNS no. Launcher разбирает только точную allowlist этого config и затем сверяет эффективные параметры через локальный `ssh -G`, без подключения. Include, Match, ProxyCommand, другие forward, подстановки `${…}` и произвольные опции не принимаются. Config, изменённый после старта SSH, требует согласованного перезапуска своего service; timestamp/boot-time проверка также требует реального испытания. При ошибке не отключать pinning.
9. Runtime вызывается из отдельного интерактивного терминала: fd0–2 должны быть терминальными, не pipe/socket. Все остальные FD закрываются при запуске. Это сознательно исключает запуск через произвольный host helper. `--plan` работает без терминала и без Linux.

Для WSL дополнительно проверяется `/etc/wsl.conf`: `interop.enabled=false`, `interop.appendWindowsPath=false`, `automount.enabled=false`, `automount.mountFsTab=false`, `network.generateResolvConf=false`. На хосте не должно быть активного/сохранившегося WSLInterop entry или `WSL_INTEROP`. Внутри проверяются отсутствие `/init`, WSLInterop, Windows mounts и host sockets. Если реальная версия WSL сохраняет этот канал — стенд откажет; настройки других distro не меняются ради его запуска.

### Сначала чистый план

Агент подставляет **собственные абсолютные Linux-пути**, реально проверенные `$CLI_SHA256`, `$VPS_IP`, `$SSH_PID`, `$HOST_FINGERPRINT`. Ни одна переменная ниже не содержит пароль. Значения не угадываются. `--plan` на Mac тоже возможен: это только построение argv, файлы с такими путями могут отсутствовать.

```sh
python3 -I -B /путь/к/комплекту/platforms/linux/experimental/session_launcher.py \
  --plan --apps both \
  --project /home/learner/work/test-project \
  --state /home/learner/.local/state/almaty-experiment \
  --cli /opt/claude-pinned/claude --cli-sha256 "$CLI_SHA256" \
  --chrome-dir /opt/google/chrome \
  --ssh-socket /home/learner/.config/almaty-access/proxy.sock --ssh-pid "$SSH_PID" \
  --server-ip "$VPS_IP" \
  --known-hosts /home/learner/.config/almaty-access/known_hosts \
  --host-key-sha256 "$HOST_FINGERPRINT" \
  --auth-file /home/learner/.config/almaty-access/proxy.auth \
  --wayland-socket /run/user/1000/wayland-0
```

В JSON ожидается `production_ready:false`, `runtime_verified:false`, один `bwrap_argv`, фиксированный relay. В плане нет пароля. Команды собраны массивом argv без shell/eval; пути с shell-символами не исполняются. План не доказывает наличие файлов/SSH, права, ОС, сеть или GUI.

**Runtime:** после проверки плана повторить ту же команду без `--plan` в терминале. Не добавлять автоматический вход. Launcher проверяет host prerequisites до первой записи; создаёт только своё state; связывает socket с `/proc/<ssh-pid>/fd`, проверяет точные SSH args, host-key fingerprint и стартовое время PID. Весь runtime остаётся foreground.

Внутри `--unshare-all`: новый net/mount/PID/IPC/user namespace, только lo, нулевые capabilities и `NoNewPrivs=1`. Монтируются read-only `/usr`, выбранные CA/fonts/loader-cache, pinned CLI/Chrome и сама программа; сгенерированные passwd/hosts/resolver; выбранные project и отдельный HOME; ровно SSH socket, auth и опционально Wayland socket. Host `/home`, `/run`, `/tmp`, `/mnt`, весь `/etc`, Docker/DBus/SSH-agent не передаются. Состояние launcher/lock не находится в writable HOME ребёнка.

Сначала socat слушает `127.0.0.1:48921` внутри границы и связывает его только с `/transport/proxy.sock`. Затем authenticated HTTPS IP-check с нормальной TLS-проверкой обязан показать свой VPS. Пароль читается из файла; CLI получает его в proxy env, не argv. Окружение секретно: `env`, `ps e` и debug dumps не собирать. Браузер получает proxy без пароля в аргументах; владелец вводит proxy credentials локально в dialog. Ключей аккаунта Claude для этих проверок не требуется.

Chrome открывается в `about:blank`, CLI — в `/workspace`; они соседи одного netns, callback может работать только на его loopback. Автооткрытие внешнего host browser невозможно через переданные файлы/сокеты; вручную ссылку открывают только в этом Chrome. Сохранение полноценной browser sandbox и фактический OAuth требуют отдельной приёмки, запуск процесса их не доказывает.

При выходе CLI или Chrome закрывается весь сеанс. При смерти relay, смене socket inode/SSH PID или ошибке проверки — закрытый отказ и остановка дочерних процессов. Старый socket не переподключается скрыто, сеанс открывают заново. `Ctrl+C` останавливает только этот launcher; постоянный SSH service продолжает жить отдельно. Нет `sudo`, firewall reset или остановки чужих программ.

### Что испытано и что ещё нет

Офлайн-тесты: `python3 -B -m unittest discover -s platforms/linux/experimental -p test_session_launcher.py -v` из корня раздатки. Они проверяют gates, чистый mount/argv plan, пути и shell injection, SSH restrictions, namespace evidence/capabilities, WSL interop и отказ передать symlink проекта. Они **не запускают** bwrap, SSH, socat, браузер или сеть.

Не проверены: фактический bwrap на Ubuntu24/WSL, правильность UID mappings, **интерактивный CLI TUI/controlling TTY при `--new-session` и `start_new_session`**, native Chrome sandbox/Wayland/WSLg, ручной proxy dialog, многопоточный CONNECT/WebSocket/half-close, OAuth/callback, живые children/hooks/MCP, DNS tunneling, внешнее наблюдение IPv4/IPv6/UDP, stop/recovery и sleep/reboot. Все остаются в [матрице приёмки](../../../guides/verification.md). Становление процесса живым на 2 секунды не является доказательством Chrome sandbox; криптографическая проверка источника всех runtime-пакетов также остаётся отдельным шагом.

Стенд доверяет ОС, системным бинарникам, владельцу компьютера и Wayland compositor. Он не защищает от root/злонамеренного процесса того же владельца на хосте, который одновременно меняет исходные ресурсы. Для повторного запуска штатные ссылки Claude внутри собственного HOME (включая /home/guest/.claude/debug/latest) разрешены с переводом гостевого пути. Внешние, циклические, висячие ссылки и специальные объекты отвергаются. После аварии stale Chrome Singleton-ссылки могут потребовать адресного разбора; не удалять весь профиль. Запрет ссылок в передаваемом проекте сохраняется. Для отката закрыть стенд, сохранить свои файлы из project/state; ничего из истории не удалять автоматически.

Windows-вход: [Start-Almaty.ps1](../../windows/README.md). Старый experimental wrapper перенаправляет в тот же рабочий вход; отдельный opt-in не требуется.


Перед **каждым** запуском обнови SSH_PID из `systemctl --user show almaty-tunnel.service --property=MainPID --value`; проверь, что это число больше1. Engine отдельно проверяет процесс и socket. Статический PID в ежедневный ярлык не записывается. `HOST_FINGERPRINT`, `VPS_IP`, `CLI_SHA256` остаются подтверждёнными значениями; обновление бинарника требует нового hash, а не отключения проверки.

После сетевой проверки этого сеанса владелец выполняет login в защищённом Chrome, получает настоящий ответ в веб-чате и отдельно авторизует CLI ручным кодом. В CLI — чтение `hello.txt` и запись `answer.txt` в `/workspace`, затем повторное открытие Chrome/CLI и продолжение истории. Если приложение не запускается, Codex сохраняет конкретный отказ и исправляет адаптер здесь; не переключается на host browser или обычный CLI.
