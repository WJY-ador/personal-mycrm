"""웹 시험 — 이관 화면(2026-11-02, notes 이관경로-API계약 「웹 세션 경로」): app.html 「이관」 절(#_setup/migration).

실행: DATABASE_URL=postgresql://localhost/crm_test_migration_screen python3 server/test_migration_screen.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

A. 정적 — Setup 페이지 「이관」(SETUP_PAGES 끝에 덧붙임 · 휴지통 순서 그대로) · 연결 장치 화면 링크 · 이관 API 접점 = 「이관」 절 한 곳 ·
   토큰·본문을 콘솔·localStorage 에 넣지 않음 · 일괄 체크 없음.
B. 실행(node — 「이관」 절을 가짜 DOM 으로 돌린다): 꺼짐·허용 목록 밖 = 토큰 발급·기준 체크·[반영]만 숨기고 안내(plan 목록·영수증은 보임) · 토큰 발급(앞 토큰 있으면 「이전 토큰은 폐기돼요」 확인 → 한 번만 보임 →
   다른 화면 가면 지움) · 폐기 · plan 목록(상태·항목 수·만료·오늘 사용량/한도) · 확인 화면(자료군×action 개수·항목·사유·기준 체크 상자 하나씩) ·
   체크 = seqs 하나 · 반영 확인 대화상자 숫자(반영·체크 안 한 기준·warn/reject/conflict) · 반영 = plan_hash · 오류 문구(PLAN-STALE·PLAN-HASH-MISMATCH·
   RATE-LIMIT·PLAN-EXPIRED·CHECK-DEPENDENCY) · 본문 펼침 · 영수증(결과별 개수·해시 일치/다름/휴지통).
C. HTTP — 화면이 읽는 응답 키(enabled·allowed·token_days·tokens·plans·limits) · /app 에 이관 절.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
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

MAIN = "ms-main@example.com"
HTML = (HERE / "app.html").read_text(encoding="utf-8")
JS = re.search(r"<script>(.*?)</script>", HTML, re.S).group(1)
BLOCK = JS[JS.index("// ── 이관 (migration"):JS.index("// ── /이관 ──")]
CODE = "\n".join(ln for ln in BLOCK.splitlines() if not ln.lstrip().startswith("//"))


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = %s", (MAIN,)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def test_static():
    assert 'const SETUP_PAGES = [["layout", "페이지 레이아웃"], ["structure", "내 구조 설정"], ["objects", "자료 종류"], ["devices", "연결 장치"], ["map", "지도"], ["help", "문의 및 개인정보"], ["migration", "이관"]];' in JS
    assert 'const setupPages = () => trashOn() ? SETUP_PAGES.concat([["trash", "휴지통"]]) : SETUP_PAGES;' in JS, "휴지통은 그대로 맨 끝"
    assert '  else if (page === "migration") renderMigration(R.b);\n' in JS
    dev = JS[JS.index("function renderDevices() {"):JS.index("let devData = null;")]
    assert '<a href="#_setup/migration">이관</a>' in dev, "연결 장치 화면에서 이관으로"
    # 이관 API 접점 = 이 절 한 곳(토큰 경로 /api/migration/plans 는 화면이 부르지 않는다)
    for w in ("/api/migration-tokens", "/api/migrations"):
        assert JS.count(w) == BLOCK.count(w) > 0, w
    assert "/api/migration/" not in JS, "토큰 경로는 PC 업로더 몫 — 화면은 웹 세션 경로만"
    assert "console." not in CODE and "localStorage" not in CODE and "sessionStorage" not in CODE, "토큰·본문을 콘솔·저장소에 넣지 않는다"
    assert "S.migToken" not in JS and "coreFlash = {text: migToken" not in JS
    assert re.search(r'corePost\(migUrl\("check"\), \{seqs: \[seq\], checked: want\}\)', CODE), "체크 = 항목 하나씩"
    for w in ("전체 선택", "모두 체크", "모두 선택", "data-mig-checkall"):
        assert w not in BLOCK, f"일괄 체크 없음: {w}"
    assert 'corePost(migUrl("apply"), {plan_hash: MIG.plan.plan_hash})' in CODE
    assert "남기지 않" not in BLOCK and "반영 안 함" not in BLOCK, "기존 시험이 세는 문구를 늘리지 않는다"
    print("OK — A 정적(Setup 「이관」 끝에 덧붙임·휴지통 그대로·연결 장치 링크·API 접점 한 곳·토큰 경로 0·콘솔/저장소 0·체크 하나씩·반영 = plan_hash)")


def mig_run(scenario):
    """「이관」 절 실행(node) — 절 전체 + esc·날짜·techInfo 도우미. 서버·DOM 은 가짜:
    api = 보낸 요청 기록, ask = 확인창 문구, done/fail = coreDone·coreFail 호출, els = $(id) 요소."""
    node = shutil.which("node")
    assert node, "node 가 필요해요(CI 는 setup-node) — 이관 화면 실행 시험"
    helpers = "\n".join(re.search(rf"^{p}.*$", JS, re.M).group(0) for p in (
        r"const esc = ", r"const toDate = ", r"const pad2 = ", r"function mdhm\(", r"const LOADING = "))
    a = JS.index("function techInfo(err) {")
    tech = JS[a:JS.index("\n}\n", a) + 3]
    stub = """let S = {}, renderSeq = 0, rendered = 0; const render = () => { rendered++; };
