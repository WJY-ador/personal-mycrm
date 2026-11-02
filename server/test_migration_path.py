"""이관 경로(2026-11-02) 시험 — 합성 PostgreSQL. notes/2026-11-02_이관경로-구현계획.md 「검증」 목록.

실행: DATABASE_URL=postgresql://localhost/crm_test_migration CRM_DEV=1 CRM_DEV_USER=mig-a@example.com AUTHKIT_ISSUER=https://fake.authkit.test \
      CRM_PUBLIC_URL=http://127.0.0.1:8800 python3 server/test_migration_path.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

A. 서버 함수(migration.py): 정규화 벡터 · 토큰(스위치·allowlist·폐기·만료·imp 토큰 거절) · 업로드(owner 필드·offset·중복·plan 불일치·한도)
   · seal(허용/거절 사유 — pending·unknown·URL·internal·file_mtime·모순·해시·session_story · 같은 해시 다른 id warn·distinct)
   · 반영(plan_hash 대조·기준 미체크 skipped·미체크 의존 거절·두 번째 반영 noop·재업로드 noop·plan 상태 변화 = PLAN-STALE 전부 롤백
   · 한도 초과 시작 안 함·일반 한도 분리) · 날짜 종류 매핑 · 적격 판정(_ELIGIBLE_SQL) · provenance_set 잠금 · 만료·취소 영구 삭제 · 사용자 격리
   · 영수증·read-back 해시.
B. HTTP(web.py 라우트 — 토큰 경로·웹 세션 경로): test_http() — ③ 에서 더한다.
C. 이관 MCP(가안 X): test_migration_mcp.run(A, B) — 업그레이드·스위치·웹=MCP·규칙·바인딩·revert.
"""
import asyncio
import datetime as dt
import hashlib
import json
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_migration). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "mig-a@example.com"   # CI job env(tester@…)를 덮는다 — MCP 직접 호출이 env 의 DEV 사용자로 풀린다
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import db  # noqa: E402
import imports  # noqa: E402
import migration as M  # noqa: E402

A_EMAIL, B_EMAIL = "mig-a@example.com", "mig-b@example.com"
INST = "pc-test-1"
TS = "2025-03-01T10:00:00+09:00"


def ok(msg):
    print("OK —", msg, flush=True)


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (code, e.code, e.message)
        return e
    raise AssertionError(f"{code} 가 나야 하는데 성공했다")


def sql(q, args=()):
    with db.tx() as c:
        return c.execute(q, args).fetchall() if q.lstrip().upper().startswith(("SELECT", "WITH")) or "RETURNING" in q.upper() else \
            c.execute(q, args).rowcount


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", ([A_EMAIL, B_EMAIL],)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def switches(on=True, users=()):
    os.environ["CRM_BOARD_MIGRATION_ENABLED"] = "1" if on else ""
    os.environ["CRM_BOARD_MIGRATION_USERS"] = ",".join(users)


# ── 항목 만들기 ───────────────────────────────────────────

def oid(n):
    return "o_" + hashlib.sha256(f"{INST}\npath/{n}\nanchor".encode()).hexdigest()[:32]


def finish(item, keep_hash=False):
    if not keep_hash:
        item["content_hash"] = M.content_hash(M._content_text(item))
    item.pop("source_revision", None)
    item["source_revision"] = "v_" + hashlib.sha256(imports.jcs(item)).hexdigest()[:32]
    return item


def prov(**kw):
    d = {"author_kind": "self", "text_process": "verbatim", "generation_kind": "human",
         "primary_date": {"kind": "written", "value": TS}, "review": {"state": "reviewed", "decision_ref": "rv-1"}, "sensitivity": "normal"}
    d.update(kw)
    return d


def rec(n, body, keep_hash=False, **kw):
    it = {"original_id": oid(n), "source_instance": INST, "unit_kind": "record", "content_hash": "0" * 64, "body": body, **prov()}
    it.update(kw)
    return finish(it, keep_hash)


def principle(n, title, **kw):
    it = {"original_id": oid(n), "source_instance": INST, "unit_kind": "principle_c", "content_hash": "0" * 64,
          "object_ref": {"std_id": "std:principles"}, "title": title, "body": f"{title} 본문", **prov()}
    it.update(kw)
    return finish(it)


def axis(n, title, **kw):
    it = {"original_id": oid(n), "source_instance": INST, "unit_kind": "axis", "content_hash": "0" * 64,
          "object_ref": {"std_id": "std:axes"}, "title": title, "body": "", "fields": {"keywords": [title]}, **prov()}
    it.update(kw)
    return finish(it)


def source(n, name, kind="file"):
    return finish({"original_id": oid(n), "source_instance": INST, "unit_kind": "source", "content_hash": "0" * 64,
                   "source": {"kind": kind, "name": name, "location": hashlib.sha256(f"anchor-{n}".encode()).hexdigest()}})


def jsonl(items):
    return "".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items).encode("utf-8")


def stage(tok, items, chunk=None):
    """plan 만들기 → 청크 업로드 → seal. 반환 seal 결과."""
    p = M.plan_create(tok, {"contract": M.CONTRACT, "source_instance": INST})
    off = 0
    step = chunk or len(items)
    for i in range(0, len(items), step):
        r = M.plan_upload(tok, p["plan_id"], jsonl(items[i:i + step]), off)
        off = r["received"]
    return M.plan_seal(tok, p["plan_id"], off)


