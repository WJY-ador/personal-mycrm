"""자동 분류 판정 시험(2026-11-18 구조추천 명세 6.1) — route.evaluate, check_route, *_like 변환. DB 를 쓰지 않는다.

실행: python3 server/test_route.py
시험 자료는 가짜 문장이다(꼴만 명세 6.0 과 같다: `P1. 제목`, `**어디서** — …`, `### 상황 (문제)`, `### CE-2026-01-02-1. 제목`, `- 내 선택: …`).

1. *_like → 정규식(# 숫자, 맨 끝 *, 나머지 글자 그대로), 정규식 꼴 거절
2. 세 꼴 exact(라벨 6줄 1기록 1항목, 절 머리 1기록 1항목, ### CE 분할 1기록 n항목)
3. partial(require 일부, 필수 필드 빔, 제목 없음, 너무 긺), 불일치(출처, 제목 꼴, require 하나도 없음) = 빈 목록
4. 불변식 — exact 단위의 text 값 == body[span], text_list 조각은 그 구간 안, 서버가 만든 문장 없음
5. 정의 검증 거절(모르는 키, 모르는 from, 없는 필드, 타입 안 맞음, 정규식, principle, 수집 글)
6. 접은 줄(문장 중간 줄바꿈)과 \\r\\n, unit_key 중복 #2
7. 명세 6.14 — from unit_body(heading, record 단위), match.skip_body_like(heading 단위만), heading_like "*"
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import route  # noqa: E402


def ok(msg):
    print(f"  ok  {msg}")


def F(key, vt="text", required=False):
    return {"key": key, "label": key, "value_type": vt, "required": required}


def F_(key, vt="text", required=False):
    return {"key": key, "label": key, "value_type": vt, "required": required}


def rejects(route_json, fields, frag="", **kw):
    try:
        route.check_route(route_json, fields, **kw)
    except route.RouteInvalid as e:
        assert frag in str(e), (frag, str(e))
        return
    raise AssertionError(f"거절 기대: {route_json}")


def invariant(rec, units):
    """exact 단위의 text 값 == 원문 구간, text_list 조각은 구간 안. 모든 단위 구간은 본문 안."""
    body = rec["body"]
    for u in units:
        assert 0 <= u["start"] <= u["end"] <= len(body)
        if u["state"] != "exact":
            continue
        for fk, (s, e) in u["spans"].items():
            v = u["data"][fk]
            if isinstance(v, list):
                for piece in v:
                    assert piece in body[s:e], (fk, piece)
            else:
                assert v == body[s:e], (fk, v, body[s:e])
            assert u["start"] <= s <= e <= u["end"], (fk, s, e)


# ── 가짜 자료 ──────────────────────────────────────────

PIVOT_LABELS = ["어디서", "전에 가던 방향", "내가 설명한 것", "결정", "바뀐 것", "맞았나"]
PIVOT_BODY = (
    "**어디서** — 가짜 팀의 주간 회의\n"
    "**전에 가던 방향** — 도구부터 고르기\n"
    "**내가 설명한 것**\n"
    "> 사람이 먼저 정해져야 도구가 의미가 있다고\n"
    "> 말했다.\n"
    "이어서 담당을 나누자고 했다.\n"
    "**결정** — 입력 담당부터 정한다\n"
    "**바뀐 것** - 회의 순서\n"
    "**맞았나**: 다음 주에 본다\n")
PIVOT_FIELDS = [F("happened_on", "date", True), F("where", required=True), F("prior_direction"), F("my_words"),
                F("decision", required=True), F("turned"), F("was_right")]
PIVOT_ROUTE = {"v": 1, "unit": "record", "match": {"source": "세션 정리", "title_like": "P#. *"},
               "require": {"labels": PIVOT_LABELS}, "title": {"from": "title"},
               "fields": {"happened_on": {"from": "record_date"}, "where": {"from": "label", "label": "어디서"},
                          "prior_direction": {"from": "label", "label": "전에 가던 방향"},
                          "my_words": {"from": "label", "label": "내가 설명한 것"}, "decision": {"from": "label", "label": "결정"},
                          "turned": {"from": "label", "label": "바뀐 것"}, "was_right": {"from": "label", "label": "맞았나"}}}

STORY_BODY = (
    "# 가짜 세션\n"
    "### 상황 (문제)\n"
    "가짜 고객의 입력 화면이 느렸다.\n"
    "\n"
    "### 내 판단\n"
    "캐시보다 쿼리를 먼저 본다.\n"
    "### 팀과의 과정\n"
    "둘이서 로그를 나눠 읽었다.\n"
    "### 결과 (성과)\n"
    "응답이 빨라졌다.\n")
STORY_FIELDS = [F("story_date", "date"), F("situation", required=True), F("my_judgment", required=True), F("team_process"), F("result")]
STORY_ROUTE = {"v": 1, "unit": "record", "match": {"source": "세션 정리"}, "require": {"headings": ["상황", "내 판단"]},
               "fields": {"story_date": {"from": "record_date"}, "situation": {"from": "section", "heading": "상황"},
                          "my_judgment": {"from": "section", "heading": "내 판단"},
                          "team_process": {"from": "section", "heading": "팀과의 과정"}, "result": {"from": "section", "heading": "결과"}}}

CE_BODY = (
    "## 오늘 한 일\n"
    "가짜 이관을 했다.\n"
    "## 경력 증거 후보\n"
    "### CE-2026-01-02-1. 가짜 이관 검증\n"
    "- 관련성: 높음\n"
    "- 내 선택: 표본 검증, 전수 비교 ,\n"
    "- 열린 질문: 다음엔 무엇을 먼저 볼까\n"
    "### CE-2026-01-02-2. 두 번째 가짜 증거\n"
    "- 내 선택: 기다림\n"
    "## 다음 절\n"
    "끝.\n")
CE_FIELDS = [F("happened_on", "date"), F("relevance"), F("my_choice", "text_list"), F("open_question")]
CE_ROUTE = {"v": 1, "unit": "heading", "match": {"source": "세션 정리", "heading_like": "CE-#-#-#-#. *"},
            "title": {"from": "heading"},
            "fields": {"happened_on": {"from": "record_date"}, "relevance": {"from": "key", "key": "관련성"},
                       "my_choice": {"from": "key", "key": "내 선택"}, "open_question": {"from": "key", "key": "열린 질문"}}}


def rec(title, body, source="세션 정리", date="2026-01-02"):
    return {"id": "r_fake", "title": title, "body": body, "source": source, "date": date}


def norm(r, fields):
    return route.check_route(r, fields)


# ── 1 ──

def test_like():
    def m(like, text):
        return route.like_match(route.like_check(like, "t"), text)
    assert m("P#. *", "P1. 가짜") and m("P#. *", "P123. ") and not m("P#. *", "P. 가짜") and not m("P#. *", "xP1. 가짜")
    assert m("CE-#-#-#-#. *", "CE-2026-01-02-1. 가짜 제목") and not m("CE-#-#-#-#. *", "CE-2026-01-02. 가짜")
    assert m("경력 증거 후보", "경력 증거 후보") and not m("경력 증거 후보", "경력 증거 후보 2")   # * 없음 = 끝까지 같아야 한다
    assert m("상황 (문제)", "상황 (문제)") and not m("상황 (문제)", "상황 문제")             # 괄호, 마침표는 글자 그대로
    assert m("a.b", "a.b") and not m("a.b", "axb") and m("회의 #*", "회의 12 둘째") and not m("회의 #", "회의 12 ")
    assert m("v#", "v12") and not m("v#", "v12a") and m("1#x", "112x") and m("*", "아무거나") and m("a*", "a")
    for bad in (r"^P\d+\. ", "P[0-9]", "P.*", "a|b", "P#*. x", "", "x" * 81, "a\nb", "end$", "(?i)p", "##", "#" * 14, "P#1", "a#2b"):
        try:
            route.like_check(bad, "t")
        except route.RouteInvalid:
            continue
        raise AssertionError(f"like 거절 기대: {bad!r}")
    ok("*_like 매처(# = 숫자, 맨 끝 *, 글자 그대로), 정규식 꼴, 가운데 *, 빈 값, 80자 넘음, 줄바꿈, ## 연속, # 뒤 숫자 거절")


def test_like_linear():
    """검토 지적 1 — 지수 시간 역추적이 없다. 통과하는 가장 나쁜 꼴(# 과 글자 번갈아 80자)에 숫자 1000자 입력이 0.05초 안."""
    import time
    worst = route.like_check("#a" * 40, "t")
    for text in ("1" * 1000, "1" * 999 + "a", ("1" * 25 + "a") * 40, ("1" * 25 + "a") * 39 + "1" * 25):
        t = time.perf_counter()
        route.like_match(worst, text)
        assert time.perf_counter() - t < 0.05, text[:20]
    r = route.check_route({"v": 1, "unit": "heading", "match": {"heading_like": "#a" * 40}}, [])
    t = time.perf_counter()
    route.evaluate({"id": "r", "title": "t", "body": ("## " + "1" * 1000 + "\n") * 20, "source": "s", "date": None}, r, [])
    assert time.perf_counter() - t < 0.5
    try:
        route.check_route({"v": 1, "unit": "record", "match": {"title_like": "#" * 14}}, [])
    except route.RouteInvalid:
        pass
    else:
        raise AssertionError("# 연속 거절 기대")
    ok("매처는 입력 길이에 선형 — 최악 꼴 80자 x 숫자 1000자 0.05초 안, # 14연속은 거절")


# ── 2 ──

def test_exact_three_shapes():
    r = rec("P3. 입력 순서를 바꾼 날", PIVOT_BODY)
    us = route.evaluate(r, norm(PIVOT_ROUTE, PIVOT_FIELDS), PIVOT_FIELDS)
    assert len(us) == 1 and us[0]["state"] == "exact" and us[0]["unit_key"] == "", us
    d = us[0]["data"]
    assert d["happened_on"] == "2026-01-02" and d["where"] == "가짜 팀의 주간 회의" and d["prior_direction"] == "도구부터 고르기"
    assert d["my_words"] == "> 사람이 먼저 정해져야 도구가 의미가 있다고\n> 말했다.\n이어서 담당을 나누자고 했다.", d["my_words"]
    assert d["decision"] == "입력 담당부터 정한다" and d["turned"] == "회의 순서" and d["was_right"] == "다음 주에 본다"
    assert us[0]["title"] == "P3. 입력 순서를 바꾼 날" and (us[0]["start"], us[0]["end"]) == (0, len(PIVOT_BODY))
    assert "happened_on" not in us[0]["spans"]
    invariant(r, us)

    r = rec("가짜 세션 정리", STORY_BODY)
    us = route.evaluate(r, norm(STORY_ROUTE, STORY_FIELDS), STORY_FIELDS)
    assert len(us) == 1 and us[0]["state"] == "exact", us
    d = us[0]["data"]
    assert d == {"story_date": "2026-01-02", "situation": "가짜 고객의 입력 화면이 느렸다.", "my_judgment": "캐시보다 쿼리를 먼저 본다.",
                 "team_process": "둘이서 로그를 나눠 읽었다.", "result": "응답이 빨라졌다."}, d
    invariant(r, us)

    r = rec("가짜 세션 정리 2", CE_BODY)
    us = route.evaluate(r, norm(CE_ROUTE, CE_FIELDS), CE_FIELDS)
    assert [u["unit_key"] for u in us] == ["CE-2026-01-02-1. 가짜 이관 검증", "CE-2026-01-02-2. 두 번째 가짜 증거"], us
    assert all(u["state"] == "exact" for u in us)
    a, b = us
    assert a["title"] == "CE-2026-01-02-1. 가짜 이관 검증" and a["data"]["relevance"] == "높음"
    assert a["data"]["my_choice"] == ["표본 검증", "전수 비교"] and a["data"]["open_question"] == "다음엔 무엇을 먼저 볼까"
    assert b["data"] == {"happened_on": "2026-01-02", "my_choice": ["기다림"]}, b["data"]
    # 단위 구간 = 머리 줄부터 같은 수준 이하 다음 머리 줄 앞까지(## 다음 절 앞에서 끝난다)
    assert CE_BODY[a["start"]:a["end"]].startswith("### CE-2026-01-02-1.") and CE_BODY[a["end"]:].startswith("### CE-2026-01-02-2.")
    assert CE_BODY[b["end"]:].startswith("## 다음 절")
    assert "title" not in a["spans"] and CE_BODY[slice(*a["spans"]["relevance"])] == "높음"
    invariant(r, us)
    ok("세 꼴 exact — 라벨 6줄 1기록 1항목, 절 머리 1기록 1항목, ### CE 분할 1기록 n항목(구간, 제목, text_list)")


# ── 3 ──

def test_partial_and_mismatch():
    nr = norm(PIVOT_ROUTE, PIVOT_FIELDS)
    body = PIVOT_BODY.replace("**맞았나**: 다음 주에 본다\n", "")
    us = route.evaluate(rec("P4. 가짜", body), nr, PIVOT_FIELDS)
    assert len(us) == 1 and us[0]["state"] == "partial" and us[0]["reason"] == "require", us
    body = "그냥 메모.\n"   # require 하나도 없음 = record 단위는 단위 없음
    assert route.evaluate(rec("P5. 가짜", body), nr, PIVOT_FIELDS) == []
    assert route.evaluate(rec("P3. 가짜", PIVOT_BODY, source="대화에서 입력"), nr, PIVOT_FIELDS) == []   # 출처 다름
    assert route.evaluate(rec("가짜 제목", PIVOT_BODY), nr, PIVOT_FIELDS) == []                        # 제목 꼴 다름
    # 필수 필드가 빔(라벨은 있으나 값이 비었다)
    body = PIVOT_BODY.replace("**결정** — 입력 담당부터 정한다\n", "**결정** —\n")
    us = route.evaluate(rec("P6. 가짜", body), nr, PIVOT_FIELDS)
    assert us[0]["state"] == "partial" and us[0]["reason"] == "required_field" and "decision" not in us[0]["data"], us
    # 규칙 없는 필수 필드 = 늘 빔 → partial
    fields = PIVOT_FIELDS + [F("extra", required=True)]
    us = route.evaluate(rec("P3. 가짜", PIVOT_BODY), norm(PIVOT_ROUTE, fields), fields)
    assert us[0]["reason"] == "required_field"
    # 제목 없음 → title
    r2 = dict(STORY_ROUTE, match={"source": "세션 정리"})
    us = route.evaluate(rec("", STORY_BODY), norm(r2, STORY_FIELDS), STORY_FIELDS)
    assert us[0]["state"] == "partial" and us[0]["reason"] == "title", us
    # 너무 긺 → too_long
    big = "### 상황 (문제)\n" + ("가" * 12000) + "\n### 내 판단\n" + ("나" * 12000) + "\n"
    us = route.evaluate(rec("가짜", big), norm(STORY_ROUTE, STORY_FIELDS), STORY_FIELDS)
    assert us[0]["state"] == "partial" and us[0]["reason"] == "too_long", us[0]["reason"]
    # heading 단위 require 하나도 없음 = partial(단위 없음이 아니다)
    ce = dict(CE_ROUTE, require={"keys": ["관련성"]})
    us = route.evaluate(rec("가짜", CE_BODY), norm(ce, CE_FIELDS), CE_FIELDS)
    assert [(u["state"], u["reason"]) for u in us] == [("exact", None), ("partial", "require")], us
    # heading_like 에 안 맞는 머리 = 단위 없음
    assert route.evaluate(rec("가짜", STORY_BODY), norm(CE_ROUTE, CE_FIELDS), CE_FIELDS) == []
    ok("partial(require 일부, required_field, title, too_long, heading 단위 require 0), 불일치(출처, 제목 꼴, require 0) = 빈 목록")


# ── 4 ──

def test_invariant_no_server_text():
    for r, rt, fs in ((rec("P3. 가짜", PIVOT_BODY), PIVOT_ROUTE, PIVOT_FIELDS), (rec("가짜", STORY_BODY), STORY_ROUTE, STORY_FIELDS),
                      (rec("가짜", CE_BODY), CE_ROUTE, CE_FIELDS)):
        us = route.evaluate(r, norm(rt, fs), fs)
        invariant(r, us)
        for u in us:   # 값은 원문 조각, 제목 줄, 날짜뿐
            for fk, v in u["data"].items():
                for piece in (v if isinstance(v, list) else [v]):
                    assert piece in r["body"] or piece in (r["title"], r["date"]), (fk, piece)
    ok("불변식 — exact text 값 == body[span], text_list 조각 ⊂ 구간, 서버가 만든 문장 없음")


# ── 5 ──

def test_check_rejects():
    fs = PIVOT_FIELDS
    rejects({**PIVOT_ROUTE, "regex": "x"}, fs, "모르는 키")
    rejects({**PIVOT_ROUTE, "unit": "line"}, fs, "unit")
    rejects({**PIVOT_ROUTE, "match": {"source": "세션 정리", "title_regex": "P"}}, fs, "모르는 키")
    rejects({**PIVOT_ROUTE, "match": {"title_like": r"^P\d+"}}, fs, "정규식")
    rejects({**PIVOT_ROUTE, "match": {"heading_like": "CE-#. *"}}, fs, "heading")
    rejects({**CE_ROUTE, "match": {"source": "세션 정리"}}, CE_FIELDS, "heading_like")
    rejects({**PIVOT_ROUTE, "fields": {"nope": {"from": "title"}}}, fs, "없는 필드")
    rejects({**PIVOT_ROUTE, "fields": {"where": {"from": "regex"}}}, fs, "from")
    rejects({**PIVOT_ROUTE, "fields": {"where": {"from": "label"}}}, fs, "비었")
    rejects({**PIVOT_ROUTE, "fields": {"where": {"from": "label", "label": "어디서", "x": 1}}}, fs, "모르는 키")
    rejects({**PIVOT_ROUTE, "fields": {"where": {"from": "record_date"}}}, fs, "text")
    rejects({**PIVOT_ROUTE, "fields": {"happened_on": {"from": "title"}}}, fs, "date")
    rejects({**PIVOT_ROUTE, "fields": {"where": {"from": "heading"}}}, fs, "heading")
    for vt in ("select", "number", "boolean", "reference"):
        rejects({**PIVOT_ROUTE, "fields": {"k": {"from": "title"}}}, [F("k", vt)], vt)
    rejects({**PIVOT_ROUTE, "fields": {"k": {"from": "label", "label": "어디서"}}}, [F("k", "text_list")], "text_list")
    rejects({"v": 1, "unit": "record"}, fs, "모든 기록")
    rejects({**PIVOT_ROUTE, "title": {"from": "heading"}}, fs, "title.from")
    rejects({**PIVOT_ROUTE, "require": {"labels": "어디서"}}, fs, "목록")
    rejects({**PIVOT_ROUTE, "v": 2}, fs, "v")
    rejects(PIVOT_ROUTE, fs, "principle", semantic_kind="principle")
    rejects(PIVOT_ROUTE, fs, "수집 글", object_key="collected_posts")
    n = route.check_route({**PIVOT_ROUTE, "match": {"source": "세션 정리", "title_like": "  P#. *  "}}, fs)
    assert n["match"]["title_like"] == "P#. *" and n["title"] == {"from": "title"} and n["require"]["keys"] == []
    assert route.check_route({k: v for k, v in CE_ROUTE.items() if k != "title"}, CE_FIELDS)["title"] == {"from": "heading"}
    json.dumps(n, ensure_ascii=False)
    ok("정의 검증 거절(모르는 키, from, 없는 필드, 타입, 정규식, heading 규칙, 조건 없음, principle, 수집 글), 정규화 꼴")


# ── 6 ──

def test_folded_crlf_dup():
    folded = PIVOT_BODY.replace("**어디서** — 가짜 팀의 주간 회의\n",
                                "**어디서** — 가짜 팀의 주간 회의에서 이야기가 길어져 한 줄이 여든 칸을 넘어 접힌\n문장의 뒷부분\n")
    nr = norm(PIVOT_ROUTE, PIVOT_FIELDS)
    us = route.evaluate(rec("P3. 가짜", folded), nr, PIVOT_FIELDS)
    assert us[0]["state"] == "exact" and us[0]["data"]["where"].endswith("접힌\n문장의 뒷부분"), us[0]["data"]["where"]
    invariant(rec("P3. 가짜", folded), us)
    crlf = PIVOT_BODY.replace("\n", "\r\n")
    us = route.evaluate(rec("P3. 가짜", crlf), nr, PIVOT_FIELDS)
    assert us[0]["state"] == "exact" and us[0]["data"]["decision"] == "입력 담당부터 정한다", us[0]["data"]
    assert us[0]["data"]["my_words"] == "> 사람이 먼저 정해져야 도구가 의미가 있다고\r\n> 말했다.\r\n이어서 담당을 나누자고 했다."
    invariant(rec("P3. 가짜", crlf), us)
    s_crlf = STORY_BODY.replace("\n", "\r\n")
    us = route.evaluate(rec("가짜", s_crlf), norm(STORY_ROUTE, STORY_FIELDS), STORY_FIELDS)
    assert us[0]["state"] == "exact" and us[0]["data"]["situation"] == "가짜 고객의 입력 화면이 느렸다.", us[0]["data"]
    ce_crlf = CE_BODY.replace("\n", "\r\n")
    us = route.evaluate(rec("가짜", ce_crlf), norm(CE_ROUTE, CE_FIELDS), CE_FIELDS)
    assert us[0]["data"]["relevance"] == "높음" and us[0]["unit_key"] == "CE-2026-01-02-1. 가짜 이관 검증"
    invariant(rec("가짜", ce_crlf), us)
    listed = "".join("- " + ln + "\n" for ln in ("**어디서** — 가짜 회의", "**전에 가던 방향** — 가짜 방향", "**내가 설명한 것** — 가짜 설명",
                                                  "**결정** — 가짜 결정", "**바뀐 것** — 가짜 변화", "**맞았나** — 가짜 확인"))
    us = route.evaluate(rec("P3. 가짜", listed), nr, PIVOT_FIELDS)
    assert us[0]["state"] == "exact" and us[0]["data"]["where"] == "가짜 회의" and us[0]["data"]["was_right"] == "가짜 확인", us[0]["data"]
    invariant(rec("P3. 가짜", listed), us)
    dup = CE_BODY.replace("CE-2026-01-02-2. 두 번째 가짜 증거", "CE-2026-01-02-1. 가짜 이관 검증")
    us = route.evaluate(rec("가짜", dup), norm(CE_ROUTE, CE_FIELDS), CE_FIELDS)
    assert [(u["unit_key"], u["state"], u["reason"]) for u in us] == [
        ("CE-2026-01-02-1. 가짜 이관 검증", "exact", None), ("CE-2026-01-02-1. 가짜 이관 검증\n2", "partial", "duplicate_heading")]
    ok("접은 줄은 다음 라벨 줄까지 이어진 값, \\r\\n 본문도 같은 값(줄 끝 \\r 빠짐), 같은 머리 둘째 = partial(duplicate_heading)")


def test_review_fixes():
    """검토 지적 2, 5, 8, 10 — unit_key 유일, 겹친 머리, \\r 줄 끝, 키 판정 하나."""
    F = [F_("dec"), F_("who"), F_("h")]
    hd = norm({"v": 1, "unit": "heading", "match": {"heading_like": "회의 #*"},
               "fields": {"dec": {"from": "label", "label": "결정"}, "who": {"from": "key", "key": "담당"}}}, F)
    # 2: 글자 그대로 "회의 1 #2" 머리와 같은 머리 반복 — key 는 기록 안에서 유일, 둘째부터 partial
    body = "## 회의 1 #2\n**결정** A\n## 회의 1\n**결정** B\n## 회의 1\n**결정** C\n"
    us = route.evaluate(rec("t", body, source="s"), hd, F)
    keys = [u["unit_key"] for u in us]
    assert keys == ["회의 1 #2", "회의 1", "회의 1\n2"] and len(set(keys)) == 3, keys
    assert [u["state"] for u in us] == ["exact", "exact", "partial"] and us[1]["data"]["dec"] == "B"
    # 5: 겹친 머리 — 바깥 단위는 안쪽 단위(heading_like 에 맞는 더 깊은 머리) 앞에서 끝난다
    body = "## 회의 1\n### 회의 2\n**결정** child\n- 담당: 하위\n"
    a, b = route.evaluate(rec("t", body, source="s"), hd, F)
    assert body[a["start"]:a["end"]] == "## 회의 1\n" and "dec" not in a["data"] and "who" not in a["data"], a
    assert b["data"]["dec"].startswith("child") and b["data"]["who"] == "하위" and body[b["start"]:].startswith("### 회의 2"), b
    # 8: \r 만 쓴 본문 — 머리 글자에 다음 줄이 들어가지 않는다
    us = route.evaluate(rec("t", "## 회의 1\r**결정** a\r## 회의 2\r**결정** b", source="s"), hd, F)
    assert [u["unit_key"] for u in us] == ["회의 1", "회의 2"] and [u["data"]["dec"] for u in us] == ["a", "b"], us
    invariant(rec("t", "## 회의 1\r**결정** a\r## 회의 2\r**결정** b"), us)
    # 10: "- 키 :" 꼴 — require, 추출, profile 이 같은 정규식
    rk = norm({"v": 1, "unit": "record", "require": {"keys": ["담당"]}, "fields": {"who": {"from": "key", "key": "담당"}}}, F)
    u = route.evaluate(rec("t", "- 담당 : 가짜 사람\n"), rk, F)[0]
    assert u["state"] == "exact" and u["data"]["who"] == "가짜 사람"
    assert route._KEY_RE.match("- 담당 : 가짜 사람").group(1).strip() == "담당"
    ok("unit_key 유일(글자 그대로 #2, 같은 머리 둘째 partial), 겹친 머리 구간, \\r 줄 끝, 키 판정 정규식 하나")


COMM_FIELDS = [F("happened_on", "date", True), F("content", "text", True)]
COMM_ROUTE = {"v": 1, "unit": "heading",
              "match": {"source": "세션 정리", "title_like": "오늘의 소통과 결정", "heading_like": "*", "skip_body_like": "→ P#"},
              "title": {"from": "heading"}, "fields": {"happened_on": {"from": "record_date"}, "content": {"from": "unit_body"}}}
COMM_BODY = "### 첫 결정\n문장 하나.\n\n### 둘째\n→ P3\n\n### 셋째\n문장 둘.\n"


def test_unit_body_and_skip():
    """6.14 — unit_body 는 머리 다음 줄부터 단위 끝(앞뒤 공백 뺀 원문), skip_body_like 에 맞는 절은 단위가 아니다."""
    r = norm(COMM_ROUTE, COMM_FIELDS)
    assert r["match"]["skip_body_like"] == "→ P#" and r["fields"]["content"] == {"from": "unit_body"}
    assert route.check_route(r, COMM_FIELDS) == r, "정규화 꼴을 다시 넣어도 같다(sync 가 저장된 route 를 다시 검사한다)"
    rc = rec("오늘의 소통과 결정", COMM_BODY)
    us = route.evaluate(rc, r, COMM_FIELDS)
    assert [(u["unit_key"], u["state"], u["data"]["content"]) for u in us] == [("첫 결정", "exact", "문장 하나."), ("셋째", "exact", "문장 둘.")], us
    assert us[0]["data"]["happened_on"] == "2026-01-02" and us[0]["title"] == "첫 결정"
    assert COMM_BODY[us[0]["start"]:us[0]["end"]] == "### 첫 결정\n문장 하나.\n\n", "건너뛴 머리도 앞 단위의 구간 끝이다"
    invariant(rc, us)
    # 제목, 출처가 안 맞으면 단위 없음
    assert route.evaluate(rec("그 외 결정", COMM_BODY), r, COMM_FIELDS) == []
    # 머리 다음 빈 줄, 단위 끝 공백, 여러 줄 본문 — 앞뒤 공백만 빼고 가운데 빈 줄은 그대로
    body = "## 가짜 머리\n\n  첫 줄.\n\n둘째 줄.  \n\t\n## 다음\n끝.   "
    us = route.evaluate(rec("오늘의 소통과 결정", body), r, COMM_FIELDS)
    assert [u["data"]["content"] for u in us] == ["첫 줄.\n\n둘째 줄.", "끝."], us
    invariant(rec("오늘의 소통과 결정", body), us)
    # \r\n 본문 — 같은 단위, 줄 끝 \r 는 값 끝에 남지 않는다(가운데 \r\n 은 원문 그대로)
    crlf = COMM_BODY.replace("\n", "\r\n") + "### 넷째\r\n가짜 한 줄.\r\n가짜 둘째 줄.\r\n"
    us = route.evaluate(rec("오늘의 소통과 결정", crlf), r, COMM_FIELDS)
    assert [(u["unit_key"], u["data"]["content"]) for u in us] == [
        ("첫 결정", "문장 하나."), ("셋째", "문장 둘."), ("넷째", "가짜 한 줄.\r\n가짜 둘째 줄.")], us
    invariant(rec("오늘의 소통과 결정", crlf), us)
    # 본문 없는 머리(머리 줄이 마지막 줄, 머리 바로 뒤 다음 머리) — unit_body 빔 = 필수 필드 빔 partial(skip 꼴에 안 맞음)
    us = route.evaluate(rec("오늘의 소통과 결정", "### 빈 절\n### 찬 절\n가짜.\n### 끝 머리"), r, COMM_FIELDS)
    assert [(u["unit_key"], u["state"], u["reason"]) for u in us] == [
        ("빈 절", "partial", "required_field"), ("찬 절", "exact", None), ("끝 머리", "partial", "required_field")], us
    # skip 꼴: 공백 둘레는 맞고(앞뒤 공백 뺀 것으로 판정), 덧붙은 글이 있거나 숫자가 없으면 안 맞는다(그 절은 exact)
    for b, skipped in (("\n   → P12  \n\n", True), ("\r\n→ P7\r\n", True), ("\n→ P3 덧붙임\n", False), ("\n→ P3\n가짜 설명.\n", False),
                       ("\n→ P\n", False), ("\n가짜 → P3\n", False)):
        us = route.evaluate(rec("오늘의 소통과 결정", "### 가짜" + b), r, COMM_FIELDS)
        assert (us == []) is skipped and (skipped or us[0]["state"] == "exact"), (b, us)
    # 같은 머리 글자 둘, 첫째가 건너뜀 — 둘째는 중복이 아니다(exact, unit_key 에 순번 없음)
    us = route.evaluate(rec("오늘의 소통과 결정", "### 같은 머리\n→ P1\n### 같은 머리\n가짜 내용.\n"), r, COMM_FIELDS)
    assert [(u["unit_key"], u["state"]) for u in us] == [("같은 머리", "exact")], us
    # 건너뛰지 않은 같은 머리 둘 — 둘째는 여전히 duplicate_heading
    us = route.evaluate(rec("오늘의 소통과 결정", "### 같은 머리\n가짜 1.\n### 같은 머리\n→ P2\n### 같은 머리\n가짜 3.\n"), r, COMM_FIELDS)
    assert [(u["unit_key"], u["state"], u["reason"]) for u in us] == [("같은 머리", "exact", None), ("같은 머리\n2", "partial", "duplicate_heading")], us
    # skip_body_like 없으면 → P 절도 단위
    r2 = norm({**COMM_ROUTE, "match": {k: v for k, v in COMM_ROUTE["match"].items() if k != "skip_body_like"}}, COMM_FIELDS)
    us = route.evaluate(rec("오늘의 소통과 결정", COMM_BODY), r2, COMM_FIELDS)
    assert [(u["unit_key"], u["data"]["content"]) for u in us] == [("첫 결정", "문장 하나."), ("둘째", "→ P3"), ("셋째", "문장 둘.")], us
    # record 단위의 unit_body = 본문 전체(앞뒤 공백 뺌)
    fr = [F("content", "text", True)]
    rr = norm({"v": 1, "unit": "record", "match": {"title_like": "가짜 *"}, "fields": {"content": {"from": "unit_body"}}}, fr)
    rb = "\n\n  가짜 본문 첫 줄.\r\n## 가짜 머리\r\n둘째.\n \n"
    us = route.evaluate(rec("가짜 기록", rb), rr, fr)
    assert us[0]["state"] == "exact" and us[0]["data"]["content"] == "가짜 본문 첫 줄.\r\n## 가짜 머리\r\n둘째." and us[0]["unit_key"] == "", us
    invariant(rec("가짜 기록", rb), us)
    us = route.evaluate(rec("가짜 기록", " \n\t"), rr, fr)
    assert us[0]["state"] == "partial" and us[0]["reason"] == "required_field" and "content" not in us[0]["data"], us
    ok("unit_body(heading, record, 머리 다음 빈 줄, 끝 공백, \\r\\n, 빈 절), skip_body_like(맞으면 단위 없음, 안 맞으면 exact, 공백 둘레, 중복 수에서 뺌)")


def test_heading_star_and_rejects():
    """heading_like "*" = 모든 머리 줄(수준 2~4), 거절: record 단위의 skip_body_like, 날짜, 글자 목록 필드의 unit_body, 모르는 키."""
    assert route.like_check("*", "x") == "*" and route.like_check(" * ", "x") == "*" and route.like_tokens("*") == (("rest",),)
    assert all(route.like_match("*", t) for t in ("", "가", "P1. 가짜", "# 가짜 *"))
    fs = [F("content", "text", True)]
    r = norm({"v": 1, "unit": "heading", "match": {"heading_like": "*"}, "fields": {"content": {"from": "unit_body"}}}, fs)
    body = "앞 글.\n## 둘\n가짜 a.\n### 셋\n가짜 b.\n#### 넷\n가짜 c.\n##### 다섯은 머리 아님\n# 하나도 머리 아님\n"
    us = route.evaluate(rec("t", body), r, fs)
    assert [(u["unit_key"], u["data"]["content"]) for u in us] == [
        ("둘", "가짜 a."), ("셋", "가짜 b."), ("넷", "가짜 c.\n##### 다섯은 머리 아님\n# 하나도 머리 아님")], us
    invariant(rec("t", body), us)
    rec_r = {"v": 1, "unit": "record", "match": {"title_like": "가짜 *", "skip_body_like": "→ P#"}, "fields": {}}
    rejects(rec_r, fs, "skip_body_like")
    rejects({"v": 1, "unit": "heading", "match": {"heading_like": "*", "skip_body_like": "a.*"}}, fs, "정규식")
    rejects({"v": 1, "unit": "heading", "match": {"heading_like": "*", "skip_body_like": "  "}}, fs, "skip_body_like")
    rejects({"v": 1, "unit": "heading", "match": {"heading_like": "*"}, "fields": {"d": {"from": "unit_body"}}}, [F("d", "date")], "date")
    rejects({"v": 1, "unit": "heading", "match": {"heading_like": "*"}, "fields": {"t": {"from": "unit_body"}}}, [F("t", "text_list")], "text_list")
    rejects({"v": 1, "unit": "heading", "match": {"heading_like": "*"}, "fields": {"content": {"from": "unit_body", "heading": "x"}}}, fs, "모르는 키")
    ok("heading_like \"*\" = 수준 2~4 머리 줄 전부, 거절(record 단위 skip_body_like, 정규식, 빈 꼴, 날짜, 글자 목록, 덧붙은 키)")


def test_shape_and_limits():
    assert route.shape("P12. 가짜 제목") == "P#. *" and route.shape("CE-2026-01-02-1. 가짜") == "CE-#-#-#-#. *"
    assert route.shape("상황 (문제)") == "상황 (문제)" and route.shape("가짜 정리 2026-01-02") == "가짜 정리 #-#-#"
    import importlib.util
    if importlib.util.find_spec("psycopg"):
        import db
        assert (route.LIMIT_TEXT, route.LIMIT_JSON) == (db.LIMIT_TEXT, db.LIMIT_JSON)
    ok("꼴(숫자 #, 번호 앞 토큰 묶음), 크기 상한이 db 와 같다")


if __name__ == "__main__":
    for fn in (test_like, test_like_linear, test_exact_three_shapes, test_partial_and_mismatch, test_invariant_no_server_text,
               test_check_rejects, test_folded_crlf_dup, test_review_fixes, test_unit_body_and_skip, test_heading_star_and_rejects,
               test_shape_and_limits):
        fn()
    print("test_route: 전부 통과")