const location = {hash: "#_setup/migration"}; let ROUTE = {tab: "_setup", a: "migration", b: ""}; const route = () => ROUTE;
const els = {}; const $ = id => els[id] || null;
const mk = id => (els[id] = {id, innerHTML: "", textContent: "", open: false, showModal() { this.open = true; }, close() { this.open = false; }});
const document = {querySelectorAll: () => [], querySelector: () => null, addEventListener() {}};
let HASH = () => {}; const ask = []; let CONFIRM = true;
const window = {confirm: t => { ask.push(t); return CONFIRM; }, addEventListener: (ev, f) => { if (ev === "hashchange") HASH = f; }};
const navigator = {};
const api = []; let REPLY = {ok: true, j: {}}; const GETS = {};
const corePost = async (url, body) => { api.push({url, body}); return REPLY; };
const getJSON = async url => { api.push({url}); return GETS[url] || {ok: true, j: {}}; };
const done = [], fail = [];
const coreDone = async (text, hash) => { done.push({text, hash}); }; const coreFail = async (res, err) => { fail.push(res.code); };
const crumbs = (...xs) => xs.map(x => x[1]).join(" › "); const msgLine = () => ""; const loadFail = (res, what) => "FAIL " + what;
const strip = h => h.replace(/<[^>]+>/g, "").replace(/\\s+/g, " ").trim();
const btn = (d, err) => ({dataset: d, disabled: false, closest: () => (err ? {querySelector: () => err} : null)});"""
    src = f"{stub}\n{helpers}\n{tech}\n{BLOCK}\nconst out = {{}};\n(async () => {{\n{scenario}\n}})().then(() => console.log(JSON.stringify(out)), e => {{ console.error(e); process.exit(1); }});"
    r = subprocess.run([node, "-"], input=src, capture_output=True, text=True, timeout=60, env=dict(os.environ, TZ="Asia/Seoul"))
    assert r.returncode == 0, r.stderr[-1200:]
    return json.loads(r.stdout)


TOKENS = {"tokens": [{"id": "mt_a", "label": "이관 업로더", "created_at": "2026-11-02T01:00:00+00:00", "expires_at": "2026-11-16T01:00:00+00:00",
                      "revoked_at": None, "last_used_at": None, "active": True},
                     {"id": "mt_b", "label": "옛 업로더", "created_at": "2026-10-20T01:00:00+00:00", "expires_at": "2026-11-03T01:00:00+00:00",
                      "revoked_at": "2026-11-02T01:00:00+00:00", "last_used_at": "2026-10-21T01:00:00+00:00", "active": False}],
          "enabled": True, "allowed": True, "token_days": 14}
PLANS = {"plans": [{"plan_id": "mp_" + "1" * 24, "state": "sealed", "item_count": 8, "source_instance": "pc-test-1",
                    "created_at": "2026-11-02T01:00:00+00:00", "expires_at": "2026-11-05T01:00:00+00:00", "applied_at": None,
                    "summary": {"dry_run": {"actions": {"insert": 5, "warn": 2, "reject": 1}}}},
                   {"plan_id": "mp_" + "2" * 24, "state": "applied", "item_count": 1, "source_instance": "pc-test-1",
                    "created_at": "2026-11-01T01:00:00+00:00", "expires_at": "2026-11-04T01:00:00+00:00", "applied_at": "2026-11-01T02:00:00+00:00",
                    "via": "mcp", "summary": {"dry_run": {"actions": {"insert": 1}}}}],
         "enabled": True, "allowed": True,
         "limits": {"daily": 200, "used_today": 7, "plan_items": 200, "plan_days": 3, "staging_bytes": 2097152, "open_plans": 3}}
H = "a" * 64


def it(seq, unit, action, title, reason=None, needs=False, checked=False):
    return {"seq": seq, "original_id": f"o_{seq:032d}", "source_revision": f"v_{seq:032d}", "unit_kind": unit,
            "target_kind": "item" if unit.startswith("principle") else unit if unit == "source" else "record", "content_hash": H, "action": action,
            "reason": reason, "title": title, "has_body": title is not None, "needs_check": needs, "checked": checked, "result": None, "target_id": None}


DETAIL = {"plan_id": "mp_" + "1" * 24, "state": "sealed", "item_count": 8, "source_instance": "pc-test-1", "plan_hash": "b" * 64,
          "created_at": "2026-11-02T01:00:00+00:00", "expires_at": "2026-11-05T01:00:00+00:00",
          "counts": {"actions": {"insert": 4, "noop": 1, "warn": 1, "reject": 1, "conflict": 1},
                     "units": {"record": {"insert": 2, "warn": 1, "reject": 1}, "principle_c": {"insert": 2, "noop": 1}, "source": {"conflict": 1}}},
          "items": [it(0, "record", "insert", "첫 기록"), it(1, "record", "warn", "두 번째", "duplicate_content"),
                    it(2, "principle_c", "insert", "작게 자주", needs=True, checked=True), it(3, "principle_c", "insert", "원문 먼저", needs=True),
                    it(4, "principle_c", "noop", "이미 있는 기준", needs=True), it(5, "record", "reject", None, "sensitivity_internal"),
                    it(6, "source", "conflict", "출처", "conflict"), it(7, "record", "insert", "기준에 붙는 기록")]}


def test_list_tokens():
    o = mig_run(f"""
