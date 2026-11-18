"""질문에 내 기록으로 답하기 — facade 전용 읽기 op answer_get 의 본체(2026-11-12). 쓰지 않고 저장하지 않는다.

무엇: 질문 하나에 답변 초안(draft), 근거 원문(evidence), 부족한 곳(gaps) 셋을 낸다. 서버는 원문 구간과 메타만 낸다.
      연결 문장, 요약 문장을 만들지 않는다. 부족한 곳은 이 파일의 고정 문구다.
재료: 인용 적격 기록(db._ELIGIBLE_SQL 그대로)과 읽고 든 생각(source_reflections 본문)만. 항목(기준, 결정 등)은 작성자 표시가 없어 넣지 않는다.
      수집 글(object key collected_posts 의 항목)은 남의 글이라 근거가 아니다 — 제목 줄과 URL 만 related_posts 에 따로 둔다.
      ai_* 필드는 어디에도 싣지 않는다(related_posts 는 키를 하나씩 꺼낸다).
검색: 서버가 결정적으로 한다(확장 pg_trgm, FTS, 임베딩 없음). 호출자가 준 terms 는 찾는 열쇠일 뿐 답에 들어가지 않는다.
      같은 입력이면 assembled_at 을 뺀 응답이 같다.
점수(2026-11-18): 남기는 기준은 맞은 서로 다른 검색어 수 ≥ min(2, 검색어 수). 정렬은 맞은 검색어 가중치 합 — 가중치 = log(전체 문장 수 /
      (1 + 그 낱말 든 문장 수)), 0 아래면 0. 문장 수는 그 사용자의 훑는 범위 안 적격 기록에서 센다. 흔한 낱말만 맞은 문장이 아래로 간다.
인용 후보에서 빼는 줄: markdown 소제목 줄, 굵게만 있는 줄, 표 줄, 같은 글에서 목록 머리표만 다른 같은 문장(확정 후보 quote 는 빼지 않는다).
접힌 줄(2026-11-18): 약 80칸에서 접어 쓴 글은 줄 끝에서 문장이 끊기지 않게 앞 줄에 잇는다(_joins). 인용 text 는 원문 그대로라 줄바꿈이 남는다.
"""
import datetime as _dt
import math
import re
import unicodedata
from zoneinfo import ZoneInfo

import db
import export_forms

KST = ZoneInfo("Asia/Seoul")
SCAN_LIMIT = 2000                     # 훑는 범위: 적격 기록 최신 2,000편, 읽고 든 생각 최신 2,000건(시험은 작은 값으로 바꾼다)
DRAFT_MAX, DRAFT_PER_REF = 8, 2       # 답변 초안 최대 8개, 한 기록에서 최대 2개
EVIDENCE_MAX, QUOTES_MAX = 10, 3      # 근거 최대 10편(넘친 편수는 부족한 곳 more_evidence), 편당 인용 최대 3개
POSTS_MAX = 5                         # 관련 수집 글 최대 5개
QUESTION_MAX, TERMS_MAX, TERM_MAX = 300, 12, 30
STALE_DAYS = 180
COLLECTED_KEY = "collected_posts"     # imports.COLLECTED_OBJECT_KEY 와 같은 값(시험이 본다)

# 질문에서 검색어 만들기 — 끝 조사 하나(긴 것부터), 불용어
JOSA = ("으로", "에서", "에게", "까지", "부터", "이랑", "하고", "처럼", "보다",
        "은", "는", "이", "가", "을", "를", "에", "의", "도", "만", "로", "와", "과", "랑")
