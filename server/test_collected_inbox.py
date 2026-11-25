"""수집 인박스 시험(2026-11-13 오늘 탭 = 대시보드.app 오늘 탭, 판별 정본 = 서버).

실행: DATABASE_URL=postgresql://localhost/crm_test_today python3 server/test_collected_inbox.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1. 장치 state 기록(pending, kept, dropped) · 같은 내용 재전송도 state 를 채운다 · removed 휴지통은 그대로
2. 웹 목록(인박스 pending, 보관함 kept) · 오브젝트 없음 = ready false · 축 제목 · ai 필드 · https 아닌 URL 숨김
3. 웹 판별(kept, dropped, pending) — 이력 한 줄·revision +1 · CONFLICT · 같은 판별 no-op · NOT-FOUND(남의·없는·휴지통) · 보관 항목 CONFLICT
4. 사용자 판별 항목 = 장치 개정 noop(removed 포함) · 되돌리기(pending)는 다시 장치 state 를 따른다 · 버림은 휴지통이 아니다
5. 묶음 버림(200 상한, skipped) · 일반 결정 한도에 세지 않는다
6. 장치 판별 목록 GET /api/imports/decisions — 사용자 판별만 · 그 장치 항목만 · seq 커서·has_more · 인증·인자 오류
7. 대화 op collected_post_decide(via mcp 이력) · 계정 삭제가 판별 표를 지운다 · 화면 견본(collected.sample.json) 대조
10. 읽기 판 긴 요약 작업 collected_long(2026-11-25) — 접수, 열린 작업 재사용(한도 미산입), 남의·없는·휴지통 항목 404, 하루 한도, 결과 모양 오류,
   ai_* 넷만 기록(판별된 항목에도, revision·이력 불변), confirmed 종료와 재전송, 실패 코드, 스위치 꺼짐 503, 작업 CHECK 확장,
   kinds 없는 옛 폴은 임대받지 않음, MCP op collected_post_summarize
"""
import uuid
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
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_today). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ci-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_IMPORTS_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
from test_sample_shape import cmp  # noqa: E402

MAIN, OTHER, AXU, LONG = "ci-main@example.com", "ci-other@example.com", "ci-axes@example.com", "ci-long@example.com"
EMAILS = (MAIN, OTHER, AXU, LONG)
H = {"origin": PUBLIC}
FIELDS = [
    {"key": "channel", "label": "채널", "value_type": "select", "required": True, "options": list(imports.COLLECTED_CHANNELS)},
    {"key": "author_display", "label": "작성자 표시", "value_type": "text"},
    {"key": "post_url", "label": "원 URL", "value_type": "text"},
    {"key": "posted_on", "label": "게시일", "value_type": "date"},
    {"key": "collected_on", "label": "수집일", "value_type": "date", "required": True},
    {"key": "ai_grade", "label": "AI 등급", "value_type": "select", "options": list(imports.COLLECTED_GRADES)},
    {"key": "ai_summary", "label": "AI 요약", "value_type": "text"},
    {"key": "ai_as_is", "label": "AI as-is", "value_type": "text"},
    {"key": "ai_to_be", "label": "AI to-be", "value_type": "text"},
    {"key": "ai_ops", "label": "AI 운영", "value_type": "text"},
    {"key": "ai_points", "label": "AI 요점", "value_type": "text_list"}]


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


def setup_user(uid, axes=True):
    """수집 글 오브젝트 + 축 항목 1 + 장치(collected-post/1 허용). 반환 (토큰, 장치 id, 축 id)."""
    db.display_name_set(uid, "합성")
    with db.tx() as c:   # 새 사용자에 이미 있는 축 오브젝트(key axes)를 쓰고, 없으면 만든다
        o = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND key='axes'", (uid,)).fetchone()
    if not o:
        q0 = db.definition_propose(uid, None, 0, {"key": "axes", "label": "축", "semantic_kind": "collection", "fields": []})
        db.definition_apply(uid, q0["object_id"], q0["proposal_id"], 0)
        o = {"id": q0["object_id"], "revision": 1}
    p = {"object_id": o["id"]}
    ev = db.item_propose(uid, p["object_id"], o["revision"], None, 0, "AX-0", "합성 축", "", {}, [])
    ax = db.item_decide(uid, ev["item_id"], 0, ev["proposal_id"], "apply")["id"]
    with db.tx() as c:
        assert db._classify_target(c, uid) == p["object_id"]
    fields = FIELDS + ([{"key": "axes", "label": "축", "value_type": "reference", "target_kind": "item", "target_object_id": p["object_id"],
                         "multiple": True}] if axes else [])
    q = db.definition_propose(uid, None, 0, {"key": imports.COLLECTED_OBJECT_KEY, "label": "수집 글", "semantic_kind": "collection",
                                             "fields": fields})
    db.definition_apply(uid, q["object_id"], q["proposal_id"], 0)
    c1 = imports.device_connect(uid, "합성 수집 PC")
    imports.device_policy_set(uid, c1["device"]["id"], {"actions": ["like"], "transform_versions": ["collected-post/1"], "axes": [ax]}, 1)
    return c1["token"], c1["device"]["id"], ax


