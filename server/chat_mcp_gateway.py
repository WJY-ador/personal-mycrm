"""Authenticated-context adapter for the existing MyCRM facade.

This is an integration seam, not an HTTP/MCP route. The caller must obtain the
principal from request authentication and session/consent from server-owned
state on every call. There is intentionally no credential or consent bootstrap
here. Until those sources exist, no caller can construct useful validated
state. The adapter never accepts model-supplied identity or arbitrary callbacks.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from chat_mcp import (
    allowed_operations,
    call_existing,
    filter_tool_names,
    find_existing,
)

_TRUST = object()
# Scope reconstruction and dispatch share one transaction. 2026-11-12 K: 원작자 실사용, 독립 검토 I와 J 반영 뒤 켬, Codex는 꺼짐.
# The route still needs CRM_WEBCHAT_ENABLED and CRM_CHAT_MCP_ENABLED (env, default off).
ATOMIC_DISPATCH_READY = True


def route_enabled(webchat_on: bool, gateway_on: bool) -> bool:
    return ATOMIC_DISPATCH_READY and webchat_on and gateway_on


class TrustedChatPrincipal:
    """Server-minted identity for one already-validated HTTP chat request."""
    __slots__ = ("user_id", "device_id", "session_id", "provider", "model", "expires_at", "_seal")

    def __init__(self, seal, *, user_id, device_id, session_id, provider, model, expires_at):
        if seal is not _TRUST:
            raise TypeError("trusted principal must be minted by the chat gateway")
        for key, value in (("user_id", user_id), ("device_id", device_id), ("session_id", session_id),
                           ("provider", provider), ("model", model), ("expires_at", expires_at), ("_seal", seal)):
            object.__setattr__(self, key, value)

    def __setattr__(self, _name, _value):
        raise AttributeError("trusted principal is immutable")


def _mint_trusted_principal(*, user_id, device_id, session_id, provider, model, expires_at):
    """Internal route seam. Call only after a transaction validates live DB bindings."""
    return TrustedChatPrincipal(_TRUST, user_id=user_id, device_id=device_id, session_id=session_id,
                                provider=provider, model=model, expires_at=expires_at)


def trusted_principal_uid(value):
    if (type(value) is TrustedChatPrincipal and value._seal is _TRUST
            and isinstance(value.expires_at, datetime) and datetime.now(timezone.utc) < value.expires_at):
        return value.user_id
    return None


def _facade():
    # Delay application imports so pure validation and synthetic tests do not
    # load the database/HTTP stack.
    import facade
    return facade


class ChatMcpGateway:
    """Call facade functions only after scope and Context identity validation."""

    def __init__(self, *, principal, session, consent, context, catalog):
        self._principal = principal
        self._session = session
        self._consent = consent
        self._context = context
        self._catalog = catalog
        # Fail construction closed. Every method repeats validation because the
        # adapter may outlive or cross an authentication/session boundary.
        self._validate_context()
        allowed_operations(catalog)

    def _validate_context(self) -> None:
        from chat_mcp import validate_scope

        scope = validate_scope(self._principal, self._session, self._consent,
                               datetime.now(timezone.utc))
        try:
            context_uid = _facade().uid_of(self._context)
        except Exception:
            raise RuntimeError("chat MCP context denied") from None
        if context_uid != scope.user_id:
            raise RuntimeError("chat MCP context denied")

    def tools(self, requested):
        self._validate_context()
        return filter_tool_names(requested)

    def find(self, *, query="", family="", op=""):
        self._validate_context()
        return find_existing(
            self._principal, self._session, self._consent,
            catalog=self._catalog, now=datetime.now(timezone.utc),
            find_callback=_facade().find, query=query, family=family, op=op,
        )

    def call(self, surface: str, op: str, params: Any = None, bind: str = ""):
        self._validate_context()
        return call_existing(
            self._principal, self._session, self._consent,
            surface, op, params, bind,
            catalog=self._catalog, now=datetime.now(timezone.utc),
            dispatch_existing=lambda tier, name, args, token: _facade().dispatch_trusted(
                tier, name, args, self._context, token
            ),
        )

    @staticmethod
    def call_trusted(principal: TrustedChatPrincipal, surface: str, op: str,
                     params: Any = None, bind: str = ""):
        """Explicit trusted-principal path; facade still runs the registered guarded op."""
        if trusted_principal_uid(principal) is None:
            raise RuntimeError("chat MCP principal denied")
        if datetime.now(timezone.utc) >= principal.expires_at:
            raise RuntimeError("chat MCP principal expired")
        allowed = allowed_operations(_facade().load_catalog())
        from chat_mcp import validate_call
        validate_call(surface, op, params, allowed)
        return _facade().dispatch_trusted(surface, op, params or {}, principal, bind)
