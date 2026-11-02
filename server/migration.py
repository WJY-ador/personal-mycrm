"""이관 경로(2026-11-02) — 이관 토큰 · plan 상태기계 · 검증 · dry-run · 반영 · 영수증 · 만료 정리.

정본: notes/2026-11-02_이관경로-구현계획.md K1~K10 · 「가안 1 — 상태기계」(고정본). 계약 = contract/imports/board-migration-2.schema.json,
정규화 시험 벡터 = contract/imports/vectors/board-migration-2-normalize.json(agent/ 와 공유).

  staged ─(seal: 검증·dry-run·plan_hash 고정)→ sealed ─(웹 [반영] · MCP migration_apply)→ applied ─(MCP migration_revert)→ reverted
     └──────────────(취소 · 만든 뒤 3일 만료)──────────→ cancelled · expired   (항목 본문 즉시 영구 삭제)

호출하는 곳
  · web.py — 토큰 경로(Bearer mig_…): plan 만들기·항목 청크·seal·상태·영수증·취소 · 웹 세션 경로: 토큰 발급·폐기, plan 목록·상세·항목 전문·
             기준 체크·[반영]·[취소]·영수증. 체크·토큰 발급은 웹 세션에서만(토큰·MCP 불가), 반영·취소는 MCP 도(가안 X).
  · migration_mcp.py — MCP 이관 op 8개(가안 X, notes/2026-11-02_mcp-facade-이관반영-구현계획.md §5). 스위치 CRM_MIGRATION_MCP_ENABLED 를
             더 본다. 웹과 같은 함수(plan_apply·plan_cancel·…)에 via="mcp" — 차이는 기준 규칙(_rules)·반영 바인딩(expected_counts)·revert 뿐.
  · main.py — MCP 읽기 migration_receipt_get(영수증 해시·개수 — 본문 없음, migration_mcp 경유)
  · imports.expire_pending — 만료 정리 회차(expire_plans)

반영 로직은 imports.mig_apply_in(항목 해석 → 제안 → 적용 · 충돌 · 멱등, 대응표 import_entries)을 그대로 쓴다. dry-run 은 같은 코드를
savepoint 안에서 실제로 돌린 뒤 되돌린다 — seal 결과와 반영 재계산이 같은 경로라 「dry-run ≠ 실반영」 이 생기지 않는다.
이 모듈은 모델을 부르지 않고, 본문·토큰을 로그·감사·오류 문구에 넣지 않는다. 오류 = db.CrmError(code, message, action[, detail]).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import hmac as _hmac
import re
import secrets
import unicodedata

import psycopg
from psycopg.types.json import Jsonb

import db
import imports
import migrate_cli as _cli   # resolve_object·_field_problems·order_rows(명세 해석·순서 — CLI 와 같은 규칙)
from db import CrmError, _all, _one, tx
from envnames import env, switch_on

# ── 공개 상수(계약) ────────────────────────────────────────
CONTRACT = "board-migration/2"
TOKEN_DAYS = 14                       # K1 이관 토큰 만료
PLAN_DAYS = 3                         # staged·sealed plan 보관(만든 시각부터)
PLAN_MAX_ITEMS = 200                  # plan 당 항목
OPEN_PLANS_MAX = 3                    # 사용자당 열린(staged·sealed) plan
USER_STAGING_MAX_BYTES = 2 * 1024 * 1024   # 사용자당 스테이징 바이트(열린 plan 항목 JCS 합)
ITEM_MAX_BYTES = 96 * 1024            # 항목 한 줄(JCS) 상한
BODY_MAX_BYTES = db.LIMIT_BODY        # 본문 64KB
CHUNK_MAX_BYTES = db.MAX_BODY_BYTES   # 청크 요청 본문(main.BodyLimit 와 같다 — 256KB)
DAILY_LIMIT = db.DAILY_LIMITS["migration"]   # 이관 반영 200행/일(KST)
RATE_PER_MINUTE = 60                  # 이관 토큰 하나의 분당 요청(청크 8개 + seal + 상태 조회가 한 분에 들어가게)
ALLOW_ENV = "BOARD_MIGRATION_USERS"   # CRM_BOARD_MIGRATION_USERS = 쉼표로 나눈 user id 목록(기본 비어 있음 = 아무도 못 씀)

ITEM_UNITS = ("principle_c", "principle_wd", "application_axis", "decision_index", "craft", "open_question", "publication", "axis",
              "application_doc")
PRINCIPLE_UNITS = ("principle_c", "principle_wd")   # 웹: 확인 화면에서 항목마다 체크해야 반영 · MCP(가안 X): 체크 무관, 확정하지 않는다
RECORD_UNITS = ("record", "journal")
DEFERRED_UNITS = ("session_story",)   # K8 — 받되 첫 반영 대상 아님(seal 에서 reject unit_deferred)
SOURCE_UNITS = ("source",)
UNIT_KINDS = ITEM_UNITS + RECORD_UNITS + DEFERRED_UNITS + SOURCE_UNITS
AUTHOR_KINDS = ("self", "external", "unknown")
TEXT_PROCESSES = ("verbatim", "structured", "rewritten", "generated", "unknown")
GENERATION_KINDS = ("human", "ai", "mixed", "unknown")
DATE_KINDS = db.DATE_KINDS                 # written·occurred·registered·heading
FORBIDDEN_DATE_KINDS = ("file_mtime",)     # K6 — 서버가 거절
SENSITIVITIES = ("normal", "internal")     # internal = 거절(K3)
REVIEW_STATES = ("reviewed", "pending")
SOURCE_KINDS = db.SOURCE_KINDS
STATES = ("staged", "sealed", "applied", "cancelled", "expired", "reverted")
ACTIONS = ("insert", "noop", "conflict", "reject", "warn")
RESULTS = ("applied", "noop", "skipped_unchecked", "skipped_warn", "skipped_reject", "skipped_conflict")
CONFLICT_CODES = frozenset({"IDEMPOTENCY-CONFLICT", "TARGET-REVISION-CONFLICT", "KIND-CHANGED", "SOURCE-REVISION-CONFLICT", "CONFLICT"})
OWNER_KEYS = ("owner", "owner_id", "user", "user_id", "target_user_id", "uid", "account", "account_id")   # K1 — 오면 거절

_HTTP = {"MIGRATION-OFF": 503, "MIGRATION-NOT-ALLOWED": 403, "AUTH-INVALID": 401, "TOKEN-EXPIRED": 401, "TOKEN-REVOKED": 401,
         "AUTH-BLOCKED": 403, "CONTRACT-INVALID": 400, "ARG-INVALID": 400, "PAYLOAD-LIMIT": 413, "STAGING-FULL": 413,
         "PLAN-LIMIT": 429, "RATE-LIMIT": 429, "CHUNK-OFFSET": 409, "PLAN-STATE": 409, "PLAN-EXPIRED": 410, "PLAN-COUNT-MISMATCH": 409,
         "PLAN-EMPTY": 409, "PLAN-HASH-MISMATCH": 409, "PLAN-STALE": 409, "CHECK-DEPENDENCY": 409, "NOT-FOUND": 404,
         "QUOTA-GLOBAL": 507, "NAME-REQUIRED": 403, "APPLY-MISMATCH": 409, "REVERT-MODIFIED": 409}

_ID_RE = {"original_id": re.compile(r"^o_[0-9a-f]{32}$"), "source_revision": re.compile(r"^v_[0-9a-f]{32}$")}
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_PLAN_RE = re.compile(r"^mp_[0-9a-f]{24}$")
_TOKEN_RE = re.compile(r"^Bearer mig_(mt_[0-9a-f]{16})\.([A-Za-z0-9_-]{43})$")
_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


def http_status(code: str) -> int:
    """CrmError code → HTTP 상태(이관 경로). 모르는 code 는 imports.http_status."""
    return _HTTP.get(code) or imports.http_status(code)


def _err(code, msg, action="", **detail):
    e = CrmError(code, msg, action)
    if detail:
        e.detail = detail
    return e


def _bad(path, rule):
    return _err("CONTRACT-INVALID", f"{path}: {rule}", "항목을 계약(board-migration/2)에 맞추세요.")


# ── 정규화 · 해시 (K4) ──────────────────────────────────────

def normalize(text: str) -> str:
    """K4 — NFC → CRLF 를 LF 로 → 줄마다 끝의 공백·탭(U+0020·U+0009)만 지운다. 그 밖(홀로 선 CR·U+3000·NBSP·BOM·본문 끝 개행·
    내부 공백)은 그대로. agent/ 와 같은 시험 벡터(contract/imports/vectors/board-migration-2-normalize.json)로 묶는다."""
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    return "\n".join(line.rstrip(" \t") for line in t.split("\n"))


def content_hash(text: str) -> str:
    """정규화한 UTF-8 의 SHA-256 소문자 hex."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def item_sha256(item: dict) -> bytes:
    return hashlib.sha256(imports.jcs(item)).digest()


def plan_hash_of(item_shas: list) -> str:
    """plan_hash = SHA-256(JCS(seq 순 item_sha256 hex 목록)) 소문자 hex."""
    return hashlib.sha256(imports.jcs([bytes(h).hex() for h in item_shas])).hexdigest()


def _content_text(item: dict) -> str:
    """content_hash 대상 — 기록·항목 = body(없으면 ""), 출처 = source.name."""
    if item.get("unit_kind") in SOURCE_UNITS:
        return (item.get("source") or {}).get("name") or ""
    return item.get("body") or ""


def target_kind_of(unit_kind: str) -> str:
    if unit_kind in ITEM_UNITS:
        return "item"
    if unit_kind in SOURCE_UNITS:
        return "source"
    return "record"


# ── 스위치 · allowlist · 토큰 (K1) ─────────────────────────

def allowed_users() -> set:
    return {x.strip() for x in (env(ALLOW_ENV, "") or "").split(",") if x.strip()}


def gate(uid: str):
    """켜는 조건 = 스위치 BOARD_MIGRATION_ENABLED + 사용자 allowlist. 발급·토큰 사용·확인·반영 때마다 본다."""
    if not switch_on("BOARD_MIGRATION_ENABLED"):
        raise _err("MIGRATION-OFF", "이관이 지금 꺼져 있어요.", "운영자가 켤 때까지 기다리세요. 스테이징한 자료는 PC 에 남아 있어요.")
    if uid not in allowed_users():
        raise _err("MIGRATION-NOT-ALLOWED", "이 계정은 이관을 쓸 수 없어요.", "운영자에게 이관 허용 목록에 넣어 달라고 하세요.")


def switch_state(uid: str) -> dict:
    return {"enabled": switch_on("BOARD_MIGRATION_ENABLED"), "allowed": uid in allowed_users()}


