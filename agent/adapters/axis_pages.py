"""축 한 장 → axis-page/1 (2026-11-18 축 잇기 명세 3.3). 모델을 쓰지 않는다(결정적 변환).

- 입력 = 설정 axis_pages.dir(절대 경로, 기본값 없음) 바로 아래의 `<축 코드>.md` 만. 코드 = [A-Z0-9-] 1~10자(contract.AXIS_CODE_RE).
  그래서 `A.prev.md`·`A.bad.json`·`A.error.txt`·`A.material.json` 은 읽지 않는다. 숨김·심링크·하위 폴더·폴더 밖 실경로도 건너뛴다.
- 파일 하나 = 한 장 하나. 제목 = 첫 `# ` 머리 줄(없으면 「축 <코드> 한 장」), 본문 = 그 줄 뒤 전부(markdown 그대로).
  원본 시각(source_created_at) = 파일 수정 시각(KST, 오프셋 포함).
- 파일 내용 해시가 지난번에 올린 것과 같으면 아무것도 만들지 않는다(수정 시각만 바뀐 재작성은 새 판이 아니다).
- 중복 기준(PC 대응표만, 서버로 안 감) = 「axis-page:<코드>」. 경로를 넣지 않는다 — 폴더를 옮겨도 같은 원본이 이어지고,
  같은 축의 새 판은 같은 original_id 의 새 개정이 된다(서버는 새 판을 그 축에 붙이고 옛 판의 축 연결을 뗀다).
- 제목·본문의 URL·이메일·로컬 경로는 격리하지 않고 가린 뒤 보낸다(수집 글 가림 규칙 = 세션 정리 경로 가림과 같은 경로 꼴).
- 장치 허용 규칙에 axis-page/1 이 없으면(옛 서버) 아무것도 만들지 않는다(skipped=policy).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import os
import re

from .. import contract, osutil, runner as _runner
from .collected import EMAIL_MASK, PATH_MASK, URL_MASK, mask

TRANSFORM = contract.AXIS_PAGE_TRANSFORM
ADAPTER = "axis-pages"
FILE_RE = re.compile(r"^([A-Z0-9-]{1,10})\.md$")
MAX_FILE_BYTES = 64 * 1024
MAX_TITLE = 200
SHA_CURSOR = "axis_page_sha:"          # + 코드 → 지난번에 만든(또는 같다고 본) 파일 내용 해시
_H1 = re.compile(r"^#[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def parse(code: str, text: str) -> tuple:
    """한 장 글 → (제목, 본문). 첫 `# ` 줄이 제목, 그 뒤가 본문. 머리 줄이 없으면 제목은 코드로 만들고 본문은 글 전체."""
    lines = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        m = _H1.match(line)
        if m:
            return " ".join(m.group(1).split())[:MAX_TITLE], "\n".join(lines[i + 1:]).strip("\n")
        break
    return f"축 {code} 한 장", "\n".join(lines).strip("\n")


def list_files(folder: str) -> list:
    """폴더 바로 아래의 (코드, 실경로) — `<코드>.md` 만. 심링크·폴더 밖 실경로·파일 아닌 것 제외. 코드 순."""
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
        out.append((m.group(1), real))
    return out


def _masks(text: str) -> int:
    return sum(text.count(m) for m in (URL_MASK, EMAIL_MASK, PATH_MASK))


def collect(st, cfg: dict, counts: dict | None = None) -> dict:
    """설정 폴더의 한 장을 전송 대기로 만든다. 반환 {"files", "staged", "unchanged", "redacted", "skipped"} — 값·경로 없음."""
    sec = cfg.get("axis_pages") or {}
    out = {"files": 0, "staged": 0, "unchanged": 0, "redacted": 0, "skipped": None}
    folder = sec.get("dir") if isinstance(sec, dict) else None
    if not folder:
        out["skipped"] = "disabled"
        return out
    allowed = cfg.get("allowed_transforms")
    if allowed is not None and TRANSFORM not in allowed:
        out["skipped"] = "policy"            # 서버가 한 장을 모른다(옛 서버) — 올리지 않는다
        return out
    if not (isinstance(folder, str) and os.path.isabs(folder) and os.path.isdir(folder)):
        out["skipped"] = "missing-folder"
        return out
    try:
        files = list_files(folder)
    except OSError:
        out["skipped"] = "missing-folder"
        return out
    counts = counts if counts is not None else _runner.new_counts()
    execution = "attended" if cfg.get("_execution") == "attended" else "unattended"
    for code, real in files:
        try:
            with open(real, "rb") as f:
                data = f.read(MAX_FILE_BYTES + 1)
            mtime = os.stat(real).st_mtime
            text = data.decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if len(data) > MAX_FILE_BYTES:
            continue
        out["files"] += 1
        sha = hashlib.sha256(data).hexdigest()
        if st.cursor_get(SHA_CURSOR + code) == sha:
            out["unchanged"] += 1
            continue
        title, body = parse(code, text)
        title, body = mask(title).strip(), mask(body)
        if not body.strip():
            continue
        out["redacted"] += _masks(title) + _masks(body)
        at = _dt.datetime.fromtimestamp(mtime, osutil.KST).replace(microsecond=0).isoformat()
        fields = {"title": title or f"축 {code} 한 장", "body": body, "source_created_at": at, "axis_code": code}
        before = dict(counts)
        key = "axis-page:" + code
        _runner.stage_self_text(st, cfg, adapter_name=ADAPTER, dedupe_key=key, fingerprint=key, kind="self_text",
                                transform_version=TRANSFORM, execution=execution, fields=fields, counts=counts)
        if counts["staged"] > before["staged"]:
            out["staged"] += 1
        elif counts["unchanged"] > before["unchanged"]:
            out["unchanged"] += 1
        else:
            continue                          # 앞 판이 아직 전송 중(waiting)·격리·거절 — 다음 실행에 다시 본다
        st.cursor_set(SHA_CURSOR + code, sha)
    return out
