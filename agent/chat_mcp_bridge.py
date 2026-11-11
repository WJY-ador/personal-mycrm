"""Narrow stdio MCP bridge for the authenticated per-turn MyCRM HTTP facade.

Only the four facade surfaces are model-visible. Authorization and every tool
call are checked by the HTTPS client and server; no bearer is placed in argv,
environment, MCP output, or diagnostics.
"""
from __future__ import annotations

import json
import argparse
import os
import re
import stat
import sys
from collections import defaultdict

from .chat_launch_authority import AUTH_PATH, LaunchAuthorizationDenied


SERVER_NAME = "my-crm"
TOOL_PREFIX = "mcp__my-crm__"
SURFACES = ("find", "read", "write", "decide")
# Claude Code namespaces MCP tools as mcp__<server>__<name> itself (CLI 2.1.322 probe, 2026-11-10):
# a server-side name that already carries the prefix becomes mcp__my-crm__mcp__my-crm__find, which
# never matches the adapter's --allowedTools or its init check. Claude therefore gets bare names.
# Codex keeps the prefixed names its enabled_tools config expects (agent/chat_codex.py); that
# naming has not been probed against a real Codex CLI yet.
_PROVIDER_TOOL_PREFIX = {"claude": "", "codex": TOOL_PREFIX}
JSONRPC_METHOD_NOT_FOUND = -32601
FAMILIES = ("state", "question", "record", "candidate", "definition", "person", "source",
            "activity", "inbox", "trash", "desk", "migration", "pc")
MAX_LINE_BYTES = 256 * 1024
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate")
        out[key] = value
    return out


def _private_home(path):
    try:
        st = os.lstat(path)
        return (os.path.isabs(path) and stat.S_ISDIR(st.st_mode) and not stat.S_ISLNK(st.st_mode)
                and st.st_mode & 0o077 == 0 and (not hasattr(os, "getuid") or st.st_uid == os.getuid()))
    except OSError:
        return False


def surface_schemas(operations, name_prefix=TOOL_PREFIX):
    """Build the same public facade surface as server/main.py, scoped by the grant.

    `operations` keys are always the grant's prefixed names; `name_prefix` only sets the
    MCP-visible tool names (bare for Claude Code, prefixed for Codex).
    """
    if name_prefix not in _PROVIDER_TOOL_PREFIX.values():
        raise ValueError("tool-prefix")
    by_tier = defaultdict(list)
    for full_name, tier in operations.items():
        if not isinstance(full_name, str) or not full_name.startswith(TOOL_PREFIX):
            raise ValueError("tool-name")
        op = full_name[len(TOOL_PREFIX):]
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", op) or tier not in ("read", "write", "decide"):
            raise ValueError("tool-scope")
        if op != "find":
            by_tier[tier].append(op)
    out = []
    # `find` only describes non-purge operations; server/chat_mcp filters its result.
    out.append({"name": name_prefix + "find", "description": (
                    "이 서버의 할 일(op)을 찾는다. 인자 없음 = 묶음 목록, query = 말로 찾기(최대 8), "
                    "op = 그 op 의 설명·input_schema·examples·rule. 찾은 op 은 등급 도구(read·write·decide·purge)로 부른다. "
                    "확정·삭제는 decide_preview → decide/purge."),
            "annotations": {"readOnlyHint": True},
                "inputSchema": {"type": "object", "properties": {
                    "query": {"type": "string", "description": "찾을 말(사용자 표현 그대로도 된다). 부분 일치", "default": ""},
                    "family": {"type": "string", "description": "이 묶음만 (선택)",
                               "enum": ["", *FAMILIES], "default": ""},
                    "op": {"type": "string", "description": "이 op 의 설명·입력 스키마·예시·규칙 (선택)", "default": ""}},
                    "additionalProperties": False}})
    descriptions = {
        "read": "읽기 op 을 부른다(아무것도 바꾸지 않는다). op 목록은 enum, 인자는 find(op=…). "
                "확정·삭제 전 미리보기는 op=\"decide_preview\", params={op, params}.",
        "write": "사용자 말을 그대로 저장하거나 제안(draft)만 남기는 op 을 부른다. 다듬거나 추정으로 채우지 않는다. "
                 "op 목록은 enum, 인자는 find(op=…). "
                 "쓰기는 사용자가 카드로 확인한 뒤 실행된다. pending_confirmation은 완료가 아니다. "
                 "이어지는 쓰기는 다음 턴에 created id로 한다.",
        "decide": "확정·변경·휴지통 이동/복원·보관·밖으로 보내기 op 을 부른다. op 목록은 enum, 인자는 find(op=…) 로 본다. "
                  "먼저 read(op=\"decide_preview\", params={op, params}) 로 bind 를 받는다. "
                  "공통: decide_preview 의 shown 을 고치지 않고 그대로 사용자에게 보여 주고, 사용자가 말한 뒤에만 부른다.",
    }
    for tier in ("read", "write", "decide"):
        ops = sorted(by_tier[tier])
        if not ops:
            continue
        props = {"op": {"type": "string", "description": f"{tier} 등급 op 이름(지금 도구 이름 그대로)", "enum": ops},
                 "params": {"anyOf": [{"type": "object", "additionalProperties": True}, {"type": "null"}],
                            "description": "op 인자 객체 — 모양은 find(op=…) 의 input_schema·examples", "default": None}}
        required = ["op"]
        if tier == "decide":
            props["bind"] = {"type": "string", "description": "read(op=\"decide_preview\") 가 준 bind. 없거나 낡으면 거절된다", "default": ""}
        tool = {"name": name_prefix + tier, "description": descriptions[tier],
                "inputSchema": {"type": "object", "properties": props, "required": required,
                                "additionalProperties": False}}
        if tier == "read":
            tool["annotations"] = {"readOnlyHint": True}
        out.append(tool)
    return out


