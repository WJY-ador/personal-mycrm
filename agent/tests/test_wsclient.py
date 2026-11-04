"""wsclient 시험 — 가짜 WS 서버(wsfake)로 핸드셰이크·프레이밍·마스킹·조각·ping/pong·close·시간 초과·백오프."""
from __future__ import annotations

import socket
import struct
import threading
import time
import unittest

from agent import wsclient
from agent.tests.wsfake import FakeWsServer


class FrameTest(unittest.TestCase):
    def test_lengths_and_mask(self):
        for n, hlen in ((0, 2), (125, 2), (126, 4), (65535, 4), (65536, 10)):
            f = wsclient.encode_frame(wsclient.OP_TEXT, b"a" * n, mask_key=b"\x01\x02\x03\x04")
            self.assertEqual(f[0], 0x81)
            self.assertTrue(f[1] & 0x80, "클라이언트 프레임은 마스킹")
            self.assertEqual(len(f), hlen + 4 + n)
            if n:
                self.assertEqual(f[hlen + 4], ord("a") ^ 1)
        self.assertEqual(wsclient.encode_frame(wsclient.OP_TEXT, b"hi", mask=False), b"\x81\x02hi")

    def test_backoff(self):
        b = wsclient.Backoff(base=1, cap=8, jitter=0, rand=lambda: 0.5)
        self.assertEqual([b.next() for _ in range(6)], [1, 2, 4, 8, 8, 8])
        b.reset()
        self.assertEqual(b.next(), 1)
        j = wsclient.Backoff(base=10, cap=10, jitter=0.2, rand=lambda: 1.0)
        self.assertAlmostEqual(j.next(), 12.0)


