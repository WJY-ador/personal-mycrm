"""chat 시험 — FakeProvider · TurnBuffer(ack·상한) · ChatAgent(가짜 WS 서버: hello·턴 실행·delta 묶음·session_ref·재연결 재전송·
중지·인증 거절·버퍼 상한) · CLI chat(--fake 만, 토큰 없음·인증 거절 exit)."""
from __future__ import annotations

import json
import os
import queue
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest.mock import patch

from agent import chat, chat_providers, wsclient
from agent import chat_claude
from agent.chat_launch_authority import LaunchAuthorizationClient
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


def run_agent(srv, provider, token="TOK", **kw):
    stopping = threading.Event()
    refs = chat_providers.CliSessionRefStore(helpers.MemoryKeyStore(), "device-test")
    a = chat.ChatAgent(srv.url, token, provider, ref_store=refs, agent_version="t", stopping=stopping, **{**FAST, **kw})
    res = {}
    th = threading.Thread(target=lambda: res.setdefault("why", a.run()), daemon=True)
    th.start()
    return a, stopping, th, res


class AgentTest(unittest.TestCase):
    def test_turn_start_keeps_server_approval_outcomes_separate_from_original_text(self):
        provider = chat.FakeProvider(step=0)
        sent = []
        class Socket:
            def send_text(self, message): sent.append(json.loads(message)); return True
        agent = chat.ChatAgent("ws://unused", "synthetic-token", provider=provider,
                               stopping=threading.Event(), coalesce=0)
        agent.ws = Socket()
        original_text = "Please continue with my original request"
        outcome = {"id": "ca_" + "c" * 24, "op": "record_edit", "status": "confirmed"}
        agent._on({"type": "turn.start", "session_id": "cs_synthetic", "turn_id": "ct_synthetic",
                   "text": original_text, "provider": "fake", "model": None, "binding_version": 2,
                   "approval_outcomes": [outcome]})
        agent.threads[0].join(5)
        self.assertEqual(provider.last_turn_text, original_text)
        self.assertEqual(provider.last_approval_outcomes,
                         ((outcome["id"], outcome["op"], outcome["status"]),))

    def test_turn_start_rejects_untrusted_approval_outcomes_before_provider_run(self):
        provider = chat.FakeProvider(step=0)
        sent = []
        class Socket:
            def send_text(self, message): sent.append(json.loads(message)); return True
        agent = chat.ChatAgent("ws://unused", "synthetic-token", provider=provider,
                               stopping=threading.Event(), coalesce=0)
        agent.ws = Socket()
        agent._on({"type": "turn.start", "session_id": "cs_synthetic", "turn_id": "ct_synthetic",
                   "text": "synthetic original", "provider": "fake", "model": None, "binding_version": 2,
                   "approval_outcomes": [{"id": "ca_" + "d" * 24, "op": "record_edit",
                                           "status": "confirmed", "params": {"secret": "synthetic"}}]})
        self.assertEqual(provider.turns, 0)
        self.assertEqual(sent[-1]["data"], {"code": "APPROVAL-OUTCOMES"})

    @unittest.skipUnless(sys.platform == "darwin", "requires macOS process supervisor")
    def test_claude_factory_turn_runs_only_the_synthetic_cli_and_returns_events(self):
        from datetime import datetime, timedelta, timezone
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
        response = {"authorized": True, "binding": {"user_id": "u_synthetic", "device_id": "is_" + "a" * 24,
            "session_id": "cs_synthetic", "turn_id": "ct_synthetic", "provider": "claude",
            "model": "claude-synthetic", "grant_id": "g_synthetic", "consent_challenge_id": "ch_synthetic",
            "expires_at": expiry}, "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__record_get": "read"}}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(response).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def __init__(self): self.calls = 0
            def open(self, *_args, **_kwargs): self.calls += 1; return Reply()
        with tempfile.TemporaryDirectory(prefix="chat-e2e-") as home:
            cli = os.path.join(home, "fake-claude")
            script = "#!" + sys.executable + "\nimport json\n"
            script += "print(json.dumps({'type':'system','subtype':'init','session_id':'fixture-session','cwd':'.','tools':['mcp__my-crm__find','mcp__my-crm__read'],'mcp_servers':[{'name':'my-crm','status':'connected'}],'model':'claude-synthetic','permissionMode':'default'}),flush=True)\n"
            script += "print(json.dumps({'type':'assistant','session_id':'fixture-session','message':{'role':'assistant','content':[{'type':'text','text':'synthetic reply'}]}}),flush=True)\n"
            script += "print(json.dumps({'type':'result','subtype':'success','is_error':False,'session_id':'fixture-session'}),flush=True)\n"
            with open(cli, "w") as f: f.write(script)
            os.chmod(cli, 0o700)
            client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-token")
            opener = Opener()
            client._opener = opener
            factory = chat_claude.ClaudeProviderFactory(client, cli_path=cli, server_url="https://synthetic.invalid",
                agent_home=home, expected_device_id="is_" + "a" * 24, env={"HOME": home, "PATH": "/usr/bin"},
                temp_parent=home, models=("claude-synthetic",), timeout=3)
            sent = []
            class Socket:
                def send_text(self, message): sent.append(json.loads(message)); return True
            agent = chat.ChatAgent("wss://synthetic.invalid/api/device/chat/ws", "synthetic-token",
                                   claude_factory=factory, stopping=threading.Event(), coalesce=0)
            agent.ws = Socket()
            agent._on({"type": "turn.start", "session_id": "cs_synthetic", "turn_id": "ct_synthetic",
                       "text": "Reply OK", "provider": "claude", "model": "claude-synthetic",
                       "binding_version": 2, "launch_authorization_path": "/api/chat/launch-authorization"})
            agent.threads[0].join(5)
            self.assertFalse(agent.threads[0].is_alive())
            self.assertGreaterEqual(opener.calls, 1)
            events = [item for item in sent if item.get("type") == "event"]
            self.assertEqual([item["kind"] for item in events], ["delta", "done"])
            self.assertEqual(events[0]["data"]["text"], "synthetic reply")
            self.assertNotIn("synthetic-token", repr(sent))

    @patch.object(chat_claude, "sys", types.SimpleNamespace(platform="darwin", executable=sys.executable))
    def test_claude_turn_requires_server_launch_authorization_before_provider_creation(self):
        class Reply:
            status = 200
            def read(self, *_args):
                from datetime import datetime, timedelta, timezone
                expiry = (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
                return json.dumps({"authorized": True, "binding": {
                    "user_id": "u-synthetic", "device_id": "is_" + "a" * 24,
                    "session_id": "cs_expected", "turn_id": "ct_other", "provider": "claude",
                    "model": "claude-synthetic", "grant_id": "g_synthetic",
                    "consent_challenge_id": "ch_synthetic", "expires_at": expiry},
                    "tools": {"mcp__my-crm__record_get": "read"}}).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        with tempfile.TemporaryDirectory(prefix="chat-agent-launch-") as home:
            cli = os.path.join(home, "fake-claude")
            with open(cli, "w") as f:
                f.write("#!/bin/sh\nexit 0\n")
            os.chmod(cli, 0o700)
            client = LaunchAuthorizationClient("https://synthetic.invalid", lambda: "synthetic-device-token")
            client._opener = Opener()  # test-only transport installed after default construction; no user path can supply it
            factory = chat_claude.ClaudeProviderFactory(client, cli_path=cli, server_url="https://synthetic.invalid",
                agent_home=home, expected_device_id="is_" + "a" * 24, env={"HOME": home, "PATH": "/usr/bin"},
                temp_parent=home, models=("claude-synthetic",))
            sent = []
            class Socket:
                def send_text(self, message): sent.append(json.loads(message)); return True
            agent = chat.ChatAgent("wss://synthetic.invalid/api/device/chat/ws", "token",
                                   claude_factory=factory, stopping=threading.Event())
            agent.ws = Socket()
            agent._on({"type": "turn.start", "session_id": "cs_expected", "turn_id": "ct_expected",
                       "text": "synthetic", "provider": "claude", "model": "claude-synthetic",
                       "binding_version": 2, "launch_authorization_path": "/api/chat/launch-authorization"})
        self.assertEqual(sent[-1]["data"], {"code": "PROVIDER-BINDING"})
        self.assertIsNone(agent.current_provider)

    def test_consent_request_is_forwarded_once_to_local_desktop_callback(self):
        calls = []
        entered = threading.Event()
        release = threading.Event()

        def consent(request_id, authorization):
            calls.append((request_id, authorization))
            entered.set()
            release.wait(2)

        agent = chat.ChatAgent("ws://unused", lambda: "synthetic-device-token", chat.FakeProvider(),
                               consent_request=consent)
        agent._on({"type": "consent.request", "request_id": "request_test_1"})
        self.assertTrue(entered.wait(1))
        agent._on({"type": "consent.request", "request_id": "request_test_1"})
        agent._on({"type": "consent.request", "request_id": "bad id"})
        self.assertEqual(calls, [("request_test_1", "Bearer synthetic-device-token")])
        release.set()

    def test_rejects_missing_or_changed_provider_binding_without_fallback(self):
        got = {}

        def conn(c, s):
            c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_first", "text": "x",
                    "provider": "fake", "model": None, "binding_version": 2})
            got["first"] = s.events(c, "done")
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_changed", "text": "x",
                    "provider": "claude", "model": "made-up", "binding_version": 2})
            got["changed"] = s.events(c, "error")
            c.send({"type": "turn.start", "session_id": "cs_2", "turn_id": "ct_missing", "text": "x"})
            got["missing"] = s.events(c, "error")
            c.recv()

        provider = chat.FakeProvider(step=0)
        srv = FakeWsServer(Script(conn))
        a, stopping, th, _ = run_agent(srv, provider, coalesce=0.0)
        try:
            deadline = time.time() + 5
            while "missing" not in got and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(got["changed"][-1]["data"], {"code": "PROVIDER-BINDING"})
            self.assertEqual(got["missing"][-1]["data"], {"code": "PROVIDER-BINDING"})
            self.assertEqual(provider.turns, 1, "유효한 선택만 실행하고 실패 시 대체 공급자 없음")
        finally:
            stopping.set()
            th.join(5)
            srv.close()

    def test_turn_roundtrip_coalesce_session_ref(self):
        got = {}

        def conn1(c, s):
            got["hello"] = c.recv()
            c.send({"type": "ping"})
            got["pong"] = c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_1", "text": "안녕", "provider": "fake", "model": None, "binding_version": 2})
            got["events"] = s.events(c, "done")
            c.recv()

        sc = Script(conn1)
        srv = FakeWsServer(sc)
        a, stopping, th, _ = run_agent(srv, chat.FakeProvider(step=0.01))
        try:
            deadline = time.time() + 5
            while "events" not in got and time.time() < deadline:
                time.sleep(0.05)
            self.assertEqual(got["hello"], {"type": "hello", "agent_version": "t", "providers": ["fake"], "capabilities_version": 2, "capabilities": [{"provider": "fake", "models": [None]}]})
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
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_9", "text": "x", "provider": "fake", "model": None, "binding_version": 2})
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
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_s", "text": "x", "provider": "fake", "model": None, "binding_version": 2})
            first = s.events(c, n=1)
            c.send({"type": "turn.stop", "turn_id": "ct_s"})
            got["stop"] = first + s.events(c, "error")
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_s", "text": "x", "provider": "fake", "model": None, "binding_version": 2})   # 같은 턴 다시 = 실행 안 함
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_b", "text": "big", "provider": "fake", "model": None, "binding_version": 2})
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


