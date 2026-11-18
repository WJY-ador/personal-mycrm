"""구조 추천, 자동 분류 화면 API 시험(2026-11-18 구조추천 명세 6.5) — 웹 경로(server/web.py)만. 판정, 건수 정본은 test_route.py, test_route_flow.py.

실행: DATABASE_URL=postgresql://localhost/crm_test_route_screen_20261118 python3 server/test_route_screen.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
시험 자료는 전부 가짜 문장이다.

1. 규칙 문장 — route 를 사람 말로(결정적, record 단위, heading 단위, 조건 없음)
2. 추천 칸 GET /api/structure/reco — 401, 카드(이름, 필드, 담을 규칙 문장, 견본 3건, 채워질 건수, 분류 못 할 건수), route 없는 초안, 견본 키 대조(reco.sample.json)
3. 버튼 셋 POST /api/structure/drafts/{rename|discard|apply} — Origin 403, 모양 400, 이름 고치기(필드, 규칙 그대로, 새 초안 ID), 바뀐 초안 CONFLICT,
   빼기, 적용(채워짐 route_sync, 오브젝트 탭 머리 건수 = /api/state definitions route_counts, 목록 auto_routed)
4. 항목 페이지 — GET /api/route/item(근거 원문 = 단위 구간 그대로, 태그 글자 그대로), 고치기 ROUTE-LOCKED, POST /api/route/exclude(확인 뒤 빼기), 남의 항목
5. 나 탭 요약 GET /api/structure/hint — route 초안 있을 때, 없을 때, 안 붙은 기록 30편(줄 없음)과 31편(줄 있음) = route.profile suggest
6. 옛 PC 앱 보호 — 구조 추천 op 3개의 카드 결과는 다음 턴 approval_outcomes 에 싣지 않는다(webchat.OUTCOME_SKIP_OPS)
   (태그 이스케이프 렌더, 고치기 숨김, 색인 두 묶음은 화면 시험: ui/src/features/defs/Reco.test.tsx, me/RouteItem.test.tsx, objects 색인 시험)
"""
import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_route_screen_20261118). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "route-screen@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_SESSION_SECRET"] = "route-screen-test-secret"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
import route  # noqa: E402
import web  # noqa: E402

MAIN, OTHER, HINT = "route-screen@example.com", "route-screen-other@example.com", "route-screen-hint@example.com"
SRC = "세션 정리"
XSS = '<img src=x onerror="alert(1)"><script>alert(2)</script>'
SAMPLE = json.loads((HERE / "ui" / "src" / "features" / "defs" / "reco.sample.json").read_text(encoding="utf-8"))
ORIGIN = {"origin": PUBLIC}

PIVOT_DEF = {"key": "pivots", "label": "피벗", "semantic_kind": "event",
             "fields": [{"key": "happened_on", "label": "날짜", "value_type": "date", "required": True},
                        {"key": "where_", "label": "어디서", "value_type": "text", "required": True},
                        {"key": "decision", "label": "결정", "value_type": "text", "required": True},
                        {"key": "note", "label": "메모", "value_type": "text"}],
             "policy": {"route": {"v": 1, "unit": "record", "match": {"source": SRC, "title_like": "P#. *"},
                                  "require": {"labels": ["어디서", "결정"]}, "title": {"from": "title"},
                                  "fields": {"happened_on": {"from": "record_date"}, "where_": {"from": "label", "label": "어디서"},
                                             "decision": {"from": "label", "label": "결정"}}}}}
NOTE_DEF = {"key": "reading_notes", "label": "읽은 메모", "semantic_kind": "collection",
            "fields": [{"key": "memo", "label": "메모", "value_type": "text"}]}


def ok(msg):
    print(f"OK — {msg}", flush=True)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", ([MAIN, OTHER, HINT],)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def pivot(where, decision="입력 담당부터 정한다", drop=False):
    return f"**어디서** — {where}\n" + ("" if drop else f"**결정** — {decision}\n")


def add(uid, title, body, source=SRC):
    return db.record_add(uid, title, body, source=source)["id"]


def keys_in(sample, real, where):
    """견본 키 ⊆ 실제 키(중첩 dict, 목록은 첫 원소끼리)."""
    if isinstance(sample, dict):
        assert isinstance(real, dict), where
        miss = set(sample) - set(real)
        assert not miss, (where, miss)
        for k, v in sample.items():
            keys_in(v, real[k], f"{where}.{k}")
    elif isinstance(sample, list) and sample and real:
        keys_in(sample[0], real[0], where + "[0]")


