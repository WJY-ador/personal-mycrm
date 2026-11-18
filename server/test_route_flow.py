"""자동 분류 DB 흐름 시험(2026-11-18 구조추천 명세 6.2~6.4) — route.sync, 훅, 빼기와 되돌리기, profile, op.

실행: DATABASE_URL=postgresql://localhost/crm_test_route_20261118 python3 server/test_route_flow.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 자료는 전부 가짜 문장이다.

1. 적용 → 기존 기록 backfill(exact 만 항목, partial 은 행만), 한도에 세지 않는다, 자동 분류 표시(목록, item_get, 목록 보기, 건수)
2. 새 기록 훅(record_add, 장치 즉시 승인), 기록 수정 → 같은 항목 갱신, 제목, 출처 판정, 같으면 그대로
3. 휴지통 이동과 복원, 빼기와 되돌리기, 예외는 다시 안 들어온다, ROUTE-LOCKED
4. budget 넘침과 이어 하기(매일 정리), 옛 개정 기록 제외(같은 판 재전송 noop 은 그대로)
5. structure_profile_get 꼴, 초안 버리기, 훅 실패 격리, 옛 DB 이전(items.ingest_kind route), 사용자 격리
"""
import asyncio
import json
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_route_20261118). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "route-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_SESSION_SECRET"] = "route-flow-test-secret"
os.environ["CRM_TRASH_ENABLED"] = "1"
os.environ["CRM_IMPORTS_ENABLED"] = "1"
os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import facade  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import route  # noqa: E402

MAIN, OTHER, HINT, FIT = "route-main@example.com", "route-other@example.com", "route-hint@example.com", "route-fit@example.com"
SRC = "세션 정리"
LABELS = ["어디서", "전에 가던 방향", "내가 설명한 것", "결정", "바뀐 것", "맞았나"]
SECRET_LINE = "이 문장은 profile 응답에 나오면 안 되는 가짜 본문 표식이다"


def ok(msg):
    print(f"OK — {msg}", flush=True)


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (code, e.code, e.message)
        return e
    raise AssertionError(f"{code} 기대, 성공함")


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", ([MAIN, OTHER, HINT, FIT],)).fetchall()]
    for uid in ids:
        db.user_delete(uid)


def q1(sql, args=()):
    with db.tx() as c:
        return c.execute(sql, args).fetchone()


def qa(sql, args=()):
    with db.tx() as c:
        return c.execute(sql, args).fetchall()


def pivot_body(n, decision="입력 담당부터 정한다", drop=None):
    lines = {"어디서": f"가짜 팀 회의 {n}", "전에 가던 방향": "도구부터 고르기", "내가 설명한 것": "> 사람이 먼저라고 말했다.",
             "결정": decision, "바뀐 것": "회의 순서", "맞았나": "다음 주에 본다"}
    return "".join(f"**{k}** — {v}\n" for k, v in lines.items() if k != drop)


PIVOT_DEF = {"key": "pivots", "label": "피벗", "semantic_kind": "event",
             "fields": [{"key": "happened_on", "label": "날짜", "value_type": "date", "required": True},
                        {"key": "where_", "label": "어디서", "value_type": "text", "required": True},
                        {"key": "prior_direction", "label": "전에 가던 방향", "value_type": "text"},
                        {"key": "my_words", "label": "내가 설명한 것", "value_type": "text"},
                        {"key": "decision", "label": "결정", "value_type": "text", "required": True},
                        {"key": "turned", "label": "바뀐 것", "value_type": "text"},
                        {"key": "was_right", "label": "맞았나", "value_type": "text"}],
             "policy": {"route": {"v": 1, "unit": "record", "match": {"source": SRC, "title_like": "P#. *"},
                                  "require": {"labels": LABELS}, "title": {"from": "title"},
                                  "fields": {"happened_on": {"from": "record_date"}, "where_": {"from": "label", "label": "어디서"},
                                             "prior_direction": {"from": "label", "label": "전에 가던 방향"},
                                             "my_words": {"from": "label", "label": "내가 설명한 것"},
                                             "decision": {"from": "label", "label": "결정"},
                                             "turned": {"from": "label", "label": "바뀐 것"},
                                             "was_right": {"from": "label", "label": "맞았나"}}}}}

CE_DEF = {"key": "career_evidence", "label": "경력 증거", "semantic_kind": "event",
          "fields": [{"key": "happened_on", "label": "날짜", "value_type": "date"},
                     {"key": "my_choice", "label": "내 선택", "value_type": "text_list"},
                     {"key": "open_question", "label": "열린 질문", "value_type": "text"}],
          "policy": {"route": {"v": 1, "unit": "heading", "match": {"source": SRC, "heading_like": "CE-#-#-#-#. *"},
                               "title": {"from": "heading"},
                               "fields": {"happened_on": {"from": "record_date"}, "my_choice": {"from": "key", "key": "내 선택"},
                                          "open_question": {"from": "key", "key": "열린 질문"}}}}}


def ce_body(n, k=2):
    out = "## 오늘\n가짜 하루.\n## 경력 증거 후보\n"
    for j in range(1, k + 1):
        out += f"### CE-2026-01-0{n}-{j}. 가짜 증거 {n}-{j}\n- 내 선택: 표본 검증, 전수 비교\n- 열린 질문: 가짜 질문 {j}\n"
    return out


def add(uid, title, body, **kw):
    return db.record_add(uid, title, body, source=kw.pop("source", SRC), **kw)["id"]


def apply_def(uid, d):
    p = db.definition_propose(uid, None, 0, d)
    return p["object_id"], db.definition_apply(uid, p["object_id"], p["proposal_id"], 0)


def routes(uid, oid):
    return {(r["record_id"], r["unit_key"]): r for r in qa("SELECT * FROM item_routes WHERE user_id=%s AND object_id=%s", (uid, oid))}


def routed_item(uid, oid, rid, key=""):
    r = routes(uid, oid).get((rid, key))
    return r["item_id"] if r and r["state"] == "routed" else None


def daily_n(uid, kind):
    """db._daily_gate 와 같은 셈(한도에 세는 행 수)."""
    n = 0
    for table, col, *extra in db._DAILY_SOURCES[kind]:
        cond = "".join(f" AND {x}" for x in extra)
        n += q1(f"SELECT count(*) AS n FROM {table} WHERE user_id=%s AND {col} >= {db._KST_TODAY}{cond}", (uid,))["n"]
    return n


# ── 1 ──

