"""Regression tests for chat operations requiring explicit human confirmation."""
import json
from pathlib import Path
import unittest

from chat_mcp import ChatMcpDenied, allowed_operations, validate_call


class ChatConfirmationGateTests(unittest.TestCase):
    def test_all_decide_operations_and_pc_connect_fail_closed(self):
        catalog = json.loads((Path(__file__).parent / "mcp_catalog.json").read_text())
        allowed = allowed_operations(catalog)
        blocked = [(entry["tier"], name) for name, entry in catalog["ops"].items()
                   if entry["tier"] == "decide" or name == "pc_connect"]
        self.assertEqual(len(blocked), 21)
        for tier, name in blocked:
            with self.subTest(tier=tier, name=name), self.assertRaises(ChatMcpDenied):
                validate_call(tier, name, {}, allowed)

    def test_ordinary_read_and_preview_remain_available(self):
        catalog = json.loads((Path(__file__).parent / "mcp_catalog.json").read_text())
        allowed = allowed_operations(catalog)
        validate_call("read", "state_get", {}, allowed)
        validate_call("read", "decide_preview", {"op": "trash_move", "params": {}}, allowed)

    def test_chat_write_goes_to_card_not_dispatch(self):
        """F1(2026-11-11): 자유 대화의 write 는 바로 실행되지 않고 카드(chat_write_prepare)로 간다. 강제는 _chat_mcp_execute 한 곳."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import patch
        import webchat
        from chat_mcp import AuthenticatedPrincipal, ConsentBinding, SessionBinding

        now = datetime.now(timezone.utc)
        scope = (AuthenticatedPrincipal("synthetic-user", "synthetic-device"),
                 SessionBinding("synthetic-user", "synthetic-device", "db-session", "claude", "m", "active", "grant-session"),
                 ConsentBinding("synthetic-user", "synthetic-device", "grant-session", "claude", "m",
                                now, now + timedelta(minutes=1), None))
        calls = []

        class Gateway:
            def __init__(self, **_kwargs):
                pass

            def tools(self, names):
                return tuple(names)

            def call(self, *args):
                calls.append(args)
                return {"executed": True}

        class Scope:
            def __enter__(self):
                return None

            def __exit__(self, *_exc):
                return False

        body = {"session_id": "cs_" + "a" * 24, "turn_id": "ct_" + "b" * 24, "tool": "write",
                "op": "record_add", "params": {"text": "synthetic"}, "bind": "model-supplied"}
        with patch("db.tx_scope", Scope), patch("webchat._chat_mcp_scope", return_value=scope), \
             patch("chat_mcp_gateway.ChatMcpGateway", Gateway), patch("facade.load_catalog", return_value={}), \
             patch("webchat.chat_write_prepare", return_value={"status": "pending_confirmation", "approval_id": "ca_x"}) as prepare:
            result = webchat._chat_mcp_execute({"id": "synthetic-device"}, "Bearer synthetic", body)
        self.assertEqual(result["status"], "pending_confirmation")
        prepare.assert_called_once_with("synthetic-user", "db-session", body["turn_id"], "record_add", {"text": "synthetic"})
        self.assertEqual(calls, [])

    def test_write_card_set_is_every_write_tier_except_pc_connect(self):
        import webchat
        from chat_mcp import _PINNED_TIERS
        writes = {name for name, tier in _PINNED_TIERS.items() if tier == "write"}
        self.assertEqual(webchat.CHAT_WRITE_CARD_OPS, writes - {"pc_connect"})
        self.assertEqual(len(webchat.CHAT_WRITE_CARD_OPS), 14)
        self.assertEqual(len(webchat.CHAT_CARD_OPS), 24)
        self.assertEqual(set(webchat._WRITE_LABELS), set(webchat.CHAT_WRITE_CARD_OPS))
        for op, labels in webchat._WRITE_LABELS.items():
            with self.subTest(op=op):
                self.assertEqual(len(set(labels.values())), len(labels))


if __name__ == "__main__":
    unittest.main()