# 가안 X — 대화(MCP) 이관 스위치. CRM_MIGRATION_MCP_ENABLED == "1" 만 켜짐(기본 꺼짐, envnames.SWITCHES).
MCP_SWITCH = "MIGRATION_MCP_ENABLED"
MCP_DEFER_MSG = ("대화 반영에선 기준이 모두 미확정으로 들어갑니다. 웹에서 체크한 기준도 같습니다. "
                 "한 번에 확정까지 하려면 웹에서 반영하세요.")


def mcp_on() -> bool:
    return switch_on(MCP_SWITCH)


def mcp_gate(uid: str):
    """MCP 이관 op(읽기 포함) — 스위치 CRM_MIGRATION_MCP_ENABLED 를 먼저 보고, 기존 스위치·allowlist(gate)를 그 위에 본다."""
    if not mcp_on():
        raise _err("MIGRATION-OFF", "대화(MCP)에서 이관은 지금 꺼져 있어요.", "웹 「이관」 화면에서 하거나 운영자가 켤 때까지 기다리세요.")
    gate(uid)


_TOK_COLS = "id,label,created_at,expires_at,revoked_at,last_used_at"


def _tok_out(r):
    d = imports._row(r)
    d["active"] = r["revoked_at"] is None and not r.get("expired", False)
    d.pop("expired", None)
    return d


def token_status(uid: str) -> dict:
    """웹 — {"tokens": [토큰(최근 순, 원문·해시 없음)], "enabled", "allowed", "token_days"}."""
    with tx() as c:
        rows = _all(c, f"SELECT {_TOK_COLS},(expires_at <= now()) AS expired FROM migration_tokens WHERE user_id=%s "
                       "ORDER BY created_at DESC, id DESC LIMIT 20", (uid,))
    return {"tokens": [_tok_out(r) for r in rows], **switch_state(uid), "token_days": TOKEN_DAYS}


def active_count(c, uid: str) -> int:
    """살아 있는(폐기·만료 아닌) 이관 토큰 수 — 새 토큰이 처음 쓰일 때 폐기될 수(M2). 대화 발급 미리보기 「기존 이관 토큰 N개」."""
    return _one(c, "SELECT count(*) AS n FROM migration_tokens WHERE user_id=%s AND revoked_at IS NULL AND expires_at > now()", (uid,))["n"]


def token_issue_in(c, uid: str, label: str = "이관 업로더", via: str = "web") -> dict:
    """발급 본체(트랜잭션 c 안, 사용자 잠금은 호출하는 쪽). M2(PC 연결 2026-11-02) — 새 토큰은 대기 토큰: 한 번도 안 쓴 앞 토큰(앞의 대기 토큰)만
    지금 폐기하고(덮어쓰기), 쓰던 토큰은 새 토큰이 처음 인증될 때(authenticate) 폐기된다. 반환 {"token", "info"}. 감사 migration_token."""
    label = db._label(label or "이관 업로더", "토큰 이름")
    tid = "mt_" + secrets.token_hex(8)
    secret = secrets.token_urlsafe(32)
    c.execute("UPDATE migration_tokens SET revoked_at=now() WHERE user_id=%s AND revoked_at IS NULL AND last_used_at IS NULL", (uid,))
    c.execute("INSERT INTO migration_tokens (user_id,id,secret_hash,label,expires_at) VALUES (%s,%s,%s,%s,now() + make_interval(days => %s))",
              (uid, tid, hashlib.sha256(secret.encode("ascii")).digest(), label, TOKEN_DAYS))
    db._audit(c, "migration_token", uid, uid, {"token_id": tid, "via": via, "result": "issued"})
    r = _one(c, f"SELECT {_TOK_COLS},(expires_at <= now()) AS expired FROM migration_tokens WHERE user_id=%s AND id=%s", (uid, tid))
    return {"token": f"mig_{tid}.{secret}", "info": _tok_out(r)}


def token_issue(uid: str, label: str = "이관 업로더") -> dict:
    """웹 세션 — 새 이관 토큰(14일). 앞 토큰은 새 토큰을 처음 쓸 때 폐기(M2 — 사용자당 살아 있는 토큰은 결국 1개).
    반환 {"token": "mig_<id>.<secret>"(이 응답에서 한 번만), "info": 토큰}. 감사 migration_token."""
    gate(uid)
    with tx() as c:
        db._user_lock(c, uid)
        return token_issue_in(c, uid, label)


def token_revoke(uid: str, token_id: str) -> dict:
    """웹 세션 — 토큰 폐기(멱등). 반환 {"info": 토큰}."""
    with tx() as c:
        db._user_lock(c, uid)
        r = _one(c, "SELECT id FROM migration_tokens WHERE user_id=%s AND id=%s FOR UPDATE", (uid, str(token_id or "")))
        if not r:
            raise imports._nf("그 이관 토큰")
        c.execute("UPDATE migration_tokens SET revoked_at=COALESCE(revoked_at, now()) WHERE user_id=%s AND id=%s", (uid, r["id"]))
        r = _one(c, f"SELECT {_TOK_COLS},(expires_at <= now()) AS expired FROM migration_tokens WHERE user_id=%s AND id=%s", (uid, r["id"]))
    return {"info": _tok_out(r)}


def authenticate(authorization: str) -> dict:
    """Bearer 이관 토큰 → {"user_id", "token_id"}. 순서: 스위치 → 토큰(상수 시간 비교) → 폐기·만료·사용자 상태 → allowlist → 요청 속도.
    일반 연결 장치 토큰(imp_…)·MCP·웹 쿠키는 받지 않는다. 사용자는 토큰으로만 정한다."""
    if not switch_on("BOARD_MIGRATION_ENABLED"):
        raise _err("MIGRATION-OFF", "이관이 지금 꺼져 있어요.", "운영자가 켤 때까지 기다리세요.")
    m = _TOKEN_RE.match(authorization or "")
    if not m:
        raise _err("AUTH-INVALID", "이관 토큰이 없거나 형식이 틀렸어요.", "웹 「연결 장치」에서 이관 토큰을 발급하세요.")
    tid, secret = m.groups()
    with tx() as c:
        r = _one(c, "SELECT t.user_id,t.secret_hash,t.revoked_at,(t.expires_at <= now()) AS expired,u.status,u.blocked_at "
                    "FROM migration_tokens t JOIN users u ON u.id=t.user_id WHERE t.id=%s", (tid,))
    if not r or not _hmac.compare_digest(bytes(r["secret_hash"]), hashlib.sha256(secret.encode("ascii")).digest()):
        raise _err("AUTH-INVALID", "이관 토큰이 맞지 않아요.", "웹에서 이관 토큰을 다시 발급하세요.")
    if r["revoked_at"] is not None:
        raise _err("TOKEN-REVOKED", "이 이관 토큰은 폐기됐어요.", "웹에서 새로 발급하세요.")
    if r["expired"]:
        raise _err("TOKEN-EXPIRED", "이관 토큰이 만료됐어요.", "웹에서 새로 발급하세요.")
    if r["status"] != "active":
        raise _err("AUTH-INVALID", "사용자를 찾을 수 없어요.")
    if r["blocked_at"] is not None:
        raise _err("AUTH-BLOCKED", "이 계정은 지금 쓸 수 없어요.")
    if r["user_id"] not in allowed_users():
        raise _err("MIGRATION-NOT-ALLOWED", "이 계정은 이관을 쓸 수 없어요.", "운영자에게 이관 허용 목록에 넣어 달라고 하세요.")
    tok = {"user_id": r["user_id"], "token_id": tid}
    with tx() as c:   # 요청 속도 — 별도 트랜잭션(뒤에서 실패해도 센다). 카운터 표는 연결 장치와 같고 키는 토큰 id
        if imports._bump(c, tok["user_id"], tid, "minute", "request")["n"] > RATE_PER_MINUTE:
            raise _err("RATE-LIMIT", f"요청이 너무 잦아요(분당 {RATE_PER_MINUTE}회).", "1분 뒤 다시 보내세요.")
    with tx() as c:   # M2 — 이 토큰의 첫 사용이면 그 사용자의 다른 살아 있는 이관 토큰을 폐기한다(새 토큰 첫 사용 때 앞 토큰 무효)
        first = _one(c, "SELECT last_used_at IS NULL AS first FROM migration_tokens WHERE user_id=%s AND id=%s FOR UPDATE",
                     (tok["user_id"], tid))
        c.execute("UPDATE migration_tokens SET last_used_at=now() WHERE user_id=%s AND id=%s", (tok["user_id"], tid))
        if first and first["first"]:
            c.execute("UPDATE migration_tokens SET revoked_at=now() WHERE user_id=%s AND id<>%s AND revoked_at IS NULL",
                      (tok["user_id"], tid))
    return tok


# ── 항목 검사 ──────────────────────────────────────────────
# 구조(업로드 때 · 틀리면 청크 전체 400 CONTRACT-INVALID, 저장 0) · 의미(seal 때 · 항목 action=reject + 사유, 본문 즉시 삭제)

_COMMON = ("original_id", "source_revision", "source_instance", "unit_kind", "content_hash")
_PROV = ("author_kind", "text_process", "generation_kind", "primary_date", "review", "sensitivity")
_KEYS = {
    "record": (_COMMON + _PROV + ("body",),
               ("title", "other_dates", "redaction", "attach", "source_ref", "distinct", "supersedes")),
    "item": (_COMMON + _PROV + ("object_ref", "title"),
             ("body", "code", "fields", "decision", "references", "expected_target_revision", "other_dates", "redaction", "distinct",
              "supersedes")),
    "source": (_COMMON + ("source",), ("review",)),
}


def _keys(obj, path, required, optional=()):
    """정확한 키 집합 — 모르는 키 unknown_field · 빠진 키 required(imports._exact_keys 와 같은 규칙, 이 계약의 문구)."""
    if not isinstance(obj, dict):
        raise _bad(path, "object_required")
    for k in obj:
        if k not in required and k not in optional:
            raise _bad(f"{path}.{k}" if path != "$" else k, "unknown_field")
    for k in required:
        if k not in obj:
            raise _bad(f"{path}.{k}" if path != "$" else k, "required")


def _walk_strings(v, path="$"):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield from _walk_strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _walk_strings(x, f"{path}[{i}]")


def _str(v, path, max_cp, empty_ok=False):
    if not isinstance(v, str):
        raise _bad(path, "string_required")
    if not empty_ok and not v.strip():
        raise _bad(path, "empty")
    if len(v) > max_cp:
        raise _bad(path, "too_long")