STOPWORDS = frozenset(("무엇", "어떻게", "어떤", "왜", "언제", "해야", "하나", "있나", "그래서", "같아", "뭔가"))
_TOKEN = re.compile(r"[0-9A-Za-z가-힣]+")
_LINE = re.compile(r"[^\r\n]+")         # 줄 끝 = \r\n, \r, \n
_LINE_SPLIT = re.compile(r"\r\n|\r|\n")
_CUT = re.compile(r"(?<=[.?!。])\s+")   # 문장 끝 부호 뒤 공백에서 나눈다
# 접힌 줄 잇기 — 앞 줄이 FOLD_MIN 자 이상이고 문장 끝 글자로 끝나지 않으면 다음 줄을 잇는다
FOLD_MIN = 40
_SENT_END = re.compile(r"(?:[.?!。][\"'”’)\]}」』》〉）]*|[:：])$")   # 문장 끝 부호(뒤 닫는 따옴표, 괄호 허용) 또는 쌍점
_FOLD_WS = re.compile(r"[ \t]*(?:\r\n|\r|\n)[ \t]*")   # 줄 끝을 품은 공백 묶음 — 비교용 사본에서 공백 하나로
FOLD_MAX = 400                          # 이은 결과로 줄 끝을 넘는 문장이 이 글자 수를 넘으면 그 덩어리는 잇지 않는다(한 줄 문장은 상한 없음)
_FENCE = re.compile(r"`{3,}|~{3,}")     # 코드 울타리 줄 머리(들여쓰기 뺀 뒤) — 울타리 줄과 울타리 안 줄은 잇지 않는다
_RULE_LINE = re.compile(r"[-=*_][-=*_ \t]{2,}")   # 가로줄, setext 밑줄 꼴 — 앞뒤 공백 뺀 줄이 - = * _ 와 공백만으로 3자 이상
_CTRL = ("Cc", "Cf", "Zl", "Zp")        # 거절할 범주: 제어 문자, 보이지 않는 서식 문자(U+202E, U+200B 등), 줄과 문단 구분
# 인용 후보에서 빼는 줄 — markdown 소제목(ATX), 굵게만 있는 줄(끝 쌍점 허용), 표 줄. 목록 머리표는 같은 문장 비교 때만 뗀다
_HEADING_LINE = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")
_BOLD_LINE = re.compile(r"(\*\*|__)(?:(?!\1).)+\1[:：]?")
_LIST_MARK = re.compile(r"(?:[-*+]|\d{1,9}[.)])[ \t]+")

# 보여 주기 규칙 — 응답 display_rule, INSTRUCTIONS, answer_get docstring, 카탈로그 rule 이 같은 문구(시험이 본다)
DISPLAY_RULE = ("markdown 을 처음부터 끝까지 그대로 보여 준다. 줄을 빼거나 묶거나 요약하지 않는다. markdown 앞뒤에 네 문장을 덧붙이지 않는다. "
                "부족한 점은 markdown 의 부족한 곳 절만 쓴다. 사용자가 따로 묻기 전에는 해석하지 않는다.")
NOTICE = "내 기록 원문만 모았어요. 문장을 새로 쓰지 않았어요. 글로 다듬으면 그건 내 판단이 아니에요."
# markdown 근거 줄 셋째 칸 — 읽고 든 생각(source_reflections)은 출처 표시도 text_process 도 없어 kind 로 고정 낱말을 쓴다
REFLECTION_LABELS = {"reaction": "읽고 든 생각", "summary": "읽고 쓴 요약"}

# 부족한 곳 — 표 순서 그대로 낸다. 문구 안의 {n}, {date} 만 값으로 채운다
GAPS = (
    ("no_match", "질문에 맞는 내 기록을 찾지 못했어요. 검색어를 바꾸거나 이 주제로 기록을 남겨 보세요."),
    ("thin", "근거가 {n}개뿐이에요."),
    ("one_record", "근거가 기록 한 편에서만 나왔어요."),
    ("pending_candidates", "이 근거 기록에 아직 확정하지 않은 후보가 {n}개 있어요."),
    ("ineligible_excluded", "맞는 글 {n}편은 내 원문이 아니라서 넣지 않았어요."),
    ("posts_without_thought", "관련 수집 글은 있지만 내 생각이 없어요. 읽고 든 생각을 남기면 근거가 돼요."),
    ("stale", "가장 새 근거가 {date}예요. 지금도 같은지 확인하세요."),
    ("more_evidence", "같은 질문으로 찾은 기록이 {n}편 더 있어요."),
    ("truncated", "기록이 많아 최근 2,000편까지만 봤어요."),
)
GAP_TEXT = dict(GAPS)


# ── 입력 ──────────────────────────────────────────────

def _bad(msg):
    return db.CrmError("ARG-INVALID", msg, "find(op=\"answer_get\") 로 인자 모양을 보세요.")


def _clean(v, what, max_len):
    """앞뒤 공백을 자르고 1~max_len 자, 제어 문자(줄바꿈 포함) 거절."""
    if not isinstance(v, str):
        raise _bad(f"{what}은 문자열이에요.")
    v = v.strip()
    if any(unicodedata.category(ch) in _CTRL for ch in v):
        raise _bad(f"{what}에 줄바꿈, 제어 문자, 보이지 않는 서식 문자는 넣을 수 없어요.")
    if not v:
        raise _bad(f"{what}이 비었어요.")
    if len(v) > max_len:
        raise _bad(f"{what}은 {max_len}자까지예요.")
    return v


