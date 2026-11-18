#!/usr/bin/env python3
"""Комплект 1.0.0: сеанс Ubuntu 24.04/WSL2 с проверками на компьютере получателя. Python 3.10+."""
import argparse
import base64
import configparser
import ctypes
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shlex
import signal
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

RELAY = ['/usr/bin/socat', 'TCP4-LISTEN:48921,bind=127.0.0.1,reuseaddr,fork',
         'UNIX-CONNECT:/transport/proxy.sock']
SCHEMA = 'almaty-whole-session-experiment-v1'


class Refusal(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Refusal(reason)


def absolute(value):
    require(isinstance(value, str) and value.startswith('/') and not value.startswith('//'),
            'Все пути должны быть абсолютными Linux-путями.')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value), 'Управляющий символ в пути.')
    require('..' not in PurePosixPath(value).parts, 'Переход .. в пути запрещён.')
    return str(PurePosixPath(value))


def overlap(first, second):
    a, b = PurePosixPath(first), PurePosixPath(second)
    return a == b or a in b.parents or b in a.parents


def options(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experimental', action='store_true', help='Устаревший необязательный флаг совместимости.')
    parser.add_argument('--plan', '--dry-run', action='store_true', dest='plan')
    parser.add_argument('--apps', choices=['cli', 'browser', 'both'], default='both')
    for name in ['project', 'state', 'cli', 'cli-sha256', 'chrome-dir', 'ssh-socket',
                 'server-ip', 'known-hosts', 'host-key-sha256', 'auth-file', 'wayland-socket']:
        parser.add_argument('--' + name)
    parser.add_argument('--ssh-pid', type=int)
    return parser.parse_args(argv)


def configuration(args):
    cfg = vars(args).copy()
    for key in ['project', 'state', 'cli', 'chrome_dir', 'ssh_socket', 'known_hosts', 'auth_file']:
        cfg[key] = absolute(cfg[key])
    if cfg['wayland_socket']:
        cfg['wayland_socket'] = absolute(cfg['wayland_socket'])
    require(cfg['apps'] == 'cli' or cfg['wayland_socket'], 'Для браузера нужен точный --wayland-socket.')
    require(re.fullmatch(r'[0-9a-f]{64}', cfg['cli_sha256'] or ''), 'Нужен проверенный --cli-sha256.')
    require(re.fullmatch(r'SHA256:[A-Za-z0-9+/]{43}', cfg['host_key_sha256'] or ''),
            'Нужен --host-key-sha256 из независимой консоли своего VPS.')
    require(isinstance(cfg['ssh_pid'], int) and cfg['ssh_pid'] > 1, 'Нужен PID своего SSH-транспорта.')
    ip = ipaddress.IPv4Address(cfg['server_ip'])
    require(not (ip.is_loopback or ip.is_multicast or ip.is_unspecified), 'Нужен IPv4 своего VPS.')
    cfg['server_ip'] = str(ip)
    require(':' not in cfg['ssh_socket'] and len(os.fsencode(cfg['ssh_socket'])) <= 100,
            'SSH socket: путь до 100 байт без двоеточия.')
    broad = {'/', '/home', '/root', '/tmp', '/var', '/var/tmp', '/run', '/mnt', '/media', '/usr', '/etc', '/opt'}
    require(cfg['project'] not in broad and cfg['state'] not in broad, 'Нельзя открыть целый каталог хоста.')
    require(not overlap(cfg['project'], cfg['state']), 'Проект и приватное состояние должны быть раздельными.')
    package = str(Path(__file__).resolve().parents[3])
    require(not overlap(cfg['state'], package) and not overlap(cfg['project'], package),
            'Состояние и проект должны находиться вне раздатки.')
    for name in ['ssh_socket', 'known_hosts', 'auth_file', 'cli', 'chrome_dir']:
        require(not overlap(cfg['project'], cfg[name]) and not overlap(cfg['state'], cfg[name]),
                'Проект/состояние не должны содержать ключи, транспорт или бинарники.')
    return cfg


def make_plan(cfg, host_ns=None):
    """Чистый план argv. Не читает секреты, не создаёт файлы, ничего не запускает."""
    source = str(Path(__file__).resolve())
    state = cfg['state']
    command = ['/usr/bin/bwrap', '--unshare-all', '--die-with-parent', '--new-session',
               '--cap-drop', 'ALL', '--clearenv',
               '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
               '--setenv', 'HOME', '/home/guest', '--setenv', 'TERM', 'xterm-256color',
               '--ro-bind', '/usr', '/usr', '--symlink', 'usr/bin', '/bin',
               '--symlink', 'usr/sbin', '/sbin', '--symlink', 'usr/lib', '/lib',
               '--symlink', 'usr/lib64', '/lib64', '--proc', '/proc', '--dev', '/dev',
               '--tmpfs', '/tmp', '--tmpfs', '/run', '--dir', '/run/user/1000',
               '--dir', '/etc', '--ro-bind', '/etc/ssl/certs', '/etc/ssl/certs',
               '--ro-bind', '/etc/fonts', '/etc/fonts',
               '--ro-bind', '/etc/ld.so.cache', '/etc/ld.so.cache',
               '--ro-bind', state + '/hosts', '/etc/hosts',
               '--ro-bind', state + '/resolv.conf', '/etc/resolv.conf',
               '--ro-bind', state + '/passwd', '/etc/passwd',
               '--ro-bind', state + '/group', '/etc/group',
               '--bind', state + '/home', '/home/guest',
               '--bind', cfg['project'], '/workspace',
               '--ro-bind', cfg['cli'], '/opt/claude/claude',
               '--ro-bind', cfg['chrome_dir'], '/opt/google/chrome',
               '--ro-bind', source, '/opt/almaty/session_launcher.py',
               '--ro-bind', state + '/session.json', '/opt/almaty/session.json',
               '--ro-bind', cfg['ssh_socket'], '/transport/proxy.sock',
               '--ro-bind', cfg['auth_file'], '/secrets/proxy.auth']
    if cfg['wayland_socket'] and cfg['apps'] != 'cli':
        command += ['--ro-bind', cfg['wayland_socket'], '/run/user/1000/wayland-0']
    command += ['--remount-ro', '/', '--chdir', '/workspace',
                '/usr/bin/python3', '-I', '-B', '/opt/almaty/session_launcher.py', '--inner']
    return {'schema': SCHEMA, 'scope': 'guided-whole-session', 'production_ready': False,
            'runtime_verified': False, 'apps': cfg['apps'], 'bwrap_argv': command,
            'relay_argv': list(RELAY), 'host_namespaces': host_ns or {},
            'note': 'План не проверяет ОС, файлы, SSH, сеть или работоспособность Chrome.'}


def metadata(path, kind='file', private=False, root=False):
    path = Path(path)
    require(path.resolve() == path, 'Симлинки в путях ресурсов не допускаются; укажи реальный путь.')
    info = path.lstat()
    test = {'file': stat.S_ISREG, 'dir': stat.S_ISDIR, 'socket': stat.S_ISSOCK}[kind]
    require(test(info.st_mode), 'Ресурс имеет неподходящий тип.')
    require(info.st_uid == (0 if root else os.getuid()), 'Неподходящий владелец ресурса.')
    forbidden = 0o077 if private else 0o022
    require(not (stat.S_IMODE(info.st_mode) & forbidden), 'Небезопасные права ресурса.')
    return info


def validate_wayland_socket(path):
    """Вернуть один реальный compositor socket, включая штатную ссылку WSLg.

    Права подключения 0777 у сокета не равны праву заменить его inode.
    Проверяем тип/владельца и каталог, а не применяем режим секретного файла.
    Каталог WSLg, весь runtime и другие сокеты внутрь не передаются.
    """
    resolved = Path(path).resolve(strict=True)
    info = resolved.lstat()
    require(stat.S_ISSOCK(info.st_mode) and info.st_uid == os.getuid(),
            'Wayland должен быть сокетом текущего пользователя; проверь фактический compositor socket.')
    parent = resolved.parent.stat()
    require(parent.st_uid in (0, os.getuid()) and not (parent.st_mode & 0o022),
            'Каталог Wayland socket допускает подмену другими пользователями; нужен адресный разбор.')
    return str(resolved)


def strict_walk(path):
    def refuse_unreadable(_error):
        raise Refusal('Недоступный каталог нельзя пропустить при проверке границы.')
    return os.walk(path, followlinks=False, onerror=refuse_unreadable)


def tree_has_only_data(path):
    count = 0
    for root, dirs, files in strict_walk(path):
        for name in dirs + files:
            count += 1
            require(count <= 200000, 'Слишком большой проект для этого минимального стенда.')
            info = (Path(root) / name).lstat()
            mode = info.st_mode
            require(stat.S_ISREG(mode) or stat.S_ISDIR(mode),
                    'В проекте/состоянии есть ссылка, socket, FIFO или device; сначала адресная опись.')
            require(not stat.S_ISREG(mode) or info.st_nlink == 1,
                    'Hardlink в writable проекте/состоянии может вести на внешний файл.')


def resolve_home_link(path, home):
    """Разрешить ссылку в пространстве гостя, не открывая путь хоста снаружи HOME."""
    pending = list(path.relative_to(home).parts)
    current = home
    links = 0
    while pending:
        part = pending.pop(0)
        if part in ('', '.'):
            continue
        if part == '..':
            require(current != home, 'Ссылка выходит за собственный HOME.')
            current = current.parent
            continue
        candidate = current / part
        info = candidate.lstat()
        if stat.S_ISLNK(info.st_mode):
            links += 1
            require(links <= 40, 'Циклическая или слишком длинная цепочка ссылок HOME.')
            target = PurePosixPath(os.readlink(candidate))
            if target.is_absolute():
                require(target.is_relative_to('/home/guest'), 'Абсолютная ссылка ведёт вне гостевого HOME.')
                current = home
                target = target.relative_to('/home/guest')
            pending = list(target.parts) + pending
        else:
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
                    'Ссылка HOME ведёт к socket/FIFO/device.')
            require(not pending or stat.S_ISDIR(info.st_mode), 'Промежуточная цель ссылки не каталог.')
            current = candidate
    return current


