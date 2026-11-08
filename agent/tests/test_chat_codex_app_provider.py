"""Synthetic tests for the disabled app-server provider candidate."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.chat_codex import CodexProvider
from agent.chat_codex_app_provider import AppServerCandidateProvider
from agent.tests import test_chat_codex_app_server as process_fixtures
from agent.tests import test_chat_codex_dynamic as relay_fixtures


class AppServerCandidateProviderTest(unittest.TestCase):
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
                 patch.object(CodexProvider, 'is_available', return_value=True):
                provider = AppServerCandidateProvider(base, agent_home=home)
                events = list(provider.start_turn('request review'))
            self.assertEqual(events[-1], ('done', {}))
            self.assertEqual(fixture.client.calls, [('decide', 'candidate_decide', {}, 'abc')])
            self.assertTrue(base.process_supervisor.stopped)

    def test_gate_is_closed_by_default(self):
        with self.assertRaisesRegex(ValueError, 'not-ready'):
            AppServerCandidateProvider(None, agent_home='/synthetic')


if __name__ == '__main__':
    unittest.main()
