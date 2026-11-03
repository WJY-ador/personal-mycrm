"""MCP facade 시험 (2026-11-02, 계획 「MCP facade(A′)」 §7).

실행: DATABASE_URL=postgresql://localhost/crm_test_facade python3 server/test_facade.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1) 카탈로그: family 13 · op 마다 tier·family 정확히 하나 · 겉면 enum = tier 분할 · 예시 전부 입력 스키마 통과 · K2(D∪P ↔ shown 빌더)
2) 전 op 대칭: 읽기 = 직접 결과 그대로 · 쓰기·확정·삭제 = 같은 모양(ID·시각 가림) · 오류 코드 같음
3) bind: REQUIRED · 위조 · 대상 변경 STALE(detail 에 새 preview) · 인자 변경 STALE · 비밀 회전 STALE · 직접 D 도구 선택 bind
4) 가드: TIER-MISMATCH · OP-UNKNOWN(가까운 이름) · ARG-INVALID(detail) · NAME-REQUIRED 그대로 · 이관 op 은 decide_preview 대상 아님
5) 집계: facade 1호출 = 사용 집계 1번(f:<op>), 겉면 이름은 세지 않음 · flush 뒤 usage_daily 에 f: 키 그대로
6) find·설명·annotations·INSTRUCTIONS
"""
import asyncio
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_facade). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "fc-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "facade-test-secret-1"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

from mcp.client import Client  # noqa: E402

import db  # noqa: E402
import facade  # noqa: E402
import main  # noqa: E402

MAIN, NONAME = "fc-main@example.com", "fc-noname@example.com"
LAYOUT_OPS = {"layout_get", "layout_set", "layout_reset"}
EDIT_OPS = {"record_edit", "record_title_set"}
EMAILS = (MAIN, NONAME)
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
ID_RE = re.compile(r"^[a-z]{1,3}_[A-Za-z0-9_-]{6,}$")
TS_RE = re.compile(r"^\d{4}-\d\d-\d\d[T ]\d")
BODY = "도입 회의에서 입력 담당을 먼저 정했다. 도구 비교는 그다음이었다."
QUOTE = "입력 담당을 먼저 정했다"


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def ok(msg):
    print("OK —", msg, flush=True)


def val(res):
    if getattr(res, "structured_content", None) is not None:
        sc = res.structured_content
        return sc.get("result", sc) if isinstance(sc, dict) and set(sc) == {"result"} else sc
    if len(res.content) != 1:
        return [json.loads(x.text) for x in res.content]
    return json.loads(res.content[0].text)


def code(res):
    assert res.is_error, ("오류가 아님", res.content[0].text[:300] if res.content else res)
    m = CODE.search(res.content[0].text)
    return m.group(1) if m else "SDK"


def detail(res):
    t = res.content[0].text
    i = t.index(" detail=")
    return json.loads(t[i + len(" detail="):])


def mask(v, key=""):
    """ID·시각을 가린다 — 직접(A 대상)·facade(B 대상) 결과의 모양 비교용. via 는 facade 만 단다(따로 본다)."""
    if isinstance(v, dict):
        return {k: mask(x, k) for k, x in v.items() if k != "via"}
    if isinstance(v, list):
        return [mask(x) for x in v]
    if key == "id" or key.endswith("_id") or key in ("created", "updated", "at"):
        return "*"
    if isinstance(v, str) and (ID_RE.match(v) or TS_RE.match(v)):
        return "*"
    return v


async def direct(c, op, args):
    return await c.call_tool(op, args)


async def via(c, op, params, bind=None):
    o = facade.OPS[op]
    a = {"op": op, "params": params}
    if bind is not None:
        a["bind"] = bind
    return await c.call_tool(o.tier, a)


async def preview(c, op, params):
    r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": op, "params": params}})
    assert not r.is_error, r.content[0].text[:400]
    return val(r)


async def via_bound(c, op, params):
    pv = await preview(c, op, params)
    return await via(c, op, params, pv["bind"])


# ── 1) 카탈로그 ─────────────────────────────────────────