def validate_private_home(home):
    """Штатные внутренние ссылки Claude допустимы; внешние объекты не монтируются."""
    count = 0
    for root, dirs, files in strict_walk(home):
        for name in dirs + files:
            count += 1
            require(count <= 200000, 'Слишком большое состояние для адресной проверки.')
            path = Path(root) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode):
                info = resolve_home_link(path, home).lstat()
            require(stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode),
                    'В HOME есть socket/FIFO/device; нужен адресный разбор.')
            require(not stat.S_ISREG(info.st_mode) or info.st_nlink == 1,
                    'Hardlink в HOME может вести на внешний файл.')


def validate_wsl(config_text, interop_entries, environ):
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(config_text)
    for section, option in [('interop', 'enabled'), ('interop', 'appendWindowsPath'),
                            ('automount', 'enabled'), ('automount', 'mountFsTab'),
                            ('network', 'generateResolvConf')]:
        require(config.has_option(section, option) and config.getboolean(section, option) is False,
                'WSL: требуется отключённый interop, Windows PATH, automount и host resolver.')
    require(not interop_entries and not environ.get('WSL_INTEROP'),
            'WSLInterop ещё доступен: нужен перезапуск выбранного стенда и повторная проверка.')


def namespaces():
    return {name: os.readlink('/proc/self/ns/' + name) for name in ['net', 'mnt', 'pid', 'ipc', 'user']}