const T = {json.dumps(TOKENS, ensure_ascii=False)}, P = {json.dumps(PLANS, ensure_ascii=False)};
out.off = migListHtml(Object.assign({{}}, T, {{enabled: false}}), P);
out.deny = migListHtml(Object.assign({{}}, T, {{allowed: false}}), P);
out.on = migListHtml(T, P); out.onText = strip(out.on);
// 발급 — 앞 토큰 있음 = 확인창, 응답 토큰은 이 화면에서만
await migTokNew(btn({{active: "1"}}));
out.ask = ask.slice(); out.api = api.slice(); out.done = done.slice();
REPLY = {{ok: true, j: {{token: "mig_mt_0123456789abcdef.SECRET_SECRET_SECRET_SECRET_SECRET_SECRET_S", info: {{label: "이관 업로더"}}}}}};
await migTokNew(btn({{active: "1"}}));
out.withTok = migListHtml(T, P);
out.sTok = JSON.stringify(S).includes("SECRET");
ROUTE = {{tab: "_setup", a: "migration", b: ""}}; HASH(); out.keep = migListHtml(T, P).includes("SECRET");
ROUTE = {{tab: "_setup", a: "devices", b: ""}}; HASH(); out.gone = migListHtml(T, P).includes("SECRET");
// 앞 토큰 없음 = 확인창 없이
ask.length = 0; await migTokNew(btn({{active: "0"}})); out.ask0 = ask.length;
// 폐기 — 확인 → revoke · 취소 = 요청 0
api.length = 0; CONFIRM = false; await migTokRevoke(btn({{id: "mt_a"}})); out.revNo = api.length;
CONFIRM = true; await migTokRevoke(btn({{id: "mt_a"}})); out.rev = api.slice();
// 꺼짐 오류 = 사람 말
const e = {{textContent: ""}}; REPLY = {{ok: false, code: "MIGRATION-OFF", msg: "x", j: {{}}}}; await migTokNew(btn({{active: "0"}}, e)); out.offErr = e.textContent;
""")
    for k in ("off", "deny"):
        assert 'id="mig-off"' in o[k] and 'data-mig="tok-new"' not in o[k], (k, "꺼짐·허용 목록 밖 = 발급 버튼 대신 안내")
    assert "운영자가 켜면" in o["off"] and "허용 목록에 없어요" in o["deny"]
    on, txt = o["on"], o["onText"]
    assert 'data-mig="tok-new" data-active="1"' in on and on.count('data-mig="tok-revoke"') == 1, "살아 있는 토큰만 [폐기]"
    for w in ("사용 중", "폐기됨", "이관 업로더", "옛 업로더", "11월 16일 10:00 만료", "마지막 사용 아직 없음", "마지막 사용 10월 21일 10:00",
              "새로 발급하면 이전 토큰은 폐기돼요.", "14일 뒤 만료돼요",
              "오늘 반영 7 / 200행", "plan당 200항목", "열린 plan 3개까지", "보관 3일", "확인 대기", "반영함", "8항목", "11월 5일 10:00 만료",
              "새로 넣기 5 · 중복 의심 2 · 거절 1"):
        assert w in txt, w
    assert f'href="#_setup/migration/mp_{"1" * 24}"' in on
    assert on.count('data-mig-via="mcp"') == 1 and txt.count("대화에서 반영됨") == 1, "via=mcp plan 만 「대화에서 반영됨」(가안 X)"
    assert o["ask"] and "이전 토큰은 폐기돼요" in o["ask"][0] and o["api"] == [{"url": "/api/migration-tokens", "body": {}}]
    assert o["done"][0]["text"] == "새 이관 토큰을 발급했어요. 지금 옮겨 두세요."
    w = o["withTok"]
    assert 'id="mig-token"' in w and "SECRET" in w and "지금 한 번만 보여요" in w and 'data-mig="tok-copy"' in w and 'data-mig="tok-done"' in w
    assert o["sTok"] is False and o["keep"] is True and o["gone"] is False, "토큰 = 그 화면에서만(S 0 · 다른 화면 가면 지움)"
    assert o["ask0"] == 0, "앞 토큰 없음 = 확인창 없음"
    assert o["revNo"] == 0 and o["rev"] == [{"url": "/api/migration-tokens/mt_a/revoke", "body": {}}]
    assert o["offErr"] == "지금은 이관이 꺼져 있어요."
    print("OK — B1 꺼짐·허용 목록 밖 = 발급 대신 안내 · 토큰 목록(상태·만료·마지막 사용·[폐기]) · 발급(이전 토큰 폐기 확인·한 번만·화면 떠나면 지움) · plan 목록(상태·항목 수·만료·사용량/한도)")


def test_confirm_apply():
    o = mig_run(f"""
