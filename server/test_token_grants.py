"""PC 연결·토큰 대화 발급 시험 (2026-11-02 가안 2, notes/2026-11-02_pc-connect-구현계획.md §8) — 합성 PostgreSQL.

실행: DATABASE_URL=postgresql://localhost/crm_test_token_grants python3 server/test_token_grants.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

본다: 스키마(새 표 2·M2 열, 옛 DB → 같은 모양, 멱등, IP 열 없음) · 앱 라우트(Origin·헤더·세션 401·IP 분당·본문 상한) · 설치본 upsert·M3 NOT-OWNER
· grant 상태기계(waiting → delivered·expired·cancelled, 재사용 GRANT-USED, 만료 GRANT-EXPIRED, 계정·설치본 불일치) · 지목 규칙·NO-ACTIVE-APP
· 한도(열린 3·하루 10·설치본 10) · 자동 연결·교체·해제 기록(DEVICE-REVOKED) · M2(옛 토큰 = 새 토큰 첫 사용 때 무효, 대기 1개)
· Bearer 교체·90일 무업로드 · 이관 scope(스위치·allowlist·NAME-REQUIRED 재검사) · facade(bind·K2·NAME-REQUIRED) · 사용자 삭제 cascade
· CLI --browser loopback(redirect_uri 검사·302·PKCE·일회용·앱 코드와 분리·scope) · 응답(redeem·auto·rotate·cli 제외)·오류·감사·로그·grant 표에 토큰 값 없음.
"""
import asyncio
import base64
import contextlib
import hashlib
import secrets
import io
import json
import logging
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_token_grants). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "tg-a@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
os.environ["CRM_SESSION_SECRET"] = "token-grants-test-secret"
os.environ["CRM_BOARD_MIGRATION_ENABLED"] = ""
os.environ["CRM_BOARD_MIGRATION_USERS"] = ""
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402
from mcp.client import Client  # noqa: E402

import db  # noqa: E402
import facade  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402
import migration  # noqa: E402
import token_grants as TG  # noqa: E402

A_EMAIL, B_EMAIL, N_EMAIL = "tg-a@example.com", "tg-b@example.com", "tg-n@example.com"
EMAILS = (A_EMAIL, B_EMAIL, N_EMAIL)
APP_H = {"x-mycrm-desktop": "1"}
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
TOKENS: list[str] = []   # 시험 중 받은 토큰 원문 — 로그·감사·grant 표·다른 응답에 없어야 한다
SECRETS_SEEN: list[str] = []   # 토큰의 비밀 부분(마지막 조각)


def ok(msg):
    print("OK —", msg, flush=True)


def keep(tok):
    TOKENS.append(tok)
    SECRETS_SEEN.append(tok.rsplit(".", 1)[-1])
    return tok


def no_token(text, what):
    for s in SECRETS_SEEN:
        assert s not in text, f"{what} 에 토큰 값"


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (code, e.code, e.message)
        for s in SECRETS_SEEN:
            assert s not in f"{e.message} {e.action} {getattr(e, 'detail', '')}", "오류에 토큰 값"
        return e
    raise AssertionError(f"{code} 가 나야 하는데 성공했다")


def sql(q, args=()):
    with db.tx() as c:
        cur = c.execute(q, args)
        return cur.fetchall() if cur.description else cur.rowcount


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def switches(on=True, users=()):
    os.environ["CRM_BOARD_MIGRATION_ENABLED"] = "1" if on else ""
    os.environ["CRM_BOARD_MIGRATION_USERS"] = ",".join(users)


# ── MCP(facade) ────────────────────────────────────────

def val(res):
    sc = getattr(res, "structured_content", None)
    if sc is not None:
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    return json.loads(res.content[0].text)


def code(res):
    assert res.is_error, ("오류가 아님", res.content[0].text[:300])
    m = CODE.search(res.content[0].text)
    return m.group(1) if m else "SDK"


def detail(res):
    t = res.content[0].text
    return json.loads(t[t.index(" detail=") + len(" detail="):])


async def call(c, op, params=None, bind=None):
    a = {"op": op, "params": params or {}}
    if bind is not None:
        a["bind"] = bind
    r = await c.call_tool(facade.OPS[op].tier, a)
    for x in r.content:
        no_token(x.text, f"MCP {op} 응답")
    return r


async def preview(c, op, params):
    r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": op, "params": params}})
    assert not r.is_error, r.content[0].text[:400]
    no_token(r.content[0].text, "preview")
    return val(r)


async def bound(c, op, params):
    return await call(c, op, params, (await preview(c, op, params))["bind"])


# ── HTTP(앱) ───────────────────────────────────────────

def H(uid=None, origin=None, header=True):
    """앱 창 하나 — 세션 쿠키(uid) + X-MyCRM-Desktop."""
    h = httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC,
                          headers={**(APP_H if header else {}), **({"origin": origin} if origin else {})})
    if uid:
        h.cookies.set("crm_session", main.site.session_value(uid))
    return h


async def reg(h, name="집 맥", os_="darwin", iid=None, status=200):
    body = {"client_name": name, "os": os_}
    if iid:
        body["installation_id"] = iid
    r = await h.post("/desktop/installations", json=body)
    assert r.status_code == status, (r.status_code, r.text[:300])
    assert r.headers["cache-control"] == "no-store"
    return r.json()


async def poll(h, iid, status=200):
    main.site._grant_ips.clear()
    r = await h.get("/desktop/grants", params={"installation": iid})
    assert r.status_code == status, (r.status_code, r.text[:300])
    no_token(r.text, "폴링 응답")
    return r.json()


async def redeem(h, gid, iid, status=200):
    main.site._grant_ips.clear()
    r = await h.post(f"/desktop/grants/{gid}/redeem", json={"installation_id": iid})
    assert r.status_code == status, (r.status_code, r.text[:300])
    assert r.headers["cache-control"] == "no-store"
    j = r.json()
    if status == 200:
        keep(j["token"])
    else:
        no_token(r.text, "redeem 오류")
    return j


