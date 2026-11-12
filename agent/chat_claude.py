"""Claude subscription-CLI provider. Built by agent/cli.py only when CHAT_CLAUDE_PROVIDER_READY is on.

This module is only a process/stream adapter. `--allowedTools` is not authorization;
the MyCRM launch grant is issued by the server gateway (launch-authorization) and checked
by the factory's _ServerLaunchVerifier, which enforces the existing MyCRM permission rules.
No injected verifier can enable this provider. Fixture tests do not prove CLI tool
isolation or subscription terms.
"""
from __future__ import annotations

import json
import copy
import hashlib
import os
import shutil
import queue
import re
import stat
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

from .chat_process_supervisor import MacOSProcessSupervisor, ProcessContainmentUnavailable
from .chat_launch_authority import AUTH_PATH, LaunchAuthorizationClient, LaunchAuthorizationDenied
from .chat_approval_context import format_approval_outcomes


_SESSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_SERVER_NAME = "my-crm"
_TOOL_PREFIX = "mcp__my-crm__"
_ALLOWED_TIERS = {"read", "write", "decide", "purge"}
# The purge surface (AI 하나로 A3) only creates a server-owned confirmation card, like decide. The direct
# trash_purge tool name must never be exposed as a surface.
_DENIED_TOOLS = {"trash_purge"}  # exact MyCRM aliases after _TOOL_PREFIX
_SURFACE_NAMES = frozenset(("find", "read", "write", "decide", "purge"))  # the only MyCRM tools a turn may expose
_ENV_ALLOW = {"HOME", "PATH", "USER", "LOGNAME", "TMPDIR", "LANG", "LC_ALL"}
_FORBIDDEN_ENV = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_BASE_URL",
                  "OPENAI_BASE_URL", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX"}
# Belt-and-braces deny list. It is NOT the isolation layer: `--tools ""` is. Without `--tools ""`
# CLI 2.1.322 still exposed 13 other built-ins (ToolSearch, SendMessage, Cron*, *Worktree, ...)
# that no deny list here names (probe 2026-11-10, r12). The subagent tool is now "Agent";
# "Task" is kept as the older name. "TaskOutput" no longer exists in the CLI and was dropped.
_DISALLOWED_BUILTINS = (
    "Bash", "PowerShell", "Read", "Write", "Edit", "NotebookEdit", "Glob", "Grep",
    "WebFetch", "WebSearch", "Agent", "Task", "TaskStop", "Skill",
    "EnterPlanMode", "ExitPlanMode", "AskUserQuestion",
)
# Full model IDs only. Aliases (sonnet, opus, ...) are reported back by the CLI as the resolved ID,
# so an alias can never pass the init model check. Kept within agent/chat_providers.py (<=100
# chars) and server/webchat.py MODEL_RE.
_MODEL_ID = re.compile(r"^claude-[a-z0-9]+(?:-[a-z0-9]+)*$")
MAX_MODEL_ID_CHARS = 100
MAX_ADVERTISED_MODELS = 16  # server/webchat.py _normalize_capabilities accepts 1..16 per provider
_MODEL_QUERY_ID = "mycrm-models-1"
MODEL_QUERY_TIMEOUT = 15.0
# Set only by ClaudeProviderFactory to its _ServerLaunchVerifier (server launch-authorization).
# An injected verifier (including a test lambda) never matches it, so it cannot turn a provider on.
_TRUSTED_LAUNCH_VERIFIER = None
MAX_LINE_BYTES = 256 * 1024
MAX_STREAM_BYTES = 8 * 1024 * 1024


class ClaudeProviderUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class PinnedBridgeDescriptor:
    """Immutable app-owned bridge pin supplied and authenticated by the launch authority."""

    executable: str
    args: tuple[str, ...]
    sha256: str
    code_path: str | None = None
    code_sha256: str | None = None


def _session_id(value):
    return isinstance(value, str) and bool(_SESSION_ID.fullmatch(value))


def _private_dir(path, *, must_be_empty=False):
    if not isinstance(path, str) or not os.path.isabs(path):
        return False
    try:
        st = os.lstat(path)
        if not stat.S_ISDIR(st.st_mode) or stat.S_ISLNK(st.st_mode) or st.st_mode & 0o077:
            return False
        if hasattr(os, "getuid") and st.st_uid != os.getuid():
            return False
        return not must_be_empty or not os.listdir(path)
    except OSError:
        return False


def _file_matches_pin(path, expected_sha256):
    fd = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(path, flags)
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or not st.st_mode & 0o111:
            return False
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb") as handle:
            fd = None
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha256
    except OSError:
        return False
    finally:
        if fd is not None:
            os.close(fd)