const D = {json.dumps(DETAIL, ensure_ascii=False)};
MIG.pid = D.plan_id; MIG.plan = D; MIG.limits = {{daily: 200, used_today: 7}};
out.html = migPlanHtml(D); out.text = strip(out.html); out.tally = migTally(D);
// 체크 — 상자 하나 = 요청 하나(seqs 하나). 응답 = 상세로 다시 그림
mk("mig-plan"); REPLY = {{ok: true, j: Object.assign({{}}, D, {{items: D.items.map(x => x.seq === 3 ? Object.assign({{}}, x, {{checked: true}}) : x)}})}};
await migCheck({{dataset: {{migCheck: "3"}}, checked: true}});
out.check = api.slice(); out.after = migTally(MIG.plan); out.redrawn = els["mig-plan"].innerHTML.includes('data-mig-check="3" checked');
// 반영 — plan_hash 를 보내고 영수증 화면으로(상태 다시 받기)
api.length = 0; REPLY = {{ok: true, j: {{already_applied: false}}}}; await migApply();
out.apply = api.slice(); out.done = done.slice();
REPLY = {{ok: true, j: {{already_applied: true}}}}; await migApply(); out.again = done[done.length - 1].text;
// 취소 — 확인 → cancel · 확인 안 함 = 요청 0
api.length = 0; CONFIRM = false; await migCancel(btn({{}})); out.cancelNo = api.length;
CONFIRM = true; await migCancel(btn({{}})); out.cancel = api.slice(); out.cancelAsk = ask[ask.length - 1]; out.cancelDone = done[done.length - 1];
// 그 밖 상태
out.staged = strip(migPlanHtml(Object.assign({{}}, D, {{state: "staged", plan_hash: null, items: []}})));
out.expired = strip(migPlanHtml(Object.assign({{}}, D, {{state: "expired", closed_at: "2026-11-05T01:00:00+00:00"}})));
""")
    h, t = o["html"], o["text"]
    assert h.count('data-mig-check="') == 3 and 'data-mig-check="2" checked' in h and 'data-mig-check="3"' in h, "기준(needs_check)마다 상자 하나"
    assert h.count('data-mig="body"') == 8, "항목마다 [본문 보기]"
    for w in ("자료군별 개수", "principle_c", "record", "source", "합계", "#0", "첫 기록", "새로 넣기", "이미 있음", "중복 의심", "충돌", "거절",
              "사유 · 같은 내용이 다른 ID 로 있음", "duplicate_content", "사유 · 내부 자료(internal)", "(본문을 지웠어요)",
              "항목 8개 · 기준 체크 1 / 3", "이 기준을 반영할게요", "오늘 남은 이관 한도 193행"):
        assert w in t, w
    # 반영 확인 대화상자 숫자 — 반영(insert = 체크한 기준 포함) · 이미 있음 · 체크 안 한 기준 · warn/conflict/reject
    assert o["tally"] == {"insert": 3, "noop": 0, "unchecked": 2, "checks": 3, "warn": 1, "conflict": 1, "reject": 1}, o["tally"]
    dlg = h[h.index('<dialog id="mig-dlg"'):]
    for w in ("새로 넣을 항목 <b>3</b>개", "이미 있어 그대로 둘 항목 <b>0</b>개", "체크 안 한 기준 <b>2</b>개 — 반영하지 않아요",
              "중복 의심 <b>1</b> · 충돌 <b>1</b> · 거절 <b>1</b>개 — 반영하지 않아요", "오늘 남은 이관 한도 <b>193</b>행", 'data-mig="apply-go"'):
        assert w in dlg, w
    assert o["check"] == [{"url": f"/api/migrations/mp_{'1' * 24}/check", "body": {"seqs": [3], "checked": True}}]
    assert o["after"]["insert"] == 4 and o["after"]["unchecked"] == 1 and o["redrawn"], "응답 상세로 다시 그림"
    assert o["apply"] == [{"url": f"/api/migrations/mp_{'1' * 24}/apply", "body": {"plan_hash": "b" * 64}}]
    assert o["done"][0]["text"] == "반영했어요. 영수증을 확인하세요." and o["again"] == "이미 반영한 plan이에요. 같은 영수증을 보여 줘요."
    assert o["cancelNo"] == 0 and o["cancel"] == [{"url": f"/api/migrations/mp_{'1' * 24}/cancel", "body": {}}]
    assert "올린 본문을 바로 지우고 되돌릴 수 없어요" in o["cancelAsk"] and o["cancelDone"]["hash"] == "#_setup/migration"
    assert "seal 전" in o["staged"] and "data-mig-check" not in o["staged"]
    assert "보관 기간이 지나 닫힌 plan이에요" in o["expired"] and "반영" not in o["expired"].replace("반영하지", "")
    print("OK — B2 확인 화면(자료군×action 표·항목·사유·체크 상자 = 기준마다) · 체크 = seqs 하나 · 대화상자 숫자 · 반영 = plan_hash · 두 번째 반영 · 취소 · seal 전/만료 안내")


def test_errors_body_receipt():
    o = mig_run(f"""
