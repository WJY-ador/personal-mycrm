"""오류 자동 보고(명세 2026-11-13 1.4) — PC 에이전트 쪽. run-once 멈춤과 실행 실패를 운영자 Case 로 보낸다.

계약(서버 S 정본 2026-11-13): POST /api/device/error-reports, Authorization Bearer 장치 토큰, 엄격 JSON(2KiB 이하)
{"source":"agent","stage":..,"code":..,"app_version":..,"os":"mac|win|other","occurred_at":"...Z","count":1}.
응답 200 {"accepted":true|false,"state":..} · 400 · 401/403 · 429. 묶기와 횟수 합산은 서버가 한다.
담지 않는 것: 기록 본문, 제목, 경로, URL, 이메일, 토큰, 원문 오류 문장. 단계는 아래 고정 목록, 코드는 CODE 꼴만
(어긋나면 unknown). 네트워크 실패나 5xx 는 한 번만 다시 보내고, 그래도 안 되면 조용히 버린다(보고 실패를 다시 보고하지 않는다).
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from . import AGENT_VERSION

# 계약(서버 S 정본 2026-11-13).
REPORT_PATH = "/api/device/error-reports"
SOURCE = "agent"
# 단계 코드. 여기 없는 단계는 보내지 않는다(모두 서버 정규식 STAGE 안).
STAGES = frozenset({"run-once/halt", "run-once/failed"})
STAGE = re.compile(r"^[a-z][a-z0-9-]{0,23}(/[a-z0-9-]{1,32}){0,2}$")
CODE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,47}$")
TIMEOUT = 5.0


def os_kind(platform=None) -> str:
    p = platform or sys.platform
    return "win" if p.startswith("win") else "mac" if p == "darwin" else "other"


def build(stage: str, code, *, now=None, platform=None, count: int = 1) -> dict | None:
    """보낼 본문. 단계가 고정 목록 밖이면 None(보내지 않는다). 코드가 꼴에 어긋나면 unknown."""
    if stage not in STAGES or not STAGE.fullmatch(stage):
        return None
    if not isinstance(code, str) or not CODE.fullmatch(code):
        code = "unknown"
    when = (now or _dt.datetime.now(_dt.timezone.utc)).astimezone(_dt.timezone.utc).replace(microsecond=0)
    return {"source": SOURCE, "stage": stage, "code": code, "app_version": AGENT_VERSION,
            "os": os_kind(platform), "occurred_at": when.isoformat().replace("+00:00", "Z"),
            "count": min(max(int(count), 1), 1000)}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(server: str, token: str, stage: str, code: str, *, opener=None, now=None, platform=None) -> bool:
    """보낸다(네트워크 실패나 5xx 면 한 번 더). 서버가 받았으면(200) True. 예외를 내지 않는다."""
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
    except Exception:
        return False
    use = opener or urllib.request.build_opener(_NoRedirect())
    for _attempt in range(2):
        try:
            with use.open(req, timeout=TIMEOUT) as res:
                return 200 <= res.status < 300
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return False    # 400, 401/403, 429: 다시 보내지 않는다
        except Exception:
            pass
    return False
