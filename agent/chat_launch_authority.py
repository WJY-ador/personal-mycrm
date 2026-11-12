"""Fail-closed HTTP client for server-minted, per-turn provider launch grants.

This module validates the transport contract only. It does not mint Claude launch
contexts or enable a provider; that also requires an app-pinned MyCRM bridge and
the server route/gateway readiness gates.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType


AUTH_PATH = "/api/chat/launch-authorization"
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_TOOL = re.compile(r"^mcp__my-crm__[a-z][a-z0-9_]{0,63}$")
_TIERS = frozenset(("read", "write", "decide", "purge"))


class LaunchAuthorizationDenied(RuntimeError):
    """Generic denial; never include response bodies, tokens, or URLs in the message."""


@dataclass(frozen=True)
class LaunchAuthorization:
    user_id: str
    device_id: str
    session_id: str
    turn_id: str
    provider: str
    model: str
    grant_id: str
    consent_challenge_id: str
    expires_at: float
    tools: dict[str, str]


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LaunchAuthorizationClient:
    """Request/revalidate a turn grant using only HTTPS and the device bearer."""

    def __init__(self, server_url: str, token_fn, *, timeout: float = 5.0, opener=None):
        try:
            parsed = urllib.parse.urlsplit(server_url)
        except Exception:
            raise LaunchAuthorizationDenied("launch authorization denied") from None
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ("", "/")
                or not callable(token_fn) or not isinstance(timeout, (int, float)) or timeout <= 0):
            raise LaunchAuthorizationDenied("launch authorization denied")
        self._origin = f"https://{parsed.netloc}"
        self.server_origin = self._origin
        self._token_fn = token_fn
        self._timeout = float(timeout)
        self._production_transport = opener is None
        self._opener = opener or urllib.request.build_opener(_NoRedirect())

    @property
    def production_transport(self):
        return self._production_transport

    def authorize(self, path: str, session_id: str, turn_id: str, provider: str, model: str) -> LaunchAuthorization:
        if (path != AUTH_PATH or not _ID.fullmatch(session_id or "") or not _ID.fullmatch(turn_id or "")
                or provider not in ("claude", "codex") or not isinstance(model, str)
                or not model or len(model) > 120 or "\x00" in model):
            raise LaunchAuthorizationDenied("launch authorization denied")
        try:
            raw = self._post(AUTH_PATH, {"session_id": session_id, "turn_id": turn_id})
            return self._parse(raw, session_id, turn_id, provider, model)
        except Exception:
            raise LaunchAuthorizationDenied("launch authorization denied") from None

    def call_mcp(self, authorization: LaunchAuthorization, tool: str, params: dict, *, op=None, bind=""):
        """Post one facade call, bound to the session/turn from the checked grant."""
        try:
            if (type(authorization) is not LaunchAuthorization or authorization.expires_at <= time.time()
                    or tool not in ("find", "read", "write", "decide", "purge") or not isinstance(params, dict)
                    or any(key in params for key in ("uid", "user_id", "device_id", "session_id", "turn_id", "bind"))):
                raise ValueError("scope")
            body = {"session_id": authorization.session_id, "turn_id": authorization.turn_id,
                    "tool": tool, "params": params}
            if tool == "find":
                if authorization.tools.get("mcp__my-crm__find") != "read" or op is not None or bind:
                    raise ValueError("find")
                if set(params) - {"query", "family", "op"}:
                    raise ValueError("find-params")
            else:
                if (not isinstance(op, str) or not _TOOL.fullmatch("mcp__my-crm__" + op)
                        or authorization.tools.get("mcp__my-crm__" + op) != tool):
                    raise ValueError("operation")
                body["op"] = op
                if tool in ("decide", "purge"):
                    if not isinstance(bind, str) or len(bind) > 128:
                        raise ValueError("bind")
                    if bind:
                        body["bind"] = bind
                elif bind:
                    raise ValueError("bind")
            raw = self._post("/api/chat/mcp", body)
            wrapper = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
            if not isinstance(wrapper, dict) or set(wrapper) != {"result"}:
                raise ValueError("response")
            return wrapper["result"]
        except Exception:
            raise LaunchAuthorizationDenied("MyCRM tool call denied") from None

    def _post(self, path, payload):
        if path not in (AUTH_PATH, "/api/chat/mcp"):
            raise ValueError("path")
        token = self._token_fn()
        if not isinstance(token, str) or not token or len(token) > 4096 or "\r" in token or "\n" in token:
            raise ValueError("token")
        body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(self._origin + path, data=body, method="POST", headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": "application/json",
        })
        with self._opener.open(req, timeout=self._timeout) as response:
            if response.status != 200:
                raise ValueError("status")
            raw = response.read(32 * 1024 + 1)
        if len(raw) > 32 * 1024:
            raise ValueError("size")
        return raw

    @staticmethod
    def _parse(raw, session_id, turn_id, provider, model):
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
        if not isinstance(data, dict) or set(data) != {"authorized", "binding", "tools"} or data["authorized"] is not True:
            raise ValueError("response")
        binding = data["binding"]
        required = {"user_id", "device_id", "session_id", "turn_id", "provider", "model",
                    "grant_id", "consent_challenge_id", "expires_at"}
        if not isinstance(binding, dict) or set(binding) != required:
            raise ValueError("binding")
        for key in ("user_id", "device_id", "session_id", "turn_id", "provider", "model", "grant_id", "consent_challenge_id"):
            if not isinstance(binding[key], str) or not binding[key] or len(binding[key]) > 128:
                raise ValueError("binding-value")
        if ((binding["session_id"], binding["turn_id"], binding["provider"], binding["model"])
                != (session_id, turn_id, provider, model)):
            raise ValueError("binding-mismatch")
        expiry = binding["expires_at"]
        if not isinstance(expiry, str) or not expiry.endswith("Z"):
            raise ValueError("expiry")
        expires = datetime.fromisoformat(expiry[:-1] + "+00:00")
        now = datetime.now(timezone.utc)
        if expires.tzinfo is None or expires <= now or expires.timestamp() > now.timestamp() + 16:
            raise ValueError("expiry")
        tools = data["tools"]
        if not isinstance(tools, dict) or not tools or len(tools) > 256:
            raise ValueError("tools")
        for name, tier in tools.items():
            tail = name.removeprefix("mcp__my-crm__") if isinstance(name, str) else ""
            # AI 하나로 A3: trash_purge may appear only on the purge tier (a server card path); never as a tool named purge.
            if (not isinstance(name, str) or not _TOOL.fullmatch(name) or tail == "purge"
                    or tier not in _TIERS or (tier == "purge") != (tail == "trash_purge")):
                raise ValueError("tools")
        return LaunchAuthorization(
            user_id=binding["user_id"], device_id=binding["device_id"], session_id=session_id,
            turn_id=turn_id, provider=provider, model=model, grant_id=binding["grant_id"],
            consent_challenge_id=binding["consent_challenge_id"], expires_at=expires.timestamp(),
            tools=MappingProxyType(dict(tools)),
        )