const D = {json.dumps(DETAIL, ensure_ascii=False)};
MIG.pid = D.plan_id; MIG.plan = D; mk("mig-plan");
const E = (code, j) => strip(migErrHtml({{ok: false, code, msg: "서버 문구", j: Object.assign({{msg: "서버 문구"}}, j || {{}})}}));
out.stale = E("PLAN-STALE", {{detail: {{changed: [{{seq: 0, sealed: "insert", now: "noop", reason: null}}, {{seq: 7, sealed: "insert", now: "reject", reason: "ref-not-found"}}]}}}});
out.hash = E("PLAN-HASH-MISMATCH");
out.rate = E("RATE-LIMIT", {{detail: {{needed: 230}}, resume_at: "2026-11-02T15:00:00+00:00"}});
out.exp = E("PLAN-EXPIRED");
out.dep = migErrHtml({{ok: false, code: "CHECK-DEPENDENCY", j: {{detail: {{seqs: [7]}}}}}});
out.state = E("PLAN-STATE", {{detail: {{state: "applied"}}}});
out.other = E("QUOTA-GLOBAL");
// migFail — 띠 문구 오류는 coreFail, 그 밖은 확인 화면 안에 남긴다
await migFail({{ok: false, code: "NAME-REQUIRED", j: {{}}}}); out.fail = fail.slice();
await migFail({{ok: false, code: "PLAN-STALE", j: {{detail: {{changed: []}}}}}}); out.kept = els["mig-plan"].innerHTML.includes("아무것도 반영하지 않았어요");
// 본문 펼침 — 그때 하나만 받는다 · 접기 · 지운 본문
api.length = 0;
GETS[`/api/migrations/${{D.plan_id}}/items/0`] = {{ok: true, j: {{payload: {{unit_kind: "record", title: "첫 기록", body: "본문 <b>전문</b>\\n둘째 줄", author_kind: "self",
  text_process: "verbatim", generation_kind: "human", primary_date: {{kind: "written", value: "2025-03-01"}}, review: {{state: "reviewed"}}, sensitivity: "normal"}}}}}};
