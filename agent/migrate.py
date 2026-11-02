"""이관 업로더(board-migration/2) — login · logout · stage · status · cancel · receipt [--verify].

정본: 이관 경로 API 계약(2026-11-02). 토큰 경로(`Authorization: Bearer mig_mt_….…`)만 쓴다.
확인·체크·반영은 웹 세션에서만 한다(토큰으로는 못 한다).

- 토큰은 표준 입력(또는 화면에 안 보이는 입력)으로만 받아 OS 키 저장소에 둔다. 화면·argv·로그에 쓰지 않는다.
- 출력엔 본문을 쓰지 않는다. 항목은 seq·original_id·unit_kind·사유 코드만.
- 해시는 서버와 같은 공식: JCS = json.dumps(sort_keys, separators=(',', ':'), ensure_ascii=False) — agent/jcs.py(UTF-16 키 정렬)와
  다를 수 있어 여기 공식을 쓴다.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

CONTRACT = "board-migration/2"
PLANS_PATH = "/api/migration/plans"
CHUNK_MAX_BYTES = 256 * 1024          # 청크 요청 본문
LINE_MAX_BYTES = 96 * 1024            # 항목 한 줄(JCS)
BODY_MAX_BYTES = 64 * 1024            # 본문(UTF-8)
PLAN_MAX_ITEMS = 200
STAGING_MAX_BYTES = 2 * 1024 * 1024   # 사용자당 스테이징(열린 plan 항목 JCS 합) — 이 plan 만으로 넘는지 미리 본다
MAX_RESPONSE_BYTES = 4 * 1024 * 1024  # 영수증 200항목도 들어간다
OFFSET_RETRIES = 5                    # CHUNK-OFFSET 재개 상한(같은 실행에서)
NETWORK_RETRIES = 2                   # 청크 업로드 중 네트워크 끊김 → 상태 조회 후 재개

OWNER_KEYS = ("owner", "owner_id", "user", "user_id", "target_user_id", "uid", "account", "account_id")
ITEM_UNITS = ("principle_c", "principle_wd", "application_axis", "decision_index", "craft", "open_question", "publication", "axis",
              "application_doc")
RECORD_UNITS = ("record", "journal", "session_story")
SOURCE_UNITS = ("source",)
UNIT_KINDS = ITEM_UNITS + RECORD_UNITS + SOURCE_UNITS
VERIFY_RESULTS = ("applied", "noop")   # stored_hash 를 content_hash 와 대조하는 결과

TOKEN_RE = re.compile(r"^mig_mt_[0-9a-f]{16}\.[A-Za-z0-9_-]{43}$")
PLAN_ID_RE = re.compile(r"^mp_[0-9a-f]{24}$")
ORIGINAL_ID_RE = re.compile(r"^o_[0-9a-f]{32}$")
REVISION_RE = re.compile(r"^v_[0-9a-f]{32}$")
INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_ACCT_UNSAFE = re.compile(r"[^A-Za-z0-9_.:-]")


class InputError(ValueError):
    """입력 JSONL 로컬 검증 실패 — 줄 번호·경로·규칙만(값 없음)."""

    def __init__(self, line: int, path: str, rule: str):
        self.line, self.path, self.rule = line, path, rule
        super().__init__(f"{line}번째 줄 {path}: {rule}")


class ApiError(RuntimeError):
    """서버 오류 응답. 계약 오류 모양 {code, msg, action?, detail?, resume_at?} + retry-after. 토큰·본문 없음."""

    def __init__(self, status, code="", msg="", action="", detail=None, resume_at=None, retry_after=None):
        self.status, self.code, self.msg, self.action = status, code, msg, action
        self.detail = detail if isinstance(detail, dict) else {}
        self.resume_at, self.retry_after = resume_at, retry_after
        super().__init__(f"http-{status} {code}".rstrip())


class NetworkError(RuntimeError):
    pass


# ── 정규화 · 해시 (K4·K5·K9) ───────────────────────────────

def normalize(text: str) -> str:
    """NFC → CRLF 를 LF 로 → 줄마다 끝의 U+0020·U+0009 만 지운다(한 번만). 서버 migration.normalize 와 같은 벡터로 묶는다."""
    t = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    return "\n".join(line.rstrip(" \t") for line in t.split("\n"))


def content_hash(text: str) -> str:
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def content_text(item: dict) -> str:
    """content_hash 대상 — 기록·항목 = body(없으면 ""), 출처 = source.name."""
    if item.get("unit_kind") in SOURCE_UNITS:
        src = item.get("source") if isinstance(item.get("source"), dict) else {}
        name = src.get("name")
        return name if isinstance(name, str) else ""
    body = item.get("body")
    return body if isinstance(body, str) else ""


def jcs(value) -> bytes:
    """계약의 JCS — 실수·NaN 은 입력 단계에서 먼저 거절한다."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def item_sha256(item: dict) -> str:
    return sha256_hex(jcs(item))


