"""구조 추천과 자동 분류(route) — 2026-11-18 구조추천 명세 6절.

담을 규칙(오브젝트 정의의 policy.route)에 정확히 맞는 원문을 승인 없이 그 오브젝트 항목으로 바로 저장한다.
사람은 틀린 것만 뺀다(빼기 = 그 단위를 route 예외로 기록, 다시 들어오지 않는다).

- 판정은 evaluate 하나(순수 함수, DB 를 읽지 않는다). 채워질 건수, backfill, 새 원문 훅, 분류 못 함, 초안 견본이 전부 이것만 부른다.
- DB 반영은 sync 하나. 항목은 db.item_propose → item_decide(apply) 로 만들고(이력 한 줄) 지울 땐 영구 삭제 본체(db._purge_item)를 쓴다.
- 정규식을 사용자 입력으로 받지 않는다. *_like 꼴(글자 그대로 + # 숫자 한 개 이상 + 맨 끝 * 하나)만 서버가 정규식으로 바꾼다.
- 필드 값은 원문 구간(앞뒤 공백을 뺀 연속 원문)이거나 원문에서 결정적으로 뽑은 값(날짜, 제목 줄)뿐이다. 서버가 만든 문장은 없다.
- 화면과 MCP 가 읽는 사실(profile, 항목의 자동 분류 정보, 오브젝트 건수, 빼기, 되돌리기, 초안 버리기)도 여기 둔다.

이 모듈은 맨 위에서 db 를 가져오지 않는다(db 가 정의 검증에 이 모듈을 쓴다). DB 를 쓰는 함수 안에서 가져온다.
"""
import functools
import json
import re

LIKE_MAX = 80                 # *_like 글자 수 상한
WORD_MAX = 200                # require 낱말, 추출 규칙의 라벨, 머리, 키 글자 수 상한
WORDS_MAX = 20                # require 목록 하나의 낱말 수 상한
UNIT_KEY_MAX = 200            # unit_key(머리 글자) 컷
BUDGET = 500                  # sync 한 번에 새로 만드는 항목 수 상한
CHUNK = 200                   # sync_all 이 한 트랜잭션에 맞추는 기록 수
QUOTE_MAX = 200               # 견본 quote, 빼기 미리보기 구간 앞 글자 수
PROFILE_SCAN = 2000           # profile 이 읽는 기록 수 상한(answer_get 과 같다)
SUGGEST_MIN = 30              # 어느 오브젝트에도 안 붙은 기록이 이보다 많으면 추천 알림
LIMIT_TEXT = 1024             # db.LIMIT_TEXT 와 같다(제목, UTF-8 바이트) — 시험이 같은지 본다
LIMIT_JSON = 32 * 1024        # db.LIMIT_JSON 과 같다(data 직렬화, UTF-8 바이트)

UNITS = ("record", "heading")
FROMS = ("record_date", "title", "heading", "label", "section", "key", "unit_body")
REASONS = ("require", "required_field", "too_long", "title", "invalid", "duplicate_heading")   # invalid = 서버 항목 검사(item_propose)가 거절
STATES = ("routed", "partial", "excluded")    # 건수(counts, route_counts, profile)에 싣는 행 상태
ROW_STATES = STATES + ("released",)           # released = route 를 뺀 적용으로 놓아 준 항목(item_id 유지, 자동 분류 아님, 잠금 없음, 표시 없음)
_ROUTE_KEYS = frozenset({"v", "unit", "match", "require", "title", "fields"})
_MATCH_KEYS = frozenset({"source", "title_like", "heading_like", "skip_body_like"})
_REQUIRE_KEYS = ("labels", "headings", "keys")
_RULE_ARG = {"label": "label", "section": "heading", "key": "key"}   # from → 함께 받는 키
_TEXT_FROMS = ("title", "heading", "label", "section", "key", "unit_body")
_BAD_LIKE = re.compile(r"[\\\[\]|^$]|\.\*|\.\+|\(\?")   # 정규식 꼴 — 글자 그대로로 받지 않고 거절한다

_HEAD_RE = re.compile(r"(#{2,4})[ \t]+(\S.*)")       # 머리 줄: # 2~4개 + 공백 + 글자
_LABEL_RE = re.compile(r"(?:- )?\*\*(.+?)\*\*")        # 줄 처음 **라벨**(앞에 "- " 허용)
_BOLD_LINE_RE = _LABEL_RE                              # label 값의 끝: 다음 라벨 줄(**…** 로 시작, 앞에 "- " 허용 — require 와 같은 꼴)
_KEY_RE = re.compile(r"- ([^:\r\n]{1,200}?)[ \t]*:")   # 줄 처음 "- 키:" — profile 집계, require keys, key 추출이 이것 하나만 쓴다
_EOL = re.compile(r"\r\n|\r|\n")                        # 줄 끝(\r\n, \r, \n)
_DIGITS = re.compile(r"\d+")
_LEAD_TOKEN = re.compile(r"(\S{0,30}#\S{0,30})\s+\S")  # 꼴의 앞 토큰에 # 이 있으면 "토큰 *" 로 묶는다

ROUTE_GUIDE = (
    "route JSON(오브젝트 정의 policy.route): {\"v\": 1, \"unit\": \"record\"|\"heading\", "
    "\"match\": {\"source\": 출처 글자 그대로, \"title_like\": 제목 꼴, \"heading_like\": 머리 꼴(heading 단위만, 필수), "
    "\"skip_body_like\": 건너뛸 본문 꼴(heading 단위만)}, "
    "\"require\": {\"labels\": [줄 처음 **라벨**], \"headings\": [머리 글자 앞부분], \"keys\": [줄 처음 \"- 키:\"]}, "
    "\"title\": {\"from\": \"title\"|\"heading\"}, "
    "\"fields\": {필드 key: {\"from\": \"record_date\"} | {\"from\": \"title\"} | {\"from\": \"heading\"} | "
    "{\"from\": \"label\", \"label\": 라벨} | {\"from\": \"section\", \"heading\": 머리 글자 앞부분} | {\"from\": \"key\", \"key\": 키} | "
    "{\"from\": \"unit_body\"}}}. "
    "*_like 는 정규식이 아니다: 글자 그대로 + # = 숫자 한 개 이상 + 맨 끝 * = 나머지 아무 글자, 처음부터 끝까지 맞춘다(80자 이내). "
    "# 바로 뒤에 # 이나 숫자는 쓸 수 없다. heading_like \"*\" = 모든 머리 줄. "
    "unit record = 기록 하나가 항목 하나. unit heading = heading_like 에 맞는 머리 줄 하나가 항목 하나(그 머리 줄부터 같은 수준 이하 다음 머리, "
    "또는 heading_like 에 맞는 다음 머리 앞까지. 같은 기록에 같은 머리 글자가 또 나오면 첫째만 항목). "
    "unit_body = heading 단위면 머리 줄 다음 줄부터 단위 끝까지, record 단위면 본문 전체(앞뒤 공백 뺀 원문, 글자 필드만). "
    "skip_body_like = heading 단위의 unit_body 가 이 꼴에 처음부터 끝까지 맞으면 그 머리 줄은 항목이 아니다(분류 못 함으로도 세지 않는다). "
    "날짜 필드에는 record_date 만, 글자 필드에는 title, heading, label, section, key, unit_body, 글자 목록 필드에는 key(쉼표로 나눔)만. "
    "선택, 숫자, 참/거짓, 관계 필드에는 규칙을 둘 수 없다. 기준(principle) 오브젝트와 수집 글 오브젝트에는 route 를 둘 수 없다. "
    "require 가 다 있고 필수 필드가 다 채워진 단위만 항목이 된다. 일부만 맞으면 분류 못 함으로 센다.")


class RouteInvalid(ValueError):
    """route 꼴 오류 — db 가 ARG-INVALID 로 바꾼다."""


def _nbytes(s):
    return len(s.encode("utf-8"))


# ── *_like ─────────────────────────────────────────────

def like_check(s, where):
    """*_like 문자열 검사 → 그대로(앞뒤 공백 뺌). 정규식 꼴, 가운데 *, 줄바꿈, 80자 넘음은 거절."""
    if not isinstance(s, str) or not s.strip():
        raise RouteInvalid(f"{where} 가 비었어요.")
    s = s.strip()
    if len(s) > LIKE_MAX or "\n" in s or "\r" in s:
        raise RouteInvalid(f"{where} 는 한 줄 {LIKE_MAX}자 이내예요.")
    if _BAD_LIKE.search(s):
        raise RouteInvalid(f"{where} 에 정규식은 쓸 수 없어요. 글자 그대로 + # (숫자) + 맨 끝 * 만 써요.")
    if "*" in s[:-1]:
        raise RouteInvalid(f"{where} 의 * 는 맨 끝에 하나만 써요.")
    for i, ch in enumerate(s[:-1]):   # 숫자 자리 뒤에 또 숫자가 올 수 있으면 매칭이 갈래를 친다 — 꼴에서 막는다
        if ch == "#" and (s[i + 1] == "#" or s[i + 1].isdecimal()):
            raise RouteInvalid(f"{where} 의 # 바로 뒤에는 # 이나 숫자를 쓸 수 없어요.")
    return s


