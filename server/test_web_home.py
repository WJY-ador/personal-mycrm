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
F. 휴지통 PR-1 화면(node 실행 포함): 스위치 S.switches.trash 켜짐일 때만 [삭제]·Setup 「휴지통」 · 꺼짐 = 현행 · 기준 [남기기]+[삭제] · 후보 [삭제] 0 ·
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
    · Setup 「페이지 레이아웃」(S4) · 오늘(S5 — 화면은 React features/today, R4-2: 라우팅만) · 탭 3 · 축 색 토큰 · 표시 낱말."""
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
    mobile = (HERE / "ui" / "src" / "shared" / "mobile.ts").read_text(encoding="utf-8")
    assert "@media (max-width: 767px)" in html and 'export const MOBILE = "(max-width: 767px)";' in mobile, "모바일 분기점 = 768 미만(CSS·React shared/mobile.ts 와 같은 값)"
    assert "<script src" not in html.replace('<script src="{{asset:theme.js}}"></script>', ""), "외부 스크립트 0(테마 자산만)"
    # 내 구조 설정·구조·지도·질문·기록 = React(R5b-1) — 그래프 기본·영속 없음은 Vitest DefsScreen(저장소 쓰기 = arch.test 원문 포트 하나)
    for w in ('uiMount("defs")', 'uiMount("structure", [R.a || "", R.b || ""])', 'uiMount("map", [tab.id])', 'uiIsland("mast", $("ui-mast")'):
        assert w in js, w
    assert "const tabsList = () => [NAVTAB._me, NAVTAB._today];" in js, "탭 나·오늘 — 설정은 톱니"
    # S6: 글 이름 하나 「내 글」(v9 P1) — 사용자 표시 라벨 자리별. 「내 글 AI 요약」·「내가 쓴 메모」(판단 출처 표시)는 그대로
    today_text = (HERE / "ui" / "src" / "features" / "today" / "text.ts").read_text(encoding="utf-8")
    assert "내가 쓴 글" not in js and "내가 쓴 글" not in today_text and 'input_scope: { self_only: "내 글만" }' in today_text, "「내가 쓴 글」 0 — 생성 정보 입력 범위도 「내 글만」(React 오늘)"
    import activity
    assert activity.NOTICE in (HERE / "ui" / "src" / "features" / "activity" / "text.ts").read_text(encoding="utf-8"), "ME_NOTICE(React 활동) = 서버 activity.NOTICE 미러"
    chips = (HERE / "ui" / "src" / "shared" / "CandChips.tsx").read_text(encoding="utf-8")
    assert "NEWTERM" not in js and '"내가 쓴 메모"' in chips and ">확정한 판단<" in chips, "표시 낱말 = React 칩(옛 NEWTERM 치환 없음, R5b-1)"
    # S4 Setup — 페이지 6 · 레이아웃 쓰기는 layFetch 한 곳(PUT·DELETE /api/me/layout) · PUT version = 마지막 응답 version(복원 뒤 포함) ·
    # 한 번에 하나(보내는 중이면 마지막 배치만 줄 세움) · 실패 = 마지막 저장 배치로 복원 · STALE = 서버 배치 다시 받기 · 옛 묶음 주소 replace ·
    # 저장 뒤 crm:state(React 「나」가 배치를 다시 받는다)
    setup = js[js.index("// ── Setup (PR ①-b S4)"):js.index("// ── /Setup ──")]
    for w in ('["layout", "페이지 레이아웃"]', '["structure", "내 구조 설정"]', '["objects", "자료 종류"]', '["devices", "연결 장치"]', '["map", "지도"]',
              '["help", "문의 및 개인정보"]', 'fetch("/api/me/layout"', '{layout: meV2(op.layout), version: ME.version}', 'layFetch("DELETE")',
              "ME.version = Number(res.j.version) || 0;", "if (LAY.busy) LAY.queued = op; else laySend(op);", 'res.code === "LAYOUT-STALE"',
              "ME.layout = LAY.saved.layout; ME.version = LAY.saved.version;", "기본으로 되돌리기", "e.altKey", 'window.dispatchEvent(new Event("crm:state"));',
              'if (R.tab === "_obj" && !R.a) return "#_setup/objects";', 'if (R.tab === "_settings") return "#_setup/structure";',
              'if (R.tab === "_devices") return "#_setup/devices";', 'if (R.tab === "map" && R.a !== "review") return "#_setup/map";',
              'if (R.tab === "_inbox" && !R.a) return "#_today";', 'if (R.tab === "structure") {'):
        assert w in setup, w
    assert js.count('fetch("/api/me/layout"') == 1, "레이아웃 쓰기 = layFetch 한 곳"
    assert js.count("async function meSync()") == 1 and js.count("= meSync();") == 1, "레이아웃 읽기 접점 = meSync 한 곳(정의 + load 호출)"
    assert js.count('getJSON("/api/me/layout")') == 2, "읽기 = meSync + STALE 때 다시 받기"
    assert "corePost(" not in setup and "/api/" not in setup.replace("/api/me/layout", ""), "Setup 의 다른 쓰기·API 0"
    assert "{ const to = navReplace(R); if (to) { location.replace(to); return; } }" in js
    assert 'if ((R.tab === "today" || R.tab === "home") && R.a !== "review") return "#_today";' in js, "옛 오늘 화면 없음 — 옛 대조 링크만 그대로"
    # S5 오늘·저장 승인 대기 = React(features/today, R4-2) — 옛 쪽은 라우팅만. 줄·날짜 머리글·삭제 0·승인·제외는 Vitest TodayScreen.test.tsx
    assert 'else if (tab.view === "today2") uiMount("today", ["today", R.a || "", R.b || ""]);' in js
    assert 'else if (tab.view === "inbox") uiMount("today", ["inbox", R.a || ""]);' in js
    assert 'if (R.tab === "_inbox" && !["pending", "applied", "excluded", "expired", "all"].includes(R.a)) return "#_today/inbox/" + encodeURIComponent(R.a);' in js
    assert "// ── 오늘 (PR ①-b S5)" not in js and "/api/inbox" not in js, "옛 쪽 오늘·승인 대기 코드·API 0"
    for i, (lt, dk) in enumerate(zip(("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
                                     ("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767")), 1):
        assert f"--ax{i}: {lt};" in html and f"--ax{i}: {dk};" in html, ("축 색", i)
    print("OK — 옛 쪽 「나」 접점(uiMount·통계 0·미저장 uiDirty·분기점) · Setup 페이지 6·레이아웃 쓰기 한 곳·version·crm:state·옛 주소 replace · "
          "오늘·승인 대기 라우팅(React) · 축 색 토큰 · 표시 낱말 통과")


TRASH_ASK = "삭제하면 휴지통으로 이동해요. 삭제 시각부터 168시간 동안 복원할 수 있고, 이후 서버 정리 때 영구 삭제돼요."   # r4 §8 글자 그대로


def test_static_trash():
    """휴지통 PR-1 화면 — 옛 쪽엔 스위치(trashOn → Setup 「휴지통」 페이지 줄)만 남는다. 상세의 [삭제]는 React — 「나」(MeActs.test.tsx)·
    구조 서랍(StructureScreen.test.tsx, R5b-1)·활동(ActivityScreen.test.tsx)·자료 종류(ObjectsScreen.test.tsx). 접점·문구 한 벌 = ui/src/shared/item.ts."""
    html = (HERE / "app.html").read_text(encoding="utf-8")
    js = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
    tr = js[js.index("// ── 휴지통 (trash PR-1)"):js.index("// ── /휴지통 ──")]
    assert "const trashOn = () => !!(S && S.switches && S.switches.trash);" in tr
    assert "/api/trash" not in js and "data-trash" not in js, "옛 쪽 휴지통 API·버튼 0(React 로)"
    item = (HERE / "ui" / "src" / "shared" / "item.ts").read_text(encoding="utf-8")
    assert f'TRASH_ASK = "{TRASH_ASK}"' in item and '"/api/trash/move"' in item and 'TRASH_DONE = "휴지통으로 옮겼어요."' in item, "r4 §8 문구·이동 접점 한 벌"
    for f in ("me", "objects", "activity"):
        t = (HERE / "ui" / "src" / "features" / f / "text.ts").read_text(encoding="utf-8")
        assert "TRASH_ASK = " not in t and 'from "../../shared/item"' in t, (f, "삭제 문구 사본 0")
    code = "\n".join(l for l in item.splitlines() if not l.lstrip().startswith("//"))
    assert "처리 중" not in code and "재시도 중" not in code and "예정" not in code, "「영구 삭제 처리 중·재시도 중·예정」 화면 상태 0(r4 §8)"
    assert 'const setupPages = () => trashOn() ? SETUP_PAGES.concat([["trash", "휴지통"]]) : SETUP_PAGES;' in js
    assert "setupPages().some(p => p[0] === R.a)" in js and "else if (page === \"trash\") uiMount(\"trash\");" in js
    assert "남기지 않" not in html, "「남기지 않음·않기·않았어요」 0 — 표현은 「반영 안 함」 하나"
    print("OK — 휴지통 정적(옛 쪽 = 스위치·Setup 페이지 · 접점·r4 §8 문구 한 벌 shared/item.ts · 사본 0 · 처리 중 상태 0 · 반영 안 함) 통과")


def trash_run(scenario):
    """휴지통 절 실행(node) — 휴지통 절(스위치) + Setup 페이지 목록 + 날짜·esc 도우미. 상세 [삭제]는 React(Vitest MeActs·StructureScreen).
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
    stub = """let S = null, coreFlash = null;
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
    """스위치별 차이 — 꺼짐 = 휴지통 페이지 0 · 켜짐 = Setup 「휴지통」. 상세 [삭제] 버튼은 React — Vitest MeActs·StructureScreen.test.tsx."""
    o = trash_run("""