async def test_catalog():
    raw = (HERE / "mcp_catalog.json").read_text(encoding="utf-8")

    def no_dup(pairs):
        keys = [k for k, _ in pairs]
        assert len(keys) == len(set(keys)), f"카탈로그 키 중복: {[k for k in keys if keys.count(k) > 1]}"
        return dict(pairs)
    cat = json.loads(raw, object_pairs_hook=no_dup)
    fams = [f["key"] for f in cat["families"]]
    assert len(fams) == 13 == len(set(fams)), fams
    assert [f["label"] for f in cat["families"]] == ["상태·도움·나", "질문·프로필", "내 글", "판단 후보", "자료 종류·항목", "사람",
                                                     "출처·읽고 든 생각", "활동", "저장 승인 대기", "휴지통", "문의", "이관", "PC 연결"]
    for op, s in cat["ops"].items():
        assert s["tier"] in facade.TIERS and s["family"] in fams, op
        assert set(s) <= {"family", "tier", "keywords", "examples", "bind", "direct", "rule"}, (op, set(s))   # 설명은 카탈로그에 적지 않는다
        assert s.get("examples") or op in LAYOUT_OPS, f"예시 없음: {op}"   # 화면 배치 op 예시는 레지스트리에서 만든다(카탈로그에 없음)
        assert not (op in LAYOUT_OPS and "examples" in s), op
        assert s.get("bind") in (None, "self") and (s.get("bind") != "self" or s["tier"] == "decide"), op
        assert not re.search(r"@|/Users/|\.onrender\.com", json.dumps(s, ensure_ascii=False)), f"공개 레포 — 개인 값 금지: {op}"
    assert set(cat["ops"]) == set(facade.OPS)
    # 직접 도구 48 은 전부 카탈로그에, facade 전용은 direct=false 로만
    async with Client(main.mcp) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
    direct_ops = set(tools) - main.FACADE_TOOLS
    assert len(direct_ops) == 48 and direct_ops == {o for o, x in facade.OPS.items() if x.direct}, len(direct_ops)
    # 이관 family = 직접 영수증 1 + facade 전용 7(본체 migration_mcp 표와 tier 같음) · 자기 바인딩 = 이관 확정 3 뿐
    import migration_mcp
    mig = {o for o, x in facade.OPS.items() if x.family == "migration"}
    assert mig == set(migration_mcp.OPS), mig ^ set(migration_mcp.OPS)
    for op, v in migration_mcp.OPS.items():
        assert facade.OPS[op].tier == v["tier"], op
        assert facade.OPS[op].direct == (op == "migration_receipt_get"), op
    assert {o for o, x in facade.OPS.items() if x.bind == "self"} == {"migration_apply", "migration_cancel", "migration_revert"}
    # PC 연결 family(2026-11-02 가안 2) = facade 전용 7(본체 token_grants) — 확정 3 은 hmac bind(K2 shown 빌더)
    pc = {o for o, x in facade.OPS.items() if x.family == "pc"}
    assert pc == {"pc_list", "pc_connect", "migration_token_send", "pc_forget", "token_grant_status", "token_list", "token_revoke"}, pc
    assert {o: facade.OPS[o].tier for o in pc} == {"pc_list": "read", "pc_connect": "write", "migration_token_send": "decide",
                                                   "pc_forget": "decide", "token_grant_status": "read", "token_list": "read",
                                                   "token_revoke": "decide"}
    assert {o for o in pc if facade.OPS[o].bind == "hmac"} == {"migration_token_send", "pc_forget", "token_revoke"}
    # 화면 배치(2026-11-03 §5-2) = facade 전용 3(상태·도움·나 family, R 1 · W 2)
    assert {o: (facade.OPS[o].family, facade.OPS[o].tier) for o in LAYOUT_OPS} == {
        "layout_get": ("state", "read"), "layout_set": ("state", "write"), "layout_reset": ("state", "write")}
    # 수기 수정 A0′(2026-11-03 §5-1) = facade 전용 2(내 글 family, record_edit = D hmac · record_title_set = W)
    assert {o: (facade.OPS[o].family, facade.OPS[o].tier, facade.OPS[o].bind) for o in EDIT_OPS} == {
        "record_edit": ("record", "decide", "hmac"), "record_title_set": ("record", "write", None)}
    assert {o for o, x in facade.OPS.items() if not x.direct} == {"decide_preview"} | (mig - {"migration_receipt_get"}) | pc | LAYOUT_OPS | EDIT_OPS
    # 겉면 enum = tier 분할(겹침·빠짐 없음)
    enums = {t: tools[t].input_schema["properties"]["op"]["enum"] for t in facade.TIERS}
    allops = [o for t in facade.TIERS for o in enums[t]]
    assert len(allops) == len(set(allops)) and set(allops) == set(facade.OPS), "op 은 등급 도구 하나에만"
    for t in facade.TIERS:
        assert set(enums[t]) == {o for o, x in facade.OPS.items() if x.tier == t}, t
    assert enums["purge"] == ["trash_purge"], enums["purge"]
    # 예시 전부 입력 스키마 통과(decide_preview 예시는 안쪽 params 도)
    n = 0
    for op, o in facade.OPS.items():
        for ex in o.examples:
            facade.validate(o, ex)
            n += 1
            if op == "decide_preview":
                facade.validate(facade.OPS[ex["op"]], ex["params"])
    # 게이트 문장 — D∪P 전부(이관 포함)에 「…때만·뒤에만」 문장. 카탈로그 rule 은 docstring 에 그 문장이 없을 때만 둔다
    gate = re.compile(r"때만|뒤에만")
    for op, o in facade.OPS.items():
        if o.tier in ("decide", "purge"):
            assert gate.search(facade.gates_of(o)), f"게이트 문장 없음: {op}"
            if o.rule:
                assert not any(gate.search(x) for x in facade.gate_sentences(o.doc)), f"docstring 에 이미 있는데 카탈로그 rule 도 있음: {op}"
    assert "스위치와 무관" in facade.rule_of(facade.OPS["migration_receipt_get"])
    # K2 — D∪P(자기 바인딩 제외) ↔ shown 빌더 대칭
    dp = {o for o, x in facade.OPS.items() if x.tier in ("decide", "purge") and x.bind != "self"}
    assert set(facade.PREVIEWS) == dp == set(facade.hmac_ops()), set(facade.PREVIEWS) ^ dp
    assert set(tools["read"].input_schema["properties"]) == {"op", "params"}
    pv_enum = facade.OPS["decide_preview"].tool.parameters["properties"]["op"]["enum"]
    assert set(pv_enum) == dp, pv_enum
    # 분류 기준(계획 §1) 그대로
    tiers = {o: x.tier for o, x in facade.OPS.items() if x.direct}
    assert {o for o, t in tiers.items() if t == "purge"} == {"trash_purge"}
    assert {o for o, t in tiers.items() if t == "decide"} == {
        "candidate_decide", "definition_apply", "item_decide", "record_provenance_set", "definition_archive", "definition_restore",
        "source_reflection_review", "person_delete", "source_reflection_delete", "trash_move", "trash_restore", "feedback_send"}
    assert {o for o, t in tiers.items() if t == "write"} == {
        "question_add", "record_add", "candidates_propose", "profile_set", "definition_propose", "item_propose", "record_attach",
        "display_name_set", "person_save", "source_create", "source_reflection_save"}
    ok(f"카탈로그(family 13 · op {len(facade.OPS)} 마다 tier·family 하나 · enum = tier 분할 · 예시 {n}개 스키마 통과 · K2 대칭 · 분류 기준)")


