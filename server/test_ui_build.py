"""웹 시험 — React 화면 묶음(server/ui) 서빙·래칫 (2026-11-03 React 전환 R1).

실행: (cd server/ui && npm ci && npm run build) 뒤 DATABASE_URL=postgresql://localhost/crm_test_ui python3 server/test_ui_build.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.
DB 는 /app 의 개발 사용자 조회에만 쓴다.

A. manifest 허용 목록 — 진입 JS·CSS 만 /app/assets/<이름> 200 · 1년 immutable · JS/CSS MIME · nosniff · 목록 밖·경로 꼴 = 404.
B. /app — <!--{{ui}}--> 자리를 manifest 의 <link>·<script type="module" src> 로 채움 · 인라인 스크립트 수 ∈ {0, 1} · 번들 인라인 0 · CSP 해시 = 옛 인라인 1개.
C. manifest 없음 — 서버가 죽지 않고 ({}, "") · 자리는 빈 문자열 · app.html 이 「화면 파일 없음」 한 줄을 그린다.
D. 래칫 — migrated.json 의 옛 이름이 app.html 에 0 · 최상위 function 수 ≤ 상한 · 옮긴 화면은 uiMount("<이름>"…) 로 띄움.
E. 옛 쪽 다리(node 실행) — uiMount 세 갈래 · 같은 화면 자리 유지 · 떠나면 unmount · applyState 뒤 crm:state 1번 ·
   ctx = 상태 S·주소 조각(args)·setDirty(고치던 글 주소 → uiDirty)·flash(껍데기 결과 한 줄, 한 번) · applyState = 옛 본문 캐시 비움.
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
MIGRATED = json.loads((UI / "migrated.json").read_text(encoding="utf-8"))
APP = (HERE / "app.html").read_text(encoding="utf-8")
JS = re.search(r"<script>(.*?)</script>", APP, re.S).group(1)


def test_ratchet():
    for screen, names in MIGRATED["screens"].items():
        left = [n for n in names if re.search(rf"\b{re.escape(n)}\b", APP)]
        assert not left, f"옮긴 화면 {screen} 의 옛 이름이 app.html 에 남았어요: {left}"
        assert re.search(rf'uiMount\("{screen}"[,)]', JS), f"옮긴 화면 {screen} 은 uiMount 로 띄운다"
    n = len(re.findall(r"^(?:async\s+)?function\s+\w+", JS, re.M))
    cap = MIGRATED["app_html_function_max"]
    assert n <= cap, f"app.html 최상위 function {n}개 > 상한 {cap} — 새 화면 코드는 server/ui 에(옛 쪽을 늘리지 않는다)"
    assert APP.count(web.UI_SLOT) == 1, "React 묶음 자리 1개"
    assert len(web.inline_script_hashes(APP)) == 1 and APP.count("<script>") == 1, "옛 인라인 스크립트 1개(CSP 해시 대상)"
    print(f"OK — 래칫(옛 이름 0 · uiMount · function {n} ≤ {cap} · 자리 1 · 인라인 1) 통과")


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
    finally:
        web.UI_TAGS = old
    assert "이 화면 파일이 서버에 없어요." in JS and "document.querySelector('script[type=\"module\"]')" in JS, "빌드 없음 = 한 줄 안내"
    print("OK — manifest 없음·깨짐·진입 없음 = ({}, \"\") · 목록 밖 파일 0 · 자리 비움 · 화면 안내 한 줄 통과")


def test_bridge_old_side():
    """옛 쪽 다리(node 실행) — uiMount 세 갈래(모듈 있음 = CrmUI.mount · 모듈 아직 = 자리 맡김 + 불러오는 중 · 빌드 없음 = 한 줄 안내)
    · 같은 화면 다시 = 자리 유지(새로 만들지 않음) · 다른 화면이 #view 를 덮으면 uiSweep 이 unmount · applyState = crm:state 1번."""
    import shutil
    import subprocess
    node = shutil.which("node")
    assert node, "node 가 필요해요(CI 는 setup-node)"
    a, b = JS.index("let uiOn = "), JS.index("function uiSweep()")
    bridge = JS[a:JS.index("\n}\n", b) + 3]
    m = re.search(r"function applyState\(next\) \{.*?\n\}\n", JS, re.S).group(0)
    stub = """const esc = s => String(s); const LOADING = "LOADING"; const load = async () => true; let S = null, loadedAt = "";
const recCache = {r1: 1}; let coreFlash = {text: "결과"}; const mdhm = () => ""; let renders = 0; const render = () => { renders++; };
const nodes = {}; let made = 0;
const view = {set innerHTML(h) { for (const k of Object.keys(nodes)) delete nodes[k]; const m = /id="([^"]+)"/.exec(h); if (m) { made++; nodes[m[1]] = {id: m[1], innerHTML: ""}; } }};
const $ = id => id === "view" ? view : nodes[id] || null;
let MODULE = false; const document = {querySelector: q => (q === 'script[type="module"]' && MODULE ? {} : null)};
const log = []; const events = [];
const window = {dispatchEvent: e => events.push(e.type)};
class Event { constructor(t) { this.type = t; } }"""
    scen = """const out = {};
uiMount("trash"); out.none = $("ui-trash").innerHTML; out.noneOn = uiOn; out.afterNone = coreFlash;
view.innerHTML = "<p>다른 화면</p>"; uiSweep(); out.sweptOn = uiOn;
MODULE = true; uiMount("trash"); out.pending = [window.CrmUIPending && window.CrmUIPending[0], $("ui-trash").innerHTML];
window.CrmUI = {mount: (n, el, ctx) => { log.push(["mount", n, el.id, typeof ctx.reload]); out.ctx = ctx; out.flashes.push(ctx.flash); }, unmount: n => log.push(["unmount", n])};
out.pendFlash = window.CrmUIPending && window.CrmUIPending[2].flash; coreFlash = {text: "결과"}; out.flashes = [];
const before = made; uiMount("trash"); uiMount("trash"); out.made = made - before; uiSweep(); out.kept = log.length;
view.innerHTML = "<p>다른 화면</p>"; uiSweep(); out.log = log; out.pendingAfter = window.CrmUIPending === undefined; out.on = uiOn;
out.flashLeft = coreFlash;
S = {id: "S1"}; uiMount("me", ["principle", "p1"]); out.me = [out.ctx.state.id, out.ctx.args, out.ctx.flash];
out.ctx.setDirty("#_me/principle/p1"); out.dirty = uiDirty; out.ctx.setDirty(null); out.clean = uiDirty;
view.innerHTML = "<p>다른 화면</p>"; uiSweep(); log.length = 3;
applyState({generated: ""}); out.events = events; out.renders = renders; out.cache = Object.keys(recCache);
console.log(JSON.stringify(out));"""
    r = subprocess.run([node, "-"], input=f"{stub}\n{bridge}\n{m}\n{scen}", capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    o = json.loads(r.stdout)
    assert "이 화면 파일이 서버에 없어요." in o["none"] and o["noneOn"] == "trash", "빌드 없음 = 한 줄 안내"
    assert o["sweptOn"] == "", "다른 화면 = 내림"
    assert o["pending"] == ["trash", "LOADING"], "모듈 아직 = 자리 맡김 + 불러오는 중"
    assert o["made"] == 0 and o["kept"] == 2, "같은 화면 다시 = 자리 유지(새 div 0) · 머무는 동안 unmount 0"
    assert o["log"] == [["mount", "trash", "ui-trash", "function"], ["mount", "trash", "ui-trash", "function"], ["unmount", "trash"]]
    assert o["pendingAfter"] and o["on"] == ""
    assert o["events"] == ["crm:state"] and o["renders"] == 1, "새 상태 = render 뒤 crm:state 1번"
    assert o["afterNone"] == {"text": "결과"} and o["pendFlash"] == {"text": "결과"}, "빌드 없음 = 결과 문구를 넘기지 않음(남김) · 맡긴 자리 = 넘김"
    assert o["flashes"] == [{"text": "결과"}, None, None] and o["flashLeft"] is None, "껍데기 결과 한 줄 = 띄운 화면에 한 번(넘긴 뒤 비움)"
    assert o["me"] == ["S1", ["principle", "p1"], None], "ctx = 상태 S · 주소 조각 · (넘긴 결과 문구는 다시 안 감)"
    assert o["dirty"] == "#_me/principle/p1" and o["clean"] is None, "setDirty = 껍데기 미저장 보호 주소"
    assert o["cache"] == [], "새 상태 = 옛 기록 본문 캐시 비움(React 에서 고친 글)"
    print("OK — 옛 쪽 다리(빌드 없음 안내 · 모듈 아직 = 맡김 · 같은 화면 = 자리 유지 · 떠나면 unmount · crm:state 1번 · ctx 상태·주소·미저장·결과 한 줄 · 본문 캐시) 통과")


async def test_serving():
    man = json.loads((UI / "dist" / ".vite" / "manifest.json").read_text(encoding="utf-8"))
    entry = man["src/main.tsx"]
    js, css = entry["file"].removeprefix("assets/"), [c.removeprefix("assets/") for c in entry.get("css", [])]
    assert set(web.UI_ASSETS) == {js, *css}, ("허용 목록 = manifest 의 파일", web.UI_ASSETS)
    tp = httpx.ASGITransport(app=main.app)
    async with httpx.AsyncClient(transport=tp, base_url=PUBLIC) as h:
        r = await h.get("/app")
        assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
        html = r.text
        assert web.UI_SLOT not in html and f'<script type="module" src="/app/assets/{js}"></script>' in html
        for c in css:
            assert f'<link rel="stylesheet" href="/app/assets/{c}">' in html
        hs = web.inline_script_hashes(html)
        assert len(hs) in (0, 1), "인라인 스크립트 수 ∈ {0, 1}"
        assert r.headers["content-security-policy"] == f"{web.CSP_BASE} 'sha256-{hs[0]}'", "CSP = 옛 인라인 1개 해시만(React 는 self)"
        bundle = (UI / "dist" / "assets" / js).read_text(encoding="utf-8")
        inl = [b for a, b in web._SCRIPT_RE.findall(html) if not web._SRC_ATTR_RE.search(a)]
        assert all("createRoot" not in b and bundle[:200] not in b for b in inl), "React 번들 인라인 0"
        assert "unsafe-inline" not in r.headers["content-security-policy"]
        for n in [js, *css]:
            a = await h.get(f"/app/assets/{n}")
            assert a.status_code == 200 and a.headers["cache-control"] == web.ASSET_IMMUTABLE and a.headers["x-content-type-options"] == "nosniff"
            assert a.headers["content-type"] == web.UI_TYPES[Path(n).suffix], a.headers["content-type"]
        for bad in ("nope.js", "..%2Fweb.py", "%2E%2E", "manifest.json", ".vite"):
            assert (await h.get(f"/app/assets/{bad}")).status_code == 404, bad
        assert (await h.get("/app/assets/..%2F..%2Fweb.py")).status_code == 404
    print(f"OK — 서빙(허용 목록 {len(web.UI_ASSETS)} · /app 진입 태그 · 인라인 {len(hs)} · CSP self+해시 1 · immutable·MIME·nosniff · 목록 밖 404) 통과")


def main_():
    db.init_schema()
    try:
        test_ratchet()
        test_no_manifest()
        test_bridge_old_side()
        asyncio.run(test_serving())
        print("OK — React 화면 묶음 시험 전부 통과")
    finally:
        db.close()


if __name__ == "__main__":
    main_()
