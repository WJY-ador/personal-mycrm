"""웹 시험 — PC 앱 설치 페이지 GET /download (2026-10-30 설치 페이지 가안 A).

실행: DATABASE_URL=postgresql://localhost/crm_test_download python3 server/test_download.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
DB 는 쓰지 않는다(라우트가 DB 를 건드리지 않는다) — 가드는 main 을 들여올 때 엉뚱한 DB 에 붙지 않게 하는 것.

A. 플래그 CRM_DOWNLOAD_PUBLIC 꺼짐(없음·"0"·"true") → 「준비 중」·직링크 0·Release 링크 0.
B. 켜짐("1") → 직링크 3개(고정 이름)·releases/latest 링크 1개·경고 절차 본문 없음·설치 뒤 3단계.
C. UA 판정 — Mac UA = Mac 칸 먼저·강조, Windows UA = Windows 칸 먼저·강조, iPhone·Android·빈 UA = 같은 비중(Windows 먼저).
D. 비로그인 200 · 로그인이면 「대시보드로」 · CSP 헤더 = CSP_BASE · 인라인 스크립트 0 · no-store.
E. 정적 — start.html 하단에 /download 링크 · app.html renderDevices 안에 /download 링크.
"""
import asyncio
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_download). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "dl-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import main  # noqa: E402
import web  # noqa: E402

FLAG = "CRM_DOWNLOAD_PUBLIC"
LATEST = "https://github.com/WJY-ador/personal-mycrm/releases/latest"
WIN = f"{LATEST}/download/MyCRM-win-x64.exe"
ARM = f"{LATEST}/download/MyCRM-mac-arm64.dmg"
X64 = f"{LATEST}/download/MyCRM-mac-x64.dmg"
UA_MAC = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
UA_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
UA_IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
UA_ANDROID = "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"


def set_flag(v):
    if v is None:
        os.environ.pop(FLAG, None)
    else:
        os.environ[FLAG] = v


async def get(h, ua=None):
    return await h.get("/download", headers={"user-agent": ua} if ua is not None else {})


def common(r):
    """D — 모든 응답 공통: 비로그인 200 · CSP 그대로 · 인라인 스크립트 0 · no-store · 껍데기(theme.js·토글·nav 치환)."""
    assert r.status_code == 200, r.status_code
    assert r.headers["content-security-policy"] == web.CSP_BASE, r.headers.get("content-security-policy")
    assert web.inline_script_hashes(r.text) == [], "인라인 스크립트 0"
    assert r.headers["cache-control"] == "no-store" and r.headers["x-frame-options"] == "DENY"
    assert re.findall(r'/assets/[^"?]+', r.text) == ["/assets/theme.js"] and r.text.count("data-theme-toggle") == 1, "도움말과 같은 껍데기"
    assert "<!--nav-->" not in r.text and '<nav class="toc"' not in r.text, "nav 치환 · 빈 목차 칸 없음"
    assert "<title>대시보드 — PC 앱 설치</title>" in r.text


def os_blocks(t):
    """(Windows 칸 시작, Mac 칸 시작, Windows 칸 HTML, Mac 칸 HTML)."""
    wi, mi = (t.rindex("<div", 0, t.index(f'id="dl-{k}"')) for k in ("win", "mac"))   # 칸을 여는 <div 부터(class 포함)
    end = t.index('class="dl-warn"')
    w = t[wi:mi] if wi < mi else t[wi:end]
    m = t[mi:end] if wi < mi else t[mi:wi]
    return wi, mi, w, m


async def test_flag_off(h):
    for v in (None, "", "0", "true", " 1"):
        set_flag(v)
        for ua in (UA_MAC, UA_WIN, None):
            r = await get(h, ua)
            common(r)
            assert "준비 중이에요" in r.text and "공개 일정은 아직 정하지 않았어요" in r.text, (v, ua)
            assert "releases/latest" not in r.text and "MyCRM-" not in r.text and "github.com" not in r.text, f"꺼짐: 링크 0 ({v!r})"
            assert 'id="dl-win"' not in r.text and 'id="dl-mac"' not in r.text
    print("OK — A 플래그 꺼짐(없음·빈칸·0·true·' 1') = 「준비 중」·직링크 0·Release 링크 0")


