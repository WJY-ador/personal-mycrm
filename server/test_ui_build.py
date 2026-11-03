"""웹 시험 — React 화면 묶음(server/ui) 서빙·래칫 (2026-11-03 React 전환 R1).

실행: (cd server/ui && npm ci && npm run build) 뒤 DATABASE_URL=postgresql://localhost/crm_test_ui python3 server/test_ui_build.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
DB 는 /app 의 개발 사용자 조회에만 쓴다.

A. manifest 허용 목록 — manifest 의 파일 전부(진입 + 화면별 지연 불러오기 묶음·CSS)만 /app/assets/<이름> 200 · 1년 immutable · JS/CSS MIME ·
   nosniff · 목록 밖·경로 꼴 = 404.
B. /app — <!--{{ui}}--> 자리를 진입 <link>·<script type="module" src> 로 채움 · 인라인 스크립트 0·인라인 <style> 0 · CSP = CSP_BASE 그대로(해시 없음).
C. manifest 없음 — 서버가 죽지 않고 ({}, "") · 자리는 빈 문자열 · 화면 자리의 「불러오는 중」 줄 = 「화면 파일 없음」 한 줄(서버가 바꾼다).
D. 정적 뼈대 — app.html 인라인 스크립트·<style>·style·on* 속성 0 · 스크립트 = 테마 하나 · 자리 하나씩(옛 래칫 migrated.json 을 대신한다 —
   스크립트가 없으니 옛 함수 이름이 돌아올 자리가 없다). 라우터·화면 동작은 Vitest — layout/App.test.tsx · shared/route.test.ts.
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import urllib.parse
from pathlib import Path

HERE = Path(__file__).parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_ui). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
PUBLIC = "http://127.0.0.1:8800"
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ui-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = PUBLIC
sys.path.insert(0, str(HERE))

import httpx  # noqa: E402

import db  # noqa: E402
import main  # noqa: E402
import web  # noqa: E402

UI = HERE / "ui"
APP = (HERE / "app.html").read_text(encoding="utf-8")
INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", re.I)   # src 없는 <script>(인라인) — 어느 화면에도 0


def test_static():
    assert not INLINE_SCRIPT.search(APP), "app.html 인라인 스크립트 0"
    assert "<style" not in APP and not re.search(r"\sstyle\s*=", APP), "app.html 인라인 <style>·style 속성 0(CSS = 번들)"
    assert not re.search(r"\son[a-z]+\s*=", APP, re.I), "app.html 인라인 이벤트 속성 0"
    assert re.findall(r"<script\b[^>]*>", APP) == ['<script src="{{asset:theme.js}}">'], "스크립트 = 첫 칠 전 테마(외부 파일) 하나"
    assert APP.count(web.UI_SLOT) == 1 and APP.count(web.UI_BOOT) == 1, "React 묶음 자리 1 · 화면 자리 첫 줄 1"
    print(f"OK — 정적 뼈대({len(APP.splitlines())}줄 · 인라인 스크립트·style·on* 0 · 테마 스크립트 1 · 자리 1) 통과")


def test_no_manifest():
    with tempfile.TemporaryDirectory() as d:
        assert web.load_ui(Path(d)) == ({}, ""), "manifest 없음 = 빈 허용 목록·빈 태그(서버는 뜬다)"
        (Path(d) / ".vite").mkdir()
        (Path(d) / ".vite" / "manifest.json").write_text("{깨짐", encoding="utf-8")
        assert web.load_ui(Path(d)) == ({}, ""), "깨진 manifest 도 같은 동작"
        (Path(d) / ".vite" / "manifest.json").write_text(json.dumps({"src/main.tsx": {"file": "assets/main-x.js"}}), encoding="utf-8")
        assert web.load_ui(Path(d)) == ({}, ""), "진입 파일이 실제로 없으면 같은 동작"
        (Path(d) / "assets").mkdir()
        (Path(d) / "assets" / "main-x.js").write_text("export {}", encoding="utf-8")
        (Path(d) / "assets" / "secret.txt").write_text("x", encoding="utf-8")
        (Path(d) / ".vite" / "manifest.json").write_text(json.dumps({"src/main.tsx": {"file": "assets/main-x.js", "css": ["../web.py"],
                                                                                     "assets": ["assets/secret.txt", "assets/../x.js"]}}), encoding="utf-8")
        files, tags = web.load_ui(Path(d))
        assert list(files) == ["main-x.js"] and files["main-x.js"][1].startswith("text/javascript"), files
        assert tags == '<script type="module" src="/app/assets/main-x.js"></script>', "목록 밖 확장자·경로 꼴은 빠진다"
    old = web.UI_TAGS
    try:
        web.UI_TAGS = ""
        head = web._fill_ui(APP).split("</head>", 1)[0]
        assert web.UI_SLOT not in head and "/app/assets/" not in head, "자리 = 빈 문자열(진입 태그 0)"
        assert web.UI_BOOT not in web._fill_ui(APP) and web._fill_ui(APP).count(web.UI_MISSING) == 1, "빌드 없음 = 화면 자리에 한 줄 안내"
    finally:
        web.UI_TAGS = old
    print("OK — manifest 없음·깨짐·진입 없음 = ({}, \"\") · 목록 밖 파일 0 · 자리 비움 · 화면 안내 한 줄 통과")


async def test_serving():
    man = json.loads((UI / "dist" / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    entry = man["src/main.tsx"]
    js, css = entry["file"].removeprefix("assets/"), [c.removeprefix("assets/") for c in entry.get("css", [])]
    every = {f.removeprefix("assets/") for c in man.values() for f in [c["file"], *c.get("css", [])]}
    lazy = {c["file"].removeprefix("assets/") for c in man.values() if c.get("isDynamicEntry")}
    assert set(web.UI_ASSETS) == every, ("허용 목록 = manifest 의 파일 전부(지연 불러오기 묶음·CSS 포함)", set(web.UI_ASSETS) ^ every)
    assert len(lazy) >= 10 and lazy <= every and js not in lazy, ("화면별 지연 불러오기 묶음", lazy)
    assert any(c.get("isDynamicEntry") and c.get("css") for c in man.values()), "지연 묶음 CSS 도 목록에"
    tp = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=tp, base_url=PUBLIC) as h:
        r = await h.get("/app")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        html = r.text
        assert web.UI_SLOT not in html and f'<script type="module" src="/app/assets/{js}"></script>' in html and web.UI_BOOT in html
        for c in css:
            assert f'<link rel="stylesheet" href="/app/assets/{c}">' in html
        assert not INLINE_SCRIPT.search(html) and "<style" not in html, "응답 인라인 스크립트·<style> 0"
        assert r.headers["content-security-policy"] == web.CSP_BASE, "CSP = script-src 'self' 그대로(해시 없음)"
        assert "unsafe-inline" not in r.headers["content-security-policy"]
        for n in sorted(every):
            a = await h.get(f"/app/assets/{n}")
            assert a.status_code == 200 and a.headers["cache-control"] == web.ASSET_IMMUTABLE and a.headers["x-content-type-options"] == "nosniff"
            assert a.headers["content-type"] == web.UI_TYPES[Path(n).suffix], a.headers["content-type"]
        for bad in ("nope.js", "..%2Fweb.py", "%2E%2E", "manifest.json", ".vite"):
            assert (await h.get(f"/app/assets/{bad}")).status_code == 404, bad
        assert (await h.get("/app/assets/..%2F..%2Fweb.py")).status_code == 404
    print(f"OK — 서빙(허용 목록 {len(web.UI_ASSETS)} · 지연 묶음 {len(lazy)} · /app 진입 태그 · 인라인 0 · CSP self · immutable·MIME·nosniff · 목록 밖 404) 통과")


def main_():
    db.init_schema()
    try:
        test_static()
        test_no_manifest()
        asyncio.run(test_serving())
        print("OK — React 화면 묶음 시험 전부 통과")
    finally:
        db.close()


if __name__ == "__main__":
    main_()
