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

    def test_ordinary_read_write_and_preview_remain_available(self):
        catalog = json.loads((Path(__file__).parent / "mcp_catalog.json").read_text())
        allowed = allowed_operations(catalog)
        validate_call("read", "state_get", {}, allowed)
        validate_call("write", "record_add", {"text": "synthetic"}, allowed)
        validate_call("read", "decide_preview", {"op": "trash_move", "params": {}}, allowed)


if __name__ == "__main__":
    unittest.main()