# ── 1 ──

def test_rule_text():
    nr = route.check_route(PIVOT_DEF["policy"]["route"], PIVOT_DEF["fields"])
    t = web.route_rule_text(nr)
    assert t == "출처가 세션 정리이고 제목이 P숫자. 로 시작하고 라벨 2개(어디서, 결정)가 다 있는 기록, 기록 하나가 항목 하나", t
    assert web.route_rule_text(nr) == t, "결정적"
    ce = route.check_route({"v": 1, "unit": "heading", "match": {"source": SRC, "heading_like": "CE-#-#-#-#. *"}, "title": {"from": "heading"}}, [])
    assert web.route_rule_text(ce) == "출처가 세션 정리인 기록 안에서 머리 줄이 CE-숫자-숫자-숫자-숫자. 로 시작하는 절 하나가 항목 하나", web.route_rule_text(ce)
    hd = route.check_route({"v": 1, "unit": "record", "match": {"title_like": "주간 회고"}, "require": {"headings": ["상황", "내 판단"]}}, [])
    assert web.route_rule_text(hd) == "제목이 주간 회고 와 같고 머리 2개(상황, 내 판단)가 다 있는 기록, 기록 하나가 항목 하나", web.route_rule_text(hd)
    assert web.route_rule_text(None) == "" and web.route_rule_text({"unit": "x"}) == ""
    assert web._rule_from({"from": "section", "heading": "상황"}) == "머리 상황 아래 글" and web._rule_from({"from": "key", "key": "내 선택"}) == "키 내 선택"
    ok("규칙 문장(record 단위 = 명세 예문 꼴, heading 단위, 머리 조건, 꼴 아님 = 빈 글)")


# ── 2~4 ──

