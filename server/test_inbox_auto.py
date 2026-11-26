"""받는 즉시 승인 시험(2026-11-13 원작자 「서버에 넣는건 항상 승인」) — 장치가 올린 내 글은 대기 없이 기록이 된다.

실행: DATABASE_URL=postgresql://localhost/crm_test_inbox_auto python3 server/test_inbox_auto.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다. 자료는 전부 합성.

1. 스위치 켬 — self-text/1 = self·verbatim · session-wrap/1 = structured·mixed·decision_owner self·출처 세션 정리 · self-summary/1 =
   unknown·generated·ai(인용 불가) · resolved_by auto · 대기 0 · 같은 원천 새 개정 = 새 기록·현재 판 이동(승인 경로와 같다) · 같은 내용 = noop
2. 기록 일일 한도 = 대기로 남음(잃지 않음) → auto_approve_pending 이 한도가 풀린 뒤 승인
3. 스위치 꺼짐(비상 끄기) = 대기로 남음 → 켠 뒤 auto_approve_pending 이 승인 · 옛 개정 대기는 승인하지 않는다
4. 주제 잇기(2026-11-26) — session-wrap/1 topic: 주제 오브젝트 없음 = topic_dropped 1(기록은 남음) · 오브젝트가 생기면 features topics(축과 독립)
   · 새 주제 = 항목 생성(ingest_kind inbox, 자동 분류 표시 없음) · 같은 이름(NFC, 공백, 대소문자) = 같은 항목에 이어 붙기 · 개정으로 주제 바뀜 =
   현재 판만 새 주제 · 휴지통 주제 = 붙이지 않음 · record_attach(attach_to)가 주제 연결을 지우지 않음 · 기록 한도 대기 → 승인 때 붙음 · item_get thread 날짜순
"""
import asyncio
import json
import os
import secrets
import sys
import unicodedata
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_inbox_auto). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ia-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_IMPORTS_ENABLED"] = "1"
os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402

EMAILS = ("ia-main@example.com",)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def req(dev, transform="self-text/1", original=None, prev=None, **kw):
    kind = "self_summary" if transform == "self-summary/1" else "self_text"
    r = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev, "original_id": original or "o_" + secrets.token_hex(16),
         "revision": "v_" + secrets.token_hex(16), "previous_revision": prev, "kind": kind, "execution": "attended",
         "transform_version": transform, "policy_revision": 2, "title": "합성 제목", "body": "합성 자기 글 본문이다.", "source_date": "2026-11-12"}
    if kind == "self_summary":
        r["generation"] = {"method": "ai_summary", "tool": "claude-cli", "model": "unknown", "input_scope": "self_only",
                           "inputs": [{"original_id": "o_" + secrets.token_hex(16), "revision": "v_" + secrets.token_hex(16), "sha256": "ab" * 32}]}
    r.update(kw)
    return r


async def post(tok, body):
    hd = {"content-type": "application/json", "authorization": "Bearer " + tok,
          "idempotency-key": imports.idempotency_key(body["source_instance_id"], body["original_id"], body["revision"])}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        r = await h.post("/api/imports", content=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=hd)
    assert r.status_code in (200, 201), r.text
    return r.json()


def rec(uid, rid):
    with db.tx() as c:
        return c.execute("SELECT author_kind, text_process, generation_kind, decision_owner, source, ingest_kind, body FROM records "
                         "WHERE user_id=%s AND id=%s", (uid, rid)).fetchone()


def entry(uid, iid):
    with db.tx() as c:
        return c.execute("SELECT state, resolved_by, payload IS NULL AS gone, is_current_applied, target_record_id FROM import_entries "
                         "WHERE user_id=%s AND id=%s", (uid, iid)).fetchone()


async def run():
    uid = db.user_by_email(EMAILS[0])["id"]
    db.display_name_set(uid, "합성")
    con = imports.device_connect(uid, "합성 PC")
    dev, tok = con["device"]["id"], con["token"]
    imports.device_policy_set(uid, dev, {"actions": ["like"], "transform_versions": ["self-text/1", "self-summary/1", "session-wrap/1"],
                                         "axes": []}, 1)
    lim = dict(imports.LIMITS)
    imports.LIMITS[("device", "minute", "request")] = (100000, None)
    imports.LIMITS[("user", "minute", "request")] = (100000, None)
    try:
        await body(uid, dev, tok)
    finally:
        imports.LIMITS.clear()
        imports.LIMITS.update(lim)


