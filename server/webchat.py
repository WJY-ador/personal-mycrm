"""웹 「대화」(구독 AI 채팅) — 전송 골격(2026-11-04 PR 1, notes 구현계획 §2 계약).

내 PC 의 구독 CLI 가 답하고 서버는 모델을 부르지 않는다 — 중계·보관만 한다.
  PC 에이전트 ──WebSocket 1개(장치 토큰)──▶ 서버 ◀──POST(입력)·SSE(출력, 쿠키 세션)── 웹

웹(쿠키 세션 · POST 는 Origin 검사):
  POST /api/chat/sessions {device_id?}              → {session_id, status, device_id, connected}
  GET  /api/chat/sessions                           → {sessions:[…], connected}
  GET  /api/chat/sessions/{id}/messages?after=<turn_id> → {messages:[…]} (턴 단위 — after 턴 뒤의 메시지)
  POST /api/chat/sessions/{id}/turns {text, client_turn_id} → {turn_id, status, created} · 409 TURN-BUSY · 같은 client_turn_id = 같은 턴
  POST /api/chat/sessions/{id}/stop                 → {turn_id, status} (실행 중 턴 없으면 turn_id null)
  GET  /api/chat/sessions/{id}/stream               → SSE. id = "<turn_id>:<seq>"(seq 0 = 턴 시작). Last-Event-ID(또는 ?last_event_id=)
                                                      뒤부터 DB 재생 → 실시간. 사용자당 활성 1(새 연결이 옛 연결을 닫음 — 옛 쪽에 event: replaced).
                                                      heartbeat 15초. 재생 상한 = 최근 REPLAY_TURNS 턴·REPLAY_BYTES(넘으면 맨 앞 event: trimmed)
  POST /api/chat/grants {device_id, provider, model|null, request_id} → pending grant(201 새로·200 같은 요청). 서명된 PC 승인 뒤 approved, 소비·공급자 실행은 차단
  GET  /api/chat/grants/{request_id}               → {request_id, device_id, provider, model, state, prompt, close_reason, expires_at, connected}(읽기 전용, 본인 것만)
  GET  /api/chat/permits                            → {permits:[{device_id, installation_id, provider, created_at}]} 살아 있는 서 있는 허용(2026-11-12 J)
  POST /api/chat/permits/revoke {device_id | installation_id, provider|null} → {revoked}(멱등, 장치 토큰 없음 — 권한을 줄이기만 한다)
  GET  /api/chat/capabilities                       → {devices:[{…, allowed_providers}], setup: none|offline|no_provider|ready}
웹 세션 + Origin + Authorization: Bearer 장치 토큰(2026-11-07, 엄격 JSON·4KB):
  POST /api/chat/consent/keys/{begin,activate,revoke} · POST /api/chat/consent/challenges/{issue,verify}
장치(Authorization: Bearer 장치 토큰): WS /api/device/chat/ws
  서버→PC turn.start{session_id, turn_id, text, cli_session_ref?} · turn.stop{turn_id} · ack{turn_id, seq} · ping
  PC→서버 hello{agent_version, providers[]} · event{turn_id, seq, kind, data} · session_ref{session_id, cli_session_ref} · pong
  POST /api/chat/launch-authorization {session_id,turn_id} — launch 권한은 매번 DB 재검증, 현재 실행 상태를 반환(기본 OFF)

해석(스펙이 비운 곳 — PR 본문에 적는다):
- ack = 누적(그 턴에서 연속으로 저장된 마지막 seq). 중복(seq ≤ 마지막) = 무시하고 다시 ack. 빈 칸(seq > 마지막+1) = 저장하지 않음(PC 재전송).
- 턴 끝 = PC 의 done·error 이벤트, 또는 서버가 직접 넣는 error 이벤트(STOPPED·TURN-LIMIT·TURN-TIMEOUT·DEVICE-OFFLINE).
  중지 요청은 PC 연결과 무관하게 서버에서 바로 stopped — 그 뒤 도착하는 그 턴 이벤트는 버린다(ack 는 한다).
  PC 가 조용히 사라진 턴은 TURN_IDLE_SECONDS 뒤 다음 입력 때 failed(TURN-TIMEOUT) — 영구 TURN-BUSY 방지. 자동 재실행 없음(D6).
- 턴 시작 시 그 장치 WS 가 없으면 409 DEVICE-OFFLINE(턴을 만들지 않는다). 활성 세션이 이미 있으면 그 세션을 돌려준다
  (다른 device_id 를 고르면 옛 세션을 닫고 새로).
- 로그·집계엔 코드만 — 본문·토큰·ID 없음.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
from psycopg.types.json import Jsonb

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

import db
import imports
from db import CrmError, tx, _one, _all, _user_lock
from envnames import env
import features   # 판정 정본(2026-11-12) — 조직 설정 + 프로필 권한 + env 비상 끄기

# ── 한도(초기값, 상수 — 구현계획 §2 「한도」). imports.LIMITS·POLL_LIMITS 버킷과 분리(대화는 jobs 큐를 쓰지 않는다) ──
ACTIVE_SESSIONS_PER_USER = 1        # DB 부분 UNIQUE(ux_chat_sessions_active)가 강제
TURNS_PER_MINUTE = 6
TEXT_MAX_CHARS = 8000               # 사용자 메시지(코드포인트)
EVENTS_PER_TURN = 2000
TURN_BYTES_MAX = 1024 * 1024        # 턴당 이벤트 data 합(JSON UTF-8 바이트)
LIVE_BUFFER_BYTES = 256 * 1024      # SSE 구독 하나의 서버 메모리 대기열(넘으면 연결을 닫고 클라이언트가 Last-Event-ID 로 DB 재생)
WS_MESSAGE_MAX = 64 * 1024          # 장치 WS 메시지 하나(바이트)
KEEP_DAYS = 30                      # 보관 — 메시지 생성일 기준, 활동으로 연장 없음
HEARTBEAT_SECONDS = 15              # SSE 주석
REPLAY_TURNS = 20                   # SSE 재생 상한 — 최근 턴 수(앞부분은 messages API 합본으로)
REPLAY_BYTES = 2 * 1024 * 1024      # SSE 재생 상한 — 이벤트 바이트(n_bytes) 합. 최근 턴 1개는 늘 재생한다
SSE_MAX_SECONDS = 300               # SSE 연결 하나의 최대 수명 — 끝나면 브라우저가 Last-Event-ID 로 다시 붙는다(재배포 때 옛 프로세스가 열린 SSE 를 무한히 기다리지 않게)
PING_SECONDS = 25                   # 장치 WS ping + 토큰 재확인(철회·만료·차단 = 닫음)
TURN_IDLE_SECONDS = 600             # 이벤트 없는 running 턴 → 다음 입력 때 failed(TURN-TIMEOUT)
PROVIDER_LAUNCH_READY = True        # 2026-11-12 K: 원작자 실사용, 독립 검토 I와 J 반영 뒤 켬, Codex는 꺼짐
LAUNCH_AUTHORIZATION_PATH = "/api/chat/launch-authorization"
LAUNCH_AUTHORIZATION_TTL_SECONDS = 15
CLIENT_TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CLI_REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
# R-J1: ':'로 시작하는 이름은 받지 않는다 — ":default"(CONSENT_DEFAULT_MODEL)는 서버가 서명 claims 에만 넣는 내부 표지다(grant 요청, 세션 생성. PC 선택지는 _normalize_capabilities 가 그 모델만 뺀다)
MODEL_RE = re.compile(r"^(?!:)[A-Za-z0-9._:/+-]{1,120}$")
CLIENT_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9]*$")
KINDS = ("delta", "tool_call", "tool_result", "done", "error")
TERMINAL_STATUS = {"done": "done", "error": "failed"}

HTTP = {"SWITCH-OFF": 503, "UNAUTHORIZED": 401, "ORIGIN": 403, "NOT-FOUND": 404, "TURN-BUSY": 409, "DEVICE-OFFLINE": 409,
        "NO-DEVICE": 409, "DEVICE-GONE": 409, "SESSION-CLOSED": 409, "DEVICE-REQUIRED": 400, "ARG-INVALID": 400,
        "SESSION-CONFLICT": 409, "PROVIDER-UNAVAILABLE": 409, "CONSENT_REQUIRED": 409,
        "GRANT-CONFLICT": 409, "GRANT-INVALID": 409, "GRANT-USED": 409, "GRANT-EXPIRED": 409,
        "TEXT-LIMIT": 413, "RATE-LIMIT": 429, "AUTH-INVALID": 401, "TOKEN-EXPIRED": 401, "TOKEN-REVOKED": 401,
        "AUTH-BLOCKED": 403, "MCP-ERROR": 400}
HTTP.update({"APPROVAL-STALE": 409, "APPROVAL-CLOSED": 409})

# Operations with complete existing HMAC previews only. Sending content to
# third parties, device authority changes and migration's own bind protocol
# stay disabled until their separate confirmation contracts are implemented.
CHAT_APPROVABLE_OPS = frozenset({
    "record_edit", "record_provenance_set", "candidate_decide",
    "definition_archive", "definition_restore", "person_delete",
    "source_reflection_review", "source_reflection_delete", "trash_move", "trash_restore",
})
# 대화 하나로 F1(2026-11-11): 자유 대화의 write 등급은 pc_connect 를 빼고 전부 카드를 거친다. 판정은 이름 나열이 아니라
# 등급(chat_mcp._PINNED_TIERS)이다 — 나중에 더한 write op 도 카드를 건너뛰지 못한다. 강제는 _chat_mcp_execute 한 곳.
# 이 집합은 다음 턴 outcomes 필터와 F11 대조(서버, agent, 화면)에만 쓴다.
from chat_mcp import _PINNED_TIERS as _CHAT_TIERS  # noqa: E402
CHAT_WRITE_CARD_OPS = frozenset(n for n, t in _CHAT_TIERS.items() if t == "write" and n != "pc_connect")
CHAT_CARD_OPS = CHAT_APPROVABLE_OPS | CHAT_WRITE_CARD_OPS
APPROVAL_TTL_SECONDS = 600
APPROVAL_PENDING_LIMIT = 20
APPROVAL_SESSION_LIMIT = 100
# F8: /api/chat/mcp 본문(바이트). 기록 쓰기 상한 64 KiB(db.py) + JSON 봉투, 이스케이프 여유. 실제 글 상한은 db 쓰기 상한이 정한다.
# 바깥 main.BodyLimit(256 KiB)과 PC 브리지 한 줄(256 KiB) 안이다. grant, 동의 경로는 CONSENT_BODY_MAX(4 KiB) 그대로
CHAT_MCP_BODY_MAX = 96 * 1024
# F13(2026-11-11): 다음 턴 outcomes 를 agent 꼴(json 압축, ensure_ascii=False)로 직렬화한 바이트 상한. agent 는 고정 지시문과 머리말을 더한
# 모델 context 가 16 KiB 를 넘으면 턴을 거절한다(APPROVAL-OUTCOMES). 고정 문구(실측 1237 바이트) + 이 값 <= 16 KiB - 1 KiB 여유.
# 시험(test_chat_injection)이 agent/chat_approval_context.py 의 실제 문구로 이 부등식을 대조한다. 최신 행부터 담고 넘치면 오래된 행을 뺀다
APPROVAL_OUTCOMES_JSON_MAX = 13 * 1024
# I 반영 R4(2026-11-11): 대화 경로의 요청 속도 버킷 — 접수(imports._rate, 장치 분당 10, 사용자 분당 30)와 나눈다. 5초 재인증(분당 12)과
# 도구 호출이 접수 한도를 먹지 않고, 주입된 반복 호출이 같은 장치의 접수를 막지 못한다. 저장은 같은 import_counters 표(버킷 이름만 다름,
# 매시 정리는 버킷과 무관). 버킷 → 장치 분당 상한. 사용자 합계 상한은 같은 버킷 안에서 장치 상한의 2배.
CHAT_RATE_LIMITS = {"chat_launch": 60, "chat_mcp": 60}

# F4: 확정된 write 카드가 다음 턴에 넘기는 생성 id — op별 (결과 키, id 접두어) 허용 목록. 값은 생성기 모양 정규식만 통과한다
# (db.new_id = 접두어_urlsafe 11자, 오브젝트 = od_ hex 10자). 모델이 고른 slug, 글, 그 밖의 값은 넘기지 않는다.
# record_attach, record_title_set 의 id 는 입력 그대로라 넣지 않는다. candidates_propose 는 id 목록(added[])이라 넣지 않는다(candidate_list 로 읽는다).
_WRITE_CREATED = {
    "question_add": (("id", "q"),),
    "record_add": (("id", "r"), ("source_id", "s")),
    "person_save": (("id", "p"),),
    "source_create": (("id", "s"),),
    "source_reflection_save": (("id", "sr"), ("source_id", "s")),
    "definition_propose": (("object_id", "od"), ("proposal_id", "dp")),
    "item_propose": (("item_id", "i"), ("proposal_id", "ip")),
}
_CREATED_ID_RE = {p: re.compile(r"^od_[0-9a-f]{10}$" if p == "od" else rf"^{p}_[A-Za-z0-9_-]{{11}}$")
                  for p in ("q", "r", "s", "p", "sr", "od", "dp", "i", "ip")}

# F2, F3: write 카드 shown 의 한국어 이름표(op별). 정규화 params 의 키를 하나도 빼지 않는다 — 표에 없는 키는 키 이름 그대로 보인다.
_WRITE_LABELS = {
    "layout_set": {"page": "화면", "layout": "배치", "version": "배치 판"},
    "layout_reset": {"page": "화면"},
    "display_name_set": {"display_name": "표시 이름"},
    "question_add": {"text": "질문 문장"},
    "profile_set": {"key": "프로필 항목", "value": "값", "status": "상태", "source": "어디서 알았나"},
    "record_add": {"text": "본문", "title": "제목", "question_id": "질문 ID", "source": "출처 메모", "source_name": "출처 이름",
                   "source_kind": "출처 종류", "source_location": "출처 위치", "decision_owner": "내 결정 표시"},
    "record_attach": {"record_id": "기록 ID", "attach_to": "붙일 곳", "axes": "축", "use_at": "쓸 때", "unattached": "붙이지 않음"},
    "record_title_set": {"record_id": "기록 ID", "title": "새 제목", "expected_revision": "기록 판"},
    "candidates_propose": {"record_id": "기록 ID", "question_id": "질문 ID", "candidates": "판단 후보", "origin": "뽑은 쪽"},
    "definition_propose": {"object_id": "자료 종류 ID", "expected_revision": "자료 종류 판", "definition_json": "정의(JSON)"},
    "item_propose": {"object_id": "자료 종류 ID", "schema_revision": "정의 판", "item_id": "항목 ID", "expected_revision": "항목 판",
                     "code": "코드", "title": "제목", "body": "본문", "data_json": "값(JSON)", "links": "연결"},
    "person_save": {"alias": "별칭", "person_id": "사람 ID", "expected_revision": "판"},
    "source_create": {"kind": "종류", "name": "이름", "location": "위치"},
    "source_reflection_save": {"source_id": "출처 ID", "kind": "종류", "body": "본문", "reflection_id": "읽고 든 생각 ID",
                               "expected_revision": "판"},
}


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _off() -> CrmError:
    return CrmError("SWITCH-OFF", "대화 기능이 지금 꺼져 있어요.", "운영자가 켤 때까지 기다리세요.")


def enabled(uid=None) -> bool:
    """웹 대화 켜짐 — uid 없으면 조직 설정만(사용자 확인 전 첫 관문), 있으면 그 사용자 프로필까지."""
    return features.feature_on(uid, "webchat")


def chat_mcp_enabled(uid=None) -> bool:
    """Gateway route on = ATOMIC_DISPATCH_READY + webchat + chat_mcp(features — 조직 설정·프로필 권한·env 비상 끄기)."""
    from chat_mcp_gateway import route_enabled
    return route_enabled(enabled(uid), features.feature_on(uid, "chat_mcp"))


def _chat_rate(dev, bucket):
    """R4: 대화 요청 속도 — 별도 트랜잭션(뒤에서 실패해도 남는다). 장치 분당 CHAT_RATE_LIMITS[bucket], 사용자 합계는 그 2배.
    접수 버킷(request)은 건드리지 않는다."""
    lim = CHAT_RATE_LIMITS[bucket]
    with tx() as c:
        for key, n in ((dev["id"], lim), ("user", lim * 2)):
            if imports._bump(c, dev["user_id"], key, "minute", bucket)["n"] > n:
                raise CrmError("RATE-LIMIT", f"요청이 너무 잦아요(분당 {n}회).", "1분 뒤 다시 보내세요.")


def _chat_mcp_scope(dev, authorization, session_id, turn_id):
    """Rebuild a one-call scope from current server rows after device auth.

    Scope reads and dispatch share one transaction. The request's exact active
    session and running turn are locators only; user/device/grant/challenge/key
    bindings are rebuilt from server rows under the account lock on every call.
    """
    from chat_mcp import AuthenticatedPrincipal, ConsentBinding, SessionBinding

    m = imports._TOKEN_RE.fullmatch(authorization or "")
    if not m:
        raise _consent_denied()
    stream_id, token_id, secret = m.groups()
    if stream_id != dev.get("id"):
        raise _consent_denied()
    supplied_hash = hashlib.sha256(secret.encode("ascii")).digest()
    uid = dev.get("user_id")
    with tx() as c:
        _user_lock(c, uid)
        user = _one(c, "SELECT blocked_at FROM users WHERE id=%s AND status='active'", (uid,))
        if not user or user["blocked_at"] is not None:
            raise _consent_denied()
        device = _one(c, "SELECT id,user_id,channel,token_id,secret_hash,token_expires_at,token_revoked_at,revoked_at "
                       "FROM import_streams WHERE user_id=%s AND id=%s FOR NO KEY UPDATE", (uid, stream_id))
        if (not device or device["channel"] != "device" or device["revoked_at"] is not None
                or device["token_revoked_at"] is not None or device["token_id"] != token_id
                or device["token_expires_at"] <= _db_clock(c)
                or not hmac.compare_digest(bytes(device["secret_hash"]), supplied_hash)):
            raise _consent_denied()
        # 대화 하나로 J(JD1): 세션 동의 = 그 세션이 묶인 (장치, 공급자) 서 있는 허용이 지금 살아 있는가. 그 세션의 grant 는 보지 않는다
        row = _one(c, "SELECT id AS session_id,user_id,device_id,provider,model,status,binding_version,permit_id,"
                      "created_at AS session_created_at,client_session_id AS grant_session_id FROM chat_sessions "
                      "WHERE user_id=%s AND device_id=%s AND status='active' AND binding_version=2 "
                      "AND provider IN ('claude','codex') AND permit_id IS NOT NULL AND client_session_id IS NOT NULL "
                      "AND id=%s FOR NO KEY UPDATE", (uid, stream_id, session_id))
        turn = _one(c, "SELECT id FROM chat_turns WHERE id=%s AND session_id=%s AND status='running' FOR UPDATE",
                    (turn_id, session_id))
        permit = _permit_live(c, uid, stream_id, row["provider"], row["permit_id"]) if row else None
        now = _db_clock(c)
        session_expires_at = row["session_created_at"] + timedelta(days=KEEP_DAYS) if row else None
        if (not row or not turn or not permit or row["user_id"] != uid or row["device_id"] != stream_id
                or session_expires_at <= now):
            raise _consent_denied()
    principal = AuthenticatedPrincipal(user_id=uid, device_id=stream_id)
    session = SessionBinding(user_id=uid, device_id=stream_id, session_id=row["session_id"],
                             provider=row["provider"], model=row["model"], status=row["status"],
                             grant_session_id=row["grant_session_id"])
    consent = ConsentBinding(user_id=uid, device_id=stream_id, session_id=row["grant_session_id"],
                             provider=row["provider"], model=row["model"], consented_at=min(permit["created_at"], now),
                             expires_at=min(session_expires_at, device["token_expires_at"]), revoked_at=None)
    return principal, session, consent


def _chat_mcp_execute(dev, authorization, body):
    """One HTTP request → fresh trusted scope and facade operation atomically."""
    from chat_mcp_gateway import ChatMcpGateway, _mint_trusted_principal
    import facade

    # tx_scope makes _chat_mcp_scope's user lock and every existing db.tx() in
    # guard/tool handlers savepoints on this same connection. Revoke, close,
    # expiry, or write therefore commits before this request or waits until it
    # commits. Nested tx_scope operations (migration apply/revert) are savepoints.
    with db.tx_scope():
        principal, session, consent = _chat_mcp_scope(dev, authorization, body["session_id"], body["turn_id"])
        trusted = _mint_trusted_principal(
            user_id=principal.user_id, device_id=principal.device_id, session_id=session.session_id,
            provider=session.provider, model=session.model, expires_at=consent.expires_at,
        )
        gateway = ChatMcpGateway(principal=principal, session=session, consent=consent,
                                 context=trusted, catalog=facade.load_catalog())
        tool = body["tool"]
        if tool == "list":
            return {"tools": list(gateway.tools(("find", "read", "write", "decide", "purge", "shell")))}
        if tool == "find":
            args = body["params"]
            if any(type(args.get(k, "")) is not str or len(args.get(k, "")) > 1200 for k in ("query", "family", "op")):
                raise CrmError("ARG-INVALID", "find 인자가 올바르지 않아요.")
            return gateway.find(query=args.get("query", ""), family=args.get("family", ""), op=args.get("op", ""))
        if tool == "decide" and body["op"] in CHAT_APPROVABLE_OPS:
            return approval_prepare(principal.user_id, session.session_id, body["turn_id"],
                                    body["op"], body["params"])
        if tool == "write":
            # F1: write 겉면은 어떤 op 이든 바로 실행하지 않는다. 모델이 준 bind 는 무시한다.
            # 등급이 write 가 아니거나 pc_connect 면 chat_write_prepare 가 거절한다(그래서 gateway.call 에 닿지 않는다).
            return chat_write_prepare(principal.user_id, session.session_id, body["turn_id"],
                                      body["op"], body["params"])
        if tool not in gateway.tools((tool,)):
            raise _consent_denied()
        result = gateway.call(tool, body["op"], body["params"], body.get("bind", ""))
        structured = getattr(result, "structured_content", None)
        if structured is not None:
            return structured
        content = getattr(result, "content", None)
        if content is not None:
            return {"content": [{k: getattr(block, k) for k in ("type", "text", "mime_type")
                                 if getattr(block, k, None) is not None} for block in content],
                    "isError": bool(getattr(result, "isError", False))}
        return result


def _chat_launch_authorization(dev, authorization, session_id, turn_id):
    """Revalidate the live provider launch binding under the account lock.

    IDs from the request are locators only. Identity, provider/model, consent,
    and operation policy always come from authenticated server state.
    """
    import facade
    from chat_mcp import allowed_operations

    match = imports._TOKEN_RE.fullmatch(authorization or "")
    if not match or match.group(1) != dev.get("id"):
        raise _consent_denied()
    token_id, secret = match.group(2), match.group(3)
    token_hash = hashlib.sha256(secret.encode("ascii")).digest()
    uid, device_id = dev.get("user_id"), dev.get("id")
    with db.tx_scope() as c:
        _user_lock(c, uid)
        user = _one(c, "SELECT blocked_at FROM users WHERE id=%s AND status='active'", (uid,))
        if not user or user["blocked_at"] is not None:
            raise _consent_denied()
        device = _one(c, "SELECT id,user_id,channel,token_id,secret_hash,token_expires_at,token_revoked_at,revoked_at "
                       "FROM import_streams WHERE user_id=%s AND id=%s FOR NO KEY UPDATE", (uid, device_id))
        if (not device or device["channel"] != "device" or device["revoked_at"] is not None
                or device["token_revoked_at"] is not None or device["token_id"] != token_id
                or device["token_expires_at"] <= _db_clock(c)
                or not hmac.compare_digest(bytes(device["secret_hash"]), token_hash)):
            raise _consent_denied()
        session = _one(c, "SELECT * FROM chat_sessions WHERE id=%s AND user_id=%s AND device_id=%s "
                        "AND status='active' AND binding_version=2 FOR NO KEY UPDATE",
                        (session_id, uid, device_id))
        turn = _one(c, "SELECT * FROM chat_turns WHERE id=%s AND session_id=%s FOR UPDATE", (turn_id, session_id))
        if (not session or not turn or turn["status"] != "running"
                or session["provider"] not in GRANT_PROVIDERS or not session["client_session_id"]
                or not session.get("permit_id")):
            raise _consent_denied()
        # 대화 하나로 J(JD1): (장치, 공급자) 서 있는 허용 판정 하나(_permit_live). 해제되면 그 공급자의 모든 세션이 닫힌 실패다
        permit = _permit_live(c, uid, device_id, session["provider"], session["permit_id"])
        now = _db_clock(c)
        session_expires_at = session["created_at"] + timedelta(days=KEEP_DAYS)
        if not permit or session_expires_at <= now:
            raise _consent_denied()
        expires_at = min(now + timedelta(seconds=LAUNCH_AUTHORIZATION_TTL_SECONDS),
                         device["token_expires_at"], session_expires_at)
        if expires_at <= now:
            raise _consent_denied()
        tools = {f"mcp__my-crm__{op}": tier for tier, op in allowed_operations(facade.load_catalog())}
        tools["mcp__my-crm__find"] = "read"
        return {"authorized": True,
                "binding": {"user_id": uid, "device_id": device_id, "session_id": session["id"],
                            "turn_id": turn["id"], "provider": session["provider"], "model": session["model"],
                            # 키 이름은 agent 계약 그대로 — 값 = 이 허용을 성립시킨 grant 와 challenge 의 id(세션 안에서 바뀌지 않는다)
                            "grant_id": permit["grant_id"], "consent_challenge_id": permit["challenge_id"],
                            "expires_at": expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")},
                "tools": tools}


def _cp(s: str) -> int:
    return len(s)   # Python str 길이 = 코드포인트


def _jbytes(v) -> int:
    return len(json.dumps(v, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _iso(v):
    return v.isoformat() if v is not None else None


# ── DB ────────────────────────────────────────────────────

def _active_devices(c, uid):
    return [r["id"] for r in _all(c, "SELECT id FROM import_streams WHERE user_id=%s AND channel='device' AND revoked_at IS NULL "
                                     "AND token_revoked_at IS NULL ORDER BY created_at", (uid,))]


def _active_devices_for_user(uid):
    with tx() as c:
        return _active_devices(c, uid)


def _normalize_capabilities(value):
    if not isinstance(value, list) or len(value) > 8:
        return []
    out, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"provider", "models"}:
            continue
        provider, models = item["provider"], item["models"]
        # FakeProvider is test-only; never show it as an available provider outside CRM_DEV.
        if provider not in ("claude", "codex", "fake") or (provider == "fake" and env("DEV", "") != "1") or provider in seen or not isinstance(models, list) or not 1 <= len(models) <= 16:
            continue
        normalized, valid = [], True
        for model in models:
            if isinstance(model, str) and model.startswith(":"):
                continue   # R-J1: ':'로 시작하는 이름(:default 표지)은 그 모델 하나만 뺀다. 그 밖의 잘못된 값은 공급자 항목을 버린다(그대로)
            if model is None and None not in normalized:
                normalized.append(None)
            elif isinstance(model, str) and MODEL_RE.fullmatch(model) and model not in normalized:
                normalized.append(model)
            else:
                valid = False
                break
        if valid and normalized:
            seen.add(provider)
            out.append({"provider": provider, "models": normalized})
    return out


def _supports(caps, provider, model):
    return any(c["provider"] == provider and model in c["models"] for c in caps)


def _session_out(s, connected=None):
    out = {"session_id": s["id"], "status": s["status"], "device_id": s["device_id"], "provider": s["provider"],
           "model": s.get("model"), "binding_version": s.get("binding_version", 0),
           "created_at": _iso(s["created_at"]), "last_at": _iso(s["last_at"])}
    if connected is not None:
        out["connected"] = connected
    return out


def session_open(uid: str, device_id: str | None):
    """활성 세션 하나 — 있으면 그것(다른 device_id 를 고르면 닫고 새로), 없으면 만든다. 장치 = 사용자의 연결된 장치(1대면 자동).
    반환 (세션, 닫은 세션의 끝 이벤트 [(session_id, 이벤트)] — 호출한 쪽이 SSE 로 보낸다)."""
    with tx() as c:
        _user_lock(c, uid)
        devs = _active_devices(c, uid)
        if device_id is not None and device_id not in devs:
            raise CrmError("NOT-FOUND", "그 장치를 찾을 수 없어요.", "웹의 「연결 장치」에서 확인하세요.")
        cur = _one(c, "SELECT * FROM chat_sessions WHERE user_id=%s AND status='active' FOR NO KEY UPDATE", (uid,))
        if cur and cur["device_id"] in devs and (device_id is None or device_id == cur["device_id"]):
            return _session_out(cur), []
        closed = [(cur["id"], e) for e in _close_session(c, cur["id"])] if cur else []
        if device_id is None:
            if not devs:
                raise CrmError("NO-DEVICE", "연결된 PC 가 없어요.", "PC 에서 my-crm 에이전트를 연결하세요.")
            if len(devs) > 1:
                raise CrmError("DEVICE-REQUIRED", "연결된 PC 가 여러 대예요.", "device_id 로 PC 하나를 고르세요.")
            device_id = devs[0]
        s = _one(c, "INSERT INTO chat_sessions (id,user_id,device_id) VALUES (%s,%s,%s) RETURNING *", (_id("cs"), uid, device_id))
        return _session_out(s), closed


def session_new(uid: str, device_id: str, provider: str, model, client_session_id: str, *, capability_ok=False):
    if not isinstance(client_session_id, str) or not CLIENT_SESSION_RE.fullmatch(client_session_id):
        raise CrmError("ARG-INVALID", "client_session_id 형식이 올바르지 않아요.")
    with tx() as c:
        _user_lock(c, uid)
        old = _one(c, "SELECT * FROM chat_sessions WHERE user_id=%s AND client_session_id=%s", (uid, client_session_id))
        if old:
            if old["device_id"] != device_id or old["provider"] != provider or old["model"] != model:
                raise CrmError("SESSION-CONFLICT", "같은 새 대화 요청 식별자를 다른 선택에 이미 썼어요.")
            return _session_out(old), [], False
        if provider not in ("claude", "codex", "fake") or (model is not None and (not isinstance(model, str) or not MODEL_RE.fullmatch(model))):
            raise CrmError("ARG-INVALID", "provider 또는 model 값이 올바르지 않아요.")
        if not capability_ok:
            raise CrmError("PROVIDER-UNAVAILABLE", "선택한 AI 또는 모델을 이 PC에서 사용할 수 없어요.", "연결 상태와 선택지를 확인하세요.")
        devs = _active_devices(c, uid)
        if device_id not in devs:
            raise CrmError("NOT-FOUND", "그 장치를 찾을 수 없어요.")
        if _one(c, "SELECT 1 FROM chat_turns t JOIN chat_sessions s ON s.id=t.session_id WHERE s.user_id=%s AND t.status='running'", (uid,)):
            raise CrmError("TURN-BUSY", "앞 답이 아직 끝나지 않았어요.", "끝나거나 중지한 뒤 새 대화를 시작하세요.")
        permit_id = None
        if provider in GRANT_PROVIDERS:
            # 대화 하나로 J(JD1): (장치, 공급자) 서 있는 허용이 살아 있으면 grant 없이 연다(모델이 달라도, 새 대화여도 다시 묻지 않는다).
            # 없으면 지금처럼 그 request_id 의 서명 검증된 grant 를 같은 트랜잭션에서 1회 소비하고 허용을 세운다.
            # 실패하면 무엇도 커밋되지 않는다 — 지금 세션은 닫히지 않는다.
            permit = _permit_live(c, uid, device_id, provider)
            if not permit:
                grant_id = grant_consume(c, uid, device_id, provider, model, client_session_id)
                permit = _permit_establish(c, uid, device_id, provider, grant_id)
            permit_id = permit["id"]
        cur = _one(c, "SELECT * FROM chat_sessions WHERE user_id=%s AND status='active' FOR NO KEY UPDATE", (uid,))
        closed = [(cur["id"], e) for e in _close_session(c, cur["id"])] if cur else []
        s = _one(c, "INSERT INTO chat_sessions (id,user_id,device_id,provider,model,client_session_id,binding_version,permit_id) "
                    "VALUES (%s,%s,%s,%s,%s,%s,2,%s) RETURNING *",
                 (_id("cs"), uid, device_id, provider, model, client_session_id, permit_id))
        return _session_out(s), closed, True


# ── 서 있는 허용(대화 하나로 J, 2026-11-12 JD1~JD3) ─────────────────
# (사용자, 장치, 공급자)마다 한 번. 성립 = 서명 검증된 grant 를 session_new 가 소비할 때(PC 동의 창 허용 + Ed25519 + 키 active, 지금과 같다).
# 판정은 _permit_live 하나 — session_new, 세션 재확인(턴, 확인 카드), launch-authorization, /api/chat/mcp, capabilities 가 같이 쓴다.
# 화면 잠금과 앱 재시작은 허용을 지우지 않는다(JD2, 원작자 위험 수용). 끝내는 길(JD3) = 사람이 하는 해제(permit_revoke: 웹, PC 앱),
# 장치 해제와 웹 토큰 재발급(imports), 설치본 해제(token_grants.pc_forget), 키 폐기(_consent_revoke), 토큰 만료(판정 실패).
def _permit_live(c, uid, device_id, provider, permit_id=None, lock=True):
    """살아 있는 허용 행 | None. 호출자는 _user_lock 을 잡았다(lock=False 는 읽기 전용 표시용).
    살아 있음 = 행이 있고(permit_id 를 주면 그 행이어야), 장치가 연결 중(해제, 토큰 폐기, 토큰 만료 아님),
    행의 키가 같은 사용자, 설치본, 장치의 active 키, 설치본이 해제되지 않고 같은 장치에 묶임."""
    if provider not in GRANT_PROVIDERS or not isinstance(device_id, str) or not device_id:
        return None
    f, nk = (" FOR UPDATE", " FOR NO KEY UPDATE") if lock else ("", "")
    p = _one(c, "SELECT * FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider=%s" + f,
             (uid, device_id, provider))
    if not p or (permit_id is not None and p["id"] != permit_id):
        return None
    device = _one(c, "SELECT channel,revoked_at,token_revoked_at,token_expires_at FROM import_streams WHERE id=%s AND user_id=%s" + nk,
                  (device_id, uid))
    key = _one(c, "SELECT user_id,installation_id,device_id,state FROM desktop_consent_keys WHERE id=%s AND user_id=%s" + f,
               (p["key_id"], uid))
    inst = _one(c, "SELECT device_id,revoked_at FROM desktop_installations WHERE id=%s AND user_id=%s" + f,
                (p["installation_id"], uid))
    now = _db_clock(c)
    if (not device or device["channel"] != "device" or device["revoked_at"] is not None
            or device["token_revoked_at"] is not None or device["token_expires_at"] <= now
            or not key or key["state"] != "active" or key["installation_id"] != p["installation_id"]
            or key["device_id"] != device_id
            or not inst or inst["revoked_at"] is not None or inst["device_id"] != device_id):
        return None
    return dict(p)


def _permit_establish(c, uid, device_id, provider, grant_id):
    """grant_consume 직후(같은 트랜잭션) 그 grant 의 verified challenge 로 허용을 세운다. 있던 (장치, 공급자) 행은 새 id 로 바꾼다 —
    옛 행에 묶인 세션은 다시 살아나지 않는다."""
    ch = _one(c, "SELECT id,key_id,installation_id FROM chat_consent_challenges WHERE user_id=%s AND grant_id=%s AND device_id=%s "
                 "AND provider=%s AND state='verified' ORDER BY created_at DESC, id DESC LIMIT 1", (uid, grant_id, device_id, provider))
    if not ch:
        raise _consent_denied()
    c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s AND device_id=%s AND provider=%s", (uid, device_id, provider))
    return dict(_one(c, "INSERT INTO chat_provider_permits (id,user_id,device_id,provider,installation_id,key_id,grant_id,challenge_id) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                     (_id("cp"), uid, device_id, provider, ch["installation_id"], ch["key_id"], grant_id, ch["id"])))


def permits_live(uid) -> list:
    """살아 있는 허용 목록(읽기). [{device_id, installation_id, provider, created_at}] — 해제 버튼과 capabilities 의 allowed_providers 가 쓴다."""
    with tx() as c:
        rows = _all(c, "SELECT * FROM chat_provider_permits WHERE user_id=%s ORDER BY created_at, id", (uid,))
        out = []
        for p in rows:
            if _permit_live(c, uid, p["device_id"], p["provider"], p["id"], lock=False):
                out.append({"device_id": p["device_id"], "installation_id": p["installation_id"], "provider": p["provider"],
                            "created_at": _iso(p["created_at"])})
        return out


def permit_revoke(uid: str, device_id=None, installation_id=None, provider=None, *, closed=None) -> int:
    """JD3 허용 해제 — 사람이 직접(웹 쿠키 + Origin. 권한을 줄이기만 하므로 장치 토큰을 요구하지 않는다). 장치(device_id) 또는
    PC 설치본(installation_id) 하나와 공급자(claude, codex, None = 전부). 다른 사용자의 장치, 설치본 = NOT-FOUND. 멱등. 반환 = 지운 행 수.
    R-J2(보안 검토 발견 1): 지운 (장치, 공급자)의 열린 세션을 같은 트랜잭션에서 닫는다(실행 중 턴 = failed CONSENT_REQUIRED).
    closed 목록을 주면 닫은 것을 [{session_id, device_id, turn_ids, events}]로 채운다 — route 가 커밋 뒤 PC 에 turn.stop 을,
    화면 SSE 에 끝 이벤트를 보낸다. 잠금 순서 = users → chat_sessions → chat_turns → 허용 행(다른 경로와 같다)."""
    if (device_id is None) == (installation_id is None) or (provider is not None and provider not in GRANT_PROVIDERS):
        raise CrmError("ARG-INVALID", "PC 하나와 AI 종류를 골라 주세요.")
    with tx() as c:
        _user_lock(c, uid)
        if installation_id is not None:
            _check_installation(installation_id)
            if not _one(c, "SELECT 1 FROM desktop_installations WHERE user_id=%s AND id=%s", (uid, installation_id)):
                raise CrmError("NOT-FOUND", "그 PC 를 찾을 수 없어요.")
            col, val = "installation_id", installation_id
        else:
            if not isinstance(device_id, str) or not 1 <= len(device_id) <= 200 or not _one(
                    c, "SELECT 1 FROM import_streams WHERE user_id=%s AND id=%s AND channel='device'", (uid, device_id)):
                raise CrmError("NOT-FOUND", "그 장치를 찾을 수 없어요.")
            col, val = "device_id", device_id
        where, args = f"user_id=%s AND {col}=%s" + (" AND provider=%s" if provider else ""), (uid, val, provider) if provider else (uid, val)
        # 세션, 실행 중 턴을 허용 행보다 먼저 잠근다(턴 만들기, launch-authorization, /api/chat/mcp 가 세션 → 턴 → 허용 순서로 잡는다)
        pairs = {(p["device_id"], p["provider"]) for p in _all(c, f"SELECT device_id, provider FROM chat_provider_permits WHERE {where}", args)}
        sessions = [s for s in _all(c, "SELECT id, device_id, provider FROM chat_sessions WHERE user_id=%s AND status='active' "
                                       "ORDER BY id FOR NO KEY UPDATE", (uid,)) if (s["device_id"], s["provider"]) in pairs]
        running = {s["id"]: [t["id"] for t in _all(c, "SELECT id FROM chat_turns WHERE session_id=%s AND status='running' ORDER BY id FOR UPDATE",
                                                    (s["id"],))] for s in sessions}
        gone = {(r["device_id"], r["provider"]) for r in _all(c, f"DELETE FROM chat_provider_permits WHERE {where} RETURNING device_id, provider", args)}
        for s in sessions:
            if (s["device_id"], s["provider"]) not in gone:
                continue
            turn_ids = running[s["id"]]
            events = [e for e in _close_session(c, s["id"], "CONSENT_REQUIRED") if e]
            if closed is not None:
                closed.append({"session_id": s["id"], "device_id": s["device_id"], "turn_ids": turn_ids, "events": events})
        return len(gone)


# ── PC 명시 승인 grant(D7 기반, 2026-11-06) ─────────────────
# 승인된 grant 는 session_new 안에서 세션 생성과 함께 1회 소비한다.
# 웹 요청의 Origin 부재·X-MyCRM-Desktop 같은 머리글은 증거가 아니다 — verifier 는 요청 객체를 받지 않고 grant 행·proof 만 받는다.
# 오래된 grant_approve helper 는 운영 기본에서 닫혀 있다. 세션 소비는 그 callback 결과를 신뢰하지 않고,
# 실제 Ed25519 검증으로 기록된 verified challenge·active key·installation 만 근거로 삼는다.
GRANT_TTL_SECONDS = 300
GRANT_PROVIDERS = ("claude", "codex")
REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_desktop_verifier = None   # legacy approve-only hook. grant_consume 는 이 callback 을 사용하지 않는다.


def _grant_verifier():
    v = _desktop_verifier
    if not callable(v):
        raise CrmError("CONSENT_REQUIRED", "PC 허용 증명을 확인할 수단이 아직 없어요.", "PC 허용 절차가 준비된 뒤 다시 시도하세요.")
    return v


def _grant_args(device_id, provider, model, request_id):
    if (not isinstance(device_id, str) or not 1 <= len(device_id) <= 200 or provider not in GRANT_PROVIDERS
            or (model is not None and (not isinstance(model, str) or not MODEL_RE.fullmatch(model)))
            or not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id)):
        raise CrmError("ARG-INVALID", "허용 요청 값이 올바르지 않아요.")


def _grant_binding(g):
    return {k: g[k] for k in ("id", "user_id", "device_id", "provider", "model", "request_id")}


def grant_request(uid: str, device_id: str, provider: str, model, request_id: str):
    """허용 요청 저장(pending). 같은 request_id·같은 바인딩 = 같은 행(멱등), 다른 바인딩 = GRANT-CONFLICT.
    chat_sessions 는 건드리지 않는다 — 요청만으로 기존 active 세션이 닫히지 않는다. 반환 (grant, created)."""
    _grant_args(device_id, provider, model, request_id)
    with tx() as c:
        _user_lock(c, uid)
        if device_id not in _active_devices(c, uid):
            raise CrmError("NOT-FOUND", "그 장치를 찾을 수 없어요.")
        old = _one(c, "SELECT * FROM chat_provider_grants WHERE user_id=%s AND request_id=%s FOR UPDATE", (uid, request_id))
        if old:
            if (old["device_id"], old["provider"], old["model"]) != (device_id, provider, model):
                raise CrmError("GRANT-CONFLICT", "같은 허용 요청 식별자를 다른 선택에 이미 썼어요.")
            return dict(old), False
        g = _one(c, "INSERT INTO chat_provider_grants (id,user_id,device_id,provider,model,request_id,expires_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s, now() + make_interval(secs => %s)) RETURNING *",
                 (_id("cg"), uid, device_id, provider, model, request_id, GRANT_TTL_SECONDS))
        return dict(g), True


def grant_status(uid: str, request_id: str) -> dict:
    """허용 대기 화면용 읽기(2026-11-10). 상태를 바꾸지 않는다. 세션 uid 의 요청만, 남의 것과 없는 것 = NOT-FOUND.
    state = pending, approved, consumed, 소비 전에 만료(서버 벽시계) = expired.
    prompt = PC 동의 창 상태: none(PC 가 아직 서명 요청을 열지 않음), open(창이 떠 있음), done(서명 확인됨),
    closed(창이 끝났는데 승인 없음), declined(PC 앱이 사용자가 허용하지 않았다고 알림, F9).
    0.1.3 이하 PC 앱은 거절을 알리지 않아(F10) 그 앱의 취소, 시간 초과, 서명 실패는 closed 하나로 둔다.
    close_reason = locked, failed 는 바로 closed 다."""
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise CrmError("ARG-INVALID", "허용 요청 값이 올바르지 않아요.")
    with tx() as c:
        g = _one(c, "SELECT * FROM chat_provider_grants WHERE user_id=%s AND request_id=%s", (uid, request_id))
        if not g:
            raise CrmError("NOT-FOUND", "그 허용 요청을 찾을 수 없어요.")
        now = _db_clock(c)
        ch = _one(c, "SELECT state, expires_at FROM chat_consent_challenges WHERE user_id=%s AND grant_id=%s "
                     "ORDER BY created_at DESC, id DESC LIMIT 1", (uid, g["id"]))
    state = g["state"]
    if state != "consumed" and g["expires_at"] <= now:
        state = "expired"
    if g.get("close_reason") == "declined":
        prompt = "declined"
    elif g.get("close_reason"):
        prompt = "closed"
    elif not ch:
        prompt = "none"
    elif ch["state"] == "verified":
        prompt = "done"
    elif ch["state"] == "issued" and int(ch["expires_at"]) > int(now.timestamp()):
        prompt = "open"
    else:
        prompt = "closed"
    # J-F2(2026-11-12): close_reason 을 그대로 내 화면이 실패(failed: PC 앱이 창을 못 띄움), 잠김(locked), 거절(declined)을 나눠 말한다
    return {"request_id": g["request_id"], "device_id": g["device_id"], "provider": g["provider"], "model": g["model"],
            "state": state, "prompt": prompt, "close_reason": g.get("close_reason"), "expires_at": _iso(g["expires_at"])}


def grant_approve(uid: str, request_id: str, proof):
    """pending → approved. verifier 없음·거절 = CONSENT_REQUIRED(상태 그대로). 만료 = GRANT-EXPIRED. 이미 승인·소비 = GRANT-USED."""
    verify = _grant_verifier()   # 행을 읽기 전에 닫는다
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise CrmError("ARG-INVALID", "허용 요청 값이 올바르지 않아요.")
    with tx() as c:
        _user_lock(c, uid)
        g = _one(c, "SELECT * FROM chat_provider_grants WHERE user_id=%s AND request_id=%s FOR UPDATE",
                 (uid, request_id))
        if not g:
            raise CrmError("NOT-FOUND", "그 허용 요청을 찾을 수 없어요.")
        if g["state"] != "pending":
            raise CrmError("GRANT-USED", "이미 처리한 허용 요청이에요.")
        if g.get("close_reason"):   # F9: PC 가 닫은 grant
            raise CrmError("CONSENT_REQUIRED", "PC 허용 증명을 확인하지 못했어요.", "PC 에서 다시 허용하세요.")
        # Evaluate only after the row lock. PostgreSQL now() is transaction-start time and
        # can be stale if SELECT ... FOR UPDATE waited past the grant expiry.
        if g["expires_at"] <= _db_clock(c):
            raise CrmError("GRANT-EXPIRED", "허용 요청 시간이 지났어요.", "다시 요청하세요.")
        if verify(uid, _grant_binding(g), proof) is not True:
            raise CrmError("CONSENT_REQUIRED", "PC 허용 증명을 확인하지 못했어요.", "PC 에서 다시 허용하세요.")
        if g["expires_at"] <= _db_clock(c):
            raise CrmError("GRANT-EXPIRED", "허용 요청 시간이 지났어요.", "다시 요청하세요.")
        return dict(_one(c, "UPDATE chat_provider_grants SET state='approved', approved_at=clock_timestamp() WHERE id=%s AND state='pending' RETURNING *",
                         (g["id"],)))


def grant_consume(c, uid: str, device_id: str, provider: str, model, request_id: str) -> str:
    """호출한 쪽 트랜잭션(c) 안에서 approved grant 를 1회 소비 — 세션 생성과 같이 커밋·롤백된다. 반환 grant id.
    실제 desktop 키 서명이 검증된 challenge 와 active key/install 이 함께 있어야 한다.
    바인딩 불일치 = GRANT-INVALID, 소비됨 = GRANT-USED, 검증 근거 없음 = CONSENT_REQUIRED, 만료 = GRANT-EXPIRED."""
    _grant_args(device_id, provider, model, request_id)
    g = _one(c, "SELECT * FROM chat_provider_grants WHERE user_id=%s AND request_id=%s FOR UPDATE",
             (uid, request_id))
    if not g or g.get("close_reason"):   # F9: PC 가 닫은 grant 는 소비하지 않는다
        raise CrmError("CONSENT_REQUIRED", "이 대화에 필요한 PC 허용이 없어요.", "PC 에서 허용하세요.")
    if (g["device_id"], g["provider"], g["model"]) != (device_id, provider, model) or device_id not in _active_devices(c, uid):
        raise CrmError("GRANT-INVALID", "이 선택에 맞는 PC 허용이 없어요.", "PC 에서 다시 허용하세요.")
    if g["state"] == "consumed":
        raise CrmError("GRANT-USED", "이미 쓴 PC 허용이에요.", "PC 에서 다시 허용하세요.")
    if g["state"] != "approved" or g["approved_at"] is None:
        raise CrmError("CONSENT_REQUIRED", "PC 허용이 아직 없어요.", "PC 에서 허용하세요.")
    wall_now = _db_clock(c)
    wall_epoch = int(wall_now.timestamp())
    if g["expires_at"] <= wall_now:
        raise CrmError("GRANT-EXPIRED", "PC 허용 시간이 지났어요.", "PC 에서 다시 허용하세요.")

    proof = _one(c, "SELECT ch.id, ch.expires_at, k.state AS key_state, i.revoked_at AS installation_revoked_at "
                    "FROM chat_consent_challenges ch "
                    "JOIN desktop_consent_keys k ON k.id=ch.key_id AND k.user_id=ch.user_id "
                    "JOIN desktop_installations i ON i.user_id=ch.user_id AND i.id=ch.installation_id "
                    "WHERE ch.grant_id=%s AND ch.user_id=%s AND ch.device_id=%s AND ch.session_id=%s "
                    "AND i.device_id=ch.device_id "
                    "AND ch.provider=%s AND ch.model IS NOT DISTINCT FROM %s AND ch.state='verified' "
                    "FOR UPDATE OF ch, k, i", (g["id"], uid, device_id, request_id, provider,
                                               model if model is not None else CONSENT_DEFAULT_MODEL))
    if not proof or proof["key_state"] != "active" or proof["installation_revoked_at"] is not None:
        raise CrmError("CONSENT_REQUIRED", "PC 허용 서명을 확인하지 못했어요.", "PC 에서 다시 허용하세요.")
    proof_now = int(_db_clock(c).timestamp())
    if proof["expires_at"] <= proof_now:
        raise CrmError("GRANT-EXPIRED", "PC 허용 시간이 지났어요.", "PC 에서 다시 허용하세요.")

    consumed = _one(c, "UPDATE chat_provider_grants SET state='consumed', consumed_at=clock_timestamp() "
                       "WHERE id=%s AND state='approved' AND expires_at > clock_timestamp() "
                       "AND EXISTS (SELECT 1 FROM chat_consent_challenges ch WHERE ch.id=%s AND ch.grant_id=%s "
                       "AND ch.state='verified' AND to_timestamp(ch.expires_at) > clock_timestamp()) RETURNING id",
                    (g["id"], proof["id"], g["id"]))
    if not consumed:
        raise CrmError("GRANT-EXPIRED", "PC 허용 시간이 지났어요.", "PC 에서 다시 허용하세요.")
    return g["id"]


CONSENT_RESULT_OUTCOMES = frozenset({"declined", "locked", "failed"})


def consent_result(dev, request_id, outcome) -> bool:
    """F9(2026-11-11): PC 앱이 동의 창이 허용 없이 끝났다고 장치 WS 로 알린다({type: consent.result, request_id, outcome}).
    권한을 줄이기만 하는 신호다 — 그 연결의 사용자와 장치에 속한 pending grant 만, 아직 닫히지 않았을 때만 close_reason 을 쓰고
    그 grant 의 issued challenge 를 revoked 로 바꾼다. 그 밖(형식 틀림, 목록 밖 outcome, 없음, 다른 장치, 이미 승인, 소비, 닫힘)은
    아무것도 하지 않는다(멱등, 응답 없음). 반환 = 닫았으면 True."""
    if (not isinstance(outcome, str) or outcome not in CONSENT_RESULT_OUTCOMES
            or not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id)):
        return False
    uid, device_id = dev.get("user_id"), dev.get("id")
    if not isinstance(uid, str) or not uid or not isinstance(device_id, str) or not device_id:
        return False
    with tx() as c:
        _user_lock(c, uid)
        g = _one(c, "SELECT id, state, close_reason FROM chat_provider_grants WHERE user_id=%s AND request_id=%s AND device_id=%s "
                    "FOR UPDATE", (uid, request_id, device_id))
        if not g or g["state"] != "pending" or g["close_reason"] is not None:
            return False
        c.execute("UPDATE chat_provider_grants SET close_reason=%s WHERE id=%s AND state='pending' AND close_reason IS NULL",
                  (outcome, g["id"]))
        c.execute("UPDATE chat_consent_challenges SET state='revoked', settled_at=now() WHERE user_id=%s AND grant_id=%s AND state='issued'",
                  (uid, g["id"]))
        return True


# ── PC 동의 키·challenge(2026-11-07) ─────────────────
# HTTP route(POST /api/chat/consent/*)는 데스크톱 main→private IPC→device agent 경로에서 호출된다.
# 웹 renderer 는 장치 Bearer 나 서명 private key 를 받지 않는다.
# 함수는 (웹 세션으로 확인된 uid, 원문 Authorization 머리글)을 받아 장치 토큰을 여기서 직접 검증한다. 호출자가 넘긴 장치 id·Origin·
# X-MyCRM-Desktop·renderer 값은 증거가 아니다. 설치본은 호출자가 고르지만, 그 설치본의 device_id 가 토큰의 장치와 같아야만 통과한다.
# 서버가 challenge 서명을 확인하면 grant 는 approved 가 되고 session_new 에서 한 번 소비된다. provider turn dispatch 는 계속 차단한다.
from consent_signature import EXPIRED as _SIG_EXPIRED, encode_consent as _encode_consent, verify_consent as _verify_consent  # noqa: E402
from consent_signature import _load_public_key as _load_consent_key  # noqa: E402

CONSENT_POP_TTL_SECONDS = 120
CONSENT_CHALLENGE_TTL_SECONDS = 120
# 대화 하나로 J(JD1, 2026-11-12 메인): 기본 모델(grant.model = null)도 허용을 세울 수 있다. 서명 claims 의 model 은 문자열이어야 하므로
# null 을 이 표지로 서명한다(서버, PC 앱의 claims 문자 규칙 [A-Za-z0-9._:/+-] 안). 허용은 공급자 단위라 model 은 창에 보일 정보일 뿐이다.
# 같은 글자의 실제 모델이 있어도 challenge 는 grant 행(grant_id, session_id = request_id)에 묶여 섞이지 않는다
CONSENT_DEFAULT_MODEL = ":default"
KEY_POP_PROVIDER = "mycrm-key"   # GRANT_PROVIDERS 와 겹치지 않는다 — 키 증명 서명을 grant 동의로 다시 쓸 수 없다
INSTALLATION_RE = re.compile(r"^di_[0-9a-f]{24}$")
KEY_ID_RE = re.compile(r"^ck_[0-9a-f]{24}$")
NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
CONSENT_BODY_MAX = 4 * 1024      # grant·동의 route 본문(바이트). main.BodyLimit(256KB)보다 좁다
AUTHZ_MAX = 512                  # Authorization 머리글 글자 수
B64URL_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _consent_denied():
    # 무엇이 어긋났는지(사용자·장치·설치본·키) 밝히지 않는다
    return CrmError("CONSENT_REQUIRED", "이 PC 의 동의 절차를 확인하지 못했어요.", "PC 앱에서 다시 시도하세요.")


def _consent_bearer(authorization):
    """장치 Bearer 토큰 검증(실패 = AUTH-*·TOKEN-*). tx 밖에서 부른다 — authenticate 는 자기 트랜잭션을 쓴다."""
    return imports.authenticate(authorization if isinstance(authorization, str) else "")


def _consent_bind(c, uid, dev, installation_id) -> str:
    """세션 uid·토큰 장치·설치본이 한 묶음인지 tx 안에서 다시 본다(잠금 포함). 반환 = 장치 id."""
    if dev.get("user_id") != uid or dev.get("id") not in _active_devices(c, uid):
        raise _consent_denied()
    inst = _one(c, "SELECT device_id, revoked_at FROM desktop_installations WHERE user_id=%s AND id=%s FOR UPDATE", (uid, installation_id))
    if not inst or inst["revoked_at"] is not None or inst["device_id"] != dev["id"]:
        raise _consent_denied()
    return dev["id"]


def _db_clock(c):
    """실제 벽시계. now()는 transaction 시작 시각이라 lock 대기 뒤 만료 판단에 쓰면 안 된다."""
    return _one(c, "SELECT clock_timestamp() AS t", ())["t"]


def _db_now(c) -> int:
    """서명 계약의 epoch 초 시계. 호출자는 관련 행 잠금을 얻은 뒤 읽는다."""
    return int(_db_clock(c).timestamp())


def _require_consumed_session_consent(c, uid, session):
    """Fail closed unless the session's standing (device, provider) permit is still live.

    Caller holds the user and session locks. Permit, device, key, and
    installation are locked here (_permit_live) so permit revoke, key revoke,
    and turn creation serialize on the same user transaction.
    """
    if (session.get("binding_version") != 2 or session.get("provider") not in GRANT_PROVIDERS
            or not session.get("client_session_id") or session.get("user_id") != uid):
        raise _consent_denied()
    user = _one(c, "SELECT status,blocked_at FROM users WHERE id=%s", (uid,))
    if not user or user["status"] != "active" or user["blocked_at"] is not None:
        raise _consent_denied()
    # 대화 하나로 J(JD1): 그 세션의 grant 가 아니라 세션이 묶인 (장치, 공급자) 서 있는 허용이 살아 있는지 본다.
    # 허용이 해제되면(행 없음, 다른 id) 그 공급자의 모든 세션이 여기서 닫힌 실패다. J 이전 세션(permit_id 없음)도 닫힌 실패다
    if not session.get("permit_id"):
        raise _consent_denied()
    permit = _permit_live(c, uid, session.get("device_id"), session["provider"], session["permit_id"])
    if not permit or session["created_at"] + timedelta(days=KEEP_DAYS) <= _db_clock(c):
        raise _consent_denied()


def _pop_claims(uid, device_id, key_id, purpose, nonce, expires_at):
    return {"user_id": uid, "device_id": device_id, "session_id": key_id, "provider": KEY_POP_PROVIDER,
            "model": purpose, "nonce": nonce, "expires_at": int(expires_at)}


def _check_installation(installation_id):
    if not isinstance(installation_id, str) or not INSTALLATION_RE.fullmatch(installation_id):
        raise CrmError("ARG-INVALID", "설치본 값이 올바르지 않아요.")


def consent_key_begin(uid: str, authorization: str, installation_id: str, spki_der: bytes) -> dict:
    """새 서명 키 등록 시작(pending). 반환 {key_id, claims} — claims(model='bind')를 새 키로 서명해 activate 에 낸다.
    같은 설치본의 옛 pending 키는 지운다(대기 키 1개)."""
    _check_installation(installation_id)
    try:
        _load_consent_key(spki_der)
    except TypeError:
        raise CrmError("ARG-INVALID", "공개키 형식이 올바르지 않아요.") from None
    dev = _consent_bearer(authorization)
    with tx() as c:
        _user_lock(c, uid)
        device_id = _consent_bind(c, uid, dev, installation_id)
        c.execute("DELETE FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s AND state='pending'", (uid, installation_id))
        now = _db_now(c)
        nonce = secrets.token_urlsafe(32)
        k = _one(c, "INSERT INTO desktop_consent_keys (id,user_id,installation_id,device_id,spki,pop_nonce,pop_expires_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                 (_id("ck"), uid, installation_id, device_id, spki_der, nonce, now + CONSENT_POP_TTL_SECONDS))
        return {"key_id": k["id"], "claims": _pop_claims(uid, device_id, k["id"], "bind", nonce, now + CONSENT_POP_TTL_SECONDS)}


def consent_key_activate(uid: str, authorization: str, installation_id: str, key_id: str, pop_signature, rotate_signature=None) -> dict:
    """pending → active. 새 키 서명(model='bind') 필수, active 키가 이미 있으면 옛 키 서명(model='rotate', 같은 nonce·key_id)도 필수.
    시도는 한 번뿐 — 실패해도 그 pending 키는 revoked 로 커밋한다. 성공 = 옛 키·그 키의 issued challenge 를 같은 tx 에서 폐기."""
    _check_installation(installation_id)
    if not isinstance(key_id, str) or not KEY_ID_RE.fullmatch(key_id):
        raise CrmError("ARG-INVALID", "키 값이 올바르지 않아요.")
    dev = _consent_bearer(authorization)
    err = out = None
    with tx() as c:
        _user_lock(c, uid)
        device_id = _consent_bind(c, uid, dev, installation_id)
        k = _one(c, "SELECT * FROM desktop_consent_keys WHERE id=%s AND user_id=%s AND installation_id=%s FOR UPDATE", (key_id, uid, installation_id))
        if not k or k["state"] != "pending" or k["device_id"] != device_id:
            raise _consent_denied()
        now = _db_now(c)
        claims = _pop_claims(uid, device_id, k["id"], "bind", k["pop_nonce"], k["pop_expires_at"])
        new_v = _verify_consent(claims, pop_signature, bytes(k["spki"]), now_seconds=now)
        old = _one(c, "SELECT * FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s AND state='active' FOR UPDATE", (uid, installation_id))
        old_ok = old is None or _verify_consent(dict(claims, model="rotate"), rotate_signature, bytes(old["spki"]), now_seconds=now).ok
        if not (new_v.ok and old_ok):
            c.execute("UPDATE desktop_consent_keys SET state='revoked', revoked_at=now() WHERE id=%s", (k["id"],))
            err = CrmError("GRANT-EXPIRED", "키 등록 시간이 지났어요.", "PC 앱에서 다시 시도하세요.") if new_v.code == _SIG_EXPIRED else _consent_denied()
        else:
            if old:
                c.execute("UPDATE chat_consent_challenges SET state='revoked', settled_at=now() WHERE key_id=%s AND state='issued'", (old["id"],))
                c.execute("UPDATE desktop_consent_keys SET state='revoked', revoked_at=now() WHERE id=%s", (old["id"],))
            r = _one(c, "UPDATE desktop_consent_keys SET state='active', activated_at=now() WHERE id=%s AND state='pending' RETURNING id, state",
                     (k["id"],))
            if old:
                # 대화 하나로 J(JD1): 옛 키 서명(rotate)으로 이어짐이 증명된 회전 — 그 키에 선 허용을 새 키로 옮긴다.
                # PC 앱은 동의 창마다 키를 회전하므로, 옮기지 않으면 다른 공급자 동의 한 번에 서 있는 허용이 죽는다
                c.execute("UPDATE chat_provider_permits SET key_id=%s WHERE user_id=%s AND key_id=%s", (r["id"], uid, old["id"]))
            out = {"key_id": r["id"], "state": r["state"], "rotated": old is not None}
    if err:
        raise err
    return out


def consent_key_revoke(uid: str, installation_id: str) -> int:
    """웹 세션만으로 그 설치본의 pending·active 키와 issued challenge 를 폐기(권한을 줄이기만 하므로 장치 토큰을 요구하지 않는다).
    다시 등록하려면 begin·activate(장치 토큰 + PoP)를 처음부터 거친다. 반환 = 폐기한 키 수."""
    _check_installation(installation_id)
    with tx() as c:
        _user_lock(c, uid)
        return _consent_revoke(c, uid, installation_id)


def _consent_revoke(c, uid, installation_id) -> int:
    # 대화 하나로 J: 키 폐기 = 그 설치본(PC)의 서 있는 허용 전부를 함께 지운다(옛 PC 앱의 시작, 잠금 폐기도 닫힌 실패로 남는다)
    c.execute("DELETE FROM chat_provider_permits WHERE user_id=%s AND installation_id=%s", (uid, installation_id))
    c.execute("UPDATE chat_consent_challenges SET state='revoked', settled_at=now() WHERE user_id=%s AND installation_id=%s AND state='issued'",
              (uid, installation_id))
    cur = c.execute("UPDATE desktop_consent_keys SET state='revoked', revoked_at=now() WHERE user_id=%s AND installation_id=%s "
                    "AND state IN ('pending','active')", (uid, installation_id))
    return cur.rowcount


def consent_key_revoke_bound(uid: str, authorization: str, installation_id: str) -> int:
    """route 용 폐기 — 세션 uid·장치 Bearer·설치본 묶음을 같은 tx 에서 확인한 뒤 consent_key_revoke 와 같은 폐기를 한다.
    (consent_key_revoke 는 authorization 인자가 없어 route 의 「세션 + Bearer」 조건을 helper 에 넘길 수 없다.)"""
    _check_installation(installation_id)
    dev = _consent_bearer(authorization)
    with tx() as c:
        _user_lock(c, uid)
        _consent_bind(c, uid, dev, installation_id)
        return _consent_revoke(c, uid, installation_id)


def consent_challenge_issue(uid: str, authorization: str, installation_id: str, request_id: str) -> dict:
    """pending grant 하나에 대한 서명 요청. 반환 {challenge_id, claims}. session_id = grant.request_id(만들 대화의 client_session_id).
    같은 grant 의 옛 issued challenge 는 revoked. 만료 = min(지금+TTL, grant 만료)."""
    _check_installation(installation_id)
    if not isinstance(request_id, str) or not REQUEST_ID_RE.fullmatch(request_id):
        raise CrmError("ARG-INVALID", "허용 요청 값이 올바르지 않아요.")
    dev = _consent_bearer(authorization)
    with tx() as c:
        _user_lock(c, uid)
        device_id = _consent_bind(c, uid, dev, installation_id)
        key = _one(c, "SELECT id FROM desktop_consent_keys WHERE user_id=%s AND installation_id=%s AND state='active' FOR UPDATE", (uid, installation_id))
        if not key:
            raise _consent_denied()
        g = _one(c, "SELECT *, floor(extract(epoch from expires_at))::bigint AS exp_epoch "
                    "FROM chat_provider_grants WHERE user_id=%s AND request_id=%s FOR UPDATE", (uid, request_id))
        if (not g or g["device_id"] != device_id or g["state"] != "pending"
                or g.get("close_reason") is not None):   # F9: PC 가 닫은 grant 에는 새 서명 요청을 만들지 않는다
            raise CrmError("GRANT-INVALID", "이 PC 에 맞는 허용 요청이 없어요.")
        wall_now = _db_clock(c)
        now = int(wall_now.timestamp())
        exp = min(now + CONSENT_CHALLENGE_TTL_SECONDS, int(g["exp_epoch"]))
        if g["expires_at"] <= wall_now or exp <= now:
            raise CrmError("GRANT-EXPIRED", "허용 요청 시간이 지났어요.", "다시 요청하세요.")
        nonce = secrets.token_urlsafe(32)
        signed_model = g["model"] if g["model"] is not None else CONSENT_DEFAULT_MODEL
        claims = {"user_id": uid, "device_id": device_id, "session_id": g["request_id"], "provider": g["provider"],
                  "model": signed_model, "nonce": nonce, "expires_at": exp}
        try:
            _encode_consent(claims)   # 서명 형식에 안 맞는 값(model 의 '/' 등)은 challenge 를 만들지 않는다
        except TypeError:
            raise CrmError("GRANT-INVALID", "이 허용 요청은 PC 서명 형식에 맞지 않아요.") from None
        c.execute("UPDATE chat_consent_challenges SET state='revoked', settled_at=now() WHERE user_id=%s AND grant_id=%s AND state='issued'",
                  (uid, g["id"]))
        ch = _one(c, "INSERT INTO chat_consent_challenges (id,user_id,device_id,installation_id,key_id,grant_id,session_id,provider,model,nonce,expires_at) "
                     "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                  (_id("cc"), uid, device_id, installation_id, key["id"], g["id"], g["request_id"], g["provider"], signed_model, nonce, exp))
        return {"challenge_id": ch["id"], "claims": claims}


def consent_challenge_verify(uid: str, authorization: str, installation_id: str, nonce: str, signature) -> dict:
    """issued challenge 를 한 번 검증한다. 서명 대상 claims 는 DB 행에서 다시 만든다(요청 값을 쓰지 않는다).
    키·grant·설치본이 그새 바뀌었으면 revoked, 서명 불일치 rejected, 만료 expired — 모두 커밋되고 다시 쓸 수 없다.
    다른 사용자·장치·설치본의 호출은 상태를 바꾸지 않고 CONSENT_REQUIRED. 성공은 같은 트랜잭션에서 challenge=verified, grant=approved로 기록한다.
    grant 소비와 provider 실행은 별도 verifier 연결 전까지 차단한다."""
    _check_installation(installation_id)
    if not isinstance(nonce, str) or not NONCE_RE.fullmatch(nonce):
        raise CrmError("ARG-INVALID", "nonce 값이 올바르지 않아요.")
    dev = _consent_bearer(authorization)
    err = out = None
    with tx() as c:
        _user_lock(c, uid)
        device_id = _consent_bind(c, uid, dev, installation_id)
        ch = _one(c, "SELECT * FROM chat_consent_challenges WHERE user_id=%s AND nonce=%s FOR UPDATE", (uid, nonce))
        if not ch or ch["installation_id"] != installation_id or ch["device_id"] != device_id:
            raise _consent_denied()
        if ch["state"] != "issued":
            raise CrmError("GRANT-USED", "이미 처리한 동의 요청이에요.", "PC 앱에서 다시 시도하세요.")
        key = _one(c, "SELECT * FROM desktop_consent_keys WHERE id=%s FOR UPDATE", (ch["key_id"],))
        g = _one(c, "SELECT * FROM chat_provider_grants WHERE id=%s FOR UPDATE", (ch["grant_id"],))
        now = _db_now(c)
        if (not key or key["state"] != "active" or key["installation_id"] != installation_id or not g or g["state"] != "pending"
                or g.get("close_reason") is not None   # F9: PC 가 닫은 grant 는 서명이 맞아도 승인하지 않는다
                or (g["user_id"], g["device_id"], g["provider"], g["model"] if g["model"] is not None else CONSENT_DEFAULT_MODEL, g["request_id"])
                != (uid, ch["device_id"], ch["provider"], ch["model"], ch["session_id"])):
            state, err = "revoked", _consent_denied()
        else:
            claims = {"user_id": uid, "device_id": ch["device_id"], "session_id": ch["session_id"], "provider": ch["provider"],
                      "model": ch["model"], "nonce": ch["nonce"], "expires_at": int(ch["expires_at"])}
            v = _verify_consent(claims, signature, bytes(key["spki"]), now_seconds=now)
            if v.ok:
                approved = _one(c, "UPDATE chat_provider_grants SET state='approved', approved_at=clock_timestamp() "
                                "WHERE id=%s AND state='pending' AND expires_at > clock_timestamp() RETURNING id", (g["id"],))
                if approved:
                    state, out = "verified", {"challenge_id": ch["id"], "state": "verified", "grant_id": g["id"]}
                else:
                    state, err = "expired", CrmError("GRANT-EXPIRED", "허용 요청 시간이 지났어요.", "다시 요청하세요.")
            elif v.code == _SIG_EXPIRED:
                state, err = "expired", CrmError("GRANT-EXPIRED", "동의 요청 시간이 지났어요.", "PC 앱에서 다시 시도하세요.")
            else:
                state, err = "rejected", _consent_denied()
        c.execute("UPDATE chat_consent_challenges SET state=%s, settled_at=now() WHERE id=%s AND state='issued'", (state, ch["id"]))
    if err:
        raise err
    return out


def session_resume(uid: str, sid: str):
    s = session_get(uid, sid)
    if s["status"] != "active" or s.get("binding_version") != 2:
        raise CrmError("SESSION-CLOSED", "이 대화는 재개할 수 없어요.", "새 대화를 시작하세요.")
    return _session_out(s)


def sessions_list(uid: str) -> list:
    with tx() as c:
        return [_session_out(s) for s in _all(c, "SELECT * FROM chat_sessions WHERE user_id=%s ORDER BY created_at DESC, id LIMIT 50", (uid,))]


# 잠금 순서(모든 경로 같음): users(_user_lock) → chat_sessions(FOR NO KEY UPDATE) → chat_turns(FOR UPDATE).
# 세션 잠금은 NO KEY UPDATE — 자식 INSERT 의 FK 검사(KEY SHARE)와 충돌하지 않는다(턴을 잡은 채 메시지를 넣어도 세션 대기 없음).
def _session_get(c, uid, sid, lock=False):
    s = _one(c, "SELECT * FROM chat_sessions WHERE id=%s AND user_id=%s" + (" FOR NO KEY UPDATE" if lock else ""), (sid, uid))
    if not s:
        raise CrmError("NOT-FOUND", "그 대화를 찾을 수 없어요.")
    return s


def session_get(uid: str, sid: str) -> dict:
    with tx() as c:
        return dict(_session_get(c, uid, sid))


def _approval_closed():
    return CrmError("APPROVAL-CLOSED", "확인할 수 없는 작업이에요.")


def _approval_session(c, uid, sid):
    _user_lock(c, uid)
    session = _session_get(c, uid, sid, lock=True)
    if session["status"] != "active":
        raise _approval_closed()
    _require_consumed_session_consent(c, uid, session)
    return session


def _approval_slot(c, uid, sid, tid):
    """카드 한 장을 만들 수 있나 — 세션, 동의 재확인, 실행 중 턴, 한도(F6: 대기 20, 세션 100행). decide, write 공통."""
    _approval_session(c, uid, sid)
    if not _one(c, "SELECT id FROM chat_turns WHERE id=%s AND session_id=%s AND status='running' FOR UPDATE", (tid, sid)):
        raise _approval_closed()
    if _one(c, "SELECT count(*) AS n FROM chat_approvals WHERE user_id=%s AND session_id=%s "
               "AND state='pending' AND expires_at>clock_timestamp()", (uid, sid))["n"] >= APPROVAL_PENDING_LIMIT:
        raise CrmError("RATE-LIMIT", "확인 대기 중인 작업이 너무 많아요.")
    if _one(c, "SELECT count(*) AS n FROM chat_approvals WHERE user_id=%s AND session_id=%s", (uid, sid))["n"] >= APPROVAL_SESSION_LIMIT:
        raise CrmError("RATE-LIMIT", "이 대화의 확인 작업 한도에 도달했어요.")


def _write_shown(op, norm) -> dict:
    """F3: 정규화 params 의 모든 키를 한 줄씩 — 아는 키는 한국어 이름표, 모르는 키는 키 이름 그대로. 값은 자르거나 요약하지 않는다.
    이름표가 겹치면 키 이름으로, 그것도 겹치면 번호를 붙여 줄이 사라지지 않게 한다(줄 수 == 키 수)."""
    labels = _WRITE_LABELS.get(op, {})
    shown = {}
    for key, value in norm.items():
        label = labels.get(key, key)
        if label in shown:
            label = key
        n = 2
        base = label
        while label in shown:
            label = f"{base} ({n})"
            n += 1
        shown[label] = value
    return shown


# I 반영 R1~R3(2026-11-11): 덮어쓰기 write 카드는 대상의 "지금" 상태를 서버가 DB 에서 읽어 "바뀐 뒤"(F3 줄)와 함께 보인다.
# 지금 상태는 미리보기 해시에 들어가고, 확정 때 같은 잠금(users 행, 대상 행 FOR UPDATE) 안에서 다시 읽어 다르면 APPROVAL-STALE.
# 판별은 이름이 아니라 db 코드로 op마다 정했다(_WRITE_CURRENT 읽기 함수 표). 새로 만들기만 하는 op 은 _WRITE_CREATE_ONLY.
# 두 표 어디에도 없는 write op 은 카드를 만들지 않는다(애매하면 덮어쓰기로 다룬다 — 읽기 함수가 생길 때까지 닫힘).
# 값은 JSON 그대로(text, int, jsonb)만 — 시각 값을 넣지 않는다(jsonb 왕복 뒤 비교가 같아야 거짓 STALE 이 없다).
# 모델에게 가는 응답(prepare 결과, 오류 문구)에는 지금 값을 넣지 않는다. 지금 값은 사람이 보는 카드(approvals_list)에만 있다.
_NOW, _AFTER = "지금", "바뀐 뒤"
_TARGET_MISSING = {"대상": "찾을 수 없어요"}
_TARGET_TRASHED = {"대상": "휴지통에 있어요"}
_WRITE_CREATE_ONLY = frozenset({"question_add", "record_add", "candidates_propose", "source_create"})


def _cur_layout(c, uid, n):
    """layout_set, layout_reset — page_layouts.layout 의 그 페이지(저장 없음이면 기본)와 version 을 덮는다(db.layout_set, layout_reset)."""
    r = _one(c, "SELECT layout, version FROM page_layouts WHERE user_id=%s FOR UPDATE", (uid,))
    full = db._layout_up(r["layout"] if r else None)
    return {"화면": n.get("page"), "배치": full["pages"].get(n.get("page")), "배치 판": r["version"] if r else 0}


def _cur_display_name(c, uid, n):
    """display_name_set — users.display_name 을 덮는다(db.display_name_set UPDATE users)."""
    r = _one(c, "SELECT display_name FROM users WHERE id=%s", (uid,))
    return {"표시 이름": r["display_name"] if r else None}


def _cur_profile(c, uid, n):
    """profile_set — profile(user_id,key) upsert 로 value, status, source 를 덮는다(db.profile_set ON CONFLICT DO UPDATE). 행이 없으면 값 없음."""
    r = _one(c, "SELECT value, status, source FROM profile WHERE user_id=%s AND key=%s FOR UPDATE", (uid, n.get("key")))
    return {"프로필 항목": n.get("key"), "값": r["value"] if r else None, "상태": r["status"] if r else None,
            "어디서 알았나": r["source"] if r else None}


def _link_label(c, uid, kind, tid):
    if kind == "item":
        t = _one(c, "SELECT title FROM items WHERE user_id=%s AND id=%s", (uid, tid))
        return f"항목 {tid}" + (f" ({t['title']})" if t else " (찾을 수 없음)")
    if kind == "candidate":
        t = _one(c, "SELECT text FROM candidates WHERE user_id=%s AND id=%s", (uid, tid))
        return f"후보 {tid}" + (f" ({t['text']})" if t else " (찾을 수 없음)")
    return f"{kind} {tid}"


def _cur_record_attach(c, uid, n):
    """record_attach — 값을 준 칸만 덮는다: attach_to, axes = item_links(source_record_id, field_key) 전부 지우고 다시 넣기,
    use_at, unattached = records.notes 의 그 키(db.record_attach). 기록 제목(R2)과 바뀌는 칸의 지금 값."""
    rec = _one(c, "SELECT title, notes, trashed_at FROM records WHERE user_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE",
               (uid, n.get("record_id")))
    if not rec:
        return _TARGET_MISSING
    if rec["trashed_at"] is not None:
        return _TARGET_TRASHED
    out = {"기록 제목": rec["title"]}
    for key, label in (("attach_to", "붙일 곳"), ("axes", "축")):
        if n.get(key) is not None:
            links = _all(c, "SELECT target_item_id, target_candidate_id FROM item_links WHERE user_id=%s AND source_record_id=%s "
                            "AND field_key=%s ORDER BY id", (uid, n["record_id"], key))
            out[label] = [_link_label(c, uid, "item", ln["target_item_id"]) if ln["target_item_id"]
                          else _link_label(c, uid, "candidate", ln["target_candidate_id"]) for ln in links]
    notes = rec["notes"] or {}
    for key, label in (("use_at", "쓸 때"), ("unattached", "붙이지 않음")):
        if n.get(key) is not None:
            out[label] = notes.get(key)
    return out


def _cur_record_title(c, uid, n):
    """record_title_set — records.title 을 덮는다(db.record_title_set UPDATE records, 이력 한 줄)."""
    r = _one(c, "SELECT title, revision, trashed_at FROM records WHERE user_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE",
             (uid, n.get("record_id")))
    if not r:
        return _TARGET_MISSING
    if r["trashed_at"] is not None:
        return _TARGET_TRASHED
    return {"기록 제목": r["title"], "기록 판": r["revision"]}


def _cur_definition(c, uid, n):
    """definition_propose — object_defs.draft_doc 을 덮는다(새 제안이 이전 제안을 덮는다). object_id 가 없어도 같은 key 의
    미적용 행이 있으면 그 행의 제안을 덮는다(db.definition_propose). 그 행이 없으면 새로 만들기."""
    if n.get("object_id"):
        r = _one(c, "SELECT id, key, label, revision, draft_doc FROM object_defs WHERE user_id=%s AND id=%s FOR UPDATE",
                 (uid, n["object_id"]))
        if not r:
            return _TARGET_MISSING
    else:
        try:
            key = db.normalize_definition(json.loads(n.get("definition_json") or "{}"))["key"]
        except Exception:
            return None   # 정의가 틀리면 실행이 거절된다(만들 것도 덮을 것도 없음)
        r = _one(c, "SELECT id, key, label, revision, draft_doc FROM object_defs WHERE user_id=%s AND key=%s FOR UPDATE", (uid, key))
        if not r:
            return None
    return {"자료 종류 ID": r["id"], "key": r["key"], "이름": r["label"], "자료 종류 판": r["revision"], "대기 중 제안": r["draft_doc"]}


def _cur_item(c, uid, n):
    """item_propose(item_id 있음) — items.draft_doc 을 덮는다(그 항목의 대기 중 제안이 바뀐다, db.item_propose). item_id 없음 = 새로 만들기."""
    if not n.get("item_id"):
        return None
    r = _one(c, "SELECT title, body, revision, draft_doc, trashed_at FROM items WHERE user_id=%s AND id=%s FOR UPDATE",
             (uid, n["item_id"]))
    if not r:
        return _TARGET_MISSING
    if r["trashed_at"] is not None:
        return _TARGET_TRASHED
    return {"제목": r["title"], "본문": r["body"], "항목 판": r["revision"], "대기 중 제안": r["draft_doc"]}


def _cur_person(c, uid, n):
    """person_save(person_id 있음) — people.alias 를 덮는다(db.person_save UPDATE people). person_id 없음 = 새로 만들기."""
    if not n.get("person_id"):
        return None
    r = _one(c, "SELECT alias, revision, trashed_at FROM people WHERE user_id=%s AND id=%s AND purged_at IS NULL FOR UPDATE",
             (uid, n["person_id"]))
    if not r:
        return _TARGET_MISSING
    if r["trashed_at"] is not None:
        return _TARGET_TRASHED
    return {"별칭": r["alias"], "판": r["revision"]}


def _cur_reflection(c, uid, n):
    """source_reflection_save(reflection_id 있음) — source_reflections 의 source_id, kind, body 를 이력 없이 덮고 검토를 대기로 돌린다
    (db.source_reflection_save UPDATE). reflection_id 없음 = 새로 만들기."""
    if not n.get("reflection_id"):
        return None
    r = _one(c, "SELECT r.source_id, s.name AS source_name, r.kind, r.body, r.review, r.revision, r.trashed_at "
                "FROM source_reflections r LEFT JOIN sources s ON s.user_id=r.user_id AND s.id=r.source_id "
                "WHERE r.user_id=%s AND r.id=%s FOR UPDATE OF r", (uid, n["reflection_id"]))
    if not r:
        return _TARGET_MISSING
    if r["trashed_at"] is not None:
        return _TARGET_TRASHED
    return {"출처 ID": r["source_id"], "출처 이름": r["source_name"], "종류": r["kind"], "본문": r["body"],
            "검토": r["review"], "판": r["revision"]}


_WRITE_CURRENT = {
    "layout_set": _cur_layout, "layout_reset": _cur_layout, "display_name_set": _cur_display_name,
    "profile_set": _cur_profile, "record_attach": _cur_record_attach, "record_title_set": _cur_record_title,
    "definition_propose": _cur_definition, "item_propose": _cur_item, "person_save": _cur_person,
    "source_reflection_save": _cur_reflection,
}


def _write_current(c, uid, op, norm):
    """덮어쓰기 대상의 지금 상태(JSON 값) 또는 None(새로 만들기). 판별표에 없는 op 은 카드를 만들지 않는다."""
    if op in _WRITE_CREATE_ONLY:
        return None
    reader = _WRITE_CURRENT.get(op)
    if reader is None:
        raise _approval_closed()
    return reader(c, uid, norm)


def _write_preview(op, norm, current=None) -> dict:
    """F2: chat 전용 write 미리보기 — facade PREVIEWS, bind 와 무관. 서버가 정규화 params 와 DB 값으로만 만든다(모델 문구 없음).
    R1: 덮어쓰기면 shown = {지금: 대상의 지금 상태, 바뀐 뒤: F3 줄}, 해시 = [op, norm, 지금]. 새로 만들기면 F3 줄 그대로, 해시 = [op, norm]."""
    import facade
    after = _write_shown(op, norm)
    if current is None:
        return {"op": op, "shown": after, "impact": {"tier": "write"}, "irreversible": False,
                "hash": hashlib.sha256(facade._canon([op, norm])).hexdigest()}
    return {"op": op, "shown": {_NOW: current, _AFTER: after}, "impact": {"tier": "write"}, "irreversible": False,
            "hash": hashlib.sha256(facade._canon([op, norm, current])).hexdigest()}


def _write_spec(op):
    """write 카드가 될 수 있는 op 의 facade 등록부 항목. 등급이 write 가 아니거나 pc_connect 면 거절."""
    import facade
    spec = facade.OPS.get(op) if isinstance(op, str) else None
    if (not spec or op == "pc_connect" or spec.tier != "write" or _CHAT_TIERS.get(op) != "write"
            or op not in CHAT_WRITE_CARD_OPS):
        raise _approval_closed()
    return spec


def chat_write_prepare(uid, sid, tid, op, params):
    """F1, F2: 자유 대화의 write 요청을 카드로 저장만 한다. 이 경로는 실행하지 않는다. 사람이 웹 카드에서 확인해야 approval_confirm 이 실행한다."""
    import facade
    if not isinstance(params, dict) or any(k in params for k in ("uid", "user_id", "bind")):
        raise _approval_closed()
    spec = _write_spec(op)
    with db.tx_scope() as c:
        _approval_slot(c, uid, sid, tid)
        facade.validate(spec, params)
        norm = facade.normalize(op, params)
        preview = _write_preview(op, norm, _write_current(c, uid, op, norm))
        aid = _id("ca")
        c.execute("INSERT INTO chat_approvals (id,user_id,session_id,turn_id,op,params,preview,expires_at,kind) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+make_interval(secs => %s),'write')",
                  (aid, uid, sid, tid, op, Jsonb(norm), Jsonb(preview), APPROVAL_TTL_SECONDS))
        return {"status": "pending_confirmation", "approval_id": aid}


def _result_object(result) -> dict:
    """facade 결과 → jsonb 객체. structured_content 가 없으면(일부 op) 텍스트 한 덩어리의 JSON 객체를 읽는다."""
    if getattr(result, "isError", False):
        raise CrmError("MCP-ERROR", "작업을 완료하지 못했어요.")
    value = getattr(result, "structured_content", None)
    if value is None:
        content = getattr(result, "content", None) or []
        if len(content) == 1 and getattr(content[0], "type", "") == "text":
            try:
                value = json.loads(content[0].text)
            except (TypeError, ValueError):
                value = None
    if not isinstance(value, dict):
        raise CrmError("MCP-ERROR", "작업 결과를 확인하지 못했어요.")
    return value


def _created(op, result) -> dict:
    """F4: 확정된 write 결과에서 허용 키의 생성 id 만. 글이나 그 밖의 값은 넣지 않는다."""
    out = {}
    if isinstance(result, dict):
        for key, prefix in _WRITE_CREATED.get(op, ()):
            value = result.get(key)
            if isinstance(value, str) and _CREATED_ID_RE[prefix].fullmatch(value):
                out[key] = value
    return out


def approval_prepare(uid, sid, tid, op, params):
    """Create a server-owned preview only; this path never executes the action."""
    import facade
    if (op not in CHAT_APPROVABLE_OPS or not isinstance(params, dict)
            or any(k in params for k in ("uid", "user_id", "bind"))):
        raise _approval_closed()
    spec = facade.OPS.get(op)
    if not spec or spec.tier != "decide" or spec.bind != "hmac":
        raise _approval_closed()
    with db.tx_scope() as c:
        _approval_slot(c, uid, sid, tid)
        facade.validate(spec, params)
        norm = facade.normalize(op, params)
        preview = facade.preview(op, norm, uid)
        if preview.get("irreversible") is not False:
            raise _approval_closed()
        aid = _id("ca")
        c.execute("INSERT INTO chat_approvals (id,user_id,session_id,turn_id,op,params,preview,expires_at) "
                  "VALUES (%s,%s,%s,%s,%s,%s,%s,clock_timestamp()+make_interval(secs => %s))",
                  (aid, uid, sid, tid, op, Jsonb(norm), Jsonb(preview), APPROVAL_TTL_SECONDS))
        return {"status": "pending_confirmation", "approval_id": aid}


def approvals_list(uid, sid):
    with tx() as c:
        _session_get(c, uid, sid)
        rows = _all(c, "SELECT * FROM chat_approvals WHERE user_id=%s AND session_id=%s "
                       "AND (state IN ('confirmed','cancelled') OR (state='pending' AND expires_at>clock_timestamp())) "
                       "ORDER BY created_at,id LIMIT %s", (uid, sid, APPROVAL_SESSION_LIMIT))
        return [{"id": r["id"], "turn_id": r["turn_id"], "op": r["op"], "params": r["params"],
                 "shown": r["preview"]["shown"], "impact": r["preview"]["impact"],
                 "irreversible": r["preview"]["irreversible"], "status": r["state"],
                 "created_at": _iso(r["created_at"]), "expires_at": _iso(r["expires_at"]),
                 "finished_at": _iso(r["finished_at"]), "result": r["result"]} for r in rows]


def approval_confirm(uid, sid, aid):
    """Execute exactly the stored action, after current consent and preview revalidation."""
    import facade
    from chat_mcp_gateway import _mint_trusted_principal
    if not chat_mcp_enabled(uid):
        raise _off()
    with db.tx_scope() as c:
        session = _approval_session(c, uid, sid)
        row = _one(c, "SELECT * FROM chat_approvals WHERE id=%s AND user_id=%s AND session_id=%s FOR UPDATE", (aid, uid, sid))
        if not row or row["state"] != "pending" or row["expires_at"] <= _db_clock(c):
            raise _approval_closed()
        op, params, previous = row["op"], row["params"], row["preview"]
        if row.get("kind", "decide") == "write":
            value = _confirm_write(c, uid, sid, session, op, params, previous)
            c.execute("UPDATE chat_approvals SET state='confirmed',result=%s,finished_at=clock_timestamp() WHERE id=%s",
                      (Jsonb(value), aid))
            return {"status": "confirmed", "result": value}
        if (row.get("kind", "decide") != "decide" or op not in CHAT_APPROVABLE_OPS
                or not isinstance(params, dict) or not isinstance(previous, dict)):
            raise _approval_closed()
        spec = facade.OPS.get(op)
        if not spec or spec.tier != "decide" or spec.bind != "hmac":
            raise _approval_closed()
        now_preview = facade.preview(op, params, uid)
        if (previous.get("irreversible") is not False or now_preview.get("irreversible") is not False
                or not hmac.compare_digest(previous["bind"], now_preview["bind"])
                or previous != now_preview):
            raise CrmError("APPROVAL-STALE", "대상이 바뀌어 다시 확인해야 해요.")
        principal = _mint_trusted_principal(user_id=uid, device_id=session["device_id"], session_id=sid,
                                           provider=session["provider"], model=session["model"],
                                           expires_at=_db_clock(c) + timedelta(seconds=15))
        result = facade.dispatch("decide", op, params, principal, previous["bind"])
        if getattr(result, "isError", False):
            raise CrmError("MCP-ERROR", "작업을 완료하지 못했어요.")
        value = getattr(result, "structured_content", None)
        if not isinstance(value, dict):
            raise CrmError("MCP-ERROR", "작업 결과를 확인하지 못했어요.")
        c.execute("UPDATE chat_approvals SET state='confirmed',result=%s,finished_at=clock_timestamp() WHERE id=%s",
                  (Jsonb(value), aid))
        return {"status": "confirmed", "result": value}


def _confirm_write(c, uid, sid, session, op, params, previous):
    """F2: 저장한 params 를 다시 검증, 정규화해 해시와 shown 이 저장 때와 같아야 실행한다(다르면 APPROVAL-STALE).
    R1: 덮어쓰기 대상의 지금 상태를 같은 트랜잭션(users 행 잠금 + 대상 행 FOR UPDATE)에서 다시 읽어 해시에 넣는다 — 카드 뒤 대상이 바뀌면 STALE.
    실행 = facade.dispatch("write", op, params, 서버가 만든 principal, None) — guard, 쿼터, 도구 검사는 직접 MCP 와 같다."""
    import facade
    from chat_mcp_gateway import _mint_trusted_principal
    if not isinstance(params, dict) or not isinstance(previous, dict) or any(k in params for k in ("uid", "user_id", "bind")):
        raise _approval_closed()
    spec = _write_spec(op)
    try:
        facade.validate(spec, params)
        norm = facade.normalize(op, params)
    except Exception:
        raise CrmError("APPROVAL-STALE", "대상이 바뀌어 다시 확인해야 해요.") from None
    now_preview = _write_preview(op, norm, _write_current(c, uid, op, norm))
    if (previous.get("irreversible") is not False or not isinstance(previous.get("hash"), str)
            or not hmac.compare_digest(previous["hash"], now_preview["hash"])
            or norm != params or previous != now_preview):
        raise CrmError("APPROVAL-STALE", "대상이 바뀌어 다시 확인해야 해요.")
    principal = _mint_trusted_principal(user_id=uid, device_id=session["device_id"], session_id=sid,
                                       provider=session["provider"], model=session["model"],
                                       expires_at=_db_clock(c) + timedelta(seconds=15))
    return _result_object(facade.dispatch("write", op, params, principal, None))


def approval_cancel(uid, sid, aid):
    with db.tx_scope() as c:
        _user_lock(c, uid)
        _session_get(c, uid, sid, lock=True)
        row = _one(c, "SELECT state,expires_at FROM chat_approvals WHERE id=%s AND user_id=%s AND session_id=%s FOR UPDATE", (aid, uid, sid))
        if not row or row["state"] != "pending" or row["expires_at"] <= _db_clock(c):
            raise _approval_closed()
        c.execute("UPDATE chat_approvals SET state='cancelled',finished_at=clock_timestamp() WHERE id=%s", (aid,))
        return {"status": "cancelled"}


def _last_seq(c, tid) -> int:
    return _one(c, "SELECT COALESCE(max(seq), 0) AS n FROM chat_events WHERE turn_id=%s", (tid,))["n"]


def _finish(c, t, status, code=None):
    """턴 끝 — status·ended_at + 답 메시지(delta 합). code 가 있으면 서버가 error 이벤트를 마지막 seq 로 넣는다. 넣은 이벤트(또는 None)."""
    ev = None
    if code:
        seq = _last_seq(c, t["id"]) + 1
        r = _one(c, "INSERT INTO chat_events (turn_id,seq,kind,data) VALUES (%s,%s,'error',%s) RETURNING created_at",
                 (t["id"], seq, json.dumps({"code": code})))
        c.execute("UPDATE chat_turns SET n_events=n_events+1, n_bytes=n_bytes+%s WHERE id=%s", (_jbytes({"code": code}), t["id"]))
        ev = {"turn_id": t["id"], "seq": seq, "kind": "error", "data": {"code": code}, "created_at": _iso(r["created_at"])}
    c.execute("UPDATE chat_turns SET status=%s, ended_at=now() WHERE id=%s", (status, t["id"]))
    body = _one(c, "SELECT COALESCE(string_agg(data->>'text', '' ORDER BY seq), '') AS b FROM chat_events "
                   "WHERE turn_id=%s AND kind='delta'", (t["id"],))["b"]
    c.execute("INSERT INTO chat_messages (id,session_id,turn_id,role,body) VALUES (%s,%s,%s,'assistant',%s) ON CONFLICT (turn_id, role) DO NOTHING",
              (_id("cm"), t["session_id"], t["id"], body))
    return ev


def _close_session(c, sid, code="SESSION-CLOSED"):
    """세션 닫기 — 실행 중 턴도 끝낸다(세션을 이미 잠근 뒤 부른다). 넣은 이벤트 목록."""
    c.execute("UPDATE chat_sessions SET status='closed' WHERE id=%s", (sid,))
    return [_finish(c, t, "failed", code) for t in _all(c, "SELECT * FROM chat_turns WHERE session_id=%s AND status='running' FOR UPDATE", (sid,))]


def sweep(uid: str, sid: str) -> list:
    """유휴 턴 정리만(SSE 연결·세션 목록 때) — 화면은 실행 중이면 보내기를 막으니 다음 입력을 기다리지 않는다. 넣은 이벤트 목록."""
    with tx() as c:
        s = _session_get(c, uid, sid, lock=True)
        return [e for e in _sweep_idle(c, s["id"]) if e]


def _sweep_idle(c, sid):
    """이벤트 없이 TURN_IDLE_SECONDS 지난 running 턴 → failed(TURN-TIMEOUT). 넣은 이벤트 목록."""
    rows = _all(c, "SELECT t.* FROM chat_turns t WHERE t.session_id=%s AND t.status='running' AND GREATEST(t.created_at, "
                   "COALESCE((SELECT max(e.created_at) FROM chat_events e WHERE e.turn_id=t.id), t.created_at)) "
                   "< now() - make_interval(secs => %s) FOR UPDATE", (sid, TURN_IDLE_SECONDS))
    return [_finish(c, t, "failed", "TURN-TIMEOUT") for t in rows]


def turn_create(uid: str, sid: str, text, client_turn_id, *, connected, capable=None) -> dict:
    out = _turn_create(uid, sid, text, client_turn_id, connected, capable)
    if isinstance(out, list):   # 장치 철회 — 세션을 닫았다(커밋). 끝낸 턴 이벤트는 거절과 함께 넘겨 SSE 로 보낸다
        e = CrmError("DEVICE-GONE", "이 대화의 PC 연결이 해제됐어요.", "새 대화를 시작하세요.")
        e.events = out
        raise e
    return out


def _turn_create(uid, sid, text, client_turn_id, connected, capable=None):
    """턴 만들기. connected(device_id) → bool — 장치 WS 가 붙어 있나(허브). 반환 {turn, created, session, events(서버가 넣은 끝 이벤트)}."""
    if not isinstance(text, str) or not text.strip():
        raise CrmError("ARG-INVALID", "보낼 글이 비었어요.")
    if _cp(text) > TEXT_MAX_CHARS:
        raise CrmError("TEXT-LIMIT", f"한 번에 {TEXT_MAX_CHARS}자까지 보낼 수 있어요.")
    if not isinstance(client_turn_id, str) or not CLIENT_TURN_ID_RE.match(client_turn_id):
        raise CrmError("ARG-INVALID", "client_turn_id 가 필요해요(영문·숫자·-·_ 1~64자).")
    with tx() as c:
        _user_lock(c, uid)
        s = _session_get(c, uid, sid, lock=True)
        old = _one(c, "SELECT * FROM chat_turns WHERE session_id=%s AND client_turn_id=%s", (sid, client_turn_id))
        if old:   # 같은 client_turn_id = 같은 턴(멱등). 다시 보내지 않는다(D6)
            return {"turn": dict(old), "created": False, "session": dict(s), "events": []}
        if s["status"] != "active":
            raise CrmError("SESSION-CLOSED", "끝난 대화예요.", "새 대화를 시작하세요.")
        if s.get("binding_version", 0) != 2:
            raise CrmError("PROVIDER-UNAVAILABLE", "이전 형식의 대화는 새 요청을 시작할 수 없어요.", "새 대화를 시작하세요.")
        if s["device_id"] not in _active_devices(c, uid):   # 닫기는 커밋하고(트랜잭션을 정상으로 끝낸 뒤) 거절한다
            return _close_session(c, sid, "DEVICE-GONE")
        if s.get("provider") in GRANT_PROVIDERS:
            _require_consumed_session_consent(c, uid, s)
        elif s.get("provider") != "fake":
            raise CrmError("PROVIDER-UNAVAILABLE", "이 공급자를 사용할 수 없어요.", "새 대화를 시작하세요.")
        if not connected(s["device_id"]):
            raise CrmError("DEVICE-OFFLINE", "PC 가 연결돼 있지 않아요.", "PC 에서 my-crm 에이전트 대화를 켜세요.")
        if not capable or not capable(s):
            raise CrmError("PROVIDER-UNAVAILABLE", "이 대화에 고정한 AI 또는 모델을 PC가 제공하지 않아요.", "연결 상태와 선택을 확인하세요.")
        evs = [e for e in _sweep_idle(c, sid) if e]
        if _one(c, "SELECT 1 FROM chat_turns WHERE session_id=%s AND status='running'", (sid,)):
            raise CrmError("TURN-BUSY", "앞 답이 아직 끝나지 않았어요.", "끝나거나 중지한 뒤 보내세요.")
        n = _one(c, "SELECT count(*) AS n FROM chat_turns t JOIN chat_sessions s ON s.id=t.session_id "
                    "WHERE s.user_id=%s AND t.created_at > now() - interval '60 seconds'", (uid,))["n"]
        if n >= TURNS_PER_MINUTE:
            raise CrmError("RATE-LIMIT", f"1분에 {TURNS_PER_MINUTE}번까지 보낼 수 있어요.", "잠시 뒤 다시 보내세요.")
        t = _one(c, "INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,%s) RETURNING *", (_id("ct"), sid, client_turn_id))
        c.execute("INSERT INTO chat_messages (id,session_id,turn_id,role,body) VALUES (%s,%s,%s,'user',%s)", (_id("cm"), sid, t["id"], text))
        c.execute("UPDATE chat_sessions SET last_at=now() WHERE id=%s", (sid,))
        outcomes = _all(c, "SELECT id,op,state,kind,result FROM chat_approvals WHERE user_id=%s AND session_id=%s "
                           "AND state IN ('confirmed','cancelled') ORDER BY finished_at DESC,id DESC LIMIT %s",
                        (uid, sid, APPROVAL_SESSION_LIMIT))
        safe_outcomes, size = [], 2   # 최신부터(F13). size = agent 꼴 JSON 배열 바이트([] + 항목 + 쉼표)
        for row in outcomes:   # 승인 가능 집합 24개(decide 10 + write 14). 종류와 op 등급이 맞는 행만
            if not ((row["kind"] == "decide" and row["op"] in CHAT_APPROVABLE_OPS)
                    or (row["kind"] == "write" and row["op"] in CHAT_WRITE_CARD_OPS)):
                continue
            item = {"id": row["id"], "op": row["op"], "status": row["state"]}
            if row["kind"] == "write" and row["state"] == "confirmed":
                created = _created(row["op"], row["result"])   # F4: 정해진 id 키만, 다음 턴에 잇는다
                if created:
                    item["created"] = created
            n = len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + (1 if safe_outcomes else 0)
            if size + n > APPROVAL_OUTCOMES_JSON_MAX:
                break   # 이보다 오래된 행은 뺀다
            size += n
            safe_outcomes.append(item)
        safe_outcomes.reverse()   # 모델에는 시간순으로
        return {"turn": dict(t), "created": True, "session": dict(s), "events": evs, "text": text,
                "approval_outcomes": safe_outcomes}


def turn_fail(tid: str, code: str):
    """서버가 턴을 끝낸다(보내기 실패 등). running 이 아니면 None."""
    with tx() as c:
        t = _lock_turn(c, tid)
        if not t or t["status"] != "running":
            return None
        return _finish(c, t, "failed", code)


def _lock_turn(c, tid):
    """턴 잠금 — 세션 먼저(NO KEY UPDATE), 그다음 턴(FOR UPDATE). 두 문장으로 나눠 잠금 순서를 모든 경로와 맞춘다."""
    sid = _one(c, "SELECT session_id FROM chat_turns WHERE id=%s", (tid,))
    if not sid:
        return None
    s = _one(c, "SELECT user_id, device_id FROM chat_sessions WHERE id=%s FOR NO KEY UPDATE", (sid["session_id"],))
    t = _one(c, "SELECT * FROM chat_turns WHERE id=%s FOR UPDATE", (tid,))
    return {**t, "user_id": s["user_id"], "device_id": s["device_id"]} if t and s else None


def turn_stop(uid: str, sid: str):
    """실행 중 턴을 바로 stopped(PC 연결과 무관). 반환 (turn 행 | None, 넣은 이벤트 | None)."""
    with tx() as c:
        s = _session_get(c, uid, sid, lock=True)
        t = _one(c, "SELECT * FROM chat_turns WHERE session_id=%s AND status='running' FOR UPDATE", (s["id"],))
        if not t:
            return None, None, s
        return dict(t), _finish(c, t, "stopped", "STOPPED"), s


def provider_set(sid: str, provider: str):
    with tx() as c:
        c.execute("UPDATE chat_sessions SET provider=%s WHERE id=%s AND provider IS NULL", (provider, sid))


def messages(uid: str, sid: str, after: str | None) -> list:
    with tx() as c:
        _session_get(c, uid, sid)
        args, cond = [sid], ""
        if after:
            t = _one(c, "SELECT created_at, id FROM chat_turns WHERE id=%s AND session_id=%s", (after, sid))
            if not t:
                raise CrmError("ARG-INVALID", "after 는 이 대화의 turn_id 여야 해요.")
            cond, args = " AND (t.created_at, t.id) > (%s, %s)", [sid, t["created_at"], t["id"]]
        rows = _all(c, "SELECT m.id, m.turn_id, m.role, m.body, m.created_at, t.status FROM chat_messages m JOIN chat_turns t ON t.id=m.turn_id "
                       f"WHERE m.session_id=%s{cond} ORDER BY t.created_at, t.id, (m.role='assistant')", tuple(args))
    return [{"id": r["id"], "turn_id": r["turn_id"], "role": r["role"], "body": r["body"], "created_at": _iso(r["created_at"]),
             "turn_status": r["status"]} for r in rows]


def parse_cursor(raw: str | None):
    """"<turn_id>:<seq>" → (turn_id, seq) · 없거나 틀리면 None(처음부터)."""
    m = re.match(r"^(ct_[0-9a-f]{24}):(\d{1,9})$", (raw or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


def replay(uid: str, sid: str, cursor) -> list:
    """SSE 재생 — 커서 뒤의 SSE 항목 목록 [(id, event, data)]. 턴 시작 = seq 0(사용자 글), 그 뒤 이벤트 seq 순.
    상한: 최근 REPLAY_TURNS 턴·REPLAY_BYTES(n_bytes 합) — 넘으면 앞을 자르고 맨 앞에 trimmed(id 없음, 앞부분은 messages API).
    이벤트는 한 쿼리로 읽는다."""
    with tx() as c:
        _session_get(c, uid, sid)
        cols = "SELECT t.id, t.client_turn_id, t.created_at, t.n_bytes, m.body FROM chat_turns t LEFT JOIN chat_messages m ON m.turn_id=t.id AND m.role='user' "
        rows = _all(c, cols + "WHERE t.session_id=%s ORDER BY t.created_at DESC, t.id DESC LIMIT %s", (sid, REPLAY_TURNS + 1))
        more = len(rows) > REPLAY_TURNS   # 최근 N턴보다 앞이 더 있다
        rows = list(reversed(rows[:REPLAY_TURNS]))
        ct = _one(c, cols + "WHERE t.session_id=%s AND t.id=%s", (sid, cursor[0])) if cursor else None   # 커서 턴은 따로
        idx = next((i for i, t in enumerate(rows) if ct and t["id"] == ct["id"]), None)
        if ct and idx is not None:
            cand, cut = rows[idx:], False
        else:   # 커서 없음·모름 = 최근 N턴 · 커서가 그보다 앞 = 최근 N턴(사이는 생략)
            cand, cut = rows, more or bool(ct)
        pick, size = [], 0
        for t in reversed(cand):
            if pick and size + t["n_bytes"] > REPLAY_BYTES:
                break
            pick.append(t)
            size += t["n_bytes"]
        pick.reverse()
        cur = cursor if idx is not None and pick and pick[0]["id"] == cursor[0] else None
        out = []
        if cut or len(pick) < len(cand):
            out.append((None, "trimmed", {"first_turn_id": pick[0]["id"]}))
        evs = {}
        if pick:
            for e in _all(c, "SELECT turn_id, seq, kind, data, created_at FROM chat_events WHERE turn_id = ANY(%s) AND (turn_id <> %s OR seq > %s) "
                             "ORDER BY turn_id, seq", ([t["id"] for t in pick], cur[0] if cur else "", cur[1] if cur else 0)):
                evs.setdefault(e["turn_id"], []).append(e)
        for t in pick:
            if not (cur and t["id"] == cur[0]):
                out.append((f"{t['id']}:0", "turn", {"turn_id": t["id"], "client_turn_id": t["client_turn_id"], "text": t["body"] or "",
                                                     "created_at": _iso(t["created_at"])}))
            for e in evs.get(t["id"], []):
                out.append((f"{t['id']}:{e['seq']}", e["kind"], {"turn_id": t["id"], "seq": e["seq"], "data": e["data"],
                                                               "created_at": _iso(e["created_at"])}))
    return out


def ingest(dev: dict, turn_id, seq, kind, data) -> dict:
    """PC 이벤트 하나 저장. 반환 {state: stored|dup|gap|dropped|foreign, ack, event?, stop?(서버가 끝냈으니 PC 에 turn.stop), session_id?}.
    foreign = 남의 턴·다른 장치 세션(저장·ack 없음). dropped = 끝난 턴(버리고 ack)."""
    if not isinstance(turn_id, str) or not isinstance(seq, int) or isinstance(seq, bool) or seq < 1 or kind not in KINDS \
            or not isinstance(data, dict):
        raise CrmError("ARG-INVALID", "event 모양이 틀렸어요.")
    with tx() as c:
        t = _lock_turn(c, turn_id)
        if not t or t["user_id"] != dev["user_id"] or t["device_id"] != dev["id"]:
            return {"state": "foreign"}
        last = _last_seq(c, turn_id)
        base = {"session_id": t["session_id"], "user_id": t["user_id"]}
        if t["status"] != "running":
            return {**base, "state": "dropped", "ack": max(seq, last)}
        if seq <= last:
            return {**base, "state": "dup", "ack": last}
        if seq != last + 1:
            return {**base, "state": "gap", "ack": last}
        nb = _jbytes(data)
        if t["n_events"] + 1 > EVENTS_PER_TURN or t["n_bytes"] + nb > TURN_BYTES_MAX:   # 누계 열 — O(1)
            ev = _finish(c, t, "failed", "TURN-LIMIT")
            return {**base, "state": "stored", "ack": seq, "event": ev, "stop": True}
        r = _one(c, "INSERT INTO chat_events (turn_id,seq,kind,data) VALUES (%s,%s,%s,%s) ON CONFLICT (turn_id, seq) DO NOTHING RETURNING created_at",
                 (turn_id, seq, kind, json.dumps(data, ensure_ascii=False)))
        if not r:
            return {**base, "state": "dup", "ack": seq}
        c.execute("UPDATE chat_turns SET n_events=n_events+1, n_bytes=n_bytes+%s WHERE id=%s", (nb, turn_id))
        if kind in TERMINAL_STATUS:
            status = "stopped" if kind == "error" and data.get("code") == "STOPPED" else TERMINAL_STATUS[kind]
            _finish(c, t, status)
        c.execute("UPDATE chat_sessions SET last_at=now() WHERE id=%s", (t["session_id"],))
        return {**base, "state": "stored", "ack": seq,
                "event": {"turn_id": turn_id, "seq": seq, "kind": kind, "data": data, "created_at": _iso(r["created_at"])}}


def session_ref_set(dev: dict, sid, ref) -> bool:
    if not isinstance(sid, str) or not isinstance(ref, str) or not CLI_REF_RE.match(ref):
        return False
    with tx() as c:
        r = c.execute("UPDATE chat_sessions SET cli_session_ref=%s WHERE id=%s AND user_id=%s AND device_id=%s",
                      (ref, sid, dev["user_id"], dev["id"]))
        return r.rowcount == 1


def purge() -> int:
    """보관 30일(생성일 기준) 지난 대화 기록 삭제 — main.purge_once 회차. 30일 넘은 running 턴은 먼저 failed 로 끝낸 뒤 지운다. 지운 행 수 합."""
    n = 0
    with tx() as c:   # 30일 넘게 running(유휴 정리를 못 만난 턴) — 먼저 failed 로 끝낸다(잠금 순서 = 세션 → 턴)
        for r in _all(c, "SELECT id FROM chat_turns WHERE status='running' AND created_at < now() - make_interval(days => %s)", (KEEP_DAYS,)):
            t = _lock_turn(c, r["id"])
            if t and t["status"] == "running":
                _finish(c, t, "failed", "TURN-TIMEOUT")
    with tx() as c:
        for sql in ("DELETE FROM chat_turns WHERE status <> 'running' AND created_at < now() - make_interval(days => %s)",
                    "DELETE FROM chat_messages WHERE created_at < now() - make_interval(days => %s)",
                    "DELETE FROM chat_events WHERE created_at < now() - make_interval(days => %s)",
                    "DELETE FROM chat_sessions s WHERE created_at < now() - make_interval(days => %s) "
                    "AND NOT EXISTS (SELECT 1 FROM chat_turns t WHERE t.session_id=s.id)"):
            n += c.execute(sql, (KEEP_DAYS,)).rowcount
    # I 반영 R8(2026-11-11 원작자): PC 허용 기록도 30일. 참조 = challenge 가 key_id, grant_id 를 FK(ON DELETE CASCADE)로 가리킨다.
    # 세션은 grant 를 client_session_id=request_id 로만 찾는다(FK 없음) — 지운 뒤 남은 세션의 동의 재확인은 CONSENT_REQUIRED 로 닫힌다(허용).
    # 순서: challenge(생성 30일) → grant(생성 30일, 남은 challenge 는 CASCADE) → 키(폐기 또는 PoP 만료 뒤 30일만).
    # 쓰고 있는 키(active)와 아직 PoP 기한 안의 pending 키는 지우지 않는다. 폐기, 만료 30일 뒤의 키를 가리키는 challenge 는 그보다 먼저 만든 것이다.
    with tx() as c:
        for sql in ("DELETE FROM chat_consent_challenges WHERE created_at < now() - make_interval(days => %s)",
                    "DELETE FROM chat_provider_grants WHERE created_at < now() - make_interval(days => %s)",
                    "DELETE FROM desktop_consent_keys WHERE (state='revoked' AND revoked_at < now() - make_interval(days => %s)) "
                    "OR (state='pending' AND pop_expires_at < extract(epoch FROM now() - make_interval(days => %s)))"):
            n += c.execute(sql, (KEEP_DAYS,) * sql.count("%s")).rowcount
    return n


# ── 허브(프로세스 메모리 — Render 1 인스턴스) ─────────────────────────

class _Sub:
    def __init__(self, uid, sid, device_id=None):
        self.uid, self.sid, self.device_id = uid, sid, device_id
        self.q: asyncio.Queue = asyncio.Queue()
        self.bytes = 0
        self.closed = asyncio.Event()

    def put(self, item, size):
        if self.closed.is_set():
            return
        if self.bytes + size > LIVE_BUFFER_BYTES:   # 느린 구독 — 닫고 클라이언트가 Last-Event-ID 로 DB 재생
            return self.close()
        self.bytes += size
        self.q.put_nowait((item, size))

    def close(self, reason=None):
        """reason = "replaced"(다른 탭이 새로 붙음 — 스트림이 event: replaced 를 보내고 끝난다) · None(그 밖)."""
        if not self.closed.is_set():
            self.closed.set()
            self.q.put_nowait(("close", reason))   # 기다리는 스트림을 깨운다


class _Dev:
    def __init__(self, ws: WebSocket, dev: dict):
        self.ws, self.dev = ws, dev
        self.lock = asyncio.Lock()
        self.providers: list = []
        self.v2 = False
        self.agent_version = None
        self.capabilities: list = []
        self.closed = False
        self.stop_sent: set = set()   # 이 연결에서 turn.stop 을 보낸 turn_id(끝난 턴 이벤트가 오면 한 번만 다시 알린다)

    async def send(self, obj) -> bool:
        if self.closed:
            return False
        try:
            async with self.lock:
                await self.ws.send_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
            return True
        except Exception:
            self.closed = True
            return False


class Hub:
    def __init__(self):
        self.devs: dict = {}    # (user_id, device_id) → _Dev
        self.subs: dict = {}    # user_id → _Sub

    def connected(self, uid, did) -> bool:
        d = self.devs.get((uid, did))
        return bool(d and not d.closed)

    def dev(self, uid, did):
        d = self.devs.get((uid, did))
        return d if d and not d.closed else None

    async def attach(self, d: _Dev):
        key = (d.dev["user_id"], d.dev["id"])
        old = self.devs.get(key)
        self.devs[key] = d
        if old and old is not d:   # 장치당 1연결 — 새 연결이 옛 연결을 대체
            old.closed = True
            try:
                await old.ws.close(code=4000)
            except Exception:
                pass
        self.notify_pc(d.dev["user_id"], d.dev["id"])

    def detach(self, d: _Dev):
        key = (d.dev["user_id"], d.dev["id"])
        d.closed = True
        if self.devs.get(key) is d:
            del self.devs[key]
            self.notify_pc(d.dev["user_id"], d.dev["id"])

    def subscribe(self, uid, sid, device_id=None) -> _Sub:
        old = self.subs.get(uid)
        if old:   # 사용자당 활성 SSE 1 — 새 연결이 옛 연결을 닫는다(옛 쪽은 event: replaced 를 받고 다시 붙지 않는다)
            old.close("replaced")
        s = self.subs[uid] = _Sub(uid, sid, device_id)
        return s

    def unsubscribe(self, s: _Sub):
        s.close()
        if self.subs.get(s.uid) is s:
            del self.subs[s.uid]

    def publish(self, uid, sid, sse_id, event, data):
        s = self.subs.get(uid)
        if s and s.sid == sid:   # 그 사용자·그 세션 구독에만
            frame = _sse(sse_id, event, data)
            s.put((sse_id, frame), len(frame))

    def publish_event(self, uid, sid, ev):
        if ev:
            self.publish(uid, sid, f"{ev['turn_id']}:{ev['seq']}", ev["kind"], {k: ev[k] for k in ("turn_id", "seq", "data", "created_at")})

    def notify_pc(self, uid, did):
        s = self.subs.get(uid)
        if s and s.device_id == did:   # 그 세션의 장치만 — 다른 PC 가 붙거나 끊겨도 표시가 뒤집히지 않는다
            frame = _sse(None, "pc", {"device_id": did, "connected": self.connected(uid, did)})
            s.put((None, frame), len(frame))


hub = Hub()


def _sse(sse_id, event, data) -> bytes:
    head = (f"id: {sse_id}\n" if sse_id else "") + f"event: {event}\n"
    return (head + "data: " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode("utf-8")


# ── HTTP·WS 경로 ──────────────────────────────────────────

def _err(e: CrmError, status=None):
    return JSONResponse({"code": e.code, "msg": e.message, "action": e.action}, status_code=status or HTTP.get(e.code, 400),
                        headers={"cache-control": "no-store"})


class Routes:
    """웹·장치 경로. site = web.Web(쿠키 세션 uid_of · same_origin). 사용 집계 = web._usage(이름 web:chat_* · api:chat_ws)."""

    def __init__(self, site, usage):
        self.site, self.usage = site, usage

    def routes(self) -> list:
        u = self.usage
        return [
            Route("/api/chat/sessions", u("web:chat_sessions", self.sessions), methods=["GET", "POST"]),
            Route("/api/chat/capabilities", u("web:chat_capabilities", self.capabilities)),
            Route("/api/chat/sessions/{sid}/messages", u("web:chat_messages", self.messages)),
            Route("/api/chat/sessions/{sid}/approvals", u("web:chat_approvals", self.approvals)),
            Route("/api/chat/sessions/{sid}/approvals/{aid}/confirm", u("web:chat_approval_confirm", self.approval_confirm), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/approvals/{aid}/cancel", u("web:chat_approval_cancel", self.approval_cancel), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/turns", u("web:chat_turns", self.turns), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/stop", u("web:chat_stop", self.stop), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/stream", u("web:chat_stream", self.stream)),
            Route("/api/chat/grants", u("web:chat_grant", self.grant), methods=["POST"]),
            Route("/api/chat/grants/{request_id}", u("web:chat_grant_status", self.grant_status)),
            Route("/api/chat/permits", u("web:chat_permits", self.permits)),
            Route("/api/chat/permits/revoke", u("web:chat_permit_revoke", self.permit_revoke), methods=["POST"]),
            Route("/api/chat/mcp", u("web:chat_mcp", self.chat_mcp), methods=["POST"]),
            Route(LAUNCH_AUTHORIZATION_PATH, u("web:chat_launch_authorization", self.launch_authorization), methods=["POST"]),
            Route("/api/chat/consent/keys/begin", u("web:chat_consent_key_begin", self.consent_key_begin), methods=["POST"]),
            Route("/api/chat/consent/keys/activate", u("web:chat_consent_key_activate", self.consent_key_activate), methods=["POST"]),
            Route("/api/chat/consent/keys/revoke", u("web:chat_consent_key_revoke", self.consent_key_revoke), methods=["POST"]),
            Route("/api/chat/consent/challenges/issue", u("web:chat_consent_issue", self.consent_issue), methods=["POST"]),
            Route("/api/chat/consent/challenges/verify", u("web:chat_consent_verify", self.consent_verify), methods=["POST"]),
            WebSocketRoute("/api/device/chat/ws", self.device_ws),
        ]

    async def _gate(self, request, post=False):
        """스위치(503) → 세션(401) → POST Origin(403). (uid, None) | (None, 응답)."""
        if not enabled():
            return None, _err(_off())
        uid = await self.site.uid_of(request)
        if uid is None:
            return None, _err(CrmError("UNAUTHORIZED", "로그인이 필요해요."))
        if not await run_in_threadpool(enabled, uid):   # 프로필 권한(2026-11-12) — 조직은 켜졌는데 이 사용자 프로필에 없으면 같은 SWITCH-OFF
            return None, _err(_off())
        if post and not self.site.same_origin(request):
            return None, _err(CrmError("ORIGIN", "다른 사이트에서 온 요청이에요."))
        return uid, None

    @staticmethod
    async def _body(request) -> dict:
        raw = await request.body()
        if len(raw) > 64 * 1024:
            raise CrmError("TEXT-LIMIT", "요청 본문이 너무 커요.")
        try:
            b = json.loads(raw.decode("utf-8")) if raw.strip() else {}
        except ValueError:
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.") from None
        if not isinstance(b, dict):
            raise CrmError("ARG-INVALID", "JSON 객체가 필요해요.")
        return b

    async def sessions(self, request):
        uid, err = await self._gate(request, post=request.method == "POST")
        if err:
            return err
        try:
            if request.method == "POST":
                body = await self._body(request)
                if body.get("operation") in ("new", "resume"):
                    if body["operation"] == "resume":
                        out = await run_in_threadpool(session_resume, uid, body.get("session_id"))
                        out["connected"] = hub.connected(uid, out["device_id"])
                        return JSONResponse(out, headers={"cache-control": "no-store"})
                    did, provider, model, client_id = (body.get("device_id"), body.get("provider"), body.get("model"), body.get("client_session_id"))
                    d = hub.dev(uid, did) if isinstance(did, str) else None
                    capable = bool(d and d.v2 and _supports(d.capabilities, provider, model))
                    out, closed, created = await run_in_threadpool(session_new, uid, did, provider, model, client_id, capability_ok=capable)
                    for old_sid, ev in closed:
                        hub.publish_event(uid, old_sid, ev)
                    out["connected"] = hub.connected(uid, did)
                    out["created"] = created
                    return JSONResponse(out, status_code=201 if created else 200, headers={"cache-control": "no-store"})
                did = body.get("device_id")
                if did is not None and not isinstance(did, str):
                    raise CrmError("ARG-INVALID", "device_id 는 글자여야 해요.")
                out, closed = await run_in_threadpool(session_open, uid, did)
                for old_sid, ev in closed:   # 닫은 세션의 실행 중 턴 끝 — 그 세션을 보던 SSE 에 알린다
                    hub.publish_event(uid, old_sid, ev)
                out["connected"] = hub.connected(uid, out["device_id"])
                return JSONResponse(out, headers={"cache-control": "no-store"})
            rows = await run_in_threadpool(sessions_list, uid)
            for r in rows:
                r["connected"] = r["status"] == "active" and hub.connected(uid, r["device_id"])
                if r["status"] == "active":   # 유휴 턴 정리 — 화면은 실행 중이면 보내기를 막으니 다음 입력을 기다리지 않는다
                    for ev in await run_in_threadpool(sweep, uid, r["session_id"]):
                        hub.publish_event(uid, r["session_id"], ev)
            return JSONResponse({"sessions": rows}, headers={"cache-control": "no-store"})
        except CrmError as e:
            return _err(e)

    async def capabilities(self, request):
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            ids = await run_in_threadpool(_active_devices_for_user, uid)
            allowed = {}
            for p in await run_in_threadpool(permits_live, uid):
                allowed.setdefault(p["device_id"], []).append(p["provider"])
            devices = []
            for did in ids:
                d = hub.dev(uid, did)
                if d and d.v2:
                    # J(JD1): allowed_providers = 이 PC 에 서 있는 허용이 있는 공급자 — 화면이 동의 창 단계를 건너뛸지 안다(낡을 수 있다:
                    # 세션 생성이 CONSENT_REQUIRED 면 화면은 허용 흐름으로 간다). 허브의 capabilities 는 사본 없이 그대로 둔다(추가 필드만)
                    devices.append({"device_id": did, "connected": True, "agent_version": d.agent_version,
                                    "capabilities_version": 2, "capabilities": d.capabilities,
                                    "allowed_providers": sorted(allowed.get(did, []))})
            # J-F1: 연결 안내 패널이 멈춘 단계를 안다. none = 등록된 PC 없음, offline = PC 는 있으나 연결된 PC 앱 없음,
            # no_provider = PC 앱은 연결됐으나 대화에 쓸 AI 를 알려 오지 않음, ready = 고를 모델이 있음
            setup = ("none" if not ids else "ready" if devices
                     else "no_provider" if any(hub.connected(uid, did) for did in ids) else "offline")
            return JSONResponse({"devices": devices, "setup": setup}, headers={"cache-control": "no-store"})
        except CrmError as e:
            return _err(e)

    async def messages(self, request):
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            out = await run_in_threadpool(messages, uid, request.path_params["sid"], request.query_params.get("after") or None)
        except CrmError as e:
            return _err(e)
        return JSONResponse({"messages": out}, headers={"cache-control": "no-store"})

    async def approvals(self, request):
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            out = await run_in_threadpool(approvals_list, uid, request.path_params["sid"])
            return JSONResponse({"approvals": out}, headers={"cache-control": "no-store"})
        except CrmError as e:
            return _err(e)

    async def _approval_action(self, request, action):
        uid, err = await self._gate(request, post=True)
        if err:
            return err
        try:
            if await self._body(request) != {}:
                raise CrmError("ARG-INVALID", "확인 요청에는 작업 내용을 넣을 수 없어요.")
            out = await run_in_threadpool(action, uid, request.path_params["sid"], request.path_params["aid"])
            return JSONResponse(out, headers={"cache-control": "no-store"})
        except CrmError as e:
            return _err(e)
        except Exception:
            return _err(CrmError("MCP-ERROR", "작업을 완료하지 못했어요."))

    async def approval_confirm(self, request):
        return await self._approval_action(request, approval_confirm)

    async def approval_cancel(self, request):
        return await self._approval_action(request, approval_cancel)

    async def turns(self, request):
        uid, err = await self._gate(request, post=True)
        if err:
            return err
        sid = request.path_params["sid"]
        try:
            b = await self._body(request)
            r = await run_in_threadpool(turn_create, uid, sid, b.get("text"), b.get("client_turn_id"),
                                        connected=lambda did: hub.connected(uid, did),
                                        capable=lambda s: (lambda d: bool(d and d.v2 and _supports(d.capabilities, s["provider"], s["model"])))(hub.dev(uid, s["device_id"])))
        except CrmError as e:
            for ev in getattr(e, "events", []):   # DEVICE-GONE — 세션을 닫으며 끝낸 턴
                hub.publish_event(uid, sid, ev)
            return _err(e)
        for ev in r["events"]:
            hub.publish_event(uid, sid, ev)
        t = r["turn"]
        if r["created"]:
            hub.publish(uid, sid, f"{t['id']}:0", "turn", {"turn_id": t["id"], "client_turn_id": t["client_turn_id"], "text": r["text"],
                                                           "created_at": _iso(t["created_at"])})
            d = hub.dev(uid, r["session"]["device_id"])
            msg = {"type": "turn.start", "session_id": sid, "turn_id": t["id"], "text": r["text"],
                   "provider": r["session"]["provider"], "model": r["session"]["model"], "binding_version": r["session"]["binding_version"]}
            if r.get("approval_outcomes"):
                msg["approval_outcomes"] = r["approval_outcomes"]
            if r["session"]["cli_session_ref"]:
                msg["cli_session_ref"] = r["session"]["cli_session_ref"]
            if r["session"].get("binding_version") == 2 and r["session"].get("provider") in GRANT_PROVIDERS:
                msg["launch_authorization_path"] = LAUNCH_AUTHORIZATION_PATH
            if not (d and await d.send(msg)):   # 붙어 있다고 봤는데 보내기 실패 — 턴을 끝낸다(재실행 없음)
                ev = await run_in_threadpool(turn_fail, t["id"], "DEVICE-OFFLINE")
                hub.publish_event(uid, sid, ev)
        return JSONResponse({"turn_id": t["id"], "status": t["status"], "created": r["created"]},
                            status_code=201 if r["created"] else 200, headers={"cache-control": "no-store"})

    async def stop(self, request):
        uid, err = await self._gate(request, post=True)
        if err:
            return err
        sid = request.path_params["sid"]
        try:
            t, ev, s = await run_in_threadpool(turn_stop, uid, sid)
        except CrmError as e:
            return _err(e)
        if not t:
            return JSONResponse({"turn_id": None, "status": None}, headers={"cache-control": "no-store"})
        hub.publish_event(uid, sid, ev)
        d = hub.dev(uid, s["device_id"])
        if d:
            await d.send({"type": "turn.stop", "turn_id": t["id"]})
        return JSONResponse({"turn_id": t["id"], "status": "stopped"}, headers={"cache-control": "no-store"})

    async def stream(self, request):
        uid, err = await self._gate(request)
        if err:
            return err
        sid = request.path_params["sid"]
        try:
            s = await run_in_threadpool(session_get, uid, sid)
            if s["status"] == "active":
                await run_in_threadpool(sweep, uid, sid)   # 유휴 턴 정리 — 결과 이벤트는 아래 재생에 들어간다
        except CrmError as e:
            return _err(e)
        cursor = parse_cursor(request.headers.get("last-event-id") or request.query_params.get("last_event_id"))
        sub = hub.subscribe(uid, sid, s["device_id"])   # 재생 전에 구독 — 재생 중 들어온 실시간 항목은 큐에 쌓이고, 재생한 id 는 건너뛴다
        try:
            items = await run_in_threadpool(replay, uid, sid, cursor)
        except Exception:
            hub.unsubscribe(sub)
            raise
        seen = {}
        for sse_id, _, _ in items:
            if sse_id:
                tid, seq = sse_id.split(":")
                seen[tid] = max(seen.get(tid, -1), int(seq))

        async def gen():
            try:
                yield b"retry: 3000\n\n"
                yield _sse(None, "pc", {"device_id": s["device_id"], "connected": hub.connected(uid, s["device_id"])})
                for sse_id, event, data in items:
                    yield _sse(sse_id, event, data)
                until = asyncio.get_running_loop().time() + SSE_MAX_SECONDS
                while enabled(uid) and asyncio.get_running_loop().time() < until:
                    try:
                        item = await asyncio.wait_for(sub.q.get(), HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield b": hb\n\n"
                        continue
                    if item[0] == "close":   # 닫힘 — 다른 탭이 새로 붙었으면 알리고 끝(클라이언트는 다시 붙지 않는다)
                        if item[1] == "replaced":
                            yield _sse(None, "replaced", {})
                        break
                    (sse_id, frame), size = item
                    sub.bytes -= size
                    if sse_id:
                        tid, seq = sse_id.split(":")
                        if int(seq) <= seen.get(tid, -1):
                            continue
                        seen[tid] = int(seq)
                    yield frame
            finally:
                hub.unsubscribe(sub)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"cache-control": "no-store", "x-accel-buffering": "no"})

    @staticmethod
    async def _chat_mcp_body(request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.")
        raw = await request.body()
        if len(raw) > CHAT_MCP_BODY_MAX:
            raise CrmError("TEXT-LIMIT", "요청 본문이 너무 커요.")

        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out

        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                              parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("constant")))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.") from None
        if not isinstance(body, dict) or body.get("tool") not in ("list", "find", "read", "write", "decide"):
            raise CrmError("ARG-INVALID", "도구 이름이 올바르지 않아요.")
        tool = body["tool"]
        common = {"session_id", "turn_id", "tool", "params"}
        allowed = common if tool in ("list", "find") else common | {"op", "bind"}
        required = common if tool in ("list", "find") else common | {"op"}
        if not required <= set(body) or set(body) - allowed:
            raise CrmError("ARG-INVALID", "필드가 빠졌거나 받지 않는 필드가 있어요.")
        if (not isinstance(body["session_id"], str) or not re.fullmatch(r"cs_[0-9a-f]{24}", body["session_id"])
                or not isinstance(body["turn_id"], str) or not re.fullmatch(r"ct_[0-9a-f]{24}", body["turn_id"])):
            raise CrmError("ARG-INVALID", "현재 대화와 턴 식별자가 필요해요.")
        if tool in ("read", "write", "decide") and (not isinstance(body.get("op"), str) or not body["op"] or len(body["op"]) > 128):
            raise CrmError("ARG-INVALID", "op 값이 올바르지 않아요.")
        if tool in ("read", "write", "decide") and "bind" in body and (not isinstance(body["bind"], str) or len(body["bind"]) > 128):
            raise CrmError("ARG-INVALID", "bind 값이 올바르지 않아요.")
        if not isinstance(body["params"], dict):
            raise CrmError("ARG-INVALID", "params 객체가 필요해요.")
        if tool == "find" and (set(body["params"]) - {"query", "family", "op"}):
            raise CrmError("ARG-INVALID", "find 인자가 올바르지 않아요.")
        return body

    async def chat_mcp(self, request):
        """Short session-scoped route for the local provider agent. Disabled by default."""
        if not chat_mcp_enabled():
            return _err(_off())
        try:
            authorization = self._bearer(request)
            dev = await run_in_threadpool(self._auth, authorization)
            if not await run_in_threadpool(chat_mcp_enabled, dev["user_id"]):   # 장치 소유자 프로필까지
                raise _off()
            await run_in_threadpool(_chat_rate, dev, "chat_mcp")   # R4: 접수 요청 버킷과 나눈 대화 버킷
            body = await self._chat_mcp_body(request)
            result = await run_in_threadpool(_chat_mcp_execute, dev, authorization, body)
            return JSONResponse({"result": result}, headers={"cache-control": "no-store"})
        except CrmError as e:
            return _err(e)
        except Exception:
            # Never put request headers, params, or raw exception text in an HTTP response.
            return _err(CrmError("MCP-ERROR", "도구 호출을 완료하지 못했어요."))

    @staticmethod
    async def _launch_authorization_body(request) -> dict:
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.")
        raw = await request.body()
        if len(raw) > 512:
            raise CrmError("TEXT-LIMIT", "요청 본문이 너무 커요.")
        def pairs(items):
            out = {}
            for key, value in items:
                if key in out:
                    raise ValueError("duplicate key")
                out[key] = value
            return out
        try:
            body = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                              parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("constant")))
        except (ValueError, UnicodeDecodeError, RecursionError):
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.") from None
        if (not isinstance(body, dict) or set(body) != {"session_id", "turn_id"}
                or not isinstance(body["session_id"], str) or not re.fullmatch(r"cs_[0-9a-f]{24}", body["session_id"])
                or not isinstance(body["turn_id"], str) or not re.fullmatch(r"ct_[0-9a-f]{24}", body["turn_id"])):
            raise CrmError("ARG-INVALID", "현재 대화와 턴 식별자가 필요해요.")
        return body

    async def launch_authorization(self, request):
        """Revalidate the device's current provider launch scope for each request."""
        if not enabled() or not PROVIDER_LAUNCH_READY:
            return _err(_off())
        try:
            authorization = self._bearer(request)
            dev = await run_in_threadpool(self._auth, authorization)
            if not await run_in_threadpool(enabled, dev["user_id"]):   # 장치 소유자 프로필까지
                raise _off()
            await run_in_threadpool(_chat_rate, dev, "chat_launch")   # R4: 접수 요청 버킷과 나눈 대화 버킷
            body = await self._launch_authorization_body(request)
            result = await run_in_threadpool(_chat_launch_authorization, dev, authorization,
                                             body["session_id"], body["turn_id"])
            return JSONResponse(result, headers={"cache-control": "no-store", "pragma": "no-cache"})
        except CrmError as e:
            return _err(e)
        except Exception:
            return _err(CrmError("MCP-ERROR", "대화 실행 권한을 확인하지 못했어요."))

    # ── PC 허용 grant 요청 · 동의 키 · challenge (2026-11-07) ──
    # 권한 주체 = 웹 세션 uid 하나. 본문에 user_id 를 받지 않는다(모르는 필드 = ARG-INVALID).
    # Origin 검사는 CSRF 방어일 뿐 PC 증거가 아니다. X-MyCRM-Desktop·renderer 표식은 읽지 않는다.
    # 키·challenge 경로는 세션에 더해 Authorization: Bearer <장치 토큰>을 요구하고, 원문 그대로 helper 에 넘긴다 —
    # 토큰 주인 = 세션 uid · 활성 장치 · 설치본.device_id 일치는 helper(_consent_bind)가 tx 안에서 본다. 장치 id 는 토큰에서만 나온다.
    # grant route 는 요청만 저장한다. challenge verify 가 승인하고, session_new 가 같은 트랜잭션에서 소비한다.
    # provider 실행은 PROVIDER_LAUNCH_READY(2026-11-12 K 켬)와 launch-authorization 재확인을 거친다. 도구 호출은 /api/chat/mcp(CRM_CHAT_MCP_ENABLED).

    @staticmethod
    async def _strict_body(request, spec: dict, optional=()) -> dict:
        """JSON 객체 본문을 엄격히 읽는다. spec = {필드: (최대 글자 수, null 허용)}. optional 에 없는 spec 필드는 필수.
        Content-Type application/json · CONSENT_BODY_MAX 바이트 · 중복 키·모르는 필드·문자열 아닌 값 = 거절."""
        if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.")
        cl = request.headers.get("content-length")
        if cl is not None and (not cl.isdigit() or int(cl) > CONSENT_BODY_MAX):
            raise CrmError("TEXT-LIMIT", "요청 본문이 너무 커요.")
        raw = bytearray()
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > CONSENT_BODY_MAX:
                raise CrmError("TEXT-LIMIT", "요청 본문이 너무 커요.")

        def pairs(kv):
            d = {}
            for k, v in kv:
                if k in d:
                    raise ValueError("duplicate key")
                d[k] = v
            return d

        def no_const(_):
            raise ValueError("constant")

        try:
            b = json.loads(bytes(raw).decode("utf-8"), object_pairs_hook=pairs, parse_constant=no_const)
        except (ValueError, RecursionError):   # UnicodeDecodeError·JSONDecodeError 포함, 깊은 중첩
            raise CrmError("ARG-INVALID", "JSON 본문이 필요해요.") from None
        if not isinstance(b, dict):
            raise CrmError("ARG-INVALID", "JSON 객체가 필요해요.")
        required = set(spec) - set(optional)
        if not required <= set(b) or not set(b) <= set(spec):
            raise CrmError("ARG-INVALID", "필드가 빠졌거나 받지 않는 필드가 있어요.")
        for k, v in b.items():
            max_len, nullable = spec[k]
            if v is None and nullable:
                continue
            if type(v) is not str or not 1 <= len(v) <= max_len:
                raise CrmError("ARG-INVALID", f"{k} 값이 올바르지 않아요.")
        return b

    @staticmethod
    def _bearer(request) -> str:
        """Authorization 머리글 원문(검증은 helper 가 imports.authenticate 로). 없음·여러 개·Bearer 아님·너무 김 = AUTH-INVALID."""
        hs = request.headers.getlist("authorization")
        if len(hs) != 1 or not hs[0].startswith("Bearer ") or len(hs[0]) > AUTHZ_MAX:
            raise CrmError("AUTH-INVALID", "장치 토큰이 없거나 형식이 틀렸어요.", "장치를 다시 연결하세요.")
        return hs[0]

    @staticmethod
    def _b64url_bytes(s: str, field: str) -> bytes:
        """canonical unpadded base64url → bytes. 별칭(패딩 비트)·패딩·다른 글자 = ARG-INVALID."""
        try:
            if not B64URL_RE.fullmatch(s):
                raise ValueError
            raw = base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
            if base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii") != s:
                raise ValueError
        except ValueError:   # binascii.Error 포함
            raise CrmError("ARG-INVALID", f"{field} 값이 올바르지 않아요.") from None
        return raw

    async def _consent_call(self, request, spec, call, optional=(), bearer=True, status=200, after=None):
        """스위치(503) → 세션(401) → Origin(403, CSRF) → Bearer 형식(401) → 본문 모양(400·413) → helper(uid = 세션)."""
        uid, err = await self._gate(request, post=True)
        if err:
            return err
        try:
            authz = self._bearer(request) if bearer else None
            b = await self._strict_body(request, spec, optional)
            out = await run_in_threadpool(call, uid, authz, b)
            if isinstance(out, tuple):
                out, status = out
            if after is not None:
                await after(uid, authz, b, out)
        except CrmError as e:
            return _err(e)
        return JSONResponse(out, status_code=status, headers={"cache-control": "no-store"})

    async def grant(self, request):
        """POST /api/chat/grants {device_id, provider, model|null, request_id} → pending grant(멱등). device_id 는 권한이 아니라 선택값 —
        grant_request 가 세션 uid 의 활성 장치인지 본다. 연결된 PC에 동의 요청을 알린다. 201 새로 · 200 같은 요청."""
        closed = []

        def call(uid, _authz, b):
            g, created = grant_request(uid, b["device_id"], b["provider"], b["model"], b["request_id"])
            if g.get("close_reason"):
                closed.append(True)
            return ({"request_id": g["request_id"], "device_id": g["device_id"], "provider": g["provider"], "model": g["model"],
                     "state": g["state"], "expires_at": _iso(g["expires_at"]), "created": created}, 201 if created else 200)
        async def notify(uid, _authz, _body, result):
            d = hub.dev(uid, result["device_id"])
            if d and result["state"] == "pending" and not closed:   # PC 가 닫은 grant 에 창을 다시 띄우지 않는다
                await d.send({"type": "consent.request", "request_id": result["request_id"]})
        return await self._consent_call(request, {"device_id": (200, False), "provider": (40, False), "model": (120, True),
                                                  "request_id": (64, False)}, call, bearer=False, after=notify)

    async def grant_status(self, request):
        """GET /api/chat/grants/{request_id} → {request_id, device_id, provider, model, state, prompt, expires_at, connected}.
        허용 대기 화면이 1~2초마다 읽는다(세션이 아직 없어 세션 SSE 에 실을 수 없다). 스위치와 세션 검사는 다른 GET 과 같다."""
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            out = await run_in_threadpool(grant_status, uid, request.path_params["request_id"])
        except CrmError as e:
            return _err(e)
        out["connected"] = hub.connected(uid, out["device_id"])
        return JSONResponse(out, headers={"cache-control": "no-store"})

    # ── 서 있는 허용 조회,해제(대화 하나로 J, JD3) — 웹 쿠키 세션 + POST Origin. 장치 토큰은 받지 않는다(권한을 줄이기만 한다).
    # PC 앱은 대시보드 세션으로 같은 경로를 부른다(installation_id 로 자기 PC 를 가리킨다).
    async def permits(self, request):
        """GET /api/chat/permits → {permits: [{device_id, installation_id, provider, created_at}]}(살아 있는 것만)."""
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            out = await run_in_threadpool(permits_live, uid)
        except CrmError as e:
            return _err(e)
        return JSONResponse({"permits": out}, headers={"cache-control": "no-store"})

    async def permit_revoke(self, request):
        """POST /api/chat/permits/revoke {device_id | installation_id, provider: claude|codex|null} → {revoked: 지운 수}(멱등).
        R-J2: 커밋 뒤 닫힌 세션의 실행 중 턴마다 PC 에 turn.stop, 화면 SSE 에 끝 이벤트(중지 route 와 같은 꼴)."""
        closed = []

        def call(uid, _authz, b):
            return {"revoked": permit_revoke(uid, b.get("device_id"), b.get("installation_id"), b["provider"], closed=closed)}
        async def notify(uid, _authz, _body, _result):
            for s in closed:
                for ev in s["events"]:
                    hub.publish_event(uid, s["session_id"], ev)
                d = hub.dev(uid, s["device_id"])
                for tid in s["turn_ids"]:
                    if d:
                        await d.send({"type": "turn.stop", "turn_id": tid})
        return await self._consent_call(request, {"device_id": (200, False), "installation_id": (40, False), "provider": (40, True)},
                                        call, optional=("device_id", "installation_id"), bearer=False, after=notify)

    async def consent_key_begin(self, request):
        """POST /api/chat/consent/keys/begin {installation_id, spki(base64url DER)} + Bearer → {key_id, claims}."""
        def call(uid, authz, b):
            return consent_key_begin(uid, authz, b["installation_id"], self._b64url_bytes(b["spki"], "spki"))
        return await self._consent_call(request, {"installation_id": (40, False), "spki": (128, False)}, call)

    async def consent_key_activate(self, request):
        """POST /api/chat/consent/keys/activate {installation_id, key_id, pop_signature, rotate_signature?} + Bearer → {key_id, state, rotated}."""
        def call(uid, authz, b):
            return consent_key_activate(uid, authz, b["installation_id"], b["key_id"], b["pop_signature"], b.get("rotate_signature"))
        return await self._consent_call(request, {"installation_id": (40, False), "key_id": (40, False), "pop_signature": (128, False),
                                                  "rotate_signature": (128, False)}, call, optional=("rotate_signature",))

    async def consent_key_revoke(self, request):
        """POST /api/chat/consent/keys/revoke {installation_id} + Bearer → {revoked: 폐기한 키 수}."""
        def call(uid, authz, b):
            return {"revoked": consent_key_revoke_bound(uid, authz, b["installation_id"])}
        return await self._consent_call(request, {"installation_id": (40, False)}, call)

    async def consent_issue(self, request):
        """POST /api/chat/consent/challenges/issue {installation_id, request_id} + Bearer → {challenge_id, claims}."""
        def call(uid, authz, b):
            return consent_challenge_issue(uid, authz, b["installation_id"], b["request_id"])
        return await self._consent_call(request, {"installation_id": (40, False), "request_id": (64, False)}, call)

    async def consent_verify(self, request):
        """POST /api/chat/consent/challenges/verify {installation_id, nonce, signature} + Bearer → {challenge_id, state, grant_id}.
        성공 시 grant 는 approved, consume/provider 실행은 여전히 fail-closed."""
        def call(uid, authz, b):
            return consent_challenge_verify(uid, authz, b["installation_id"], b["nonce"], b["signature"])
        return await self._consent_call(request, {"installation_id": (40, False), "nonce": (128, False), "signature": (128, False)}, call)

    # ── 장치 WS ──
    @staticmethod
    async def _deny(ws: WebSocket, e: CrmError):
        try:
            await ws.send_denial_response(_err(e))
        except Exception:   # 서버가 denial 확장을 모르면 닫기(HTTP 403)
            await ws.close(code=1008)

    @staticmethod
    def _auth(h):
        dev = imports.authenticate(h)
        db.device_seen(dev["user_id"], dev["id"])
        return dev

    async def device_ws(self, ws: WebSocket):
        code = "EXC"
        try:
            if not enabled():
                code = "SWITCH-OFF"
                return await self._deny(ws, _off())
            h = ws.headers.get("authorization", "")
            try:
                dev = await run_in_threadpool(self._auth, h)
            except CrmError as e:
                code = e.code
                return await self._deny(ws, e)
            if not await run_in_threadpool(enabled, dev["user_id"]):   # 장치 소유자 프로필까지
                code = "SWITCH-OFF"
                return await self._deny(ws, _off())
            await ws.accept()
            code = "OK"
            d = _Dev(ws, dev)
            await hub.attach(d)
            pinger = asyncio.ensure_future(self._pinger(d, h))
            try:
                await self._reader(d)
            finally:
                pinger.cancel()
                hub.detach(d)
        finally:
            db.usage_count(None, "api:chat_ws", code)

    async def _pinger(self, d: _Dev, h):
        """PING_SECONDS 마다 ping + 토큰 재확인(철회·만료·차단 = 4001) · 스위치 꺼짐 = 1013."""
        while not d.closed:
            await asyncio.sleep(PING_SECONDS)
            close = None
            if not await run_in_threadpool(enabled, d.dev["user_id"]):
                close = 1013
            else:
                try:
                    await run_in_threadpool(self._auth, h)
                except CrmError:
                    close = 4001
                except Exception:
                    close = None   # DB 일시 장애 — 다음 회차
            if close:
                d.closed = True
                try:
                    await d.ws.close(code=close)
                except Exception:
                    pass
                return
            await d.send({"type": "ping"})

    async def _reader(self, d: _Dev):
        dev = d.dev
        while True:
            try:
                msg = await d.ws.receive()
            except (WebSocketDisconnect, RuntimeError):
                return
            if msg["type"] == "websocket.disconnect":
                return
            raw = msg.get("text")
            if raw is None:
                raw = (msg.get("bytes") or b"").decode("utf-8", "replace")
            if len(raw.encode("utf-8")) > WS_MESSAGE_MAX:
                await d.ws.close(code=1009)
                return
            if not enabled(dev["user_id"]):
                await d.ws.close(code=1013)
                return
            try:
                m = json.loads(raw)
                assert isinstance(m, dict)
            except Exception:
                continue
            typ = m.get("type")
            if typ == "hello":
                p = m.get("providers")
                d.providers = [x for x in p if isinstance(x, str) and PROVIDER_RE.match(x)][:8] if isinstance(p, list) else []
                d.v2 = m.get("capabilities_version") == 2 and isinstance(m.get("agent_version"), str) and len(m["agent_version"]) <= 80
                d.agent_version = m.get("agent_version") if d.v2 else None
                d.capabilities = _normalize_capabilities(m.get("capabilities")) if d.v2 else []
                if not d.capabilities:
                    d.v2 = False
            elif typ == "event":
                try:
                    r = await run_in_threadpool(ingest, dev, m.get("turn_id"), m.get("seq"), m.get("kind"), m.get("data"))
                except CrmError:
                    continue
                except Exception as e:   # DB 일시 장애·교착 등 — 1011 로 닫아 PC 가 다시 붙어 미확인 이벤트를 재전송하게 한다(코드만 집계).
                    # 연결을 살려 두면 그 seq 이후가 전부 「빈 칸」이 되어 다음 재연결까지 묶인다
                    name = type(e).__name__[:30].upper()
                    db.usage_count(None, "api:chat_ws_event", name if _CODE.match(name) else "EXC")
                    try:
                        await d.ws.close(code=1011)
                    except Exception:   # 반대편이 이미 닫은 WS — 연결 정리는 device_ws 의 finally 가 맡는다
                        pass
                    return
                if r["state"] == "foreign":
                    continue
                await d.send({"type": "ack", "turn_id": m["turn_id"], "seq": r["ack"]})
                if r.get("event"):
                    hub.publish_event(r["user_id"], r["session_id"], r["event"])
                # 서버가 끝낸 턴(한도) · 이미 끝난 턴의 이벤트(중지 때 PC 가 끊겨 turn.stop 을 못 받았을 수 있다) — 연결당 한 번 알린다
                if (r.get("stop") or r["state"] == "dropped") and m["turn_id"] not in d.stop_sent:
                    d.stop_sent.add(m["turn_id"])
                    await d.send({"type": "turn.stop", "turn_id": m["turn_id"]})
            elif typ == "session_ref":
                try:
                    await run_in_threadpool(session_ref_set, dev, m.get("session_id"), m.get("cli_session_ref"))
                except Exception:
                    db.usage_count(None, "api:chat_ws_ref", "EXC")
            elif typ == "consent.result":   # F9 — 응답을 보내지 않는다(멱등). 실패는 서버 시간 초과 경로가 남는다
                try:
                    await run_in_threadpool(consent_result, dev, m.get("request_id"), m.get("outcome"))
                except Exception:
                    db.usage_count(None, "api:chat_ws_consent_result", "EXC")
            # pong·모르는 type = 무시
