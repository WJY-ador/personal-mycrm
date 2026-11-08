import os
import io
import tempfile
import unittest

from agent.chat_codex_login import run_login_dialog, run_login_session
from agent.tests import test_chat_codex_dynamic as fixtures


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
        self.assertEqual(statuses, ['waiting', 'cancelled'])
        self.assertTrue(any(m.get('method') == 'account/login/cancel' for m in transport.sent))

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