async def body(uid, dev, tok):
    # ── 1. 스위치 켬 = 받는 즉시 승인 ──
    b1 = req(dev)
    r = await post(tok, b1)
    assert r["state"] == "applied" and r["target_kind"] == "record" and not r["duplicate"], r
    assert entry(uid, r["import_id"]) == {"state": "applied", "resolved_by": "auto", "gone": True, "is_current_applied": True,
                                          "target_record_id": r["target_id"]}
    x = rec(uid, r["target_id"])
    assert (x["author_kind"], x["text_process"], x["source"], x["ingest_kind"]) == ("self", "verbatim", imports.RECORD_SOURCE_TEXT, "inbox"), x
    r1 = r["target_id"]
    w = await post(tok, req(dev, transform="session-wrap/1"))
    y = rec(uid, w["target_id"])
    assert (y["author_kind"], y["text_process"], y["generation_kind"], y["decision_owner"], y["source"]) == \
        ("self", "structured", "mixed", "self", imports.SESSION_WRAP_SOURCE), y
    s = await post(tok, req(dev, transform="self-summary/1"))
    z = rec(uid, s["target_id"])
    assert (z["author_kind"], z["text_process"], z["generation_kind"]) == ("unknown", "generated", "ai"), z
    assert imports.inbox_list(uid, "pending")["entries"] == [] and imports.inbox_count(uid) == 0
    # 같은 원천 새 개정 = 새 기록·현재 판 이동(승인 경로와 같다) · 같은 내용 새 개정 = noop · 같은 개정 재전송 = duplicate
    b2 = req(dev, original=b1["original_id"], prev=b1["revision"], body="합성 고친 본문이다.")
    r = await post(tok, b2)
    assert r["state"] == "applied" and r["target_id"] != r1 and rec(uid, r["target_id"])["body"] == "합성 고친 본문이다."
    with db.tx() as c:
        cur = c.execute("SELECT count(*) AS n FROM import_entries WHERE user_id=%s AND original_id=%s AND is_current_applied",
                        (uid, b1["original_id"])).fetchone()["n"]
    assert cur == 1
    b3 = {**b2, "revision": "v_" + secrets.token_hex(16), "previous_revision": b2["revision"]}
    assert (await post(tok, b3))["state"] == "noop"
    assert (await post(tok, b3))["duplicate"] is True
    print("OK 1 받는 즉시 승인(self-text·session-wrap·self-summary 출처 판정 · resolved_by auto · 대기 0 · 새 개정 = 새 기록 · noop · duplicate)")

    # ── 2. 기록 일일 한도 = 대기로 남음 → 한도가 풀리면 auto_approve_pending ──
    saved = dict(db.DAILY_LIMITS)
    with db.tx() as c:
        n_rec = c.execute(f"SELECT count(*) AS n FROM records WHERE user_id=%s AND COALESCE(received_at, created) >= {db._KST_TODAY} "
                          "AND ingest_kind <> 'board_migration'", (uid,)).fetchone()["n"]
    db.DAILY_LIMITS.update(records=n_rec)
    try:
        q = await post(tok, req(dev, body="합성 한도 초과 본문이다."))
        assert q["state"] == "pending" and q["target_id"] is None, q
        assert imports.auto_approve_pending() == 0 and entry(uid, q["import_id"])["state"] == "pending", "한도 안이면 다음 회차"
    finally:
        db.DAILY_LIMITS.clear()
        db.DAILY_LIMITS.update(saved)
    assert imports.auto_approve_pending() == 1
    e = entry(uid, q["import_id"])
    assert (e["state"], e["resolved_by"], e["gone"]) == ("applied", "auto", True) and rec(uid, e["target_record_id"])["body"] == "합성 한도 초과 본문이다."
    print("OK 2 기록 한도 = 대기로 남음(잃지 않음) → 한도가 풀린 회차에 승인")

    # ── 3. 스위치 꺼짐 = 대기 → 켠 뒤 승인 · 옛 개정은 승인하지 않는다 ──
    os.environ.pop("CRM_INBOX_APPROVALS_ENABLED", None)
    try:
        o1 = req(dev, body="합성 꺼짐 본문 하나.")
        p1 = await post(tok, o1)
        p2 = await post(tok, req(dev, original=o1["original_id"], prev=o1["revision"], body="합성 꺼짐 본문 둘."))
        assert p1["state"] == p2["state"] == "pending"
        assert entry(uid, p1["import_id"])["state"] == "excluded", "같은 원천 옛 대기는 새 개정이 닫는다(superseded)"
        assert imports.auto_approve_pending() == 0, "스위치 꺼짐 = 승인 안 함"
    finally:
        os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
    assert imports.auto_approve_pending() == 1
    e = entry(uid, p2["import_id"])
    assert (e["state"], e["resolved_by"]) == ("applied", "auto") and rec(uid, e["target_record_id"])["body"] == "합성 꺼짐 본문 둘."
    assert imports.inbox_count(uid) == 0
    print("OK 3 스위치 꺼짐 = 대기(비상 끄기) → 켠 뒤 승인 · 옛 개정 대기는 닫힘")
    await topics(uid, dev, tok)