def _bridge_matches_pin(bridge):
    return (_file_matches_pin(bridge.executable, bridge.sha256)
            and (bridge.code_path is None and bridge.code_sha256 is None
                 or isinstance(bridge.code_path, str) and isinstance(bridge.code_sha256, str)
                 and _file_hash_matches(bridge.code_path, bridge.code_sha256)))


def _file_hash_matches(path, expected_sha256):
    try:
        h = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(64 * 1024), b""):
                h.update(chunk)
        return h.hexdigest() == expected_sha256
    except OSError:
        return False


def _validate_launch(launch_context, verifier, model, cli_path, *, verify_files=True):
    """Validate the externally issued, session-bound PC consent + gateway snapshot."""
    if (_TRUSTED_LAUNCH_VERIFIER is None or verifier is not _TRUSTED_LAUNCH_VERIFIER
            or launch_context is None):
        return None
    try:
        if not verifier(launch_context) or not launch_context.current():
            return None
        if (not _session_id(launch_context.session_id)
                or not isinstance(launch_context.user_id, str) or not launch_context.user_id
                or not isinstance(launch_context.device_id, str) or not launch_context.device_id
                or launch_context.provider != "claude"
                or not isinstance(launch_context.consent_id, str) or not launch_context.consent_id
                or not isinstance(launch_context.consent_expires_at, (int, float))
                or launch_context.consent_expires_at <= time.time()):
            return None
        if launch_context.model != model:
            return None
        if (not isinstance(launch_context.cli_path, str) or launch_context.cli_path != cli_path
                or not isinstance(launch_context.cli_sha256, str)
                or not re.fullmatch(r"[a-f0-9]{64}", launch_context.cli_sha256)
                or (verify_files and not _file_matches_pin(cli_path, launch_context.cli_sha256))):
            return None
        tools = launch_context.tools
        if not isinstance(tools, dict) or not tools:
            return None
        for name, tier in tools.items():
            if (not isinstance(name, str) or not name.startswith(_TOOL_PREFIX)
                    or name[len(_TOOL_PREFIX):] in _DENIED_TOOLS or tier not in _ALLOWED_TIERS):
                return None
            # Each MyCRM surface carries exactly its own tier (find is read), so a purge alias cannot ride a decide grant.
            tail = name[len(_TOOL_PREFIX):]
            if tail not in _SURFACE_NAMES or tier != ("read" if tail == "find" else tail):
                return None
        config = launch_context.config
        if not isinstance(config, dict) or set(config) != {"mcpServers"}:
            return None
        servers = config.get("mcpServers")
        if not isinstance(servers, dict) or set(servers) != {_SERVER_NAME}:
            return None
        bridge = launch_context.bridge
        if (not isinstance(bridge, PinnedBridgeDescriptor)
                or not os.path.isabs(bridge.executable)
                or not isinstance(bridge.args, tuple)
                or any(not isinstance(arg, str) or "\x00" in arg for arg in bridge.args)
                or not re.fullmatch(r"[a-f0-9]{64}", bridge.sha256)
                or ((bridge.code_path is None) != (bridge.code_sha256 is None))
                or (bridge.code_sha256 is not None and not re.fullmatch(r"[a-f0-9]{64}", bridge.code_sha256))):
            return None
        if verify_files and not _bridge_matches_pin(bridge):
            return None
        server = servers[_SERVER_NAME]
        if (not isinstance(server, dict) or set(server) != {"command", "args"}
                or server.get("command") != bridge.executable
                or server.get("args") != list(bridge.args)):
            return None
        if not _private_dir(launch_context.cwd, must_be_empty=True):
            return None
        if not _private_dir(launch_context.runtime_dir):
            return None
        env = launch_context.env
        if not isinstance(env, dict) or not {"HOME", "PATH"} <= set(env):
            return None
        if set(env) - _ENV_ALLOW or set(env) & _FORBIDDEN_ENV:
            return None
        if not all(isinstance(k, str) and isinstance(v, str) and "\x00" not in v for k, v in env.items()):
            return None
        return tuple(sorted(tools))
    except Exception:
        return None


def _valid_model_id(model):
    return (isinstance(model, str) and len(model) <= MAX_MODEL_ID_CHARS
            and bool(_MODEL_ID.fullmatch(model)))


def _cli_file_trusted(st):
    trusted = {0, os.getuid()} if hasattr(os, "getuid") else None
    return trusted is None or st.st_uid in trusted


