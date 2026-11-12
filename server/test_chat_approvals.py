"""Synthetic PostgreSQL tests for human-confirmed chat operations.

Only runs with an explicitly specified local crm_test database.
"""
import os
import concurrent.futures
import threading
import urllib.parse
import unittest
from unittest.mock import patch

url = urllib.parse.urlsplit(os.environ.get("DATABASE_URL", ""))
if url.hostname not in ("localhost", "127.0.0.1", "::1") or not url.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("A local crm_test DATABASE_URL is required")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_SESSION_SECRET"] = "synthetic-approval-only-secret"

import db
import main  # installs the real facade catalog and guarded operations
import webchat


class ChatApprovalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_schema()

    @classmethod
    def tearDownClass(cls):
        db.close()

    def setUp(self):
        self.uid = db.user_by_email("synthetic-chat-approval@example.invalid")["id"]
        self.other = db.user_by_email("synthetic-chat-other@example.invalid")["id"]
        db.display_name_set(self.uid, "Synthetic")
        self.sid = webchat._id("cs")
        self.tid = webchat._id("ct")
        with db.tx() as c:
            c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version) "
                      "VALUES (%s,%s,'synthetic-device','codex','synthetic-model','synthetic-client',2)",
                      (self.sid, self.uid))
            c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,'synthetic-turn')",
                      (self.tid, self.sid))
        self.record = db.record_add(self.uid, "Synthetic record", "before synthetic after")
        self.params = {"record_id": self.record["id"], "expected_revision": 1,
                       "old": "before", "new": "changed"}
        self.consent = patch("webchat._require_consumed_session_consent")
        self.consent.start()
        self.enabled = patch("webchat.chat_mcp_enabled", return_value=True)
        self.enabled.start()

    def tearDown(self):
        self.consent.stop()
        self.enabled.stop()
        db.user_delete(self.uid)
        db.user_delete(self.other)

    def prepare(self):
        return webchat.approval_prepare(self.uid, self.sid, self.tid, "record_edit", self.params)

    def test_confirm_applies_only_once_and_denies_cross_user(self):
        request = self.prepare()
        self.assertEqual(request["status"], "pending_confirmation")
        approval_id = request["approval_id"]
        listed = webchat.approvals_list(self.uid, self.sid)
        self.assertEqual(listed[0]["params"], self.params)
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.other, self.sid, approval_id)
        result = webchat.approval_confirm(self.uid, self.sid, approval_id)
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "changed synthetic after")
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.uid, self.sid, approval_id)
        completed = webchat.approvals_list(self.uid, self.sid)
        self.assertEqual(completed[0]["status"], "confirmed")
        self.assertEqual(completed[0]["result"], result["result"])
        self.assertIsNotNone(completed[0]["finished_at"])

    def test_changed_record_and_revoked_consent_never_apply(self):
        request = self.prepare()
        db.record_title_set(self.uid, self.record["id"], "Changed title", 1)
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.uid, self.sid, request["approval_id"])
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")
        self.params["expected_revision"] = 2
        request = self.prepare()
        with patch("webchat._require_consumed_session_consent", side_effect=db.CrmError("CONSENT_REQUIRED", "revoked")):
            with self.assertRaises(db.CrmError):
                webchat.approval_confirm(self.uid, self.sid, request["approval_id"])
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")

    def test_parallel_confirmation_executes_once(self):
        approval_id = self.prepare()["approval_id"]
        barrier = threading.Barrier(2)
        def confirm():
            barrier.wait()
            try:
                return webchat.approval_confirm(self.uid, self.sid, approval_id)["status"]
            except db.CrmError as error:
                return error.code
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(lambda _: confirm(), range(2)))
        self.assertCountEqual(outcomes, ["confirmed", "APPROVAL-CLOSED"])
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "changed synthetic after")

    def test_changed_visible_preview_is_stale_even_if_bind_matches(self):
        approval_id = self.prepare()["approval_id"]
        import facade
        actual_preview = facade.preview
        def changed_preview(*args, **kwargs):
            preview = actual_preview(*args, **kwargs)
            preview["shown"]["기록"] = "changed display only"
            return preview
        with patch("facade.preview", side_effect=changed_preview):
            with self.assertRaises(db.CrmError) as error:
                webchat.approval_confirm(self.uid, self.sid, approval_id)
        self.assertEqual(error.exception.code, "APPROVAL-STALE")
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")

    def test_irreversible_card_needs_second_confirmation_and_preview_change_is_stale(self):
        """AI 하나로 A5: 되돌릴 수 없는 미리보기는 카드가 되고(표시 irreversible), 두 번째 확인(irreversible_ack) 없이는 실행하지 않는다.
        되돌릴 수 있게 만든 카드가 확정 때 되돌릴 수 없게 바뀌면 APPROVAL-STALE 이다."""
        import facade
        approval_id = self.prepare()["approval_id"]
        actual_preview = facade.preview
        def irreversible(*args, **kwargs):
            preview = actual_preview(*args, **kwargs)
            preview["irreversible"] = True
            return preview
        with patch("facade.preview", side_effect=irreversible):
            with self.assertRaises(db.CrmError) as stale:
                webchat.approval_confirm(self.uid, self.sid, approval_id)
            self.assertEqual(stale.exception.code, "APPROVAL-STALE")
            hard = self.prepare()["approval_id"]
            self.assertTrue([a for a in webchat.approvals_list(self.uid, self.sid) if a["id"] == hard][0]["irreversible"])
            for ack in (False, None, 1, "true"):
                with self.subTest(ack=ack), self.assertRaises(db.CrmError) as again:
                    webchat.approval_confirm(self.uid, self.sid, hard, irreversible_ack=ack)
                self.assertEqual(again.exception.code, "APPROVAL-CONFIRM-AGAIN")
            self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")
            self.assertEqual([a for a in webchat.approvals_list(self.uid, self.sid) if a["id"] == hard][0]["status"], "pending")
            self.assertEqual(webchat.approval_confirm(self.uid, self.sid, hard, irreversible_ack=True)["status"], "confirmed")
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "changed synthetic after")

    def test_fixed_irreversible_ops_need_second_confirmation_even_if_preview_says_reversible(self):
        """AI 하나로 A5: pc_forget, migration_token_send, token_revoke, feedback_send 는 facade 미리보기가 irreversible=False 여도
        카드는 되돌릴 수 없음이고, 두 번째 확인 없이는 dispatch 에 닿지 않는다."""
        import facade
        params = {"pc_forget": {"installation_id": "di_synthetic"}, "migration_token_send": {"installation_id": "di_synthetic"},
                  "token_revoke": {"kind": "device", "id": "is_synthetic"}, "feedback_send": {"kind": "bug", "text": "synthetic"}}
        def reversible(op, norm, uid):
            return {"op": op, "shown": {"대상": "synthetic"}, "impact": {}, "irreversible": False, "bind": "B" * 16}
        dispatched = []
        with patch("facade.preview", side_effect=reversible), \
             patch("facade.dispatch", side_effect=lambda *a, **k: dispatched.append(a) or None):
            for op, p in params.items():
                with self.subTest(op=op):
                    aid = webchat.approval_prepare(self.uid, self.sid, self.tid, op, p)["approval_id"]
                    card = [a for a in webchat.approvals_list(self.uid, self.sid) if a["id"] == aid][0]
                    self.assertTrue(card["irreversible"])
                    with self.assertRaises(db.CrmError) as again:
                        webchat.approval_confirm(self.uid, self.sid, aid)
                    self.assertEqual(again.exception.code, "APPROVAL-CONFIRM-AGAIN")
                    webchat.approval_cancel(self.uid, self.sid, aid)
        self.assertEqual(dispatched, [])

    def test_approval_table_is_in_account_deletion_inventory(self):
        self.assertIn("chat_approvals", db.DELETE_TABLES)

    def test_person_and_reflection_delete_trash_change_is_stale_and_hard_delete_needs_second_confirmation(self):
        """휴지통이 꺼져 있으면 삭제 카드는 되돌릴 수 없음(두 번 확인). 휴지통이 켜졌을 때 만든 카드는 꺼진 뒤 확정하면 STALE."""
        person = db.person_save(self.uid, "synthetic person")
        source = db.source_create(self.uid, "other", "synthetic source")
        reflection = db.source_reflection_save(self.uid, source["id"], "summary", "synthetic reflection")
        targets = [
            ("person_delete", {"person_id": person["id"], "expected_revision": person["revision"]}),
            ("source_reflection_delete", {"reflection_id": reflection["id"], "expected_revision": reflection["revision"]}),
        ]
        for op, params in targets:
            with self.subTest(op=op):
                with patch.dict(os.environ, {"CRM_TRASH_ENABLED": "0"}):
                    hard = webchat.approval_prepare(self.uid, self.sid, self.tid, op, params)["approval_id"]
                    with self.assertRaises(db.CrmError) as again:
                        webchat.approval_confirm(self.uid, self.sid, hard)
                    self.assertEqual(again.exception.code, "APPROVAL-CONFIRM-AGAIN")
                    webchat.approval_cancel(self.uid, self.sid, hard)
                with patch.dict(os.environ, {"CRM_TRASH_ENABLED": "1"}):
                    aid = webchat.approval_prepare(self.uid, self.sid, self.tid, op, params)["approval_id"]
                with patch.dict(os.environ, {"CRM_TRASH_ENABLED": "0"}):
                    with self.assertRaises(db.CrmError) as stale:
                        webchat.approval_confirm(self.uid, self.sid, aid, irreversible_ack=True)
                    self.assertEqual(stale.exception.code, "APPROVAL-STALE")
        self.assertEqual(db.person_get(self.uid, person["id"])["alias"], "synthetic person")
        self.assertEqual(db.source_reflection_get(self.uid, reflection["id"])["body"], "synthetic reflection")

    def test_followup_turn_receives_only_server_generated_outcomes(self):
        approved = self.prepare()["approval_id"]
        pending = self.prepare()["approval_id"]
        webchat.approval_confirm(self.uid, self.sid, approved)
        webchat.approval_cancel(self.uid, self.sid, pending)
        with db.tx() as c:
            c.execute("UPDATE chat_turns SET status='done',ended_at=now() WHERE id=%s", (self.tid,))
        with patch("webchat._active_devices", return_value={"synthetic-device"}):
            turn = webchat.turn_create(self.uid, self.sid, "synthetic follow-up", "follow-up",
                                        connected=lambda _device: True, capable=lambda _session: True)
        self.assertEqual(turn["text"], "synthetic follow-up")
        self.assertEqual(turn["approval_outcomes"], [
            {"id": approved, "op": "record_edit", "status": "confirmed"},
            {"id": pending, "op": "record_edit", "status": "cancelled"},
        ])
        messages = webchat.messages(self.uid, self.sid, None)
        self.assertEqual(messages[-1]["body"], "synthetic follow-up")

    def test_cancel_expiry_and_closed_session_prevent_execution(self):
        first = self.prepare()["approval_id"]
        self.assertEqual(webchat.approval_cancel(self.uid, self.sid, first)["status"], "cancelled")
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.uid, self.sid, first)
        second = self.prepare()["approval_id"]
        with db.tx() as c:
            c.execute("UPDATE chat_approvals SET expires_at=clock_timestamp()-interval '1 second' WHERE id=%s", (second,))
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.uid, self.sid, second)
        third = self.prepare()["approval_id"]
        with db.tx() as c:
            c.execute("UPDATE chat_sessions SET status='closed' WHERE id=%s", (self.sid,))
        with self.assertRaises(db.CrmError):
            webchat.approval_confirm(self.uid, self.sid, third)
        self.assertEqual(db.record_get(self.uid, self.record["id"])["body"], "before synthetic after")

    def test_session_has_a_bounded_total_number_of_approval_rows(self):
        with db.tx() as c:
            for _ in range(100):
                c.execute("INSERT INTO chat_approvals (id,user_id,session_id,turn_id,op,params,preview,state,expires_at,finished_at) "
                          "VALUES (%s,%s,%s,%s,'record_edit','{}','{}','cancelled',clock_timestamp(),clock_timestamp())",
                          (webchat._id("ca"), self.uid, self.sid, self.tid))
        with self.assertRaises(db.CrmError) as error:
            self.prepare()
        self.assertEqual(error.exception.code, "RATE-LIMIT")


if __name__ == "__main__":
    unittest.main()
