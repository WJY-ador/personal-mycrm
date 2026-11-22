"""루틴판 써 보고 고칠 것 시험(2026-11-22 구현계획 2절 축 한 장 내가 고친 판, 4-3 인박스 요약).

실행: DATABASE_URL=postgresql://localhost/crm_test_routine_feedback python3 server/test_routine_feedback.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 자료는 가짜 축 코드, 가짜 URL, 가짜 문장뿐이다. 1절(목록 window, verdict, 루틴판 in.by_axis)은 test_routine_board.py 3b.

1. 인박스 요약 받기(inbox-digest/1) — 받는 즉시 기록(unknown·generated·ai, 출처 인박스 요약) · post_urls → 수집 글 항목 id(없는 URL 은 버리고 수)
   · 새 판이 옛 요약 기록을 영구 삭제(같은 원본 옛 개정, 다른 원본의 현재 판은 남김 — 그 원본이 막히지 않게) · 계약 거절
2. 읽기(imports.inbox_digest = 웹 GET /api/collected/digest = MCP inbox_digest_get) — pending_n, new_since(요약 밖·요약 뒤), by_axis,
   item_ids 는 살아 있는 항목만 · 요약 없음 · 견본 digest.sample.json 대조
3. 요약 기록 제외 — 내 글 목록, heatmap, 종류별 건수, 답변 재료(비적격 셈 포함), 후보, 꺼내기
4. 정책 이관 v4 — 모든 장치에 inbox-digest/1(다른 변환 그대로, 가진 장치 그대로, 판 +1, 한 번) · 새 장치 기본 정책
5. 축 한 장 내가 고친 판(imports.axis_page_save = 웹 POST /api/axes/<id>/page = MCP axis_page_save) — 받은 그대로 저장 · 낙관적 잠금 STALE
   · 옛 내 판은 휴지통 · 축 보기 page.mine, ai_newer, body, ai_body · AI 초안 없는 축 · 비적격(후보, 답변, 꺼내기, 출처 정정 잠금) · 격리
   · 견본 axes.sample.json 대조 · MCP write op(facade 전용)
"""
import asyncio
import json
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_routine_feedback). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ci-feedback-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_IMPORTS_ENABLED"] = "1"
os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
os.environ["CRM_TRASH_ENABLED"] = "1"   # 옛 내 판 되살리기
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from mcp.client import Client  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

import answer  # noqa: E402
import db  # noqa: E402
import export_forms  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
from test_sample_shape import cmp  # noqa: E402

MAIN, OTHER = "ci-feedback-main@example.com", "ci-feedback-other@example.com"
EMAILS = (MAIN, OTHER)
FIELDS = [
    {"key": "channel", "label": "채널", "value_type": "select", "required": True, "options": list(imports.COLLECTED_CHANNELS)},
    {"key": "collected_on", "label": "수집일", "value_type": "date", "required": True},
    {"key": "post_url", "label": "원 URL", "value_type": "text"},
    {"key": "ai_grade", "label": "AI 판별", "value_type": "select", "options": list(imports.COLLECTED_GRADES)},
    {"key": "ai_summary", "label": "AI 요약", "value_type": "text"}]
WORD = "가짜요약낱말"   # 요약 본문과 내 글에 같이 넣는 찾기 낱말
MINE_WORD = "가짜내판낱말"
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")


def ok(msg):
    print("OK", msg, flush=True)


def url(n):
    return f"https://example.com/fake/post-{n}"


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


def axis_item(uid, oid, code, title):
    p = db.item_propose(uid, oid, 1, None, 0, code, title, "", {}, [])
    return db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]