def validate_host():
    require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'Нужна Ubuntu 24.04 x64 / WSL2.')
    require(os.geteuid() != 0, 'Только обычный пользователь; sudo не применяется.')
    release = Path('/etc/os-release').read_text()
    require('ID=ubuntu\n' in release and 'VERSION_ID="24.04"' in release, 'Нужна Ubuntu 24.04 x64.')
    wsl = 'microsoft' in Path('/proc/sys/kernel/osrelease').read_text().lower()
    if wsl:
        entries = list(Path('/proc/sys/fs/binfmt_misc').glob('*WSLInterop*'))
        validate_wsl(Path('/etc/wsl.conf').read_text(), entries, os.environ)
    for tool in ['bwrap', 'python3', 'socat', 'ssh']:
        real = Path('/usr/bin/' + tool).resolve()
        info = metadata(real, root=True)
        require(info.st_mode & 0o111 and not (info.st_mode & (stat.S_ISUID | stat.S_ISGID)),
                'Нужны обычные root-owned bwrap/Python/socat/SSH без setuid.')
    return wsl


def check_auth(path):
    metadata(path, private=True)
    raw = Path(path).read_bytes()
    require(re.fullmatch(rb'client [0-9a-f]{64}\n', raw), 'Неверный формат proxy.auth; значение скрыто.')
    return raw.decode().strip().split(' ', 1)