def bearer_ok(tok):
    return imports.authenticate("Bearer " + tok)


# ── 1) 스키마 ──────────────────────────────────────────

def _shape(c, tables):
    cols = c.execute("SELECT table_name, column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                     "WHERE table_schema=current_schema() AND table_name = ANY(%s) ORDER BY 1, 2", (list(tables),)).fetchall()
    cons = c.execute("SELECT conrelid::regclass::text AS t, conname, pg_get_constraintdef(oid) AS d FROM pg_constraint "
                     "WHERE connamespace = current_schema()::regnamespace AND conrelid::regclass::text = ANY(%s) ORDER BY 1, 2",
                     (list(tables),)).fetchall()
    idx = c.execute("SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname=current_schema() AND tablename = ANY(%s) "
                    "ORDER BY 1, 2", (list(tables),)).fetchall()
    return [dict(r) for r in cols], [dict(r) for r in cons], [dict(r) for r in idx]


def test_schema():
    tables = ("import_streams", "desktop_installations", "token_grants", "admin_audit")
    db.init_schema()
    with db.tx() as c:
        want = _shape(c, tables)
    # 옛 DB 흉내 — 새 token/device 및 consent 표·M2 열·인덱스·CHECK 없음 · 감사 열거 옛 값
    with db.tx() as c:
        c.execute("DROP TABLE chat_consent_challenges, desktop_consent_keys, chat_provider_grants, token_grants, desktop_installations")
        c.execute("DROP INDEX ux_import_streams_pending")
        c.execute("ALTER TABLE import_streams DROP CONSTRAINT ck_import_streams_pending, DROP COLUMN pending_token_id, "
                  "DROP COLUMN pending_secret_hash, DROP COLUMN pending_expires_at")
        c.execute("ALTER TABLE admin_audit DROP CONSTRAINT admin_audit_action_check")
        c.execute("ALTER TABLE admin_audit ADD CONSTRAINT admin_audit_action_check CHECK (action IN ('bootstrap','recover','role_grant',"
                  "'role_revoke','web_signout','block','unblock','delete_notify','delete_run','delete_cancel','device_connect',"
                  "'device_reissue','device_revoke','device_policy','migration_apply','migration_extend','migration_close','migration_token'))")
    db.init_schema()
    db.init_schema()
    with db.tx() as c:
        assert _shape(c, tables) == want, "옛 DB 2회 = 새 DB 모양(열·이름 붙은 CHECK·인덱스)"
        cols = {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                                    "AND table_name='desktop_installations'").fetchall()}
    assert cols == {"user_id", "id", "client_name", "os", "device_id", "created_at", "last_login_at", "last_seen_at", "revoked_at"}, cols
    assert not any("ip" in x.split("_") or "host" in x or "path" in x for x in cols), "설치본 표에 IP·호스트·경로 없음"
    with db.tx() as c:
        gcols = {r["column_name"] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() "
                                                     "AND table_name='token_grants'").fetchall()}
    assert not any("token" in x or "secret" in x or "hash" in x for x in gcols), ("grant 표에 토큰·해시 열 없음", gcols)
    order = {t: i for i, t in enumerate(db.DELETE_TABLES)}
    assert order["token_grants"] < order["desktop_installations"] and "import_streams" in order
    ok("스키마(새 표 2 · M2 열·CHECK·UNIQUE · 감사 열거 4 · 옛 DB 2회 = 새 DB 모양 · 설치본 IP 없음 · grant 표 토큰 열 없음 · 삭제 순서)")


# ── 2) 앱 라우트 경계 · 설치본 ────────────────────────────

async def test_routes(A, B):
    site = main.site
    site.dev, site.dev_user = False, ""   # 운영처럼 — 세션 쿠키 없으면 401
    async with H() as h:
        r = await h.get("/desktop/grants", params={"installation": "di_" + "0" * 24})
        assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED", r.text
        r = await h.post("/desktop/installations", json={"client_name": "x", "os": "darwin"})
        assert r.status_code == 401
    async with H(A, origin="https://evil.example") as h:
        r = await h.post("/desktop/installations", json={"client_name": "x", "os": "darwin"})
        assert r.status_code == 403 and r.json()["code"] == "ORIGIN"
    async with H(A, header=False) as h:
        r = await h.post("/desktop/installations", json={"client_name": "x", "os": "darwin"})
        assert r.status_code == 403 and r.json()["code"] == "DESKTOP-HEADER"
        r = await h.get("/desktop/grants", params={"installation": "di_" + "0" * 24})
        assert r.status_code == 403
    async with H(A, origin="null") as h:
        a1 = await reg(h, "집 맥")
    async with H(A, origin=PUBLIC) as h:
        a1b = await reg(h, "집 맥 새 이름", "darwin", a1["installation_id"])
        assert a1b["installation_id"] == a1["installation_id"] and a1b["client_name"] == "집 맥 새 이름" and a1b["account_label"] == A_EMAIL
        assert a1b["device"] is None and a1b["revoked"] is False and a1b["poll_seconds"] == 30
        r = await h.post("/desktop/installations", json={"client_name": "x", "os": "beos"})
        assert r.status_code == 400 and r.json()["code"] == "ARG-INVALID"
        r = await h.post("/desktop/installations", json={"client_name": 3, "os": "darwin"})
        assert r.status_code == 400
        r = await h.post("/desktop/installations", content=b"{" + b" " * 5000 + b"}", headers={"content-type": "application/json"})
        assert r.status_code == 413 and r.json()["code"] == "PAYLOAD-LIMIT"
        e = await reg(h, "x", "darwin", "di_" + "f" * 24, status=404)
        assert e["code"] == "INSTALLATION-UNKNOWN"
    async with H(B) as h:
        e = await reg(h, "남의 PC", "win32", a1["installation_id"], status=403)
        assert e["code"] == "NOT-OWNER", "M3 — 다른 계정 설치본 id"
        await poll(h, a1["installation_id"], status=403)
    # IP 분당 상한(폴링·redeem 공유) — 10 넘으면 429 + retry-after
    async with H(A) as h:
        site._grant_ips.clear()
        codes = [(await h.get("/desktop/grants", params={"installation": a1["installation_id"]})).status_code for _ in range(11)]
        assert codes == [200] * 10 + [429], codes
        r = await h.post(f"/desktop/grants/tg_{'0' * 24}/redeem", json={"installation_id": a1["installation_id"]})
        assert r.status_code == 429 and "retry-after" in r.headers
        site._grant_ips.clear()
    # 설치본 한도 — 해제 안 된 것 10
    async with H(A) as h:
        ids = [a1["installation_id"]] + [(await reg(h, f"PC {i}", "linux"))["installation_id"] for i in range(TG.INSTALL_MAX - 1)]
        e = await reg(h, "11번째", "linux", status=429)
        assert e["code"] == "RATE-LIMIT"
    sql("DELETE FROM desktop_installations WHERE user_id=%s AND id = ANY(%s)", (A, ids[1:]))
    ok("앱 라우트(세션 없음 401 · Origin evil 403 · 헤더 없음 403 · Origin null·자기 OK · 설치본 upsert 같은 id · OS 열거 · 4KB 413 · "
       "모르는 id 404 · 다른 계정 id NOT-OWNER(M3) · IP 분당 10 공유 429 · 설치본 10)")
    return a1["installation_id"]