GETS[`/api/migrations/${{D.plan_id}}/items/5`] = {{ok: true, j: {{payload: null}}}};
GETS[`/api/migrations/${{D.plan_id}}/items/6`] = {{ok: true, j: {{payload: {{unit_kind: "source", source: {{kind: "file", name: "출처 이름", location: "c".repeat(64)}}}}}}}};
await migBody(btn({{seq: "0"}})); out.body0 = els["mig-plan"].innerHTML;
await migBody(btn({{seq: "5"}})); await migBody(btn({{seq: "6"}})); out.bodies = els["mig-plan"].innerHTML; out.gets = api.map(x => x.url);
await migBody(btn({{seq: "0"}})); out.closed = els["mig-plan"].innerHTML.includes("본문 <b>"); out.closedEsc = els["mig-plan"].innerHTML.includes("본문 &lt;b&gt;전문");
await migBody(btn({{seq: "0"}})); out.refetch = api.length;
// 영수증
const R = {{plan_id: D.plan_id, import_batch_id: D.plan_id, plan_hash: "b".repeat(64), receipt_hash: "d".repeat(64), applied_at: "2026-11-02T02:00:00+00:00",
  counts: {{results: {{applied: 2, noop: 1, skipped_unchecked: 1, skipped_reject: 1}}, units: {{record: {{applied: 2, skipped_reject: 1}}, principle_c: {{noop: 1, skipped_unchecked: 1}}}}}},
  items: [{{seq: 0, unit_kind: "record", original_id: "o_0", content_hash: "e".repeat(64), result: "applied", target_id: "r_1", stored_hash: "e".repeat(64), target_state: "live"}},
          {{seq: 1, unit_kind: "record", original_id: "o_1", content_hash: "e".repeat(64), result: "applied", target_id: "r_2", stored_hash: "f".repeat(64), target_state: "live"}},
          {{seq: 2, unit_kind: "principle_c", original_id: "o_2", content_hash: "e".repeat(64), result: "noop", target_id: "i_1", stored_hash: null, target_state: "trashed"}},
          {{seq: 3, unit_kind: "principle_c", original_id: "o_3", content_hash: "e".repeat(64), result: "skipped_unchecked", target_id: null, stored_hash: null, target_state: null}},
          {{seq: 4, unit_kind: "record", original_id: "o_4", content_hash: "e".repeat(64), result: "skipped_reject", target_id: null, stored_hash: null, target_state: null}}]}};