def acts(st):
    return {x["original_id"]: (x["action"], x["reason"]) for x in st["items"]}


def counts(uid):
    r = sql("SELECT (SELECT count(*) FROM records WHERE user_id=%s) AS r, (SELECT count(*) FROM items WHERE user_id=%s AND revision > 0) AS i, "
            "(SELECT count(*) FROM sources WHERE user_id=%s) AS s, (SELECT count(*) FROM import_entries WHERE user_id=%s) AS e",
            (uid, uid, uid, uid))[0]
    return dict(r)


# ── A. 서버 함수 ──────────────────────────────────────────

def test_vectors():
    d = json.loads((HERE / "contract" / "imports" / "vectors" / "board-migration-2-normalize.json").read_text(encoding="utf-8"))
    assert d["contract"] == M.CONTRACT and len(d["vectors"]) >= 15
    for v in d["vectors"]:
        assert M.normalize(v["input"]) == v["normalized"], v["name"]
        assert M.content_hash(v["input"]) == v["sha256"], v["name"]
    json.loads((HERE / "contract" / "imports" / "board-migration-2.schema.json").read_text(encoding="utf-8"))
    ok(f"정규화 벡터 {len(d['vectors'])}개(NFC·CRLF·줄끝 공백·CR·U+3000·BOM) = 서버 normalize · 계약 스키마 JSON")


def test_tokens(A, B):
    switches(False, [A])
    expect("MIGRATION-OFF", M.token_issue, A)
    switches(True, [])
    expect("MIGRATION-NOT-ALLOWED", M.token_issue, A)
    switches(True, [A])
    t1 = M.token_issue(A)
    assert t1["token"].startswith("mig_mt_") and t1["info"]["active"] and "secret_hash" not in t1["info"]
    a = M.authenticate("Bearer " + t1["token"])
    assert a == {"user_id": A, "token_id": t1["info"]["id"]}
    t2 = M.token_issue(A)   # 새로 발급 = 앞 토큰 폐기(사용자당 1개)
    expect("TOKEN-REVOKED", M.authenticate, "Bearer " + t1["token"])
    M.authenticate("Bearer " + t2["token"])
    expect("AUTH-INVALID", M.authenticate, "Bearer " + t2["token"][:-1] + ("A" if t2["token"][-1] != "A" else "B"))
    expect("AUTH-INVALID", M.authenticate, "Bearer imp_is_" + "0" * 24 + ".it_" + "0" * 16 + "." + "x" * 43)   # 일반 장치 토큰 꼴 거절
    expect("AUTH-INVALID", M.authenticate, "")
    switches(True, [B])   # allowlist 에서 빠지면 토큰이 살아 있어도 못 쓴다
    expect("MIGRATION-NOT-ALLOWED", M.authenticate, "Bearer " + t2["token"])
    switches(False, [A])
    expect("MIGRATION-OFF", M.authenticate, "Bearer " + t2["token"])
    switches(True, [A, B])
    sql("UPDATE migration_tokens SET expires_at = now() - interval '1 second', created_at = now() - interval '1 day' WHERE id=%s",
        (t2["info"]["id"],))
    expect("TOKEN-EXPIRED", M.authenticate, "Bearer " + t2["token"])
    t3 = M.token_issue(A)
    M.token_revoke(A, t3["info"]["id"])
    expect("TOKEN-REVOKED", M.authenticate, "Bearer " + t3["token"])
    expect("NOT-FOUND", M.token_revoke, B, t3["info"]["id"])   # 남의 토큰
    st = M.token_status(A)
    assert st["enabled"] and st["allowed"] and st["token_days"] == 14 and not any(x["active"] for x in st["tokens"])
    assert all("secret" not in json.dumps(x) for x in st["tokens"])
    assert sql("SELECT count(*) AS n FROM admin_audit WHERE action='migration_token' AND actor_id=%s", (A,))[0]["n"] == 3
    ok("토큰: 스위치·allowlist(발급·사용 때마다) · 사용자당 1개 · 폐기·만료·변조·imp 토큰 거절 · 남의 토큰 404 · 감사 migration_token")