def _args(question, question_id, terms):
    """question, question_id = 문자열 또는 None 만. terms = 문자열 목록 또는 None 만. 다른 형식은 ARG-INVALID."""
    for v, what in ((question, "question"), (question_id, "question_id")):
        if v is not None and not isinstance(v, str):
            raise _bad(f"{what}은 문자열이에요.")
    q, qid = (question or "").strip(), (question_id or "").strip()
    if bool(q) == bool(qid):
        raise _bad("question 과 question_id 중 하나만 주세요.")
    q = _clean(q, "question", QUESTION_MAX) if q else ""
    qid = _clean(qid, "question_id", db.LIMIT_TEXT) if qid else ""
    if terms is None:
        terms = []
    if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
        raise _bad("terms 는 문자열 목록이에요.")
    if len(terms) > TERMS_MAX:
        raise _bad(f"terms 는 {TERMS_MAX}개까지예요.")
    return q, qid, [_clean(t, "terms 의 검색어", TERM_MAX) for t in terms]


def question_terms(text):
    """질문 → 검색어. [0-9A-Za-z가-힣]+ 토큰 → 끝 조사 하나 제거(가장 긴 조사, 남는 길이 2자 이상일 때만) → 2자 미만, 불용어 제거."""
    out = []
    for t in _TOKEN.findall(text):
        j = next((j for j in JOSA if t.endswith(j)), None)
        if j and len(t) - len(j) >= 2:
            t = t[:-len(j)]
        if len(t) >= 2 and t not in STOPWORDS:
            out.append(t)
    return out


def merge_terms(given, from_question):
    """호출자 검색어 먼저, 질문에서 만든 검색어 뒤. 중복 제거(라틴 문자 대소문자 무시) → 다른 검색어를 부분 문자열로 품은 긴 검색어는 뺀다
    ('팀'과 '팀에' → '팀', 긴 쪽이 든 문장은 짧은 쪽도 들어 있어 한 문장이 점수 2를 거저 받는 것을 막는다) → 앞에서 12개."""
    out, seen = [], set()
    for t in [*given, *from_question]:
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    low = [t.lower() for t in out]
    return [t for t, lt in zip(out, low) if not any(o != lt and o in lt for o in low)][:TERMS_MAX]


# ── 문장, 점수 ──────────────────────────────────────────

def _skip_line(line):
    """인용 후보에서 빼는 줄인가 — markdown 소제목, 굵게만 있는 줄, 표 줄. 줄 하나를 통째로 판정한다('# 제목. 둘째 문장' 의 둘째 조각도 뺀다)."""
    s = line.strip()
    return bool(_HEADING_LINE.match(line) or _BOLD_LINE.fullmatch(s) or s.startswith("|"))


def _flat(text):
    """비교용 사본 — 줄 끝을 품은 공백 묶음만 공백 하나로. 한 줄 글은 그대로다(반환 text 에는 쓰지 않는다)."""
    return _FOLD_WS.sub(" ", text)


def _indent(line):
    """줄 머리 들여쓰기 칸 수(탭 = 4칸)."""
    return len(_INDENT.match(line).group().expandtabs(4))


def _joins(prev, nxt, list_item=False):
    """접힌 줄인가 — 다음 줄을 앞 줄에 이어 한 덩어리로 볼지. 조건을 전부 만족할 때만 잇는다: 앞 줄이 문장 끝 글자로 끝나지 않는다,
    앞 줄 길이(앞뒤 공백 뺀 글자 수) FOLD_MIN 이상, 다음 줄이 비지 않았다, 다음 줄(들여쓰기 뺀)이 목록 머리표, #, >, |, ** 로 시작하지 않는다,
    두 줄 다 _skip_line 이 아니다. 목록 항목의 들여쓴 이어지는 줄도 같은 조건으로 잇는다.
    두 줄 다 코드 울타리 줄(``` ~~~)과 가로줄, 밑줄 꼴(_RULE_LINE)이 아니다. 4칸 이상 들여쓴 줄은 list_item(덩어리 첫 줄이 목록 항목)일 때만 잇는다."""
    p, n = prev.strip(), nxt.lstrip()
    return bool(len(p) >= FOLD_MIN and not _SENT_END.search(p) and n.strip()
                and not _LIST_MARK.match(n) and not n.startswith(("#", ">", "|", "**"))
                and not _skip_line(prev) and not _skip_line(nxt)
                and not _FENCE.match(p) and not _FENCE.match(n)
                and not _RULE_LINE.fullmatch(p) and not _RULE_LINE.fullmatch(n.strip())
                and (list_item or (_indent(prev) < 4 and _indent(nxt) < 4)))


