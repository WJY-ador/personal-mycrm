"""오류 자동 Case(2026-11-13 명세 1.4) — 사용자 쪽 오류를 운영자 문의(tickets kind bug, via auto)로 자동 접수한다.

경로 셋, 본문 같음(server/web.py):
  POST /api/device/error-reports   Authorization: Bearer 장치 토큰(PC 에이전트, 앱 main) — source app | agent
  POST /desktop/error-reports      앱 로그인 세션(/desktop/device/auto 와 같은 관문) — 장치 토큰이 죽은 때. source app | agent
  POST /api/error-reports          웹 세션 쿠키 + Origin — source web
본문(엄격 JSON, BODY_MAX 바이트, 모르는 키·중복 키 = 400):
  {"source", "stage", "code", "app_version", "os", "occurred_at", "count"?}
담는 것 = 출처, 단계 코드, 오류 코드, 앱 버전, OS 종류, 발생 시각, 횟수. 담지 않는 것 = 기록 본문, 제목, 경로, URL, 이메일, 토큰, 오류 문장.
정규식이 점, 슬래시(단계 구분 밖), 공백, @ 를 막아 그런 값이 실릴 자리가 없다. 어긋나면 잘라 저장하지 않고 400.
응답 200 {"accepted": true, "state": "created"|"counted"} · 200 {"accepted": false, "state": "off"|"capped"}.
보고 호출의 실패는 다시 보고하지 않는다(클라이언트 계약).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone

import db
import imports
from db import CrmError, tx
import features

BODY_MAX = 2048
RATE_PER_MIN = 30          # 사용자 분당 보고 수(경로 셋 합계)
COUNT_MAX = 1000           # 한 보고가 싣는 횟수(클라이언트 쪽 합산분)
PAST_DAYS = 7
FUTURE_SECONDS = 300
OS_KINDS = ("mac", "win", "other")
KEYS = {"source", "stage", "code", "app_version", "os", "occurred_at"}
STAGE_RE = re.compile(r"[a-z][a-z0-9-]{0,23}(?:/[a-z0-9-]{1,32}){0,2}")
CODE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,47}")
VERSION_RE = re.compile(r"\d{1,3}\.\d{1,3}\.\d{1,3}(?:[-+][0-9A-Za-z.-]{1,20})?")
TIME_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z")
SOURCES_DEVICE = ("app", "agent")
SOURCES_WEB = ("web",)


def _bad(field: str) -> CrmError:
    return CrmError("ARG-INVALID", f"오류 보고 형식이 맞지 않아요({field}).")


def _no_dupes(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError("dup")
        out[k] = v
    return out


def parse(raw: bytes, allowed_sources) -> dict:
    """본문 검사 → {source, stage, code, app_version, os, occurred_at, count}. 틀리면 ARG-INVALID(어느 칸인지만, 값은 넣지 않는다)."""
    if len(raw) > BODY_MAX:
        raise CrmError("PAYLOAD-LIMIT", f"오류 보고가 너무 커요(상한 {BODY_MAX} 바이트).")
    try:
        body = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_dupes)
    except Exception:
        raise _bad("json") from None
    if not isinstance(body, dict) or not KEYS <= set(body) or not set(body) <= KEYS | {"count"}:
        raise _bad("keys")
    src, stage, code, ver, os_kind, at = (body[k] for k in ("source", "stage", "code", "app_version", "os", "occurred_at"))
    n = body.get("count", 1)
    if src not in allowed_sources:
        raise _bad("source")
    if not isinstance(stage, str) or not STAGE_RE.fullmatch(stage):
        raise _bad("stage")
    if not isinstance(code, str) or not CODE_RE.fullmatch(code):
        raise _bad("code")
    if not isinstance(ver, str) or not (ver == "" or VERSION_RE.fullmatch(ver)):
        raise _bad("app_version")
    if os_kind not in OS_KINDS:
        raise _bad("os")
    if not isinstance(at, str) or not TIME_RE.fullmatch(at):
        raise _bad("occurred_at")
    when = datetime.fromisoformat(at[:-1] + "+00:00")
    now = datetime.now(timezone.utc)
    if not now - timedelta(days=PAST_DAYS) <= when <= now + timedelta(seconds=FUTURE_SECONDS):
        raise _bad("occurred_at")
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= COUNT_MAX:
        raise _bad("count")
    return {"source": src, "stage": stage, "code": code, "app_version": ver, "os": os_kind, "occurred_at": at, "count": n}


def _rate(uid):
    """사용자 분당 RATE_PER_MIN — 별도 트랜잭션(뒤에서 실패해도 남는다). 버킷 auto_case(접수, 대화 버킷과 따로)."""
    with tx() as c:
        if imports._bump(c, uid, "user", "minute", "auto_case")["n"] > RATE_PER_MIN:
            raise CrmError("RATE-LIMIT", f"오류 보고가 너무 잦아요(분당 {RATE_PER_MIN}회).", "1분 뒤 다시 보내세요.")


def record(uid: str, raw: bytes, allowed_sources) -> dict:
    """검사 → 스위치 → 속도 → 묶기. 스위치 꺼짐과 상한은 200(accepted false) — 클라이언트가 다시 보내지 않는다."""
    r = parse(raw, allowed_sources)
    if not features.feature_on(uid, "auto_cases"):
        db.usage_count(uid, "auto_case", "OFF")
        return {"accepted": False, "state": "off"}
    _rate(uid)
    state = db.ticket_auto(uid, r["source"], r["stage"], r["code"], r["app_version"], r["os"], r["occurred_at"], r["count"])
    db.usage_count(uid, "auto_case", state.upper())   # 상한으로 버린 것도 집계에만 남는다
    return {"accepted": state != "capped", "state": state}
