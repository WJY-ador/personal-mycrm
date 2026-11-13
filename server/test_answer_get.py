"""질문에 내 기록으로 답하기 시험 (2026-11-12, facade 전용 읽기 op answer_get).

실행: DATABASE_URL=postgresql://localhost/crm_test_answer python3 server/test_answer_get.py
가드: server/.env 를 읽지 않는다(운영 DB 폴백 사고 방지) — DATABASE_URL 을 명시해야 하고, 호스트는 로컬, DB 이름은 crm_test 로 시작해야 한다.

1) 결정성 2) 다른 사용자 섞임 없음 3) 휴지통·지운 글 없음 4) quote = 원 본문[start:end] 5) 비적격(AI 요약) 빠짐, ineligible_excluded 건수
6) 세션 정리 꼴 기록 draft 에 들어감 7) 수집 글은 related_posts 만(ai_*·본문 없음) 8) 항목(기준) 없음 9) question_id 확정 후보 맨 앞·남의 질문 NOT-FOUND
10) 검색어 만들기 11) gaps 코드별 1건 이상 12) markdown 줄머리 이스케이프 13) ARG-INVALID 14) 카탈로그 tier read = chat_mcp 고정 목록
"""
import asyncio
import datetime as _dt
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", "")
if not URL:
    raise SystemExit("중단: DATABASE_URL 을 명시하세요(예: postgresql://localhost/crm_test_answer). server/.env 는 읽지 않아요.")
_u = urllib.parse.urlsplit(URL)
if _u.hostname not in ("localhost", "127.0.0.1", "::1", None) or not _u.path.lstrip("/").startswith("crm_test"):
    raise SystemExit("중단: 로컬 시험 DB(이름 crm_test*)만 허용해요.")
os.environ["CRM_DEV"] = "1"
os.environ["CRM_DEV_USER"] = "ans-main@example.com"
os.environ["AUTHKIT_ISSUER"] = "https://fake.authkit.test"
os.environ["CRM_PUBLIC_URL"] = "http://127.0.0.1:8800"
os.environ["CRM_SESSION_SECRET"] = "answer-test-secret-1"
os.environ["CRM_TRASH_ENABLED"] = "1"
sys.path.insert(0, str(HERE))

from mcp.client import Client  # noqa: E402

import answer  # noqa: E402
import chat_mcp  # noqa: E402
import db  # noqa: E402
import facade  # noqa: E402
import imports  # noqa: E402
import main  # noqa: E402

MAIN, OTHER = "ans-main@example.com", "ans-other@example.com"
EMAILS = (MAIN, OTHER)
CODE = re.compile(r"\[([A-Z][A-Z0-9-]+)\]")
NOW = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
TODAY = NOW.astimezone(answer.KST).date()
Q_MAIN = "알파도구 베타검증은 무엇부터 하나"
# 응답에 나오면 안 되는 표식
AI_MARK, TRASH_MARK, DEL_MARK, ITEM_MARK, OTHER_MARK = "AI요약표식ZQX", "휴지통표식ZQX", "지운글표식ZQX", "항목표식ZQX", "남의자료ZQX"
AISUM_MARK, POSTBODY_MARK, LOC_MARK = "수집AI요약ZQX", "수집본문ZQX", "https://secret.example/loc-ZQX"


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


def days_ago(n):
    return TODAY - _dt.timedelta(days=n)


def rec(uid, title, body, date=None, **kw):
    rid = db.record_add(uid, title, body, **kw)["id"]
    if date is not None:
        sql("UPDATE records SET source_date=%s WHERE user_id=%s AND id=%s", (date, uid, rid))
    return rid


def cands(uid, rid, qid, quotes):
    added, dropped = db.candidates_propose(uid, rid, qid or "", [{"text": f"판단 — {q[:8]}", "quote": q} for q in quotes], "ai")
    assert not dropped and len(added) == len(quotes), (added, dropped)
    return added


def std_obj(uid, key):
    with db.tx() as c:
        r = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND std_id=%s", (uid, f"std:{key}")).fetchone()
    assert r, f"표준 오브젝트 없음: {key}"
    return r


