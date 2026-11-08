"""이관 MCP(가안 X, 2026-11-02) 시험 — 합성 PostgreSQL. notes/2026-11-02_mcp-facade-이관반영-구현계획.md §5·§7.

실행(단독): DATABASE_URL=postgresql://localhost/crm_test_mig_mcp python3 server/test_migration_mcp.py
CI: test_migration_path.py 가 끝에서 run(A, B) 를 부른다(같은 DB 단계). 가드·사용자·항목 도우미는 test_migration_path 의 것을 쓴다.

· 옛 스키마 업그레이드(옛 plan·항목·접수 모양 → init_schema 두 번 = 최종형, 멱등)
· 스위치 CRM_MIGRATION_MCP_ENABLED 꺼짐 = 읽기 포함 op 8개 전부 거절 · 기존 스위치·allowlist 도 본다
· 웹 = MCP 결과 동일(기준 결정 없는 plan — 결과·created·개수·receipt_hash 모양 같음, via 만 다름)
· MCP 규칙: confirmed 를 확정하지 않음(새 기준 미확정 = decision_deferred · 이미 확정된 기준은 그대로) · excluded 반입 안 함(skipped_reject, decision_excluded) · 제외 기준 의존 거절
· APPLY-MISMATCH(plan_hash·expected_counts, detail{field, server}) · 두 번째 반영 noop · 감사 via(영수증·item_history.event_meta)
· migration_revert a~e: 출처 유지 · 접수 reverted → 재stage insert · 변경 뒤 REVERT-MODIFIED(기준 확정·후보) · reverted·두 번째 noop·한도 안 되돌림
  · 새로 만든 대상만 휴지통, 갱신분 kept_updated · 휴지통 꺼짐 SWITCH-OFF · 웹 revert 경로 없음
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import test_migration_path as T  # noqa: E402 — 가드(DATABASE_URL·crm_test*)·env 를 먼저 건다

import db  # noqa: E402
import migration as M  # noqa: E402
import migration_mcp as X  # noqa: E402

ok, expect, sql = T.ok, T.expect, T.sql


def mcp(on=True):
    os.environ["CRM_MIGRATION_MCP_ENABLED"] = "1" if on else ""


def trash(on=True):
    os.environ["CRM_TRASH_ENABLED"] = "1" if on else ""


def stage(uid, items):
    return T.stage({"user_id": uid, "token_id": None}, items)


def seq_of(st, item):
    return next(x["seq"] for x in st["items"] if x["original_id"] == item["original_id"])


def by_oid(rc):
    return {x["original_id"]: x for x in rc["items"]}


def cons(table):
    return {r["conname"]: r["d"] for r in sql("SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                                              "WHERE conrelid = %s::regclass", (table,))}


def cols(table):
    return {r["column_name"] for r in sql("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                          "AND table_name=%s", (table,))}


# ── 옛 스키마 업그레이드 ─────────────────────────────────

def test_upgrade():
    """옛 모양(가안 X 전 — reverted·via·created 없음, 판 UNIQUE 표 제약)으로 되돌린 뒤 init_schema 두 번 = 최종형."""
    assert not sql("SELECT 1 FROM migration_plans WHERE state='reverted'"), "업그레이드 시험은 reverted plan 이 생기기 전에"
    with db.tx() as c:
        for n in ("ck_migration_plans_applied", "ck_migration_plans_reverted", "ck_migration_plans_via", "migration_plans_state_check"):
            c.execute(f"ALTER TABLE migration_plans DROP CONSTRAINT {n}")
        c.execute("ALTER TABLE migration_plans DROP COLUMN reverted_at, DROP COLUMN via")
        c.execute("ALTER TABLE migration_plans ADD CHECK (state IN ('staged','sealed','applied','cancelled','expired'))")   # 옛 인라인(자동 이름)
        c.execute("ALTER TABLE migration_plans ADD CHECK ((state = 'applied') = (applied_at IS NOT NULL))")              # 옛 이름 없는 CHECK
        c.execute("ALTER TABLE migration_plan_items DROP COLUMN created, DROP COLUMN decision_deferred")
        c.execute("DROP INDEX ux_import_revision")
        c.execute("ALTER TABLE import_entries ADD UNIQUE (user_id, stream_id, original_id, source_revision)")
        c.execute("ALTER TABLE import_entries DROP CONSTRAINT import_entries_state_check")
        c.execute("ALTER TABLE import_entries ADD CONSTRAINT import_entries_state_check CHECK (state IN "
                  "('pending','applied','noop','excluded','expired','deleted'))")
    old = cons("migration_plans")
    assert "ck_migration_plans_applied" not in old and any("applied_at IS NOT NULL" in d for d in old.values())
    for _ in range(2):   # 멱등 — 두 번째는 아무것도 바꾸지 않는다
        db.init_schema()
        pc, ic = cons("migration_plans"), cons("import_entries")
        assert pc["ck_migration_plans_applied"].count("applied_at IS NOT NULL") == 1
        assert [n for n, d in pc.items() if "applied_at IS NOT NULL" in d] == ["ck_migration_plans_applied"], "옛 CHECK 를 지웠다"
        assert "'reverted'" in pc["migration_plans_state_check"] and "ck_migration_plans_reverted" in pc and "ck_migration_plans_via" in pc
        assert {"reverted_at", "via"} <= cols("migration_plans") and {"created", "decision_deferred"} <= cols("migration_plan_items")
        assert "'reverted'" in ic["import_entries_state_check"]
        assert not any(d == "UNIQUE (user_id, stream_id, original_id, source_revision)" for d in ic.values()), "판 UNIQUE → 부분 UNIQUE"
        assert sql("SELECT indexdef FROM pg_indexes WHERE indexname='ux_import_revision'")[0]["indexdef"].endswith(
            "WHERE (state <> 'reverted'::text)")
    old_applied = sql("SELECT count(*) AS n FROM migration_plans WHERE state='applied' AND via IS NULL")[0]["n"]
    assert old_applied > 0 and not sql("SELECT 1 FROM migration_plan_items WHERE created IS NOT NULL"), "옛 행 via·created = NULL(백필 없음)"
    ok("업그레이드: 옛 plan·항목·접수 모양 → init_schema 두 번 = 최종형(reverted·via·created·decision_deferred·부분 UNIQUE, 옛 CHECK 교체) · 옛 행 NULL")


# ── 스위치 ──────────────────────────────────────────────

def test_switch(A, B):
    calls = [(X.migration_list, ()), (X.migration_get, ("mp_" + "0" * 24,)), (X.migration_item_get, ("mp_" + "0" * 24, 0)),
             (X.migration_apply_preview, ("mp_" + "0" * 24,)), (X.migration_receipt_get, ()),
             (X.migration_apply, ("mp_" + "0" * 24, "0" * 64, {})), (X.migration_cancel, ("mp_" + "0" * 24,)),
             (X.migration_revert, ("mp_" + "0" * 24,))]
    assert set(X.OPS) == {f.__name__ for f, _ in calls} and len(X.OPS) == 8
    assert {k for k, v in X.OPS.items() if v["tier"] == "decide"} == {"migration_apply", "migration_cancel", "migration_revert"}
    mcp(False)
    for f, a in calls:
        e = expect("MIGRATION-OFF", f, A, *a)
        assert M.http_status(e.code) == 503
    X.receipt_get_direct(A)   # 기존 직접 도구 본체는 MCP 스위치를 보지 않는다(기존 동작)
    mcp(True)
    T.switches(False, [A, B])
    expect("MIGRATION-OFF", X.migration_list, A)
    T.switches(True, [B])
    expect("MIGRATION-NOT-ALLOWED", X.migration_list, A)
    T.switches(True, [A, B])
    lst = X.migration_list(A)
    assert lst["mcp_enabled"] is True and "limits" in lst and all("items" not in p for p in lst["plans"])
    expect("NOT-FOUND", X.migration_get, A, "mp_" + "0" * 24)
    ok("스위치: CRM_MIGRATION_MCP_ENABLED 꺼짐 = op 8개(읽기 포함) MIGRATION-OFF 503 · 기존 스위치·allowlist 도 봄 · 직접 영수증 도구는 그대로")


# ── 웹 = MCP ────────────────────────────────────────────

def _eq_items(tag):
    ax = T.axis(300, f"{tag} 축")
    p = T.principle(301, f"{tag} 기준", references=[{"field_key": "axes", "target": {"original_id": ax["original_id"],
                                                                                   "revision": ax["source_revision"]}}])
    src = T.source(302, f"{tag} 노트")
    r = T.rec(303, f"{tag} 원문 기록", source_ref={"original_id": src["original_id"]})
    bad = T.rec(304, f"{tag} 검토 중", review={"state": "pending"})
    return [ax, p, src, r, bad]


def test_web_equals_mcp(A, B):
    items = _eq_items("동일성")
    sa, sb = stage(A, items), stage(B, items)
    assert sa["plan_hash"] == sb["plan_hash"]
    det = M.plan_detail(A, sa["plan_id"])
    M.plan_check(A, sa["plan_id"], [x["seq"] for x in det["items"] if x["needs_check"]], True)   # 웹 = 기준 체크(결정 없음)
    web = M.plan_apply(A, sa["plan_id"], sa["plan_hash"], via="web")
    pv = X.migration_apply_preview(B, sb["plan_id"])
    assert pv["blocked"] == [] and pv["decision_deferred"] == 0 and pv["decision_excluded"] == 0 and pv["message"] == M.MCP_DEFER_MSG
    got = X.migration_apply(B, sb["plan_id"], pv["plan_hash"], pv["expected_counts"])
    assert pv["expected_counts"] == got["counts"]["results"], "미리보기 개수 = 실제 결과"
    strip = lambda rc: [{k: v for k, v in x.items() if k not in ("target_id", "via", "stored_hash")} for x in rc["items"]]   # noqa: E731
    assert strip(web) == strip(got), "웹·MCP 영수증 항목(결과·created·reason·해시) 같음"
    assert web["counts"] == got["counts"] and web["via"] == "web" and got["via"] == "mcp"
    assert all(x["via"] == "web" for x in web["items"]) and all(x["via"] == "mcp" for x in got["items"])
    assert [x["stored_hash"] for x in web["items"]] == [x["stored_hash"] for x in got["items"]]
    assert all(x["created"] is True for x in got["items"] if x["result"] == "applied")
    for uid, rc, via in ((A, web, "web"), (B, got, "mcp")):
        pid = by_oid(rc)[items[1]["original_id"]]["target_id"]
        metas = [r["event_meta"] for r in sql("SELECT event_meta FROM item_history WHERE user_id=%s AND item_id=%s", (uid, pid))]
        assert metas and all(m.get("via") == via and m.get("ingest") == "board_migration" for m in metas), metas
    assert next(p for p in X.migration_list(B)["plans"] if p["plan_id"] == sb["plan_id"])["via"] == "mcp"
    ok("웹 = MCP: 같은 plan(기준 결정 없음)의 결과·created·개수·저장 해시 같음 · 미리보기 개수 = 결과 · via 는 영수증·item_history·목록에")


def test_nested_tx_scope_apply_revert(A):
    """Migration's own scopes must nest atomically inside the chat route scope."""
    old_trash = os.environ.get("CRM_TRASH_ENABLED", "") == "1"
    item = T.rec(361, "중첩 트랜잭션 이관 기록")
    st = stage(A, [item])
    pv = X.migration_apply_preview(A, st["plan_id"])
    with db.tx_scope():
        applied = X.migration_apply(A, st["plan_id"], pv["plan_hash"], pv["expected_counts"])
    assert applied["state"] == "applied"

    failed_item = T.rec(362, "중첩 트랜잭션 실패 기록")
    failed = stage(A, [failed_item])
    failed_preview = X.migration_apply_preview(A, failed["plan_id"])
    with db.tx_scope():
        expect("APPLY-MISMATCH", X.migration_apply, A, failed["plan_id"], "f" * 64,
               failed_preview["expected_counts"])
        assert M.plan_status({"user_id": A, "token_id": None}, failed["plan_id"])["state"] == "sealed"
    assert M.plan_status({"user_id": A, "token_id": None}, failed["plan_id"])["state"] == "sealed"

    trash(True)
    try:
        with db.tx_scope():
            reverted = X.migration_revert(A, st["plan_id"])
        assert reverted["state"] == "reverted"
    finally:
        trash(old_trash)
    ok("중첩 tx_scope: MCP migration_apply/revert 정상 처리 · 잘못된 해시 savepoint rollback 뒤 outer transaction 사용 가능")


