"""Fail-closed filters for a future session-scoped chat MCP adapter.

This module is deliberately not wired into a server route. A route must build
AuthenticatedPrincipal from imports.authenticate(), load SessionBinding and
ConsentBinding from server-owned state on every call, and pass the original
facade dispatch/find functions bound to the authenticated Context. It must
fail closed until a real consent record exists. Never construct principals or
bindings from model arguments, and never pass tokens to the model/provider.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from collections.abc import Mapping
from typing import Any, Callable


class ChatMcpDenied(ValueError):
    """Generic denial; callers should not return binding details to the model."""

    code = "CHAT-MCP-DENIED"


# Pinned against server/mcp_catalog.json v1. A catalog change requires an
# explicit review and coordinated update here plus the exact-set test below.
_PINNED_TIERS = {
    "state_get": "read", "help_get": "read", "me_get": "read", "me_aggregate_get": "read",
    "layout_get": "read", "export_get": "read", "decide_preview": "read", "question_list": "read", "answer_get": "read", "record_get": "read",
    "candidate_list": "read", "definitions_get": "read", "person_list": "read", "person_get": "read",
    "person_context_get": "read", "source_list": "read", "source_get": "read", "source_context_get": "read",
    "source_reflection_list": "read", "source_reflection_get": "read", "activity_list": "read",
    "activity_get": "read", "inbox_list": "read", "inbox_get": "read", "trash_list": "read",
    "ticket_list_mine": "read", "ticket_get_mine": "read", "migration_receipt_get": "read",
    "migration_list": "read", "migration_get": "read", "migration_item_get": "read",
    "migration_apply_preview": "read", "pc_list": "read", "token_grant_status": "read", "token_list": "read",
    "layout_set": "write", "layout_reset": "write", "display_name_set": "write", "question_add": "write",
    "profile_set": "write", "record_add": "write", "record_attach": "write", "record_title_set": "write",
    "candidates_propose": "write", "definition_propose": "write", "item_propose": "write",
    "person_save": "write", "source_create": "write", "source_reflection_save": "write", "pc_connect": "write",
    "collected_post_decide": "write",
    "record_edit": "decide", "record_provenance_set": "decide", "candidate_decide": "decide",
    "definition_apply": "decide", "definition_archive": "decide", "definition_restore": "decide",
    "item_decide": "decide", "person_delete": "decide", "source_reflection_review": "decide",
    "source_reflection_delete": "decide", "inbox_decide": "decide", "trash_move": "decide",
    "trash_restore": "decide", "feedback_send": "decide", "migration_apply": "decide",
    "migration_cancel": "decide", "migration_revert": "decide", "migration_token_send": "decide",
    "pc_forget": "decide", "token_revoke": "decide", "trash_purge": "purge",
}
# AI 하나로 A3(2026-11-12): purge(trash_purge)도 대화 도구 목록에 든다. 실행은 decide 와 같이 확인 카드로만 한다(validate_call 이 바로 실행을 막는다)
_ALLOWED_OPS = frozenset((tier, name) for name, tier in _PINNED_TIERS.items())
CHAT_TOOL_NAMES = ("find", "read", "write", "decide", "purge")
_TOOL_NAME_SET = frozenset(CHAT_TOOL_NAMES)
_TIERS = frozenset(("read", "write", "decide", "purge"))


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Identity produced by the server auth layer, never by model arguments."""

    user_id: str
    device_id: str


@dataclass(frozen=True)
class SessionBinding:
    """Current session row, loaded by the server using its authenticated principal."""

    user_id: str
    device_id: str
    session_id: str
    provider: str
    model: str | None
    status: str
    grant_session_id: str | None = None


@dataclass(frozen=True)
class ConsentBinding:
    """Server-owned, one-session local consent state; absent state means denial."""

    user_id: str
    device_id: str
    session_id: str
    provider: str
    model: str | None
    consented_at: datetime | None
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True)
class ValidatedScope:
    """Non-secret scope returned by validate_scope().

    call_existing()/find_existing() do not forward it to their callbacks, so
    this module cannot prove the callback acts for this principal. The route
    must bind each callback to a Context whose uid_of(ctx) equals
    principal.user_id for the same authenticated request/device.
    """

    user_id: str
    device_id: str
    session_id: str
    provider: str
    model: str | None


def _deny() -> ChatMcpDenied:
    return ChatMcpDenied("chat MCP scope or operation denied")


def filter_tool_names(names) -> tuple[str, ...]:
    """Expose only the five MyCRM facade surfaces; all direct/other tools vanish."""
    if isinstance(names, (str, bytes)):
        raise _deny()
    try:
        requested = set(names)
    except (TypeError, ValueError):
        raise _deny() from None
    if any(not isinstance(n, str) for n in requested):
        raise _deny()
    return tuple(name for name in CHAT_TOOL_NAMES if name in requested)


