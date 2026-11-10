"""꺼내기 양식 시험 (2026-11-10, facade 전용 읽기 op export_get).

실행: DATABASE_URL=postgresql://localhost/crm_test_export python3 server/test_export_forms.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1) 결정성 2) 미확정·남기지 않은 후보 빠짐, omitted.pending 3) 빈 절 없음 4) 휴지통·보관·지워진 글 빠짐 5) 다른 사용자 섞임 없음
6) quote 글자 그대로 7) ref 실재·revision 현재 값, 재료 행만 ref 8) 사람 별칭·출처 위치 없음 9) 행 상한 50 → omitted.truncated
10) 양식·scope 종류 불일치 ARG-INVALID 11) 기간 밖 확정 판단 빠짐 12) export_forms.py --check 13) 카탈로그 tier read = chat_mcp 고정 목록
"""
import asyncio
import copy
import datetime as _dt
import json
import os
import re
import subprocess
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_export). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ex-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "export-test-secret-1"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

from mcp.client import Client  # noqa: E402

import chat_mcp  # noqa: E402
import db  # noqa: E402
import export_forms as ef  # noqa: E402
import facade  # noqa: E402
import main  # noqa: E402

MAIN, OTHER, BULK = "ex-main@example.com", "ex-other@example.com", "ex-bulk@example.com"
EMAILS = (MAIN, OTHER, BULK)
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
NOW = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
TODAY = NOW.astimezone(ef.KST).date()
# 응답에 나오면 안 되는 표식(사람 별칭·출처 위치·읽고 든 생각·인용 밖 본문·다른 사용자)
ALIAS, LOCATION, REFLECTION, BODY_ONLY, OTHER_MARK = "별칭표식ZQX", "https://secret.example/loc-ZQX", "생각표식ZQX", "본문만표식ZQX", "남의자료ZQX"


def ok(msg):
    print("OK —", msg, flush=True)


def cleanup():
    with db.tx() as c:
        ids = [r["id"] for r in c.execute("SELECT id FROM users WHERE email = ANY(%s)", (list(EMAILS),)).fetchall()]
        c.execute("DELETE FROM admin_audit WHERE actor_id = ANY(%s) OR target_id = ANY(%s)", (ids, ids))
    for uid in ids:
        db.user_delete(uid)


def expect(code, fn, *a, **k):
    try:
        fn(*a, **k)
    except db.CrmError as e:
        assert e.code == code, (code, e.code, e.message)
        return e
    raise AssertionError(f"{code} 이어야 하는데 통과: {fn.__name__}{a}")


def sql(q, args=()):
    with db.tx() as c:
        c.execute(q, args)


def std_obj(uid, key):
    with db.tx() as c:
        r = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND std_id=%s", (uid, f"std:{key}")).fetchone()
    assert r, f"표준 오브젝트 없음: {key}"
    return r


def cands(uid, rid, qid, quotes):
    """quote 마다 후보 하나(같은 기록, 1편 3개까지)."""
    added, dropped = db.candidates_propose(uid, rid, qid or "", [{"text": f"판단 — {q[:8]}", "quote": q} for q in quotes], "ai")
    assert not dropped and len(added) == len(quotes), (added, dropped)
    return added


def item(uid, key, title, body, data=None, confirm=False):
    o = std_obj(uid, key)
    p = db.item_propose(uid, o["id"], o["revision"], None, 0, None, title, body, data or {}, [])
    it = db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")
    if confirm:
        it = db.item_decide(uid, it["id"], it["revision"], None, "confirm")
    return it["id"]


def days_ago(n):
    return (TODAY - _dt.timedelta(days=n)).isoformat()


# ── 준비 ───────────────────────────────────────────────