@functools.lru_cache(maxsize=256)
def like_tokens(s):
    """검사한 *_like → 토큰 묶음: ("lit", 글자들) | ("num",) | ("rest",). 정규식을 만들지 않는다."""
    out, lit = [], []
    for i, ch in enumerate(s):
        if ch == "#" or (ch == "*" and i == len(s) - 1):
            if lit:
                out.append(("lit", "".join(lit)))
                lit = []
            out.append(("num",) if ch == "#" else ("rest",))
        else:
            lit.append(ch)
    if lit:
        out.append(("lit", "".join(lit)))
    return tuple(out)


def like_match(s, text):
    """*_like 가 text 처음부터 끝까지 맞나 — 입력 길이에 선형(갈래 없음). # = 숫자(str.isdecimal) 한 개 이상을 다 먹는다.
    like_check 가 # 뒤에 # 이나 숫자를 못 오게 해서, 숫자를 다 먹는 것 말고 다른 맞춤은 없다."""
    p = 0
    for tok in like_tokens(s):
        if tok[0] == "rest":
            return True
        if tok[0] == "lit":
            if not text.startswith(tok[1], p):
                return False
            p += len(tok[1])
        else:
            q = p
            while q < len(text) and text[q].isdecimal():
                q += 1
            if q == p:
                return False
            p = q
    return p == len(text)


# ── 정의 검증 ───────────────────────────────────────────

def _word(v, where):
    if not isinstance(v, str) or not v.strip():
        raise RouteInvalid(f"{where} 가 비었어요.")
    v = v.strip()
    if len(v) > WORD_MAX or "\n" in v or "\r" in v:
        raise RouteInvalid(f"{where} 는 한 줄 {WORD_MAX}자 이내예요.")
    return v


def check_route(route, fields, object_key=None, semantic_kind=None):
    """policy.route 꼴 검사 → 정규화한 route. fields = 그 정의의 필드 목록(normalize_definition 결과 꼴).
    모르는 키, 모르는 from, 없는 필드 key, 타입에 안 맞는 추출 규칙, 정규식 꼴은 RouteInvalid."""
    if semantic_kind == "principle":
        raise RouteInvalid("기준(principle) 오브젝트에는 담을 규칙(route)을 둘 수 없어요.")
    if object_key == "collected_posts":
        raise RouteInvalid("수집 글 오브젝트에는 담을 규칙(route)을 둘 수 없어요.")
    if not isinstance(route, dict):
        raise RouteInvalid("policy.route 는 JSON 객체예요.")
    bad = sorted(str(k) for k in route if k not in _ROUTE_KEYS)
    if bad:
        raise RouteInvalid(f"policy.route 에 모르는 키가 있어요: {', '.join(bad)}")
    if route.get("v", 1) != 1:
        raise RouteInvalid("policy.route.v 는 1 이에요.")
    unit = route.get("unit")
    if unit not in UNITS:
        raise RouteInvalid(f"policy.route.unit 은 {', '.join(UNITS)} 중 하나예요.")
    match = route.get("match") or {}
    if not isinstance(match, dict):
        raise RouteInvalid("policy.route.match 는 JSON 객체예요.")
    bad = sorted(str(k) for k in match if k not in _MATCH_KEYS)
    if bad:
        raise RouteInvalid(f"policy.route.match 에 모르는 키가 있어요: {', '.join(bad)}")
    m = {}
    if match.get("source") is not None:
        src = match["source"]
        if not isinstance(src, str) or not src.strip() or _nbytes(src) > LIMIT_TEXT:
            raise RouteInvalid("match.source 는 비지 않은 출처 글자예요.")
        m["source"] = src
    if match.get("title_like") is not None:
        m["title_like"] = like_check(match["title_like"], "match.title_like")
    if match.get("heading_like") is not None:
        if unit != "heading":
            raise RouteInvalid("match.heading_like 는 unit heading 에서만 써요.")
        m["heading_like"] = like_check(match["heading_like"], "match.heading_like")
    if match.get("skip_body_like") is not None:
        if unit != "heading":
            raise RouteInvalid("match.skip_body_like 는 unit heading 에서만 써요.")
        m["skip_body_like"] = like_check(match["skip_body_like"], "match.skip_body_like")
    if unit == "heading" and "heading_like" not in m:
        raise RouteInvalid("unit heading 은 match.heading_like 가 필요해요.")
    req = route.get("require") or {}
    if not isinstance(req, dict):
        raise RouteInvalid("policy.route.require 는 JSON 객체예요.")
    bad = sorted(str(k) for k in req if k not in _REQUIRE_KEYS)
    if bad:
        raise RouteInvalid(f"policy.route.require 에 모르는 키가 있어요: {', '.join(bad)}")
    r = {}
    for k in _REQUIRE_KEYS:
        v = req.get(k) or []
        if not isinstance(v, list) or len(v) > WORDS_MAX:
            raise RouteInvalid(f"require.{k} 는 {WORDS_MAX}개 이내 글자 목록이에요.")
        words = []
        for w in v:
            w = _word(w, f"require.{k}")
            if w not in words:
                words.append(w)
        r[k] = words
    if unit == "record" and not m and not any(r.values()):
        raise RouteInvalid("unit record 는 match(source, title_like)나 require 가 하나 이상 있어야 해요(모든 기록을 담지 않는다).")
    t = route.get("title") or {}
    if not isinstance(t, dict) or sorted(t) not in ([], ["from"]):
        raise RouteInvalid("policy.route.title 은 {\"from\": \"title\"|\"heading\"} 이에요.")
    tfrom = t.get("from") or ("heading" if unit == "heading" else "title")
    if tfrom not in ("title", "heading") or (tfrom == "heading" and unit != "heading"):
        raise RouteInvalid("title.from 은 title 이거나(heading 단위면) heading 이에요.")
    byk = {f["key"]: f for f in fields if isinstance(f, dict) and f.get("key")}
    rules = route.get("fields") or {}
    if not isinstance(rules, dict):
        raise RouteInvalid("policy.route.fields 는 JSON 객체예요.")
    out_rules = {}
    for fk, rule in rules.items():
        f = byk.get(fk)
        if f is None:
            raise RouteInvalid(f"route.fields 의 {fk} 는 이 정의에 없는 필드예요.")
        if not isinstance(rule, dict):
            raise RouteInvalid(f"route.fields.{fk} 는 JSON 객체예요.")
        src = rule.get("from")
        if src not in FROMS:
            raise RouteInvalid(f"route.fields.{fk}.from 은 {', '.join(FROMS)} 중 하나예요.")
        arg = _RULE_ARG.get(src)
        allowed = {"from", arg} if arg else {"from"}
        bad = sorted(str(k) for k in rule if k not in allowed)
        if bad:
            raise RouteInvalid(f"route.fields.{fk} 에 모르는 키가 있어요: {', '.join(bad)}")
        vt = f.get("value_type")
        if vt == "date":
            ok = src == "record_date"
        elif vt == "text":
            ok = src in _TEXT_FROMS
        elif vt == "text_list":
            ok = src == "key"
        else:
            ok = False
        if not ok:
            raise RouteInvalid(f"route.fields.{fk}: {vt} 필드에는 from {src} 규칙을 둘 수 없어요.")
        if src == "heading" and unit != "heading":
            raise RouteInvalid(f"route.fields.{fk}: from heading 은 unit heading 에서만 써요.")
        nr = {"from": src}
        if arg:
            nr[arg] = _word(rule.get(arg), f"route.fields.{fk}.{arg}")
        out_rules[fk] = nr
    return {"v": 1, "unit": unit, "match": m, "require": r, "title": {"from": tfrom}, "fields": out_rules}


# ── 판정(순수) ──────────────────────────────────────────

def _lines(body):
    """본문 줄 목록 [(줄 시작, 내용 끝, 내용)] — 줄 끝은 \\r\\n, \\r, \\n 셋 다(answer.py 와 같다). 내용에는 줄 끝 글자가 없다.
    offset 은 str 인덱스."""
    out, pos, n = [], 0, len(body)
    for m in _EOL.finditer(body):
        out.append((pos, m.start(), body[pos:m.start()]))
        pos = m.end()
    out.append((pos, n, body[pos:n]))
    return out


