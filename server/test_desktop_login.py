"""앱 로그인 넘김(2026-11-02) 시험 — 합성 PostgreSQL. 앱 대시보드 로그인 구현계획 「검증」 서버 항목.

실행: DATABASE_URL=postgresql://localhost/crm_test_desktop_login python3 server/test_desktop_login.py
가드: server/.env 를 읽지 않는다 — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

흐름: /desktop/login(challenge·state 형식) → crm_desktop 쿠키 + 기존 /login → /auth/callback → 「앱으로 돌아가요」(mycrm://auth/callback?code&state)
→ POST /desktop/claim(code·verifier·state) → crm_session → 303 /app.
본다: 정상 흐름 · challenge 불일치 · state 불일치 · 재사용 · 만료 · 다른 사용자 코드 · crm_desktop 없음(만료·변조 포함) → 일반 로그인 그대로
· 형식 이상 거절 · 이미 웹 세션 → AuthKit 건너뜀 · CRM_DEV(개발 사용자) 흐름 · IP 분당 상한 · 만료 행 정리 · 사용자 삭제
· 로그·실패 페이지·DB 에 code·verifier·state 값 없음.
"""
import asyncio
import base64
import contextlib
import hashlib
import html
import io
import os
import re
import secrets
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_desktop_login). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "dl-a@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import logging  # noqa: E402

import httpx  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
import web  # noqa: E402

A_EMAIL, B_EMAIL = "dl-a@example.com", "dl-b@example.com"
SECRETS: list[str] = []   # 시험 중 만든·받은 code·verifier·state — 로그·페이지·DB 에 없어야 한다


def ok(msg):
    print("OK —", msg, flush=True)


def b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def pkce():
    """앱이 만드는 값 — verifier 32바이트·state 16바이트(base64url). challenge = base64url(sha256(verifier))."""
    v, st = b64(secrets.token_bytes(32)), b64(secrets.token_bytes(16))
    SECRETS.extend([v, st])
    return v, b64(hashlib.sha256(v.encode()).digest()), st


def cookies(r) -> dict:
    """set-cookie → {이름: 소문자 헤더 전체}."""
    return {h.split("=", 1)[0]: h.lower() for h in r.headers.get_list("set-cookie")}


def handoff_code(r) -> str:
    """「앱으로 돌아가요」 페이지에서 링크·meta refresh 를 읽어 code 를 꺼낸다(둘이 같아야 한다)."""
    links = re.findall(r'href="(mycrm://[^"]+)"', r.text)
    meta = re.findall(r'<meta http-equiv="refresh" content="0;url=(mycrm://[^"]+)">', r.text)
    assert len(links) == 1 and meta == links, r.text
    u = urllib.parse.urlsplit(html.unescape(links[0]))
    assert (u.scheme, u.netloc, u.path) == ("mycrm", "auth", "/callback"), u
    q = urllib.parse.parse_qs(u.query)
    assert set(q) == {"code", "state"} and re.fullmatch(r"[A-Za-z0-9_-]{43}", q["code"][0]), q
    SECRETS.append(q["code"][0])
    return q["code"][0], q["state"][0]


def assert_handoff_page(r):
    assert r.status_code == 200, (r.status_code, r.text[:300])
    assert r.headers["cache-control"] == "no-store" and r.headers["content-security-policy"] == web.CSP_BASE, r.headers
    assert "<script" not in r.text.lower() and "MyCRM 앱으로 돌아가요" in r.text and "앱이 안 열리면" in r.text, r.text
    ck = cookies(r)
    assert "max-age=0" in ck.get("crm_desktop", ""), ("crm_desktop 을 지운다", ck)


def assert_fail(r, status):
    assert r.status_code == status, (r.status_code, r.text[:300])
    assert r.headers["cache-control"] == "no-store" and "다시 로그인해 주세요" in r.text, r.text
    assert "crm_session" not in cookies(r), "실패면 세션 쿠키 없음"
    for s in SECRETS:
        assert s not in r.text, "실패 페이지에 값 없음"