class McpStdioBridge:
    """Translate MCP JSON-RPC over stdio into strict per-turn HTTPS facade calls."""

    def __init__(self, authorization_client, authorization_path: str, session_id: str,
                 turn_id: str, provider: str, model: str, expected_device_id: str):
        if (authorization_path != AUTH_PATH or not _ID.fullmatch(session_id or "")
                or not _ID.fullmatch(turn_id or "") or provider not in ("claude", "codex")
                or not isinstance(model, str) or not model or len(model) > 120
                or not isinstance(expected_device_id, str) or not expected_device_id):
            raise ValueError("bridge-binding")
        if not callable(getattr(authorization_client, "authorize", None)) or not callable(
                getattr(authorization_client, "call_mcp", None)):
            raise ValueError("bridge-client")
        self.client = authorization_client
        self.authorization_path, self.session_id, self.turn_id = authorization_path, session_id, turn_id
        self.provider, self.model = provider, model
        self.expected_device_id = expected_device_id
        self.name_prefix = _PROVIDER_TOOL_PREFIX[provider]
        self._anchor = None

    def _authorization(self):
        authorization = self.client.authorize(self.authorization_path, self.session_id, self.turn_id,
                                              self.provider, self.model)
        if authorization.device_id != self.expected_device_id or not authorization.user_id:
            raise ValueError("authorization-binding")
        anchor = (authorization.user_id, authorization.device_id, authorization.session_id, authorization.turn_id,
                  authorization.provider, authorization.model, authorization.grant_id,
                  authorization.consent_challenge_id, dict(authorization.tools))
        if self._anchor is None:
            self._anchor = anchor
        elif self._anchor != anchor:
            raise ValueError("authorization-changed")
        return authorization

    def handle_line(self, line: str):
        if not isinstance(line, str) or len(line.encode("utf-8", "replace")) > MAX_LINE_BYTES:
            return None
        try:
            message = json.loads(line, object_pairs_hook=_pairs,
                                 parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("constant")))
        except (TypeError, ValueError, UnicodeError, RecursionError):
            return None
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            return None
        method = message.get("method")
        request_id = message.get("id")
        if method == "notifications/initialized" and "id" not in message:
            return None
        if request_id is None:
            return None  # notifications never get a reply
        if method not in ("initialize", "ping", "tools/list", "tools/call"):
            # Claude Code 2.1.322 opens with `server/discover`; without an answer it waits ~3 s
            # before falling back to `initialize`. Answer every unknown request at once.
            if type(request_id) not in (str, int) or isinstance(request_id, bool):
                return None
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": JSONRPC_METHOD_NOT_FOUND, "message": "Method not found"}}
            return json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        try:
            params = message.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("params")
            if method == "initialize":
                result = {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                          "serverInfo": {"name": SERVER_NAME, "version": "1"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                auth = self._authorization()
                result = {"tools": surface_schemas(auth.tools, self.name_prefix)}
            else:
                result = self._call_tool(params)
            response = {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception:
            response = {"jsonrpc": "2.0", "id": request_id,
                        "error": {"code": -32000, "message": "MyCRM tool call denied"}}
        encoded = json.dumps(response, ensure_ascii=False, separators=(",", ":"))
        return encoded if len(encoded.encode("utf-8")) <= MAX_LINE_BYTES else None

    def _call_tool(self, params):
        # Claude Code 2.1.322 adds MCP `_meta` (toolUseId, progressToken) to every tools/call.
        # It is accepted only as an object and never forwarded.
        if not {"name", "arguments"} <= set(params) <= {"name", "arguments", "_meta"}:
            raise ValueError("call-shape")
        if "_meta" in params and not isinstance(params["_meta"], dict):
            raise ValueError("call-shape")
        name, args = params["name"], params["arguments"]
        # Only the exact name form this provider was given in tools/list is accepted.
        if (not isinstance(name, str) or not isinstance(args, dict)
                or name not in {self.name_prefix + surface for surface in SURFACES}):
            raise ValueError("call-shape")
        auth = self._authorization()  # Fresh server grant check before each tool dispatch.
        tail = name[len(self.name_prefix):]
        if tail == "find":
            if auth.tools.get(TOOL_PREFIX + "find") != "read":
                raise ValueError("find-scope")
            if set(args) - {"query", "family", "op"} or any(
                    type(args.get(key, "")) is not str or len(args.get(key, "")) > 1200
                    for key in ("query", "family", "op")):
                raise ValueError("find-args")
            result = self.client.call_mcp(auth, "find", args)
        elif tail in SURFACES:
            tier = tail
            allowed = {n[len(TOOL_PREFIX):] for n, value in auth.tools.items() if value == tier}
            if set(args) - {"op", "params", "bind"} or args.get("op") not in allowed:
                raise ValueError("operation")
            params_value = args.get("params")
            if params_value is not None and not isinstance(params_value, dict):
                raise ValueError("operation-params")
            bind = args.get("bind", "")
            if (tier == "decide" and (not isinstance(bind, str) or len(bind) > 128)
                    or tier != "decide" and "bind" in args):
                raise ValueError("bind")
            result = self.client.call_mcp(auth, tier, params_value or {}, op=args["op"], bind=bind)
        else:
            raise ValueError("tool")
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":"), default=str)
        return {"content": [{"type": "text", "text": content}], "isError": False}


def _parser():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--agent-home", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--device-id", required=True)
    parser.add_argument("--provider", required=True, choices=("claude", "codex"))
    parser.add_argument("--model", required=True)
    parser.add_argument("--authorization-path", required=True)
    return parser


