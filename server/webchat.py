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
장치(Authorization: Bearer 장치 토큰): WS /api/device/chat/ws
  서버→PC turn.start{session_id, turn_id, text, cli_session_ref?} · turn.stop{turn_id} · ack{turn_id, seq} · ping
  PC→서버 hello{agent_version, providers[]} · event{turn_id, seq, kind, data} · session_ref{session_id, cli_session_ref} · pong

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
import json
import re
import secrets

from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

import db
import imports
from db import CrmError, tx, _one, _all, _user_lock
from envnames import switch_on

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
CLIENT_TURN_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
CLI_REF_RE = re.compile(r"^[A-Za-z0-9._:-]{1,200}$")
PROVIDER_RE = re.compile(r"^[a-z0-9_-]{1,40}$")
_CODE = re.compile(r"^[A-Z][A-Z0-9]*$")
KINDS = ("delta", "tool_call", "tool_result", "done", "error")
TERMINAL_STATUS = {"done": "done", "error": "failed"}

HTTP = {"SWITCH-OFF": 503, "UNAUTHORIZED": 401, "ORIGIN": 403, "NOT-FOUND": 404, "TURN-BUSY": 409, "DEVICE-OFFLINE": 409,
        "NO-DEVICE": 409, "DEVICE-GONE": 409, "SESSION-CLOSED": 409, "DEVICE-REQUIRED": 400, "ARG-INVALID": 400,
        "TEXT-LIMIT": 413, "RATE-LIMIT": 429, "AUTH-INVALID": 401, "TOKEN-EXPIRED": 401, "TOKEN-REVOKED": 401, "AUTH-BLOCKED": 403}


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(12)}"


def _off() -> CrmError:
    return CrmError("SWITCH-OFF", "대화 기능이 지금 꺼져 있어요.", "운영자가 켤 때까지 기다리세요.")


def enabled() -> bool:
    return switch_on("WEBCHAT_ENABLED")


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


def _session_out(s, connected=None):
    out = {"session_id": s["id"], "status": s["status"], "device_id": s["device_id"], "provider": s["provider"],
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


def turn_create(uid: str, sid: str, text, client_turn_id, *, connected) -> dict:
    out = _turn_create(uid, sid, text, client_turn_id, connected)
    if isinstance(out, list):   # 장치 철회 — 세션을 닫았다(커밋). 끝낸 턴 이벤트는 거절과 함께 넘겨 SSE 로 보낸다
        e = CrmError("DEVICE-GONE", "이 대화의 PC 연결이 해제됐어요.", "새 대화를 시작하세요.")
        e.events = out
        raise e
    return out


def _turn_create(uid, sid, text, client_turn_id, connected):
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
        if s["device_id"] not in _active_devices(c, uid):   # 닫기는 커밋하고(트랜잭션을 정상으로 끝낸 뒤) 거절한다
            return _close_session(c, sid, "DEVICE-GONE")
        evs = [e for e in _sweep_idle(c, sid) if e]
        if _one(c, "SELECT 1 FROM chat_turns WHERE session_id=%s AND status='running'", (sid,)):
            raise CrmError("TURN-BUSY", "앞 답이 아직 끝나지 않았어요.", "끝나거나 중지한 뒤 보내세요.")
        n = _one(c, "SELECT count(*) AS n FROM chat_turns t JOIN chat_sessions s ON s.id=t.session_id "
                    "WHERE s.user_id=%s AND t.created_at > now() - interval '60 seconds'", (uid,))["n"]
        if n >= TURNS_PER_MINUTE:
            raise CrmError("RATE-LIMIT", f"1분에 {TURNS_PER_MINUTE}번까지 보낼 수 있어요.", "잠시 뒤 다시 보내세요.")
        if not connected(s["device_id"]):
            raise CrmError("DEVICE-OFFLINE", "PC 가 연결돼 있지 않아요.", "PC 에서 my-crm 에이전트 대화(python3 -m agent chat)를 켜세요.")
        t = _one(c, "INSERT INTO chat_turns (id,session_id,client_turn_id) VALUES (%s,%s,%s) RETURNING *", (_id("ct"), sid, client_turn_id))
        c.execute("INSERT INTO chat_messages (id,session_id,turn_id,role,body) VALUES (%s,%s,%s,'user',%s)", (_id("cm"), sid, t["id"], text))
        c.execute("UPDATE chat_sessions SET last_at=now() WHERE id=%s", (sid,))
        return {"turn": dict(t), "created": True, "session": dict(s), "events": evs, "text": text}


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
            Route("/api/chat/sessions/{sid}/messages", u("web:chat_messages", self.messages)),
            Route("/api/chat/sessions/{sid}/turns", u("web:chat_turns", self.turns), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/stop", u("web:chat_stop", self.stop), methods=["POST"]),
            Route("/api/chat/sessions/{sid}/stream", u("web:chat_stream", self.stream)),
            WebSocketRoute("/api/device/chat/ws", self.device_ws),
        ]

    async def _gate(self, request, post=False):
        """스위치(503) → 세션(401) → POST Origin(403). (uid, None) | (None, 응답)."""
        if not enabled():
            return None, _err(_off())
        uid = await self.site.uid_of(request)
        if uid is None:
            return None, _err(CrmError("UNAUTHORIZED", "로그인이 필요해요."))
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
                did = (await self._body(request)).get("device_id")
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

    async def messages(self, request):
        uid, err = await self._gate(request)
        if err:
            return err
        try:
            out = await run_in_threadpool(messages, uid, request.path_params["sid"], request.query_params.get("after") or None)
        except CrmError as e:
            return _err(e)
        return JSONResponse({"messages": out}, headers={"cache-control": "no-store"})

    async def turns(self, request):
        uid, err = await self._gate(request, post=True)
        if err:
            return err
        sid = request.path_params["sid"]
        try:
            b = await self._body(request)
            r = await run_in_threadpool(turn_create, uid, sid, b.get("text"), b.get("client_turn_id"),
                                        connected=lambda did: hub.connected(uid, did))
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
            msg = {"type": "turn.start", "session_id": sid, "turn_id": t["id"], "text": r["text"]}
            if r["session"]["cli_session_ref"]:
                msg["cli_session_ref"] = r["session"]["cli_session_ref"]
            if not (d and await d.send(msg)):   # 붙어 있다고 봤는데 보내기 실패 — 턴을 끝낸다(재실행 없음)
                ev = await run_in_threadpool(turn_fail, t["id"], "DEVICE-OFFLINE")
                hub.publish_event(uid, sid, ev)
            elif d.providers and not r["session"]["provider"]:
                await run_in_threadpool(provider_set, sid, d.providers[0])
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
                while enabled() and asyncio.get_running_loop().time() < until:
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
            if not enabled():
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
            if not enabled():
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
            elif typ == "event":
                try:
                    r = await run_in_threadpool(ingest, dev, m.get("turn_id"), m.get("seq"), m.get("kind"), m.get("data"))
                except CrmError:
                    continue
                except Exception as e:   # DB 일시 장애·교착 등 — 1011 로 닫아 PC 가 다시 붙어 미확인 이벤트를 재전송하게 한다(코드만 집계).
                    # 연결을 살려 두면 그 seq 이후가 전부 「빈 칸」이 되어 다음 재연결까지 묶인다
                    name = type(e).__name__[:30].upper()
                    db.usage_count(None, "api:chat_ws_event", name if _CODE.match(name) else "EXC")
                    await d.ws.close(code=1011)
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
            # pong·모르는 type = 무시
