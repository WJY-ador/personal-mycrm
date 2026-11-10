"""Content-addressed installation of a separately verified native Codex CLI.

This primitive is not an authorization decision. The caller must first verify
a current signed policy, its build fingerprint and platform, then supply the
native digest from the matching policy entry. No user CLI or credential is read.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
import secrets
import stat
import tarfile

from .chat_codex_auth import _open_private_dir, _check_stat

_MAX_ARCHIVE = 256 * 1024 * 1024
_MAX_BINARY = 512 * 1024 * 1024
_TRIPLES = {'arm64': 'aarch64-apple-darwin', 'x64': 'x86_64-apple-darwin'}


class _BoundedReader:
    def __init__(self, source):
        self.source = source
        self.total = 0

    def read(self, size=-1):
        remaining = _MAX_ARCHIVE - self.total
        amount = min(size, remaining + 1) if size >= 0 else remaining + 1
        data = self.source.read(amount)
        if not isinstance(data, bytes) or len(data) > remaining:
            raise ValueError('managed-cli-archive-too-large')
        self.total += len(data)
        return data


def _verified_existing(directory, name, expected):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
    except FileNotFoundError:
        return False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700
                or not hasattr(os, 'getuid') or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > _MAX_BINARY):
            raise ValueError('unsafe-managed-cli')
        digest = hashlib.sha256()
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
        if digest.hexdigest() != expected:
            raise ValueError('managed-cli-digest-mismatch')
        return True
    finally:
        os.close(fd)


def install_native(agent_home, arch, native_sha256, host_sha256, archive):
    """Install both verified native components without replacing an old version."""
    if (arch not in _TRIPLES or not all(isinstance(item, str) and re.fullmatch(r'[0-9a-f]{64}', item)
                                       for item in (native_sha256, host_sha256))
            or not (archive is None or isinstance(archive, bytes) or callable(getattr(archive, 'read', None)))
            or isinstance(archive, bytes) and (not archive or len(archive) > _MAX_ARCHIVE)
            or not hasattr(os, 'O_NOFOLLOW')):
        raise ValueError('invalid-managed-cli-input')
    parent, managed, directory = _open_private_dir(agent_home), None, None
    folder = 'v-' + native_sha256 + '-' + host_sha256
    targets = {'codex': native_sha256, 'codex-code-mode-host': host_sha256}
    staged = {}
    try:
        try:
            os.mkdir('managed-codex', mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        try:
            managed = os.open('managed-codex', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            _check_stat(os.fstat(managed), directory=True)
            try:
                os.mkdir(folder, mode=0o700, dir_fd=managed)
            except FileExistsError:
                pass
            directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=managed)
            _check_stat(os.fstat(directory), directory=True)
        except OSError:
            raise ValueError('unsafe-managed-cli-directory') from None
        present = {name: _verified_existing(directory, name, digest) for name, digest in targets.items()}
        result = os.path.join(agent_home, 'managed-codex', folder, 'codex')
        if all(present.values()):
            return result
        if archive is None:
            raise ValueError('managed-cli-not-installed')
        prefix = 'package/vendor/' + _TRIPLES[arch] + '/bin/'
        found = set()
        try:
            source_archive = io.BytesIO(archive) if isinstance(archive, bytes) else archive
            with tarfile.open(fileobj=_BoundedReader(source_archive), mode='r|gz') as tar:
                for index, member in enumerate(tar):
                    if index >= 1024 or member.size < 0 or member.size > _MAX_BINARY:
                        raise ValueError('invalid-managed-cli-archive')
                    name = member.name[len(prefix):] if member.name.startswith(prefix) else ''
                    if name not in targets:
                        continue
                    if name in found or not member.isfile() or member.size <= 0:
                        raise ValueError('invalid-managed-cli-member')
                    found.add(name)
                    if present[name]:
                        continue
                    source = tar.extractfile(member)
                    if source is None:
                        raise ValueError('invalid-managed-cli-member')
                    temp_name = '.install-' + secrets.token_hex(16)
                    fd = os.open(temp_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o700, dir_fd=directory)
                    staged[name] = temp_name
                    try:
                        digest = hashlib.sha256()
                        remaining = member.size
                        while remaining:
                            chunk = source.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise ValueError('truncated-managed-cli')
                            digest.update(chunk)
                            view = memoryview(chunk)
                            while view:
                                written = os.write(fd, view)
                                if written <= 0:
                                    raise ValueError('managed-cli-write-failed')
                                view = view[written:]
                            remaining -= len(chunk)
                        if digest.hexdigest() != targets[name]:
                            raise ValueError('managed-cli-digest-mismatch')
                        os.fsync(fd)
                    finally:
                        os.close(fd)
            if found != set(targets):
                raise ValueError('missing-managed-cli')
            for name, temp_name in list(staged.items()):
                try:
                    os.link(temp_name, name, src_dir_fd=directory, dst_dir_fd=directory,
                            follow_symlinks=False)
                except FileExistsError:
                    if not _verified_existing(directory, name, targets[name]):
                        raise ValueError('managed-cli-race') from None
                os.unlink(temp_name, dir_fd=directory)
                del staged[name]
            os.fsync(directory)
            if not all(_verified_existing(directory, name, digest) for name, digest in targets.items()):
                raise ValueError('managed-cli-unavailable')
            return result
        except (tarfile.TarError, EOFError, OSError):
            raise ValueError('invalid-managed-cli-archive') from None
        finally:
            for temp_name in staged.values():
                try:
                    os.unlink(temp_name, dir_fd=directory)
                except FileNotFoundError:
                    pass
    finally:
        if directory is not None:
            os.close(directory)
        if managed is not None:
            os.close(managed)
        os.close(parent)
