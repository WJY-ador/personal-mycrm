"""최소 RFC 6455 WebSocket 클라이언트 — 표준 라이브러리만(Python ≥3.9). 웹 「대화」 PC→서버 연결 1개에 쓴다.

범위: ws·wss(TLS) · 텍스트 프레임 · 클라이언트 마스킹 · 조각(continuation) 이어 붙이기 · ping→pong 자동 응답 · close 핸드셰이크
· 지수 백오프(Backoff). 확장(permessage-deflate 등)·서브프로토콜 없음. 바이너리 프레임은 받으면 프로토콜 오류로 닫는다.
보내기는 스레드 여럿에서 해도 된다(잠금). 받기는 한 스레드만.
로그·오류 문구엔 토큰·URL·본문을 넣지 않는다(상태 코드·서버 오류 코드만).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import random
import socket
import ssl
import struct
import threading
import time
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OP_CONT, OP_TEXT, OP_BIN, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA
MAX_MESSAGE = 256 * 1024        # 받는 메시지 하나 상한(서버 → PC 는 turn.start 가 가장 크다: 8,000자 ≤ 32KiB)
HEADER_MAX = 16 * 1024
STALL_MAX = 50.0               # 메시지 중간에서 이만큼 바이트가 안 오면 끊긴 연결로 본다(chat 은 silence_max 로 맞춘다)
DENIAL_BODY_MAX = 4 * 1024


class WsError(Exception):
    """kind = network · handshake · protocol · closed. status = 핸드셰이크 HTTP 상태 · code = 서버 오류 코드(JSON code) 또는 close 코드."""

    def __init__(self, kind: str, status: int | None = None, code=None):
        self.kind, self.status, self.code = kind, status, code
        super().__init__(kind + (f" http-{status}" if status else "") + (f" {code}" if code is not None else ""))


class Backoff:
    """지수 백오프 + 지터. next() = 다음 대기(초), reset() = 연결 성공 뒤 처음으로."""

    def __init__(self, base: float = 1.0, cap: float = 60.0, factor: float = 2.0, jitter: float = 0.2, rand=random.random):
        self.base, self.cap, self.factor, self.jitter, self.rand = base, cap, factor, jitter, rand
        self.n = 0

    def next(self) -> float:
        d = min(self.cap, self.base * (self.factor ** self.n))
        self.n += 1
        return d * (1 - self.jitter + 2 * self.jitter * self.rand())

    def reset(self) -> None:
        self.n = 0


def _accept(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode("ascii")).digest()).decode("ascii")


def encode_frame(opcode: int, payload: bytes, *, mask: bool = True, fin: bool = True, mask_key: bytes | None = None) -> bytes:
    """프레임 하나. 클라이언트는 늘 마스킹(RFC 6455 5.3)."""
    head = bytearray([(0x80 if fin else 0) | opcode])
    n = len(payload)
    mbit = 0x80 if mask else 0
    if n < 126:
        head.append(mbit | n)
    elif n < 1 << 16:
        head.append(mbit | 126)
        head += struct.pack("!H", n)
    else:
        head.append(mbit | 127)
        head += struct.pack("!Q", n)
    if not mask:
        return bytes(head) + payload
    k = mask_key if mask_key is not None else os.urandom(4)
    return bytes(head) + k + bytes(b ^ k[i % 4] for i, b in enumerate(payload))


class WebSocket:
    def __init__(self, sock, buf: bytes = b"", max_message: int = MAX_MESSAGE):
        self.sock = sock
        self.buf = bytearray(buf)
        self.max_message = max_message
        self.send_lock = threading.Lock()
        self.closed = False
        self.close_code = None
        self.last_rx = time.monotonic()   # 마지막으로 바이트를 받은 단조 시각 — 반쯤 열린 연결(half-open) 감지용
        self.stall_max = STALL_MAX
    # ── 연결 ──
    @classmethod
    def connect(cls, url: str, headers: dict | None = None, timeout: float = 10.0, ssl_context=None,
                max_message: int = MAX_MESSAGE) -> "WebSocket":
        u = urlsplit(url)
        if u.scheme not in ("ws", "wss") or not u.hostname:
            raise WsError("handshake", code="url")
        port = u.port or (443 if u.scheme == "wss" else 80)
        try:
            sock = socket.create_connection((u.hostname, port), timeout=timeout)
            if u.scheme == "wss":
                ctx = ssl_context or ssl.create_default_context()
                sock = ctx.wrap_socket(sock, server_hostname=u.hostname)
        except (OSError, ssl.SSLError):
            raise WsError("network") from None
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        host = u.hostname if u.port is None else f"{u.hostname}:{u.port}"
        path = (u.path or "/") + (f"?{u.query}" if u.query else "")
        lines = [f"GET {path} HTTP/1.1", f"Host: {host}", "Upgrade: websocket", "Connection: Upgrade",
                 f"Sec-WebSocket-Key: {key}", "Sec-WebSocket-Version: 13"]
        for k, v in (headers or {}).items():
            if "\r" in k or "\n" in k or "\r" in str(v) or "\n" in str(v):
                sock.close()
                raise WsError("handshake", code="header")
            lines.append(f"{k}: {v}")
        try:
            sock.sendall(("\r\n".join(lines) + "\r\n\r\n").encode("latin-1"))
            raw = b""
            while b"\r\n\r\n" not in raw:
                chunk = sock.recv(4096)
                if not chunk:
                    raise WsError("network")
                raw += chunk
                if len(raw) > HEADER_MAX:
                    raise WsError("handshake", code="header-size")
        except WsError:
            sock.close()
            raise
        except (OSError, ssl.SSLError):
            sock.close()
            raise WsError("network") from None
        head, rest = raw.split(b"\r\n\r\n", 1)
        status_line, *hlines = head.decode("latin-1").split("\r\n")
        parts = status_line.split(" ", 2)
        try:
            status = int(parts[1])
        except (IndexError, ValueError):
            sock.close()
            raise WsError("handshake", code="status-line") from None
        hdr = {}
        for ln in hlines:
            if ":" in ln:
                k, v = ln.split(":", 1)
                hdr[k.strip().lower()] = v.strip()
        if status != 101:
            code = cls._denial_code(sock, hdr, rest)
            sock.close()
            raise WsError("handshake", status=status, code=code)
        if hdr.get("upgrade", "").lower() != "websocket" or hdr.get("sec-websocket-accept") != _accept(key):
            sock.close()
            raise WsError("handshake", status=101, code="accept")
        if hdr.get("sec-websocket-extensions"):
            sock.close()
            raise WsError("handshake", status=101, code="extensions")
        sock.settimeout(None)
        return cls(sock, rest, max_message)

    @staticmethod
    def _denial_code(sock, hdr, rest):
        """거절 응답 본문의 JSON code(있으면). 본문은 상한까지만 읽는다."""
        try:
            n = min(int(hdr.get("content-length", "0")), DENIAL_BODY_MAX)
        except ValueError:
            n = 0
        body = rest
        try:
            while len(body) < n:
                chunk = sock.recv(n - len(body))
                if not chunk:
                    break
                body += chunk
            code = json.loads(body[:n].decode("utf-8")).get("code") if n else None
        except Exception:
            code = None
        return code if isinstance(code, str) and len(code) <= 40 else None

    # ── 보내기 ──
    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self.closed:
            raise WsError("closed", code=self.close_code)
        data = encode_frame(opcode, payload)
        with self.send_lock:
            try:
                self.sock.sendall(data)
            except (OSError, ssl.SSLError):
                self.closed = True
                raise WsError("network") from None

    def send_text(self, text: str) -> None:
        self._send_frame(OP_TEXT, text.encode("utf-8"))

    def ping(self, payload: bytes = b"") -> None:
        self._send_frame(OP_PING, payload[:125])

    def close(self, code: int = 1000) -> None:
        if not self.closed:
            try:
                self._send_frame(OP_CLOSE, struct.pack("!H", code))
            except WsError:
                pass
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass

    # ── 받기 ──
    def _need(self, n: int) -> None:
        """버퍼에 n 바이트가 찰 때까지 읽는다(꺼내지 않는다 — 시간 초과가 나도 읽은 바이트는 버퍼에 남는다)."""
        while len(self.buf) < n:
            try:
                chunk = self.sock.recv(max(4096, n - len(self.buf)))
            except socket.timeout:
                raise
            except (OSError, ssl.SSLError):
                self.closed = True
                raise WsError("network") from None
            if not chunk:
                self.closed = True
                raise WsError("network")
            self.last_rx = time.monotonic()
            self.buf += chunk

    def _frame(self):
        """프레임 하나 — 다 찬 뒤에만 버퍼에서 꺼낸다."""
        self._need(2)
        b0, b1 = self.buf[0], self.buf[1]
        fin, opcode, masked, n = bool(b0 & 0x80), b0 & 0x0F, bool(b1 & 0x80), b1 & 0x7F
        if b0 & 0x70:
            raise self._fail(1002)
        at = 2
        if n == 126:
            self._need(4)
            n, at = struct.unpack("!H", bytes(self.buf[2:4]))[0], 4
        elif n == 127:
            self._need(10)
            n, at = struct.unpack("!Q", bytes(self.buf[2:10]))[0], 10
        if n > self.max_message:
            raise self._fail(1009)
        klen = 4 if masked else 0
        self._need(at + klen + n)
        key = bytes(self.buf[at:at + klen])
        payload = bytes(self.buf[at + klen:at + klen + n])
        del self.buf[:at + klen + n]
        if key:
            payload = bytes(b ^ key[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    def _fail(self, code: int) -> WsError:
        self.close(code)
        return WsError("protocol", code=code)

    def recv(self, timeout: float | None = None) -> str:
        """다음 텍스트 메시지. ping 은 pong 으로 답하고 넘어간다. 닫힘 = WsError(closed, code). timeout = socket.timeout.
        timeout 은 메시지 첫 바이트를 기다리는 시간 — 메시지 중간이면 더 기다리되(읽은 바이트는 버퍼에 남는다),
        마지막 수신에서 stall_max 가 지나면 WsError(network)(반쯤 보낸 채 멈춘 연결)."""
        self.sock.settimeout(timeout)
        parts, size, op = [], 0, None
        while True:
            try:
                fin, opcode, payload = self._frame()
            except socket.timeout:
                if parts or self.buf:   # 메시지 중간 — 더 기다리되 상한을 둔다
                    left = self.stall_max - (time.monotonic() - self.last_rx)
                    if left <= 0:
                        self.close(1001)
                        raise WsError("network", code="stall") from None
                    self.sock.settimeout(min(1.0, left))
                    continue
                raise
            if opcode == OP_PING:
                if len(payload) > 125 or not fin:
                    raise self._fail(1002)
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                code = struct.unpack("!H", payload[:2])[0] if len(payload) >= 2 else 1005
                self.close_code = code
                if not self.closed:
                    try:
                        self._send_frame(OP_CLOSE, payload[:2])
                    except WsError:
                        pass
                self.closed = True
                try:
                    self.sock.close()
                except OSError:
                    pass
                raise WsError("closed", code=code)
            if opcode == OP_BIN:
                raise self._fail(1003)
            if opcode == OP_TEXT:
                if op is not None:
                    raise self._fail(1002)
                op = OP_TEXT
            elif opcode == OP_CONT:
                if op is None:
                    raise self._fail(1002)
            else:
                raise self._fail(1002)
            parts.append(payload)
            size += len(payload)
            if size > self.max_message:
                raise self._fail(1009)
            if fin:
                try:
                    return b"".join(parts).decode("utf-8")
                except UnicodeDecodeError:
                    raise self._fail(1007) from None


def connect(url: str, headers: dict | None = None, timeout: float = 10.0, ssl_context=None) -> WebSocket:
    return WebSocket.connect(url, headers, timeout, ssl_context)
