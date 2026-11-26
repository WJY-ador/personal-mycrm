"""세션 정리 → 내 글(승인 대기) — 사람이 지정한 세션 정리 폴더의 `YYYY-MM-DD.md` 만 읽는다. 모델을 쓰지 않는다(결정적 변환).

정본: notes 「2026-11-04_세션정리-결정본인-구현계획」 §2 (원작자 A안).
- 입력 = 설정 session_wrap.folders(절대 경로 목록) 바로 아래의 `YYYY-MM-DD.md` 파일만. 하위 폴더·숨김·심링크·폴더 밖 실경로는 건너뛴다.
  폴더 목록은 PC 로컬 설정에만 둔다(레포·문서에 실제 경로를 적지 않는다).
- 묶음 하나 = `## 제목` 줄부터 다음 `## `·`# `·`---` 줄 앞까지. 묶음 하나가 기록 하나(제목 = 제목 줄, 본문 = 문단).
  `### 소제목`(옛 4단 양식)은 본문에 그대로 둔다. 머리말(frontmatter)·`# 세션 스토리` 머리줄·첫 `##` 앞 글은 보내지 않는다.
- `→ 남긴 곳:` 줄은 뺀다 — 정리 글을 어디에 남겼는지 가리키는 줄이지 내 판단이 아니다(경로가 섞이면 계약이 본문을 막는다).
  `정본 후보:` 줄은 남긴다 — 내 말 한 줄이라 판단 후보의 재료다. 그 밖의 `→` 줄도 건드리지 않는다.
- 원본 날짜 = 파일 이름의 날짜(source_date). 변환 버전 session-wrap/1(kind self_text) — 서버는 승인 뒤
  self·structured·mixed·「내 결정」 표시로 기록한다(서버 imports.inbox_approve).
- 중복 기준(PC 대응표만, 서버로 안 감) = 다이제스트(변환 버전, 폴더 실경로, 파일 이름, 제목, 같은 제목의 순번).
  같은 묶음의 문단을 고치면 새 개정, 제목을 고치면 새 원본이다. original_id 는 runner 가 난수로 1회 발급한다.
- 제목·본문의 로컬 경로(`~/`·`/Users/`·`/home/`·`/private/`·`/var/`·`/Volumes/`·Windows 드라이브·UNC 로 시작하는 덩어리)는
  격리하지 않고 PATH_MASK(`‹경로›`)로 가린 뒤 보낸다(원작자 2026-11-04 「b」). 덩어리 = 접두부터 공백·닫는 괄호·따옴표·백틱·`|` 앞까지
  (붙은 조사도 함께 가린다 — 폴더 이름이 새지 않게). 가린 수는 collect 반환 redacted 와, 서버가 승인 때 센 기록 메타에만 남는다.
- URL·이메일이 있거나 길이 한도를 넘으면 계약 검증에서 격리된다(보내지 않는다) — 지금 규칙 그대로.
- 장치 허용 규칙에 session-wrap/1 이 없으면 아무것도 만들지 않는다(skipped=policy) — 웹 「연결 장치」에서 「세션 정리」를 켠다.
- 주제 줄(2026-11-26 주제 잇기): 묶음 본문에서 줄 처음이 `주제:` 인 첫 줄(코드 울타리 밖)의 콜론 뒤 글자(앞뒤 공백 뺌)를 주제 이름으로
  fields topic 에 싣고 그 줄은 본문에서 뺀다. 서버는 같은 이름의 주제 항목에 이 기록을 이어 붙인다. 이름이 계약(contract.check_topic: 1~40자
  한 줄, 제어 문자·URL·경로 꼴 없음)에 안 맞거나, 줄을 빼면 본문이 비거나, 서버 features 에 topics 가 없으면(옛 서버, 주제 오브젝트 없는 계정)
  줄을 본문에 그대로 둔다(axis_codes 와 같은 방식).
"""
from __future__ import annotations