COL_FIELDS = [   # 수집 글 오브젝트(test_tools COL_FIELDS 의 부분)
    {"key": "channel", "label": "채널", "value_type": "select", "required": True, "options": list(imports.COLLECTED_CHANNELS)},
    {"key": "author_display", "label": "작성자 표시", "value_type": "text"},
    {"key": "post_url", "label": "원 URL", "value_type": "text"},
    {"key": "collected_on", "label": "수집일", "value_type": "date", "required": True},
    {"key": "ai_grade", "label": "AI 등급", "value_type": "select", "options": list(imports.COLLECTED_GRADES)},
    {"key": "ai_summary", "label": "AI 요약", "value_type": "text"}]


def collected(uid, title, collected_on, url):
    with db.tx() as c:
        o = c.execute("SELECT id, revision FROM object_defs WHERE user_id=%s AND key=%s", (uid, imports.COLLECTED_OBJECT_KEY)).fetchone()
    if not o:
        p = db.definition_propose(uid, None, 0, {"key": imports.COLLECTED_OBJECT_KEY, "label": "수집 글", "semantic_kind": "collection",
                                                 "fields": COL_FIELDS})
        db.definition_apply(uid, p["object_id"], p["proposal_id"], 0)
        o = {"id": p["object_id"], "revision": 1}
    p = db.item_propose(uid, o["id"], o["revision"], None, 0, None, title, POSTBODY_MARK,
                        {"channel": "linkedin", "author_display": "합성 작성자", "post_url": url, "collected_on": collected_on,
                         "ai_grade": "signal", "ai_summary": AISUM_MARK}, [])
    return db.item_decide(uid, p["item_id"], 0, p["proposal_id"], "apply")["id"]


# ── 준비 ───────────────────────────────────────────────

