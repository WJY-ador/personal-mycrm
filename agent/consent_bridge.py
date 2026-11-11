"""Fail-closed client for the desktop app's private local consent bridge."""
from __future__ import annotations

import json
import os
import re
import socket

MAX_LINE = 8192
_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}")
_REQUEST_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")
_BEARER = re.compile(r"Bearer [A-Za-z0-9._~+/-]{16,500}")
# Refusal reasons the desktop may report. The agent forwards them to the server as consent.result.
REASONS = frozenset({"declined", "locked", "failed"})
_FAILED = (False, "failed")


def _parse_reply(result) -> "tuple[bool, str | None]":
    """Accept only {"ok": true} or {"ok": false[, "reason": <REASONS>]}; anything else fails closed."""
    if not isinstance(result, dict):
        return _FAILED
    keys = set(result)
    if keys not in ({"ok"}, {"ok", "reason"}) or type(result["ok"]) is not bool:
        return _FAILED
    if result["ok"] is True:
        return (True, None) if keys == {"ok"} else _FAILED
    reason = result.get("reason")
    # A 0.1.3 desktop answers a bare {"ok": false}; an unknown reason is treated the same way.
    if isinstance(reason, str) and reason in REASONS:
        return (False, reason)
    return _FAILED


def request_approval(socket_path: str, token: str, request_id: str, device_bearer: str, *,
                     timeout: float = 150) -> "tuple[bool, str | None]":
    """Send only a pending request id and device token to the supervised desktop main process.

    The socket path and one-run random capability are injected by the desktop supervisor.
    The hosted renderer never receives either value. Returns (ok, reason): (True, None) only for
    an exact affirmative reply. Malformed input, transport error, timeout or a malformed reply
    returns (False, "failed"); a desktop refusal returns (False, "declined" | "locked" | "failed").
    """
    if (not isinstance(socket_path, str) or not os.path.isabs(socket_path)
            or not isinstance(token, str) or not _TOKEN.fullmatch(token)
            or not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id)
            or not isinstance(device_bearer, str) or not _BEARER.fullmatch(device_bearer)
            or not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0):
        return _FAILED
    return _exchange(socket_path, {"version": 1, "token": token, "request_id": request_id,
                                   "device_bearer": device_bearer}, timeout)


def request_revoke(socket_path: str, token: str, device_bearer: str, *, timeout: float = 30) -> bool:
    """Hand this PC's device token to desktop main so it revokes the installation's server consent key.

    Desktop main runs `chat-consent-revoke` at app start and on screen lock. Main owns the session cookie and the
    installation id; the agent owns the device token. True only for an exact {"ok": true} reply, which main sends
    after the server answered keys/revoke. Everything else is False.
    """
    if (not isinstance(socket_path, str) or not os.path.isabs(socket_path)
            or not isinstance(token, str) or not _TOKEN.fullmatch(token)
            or not isinstance(device_bearer, str) or not _BEARER.fullmatch(device_bearer)
            or not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or timeout <= 0):
        return False
    return _exchange(socket_path, {"version": 1, "token": token, "kind": "revoke",
                                   "device_bearer": device_bearer}, timeout) == (True, None)


def _exchange(socket_path: str, message: dict, timeout: float) -> "tuple[bool, str | None]":
    """One request line, one reply line, parsed by _parse_reply. Any transport or format error fails closed."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_LINE:
        return _FAILED
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.settimeout(timeout)
        client.connect(socket_path)
        client.sendall(payload)
        client.shutdown(socket.SHUT_WR)
        raw = bytearray()
        while len(raw) <= MAX_LINE:
            chunk = client.recv(min(1024, MAX_LINE + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if b"\n" in chunk:
                break
        if len(raw) > MAX_LINE or raw.count(b"\n") != 1 or not raw.endswith(b"\n"):
            return _FAILED
        return _parse_reply(json.loads(raw[:-1].decode("utf-8")))
    except (OSError, ValueError, UnicodeError, TimeoutError, RecursionError):
        return _FAILED
    finally:
        client.close()