def test_upload(A):
    tok = {"user_id": A, "token_id": None}
    for bad in ({"contract": M.CONTRACT, "source_instance": INST, "owner": A}, {"contract": M.CONTRACT, "source_instance": INST, "user_id": A},
                {"contract": "board-migration/1", "source_instance": INST}, {"contract": M.CONTRACT, "source_instance": "a b"}):
        expect("CONTRACT-INVALID", M.plan_create, tok, bad)
    p = M.plan_create(tok, {"contract": M.CONTRACT, "source_instance": INST})
    assert p["state"] == "staged" and p["item_count"] == 0
    pid = p["plan_id"]
    r1 = rec(1, "업로드 시험 하나")
    e = expect("CHUNK-OFFSET", M.plan_upload, tok, pid, jsonl([r1]), 3)
    assert e.detail["received"] == 0
    for item, rule in (({**r1, "owner_id": A}, "owner_field_not_allowed"), ({**r1, "source_instance": "pc-other"}, "plan_mismatch"),
                       ({**r1, "extra": 1}, "unknown_field"), ({**r1, "author_kind": "me"}, "enum"),
                       ({**r1, "primary_date": {"kind": "mtime", "value": TS}}, "enum"), ({**r1, "body": "a\x00b"}, "invalid_char")):
        e = expect("CONTRACT-INVALID", M.plan_upload, tok, pid, jsonl([item]), 0)
        assert rule in e.message, (rule, e.message)
    e = expect("CONTRACT-INVALID", M.plan_upload, tok, pid, b'{"a": 1.5}\n', 0)
    assert "lines[0]" in e.message
    assert M.plan_upload(tok, pid, jsonl([r1]), 0)["received"] == 1
    e = expect("CONTRACT-INVALID", M.plan_upload, tok, pid, jsonl([rec(2, "둘"), r1]), 1)   # 같은 plan 안 같은 original_id
    assert "duplicate_in_plan" in e.message
    assert M.plan_status(tok, pid)["item_count"] == 1, "청크 하나는 전부 또는 전무"
    old = M.USER_STAGING_MAX_BYTES
    M.USER_STAGING_MAX_BYTES = 10
    try:
        expect("STAGING-FULL", M.plan_upload, tok, pid, jsonl([rec(3, "셋")]), 1)
    finally:
        M.USER_STAGING_MAX_BYTES = old
    expect("PLAN-COUNT-MISMATCH", M.plan_seal, tok, pid, 2)
    ps = [M.plan_create(tok, {"contract": M.CONTRACT, "source_instance": INST}) for _ in range(M.OPEN_PLANS_MAX - 1)]
    expect("PLAN-LIMIT", M.plan_create, tok, {"contract": M.CONTRACT, "source_instance": INST})
    for x in ps + [p]:
        M.plan_cancel(A, x["plan_id"])
    assert sql("SELECT count(*) AS n FROM migration_plan_items WHERE user_id=%s AND payload IS NOT NULL", (A,))[0]["n"] == 0, "취소 = 본문 삭제"
    expect("PLAN-STATE", M.plan_upload, tok, pid, jsonl([rec(3, "셋")]), 1)
    ok("업로드: owner·user 필드 거절 · 계약 · offset(received) · 구조 거절은 청크 전체 · plan 안 중복 · 스테이징 2MB · 열린 plan 3 · 취소 = 본문 즉시 삭제")