# ── 준비 ───────────────────────────────────────────────

def setup():
    uid = db.user_by_email(MAIN)["id"]
    db.display_name_set(uid, "facade 시험")
    q = db.question_add(uid, "무엇부터 정하나")
    S = {"uid": uid, "q": q["id"]}

    def rec(title="기록"):
        return db.record_add(uid, title, BODY, q["id"])["id"]

    def cand():
        rid = rec()
        added, _ = db.candidates_propose(uid, rid, q["id"], [{"text": "입력 담당부터 정한다", "quote": QUOTE}], "ai")
        return added[0]

    def obj(apply=True, key="k"):
        p = db.definition_propose(uid, None, 0, {"key": key, "label": "교훈", "semantic_kind": "principle", "policy": {}, "fields": []})
        if apply:
            db.definition_apply(uid, p["object_id"], p["proposal_id"], 0)
        return p

    S["rec"], S["rec2"] = rec(), rec()
    S["cand"] = [cand(), cand(), cand()]
    S["def_pending"] = [obj(False, "pa"), obj(False, "pb")]
    S["def_applied"] = [obj(True, "aa")["object_id"], obj(True, "ab")["object_id"]]
    P = obj(True, "pr")["object_id"]
    S["obj"] = P
    S["items"] = [db.item_propose(uid, P, 1, None, 0, None, "입력 담당 먼저", "도구보다 사람을 먼저.", {}, []) for _ in range(3)]
    S["prov"] = [rec(), rec()]
    S["src"] = db.source_create(uid, "url", "도입 사례 글", "https://example.com/a")["id"]
    S["refl_rev"] = [db.source_reflection_save(uid, S["src"], "reaction", "우리 팀에도 맞겠다.", "", None)["id"] for _ in range(3)]
    S["refl_del"] = [db.source_reflection_save(uid, S["src"], "reaction", "지울 생각.", "", None)["id"] for _ in range(2)]
    S["people"] = [db.person_save(uid, f"팀장 {i}", "", None)["id"] for i in range(3)]
    S["trash"] = [rec("지울 글"), rec("지울 글")]
    S["purge"] = [rec("영구 삭제할 글"), rec("영구 삭제할 글")]
    for r in S["purge"]:
        db.trash_move(uid, "record", r)
    return S


# ── 2) 전 op 대칭 ───────────────────────────────────────

def read_args(S):
    return {
        "state_get": {}, "help_get": {"topic": "words"}, "me_get": {}, "me_aggregate_get": {"period": "30d"},
        "question_list": {}, "record_get": {"record_id": S["rec"]}, "candidate_list": {"question_id": S["q"]},
        "definitions_get": {"object_ids": None, "include_archived": True}, "person_list": {}, "person_get": {"person_id": S["people"][2]},
        "person_context_get": {"person_id": S["people"][2]}, "source_list": {}, "source_get": {"source_id": S["src"]},
        "source_context_get": {"source_id": S["src"]}, "source_reflection_list": {"source_id": S["src"]},
        "source_reflection_get": {"reflection_id": S["refl_rev"][2]}, "activity_list": {}, "activity_get": {"activity_id": "a_example01"},
        "inbox_list": {}, "inbox_get": {"import_id": "ie_example01"}, "trash_list": {}, "ticket_list_mine": {},
        "ticket_get_mine": {"ticket_id": "t_example01"}, "migration_receipt_get": {"plan_id": "mp_example01"},
    }


