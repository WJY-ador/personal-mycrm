"""Synthetic HTTP gateway tests; no PostgreSQL, credentials, or provider."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
import threading
import unittest
from unittest.mock import patch

import db
import facade
import webchat
from chat_mcp import AuthenticatedPrincipal, ConsentBinding, SessionBinding
from chat_mcp import ChatMcpDenied
from chat_mcp_gateway import _mint_trusted_principal
from test_db_tx_scope import FakeConnection, FakePool


class Request:
    def __init__(self, body, content_type="application/json", authorization="Bearer synthetic"):
        self._body = body
        self.headers = {"content-type": content_type, "authorization": authorization}

    async def body(self):
        return self._body


class ChatMcpRouteTests(unittest.TestCase):
    session_id = "cs_" + "a" * 24
    turn_id = "ct_" + "b" * 24

    def test_route_remains_off_even_with_both_switches_until_review(self):
        with patch("webchat.enabled", return_value=True), patch("webchat.env", return_value=""):
            self.assertFalse(webchat.chat_mcp_enabled())
        with patch("webchat.enabled", return_value=False), patch("webchat.env", return_value="1"):
            self.assertFalse(webchat.chat_mcp_enabled())
        with patch("webchat.enabled", return_value=True), patch("webchat.env", return_value="1"):
            self.assertFalse(webchat.chat_mcp_enabled())

    def test_body_rejects_duplicates_unknown_identity_and_purge(self):
        cases = (
            b'{"tool":"read","op":"state_get","params":{},"uid":"other"}',
            b'{"tool":"read","op":"state_get","op":"other","params":{}}',
            b'{"tool":"purge","op":"trash_purge","params":{}}',
            b'{"tool":"read","op":"state_get","params":{},"bind":"x","extra":1}',
        )
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(db.CrmError):
                asyncio.run(webchat.Routes._chat_mcp_body(Request(raw)))

    def test_list_and_find_bodies_have_narrow_shapes(self):
        ids = f'"session_id":"{self.session_id}","turn_id":"{self.turn_id}"'
        listing = asyncio.run(webchat.Routes._chat_mcp_body(Request(('{' + ids + ',"tool":"list","params":{}}').encode())))
        self.assertEqual(listing["tool"], "list")
        find = asyncio.run(webchat.Routes._chat_mcp_body(Request(('{' + ids + ',"tool":"find","params":{"query":"record"}}').encode())))
        self.assertEqual(find["params"], {"query": "record"})
        with self.assertRaises(db.CrmError):
            asyncio.run(webchat.Routes._chat_mcp_body(Request(('{' + ids + ',"tool":"find","params":{"uid":"x"}}').encode())))

    def test_route_scope_and_guarded_dispatch_share_one_outer_connection(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        now = datetime.now(timezone.utc)
        identity = AuthenticatedPrincipal("synthetic-user", "synthetic-device")
        session = SessionBinding("synthetic-user", "synthetic-device", "db-session", "claude", "m", "active", "grant-session")
        consent = ConsentBinding("synthetic-user", "synthetic-device", "grant-session", "claude", "m",
                                 now, now + timedelta(minutes=1), None)
        seen = []

        def scope(_dev, _authorization, _session_id, _turn_id):
            with db.tx() as c:
                seen.append(("scope", c))
            return identity, session, consent

        class FakeGateway:
            def __init__(self, **_kwargs):
                with db.tx() as c:
                    seen.append(("gateway", c))

            def tools(self, names):
                return tuple(name for name in names if name in ("find", "read", "write", "decide"))

            def call(self, *_args):
                with db.tx() as c:
                    seen.append(("dispatch", c))
                return {"synthetic": True}

        body = {"session_id": self.session_id, "turn_id": self.turn_id,
                "tool": "write", "op": "question_add", "params": {"text": "synthetic"}}
        with patch("db.pool", return_value=pool), patch("webchat._chat_mcp_scope", side_effect=scope), \
             patch("chat_mcp_gateway.ChatMcpGateway", FakeGateway):
            result = webchat._chat_mcp_execute({"id": "synthetic-device"}, "Bearer synthetic", body)
        self.assertEqual(result, {"synthetic": True})
        self.assertEqual(pool.opens, 1)
        self.assertEqual([kind for kind, _conn in seen], ["scope", "gateway", "dispatch"])
        self.assertTrue(all(conn is connection for _kind, conn in seen))
        self.assertEqual([event[0] for event in connection.events].count("commit"), 4)

    def test_dispatch_failure_aborts_outer_scope(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        now = datetime.now(timezone.utc)
        identity = AuthenticatedPrincipal("synthetic-user", "synthetic-device")
        session = SessionBinding("synthetic-user", "synthetic-device", "db-session", "claude", "m", "active", "grant-session")
        consent = ConsentBinding("synthetic-user", "synthetic-device", "grant-session", "claude", "m",
                                 now, now + timedelta(minutes=1), None)

        def scope(_dev, _authorization, _session_id, _turn_id):
            with db.tx() as c:
                self.assertIs(c, connection)
            return identity, session, consent

        class FailingGateway:
            def __init__(self, **_kwargs):
                pass

            def tools(self, names):
                return tuple(names)

            def call(self, *_args):
                with db.tx():
                    raise RuntimeError("synthetic failure")

        with patch("db.pool", return_value=pool), patch("webchat._chat_mcp_scope", side_effect=scope), \
             patch("chat_mcp_gateway.ChatMcpGateway", FailingGateway):
            with self.assertRaises(RuntimeError):
                webchat._chat_mcp_execute({"id": "synthetic-device"}, "Bearer synthetic",
                                          {"session_id": self.session_id, "turn_id": self.turn_id,
                                           "tool": "write", "op": "question_add", "params": {"text": "x"}})
        self.assertEqual(connection.events[-1][0], "rollback")

    def test_facade_trusted_path_blocks_unconfirmed_decide_and_purge(self):
        trusted = _mint_trusted_principal(
            user_id="synthetic-user", device_id="synthetic-device", session_id="db-session",
            provider="claude", model="synthetic-model",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=1),
        )
        with patch("facade.dispatch", return_value={"ok": True}) as dispatch:
            with self.assertRaises(ChatMcpDenied):
                facade.dispatch_trusted(
                    "decide", "trash_move", {"kind": "record", "target_id": "r_synthetic"},
                    trusted, "synthetic-bind",
                )
            with self.assertRaises(ChatMcpDenied):
                facade.dispatch_trusted("purge", "trash_purge", {}, trusted)
            dispatch.assert_not_called()

    def test_facade_trusted_path_rejects_caller_created_identity(self):
        forged = object()
        with patch("facade.dispatch") as dispatch:
            with self.assertRaises(db.CrmError):
                facade.dispatch_trusted("read", "state_get", {}, forged)
            dispatch.assert_not_called()

    def test_concurrent_requests_cannot_reach_dispatch_while_route_is_off(self):
        route = webchat.Routes(None, lambda name, handler: handler)
        request = Request((f'{{"session_id":"{self.session_id}","turn_id":"{self.turn_id}",'
                           '"tool":"list","params":{}}').encode())
        called = []
        with patch("webchat.chat_mcp_enabled", return_value=False), \
             patch.object(route, "_auth", side_effect=lambda _auth: called.append("auth")):
            responses = []
            threads = [threading.Thread(target=lambda: responses.append(asyncio.run(route.chat_mcp(request)))) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual(len(responses), 2)
        self.assertTrue(all(response.status_code == 503 for response in responses))
        self.assertEqual(called, [])
        self.assertNotIn(b"synthetic", responses[0].body)


if __name__ == "__main__":
    unittest.main()
