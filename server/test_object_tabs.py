"""오브젝트 탭 시험(2026-11-18 오브젝트 탭 명세 1절) — 「나」 하위 탭 레이아웃의 오브젝트 탭 · 목록 보기 API.

실행: DATABASE_URL=postgresql://localhost/crm_test_objtab python3 server/test_object_tabs.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1. 레이아웃 — 오브젝트 없음 = 고정 6탭 · 적용한 사용자 오브젝트마다 obj:<key> 탭(사람·출처 앞, 만든 순) · 기준·결정·축 표준은 탭 아님
   · 옛 custom 탭 = 그 자리에서 펼침(쓰기 없음) · 보관 = 탭 빠짐 · 저장은 내 오브젝트 key 만(남의·없는 key = LAYOUT-INVALID) · 빠진 탭은 채움
2. 목록 보기 — 열(제목 + 필드 앞 5, 참조·AI 긴 필드 제외) · 상태 열(수집 글만) · 기본 정렬(첫 날짜 필드 내림차순, 없으면 수정 시각)
   · 열 정렬(오름·내림, 같은 값은 id) · select 칩 건수(전체 기준) · 상태 칩 · 제목 검색(%, _ 글자 그대로) · 50행 쪽 · 휴지통·보관 제외
   · 사용자 격리(남의 key = NOT-FOUND) · 인자 오류 · 웹 GET /api/me/objects/{key}(401·404·200)
"""
import asyncio
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_objtab). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ci-objtab@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402

