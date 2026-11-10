"""Synthetic tests for the disabled app-server provider candidate."""
import os
import tempfile
import unittest
import json
import sys
import subprocess
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from agent.chat_codex import CodexProvider
from agent.chat_launch_authority import AUTH_PATH, LaunchAuthorizationClient
from agent import chat
from agent.chat_codex_app_provider import AppServerCandidateProvider, _build_appserver_argv, _cli_version_supported, inspect_cli_version
from agent.tests import test_chat_codex_app_server as process_fixtures
from agent.tests import test_chat_codex_dynamic as relay_fixtures
from agent.tests.test_chat_codex import FixtureSupervisor
from agent.tests.helpers import MemoryKeyStore


class AppServerCandidateProviderTest(unittest.TestCase):
    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
    def test_managed_new_version_requires_verified_policy_for_each_launch(self):
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            auth_home = os.path.join(home, 'codex-auth')
            os.mkdir(auth_home, 0o700)
            auth_file = os.path.join(auth_home, 'auth.json')
            with open(auth_file, 'w', encoding='utf-8') as handle:
                handle.write('synthetic')
            os.chmod(auth_file, 0o600)
            fixture = relay_fixtures.DynamicToolRelayTest()
            fixture.setUp()
            context = SimpleNamespace(codex_home=auth_home, cwd=home, runtime_dir=home,
                session_id='s1', turn_id='t1', device_id='d1', model='synthetic',
                env={'CODEX_HOME':auth_home, 'HOME':home, 'PATH':'/usr/bin:/bin'}, current=lambda: True)
            base = object.__new__(CodexProvider)
            base.cli_path, base.model, base.launch_context = '/usr/bin/true', 'synthetic', context
            base.launch_verifier = SimpleNamespace(client=fixture.client, verify_codex_grant=lambda _: True)
            base.process_supervisor, base.timeout = process_fixtures.SyntheticSupervisor(), 3
            store = MemoryKeyStore()
            with patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True), \
                 patch('agent.chat_codex_app_provider._cli_version_supported', return_value=False), \
                 patch('agent.chat_codex_app_provider.verify_managed_cli_locked', side_effect=[True, False]) as verify, \
                 patch.object(CodexProvider, 'is_available', return_value=True):
                provider = AppServerCandidateProvider(base, agent_home=home,
                                                       managed_store=store, managed_version='0.168.0')
                self.assertEqual(list(provider.start_turn('request'))[-1], ('done', {}))
                self.assertEqual(list(provider.start_turn('request'))[-1], ('error', {'code':'CODEX-FAILED'}))
                self.assertEqual(verify.call_count, 2)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
    def test_factory_through_child_and_server_bound_approval_request(self):
        from agent.chat_codex_app_provider import AppServerCandidateFactory
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace('+00:00', 'Z')
        binding = {'user_id':'u_'+'a'*24, 'device_id':'is_'+'b'*24,
                   'session_id':'cs_'+'c'*24, 'turn_id':'ct_'+'d'*24,
                   'provider':'codex', 'model':'synthetic-model', 'grant_id':'grant_synthetic',
                   'consent_challenge_id':'challenge_synthetic', 'expires_at':expiry}
        auth = {'authorized':True, 'binding':binding,
                'tools':{'mcp__my-crm__find':'read','mcp__my-crm__candidate_decide':'decide'}}
        requests = []
        class Reply:
            status = 200
            def __init__(self, payload): self.payload = payload
            def read(self, *_): return json.dumps(self.payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, request, **_kwargs):
                body = json.loads(request.data)
                requests.append((request.full_url, body))
                if request.full_url.endswith(AUTH_PATH):
                    return Reply(auth)
                if request.full_url.endswith('/api/chat/mcp'):
                    return Reply({'result':{'pending_confirmation':True}})
                raise AssertionError('unexpected endpoint')
        class ChildSupervisor(FixtureSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', process_fixtures.CHILD], **kwargs)
                return self.proc
            def terminate_tree(self, proc):
                proc.terminate()
                proc.wait(timeout=3)
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            exe = os.path.join(home, 'synthetic-codex')
            with open(exe, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\nexit 0\n')
            os.chmod(exe, 0o700)
            client = LaunchAuthorizationClient('https://synthetic.invalid', lambda: 'synthetic-token')
            client._opener = Opener()
            with patch.object(sys, 'platform', 'darwin'), \
                 patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True), \
                 patch('agent.chat_codex_app_provider._cli_version_supported', return_value=True):
                factory = AppServerCandidateFactory(client, cli_path=exe,
                    server_url='https://synthetic.invalid', agent_home=home,
                    expected_device_id=binding['device_id'], models=('synthetic-model',),
                    process_supervisor=ChildSupervisor(), timeout=3)
                auth_file = os.path.join(home, 'codex-auth', 'auth.json')
                with open(auth_file, 'w', encoding='utf-8') as handle:
                    handle.write('synthetic')
                os.chmod(auth_file, 0o600)
                provider = factory.create_turn(binding['session_id'], binding['turn_id'], AUTH_PATH,
                                               'codex', 'synthetic-model')
                try:
                    events = list(provider.start_turn('synthetic request'))
                finally:
                    provider.close()
        self.assertEqual(events[-1], ('done', {}))
        mcp = [body for url, body in requests if url.endswith('/api/chat/mcp')]
        self.assertEqual(len(mcp), 1)
        self.assertEqual((mcp[0]['session_id'], mcp[0]['turn_id'], mcp[0]['tool'], mcp[0]['op']),
                         (binding['session_id'], binding['turn_id'], 'decide', 'candidate_decide'))
    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
    def test_app_factory_binds_fresh_authorization_to_isolated_home(self):
        from agent.chat_codex_app_provider import AppServerCandidateFactory
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat().replace('+00:00', 'Z')
        binding = {'user_id':'u_'+'a'*24, 'device_id':'is_'+'b'*24,
                   'session_id':'cs_'+'c'*24, 'turn_id':'ct_'+'d'*24,
                   'provider':'codex', 'model':'synthetic-model', 'grant_id':'grant_synthetic',
                   'consent_challenge_id':'challenge_synthetic', 'expires_at':expiry}
        payload = {'authorized':True, 'binding':binding,
                   'tools':{'mcp__my-crm__find':'read','mcp__my-crm__record_edit':'decide'}}
        class Reply:
            status = 200
            def read(self, *_): return json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            exe = os.path.join(home, 'synthetic-codex')
            with open(exe, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\nexit 0\n')
            os.chmod(exe, 0o700)
            client = LaunchAuthorizationClient('https://synthetic.invalid', lambda: 'synthetic-token')
            client._opener = Opener()
            with patch.object(sys, 'platform', 'darwin'), \
                 patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True):
                factory = AppServerCandidateFactory(client, cli_path=exe,
                    server_url='https://synthetic.invalid', agent_home=home,
                    expected_device_id=binding['device_id'], models=('synthetic-model',),
                    process_supervisor=FixtureSupervisor())
                agent = chat.ChatAgent('wss://synthetic.invalid', 'synthetic', codex_factory=factory)
                self.assertIs(agent.codex_factory, factory)
                provider = factory.create_turn(binding['session_id'], binding['turn_id'], AUTH_PATH,
                                               'codex', 'synthetic-model')
                try:
                    self.assertEqual(provider.base.launch_context.codex_home, os.path.realpath(os.path.join(home, 'codex-auth')))
                    self.assertEqual(provider.base.launch_context.turn_id, binding['turn_id'])
                    self.assertEqual(provider.base.launch_context.device_id, binding['device_id'])
                    self.assertEqual(provider.base.launch_context.tools['mcp__my-crm__decide'], 'decide')
                finally:
                    provider.close()
                with self.assertRaises(Exception):
                    factory.create_turn(binding['session_id'], 'different-turn', AUTH_PATH, 'codex', 'synthetic-model')
                store = MemoryKeyStore()
                with patch('agent.chat_codex_app_provider.resolve_managed_cli',
                           return_value={'version':'0.168.0', 'path':exe}) as resolve:
                    managed = AppServerCandidateFactory(client, cli_path=None, managed_store=store,
                        server_url='https://synthetic.invalid', agent_home=home,
                        expected_device_id=binding['device_id'], models=('synthetic-model',),
                        process_supervisor=FixtureSupervisor())
                    managed_provider = managed.create_turn(binding['session_id'], binding['turn_id'], AUTH_PATH,
                                                            'codex', 'synthetic-model')
                    try:
                        self.assertEqual(managed_provider._managed_version, '0.168.0')
                        self.assertIs(managed_provider._managed_store, store)
                        self.assertGreaterEqual(resolve.call_count, 2)
                    finally:
                        managed_provider.close()

    def test_factory_refuses_registration_when_candidate_gate_is_closed(self):
        from agent.chat_codex_app_provider import AppServerCandidateFactory
        with patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', False):
            with self.assertRaisesRegex(ValueError, 'not-ready'):
                AppServerCandidateFactory(None, cli_path='/synthetic', server_url='https://synthetic.invalid',
                    agent_home='/synthetic', expected_device_id='synthetic', models=('synthetic',))

    def test_version_diagnostics_distinguish_unverified_and_old_versions(self):
        with patch('agent.chat_codex_app_provider._capture_version_output') as run:
            for output, expected, action in [
                ('codex-cli 0.166.0\n', 'supported', 'none'),
                ('codex-cli 0.167.0\n', 'supported', 'none'),
                ('codex-cli 0.165.0\n', 'too_old', 'update_codex'),
                ('codex-cli 0.168.0\n', 'unverified_newer', 'update_mycrm'),
                ('codex-cli 0.166.1-rc.1\n', 'unverified_version', 'update_mycrm'),
            ]:
                with self.subTest(output=output):
                    run.return_value = output
                    result = inspect_cli_version('/synthetic/codex', cwd='/synthetic', env={})
                    self.assertEqual(result['status'], expected)
                    self.assertEqual(result['recommended_action'], action)
                    self.assertEqual(result['supported_versions'], ['0.166.0', '0.167.0'])

    def test_malformed_version_and_process_failure_do_not_expose_output(self):
        with patch('agent.chat_codex_app_provider._capture_version_output') as run:
            for value in [None, 'sensitive']:
                run.return_value = value
                result = inspect_cli_version('/synthetic/codex', cwd='/synthetic', env={})
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['installed_version'])
                self.assertNotIn('sensitive', repr(result))

    @unittest.skipIf(os.name == 'nt', 'synthetic POSIX executable')
    def test_version_probe_rejects_oversized_output(self):
        with tempfile.TemporaryDirectory() as home:
            executable = os.path.join(home, 'codex')
            with open(executable, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\nexec /usr/bin/yes x\n')
            os.chmod(executable, 0o700)
            result = inspect_cli_version(executable, cwd=home, env={'PATH':'/usr/bin:/bin'})
            self.assertEqual(result['status'], 'unavailable')
            self.assertIsNone(result['installed_version'])

    @unittest.skipIf(os.name != 'posix', 'synthetic POSIX executable')
    def test_version_probe_times_out_when_descendant_holds_output_open(self):
        import signal
        with tempfile.TemporaryDirectory() as home:
            executable = os.path.join(home, 'codex')
            with open(executable, 'w', encoding='utf-8') as handle:
                handle.write('#!/bin/sh\n(sleep 20) &\nexit 0\n')
            os.chmod(executable, 0o700)
            code = ("from agent.chat_codex_app_provider import inspect_cli_version; import sys; "
                    "print(inspect_cli_version(sys.argv[1],cwd=sys.argv[2],env={'PATH':'/usr/bin:/bin'})['status'])")
            process = subprocess.Popen([sys.executable, '-c', code, executable, home],
                start_new_session=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                try:
                    stdout, stderr = process.communicate(timeout=8)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    self.fail('version inspection did not return within its time limit')
                self.assertEqual(process.returncode, 0, stderr.decode('utf-8', 'replace'))
                self.assertEqual(stdout.strip(), b'unavailable')
            finally:
                if process.poll() is None:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()

    def test_known_cli_version_required_and_other_versions_fail_closed(self):
        with patch('agent.chat_codex_app_provider._capture_version_output') as run:
            run.return_value = 'codex-cli 0.166.0\n'
            self.assertTrue(_cli_version_supported('/synthetic/codex', cwd='/synthetic', env={}))
            run.return_value = 'codex-cli 0.168.0\n'
            self.assertFalse(_cli_version_supported('/synthetic/codex', cwd='/synthetic', env={}))

    def test_candidate_uses_synthetic_verified_tool_restrictions(self):
        argv = _build_appserver_argv('/synthetic/codex')
        self.assertIn('features.code_mode_host=true', argv)
        self.assertIn('features.goals=false', argv)
        self.assertNotIn('features.code_mode_host=false', argv)
        self.assertIn('agents.enabled=false', argv)
        self.assertIn('tools.experimental_request_user_input.enabled=false', argv)
        self.assertIn('web_search="disabled"', argv)
        self.assertIn('mcp_servers={}', argv)

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
    def test_user_approved_pending_action_runs_through_bridge(self):
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            auth_home = os.path.join(home, 'codex-auth')
            os.mkdir(auth_home, 0o700)
            auth_file = os.path.join(auth_home, 'auth.json')
            with open(auth_file, 'w', encoding='utf-8') as handle:
                handle.write('synthetic')
            os.chmod(auth_file, 0o600)
            fixture = relay_fixtures.DynamicToolRelayTest()
            fixture.setUp()
            context = SimpleNamespace(codex_home=auth_home, cwd=home, runtime_dir=home,
                session_id='s1', turn_id='t1', device_id='d1', model='synthetic',
                env={'CODEX_HOME':auth_home, 'HOME':home, 'PATH':'/usr/bin:/bin'},
                current=lambda: True)
            verifier = SimpleNamespace(client=fixture.client, verify_codex_grant=lambda _: True)
            base = object.__new__(CodexProvider)
            base.cli_path = '/usr/bin/true'
            base.model = 'synthetic'
            base.launch_context = context
            base.launch_verifier = verifier
            base.process_supervisor = process_fixtures.SyntheticSupervisor()
            base.timeout = 3
            with patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True), \
                 patch('agent.chat_codex_app_provider._cli_version_supported', return_value=True), \
                 patch.object(CodexProvider, 'is_available', return_value=True):
                provider = AppServerCandidateProvider(base, agent_home=home)
                events = list(provider.start_turn('request review'))
            self.assertEqual(events[-1], ('done', {}))
            self.assertEqual(fixture.client.calls, [('decide', 'candidate_decide', {}, 'abc')])

    @unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
    def test_missing_account_reports_login_required_and_never_starts_turn(self):
        child = ("import json,sys\n"
                 "def read(): return json.loads(sys.stdin.buffer.readline())\n"
                 "def send(x): print(json.dumps(x),flush=True)\n"
                 "x=read(); send({'id':x['id'],'result':{}})\n"
                 "read()\n"
                 "x=read(); assert x['method']=='account/read'; "
                 "send({'id':x['id'],'result':{'account':None}})\n"
                 "sys.stdin.buffer.read()\n")
        class NoAccountSupervisor(process_fixtures.SyntheticSupervisor):
            def spawn(self, argv, **kwargs):
                self.proc = subprocess.Popen([sys.executable, '-u', '-c', child], **kwargs)
                return self.proc
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            auth_home = os.path.join(home, 'codex-auth')
            os.mkdir(auth_home, 0o700)
            auth_file = os.path.join(auth_home, 'auth.json')
            with open(auth_file, 'w', encoding='utf-8') as handle:
                handle.write('synthetic')
            os.chmod(auth_file, 0o600)
            fixture = relay_fixtures.DynamicToolRelayTest()
            fixture.setUp()
            context = SimpleNamespace(codex_home=auth_home, cwd=home, runtime_dir=home,
                session_id='s1', turn_id='t1', device_id='d1', model='synthetic',
                env={'CODEX_HOME':auth_home, 'HOME':home, 'PATH':'/usr/bin:/bin'}, current=lambda: True)
            base = object.__new__(CodexProvider)
            base.cli_path, base.model, base.launch_context = '/usr/bin/true', 'synthetic', context
            base.launch_verifier = SimpleNamespace(client=fixture.client, verify_codex_grant=lambda _: True)
            base.process_supervisor, base.timeout = NoAccountSupervisor(), 3
            with patch('agent.chat_codex_app_provider.APP_SERVER_CANDIDATE_READY', True), \
                 patch('agent.chat_codex_app_provider._cli_version_supported', return_value=True), \
                 patch.object(CodexProvider, 'is_available', return_value=True):
                events = list(AppServerCandidateProvider(base, agent_home=home).start_turn('hello'))
            self.assertEqual(events, [('error', {'code':'CODEX-LOGIN-REQUIRED'})])
            self.assertEqual(fixture.client.calls, [])
            self.assertTrue(base.process_supervisor.stopped)

    def test_gate_is_closed_by_default(self):
        with self.assertRaisesRegex(ValueError, 'not-ready'):
            AppServerCandidateProvider(None, agent_home='/synthetic')


if __name__ == '__main__':
    unittest.main()