async def test_symmetry(S):
    async with Client(main.mcp) as c:
        # 읽기 — 결과(또는 오류 코드) 그대로
        ra = read_args(S)
        reads = {o for o, x in facade.OPS.items() if x.tier == "read" and x.direct}
        assert set(ra) == reads, set(ra) ^ reads
        for op, a in ra.items():
            d, f = await direct(c, op, a), await via(c, op, a)
            assert d.is_error == f.is_error, (op, d.content[0].text[:200], f.content[0].text[:200])
            if d.is_error:
                assert code(d) == code(f), (op, code(d), code(f))
            else:
                assert val(d) == val(f), op
                assert [x.text for x in d.content] == [x.text for x in f.content], f"{op} 본문 모양"
        # 쓰기 — A 직접 · B facade, 모양 같음
        r3, r4 = db.record_add(S["uid"], "후보용", BODY, S["q"])["id"], db.record_add(S["uid"], "후보용", BODY, S["q"])["id"]
        wa = {
            "question_add": ({"text": "다음 질문"},) * 2,
            "record_add": ({"text": BODY, "title": "새 기록"},) * 2,
            "candidates_propose": tuple({"record_id": r, "question_id": "", "candidates": [{"text": "담당 먼저", "quote": QUOTE}]} for r in (r3, r4)),
            "profile_set": ({"key": "purpose", "value": "판단을 모은다", "status": "confirmed", "source": "사용자 답"},) * 2,
            "definition_propose": ({"object_id": None, "expected_revision": 0, "definition_json": json.dumps(
                {"key": "w", "label": "새 종류", "semantic_kind": "collection", "policy": {}, "fields": []})},) * 2,
            "item_propose": ({"object_id": S["obj"], "schema_revision": 1, "item_id": None, "expected_revision": 0, "code": None,
                              "title": "새 항목", "body": "본문", "data_json": "{}", "links": []},) * 2,
            "record_attach": tuple({"record_id": r, "use_at": "다음 회의"} for r in (S["rec"], S["rec2"])),
            "display_name_set": ({"display_name": "facade 시험"},) * 2,
            "person_save": ({"alias": "새 사람"},) * 2,
            "source_create": ({"kind": "url", "name": "도입 사례 글", "location": "https://example.com/a"},) * 2,
            "source_reflection_save": ({"source_id": S["src"], "kind": "summary", "body": "요약"},) * 2,
        }
        writes = {o for o, x in facade.OPS.items() if x.tier == "write" and x.direct}   # facade 전용 쓰기(pc_connect)는 test_token_grants
        assert set(wa) == writes, set(wa) ^ writes
        for op, (a, b) in wa.items():
            d, f = await direct(c, op, a), await via(c, op, b)
            assert not d.is_error and not f.is_error, (op, d.content[0].text[:300], f.content[0].text[:300])
            assert mask(val(d)) == mask(val(f)), (op, mask(val(d)), mask(val(f)))
        # 쓰기 오류 코드 — 같은 잘못된 인자
        for op, a in (("record_attach", {"record_id": "r_example01", "use_at": "x"}),
                      ("candidates_propose", {"record_id": "r_example01", "question_id": "", "candidates": [{"text": "a", "quote": "b"}]}),
                      ("person_save", {"alias": "", "person_id": ""})):
            d, f = await direct(c, op, a), await via(c, op, a)
            assert code(d) == code(f), (op, code(d), code(f))
        # 확정·삭제 — A 직접 · B facade(preview → bind), 모양 같음 + via
        it = S["items"]
        da = [
            ("candidate_decide", *({"candidate_id": x, "action": "confirm"} for x in S["cand"][:2])),
            ("definition_apply", *({"object_id": p["object_id"], "proposal_id": p["proposal_id"], "expected_revision": 0} for p in S["def_pending"])),
            ("definition_archive", *({"object_id": x} for x in S["def_applied"])),
            ("definition_restore", *({"object_id": x} for x in S["def_applied"])),
            ("item_decide", *({"item_id": p["item_id"], "expected_revision": 0, "proposal_id": p["proposal_id"], "action": "apply",
                               "history_id": None} for p in it[:2])),
            ("record_provenance_set", *({"record_id": x, "author_kind": "self", "text_process": "structured", "reason": "구조만 정리했어요"}
                                        for x in S["prov"])),
            ("source_reflection_review", *({"reflection_id": x, "expected_revision": 0, "reviewed": True} for x in S["refl_rev"][:2])),
            ("source_reflection_delete", *({"reflection_id": x, "expected_revision": 0} for x in S["refl_del"])),
            ("person_delete", *({"person_id": x, "expected_revision": 0} for x in S["people"][:2])),
            ("trash_move", *({"kind": "record", "target_id": x, "expected_revision": None} for x in S["trash"])),
            ("trash_restore", *({"kind": "record", "target_id": x, "expected_revision": None} for x in S["trash"])),
            ("trash_purge", *({"kind": "record", "target_id": x, "expected_revision": None} for x in S["purge"])),
            ("feedback_send", *({"kind": "question", "text": "facade 시험 문의예요.", "tool": "find"},) * 2),
        ]
        direct_pv = {o for o in facade.PREVIEWS if facade.OPS[o].direct}   # facade 전용 확정 op(PC 연결)은 test_token_grants 가 본다
        assert {x[0] for x in da} == direct_pv, {x[0] for x in da} ^ direct_pv
        for op, a, b in da:
            d, f = await direct(c, op, a), await via_bound(c, op, b)
            assert not d.is_error and not f.is_error, (op, d.content[0].text[:300], f.content[0].text[:300])
            vd, vf = val(d), val(f)
            assert vf.get("via") == "facade" and "via" not in vd, op
            if op.startswith("definition_"):   # A·B 오브젝트는 key 만 다르다(사용자 안에서 key 유일)
                vd, vf = {**vd, "key": "*"}, {**vf, "key": "*"}
            assert mask(vd) == mask(vf), (op, mask(vd), mask(vf))
        # 확정·삭제 오류 코드 — bind 뒤 서버 검사(낡은 revision)는 같은 코드
        for op, a in (("person_delete", {"person_id": S["people"][2], "expected_revision": 9}),
                      ("source_reflection_review", {"reflection_id": S["refl_rev"][2], "expected_revision": 9, "reviewed": True}),
                      ("item_decide", {"item_id": it[2]["item_id"], "expected_revision": 9, "proposal_id": it[2]["proposal_id"],
                                       "action": "apply", "history_id": None})):
            d, f = await direct(c, op, a), await via_bound(c, op, a)
            assert code(d) == code(f) and code(d) not in ("BIND-STALE", "BIND-REQUIRED"), (op, code(d), code(f))
        # 없는 대상 — 직접 오류 코드 = 미리보기 오류 코드(미리보기가 같은 조회를 한다)
        for op in direct_pv:
            if op == "feedback_send":
                continue
            ex = facade.OPS[op].examples[0]
            d = await direct(c, op, ex)
            p = await c.call_tool("read", {"op": "decide_preview", "params": {"op": op, "params": ex}})
            assert code(d) == code(p), (op, code(d), code(p))
    ok(f"전 op 대칭(읽기 {len(ra)} 값·본문 그대로 · 쓰기 {len(wa)} · 확정·삭제 {len(da)} 모양 같음+via · 오류 코드 같음)")


# ── 3) bind ─────────────────────────────────────────────