def test_seal_apply(A, B):
    tok = {"user_id": A, "token_id": None}
    ax = axis(10, "축 하나")
    p1 = principle(11, "기준 하나", references=[{"field_key": "axes", "target": {"original_id": ax["original_id"], "revision": ax["source_revision"]}}])
    p2 = principle(12, "기준 둘(체크 안 함)")
    src = source(13, "회고 노트")
    good = rec(1, "내가 쓴 원문이다.\r\n둘째 줄  \n", title="원문", source_ref={"original_id": src["original_id"]},
               other_dates=[{"kind": "registered", "value": "2025-03-05"}])
    occ = rec(2, "발생일만 아는 글", primary_date={"kind": "occurred", "value": "2024-12-31"})
    reg = rec(3, "등록일 글", primary_date={"kind": "registered", "value": "2024-11-11"})
    head = rec(4, "제목 날짜 글", primary_date={"kind": "heading", "value": "2024-10-10T23:30:00-05:00"})
    nodate = rec(5, "날짜 모름", primary_date=None)
    aiw = rec(6, "AI 가 다시 쓴 요약", generation_kind="ai", text_process="rewritten")
    dup1 = rec(7, "반복되는 짧은 글")
    dup2 = rec(8, "반복되는 짧은 글")
    dup3 = rec(9, "반복되는 짧은 글", distinct=True)
    bad = {"pending": rec(20, "검토 중", review={"state": "pending"}), "unknown": rec(21, "모름", author_kind="unknown"),
           "url": rec(22, "링크 https://example.com/x 있음"), "email": rec(23, "메일 a@b.co 있음"), "path": rec(24, "경로 ~/Personal/x 있음"),
           "internal": rec(25, "고객 내부", sensitivity="internal"), "mtime": rec(26, "수정일", primary_date={"kind": "file_mtime", "value": TS}),
           "contra": rec(27, "모순", generation_kind="mixed"), "external": rec(28, "남의 글", author_kind="external"),
           "hash": rec(29, "해시 다름", keep_hash=True), "story": rec(30, "세션 이야기", unit_kind="session_story"),
           "date": rec(31, "날짜 틀림", primary_date={"kind": "written", "value": "2025-13-40"})}
    items = [good, occ, reg, head, nodate, aiw, dup1, dup2, dup3, ax, p1, p2, src] + list(bad.values())
    before = counts(A)
    st = stage(tok, items, chunk=7)
    assert counts(A) == before, "seal(dry-run) = 업무 쓰기 0"
    a = acts(st)
    want_reject = {"pending": "review_pending", "unknown": "provenance_unknown", "url": "url_not_allowed", "email": "email_not_allowed",
                   "path": "path_not_allowed", "internal": "sensitivity_internal", "mtime": "file_mtime_not_allowed",
                   "contra": "provenance_contradiction", "external": "scope_self_only", "hash": "content_hash_mismatch", "story": "unit_deferred",
                   "date": "date_invalid"}
    for k, why in want_reject.items():
        assert a[bad[k]["original_id"]] == ("reject", why), (k, a[bad[k]["original_id"]])
    for it in (good, occ, reg, head, nodate, aiw, dup3, ax, p1, p2, src):
        assert a[it["original_id"]] == ("insert", None), (it.get("title") or it.get("body"), a[it["original_id"]])
    assert a[dup1["original_id"]] == ("warn", "duplicate_content") and a[dup2["original_id"]] == ("warn", "duplicate_content")
    assert st["state"] == "sealed" and len(st["plan_hash"]) == 64 and st["counts"]["actions"]["reject"] == len(bad)
    pid = st["plan_id"]
    assert M.plan_hash_of([hashlib.sha256(imports.jcs(i)).digest() for i in items]) == st["plan_hash"], "plan_hash = 항목 JCS 해시 목록"
    gone = sql("SELECT count(*) AS n FROM migration_plan_items WHERE plan_id=%s AND action='reject' AND payload IS NOT NULL", (pid,))[0]["n"]
    assert gone == 0, "reject 항목 본문은 seal 때 지운다"
    det = M.plan_detail(A, pid)
    need = {x["seq"] for x in det["items"] if x["needs_check"]}
    assert len(need) == 2 and all(not x["checked"] for x in det["items"])
    full = M.plan_item(A, pid, next(x["seq"] for x in det["items"] if x["original_id"] == good["original_id"]))
    assert full["payload"]["body"] == good["body"], "항목 전문 = 받은 그대로"
    # 기준 체크 — p1 만. p2 는 미체크(skipped_unchecked)
    s1 = next(x["seq"] for x in det["items"] if x["original_id"] == p1["original_id"])
    expect("ARG-INVALID", M.plan_check, A, pid, [0], True)   # 기준 아닌 항목
    M.plan_check(A, pid, [s1], True)
    expect("PLAN-HASH-MISMATCH", M.plan_apply, A, pid, "f" * 64)
    expect("NOT-FOUND", M.plan_apply, B, pid, st["plan_hash"])   # 사용자 격리(B 도 allowlist)
    expect("NOT-FOUND", M.plan_detail, B, pid)
    expect("NOT-FOUND", M.plan_status, {"user_id": B, "token_id": None}, pid)
    rc = M.plan_apply(A, pid, st["plan_hash"])
    assert rc["already_applied"] is False and rc["import_batch_id"] == pid
    res = {x["original_id"]: x for x in rc["items"]}
    assert res[p2["original_id"]]["result"] == "skipped_unchecked" and res[p2["original_id"]]["target_id"] is None
    assert res[dup1["original_id"]]["result"] == "skipped_warn" and res[bad["url"]["original_id"]]["result"] == "skipped_reject"
    for it in (good, occ, reg, head, nodate, aiw, dup3, ax, p1, src):
        x = res[it["original_id"]]
        assert x["result"] == "applied" and x["target_id"] and x["stored_hash"] == it["content_hash"] and x["target_state"] == "live", x
    after = counts(A)
    assert after["r"] - before["r"] == 7 and after["i"] - before["i"] == 2 and after["s"] - before["s"] == 1, (before, after)
    assert sql("SELECT count(*) AS n FROM migration_plan_items WHERE plan_id=%s AND payload IS NOT NULL", (pid,))[0]["n"] == 0, "반영 뒤 본문 삭제"
    # 기록 = 신고 provenance · 날짜 종류 · 출처 연결 · 적격(_ELIGIBLE_SQL)
    rid = {k: res[v["original_id"]]["target_id"] for k, v in (("good", good), ("occ", occ), ("reg", reg), ("head", head), ("nodate", nodate),
                                                               ("aiw", aiw))}
    rows = {r["id"]: r for r in sql(f"SELECT r.*, ({db._ELIGIBLE_SQL}) AS eligible FROM records r WHERE r.id = ANY(%s)", (list(rid.values()),))}
    g = rows[rid["good"]]
    assert (g["author_kind"], g["text_process"], g["generation_kind"], g["ingest_kind"], g["import_batch_id"]) == \
        ("self", "verbatim", "human", "board_migration", pid)
    assert g["body"] == good["body"], "본문 = 받은 그대로(정규화는 해시에만)"
    assert g["date_kind"] == "written" and g["source_created_at"] == dt.datetime.fromisoformat(TS) and g["created"] == g["source_created_at"]
    assert g["source_id"] == res[src["original_id"]]["target_id"] and g["eligible"]
    assert g["provenance_history"][0]["other_dates"] == [{"kind": "registered", "value": "2025-03-05"}]
    o = rows[rid["occ"]]
    assert o["date_kind"] == "occurred" and str(o["source_date"]) == "2024-12-31" and o["source_created_at"] is None
    assert o["created"] > dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1), "날짜만 = created 는 받은 시각(자정을 만들지 않는다)"
    r_ = rows[rid["reg"]]
    assert r_["date_kind"] == "registered" and str(r_["source_date"]) == "2024-11-11" and r_["created"] > o["created"] - dt.timedelta(hours=1)
    h = rows[rid["head"]]
    assert h["date_kind"] == "heading" and str(h["source_date"]) == "2024-10-10", "시각 값 = 그 값에 적힌 날짜"
    n_ = rows[rid["nodate"]]
    assert n_["date_kind"] is None and n_["source_date"] is None and n_["source_created_at"] is None
    w = rows[rid["aiw"]]
    assert (w["generation_kind"], w["text_process"]) == ("ai", "rewritten") and not w["eligible"], "ai = 비적격"
    expect("PROVENANCE-MIGRATION-LOCKED", db.record_provenance_set, A, rid["aiw"], "self", "verbatim", "사후 승격 시도")
    expect("PROVENANCE-MIGRATION-LOCKED", db.record_provenance_set, A, rid["good"], "unknown", "verbatim", "강등")
    pi = sql("SELECT generation_kind, generation_meta, ingest_kind FROM items WHERE id=%s", (res[p1["original_id"]]["target_id"],))[0]
    assert pi["ingest_kind"] == "board_migration" and pi["generation_kind"] == "human" and pi["generation_meta"]["author_kind"] == "self"
    links = sql("SELECT target_item_id FROM item_links WHERE source_item_id=%s", (res[p1["original_id"]]["target_id"],))
    assert [x["target_item_id"] for x in links] == [res[ax["original_id"]]["target_id"]], "references(original_id) = 같은 plan 의 축"
    # 두 번째 반영 = noop(같은 영수증)
    rc2 = M.plan_apply(A, pid, st["plan_hash"])
    assert rc2["already_applied"] is True and rc2["receipt_hash"] == rc["receipt_hash"] and counts(A) == after
    assert M.receipt(A)["plan_id"] == pid
    assert sql("SELECT count(*) AS n FROM admin_audit WHERE action='migration_apply' AND actor_id=%s", (A,))[0]["n"] == 1
    # 멱등 재업로드 — 같은 항목 새 plan = 전부 noop(기준 p2 는 이번에 insert)
    st2 = stage(tok, [good, occ, ax, p1, src, p2])
    a2 = acts(st2)
    assert all(a2[i["original_id"]] == ("noop", None) for i in (good, occ, ax, p1, src)), a2
    assert a2[p2["original_id"]] == ("insert", None)
    det2 = M.plan_detail(A, st2["plan_id"])
    M.plan_check(A, st2["plan_id"], [x["seq"] for x in det2["items"] if x["needs_check"]], True)
    rc3 = M.plan_apply(A, st2["plan_id"], st2["plan_hash"])
    r3 = {x["original_id"]: x["result"] for x in rc3["items"]}
    assert r3[p2["original_id"]] == "applied" and all(r3[i["original_id"]] == "noop" for i in (good, occ, ax, p1, src))
    assert counts(A)["r"] == after["r"] and counts(A)["i"] == after["i"] + 1
    # 같은 해시 다른 id — 앞서 반영한 plan 과 대조(warn) · supersedes 면 넘어감
    again = rec(40, "내가 쓴 원문이다.\r\n둘째 줄  \n")
    sup = rec(41, "발생일만 아는 글", supersedes=occ["original_id"])
    a4 = acts(stage(tok, [again, sup]))
    assert a4[again["original_id"]] == ("warn", "duplicate_content") and a4[sup["original_id"]] == ("insert", None)
    for x in M.plans_list(A)["plans"]:
        if x["state"] == "sealed":
            M.plan_cancel(A, x["plan_id"])
    ok("seal: 거절 12종(pending·unknown·URL·이메일·경로·internal·file_mtime·모순·external·해시·session_story·날짜) · warn(같은 해시 다른 id, "
       "distinct·supersedes 넘김) · dry-run 쓰기 0 · reject 본문 즉시 삭제 · plan_hash")
    ok("반영: plan_hash 대조 · 기준 체크만 반영(skipped_unchecked) · 사용자 격리 · 신고 provenance 저장·적격(_ELIGIBLE_SQL, ai 비적격) · "
       "provenance_set 잠금 · 날짜 종류 매핑(written 시각=created · 날짜만·registered·heading = source_date+라벨) · 출처 연결 · 축 참조 · "
       "본문 삭제 · 두 번째 반영 noop · 재업로드 noop · read-back 해시")
    return {"good": good, "src": src}


