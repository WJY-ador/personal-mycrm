import hashlib
import io
import os
import tarfile
import tempfile
import unittest

from agent.chat_codex_managed import install_native


def archive(data, host=b'synthetic host', path='package/vendor/aarch64-apple-darwin/bin/codex', kind=tarfile.REGTYPE):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as tar:
        entry = tarfile.TarInfo(path)
        entry.type = kind
        entry.size = len(data) if kind == tarfile.REGTYPE else 0
        tar.addfile(entry, io.BytesIO(data) if entry.size else None)
        host_entry = tarfile.TarInfo('package/vendor/aarch64-apple-darwin/bin/codex-code-mode-host')
        host_entry.size = len(host)
        tar.addfile(host_entry, io.BytesIO(host))
    return buffer.getvalue()


class ManagedNativeInstallTest(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.TemporaryDirectory(prefix='mycrm-managed-test-')
        os.chmod(self.root.name, 0o700)
        self.data = b'synthetic native binary'
        self.host = b'synthetic host'
        self.digest = hashlib.sha256(self.data).hexdigest()
        self.host_digest = hashlib.sha256(self.host).hexdigest()

    def tearDown(self):
        self.root.cleanup()

    def test_installs_exact_verified_native_and_reuses_it(self):
        path = install_native(self.root.name, 'arm64', self.digest, self.host_digest, io.BytesIO(archive(self.data)))
        with open(path, 'rb') as handle:
            self.assertEqual(handle.read(), self.data)
        self.assertEqual(os.stat(path).st_mode & 0o777, 0o700)
        self.assertEqual(path, install_native(self.root.name, 'arm64', self.digest, self.host_digest, archive(self.data)))
        with open(os.path.join(os.path.dirname(path), 'codex-code-mode-host'), 'rb') as handle:
            self.assertEqual(handle.read(), self.host)

    def test_rejects_wrong_hash_wrong_arch_and_tar_link(self):
        for arch, digest, contents in [('arm64', '0' * 64, archive(self.data)),
                                       ('x64', self.digest, archive(self.data)),
                                       ('arm64', self.digest, archive(self.data, kind=tarfile.SYMTYPE))]:
            with self.subTest(arch=arch), self.assertRaises(ValueError):
                install_native(self.root.name, arch, digest, self.host_digest, contents)

    def test_rejects_symlinked_management_directory(self):
        with tempfile.TemporaryDirectory() as outside:
            os.symlink(outside, os.path.join(self.root.name, 'managed-codex'))
            with self.assertRaises(ValueError):
                install_native(self.root.name, 'arm64', self.digest, self.host_digest, archive(self.data))

    def test_rejects_wrong_host_hash_without_installing_cli(self):
        with self.assertRaises(ValueError):
            install_native(self.root.name, 'arm64', self.digest, '0' * 64, archive(self.data))

    def test_failed_update_preserves_previously_installed_version(self):
        old = install_native(self.root.name, 'arm64', self.digest, self.host_digest, archive(self.data))
        with self.assertRaises(ValueError):
            install_native(self.root.name, 'arm64', '0' * 64, self.host_digest, archive(self.data))
        self.assertEqual(old, install_native(self.root.name, 'arm64', self.digest, self.host_digest, None))

    def test_existing_component_tampering_is_not_reused(self):
        path = install_native(self.root.name, 'arm64', self.digest, self.host_digest, archive(self.data))
        with open(os.path.join(os.path.dirname(path), 'codex-code-mode-host'), 'wb') as handle:
            handle.write(b'changed')
        with self.assertRaises(ValueError):
            install_native(self.root.name, 'arm64', self.digest, self.host_digest, None)

    def test_interrupted_staging_files_are_never_used_as_installed_cli(self):
        managed = os.path.join(self.root.name, 'managed-codex')
        version = os.path.join(managed, 'v-' + self.digest + '-' + self.host_digest)
        os.mkdir(managed, 0o700)
        os.mkdir(version, 0o700)
        with open(os.path.join(version, '.install-synthetic'), 'wb') as handle:
            handle.write(self.data)
        with self.assertRaises(ValueError):
            install_native(self.root.name, 'arm64', self.digest, self.host_digest, None)