def setup():
    A = db.user_by_email(MAIN)["id"]
    B = db.user_by_email(OTHER)["id"]
    db.display_name_set(A, "답하기 시험")
    q1 = db.question_add(A, Q_MAIN)["id"]
    S = {"A": A, "B": B, "q1": q1}

    # 주 재료 — 오늘 날짜. r_main 은 맞는 문장 3개(초안은 2개까지), 미확정 후보 1
    body_main = "알파도구 도입 전에 베타검증을 먼저 했다. 관련 없는 문장이다.\n알파도구는 베타검증 두 번째 문장이다.  세 번째 알파도구 베타검증 문장이다."
    S["r_main"] = rec(A, "도입 메모", body_main, source_ref={"kind": "url", "name": "회의 노트", "location": LOC_MARK})
    (S["c_pend"],) = cands(A, S["r_main"], "", ["관련 없는 문장이다."])
    # 확정 후보가 있는 기록 — 10일 전(점수 같으면 날짜보다 먼저)
    S["r_conf"] = rec(A, "확정 근거 메모", "알파도구 베타검증 확정 근거 문장이다.", date=days_ago(10))
    (S["c_conf"],) = cands(A, S["r_conf"], q1, ["알파도구 베타검증 확정 근거 문장이다."])
    db.candidate_decide(A, S["c_conf"], "confirm")
    # 질문에 묶인 확정 후보지만 검색어와 무관(question_id 면 점수 무관하게 맨 앞)
    S["r_pin"] = rec(A, "질문 답 메모", "점수와 무관한 확정 문장이다.\n둘째 줄\n셋째 줄 메모", date=days_ago(3))
    S["c_pin"], S["c_pin_pend"] = cands(A, S["r_pin"], q1, ["점수와 무관한 확정 문장이다.\n둘째 줄", "셋째 줄 메모"])
    db.candidate_decide(A, S["c_pin"], "confirm")
    # 세션 정리 꼴 — self, structured, mixed, decision_owner self, 출처 「세션 정리」
    S["r_wrap"] = rec(A, "세션 정리 기록", "결정: 알파도구 베타검증은 팀 합의로 정했다.", source=imports.SESSION_WRAP_SOURCE,
                      author_kind="self", text_process="structured", decision_owner="self")
    sql("UPDATE records SET generation_kind='mixed' WHERE user_id=%s AND id=%s", (A, S["r_wrap"]))
    # 비적격 — AI 요약(author unknown, generated, ai)
    S["r_ai"] = rec(A, "AI 요약", f"알파도구 베타검증 요약 {AI_MARK}.", author_kind="unknown", text_process="generated")
    sql("UPDATE records SET generation_kind='ai' WHERE user_id=%s AND id=%s", (A, S["r_ai"]))
    # 휴지통 글, 지운 글
    S["r_trash"] = rec(A, "휴지통 글", f"알파도구 베타검증 {TRASH_MARK}.")
    db.trash_move(A, "record", S["r_trash"])
    S["r_del"] = rec(A, "지운 글", f"알파도구 베타검증 {DEL_MARK}.")
    sql("UPDATE records SET deleted_at=now() WHERE user_id=%s AND id=%s", (A, S["r_del"]))
    # 읽고 든 생각
    src = db.source_create(A, "url", "읽은 글", LOC_MARK)["id"]
    S["refl"] = db.source_reflection_save(A, src, "reaction", "알파도구 베타검증은 우리 팀에도 맞겠다.", "", None)["id"]
    src2 = db.source_create(A, "url", "요약한 글", "https://example.com/sum")["id"]
    S["refl_sum"] = db.source_reflection_save(A, src2, "summary", "알파도구 베타검증 순서를 내 말로 요약해 둔다.", "", None)["id"]
    # 항목(기준) — 어디에도 없어야 한다
    o = std_obj(A, "principles")
    p = db.item_propose(A, o["id"], o["revision"], None, 0, None, f"알파도구 베타검증 기준 {ITEM_MARK}", f"알파도구 베타검증 {ITEM_MARK}", {}, [])
    S["item"] = db.item_decide(A, p["item_id"], 0, p["proposal_id"], "apply")["id"]
    # 수집 글 — 제목 줄이 맞는 것(related_posts), 맞지 않는 것
    S["post"] = collected(A, "알파도구 베타검증 수집 글 제목", days_ago(1).isoformat(), "https://www.linkedin.com/posts/synthetic-1")
    S["post_x"] = collected(A, "상관없는 수집 글", days_ago(1).isoformat(), "https://www.linkedin.com/posts/synthetic-2")
    S["post_only"] = collected(A, "수집전용표식 이타표식 제목", days_ago(2).isoformat(), "https://www.linkedin.com/posts/synthetic-3")
    # 옛 기록 한 편 — 문장 둘(one_record, thin, stale)
    S["r_old"] = rec(A, "옛 메모", "엡실론표식 제타표식 첫 문장. 엡실론표식 제타표식 둘째 문장.", date=days_ago(400))
    # markdown 이스케이프 — 구조 꼴로 시작하는 원문과 제목
    S["r_esc1"] = rec(A, "# 제목꼴 제목", "# 감마표식 델타표식 제목꼴\n> 감마표식 델타표식 인용꼴")
    S["r_esc2"] = rec(A, "목록꼴 메모", "--- 감마표식 델타표식 가로줄꼴\n- 감마표식 델타표식 목록꼴")
    # bare CR 줄 끝(\r, \r\n)
    S["r_cr"] = rec(A, "CR 메모", "카파표식 람다표식 첫줄\r카파표식 람다표식 둘째줄\r\n카파표식 람다표식 셋째줄")
    # stale = 초안과 근거 전체 — 점수 3인 옛 기록 4편이 초안 8개를 채우고, 점수 2인 새 기록은 근거에만
    S["r_hi"] = [rec(A, f"옛 고득점 {i}", "에타표식 테타표식 요타표식 문장 하나. 에타표식 테타표식 요타표식 문장 둘.", date=days_ago(400))
                 for i in range(4)]
    S["r_new"] = rec(A, "새 저득점", "에타표식 테타표식 새 문장.")

    # 다른 사용자 — 같은 검색어의 자료(섞이면 안 된다)
    qb = db.question_add(B, f"{OTHER_MARK} 질문")["id"]
    rb = rec(B, f"{OTHER_MARK} 글", f"알파도구 베타검증 {OTHER_MARK} 원문이다.")
    (cb,) = cands(B, rb, qb, [f"알파도구 베타검증 {OTHER_MARK} 원문이다."])
    db.candidate_decide(B, cb, "confirm")
    srcb = db.source_create(B, "url", "남의 출처", "https://example.com/b")["id"]
    db.source_reflection_save(B, srcb, "reaction", f"알파도구 베타검증 {OTHER_MARK} 생각.", "", None)
    S["qb"] = qb
    return S


def get(uid, **kw):
    return answer.assemble(uid, now=kw.pop("now", NOW), **kw)


def dump(res):
    return json.dumps(res, ensure_ascii=False)


def draft_ids(res):
    return [d["ref"]["id"] for d in res["draft"]]


def codes(res):
    return [g["code"] for g in res["gaps"]]


# ── 시험 ───────────────────────────────────────────────