def test_stale_limits(A):
    tok = {"user_id": A, "token_id": None}
    # 1) 기준 미체크 의존 = 시작 전 거절
    pr = principle(50, "의존 대상 기준")
    rr = rec(51, "기준에 붙는 기록", attach={"attach_to": [{"original_id": pr["original_id"], "revision": pr["source_revision"]}]})
    st = stage(tok, [pr, rr])
    assert acts(st)[rr["original_id"]] == ("insert", None), acts(st)
    before = counts(A)
    e = expect("CHECK-DEPENDENCY", M.plan_apply, A, st["plan_id"], st["plan_hash"])
    assert e.detail["seqs"] == [1] and counts(A) == before
    M.plan_cancel(A, st["plan_id"])
    # 2) seal 뒤 서버 상태 변화 → PLAN-STALE, 전부 롤백
    x1, x2, xs = rec(60, "먼저 들어갈 글"), rec(61, "같이 들어갈 글"), source(62, "새 출처")
    s1 = stage(tok, [x1, x2, xs])
    s2 = stage(tok, [x1])
    M.plan_apply(A, s2["plan_id"], s2["plan_hash"])   # 다른 plan 이 x1 을 먼저 반영 → s1 의 x1 은 이제 noop
    before = counts(A)
    e = expect("PLAN-STALE", M.plan_apply, A, s1["plan_id"], s1["plan_hash"])
    assert [(c["seq"], c["sealed"], c["now"]) for c in e.detail["changed"]] == [(0, "insert", "noop")]
    assert counts(A) == before, "PLAN-STALE = 아무것도 반영하지 않음(x2·출처 포함)"
    assert M.plan_status(tok, s1["plan_id"])["state"] == "sealed"
    M.plan_cancel(A, s1["plan_id"])
    # 3) 중간 실패 주입 → 전부 롤백
    y1, y2 = rec(70, "롤백 시험 하나"), rec(71, "롤백 시험 둘")
    s3 = stage(tok, [y1, y2])
    orig = imports._mig_record
    calls = []

    def boom(*a, **k):
        calls.append(1)
        if len(calls) == 2:
            raise db.CrmError("ARG-INVALID", "주입")
        return orig(*a, **k)
    imports._mig_record = boom
    try:
        before = counts(A)
        expect("PLAN-STALE", M.plan_apply, A, s3["plan_id"], s3["plan_hash"])
        assert counts(A) == before and len(calls) == 2, "첫 항목도 롤백"
    finally:
        imports._mig_record = orig
    # 4) 한도 — 남은 이관 한도 < 반영 행 → 시작 안 함
    used = M.plans_list(A)["limits"]["used_today"]
    old = db.DAILY_LIMITS["migration"]
    db.DAILY_LIMITS["migration"] = used + 1
    try:
        e = expect("RATE-LIMIT", M.plan_apply, A, s3["plan_id"], s3["plan_hash"])
        assert e.detail["needed"] == 2 and getattr(e, "resume_at", None) and counts(A) == before
    finally:
        db.DAILY_LIMITS["migration"] = old
    M.plan_apply(A, s3["plan_id"], s3["plan_hash"])
    # 5) 일반 한도 분리 — 이관 행은 일반 기록 50 에 들어가지 않는다
    oldr = db.DAILY_LIMITS["records"]
    db.DAILY_LIMITS["records"] = 1
    try:
        db.record_add(A, "", "이관한 날에도 직접 쓴 기록 1편은 된다")
        expect("RATE-LIMIT", db.record_add, A, "", "둘째는 일반 한도 1 에 걸린다")
    finally:
        db.DAILY_LIMITS["records"] = oldr
    ok("PLAN-STALE(seal 뒤 상태 변화·중간 실패 = 전부 롤백) · 기준 미체크 의존 = CHECK-DEPENDENCY · 이관 한도 부족 = 시작 안 함(resume_at)"
       " · 일반 기록 한도에서 이관 행 제외")


