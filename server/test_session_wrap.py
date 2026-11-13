"""세션 정리 → 판단 확정 A안 시험 (2026-11-04, notes 「2026-11-04_세션정리-결정본인-구현계획」).

실행: DATABASE_URL=postgresql://localhost/crm_test_session_wrap python3 server/test_session_wrap.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다. 자료는 전부 합성.

1) 적격 표(후보 만들기 candidates_propose · 확정 candidate_decide 둘 다): verbatim·self OK · structured·decision_owner=self OK(신규)
   · structured·NULL = 만들기 거절·확정 CANDIDATE-REVIEW(processed) · external = SCOPE-SELF-ONLY·확정 CANDIDATE-REVIEW(external) · 휴지통 IN-TRASH
2) MCP record_add decision_owner · record_provenance_set 로 표시 붙이기·지우기(세션 정리 기록 = mixed 여도 AI 잠금 없음) · 후보 있으면 지우기 PROVENANCE-LOCKED
   · 가공 방식 바꾸기는 여전히 PROVENANCE-AI-LOCKED · 이력 한 줄 · decide_preview shown
3) 가져오기: session-wrap/1 → 승인 대기 → 승인 = self·structured·mixed·「내 결정」·출처 「세션 정리」 → 후보 확정 OK · 허용 규칙에 없으면 POLICY-DENIED
3b) MCP inbox_decide(facade 전용 D): decide_preview shown · bind 규칙 · 승인 = 같은 기록 꼴 + 가린 경로 수 메타 · 제외 · 스위치·표시 이름 관문
4) 화면 표시 0: /api/state·/api/records·/api/journal·/api/inbox·/api/trash 응답 · 코어 정의(web.core_schema·service_schema)에 decision_owner 없음
5) 옛 DB 업그레이드(records.decision_owner 없음 → 열·CHECK, 옛 행 NULL · 멱등)
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
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_session_wrap). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "sw-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "session-wrap-test-secret"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from mcp.client import Client  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import service_schema  # noqa: E402
import web  # noqa: E402

MAIN = "sw-main@example.com"
PUBLIC = "http://127.0.0.1:8800"
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
BODY = "합성 정리 글이다. 내가 화면 칸을 하나로 줄이기로 정했다. 도구 비교는 다음으로 미뤘다."
QUOTE = "화면 칸을 하나로 줄이기로 정했다"
LEAK = ("decision_owner", "내 결정", "결정은 본인")


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = %s", (MAIN,)).fetchall()]
    for uid in ids:
        db.user_delete(uid)


def ok(msg):
    print("OK —", msg, flush=True)


def val(res):
    assert not res.is_error, res.content[0].text[:400]
    sc = getattr(res, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(res.content[0].text)


def code(res):
    assert res.is_error, ("오류가 아님", res.content[0].text[:300] if res.content else res)
    m = CODE.search(res.content[0].text)
    return m.group(1) if m else "SDK"


def expect(want, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == want, (want, e.code, e.message)
        return e
    raise AssertionError(f"{want} 가 나야 하는데 성공했어요")


def row(uid, rid):
    with db.tx() as c:
        return c.execute("SELECT author_kind,text_process,generation_kind,decision_owner,source,ingest_kind,source_date,provenance_history "
                         "FROM records WHERE user_id=%s AND id=%s", (uid, rid)).fetchone()


def sql(q, args):
    with db.tx() as c:
        c.execute(q, args)


def propose(uid, rid, quote=QUOTE, text="칸은 하나로 줄인다"):
    return db.candidates_propose(uid, rid, None, [{"text": text, "quote": quote}], "ai")


def cand(uid, rid):
    added, dropped = propose(uid, rid)
    assert added and not dropped, dropped
    return added[0]


def review_of(uid, cid):
    return db.candidate_get(uid, cid)["review"]


# ── 1) 적격 표 ────────────────────────────────────────

def test_eligibility(uid):
    # verbatim·self → 만들기·확정 OK(기존)
    rv = db.record_add(uid, "원문", BODY)["id"]
    cv = cand(uid, rv)
    assert review_of(uid, cv) is None
    assert db.candidate_decide(uid, cv, "confirm")["status"] == "confirmed"
    # structured·decision_owner=self → OK(신규)
    ro = db.record_add(uid, "정리", BODY, text_process="structured", decision_owner="self")["id"]
    assert row(uid, ro)["decision_owner"] == "self"
    co = cand(uid, ro)
    assert review_of(uid, co) is None
    assert db.candidate_decide(uid, co, "confirm")["status"] == "confirmed"
    # structured·NULL → 만들기 거절(기존 문구) · 확정 CANDIDATE-REVIEW(processed)
    rn = db.record_add(uid, "정리 표시 없음", BODY, text_process="structured")["id"]
    added, dropped = propose(uid, rn)
    assert not added and dropped[0]["why"] == db.INELIGIBLE_WHY, dropped
    rn2 = db.record_add(uid, "표시 뒤 지움", BODY, text_process="structured", decision_owner="self")["id"]
    cn = cand(uid, rn2)
    sql("UPDATE records SET decision_owner=NULL WHERE user_id=%s AND id=%s", (uid, rn2))   # 정정 잠금을 건너뛴 옛 상태 흉내
    assert review_of(uid, cn) == "processed"
    e = expect("CANDIDATE-REVIEW", db.candidate_decide, uid, cn, "confirm")
    assert "원문 그대로가 아니라" in e.message
    # external → 넣기 거절 · 표시가 있어도 확정 거절(external)
    expect("SCOPE-SELF-ONLY", db.record_add, uid, "남의 글", BODY, author_kind="external")
    expect("ARG-INVALID", db.record_add, uid, "작성자 모름", BODY, author_kind="unknown", text_process="structured", decision_owner="self")
    rx = db.record_add(uid, "남의 글로 바뀜", BODY, text_process="structured", decision_owner="self")["id"]
    cx = cand(uid, rx)
    sql("UPDATE records SET author_kind='external' WHERE user_id=%s AND id=%s", (uid, rx))
    assert review_of(uid, cx) == "external"
    expect("CANDIDATE-REVIEW", db.candidate_decide, uid, cx, "confirm")
    added, dropped = propose(uid, rx, quote="도구 비교는 다음으로 미뤘다")
    assert not added and dropped, "external 기록에서 후보가 나왔다"
    # 휴지통 → 거절
    rt = db.record_add(uid, "휴지통 갈 정리", BODY, text_process="structured", decision_owner="self")["id"]
    ct = cand(uid, rt)
    db.trash_move(uid, "record", rt)
    expect("IN-TRASH", db.candidate_decide, uid, ct, "confirm")
    expect("IN-TRASH", propose, uid, rt, "도구 비교는 다음으로 미뤘다")
    # 승격 집계도 같은 SQL — 표시 있는 정리 기록의 확정 후보는 적격으로 센다
    with db.tx() as c:
        n = c.execute(f"SELECT count(*) AS n FROM candidates c JOIN records r ON r.user_id=c.user_id AND r.id=c.record_id "
                      f"AND {db._ELIGIBLE_SQL} WHERE c.user_id=%s AND c.id = ANY(%s)", (uid, [cv, co, cn])).fetchone()["n"]
    assert n == 2, n
    ok("적격 표 — verbatim OK · structured+「내 결정」 OK · structured 표시 없음 거절(processed) · external 거절 · 휴지통 거절 · 집계 SQL 같음")
    return rt


# ── 2) MCP record_add · record_provenance_set ───────────

async def test_mcp(uid):
    async with Client(main.mcp) as c:
        r = val(await c.call_tool("record_add", {"text": BODY, "title": "대화 기록", "decision_owner": "self"}))
        assert row(uid, r["id"])["decision_owner"] == "self"
        assert "decision_owner" not in r   # 응답 모양은 그대로
        r0 = val(await c.call_tool("record_add", {"text": BODY, "title": "표시 없음"}))
        assert row(uid, r0["id"])["decision_owner"] is None
        # 세션 정리 같은 mixed 기록 — 표시만 바꾸는 정정은 AI 잠금을 받지 않는다
        rid = db.record_add(uid, "세션 정리 흉내", BODY, text_process="structured", decision_owner="self")["id"]
        sql("UPDATE records SET generation_kind='mixed' WHERE user_id=%s AND id=%s", (uid, rid))
        args = {"record_id": rid, "author_kind": "self", "text_process": "structured", "reason": "이건 내 결정이 아니었다", "decision_owner": "none"}
        pv = val(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_provenance_set", "params": args}}))
        assert pv["shown"]["「내 결정」 표시 전"] == "내 결정" and pv["shown"]["「내 결정」 표시 후"] == "표시 없음", pv["shown"]
        out = val(await c.call_tool("decide", {"op": "record_provenance_set", "params": args, "bind": pv["bind"]}))
        assert out["text_process"] == "structured"
        h = row(uid, rid)
        assert h["decision_owner"] is None
        last = h["provenance_history"][-1]
        assert last["from"]["decision_owner"] == "self" and last["decision_owner"] is None and last["via"] == "mcp", last
        pv2 = val(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_provenance_set", "params": {
            "record_id": rid, "author_kind": "self", "text_process": "structured", "reason": "같은 값"}}}))
        assert not any("내 결정" in k for k in pv2["shown"]), pv2["shown"]   # 표시를 안 바꾸면 줄도 없다
        # 다시 붙이기 → 후보 → 지우기는 잠금
        r2 = await c.call_tool("record_provenance_set", {"record_id": rid, "author_kind": "self", "text_process": "structured",
                                                         "reason": "다시 보니 내 결정", "decision_owner": "self"})
        assert not r2.is_error, r2.content[0].text
        cand(uid, rid)
        r3 = await c.call_tool("record_provenance_set", {"record_id": rid, "author_kind": "self", "text_process": "structured",
                                                         "reason": "지우기", "decision_owner": "none"})
        assert code(r3) == "PROVENANCE-LOCKED"
        # 가공 방식 바꾸기는 여전히 AI 잠금(생성 이력 보존)
        r4 = await c.call_tool("record_provenance_set", {"record_id": rid, "author_kind": "self", "text_process": "verbatim", "reason": "x"})
        assert code(r4) == "PROVENANCE-AI-LOCKED"
        # 원문 기록(후보 있음) → structured 로 바꾸면서 「내 결정」을 붙이면 근거가 그대로라 잠기지 않는다 · 표시 없이 바꾸면 잠긴다
        rv = db.record_add(uid, "원문", BODY)["id"]
        cand(uid, rv)
        r5 = await c.call_tool("record_provenance_set", {"record_id": rv, "author_kind": "self", "text_process": "structured", "reason": "정리"})
        assert code(r5) == "PROVENANCE-LOCKED"
        r6 = await c.call_tool("record_provenance_set", {"record_id": rv, "author_kind": "self", "text_process": "structured",
                                                         "reason": "정리했지만 내 결정", "decision_owner": "self"})
        assert not r6.is_error, r6.content[0].text
        assert row(uid, rv)["decision_owner"] == "self"
        r7 = await c.call_tool("record_provenance_set", {"record_id": rv, "author_kind": "unknown", "text_process": "structured",
                                                         "reason": "모름", "decision_owner": "self"})
        assert code(r7) == "ARG-INVALID"
    ok("MCP record_add 「내 결정」 · 정정(붙이기·지우기, mixed 도 · 후보 있으면 지우기 잠금 · 가공 방식은 AI 잠금 · 미리보기 줄)")


# ── 3) 가져오기 session-wrap/1 ──────────────────────────

def _req(dev, transform="session-wrap/1", **kw):
    r = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev, "original_id": "o_" + secrets.token_hex(16),
         "revision": "v_" + secrets.token_hex(16), "previous_revision": None, "kind": "self_text", "execution": "unattended",
         "transform_version": transform, "policy_revision": 1, "title": "합성 세션 정리 제목", "body": BODY, "source_date": "2030-01-02"}
    r.update(kw)
    return r


async def _post(token, body):
    hd = {"content-type": "application/json", "authorization": "Bearer " + token,
          "idempotency-key": imports.idempotency_key(body["source_instance_id"], body["original_id"], body["revision"])}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        return await h.post("/api/imports", content=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=hd)


async def test_import(uid):
    saved = {n: os.environ.get("CRM_" + n) for n in ("IMPORTS_ENABLED", "INBOX_APPROVALS_ENABLED")}
    os.environ["CRM_IMPORTS_ENABLED"] = os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
    try:
        con = imports.device_connect(uid, "합성 PC")
        dev, tok = con["device"], con["token"]
        assert "session-wrap/1" in dev["policy"]["transform_versions"]
        r = await _post(tok, _req(dev["id"]))   # 받는 즉시 승인(2026-11-13) — 대기 없이 기록, 출처 판정은 승인과 같다
        assert r.status_code == 201 and r.json()["state"] == "applied" and r.json()["target_kind"] == "record", r.text
        rid = r.json()["target_id"]
        x = row(uid, rid)
        assert (x["author_kind"], x["text_process"], x["generation_kind"], x["decision_owner"], x["source"], x["ingest_kind"]) == \
            ("self", "structured", "mixed", "self", "세션 정리", "inbox"), x
        assert str(x["source_date"]) == "2030-01-02"
        cid = cand(uid, rid)
        assert db.candidate_decide(uid, cid, "confirm")["status"] == "confirmed"
        # 같은 계약의 self-text/1 은 그대로 원문(표시 없음)
        r = await _post(tok, _req(dev["id"], transform="self-text/1"))
        y = row(uid, r.json()["target_id"])
        assert (y["text_process"], y["decision_owner"], y["source"]) == ("verbatim", None, imports.RECORD_SOURCE_TEXT), y
        # 허용 규칙에서 빼면 POLICY-DENIED
        pol = {"actions": ["like"], "transform_versions": ["self-text/1"], "axes": []}
        imports.device_policy_set(uid, dev["id"], pol, 1)
        r = await _post(tok, _req(dev["id"], policy_revision=2))
        assert r.status_code == 403 and r.json()["code"] == "POLICY-DENIED", r.text
        assert web.TRANSFORM_LABELS["session-wrap/1"] == "세션 정리(바로 저장)"
    finally:
        for n, v in saved.items():
            os.environ.pop("CRM_" + n, None)
            if v is not None:
                os.environ["CRM_" + n] = v
    ok("가져오기 session-wrap/1 — 받는 즉시 승인 = self·structured·mixed·「내 결정」·출처 「세션 정리」 → 후보 확정 · self-text/1 그대로 · 허용 규칙 밖 거절")


# ── 3b) MCP inbox_decide(승인·제외, facade 전용 D) ────────

async def test_inbox_decide(uid):
    saved = {n: os.environ.get("CRM_" + n) for n in ("IMPORTS_ENABLED", "INBOX_APPROVALS_ENABLED")}
    os.environ["CRM_IMPORTS_ENABLED"] = os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
    mask = imports.SESSION_WRAP_PATH_MASK
    try:
        con = imports.device_connect(uid, "합성 PC 2")
        dev, tok = con["device"], con["token"]

        async def pending(**kw):   # 승인 스위치를 끄고 받아 대기로 남긴다(켜져 있으면 받는 즉시 승인)
            os.environ.pop("CRM_INBOX_APPROVALS_ENABLED", None)
            try:
                r = await _post(tok, _req(dev["id"], **kw))
            finally:
                os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
            assert r.status_code == 201 and r.json()["state"] == "pending", r.text
            return r.json()["import_id"]
        wrap_body = f"합성 정리 글이다. {mask} 에 남긴 계획을 보고 칸을 하나로 줄이기로 정했다. 비교 표는 {mask} 에 있다."
        e1 = await pending(body=wrap_body)
        long_body = "합성 원문 문장이다. " * 40
        e2 = await pending(transform="self-text/1", title="합성 원문 제목", body=long_body)
        async with Client(main.mcp) as c:
            d = val(await c.call_tool("find", {"op": "inbox_decide"}))
            assert d["tier"] == "decide" and d["family"] == "inbox" and "decide_preview" in d["flow"][0]
            assert "승인·제외를 말한 뒤에만" in d["rule"], d["rule"]
            assert "inbox_decide" in [m["op"] for m in val(await c.call_tool("find", {"query": "승인 대기 승인"}))["matches"]]
            assert "inbox_decide" not in {t.name for t in (await c.list_tools()).tools}, "직접 도구로 등록하지 않는다"
            a1 = {"import_id": e1, "action": "approve"}
            pv = val(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "inbox_decide", "params": a1}}))
            assert pv["shown"] == {"할 일": "승인 — 내 글로 저장", "종류": "내 글", "제목": "합성 세션 정리 제목", "본문 앞부분": wrap_body,
                                   "출처": "세션 정리"}, pv["shown"]
            assert not any("내 결정" in k or "결정은 본인" in k for k in pv["shown"]), pv["shown"]   # 운영에 안 보인다(원작자)
            assert pv["irreversible"] is False and pv["impact"]["import_id"] == e1
            assert code(await c.call_tool("decide", {"op": "inbox_decide", "params": a1})) == "BIND-REQUIRED"
            assert code(await c.call_tool("write", {"op": "inbox_decide", "params": a1})) == "TIER-MISMATCH"
            # 같은 bind 로 action 만 바꾸면 STALE(인자가 바뀜)
            r = await c.call_tool("decide", {"op": "inbox_decide", "params": {**a1, "action": "exclude"}, "bind": pv["bind"]})
            assert code(r) == "BIND-STALE", r
            out = val(await c.call_tool("decide", {"op": "inbox_decide", "params": a1, "bind": pv["bind"]}))
            assert out["state"] == "applied" and out["via"] == "facade", out
            x = row(uid, out["record_id"])
            assert (x["author_kind"], x["text_process"], x["generation_kind"], x["decision_owner"], x["source"], x["ingest_kind"]) == \
                ("self", "structured", "mixed", "self", "세션 정리", "inbox"), x
            with db.tx() as cx:
                gm = cx.execute("SELECT generation_meta FROM records WHERE user_id=%s AND id=%s", (uid, out["record_id"])).fetchone()["generation_meta"]
            assert gm["redacted_paths"] == 2, gm   # 가린 수는 기록 메타에만
            r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "inbox_decide", "params": a1}})
            assert code(r) == "INBOX-RESOLVED", "처리한 대기는 미리보기도 같은 오류"
            # 원문(self-text/1) — 본문 앞부분 300자 + …, 출처 「연결 장치에서 가져옴」, 「내 결정」 줄 없음 · 제외 = 되돌릴 수 없음
            pv2 = val(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "inbox_decide",
                                                                                   "params": {"import_id": e2, "action": "approve"}}}))
            assert pv2["shown"]["본문 앞부분"] == long_body[:imports.INBOX_PREVIEW_CHARS] + "…" and pv2["shown"]["출처"] == imports.RECORD_SOURCE_TEXT
            assert "「내 결정」 표시" not in pv2["shown"]
            a2 = {"import_id": e2, "action": "exclude"}
            px = val(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "inbox_decide", "params": a2}}))
            assert px["irreversible"] is True and px["shown"]["할 일"].startswith("제외")
            # 승인 스위치 꺼짐 — 승인 미리보기는 APPROVALS-OFF, 제외는 된다(웹과 같다)
            os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "0"
            r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "inbox_decide", "params": {"import_id": e2, "action": "approve"}}})
            assert code(r) == "APPROVALS-OFF", r
            # 표시 이름 관문 = 웹과 같은 write_gate
            with db.tx() as cx:
                cx.execute("UPDATE users SET display_name=NULL WHERE id=%s", (uid,))
            try:
                assert code(await c.call_tool("decide", {"op": "inbox_decide", "params": a2, "bind": px["bind"]})) == "NAME-REQUIRED"
            finally:
                db.display_name_set(uid, "세션 정리 시험")
            out = val(await c.call_tool("decide", {"op": "inbox_decide", "params": a2, "bind": px["bind"]}))
            assert out == {"import_id": e2, "state": "excluded", "via": "facade"}, out
            assert imports.inbox_get(uid, e2)["body"] is None
    finally:
        for n, v in saved.items():
            os.environ.pop("CRM_" + n, None)
            if v is not None:
                os.environ["CRM_" + n] = v
    ok("MCP inbox_decide(facade D) — find·decide_preview shown(제목·본문 앞부분·출처 · 「내 결정」 줄 없음) · BIND-REQUIRED·STALE·TIER-MISMATCH "
       "· 승인 = 세션 정리 기록(가린 경로 수 메타) · 처리 뒤 INBOX-RESOLVED · 제외 되돌릴 수 없음 · APPROVALS-OFF · NAME-REQUIRED")


# ── 4) 화면 표시 0 ────────────────────────────────────

async def test_no_display(uid, trashed_rid):
    site = main.site
    real = site.dev, site.dev_user
    site.dev, site.dev_user = True, MAIN
    with db.tx() as c:
        live = c.execute("SELECT id FROM records WHERE user_id=%s AND decision_owner='self' AND trashed_at IS NULL", (uid,)).fetchall()
    assert len(live) >= 3, live
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            paths = ["/api/state", "/api/records?limit=100", "/api/inbox?state=all", "/api/trash",
                     *[f"/api/journal?id={x['id']}" for x in live],
                     f"/api/trash/record/{trashed_rid}", "/app"]
            for p in paths:
                r = await h.get(p)
                assert r.status_code == 200, (p, r.status_code, r.text[:200])
                for w in LEAK:
                    assert w not in r.text, (p, w)
    finally:
        site.dev, site.dev_user = real
    sql_text = (HERE / "schema.sql").read_text(encoding="utf-8")
    assert "decision_owner" in sql_text
    core = web.core_schema(sql_text)
    rec = next(t for t in core if t["table"] == "records")
    assert "decision_owner" not in {f["name"] for f in rec["fields"]}
    assert "decision_owner" not in json.dumps(service_schema._core_objects(core), ensure_ascii=False)
    ok("화면 표시 0 — /api/state·records·journal·inbox·trash·/app 응답 · 코어 정의·Object Manager 표시 자료에 decision_owner·문구 없음")


# ── 5) 옛 DB 업그레이드 ───────────────────────────────

def test_upgrade(uid):
    with db.tx() as c:
        c.execute("ALTER TABLE records DROP CONSTRAINT IF EXISTS ck_records_decision_owner")
        c.execute("ALTER TABLE records DROP COLUMN decision_owner")
    db.init_schema()
    with db.tx() as c:
        assert {r["d"] for r in c.execute("SELECT decision_owner AS d FROM records WHERE user_id=%s", (uid,)).fetchall()} == {None}
        assert c.execute("SELECT 1 FROM pg_constraint WHERE conname='ck_records_decision_owner'").fetchone()
    db.init_schema()   # 멱등
    expect("ARG-INVALID", db.record_add, uid, "x", BODY, decision_owner="other")
    ok("옛 DB 업그레이드(records.decision_owner 열·CHECK, 옛 행 NULL · 멱등)")


async def run():
    db.init_schema()
    cleanup()
    try:
        db.user_by_email(MAIN)
        uid = db.user_by_email(MAIN)["id"]
        db.display_name_set(uid, "세션 정리 시험")
        trashed = test_eligibility(uid)
        await test_mcp(uid)
        await test_import(uid)
        await test_inbox_decide(uid)
        await test_no_display(uid, trashed)
        test_upgrade(uid)
    finally:
        cleanup()
        db.close()
    print("OK — 세션 정리 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