def test_backfill(uid):
    r_ok = [add(uid, f"P{i}. 가짜 피벗 {i}", pivot_body(i)) for i in (1, 2, 3)]
    r_part = add(uid, "P4. 가짜 일부", pivot_body(4, drop="맞았나"))
    r_other = add(uid, "가짜 메모", pivot_body(5))                     # 제목 꼴 다름
    r_src = add(uid, "P6. 다른 출처", pivot_body(6), source="대화에서 입력")
    r_tr = add(uid, "P7. 휴지통", pivot_body(7))
    db.trash_move(uid, "record", r_tr)
    p = db.definition_propose(uid, None, 0, PIVOT_DEF)
    prof = route.profile(uid)
    dr = next(d for d in prof["drafts"] if d["object_id"] == p["object_id"])
    assert (dr["has_route"], dr["would_fill"], dr["partial"], len(dr["samples"])) == (True, 3, 1, 3), dr
    assert all(s["record_id"] in r_ok and len(s["quote"]) <= 200 and s["unit_key"] == "" for s in dr["samples"]), dr["samples"]
    before = (daily_n(uid, "proposals"), daily_n(uid, "decisions"))
    out = db.definition_apply(uid, p["object_id"], p["proposal_id"], 0)
    oid = p["object_id"]
    assert out["route_sync"] == {"created": 3, "updated": 0, "removed": 0, "partial": 1, "left": 0}, out["route_sync"]
    assert (daily_n(uid, "proposals"), daily_n(uid, "decisions")) == before, "자동 분류는 제안, 결정 한도에 세지 않는다"
    rs = routes(uid, oid)
    assert {k for k, v in rs.items() if v["state"] == "routed"} == {(r, "") for r in r_ok}
    assert rs[(r_part, "")]["state"] == "partial" and rs[(r_part, "")]["reason"] == "require" and rs[(r_part, "")]["item_id"] is None
    assert (r_other, "") not in rs and (r_src, "") not in rs and (r_tr, "") not in rs
    its = db.items(uid, oid)
    assert len(its) == 3 and all(i["auto_routed"] and i["route_source"]["record_id"] in r_ok for i in its)
    it = next(i for i in its if i["route_source"]["record_id"] == r_ok[0])
    body = db.record_get(uid, r_ok[0])["body"]
    assert it["title"] == "P1. 가짜 피벗 1" and it["body"] == "" and it["data"]["where_"] == "가짜 팀 회의 1" and it["links"] == []
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", it["data"]["happened_on"])
    src = it["route_source"]
    assert (src["start"], src["end"], src["record_title"]) == (0, len(body), "P1. 가짜 피벗 1")
    sp = rs[(r_ok[0], "")]["spans"]["decision"]
    assert body[sp[0]:sp[1]] == it["data"]["decision"] == "입력 담당부터 정한다"
    row = q1("SELECT ingest_kind, revision FROM items WHERE user_id=%s AND id=%s", (uid, it["id"]))
    assert (row["ingest_kind"], row["revision"]) == ("route", 1)
    h = qa("SELECT action, event_meta FROM item_history WHERE user_id=%s AND item_id=%s", (uid, it["id"]))
    assert [(x["action"], x["event_meta"].get("ingest")) for x in h] == [("apply", "route")], h
    g = db.item_get(uid, it["id"])
    assert g["auto_routed"] and g["route_source"]["record_id"] == r_ok[0]
    d = next(x for x in db.definitions(uid) if x["id"] == oid)
    assert d["route_counts"] == {"routed": 3, "partial": 1, "excluded": 0}, d["route_counts"]
    assert all("route_counts" not in x for x in db.definitions(uid) if x["id"] != oid), "route 없는 오브젝트 응답 꼴은 그대로"
    rt = db.definition_propose(uid, oid, d["revision"], d)   # definitions 응답 그대로 되돌려 보내기(route_counts 는 읽기 전용)
    assert rt["definition"]["policy"]["route"] == d["policy"]["route"]
    route.draft_discard(uid, oid, rt["proposal_id"])
    lst = db.object_list(uid, "pivots")
    assert lst["total"] == 3 and all(r["auto_routed"] and r["route_source"]["record_id"] in r_ok for r in lst["rows"])
    info = route.item_info(uid, it["id"])
    assert info["text"] == body and info["record_title"] == "P1. 가짜 피벗 1" and route.item_info(uid, "i_nope") is None
    assert route.counts(uid)[oid]["routed"] == 3
    again = db.tx_scope
    with again() as c:
        assert route.sync(c, uid) == {"created": 0, "updated": 0, "removed": 0, "partial": 1, "left": 0}, "같으면 그대로"
    assert q1("SELECT revision FROM items WHERE user_id=%s AND id=%s", (uid, it["id"]))["revision"] == 1
    ok("적용 → backfill(exact 3 항목, partial 1 행, 다른 출처, 제목 꼴, 휴지통 제외), 한도 안 셈, 표시(목록, item_get, 목록 보기, 건수), 두 번째 맞추기 무변화")
    return oid, r_ok, r_part


# ── 2 ──