def test_expiry(A):
    tok = {"user_id": A, "token_id": None}
    s = stage(tok, [rec(80, "만료될 글")])
    p = M.plan_create(tok, {"contract": M.CONTRACT, "source_instance": INST})
    M.plan_upload(tok, p["plan_id"], jsonl([rec(81, "스테이징만 한 글")]), 0)
    sql("UPDATE migration_plans SET expires_at = now() - interval '1 second' WHERE id = ANY(%s)", ([s["plan_id"], p["plan_id"]],))
    n = imports.expire_pending()
    assert n >= 2
    rows = sql("SELECT state, closed_at IS NOT NULL AS closed FROM migration_plans WHERE id = ANY(%s)", ([s["plan_id"], p["plan_id"]],))
    assert all(r["state"] == "expired" and r["closed"] for r in rows)
    assert sql("SELECT count(*) AS n FROM migration_plan_items WHERE plan_id = ANY(%s) AND payload IS NOT NULL",
               ([s["plan_id"], p["plan_id"]],))[0]["n"] == 0, "만료 = 본문 영구 삭제"
    expect("PLAN-EXPIRED", M.plan_apply, A, s["plan_id"], s["plan_hash"])
    # 접근 때 즉시 닫힘(정리 회차 전)
    q = stage(tok, [rec(82, "접근 때 만료")])
    sql("UPDATE migration_plans SET expires_at = now() - interval '1 second' WHERE id=%s", (q["plan_id"],))
    expect("PLAN-EXPIRED", M.plan_apply, A, q["plan_id"], q["plan_hash"])
    assert sql("SELECT count(*) AS n FROM migration_plan_items WHERE plan_id=%s AND payload IS NOT NULL", (q["plan_id"],))[0]["n"] == 0
    ok("만료(3일): 정리 회차(imports.expire_pending) · 접근 때 즉시 → expired + 본문 영구 삭제 · 반영 PLAN-EXPIRED")


