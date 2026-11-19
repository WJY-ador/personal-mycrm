"""축 잇기 시험(2026-11-18 축 잇기 명세 2절 — 수집 글 축 코드, 축 한 장, 축 보기).

실행: DATABASE_URL=postgresql://localhost/crm_test_axis python3 server/test_axis_link.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 자료는 가짜 축 코드·가짜 이름뿐이다.

1. 수집 글 axis_codes — 그 사용자의 축 항목(items.code)으로 바꿔 axes 관계 · 없는 코드는 버리고 수만 응답 · 장치 정책 축과 대조하지 않음
   · 둘 다 오면 axis_codes · 옛 axes(항목 id) 경로와 POLICY-DENIED 그대로 · 새 개정이 축 관계를 바꾼다 · 같은 내용 noop · 옛 투영 해시 그대로
2. 사용자가 판별(보관)한 글 — 새 개정의 축 관계만 맞춘다(제목·판별 state 그대로)
3. 축 한 장 axis-page/1 — 받는 즉시 기록(unknown·generated·ai, 출처 축 한 장) · 그 축에 axes 연결 · 새 판이 옛 판의 축 연결을 대신 · 계약 거절
4. 인용 비적격 — answer_get 근거·후보·꺼내기 인용에 한 장이 들어가지 않는다
5. 축 보기(imports.axis_overview = 웹 GET /api/axes = MCP axis_overview_get) — 건수·최신 한 장·본문·격리 · 목록 보기 f.axes 필터·축 칩
6. 장치 정보 features(코드 있는 축이 있을 때만 axis_codes) · 「전부 허용」 장치에 axis-page/1 을 더하는 이관(한 번)
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
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_axis). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ci-axis-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_IMPORTS_ENABLED"] = "1"
os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

import answer  # noqa: E402
import db  # noqa: E402
import export_forms  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
from test_sample_shape import cmp  # noqa: E402

MAIN, OTHER = "ci-axis-main@example.com", "ci-axis-other@example.com"
EMAILS = (MAIN, OTHER)
FIELDS = [
    {"key": "channel", "label": "채널", "value_type": "select", "required": True, "options": list(imports.COLLECTED_CHANNELS)},
    {"key": "collected_on", "label": "수집일", "value_type": "date", "required": True}]
WORD = "가짜축낱말"   # 한 장 본문과 내 글에 같이 넣는 찾기 낱말(answer_get 근거 시험)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def axes_object(uid):
    with db.tx() as c:
        o = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND key='axes'", (uid,)).fetchone()
    if not o:
        q0 = db.definition_propose(uid, None, 0, {"key": "axes", "label": "축", "semantic_kind": "collection", "fields": []})
        db.definition_apply(uid, q0["object_id"], q0["proposal_id"], 0)
        o = {"id": q0["object_id"], "revision": 1}
    return o


def axis_item(uid, o, code, title, body="", data=None):
    p = db.item_propose(uid, o["id"], o["revision"], None, 0, code, title, body, data or {}, [])
    return db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]


def setup_user(uid, coded=True):
    """축 오브젝트(가짜 축 둘, coded=False 면 코드 없음) + 수집 글 오브젝트(axes 여럿) + 기본 정책 장치. 반환 (토큰, 장치 id, {코드: 축 id})."""
    db.display_name_set(uid, "합성")
    o = axes_object(uid)
    with db.tx() as c:   # 키워드 필드 유무는 계정 시드에 따른다
        keys = {f["key"] for f in db._fields(c, uid, o["id"])}
    data = {"keywords": ["가짜 낱말", "가짜 둘"]} if "keywords" in keys else {}
    axes = {}
    axes["A" if coded else "_1"] = axis_item(uid, o, "A" if coded else None, "가짜 축 하나", "가짜 관점 하나", data)
    axes["B-1" if coded else "_2"] = axis_item(uid, o, "B-1" if coded else None, "가짜 축 둘", "", {})
    fields = FIELDS + [{"key": "axes", "label": "축", "value_type": "reference", "target_kind": "item", "target_object_id": o["id"],
                        "multiple": True}]
    q = db.definition_propose(uid, None, 0, {"key": imports.COLLECTED_OBJECT_KEY, "label": "수집 글", "semantic_kind": "collection",
                                             "fields": fields})
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    c1 = imports.device_connect(uid, "합성 PC")
    return c1["token"], c1["device"]["id"], axes


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (e.code, e.message)
        return e
    raise AssertionError(f"{code} 기대, 성공함")


class Dev:
    """장치 한 대 — 원본마다 개정 사슬을 기억한다. 정책 판은 장치 정보(device_self) 그대로."""
    def __init__(self, token, dev_id):
        self.token, self.id, self.chain = token, dev_id, {}
        self.pr = imports.device_self("Bearer " + token)["policy_revision"]

    def body(self, key, kind="collected_post", **kw):
        o, prev, raw = self.chain.get(key, ("o_" + secrets.token_hex(16), None, secrets.token_hex(24)))
        b = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": self.id, "original_id": o,
             "revision": "v_" + secrets.token_hex(16), "previous_revision": prev, "kind": kind, "execution": "unattended",
             "policy_revision": self.pr}
        if kind == "collected_post":
            b.update({"transform_version": "collected-post/1", "raw_id": raw, "channel": "linkedin", "collected_on": "2026-11-12",
                      "title": f"합성 {key} 첫 줄", "state": "pending"})
        else:
            b.update({"transform_version": "axis-page/1", "title": f"가짜 한 장 {key}", "body": "가짜 본문",
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


async def web(path, user=MAIN):
    site = main.site
    real = site.dev, site.dev_user
    try:
        site.dev, site.dev_user = True, user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            return await h.get(path)
    finally:
        site.dev, site.dev_user = real


def axes_of(uid, item_id):
    with db.tx() as c:
        return sorted(r["target_item_id"] for r in c.execute(
            "SELECT target_item_id FROM item_links WHERE user_id=%s AND source_item_id=%s AND field_key='axes'", (uid, item_id)).fetchall())


def rec_axes(uid, rid):
    with db.tx() as c:
        return sorted(r["target_item_id"] for r in c.execute(
            "SELECT target_item_id FROM item_links WHERE user_id=%s AND source_record_id=%s AND field_key='axes'", (uid, rid)).fetchall())


def entry(uid, iid):
    with db.tx() as c:
        return c.execute("SELECT state, is_current_applied, target_item_id, target_record_id FROM import_entries "
                         "WHERE user_id=%s AND id=%s", (uid, iid)).fetchone()


async def run():
    A, B = db.user_by_email(MAIN)["id"], db.user_by_email(OTHER)["id"]
    tok, did, ax = setup_user(A)
    btok, bdid, bax = setup_user(B, coded=False)
    d = Dev(tok, did)

    # ── 1. 수집 글 axis_codes ──
    with db.tx() as c:
        pol = c.execute("SELECT policy FROM import_streams WHERE user_id=%s AND id=%s", (A, did)).fetchone()["policy"]
    assert pol["axes"] == [] and "axis-page/1" in pol["transform_versions"], pol   # 기본 정책 = 축 0개, 새 변환 포함
    r = await d.send("p1", axis_codes=["A", "B-1", "ZZ"])
    assert r["state"] == "applied" and r["axis_codes_unknown"] == 1, r   # 없는 코드 ZZ = 버리고 수만
    i1 = r["target_id"]
    assert axes_of(A, i1) == sorted([ax["A"], ax["B-1"]])
    # 새 개정이 축 관계를 바꾼다(장치 값으로 덮는다)
    r = await d.send("p1", axis_codes=["B-1"])
    assert r["state"] == "applied" and r["axis_codes_unknown"] == 0 and axes_of(A, i1) == [ax["B-1"]], (r, axes_of(A, i1))
    # 같은 내용 새 개정 = noop(축 맞추기를 하지 않아 수 키도 없다)
    r = await d.send("p1", axis_codes=["B-1"])
    assert r["state"] == "noop" and "axis_codes_unknown" not in r, r
    # 둘 다 오면 axis_codes — axes 의 남의(분류 아닌) id 가 있어도 POLICY-DENIED 가 아니다
    r = await d.send("p2", axes=[bax["_1"]], axis_codes=["A"])
    assert r["state"] == "applied" and axes_of(A, r["target_id"]) == [ax["A"]], r
    # 옛 앱 경로(axes 항목 id) 그대로 — 계정의 축이면 받고, 아니면 POLICY-DENIED
    r = await d.send("p3", axes=[ax["A"]])
    assert axes_of(A, r["target_id"]) == [ax["A"]]
    r = await d.send("p4", axes=[bax["_1"]], status=403)
    assert r["code"] == "POLICY-DENIED", r
    # 계약: 코드 꼴, 개수, 중복
    for bad, rule in ((["a"], "axis_codes[0]: format"), (["A"] * 2, "axis_codes: duplicate"),
                      ([f"X{i}" for i in range(11)], "axis_codes: list_max_10"), (["TOO-LONG-CODE"], "axis_codes[0]: format")):
        r = await d.send("p5", axis_codes=bad, status=400)
        assert r["code"] == "CONTRACT-INVALID" and rule in r["msg"], (bad, r)
    # 투영: axis_codes 키가 없으면 옛 투영 그대로(옛 앱 재전송이 새 개정으로 바뀌지 않는다), 있으면 정렬해 넣는다
    base = d.body("x")
    assert "axis_codes" not in imports.projection(base)
    assert imports.projection({**base, "axis_codes": ["B-1", "A"]})["axis_codes"] == ["A", "B-1"]
    print("OK 1 수집 글 axis_codes(코드 → 축 항목·없는 코드 수·정책 축 대조 없음·둘 다면 코드·옛 경로·POLICY-DENIED·개정·noop·계약·투영)")

    # ── 2. 사용자가 보관한 글 — 축 관계만 맞춘다 ──
    r = await d.send("k1", axis_codes=["A"])
    k1 = r["target_id"]
    imports.collected_decide(A, k1, "kept", None, via="web")
    r = await d.send("k1", axis_codes=["A", "B-1"], title="합성 k1 바뀐 첫 줄")
    assert r["state"] == "applied" and axes_of(A, k1) == sorted([ax["A"], ax["B-1"]]), (r, axes_of(A, k1))
    with db.tx() as c:
        it = c.execute("SELECT title FROM items WHERE user_id=%s AND id=%s", (A, k1)).fetchone()
        cs = c.execute("SELECT state, decided_by FROM collected_states WHERE user_id=%s AND item_id=%s", (A, k1)).fetchone()
    assert it["title"] == "합성 k1 첫 줄" and (cs["state"], cs["decided_by"]) == ("kept", "user"), (it, cs)
    r = await d.send("k1", axis_codes=["A", "B-1"], title="합성 k1 또 바뀐 첫 줄")   # 축이 같으면 noop
    assert r["state"] == "noop", r
    print("OK 2 사용자가 보관한 글 = 축 관계만 새 개정 값으로(제목·판별 state 그대로) · 축이 같으면 noop")

    # ── 3. 축 한 장 ──
    r = await d.send("ax-A", kind="self_text", body=f"# 무시\n가짜 첫 판 {WORD} 본문")
    assert r["state"] == "applied" and r["target_kind"] == "record", r
    r1 = r["target_id"]
    with db.tx() as c:
        x = c.execute("SELECT author_kind, text_process, generation_kind, source, generation_meta, source_created_at FROM records "
                      "WHERE user_id=%s AND id=%s", (A, r1)).fetchone()
    assert (x["author_kind"], x["text_process"], x["generation_kind"], x["source"]) == ("unknown", "generated", "ai", "축 한 장"), x
    assert x["generation_meta"]["axis_code"] == "A" and x["generation_meta"]["transform_version"] == "axis-page/1", x
    assert rec_axes(A, r1) == [ax["A"]]
    first_entry = r["import_id"]
    r = await d.send("ax-A", kind="self_text", body=f"가짜 둘째 판 {WORD} 본문")
    r2 = r["target_id"]
    assert r2 != r1 and rec_axes(A, r2) == [ax["A"]] and rec_axes(A, r1) == [], "새 판이 그 축 연결을 대신한다"
    assert entry(A, r["import_id"])["is_current_applied"] and not entry(A, first_entry)["is_current_applied"]
    with db.tx() as c:
        assert c.execute("SELECT 1 FROM records WHERE user_id=%s AND id=%s AND deleted_at IS NULL", (A, r1)).fetchone(), "옛 판 기록은 남는다"
    # 승인 스위치가 꺼지면 대기 → 켠 뒤 승인(inbox_approve)도 같은 본체(축 연결, 옛 판 연결 떼기)
    os.environ.pop("CRM_INBOX_APPROVALS_ENABLED", None)
    try:
        r = await d.send("ax-A", kind="self_text", body="가짜 셋째 판 본문")
        assert r["state"] == "pending", r
    finally:
        os.environ["CRM_INBOX_APPROVALS_ENABLED"] = "1"
    r3 = imports.inbox_approve(A, r["import_id"])["record_id"]
    assert rec_axes(A, r3) == [ax["A"]] and rec_axes(A, r2) == [], "수동 승인도 같은 길"
    r = await d.send("ax-A", kind="self_text", body=f"가짜 넷째 판 {WORD} 본문")
    r1, r2 = r3, r["target_id"]
    assert rec_axes(A, r2) == [ax["A"]] and rec_axes(A, r1) == []
    # 축 항목이 없는 코드 = 기록만(연결 없음, 오류 아님)
    r = await d.send("ax-Q", kind="self_text", axis_code="Q")
    assert r["state"] == "applied" and rec_axes(A, r["target_id"]) == []
    # 계약 — axis_code 필수·꼴, 다른 변환의 axis_code 금지, 한 장의 activity_ref·generation 금지
    r = await d.send("bad1", kind="self_text", axis_code=..., status=400)
    assert "axis_code: required" in r["msg"], r
    r = await d.send("bad2", kind="self_text", axis_code="b-1", status=400)
    assert "axis_code: format" in r["msg"], r
    r = await d.send("bad3", kind="self_text", transform_version="self-text/1", status=400)
    assert "axis_code: unknown_field" in r["msg"], r
    r = await d.send("bad4", kind="self_text", generation={"method": "none"}, status=400)
    assert "generation: unknown_field" in r["msg"], r
    print("OK 3 축 한 장(받는 즉시 기록 unknown·generated·ai·출처 축 한 장 · 축 연결 · 새 판이 옛 판 연결을 대신 · 현재 판 · 없는 코드 · 계약)")

    # ── 4. 인용 비적격 ──
    mine = db.record_add(A, "합성 내 글", f"내가 쓴 {WORD} 문장")
    mine_id = mine["id"] if isinstance(mine, dict) else mine
    out = answer.assemble(A, question=f"{WORD} 는?", terms=[WORD])
    ev_ids = {e.get("record", {}).get("id") or e.get("id") for e in out["evidence"]}
    blob = json.dumps(out, ensure_ascii=False)
    assert mine_id in blob and r2 not in blob and r1 not in blob and "가짜 넷째 판" not in blob, (ev_ids, out["evidence"])
    acc, rej = db.candidates_propose(A, r2, "", [{"text": "가짜 판단", "quote": "가짜 넷째 판"}], "ai")
    assert acc == [] and rej and rej[0]["why"] == db.INELIGIBLE_WHY, (acc, rej)
    ex = export_forms.assemble(A, "period_report", {"kind": "period", "period": "all"})
    ex_blob = json.dumps(ex, ensure_ascii=False)
    assert r2 not in ex_blob and "가짜 넷째 판" not in ex_blob
    print("OK 4 한 장 = 인용 비적격(answer_get 근거 0 · 후보 거절 · 꺼내기 인용 0)")

    # ── 5. 축 보기 · 목록 필터 ──
    ov = imports.axis_overview(A)
    assert ov["ready"] is True
    byc = {a["code"]: a for a in ov["axes"]}
    assert [a["code"] for a in ov["axes"]][:2] == ["A", "B-1"], ov
    a_ = byc["A"]
    # A: p2(대기), k1(보관) · B-1: p1(대기), k1(보관). p3 = 옛 경로로 A
    assert a_["counts"] == {"pending": 2, "kept": 1, "total": 3}, a_["counts"]
    assert byc["B-1"]["counts"] == {"pending": 1, "kept": 1, "total": 2}, byc["B-1"]["counts"]
    assert a_["title"] == "가짜 축 하나" and a_["description"] == "가짜 관점 하나" and isinstance(a_["keywords"], list)
    assert a_["page"]["record_id"] == r2 and a_["page"]["ai"] is True and "body" not in a_["page"], a_["page"]
    assert a_["page"]["notice"] == imports.AXIS_PAGE_NOTICE and a_["page"]["at"].startswith("2026-11-18T")
    assert byc["B-1"]["page"] is None
    one = imports.axis_overview(A, ax["A"])
    assert len(one["axes"]) == 1 and "가짜 넷째 판" in one["axes"][0]["page"]["body"], one
    expect("NOT-FOUND", imports.axis_overview, B, ax["A"])   # 남의 축
    expect("ARG-INVALID", imports.axis_overview, A, "nope")
    ob = imports.axis_overview(B)
    assert [a["code"] for a in ob["axes"]][-2:] == [None, None] and all(a["page"] is None for a in ob["axes"]), ob
    # 웹 = 같은 함수
    w = await web("/api/axes")
    assert w.status_code == 200 and w.json() == json.loads(json.dumps(imports.axis_overview(A))), w.text
    w = await web(f"/api/axes?id={ax['A']}")
    assert w.status_code == 200 and w.json()["axes"][0]["page"]["body"] == one["axes"][0]["page"]["body"]
    assert (await web(f"/api/axes?id={ax['A']}", user=OTHER)).status_code == 404
    # 목록 보기 f.axes = 그 축에 붙은 수집 글만 · 행에 축 칩
    lst = db.object_list(A, imports.COLLECTED_OBJECT_KEY, filters={"axes": ax["B-1"]})
    assert {r["id"] for r in lst["rows"]} == {i1, k1} and lst["total"] == 2, lst["rows"]
    row = next(r for r in lst["rows"] if r["id"] == k1)
    assert [x["code"] for x in row["axes"]] == ["A", "B-1"], row
    expect("ARG-INVALID", db.object_list, A, imports.COLLECTED_OBJECT_KEY, filters={"axes": "A"})
    # 축 필터가 있으면 상태 칩(states)·필터 칩(filters) 건수도 그 축 안에서 센다 — 축 보기 counts 와 같다
    allv = db.object_list(A, imports.COLLECTED_OBJECT_KEY)
    for aid, code in ((ax["A"], "A"), (ax["B-1"], "B-1")):
        one_ax = db.object_list(A, imports.COLLECTED_OBJECT_KEY, filters={"axes": aid})
        cnt = byc[code]["counts"]
        assert one_ax["states"]["pending"] == cnt["pending"] and one_ax["states"]["kept"] == cnt["kept"], (code, one_ax["states"], cnt)
        assert sum(one_ax["states"].values()) == one_ax["total"] == cnt["total"], (code, one_ax["states"], one_ax["total"])
        ch = next(f for f in one_ax["filters"] if f["key"] == "channel")
        assert sum(v["n"] for v in ch["values"]) == cnt["total"], (code, ch)
    # 축 필터가 없으면 전과 같다 — 오브젝트 전체 기준(축 없는 글 포함)
    with db.tx() as c:
        n_all = c.execute("SELECT count(*) AS n FROM items i JOIN object_defs o ON o.user_id=i.user_id AND o.id=i.object_id "
                          "WHERE i.user_id=%s AND o.key=%s AND i.revision > 0 AND i.archived_at IS NULL AND i.trashed_at IS NULL",
                          (A, imports.COLLECTED_OBJECT_KEY)).fetchone()["n"]
    assert allv["total"] == n_all == sum(allv["states"].values()) > a_["counts"]["total"], (allv["total"], n_all, allv["states"])
    ch = next(f for f in allv["filters"] if f["key"] == "channel")
    assert sum(v["n"] for v in ch["values"]) == n_all, ch
    w = await web(f"/api/me/objects/{imports.COLLECTED_OBJECT_KEY}?f.axes={ax['A']}")
    assert w.status_code == 200 and w.json()["total"] == 3, w.text
    # 화면 견본(server/ui/src/shared/axes.sample.json) = 실제 응답 꼴(키 집합까지)
    sample = json.loads((HERE / "ui" / "src" / "shared" / "axes.sample.json").read_text(encoding="utf-8"))
    real_one = json.loads(json.dumps(one))
    bad = cmp(sample["overview"], json.loads(json.dumps(ov)), "overview", exact=True) + \
        cmp(sample["one"], real_one, "one", exact=True) + cmp(sample["row_axes"], row["axes"], "row_axes", exact=True)
    assert not bad, (bad, "axes.sample.json, shared/axes.ts 의 타입을 같이 고친다")
    col = imports.collected_list(A, "kept")
    assert [x["code"] for x in col["posts"][0]["axes"]] == ["A", "B-1"], col["posts"][0]["axes"]
    print("OK 5 축 보기(건수·최신 한 장·본문은 하나 물을 때·격리·코드 없는 축 · 웹 = 같은 함수) · 목록 f.axes 필터·축 칩 · 인박스 축 코드")

    # ── 6. 장치 features · 정책 이관 ──
    assert imports.device_self("Bearer " + tok)["features"] == ["axis_codes"]
    assert imports.device_self("Bearer " + btok)["features"] == [], "코드 있는 축이 없으면 앱은 옛 경로 그대로"
    old = [t for t in imports.TRANSFORMS if t != "axis-page/1"]
    assert set(old) == set(imports.ALL_BEFORE_V2)
    with db.tx() as c:
        c.execute("UPDATE import_streams SET policy=%s WHERE user_id=%s AND id=%s",
                  (Jsonb({"actions": list(imports.ACTIONS), "transform_versions": old, "axes": []}), B, bdid))
        c.execute("DELETE FROM schema_marks WHERE key=%s", (imports.POLICY_ALL_V2_MARK,))
        before = c.execute("SELECT policy_revision FROM import_streams WHERE user_id=%s AND id=%s", (B, bdid)).fetchone()["policy_revision"]
        n = imports.migrate_device_policy(c)
        s = c.execute("SELECT policy, policy_revision FROM import_streams WHERE user_id=%s AND id=%s", (B, bdid)).fetchone()
        assert n >= 1 and "axis-page/1" in s["policy"]["transform_versions"] and s["policy_revision"] == before + 1, (n, s)
        assert imports.migrate_device_policy(c) == 0, "표식 한 번"
        # 사용자가 줄인 정책(일부 변환만)은 그대로
        c.execute("UPDATE import_streams SET policy=%s WHERE user_id=%s AND id=%s",
                  (Jsonb({"actions": ["like"], "transform_versions": ["collected-post/1"], "axes": []}), B, bdid))
        c.execute("DELETE FROM schema_marks WHERE key=%s", (imports.POLICY_ALL_V2_MARK,))
        imports.migrate_device_policy(c)
        s = c.execute("SELECT policy FROM import_streams WHERE user_id=%s AND id=%s", (B, bdid)).fetchone()
        assert s["policy"]["transform_versions"] == ["collected-post/1"], s
    # v3(2026-11-19): v2 대상 밖(board-mail/1 없음) 장치에도 axis-page/1 을 더한다. 다른 변환은 그대로, 이미 가진 장치는 그대로, 한 번
    assert "axis-page/1" in imports.DEFAULT_POLICY["transform_versions"], "새 장치 기본 정책"
    no_mail = [t for t in old if t != "board-mail/1"]
    with db.tx() as c:
        c.execute("UPDATE import_streams SET policy=%s WHERE user_id=%s AND id=%s",
                  (Jsonb({"actions": list(imports.ACTIONS), "transform_versions": no_mail, "axes": []}), B, bdid))
        rev = lambda u, d: c.execute("SELECT policy, policy_revision FROM import_streams WHERE user_id=%s AND id=%s",
                                     (u, d)).fetchone()
        b0, a0 = rev(B, bdid), rev(A, did)
        assert "axis-page/1" in a0["policy"]["transform_versions"], a0
        c.execute("DELETE FROM schema_marks WHERE key=%s", (imports.POLICY_ALL_V3_MARK,))
        n = imports.migrate_device_policy(c)
        b1, a1 = rev(B, bdid), rev(A, did)
        assert n >= 1 and b1["policy"]["transform_versions"] == no_mail + ["axis-page/1"], (n, b1)
        assert b1["policy_revision"] == b0["policy_revision"] + 1 and b1["policy"]["actions"] == b0["policy"]["actions"], b1
        assert "board-mail/1" not in b1["policy"]["transform_versions"], "다른 변환은 더하지 않는다"
        assert a1 == a0, "이미 가진 장치는 판도 그대로"
        assert imports.migrate_device_policy(c) == 0, "v3 표식 한 번"
    print("OK 6 장치 features(코드 있는 축 = axis_codes, 없으면 빈 목록) · 전부 허용 장치에 axis-page/1 더하기(판 +1, 한 번, 줄인 정책 그대로)"
          " · v3 모든 장치에 axis-page/1(다른 변환 그대로, 가진 장치 그대로, 한 번)")


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
    print("ALL OK — test_axis_link")


if __name__ == "__main__":
    main_()