async def test_hooks(uid, oid, r_ok, r_part):
    rid = add(uid, "P8. 새 기록", pivot_body(8))
    iid = routed_item(uid, oid, rid)
    assert iid and db.item_get(uid, iid)["data"]["where_"] == "가짜 팀 회의 8"
    # 기록 수정 → 같은 항목 갱신(revision +1, 이력 한 줄 더)
    rev = db.record_get(uid, rid)["revision"]
    db.record_edit(uid, rid, rev, "입력 담당부터 정한다", "출력 담당부터 정한다")
    assert routed_item(uid, oid, rid) == iid
    g = db.item_get(uid, iid)
    assert g["data"]["decision"] == "출력 담당부터 정한다" and g["revision"] == 2 and len(g["history"]) == 2
    # 라벨 하나 지우기 → partial(항목 완전 삭제)
    db.record_edit(uid, rid, rev + 1, "**맞았나** — 다음 주에 본다\n", "")
    assert routed_item(uid, oid, rid) is None and routes(uid, oid)[(rid, "")]["state"] == "partial"
    assert not q1("SELECT 1 AS x FROM items WHERE user_id=%s AND id=%s", (uid, iid)), "휴지통 아닌 완전 삭제"
    assert not q1("SELECT 1 AS x FROM item_history WHERE user_id=%s AND item_id=%s", (uid, iid))
    db.record_edit(uid, rid, rev + 2, "**바뀐 것** — 회의 순서\n", "**바뀐 것** — 회의 순서\n**맞았나** — 다음 주에 본다\n")
    iid2 = routed_item(uid, oid, rid)
    assert iid2 and iid2 != iid
    # 제목 → 꼴이 안 맞으면 빠진다, 다시 맞으면 새 항목
    rev = db.record_get(uid, rid)["revision"]
    db.record_title_set(uid, rid, "가짜 다른 제목", rev)
    assert (rid, "") not in routes(uid, oid)
    db.record_title_set(uid, rid, "P8. 돌아온 제목", rev + 1)
    iid3 = routed_item(uid, oid, rid)
    assert iid3 and db.item_get(uid, iid3)["title"] == "P8. 돌아온 제목"
    # 출처 판정 — 정리 기록(structured, 표시 없음)은 비적격 → 내 결정 표시를 붙이면 들어온다
    r_st = add(uid, "P9. 정리 글", pivot_body(9), text_process="structured")
    assert (r_st, "") not in routes(uid, oid)
    db.record_provenance_set(uid, r_st, "self", "structured", "제가 결정했어요", decision_owner="self")
    assert routed_item(uid, oid, r_st)
    db.record_provenance_set(uid, r_st, "self", "structured", "표시를 지워요", decision_owner=None)
    assert (r_st, "") not in routes(uid, oid)
    # 장치 즉시 승인 — 새 판이 오면 옛 판 기록의 항목은 빠지고 새 기록에 생긴다. 같은 내용 재전송(noop)은 그대로
    con = imports.device_connect(uid, "가짜 PC")
    dev, tok = con["device"], con["token"]
    o = "o_" + secrets.token_hex(16)
    v1, v2, v3 = ("v_" + secrets.token_hex(16) for _ in range(3))
    body1 = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev["id"], "original_id": o, "revision": v1,
             "previous_revision": None, "kind": "self_text", "execution": "unattended", "transform_version": "session-wrap/1",
             "policy_revision": 1, "title": "P10. 장치 피벗", "body": pivot_body(10), "source_date": "2030-01-02"}
    r1 = await _post(tok, body1)
    assert r1.status_code == 201 and r1.json()["state"] == "applied", r1.text
    rec1 = r1.json()["target_id"]
    it1 = routed_item(uid, oid, rec1)
    assert it1 and db.item_get(uid, it1)["data"]["happened_on"] == "2030-01-02"
    body2 = {**body1, "revision": v2, "previous_revision": v1, "body": pivot_body(10, decision="장치에서 고친 결정")}
    r2 = await _post(tok, body2)
    rec2 = r2.json()["target_id"]
    assert rec2 != rec1 and (rec1, "") not in routes(uid, oid), "옛 개정 기록의 항목은 빠진다"
    it2 = routed_item(uid, oid, rec2)
    assert it2 and db.item_get(uid, it2)["data"]["decision"] == "장치에서 고친 결정"
    r3 = await _post(tok, {**body2, "revision": v3, "previous_revision": v2})
    assert r3.json()["state"] == "noop" and r3.json()["target_id"] == rec2, r3.text
    with db.tx_scope() as c:
        route.sync(c, uid)
    assert routed_item(uid, oid, rec2) == it2, "같은 판 재전송(noop) 뒤에도 지금 기록"
    # 3c: 뺀 단위는 장치 새 판(새 기록)에서도 다시 들어오지 않는다(같은 원본의 다른 판 기록의 excluded 를 옮겨 적는다)
    route.exclude(uid, it2, db.item_get(uid, it2)["revision"])
    v4 = "v_" + secrets.token_hex(16)
    r4 = await _post(tok, {**body2, "revision": v4, "previous_revision": v3, "body": pivot_body(10, decision="세 번째 판의 결정")})
    rec4 = r4.json()["target_id"]
    assert rec4 not in (rec1, rec2) and routes(uid, oid)[(rec4, "")]["state"] == "excluded" and routed_item(uid, oid, rec4) is None
    with db.tx_scope() as c:
        route.sync(c, uid)
    assert routed_item(uid, oid, rec4) is None, "매일 정리 뒤에도 그대로"
    ok("훅 — record_add, 기록 수정(같은 항목 갱신, 라벨 빠지면 완전 삭제), 제목, 출처 판정, 장치 즉시 승인(옛 개정 제외, noop 그대로)")
    return rid


async def _post(token, body):
    hd = {"content-type": "application/json", "authorization": "Bearer " + token,
          "idempotency-key": imports.idempotency_key(body["source_instance_id"], body["original_id"], body["revision"])}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        return await h.post("/api/imports", content=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=hd)


# ── 3 ──

def test_trash_exclude_lock(uid, oid, rid):
    iid = routed_item(uid, oid, rid)
    db.trash_move(uid, "record", rid)
    assert (rid, "") not in routes(uid, oid) and not q1("SELECT 1 AS x FROM items WHERE user_id=%s AND id=%s", (uid, iid))
    db.trash_restore(uid, "record", rid)
    iid = routed_item(uid, oid, rid)
    assert iid
    # ROUTE-LOCKED — 서버 내부 갱신만
    g = db.item_get(uid, iid)
    expect("ROUTE-LOCKED", db.item_propose, uid, oid, 1, iid, g["revision"], None, "고친 제목", "", g["data"], [])
    expect("ROUTE-LOCKED", db.item_edit, uid, iid, g["revision"], "고친 제목", "")
    expect("ROUTE-LOCKED", db.trash_move, uid, "item", iid, g["revision"])
    expect("ROUTE-LOCKED", db.item_decide, uid, iid, g["revision"], None, "archive")
    assert db.item_get(uid, iid)["revision"] == g["revision"]
    # 빼기 — 미리보기 shown, 완전 삭제, excluded 행
    snap, shown, impact, irrev = facade.PREVIEWS["item_route_exclude"](uid, {"item_id": iid, "expected_revision": g["revision"]})
    assert set(shown) == {"항목", "원문 기록", "원문 구간", "결과"} and shown["원문 기록"] == db.record_get(uid, rid)["title"]
    assert len(shown["원문 구간"]) <= 200 and not irrev
    expect("CONFLICT", route.exclude, uid, iid, g["revision"] + 5)
    out = route.exclude(uid, iid, g["revision"])
    assert out["state"] == "excluded" and not q1("SELECT 1 AS x FROM items WHERE user_id=%s AND id=%s", (uid, iid))
    assert routes(uid, oid)[(rid, "")]["state"] == "excluded"
    expect("ARG-INVALID", route.exclude, uid, iid, g["revision"])
    other = db.item_propose(uid, oid, 1, None, 0, None, "손으로 만든 항목", "", {"happened_on": "2026-01-01", "where_": "가짜",
                                                                             "decision": "가짜"}, [])
    db.item_decide(uid, other["item_id"], 0, other["proposal_id"], "apply")
    expect("ARG-INVALID", route.exclude, uid, other["item_id"], 1)   # 손으로 만든 항목 = 자동 분류 아님(고치기 잠금도 없다)
    db.item_edit(uid, other["item_id"], 1, "손으로 고친 제목", "")
    # 예외는 다시 안 들어온다 — 매일 정리, 기록 수정, 휴지통 왕복
    with db.tx_scope() as c:
        route.sync(c, uid)
    rev = db.record_get(uid, rid)["revision"]
    db.record_edit(uid, rid, rev, "회의 순서", "회의 순서와 담당")
    db.trash_move(uid, "record", rid)
    db.trash_restore(uid, "record", rid)
    assert routes(uid, oid)[(rid, "")]["state"] == "excluded" and routed_item(uid, oid, rid) is None
    assert route.counts(uid)[oid]["excluded"] == 3   # 이 기록 하나 + 장치 시험의 옛 판, 새 판(옮겨 적은 것)
    # 되돌리기 — 미리보기, 다시 맞추기
    _s, shown, _i, _r = facade.PREVIEWS["item_route_include"](uid, {"object_id": oid, "record_id": rid, "unit_key": ""})
    assert shown["원문 기록"] == db.record_get(uid, rid)["title"]
    back = route.include(uid, oid, rid, "")
    assert back["item_id"] and routed_item(uid, oid, rid) == back["item_id"]
    expect("ARG-INVALID", route.include, uid, oid, rid, "")
    ok("휴지통 이동(완전 삭제)과 복원(다시 생김), ROUTE-LOCKED 넷, 빼기(미리보기, CONFLICT, 완전 삭제), 예외 유지, 되돌리기")