def test_shape_and_determinism(S):
    a = answer.assemble(S["A"], question=Q_MAIN)
    b = answer.assemble(S["A"], question=Q_MAIN)
    assert list(a) == ["kind", "question", "terms", "draft", "evidence", "related_posts", "gaps", "markdown", "notice", "assembled_at"], list(a)
    a.pop("assembled_at")
    b.pop("assembled_at")
    assert a == b
    assert a["kind"] == "answer_material" and a["question"] == {"text": Q_MAIN, "id": None} and a["notice"] == answer.NOTICE
    assert a["terms"] == ["알파도구", "베타검증"], a["terms"]
    # 정렬: 점수 같으면 확정 후보 있는 기록(10일 전)이 오늘 기록보다 먼저 · 한 기록에서 초안 2개까지
    ids = draft_ids(a)
    assert ids[0] == S["r_conf"], ids
    assert ids.count(S["r_main"]) == 2 and set(ids) == {S["r_conf"], S["r_main"], S["r_wrap"], S["refl"], S["refl_sum"]}, ids
    assert [d["n"] for d in a["draft"]] == list(range(1, len(ids) + 1))
    assert all(set(d) == {"n", "quote", "ref"} for d in a["draft"])
    ev = {e["ref"]["id"]: e for e in a["evidence"]}
    assert len(ev[S["r_main"]]["quotes"]) == 3 and all(q["score"] == 2 for q in ev[S["r_main"]]["quotes"])
    assert ev[S["refl"]]["ref"]["kind"] == "reflection" and ev[S["refl"]]["title"] == "읽은 글"
    assert ev[S["refl"]]["provenance"] == {"text_process": None, "generation_kind": None, "decision_owner": None}
    assert ev[S["r_main"]]["date"] == TODAY.isoformat() and ev[S["r_conf"]]["date"] == days_ago(10).isoformat()
    assert ev[S["r_main"]]["provenance"]["text_process"] == "verbatim" and ev[S["r_main"]]["source"] is None
    assert LOC_MARK not in dump(a), "출처 위치는 싣지 않는다"
    ok("1) 같은 입력 두 번 = assembled_at 빼고 같다 · 모양 · 정렬(확정 후보 기록 먼저) · 한 기록 초안 2개 · 근거 편당 인용 3개")


def test_tenant(S):
    a = get(S["A"], question=Q_MAIN)
    assert OTHER_MARK not in dump(a)
    b = get(S["B"], question=Q_MAIN)
    assert all(OTHER_MARK in d["quote"] for d in b["draft"]) and b["draft"], b["draft"]
    assert not ({e["ref"]["id"] for e in b["evidence"]} & {e["ref"]["id"] for e in a["evidence"]})
    ok("2) 다른 사용자 기록, 생각이 섞이지 않는다")


def test_trash_deleted(S):
    s = dump(get(S["A"], question=Q_MAIN))
    assert TRASH_MARK not in s and DEL_MARK not in s and S["r_trash"] not in s and S["r_del"] not in s
    ok("3) 휴지통, 지운 기록이 나오지 않는다")


def _body(uid, kind, rid):
    with db.tx() as c:
        if kind == "record":
            return c.execute("SELECT body FROM records WHERE user_id=%s AND id=%s", (uid, rid)).fetchone()["body"]
        return c.execute("SELECT body FROM source_reflections WHERE user_id=%s AND id=%s", (uid, rid)).fetchone()["body"]


def test_quote_verbatim(S):
    n = 0
    for kw in ({"question": Q_MAIN}, {"question_id": S["q1"]}, {"question": "감마표식 델타표식"}, {"question": "엡실론표식 제타표식"},
               {"question": "카파표식 람다표식"}):
        res = get(S["A"], **kw)
        spans = set()
        for e in res["evidence"]:
            body = _body(S["A"], e["ref"]["kind"], e["ref"]["id"])
            for q in e["quotes"]:
                assert body[q["start"]:q["end"]] == q["text"], (q, body)
                spans.add((e["ref"]["id"], q["text"]))
                n += 1
        for d in res["draft"]:
            if d["ref"]["kind"] == "candidate":
                with db.tx() as c:
                    r = c.execute("SELECT c.quote, c.quote_start, c.quote_end, r.body FROM candidates c JOIN records r ON r.user_id=c.user_id "
                                  "AND r.id=c.record_id WHERE c.user_id=%s AND c.id=%s", (S["A"], d["ref"]["id"])).fetchone()
                assert d["quote"] == r["quote"] == r["body"][r["quote_start"]:r["quote_end"]]
            else:
                assert (d["ref"]["id"], d["quote"]) in spans, d   # 초안 문장 = 근거 인용 중 하나
                assert d["quote"] in _body(S["A"], d["ref"]["kind"], d["ref"]["id"])
            n += 1
    assert n > 10
    ok(f"4) 초안, 근거 인용 {n}개 = 원 본문[start:end] 글자 그대로(후보는 candidates 구간)")