async def test_http(A, B):
    """B. HTTP — 토큰 경로는 Bearer 이관 토큰만(세션·imp 토큰 불가) · 웹 세션 경로는 쿠키 세션만(토큰 불가) · 전체 흐름 · 격리 · 스위치."""
    import httpx
    import main
    site = main.site
    real = site.dev, site.dev_user
    H = {"origin": PUBLIC}
    nd = {"content-type": "application/x-ndjson"}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            site.dev, site.dev_user = True, A_EMAIL   # 웹 세션 = DEV 사용자 A
            r = await h.post("/api/migration-tokens", json={"label": "집 PC"})
            assert r.status_code == 403 and r.json()["code"] == "ORIGIN"
            r = await h.post("/api/migration-tokens", json={"label": "집 PC"}, headers=H)
            assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
            tokA = r.json()["token"]
            AUTH = {"authorization": "Bearer " + tokA}
            r = await h.get("/api/migration-tokens")
            assert r.status_code == 200 and r.json()["allowed"] and tokA.split(".")[1] not in r.text, "목록에 비밀값 없음"
            # 토큰 경로 — 세션만 있고 토큰 없음 / imp 토큰 / 틀린 토큰 → 401
            for hd in ({}, {"authorization": "Bearer imp_is_" + "0" * 24 + ".it_" + "0" * 16 + "." + "x" * 43}, {"authorization": "Bearer mig_x"}):
                r = await h.post("/api/migration/plans", json={"contract": M.CONTRACT, "source_instance": INST}, headers=hd)
                assert r.status_code == 401 and r.json()["code"] == "AUTH-INVALID", (hd, r.text)
            r = await h.post("/api/migration/plans", json={"contract": M.CONTRACT, "source_instance": INST, "user_id": B}, headers=AUTH)
            assert r.status_code == 400 and r.json()["code"] == "CONTRACT-INVALID" and "owner_field_not_allowed" in r.json()["msg"]
            r = await h.post("/api/migration/plans", content=b'{"contract": "board-migration/2", "contract": "x"}', headers=AUTH)
            assert r.status_code == 400 and r.json()["code"] == "CONTRACT-INVALID", "중복 키"
            r = await h.post("/api/migration/plans", json={"contract": M.CONTRACT, "source_instance": INST}, headers=AUTH)
            assert r.status_code == 201 and r.json()["state"] == "staged", r.text
            pid = r.json()["plan_id"]
            items = [rec(90, "HTTP 로 온 원문"), principle(91, "HTTP 기준")]
            r = await h.post(f"/api/migration/plans/{pid}/items?offset=1", content=jsonl(items), headers={**AUTH, **nd})
            assert r.status_code == 409 and r.json()["code"] == "CHUNK-OFFSET" and r.json()["detail"]["received"] == 0
            r = await h.post(f"/api/migration/plans/{pid}/items?offset=0", content=jsonl(items[:1]), headers={**AUTH, **nd})
            assert r.status_code == 200 and r.json()["received"] == 1, r.text
            r = await h.post(f"/api/migration/plans/{pid}/items?offset=1", content=jsonl(items[1:]), headers={**AUTH, **nd})
            assert r.json()["received"] == 2
            r = await h.post(f"/api/migration/plans/{pid}/items?offset=2", content=b"x" * (M.CHUNK_MAX_BYTES + 1), headers={**AUTH, **nd})
            assert r.status_code == 413 and r.json()["code"] == "PAYLOAD-LIMIT"
            r = await h.post(f"/api/migration/plans/{pid}/seal", json={"item_count": 3}, headers=AUTH)
            assert r.status_code == 409 and r.json()["code"] == "PLAN-COUNT-MISMATCH" and r.json()["detail"]["received"] == 2
            r = await h.post(f"/api/migration/plans/{pid}/seal", json={"item_count": 2}, headers=AUTH)
            assert r.status_code == 200 and r.json()["state"] == "sealed", r.text
            sealed = r.json()
            assert all("body" not in json.dumps(x) for x in sealed["items"]) and HTTP_BODY not in r.text, "토큰 응답에 본문 없음"
            r = await h.get(f"/api/migration/plans/{pid}", headers=AUTH)
            assert r.status_code == 200 and r.json()["plan_hash"] == sealed["plan_hash"]
            r = await h.get(f"/api/migration/plans/{pid}/receipt", headers=AUTH)
            assert r.status_code == 409 and r.json()["code"] == "PLAN-STATE"
            r = await h.post(f"/api/migration/plans/{pid}/apply", json={"plan_hash": sealed["plan_hash"]}, headers=AUTH)
            assert r.status_code == 404, "토큰으로 반영 경로 없음"
            # 웹 세션 경로 — 토큰만으로는 불가(DEV 끄고 쿠키 없음)
            site.dev, site.dev_user = False, ""
            for path, body in ((f"/api/migrations/{pid}/apply", {"plan_hash": sealed["plan_hash"]}), (f"/api/migrations/{pid}/check", {"seqs": [1], "checked": True}),
                               ("/api/migration-tokens", {"label": "x"})):
                r = await h.post(path, json=body, headers={**H, **AUTH})
                assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED", (path, r.text)
            for path in ("/api/migrations", f"/api/migrations/{pid}", f"/api/migrations/{pid}/items/0"):
                assert (await h.get(path, headers=AUTH)).status_code == 401, path
            site.dev, site.dev_user = True, A_EMAIL
            # 웹 확인 화면 — 목록 · 상세(제목·체크 필요) · 항목 전문 · 체크 · 반영
            r = await h.get("/api/migrations")
            assert r.status_code == 200 and any(x["plan_id"] == pid for x in r.json()["plans"]) and r.json()["limits"]["daily"] == 200
            d = (await h.get(f"/api/migrations/{pid}")).json()
            assert [x["needs_check"] for x in d["items"]] == [False, True] and d["items"][0]["title"]
            it = (await h.get(f"/api/migrations/{pid}/items/0")).json()
            assert it["payload"]["body"] == HTTP_BODY
            r = await h.post(f"/api/migrations/{pid}/check", json={"seqs": [1], "checked": True})
            assert r.status_code == 403
            r = await h.post(f"/api/migrations/{pid}/check", json={"seqs": [1], "checked": "yes"}, headers=H)
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID"
            r = await h.post(f"/api/migrations/{pid}/check", json={"seqs": [1], "checked": True}, headers=H)
            assert r.status_code == 200 and r.json()["items"][1]["checked"] is True
            r = await h.post(f"/api/migrations/{pid}/apply", json={"plan_hash": "0" * 64}, headers=H)
            assert r.status_code == 409 and r.json()["code"] == "PLAN-HASH-MISMATCH"
            r = await h.post(f"/api/migrations/{pid}/apply", json={"plan_hash": sealed["plan_hash"]}, headers=H)
            assert r.status_code == 200 and r.json()["already_applied"] is False, r.text
            rc = r.json()
            assert [x["result"] for x in rc["items"]] == ["applied", "applied"] and HTTP_BODY not in r.text
            r = await h.post(f"/api/migrations/{pid}/apply", json={"plan_hash": sealed["plan_hash"]}, headers=H)
            assert r.status_code == 200 and r.json()["already_applied"] is True and r.json()["receipt_hash"] == rc["receipt_hash"]
            r = await h.get(f"/api/migration/plans/{pid}/receipt", headers=AUTH)
            assert r.status_code == 200 and r.json()["receipt_hash"] == rc["receipt_hash"]
            assert (await h.get(f"/api/migrations/{pid}/receipt")).json()["receipt_hash"] == rc["receipt_hash"]
            # MCP 읽기 도구 — 같은 영수증(DEV 사용자 A)
            assert main.migration_receipt_get(None, pid)["receipt_hash"] == rc["receipt_hash"]
            assert main.migration_receipt_get(None)["plan_id"] == pid
            # 격리 — B 의 토큰으로 A 의 plan = 404
            site.dev_user = B_EMAIL
            tokB = (await h.post("/api/migration-tokens", json={}, headers=H)).json()["token"]
            r = await h.get(f"/api/migration/plans/{pid}", headers={"authorization": "Bearer " + tokB})
            assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND"
            assert (await h.get(f"/api/migrations/{pid}")).status_code == 404
            site.dev_user = A_EMAIL
            # 취소(토큰) · 스위치 끔
            r = await h.post("/api/migration/plans", json={"contract": M.CONTRACT, "source_instance": INST}, headers=AUTH)
            p2 = r.json()["plan_id"]
            r = await h.post(f"/api/migration/plans/{p2}/cancel", json={}, headers=AUTH)
            assert r.status_code == 200 and r.json()["state"] == "cancelled"
            switches(False, [A, B])
            r = await h.get(f"/api/migration/plans/{pid}", headers=AUTH)
            assert r.status_code == 503 and r.json()["code"] == "MIGRATION-OFF"
            r = await h.post("/api/migration-tokens", json={}, headers=H)
            assert r.status_code == 503 and r.json()["code"] == "MIGRATION-OFF"
            switches(True, [A, B])
    finally:
        site.dev, site.dev_user = real
    ok("HTTP: 토큰 경로 = Bearer mig 만(세션·imp·틀린 토큰 401) · owner 필드·중복 키 400 · offset 409 · 청크 413 · seal 수 불일치 409 · "
       "토큰 응답 본문 없음 · 토큰으로 반영 경로 없음 · 웹 세션 경로 = 쿠키만(토큰 401) · Origin 403 · 모양 400 · 확인·체크·반영·두 번째 noop · "
       "영수증 3경로(토큰·웹·MCP) 같음 · 격리 404 · 취소 · 스위치 503")