# ── 4 ──

def test_budget_and_sweep(uid):
    rids = [add(uid, f"가짜 하루 {n}", ce_body(n)) for n in range(1, 4)]   # 3기록 x 2단위 = 6
    saved = route.BUDGET, route.CHUNK
    route.BUDGET, route.CHUNK = 4, 2   # 9: 기록 2편씩 트랜잭션을 나눠도 상한과 결과가 같다
    try:
        oid, out = apply_def(uid, CE_DEF)
    finally:
        route.BUDGET, route.CHUNK = saved
    assert out["route_sync"]["created"] == 4 and out["route_sync"]["left"] == 2, out["route_sync"]
    route.CHUNK = 3
    try:
        t = route.sweep(budget=1)
    finally:
        route.CHUNK = saved[1]
    assert t["created"] == 1 and t["left"] == 1 and t["failed"] == 0, t
    t = route.sweep(budget=5)
    assert t["created"] == 1 and t["left"] == 0, t
    rs = routes(uid, oid)
    assert len([r for r in rs.values() if r["state"] == "routed"]) == 6
    k = ("CE-2026-01-01-1. 가짜 증거 1-1")
    it = db.item_get(uid, rs[(rids[0], k)]["item_id"])
    assert it["title"] == k and it["data"]["my_choice"] == ["표본 검증", "전수 비교"] and it["data"]["open_question"] == "가짜 질문 1"
    body = db.record_get(uid, rids[0])["body"]
    assert body[rs[(rids[0], k)]["start_pos"]:rs[(rids[0], k)]["end_pos"]].startswith("### " + k)
    ok("budget 넘침 = left, 매일 정리(sweep)가 이어서 채움, heading 분할 1기록 n항목")
    return oid


# ── 5 ──

def test_profile_discard(uid, pivot_oid, ce_oid):
    add(uid, "가짜 잡담", "## 가짜 절\n" + SECRET_LINE + "\n**혼자 라벨** — 값\n- 혼자 키: 값\n", source="대화에서 입력")
    p = route.profile(uid)
    assert set(p) == {"kind", "objects", "unattached", "headings", "labels", "keys", "titles", "collected", "activities", "drafts",
                      "route_guide", "suggest", "notice"}, set(p)
    assert p["kind"] == "structure_profile" and isinstance(p["route_guide"], str) and p["suggest"] is False
    objs = {o["object_id"]: o for o in p["objects"]}
    assert objs[pivot_oid]["group"] == "custom" and objs[pivot_oid]["has_route"] and objs[pivot_oid]["auto_routed"] >= 1
    assert set(objs[pivot_oid]) == {"object_id", "key", "label", "semantic_kind", "group", "items", "auto_routed", "partial", "excluded", "has_route"}
    # 12: group = 화면 origin 범주(structure_svg.ORIGIN_CATEGORY) — 표준만 standard, template 계보와 사용자 것은 custom
    stds = {x["id"] for x in db.definitions(uid) if x.get("std_id")}
    assert stds and all(objs[o]["group"] == "standard" for o in stds if o in objs), "표준 = standard"
    db.template_slot_mark(uid, ce_oid, "author@1:career_evidence", {})
    p2 = route.profile(uid)
    assert {o["object_id"]: o["group"] for o in p2["objects"]}[ce_oid] == "custom", "template 계보 = custom"
    assert objs[ce_oid]["items"] == 6 and objs[ce_oid]["auto_routed"] == 6
    assert set(p["unattached"]) == {"count", "by_source"} and p["unattached"]["count"] >= 1
    heads = {h["text"]: h for h in p["headings"]}
    assert heads["CE-#-#-#-#. *"]["records"] == 3 and heads["CE-#-#-#-#. *"]["count"] == 6, p["headings"]
    labels = {x["text"] for x in p["labels"]}
    assert set(LABELS) <= labels and "혼자 라벨" not in labels, "라벨은 2편 이상만"
    assert "내 선택" in {x["text"] for x in p["keys"]} and "혼자 키" not in {x["text"] for x in p["keys"]}
    assert "P#. *" in {t["shape"] for t in p["titles"]}
    assert SECRET_LINE not in json.dumps(p, ensure_ascii=False), "본문을 싣지 않는다"
    # 초안 버리기 — 적용 전 새 오브젝트는 행 삭제, 적용된 오브젝트는 초안만
    d = db.definition_propose(uid, None, 0, {"key": "drafty", "label": "가짜 초안", "semantic_kind": "collection", "fields": []})
    expect("CONFLICT", route.draft_discard, uid, d["object_id"], "dp_nope")
    _s, shown, impact, _r = facade.PREVIEWS["definition_draft_discard"](uid, {"object_id": d["object_id"], "proposal_id": d["proposal_id"]})
    assert impact["deleted"] is True and shown["초안 이름"] == "가짜 초안"
    assert route.draft_discard(uid, d["object_id"], d["proposal_id"]) == {"object_id": d["object_id"], "discarded": True, "deleted": True}
    assert not q1("SELECT 1 AS x FROM object_defs WHERE user_id=%s AND id=%s", (uid, d["object_id"]))
    cur = next(x for x in db.definitions(uid) if x["id"] == pivot_oid)
    d2 = db.definition_propose(uid, pivot_oid, cur["revision"], {**PIVOT_DEF, "label": "피벗 새 이름"})
    assert route.draft_discard(uid, pivot_oid, d2["proposal_id"])["deleted"] is False
    assert next(x for x in db.definitions(uid) if x["id"] == pivot_oid)["proposal"] is None
    ok("structure_profile_get 꼴(키, group, 머리 꼴, 라벨과 키 2편 이상, 제목 꼴, 본문 없음), 초안 버리기(행 삭제, 초안만, CONFLICT)")