def _pairs_no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _deny()
        out[key] = value
    return out


def _catalog_object(catalog):
    if isinstance(catalog, bytes):
        try:
            catalog = catalog.decode("utf-8")
        except UnicodeDecodeError:
            raise _deny() from None
    if isinstance(catalog, str):
        try:
            catalog = json.loads(catalog, object_pairs_hook=_pairs_no_duplicates)
        except (ValueError, TypeError):
            raise _deny() from None
    if not isinstance(catalog, Mapping):
        raise _deny()
    return catalog


def allowed_operations(catalog) -> frozenset[tuple[str, str]]:
    """Return the pinned read/write/decide/purge set only if catalog v1 matches exactly.

    `catalog` may be raw JSON text/bytes so duplicate JSON keys are detectable.
    Mapping callers must load trusted repository data without duplicate keys.
    Unknown, missing, extra, or retiered operations deny the entire gateway.
    """
    catalog = _catalog_object(catalog)
    if type(catalog.get("version")) is not int or catalog.get("version") != 1:
        raise _deny()
    ops = catalog.get("ops")
    if not isinstance(ops, Mapping) or set(ops) != set(_PINNED_TIERS):
        raise _deny()
    for name, tier in _PINNED_TIERS.items():
        spec = ops.get(name)
        if not isinstance(spec, Mapping) or spec.get("tier") != tier:
            raise _deny()
    return _ALLOWED_OPS


def _check_allowed_ops(allowed_ops):
    if allowed_ops != _ALLOWED_OPS:
        raise _deny()


def _utc(value):
    """Convert an aware timestamp to UTC; malformed/custom tzinfo fails closed."""
    if not isinstance(value, datetime):
        return None
    try:
        if value.utcoffset() is None:
            return None
        return value.astimezone(timezone.utc)
    except Exception:
        return None


def validate_scope(principal, session, consent, now) -> ValidatedScope:
    """Require an authenticated identity and matching active, consented session grant.

    `principal` must come from the server authentication handler. `session` and
    `consent` must be loaded from authoritative server state on every call.
    This helper cannot authenticate an HTTP request or create consent itself.
    """
    if type(principal) is not AuthenticatedPrincipal or type(session) is not SessionBinding or type(consent) is not ConsentBinding:
        raise _deny()
    now_utc = _utc(now)
    expires_utc = _utc(consent.expires_at)
    consented_utc = _utc(consent.consented_at)
    if now_utc is None or expires_utc is None or consented_utc is None:
        raise _deny()
    if not all(isinstance(v, str) and v and len(v) <= 128 for v in (
            principal.user_id, principal.device_id, session.user_id, session.device_id,
            session.session_id, session.provider, consent.user_id, consent.device_id,
            consent.session_id, consent.provider)):
        raise _deny()
    if session.model is not None and (not isinstance(session.model, str) or not session.model or len(session.model) > 120):
        raise _deny()
    if consent.model is not None and (not isinstance(consent.model, str) or not consent.model or len(consent.model) > 120):
        raise _deny()
    if session.provider not in ("claude", "codex"):
        raise _deny()
    if session.status != "active" or consent.consented_at is None:
        raise _deny()
    if consent.revoked_at is not None or expires_utc <= now_utc or consented_utc > now_utc:
        raise _deny()
    grant_session_id = session.grant_session_id or session.session_id
    if not isinstance(grant_session_id, str) or not grant_session_id or len(grant_session_id) > 128:
        raise _deny()
    session_binding = (session.user_id, session.device_id, session.provider, session.model)
    consent_binding = (consent.user_id, consent.device_id, consent.session_id, consent.provider, consent.model)
    if ((principal.user_id, principal.device_id) != (session.user_id, session.device_id)
            or session_binding != (consent.user_id, consent.device_id, consent.provider, consent.model)
            or consent.session_id != grant_session_id):
        raise _deny()
    return ValidatedScope(session.user_id, session.device_id, session.session_id, session.provider, session.model)


def validate_call(surface: str, op: str, params, allowed_ops) -> None:
    """Validate a facade call before invoking the existing guarded dispatcher."""
    _check_allowed_ops(allowed_ops)
    if surface not in ("read", "write", "decide", "purge") or not isinstance(op, str):
        raise _deny()
    if (surface, op) not in _ALLOWED_OPS:
        raise _deny()
    # A facade bind proves that the model obtained a preview, not that a
    # human saw or approved it. decide and purge run only from a server-owned
    # confirmation card (webchat.approval_confirm calls facade.dispatch itself),
    # so the agent never executes them here, nor initiates PC pairing.
    if surface in ("decide", "purge") or op == "pc_connect":
        raise _deny()
    if params is None:
        params = {}
    if not isinstance(params, Mapping) or "uid" in params or "user_id" in params or "bind" in params:
        raise _deny()
    if op == "decide_preview":
        target, nested = params.get("op"), params.get("params")
        if not isinstance(target, str) or not isinstance(nested, Mapping) or ("bind" in nested or "uid" in nested or "user_id" in nested):
            raise _deny()
        if not any(tier in ("decide", "purge") and name == target for tier, name in _ALLOWED_OPS):
            raise _deny()