def main(argv=None, *, home=None, keystore_factory=None, opener=None, stdin=None, stdout=None):
    """stdio entry point. It loads only agent config and device token from OS keystore."""
    from . import config, keystore
    args = _parser().parse_args(argv)
    try:
        paths = config.Paths(home or args.agent_home)
        if not _private_home(paths.home):
            return 1
        cfg = config.load(paths)
        server_url = cfg.get("server_url")
        source_id = cfg.get("source_instance_id")
        service = cfg.get("keychain_service")
        if not isinstance(server_url, str) or not isinstance(source_id, str) or not source_id:
            return 1
        store = (keystore_factory or keystore.for_platform)(service)
        token_fn = lambda: store.get(config.token_account(source_id))
        from .chat_launch_authority import LaunchAuthorizationClient
        client = LaunchAuthorizationClient(server_url, token_fn, opener=opener)
        bridge = McpStdioBridge(client, args.authorization_path, args.session_id, args.turn_id,
                                args.provider, args.model, args.device_id)
        source = stdin or sys.stdin
        sink = stdout or sys.stdout
        while True:
            line = source.readline(MAX_LINE_BYTES + 2)
            if not line:
                return 0
            if len(line.encode("utf-8", "replace")) > MAX_LINE_BYTES + 1:
                return 1
            result = bridge.handle_line(line.rstrip("\r\n"))
            if result is not None:
                sink.write(result + "\n")
                sink.flush()
    except Exception:
        # No exception, URL, token, tool output or config value on stderr/stdout.
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