# ── 3) grant 상태기계 · 지목 · 한도 ─────────────────────────

async def test_grants(A, B, IA):
    async with Client(main.mcp) as c, H(A) as ha, H(B) as hb:
        # 지목 — 켜진 앱 0대 → NO-ACTIVE-APP(grant 10분 대기, detail 에 grant_id)
        sql("UPDATE desktop_installations SET last_seen_at = now() - interval '5 minutes' WHERE user_id=%s", (A,))
        pl = val(await call(c, "pc_list"))
        assert [p["installation_id"] for p in pl["pcs"]] == [IA] and pl["pcs"][0]["active"] is False and not pl["pcs"][0]["is_default"]
        r = await call(c, "pc_connect")
        assert code(r) == "NO-ACTIVE-APP"
        d = detail(r)
        assert d["sent_to"] == "집 맥 새 이름" and d["scope"] == "device" and d["grant_id"].startswith("tg_")
        g0 = d["grant_id"]
        assert sql("SELECT state FROM token_grants WHERE id=%s", (g0,))[0]["state"] == "waiting"
        # 앱을 켜면(폴링) 그 grant 가 보인다 · 같은 scope·설치본 재요청 = 같은 grant(한도에 안 셈)
        p = await poll(ha, IA)
        assert [x["grant_id"] for x in p["grants"]] == [g0] and p["installation"]["installation_id"] == IA
        r = await call(c, "pc_connect")
        assert not r.is_error and val(r)["grant_id"] == g0 and val(r)["sent_to"] == "집 맥 새 이름"
        assert set(val(r)) == {"grant_id", "scope", "sent_to", "installation_id", "expires_at"}
        st = val(await call(c, "token_grant_status", {"grant_id": g0}))
        assert st["state"] == "waiting" and st["delivered_at"] is None
        # redeem 경계 — 다른 계정 · 다른 설치본 · 없는 grant
        IB = (await reg(hb, "회사 PC", "win32"))["installation_id"]
        e = await redeem(hb, g0, IB, status=403)
        assert e["code"] == "NOT-OWNER"
        IA2 = (await reg(ha, "노트북", "darwin"))["installation_id"]
        e = await redeem(ha, g0, IA2, status=404)
        assert e["code"] == "INSTALLATION-UNKNOWN"
        e = await redeem(ha, "tg_" + "1" * 24, IA, status=404)
        assert e["code"] == "NOT-FOUND"
        e = await redeem(ha, g0, IB, status=403)
        assert e["code"] == "NOT-OWNER", "남의 설치본 id"
        # 정상 redeem — 그 자리에서 발급, 일회용
        j = await redeem(ha, g0, IA)
        assert set(j) == {"grant_id", "scope", "token", "device_id", "device_label", "account_label", "token_expires_at"}
        assert j["scope"] == "device" and j["token"].startswith("imp_" + j["device_id"] + ".") and j["account_label"] == A_EMAIL
        assert j["device_label"] == "집 맥 새 이름"
        assert bearer_ok(j["token"])["id"] == j["device_id"]
        T1, DEV = j["token"], j["device_id"]
        e = await redeem(ha, g0, IA, status=409)
        assert e["code"] == "GRANT-USED"
        st = val(await call(c, "token_grant_status", {"grant_id": g0}))
        assert st["state"] == "delivered" and st["delivered_to"] == "집 맥 새 이름" and st["delivered_at"]
        assert (await poll(ha, IA))["grants"] == [] and (await poll(ha, IA))["installation"]["device"]["device_id"] == DEV
        # 지목 규칙 — 켜진 앱 둘: 가장 최근 로그인이 기본 · 이름(id) 지목
        sql("UPDATE desktop_installations SET last_seen_at = now(), last_login_at = now() - interval '1 hour' WHERE id=%s", (IA,))
        sql("UPDATE desktop_installations SET last_seen_at = now(), last_login_at = now() WHERE id=%s", (IA2,))
        pl = {p["installation_id"]: p for p in val(await call(c, "pc_list"))["pcs"]}
        assert pl[IA2]["is_default"] and not pl[IA]["is_default"] and pl[IA]["active"] and pl[IA]["device_connected"]
        r = val(await call(c, "pc_connect"))
        assert r["installation_id"] == IA2 and r["sent_to"] == "노트북" and "note" not in r
        r2 = val(await call(c, "pc_connect", {"installation_id": IA}))
        assert r2["installation_id"] == IA and r2["grant_id"] != r["grant_id"]
        assert (await poll(ha, IA2))["grants"][0]["grant_id"] == r["grant_id"] and len((await poll(ha, IA))["grants"]) == 1
        # M2 — 같은 장치 새 토큰: 옛 토큰은 새 토큰 첫 사용 때 무효
        j2 = await redeem(ha, r2["grant_id"], IA)
        assert j2["device_id"] == DEV and j2["token"] != T1
        assert bearer_ok(T1)["id"] == DEV, "새 토큰 안 썼으면 옛 토큰 유효"
        assert bearer_ok(j2["token"])["id"] == DEV
        expect("AUTH-INVALID", bearer_ok, T1)
        # 만료 · 취소
        r3 = val(await call(c, "pc_connect", {"installation_id": IA2}))
        assert r3["grant_id"] == r["grant_id"], "대기 grant 재사용"
        sql("UPDATE token_grants SET expires_at = now() - interval '1 second', created_at = now() - interval '11 minutes' WHERE id=%s",
            (r["grant_id"],))
        e = await redeem(ha, r["grant_id"], IA2, status=410)
        assert e["code"] == "GRANT-EXPIRED"
        assert val(await call(c, "token_grant_status", {"grant_id": r["grant_id"]}))["state"] == "expired"
        assert (await poll(ha, IA2))["grants"] == []
        assert TG.expire_round() >= 1 and sql("SELECT state FROM token_grants WHERE id=%s", (r["grant_id"],))[0]["state"] == "expired"
        assert code(await call(c, "token_grant_status", {"grant_id": "tg_" + "2" * 24})) == "NOT-FOUND"
        # 한도 — 열린 3 · 하루 10(KST)
        sql("DELETE FROM token_grants WHERE user_id=%s", (A,))
        IA3 = (await reg(ha, "세 번째", "linux"))["installation_id"]
        for i in (IA, IA2, IA3):
            assert not (await call(c, "pc_connect", {"installation_id": i})).is_error
        IA4 = (await reg(ha, "네 번째", "linux"))["installation_id"]
        assert code(await call(c, "pc_connect", {"installation_id": IA4})) == "RATE-LIMIT"
        sql("UPDATE token_grants SET state='expired' WHERE user_id=%s", (A,))
        sql("INSERT INTO token_grants (user_id,id,scope,installation_id,state,via,expires_at) "
            "SELECT %s, 'tg_' || lpad(to_hex(g), 24, '0'), 'device', %s, 'expired', 'mcp', now() + interval '1 minute' "
            "FROM generate_series(100, 106) g", (A, IA4))
        assert sql("SELECT count(*) AS n FROM token_grants WHERE user_id=%s", (A,))[0]["n"] == 10
        r = await call(c, "pc_connect", {"installation_id": IA4})
        assert code(r) == "RATE-LIMIT" and "오늘" in r.content[0].text
        sql("DELETE FROM token_grants WHERE user_id=%s", (A,))
        sql("DELETE FROM desktop_installations WHERE id = ANY(%s)", ([IA3, IA4],))
        # 설치본이 하나도 없는 계정(B 의 MCP 는 없다 — 함수로) → NO-ACTIVE-APP, grant 없음
        e = expect("NO-ACTIVE-APP", TG.pc_connect, db.user_by_email(N_EMAIL)["id"])
        assert e.detail["installations"] == 0 and e.detail["grant_id"] is None
    ok("grant 상태기계(NO-ACTIVE-APP 대기 → 폴링 → redeem 발급 → GRANT-USED · 만료 GRANT-EXPIRED · 정리 회차) · 계정 불일치 NOT-OWNER · "
       "설치본 불일치 · 대기 grant 재사용 · 지목(최근 로그인 기본·id 지목) · M2(같은 장치 새 토큰, 옛 토큰 첫 사용 때 무효) · 한도 열린 3·하루 10")
    return IA, IA2, DEV