def _scrub_preview_schema(schema):
    """find(op="decide_preview") lists every D∪P target in its op enum; keep allowlisted decide/purge ops only."""
    if not isinstance(schema, Mapping) or not isinstance(schema.get("properties"), Mapping):
        raise _deny()
    props = dict(schema["properties"])
    op_prop = props.get("op")
    if not isinstance(op_prop, Mapping):
        raise _deny()
    op_prop = dict(op_prop)
    if "enum" in op_prop:
        enum = op_prop["enum"]
        if not isinstance(enum, list) or any(not isinstance(name, str) for name in enum):
            raise _deny()
        op_prop["enum"] = [name for name in enum if ("decide", name) in _ALLOWED_OPS or ("purge", name) in _ALLOWED_OPS]
    props["op"] = op_prop
    return {**schema, "properties": props}


def filter_find_result(result, allowed_ops) -> dict:
    """Sanitize known facade.find response shapes, failing closed on unknown shape."""
    _check_allowed_ops(allowed_ops)
    if not isinstance(result, Mapping):
        raise _deny()
    out = dict(result)
    if "families" in out:
        families = out["families"]
        if not isinstance(families, list):
            raise _deny()
        filtered = []
        for family in families:
            if not isinstance(family, Mapping) or not isinstance(family.get("ops_by_tier"), Mapping):
                raise _deny()
            item = dict(family)
            tiers = family["ops_by_tier"]
            item["ops_by_tier"] = {tier: list(names) for tier, names in tiers.items()
                                    if tier in ("read", "write", "decide", "purge") and isinstance(names, list)}
            if any(tier in _TIERS and not isinstance(names, list) for tier, names in tiers.items()):
                raise _deny()
            for tier, names in item["ops_by_tier"].items():
                if any(not isinstance(name, str) or (tier, name) not in _ALLOWED_OPS for name in names):
                    raise _deny()
            filtered.append(item)
        out["families"] = filtered
        return out
    if "op" in out:
        if (not isinstance(out.get("tier"), str) or not isinstance(out.get("op"), str)
                or (out["tier"], out["op"]) not in _ALLOWED_OPS):
            raise _deny()
        if out["op"] == "decide_preview":
            out["input_schema"] = _scrub_preview_schema(out.get("input_schema"))
        return out
    for key in ("ops", "matches"):
        if key in out:
            entries = out[key]
            if not isinstance(entries, list):
                raise _deny()
            kept = []
            for entry in entries:
                if not isinstance(entry, Mapping):
                    raise _deny()
                tier, name = entry.get("tier"), entry.get("op")
                if not isinstance(tier, str) or not isinstance(name, str):
                    raise _deny()
                if (tier, name) in _ALLOWED_OPS:
                    kept.append(dict(entry))
            out[key] = kept
            return out
    raise _deny()


def call_existing(principal, session, consent, surface, op, params, bind, *, catalog, now,
                  dispatch_existing: Callable[[str, str, Any, str], Any]):
    """Guarded adapter seam; production callback must call facade.dispatch with its authenticated Context.

    This function does not authenticate `principal`, load server state, or
    enforce MCP transport auth. Missing/invalid state always denies before the
    callback runs. The callback is intentionally injected for isolated tests
    and later server integration; it is not itself proof of a real guard.
    The validated scope is not passed to the callback: the route must bind it
    to a Context with uid_of(ctx) == principal.user_id (same request/device),
    and must keep `bind` verification inside facade.dispatch's guard.
    """
    scope = validate_scope(principal, session, consent, now)
    allowed_ops = allowed_operations(catalog)
    validate_call(surface, op, params, allowed_ops)
    return dispatch_existing(surface, op, params, bind)


def find_existing(principal, session, consent, *, catalog, now, find_callback: Callable[..., Any],
                  query="", family="", op=""):
    """Call existing facade.find through an auth-bound callback and filter purge output.

    Same route invariant as call_existing: the callback must already be bound
    to this principal's authenticated Context; this function cannot verify it.
    """
    validate_scope(principal, session, consent, now)
    allowed_ops = allowed_operations(catalog)
    if op:
        # `find(op=...)` may describe only an allowlisted read/write/decide/purge op.
        if not any(name == op for _tier, name in allowed_ops):
            raise _deny()
    result = find_callback(query=query, family=family, op=op)
    return filter_find_result(result, allowed_ops)
