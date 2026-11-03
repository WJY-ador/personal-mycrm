"""웹 시험 — PR① 「나」 홈(기존 데이터 화면): 기록 이어 받기 읽기 API GET /api/records · 홈 화면 정적 검사 (2026-10-21).

실행: DATABASE_URL=postgresql://localhost/crm_test_ux python3 server/test_web_home.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

A. /api/records — 401 · no-store · 기본(before 없음) = /api/state journal 과 같은 50편 · next_before 커서로 겹침·빠짐 없이 이어 받기 ·
   created 동률 블록(한 tx 의 now())이 페이지 경계에 걸쳐도 겹침·누락 0 · limit 끝값 · 틀린 before 400 · 남의 기록 0 · db.records 기본 호출 결과 불변.
B. app.html 정적 — 옛 쪽에 남은 「나」 접점(uiMount("me") · 미저장 보호 uiDirty · Setup 레이아웃 · 오늘 · 축 색 토큰).
   「나」 화면 자체(R2 2026-11-03 React)는 Vitest — server/ui/src/features/me/MeScreen·MeEdit·MeActs.test.tsx.
G. API 견본 대조(R2) — ui/src/shared/state.sample.json ⊆ /api/state · ui/src/features/me/me.sample.json = /api/me/stats·layout·journal·본문 미리보기.
C·D. 대화 서랍(PR ②-b B5 · ③-0.2)은 React(R3 2026-11-03) — server/ui/src/features/chat/store.test.ts·ChatRoot.test.tsx(Vitest).
   판단 검토(원문과 대조하기)도 React — server/ui/src/features/review/ReviewScreen.test.tsx.
F. 휴지통 PR-1 화면(node 실행 포함): 스위치 S.switches.trash + 새 탐색일 때만 [삭제]·Setup 「휴지통」 · 꺼짐 = 현행 · 기준 [남기기]+[삭제] · 후보 [삭제] 0 ·
   r4 §8 문구 · 휴지통 행(종류·제목·삭제 시각·복원 가능 기한)·더 보기·복원·영구 삭제·기한 이후 · 「반영 안 함」 한 표현 · 근거 이용 불가.
E. test_tools.py 에서 옮겨 온 app.html 정적 단언(③-0.2 A1~A5·B1~B4 — 문의 esc·계정 메뉴·구조 정의·LABELS·24h 화면·라이트 기본·셰이더·동의·재인증).
"""
import asyncio
import datetime as dt
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_ux). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "wh-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
from test_sample_shape import cmp as _cmp  # noqa: E402
import main  # noqa: E402

MAIN, OTHER, TIE, SAMPLE = "wh-main@example.com", "wh-other@example.com", "wh-tie@example.com", "wh-sample@example.com"
EMAILS = (MAIN, OTHER, TIE, SAMPLE)
N = 120   # 50 + 50 + 20


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def seed(uid, n, tag):
    """합성 기록 n 편 — created 를 1시간씩 과거로(하루 한도를 피해 직접 넣는다). 한 편은 지운 것."""
    now = dt.datetime.now(dt.timezone.utc)
    with db.tx() as c:
        for i in range(n):
            at = now - dt.timedelta(hours=i)
            c.execute("INSERT INTO records (id,user_id,title,body,created,author_kind,text_process,received_at) "
                      "VALUES (%s,%s,%s,%s,%s,'self','verbatim',%s)", (f"r_{tag}{i:03d}", uid, f"{tag} 기록 {i}", f"{tag} 본문 {i}", at, at))
        c.execute("UPDATE records SET deleted_at=now() WHERE user_id=%s AND id=%s", (uid, f"r_{tag}005"))


def seed_tie(uid):
    """동률 경계 — 앞 40편은 1분 간격(미래 쪽), 뒤 20편은 한 tx 의 기본 created(now() = tx 시작 시각, board 이전과 같은 꼴).
    limit 50 이면 1쪽 = 40 + 동률 10, 2쪽 = 동률 나머지 10. created 단독 커서였다면 2쪽이 0편(10편 누락)."""
    now = dt.datetime.now(dt.timezone.utc)
    with db.tx() as c:
        for i in range(40):
            at = now + dt.timedelta(minutes=40 - i)
            c.execute("INSERT INTO records (id,user_id,title,body,created,author_kind,text_process,received_at) "
                      "VALUES (%s,%s,%s,%s,%s,'self','verbatim',%s)", (f"r_s{i:03d}", uid, f"간격 {i}", f"간격 본문 {i}", at, at))
        for i in range(20):
            c.execute("INSERT INTO records (id,user_id,title,body,author_kind,text_process) "
                      "VALUES (%s,%s,%s,%s,'self','verbatim')", (f"r_t{i:03d}", uid, f"동률 {i}", f"동률 본문 {i}"))