class Dev:
    """장치 한 대의 수집 글 전송 — 원본마다 개정 사슬을 기억한다."""
    def __init__(self, token, dev_id):
        self.token, self.id, self.chain, self.last = token, dev_id, {}, {}

    def body(self, key, **kw):
        o, prev = self.chain.get(key, (None, None, None))[:2]
        raw = self.chain.get(key, (None, None, secrets.token_hex(24)))[2]
        b = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": self.id, "original_id": o or "o_" + secrets.token_hex(16),
             "revision": "v_" + secrets.token_hex(16), "previous_revision": prev, "kind": "collected_post", "execution": "unattended",
             "transform_version": "collected-post/1", "policy_revision": 2, "raw_id": raw, "channel": "linkedin",
             "collected_on": "2026-11-12", "title": f"합성 {key} 첫 줄", "state": "pending"}
        b.update(kw)
        return b

    async def send(self, key, **kw):
        b = self.body(key, **kw)
        hd = {"content-type": "application/json", "authorization": "Bearer " + self.token,
              "idempotency-key": imports.idempotency_key(b["source_instance_id"], b["original_id"], b["revision"])}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            r = await h.post("/api/imports", content=json.dumps(b, ensure_ascii=False).encode("utf-8"), headers=hd)
        assert r.status_code in (200, 201), r.text
        self.chain[key] = (b["original_id"], b["revision"], b["raw_id"])
        self.last[key] = b
        return r.json()

    async def resend(self, key):
        """마지막에 보낸 요청 그대로(같은 개정) — duplicate."""
        b = self.last[key]
        hd = {"content-type": "application/json", "authorization": "Bearer " + self.token,
              "idempotency-key": imports.idempotency_key(b["source_instance_id"], b["original_id"], b["revision"])}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            r = await h.post("/api/imports", content=json.dumps(b, ensure_ascii=False).encode("utf-8"), headers=hd)
        assert r.status_code == 200, r.text
        return r.json()

    async def decisions(self, token=None, **params):
        hd = {"authorization": "Bearer " + (token or self.token)} if token != "" else {}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            return await h.get("/api/imports/decisions", params=params, headers=hd)


def cs(uid, iid):
    with db.tx() as c:
        return c.execute("SELECT state, decided_by, seq FROM collected_states WHERE user_id=%s AND item_id=%s", (uid, iid)).fetchone()


def item(uid, iid):
    with db.tx() as c:
        return c.execute("SELECT title, revision, trashed_at, archived_at FROM items WHERE user_id=%s AND id=%s", (uid, iid)).fetchone()


def hist(uid, iid):
    with db.tx() as c:
        return [(r["action"], r["event_meta"]) for r in c.execute(
            "SELECT action, event_meta FROM item_history WHERE user_id=%s AND item_id=%s ORDER BY id", (uid, iid))]


async def web(method, path, body=None, user=MAIN):
    site = main.site
    real = site.dev, site.dev_user
    try:
        site.dev, site.dev_user = True, user
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            if method == "GET":
                return await h.get(path)
            return await h.post(path, json=body, headers=H)
    finally:
        site.dev, site.dev_user = real