def _heads(lines):
    """머리 줄 [(줄 번호, 수준, 글자, 글자 시작, 글자 끝)]."""
    out = []
    for i, (s, _e, t) in enumerate(lines):
        m = _HEAD_RE.fullmatch(t)
        if m:
            text = m.group(2).rstrip()
            ts = s + m.start(2)
            out.append((i, len(m.group(1)), text, ts, ts + len(text)))
    return out


def _strip(body, s, e):
    """[s, e) 에서 앞뒤 공백을 뺀 구간. 비면 None."""
    while s < e and body[s].isspace():
        s += 1
    while e > s and body[e - 1].isspace():
        e -= 1
    return (s, e) if e > s else None


def _label_of(t):
    m = _LABEL_RE.match(t)
    return (m, m.group(1).strip().rstrip(":：").strip()) if m else (None, None)


class _Unit:
    """단위 하나의 줄과 머리 — 추출과 require 검사가 같이 쓴다."""

    def __init__(self, body, lines, heads, us, ue, li, lj, head=None):
        self.body, self.lines, self.us, self.ue = body, lines, us, ue
        self.idx = range(li, lj)                      # 단위 안 줄 번호
        self.heads = [h for h in heads if li <= h[0] < lj]
        self.head = head                              # heading 단위의 머리 줄(record 단위는 None)

    def has_label(self, label):
        return any(_label_of(self.lines[i][2])[1] == label for i in self.idx)

    def has_heading(self, prefix):
        return any(h[2].startswith(prefix) for h in self.heads)

    def _key_line(self, key):
        """키 줄(_KEY_RE 하나로 판정) → (줄 번호, 값 시작). 없으면 None."""
        for i in self.idx:
            m = _KEY_RE.match(self.lines[i][2])
            if m and m.group(1).strip() == key:
                return i, self.lines[i][0] + m.end()
        return None

    def has_key(self, key):
        return self._key_line(key) is not None

    def _next_start(self, i):
        return self.lines[i + 1][0] if i + 1 < len(self.lines) and i + 1 in self.idx else self.ue

    def label(self, label):
        for i in self.idx:
            s, ce, t = self.lines[i]
            m, name = _label_of(t)
            if name != label:
                continue
            p = s + m.end()
            while p < ce and self.body[p] in " \t":
                p += 1
            if p < ce and self.body[p] in "—–-:":
                p += 1
            end = self.ue
            for j in self.idx:
                if j <= i:
                    continue
                tj = self.lines[j][2]
                if _BOLD_LINE_RE.match(tj) or _HEAD_RE.fullmatch(tj):
                    end = self.lines[j][0]
                    break
            return _strip(self.body, p, end)
        return None

    def section(self, prefix):
        for k, h in enumerate(self.heads):
            if not h[2].startswith(prefix):
                continue
            s = self._next_start(h[0])
            e = self.lines[self.heads[k + 1][0]][0] if k + 1 < len(self.heads) else self.ue
            return _strip(self.body, s, max(s, e))
        return None

    def key(self, key):
        k = self._key_line(key)
        return _strip(self.body, k[1], self.lines[k[0]][1]) if k else None

    def unit_body(self):
        """단위 본문 — heading 단위는 머리 줄 다음 줄부터 단위 끝까지, record 단위는 단위 전체(본문 전체). 앞뒤 공백 뺀 구간, 비면 None.
        필드 추출(from unit_body)과 match.skip_body_like 판정이 이것 하나를 쓴다."""
        s = self._next_start(self.head[0]) if self.head else self.us
        return _strip(self.body, s, max(s, self.ue))


def _pieces(body, s, e):
    """text_list 조각 — 쉼표로 나눠 앞뒤 공백을 뺀 원문 조각 목록."""
    out, p = [], s
    for part in body[s:e].split(","):
        q = _strip(body, p, p + len(part))
        if q:
            out.append(body[q[0]:q[1]])
        p += len(part) + 1
    return out


def evaluate(record, route, fields):
    """기록 하나를 route 로 판정 → 단위 목록. record = {id, title, body, source, date(YYYY-MM-DD)}.
    route = check_route 를 지난 꼴(정규화). fields = 오브젝트의 지금 필드 정의(required 검사에 전부 쓴다).
    Unit = {unit_key, state(exact|partial), reason, title, data, start, end, spans{field_key: [start, end]}}.
    offset = Python str 인덱스, body[start:end] 가 단위 구간. 일치 없음 = 빈 목록."""
    body = record.get("body") or ""
    title = (record.get("title") or "").strip()
    m = route.get("match") or {}
    if "source" in m and record.get("source") != m["source"]:
        return []
    if "title_like" in m and not like_match(m["title_like"], title):
        return []
    lines = _lines(body)
    heads = _heads(lines)
    unit = route["unit"]
    spans_units = []   # (unit_key, 단위, 머리 or None, 중복 머리인가)
    if unit == "record":
        spans_units.append(("", _Unit(body, lines, heads, 0, len(body), 0, len(lines)), None, False))
    else:
        hits = [k for k, h in enumerate(heads) if like_match(m["heading_like"], h[2])]
        hit_set = set(hits)
        skip = m.get("skip_body_like")
        seen = {}
        for k in hits:
            h = heads[k]
            # 구간 끝 = 같은 수준 이하 다음 머리, 또는 heading_like 에 맞는 다음 머리(수준 무관) 가운데 먼저 오는 곳.
            # 겹친 머리에서 바깥 단위가 안쪽 단위의 줄을 가져가지 않는다. 건너뛴(skip_body_like) 머리도 구간 끝이다(hit_set 에 남긴다)
            nxt = next((j for j in range(k + 1, len(heads)) if heads[j][1] <= h[1] or j in hit_set), None)
            ue = lines[heads[nxt][0]][0] if nxt is not None else len(body)
            lj = heads[nxt][0] if nxt is not None else len(lines)
            u = _Unit(body, lines, heads, lines[h[0]][0], ue, h[0], lj, h)
            if skip:
                # unit_body(앞뒤 공백 뺀 것, 비면 "")가 꼴에 처음부터 끝까지 맞으면 단위가 아니다 — partial 도 아니고 중복 수에도 안 든다
                sp = u.unit_body()
                if like_match(skip, body[sp[0]:sp[1]] if sp else ""):
                    continue
            # unit_key = 머리 글자 그대로. 같은 기록에서 같은 머리가 또 나오면 첫째만 단위, 둘째부터는 partial(duplicate_heading)이고
            # key = 머리 글자 + "\n" + 순번(머리 글자에는 줄바꿈이 없어 겹치지 않는다). 그래서 key 는 기록 안에서 유일하다
            key = h[2][:UNIT_KEY_MAX]
            seen[key] = seen.get(key, 0) + 1
            dup = seen[key] > 1
            spans_units.append((f"{key}\n{seen[key]}" if dup else key, u, h, dup))
    req = route.get("require") or {}
    checks = (("labels", "has_label"), ("headings", "has_heading"), ("keys", "has_key"))
    byk = {f["key"]: f for f in fields}
    out = []
    for key, u, h, dup in spans_units:
        want = [(meth, w) for k, meth in checks for w in req.get(k) or []]
        got = sum(1 for meth, w in want if getattr(u, meth)(w))
        if want and got == 0 and unit == "record":
            continue
        data, spans = {}, {}
        for fk, rule in (route.get("fields") or {}).items():
            src = rule["from"]
            if src == "record_date":
                if record.get("date"):
                    data[fk] = str(record["date"])
                continue
            if src == "title":
                if title:
                    data[fk] = title
                continue
            if src == "heading":
                sp = (h[3], h[4]) if h else None
            elif src == "label":
                sp = u.label(rule["label"])
            elif src == "section":
                sp = u.section(rule["heading"])
            elif src == "unit_body":
                sp = u.unit_body()
            else:
                sp = u.key(rule["key"])
            if not sp:
                continue
            if (byk.get(fk) or {}).get("value_type") == "text_list":
                parts = _pieces(body, *sp)
                if not parts:
                    continue
                data[fk] = parts
            else:
                data[fk] = body[sp[0]:sp[1]]
            spans[fk] = [sp[0], sp[1]]
        utitle = (h[2] if h and route["title"]["from"] == "heading" else title).strip()
        reason = None
        if dup:
            reason = "duplicate_heading"
        elif want and got < len(want):
            reason = "require"
        elif any(f.get("required") and f["key"] not in data for f in fields):
            reason = "required_field"
        elif _nbytes(json.dumps(data, ensure_ascii=False)) > LIMIT_JSON:
            reason = "too_long"
        elif not utitle or _nbytes(utitle) > LIMIT_TEXT:
            reason = "title"
        out.append({"unit_key": key, "state": "partial" if reason else "exact", "reason": reason, "title": utitle,
                    "data": data, "start": u.us, "end": u.ue, "spans": spans})
    return out


