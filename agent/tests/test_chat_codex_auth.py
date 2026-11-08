import os
import stat
import tempfile
import unittest
from pathlib import Path

from agent.chat_codex_auth import (
    CodexAuthError, codex_auth_lock, login_cancel_request, login_start_request,
    prepare_codex_home, validate_credentials, login_completed,
)


class CodexAuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name)

    def test_private_home_created_and_no_credentials_required(self):
        home = Path(prepare_codex_home(str(self.parent)))
        self.assertEqual(home, self.parent / 'codex-auth')
        self.assertEqual(stat.S_IMODE(home.stat().st_mode), 0o700)
        self.assertFalse(validate_credentials(str(home)))

    def test_unsafe_parent_or_child_rejected(self):
        os.chmod(self.parent, 0o755)
        with self.assertRaises(CodexAuthError):
            prepare_codex_home(str(self.parent))
        os.chmod(self.parent, 0o700)
        (self.parent / 'codex-auth').symlink_to(self.parent)
        with self.assertRaises(CodexAuthError):
            prepare_codex_home(str(self.parent))

    def test_credentials_require_private_regular_owned_single_link_file(self):
        home = Path(prepare_codex_home(str(self.parent)))
        auth = home / 'auth.json'
        auth.write_text('synthetic only')
        os.chmod(auth, 0o600)
        self.assertTrue(validate_credentials(str(home)))
        os.chmod(auth, 0o644)
        with self.assertRaises(CodexAuthError):
            validate_credentials(str(home))
        auth.unlink()
        auth.symlink_to(self.parent / 'elsewhere')
        with self.assertRaises(CodexAuthError):
            validate_credentials(str(home))

    def test_lock_is_exclusive_and_released(self):
        home = prepare_codex_home(str(self.parent))
        with codex_auth_lock(home):
            with self.assertRaises(CodexAuthError):
                with codex_auth_lock(home):
                    pass
        with codex_auth_lock(home):
            pass

    def test_login_completion_requires_matching_attempt_and_private_credentials(self):
        home = Path(prepare_codex_home(str(self.parent)))
        event = {'method': 'account/login/completed', 'params': {'loginId': 'attempt', 'success': True}}
        with self.assertRaises(CodexAuthError):
            login_completed(str(home), 'attempt', event)
        auth = home / 'auth.json'
        auth.write_text('synthetic only')
        os.chmod(auth, 0o600)
        self.assertTrue(login_completed(str(home), 'attempt', event))
        with self.assertRaises(CodexAuthError):
            login_completed(str(home), 'other', event)
        self.assertFalse(login_completed(str(home), 'attempt', {'method': 'account/login/completed', 'params': {'loginId': 'attempt', 'success': False}}))

    def test_login_rpc_only_known_methods_and_cancel_id(self):
        self.assertEqual(login_start_request(1)['params'], {'type': 'chatgpt'})
        self.assertEqual(login_cancel_request(2, 'login-1')['params'], {'loginId': 'login-1'})
        with self.assertRaises(CodexAuthError):
            login_cancel_request(2, '')


if __name__ == '__main__':
    unittest.main()