def test_ineligible(S):
    a = get(S["A"], question=Q_MAIN)
    assert AI_MARK not in dump(a) and S["r_ai"] not in dump(a)
    g = next(x for x in a["gaps"] if x["code"] == "ineligible_excluded")
    assert g["count"] == 1 and g["text"] == "맞는 글 1편은 내 원문이 아니라서 넣지 않았어요.", g
    ok("5) 비적격 기록(AI 요약)은 초안, 근거에 없고 ineligible_excluded 건수로만")


def test_session_wrap(S):
    a = get(S["A"], question=Q_MAIN)
    assert S["r_wrap"] in draft_ids(a)
    e = next(e for e in a["evidence"] if e["ref"]["id"] == S["r_wrap"])
    assert e["source"] == "세션 정리" and e["provenance"] == {"text_process": "structured", "generation_kind": "mixed", "decision_owner": "self"}
    md = a["markdown"].split("\n")
    assert f"- ({S['r_wrap']}) 세션 정리 기록, {TODAY.isoformat()}, 세션 정리" in md, md
    assert f"- ({S['refl']}) 읽은 글, {TODAY.isoformat()}, 읽고 든 생각" in md, md   # reaction
    assert f"- ({S['refl_sum']}) 요약한 글, {TODAY.isoformat()}, 읽고 쓴 요약" in md, md   # summary
    assert f"- ({S['r_main']}) 도입 메모, {TODAY.isoformat()}, verbatim" in md, md
    ok("6) 세션 정리 꼴 기록(structured, mixed, decision_owner self)은 초안에 들어간다 · 근거 줄 꼴(ref id, 제목, 날짜, 셋째 칸)")


def test_collected(S):
    a = get(S["A"], question=Q_MAIN)
    s = dump(a)
    assert a["related_posts"] == [{"id": S["post"], "title": "알파도구 베타검증 수집 글 제목", "post_url": "https://www.linkedin.com/posts/synthetic-1",
                                   "author_display": "합성 작성자", "collected_on": days_ago(1).isoformat()}], a["related_posts"]
    assert AISUM_MARK not in s and POSTBODY_MARK not in s and "ai_" not in s and "signal" not in s
    assert S["post"] not in {d["ref"]["id"] for d in a["draft"]} | {e["ref"]["id"] for e in a["evidence"]}
    assert S["post_x"] not in s
    assert answer.COLLECTED_KEY == imports.COLLECTED_OBJECT_KEY
    ok("7) 수집 글은 초안, 근거에 없고 related_posts 에 제목 줄과 메타만(ai_*, 본문 없음)")


def test_items(S):
    s = dump(get(S["A"], question=Q_MAIN))
    assert ITEM_MARK not in s and S["item"] not in s
    ok("8) 항목(기준)은 어디에도 없다")