async def test_flag_on(h):
    set_flag("1")
    for ua in (UA_MAC, UA_WIN, UA_IPHONE, None):
        r = await get(h, ua)
        common(r)
        t = r.text
        assert "준비 중" not in t
        for u in (WIN, ARM, X64):
            assert t.count(f'href="{u}"') == 1, (ua, u)
        assert sorted(re.findall(r'href="(https://github\.com/[^"]+)"', t)) == sorted([WIN, ARM, X64, LATEST]), "GitHub 링크 = 직링크 3 + latest 1"
        assert t.count(f'href="{LATEST}"') == 1 and "설치 경고 안내·체크섬" in t
        assert "베타 — 서명이 없어 첫 실행 때 OS 경고가 떠요." in t
        for w in ("그래도 열기", "추가 정보", "개인정보 보호 및 보안", "shasum", "certutil", "SmartScreen"):
            assert w not in t, f"경고 절차 본문은 Release 본문에만: {w}"
        assert "Apple 칩용 받기" in t and "Intel 칩용 받기" in t and "칩 확인:" in t
        assert t.index("설치한 뒤") > t.index('class="dl-warn"')
        steps = re.search(r'<h2 id="download-after">설치한 뒤</h2><ol>(.*?)</ol>', t).group(1)
        assert steps.count("<li>") == 3 and "로그인" in steps and "「연결 장치」" in steps and "토큰" in steps and "붙여 넣고 시작" in steps
    print("OK — B 플래그 켜짐 = 직링크 3(고정 이름)·releases/latest 1·경고 절차 본문 0·설치 뒤 3단계")


async def test_ua_order(h):
    set_flag("1")
    t = (await get(h, UA_MAC)).text
    wi, mi, w, m = os_blocks(t)
    assert mi < wi, "Mac UA = Mac 칸 먼저"
    assert 'class="dl-os pick"' in m and "지금 쓰는 PC" in m and 'class="dl-os"' in w and "지금 쓰는 PC" not in w
    assert f'class="btn primary" href="{ARM}"' in m and f'class="btn primary" href="{X64}"' in m and f'class="btn" href="{WIN}"' in w
    t = (await get(h, UA_WIN)).text
    wi, mi, w, m = os_blocks(t)
    assert wi < mi, "Windows UA = Windows 칸 먼저"
    assert 'class="dl-os pick"' in w and "지금 쓰는 PC" in w and "지금 쓰는 PC" not in m
    assert f'class="btn primary" href="{WIN}"' in w and f'class="btn" href="{ARM}"' in m and f'class="btn" href="{X64}"' in m
    for ua in (UA_IPHONE, UA_ANDROID, "", None):
        t = (await get(h, ua)).text
        wi, mi, w, m = os_blocks(t)
        assert wi < mi and "dl-os pick" not in t and "지금 쓰는 PC" not in t, f"모름 = 같은 비중: {ua!r}"
        assert t.count('class="btn primary" href="https://github.com') == 3, ua
    # 칩은 판정하지 않는다 — Apple 칩 Mac 도 Intel UA 를 보낸다
    assert web.ua_os(UA_MAC) == "mac" and web.ua_os(UA_WIN) == "win"
    assert web.ua_os(UA_IPHONE) == "" and web.ua_os(UA_ANDROID) == "" and web.ua_os("") == "" and web.ua_os(None) == ""
    assert web.ua_os("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Macintosh") == "", "iPad 표시 문자열에 Macintosh 가 섞여도 Mac 아님"
    print("OK — C UA 판정(Mac·Windows 먼저·강조, iPhone·iPad·Android·빈 UA = 같은 비중·Windows 먼저, 칩 판정 0)")


async def test_session(h):
    site = main.site
    real = (site.dev, site.dev_user)
    try:
        site.dev, site.dev_user = False, ""
        for v in (None, "1"):
            set_flag(v)
            r = await get(h, UA_MAC)
            common(r)
            assert '<a class="btn primary" href="/login">로그인</a>' in r.text, "비로그인 = 로그인 버튼"
        site.dev, site.dev_user = True, "dl-main@example.com"
        r = await get(h, UA_MAC)
        common(r)
        assert '<a class="btn" href="/app">대시보드로</a>' in r.text and 'href="/login"' not in r.text, "로그인 = 대시보드로"
    finally:
        site.dev, site.dev_user = real
    print("OK — D 비로그인 200·로그인 버튼 / 로그인 = 대시보드로 · CSP 그대로 · 인라인 스크립트 0 · no-store")


def test_static():
    start = (HERE / "start.html").read_text(encoding="utf-8")
    foot = start[start.index('<footer class="foot">'):start.index("</footer>")]
    assert foot.count('<a href="/download">PC 앱 설치</a>') == 1, "start.html 하단 링크(플래그와 무관)"
    assert start.count('href="/download"') == 1
    app = (HERE / "app.html").read_text(encoding="utf-8")
    i = app.index("function renderDevices() {")
    body = app[i:app.index("\nfunction ", i + 1)]
    assert body.count('<a href="/download">PC 앱 설치</a>') == 1, "「연결 장치」 화면 링크"
    assert app.count('href="/download"') == 1
    print("OK — E 정적(start.html 하단 · app.html renderDevices 에 /download 링크 하나씩)")


async def run():
    saved = os.environ.get(FLAG)
    try:
        test_static()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url=PUBLIC) as h:
            await test_flag_off(h)
            await test_flag_on(h)
            await test_ua_order(h)
            await test_session(h)
    finally:
        set_flag(saved)


if __name__ == "__main__":
    asyncio.run(run())
