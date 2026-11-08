"""Disabled app-owned Codex login flow. The login URL is never reported."""
import os
import subprocess
import tempfile
import time
import webbrowser
from urllib.parse import urlsplit

from .chat_codex_auth import (codex_auth_lock, login_start_request, login_cancel_request,
                              login_completed, prepare_codex_home, safe_cli_path)

APP_SERVER_LOGIN_READY = False


def _valid_auth_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(c in value for c in '\r\n\x00'):
        return False
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == 'https' and parsed.hostname == 'auth.openai.com'
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except ValueError:
        return False


def run_login_dialog(transport, home, open_browser, cancelled, report, *, timeout=600):
    """Run one browser login. Only fixed status words reach report()."""
    if not all(callable(fn) for fn in (open_browser, cancelled, report)) or timeout <= 0:
        raise ValueError('login-configuration')
    deadline = time.monotonic() + timeout
    buffered = []

    def receive():
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('login-timeout')
            try:
                message = transport.receive(min(remaining, 1.0))
            except TimeoutError:
                if cancelled():
                    return None
                continue
            if not isinstance(message, dict):
                raise ValueError('login-protocol')
            return message

    def request(message):
        transport.send(message)
        while True:
            reply = receive()
            if reply is None:
                raise ValueError('login-cancelled')
            if reply.get('id') == message['id'] and 'method' not in reply:
                if 'error' in reply or not isinstance(reply.get('result'), dict):
                    raise ValueError('login-request-failed')
                return reply['result']
            if 'id' in reply and 'method' in reply or len(buffered) >= 100:
                raise ValueError('unexpected-server-request')
            buffered.append(reply)

    request({'id':1, 'method':'initialize', 'params':{'clientInfo':{'name':'mycrm', 'version':'1'},
                                                        'capabilities':{'experimentalApi':True}}})
    transport.send({'method':'initialized', 'params':{}})
    start = request(login_start_request(2))
    login_id, url = start.get('loginId'), start.get('authUrl')
    if start.get('type') != 'chatgpt' or not isinstance(login_id, str) or not login_id or not _valid_auth_url(url):
        raise ValueError('login-response')
    if open_browser(url) is not True:
        raise ValueError('browser-unavailable')
    report('waiting')
    while True:
        if cancelled():
            # Cancellation response is authoritative. A completed/unknown login
            # must not be reported as cancelled.
            if request(login_cancel_request(3, login_id)).get('status') != 'canceled':
                raise ValueError('login-cancel-failed')
            report('cancelled')
            return 'cancelled'
        event = buffered.pop(0) if buffered else receive()
        if event is None:
            continue
        if event.get('method') != 'account/login/completed':
            if 'id' in event and 'method' in event:
                raise ValueError('unexpected-server-request')
            continue
        if not login_completed(home, login_id, event):
            raise ValueError('login-failed')
        account = request({'id':4, 'method':'account/read', 'params':{'refreshToken':False}}).get('account')
        if not isinstance(account, dict) or account.get('type') != 'chatgpt':
            raise ValueError('login-account-unverified')
        report('completed')
        return 'completed'


def run_login_session(agent_home, cli_path, *, cancelled, report, open_browser=None, supervisor=None, timeout=600):
    """Run one isolated CLI login under an exclusive app-owned auth lock."""
    if APP_SERVER_LOGIN_READY is not True:
        report('unavailable')
        return 'unavailable'
    if (not isinstance(cli_path, str) or not os.path.isabs(cli_path) or os.path.islink(cli_path)
            or not os.path.isfile(cli_path) or not os.access(cli_path, os.X_OK)):
        report('error')
        return 'error'
    from .chat_codex import _DISABLED_FEATURES
    from .chat_codex_app_provider import _EXTRA_DISABLED
    from .chat_codex_dynamic import JsonRpcTransport
    from .chat_process_supervisor import MacOSProcessSupervisor
    supervisor = supervisor or MacOSProcessSupervisor()
    open_browser = open_browser or webbrowser.open
    terminal = []
    proc = None
    try:
        home = prepare_codex_home(agent_home)
        if os.path.lexists(os.path.join(home, 'config.toml')):
            raise ValueError('unexpected-user-config')
        argv = [cli_path, 'app-server', '--listen', 'stdio://',
                '-c', 'cli_auth_credentials_store="file"', '-c', 'web_search="disabled"',
                '-c', 'mcp_servers={}']
        for name in dict.fromkeys(_DISABLED_FEATURES + _EXTRA_DISABLED):
            argv.extend(('-c', 'features.' + name + '=false'))
        env = {'HOME':agent_home, 'CODEX_HOME':home,
               'PATH':safe_cli_path(cli_path, os.environ.get('PATH', ''))}
        with codex_auth_lock(home), tempfile.TemporaryDirectory(prefix='codex-login-', dir=agent_home) as cwd:
            os.chmod(cwd, 0o700)
            proc = supervisor.spawn(argv, cwd=cwd, env=env, stdin=subprocess.PIPE,
                                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                transport = JsonRpcTransport(proc.stdout, proc.stdin)
                def status(value):
                    if value == 'waiting':
                        report(value)
                    else:
                        terminal.append(value)
                run_login_dialog(transport, home, open_browser, cancelled, status, timeout=timeout)
            finally:
                try:
                    supervisor.terminate_tree(proc)
                finally:
                    for stream in (proc.stdin, proc.stdout):
                        if stream:
                            try:
                                stream.close()
                            except BrokenPipeError:
                                pass
                proc = None
        if len(terminal) != 1 or terminal[0] not in ('completed', 'cancelled'):
            raise ValueError('login-incomplete')
        report(terminal[0])
        return terminal[0]
    except Exception:
        report('error')
        return 'error'