def test_hook_isolation(uid, oid):
    real = route.sync

    def boom(*a, **k):
        raise RuntimeError("가짜 실패")
    route.sync = boom
    try:
        rid = add(uid, "P11. 훅 실패", pivot_body(11))
    finally:
        route.sync = real
    assert db.record_get(uid, rid)["title"] == "P11. 훅 실패" and (rid, "") not in routes(uid, oid)
    # 필드 정의와 안 맞는 route 가 DB 에 있어도 원문 저장은 된다(시험만 정의 검사를 건너 직접 넣는다)
    with db.tx() as c:
        c.execute("UPDATE object_defs SET policy = jsonb_set(policy, '{route,fields,where_}', '{\"from\": \"bogus\"}') "
                  "WHERE user_id=%s AND id=%s", (uid, oid))
    try:
        rid2 = add(uid, "P12. 정의와 안 맞는 route", pivot_body(12))
        rev = db.record_get(uid, rid2)["revision"]
        db.record_edit(uid, rid2, rev, "가짜 팀 회의 12", "가짜 팀 회의 열둘")
        assert db.record_get(uid, rid2)["revision"] == rev + 1 and (rid2, "") not in routes(uid, oid)
        assert route.sweep()["failed"] == 0, "오브젝트마다 savepoint — 깨진 route 하나가 사용자 전체 맞추기를 실패시키지 않는다"
        ce = next(x["id"] for x in db.definitions(uid) if x["key"] == "career_evidence")
        r_ce = add(uid, "가짜 하루 9", ce_body(9, 1))   # 깨진 오브젝트가 있어도 다른 오브젝트 훅은 돈다
        assert routed_item(uid, ce, r_ce, "CE-2026-01-09-1. 가짜 증거 9-1") and (rid2, "") not in routes(uid, oid)
    finally:
        with db.tx() as c:
            c.execute("UPDATE object_defs SET policy = jsonb_set(policy, '{route,fields,where_}', '{\"from\": \"label\", \"label\": \"어디서\"}') "
                      "WHERE user_id=%s AND id=%s", (uid, oid))
    t = route.sweep()
    assert t["failed"] == 0 and routed_item(uid, oid, rid) and routed_item(uid, oid, rid2), t
    ok("훅 실패 격리(sync 예외, 정의와 안 맞는 route) — 원문 저장, 수정은 그대로, 매일 정리가 다시 맞춤")


def test_definition_checks(uid):
    bad = json.loads(json.dumps(PIVOT_DEF))
    bad["key"] = "pivots_bad"
    bad["policy"]["route"]["match"]["title_like"] = r"^P\d+\. "
    expect("ARG-INVALID", db.definition_propose, uid, None, 0, bad)
    bad["policy"]["route"]["match"]["title_like"] = "P#. *"
    bad["policy"]["route"]["fields"]["where_"] = {"from": "label"}
    expect("ARG-INVALID", db.definition_propose, uid, None, 0, bad)
    pr = {"key": "rules_x", "label": "가짜 기준", "semantic_kind": "principle", "fields": [],
          "policy": {"route": {"v": 1, "unit": "record", "match": {"source": SRC}}}}
    expect("ARG-INVALID", db.definition_propose, uid, None, 0, pr)
    # 7: 저장된 초안의 route 를 적용 직전에 다시 검사한다(시험만 정의 검사를 건너 초안을 직접 망가뜨린다)
    q = db.definition_propose(uid, None, 0, {**json.loads(json.dumps(PIVOT_DEF)), "key": "pivots_z"})
    with db.tx() as c:
        c.execute("UPDATE object_defs SET draft_doc = jsonb_set(draft_doc, '{policy,route,match,title_like}', to_jsonb(%s::text)) "
                  "WHERE user_id=%s AND id=%s", ("^P\\d+", uid, q["object_id"]))
    expect("ARG-INVALID", db.definition_apply, uid, q["object_id"], q["proposal_id"], 0)
    assert q1("SELECT revision FROM object_defs WHERE user_id=%s AND id=%s", (uid, q["object_id"]))["revision"] == 0, "적용 안 됨"
    ok("정의 검증 — 정규식, 빈 규칙, principle = ARG-INVALID, 적용 직전 초안 route 재검사")


def test_release_archive_stack(uid):
    """메인 결정(2026-11-18 후속 3, 4) — 보관은 행과 잠금 유지, 복구하면 다시 맞춤, route 를 뺀 적용 = 행 전부 지움, 항목은 보통 항목
   , 대화 확정(stack_service._bump)이 자동 분류 항목을 고치려 하면 ROUTE-LOCKED."""
    import stack_service
    d = json.loads(json.dumps(PIVOT_DEF))
    d["key"], d["label"] = "pivots_q", "가짜 Q"
    d["policy"]["route"]["match"]["title_like"] = "Q#. *"
    r1, r2 = add(uid, "Q1. 가짜", pivot_body(21)), add(uid, "Q2. 가짜", pivot_body(22))
    r3 = add(uid, "Q3. 가짜 일부", pivot_body(23, drop="맞았나"))
    oid, out = apply_def(uid, d)
    assert (out["route_sync"]["created"], out["route_sync"]["partial"]) == (2, 1), out["route_sync"]
    i1, i2 = routed_item(uid, oid, r1), routed_item(uid, oid, r2)
    route.exclude(uid, i2, db.item_get(uid, i2)["revision"])
    # 대화 확정의 항목 갱신 자리 — 자동 분류 항목이면 ROUTE-LOCKED
    g = db.item_get(uid, i1)
    with db.tx() as c:
        snap = db._item_state(q1(f"SELECT {db._ITEM_COLS} FROM items WHERE user_id=%s AND id=%s", (uid, i1)), [])
        try:
            stack_service._bump(c, uid, i1, g["revision"], snap, "apply", "title=%s", ("가짜 대화 고침",), {})
        except db.CrmError as e:
            assert e.code == "ROUTE-LOCKED", e.code
        else:
            raise AssertionError("ROUTE-LOCKED 기대")
    assert db.item_get(uid, i1)["revision"] == g["revision"]
    # 보관 — 행과 잠금 유지, 새 기록은 안 들어감, 복구하면 다시 맞춤
    db.definition_archive(uid, oid)
    r4 = add(uid, "Q4. 보관 중 기록", pivot_body(24))
    rs = routes(uid, oid)
    assert {k[0] for k in rs} == {r1, r2, r3} and rs[(r2, "")]["state"] == "excluded"
    expect("ROUTE-LOCKED", db.trash_move, uid, "item", i1, g["revision"])
    back = db.definition_restore(uid, oid)
    assert back["route_sync"]["created"] == 1 and routed_item(uid, oid, r4), back["route_sync"]
    assert routes(uid, oid)[(r2, "")]["state"] == "excluded", "복구해도 예외는 그대로"
    # 4: 자동 분류 항목을 가리키는 연결은 만들 수 없다(record_attach, 항목 관계)
    i4 = routed_item(uid, oid, r4)
    r5 = add(uid, "가짜 메모 붙이기", "가짜 메모 본문", source="대화에서 입력")
    expect("ROUTE-LOCKED", db.record_attach, uid, r5, [{"field_key": "attach_to", "target_kind": "item", "target_id": i4}])
    # route 를 뺀 적용(검토 반영 3b) — routed 는 released(항목 유지, 표시와 잠금 없음), partial 은 지움, excluded 는 그대로
    cur = next(x for x in db.definitions(uid) if x["id"] == oid)
    nd = json.loads(json.dumps(d))
    nd["policy"].pop("route")
    p = db.definition_propose(uid, oid, cur["revision"], nd)
    res = db.definition_apply(uid, oid, p["proposal_id"], cur["revision"])
    assert res["route_sync"] == {"created": 0, "updated": 0, "removed": 0, "partial": 0, "left": 0, "released": 2}, res["route_sync"]
    assert {k[0]: v["state"] for k, v in routes(uid, oid).items()} == {r1: "released", r4: "released", r2: "excluded"}
    assert next(x for x in db.definitions(uid) if x["id"] == oid)["route_counts"] == {"routed": 0, "partial": 0, "excluded": 1}
    its = db.items(uid, oid)
    assert len(its) == 2 and not any(i.get("auto_routed") for i in its) and route.item_info(uid, i1) is None
    g = db.item_get(uid, i1)
    pp = db.item_propose(uid, oid, g["object"]["revision"], i1, g["revision"], None, "손으로 고친 Q1", "", g["data"], [])   # 잠금 풀림
    db.item_decide(uid, i1, g["revision"], pp["proposal_id"], "apply")
    assert db.item_get(uid, i1)["title"] == "손으로 고친 Q1"
    rev = db.record_get(uid, r1)["revision"]
    db.record_edit(uid, r1, rev, "가짜 팀 회의 21", "가짜 팀 회의 스물하나")
    assert db.item_get(uid, i1)["title"] == "손으로 고친 Q1", "route 가 없으니 원문 수정이 항목을 바꾸지 않는다"
    db.record_attach(uid, r5, [{"field_key": "attach_to", "target_kind": "item", "target_id": i4}])   # 놓아 준 항목에는 연결된다
    # route 를 다시 넣은 적용 — released 항목은 사용자 것이다(재검토 15). 사용자가 고친 것(i1)과 연결이 붙은 것(i4)은 그대로 두고,
    # 그 단위에 새 항목도 만들지 않는다
    cur = next(x for x in db.definitions(uid) if x["id"] == oid)
    p = db.definition_propose(uid, oid, cur["revision"], d)
    res = db.definition_apply(uid, oid, p["proposal_id"], cur["revision"])
    assert (res["route_sync"]["created"], res["route_sync"]["updated"], res["route_sync"]["partial"]) == (0, 0, 1), res["route_sync"]
    rs = routes(uid, oid)
    assert rs[(r1, "")]["state"] == "released" and db.item_get(uid, i1)["title"] == "손으로 고친 Q1", "고친 released 는 덮지 않는다"
    assert rs[(r4, "")]["state"] == "released" and rs[(r4, "")]["item_id"] == i4, "연결이 붙은 놓아 준 항목은 다시 가져가지 않는다"
    assert rs[(r2, "")]["state"] == "excluded" and len(db.items(uid, oid)) == 2, "뺀 단위는 다시 안 들어오고 항목도 늘지 않는다"
    # 16: released 행은 원문이 대상에서 빠져도 서버가 지우지 않는다(항목, 연결 그대로). 복원해도 항목 하나
    db.trash_move(uid, "record", r4)
    with db.tx_scope() as c:
        route.sync(c, uid)
    assert routes(uid, oid)[(r4, "")]["state"] == "released" and db.item_get(uid, i4)["id"] == i4
    db.trash_restore(uid, "record", r4)
    assert routes(uid, oid)[(r4, "")]["state"] == "released" and len(db.items(uid, oid)) == 2
    ok("보관(행과 잠금 유지, 복구하면 다시 맞춤), 자동 분류 항목 연결 거절, route 뺀 적용(routed = released, partial 지움, excluded 유지), "
       "다시 넣어도 고친 released, 연결 붙은 released 는 그대로(항목 둘 안 됨), released 행 유지, 대화 확정 _bump ROUTE-LOCKED")