def resolve_cli_path(cli_path):
    """Follow the configured CLI link once per agent start and return the real file to pin.

    Installers keep a stable link (for example ~/.local/bin/claude -> .../versions/<v>) and point
    it at a new file on update. Only this function follows links. Every later check opens the
    resolved path with O_NOFOLLOW and re-hashes it (`_file_matches_pin`), so a file replaced
    after this point fails closed; the next agent start resolves and pins again.
    The link itself, the final file and the final file's directory must be owned by the user
    or root, and the file and directory must not be group/other-writable.
    """
    if not isinstance(cli_path, str) or not os.path.isabs(cli_path) or "\x00" in cli_path:
        raise ClaudeProviderUnavailable("cli-unavailable")
    try:
        configured = os.lstat(cli_path)
        resolved = os.path.realpath(cli_path)
        target = os.lstat(resolved)
        parent = os.lstat(os.path.dirname(resolved))
    except OSError:
        raise ClaudeProviderUnavailable("cli-unavailable") from None
    if (not (stat.S_ISREG(configured.st_mode) or stat.S_ISLNK(configured.st_mode))
            or not _cli_file_trusted(configured)
            or not stat.S_ISREG(target.st_mode) or not target.st_mode & 0o111
            or target.st_mode & 0o022 or not _cli_file_trusted(target)
            or not stat.S_ISDIR(parent.st_mode) or parent.st_mode & 0o022
            or not _cli_file_trusted(parent)):
        raise ClaudeProviderUnavailable("cli-unavailable")
    return resolved


def models_from_initialize(message):
    """Keep only resolved full model IDs from a control_response to `initialize`.

    Everything else in the response (account, commands, agents, ...) is dropped here and never
    returned, logged or stored. Order follows the CLI (recommended aliases first); duplicates are
    removed and the list is cut at MAX_ADVERTISED_MODELS.
    """
    if not isinstance(message, dict) or message.get("type") != "control_response":
        return ()
    outer = message.get("response")
    if (not isinstance(outer, dict) or outer.get("request_id") != _MODEL_QUERY_ID
            or outer.get("subtype") != "success"):
        return ()
    inner = outer.get("response")
    rows = inner.get("models") if isinstance(inner, dict) else None
    if not isinstance(rows, list):
        return ()
    models = []
    for row in rows:
        model = row.get("resolvedModel") if isinstance(row, dict) else None
        if _valid_model_id(model) and model not in models:
            models.append(model)
        if len(models) == MAX_ADVERTISED_MODELS:
            break
    return tuple(models)


def query_cli_models(cli_path, env, cwd, process_supervisor, *, timeout=MODEL_QUERY_TIMEOUT):
    """Ask the pinned CLI which models this login can use, without starting a model turn.

    Sends only a stream-json `initialize` control request: no user message, so no API request and
    no subscription usage (probe 2026-11-10: no API dispatch in the debug log, no transcript with
    --no-session-persistence, answer in ~0.5 s). Returns () on any failure; callers must then
    advertise no Claude model rather than invent one.
    """
    argv = [cli_path, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--restricted", "--strict-mcp-config", "--tools", "", "--permission-mode", "dontAsk",
            "--permission-prompts", "none", "--disable-slash-commands", "--no-session-persistence"]
    request = {"type": "control_request", "request_id": _MODEL_QUERY_ID, "request": {"subtype": "initialize"}}
    proc = None
    lines = queue.Queue()
    try:
        proc = process_supervisor.spawn(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, cwd=cwd, env=env, shell=False, close_fds=True)
        proc.stdin.write((json.dumps(request, separators=(",", ":")) + "\n").encode("utf-8"))
        proc.stdin.flush()

        def read_lines():
            total = 0
            try:
                while total <= MAX_STREAM_BYTES:
                    line = proc.stdout.readline(MAX_LINE_BYTES + 1)
                    if not line or len(line) > MAX_LINE_BYTES:
                        break
                    total += len(line)
                    lines.put(line)
            except Exception:
                pass
            lines.put(None)

        threading.Thread(target=read_lines, name="claude-models", daemon=True).start()
        deadline = time.monotonic() + timeout
        while True:
            remain = deadline - time.monotonic()
            if remain <= 0:
                return ()
            try:
                line = lines.get(timeout=remain)
            except queue.Empty:
                return ()
            if line is None:
                return ()
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                return ()
            if isinstance(message, dict) and message.get("type") == "control_response":
                return models_from_initialize(message)
    except Exception:
        return ()
    finally:
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                process_supervisor.terminate_tree(proc)
            except Exception:
                pass
            try:
                if proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass


