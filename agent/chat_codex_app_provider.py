"""Unregistered, disabled Codex app-server provider candidate.

The feature remains off until tool isolation, login and real CLI E2E have been
verified. Do not register or enable this provider solely on the unit tests.
"""
from __future__ import annotations

import os
import threading

from .chat_approval_context import format_approval_outcomes
from .chat_codex import CodexProvider, _DISABLED_FEATURES, _FORBIDDEN_ENV
from .chat_codex_auth import codex_auth_lock, prepare_codex_home, safe_cli_path, validate_credentials
from .chat_codex_dynamic import AppServerProcess, DynamicToolRelay
from .chat_launch_authority import AUTH_PATH
from .chat_mcp_bridge import McpStdioBridge

APP_SERVER_CANDIDATE_READY = False
_EXTRA_DISABLED = ('plugins', 'hooks', 'multi_agent', 'unified_exec', 'view_image',
                   'image_generation', 'skill_search', 'skill_mcp_dependency_install',
                   'code_mode_host', 'tool_suggest', 'sleep_tool')


class AppServerCandidateProvider:
    name = 'codex'

    def __init__(self, base, *, agent_home):
        if APP_SERVER_CANDIDATE_READY is not True:
            raise ValueError('not-ready')
        if type(base) is not CodexProvider or not base.is_available():
            raise ValueError('launch-denied')
        if not isinstance(agent_home, str) or not os.path.isabs(agent_home):
            raise ValueError('agent-home')
        auth_home = prepare_codex_home(agent_home)
        if base.launch_context.codex_home != auth_home:
            raise ValueError('auth-home-binding')
        if os.path.lexists(os.path.join(auth_home, 'config.toml')):
            raise ValueError('unexpected-user-config')
        self.base = base
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
            instructions = format_approval_outcomes(approval_outcomes)
            argv = [self.base.cli_path, 'app-server', '--listen', 'stdio://',
                    '-c', 'cli_auth_credentials_store="file"', '-c', 'web_search="disabled"',
                    '-c', 'mcp_servers={}']
            for name in dict.fromkeys(_DISABLED_FEATURES + _EXTRA_DISABLED):
                argv.extend(('-c', 'features.' + name + '=false'))
            with codex_auth_lock(self.auth_home):
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
                        text=text, thread_ref=cli_session_ref, developer_instructions=instructions)
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