# ── profile 꼴 ─────────────────────────────────────────

def shape(text):
    """제목, 머리 꼴 — 숫자 연속은 #, 앞 토큰에 # 이 있으면 "토큰 *"(같은 번호 꼴을 하나로 묶는다). 200자 컷."""
    s = _DIGITS.sub("#", text.strip())
    m = _LEAD_TOKEN.match(s)
    if m:
        s = m.group(1) + " *"
    return s[:QUOTE_MAX]


# ── DB 반영(sync) ───────────────────────────────────────

# 옛 개정 = 그 기록을 가리키는 접수 행이 있고, 그 가운데 지금 적용(is_current_applied)인 행이 하나도 없다.
# (같은 판 재전송 noop 은 옛 행 false + 새 noop 행 true 로 같은 기록을 가리킨다 — false 행 하나로 빼면 살아 있는 기록이 빠진다)
_OLD_SQL = ("(EXISTS (SELECT 1 FROM import_entries e WHERE e.user_id=r.user_id AND e.target_record_id=r.id) "
            "AND NOT EXISTS (SELECT 1 FROM import_entries e WHERE e.user_id=r.user_id AND e.target_record_id=r.id AND e.is_current_applied))")


def target_sql():
    """대상 기록 조건(별칭 r) — 인용 적격(db._ELIGIBLE_SQL, answer_get 과 같다) + 옛 개정 아님."""
    import db
    return f"({db._ELIGIBLE_SQL} AND NOT {_OLD_SQL})"


def _records(c, uid, record_ids=None, limit=None):
    """record_ids 없음 = 대상 기록 전부(target 참), 있음 = 그 기록들(target 판정 포함, 지운 것도). date = 목록 정렬 날짜(KST)."""
    import db
    cols = f"r.id, r.title, r.body, r.source, r.revision, ({db.RECORD_SORT})::text AS date"
    if record_ids is None:
        sql = f"SELECT {cols}, true AS target FROM records r WHERE r.user_id=%s AND {target_sql()} ORDER BY {db.RECORD_SORT} DESC, r.id DESC"
        args = [uid]
        if limit:
            sql += " LIMIT %s"
            args.append(limit)
        return db._all(c, sql, args)
    return db._all(c, f"SELECT {cols}, COALESCE({target_sql()}, false) AS target FROM records r WHERE r.user_id=%s AND r.id = ANY(%s) "
                      "ORDER BY r.id", (uid, list(record_ids)))


def _route_objects(c, uid, object_ids=None):
    import db
    sql = (f"SELECT {db._DEF_COLS} FROM object_defs WHERE user_id=%s AND revision > 0 AND archived_at IS NULL AND policy ? 'route'")
    args = [uid]
    if object_ids is not None:
        sql += " AND id = ANY(%s)"
        args.append(list(object_ids))
    return db._all(c, sql + " ORDER BY created_at, id", args)


def _upsert(c, uid, oid, rid, u, state, item_id, rev, reason=None):
    import db
    c.execute("INSERT INTO item_routes (user_id,object_id,record_id,unit_key,state,item_id,start_pos,end_pos,spans,record_revision,reason) "
              "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (user_id,object_id,record_id,unit_key) DO UPDATE SET "
              "state=excluded.state, item_id=excluded.item_id, start_pos=excluded.start_pos, end_pos=excluded.end_pos, "
              "spans=excluded.spans, record_revision=excluded.record_revision, reason=excluded.reason, released_revision=NULL, updated_at=now()",
              (uid, oid, rid, u["unit_key"], state, item_id, u["start"], u["end"], db.Jsonb(u["spans"]), rev, reason))


def _same_row(row, u, rev, reason=None):
    return (row["start_pos"], row["end_pos"], row["spans"] or {}, row["record_revision"], row["reason"]) == \
        (u["start"], u["end"], u["spans"], rev, reason)


def _write_item(c, uid, od, item_id, base, u):
    """항목 새로 만들기(item_id None) 또는 값 갱신 — 제안 → 적용(이력 한 줄). savepoint 안: 정의 검사 거절(ARG-INVALID 등)은 None."""
    import db
    try:
        with c.transaction():
            p = db.item_propose(uid, od["id"], od["revision"], item_id, base, None, u["title"], "", u["data"], [])
            db.item_decide(uid, p["item_id"], base, p["proposal_id"], "apply")
            if item_id is None:
                c.execute("UPDATE items SET ingest_kind='route' WHERE user_id=%s AND id=%s", (uid, p["item_id"]))
            return p["item_id"]
    except db.CrmError:
        return None


def _drop_item(c, uid, item_id):
    """자동 분류 항목 완전 삭제(휴지통 없이) — 영구 삭제 본체. item_routes 행은 FK 로 함께 지워진다."""
    import db
    db._purge_item(c, uid, item_id)


def _has_links(c, uid, item_id):
    """그 항목을 가리키는 연결(item_links 대상, activity_links 축)이 있나 — 있으면 지우지 않는다(사용자가 만든 연결 보호)."""
    import db
    return db._one(c, "SELECT EXISTS (SELECT 1 FROM item_links WHERE user_id=%s AND target_item_id=%s) "
                      "OR EXISTS (SELECT 1 FROM activity_links WHERE user_id=%s AND axis_item_id=%s) AS x",
                   (uid, item_id, uid, item_id))["x"]


def _release_or_drop(c, uid, oid, k, row, out):
    """자동 분류 항목을 놓는다 — 연결이 있으면 지우지 않고 released 로 둔다(True), 없으면 완전 삭제(False, 행도 함께 지워진다).
    routed 항목에는 연결 가드(db._route_link_guard) 때문에 연결이 붙지 않는다 — 연결이 있는 경우는 방어 코드다."""
    if _has_links(c, uid, row["item_id"]):
        c.execute("UPDATE item_routes r SET state='released', reason=NULL, released_revision=i.revision, updated_at=now() FROM items i "
                  "WHERE i.user_id=r.user_id AND i.id=r.item_id AND r.user_id=%s AND r.object_id=%s AND r.record_id=%s AND r.unit_key=%s",
                  (uid, oid, k[0], k[1]))
        return True
    _drop_item(c, uid, row["item_id"])
    out["removed"] += 1
    return False


def _takeable(c, uid, row):
    """놓아 준 항목을 서버가 다시 가져가도 되나 — 항목이 살아 있고(삭제, 휴지통, 보관 아님), revision 이 놓아 줄 때와 같고(사용자가 손대지
    않았다), 그 항목을 가리키는 연결이 없을 때만."""
    import db
    it = db._one(c, "SELECT revision FROM items WHERE user_id=%s AND id=%s AND trashed_at IS NULL AND archived_at IS NULL", (uid, row["item_id"]))
    return bool(it) and row["released_revision"] is not None and it["revision"] == row["released_revision"] \
        and not _has_links(c, uid, row["item_id"])


# 같은 원본(접수 행의 같은 stream_id, original_id)의 다른 판 기록에 있는 빼기(excluded)를 이 기록들에 옮겨 적는다.
# 장치 새 판, 이관 새 판이 새 기록이 되어도 뺀 단위는 다시 들어오지 않는다
_CARRY_EXCLUDED = (
    "INSERT INTO item_routes (user_id,object_id,record_id,unit_key,state,reason) "
    "SELECT DISTINCT x.user_id, x.object_id, e2.target_record_id, x.unit_key, 'excluded', 'user' FROM item_routes x "
    "JOIN import_entries e1 ON e1.user_id=x.user_id AND e1.target_record_id=x.record_id "
    "JOIN import_entries e2 ON e2.user_id=e1.user_id AND e2.stream_id=e1.stream_id AND e2.original_id=e1.original_id "
    "AND e2.target_record_id IS NOT NULL AND e2.target_record_id <> x.record_id "
    "WHERE x.user_id=%s AND x.object_id=%s AND x.state='excluded' AND e2.target_record_id = ANY(%s) "
    "ON CONFLICT DO NOTHING")