def _date_obj(v, path):
    _keys(v, path, ("kind", "value"))
    if not isinstance(v["kind"], str) or v["kind"] not in DATE_KINDS + FORBIDDEN_DATE_KINDS:
        raise _bad(f"{path}.kind", "enum")
    if not isinstance(v["value"], str) or len(v["value"]) > 40:
        raise _bad(f"{path}.value", "string_required")


def _target_ref(v, path):
    """references·attach 대상 — {original_id, revision} | {record_id} | {item_id} | {candidate_id}(board-migration/1 과 같다)."""
    if not isinstance(v, dict) or not v:
        raise _bad(path, "object_required")
    if "original_id" in v:
        _keys(v, path, ("original_id", "revision"))
        if not isinstance(v["original_id"], str) or not _ID_RE["original_id"].match(v["original_id"]):
            raise _bad(f"{path}.original_id", "format")
        if not isinstance(v["revision"], str) or not _ID_RE["source_revision"].match(v["revision"]):
            raise _bad(f"{path}.revision", "format")
        return
    if len(v) != 1 or next(iter(v)) not in ("record_id", "item_id", "candidate_id") or not isinstance(next(iter(v.values())), str):
        raise _bad(path, "target_form")


def check_item(it, plan_instance: str, path: str = "$") -> dict:
    """구조 검사 — 통과하면 {"target_kind"}. 실패 = CrmError CONTRACT-INVALID("<경로>: <규칙>", 값 없음)."""
    if not isinstance(it, dict):
        raise _bad(path, "object_required")
    for k in it:
        if k in OWNER_KEYS:
            raise _bad(f"{path}.{k}", "owner_field_not_allowed")   # K1 — 사용자는 서버가 토큰으로 정한다
    for p, s in _walk_strings(it, path):
        if "\x00" in s or any(0xD800 <= ord(ch) <= 0xDFFF for ch in s):
            raise _bad(p, "invalid_char")
    uk = it.get("unit_kind")
    if uk not in UNIT_KINDS:
        raise _bad(f"{path}.unit_kind", "enum")
    tk = target_kind_of(uk)
    req, opt = _KEYS[tk]
    _keys(it, path, req, opt)
    for k in ("original_id", "source_revision"):
        if not isinstance(it[k], str) or not _ID_RE[k].match(it[k]):
            raise _bad(f"{path}.{k}", "format")
    if not isinstance(it["source_instance"], str) or not _INSTANCE_RE.match(it["source_instance"]):
        raise _bad(f"{path}.source_instance", "format")
    if it["source_instance"] != plan_instance:
        raise _bad(f"{path}.source_instance", "plan_mismatch")
    if not isinstance(it["content_hash"], str) or not _HEX64.match(it["content_hash"]):
        raise _bad(f"{path}.content_hash", "format")
    if tk == "source":
        _keys(it["source"], f"{path}.source", ("kind", "name", "location"))
        if it["source"]["kind"] not in SOURCE_KINDS:
            raise _bad(f"{path}.source.kind", "enum")
        _str(it["source"]["name"], f"{path}.source.name", db.LIMIT_TEXT)
        if not isinstance(it["source"]["location"], str) or not _HEX64.match(it["source"]["location"]):
            raise _bad(f"{path}.source.location", "anchor_hash_required")   # K7 — URL 이 아니라 로컬 anchor 해시(opaque)
        if "review" in it:
            _keys(it["review"], f"{path}.review", ("state",), ("decision_ref",))
            if it["review"]["state"] not in REVIEW_STATES:
                raise _bad(f"{path}.review.state", "enum")
        return {"target_kind": tk}
    for k, vals in (("author_kind", AUTHOR_KINDS), ("text_process", TEXT_PROCESSES), ("generation_kind", GENERATION_KINDS),
                    ("sensitivity", SENSITIVITIES)):
        if it[k] not in vals:
            raise _bad(f"{path}.{k}", "enum")
    if it["primary_date"] is not None:
        _date_obj(it["primary_date"], f"{path}.primary_date")
    od = it.get("other_dates", [])
    if not isinstance(od, list) or len(od) > 10:
        raise _bad(f"{path}.other_dates", "list_0_10")
    for i, d in enumerate(od):
        _date_obj(d, f"{path}.other_dates[{i}]")
    _keys(it["review"], f"{path}.review", ("state",), ("decision_ref",))
    if it["review"]["state"] not in REVIEW_STATES:
        raise _bad(f"{path}.review.state", "enum")
    if it["review"].get("decision_ref") is not None:
        _str(it["review"]["decision_ref"], f"{path}.review.decision_ref", 200)
    if "redaction" in it:
        _keys(it["redaction"], f"{path}.redaction", ("count",))
        if not imports._is_int(it["redaction"]["count"]) or not 1 <= it["redaction"]["count"] <= 10000:
            raise _bad(f"{path}.redaction.count", "int_1_10000")
    if "title" in it and it["title"] is not None:
        _str(it["title"], f"{path}.title", db.LIMIT_TEXT, empty_ok=True)
    if it.get("body") is not None:
        _str(it["body"], f"{path}.body", BODY_MAX_BYTES, empty_ok=(tk == "item"))
        if len(it["body"].encode("utf-8")) > BODY_MAX_BYTES:
            raise _bad(f"{path}.body", "too_long_bytes")
    if "distinct" in it and not isinstance(it["distinct"], bool):
        raise _bad(f"{path}.distinct", "boolean_required")
    if "supersedes" in it and (not isinstance(it["supersedes"], str) or not _ID_RE["original_id"].match(it["supersedes"])):
        raise _bad(f"{path}.supersedes", "format")
    if tk == "item":
        ref = it["object_ref"]
        if not isinstance(ref, dict) or not ref or any(k not in ("std_id", "template_slot", "key") or not isinstance(v, str)
                                                       for k, v in ref.items()):
            raise _bad(f"{path}.object_ref", "std_id_template_slot_key")
        _str(it["title"], f"{path}.title", db.LIMIT_TEXT)
        if it.get("code") is not None:
            _str(it["code"], f"{path}.code", 80)
        if "fields" in it and not isinstance(it["fields"], dict):
            raise _bad(f"{path}.fields", "object_required")
        if it.get("decision") is not None and it["decision"] not in ("pending", "confirmed", "excluded"):
            raise _bad(f"{path}.decision", "enum")
        for i, x in enumerate(it.get("references") or []):
            _keys(x, f"{path}.references[{i}]", ("field_key", "target"))
            if not isinstance(x["field_key"], str) or not _KEY_RE.match(x["field_key"]):
                raise _bad(f"{path}.references[{i}].field_key", "format")
            _target_ref(x["target"], f"{path}.references[{i}].target")
        etr = it.get("expected_target_revision")
        if etr is not None and (not imports._is_int(etr) or etr < 0):
            raise _bad(f"{path}.expected_target_revision", "int")
    else:
        at = it.get("attach")
        if at is not None:
            _keys(at, f"{path}.attach", (), ("attach_to", "axes", "use_at", "unattached"))
            for k in ("attach_to", "axes"):
                for i, t in enumerate(at.get(k) or []):
                    _target_ref(t, f"{path}.attach.{k}[{i}]")
            for k in ("use_at", "unattached"):
                for i, t in enumerate(at.get(k) or []):
                    _str(t, f"{path}.attach.{k}[{i}]", db.LIMIT_TEXT)
        sr = it.get("source_ref")
        if sr is not None:
            _keys(sr, f"{path}.source_ref", ("original_id",))
            if not isinstance(sr["original_id"], str) or not _ID_RE["original_id"].match(sr["original_id"]):
                raise _bad(f"{path}.source_ref.original_id", "format")
    return {"target_kind": tk}


def _parse_when(v):
    """신고 날짜 값 → ("ts", datetime) | ("date", date) | None(형식 틀림)."""
    try:
        if imports._DATE_RE.match(v):
            return "date", imports._date(v, "v")
        return "ts", imports._ts(v, "v")
    except CrmError:
        return None


def semantic_reject(it: dict) -> str | None:
    """의미 검사(seal) — 거절 사유 코드 또는 None. 순서가 곧 우선순위(첫 사유 하나만)."""
    uk = it["unit_kind"]
    if uk in DEFERRED_UNITS:
        return "unit_deferred"
    rv = it.get("review")
    if (rv is not None or uk not in SOURCE_UNITS) and (rv or {}).get("state") != "reviewed":
        return "review_pending"                      # K2 — 검토 미완 = 비적격으로라도 올리는 길 없음
    if uk not in SOURCE_UNITS:
        if it["sensitivity"] == "internal":
            return "sensitivity_internal"
        if "unknown" in (it["author_kind"], it["text_process"], it["generation_kind"]):
            return "provenance_unknown"
        if it["author_kind"] == "external":
            return "scope_self_only"
        if it["generation_kind"] in ("ai", "mixed") and it["author_kind"] == "self" and it["text_process"] == "verbatim":
            return "provenance_contradiction"        # 메인 결정 1 — ai/mixed 는 text_process ≠ verbatim 일 때만(기존 적격 SQL 로 비적격)
        for d in ([it["primary_date"]] if it["primary_date"] else []) + list(it.get("other_dates") or []):
            if d["kind"] in FORBIDDEN_DATE_KINDS:
                return "file_mtime_not_allowed"
            if _parse_when(d["value"]) is None:
                return "date_invalid"
    if content_hash(_content_text(it)) != it["content_hash"]:
        return "content_hash_mismatch"
    for _p, s in _walk_strings({k: v for k, v in it.items() if k not in ("original_id", "source_revision", "source_instance",
                                                                          "content_hash", "object_ref")}):
        for rule, rx in imports.LEAK_RULES:
            if rx.search(s):
                return f"{rule}_not_allowed"         # K3 — URL·이메일·로컬 경로(본문·메타)
    if target_kind_of(uk) == "record" and not normalize(it.get("body") or "").strip():
        return "body_empty"
    return None


def _dates(it):
    """K6 → (source_created_at, source_date, date_kind, 기록에 남길 신고 날짜). written·occurred 시각 = created 를 채운다.
    날짜만이거나 registered·heading 이면 source_date(시각이면 그 값에 적힌 날짜 그대로) + 라벨, created = 받은 시각."""
    pd = it.get("primary_date")
    if not pd:
        return None, None, None
    shape, v = _parse_when(pd["value"])
    if pd["kind"] in ("written", "occurred") and shape == "ts":
        return v, None, pd["kind"]
    return None, (v.date() if shape == "ts" else v), pd["kind"]


# ── plan (토큰) ────────────────────────────────────────────
_PLAN_COLS = ("id,token_id,contract,source_instance,state,item_count,staged_bytes,plan_hash,summary,created_at,expires_at,sealed_at,"
              "applied_at,closed_at,reverted_at,via")