def validate_ssh_argv(argv, cfg):
    require(len(argv) == 5 and Path(argv[0]).name == 'ssh' and argv[1] == '-F' and
            argv[3:] == ['-NT', 'almaty-access'], 'SSH argv должен точно соответствовать unit с -F ssh_config -NT almaty-access.')
    path = absolute(argv[2])
    require(not overlap(path, cfg['project']) and not overlap(path, cfg['state']), 'SSH config доступен в проекте/состоянии.')
    return path


def validate_ssh_config(text, cfg):
    # Строгая подгруппа формата OpenSSH: никаких Include/Match/exec/подстановок окружения.
    options = {}
    for line in text.splitlines():
        tokens = shlex.split(line, comments=True, posix=True)
        if not tokens:
            continue
        name = tokens[0].lower()
        require(name not in options and len(tokens) >= 2, 'Повтор/пустая SSH-опция.')
        options[name] = tokens[1:]
    require(options.get('host') == ['almaty-access'], 'Нужен единственный точный Host almaty-access.')
    def literal_path(name):
        values = options.get(name, [])
        require(len(values) == 1, 'Нужен ровно один путь SSH.')
        value = values[0]
        require('${' not in value and '%' not in value.replace('%%', ''), 'SSH-подстановки запрещены; literal % кодируется %%.')
        return absolute(value.replace('%%', '%'))
    key = literal_path('identityfile')
    known = literal_path('userknownhostsfile')
    forward = options.get('localforward', [])
    require(len(forward) == 2, 'Нужен один Unix LocalForward.')
    require('${' not in forward[0] and '%' not in forward[0].replace('%%', ''), 'Подстановка в LocalForward запрещена.')
    forward_path = absolute(forward[0].replace('%%', '%'))
    expected = {'host': ['almaty-access'], 'hostname': [cfg['server_ip']], 'user': ['almaty-tunnel'], 'port': ['22'],
                'identityfile': options['identityfile'], 'userknownhostsfile': options['userknownhostsfile'],
                'globalknownhostsfile': ['/dev/null'], 'updatehostkeys': ['no'], 'verifyhostkeydns': ['no'],
                'passwordauthentication': ['no'], 'kbdinteractiveauthentication': ['no'],
                'stricthostkeychecking': ['yes'], 'batchmode': ['yes'], 'identitiesonly': ['yes'],
                'forwardagent': ['no'], 'forwardx11': ['no'], 'exitonforwardfailure': ['yes'],
                'connecttimeout': ['10'], 'serveraliveinterval': ['15'], 'serveralivecountmax': ['2'],
                'streamlocalbindmask': ['0177'], 'streamlocalbindunlink': ['yes'], 'localforward': forward}
    require(options == expected and known == cfg['known_hosts'] and forward_path == cfg['ssh_socket'] and
            forward[1] == '127.0.0.1:48921', 'SSH config не соответствует закреплённому транспорту.')
    require(not overlap(key, cfg['project']) and not overlap(key, cfg['state']), 'SSH-ключ доступен в проекте/состоянии.')
    return key


def check_effective_ssh(config, cfg, key):
    # Вызывается только после allowlist-разбора. ssh -G не соединяется с VPS.
    result = subprocess.run(['/usr/bin/ssh', '-G', '-F', config, 'almaty-access'],
                            capture_output=True, text=True, timeout=5, close_fds=True,
                            env={'PATH': '/usr/bin:/bin', 'HOME': str(Path.home()), 'LANG': 'C'})
    require(result.returncode == 0, 'OpenSSH не принял подготовленный config.')
    effective = {}
    for line in result.stdout.splitlines():
        name, _, value = line.partition(' ')
        effective.setdefault(name, []).append(value.replace('%%', '%'))
    expected = {'hostname': cfg['server_ip'], 'user': 'almaty-tunnel', 'port': '22',
                'identityfile': key, 'userknownhostsfile': cfg['known_hosts'], 'globalknownhostsfile': '/dev/null',
                'stricthostkeychecking': 'true', 'passwordauthentication': 'no', 'kbdinteractiveauthentication': 'no',
                'verifyhostkeydns': 'false', 'updatehostkeys': 'false', 'forwardagent': 'no', 'forwardx11': 'no',
                'localforward': cfg['ssh_socket'] + ' [127.0.0.1]:48921'}
    require(all(effective.get(name) == [value] for name, value in expected.items()),
            'Эффективная конфигурация OpenSSH отличается; запуск остановлен.')