def test_question_id(S):
    a = get(S["A"], question_id=S["q1"])
    assert a["question"] == {"text": Q_MAIN, "id": S["q1"]}
    assert [d["ref"] for d in a["draft"][:2]] == [{"kind": "candidate", "id": S["c_conf"], "revision": 2},
                                                  {"kind": "candidate", "id": S["c_pin"], "revision": 2}], a["draft"][:2]
    # 고정한 후보 quote 와 같은 문장은 거듭 싣지 않는다
    assert S["r_conf"] not in draft_ids(a)
    assert a["draft"][1]["quote"] == "점수와 무관한 확정 문장이다.\n둘째 줄"
    assert f"> 점수와 무관한 확정 문장이다.\n> 둘째 줄 ({S['c_pin']})" in a["markdown"]
    # 맨 앞에 둔 확정 후보의 기록은 점수와 무관하게 근거에(그 quote 가 인용, 같은 구간은 한 번)
    ev = {e["ref"]["id"]: e for e in a["evidence"]}
    assert [e["ref"]["id"] for e in a["evidence"][:2]] == [S["r_conf"], S["r_pin"]], a["evidence"][:2]
    assert [q["text"] for q in ev[S["r_pin"]]["quotes"]] == ["점수와 무관한 확정 문장이다.\n둘째 줄"] and ev[S["r_pin"]]["quotes"][0]["score"] == 0
    assert [q["text"] for q in ev[S["r_conf"]]["quotes"]] == ["알파도구 베타검증 확정 근거 문장이다."]
    assert f"- ({S['r_pin']}) 질문 답 메모, {days_ago(3).isoformat()}, verbatim" in a["markdown"].split("\n")
    pend = next(g for g in a["gaps"] if g["code"] == "pending_candidates")
    assert pend["count"] == 2, pend   # r_main 1 + r_pin 1(근거에 들어와 집계에도)
    by_text = get(S["A"], question=Q_MAIN)
    assert draft_ids(a)[2:] == [i for i in draft_ids(by_text) if i != S["r_conf"]]
    e = expect("NOT-FOUND", answer.assemble, S["A"], question_id=S["qb"])
    assert OTHER_MARK not in e.message
    expect("NOT-FOUND", answer.assemble, S["A"], question_id="q_nope")
    ok("9) question_id: 묶인 확정 후보 quote 가 맨 앞(점수 무관, 같은 문장 거듭 없음) · 남의 질문, 없는 질문 NOT-FOUND")


def test_terms():
    assert answer.question_terms("새 도구를 팀에 들일 때 무엇부터 확인해야 하나") == ["도구", "팀에", "들일", "확인해야"]
    assert answer.question_terms("검증으로 Salesforce를 고른 이유가 왜 있나") == ["검증", "Salesforce", "고른", "이유"]
    assert answer.merge_terms(["도입", "도구", "SALESFORCE"], ["도구", "Salesforce", "팀에"]) == ["도입", "도구", "SALESFORCE", "팀에"]
    assert answer.merge_terms([f"t{i:02d}" for i in range(12)], ["도구"]) == [f"t{i:02d}" for i in range(12)]
    # 다른 검색어를 품은 긴 검색어는 뺀다('팀'과 '팀에' → '팀')
    assert answer.merge_terms(["팀"], answer.question_terms("새 도구를 팀에 들일 때 무엇부터 확인해야 하나")) == ["팀", "도구", "들일", "확인해야"]
    assert answer.merge_terms(["Tool"], ["toolkit", "도구"]) == ["Tool", "도구"]
    # 검색어가 없으면 아무것도 남기지 않는다
    res = answer.assemble(db.user_by_email(MAIN)["id"], question="무엇 어떻게 왜", now=NOW)
    assert res["terms"] == [] and res["draft"] == [] and codes(res)[0] == "no_match"
    ok("10) 검색어 만들기: 조사 하나 제거(남는 길이 2자 이상만) · 불용어 · 호출자 검색어 먼저, 대소문자 무시 중복 제거, 품은 긴 검색어 뺌, 12개 · 검색어 없음 = no_match")


def test_gaps(S):
    seen = set()
    a = get(S["A"], question=Q_MAIN)
    assert codes(a) == ["pending_candidates", "ineligible_excluded"], codes(a)
    g = a["gaps"][0]
    assert g["count"] == 1 and g["text"] == "이 근거 기록에 아직 확정하지 않은 후보가 1개 있어요."
    seen |= set(codes(a))
    old = get(S["A"], question="엡실론표식 제타표식")
    assert draft_ids(old) == [S["r_old"]] * 2
    assert codes(old) == ["thin", "one_record", "stale"], codes(old)
    assert old["gaps"][0]["text"] == "근거가 2개뿐이에요." and old["gaps"][2]["text"] == f"가장 새 근거가 {days_ago(400).isoformat()}예요. 지금도 같은지 확인하세요."
    seen |= set(codes(old))
    hi = get(S["A"], question="에타표식 테타표식 요타표식")
    assert len(hi["draft"]) == 8 and set(draft_ids(hi)) == set(S["r_hi"]), draft_ids(hi)
    assert S["r_new"] in {e["ref"]["id"] for e in hi["evidence"]} and "stale" not in codes(hi), codes(hi)   # 초안은 400일 전뿐, 근거에 오늘 기록
    po = get(S["A"], question="수집전용표식 이타표식")
    assert codes(po) == ["no_match", "posts_without_thought"] and [p["id"] for p in po["related_posts"]] == [S["post_only"]], po
    assert po["gaps"][0]["text"] == answer.GAP_TEXT["no_match"]
    seen |= set(codes(po))
    saved = answer.SCAN_LIMIT
    answer.SCAN_LIMIT = 3
    try:
        t = get(S["A"], question=Q_MAIN)
        assert codes(t)[-1] == "truncated" and t["gaps"][-1]["text"] == "기록이 많아 최근 2,000편까지만 봤어요.", codes(t)
        seen.add("truncated")
    finally:
        answer.SCAN_LIMIT = saved
    assert seen == {c for c, _ in answer.GAPS}, seen ^ {c for c, _ in answer.GAPS}
    for res in (a, old, po):
        assert "### 부족한 곳" in res["markdown"] and all(f"- {g['text']}" in res["markdown"] for g in res["gaps"])
    ok("11) gaps 코드 8개 모두 한 번 이상(표 순서, 고정 문구, {n}·{date} 만 채움)")