MAIN, OTHER = "ci-objtab@example.com", "ci-objtab-other@example.com"
EMAILS = (MAIN, OTHER)
FIXED = ["summary", "principle", "decision", "axis", "person", "source"]
POST_FIELDS = [
    {"key": "channel", "label": "채널", "value_type": "select", "required": True, "options": list(imports.COLLECTED_CHANNELS)},
    {"key": "author_display", "label": "작성자", "value_type": "text"},
    {"key": "ai_as_is", "label": "AI as-is", "value_type": "text"},
    {"key": "posted_on", "label": "게시일", "value_type": "date"},
    {"key": "collected_on", "label": "수집일", "value_type": "date", "required": True},
    {"key": "ai_grade", "label": "AI 등급", "value_type": "select", "options": list(imports.COLLECTED_GRADES)},
    {"key": "ai_summary", "label": "AI 요약", "value_type": "text"},
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


def obj(uid, key, label, fields=()):
    p = db.definition_propose(uid, None, 0, {"key": key, "label": label, "semantic_kind": "collection", "fields": list(fields)})
    db.definition_apply(uid, p["object_id"], p["proposal_id"], 0)
    return p["object_id"]


def item(uid, oid, title, data, code=None):
    ev = db.item_propose(uid, oid, 1, None, 0, code, title, "", data, [])
    return db.item_decide(uid, ev["item_id"], 0, ev["proposal_id"], "apply")["id"]


def raw_item(uid, oid, title, data):
    """적용된 항목 한 행을 바로 넣는다 — 하루 제안 한도(100) 밖에서 쪽 나눔용 120건을 만든다."""
    iid = f"i_objtab_{abs(hash((oid, title))) % 10**12:012d}"
    with db.tx() as c:
        c.execute("INSERT INTO items (user_id, id, object_id, schema_revision, title, data, revision) VALUES (%s,%s,%s,1,%s,%s,1)",
                  (uid, iid, oid, title, db.Jsonb(data)))
    return iid


def tabs(uid):
    return db.layout_get(uid)["layout"]["pages"]["me"]["tabs"]


def page(tab_list):
    return {"tabs": tab_list, "regions": {"summary": [{"c": "kinds", "p": {}}]}}


def test_layout(U, O):
    assert db.DEFAULT_LAYOUT["pages"]["me"]["tabs"] == FIXED, "기본 = 고정 6탭(커스텀 탭 없음)"
    assert tabs(U) == FIXED, "오브젝트 없음 = 고정 6탭"
    po = obj(U, "collected_posts", "수집 글", POST_FIELDS)
    vo = obj(U, "verified_results", "확인된 결과")
    std = obj(U, "principles_x", "기준 표준")
    with db.tx() as c:   # 표준 기준 오브젝트(시드가 std_id 를 채운다) — 탭이 아니다
        c.execute("UPDATE object_defs SET std_id='std:principles' WHERE user_id=%s AND id=%s", (U, std))
    obj(O, "others_only", "남의 오브젝트")
    want = ["summary", "principle", "decision", "axis", "obj:collected_posts", "obj:verified_results", "person", "source"]
    assert tabs(U) == want, tabs(U)
    assert tabs(O) == FIXED[:4] + ["obj:others_only"] + FIXED[4:], "남의 오브젝트 탭은 안 보이고, 내 것만"
    # 저장 — 내 key 만 · 빠진 오브젝트 탭은 채운다 · 남의·없는 key 는 거절
    r = db.layout_set(U, page(["obj:verified_results", "source"] + FIXED[:5]), 0, page="me")
    saved = ["obj:verified_results", "obj:collected_posts", "source", "summary", "principle", "decision", "axis", "person"]
    assert r["layout"]["pages"]["me"]["tabs"] == saved, "빠진 탭 = 사람·출처 가운데 앞선 것(출처) 바로 앞"
    expect("LAYOUT-INVALID", db.layout_set, U, page(FIXED + ["obj:others_only"]), 1, page="me")
    expect("LAYOUT-INVALID", db.layout_set, U, page(FIXED + ["obj:principles_x"]), 1, page="me")
    expect("LAYOUT-INVALID", db.layout_set, U, page(FIXED + ["custom"]), 1, page="me")
    assert db.layout_get(U)["version"] == 1, "거절은 저장하지 않는다"
    # 보관 = 탭 빠짐(쓰기 없음) · 다시 살리면 저장해 둔 자리로
    db.definition_archive(U, vo)
    assert tabs(U) == [t for t in saved if t != "obj:verified_results"], tabs(U)
    db.definition_restore(U, vo)
    assert tabs(U) == saved, tabs(U)
    # 옛 custom 탭(오브젝트 탭 전 저장값) — 그 자리에서 펼친다. 저장값은 그대로(읽기는 쓰지 않는다)
    old = {"v": 2, "pages": {"me": {"tabs": ["custom", "summary", "principle", "decision", "axis", "person", "source"],
                                    "regions": {"summary": [{"c": "recent", "p": {}}]}}}}
    with db.tx() as c:
        c.execute("UPDATE page_layouts SET layout=%s WHERE user_id=%s", (db.Jsonb(old), U))
    got = db.layout_get(U)["layout"]["pages"]["me"]
    assert got["tabs"] == ["obj:collected_posts", "obj:verified_results"] + FIXED and got["regions"]["summary"] == [{"c": "recent", "p": {}}], got
    with db.tx() as c:
        assert c.execute("SELECT layout FROM page_layouts WHERE user_id=%s", (U,)).fetchone()["layout"] == old
    v1 = {"v": 1, "tabs": ["summary", "principle", "decision", "axis", "custom", "person", "source"], "blocks": {"summary": ["kinds"]}}
    with db.tx() as c:
        c.execute("UPDATE page_layouts SET layout=%s WHERE user_id=%s", (db.Jsonb(v1), U))
    assert tabs(U) == want, "v1 의 custom 도 펼친다"
    # 되돌리기 = 기본 + 오브젝트 탭
    assert db.layout_reset(U)["layout"]["pages"]["me"]["tabs"] == want
    print("OK 1 레이아웃 오브젝트 탭(만든 순·사람 앞·표준 제외·격리·custom 펼침·보관·저장 검사)")
    return po


async def test_list(U, O, po):
    with db.tx() as c:   # 휴지통 스위치 — trash_move 가 쓰려면 켜져 있어야 한다
        c.execute("INSERT INTO org_features (feature, enabled) VALUES ('trash', true) ON CONFLICT (feature) DO UPDATE SET enabled=true")
    ch = imports.COLLECTED_CHANNELS
    ids = []
    for i in range(120):
        d = {"channel": ch[i % 3], "collected_on": "2026-11-10", "author_display": f"작성자 {i % 7}", "ai_as_is": "긴 글",
             "ai_summary": f"요약 {i}", "ai_points": ["a"]}
        if i % 10:   # 열 개 중 하나는 게시일 없음(정렬에서 맨 뒤)
            d["posted_on"] = f"2026-{1 + i % 12:02d}-{1 + i % 28:02d}"
        if i % 4 == 0:
            d["ai_grade"] = "signal"
        ids.append(raw_item(U, po, f"합성 글 {i:03d}" + (" 100%_진짜" if i == 7 else ""), d))
    imports.collected_decide(U, ids[1], "kept", db.item_get(U, ids[1])["revision"])
    imports.collected_decide(U, ids[2], "dropped", db.item_get(U, ids[2])["revision"])
    imports.collected_decide(U, ids[3], "kept", db.item_get(U, ids[3])["revision"])
    db.trash_move(U, "item", ids[4], db.item_get(U, ids[4])["revision"])
    db.item_decide(U, ids[5], db.item_get(U, ids[5])["revision"], None, "archive")
    live = 118

    r = db.object_list(U, "collected_posts")
    assert r["object"]["key"] == "collected_posts" and r["object"]["label"] == "수집 글"
    assert [c["key"] for c in r["columns"]] == ["channel", "author_display", "posted_on", "collected_on", "ai_grade"], r["columns"]
    assert r["has_state"] is True and r["states"] == {"pending": live - 3, "kept": 2, "dropped": 1}, r["states"]
    assert r["sort"] == {"key": "posted_on", "dir": "desc"}, "기본 정렬 = 첫 날짜 필드 내림차순"
    assert r["total"] == live and len(r["rows"]) == 50 and r["next_cursor"] == "50"
    row = r["rows"][0]
    assert set(row) == {"id", "code", "title", "revision", "updated_at", "data", "state"}
    assert set(row["data"]) <= {"channel", "author_display", "posted_on", "collected_on", "ai_grade"}, "열 밖 값(AI 긴 필드 등)은 싣지 않는다"
    ps = [x["data"].get("posted_on") for x in r["rows"]]
    assert ps == sorted(ps, reverse=True) and ps[0] == "2026-12-28", ps[:3]
    # 쪽 넘김 — 겹침·빠짐 없음, 게시일 없는 글은 맨 뒤
    seen = [x["id"] for x in r["rows"]]
    cur = r["next_cursor"]
    while cur:
        n = db.object_list(U, "collected_posts", cursor=cur)
        seen += [x["id"] for x in n["rows"]]
        last = n
        cur = n["next_cursor"]
    assert len(seen) == live == len(set(seen)) and ids[4] not in seen and ids[5] not in seen, "휴지통·보관 제외"
    assert all("posted_on" not in x["data"] for x in last["rows"][-12:]), "날짜 없음 = 맨 뒤(NULLS LAST)"
    # 정렬 — 제목 오름(기본 방향) · 내림 · 같은 결과 반복(결정적)
    t = db.object_list(U, "collected_posts", sort="title")
    assert t["sort"] == {"key": "title", "dir": "asc"} and t["rows"][0]["title"] == "합성 글 000"
    t2 = db.object_list(U, "collected_posts", sort="title", direction="desc")
    assert t2["rows"][0]["title"] == "합성 글 119"
    assert db.object_list(U, "collected_posts", sort="author_display")["rows"] == db.object_list(U, "collected_posts", sort="author_display")["rows"]
    st = db.object_list(U, "collected_posts", sort="state", direction="asc")
    assert st["rows"][0]["state"] == "dropped", "상태 열 정렬(글자 순 dropped < kept < pending)"
    # 칩 — select 필드마다 값별 건수(전체 기준, 거르기와 무관) · 선택지 순서
    fl = {f["key"]: f for f in r["filters"]}
    assert list(fl) == ["channel", "ai_grade"]
    chn = {v["value"]: v["n"] for v in fl["channel"]["values"]}
    assert [v["value"] for v in fl["channel"]["values"]] == list(ch) and sum(chn.values()) == live and chn["threads"] == 0, chn
    assert {v["value"]: v["n"] for v in fl["ai_grade"]["values"]}["signal"] == 29, "0,4,…,116 = 30 에서 휴지통(i=4) 빼고 29"
    # 필터 — 채널 · 상태 · 두 개 함께 · 칩 건수는 그대로
    f1 = db.object_list(U, "collected_posts", filters={"channel": "reddit"})
    assert f1["total"] == chn["reddit"] and all(x["data"]["channel"] == "reddit" for x in f1["rows"]) and f1["filters"] == r["filters"]
    k = db.object_list(U, "collected_posts", state="kept")
    assert k["total"] == 2 and {x["id"] for x in k["rows"]} == {ids[1], ids[3]} and all(x["state"] == "kept" for x in k["rows"])
    both = db.object_list(U, "collected_posts", filters={"channel": ch[1]}, state="kept")
    assert [x["id"] for x in both["rows"]] == [ids[1]], both
    # 검색 — 제목, 대소문자·와일드카드 글자 그대로(%·_ 는 글자)
    assert [x["id"] for x in db.object_list(U, "collected_posts", q="100%_")["rows"]] == [ids[7]]
    assert db.object_list(U, "collected_posts", q="%")["total"] == 1, "% 는 모든 글이 아니라 글자 %"
    assert db.object_list(U, "collected_posts", q="합성 글 11")["total"] == 10
    # 날짜 필드 없는 오브젝트 = 수정 시각 내림차순 · 상태 없음
    vo_list = db.object_list(U, "verified_results")
    assert vo_list["sort"] == {"key": "updated_at", "dir": "desc"} and vo_list["has_state"] is False and vo_list["states"] is None
    vo = vo_list["object"]["id"]
    a, b = raw_item(U, vo, "먼저", {}), raw_item(U, vo, "나중", {})
    assert [x["id"] for x in db.object_list(U, "verified_results")["rows"]] == [b, a] and "state" not in db.object_list(U, "verified_results")["rows"][0]
    # 격리·없는 key·표준 기준 = NOT-FOUND · 인자 오류
    expect("NOT-FOUND", db.object_list, U, "others_only")
    expect("NOT-FOUND", db.object_list, O, "collected_posts")
    expect("NOT-FOUND", db.object_list, U, "principles_x")
    expect("NOT-FOUND", db.object_list, U, "none_such")
    for kw in ({"sort": "ai_nope"}, {"direction": "up"}, {"filters": {"author_display": "x"}}, {"filters": {"nope": "x"}},
               {"state": "maybe"}, {"cursor": "-1"}, {"cursor": "abc"}, {"q": "가" * 201}):
        expect("ARG-INVALID", db.object_list, U, "collected_posts", **kw)
    expect("ARG-INVALID", db.object_list, U, "verified_results", state="kept")
    # 웹 — 401 · 404 · 200(쿼리 f.<key>)
    site = main.site
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        site.dev, site.dev_user = False, ""
        assert (await h.get("/api/me/objects/collected_posts")).status_code == 401
        site.dev, site.dev_user = True, MAIN
        w = await h.get("/api/me/objects/collected_posts", params={"f.channel": "reddit", "state": "kept", "sort": "title", "dir": "desc"})
        assert w.status_code == 200 and w.headers.get("cache-control") == "no-store", w.text
        assert w.json() == db.object_list(U, "collected_posts", "title", "desc", "", {"channel": "reddit"}, "kept"), "웹 = db"
        assert (await h.get("/api/me/objects/others_only")).status_code == 404
        assert (await h.get("/api/me/objects/collected_posts", params={"sort": "nope"})).status_code == 400
    print("OK 2 목록 보기(열·상태·정렬·칩·필터·검색·쪽·휴지통·보관·격리·웹)")


def main_():
    db.init_schema()
    cleanup()
    U, O = (db.user_by_email(e)["id"] for e in EMAILS)
    try:
        po = test_layout(U, O)
        asyncio.run(test_list(U, O, po))
    finally:
        cleanup()
        db.close()
    print("ALL OK — test_object_tabs")


if __name__ == "__main__":
    main_()
