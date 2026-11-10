import os
import io
import tempfile
import unittest
from unittest.mock import patch

from agent.chat_codex_login import run_login_dialog, run_login_session
from agent.tests import test_chat_codex_dynamic as fixtures
from agent.tests.helpers import MemoryKeyStore


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
class CodexLoginDialogTests(unittest.TestCase):
    def test_login_success_opens_browser_without_disclosing_url_in_status(self):
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            with open(os.path.join(home, 'auth.json'), 'w', encoding='utf8') as stream:
                stream.write('synthetic')
            os.chmod(os.path.join(home, 'auth.json'), 0o600)
            url = 'https://auth.openai.com/authorize?state=synthetic'
            transport = fixtures.SyntheticTransport([
                {'id':1,'result':{}},
                {'id':2,'result':{'type':'chatgpt','loginId':'synthetic','authUrl':url}},
                {'method':'account/login/completed','params':{'loginId':'synthetic','success':True}},
                {'id':4,'result':{'account':{'type':'chatgpt'}}},
            ])
            opened, statuses = [], []
            status = run_login_dialog(transport, home, lambda value: opened.append(value) or True,
                                      lambda: False, statuses.append, timeout=3)
            self.assertEqual(status, 'completed')
            self.assertEqual(opened, [url])
            self.assertEqual(statuses, ['waiting', 'completed'])
            self.assertNotIn(url, repr(statuses))

    def test_untrusted_browser_origin_is_rejected(self):
        transport = fixtures.SyntheticTransport([
            {'id':1,'result':{}},
            {'id':2,'result':{'type':'chatgpt','loginId':'synthetic','authUrl':'https://evil.invalid/test'}},
        ])
        opened, statuses = [], []
        with self.assertRaises(ValueError):
            run_login_dialog(transport, '/synthetic', opened.append, lambda:False, statuses.append, timeout=3)
        self.assertEqual(opened, [])

    def test_cancel_ends_login_without_completing(self):
        transport = fixtures.SyntheticTransport([
            {'id':1,'result':{}},
            {'id':2,'result':{'type':'chatgpt','loginId':'synthetic','authUrl':'https://auth.openai.com/authorize'}},
            {'id':3,'result':{'status':'canceled'}},
        ])
        statuses = []
        status = run_login_dialog(transport, '/synthetic', lambda _:True, lambda:True, statuses.append, timeout=3)
        self.assertEqual(status, 'cancelled')
        self.assertEqual(statuses, ['cancelled'])
        self.assertTrue(any(m.get('method') == 'account/login/cancel' for m in transport.sent))

    def test_cancel_during_login_start_does_not_open_browser(self):
        state = {'cancelled': False}
        class CancelsOnStart(fixtures.SyntheticTransport):
            def receive(self, timeout):
                event = super().receive(timeout)
                if event.get('id') == 2:
                    state['cancelled'] = True
                return event
        transport = CancelsOnStart([
            {'id':1,'result':{}},
            {'id':2,'result':{'type':'chatgpt','loginId':'synthetic','authUrl':'https://auth.openai.com/authorize'}},
            {'id':3,'result':{'status':'canceled'}},
        ])
        opened, statuses = [], []
        result = run_login_dialog(transport, '/synthetic', lambda url: opened.append(url) or True,
                                  lambda: state['cancelled'], statuses.append, timeout=3)
        self.assertEqual(result, 'cancelled')
        self.assertEqual(opened, [])
        self.assertEqual(statuses, ['cancelled'])

    def test_cancel_waits_for_delayed_cancel_response(self):
        class Delayed(fixtures.SyntheticTransport):
            def __init__(self, events):
                super().__init__(events)
                self.delayed = False
            def receive(self, timeout):
                if self.sent and self.sent[-1].get('method') == 'account/login/cancel' and not self.delayed:
                    self.delayed = True
                    raise TimeoutError()
                return super().receive(timeout)
        transport = Delayed([
            {'id':1,'result':{}},
            {'id':2,'result':{'type':'chatgpt','loginId':'synthetic','authUrl':'https://auth.openai.com/authorize'}},
            {'id':3,'result':{'status':'canceled'}},
        ])
        statuses = []
        self.assertEqual(run_login_dialog(transport, '/synthetic', lambda _:True, lambda:True,
                                          statuses.append, timeout=3), 'cancelled')

    def test_session_gate_is_closed_by_default(self):
        statuses = []
        self.assertEqual(run_login_session('/tmp/synthetic', '/usr/bin/true',
            cancelled=lambda:False, report=statuses.append), 'unavailable')
        self.assertEqual(statuses, ['unavailable'])

    def test_hidden_cli_returns_fixed_unavailable_without_login_url(self):
        from agent import cli
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as home:
            code = cli.main(['--home', home, 'codex-app-login'], out=output, stdin=io.StringIO(''))
        self.assertEqual(code, cli.EXIT_ERR)
        self.assertEqual(output.getvalue(), '{"status":"unavailable"}\n')

    def test_managed_login_rechecks_policy_before_spawning(self):
        class Supervisor:
            def spawn(self, *_args, **_kwargs):
                self.fail('unverified login executable must not start')
            def fail(self, message):
                raise AssertionError(message)
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            statuses = []
            with patch('agent.chat_codex_login.APP_SERVER_LOGIN_READY', True), \
                 patch('agent.chat_codex_update.verify_managed_cli_locked', return_value=False) as verify:
                result = run_login_session(home, '/usr/bin/true', cancelled=lambda:False,
                    report=statuses.append, supervisor=Supervisor(), managed_store=MemoryKeyStore(),
                    managed_version='0.168.0')
            self.assertEqual(result, 'error')
            self.assertEqual(statuses, ['error'])
            self.assertEqual(verify.call_count, 1)

    def test_unmanaged_login_is_never_started_when_feature_enabled(self):
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            statuses = []
            with patch('agent.chat_codex_login.APP_SERVER_LOGIN_READY', True), \
                 patch('agent.chat_process_supervisor.MacOSProcessSupervisor.spawn') as spawn:
                result = run_login_session(home, '/usr/bin/true', cancelled=lambda:False,
                                           report=statuses.append)
            self.assertEqual(result, 'error')
            self.assertEqual(statuses, ['error'])
            spawn.assert_not_called()

    def test_desktop_login_uses_managed_binary_without_global_cli(self):
        from types import SimpleNamespace
        from agent import cli
        output = io.StringIO()
        store = MemoryKeyStore()
        ctx = SimpleNamespace(paths=SimpleNamespace(home='/synthetic-home', ensure=lambda: None),
                              keystore=lambda _:store, stdin=io.StringIO(''),
                              out=output, browser_open=lambda _:True)
        with patch('agent.chat_codex_login.APP_SERVER_LOGIN_READY', True), \
             patch('agent.cli._config.load', return_value={'summary':{}}), \
             patch.dict(os.environ, {'OPENAI_API_KEY':'synthetic-key', 'ANTHROPIC_BASE_URL':'https://synthetic.invalid'}), \
             patch('threading.Thread.start'), \
             patch('agent.chat_codex_prepare.run_preparation',
                   return_value={'path':'/synthetic-managed/codex','version':'0.168.0'}) as prepare, \
             patch('agent.chat_codex_login.run_login_session', return_value='completed') as run:
            self.assertEqual(cli.cmd_codex_app_login(ctx, None), cli.EXIT_OK)
        self.assertNotIn('OPENAI_API_KEY', prepare.call_args.kwargs['env'])
        self.assertNotIn('ANTHROPIC_BASE_URL', prepare.call_args.kwargs['env'])
        self.assertEqual(run.call_args.args[:2], ('/synthetic-home','/synthetic-managed/codex'))
        self.assertIs(run.call_args.kwargs['managed_store'], store)
        self.assertEqual(run.call_args.kwargs['managed_version'], '0.168.0')

    def test_login_cancel_is_received_before_cli_preparation_completes(self):
        import time
        from types import SimpleNamespace
        from agent import cli
        from agent.chat_codex_prepare import PreparationCancelled
        output = io.StringIO()
        ctx = SimpleNamespace(paths=SimpleNamespace(home='/synthetic-home', ensure=lambda: None),
                              keystore=lambda _:MemoryKeyStore(), stdin=io.StringIO('cancel\n'),
                              out=output, browser_open=lambda _:True)
        def preparation(_argv, *, cancelled, env):
            deadline = time.monotonic() + 1
            while not cancelled() and time.monotonic() < deadline:
                time.sleep(0.01)
            if cancelled():
                raise PreparationCancelled()
            self.fail('cancel was not received')
        with patch('agent.chat_codex_login.APP_SERVER_LOGIN_READY', True), \
             patch('agent.cli._config.load', return_value={'summary':{}}), \
             patch('agent.chat_codex_prepare.run_preparation', side_effect=preparation), \
             patch('agent.chat_codex_login.run_login_session') as run:
            self.assertEqual(cli.cmd_codex_app_login(ctx, None), cli.EXIT_OK)
        run.assert_not_called()
        self.assertEqual(output.getvalue(), '{"status":"cancelled"}\n')


