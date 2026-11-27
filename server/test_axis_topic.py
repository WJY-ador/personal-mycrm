"""축 > 주제 > 하위 목록 시험(2026-11-27) — 세션 정리 축 줄, 주제 항목의 축, 주제 하위 목록, 축의 주제 목록.

실행: DATABASE_URL=postgresql://localhost/crm_test_axis_topic python3 server/test_axis_topic.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다. 자료는 전부 합성.

1. 축 줄 계약 — session-wrap/1 만, 코드 1~2개, [A-Z0-9-] 꼴, 중복 금지 · 다른 변환 거절 · 투영(없으면 옛 해시, 순서만 다르면 같은 내용) · 대기 payload
2. 기록의 축 — 그 사용자의 축 항목(code)에 기록 출발 axes 관계 · 없는 코드는 버리고 axis_codes_unknown · 축 줄만(주제 없음)도 기록에 잇는다
3. 주제의 축 — 주제 오브젝트에 축 필드가 없으면 주제에는 잇지 않는다(오류 아님) · 필드가 생기면 새 축만 더한다(있는 축 그대로, 같으면 revision 그대로)
   · 필드 꼴이 다르면(하나만) 없는 것과 같다
4. 주제 하위 목록(item_get children) — 붙은 기록의 자동 분류 항목을 오브젝트별, 날짜순, 요약 칸(글자 필드 앞 3개, 300자) · 뺀 항목·휴지통 기록 제외
5. 축의 주제 목록(axis_overview topics) — 축 필드, 없으면 붙은 기록들의 축으로 계산 · 글 수, 마지막 날짜 · 주제 오브젝트 없음 = 빈 목록
"""
import asyncio
import json
import os
import secrets
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_axis_topic). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "at-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_TRASH_ENABLED"] = "1"
os.environ["CRM_IMPORTS_ENABLED"] = "1"
os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import route  # noqa: E402

MAIN, BARE = "at-main@example.com", "at-bare@example.com"
EMAILS = (MAIN, BARE)
SW = "session-wrap/1"

# 자동 분류 오브젝트 셋(가짜) — 세션 정리 기록의 소제목 단위. 글자 필드 앞 3개 요약을 보려고 이야기에는 글자 필드 넷(하나는 목록)
STORY = {"key": "fake_story", "label": "세션 스토리", "semantic_kind": "event",
         "fields": [{"key": "scene", "label": "장면", "value_type": "text"}, {"key": "tags", "label": "꼬리표", "value_type": "text_list"},
                    {"key": "why", "label": "이유", "value_type": "text"}, {"key": "result", "label": "결과", "value_type": "text"},
                    {"key": "extra", "label": "덧붙임", "value_type": "text"}],
         "policy": {"route": {"v": 1, "unit": "heading", "match": {"source": imports.SESSION_WRAP_SOURCE, "heading_like": "S-#. *"},
                              "title": {"from": "heading"},
                              "fields": {"scene": {"from": "key", "key": "장면"}, "tags": {"from": "key", "key": "꼬리표"},
                                         "why": {"from": "key", "key": "이유"}, "result": {"from": "key", "key": "결과"},
                                         "extra": {"from": "key", "key": "덧붙임"}}}}}
DECIDE = {"key": "fake_decide", "label": "소통과 결정", "semantic_kind": "event",
          "fields": [{"key": "said", "label": "말", "value_type": "text"}],
          "policy": {"route": {"v": 1, "unit": "heading", "match": {"source": imports.SESSION_WRAP_SOURCE, "heading_like": "D-#. *"},
                               "title": {"from": "heading"}, "fields": {"said": {"from": "key", "key": "말"}}}}}


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def define(uid, d):
    q = db.definition_propose(uid, None, 0, d)
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    return q["object_id"]