def _pieces(text):
    """덩어리 → (덩어리 안 시작 위치, 문장). . ? ! 。 뒤 공백에서 나누고 앞뒤 공백을 뺀다. 빈 조각은 내지 않는다."""
    pos = 0
    for a, b in [(c.start(), c.end()) for c in _CUT.finditer(text)] + [(len(text), len(text))]:
        seg = text[pos:a]
        s = seg.strip()
        if s:
            yield pos + (len(seg) - len(seg.lstrip())), s
        pos = b


def _blocks(body):
    """본문 → 문장을 나눌 덩어리 (start, end). 줄 끝 = \r\n, \r, \n. 접힌 줄(_joins)은 한 덩어리로 잇고, 빈 줄이 사이에 있으면 잇지 않는다.
    _skip_line 줄은 덩어리가 아니다. 코드 울타리(``` ~~~) 열림과 닫힘을 따라가 울타리 줄과 울타리 안 줄은 줄마다 따로 둔다.
    이은 덩어리 안에 줄 끝을 넘는 문장이 FOLD_MAX 자를 넘으면 그 덩어리는 잇지 않고 줄마다 나눈다."""
    lines = list(_LINE.finditer(body))
    i, fence = 0, None
    while i < len(lines):
        m = lines[i]
        head = m.group().lstrip()
        if fence is not None or _FENCE.match(head) or _skip_line(m.group()):
            if fence is None and _FENCE.match(head):   # 울타리 열림 — 같은 글자 3개로 시작하는 줄이 닫는다
                fence = head[:3]
            elif fence is not None and head.startswith(fence):
                fence = None
            if not _skip_line(m.group()):   # 울타리 줄, 울타리 안 줄 — 기존처럼 줄 하나가 덩어리
                yield m.start(), m.end()
            i += 1
            continue
        j, item = i, bool(_LIST_MARK.match(head))
        while j + 1 < len(lines) and _LINE_SPLIT.fullmatch(body, lines[j].end(), lines[j + 1].start()) \
                and _joins(lines[j].group(), lines[j + 1].group(), item):
            j += 1
        a, b = m.start(), lines[j].end()
        if j > i and any(len(t) > FOLD_MAX and _LINE_SPLIT.search(t) for _, t in _pieces(body[a:b])):
            yield from ((x.start(), x.end()) for x in lines[i:j + 1])   # 상한 넘침 — 잇지 않고 줄마다(다시 잇지도 않는다)
        else:
            yield a, b
        i = j + 1


def sentences(body):
    """본문 → (start, end, 문장). 줄 끝(\r\n, \r, \n), 또는 . ? ! 。 뒤 공백에서 나눈다. 문장 = 앞뒤 공백을 뺀 연속 구간(body[start:end] 와 같다).
    접힌 줄(_joins)은 줄 끝에서 나누지 않고 한 덩어리로 이은 뒤 그 안에서 . ? ! 。 뒤 공백(줄바꿈 포함)에서 나눈다 — 문장에 줄바꿈과 다음 줄 들여쓰기가 남는다.
    인용 후보에서 빼는 줄(_skip_line)은 건너뛰고, 같은 글 안에서 목록 머리표를 뗀 글자가 앞 문장과 같으면 뒤 문장은 건너뛴다(비교는 _flat 사본)."""
    seen = set()
    for base, end in _blocks(body):
        for off, s in _pieces(body[base:end]):
            norm = _flat(_LIST_MARK.sub("", s, count=1) if _LIST_MARK.match(s) else s)
            if norm not in seen:
                seen.add(norm)
                st = base + off
                yield st, st + len(s), s


def score(text, keys):
    """문장에 들어 있는 서로 다른 검색어 수(keys = 소문자 검색어). 접힌 줄바꿈은 공백으로 본다(_flat)."""
    low = _flat(text).lower()
    return sum(1 for k in keys if k in low)


