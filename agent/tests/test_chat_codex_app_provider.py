"""Synthetic tests for the disabled app-server provider candidate."""
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from agent.chat_codex import CodexProvider
from agent.chat_codex_app_provider import AppServerCandidateProvider, _build_appserver_argv, _cli_version_supported, inspect_cli_version
from agent.tests import test_chat_codex_app_server as process_fixtures
from agent.tests import test_chat_codex_dynamic as relay_fixtures


class AppServerCandidateProviderTest(unittest.TestCase):
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
            self.assertTrue(base.process_supervisor.stopped)

    def test_gate_is_closed_by_default(self):
        with self.assertRaisesRegex(ValueError, 'not-ready'):
            AppServerCandidateProvider(None, agent_home='/synthetic')


if __name__ == '__main__':
    unittest.main()