def plan_hash_of(item_sha_hexes) -> str:
    """plan_hash = SHA-256(JCS(seq 순 item_sha256 hex 목록))."""
    return sha256_hex(jcs(list(item_sha_hexes)))


def receipt_hash_of(rows) -> str:
    """receipt_hash = SHA-256(JCS(seq 순 [original_id, source_revision, content_hash, result, target_id]))."""
    return sha256_hex(jcs([[r["original_id"], r["source_revision"], r["content_hash"], r["result"], r["target_id"]] for r in rows]))


def recommended_original_id(source_instance: str, source_path: str, anchor: str) -> str:
    """권장 original_id = 'o_' + sha256(source_instance + '\\n' + 원천 경로 + '\\n' + anchor)[:32] — 해시가 아니라 원천 위치(K5)."""
    return "o_" + sha256_hex((source_instance + "\n" + source_path + "\n" + anchor).encode("utf-8"))[:32]


def recommended_source_revision(item: dict) -> str:
    """권장 source_revision = 'v_' + sha256(JCS(항목 − source_revision))[:32]."""
    return "v_" + sha256_hex(jcs({k: v for k, v in item.items() if k != "source_revision"}))[:32]


# ── 입력 JSONL ─────────────────────────────────────────────

class _Reject(ValueError):
    def __init__(self, rule):
        self.rule = rule
        super().__init__(rule)