async def test_released_rules(uid):
    """재검토 15, 16, 17 — 손대지 않은 released 는 다시 가져가고(E1R 반대), 휴지통 왕복 뒤에도 항목 하나(E2), 연결 붙은 released 는
    원문 휴지통, 매일 정리, 복원 뒤에도 항목 하나(E3), 장치 새 판으로 옮겨 적은 빼기는 계보 include 로 되돌린다(F)."""
    hd = {"key": "meets_r", "label": "가짜 회의", "semantic_kind": "event", "fields": [{"key": "dec", "label": "결정", "value_type": "text"}],
          "policy": {"route": {"v": 1, "unit": "heading", "match": {"heading_like": "회의 #*"}, "fields": {"dec": {"from": "label", "label": "결정"}}}}}

    def set_policy(oid, pol):
        cur = next(x for x in db.definitions(uid) if x["id"] == oid)
        nd = {**{k: hd[k] for k in ("key", "label", "semantic_kind", "fields")}, "policy": pol}
        p = db.definition_propose(uid, oid, cur["revision"], nd)
        return db.definition_apply(uid, oid, p["proposal_id"], cur["revision"]).get("route_sync")

    oid, _ = apply_def(uid, hd)
    ra = add(uid, "가짜 회의록 A", "## 회의 1\n**결정** 그대로\n")
    rb = add(uid, "가짜 회의록 B", "## 회의 1\n**결정** 휴지통 갈 것\n")
    ia, ib = routed_item(uid, oid, ra, "회의 1"), routed_item(uid, oid, rb, "회의 1")
    set_policy(oid, {})
    # E2: 놓아 준 항목을 휴지통에 넣고 route 를 다시 넣으면 새 항목을 만들지 않는다. 복원하면 다시 가져가 항목 하나
    db.trash_move(uid, "item", ib, db.item_get(uid, ib)["revision"])
    r = set_policy(oid, hd["policy"])
    assert r["created"] == 0, r
    assert routed_item(uid, oid, ra, "회의 1") == ia, "손대지 않은 released 는 다시 가져간다"
    assert routes(uid, oid)[(rb, "회의 1")]["state"] == "released"
    db.trash_restore(uid, "item", ib)
    with db.tx_scope() as c:
        route.sync(c, uid)
    assert routed_item(uid, oid, rb, "회의 1") == ib and len(db.items(uid, oid)) == 2, "휴지통 왕복 뒤에도 항목 하나"
    # E3: 연결 붙은 released — 원문 휴지통, 매일 정리(sync_all), 복원 뒤에도 항목 하나
    rc = add(uid, "가짜 회의록 C", "## 회의 1\n**결정** 연결 붙일 것\n")
    ic = routed_item(uid, oid, rc, "회의 1")
    set_policy(oid, {})
    rm = add(uid, "가짜 메모", "가짜 메모 본문", source="대화에서 입력")
    db.record_attach(uid, rm, [{"field_key": "attach_to", "target_kind": "item", "target_id": ic}])
    set_policy(oid, hd["policy"])
    db.trash_move(uid, "record", rc)
    route.sync_all(uid)
    db.trash_restore(uid, "record", rc)
    assert routes(uid, oid)[(rc, "회의 1")]["state"] == "released" and len(db.items(uid, oid)) == 3, "같은 단위 항목 둘이 안 된다"
    # F: 장치 새 판으로 옮겨 적은 빼기 — 새 판 기록에서 include 하면 계보 전체의 빼기를 지우고 항목이 생긴다
    con = imports.device_connect(uid, "가짜 PC 2")
    dev, tok = con["device"], con["token"]
    o, v1, v2 = "o_" + secrets.token_hex(16), "v_" + secrets.token_hex(16), "v_" + secrets.token_hex(16)
    b1 = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev["id"], "original_id": o, "revision": v1,
          "previous_revision": None, "kind": "self_text", "execution": "unattended", "transform_version": "session-wrap/1",
          "policy_revision": 1, "title": "가짜 장치 글", "body": "## 회의 1\n**결정** 판1\n", "source_date": "2030-01-02"}
    rec1 = (await _post(tok, b1)).json()["target_id"]
    i1 = routed_item(uid, oid, rec1, "회의 1")
    route.exclude(uid, i1, db.item_get(uid, i1)["revision"])
    rec2 = (await _post(tok, {**b1, "revision": v2, "previous_revision": v1, "body": "## 회의 1\n**결정** 판2\n"})).json()["target_id"]
    assert routes(uid, oid)[(rec2, "회의 1")]["state"] == "excluded"
    back = route.include(uid, oid, rec2, "회의 1")
    assert back["item_id"] and back["reason"] is None and routed_item(uid, oid, rec2, "회의 1") == back["item_id"], back
    assert (rec1, "회의 1") not in routes(uid, oid) or routes(uid, oid)[(rec1, "회의 1")]["state"] != "excluded"
    # 항목이 안 생기는 되돌리기는 reason 으로 보인다
    rp = add(uid, "가짜 회의록 P", "## 회의 1\n**결정** 뺄 것\n")
    ip = routed_item(uid, oid, rp, "회의 1")
    route.exclude(uid, ip, db.item_get(uid, ip)["revision"])
    db.trash_move(uid, "record", rp)
    back = route.include(uid, oid, rp, "회의 1")
    assert back["item_id"] is None and back["reason"] == "not_target", back
    # 18: 긴 id 는 길이 표로 거절, 오류 문장에 id 를 64자 넘게 싣지 않는다
    expect("PAYLOAD-LIMIT", route.exclude, uid, "x" * 100000, 1)
    e = expect("ARG-INVALID", route.exclude, uid, "i_" + "y" * 500, 1)
    assert "y" * 65 not in e.message, e.message
    ok("released 규칙 — 손대지 않은 것은 다시 가져감, 휴지통 왕복 뒤 항목 하나, 연결 붙은 released 유지, 계보 include, reason, id 길이")