def build_argv(cli_path: str, model: str, tools: tuple[str, ...], config_path: str, resume: str | None = None,
               approval_outcomes=()) -> list[str]:
    """Fixed argument vector: prompt is stdin-only; never use a shell.

    Load-bearing flags (CLI 2.1.322 probe, 2026-11-10; do not drop any of them):
    - `--tools ""` removes every built-in tool. It is the isolation layer; the deny list is not.
    - `--restricted` ignores user/project/local settings (hooks, plugins, skills, CLAUDE.md) and
      confines file tools to the working directory. Without it the user's hooks ran.
    - `--permission-mode dontAsk` denies any tool outside --allowedTools. The organisation's remote
      managed settings can set defaultMode=bypassPermissions; this flag overrides it, and with
      `--restricted` a missing mode makes the CLI refuse to start instead.
    - `--strict-mcp-config` keeps the user's own MCP servers and claude.ai connectors out.
    - `--system-prompt-snapshot off`: with the default (on) a resumed session reuses the first
      turn's system prompt and silently drops this turn's --append-system-prompt, so approval
      outcomes of later turns would never reach the model.
    """
    if not isinstance(cli_path, str) or not os.path.isabs(cli_path) or not os.path.isfile(cli_path) or not os.access(cli_path, os.X_OK):
        raise ClaudeProviderUnavailable("cli-unavailable")
    if not _valid_model_id(model):
        raise ClaudeProviderUnavailable("model-unavailable")
    if not tools or any(not isinstance(t, str) or not t.startswith(_TOOL_PREFIX) or t[len(_TOOL_PREFIX):] in _DENIED_TOOLS
                        or t[len(_TOOL_PREFIX):] not in _SURFACE_NAMES for t in tools):
        raise ClaudeProviderUnavailable("tool-scope")
    argv = [cli_path, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", model, "--restricted", "--strict-mcp-config", "--tools", "",
            "--disallowedTools", *_DISALLOWED_BUILTINS, "--mcp-config", config_path,
            "--permission-mode", "dontAsk", "--permission-prompts", "none",
            "--disable-slash-commands", "--system-prompt-snapshot", "off", "--allowedTools", *tools]
    # Claude CLI persistence stays enabled because follow-up turns use --resume.
    # Its local transcript retention is therefore separate from server retention.
    if resume is not None:
        if not _session_id(resume):
            raise ClaudeProviderUnavailable("session-ref")
        argv += ["--resume", resume]
    trusted_context = format_approval_outcomes(approval_outcomes)
    if trusted_context:
        argv += ["--append-system-prompt", trusted_context]
    return argv


def user_jsonl(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 8000 or "\x00" in text:
        raise ClaudeProviderUnavailable("input-shape")
    row = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}
    return (json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def _text_content(value):
    if isinstance(value, str):
        return value[:4000]
    if isinstance(value, list):
        return " ".join(x.get("text", "") for x in value if isinstance(x, dict) and x.get("type") == "text" and isinstance(x.get("text"), str))[:4000]
    return ""


def _message_events(obj, allowed_tools, tool_ids):
    """Map only the documented SDKMessage union and known content blocks; ignore unknown blocks/types."""
    if not isinstance(obj, dict):
        raise ClaudeProviderUnavailable("output-shape")
    typ = obj.get("type")
    if typ == "system" and obj.get("subtype") == "init":
        sid = obj.get("session_id")
        if not _session_id(sid):
            raise ClaudeProviderUnavailable("session-ref")
        return [("session_ref", {"cli_session_ref": sid})]
    if typ == "assistant":
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            raise ClaudeProviderUnavailable("output-shape")
        events = []
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"]:
                events.append(("delta", {"text": block["text"]}))
            elif block.get("type") == "tool_use":
                name, tid, data = block.get("name"), block.get("id"), block.get("input")
                if name not in allowed_tools or not isinstance(tid, str) or len(tid) > 128 or not isinstance(data, dict):
                    raise ClaudeProviderUnavailable("tool-scope")
                tool_ids[tid] = name
                events.append(("tool_call", {"name": name, "input": data}))
        return events
    if typ == "user":
        message = obj.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, list):
            return []
        events = []
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tid = block.get("tool_use_id")
            name = tool_ids.pop(tid, None) if isinstance(tid, str) else None
            if name:
                events.append(("tool_result", {"name": name, "ok": block.get("is_error") is not True,
                                                "summary": _text_content(block.get("content"))}))
        return events
    if typ == "result":
        if obj.get("subtype") == "success" and obj.get("is_error") is not True:
            sid = obj.get("session_id")
            if sid is not None and not _session_id(sid):
                raise ClaudeProviderUnavailable("session-ref")
            return [("done", {})]
        if obj.get("subtype") in ("error_max_turns", "error_during_execution") or obj.get("is_error") is True:
            raise ClaudeProviderUnavailable("cli-result")
        return []
    return []