def test_markdown_escape(S):
    res = get(S["A"], question="감마표식 델타표식")
    md = res["markdown"].split("\n")
    i1, i2 = S["r_esc1"], S["r_esc2"]
    for line in (f"> \\# 감마표식 델타표식 제목꼴 ({i1})", f"> \\> 감마표식 델타표식 인용꼴 ({i1})",
                 f"> \\--- 감마표식 델타표식 가로줄꼴 ({i2})", f"> \\- 감마표식 델타표식 목록꼴 ({i2})"):
        assert line in md, (line, md)
    assert f"- ({i1}) # 제목꼴 제목, {TODAY.isoformat()}, verbatim" in md, md   # 근거 줄 = "- (ref id) 제목, 날짜, 셋째 칸"
    assert md[0] == "## 감마표식 델타표식" and "### 답변 초안" in md and "### 근거" in md
    assert {d["quote"] for d in res["draft"]} >= {"# 감마표식 델타표식 제목꼴", "- 감마표식 델타표식 목록꼴"}   # 값은 그대로
    # 줄 머리 꼴 각 1건(정렬 목록, 글머리 *, +, 코드 울타리 ```, ~~~, HTML <, 링크 정의 [, setext = -, 들여쓴 코드 4칸, 탭)
    for raw, want in (("1. 하나", "1\\. 하나"), ("12) 둘", "12\\) 둘"), ("* 별", "\\* 별"), ("+ 더하기", "\\+ 더하기"),
                      ("```py", "\\```py"), ("~~~", "\\~~~"), ("<div>태그", "\\<div>태그"), ("[x]: https://e.x", "\\[x]: https://e.x"),
                      ("===", "\\==="), ("--", "\\--"), ("    코드", "&#32;   코드"), ("\t코드", "&#32;코드"), ("  # 두 칸", "  \\# 두 칸"),
                      ("보통 줄", "보통 줄")):
        assert answer._md_escape(raw) == want, (raw, answer._md_escape(raw))
    # bare CR 도 줄 끝
    assert answer._md_lines("앞\r# 뒤\r\n> 끝") == ["앞", "\\# 뒤", "\\> 끝"]
    cr = get(S["A"], question="카파표식 람다표식")
    assert [q["text"] for e in cr["evidence"] for q in e["quotes"]] == ["카파표식 람다표식 첫줄", "카파표식 람다표식 둘째줄", "카파표식 람다표식 셋째줄"]
    assert "\r" not in cr["markdown"]
    # 질문 소제목: 줄 머리와 끝의 '#'
    assert get(S["A"], question="C# 도입 #")["markdown"].split("\n")[0] == "## C# 도입 \\#"
    assert get(S["A"], question="# 감마표식 델타표식")["markdown"].split("\n")[0] == "## \\# 감마표식 델타표식"
    ok("12) markdown 줄머리 이스케이프(#, >, ---, -, 정렬 목록, *, +, 코드 울타리, <, [, setext, 들여쓰기) · bare CR · 질문 소제목 끝 # · 근거 줄 맨 앞 ref id")


