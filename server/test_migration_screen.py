"""웹 시험 — 이관 화면(2026-11-02, notes 이관경로-API계약 「웹 세션 경로」)의 서버 쪽. 화면은 React(R4 — server/ui/src/features/migration):
화면 동작(꺼짐 안내·토큰 한 번만·체크 하나씩·확인창 숫자·반영 = plan_hash·오류 문구·본문 펼침·영수증)은 Vitest MigList·MigPlan,
토큰·본문 저장 0·이관 토큰 경로 0 은 Vitest arch.test.ts 가 본다.

실행: DATABASE_URL=postgresql://localhost/crm_test_migration_screen python3 server/test_migration_screen.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

A. HTTP — 화면이 읽는 응답 키(enabled·allowed·token_days·tokens·plans·limits) · 발급 토큰.
B. API 견본 대조 — ui/src/features/migration/migration.sample.json(토큰·plan 목록·확인·본문·영수증) ⊆⊇ 실제 응답(키 집합·값 타입).
   TS 쪽은 migration.sample.test.ts 의 satisfies(tsc).
"""
import asyncio
import json
import os
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_migration_screen). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ms-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
import migration as M  # noqa: E402
import test_migration_path as TMP  # noqa: E402  (항목 만들기·stage 도우미 재사용 — main_ 은 돌지 않는다)
from test_sample_shape import cmp  # noqa: E402

os.environ["CRM_DEV_USER"] = "ms-main@example.com"   # test_migration_path 가 import 때 바꾼 값을 되돌린다
MAIN = "ms-main@example.com"


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = %s", (MAIN,)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


async def test_http():
    site = main.site
    real = site.dev, site.dev_user
    old = {k: os.environ.get(k) for k in ("CRM_BOARD_MIGRATION_ENABLED", "CRM_BOARD_MIGRATION_USERS")}
    uid = db.user_by_email(MAIN)["id"]
    db.display_name_set(uid, "이관화면")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            site.dev, site.dev_user = True, MAIN
            os.environ["CRM_BOARD_MIGRATION_ENABLED"], os.environ["CRM_BOARD_MIGRATION_USERS"] = "", ""
            t = (await h.get("/api/migration-tokens")).json()
            assert t["enabled"] is False and t["allowed"] is False and t["tokens"] == [] and t["token_days"] == 14
            os.environ["CRM_BOARD_MIGRATION_ENABLED"], os.environ["CRM_BOARD_MIGRATION_USERS"] = "1", uid
            r = await h.post("/api/migration-tokens", json={}, headers={"origin": PUBLIC})
            assert r.status_code == 200 and r.json()["token"].startswith("mig_mt_"), r.status_code
            t = (await h.get("/api/migration-tokens")).json()
            assert t["enabled"] and t["allowed"] and set(t["tokens"][0]) >= {"id", "label", "created_at", "expires_at", "revoked_at", "last_used_at", "active"}
            p = (await h.get("/api/migrations")).json()
            assert p["plans"] == [] and set(p["limits"]) >= {"daily", "used_today", "plan_items", "plan_days", "open_plans"}
    finally:
        site.dev, site.dev_user = real
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("OK — HTTP(화면이 읽는 키: enabled·allowed·token_days·tokens·plans·limits · 발급 토큰 mig_mt_)")


async def test_ui_samples():
    """견본 = 화면이 읽는 다섯 응답. 견본을 만든 자료와 같은 꼴(반영한 plan 1 → 확인 대기 plan 1, 첫 항목 = 제목 있는 기록)."""
    site = main.site
    real = site.dev, site.dev_user
    old = {k: os.environ.get(k) for k in ("CRM_BOARD_MIGRATION_ENABLED", "CRM_BOARD_MIGRATION_USERS")}
    uid = db.user_by_email(MAIN)["id"]
    db.display_name_set(uid, "이관견본")
    os.environ["CRM_BOARD_MIGRATION_ENABLED"], os.environ["CRM_BOARD_MIGRATION_USERS"] = "1", uid
    sample = json.loads((HERE / "ui" / "src" / "features" / "migration" / "migration.sample.json").read_text(encoding="utf-8"))
    try:
        tok = {"user_id": uid, "token_id": None}
        M.token_issue(uid)
        a = TMP.stage(tok, [TMP.rec(101, "회의 전에 안건을 먼저 공유한다.", title="회의 메모"), TMP.source(102, "회고 노트")])
        M.plan_apply(uid, a["plan_id"], a["plan_hash"])
        b = TMP.stage(tok, [TMP.rec(111, "고객 요청은 하루 안에 답한다.", title="응대 원칙 메모"), TMP.principle(113, "먼저 묻고 정한다")])
        site.dev, site.dev_user = True, MAIN
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            got = {"tokens": (await h.get("/api/migration-tokens")).json(), "plans": (await h.get("/api/migrations")).json(),
                   "detail": (await h.get(f"/api/migrations/{b['plan_id']}")).json(), "item": (await h.get(f"/api/migrations/{b['plan_id']}/items/0")).json(),
                   "receipt": (await h.get(f"/api/migrations/{a['plan_id']}/receipt")).json()}
    finally:
        site.dev, site.dev_user = real
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    assert got["plans"]["plans"][0]["state"] == "sealed" and got["detail"]["items"][0]["title"] == "응대 원칙 메모" and got["item"]["payload"], got["plans"]
    assert got["receipt"]["items"][0]["stored_hash"] == got["receipt"]["items"][0]["content_hash"], "영수증 첫 행 = 해시 일치"
    for k in ("tokens", "plans", "detail", "item", "receipt"):
        bad = cmp(sample[k], got[k], k, exact=True)
        assert not bad, (bad, "migration.sample.json·features/migration/migApi.ts 의 타입을 같이 고친다")
    print("OK — API 견본 대조(이관 토큰·plan 목록·확인·본문·영수증 = 견본 키·값 타입) 통과")


async def run():
    db.init_schema()
    cleanup()
    try:
        await test_http()
        cleanup()
        await test_ui_samples()
    finally:
        cleanup()
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