def topic_links(uid, rid):
    return [ln["target_id"] for ln in db.record_links(uid, [rid]) if ln["field_key"] == "topics"]


def topic_items(uid, oid):
    with db.tx() as c:
        return c.execute("SELECT id, title, ingest_kind, trashed_at FROM items WHERE user_id=%s AND object_id=%s AND revision > 0 "
                         "ORDER BY created_at, id", (uid, oid)).fetchall()


async def topics(uid, dev, tok):
    # ── 4. 주제 잇기 ──
    sw = dict(transform="session-wrap/1")
    r = await post(tok, req(dev, topic="합성 주제", **sw))
    assert r["state"] == "applied" and r["topic_dropped"] == 1 and topic_links(uid, r["target_id"]) == [], "오브젝트 없음 = 기록만"
    assert "topics" not in imports.device_self("Bearer " + tok)["features"]
    q = db.definition_propose(uid, None, 0, {"key": imports.TOPIC_OBJECT_KEY, "label": "주제", "semantic_kind": "collection", "fields": []})
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    oid = q["object_id"]
    assert imports.device_self("Bearer " + tok)["features"] == ["topics"], "축 항목 없이도 topics 는 실린다"
    # 새 주제 = 항목 하나. 날짜를 거꾸로 보내 thread 가 날짜순인지 본다
    a = req(dev, topic="합성 주제", source_date="2026-11-20", title="합성 셋째 날", **sw)
    r1 = await post(tok, a)
    assert r1["topic_dropped"] == 0, r1
    its = topic_items(uid, oid)
    assert [(x["title"], x["ingest_kind"]) for x in its] == [("합성 주제", "inbox")], its
    tid = its[0]["id"]
    assert topic_links(uid, r1["target_id"]) == [tid]
    full = db.item_get(uid, tid)
    assert not full.get("auto_routed"), "자동 분류 표시 없음"
    # 같은 이름(연속 공백, NFD, 대소문자) = 같은 항목에 이어 붙기
    r2 = await post(tok, req(dev, topic="합성  주제", source_date="2026-11-18", title="합성 첫째 날", **sw))
    r3 = await post(tok, req(dev, topic=unicodedata.normalize("NFD", "합성 주제"), source_date="2026-11-19", title="합성 둘째 날", **sw))
    assert topic_links(uid, r2["target_id"]) == topic_links(uid, r3["target_id"]) == [tid] and len(topic_items(uid, oid)) == 1
    rc = await post(tok, req(dev, topic="Topic Case", **sw))
    rc2 = await post(tok, req(dev, topic="topic case", **sw))
    assert topic_links(uid, rc["target_id"]) == topic_links(uid, rc2["target_id"]) and len(topic_items(uid, oid)) == 2
    th = db.item_get(uid, tid)["thread"]
    assert [(x["title"], x["on"]) for x in th] == [("합성 첫째 날", "2026-11-18"), ("합성 둘째 날", "2026-11-19"),
                                                   ("합성 셋째 날", "2026-11-20")], th
    assert th[0]["body"] and th[0]["record_id"] == r2["target_id"]
    assert db.item_get(uid, topic_items(uid, oid)[1]["id"])["thread"][0]["on"] == "2026-11-12"
    # 다른 변환에 topic = 계약 위반
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        b = req(dev, topic="합성 주제")
        bad = await h.post("/api/imports", content=json.dumps(b, ensure_ascii=False).encode("utf-8"), headers={
            "content-type": "application/json", "authorization": "Bearer " + tok,
            "idempotency-key": imports.idempotency_key(b["source_instance_id"], b["original_id"], b["revision"])})
    assert bad.status_code == 400 and bad.json()["code"] == "CONTRACT-INVALID" and "topic" in bad.json()["msg"], bad.text
    # 개정으로 주제 바뀜 = 현재 판 기록만 새 주제에(옛 판 기록의 주제 연결은 떨어진다)
    a2 = req(dev, original=a["original_id"], prev=a["revision"], topic="합성 다른 주제", source_date="2026-11-20", title="합성 셋째 날", **sw)
    r4 = await post(tok, a2)
    new = [x["id"] for x in topic_items(uid, oid) if x["title"] == "합성 다른 주제"]
    assert r4["topic_dropped"] == 0 and len(new) == 1 and topic_links(uid, r4["target_id"]) == new
    assert topic_links(uid, r1["target_id"]) == [] and len(db.item_get(uid, tid)["thread"]) == 2
    # 주제 줄을 뺀 개정 = 현재 판은 주제 없음(topic 키 없음 → topic_dropped 키도 없음)
    a3 = req(dev, original=a["original_id"], prev=a2["revision"], source_date="2026-11-20", title="합성 셋째 날", body="합성 주제 없는 판.", **sw)
    r5 = await post(tok, a3)
    assert "topic_dropped" not in r5 and topic_links(uid, r5["target_id"]) == [] and topic_links(uid, r4["target_id"]) == []
    # record_attach(attach_to) 는 주제 연결을 지우지 않는다
    db.record_attach(uid, r2["target_id"], attach_to=[])
    assert topic_links(uid, r2["target_id"]) == [tid]
    # 휴지통 주제 = 붙이지 않는다(새로 만들지도 않는다)
    os.environ["CRM_TRASH_ENABLED"] = "1"
    try:
        db.trash_move(uid, "item", new[0], db.item_get(uid, new[0])["revision"])
    finally:
        os.environ.pop("CRM_TRASH_ENABLED", None)
    r6 = await post(tok, req(dev, topic="합성 다른 주제", **sw))
    assert r6["topic_dropped"] == 1 and topic_links(uid, r6["target_id"]) == [] and len(topic_items(uid, oid)) == 3
    # 기록 일일 한도 = 대기(topic_dropped 없음) → 한도가 풀린 회차 승인 때 붙는다
    saved = dict(db.DAILY_LIMITS)
    with db.tx() as c:
        n_rec = c.execute(f"SELECT count(*) AS n FROM records WHERE user_id=%s AND COALESCE(received_at, created) >= {db._KST_TODAY} "
                          "AND ingest_kind <> 'board_migration'", (uid,)).fetchone()["n"]
    db.DAILY_LIMITS.update(records=n_rec)
    try:
        p = await post(tok, req(dev, topic="합성 주제", body="합성 한도 뒤 주제 본문.", **sw))
        assert p["state"] == "pending" and "topic_dropped" not in p, p
    finally:
        db.DAILY_LIMITS.clear()
        db.DAILY_LIMITS.update(saved)
    assert imports.auto_approve_pending() == 1
    assert topic_links(uid, entry(uid, p["import_id"])["target_record_id"]) == [tid]
    print("OK 4 주제 잇기(오브젝트 없음 dropped · features 독립 · 새 주제 · 이름 정규화 이어 붙기 · 다른 변환 거절 · 개정 이동 · "
          "attach_to 와 따로 · 휴지통 · 한도 대기 뒤 붙음 · thread 날짜순)")


def main_():
    db.init_schema()
    cleanup()
    db.user_by_email(EMAILS[0])
    try:
        asyncio.run(run())
    finally:
        cleanup()
        db.close()
    print("ALL OK — test_inbox_auto")


if __name__ == "__main__":
    main_()