def setup_user(uid):
    """축 오브젝트(가짜 축 A, B-1) + 수집 글 오브젝트 + 기본 정책 장치. 반환 (토큰, 장치 id, {코드: 축 id})."""
    db.display_name_set(uid, "합성")
    with db.tx() as c:
        o = c.execute("SELECT id FROM object_defs WHERE user_id=%s AND key='axes'", (uid,)).fetchone()
    if not o:
        q0 = db.definition_propose(uid, None, 0, {"key": "axes", "label": "축", "semantic_kind": "collection", "fields": []})
        db.definition_apply(uid, q0["object_id"], q0["proposal_id"], 0)
        o = {"id": q0["object_id"]}
    with db.tx() as c:
        rev = c.execute("SELECT revision FROM object_defs WHERE user_id=%s AND id=%s", (uid, o["id"])).fetchone()["revision"]
    ax = {}
    for code, title in (("A", "가짜 축 하나"), ("B-1", "가짜 축 둘")):
        p = db.item_propose(uid, o["id"], rev, None, 0, code, title, "", {}, [])
        ax[code] = db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]
    fields = FIELDS + [{"key": "axes", "label": "축", "value_type": "reference", "target_kind": "item", "target_object_id": o["id"],
                        "multiple": True}]
    q = db.definition_propose(uid, None, 0, {"key": imports.COLLECTED_OBJECT_KEY, "label": "수집 글", "semantic_kind": "collection",
                                             "fields": fields})
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    c1 = imports.device_connect(uid, "합성 PC")
    return c1["token"], c1["device"]["id"], ax


DIGEST = {"themes": [{"name": "가짜 주제 하나", "line": "가짜 글 둘이 같은 흐름을 말해요.", "post_urls": [url(1), url(2), url(99)]},
                     {"name": "가짜 주제 둘", "line": "가짜 글 하나가 반대쪽이에요.", "post_urls": [url(3)]}],
          "input_n": 4, "made_at": "2026-11-22T09:00:00+09:00"}


class Dev:
    """장치 한 대 — 원본마다 개정 사슬을 기억한다."""
    def __init__(self, token, dev_id):
        self.token, self.id, self.chain = token, dev_id, {}
        self.pr = imports.device_self("Bearer " + token)["policy_revision"]

    def body(self, key, kind="collected_post", **kw):
        o, prev, raw = self.chain.get(key, ("o_" + secrets.token_hex(16), None, secrets.token_hex(24)))
        b = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": self.id, "original_id": o,
             "revision": "v_" + secrets.token_hex(16), "previous_revision": prev, "kind": kind, "execution": "unattended",
             "policy_revision": self.pr}
        if kind == "collected_post":
            b.update({"transform_version": "collected-post/1", "raw_id": raw, "channel": "linkedin", "collected_on": "2026-11-22",
                      "title": f"합성 {key} 첫 줄", "state": "pending"})
        elif kind == "digest":
            b.update({"kind": "self_text", "transform_version": "inbox-digest/1",
                      "body": f"가짜 주제 하나: 가짜 글 둘이 같은 흐름 {WORD}\n가짜 주제 둘: 반대쪽", "digest": DIGEST})
        else:
            b.update({"kind": "self_text", "transform_version": "axis-page/1", "title": f"가짜 한 장 {key}", "body": "가짜 AI 본문",
                      "source_created_at": "2026-11-18T14:00:00+09:00", "axis_code": "A"})
        b.update(kw)
        for k in [k for k, v in b.items() if v is ...]:
            del b[k]
        return b

    async def send(self, key, kind="collected_post", status=(200, 201), **kw):
        b = self.body(key, kind, **kw)
        hd = {"content-type": "application/json", "authorization": "Bearer " + self.token,
              "idempotency-key": imports.idempotency_key(b["source_instance_id"], b["original_id"], b["revision"])}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            r = await h.post("/api/imports", content=json.dumps(b, ensure_ascii=False).encode("utf-8"), headers=hd)
        assert r.status_code in ((status,) if isinstance(status, int) else status), (r.status_code, r.text)
        if r.status_code in (200, 201):
            self.chain[key] = (b["original_id"], b["revision"], b.get("raw_id") or secrets.token_hex(24))
        return r.json()


