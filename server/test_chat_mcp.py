"""Synthetic tests for the chat MCP scope filter. No DB, credentials, or live server."""
from datetime import datetime, timedelta, timezone, tzinfo
import unittest
from zoneinfo import ZoneInfo

from chat_mcp import (
    AuthenticatedPrincipal,
    ChatMcpDenied,
    ConsentBinding,
    SessionBinding,
    allowed_operations,
    call_existing,
    filter_find_result,
    filter_tool_names,
    find_existing,
    validate_call,
    validate_scope,
)


EXPECTED = {
    "read": "state_get help_get me_get me_aggregate_get layout_get export_get decide_preview question_list answer_get record_get candidate_list definitions_get person_list person_get person_context_get source_list source_get source_context_get source_reflection_list source_reflection_get activity_list activity_get inbox_list inbox_get trash_list ticket_list_mine ticket_get_mine migration_receipt_get migration_list migration_get migration_item_get migration_apply_preview pc_list token_grant_status token_list",
    "write": "layout_set layout_reset display_name_set question_add profile_set record_add record_attach record_title_set candidates_propose definition_propose item_propose person_save source_create source_reflection_save pc_connect",
    "decide": "record_edit record_provenance_set candidate_decide definition_apply definition_archive definition_restore item_decide person_delete source_reflection_review source_reflection_delete inbox_decide trash_move trash_restore feedback_send migration_apply migration_cancel migration_revert migration_token_send pc_forget token_revoke",
    "purge": "trash_purge",
}


def catalog_from_expected():
    return {"version": 1, "ops": {
        name: {"tier": tier}
        for tier, names in EXPECTED.items()
        for name in names.split()
    }}


class ChatMcpScopeTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)
        self.principal = AuthenticatedPrincipal(user_id="u-synthetic", device_id="d-synthetic")
        self.session = SessionBinding(
            user_id="u-synthetic", device_id="d-synthetic", session_id="cs-synthetic",
            provider="claude", model="claude-sonnet-synthetic", status="active",
        )
        self.consent = ConsentBinding(
            user_id="u-synthetic", device_id="d-synthetic", session_id="cs-synthetic",
            provider="claude", model="claude-sonnet-synthetic", consented_at=self.now,
            expires_at=self.now + timedelta(minutes=5), revoked_at=None,
        )
        self.allowed = allowed_operations(catalog_from_expected())

    def test_only_chat_facade_tools_are_visible(self):
        names = filter_tool_names(("record_add", "find", "purge", "read", "shell", "write", "decide"))
        self.assertEqual(names, ("find", "read", "write", "decide", "purge"))   # AI 하나로 A3: purge 도 카드 경로로 보인다

    def test_catalog_must_match_pinned_operation_tiers_exactly(self):
        catalog = catalog_from_expected()
        catalog["ops"]["new_write"] = {"tier": "write"}
        with self.assertRaises(ChatMcpDenied):
            allowed_operations(catalog)
        with self.assertRaises(ChatMcpDenied):
            allowed_operations({**catalog_from_expected(), "version": True})

    def test_catalog_unknown_tier_and_duplicate_source_are_denied(self):
        catalog = catalog_from_expected()
        catalog["ops"]["record_add"] = {"tier": "purge"}
        with self.assertRaises(ChatMcpDenied):
            allowed_operations(catalog)
        with self.assertRaises(ChatMcpDenied):
            allowed_operations({"version": 1, "ops": [("record_add", {"tier": "write"})]})
        with self.assertRaises(ChatMcpDenied):
            allowed_operations('{"version":1,"ops":{"record_add":{"tier":"write"},"record_add":{"tier":"write"}}}')

    def test_allowed_operation_set_is_explicit_and_includes_purge_for_cards(self):
        """AI 하나로 A3: purge(trash_purge)도 대화 도구 목록에 든다. 실행은 카드뿐(validate_call 이 바로 실행을 막는다)."""
        expected = frozenset((tier, name) for tier, names in EXPECTED.items() for name in names.split())
        self.assertEqual(self.allowed, expected)
        self.assertEqual(len(self.allowed), 71)
        self.assertIn(("write", "record_add"), self.allowed)
        self.assertIn(("decide", "item_decide"), self.allowed)
        self.assertIn(("purge", "trash_purge"), self.allowed)

    def test_scope_requires_exact_authenticated_user_device_session_and_ai_binding(self):
        scope = validate_scope(self.principal, self.session, self.consent, self.now)
        self.assertEqual((scope.user_id, scope.device_id, scope.session_id, scope.provider, scope.model),
                         ("u-synthetic", "d-synthetic", "cs-synthetic", "claude", "claude-sonnet-synthetic"))
        wrong_principal = AuthenticatedPrincipal(user_id="u-other", device_id="d-synthetic")
        with self.assertRaises(ChatMcpDenied):
            validate_scope(wrong_principal, self.session, self.consent, self.now)

    def test_scope_fails_closed_for_expired_revoked_unconsented_or_mismatched_binding(self):
        cases = [
            ConsentBinding(**{**self.consent.__dict__, "expires_at": self.now}),
            ConsentBinding(**{**self.consent.__dict__, "revoked_at": self.now}),
            ConsentBinding(**{**self.consent.__dict__, "consented_at": None}),
            ConsentBinding(**{**self.consent.__dict__, "provider": "codex"}),
            SessionBinding(**{**self.session.__dict__, "status": "closed"}),
            SessionBinding(**{**self.session.__dict__, "model": "other-model"}),
            SessionBinding(**{**self.session.__dict__, "provider": "fake"}),
        ]
        for binding in cases:
            with self.subTest(binding=binding), self.assertRaises(ChatMcpDenied):
                consent = binding if isinstance(binding, ConsentBinding) else self.consent
                session = binding if isinstance(binding, SessionBinding) else self.session
                validate_scope(self.principal, session, consent, self.now)

    def test_scope_denies_cross_user_device_session_and_model_mismatch(self):
        principal_cases = [
            AuthenticatedPrincipal(user_id="u-synthetic", device_id="d-other"),
            AuthenticatedPrincipal(user_id="U-synthetic", device_id="d-synthetic"),
        ]
        for principal in principal_cases:
            with self.subTest(principal=principal), self.assertRaises(ChatMcpDenied):
                validate_scope(principal, self.session, self.consent, self.now)
        consent_cases = [
            {"user_id": "u-other"}, {"device_id": "d-other"}, {"session_id": "cs-other"},
            {"model": None}, {"consented_at": self.now + timedelta(seconds=1)},
        ]
        for change in consent_cases:
            with self.subTest(consent=change), self.assertRaises(ChatMcpDenied):
                validate_scope(self.principal, self.session,
                               ConsentBinding(**{**self.consent.__dict__, **change}), self.now)
        no_model_session = SessionBinding(**{**self.session.__dict__, "model": None})
        with self.assertRaises(ChatMcpDenied):
            validate_scope(self.principal, no_model_session, self.consent, self.now)
        both_none = ConsentBinding(**{**self.consent.__dict__, "model": None})
        self.assertIsNone(validate_scope(self.principal, no_model_session, both_none, self.now).model)

    def test_db_session_id_and_consumed_grant_request_id_are_both_bound(self):
        session = SessionBinding(**{**self.session.__dict__, "session_id": "database-session",
                                   "grant_session_id": "client-request"})
        consent = ConsentBinding(**{**self.consent.__dict__, "session_id": "client-request"})
        scope = validate_scope(self.principal, session, consent, self.now)
        self.assertEqual(scope.session_id, "database-session")
        with self.assertRaises(ChatMcpDenied):
            validate_scope(self.principal, session,
                           ConsentBinding(**{**consent.__dict__, "session_id": "other-request"}), self.now)

    def test_scope_fails_closed_for_missing_or_naive_identity_and_time(self):
        for args in ((None, self.session, self.consent),
                     (self.principal, None, self.consent),
                     (self.principal, self.session, None)):
            with self.subTest(args=args), self.assertRaises(ChatMcpDenied):
                validate_scope(*args, now=self.now)
        naive = datetime(2026, 11, 6)
        with self.assertRaises(ChatMcpDenied):
            validate_scope(self.principal, self.session, self.consent, naive)

    def test_expiry_uses_absolute_time_across_dst_fold(self):
        ny = ZoneInfo("America/New_York")
        now = datetime(2026, 11, 1, 1, 15, tzinfo=ny, fold=1)  # 06:15 UTC
        expired = ConsentBinding(**{**self.consent.__dict__,
                                    "consented_at": datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
                                    "expires_at": datetime(2026, 11, 1, 1, 30, tzinfo=ny, fold=0)})  # 05:30 UTC
        with self.assertRaises(ChatMcpDenied):
            validate_scope(self.principal, self.session, expired, now)

    def test_expiry_boundary_is_exclusive_even_when_offsets_differ(self):
        now = datetime(2026, 11, 6, 9, 0, tzinfo=timezone(timedelta(hours=9)))
        same_instant = ConsentBinding(**{**self.consent.__dict__,
                                         "consented_at": now - timedelta(minutes=1),
                                         "expires_at": datetime(2026, 11, 6, 0, 0, tzinfo=timezone.utc)})
        with self.assertRaises(ChatMcpDenied):
            validate_scope(self.principal, self.session, same_instant, now)

    def test_local_clock_moving_backwards_can_still_be_future_in_absolute_time(self):
        ny = ZoneInfo("America/New_York")
        now = datetime(2026, 11, 1, 1, 45, tzinfo=ny, fold=0)  # 05:45 UTC
        consent = ConsentBinding(**{**self.consent.__dict__,
                                    "consented_at": datetime(2026, 11, 1, 0, 0, tzinfo=timezone.utc),
                                    "expires_at": datetime(2026, 11, 1, 1, 15, tzinfo=ny, fold=1)})  # 06:15 UTC
        scope = validate_scope(self.principal, self.session, consent, now)
        self.assertEqual(scope.session_id, "cs-synthetic")

    def test_time_conversion_errors_fail_closed_without_leaking_timezone_exception(self):
        class BrokenTimezone(tzinfo):
            def utcoffset(self, dt):
                raise RuntimeError("synthetic timezone failure")
        broken = datetime(2026, 11, 6, tzinfo=BrokenTimezone())
        for now, consent in ((broken, self.consent),
                             (self.now, ConsentBinding(**{**self.consent.__dict__, "expires_at": broken})),
                             (self.now, ConsentBinding(**{**self.consent.__dict__, "consented_at": broken})),
                             ("2026-11-06T00:00:00Z", self.consent),
                             (self.now, ConsentBinding(**{**self.consent.__dict__, "expires_at": "not-a-timestamp"})),
                             (self.now, ConsentBinding(**{**self.consent.__dict__, "consented_at": 123}))):
            with self.subTest(now=now, consent=consent), self.assertRaises(ChatMcpDenied):
                validate_scope(self.principal, self.session, consent, now)

    def test_find_results_keep_allowlisted_purge_and_drop_unknown_ops(self):
        """AI 하나로 A3: find 는 허용 목록의 purge(trash_purge)를 보인다. 목록 밖 op, 등급이 틀린 짝은 지운다."""
        family = {"family": "trash", "ops": [
            {"op": "trash_list", "tier": "read"}, {"op": "trash_move", "tier": "decide"},
            {"op": "trash_purge", "tier": "purge"}, {"op": "trash_purge", "tier": "decide"}, {"op": "shell", "tier": "purge"},
        ]}
        result = filter_find_result(family, self.allowed)
        self.assertEqual([op["op"] for op in result["ops"]], ["trash_list", "trash_move", "trash_purge"])
        search = {"matches": family["ops"]}
        self.assertEqual([op["op"] for op in filter_find_result(search, self.allowed)["matches"]],
                         ["trash_list", "trash_move", "trash_purge"])
        overview = {"families": [{"key": "trash", "ops_by_tier": {"read": ["trash_list"],
                     "decide": ["trash_move"], "purge": ["trash_purge"]}}]}
        self.assertEqual(filter_find_result(overview, self.allowed)["families"][0]["ops_by_tier"]["purge"], ["trash_purge"])
        self.assertEqual(filter_find_result({"op": "trash_purge", "tier": "purge"}, self.allowed)["op"], "trash_purge")
        with self.assertRaises(ChatMcpDenied):
            filter_find_result({"op": "trash_purge", "tier": "decide"}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            filter_find_result({"families": [{"key": "x", "ops_by_tier": {"purge": ["shell"]}}]}, self.allowed)

    def test_single_op_find_result_with_non_string_op_is_denied(self):
        for op in (["trash_move"], {"op": "trash_move"}, None):
            with self.subTest(op=op), self.assertRaises(ChatMcpDenied):
                filter_find_result({"op": op, "tier": "decide"}, self.allowed)

    def test_decide_preview_description_keeps_only_allowlisted_targets(self):
        schema = {"type": "object", "required": ["op", "params"], "properties": {
            "op": {"type": "string", "enum": ["item_decide", "trash_move", "trash_purge", "record_add", "shell"]},
            "params": {"type": "object"},
        }}
        result = filter_find_result({"op": "decide_preview", "tier": "read", "input_schema": schema}, self.allowed)
        self.assertEqual(result["input_schema"]["properties"]["op"]["enum"], ["item_decide", "trash_move", "trash_purge"])
        self.assertIn("shell", schema["properties"]["op"]["enum"], "caller-owned result is not mutated")
        for bad in (None, {"properties": []}, {"properties": {"op": {"enum": "trash_purge"}}}):
            with self.subTest(schema=bad), self.assertRaises(ChatMcpDenied):
                filter_find_result({"op": "decide_preview", "tier": "read", "input_schema": bad}, self.allowed)

    def test_only_allowlisted_facade_operation_pairs_can_dispatch(self):
        validate_call("write", "record_add", {"text": "합성 글"}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            validate_call("decide", "item_decide", {"item_id": "i-synthetic"}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            validate_call("purge", "trash_purge", {}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            validate_call("read", "trash_purge", {}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            validate_call("shell", "exec", {}, self.allowed)
        with self.assertRaises(ChatMcpDenied):
            validate_call("record_add", "", {}, self.allowed)

    def test_decide_preview_targets_only_decide_or_purge_and_rejects_malformed(self):
        validate_call("read", "decide_preview", {"op": "item_decide", "params": {}}, self.allowed)
        validate_call("read", "decide_preview", {"op": "trash_purge", "params": {}}, self.allowed)
        for params in ({"op": "shell", "params": {}}, {"op": "record_add", "params": {}},
                       {"op": "item_decide", "params": [], "uid": "u-other"}):
            with self.subTest(params=params), self.assertRaises(ChatMcpDenied):
                validate_call("read", "decide_preview", params, self.allowed)

    def test_model_cannot_supply_uid_or_bind_inside_operation_params(self):
        for params in ({"text": "x", "uid": "u-other"}, {"text": "x", "bind": "forged"}):
            with self.subTest(params=params), self.assertRaises(ChatMcpDenied):
                validate_call("write", "record_add", params, self.allowed)

    def test_call_existing_dispatches_only_after_scope_and_allowlist_checks(self):
        calls = []
        dispatch = lambda *args: calls.append(args) or {"ok": True}
        result = call_existing(self.principal, self.session, self.consent, "write", "record_add",
                               {"text": "합성 본문"}, "", catalog=catalog_from_expected(), now=self.now,
                               dispatch_existing=dispatch)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(calls, [("write", "record_add", {"text": "합성 본문"}, "")])
        with self.assertRaises(ChatMcpDenied):
            call_existing(self.principal, self.session, self.consent, "purge", "trash_purge", {}, "",
                           catalog=catalog_from_expected(), now=self.now, dispatch_existing=dispatch)
        with self.assertRaises(ChatMcpDenied):
            call_existing(self.principal, self.session, None, "write", "record_add", {"text": "x"}, "",
                           catalog=catalog_from_expected(), now=self.now, dispatch_existing=dispatch)
        self.assertEqual(len(calls), 1, "denials must happen before the injected existing-dispatch callback")

    def test_find_callback_is_filtered_and_cannot_target_unknown_ops(self):
        calls = []
        def find_cb(**kwargs):
            calls.append(kwargs)
            return {"matches": [
                {"op": "trash_move", "tier": "decide"},
                {"op": "trash_purge", "tier": "purge"},
                {"op": "shell", "tier": "write"},
            ]}
        result = find_existing(self.principal, self.session, self.consent, catalog=catalog_from_expected(),
                               now=self.now, find_callback=find_cb, query="삭제")
        self.assertEqual(result["matches"], [{"op": "trash_move", "tier": "decide"}, {"op": "trash_purge", "tier": "purge"}])
        self.assertEqual(calls, [{"query": "삭제", "family": "", "op": ""}])
        with self.assertRaises(ChatMcpDenied):
            find_existing(self.principal, self.session, self.consent, catalog=catalog_from_expected(),
                          now=self.now, find_callback=find_cb, op="shell")
        self.assertEqual(len(calls), 1, "unknown op descriptions are rejected before querying the callback")


if __name__ == "__main__":
    unittest.main()