class ClaudeProvider:
    """Candidate adapter for the existing CLI. No default registration is provided."""

    name = "claude"

    def __init__(self, *, cli_path, model, launch_context=None, launch_verifier=None,
                 popen=subprocess.Popen, process_supervisor=None, timeout=300,
                 line_max=MAX_LINE_BYTES, stream_max=MAX_STREAM_BYTES):
        if _validate_launch(launch_context, launch_verifier, model, cli_path) is None:
            raise ClaudeProviderUnavailable("launch-integration-unavailable")
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ClaudeProviderUnavailable("timeout")
        self.cli_path, self.model = cli_path, model
        self.launch_context, self.launch_verifier = launch_context, launch_verifier
        self._config_snapshot = json.dumps(copy.deepcopy(launch_context.config), ensure_ascii=False, separators=(",", ":"))
        self._tool_snapshot = tuple(_validate_launch(launch_context, launch_verifier, model, cli_path))
        self.models = (model,)
        self.process_supervisor = process_supervisor or MacOSProcessSupervisor(popen=popen)
        if not isinstance(self.process_supervisor, MacOSProcessSupervisor):
            raise ClaudeProviderUnavailable("process-supervisor-required")
        self.timeout = float(timeout)
        self.line_max, self.stream_max = line_max, stream_max
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._proc = None
        self._stopping = threading.Event()

    def is_available(self):
        current_tools = _validate_launch(self.launch_context, self.launch_verifier, self.model, self.cli_path,
                                         verify_files=False)
        if current_tools is None or current_tools != self._tool_snapshot:
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
        tools = self._tool_snapshot
        try:
            payload = user_jsonl(text)
            if cli_session_ref is not None and not _session_id(cli_session_ref):
                raise ClaudeProviderUnavailable("session-ref")
        except ClaudeProviderUnavailable as exc:
            yield "error", {"code": "CLI-" + str(exc).upper().replace("_", "-")}
            return
        if not self._lock.acquire(blocking=False):
            yield "error", {"code": "CLI-BUSY"}
            return
        proc = None
        temp_dir = None
        q = queue.Queue()
        failure = None
        successful = False
        try:
            if self._stopping.is_set():
                raise ClaudeProviderUnavailable("STOPPED")
            # The gateway supplies a private runtime directory and validated config. The file is
            # ephemeral and mode 0600; it is never copied into the model's environment.
            temp_dir = tempfile.TemporaryDirectory(prefix="claude-mcp-", dir=self.launch_context.runtime_dir)
            os.chmod(temp_dir.name, 0o700)
            config_path = os.path.join(temp_dir.name, "mcp.json")
            fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            try:
                if not self.is_available():
                    raise ClaudeProviderUnavailable("CONSENT-REVOKED")
                data = self._config_snapshot.encode("utf-8")
                with os.fdopen(fd, "wb") as f:
                    f.write(data)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                try: os.close(fd)
                except OSError: pass
                raise
            argv = build_argv(self.cli_path, self.model, tools, config_path, cli_session_ref,
                              approval_outcomes=approval_outcomes)
            if self._stopping.is_set():
                raise ClaudeProviderUnavailable("STOPPED")
            if _validate_launch(self.launch_context, self.launch_verifier, self.model, self.cli_path) is None:
                raise ClaudeProviderUnavailable("CONSENT-REVOKED")
            env = dict(self.launch_context.env)  # never inherit ambient API-key variables
            if _FORBIDDEN_ENV & env.keys():
                raise ClaudeProviderUnavailable("api-key-env")
            kw = {"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "stderr": subprocess.DEVNULL,
                  "cwd": self.launch_context.cwd, "env": env, "shell": False, "close_fds": True}
            proc = self.process_supervisor.spawn(argv, **kw)
            with self._state_lock:
                self._proc = proc
                cancelled = self._stopping.is_set()
            if cancelled:
                raise ClaudeProviderUnavailable("STOPPED")
            if not self.is_available():
                raise ClaudeProviderUnavailable("CONSENT-REVOKED")
            proc.stdin.write(payload)
            proc.stdin.flush()
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

            reader = threading.Thread(target=read_lines, name="claude-jsonl", daemon=True)
            reader.start()
            deadline = time.monotonic() + self.timeout
            tool_ids = {}
            seen_init = False
            cli_session_id = None
            ended = False
            while not ended:
                if self._stopping.is_set():
                    raise ClaudeProviderUnavailable("STOPPED")
                if not self.launch_context.current() or not self.launch_verifier(self.launch_context):
                    raise ClaudeProviderUnavailable("CONSENT-REVOKED")
                remain = deadline - time.monotonic()
                if remain <= 0:
                    raise ClaudeProviderUnavailable("TIMEOUT")
                try:
                    kind, raw = q.get(timeout=min(0.1, remain))
                except queue.Empty:
                    continue
                if kind == "eof":
                    break
                if kind in ("too-large", "reader-error"):
                    raise ClaudeProviderUnavailable("CLI-OUTPUT")
                try:
                    obj = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    raise ClaudeProviderUnavailable("CLI-OUTPUT") from None
                if isinstance(obj, dict) and obj.get("type") == "system" and obj.get("subtype") == "init":
                    if seen_init and obj.get("session_id") != cli_session_id:
                        raise ClaudeProviderUnavailable("CLI-OUTPUT")
                    if obj.get("model") != self.model or not self._init_scope_ok(obj, tools):
                        raise ClaudeProviderUnavailable("CLI-SCOPE")
                    seen_init = True
                    cli_session_id = obj.get("session_id")
                elif isinstance(obj, dict) and obj.get("type") in ("assistant", "user", "result"):
                    if not seen_init or obj.get("session_id") != cli_session_id:
                        raise ClaudeProviderUnavailable("CLI-OUTPUT")
                events = _message_events(obj, tools, tool_ids)
                for event_kind, event_data in events:
                    if event_kind == "session_ref" and not seen_init:
                        raise ClaudeProviderUnavailable("CLI-OUTPUT")
                    if event_kind == "done":
                        ended = True
                        continue  # success waits for process cleanup confirmation
                    yield event_kind, event_data
            try:
                rc, _complete_tree_verified = self.process_supervisor.finish(
                    proc, max(0.1, min(2.0, deadline - time.monotonic())))
            except ProcessContainmentUnavailable:
                raise ClaudeProviderUnavailable("PROCESS-CLEANUP") from None
            if not seen_init or rc != 0 or not ended:
                raise ClaudeProviderUnavailable("CLI-EXIT")
            successful = True
        except ClaudeProviderUnavailable as exc:
            code = str(exc)
            if code == "STOPPED" or self._stopping.is_set():
                failure = {"code": "STOPPED"}
            elif code.startswith("CONSENT"):
                failure = {"code": "CONSENT-REQUIRED"}
            elif code == "TIMEOUT":
                failure = {"code": "CLI-TIMEOUT"}
            else:
                failure = {"code": "CLI-FAILED"}
        except Exception:
            failure = {"code": "CLI-FAILED"}
        finally:
            if proc is not None:
                try:
                    self._terminate(proc)
                except Exception:
                    failure = {"code": "CLI-FAILED"}
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
                    failure = {"code": "CLI-FAILED"}
                    successful = False
            with self._state_lock:
                self._proc = None
            self._lock.release()
        if failure is not None:
            yield "error", failure
        elif successful:
            yield "done", {}

    def _init_scope_ok(self, obj, expected_tools):
        tools = obj.get("tools")
        servers = obj.get("mcp_servers")
        return (isinstance(tools, list) and set(tools) == set(expected_tools)
                and isinstance(servers, list) and len(servers) == 1
                and servers[0].get("name") == _SERVER_NAME and servers[0].get("status") == "connected"
                and obj.get("permissionMode") == "dontAsk")

    def _terminate(self, proc):
        self.process_supervisor.terminate_tree(proc)

    def stop(self):
        self._stopping.set()
        with self._state_lock:
            proc = self._proc
        if proc is not None:
            self._terminate(proc)

    def close(self):
        self.stop()
        cleanup = getattr(self.launch_context, "cleanup", None)
        if callable(cleanup):
            cleanup()
        unregister = getattr(self.launch_verifier, "unregister", None)
        if callable(unregister):
            unregister(self.launch_context)