def _plan_out(r) -> dict:
    d = imports._row({k: r[k] for k in _PLAN_COLS.split(",")})
    d["plan_id"] = d.pop("id")
    d["plan_hash"] = bytes(r["plan_hash"]).hex() if r["plan_hash"] else None
    return d


def _close_due(c, uid=None):
    """만료 지난 열린 plan → expired + 항목 본문 영구 삭제. uid 를 주면 그 사용자만(접근 때 즉시). 반환 닫은 plan 수."""
    cond, args = ("AND user_id=%s", (uid,)) if uid else ("", ())
    ids = _all(c, f"UPDATE migration_plans SET state='expired', closed_at=now() WHERE state IN ('staged','sealed') AND expires_at <= now() "
                  f"{cond} RETURNING user_id, id", args)
    for r in ids:
        c.execute("UPDATE migration_plan_items SET payload=NULL, payload_bytes=0 WHERE user_id=%s AND plan_id=%s", (r["user_id"], r["id"]))
    return len(ids)


def expire_plans() -> int:
    """정리 회차(imports.expire_pending → main.purge_once) — 만료 지난 plan 을 닫고 본문을 지운다. 반환 건수."""
    with tx() as c:
        return _close_due(c)


def _sweep(uid):
    """접근 때 만료 정리 — 자기 트랜잭션에서 먼저 커밋한다(뒤 작업이 PLAN-EXPIRED 로 롤백돼도 본문 삭제는 남는다)."""
    with tx() as c:
        _close_due(c, uid)


def _plan_lock(c, uid, plan_id):
    """plan 행 잠금(만료 지났으면 그 자리에서 닫는다). 없거나 남의 plan = NOT-FOUND."""
    if not isinstance(plan_id, str) or not _PLAN_RE.match(plan_id):
        raise imports._nf("그 이관 plan")
    _close_due(c, uid)
    r = _one(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s AND id=%s FOR UPDATE", (uid, plan_id))
    if not r:
        raise imports._nf("그 이관 plan")
    return r


def _need_state(r, *states):
    if r["state"] in states:
        return
    if r["state"] == "expired":
        raise _err("PLAN-EXPIRED", "보관 기간(3일)이 지나 닫힌 plan 이에요. 스테이징한 본문은 지웠어요.", "PC 에서 다시 stage 하세요.")
    raise _err("PLAN-STATE", f"지금 plan 상태({r['state']})에선 할 수 없어요.", "plan 상태를 다시 보세요.", state=r["state"])


def plan_create(tok: dict, body: dict) -> dict:
    """POST /api/migration/plans {contract: "board-migration/2", source_instance} → plan(staged). 열린 plan 3개까지."""
    uid = tok["user_id"]
    if not isinstance(body, dict):
        raise _bad("$", "object_required")
    for k in body:
        if k in OWNER_KEYS:
            raise _bad(k, "owner_field_not_allowed")
    _keys(body, "$", ("contract", "source_instance"))
    if body["contract"] != CONTRACT:
        raise _bad("contract", "const")
    if not isinstance(body["source_instance"], str) or not _INSTANCE_RE.match(body["source_instance"]):
        raise _bad("source_instance", "format")
    db.check_global_quota(uid)
    pid = "mp_" + secrets.token_hex(12)
    with tx() as c:
        db._user_lock(c, uid)
        _close_due(c, uid)
        n = _one(c, "SELECT count(*) AS n FROM migration_plans WHERE user_id=%s AND state IN ('staged','sealed')", (uid,))["n"]
        if n >= OPEN_PLANS_MAX:
            raise _err("PLAN-LIMIT", f"열린 이관 plan 은 {OPEN_PLANS_MAX}개까지예요.", "반영하거나 취소한 뒤 다시 만드세요.")
        r = _one(c, "INSERT INTO migration_plans (user_id,id,token_id,contract,source_instance,state,expires_at) "
                    f"VALUES (%s,%s,%s,%s,%s,'staged',now() + make_interval(days => %s)) RETURNING {_PLAN_COLS}",
                 (uid, pid, tok.get("token_id"), CONTRACT, body["source_instance"], PLAN_DAYS))
    return _plan_out(r)


def _parse_lines(raw: bytes) -> list:
    if len(raw) > CHUNK_MAX_BYTES:
        raise _err("PAYLOAD-LIMIT", f"청크는 {CHUNK_MAX_BYTES} 바이트까지예요.", "나눠서 보내세요.")
    try:
        text = bytes(raw).decode("utf-8")
    except UnicodeDecodeError:
        raise _bad("$", "utf8")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise _bad("$", "empty_chunk")
    out = []
    for i, ln in enumerate(lines):
        if len(ln.encode("utf-8")) > ITEM_MAX_BYTES:
            raise _bad(f"lines[{i}]", "too_long_bytes")
        try:
            out.append(imports.parse_request(ln.encode("utf-8")))
        except CrmError as e:
            raise _bad(f"lines[{i}]", e.message.split(": ", 1)[-1])
    return out


def plan_upload(tok: dict, plan_id: str, raw: bytes, offset) -> dict:
    """POST /api/migration/plans/{id}/items?offset=N — JSONL(한 줄 = 항목 하나) 청크를 받은 순으로 덧붙인다. N = 지금까지 받은 항목 수
    (다르면 409 CHUNK-OFFSET + received — 응답이 끊긴 청크를 다시 보낼 때 쓴다). 청크 하나는 전부 저장하거나 전부 거절.
    반환 {"plan_id", "received", "staged_bytes"}."""
    uid = tok["user_id"]
    _sweep(uid)
    items = _parse_lines(raw)
    db.check_global_quota(uid)
    with tx() as c:
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        _need_state(pl, "staged")
        if not imports._is_int(offset) or offset != pl["item_count"]:
            raise _err("CHUNK-OFFSET", "청크 시작 위치(offset)가 서버가 받은 항목 수와 달라요.", "received 부터 다시 보내세요.",
                       received=pl["item_count"])
        if pl["item_count"] + len(items) > PLAN_MAX_ITEMS:
            raise _err("PAYLOAD-LIMIT", f"plan 하나는 {PLAN_MAX_ITEMS}항목까지예요.", "plan 을 나누세요.")
        seen = {r["original_id"] for r in _all(c, "SELECT original_id FROM migration_plan_items WHERE user_id=%s AND plan_id=%s",
                                               (uid, plan_id))}
        rows, nbytes = [], 0
        for i, it in enumerate(items):
            check_item(it, pl["source_instance"], f"lines[{i}]")
            if it["original_id"] in seen:
                raise _bad(f"lines[{i}].original_id", "duplicate_in_plan")
            seen.add(it["original_id"])
            b = imports.jcs(it)
            nbytes += len(b)
            rows.append((it, b))
        used = _one(c, "SELECT COALESCE(sum(i.payload_bytes), 0) AS b FROM migration_plan_items i JOIN migration_plans p "
                       "ON p.user_id=i.user_id AND p.id=i.plan_id WHERE i.user_id=%s AND p.state IN ('staged','sealed')", (uid,))["b"]
        if used + nbytes > USER_STAGING_MAX_BYTES:
            raise _err("STAGING-FULL", f"스테이징은 사용자당 {USER_STAGING_MAX_BYTES} 바이트까지예요.", "반영하거나 취소한 뒤 다시 보내세요.")
        for k, (it, b) in enumerate(rows):
            c.execute("INSERT INTO migration_plan_items (user_id,plan_id,seq,original_id,source_revision,unit_kind,target_kind,content_hash,"
                      "item_sha256,payload,payload_bytes) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (uid, plan_id, pl["item_count"] + k, it["original_id"], it["source_revision"], it["unit_kind"],
                       target_kind_of(it["unit_kind"]), bytes.fromhex(it["content_hash"]), hashlib.sha256(b).digest(), Jsonb(it), len(b)))
        r = _one(c, "UPDATE migration_plans SET item_count=item_count+%s, staged_bytes=staged_bytes+%s WHERE user_id=%s AND id=%s "
                    "RETURNING item_count, staged_bytes", (len(rows), nbytes, uid, plan_id))
    return {"plan_id": plan_id, "received": r["item_count"], "staged_bytes": r["staged_bytes"]}


# ── dry-run · 반영 공통 ─────────────────────────────────────
_ITEM_COLS = ("seq,original_id,source_revision,unit_kind,target_kind,content_hash,item_sha256,payload,payload_bytes,action,reason,checked,"
              "result,target_id,applied_at,created,decision_deferred")


def _items(c, uid, plan_id):
    return _all(c, f"SELECT {_ITEM_COLS} FROM migration_plan_items WHERE user_id=%s AND plan_id=%s ORDER BY seq", (uid, plan_id))


def _deps(it: dict) -> set:
    """이 항목이 기대는 다른 항목의 original_id — references·attach·source_ref."""
    out = set()
    for x in it.get("references") or []:
        if "original_id" in x.get("target", {}):
            out.add(x["target"]["original_id"])
    for k in ("attach_to", "axes"):
        for t in (it.get("attach") or {}).get(k) or []:
            if "original_id" in t:
                out.add(t["original_id"])
    if it.get("source_ref"):
        out.add(it["source_ref"]["original_id"])
    return out


def _dup_warns(c, uid, plan, rows, skip) -> dict:
    """K5 — 같은 source_instance 에서 original_id 가 다른데 content_hash 가 같으면 warn(기록·항목, 정규화 본문이 빈 것 제외).
    distinct=true 거나 supersedes 가 그 다른 original_id 면 넘어간다. 대조 = 같은 plan + 앞서 반영한 plan 항목."""
    by_hash = {}
    for r in rows:
        if r["seq"] in skip or r["target_kind"] == "source" or not normalize(r["payload"].get("body") or "").strip():
            continue
        by_hash.setdefault(bytes(r["content_hash"]), []).append(r)
    past = {}
    if by_hash:
        for x in _all(c, "SELECT i.content_hash, i.original_id FROM migration_plan_items i JOIN migration_plans p ON p.user_id=i.user_id "
                         "AND p.id=i.plan_id WHERE i.user_id=%s AND p.source_instance=%s AND p.id <> %s AND i.result IN ('applied','noop') "
                         "AND NOT (p.state = 'reverted' AND i.created IS TRUE) AND i.content_hash = ANY(%s)", (uid, plan["source_instance"], plan["id"], list(by_hash))):
            past.setdefault(bytes(x["content_hash"]), set()).add(x["original_id"])
    out = {}
    for h, rs in by_hash.items():
        for r in rs:
            others = ({x["original_id"] for x in rs} | past.get(h, set())) - {r["original_id"]}
            if not others or r["payload"].get("distinct") is True or r["payload"].get("supersedes") in others:
                continue
            out[r["seq"]] = "duplicate_content"
    return out