async def test_screen(uid, other):
    r_ok = [add(uid, f"P{i}. 가짜 피벗 {i}", pivot(f"가짜 팀 회의 {i}")) for i in (1, 2, 3)]
    r_xss = add(uid, "P9. 태그가 든 피벗", pivot(XSS))
    r_part = add(uid, "P4. 가짜 일부", pivot("가짜 회의 4", drop=True))
    pv = db.definition_propose(uid, None, 0, PIVOT_DEF)
    nt = db.definition_propose(uid, None, 0, NOTE_DEF)
    site = main.site
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        site.dev, site.dev_user = False, ""
        for path in ("/api/structure/reco", "/api/structure/hint", "/api/route/item?id=x"):
            assert (await h.get(path)).status_code == 401, path
        assert (await h.post("/api/route/exclude", json={}, headers=ORIGIN)).status_code == 401
        site.dev, site.dev_user = True, MAIN

        # 2. 추천 칸
        w = await h.get("/api/structure/reco")
        assert w.status_code == 200 and w.headers.get("cache-control") == "no-store", w.text
        reco = w.json()
        keys_in(SAMPLE, reco, "reco")
        assert reco["ask"] == "내 기록을 보고 구조를 추천해 줘" and reco["suggest"] is False and reco["unattached"] == 5, reco
        by = {d["object_id"]: d for d in reco["drafts"]}
        assert set(by) == {pv["object_id"], nt["object_id"]}
        c = by[pv["object_id"]]
        assert (c["label"], c["key"], c["proposal_id"], c["base_revision"], c["has_route"]) == ("피벗", "pivots", pv["proposal_id"], 0, True), c
        assert (c["would_fill"], c["partial"], len(c["samples"])) == (4, 1, 3), c
        assert c["rule"].startswith("출처가 세션 정리이고 제목이 P숫자. 로 시작하고"), c["rule"]
        assert [(f["label"], f["from"]) for f in c["fields"]] == [("날짜", "기록 날짜"), ("어디서", "라벨 어디서"), ("결정", "라벨 결정"), ("메모", "")]
        bodies = {r: db.record_get(uid, r)["body"] for r in r_ok + [r_xss]}
        for s in c["samples"]:
            assert s["record_id"] in bodies and bodies[s["record_id"]].startswith(s["quote"]) and len(s["quote"]) <= 200, s
            assert s["title"] == db.record_get(uid, s["record_id"])["title"]
        n = by[nt["object_id"]]
        assert (n["has_route"], n["rule"], n["would_fill"], n["samples"], n["fields"][0]["from"]) == (False, "", 0, [], ""), n
        ok("추천 칸 GET — 401, no-store, 카드(이름, 필드와 뽑는 곳, 규칙 문장, 견본 3건 = 원문 앞, 채워질 4, 분류 못 할 1), route 없는 초안, 견본 키 ⊆ 실제")

        # 3. 버튼 셋
        base = "/api/structure/drafts/"
        assert (await h.post(base + "rename", json={"object_id": pv["object_id"]})).status_code == 403, "Origin 없음"
        assert (await h.post(base + "rename", json={"object_id": pv["object_id"]}, headers=ORIGIN)).status_code == 400
        assert (await h.post(base + "apply", json={"object_id": pv["object_id"], "proposal_id": pv["proposal_id"], "expected_revision": True},
                             headers=ORIGIN)).status_code == 400, "bool 은 정수가 아니다"
        assert (await h.post(base + "nope", json={}, headers=ORIGIN)).status_code == 404
        w = await h.post(base + "rename", json={"object_id": pv["object_id"], "proposal_id": pv["proposal_id"], "expected_revision": 0, "label": "  전환점 "},
                         headers=ORIGIN)
        assert w.status_code == 200, w.text
        new_pid = w.json()["proposal_id"]
        assert new_pid != pv["proposal_id"]
        d = db.definitions(uid, [pv["object_id"]])[0]["proposal"]
        assert d["proposal_id"] == new_pid and d["definition"]["label"] == "전환점" and d["definition"]["key"] == "pivots"
        assert d["definition"]["policy"]["route"] == pv["definition"]["policy"]["route"] and d["definition"]["fields"] == pv["definition"]["fields"], "이름만 바뀐다"
        w = await h.post(base + "rename", json={"object_id": pv["object_id"], "proposal_id": pv["proposal_id"], "expected_revision": 0, "label": "다른 이름"},
                         headers=ORIGIN)
        assert w.status_code == 400 and w.json()["code"] == "CONFLICT", w.text
        w = await h.post(base + "rename", json={"object_id": pv["object_id"], "proposal_id": new_pid, "expected_revision": 0, "label": "  "}, headers=ORIGIN)
        assert w.status_code == 400 and w.json()["code"] == "ARG-INVALID", w.text
        w = await h.post(base + "discard", json={"object_id": nt["object_id"], "proposal_id": nt["proposal_id"]}, headers=ORIGIN)
        assert w.status_code == 200 and w.json()["deleted"] is True, w.text
        assert [x["object_id"] for x in (await h.get("/api/structure/reco")).json()["drafts"]] == [pv["object_id"]]
        assert (await h.get("/api/structure/hint")).json() == {"show": True}, "route 초안이 있으면 줄이 보인다"
        w = await h.post(base + "apply", json={"object_id": pv["object_id"], "proposal_id": new_pid, "expected_revision": 0}, headers=ORIGIN)
        assert w.status_code == 200, w.text
        assert w.json()["route_sync"]["created"] == 4 and w.json()["route_sync"]["partial"] == 1, w.json()["route_sync"]
        st = (await h.get("/api/state")).json()
        dd = next(x for x in st["definitions"] if x["id"] == pv["object_id"])
        assert dd["label"] == "전환점" and dd["policy"]["route"] and dd["route_counts"] == {"routed": 4, "partial": 1, "excluded": 0}, dd
        so = next(x for x in st["structure"]["objects"] if x["id"] == pv["object_id"])
        assert so["origin"] == "custom", "사용자가 만든 오브젝트 = 커스텀 묶음"
        items = [i for i in st["items"] if i["object_id"] == pv["object_id"]]
        assert len(items) == 4 and all(i["auto_routed"] and i["route_source"]["record_id"] in bodies for i in items)
        assert (await h.get("/api/structure/reco")).json()["drafts"] == [] and (await h.get("/api/structure/hint")).json() == {"show": False}
        lst = (await h.get("/api/me/objects/pivots")).json()
        assert lst["total"] == 4 and all(r["auto_routed"] for r in lst["rows"])
        ok("버튼 셋 — Origin 403, 모양 400, 없는 op 404, 이름 고치기(이름만, 새 초안 ID, 낡은 초안 CONFLICT, 빈 이름), 빼기, 적용(채움 4, 머리 건수, 목록 표시, 커스텀)")

        # 4. 항목 페이지
        x = next(i for i in items if i["route_source"]["record_id"] == r_xss)
        w = await h.get("/api/route/item", params={"id": x["id"]})
        assert w.status_code == 200 and w.headers.get("cache-control") == "no-store"
        info = w.json()["item"]
        assert info["text"] == bodies[r_xss] and XSS in info["text"] and info["record_title"] == "P9. 태그가 든 피벗", info
        assert "application/json" in w.headers["content-type"], "글자는 JSON 문자열로만(화면이 글자로 그린다)"
        assert (await h.get("/api/route/item", params={"id": "i_nope"})).json() == {"item": None}
        w = await h.post("/api/item/edit", json={"item_id": x["id"], "expected_revision": x["revision"], "title": "고친 제목", "body": ""}, headers=ORIGIN)
        assert w.status_code == 400 and w.json()["code"] == "ROUTE-LOCKED", w.text
        w = await h.post("/api/trash/move", json={"kind": "item", "id": x["id"], "expected_revision": x["revision"]}, headers=ORIGIN)
        assert w.status_code >= 400 and w.json()["code"] == "ROUTE-LOCKED", w.text
        assert (await h.post("/api/route/exclude", json={"item_id": x["id"], "expected_revision": x["revision"]})).status_code == 403
        assert (await h.post("/api/route/exclude", json={"item_id": x["id"]}, headers=ORIGIN)).status_code == 400
        w = await h.post("/api/route/exclude", json={"item_id": x["id"], "expected_revision": x["revision"] + 5}, headers=ORIGIN)
        assert w.status_code == 400 and w.json()["code"] == "CONFLICT", w.text
        site.dev_user = OTHER
        w = await h.post("/api/route/exclude", json={"item_id": x["id"], "expected_revision": x["revision"]}, headers=ORIGIN)
        assert w.status_code == 400 and w.json()["code"] == "ARG-INVALID", "남의 항목 = 자동 분류 항목이 아니라고 답한다(같은 모양)"
        assert (await h.get("/api/route/item", params={"id": x["id"]})).json() == {"item": None}, "남의 근거 원문은 안 보인다"
        site.dev_user = MAIN
        w = await h.post("/api/route/exclude", json={"item_id": x["id"], "expected_revision": x["revision"]}, headers=ORIGIN)
        assert w.status_code == 200 and w.json()["state"] == "excluded" and w.json()["record_id"] == r_xss, w.text
        assert (await h.post("/api/route/exclude", json={"item_id": x["id"], "expected_revision": x["revision"]}, headers=ORIGIN)).json()["code"] == "ARG-INVALID"
        st = (await h.get("/api/state")).json()
        assert next(d for d in st["definitions"] if d["id"] == pv["object_id"])["route_counts"] == {"routed": 3, "partial": 1, "excluded": 1}
        assert x["id"] not in {i["id"] for i in st["items"]} and db.record_get(uid, r_xss)["body"] == bodies[r_xss], "원문은 그대로"
        ok("항목 페이지 — 근거 원문(단위 구간 그대로, 태그 글자 그대로, JSON), 고치기, 삭제 ROUTE-LOCKED, 빼기(Origin, 모양, CONFLICT, 남의 것, 두 번), 건수")
    assert other and r_part


