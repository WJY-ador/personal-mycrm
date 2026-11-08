import json
import threading
import unittest
from datetime import datetime, timedelta, timezone

from agent.chat_launch_authority import LaunchAuthorizationClient, LaunchAuthorizationDenied


def response_payload(**overrides):
    binding = {
        "user_id": "u-synthetic", "device_id": "d-synthetic",
        "session_id": "cs_synthetic", "turn_id": "turn_synthetic",
        "provider": "claude", "model": "claude-synthetic",
        "grant_id": "grant-synthetic", "consent_challenge_id": "challenge-synthetic",
        "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat().replace("+00:00", "Z"),
    }
    binding.update(overrides)
    return {"authorized": True, "binding": binding,
            "tools": {"mcp__my-crm__find": "read", "mcp__my-crm__write": "write"}}


class LaunchAuthorizationClientTest(unittest.TestCase):
    def client(self, **kw):
        return LaunchAuthorizationClient("https://example.invalid", lambda: "device-token", **kw)

    def test_posts_only_locator_ids_over_https_and_validates_response_binding(self):
        payload = response_payload()
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, req, timeout):
                self.req, self.timeout = req, timeout
                return Reply()
        opener = Opener()
        result = self.client(opener=opener).authorize("/api/chat/launch-authorization", "cs_synthetic", "turn_synthetic",
                                                      "claude", "claude-synthetic")
        req = opener.req
        self.assertEqual(req.full_url, "https://example.invalid/api/chat/launch-authorization")
        self.assertEqual(req.get_method(), "POST")
        self.assertEqual(req.get_header("Authorization"), "Bearer device-token")
        self.assertEqual(json.loads(req.data), {"session_id": "cs_synthetic", "turn_id": "turn_synthetic"})
        self.assertEqual(result.user_id, "u-synthetic")
        self.assertEqual(result.tools, payload["tools"])
        with self.assertRaises(TypeError):
            result.tools["mcp__my-crm__find"] = "decide"

    def test_denies_non_https_path_mismatch_expiry_and_forbidden_tools(self):
        with self.assertRaises(LaunchAuthorizationDenied):
            LaunchAuthorizationClient("http://example.invalid", lambda: "x")
        for path in ("https://evil.invalid/api/chat/launch-authorization", "/wrong", "//evil.invalid/x"):
            with self.subTest(path=path), self.assertRaises(LaunchAuthorizationDenied):
                self.client().authorize(path, "cs_synthetic", "turn_synthetic", "claude", "claude-synthetic")
        for change in (
            {"provider": "codex"},
            {"session_id": "another"},
            {"turn_id": "another-turn"},
            {"model": "another-model"},
            {"expires_at": "2000-01-01T00:00:00Z"},
        ):
            payload = response_payload(**change)
            class Reply:
                status = 200
                def read(self, *_args): return json.dumps({"authorized": True, "binding": payload,
                    "tools": {"mcp__my-crm__find": "read"}}).encode()
                def __enter__(self): return self
                def __exit__(self, *_): pass
            class Opener:
                def open(self, *_args, **_kwargs): return Reply()
            with self.assertRaises(LaunchAuthorizationDenied):
                self.client(opener=Opener()).authorize("/api/chat/launch-authorization", "cs_synthetic", "turn_synthetic",
                                                       "claude", "claude-synthetic")

    def test_denies_purge_tools(self):
        payload = response_payload()
        payload["tools"] = {"mcp__my-crm__trash_purge": "decide"}
        class Reply:
            status = 200
            def read(self, *_args): return json.dumps(payload).encode()
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, *_args, **_kwargs): return Reply()
        with self.assertRaises(LaunchAuthorizationDenied):
            self.client(opener=Opener()).authorize("/api/chat/launch-authorization", "cs_synthetic", "turn_synthetic",
                                                   "claude", "claude-synthetic")

    def test_denies_transport_failure_without_returning_partial_grant(self):
        class FailingOpener:
            def open(self, *_args, **_kwargs): raise OSError("synthetic")
        with self.assertRaises(LaunchAuthorizationDenied):
            self.client(opener=FailingOpener()).authorize("/api/chat/launch-authorization", "cs_synthetic", "turn_synthetic",
                                                           "claude", "claude-synthetic")

    def test_mcp_tool_call_carries_authorized_session_and_turn_locators(self):
        from types import MappingProxyType
        from agent.chat_launch_authority import LaunchAuthorization
        authorization = LaunchAuthorization("u-synthetic", "d-synthetic", "cs_synthetic", "turn_synthetic",
            "claude", "claude-synthetic", "grant-synthetic", "challenge-synthetic",
            (datetime.now(timezone.utc) + timedelta(seconds=10)).timestamp(),
            MappingProxyType({"mcp__my-crm__record_get": "read"}))
        class Reply:
            status = 200
            def read(self, *_args): return b'{"result":{"ok":true}}'
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, req, timeout): self.req = req; return Reply()
        opener = Opener()
        result = self.client(opener=opener).call_mcp(authorization, "read", {"record_id": "r_synthetic"},
                                                    op="record_get")
        self.assertEqual(json.loads(opener.req.data), {"session_id": "cs_synthetic", "turn_id": "turn_synthetic",
                                                       "tool": "read", "op": "record_get",
                                                       "params": {"record_id": "r_synthetic"}})
        self.assertEqual(result, {"ok": True})

    def test_mcp_call_refuses_scope_mismatch_or_invalid_shape(self):
        from types import MappingProxyType
        from agent.chat_launch_authority import LaunchAuthorization
        authorization = LaunchAuthorization("u-synthetic", "d-synthetic", "cs_synthetic", "turn_synthetic",
            "claude", "claude-synthetic", "grant-synthetic", "challenge-synthetic",
            (datetime.now(timezone.utc) + timedelta(seconds=10)).timestamp(),
            MappingProxyType({"mcp__my-crm__record_get": "read"}))
        class UnusedOpener:
            def open(self, *_args, **_kwargs): raise AssertionError("must not send")
        client = self.client(opener=UnusedOpener())
        with self.assertRaises(LaunchAuthorizationDenied):
            client.call_mcp(authorization, "read", {}, op="record_add")
        with self.assertRaises(LaunchAuthorizationDenied):
            client.call_mcp(authorization, "read", {"user_id": "u_attack"}, op="record_get")

    def test_concurrent_turn_authorizations_keep_session_and_turn_bindings_separate(self):
        barrier = threading.Barrier(2)
        class Reply:
            status = 200
            def __init__(self, data): self.data = data
            def read(self, *_args): return self.data
            def __enter__(self): return self
            def __exit__(self, *_): pass
        class Opener:
            def open(self, req, timeout):
                body = json.loads(req.data)
                barrier.wait(timeout=2)
                payload = response_payload(session_id=body["session_id"], turn_id=body["turn_id"])
                payload["binding"]["device_id"] = "device-synthetic"
                return Reply(json.dumps(payload).encode())
        client = self.client(opener=Opener())
        outcomes = {}
        def authorize(which):
            sid, tid = f"cs_synthetic_{which}", f"turn_synthetic_{which}"
            outcomes[which] = client.authorize("/api/chat/launch-authorization", sid, tid,
                                                "claude", "claude-synthetic")
        threads = [threading.Thread(target=authorize, args=(i,)) for i in (1, 2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(3)
        self.assertEqual((outcomes[1].session_id, outcomes[1].turn_id), ("cs_synthetic_1", "turn_synthetic_1"))
        self.assertEqual((outcomes[2].session_id, outcomes[2].turn_id), ("cs_synthetic_2", "turn_synthetic_2"))


if __name__ == "__main__":
    unittest.main()
