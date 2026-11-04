"""chat 시험 — FakeProvider · TurnBuffer(ack·상한) · ChatAgent(가짜 WS 서버: hello·턴 실행·delta 묶음·session_ref·재연결 재전송·
중지·인증 거절·버퍼 상한) · CLI chat(--fake 만, 토큰 없음·인증 거절 exit)."""
from __future__ import annotations

import json
import queue
import threading
import time
import unittest

from agent import chat, wsclient
from agent.tests import helpers
from agent.tests.wsfake import FakeWsServer

FAST = dict(backoff=wsclient.Backoff(base=0.05, cap=0.2, jitter=0), recv_tick=0.05)


class ProviderBufferTest(unittest.TestCase):
    def test_fake_provider_script_and_stop(self):
        p = chat.FakeProvider(step=0)
        out = list(p.start_turn("안녕하세요"))
        self.assertEqual(out[0][0], "session_ref")
        self.assertEqual([k for k, _ in out[1:]], ["delta", "delta", "tool_call", "tool_result", "delta", "done"])
        self.assertIn("5자", out[2][1]["text"])
        self.assertNotIn("session_ref", [k for k, _ in p.start_turn("x", "ref-1")], "재개 ID 가 있으면 새로 내지 않는다")
        p2 = chat.FakeProvider(step=0.05)
        it = p2.start_turn("x", "r")
        next(it)
        p2.stop()
        self.assertEqual(list(it), [("error", {"code": "STOPPED"})])

    def test_turn_buffer(self):
        b = chat.TurnBuffer("ct_1", limit=200)
        m1 = json.loads(b.add("delta", {"text": "a"}))
        self.assertEqual((m1["type"], m1["turn_id"], m1["seq"], m1["kind"]), ("event", "ct_1", 1, "delta"))
        b.add("delta", {"text": "b"})
        self.assertIsNone(b.add("delta", {"text": "x" * 200}), "상한 초과 = None")
        self.assertEqual(b.seq, 2)
        self.assertEqual([json.loads(m)["seq"] for m in b.pending()], [1, 2])
        b.ack(1)
        self.assertEqual([json.loads(m)["seq"] for m in b.pending()], [2])
        self.assertTrue(b.add("done", {}, force=True))
        self.assertFalse(b.done())
        b.ack(3)
        self.assertTrue(b.done() and b.bytes == 0)

    def test_ws_url(self):
        self.assertEqual(chat.ws_url("https://x.example/"), "wss://x.example/api/device/chat/ws")
        self.assertEqual(chat.ws_url("http://127.0.0.1:8800"), "ws://127.0.0.1:8800/api/device/chat/ws")
        with self.assertRaises(ValueError):
            chat.ws_url("ftp://x")


class Script:
    """가짜 서버 연결 처리 — 연결마다 순서대로 함수 하나."""

    def __init__(self, *steps):
        self.steps = list(steps)
        self.msgs = queue.Queue()

    def __call__(self, c):
        step = self.steps.pop(0) if self.steps else (lambda c, s: c.recv())
        step(c, self)

    def events(self, c, until_kind=None, ack=True, n=None):
        """이벤트를 모은다 — session_ref 는 따로 msgs 로. until_kind 가 오면 멈춤."""
        got = []
        while True:
            m = c.recv()
            if isinstance(m, tuple):
                return got
            self.msgs.put(m)
            if m.get("type") == "event":
                got.append(m)
                if ack:
                    c.send({"type": "ack", "turn_id": m["turn_id"], "seq": m["seq"]})
                if m["kind"] == until_kind or (n and len(got) >= n):
                    return got


def run_agent(srv, provider, **kw):
    stopping = threading.Event()
    a = chat.ChatAgent(srv.url, "TOK", provider, agent_version="t", stopping=stopping, **{**FAST, **kw})
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("why", a.run()), daemon=True)
    th.start()
    return a, stopping, th, res