out.rc = migReceiptHtml(Object.assign({{}}, D, {{state: "applied"}}), R); out.rcText = strip(out.rc);
""")
    s = o["stale"]
    assert "아무것도 반영하지 않았어요" in s and "#0 첫 기록 — 새로 넣기 → 이미 있음" in s and "#7 기준에 붙는 기록 — 새로 넣기 → 거절" in s
    assert "가리키는 항목을 찾을 수 없음" in s and "취소한 뒤 PC에서 다시 올려 주세요" in s
    assert "서버에 저장한 plan이 달라요" in o["hash"] and "아무것도 반영하지 않았어요" in o["hash"] and "다시 올려 주세요" in o["hash"]
    assert "230행" in o["rate"] and "11월 3일 00:00 이후에 다시 반영해 주세요" in o["rate"] and "아무것도 반영하지 않았어요" in o["rate"]
    assert "보관 기간(3일)이 지나" in o["exp"] and "PC에서 다시 올려 주세요" in o["exp"]
    assert 'data-mig-jump="7"' in o["dep"] and "#7 기준에 붙는 기록" in o["dep"] and "체크하지 않은 기준을 가리키는 항목" in o["dep"]
    assert "지금 plan 상태(반영함)" in o["state"] and "서버 문구" in o["other"]
    for k in ("stale", "hash", "rate", "exp", "state"):
        assert o[k].startswith(("확인", "오늘", "보관", "지금")), (k, "첫 줄 = 사람 말(코드는 기술 정보에만)")
    assert o["fail"] == ["NAME-REQUIRED"] and o["kept"]
    b0 = o["body0"]
    assert "본문 &lt;b&gt;전문&lt;/b&gt;\n둘째 줄" in b0 and "본문 <b>" not in b0, "본문 = esc 로만"
    assert 'aria-expanded="true"' in b0 and "받은 그대로(JSON)" in b0 and "written" in b0
    assert "본문은 지웠어요" in o["bodies"] and "출처 이름" in o["bodies"] and "c" * 64 in o["bodies"]
    assert o["gets"] == [f"/api/migrations/mp_{'1' * 24}/items/{n}" for n in (0, 5, 6)], "펼칠 때 하나씩"
    assert o["closed"] is False and o["closedEsc"] is False and o["refetch"] == 3, "접기 · 다시 펼치면 받은 것 그대로(요청 0)"
    rt = o["rcText"]
    for w in ("이관 영수증", "import_batch_id", "receipt_hash", "결과별 개수", "반영함", "이미 있음", "체크 안 함", "거절 · 건너뜀",
              "본문 해시 대조", "1 / 3 일치", "일치", "다름", "휴지통에 있음", "r_1", "i_1", "o_4"):
        assert w in rt, w
    assert o["rc"].count('class="chip st-mine">일치') == 1 and o["rc"].count('class="chip flag">다름') == 1
    print("OK — B3 오류 문구(PLAN-STALE 바뀐 항목·HASH-MISMATCH·RATE-LIMIT resume_at·EXPIRED·CHECK-DEPENDENCY seq·STATE) · 본문 펼침(하나씩·esc·지운 본문·출처) · 영수증(결과별·해시 일치/다름/휴지통)")


def test_off_applied():
    """꺼짐(또는 허용 목록 밖) + applied plan — 목록·영수증 링크·영수증은 보이고, 토큰 발급·기준 체크·[반영]은 없다(그 자리에 안내).
    발급 직후 받은 토큰이 남아 있어도 꺼짐이면 그리지 않는다. [폐기]·[취소]는 스위치와 무관하게 남는다."""
    o = mig_run(f"""
