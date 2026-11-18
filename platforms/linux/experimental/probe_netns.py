#!/usr/bin/env python3
"""Лабораторный тест без аккаунта. НЕ launcher Claude/Chrome. Python 3.10+."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import platform
import selectors
import shutil
import socket
import stat
import subprocess
import sys
import threading


def die(message):
    print(message, file=sys.stderr)
    raise SystemExit(78)


def parse():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--experimental-probe', action='store_true')
    p.add_argument('--ssh-socket', type=Path)
    p.add_argument('--ipv4')
    p.add_argument('--ipv6')
    p.add_argument('--port', type=int, default=443)
    p.add_argument('--inner-host-netns', help=argparse.SUPPRESS)
    return p.parse_args()


def failed_direct(address, port, kind=socket.SOCK_STREAM):
    family = socket.AF_INET6 if ':' in address else socket.AF_INET
    with socket.socket(family, kind) as s:
        s.settimeout(2)
        try:
            if kind == socket.SOCK_STREAM:
                s.connect((address, port))
            else:
                s.sendto(b'almaty-probe-no-secret', (address, port))
        except OSError as e:
            return {'blocked': True, 'errno': e.errno}
    return {'blocked': False, 'errno': None}


def relay_connection(client):
    """Прозрачный relay без чтения пароля и логирования содержимого."""
    upstream = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        upstream.settimeout(3)
        upstream.connect('/proxy.sock')
        upstream.settimeout(None)
        with selectors.DefaultSelector() as selector:
            selector.register(client, selectors.EVENT_READ, upstream)
            selector.register(upstream, selectors.EVENT_READ, client)
            while True:
                events = selector.select(timeout=5)
                if not events:
                    return
                for key, _ in events:
                    data = key.fileobj.recv(65536)
                    if not data:
                        return
                    key.data.sendall(data)
    except OSError:
        pass
    finally:
        upstream.close()
        client.close()


def proxy_challenge():
    # Listener существует только внутри netns и живёт до завершения теста.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 48921))
        listener.listen(1)

        def accept_one():
            client, _ = listener.accept()
            relay_connection(client)

        t = threading.Thread(target=accept_one, daemon=True)
        t.start()
        try:
            with socket.create_connection(('127.0.0.1', 48921), timeout=5) as c:
                c.sendall(b'CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n')
                line = b''
                while b'\r\n' not in line and len(line) < 1024:
                    part = c.recv(1)
                    if not part:
                        break
                    line += part
                fields = line.split(b' ', 2)
                return len(fields) >= 2 and fields[1] == b'407'
        except OSError:
            return False
        finally:
            t.join(timeout=1)


def inner(args):
    current = os.readlink('/proc/self/ns/net')
    interfaces = [name for _, name in socket.if_nameindex()]
    cap = next(x.split(':', 1)[1].strip() for x in Path('/proc/self/status').read_text().splitlines() if x.startswith('CapEff:'))
    boundary = current != args.inner_host_netns and interfaces == ['lo'] and int(cap, 16) == 0
    if not boundary:
        die('Граница не создана: требуется отдельный netns, только lo, нулевой CapEff.')
    report = {
        'schema': 1, 'kit_version': '1.0.0', 'scope': 'experimental-probe-only',
        'production_ready': False, 'boundary': True, 'interfaces': interfaces,
        'direct': {},
    }
    for name, ip in [('ipv4', args.ipv4), ('ipv6', args.ipv6)]:
        report['direct'][name + '_tcp'] = failed_direct(ip, args.port)
        report['direct'][name + '_udp'] = failed_direct(ip, args.port, socket.SOCK_DGRAM)
        report['direct'][name + '_dns_tcp'] = failed_direct(ip, 53)
        report['direct'][name + '_dns_udp'] = failed_direct(ip, 53, socket.SOCK_DGRAM)
    # Код дочернего процесса фиксирован, пользовательскую команду не принимаем.
    code = "import socket,sys; s=socket.socket(); s.settimeout(2);\ntry: s.connect((sys.argv[1],int(sys.argv[2])))\nexcept OSError: sys.exit(0)\nsys.exit(1)"
    report['child_direct_blocked'] = subprocess.run(
        ['/usr/bin/python3', '-c', code, args.ipv4, str(args.port)],
        env={'PATH': '/usr/bin:/bin', 'NO_PROXY': '*'}, close_fds=True,
        timeout=5, check=False).returncode == 0
    report['proxy_407_via_tcp_unix_ssh'] = proxy_challenge()
    report['passed'] = all(x['blocked'] for x in report['direct'].values()) and report['child_direct_blocked'] and report['proxy_407_via_tcp_unix_ssh']
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if report['passed'] else 1


def main():
    args = parse()
    if not args.experimental_probe:
        die('СТОП: это только лабораторный тест. Нужен --experimental-probe; CLI/браузер не запускаются.')
    if sys.platform != 'linux' or platform.machine() != 'x86_64':
        die('Нужен стенд Ubuntu 24.04 x64; другая ОС не поддержана этим прототипом.')
    try:
        for value, version in [(args.ipv4, 4), (args.ipv6, 6)]:
            address = ipaddress.ip_address(value)
            if address.version != version or not address.is_global:
                raise ValueError('Нужны публичные адреса работающих контрольных endpoint')
        if not 1 <= args.port <= 65535:
            raise ValueError('Неверный port')
    except (TypeError, ValueError) as e:
        die(str(e))
    if args.inner_host_netns:
        return inner(args)
    if os.geteuid() == 0:
        die('Этот прототип запускается обычным пользователем, без sudo.')
    release = Path('/etc/os-release').read_text()
    if 'ID=ubuntu\n' not in release or 'VERSION_ID="24.04"' not in release:
        die('Прототип заявлен только для Ubuntu 24.04.')
    if not shutil.which('bwrap'):
        die('Нет bubblewrap. Не заменять тест обычным запуском.')
    if not args.ssh_socket:
        die('Нужен --ssh-socket с сокетом отдельной службы SSH.')
    source = args.ssh_socket.absolute()
    info = source.lstat()
    parent = source.parent.stat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        die('SSH socket должен принадлежать тебе; доступ группы/других запрещён.')
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        die('Папка SSH socket должна принадлежать тебе и иметь права 700.')
    if len(os.fsencode(source)) > 100:
        die('Путь Unix socket слишком длинный; используй короткий приватный CONFIG_DIR.')
    for fd in (0, 1, 2):
        if stat.S_ISSOCK(os.fstat(fd).st_mode):
            die('Не принимать унаследованные сетевые stdin/stdout/stderr.')
    command = [shutil.which('bwrap'), '--unshare-all', '--die-with-parent', '--new-session',
               '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'HOME', '/home/guest', '--setenv', 'LANG', 'C.UTF-8',
               '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
               '--symlink', 'usr/lib', '/lib', '--symlink', 'usr/lib64', '/lib64',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/run',
               '--dir', '/etc', '--dir', '/home/guest',
               '--ro-bind', str(source), '/proxy.sock',
               '--ro-bind', str(Path(__file__).resolve()), '/probe.py',
               '--chdir', '/home/guest', '/usr/bin/python3', '/probe.py',
               '--experimental-probe', '--inner-host-netns', os.readlink('/proc/self/ns/net'),
               '--ipv4', args.ipv4, '--ipv6', args.ipv6, '--port', str(args.port)]
    return subprocess.run(command, close_fds=True, check=False).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, subprocess.TimeoutExpired) as error:
        die(f'Тест остановлен ({type(error).__name__}). Никакого fallback не выполнено.')
