"""수기 수정 A0′ 시험 (2026-11-03, React 전환 구현계획 §5-1).

실행: DATABASE_URL=postgresql://localhost/crm_test_record_edit python3 server/test_record_edit.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1) MCP record_edit(facade D): decide_preview shown = 전·후 + 사라질 미결 후보 수 · bind 필수·STALE · old 0번 EDIT-NOT-FOUND · 2번(겹침 포함)
   EDIT-AMBIGUOUS · revision CONFLICT · 잠금 RECORD-LOCKED(확정·남기지 않음 후보 · external) · 휴지통 IN-TRASH · 이력 한 줄(via mcp) · 일일 한도 밖
2) 미결 후보(메인 판정 c′): 변경 구간과 겹치거나 닿으면 삭제 · 앞 그대로 · 뒤 delta 이동(UNIQUE 순간 충돌 없음) · 이동 뒤 quote 단언
3) record_title_set(facade W): 판단 붙은 글도 됨 · 같은 제목 no-op · 이력(title) · 휴지통·external 거절
4) 웹: POST /api/records/{id}/body(공통 앞·뒤를 뺀 한 구간) · /title · /api/item/edit(propose+apply 한 트랜잭션, 확정 유지, 이력 한 줄)
   · 401 · Origin 403 · 모양 400 · via web
5) provenance_history via · 옛 DB 업그레이드(records.revision 없음 → 1)
"""
import asyncio
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_record_edit). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "re-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "record-edit-test-secret"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from mcp.client import Client  # noqa: E402

import db  # noqa: E402
import facade  # noqa: E402
import main  # noqa: E402

MAIN = "re-main@example.com"
PUBLIC = "http://127.0.0.1:8800"
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
BODY = "도입 회의에서 입력 담당을 먼저 정했다. 도구 비교는 그다음이었다."
QUOTE = "입력 담당을 먼저 정했다"


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


async def preview(c, params):
    r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_edit", "params": params}})
    return val(r)


async def edit(c, params, bind=None):
    a = {"op": "record_edit", "params": params}
    if bind is not None:
        a["bind"] = bind
    return await c.call_tool("decide", a)


def hist(uid, rid):
    with db.tx() as c:
        return c.execute("SELECT action,prev_revision,change,via FROM record_history WHERE user_id=%s AND record_id=%s ORDER BY id",
                         (uid, rid)).fetchall()


def setup():
    uid = db.user_by_email(MAIN)["id"]
    db.display_name_set(uid, "수정 시험")
    return uid


def rec(uid, body=BODY, title="회의 메모"):
    return db.record_add(uid, title, body)["id"]


def cand(uid, rid, quote=QUOTE, text="입력 담당부터 정한다"):
    added, dropped = db.candidates_propose(uid, rid, None, [{"text": text, "quote": quote}], "ai")
    assert added and not dropped, dropped
    return added[0]


# ── 1) MCP record_edit ────────────────────────────────