# ── 5 ──

async def test_hint(hid):
    site = main.site
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
        site.dev, site.dev_user = True, HINT
        assert (await h.get("/api/structure/hint")).json() == {"show": False}, "기록 없음"
        for i in range(route.SUGGEST_MIN):
            add(hid, f"가짜 메모 {i}", f"가짜 본문 {i}")
        assert route.profile(hid)["suggest"] is False and (await h.get("/api/structure/hint")).json() == {"show": False}, "30편 = 줄 없음"
        rid = add(hid, "가짜 메모 끝", "가짜 본문 끝")
        assert route.profile(hid)["suggest"] is True and (await h.get("/api/structure/hint")).json() == {"show": True}, "31편 = 줄 있음"
        db.trash_move(hid, "record", rid)
        assert route.profile(hid)["suggest"] is False and (await h.get("/api/structure/hint")).json() == {"show": False}, "휴지통 = 대상 밖"
        # 자동 분류된 기록은 안 붙은 기록이 아니다 — 31편 가운데 1편이 오브젝트에 담기면 30편(둘 다 줄 없음)
        add(hid, "P1. 담길 피벗", pivot("가짜 회의"))
        assert route.profile(hid)["suggest"] is True and (await h.get("/api/structure/hint")).json() == {"show": True}
        p = db.definition_propose(hid, None, 0, PIVOT_DEF)
        db.definition_apply(hid, p["object_id"], p["proposal_id"], 0)
        assert route.profile(hid)["unattached"]["count"] == route.SUGGEST_MIN
        assert route.profile(hid)["suggest"] is False and (await h.get("/api/structure/hint")).json() == {"show": False}, "자동 분류 = 붙은 기록"
        p = db.definition_propose(hid, None, 0, {**NOTE_DEF, "key": "plain_notes"})
        assert (await h.get("/api/structure/hint")).json() == {"show": False}, "route 없는 초안은 줄을 켜지 않는다"
        route.draft_discard(hid, p["object_id"], p["proposal_id"])
        p = db.definition_propose(hid, None, 0, {**PIVOT_DEF, "key": "pivots_two"})
        assert (await h.get("/api/structure/hint")).json() == {"show": True}, "route 초안 = 줄 있음"
    ok("나 탭 요약 한 줄 — 기록 없음, 30편 없음, 31편 있음(= profile suggest), 휴지통 제외, 자동 분류된 기록 = 붙음, route 없는 초안 없음, route 초안 있음")