class AgentTest(unittest.TestCase):
    def test_turn_roundtrip_coalesce_session_ref(self):
        got = {}

        def conn1(c, s):
            got["hello"] = c.recv()
            c.send({"type": "ping"})
            got["pong"] = c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_1", "text": "안녕"})
            got["events"] = s.events(c, "done")
            c.recv()

        sc = Script(conn1)
        srv = FakeWsServer(sc)
        a, stopping, th, _ = run_agent(srv, chat.FakeProvider(step=0.01))
        try:
            deadline = time.time() + 5
            while "events" not in got and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(got["hello"], {"type": "hello", "agent_version": "t", "providers": ["fake"]})
            self.assertEqual(srv.requests[0]["headers"]["authorization"], "Bearer TOK")
            self.assertEqual(got["pong"], {"type": "pong"})
            ev = got["events"]
            self.assertEqual([e["seq"] for e in ev], list(range(1, len(ev) + 1)), "seq 1부터 연속")
            self.assertEqual([e["kind"] for e in ev], ["delta", "tool_call", "tool_result", "delta", "done"], "0.5초 안 delta 둘은 하나로 묶음")
            self.assertEqual(ev[0]["data"]["text"], "가짜 답이에요. 받은 글은 2자예요. ")
            refs = [m for m in list(sc.msgs.queue) if m.get("type") == "session_ref"]
            self.assertEqual(len(refs), 1)
            self.assertEqual(refs[0]["session_id"], "cs_1")
            time.sleep(0.2)
            self.assertEqual(a.buffers, {}, "모두 ack — 버퍼 비움")
        finally:
            stopping.set()
            th.join(5)
            srv.close()
        self.assertFalse(th.is_alive())

    def test_reconnect_resends_unacked_without_rerun(self):
        got = {"first": [], "second": []}

        def conn1(c, s):
            c.recv()   # hello
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_9", "text": "x"})
            ev = s.events(c, ack=False, n=2)   # 둘 받고 ack 없이 끊는다
            got["first"] = [e["seq"] for e in ev]
            c.drop()

        def conn2(c, s):
            got["hello2"] = c.recv()
            ev = s.events(c, "done")
            got["second"] = [e["seq"] for e in ev]
            c.recv()

        provider = chat.FakeProvider(step=0.05)
        srv = FakeWsServer(Script(conn1, conn2))
        a, stopping, th, _ = run_agent(srv, provider, coalesce=0.0)
        try:
            deadline = time.time() + 8
            while not got["second"] and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(got["first"], [1, 2])
            self.assertEqual(got["hello2"]["type"], "hello", "재연결 뒤 hello 먼저")
            self.assertEqual(got["second"][:2], [1, 2], "미확인 이벤트를 같은 seq 로 재전송")
            self.assertEqual(got["second"][-1], max(got["second"]))
            self.assertEqual(provider.turns, 1, "턴 자동 재실행 없음")
            self.assertGreaterEqual(a.connects, 2)
        finally:
            stopping.set()
            th.join(5)
            srv.close()

    def test_stop_and_buffer_limit(self):
        got = {}

        def conn1(c, s):
            c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_s", "text": "x"})
            first = s.events(c, n=1)
            c.send({"type": "turn.stop", "turn_id": "ct_s"})
            got["stop"] = first + s.events(c, "error")
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_s", "text": "x"})   # 같은 턴 다시 = 실행 안 함
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_b", "text": "big"})
            got["buf"] = s.events(c, "error", ack=False)   # ack 없음 — 버퍼가 찬다
            c.recv()

        big = [("tool_call", {"name": "n", "input": {"p": "y" * 300}})] * 5 + [("done", {})]
        provider = chat.FakeProvider(step=0.1)
        provider.script = lambda text: big if text == "big" else provider._default(text)
        srv = FakeWsServer(Script(conn1))
        a, stopping, th, _ = run_agent(srv, provider, coalesce=0.0, buffer_max=1000)
        try:
            deadline = time.time() + 8
            while "stop" not in got and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(got["stop"][-1]["data"], {"code": "STOPPED"})
            while "buf" not in got and time.time() < deadline:
                time.sleep(0.05)
            ev = got["buf"]
            self.assertEqual(ev[-1]["data"], {"code": "BUFFER-LIMIT"}, ev)
            self.assertEqual(provider.turns, 2, "같은 turn_id 의 두 번째 turn.start 는 실행하지 않는다")
        finally:
            stopping.set()
            th.join(5)
            srv.close()

    def test_auth_denied_stops(self):
        srv = FakeWsServer(lambda c: None, deny=(401, "TOKEN-REVOKED"))
        logs = []
        a, stopping, th, res = run_agent(srv, chat.FakeProvider(), log=logs.append)
        th.join(5)
        srv.close()
        self.assertEqual(res["why"], "auth")
        self.assertEqual(logs, [{"event": "connect", "error": "auth", "status": 401}])

    def test_retry_on_503(self):
        srv = FakeWsServer(lambda c: None, deny=(503, "SWITCH-OFF"))
        a, stopping, th, res = run_agent(srv, chat.FakeProvider())
        time.sleep(0.5)
        self.assertGreaterEqual(len(srv.requests), 2, "503 = 백오프 뒤 다시")
        stopping.set()
        th.join(5)
        srv.close()
        self.assertEqual(res["why"], "signal")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.th = helpers.TempHome()
        self.addCleanup(self.th.cleanup)

    def test_requires_fake_and_token(self):
        code, out = helpers.run_cli(["--home", self.th.home, "chat"])
        self.assertEqual(code, 2)
        self.assertIn("--fake", out)
        helpers.connected_config(self.th, "http://127.0.0.1:9")
        code, out = helpers.run_cli(["--home", self.th.home, "chat", "--fake"], ks_factory=lambda svc: helpers.MemoryKeyStore())
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(out.strip()), {"event": "start", "stopped": "auth"})

    def test_runs_and_stops_without_secrets_in_output(self):
        got = threading.Event()

        def h(c):
            c.recv()
            got.set()
            c.recv()

        srv = FakeWsServer(h)
        self.addCleanup(srv.close)
        helpers.connected_config(self.th, f"http://127.0.0.1:{srv.port}")
        stopping = threading.Event()
        threading.Thread(target=lambda: (got.wait(5), stopping.set()), daemon=True).start()
        ks = helpers.keystore_with_secrets()
        code, out = helpers.run_cli(["--home", self.th.home, "chat", "--fake"], ks_factory=lambda svc: ks,
                                    chat_kw={"stopping": stopping, **FAST})
        self.assertEqual(code, 0)
        self.assertEqual(srv.requests[0]["headers"]["authorization"], "Bearer " + helpers.TOKEN)
        self.assertNotIn(helpers.TOKEN, out)
        self.assertNotIn("127.0.0.1", out)
        lines = [json.loads(x) for x in out.strip().splitlines()]
        self.assertEqual(lines[0], {"event": "connect", "ok": True})
        self.assertEqual(lines[-1], {"event": "stop", "stopped": "signal"})

        code, out = helpers.run_cli(["--home", self.th.home, "chat", "--fake"], ks_factory=lambda svc: ks,
                                    chat_kw={"connect": lambda *a, **k: (_ for _ in ()).throw(wsclient.WsError("handshake", 403, "AUTH-BLOCKED")),
                                             **FAST})
        self.assertEqual(code, 3)


if __name__ == "__main__":
    unittest.main()