import datetime as _dt
import os
import re

from . import contract, jcs, runner as _runner

TRANSFORM = "session-wrap/1"
ADAPTER = "session-wrap"
FILE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
MAX_FILE_BYTES = 512 * 1024
MAX_TITLE = 200                       # 계약 title 상한(코드 포인트)
_H2 = re.compile(r"^##[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")
_H1 = re.compile(r"^#[ \t]+\S")
_RULE = re.compile(r"^-{3,}[ \t]*$")
_FENCE = re.compile(r"^[ \t]{0,3}(```|~~~)")
_DROP = re.compile(r"^[ \t]*(?:[-*][ \t]+)?→[ \t]*남긴[ \t]*곳[ \t]*[:：]")
_TOPIC = re.compile(r"^주제:(.*)$")
TOPICS_FEATURE = "topics"             # 서버 features(GET /api/imports/device) — 주제 오브젝트가 있는 계정에만 실린다
PATH_MASK = "‹경로›"                  # 서버 imports.SESSION_WRAP_PATH_MASK 와 같은 문자열(서버는 승인 때 개수만 센다)
# 경로 덩어리 — 계약 차단 규칙(contract._BLOCK_PATTERNS path)의 접두를 모두 덮고 앞 경계는 더 넓다(영숫자·._/~- 뒤만 아니면).
# 그래서 가린 결과는 path 규칙에 걸리지 않는다(시험이 본다). UNC 는 계약처럼 앞 경계 없이.
_PATH_TAIL = r"[^\s)\]}>\"'`|]*"
_PATH_SPAN = re.compile(r"(?<![A-Za-z0-9._/~-])(?:~/|/Users/|/home/|/private/|/var/|/Volumes/|[A-Za-z]:\\)" + _PATH_TAIL
                        + r"|\\\\[A-Za-z0-9._-]+\\" + _PATH_TAIL)


def redact_paths(text: str) -> tuple:
    """로컬 경로 덩어리를 PATH_MASK 로 바꾼다. 반환 (바꾼 글, 가린 수)."""
    return _PATH_SPAN.subn(PATH_MASK, text)


def _strip_frontmatter(lines: list) -> list:
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                return lines[i + 1:]
    return lines