# ── 6 ──

def test_outcome_skip(uid):
    """옛 PC 앱(0.1.7 이하) 보호 — 구조 추천 op 3개의 확정, 취소 카드 결과는 다음 턴 approval_outcomes 에 없다. 다른 op 결과는 그대로.
    뺀 행은 100개 상한 자리를 차지하지 않는다(SQL 에서 거른다)."""
    from unittest.mock import patch
    import webchat
    dev = "is_shot_device"
    sid, tid = webchat._id("cs"), webchat._id("ct")
    with db.tx() as c:
        c.execute("INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version,status) "
                  "VALUES (%s,%s,%s,'claude','synthetic-model',%s,2,'active')", (sid, uid, dev, "grant-" + sid[3:]))
        c.execute("INSERT INTO chat_turns (id,session_id,client_turn_id,status,ended_at) VALUES (%s,%s,'synthetic-turn','done',now())", (tid, sid))
        rows = [("record_edit", "confirmed", "decide")] + [("item_route_exclude", "confirmed", "decide"), ("item_route_include", "cancelled", "decide"),
                                                           ("definition_draft_discard", "confirmed", "decide")] * 40 + [("trash_restore", "cancelled", "decide")]
        ids = {}
        for i, (op, st, kind) in enumerate(rows):
            aid = webchat._id("ca")
            ids.setdefault(op, []).append(aid)
            c.execute("INSERT INTO chat_approvals (id,user_id,session_id,turn_id,op,params,preview,state,kind,expires_at,finished_at) "
                      "VALUES (%s,%s,%s,%s,%s,'{}','{}',%s,%s,clock_timestamp(),clock_timestamp()+make_interval(secs => %s))",
                      (aid, uid, sid, tid, op, st, kind, i))
    assert webchat.OUTCOME_SKIP_OPS == {"item_route_exclude", "item_route_include", "definition_draft_discard"}
    assert webchat.OUTCOME_SKIP_OPS <= webchat.CHAT_CARD_OPS, "카드 자체는 그대로 만든다"
    with patch("webchat._active_devices", return_value={dev}), patch("webchat._require_consumed_session_consent"):
        turn = webchat.turn_create(uid, sid, "가짜 다음 턴", "route-screen-next", connected=lambda _d: True, capable=lambda _s: True)
    out = turn["approval_outcomes"]
    assert [o["op"] for o in out] == ["record_edit", "trash_restore"], out
    assert [o["id"] for o in out] == [ids["record_edit"][0], ids["trash_restore"][0]] and [o["status"] for o in out] == ["confirmed", "cancelled"]
    ok("옛 앱 보호 — 구조 추천 op 3개 결과(120행, 100개 상한 넘음)는 approval_outcomes 에서 빠지고, 그보다 오래된 다른 op 결과도 그대로 실린다")


def main_():
    db.init_schema()
    cleanup()
    uid, other, hid = (db.user_by_email(e)["id"] for e in (MAIN, OTHER, HINT))
    for u, n in ((uid, "가짜 화면"), (other, "다른 가짜"), (hid, "가짜 알림")):
        db.display_name_set(u, n)
    try:
        test_rule_text()
        asyncio.run(test_screen(uid, other))
        asyncio.run(test_hint(hid))
        test_outcome_skip(uid)
    finally:
        cleanup()
        db.close()
    print("ALL OK — test_route_screen")


if __name__ == "__main__":
    main_()
