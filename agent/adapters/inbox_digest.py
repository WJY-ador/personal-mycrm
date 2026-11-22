"""수집 인박스 요약 → inbox-digest/1 (2026-11-22 루틴판 고칠 것 명세 4-2). 무인 모델 예외 하나 — 조건은 agent/README.md.

- 입력 = feed JSONL(설정 adapters.feed.input_path)의 대기(status pending) 수집 글 중 수집일 최신 60개. 항목마다
  {post_url, 제목 줄, 작성자 표시, 채널, 축 코드, ai.grade, ai.summary} 만. 원문 본문은 보내지 않는다(제목 줄 = 첫 줄, 수집 글과 같은 규칙).
  글자 값(제목 줄·작성자 표시·AI 요약)은 항목당 합쳐 300자 안으로 자른다. post_url 은 대조용이라 자르지 않는다 — https 가 아니거나
  300자를 넘거나 계약 차단 꼴(이메일·경로)이 있으면 항목을 뺀다. feed 어댑터가 보내지 않는 source(채널 매핑 null·없음)도 뺀다.
- 돌릴 조건(전부): inbox_digest.enabled true(기본 false, 동의) · summary.cli_path 있음 · 장치 허용 규칙에 inbox-digest/1 ·
  입력 집합 해시가 지난 요약과 다름 · KST 하루 6회 이하 · 600초 종료 기준 남은 시간 220초 이상. 하나라도 안 맞으면 skipped 에 이유.
- 모델 호출은 agent/summary.py 의 격리 그대로(도구·MCP 끔, 1턴, 최소 환경변수, 빈 작업 폴더, 토큰 안 넘김). 시간 제한 150초.
- 출력 검증(키·길이·post_url 이 입력에 있는지) 실패면 버린다. 한 글이 여러 주제에 있으면 앞 주제에만 둔다.
- 로컬 계정 식별자 대조(runner.stage_self_text)는 제목·body(주제 이름·문장)만 본다 — post_url 은 이미 수집 글로 가는 남의 글 주소다. 같은 입력이 그날 실패했으면 다시 부르지 않는다(입력이 바뀌면 다시).
- 올리기 = self_text 장치 업로드, 원본 하나(중복 기준 「inbox-digest」) — 새 요약은 같은 원본의 새 개정. body = 「이름: 문장」 줄(URL 없음),
  digest 키 = {themes:[{name, line, post_urls}], input_n, made_at}. 서버가 post_url 을 항목 id 로 바꾼다.
- 실행 결과에는 수와 이유만 남긴다(URL·제목·경로 없음). 시험은 모의 실행기로만 한다.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time

from .. import contract, jcs, osutil, runner as _runner, summary as _summary
from . import collected as _collected
from .base import Quarantine

TRANSFORM = contract.INBOX_DIGEST_TRANSFORM
ADAPTER = "inbox-digest"
DEDUPE_KEY = "inbox-digest"
TITLE = "인박스 요약"
MAX_INPUT = contract.DIGEST_MAX_INPUT        # 60
ITEM_TEXT_LIMIT = 300                        # 항목당 글자 값(제목 줄·작성자 표시·AI 요약) 합계
TITLE_LIMIT, AUTHOR_LIMIT = 120, 40
DAILY_LIMIT = 6
RUN_KILL_SEC = 600.0                         # 데스크톱 앱이 run-once 를 끊는 시각(desktop/src/main.cjs)
MIN_LEFT_SEC = 220.0                         # 남은 시간이 이보다 적으면 모델을 부르지 않는다
MODEL_TIMEOUT_SEC = 150.0
SHA_CURSOR = "inbox_digest_sha"              # 지난번 올린 요약의 입력 해시
FAILED_CURSOR = "inbox_digest_failed"        # "<KST 날짜>:<입력 해시>" — 그날 그 입력은 다시 부르지 않는다
DAY_CURSOR = "inbox_digest_day:"             # + KST 날짜 → 그날 모델 호출 수

PROMPT = (
    "You group the user's pending reading inbox given on standard input as a JSON array of items "
    "(post_url, title, author, channel, axes, grade, summary). Return ONLY a JSON object "
    "{\"themes\": [{\"name\": string, \"line\": string, \"post_urls\": [string]}]} with 3 to 7 themes, "
    "written in the same language as the items. name: at most 20 characters. line: one sentence, at most 80 characters. "
    "post_urls: the post_url values of the items in that theme, copied exactly from the input. "
    "Use only facts present in the input. Do not put URLs, e-mail addresses, or file paths in name or line. "
    "Do not use tools."
)


class DigestError(RuntimeError):
    pass


def _cut(text, limit: int):
    return text[:limit].rstrip() if isinstance(text, str) else None


def _url_sendable(url: str) -> bool:
    try:
        contract._scan_strings(url, "post_url", ("post_url",))
    except contract.ContractError:
        return False
    return True


def build_inputs(feed_path: str, chans: dict) -> list:
    """feed JSONL → 대기 글 항목(수집일 최신 MAX_INPUT 개). 같은 id 는 파일의 마지막 행(feed 어댑터와 같다). 결정적."""
    last, order = {}, []
    for pos, row in enumerate(_collected.read_jsonl(feed_path, "feed")):
        if isinstance(row, Quarantine):
            continue
        rid = row.get("id")
        if not (isinstance(rid, str) and rid.strip()):
            continue
        if rid not in last:
            order.append(rid)
        last[rid] = (pos, row)
    picked = []
    for rid in order:
        pos, row = last[rid]
        if row.get("status") != "pending":
            continue
        url = _collected.post_url_of(row.get("post_url"))
        day = _collected.kst_date(row.get("collected_at"))
        title = _collected.title_of(row.get("text"))
        src = row.get("source")
        channel = chans.get(src if isinstance(src, str) else "")
        # feed 어댑터가 서버로 보내는 글만(채널 매핑 null·없음 = 보내지 않는 source). URL 은 계약 차단 꼴(이메일·경로)이 없고 300자 안
        if (url is None or day is None or title is None or channel not in contract.CHANNELS
                or len(url) > contract.DIGEST_MAX_URL or not _url_sendable(url)):
            continue
        ai = _collected.ai_of(row) or {}
        title = _cut(title, TITLE_LIMIT)
        author = _cut(_collected.clean_text(row.get("author"), contract.MAX_AUTHOR_DISPLAY, single_line=True),
                      AUTHOR_LIMIT)
        left = ITEM_TEXT_LIMIT - len(title) - len(author or "")
        summary = _cut(ai.get("summary"), max(0, left)) or None
        item = {"post_url": url, "title": title, "author": author, "channel": channel,
                "axes": _collected.axis_codes_of(row), "grade": ai.get("grade"), "summary": summary}
        picked.append(((day, pos), item))
    picked.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in picked[:MAX_INPUT]]


def input_sha(items: list) -> str:
    return jcs.sha256_hex({"transform": TRANSFORM, "items": items})


def _strip_fence(text: str) -> str:
    t = text.strip()
    if t.startswith("```") and t.endswith("```"):
        t = t[3:-3]
        if t.startswith("json"):
            t = t[4:]
    return t.strip()


def parse_output(stdout: bytes, urls: set) -> list:
    """claude -p --output-format json 결과 → themes. 키·길이·post_url(입력에 있는 것만) 검증. 틀리면 DigestError(이유 낱말)."""
    if len(stdout) > _summary.MAX_OUTPUT_BYTES:
        raise DigestError("output-too-large")
    try:
        outer = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise DigestError("output-not-json") from None
    if not isinstance(outer, dict) or outer.get("is_error") is True or not isinstance(outer.get("result"), str):
        raise DigestError("output-shape")
    try:
        inner = json.loads(_strip_fence(outer["result"]))
    except ValueError:
        raise DigestError("result-not-json") from None
    if not isinstance(inner, dict) or set(inner) != {"themes"} or not isinstance(inner["themes"], list):
        raise DigestError("result-shape")
    themes = inner["themes"]
    if not contract.DIGEST_MIN_THEMES <= len(themes) <= contract.DIGEST_MAX_THEMES:
        raise DigestError("theme-count")
    out, seen = [], set()
    for t in themes:
        if not isinstance(t, dict) or set(t) != {"name", "line", "post_urls"}:
            raise DigestError("theme-shape")
        name, line, pu = t["name"], t["line"], t["post_urls"]
        if not (isinstance(name, str) and isinstance(line, str) and isinstance(pu, list)):
            raise DigestError("theme-shape")
        name, line = " ".join(name.split()), " ".join(line.split())
        if not name or len(name) > contract.DIGEST_MAX_NAME:
            raise DigestError("name-length")
        if not line or len(line) > contract.DIGEST_MAX_LINE:
            raise DigestError("line-length")
        if _collected._blocked(name) or _collected._blocked(line):
            raise DigestError("blocked-text")
        if not pu or not all(isinstance(u, str) and u in urls for u in pu):
            raise DigestError("unknown-url")
        keep = [u for u in dict.fromkeys(pu) if u not in seen]    # 한 글은 앞 주제에만 — body 길이와 글 수 칩을 맞춘다
        if not keep:
            raise DigestError("empty-theme")
        seen.update(keep)
        out.append({"name": name, "line": line, "post_urls": keep})
    return out


def body_of(themes: list) -> str:
    """사람이 읽는 본문 — 주제마다 「이름: 문장」 한 줄. URL 은 넣지 않는다(digest 키에만)."""
    return "\n".join(f"{t['name']}: {t['line']}" for t in themes)


def _day_count(st, day: str) -> int:
    try:
        return int(st.cursor_get(DAY_CURSOR + day) or 0)
    except ValueError:
        return DAILY_LIMIT


def collect(st, cfg: dict, counts: dict | None = None, *, paths, exec_runner=None, process_started: float | None = None,
            clock=time.monotonic, now=osutil.kst_now) -> dict:
    """조건이 맞으면 요약 하나를 전송 대기로 만든다. 반환 {"skipped", "input_n", "themes", "staged", "failed"} — 값·경로 없음.
    process_started = 이 실행이 시작된 clock 값(앱의 600초 종료 기준). 없으면 지금으로 본다."""
    out = {"skipped": None, "input_n": 0, "themes": 0, "staged": False, "failed": None}
    sec = cfg.get("inbox_digest") or {}
    if not (isinstance(sec, dict) and sec.get("enabled") is True):
        out["skipped"] = "disabled"
        return out
    cli_path = (cfg.get("summary") or {}).get("cli_path")
    if not (isinstance(cli_path, str) and os.path.isabs(cli_path)):
        out["skipped"] = "no-cli"
        return out
    allowed = cfg.get("allowed_transforms")
    if allowed is not None and TRANSFORM not in allowed:
        out["skipped"] = "policy"                      # 서버가 이 변환을 모른다(옛 서버·허용 안 됨)
        return out
    feed = (cfg.get("adapters") or {}).get("feed") or {}
    feed_path = feed.get("input_path")
    if not feed.get("enabled") or not (isinstance(feed_path, str) and os.path.isabs(os.path.expanduser(feed_path))):
        out["skipped"] = "no-feed"
        return out
    try:
        items = build_inputs(os.path.expanduser(feed_path), feed.get("channels") or {})
    except _collected.AdapterError:
        out["skipped"] = "feed-unreadable"
        return out
    out["input_n"] = len(items)
    if len(items) < contract.DIGEST_MIN_THEMES:
        out["skipped"] = "too-few"                     # 주제 3개(한 글은 한 주제에만)를 만들 수 없다 — 모델을 부르지 않는다
        return out
    sha = input_sha(items)
    if st.cursor_get(SHA_CURSOR) == sha:
        out["skipped"] = "unchanged"
        return out
    ev = st.event_get(ADAPTER, DEDUPE_KEY)
    if ev is not None and st.has_open_revision(ev["original_id"]):
        out["skipped"] = "waiting"                     # 앞 요약이 아직 전송 대기 — 모델을 부르지 않는다(다음 실행에 다시 본다)
        return out
    day = now().date().isoformat()
    if st.cursor_get(FAILED_CURSOR) == f"{day}:{sha}":
        out["skipped"] = "failed-today"
        return out
    if _day_count(st, day) >= DAILY_LIMIT:
        out["skipped"] = "daily-limit"
        return out
    started = clock() if process_started is None else process_started
    if RUN_KILL_SEC - (clock() - started) < MIN_LEFT_SEC:
        out["skipped"] = "time"
        return out

    st.cursor_set(DAY_CURSOR + day, str(_day_count(st, day) + 1))   # 부르기 전에 센다 — 도중에 끊겨도 하루 몫을 넘지 않게
    runner_ = exec_runner or _summary._subprocess_runner
    data = json.dumps(items, ensure_ascii=False).encode("utf-8")
    os.makedirs(paths.summary_work, exist_ok=True)

    def fail(reason: str) -> dict:
        st.cursor_set(FAILED_CURSOR, f"{day}:{sha}")
        out["failed"] = reason
        return out
    try:
        code, so, se = runner_(_summary.build_argv(cli_path, PROMPT), stdin_bytes=data,
                               env=_summary.child_env(paths, cli_path), cwd=paths.summary_work,
                               timeout=MODEL_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return fail("timeout")
    except OSError:
        return fail("exec")
    if code != 0:
        text = ((so or b"")[:4096] + b" " + (se or b"")[:4096]).decode("utf-8", "replace")
        return fail("login" if _summary._LOGIN_RE.search(text) else f"exit-{code}")
    try:
        themes = parse_output(so or b"", {it["post_url"] for it in items})
    except DigestError as e:
        return fail(str(e))
    made_at = now().replace(microsecond=0).isoformat()
    digest = {"themes": themes, "input_n": len(items), "made_at": made_at}
    fields = {"title": TITLE, "body": body_of(themes), "source_created_at": made_at, "digest": digest}
    try:
        contract._validate_inbox_digest(digest)
    except contract.ContractError:
        return fail("contract")
    counts = counts if counts is not None else _runner.new_counts()
    execution = "attended" if cfg.get("_execution") == "attended" else "unattended"
    ok = _runner.stage_self_text(st, cfg, adapter_name=ADAPTER, dedupe_key=DEDUPE_KEY, fingerprint=DEDUPE_KEY,
                                 kind="self_text", transform_version=TRANSFORM, execution=execution, fields=fields,
                                 counts=counts, identity_text=fields["title"] + " " + fields["body"])
    if not ok:
        return fail("not-staged")                       # 격리(로컬 계정 식별자 대조 등) — 같은 날 같은 입력은 다시 부르지 않는다
    st.cursor_set(SHA_CURSOR, sha)
    out.update(themes=len(themes), staged=True)
    return out