async def test_bind(S):
    uid = S["uid"]
    cid = S["cand"][2]
    p = {"candidate_id": cid, "action": "exclude"}
    async with Client(main.mcp) as c:
        r = await via(c, "candidate_decide", p)
        assert code(r) == "BIND-REQUIRED" and "decide_preview" in r.content[0].text, r.content[0].text
        r = await via(c, "candidate_decide", p, "")
        assert code(r) == "BIND-REQUIRED"
        r = await via(c, "candidate_decide", p, "AAAAAAAAAAAAAAAA")   # 위조
        assert code(r) == "BIND-STALE"
        pv = detail(r)
        assert set(pv) == {"op", "shown", "impact", "irreversible", "bind"} and len(pv["bind"]) == facade.BIND_LEN, pv
        assert pv["shown"]["후보 문장"] == "입력 담당부터 정한다" and pv["shown"]["근거 인용"] == QUOTE and pv["irreversible"] is False, pv
        assert db.candidate_get(uid, cid)["status"] == "pending", "거절된 호출은 바꾸지 않는다"
        good = (await preview(c, "candidate_decide", p))["bind"]
        assert good == pv["bind"], "STALE detail 의 preview = 새 preview"
        # 인자 바뀜 → STALE
        r = await via(c, "candidate_decide", {"candidate_id": cid, "action": "confirm"}, good)
        assert code(r) == "BIND-STALE"
        # 정규화 — 기본값을 채운 것과 같은 params 는 같은 bind
        assert (await preview(c, "candidate_decide", {**p, "text": ""}))["bind"] == good
        # 대상 바뀜(문장 고침) → STALE
        db.candidate_decide(uid, cid, "edit", "입력 담당을 맨 먼저 정한다")
        r = await via(c, "candidate_decide", p, good)
        assert code(r) == "BIND-STALE" and detail(r)["shown"]["후보 문장"] == "입력 담당을 맨 먼저 정한다"
        # 비밀 회전 → STALE
        good = (await preview(c, "candidate_decide", p))["bind"]
        os.environ["CRM_SESSION_SECRET"] = "facade-test-secret-2"
        try:
            r = await via(c, "candidate_decide", p, good)
            assert code(r) == "BIND-STALE"
        finally:
            os.environ["CRM_SESSION_SECRET"] = "facade-test-secret-1"
        r = await via(c, "candidate_decide", p, good)
        assert not r.is_error and val(r)["status"] == "excluded" and val(r)["via"] == "facade", r.content[0].text[:300]
        # 직접 D 도구 선택 bind — 없으면 지금처럼, 틀리면 STALE, 맞으면 통과
        q2 = {"candidate_id": cid, "action": "pending"}
        r = await direct(c, "candidate_decide", {**q2, "bind": "AAAAAAAAAAAAAAAA"})
        assert code(r) == "BIND-STALE" and db.candidate_get(uid, cid)["status"] == "excluded"
        b = (await preview(c, "candidate_decide", q2))["bind"]
        r = await direct(c, "candidate_decide", {**q2, "bind": b})
        assert not r.is_error and "via" not in val(r) and val(r)["status"] == "pending"
        r = await direct(c, "candidate_decide", {"candidate_id": cid, "action": "exclude"})
        assert not r.is_error, "bind 없이도 지금처럼"
        # bind 를 params 안에 넣으면 거절(겉면 인자)
        r = await via(c, "candidate_decide", {**p, "bind": b}, b)
        assert code(r) == "ARG-INVALID"
        # find(op) 스키마엔 bind 가 없다(겉면 인자) — 직접 도구 스키마엔 선택 인자로 있다
        f = val(await c.call_tool("find", {"op": "candidate_decide"}))
        assert "bind" not in f["input_schema"]["properties"] and "bind" not in f["input_schema"].get("required", [])
        tools = {t.name: t for t in (await c.list_tools()).tools}
        for op in (o for o in facade.PREVIEWS if facade.OPS[o].direct):
            assert "bind" in tools[op].input_schema["properties"] and "bind" not in tools[op].input_schema.get("required", []), op
        # 되돌릴 수 없음 표시 — 영구 삭제·밖으로 보내기 · 휴지통 꺼짐이면 사람 삭제도
        pv = await preview(c, "trash_purge", {"kind": "record", "target_id": S["trash"][0], "expected_revision": None})
        assert pv["irreversible"] is True and pv["shown"]["종류"] == "내 글"
        pv = await preview(c, "person_delete", {"person_id": S["people"][2], "expected_revision": 0})
        assert pv["irreversible"] is False
        os.environ["CRM_TRASH_ENABLED"] = "0"
        try:
            pv2 = await preview(c, "person_delete", {"person_id": S["people"][2], "expected_revision": 0})
            assert pv2["irreversible"] is True and pv2["bind"] != pv["bind"], "스위치가 바뀌면 bind 도 바뀐다"
        finally:
            os.environ["CRM_TRASH_ENABLED"] = "1"
        pv = await preview(c, "definition_archive", {"object_id": S["obj"]})
        assert pv["impact"] == {"items": 0, "referencing_fields": 0} or set(pv["impact"]) == {"items", "referencing_fields"}, pv
        pv = await preview(c, "feedback_send", {"kind": "bug", "text": "보낼 글 그대로", "tool": ""})
        assert pv["shown"]["보낼 글"] == "보낼 글 그대로" and pv["irreversible"] is True
        # 운영(비 DEV)에 비밀이 없으면 bind 를 만들지 않는다
        os.environ["CRM_DEV"], sec = "0", os.environ.pop("CRM_SESSION_SECRET")
        try:
            try:
                facade._key()
                raise AssertionError("비밀 없이 키를 만들었다")
            except db.CrmError as e:
                assert e.code == "BIND-UNAVAILABLE"
        finally:
            os.environ["CRM_DEV"], os.environ["CRM_SESSION_SECRET"] = "1", sec
    ok("bind(REQUIRED · 위조 · 인자·대상 변경 · 비밀 회전 = STALE + 새 preview · 정규화 · 직접 D 선택 bind · params 안 bind 거절 · irreversible · 비밀 없음)")


# ── 4) 가드 ─────────────────────────────────────────────