# ── MCP 규칙 · 바인딩 ────────────────────────────────────

def test_rules_binding(B):
    pc = T.principle(320, "확정 표시 기준", decision="confirmed")
    pe = T.principle(321, "제외 표시 기준", decision="excluded")
    pn = T.principle(322, "결정 없는 기준")
    r = T.rec(323, "규칙 시험 기록")
    st = stage(B, [pc, pe, pn, r])
    assert not any(x["checked"] for x in M.plan_detail(B, st["plan_id"])["items"]), "웹 체크 없이"
    pv = X.migration_apply_preview(B, st["plan_id"])
    assert (pv["decision_deferred"], pv["decision_excluded"]) == (1, 1) and pv["message"] == M.MCP_DEFER_MSG
    assert pv["expected_counts"] == {"applied": 3, "skipped_reject": 1} and pv["will_apply_rows"] == 3 and pv["blocked"] == []
    e = expect("APPLY-MISMATCH", X.migration_apply, B, st["plan_id"], "f" * 64, pv["expected_counts"])
    assert e.detail == {"field": "plan_hash", "server": st["plan_hash"]} and M.http_status(e.code) == 409
    e = expect("APPLY-MISMATCH", X.migration_apply, B, st["plan_id"], pv["plan_hash"], {"applied": 4})
    assert e.detail == {"field": "expected_counts", "server": pv["expected_counts"]}
    expect("ARG-INVALID", X.migration_apply, B, st["plan_id"], pv["plan_hash"], "3")
    assert M.plans_list(B)["plans"][0]["state"] == "sealed", "불일치 = 아무것도 반영 안 함"
    rc = X.migration_apply(B, st["plan_id"], pv["plan_hash"], pv["expected_counts"])
    x = by_oid(rc)
    assert x[pc["original_id"]]["decision_deferred"] is True and x[pc["original_id"]]["result"] == "applied"
    assert (x[pe["original_id"]]["result"], x[pe["original_id"]]["reason"], x[pe["original_id"]]["target_id"]) == \
        ("skipped_reject", "decision_excluded", None)
    assert x[pn["original_id"]]["decision_deferred"] is False and rc["counts"]["decision_deferred"] == 1
    dec = {r_["id"]: r_["decision"] for r_ in sql("SELECT id, decision FROM items WHERE id = ANY(%s)",
                                                   ([x[pc["original_id"]]["target_id"], x[pn["original_id"]]["target_id"]],))}
    assert set(dec.values()) == {"pending"}, "대화 반영은 기준을 확정하지 않는다"
    again = X.migration_apply(B, st["plan_id"], pv["plan_hash"], pv["expected_counts"])
    assert again["already_applied"] is True and again["receipt_hash"] == rc["receipt_hash"]
    e = expect("APPLY-MISMATCH", X.migration_apply, B, st["plan_id"], pv["plan_hash"], {"applied": 9})
    assert e.detail["server"] == rc["counts"]["results"]
    pv2 = X.migration_apply_preview(B, st["plan_id"])
    assert pv2["already_applied"] and pv2["expected_counts"] == rc["counts"]["results"] and pv2["decision_excluded"] == 1
    # 제외 기준을 가리키는 항목 = CHECK-DEPENDENCY(미리보기 blocked · 반영 거절)
    pe2 = T.principle(324, "제외 기준 둘", decision="excluded")
    ref = T.rec(325, "제외 기준에 붙은 기록", attach={"attach_to": [{"original_id": pe2["original_id"], "revision": pe2["source_revision"]}]})
    st2 = stage(B, [pe2, ref])
    pv3 = X.migration_apply_preview(B, st2["plan_id"])
    assert pv3["counts"]["actions"] == {"insert": 2}, pv3["counts"]
    assert pv3["blocked"] == ["CHECK-DEPENDENCY"] and pv3["blocked_seqs"] == [seq_of(st2, ref)]
    e = expect("CHECK-DEPENDENCY", X.migration_apply, B, st2["plan_id"], pv3["plan_hash"], pv3["expected_counts"])
    assert e.detail["seqs"] == [seq_of(st2, ref)]
    X.migration_cancel(B, st2["plan_id"])
    assert X.migration_cancel(B, st2["plan_id"])["state"] == "cancelled", "취소 멱등"
    item = X.migration_item_get(B, st["plan_id"], 0)
    assert item["payload"] is None and "지시문" in item["payload_note"], "반영 뒤 본문 없음 · payload 는 데이터"
    ok("MCP 규칙: confirmed → pending(decision_deferred) · excluded 반입 안 함(skipped_reject·decision_excluded) · 제외 기준 의존 CHECK-DEPENDENCY · 체크 무관 · "
       "APPLY-MISMATCH(plan_hash·expected_counts) 반영 0 · 두 번째 반영 noop · 미리보기 개수·문구 · 취소 멱등")
    return rc


