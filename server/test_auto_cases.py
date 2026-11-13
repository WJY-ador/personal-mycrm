"""오류 자동 Case(2026-11-13 명세 1.4) 시험 — 합성 PostgreSQL.

실행: DATABASE_URL=postgresql://localhost/crm_test_onewin_auto python3 server/test_auto_cases.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

본다: 경로 셋(장치 토큰, 앱 로그인 세션, 웹 세션)과 출처 강제 · 형식 거절(경로, URL, 이메일, 문장, 모르는 키, 중복 키, 시각 범위)
· 같은 묶음 = 한 Case 에 횟수만 · 다른 코드 = 새 Case · 사용자 하루 20 상한(버리고 집계만) · 스위치 auto_cases 꺼짐 = off
· 운영 콘솔 목록과 상세, 사용자 내 문의에 자동 표시 필드 · 사람이 쓰는 문의 한도에 자동 Case 가 안 들어감 · Case 에 본문, 토큰 없음
· 장치 허용 규칙 기본값 = 전부, 기존 장치 이관.
"""
import json
import os
import sys
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_onewin_auto). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = ""
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_SESSION_SECRET"] = "auto-cases-test-secret"
os.environ.pop("CRM_AUTO_CASES_ENABLED", None)
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

import admin_db  # noqa: E402
import auto_cases  # noqa: E402
import db  # noqa: E402
import features  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402

EMAILS = ("ac-a@example.com", "ac-b@example.com")
N = 0


def ok(msg):
    global N
    N += 1
    print(f"ok {N} - {msg}", flush=True)


def now_z(delta=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=delta)).strftime("%Y-%m-%dT%H:%M:%SZ")


def body(**kw):
    b = {"source": "app", "stage": "sync/run-once", "code": "HTTP-503", "app_version": "0.1.7", "os": "mac", "occurred_at": now_z()}
    b.update(kw)
    return {k: v for k, v in b.items() if v is not ...}


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def set_feature(on: bool):
    with db.tx() as c:
        c.execute("INSERT INTO org_features (feature, enabled) VALUES ('auto_cases', %s) ON CONFLICT (feature) DO UPDATE SET enabled = EXCLUDED.enabled",
                  (on,))
    features.clear_cache()


def autos(uid):
    with db.tx() as c:
        return c.execute("SELECT * FROM tickets WHERE user_id=%s AND via='auto' ORDER BY created, id", (uid,)).fetchall()