async def test_guards(S):
    async with Client(main.mcp) as c:
        r = await c.call_tool("write", {"op": "state_get", "params": {}})
        assert code(r) == "TIER-MISMATCH" and detail(r) == {"tier": "read"}, r.content[0].text
        r = await c.call_tool("decide", {"op": "trash_purge", "params": {}, "bind": "x"})
        assert code(r) == "TIER-MISMATCH" and detail(r) == {"tier": "purge"}
        r = await c.call_tool("read", {"op": "candidate_decide", "params": {}})
        assert code(r) == "TIER-MISMATCH"
        r = await c.call_tool("read", {"op": "state_gte", "params": {}})
        assert code(r) == "OP-UNKNOWN" and "state_get" in detail(r)["near"] and len(detail(r)["near"]) == 3, r.content[0].text
        r = await c.call_tool("read", {"op": "record_get", "params": {}})
        assert code(r) == "ARG-INVALID", r.content[0].text
        d = detail(r)
        assert set(d["expected"]) == {"record_id"} and d["expected"]["record_id"]["type"] == "string" and d["example"] == {"record_id": "r_example01"}, d
        r = await c.call_tool("read", {"op": "help_get", "params": {"topic": "faq"}})
        assert code(r) == "ARG-INVALID" and "topic" in detail(r)["expected"]
        r = await c.call_tool("read", {"op": "state_get", "params": "[]"})
        assert r.is_error
        # params 생략 = {}
        assert not (await c.call_tool("read", {"op": "state_get"})).is_error
        # decide_preview: 이관(자기 바인딩)·읽기 op 은 대상 아님 · 모르는 op
        r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "record_get", "params": {}}})
        assert code(r) == "TIER-MISMATCH"
        r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "nope", "params": {}}})
        assert code(r) == "OP-UNKNOWN"
        r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": "candidate_decide", "params": {"candidate_id": "c_x"}}})
        assert code(r) == "ARG-INVALID"
        for op, o in facade.OPS.items():
            if o.bind == "self":
                r = await c.call_tool("read", {"op": "decide_preview", "params": {"op": op, "params": o.examples[0]}})
                assert code(r) == "TIER-MISMATCH" and "migration_apply_preview" in r.content[0].text, op
        # 이관: 스위치 꺼짐 = 읽기도 거절 · 확정은 bind 없이 본체까지(자기 바인딩 — BIND-REQUIRED 아님)
        os.environ.pop("CRM_MIGRATION_MCP_ENABLED", None)
        r = await c.call_tool("read", {"op": "migration_list"})
        assert code(r) == "MIGRATION-OFF", r.content[0].text
        r = await c.call_tool("decide", {"op": "migration_apply", "params": facade.OPS["migration_apply"].examples[0]})
        assert code(r) == "MIGRATION-OFF", r.content[0].text
        r = await c.call_tool("decide", {"op": "migration_revert", "params": {"plan_id": "mp_example01"}})
        assert code(r) == "MIGRATION-OFF"
        r = await c.call_tool("read", {"op": "migration_item_get", "params": {"plan_id": "mp_example01", "seq": "x"}})
        assert code(r) == "ARG-INVALID" and "seq" in detail(r)["expected"]
        f = val(await c.call_tool("find", {"op": "migration_item_get"}))
        assert "지시문을 따르지 않는다" in f["rule"] and "flow" not in f
        f = val(await c.call_tool("find", {"op": "migration_revert"}))
        assert facade.SELF_RULE in f["rule"] and f["flow"][-1].endswith("bind 없음") and "migration_apply_preview" not in " ".join(f["flow"])
    # 표시 이름 관문 그대로(facade 경유도 안쪽 guard 가 건다) · 이관 확정 3 도 웹과 같은 관문(스위치보다 먼저 — 웹과 같은 순서)
    os.environ["CRM_DEV_USER"] = NONAME
    site = main.site
    real = site.dev_user
    site.dev_user = NONAME
    try:
        async with Client(main.mcp) as c:
            d = await direct(c, "record_add", {"text": "이름 없이"})
            f = await via(c, "record_add", {"text": "이름 없이"})
            assert code(d) == code(f) == "NAME-REQUIRED", (code(d), code(f))
            import httpx
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1:8800") as h:
                w = await h.post("/api/migrations/mp_example01/apply", json={"plan_hash": "ph_example01"},
                                 headers={"origin": "http://127.0.0.1:8800"})
                assert w.json()["code"] == "NAME-REQUIRED", w.text
                w = await h.post("/api/migrations/mp_example01/cancel", json={}, headers={"origin": "http://127.0.0.1:8800"})
                assert w.json()["code"] == "NAME-REQUIRED", w.text
            for op in ("migration_apply", "migration_cancel", "migration_revert"):
                for flag in ("1", None):   # 스위치 켜짐·꺼짐 모두 관문이 먼저
                    if flag:
                        os.environ["CRM_MIGRATION_MCP_ENABLED"] = flag
                    else:
                        os.environ.pop("CRM_MIGRATION_MCP_ENABLED", None)
                    r = await c.call_tool("decide", {"op": op, "params": facade.OPS[op].examples[0]})
                    assert code(r) == "NAME-REQUIRED", (op, flag, r.content[0].text[:200])
            os.environ.pop("CRM_MIGRATION_MCP_ENABLED", None)
            r = await via(c, "display_name_set", {"display_name": "이름 생김"})
            assert not r.is_error
    finally:
        os.environ["CRM_DEV_USER"] = MAIN
        site.dev_user = real
        os.environ.pop("CRM_MIGRATION_MCP_ENABLED", None)
    ok("가드(TIER-MISMATCH ×3 · OP-UNKNOWN 가까운 이름 3 · ARG-INVALID detail{expected, example} · decide_preview 대상 · 이관 스위치 꺼짐 = 읽기도 거절"
       "·확정 bind 면제 · NAME-REQUIRED 그대로(이관 확정 3 = 웹과 같은 관문))")


# ── 5) 집계 ─────────────────────────────────────────────

def _usage():
    return {(k[2], k[3]): n for k, n in db.usage_snapshot().items()}


