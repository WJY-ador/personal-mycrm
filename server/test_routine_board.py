"""첫 화면 루틴판 시험(2026-11-21 첫 화면 루틴판 구현계획 2절).

실행: DATABASE_URL=postgresql://localhost/crm_test_routine python3 server/test_routine_board.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 자료는 가짜 문장, 가짜 오브젝트 key 뿐이다.

1. 블록 설정 p 검증(필수 5키, 길이, "칸key:값" 꼴, 모르는 키) · 기본 배치에 routine 없음 · 저장한 p 를 읽는다
2. 판정 첫 낱말 규칙 표
3. 집계 숫자(들어온 것 7일 경계, created_at 대체, 신호, 판정 수, 쓰는 중 stage 조건과 카드) · lines 배치(post → in, route 기록 → decided,
   route 아닌 기록은 어느 열에도 없음, 같은 대상은 최근 줄 하나) · more · unrefined · since(이력 없음 = 전체, 이력 뒤 생긴 것)
4. missing(키 집합 그대로, 숫자 0) · 설정 없음 = ready false · AI 값 키 없음
5. 상세(소제목 순서, 출처 합과 중복 제외, 출처 없는 소제목, missing_sources) · 남의 항목, 휴지통, 보관, 다른 오브젝트 항목 404
6. 웹 GET /api/me/routine[/<id>] = 같은 함수 · 견본 routine.sample.json 대조 · MCP read op 두 개
"""
import asyncio
import datetime as _dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_routine). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ci-routine-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from mcp.client import Client  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
import routine_board as rb  # noqa: E402
from test_sample_shape import cmp  # noqa: E402

MAIN, OTHER = "ci-routine-main@example.com", "ci-routine-other@example.com"
EMAILS = (MAIN, OTHER)
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
P = {"in": "rb_posts", "in_signal": "ai_grade:signal", "decided": "rb_pivots", "verdict": "was_right", "writing": "rb_boards",
     "stage": "stage:draft", "lines": "rb_lines", "subheads": "rb_subheads"}


def ok(msg):
    print("OK", msg, flush=True)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (e.code, e.message)
        return e
    raise AssertionError(f"{code} 기대, 성공함")


def obj(uid, key, label, fields, policy=None):
    d = {"key": key, "label": label, "semantic_kind": "collection", "fields": fields}
    if policy:
        d["policy"] = policy
    q = db.definition_propose(uid, None, 0, d)
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    return q["object_id"]


def item(uid, oid, title, data=None, links=None, body=""):
    p = db.item_propose(uid, oid, 1, None, 0, None, title, body, data or {}, links or [])
    return db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]


def ref_item(field, iid):
    return {"field_key": field, "target_kind": "item", "target_id": iid}


def ref_rec(field, rid):
    return {"field_key": field, "target_kind": "record", "target_id": rid}


def sql(q, args=()):
    with db.tx() as c:
        c.execute(q, args)


def trash_item(uid, iid):
    sql("UPDATE items SET trashed_at=now(), purge_at=now() + interval '7 days', last_trashed_at=now() WHERE user_id=%s AND id=%s", (uid, iid))


def route(uid, oid, rid, iid):
    sql("INSERT INTO item_routes (user_id, object_id, record_id, unit_key, state, item_id) VALUES (%s,%s,%s,'','routed',%s)", (uid, oid, rid, iid))


