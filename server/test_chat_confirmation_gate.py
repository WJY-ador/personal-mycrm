"""Regression tests for chat operations requiring explicit human confirmation."""
import json
from pathlib import Path
import unittest

from chat_mcp import ChatMcpDenied, allowed_operations, validate_call


class ChatConfirmationGateTests(unittest.TestCase):
    def test_all_decide_purge_operations_and_pc_connect_fail_closed(self):
        """AI 하나로 A3: decide, purge 는 대화 도구 목록에 들지만 바로 실행(validate_call)은 계속 막힌다. 실행은 확인 카드뿐."""
        catalog = json.loads((Path(__file__).parent / "mcp_catalog.json").read_text())
        allowed = allowed_operations(catalog)
        blocked = [(entry["tier"], name) for name, entry in catalog["ops"].items()
                   if entry["tier"] in ("decide", "purge") or name == "pc_connect"]
        self.assertEqual(len(blocked), 22)
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

    def test_chat_decide_and_purge_go_to_card_not_dispatch(self):
        """AI 하나로 A3: decide, purge 겉면은 어떤 op 이든 approval_prepare(카드)로만 간다. 모델 bind 는 넘기지 않는다."""
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

        for tool, op in (("decide", "definition_apply"), ("decide", "migration_apply"), ("decide", "token_revoke"),
                         ("purge", "trash_purge"), ("decide", "trash_purge"), ("purge", "trash_move")):
            body = {"session_id": "cs_" + "a" * 24, "turn_id": "ct_" + "b" * 24, "tool": tool,
                    "op": op, "params": {"x": 1}, "bind": "model-supplied"}
            with self.subTest(tool=tool, op=op), patch("db.tx_scope", Scope), \
                 patch("webchat._chat_mcp_scope", return_value=scope), \
                 patch("chat_mcp_gateway.ChatMcpGateway", Gateway), patch("facade.load_catalog", return_value={}), \
                 patch("webchat.approval_prepare", return_value={"status": "pending_confirmation", "approval_id": "ca_x"}) as prepare:
                result = webchat._chat_mcp_execute({"id": "synthetic-device"}, "Bearer synthetic", body)
                self.assertEqual(result["status"], "pending_confirmation")
                prepare.assert_called_once_with("synthetic-user", "db-session", body["turn_id"], op, {"x": 1}, surface=tool)
        self.assertEqual(calls, [])

    def test_card_surface_must_match_tier(self):
        """AI 하나로 A3: 겉면과 등급이 다르면(purge 겉면의 trash_move, decide 겉면의 trash_purge) 카드를 만들지 않는다."""
        from types import SimpleNamespace
        from unittest.mock import patch
        import facade
        import webchat
        fake = {name: SimpleNamespace(tier=tier, bind="self" if name.startswith("migration_") and tier == "decide" else
                                      ("hmac" if tier in ("decide", "purge") else None))
                for name, tier in __import__("chat_mcp")._PINNED_TIERS.items()}
        with patch.dict(facade.OPS, fake, clear=True):
            self._surface_checks(webchat)

    def _surface_checks(self, webchat):
        for op, surface in (("trash_move", "purge"), ("trash_purge", "decide"), ("record_add", "decide"),
                            ("pc_connect", "decide"), ("state_get", "decide")):
            with self.subTest(op=op, surface=surface), self.assertRaises(Exception) as error:
                webchat._decide_spec(op, surface)
            self.assertEqual(error.exception.code, "APPROVAL-CLOSED")
        self.assertEqual(webchat._decide_spec("trash_purge", "purge").tier, "purge")
        self.assertEqual(webchat._decide_spec("migration_cancel", "decide").bind, "self")

    def test_write_card_set_is_every_write_tier_except_pc_connect(self):
        import webchat
        from chat_mcp import _PINNED_TIERS
        writes = {name for name, tier in _PINNED_TIERS.items() if tier == "write"}
        self.assertEqual(webchat.CHAT_WRITE_CARD_OPS, writes - {"pc_connect"})
        self.assertEqual(len(webchat.CHAT_WRITE_CARD_OPS), 15)
        decides = {name for name, tier in _PINNED_TIERS.items() if tier in ("decide", "purge")}
        self.assertEqual(webchat.CHAT_APPROVABLE_OPS, decides)   # AI 하나로 A3: decide 20 + purge 1
        self.assertEqual(len(webchat.CHAT_APPROVABLE_OPS), 21)
        self.assertEqual(len(webchat.CHAT_CARD_OPS), 36)
        # A5: 늘 되돌릴 수 없음으로 보는 op 은 모두 카드 대상이다
        self.assertLessEqual(webchat.CHAT_IRREVERSIBLE_OPS, webchat.CHAT_APPROVABLE_OPS)
        self.assertEqual(webchat.CHAT_IRREVERSIBLE_OPS, {"trash_purge", "token_revoke", "pc_forget", "migration_token_send",
                                                         "feedback_send", "migration_cancel"})
        self.assertEqual(set(webchat._WRITE_LABELS), set(webchat.CHAT_WRITE_CARD_OPS))
        for op, labels in webchat._WRITE_LABELS.items():
            with self.subTest(op=op):
                self.assertEqual(len(set(labels.values())), len(labels))
        # I R3(2026-11-11): every write card op is classified once — overwrite (current-state reader) or create only
        self.assertEqual(set(webchat._WRITE_CURRENT) | webchat._WRITE_CREATE_ONLY, set(webchat.CHAT_WRITE_CARD_OPS))
        self.assertFalse(set(webchat._WRITE_CURRENT) & webchat._WRITE_CREATE_ONLY)
        self.assertEqual(webchat._WRITE_CREATE_ONLY, {"question_add", "record_add", "candidates_propose", "source_create"})

    def test_unclassified_write_op_makes_no_card(self):
        """I R3: a write op with no current-state reader is not treated as a create; it is refused (fail closed)."""
        import webchat
        with self.assertRaises(Exception) as error:
            webchat._write_current(None, "synthetic-user", "synthetic_new_write_op", {})
        self.assertEqual(error.exception.code, "APPROVAL-CLOSED")

    def test_chat_routes_use_their_own_rate_buckets(self):
        """I R4: launch-authorization and /api/chat/mcp count chat buckets, not the import request bucket."""
        import inspect
        import webchat
        self.assertEqual(webchat.CHAT_RATE_LIMITS, {"chat_launch": 60, "chat_mcp": 60})
        for name, bucket in (("launch_authorization", "chat_launch"), ("chat_mcp", "chat_mcp")):
            src = inspect.getsource(getattr(webchat.Routes, name))
            self.assertNotIn("imports._rate", src)
            self.assertIn(f'_chat_rate, dev, "{bucket}"', src)


if __name__ == "__main__":
    unittest.main()