def _delta(before, after):
    return {k: after.get(k, 0) - before.get(k, 0) for k in set(before) | set(after) if after.get(k, 0) != before.get(k, 0)}


async def test_usage(S):
    async with Client(main.mcp) as c:
        b = _usage()
        await via(c, "state_get", {})
        assert _delta(b, _usage()) == {("f:state_get", "OK"): 1}, _delta(b, _usage())
        b = _usage()
        await direct(c, "state_get", {})
        assert _delta(b, _usage()) == {("state_get", "OK"): 1}
        b = _usage()
        await via(c, "record_get", {"record_id": "r_example01"})
        assert _delta(b, _usage()) == {("f:record_get", "RECORD-MISSING"): 1}
        b = _usage()
        await c.call_tool("write", {"op": "state_get", "params": {}})
        await c.call_tool("read", {"op": "state_gte", "params": {}})
        await c.call_tool("read", {"op": "record_get", "params": {}})
        assert _delta(b, _usage()) == {("f:state_get", "TIER-MISMATCH"): 1, ("f:?", "OP-UNKNOWN"): 1, ("f:record_get", "ARG-INVALID"): 1}
        p = {"candidate_id": S["cand"][2], "action": "exclude"}
        b = _usage()
        await via(c, "candidate_decide", p)
        assert _delta(b, _usage()) == {("f:candidate_decide", "BIND-REQUIRED"): 1}, _delta(b, _usage())
        b = _usage()
        pv = await preview(c, "candidate_decide", p)
        await via(c, "candidate_decide", p, pv["bind"])
        assert _delta(b, _usage()) == {("f:decide_preview", "OK"): 1, ("f:candidate_decide", "OK"): 1}, _delta(b, _usage())
        b = db.usage_snapshot()
        await c.call_tool("find", {"query": "후보"})
        d = {k: n for k, n in db.usage_snapshot().items() if n != b.get(k, 0)}
        assert [(k[1], k[2], k[3]) for k in d] == [(S["uid"], "find", "OK")], d   # find 도 그 사용자 행(미연결 '' 행 금지)
        # 겉면 이름(read·write·decide·purge)으로는 세지 않는다
        assert not any(k[0] in facade.TIERS for k in _usage()), "겉면 래퍼는 세지 않는다"
    # flush — f: 키가 usage_daily 에 그대로(이름 열 text, 길이 제한 없음 · 읽는 쪽은 이름을 그대로 쓴다)
    db.usage_flush()
    with db.tx() as c2:
        rows = {r["name"] for r in c2.execute("SELECT name FROM usage_daily WHERE user_id=%s", (S["uid"],)).fetchall()}
        anon = {r["name"] for r in c2.execute("SELECT name FROM usage_daily WHERE user_id=''").fetchall()}
    assert {"f:state_get", "f:candidate_decide", "f:decide_preview", "f:?", "state_get", "find"} <= rows, rows
    assert "find" not in anon, "find 는 uid 를 푼다 — 미연결('') 행 없음"
    import admin_db
    facts = admin_db._facts("usage", {"day": __import__("datetime").date.today(), "user_id": S["uid"], "name": "f:state_get", "code": "OK"}, None)
    assert facts["name"] == "f:state_get" and facts["result"] == "ok"
    ok("집계(facade 1호출 = 1번 f:<op> · 직접 = <op> · facade 단계 거절도 1번 · preview+decide = 2호출 2번 · 겉면 이름 0 · flush·운영 리포트 f: 그대로)")


# ── 6) find·설명 ────────────────────────────────────────

async def test_find(S):
    async with Client(main.mcp) as c:
        tools = {t.name: t for t in (await c.list_tools()).tools}
        assert tools["find"].annotations.read_only_hint and tools["read"].annotations.read_only_hint
        assert tools["purge"].annotations.destructive_hint and not (tools["decide"].annotations and tools["decide"].annotations.read_only_hint)
        assert tools["write"].annotations is None
        f = val(await c.call_tool("find", {}))
        assert [x["key"] for x in f["families"]] == [x["key"] for x in facade.FAMILIES] and len(f["families"]) == 13
        allops = [o for x in f["families"] for t in facade.TIERS for o in x["ops_by_tier"][t]]
        assert sorted(allops) == sorted(facade.OPS)
        m = val(await c.call_tool("find", {"query": "후보 남길게"}))["matches"]
        assert 0 < len(m) <= facade.FIND_MAX and "candidate_decide" in [x["op"] for x in m], m
        assert set(m[0]) == {"op", "family", "tier", "summary", "user_words", "rule"}
        m = val(await c.call_tool("find", {"query": "영구 삭제"}))["matches"]
        assert m[0]["op"] == "trash_purge" and "되돌릴 수 없다" in m[0]["rule"], m[0]
        m = val(await c.call_tool("find", {"query": "기록"}))["matches"]
        assert len(m) == facade.FIND_MAX
        assert val(await c.call_tool("find", {"query": "쀍쀍"}))["matches"] == []
        fam = val(await c.call_tool("find", {"family": "trash"}))
        assert fam["label"] == "휴지통" and {x["op"] for x in fam["ops"]} == {"trash_list", "trash_move", "trash_restore", "trash_purge"}
        m = val(await c.call_tool("find", {"query": "삭제", "family": "person"}))["matches"]
        assert {x["op"] for x in m} == {"person_delete"}, m
        d = val(await c.call_tool("find", {"op": "candidate_decide"}))
        assert set(d) == {"op", "tier", "family", "description", "input_schema", "examples", "rule", "flow"}
        assert d["description"] == tools["candidate_decide"].description and facade.COMMON_RULE in d["rule"] and "decide_preview" in d["flow"][0]
        d = val(await c.call_tool("find", {"op": "record_add"}))
        assert "flow" not in d and d["input_schema"] == tools["record_add"].input_schema and d["tier"] == "write"
        r = await c.call_tool("find", {"op": "record_ad"})
        assert code(r) == "OP-UNKNOWN" and "record_add" in detail(r)["near"]
        r = await c.call_tool("find", {"family": "nope"})
        assert r.is_error   # enum 밖 — SDK 또는 서버가 거절
        # 규칙 전달: decide·purge 설명 = 공통 문장 + op 별 게이트 문장 / INSTRUCTIONS 단락
        dd, pd = tools["decide"].description, tools["purge"].description
        assert facade.COMMON_RULE in dd and facade.COMMON_RULE in pd and facade.PURGE_RULE in pd
        for op in facade.ops_of("decide"):
            assert f"- {op}:" in dd, op
        assert "- candidate_decide: 사용자가 말하기 전에 부르지 않는다." in dd and "- trash_purge:" in pd
        assert "사용자가 분명히 말할 때만 부른다" in pd
        ins = main.INSTRUCTIONS
        assert "find 로 할 일(op)을 찾고 그 등급 도구로 부른다" in ins and "decide_preview" in ins and "migration_apply_preview" in ins
        assert "되물을 수 없다" in ins
        # find 는 search·fetch 이름을 쓰지 않는다(다음 묶음 예약)
        assert not {"search", "fetch"} & set(tools)
    ok("find(family 13 · query ≤8·부분 일치·family 걸기 · op 상세 = docstring·스키마·예시·rule·flow · OP-UNKNOWN) · annotations · 설명·INSTRUCTIONS 규칙")