def setup_objects(uid):
    db.display_name_set(uid, "합성")
    o = {}
    o["posts"] = obj(uid, "rb_posts", "가짜 글", [
        {"key": "channel", "label": "채널", "value_type": "select", "options": [{"value": "linkedin", "label": "링크드인"}]},
        {"key": "posted_on", "label": "글 날짜", "value_type": "date"},
        {"key": "author_display", "label": "작성자", "value_type": "text"},
        {"key": "ai_grade", "label": "AI 판별", "value_type": "select",
         "options": [{"value": "signal", "label": "신호"}, {"value": "noise", "label": "잡음"}]},
        {"key": "ai_summary", "label": "AI 요약", "value_type": "text"}])
    o["pivots"] = obj(uid, "rb_pivots", "가짜 결정", [
        {"key": "decided_on", "label": "정한 날", "value_type": "date"},
        {"key": "was_right", "label": "맞았나", "value_type": "text"}])
    o["boards"] = obj(uid, "rb_boards", "가짜 한판", [
        {"key": "stage", "label": "단계", "value_type": "select", "required": True,
         "options": [{"value": "draft", "label": "초안"}, {"value": "published", "label": "발행"}]},
        {"key": "inflow_posts", "label": "유입 글", "value_type": "reference", "target_kind": "item", "target_object_id": o["posts"],
         "multiple": True},
        {"key": "materials", "label": "재료", "value_type": "reference", "target_kind": "record", "multiple": True},
        {"key": "key_line", "label": "핵심 한 줄", "value_type": "text"},
        {"key": "published_on", "label": "발행일", "value_type": "date"}])
    o["subheads"] = obj(uid, "rb_subheads", "가짜 소제목", [
        {"key": "board", "label": "한판", "value_type": "reference", "target_kind": "item", "target_object_id": o["boards"]},
        {"key": "order", "label": "순서", "value_type": "number"},
        {"key": "src_records", "label": "출처 기록", "value_type": "reference", "target_kind": "record", "multiple": True},
        {"key": "src_posts", "label": "출처 글", "value_type": "reference", "target_kind": "item", "target_object_id": o["posts"],
         "multiple": True}])
    o["lines"] = obj(uid, "rb_lines", "가짜 줄", [
        {"key": "subject_record", "label": "대상 기록", "value_type": "reference", "target_kind": "record"},
        {"key": "subject_post", "label": "대상 글", "value_type": "reference", "target_kind": "item", "target_object_id": o["posts"]}],
        policy={"exactly_one_reference": ["subject_record", "subject_post"]})
    return o


def no_ai_keys(v, path="$"):
    if isinstance(v, dict):
        for k, x in v.items():
            assert not k.startswith("ai_"), f"{path}.{k} — 판 응답에 AI 값 금지"
            no_ai_keys(x, f"{path}.{k}")
    elif isinstance(v, list):
        for x in v:
            no_ai_keys(x, path + "[]")


async def web(path, user=MAIN):
    site = main.site
    real = site.dev, site.dev_user
    try:
        site.dev, site.dev_user = True, user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            return await h.get(path)
    finally:
        site.dev, site.dev_user = real


def mcp_val(res):
    v = res.structured_content
    v = v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v
    return json.loads(res.content[0].text) if v is None else v


def test_p_check():
    base = {"tabs": list(db.DEFAULT_LAYOUT["pages"]["me"]["tabs"]), "regions": {"summary": []}}

    def lay(p):
        b = json.loads(json.dumps(base))
        b["regions"]["summary"] = [{"c": "heatmap", "p": {}}, {"c": "routine", "p": p}]
        return {"v": 2, "pages": {"me": b}}
    assert db.layout_check(lay(P))["pages"]["me"]["regions"]["summary"][1] == {"c": "routine", "p": P}
    assert db.layout_check(lay({k: P[k] for k in db.ROUTINE_OBJ_KEYS})), "선택 키 없이도 된다"
    for bad, why in (({k: v for k, v in P.items() if k != "lines"}, "필수 키 빠짐"), ({**P, "in": ""}, "빈 문자열"),
                     ({**P, "in": "   "}, "공백뿐"), ({**P, "in": "x" * 65}, "65자"), ({**P, "stage": "draft"}, "콜론 없음"),
                     ({**P, "in_signal": ":signal"}, "칸 key 빈 값"), ({**P, "stage": "stage:"}, "값 빈 값"),
                     ({**P, "extra": "x"}, "모르는 키"), ({**P, "in": 3}, "문자열 아님")):
        expect("LAYOUT-INVALID", db.layout_check, lay(bad))
    assert "routine" not in [e["c"] for e in db.DEFAULT_LAYOUT["pages"]["me"]["regions"]["summary"]], "기본 배치에 넣지 않는다"
    reg = db.LAYOUT_REGISTRY["components"]["routine"]
    assert reg["label"] == "루틴판" and reg["regions"] == ["summary"] and reg["width"] == "full", reg
    ok("1a 블록 설정 p 검증(필수 5키, 1~64자, 칸key:값, 모르는 키, 타입) · 기본 배치 밖 · 레지스트리 라벨, 자리, 폭")