def setup():
    A = db.user_by_email(MAIN)["id"]
    B = db.user_by_email(OTHER)["id"]
    db.display_name_set(A, "꺼내기 시험")
    q1, q2, q3 = (db.question_add(A, t)["id"] for t in ("무엇부터 정하나", "도구는 언제 고르나", "아직 답이 없는 질문"))
    db.person_save(A, ALIAS, "", None)
    S = {"A": A, "B": B, "q1": q1, "q2": q2, "q3": q3}

    # 기록 1(q1, 출처 위치 있음) — 확정 1 · 미확정 1 · 남기지 않음 1
    body1 = f"도입 회의에서 입력 담당을 먼저 정했다.  두 칸 공백도 그대로. 도구 비교는 그다음이었다. 마지막 줄은 다른 이야기. {BODY_ONLY}"
    r1 = db.record_add(A, "도입 회의 메모", body1, q1, source_ref={"kind": "url", "name": "회의 노트", "location": LOCATION})["id"]
    c_conf, c_pend, c_excl = cands(A, r1, q1, ["입력 담당을 먼저 정했다.  두 칸 공백도 그대로.", "도구 비교는 그다음이었다.", "마지막 줄은 다른 이야기."])
    db.candidate_decide(A, c_conf, "confirm")
    db.candidate_decide(A, c_excl, "exclude")
    # 기록 2(q2·질문 없음) — 여러 줄 인용 확정 · 질문 없는 확정
    body2 = "첫 줄은 도구 이야기다.\n둘째 줄에서 사람을 먼저 본다고 정했다.\n셋째 줄은 질문과 상관없는 다짐이다."
    r2 = db.record_add(A, "도구 메모", body2, q2)["id"]
    (c_multi,) = cands(A, r2, q2, ["도구 이야기다.\n둘째 줄에서 사람을 먼저 본다고 정했다."])
    (c_loose,) = cands(A, r2, "", ["질문과 상관없는 다짐이다."])
    db.candidate_decide(A, c_multi, "confirm")
    db.candidate_decide(A, c_loose, "confirm")
    # 휴지통 글·지워진 글의 확정 판단(빠져야 한다)
    r_tr = db.record_add(A, "휴지통 갈 글", "휴지통 글의 확정 판단 문장이다.", q1)["id"]
    (c_tr,) = cands(A, r_tr, q1, ["휴지통 글의 확정 판단 문장이다."])
    db.candidate_decide(A, c_tr, "confirm")
    db.trash_move(A, "record", r_tr)
    r_del = db.record_add(A, "지워진 글", "지워진 글의 확정 판단 문장이다.", q1)["id"]
    (c_del,) = cands(A, r_del, q1, ["지워진 글의 확정 판단 문장이다."])
    db.candidate_decide(A, c_del, "confirm")
    sql("UPDATE records SET deleted_at=now() WHERE user_id=%s AND id=%s", (A, r_del))
    # 기간: 40일 전에 확정한 판단(30d 밖·90d 안) · 이력 없는 옛 확정 판단(updated 200일 전, 90d 밖·all 안)
    r_old = db.record_add(A, "옛 메모", "사십일 전에 확정한 판단이다. 이백일 전 판단이다.", q1)["id"]
    c_40, c_200 = cands(A, r_old, q1, ["사십일 전에 확정한 판단이다.", "이백일 전 판단이다."])
    db.candidate_decide(A, c_40, "confirm")
    db.candidate_decide(A, c_200, "confirm")
    sql("UPDATE candidate_history SET at = now() - interval '40 days' WHERE user_id=%s AND candidate_id=%s AND action='confirm'", (A, c_40))
    sql("DELETE FROM candidate_history WHERE user_id=%s AND candidate_id=%s", (A, c_200))
    sql("UPDATE candidates SET updated = now() - interval '200 days' WHERE user_id=%s AND id=%s", (A, c_200))
    # 읽고 든 생각(빠져야 한다)
    src = db.source_create(A, "url", "읽은 글", "https://example.com/read")["id"]
    db.source_reflection_save(A, src, "reaction", REFLECTION, "", None)

    # 기준: 확정 2(하나는 판 있음) · 미확정 1 · 확정 뒤 보관 1 · 확정 뒤 휴지통 1
    p1 = item(A, "principles", "사람을 먼저 정한다", "도구보다 입력 담당을 먼저 정한다.", confirm=True)
    p2 = item(A, "principles", "작게 시작한다", "한 팀에서 먼저 써 본다.", confirm=True)
    p_pend = item(A, "principles", "아직 고민 중인 기준", "미확정")
    p_arch = item(A, "principles", "보관한 기준", "보관", confirm=True)
    db.item_decide(A, p_arch, 2, None, "archive")
    p_tr = item(A, "principles", "휴지통 기준", "휴지통", confirm=True)
    db.trash_move(A, "item", p_tr, 2)
    with db.tx() as c:   # 판 이력 하나(확인 1번 경로 대신 직접) — ref.version_id 가 현재 판을 가리키는지 본다
        rev = c.execute("SELECT revision FROM items WHERE user_id=%s AND id=%s", (A, p1)).fetchone()["revision"]
        c.execute("INSERT INTO item_versions (user_id,id,item_id,version_no,item_revision,fields,links) VALUES (%s,%s,%s,1,%s,'{}','[]')",
                  (A, "iv_exporttest1", p1, rev))
        c.execute("UPDATE items SET current_version_id='iv_exporttest1' WHERE user_id=%s AND id=%s", (A, p1))
    # 결정: 3일 전 · 10일 전 · 100일 전 · 결정일 없음 · 꼴이 틀린 결정일 · 보관
    d3 = item(A, "decision_events", "입력 담당 지정", "담당을 먼저 정했다.", {"happened_on": days_ago(3)})
    d10 = item(A, "decision_events", "시범 팀 선정", "", {"happened_on": days_ago(10)})
    d100 = item(A, "decision_events", "예전 결정", "", {"happened_on": days_ago(100)})
    d_none = item(A, "decision_events", "날짜 없는 결정", "")
    d_bad = item(A, "decision_events", "꼴이 틀린 결정", "", {"happened_on": days_ago(2)})
    sql("UPDATE items SET data = jsonb_set(data, '{happened_on}', to_jsonb(%s::text)) WHERE user_id=%s AND id=%s",
        (days_ago(2).replace("-", "/"), A, d_bad))
    d_arch = item(A, "decision_events", "보관한 결정", "", {"happened_on": days_ago(1)})
    db.item_decide(A, d_arch, 1, None, "archive")

    # 다른 사용자 — 같은 꼴의 확정 자료(섞이면 안 된다)
    qb = db.question_add(B, f"{OTHER_MARK} 질문")["id"]
    rb = db.record_add(B, f"{OTHER_MARK} 글", f"{OTHER_MARK} 확정 판단 원문이다.", qb)["id"]
    (cb,) = cands(B, rb, qb, [f"{OTHER_MARK} 확정 판단 원문이다."])
    db.candidate_decide(B, cb, "confirm")
    item(B, "principles", f"{OTHER_MARK} 기준", "남의 기준", confirm=True)
    item(B, "decision_events", f"{OTHER_MARK} 결정", "", {"happened_on": days_ago(1)})

    S.update(c_conf=c_conf, c_pend=c_pend, c_excl=c_excl, c_multi=c_multi, c_loose=c_loose, c_tr=c_tr, c_del=c_del, c_40=c_40, c_200=c_200,
             p1=p1, p2=p2, p_pend=p_pend, p_arch=p_arch, p_tr=p_tr, d3=d3, d10=d10, d100=d100, d_none=d_none, d_bad=d_bad, d_arch=d_arch,
             qb=qb, cb=cb)
    return S