async def axes_from_account(other_ax):
    """축(2026-11-13 메인 판정) — 장치 정책 axes 허용 목록을 보지 않는다. 기본 정책(축 0개) 장치도 계정의 축 항목이면 받는다.
    장치 정책 응답 axes = 계정의 지금 축 전부, 판 = 저장 판 + 축 지문(축이 바뀌면 바뀐다). 남의 축 = POLICY-DENIED, 휴지통 축 = 연결만 뺀다."""
    U = db.user_by_email(AXU)["id"]
    tok, dev_id, ax = setup_user(U)
    imports.device_policy_set(U, dev_id, imports.DEFAULT_POLICY, 2)   # 기본 정책(축 0개)으로 되돌림 — 저장 판 3
    hd = {"authorization": "Bearer " + tok}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        info = (await h.get("/api/imports/device", headers=hd)).json()
    assert info["policy"]["axes"] == [ax] and info["policy"]["transform_versions"] == imports.DEFAULT_POLICY["transform_versions"], info
    with db.tx() as c:
        wire = imports.wire_revision(3, imports.live_axes(c, U))
    assert info["policy_revision"] == wire != 3, info
    d = Dev(tok, dev_id)

    async def post(b):
        hd2 = {**hd, "content-type": "application/json",
               "idempotency-key": imports.idempotency_key(b["source_instance_id"], b["original_id"], b["revision"])}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            return await h.post("/api/imports", content=json.dumps(b, ensure_ascii=False).encode("utf-8"), headers=hd2)

    r = await post(d.body("ax1", axes=[ax], policy_revision=wire))
    assert r.status_code in (200, 201), r.text
    with db.tx() as c:
        links = c.execute("SELECT target_item_id FROM item_links WHERE user_id=%s AND field_key='axes' AND source_item_id IS NOT NULL", (U,)).fetchall()
    assert [x["target_item_id"] for x in links] == [ax], links
    act = {"contract": "canon-inbox/1", "schema_revision": 2, "source_instance_id": dev_id, "original_id": "o_" + secrets.token_hex(16),
           "revision": "v_" + secrets.token_hex(16), "previous_revision": None, "kind": "activity", "execution": "unattended",
           "transform_version": "board-likes/1", "policy_revision": 3, "action": "like", "state": "active", "occurred_on": None,
           "observed_on": None, "provider": "sns", "raw_id": secrets.token_hex(24), "axes": [ax]}
    import features
    with db.tx() as c:   # 활동 접수 스위치를 이 시험 동안만 켠다(끝에 원래 값)
        prev = c.execute("SELECT enabled FROM org_features WHERE feature='activity_imports'").fetchone()
        c.execute("INSERT INTO org_features (feature, enabled) VALUES ('activity_imports', true) ON CONFLICT (feature) DO UPDATE SET enabled=true")
    features.clear_cache()
    try:
        r = await post(act)
        assert r.status_code in (200, 201), r.text   # 저장 판(3)도 받는다
        r = await post({**act, "original_id": "o_" + secrets.token_hex(16), "revision": "v_" + secrets.token_hex(16),
                        "raw_id": secrets.token_hex(24), "axes": [other_ax]})
        assert r.status_code == 403 and r.json()["code"] == "POLICY-DENIED", r.text
    finally:
        with db.tx() as c:
            if prev is None:
                c.execute("DELETE FROM org_features WHERE feature='activity_imports'")
            else:
                c.execute("UPDATE org_features SET enabled=%s WHERE feature='activity_imports'", (prev["enabled"],))
        features.clear_cache()
    r = await post(d.body("ax2", axes=[other_ax], policy_revision=wire))
    assert r.status_code == 403 and r.json()["code"] == "POLICY-DENIED", r.text
    print("OK 8 축 = 계정의 축 항목이면 받음(기본 정책 장치, 수집 글과 활동) · 남의 축 POLICY-DENIED · 정책 응답 axes 계산값")
    # 축을 더하면 판이 바뀐다 → 옛 계산 판 = POLICY-STALE(agent 가 다시 받는다), 저장 판은 그대로 받음
    with db.tx() as c:
        o = c.execute("SELECT object_id FROM items WHERE id=%s", (ax,)).fetchone()["object_id"]
        orev = c.execute("SELECT revision FROM object_defs WHERE id=%s", (o,)).fetchone()["revision"]
    ev = db.item_propose(U, o, orev, None, 0, "AX-1", "합성 축 둘", "", {}, [])
    ax2 = db.item_decide(U, ev["item_id"], 0, ev["proposal_id"], "apply")["id"]
    r = await post(d.body("ax3", axes=[ax2], policy_revision=wire))
    assert r.status_code == 409 and r.json()["code"] == "POLICY-STALE", r.text
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        info2 = (await h.get("/api/imports/device", headers=hd)).json()
    assert sorted(info2["policy"]["axes"]) == sorted([ax, ax2]) and info2["policy_revision"] != wire, info2
    r = await post(d.body("ax3", axes=[ax2], policy_revision=info2["policy_revision"]))
    assert r.status_code in (200, 201), r.text
    # 휴지통 축 = 연결만 빼고 받는다(영구 격리 없음, 휴지통 PR-1 규칙 그대로), 정책 응답에서도 빠진다
    with db.tx() as c:   # 휴지통 스위치(이 시험 뒤 계정은 지운다)
        c.execute("INSERT INTO org_features (feature, enabled) VALUES ('trash', true) ON CONFLICT (feature) DO UPDATE SET enabled=true")
    features.clear_cache()
    db.trash_move(U, "item", ax2, item(U, ax2)["revision"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        info3 = (await h.get("/api/imports/device", headers=hd)).json()
    assert info3["policy"]["axes"] == [ax], info3
    r = await post(d.body("ax4", axes=[ax2], policy_revision=info3["policy_revision"]))
    assert r.status_code in (200, 201), r.text
    with db.tx() as c:
        n = c.execute("SELECT count(*) AS n FROM item_links WHERE user_id=%s AND target_item_id=%s", (U, ax2)).fetchone()["n"]
    assert n == 1, n   # ax3 글의 연결 하나뿐 — 휴지통 뒤 보낸 ax4 글은 그 축 연결 없이 저장
    print("OK 9 축을 더하면 판이 바뀜(옛 계산 판 POLICY-STALE, 다시 받으면 새 축 포함) · 휴지통 축은 정책에서 빠지고 연결만 뺌")


async def run():
    A, B = db.user_by_email(MAIN)["id"], db.user_by_email(OTHER)["id"]
    tok, dev_id, ax = setup_user(A)
    d = Dev(tok, dev_id)
    lim = dict(imports.LIMITS)
    imports.LIMITS[("device", "minute", "request")] = (100000, None)
    imports.LIMITS[("user", "minute", "request")] = (100000, None)
    try:
        await body(A, B, d, ax)
        await axes_from_account(ax)
        await long_jobs(B)
    finally:
        imports.LIMITS.clear()
        imports.LIMITS.update(lim)


async def body(A, B, d, ax):
    # ── 1. 장치 state 기록 ──
    i1 = (await d.send("p1", post_url="https://www.linkedin.com/posts/synthetic-1", author_display="합성 작성자", posted_on="2026-11-10",
                       axes=[ax], ai={"grade": "signal", "summary": "합성 요약", "as_is": "지금", "to_be": "다음", "ops": "운영", "points": ["점"]}))["target_id"]
    assert cs(A, i1) == {"state": "pending", "decided_by": "device", "seq": None}
    i2 = (await d.send("p2", collected_on="2026-11-11", ai={"grade": "news"}))["target_id"]
    i3 = (await d.send("p3", collected_on="2026-11-13"))["target_id"]
    r = await d.send("p2", collected_on="2026-11-11", ai={"grade": "news"}, state="kept")
    assert r["state"] == "applied" and cs(A, i2)["state"] == "kept"
    i4 = (await d.send("p4", collected_on="2026-11-10"))["target_id"]
    expect("CONTRACT-INVALID", imports.validate, d.body("px", state="dropped"))   # 장치 계약엔 dropped 가 없다(판별 표 값일 뿐)
    with db.tx() as c:   # 판별 표가 생기기 전에 올라온 항목 흉내 — 행을 지운다. 같은 내용 새 개정(noop)이 state 를 다시 채운다
        c.execute("DELETE FROM collected_states WHERE user_id=%s AND item_id=%s", (A, i3))
    assert (await d.send("p3", collected_on="2026-11-13"))["state"] == "noop" and cs(A, i3)["state"] == "pending"
    with db.tx() as c:   # 같은 개정 재전송(duplicate)도 빈 state 를 채운다
        c.execute("DELETE FROM collected_states WHERE user_id=%s AND item_id=%s", (A, i3))
    r = await d.resend("p3")
    assert r["duplicate"] is True and cs(A, i3) == {"state": "pending", "decided_by": "device", "seq": None}, (r, cs(A, i3))
    print("OK 1 장치 state 기록(pending·kept · 장치 dropped 거절 · noop·duplicate 재전송이 빈 state 를 채움)")

    # ── 2. 웹 목록 ──
    r = await web("GET", "/api/collected?state=pending")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    j = r.json()
    assert j["ready"] is True and [p["id"] for p in j["posts"]] == [i3, i1, i4] and j["counts"] == {"pending": 3, "kept": 1}, j
    p1 = j["posts"][1]   # 같은 수집일(11-12)이면 id 순
    assert p1["axes"] == [{"id": ax, "code": "AX-0", "title": "합성 축"}] and p1["post_url"] == "https://www.linkedin.com/posts/synthetic-1", p1
    assert p1["ai"] == {"grade": "signal", "summary": "합성 요약", "as_is": "지금", "to_be": "다음", "ops": "운영", "points": ["점"]}, p1["ai"]
    assert p1["state"] == "pending" and p1["decided_by"] == "device" and p1["author_display"] == "합성 작성자"
    j = (await web("GET", "/api/collected?state=kept")).json()
    assert [p["id"] for p in j["posts"]] == [i2]
    assert (await web("GET", "/api/collected?state=dropped")).status_code == 400
    j = (await web("GET", "/api/collected?state=pending", user=OTHER)).json()
    assert j == {"ready": False, "posts": [], "counts": {"pending": 0, "kept": 0}}, j
    print("OK 2 웹 목록(인박스·보관함·축·ai · 오브젝트 없음 ready false · state 인자)")

    # ── 3. 웹 판별 ──
    rev = item(A, i1)["revision"]
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "kept", "expected_revision": rev})
    assert r.status_code == 200, r.text
    dj = r.json()
    assert dj["state"] == "kept" and dj["revision"] == rev + 1 == item(A, i1)["revision"] and dj["decided_at"], dj
    assert cs(A, i1)["decided_by"] == "user" and cs(A, i1)["seq"] is not None
    assert hist(A, i1)[-1] == ("collected_decide", {"state": "kept", "prev": "pending", "decided_by": "user", "via": "web"}), hist(A, i1)
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "kept", "expected_revision": rev + 1})
    assert r.status_code == 200 and r.json()["revision"] == rev + 1, "같은 판별 반복 = no-op"
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "dropped", "expected_revision": rev})
    assert r.status_code == 400 and r.json()["code"] == "CONFLICT", r.text
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "removed", "expected_revision": rev + 1})
    assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", r.text
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "kept"})
    assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", "expected_revision 필수"
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "dropped", "expected_revision": rev + 1}, user=OTHER)
    assert r.status_code in (403, 404), r.text   # 남의 항목(표시 이름 없는 사용자면 이름 관문이 먼저)
    db.display_name_set(B, "남")
    r = await web("POST", f"/api/collected/{i1}/decide", {"state": "dropped", "expected_revision": rev + 1}, user=OTHER)
    assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND", r.text
    r = await web("POST", "/api/collected/i_nothere1234/decide", {"state": "kept", "expected_revision": 1})
    assert r.status_code == 404
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        main.site.dev = False
        try:
            assert (await h.get("/api/collected")).status_code == 401
        finally:
            main.site.dev = True
    expect("NOT-FOUND", imports.collected_decide, A, ax, "kept")   # 수집 글이 아닌 항목
    print("OK 3 웹 판별(이력·revision · no-op · CONFLICT · 인자 · 남의·없는·수집 글 아닌 항목 404 · 401)")

    # ── 4. 사용자 판별 잠금 ──
    r = await d.send("p1", post_url="https://www.linkedin.com/posts/synthetic-1", author_display="합성 작성자", posted_on="2026-11-10",
                     axes=[ax], title="장치가 바꾼 제목", state="pending")
    assert r["state"] == "noop" and cs(A, i1)["state"] == "kept" and item(A, i1)["title"] == "합성 p1 첫 줄", (r, cs(A, i1))
    r = await d.send("p1", state="removed")
    assert r["state"] == "noop" and item(A, i1)["trashed_at"] is None, "사용자 보관 항목은 장치 removed 도 휴지통으로 보내지 않는다"
    dj = imports.collected_decide(A, i1, "pending", item(A, i1)["revision"])   # 되돌리기 — 잠금 풀림
    assert cs(A, i1) and cs(A, i1)["state"] == "pending" and cs(A, i1)["decided_by"] == "user"
    r = await d.send("p1", state="kept", title="되돌린 뒤 장치 제목")
    assert r["state"] == "applied" and cs(A, i1)["state"] == "kept" and cs(A, i1)["decided_by"] == "device" and cs(A, i1)["seq"] is None
    imports.collected_decide(A, i3, "dropped")
    assert item(A, i3)["trashed_at"] is None and cs(A, i3)["state"] == "dropped", "버림은 휴지통이 아니다"
    # 웹 버림 → PC 행 dropped → 다음 업로드는 removed 로 온다 → 사용자 판별 항목이라 noop(휴지통 아님)
    r = await d.send("p3", collected_on="2026-11-13", state="removed")
    assert r["state"] == "noop" and item(A, i3)["trashed_at"] is None and cs(A, i3)["state"] == "dropped", r
    # 사용자 되돌리기(pending) 행 = 같은 내용 재전송(noop)이 건드리지 않는다
    iq = (await d.send("q1"))["target_id"]
    imports.collected_decide(A, iq, "kept")
    imports.collected_decide(A, iq, "pending")
    assert (await d.send("q1"))["state"] == "noop" and cs(A, iq)["decided_by"] == "user", cs(A, iq)
    imports.collected_decide(A, iq, "dropped")
    j = (await web("GET", "/api/collected?state=pending")).json()
    assert i3 not in [p["id"] for p in j["posts"]] and j["counts"]["pending"] == 1, j["counts"]   # i4 만
    # 보관(archive)한 항목 = 판별 CONFLICT · 목록에서 빠짐
    db.item_decide(A, i4, item(A, i4)["revision"], None, "archive")
    expect("CONFLICT", imports.collected_decide, A, i4, "kept")
    print("OK 4 사용자 판별 잠금(장치 pending·removed noop) · 되돌리기 뒤 장치 state · 버림 ≠ 휴지통 · 버림 뒤 removed noop · "
          "되돌리기 행은 noop 재전송이 안 건드림 · 보관 항목 CONFLICT")

    # ── 5. 묶음 버림 · 일반 결정 한도 ──
    i5 = (await d.send("p5"))["target_id"]
    i6 = (await d.send("p6"))["target_id"]
    def gate_n():   # 일반 결정 한도가 세는 수(_daily_gate 와 같은 식)
        with db.tx() as c:
            return sum(c.execute(f"SELECT count(*) AS n FROM {t} WHERE user_id=%s AND {col} >= {db._KST_TODAY}"
                                 + "".join(f" AND {x}" for x in extra), (A,)).fetchone()["n"] for t, col, *extra in db._DAILY_SOURCES["decisions"])
    saved = dict(db.DAILY_LIMITS)
    db.DAILY_LIMITS.update(decisions=gate_n())   # 지금 수 그대로 — 판별 이력이 세지면 아래 관문이 막힌다
    try:
        r = await web("POST", "/api/collected/drop", {"ids": [i5, i6, i5, i3, "i_nothere1234"], "state": "dropped"})
        assert r.status_code == 200, r.text
        assert r.json() == {"dropped": [i5, i6], "skipped": [i3, "i_nothere1234"]}, r.json()
        with db.tx() as c:
            db._daily_gate(c, A, "decisions", adding=0)   # 판별 이력(묶음 버림 2건)은 결정 한도에 세지 않는다
    finally:
        db.DAILY_LIMITS.clear()
        db.DAILY_LIMITS.update(saved)
    r = await web("POST", "/api/collected/drop", {"ids": [i5] * 201, "state": "dropped"})
    assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID"
    r = await web("POST", "/api/collected/drop", {"ids": [i5], "state": "kept"})
    assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID"
    print("OK 5 묶음 버림(중복 한 번 · skipped · 201 거절 · state dropped 만) · 결정 한도 미산입")

    # ── 6. 장치 판별 목록 ──
    r = await d.decisions()
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    j = r.json()
    got = [(x["item_id"], x["state"]) for x in j["decisions"]]
    assert got == [(i3, "dropped"), (iq, "dropped"), (i5, "dropped"), (i6, "dropped")], got   # 오래된 seq 부터   # i1 은 장치가 덮어 device · i4 는 사용자 판별 없음
    assert j["has_more"] is False and j["next_cursor"].isdigit() and all(x["decided_at"] for x in j["decisions"])
    assert set(j) == {"decisions", "next_cursor", "has_more"} and set(j["decisions"][0]) == {"item_id", "state", "decided_at"}
    j1 = (await d.decisions(limit="1")).json()
    assert [x["item_id"] for x in j1["decisions"]] == [i3] and j1["has_more"] is True
    j2 = (await d.decisions(since=j1["next_cursor"], limit="2")).json()
    assert [x["item_id"] for x in j2["decisions"]] == [iq, i5] and j2["has_more"] is True
    j3 = (await d.decisions(since=j["next_cursor"])).json()
    assert j3 == {"decisions": [], "next_cursor": j["next_cursor"], "has_more": False}, j3
    imports.collected_decide(A, i3, "pending")   # 되돌리기도 새 seq 로 실린다(PC 는 pending 을 무시)
    j4 = (await d.decisions(since=j["next_cursor"])).json()
    assert [(x["item_id"], x["state"]) for x in j4["decisions"]] == [(i3, "pending")], j4
    tb, db_dev, _ = setup_user(B, axes=False)   # 남의 장치 — 내 판별은 안 보인다
    assert (await Dev(tb, db_dev).decisions()).json()["decisions"] == []
    c2 = imports.device_connect(A, "합성 다른 PC")   # 같은 사용자의 다른 장치 — 그 장치가 올린 항목만
    assert (await d.decisions(token=c2["token"])).json()["decisions"] == []
    assert (await d.decisions(token="")).status_code == 401
    r = await d.decisions(since="abc")
    assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID"
    assert (await d.decisions(limit="0")).status_code == 400 and (await d.decisions(limit="201")).status_code == 400
    imports.device_revoke(A, c2["device"]["id"])
    assert (await d.decisions(token=c2["token"])).status_code == 401
    print("OK 6 장치 판별 목록(사용자 판별만 · seq 커서·has_more · 되돌리기 실림 · 남의·다른 장치 0 · 401·400)")

    # ── 7. 대화 op · 견본 · 계정 삭제 ──
    out = imports.collected_decide(A, i6, "kept", None, via="mcp")
    assert out["state"] == "kept" and hist(A, i6)[-1][1]["via"] == "mcp"
    assert main.collected_post_decide.__name__ in __import__("facade").OPS
    sample = json.loads((HERE / "ui" / "src" / "features" / "today" / "collected.sample.json").read_text(encoding="utf-8"))
    lst = (await web("GET", "/api/collected?state=kept")).json()
    full = next(p for p in lst["posts"] if p["id"] == i1)   # 축·ai·URL 이 다 있는 글
    bad = cmp(sample["list"], {**lst, "posts": [full]}, "list", exact=True)
    assert not bad, (bad, "collected.sample.json·features/today/collectedApi.ts 의 타입을 같이 고친다")
    dec = (await web("POST", f"/api/collected/{i6}/decide", {"state": "dropped", "expected_revision": item(A, i6)["revision"]})).json()
    assert not cmp(sample["decided"], dec, "decided", exact=True), cmp(sample["decided"], dec, "decided", exact=True)
    dr = (await web("POST", "/api/collected/drop", {"ids": [i1], "state": "dropped"})).json()
    assert not cmp(sample["dropped"], dr, "dropped", exact=True), dr
    with db.tx() as c:
        n = c.execute("SELECT count(*) AS n FROM collected_states WHERE user_id=%s", (A,)).fetchone()["n"]
    assert n >= 5
    db.user_delete(A)
    with db.tx() as c:
        assert c.execute("SELECT count(*) AS n FROM collected_states WHERE user_id=%s", (A,)).fetchone()["n"] == 0
    print("OK 7 대화 op(via mcp) · 화면 견본 대조(목록·판별·묶음 버림) · 계정 삭제가 판별 표를 지움")


