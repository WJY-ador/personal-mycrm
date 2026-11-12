"""Disabled candidate adapter for Codex subscription CLI.

The module is intentionally not registered or advertised. It can be constructed
only with a verified PC-consent grant and a server-authorized MyCRM MCP gateway
snapshot. Fixture tests do not prove Codex tool isolation, credential isolation,
or server-side authorization.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import queue
import re
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

from .chat_launch_authority import AUTH_PATH, LaunchAuthorizationClient, LaunchAuthorizationDenied
from .chat_process_supervisor import MacOSProcessSupervisor, ProcessContainmentUnavailable
from .chat_approval_context import format_approval_outcomes


_THREAD_ID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_ENV_ALLOW = {"HOME", "CODEX_HOME", "PATH", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL"}
_FORBIDDEN_ENV = {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"}
_SERVER = "my_crm"
_FORBIDDEN_TOOL_NAMES = {"trash_purge"}
MAX_LINE_BYTES = 256 * 1024
MAX_STREAM_BYTES = 8 * 1024 * 1024


class CodexProviderUnavailable(RuntimeError):
    pass


class CodexProcessSupervisor:
    """Process cleanup interface used by the Codex adapter."""

    def spawn(self, argv, **kwargs):
        raise NotImplementedError

    def finish(self, proc, timeout):
        raise NotImplementedError

    def terminate_tree(self, proc):
        raise NotImplementedError


class MacOSCodexProcessSupervisor(CodexProcessSupervisor):
    """Use the shared macOS process-group supervisor; it does not certify escaped descendants."""

    def __init__(self, *, popen=subprocess.Popen):
        self._delegate = MacOSProcessSupervisor(popen=popen)

    def spawn(self, argv, **kwargs):
        return self._delegate.spawn(argv, **kwargs)

    def finish(self, proc, timeout):
        return self._delegate.finish(proc, timeout)

    def terminate_tree(self, proc):
        return self._delegate.terminate_tree(proc)


def _private_dir(path: str, *, empty: bool = False) -> bool:
    if not isinstance(path, str) or not os.path.isabs(path):
        return False
    try:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_mode & 0o077:
            return False
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return False
        return not empty or not os.listdir(path)
    except OSError:
        return False


def _file_sha256(path: str) -> str:
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()
    except OSError:
        return ""


def _nonempty_id(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 256 and "\x00" not in value


class _CodexLaunchContext:
    def __init__(self, authorization, *, cli_path, cli_sha256, codex_home, gateway_path,
                 gateway_sha256, gateway_args, config, tools, env, cwd, runtime_dir, owner):
        self.user_id, self.device_id = authorization.user_id, authorization.device_id
        self.session_id, self.turn_id = authorization.session_id, authorization.turn_id
        self.provider, self.model = authorization.provider, authorization.model
        self.consent_id, self.consent_challenge_id = authorization.grant_id, authorization.consent_challenge_id
        self.expires_at = authorization.expires_at
        self.cli_path, self.cli_sha256 = cli_path, cli_sha256
        self.codex_home, self.gateway_path, self.gateway_sha256 = codex_home, gateway_path, gateway_sha256
        self.gateway_args = gateway_args
        self.config, self.tools, self.env = config, tools, env
        self.cwd, self.runtime_dir = cwd, runtime_dir
        self._authorization = authorization
        self._owner = owner
        self._cleanup_lock = threading.Lock()
        self._cleaned = False

    def current(self):
        return self.expires_at > time.time()

    def cleanup(self):
        with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
        self._owner.cleanup()


class _CodexLaunchVerifier:
    """Only factory-minted turn contexts can be revalidated by the server client."""

    def __init__(self, client):
        if type(client) is not LaunchAuthorizationClient:
            raise CodexProviderUnavailable("launch-authority-required")
        self.client = client
        self._contexts = {}
        self._next_check = {}
        self._lock = threading.Lock()

    @staticmethod
    def _same(left, right):
        return ((left.user_id, left.device_id, left.session_id, left.turn_id, left.provider, left.model,
                 left.grant_id, left.consent_challenge_id, dict(left.tools))
                == (right.user_id, right.device_id, right.session_id, right.turn_id, right.provider, right.model,
                    right.grant_id, right.consent_challenge_id, dict(right.tools)))

    def register(self, context):
        with self._lock:
            self._contexts[id(context)] = context
            self._next_check[id(context)] = time.monotonic() + 5.0

    def unregister(self, context):
        with self._lock:
            self._contexts.pop(id(context), None)
            self._next_check.pop(id(context), None)

    def verify_codex_grant(self, context):
        key = id(context)
        with self._lock:
            if self._contexts.get(key) is not context or not context.current():
                return False
            if time.monotonic() < self._next_check.get(key, 0):
                return True
            try:
                latest = self.client.authorize(AUTH_PATH, context.session_id, context.turn_id,
                                               "codex", context.model)
            except Exception:
                return False
            if not self._same(context._authorization, latest) or latest.expires_at <= time.time():
                return False
            context._authorization = latest
            context.expires_at = latest.expires_at
            self._next_check[key] = time.monotonic() + 5.0
            return True


class CodexProviderFactory:
    """Create a Codex provider only from HTTPS server authorization and a private app home."""

    name = "codex"

    def __init__(self, authorization_client, *, cli_path, server_url, agent_home, codex_home=None,
                 expected_device_id, models, env=None, process_supervisor=None, timeout=300):
        if type(authorization_client) is not LaunchAuthorizationClient or authorization_client.production_transport is not True:
            raise CodexProviderUnavailable("launch-transport-untrusted")
        if sys.platform != "darwin":
            raise CodexProviderUnavailable("platform")
        if authorization_client.server_origin != server_url.rstrip("/"):
            raise CodexProviderUnavailable("server-binding")
        if (not isinstance(cli_path, str) or not os.path.isabs(cli_path)
                or not os.path.isfile(cli_path) or os.path.islink(cli_path) or not os.access(cli_path, os.X_OK)):
            raise CodexProviderUnavailable("cli-unavailable")
        source_env = dict(os.environ if env is None else env)
        if codex_home is None:
            codex_home = source_env.get("CODEX_HOME")
            if not codex_home:
                user_home = source_env.get("HOME") or os.path.expanduser("~")
                codex_home = os.path.join(user_home, ".codex")
        if not _private_dir(agent_home) or not _private_dir(codex_home):
            raise CodexProviderUnavailable("codex-home")
        app_home = os.path.realpath(agent_home)
        codex_home_real = os.path.realpath(codex_home)
        if codex_home_real == app_home:
            raise CodexProviderUnavailable("codex-home")
        if not _nonempty_id(expected_device_id):
            raise CodexProviderUnavailable("device-binding")
        if (not isinstance(models, (tuple, list)) or not 1 <= len(models) <= 20
                or any(not isinstance(m, str) or not re.fullmatch(r"[A-Za-z0-9._:/+-]{1,120}", m)
                       for m in models)
                or len(set(models)) != len(models)):
            raise CodexProviderUnavailable("models")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise CodexProviderUnavailable("timeout")
        self.authorization_client = authorization_client
        self.cli_path = os.path.realpath(cli_path)
        self.cli_sha256 = self._hash(self.cli_path)
        if not self.cli_sha256:
            raise CodexProviderUnavailable("cli-unavailable")
        self.server_url, self.agent_home = server_url.rstrip("/"), app_home
        self.codex_home, self.expected_device_id = codex_home_real, expected_device_id
        self.models = tuple(models)
        self.env = self._clean_env(source_env, app_home, codex_home_real, self.cli_path)
        self.process_supervisor = process_supervisor or MacOSCodexProcessSupervisor()
        self.timeout = float(timeout)
        self.verifier = _CodexLaunchVerifier(authorization_client)

    @staticmethod
    def _hash(path):
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for block in iter(lambda: handle.read(64 * 1024), b""):
                    digest.update(block)
            return digest.hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _clean_env(source, agent_home, codex_home, cli_path):
        env = {key: value for key, value in source.items()
               if key in _ENV_ALLOW and isinstance(value, str) and "\x00" not in value}
        env.update({"HOME": agent_home, "CODEX_HOME": codex_home,
                    "PATH": os.path.dirname(cli_path) + os.pathsep + "/usr/bin:/bin"})
        return env

    def create_turn(self, session_id, turn_id, authorization_path, provider, model):
        if authorization_path != AUTH_PATH or provider != self.name or model not in self.models:
            raise CodexProviderUnavailable("launch-binding")
        try:
            authorization = self.authorization_client.authorize(AUTH_PATH, session_id, turn_id, provider, model)
        except LaunchAuthorizationDenied:
            raise CodexProviderUnavailable("launch-denied") from None
        if ((authorization.session_id, authorization.turn_id, authorization.provider, authorization.model)
                != (session_id, turn_id, provider, model) or authorization.expires_at <= time.time()
                or authorization.device_id != self.expected_device_id or not authorization.user_id
                or not authorization.tools.get("mcp__my-crm__find")):
            raise CodexProviderUnavailable("launch-binding")
        tools = {"mcp__my-crm__find": "read"}
        for tier in ("read", "write", "decide", "purge"):
            if any(value == tier for name, value in authorization.tools.items()
                   if name != "mcp__my-crm__find"):
                tools["mcp__my-crm__" + tier] = tier
        # The server's decide and purge surfaces only create a pending confirmation card;
        # final execution is a separate user-confirmed, one-time server action.
        owner = tempfile.TemporaryDirectory(prefix="codex-chat-turn-", dir=self.agent_home)
        context = None
        try:
            os.chmod(owner.name, 0o700)
            cwd = os.path.join(owner.name, "work")
            runtime_dir = os.path.join(owner.name, "runtime")
            os.mkdir(cwd, 0o700); os.mkdir(runtime_dir, 0o700)
            executable = os.path.realpath(sys.executable)
            executable_hash = self._hash(executable)
            frozen = bool(getattr(sys, "frozen", False))
            bridge_args = (("chat-mcp-bridge",) if frozen else ("-m", "agent.chat_mcp_bridge")) + (
                "--agent-home", self.agent_home, "--session-id", session_id, "--turn-id", turn_id,
                "--device-id", authorization.device_id, "--provider", provider, "--model", model,
                "--authorization-path", AUTH_PATH)
            if not executable_hash:
                raise CodexProviderUnavailable("bridge-pin")
            enabled_tools = list(tools)
            gateway_args = list(bridge_args)
            config = {"mcp_servers": {_SERVER: {"command": executable, "args": gateway_args,
                "enabled": True, "required": True, "enabled_tools": enabled_tools,
                "disabled_tools": ["trash_purge"]}},
                "features": {name: False for name in _DISABLED_FEATURES}}
            env = dict(self.env)
            env["TMPDIR"] = runtime_dir
            context = _CodexLaunchContext(authorization, cli_path=self.cli_path, cli_sha256=self.cli_sha256,
                codex_home=self.codex_home, gateway_path=executable, gateway_sha256=executable_hash,
                gateway_args=gateway_args,
                config=config, tools=tools, env=env, cwd=cwd, runtime_dir=runtime_dir, owner=owner)
            self.verifier.register(context)
            return CodexProvider(cli_path=self.cli_path, model=model, launch_context=context,
                launch_verifier=self.verifier, process_supervisor=self.process_supervisor, timeout=self.timeout)
        except Exception:
            if context is not None:
                self.verifier.unregister(context)
            owner.cleanup()
            raise


_DISABLED_FEATURES = ("shell_tool", "browser_use", "browser_use_external", "browser_use_full_cdp_access",
                      "computer_use", "in_app_browser", "in_app_local_automation", "web_search_request",
                      "standalone_web_search", "apps", "enable_mcp_apps")


def _validate_launch(grant, verifier, model):
    """Check server-issued user/device/session/provider/model grant and gateway scope."""
    if grant is None:
        return None
    try:
        server_minted = type(grant) is _CodexLaunchContext and type(verifier) is _CodexLaunchVerifier
        verify = getattr(verifier, "verify_codex_grant", None)
        if not callable(verify) or verify(grant) is not True or not grant.current():
            return None
        # Windows job-object containment is not implemented; fail closed there.
        if os.name == "nt":
            return None
        if any(not _nonempty_id(getattr(grant, name, None)) for name in ("user_id", "device_id", "session_id")):
            return None
        if grant.provider != "codex" or grant.model != model or not _nonempty_id(model):
            return None
        if (not _nonempty_id(grant.consent_id)
                or not isinstance(grant.expires_at, (int, float)) or grant.expires_at <= time.time()):
            return None
        if (not server_minted and (not _nonempty_id(grant.issuer)
                or not isinstance(grant.signature, str) or len(grant.signature) < 32)):
            return None
        if not isinstance(grant.cli_path, str) or not os.path.isabs(grant.cli_path):
            return None
        cli_stat = os.lstat(grant.cli_path)
        if not stat.S_ISREG(cli_stat.st_mode) or stat.S_ISLNK(cli_stat.st_mode) or not os.access(grant.cli_path, os.X_OK):
            return None
        with open(grant.cli_path, "rb") as cli_file:
            cli_digest = hashlib.sha256(cli_file.read()).hexdigest()
        if grant.cli_sha256 != cli_digest:
            return None
        if server_minted:
            gateway_path = grant.gateway_path
            gateway_stat = os.lstat(gateway_path)
            if (not stat.S_ISREG(gateway_stat.st_mode) or stat.S_ISLNK(gateway_stat.st_mode)
                    or not os.access(gateway_path, os.X_OK)
                    or not isinstance(grant.gateway_sha256, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", grant.gateway_sha256)
                    or _file_sha256(gateway_path) != grant.gateway_sha256):
                return None
        if not _private_dir(grant.cwd, empty=True) or not _private_dir(grant.runtime_dir):
            return None
        env = grant.env
        if (not isinstance(env, dict) or not {"HOME", "CODEX_HOME", "PATH"} <= set(env)
                or set(env) - _ENV_ALLOW or set(env) & _FORBIDDEN_ENV):
            return None
        if not all(isinstance(k, str) and isinstance(v, str) and "\x00" not in v for k, v in env.items()):
            return None
        if not os.path.isabs(env["CODEX_HOME"]) or not _private_dir(env["CODEX_HOME"]):
            return None
        if env["CODEX_HOME"] != grant.codex_home:
            return None
        config = grant.config
        expected_config_keys = {"mcp_servers", "features"} if server_minted else {"mcp_servers"}
        if not isinstance(config, dict) or set(config) != expected_config_keys:
            return None
        servers = config["mcp_servers"]
        if (not isinstance(servers, dict) or set(servers) != {_SERVER}
                or (server_minted and set(config) != {"mcp_servers", "features"})
                or (not server_minted and set(config) != {"mcp_servers"})):
            return None
        if server_minted:
            features = config["features"]
            if (not isinstance(features, dict) or set(features) != set(_DISABLED_FEATURES)
                    or any(value is not False for value in features.values())):
                return None
        server = servers[_SERVER]
        if not isinstance(server, dict) or set(server) != {"command", "args", "enabled", "required", "enabled_tools", "disabled_tools"}:
            return None
        command, args = server["command"], server["args"]
        if (not isinstance(command, str) or not os.path.isabs(command) or "\x00" in command
                or command != grant.gateway_path):
            return None
        if (not isinstance(args, list) or any(not isinstance(x, str) or "\x00" in x for x in args)
                or not isinstance(grant.gateway_args, list) or args != grant.gateway_args):
            return None
        if server["enabled"] is not True or server["required"] is not True:
            return None
        tools, denied = server["enabled_tools"], server["disabled_tools"]
        if (not isinstance(tools, list) or not tools or len(tools) != len(set(tools))
                or any(not isinstance(x, str) or not x or x in _FORBIDDEN_TOOL_NAMES for x in tools)):
            return None
        if not isinstance(denied, list) or not _FORBIDDEN_TOOL_NAMES <= set(denied):
            return None
        if any(not isinstance(x, str) for x in denied):
            return None
        if server_minted:
            allowed_surfaces = {"mcp__my-crm__find", "mcp__my-crm__read", "mcp__my-crm__write", "mcp__my-crm__decide",
                                "mcp__my-crm__purge"}
            if (set(tools) != set(grant.tools) or not set(tools) <= allowed_surfaces
                    or len(tools) != len(set(tools))):
                return None
        return tuple(sorted(tools))
    except Exception:
        return None


def _toml_string(value: str) -> str:
    # JSON basic-string escapes are a subset of TOML basic-string escapes.
    return json.dumps(value, ensure_ascii=False)


def _toml_strings(values) -> str:
    return "[" + ",".join(_toml_string(x) for x in values) + "]"


def build_argv(cli_path, model, config, cwd, thread_ref=None, approval_outcomes=()):
    """Build a shell-free fixed command. User text is supplied only through stdin."""
    if not isinstance(cli_path, str) or not os.path.isabs(cli_path) or not os.path.isfile(cli_path) or not os.access(cli_path, os.X_OK):
        raise CodexProviderUnavailable("cli-unavailable")
    if not isinstance(model, str) or not model or len(model) > 120 or "\x00" in model:
        raise CodexProviderUnavailable("model-unavailable")
    servers = config.get("mcp_servers", {})
    gateway = servers.get(_SERVER) if isinstance(servers, dict) else None
    if not isinstance(gateway, dict):
        raise CodexProviderUnavailable("gateway-scope")
    argv = [cli_path, "exec"]
    if thread_ref is not None:
        if not isinstance(thread_ref, str) or not _THREAD_ID.fullmatch(thread_ref):
            raise CodexProviderUnavailable("thread-ref")
        argv += ["resume", thread_ref]
    argv += ["--json", "--model", model, "--ignore-user-config", "--skip-git-repo-check"]
    if thread_ref is None:
        argv += ["--sandbox", "read-only"]
    for feature in _DISABLED_FEATURES:
        argv += ["--disable", feature]
    # Resume's installed help does not expose --sandbox; config overrides reassert
    # the same read-only and shell-disabled policy for both creation and resumption.
    overrides = [
        "sandbox_mode=\"read-only\"",
        "features.shell_tool=false",
        *[f"features.{feature}=false" for feature in _DISABLED_FEATURES],
        f"mcp_servers.{_SERVER}.command={_toml_string(gateway['command'])}",
        f"mcp_servers.{_SERVER}.args={_toml_strings(gateway['args'])}",
        f"mcp_servers.{_SERVER}.enabled=true",
        f"mcp_servers.{_SERVER}.required=true",
        f"mcp_servers.{_SERVER}.enabled_tools={_toml_strings(gateway['enabled_tools'])}",
        f"mcp_servers.{_SERVER}.disabled_tools={_toml_strings(gateway['disabled_tools'])}",
    ]
    trusted_context = format_approval_outcomes(approval_outcomes)
    if trusted_context:
        overrides.append("developer_instructions=" + _toml_string(trusted_context))
    for item in overrides:
        argv += ["-c", item]
    argv.append("-")
    return argv


def _map_event(obj, expected_thread):
    """Map documented Codex JSONL thread/turn/agent-message events only."""
    if not isinstance(obj, dict) or not isinstance(obj.get("type"), str):
        raise CodexProviderUnavailable("output-shape")
    kind = obj["type"]
    if kind == "thread.started":
        thread_id = obj.get("thread_id")
        if not isinstance(thread_id, str) or not _THREAD_ID.fullmatch(thread_id):
            raise CodexProviderUnavailable("thread-ref")
        if expected_thread is not None and thread_id != expected_thread:
            raise CodexProviderUnavailable("thread-mismatch")
        return [("session_ref", {"cli_session_ref": thread_id})]
    if kind in ("turn.started", "item.started", "item.updated"):
        return []
    if kind == "item.completed":
        item = obj.get("item")
        if not isinstance(item, dict):
            raise CodexProviderUnavailable("output-shape")
        # With shell_tool=false any command/file operation indicates unexpected
        # tool-surface drift. MCP calls stay inside the gateway and are not sent
        # back to the browser as guessed tool schemas.
        item_type = item.get("type")
        if item_type in ("command_execution", "file_change", "patch_apply"):
            raise CodexProviderUnavailable("tool-surface")
        if item_type == "agent_message":
            text = item.get("text")
            if not isinstance(text, str):
                raise CodexProviderUnavailable("output-shape")
            return [("delta", {"text": text})] if text else []
        return []
    if kind == "turn.completed":
        return [("done", {})]
    if kind in ("turn.failed", "error"):
        raise CodexProviderUnavailable("cli-result")
    raise CodexProviderUnavailable("output-event")


class CodexProvider:
    """Non-registered candidate Codex subscription CLI adapter."""

    name = "codex"

    def __init__(self, *, cli_path, model, launch_context=None, launch_verifier=None,
                 process_supervisor=None, timeout=300, line_max=MAX_LINE_BYTES, stream_max=MAX_STREAM_BYTES):
        tools = _validate_launch(launch_context, launch_verifier, model)
        if tools is None or launch_context.cli_path != cli_path:
            raise CodexProviderUnavailable("launch-not-authorized")
        if (not isinstance(process_supervisor, CodexProcessSupervisor)
                or type(process_supervisor).spawn is CodexProcessSupervisor.spawn
                or type(process_supervisor).finish is CodexProcessSupervisor.finish
                or type(process_supervisor).terminate_tree is CodexProcessSupervisor.terminate_tree):
            raise CodexProviderUnavailable("process-supervisor-required")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise CodexProviderUnavailable("timeout")
        self.cli_path, self.model = cli_path, model
        self.launch_context, self.launch_verifier = launch_context, launch_verifier
        self._config_snapshot = json.dumps(copy.deepcopy(launch_context.config), ensure_ascii=False, separators=(",", ":"))
        self._tools = tools
        self.models = (model,)
        self.process_supervisor, self.timeout = process_supervisor, float(timeout)
        self.line_max, self.stream_max = line_max, stream_max
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._termination_lock = threading.Lock()
        self._proc = None
        self._stopping = threading.Event()

    def is_available(self):
        tools = _validate_launch(self.launch_context, self.launch_verifier, self.model)
        if tools != self._tools or tools is None or self.launch_context.cli_path != self.cli_path:
            return False
        try:
            return json.dumps(self.launch_context.config, ensure_ascii=False, separators=(",", ":")) == self._config_snapshot
        except Exception:
            return False

    def start_turn(self, text: str, cli_session_ref: str | None = None, *, approval_outcomes=()):
        if self._stopping.is_set():
            yield "error", {"code": "STOPPED"}
            return
        if not self.is_available():
            yield "error", {"code": "CONSENT-REQUIRED"}
            return
        if not isinstance(text, str) or len(text) > 8000 or "\x00" in text:
            yield "error", {"code": "CODEX-INPUT-SHAPE"}
            return
        if cli_session_ref is not None and (not isinstance(cli_session_ref, str) or not _THREAD_ID.fullmatch(cli_session_ref)):
            yield "error", {"code": "CODEX-THREAD-REF"}
            return
        if not self._lock.acquire(blocking=False):
            yield "error", {"code": "CODEX-BUSY"}
            return
        proc, temp_dir = None, None
        reader = None
        q = queue.Queue()
        seen_thread = None
        ended = False
        failure = None
        successful = False
        try:
            if self._stopping.is_set():
                raise CodexProviderUnavailable("STOPPED")
            # Empty private scratch is used as cwd. MCP gateway policy is injected
            # from the verified grant and never from project/user config.
            temp_dir = tempfile.TemporaryDirectory(prefix="codex-chat-", dir=self.launch_context.runtime_dir)
            os.chmod(temp_dir.name, 0o700)
            argv = build_argv(self.cli_path, self.model, self.launch_context.config,
                              self.launch_context.cwd, cli_session_ref,
                              approval_outcomes=approval_outcomes)
            env = dict(self.launch_context.env)
            env["TMPDIR"] = temp_dir.name
            if _FORBIDDEN_ENV & env.keys():
                raise CodexProviderUnavailable("api-key-env")
            if not self.is_available():
                raise CodexProviderUnavailable("CONSENT-REVOKED")
            if self._stopping.is_set():
                raise CodexProviderUnavailable("STOPPED")
            # Process group/session creation is the supervisor's responsibility.
            # Passing start_new_session here makes the supervisor reject the launch
            # because it must own the pgid setup and its cleanup invariant.
            kw = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                  "cwd": self.launch_context.cwd, "env": env}
            proc = self.process_supervisor.spawn(argv, **kw)
            with self._state_lock:
                self._proc = proc
                cancelled = self._stopping.is_set()
            if cancelled:
                raise CodexProviderUnavailable("STOPPED")
            if not self.is_available():
                raise CodexProviderUnavailable("CONSENT-REVOKED")
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()

            def read_lines():
                total = 0
                try:
                    while True:
                        line = proc.stdout.readline(self.line_max + 1)
                        if not line:
                            q.put(("eof", None))
                            return
                        total += len(line)
                        if len(line) > self.line_max or total > self.stream_max:
                            q.put(("too-large", None))
                            return
                        q.put(("line", line))
                except Exception:
                    q.put(("reader-error", None))

            reader = threading.Thread(target=read_lines, name="codex-jsonl", daemon=True)
            reader.start()
            deadline = time.monotonic() + self.timeout
            while not ended:
                if self._stopping.is_set():
                    raise CodexProviderUnavailable("STOPPED")
                verify = getattr(self.launch_verifier, "verify_codex_grant", None)
                if not self.launch_context.current() or not callable(verify) or verify(self.launch_context) is not True:
                    raise CodexProviderUnavailable("CONSENT-REVOKED")
                remain = deadline - time.monotonic()
                if remain <= 0:
                    raise CodexProviderUnavailable("TIMEOUT")
                try:
                    event_kind, raw = q.get(timeout=min(0.1, remain))
                except queue.Empty:
                    continue
                if event_kind == "eof":
                    break
                if event_kind in ("too-large", "reader-error"):
                    raise CodexProviderUnavailable("CLI-OUTPUT")
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise CodexProviderUnavailable("CLI-OUTPUT") from None
                if isinstance(obj, dict) and obj.get("type") == "thread.started":
                    candidate = obj.get("thread_id")
                    if seen_thread is not None and candidate != seen_thread:
                        raise CodexProviderUnavailable("THREAD-MISMATCH")
                    if cli_session_ref is not None and candidate != cli_session_ref:
                        raise CodexProviderUnavailable("THREAD-MISMATCH")
                    if not isinstance(candidate, str) or not _THREAD_ID.fullmatch(candidate):
                        raise CodexProviderUnavailable("THREAD-REF")
                    seen_thread = candidate
                elif isinstance(obj, dict) and obj.get("type", "").startswith(("turn.", "item.")):
                    if seen_thread is None:
                        raise CodexProviderUnavailable("CLI-OUTPUT")
                events = _map_event(obj, cli_session_ref)
                for kind, data in events:
                    if kind == "done":
                        ended = True
                        continue  # don't report success before process cleanup is confirmed
                    yield kind, data
            rc, _tree_clean = self.process_supervisor.finish(
                proc, max(0.1, min(2.0, deadline - time.monotonic())))
            reader.join(timeout=1)
            if reader.is_alive():
                raise CodexProviderUnavailable("CLI-OUTPUT")
            if proc.stdout:
                proc.stdout.close()
            proc = None  # supervisor has reaped it and released containment
            if seen_thread is None or rc != 0 or not ended:
                raise CodexProviderUnavailable("CLI-EXIT")
            successful = True
        except CodexProviderUnavailable as exc:
            code = str(exc)
            if code == "STOPPED" or self._stopping.is_set():
                failure = {"code": "STOPPED"}
            elif code.startswith("CONSENT"):
                failure = {"code": "CONSENT-REQUIRED"}
            elif code == "TIMEOUT":
                failure = {"code": "CODEX-TIMEOUT"}
            elif code == "thread-ref" or code == "THREAD-REF":
                failure = {"code": "CODEX-THREAD-REF"}
            else:
                failure = {"code": "CODEX-FAILED"}
        except Exception:
            failure = {"code": "CODEX-FAILED"}
        finally:
            if proc is not None:
                try:
                    self.process_supervisor.terminate_tree(proc)
                except Exception:
                    failure = {"code": "CODEX-FAILED"}
                    successful = False
                try:
                    if proc.stdout:
                        proc.stdout.close()
                except Exception:
                    pass
            if temp_dir is not None:
                try:
                    temp_dir.cleanup()
                except Exception:
                    failure = {"code": "CODEX-FAILED"}
                    successful = False
            with self._state_lock:
                self._proc = None
            self._lock.release()
        if failure is not None:
            yield "error", failure
        elif successful:
            yield "done", {}

    def stop(self):
        self._stopping.set()
        with self._state_lock:
            proc = self._proc
        if proc is not None:
            self.process_supervisor.terminate_tree(proc)

    def close(self):
        self.stop()
        cleanup = getattr(self.launch_context, "cleanup", None)
        if callable(cleanup):
            cleanup()
        unregister = getattr(self.launch_verifier, "unregister", None)
        if callable(unregister):
            unregister(self.launch_context)