def row_count(where="TRUE", args=()):
    with db.tx() as c:
        return c.execute(f"SELECT count(*) AS n FROM desktop_handoffs WHERE {where}", args).fetchone()["n"]


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", ([A_EMAIL, B_EMAIL],)).fetchall()]
    for uid in ids:
        db.user_delete(uid)


class FakeVerifier:
    async def verify_token(self, tok):
        return {"tok-a": "A", "tok-b": "B"}.get(tok)


async def flow(h, who="tok-a"):
    """시스템 브라우저 쪽: /desktop/login → (AuthKit 가짜) → /auth/callback → 넘김 페이지. 반환 (code, verifier, state, callback 응답)."""
    v, ch, st = pkce()
    r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
    assert r.status_code == 302 and r.headers["location"].startswith("https://fake.authkit.test/oauth2/authorize?"), (r.status_code, r.text[:200])
    ck = cookies(r)
    assert "crm_login" in ck and "crm_desktop" in ck, ck
    for want in ("httponly", "samesite=lax", "max-age=600", "path=/"):
        assert want in ck["crm_desktop"], (want, ck["crm_desktop"])
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)
    assert q["redirect_uri"] == [f"{PUBLIC}/auth/callback"] and q["code_challenge"] != [ch], "AuthKit PKCE 는 서버 자신의 값(앱 값과 별개)"
    TOK["next"] = who
    r = await h.get("/auth/callback", params={"code": "authkit-code", "state": q["state"][0]})
    assert_handoff_page(r)
    ck = cookies(r)
    assert "crm_session" in ck and "max-age=0" in ck.get("crm_login", ""), "브라우저 쪽 웹 세션은 생긴다 · crm_login 지움"
    code, st2 = handoff_code(r)
    assert st2 == st, "딥링크 state = 앱이 보낸 state 그대로"
    return code, v, st, r


async def claim(h, code, verifier, state, headers=None):
    return await h.post("/desktop/claim", data={"code": code, "verifier": verifier, "state": state}, headers=headers or {})


TOK = {"next": "tok-a"}


