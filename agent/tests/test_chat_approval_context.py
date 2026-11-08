import unittest
import json

from agent.chat_approval_context import format_approval_outcomes, normalize_approval_outcomes


class ApprovalOutcomesContextTest(unittest.TestCase):
    def test_fixed_mycrm_instructions_exist_without_user_or_record_data(self):
        context = format_approval_outcomes(())
        self.assertIn("MyCRM", context)
        self.assertIn("mcp__my-crm", context)
        self.assertIn("사용자 지시", context)
        self.assertIn("지어내지", context)
        self.assertIn("pending_confirmation", context)
        self.assertIn("실행 성공", context)
        self.assertNotIn("record_id", context)
        self.assertNotIn("user_id", context)

    def test_accepts_only_server_approved_metadata_and_keeps_context_separate(self):
        outcome = {"id": "ca_" + "a" * 24, "op": "record_edit", "status": "confirmed"}
        normalized = normalize_approval_outcomes([outcome])
        self.assertEqual(normalized, ((outcome["id"], "record_edit", "confirmed"),))
        context = format_approval_outcomes(normalized)
        self.assertIn(outcome["id"], context)
        self.assertIn("record_edit", context)
        self.assertIn("confirmed", context)
        payload = json.loads(context.splitlines()[-1])
        self.assertEqual(payload, [outcome])
        self.assertEqual(set(payload[0]), {"id", "op", "status"})

    def test_rejects_invalid_and_duplicate_ids_and_more_than_one_hundred(self):
        valid = {"id": "ca_" + "b" * 24, "op": "trash_restore", "status": "cancelled"}
        for invalid in (
            {**valid, "unexpected": "x"},
            {**valid, "id": "not-server-generated"},
            {**valid, "op": "unknown_op"},
            {**valid, "status": "pending"},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                normalize_approval_outcomes([invalid])
        with self.assertRaises(ValueError):
            normalize_approval_outcomes([valid, valid])
        with self.assertRaises(ValueError):
            normalize_approval_outcomes([valid] * 101)


if __name__ == "__main__":
    unittest.main()
