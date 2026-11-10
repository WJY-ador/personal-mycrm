import base64
import contextlib
import hashlib
import io
import json
import os
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agent.chat_codex_update import _Updater, _fetch_policy
from agent.tests.helpers import MemoryKeyStore


def make_archive(native, host):
    result = io.BytesIO()
    with tarfile.open(fileobj=result, mode='w:gz') as tar:
        for name, contents in [('codex', native), ('codex-code-mode-host', host)]:
            info = tarfile.TarInfo('package/vendor/aarch64-apple-darwin/bin/' + name)
            info.size = len(contents)
            tar.addfile(info, io.BytesIO(contents))
    return result.getvalue()


class ManagedUpdateTest(unittest.TestCase):
    def test_policy_url_is_scoped_to_build_digest(self):
        with patch('agent.chat_codex_update._open_https') as opened:
            opened.return_value.__enter__.return_value.read.return_value = b'signed'
            self.assertEqual(_fetch_policy('arm64', 'b' * 64), b'signed')
            self.assertIn('/darwin-arm64-' + 'b' * 64 + '.json', opened.call_args.args[0])

    def test_policy_url_rejects_non_digest_before_network(self):
        with patch('agent.chat_codex_update._open_https') as opened:
            with self.assertRaises(ValueError):
                _fetch_policy('arm64', '../invalid')
            opened.assert_not_called()

    def setUp(self):
        self.home = tempfile.TemporaryDirectory(prefix='mycrm-update-test-')
        os.chmod(self.home.name, 0o700)
        self.key = Ed25519PrivateKey.generate()
        self.public = self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.store = MemoryKeyStore()
        self.now = 1780000000
        self.native, self.host = b'synthetic-native', b'synthetic-host'
        self.entry = {'version': '0.167.0', 'native_sha256': hashlib.sha256(self.native).hexdigest(),
                      'host_sha256': hashlib.sha256(self.host).hexdigest()}
        self.payload = {'schema': 2, 'revision': 1, 'issued_at': self.now - 1, 'expires_at': self.now + 3600,
                        'os': 'darwin', 'arch': 'arm64', 'min_app': '0.1.2', 'source_sha': 'a' * 40,
                        'config_sha256': 'b' * 64, 'versions': [self.entry]}
        self.policy = self.sign(self.payload)
        self.archive = make_archive(self.native, self.host)

    def tearDown(self):
        self.home.cleanup()

    def sign(self, payload):
        raw = json.dumps(payload, separators=(',', ':')).encode()
        return json.dumps({'key_id':'test', 'payload':base64.b64encode(raw).decode(),
                           'signature':base64.b64encode(self.key.sign(raw)).decode()}).encode()

    def updater(self, fetch_policy=None, fetch_archive=None):
        return _Updater(keys={'test': self.public}, store=self.store, lock=contextlib.nullcontext(),
                        now=lambda: self.now, config_sha256='b' * 64, app_version='0.1.2',
                        os_name='darwin', arch='arm64',
                        fetch_policy=fetch_policy or (lambda _: self.policy),
                        fetch_archive=fetch_archive or (lambda _: io.BytesIO(self.archive)))

    def test_signed_policy_installs_exact_binary_and_offline_cache_reuses_it(self):
        first = self.updater().resolve(self.home.name)
        self.assertEqual(first['version'], '0.167.0')
        self.assertTrue(os.path.isfile(first['path']))
        def offline(_):
            raise OSError('offline')
        second = self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name)
        self.assertEqual(first, second)

    def test_version_diagnostic_uses_only_local_cache_and_never_downloads(self):
        first = self.updater().resolve(self.home.name)
        def unexpected(_):
            self.fail('diagnostic must not access network')
        local = self.updater(fetch_policy=unexpected, fetch_archive=unexpected)
        self.assertEqual(local.inspect(self.home.name), first)

    def test_version_diagnostic_reports_setup_when_cache_is_absent(self):
        def unexpected(_):
            self.fail('diagnostic must not access network')
        with self.assertRaisesRegex(ValueError, '^managed-cli-setup-required$'):
            self.updater(fetch_policy=unexpected, fetch_archive=unexpected).inspect(self.home.name)

    def test_builds_keep_separate_cached_policies(self):
        first = self.updater().resolve(self.home.name)
        other_policy = self.sign({**self.payload, 'config_sha256':'c' * 64})
        other = _Updater(keys={'test': self.public}, store=self.store, lock=contextlib.nullcontext(),
                         now=lambda: self.now, config_sha256='c' * 64, app_version='0.1.2',
                         os_name='darwin', arch='arm64', fetch_policy=lambda _: other_policy,
                         fetch_archive=lambda _: io.BytesIO(self.archive))
        self.assertEqual(other.resolve(self.home.name), first)
        def offline(_):
            raise OSError('offline')
        self.assertEqual(self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name), first)

    def test_interrupted_cache_commit_recovers_signed_pending_policy_offline(self):
        from agent.chat_codex_update import _save_cache
        first = self.updater().resolve(self.home.name)
        self.policy = self.sign({**self.payload, 'revision':2})
        def interrupted(directory, raw, arch, config_sha256, *, pending=False):
            if not pending:
                raise OSError('simulated interruption')
            return _save_cache(directory, raw, arch, config_sha256, pending=pending)
        with patch('agent.chat_codex_update._save_cache', side_effect=interrupted):
            with self.assertRaises(OSError):
                self.updater().resolve(self.home.name)
        def offline(_):
            raise OSError('offline')
        self.assertEqual(self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name), first)

    def test_interruption_before_checkpoint_commit_recovers_signed_pending_policy(self):
        first = self.updater().resolve(self.home.name)
        self.policy = self.sign({**self.payload, 'revision':2})
        with patch('agent.chat_codex_update.accept_policy', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                self.updater().resolve(self.home.name)
        def offline(_):
            raise OSError('offline')
        self.assertEqual(self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name), first)

    def test_rejected_rollback_does_not_prevent_offline_recovery(self):
        self.updater().resolve(self.home.name)
        newer = self.sign({**self.payload, 'revision':2})
        self.policy = newer
        expected = self.updater().resolve(self.home.name)
        self.policy = self.sign(self.payload)
        with self.assertRaises(ValueError):
            self.updater().resolve(self.home.name)
        def offline(_):
            raise OSError('offline')
        self.assertEqual(self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name), expected)

    def test_invalid_fetched_signature_never_falls_back_to_cached_policy(self):
        self.updater().resolve(self.home.name)
        with self.assertRaises(ValueError):
            self.updater(fetch_policy=lambda _: b'not a signed policy').resolve(self.home.name)

    def test_expired_cached_policy_never_authorizes_offline(self):
        self.updater().resolve(self.home.name)
        self.now += 3601
        def offline(_):
            raise OSError('offline')
        with self.assertRaises(ValueError):
            self.updater(fetch_policy=offline, fetch_archive=offline).resolve(self.home.name)

    def test_failed_update_keeps_existing_version_if_still_authorized(self):
        old = self.updater().resolve(self.home.name)
        newer = {'version':'0.168.0', 'native_sha256':'c'*64, 'host_sha256':'d'*64}
        self.policy = self.sign({**self.payload, 'revision':2, 'versions':[self.entry,newer]})
        def unavailable(_):
            raise OSError('network error')
        self.assertEqual(old, self.updater(fetch_archive=unavailable).resolve(self.home.name))

    def test_revoked_binary_is_not_used_as_fallback(self):
        self.updater().resolve(self.home.name)
        self.policy = self.sign({**self.payload, 'revision':2, 'versions':[]})
        with self.assertRaises(ValueError):
            self.updater().resolve(self.home.name)

    def test_each_launch_rechecks_policy_and_both_binaries(self):
        resolved = self.updater().resolve(self.home.name)
        self.assertTrue(self.updater().verify_launch(self.home.name, **resolved))
        host = os.path.join(os.path.dirname(resolved['path']), 'codex-code-mode-host')
        with open(host, 'wb') as handle:
            handle.write(b'tampered')
        with self.assertRaises(ValueError):
            self.updater().verify_launch(self.home.name, **resolved)

    def test_each_launch_rejects_revoked_or_expired_policy(self):
        resolved = self.updater().resolve(self.home.name)
        self.policy = self.sign({**self.payload, 'revision':2, 'versions':[]})
        with self.assertRaises(ValueError):
            self.updater().resolve(self.home.name)
        with self.assertRaises(ValueError):
            self.updater().verify_launch(self.home.name, **resolved)

    def test_each_launch_rejects_alternate_path(self):
        resolved = self.updater().resolve(self.home.name)
        with self.assertRaises(ValueError):
            self.updater().verify_launch(self.home.name, resolved['version'], resolved['path'] + '-wrong')