HTTP_BODY = "HTTP 로 온 원문"


def test_mcp_tool(A):
    import main
    tools = {t.name for t in main.mcp._tool_manager.list_tools()}
    assert "migration_receipt_get" in tools and "migration_receipt_get" in main.ALLOWED_TOOLS
    assert not any("migration" in n and n != "migration_receipt_get" for n in tools), "MCP 이관 쓰기 도구 없음"
    assert "migration_receipt_get" not in db.WRITE_LIMITS and "migration_receipt_get" not in main.WRITE_TOOLS
    ok("MCP: migration_receipt_get 하나(읽기 · ALLOWED_TOOLS) · 이관 쓰기 도구 없음")


def main_():
    db.init_schema()
    cleanup()
    switches(True, [])
    A = db.user_by_email(A_EMAIL)["id"]
    B = db.user_by_email(B_EMAIL)["id"]
    db.display_name_set(A, "이관 시험")
    db.display_name_set(B, "이관 다른 사람")
    switches(True, [A, B])
    try:
        test_vectors()
        test_tokens(A, B)
        switches(True, [A, B])
        test_upload(A)
        test_seal_apply(A, B)
        test_stale_limits(A)
        test_expiry(A)
        asyncio.run(test_http(A, B))
        test_mcp_tool(A)
        import test_migration_mcp   # 이관 MCP(가안 X) — 같은 DB·사용자(CI ④-g 단계 하나로 돈다)
        test_migration_mcp.run(A, B)
    finally:
        cleanup()
        db.close()
    print("OK — 이관 경로 시험 전부 통과")


if __name__ == "__main__":
    main_()