# ── 4) 자동 연결 · 교체 · 해제 기록 ───────────────────────

async def test_auto_rotate(A, IA, IA2, DEV):
    async with Client(main.mcp) as c, H(A) as ha:
        main.site._grant_ips.clear()
        # 자동 연결 — 장치 없는 설치본 = 새 장치 · 있는 설치본 = 대기 토큰(토큰 분실 재발급)
        r = await ha.post("/desktop/device/auto", json={"installation_id": IA2, "client_name": "노트북", "os": "darwin"})
        assert r.status_code == 200 and r.json()["created"] is True, r.text
        a = r.json()
        keep(a["token"])
        assert set(a) == {"token", "device_id", "device_label", "account_label", "token_expires_at", "created"} and a["device_label"] == "노트북"
        r = await ha.post("/desktop/device/auto", json={"installation_id": IA2})
        b = r.json()
        keep(b["token"])
        assert r.status_code == 200 and b["created"] is False and b["device_id"] == a["device_id"]
        assert bearer_ok(a["token"]) and bearer_ok(b["token"])
        expect("AUTH-INVALID", bearer_ok, a["token"])
        # 세션 교체 — 대기 토큰 1개(덮어씀)
        r1 = (await ha.post("/desktop/device/rotate", json={"installation_id": IA2})).json()
        r2 = (await ha.post("/desktop/device/rotate", json={"installation_id": IA2})).json()
        keep(r1["token"]), keep(r2["token"])
        assert set(r2) == {"token", "device_id", "device_label", "account_label", "token_expires_at"}
        expect("AUTH-INVALID", bearer_ok, r1["token"])   # 덮어쓴 대기 토큰
        assert bearer_ok(b["token"]) and bearer_ok(r2["token"])
        expect("AUTH-INVALID", bearer_ok, b["token"])
        # 장치 없는 설치본 rotate = NOT-FOUND(→ auto)
        IA5 = (await reg(ha, "다섯 번째", "linux"))["installation_id"]
        r = await ha.post("/desktop/device/rotate", json={"installation_id": IA5})
        assert r.status_code == 404 and r.json()["code"] == "NOT-FOUND"
        sql("DELETE FROM desktop_installations WHERE id=%s", (IA5,))
        # Bearer 교체 — M2 · 90일 무업로드 거절 · 형식 틀림 401
        async with H() as hn:
            r = await hn.post("/api/device/rotate", headers={"authorization": "Bearer " + r2["token"]})
            assert r.status_code == 200 and set(r.json()) == {"token", "stream_id", "token_expires_at"} and r.json()["stream_id"] == a["device_id"]
            t3 = keep(r.json()["token"])
            assert bearer_ok(r2["token"]) and bearer_ok(t3)
            expect("AUTH-INVALID", bearer_ok, r2["token"])
            r = await hn.post("/api/device/rotate", headers={"authorization": "Bearer nope"})
            assert r.status_code == 401 and r.json()["code"] == "AUTH-INVALID"
            r = await hn.post("/api/device/rotate", headers={"authorization": "Bearer " + r2["token"]})
            assert r.status_code == 401 and r.json()["code"] == "AUTH-INVALID", "무효 옛 토큰"
            sql("UPDATE import_streams SET last_used_at = now() - interval '91 days', created_at = now() - interval '200 days' WHERE id=%s",
                (a["device_id"],))
            r = await hn.post("/api/device/rotate", headers={"authorization": "Bearer " + t3})
            assert r.status_code == 401 and r.json()["code"] == "TOKEN-EXPIRED" and "90일" in r.json()["msg"]
            sql("UPDATE import_streams SET last_used_at = now() WHERE id=%s", (a["device_id"],))
            no_token(r.text, "Bearer 교체 오류")
        # 해제 기록 — pc_forget(D, bind) → 장치 폐기·grant 취소·자동 재연결 금지
        g = val(await call(c, "pc_connect", {"installation_id": IA}))
        assert code(await call(c, "pc_forget", {"installation_id": IA})) == "BIND-REQUIRED"
        pv = await preview(c, "pc_forget", {"installation_id": IA})
        assert pv["shown"]["PC"] == "집 맥 새 이름" and "취소될 요청" in pv["shown"] and pv["irreversible"] is False
        f = val(await call(c, "pc_forget", {"installation_id": IA}, pv["bind"]))
        assert f["revoked"] and f["device_revoked"] and f["cancelled_grants"] == 1 and f["via"] == "facade"
        assert val(await call(c, "token_grant_status", {"grant_id": g["grant_id"]}))["state"] == "cancelled"
        r = await call(c, "pc_forget", {"installation_id": IA}, pv["bind"])
        assert code(r) == "BIND-STALE", "해제 뒤 대상 바뀜"
        for path in ("/desktop/device/auto", "/desktop/device/rotate"):
            r = await ha.post(path, json={"installation_id": IA})
            assert r.status_code == 409 and r.json()["code"] == "DEVICE-REVOKED", (path, r.text)
        rr = await reg(ha, "집 맥 새 이름", "darwin", IA)
        assert rr["revoked"] is True and rr["device"]["active"] is False, "재등록해도 해제 기록 유지"
        p = await poll(ha, IA)
        assert p["installation"]["revoked"] is True, "해제된 설치본도 폴링(다시 연결 통로)"
        # 해제 PC 는 기본 대상이 아니다 — 해제 PC 만 켜져 있으면 지목 없는 pc_connect = NO-ACTIVE-APP(grant 없음)
        others = [r["id"] for r in sql("SELECT id FROM desktop_installations WHERE user_id=%s AND id<>%s", (A, IA))]
        sql("UPDATE desktop_installations SET revoked_at = now() WHERE id = ANY(%s)", (others,))
        n0 = sql("SELECT count(*) AS n FROM token_grants WHERE user_id=%s", (A,))[0]["n"]
        r = await call(c, "pc_connect")
        assert code(r) == "NO-ACTIVE-APP" and detail(r)["grant_id"] is None, r.content[0].text
        assert sql("SELECT count(*) AS n FROM token_grants WHERE user_id=%s", (A,))[0]["n"] == n0
        assert not any(x["is_default"] for x in val(await call(c, "pc_list"))["pcs"]), "해제 PC 는 is_default 아님"
        sql("UPDATE desktop_installations SET revoked_at = NULL WHERE id = ANY(%s)", (others,))
        # 대화로 다시 연결(지목) → note · 새 장치 + 해제 풀림
        g = val(await call(c, "pc_connect", {"installation_id": IA}))
        assert g["note"] == TG.REVIVE_NOTE
        j = await redeem(ha, g["grant_id"], IA)
        assert j["device_id"] != DEV and (await poll(ha, IA))["installation"]["revoked"] is False
        # token_revoke(device) — 장치 해제도 자동 재연결 금지
        pv = await preview(c, "token_revoke", {"kind": "device", "id": j["device_id"]})
        assert pv["shown"]["종류"].startswith("장치 토큰") and pv["irreversible"] is True
        t = val(await call(c, "token_revoke", {"kind": "device", "id": j["device_id"]}, pv["bind"]))
        assert t == {"kind": "device", "id": j["device_id"], "active": False, "via": "facade"}
        r = await ha.post("/desktop/device/auto", json={"installation_id": IA})
        assert r.status_code == 409 and r.json()["code"] == "DEVICE-REVOKED"
        tl = val(await call(c, "token_list"))
        assert {d["device_id"] for d in tl["devices"]} >= {DEV, j["device_id"], a["device_id"]}
        assert all(set(d) == {"device_id", "label", "active", "created_at", "token_expires_at", "last_used_at", "pc"} for d in tl["devices"])
        # 없는 대상 — preview 오류 = op 오류
        for op, prm in (("pc_forget", {"installation_id": "di_" + "e" * 24}), ("token_revoke", {"kind": "device", "id": "is_nope"}),
                        ("token_revoke", {"kind": "migration", "id": "mt_nope"})):
            p_ = await c.call_tool("read", {"op": "decide_preview", "params": {"op": op, "params": prm}})
            d_ = await call(c, op, prm, "AAAAAAAAAAAAAAAA")
            assert code(p_) == code(d_) and code(p_) in ("INSTALLATION-UNKNOWN", "NOT-FOUND"), (op, code(p_), code(d_))
    ok("자동 연결(새 장치·분실 재발급) · 세션 교체(대기 1개 덮어씀) · Bearer 교체 M2·90일 무업로드 TOKEN-EXPIRED · pc_forget(bind·STALE·grant 취소) "
       "→ auto·rotate DEVICE-REVOKED · 재등록해도 해제 유지 · 대화 재연결 = 새 장치 · token_revoke(device) · token_list 값 없음 · 없는 대상 preview=op")


