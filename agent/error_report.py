"""오류 자동 보고(명세 2026-11-13 1.4) — PC 에이전트 쪽. run-once 멈춤과 실행 실패를 운영자 Case 로 보낸다.

담는 것: 출처(agent), 단계 코드, 오류 코드, 앱 버전, OS 종류, 발생 시각. 묶기와 횟수는 서버가 한다.
담지 않는 것: 기록 본문, 제목, 경로, URL, 이메일, 토큰, 원문 오류 문장. 단계와 오류 코드는 아래 고정 목록에서만 고른다.
보내기는 한 번, 짧은 시간 제한, 실패해도 조용히 버린다(보고 실패를 다시 보고하지 않는다). 장치 토큰으로만 보낸다.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.parse
import urllib.request

from . import AGENT_VERSION

# 계약(서버 S 가 정본). 받으면 이 두 줄만 맞춘다.
REPORT_PATH = "/api/errors/report"
SOURCE = "agent"
# 단계 코드. 여기 없는 단계는 보내지 않는다.
STAGES = frozenset({"run-once/halt", "run-once/failed"})
_CODE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
TIMEOUT = 5.0


def os_kind(platform=None) -> str:
    p = platform or sys.platform
    return "win" if p.startswith("win") else "mac" if p == "darwin" else "linux"


def build(stage: str, code: str, *, now=None, platform=None) -> dict | None:
    """보낼 본문. 단계나 코드가 고정 꼴이 아니면 None(보내지 않는다)."""
    if stage not in STAGES or not isinstance(code, str) or not _CODE.fullmatch(code):
        return None
    when = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc).replace(microsecond=0)
    return {"source": SOURCE, "stage": stage, "code": code, "app_version": AGENT_VERSION,
            "os": os_kind(platform), "occurred_at": when.isoformat().replace("+00:00", "Z")}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(server: str, token: str, stage: str, code: str, *, opener=None, now=None, platform=None) -> bool:
    """한 번 보낸다. 성공(2xx)이면 True. 예외를 내지 않는다."""
    body = build(stage, code, now=now, platform=platform)
    try:
        parsed = urllib.parse.urlsplit(server or "")
        if (body is None or parsed.scheme not in ("https", "http") or not parsed.hostname
                or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost"))
                or not isinstance(token, str) or not token or "\n" in token or "\r" in token):
            return False
        req = urllib.request.Request(f"{parsed.scheme}://{parsed.netloc}{REPORT_PATH}",
                                     data=json.dumps(body, separators=(",", ":")).encode("utf-8"), method="POST",
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                              "Accept": "application/json"})
        with (opener or urllib.request.build_opener(_NoRedirect())).open(req, timeout=TIMEOUT) as res:
            return 200 <= res.status < 300
    except Exception:
        return False