def _counter(uid, bucket):
    with db.tx() as c:
        r = c.execute("SELECT COALESCE(sum(n), 0) AS n FROM import_counters WHERE user_id=%s AND bucket=%s", (uid, bucket)).fetchone()
    return int(r["n"])


def _job(jid):
    with db.tx() as c:
        return c.execute("SELECT kind, status, reason_code, terminal_at FROM jobs WHERE id=%s", (jid,)).fetchone()


def _data(uid, iid):
    with db.tx() as c:
        return c.execute("SELECT data FROM items WHERE user_id=%s AND id=%s", (uid, iid)).fetchone()["data"]


async def long_jobs(B):
    """10. 읽기 판 긴 요약 collected_long — 웹 접수 → 장치 임대·입력 → 결과(항목 ai_* 기록 + confirmed) · 실패 · 한도 · 스위치."""
    L = db.user_by_email(LONG)["id"]
    tok, dev_id, _ax = setup_user(L, axes=False)
    d = Dev(tok, dev_id)
    i1 = (await d.send("l1", ai={"grade": "signal", "summary": "합성 요약"}))["target_id"]
    i2 = (await d.send("l2"))["target_id"]
    hd = {"authorization": "Bearer " + tok}
    poll_saved = dict(imports.POLL_LIMITS)
    for k in imports.POLL_LIMITS:
        imports.POLL_LIMITS[k] = 100000
    new = lambda text: web("POST", "/api/jobs", {"kind": "collected_long", "text": text}, user=LONG)   # noqa: E731
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            async def lease(expect_id):
                r = await h.get("/api/device/jobs", params={"wait": 0, "kinds": "converse,collected_long"}, headers=hd)
                assert r.status_code == 200 and r.json()["kind"] == "collected_long" and r.json()["id"] == expect_id, r.text
                gen = r.json()["lease"]["generation"]
                r = await h.get(f"/api/device/jobs/{expect_id}/input", params={"lease_generation": gen}, headers=hd)
                assert r.status_code == 200, r.text
                return gen, r.json()

            async def result(jid, b):
                return await h.post(f"/api/device/jobs/{jid}/result", content=json.dumps(b, ensure_ascii=False).encode("utf-8"),
                                    headers={**hd, "content-type": "application/json"})

            # 작업 CHECK 확장(schema.sql 뒤 _WIDEN_CHECKS)
            with db.tx() as c:
                defs = {r["conname"]: r["d"] for r in c.execute(
                    "SELECT conname, pg_get_constraintdef(oid) AS d FROM pg_constraint WHERE conrelid='jobs'::regclass "
                    "AND conname IN ('jobs_kind_check','jobs_reason_code_check')").fetchall()}
            assert "'collected_long'" in defs["jobs_kind_check"] and "'long-short'" in defs["jobs_reason_code_check"], defs

            # 접수 · 재사용(같은 id, 한도 미산입) · 인자 오류 · 남의·없는 항목 404
            r = await new(i1)
            assert r.status_code == 201, r.text
            j1 = r.json()["id"]
            r = await new(i1)
            assert r.status_code == 201 and r.json()["id"] == j1, r.text
            assert _counter(L, "job_collected_long") == 1, "재사용은 하루 한도에 세지 않는다"
            for bad in ("i_x", "합성 글자", "i_nothere0000"):
                r = await new(bad)
                assert r.status_code == (404 if bad.startswith("i_nothere") else 400), (bad, r.text)
            expect("NOT-FOUND", db.job_create, B, "collected_long", i1)   # 남의 항목(B 는 수집 글 오브젝트와 장치가 있다)
            expect("ARG-INVALID", db.job_create, L, "collected_long", i1, session_id=str(uuid.uuid4()))

            # kinds 없는 옛 폴, collected_long 을 밝히지 않은 폴은 임대받지 않는다(queued 그대로) · 모르는 이름은 버린다
            for params in ({"wait": 0}, {"wait": 0, "kinds": "converse,routine_ingest"}, {"wait": 0, "kinds": "collected_longx, ,nope"}):
                r = await h.get("/api/device/jobs", params=params, headers=hd)
                assert r.status_code == 204, (params, r.text)
            assert _job(j1)["status"] == "queued"

            # 임대 · 입력 = 항목 id · 실행 중에도 재사용
            gen, inp = await lease(j1)
            assert inp["text"] == i1, inp
            assert (await new(i1)).json()["id"] == j1

            # 결과 모양 오류(작업은 running 그대로)
            ok = {"lease_generation": gen, "input_version": 1, "result_version": str(uuid.uuid4()),
                  "collected_long": {"as_is": "지금 합성", "to_be": None, "ops": "운영 합성", "points": ["점 하나", "점 둘"]}, "model_meta": {}}
            cl = ok["collected_long"]
            for why, b in (("points 0", {**ok, "collected_long": {**cl, "points": []}}),
                           ("points 13", {**ok, "collected_long": {**cl, "points": ["점"] * 13}}),
                           ("point 301", {**ok, "collected_long": {**cl, "points": ["가" * 301]}}),
                           ("as_is 1001", {**ok, "collected_long": {**cl, "as_is": "가" * 1001}}),
                           ("url", {**ok, "collected_long": {**cl, "to_be": "합성 https://example.com/a"}}),
                           ("mail", {**ok, "collected_long": {**cl, "ops": "합성 a@example.com"}}),
                           ("path", {**ok, "collected_long": {**cl, "ops": "합성 ~/x"}}),
                           ("빈 글", {**ok, "collected_long": {**cl, "as_is": " "}}),
                           ("키 빠짐", {**ok, "collected_long": {k: v for k, v in cl.items() if k != "ops"}}),
                           ("키 더함", {**ok, "extra": 1}),
                           ("옛 꼴", {"lease_generation": gen, "input_version": 1, "result_version": str(uuid.uuid4()), "summary_text": "",
                                     "changes": [], "blocked": [], "text_map": [], "model_meta": {}})):
                r = await result(j1, b)
                assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", (why, r.text)
                assert "가가가" not in r.text and "example.com" not in r.text, ("오류에 값을 싣지 않는다", why)
            assert _job(j1)["status"] == "running"
            r = await result(j1, {**ok, "input_version": 2})
            assert r.status_code == 409 and r.json()["code"] == "JOB-VERSION", r.text
            r = await result(j1, {**ok, "lease_generation": gen + 1})
            assert r.status_code == 409 and r.json()["code"] == "JOB-LEASE", r.text

            # 판별(보관)된 항목에도 쓴다 · ai_* 넷만 · revision, 이력 불변 · null 은 그 키를 지운다
            imports.collected_decide(L, i1, "kept")
            with db.tx() as c:
                c.execute("UPDATE items SET data = data || '{\"ai_to_be\": \"옛 값\"}'::jsonb WHERE user_id=%s AND id=%s", (L, i1))
            rev0, h0 = item(L, i1)["revision"], hist(L, i1)
            r = await result(j1, ok)
            assert r.status_code == 200 and r.json() == {"status": "confirmed"}, r.text
            dat = _data(L, i1)
            assert dat["ai_as_is"] == "지금 합성" and dat["ai_ops"] == "운영 합성" and dat["ai_points"] == ["점 하나", "점 둘"], dat
            assert "ai_to_be" not in dat and dat["ai_summary"] == "합성 요약" and dat["ai_grade"] == "signal", dat
            assert item(L, i1)["revision"] == rev0 and hist(L, i1) == h0, "revision·이력 불변"
            assert cs(L, i1)["state"] == "kept", "판별 그대로"
            jj = _job(j1)
            assert jj["status"] == "confirmed" and jj["terminal_at"] is not None, jj
            st = db.job_get(L, j1)
            assert st["status"] == "confirmed" and "result" not in st, st
            with db.tx() as c:
                inp_t, res_t = db._tmp_names(c)
                assert not c.execute(f"SELECT 1 FROM {inp_t} WHERE job_id=%s", (j1,)).fetchone(), "임시 입력 정리"
            r = await result(j1, ok)
            assert r.status_code == 200 and r.json() == {"duplicate": True}, r.text
            web_post = next(p for p in (await web("GET", "/api/collected?state=kept", user=LONG)).json()["posts"] if p["id"] == i1)
            assert web_post["ai"]["as_is"] == "지금 합성" and web_post["ai"]["points"] == ["점 하나", "점 둘"], web_post

            # 끝난 뒤 다시 요청 = 새 작업 · 실패 코드(long-short) · 모르는 코드 400
            r = await new(i1)
            j2 = r.json()["id"]
            assert r.status_code == 201 and j2 != j1 and _counter(L, "job_collected_long") == 2
            gen2, _ = await lease(j2)
            r = await h.post(f"/api/device/jobs/{j2}/fail", json={"lease_generation": gen2, "reason_code": "long-nope"}, headers=hd)
            assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", r.text
            r = await h.post(f"/api/device/jobs/{j2}/fail", json={"lease_generation": gen2, "reason_code": "long-short"}, headers=hd)
            assert r.status_code == 200 and r.json() == {"status": "failed"}, r.text
            assert _job(j2)["reason_code"] == "long-short" and db.job_get(L, j2)["reason_code"] == "long-short"

            # 결과 전에 항목이 휴지통에 가면 쓰지 않고 failed(long-not-found) · 휴지통 항목 접수 404
            j3 = (await new(i2)).json()["id"]
            gen3, _ = await lease(j3)
            with db.tx() as c:
                db._trash_rows(c, L, "items", [i2], "move")
            r = await result(j3, {**ok, "lease_generation": gen3})
            assert r.status_code == 200 and r.json() == {"status": "failed", "reason_code": "long-not-found"}, r.text
            assert _job(j3)["reason_code"] == "long-not-found" and "ai_as_is" not in _data(L, i2)
            assert (await new(i2)).status_code == 404

            # 하루 한도(지금 3건) · 스위치 꺼짐 = 접수 503, 장치에 임대하지 않는다
            assert _counter(L, "job_collected_long") == 3
            imports.JOB_REQUEST_LIMITS["collected_long"] = 3
            try:
                r = await new(i1)
                assert r.status_code == 429 and r.json()["code"] == "JOB-QUOTA" and r.json().get("resume_at"), r.text
            finally:
                imports.JOB_REQUEST_LIMITS["collected_long"] = 60
            j4 = (await new(i1)).json()["id"]
            os.environ["CRM_COLLECTED_LONG_ENABLED"] = "0"
            try:
                r = await new(i1)
                assert r.status_code == 503 and r.json()["code"] == "SWITCH-OFF", r.text
                r = await h.get("/api/device/jobs", params={"wait": 0, "kinds": "collected_long"}, headers=hd)
                assert r.status_code == 204, ("꺼진 종류는 임대하지 않는다", r.text)
            finally:
                os.environ.pop("CRM_COLLECTED_LONG_ENABLED", None)
            await lease(j4)

        # MCP op collected_post_summarize(write, facade 전용) — 같은 작업(진행 중) 재사용 · 없는 항목 NOT-FOUND · 카탈로그와 등급표
        from mcp.client import Client
        import chat_mcp
        import facade
        cat = facade.load_catalog()
        assert (cat["ops"]["collected_post_summarize"]["tier"], cat["ops"]["collected_post_summarize"].get("direct")) == ("write", False)
        assert chat_mcp._PINNED_TIERS["collected_post_summarize"] == "write" and ("write", "collected_post_summarize") in chat_mcp.allowed_operations(cat)
        assert "collected_post_summarize 로 부른다" in main.INSTRUCTIONS
        saved_user = os.environ.get("CRM_DEV_USER")
        os.environ["CRM_DEV_USER"] = LONG
        try:
            async with Client(main.mcp) as c:
                assert "collected_post_summarize" not in {t.name for t in (await c.list_tools()).tools}, "facade 전용"
                res = await c.call_tool("write", {"op": "collected_post_summarize", "params": {"item_id": i1}})
                assert not res.is_error, res.content[0].text[:300]
                v = res.structured_content
                v = v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v
                if v is None:   # facade 는 결과를 글(JSON)로 돌려준다
                    v = json.loads(res.content[0].text)
                assert v == {"job_id": j4, "status": "running", "reason_code": None}, v
                bad = await c.call_tool("write", {"op": "collected_post_summarize", "params": {"item_id": "i_nothere0000"}})
                assert bad.is_error and "NOT-FOUND" in bad.content[0].text, bad.content[0].text[:200]
        finally:
            os.environ["CRM_DEV_USER"] = saved_user if saved_user is not None else MAIN
    finally:
        imports.POLL_LIMITS.clear()
        imports.POLL_LIMITS.update(poll_saved)
    print("OK 10 읽기 판 긴 요약(접수·재사용·404·한도·모양 오류·ai_* 기록과 revision 불변·confirmed·재전송·실패 코드·스위치 503·옛 폴 임대 없음·MCP op)")


def main_():
    db.init_schema()
    cleanup()
    for e in EMAILS:
        db.user_by_email(e)
    try:
        asyncio.run(run())
    finally:
        cleanup()
        db.close()
    print("ALL OK — test_collected_inbox")


if __name__ == "__main__":
    main_()