# ── 5) 이관 scope ─────────────────────────────────────

async def test_migration(A, IA2):
    async with Client(main.mcp) as c, H(A) as ha:
        switches(False, [])
        p = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "migration_token_send", "params": {}}})
        assert code(p) == "MIGRATION-OFF"
        switches(True, [])
        assert code(await call(c, "migration_token_send", {}, "AAAAAAAAAAAAAAAA")) in ("MIGRATION-NOT-ALLOWED", "BIND-STALE")
        switches(True, [A])
        web_tok = keep(migration.token_issue(A)["token"])   # 웹 발급 — 쓰던 토큰으로 만든다
        migration.authenticate("Bearer " + web_tok)
        assert code(await call(c, "migration_token_send", {})) == "BIND-REQUIRED"
        pv0 = await preview(c, "migration_token_send", {})
        assert pv0["shown"]["받을 PC"] == "집 맥 새 이름", "지목 없음 = 켜진 앱 중 최근 로그인(방금 재등록한 PC)"
        P = {"installation_id": IA2}
        pv = await preview(c, "migration_token_send", P)
        assert pv["shown"]["받을 PC"] == "노트북" and pv["shown"]["기존 이관 토큰"].startswith("기존 이관 토큰 1개가 폐기돼요"), pv["shown"]
        assert pv["impact"]["revokes"] == 1
        assert code(await call(c, "migration_token_send", P, pv0["bind"])) == "BIND-STALE", "다른 PC 의 bind"
        r = val(await call(c, "migration_token_send", P, pv["bind"]))
        assert r["scope"] == "migration" and r["revokes"] == 1 and r["sent_to"] == "노트북" and r["via"] == "facade"
        # 수령 때 재검사 — allowlist 빠짐 · 표시 이름 없음
        switches(True, [])
        e = await redeem(ha, r["grant_id"], IA2, status=403)
        assert e["code"] == "MIGRATION-NOT-ALLOWED"
        switches(True, [A])
        name = sql("SELECT display_name FROM users WHERE id=%s", (A,))[0]["display_name"]
        sql("UPDATE users SET display_name = NULL WHERE id=%s", (A,))
        e = await redeem(ha, r["grant_id"], IA2, status=403)
        assert e["code"] == "NAME-REQUIRED"
        sql("UPDATE users SET display_name = %s WHERE id=%s", (name, A))
        j = await redeem(ha, r["grant_id"], IA2)
        assert j["scope"] == "migration" and j["token"].startswith("mig_mt_") and j["device_id"] is None and j["device_label"] is None
        # M2 — 웹 토큰은 새 토큰 첫 사용 때 폐기
        migration.authenticate("Bearer " + web_tok)
        migration.authenticate("Bearer " + j["token"])
        expect("TOKEN-REVOKED", migration.authenticate, "Bearer " + web_tok)
        # 표시 이름 없는 계정 — 대화 쓰기 관문(pc_connect · migration_token_send)
        os.environ["CRM_DEV_USER"] = N_EMAIL
        try:
            assert code(await call(c, "pc_connect", {})) == "NAME-REQUIRED"
        finally:
            os.environ["CRM_DEV_USER"] = A_EMAIL
        # token_list · token_revoke(migration)
        tl = val(await call(c, "token_list"))
        mt = [t for t in tl["migration_tokens"] if t["active"]]
        assert len(mt) == 1 and set(mt[0]) == {"id", "label", "active", "created_at", "expires_at", "last_used_at"}
        t = val(await bound(c, "token_revoke", {"kind": "migration", "id": mt[0]["id"]}))
        assert t["active"] is False
        expect("TOKEN-REVOKED", migration.authenticate, "Bearer " + j["token"])
        switches(False, [])
    ok("이관 scope(스위치 꺼짐·allowlist — preview·op · D bind · shown 「기존 이관 토큰 N개」·받을 PC · 수령 때 allowlist·NAME-REQUIRED 재검사 · "
       "mig 토큰 → 웹 토큰은 새 토큰 첫 사용 때 폐기(M2) · token_revoke(migration)) · 이름 없는 계정 pc_connect NAME-REQUIRED")