class _ServerLaunchContext:
    def __init__(self, authorization, *, cli_path, cli_sha256, bridge, config, tools,
                 env, cwd, runtime_dir, owner):
        self.user_id, self.device_id = authorization.user_id, authorization.device_id
        self.session_id, self.turn_id = authorization.session_id, authorization.turn_id
        self.provider, self.model = authorization.provider, authorization.model
        self.consent_id, self.consent_challenge_id = authorization.grant_id, authorization.consent_challenge_id
        self.consent_expires_at = authorization.expires_at
        self.cli_path, self.cli_sha256 = cli_path, cli_sha256
        self.bridge, self.config, self.tools = bridge, config, tools
        self.env, self.cwd, self.runtime_dir = env, cwd, runtime_dir
        self._owner = owner
        self._cleaned = False
        self._cleanup_lock = threading.Lock()

    def current(self):
        return self.consent_expires_at > time.time()

    def cleanup(self):
        with self._cleanup_lock:
            if self._cleaned:
                return
            self._cleaned = True
        self._owner.cleanup()


class _ServerLaunchVerifier:
    """Concrete server revalidator. It accepts only contexts it minted and refreshes leases every 5s."""

    def __init__(self, client):
        if type(client) is not LaunchAuthorizationClient:
            raise ClaudeProviderUnavailable("launch-authority-required")
        self.client = client
        self._contexts = {}
        self._lock = threading.Lock()
        self._next_check = {}

    @staticmethod
    def _same(left, right):
        return ((left.user_id, left.device_id, left.session_id, left.turn_id, left.provider, left.model,
                 left.grant_id, left.consent_challenge_id, dict(left.tools))
                == (right.user_id, right.device_id, right.session_id, right.turn_id, right.provider, right.model,
                    right.grant_id, right.consent_challenge_id, dict(right.tools)))

    def register(self, context, authorization):
        with self._lock:
            self._contexts[id(context)] = (context, authorization)
            self._next_check[id(context)] = time.monotonic() + 5.0

    def unregister(self, context):
        with self._lock:
            self._contexts.pop(id(context), None)
            self._next_check.pop(id(context), None)

    def __call__(self, context):
        key = id(context)
        with self._lock:
            entry = self._contexts.get(key)
            if entry is None or entry[0] is not context:
                return False
            original = entry[1]
            if not context.current():
                return False
            if time.monotonic() < self._next_check.get(key, 0):
                return True
            try:
                latest = self.client.authorize(AUTH_PATH, context.session_id, context.turn_id,
                                               context.provider, context.model)
            except Exception:
                return False
            if not self._same(original, latest) or latest.expires_at <= time.time():
                return False
            context.consent_expires_at = latest.expires_at
            self._next_check[key] = time.monotonic() + 5.0
            self._contexts[key] = (context, latest)
            return True


