"""Disabled Codex app-server provider and server-authorized factory.

The feature remains off until tool isolation, login and real CLI E2E have been
verified. Do not enable this provider solely on the unit tests.
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import threading

from .chat_approval_context import format_approval_outcomes
from .chat_codex import CodexProvider, CodexProviderFactory, _DISABLED_FEATURES, _FORBIDDEN_ENV
from .chat_codex_auth import codex_auth_lock, prepare_codex_home, safe_cli_path, validate_credentials
from .chat_codex_dynamic import AppServerProcess, DynamicToolRelay
from .chat_codex_update import resolve_managed_cli, verify_managed_cli_locked
from .keystore import KeyStore
from .chat_launch_authority import AUTH_PATH
from .chat_mcp_bridge import McpStdioBridge

APP_SERVER_CANDIDATE_READY = False
_EXTRA_DISABLED = ('plugins', 'hooks', 'multi_agent', 'unified_exec', 'view_image',
                   'image_generation', 'skill_search', 'skill_mcp_dependency_install',
                   'tool_suggest', 'sleep_tool', 'goals')
# Add a version only after running the isolation and dynamic-tool probes on it.
SUPPORTED_CLI_VERSIONS = ('0.166.0', '0.167.0')
_VERSION_RE = re.compile(r'codex-cli (0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})\.(0|[1-9]\d{0,5})(-[0-9A-Za-z.-]{1,40})?\Z')


def _capture_version_output(cli_path, *, cwd, env):
    """Bound output and runtime even if the selected executable misbehaves."""
    proc = subprocess.Popen([cli_path, '--version'], cwd=cwd, env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=(os.name == 'posix'))
    output = []
    completed = False
    def read_bounded():
        try:
            output.append(proc.stdout.read(257))
        except (OSError, ValueError):
            pass
    reader = threading.Thread(target=read_bounded, daemon=True)
    reader.start()
    try:
        reader.join(5)
        if reader.is_alive() or not output or len(output[0]) > 256:
            return None
        try:
            returncode = proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            return None
        completed = True
        return output[0].decode('utf-8', 'strict') if returncode == 0 else None
    finally:
        if not completed and os.name == 'posix':
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        reader.join(1)
        # A detached descendant may retain the pipe. Closing a buffered stream
        # while another thread is reading it can block beyond the deadline.
        if not reader.is_alive():
            proc.stdout.close()


def inspect_cli_version(cli_path, *, cwd, env):
    """Return only a sanitized diagnostic; untested versions remain disabled."""
    result = {'status': 'unavailable', 'installed_version': None,
              'supported_versions': list(SUPPORTED_CLI_VERSIONS),
              'recommended_action': 'check_installation'}
    if not isinstance(cli_path, str) or not os.path.isabs(cli_path):
        return result
    try:
        output = _capture_version_output(cli_path, cwd=cwd, env=env)
        match = _VERSION_RE.fullmatch(output.strip()) if output is not None else None
        if match is None:
            return result
        version = '.'.join(match.group(i) for i in (1, 2, 3)) + (match.group(4) or '')
        result['installed_version'] = version
        if version in SUPPORTED_CLI_VERSIONS:
            result.update(status='supported', recommended_action='none')
        elif tuple(int(match.group(i)) for i in (1, 2, 3)) < tuple(map(int, SUPPORTED_CLI_VERSIONS[0].split('.'))):
            result.update(status='too_old', recommended_action='update_codex')
        elif match.group(4):
            result.update(status='unverified_version', recommended_action='update_mycrm')
        else:
            result.update(status='unverified_newer', recommended_action='update_mycrm')
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        pass
    return result


def _cli_version_supported(cli_path, *, cwd, env):
    return inspect_cli_version(cli_path, cwd=cwd, env=env)['status'] == 'supported'


def _build_appserver_argv(cli_path):
    argv = [cli_path, 'app-server', '--listen', 'stdio://', '--strict-config',
            '-c', 'cli_auth_credentials_store="file"', '-c', 'web_search="disabled"',
            '-c', 'mcp_servers={}', '-c', 'agents.enabled=false',
            '-c', 'tools.experimental_request_user_input.enabled=false',
            '-c', 'features.code_mode_host=true']
    for name in dict.fromkeys(_DISABLED_FEATURES + _EXTRA_DISABLED):
        argv.extend(('-c', 'features.' + name + '=false'))
    return argv


class AppServerCandidateFactory:
    """Mint each turn with the existing server authorization and isolated auth home."""

    name = 'codex'

    def __init__(self, authorization_client, *, cli_path, server_url, agent_home,
                 expected_device_id, models, env=None, process_supervisor=None, timeout=300,
                 managed_store=None):
        if APP_SERVER_CANDIDATE_READY is not True:
            raise ValueError('not-ready')
        auth_home = prepare_codex_home(agent_home)
        self.agent_home = os.path.realpath(agent_home)
        if managed_store is not None and not isinstance(managed_store, KeyStore):
            raise ValueError('managed-cli-binding')
        self._managed_store = managed_store
        self._managed_version = None
        self._factory_lock = threading.RLock()
        self._factory_args = {'server_url':server_url, 'agent_home':self.agent_home,
            'codex_home':auth_home, 'expected_device_id':expected_device_id,
            'models':models, 'env':env, 'process_supervisor':process_supervisor, 'timeout':timeout}
        self._authorization_client = authorization_client
        if managed_store is not None:
            resolved = resolve_managed_cli(self.agent_home, managed_store)
            cli_path, self._managed_version = resolved['path'], resolved['version']
        self._base = CodexProviderFactory(authorization_client, cli_path=cli_path, **self._factory_args)
        self.models = self._base.models

    def create_turn(self, session_id, turn_id, authorization_path, provider, model):
        if APP_SERVER_CANDIDATE_READY is not True:
            raise ValueError('not-ready')
        with self._factory_lock:
            if self._managed_store is not None:
                resolved = resolve_managed_cli(self.agent_home, self._managed_store)
                if resolved['path'] != self._base.cli_path or resolved['version'] != self._managed_version:
                    self._base = CodexProviderFactory(self._authorization_client, cli_path=resolved['path'],
                                                      **self._factory_args)
                    self._managed_version = resolved['version']
            base = self._base.create_turn(session_id, turn_id, authorization_path, provider, model)
            try:
                return AppServerCandidateProvider(base, agent_home=self.agent_home,
                    managed_store=self._managed_store, managed_version=self._managed_version)
            except Exception:
                base.close()
                raise


class AppServerCandidateProvider:
    name = 'codex'

    def __init__(self, base, *, agent_home, managed_store=None, managed_version=None):
        if APP_SERVER_CANDIDATE_READY is not True:
            raise ValueError('not-ready')
        if type(base) is not CodexProvider or not base.is_available():
            raise ValueError('launch-denied')
        if not isinstance(agent_home, str) or not os.path.isabs(agent_home):
            raise ValueError('agent-home')
        auth_home = prepare_codex_home(agent_home)
        if base.launch_context.codex_home != auth_home:
            raise ValueError('auth-home-binding')
        if (managed_store is None) != (managed_version is None):
            raise ValueError('managed-cli-binding')
        if managed_store is not None and (not isinstance(managed_store, KeyStore)
                or not isinstance(managed_version, str)
                or not re.fullmatch(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)', managed_version)):
            raise ValueError('managed-cli-binding')
        if os.path.lexists(os.path.join(auth_home, 'config.toml')):
            raise ValueError('unexpected-user-config')
        self.base = base
        self.agent_home = os.path.realpath(agent_home)
        self._managed_store = managed_store
        self._managed_version = managed_version
        self.auth_home = auth_home
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._stopping = threading.Event()
        self._runner = None

    def is_available(self):
        if self._stopping.is_set() or APP_SERVER_CANDIDATE_READY is not True:
            return False
        try:
            return self.base.is_available() and self.base.launch_verifier.verify_codex_grant(self.base.launch_context) is True
        except Exception:
            return False

    def start_turn(self, text, cli_session_ref=None, *, approval_outcomes=()):
        if not self._lock.acquire(blocking=False):
            yield 'error', {'code': 'CODEX-BUSY'}
            return
        try:
            if not self.is_available():
                raise ValueError('consent-revoked')
            context = self.base.launch_context
            env = dict(context.env)
            if (env.get('CODEX_HOME') != self.auth_home or _FORBIDDEN_ENV.intersection(env)
                    or os.path.lexists(os.path.join(self.auth_home, 'config.toml'))):
                raise ValueError('unsafe-environment')
            env['PATH'] = safe_cli_path(self.base.cli_path, os.environ.get('PATH', ''))
            if self._managed_store is None and not _cli_version_supported(self.base.cli_path, cwd=context.cwd, env=env):
                raise ValueError('unsupported-cli-version')
            instructions = format_approval_outcomes(approval_outcomes)
            argv = _build_appserver_argv(self.base.cli_path)
            with codex_auth_lock(self.auth_home):
                if self._managed_store is not None and verify_managed_cli_locked(
                        self.agent_home, self._managed_store, self._managed_version, self.base.cli_path) is not True:
                    raise ValueError('managed-cli-denied')
                if not validate_credentials(self.auth_home):
                    raise ValueError('login-required')
                bridge = McpStdioBridge(self.base.launch_verifier.client, AUTH_PATH,
                    context.session_id, context.turn_id, 'codex', context.model, context.device_id)
                runner = AppServerProcess(self.base.process_supervisor, DynamicToolRelay(bridge),
                                          self.is_available, timeout=self.base.timeout)
                with self._state_lock:
                    self._runner = runner
                    stopping = self._stopping.is_set()
                if stopping:
                    runner.stop()
                try:
                    yield from runner.run(argv, cwd=context.cwd, env=env, model=self.base.model,
                        text=text, thread_ref=cli_session_ref, developer_instructions=instructions,
                        require_authenticated_account=True)
                finally:
                    with self._state_lock:
                        self._runner = None
        except Exception as error:
            code = 'CODEX-LOGIN-REQUIRED' if str(error) == 'login-required' else 'CODEX-FAILED'
            yield 'error', {'code': code}
        finally:
            self._lock.release()

    def stop(self):
        self._stopping.set()
        with self._state_lock:
            runner = self._runner
        if runner is not None:
            runner.stop()

    def close(self):
        self.stop()
        self.base.close()