class ReviewTest(unittest.TestCase):
    """PR #45 리뷰 — 반쯤 열린 연결 감지 · 메시지 크기 상한 · 토큰 교체 뒤 이어 가기."""

    def test_fit_event(self):
        big = "가" * 100000
        parts = chat.fit_event("ct_1", "delta", {"text": big})
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(p["text"] for p in parts), big)
        self.assertTrue(all(chat._size("ct_1", "delta", p) <= chat.WS_MESSAGE_MAX for p in parts))
        esc = "\x01" * 40000   # JSON 이스케이프(\u0001 = 6바이트) 최악
        self.assertTrue(all(chat._size("ct_1", "delta", p) <= chat.WS_MESSAGE_MAX for p in chat.fit_event("ct_1", "delta", {"text": esc})))
        t = chat.fit_event("ct_1", "tool_call", {"name": "find", "input": {"q": "x" * 100000}, "ok": True})
        self.assertEqual(t, [{"name": "find", "ok": True, "truncated": True}])
        t = chat.fit_event("ct_1", "tool_result", {"name": "find", "summary": "y" * 100000})
        self.assertEqual((len(t), t[0]["truncated"], len(t[0]["summary"])), (1, True, 2000))
        self.assertEqual(chat.fit_event("ct_1", "done", {}), [{}], "작으면 그대로")

    def test_big_events_stay_under_limit(self):
        got = {}

        def conn1(c, s):
            c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_big", "text": "x", "provider": "fake", "model": None, "binding_version": 2})
            got["ev"] = s.events(c, "done")
            c.recv()

        script = lambda text: [("delta", {"text": "나" * 60000}), ("tool_call", {"name": "n", "input": {"p": "z" * 90000}}), ("done", {})]
        srv = FakeWsServer(Script(conn1))
        a, stopping, th, _ = run_agent(srv, chat.FakeProvider(step=0, script=script), coalesce=0.0, buffer_max=10 ** 7)
        try:
            deadline = time.time() + 5
            while "ev" not in got and time.time() < deadline:
                time.sleep(0.05)
            ev = got["ev"]
            self.assertTrue(all(len(json.dumps(m, ensure_ascii=False, separators=(",", ":")).encode()) <= chat.WS_MESSAGE_MAX for m in ev))
            self.assertEqual("".join(m["data"]["text"] for m in ev if m["kind"] == "delta"), "나" * 60000)
            self.assertEqual([m["data"] for m in ev if m["kind"] == "tool_call"], [{"name": "n", "truncated": True}])
            self.assertEqual([m["seq"] for m in ev], list(range(1, len(ev) + 1)))
        finally:
            stopping.set()
            th.join(5)
            srv.close()

    def test_half_open_reconnects(self):
        got = {"n": 0}

        def hold(c, s):   # hello 만 받고 아무것도 보내지 않은 채 소켓을 붙든다(FIN 없음)
            c.recv()
            got["n"] += 1
            time.sleep(3)

        srv = FakeWsServer(Script(hold, hold, hold))
        logs = []
        a, stopping, th, _ = run_agent(srv, chat.FakeProvider(), silence_max=0.3, log=logs.append)
        try:
            deadline = time.time() + 5
            while a.connects < 2 and time.time() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(a.connects, 2, "조용한 연결을 닫고 다시 붙는다")
            self.assertIn({"event": "disconnect", "why": "silent"}, logs)
        finally:
            stopping.set()
            th.join(5)
            srv.close()

    def test_token_reread_on_401_and_4001(self):
        reads = []

        def keystore_now():   # 첫 읽기 = 옛 토큰, 그 뒤 = run-once 의 rotate 가 바꾼 새 토큰
            reads.append(1)
            return "OLD" if len(reads) == 1 else "NEW"

        srv = FakeWsServer(lambda c: (c.recv(), c.recv()), deny=lambda h: (401, "TOKEN-REVOKED") if h.get("authorization") != "Bearer NEW" else None)
        logs = []
        a, stopping, th, res = run_agent(srv, chat.FakeProvider(), token=keystore_now, log=logs.append)
        try:
            deadline = time.time() + 5
            while a.connects < 1 and time.time() < deadline:
                time.sleep(0.05)
            self.assertGreaterEqual(a.connects, 1, "새 토큰으로 이어 간다")
            self.assertEqual([r["headers"]["authorization"] for r in srv.requests[:2]], ["Bearer OLD", "Bearer NEW"])
            self.assertNotIn("why", res, "멈추지 않았다")
        finally:
            stopping.set()
            th.join(5)
            srv.close()

        def close4001(c, s):
            c.recv()
            c.close(4001)

        srv2 = FakeWsServer(Script(close4001, close4001))
        a2, stopping2, th2, res2 = run_agent(srv2, chat.FakeProvider(), log=logs.append)   # 토큰 그대로 = 멈춤
        th2.join(5)
        srv2.close()
        self.assertEqual(res2.get("why"), "auth")
        self.assertEqual(a2.connects, 1)
        self.assertIn({"event": "disconnect", "why": "auth-closed"}, logs)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.th = helpers.TempHome()
        self.addCleanup(self.th.cleanup)

    def test_ready_false_normal_chat_connects_without_provider_and_forwards_consent(self):
        self.assertFalse(__import__("agent.cli", fromlist=["CHAT_CLAUDE_PROVIDER_READY"]).CHAT_CLAUDE_PROVIDER_READY)
        got = {"hello": None}
        consented = threading.Event()
        stopping = threading.Event()
        def handler(c):
            got["hello"] = c.recv()
            c.send({"type": "consent.request", "request_id": "request_synthetic"})
            consented.wait(3)
        server = FakeWsServer(handler)
        self.addCleanup(server.close)
        helpers.connected_config(self.th, f"http://127.0.0.1:{server.port}")
        ks = helpers.keystore_with_secrets()
        bridge_calls = []
        def request_approval(socket_path, bridge_token, request_id, authorization):
            bridge_calls.append((socket_path, bridge_token, request_id, authorization))
            consented.set()
            stopping.set()
            return True
        env = {"MYCRM_CHAT_BRIDGE_SOCKET": "/synthetic/chat.sock",
               "MYCRM_CHAT_BRIDGE_TOKEN": "synthetic-desktop-bridge-token"}
        with patch.dict(os.environ, env), patch("agent.consent_bridge.request_approval", request_approval):
            code, out = helpers.run_cli(["--home", self.th.home, "chat"], ks_factory=lambda svc: ks,
                                        chat_kw={"stopping": stopping, "codex_factory": object(), **FAST})
        self.assertEqual(code, 0)
        self.assertEqual(got["hello"]["providers"], [])
        self.assertEqual(bridge_calls, [(env["MYCRM_CHAT_BRIDGE_SOCKET"], env["MYCRM_CHAT_BRIDGE_TOKEN"],
                                         "request_synthetic", "Bearer " + helpers.TOKEN)])
        self.assertNotIn(env["MYCRM_CHAT_BRIDGE_TOKEN"], out)
        self.assertNotIn(helpers.TOKEN, out)

    def test_consent_only_requires_bridge_and_fake_still_requires_device_token(self):
        code, out = helpers.run_cli(["--home", self.th.home, "chat", "--consent-only"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.strip()), {"event": "start", "stopped": "bridge"})
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

    def test_supervisor_stdin_stop_reaches_active_provider_in_normal_chat(self):
        class ControlInput:
            def __init__(self):
                self.ready = threading.Event()
                self.line = ""
            def readline(self):
                self.ready.wait(5)
                value, self.line = self.line, ""
                return value
            def stop(self):
                self.line = '{"command":"stop"}\n'
                self.ready.set()

        class StopAwareProvider:
            name = "fake"
            def __init__(self):
                self.started = threading.Event()
                self.stopped = threading.Event()
                self.proc = None
            def start_turn(self, text, cli_session_ref=None):
                import subprocess
                self.proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL)
                self.started.set()
                self.proc.wait(timeout=5)
                yield "error", {"code": "STOPPED"}
            def stop(self):
                if self.proc is not None and self.proc.poll() is None:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=2)
                    except Exception:
                        self.proc.kill()
                        self.proc.wait(timeout=2)
                self.stopped.set()

        provider, control = StopAwareProvider(), ControlInput()
        def handler(c):
            c.recv()
            c.send({"type": "turn.start", "session_id": "cs_1", "turn_id": "ct_control",
                    "text": "synthetic", "provider": "fake", "model": None, "binding_version": 2})
            c.recv()

        server = FakeWsServer(handler)
        self.addCleanup(server.close)
        helpers.connected_config(self.th, f"http://127.0.0.1:{server.port}")
        ks = helpers.keystore_with_secrets()
        env = patch.dict(os.environ, {"MYCRM_DESKTOP_CONTROL": "1"})
        result = {}
        def run():
            with env:
                result["value"] = helpers.run_cli(["--home", self.th.home, "chat"],
                    ks_factory=lambda svc: ks, stdin=control,
                    chat_kw={"provider": provider, **FAST})
        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        try:
            self.assertTrue(provider.started.wait(3), "synthetic turn should start before desktop stop")
            control.stop()
            worker.join(3)
            self.assertFalse(worker.is_alive(), "stdin stop should end normal chat promptly")
            self.assertTrue(provider.stopped.is_set(), "ChatAgent must stop its active provider on desktop stop")
            self.assertIsNotNone(provider.proc.poll(), "desktop stop must terminate the synthetic provider child")
            self.assertEqual(result["value"][0], 0)
        finally:
            control.stop()
            worker.join(1)
            server.close()


if __name__ == "__main__":
    unittest.main()