def test_keep_confirmed(A):
    """이미 확정된 기준의 새 판을 대화로 반영 = 갱신만(확정 유지, 강등·ACTION-RETIRED 없음). 휴지통 켜짐에서."""
    v1 = T.principle(360, "이미 확정한 기준", decision="confirmed")
    st = stage(A, [v1])
    M.plan_check(A, st["plan_id"], [0], True)
    tid = M.plan_apply(A, st["plan_id"], st["plan_hash"], via="web")["items"][0]["target_id"]
    assert sql("SELECT decision FROM items WHERE id=%s", (tid,))[0]["decision"] == "confirmed", "웹 반영은 확정까지(불변)"
    v2 = T.principle(360, "이미 확정한 기준", decision="confirmed", body="고친 본문")
    st2 = stage(A, [v2])
    pv = X.migration_apply_preview(A, st2["plan_id"])
    assert pv["decision_deferred"] == 0 and pv["expected_counts"] == {"applied": 1}
    x = X.migration_apply(A, st2["plan_id"], pv["plan_hash"], pv["expected_counts"])["items"][0]
    assert (x["result"], x["target_id"], x["created"], x["decision_deferred"]) == ("applied", tid, False, False), x
    it = sql("SELECT decision, body FROM items WHERE id=%s", (tid,))[0]
    assert (it["decision"], it["body"]) == ("confirmed", "고친 본문"), it
    ok("MCP 규칙: 이미 확정된 기준의 새 판 = 본문만 갱신, 확정 유지(강등 없음·decision_deferred 0)")