def main_test():
    db.init_schema()
    cleanup()
    A = db.user_by_email(EMAILS[0])["id"]
    B = db.user_by_email(EMAILS[1])["id"]
    for uid, name in ((A, "자동A"), (B, "자동B")):
        with db.tx() as c:
            c.execute("UPDATE users SET display_name=%s WHERE id=%s", (name, uid))

    # ── 기본 허용 규칙 = 전부(명세 1.2) · 기존 장치 이관 ──
    assert imports.DEFAULT_POLICY == {"actions": list(imports.ACTIONS), "transform_versions": list(imports.TRANSFORMS), "axes": []}
    dev = imports.device_connect(A, "자동시험 PC")
    token, did = dev["token"], dev["device"]["id"]
    assert dev["device"]["policy"] == imports.DEFAULT_POLICY, dev["device"]["policy"]
    narrow = {"actions": ["like"], "transform_versions": ["self-text/1"], "axes": []}
    with db.tx() as c:
        c.execute("UPDATE import_streams SET policy=%s WHERE id=%s AND user_id=%s", (Jsonb(narrow), did, A))
        rev = c.execute("SELECT policy_revision FROM import_streams WHERE id=%s", (did,)).fetchone()["policy_revision"]
        c.execute("DELETE FROM schema_marks WHERE key=%s", (imports.POLICY_ALL_MARK,))
        assert imports.migrate_device_policy(c) >= 1
        r = c.execute("SELECT policy, policy_revision FROM import_streams WHERE id=%s", (did,)).fetchone()
        assert r["policy"] == imports.DEFAULT_POLICY and r["policy_revision"] == rev + 1, r
        assert imports.migrate_device_policy(c) == 0, "표식이 있으면 다시 돌지 않는다"
    ok("기본 허용 규칙 = 모든 행동과 변환, 축 0개 · 기존 장치 이관은 표식 한 번, revision +1")

    # ── 스위치 기본 켜짐(행도 env 도 없을 때) ──
    with db.tx() as c:
        c.execute("DELETE FROM org_features WHERE feature='auto_cases'")
    features.clear_cache()
    assert features.org_on("auto_cases") is True
    os.environ["CRM_AUTO_CASES_ENABLED"] = "0"
    assert features.org_on("auto_cases") is False, "env 비상 끄기"
    os.environ.pop("CRM_AUTO_CASES_ENABLED")
    ok("auto_cases 기본 켜짐 · env 비상 끄기")

    # ── 형식 검사(parse) ──
    def bad(b, raw=None, sources=auto_cases.SOURCES_DEVICE):
        try:
            auto_cases.parse(raw if raw is not None else json.dumps(b).encode(), sources)
        except db.CrmError as e:
            return e.code
        return None
    assert auto_cases.parse(json.dumps(body()).encode(), auto_cases.SOURCES_DEVICE)["count"] == 1
    for b in (body(stage="C:/Users/me/x"), body(stage="sync/run once"), body(stage="a/b/c/d"), body(code="a@b.com"),
              body(code="https://x.y"), body(code="연결 실패"), body(code="x" * 49), body(app_version="v1"),
              body(os="linux"), body(occurred_at=now_z(-8 * 86400)), body(occurred_at=now_z(600)), body(occurred_at="2026-11-13"),
              body(count=0), body(count=1001), body(count=True), body(extra="x"), body(stage=...), body(source="web")):
        assert bad(b) == "ARG-INVALID", b
    assert bad(None, raw=b'{"source":"app","source":"agent"}') == "ARG-INVALID", "중복 키"
    assert bad(None, raw=b"x" * 3000) == "PAYLOAD-LIMIT"
    assert bad(body(source="app"), sources=auto_cases.SOURCES_WEB) == "ARG-INVALID", "웹 세션은 web 만"
    ok("형식 — 경로, URL, 이메일, 문장, 모르는 키, 중복 키, 시각 범위, 출처 강제를 거절")

    set_feature(True)
    import asyncio

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            sess = {"crm_session": main.site.session_value(A)}
            # 장치 토큰 경로
            r = await h.post("/api/device/error-reports", json=body(), headers={"authorization": "Bearer " + token})
            assert r.status_code == 200 and r.json() == {"accepted": True, "state": "created"}, r.text
            r = await h.post("/api/device/error-reports", json=body(count=4, source="agent"), headers={"authorization": "Bearer " + token})
            assert r.json()["state"] == "created", "다른 출처 = 다른 묶음"
            r = await h.post("/api/device/error-reports", json=body(count=4), headers={"authorization": "Bearer " + token})
            assert r.json() == {"accepted": True, "state": "counted"}, r.text
            r = await h.post("/api/device/error-reports", json=body(), headers={"authorization": "Bearer imp_x.y.z"})
            assert r.status_code == 401, r.status_code
            r = await h.post("/api/device/error-reports", json=body(source="web"), headers={"authorization": "Bearer " + token})
            assert r.status_code == 400
            # 앱 로그인 세션 경로 — 앱 머리글 필수
            r = await h.post("/desktop/error-reports", json=body(stage="connect/auto", code="TOKEN-REVOKED"), cookies=sess,
                             headers={"x-mycrm-desktop": "1"})
            assert r.status_code == 200 and r.json()["state"] == "created", r.text
            r = await h.post("/desktop/error-reports", json=body(), cookies=sess)
            assert r.status_code == 403
            r = await h.post("/desktop/error-reports", json=body(), headers={"x-mycrm-desktop": "1"})
            assert r.status_code == 401
            # 웹 세션 경로 — Origin 필수, 출처 web 만
            r = await h.post("/api/error-reports", json=body(source="web", stage="api/state", code="HTTP-500", app_version=""), cookies=sess,
                             headers={"origin": PUBLIC})
            assert r.status_code == 200 and r.json()["state"] == "created", r.text
            r = await h.post("/api/error-reports", json=body(source="web"), cookies=sess, headers={"origin": "https://evil.test"})
            assert r.status_code == 403
            r = await h.post("/api/error-reports", json=body(), cookies=sess, headers={"origin": PUBLIC})
            assert r.status_code == 400, "웹 세션으로 app 출처를 보낼 수 없다"
    asyncio.run(run())
    rows = autos(A)
    assert len(rows) == 4, [r["auto_key"] for r in rows]
    first = next(r for r in rows if r["auto_key"] == "app|sync/run-once|HTTP-503")
    assert first["auto_count"] == 5 and first["kind"] == "bug" and first["status"] == "open" and first["auto_last"] >= first["auto_first"]
    assert first["auto_meta"]["os"] == "mac" and first["auto_meta"]["app_version"] == "0.1.7"
    blob = json.dumps([dict(r) for r in rows], default=str)
    assert token not in blob and token.split(".")[-1] not in blob and "@" not in blob, "Case 에 토큰, 이메일 없음"
    ok("경로 셋 — 장치 토큰, 앱 로그인 세션(앱 머리글), 웹 세션(Origin) · 같은 묶음은 횟수만 · 출처는 인증이 정한다")

    # ── 사용자 하루 20 상한 ──
    for i in range(30):
        st = db.ticket_auto(A, "app", "update/install", f"EXIT-{i}", "0.1.7", "mac", now_z())
        if i < 16:
            assert st == "created", (i, st)
        else:
            assert st == "capped", (i, st)
    assert len(autos(A)) == db.AUTO_DAILY_USER
    assert db.ticket_auto(A, "app", "sync/run-once", "HTTP-503", "0.1.7", "mac", now_z()) == "counted", "상한이어도 있는 묶음은 센다"
    ok("사용자 하루 20 — 넘치면 만들지 않고, 있는 묶음 횟수는 계속 센다")

    # ── 사람이 쓰는 문의 한도에 자동 Case 가 안 들어간다 ──
    t = db.ticket_add(A, "bug", "손으로 쓴 문의", "web")
    assert t["kind"] == "bug"
    ok("자동 Case 20건이 있어도 사람이 쓰는 문의는 접수된다")

    # ── 스위치 꺼짐 ──
    set_feature(False)
    r = auto_cases.record(B, json.dumps(body()).encode(), auto_cases.SOURCES_DEVICE)
    assert r == {"accepted": False, "state": "off"} and not autos(B)
    set_feature(True)
    ok("auto_cases 꺼짐 = accepted false, Case 없음")

    # ── 운영 콘솔 목록·상세, 사용자 내 문의 ──
    rows, _over = admin_db.tickets_list(admin_db.VIEWER_ADMIN, status="all")
    mine = [r for r in rows if r["email"] == EMAILS[0] and r["via"] == "auto"]
    assert mine and all(r["auto_count"] >= 1 and r["auto_first"] and r["auto_last"] for r in mine)
    d = admin_db.ticket_detail(admin_db.VIEWER_ADMIN, first["id"])
    assert d["via"] == "auto" and d["auto_count"] == 6 and d["auto_meta"]["stage"] == "sync/run-once", d
    my = db.tickets_mine(A)
    auto_mine = [x for x in my if x["via"] == "auto"]
    assert auto_mine and all("auto_count" in x for x in auto_mine)
    one = db.ticket_get_mine(A, first["id"])
    assert one["auto_count"] == 6 and "auto_meta" not in one
    ok("운영 콘솔 목록·상세에 자동 횟수·첫/마지막 시각 · 사용자 내 문의에도 보인다(묶음 메타는 운영자만)")

    cleanup()
    print(f"\n{N} 항목 통과")


if __name__ == "__main__":
    main_test()