def get(uid, form, scope, now=NOW):
    return ef.assemble(uid, form, scope, now=now)


def refs(res, kind=None):
    return [r["ref"]["id"] for s in res["sections"] for r in s["rows"] if "ref" in r and (kind is None or r["ref"]["kind"] == kind)]


def sec(res, key):
    return next((s for s in res["sections"] if s["key"] == key), None)


# ── 시험 ───────────────────────────────────────────────

def test_shape_and_determinism(S):
    A = S["A"]
    for form, scope in (("headed_note", {"kind": "question"}), ("headed_note", {"kind": "question", "id": S["q1"]}),
                        ("period_report", {"kind": "period", "period": "30d"}), ("period_report", {"kind": "period", "period": "all"})):
        r1, r2 = get(A, form, scope), get(A, form, scope)
        assert r1 == r2, form
        later = get(A, form, scope, NOW + _dt.timedelta(seconds=1))   # 조립 시각만 다르다
        assert later["assembled_at"] != r1["assembled_at"]
        t1 = json.dumps(r1, ensure_ascii=False, sort_keys=True)
        t2 = json.dumps(later, ensure_ascii=False, sort_keys=True).replace(later["assembled_at"], r1["assembled_at"])
        assert t1 == t2, form
        assert r1["kind"] == "material" and r1["form"] == form and r1["form_version"] == 1 and r1["notice"] == ef.spec()["notice"]
        assert set(r1["omitted"]) == {"pending", "truncated"}
        if form == "headed_note":
            assert "markdown" in r1 and "outline" not in r1 and "rules" not in r1 and "basis" not in r1
        else:
            assert "markdown" not in r1 and r1["outline"] and r1["rules"] and r1["basis"]
            assert [o["key"] for o in r1["outline"]] == ["scope", "claims", "principles", "decisions", "undecided"]
            assert "13주" in r1["basis"]
    ok("1) 같은 입력이면 같은 sections·markdown(조립 시각만 다름) · 양식별 응답 키")