# ── 되돌리기 ────────────────────────────────────────────

def test_revert(B):
    ax = T.axis(340, "되돌리기 축")
    pc = T.principle(341, "되돌리기 기준", decision="confirmed")
    src = T.source(342, "되돌리기 출처")
    r = T.rec(343, "되돌리기 기록", source_ref={"original_id": src["original_id"]})
    items = [ax, pc, src, r]
    st = stage(B, items)
    pv = X.migration_apply_preview(B, st["plan_id"])
    rc = X.migration_apply(B, st["plan_id"], pv["plan_hash"], pv["expected_counts"])
    tid = {k: by_oid(rc)[v["original_id"]]["target_id"] for k, v in (("ax", ax), ("pc", pc), ("src", src), ("r", r))}
    used = M.plans_list(B)["limits"]["used_today"]
    trash(False)
    expect("SWITCH-OFF", X.migration_revert, B, st["plan_id"])
    trash(True)
    rv = X.migration_revert(B, st["plan_id"])
    assert rv["state"] == "reverted" and rv["trashed"] == {"record": 1, "item": 2} and rv["kept_source"] == 1 and rv["kept_updated"] == 0
    assert rv["restore_until"] and rv["already_reverted"] is False
    gone = sql("SELECT (SELECT trashed_at IS NOT NULL FROM records WHERE id=%s) AS r, (SELECT bool_and(trashed_at IS NOT NULL) FROM items "
               "WHERE id = ANY(%s)) AS i, (SELECT count(*) FROM sources WHERE id=%s) AS s", (tid["r"], [tid["ax"], tid["pc"]], tid["src"]))[0]
    assert gone["r"] and gone["i"] and gone["s"] == 1, "a 출처 유지 · e 새로 만든 대상만 휴지통"
    ents = sql("SELECT state, is_latest_received, is_current_applied FROM import_entries WHERE user_id=%s AND batch_id=%s", (B, st["plan_id"]))
    assert ents and all((e["state"], e["is_latest_received"], e["is_current_applied"]) == ("reverted", False, False) for e in ents), ents
    assert M.plans_list(B)["limits"]["used_today"] == used, "d 일일 한도는 돌려주지 않는다"
    assert X.migration_revert(B, st["plan_id"])["already_reverted"] is True, "d 두 번째 호출 noop"
    rr = X.migration_receipt_get(B, st["plan_id"])
    assert rr["state"] == "reverted" and rr["reverted_at"] and all(x["target_state"] == "trashed" for x in rr["items"] if x["target_kind"] != "source")
    expect("PLAN-STATE", X.migration_apply, B, st["plan_id"], pv["plan_hash"], pv["expected_counts"])
    # b 같은 판 재stage = insert(대응표 reverted 는 같은 판으로 보지 않고, 휴지통 대상은 중복 대조에서 빠진다)
    st2 = stage(B, items)
    a2 = T.acts(st2)
    assert all(a2[i["original_id"]] == ("insert", None) for i in (ax, pc, r)) and a2[src["original_id"]] == ("noop", None), a2
    pv2 = X.migration_apply_preview(B, st2["plan_id"])
    rc2 = X.migration_apply(B, st2["plan_id"], pv2["plan_hash"], pv2["expected_counts"])
    x2 = by_oid(rc2)
    assert all(x2[i["original_id"]]["result"] == "applied" and x2[i["original_id"]]["target_id"] != tid[k]
               for k, i in (("ax", ax), ("pc", pc), ("r", r)))
    # c 기준 확정 뒤 되돌리기 = REVERT-MODIFIED(전체, 아무것도 안 바꿈)
    pid = x2[pc["original_id"]]["target_id"]
    rev = sql("SELECT revision FROM items WHERE id=%s", (pid,))[0]["revision"]
    db.item_decide(B, pid, rev, None, "confirm")
    e = expect("REVERT-MODIFIED", X.migration_revert, B, st2["plan_id"])
    assert e.detail["seqs"] == [seq_of(st2, pc)] and M.http_status(e.code) == 409
    assert not sql("SELECT 1 FROM records WHERE id=%s AND trashed_at IS NOT NULL", (x2[r["original_id"]]["target_id"],))
    assert M.plans_list(B)["plans"][0]["state"] == "applied"
    # c 기록을 근거로 든 후보 = REVERT-MODIFIED
    r3 = T.rec(350, "후보가 붙을 기록 원문이다")
    st3 = stage(B, [r3])
    pv3 = X.migration_apply_preview(B, st3["plan_id"])
    rid3 = by_oid(X.migration_apply(B, st3["plan_id"], pv3["plan_hash"], pv3["expected_counts"]))[r3["original_id"]]["target_id"]
    db.candidates_propose(B, rid3, "", [{"text": "후보", "quote": "후보가 붙을 기록"}], "ai")
    e = expect("REVERT-MODIFIED", X.migration_revert, B, st3["plan_id"])
    assert e.detail["seqs"] == [0]
    # c 반영 뒤 수기 수정(record_edit — record_history) = REVERT-MODIFIED(후보·연결이 없어도)
    r5 = T.rec(351, "고칠 이관 기록 원문이다")
    st5 = stage(B, [r5])
    pv5 = X.migration_apply_preview(B, st5["plan_id"])
    rid5 = by_oid(X.migration_apply(B, st5["plan_id"], pv5["plan_hash"], pv5["expected_counts"]))[r5["original_id"]]["target_id"]
    db.record_edit(B, rid5, 1, "고칠", "고친")
    e = expect("REVERT-MODIFIED", X.migration_revert, B, st5["plan_id"])
    assert e.detail["seqs"] == [0]
    assert not sql("SELECT 1 FROM records WHERE id=%s AND trashed_at IS NOT NULL", (rid5,))
    # e 기존 대상 갱신분 = kept_updated(휴지통 아님) · 더 새 판이 생긴 앞 plan 은 REVERT-MODIFIED
    ax2 = T.axis(340, "되돌리기 축(고침)")
    st4 = stage(B, [ax2])
    pv4 = X.migration_apply_preview(B, st4["plan_id"])
    rc4 = X.migration_apply(B, st4["plan_id"], pv4["plan_hash"], pv4["expected_counts"])
    assert rc4["items"][0]["created"] is False and rc4["counts"]["kept_on_revert"] == 1
    rv4 = X.migration_revert(B, st4["plan_id"])
    assert rv4["trashed"] == {"record": 0, "item": 0} and rv4["kept_updated"] == 1 and rv4["restore_until"] is None
    assert not sql("SELECT 1 FROM items WHERE id=%s AND trashed_at IS NOT NULL", (x2[ax["original_id"]]["target_id"],))
    e = expect("REVERT-MODIFIED", X.migration_revert, B, st2["plan_id"])
    assert seq_of(st2, ax) in e.detail["seqs"]
    ok("revert: a 출처 유지(kept_source) · b 접수 reverted → 같은 판 재stage = insert · c 기준 확정·후보·수기 수정·더 새 판 = REVERT-MODIFIED(전체) · "
       "d reverted·두 번째 noop·한도 안 되돌림·영수증 reverted · e 새로 만든 것만 휴지통, 갱신분 kept_updated · 휴지통 꺼짐 SWITCH-OFF")