def _sync_object(c, uid, od, recs, record_ids, out, budget):
    import db
    fields = db._fields(c, uid, od["id"])
    route = check_route(od["policy"]["route"], fields, od["key"], od["semantic_kind"])
    oid = od["id"]
    targets = [r for r in recs if r["target"]]
    tids = {r["id"] for r in targets}
    if tids:
        c.execute(_CARRY_EXCLUDED, (uid, oid, sorted(tids)))
    sql = ("SELECT r.record_id, r.unit_key, r.state, r.item_id, r.start_pos, r.end_pos, r.spans, r.record_revision, r.reason, r.released_revision, "
           "i.title, i.data, i.revision, i.trashed_at FROM item_routes r LEFT JOIN items i ON i.user_id=r.user_id AND i.id=r.item_id "
           "WHERE r.user_id=%s AND r.object_id=%s")
    args = [uid, oid]
    if record_ids is not None:
        sql += " AND r.record_id = ANY(%s)"
        args.append(list(record_ids))
    rows = {(r["record_id"], r["unit_key"]): r for r in db._all(c, sql, args)}
    for rec in targets:
        keys = set()
        for u in evaluate(rec, route, fields):
            k = (rec["id"], u["unit_key"])
            if k in keys:   # 방어 — evaluate 의 key 는 기록 안에서 유일하다. 또 오면 뒤의 것은 건너뛴다
                continue
            keys.add(k)
            row = rows.get(k)
            st = row["state"] if row else None
            if st == "excluded":
                continue
            if st == "released":
                # 놓아 준 항목은 사용자 것이다(재검토 15, 16). 손대지 않았을 때만(살아 있음, revision 그대로, 연결 없음) 단위가 exact 면
                # 다시 가져간다. 아니면 행을 released 그대로 두고 그 단위에 새 항목도 만들지 않는다(사용자 항목이 차지한 단위)
                if u["state"] == "exact" and _takeable(c, uid, row):
                    if (row["title"], row["data"]) == (u["title"], u["data"]):
                        _upsert(c, uid, oid, rec["id"], u, "routed", row["item_id"], rec["revision"])
                    elif _write_item(c, uid, od, row["item_id"], row["revision"], u):
                        _upsert(c, uid, oid, rec["id"], u, "routed", row["item_id"], rec["revision"])
                        out["updated"] += 1
                continue
            if st == "routed" and row["trashed_at"] is not None:   # 서버 밖에서 휴지통으로 간 자동 분류 항목 — 건드리지 않는다
                continue
            if u["state"] == "exact":
                if st == "routed":
                    if (row["title"], row["data"]) == (u["title"], u["data"]):
                        if not _same_row(row, u, rec["revision"]):
                            _upsert(c, uid, oid, rec["id"], u, "routed", row["item_id"], rec["revision"])
                        continue
                    iid = _write_item(c, uid, od, row["item_id"], row["revision"], u)
                    if iid:
                        _upsert(c, uid, oid, rec["id"], u, "routed", iid, rec["revision"])
                        out["updated"] += 1
                        continue
                    if _release_or_drop(c, uid, oid, k, row, out):
                        continue
                    _upsert(c, uid, oid, rec["id"], u, "partial", None, rec["revision"], "invalid")
                    out["partial"] += 1
                    continue
                if out["created"] >= budget:
                    out["left"] += 1
                    continue
                iid = _write_item(c, uid, od, None, 0, u)
                if iid:
                    _upsert(c, uid, oid, rec["id"], u, "routed", iid, rec["revision"])
                    out["created"] += 1
                else:
                    if not row or not _same_row(row, u, rec["revision"], "invalid"):
                        _upsert(c, uid, oid, rec["id"], u, "partial", None, rec["revision"], "invalid")
                    out["partial"] += 1
                continue
            if st == "routed" and _release_or_drop(c, uid, oid, k, row, out):
                continue
            out["partial"] += 1
            if st != "partial" or not _same_row(row, u, rec["revision"], u["reason"]):
                _upsert(c, uid, oid, rec["id"], u, "partial", None, rec["revision"], u["reason"])
        for k, row in rows.items():   # 판정에서 사라진 단위
            if k[0] == rec["id"] and k not in keys and row["state"] != "excluded":
                _drop(c, uid, oid, k, row, out)
    for k, row in rows.items():   # 대상에서 빠진 기록(휴지통, 비적격, 옛 개정, 지움)
        if k[0] not in tids and row["state"] != "excluded":
            _drop(c, uid, oid, k, row, out)


def _drop(c, uid, oid, k, row, out):
    """단위가 없어졌다(판정에서 사라짐, 기록이 대상 밖) — routed 는 항목을 지운다(연결이 있으면 released 로 둔다). partial 은 행만 지운다.
    released 행은 서버가 지우지 않는다(재검토 16) — 없어지는 길은 항목, 기록의 영구 삭제(FK cascade)뿐이다."""
    if row["state"] == "released":
        return
    if row["state"] == "routed" and _release_or_drop(c, uid, oid, k, row, out):
        return
    c.execute("DELETE FROM item_routes WHERE user_id=%s AND object_id=%s AND record_id=%s AND unit_key=%s", (uid, oid, k[0], k[1]))


def _zero():
    return {"created": 0, "updated": 0, "removed": 0, "partial": 0, "left": 0}


def sync(c, uid, record_ids=None, object_ids=None, budget=BUDGET):
    """판정 결과를 DB 에 반영하는 유일한 함수. 호출자의 연결 c(트랜잭션 안)에서 — users 행 잠금부터(잠금 순서 users → object_defs → items).
    record_ids = 그 기록만(훅, 조각), object_ids = 그 오브젝트만(정의 적용). 많은 기록은 sync_all 이 조각으로 나눠 부른다.
    budget = 새로 만드는 항목 수 상한 — 넘으면 left 에 남은 수. 반환 {created, updated, removed, partial, left}.
    오브젝트마다 savepoint — 한 오브젝트의 RouteInvalid 나 오류는 로그 한 줄로 넘기고 다른 오브젝트는 맞춘다."""
    import db
    out = _zero()
    if record_ids is not None:
        record_ids = sorted({str(r) for r in record_ids if r})
        if not record_ids:
            return out
    db._user_lock(c, uid)
    objs = _route_objects(c, uid, object_ids)
    if not objs:
        return out
    recs = _records(c, uid, record_ids)
    with db.route_mode(), db.scope_bind(c):
        for od in objs:
            before = dict(out)
            try:
                with c.transaction():
                    _sync_object(c, uid, od, recs, record_ids, out, budget)
            except Exception as e:   # noqa: BLE001 — 한 오브젝트가 다른 오브젝트와 원문 쓰기를 막지 않는다
                out.clear()
                out.update(before)
                code = getattr(e, "code", None) or type(e).__name__
                print(f"[route] 오브젝트 맞추기 실패 — user={uid} object={od['id']} code={code}", flush=True)
    return out


def sync_all(uid, object_ids=None, budget=BUDGET):
    """사용자 전체(또는 그 오브젝트) 맞추기 — 기록 CHUNK 편씩(id keyset) 트랜잭션을 나눠 sync 를 부른다. 조각마다 사용자 행 잠금을 놓는다.
    본문은 조각마다 읽는다. budget 은 호출 전체의 새 항목 상한(넘친 수는 left). definition_apply 뒤 backfill, 복구, 매일 정리가 쓴다."""
    import db
    tot, last = _zero(), ""
    while True:
        with db.tx() as c:
            ids = [r["id"] for r in db._all(c, "SELECT id FROM records WHERE user_id=%s AND id > %s ORDER BY id LIMIT %s", (uid, last, CHUNK))]
        if not ids:
            return tot
        with db.tx_scope() as c:
            r = sync(c, uid, record_ids=ids, object_ids=object_ids, budget=max(0, budget - tot["created"]))
        for k in tot:
            tot[k] += r[k]
        last = ids[-1]


def hook(c, uid, record_ids):
    """원문 쓰기 훅(기록 생성, 본문, 제목, 출처 판정, 휴지통 이동, 복원) — savepoint 안에서 sync. 실패해도 원문 쓰기는 되돌리지 않는다.
    실패는 로그 한 줄(사용자 id, 기록 id, 오류 코드. 본문 없음). 매일 정리(sweep)가 다시 맞춘다."""
    try:
        with c.transaction():
            sync(c, uid, record_ids=record_ids)
    except Exception as e:   # noqa: BLE001 — 원문 저장 보호가 먼저다
        code = getattr(e, "code", None) or type(e).__name__
        print(f"[route] 훅 실패 — user={uid} records={','.join(str(r) for r in record_ids or [])} code={code}", flush=True)


