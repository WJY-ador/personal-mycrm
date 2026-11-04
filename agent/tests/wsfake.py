"""시험 도우미 — 가짜 WebSocket 서버(127.0.0.1, 표준 라이브러리만). 연결마다 handler(conn) 를 스레드에서 부른다.

conn.recv() = 클라이언트 텍스트 메시지(마스킹 확인) · conn.send(obj|str) · conn.frame(op, payload, fin) = 손으로 프레임 · conn.close(code).
deny=(status, code) 면 핸드셰이크를 그 HTTP 상태 + {"code"} JSON 으로 거절한다. headers = 받은 요청 헤더(소문자 키).
"""
from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class Conn:
    def __init__(self, sock, headers):
        self.sock, self.headers = sock, headers
        self.buf = b""
        self.masked_all = True

    def _read(self, n):
        while len(self.buf) < n:
            c = self.sock.recv(65536)
            if not c:
                raise EOFError
            self.buf += c
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv_frame(self):
        b0, b1 = self._read(2)
        op, masked, n = b0 & 0x0F, bool(b1 & 0x80), b1 & 0x7F
        if n == 126:
            n = struct.unpack("!H", self._read(2))[0]
        elif n == 127:
            n = struct.unpack("!Q", self._read(8))[0]
        self.masked_all = self.masked_all and masked
        key = self._read(4) if masked else b""
        p = self._read(n)
        if key:
            p = bytes(b ^ key[i % 4] for i, b in enumerate(p))
        return bool(b0 & 0x80), op, p

    def recv(self):
        """다음 텍스트 메시지(dict 면 JSON 풀어서). close 면 ("close", code). pong 은 ("pong", payload)."""
        fin, op, p = self.recv_frame()
        if op == 0x8:
            return ("close", struct.unpack("!H", p[:2])[0] if len(p) >= 2 else 1005)
        if op == 0xA:
            return ("pong", p)
        t = p.decode("utf-8")
        try:
            return json.loads(t)
        except ValueError:
            return t

    def frame(self, op, payload: bytes, fin=True):
        n = len(payload)
        head = bytes([(0x80 if fin else 0) | op])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack("!H", n)
        else:
            head += bytes([127]) + struct.pack("!Q", n)
        self.sock.sendall(head + payload)

    def send(self, obj):
        self.frame(0x1, (obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)).encode("utf-8"))

    def close(self, code=1000):
        try:
            self.frame(0x8, struct.pack("!H", code))
        except OSError:
            pass
        self.drop()

    def drop(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()


class FakeWsServer:
    def __init__(self, handler, deny=None, bad_accept=False):
        self.handler, self.deny, self.bad_accept = handler, deny, bad_accept
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        self.url = f"ws://127.0.0.1:{self.port}/api/device/chat/ws"
        self.conns = []
        self.requests = []
        self.errors = []
        self._stop = False
        self.th = threading.Thread(target=self._accept, daemon=True)
        self.th.start()

    def _accept(self):
        while not self._stop:
            try:
                s, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(s,), daemon=True).start()

    def _serve(self, s):
        raw = b""
        while b"\r\n\r\n" not in raw:
            c = s.recv(4096)
            if not c:
                s.close()
                return
            raw += c
        head, rest = raw.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        hdr = {k.strip().lower(): v.strip() for k, v in (ln.split(":", 1) for ln in lines[1:] if ":" in ln)}
        self.requests.append({"line": lines[0], "headers": hdr})
        if self.deny:
            st, code = self.deny
            body = json.dumps({"code": code}).encode()
            s.sendall(f"HTTP/1.1 {st} X\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
            s.close()
            return
        acc = base64.b64encode(hashlib.sha1((hdr.get("sec-websocket-key", "") + GUID).encode()).digest()).decode()
        if self.bad_accept:
            acc = "AAAA" + acc[4:]
        s.sendall(("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Accept: {acc}\r\n\r\n").encode())
        conn = Conn(s, hdr)
        conn.buf = rest
        self.conns.append(conn)
        try:
            self.handler(conn)
        except (EOFError, OSError):
            pass
        except Exception as e:   # 시험이 볼 수 있게 남긴다
            self.errors.append(e)
        finally:
            conn.drop()

    def close(self):
        self._stop = True
        try:
            self.sock.close()
        except OSError:
            pass