const snap = () => ({on: trashOn(), pages: setupPages().map(p => p[0])});
S = {switches: {converse: true}}; out.none = snap();
S = {switches: {trash: false}}; out.off = snap();
S = {switches: {trash: true}}; out.on = snap();
""")
    for k in ("none", "off"):
        s = o[k]
        assert s["on"] is False and "trash" not in s["pages"], (k, "꺼짐 = 페이지 0")
    s = o["on"]
    assert s["on"] is True and s["pages"][-1] == "trash" and s["pages"][:6] == ["layout", "structure", "objects", "devices", "map", "help"]
    print("OK — 휴지통 스위치(꺼짐·필드 없음 = 페이지 0 · 켜짐 = Setup 휴지통) 통과")


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
    for w in ('fetch(url, {method: "POST"', '[name="kind"][value="privacy"]', '$("desk-dlg").showModal()'):
        assert w in html, w
    assert 'postJSON("/api/optional-consent", { kind: "struct_names", on })' in (HERE / "ui" / "src" / "features" / "defs" / "stdApi.ts").read_text(encoding="utf-8"), "이름 공유 = 같은 API(내 구조 설정, React)"
    for w in ("/api/desk-visibility", "desk_hidden", "deskPeek", 'id="desk"'):   # Q1b: 화면은 숨김 상태를 안 쓴다
        assert w not in html, w

    # A3 구조 정의 보기·편입 대화창(Q4·Q5) — 화면은 React(server/ui/src/features/defs, R5b-1 · 동작 = Vitest DefsScreen.test.tsx).
    # 여기엔 서버 정본과 같아야 하는 글자·코드(잠금 영향·재검토 사유)와 옛 쪽에 남은 자리(그래프 토큰·CSS·주소 replace)만 본다.
    tokens = structure_svg.tokens_css(dark_attr=True, dark_media=False)
    ui = HERE / "ui" / "src"
    dtext = (ui / "features" / "defs" / "text.ts").read_text(encoding="utf-8")
    dlg = (ui / "features" / "defs" / "StdDialog.tsx").read_text(encoding="utf-8")
    api = (ui / "features" / "defs" / "stdApi.ts").read_text(encoding="utf-8")
    note = (ui / "shared" / "ReviewNote.tsx").read_text(encoding="utf-8")
    assert 'if (R.a === "defs") return "#_setup/structure";' in html and 'href="#_settings/structure"' in (ui / "features" / "structure" / "StructureScreen.tsx").read_text(encoding="utf-8"), \
        "구조 정의 보기·라우트 = 내 구조 설정(옛 #structure/defs 는 replace)"
    assert '"/api/std/preview"' in api and '"/api/std/choose"' in api and "confirmed_meaning: true, expected_revision: o.object ? o.object.revision : null" in api
    for w in ('id="std-dlg"', 'type="checkbox"', "disabled={!checked}", "같은 뜻으로 쓴다"):
        assert w in dlg, w
    assert "<dialog" not in html.replace('<dialog id="desk-dlg"', "").replace('<dialog id="dlg"', "").replace('<dialog id="name-dlg"', "").replace('<dialog id="leave-dlg"', ""), "편입 대화창 = React"
    for code in contract.LOCKED_CHANGES:   # 잠금 영향 문구 — 서버 코드 전부
        assert re.search(rf"\b{code}: \"", dtext), code
    for code in contract.REVIEW_REASONS:
        assert re.search(rf"\b{code}: \"", note), code
    fix = note[note.index("const FIX"):note.index("};", note.index("const FIX"))]
    assert "author_unknown" in fix and "processed" in fix and "external" not in fix and "deleted" not in fix, "정정 안내는 두 사유만"
    assert "record_provenance_set" not in html + note and "verbatim 으로" not in html + note, "도구명·「바꾸면 풀린다」 안내 없음"
    assert (structure_svg.node_anchor(0), structure_svg.rel_anchor(0), structure_svg.core_anchor("record")) == (
        "dmo-o1", "dmo-r1", "dmo-core-record"), "목록 id 꼴(features/defs/DefsList.tsx) = structure_svg 앵커"
    dlist = (ui / "features" / "defs" / "DefsList.tsx").read_text(encoding="utf-8")
    assert "id={`dmo-o${i + 1}`}" in dlist and "id={`dmo-r${i + 1}`}" in dlist and "id={`dmo-core-${x.kind}`}" in dlist
    assert tokens in html and "prefers-color-scheme" not in tokens and "prefers-color-scheme" not in html, "토큰 = 테마 토글(data-theme)만"
    assert '[data-theme="dark"]' in tokens
    assert '<th scope="col">출처</th>' not in dlist and '<th scope="col">구분</th><th scope="col">보호</th>' in dlist, "필드 표 열 머리 = 구분(정의 구분 뜻의 '출처' 0)"
    assert "min-width: 420px" in html and ".dmo { background: var(--card); border: 1px solid var(--line); border-radius: 8px; padding: 8px; overflow-x: auto; }" in html
    for w in ("#std-dlg ul", "#std-dlg .stdok"):   # React 대화창이 같은 id 로 옛 CSS 를 쓴다(CSS 번들은 R5b-2)
        assert w in html, w

    def outside_marks(pos, what):   # 관리자 /app 도 쓰는 대화창 — <!--user-->/<!--admin--> 구간 표식 밖
        for mark in ("<!--user-->", "<!--admin-->"):
            for a in [m.start() for m in re.finditer(re.escape(mark), html)]:
                b = html.index(mark.replace("<!--", "<!--/"), a)
                assert not (a < pos < b), (what, "구간 안", mark)

    # A4 코어 표시명 — app.html LABELS(std@1 표시명 절의 화면 몫. web.CORE_LABEL 비교는 test_tools 에 남는다)
    assert all(f'{k}: "{v}"' in html for k, v in (("question", "질문"), ("record", "기록"), ("candidate", "후보"))), "app.html LABELS"

    # A5 24h 화면 — 플래그 0 · 이름 관문·새 경로·탭 · 안내 문구 · 재검토 표시 · 이름 대화창(구간 밖) · 메뉴 · 옛 탐색 0(R5a)
    assert "FEATURE-OFF" not in html, "플래그 제거 — 화면에도 FEATURE-OFF 0"
    for w in ('if (needName()) return renderNameGate();', 'data-form="name"',
              "실명이 아니어도 돼요. 다른 사람에게 보이지 않고 운영자 화면에도 나오지 않아요.",
              '"/api/me/name"',
              'id: "_me"', 'id: "_obj"', 'id: "_settings"',
              "const tabsList = () => [NAVTAB._me, NAVTAB._today];",   # PR ①-b 탭: 나 · 오늘 · Setup(톱니)
              'if (R.tab === "_settings") return "#_setup/structure";', "삭제 완료"):
        assert w in html, w
    # 사람·읽고 든 생각 쓰기·안내 문구 = React 자료 종류(R4-2 — features/objects, 화면 동작은 Vitest ObjectsScreen.test.tsx)
    objs = HERE / "ui" / "src" / "features" / "objects"
    otext, oapi = (objs / "text.ts").read_text(encoding="utf-8"), (objs / "objApi.ts").read_text(encoding="utf-8")
    assert '"/api/people"' in oapi and '"/api/reflections"' in oapi
    assert re.search(r"REFL_HELP\s*=\s*\"출처를 접한 뒤 내가 한 생각만 적어요\. 다른 사람의 말·경험·생각을 옮기는 곳이 아니에요\.\"", otext)
    assert re.search(r"PERSON_HELP\s*=\s*\"별칭도 그 사람을 알아볼 수 있으면 개인정보예요\.\"", otext)
    assert "<ReviewNote review={c.review} />" in (HERE / "ui" / "src" / "features" / "sheet" / "RecordTab.tsx").read_text(encoding="utf-8"), "기록 화면 재검토 표시(shared/ReviewNote)"
    outside_marks(html.index('<dialog id="name-dlg"'), "name-dlg")
    menu = html[html.index('id="acct-menu"'):html.index("</details>")]
    for a in ("name", "settings"):
        assert f'data-acct="{a}"' in menu, a
    for w in ("nav-dlg", "acct-nav", "/api/nav/accept", "navNew", "새 탐색으로 바꾸기"):   # R5a 옛 탐색 삭제 — 모든 계정 새 탐색
        assert w not in html, w

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
    db.item_propose(uid, pd["id"], pd["revision"], p["item_id"], 1, "P-1", "견본 기준 고침", "본문", {}, links)   # 서랍 제안 diff(R5b-1)
    a = db.item_propose(uid, ax["id"], ax["revision"], None, 0, None, "견본 축", "", {}, [])
    db.item_decide(uid, a["item_id"], 0, a["proposal_id"], "apply")
    db.record_attach(uid, rec["id"], axes=[a["item_id"]])
    db.person_save(uid, "견본 사람")
    db.source_reflection_save(uid, src["id"], "summary", "견본 생각")
    ui = HERE / "ui" / "src"
    st_sample = json.loads((ui / "shared" / "state.sample.json").read_text(encoding="utf-8"))
    me_sample = json.loads((ui / "features" / "me" / "me.sample.json").read_text(encoding="utf-8"))
    item_sample = json.loads((ui / "features" / "structure" / "item.sample.json").read_text(encoding="utf-8"))
    std_sample = json.loads((ui / "features" / "defs" / "std.sample.json").read_text(encoding="utf-8"))
    try:
        site.dev, site.dev_user = True, SAMPLE
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            st = (await h.get("/api/state")).json()
            got = {"stats": (await h.get("/api/me/stats")).json(), "layout": (await h.get("/api/me/layout")).json(),
                   "journal": (await h.get("/api/journal", params={"id": rec["id"]})).json(),
                   "preview": (await h.post(f"/api/records/{rec['id']}/body/preview", headers={"origin": PUBLIC},
                                            json={"expected_revision": 1, "body": "견본 본문 입력 담당을 먼저 정했다. 덧붙임"})).json(),   # 판단과 겹치지 않는 자리(연결 걸린 겹침 = 잠금)
                   "item": (await h.get("/api/item", params={"id": p["item_id"]})).json(), "std": (await h.get("/api/std/preview")).json()}
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
    # R5b-1 구조 서랍·편입 미리보기 — 견본 ⊆ 실제(손 사본 타입은 쓰는 조각만) · 출처 라벨 = structure_svg 정본
    assert got["item"]["proposal"] and got["item"]["targets"] and got["item"]["history"] and got["std"]["objects"], "견본 대조에 쓸 행"
    for k, smp in (("item", item_sample), ("std", std_sample)):
        bad = _cmp(smp, got[k], k, exact=False)
        assert not bad, (bad, "item.sample.json·structApi.ts / std.sample.json·stdApi.ts 의 타입을 같이 고친다")
    import structure_svg
    assert st["origin_labels"] == {"text": structure_svg.ORIGIN_TEXT, "category": structure_svg.ORIGIN_CATEGORY}, "출처 라벨 = 서버 정본 하나"
    assert "origin_labels" not in db.state(uid), "MCP state_get 에는 없음(/app 전용)"
    print("OK — API 견본 대조(state ⊆ 실제 · stats·layout·journal 키·값 타입 = me.sample.json · journal revision·author_kind · 서랍·편입 미리보기 ⊆ 실제 · origin_labels) 통과")


async def run():
    db.init_schema()
    cleanup()
    try:
        test_static()
        test_static_trash()
        test_trash_switch()
        test_static_moved()
        await test_records_api()
        await test_ui_samples()
    finally:
        cleanup()
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