async def test_layout(S):
    """화면 배치 op(§5-2): find 예시 = 레지스트리에서(컴포넌트 이름이 레지스트리 밖이면 안 됨, 예시는 layout_check 통과) · 설명에 컴포넌트 목록
    · read(layout_get) = 웹 GET 과 같은 함수 · write(layout_set) 페이지 단위 · STALE · INVALID(모르는 컴포넌트) · layout_reset · NAME-REQUIRED · 집계 f:"""
    reg = db.LAYOUT_REGISTRY
    async with Client(main.mcp) as c:
        d = val(await c.call_tool("find", {"op": "layout_set"}))
        assert d["tier"] == "write" and "화면 배치를 바꿔 달라고 말할 때만" in d["rule"], d["rule"]
        for ex in d["examples"]:
            names = [e["c"] for es in ex["layout"]["regions"].values() for e in es]
            assert names and set(names) <= set(reg["components"]), names
            assert db.layout_check({"v": 2, "pages": {ex["page"]: ex["layout"]}})
        for k, comp in reg["components"].items():
            assert f"{k}({comp['label']}" in d["description"], k
        assert d["input_schema"]["properties"]["page"]["enum"] == list(reg["pages"])
        assert "layout_set" in [m["op"] for m in val(await c.call_tool("find", {"query": "화면 배치"}))["matches"]]
        assert "화면 배치를 바꿔 달라고 말할 때만 layout_set" in main.INSTRUCTIONS
        g = val(await c.call_tool("read", {"op": "layout_get"}))
        assert g == db.layout_get(S["uid"]) and g["version"] == 0 and g["layout"] == db.DEFAULT_LAYOUT
        me = json.loads(json.dumps(g["layout"]["pages"]["me"]))
        me["tabs"].reverse()
        me["regions"]["summary"] = me["regions"]["summary"][:2]
        r = val(await c.call_tool("write", {"op": "layout_set", "params": {"page": "me", "layout": me, "version": 0}}))
        assert r == {"layout": {"v": 2, "pages": {"me": me}}, "version": 1}, r
        r = await c.call_tool("write", {"op": "layout_set", "params": {"page": "me", "layout": me, "version": 0}})
        assert code(r) == "LAYOUT-STALE", r
        bad = {**me, "regions": {"summary": [{"c": "pie", "p": {}}]}}
        r = await c.call_tool("write", {"op": "layout_set", "params": {"page": "me", "layout": bad, "version": 1}})
        assert code(r) == "LAYOUT-INVALID", r
        r = await c.call_tool("write", {"op": "layout_set", "params": {"page": "today", "layout": me, "version": 1}})
        assert r.is_error and code(r) in ("ARG-INVALID", None), r
        assert db.layout_get(S["uid"])["version"] == 1, "거절은 저장하지 않는다"
        r = val(await c.call_tool("write", {"op": "layout_reset", "params": {"page": "me"}}))
        assert r == {"layout": db.DEFAULT_LAYOUT, "version": 2}, r
        with db.tx() as cx:
            assert cx.execute("SELECT layout FROM page_layouts WHERE user_id=%s", (S["uid"],)).fetchone()["layout"] is None
        r = await c.call_tool("decide", {"op": "layout_set", "params": {}})
        assert code(r) == "TIER-MISMATCH", r
    # 표시 이름 관문 = 웹과 같은 write_gate(이름을 지우고 본다)
    with db.tx() as cx:
        cx.execute("UPDATE users SET display_name=NULL WHERE id=%s", (S["uid"],))
    try:
        async with Client(main.mcp) as c:
            r = await c.call_tool("write", {"op": "layout_reset", "params": {"page": "me"}})
            assert code(r) == "NAME-REQUIRED", r
    finally:
        db.display_name_set(S["uid"], "facade 시험")
    ok("화면 배치 op(find 예시·설명 = 레지스트리 · read = 웹 GET · 페이지 저장·STALE·INVALID·reset · TIER-MISMATCH · NAME-REQUIRED)")


async def run():
    db.init_schema()   # CI 는 빈 전용 DB — 스키마부터
    cleanup()
    try:
        await test_catalog()
        S = setup()
        await test_symmetry(S)
        await test_bind(S)
        await test_guards(S)
        await test_usage(S)
        await test_find(S)
        await test_layout(S)
    finally:
        cleanup()
        db.close()
    print("OK — facade 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