def axes_object(uid):
    """축 오브젝트(계정 시드에 있으면 그것) {id, revision}."""
    with db.tx() as c:
        o = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND key='axes'", (uid,)).fetchone()
    if o:
        return o
    return {"id": define(uid, {"key": "axes", "label": "축", "semantic_kind": "collection", "fields": []}), "revision": 1}


def axis_items(uid):
    o = axes_object(uid)
    oid, out = o["id"], {}
    for code, title in (("A", "가짜 축 하나"), ("B-1", "가짜 축 둘"), ("C", "가짜 축 셋")):
        p = db.item_propose(uid, oid, o["revision"], None, 0, code, title, "", {}, [])
        out[code] = db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]
    return oid, out


def req(dev, original=None, prev=None, **kw):
    r = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev, "original_id": original or "o_" + secrets.token_hex(16),
         "revision": "v_" + secrets.token_hex(16), "previous_revision": prev, "kind": "self_text", "execution": "attended",
         "transform_version": SW, "policy_revision": 2, "title": "합성 제목", "body": "합성 세션 정리 본문이다.", "source_date": "2026-11-12"}
    r.update(kw)
    return r


async def raw_post(tok, body):
    hd = {"content-type": "application/json", "authorization": "Bearer " + tok,
          "idempotency-key": imports.idempotency_key(body["source_instance_id"], body["original_id"], body["revision"])}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        return await h.post("/api/imports", content=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=hd)


async def post(tok, body):
    r = await raw_post(tok, body)
    assert r.status_code in (200, 201), r.text
    return r.json()


def trash(uid, kind, target_id):
    """휴지통으로 — revision 을 받는 종류(항목)는 지금 revision 을 넣는다."""
    rev = db.item_get(uid, target_id)["revision"] if kind == "item" else None
    db.trash_move(uid, kind, target_id, rev)


def rec_axes(uid, rid):
    return sorted(ln["target_id"] for ln in db.record_links(uid, [rid]) if ln["field_key"] == "axes")


def topic_of(uid, oid, title):
    with db.tx() as c:
        return c.execute("SELECT id, revision FROM items WHERE user_id=%s AND object_id=%s AND title=%s AND revision > 0",
                         (uid, oid, title)).fetchone()


def item_axes(uid, item_id):
    with db.tx() as c:
        return sorted(r["target_item_id"] for r in c.execute("SELECT target_item_id FROM item_links WHERE user_id=%s AND source_item_id=%s "
                                                             "AND field_key='axes'", (uid, item_id)).fetchall())


def overview_topics(uid):
    return {a["code"]: [(t["title"], t["records"], t["last_on"]) for t in a["topics"]] for a in imports.axis_overview(uid)["axes"]}


async def contract_cases(dev, tok):
    # ── 1. 축 줄 계약 ──
    for bad, why in (([], "required"), (["A", "B", "C"], "list_max_2"), (["a"], "format"), (["A", "A"], "duplicate"), ("A", "list"),
                     (["A" * 11], "format")):
        r = await raw_post(tok, req(dev, axis_codes=bad))
        assert r.status_code == 400 and r.json()["code"] == "CONTRACT-INVALID" and "axis_codes" in r.json()["msg"], (bad, r.text)
    for tv, extra in (("self-text/1", {}), ("axis-page/1", {"axis_code": "A"})):
        r = await raw_post(tok, req(dev, transform_version=tv, axis_codes=["A"], **extra))
        assert r.status_code == 400 and r.json()["code"] == "CONTRACT-INVALID" and "axis_codes" in r.json()["msg"], (tv, r.text)
    base = req(dev)
    assert "axis_codes" not in imports.projection(base), "키가 없으면 옛 해시 그대로"
    assert imports.projection({**base, "axis_codes": ["B-1", "A"]}) == imports.projection({**base, "axis_codes": ["A", "B-1"]})
    assert imports._pending_payload({**base, "axis_codes": ["B-1", "A"]})["axis_codes"] == ["B-1", "A"], "대기 payload 에 실린다"
    print("OK 1 축 줄 계약(session-wrap/1 만, 1~2개, 꼴, 중복, 다른 변환 거절, 투영, 대기 payload)")


