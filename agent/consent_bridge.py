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


def request_approval(socket_path: str, token: str, request_id: str, device_bearer: str, *, timeout: float = 150) -> bool:
    """Send only a pending request id and device token to the supervised desktop main process.

    The socket path and one-run random capability are injected by the desktop supervisor.
    The hosted renderer never receives either value. Any malformed input, transport error,
    or non-affirmative response returns False.
    """
    if (not isinstance(socket_path, str) or not os.path.isabs(socket_path)
            or not isinstance(token, str) or not _TOKEN.fullmatch(token)
            or not isinstance(request_id, str) or not _REQUEST_ID.fullmatch(request_id)
            or not isinstance(device_bearer, str) or not _BEARER.fullmatch(device_bearer)
            or not isinstance(timeout, (int, float)) or timeout <= 0):
        return False
    payload = json.dumps({"version": 1, "token": token, "request_id": request_id,
                          "device_bearer": device_bearer}, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(payload) > MAX_LINE:
        return False
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
            return False
        result = json.loads(raw[:-1].decode("utf-8"))
        return isinstance(result, dict) and set(result) == {"ok"} and result["ok"] is True
    except (OSError, ValueError, UnicodeError, TimeoutError):
        return False
    finally:
        client.close()