@unittest.skipUnless(os.name == 'posix' and hasattr(os, 'O_NOFOLLOW'), 'private POSIX storage required')
class CodexAppLoginFreshHomeTests(unittest.TestCase):
    def test_desktop_login_creates_private_home_before_preparation(self):
        import stat
        from agent import cli
        from agent.chat_codex_prepare import PreparationCancelled
        seen = {}
        with tempfile.TemporaryDirectory() as root:
            home = os.path.join(root, 'home')
            def preparation(_argv, *, cancelled, env):
                seen['mode'] = stat.S_IMODE(os.stat(home).st_mode)
                raise PreparationCancelled()
            output = io.StringIO()
            with patch('agent.chat_codex_login.APP_SERVER_LOGIN_READY', True), \
                 patch('threading.Thread.start'), \
                 patch('agent.chat_codex_prepare.run_preparation', side_effect=preparation), \
                 patch('agent.chat_codex_login.run_login_session') as run:
                code = cli.main(['--home', home, 'codex-app-login'], out=output, stdin=io.StringIO(''))
        self.assertEqual(code, cli.EXIT_OK)
        self.assertEqual(seen.get('mode'), 0o700)
        run.assert_not_called()
        self.assertEqual(output.getvalue(), '{"status":"cancelled"}\n')