async def web(path, user=MAIN, body=None, origin=PUBLIC):
    site = main.site
    real = site.dev, site.dev_user
    try:
        site.dev, site.dev_user = True, user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            if body is None:
                return await h.get(path)
            return await h.post(path, json=body, headers={"origin": origin})
    finally:
        site.dev, site.dev_user = real


def mcp_val(res):
    v = res.structured_content
    v = v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v
    return json.loads(res.content[0].text) if v is None else v


def rec(uid, rid):
    with db.tx() as c:
        return c.execute("SELECT id, title, body, source, author_kind, text_process, generation_kind, generation_meta, trashed_at, deleted_at "
                         "FROM records WHERE user_id=%s AND id=%s", (uid, rid)).fetchone()


def digest_records(uid):
    with db.tx() as c:
        return [r["id"] for r in c.execute("SELECT id FROM records WHERE user_id=%s AND generation_meta->>'transform_version'=%s",
                                           (uid, imports.INBOX_DIGEST)).fetchall()]


async def run():
    A, B = db.user_by_email(MAIN)["id"], db.user_by_email(OTHER)["id"]
    tok, did, ax = setup_user(A)
    btok, bdid, bax = setup_user(B)
    d = Dev(tok, did)

    # ── 1. 인박스 요약 받기 ──
    assert "inbox-digest/1" in imports.DEFAULT_POLICY["transform_versions"], "새 장치 기본 정책"
    it = {}
    for n, grade, codes in ((1, "signal", ["A"]), (2, "news", ["A", "B-1"]), (3, "signal", ["B-1"]), (4, "noise", [])):
        r = await d.send(f"p{n}", post_url=url(n), ai={"grade": grade, "summary": f"가짜 AI 요약 {n}"}, axis_codes=codes or ...)
        assert r["state"] == "applied", r
        it[n] = r["target_id"]
    before_kinds = db.me_stats(A)["kinds"]["records"]
    before_heat = sum(c["records"] for c in db.me_stats(A)["heatmap"]["cells"])
    before_list = [x["id"] for x in db.records(A)]
    r = await d.send("dg", kind="digest")
    assert r["state"] == "applied" and r["target_kind"] == "record", r
    g1 = r["target_id"]
    x = rec(A, g1)
    assert (x["author_kind"], x["text_process"], x["generation_kind"], x["source"], x["title"]) == \
        ("unknown", "generated", "ai", "인박스 요약", "인박스 요약"), x
    gm = x["generation_meta"]
    assert gm["transform_version"] == "inbox-digest/1" and gm["dropped_urls"] == 1, gm
    assert gm["digest"] == {"themes": [{"name": "가짜 주제 하나", "line": "가짜 글 둘이 같은 흐름을 말해요.", "item_ids": [it[1], it[2]]},
                                       {"name": "가짜 주제 둘", "line": "가짜 글 하나가 반대쪽이에요.", "item_ids": [it[3]]}],
                            "input_n": 4, "made_at": "2026-11-22T09:00:00+09:00"}, gm
    assert url(1) not in json.dumps(gm), "URL 은 저장하지 않는다(항목 id 로)"
    first_entry = r["import_id"]
    # 같은 원본 새 개정 = 옛 요약 기록 영구 삭제, 접수 행은 deleted 표식 · 다른 원본도 사용자당 하나
    r = await d.send("dg", kind="digest", digest={**DIGEST, "input_n": 3})
    g2 = r["target_id"]
    assert r["state"] == "applied" and g2 != g1 and digest_records(A) == [g2] and rec(A, g1) is None, (r, digest_records(A))
    with db.tx() as c:
        e = c.execute("SELECT state, target_record_id, deleted_target_id FROM import_entries WHERE user_id=%s AND id=%s",
                      (A, first_entry)).fetchone()
    assert (e["state"], e["target_record_id"], e["deleted_target_id"]) == ("deleted", None, g1), e
    r = await d.send("dg", kind="digest", digest={**DIGEST, "input_n": 3})   # 같은 내용 새 개정 = noop(현재 판 그대로)
    assert r["state"] == "noop" and r["target_id"] == g2, r
    r = await d.send("dg2", kind="digest")
    g3 = r["target_id"]
    assert sorted(digest_records(A)) == sorted([g2, g3]), "다른 원본(다른 장치)의 현재 판은 남긴다 — 지우면 그 원본이 purged 로 막힌다"
    r = await d.send("dg", kind="digest", digest={**DIGEST, "input_n": 2})
    assert r["state"] == "applied", ("다른 원본이 대신한 뒤에도 그 원본은 계속 받는다", r)
    g4 = r["target_id"]
    assert sorted(digest_records(A)) == sorted([g3, g4]) and rec(A, g2) is None, digest_records(A)
    r = await d.send("dg2", kind="digest", digest={**DIGEST, "input_n": 1})
    g3 = r["target_id"]
    assert r["state"] == "applied" and sorted(digest_records(A)) == sorted([g3, g4]), digest_records(A)
    assert imports.inbox_digest(A)["digest"]["input_n"] == 1, "읽기는 최신 하나"
    # 계약
    bad_cases = (
        ({"digest": ...}, "digest: required"),
        ({"digest": {**DIGEST, "extra": 1}}, "digest.extra: unknown_field"),
        ({"digest": {**DIGEST, "themes": []}}, "digest.themes: list_1_to_7"),
        ({"digest": {**DIGEST, "themes": [DIGEST["themes"][1]] * 8}}, "digest.themes: list_1_to_7"),
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "name": "가" * 21}]}}, "digest.themes[0].name: too_long"),
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "line": "보기 https://example.com 링크"}]}},
         "digest.themes[0].line: url_not_allowed"),
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "post_urls": ["http://example.com/x"]}]}},
         "digest.themes[0].post_urls[0]: https_required"),
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "post_urls": [url(1), url(1)]}]}},
         "digest.themes[0].post_urls[1]: duplicate"),
        ({"digest": {**DIGEST, "themes": [DIGEST["themes"][0], {**DIGEST["themes"][1], "post_urls": [url(3), url(2)]}]}},
         "digest.themes[1].post_urls[1]: duplicate"),   # 주제 사이 중복(한 글은 한 주제에만)
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "post_urls": ["https://example.com/" + "a" * 281]}]}},
         "digest.themes[0].post_urls[0]: too_long"),
        ({"digest": {**DIGEST, "themes": [{**DIGEST["themes"][0], "post_urls": [url(i) for i in range(31)]},
                                          {**DIGEST["themes"][1], "post_urls": [url(i) for i in range(100, 131)]}]}},
         "digest.themes: post_urls_max_60"),
        ({"digest": {**DIGEST, "input_n": 61}}, "digest.input_n: int_0_to_60"),
        ({"digest": {**DIGEST, "made_at": "2026-11-22T09:00:00"}}, "digest.made_at: timestamp_with_offset_required"),
        ({"axis_code": "A"}, "axis_code: unknown_field"),
        ({"body": f"보기 {url(1)}"}, "body: url_not_allowed"),
    )
    for kw, rule in bad_cases:
        r = await d.send("bad", kind="digest", status=400, **kw)
        assert r["code"] == "CONTRACT-INVALID" and rule in r["msg"], (rule, r)
    r = await d.send("bad", kind="digest", transform_version="self-text/1", status=400)
    assert "digest: unknown_field" in r["msg"], r
    r = await d.send("bad", kind="axis", digest=DIGEST, status=400)
    assert "digest: unknown_field" in r["msg"], r
    base = d.body("x", kind="digest")
    assert imports.projection(base)["digest"] == DIGEST and "digest" not in imports.projection(d.body("x", kind="axis"))
    ok("1 인박스 요약 받기(즉시 기록 unknown·generated·ai·출처, URL → 항목 id, 없는 URL 수, 새 판이 옛 기록 영구 삭제, noop, 다른 원본, 계약 거절)")

    # ── 2. 읽기 ──
    dg = imports.inbox_digest(A)
    assert dg["digest"]["themes"][0]["item_ids"] == [it[1], it[2]] and dg["digest"]["input_n"] == 1, dg
    assert dg["pending_n"] == 4 and dg["new_since"] == 0, dg   # p4 는 요약 밖이지만 요약보다 먼저 들어왔다
    assert dg["by_axis"] == [{"code": "A", "title": "가짜 축 하나", "item_id": ax["A"], "pending": 2, "signal": 1},
                             {"code": "B-1", "title": "가짜 축 둘", "item_id": ax["B-1"], "pending": 2, "signal": 1}], dg["by_axis"]
    r = await d.send("p5", post_url=url(5), ai={"grade": "signal", "summary": "가짜"}, axis_codes=["B-1"])
    imports.collected_decide(A, it[2], "kept", None, via="web")
    imports.collected_decide(A, it[4], "dropped", None, via="web")
    with db.tx() as c:
        c.execute("UPDATE items SET trashed_at=now(), purge_at=now() + interval '7 days', last_trashed_at=now() WHERE user_id=%s AND id=%s",
                  (A, it[3]))
    dg = imports.inbox_digest(A)
    # 대기 = p1, p5 · 새로 = p5(요약 밖, 요약 뒤) · 보관한 p2 는 item_ids 에 남고 휴지통 p3 은 빠진다
    assert dg["pending_n"] == 2 and dg["new_since"] == 1, dg
    assert dg["digest"]["themes"][0]["item_ids"] == [it[1], it[2]] and dg["digest"]["themes"][1]["item_ids"] == [], dg["digest"]
    assert dg["by_axis"] == [{"code": "A", "title": "가짜 축 하나", "item_id": ax["A"], "pending": 1, "signal": 1},
                             {"code": "B-1", "title": "가짜 축 둘", "item_id": ax["B-1"], "pending": 1, "signal": 1}], dg["by_axis"]
    empty = imports.inbox_digest(B)
    assert empty == {"digest": None, "pending_n": 0, "new_since": 0, "by_axis": []}, empty
    await Dev(btok, bdid).send("bp1", post_url=url(1))
    eb = imports.inbox_digest(B)
    assert eb["digest"] is None and eb["pending_n"] == eb["new_since"] == 1, "요약이 없으면 대기 전부가 새것"
    # 웹 = 같은 함수 · 견본
    w = await web("/api/collected/digest")
    assert w.status_code == 200 and w.json() == json.loads(json.dumps(imports.inbox_digest(A))), w.text[:300]
    wb = await web("/api/collected/digest", user=OTHER)
    sample = json.loads((HERE / "ui" / "src" / "features" / "today" / "digest.sample.json").read_text(encoding="utf-8"))
    bad = cmp(sample["with"], w.json(), "with", exact=True) + cmp(sample["empty"], wb.json(), "empty", exact=True)
    assert not bad, (bad, "digest.sample.json 과 화면 타입을 같이 고친다")
    ok("2 읽기(pending_n, new_since 요약 밖·요약 뒤, by_axis 대기·신호, item_ids 살아 있는 항목, 요약 없음 = 전부 새것, 웹 같은 함수, 견본 대조)")

    # ── 3. 요약 기록 제외 ──
    assert db.me_stats(A)["kinds"]["records"] == before_kinds and \
        sum(c["records"] for c in db.me_stats(A)["heatmap"]["cells"]) == before_heat, "종류별 건수, heatmap 에 세지 않는다"
    assert [x["id"] for x in db.records(A)] == before_list, "내 글 목록에 없다"
    mine = db.record_add(A, "합성 내 글", f"내가 쓴 {WORD} 문장")["id"]
    out = answer.assemble(A, question=f"{WORD} 는?", terms=[WORD])
    blob = json.dumps(out, ensure_ascii=False)
    assert mine in blob and g3 not in blob and "가짜 주제" not in blob, out
    assert "내 원문이 아니라서" not in blob, "비적격 셈(부족한 곳)에도 넣지 않는다"
    acc, rej = db.candidates_propose(A, g3, "", [{"text": "가짜 판단", "quote": "가짜 주제 하나"}], "ai")
    assert acc == [] and rej and rej[0]["why"] == db.INELIGIBLE_WHY, (acc, rej)
    ex = json.dumps(export_forms.assemble(A, "period_report", {"kind": "period", "period": "all"}), ensure_ascii=False)
    assert g3 not in ex and "가짜 주제" not in ex
    ok("3 요약 기록 제외(내 글 목록, heatmap, 종류별 건수, 답변 근거와 비적격 셈, 후보 거절, 꺼내기)")

    # ── 4. 정책 이관 v4 ──
    no_dg = [t for t in imports.TRANSFORMS if t != "inbox-digest/1"]
    with db.tx() as c:
        rev = lambda u, dv: c.execute("SELECT policy, policy_revision FROM import_streams WHERE user_id=%s AND id=%s",   # noqa: E731
                                      (u, dv)).fetchone()
        c.execute("UPDATE import_streams SET policy=%s WHERE user_id=%s AND id=%s",
                  (Jsonb({"actions": ["like"], "transform_versions": ["collected-post/1"], "axes": []}), A, did))
        c.execute("UPDATE import_streams SET policy=%s WHERE user_id=%s AND id=%s",
                  (Jsonb({"actions": list(imports.ACTIONS), "transform_versions": no_dg + ["inbox-digest/1"], "axes": []}), B, bdid))
        a0, b0 = rev(A, did), rev(B, bdid)
        c.execute("DELETE FROM schema_marks WHERE key=%s", (imports.POLICY_ALL_V4_MARK,))
        n = imports.migrate_device_policy(c)
        a1, b1 = rev(A, did), rev(B, bdid)
        assert n >= 1 and a1["policy"]["transform_versions"] == ["collected-post/1", "inbox-digest/1"], (n, a1)
        assert a1["policy_revision"] == a0["policy_revision"] + 1 and a1["policy"]["actions"] == ["like"], a1
        assert b1 == b0, "이미 가진 장치는 판도 그대로"
        assert imports.migrate_device_policy(c) == 0, "v4 표식 한 번"
    d.pr = imports.device_self("Bearer " + tok)["policy_revision"]
    ok("4 정책 이관 v4(모든 장치에 inbox-digest/1 만 더함, 줄인 정책도, 판 +1, 가진 장치 그대로, 한 번) · 새 장치 기본 정책")

    # ── 5. 축 한 장 내가 고친 판 ──
    with db.tx() as c:   # 4 에서 줄인 정책을 기본으로 되돌린다(축 한 장 받기)
        c.execute("UPDATE import_streams SET policy=%s, policy_revision=policy_revision+1 WHERE user_id=%s AND id=%s",
                  (Jsonb(imports.DEFAULT_POLICY), A, did))
    d.pr = imports.device_self("Bearer " + tok)["policy_revision"]
    r = await d.send("ax-A", kind="axis", body=f"# 가짜 AI 한 장\n가짜 AI 첫 판 {MINE_WORD}")
    ai1 = r["target_id"]
    one = lambda: imports.axis_overview(A, ax["A"])["axes"][0]["page"]   # noqa: E731
    p0 = one()
    assert p0["record_id"] == ai1 and p0["mine"] is None and p0["ai_newer"] is False and p0["body"] == p0["ai_body"], p0
    assert "body" not in imports.axis_overview(A)["axes"][0]["page"] and "ai_body" not in imports.axis_overview(A)["axes"][0]["page"]
    md = f"# 내가 고친 한 장\n\n  가짜 내 문단 {MINE_WORD}  \n\n## 사례로 다시 보기\n"   # 앞뒤 공백까지 그대로
    s1 = imports.axis_page_save(A, ax["A"], md, None, via="web")
    pg = s1["axis"]["page"]
    m1 = pg["mine"]["record_id"]
    assert pg["body"] == md and pg["ai_body"] == p0["ai_body"] and pg["record_id"] == ai1 and pg["ai"] is True and pg["ai_newer"] is False, pg
    x = rec(A, m1)
    assert (x["author_kind"], x["text_process"], x["generation_kind"], x["source"]) == ("unknown", "generated", "mixed", "내가 고친 판"), x
    assert x["generation_meta"][imports.AXIS_MINE_KEY] == ax["A"] and x["title"] == "A. 가짜 축 하나 — 내가 고친 판", x
    # 낙관적 잠금 — 첫 저장 뒤 null, 틀린 값 = STALE(아무것도 안 바뀜)
    expect("STALE", imports.axis_page_save, A, ax["A"], "다른 판", None)
    expect("STALE", imports.axis_page_save, A, ax["A"], "다른 판", "2026-01-01T00:00:00+00:00")
    assert one()["mine"]["record_id"] == m1
    s2 = imports.axis_page_save(A, ax["A"], md + "더함\n", pg["mine"]["updated_at"], via="web")
    m2 = s2["axis"]["page"]["mine"]["record_id"]
    assert m2 != m1 and rec(A, m1)["trashed_at"] is not None and rec(A, m2)["trashed_at"] is None, "옛 내 판은 휴지통"
    assert db.trash_restore(A, "record", m1)["restored"], "복원 기한 안 되살릴 수 있다"
    assert one()["mine"]["record_id"] == m2, "되살린 옛 판보다 최신 내 판"
    # 새 AI 초안이 늦게 오면 ai_newer · 본문은 내 판 그대로
    r = await d.send("ax-A", kind="axis", body="# 가짜 AI 둘째 판")
    p2 = one()
    assert p2["ai_newer"] is True and p2["record_id"] == r["target_id"] and p2["body"] == md + "더함\n" and p2["ai_body"] == "# 가짜 AI 둘째 판", p2
    assert imports.axis_overview(A)["axes"][0]["page"]["ai_newer"] is True
    # AI 초안 없는 축 — page 는 내 판(ai false, 내 판 문구)
    sb = imports.axis_page_save(A, ax["B-1"], "가짜 B 내 판", "", via="web")["axis"]["page"]
    assert sb["ai"] is False and sb["record_id"] == sb["mine"]["record_id"] and sb["notice"] == imports.AXIS_MINE_NOTICE, sb
    assert sb["ai_body"] is None and sb["body"] == "가짜 B 내 판" and sb["ai_newer"] is False, sb
    # 비적격 — 후보, 답변, 꺼내기, 출처 정정 잠금
    acc, rej = db.candidates_propose(A, m2, "", [{"text": "가짜 판단", "quote": "가짜 내 문단"}], "ai")
    assert acc == [] and rej[0]["why"] == db.INELIGIBLE_WHY, (acc, rej)
    blob = json.dumps(answer.assemble(A, question=f"{MINE_WORD} 는?", terms=[MINE_WORD]), ensure_ascii=False)
    assert m2 not in blob, "답변 근거 아님"
    assert m2 not in json.dumps(export_forms.assemble(A, "period_report", {"kind": "period", "period": "all"}), ensure_ascii=False)
    expect("PROVENANCE-AI-LOCKED", db.record_provenance_set, A, m2, "self", "verbatim", "가짜 사유")
    # 잘못된 값 · 격리
    expect("ARG-INVALID", imports.axis_page_save, A, ax["A"], "   ", None)
    expect("ARG-INVALID", imports.axis_page_save, A, ax["A"], "가" * (imports.BODY_MAX_CP + 1), None)
    expect("ARG-INVALID", imports.axis_page_save, A, "nope", "x", None)
    expect("NOT-FOUND", imports.axis_page_save, B, ax["A"], "남의 축", None)
    expect("NOT-FOUND", imports.axis_page_save, A, it[1], "축 아닌 항목", None)
    assert imports.axis_overview(B)["axes"][0]["page"] is None, "남의 내 판은 안 보인다"
    # 웹 = 같은 함수
    cur = one()["mine"]["updated_at"]
    w = await web(f"/api/axes/{ax['A']}/page", body={"markdown": "웹 내 판", "expected_updated_at": cur})
    assert w.status_code == 200 and w.json()["axis"]["page"]["body"] == "웹 내 판", w.text[:300]
    w = await web(f"/api/axes/{ax['A']}/page", body={"markdown": "웹 내 판", "expected_updated_at": cur})
    assert w.status_code == 400 and w.json()["code"] == "STALE", w.text
    assert (await web(f"/api/axes/{ax['A']}/page", user=OTHER, body={"markdown": "x", "expected_updated_at": None})).status_code == 404
    assert (await web(f"/api/axes/{ax['A']}/page", body={"markdown": "x"}, origin="https://evil.example")).status_code == 403
    assert (await web(f"/api/axes/{ax['A']}/page", body={"markdown": 3})).status_code == 400
    w = await web(f"/api/axes?id={ax['A']}")
    sample = json.loads((HERE / "ui" / "src" / "shared" / "axes.sample.json").read_text(encoding="utf-8"))
    bad = cmp(sample["one"], w.json(), "one", exact=True) + cmp(sample["overview"], (await web("/api/axes")).json(), "overview", exact=True)
    assert not bad, (bad, "axes.sample.json 과 화면 타입을 같이 고친다")
    # MCP — facade 전용 write op, axis_overview_get 에 mine, inbox_digest_get read op
    async with Client(main.mcp) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert "axis_page_save" not in tools and "inbox_digest_get" not in tools, "facade 전용"
        cur = one()["mine"]["updated_at"]
        res = await c.call_tool("write", {"op": "axis_page_save", "params": {"axis_id": ax["A"], "markdown": "대화 내 판",
                                                                             "expected_updated_at": cur}})
        assert not res.is_error and mcp_val(res)["axis"]["page"]["body"] == "대화 내 판", res.content[0].text[:300]
        res = await c.call_tool("write", {"op": "axis_page_save", "params": {"axis_id": ax["A"], "markdown": "x", "expected_updated_at": cur}})
        assert res.is_error and CODE.search(res.content[0].text).group(1) == "STALE", res.content[0].text
        res = await c.call_tool("read", {"op": "axis_overview_get", "params": {"axis_id": ax["A"]}})
        assert mcp_val(res)["axes"][0]["page"]["mine"]["record_id"] == one()["mine"]["record_id"]
        res = await c.call_tool("read", {"op": "inbox_digest_get", "params": {}})
        assert not res.is_error and mcp_val(res) == json.loads(json.dumps(imports.inbox_digest(A))), res.content[0].text[:300]
        det = await c.call_tool("find", {"op": "inbox_digest_get"})
        assert not det.is_error and "AI 값" in det.content[0].text, det.content[0].text[:300]
    with db.tx() as c:
        via = c.execute("SELECT generation_meta->>'via' AS v FROM records WHERE user_id=%s AND id=%s",
                        (A, one()["mine"]["record_id"])).fetchone()["v"]
    assert via == "mcp"
    assert "axis_page_save" in main.INSTRUCTIONS and "inbox_digest_get" in main.INSTRUCTIONS
    ok("5 내가 고친 판(받은 그대로, STALE, 옛 판 휴지통과 복원, ai_newer, body/ai_body, AI 초안 없는 축, 비적격, 출처 정정 잠금, 격리, 웹 같은 함수,"
       " 견본 대조, MCP write op facade 전용)")


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
    print("ALL OK — test_routine_feedback")


if __name__ == "__main__":
    main_()