def socket_kernel_inode(text, source):
    rows = [row.split(maxsplit=7) for row in text.splitlines()[1:]]
    matches = [row for row in rows if len(row) == 8 and row[-1] == source and row[3] == '00010000']
    require(len(matches) == 1, 'Не найден единственный listener своего Unix socket.')
    return matches[0][6]


def validate_transport(cfg, effective=False):
    info = metadata(cfg['ssh_socket'], 'socket', private=True)
    metadata(Path(cfg['ssh_socket']).parent, 'dir', private=True)
    metadata(cfg['known_hosts'], private=True)
    lines = Path(cfg['known_hosts']).read_text().splitlines()
    require(len(lines) == 1, 'Для стенда known_hosts содержит ровно один проверенный ключ.')
    fields = lines[0].split()
    require(len(fields) == 3 and fields[:2] == [cfg['server_ip'], 'ssh-ed25519'], 'Нужен точный IPv4 и ed25519 host key.')
    digest = base64.b64encode(hashlib.sha256(base64.b64decode(fields[2], validate=True)).digest()).decode().rstrip('=')
    require('SHA256:' + digest == cfg['host_key_sha256'], 'Host key не совпал с независимым fingerprint.')
    proc = Path('/proc') / str(cfg['ssh_pid'])
    require(proc.stat().st_uid == os.getuid(), 'SSH PID принадлежит другому пользователю.')
    require(os.readlink(proc / 'exe') == str(Path('/usr/bin/ssh').resolve()), 'PID исполняет не системный SSH.')
    argv = (proc / 'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    config = validate_ssh_argv(argv, cfg)
    config_info = metadata(config, private=True)
    config_text = Path(config).read_text()
    key = validate_ssh_config(config_text, cfg)
    metadata(key, private=True)
    handle = 'socket:[' + socket_kernel_inode(Path('/proc/net/unix').read_text(), cfg['ssh_socket']) + ']'
    require(any(os.readlink(fd) == handle for fd in (proc / 'fd').iterdir()), 'Socket обслуживает другой процесс.')
    # starttime не меняется при продолжении процесса и защищает от повторного использования PID.
    starttime = (proc / 'stat').read_text().rsplit(')', 1)[1].split()[19]
    boot = next(int(line.split()[1]) for line in Path('/proc/stat').read_text().splitlines() if line.startswith('btime '))
    started_at = boot + int(starttime) / os.sysconf('SC_CLK_TCK')
    require(max(config_info.st_mtime, config_info.st_ctime) <= started_at,
            'SSH config изменён после старта процесса; согласованно перезапусти только свой транспорт.')
    if effective:
        check_effective_ssh(config, cfg, key)
    return (info.st_dev, info.st_ino, starttime, config_info.st_dev, config_info.st_ino,
            hashlib.sha256(config_text.encode()).hexdigest())


def runtime_inputs(cfg):
    require(ipaddress.IPv4Address(cfg['server_ip']).is_global, 'Для запуска нужен реальный публичный IPv4, не пример.')
    metadata(cfg['project'], 'dir')
    require(Path(cfg['project']) != Path.home(), 'Весь HOME нельзя передавать как проект.')
    tree_has_only_data(cfg['project'])
    cli = metadata(cfg['cli'], root=True)
    require(cli.st_mode & 0o111, 'CLI должен быть исполняемым native binary.')
    with open(cfg['cli'], 'rb') as stream:
        require(stream.read(4) == b'\x7fELF', 'CLI должен быть Linux ELF, не shell/npm wrapper.')
    require(hashlib.sha256(Path(cfg['cli']).read_bytes()).hexdigest() == cfg['cli_sha256'], 'CLI hash изменился.')
    metadata(cfg['chrome_dir'], 'dir', root=True)
    metadata(Path(cfg['chrome_dir']) / 'chrome', root=True)
    for root, dirs, files in strict_walk(cfg['chrome_dir']):
        for name in dirs + files:
            path = Path(root) / name
            item = path.lstat()
            require(item.st_uid == 0 and not (item.st_mode & 0o022), 'Chrome tree должен быть root-owned и без чужой записи.')
            require(stat.S_ISREG(item.st_mode) or stat.S_ISDIR(item.st_mode), 'Chrome tree: ссылки и специальные файлы не поддержаны.')
    check_auth(cfg['auth_file'])
    if cfg['apps'] != 'cli':
        cfg['wayland_socket'] = validate_wayland_socket(cfg['wayland_socket'])
    existing_state = validate_state(cfg)
    # Только терминальные fd0–2. Pipe/socket может стать каналом к host helper.
    require(all(os.isatty(fd) and stat.S_ISCHR(os.fstat(fd).st_mode) for fd in (0, 1, 2)),
            'Runtime запускается в отдельном интерактивном терминале, не с pipe/socket stdio.')
    return existing_state


def state_identity(cfg):
    return {'owner_uid': os.getuid(), 'project': cfg['project'], 'cli': cfg['cli'],
            'cli_sha256': cfg['cli_sha256'], 'chrome_dir': cfg['chrome_dir']}


def validate_state(cfg):
    state = Path(cfg['state'])
    require(state.parent.resolve() == state.parent, 'Родитель state не должен быть ссылкой.')
    metadata(state.parent, 'dir')
    if not state.exists() and not state.is_symlink():
        return False
    metadata(state, 'dir', private=True)
    allowed = {'home', 'session.json', 'hosts', 'resolv.conf', 'passwd', 'group', '.lock'}
    require(set(p.name for p in state.iterdir()) <= allowed, 'state содержит неизвестные файлы; нужен адресный разбор.')
    marker = state / 'session.json'
    require(marker.is_file(), 'Существующий state без session.json не принимается, даже пустой; после аварии нужен разбор.')
    for file in state.iterdir():
        if file.name != 'home':
            private_generated_file(file)
    data = json.loads(marker.read_text())
    require(isinstance(data, dict) and data.get('schema') == SCHEMA and
            data.get('state_identity') == state_identity(cfg), 'State принадлежит другой схеме/проекту/CLI; не перезаписывать.')
    require((state / 'home').is_dir(), 'State неполон: отсутствует собственный HOME; нужен разбор после аварии.')
    metadata(state / 'home', 'dir', private=True)
    validate_private_home(state / 'home')
    return True


def no_new_privileges():
    require(ctypes.CDLL(None, use_errno=True).prctl(38, 1, 0, 0, 0) == 0, 'Не удалось включить no_new_privs.')


def boundary_report(status, current_ns, host_ns, interfaces, routes4, routes6, forbidden):
    """Проверяется перед relay, CLI и браузером. Отказ не заменяется обычным запуском."""
    names = {'net', 'mnt', 'pid', 'ipc', 'user'}
    require(set(current_ns) == names and set(host_ns) == names and
            all(re.fullmatch(key + r':\[\d+\]', host_ns[key]) and
                current_ns[key] != host_ns[key] for key in names), 'Не все namespaces изолированы.')
    require(interfaces == ['lo'], 'Есть внешний сетевой интерфейс.')
    fields = dict(line.split(':', 1) for line in status.splitlines() if ':' in line)
    require(fields.get('NoNewPrivs', '').strip() == '1', 'NoNewPrivs отсутствует.')
    require(all(int(fields.get(name, '-1').strip(), 16) == 0 for name in
                ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb']), 'Capabilities не сброшены.')
    require(all(row.split()[0] == 'lo' for row in routes4.splitlines()[1:] if row.strip()), 'Есть IPv4 маршрут вне lo.')
    require(all(row.split()[-1] == 'lo' for row in routes6.splitlines() if row.strip()), 'Есть IPv6 маршрут вне lo.')
    require(not forbidden, 'Внутри виден host-exec/interop/host socket.')


def check_inner_boundary(data):
    no_new_privileges()
    forbidden = [p for p in ['/init', '/mnt/c', '/mnt/wslg', '/run/dbus/system_bus_socket',
                             '/var/run/docker.sock', '/run/user/1000/bus'] if Path(p).exists()]
    forbidden += list(Path('/proc/sys/fs/binfmt_misc').glob('*WSLInterop*'))
    boundary_report(Path('/proc/self/status').read_text(), namespaces(), data['host_namespaces'],
                    [name for _, name in socket.if_nameindex()], Path('/proc/net/route').read_text(),
                    Path('/proc/net/ipv6_route').read_text(), forbidden)
    require(not any(name in os.environ for name in ['WSL_INTEROP', 'SSH_AUTH_SOCK', 'DBUS_SESSION_BUS_ADDRESS', 'DISPLAY']),
            'Сохранено запрещённое host окружение.')


def authenticated_ip(user, password, expected):
    credentials = base64.b64encode((user + ':' + password).encode()).decode()
    connection = http.client.HTTPSConnection('127.0.0.1', 48921, timeout=12, context=ssl.create_default_context())
    try:
        connection.set_tunnel('api.ipify.org', 443, {'Proxy-Authorization': 'Basic ' + credentials})
        connection.request('GET', '/')
        response = connection.getresponse()
        require(response.status == 200 and response.read(128).decode().strip() == expected,
                'Проверка authenticated VPS IP не прошла.')
    finally:
        connection.close()


def stop_children(children):
    for child in reversed(children):
        if child.poll() is None:
            try:
                os.killpg(child.pid, signal.SIGTERM)
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait(timeout=3)
            except ProcessLookupError:
                pass


def inner():
    require(sys.platform == 'linux', 'Inner доступен только внутри созданной Linux-границы.')
    data = json.loads(Path('/opt/almaty/session.json').read_text())
    require(data['schema'] == SCHEMA, 'Неизвестная схема сеанса.')
    check_inner_boundary(data)
    os.chmod('/run/user/1000', 0o700)
    children = []
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        relay = subprocess.Popen(RELAY, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True)
        children.append(relay)
        for attempt in range(30):
            require(relay.poll() is None, 'Relay отказал до запуска приложений.')
            try:
                with socket.create_connection(('127.0.0.1', 48921), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise Refusal('Relay не стал доступен.')
        user, password = check_auth('/secrets/proxy.auth')
        authenticated_ip(user, password, data['server_ip'])
        base_env = {'PATH': '/usr/bin:/bin', 'HOME': '/home/guest', 'LANG': 'C.UTF-8',
                    'TERM': 'xterm-256color', 'XDG_CONFIG_HOME': '/home/guest/.config',
                    'XDG_CACHE_HOME': '/home/guest/.cache', 'XDG_RUNTIME_DIR': '/run/user/1000',
                    'WAYLAND_DISPLAY': 'wayland-0', 'NO_PROXY': 'localhost,127.0.0.1,::1'}
        browser = None
        if data['apps'] != 'cli':
            browser = subprocess.Popen(['/opt/google/chrome/chrome', '--ozone-platform=wayland',
                '--user-data-dir=/home/guest/chrome', '--proxy-server=http://127.0.0.1:48921',
                '--proxy-bypass-list=localhost;127.0.0.1;[::1]', '--no-first-run',
                '--disable-gpu', 'about:blank'], env=base_env, cwd='/workspace',
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, start_new_session=True)
            children.append(browser)
            time.sleep(2)
            require(browser.poll() is None, 'Chrome не запустился с штатной sandbox/Wayland; ослабления запрещены.')
        cli = None
        if data['apps'] != 'browser':
            proxy = 'http://' + quote(user, safe='') + ':' + quote(password, safe='') + '@127.0.0.1:48921'
            env = dict(base_env, HTTP_PROXY=proxy, HTTPS_PROXY=proxy, ALL_PROXY=proxy,
                       http_proxy=proxy, https_proxy=proxy, all_proxy=proxy,
                       no_proxy='localhost,127.0.0.1,::1', CLAUDE_CONFIG_DIR='/home/guest/.claude')
            cli = subprocess.Popen(['/opt/claude/claude'], env=env, cwd='/workspace',
                                   close_fds=True, start_new_session=True)
            children.append(cli)
        print('Сеанс запущен. Заверши сетевые проверки этой машины, затем вход и обе реальные задачи.', flush=True)
        while True:
            require(relay.poll() is None, 'Relay завершился; сеанс остановлен.')
            if cli and cli.poll() is not None:
                return cli.returncode
            if browser and browser.poll() is not None:
                require(browser.returncode == 0, 'Chrome завершился с ошибкой; сеанс остановлен.')
                return 0
            time.sleep(0.25)
    finally:
        stop_children(children)


def private_generated_file(path):
    info = metadata(path, private=True)
    require(info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
            'Generated state file должен быть обычным файлом 600 без hardlink.')
    return (info.st_dev, info.st_ino)


def write_private(path, value):
    prior = private_generated_file(path) if path.exists() or path.is_symlink() else None
    fd, temporary = tempfile.mkstemp(prefix='.generated-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        if prior:
            require(private_generated_file(path) == prior, 'Generated state file изменился во время записи.')
        else:
            require(not path.exists() and not path.is_symlink(), 'Generated state path появился во время записи.')
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_session(cfg):
    import fcntl
    wsl = validate_host()
    existing_state = runtime_inputs(cfg)
    identity = validate_transport(cfg, effective=True)
    host_ns = namespaces()
    state = Path(cfg['state'])
    # Все входные параметры/ресурсы проверены до первой записи.
    if not existing_state:
        state.mkdir(mode=0o700)
    lock_fd = os.open(state / '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    process = None
    try:
        lock_info = os.fstat(lock_fd)
        require(stat.S_ISREG(lock_info.st_mode) and lock_info.st_nlink == 1 and
                lock_info.st_uid == os.getuid() and stat.S_IMODE(lock_info.st_mode) == 0o600,
                'Lock должен быть своим обычным файлом 600 без hardlink.')
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if existing_state:
            validate_state(cfg)
        (state / 'home').mkdir(mode=0o700, exist_ok=True)
        data = {'schema': SCHEMA, 'host_namespaces': host_ns, 'server_ip': cfg['server_ip'],
                'apps': cfg['apps'], 'wsl': wsl, 'production_ready': False, 'state_identity': state_identity(cfg)}
        write_private(state / 'session.json', json.dumps(data))
        write_private(state / 'hosts', '127.0.0.1 localhost\n::1 localhost\n')
        write_private(state / 'resolv.conf', 'nameserver 127.0.0.1\noptions timeout:1 attempts:1\n')
        write_private(state / 'passwd', f'guest:x:{os.getuid()}:{os.getgid()}:Experiment:/home/guest:/bin/bash\n')
        write_private(state / 'group', f'guest:x:{os.getgid()}:\n')
        no_new_privileges()
        require(validate_transport(cfg) == identity, 'SSH изменился до запуска.')
        process = subprocess.Popen(make_plan(cfg, host_ns)['bwrap_argv'], close_fds=True,
                                   env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'})
        while process.poll() is None:
            time.sleep(0.5)
            require(validate_transport(cfg) == identity, 'SSH/socket изменился; нужно заново открыть сеанс.')
        return process.returncode
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        os.close(lock_fd)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ['--inner']:
        return inner()
    if '--plan' not in argv and '--dry-run' not in argv:
        require(sys.platform == 'linux' and platform.machine() == 'x86_64', 'Нужна Ubuntu 24.04 x64 / WSL2.')
    cfg = configuration(options(argv))
    if cfg['plan']:
        print(json.dumps(make_plan(cfg), ensure_ascii=False, indent=2))
        return 0
    return run_session(cfg)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('Сеанс остановлен владельцем.', file=sys.stderr)
        raise SystemExit(130)
    except (Refusal, OSError, ValueError, KeyError, configparser.Error, subprocess.SubprocessError,
            http.client.HTTPException, ssl.SSLError) as error:
        # Не выводить raw исключение сетевой библиотеки/credential parser.
        message = str(error) if isinstance(error, Refusal) else type(error).__name__
        print('СТОП: ' + message + ' Прямой fallback не выполнялся.', file=sys.stderr)
        raise SystemExit(78)
