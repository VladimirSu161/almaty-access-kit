#!/usr/bin/env python3
"""Подготовка комплекта без сетевых запросов и изменений установленных программ."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import plistlib
import re
import shutil
import sys

VERSION = '1.0.0'


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def write_new(path, data):
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data if isinstance(data, bytes) else data.encode('utf-8'))


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def doctor():
    emit({'kit_version': VERSION, 'os': platform.system(),
          'os_release': platform.release(), 'architecture': platform.machine(),
          'python': platform.python_version(),
          'tools_present': {name: bool(shutil.which(name)) for name in
                            ['ssh', 'git', 'claude', 'codex', 'systemctl', 'bwrap', 'socat']},
          'network_verified': False,
          'note': 'Только опись программ. Файлы входа не читались; сеть не проверялась.'})


def initialize(path):
    state = {'schema': 1, 'kit_version': VERSION, 'os': platform.system(),
             'stage': 'inventory', 'checks': [],
             'created_at': datetime.now(timezone.utc).isoformat(),
             'next_step': 'Прочитать SETUP.md и выполнить опись без изменений.'}
    write_new(path, json_bytes(state))
    emit({'created': str(path), 'network_verified': False})


def validate_ip(value):
    try:
        ip = ipaddress.IPv4Address(value)
    except ipaddress.AddressValueError as exc:
        raise ValueError('Укажи числовой публичный IPv4 своего VPS.') from exc
    documentation = any(ip in ipaddress.ip_network(net) for net in
                        ['192.0.2.0/24', '198.51.100.0/24', '203.0.113.0/24'])
    if not ip.is_global and not documentation or ip.is_multicast:
        raise ValueError('Нужен публичный IPv4 VPS, не адрес домашней сети или localhost.')
    return str(ip), documentation


def ssh_quote(path):
    value = str(path)
    if any(c in value for c in '\n\r\0'):
        raise ValueError('Путь содержит неподдерживаемый перевод строки.')
    # OpenSSH expands % tokens; %% means a literal percent.
    return '"' + value.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'


def prepare(server_ip, output):
    ip, example = validate_ip(server_ip)
    system = platform.system()
    if system == 'Windows':
        raise ValueError('Подготовку Windows выполняй внутри выбранного Ubuntu WSL2: python3 kit.py prepare. Native Windows HOME не подходит.')
    if system not in ('Darwin', 'Linux'):
        raise ValueError('Подготовка этой ОС не поддерживается.')
    home = Path.home()
    config = home / '.config' / 'almaty-access'
    key = config / 'tunnel_ed25519'
    deployment = {'schema': 1, 'kit_version': VERSION, 'server_ip': ip,
                  'example_address': example, 'applied': False, 'network_verified': False,
                  'config_dir': str(config), 'ssh_key': str(key),
                  'cli_binary': str(config / 'claude-native'), 'local_port': 48921,
                  'tunnel_user': 'almaty-tunnel', 'proxy_user': 'client',
                  'service_label': 'local.almaty-access.tunnel'}
    deployment['target_platform'] = 'macos' if system == 'Darwin' else 'linux_or_wsl'
    deployment['transport'] = 'loopback_tcp' if system == 'Darwin' else 'unix_socket'
    forward = ('    LocalForward 127.0.0.1:48921 127.0.0.1:48921' if system == 'Darwin'
               else '    LocalForward ' + ssh_quote(config / 'proxy.sock') + ' 127.0.0.1:48921')
    ssh = '\n'.join([
        'Host almaty-access', '    HostName ' + ip, '    User almaty-tunnel',
        '    Port 22', '    IdentityFile ' + ssh_quote(key),
        '    UserKnownHostsFile ' + ssh_quote(config / 'known_hosts'),
        '    GlobalKnownHostsFile /dev/null', '    UpdateHostKeys no',
        '    VerifyHostKeyDNS no', '    PasswordAuthentication no',
        '    KbdInteractiveAuthentication no',
        '    StrictHostKeyChecking yes', '    BatchMode yes', '    IdentitiesOnly yes',
        '    ForwardAgent no', '    ForwardX11 no', '    ExitOnForwardFailure yes',
        '    ConnectTimeout 10', '    ServerAliveInterval 15', '    ServerAliveCountMax 2',
        '    StreamLocalBindMask 0177', '    StreamLocalBindUnlink yes', forward, ''])
    plist = {'Label': 'local.almaty-access.tunnel', 'RunAtLoad': True,
             'KeepAlive': True, 'ThrottleInterval': 10,
             'ProgramArguments': ['/usr/bin/ssh', '-F', str(config / 'ssh_config'),
                                  '-NT', 'almaty-access']}
    instructions = ('Подготовлены параметры, а не установленная система.\n'
                    'Прочитай SETUP.md и platform README своей ОС.\n'
                    'Сначала проверь host key через консоль провайдера, создай свои ключи.\n'
                    'Адаптируй *.template по deployment.json, проверь синтаксис, затем применяй.\n'
                    'SSH-туннель сам по себе не ограничивает сеть Claude или браузера.\n'
                    'Вход до полного протокола своей ОС запрещён инструкцией комплекта.\n'
                    'Пароли и ключи этой утилитой не созданы.\n')
    if example:
        instructions += 'Адрес из диапазона примеров: он не является реальным VPS.\n'
    # mkdir refuses both an existing directory and a symlink. No installed paths are written.
    output.mkdir(mode=0o700)
    write_new(output / 'deployment.json', json_bytes(deployment))
    write_new(output / 'ssh_config', ssh)
    if system == 'Darwin':
        write_new(output / 'local.almaty-access.tunnel.plist', plistlib.dumps(plist))
    write_new(output / 'READ-ME.txt', instructions)
    emit({'prepared': str(output), 'applied': False, 'network_verified': False,
          'example_address': example})


def verify(manifest):
    root = manifest.resolve().parent
    entries = manifest.read_text(encoding='utf-8').splitlines()
    if not entries:
        raise ValueError('Пустой манифест.')
    seen = set()
    failures = []
    for line in entries:
        match = re.fullmatch(r'([0-9a-f]{64})  (.+)', line)
        if not match:
            raise ValueError('Неверная строка манифеста.')
        digest, relative = match.groups()
        rel = PurePosixPath(relative)
        if rel.is_absolute() or '..' in rel.parts or '\\' in relative or ':' in relative:
            raise ValueError('Путь манифеста выходит за папку комплекта.')
        if relative in seen:
            raise ValueError('Повтор файла в манифесте.')
        seen.add(relative)
        path = root.joinpath(*rel.parts)
        if not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root):
            raise ValueError('Ссылки на файлы вне комплекта запрещены.')
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            failures.append(relative)
    if failures:
        emit({'integrity': False, 'failed_files': failures})
        return 1
    emit({'integrity': True, 'checked_files': len(seen), 'network_verified': False,
          'note': 'Проверена целостность перечисленных файлов, не безопасность сетевой установки.'})
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Опись без изменений и сетевых запросов')
    p = sub.add_parser('init', help='Создать новый журнал, не перезаписывая старый')
    p.add_argument('--state', type=Path, required=True)
    p = sub.add_parser('prepare', help='Подготовить конфиги в новой папке; не устанавливать')
    p.add_argument('--server-ip', required=True)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('verify', help='Проверить SHA256 файлов выдачи')
    p.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'doctor': doctor()
        elif args.command == 'init': initialize(args.state)
        elif args.command == 'prepare': prepare(args.server_ip, args.output)
        else: return verify(args.manifest)
    except (OSError, ValueError) as exc:
        print('Ошибка: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