# ── 6) CLI --browser (RFC 8252 loopback) ───────────────────

def _b64(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def pkce():
    v, st = _b64(secrets.token_bytes(32)), _b64(secrets.token_bytes(16))
    SECRETS_SEEN.extend([v, st])
    return v, _b64(hashlib.sha256(v.encode()).digest()), st


def loop_code(r, uri):
    assert r.status_code == 302 and r.headers["cache-control"] == "no-store", (r.status_code, r.text[:200])
    loc = urllib.parse.urlsplit(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == uri, r.headers["location"]
    q = urllib.parse.parse_qs(loc.query)
    assert set(q) == {"code", "state"}
    SECRETS_SEEN.append(q["code"][0])
    return q["code"][0], q["state"][0]


async def cli_claim(h, **f):
    main.site._claims.clear()
    r = await h.post("/desktop/cli/claim", data=f)
    assert r.headers["cache-control"] == "no-store"
    return r


async def test_cli_browser(A):
    site = main.site
    URI = "http://127.0.0.1:53121/cb"
    async with H(A, header=False) as h, H(header=False) as cli:
        v, ch, st = pkce()
        for bad in ("http://evil.example/cb", "http://127.0.0.1:80/cb", "https://127.0.0.1:53121/cb", "http://127.0.0.1:53121/other",
                    "http://localhost:53121/cb", "http://127.0.0.1:53121/cb?x=1", "http://127.0.0.1:70000/cb", "mycrm://auth/callback"):
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st, "redirect_uri": bad})
            assert r.status_code == 400 and "location" not in r.headers, bad
        # 이미 웹 세션 → 로그인 없이 302 loopback ?code&state
        code, st2 = loop_code(await h.get("/desktop/login", params={"challenge": ch, "state": st, "redirect_uri": URI}), URI)
        assert st2 == st
        assert sql("SELECT loopback FROM desktop_handoffs WHERE code_hash=%s", (hashlib.sha256(code.encode()).digest(),))[0]["loopback"]
        # 앱 /desktop/claim 은 loopback 코드를 받지 않는다
        main.site._claims.clear()
        r = await cli.post("/desktop/claim", data={"code": code, "verifier": v, "state": st}, headers=APP_H)
        assert r.status_code == 400 and "crm_session" not in r.headers.get("set-cookie", "")
        # 형식·scope·Origin·PKCE 불일치(코드 안 태움) → 성공 → 재사용
        assert (await cli_claim(cli, code=code, verifier=v, state=st, scope="admin")).json()["code"] == "ARG-INVALID"
        assert (await cli_claim(cli, code=code, verifier=v, state=st, scope="device")).json()["code"] == "ARG-INVALID", "device 는 client_name 필수"
        main.site._claims.clear()
        r = await cli.post("/desktop/cli/claim", data={"code": code, "verifier": v, "state": st, "scope": "device", "client_name": "x"},
                           headers={"origin": "https://evil.example"})
        assert r.status_code == 403 and r.json()["code"] == "ORIGIN"
        v_bad, _, st_bad = pkce()
        for vv, ss in ((v_bad, st), (v, st_bad)):
            r = await cli_claim(cli, code=code, verifier=vv, state=ss, scope="device", client_name="CLI 맥")
            assert r.status_code == 400 and r.json()["code"] == "HANDOFF-INVALID"
        r = await cli_claim(cli, code=code, verifier=v, state=st, scope="device", client_name="CLI 맥")
        assert r.status_code == 200, r.text
        j = r.json()
        keep(j["token"])
        assert set(j) == {"scope", "token", "stream_id", "token_expires_at", "account_label"} and j["account_label"] == A_EMAIL
        assert bearer_ok(j["token"])["id"] == j["stream_id"] and "crm_session" not in r.headers.get("set-cookie", "")
        r = await cli_claim(cli, code=code, verifier=v, state=st, scope="device", client_name="CLI 맥")
        assert r.status_code == 400 and r.json()["code"] == "HANDOFF-INVALID", "일회용"
        # 앱 코드(mycrm://, redirect_uri 없음)는 cli/claim 이 받지 않는다
        v2, ch2, st3 = pkce()
        r = await h.get("/desktop/login", params={"challenge": ch2, "state": st3})
        app_code = re.search(r"code=([A-Za-z0-9_-]{43})", r.text).group(1)
        SECRETS_SEEN.append(app_code)
        r = await cli_claim(cli, code=app_code, verifier=v2, state=st3, scope="device", client_name="x")
        assert r.status_code == 400 and r.json()["code"] == "HANDOFF-INVALID"
        # migration scope — 스위치 꺼짐(코드는 쓴 것) · 켜짐 = 이관 토큰
        for on in (False, True):
            switches(on, [A] if on else [])
            v3, ch3, st4 = pkce()
            c3, _ = loop_code(await h.get("/desktop/login", params={"challenge": ch3, "state": st4, "redirect_uri": "http://[::1]:61000/cb"}),
                              "http://[::1]:61000/cb")
            r = await cli_claim(cli, code=c3, verifier=v3, state=st4, scope="migration")
            if not on:
                assert r.status_code == 503 and r.json()["code"] == "MIGRATION-OFF"
            else:
                assert r.status_code == 200, r.text
                m = r.json()
                keep(m["token"])
                assert set(m) == {"scope", "token", "token_id", "expires_at", "account_label"} and m["token"].startswith("mig_" + m["token_id"])
                migration.authenticate("Bearer " + m["token"])
        switches(False, [])
    # 로그인 흐름(세션 없음) — crm_desktop 쿠키에 redirect_uri → 로그인 끝 = loopback 302(개발 로그인으로)
    real = (site.dev, site.dev_user)
    site.dev, site.dev_user = True, ""
    try:
        async with H(header=False) as b:
            v4, ch4, st5 = pkce()
            r = await b.get("/desktop/login", params={"challenge": ch4, "state": st5, "redirect_uri": URI})
            assert r.status_code == 302 and r.headers["location"] == "/dev/login", (r.status_code, r.headers.get("location"))
            r = await b.post("/dev/login", data={"email": A_EMAIL}, headers={"origin": PUBLIC})
            c4, _ = loop_code(r, URI)
            r = await cli_claim(b, code=c4, verifier=v4, state=st5, scope="device", client_name="CLI 둘")
            assert r.status_code == 200
            keep(r.json()["token"])
    finally:
        site.dev, site.dev_user = real
    # 로그인 거절·실패(AuthKit 경유) — loopback 이면 302 <redirect_uri>?error=<짧은 code>&state, 앱 흐름은 종전 오류 페이지
    real2 = (site.dev, site.dev_user, site.client_id)
    site.dev, site.dev_user, site.client_id = False, "", "client_test"
    try:
        for qp, want in (({"error": "access_denied", "error_description": "user said no"}, "access_denied"),
                         ({"error": "server_error"}, "login_failed"), ({"code": "x", "state": "wrong"}, "login_expired")):
            async with H(header=False) as b:
                v5, ch5, st6 = pkce()
                r = await b.get("/desktop/login", params={"challenge": ch5, "state": st6, "redirect_uri": URI})
                assert r.status_code == 302 and r.headers["location"].startswith("https://fake.authkit.test/"), r.headers.get("location")
                r = await b.get("/auth/callback", params=qp)
                assert r.status_code == 302 and r.headers["cache-control"] == "no-store", (qp, r.status_code)
                loc = urllib.parse.urlsplit(r.headers["location"])
                assert f"{loc.scheme}://{loc.netloc}{loc.path}" == URI
                assert urllib.parse.parse_qs(loc.query) == {"error": [want], "state": [st6]}, loc.query
                assert "user said no" not in r.headers["location"] and "crm_session" not in r.headers.get("set-cookie", "")
        async with H(header=False) as b:   # 앱 흐름(redirect_uri 없음) — 종전대로 오류 페이지
            v5, ch5, st6 = pkce()
            await b.get("/desktop/login", params={"challenge": ch5, "state": st6})
            r = await b.get("/auth/callback", params={"error": "access_denied"})
            assert r.status_code == 400 and "location" not in r.headers
    finally:
        site.dev, site.dev_user, site.client_id = real2
    ok("CLI --browser(redirect_uri loopback 만 — 8가지 거절 · 세션 있으면 바로 302 · 로그인 쿠키 경유 302 · 코드 loopback 표식 · 앱 claim 은 "
       "loopback 코드 거절·cli claim 은 앱 코드 거절 · scope·client_name·Origin · PKCE·state 불일치 HANDOFF-INVALID(안 태움) · 일회용 · "
       "device = 새 장치 토큰 · migration 스위치 꺼짐 503·켜짐 이관 토큰 · [::1] · 거절·실패·만료 = 302 ?error=코드&state, 앱 흐름은 오류 페이지)")