class ClaudeProviderFactory:
    """Create a per-turn provider only after a concrete server grant and local runtime pins."""

    name = "claude"

    def __init__(self, authorization_client, *, cli_path, server_url, agent_home, expected_device_id, env=None,
                 temp_parent=None, models=None, popen=subprocess.Popen,
                 process_supervisor=None, timeout=300):
        if type(authorization_client) is not LaunchAuthorizationClient:
            raise ClaudeProviderUnavailable("launch-authority-required")
        if authorization_client.production_transport is not True:
            raise ClaudeProviderUnavailable("launch-transport-untrusted")
        if sys.platform != "darwin":
            raise ClaudeProviderUnavailable("platform")
        if authorization_client.server_origin != server_url.rstrip("/"):
            raise ClaudeProviderUnavailable("server-binding")
        # Pin the resolved file once per process start (see resolve_cli_path).
        cli_path = resolve_cli_path(cli_path)
        cli_sha256 = self._hash(cli_path)
        if not cli_sha256 or not _file_matches_pin(cli_path, cli_sha256):
            raise ClaudeProviderUnavailable("cli-unavailable")
        if not _private_dir(agent_home):
            raise ClaudeProviderUnavailable("agent-home")
        self.authorization_client = authorization_client
        self.cli_path = cli_path
        self.cli_sha256 = cli_sha256
        self.server_url = server_url
        self.agent_home = agent_home
        if not isinstance(expected_device_id, str) or not expected_device_id:
            raise ClaudeProviderUnavailable("device-binding")
        self.expected_device_id = expected_device_id
        self.env = self._clean_env(dict(os.environ if env is None else env))
        self.temp_parent = temp_parent
        self.popen, self.process_supervisor, self.timeout = popen, process_supervisor, timeout
        if models is None:
            # Asked once per agent start, together with the CLI pin: the list changes with the CLI
            # version or the account plan, and both are re-read at the next start. The query costs
            # no model turn. On failure nothing is advertised (never a made-up default).
            models = self._query_models()
        self.models = tuple(models)
        if (not self.models or len(self.models) > MAX_ADVERTISED_MODELS
                or len(set(self.models)) != len(self.models)
                or any(not _valid_model_id(model) for model in self.models)):
            raise ClaudeProviderUnavailable("models-unavailable")
        self.verifier = _ServerLaunchVerifier(authorization_client)
        global _TRUSTED_LAUNCH_VERIFIER
        _TRUSTED_LAUNCH_VERIFIER = self.verifier

    def _query_models(self):
        owner = tempfile.TemporaryDirectory(prefix="chat-claude-models-", dir=self.temp_parent)
        try:
            os.chmod(owner.name, 0o700)
            cwd, runtime = os.path.join(owner.name, "work"), os.path.join(owner.name, "runtime")
            os.mkdir(cwd, 0o700); os.mkdir(runtime, 0o700)
            env = dict(self.env)
            env["TMPDIR"] = runtime
            supervisor = self.process_supervisor or MacOSProcessSupervisor(popen=self.popen)
            return query_cli_models(self.cli_path, env, cwd, supervisor)
        except Exception:
            return ()
        finally:
            owner.cleanup()

    @staticmethod
    def _hash(path):
        try:
            h = hashlib.sha256()
            with open(path, "rb") as f:
                for block in iter(lambda: f.read(64 * 1024), b""):
                    h.update(block)
            return h.hexdigest()
        except OSError:
            return ""

    @staticmethod
    def _clean_env(source):
        env = {k: v for k, v in source.items() if k in _ENV_ALLOW and isinstance(v, str) and "\x00" not in v}
        if "HOME" not in env:
            env["HOME"] = os.path.expanduser("~")
        if "PATH" not in env:
            env["PATH"] = "/usr/bin:/bin"
        return env

    def create_turn(self, session_id, turn_id, authorization_path, provider, model):
        if (authorization_path != AUTH_PATH or provider != self.name or model not in self.models):
            raise ClaudeProviderUnavailable("launch-binding")
        try:
            authorization = self.authorization_client.authorize(authorization_path, session_id, turn_id,
                                                                provider, model)
        except LaunchAuthorizationDenied:
            raise ClaudeProviderUnavailable("launch-denied") from None
        if ((authorization.session_id, authorization.turn_id, authorization.provider, authorization.model)
                != (session_id, turn_id, provider, model) or authorization.expires_at <= time.time()
                or authorization.device_id != self.expected_device_id or not authorization.user_id
                or not authorization.tools):
            raise ClaudeProviderUnavailable("launch-binding")
        tools = {"mcp__my-crm__find": "read"}
        for tier in ("read", "write", "decide", "purge"):
            if any(value == tier for value in authorization.tools.values()):
                tools["mcp__my-crm__" + tier] = tier
        owner = tempfile.TemporaryDirectory(prefix="chat-claude-turn-", dir=self.temp_parent)
        context = None
        try:
            root = owner.name
            os.chmod(root, 0o700)
            cwd, runtime_dir = os.path.join(root, "work"), os.path.join(root, "runtime")
            os.mkdir(cwd, 0o700); os.mkdir(runtime_dir, 0o700)
            pyexe = os.path.realpath(sys.executable)
            pyhash = self._hash(pyexe)
            frozen = bool(getattr(sys, "frozen", False))
            module_path = None if frozen else os.path.realpath(os.path.join(os.path.dirname(__file__), "chat_mcp_bridge.py"))
            module_hash = None if frozen else self._hash(module_path)
            if not pyhash or (not frozen and not module_hash):
                raise ClaudeProviderUnavailable("bridge-pin")
            bridge_args = (("chat-mcp-bridge",) if frozen else ("-m", "agent.chat_mcp_bridge")) + ("--agent-home", self.agent_home,
                           "--session-id", session_id, "--turn-id", turn_id, "--device-id", authorization.device_id,
                           "--provider", provider,
                           "--model", model, "--authorization-path", authorization_path)
            bridge = PinnedBridgeDescriptor(pyexe, bridge_args, pyhash, module_path, module_hash)
            config = {"mcpServers": {"my-crm": {"command": pyexe, "args": list(bridge_args)}}}
            turn_env = dict(self.env)
            turn_env["TMPDIR"] = runtime_dir
            context = _ServerLaunchContext(authorization, cli_path=self.cli_path, cli_sha256=self.cli_sha256,
                bridge=bridge, config=config, tools=tools, env=turn_env, cwd=cwd, runtime_dir=runtime_dir, owner=owner)
            self.verifier.register(context, authorization)
            return ClaudeProvider(cli_path=self.cli_path, model=model, launch_context=context,
                launch_verifier=self.verifier, popen=self.popen, process_supervisor=self.process_supervisor,
                timeout=self.timeout)
        except Exception:
            if context is not None:
                self.verifier.unregister(context)
            owner.cleanup()
            raise