def test_confirmed_only(S):
    A = S["A"]
    allq = get(A, "headed_note", {"kind": "question"})
    ids = set(refs(allq))
    assert ids == {S["c_conf"], S["c_multi"], S["c_loose"], S["c_40"], S["c_200"]}, ids
    assert not {S["c_pend"], S["c_excl"]} & ids
    assert allq["omitted"]["pending"] == 1
    assert get(A, "headed_note", {"kind": "question", "id": S["q1"]})["omitted"]["pending"] == 1
    assert get(A, "headed_note", {"kind": "question", "id": S["q2"]})["omitted"]["pending"] == 0
    rep = get(A, "period_report", {"kind": "period", "period": "all"})
    assert rep["omitted"]["pending"] == 1 and S["c_pend"] not in refs(rep) and S["c_excl"] not in refs(rep)
    und = sec(rep, "undecided")
    assert [r["text"] for r in und["rows"]] == ["미확정 판단 후보 1건", "미확정 기준 1건"], und
    assert S["p_pend"] not in refs(rep, "item")
    # headed_note 구조: 질문 순 절(heading = 질문 문장) → 마지막 절 「질문 없이 남긴 판단」
    assert [s["key"] for s in allq["sections"]] == [S["q1"], S["q2"], "no_question"], [s["key"] for s in allq["sections"]]
    assert [s["heading"] for s in allq["sections"]] == ["무엇부터 정하나", "도구는 언제 고르나", "질문 없이 남긴 판단"]
    assert refs(allq)[:3] == [S["c_conf"], S["c_40"], S["c_200"]]
    md = allq["markdown"]
    assert md.startswith("## 무엇부터 정하나\n") and "## 질문 없이 남긴 판단" in md
    assert md.rstrip().splitlines()[-1].startswith(f"조립 {allq['assembled_at']}, 양식 headed_note@1, 범위 질문 전부, 넣지 않은 미확정 판단 후보 1건")
    ok("2) 확정만 · 미확정/남기지 않은 후보 빠짐 · omitted.pending(질문 범위·전체) · 절 순서·markdown 끝줄")


def test_empty_sections(S):
    A = S["A"]
    r = get(A, "headed_note", {"kind": "question", "id": S["q3"]})
    assert r["sections"] == [] and "확정한 판단이 아직 없어요." in r["markdown"]
    w = get(A, "period_report", {"kind": "period", "period": "7d"})
    keys = [s["key"] for s in w["sections"]]
    assert keys == ["scope", "claims", "principles", "decisions", "undecided"], keys
    for s in w["sections"]:
        assert s["rows"], s["key"]
    # 결정이 없는 사용자 = 결정 절 없음 · 범위 절은 항상
    C = db.user_by_email(BULK)["id"]
    e = get(C, "period_report", {"kind": "period", "period": "7d"})
    assert [s["key"] for s in e["sections"]] == ["scope"], e["sections"]
    assert get(C, "headed_note", {"kind": "question"})["sections"] == []
    ok("3) 빈 절은 응답에 없다(범위 절만 항상)")


