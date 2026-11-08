"""App-owned Codex authentication directory; no credential contents are read.

The caller must hold ``codex_auth_lock`` for the entire app-server lifetime,
including login and token refresh. A busy or unsupported lock fails closed.
This module does not initiate network requests or perform a browser login.
"""
from __future__ import annotations

import contextlib
import os
import stat

try:
    import fcntl
except ImportError:  # Windows is not supported by the app-server integration.
    fcntl = None


class CodexAuthError(RuntimeError):
    pass


# Pass as separate argv entries, not through a shell.
CODEX_AUTH_CONFIG_ARGS = ('-c', 'cli_auth_credentials_store="file"')


def _check_stat(info, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    expected = 0o700 if directory else 0o600
    if (not kind(info.st_mode) or stat.S_IMODE(info.st_mode) != expected
            or not hasattr(os, 'getuid') or info.st_uid != os.getuid()
            or (not directory and info.st_nlink != 1)):
        raise CodexAuthError('unsafe authentication storage permissions')


def _open_private_dir(path):
    if not isinstance(path, str) or not os.path.isabs(path) or not hasattr(os, 'O_NOFOLLOW'):
        raise CodexAuthError('unsupported authentication storage path')
    try:
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _check_stat(os.fstat(fd), directory=True)
        except Exception:
            os.close(fd)
            raise
        return fd
    except OSError as exc:
        raise CodexAuthError('cannot access authentication directory') from exc


def prepare_codex_home(agent_home):
    """Create and verify the isolated home beneath an already-private agent home."""
    parent = _open_private_dir(agent_home)
    try:
        try:
            os.mkdir('codex-auth', mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        except OSError as exc:
            raise CodexAuthError('cannot create authentication directory') from exc
        try:
            fd = os.open('codex-auth', os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                         dir_fd=parent)
        except OSError as exc:
            raise CodexAuthError('cannot access authentication directory') from exc
        try:
            _check_stat(os.fstat(fd), directory=True)
        finally:
            os.close(fd)
    finally:
        os.close(parent)
    return os.path.join(agent_home, 'codex-auth')


def validate_credentials(codex_home):
    """Return whether a private auth file exists, without opening or reading it.

    A present file does not prove that authentication is still valid; callers
    must query app-server account status and handle login or expiration.
    """
    home = _open_private_dir(codex_home)
    try:
        try:
            info = os.stat('auth.json', dir_fd=home, follow_symlinks=False)
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise CodexAuthError('cannot inspect authentication file') from exc
        _check_stat(info)
        return True
    finally:
        os.close(home)


@contextlib.contextmanager
def codex_auth_lock(codex_home):
    """Serialize app-server instances sharing a home, including refresh/login."""
    if fcntl is None or not hasattr(os, 'O_NOFOLLOW'):
        raise CodexAuthError('authentication locking is unsupported')
    home = _open_private_dir(codex_home)
    lock = None
    try:
        try:
            lock = os.open('.mycrm-auth.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                           0o600, dir_fd=home)
            _check_stat(os.fstat(lock))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise CodexAuthError('authentication is already in use or unavailable') from exc
        yield
    finally:
        if lock is not None:
            os.close(lock)
        os.close(home)


def _request_id(request_id):
    if isinstance(request_id, bool) or not isinstance(request_id, (int, str)) or request_id == '':
        raise CodexAuthError('invalid RPC request id')
    return request_id


def login_start_request(request_id):
    return {'id': _request_id(request_id), 'method': 'account/login/start',
            'params': {'type': 'chatgpt'}}


def login_cancel_request(request_id, login_id):
    if not isinstance(login_id, str) or not login_id or len(login_id) > 256 or '\x00' in login_id:
        raise CodexAuthError('invalid login id')
    return {'id': _request_id(request_id), 'method': 'account/login/cancel',
            'params': {'loginId': login_id}}


def login_completed(codex_home, login_id, event):
    """Accept only a completion for the explicit attempt and private storage.

    The caller must also verify account status with app-server. A present file
    does not establish the identity of its owner or guarantee token freshness.
    """
    if not isinstance(login_id, str) or not login_id or len(login_id) > 256:
        raise CodexAuthError('invalid login id')
    if not isinstance(event, dict) or event.get('method') != 'account/login/completed':
        raise CodexAuthError('unexpected login notification')
    params = event.get('params')
    if (not isinstance(params, dict) or params.get('loginId') != login_id
            or not isinstance(params.get('success'), bool)):
        raise CodexAuthError('mismatched login notification')
    if not params['success']:
        return False
    if not validate_credentials(codex_home):
        raise CodexAuthError('login did not create private credentials')
    return True