async def test_mcp_edit(uid):
    rid = rec(uid)
    r0 = db.record_get(uid, rid)
    assert r0["revision"] == 1, r0
    p = {"record_id": rid, "expected_revision": 1, "old": "그다음이었다", "new": "그 뒤였다"}
    async with Client(main.mcp) as c:
        d = val(await c.call_tool("find", {"op": "record_edit"}))
        assert d["tier"] == "decide" and "decide_preview" in d["flow"][0] and "고치라고 말한 구절만" in d["rule"], d
        r = await edit(c, p)
        assert code(r) == "BIND-REQUIRED", r
        pv = await preview(c, p)
        assert pv["shown"] == {"기록": "회의 메모", "전": BODY, "후": BODY.replace("그다음이었다", "그 뒤였다")}, pv["shown"]
        assert db._edit_window("가" * 40 + "X" + "나" * 40, 40, "X", "Y") == ("…" + "가" * 30 + "X" + "나" * 30 + "…",
                                                                            "…" + "가" * 30 + "Y" + "나" * 30 + "…")
        assert pv["irreversible"] is False and pv["impact"]["deleted_candidates"] == 0
        out = val(await edit(c, p, pv["bind"]))
        assert out["revision"] == 2 and out["body"] == BODY.replace("그다음이었다", "그 뒤였다"), out
        assert (out["deleted_candidates"], out["moved_candidates"], out["via"]) == (0, 0, "facade"), out
        h = hist(uid, rid)
        assert h == [{"action": "edit", "prev_revision": 1, "via": "mcp",
                      "change": {"start": BODY.index("그다음이었다"), "old": "그다음이었다", "new": "그 뒤였다",
                                 "deleted_candidates": 0, "moved_candidates": 0}}], h
        # 같은 호출 다시 = 그 구절이 이제 없다(미리보기를 다시 만들다 같은 오류) · 다른 구절은 대상(revision·본문)이 바뀌어 STALE
        r = await edit(c, p, pv["bind"])
        assert code(r) == "EDIT-NOT-FOUND", r
        q = {"record_id": rid, "expected_revision": 2, "old": "도구 비교는", "new": "도구 견주기는"}
        pq = await preview(c, q)
        db.record_title_set(uid, rid, "제목 바뀜", 2)   # 그사이 revision +1
        q["expected_revision"] = 3
        r = await edit(c, q, pq["bind"])
        assert code(r) == "BIND-STALE", r
        # 0번 · 2번(겹침 포함) · revision 다름
        p2 = {"record_id": rid, "expected_revision": 3, "old": "없는 구절", "new": "x"}
        assert code(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_edit", "params": p2}})) == "EDIT-NOT-FOUND"
        rid2 = rec(uid, "아아아 하고 웃었다. 아아 그렇구나.")
        p3 = {"record_id": rid2, "expected_revision": 1, "old": "아아", "new": "오오"}
        assert code(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_edit", "params": p3}})) == "EDIT-AMBIGUOUS"
        expect("EDIT-AMBIGUOUS", db.record_edit, uid, rid2, 1, "아아", "오오")
        e = expect("EDIT-AMBIGUOUS", db.record_edit, uid, rec(uid, "aaa 끝"), 1, "aa", "b")   # 겹침도 두 번으로 센다
        assert "더 길게" in e.action
        expect("CONFLICT", db.record_edit, uid, rid, 2, "그 뒤였다", "그다음이었다")
        expect("ARG-INVALID", db.record_edit, uid, rid, 3, "", "x")
        expect("ARG-INVALID", db.record_edit, uid, rid, 3, "그 뒤였다", "그 뒤였다")
        expect("ARG-INVALID", db.record_edit, uid, rec(uid, "전부"), 1, "전부", "  ")   # 고친 뒤 빈 본문
        e = expect("PAYLOAD-LIMIT", db.record_edit, uid, rid, 3, "그 뒤였다", "가" * (db.LIMIT_BODY // 3 + 10))
        # 잠금 — 확정·남기지 않음 후보 / external / 휴지통
        for action in ("confirm", "exclude"):
            r3 = rec(uid)
            cid = cand(uid, r3)
            db.candidate_decide(uid, cid, action)
            e = expect("RECORD-LOCKED", db.record_edit, uid, r3, 1, "그다음이었다", "그 뒤였다")
            assert "새 기록" in e.action, e.action
            pp = {"record_id": r3, "expected_revision": 1, "old": "그다음이었다", "new": "그 뒤였다"}
            assert code(await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_edit", "params": pp}})) == "RECORD-LOCKED"
            assert db.record_title_set(uid, r3, "제목만 바꿈", 1)["revision"] == 2, "판단이 붙어도 제목은 된다"
        rx = rec(uid)
        db.record_provenance_set(uid, rx, "external", "verbatim", "남이 쓴 글이었다")
        expect("RECORD-LOCKED", db.record_edit, uid, rx, 1, "그다음이었다", "그 뒤였다")
        expect("RECORD-LOCKED", db.record_title_set, uid, rx, "x", 1)
        rt = rec(uid)
        db.trash_move(uid, "record", rt)
        expect("IN-TRASH", db.record_edit, uid, rt, 1, "그다음이었다", "그 뒤였다")
        expect("IN-TRASH", db.record_title_set, uid, rt, "x", 1)
        expect("RECORD-MISSING", db.record_edit, uid, "r_nope", 1, "a", "b")
        # 출처 판정·일일 한도 그대로 — 본문을 고쳐도 self·verbatim(적격) 유지, records 일일 한도 카운트 없음
        r4 = db.record_get(uid, rid)
        assert (r4["author_kind"], r4["text_process"]) == ("self", "verbatim")
    ok("MCP record_edit(BIND-REQUIRED·shown 전·후·STALE · 0번·2번(겹침)·CONFLICT·빈 본문·크기 · 잠금 확정/남기지 않음/external/휴지통 · 이력 via mcp · 적격 유지)")


# ── 2) 미결 후보 ───────────────────────────────────────

def cands_of(uid, rid):
    with db.tx() as c:
        return {r["id"]: r for r in c.execute("SELECT id,quote,quote_start,quote_end,revision FROM candidates WHERE user_id=%s AND record_id=%s",
                                              (uid, rid)).fetchall()}


def quotes_hold(uid, rid):
    body = db.record_get(uid, rid)["body"]
    for r in cands_of(uid, rid).values():
        assert body[r["quote_start"]:r["quote_end"]] == r["quote"], r


async def test_pending_candidates(uid):
    """메인 판정 c′ — 변경 구간과 겹치거나 닿는 미결 후보 삭제 · 앞 = 그대로 · 뒤 = delta 이동 · 이동 뒤 quote 단언 · 휴지통·복원 없음."""
    rid = rec(uid)
    c_before = cand(uid, rid, "도입 회의에서", "회의에서 정한다")
    c_hit = cand(uid, rid, QUOTE)
    c_after = cand(uid, rid, "도구 비교는 그다음이었다", "도구는 나중에 본다")
    old_after = cands_of(uid, rid)[c_after]
    p = {"record_id": rid, "expected_revision": 1, "old": "먼저", "new": "가장 먼저"}
    async with Client(main.mcp) as c:
        pv = await preview(c, p)
        assert pv["impact"]["deleted_candidates"] == 1 and pv["shown"]["지워질 판단 후보"] == "검토할 판단 1개가 지워져요(다시 뽑을 수 있어요)", pv
        assert not re.search(r"복원|168|quote_changed|휴지통", json.dumps(pv["shown"], ensure_ascii=False))
        out = val(await edit(c, p, pv["bind"]))
    assert (out["deleted_candidates"], out["moved_candidates"]) == (1, 1), out
    assert hist(uid, rid)[-1]["change"] == {"start": BODY.index("먼저"), "old": "먼저", "new": "가장 먼저", "deleted_candidates": 1, "moved_candidates": 1}
    now = cands_of(uid, rid)
    assert set(now) == {c_before, c_after}, now
    assert (now[c_after]["quote_start"], now[c_after]["quote_end"]) == (old_after["quote_start"] + 3, old_after["quote_end"] + 3)
    assert now[c_after]["revision"] == old_after["revision"], "옮기기는 문장·결정을 바꾸지 않는다(revision 그대로)"
    quotes_hold(uid, rid)
    expect("ARG-INVALID", db.candidate_get, uid, c_hit)
    assert "candidate" not in db.TRASH_KINDS
    cand(uid, rid, "입력 담당을 가장 먼저 정했다", "다시 뽑은 판단")   # 고친 본문에서 다시 뽑는다
    # 경계 접촉 = 겹침(앞 끝 = s · 뒤 시작 = e) · 줄어드는 delta
    r2 = rec(uid, "가나다라마바사아")
    k1, k2, k3 = cand(uid, r2, "가나", "가"), cand(uid, r2, "마바", "마"), cand(uid, r2, "사아", "사")
    out = db.record_edit(uid, r2, 1, "다라", "X")
    assert (out["deleted_candidates"], out["moved_candidates"]) == (2, 1) and set(cands_of(uid, r2)) == {k3}, out
    assert (cands_of(uid, r2)[k3]["quote_start"], cands_of(uid, r2)[k3]["quote_end"]) == (5, 7)
    quotes_hold(uid, r2)
    # 끼워 넣기(old 빈 구간 — 웹) 자리에 닿는 후보도 지운다
    r2b = rec(uid, "가나다라마")
    j1, j2 = cand(uid, r2b, "가나", "가"), cand(uid, r2b, "다라", "다")
    out = db.record_body_set(uid, r2b, 1, "가나!다라마")
    assert (out["deleted_candidates"], out["moved_candidates"]) == (2, 0) and cands_of(uid, r2b) == {}, out
    # UNIQUE 순간 충돌 없음 — 이웃 후보가 delta(±2)만큼 떨어져 있을 때 늘기·줄기 둘 다
    for new in ("변경점22", "변"):
        r3 = rec(uid, "변경점 ABCDEF끝")
        a1, a2, a3 = cand(uid, r3, "AB", "a"), cand(uid, r3, "CD", "c"), cand(uid, r3, "EF", "e")
        before = cands_of(uid, r3)
        out = db.record_edit(uid, r3, 1, "변경점", new)
        d = len(new) - 3
        after = cands_of(uid, r3)
        assert out["moved_candidates"] == 3 and all(after[x]["quote_start"] == before[x]["quote_start"] + d for x in (a1, a2, a3)), (new, after)
        quotes_hold(uid, r3)
    # 방어 — 옮긴 자리의 새 본문이 quote 와 다르면 그 후보를 지운다(저장값이 어긋난 경우를 직접 만들어 본다)
    r4 = rec(uid, "앞부분 가운데 뒷부분이다")
    g1 = cand(uid, r4, "뒷부분", "뒤")
    with db.tx() as cx:
        cx.execute("UPDATE candidates SET quote='뒷부눈' WHERE id=%s", (g1,))   # 같은 길이, 다른 글자
    out = db.record_edit(uid, r4, 1, "앞부분", "앞")
    assert (out["deleted_candidates"], out["moved_candidates"]) == (1, 0) and cands_of(uid, r4) == {}, out
    # 기준·항목 연결이 걸린 후보 — 지워질 자리면 수정 전체 RECORD-LOCKED(아무것도 안 바뀜) · 옮기기만 하는 자리면 통과(연결 그대로)
    hap = db.definition_propose(uid, None, 0, {"key": "edit_ev", "label": "일", "semantic_kind": "event", "fields": [
        {"key": "claims", "label": "판단", "value_type": "reference", "target_kind": "candidate", "multiple": True}]})
    hap = db.definition_apply(uid, hap["object_id"], hap["proposal_id"], 0)
    r5 = rec(uid)
    l_hit = cand(uid, r5, QUOTE)
    l_after = cand(uid, r5, "도구 비교는 그다음이었다", "도구는 나중에 본다")
    ev = db.item_propose(uid, hap["id"], hap["revision"], None, 0, None, "연결 사건", "", {},
                         [{"field_key": "claims", "target_kind": "candidate", "target_id": l_hit},
                          {"field_key": "claims", "target_kind": "candidate", "target_id": l_after}])
    db.item_decide(uid, ev["item_id"], 0, ev["proposal_id"], "apply")
    snap = cands_of(uid, r5)
    e = expect("RECORD-LOCKED", db.record_edit, uid, r5, 1, "먼저", "가장 먼저")
    assert "연결" in e.message and "새 기록" in e.action, (e.message, e.action)
    async with Client(main.mcp) as c:
        r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_edit", "params": {
            "record_id": r5, "expected_revision": 1, "old": "먼저", "new": "가장 먼저"}}})
        assert code(r) == "RECORD-LOCKED", r
    assert cands_of(uid, r5) == snap and db.record_get(uid, r5)["revision"] == 1, "거절은 아무것도 바꾸지 않는다"
    out = db.record_edit(uid, r5, 1, "도입 회의에서", "첫 도입 회의에서")   # 두 후보 다 뒤쪽 — 옮기기만
    assert (out["deleted_candidates"], out["moved_candidates"]) == (0, 2), out
    assert cands_of(uid, r5)[l_hit]["quote_start"] == snap[l_hit]["quote_start"] + 2
    quotes_hold(uid, r5)
    with db.tx() as cx:
        n = cx.execute("SELECT count(*) AS n FROM item_links WHERE user_id=%s AND target_candidate_id = ANY(%s)",
                       (uid, [l_hit, l_after])).fetchone()["n"]
    assert n == 2, "옮긴 후보의 연결은 그대로"
    ok("미결 후보 c′(겹침 삭제·경계 접촉·끼워 넣기 · 앞 그대로 · 뒤 delta 이동(±)·UNIQUE 순간 충돌 없음 · 이동 뒤 quote 단언·어긋나면 삭제 · shown 「지워져요」 · 휴지통 없음 · 연결 걸린 지울 후보 = RECORD-LOCKED, 옮길 후보는 통과)")


# ── 3) record_title_set ────────────────────────────────

async def test_title(uid):
    rid = rec(uid)
    async with Client(main.mcp) as c:
        d = val(await c.call_tool("find", {"op": "record_title_set"}))
        assert d["tier"] == "write" and "제목을 바꿔 달라고 말할 때만" in d["rule"]
        out = val(await c.call_tool("write", {"op": "record_title_set", "params": {"record_id": rid, "title": "  새 제목 ", "expected_revision": 1}}))
        assert out["title"] == "새 제목" and out["revision"] == 2 and out["body"] == BODY, out
        same = val(await c.call_tool("write", {"op": "record_title_set", "params": {"record_id": rid, "title": "새 제목", "expected_revision": 2}}))
        assert same["revision"] == 2, "같은 제목 = no-op"
        r = await c.call_tool("write", {"op": "record_title_set", "params": {"record_id": rid, "title": "또", "expected_revision": 1}})
        assert code(r) == "CONFLICT"
        r = await c.call_tool("write", {"op": "record_title_set", "params": {"record_id": rid, "title": "   ", "expected_revision": 2}})
        assert code(r) == "ARG-INVALID"
    assert hist(uid, rid) == [{"action": "title", "prev_revision": 1, "via": "mcp", "change": {"old": "회의 메모", "new": "새 제목"}}]
    ok("record_title_set(W · strip · revision +1 · 같은 제목 no-op · CONFLICT · 빈 제목 · 이력 title via mcp)")


# ── 4) 웹 ──────────────────────────────────────────────

async def test_web(uid):
    site = main.site
    real = site.dev, site.dev_user
    origin = {"origin": PUBLIC}
    rid = rec(uid)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            site.dev, site.dev_user = False, ""
            assert (await h.post(f"/api/records/{rid}/body", json={"expected_revision": 1, "body": "x"}, headers=origin)).status_code == 401
            assert (await h.post(f"/api/records/{rid}/title", json={"expected_revision": 1, "title": "x"}, headers=origin)).status_code == 401
            assert (await h.post("/api/item/edit", json={}, headers=origin)).status_code == 401
            site.dev, site.dev_user = True, MAIN
            new = BODY.replace("입력 담당을 먼저", "입력 담당을 가장 먼저")
            r = await h.post(f"/api/records/{rid}/body", json={"expected_revision": 1, "body": new}, headers={"origin": "https://evil.example"})
            assert r.status_code == 403
            for bad in ({"expected_revision": "1", "body": new}, {"body": new}, {"expected_revision": 1, "body": 3}):
                r = await h.post(f"/api/records/{rid}/body", json=bad, headers=origin)
                assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", (bad, r.text)
            r = await h.post(f"/api/records/{rid}/body", json={"expected_revision": 1, "body": new}, headers=origin)
            assert r.status_code == 200 and r.json()["body"] == new and r.json()["revision"] == 2, r.text
            assert r.headers.get("cache-control") == "no-store"
            ch = hist(uid, rid)[-1]
            assert ch["via"] == "web" and ch["change"]["old"] == "" and ch["change"]["new"] == "가장 ", ch   # 공통 앞·뒤를 뺀 한 구간
            r = await h.post(f"/api/records/{rid}/body", json={"expected_revision": 1, "body": BODY}, headers=origin)
            assert r.status_code == 400 and r.json()["code"] == "CONFLICT"
            r = await h.post(f"/api/records/{rid}/body", json={"expected_revision": 2, "body": new}, headers=origin)
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", "바뀐 곳 없음"
            # 반복 글자 안의 수정도 위치로 정한다(웹은 구절 유일성 조건이 없다)
            rr = rec(uid, "아아아 아아아")
            r = await h.post(f"/api/records/{rr}/body", json={"expected_revision": 1, "body": "아아아 아오아"}, headers=origin)
            assert r.status_code == 200 and r.json()["body"] == "아아아 아오아", r.text
            r = await h.post(f"/api/records/{rid}/title", json={"expected_revision": 2, "title": "웹 제목"}, headers=origin)
            assert r.status_code == 200 and r.json()["title"] == "웹 제목" and r.json()["revision"] == 3, r.text
            assert hist(uid, rid)[-1]["via"] == "web"
            # 잠금은 웹도 같다
            r3 = rec(uid)
            db.candidate_decide(uid, cand(uid, r3), "confirm")
            r = await h.post(f"/api/records/{r3}/body", json={"expected_revision": 1, "body": BODY + " 덧붙임"}, headers=origin)
            assert r.status_code == 400 and r.json()["code"] == "RECORD-LOCKED", r.text
            # 항목 인라인 편집 = propose+apply 한 트랜잭션 · 확정 기준은 확정 유지 · 이력 한 줄 · code 불변
            od = db.definition_propose(uid, None, 0, {"key": "edit_pr", "label": "교훈", "semantic_kind": "principle", "policy": {}, "fields": []})
            db.definition_apply(uid, od["object_id"], od["proposal_id"], 0)
            ip = db.item_propose(uid, od["object_id"], 1, None, 0, "P-1", "입력 담당 먼저", "도구보다 사람을 먼저.", {}, [])
            db.item_decide(uid, ip["item_id"], 0, ip["proposal_id"], "apply")
            it = db.item_decide(uid, ip["item_id"], 1, None, "confirm")
            assert it["decision"] == "confirmed" and it["revision"] == 2
            r = await h.post("/api/item/edit", json={"item_id": ip["item_id"], "expected_revision": 2, "title": "입력 담당을 먼저",
                                                     "body": "도구보다 사람을 먼저 정한다."}, headers=origin)
            assert r.status_code == 200, r.text
            j = r.json()
            assert (j["title"], j["body"], j["decision"], j["revision"], j["code"]) == ("입력 담당을 먼저", "도구보다 사람을 먼저 정한다.", "confirmed", 3, "P-1"), j
            assert j["proposal"] is None
            with db.tx() as c:
                hs = c.execute("SELECT action,prev_revision FROM item_history WHERE user_id=%s AND item_id=%s ORDER BY id",
                               (uid, ip["item_id"])).fetchall()
            assert [x["action"] for x in hs] == ["apply", "confirm", "apply"] and hs[-1]["prev_revision"] == 2, hs
            r = await h.post("/api/item/edit", json={"item_id": ip["item_id"], "expected_revision": 2, "title": "x", "body": ""}, headers=origin)
            assert r.status_code == 400 and r.json()["code"] == "CONFLICT", r.text
            r = await h.post("/api/item/edit", json={"item_id": ip["item_id"], "expected_revision": 3, "title": " ", "body": ""}, headers=origin)
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", r.text
            assert db.item_get(uid, ip["item_id"])["revision"] == 3, "거절은 쓰지 않는다(제안도 남지 않는다)"
            assert db.item_get(uid, ip["item_id"])["proposal"] is None
    finally:
        site.dev, site.dev_user = real
    ok("웹(본문 = 공통 앞·뒤 뺀 한 구간·위치 기준 · 제목 · 401·Origin 403·모양 400·CONFLICT·바뀐 곳 없음·잠금 · 항목 편집 = 한 트랜잭션·확정 유지·code 불변·이력 한 줄·거절 무흔적)")


# ── 5) 출처 via · 옛 DB 업그레이드 ─────────────────────

async def test_provenance_and_upgrade(uid):
    rid = rec(uid)
    async with Client(main.mcp) as c:
        r = await c.call_tool("record_provenance_set", {"record_id": rid, "author_kind": "self", "text_process": "structured",
                                                        "reason": "정리한 글이었다"})
        assert not r.is_error, r.content[0].text
    with db.tx() as c:
        ph = c.execute("SELECT provenance_history FROM records WHERE id=%s", (rid,)).fetchone()["provenance_history"]
    assert ph[-1]["via"] == "mcp", ph
    # 옛 DB — revision 열이 없으면 init_schema 가 더한다(옛 행 1)
    with db.tx() as c:
        c.execute("ALTER TABLE records DROP CONSTRAINT IF EXISTS ck_records_revision")
        c.execute("ALTER TABLE records DROP COLUMN revision")
    db.init_schema()
    with db.tx() as c:
        assert {r["revision"] for r in c.execute("SELECT revision FROM records WHERE user_id=%s", (uid,)).fetchall()} == {1}
        assert c.execute("SELECT 1 FROM pg_constraint WHERE conname='ck_records_revision'").fetchone()
    db.init_schema()   # 멱등
    ok("출처 정정 이력 via · 옛 DB 업그레이드(records.revision 열·CHECK, 옛 행 1 · 멱등)")


async def run():
    db.init_schema()
    cleanup()
    try:
        db.user_by_email(MAIN)
        uid = setup()
        await test_mcp_edit(uid)
        await test_pending_candidates(uid)
        await test_title(uid)
        await test_web(uid)
        await test_provenance_and_upgrade(uid)
    finally:
        cleanup()
        db.close()
    print("OK — 수기 수정 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
