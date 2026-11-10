"""Resolve a signed compatibility policy to an app-managed native CLI.

Policy acceptance is separate from user consent and server launch grants. The
production resolver remains unavailable without a pinned operating public key.
"""
from __future__ import annotations

import contextlib
import os
import platform
import re
import secrets
import stat
import urllib.error
import urllib.parse
import urllib.request

from .chat_codex_auth import _open_private_dir, codex_auth_lock, prepare_codex_home
from .chat_codex_compat import accept_policy, verify_policy
from .chat_codex_managed import install_native
from .chat_codex_trust import TRUSTED_COMPAT_KEYS

_POLICY_LIMIT = 16384
_POLICY_URL = 'https://github.com/WJY-ador/personal-mycrm/releases/download/codex-compat-policy/darwin-{arch}-{config}.json'
_ARCHIVE_URL = 'https://registry.npmjs.org/@openai/codex/-/codex-{version}-darwin-{arch}.tgz'


class _Redirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = frozenset(hosts)

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != 'https' or parsed.hostname not in self.hosts or parsed.username or parsed.password:
            raise ValueError('unsafe-download-redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _open_https(url, hosts):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise ValueError('unsafe-download-url')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Redirects(hosts))
    return opener.open(urllib.request.Request(url, headers={'User-Agent':'MyCRM-Codex-compat/1'}), timeout=30)


def _fetch_policy(arch, config_sha256):
    if arch not in ('arm64', 'x64') or not isinstance(config_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', config_sha256):
        raise ValueError('unsupported-platform')
    with _open_https(_POLICY_URL.format(arch=arch, config=config_sha256),
                     {'github.com','objects.githubusercontent.com','release-assets.githubusercontent.com'}) as response:
        raw = response.read(_POLICY_LIMIT + 1)
    if not raw or len(raw) > _POLICY_LIMIT:
        raise ValueError('invalid-policy-download')
    return raw


def _fetch_archive(version, arch):
    if (arch not in ('arm64', 'x64') or not isinstance(version, str)
            or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', version)):
        raise ValueError('invalid-managed-version')
    return _open_https(_ARCHIVE_URL.format(version=version, arch=arch), {'registry.npmjs.org'})


def _cache_name(arch, config_sha256):
    if arch not in ('arm64', 'x64') or not isinstance(config_sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', config_sha256):
        raise ValueError('invalid-policy-cache')
    return f'codex-compat-policy-{arch}-{config_sha256}.json'


def _read_cache(directory, arch, config_sha256, *, pending=False):
    fd = _open_private_dir(directory)
    try:
        try:
            name = _cache_name(arch, config_sha256) + ('.pending' if pending else '')
            file = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=fd)
        except FileNotFoundError:
            return None
        try:
            info = os.fstat(file)
            if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                    or not hasattr(os, 'getuid') or info.st_uid != os.getuid()
                    or info.st_nlink != 1 or info.st_size > _POLICY_LIMIT):
                raise ValueError('unsafe-policy-cache')
            raw = os.read(file, _POLICY_LIMIT + 1)
            if len(raw) != info.st_size:
                raise ValueError('invalid-policy-cache')
            return raw
        finally:
            os.close(file)
    finally:
        os.close(fd)


def _save_cache(directory, raw, arch, config_sha256, *, pending=False):
    if not isinstance(raw, bytes) or not raw or len(raw) > _POLICY_LIMIT:
        raise ValueError('invalid-policy-cache')
    fd = _open_private_dir(directory)
    temporary = '.compat-' + secrets.token_hex(16)
    try:
        file = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(file, view)
                if written <= 0:
                    raise ValueError('policy-cache-write-failed')
                view = view[written:]
            os.fsync(file)
        finally:
            os.close(file)
        name = _cache_name(arch, config_sha256) + ('.pending' if pending else '')
        os.replace(temporary, name, src_dir_fd=fd, dst_dir_fd=fd)
        os.fsync(fd)
    finally:
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)


class _Updater:
    def __init__(self, *, keys, store, lock, now, config_sha256, app_version,
                 os_name, arch, fetch_policy, fetch_archive):
        self.keys, self.store, self.lock, self.now = keys, store, lock, now
        self.config_sha256, self.app_version = config_sha256, app_version
        self.os_name, self.arch = os_name, arch
        self.fetch_policy, self.fetch_archive = fetch_policy, fetch_archive

    def resolve(self, agent_home):
        with self.lock:
            fetched = True
            try:
                raw = self.fetch_policy(self.arch)
            except (OSError, TimeoutError, urllib.error.URLError):
                fetched = False
                raw = _read_cache(agent_home, self.arch, self.config_sha256, pending=True)
                if raw is None:
                    raw = _read_cache(agent_home, self.arch, self.config_sha256)
                if raw is None:
                    raise ValueError('compatibility-policy-unavailable') from None
            if fetched:
                # Persist an authenticated recovery copy before advancing the
                # KeyStore checkpoint. Both are checked again before use.
                verify_policy(raw, keys=self.keys, now=self.now(), os_name=self.os_name,
                    arch=self.arch, app_version=self.app_version, config_sha256=self.config_sha256,
                    floor={'revision':0, 'digest':None})
                _save_cache(agent_home, raw, self.arch, self.config_sha256, pending=True)
            try:
                policy = accept_policy(raw, keys=self.keys, now=self.now(), os_name=self.os_name,
                    arch=self.arch, app_version=self.app_version, config_sha256=self.config_sha256,
                    store=self.store, lock=contextlib.nullcontext())
            except ValueError:
                if fetched:
                    raise
                # A stale recovery copy must not hide the last committed policy.
                # The committed copy must independently pass the current floor.
                committed = _read_cache(agent_home, self.arch, self.config_sha256)
                if committed is None or committed == raw:
                    raise
                raw = committed
                policy = accept_policy(raw, keys=self.keys, now=self.now(), os_name=self.os_name,
                    arch=self.arch, app_version=self.app_version, config_sha256=self.config_sha256,
                    store=self.store, lock=contextlib.nullcontext())
            _save_cache(agent_home, raw, self.arch, self.config_sha256)
            entries = sorted(policy['versions'], key=lambda e: tuple(map(int, e['version'].split('.'))), reverse=True)
            for entry in entries:
                try:
                    path = install_native(agent_home, self.arch, entry['native_sha256'], entry['host_sha256'], None)
                    return {'version':entry['version'], 'path':path}
                except ValueError:
                    pass
                try:
                    with self.fetch_archive(entry['version']) as archive:
                        path = install_native(agent_home, self.arch, entry['native_sha256'], entry['host_sha256'], archive)
                    return {'version':entry['version'], 'path':path}
                except (ValueError, OSError, TimeoutError, urllib.error.URLError):
                    continue
            raise ValueError('verified-codex-unavailable')

    def inspect(self, agent_home):
        """Inspect only locally cached policy and installed binaries, never download."""
        with self.lock:
            candidates = [_read_cache(agent_home, self.arch, self.config_sha256, pending=True),
                          _read_cache(agent_home, self.arch, self.config_sha256)]
            if not any(candidates):
                raise ValueError('managed-cli-setup-required')
            error = None
            for raw in candidates:
                if raw is None:
                    continue
                try:
                    policy = accept_policy(raw, keys=self.keys, now=self.now(), os_name=self.os_name,
                        arch=self.arch, app_version=self.app_version, config_sha256=self.config_sha256,
                        store=self.store, lock=contextlib.nullcontext())
                except ValueError as exc:
                    error = exc
                    continue
                entries = sorted(policy['versions'], key=lambda e: tuple(map(int, e['version'].split('.'))), reverse=True)
                for entry in entries:
                    try:
                        path = install_native(agent_home, self.arch, entry['native_sha256'], entry['host_sha256'], None)
                        return {'version':entry['version'], 'path':path}
                    except ValueError:
                        continue
                raise ValueError('managed-cli-setup-required')
            raise error or ValueError('managed-cli-setup-required')

    def verify_launch(self, agent_home, version, path):
        """Recheck cached authorization and both installed files before launch."""
        if not isinstance(version, str) or not isinstance(path, str) or not os.path.isabs(path):
            raise ValueError('managed-cli-launch-binding')
        with self.lock:
            raw = _read_cache(agent_home, self.arch, self.config_sha256)
            if raw is None:
                raise ValueError('compatibility-policy-unavailable')
            policy = accept_policy(raw, keys=self.keys, now=self.now(), os_name=self.os_name,
                arch=self.arch, app_version=self.app_version, config_sha256=self.config_sha256,
                store=self.store, lock=contextlib.nullcontext())
            entries = [entry for entry in policy['versions'] if entry['version'] == version]
            if len(entries) != 1:
                raise ValueError('managed-cli-version-revoked')
            entry = entries[0]
            expected = install_native(agent_home, self.arch, entry['native_sha256'], entry['host_sha256'], None)
            if os.path.abspath(path) != expected or os.path.islink(path):
                raise ValueError('managed-cli-launch-binding')
            return True


def _production_updater(store, lock):
    if not TRUSTED_COMPAT_KEYS or platform.system() != 'Darwin':
        raise ValueError('managed-codex-not-ready')
    try:
        from _desktop_build import APP_VERSION, CODEX_CONFIG_SHA256
    except ImportError:
        raise ValueError('managed-codex-build-identity-unavailable') from None
    arch = {'arm64':'arm64', 'x86_64':'x64'}.get(platform.machine())
    if arch is None:
        raise ValueError('unsupported-platform')
    import time
    return _Updater(keys=TRUSTED_COMPAT_KEYS, store=store, lock=lock,
        now=lambda: int(time.time()), config_sha256=CODEX_CONFIG_SHA256, app_version=APP_VERSION,
        os_name='darwin', arch=arch, fetch_policy=lambda selected_arch: _fetch_policy(selected_arch, CODEX_CONFIG_SHA256),
        fetch_archive=lambda version: _fetch_archive(version, arch))


def resolve_managed_cli(agent_home, store):
    """Production entry point. Uses only build identity and pinned keys."""
    auth_home = prepare_codex_home(agent_home)
    return _production_updater(store, codex_auth_lock(auth_home)).resolve(agent_home)


def inspect_managed_cli(agent_home, store):
    """Check the cached managed CLI without attempting a network download."""
    # Pinned keys, platform and build identity decide readiness before storage.
    _production_updater(store, contextlib.nullcontext())
    # A fresh install has no agent home yet. This read-only diagnostic never
    # creates it; an existing home still gets the full private-storage check.
    if not os.path.lexists(agent_home):
        raise ValueError('managed-cli-setup-required')
    auth_home = prepare_codex_home(agent_home)
    return _production_updater(store, codex_auth_lock(auth_home)).inspect(agent_home)


def verify_managed_cli_locked(agent_home, store, version, path):
    """Recheck under the caller's already-held codex_auth_lock before launch."""
    return _production_updater(store, contextlib.nullcontext()).verify_launch(agent_home, version, path)
