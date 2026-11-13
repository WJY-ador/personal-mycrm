"""수집 글 어댑터 — feed · reactions · mail (명세 2026-11-12 수집 글 1단계).

서버로 가는 것(S1): 수집 글(collected-post/1)의 URL·제목 줄·메타·AI 요약과 분석, 그리고 명시된 내 행동(활동).
원문 본문 전체·작성자 소개·메일 주소·제목·스니펫은 PC 원문 저장소에만 둔다.

- feed      feed-queue JSONL → 수집 글 + 보관(kept)이면 save 활동
- reactions reactions JSONL → 수집 글(state kept) + like·comment·repost·reply 활동.
            Threads likes JSONL → 수집 글만(like 활동은 likes 어댑터 몫)
- mail      mail JSONL → 활동만(read·save·send·reply). 수집 글을 만들지 않는다

공통 규칙(골격 규칙 r3 T4 그대로):
- 파일 경로·행 번호로 이벤트 ID 를 만들지 않는다. 원천 ID(메일은 계정·주소·시각·제목·URL 의 다이제스트)가 중복 기준이다.
- 같은 중복 기준의 행이 여럿이면 파일의 마지막 행을 쓴다. 신원(fingerprint)은 원천 ID 만이라 URL·요약이 바뀌어도
  격리하지 않고 새 개정으로 갱신한다.
- 날짜는 KST 날짜로 자른다. 시간대를 모르는 시각은 쓰지 않는다(KST 로 임의 변환 금지).
- 활동의 행동 날짜(occurred_on)는 명시적 행동 시각(reacted_at, 보낸 메일의 ts)에서만. 수집 시각으로 대신하지 않는다.
- 행이 사라지거나 보관이 풀려도 활동 취소(retracted)를 만들지 않는다.
- 모델을 쓰지 않는다.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import re

from .. import contract, jcs
from .base import Adapter, AdapterError, CollectedPost, Observation, Quarantine

MAX_LINE_BYTES = 256 * 1024
KST = _dt.timezone(_dt.timedelta(hours=9))

# 채널 → 활동 provider(서버 activity_provider enum)
CHANNEL_PROVIDER = {"linkedin": "sns", "reddit": "sns", "threads": "sns", "kakao": "kakao", "blog": "web",
                    "web": "web"}
FEED_SEND_STATUSES = ("pending", "kept")
FEED_REMOVED_STATUSES = ("dropped", "expired", "excluded", "superseded")
REACTION_FORMATS = ("reactions", "threads_likes")

# ---- 가림(제목 줄·작성자 표시·AI 문장) ---------------------------------------------
# URL 은 post_url 에서만 보낸다. 다른 필드의 URL·이메일·로컬 경로 덩어리는 가린 뒤 보낸다(계약 차단 규칙과 같은 꼴을 덮는다).
URL_MASK, EMAIL_MASK, PATH_MASK = "‹링크›", "‹메일›", "‹경로›"
_TAIL = r"[^\s)\]}>\"'`|]*"
_MASKS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"), EMAIL_MASK),
    (re.compile(r"(?i)\b(?:https?|ftp|file|wss?)://" + _TAIL), URL_MASK),
    (re.compile(r"(?i)\bwww\.[a-z0-9-]+\.[a-z]{2,}" + _TAIL), URL_MASK),
    (re.compile(r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|kr|co|me|ai|app|dev|so)/" + _TAIL), URL_MASK),
    (re.compile(r"(?<![A-Za-z0-9._/~-])(?:~/|/Users/|/home/|/private/|/var/|/Volumes/|[A-Za-z]:\\)" + _TAIL
                + r"|\\\\[A-Za-z0-9._-]+\\" + _TAIL), PATH_MASK),
)


def mask(text: str) -> str:
    for pat, rep in _MASKS:
        text = pat.sub(rep, text)
    return text


def _blocked(text: str) -> bool:
    try:
        contract._scan_strings(text, "x")
    except contract.ContractError:
        return True
    return False


def clean_text(v, limit: int, *, single_line: bool):
    """가리고 자른 글. 비거나 가린 뒤에도 차단 꼴이 남으면 None."""
    if not isinstance(v, str):
        return None
    if single_line:
        v = " ".join(v.split())
    v = mask(v).strip()
    if not v:
        return None
    v = v[:limit].strip()
    if not v or _blocked(v) or "\x00" in v:
        return None
    return v


def title_of(text):
    """원문 첫 줄(빈 줄 건너뜀) 앞 200자. 요약하지 않는다."""
    if not isinstance(text, str):
        return None
    for line in text.splitlines():
        t = clean_text(line, contract.MAX_TITLE_CODEPOINTS, single_line=True)
        if t and _unmasked(t).strip():
            return t
        if line.strip():
            return None        # 첫 줄이 가린 뒤 비었거나(가림 표시만 남음) 못 쓰는 꼴 → 격리. 다음 줄로 넘어가지 않는다
    return None


def _unmasked(text: str) -> str:
    for m in (URL_MASK, EMAIL_MASK, PATH_MASK):
        text = text.replace(m, "")
    return text


def masked_count(fields: dict) -> int:
    """서버로 갈 필드(제목 줄·작성자 표시·AI 문장)에 든 가림 표시 수 — 실행 요약(counts masked)용."""
    vals = [fields.get("title"), fields.get("author_display")]
    ai = fields.get("ai") or {}
    vals += [ai.get(k) for k in contract.AI_TEXT_LIMITS] + list(ai.get("points") or [])
    return sum(v.count(m) for v in vals if isinstance(v, str) for m in (URL_MASK, EMAIL_MASK, PATH_MASK))


def post_url_of(v):
    if (isinstance(v, str) and v.startswith("https://") and len(v) > len("https://")
            and len(v) <= contract.MAX_POST_URL and not any(c.isspace() for c in v)):
        return v
    return None


# ---- 날짜 ------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?[ ]?(Z|[+-]\d{2}:?\d{2})$")


def kst_date(v):
    """YYYY-MM-DD 는 그대로, 오프셋 있는 시각(Z·+09:00·+0900·소수 초)은 KST 날짜로. 오프셋 없는 시각·이상한 값은 None.
    Python 3.9 의 fromisoformat 은 Z·+0900 을 못 읽어 직접 푼다."""
    if isinstance(v, str):
        v = v.strip()
        if _DATE_RE.match(v):
            try:
                _dt.date.fromisoformat(v)
            except ValueError:
                return None
            return v
        m = _DT_RE.match(v)
        if not m:
            return None
        y, mo, d, hh, mi, ss, off = m.groups()
        if off == "Z":
            tz = _dt.timezone.utc
        else:
            sign = 1 if off[0] == "+" else -1
            digits = off[1:].replace(":", "")
            oh, om = int(digits[:2]), int(digits[2:])
            if oh > 23 or om > 59:
                return None
            tz = _dt.timezone(sign * _dt.timedelta(hours=oh, minutes=om))
        try:
            t = _dt.datetime(int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), tzinfo=tz)
        except ValueError:
            return None
        return t.astimezone(KST).date().isoformat()
    if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
        sec = v / 1000.0 if v > 1e11 else float(v)      # 밀리초 epoch 판별
        try:
            return _dt.datetime.fromtimestamp(sec, KST).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    return None


# ---- 축·AI ----------------------------------------------------------------------
def map_axes(codes, axes_map: dict) -> list:
    """축 코드 → 축 항목 ID. 매핑에 없는 코드는 버린다. 중복 제거, 최대 10."""
    out = []
    if not isinstance(codes, list):
        return out
    for c in codes:
        item = axes_map.get(c) if isinstance(c, str) else None
        if isinstance(item, str) and item not in out:
            out.append(item)
    return out[:contract.MAX_AXES]


def ai_of(row: dict):
    """원천 grade·summary·long{asis,tobe,ops,points} → ai 객체. 비면 None. 한도를 넘는 글은 자른다."""
    ai = {}
    g = row.get("grade")
    if g in contract.AI_GRADES:
        ai["grade"] = g
    long = row.get("long") if isinstance(row.get("long"), dict) else {}
    for key, src in (("summary", row.get("summary")), ("as_is", long.get("asis")), ("to_be", long.get("tobe")),
                     ("ops", long.get("ops"))):
        t = clean_text(src, contract.AI_TEXT_LIMITS[key], single_line=False)
        if t:
            ai[key] = t
    pts = []
    raw_pts = long.get("points") if isinstance(long.get("points"), list) else []
    for p in raw_pts:
        t = clean_text(p, contract.MAX_AI_POINT, single_line=False)
        if t:
            pts.append(t)
    if pts:
        ai["points"] = pts[:contract.MAX_AI_POINTS]
    return ai or None


# ---- JSONL ----------------------------------------------------------------------
def read_jsonl(path: str, label: str):
    """(행 dict) 또는 Quarantine 를 낸다."""
    try:
        fh = open(path, "rb")
    except OSError:
        raise AdapterError(label + " input not readable") from None
    with fh:
        for lineno, line in enumerate(fh, 1):
            if not line.strip():
                continue
            if len(line) > MAX_LINE_BYTES:
                yield Quarantine("line-too-large", f"{label}:{lineno}:{len(line)}")
                continue
            try:
                row = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                yield Quarantine("bad-json", line.decode("utf-8", "replace"))
                continue
            if not isinstance(row, dict):
                yield Quarantine("not-object", line.decode("utf-8", "replace"))
                continue
            yield row


def _group(items, key_of, fp_of):
    """같은 중복 기준끼리 묶는다. 신원이 다르면 격리, 같으면 마지막 행. 반환 [(key, rows)] · Quarantine."""
    groups, order = {}, []
    for it in items:
        if isinstance(it, Quarantine):
            yield it
            continue
        key = key_of(it)
        if key is None:
            yield Quarantine("no-event-id", json.dumps(it, ensure_ascii=False, sort_keys=True))
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it)
    for key in order:
        rows = groups[key]
        if len({fp_of(r) for r in rows}) != 1:
            yield Quarantine("ambiguous-duplicate", key)
            continue
        yield key, rows


def _abs_path(section: dict, key: str, label: str) -> str:
    p = section.get(key)
    if not isinstance(p, str) or not p or not os.path.isabs(os.path.expanduser(p)):
        raise AdapterError(f"{label}.{key} must be an absolute path in config")
    return os.path.expanduser(p)


def _str_map(section: dict, key: str, label: str) -> dict:
    m = section.get(key) or {}
    if not isinstance(m, dict) or not all(isinstance(k, str) and (v is None or isinstance(v, str))
                                          for k, v in m.items()):
        raise AdapterError(f"{label}.{key} must be an object of strings")
    return {k: v for k, v in m.items() if v is not None}


def _post_fields(*, channel, collected_on, title, state, post_url, author, posted_on, axes, ai) -> dict:
    f = {"channel": channel, "collected_on": collected_on, "title": title, "state": state}
    if post_url:
        f["post_url"] = post_url
    a = clean_text(author, contract.MAX_AUTHOR_DISPLAY, single_line=True)
    if a:
        f["author_display"] = a
    if posted_on:
        f["posted_on"] = posted_on
    if axes:
        f["axes"] = list(axes)
    if ai:
        f["ai"] = ai
    return f


def _activity(key, fp, row, action, occurred_on, observed_on, provider, axes) -> Observation:
    return Observation(dedupe_key=f"{key}#{action}", fingerprint=fp, raw=row, action=action, state="active",
                       occurred_on=occurred_on, observed_on=observed_on, provider=provider, people=[],
                       axes=list(axes))


# ---- feed -----------------------------------------------------------------------
class FeedAdapter(Adapter):
    name = "feed"
    kind = "collected_post"
    transform_version = "board-feed/1"          # 활동(save). 수집 글은 collected-post/1
    RULES = {
        "pc_only": "원문 본문 전체·작성자 소개",
        "to_server": "수집 글(URL·제목 줄·작성자 표시·날짜·축·AI 요약과 분석). 보관(kept)이면 save 활동",
        "forbidden": "큐에 있다는 이유로 read 생성 금지. 버림·만료·자동제외는 새로 올리지 않는다",
    }

    def check_config(self, section: dict) -> None:
        _abs_path(section, "input_path", "feed")
        chans = _str_map(section, "channels", "feed")
        for v in chans.values():
            if v not in contract.CHANNELS:
                raise AdapterError("feed.channels values must be channels")
        _str_map(section, "axes_map", "feed")

    def collect(self, section: dict):
        self.check_config(section)
        path = _abs_path(section, "input_path", "feed")
        chans = _str_map(section, "channels", "feed")
        axes_map = _str_map(section, "axes_map", "feed")

        def key_of(r):
            rid = r.get("id")
            return "feed:" + rid if isinstance(rid, str) and rid.strip() else None

        def fp_of(r):
            # 신원 = 원천 ID 만. URL 은 나중에 채워지거나 바뀔 수 있어 넣지 않는다(바뀌면 새 개정으로 갱신)
            return jcs.sha256_hex(["feed", r.get("id")])

        for g in _group(read_jsonl(path, "feed"), key_of, fp_of):
            if isinstance(g, Quarantine):
                yield g
                continue
            key, rows = g
            yield from self._one(key, rows[-1], fp_of(rows[-1]), chans, axes_map)

    def _one(self, key, row, fp, chans, axes_map):
        status = row.get("status")
        if status in FEED_SEND_STATUSES:
            state = status
        elif status in FEED_REMOVED_STATUSES:
            state = "removed"
        else:
            yield Quarantine("unknown-status", key)
            return
        src = row.get("source")
        channel = chans.get(src if isinstance(src, str) else "")
        collected_on = kst_date(row.get("collected_at"))
        title = title_of(row.get("text"))
        bad = ("unmapped-channel" if channel not in contract.CHANNELS else
               "no-collected-date" if collected_on is None else "no-title" if title is None else None)
        if bad:
            if state != "removed":      # 버린 글의 형식 오류는 격리하지 않는다(올릴 대상이 아니다)
                yield Quarantine(bad, key)
            return
        axes = map_axes(row.get("axes"), axes_map)
        fields = _post_fields(channel=channel, collected_on=collected_on, title=title, state=state,
                              post_url=post_url_of(row.get("post_url")), author=row.get("author"),
                              posted_on=kst_date(row.get("published_at")), axes=axes, ai=ai_of(row))
        yield CollectedPost(dedupe_key=key, fingerprint=fp, raw=row, fields=fields,
                            only_if_sent=(state == "removed"))
        if state == "kept":
            yield _activity(key, fp, row, "save", None, collected_on, CHANNEL_PROVIDER[channel], axes)


# ---- reactions ------------------------------------------------------------------
class ReactionsAdapter(Adapter):
    name = "reactions"
    kind = "collected_post"
    transform_version = "board-reactions/1"     # 활동. 수집 글은 collected-post/1
    RULES = {
        "pc_only": "원문 본문 전체·인용·상대 정보",
        "to_server": "반응한 글을 수집 글(state kept)로. 명시된 좋아요·댓글·리포스트·답장 → like/comment/repost/reply",
        "self_text": "내 반응 문장은 이 어댑터가 보내지 않는다(내 글은 별도 경로)",
    }

    def check_config(self, section: dict) -> None:
        inputs = section.get("inputs")
        if not isinstance(inputs, list) or not inputs:
            raise AdapterError("reactions.inputs must be a non-empty list in config")
        for i, inp in enumerate(inputs):
            if not isinstance(inp, dict):
                raise AdapterError(f"reactions.inputs[{i}] must be an object")
            _abs_path(inp, "path", f"reactions.inputs[{i}]")
            if inp.get("format") not in REACTION_FORMATS:
                raise AdapterError(f"reactions.inputs[{i}].format must be reactions or threads_likes")
            if inp.get("channel") not in contract.CHANNELS or CHANNEL_PROVIDER[inp["channel"]] not in \
                    contract.TRANSFORM_ACTIVITY[self.transform_version]["providers"]:
                raise AdapterError(f"reactions.inputs[{i}].channel must be a channel other than kakao")
        km = _str_map(section, "kind_actions", "reactions")
        for v in km.values():
            if v not in contract.TRANSFORM_ACTIVITY["board-reactions/1"]["actions"]:
                raise AdapterError("reactions.kind_actions values must be like, comment, repost or reply")

    def collect(self, section: dict):
        self.check_config(section)
        km = _str_map(section, "kind_actions", "reactions")
        for inp in section["inputs"]:
            yield from self._input(os.path.expanduser(inp["path"]), inp["format"], inp["channel"], km)

    def _input(self, path, fmt, channel, km):
        url_key = "original_url" if fmt == "threads_likes" else "post_url"

        def key_of(r):
            rid = r.get("id")
            return f"{fmt}:{rid}" if isinstance(rid, str) and rid.strip() else None

        def fp_of(r):
            return jcs.sha256_hex(["reactions", fmt, r.get("id")])     # 신원 = 원천 ID 만(feed 와 같은 이유)

        provider = CHANNEL_PROVIDER[channel]
        for g in _group(read_jsonl(path, "reactions"), key_of, fp_of):
            if isinstance(g, Quarantine):
                yield g
                continue
            key, rows = g
            row = rows[-1]
            fp = fp_of(row)
            collected_on = kst_date(row.get("first_seen" if fmt == "threads_likes" else "collected_at"))
            if collected_on is None:
                yield Quarantine("no-collected-date", key)
                continue
            title = title_of(row.get("text"))
            if title is None:
                yield Quarantine("no-title", key)
                continue
            fields = _post_fields(channel=channel, collected_on=collected_on, title=title, state="kept",
                                  post_url=post_url_of(row.get(url_key)), author=row.get("author"),
                                  posted_on=kst_date(row.get("posted_at")), axes=[], ai=None)
            yield CollectedPost(dedupe_key=key, fingerprint=fp, raw=row, fields=fields)
            if fmt == "threads_likes":
                # Threads 좋아요 파일 — 수집 글만 낸다. like 활동은 likes 어댑터 몫(같은 파일을 둘이 읽어도 겹치지 않게)
                continue
            seen = set()
            for r in rows:
                k = r.get("kind")
                action = km.get(k) if isinstance(k, str) else None
                if action is None:
                    yield Quarantine("unmapped-kind", key)
                    continue
                if action in seen:
                    continue
                seen.add(action)
                yield _activity(key, fp, r, action, kst_date(r.get("reacted_at")), collected_on, provider, [])


# ---- mail -----------------------------------------------------------------------
class MailAdapter(Adapter):
    name = "mail"
    kind = "activity"
    transform_version = "board-mail/1"
    RULES = {
        "pc_only": "메일 원문·제목·스니펫·주소·보낸 사람·URL·계정",
        "to_server": "명시된 읽음(unread=false)·보관(saved)·발송(sent)·답장(replied) → read/save/send/reply",
        "forbidden": "수신·목록 존재만으로 사용자 행동 생성 금지. 수집 글을 만들지 않는다",
    }

    def check_config(self, section: dict) -> None:
        _abs_path(section, "input_path", "mail")

    def collect(self, section: dict):
        self.check_config(section)
        path = _abs_path(section, "input_path", "mail")

        def key_of(r):
            # 메일엔 원천 ID 가 없다 — URL 이 메시지마다 다르다는 보장이 없어 계정·보낸 주소·시각·제목·URL 을 함께
            # 다이제스트한다. 평문 주소를 키에 두지 않는다
            parts = [r.get(k) for k in ("acct", "from_email", "ts", "subject", "url")]
            if all(p is None or p == "" for p in parts):
                return None
            try:
                return "mail:" + jcs.sha256_hex(parts)
            except (TypeError, ValueError):
                return None

        def fp_of(r):
            return key_of(r)

        for g in _group(read_jsonl(path, "mail"), key_of, fp_of):
            if isinstance(g, Quarantine):
                yield g
                continue
            key, rows = g
            row = rows[-1]
            observed_on = kst_date(row.get("first_seen"))
            acts = []
            if row.get("unread") is False:
                acts.append(("read", None))
            if row.get("saved") is True:
                acts.append(("save", None))
            if row.get("sent") is True:
                acts.append(("send", kst_date(row.get("ts"))))     # 보낸 메일의 ts = 보낸 시각
            if row.get("replied") is True:
                acts.append(("reply", None))
            for action, occurred_on in acts:
                yield _activity(key, key, row, action, occurred_on, observed_on, "mail", [])


# ---- feed 판별 되돌림(write_back, 명세 2026-11-13 4절) ---------------------------------
# 웹에서 사용자가 보관·버림한 수집 글을 feed 입력 파일(feed-queue JSONL)의 그 행에 되돌려 쓴다. 대시보드·수집기도 같은 파일을
# 잠금 없이 원자 교체(os.replace)로 쓴다 — 같은 방식으로 쓰고, 읽은 뒤 파일이 바뀌었으면 한 번 다시 읽어 재시도한다.
# 바꾸는 것: 그 id 의 마지막 행(어댑터가 읽는 행)이 pending 일 때만 status·decided_at 두 필드. 다른 줄은 원래 바이트 그대로 둔다.
WRITE_BACK_STATES = ("kept", "dropped")


class FileChanged(RuntimeError):
    """다시 읽어 재시도한 뒤에도 쓰기 직전에 파일이 바뀌었다(다른 프로그램이 쓰는 중)."""


def _file_sig(path: str):
    s = os.stat(path)
    return (s.st_mtime_ns, s.st_size, s.st_ino)


def _plan_write_back(data: bytes, changes: dict):
    """(새 바이트 | None, applied, skipped_not_pending, missing). 변경이 없으면 새 바이트 None."""
    lines = data.splitlines(keepends=True)
    last = {}
    for i, line in enumerate(lines):
        if not line.strip() or len(line) > MAX_LINE_BYTES:
            continue
        try:
            row = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            continue
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"] in changes:
            last[row["id"]] = (i, row)
    applied = skipped = 0
    for rid, (state, decided_at) in changes.items():
        if rid not in last:
            continue
        i, row = last[rid]
        if row.get("status") != "pending":
            skipped += 1            # 대시보드에서 먼저 판별했거나 만료된 행 — 건드리지 않는다
            continue
        row["status"], row["decided_at"] = state, decided_at
        line = lines[i]
        eol = line[len(line.rstrip(b"\r\n")):]
        lines[i] = _dump_like(row, line) + eol
        applied += 1
    missing = len(changes) - len(last)
    return (b"".join(lines) if applied else None), applied, skipped, missing


def _dump_like(row: dict, original: bytes) -> bytes:
    """바꾼 행을 원래 줄의 꼴대로 — 원래 줄이 ASCII 뿐이면 \\u 이스케이프(ensure_ascii), 아니면 UTF-8 그대로.
    짝 없는 서로게이트(수집기가 이모지 중간에서 자른 글)는 UTF-8 로 쓸 수 없어 이스케이프로 쓴다."""
    if original.isascii():
        return json.dumps(row).encode("ascii")
    try:
        return json.dumps(row, ensure_ascii=False).encode("utf-8")
    except UnicodeEncodeError:
        return json.dumps(row).encode("ascii")


def _replace_keep_mode(path: str, data: bytes, mode: int) -> None:
    """같은 폴더 임시 파일 → fsync → os.replace. 원래 파일 권한을 유지한다(osutil.atomic_write 는 0600 으로 만든다)."""
    import tempfile
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".tmp-writeback-", dir=d)
    try:
        if os.name != "nt":
            os.fchmod(fd, mode & 0o7777)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_back_feed(path: str, changes: dict, *, before_replace=None) -> dict:
    """changes: 원천 id → (status kept|dropped, decided_at). 반환 {applied, skipped_not_pending, missing, retried}.
    파일을 못 읽으면 OSError, 재시도 뒤에도 파일이 바뀌면 FileChanged(아무것도 쓰지 않음).
    before_replace: 시험용 — 계획을 세운 뒤 바뀜 확인 직전에 부른다."""
    for rid, (state, decided_at) in changes.items():
        if state not in WRITE_BACK_STATES or not isinstance(rid, str) or not isinstance(decided_at, str):
            raise ValueError("write_back change")
    real = os.path.realpath(path)
    retried = 0
    for attempt in (0, 1):
        sig = _file_sig(real)
        mode = os.stat(real).st_mode
        with open(real, "rb") as f:
            data = f.read()
        new, applied, skipped, missing = _plan_write_back(data, changes)
        out = {"applied": applied, "skipped_not_pending": skipped, "missing": missing, "retried": retried}
        if new is None:
            return out
        if before_replace is not None:
            before_replace(attempt)
        if _file_sig(real) != sig:
            if attempt == 0:
                retried = 1
                continue
            raise FileChanged("feed input changed while writing back")
        _replace_keep_mode(real, new, mode)
        return out
    raise FileChanged("feed input changed while writing back")     # 도달하지 않음