const T = {json.dumps(TOKENS, ensure_ascii=False)}, P = {json.dumps(PLANS, ensure_ascii=False)}, D = {json.dumps(DETAIL, ensure_ascii=False)};
migToken = {{label: "이관 업로더", token: "mig_mt_0123456789abcdef.SECRET"}};
out.list = {{}};
for (const [k, sw] of [["off", {{enabled: false}}], ["deny", {{allowed: false}}]]) out.list[k] = migListHtml(Object.assign({{}}, T, sw), Object.assign({{}}, P, sw));
// 상세 — 꺼짐이면 sealed 확인 화면에 체크 상자·[반영]·대화상자 0, 안내 + [취소]
GETS["/api/migrations/" + D.plan_id] = {{ok: true, j: D}};
GETS["/api/migrations"] = {{ok: true, j: Object.assign({{}}, P, {{enabled: false}})}};
mk("view"); mk("mig-plan");
await migPlanLoad(D.plan_id); out.on = MIG.on; out.sealedOff = els["mig-plan"].innerHTML;
GETS["/api/migrations"] = {{ok: true, j: P}};
await migPlanLoad(D.plan_id); out.on2 = MIG.on; out.sealedOn = els["mig-plan"].innerHTML;
// applied — 꺼져도 영수증
const A = Object.assign({{}}, D, {{plan_id: "mp_" + "2".repeat(24), state: "applied", items: []}});
GETS["/api/migrations/" + A.plan_id] = {{ok: true, j: A}};
GETS["/api/migrations/" + A.plan_id + "/receipt"] = {{ok: true, j: {{plan_id: A.plan_id, import_batch_id: A.plan_id, plan_hash: "b".repeat(64), receipt_hash: "d".repeat(64),
  applied_at: "2026-11-01T02:00:00+00:00", counts: {{results: {{applied: 1}}, units: {{record: {{applied: 1}}}}}},
  items: [{{seq: 0, unit_kind: "record", original_id: "o_0", content_hash: "e".repeat(64), result: "applied", target_id: "r_1", stored_hash: "e".repeat(64), target_state: "live"}}]}}}};
GETS["/api/migrations"] = {{ok: true, j: Object.assign({{}}, P, {{enabled: false}})}};
await migPlanLoad(A.plan_id); out.receipt = strip(els["mig-plan"].innerHTML);
""")
    applied = f'href="#_setup/migration/mp_{"2" * 24}"'
    for k, h in o["list"].items():
        assert 'id="mig-off"' in h and "지난 plan과 영수증은 아래에서 볼 수 있어요" in h, k
        assert 'data-mig="tok-new"' not in h and "이관이 켜지면 여기서 새 토큰을 발급해요" in h, (k, "발급 버튼 대신 안내")
        assert "SECRET" not in h and 'id="mig-token"' not in h, (k, "꺼짐 = 받은 토큰도 그리지 않음")
        assert h.count(applied) == 2 and ">영수증 보기</a>" in h and f'href="#_setup/migration/mp_{"1" * 24}"' in h, (k, "plan 목록·영수증 링크 보임")
        assert 'data-mig="tok-revoke"' in h, (k, "폐기는 스위치 무관")
        assert 'data-mig="apply' not in h and "data-mig-check" not in h
    so = o["sealedOff"]
    assert o["on"] is False and 'id="mig-off"' in so and "기준 체크와 반영을 할 수 없어요" in so
    assert "data-mig-check" not in so and 'data-mig="apply"' not in so and 'id="mig-dlg"' not in so and 'data-mig="apply-go"' not in so, "꺼짐 = 체크·[반영]·대화상자 0"
    assert 'data-mig="cancel"' in so and so.count('data-mig="body"') == 8, "[취소]·본문 보기는 그대로"
    assert "체크함" in so and "체크 안 함" in so, "기준 체크 상태는 글로만"
    son = o["sealedOn"]
    assert o["on2"] is True and 'id="mig-off"' not in son and son.count("data-mig-check") == 3 and 'data-mig="apply"' in son and 'id="mig-dlg"' in son
    rt = o["receipt"]
    assert "이관 영수증" in rt and "r_1" in rt and "1 / 1 일치" in rt, "꺼져도 영수증"
    print("OK — B4 꺼짐·허용 목록 밖 + applied plan = 목록·영수증 링크·영수증 보임 · 토큰 발급·기준 체크·[반영]·대화상자 0(그 자리 안내) · [폐기]·[취소] 그대로 · 켜짐 = 그대로")


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
            app = (await h.get("/app")).text
            assert "function renderMigration(pid)" in app and '["migration", "이관"]' in app
    finally:
        site.dev, site.dev_user = real
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    print("OK — C HTTP(화면이 읽는 키: enabled·allowed·token_days·tokens·plans·limits · 발급 토큰 mig_mt_ · /app 이관 절)")


async def run():
    db.init_schema()
    cleanup()
    try:
        test_static()
        test_list_tokens()
        test_confirm_apply()
        test_errors_body_receipt()
        test_off_applied()
        await test_http()
    finally:
        cleanup()
        db.close()


if __name__ == "__main__":
    asyncio.run(run())