def _stream_in(c, uid):
    """사용자의 board_migration 입력원(대응표 import_entries 의 stream) — 없으면 만든다(같은 트랜잭션). 병행 기간은 보지 않는다(새 경로)."""
    r = _one(c, "SELECT id FROM import_streams WHERE user_id=%s AND channel='board_migration'", (uid,))
    if not r:
        c.execute("INSERT INTO import_streams (user_id,id,channel,label) VALUES (%s,%s,'board_migration','board 이전')",
                  (uid, "is_" + secrets.token_hex(12)))
    return imports._mig_lock(c, uid, _one(c, "SELECT id FROM import_streams WHERE user_id=%s AND channel='board_migration'", (uid,))["id"])


def _prev_revision(c, uid, sid, original_id, revision):
    """서버 대응표로 정하는 previous_revision — 그 원본의 최신 접수 판(같은 판 재전송이면 그 판이 처음 받은 부모)."""
    lt = _one(c, "SELECT source_revision, previous_entry_id FROM import_entries WHERE user_id=%s AND stream_id=%s AND original_id=%s "
                 "AND is_latest_received", (uid, sid, original_id))
    if not lt:
        return None
    if lt["source_revision"] != revision:
        return lt["source_revision"]
    if not lt["previous_entry_id"]:
        return None
    p = _one(c, "SELECT source_revision FROM import_entries WHERE user_id=%s AND id=%s", (uid, lt["previous_entry_id"]))
    return p["source_revision"] if p else None


_PROJ_KEYS = ("unit_kind", "title", "body", "code", "fields", "decision", "references", "attach", "source_ref", "author_kind",
              "text_process", "generation_kind", "primary_date", "redaction")


def _apply_source(c, uid, it):
    """출처 메타(K7) — 자연키 (kind, name, location=anchor 해시). 같은 location 에 다른 kind·name 이 있으면 conflict."""
    s = it["source"]
    hit = _one(c, "SELECT id FROM sources WHERE user_id=%s AND kind=%s AND name=%s AND location=%s", (uid, s["kind"], s["name"], s["location"]))
    if hit:
        return "noop", hit["id"]
    if _one(c, "SELECT 1 FROM sources WHERE user_id=%s AND location=%s", (uid, s["location"])):
        raise CrmError("CONFLICT", "같은 출처 위치에 다른 이름·종류가 이미 있어요.")
    sid = db.new_id("s")
    c.execute("INSERT INTO sources (user_id,id,kind,name,location) VALUES (%s,%s,%s,%s,%s)", (uid, sid, s["kind"], s["name"], s["location"]))
    return "insert", sid


def _apply_one(c, uid, st, plan, r, defs, by_oid, srcmap, lower=False):
    """항목 하나 반영(호출자 savepoint 안) → {"action": insert|noop, "target_id", "created"}. 실패 = CrmError(conflict·reject 로 분류된다).
    lower = MCP 경로(가안 X) — decision=confirmed 기준의 결정을 반영하지 않는다(decide 를 부르지 않음 — 새 기준은 기본 pending 으로 남고,
    이미 확정된 기준은 그대로: 묶음 반영이 판단 상태를 올리지도 내리지도 않는다). 투영 해시는 받은 값 그대로(seal 과 같은 action).
    deferred = 반영 뒤 그 기준이 확정이 아니다(확정 표시가 미뤄졌다)."""
    it = r["payload"]
    if r["target_kind"] == "source":
        act, sid = _apply_source(c, uid, it)
        srcmap[it["original_id"]] = sid
        return {"action": act, "target_id": sid, "created": act == "insert"}
    tk = r["target_kind"]
    oid = None
    if tk == "item":
        oid, why = _cli.resolve_object(defs, it["object_ref"])
        if why:
            raise CrmError(why.split(":")[0].upper(), "대상 오브젝트를 해석하지 못했어요.")
        if by_oid[oid].get("archived_at"):
            raise CrmError("OBJECT-ARCHIVED", "대상 오브젝트가 보관됐어요.")
        probs = _cli._field_problems(by_oid[oid], it.get("fields"), "$")
        if probs:
            raise CrmError(probs[0][1].upper(), "항목 필드가 대상 오브젝트와 맞지 않아요.")
    sid = None
    if it.get("source_ref"):
        sid = srcmap.get(it["source_ref"]["original_id"])
        if not sid:
            raise CrmError("SOURCE-REF-NOT-FOUND", "source_ref 가 가리키는 출처가 아직 이관되지 않았어요.")
    sca, sdate, dk = _dates(it)
    hist = {"generation_kind": it["generation_kind"], "primary_date": it["primary_date"], "other_dates": it.get("other_dates") or [],
            "decision_ref": it["review"].get("decision_ref"), "redaction": it.get("redaction"), "plan_id": plan["id"],
            "original_id": it["original_id"], "source_revision": it["source_revision"]}
    gm = {"reported_by": "board_migration", "author_kind": it["author_kind"], "text_process": it["text_process"], "date_kind": dk,
          "primary_date": it["primary_date"], "other_dates": it.get("other_dates") or [], "redaction": it.get("redaction")}
    ext = {"author_kind": it["author_kind"], "text_process": it["text_process"], "generation_kind": it["generation_kind"], "date_kind": dk,
           "source_id": sid, "history": hist, "generation_meta": gm}
    row = {"original_id": it["original_id"], "revision": it["source_revision"], "target_kind": tk, "unit_kind": it["unit_kind"],
           "object_id": oid, "code": it.get("code"), "title": it.get("title"), "body": it.get("body") or "", "fields": it.get("fields"),
           "decision": None if lower else it.get("decision"),
           "references": it.get("references"), "attach": it.get("attach"), "expected_target_revision": it.get("expected_target_revision")}
    proj = {k: it.get(k) for k in _PROJ_KEYS}
    proj["object_id"] = oid
    pr = _prev_revision(c, uid, st["id"], it["original_id"], it["source_revision"])
    out = imports.mig_apply_in(c, uid, st, row, pr, tk, sca, sdate, plan["id"], None, CONTRACT, bytes(r["item_sha256"]),
                               hashlib.sha256(imports.jcs(proj)).digest(), window=False, gate=False, ext=ext)
    fresh = out["state"] == "applied" and not out["duplicate"]
    res = {"action": "insert" if fresh else "noop", "target_id": out["target_id"], "created": bool(fresh and out.get("created"))}
    if lower and fresh and tk == "item":
        res["deferred"] = _one(c, "SELECT decision FROM items WHERE user_id=%s AND id=%s", (uid, out["target_id"]))["decision"] != "confirmed"
    return res


def _order(rows) -> tuple:
    """반영 순서 — 출처 먼저(seq 순), 그다음 기록·항목은 CLI 와 같은 의존성 순서(축·선행 항목 → 기록 → 기록을 참조하는 항목).
    반환 (순서 seq 목록, 순환으로 거절할 seq 집합)."""
    srcs = [r["seq"] for r in rows if r["target_kind"] == "source"]
    rest = [r for r in rows if r["target_kind"] != "source"]
    v1 = [{"original_id": r["payload"]["original_id"], "target_kind": r["target_kind"], "references": r["payload"].get("references"),
           "attach": r["payload"].get("attach")} for r in rest]
    try:
        idx = _cli.order_rows(v1)
        return srcs + [rest[i]["seq"] for i in idx], set()
    except _cli.Reject as e:
        bad = {rest[int(at.split("[")[1].split("]")[0])]["seq"] for at, _rule in e.problems}
        ok = [r for r in rest if r["seq"] not in bad]
        again, more = _order([{**r} for r in ok]) if ok else ([], set())
        return srcs + [s for s in again if s not in srcs], bad | more


def _simulate(c, uid, plan, rows, include: set, lower: frozenset = frozenset()) -> dict:
    """include 의 항목을 실제로 반영해 본다(항목마다 savepoint — 실패한 항목만 되돌리고 계속). 호출자가 바깥 savepoint 로 전체를 되돌리면
    dry-run, 그대로 두면 반영. 반환 {seq: {"action", "target_id"?, "reason"?}}."""
    st = _stream_in(c, uid)
    defs = db.definitions(uid, include_archived=True)
    by_oid = {d["id"]: d for d in defs}
    srcmap = {x["original_id"]: x["target_id"] for x in _all(
        c, "SELECT DISTINCT ON (original_id) original_id, target_id FROM migration_plan_items WHERE user_id=%s AND target_kind='source' "
           "AND result IN ('applied','noop') ORDER BY original_id, applied_at DESC", (uid,))}
    use = [r for r in rows if r["seq"] in include]
    order, cyc = _order(use)
    out = {s: {"action": "reject", "reason": "dependency_cycle"} for s in cyc}
    by_seq = {r["seq"]: r for r in use}
    for s in order:
        try:
            with c.transaction():
                out[s] = _apply_one(c, uid, st, plan, by_seq[s], defs, by_oid, srcmap, s in lower)
        except CrmError as e:
            out[s] = {"action": "conflict" if e.code in CONFLICT_CODES else "reject", "reason": e.code.lower()}
        except psycopg.Error as e:   # DB 제약 위반 등 — 그 항목만 거절(어느 제약인지만)
            out[s] = {"action": "reject", "reason": "db_" + type(e).__name__.lower()}
    return out


class _Undo(Exception):
    """dry-run 되돌리기 표식."""


def _counts(rows, key) -> dict:
    out = {"actions": {}, "units": {}}
    for r in rows:
        v = r[key]
        if v is None:
            continue
        out["actions"][v] = out["actions"].get(v, 0) + 1
        u = out["units"].setdefault(r["unit_kind"], {})
        u[v] = u.get(v, 0) + 1
    return out


def _item_brief(r) -> dict:
    return {"seq": r["seq"], "original_id": r["original_id"], "source_revision": r["source_revision"], "unit_kind": r["unit_kind"],
            "target_kind": r["target_kind"], "content_hash": bytes(r["content_hash"]).hex(), "action": r["action"], "reason": r["reason"]}