async def run():
    uid = db.user_by_email(MAIN)["id"]
    bare = db.user_by_email(BARE)["id"]
    for u in (uid, bare):
        db.display_name_set(u, "합성")
    _, ax = axis_items(uid)
    sid, did = define(uid, STORY), define(uid, DECIDE)
    con = imports.device_connect(uid, "합성 PC")
    dev, tok = con["device"]["id"], con["token"]
    imports.device_policy_set(uid, dev, {"actions": ["like"], "transform_versions": ["self-text/1", SW, "axis-page/1"], "axes": []}, 1)
    await contract_cases(dev, tok)

    # ── 2. 기록의 축 · 3. 주제 오브젝트에 축 필드 없음 ──
    tobj = define(uid, {"key": imports.TOPIC_OBJECT_KEY, "label": "주제", "semantic_kind": "collection", "fields": []})
    assert imports.device_self("Bearer " + tok)["features"] == ["axis_codes", "topics", "wrap_axes"], "세션 정리 축 줄 = wrap_axes(코드 있는 축)"
    body1 = ("## 오늘\n가짜 하루.\n### S-1. 가짜 이야기 하나\n- 장면: 가짜 장면 하나\n- 꼬리표: 가, 나\n- 이유: 가짜 이유 하나\n"
             "- 결과: " + "결" * 320 + "\n- 덧붙임: 넷째 글자 필드\n### D-1. 가짜 결정 하나\n- 말: 가짜 말 하나\n")
    r1 = await post(tok, req(dev, topic="합성 주제", axis_codes=["A", "Z"], title="합성 둘째 날", body=body1, source_date="2026-11-19"))
    assert r1["state"] == "applied" and r1["axis_codes_unknown"] == 1 and r1["topic_dropped"] == 0, r1
    assert rec_axes(uid, r1["target_id"]) == [ax["A"]], "기록에 축 A, 없는 코드 Z 는 버림"
    tp = topic_of(uid, tobj, "합성 주제")
    assert item_axes(uid, tp["id"]) == [], "축 필드 없음 = 주제에는 잇지 않는다(오류 아님)"
    r0 = await post(tok, req(dev, axis_codes=["C"], title="합성 축 줄만"))
    assert rec_axes(uid, r0["target_id"]) == [ax["C"]] and "topic_dropped" not in r0 and r0["axis_codes_unknown"] == 0
    rn = await post(tok, req(dev, title="합성 축 없음"))
    assert "axis_codes_unknown" not in rn and rec_axes(uid, rn["target_id"]) == []
    # 축 필드 꼴이 다르면(하나만) 없는 것과 같다
    tdef = db.definitions(uid, [tobj])[0]
    one = {"key": "axes", "label": "축", "value_type": "reference", "target_kind": "item", "target_object_id": db.classify_target(uid),
           "multiple": False}
    q = db.definition_propose(uid, tobj, tdef["revision"], {"key": "topics", "label": "주제", "semantic_kind": "collection", "fields": [one]})
    db.definition_apply(uid, tobj, q["proposal_id"], tdef["revision"])
    await post(tok, req(dev, topic="합성 주제", axis_codes=["B-1"], title="합성 꼴 다름"))
    assert item_axes(uid, tp["id"]) == [], "하나만 받는 필드 = 주제에 잇지 않는다"
    # 필드를 여럿으로 고치면 새 축만 더한다
    tdef = db.definitions(uid, [tobj])[0]
    q = db.definition_propose(uid, tobj, tdef["revision"], {"key": "topics", "label": "주제", "semantic_kind": "collection",
                                                           "fields": [{**one, "multiple": True}]})
    db.definition_apply(uid, tobj, q["proposal_id"], tdef["revision"])
    body2 = "### S-2. 가짜 이야기 둘\n- 장면: 가짜 장면 둘\n### D-2. 가짜 결정 둘\n- 말: 가짜 말 둘\n### D-3. 가짜 결정 셋\n- 말: 가짜 말 셋\n"
    a2 = req(dev, topic="합성 주제", axis_codes=["B-1"], title="합성 첫째 날", body=body2, source_date="2026-11-18")
    r2 = await post(tok, a2)
    assert item_axes(uid, tp["id"]) == [ax["B-1"]] and rec_axes(uid, r2["target_id"]) == [ax["B-1"]], "새 축 B-1"
    # 주제에 축이 하나라도 있으면 계산하지 않는다 — 축 하나만 물어도 전체 보기와 같다(r1 기록의 축 A 로 주제가 A 에 끼지 않는다)
    assert imports.axis_overview(uid, ax["A"])["axes"][0]["topics"] == [] and overview_topics(uid)["A"] == []
    rev = topic_of(uid, tobj, "합성 주제")["revision"]
    await post(tok, req(dev, topic="합성 주제", axis_codes=["B-1"], title="합성 같은 축"))
    assert topic_of(uid, tobj, "합성 주제")["revision"] == rev, "같은 축이면 쓰지 않는다"
    r3 = await post(tok, req(dev, topic="합성 주제", axis_codes=["A", "B-1"], title="합성 셋째 날", source_date="2026-11-20"))
    assert item_axes(uid, tp["id"]) == sorted([ax["A"], ax["B-1"]]) and topic_of(uid, tobj, "합성 주제")["revision"] == rev + 1, "A 만 더한다"
    it = db.item_get(uid, tp["id"])
    assert [ln["target_id"] for ln in it["links"] if ln["field_key"] == "axes"] and it["history"][-1]["action"] == "apply"
    # 같은 묶음 새 개정이 축 줄을 바꿔도 주제의 축은 더하기만(있는 축 그대로)
    r2b = await post(tok, {**a2, "revision": "v_" + secrets.token_hex(16), "previous_revision": a2["revision"], "axis_codes": ["C"]})
    assert rec_axes(uid, r2b["target_id"]) == [ax["C"]] and item_axes(uid, tp["id"]) == sorted([ax["A"], ax["B-1"], ax["C"]])
    print("OK 2 기록의 축(코드 → 축 항목, 없는 코드 버림 axis_codes_unknown, 축 줄만, 축 없음)")
    print("OK 3 주제의 축(필드 없음 = 기록만 · 하나만 받는 필드 = 없음 · 새 축만 더하기 · 같으면 revision 그대로 · 개정도 더하기만)")

    # ── 4. 주제 하위 목록 ──
    ch = db.item_get(uid, tp["id"])["children"]
    got = [(x["object_label"], x["title"], x["on"]) for x in ch]
    assert got == [("세션 스토리", "S-2. 가짜 이야기 둘", "2026-11-18"), ("세션 스토리", "S-1. 가짜 이야기 하나", "2026-11-19"),
                   ("소통과 결정", "D-2. 가짜 결정 둘", "2026-11-18"), ("소통과 결정", "D-3. 가짜 결정 셋", "2026-11-18"),
                   ("소통과 결정", "D-1. 가짜 결정 하나", "2026-11-19")], got
    assert {x["object_id"] for x in ch} == {sid, did}
    s1 = next(x for x in ch if x["title"].startswith("S-1"))
    assert [(f["key"], f["label"]) for f in s1["summary"]] == [("scene", "장면"), ("why", "이유"), ("result", "결과")], s1["summary"]
    assert s1["summary"][0]["text"] == "가짜 장면 하나" and len(s1["summary"][2]["text"]) == 300, "글자 필드 앞 3개, 300자"
    assert [f["key"] for f in next(x for x in ch if x["title"].startswith("S-2"))["summary"]] == ["scene"], "값 있는 것만"
    d3 = next(x["item_id"] for x in ch if x["title"].startswith("D-3"))   # 자동 분류 항목은 휴지통 대신 빼기
    route.exclude(uid, d3, db.item_get(uid, d3)["revision"])
    trash(uid, "record", r1["target_id"])
    ch2 = [x["title"] for x in db.item_get(uid, tp["id"])["children"]]
    assert ch2 == ["S-2. 가짜 이야기 둘", "D-2. 가짜 결정 둘"], ("뺀 항목, 휴지통 기록의 항목 제외", ch2)
    assert db.item_get(uid, ax["A"])["children"] == [], "붙은 글 없는 항목 = 빈 목록"
    print("OK 4 주제 하위 목록(오브젝트별, 날짜순, 요약 칸 앞 3개 300자, 값 있는 것만, 뺀 항목과 휴지통 기록 제외)")

    # ── 5. 축의 주제 목록 ──
    # 축 필드에 축이 있는 주제 = 그 축들. 축 없는 주제 = 붙은 기록들의 축(계산). 필드가 없는 계정은 모두 계산
    await post(tok, req(dev, topic="합성 둘째 주제", axis_codes=["C"], title="합성 둘째 주제 글", source_date="2026-11-21"))
    t2 = topic_of(uid, tobj, "합성 둘째 주제")
    with db.tx() as c:   # 축 필드가 생기기 전에 붙은 주제처럼 — 주제 쪽 축 관계를 지워 계산 경로를 본다
        c.execute("DELETE FROM item_links WHERE user_id=%s AND source_item_id=%s", (uid, t2["id"]))
    ov = overview_topics(uid)
    # 합성 주제의 글: 둘째 날(휴지통), 첫째 날 개정(현재 판), 셋째 날, 꼴 다름, 같은 축 = 4편, 마지막 날짜 = 셋째 날
    assert ov["A"] == [("합성 주제", 4, "2026-11-20")] and ov["B-1"] == ov["A"], ov
    assert ov["C"] == [("합성 둘째 주제", 1, "2026-11-21"), ("합성 주제", 4, "2026-11-20")], ov
    one_ax = imports.axis_overview(uid, ax["C"])["axes"][0]
    assert [t["item_id"] for t in one_ax["topics"]] == [t2["id"], tp["id"]]
    assert set(one_ax["topics"][0]) == {"item_id", "title", "records", "last_on"}
    # 휴지통 주제는 빠진다
    trash(uid, "item", t2["id"])
    assert overview_topics(uid)["C"] == [("합성 주제", 4, "2026-11-20")]
    # 주제 오브젝트 없는 계정 = 빈 목록
    ob = axes_object(bare)
    p = db.item_propose(bare, ob["id"], ob["revision"], None, 0, "A", "가짜 축", "", {}, [])
    db.item_decide(bare, p["item_id"], 0, p["proposal_id"], "apply")
    assert all(a["topics"] == [] for a in imports.axis_overview(bare)["axes"])
    print("OK 5 축의 주제 목록(축 필드 · 없으면 붙은 기록의 축 계산 · 글 수, 마지막 날짜, 늦은 순 · 휴지통 주제 제외 · 주제 오브젝트 없음 = 빈 목록)")


def main_():
    db.init_schema()
    cleanup()
    for e in EMAILS:
        db.user_by_email(e)
    lim = dict(imports.LIMITS)   # 분당 요청 한도만 시험 동안 넓힌다(하루 한도는 그대로)
    imports.LIMITS[("device", "minute", "request")] = (100000, None)
    imports.LIMITS[("user", "minute", "request")] = (100000, None)
    try:
        asyncio.run(run())
    finally:
        imports.LIMITS.clear()
        imports.LIMITS.update(lim)
        cleanup()
        db.close()
    print("ALL OK — test_axis_topic")


if __name__ == "__main__":
    main_()