def test_words():
    table = {"맞았다": "right", "맞음, 생각보다 빨랐다": "right", "  맞다": "right", "**맞았다**": "right", "- 맞음": "right",
             "미확인": "unknown", "(미확인) 다음 달에 본다": "unknown", "일부 맞았다": "partial", "일부만": "partial",
             "틀렸다": "wrong", "틀림": "wrong", "아니었다 결국": "wrong", "안 맞았다": "none", "맞는지 모름": "none",
             "결과: 맞았다": "none", "": "none", "   ": "none", None: "none", 3: "none"}
    for v, want in table.items():
        assert rb.verdict_of(v) == want, (v, rb.verdict_of(v), want)
    assert rb.verdict_of(["맞았다"]) == "none"
    ok("2 판정 첫 낱말 규칙 표(앞 공백, 문장부호 빼기, 첫 어절 시작 낱말, 부정 앞말은 none, 문자열 아님 none)")


async def run():
    A, B = db.user_by_email(MAIN)["id"], db.user_by_email(OTHER)["id"]
    test_p_check()
    # 저장한 p 를 읽는다(웹, MCP 의 p 원천) · 저장 전엔 None
    assert rb.routine_p(A) is None
    o = setup_objects(A)
    setup_objects(B)
    with db.tx() as c:
        today = c.execute("SELECT (now() AT TIME ZONE 'Asia/Seoul')::date AS d").fetchone()["d"]
    day = lambda n: (today - _dt.timedelta(days=n)).isoformat()   # noqa: E731
    empty = rb.routine_board(A)
    assert empty["ready"] is False and empty["missing"] == [] and empty["in"]["n_total"] == 0, empty
    g = db.layout_get(A)
    me = g["layout"]["pages"]["me"]
    me["regions"]["summary"].append({"c": "routine", "p": P})
    db.layout_set(A, me, g["version"], page="me")
    assert rb.routine_p(A) == P
    ok("1b 저장한 배치의 routine 블록 p 를 읽는다(저장 전 None, 설정 없음 = ready false)")

    # ── 자료 ──
    po = {}
    po["P1"] = item(A, o["posts"], "가짜 글 하나", {"posted_on": day(0), "ai_grade": "signal", "channel": "linkedin",
                                                 "author_display": "가짜 작성자", "ai_summary": "가짜 AI 요약"})
    po["P2"] = item(A, o["posts"], "가짜 글 둘", {"posted_on": day(6), "ai_grade": "noise"})
    po["P3"] = item(A, o["posts"], "가짜 글 셋", {"posted_on": day(7), "ai_grade": "signal"})   # 7일 밖
    po["P4"] = item(A, o["posts"], "가짜 글 넷", {"ai_grade": "signal"})                       # 날짜 칸 없음 → created_at(오늘)
    po["P5"] = item(A, o["posts"], "가짜 글 다섯", {"posted_on": day(0), "ai_grade": "signal"})   # 휴지통
    po["P6"] = item(A, o["posts"], "가짜 글 여섯", {"posted_on": day(30)})                       # 줄 없음
    po["P7"] = item(A, o["posts"], "가짜 글 일곱", {"posted_on": day(1)})                        # 보관
    sql("UPDATE items SET archived_at=now() WHERE user_id=%s AND id=%s", (A, po["P7"]))
    po["P8"] = item(A, o["posts"], "가짜 글 여덟", {"posted_on": day(0), "ai_grade": "signal"})   # 버림
    sql("INSERT INTO collected_states (user_id, item_id, state, decided_by) VALUES (%s,%s,'dropped','device')", (A, po["P8"]))
    pv = {}
    for k, v, d in (("D1", "맞았다 생각보다 빨랐다", 3), ("D2", "  미확인", 2), ("D3", "일부 맞음", 1), ("D4", "틀림", 0),
                    ("D5", "안 맞았다", 0), ("D6", None, 0)):
        pv[k] = item(A, o["pivots"], f"가짜 결정 {k}", {"decided_on": day(d), **({"was_right": v} if v else {})})
    rec = {k: db.record_add(A, f"가짜 기록 {k}", f"가짜 본문 {k}")["id"] for k in ("R1", "R2", "R3", "R4", "R5")}
    for r, d in (("R1", "D1"), ("R2", "D2"), ("R3", "D3")):
        route(A, o["pivots"], rec[r], pv[d])
    # 이력 없음 = 전체가 새것(since)
    s0 = rb.routine_board(A)
    assert s0["ready"] and s0["last_routine_at"] is None and s0["since"] == {"new_in": 6, "new_decided": 6}, s0["since"]

    ln = {}
    ln["L1"] = item(A, o["lines"], "다듬은 줄 하나", links=[ref_item("subject_post", po["P1"])])
    ln["L2"] = item(A, o["lines"], "다듬은 줄 셋", links=[ref_item("subject_post", po["P3"])])
    ln["L3"] = item(A, o["lines"], "다듬은 결정 줄", links=[ref_rec("subject_record", rec["R1"])])
    ln["L4"] = item(A, o["lines"], "route 아닌 기록 줄", links=[ref_rec("subject_record", rec["R4"])])
    ln["L5"] = item(A, o["lines"], "옛 줄 둘", links=[ref_item("subject_post", po["P2"])])
    ln["L6"] = item(A, o["lines"], "새 줄 둘", links=[ref_item("subject_post", po["P2"])])
    ln["L7"] = item(A, o["lines"], "다듬은 줄 넷", links=[ref_item("subject_post", po["P4"])])
    ln["L8"] = item(A, o["lines"], "휴지통 글 줄", links=[ref_item("subject_post", po["P5"])])
    trash_item(A, po["P5"])   # 줄을 단 뒤 휴지통
    ln["L9"] = item(A, o["lines"], "버림 글 줄", links=[ref_item("subject_post", po["P8"])])
    sql("UPDATE items SET updated_at = now() + interval '2 minutes' WHERE user_id=%s AND id=%s", (A, ln["L9"]))   # 버리지 않았다면 맨 앞
    sql("UPDATE items SET updated_at = now() - interval '1 minute' WHERE user_id=%s AND id=%s", (A, ln["L5"]))
    sql("UPDATE items SET updated_at = now() + interval '1 minute' WHERE user_id=%s AND id=%s", (A, ln["L7"]))

    bd = {}
    bd["B1"] = item(A, o["boards"], "가짜 한판 하나", {"stage": "draft", "key_line": "가짜 핵심 한 줄"},
                    [ref_item("inflow_posts", po["P3"]), ref_item("inflow_posts", po["P1"]), ref_rec("materials", rec["R2"])])
    bd["B2"] = item(A, o["boards"], "가짜 한판 둘", {"stage": "draft"})
    bd["B3"] = item(A, o["boards"], "가짜 한판 셋", {"stage": "published", "published_on": day(0)})
    bd["B4"] = item(A, o["boards"], "가짜 한판 넷", {"stage": "draft"})
    bd["B6"] = item(A, o["boards"], "가짜 한판 여섯", {"stage": "draft"})
    bd["B7"] = item(A, o["boards"], "가짜 한판 일곱", {"stage": "draft"})   # 휴지통
    trash_item(A, bd["B7"])
    for k, n in (("B1", 2), ("B2", 1), ("B4", 5), ("B6", 10)):   # created_at 대체 날짜(이 한판들은 발행일 없음)
        sql("UPDATE items SET created_at = now() - make_interval(days => %s) WHERE user_id=%s AND id=%s", (n, A, bd[k]))
    sh = {}
    sh["S1"] = item(A, o["subheads"], "가짜 소제목 둘째", {"order": 2},
                    [ref_item("board", bd["B1"]), ref_item("src_posts", po["P1"]), ref_rec("src_records", rec["R4"])], body="가짜 전문 1")
    sh["S2"] = item(A, o["subheads"], "가짜 소제목 첫째", {"order": 1},
                    [ref_item("board", bd["B1"]), ref_item("src_posts", po["P1"]), ref_item("src_posts", po["P2"]),
                     ref_rec("src_records", rec["R1"])], body="가짜 전문 2")
    sh["S3"] = item(A, o["subheads"], "가짜 소제목 순서 없음", {}, [ref_item("board", bd["B1"])])
    sh["S4"] = item(A, o["subheads"], "가짜 소제목 셋째", {"order": 3}, [ref_item("board", bd["B1"]), ref_rec("src_records", rec["R5"])])
    sh["S5"] = item(A, o["subheads"], "가짜 소제목 휴지통", {"order": 0}, [ref_item("board", bd["B1"]), ref_item("src_posts", po["P6"])])
    sh["S6"] = item(A, o["subheads"], "가짜 다른 한판 소제목", {"order": 1}, [ref_item("board", bd["B2"]), ref_item("src_posts", po["P6"])])
    trash_item(A, sh["S5"])
    sql("UPDATE records SET trashed_at=now(), purge_at=now() + interval '7 days', last_trashed_at=now() WHERE user_id=%s AND id=%s",
        (A, rec["R5"]))

    # since: 루틴 적용 시각 = 2시간 전 · P1, P4, D2 만 그 뒤에 생겼다(나머지는 3시간 전으로)
    with db.tx() as c:
        c.execute("UPDATE item_history SET at = now() - interval '2 hours' WHERE user_id=%s AND action='apply'", (A,))
        c.execute("UPDATE items SET created_at = now() - interval '3 hours' WHERE user_id=%s AND object_id = ANY(%s) AND NOT id = ANY(%s)",
                  (A, [o["posts"], o["pivots"]], [po["P1"], po["P4"], pv["D2"]]))
        last = c.execute("SELECT max(at) AS t FROM item_history WHERE user_id=%s", (A,)).fetchone()["t"]

    # ── 3. 집계 ──
    r = rb.routine_board(A)
    assert r["ready"] is True and r["missing"] == []
    assert r["in"]["n_total"] == 5 and r["in"]["n_7d"] == 3 and r["in"]["signal_7d"] == 2, r["in"]   # P1·P2·P4 / 신호 P1·P4
    assert {k: r["decided"][k] for k in ("total", *rb.VERDICTS)} == {"total": 6, "right": 1, "unknown": 1, "partial": 1, "wrong": 1,
                                                                     "none": 2}, r["decided"]
    assert r["last_routine_at"] == last.isoformat() and r["since"] == {"new_in": 2, "new_decided": 1}, (r["last_routine_at"], r["since"])
    # in 열: 대상 P1(오늘), P4(오늘, 줄이 더 최근), P2(6일 전, 새 줄 L6), P3(7일 전) → 3개 + more 1. P5(휴지통)는 없다
    il = r["in"]["lines"]
    assert [x["text"] for x in il] == ["다듬은 줄 넷", "다듬은 줄 하나", "새 줄 둘"] and r["in"]["more"] == 1, il
    assert il[1] == {"date": day(0), "text": "다듬은 줄 하나",
                     "target": {"kind": "item", "id": po["P1"], "object_key": "rb_posts", "item_id": po["P1"]}}, il[1]
    assert il[2]["date"] == day(6)
    assert r["in"]["unrefined"] == 1, "줄 없는 글 = P6"
    # decided 열: route 기록 R1 → D1 만. R4(route 아님) 줄은 어느 열에도 없다
    assert r["decided"]["lines"] == [{"date": day(3), "text": "다듬은 결정 줄",
                                      "target": {"kind": "record", "id": rec["R1"], "object_key": "rb_pivots", "item_id": pv["D1"]}}]
    assert r["decided"]["more"] == 0 and r["decided"]["unrefined"] == 2, r["decided"]   # route 있는 D2·D3
    assert "route 아닌 기록 줄" not in json.dumps(r, ensure_ascii=False)
    assert "버림 글 줄" not in json.dumps(r, ensure_ascii=False), "버림 수집 글은 숫자(n_total, n_7d, signal_7d, unrefined, new_in)와 줄에서 뺀다"
    # 쓰는 중: draft 만(B3 발행, B7 휴지통 제외) · 최신 3장(created_at 대체 날짜 B2 1일, B1 2일, B4 5일)
    w = r["writing"]
    assert w["drafts"] == 4 and [x["item_id"] for x in w["cards"]] == [bd["B2"], bd["B1"], bd["B4"]], w
    c1 = w["cards"][1]
    assert c1 == {"item_id": bd["B1"], "key_line": "가짜 핵심 한 줄", "date": day(2), "n_subheads": 4, "n_sources": 4,
                  "n_posts": 3, "n_records": 3}, c1   # 소제목 P1·P2·R1·R4 · 한판 유입 P3·P1, 재료 R2 더해 글 P1·P2·P3, 기록 R1·R4·R2
    assert w["cards"][0]["key_line"] == "가짜 한판 둘" and w["cards"][0]["n_subheads"] == 1 and w["cards"][0]["n_sources"] == 1 \
        and (w["cards"][0]["n_posts"], w["cards"][0]["n_records"]) == (1, 0)
    no_ai_keys(r)
    ok("3 집계(7일 경계 오늘-6 포함 오늘-7 제외, created_at 대체, 신호, 판정 수, stage 조건, 카드 3장, 출처 합) · lines(post→in, route 기록→decided,"
       " route 아닌 기록 없음, 같은 대상은 최근 줄, 휴지통 대상 없음, more) · unrefined · since(이력 없음 = 전체, 적용 뒤 생긴 것) · 버림 글 제외 · AI 값 없음")

    # ── 4. missing · 설정 없음 ──
    m = rb.routine_board(A, {**P, "lines": "rb_nothing", "subheads": "rb_nothing2"})
    assert m["ready"] is False and m["missing"] == ["lines", "subheads"] and m["in"]["n_total"] == 0 and m["writing"]["cards"] == [], m
    assert set(m) == set(r) == set(empty) and all(set(m[k]) == set(r[k]) for k in ("since", "in", "decided", "writing")), "키 집합 같음"
    sql("UPDATE object_defs SET archived_at=now() WHERE user_id=%s AND id=%s", (A, o["lines"]))
    assert rb.routine_board(A)["missing"] == ["lines"], "보관한 오브젝트 = 없는 것"
    sql("UPDATE object_defs SET archived_at=NULL WHERE user_id=%s AND id=%s", (A, o["lines"]))
    assert rb.routine_board(B)["ready"] is False, "B 는 설정 없음"
    ok("4 missing(p 키, 보관 오브젝트 포함, 숫자 0, 키 집합 같음) · 설정 없음 ready false")

    # ── 5. 상세 ──
    d = rb.routine_board_detail(A, bd["B1"])
    assert d["board"] == {"item_id": bd["B1"], "title": "가짜 한판 하나", "key_line": "가짜 핵심 한 줄", "stage": "draft", "date": day(2)}
    assert [s["item_id"] for s in d["subheads"]] == [sh["S2"], sh["S1"], sh["S4"], sh["S3"]], "order 순, 없으면 뒤(생성순), 휴지통 제외"
    s2 = d["subheads"][0]
    assert s2["order"] == 1 and s2["text"] == "가짜 소제목 첫째" and s2["body"] == "가짜 전문 2"
    assert [(x["kind"], x["id"]) for x in s2["sources"]] == [("post", po["P1"]), ("post", po["P2"]), ("record", rec["R1"])], s2["sources"]
    assert d["subheads"][2]["sources"] == [] and d["subheads"][3]["sources"] == [] and d["subheads"][3]["order"] is None
    assert [x["id"] for x in d["inflow"]] == [po["P1"], po["P2"], po["P3"]], "소제목 순으로 모은 뒤 한판 유입 글, 중복 제외"
    assert [x["id"] for x in d["decided"]] == [rec["R1"], rec["R4"], rec["R2"]], d["decided"]
    assert d["inflow"][0] == {"kind": "post", "id": po["P1"], "title": "가짜 글 하나", "author": "가짜 작성자", "channel": "linkedin",
                              "date": day(0), "ai_summary": "가짜 AI 요약", "ai": True}, d["inflow"][0]
    assert d["decided"][0]["item"] == {"object_key": "rb_pivots", "item_id": pv["D1"], "title": "가짜 결정 D1", "verdict": "맞았다 생각보다 빨랐다"}
    assert d["decided"][1]["item"] is None and d["decided"][2]["item"]["verdict"] == "  미확인"
    assert d["missing_sources"] == 1, "휴지통 기록 R5"
    ai = [k for x in d["inflow"] for k in x if k.startswith("ai")]
    assert set(ai) == {"ai_summary", "ai"}
    for bad_id in (bd["B7"], po["P1"], "i_nothing01", ""):   # 휴지통 한판, 다른 오브젝트 항목, 없는 id
        expect("NOT-FOUND", rb.routine_board_detail, A, bad_id)
    expect("NOT-FOUND", rb.routine_board_detail, B, bd["B1"])   # 남의 항목(B 는 설정도 없음)
    expect("NOT-FOUND", rb.routine_board_detail, B, bd["B1"], P)   # 남의 항목(같은 p)
    sql("UPDATE items SET archived_at=now() WHERE user_id=%s AND id=%s", (A, bd["B4"]))
    expect("NOT-FOUND", rb.routine_board_detail, A, bd["B4"])
    assert rb.routine_board_detail(A, bd["B3"])["board"]["stage"] == "published", "발행 한판도 상세는 연다"
    ok("5 상세(소제목 순서, 출처 posts 먼저, 출처 합과 중복 제외, 출처 없는 소제목, missing_sources, AI 요약은 수집 글 ref 만) · 404(휴지통, 보관,"
       " 다른 오브젝트, 없는 id, 남의 항목)")

    # ── 6. 웹 · 견본 · MCP ──
    w1 = await web("/api/me/routine")
    assert w1.status_code == 200 and w1.headers["cache-control"] == "no-store"
    real_board = rb.routine_board(A)
    assert w1.json() == json.loads(json.dumps(real_board)), "웹 = 같은 함수"
    w2 = await web(f"/api/me/routine/{bd['B1']}")
    assert w2.status_code == 200 and w2.json() == json.loads(json.dumps(rb.routine_board_detail(A, bd["B1"])))
    assert (await web(f"/api/me/routine/{bd['B1']}", user=OTHER)).status_code == 404
    assert (await web("/api/me/routine/i_nothing01")).status_code == 404
    wb = await web("/api/me/routine", user=OTHER)
    assert wb.status_code == 200 and wb.json()["ready"] is False
    sample = json.loads((HERE / "ui" / "src" / "features" / "me" / "routine.sample.json").read_text(encoding="utf-8"))
    bad = cmp(sample["board"], w1.json(), "board", exact=True) + cmp(sample["detail"], w2.json(), "detail", exact=True) \
        + cmp(sample["board"], json.loads(json.dumps(m)), "missing", exact=True)
    assert not bad, (bad, "routine.sample.json 과 화면 타입을 같이 고친다")
    async with Client(main.mcp) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert "routine_board_get" not in tools and "routine_board_detail_get" not in tools, "facade 전용"
        res = await c.call_tool("read", {"op": "routine_board_get", "params": {}})
        assert not res.is_error, res.content[0].text[:300]
        assert mcp_val(res) == json.loads(json.dumps(rb.routine_board(A)))
        res = await c.call_tool("read", {"op": "routine_board_detail_get", "params": {"item_id": bd["B1"]}})
        assert not res.is_error and mcp_val(res)["board"]["item_id"] == bd["B1"], res.content[0].text[:300]
        nf = await c.call_tool("read", {"op": "routine_board_detail_get", "params": {"item_id": "i_nothing01"}})
        assert nf.is_error and CODE.search(nf.content[0].text).group(1) == "NOT-FOUND", nf.content[0].text
        det = await c.call_tool("find", {"op": "routine_board_get"})
        assert not det.is_error and "AI 값은 근거가 아니다" in det.content[0].text, det.content[0].text[:300]
    assert "routine_board_get" in main.INSTRUCTIONS and "24자 안쪽" in main.INSTRUCTIONS
    ok("6 웹 GET /api/me/routine[/<id>] = 같은 함수(no-store, 404, 설정 없음) · 견본 키 집합 대조(정상, missing) · MCP read op 두 개(facade 전용, NOT-FOUND, 설명)")


def main_():
    db.init_schema()
    cleanup()
    try:
        test_words()
        asyncio.run(run())
    finally:
        cleanup()
    print("ALL OK test_routine_board")


if __name__ == "__main__":
    main_()