def test_me_stats_and_axis(uid):
    """메인 결정 13, 14 — 자동 분류 항목은 나 탭의 결정, 기준 건수에서 빼고 커스텀에 센다(released 면 다시 결정). 축 오브젝트에는 route 금지."""
    d = json.loads(json.dumps(PIVOT_DEF))
    d["key"], d["label"] = "pivots_m", "가짜 M"
    d["policy"]["route"]["match"]["title_like"] = "M#. *"
    add(uid, "M1. 가짜", pivot_body(31))
    add(uid, "M2. 가짜", pivot_body(32))
    before = db.me_stats(uid)["kinds"]
    home0 = db.me_home(uid)["counts"]
    oid, out = apply_def(uid, d)
    assert out["route_sync"]["created"] == 2
    k = db.me_stats(uid)["kinds"]
    want = (before["decision"], before["principle"], before["axis"], before["custom"] + 2)
    assert (k["decision"], k["principle"], k["axis"], k["custom"]) == want, (before, k)
    home1 = db.me_home(uid)["counts"]   # 21: me_home(/api/state, MCP me_get)도 같은 기준
    assert (home1["decisions"], home1["principles"]) == (home0["decisions"], home0["principles"]), (home0, home1)
    assert home1["decisions"] == k["decision"], "me_home 결정 = me_stats 결정(촬영에서 0 과 5 로 어긋났던 것)"
    cur = next(x for x in db.definitions(uid) if x["id"] == oid)
    nd = json.loads(json.dumps(d))
    nd["policy"].pop("route")
    p = db.definition_propose(uid, oid, cur["revision"], nd)
    db.definition_apply(uid, oid, p["proposal_id"], cur["revision"])
    k2 = db.me_stats(uid)["kinds"]
    assert (k2["decision"], k2["custom"]) == (before["decision"] + 2, before["custom"]), (before, k2)   # released = 보통 결정 항목
    assert db.me_home(uid)["counts"]["decisions"] == home0["decisions"] + 2, "released 면 me_home 결정도 늘어난다"
    # 14: 축(분류 역할) 오브젝트에는 담을 규칙을 둘 수 없다
    with db.tx() as c:
        ax = db._axis_object(c, uid)
    assert ax, "표준 축 시드"
    a = next(x for x in db.definitions(uid) if x["id"] == ax)
    ad = {k: a[k] for k in ("key", "label", "semantic_kind")}
    ad["fields"] = [{k: f[k] for k in ("key", "label", "value_type", "required", "options", "target_kind", "target_object_id", "multiple")}
                    for f in a["fields"]]
    ad["policy"] = {**(a["policy"] or {}), "route": {"v": 1, "unit": "record", "match": {"source": SRC}}}
    e = expect("ARG-INVALID", db.definition_propose, uid, ax, a["revision"], ad)
    assert "축 오브젝트" in e.message, e.message
    ok("나 탭 건수 — 자동 분류 항목은 결정에서 빼고 커스텀(released 면 다시 결정), 축 오브젝트 route = ARG-INVALID")


def test_hint():
    """route.hint(나 탭 요약) — profile 과 같은 판정. 안 붙은 기록 30편 = 알림 없음, 31편 = 알림. 붙은 기록은 세지 않는다."""
    h = db.user_by_email(HINT)["id"]
    db.display_name_set(h, "가짜 알림")
    assert route.hint(h) == {"suggest": False, "route_drafts": 0}
    rids = [db.record_add(h, f"가짜 메모 {n}", f"가짜 본문 {n}", source="대화에서 입력")["id"] for n in range(30)]
    p = route.profile(h)
    assert (p["unattached"]["count"], p["suggest"]) == (30, False) and route.hint(h)["suggest"] is False
    assert p["unattached"]["by_source"] == [{"source": "대화에서 입력", "count": 30}]
    rids.append(db.record_add(h, "가짜 메모 30", "가짜 본문 30", source="가짜 출처")["id"])
    p = route.profile(h)
    assert (p["unattached"]["count"], p["suggest"]) == (31, True) and route.hint(h)["suggest"] is True
    # 항목에 붙은 기록은 빠진다(item_links) — 다시 30편 = 알림 없음
    ax, _ = apply_def(h, {"key": "events_x", "label": "가짜 결정", "semantic_kind": "event", "fields": []})
    it = db.item_propose(h, ax, 1, None, 0, None, "가짜 결정 하나", "", {}, [])
    db.item_decide(h, it["item_id"], 0, it["proposal_id"], "apply")
    db.record_attach(h, rids[0], attach_to=[{"field_key": "attach_to", "target_kind": "item", "target_id": it["item_id"]}])
    p = route.profile(h)
    assert (p["unattached"]["count"], p["suggest"]) == (30, False) and route.hint(h) == {"suggest": False, "route_drafts": 0}
    # route 있는 초안만 센다
    db.definition_propose(h, None, 0, {"key": "drafty", "label": "가짜 초안", "semantic_kind": "collection", "fields": []})
    d = json.loads(json.dumps(PIVOT_DEF))
    db.definition_propose(h, None, 0, d)
    assert route.hint(h)["route_drafts"] == 1
    ok("route.hint — 30편 알림 없음, 31편 알림, 붙은 기록 제외(profile 과 같은 값), route 있는 초안 수")