def term_weights(bodies, keys):
    """검색어별 가중치 = log(전체 문장 수 / (1 + 그 낱말 든 문장 수)), 0 아래면 0, 소수 여섯째 자리 반올림. bodies = 적격 기록 본문.
    문장은 sentences() 그대로 센다(인용 후보와 같은 문장). 문장이 없으면 모두 0."""
    n, df = 0, dict.fromkeys(keys, 0)
    for body in bodies:
        for _, _, s in sentences(body):
            n += 1
            low = _flat(s).lower()
            for k in keys:
                if k in low:
                    df[k] += 1
    return {k: round(max(0.0, math.log(n / (1 + df[k]))), 6) if n else 0.0 for k in keys}


def weigh(text, keys, weights):
    """문장 → (맞은 서로 다른 검색어 수, 맞은 검색어 가중치 합). 합은 keys 순서로 더해 반올림한다(결정적). 접힌 줄바꿈은 공백으로 본다(_flat)."""
    low = _flat(text).lower()
    hit = [k for k in keys if k in low]
    return len(hit), round(sum(weights[k] for k in hit), 6)


# ── 조회 ──────────────────────────────────────────────

_REC_COLS = (f"r.id, r.title, r.body, r.source, r.revision, r.text_process, r.generation_kind, r.decision_owner, r.created, "
             f"{db.RECORD_SORT} AS d")
_REC_ORDER = "ORDER BY d DESC, r.created DESC, r.id DESC"


def _records(c, uid, pats, eligible):
    """최신 SCAN_LIMIT 편(정렬 = db.RECORD_SORT) 안에서 검색어 하나라도 든 기록. eligible=False = 지우지 않은 비적격 내 기록.
    pats=None 이면 거르지 않고 훑는 범위 전부(가중치의 문장 수를 세려고 적격 기록 본문 전체가 필요하다)."""
    cond = db._ELIGIBLE_SQL if eligible else \
        f"r.deleted_at IS NULL AND r.trashed_at IS NULL AND NOT COALESCE({db._ELIGIBLE_SQL}, false)"
    where = "" if pats is None else "WHERE x.body ILIKE ANY(%(pats)s)"
    return db._all(c, f"SELECT x.*, EXISTS (SELECT 1 FROM candidates k WHERE k.user_id=%(uid)s AND k.record_id=x.id "
                      f"AND k.decision='confirmed') AS confirmed "
                      f"FROM (SELECT {_REC_COLS} FROM records r WHERE r.user_id=%(uid)s AND {cond} {_REC_ORDER} LIMIT %(lim)s) x "
                      f"{where}", {"uid": uid, "lim": SCAN_LIMIT, "pats": pats})


def _over(c, uid):
    """훑는 범위를 넘쳤는가 — 적격 기록 또는 읽고 든 생각이 SCAN_LIMIT 보다 많다."""
    n_rec = db._one(c, f"SELECT count(*) AS n FROM (SELECT 1 FROM records r WHERE r.user_id=%s AND {db._ELIGIBLE_SQL} "
                       f"LIMIT %s) z", (uid, SCAN_LIMIT + 1))["n"]
    n_ref = db._one(c, "SELECT count(*) AS n FROM (SELECT 1 FROM source_reflections WHERE user_id=%s AND trashed_at IS NULL "
                       "LIMIT %s) z", (uid, SCAN_LIMIT + 1))["n"]
    return n_rec > SCAN_LIMIT or n_ref > SCAN_LIMIT


def _reflections(c, uid, pats):
    return db._all(c, "SELECT x.* FROM (SELECT sr.id, sr.kind, sr.body, sr.revision, sr.created, s.name AS title, "
                      "(sr.created AT TIME ZONE 'Asia/Seoul')::date AS d "
                      "FROM source_reflections sr JOIN sources s ON s.user_id=sr.user_id AND s.id=sr.source_id "
                      "WHERE sr.user_id=%(uid)s AND sr.trashed_at IS NULL ORDER BY sr.created DESC, sr.id DESC LIMIT %(lim)s) x "
                      "WHERE x.body ILIKE ANY(%(pats)s)", {"uid": uid, "lim": SCAN_LIMIT, "pats": pats})


