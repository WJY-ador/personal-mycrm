"""Tests for the disabled Codex app-server tool relay candidate."""
import json
import io
import subprocess
import sys
import unittest
from types import MappingProxyType
from datetime import datetime, timezone

from agent.chat_launch_authority import LaunchAuthorization
from agent.chat_mcp_bridge import McpStdioBridge
from agent.chat_codex_dynamic import DynamicToolRelay, DynamicRequestDispatcher, AppServerTurn, JsonRpcTransport


class SyntheticClient:
    def __init__(self):
        self.calls = []
        self.enabled = True
        self.auth = LaunchAuthorization(
            user_id="u1", device_id="d1", session_id="s1", turn_id="t1",
            provider="codex", model="synthetic", grant_id="g1",
            consent_challenge_id="c1", expires_at=datetime.now(timezone.utc).timestamp()+60,
            tools=MappingProxyType({"mcp__my-crm__find": "read",
                "mcp__my-crm__record_get": "read",
                "mcp__my-crm__candidate_decide": "decide"}))

    def authorize(self, *args):
        if not self.enabled:
            raise RuntimeError("revoked")
        return self.auth

    def call_mcp(self, auth, surface, params, *, op=None, bind=""):
        self.calls.append((surface, op, params, bind))
        return {"pending_confirmation": True} if surface == "decide" else {"synthetic": True}


class DynamicToolRelayTest(unittest.TestCase):
    def setUp(self):
        self.client = SyntheticClient()
        self.bridge = McpStdioBridge(self.client, "/api/chat/launch-authorization", "s1", "t1",
                                     "codex", "synthetic", "d1")
        self.relay = DynamicToolRelay(self.bridge)

    def test_tools_are_scoped_to_server_grant_without_purge(self):
        names = [tool["name"] for tool in self.relay.tools()]
        self.assertEqual(names, ["mycrm_find", "mycrm_read", "mycrm_decide"])
        self.assertNotIn("mycrm_write", names)
        self.assertNotIn("purge", repr(names))
        decide = self.relay.tools()[-1]
        self.assertIn("확인 카드", decide["description"])
        self.assertNotIn("사용자가 말한 뒤에만", decide["description"])

    def test_decide_only_relays_to_authorized_bridge_and_returns_pending(self):
        result = self.relay.call("mycrm_decide", {"op":"candidate_decide", "params":{}, "bind":"abc"})
        self.assertTrue(result["success"])
        self.assertEqual(json.loads(result["contentItems"][0]["text"]), {"pending_confirmation": True})
        self.assertEqual(self.client.calls, [("decide", "candidate_decide", {}, "abc")])

    def test_unlisted_tool_and_scope_are_denied(self):
        self.assertFalse(self.relay.call("mycrm_write", {"op":"record_add"})["success"])
        self.assertFalse(self.relay.call("mycrm_decide", {"op":"trash_purge"})["success"])
        self.assertFalse(self.relay.call("shell", {})["success"])
        self.assertFalse(self.relay.call(["mycrm_read"], {})["success"])
        self.assertFalse(self.relay.call("mycrm_read", {"op":"record_get", "session_id":"other"})["success"])
        self.assertEqual(self.client.calls, [])

    def test_revoked_consent_rejects_future_calls(self):
        self.relay.tools()
        self.client.enabled = False
        self.assertFalse(self.relay.call("mycrm_read", {"op":"record_get"})["success"])
        self.assertEqual(self.client.calls, [])

    def test_dispatch_rejects_wrong_thread_or_turn_without_calling_bridge(self):
        dispatcher = DynamicRequestDispatcher(self.relay, "thread-1", "turn-1")
        for key in ("threadId", "turnId"):
            params = {"threadId":"thread-1", "turnId":"turn-1", "callId":"call-1",
                      "tool":"mycrm_read", "arguments":{"op":"record_get"}}
            params[key] = "other"
            response = dispatcher.dispatch({"id":1,"method":"item/tool/call","params":params})
            self.assertFalse(response["result"]["success"])
        self.assertEqual(self.client.calls, [])

    def test_dispatch_rejects_duplicate_call_and_unrelated_server_request(self):
        dispatcher = DynamicRequestDispatcher(self.relay, "thread-1", "turn-1")
        message = {"id": 1, "method":"item/tool/call", "params": {"threadId":"thread-1",
                   "turnId":"turn-1", "callId":"call-1", "tool":"mycrm_read",
                   "arguments":{"op":"record_get"}}}
        self.assertTrue(dispatcher.dispatch(message)["result"]["success"])
        message["id"] = 2
        self.assertFalse(dispatcher.dispatch(message)["result"]["success"])
        with self.assertRaises(ValueError):
            dispatcher.dispatch({"id":3,"method":"item/commandExecution/requestApproval","params":{}})
        self.assertEqual(len(self.client.calls), 1)

    def test_app_server_turn_routes_tool_calls_and_emits_model_text(self):
        thread = "11111111-1111-4111-8111-111111111111"
        turn = "22222222-2222-4222-8222-222222222222"
        transport = SyntheticTransport([
            {"id":1,"result":{}},
            {"id":2,"result":{"thread":{"id":thread}}},
            {"id":3,"result":{"turn":{"id":turn}}},
            {"id":10,"method":"item/tool/call", "params":{"threadId":thread,"turnId":turn,
                "callId":"one","tool":"mycrm_read","arguments":{"op":"record_get"}}},
            {"method":"item/completed","params":{"threadId":thread,"turnId":turn,
                "item":{"type":"agentMessage","text":"synthetic response"}}},
            {"method":"turn/completed","params":{"threadId":thread,
                "turn":{"id":turn,"status":"completed"}}},
        ])
        runner = AppServerTurn(transport, self.relay, lambda: True, timeout=3)
        events = list(runner.run(model="synthetic", cwd="/synthetic", text="hello"))
        self.assertEqual(events, [("session_ref", {"cli_session_ref":thread}),
                                  ("delta", {"text":"synthetic response"}), ("done", {})])
        self.assertEqual(self.client.calls[0][:2], ("read", "record_get"))
        tool_response = next(m for m in transport.sent if m.get("id") == 10)
        self.assertTrue(tool_response["result"]["success"])

    def test_app_server_turn_fails_closed_for_other_server_requests(self):
        thread = "11111111-1111-4111-8111-111111111111"
        turn = "22222222-2222-4222-8222-222222222222"
        transport = SyntheticTransport([{"id":1,"result":{}}, {"id":2,"result":{"thread":{"id":thread}}},
            {"id":3,"result":{"turn":{"id":turn}}},
            {"id":9,"method":"item/commandExecution/requestApproval","params":{}}])
        runner = AppServerTurn(transport, self.relay, lambda: True, timeout=3)
        with self.assertRaises(ValueError):
            list(runner.run(model="synthetic", cwd="/synthetic", text="hello"))
        self.assertEqual(self.client.calls, [])

    def test_transport_poll_timeout_rechecks_consent_before_failing(self):
        class PollTimeoutTransport:
            def send(self, message):
                pass

            def receive(self, timeout):
                raise TimeoutError()

        checks = iter((True, True, False))
        runner = AppServerTurn(PollTimeoutTransport(), self.relay, lambda: next(checks), timeout=3)
        with self.assertRaisesRegex(ValueError, "consent-revoked"):
            list(runner.run(model="synthetic", cwd="/synthetic", text="hello"))