class HandshakeTest(unittest.TestCase):
    def test_ok_headers_and_mask(self):
        got = {}

        def h(c):
            got["m"] = c.recv()
            c.send({"type": "ping"})
            got["masked"] = c.masked_all
            c.recv()

        srv = FakeWsServer(h)
        try:
            ws = wsclient.connect(srv.url, {"Authorization": "Bearer T0K"}, timeout=5)
            ws.send_text('{"type":"hello"}')
            self.assertEqual(ws.recv(timeout=5), '{"type": "ping"}')
            ws.close()
            time.sleep(0.1)
            req = srv.requests[0]
            self.assertEqual(req["line"], "GET /api/device/chat/ws HTTP/1.1")
            self.assertEqual(req["headers"]["authorization"], "Bearer T0K")
            self.assertEqual(req["headers"]["sec-websocket-version"], "13")
            self.assertEqual(got["m"], {"type": "hello"})
            self.assertTrue(got["masked"])
        finally:
            srv.close()

    def test_denied_bad_accept_header_injection(self):
        srv = FakeWsServer(lambda c: None, deny=(401, "TOKEN-REVOKED"))
        try:
            with self.assertRaises(wsclient.WsError) as cm:
                wsclient.connect(srv.url, timeout=5)
            self.assertEqual((cm.exception.kind, cm.exception.status, cm.exception.code), ("handshake", 401, "TOKEN-REVOKED"))
        finally:
            srv.close()
        srv = FakeWsServer(lambda c: None, bad_accept=True)
        try:
            with self.assertRaises(wsclient.WsError) as cm:
                wsclient.connect(srv.url, timeout=5)
            self.assertEqual(cm.exception.code, "accept")
            with self.assertRaises(wsclient.WsError):
                wsclient.connect(srv.url, {"X": "a\r\nInjected: 1"}, timeout=5)
        finally:
            srv.close()
        with self.assertRaises(wsclient.WsError) as cm:
            wsclient.connect("http://127.0.0.1:1/x")
        self.assertEqual(cm.exception.code, "url")

    def test_network_error(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        with self.assertRaises(wsclient.WsError) as cm:
            wsclient.connect(f"ws://127.0.0.1:{port}/x", timeout=2)
        self.assertEqual(cm.exception.kind, "network")


class RecvTest(unittest.TestCase):
    def run_srv(self, h):
        srv = FakeWsServer(h)
        self.addCleanup(srv.close)
        return srv, wsclient.connect(srv.url, timeout=5)

    def test_fragments_ping_close(self):
        seen = {}

        def h(c):
            c.frame(0x1, "조".encode()[:2], fin=False)   # UTF-8 글자가 조각 경계에 걸쳐도 이어 붙인 뒤 푼다
            c.frame(0x9, b"pp")                          # 조각 사이 ping(제어 프레임 끼어들기 허용)
            c.frame(0x0, "조".encode()[2:] + "각".encode(), fin=True)
            seen["pong"] = c.recv()
            c.close(4001)
            seen["close"] = None

        srv, ws = self.run_srv(h)
        self.assertEqual(ws.recv(timeout=5), "조각")
        with self.assertRaises(wsclient.WsError) as cm:
            ws.recv(timeout=5)
        self.assertEqual((cm.exception.kind, cm.exception.code), ("closed", 4001))
        self.assertEqual(seen["pong"], ("pong", b"pp"))
        with self.assertRaises(wsclient.WsError):
            ws.send_text("x")

    def test_binary_and_oversize_are_protocol_errors(self):
        def h(c):
            c.frame(0x2, b"\x00")
            c.recv()

        srv, ws = self.run_srv(h)
        with self.assertRaises(wsclient.WsError) as cm:
            ws.recv(timeout=5)
        self.assertEqual((cm.exception.kind, cm.exception.code), ("protocol", 1003))

        def h2(c):
            c.frame(0x1, b"x" * 300)
            c.recv()

        srv2 = FakeWsServer(h2)
        self.addCleanup(srv2.close)
        ws2 = wsclient.WebSocket.connect(srv2.url, timeout=5, max_message=100)
        with self.assertRaises(wsclient.WsError) as cm:
            ws2.recv(timeout=5)
        self.assertEqual(cm.exception.code, 1009)

    def test_timeout_keeps_partial_frame(self):
        go = threading.Event()

        def h(c):
            payload = b'{"type":"ack","seq":7}'
            frame = bytes([0x81, len(payload)]) + payload
            c.sock.sendall(frame[:5])   # 반쪽 프레임
            go.wait(5)
            c.sock.sendall(frame[5:])
            c.recv()

        srv, ws = self.run_srv(h)
        t0 = time.monotonic()
        threading.Timer(0.3, go.set).start()
        self.assertEqual(ws.recv(timeout=0.1), '{"type":"ack","seq":7}', "중간이면 끝까지 기다린다 — 읽은 바이트 보존")
        self.assertGreaterEqual(time.monotonic() - t0, 0.25)

        def h3(c):
            c.recv()

        srv3 = FakeWsServer(h3)
        self.addCleanup(srv3.close)
        ws3 = wsclient.connect(srv3.url, timeout=5)
        with self.assertRaises(socket.timeout):
            ws3.recv(timeout=0.1)
        ws3.close()

    def test_stall_mid_frame_gives_up(self):
        def h(c):
            c.sock.sendall(bytes([0x81, 20]) + b"0123")   # 20바이트 중 4바이트만 보내고 멈춘다
            time.sleep(3)

        srv, ws = self.run_srv(h)
        ws.stall_max = 0.3
        t0 = time.monotonic()
        with self.assertRaises(wsclient.WsError) as cm:
            ws.recv(timeout=0.1)
        self.assertEqual((cm.exception.kind, cm.exception.code), ("network", "stall"))
        self.assertLess(time.monotonic() - t0, 2.0, "상한 안에서 포기")

    def test_close_code_parse(self):
        def h(c):
            c.frame(0x8, struct.pack("!H", 1013))
            c.recv()

        srv, ws = self.run_srv(h)
        with self.assertRaises(wsclient.WsError) as cm:
            ws.recv(timeout=5)
        self.assertEqual(cm.exception.code, 1013)


if __name__ == "__main__":
    unittest.main()
