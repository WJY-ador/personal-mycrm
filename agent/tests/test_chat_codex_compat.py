import base64
import contextlib
import hashlib
import json
import shutil
import subprocess
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agent.chat_codex_compat import verify_policy, accept_policy
from agent.tests.helpers import MemoryKeyStore, FailingKeyStore

class SignedCompatibilityPolicyTest(unittest.TestCase):
    def setUp(self):
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        self.now = 1780000000
        self.payload = {'schema': 2, 'revision': 1, 'issued_at': self.now - 1,
                        'expires_at': self.now + 3600, 'os': 'darwin', 'arch': 'arm64',
                        'min_app': '0.1.2', 'source_sha': 'a' * 40, 'config_sha256': 'b' * 64,
                        'versions': [{'version':'0.166.0', 'native_sha256':'c' * 64, 'host_sha256':'e' * 64},
                                     {'version':'0.167.0', 'native_sha256':'d' * 64, 'host_sha256':'f' * 64}]}

    def envelope(self, payload=None, key=None):
        data = json.dumps(payload or self.payload, separators=(',', ':')).encode()
        signature = (key or self.private).sign(data)
        return json.dumps({'key_id': 'test', 'payload': base64.b64encode(data).decode(),
                           'signature': base64.b64encode(signature).decode()}).encode()

    def verify(self, raw=None, **kw):
        args = {'keys': {'test': self.public}, 'now': self.now, 'os_name': 'darwin',
                'arch': 'arm64', 'app_version': '0.1.2', 'config_sha256': 'b' * 64,
                'floor': {'revision': 0, 'digest': None}}
        args.update(kw)
        return verify_policy(self.envelope() if raw is None else raw, **args)

    def test_valid_signature_accepts_only_signed_versions(self):
        result = self.verify()
        self.assertEqual(result['versions'], self.payload['versions'])
        self.assertEqual(result['checkpoint']['revision'], 1)
        data = base64.b64decode(json.loads(self.envelope())['payload'])
        self.assertEqual(result['checkpoint']['digest'], hashlib.sha256(data).hexdigest())

    def test_rejects_bad_signature_expiry_future_and_other_platform(self):
        for raw, kwargs in [(self.envelope(key=Ed25519PrivateKey.generate()), {}),
                            (self.envelope({**self.payload, 'expires_at': self.now}), {}),
                            (self.envelope({**self.payload, 'issued_at': self.now + 1}), {}),
                            (self.envelope(), {'arch': 'x64'}),
                            (self.envelope({**self.payload, 'versions': ['latest']}), {}),
                            (self.envelope(), {'config_sha256': 'f' * 64}),
                            (self.envelope({**self.payload, 'versions': [{'version': '0.167.0', 'native_sha256': 'x' * 64}]}), {})]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.verify(raw, **kwargs)

    def test_signed_expired_policy_reports_expiry(self):
        with self.assertRaisesRegex(ValueError, '^compatibility-policy-expired$'):
            self.verify(self.envelope({**self.payload, 'expires_at': self.now}))

    def test_rejects_rollback_and_same_revision_with_different_hash(self):
        with self.assertRaises(ValueError):
            self.verify(floor={'revision': 2, 'digest': 'a' * 64})
        with self.assertRaises(ValueError):
            self.verify(floor={'revision': 1, 'digest': 'a' * 64})
        self.assertEqual(self.verify(floor=self.verify()['checkpoint'])['versions'], self.payload['versions'])

    def test_rejects_invalid_type_duplicate_keys_and_oversized_input(self):
        for value in (b'x' * 17000, b'{"key_id":"test","key_id":"test"}', b'[]'):
            with self.subTest(value=value[:20]), self.assertRaises(ValueError):
                self.verify(value)
        with self.assertRaises(ValueError):
            self.verify(self.envelope({**self.payload, 'revision': True}))

    def test_signed_empty_list_revokes_all(self):
        self.assertEqual(self.verify(self.envelope({**self.payload, 'versions': []}))['versions'], [])

    def test_checkpoint_is_persisted_and_prevents_rollback(self):
        store = MemoryKeyStore()
        options = {'keys': {'test': self.public}, 'now': self.now, 'os_name': 'darwin',
                   'arch': 'arm64', 'app_version': '0.1.2', 'config_sha256': 'b' * 64, 'store': store,
                   'lock': contextlib.nullcontext()}
        result = accept_policy(self.envelope(), **options)
        self.assertEqual(result['versions'], self.payload['versions'])
        newer = {**self.payload, 'revision': 2}
        accept_policy(self.envelope(newer), **options)
        with self.assertRaises(ValueError):
            accept_policy(self.envelope(), **options)

    def test_checkpoint_failure_does_not_return_an_execution_grant(self):
        options = {'keys': {'test': self.public}, 'now': self.now, 'os_name': 'darwin',
                   'arch': 'arm64', 'app_version': '0.1.2', 'config_sha256': 'b' * 64, 'store': FailingKeyStore(),
                   'lock': contextlib.nullcontext()}
        with self.assertRaises(Exception):
            accept_policy(self.envelope(), **options)

    def test_checkpoint_must_be_readable_after_write(self):
        class LostWriteStore(MemoryKeyStore):
            def set(self, account, secret):
                pass
        with self.assertRaises(ValueError):
            accept_policy(self.envelope(), keys={'test': self.public}, now=self.now,
                          os_name='darwin', arch='arm64', app_version='0.1.2', config_sha256='b' * 64,
                          store=LostWriteStore(), lock=contextlib.nullcontext())

    def test_invalid_checkpoint_is_never_treated_as_first_use(self):
        store = MemoryKeyStore()
        store.set('codex-compat-checkpoint-darwin-arm64-' + 'b' * 64, 'not_a_valid_checkpoint')
        with self.assertRaises(ValueError):
            accept_policy(self.envelope(), keys={'test': self.public}, now=self.now,
                          os_name='darwin', arch='arm64', app_version='0.1.2', config_sha256='b' * 64, store=store,
                          lock=contextlib.nullcontext())

    def test_checkpoint_is_scoped_by_architecture_and_build(self):
        store = MemoryKeyStore()
        def accept(payload):
            return accept_policy(self.envelope(payload), keys={'test': self.public}, now=self.now,
                os_name='darwin', arch=payload['arch'], app_version='0.1.2',
                config_sha256=payload['config_sha256'], store=store, lock=contextlib.nullcontext())
        accept(self.payload)
        accept({**self.payload, 'arch':'x64'})
        accept({**self.payload, 'config_sha256':'c' * 64})
        with self.assertRaises(ValueError):
            accept({**self.payload, 'versions':[]})

    @unittest.skipUnless(shutil.which('node'), 'node unavailable')
    def test_desktop_issuer_policy_is_accepted_by_agent_verifier(self):
        js = r'''
const crypto = require('node:crypto');
const issuer = require('./desktop/scripts/codex-compat-issuer.cjs');
const {privateKey, publicKey} = crypto.generateKeyPairSync('ed25519');
const payload = JSON.parse(process.argv[1]);
const envelope = issuer.issuePolicy(payload, {privateKey, keyId:'test', now:payload.issued_at + 1});
const spki = publicKey.export({format:'der',type:'spki'});
process.stdout.write(JSON.stringify({envelope, public:spki.subarray(-32).toString('base64')}));
'''
        child = subprocess.run(['node', '-e', js, json.dumps(self.payload)],
                               check=True, text=True, capture_output=True, timeout=5)
        output = json.loads(child.stdout)
        result = self.verify(output['envelope'].encode(),
                             keys={'test': base64.b64decode(output['public'])})
        self.assertEqual(result['versions'], self.payload['versions'])

if __name__ == '__main__':
    unittest.main()