def sweep(budget=BUDGET) -> dict:
    """매일 정리(main.purge_once) — route 있는 오브젝트를 가진 모든 활성 사용자를 사용자마다 budget 으로 맞춘다.
    남은 backfill 과 훅이 놓친 것의 안전망. 사용자 하나의 실패는 로그 한 줄로 넘기고 다음 사용자로. 반환 합계 + failed."""
    import db
    tot = {"users": 0, "created": 0, "updated": 0, "removed": 0, "partial": 0, "left": 0, "failed": 0}
    with db.tx() as c:
        uids = [r["user_id"] for r in db._all(c, "SELECT DISTINCT o.user_id FROM object_defs o JOIN users u ON u.id=o.user_id "
                                                 "WHERE u.status='active' AND o.revision > 0 AND o.archived_at IS NULL "
                                                 "AND o.policy ? 'route' ORDER BY o.user_id")]
    for uid in uids:
        try:
            r = sync_all(uid, budget=budget)   # 기록 CHUNK 편씩 트랜잭션을 나눈다(본문을 한꺼번에 읽지 않는다)
        except Exception as e:   # noqa: BLE001
            tot["failed"] += 1
            print(f"[route] 매일 맞추기 실패 — user={uid} code={getattr(e, 'code', None) or type(e).__name__}", flush=True)
            continue
        tot["users"] += 1
        for k in ("created", "updated", "removed", "partial", "left"):
            tot[k] += r[k]
    return tot


# ── 항목, 오브젝트의 자동 분류 사실(화면, MCP 응답) ─────────────

def item_sources(c, uid, item_ids):
    """자동 분류 항목 → route_source {record_id, record_title, unit_key, start, end}. 자동 분류가 아닌 항목은 없다."""
    import db
    if not item_ids:
        return {}
    rows = db._all(c, "SELECT r.item_id, r.record_id, r.unit_key, r.start_pos, r.end_pos, rc.title AS record_title FROM item_routes r "
                      "JOIN records rc ON rc.user_id=r.user_id AND rc.id=r.record_id "
                      "WHERE r.user_id=%s AND r.state='routed' AND r.item_id = ANY(%s)", (uid, list(item_ids)))
    return {r["item_id"]: {"record_id": r["record_id"], "record_title": r["record_title"], "unit_key": r["unit_key"],
                           "start": r["start_pos"], "end": r["end_pos"]} for r in rows}


def mark_items(c, uid, items):
    """항목 dict 목록(id 키)에 자동 분류 표시를 단다 — auto_routed: true, route_source. 자동 분류가 아니면 키를 더하지 않는다."""
    src = item_sources(c, uid, [d["id"] for d in items])
    for d in items:
        s = src.get(d["id"])
        if s:
            d["auto_routed"] = True
            d["route_source"] = s
    return items


def is_routed(c, uid, item_id):
    import db
    return db._one(c, "SELECT 1 AS x FROM item_routes WHERE user_id=%s AND item_id=%s AND state='routed'", (uid, item_id)) is not None


def object_counts(c, uid, object_ids=None):
    """오브젝트별 route_counts {routed, partial, excluded}. 행이 없는 오브젝트는 0 셋."""
    import db
    sql = "SELECT object_id, state, count(*) AS n FROM item_routes WHERE user_id=%s AND state <> 'released'"   # 놓아 준 행은 세지 않는다
    args = [uid]
    if object_ids is not None:
        sql += " AND object_id = ANY(%s)"
        args.append(list(object_ids))
    out = {}
    for r in db._all(c, sql + " GROUP BY object_id, state", args):
        out.setdefault(r["object_id"], {s: 0 for s in STATES})[r["state"]] = r["n"]
    return out


def counts(uid, object_ids=None):
    """화면용 — {object_id: {routed, partial, excluded}}(행이 없는 오브젝트는 빠진다. 없으면 0 으로 본다)."""
    import db
    with db.tx() as c:
        return object_counts(c, uid, object_ids)


def item_info(uid, item_id):
    """화면용 — 항목 하나의 자동 분류 사실. 자동 분류가 아니면 None. 있으면
    {item_id, object_id, record_id, record_title, unit_key, start, end, text(단위 구간 원문)}. 원문이 휴지통이면 text None."""
    import db
    with db.tx() as c:
        r = db._one(c, "SELECT r.item_id, r.object_id, r.record_id, r.unit_key, r.start_pos, r.end_pos, rc.title, rc.body, rc.trashed_at "
                       "FROM item_routes r JOIN records rc ON rc.user_id=r.user_id AND rc.id=r.record_id "
                       "WHERE r.user_id=%s AND r.item_id=%s AND r.state='routed'", (uid, str(item_id or "")))
    if not r:
        return None
    live = r["trashed_at"] is None
    return {"item_id": r["item_id"], "object_id": r["object_id"], "record_id": r["record_id"], "record_title": r["title"] if live else None,
            "unit_key": r["unit_key"], "start": r["start_pos"], "end": r["end_pos"],
            "text": r["body"][r["start_pos"]:r["end_pos"]] if live else None}


# ── 빼기, 되돌리기, 초안 버리기 ─────────────────────────────

def _routed_row(c, uid, item_id):
    import db
    return db._one(c, "SELECT r.object_id, r.record_id, r.unit_key, r.start_pos, r.end_pos, i.title, i.revision, rc.title AS record_title, "
                      "rc.body FROM item_routes r JOIN items i ON i.user_id=r.user_id AND i.id=r.item_id "
                      "JOIN records rc ON rc.user_id=r.user_id AND rc.id=r.record_id "
                      "WHERE r.user_id=%s AND r.item_id=%s AND r.state='routed' AND i.trashed_at IS NULL", (uid, str(item_id or "")))


ID_ECHO_MAX = 64   # 오류 문장에 되돌려 주는 id 글자 수(재검토 18)


def _cut(v):
    return str(v or "")[:ID_ECHO_MAX]


def _check_args(**kw):
    """op 인자 길이 — 다른 op 와 같은 상한(db.check_len, LIMIT_TEXT 바이트). 넘으면 PAYLOAD-LIMIT(값은 되돌려 주지 않는다)."""
    import db
    for name, v in kw.items():
        if v is not None and not isinstance(v, (str, int)):
            raise db.CrmError("ARG-INVALID", f"{name} 꼴이 틀렸어요.")
        if isinstance(v, str):
            db.check_len(name, v, db.LIMIT_TEXT)


def _not_routed(item_id):
    import db
    return db.CrmError("ARG-INVALID", f"자동 분류 항목이 아니에요: {_cut(item_id)}", "자동 분류 항목(auto_routed)만 뺄 수 있어요.")


def exclude_preview(uid, item_id):
    """빼기 미리보기 — {item_id, revision, item_title, record_id, record_title, quote(단위 구간 앞 200자)}. 자동 분류가 아니면 ARG-INVALID."""
    import db
    _check_args(item_id=item_id)
    with db.tx() as c:
        r = _routed_row(c, uid, item_id)
    if not r:
        raise _not_routed(item_id)
    return {"item_id": str(item_id), "revision": r["revision"], "item_title": r["title"], "record_id": r["record_id"],
            "record_title": r["record_title"], "quote": r["body"][r["start_pos"]:r["end_pos"]][:QUOTE_MAX]}


def exclude(uid, item_id, expected_revision):
    """빼기(item_route_exclude) — 자동 분류 항목을 지우고(완전 삭제) 그 단위를 excluded 로 남긴다(다시 들어오지 않는다).
    반환 {item_id, object_id, record_id, unit_key, state: excluded}."""
    import db
    _check_args(item_id=item_id)
    if not isinstance(expected_revision, int) or isinstance(expected_revision, bool):
        raise db.CrmError("ARG-INVALID", "expected_revision 은 정수예요.", "item_get 의 revision 을 그대로 넣으세요.")
    with db.tx() as c:
        db._user_lock(c, uid)   # 잠금 순서 = users → items
        db._one(c, "SELECT id FROM items WHERE user_id=%s AND id=%s FOR UPDATE", (uid, str(item_id or "")))
        r = _routed_row(c, uid, item_id)
        if not r:
            raise _not_routed(item_id)
        if r["revision"] != expected_revision:
            raise db._conflict(f"지금 revision {r['revision']}")
        _drop_item(c, uid, item_id)
        c.execute("INSERT INTO item_routes (user_id,object_id,record_id,unit_key,state,item_id,start_pos,end_pos,reason) "
                  "VALUES (%s,%s,%s,%s,'excluded',NULL,%s,%s,'user') ON CONFLICT (user_id,object_id,record_id,unit_key) DO UPDATE SET "
                  "state='excluded', item_id=NULL, reason='user', updated_at=now()",
                  (uid, r["object_id"], r["record_id"], r["unit_key"], r["start_pos"], r["end_pos"]))
    return {"item_id": str(item_id), "object_id": r["object_id"], "record_id": r["record_id"], "unit_key": r["unit_key"], "state": "excluded"}


