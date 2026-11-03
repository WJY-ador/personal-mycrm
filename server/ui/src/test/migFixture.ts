// 시험 도우미 — 이관 화면용 가짜 응답(옛 test_migration_screen.py TOKENS·PLANS·DETAIL 그대로). 화면 코드가 아니다(*.test 만 import).
const T = (d: string) => `2026-${d}T01:00:00+00:00`;
export const PID = "mp_" + "1".repeat(24);
export const TOKENS = {
  tokens: [
    { id: "mt_a", label: "이관 업로더", created_at: T("11-02"), expires_at: T("11-16"), revoked_at: null, last_used_at: null, active: true },
    { id: "mt_b", label: "옛 업로더", created_at: T("10-20"), expires_at: T("11-03"), revoked_at: T("11-02"), last_used_at: T("10-21"), active: false },
  ],
  enabled: true, allowed: true, token_days: 14,
};
export const PLANS = {
  plans: [
    { plan_id: PID, state: "sealed", item_count: 8, source_instance: "pc-test-1", created_at: T("11-02"), expires_at: T("11-05"), applied_at: null, closed_at: null,
      plan_hash: "b".repeat(64), via: null, summary: { dry_run: { actions: { insert: 5, warn: 2, reject: 1 }, units: {} } } },
    { plan_id: "mp_" + "2".repeat(24), state: "applied", item_count: 1, source_instance: "pc-test-1", created_at: T("11-01"), expires_at: T("11-04"),
      applied_at: "2026-11-01T02:00:00+00:00", closed_at: null, plan_hash: "c".repeat(64), via: "mcp", summary: { dry_run: { actions: { insert: 1 }, units: {} } } },
  ],
  enabled: true, allowed: true, limits: { daily: 200, used_today: 7, plan_items: 200, plan_days: 3, open_plans: 3 },
};
const it = (seq: number, unit_kind: string, action: string, title: string | null, reason: string | null = null, needs_check = false, checked = false) =>
  ({ seq, unit_kind, action, reason, title, needs_check, checked, result: null, target_id: null });
export const DETAIL = {
  ...PLANS.plans[0], item_count: 8,
  counts: { actions: { insert: 4, noop: 1, warn: 1, reject: 1, conflict: 1 },
    units: { record: { insert: 2, warn: 1, reject: 1 }, principle_c: { insert: 2, noop: 1 }, source: { conflict: 1 } } },
  items: [it(0, "record", "insert", "첫 기록"), it(1, "record", "warn", "두 번째", "duplicate_content"),
    it(2, "principle_c", "insert", "작게 자주", null, true, true), it(3, "principle_c", "insert", "원문 먼저", null, true),
    it(4, "principle_c", "noop", "이미 있는 기준", null, true), it(5, "record", "reject", null, "sensitivity_internal"),
    it(6, "source", "conflict", "출처", "conflict"), it(7, "record", "insert", "기준에 붙는 기록")],
};
const e = "e".repeat(64);
export const RECEIPT = {
  plan_id: PID, import_batch_id: PID, plan_hash: "b".repeat(64), receipt_hash: "d".repeat(64), applied_at: "2026-11-02T02:00:00+00:00",
  counts: { results: { applied: 2, noop: 1, skipped_unchecked: 1, skipped_reject: 1 }, units: { record: { applied: 2, skipped_reject: 1 }, principle_c: { noop: 1, skipped_unchecked: 1 } } },
  items: [
    { seq: 0, unit_kind: "record", original_id: "o_0", content_hash: e, result: "applied", target_id: "r_1", stored_hash: e, target_state: "live" },
    { seq: 1, unit_kind: "record", original_id: "o_1", content_hash: e, result: "applied", target_id: "r_2", stored_hash: "f".repeat(64), target_state: "live" },
    { seq: 2, unit_kind: "principle_c", original_id: "o_2", content_hash: e, result: "noop", target_id: "i_1", stored_hash: null, target_state: "trashed" },
    { seq: 3, unit_kind: "principle_c", original_id: "o_3", content_hash: e, result: "skipped_unchecked", target_id: null, stored_hash: null, target_state: null },
    { seq: 4, unit_kind: "record", original_id: "o_4", content_hash: e, result: "skipped_reject", target_id: null, stored_hash: null, target_state: null },
  ],
};