def test_arg_invalid(S):
    A = S["A"]
    for kw in ({}, {"question": "   "}, {"question": Q_MAIN, "question_id": S["q1"]}, {"question": "가" * 301},
               {"question": Q_MAIN, "terms": [f"t{i}" for i in range(13)]}, {"question": "줄\n바꿈"}, {"question": "탭\t문자"},
               {"question": Q_MAIN, "terms": ["좋은", "제어\x07"]}, {"question": Q_MAIN, "terms": ["  "]},
               {"question": Q_MAIN, "terms": ["가" * 31]}, {"question": Q_MAIN, "terms": "도구"}, {"question_id": "q\x00x"},
               {"question": 5}, {"question": 0}, {"question_id": []}, {"question": Q_MAIN, "terms": ("도입",)}, {"question": Q_MAIN, "terms": [1]},
               {"question": "알파\u202e도구"}, {"question": Q_MAIN, "terms": ["도\u200b구"]}):
        expect("ARG-INVALID", answer.assemble, A, **kw)
    assert get(A, question="가" * 300)["question"]["text"] == "가" * 300
    assert get(A, question=f"  {Q_MAIN}  ", terms=[" 도입 "])["terms"] == ["도입", "알파도구", "베타검증"]
    assert get(A, question=None, question_id=S["q1"])["question"]["id"] == S["q1"]
    ok("13) ARG-INVALID: 둘 다 없음, 둘 다 있음, 301자, terms 13개, 제어 문자, 서식 문자(Cf), 빈 검색어, 31자 검색어, 문자열 아닌 형식 · 앞뒤 공백 자름")


async def test_catalog(S):
    cat = facade.load_catalog()
    spec = cat["ops"]["answer_get"]
    assert (spec["tier"], spec["family"], spec.get("direct")) == ("read", "question", False)
    assert chat_mcp._PINNED_TIERS["answer_get"] == "read"
    allowed = chat_mcp.allowed_operations(cat)   # 고정 목록 ≠ 카탈로그면 ChatMcpDenied
    assert ("read", "answer_get") in allowed
    o = facade.OPS["answer_get"]
    assert (o.tier, o.family, o.direct, o.bind) == ("read", "question", False, None)
    for ex in o.examples:
        facade.validate(o, ex)
    assert "answer_get 을 부른다. markdown 은 고치지 않고 그대로 보여 준다. 초안 사이에 문장을 더하거나 요약하지 않는다." in main.INSTRUCTIONS
    assert "읽고 든 생각은 내 글이라 근거에 들어간다. 검토 완료 표시는 판단 확정이 아니다." in main.INSTRUCTIONS
    async with Client(main.mcp) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        assert "answer_get" not in tools, "facade 전용 — 직접 도구로 등록하지 않는다"
        res = await c.call_tool("read", {"op": "answer_get", "params": {"question": Q_MAIN}})
        assert not res.is_error, res.content[0].text[:300]
        v = res.structured_content
        v = v.get("result", v) if isinstance(v, dict) and set(v) == {"result"} else v
        if v is None:
            assert len(res.content) == 1, res.content
            v = json.loads(res.content[0].text)
        mine = answer.assemble(S["A"], question=Q_MAIN)
        v.pop("assembled_at")
        mine.pop("assembled_at")
        assert v == mine
        bad = await c.call_tool("read", {"op": "answer_get", "params": {}})
        assert bad.is_error and CODE.search(bad.content[0].text).group(1) == "ARG-INVALID", bad.content[0].text
        nf = await c.call_tool("read", {"op": "answer_get", "params": {"question_id": S["qb"]}})
        assert nf.is_error and CODE.search(nf.content[0].text).group(1) == "NOT-FOUND", nf.content[0].text
        wrong = await c.call_tool("write", {"op": "answer_get", "params": {"question": Q_MAIN}})
        assert wrong.is_error and CODE.search(wrong.content[0].text).group(1) == "TIER-MISMATCH"
    ok("14) 카탈로그: answer_get tier read, family question, facade 전용 = chat_mcp 고정 목록 · read 겉면 호출 = 조립 결과 · ARG-INVALID·NOT-FOUND·TIER-MISMATCH")


async def run():
    db.init_schema()   # CI 는 빈 전용 DB — 스키마부터
    cleanup()
    try:
        S = setup()
        test_shape_and_determinism(S)
        test_tenant(S)
        test_trash_deleted(S)
        test_quote_verbatim(S)
        test_ineligible(S)
        test_session_wrap(S)
        test_collected(S)
        test_items(S)
        test_question_id(S)
        test_terms()
        test_gaps(S)
        test_markdown_escape(S)
        test_arg_invalid(S)
        await test_catalog(S)
    finally:
        cleanup()
        db.close()
    print("OK — 답하기 시험 전부 통과")


if __name__ == "__main__":
    asyncio.run(run())