def _posts(c, uid, pats):
    """수집 글 — 제목 줄과 메타 키만 하나씩 꺼낸다(본문, ai_* 없음). 수집일 내림차순."""
    return db._all(c, "SELECT x.* FROM (SELECT i.id, i.title, i.data->>'post_url' AS post_url, "
                      "i.data->>'author_display' AS author_display, i.data->>'collected_on' AS collected_on "
                      "FROM items i JOIN object_defs o ON o.user_id=i.user_id AND o.id=i.object_id "
                      "WHERE i.user_id=%(uid)s AND o.key=%(key)s AND i.revision > 0 AND i.archived_at IS NULL AND i.trashed_at IS NULL "
                      "ORDER BY i.data->>'collected_on' DESC NULLS LAST, i.id LIMIT %(lim)s) x "
                      "WHERE x.title ILIKE ANY(%(pats)s) ORDER BY x.collected_on DESC NULLS LAST, x.id", {"uid": uid, "key": COLLECTED_KEY, "lim": SCAN_LIMIT, "pats": pats})


def _pinned(c, uid, qid):
    """질문에 묶인 확정 후보(지운 글, 휴지통 글의 후보는 뺀다 — export_forms 와 같은 조건). rec = 근거 기록 행(날짜 = db.RECORD_SORT)."""
    rows = db._all(c, "SELECT c.id, c.record_id, c.quote, c.quote_start, c.quote_end, c.revision FROM candidates c JOIN records r ON r.user_id=c.user_id "
                      "AND r.id=c.record_id AND r.deleted_at IS NULL AND r.trashed_at IS NULL "
                      "WHERE c.user_id=%s AND c.question_id=%s AND c.decision='confirmed' ORDER BY c.created, c.quote_start, c.id",
                   (uid, qid))
    ids = sorted({r["record_id"] for r in rows})
    recs = {x["id"]: x for x in db._all(c, f"SELECT {_REC_COLS} FROM records r WHERE r.user_id=%s AND r.id = ANY(%s)",
                                        (uid, ids))} if ids else {}
    return [{**r, "rec": recs[r["record_id"]], "d": recs[r["record_id"]]["d"]} for r in rows]


# ── 조립 ──────────────────────────────────────────────

def _ref(kind, row):
    return {"kind": kind, "id": row["id"], "revision": row["revision"]}


_HEAD_CHARS = tuple("#>-*+_=`~<[")    # 줄 머리에 오면 구조(소제목, 인용, 목록, 가로줄, setext 밑줄, 코드 울타리, HTML, 링크 정의)가 될 수 있는 글자
_ORDERED = re.compile(r"\d{1,9}(?=[.)])")   # 정렬 목록 꼴 '1. ', '1) '
_INDENT = re.compile(r"[ \t]*")
_THEMATIC = re.compile(r"(?:\*[ \t]*){3,}|(?:-[ \t]*){3,}|(?:_[ \t]*){3,}")   # 가로줄 꼴(같은 글자 3개 이상과 공백만)


def _md_escape(line):
    """markdown 줄 하나를 글자 그대로 보이게 한다(값은 그대로, markdown 만). 4칸 이상 들여쓰기(탭 포함)는 들여쓴 코드가 되므로
    첫 공백을 &#32; 로 바꾼다. 3칸 이하는 첫 글자 앞에 백슬래시(정렬 목록은 숫자 뒤 '.' ')' 앞). 백슬래시 + ASCII 문장 부호는 그 글자로 보인다.
    줄머리 '**', '__'(굵게)는 구조를 깨지 않아 이스케이프하지 않는다(대화 화면에 백슬래시가 남던 것) — 가로줄 꼴('***', '___')만 이스케이프한다."""
    ws = _INDENT.match(line).group()
    body = line[len(ws):]
    if not body:
        return line
    if len(ws.expandtabs(4)) >= 4:
        return "&#32;" + line[1:]
    if body.startswith(("**", "__")) and not _THEMATIC.fullmatch(body):
        return line
    m = _ORDERED.match(body)
    if m:
        return ws + body[:m.end()] + "\\" + body[m.end():]
    return ws + "\\" + body if body.startswith(_HEAD_CHARS) else line


def _md_lines(text):
    """원문 → 이스케이프한 markdown 줄 목록. 줄 끝 = \r\n, \r, \n(export_forms._md_text 는 \n 만 본다)."""
    return [_md_escape(ln) for ln in _LINE_SPLIT.split(text)]


def _md_heading(text):
    """질문 → '## ' 뒤 소제목 글자. 줄 머리 이스케이프 + 끝의 '#' 이스케이프(ATX 닫는 '#' 으로 사라지지 않게, 'C# 도입 #')."""
    return re.sub(r"(?<!\\)(#+)$", r"\\\1", _md_escape(export_forms._one_line(text)))