def parse(text: str) -> list:
    """세션 정리 글 → [(제목, 본문)]. 본문이 빈 묶음은 뺀다."""
    lines = _strip_frontmatter(text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n"))
    blocks, cur, fence = [], None, None
    for line in lines:
        if fence is not None:                       # 코드 울타리 안의 ##·--- 는 묶음 경계가 아니다
            if cur is not None:
                cur[1].append(line)
            if line.strip().startswith(fence):
                fence = None
            continue
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            if cur is not None:
                cur[1].append(line)
            continue
        h = _H2.match(line)
        if h and not line.startswith("###"):
            cur = [h.group(1).strip(), []]
            blocks.append(cur)
            continue
        if _H1.match(line) or _RULE.match(line):
            cur = None
            continue
        if cur is not None and not _DROP.match(line):
            cur[1].append(line)
    out = []
    for title, body_lines in blocks:
        body = "\n".join(body_lines).strip("\n")
        if body.strip() and title:
            out.append((title[:MAX_TITLE], body))
    return out


def split_topic(body: str):
    """묶음 본문 → (주제 이름 또는 None, 그 줄을 뺀 본문). 줄 처음이 `주제:` 인 첫 줄만 본다(코드 울타리 안 제외).
    이름이 계약에 안 맞거나 줄을 빼면 본문이 비면 (None, 본문 그대로)."""
    lines, fence = body.split("\n"), None
    for i, line in enumerate(lines):
        if fence is not None:
            if line.strip().startswith(fence):
                fence = None
            continue
        m = _FENCE.match(line)
        if m:
            fence = m.group(1)
            continue
        t = _TOPIC.match(line)
        if not t:
            continue
        name = t.group(1).strip()
        rest = "\n".join(lines[:i] + lines[i + 1:]).strip("\n")
        try:
            contract.check_topic(name)
        except contract.ContractError:
            return None, body
        return (name, rest) if rest.strip() else (None, body)
    return None, body


def list_files(folder: str) -> list:
    """폴더 바로 아래의 (날짜, 파일 이름, 실경로) — 날짜 이름 .md 만. 숨김·심링크·폴더 밖 실경로·하위 폴더 제외."""
    root = os.path.realpath(folder)
    out = []
    for fn in sorted(os.listdir(root)):
        m = FILE_RE.match(fn)
        full = os.path.join(root, fn)
        if not m or os.path.islink(full) or not os.path.isfile(full):
            continue
        real = os.path.realpath(full)
        if os.path.dirname(real) != root:
            continue
        try:
            _dt.date.fromisoformat(m.group(1))
        except ValueError:
            continue
        out.append((m.group(1), fn, real))
    return out


def collect(st, cfg: dict, counts: dict | None = None) -> dict:
    """설정 폴더의 세션 정리 묶음을 전송 대기로 만든다. 반환 {"files", "blocks", "staged", "redacted", "skipped", "missing_folders"}
    — 값·경로 없음. redacted = 이번 실행에서 가린 경로 수(전송 대기로 만든 묶음만이 아니라 읽은 묶음 전부)."""
    sc = cfg.get("session_wrap") or {}
    out = {"files": 0, "blocks": 0, "staged": 0, "redacted": 0, "missing_folders": 0, "skipped": None}
    if not sc.get("enabled"):
        out["skipped"] = "disabled"
        return out
    allowed = cfg.get("allowed_transforms")
    if allowed is not None and TRANSFORM not in allowed:
        out["skipped"] = "policy"                   # 장치 허용 규칙에 「세션 정리」가 없다 — 웹 「연결 장치」에서 켠다
        return out
    counts = counts if counts is not None else _runner.new_counts()
    execution = "attended" if cfg.get("_execution") == "attended" else "unattended"
    topics_on = TOPICS_FEATURE in (cfg.get("server_features") or [])
    for folder in sc.get("folders") or []:
        if not (isinstance(folder, str) and os.path.isabs(folder) and os.path.isdir(folder)):
            out["missing_folders"] += 1             # 폴더 하나가 없어도 나머지는 계속한다
            continue
        root = os.path.realpath(folder)
        try:
            files = list_files(folder)
        except OSError:
            out["missing_folders"] += 1             # 읽을 수 없는 폴더 — 나머지는 계속한다
            continue
        for date, fn, real in files:
            try:
                with open(real, "rb") as f:
                    data = f.read(MAX_FILE_BYTES + 1)
                text = data.decode("utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if len(data) > MAX_FILE_BYTES:
                continue
            out["files"] += 1
            seen = {}
            for title, body in parse(text):
                n = seen.get(title, 0)
                seen[title] = n + 1
                out["blocks"] += 1
                key = jcs.sha256_hex([TRANSFORM, root, fn, title, n])   # 중복 기준은 가리기 전 제목(PC 대응표만)
                topic, body = split_topic(body) if topics_on else (None, body)
                t, n1 = redact_paths(title)
                b, n2 = redact_paths(body)
                out["redacted"] += n1 + n2
                fields = {"title": t, "body": b, "source_date": date}
                if topic is not None:
                    fields["topic"] = topic
                ident = " ".join(str(fields.get(k) or "") for k in ("title", "body", "topic"))   # 계정 식별자 대조에 주제 이름도
                if _runner.stage_self_text(st, cfg, adapter_name=ADAPTER, dedupe_key=key, fingerprint=key, kind="self_text",
                                           transform_version=TRANSFORM, execution=execution, fields=fields, counts=counts,
                                           identity_text=ident):
                    out["staged"] += 1
    return out
