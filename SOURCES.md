# Источники и версии

Проверка: 6 ноября 2026. Ссылки на документацию не являются результатами испытаний комплекта. Цены, интерфейсы и версии повторно сверяются перед реальной установкой.

| Для чего | Источник |
|---|---|
| Codex и первый запуск | [Официальный CLI](https://learn.chatgpt.com/docs/codex/cli), [Windows](https://learn.chatgpt.com/docs/app/windows) |
| Python | [Загрузка](https://www.python.org/downloads/) |
| Провайдер / кабинет | [Serverspace](https://serverspace.kz/), [кабинет](https://my.serverspace.kz/) |
| Параметры VPS / цена | [Linux VPS](https://serverspace.kz/services/vps-server/linux/), [калькулятор](https://serverspace.kz/conditions/price/) |
| Docker на сервере | [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) |
| GOST v2 | [Документация](https://v2.gost.run/en/), [исходники](https://github.com/ginuerzh/gost) — эталон 2.11.5 |
| OpenSSH | [ssh](https://man.openbsd.org/ssh), [sshd_config](https://man.openbsd.org/sshd_config) |
| Claude Code | [Установка](https://code.claude.com/docs/en/setup), [прокси](https://code.claude.com/docs/en/network-config), [вход](https://code.claude.com/docs/en/authentication) |
| Настройки Claude | [Переменные](https://code.claude.com/docs/en/env-vars), [настройки](https://code.claude.com/docs/en/settings), [область sandbox](https://code.claude.com/docs/en/sandboxing) |
| Проблемы входа | [Официальная помощь](https://support.claude.com/en/articles/14552646-troubleshoot-claude-code-installation-and-authentication) |
| Chromium | [Proxy](https://chromium.googlesource.com/chromium/src/+/HEAD/net/docs/proxy.md), [Linux sandbox](https://chromium.googlesource.com/chromium/src/+/HEAD/sandbox/linux/README.md) |
| Linux | [Network namespaces](https://man7.org/linux/man-pages/man7/network_namespaces.7.html), [systemd.exec](https://man7.org/linux/man-pages/man5/systemd.exec.5.html), [nftables](https://www.netfilter.org/projects/nftables/manpage.html) |
| WSL2 | [Установка](https://learn.microsoft.com/en-us/windows/wsl/install), [конфигурация](https://learn.microsoft.com/en-us/windows/wsl/wsl-config), [сеть](https://learn.microsoft.com/en-us/windows/wsl/networking), [WSLg](https://learn.microsoft.com/en-us/windows/wsl/tutorials/gui-apps) |
| Windows firewall | [Правила](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules), [Hyper-V firewall](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/hyper-v-firewall) |
| Google Chrome | [Официальная установка](https://www.google.com/chrome/) |
| Аккаунт Claude / тариф | [Веб-приложение](https://claude.ai/), [тарифы](https://claude.com/pricing) — проверять условия до оплаты |
| iTerm2 | [Официальный сайт](https://iterm2.com/) |
| Agentbelt | [Репозиторий](https://github.com/vakovalskii/agentbelt), [зафиксированный proxy-гайд](https://github.com/vakovalskii/agentbelt/blob/7d342f351d90801efaaa869b48da13a0b79cc33b/docs/proxies.md) |

Исходный опыт macOS: Claude CLI 2.1.312, Agentbelt commit `7d342f351d90801efaaa869b48da13a0b79cc33b`, gost 2.11.5, Ubuntu 24.04.4. Эти номера обозначают изученный эталон, не автоматически рекомендуемые навсегда версии. Комплект не включает чужие бинарники, историю автора, его учётные данные или архивы.

Agentbelt связан с iTerm2/macOS. Его необязательное использование не означает порт на Windows/Linux. Он распространяется под MIT, Copyright 2026 Valerii Kovalskii; при копировании/модификации исходников сохранить полное уведомление из upstream LICENSE. Установщики и программы остальных поставщиков получают по их собственным лицензиям; подписки не входят в комплект.

Публичные исходные обсуждения: [neuraldeep/2347](https://t.me/neuraldeep/2347), [countwithsasha/819](https://t.me/countwithsasha/819). Они объясняют происхождение идеи. Гипотезы из постов не являются техническими гарантиями. Тексты постов, чужие аккаунты и платёжные рецепты в выдачу не скопированы.

Выпуск 1.0.0: комплект для настройки с агентом до веб-чата и CLI; runtime Windows/Linux проверяется получателем. Версия выпуска не означает испытание на всех ОС. На Mac воспроизводится fixed-proxy Chrome и отдельная внешняя граница CLI.