class SyntheticTransport:
    def __init__(self, events):
        self.events, self.sent = list(events), []

    def send(self, message):
        self.sent.append(message)

    def receive(self, timeout):
        if not self.events:
            raise TimeoutError
        return self.events.pop(0)


class JsonRpcTransportTest(unittest.TestCase):
    def test_writes_one_json_line_and_reads_one_message(self):
        writer = io.BytesIO()
        transport = JsonRpcTransport(io.BytesIO(b'{"id":1,"result":{}}\n'), writer)
        transport.send({"id": 1, "method": "initialize"})
        self.assertEqual(json.loads(writer.getvalue()), {"id": 1, "method": "initialize"})
        self.assertEqual(transport.receive(1), {"id": 1, "result": {}})

    def test_rejects_oversized_inbound_messages(self):
        transport = JsonRpcTransport(io.BytesIO(b'x' * (2 * 1024 * 1024) + b'\n'), io.BytesIO())
        with self.assertRaises(ValueError):
            transport.receive(1)

    def test_exchange_over_real_subprocess_pipes(self):
        child = subprocess.Popen([sys.executable, '-u', '-c',
            'import json,sys; x=json.loads(sys.stdin.readline()); '
            'print(json.dumps({"id":x["id"],"result":{"ok":True}}),flush=True)'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        try:
            transport = JsonRpcTransport(child.stdout, child.stdin)
            transport.send({"id": 7, "method": "initialize"})
            self.assertEqual(transport.receive(3), {"id": 7, "result": {"ok": True}})
            self.assertEqual(child.wait(timeout=3), 0)
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            child.stdin.close()
            child.stdout.close()


if __name__ == "__main__":
    unittest.main()