def plan_seal(tok: dict, plan_id: str, item_count) -> dict:
    """POST /api/migration/plans/{id}/seal {item_count} — 의미 검사(K2~K7) · 중복 warn(K5) · dry-run(실제 반영을 savepoint 에서 되돌림)
    · plan_hash 고정 → sealed. reject 항목 본문은 바로 지운다. 반환 = plan_status 모양."""
    uid = tok["user_id"]
    _sweep(uid)
    if not imports._is_int(item_count):
        raise _bad("item_count", "int")
    with db.tx_scope() as c, db.migration_mode():
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        _need_state(pl, "staged")
        if item_count != pl["item_count"]:
            raise _err("PLAN-COUNT-MISMATCH", "seal 하려는 항목 수가 서버가 받은 수와 달라요.", "빠진 청크를 보낸 뒤 다시 seal 하세요.",
                       received=pl["item_count"])
        if pl["item_count"] == 0:
            raise _err("PLAN-EMPTY", "항목이 없는 plan 이에요.", "항목을 보낸 뒤 seal 하세요.")
        rows = _items(c, uid, plan_id)
        res = {r["seq"]: {"action": "reject", "reason": why} for r in rows if (why := semantic_reject(r["payload"]))}
        res.update({s: {"action": "warn", "reason": w} for s, w in _dup_warns(c, uid, pl, rows, set(res)).items()})
        include = {r["seq"] for r in rows} - set(res)
        sim = {}
        try:
            with c.transaction():
                sim = _simulate(c, uid, pl, rows, include)
                raise _Undo
        except _Undo:
            pass
        res.update(sim)
        for r in rows:
            a = res[r["seq"]]
            drop = a["action"] == "reject"
            c.execute("UPDATE migration_plan_items SET action=%s, reason=%s" + (", payload=NULL, payload_bytes=0" if drop else "")
                      + " WHERE user_id=%s AND plan_id=%s AND seq=%s", (a["action"], a.get("reason"), uid, plan_id, r["seq"]))
        ph = plan_hash_of([r["item_sha256"] for r in rows])
        rows = _items(c, uid, plan_id)
        summary = {"dry_run": _counts(rows, "action")}
        c.execute("UPDATE migration_plans SET state='sealed', sealed_at=now(), plan_hash=%s, summary=%s, "
                  "staged_bytes=(SELECT COALESCE(sum(payload_bytes),0) FROM migration_plan_items WHERE user_id=%s AND plan_id=%s) "
                  "WHERE user_id=%s AND id=%s", (bytes.fromhex(ph), Jsonb(summary), uid, plan_id, uid, plan_id))
        pl = _one(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s AND id=%s", (uid, plan_id))
        return _status(pl, rows)


def _status(pl, rows, web=False) -> dict:
    d = _plan_out(pl)
    d["counts"] = _counts(rows, "action")
    items = []
    for r in rows:
        b = _item_brief(r)
        if web:
            p = r["payload"] or {}
            title = (p.get("title") or "").strip() or ((p.get("source") or {}).get("name") if r["target_kind"] == "source" else None) \
                or ((p.get("body") or "").strip().splitlines() or [""])[0][:40]
            b.update({"title": title if r["payload"] is not None else None, "has_body": r["payload"] is not None,
                      "needs_check": r["unit_kind"] in PRINCIPLE_UNITS and r["action"] in ("insert", "noop"), "checked": r["checked"],
                      "result": r["result"], "target_id": r["target_id"]})
        items.append(b)
    d["items"] = items
    return d


def plan_status(tok: dict, plan_id: str) -> dict:
    """GET /api/migration/plans/{id} (토큰) — 상태·dry-run 집계·항목별 action(본문 없음)."""
    uid = tok["user_id"]
    _sweep(uid)
    with tx() as c:
        pl = _plan_lock(c, uid, plan_id)
        return _status(pl, _items(c, uid, plan_id))


def plan_cancel(uid: str, plan_id: str) -> dict:
    """취소(토큰·웹 세션) — staged·sealed → cancelled, 항목 본문 즉시 영구 삭제. 이미 cancelled 면 그대로(멱등)."""
    _sweep(uid)
    with tx() as c:
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        if pl["state"] != "cancelled":
            _need_state(pl, "staged", "sealed")
            c.execute("UPDATE migration_plans SET state='cancelled', closed_at=now(), staged_bytes=0 WHERE user_id=%s AND id=%s", (uid, plan_id))
            c.execute("UPDATE migration_plan_items SET payload=NULL, payload_bytes=0 WHERE user_id=%s AND plan_id=%s", (uid, plan_id))
        pl = _one(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s AND id=%s", (uid, plan_id))
        return _plan_out(pl)


# ── 웹 세션: 확인 · 체크 · 반영 ─────────────────────────────

def _used_today(c, uid) -> int:
    """오늘(KST) 쓴 이관 반영 행 — db._DAILY_SOURCES["migration"] 과 같은 셈(되돌린 행도 센다)."""
    return _one(c, f"SELECT count(*) AS n FROM import_entries WHERE user_id=%s AND received_at >= {db._KST_TODAY} "
                   "AND kind IN ('migration_item','migration_record') AND state IN ('applied','reverted')", (uid,))["n"] \
        + _one(c, f"SELECT count(*) AS n FROM migration_plan_items WHERE user_id=%s AND applied_at >= {db._KST_TODAY} "
                  "AND target_kind='source' AND result='applied'", (uid,))["n"]


def plans_list(uid: str) -> dict:
    """웹·MCP — {"plans": [plan(최근 20, via·reverted_at 포함)], "enabled", "allowed", "mcp_enabled", "limits"}. 본문 없음."""
    with tx() as c:
        _close_due(c, uid)
        rows = _all(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s ORDER BY created_at DESC, id DESC LIMIT 20", (uid,))
        used = _used_today(c, uid)
    return {"plans": [_plan_out(r) for r in rows], **switch_state(uid), "mcp_enabled": mcp_on(),
            "limits": {"daily": DAILY_LIMIT, "used_today": used, "plan_items": PLAN_MAX_ITEMS, "plan_days": PLAN_DAYS,
                       "staging_bytes": USER_STAGING_MAX_BYTES, "open_plans": OPEN_PLANS_MAX}}


def plan_detail(uid: str, plan_id: str) -> dict:
    """웹 — plan + 집계 + 항목 목록(제목·action·사유·체크 필요/여부·결과 — 본문은 plan_item 으로 하나씩)."""
    _sweep(uid)
    with tx() as c:
        pl = _plan_lock(c, uid, plan_id)
        return _status(pl, _items(c, uid, plan_id), web=True)


def plan_item(uid: str, plan_id: str, seq) -> dict:
    """웹 — 항목 전문 하나(받은 그대로 + action·사유). 본문이 지워진 항목(reject·반영·취소·만료)은 payload=null."""
    _sweep(uid)
    try:
        seq = int(seq)
    except (TypeError, ValueError):
        raise imports._nf("그 항목")
    with tx() as c:
        _plan_lock(c, uid, plan_id)
        r = _one(c, f"SELECT {_ITEM_COLS} FROM migration_plan_items WHERE user_id=%s AND plan_id=%s AND seq=%s", (uid, plan_id, seq))
    if not r:
        raise imports._nf("그 항목")
    d = _item_brief(r)
    d.update({"payload": r["payload"], "checked": r["checked"], "needs_check": r["unit_kind"] in PRINCIPLE_UNITS and r["action"] in ("insert", "noop"),
              "result": r["result"], "target_id": r["target_id"]})
    return d


def plan_check(uid: str, plan_id: str, seqs, checked) -> dict:
    """웹 — 기준(principle_c·principle_wd) 항목 체크 켜기/끄기. sealed 의 insert·noop 기준 항목만. 반환 plan_detail."""
    _sweep(uid)
    if not isinstance(seqs, list) or not seqs or len(seqs) > PLAN_MAX_ITEMS or not all(imports._is_int(s) for s in seqs) \
            or not isinstance(checked, bool):
        raise CrmError("ARG-INVALID", "seqs 는 항목 번호 목록, checked 는 true·false 예요.")
    with tx() as c:
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        _need_state(pl, "sealed")
        ok = {r["seq"] for r in _all(c, "SELECT seq FROM migration_plan_items WHERE user_id=%s AND plan_id=%s AND seq = ANY(%s) "
                                        "AND unit_kind = ANY(%s) AND action IN ('insert','noop')", (uid, plan_id, seqs, list(PRINCIPLE_UNITS)))}
        if ok != set(seqs):
            raise CrmError("ARG-INVALID", "체크할 수 있는 건 반영 대상(insert·noop)인 기준 항목뿐이에요.")
        c.execute("UPDATE migration_plan_items SET checked=%s WHERE user_id=%s AND plan_id=%s AND seq = ANY(%s)", (checked, uid, plan_id, seqs))
    return plan_detail(uid, plan_id)


def _readback(c, uid, r) -> dict:
    """반영 대상의 지금 본문을 재해시(read-back, 본문 없음). 휴지통·영구 삭제면 stored_hash=null + target_state."""
    tid, tk = r["target_id"], r["target_kind"]
    if not tid:
        return {"stored_hash": None, "target_state": None}
    if tk == "record":
        x = _one(c, "SELECT body AS t, (trashed_at IS NOT NULL OR deleted_at IS NOT NULL) AS gone FROM records WHERE user_id=%s AND id=%s", (uid, tid))
    elif tk == "item":
        x = _one(c, "SELECT body AS t, (trashed_at IS NOT NULL) AS gone FROM items WHERE user_id=%s AND id=%s", (uid, tid))
    else:
        x = _one(c, "SELECT name AS t, false AS gone FROM sources WHERE user_id=%s AND id=%s", (uid, tid))
    if not x:
        return {"stored_hash": None, "target_state": "missing"}
    if x["gone"]:
        return {"stored_hash": None, "target_state": "trashed"}
    return {"stored_hash": content_hash(x["t"] or ""), "target_state": "live"}


def receipt(uid: str, plan_id: str | None = None) -> dict:
    """영수증(K9) — 반영한 plan(applied·reverted). plan_id 없으면 가장 최근에 반영한 plan. 본문 없음:
    {"plan_id", "import_batch_id", "plan_hash", "receipt_hash", "applied_at", "state", "via", "reverted_at",
     "counts": {"results": {result: n}, "units": {unit: {result: n}}, "decision_deferred": n, "kept_on_revert": n},
     "items": [{seq, original_id, source_revision, unit_kind, target_kind, content_hash, result, reason, target_id, stored_hash, target_state,
                created, via, decision_deferred}]}.
    receipt_hash = SHA-256(JCS(seq 순 [original_id, source_revision, content_hash, result, target_id])) — 가안 X 에서도 정의 불변.
    created = 이 반영이 대상을 새로 만들었나(되돌리면 휴지통 · 옛 반영은 null = 모름) · via = 반영 경로 web·mcp(옛 반영 null)
    · decision_deferred = MCP 반영이 확정(confirmed) 표시 기준을 확정하지 않고 넣었다(반영 뒤 미확정) · kept_on_revert = 되돌려도 남는 갱신 수
    (이전 판은 항목 이력 restore) · reason = decision_excluded(MCP 가 반입하지 않은 제외 기준) 또는 seal 사유."""
    _sweep(uid)
    with tx() as c:
        if plan_id:
            pl = _plan_lock(c, uid, plan_id)
        else:
            pl = _one(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s AND state IN ('applied','reverted') "
                         "ORDER BY applied_at DESC LIMIT 1", (uid,))
            if not pl:
                raise imports._nf("반영한 이관 plan")
        _need_state(pl, "applied", "reverted")
        rows = _items(c, uid, pl["id"])
        items = []
        for r in rows:
            b = {k: v for k, v in _item_brief(r).items() if k != "action"}
            b.update({"result": r["result"], "target_id": r["target_id"], **_readback(c, uid, r), "created": r["created"], "via": pl["via"],
                      "decision_deferred": r["decision_deferred"]})
            items.append(b)
    rh = hashlib.sha256(imports.jcs([[x["original_id"], x["source_revision"], x["content_hash"], x["result"], x["target_id"]]
                                     for x in items])).hexdigest()
    cnt = _counts(rows, "result")
    return {"plan_id": pl["id"], "import_batch_id": pl["id"], "plan_hash": bytes(pl["plan_hash"]).hex(), "receipt_hash": rh,
            "applied_at": imports._j(pl["applied_at"]), "state": pl["state"], "via": pl["via"], "reverted_at": imports._j(pl["reverted_at"]),
            "counts": {"results": cnt["actions"], "units": cnt["units"], "decision_deferred": sum(1 for r in rows if r["decision_deferred"]),
                       "kept_on_revert": sum(1 for r in rows if r["result"] == "applied" and r["target_kind"] != "source"
                                             and r["created"] is not True)},
            "items": items}


_SKIP = {"warn": "skipped_warn", "reject": "skipped_reject", "conflict": "skipped_conflict"}


def _rules(rows, via):
    """반영 대상 규칙 → (include, skipped{seq: result}, reasons{seq: reason}, lower). sealed 의 insert·noop 만 반영 후보.
    · web(불변): 기준(principle_c·principle_wd) 중 체크 안 한 것 = skipped_unchecked. decision 은 받은 그대로(confirmed 면 확정까지).
    · mcp(가안 X §5): 체크 표식과 무관하게 기준 전부 반입 — decision=excluded 는 반입 안 함(skipped_reject, reason decision_excluded),
      decision=confirmed 는 결정을 반영하지 않는다(lower — 새 기준은 미확정, 이미 확정된 기준은 그대로). 확정은 item_decide(confirm) 하나씩."""
    live = {r["seq"] for r in rows if r["action"] in ("insert", "noop")}
    skipped, reasons, lower = {}, {}, set()
    for r in rows:
        s = r["seq"]
        if s not in live or r["unit_kind"] not in PRINCIPLE_UNITS:
            continue
        dec = (r["payload"] or {}).get("decision")
        if via == "web":
            if not r["checked"]:
                skipped[s] = "skipped_unchecked"
        elif dec == "excluded":
            skipped[s], reasons[s] = "skipped_reject", "decision_excluded"
        elif dec == "confirmed":
            lower.add(s)
    return live - set(skipped), skipped, reasons, frozenset(lower)


def _predict(rows, include, skipped) -> dict:
    """sealed action 과 규칙으로 정해지는 결과 개수 {result: n} — MCP 반영 바인딩(expected_counts)."""
    out = {}
    for r in rows:
        s = r["seq"]
        res = ("applied" if r["action"] == "insert" else "noop") if s in include else (skipped.get(s) or _SKIP[r["action"]])
        out[res] = out.get(res, 0) + 1
    return out


def _blocked_by(rows, include, skipped) -> list:
    """반입하지 않는 기준(미체크·제외)을 가리키는 반영 항목의 seq — 있으면 CHECK-DEPENDENCY."""
    gone = {rows[s]["original_id"] for s in skipped}
    return sorted(r["seq"] for r in rows if r["seq"] in include and _deps(r["payload"]) & gone)


def _mismatch(field, server):
    return _err("APPLY-MISMATCH", f"반영 인자({field})가 서버 값과 달라요. 아무것도 반영하지 않았어요.",
                "migration_apply_preview 를 다시 불러 그 plan_hash·expected_counts 를 그대로 보내세요.", field=field, server=server)


def plan_apply(uid: str, plan_id: str, plan_hash, *, via: str = "web", expected_counts=None) -> dict:
    """[반영] — 웹 세션(via=web, 의미 불변) · MCP migration_apply(via=mcp, 가안 X). 같은 함수, 차이는 _rules 와 바인딩뿐.
    한 트랜잭션: plan_hash 대조(요청 = 고정값 = 저장 바이트 재계산) → (mcp) expected_counts 대조 → 반입 안 하는 기준의 의존 거절
    → 남은 이관 한도 ≥ 반영 행 → action 재계산(seal 과 같은 코드) — seal 과 다르면 시작하지 않음(PLAN-STALE, 재stage) → 전부 반영 또는 전부 롤백.
    이미 applied = 같은 영수증 + already_applied(두 번째 반영 = noop). MCP 바인딩: plan_hash·expected_counts 가 서버 값과 정확히 같아야 시작
    (아니면 APPLY-MISMATCH + detail{field, server}). 영수증 항목 created·via·decision_deferred, item_history.event_meta.via 를 남긴다.
    반환 = receipt + already_applied."""
    if via not in ("web", "mcp"):
        raise ValueError(via)
    mcp = via == "mcp"
    _sweep(uid)
    gate(uid)
    if not isinstance(plan_hash, str) or not _HEX64.match(plan_hash):
        raise CrmError("ARG-INVALID", "plan_hash 는 64자리 소문자 hex 예요.")
    if mcp and (not isinstance(expected_counts, dict) or not all(isinstance(k, str) and imports._is_int(v) for k, v in expected_counts.items())):
        raise CrmError("ARG-INVALID", "expected_counts 는 migration_apply_preview 가 준 {결과: 개수} 그대로예요.")
    db.check_global_quota(uid)
    with db.tx_scope() as c, db.migration_mode(via=via):
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        if pl["state"] == "applied":
            stored = bytes(pl["plan_hash"]).hex()
            if stored != plan_hash:
                if mcp:
                    raise _mismatch("plan_hash", stored)
                raise _err("PLAN-HASH-MISMATCH", "확인한 plan 과 반영된 plan 이 달라요.", "목록을 새로 고치세요.")
            if mcp:
                got = _counts(_items(c, uid, plan_id), "result")["actions"]
                if expected_counts != got:
                    raise _mismatch("expected_counts", got)
            done = True
        else:
            done = False
            _need_state(pl, "sealed")
            rows = _items(c, uid, plan_id)
            live = [r for r in rows if r["payload"] is not None]
            stored = bytes(pl["plan_hash"]).hex()
            if mcp and stored != plan_hash:
                raise _mismatch("plan_hash", stored)
            if stored != plan_hash or plan_hash_of([r["item_sha256"] for r in rows]) != plan_hash \
                    or any(item_sha256(r["payload"]) != bytes(r["item_sha256"]) for r in live):
                raise _err("PLAN-HASH-MISMATCH", "확인한 plan 과 서버에 저장한 plan 이 달라요.", "취소하고 PC 에서 다시 stage 하세요.")
            include, skipped, reasons, lower = _rules(rows, via)
            if mcp:
                want = _predict(rows, include, skipped)
                if expected_counts != want:
                    raise _mismatch("expected_counts", want)
            blocked = _blocked_by(rows, include, skipped)
            if blocked:
                if mcp:
                    raise _err("CHECK-DEPENDENCY", "반입하지 않는 기준(decision=excluded)을 가리키는 항목이 있어요.",
                               "PC 에서 그 항목을 빼거나 기준의 decision 을 바꿔 다시 stage 하세요.", seqs=blocked)
                raise _err("CHECK-DEPENDENCY", "체크하지 않은 기준 항목을 가리키는 항목이 있어요.",
                           "그 기준을 체크하거나, 취소하고 그 항목을 뺀 plan 을 다시 stage 하세요.", seqs=blocked)
            n = sum(1 for r in rows if r["seq"] in include and r["action"] == "insert")
            try:
                db._daily_gate(c, uid, "migration", n)
            except CrmError as e:
                raise imports._with_resume(_err("RATE-LIMIT", f"오늘 남은 이관 한도({DAILY_LIMIT}행/일)보다 반영할 행이 많아요.",
                                                "내일(KST 0시 이후) 다시 반영하세요. 시작하지 않았어요.", needed=n)) from e
            sim = _simulate(c, uid, pl, rows, include, lower)
            changed = [{"seq": s, "sealed": rows[s]["action"], "now": sim[s]["action"], "reason": sim[s].get("reason")}
                       for s in sorted(include) if sim[s]["action"] != rows[s]["action"]]
            if changed:
                raise _err("PLAN-STALE", "확인 뒤 서버 상태가 바뀌어 반영 결과가 dry-run 과 달라요. 아무것도 반영하지 않았어요.",
                           "취소하고 PC 에서 다시 stage 하세요.", changed=changed)
            for r in rows:
                s = r["seq"]
                if s in include:
                    res, tid, cr = ("applied" if sim[s]["action"] == "insert" else "noop"), sim[s]["target_id"], sim[s].get("created", False)
                    dd, why = bool(sim[s].get("deferred")), r["reason"]
                else:
                    res, tid, cr, dd, why = skipped.get(s) or _SKIP[r["action"]], None, None, False, reasons.get(s, r["reason"])
                c.execute("UPDATE migration_plan_items SET result=%s, target_id=%s, created=%s, decision_deferred=%s, reason=%s, "
                          "applied_at=now(), payload=NULL, payload_bytes=0 WHERE user_id=%s AND plan_id=%s AND seq=%s",
                          (res, tid, cr, dd, why, uid, plan_id, s))
            rows = _items(c, uid, plan_id)
            summary = {**(pl["summary"] or {}), "receipt": _counts(rows, "result")}
            c.execute("UPDATE migration_plans SET state='applied', applied_at=now(), via=%s, staged_bytes=0, summary=%s WHERE user_id=%s AND id=%s",
                      (via, Jsonb(summary), uid, plan_id))
            db._audit(c, "migration_apply", uid, uid, {"plan": plan_id, "applied": n, "via": via, "result": "ok"})
    out = receipt(uid, plan_id)
    out["already_applied"] = done
    return out


def apply_preview(uid: str, plan_id: str) -> dict:
    """MCP migration_apply_preview(가안 X) — 읽기 계산만(쓰지 않는다). sealed = MCP 규칙(_rules via=mcp)으로 낼 결과:
    {"plan_id", "state", "plan_hash", "expected_counts": {result: n}, "counts": {actions, units}, "will_apply_rows", "remaining_today",
     "blocked": [code], "decision_deferred", "decision_excluded", "message"}. plan_hash·expected_counts 를 그대로 migration_apply 에 넘긴다.
    blocked = 지금 반영하면 날 거절(CHECK-DEPENDENCY + blocked_seqs · RATE-LIMIT · PLAN-STATE). 반영 때 action 재계산이 seal 과 다르면 PLAN-STALE.
    applied = 이미 반영한 결과 개수(already_applied — 같은 값으로 부르면 같은 영수증)."""
    _sweep(uid)
    with tx() as c:
        pl = _plan_lock(c, uid, plan_id)
        rows = _items(c, uid, plan_id)
        used = _used_today(c, uid)
        firm = {x["original_id"] for x in _all(
            c, "SELECT e.original_id FROM import_entries e JOIN import_streams s ON s.user_id=e.user_id AND s.id=e.stream_id "
               "JOIN items i ON i.user_id=e.user_id AND i.id=e.target_item_id WHERE e.user_id=%s AND s.channel='board_migration' "
               "AND e.is_current_applied AND i.decision='confirmed' AND e.original_id = ANY(%s)",
            (uid, [r["original_id"] for r in rows if r["unit_kind"] in PRINCIPLE_UNITS]))}
    out = {"plan_id": pl["id"], "state": pl["state"], "plan_hash": bytes(pl["plan_hash"]).hex() if pl["plan_hash"] else None,
           "counts": _counts(rows, "action"), "remaining_today": max(0, DAILY_LIMIT - used), "message": MCP_DEFER_MSG}
    blocked = []
    if pl["state"] == "sealed":
        include, skipped, reasons, lower = _rules(rows, "mcp")
        dep = _blocked_by(rows, include, skipped)
        n = sum(1 for r in rows if r["seq"] in include and r["action"] == "insert")
        if dep:
            blocked.append("CHECK-DEPENDENCY")
            out["blocked_seqs"] = dep
        if n > out["remaining_today"]:
            blocked.append("RATE-LIMIT")
        out.update({"expected_counts": _predict(rows, include, skipped), "will_apply_rows": n,
                    "decision_deferred": sum(1 for s in lower if rows[s]["action"] == "insert" and rows[s]["original_id"] not in firm),
                    "decision_excluded": sum(1 for v in reasons.values() if v == "decision_excluded")})
    elif pl["state"] == "applied":
        out.update({"expected_counts": _counts(rows, "result")["actions"], "will_apply_rows": 0, "already_applied": True,
                    "decision_deferred": sum(1 for r in rows if r["decision_deferred"]),
                    "decision_excluded": sum(1 for r in rows if r["reason"] == "decision_excluded" and r["result"] == "skipped_reject")})
    else:
        blocked.append("PLAN-STATE")
        out.update({"expected_counts": {}, "will_apply_rows": 0, "decision_deferred": 0, "decision_excluded": 0})
    out["blocked"] = blocked
    return out


def _revert_out(pl, rows, already: bool, restore_until=None) -> dict:
    tg = [r for r in rows if r["result"] == "applied" and r["target_kind"] in ("record", "item")]
    if restore_until is None and already and pl["reverted_at"] is not None:
        restore_until = pl["reverted_at"] + _dt.timedelta(hours=db.TRASH_HOURS)
    trashed = {k: sum(1 for r in tg if r["created"] is True and r["target_kind"] == k) for k in ("record", "item")}
    return {"plan_id": pl["id"], "state": "reverted", "trashed": trashed,
            "kept_source": sum(1 for r in rows if r["target_kind"] == "source" and r["result"] in ("applied", "noop")),
            "kept_updated": sum(1 for r in tg if r["created"] is not True),
            "restore_until": imports._j(restore_until) if any(trashed.values()) else None, "already_reverted": already}


_REVERT_ITEM_CHECKS = (   # 반영 뒤(> applied_at) 항목 변화 — 모든 항목 변경(revision·decision·보관·복원)은 이력 한 줄이다
    "SELECT DISTINCT item_id AS id FROM item_history WHERE user_id=%s AND item_id = ANY(%s) AND at > %s",
    "SELECT DISTINCT target_item_id AS id FROM item_links WHERE user_id=%s AND target_item_id = ANY(%s) AND created_at > %s",
    "SELECT DISTINCT axis_item_id AS id FROM activity_links WHERE user_id=%s AND axis_item_id = ANY(%s) AND created_at > %s")
_REVERT_RECORD_CHECKS = (   # 기록은 revision 이 없다 — 근거 후보 · 가리키거나 나간 연결 · 출처 정정 이력
    "SELECT DISTINCT record_id AS id FROM candidates WHERE user_id=%s AND record_id = ANY(%s)",
    "SELECT DISTINCT target_record_id AS id FROM item_links WHERE user_id=%s AND target_record_id = ANY(%s) AND created_at > %s",
    "SELECT DISTINCT source_record_id AS id FROM item_links WHERE user_id=%s AND source_record_id = ANY(%s) AND created_at > %s",
    "SELECT DISTINCT record_id AS id FROM activity_links WHERE user_id=%s AND record_id = ANY(%s) AND created_at > %s",
    "SELECT DISTINCT linked_record_id AS id FROM activity_links WHERE user_id=%s AND linked_record_id = ANY(%s) AND created_at > %s",
    "SELECT id FROM records WHERE user_id=%s AND id = ANY(%s) AND jsonb_array_length(provenance_history) > 1")


def plan_revert(uid: str, plan_id: str) -> dict:
    """MCP migration_revert(가안 X §5) — 반영한 plan 되돌리기. 한 트랜잭션, 전부 또는 전무(웹 API·버튼 없음):
    a 출처(sources)는 지우지 않는다(kept_source) · b 이 plan 이 새로 만든 대상의 접수(import_entries)는 reverted — 최신·현재 표시를
      직전 판에 돌려준다(같은 판을 다시 stage 하면 insert) · c 반영 뒤 대상(기록·항목) 중 하나라도 바뀌었으면 전체 REVERT-MODIFIED + detail.seqs
      (항목 = 이력(revision·decision 변화 포함)·그 항목을 가리키는 연결 · 기록 = 근거로 든 후보·가리키거나 그 기록에서 나간 연결·출처 정정 이력
      · 공통 = 그 원본의 더 새 판 접수) · d plan state reverted, 두 번째 호출 noop(already_reverted), 일일 한도는 돌려주지 않는다
    · e created=true 대상만 휴지통(168h 복원). 기존 대상 갱신분(created=false · 옛 반영 null)은 그대로(kept_updated — 이전 판은 이력 restore).
    휴지통이 꺼져 있으면 SWITCH-OFF. 반환 {plan_id, state, trashed:{record,item}, kept_source, kept_updated, restore_until, already_reverted}."""
    _sweep(uid)
    gate(uid)
    if not db.trash_on():
        raise db._trash_off()
    with db.tx_scope() as c:
        db._user_lock(c, uid)
        pl = _plan_lock(c, uid, plan_id)
        rows = _items(c, uid, plan_id)
        if pl["state"] == "reverted":
            return _revert_out(pl, rows, True)
        _need_state(pl, "applied")
        at = pl["applied_at"]
        tg = [r for r in rows if r["result"] == "applied" and r["target_kind"] in ("record", "item")]
        seq_of = {(r["target_kind"], r["target_id"]): r["seq"] for r in tg}
        bad = set()
        for kind, checks in (("item", _REVERT_ITEM_CHECKS), ("record", _REVERT_RECORD_CHECKS)):
            ids = [t for k, t in seq_of if k == kind]
            if ids:
                for q in checks:
                    bad |= {seq_of[(kind, x["id"])] for x in _all(c, q, (uid, ids, at)[:q.count("%s")])}
        ents = _all(c, "SELECT id, original_id, target_item_id, target_record_id, previous_entry_id, is_latest_received FROM import_entries "
                       "WHERE user_id=%s AND batch_id=%s AND kind IN ('migration_item','migration_record') AND state='applied' FOR UPDATE",
                    (uid, plan_id))
        oid_seq = {r["original_id"]: r["seq"] for r in tg}
        bad |= {oid_seq[e["original_id"]] for e in ents if not e["is_latest_received"] and e["original_id"] in oid_seq}   # 더 새 판
        if bad:
            raise _err("REVERT-MODIFIED", "반영 뒤 바뀐 대상이 있어 되돌릴 수 없어요(부분 되돌리기는 없어요). 아무것도 바꾸지 않았어요.",
                       "바뀐 대상(seqs)은 그대로 두거나, 필요 없는 것만 하나씩 trash_move 로 지우세요.", seqs=sorted(bad))
        new = {k: [r["target_id"] for r in tg if r["created"] is True and r["target_kind"] == k] for k in ("record", "item")}
        recs = [x["id"] for x in _all(c, "SELECT id FROM records WHERE user_id=%s AND id = ANY(%s) AND deleted_at IS NULL FOR UPDATE",
                                      (uid, new["record"]))] if new["record"] else []
        items = [x["id"] for x in _all(c, "SELECT id FROM items WHERE user_id=%s AND id = ANY(%s) FOR UPDATE", (uid, new["item"]))] \
            if new["item"] else []
        for iid in items:
            db._axis_policy_check(c, uid, iid)
        if recs:
            db._trash_rows(c, uid, "records", recs, "move")
        if items:
            db._trash_rows(c, uid, "items", items, "move")
        gone = set(new["record"]) | set(new["item"])
        for e in ents:
            if (e["target_item_id"] or e["target_record_id"]) not in gone:
                continue
            c.execute("UPDATE import_entries SET state='reverted', is_latest_received=false, is_current_applied=false "
                      "WHERE user_id=%s AND id=%s", (uid, e["id"]))
            if e["previous_entry_id"]:   # 직전 판에 최신·현재 표시를 돌려준다(이 판이 내렸던 것)
                c.execute("UPDATE import_entries SET is_latest_received=true, is_current_applied=(state IN ('applied','noop')) "
                          "WHERE user_id=%s AND id=%s", (uid, e["previous_entry_id"]))
        ru = _one(c, "SELECT max(purge_at) AS t FROM (SELECT purge_at FROM records WHERE user_id=%s AND id = ANY(%s) "
                     "UNION ALL SELECT purge_at FROM items WHERE user_id=%s AND id = ANY(%s)) x", (uid, recs, uid, items))["t"]
        c.execute("UPDATE migration_plans SET state='reverted', reverted_at=now() WHERE user_id=%s AND id=%s", (uid, plan_id))
        db._audit(c, "migration_apply", uid, uid, {"plan": plan_id, "via": "mcp", "result": "reverted",
                                                   "trashed": len(recs) + len(items)})
        pl = _one(c, f"SELECT {_PLAN_COLS} FROM migration_plans WHERE user_id=%s AND id=%s", (uid, plan_id))
        return _revert_out(pl, rows, False, ru)
