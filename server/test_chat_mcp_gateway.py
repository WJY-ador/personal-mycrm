"""Synthetic gateway tests; no credentials, DB, provider, or live server."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from chat_mcp import AuthenticatedPrincipal, ChatMcpDenied, ConsentBinding, SessionBinding
from chat_mcp_gateway import (
    ATOMIC_DISPATCH_READY, ChatMcpGateway, TrustedChatPrincipal,
    _mint_trusted_principal, route_enabled, trusted_principal_uid,
)


class ChatMcpGatewayTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.principal = AuthenticatedPrincipal("synthetic-user", "synthetic-device")
        self.session = SessionBinding("synthetic-user", "synthetic-device", "synthetic-session",
                                      "claude", "synthetic-model", "active")
        self.consent = ConsentBinding("synthetic-user", "synthetic-device", "synthetic-session",
                                      "claude", "synthetic-model", self.now,
                                      self.now + timedelta(minutes=2), None)
        self.catalog = json.loads((Path(__file__).parent / "mcp_catalog.json").read_text())
        self.context = object()
        self.trusted = _mint_trusted_principal(user_id="synthetic-user", device_id="synthetic-device",
                                               session_id="synthetic-session", provider="claude",
                                               model="synthetic-model", expires_at=self.now + timedelta(minutes=2))

    def make_gateway(self):
        return ChatMcpGateway(principal=self.principal, session=self.session,
                              consent=self.consent, context=self.context,
                              catalog=self.catalog)

    def test_context_uid_must_match_authenticated_scope_before_dispatch(self):
        dispatch = unittest.mock.Mock()
        fake = SimpleNamespace(uid_of=lambda _ctx: "other-user", dispatch=dispatch)
        with patch("chat_mcp_gateway._facade", return_value=fake):
            with self.assertRaises(RuntimeError):
                self.make_gateway()
            dispatch.assert_not_called()

    def test_call_uses_real_facade_dispatch_with_the_checked_context(self):
        expected = {"ok": True}
        dispatch = unittest.mock.Mock(return_value=expected)
        fake = SimpleNamespace(uid_of=lambda _ctx: "synthetic-user", dispatch_trusted=dispatch,
                               load_catalog=lambda: self.catalog)
        with patch("chat_mcp_gateway._facade", return_value=fake):
            result = self.make_gateway().call("write", "question_add", {"text": "synthetic"})
        self.assertIs(result, expected)
        dispatch.assert_called_once_with("write", "question_add", {"text": "synthetic"}, self.context, "")

    def test_trusted_route_uses_explicit_dispatch_boundary(self):
        expected = {"ok": True}
        dispatch = unittest.mock.Mock(return_value=expected)
        fake = SimpleNamespace(uid_of=lambda _ctx: "synthetic-user", dispatch_trusted=dispatch,
                               load_catalog=lambda: self.catalog)
        with patch("chat_mcp_gateway._facade", return_value=fake):
            result = ChatMcpGateway.call_trusted(self.trusted, "write", "question_add", {"text": "synthetic"})
        self.assertIs(result, expected)
        dispatch.assert_called_once_with("write", "question_add", {"text": "synthetic"}, self.trusted, "")

    def test_trusted_principal_cannot_be_forged_or_mutated(self):
        with self.assertRaises(TypeError):
            TrustedChatPrincipal(object(), user_id="other-user", device_id="synthetic-device",
                                 session_id="synthetic-session", provider="claude",
                                 model="synthetic-model", expires_at=self.now + timedelta(minutes=1))
        with self.assertRaises(AttributeError):
            self.trusted.user_id = "other-user"
        self.assertEqual(trusted_principal_uid(self.trusted), "synthetic-user")

    def test_http_route_needs_both_switches(self):
        # 2026-11-12 K: gate on. The route still needs CRM_WEBCHAT_ENABLED and CRM_CHAT_MCP_ENABLED.
        self.assertTrue(ATOMIC_DISPATCH_READY)
        self.assertFalse(route_enabled(True, False))
        self.assertTrue(route_enabled(True, True))
        self.assertFalse(route_enabled(False, True))
        self.assertFalse(route_enabled(False, False))

    def test_expired_trusted_principal_and_invalid_scope_never_dispatch(self):
        expired = _mint_trusted_principal(user_id="synthetic-user", device_id="synthetic-device",
                                          session_id="synthetic-session", provider="claude",
                                          model="synthetic-model", expires_at=self.now - timedelta(seconds=1))
        with patch("chat_mcp_gateway._facade") as facade_mock:
            with self.assertRaises(RuntimeError):
                ChatMcpGateway.call_trusted(expired, "read", "state_get", {})
            facade_mock.assert_not_called()

    def test_purge_is_never_dispatched(self):
        dispatch = unittest.mock.Mock()
        fake = SimpleNamespace(uid_of=lambda _ctx: "synthetic-user", dispatch=dispatch)
        with patch("chat_mcp_gateway._facade", return_value=fake):
            with self.assertRaises(ChatMcpDenied):
                self.make_gateway().call("purge", "trash_purge", {})
            dispatch.assert_not_called()

    def test_identity_arguments_and_unknown_surfaces_never_dispatch(self):
        dispatch = unittest.mock.Mock()
        fake = SimpleNamespace(uid_of=lambda _ctx: "synthetic-user", dispatch_trusted=dispatch,
                               load_catalog=lambda: self.catalog)
        with patch("chat_mcp_gateway._facade", return_value=fake):
            with self.assertRaises(ChatMcpDenied):
                ChatMcpGateway.call_trusted(self.trusted, "read", "state_get", {"uid": "other-user"})
            with self.assertRaises(ChatMcpDenied):
                ChatMcpGateway.call_trusted(self.trusted, "purge", "trash_purge", {})
            dispatch.assert_not_called()

    def test_catalog_drift_denies_gateway_construction(self):
        bad_catalog = json.loads(json.dumps(self.catalog))
        bad_catalog["ops"]["trash_purge"]["tier"] = "decide"
        fake = SimpleNamespace(uid_of=lambda _ctx: "synthetic-user")
        with patch("chat_mcp_gateway._facade", return_value=fake):
            with self.assertRaises(ChatMcpDenied):
                ChatMcpGateway(principal=self.principal, session=self.session,
                               consent=self.consent, context=self.context,
                               catalog=bad_catalog)


if __name__ == "__main__":
    unittest.main()