async def test_records_api():
    site = main.site
    real = site.dev, site.dev_user
    uid = db.user_by_email(MAIN)["id"]
    db.display_name_set(uid, "홈시험")
    other = db.user_by_email(OTHER)["id"]
    tie = db.user_by_email(TIE)["id"]
    seed(uid, N, "m")
    seed(other, 3, "o")
    seed_tie(tie)
    live = N - 1   # 지운 1편 제외
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            site.dev, site.dev_user = False, ""
            assert (await h.get("/api/records")).status_code == 401
            site.dev, site.dev_user = True, MAIN
            r = await h.get("/api/records")
            assert r.status_code == 200 and r.headers.get("cache-control") == "no-store", r.status_code
            p1 = r.json()
            assert set(p1) == {"records", "next_before"}, "응답 계약 {records, next_before}"
            st = (await h.get("/api/state")).json()
            assert p1["records"] == st["journal"] and len(p1["records"]) == 50, "기본 = /api/state journal 50편"
            ds = st["devices_status"]   # ③-0.2 화면이 읽는 꼴 — 키 3개뿐(장치 id·이름 없음), 장치 없는 사용자 = none
            assert set(ds) == {"state", "last_seen_at", "threshold_seconds"} and ds["state"] == "none" and ds["last_seen_at"] is None, ds
            assert p1["next_before"] == f"{p1['records'][-1]['created']}|{p1['records'][-1]['id']}", "커서 = 마지막 created|id"
            assert st["journal_next_before"] == p1["next_before"], "/api/state journal_next_before = 기본 /api/records next_before(같은 커서 함수)"
            assert db.records(uid) == st["journal"] == db.records(uid, 50, None, None), "db.records 기본 호출 결과 불변"
            assert db.records(uid, 5) == st["journal"][:5], "records(uid, 5) 호출자(db.py) 불변"

            async def walk(first):
                seen, page, pages = [x["id"] for x in first["records"]], first, 1
                while page["next_before"]:
                    r = await h.get("/api/records", params={"before": page["next_before"], "limit": 50})
                    assert r.status_code == 200, r.text
                    nxt = r.json()
                    last = page["records"][-1]
                    assert all((x["created"], x["id"]) < (last["created"], last["id"]) or x["created"] < last["created"]
                               for x in nxt["records"]), "커서보다 뒤 순서만"
                    seen += [x["id"] for x in nxt["records"]]
                    page, pages = nxt, pages + 1
                return seen, pages
            seen, pages = await walk(p1)
            # journal_next_before 로 이어 받아도 같은 결과(화면 첫 「더 보기」 경로)
            r2 = (await h.get("/api/records", params={"before": st["journal_next_before"]})).json()
            assert [x["id"] for x in r2["records"]] == seen[50:100], "journal_next_before 로 2쪽"
            assert pages == 3 and len(seen) == live == len(set(seen)), (pages, len(seen))
            assert "r_m005" not in seen and not any(x.startswith("r_o") for x in seen), "지운 기록·남의 기록 0"
            created = [x["created"] for x in p1["records"]]
            assert created == sorted(created, reverse=True), "최신순"
            # limit 범위 밖 = 끝값(_qint 관례) · 숫자 아님 = 기본
            assert len((await h.get("/api/records?limit=101")).json()["records"]) == 100
            assert len((await h.get("/api/records?limit=500")).json()["records"]) == 100
            assert len((await h.get("/api/records?limit=0")).json()["records"]) == 1
            assert len((await h.get("/api/records?limit=x")).json()["records"]) == 50
            # 틀린 before → 400 ARG-INVALID(시간대 없음 · 날짜 틀림 · id 빠짐 · 구분자 없음)
            for bad in ("abc", "2026-10-01T00:00:00|r_x", "2026-13-01T00:00:00+00:00|r_x", "2026-10-01T00:00:00+00:00|",
                        "2026-10-01T00:00:00+00:00", "|r_x"):
                r = await h.get("/api/records", params={"before": bad})
                assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID", (bad, r.status_code)
            # 아주 이른 before = 빈 목록
            r = (await h.get("/api/records", params={"before": "2000-01-01T00:00:00+00:00|r_zzz"})).json()
            assert r == {"records": [], "next_before": None}
            # created 동률 블록이 1·2쪽 경계에 걸침 — 겹침·누락 0
            site.dev_user = TIE
            db.display_name_set(tie, "동률")
            t1 = (await h.get("/api/records")).json()
            tied = [x for x in t1["records"] if x["id"].startswith("r_t")]
            assert len(t1["records"]) == 50 and len(tied) == 10 and len({x["created"] for x in tied}) == 1, "1쪽 = 간격 40 + 동률 10"
            assert [x["id"] for x in tied] == [f"r_t{i:03d}" for i in range(19, 9, -1)], "동률은 id DESC"
            seen, pages = await walk(t1)
            assert pages == 2 and len(seen) == 60 == len(set(seen)), (pages, len(seen))
            assert db.records(tie, 50, dt.datetime.fromisoformat(tied[-1]["created"])) == [], "created 단독 커서였다면 동률 10편 누락(대조)"
            # 다른 사용자 세션 = 자기 기록 3편만
            site.dev_user = OTHER
            db.display_name_set(other, "남")
            r = (await h.get("/api/records")).json()
            assert [x["id"] for x in r["records"]] == ["r_o000", "r_o001", "r_o002"] and r["next_before"] is None
            assert (await h.get("/api/state")).json()["journal_next_before"] is None, "journal 50편 미만 = null"
            # journal 정확히 50편 = 커서 줌, 다음 호출 0편 + null(수용)
            with db.tx() as c:
                for i in range(3, 50):
                    c.execute("INSERT INTO records (id,user_id,title,body,created,author_kind,text_process,received_at) "
                              "VALUES (%s,%s,'t','b',now() - make_interval(days => %s),'self','verbatim',now())", (f"r_o{i:03d}", other, i))
            st50 = (await h.get("/api/state")).json()
            assert len(st50["journal"]) == 50 and st50["journal_next_before"], "정확히 50편 = 커서"
            r = (await h.get("/api/records", params={"before": st50["journal_next_before"]})).json()
            assert r == {"records": [], "next_before": None}, "50편 뒤 = 0편 + null"
    finally:
        site.dev, site.dev_user = real
    print("OK — /api/records(401·no-store·기본 = state journal·next_before 커서 이어 받기 겹침 0·동률 경계·limit 끝값·틀린 before 400·지운·남의 기록 0·state journal_next_before) 통과")