async def test_http(A, B):
    site = main.site
    real = (site.dev, site.dev_user, site.client_id, site.verifier, site.token_post, web.auth.user_id_for, site.secure)
    uids = {"A": A, "B": B}

    async def fake_token_post(data):
        assert data["grant_type"] == "authorization_code" and data["code"] == "authkit-code", data
        return 200, {"access_token": TOK["next"], "token_type": "Bearer"}

    site.dev, site.dev_user, site.client_id = False, "", "client_test"   # 운영처럼 — DEV 폴백 없이
    site.verifier, site.token_post = FakeVerifier(), fake_token_post
    web.auth.user_id_for = lambda verified: uids[verified]
    site._claims.clear()

    def T():
        """새 클라이언트(쿠키 저장소 따로). IP 분당 상한 카운터를 비운다 — 시험 클라이언트는 모두 같은 접속 주소라서."""
        site._claims.clear()
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC)

    try:
        # ① 정상 흐름 — 브라우저(h)와 앱 창(app)은 쿠키 저장소가 다르다
        async with T() as h, T() as app:
            code, v, st, _ = await flow(h)
            with db.tx() as c:
                rows = c.execute("SELECT * FROM desktop_handoffs WHERE user_id=%s", (A,)).fetchall()
            assert len(rows) == 1 and bytes(rows[0]["code_hash"]) == hashlib.sha256(code.encode()).digest(), "코드는 SHA-256 만"
            assert code not in repr(rows) and v not in repr(rows) and rows[0]["used_at"] is None, "DB 에 코드·verifier 원문 없음"
            assert (rows[0]["expires_at"] - rows[0]["created_at"]).total_seconds() == db.HANDOFF_TTL_SECONDS == 120
            assert (await app.get("/desktop/claim")).status_code in (404, 405), "claim 은 POST 만(GET 은 MCP 마운트가 404)"
            r = await claim(app, code, v, st)
            assert r.status_code == 303 and r.headers["location"] == "/app", (r.status_code, r.text[:200])
            ck = cookies(r)
            assert "crm_session" in ck and "httponly" in ck["crm_session"] and "max-age=604800" in ck["crm_session"], ck
            assert (await app.get("/app")).status_code == 200, "앱 창 세션으로 /app"
            assert (await app.get("/api/state")).json()["user"]["email"] == A_EMAIL
            assert row_count("used_at IS NOT NULL AND user_id=%s", (A,)) == 1
            # ② 재사용 — 두 번째는 거절(세션 쿠키 없음)
            async with T() as app2:
                assert_fail(await claim(app2, code, v, st), 400)
                assert (await app2.get("/app")).status_code == 302
        ok("정상 흐름(login → callback 넘김 페이지 → claim → 세션 → /app) · 코드 해시만 저장 · 2분 · 재사용 거절")

        # ③ challenge 불일치 · state 불일치 — 거절하되 코드를 태우지 않는다(맞는 값이면 그 뒤에 성공)
        async with T() as h, T() as app:
            code, v, st, _ = await flow(h)
            other_v, _, other_st = pkce()
            assert_fail(await claim(app, code, other_v, st), 400)
            assert_fail(await claim(app, code, v, other_st), 400)
            assert row_count("used_at IS NOT NULL AND code_hash=%s", (hashlib.sha256(code.encode()).digest(),)) == 0
            assert (await claim(app, code, v, st)).status_code == 303
        ok("challenge 불일치·state 불일치 거절(코드 안 태움 — 맞는 값은 뒤에 성공)")

        # ④ 만료 — 2분 지난 코드 거절, 다음 발급 때 만료 행 정리
        async with T() as h, T() as app:
            code, v, st, _ = await flow(h)
            hc = hashlib.sha256(code.encode()).digest()
            with db.tx() as c:
                c.execute("UPDATE desktop_handoffs SET created_at=now() - interval '3 minutes', expires_at=now() - interval '1 minute' "
                          "WHERE code_hash=%s", (hc,))
            assert_fail(await claim(app, code, v, st), 400)
            assert row_count("code_hash=%s", (hc,)) == 1
            h.cookies.clear()   # 브라우저 웹 세션을 지워 AuthKit 경로로 다시
            await flow(h)
            assert row_count("code_hash=%s", (hc,)) == 0 and row_count("expires_at <= now()") == 0, "발급 때 만료 행 정리"
        ok("만료 거절 · 발급 때 만료 행 정리")

        # ⑤ 다른 사용자 코드 — B 의 코드에 A 의 verifier 는 거절 · B 의 코드는 A 세션이 있던 창도 B 세션으로 바꾼다(코드가 사용자를 정한다)
        async with T() as hb, T() as ha, T() as app:
            code_a, v_a, st_a, _ = await flow(ha, "tok-a")
            code_b, v_b, st_b, _ = await flow(hb, "tok-b")
            assert_fail(await claim(app, code_b, v_a, st_a), 400)
            assert_fail(await claim(app, code_a, v_b, st_b), 400)
            assert (await claim(app, code_a, v_a, st_a)).status_code == 303
            assert (await app.get("/api/state")).json()["user"]["email"] == A_EMAIL
            assert (await claim(app, code_b, v_b, st_b)).status_code == 303
            assert (await app.get("/api/state")).json()["user"]["email"] == B_EMAIL
        ok("다른 사용자 코드 — 서로의 verifier·state 로 거절 · 코드 주인 세션만")

        # ⑥ crm_desktop 없음 → 일반 로그인 그대로(302 /app, 넘김 행 없음) · 만료·변조 쿠키도 같다
        async with T() as h:
            n0 = row_count()
            for cookie in (None, site.sign({"c": "A" * 43, "s": "B" * 22}, -10), "garbage.sig",
                           site.sign({"c": "A" * 43, "s": "B" * 22}, 600)[:-2] + "xx", site.sign({"c": "short", "s": "B" * 22}, 600)):
                h.cookies.clear()
                r = await h.get("/login")
                assert r.status_code == 302 and "crm_desktop" not in cookies(r), "일반 /login 은 crm_desktop 을 만들지 않는다"
                st = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)["state"][0]
                if cookie:   # callback 직전에 심는다 — callback 의 만료·변조·모양 틀림 분기를 본다(/login 은 남은 쿠키를 지운다, ⑱)
                    h.cookies.set("crm_desktop", cookie)
                TOK["next"] = "tok-a"
                r = await h.get("/auth/callback", params={"code": "authkit-code", "state": st})
                assert r.status_code == 302 and r.headers["location"] == "/app", (cookie, r.status_code, r.text[:200])
                ck = cookies(r)
                assert set(ck) == {"crm_session", "crm_login"} and "max-age=604800" in ck["crm_session"], ck
            assert row_count() == n0, "일반 로그인은 넘김 행을 만들지 않는다"
        ok("crm_desktop 없음·만료·변조·모양 틀림 → 일반 로그인 그대로(302 /app · 쿠키 2개 · 넘김 없음)")

        # ⑦ 형식 이상 거절 — /desktop/login(쿠키·리다이렉트 없음) · /desktop/claim(폼 아님·길이·문자)
        async with T() as h:
            v, ch, st = pkce()
            for params in ({}, {"challenge": ch}, {"state": st}, {"challenge": ch[:-1], "state": st}, {"challenge": ch + "=", "state": st},
                           {"challenge": ch[:-1] + "/", "state": st}, {"challenge": ch, "state": "short"}, {"challenge": ch, "state": "a" * 65},
                           {"challenge": ch, "state": st[:-1] + "."}, {"challenge": ch, "state": st, "x": "<b>"}):
                r = await h.get("/desktop/login", params=params)
                if params.get("x"):
                    assert r.status_code == 302, "모르는 키는 무시"
                    continue
                assert r.status_code == 400 and "location" not in r.headers and "crm_desktop" not in cookies(r), (params, r.status_code)
                assert r.headers["cache-control"] == "no-store" and ch not in r.text and st not in r.text
            code, cv, cst, _ = await flow(h)
            for form in ({"code": code, "verifier": cv}, {"code": code[:-1], "verifier": cv, "state": cst},
                         {"code": code, "verifier": cv + "x", "state": cst}, {"code": code, "verifier": cv, "state": cst + "!"},
                         {"code": code, "verifier": "A" * 43, "state": cst}):
                async with T() as app:
                    assert_fail(await app.post("/desktop/claim", data=form), 400)
            async with T() as app:
                assert_fail(await app.post("/desktop/claim", json={"code": code, "verifier": cv, "state": cst}), 400)
                big = {"code": code, "verifier": cv, "state": cst, "pad": "x" * 3000}
                assert_fail(await app.post("/desktop/claim", data=big), 400)
                r = await claim(app, code, cv, cst, headers={"origin": "null"})
                assert r.status_code == 303, "Origin 없음·null 모두 받는다(앱 창의 브라우저 시작 요청)"
        ok("형식 이상 거절(challenge 43·state 16~64 base64url · 폼만 · 2KB) · 실패에 값·쿠키 없음")

        # ⑧ 이미 웹 세션 → AuthKit 건너뛰고 바로 넘김 페이지
        async with T() as h, T() as app:
            await flow(h)   # h 에 A 세션
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert_handoff_page(r)
            code, _ = handoff_code(r)
            assert (await claim(app, code, v, st)).status_code == 303
        ok("이미 웹 세션 → AuthKit 없이 넘김 페이지")

        # ⑨ 로그인 설정 없음(운영 503) → 쿠키 없이 503 · Secure 쿠키(https 공개 주소)
        async with T() as h:
            site.client_id = ""
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert r.status_code == 503 and "crm_desktop" not in cookies(r), r.status_code
            site.client_id, site.secure = "client_test", True
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert "secure" in cookies(r)["crm_desktop"], "https 면 Secure"
            site.secure = real[6]
        ok("로그인 설정 없음 503(쿠키 없음) · https 면 crm_desktop Secure")

        # ⑩ IP 분당 상한 — 같은 IP 11번째 429, 다른 IP 는 따로
        async with T() as app:
            site._claims.clear()
            ip = {"x-forwarded-for": "203.0.113.9, 198.51.100.7"}
            for _ in range(web.DESKTOP_CLAIM_PER_MIN):
                assert (await claim(app, "A" * 43, "B" * 43, "C" * 22, headers=ip)).status_code == 400
            r = await claim(app, "A" * 43, "B" * 43, "C" * 22, headers=ip)
            assert_fail(r, 429)
            assert int(r.headers["retry-after"]) >= 1
            assert (await claim(app, "A" * 43, "B" * 43, "C" * 22, headers={"x-forwarded-for": "198.51.100.8"})).status_code == 400
            site._claims.clear()
        ok("claim IP 분당 상한(10) — 11번째 429·retry-after · 다른 IP 는 따로")

        # ⑪ CRM_DEV(개발 사용자) — AuthKit 설정 없이 /desktop/login → 넘김 페이지 → claim → 세션(로컬 앱 E2E 경로)
        site.dev, site.dev_user, site.client_id = True, A_EMAIL, ""
        async with T() as h, T() as app:
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert_handoff_page(r)
            code, _ = handoff_code(r)
            r = await claim(app, code, v, st)
            assert r.status_code == 303 and "crm_session" in cookies(r)
            site.dev_user = ""   # 세션 쿠키만으로 /app 이 열리는지
            assert (await app.get("/app")).status_code == 200
        ok("CRM_DEV 개발 사용자 흐름(AuthKit 없이 넘김 → claim → 세션)")

        # ⑰ claim Origin — 외부 http(s) Origin 403(login CSRF) · 없음·null·자기 origin 허용
        site.dev, site.dev_user, site.client_id = False, "", "client_test"
        async with T() as h, T() as app:
            code, v, st, _ = await flow(h)
            for bad in ("https://evil.example", "http://127.0.0.1:9999", "", "file://"):
                r = await claim(app, code, v, st, headers={"origin": bad})
                assert_fail(r, 403)
                assert "다른 사이트" in r.text
            assert row_count("used_at IS NOT NULL AND code_hash=%s", (hashlib.sha256(code.encode()).digest(),)) == 0, "Origin 거절은 코드를 안 태운다"
            assert (await claim(app, code, v, st, headers={"origin": PUBLIC})).status_code == 303, "자기 origin 허용"
            for hd in ({}, {"origin": "null"}):
                h.cookies.clear()
                code, v, st, _ = await flow(h)
                assert (await claim(app, code, v, st, headers=hd)).status_code == 303, ("Origin 없음·null 허용", hd)
        ok("claim Origin — 외부·빈 값·file 403(코드 안 태움) · 없음·null·자기 origin 허용")

        # ⑱ 일반 /login 은 남은 crm_desktop 을 지운다 — 앱 로그인을 버린 뒤 일반 로그인은 /app 으로
        async with T() as h:
            h.cookies.clear()
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert r.status_code == 302 and "crm_desktop" in h.cookies, "앱 로그인 시작(버림)"
            r = await h.get("/login")
            assert r.status_code == 302 and "max-age=0" in cookies(r).get("crm_desktop", ""), cookies(r)
            assert "crm_desktop" not in h.cookies
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)
            TOK["next"] = "tok-a"
            r = await h.get("/auth/callback", params={"code": "authkit-code", "state": q["state"][0]})
            assert r.status_code == 302 and r.headers["location"] == "/app", "버린 앱 로그인 뒤 일반 로그인 = /app"
            h.cookies.clear()
            r = await h.get("/login")
            assert "crm_desktop" not in cookies(r), "crm_desktop 이 없으면 /login 응답 종전과 같다(지우는 헤더 없음)"
        ok("일반 /login — 남은 crm_desktop 지움 → callback 302 /app · 쿠키 없으면 응답 불변")

        # ⑬ fresh=1 — 웹 세션이 있어도 지름길 없이 AuthKit(prompt=login)으로 → 다른 계정(B)으로 전환
        site.dev, site.dev_user, site.client_id = False, "", "client_test"
        async with T() as h, T() as app:
            await flow(h, "tok-a")   # h 에 A 웹 세션
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st, "fresh": "1"})
            assert r.status_code == 302 and r.headers["location"].startswith("https://fake.authkit.test/oauth2/authorize?"), r.status_code
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.headers["location"]).query)
            assert q["prompt"] == ["login"] and "crm_desktop" in cookies(r), q
            TOK["next"] = "tok-b"
            r = await h.get("/auth/callback", params={"code": "authkit-code", "state": q["state"][0]})
            assert_handoff_page(r)
            code, _ = handoff_code(r)
            assert (await claim(app, code, v, st)).status_code == 303
            assert (await app.get("/api/state")).json()["user"]["email"] == B_EMAIL, "fresh=1 = 계정 전환"
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert r.status_code == 200, "fresh 없으면 종전대로 지름길"
        ok("fresh=1 — 웹 세션 지름길 없이 AuthKit prompt=login · 다른 계정으로 넘김")

        # ⑭ 개발 로그인(/dev/login) — CRM_DEV + 개발 사용자 폴백 없음(CRM_DEV_USER 빈 값) + AuthKit 설정 없음 = 로컬 E2E 경로
        async with T() as h:
            assert (await h.get("/dev/login")).status_code == 404, "운영(DEV 아님)엔 개발 로그인 없음"
            assert (await h.post("/dev/login", data={"email": A_EMAIL}, headers={"origin": PUBLIC})).status_code == 404
        site.dev, site.dev_user, site.client_id = True, "", ""
        async with T() as h, T() as app:
            assert (await app.get("/app")).status_code == 302, "개발 사용자 폴백 없음 — 쿠키 없으면 로그인 안 됨"
            v, ch, st = pkce()
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st})
            assert r.status_code == 302 and r.headers["location"] == "/dev/login" and "max-age=600" in cookies(r)["crm_desktop"], r.status_code
            r = await h.get("/dev/login")
            assert r.status_code == 200 and '<form method="post" action="/dev/login">' in r.text and 'name="email"' in r.text, r.text
            assert "<script" not in r.text.lower() and r.headers["cache-control"] == "no-store"
            assert (await h.post("/dev/login", data={"email": A_EMAIL})).status_code == 403, "Origin 없음 거절"
            assert (await h.post("/dev/login", data={"email": "nope"}, headers={"origin": PUBLIC})).status_code == 400
            r = await h.post("/dev/login", data={"email": A_EMAIL}, headers={"origin": PUBLIC})
            assert_handoff_page(r)
            assert "crm_session" in cookies(r), "브라우저 쪽 개발 세션도 생긴다"
            code, _ = handoff_code(r)
            r = await claim(app, code, v, st)
            assert r.status_code == 303 and r.headers["location"] == "/app"
            assert (await app.get("/api/state")).json()["user"]["email"] == A_EMAIL
            # 브라우저에 세션이 있으면 지름길 · fresh=1 이면 다시 개발 로그인 폼(계정 전환)
            v, ch, st = pkce()
            assert (await h.get("/desktop/login", params={"challenge": ch, "state": st})).status_code == 200
            r = await h.get("/desktop/login", params={"challenge": ch, "state": st, "fresh": "1"})
            assert r.status_code == 302 and r.headers["location"] == "/dev/login"
            r = await h.post("/dev/login", data={"email": B_EMAIL}, headers={"origin": PUBLIC})
            assert_handoff_page(r)
            code, _ = handoff_code(r)
            assert (await claim(app, code, v, st)).status_code == 303
            assert (await app.get("/api/state")).json()["user"]["email"] == B_EMAIL
            # crm_desktop 없이 개발 로그인 = 302 /app(일반 웹 개발 로그인)
            h.cookies.clear()
            r = await h.post("/dev/login", data={"email": A_EMAIL}, headers={"origin": PUBLIC})
            assert r.status_code == 302 and r.headers["location"] == "/app" and "crm_session" in cookies(r)
        ok("개발 로그인(/dev/login) — DEV 아님 404 · 폼 · Origin · 넘김 · fresh=1 계정 전환 · crm_desktop 없으면 /app")

        # ⑮ IP 상한 dict 크기 상한 — 기억하는 IP 가 상한이면 새 IP 는 그 분 동안 429
        real_max = web.DESKTOP_CLAIM_IPS_MAX
        try:
            web.DESKTOP_CLAIM_IPS_MAX = 2
            async with T() as app:
                for i in (1, 2):
                    assert (await claim(app, "A" * 43, "B" * 43, "C" * 22, headers={"x-forwarded-for": f"192.0.2.{i}"})).status_code == 400
                assert_fail(await claim(app, "A" * 43, "B" * 43, "C" * 22, headers={"x-forwarded-for": "192.0.2.3"}), 429)
                assert (await claim(app, "A" * 43, "B" * 43, "C" * 22, headers={"x-forwarded-for": "192.0.2.1"})).status_code == 400
                assert len(site._claims) == 2
        finally:
            web.DESKTOP_CLAIM_IPS_MAX = real_max
            site._claims.clear()
        ok("IP 기억 상한 — 넘으면 새 IP 429 · 아는 IP 는 그대로")

        # ⑯ 주기 정리(main.purge_once) — 만료 넘김 행 삭제
        with db.tx() as c:
            c.execute("UPDATE desktop_handoffs SET created_at=now() - interval '3 minutes', expires_at=now() - interval '1 minute'")
        assert row_count("expires_at <= now()") >= 1
        await main.purge_once()
        assert row_count("expires_at <= now()") == 0
        ok("주기 정리(purge_once) — 만료 넘김 행 삭제")

        # ⑫ 사용자 삭제 → 넘김 행도 삭제
        site.dev, site.dev_user, site.client_id = False, "", "client_test"
        async with T() as h:
            await flow(h, "tok-b")
        assert row_count("user_id=%s", (B,)) >= 1
        db.user_delete(B)
        assert row_count("user_id=%s", (B,)) == 0
        assert "desktop_handoffs" in db.DELETE_TABLES
        ok("사용자 삭제 = 넘김 행 삭제(cascade · 삭제 CLI 목록)")
    finally:
        site.dev, site.dev_user, site.client_id, site.verifier, site.token_post, web.auth.user_id_for, site.secure = real
        site._claims.clear()