def _no_dup(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise _Reject("duplicate_key")
        d[k] = v
    return d


def _no_float(_s):
    raise _Reject("float_not_allowed")


def _no_const(_s):
    raise _Reject("nan_not_allowed")


def _strings(v, path="$"):
    if isinstance(v, str):
        yield path, v
    elif isinstance(v, dict):
        for k, x in v.items():
            yield f"{path}.{k}", k
            yield from _strings(x, f"{path}.{k}")
    elif isinstance(v, list):
        for i, x in enumerate(v):
            yield from _strings(x, f"{path}[{i}]")


def parse_line(text: str, line_no: int) -> dict:
    try:
        v = json.loads(text, object_pairs_hook=_no_dup, parse_float=_no_float, parse_constant=_no_const)
    except _Reject as e:
        raise InputError(line_no, "$", e.rule) from None
    except (ValueError, RecursionError):
        raise InputError(line_no, "$", "json") from None
    if not isinstance(v, dict):
        raise InputError(line_no, "$", "object_required")
    return v


def read_items(path: str) -> list:
    """입력 파일 → (줄 번호, 항목) 목록. UTF-8(앞 BOM 하나는 허용) · 한 줄 = JSON 객체 하나 · 빈 줄은 건너뛴다."""
    with open(path, "rb") as f:
        raw = f.read()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(0, "$", "utf8") from None
    if text.startswith("﻿"):
        text = text[1:]
    out = []
    for i, ln in enumerate(text.split("\n"), 1):
        if ln.endswith("\r"):
            ln = ln[:-1]
        if not ln.strip():
            continue
        out.append((i, parse_line(ln, i)))
    return out


def plan_instance(items, flag: str | None) -> str:
    """plan 의 source_instance — 플래그가 있으면 그 값(항목 값과 다르면 거절), 없으면 항목들의 같은 값."""
    seen = set()
    for line_no, it in items:
        si = it.get("source_instance")
        if si is None:
            continue
        if not isinstance(si, str) or not INSTANCE_RE.match(si):
            raise InputError(line_no, "$.source_instance", "format")
        if flag is not None and si != flag:
            raise InputError(line_no, "$.source_instance", "plan_mismatch")
        seen.add(si)
    if flag is not None:
        if not INSTANCE_RE.match(flag):
            raise InputError(0, "--source-instance", "format")
        return flag
    if len(seen) == 1:
        return seen.pop()
    raise InputError(0, "$.source_instance", "missing" if not seen else "plan_mismatch")


def prepare(items, source_instance: str) -> list:
    """로컬 검증 + 빈 값 채움 → 보낼 항목 목록(입력 순서 = seq).

    채우는 것: source_instance(없으면) → content_hash(없으면, 정규화 해시) → source_revision(없으면, 권장 공식).
    있는 content_hash 가 다시 계산한 값과 다르면 거절(서버 seal 에서 content_hash_mismatch 로 거절될 값).
    그 밖 구조(계약 스키마 전체)는 서버가 업로드 때 판정한다(400 CONTRACT-INVALID 경로·규칙)."""
    if not items:
        raise InputError(0, "$", "no_items")
    if len(items) > PLAN_MAX_ITEMS:
        raise InputError(0, "$", f"too_many_items(max {PLAN_MAX_ITEMS})")
    out, seen, total = [], set(), 0
    for line_no, src in items:
        it = dict(src)
        for k in it:
            if k in OWNER_KEYS:
                raise InputError(line_no, f"$.{k}", "owner_field_not_allowed")   # 사용자는 서버가 토큰으로 정한다
        for p, s in _strings(it):
            if "\x00" in s or any(0xD800 <= ord(ch) <= 0xDFFF for ch in s):
                raise InputError(line_no, p, "invalid_char")
        oid = it.get("original_id")
        if not isinstance(oid, str) or not ORIGINAL_ID_RE.match(oid):
            raise InputError(line_no, "$.original_id", "required" if oid is None else "format")
        if oid in seen:
            raise InputError(line_no, "$.original_id", "duplicate_in_plan")
        seen.add(oid)
        if it.get("unit_kind") not in UNIT_KINDS:
            raise InputError(line_no, "$.unit_kind", "enum")
        if "source_instance" not in it:
            it["source_instance"] = source_instance
        body = it.get("body")
        if isinstance(body, str) and len(body.encode("utf-8")) > BODY_MAX_BYTES:
            raise InputError(line_no, "$.body", "too_long_bytes")
        ch = content_hash(content_text(it))
        if "content_hash" not in it:
            it["content_hash"] = ch
        elif it["content_hash"] != ch:
            raise InputError(line_no, "$.content_hash", "content_hash_mismatch")
        if "source_revision" not in it:
            it["source_revision"] = recommended_source_revision(it)
        elif not isinstance(it["source_revision"], str) or not REVISION_RE.match(it["source_revision"]):
            raise InputError(line_no, "$.source_revision", "format")
        line = jcs(it)
        if len(line) > LINE_MAX_BYTES:
            raise InputError(line_no, "$", f"line_too_long_bytes(max {LINE_MAX_BYTES})")
        total += len(line)
        out.append(it)
    if total > STAGING_MAX_BYTES:
        raise InputError(0, "$", f"staging_too_large(max {STAGING_MAX_BYTES})")
    return out


def chunk_end(lines, start: int, max_bytes: int = CHUNK_MAX_BYTES) -> int:
    """lines[start:] 에서 한 청크(줄마다 + '\\n', 합 ≤ max_bytes)에 들어가는 끝 인덱스(제외). 줄 하나는 항상 들어간다(줄 상한 < 청크 상한)."""
    size, end = 0, start
    while end < len(lines) and size + len(lines[end]) + 1 <= max_bytes:
        size += len(lines[end]) + 1
        end += 1
    return max(end, start + 1) if start < len(lines) else start


def chunks(lines, max_bytes: int = CHUNK_MAX_BYTES):
    """처음부터 나눈 청크 경계 [(start, end)] — 시험·요약용."""
    out, i = [], 0
    while i < len(lines):
        j = chunk_end(lines, i, max_bytes)
        out.append((i, j))
        i = j
    return out


# ── HTTP ───────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다 — 토큰이 다른 주소로 가지 않게(uploader 관례)."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, server_url: str, token: str, *, timeout: float = 30, opener=None):
        self.base = server_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(_NoRedirect())

    def __repr__(self):
        return "MigrationClient(<redacted>)"

    def _call(self, method: str, path: str, body: bytes | None = None, ctype: str = "application/json"):
        req = urllib.request.Request(self.base + path, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        req.add_header("Accept", "application/json")
        if body is not None:
            req.add_header("Content-Type", ctype)
        try:
            try:
                resp = self.opener.open(req, timeout=self.timeout)
                status, headers, data = resp.status, resp.headers, resp.read(MAX_RESPONSE_BYTES)
                resp.close()
            except urllib.error.HTTPError as e:
                status, headers = e.code, e.headers
                try:
                    data = e.read(MAX_RESPONSE_BYTES)
                except Exception:
                    data = b""
                e.close()
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            raise NetworkError(type(e).__name__) from None
        try:
            payload = json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        if not 200 <= status < 300:
            ra = headers.get("retry-after") if headers is not None else None
            s = lambda k: payload.get(k) if isinstance(payload.get(k), str) else ""   # noqa: E731
            raise ApiError(status, s("code"), s("msg"), s("action"), payload.get("detail"), s("resume_at") or None, ra)
        return payload

    def create_plan(self, source_instance: str) -> dict:
        return self._call("POST", PLANS_PATH, jcs({"contract": CONTRACT, "source_instance": source_instance}))

    def upload(self, plan_id: str, offset: int, raw: bytes) -> dict:
        return self._call("POST", f"{PLANS_PATH}/{plan_id}/items?offset={int(offset)}", raw, "application/x-ndjson")

    def seal(self, plan_id: str, item_count: int) -> dict:
        return self._call("POST", f"{PLANS_PATH}/{plan_id}/seal", jcs({"item_count": int(item_count)}))

    def status(self, plan_id: str) -> dict:
        return self._call("GET", f"{PLANS_PATH}/{plan_id}")

    def cancel(self, plan_id: str) -> dict:
        return self._call("POST", f"{PLANS_PATH}/{plan_id}/cancel", b"{}")

    def receipt(self, plan_id: str) -> dict:
        return self._call("GET", f"{PLANS_PATH}/{plan_id}/receipt")


def upload_all(client: Client, plan_id: str, lines, say=lambda m: None) -> int:
    """청크 업로드 — 서버가 받은 항목 수(offset)부터 이어 보낸다. 409 CHUNK-OFFSET 이면 detail.received 부터,
    네트워크가 끊기면 상태를 조회해 그 item_count 부터 다시 보낸다. 반환 = 서버가 받은 항목 수."""
    pos, offset_retries, net_retries = 0, 0, 0
    n = len(lines)
    while pos < n:
        end = chunk_end(lines, pos)
        raw = b"".join(ln + b"\n" for ln in lines[pos:end])
        try:
            r = client.upload(plan_id, pos, raw)
        except ApiError as e:
            if e.status == 409 and e.code == "CHUNK-OFFSET" and isinstance(e.detail.get("received"), int) \
                    and not isinstance(e.detail.get("received"), bool) and 0 <= e.detail["received"] <= n \
                    and offset_retries < OFFSET_RETRIES:
                offset_retries += 1
                say(f"  서버가 받은 항목 수 {e.detail['received']} — 거기서부터 이어 보냅니다.")
                pos = e.detail["received"]
                continue
            raise
        except NetworkError:
            if net_retries >= NETWORK_RETRIES:
                raise
            net_retries += 1
            got = client.status(plan_id).get("item_count")
            if not isinstance(got, int) or isinstance(got, bool) or not 0 <= got <= n:
                raise
            say(f"  연결이 끊겨 상태를 다시 봤어요 — 받은 항목 {got}부터 이어 보냅니다.")
            pos = got
            continue
        got = r.get("received")
        if not isinstance(got, int) or isinstance(got, bool) or not pos < got <= n:
            raise ApiError(200, "UNEXPECTED", "서버가 받은 항목 수가 이상해요.")
        pos = got
    return pos


# ── 요약 · 대조 ─────────────────────────────────────────────

def reason_counts(items, actions=("reject", "warn", "conflict")) -> dict:
    """{action: {reason: n}} — 본문 없이 사유 코드만."""
    out = {}
    for it in items or []:
        a = it.get("action")
        if a in actions:
            r = it.get("reason") or "-"
            out.setdefault(a, {})[r] = out.setdefault(a, {}).get(r, 0) + 1
    return out


def verify(receipt: dict, items) -> dict:
    """영수증 ↔ 입력 항목 대조. 반환 {"ok", "problems": [(seq, original_id, 사유)], "receipt_hash_ok", "plan_hash_ok", "units"}.

    - 항목 수·original_id 집합 · source_revision · content_hash 일치
    - result ∈ {applied, noop} 이면 stored_hash == content_hash(null = 휴지통·없음 → 불일치)
    - 자료군(unit_kind)별 개수: 입력 = 영수증 항목 = 영수증 counts.units 합
    - receipt_hash: 입력의 (original_id, source_revision, content_hash) + 영수증의 (result, target_id) 로 다시 계산
    - plan_hash: 입력 항목 JCS 해시 목록으로 다시 계산(같은 바이트를 올렸는지)"""
    problems = []
    rows = sorted([x for x in receipt.get("items") or [] if isinstance(x, dict)], key=lambda x: x.get("seq", 0))
    by_oid = {}
    for x in rows:
        by_oid.setdefault(x.get("original_id"), x)
    mine = {it["original_id"]: (seq, it) for seq, it in enumerate(items)}
    for oid, (seq, it) in mine.items():
        x = by_oid.get(oid)
        if x is None:
            problems.append((seq, oid, "missing_in_receipt"))
            continue
        if x.get("seq") != seq:
            problems.append((seq, oid, "seq_mismatch"))
        if x.get("source_revision") != it["source_revision"]:
            problems.append((seq, oid, "source_revision_mismatch"))
        if x.get("content_hash") != it["content_hash"]:
            problems.append((seq, oid, "content_hash_mismatch"))
        if x.get("unit_kind") != it.get("unit_kind"):
            problems.append((seq, oid, "unit_kind_mismatch"))
        if x.get("result") in VERIFY_RESULTS and x.get("stored_hash") != it["content_hash"]:
            why = "stored_hash_mismatch" if x.get("stored_hash") else f"stored_{x.get('target_state') or 'missing'}"
            problems.append((seq, oid, why))
    for x in rows:
        if x.get("original_id") not in mine:
            problems.append((x.get("seq"), x.get("original_id"), "extra_in_receipt"))
    if len(rows) != len(items) and not any(p[2] in ("missing_in_receipt", "extra_in_receipt") for p in problems):
        problems.append((None, None, "item_count_mismatch"))
    # 자료군별 개수
    want, got_rows, got_counts = {}, {}, {}
    for it in items:
        want[it["unit_kind"]] = want.get(it["unit_kind"], 0) + 1
    for x in rows:
        got_rows[x.get("unit_kind")] = got_rows.get(x.get("unit_kind"), 0) + 1
    units = ((receipt.get("counts") or {}).get("units") or {})
    for u, res in units.items():
        got_counts[u] = sum(v for v in (res or {}).values() if isinstance(v, int))
    for u in sorted(set(want) | set(got_rows) | set(got_counts), key=str):
        if not (want.get(u, 0) == got_rows.get(u, 0) == got_counts.get(u, 0)):
            problems.append((None, None, f"unit_count_mismatch:{u}"))
    # receipt_hash · plan_hash
    rh_ok = False
    if len(rows) == len(items):
        try:
            recomputed = receipt_hash_of([{"original_id": it["original_id"], "source_revision": it["source_revision"],
                                           "content_hash": it["content_hash"], "result": x.get("result"),
                                           "target_id": x.get("target_id")} for it, x in zip(items, rows)])
            rh_ok = recomputed == receipt.get("receipt_hash")
        except (TypeError, ValueError):
            rh_ok = False
    if not rh_ok:
        problems.append((None, None, "receipt_hash_mismatch"))
    ph_ok = plan_hash_of(item_sha256(it) for it in items) == receipt.get("plan_hash")
    if not ph_ok:
        problems.append((None, None, "plan_hash_mismatch"))
    return {"ok": not problems, "problems": problems, "receipt_hash_ok": rh_ok, "plan_hash_ok": ph_ok, "units": want}


# ── 키 저장소 계정 ──────────────────────────────────────────

def token_account(server_url: str) -> str:
    """키 저장소 계정 이름 — 'migration-token:<host[:port]>'(연결 장치 토큰·HMAC 키 계정과 겹치지 않는다)."""
    p = urllib.parse.urlsplit(server_url)
    host = (p.hostname or "").lower()
    if p.port:
        host += f":{p.port}"
    return ("migration-token:" + _ACCT_UNSAFE.sub("_", host))[:128]


# ── 명령 (cli.py `migrate` 가 부른다) ────────────────────────

EXIT_OK, EXIT_ERR, EXIT_USAGE = 0, 1, 2
MAX_PROBLEM_LINES = 50

_HINTS = {
    "AUTH-INVALID": "웹에서 이관 토큰을 새로 발급해 `migrate login` 으로 다시 넣으세요.",
    "TOKEN-EXPIRED": "토큰이 만료됐어요(발급 뒤 14일). 웹에서 새로 발급해 `migrate login` 으로 다시 넣으세요.",
    "TOKEN-REVOKED": "폐기된 토큰이에요. 웹에서 새로 발급해 `migrate login` 으로 다시 넣으세요.",
    "AUTH-BLOCKED": "이 계정은 지금 쓸 수 없어요. 운영자에게 문의하세요.",
    "MIGRATION-OFF": "서버의 이관 스위치가 꺼져 있어요. 운영자가 켠 뒤 다시 실행하세요.",
    "MIGRATION-NOT-ALLOWED": "이 계정은 이관 허용 목록에 없어요. 운영자에게 문의하세요.",
    "PLAN-EXPIRED": "plan 이 만료됐어요(만든 뒤 3일). 본문은 서버에서 지워졌어요 — 다시 stage 하세요.",
    "PLAN-LIMIT": "열린 plan 이 3개예요. 웹에서 반영하거나 `migrate cancel` 로 취소한 뒤 다시 하세요.",
    "STAGING-FULL": "스테이징 공간(사용자당 2MB)이 찼어요. 열린 plan 을 반영하거나 취소하세요.",
    "NOT-FOUND": "그런 plan 이 없어요(이 토큰의 계정 것이 아니어도 이렇게 보여요).",
    "QUOTA-GLOBAL": "서버 전체 저장 공간이 찼어요. 운영자에게 문의하세요.",
}


def explain(e) -> list:
    """서버 오류 → 사람이 읽는 줄들(토큰·본문 없음). 429 는 기다릴 시간만 알려 주고 자동으로 다시 하지 않는다."""
    if isinstance(e, NetworkError):
        return ["서버에 닿지 못했어요(네트워크·시간 초과). 주소·네트워크를 확인하고 다시 실행하세요."]
    head = f"서버 오류 http-{e.status}" + (f" {e.code}" if e.code else "") + (f": {e.msg}" if e.msg else "")
    out = [head]
    if e.action:
        out.append("  " + e.action)
    if e.code == "PLAN-STATE" and e.detail.get("state"):
        out.append(f"  지금 상태: {e.detail['state']}")
    if e.code in ("CHUNK-OFFSET", "PLAN-COUNT-MISMATCH") and "received" in e.detail:
        out.append(f"  서버가 받은 항목 수: {e.detail['received']}")
    if e.status == 429:
        wait = str(e.retry_after).strip() if e.retry_after else ""
        out.append(("  " + wait + "초 뒤에 다시 실행하세요." if wait.isdigit() else "  잠시 뒤 다시 실행하세요.")
                   + " 자동으로 기다리며 다시 보내지 않아요.")
        if e.resume_at:
            out.append(f"  다시 할 수 있는 시각: {e.resume_at}")
    hint = _HINTS.get(e.code)
    if hint:
        out.append("  " + hint)
    return out


def _server(ctx, a):
    from . import config as _config
    try:
        return _config.check_server_url(a.server)
    except _config.ConfigError:
        ctx.say("서버 주소는 https(로컬 시험만 http://127.0.0.1·localhost)이고 경로·쿼리 없이 적어요.")
        return None


def _keystore(ctx):
    from . import config as _config
    try:
        cfg = _config.load(ctx.paths)
    except _config.ConfigError:
        cfg = {}
    return ctx.keystore(cfg)


def _token(ctx, server):
    from . import keystore
    try:
        tok = _keystore(ctx).get(token_account(server))
    except keystore.KeyStoreError as e:
        ctx.say(f"자격 증명 저장소 접근 불가: {e}")
        return None
    if not tok:
        ctx.say("이 서버의 이관 토큰이 없어요. 먼저 `python3 -m agent migrate login --server <주소> --token-stdin` 으로 넣으세요.")
        return None
    return tok


def _client(ctx, server, token):
    factory = getattr(ctx, "migrate_client_factory", None) or Client
    return factory(server, token, timeout=30)


def _plan_id(ctx, pid):
    if not PLAN_ID_RE.match(pid or ""):
        ctx.say("plan_id 형식이 맞지 않아요(mp_ + 24자리 hex).")
        return False
    return True


def _fmt_counts(d) -> str:
    return " · ".join(f"{k} {v}" for k, v in sorted((d or {}).items())) or "없음"


def say_plan(ctx, pl: dict, local_plan_hash: str | None = None) -> None:
    """plan 요약 — 본문 없이 상태·개수·사유 코드만."""
    ctx.say(f"  plan_id: {pl.get('plan_id')} · 상태 {pl.get('state')} · 항목 {pl.get('item_count')} · "
            f"스테이징 {pl.get('staged_bytes')} 바이트")
    if pl.get("plan_hash"):
        tail = ""
        if local_plan_hash is not None:
            tail = " (로컬 계산과 일치)" if local_plan_hash == pl["plan_hash"] else " (로컬 계산과 다름!)"
        ctx.say(f"  plan_hash: {pl['plan_hash']}{tail}")
    for k, label in (("created_at", "만든 시각"), ("expires_at", "만료"), ("sealed_at", "seal"), ("applied_at", "반영"),
                     ("closed_at", "닫힘")):
        if pl.get(k):
            ctx.say(f"  {label}: {pl[k]}")
    counts = pl.get("counts") or {}
    if counts.get("actions"):
        ctx.say(f"  action: {_fmt_counts(counts['actions'])}")
        for u, acts in sorted((counts.get("units") or {}).items()):
            ctx.say(f"    {u}: {_fmt_counts(acts)}")
    for act, reasons in sorted(reason_counts(pl.get("items")).items()):
        ctx.say(f"  {act} 사유: {_fmt_counts(reasons)}")


def cmd_login(ctx, a) -> int:
    from . import keystore
    server = _server(ctx, a)
    if not server:
        return EXIT_USAGE
    if a.token_stdin:
        token = ctx.stdin.readline().strip()
    else:
        token = ctx.getpass_fn("이관 토큰(화면에 안 보임): ").strip()
    if not TOKEN_RE.match(token):
        ctx.say("이관 토큰 형식이 맞지 않아요(mig_mt_…). 웹 이관 화면에서 받은 토큰을 그대로 넣으세요.")
        return EXIT_USAGE
    acct = token_account(server)
    try:
        _keystore(ctx).set(acct, token)
    except keystore.KeyStoreError as e:
        ctx.say(f"자격 증명 저장소에 쓰지 못했어요: {e}. 평문으로 저장하지 않고 멈춥니다.")
        return EXIT_ERR
    ctx.say("이관 토큰을 키 저장소에 넣었어요(표시 안 함).")
    ctx.say(f"  서버: {server}")
    ctx.say(f"  계정: {acct}")
    ctx.say("  토큰은 발급 뒤 14일에 만료돼요. 서버 확인은 stage 때 합니다.")
    return EXIT_OK


def cmd_logout(ctx, a) -> int:
    from . import keystore
    server = _server(ctx, a)
    if not server:
        return EXIT_USAGE
    try:
        removed = _keystore(ctx).delete(token_account(server))
    except keystore.KeyStoreError as e:
        ctx.say(f"자격 증명 저장소 접근 불가: {e}")
        return EXIT_ERR
    ctx.say("로컬 이관 토큰: " + ("지웠어요" if removed else "없었어요"))
    ctx.say("서버 쪽 토큰은 웹 이관 화면에서 폐기하세요(그대로 두면 14일 뒤 만료).")
    return EXIT_OK


def _load(ctx, path, flag_instance):
    """입력 → (source_instance, 보낼 항목). 실패면 None(메시지 출력)."""
    try:
        raw = read_items(path)
        si = plan_instance(raw, flag_instance)
        return si, prepare(raw, si)
    except FileNotFoundError:
        ctx.say("입력 파일이 없어요.")
    except OSError as e:
        ctx.say(f"입력 파일을 읽지 못했어요: {type(e).__name__}")
    except InputError as e:
        where = f"{e.line}번째 줄 " if e.line else ""
        ctx.say(f"입력 검증 실패: {where}{e.path}: {e.rule}")
        if e.path == "$.source_instance" and e.rule == "missing":
            ctx.say("  항목에 source_instance 가 없으면 --source-instance 로 정하세요.")
    return None


def cmd_stage(ctx, a) -> int:
    server = _server(ctx, a)
    if not server:
        return EXIT_USAGE
    loaded = _load(ctx, a.items, a.source_instance)
    if loaded is None:
        return EXIT_ERR
    si, items = loaded
    lines = [jcs(it) for it in items]
    local_ph = plan_hash_of(sha256_hex(ln) for ln in lines)
    units = {}
    for it in items:
        units[it["unit_kind"]] = units.get(it["unit_kind"], 0) + 1
    ctx.say(f"입력 {len(items)}항목 — 로컬 검증 통과(정규화·해시·한도). 자료군: {_fmt_counts(units)}")
    ctx.say(f"  source_instance: {si} · 청크 {len(chunks(lines))}개(≤{CHUNK_MAX_BYTES} 바이트)")
    token = _token(ctx, server)
    if not token:
        return EXIT_ERR
    cl = _client(ctx, server, token)
    pid = None
    try:
        pl = cl.create_plan(si)
        pid = pl.get("plan_id")
        if not isinstance(pid, str) or not PLAN_ID_RE.match(pid):
            ctx.say("서버 응답에 plan_id 가 없어요.")
            return EXIT_ERR
        ctx.say(f"plan 만듦: {pid} (만료 {pl.get('expires_at')})")
        got = upload_all(cl, pid, lines, ctx.say)
        ctx.say(f"업로드 완료 — 서버가 받은 항목 {got}")
        pl = cl.seal(pid, len(lines))
    except (ApiError, NetworkError) as e:
        for ln in explain(e):
            ctx.say(ln)
        if pid:
            ctx.say(f"plan {pid} 은 열린 채로 남았어요. 상태: `migrate status {pid}` · 취소: `migrate cancel {pid}`.")
        return EXIT_ERR
    ctx.say("seal 완료 — dry-run 결과(아직 반영 안 함):")
    say_plan(ctx, pl, local_ph)
    if pl.get("plan_hash") != local_ph:
        ctx.say("plan_hash 가 로컬 계산과 달라요. 반영하지 말고 `migrate cancel` 로 취소한 뒤 원인을 확인하세요.")
        return EXIT_ERR
    ctx.say(f"plan_id: {pid}")
    ctx.say(f"다음: 웹({server})의 이관 화면에서 이 plan 의 항목을 확인하고 반영하세요(기준 항목은 하나씩 체크).")
    ctx.say(f"반영 뒤 대조: python3 -m agent migrate receipt {pid} --server {server} --verify <같은 입력 파일>")
    return EXIT_OK


def cmd_status(ctx, a) -> int:
    server = _server(ctx, a)
    if not server or not _plan_id(ctx, a.plan_id):
        return EXIT_USAGE
    token = _token(ctx, server)
    if not token:
        return EXIT_ERR
    try:
        pl = _client(ctx, server, token).status(a.plan_id)
    except (ApiError, NetworkError) as e:
        for ln in explain(e):
            ctx.say(ln)
        return EXIT_ERR
    ctx.say("plan 상태:")
    say_plan(ctx, pl)
    return EXIT_OK


def cmd_cancel(ctx, a) -> int:
    server = _server(ctx, a)
    if not server or not _plan_id(ctx, a.plan_id):
        return EXIT_USAGE
    token = _token(ctx, server)
    if not token:
        return EXIT_ERR
    try:
        pl = _client(ctx, server, token).cancel(a.plan_id)
    except (ApiError, NetworkError) as e:
        for ln in explain(e):
            ctx.say(ln)
        return EXIT_ERR
    ctx.say(f"plan {a.plan_id}: 상태 {pl.get('state')} — 서버의 스테이징 본문은 지워졌어요.")
    return EXIT_OK


def cmd_receipt(ctx, a) -> int:
    server = _server(ctx, a)
    if not server or not _plan_id(ctx, a.plan_id):
        return EXIT_USAGE
    token = _token(ctx, server)
    if not token:
        return EXIT_ERR
    cl = _client(ctx, server, token)
    try:
        rc = cl.receipt(a.plan_id)
        pl = cl.status(a.plan_id) if a.verify else None
    except (ApiError, NetworkError) as e:
        for ln in explain(e):
            ctx.say(ln)
        return EXIT_ERR
    counts = rc.get("counts") or {}
    ctx.say(f"영수증: plan {rc.get('plan_id')} · 반영 {rc.get('applied_at')} · 항목 {len(rc.get('items') or [])}")
    ctx.say(f"  import_batch_id: {rc.get('import_batch_id')}")
    ctx.say(f"  receipt_hash: {rc.get('receipt_hash')}")
    ctx.say(f"  result: {_fmt_counts(counts.get('results'))}")
    for u, res in sorted((counts.get("units") or {}).items()):
        ctx.say(f"    {u}: {_fmt_counts(res)}")
    if not a.verify:
        return EXIT_OK
    si = pl.get("source_instance") if isinstance(pl, dict) else None
    if not isinstance(si, str):
        ctx.say("plan 의 source_instance 를 받지 못했어요.")
        return EXIT_ERR
    loaded = _load(ctx, a.verify, si)
    if loaded is None:
        return EXIT_ERR
    _si, items = loaded
    res = verify(rc, items)
    ctx.say(f"대조(--verify): 입력 {len(items)}항목 · 자료군 {_fmt_counts(res['units'])}")
    ctx.say("  receipt_hash 재계산: " + ("일치" if res["receipt_hash_ok"] else "불일치"))
    ctx.say("  plan_hash 재계산: " + ("일치" if res["plan_hash_ok"] else "불일치"))
    if res["ok"]:
        ctx.say("  결과: 일치 — original_id·source_revision·content_hash·저장 해시(applied·noop)·자료군별 개수.")
        return EXIT_OK
    ctx.say(f"  결과: 불일치 {len(res['problems'])}건")
    for seq, oid, why in res["problems"][:MAX_PROBLEM_LINES]:
        ctx.say("    " + (f"seq={seq} " if seq is not None else "") + (f"original_id={oid} " if oid else "") + why)
    if len(res["problems"]) > MAX_PROBLEM_LINES:
        ctx.say(f"    … 외 {len(res['problems']) - MAX_PROBLEM_LINES}건")
    return EXIT_ERR


COMMANDS = {"login": cmd_login, "logout": cmd_logout, "stage": cmd_stage, "status": cmd_status, "cancel": cmd_cancel,
            "receipt": cmd_receipt}


def run(ctx, a) -> int:
    if not getattr(a, "mcmd", None):
        ctx.say("쓰는 법: python3 -m agent migrate {login|logout|stage|status|cancel|receipt} --server <주소> …")
        return EXIT_USAGE
    return COMMANDS[a.mcmd](ctx, a)