def include(uid, object_id, record_id, unit_key=""):
    """되돌리기(item_route_include) — 그 단위(object_id, unit_key)의 excluded 행을 같은 계보(같은 stream_id, original_id 의 모든 판 기록)에서
    함께 지우고 그 기록들을 다시 맞춘다(잘못 뺀 것 되돌리기). 계보가 없는 기록은 그 기록의 행만. excluded 행이 없으면 ARG-INVALID.
    반환 {object_id, record_id, unit_key, item_id(다시 생긴 항목, 없으면 None), reason(항목이 안 생긴 까닭 한 낱말, 생겼으면 None), sync}.
    reason = not_target(기록이 대상 밖) | no_unit(규칙에 안 맞음) | partial 이유(require 등) | released(사용자 항목이 차지) | budget."""
    import db
    _check_args(object_id=object_id, record_id=record_id, unit_key=unit_key)
    unit_key = unit_key or ""
    oid, rid = str(object_id or ""), str(record_id or "")
    with db.tx_scope() as c:
        db._user_lock(c, uid)
        rids = [r["id"] for r in db._all(
            c, "SELECT DISTINCT e2.target_record_id AS id FROM import_entries e1 JOIN import_entries e2 ON e2.user_id=e1.user_id "
               "AND e2.stream_id=e1.stream_id AND e2.original_id=e1.original_id WHERE e1.user_id=%s AND e1.target_record_id=%s "
               "AND e2.target_record_id IS NOT NULL", (uid, rid))]
        rids = sorted({rid, *rids})
        n = c.execute("DELETE FROM item_routes WHERE user_id=%s AND object_id=%s AND unit_key=%s AND state='excluded' AND record_id = ANY(%s)",
                      (uid, oid, unit_key, rids)).rowcount
        if not n or not db._one(c, "SELECT 1 AS x FROM records WHERE user_id=%s AND id=%s", (uid, rid)):
            raise db.CrmError("ARG-INVALID", "뺀 기록이 아니에요.", "object_id, record_id, unit_key 를 빼기 결과 그대로 넣으세요.")
        res = sync(c, uid, record_ids=rids, object_ids=[oid])
        r = db._one(c, "SELECT state, item_id, reason FROM item_routes WHERE user_id=%s AND object_id=%s AND record_id=%s AND unit_key=%s",
                    (uid, oid, rid, unit_key))
        tgt = db._one(c, f"SELECT {target_sql()} AS t FROM records r WHERE r.user_id=%s AND r.id=%s", (uid, rid))
        # 옛 판 기록에서 되돌려도 계보의 지금 판에 항목이 생길 수 있다 — 그 항목을 돌려준다
        lin = db._one(c, "SELECT record_id, item_id FROM item_routes WHERE user_id=%s AND object_id=%s AND unit_key=%s AND state='routed' "
                         "AND record_id = ANY(%s) ORDER BY record_id = %s DESC LIMIT 1", (uid, oid, unit_key, rids, rid))
    item_id = r["item_id"] if r and r["state"] == "routed" else (lin["item_id"] if lin else None)
    if item_id:
        reason = None
    elif not (tgt and tgt["t"]):
        reason = "not_target"
    elif r is None:
        reason = "budget" if res["left"] else "no_unit"
    else:
        reason = r["state"] if r["state"] == "released" else (r["reason"] or r["state"])
    return {"object_id": oid, "record_id": rid, "unit_key": unit_key, "item_id": item_id, "reason": reason, "sync": res}


def draft_discard(uid, object_id, proposal_id):
    """초안 버리기(definition_draft_discard) — 적용 전(revision 0) 오브젝트면 행을 지우고, 적용된 오브젝트면 draft 만 비운다.
    proposal_id 가 지금 초안과 다르면 CONFLICT. 반환 {object_id, discarded: true, deleted: bool}."""
    import db
    _check_args(object_id=object_id, proposal_id=proposal_id)
    with db.tx() as c:
        db._user_lock(c, uid)
        r = db._one(c, "SELECT id, revision, draft_id FROM object_defs WHERE user_id=%s AND id=%s FOR UPDATE", (uid, str(object_id or "")))
        if not r:
            raise db.CrmError("ARG-INVALID", f"오브젝트를 찾을 수 없어요: {_cut(object_id)}", "definitions_get 으로 ID 를 확인하세요.")
        if not r["draft_id"] or r["draft_id"] != proposal_id:
            raise db._conflict("초안이 없거나 바뀌었어요")
        if r["revision"] == 0:
            if db._one(c, "SELECT 1 AS x FROM items WHERE user_id=%s AND object_id=%s LIMIT 1", (uid, r["id"])) or \
                    db._one(c, "SELECT 1 AS x FROM field_defs WHERE user_id=%s AND target_object_id=%s LIMIT 1", (uid, r["id"])):
                raise db.CrmError("ARG-INVALID", "이 초안을 가리키는 것이 있어 지울 수 없어요.")
            c.execute("DELETE FROM object_defs WHERE user_id=%s AND id=%s", (uid, r["id"]))
            return {"object_id": r["id"], "discarded": True, "deleted": True}
        c.execute("UPDATE object_defs SET draft_doc=NULL, draft_id=NULL, draft_base_revision=NULL, updated_at=now() WHERE user_id=%s AND id=%s",
                  (uid, r["id"]))
    return {"object_id": r["id"], "discarded": True, "deleted": False}


# ── structure_profile_get ─────────────────────────────

def _top(counter, n, min_records=1):
    rows = [(k, v) for k, v in counter.items() if len(v["records"]) >= min_records]
    rows.sort(key=lambda kv: (-len(kv[1]["records"]), -kv[1]["count"], kv[0]))
    return rows[:n]


def _draft_eval(c, uid, od, recs, excluded):
    """초안 하나의 채워질 건수, 분류 못 함 건수, 견본 3건 — evaluate 만 부른다(쓰지 않는다)."""
    d = od["draft_doc"] or {}
    route = (d.get("policy") or {}).get("route")
    out = {"object_id": od["id"], "proposal_id": od["draft_id"], "key": d.get("key"), "label": d.get("label"),
           "has_route": route is not None, "would_fill": 0, "partial": 0, "samples": []}
    if route is None:
        return out
    try:
        nr = check_route(route, d.get("fields") or [], d.get("key"), d.get("semantic_kind"))
    except RouteInvalid:
        return out
    fields = d.get("fields") or []
    for rec in recs:
        for u in evaluate(rec, nr, fields):
            if (od["id"], rec["id"], u["unit_key"]) in excluded:
                continue
            if u["state"] == "exact":
                out["would_fill"] += 1
                if len(out["samples"]) < 3:
                    out["samples"].append({"record_id": rec["id"], "unit_key": u["unit_key"], "title": u["title"][:QUOTE_MAX],
                                           "quote": rec["body"][u["start"]:u["end"]][:QUOTE_MAX]})
            else:
                out["partial"] += 1
    return out


def _unattached(c, uid):
    """어느 오브젝트에도 안 붙은 기록 수(출처별) — 대상 기록(target_sql) 최신 PROFILE_SCAN 편 가운데 routed 행도 항목 관계(item_links,
    기록에서 항목으로 또는 항목에서 기록으로)도 없는 기록. 본문 열을 읽지 않는다. profile 과 hint 가 이 함수 하나만 쓴다.
    반환 [{source, n}] (많은 순, 출처 이름 순)."""
    import db
    return db._all(c, f"""SELECT x.source, count(*) AS n FROM (
        SELECT r.id, r.source FROM records r WHERE r.user_id=%(uid)s AND {target_sql()} ORDER BY {db.RECORD_SORT} DESC, r.id DESC LIMIT %(lim)s) x
        WHERE NOT EXISTS (SELECT 1 FROM item_routes ir WHERE ir.user_id=%(uid)s AND ir.record_id=x.id AND ir.state='routed')
        AND NOT EXISTS (SELECT 1 FROM item_links l WHERE l.user_id=%(uid)s AND ((l.source_record_id=x.id AND l.target_item_id IS NOT NULL)
                        OR (l.target_record_id=x.id AND l.source_item_id IS NOT NULL)))
        GROUP BY x.source ORDER BY n DESC, x.source NULLS FIRST""", {"uid": uid, "lim": PROFILE_SCAN})