def test_profile_fit(uid):
    """20번 — MCP op 의 profile 은 대화 도구 응답 상한(24 KiB) 안으로 결정적으로 줄인다. 화면(기본값)은 줄이지 않는다."""
    small = route.profile(uid, fit_chat=True)
    assert "truncated" not in small, "작은 자료는 줄이지 않는다"
    h = db.user_by_email(FIT)["id"]
    db.display_name_set(h, "가짜 큰 자료")
    syl = [chr(0xAC00 + i * 500) for i in range(20)] + [chr(0xAC00 + i * 28 + 1) for i in range(30)]
    for i in range(40):
        a, b = syl[i % 20], syl[20 + i % 30]
        body = "".join(f"## 긴 머리 {syl[20 + (i + j) % 30]}{'나' * 185}\n가짜 문장\n" for j in range(3))
        body += "".join(f"**라벨{syl[(i + j) % 20]}{'다' * 60}** — 가짜 값\n" for j in range(2))
        body += "".join(f"- 키{syl[20 + (i + j) % 20]}{'라' * 60}: 가짜 값\n" for j in range(2))
        db.record_add(h, f"가짜 긴 제목 {a}{'가' * 180} 꼴{b}", body, source=SRC)
    d = json.loads(json.dumps(PIVOT_DEF))
    d["key"], d["policy"]["route"]["match"]["title_like"] = "pivots_fit", "가짜 *"
    d["policy"]["route"]["require"] = {"labels": []}
    d["fields"] = [f for f in d["fields"] if not f.get("required") or f["key"] == "happened_on"]
    d["policy"]["route"]["fields"] = {"happened_on": {"from": "record_date"}}
    db.definition_propose(h, None, 0, d)
    full = route.profile(h)
    n_full = len(json.dumps(full, ensure_ascii=False).encode("utf-8"))
    assert n_full > 32 * 1024 and "truncated" not in full, n_full   # 화면 경로(기본값)는 줄이지 않는다
    got = route.profile(h, fit_chat=True)
    n_got = len(json.dumps(got, ensure_ascii=False).encode("utf-8"))
    assert n_got <= route.PROFILE_MAX_BYTES and got["truncated"] is True, n_got
    for k in ("kind", "objects", "route_guide", "suggest", "notice"):
        assert got[k] == full[k], k
    assert got["unattached"]["count"] == full["unattached"]["count"]
    assert [(x["object_id"], x["would_fill"], x["partial"]) for x in got["drafts"]] == \
        [(x["object_id"], x["would_fill"], x["partial"]) for x in full["drafts"]]
    assert all(len(x["text"]) <= 80 for x in got["headings"]) and all(len(x["text"]) <= 40 for x in got["labels"] + got["keys"])
    assert all(len(x["shape"]) <= 80 and len(x["sample"]) <= 80 for x in got["titles"])
    assert route.profile(h, fit_chat=True) == got, "결정적"
    tight = route.fit(json.loads(json.dumps(full)), 6 * 1024)   # 목록 줄이기 경로 — titles, keys, labels 순으로 뒤에서부터 비운다
    assert len(json.dumps(tight, ensure_ascii=False).encode("utf-8")) <= 6 * 1024 and tight["truncated"] is True
    assert tight["titles"] == [] and tight["keys"] == [] and len(tight["headings"]) <= len(full["headings"]), tight
    assert tight["objects"] == full["objects"] and tight["unattached"]["count"] == full["unattached"]["count"]
    ok(f"profile 크기 상한 — 줄이기 전 {n_full} 바이트, op 응답 {n_got} 바이트(24 KiB 이하), truncated, 건수 키 그대로, 화면은 안 줄임, 작은 자료는 키 없음")


def test_isolation_and_migration(uid, oid):
    other = db.user_by_email(OTHER)["id"]
    db.display_name_set(other, "다른 가짜")
    rid = db.record_add(other, "P1. 남의 기록", pivot_body(1), source=SRC)["id"]
    assert not qa("SELECT 1 FROM item_routes WHERE record_id=%s", (rid,)), "남의 오브젝트 route 는 내 기록에 안 붙는다"
    expect("ARG-INVALID", route.exclude, other, routed_item(uid, oid, add(uid, "P13. 가짜", pivot_body(13))), 1)
    # 옛 DB — items.ingest_kind CHECK 에 route 가 없던 꼴에서 이전
    with db.tx() as c:
        c.execute("UPDATE items SET ingest_kind='interactive' WHERE ingest_kind='route'")
        c.execute("ALTER TABLE items DROP CONSTRAINT ck_items_ingest_kind")
        c.execute("ALTER TABLE items ADD CONSTRAINT ck_items_ingest_kind CHECK (ingest_kind IN ('legacy','interactive','inbox','board_migration'))")
    db.init_schema()
    db.init_schema()   # 멱등
    d = q1("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname='ck_items_ingest_kind'")["d"]
    assert "'route'" in d and "'board_migration'" in d, d
    r = q1("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname='ck_records_ingest_kind'")["d"]
    assert "'route'" not in r, "records CHECK 는 그대로"
    d = q1("SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conname='ck_item_routes_item'")["d"]
    assert "'released'" in d, d
    with db.tx() as c:
        c.execute("UPDATE items i SET ingest_kind='route' FROM item_routes r WHERE r.user_id=i.user_id AND r.item_id=i.id")
    assert "item_routes" in db.DELETE_TABLES and db.DELETE_TABLES.index("item_routes") < db.DELETE_TABLES.index("items")
    ok("사용자 격리, 옛 DB 이전(items CHECK 에 route, records 그대로, 멱등), 계정 삭제 표 순서")


async def run():
    db.init_schema()
    cleanup()
    try:
        uid = db.user_by_email(MAIN)["id"]
        db.display_name_set(uid, "가짜 사용자")
        oid, r_ok, r_part = test_backfill(uid)
        rid = await test_hooks(uid, oid, r_ok, r_part)
        test_trash_exclude_lock(uid, oid, rid)
        ce_oid = test_budget_and_sweep(uid)
        test_profile_discard(uid, oid, ce_oid)
        test_hook_isolation(uid, oid)
        test_definition_checks(uid)
        test_release_archive_stack(uid)
        test_me_stats_and_axis(uid)
        test_profile_fit(uid)
        await test_released_rules(uid)
        test_hint()
        test_isolation_and_migration(uid, oid)
    finally:
        cleanup()
        db.close()
    print("OK — 자동 분류 흐름 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
