"""Офлайн-контракт launcher: запуск приложений и сеть здесь не тестируются."""
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest

LAUNCHER = Path(__file__).with_name('session_launcher.py')


def arguments():
    return [
        '--experimental', '--plan', '--apps', 'both',
        '--project', '/home/learner/work/test-project',
        '--state', '/home/learner/.local/state/almaty-experiment',
        '--cli', '/opt/claude-pinned/claude', '--cli-sha256', '0' * 64,
        '--chrome-dir', '/opt/google/chrome',
        '--ssh-socket', '/home/learner/.config/almaty-access/proxy.sock',
        '--ssh-pid', '1234', '--server-ip', '203.0.113.10',
        '--known-hosts', '/home/learner/.config/almaty-access/known_hosts',
        '--host-key-sha256', 'SHA256:' + 'A' * 43,
        '--auth-file', '/home/learner/.config/almaty-access/proxy.auth',
        '--wayland-socket', '/run/user/1000/wayland-0',
    ]


def changed(args, flag, value):
    result = list(args)
    result[result.index(flag) + 1] = value
    return result


class PlanContract(unittest.TestCase):
    def invoke(self, args):
        return subprocess.run([sys.executable, str(LAUNCHER), *args],
                              capture_output=True, text=True, timeout=10)

    def plan(self, args=None):
        result = self.invoke(arguments() if args is None else args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_normal_plan_reaches_engine_without_legacy_opt_in(self):
        args = [arg for arg in arguments() if arg != '--experimental']
        plan = self.plan(args)
        self.assertIn('--unshare-all', plan['bwrap_argv'])
        self.assertFalse(plan['runtime_verified'])

    @unittest.skipIf(sys.platform == 'linux', 'На Linux это runtime-предусловие.')
    def test_unsupported_host_refuses_before_files_or_children(self):
        result = self.invoke(['--experimental'])
        self.assertEqual(result.returncode, 78)
        self.assertIn('Ubuntu 24.04', result.stderr)

    def test_plan_has_one_whole_session_and_no_broad_host_binds(self):
        plan = self.plan()
        self.assertFalse(plan['production_ready'])
        self.assertFalse(plan['runtime_verified'])
        command = plan['bwrap_argv']
        self.assertIn('--unshare-all', command)
        self.assertIn('--clearenv', command)
        self.assertNotIn('--share-net', command)
        mounts = [(command[i + 1], command[i + 2]) for i, arg in enumerate(command)
                  if arg in ('--bind', '--ro-bind')]
        for source, _ in mounts:
            self.assertNotIn(source, ['/', '/home', '/home/learner', '/run', '/tmp',
                                      '/mnt', '/mnt/wslg', '/proc', '/dev', '/etc'])
        self.assertIn(('/home/learner/work/test-project', '/workspace'), mounts)
        self.assertIn(('/opt/claude-pinned/claude', '/opt/claude/claude'), mounts)
        self.assertIn(('/run/user/1000/wayland-0', '/run/user/1000/wayland-0'), mounts)
        self.assertNotIn('--no-sandbox', json.dumps(plan))
        self.assertNotIn('--disable-setuid-sandbox', json.dumps(plan))

    def test_plan_does_not_create_state_or_read_auth(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'not-created'
            args = changed(arguments(), '--state', str(target))
            plan = self.plan(args)
            self.assertFalse(target.exists())
            self.assertNotIn('proxy_password', plan)

    def test_relative_parent_and_control_paths_refused(self):
        for path in ('relative/project', '/home/a/../secret', '/home/a\n--bind', '/home/a\r'):
            with self.subTest(path=path):
                result = self.invoke(changed(arguments(), '--project', path))
                self.assertEqual(result.returncode, 78)

    def test_shell_characters_stay_one_argument_and_are_never_executed(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / 'injected'
            path = '/home/learner/work/$(touch ' + str(marker) + ');x'
            command = self.plan(changed(arguments(), '--project', path))['bwrap_argv']
            self.assertIn(path, command)
            self.assertFalse(marker.exists())
            self.assertNotIn('sh', command)
            self.assertNotIn('-c', command)

    def test_browser_requires_exact_wayland_socket(self):
        args = arguments()
        args = args[:args.index('--wayland-socket')]
        self.assertEqual(self.invoke(args).returncode, 78)
        args = changed(args, '--apps', 'cli')
        self.assertEqual(self.invoke(args).returncode, 0)

    def test_cli_requires_pin_and_project_cannot_contain_state(self):
        self.assertEqual(self.invoke(changed(arguments(), '--cli-sha256', 'latest')).returncode, 78)
        self.assertEqual(self.invoke(changed(arguments(), '--project', '/home/learner')).returncode, 78)

    def test_single_fixed_relay_target_no_user_socat_options(self):
        relay = self.plan()['relay_argv']
        self.assertEqual(relay, ['/usr/bin/socat',
                               'TCP4-LISTEN:48921,bind=127.0.0.1,reuseaddr,fork',
                               'UNIX-CONNECT:/transport/proxy.sock'])


class BoundaryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location('session_under_test', LAUNCHER)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def cfg(self):
        return self.module.configuration(self.module.options(arguments()))

    def test_wayland_socket_symlink_resolves_to_one_socket_even_with_0777_mode(self):
        # WSLg exposes a symlink to its compositor socket; connection permissions
        # do not make a Unix socket a writable regular file.
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            root = Path(directory).resolve()
            source = root / 'wayland-0'
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(source))
                source.chmod(0o777)
                link = root / 'runtime-link'
                link.symlink_to(source)
                self.assertTrue(hasattr(self.module, 'validate_wayland_socket'),
                                'Нет отдельной проверки Wayland socket вместо file-permissions gate.')
                self.assertEqual(self.module.validate_wayland_socket(str(link)), str(source))

    def test_wayland_regular_file_and_shared_parent_are_refused(self):
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            root = Path(directory).resolve()
            source = root / 'wayland-0'
            source.write_text('not a compositor')
            self.assertTrue(hasattr(self.module, 'validate_wayland_socket'))
            with self.assertRaises(self.module.Refusal):
                self.module.validate_wayland_socket(str(source))
            source.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(source))
                root.chmod(0o777)
                try:
                    with self.assertRaises(self.module.Refusal):
                        self.module.validate_wayland_socket(str(source))
                finally:
                    root.chmod(0o700)

    def test_missing_host_namespace_evidence_is_not_a_new_namespace(self):
        current = dict(net='net:[2]', mnt='mnt:[2]', pid='pid:[2]', ipc='ipc:[2]', user='user:[2]')
        status = 'NoNewPrivs:\t1\n' + ''.join(name + ':\t00000000\n' for name in
                                            ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'])
        with self.assertRaises(self.module.Refusal):
            self.module.boundary_report(status, current, {}, ['lo'], 'Iface\n', '', [])

    def test_new_namespace_with_extra_interface_or_privilege_refused(self):
        host = {name: name + ':[1]' for name in ['net', 'mnt', 'pid', 'ipc', 'user']}
        current = {name: name + ':[2]' for name in host}
        status = 'NoNewPrivs:\t1\n' + ''.join(name + ':\t00000000\n' for name in
                                            ['CapInh', 'CapPrm', 'CapEff', 'CapBnd', 'CapAmb'])
        self.module.boundary_report(status, current, host, ['lo'], 'Iface\n', '', [])
        cases = [(status, ['lo', 'eth0'], []), (status.replace('CapEff:\t00000000', 'CapEff:\t00000001'), ['lo'], []),
                 (status.replace('NoNewPrivs:\t1', 'NoNewPrivs:\t0'), ['lo'], []), (status, ['lo'], ['/init'])]
        for body, interfaces, forbidden in cases:
            with self.subTest(interfaces=interfaces, forbidden=forbidden):
                with self.assertRaises(self.module.Refusal):
                    self.module.boundary_report(body, current, host, interfaces, 'Iface\n', '', forbidden)

    def test_ssh_command_cannot_disable_pinning_or_add_proxycommand(self):
        cfg = self.cfg()
        argv = ['/usr/bin/ssh', '-F', '/home/learner/.config/almaty-access/ssh_config', '-NT', 'almaty-access']
        self.assertEqual(self.module.validate_ssh_argv(argv, cfg), '/home/learner/.config/almaty-access/ssh_config')
        variants = [argv[:-1] + ['-o', 'StrictHostKeyChecking=no', argv[-1]],
                    argv[:-1] + ['-o', 'ProxyCommand=sh -c something', argv[-1]],
                    argv[:-1] + ['-L', '/tmp/other.sock:127.0.0.1:22', argv[-1]]]
        for variant in variants:
            with self.assertRaises(self.module.Refusal):
                self.module.validate_ssh_argv(variant, cfg)

    def test_generated_config_rejects_include_match_and_other_trust_sources(self):
        cfg = self.cfg()
        body = '''Host almaty-access
HostName 203.0.113.10
User almaty-tunnel
Port 22
IdentityFile "/home/learner/.config/almaty-access/tunnel_ed25519"
UserKnownHostsFile "/home/learner/.config/almaty-access/known_hosts"
GlobalKnownHostsFile /dev/null
UpdateHostKeys no
VerifyHostKeyDNS no
PasswordAuthentication no
KbdInteractiveAuthentication no
StrictHostKeyChecking yes
BatchMode yes
IdentitiesOnly yes
ForwardAgent no
ForwardX11 no
ExitOnForwardFailure yes
ConnectTimeout 10
ServerAliveInterval 15
ServerAliveCountMax 2
StreamLocalBindMask 0177
StreamLocalBindUnlink yes
LocalForward "/home/learner/.config/almaty-access/proxy.sock" 127.0.0.1:48921
'''
        self.assertTrue(hasattr(self.module, 'validate_ssh_config'), 'Нет проверки нового конфигурационного транспорта.')
        self.assertEqual(self.module.validate_ssh_config(body, cfg), '/home/learner/.config/almaty-access/tunnel_ed25519')
        if Path('/usr/bin/ssh').is_file():
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'ssh_config'
                path.write_text(body)
                self.module.check_effective_ssh(str(path), cfg, '/home/learner/.config/almaty-access/tunnel_ed25519')
        variants = [body + 'Include /tmp/other\n', body + 'Match exec "touch /tmp/test"\n',
                    body.replace('GlobalKnownHostsFile /dev/null', 'GlobalKnownHostsFile /etc/ssh/ssh_known_hosts'),
                    body.replace('StrictHostKeyChecking yes', 'StrictHostKeyChecking no'),
                    body.replace('127.0.0.1:48921', '127.0.0.1:22'),
                    body.replace('Host almaty-access', 'Host *')]
        for variant in variants:
            with self.assertRaises(self.module.Refusal):
                self.module.validate_ssh_config(variant, cfg)

    def test_wsl_configuration_and_live_interop_both_must_be_closed(self):
        config = '[interop]\nenabled=false\nappendWindowsPath=false\n[automount]\nenabled=false\nmountFsTab=false\n[network]\ngenerateResolvConf=false\n'
        self.module.validate_wsl(config, [], {})
        for body, entries, env in [(config.replace('enabled=false', 'enabled=true', 1), [], {}),
                                    (config, ['WSLInterop'], {}), (config, [], {'WSL_INTEROP': '/run/interop'}),
                                    ('[interop]\nenabled=false', [], {})]:
            with self.assertRaises(self.module.Refusal):
                self.module.validate_wsl(body, entries, env)

    def test_project_symlink_does_not_open_host_files(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / 'regular').write_text('test')
            self.module.tree_has_only_data(project)
            (project / 'host-link').symlink_to('/run')
            with self.assertRaises(self.module.Refusal):
                self.module.tree_has_only_data(project)

    def test_unreadable_project_subtree_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            private = project / 'unreadable'
            private.mkdir()
            (private / 'hidden-host-link').symlink_to('/run')
            private.chmod(0)
            try:
                with self.assertRaises(self.module.Refusal):
                    self.module.tree_has_only_data(project)
            finally:
                private.chmod(0o700)

    def test_writable_project_hardlink_cannot_reach_external_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outside = root / 'outside'
            outside.write_text('keep')
            project = root / 'project'
            project.mkdir()
            (project / 'linked').hardlink_to(outside)
            with self.assertRaises(self.module.Refusal):
                self.module.tree_has_only_data(project)

    def test_generated_state_hardlink_cannot_truncate_external_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            outside = root / 'external-project'
            outside.write_text('keep this data')
            outside.chmod(0o600)
            state = root / 'state'
            state.mkdir(mode=0o700)
            (state / 'hosts').hardlink_to(outside)
            with self.assertRaisesRegex(self.module.Refusal, 'hardlink'):
                self.module.write_private(state / 'hosts', 'replacement')
            self.assertEqual(outside.read_text(), 'keep this data')

    def test_existing_empty_or_unrelated_state_is_not_adopted(self):
        self.assertTrue(hasattr(self.module, 'validate_state'), 'Нет проверки принадлежности persistent state.')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            state = root / 'state'
            state.mkdir(mode=0o700)
            cfg = self.cfg()
            cfg['state'] = str(state)
            with self.assertRaises(self.module.Refusal):
                self.module.validate_state(cfg)
            marker = state / 'session.json'
            marker.write_text(json.dumps({'schema': 'unrelated', 'state_identity': {}}))
            marker.chmod(0o600)
            with self.assertRaises(self.module.Refusal):
                self.module.validate_state(cfg)
            self.assertEqual(json.loads(marker.read_text())['schema'], 'unrelated')

    def test_own_state_requires_same_project_and_cli_identity(self):
        self.assertTrue(hasattr(self.module, 'validate_state'), 'Нет проверки принадлежности persistent state.')
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory).resolve() / 'state'
            cfg = self.cfg()
            cfg['state'] = str(state)
            self.assertFalse(self.module.validate_state(cfg))
            state.mkdir(mode=0o700)
            (state / 'home').mkdir(mode=0o700)
            marker = {'schema': 'almaty-whole-session-experiment-v1', 'state_identity': {
                'owner_uid': __import__('os').getuid(), 'project': cfg['project'], 'cli': cfg['cli'],
                'cli_sha256': cfg['cli_sha256'], 'chrome_dir': cfg['chrome_dir']}}
            path = state / 'session.json'
            path.write_text(json.dumps(marker))
            path.chmod(0o600)
            self.assertTrue(self.module.validate_state(cfg))
            debug = state / 'home/.claude/debug'
            debug.mkdir(parents=True)
            (debug / 'example-session.txt').write_text('log')
            (debug / 'latest').symlink_to('/home/guest/.claude/debug/example-session.txt')
            self.assertTrue(self.module.validate_state(cfg), 'Штатная ссылка Claude не должна ломать resume.')
            changed_cfg = dict(cfg, cli_sha256='1' * 64)
            with self.assertRaises(self.module.Refusal):
                self.module.validate_state(changed_cfg)

    def test_private_home_links_resolve_in_guest_home_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory).resolve() / 'home'
            home.mkdir()
            (home / 'log').write_text('keep')
            (home / 'latest').symlink_to('log')
            (home / 'chain').symlink_to('/home/guest/latest')
            self.assertTrue(hasattr(self.module, 'validate_private_home'))
            self.module.validate_private_home(home)
            for target in ('../outside', '/etc/passwd', '/home/guest/missing', 'chain'):
                with self.subTest(target=target):
                    (home / 'latest').unlink()
                    (home / 'latest').symlink_to(target)
                    with self.assertRaises((self.module.Refusal, OSError)):
                        self.module.validate_private_home(home)
            (home / 'latest').unlink()
            (home / 'latest').symlink_to('log')
            (home / 'fifo').touch()
            (home / 'fifo').unlink()
            os.mkfifo(home / 'fifo')
            with self.assertRaises(self.module.Refusal):
                self.module.validate_private_home(home)

    def test_private_generated_write_preserves_mode_without_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve() / 'state.json'
            self.module.write_private(path, 'first')
            before = path.stat().st_ino
            self.module.write_private(path, 'second')
            self.assertEqual(path.read_text(), 'second')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotEqual(path.stat().st_ino, before)

    def test_proc_unix_socket_path_can_contain_spaces(self):
        self.assertTrue(hasattr(self.module, 'socket_kernel_inode'), 'Нет безопасного разбора /proc/net/unix.')
        text = 'Num RefCount Protocol Flags Type St Inode Path\n0001: 00000002 00000000 00010000 0001 01 123 /home/test user/прокси.sock\n'
        self.assertEqual(self.module.socket_kernel_inode(text, '/home/test user/прокси.sock'), '123')


if __name__ == '__main__':
    unittest.main()