def test_trash_archive_deleted(S):
    A = S["A"]
    allq = refs(get(A, "headed_note", {"kind": "question"}))
    assert S["c_tr"] not in allq and S["c_del"] not in allq
    rep = get(A, "period_report", {"kind": "period", "period": "all"})
    ids = refs(rep)
    assert not {S["c_tr"], S["c_del"], S["p_arch"], S["p_tr"], S["d_arch"]} & set(ids), ids
    assert set(refs({"sections": [sec(rep, "principles")]})) == {S["p1"], S["p2"]}
    ok("4) 휴지통 글·지워진 글의 후보 · 보관·휴지통 기준 · 보관 결정 빠짐")


def test_tenant(S):
    A = S["A"]
    outs = [get(A, "headed_note", {"kind": "question"}), get(A, "period_report", {"kind": "period", "period": "all"})]
    for o in outs:
        assert OTHER_MARK not in json.dumps(o, ensure_ascii=False)
        assert S["cb"] not in refs(o)
    expect("ARG-INVALID", get, A, "headed_note", {"kind": "question", "id": S["qb"]})
    b = get(S["B"], "headed_note", {"kind": "question"})
    assert refs(b) == [S["cb"]], refs(b)
    ok("5) 다른 사용자의 자료가 섞이지 않는다(남의 질문 ID = ARG-INVALID)")


def test_quote_verbatim(S):
    A = S["A"]
    r = get(A, "headed_note", {"kind": "question"})
    with db.tx() as c:
        db_q = {x["id"]: x["quote"] for x in c.execute("SELECT id, quote FROM candidates WHERE user_id=%s", (A,)).fetchall()}
    n = 0
    for s in r["sections"]:
        for row in s["rows"]:
            assert row["quote"] == db_q[row["ref"]["id"]], row
            n += 1
    multi = next(row for s in r["sections"] for row in s["rows"] if row["ref"]["id"] == S["c_multi"])
    assert multi["quote"] == "도구 이야기다.\n둘째 줄에서 사람을 먼저 본다고 정했다."
    assert "> 도구 이야기다.\n> 둘째 줄에서 사람을 먼저 본다고 정했다." in r["markdown"]
    assert "> 입력 담당을 먼저 정했다.  두 칸 공백도 그대로." in r["markdown"]
    rep = get(A, "period_report", {"kind": "period", "period": "all"})
    for row in sec(rep, "claims")["rows"]:
        assert row["quote"] == db_q[row["ref"]["id"]]
    ok(f"6) quote 가 candidates.quote 와 글자 그대로 같다({n}행 · 여러 줄 · 두 칸 공백)")


def test_refs(S):
    A = S["A"]
    with db.tx() as c:
        cand = {x["id"]: x["revision"] for x in c.execute("SELECT id, revision FROM candidates WHERE user_id=%s", (A,)).fetchall()}
        its = {x["id"]: x for x in c.execute("SELECT id, revision, current_version_id FROM items WHERE user_id=%s", (A,)).fetchall()}
        recs = {x["id"]: x["title"] for x in c.execute("SELECT id, title FROM records WHERE user_id=%s", (A,)).fetchall()}
    n = 0
    for res in (get(A, "headed_note", {"kind": "question"}), get(A, "period_report", {"kind": "period", "period": "all"})):
        mats = {s["key"]: s["material"] for f in ef.spec()["forms"] for s in f["sections"]}
        for s in res["sections"]:
            mat = mats.get(s["key"], "claims_by_question")
            for row in s["rows"]:
                assert set(row) <= set(ef.MATERIALS[mat]), (s["key"], row)
                if mat not in ef.REF_MATERIALS:
                    assert "ref" not in row and set(row) == {"text"}, (s["key"], row)   # 범위·아직 정하지 않은 것 = text 만
                    continue
                ref = row["ref"]
                n += 1
                if ref["kind"] == "candidate":
                    assert ref["id"] in cand and ref["revision"] == cand[ref["id"]], ref
                    assert row["record"]["title"] == recs[row["record"]["id"]] and re.match(r"^\d{4}-\d\d-\d\d$", row["record"]["date"])
                else:
                    assert ref["kind"] == "item" and ref["id"] in its and ref["revision"] == its[ref["id"]]["revision"], ref
                    assert ref.get("version_id") == its[ref["id"]]["current_version_id"], ref
    assert its[S["p1"]]["current_version_id"] == "iv_exporttest1"
    ok(f"7) 재료 행 {n}개 전부 ref(id 실재·revision 현재 값·확정 판 id) · 범위/미정 절 행은 ref 없음")


