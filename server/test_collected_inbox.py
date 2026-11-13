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

MAIN, OTHER = "ci-main@example.com", "ci-other@example.com"
EMAILS = (MAIN, OTHER)
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
        self.token, self.id, self.chain = token, dev_id, {}

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


async def run():
    A, B = db.user_by_email(MAIN)["id"], db.user_by_email(OTHER)["id"]
    tok, dev_id, ax = setup_user(A)
    d = Dev(tok, dev_id)
    lim = dict(imports.LIMITS)
    imports.LIMITS[("device", "minute", "request")] = (100000, None)
    imports.LIMITS[("user", "minute", "request")] = (100000, None)
    try:
        await body(A, B, d, ax)
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
    i4 = (await d.send("p4", state="dropped"))["target_id"]   # 장치 dropped(enum 확장) = 버림, 휴지통 아님
    assert cs(A, i4)["state"] == "dropped" and item(A, i4)["trashed_at"] is None
    with db.tx() as c:   # 판별 표가 생기기 전에 올라온 항목 흉내 — 행을 지운다. 같은 내용 새 개정(noop)이 state 를 다시 채운다
        c.execute("DELETE FROM collected_states WHERE user_id=%s AND item_id=%s", (A, i3))
    assert (await d.send("p3", collected_on="2026-11-13"))["state"] == "noop" and cs(A, i3)["state"] == "pending"
    print("OK 1 장치 state 기록(pending·kept·dropped · noop 재전송이 빈 state 를 채움)")

    # ── 2. 웹 목록 ──
    r = await web("GET", "/api/collected?state=pending")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store", r.text
    j = r.json()
    assert j["ready"] is True and [p["id"] for p in j["posts"]] == [i3, i1] and j["counts"] == {"pending": 2, "kept": 1}, j
    p1 = j["posts"][1]
    assert p1["axes"] == [{"id": ax, "title": "합성 축"}] and p1["post_url"] == "https://www.linkedin.com/posts/synthetic-1", p1
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
    j = (await web("GET", "/api/collected?state=pending")).json()
    assert i3 not in [p["id"] for p in j["posts"]] and j["counts"]["pending"] == 0
    # 보관(archive)한 항목 = 판별 CONFLICT · 목록에서 빠짐
    db.item_decide(A, i4, item(A, i4)["revision"], None, "archive")
    expect("CONFLICT", imports.collected_decide, A, i4, "kept")
    print("OK 4 사용자 판별 잠금(장치 pending·removed noop) · 되돌리기 뒤 장치 state · 버림 ≠ 휴지통 · 보관 항목 CONFLICT")

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
    assert got == [(i3, "dropped"), (i5, "dropped"), (i6, "dropped")], got   # i1 은 장치가 덮어 device · i4 는 사용자 판별 없음
    assert j["has_more"] is False and j["next_cursor"].isdigit() and all(x["decided_at"] for x in j["decisions"])
    assert set(j) == {"decisions", "next_cursor", "has_more"} and set(j["decisions"][0]) == {"item_id", "state", "decided_at"}
    j1 = (await d.decisions(limit="1")).json()
    assert [x["item_id"] for x in j1["decisions"]] == [i3] and j1["has_more"] is True
    j2 = (await d.decisions(since=j1["next_cursor"], limit="2")).json()
    assert [x["item_id"] for x in j2["decisions"]] == [i5, i6] and j2["has_more"] is False
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