def test_no_web_revert():
    import web
    src = Path(web.__file__).read_text(encoding="utf-8")
    assert "plan_revert" not in src and "/revert" not in src.replace("/api/migration-tokens/{tid}/revoke", ""), "웹 revert API 없음"
    ok("웹: revert 경로·버튼 없음(이번 PR 은 MCP 만)")


def run(A, B):
    """test_migration_path.main_ 이 사용자·스위치를 만든 뒤 부른다(같은 DB). 끝나면 스위치를 끈다."""
    try:
        test_upgrade()
        mcp(True)
        trash(False)
        test_switch(A, B)
        test_web_equals_mcp(A, B)
        test_nested_tx_scope_apply_revert(A)
        test_rules_binding(B)
        trash(True)
        test_keep_confirmed(A)
        test_revert(B)
        test_no_web_revert()
    finally:
        mcp(False)
        trash(False)
    ok("이관 MCP(가안 X) 시험 전부 통과")


if __name__ == "__main__":
    db.init_schema()
    T.cleanup()
    T.switches(True, [])
    A = db.user_by_email(T.A_EMAIL)["id"]
    B = db.user_by_email(T.B_EMAIL)["id"]
    db.display_name_set(A, "이관 시험")
    db.display_name_set(B, "이관 다른 사람")
    T.switches(True, [A, B])
    try:
        # 옛 행(via·created NULL) 이 있어야 업그레이드 시험이 의미 있다 — 웹 반영 plan 하나를 먼저 만든다
        st = stage(A, [T.rec(390, "업그레이드 전 반영")])
        M.plan_apply(A, st["plan_id"], st["plan_hash"])
        with db.tx() as c:
            c.execute("UPDATE migration_plans SET via=NULL WHERE id=%s", (st["plan_id"],))
            c.execute("UPDATE migration_plan_items SET created=NULL WHERE plan_id=%s", (st["plan_id"],))
        run(A, B)
    finally:
        T.cleanup()
        db.close()