def test_no_alias_location(S):
    A = S["A"]
    for form, scope in (("headed_note", {"kind": "question"}), ("period_report", {"kind": "period", "period": "all"})):
        t = json.dumps(get(A, form, scope), ensure_ascii=False)
        for mark in (ALIAS, LOCATION, "secret.example", REFLECTION, BODY_ONLY, "회의 노트"):
            assert mark not in t, (form, mark)
    ok("8) 응답 어디에도 사람 별칭·출처 위치(·읽고 든 생각·인용 밖 본문)가 없다")


def test_truncation(S):
    C = db.user_by_email(BULK)["id"]
    body = "가나" * 60
    rid = db.record_add(C, "많은 판단", body, None)["id"]
    ev = std_obj(C, "decision_events")
    with db.tx() as c:   # 기록 1편 3개 한도를 넘겨 확정 판단 53개(직접 넣는다, 번호가 클수록 나중에 확정) · 결정 52개(번호가 클수록 늦은 결정일)
        for i in range(53):
            c.execute("INSERT INTO candidates (id,user_id,record_id,text,quote,quote_start,quote_end,origin,decision,updated) "
                      "VALUES (%s,%s,%s,%s,%s,%s,%s,'ai','confirmed',%s)",
                      (f"c_bulk{i:03d}", C, rid, f"판단 {i:03d}", body[i:i + 2], i, i + 2, NOW - _dt.timedelta(minutes=53 - i)))
        for i in range(52):
            c.execute("INSERT INTO items (user_id,id,object_id,schema_revision,title,data,revision) VALUES (%s,%s,%s,%s,%s,%s,1)",
                      (C, f"i_bulk{i:03d}", ev["id"], ev["revision"], f"결정 {i:03d}", json.dumps({"happened_on": days_ago(6 - i // 9)})))
    r = get(C, "headed_note", {"kind": "question"})
    s = sec(r, "no_question")
    assert len(s["rows"]) == 50 and r["omitted"]["truncated"] == {"no_question": 3}, r["omitted"]
    assert [x["ref"]["id"] for x in s["rows"]] == [f"c_bulk{i:03d}" for i in range(50)]
    assert "행 상한 50개로 뺀 판단 3건" in r["markdown"].splitlines()[-1]
    p = get(C, "period_report", {"kind": "period", "period": "7d"})
    assert p["omitted"]["truncated"] == {"claims": 3, "decisions": 2}, p["omitted"]
    # 시간 오름차순 절은 최신 50개를 남기고 오래된 것을 뺀다(싣는 순서는 오름차순 그대로)
    assert [x["ref"]["id"] for x in sec(p, "claims")["rows"]] == [f"c_bulk{i:03d}" for i in range(3, 53)]
    assert [x["ref"]["id"] for x in sec(p, "decisions")["rows"]] == [f"i_bulk{i:03d}" for i in range(2, 52)]
    assert "확정한 판단 53건, 확정 기준 0건, 결정 52건" in sec(p, "scope")["rows"][1]["text"]
    assert "최신 50건만" in p["basis"]
    ok("9) 행 상한 50 — headed_note 는 앞 50개, 확정한 판단과 결정 절은 최신 50개(오름차순 유지), omitted.truncated 에 넘친 건수")


def test_markdown_escape(S):
    C = db.user_by_email(BULK)["id"]
    q = db.question_add(C, "구조 꼴 문장")["id"]
    rid = db.record_add(C, "꼴 메모", "인용할 원문 한 줄이다.", q)["id"]
    text = "# 소제목처럼\n> 인용처럼\n---\n- 목록처럼\n  # 들여쓴 소제목\n보통 줄 - 가운데 대시"
    added, _ = db.candidates_propose(C, rid, q, [{"text": text, "quote": "인용할 원문 한 줄이다."}], "ai")
    db.candidate_decide(C, added[0], "confirm")
    r = get(C, "headed_note", {"kind": "question", "id": q})
    assert r["sections"][0]["rows"][0]["text"] == text, "sections 의 text 는 그대로"
    md = r["markdown"]
    for ln in ("\\# 소제목처럼", "\\> 인용처럼", "\\---", "\\- 목록처럼", "  \\# 들여쓴 소제목", "보통 줄 - 가운데 대시", "> 인용할 원문 한 줄이다."):
        assert ln in md.splitlines(), (ln, md)
    assert md.splitlines()[0] == "## 구조 꼴 문장" and sum(1 for x in md.splitlines() if x.startswith("#")) == 1
    assert sum(1 for x in md.splitlines() if x == "---") == 1, "가로줄은 끝줄 앞 하나뿐"
    ok("9-1) markdown 구조 보호 — #, >, ---, - 로 시작하는 판단 줄은 백슬래시로 글자 그대로(text 값·인용은 그대로)")


def test_arg_invalid(S):
    A = S["A"]
    expect("ARG-INVALID", get, A, "headed_note", {"kind": "period", "period": "30d"})
    expect("ARG-INVALID", get, A, "period_report", {"kind": "question"})
    expect("ARG-INVALID", get, A, "period_report", {"kind": "period", "period": "14d"})
    expect("ARG-INVALID", get, A, "period_report", {"kind": "period"})
    expect("ARG-INVALID", get, A, "nope", {"kind": "question"})
    expect("ARG-INVALID", get, A, "headed_note", "question")
    expect("ARG-INVALID", get, A, "headed_note", {"kind": "question", "id": "q_nope000000"})
    expect("ARG-INVALID", get, A, "headed_note", {"kind": "question", "other": 1})
    expect("ARG-INVALID", get, A, "headed_note", {"kind": "question", "id": 3})
    ok("10) 양식과 scope 종류 불일치·모르는 기간·모르는 키·없는 질문 = ARG-INVALID")


def test_period(S):
    A = S["A"]
    by = {p: get(A, "period_report", {"kind": "period", "period": p}) for p in ("7d", "30d", "90d", "all")}
    claims = {p: set(refs({"sections": [sec(r, "claims")] if sec(r, "claims") else []})) for p, r in by.items()}
    recent = {S["c_conf"], S["c_multi"], S["c_loose"]}
    assert claims["7d"] == recent and claims["30d"] == recent, claims
    assert claims["90d"] == recent | {S["c_40"]}, claims["90d"]
    assert claims["all"] == recent | {S["c_40"], S["c_200"]}, claims["all"]
    dec = {p: [r["ref"]["id"] for r in (sec(x, "decisions") or {"rows": []})["rows"]] for p, x in by.items()}
    assert dec["7d"] == [S["d3"]] and dec["30d"] == [S["d10"], S["d3"]] and dec["all"] == [S["d100"], S["d10"], S["d3"]], dec
    assert sec(by["all"], "decisions")["rows"][0]["date"] == days_ago(100)
    for p in ("7d", "all"):   # 기준은 기간으로 거르지 않는다
        assert set(refs({"sections": [sec(by[p], "principles")]})) == {S["p1"], S["p2"]}
    assert by["30d"]["scope"] == {"kind": "period", "period": "30d", "from": days_ago(29), "to": TODAY.isoformat()}
    assert by["all"]["scope"]["from"] is None
    assert sec(by["30d"], "scope")["rows"][0]["text"] == f"기간: 최근 30일, {days_ago(29)}부터 {TODAY.isoformat()}까지(KST)"
    ok("11) 기간: 기간 밖에서 확정한 판단 빠짐(40일·이력 없는 200일) · 결정 = happened_on 오름차순(없음·꼴 틀림 빠짐) · 기준은 거르지 않음")


def test_check():
    p = subprocess.run([sys.executable, str(HERE / "export_forms.py"), "--check"], capture_output=True, text=True)
    assert p.returncode == 0 and "동결 파일과 같아요" in p.stdout, (p.returncode, p.stdout, p.stderr)
    bad = copy.deepcopy(ef.spec())
    bad["forms"][1]["sections"][2]["row_keys"] = ["text", "ref"]
    try:
        ef.validate(bad)
        raise AssertionError("row_keys 가 틀린 명세가 통과")
    except ValueError:
        pass
    assert ef.frozen_doc() != bad
    import activity
    assert ef.PERIODS == tuple(activity.PERIODS), "양식 기간 = activity 기간 함수의 기간"
    ok("12) python server/export_forms.py --check 가 동결 파일을 통과시킨다 · 틀린 명세는 검증이 거절")


async def test_catalog(S):
    cat = facade.load_catalog()
    spec = cat["ops"]["export_get"]
    assert (spec["tier"], spec["family"], spec.get("direct")) == ("read", "state", False)
    assert chat_mcp._PINNED_TIERS["export_get"] == "read"
    allowed = chat_mcp.allowed_operations(cat)   # 고정 목록 ≠ 카탈로그면 ChatMcpDenied
    assert ("read", "export_get") in allowed
    o = facade.OPS["export_get"]
    assert (o.tier, o.family, o.direct, o.bind) == ("read", "state", False, None)
    for ex in o.examples:
        facade.validate(o, ex)
    assert "export_get" in main.INSTRUCTIONS and "headed_note 의 markdown 은 고치지 않고" in main.INSTRUCTIONS
    assert o.tool.parameters["properties"]["form"]["enum"] == list(ef.form_keys())
    async with Client(main.mcp) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert "export_get" not in tools, "facade 전용 — 직접 도구로 등록하지 않는다"
        res = await c.call_tool("read", {"op": "export_get", "params": {"form": "headed_note", "scope": {"kind": "question"}}})
        assert not res.is_error, res.content[0].text[:300]
        v = res.structured_content
        v = v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v
        if v is None:
            assert len(res.content) == 1, res.content
            v = json.loads(res.content[0].text)
        mine = get(S["A"], "headed_note", {"kind": "question"})
        assert v["sections"] == mine["sections"] and v["omitted"] == mine["omitted"]
        bad = await c.call_tool("read", {"op": "export_get", "params": {"form": "headed_note", "scope": {"kind": "period", "period": "7d"}}})
        assert bad.is_error and CODE.search(bad.content[0].text).group(1) == "ARG-INVALID", bad.content[0].text
        wrong = await c.call_tool("write", {"op": "export_get", "params": {"form": "headed_note", "scope": {"kind": "question"}}})
        assert wrong.is_error and CODE.search(wrong.content[0].text).group(1) == "TIER-MISMATCH"
    ok("13) 카탈로그: export_get tier read(facade 전용) = chat_mcp 고정 목록 · read 겉면 호출 = 조립 결과 · ARG-INVALID·TIER-MISMATCH")


async def run():
    db.init_schema()   # CI 는 빈 전용 DB — 스키마부터
    cleanup()
    try:
        S = setup()
        test_shape_and_determinism(S)
        test_confirmed_only(S)
        test_empty_sections(S)
        test_trash_archive_deleted(S)
        test_tenant(S)
        test_quote_verbatim(S)
        test_refs(S)
        test_no_alias_location(S)
        test_truncation(S)
        test_markdown_escape(S)
        test_arg_invalid(S)
        test_period(S)
        test_check()
        await test_catalog(S)
    finally:
        cleanup()
        db.close()
    print("OK — 꺼내기 양식 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