def _markdown(question, draft, evidence, gaps, labels):
    lines = [f"## {_md_heading(question)}", ""]
    if draft:
        lines += ["### 답변 초안", ""]
        for d in draft:
            ql = _md_lines(d["quote"])
            ql[-1] = f"{ql[-1]} ({d['ref']['id']})"
            lines += [("> " + ln) if ln else ">" for ln in ql] + [""]
    if evidence:
        lines += ["### 근거", ""]
        for e in evidence:
            # 줄 머리 = "- (ref id)" 라 제목이 구조 꼴로 시작해도 이스케이프가 필요 없다. 초안 끝의 (ref id) 와 이 줄이 이어진다
            lines.append(f"- ({e['ref']['id']}) {export_forms._one_line(e['title'])}, {e['date']}, {labels[e['ref']['id']]}")
        lines.append("")
    if gaps:
        lines += ["### 부족한 곳", ""] + [f"- {g['text']}" for g in gaps] + [""]
    return "\n".join(lines)


def _group(groups, labels, kind, r, sws):
    """근거 기록 하나(처음 볼 때 만든다, EVIDENCE_MAX 편 넘으면 None). labels = 근거 줄 셋째 칸(출력에 싣지 않는다). sws = 세션 정리 출처 문자열."""
    g = groups.get(r["id"])
    if g is None and len(groups) < EVIDENCE_MAX:
        is_rec = kind == "record"
        src = sws if is_rec and r["source"] == sws else None
        g = groups[r["id"]] = {
            "ref": _ref(kind, r), "title": r["title"], "date": r["d"].isoformat(), "source": src,
            "provenance": {"text_process": r["text_process"] if is_rec else None,
                           "generation_kind": r["generation_kind"] if is_rec else None,
                           "decision_owner": r["decision_owner"] if is_rec else None},
            "quotes": []}
        labels[r["id"]] = (src or r["text_process"]) if is_rec else REFLECTION_LABELS[r["kind"]]
        g["_d"] = r["d"]
    return g


def _gap(code, count, **kw):
    return {"code": code, "text": GAP_TEXT[code].format(**kw), "count": count}