# ── 7) 값 없음 · cascade ───────────────────────────────

def test_no_values_and_cascade(A, B, logs):
    assert TOKENS, "토큰을 받은 적이 있어야 대조가 뜻이 있다"
    with db.tx() as c:
        dump = json.dumps([dict(r) for r in c.execute("SELECT * FROM token_grants").fetchall()], default=str)
        dump += json.dumps([dict(r) for r in c.execute("SELECT * FROM desktop_installations").fetchall()], default=str)
        aud = c.execute("SELECT action, detail FROM admin_audit WHERE actor_id = ANY(%s)", ([A, B],)).fetchall()
    dump += json.dumps([dict(r) for r in aud], default=str)
    no_token(dump, "grant·설치본 표·감사")
    # 시험 쪽 httpx 클라이언트가 자기 요청 URL(쿼리의 challenge·state)을 남기는 줄은 서버 로그가 아니다 — 빼고 본다
    server_logs = "\n".join(x for x in logs.splitlines() if "HTTP Request:" not in x)
    no_token(server_logs, "로그(stdout·logging)")
    acts = {r["action"] for r in aud}
    assert {"token_grant", "token_grant_redeem", "pc_forget", "device_rotate"} <= acts, acts
    for r in aud:
        if r["action"] in ("token_grant", "token_grant_redeem"):
            assert set(r["detail"]) <= {"grant_id", "scope", "via", "to", "result"}, r["detail"]
    # 사용자 삭제 = 설치본·grant 함께
    assert sql("SELECT count(*) AS n FROM desktop_installations WHERE user_id=%s", (B,))[0]["n"] >= 1
    db.user_delete(B)
    assert sql("SELECT count(*) AS n FROM desktop_installations WHERE user_id=%s", (B,))[0]["n"] == 0
    assert sql("SELECT count(*) AS n FROM token_grants WHERE user_id=%s", (B,))[0]["n"] == 0
    ok(f"값 없음(토큰 {len(TOKENS)}개 — grant 표·설치본 표·감사·로그·MCP 응답·preview·오류·폴링) · 감사 detail 열거 키만 · 사용자 삭제 cascade")


async def run():
    db.init_schema()
    cleanup()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    logging.getLogger().addHandler(handler)
    real = (main.site.dev, main.site.dev_user)
    try:
        test_schema()
        A = db.user_by_email(A_EMAIL)["id"]
        B = db.user_by_email(B_EMAIL)["id"]
        db.user_by_email(N_EMAIL)
        db.display_name_set(A, "연결 시험")
        db.display_name_set(B, "연결 시험 B")
        with contextlib.redirect_stdout(buf):
            IA = await test_routes(A, B)
            IA, IA2, DEV = await test_grants(A, B, IA)
            await test_auto_rotate(A, IA, IA2, DEV)
            await test_migration(A, IA2)
            await test_cli_browser(A)
        out = buf.getvalue()
        sys.stdout.write("\n".join(x for x in out.splitlines() if x.startswith("OK —")) + "\n")
        test_no_values_and_cascade(A, B, out)
    finally:
        main.site.dev, main.site.dev_user = real
        logging.getLogger().removeHandler(handler)
        cleanup()
        db.close()
    print("OK — PC 연결·토큰 대화 발급 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