def test_static():
    """옛 app.html 에 남은 「나」 접점(R2 2026-11-03 — 「나」 화면은 React server/ui/src/features/me, 시험은 Vitest MeScreen·MeEdit·MeActs)
    · Setup 「페이지 레이아웃」(S4) · 오늘(S5) · 탭 3 · 축 색 토큰 · 표시 낱말."""
    html = (HERE / "app.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    assert html.count("<script>") == 1
    # 「나」 = React 섬 — 라우터는 주소 조각만 넘기고, 화면 코드·통계 접점은 옛 쪽에 없다
    assert 'else if (tab.view === "me") { subnav(""); uiMount("me", [R.a || "", R.b || ""]); }' in js
    assert "renderMeV9" not in js and '"/api/me/stats"' not in js and "/api/records?" not in js, "「나」 화면·통계·이어 받기 = React"
    # 미저장 보호 — 옮긴 화면이 ctx.setDirty 로 알린 주소(uiDirty) · 대화창 문구 · hashchange 가드 · 새로 고침 경고
    for w in ("저장하지 않은 변경이 있어요", "계속 편집", "변경 버리기"):
        assert w in html, w
    assert "if (uiLeaveGuard()) return;" in js and 'addEventListener("beforeunload", e => { if (uiDirty)' in js and "setDirty: at => { uiDirty = at; }" in js
    assert "@media (max-width: 767px)" in html and 'const HOME_MOBILE = "(max-width: 767px)";' in js, "모바일 분기점 = 768 미만(JS·React view.ts 와 같은 값)"
    assert "<script src" not in html.replace('<script src="{{asset:theme.js}}"></script>', ""), "외부 스크립트 0(테마 자산만)"
    # 타입 그래프 기본 = 그래프(새 탐색) · 영속 없음(저장소에 쓰지 않는다)
    assert 'let defsMode = "graph", defsAt = "";' in js and 'defsMode = navNew() ? "graph" : "list"' in js
    assert not re.search(r"localStorage\.setItem\([^)]*defs", js)
    assert "if (navNew()) return [NAVTAB._me, NAVTAB._today];" in js, "탭 나·오늘 — 설정은 톱니"
    # S6: 글 이름 하나 「내 글」(v9 P1) — 사용자 표시 라벨 자리별. 「내 글 AI 요약」·「내가 쓴 메모」(판단 출처 표시)는 그대로
    assert "내가 쓴 글" not in js and 'input_scope: {self_only: "내 글만"}' in js, "「내가 쓴 글」 0 — 생성 정보 입력 범위도 「내 글만」"
    import activity
    assert activity.NOTICE in (HERE / "ui" / "src" / "features" / "activity" / "text.ts").read_text(encoding="utf-8"), "ME_NOTICE(React 활동) = 서버 activity.NOTICE 미러"
    for w in ('"기록": "내 글"', 'kind: "내 글"', '"내 글 AI 요약"', '"내가 쓴 메모"', 'r.act', '"today:" + day',
              "const ME_SHOW = 5;", "data-me-open=", "a.action_label || actLabel(a.action)"):
        assert w in js, w
    # S4 Setup — 페이지 6 · 레이아웃 쓰기는 layFetch 한 곳(PUT·DELETE /api/me/layout) · PUT version = 마지막 응답 version(복원 뒤 포함) ·
    # 한 번에 하나(보내는 중이면 마지막 배치만 줄 세움) · 실패 = 마지막 저장 배치로 복원 · STALE = 서버 배치 다시 받기 · 옛 묶음 주소 replace ·
    # 저장 뒤 crm:state(React 「나」가 배치를 다시 받는다)
    setup = js[js.index("// ── Setup (PR ①-b S4)"):js.index("// ── /Setup ──")]
    for w in ('["layout", "페이지 레이아웃"]', '["structure", "내 구조 설정"]', '["objects", "자료 종류"]', '["devices", "연결 장치"]', '["map", "지도"]',
              '["help", "문의 및 개인정보"]', 'fetch("/api/me/layout"', '{layout: meV2(op.layout), version: ME.version}', 'layFetch("DELETE")',
              "ME.version = Number(res.j.version) || 0;", "if (LAY.busy) LAY.queued = op; else laySend(op);", 'res.code === "LAYOUT-STALE"',
              "ME.layout = LAY.saved.layout; ME.version = LAY.saved.version;", "기본으로 되돌리기", "e.altKey", 'window.dispatchEvent(new Event("crm:state"));',
              'if (R.tab === "_obj" && !R.a) return "#_setup/objects";', 'if (R.tab === "_settings") return "#_setup/structure";',
              'if (R.tab === "_devices") return "#_setup/devices";', 'if (R.tab === "map") return "#_setup/map";',
              'if (R.tab === "_inbox" && !R.a) return "#_today";', 'if (R.tab === "structure") {'):
        assert w in setup, w
    assert js.count('fetch("/api/me/layout"') == 1, "레이아웃 쓰기 = layFetch 한 곳"
    assert js.count("async function meSync()") == 1 and js.count("= meSync();") == 1, "레이아웃 읽기 접점 = meSync 한 곳(정의 + load 호출)"
    assert js.count('getJSON("/api/me/layout")') == 2, "읽기 = meSync + STALE 때 다시 받기"
    assert "corePost(" not in setup and "/api/" not in setup.replace("/api/me/layout", ""), "Setup 의 다른 쓰기·API 0"
    assert "if (navNew()) { const to = navReplace(R); if (to) { location.replace(to); return; } }" in js
    # S5 오늘 — 대기(승인 대기) + 보관됨(ingest_kind=inbox 글 · 활동) · 들어온 날(KST) 머리글 · [삭제] 0 · 동작 = 기존 승인·제외(inboxOne) · 읽기만
    today = js[js.index("// ── 오늘 (PR ①-b S5)"):js.index("// ── /오늘 ──")]
    for w in ('getJSON("/api/inbox?state=pending")', 'getJSON("/api/activities?limit=50")', 'r.ingest_kind === "inbox"', 'st: "대기"', 'st: "보관됨"',
              '"Asia/Seoul"', "class=\"tday\"", "inboxOne", "#_inbox/all", "ME_EMPTY"):
        assert w in today, w
    code = "\n".join(l for l in today.splitlines() if not l.lstrip().startswith("//"))
    assert "삭제" not in code and "corePost(" not in today and "fetch(" not in today, "오늘: [삭제] 0 · 새 쓰기 0(승인·제외는 기존 data-core 경로)"
    assert 'if (R.tab === "_inbox" && !INBOX_STATE[R.a]) return "#_today/inbox/" + encodeURIComponent(R.a);' in js
    assert 'hash = navNew() ? "#_today" : "#_inbox";' in js
    for i, (lt, dk) in enumerate(zip(("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
                                     ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")), 1):
        assert f"--ax{i}: {lt};" in html and f"--ax{i}: {dk};" in html, ("축 색", i)
    print("OK — 옛 쪽 「나」 접점(uiMount·통계 0·미저장 uiDirty·분기점) · Setup 페이지 6·레이아웃 쓰기 한 곳·version·crm:state·옛 주소 replace · "
          "오늘 대기/보관됨·날짜 머리글·삭제 0 · 축 색 토큰 · 표시 낱말 통과")


TRASH_ASK = "삭제하면 휴지통으로 이동해요. 삭제 시각부터 168시간 동안 복원할 수 있고, 이후 서버 정리 때 영구 삭제돼요."   # r4 §8 글자 그대로


def test_static_trash():
    """휴지통 PR-1 화면 — 스위치(S.switches.trash) 켜짐 + 새 탐색일 때만 [삭제]·Setup 「휴지통」 · 꺼짐 = 기존 동작 그대로 ·
    「남기지 않음」 → 「반영 안 함」(스위치 무관, 글자만) · 삭제된 근거 빈 자리 = 「근거를 이용할 수 없어요.」 · 이동 접점 = trashApi.del 한 곳.
    Setup 「휴지통」 페이지(목록·복원·영구 삭제)는 React(server/ui/src/features/trash) — 그 화면 시험은 TrashScreen.test.tsx(R1 2026-11-03)."""
    html = (HERE / "app.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    tr = js[js.index("// ── 휴지통 (trash PR-1)"):js.index("// ── /휴지통 ──")]
    assert "const trashOn = () => !!(S && S.switches && S.switches.trash) && navNew();" in tr
    for w in (TRASH_ASK, "복원 기간이 끝났어요."):
        assert w in tr, w
    code = "\n".join(l for l in tr.splitlines() if not l.lstrip().startswith("//"))
    assert "처리 중" not in code and "재시도 중" not in code and "예정" not in code, "「영구 삭제 처리 중·재시도 중·예정」 화면 상태 0(r4 §8)"
    assert tr.count("/api/trash") == 1 and js.count("/api/trash") == 1 and 'corePost("/api/trash/move"' in tr, "옛 쪽 휴지통 API = 이동(trashApi.del) 하나"
    assert "localStorage" not in tr and "Storage" not in tr
    # 진입점 — 상세마다 trashBtn(꺼짐 = 빈 문자열) · 사람·생각은 켜짐이면 휴지통, 꺼짐이면 기존 즉시 삭제(data-core) 그대로
    # 「나」 상세의 [삭제](내 글·항목·생각)는 React — Vitest MeActs.test.tsx(R2 2026-11-03) · 활동 하나의 [삭제]도 React — Vitest ActivityScreen.test.tsx(R4)
    for w in ('trashOn() ? trashBtn("person", p.id, p.revision, "#_obj/person") : `<button class="secondary" type="button" data-core="person-del"',
              'trashOn() ? trashBtn("reflection", x.id, x.revision, `#_obj/source/${x.source_id}`) : `<button class="secondary" type="button" data-core="refl-del"',
              'trashBtn("item", it.id, it.revision, `#${tab.id}/${d.id}`)', "j.old_revision_links && !trashOn()"):
        assert w in js, w
    assert 'if (!window.confirm("이 사람을 지울까요? 되돌릴 수 없어요.")) return;' in js and 'if (!window.confirm("이 읽고 든 생각을 지울까요? 되돌릴 수 없어요.")) return;' in js, \
        "꺼짐 = 기존 즉시 삭제 경로 유지"
    assert not re.search(r'trashBtn\("cand', js) and "data-trash=\"cand" not in js, "후보 = 독립 휴지통 대상 아님(r4 D3) — 새 거절 버튼 0"
    # 기준 — 서랍·「나」 상세 모두 켜짐이면 [남기지 않기]·[되돌리기] 대신 [남기기]만(+[삭제]). 꺼짐 분기는 옛 버튼 그대로
    drawer = js[js.index("function drawerHtml(tab, it)"):js.index("function proposalHtml(")]
    on = drawer[drawer.index("if (!isNew && trashOn())"):drawer.index("} else if (it.semantic_kind === \"principle\" && !isNew)")]
    assert 'data-iact="exclude"' not in on and 'data-iact="pending"' not in on and 'data-iact="confirm"' in on
    assert 'data-iact="exclude"' in drawer and ">반영 안 함</button>" in drawer and "되돌리기" in drawer, "꺼짐 분기 = 옛 버튼(글자만 「반영 안 함」)"
    # Setup — SETUP_PAGES 리터럴은 그대로, 켜짐일 때만 「휴지통」 페이지
    assert 'const setupPages = () => trashOn() ? SETUP_PAGES.concat([["trash", "휴지통"]]) : SETUP_PAGES;' in js
    assert "setupPages().some(p => p[0] === R.a)" in js and "else if (page === \"trash\") uiMount(\"trash\");" in js
    # 「반영 안 함」 — 칩·필터·저장 메시지·이력·메타(스위치 무관). 기존 상태 표시만 바꾸고 동작은 그대로
    for w in ('<span class="badge b-off">반영 안 함</span>', '["excluded", "반영 안 함"]', 'excluded: ["st-off", "반영 안 함"]',
              'exclude: "반영 안 함으로 표시했어요."', 'exclude: "반영 안 함", pending: "아직 안 정함"',
              '["반영 안 함", cs.filter(c => c.status === "excluded").length, "--soft"]'):
        assert w in js, w
    assert "남기지 않" not in html, "「남기지 않음·않기·않았어요」 0 — 표현은 「반영 안 함」 하나(동작 exclude 는 그대로). React 쪽은 Vitest MeActs"
    assert js.count("반영 안 함으로 표시했어요.") == 1 and "반영 안 함으로 저장했어요." not in js, "옛 쪽 = 서랍 ITEM_SAVED 하나(판단 검토 = React features/review)"
    assert "근거를 이용할 수 없어요." in js and "찾을 수 없는 대상" not in js, "삭제된 근거 = 「근거를 이용할 수 없어요.」"
    # PR-2 몫은 그대로 — 승인 대기 [제외] · 제안 [제외] · 대화 「뺀 것」
    assert 'act === "inbox-exclude"' in js and '<button class="secondary" type="button" data-iact="discard">제외</button>' in js   # 대화 「뺀 것」 = React features/chat
    print("OK — 휴지통 정적(스위치 게이트·r4 §8 문구 그대로·처리 중 상태 0·접점 한 곳·진입점 5·후보 버튼 0·기준 버튼 변경·Setup 페이지·반영 안 함·근거 이용 불가·PR-2 몫 그대로) 통과")


def trash_run(scenario):
    """휴지통 절 실행(node) — 휴지통 절(상세 [삭제]) + Setup 페이지 목록 + 날짜·esc 도우미. 「나」 상세 동작 칸은 React(Vitest MeActs).
    서버·DOM 은 가짜: api = 보낸 요청 기록, confirmAsk = 확인창 문구 기록, done/fail = coreDone·coreFail 호출 기록."""
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "node 가 필요해요(CI 는 setup-node) — 휴지통 실행 시험"
    html = (HERE / "app.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    helpers = "\n".join(re.search(rf"^{p}.*$", js, re.M).group(0) for p in (
        r"const esc = ", r"const toDate = ", r"const pad2 = ", r"function mdhm\(", r"const SETUP_PAGES = ", r"const setupPages = "))
    b = js.index("// ── 휴지통 (trash PR-1)")
    tr = js[b:js.index("// ── /휴지통 ──", b)]   # 클릭 연결은 가짜 document 가 받고 버린다 · hashchange 는 HASH 로
    stub = """let S = null, NAVNEW = true, coreFlash = null; const navNew = () => NAVNEW;
const WHAT = {OFFLINE: "서버에 연결하지 못했어요."};
const els = {}; const $ = id => els[id] || (els[id] = {id, textContent: "", innerHTML: "", hidden: false});
const document = {querySelectorAll: () => [], querySelector: () => null, addEventListener() {}};
let ROUTE = {tab: "_setup", a: "trash"}; const route = () => ROUTE;
const api = []; let REPLY = {ok: true, j: {}}, LIST = {ok: true, j: {rows: []}};
const corePost = async (url, body) => { api.push({url, body}); return REPLY; };
const getJSON = async url => { api.push({url}); return LIST; };
const confirmAsk = []; let CONFIRM = true; let HASH = () => {};
const window = {confirm: t => { confirmAsk.push(t); return CONFIRM; }, addEventListener: (ev, f) => { if (ev === "hashchange") HASH = f; }};
const done = [], fail = [];
const coreDone = async (text, hash) => { done.push({text, hash}); }; const coreFail = async (res, err) => { fail.push(res.code); };
const coreFlashShow = () => {}; const load = async () => { S = Object.assign({}, S); };
const fakeBtn = (d, err) => ({dataset: d, disabled: false, closest: () => ({querySelector: () => err})});"""
    src = f"{stub}\n{helpers}\n{tr}\nconst out = {{}};\n(async () => {{\n{scenario}\n}})().then(() => console.log(JSON.stringify(out)), e => {{ console.error(e); process.exit(1); }});"
    r = subprocess.run([node, "-"], input=src, capture_output=True, text=True, timeout=60, env=dict(os.environ, TZ="Asia/Seoul"))
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout)


def test_trash_switch():
    """스위치별 차이 — 꺼짐(또는 옛 탐색) = [삭제]·휴지통 페이지 0 · 켜짐 = [삭제] 버튼·Setup 「휴지통」.
    「나」 상세의 버튼(기준 [남기기]+[삭제] · 후보 [삭제] 0 · 꺼짐 = 옛 버튼)은 React — Vitest MeActs.test.tsx."""
    o = trash_run("""
const snap = () => ({on: trashOn(), pages: setupPages().map(p => p[0]), btn: trashBtn("record", "r1", null, "#_me")});
S = {switches: {converse: true}}; out.none = snap();
S = {switches: {trash: false}}; out.off = snap();
S = {switches: {trash: true}}; NAVNEW = false; out.old = snap();
NAVNEW = true; out.on = snap();
""")
    for k in ("none", "off", "old"):
        s = o[k]
        assert s["on"] is False and "trash" not in s["pages"] and s["btn"] == "", (k, "꺼짐·옛 탐색 = 버튼·페이지 0")
    s = o["on"]
    assert s["on"] is True and s["pages"][-1] == "trash" and s["pages"][:6] == ["layout", "structure", "objects", "devices", "map", "help"]
    assert s["btn"] == '<button class="secondary" type="button" data-trash="record" data-id="r1" data-back="#_me">삭제</button>'
    print("OK — 휴지통 스위치(꺼짐·필드 없음·옛 탐색 = [삭제]·페이지 0 · 켜짐 = [삭제]·Setup 휴지통) 통과")


def test_trash_flow():
    """[삭제] = r4 §8 확인창 → 휴지통 API(종류·ID·revision) → 「휴지통으로 옮겼어요.」 + 목록 주소 · 취소 = 요청 0 · 축 정책 차단 = 장치 안내.
    Setup 휴지통(행·빈 상태·안내·[복원]·[영구 삭제]·기한 이후·더 보기·불러오기 실패)은 React — server/ui/src/features/trash/TrashScreen.test.tsx."""
    o = trash_run("""
S = {switches: {trash: true}};
const err = {textContent: ""};
CONFIRM = false; await trashDel(fakeBtn({trash: "item", id: "i1", rev: "3", back: "#_me/axis"}, err)); out.cancel = api.length;
CONFIRM = true; await trashDel(fakeBtn({trash: "item", id: "i1", rev: "3", back: "#_me/axis"}, err)); out.del = api.pop(); out.done = done.pop();
await trashDel(fakeBtn({trash: "record", id: "r1", back: "#_me"}, err)); out.delRec = api.pop(); done.length = 0;
REPLY = {ok: false, code: "AXIS-IN-POLICY", msg: "이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요."};
await trashDel(fakeBtn({trash: "item", id: "ax1", rev: "1", back: "#_me/axis"}, err)); out.axis = err.textContent; out.axisDone = done.length;
REPLY = {ok: false, code: "CONFLICT"}; await trashDel(fakeBtn({trash: "person", id: "p1", rev: "2", back: "#_obj/person"}, err)); out.fail = fail.slice();
out.ask = confirmAsk.slice();
""")
    assert o["cancel"] == 0, "확인창 취소 = 요청 0"
    assert o["del"] == {"url": "/api/trash/move", "body": {"kind": "item", "id": "i1", "expected_revision": 3}}
    assert o["done"] == {"text": "휴지통으로 옮겼어요.", "hash": "#_me/axis"}, "성공 = 결과 한 줄 + 목록 주소(삭제한 상세는 더 열리지 않는다)"
    assert o["delRec"] == {"url": "/api/trash/move", "body": {"kind": "record", "id": "r1"}}, "revision 없는 종류 = expected_revision 생략"
    assert o["axis"] == "이 축은 장치 「회사 PC」의 허용 규칙에 쓰여 삭제할 수 없어요." and o["axisDone"] == 0, "축 정책 차단 = 서버 장치 안내 그대로 · 이동 0"
    assert o["fail"] == ["CONFLICT"], "그 밖 오류 = 기존 coreFail(다시 불러오기)"
    assert set(o["ask"]) == {TRASH_ASK}, "삭제 확인창 = r4 §8 글자 그대로"
    print("OK — 휴지통 [삭제] 흐름(확인창 r4 문구·취소 요청 0·종류·ID·revision·성공 문구+주소·축 정책 장치 안내·그 밖 coreFail) 통과")


def test_static_moved():
    """test_tools.py 에서 옮겨 온 app.html 정적 단언(③-0.2 — 서버 에이전트 목록 A1~A5·B1~B4, 검증 범위 그대로).
    문자열 단언으로 둔 이유: 파일 성질(인라인 스크립트·CSP 해시·on* 0·특정 낱말 부재·마크업 구간·서버 정본과 같은 문구)이라 실행으로 보이지 않는다.
    서버 정본 값(db·web·contract·structure_svg)은 import 해 같은 기대값을 쓴다(하드코딩하지 않는다)."""
    import contract
    import structure_svg
    import web
    html = (HERE / "app.html").read_text(encoding="utf-8")
    # 공통(A1·A2·A3·A5) — 인라인 스크립트 1개(CSP 해시 대상) · 인라인 이벤트 속성 0(CSP)
    assert len(web.inline_script_hashes(html)) == 1 and html.count("<script>") == 1, "인라인 스크립트 1개"
    assert not re.search(r"\son[a-z]+\s*=", html, re.I), "app.html 인라인 이벤트 속성 0"

    # A1 문의 데스크 — 문의 구간의 모든 보간은 esc(…) · innerHTML 우변은 템플릿 하나(이어 붙이기 없음) · 다른 HTML 삽입 API 없음
    blk = html[html.index("// ── 문의 데스크 (desk-0) ──"):html.index("// ── /문의 데스크 ──")]
    assert blk.count("${") == blk.count("${esc(") >= 4, re.findall(r"\$\{(?!esc\()[^}]*", blk)
    for bad in ("insertAdjacentHTML", "outerHTML", "document.write", "DOMParser", "createContextualFragment"):
        assert bad not in blk, bad
    sites = list(re.finditer(r"\.innerHTML\s*=\s*", blk))
    assert sites, "행은 innerHTML 템플릿으로 만든다"
    for m in sites:
        rest = blk[m.end():]
        assert rest.startswith("`"), rest[:60]
        end = rest.index("`", 1)
        assert rest[end + 1:].lstrip().startswith(";"), rest[end:end + 40]
    i = html.index('<dialog id="desk-dlg"')   # Q1b: 문의 폼·목록은 계정 메뉴에서 여는 대화창
    sec = html[i:html.index("</dialog>", i)]
    assert "${" not in sec and db.NOTICE in sec and 'href="/privacy"' in sec, "정적 대화창 — 고지 문장·처리방침 링크"
    for w in ('value="bug"', 'value="request"', 'value="question"', 'value="privacy"', "개인정보 요청", "내 문의", "4096"):
        assert w in sec, w
    assert 'ticketStatus: {open: "접수", ack: "확인", doing: "처리중", done: "완료", wontfix: "보류"}' in html
    assert "const DESK_MAX = 4096;" in html and db.LIMIT_TICKET == 4096
    # 내 문의(P5): 상세는 본인 API 하나 · 글·답변은 esc · 이력은 textContent · 관리자 문의함·띠·옛 API 흔적 0
    for w in ('fetch("/api/feedback/" + encodeURIComponent(id)', "${esc(j.text)}", "${esc(j.reply || ", "li.textContent = ",
              "${esc(t.has_reply ? ", "${esc(md(t.public_updated)"):
        assert w in blk, w
    assert "${t." not in blk and "${j." not in blk
    for gone in ("admin-band", "deskBand", "deskAdmin", "/api/feedback/status", "/api/feedback/note", "admin_tickets", "admin_note",
                 "desk-admin", "DESK_NOTE_MAX", "j.admin"):
        assert gone not in html, ("app.html 에 관리자 문의함 흔적", gone)
    # 설정은 모든 역할에서 우측 상단 톱니 하나. 관리자 권한은 서버가 지킨다.
    gear = re.search(r'<a\b[^>]*\bid="setup-link"[^>]*>', html)
    assert gear and not re.search(r"\shidden(\s|>)", gear.group(0)) and 'href="#_setup"' in gear.group(0), gear
    assert '$("setup-link").hidden' not in html

    # A2 계정 메뉴 — 메뉴 항목 · ⚙ 메뉴 밖 · #who 말줄임 · 문의 숨기기 흔적 0 (/app 응답 CSP 해시는 test_tools 에 남는다)
    menu = html[html.index('<details class="acct" id="acct">'):html.index("</details>")]
    for act in ("send", "mine", "privacy", "names", "logout"):
        assert f'data-acct="{act}"' in menu, act
    for w in ('<span id="who"></span>', 'id="logout"', 'id="acct-names"', "구조 이름 공유", "로그아웃"):
        assert w in menu, w
    for w in ('data-acct="desk"', 'id="acct-desk"', "문의 섹션"):   # Q1b: 숨기기 메뉴 없음(서버 API·열은 남는다)
        assert w not in menu, w
    assert 'id="setup-link"' not in menu and 'id="setup-link"' in html, "⚙ 는 메뉴 밖에 그대로"
    assert re.search(r"#who \{[^}]*text-overflow: ellipsis[^}]*\}", html) and re.search(r"#who \{[^}]*min-width: 0", html), "#who 말줄임"
    for w in ('fetch(url, {method: "POST"', '"/api/optional-consent", {kind: "struct_names"',
              '[name="kind"][value="privacy"]', '$("desk-dlg").showModal()'):
        assert w in html, w
    for w in ("/api/desk-visibility", "desk_hidden", "deskPeek", 'id="desk"'):   # Q1b: 화면은 숨김 상태를 안 쓴다
        assert w not in html, w

    # A3 구조 정의 보기·편입 대화창(Q4·Q5)
    tokens = structure_svg.tokens_css(dark_attr=True, dark_media=False)
    assert '"구조 정의"' in html and "/defs" in html and 'if (a === "defs") return renderDefs(tab);' in html, "구조 정의 보기·라우트"
    assert "S.structure" in html and "/api/std/preview" in html and "/api/std/choose" in html
    i = html.index('<dialog id="std-dlg"')
    dlg = html[i:html.index("</dialog>", i)]
    for w in ('id="std-dlg-ok"', 'type="checkbox"', 'id="std-dlg-go" disabled', 'id="std-dlg-lock"', 'id="std-dlg-oktext"',
              'id="std-dlg-cancel"'):
        assert w in dlg, w

    def outside_marks(pos, what):   # 관리자 /app 도 쓰는 대화창 — <!--user-->/<!--admin--> 구간 표식 밖
        for mark in ("<!--user-->", "<!--admin-->"):
            for a in [m.start() for m in re.finditer(re.escape(mark), html)]:
                b = html.index(mark.replace("<!--", "<!--/"), a)
                assert not (a < pos < b), (what, "구간 안", mark)
    outside_marks(i, "std-dlg")
    for w in ('같은 뜻으로 쓴다', 'confirmed_meaning = true', 'expected_revision = o.object ? o.object.revision : null',
              '$("std-dlg-go").disabled = !$("std-dlg-ok").checked', '"DEF-INVALID":', '"CONFLICT":',
              "표준 정의 보호", "출처 미확인", "source_counts", "확정 전 재검토", "S.sources"):
        assert w in html, w
    for code in contract.LOCKED_CHANGES:   # 잠금 영향 문구 — 서버 코드 전부
        assert re.search(rf"\b{code}: \"", html), code
    for code in contract.REVIEW_REASONS:
        assert re.search(rf"\b{code}: \"", html), code
    fix = html[html.index("const REVIEW_FIX = {"):html.index("};", html.index("const REVIEW_FIX = {"))]
    assert "author_unknown" in fix and "processed" in fix and "external" not in fix and "deleted" not in fix, "정정 안내는 두 사유만"
    assert "record_provenance_set" not in html and "verbatim 으로" not in html, "도구명·「바꾸면 풀린다」 안내 없음"
    for w in ('let defsMode = "graph", defsAt = "";', 'data-dmode="${m}"', '"목록" : "그래프"', "S.structure_svg", 'id="dlist"', 'id="dgraph"',
              'id="dmo-o${i + 1}"', 'id="dmo-r${i + 1}"', 'id="dmo-core-${esc(x.kind)}"', 'closest(".dmo a")', 'getAttribute("href")',
              "e.preventDefault(); defsJump(", "scrollIntoView"):
        assert w in html, w
    assert (structure_svg.node_anchor(0), structure_svg.rel_anchor(0), structure_svg.core_anchor("record")) == (
        "dmo-o1", "dmo-r1", "dmo-core-record"), "app.html 의 id 꼴 = structure_svg 앵커"
    assert tokens in html and "prefers-color-scheme" not in tokens and "prefers-color-scheme" not in html, "토큰 = 테마 토글(data-theme)만"
    assert '[data-theme="dark"]' in tokens
    rendered = structure_svg.fill_origin_labels(html)
    assert "/*{{origin-text}}*/ {}" not in rendered
    assert 'const ORIGIN_CHIP = Object.fromEntries(Object.keys(ORIGIN_TEXT)' in rendered, "칩은 그래프와 같은 표시 정의"

    assert '<th scope="col">출처</th>' not in html and '<th scope="col">구분</th><th scope="col">보호</th>' in html, "필드 표 열 머리 = 구분(정의 구분 뜻의 '출처' 0)"
    sv = html[html.index("function structViews("):html.index("\n}", html.index("function structViews("))]   # 구조 탭 순서: 보기 전환 → 오브젝트 필(항목 보기만)
    assert sv.index('aria-label="구조 보기"') < sv.index("+ sub;") and 'subnav("");\n  const sub = `<nav class="pills sobjs" aria-label="구조 고르기">' in html \
        and '"구조 고르기");' not in html and 'structViews(tab, "defs", ' not in html and html.count('structViews(tab, "items", sub)') == 3, "보기 전환이 맨 위 · 오브젝트 필은 그 아래 항목 보기에서만"
    assert "min-width: 420px" in html and ".dmo { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 8px; overflow-x: auto; }" in html

    # A4 코어 표시명 — app.html LABELS(std@1 표시명 절의 화면 몫. web.CORE_LABEL 비교는 test_tools 에 남는다)
    assert all(f'{k}: "{v}"' in html for k, v in (("question", "질문"), ("record", "기록"), ("candidate", "후보"))), "app.html LABELS"

    # A5 24h 화면 — 플래그 0 · 이름 관문·nav·새 경로·탭 3 · 안내 문구 · 재검토 표시 · 대화창 둘(구간 밖) · 메뉴
    assert "FEATURE-OFF" not in html, "플래그 제거 — 화면에도 FEATURE-OFF 0"
    for w in ('if (needName()) return renderNameGate();', 'data-form="name"',
              "실명이 아니어도 돼요. 다른 사람에게 보이지 않고 운영자 화면에도 나오지 않아요.",
              '"/api/nav/accept"', '"/api/me/name"', '"/api/people', '"/api/reflections',
              'id: "_me"', 'id: "_obj"', 'id: "_settings"',
              "if (navNew()) return [NAVTAB._me, NAVTAB._today];",   # PR ①-b 탭 3: 나 · 오늘 · Setup(B1)
              'if (R.tab === "_settings") return "#_setup/structure";', "function axisChips",
              "출처를 접한 뒤 내가 한 생각만 적어요. 다른 사람의 말·경험·생각을 옮기는 곳이 아니에요.",
              "별칭도 그 사람을 알아볼 수 있으면 개인정보예요.", "삭제 완료"):
        assert w in html, w
    assert re.search(r"REFL_HELP\s*=\s*\"출처를 접한 뒤 내가 한 생각만 적어요", html) and re.search(r"PERSON_HELP\s*=\s*\"별칭도", html)
    assert html.count("${reviewNote(c)}") >= 3, "오늘·질문·기록 화면 재검토 표시(판단 검토 화면 = React shared/ReviewNote, R3)"
    for dlg_id in ("name-dlg", "nav-dlg"):
        outside_marks(html.index(f'<dialog id="{dlg_id}"'), dlg_id)
    i = html.index('<dialog id="nav-dlg"')
    nav = html[i:html.index("</dialog>", i)]
    for w in ("「나」 홈", "「자료 종류」", "「내 구조 설정」", "데이터는 바뀌지 않아요", "되돌릴 수 없어요"):   # PR① 새 탐색 안내 = 탭 3(나·자료 종류·지도)
        assert w in nav, ("nav 대화창", w)
    menu = html[html.index('id="acct-menu"'):html.index("</details>")]
    for a in ("name", "nav", "settings"):
        assert f'data-acct="{a}"' in menu, a

    # B1 기본 밝은 화면 — OS 다크 설정·?theme 를 따르지 않는다. 어두운 화면은 토글(data-theme="dark")로만
    assert "prefers-color-scheme" not in html and "dataset.theme" not in html and html.count(':root[data-theme="dark"] {') >= 1, "app.html"
    assert '<html lang="ko">' in html and "data-theme" not in html.split("<head>", 1)[0], "app.html: 기본은 라이트"
    # B2 외부 셰이더 문자열 0(바이트) — 이 파일 자신에 걸리지 않게 조립한다
    raw = (HERE / "app.html").read_bytes()
    assert not [n for n in (b"shaders" + b".com", b"type" + b"gpu") if n in raw], "app.html 외부 셰이더 문자열 0"
    # B3 필수 동의 게이트 없음 — 화면에 CONSENT-REQUIRED·/api/consent·consent_grant·/consent 링크 0
    assert "CONSENT-REQUIRED" not in html and "/api/consent" not in html and "consent_grant" not in html, "app.html 동의 게이트 흔적 0"
    assert [ln for ln in html.splitlines() if "/consent" in ln] == [], "app.html /consent 줄 0"
    # B4 재인증 제거 — 화면에도 흔적 0
    for word in ("REAUTH", "reauth_ok", "auth_time", "_reauth_fresh", "state.ra", "재인증"):
        assert word not in html, f"정적: {word} 0"
    print("OK — test_tools 에서 옮긴 app.html 정적(A1 문의 esc·A2 계정 메뉴·A3 구조 정의·편입 대화창·A4 LABELS·A5 24h 화면·B1 라이트 기본·B2 셰이더 0·B3 동의 0·B4 재인증 0) 통과")


async def test_ui_samples():
    """API 견본 대조(R2) — React 「나」가 읽는 응답 조각의 손 사본 타입(TS)과 실제 응답을 대조한다.
    ui/src/shared/state.sample.json ⊆ /api/state(AppState 는 쓰는 조각만) · ui/src/features/me/me.sample.json = /api/me/stats·/api/me/layout·/api/journal·본문 미리보기
    (키 집합까지). TS 쪽은 satisfies(tsc) — 서버 응답이 바뀌면 여기서, TS 타입이 바뀌면 tsc 에서 잡힌다."""
    import json
    site = main.site
    real = site.dev, site.dev_user
    uid = db.user_by_email(SAMPLE)["id"]
    db.display_name_set(uid, "견본")
    db.nav_accept(uid)
    q = db.question_add(uid, "견본 질문")
    src = db.source_create(uid, "url", "견본 출처")
    rec = db.record_add(uid, "견본 글", "견본 본문 입력 담당을 먼저 정했다.", q["id"])
    with db.tx() as c:
        c.execute("UPDATE records SET source_id=%s WHERE user_id=%s AND id=%s", (src["id"], uid, rec["id"]))
    cid = db.candidates_propose(uid, rec["id"], q["id"], [{"text": "담당 먼저", "quote": "입력 담당을 먼저"}], "ai")[0][0]
    defs = {d["std_id"]: d for d in db.definitions(uid)}
    pd, ax = defs["std:principles"], defs["std:axes"]
    ref = next((f for f in pd["fields"] if f["value_type"] == "reference" and f["target_kind"] == "candidate"), None)
    links = [{"field_key": ref["key"], "target_kind": "candidate", "target_id": cid}] if ref else []
    p = db.item_propose(uid, pd["id"], pd["revision"], None, 0, "P-1", "견본 기준", "본문", {}, links)
    db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")
    a = db.item_propose(uid, ax["id"], ax["revision"], None, 0, None, "견본 축", "", {}, [])
    db.item_decide(uid, a["item_id"], 0, a["proposal_id"], "apply")
    db.record_attach(uid, rec["id"], axes=[a["item_id"]])
    db.person_save(uid, "견본 사람")
    db.source_reflection_save(uid, src["id"], "summary", "견본 생각")
    ui = HERE / "ui" / "src"
    st_sample = json.loads((ui / "shared" / "state.sample.json").read_text(encoding="utf-8"))
    me_sample = json.loads((ui / "features" / "me" / "me.sample.json").read_text(encoding="utf-8"))
    try:
        site.dev, site.dev_user = True, SAMPLE
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            st = (await h.get("/api/state")).json()
            got = {"stats": (await h.get("/api/me/stats")).json(), "layout": (await h.get("/api/me/layout")).json(),
                   "journal": (await h.get("/api/journal", params={"id": rec["id"]})).json(),
                   "preview": (await h.post(f"/api/records/{rec['id']}/body/preview", headers={"origin": PUBLIC},
                                            json={"expected_revision": 1, "body": "견본 본문 입력 담당을 먼저 정했다. 덧붙임"})).json()}   # 판단과 겹치지 않는 자리(연결 걸린 겹침 = 잠금)
    finally:
        site.dev, site.dev_user = real
    for k in ("journal", "questions", "candidates", "items", "definitions", "record_links", "people", "reflections", "sources"):
        assert st[k], ("견본 대조에 쓸 행이 없어요", k)
    assert not ref or st["items"][0]["links"] or any(i["links"] for i in st["items"]), "항목 연결 행"
    bad = _cmp(st_sample, st, "state", exact=False)
    assert not bad, (bad, "state.sample.json·shared/state.ts 의 AppState 를 같이 고친다")
    assert (got["preview"].get("drop"), got["preview"].get("msg")) == (0, ""), got["preview"]
    for k in ("stats", "layout", "journal", "preview"):
        bad = _cmp(me_sample[k], got[k], k, exact=True)
        assert not bad, (bad, "me.sample.json·features/me/meApi.ts 의 타입을 같이 고친다")
    assert got["journal"]["revision"] == 1 and got["journal"]["author_kind"] == "self", "수기 수정 — 저장 expected_revision · 남이 쓴 글 판정"
    print("OK — API 견본 대조(state ⊆ 실제 · stats·layout·journal 키·값 타입 = me.sample.json · journal revision·author_kind) 통과")


async def run():
    db.init_schema()
    cleanup()
    try:
        test_static()
        test_static_trash()
        test_trash_switch()
        test_trash_flow()
        test_static_moved()
        await test_records_api()
        await test_ui_samples()
    finally:
        cleanup()
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