def hint(uid):
    """나 탭 요약용 가벼운 판정(화면을 열 때마다 부른다, 본문 열을 읽지 않는다) — {suggest, route_drafts}.
    suggest = profile 의 suggest 와 같은 정의(_unattached 합 > SUGGEST_MIN). route_drafts = 초안(draft_id 있음) 가운데
    draft_doc 의 policy 에 route 가 있는 오브젝트 수."""
    import db
    with db.tx() as c:
        un = sum(r["n"] for r in _unattached(c, uid))
        n = db._one(c, "SELECT count(*) AS n FROM object_defs WHERE user_id=%s AND draft_id IS NOT NULL "
                       "AND draft_doc->'policy' ? 'route'", (uid,))["n"]
    return {"suggest": un > SUGGEST_MIN, "route_drafts": n}


PROFILE_MAX_BYTES = 24 * 1024   # 대화 도구 응답 상한(agent 32 KiB) 안에 드는 profile 직렬화 상한(UTF-8 바이트)
_FIT_CHARS = (("headings", "text", 80), ("labels", "text", 40), ("keys", "text", 40), ("titles", "shape", 80), ("titles", "sample", 80))
_FIT_TRIM = ("titles", "keys", "labels", "headings")   # 넘치면 이 순서로 뒤(빈도 낮은 쪽)에서부터 줄인다


def _nbytes_json(v):
    return len(json.dumps(v, ensure_ascii=False).encode("utf-8"))


def fit(out, max_bytes=PROFILE_MAX_BYTES):
    """profile 을 대화 도구 응답 상한 안으로 결정적으로 줄인다(같은 입력 = 같은 결과). 글자 상한(머리 80, 라벨과 키 40, 제목 꼴과 견본 80,
    초안 견본 제목 80, quote 200) → 그래도 max_bytes 를 넘으면 titles, keys, labels, headings 를 뒤에서부터 → 초안 견본(3, 1, 0)
    → 수집 글 채널별, 활동 종류별, 안 붙은 기록 출처별(상위 10). objects, 초안 건수, unattached.count, suggest, route_guide, notice 는
    그대로. 줄였으면 "truncated": true 를 싣는다(안 줄였으면 키 없음)."""
    cut = False
    for key, field, n in _FIT_CHARS:
        for e in out[key]:
            if len(e[field]) > n:
                e[field], cut = e[field][:n], True
    for d in out["drafts"]:
        for smp in d["samples"]:
            for field, n in (("title", 80), ("quote", QUOTE_MAX)):
                if len(smp[field]) > n:
                    smp[field], cut = smp[field][:n], True
    for key in _FIT_TRIM:
        while out[key] and _nbytes_json(out) > max_bytes:
            out[key].pop()
            cut = True
    for keep in (1, 0):
        if _nbytes_json(out) <= max_bytes:
            break
        for d in out["drafts"]:
            if len(d["samples"]) > keep:
                d["samples"], cut = d["samples"][:keep], True
    if _nbytes_json(out) > max_bytes:
        for lst in (out["collected"]["by_channel"], out["activities"]["by_kind"], out["unattached"]["by_source"]):
            if len(lst) > 10:
                del lst[10:]
                cut = True
    if cut:
        out["truncated"] = True
    return out


def profile(uid, fit_chat=False):
    """structure_profile_get — 사용자 데이터 profile(사실만, 본문을 싣지 않는다: 머리 줄, 라벨, 키, 제목 줄, 견본 quote 200자만).
    읽는 기록 수 상한 PROFILE_SCAN(최신부터, 정렬 = db.RECORD_SORT). fit_chat=True(MCP op) = fit() 로 대화 도구 응답 상한 안에 줄인다.
    화면(web.py)은 기본값 False 로 줄이지 않은 값을 받는다."""
    import db
    with db.tx() as c:
        recs = _records(c, uid, limit=PROFILE_SCAN)
        defs = db._all(c, f"SELECT {db._DEF_COLS} FROM object_defs WHERE user_id=%s ORDER BY created_at, id", (uid,))
        n_items = {r["object_id"]: r["n"] for r in db._all(c, "SELECT object_id, count(*) AS n FROM items WHERE user_id=%s AND revision > 0 "
                                                              "AND archived_at IS NULL AND trashed_at IS NULL GROUP BY object_id", (uid,))}
        rc = object_counts(c, uid)
        by_src = _unattached(c, uid)
        excluded = {(r["object_id"], r["record_id"], r["unit_key"]) for r in db._all(
            c, "SELECT object_id, record_id, unit_key FROM item_routes WHERE user_id=%s AND state='excluded'", (uid,))}
        import imports
        coll = db._all(c, "SELECT i.data->>'channel' AS channel, count(*) AS n FROM items i JOIN object_defs o ON o.user_id=i.user_id "
                          "AND o.id=i.object_id WHERE i.user_id=%s AND o.key=%s AND i.revision > 0 AND i.archived_at IS NULL "
                          "AND i.trashed_at IS NULL GROUP BY 1 ORDER BY 2 DESC, 1", (uid, imports.COLLECTED_OBJECT_KEY))
        acts = db._all(c, "SELECT action, count(*) AS n FROM activities WHERE user_id=%s AND deleted_at IS NULL AND trashed_at IS NULL "
                          "GROUP BY action ORDER BY 2 DESC, 1", (uid,))
        drafts = [_draft_eval(c, uid, od, recs, excluded) for od in defs if od["draft_id"]]
    import contract
    import structure_svg   # 순수 모듈(html, json, math 만) — 화면 칩, 그래프와 같은 표시 범주. template 계보는 커스텀
    objects = []
    for od in defs:
        if od["revision"] == 0 or od["archived_at"]:
            continue
        k = rc.get(od["id"]) or {s: 0 for s in STATES}
        cat = structure_svg.ORIGIN_CATEGORY.get(contract.origin_of(od), "template")
        objects.append({"object_id": od["id"], "key": od["key"], "label": od["label"], "semantic_kind": od["semantic_kind"],
                        "group": "standard" if cat == "standard" else "custom",
                        "items": n_items.get(od["id"], 0), "auto_routed": k["routed"], "partial": k["partial"], "excluded": k["excluded"],
                        "has_route": "route" in (od["policy"] or {})})
    heads, labels, keys, titles = {}, {}, {}, {}
    for r in recs:
        t = (r["title"] or "").strip()
        if t:
            e = titles.setdefault(shape(t), {"records": set(), "count": 0, "sample": t[:QUOTE_MAX]})
            e["records"].add(r["id"])
            e["count"] += 1
        for _s, _e, line in _lines(r["body"] or ""):
            m = _HEAD_RE.fullmatch(line)
            if m:
                e = heads.setdefault(shape(m.group(2)), {"records": set(), "count": 0})
                e["records"].add(r["id"])
                e["count"] += 1
                continue
            _m, name = _label_of(line)
            if name:
                e = labels.setdefault(name[:QUOTE_MAX], {"records": set(), "count": 0})
                e["records"].add(r["id"])
                e["count"] += 1
                continue
            m = _KEY_RE.match(line)
            if m:
                e = keys.setdefault(m.group(1).strip()[:QUOTE_MAX], {"records": set(), "count": 0})
                e["records"].add(r["id"])
                e["count"] += 1
    un = sum(r["n"] for r in by_src)
    suggest = un > SUGGEST_MIN   # hint 와 같은 판정(같은 _unattached)
    out = {
        "kind": "structure_profile",
        "objects": objects,
        "unattached": {"count": un, "by_source": [{"source": r["source"], "count": r["n"]} for r in by_src]},
        "headings": [{"text": k, "records": len(v["records"]), "count": v["count"]} for k, v in _top(heads, 30)],
        "labels": [{"text": k, "records": len(v["records"])} for k, v in _top(labels, 20, 2)],
        "keys": [{"text": k, "records": len(v["records"])} for k, v in _top(keys, 20, 2)],
        "titles": [{"shape": k, "count": v["count"], "sample": v["sample"]} for k, v in _top(titles, 20, 2)],
        "collected": {"by_channel": [{"channel": r["channel"], "count": r["n"]} for r in coll]},
        "activities": {"by_kind": [{"kind": r["action"], "count": r["n"]} for r in acts]},
        "drafts": drafts,
        "route_guide": ROUTE_GUIDE,
        "suggest": suggest,
        "notice": (f"어느 오브젝트에도 안 붙은 기록이 {un}편 있어요. 추천할 구조가 있어요. " if suggest else "")
                  + "건수와 꼴은 서버가 원문에서 센 사실이에요. 이름과 필드는 사용자의 말에서 고르고, 초안은 definition_propose 로만 써요.",
    }
    return fit(out) if fit_chat else out