def assemble(uid, question="", question_id="", terms=None, now=None):
    """answer_get 본체. now = 조립 시각(시험이 고정값을 넘긴다, 없으면 지금). 같은 입력이면 assembled_at 을 뺀 응답이 같다."""
    import imports
    q, qid, given = _args(question, question_id, terms)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    local = now.astimezone(KST)
    with db.tx() as c:
        if qid:
            row = db._one(c, "SELECT id, text FROM questions WHERE user_id=%s AND id=%s", (uid, qid))
            if not row:
                raise db._nf("질문")
            q = row["text"]
        keys_terms = merge_terms(given, question_terms(q))
        keys = [t.lower() for t in keys_terms]
        need = min(2, len(keys))
        pats = [db._like(t) for t in keys_terms]
        pinned = _pinned(c, uid, qid) if qid else []
        if keys:
            scanned, refls = _records(c, uid, None, True), _reflections(c, uid, pats)
            others, posts = _records(c, uid, pats, False), _posts(c, uid, pats)
        else:   # 검색어가 없으면 아무것도 남기지 않는다(min(2, 0) = 0 이라 모든 문장이 통과하는 것을 막는다)
            scanned = refls = others = posts = []
        over = _over(c, uid)
        weights = term_weights((r["body"] for r in scanned), keys)
        recs = [r for r in scanned if any(k in r["body"].lower() for k in keys)]

        # 문장 → 남긴 문장(맞은 서로 다른 검색어 수 ≥ need). 정렬 = 가중치 합 ↓ → 맞은 수 ↓ → 확정 후보 있는 기록 먼저 → 날짜 ↓ → id → 문장 위치
        kept = []
        for kind, rows in (("record", recs), ("reflection", refls)):
            for r in rows:
                for st, en, s in sentences(r["body"]):
                    n, w = weigh(s, keys, weights)
                    if n >= need:
                        kept.append({"kind": kind, "row": r, "start": st, "end": en, "text": s, "hits": n, "score": w,
                                     "confirmed": bool(r.get("confirmed"))})
        kept.sort(key=lambda x: (-x["score"], -x["hits"], not x["confirmed"], -x["row"]["d"].toordinal(), x["row"]["id"], x["start"]))
        ineligible = sum(1 for r in others if any(score(s, keys) >= need for _, _, s in sentences(r["body"])))

        # 답변 초안 — 질문에 묶인 확정 후보 quote 가 맨 앞(점수 무관). 그 quote 와 글자까지 같은 같은 기록의 문장은 거듭 싣지 않는다
        draft, owners, dates, per = [], [], [], {}
        pinned_q = {(p["record_id"], p["quote"]) for p in pinned}
        for p in pinned[:DRAFT_MAX]:
            draft.append({"quote": p["quote"], "ref": _ref("candidate", p)})
            owners.append(p["record_id"])
            dates.append(p["d"])
        for k in kept:
            if len(draft) >= DRAFT_MAX:
                break
            rid = k["row"]["id"]
            if (k["kind"] == "record" and (rid, k["text"]) in pinned_q) or per.get(rid, 0) >= DRAFT_PER_REF:
                continue
            per[rid] = per.get(rid, 0) + 1
            draft.append({"quote": k["text"], "ref": _ref(k["kind"], k["row"])})
            owners.append(rid)
            dates.append(k["row"]["d"])
        draft = [{"n": i, **d} for i, d in enumerate(draft, 1)]

        # 근거 — 질문에 묶인 확정 후보의 기록이 먼저(점수 무관, 그 quote 를 인용으로), 이어서 남긴 문장을 기록별로(정렬 순서, 처음 나온 순).
        # 같은 구간(start, end)은 한 번만. 근거는 EVIDENCE_MAX 편까지, 넘친 서로 다른 기록 수는 more_evidence
        groups, labels, extra = {}, {}, set()
        sws = imports.SESSION_WRAP_SOURCE
        quotes = [("record", p["rec"], p["quote_start"], p["quote_end"], p["quote"], weigh(p["quote"], keys, weights)[1]) for p in pinned] + \
                 [(k["kind"], k["row"], k["start"], k["end"], k["text"], k["score"]) for k in kept]
        for kind, r, st, en, text, n in quotes:
            g = _group(groups, labels, kind, r, sws)
            if g is None:
                extra.add(r["id"])
            elif len(g["quotes"]) < QUOTES_MAX and all((q["start"], q["end"]) != (st, en) for q in g["quotes"]):
                g["quotes"].append({"text": text, "start": st, "end": en, "score": n})
        dates += [g.pop("_d") for g in groups.values()]   # stale = 초안과 근거 전체에서 가장 새 날짜
        evidence = list(groups.values())

        related = [{"id": p["id"], "title": p["title"], "post_url": p["post_url"], "author_display": p["author_display"],
                    "collected_on": p["collected_on"]} for p in posts if score(p["title"], keys) >= need][:POSTS_MAX]

        ev_records = [e["ref"]["id"] for e in evidence if e["ref"]["kind"] == "record"]
        pending = db._one(c, "SELECT count(*) AS n FROM candidates WHERE user_id=%s AND decision='pending' AND record_id = ANY(%s)",
                          (uid, ev_records))["n"] if ev_records else 0

    gaps = []
    if not draft:
        gaps.append(_gap("no_match", 0))
    elif len(draft) <= 2:
        gaps.append(_gap("thin", len(draft), n=len(draft)))
    if len(draft) >= 2 and len(set(owners)) == 1:
        gaps.append(_gap("one_record", 1))
    if pending:
        gaps.append(_gap("pending_candidates", pending, n=pending))
    if ineligible:
        gaps.append(_gap("ineligible_excluded", ineligible, n=ineligible))
    if related and not draft:
        gaps.append(_gap("posts_without_thought", len(related)))
    if dates:
        newest = max(dates)
        age = (local.date() - newest).days
        if age > STALE_DAYS:
            gaps.append(_gap("stale", age, date=newest.isoformat()))
    if extra:
        gaps.append(_gap("more_evidence", len(extra), n=len(extra)))
    if over:
        gaps.append(_gap("truncated", SCAN_LIMIT))

    return {"kind": "answer_material", "question": {"text": q, "id": qid or None}, "terms": keys_terms,
            "draft": draft, "evidence": evidence, "related_posts": related, "gaps": gaps,
            "markdown": _markdown(q, draft, evidence, gaps, labels), "notice": NOTICE,
            "display_rule": DISPLAY_RULE, "assembled_at": local.isoformat(timespec="seconds")}