def main_():
    logging.getLogger("httpx").setLevel(logging.WARNING)   # 시험 클라이언트의 요청 URL 로그(쿼리에 state)를 CI 출력에 남기지 않는다
    db.init_schema()
    cleanup()
    A = db.user_by_email(A_EMAIL)["id"]
    B = db.user_by_email(B_EMAIL)["id"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            asyncio.run(test_http(A, B))
    finally:
        out = buf.getvalue()
        sys.stdout.write(out)
    for s in SECRETS:
        assert s not in out, "로그(stdout)에 code·verifier·state 값 없음"
    with db.tx() as c:
        audit = repr(c.execute("SELECT * FROM admin_audit").fetchall())
    for s in SECRETS:
        assert s not in audit, "감사에 값 없음"
    assert "[desktop] 앱 로그인 교환 거절: mismatch" in out and "[desktop] 앱 로그인 교환 거절: used" in out, "거절 사유 분류는 남는다"
    # uvicorn 접근 로그 — /desktop/* 쿼리는 지운다(일반 경로는 그대로)
    v, ch, st = pkce()
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", f"/desktop/login?challenge={ch}&state={st}", "1.1", 302), None)
    assert all(f.filter(rec) for f in logging.getLogger("uvicorn.access").filters)
    assert ch not in rec.getMessage() and st not in rec.getMessage() and "/desktop/login?…" in rec.getMessage(), rec.getMessage()
    rec = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d',
                            ("1.2.3.4:5", "GET", "/help?x=1", "1.1", 200), None)
    assert all(f.filter(rec) for f in logging.getLogger("uvicorn.access").filters) and "/help?x=1" in rec.getMessage()
    ok(f"로그·감사에 값 없음(값 {len(SECRETS)}개 대조) · 거절 사유 분류만 · 접근 로그 /desktop/* 쿼리 지움")
    cleanup()
    db.close()
    print("PASS — 앱 로그인 넘김 시험", flush=True)


if __name__ == "__main__":
    main_()
