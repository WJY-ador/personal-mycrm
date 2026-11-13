"""전송 대기 파일 → POST /api/imports. 재시도 규칙:

- 항상 저장해 둔 바이트와 멱등 키를 그대로 다시 보낸다(요청을 다시 만들지 않는다, 모델 재실행 없음).
- 200/201            → accepted(대기 파일 삭제)
- 200 + 삭제 상태(201 이어도 같게) → accepted + server_state 'deleted'(휴지통) | 'purged'(source_deleted=purged,
  영구 삭제 표식). 그 개정은
  재시도·재전송 없음. 내용이 바뀐 새 개정은 이 판 뒤로 보낸다(서버가 복원했으면 받는다). 서버 ID 는 저장하지 않는다.
  이전 서버(삭제 상태 없음)는 위 줄 그대로
- 409 IDEMPOTENCY-CONFLICT·KIND-CHANGED → conflict + 격리(같은 키에 다른 본문 / 원본 종류 변경)
- 409 SOURCE-REVISION-CONFLICT·기타 409 → halted(그 원본만 멈춤, 사용자 확인 필요)
- 400/413/415/422 · 403 POLICY-DENIED → rejected + 격리(계약·장치 정책 불일치)
- 401 · 403 AUTH-BLOCKED · 409 DEVICE-REVOKED → 전체 멈춤(auth)
- 403 STREAM-MISMATCH → 전체 멈춤(config) · 403 NAME-REQUIRED → (account) · 409 POLICY-STALE → (policy)
  · 그 밖의 403 → (forbidden). 멈춤은 사용자 조치 뒤 `run-once --resume <범위>` 로 푼다
- 429 IMPORT-QUOTA·PEOPLE-QUOTA → 본문 resume_at(없거나 이상하면 다음 KST 0시) · INBOX-FULL → 1시간 · 그 밖(RATE-LIMIT) → Retry-After(없으면 60초). 이번 실행 중단
- 503 OBJECT-MISSING(수집 글 오브젝트 collected_posts 없음) → 그 개정만 대기 유지·지수 대기. 이번 실행의 남은 수집 글은
  미루고 다른 전송은 계속한다(사용자가 오브젝트를 만들면 다음 실행부터 이어진다)
- 5xx(*-OFF 스위치 꺼짐 포함)·네트워크·시간 초과 → 대기 유지, 지수 대기(최대 1시간). 이번 실행 중단
로그·오류 메시지엔 상태 코드·규칙 코드만 남긴다(본문·토큰 없음).
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import re
import secrets
import time
import urllib.parse
import urllib.error
import urllib.request

from . import osutil
from . import store as _store

IMPORTS_PATH = "/api/imports"
DEVICE_PATH = "/api/imports/device"
DEVICE_REVOKE_PATH = "/api/imports/device/revoke"
DEVICE_ROTATE_PATH = "/api/device/rotate"   # Bearer 교체(PC 연결 계획 §4). M2: 옛 토큰은 새 토큰 첫 사용 때 무효
# 웹 판별 목록(오늘 탭 수집 인박스 명세 2026-11-13 2절 장치 API). 업로드 토큰 GET ?since=<커서>
# → {"decisions": [{"item_id", "state", "decided_at"}], "next_cursor"}. 경로는 이 상수 한 곳에서만 바꾼다
DECISIONS_PATH = "/api/imports/decisions"
DECISIONS_MAX_BYTES = 1024 * 1024   # 한 쪽 응답 상한. 넘으면 형식 오류로 보고 커서를 옮기지 않는다
# 서버 server/imports.py _HTTP 표 기준
DAILY_LIMIT_CODES = ("IMPORT-QUOTA", "PEOPLE-QUOTA")   # 본문 resume_at(다음 KST 0시) 이 있으면 그 시각
AUTH_CODES = ("AUTH-INVALID", "TOKEN-EXPIRED", "TOKEN-REVOKED", "AUTH-BLOCKED", "DEVICE-REVOKED")
GLOBAL_HALT_CODES = {"STREAM-MISMATCH": "config", "NAME-REQUIRED": "account", "POLICY-STALE": "policy"}
CONFLICT_CODES = ("IDEMPOTENCY-CONFLICT", "KIND-CHANGED")
UPLOAD_HALT_SCOPES = ("auth", "config", "account", "policy", "forbidden")
OBJECT_MISSING = "OBJECT-MISSING"      # 서버 imports._HTTP 503 — 수집 글을 담을 오브젝트가 없다
REJECT_STATUSES = (400, 413, 415, 422)
MAX_RESPONSE_BYTES = 64 * 1024
DELETED_STATE = "deleted"   # 서버 200 응답의 state — 그 원본이 휴지통·영구 삭제 상태라 이 개정을 받지 않았다


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리다이렉트를 따라가지 않는다 — 토큰이 다른 주소로 가지 않게."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    return urllib.request.build_opener(_NoRedirect())


def _parse_iso(s):
    try:
        return _dt.datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def next_kst_midnight(now: _dt.datetime) -> _dt.datetime:
    n = now.astimezone(osutil.KST)
    return (n + _dt.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


def resume_at_or_midnight(payload: dict, now: _dt.datetime) -> _dt.datetime:
    """서버 resume_at(오프셋 있는 ISO) 을 쓰되, 과거·48시간 넘는 미래·형식 오류면 다음 KST 0시."""
    ra = _parse_iso(payload.get("resume_at")) if isinstance(payload.get("resume_at"), str) else None
    if ra is not None and ra.tzinfo is not None and now < ra <= now + _dt.timedelta(hours=48):
        return ra
    return next_kst_midnight(now)


class DeviceError(RuntimeError):
    """장치 경로 실패. status·code 만 담는다(토큰·본문 없음)."""

    def __init__(self, kind: str, status: int | None = None, code: str = ""):
        self.kind, self.status, self.code = kind, status, code
        super().__init__(f"{kind}" + (f" http-{status}" if status else "") + (f" {code}" if code else ""))


class Uploader:
    def __init__(self, server_url: str, token: str, *, timeout: float = 30, opener=None,
                 sleep=time.sleep, now=osutil.kst_now):
        self.base = server_url.rstrip("/")
        self.url = self.base + IMPORTS_PATH
        self._token = token
        self.timeout = timeout
        self.opener = opener or _opener()
        self.sleep = sleep
        self.now = now

    def __repr__(self):
        return "Uploader(<redacted>)"

    def post(self, idem_key: str, body: bytes):
        return self._request("POST", self.url, body, {"Idempotency-Key": idem_key,
                                                      "Content-Type": "application/json"})

    def _request(self, method: str, url: str, body: bytes | None, extra: dict, max_bytes: int = MAX_RESPONSE_BYTES):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self._token)
        req.add_header("Accept", "application/json")
        for k, v in extra.items():
            req.add_header(k, v)
        try:
            resp = self.opener.open(req, timeout=self.timeout)
            status, headers, data = resp.status, resp.headers, resp.read(max_bytes + 1)
            resp.close()
        except urllib.error.HTTPError as e:
            status, headers = e.code, e.headers
            try:
                data = e.read(MAX_RESPONSE_BYTES)
            except Exception:
                data = b""
            e.close()
        if len(data) > max_bytes:
            data = b""      # 상한을 넘은 본문은 읽지 않는다(잘린 JSON 을 쓰지 않는다)
        try:
            payload = json.loads(data.decode("utf-8")) if data else {}
        except (UnicodeDecodeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        return status, headers, payload

    def _device_call(self, method: str, path: str) -> dict:
        try:
            status, _h, payload = self._request(method, self.base + path, b"" if method == "POST" else None, {})
        except (urllib.error.URLError, OSError, TimeoutError):
            raise DeviceError("network") from None
        if status != 200:
            code = payload.get("code") if isinstance(payload.get("code"), str) else ""
            raise DeviceError("auth" if status == 401 else "server", status, code)
        return payload

    def device(self) -> dict:
        """GET /api/imports/device → {stream_id, label, policy, policy_revision, hmac_namespace, token_expires_at}"""
        return self._device_call("GET", DEVICE_PATH)

    def revoke(self) -> dict:
        """POST /api/imports/device/revoke → {stream_id, revoked: true}. 이후 이 토큰은 401 TOKEN-REVOKED."""
        return self._device_call("POST", DEVICE_REVOKE_PATH)

    def rotate(self) -> dict:
        """POST /api/device/rotate → {stream_id, token, token_expires_at}. 새 토큰은 응답에만 한 번 온다.
        옛 토큰은 새 토큰이 처음 쓰일 때 무효(M2) — 그 전까지 옛 토큰으로 계속 보낼 수 있다."""
        return self._device_call("POST", DEVICE_ROTATE_PATH)

    def decisions(self, since: str | None) -> dict:
        """GET 판별 목록 한 쪽. 200 이고 decisions 가 목록일 때만 응답을 돌려준다. 그 밖은 DeviceError(값 없음)."""
        url = self.base + DECISIONS_PATH
        if since:
            url += "?" + urllib.parse.urlencode({"since": since})
        try:
            status, _h, payload = self._request("GET", url, None, {}, max_bytes=DECISIONS_MAX_BYTES)
        except (urllib.error.URLError, OSError, TimeoutError):
            raise DeviceError("network") from None
        if status != 200:
            code = payload.get("code") if isinstance(payload.get("code"), str) else ""
            raise DeviceError("auth" if status == 401 else "server", status, code)
        if not isinstance(payload.get("decisions"), list):
            raise DeviceError("malformed", status)
        return payload

    def run(self, store, *, max_n: int = 100, min_interval: float = 0.0) -> dict:
        out = {"sent": 0, "accepted": 0, "duplicate": 0, "deleted": 0, "conflict": 0, "halted": 0, "rejected": 0,
               "deferred": 0, "stopped": None}
        for scope in UPLOAD_HALT_SCOPES:
            if store.halted(scope):
                out["stopped"] = scope + "-halted"
                return out
        now = self.now()
        first = True
        skip_collected = False
        for rev in store.pending_revisions():
            if out["sent"] >= max_n:
                out["stopped"] = "max-per-run"
                break
            nxt = _parse_iso(rev["next_attempt_at"]) if rev["next_attempt_at"] else None
            if nxt is not None and nxt > now:
                out["deferred"] += 1
                continue
            # 같은 원본의 앞 개정이 아직 열려 있으면 뒤 개정을 보내지 않는다(부모 순서 유지)
            earlier = store.conn.execute(
                "SELECT 1 FROM revisions WHERE original_id=? AND seq<? AND status IN ('pending','halted') LIMIT 1",
                (rev["original_id"], rev["seq"])).fetchone()
            if earlier:
                out["deferred"] += 1
                continue
            if not first and min_interval > 0:
                self.sleep(min_interval)
            first = False
            key = rev["idempotency_key"]
            body = store.read_pending(rev)
            if skip_collected and _kind_of(body) == "collected_post":
                out["deferred"] += 1
                continue
            out["sent"] += 1
            try:
                status, headers, payload = self.post(key, body)
            except (urllib.error.URLError, OSError, TimeoutError):
                self._backoff(store, rev, "network")
                out["stopped"] = "network"
                break
            code = payload.get("code") if isinstance(payload.get("code"), str) else ""
            if status in (200, 201) and payload.get("state") == DELETED_STATE:
                # 삭제된 원본 — 끝난 전송으로 두고 이번 실행의 다른 전송은 계속. 서버 ID 는 활성 대상이 아니라 남기지 않는다
                purged = payload.get("source_deleted") == "purged"
                store.mark(key, "accepted", result={"state": _store.SERVER_PURGED if purged else _store.SERVER_DELETED})
                out["deleted"] += 1
            elif status in (200, 201):
                store.mark(key, "accepted", result=payload)
                out["accepted"] += 1
                if status == 200 or payload.get("duplicate") is True:
                    out["duplicate"] += 1
            elif status == 401 or code in AUTH_CODES:
                store.halt("auth", f"http-{status}")
                store.bump_attempt(key, f"http-{status}", None)
                out["stopped"] = "auth"
                break
            elif code in GLOBAL_HALT_CODES:
                store.halt(GLOBAL_HALT_CODES[code], code)
                store.bump_attempt(key, f"http-{status}:{code}", None)
                out["stopped"] = GLOBAL_HALT_CODES[code]
                break
            elif status == 409 and code in CONFLICT_CODES:
                store.mark(key, "conflict", error=code)
                store.quarantine("upload", code.lower(), key)
                out["conflict"] += 1
            elif status == 409:
                store.mark(key, "halted", error=code or "http-409")
                out["halted"] += 1
            elif status == 403 and code == "POLICY-DENIED":
                store.mark(key, "rejected", error=code)
                store.quarantine("upload", "policy-denied", key)
                out["rejected"] += 1
            elif status == 403:
                store.halt("forbidden", code or "http-403")
                store.bump_attempt(key, f"http-403:{code}" if code else "http-403", None)
                out["stopped"] = "forbidden"
                break
            elif status == 429:
                if code in DAILY_LIMIT_CODES:
                    at = resume_at_or_midnight(payload, self.now())
                elif code == "INBOX-FULL":
                    at = self.now() + _dt.timedelta(hours=1)
                else:
                    ra = headers.get("Retry-After") if headers is not None else None
                    sec = int(ra) if ra and str(ra).isdigit() else 60
                    at = self.now() + _dt.timedelta(seconds=min(sec, 3600))
                store.bump_attempt(key, f"http-429:{code}" if code else "http-429", at.isoformat(timespec="seconds"))
                out["stopped"] = "rate-limit"
                break
            elif status in REJECT_STATUSES:
                store.mark(key, "rejected", error=f"http-{status}:{code}" if code else f"http-{status}")
                store.quarantine("upload", f"rejected-{status}", key)
                out["rejected"] += 1
            elif code == OBJECT_MISSING:
                self._backoff(store, rev, f"http-{status}:{code}")
                skip_collected = True
                out["deferred"] += 1
            else:
                self._backoff(store, rev, f"http-{status}")
                out["stopped"] = "server"
                break
        return out

    def _backoff(self, store, rev, err: str) -> None:
        n = (rev["attempts"] or 0) + 1
        wait = min(60 * (2 ** min(n, 6)), 3600)
        at = self.now() + _dt.timedelta(seconds=wait)
        store.bump_attempt(rev["idempotency_key"], err, at.isoformat(timespec="seconds"))


def _kind_of(body) -> str:
    try:
        obj = json.loads(bytes(body).decode("utf-8"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return ""
    return obj.get("kind", "") if isinstance(obj, dict) else ""


# ---- 브라우저 로그인(앱 없는 대체 경로) — RFC 8252 loopback + PKCE S256 + state -----------------
LOOPBACK_HOST = "127.0.0.1"     # localhost 이름 해석에 기대지 않는다(RFC 8252 §8.3)
LOOPBACK_PATH = "/cb"
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_ERROR_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def pkce_pair():
    """(verifier, challenge) — verifier = 32바이트 무작위 base64url(43자), challenge = base64url(SHA-256(verifier))."""
    verifier = _b64url(secrets.token_bytes(32))
    return verifier, _b64url(hashlib.sha256(verifier.encode("ascii")).digest())


def new_state() -> str:
    return _b64url(secrets.token_bytes(16))      # 22자


class LoginError(RuntimeError):
    """브라우저 로그인 실패 — 종류만(code·verifier·state·토큰 없음)."""

    def __init__(self, kind: str, status: int | None = None, code: str = ""):
        self.kind, self.status, self.code = kind, status, code
        self.msg = self.action = ""         # 서버가 준 사람용 문장(토큰·코드 값 없음)
        super().__init__(kind + (f" http-{status}" if status else "") + (f" {code}" if code else ""))


_DONE_PAGE = ("<!doctype html><meta charset=utf-8><title>MyCRM</title>"
              "<p>로그인을 받았어요. 이 창을 닫고 터미널로 돌아가세요.</p>").encode("utf-8")
_BAD_PAGE = ("<!doctype html><meta charset=utf-8><title>MyCRM</title>"
             "<p>이 요청은 받지 않았어요. 터미널에서 다시 시작하세요.</p>").encode("utf-8")


class LoopbackReceiver:
    """127.0.0.1 임의 포트에서 `/cb?code&state` 를 한 번 받는다. state 가 다르거나 code 형식이 틀리면 거절하고 계속 기다린다.
    요청 줄은 로그에 남기지 않는다(code·state 가 들어 있다)."""

    def __init__(self, expected_state: str):
        import http.server
        import threading
        outer = self
        self._expected = expected_state
        self._event = threading.Event()
        self._code = None
        self._error = None

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                return

            def do_GET(self):
                parts = urllib.parse.urlsplit(self.path)
                q = urllib.parse.parse_qs(parts.query, keep_blank_values=True)
                code = (q.get("code") or [""])[0]
                state = (q.get("state") or [""])[0]
                err = (q.get("error") or [""])[0]
                state_ok = secrets.compare_digest(state.encode(), outer._expected.encode())
                if (parts.path == LOOPBACK_PATH and err and not code and state_ok and not outer._event.is_set()
                        and _ERROR_RE.match(err)):
                    # 서버가 로그인 거절·취소를 알려 왔다 — 5분 기다리지 않고 바로 멈춘다
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(_BAD_PAGE)))
                    self.end_headers()
                    self.wfile.write(_BAD_PAGE)
                    outer._error = err
                    outer._event.set()
                    return
                ok = (parts.path == LOOPBACK_PATH and len(q.get("code") or []) == 1 and _CODE_RE.match(code)
                      and secrets.compare_digest(state.encode(), outer._expected.encode()) and not outer._event.is_set())
                body = _DONE_PAGE if ok else _BAD_PAGE
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                if ok:
                    outer._code = code
                    outer._event.set()

        self._httpd = http.server.HTTPServer((LOOPBACK_HOST, 0), H)
        self.port = self._httpd.server_address[1]
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
        self._thread.start()

    @property
    def redirect_uri(self) -> str:
        return f"http://{LOOPBACK_HOST}:{self.port}{LOOPBACK_PATH}"

    def wait(self, timeout: float) -> str:
        """받은 code. 시간 안에 못 받으면 LoginError("timeout")."""
        try:
            if not self._event.wait(timeout):
                raise LoginError("timeout")
            if self._error:
                raise LoginError("denied", code=self._error)
            return self._code
        finally:
            self.close()

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()


DESKTOP_LOGIN_PATH = "/desktop/login"
CLI_CLAIM_PATH = "/desktop/cli/claim"
LOGIN_TIMEOUT = 300.0            # 브라우저 로그인 기다림(초)
_CLIENT_NAME_BAD = re.compile(r"[\x00-\x1f\x7f]")


def default_client_name() -> str:
    """서버 연결 장치 이름 기본값 — 이 PC 의 호스트 이름(한 줄, 1~80자)."""
    import socket
    try:
        name = _CLIENT_NAME_BAD.sub("", socket.gethostname() or "").strip()
    except OSError:
        name = ""
    return (name or "my-crm-agent")[:80]


def browser_login(server_url: str, scope: str, *, client_name: str | None = None, open_browser=None, say=print,
                  timeout: float = LOGIN_TIMEOUT, opener=None) -> dict:
    """RFC 8252 loopback 로그인 → POST /desktop/cli/claim → {scope, token, …}. 토큰은 반환값에만 있다(출력·로그 없음).
    open_browser(url) 는 시스템 브라우저를 연다(시험은 가짜). 실패는 LoginError(kind: timeout·network·server·bad-response)."""
    if scope not in ("device", "migration"):
        raise ValueError("scope")
    if open_browser is None:
        import webbrowser
        open_browser = webbrowser.open
    base = server_url.rstrip("/")
    verifier, challenge = pkce_pair()
    state = new_state()
    try:
        rx = LoopbackReceiver(state)
    except OSError:
        raise LoginError("loopback") from None
    try:
        url = base + DESKTOP_LOGIN_PATH + "?" + urllib.parse.urlencode(
            {"challenge": challenge, "state": state, "redirect_uri": rx.redirect_uri})
        say("브라우저에서 로그인하세요. 브라우저가 안 열리면 이 PC 의 브라우저로 다음 주소를 여세요:")
        say("  " + url)
        try:
            open_browser(url)
        except Exception:
            pass                       # 주소를 보여 줬으니 손으로 열 수 있다
        code = rx.wait(timeout)
    finally:
        rx.close()
    form = {"code": code, "verifier": verifier, "state": state, "scope": scope}
    if scope == "device":
        form["client_name"] = client_name or default_client_name()
    req = urllib.request.Request(base + CLI_CLAIM_PATH, data=urllib.parse.urlencode(form).encode("ascii"),
                                 method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        try:
            resp = (opener or _opener()).open(req, timeout=30)
            status, data = resp.status, resp.read(MAX_RESPONSE_BYTES)
            resp.close()
        except urllib.error.HTTPError as e:
            status = e.code
            try:
                data = e.read(MAX_RESPONSE_BYTES)
            except Exception:
                data = b""
            e.close()
    except (urllib.error.URLError, OSError, TimeoutError):
        raise LoginError("network") from None
    try:
        payload = json.loads(data.decode("utf-8")) if data else {}
    except (UnicodeDecodeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if status != 200:
        err = LoginError("server", status, payload.get("code") if isinstance(payload.get("code"), str) else "")
        err.msg = payload.get("msg") if isinstance(payload.get("msg"), str) else ""
        err.action = payload.get("action") if isinstance(payload.get("action"), str) else ""
        raise err
    if payload.get("scope") != scope or not isinstance(payload.get("token"), str):
        raise LoginError("bad-response")
    return payload


# 서버 계약 v3 — loopback 로그인 실패 때 /cb?error=<코드>&state
_LOGIN_ERRORS = {
    "access_denied": "브라우저에서 로그인을 거절·취소했어요",
    "login_failed": "로그인에 실패했어요",
    "login_expired": "로그인 절차가 만료됐어요(10분 넘김·다른 탭)",
    "account_unavailable": "이 계정은 지금 연결할 수 없어요 — 운영자에게 문의하세요",
    "server_error": "서버가 로그인 코드를 만들지 못했어요",
}


def explain_login_error(e: LoginError) -> list:
    """브라우저 로그인 실패 → 사람이 읽는 줄들(값 없음)."""
    if e.kind == "timeout":
        return [f"{int(LOGIN_TIMEOUT // 60)}분 안에 브라우저 로그인을 받지 못했어요. 브라우저에서 로그인을 마치지 못했으면 다시 실행하세요."]
    if e.kind == "denied":
        why = _LOGIN_ERRORS.get(e.code, "브라우저 로그인이 끝나지 않았어요")
        return [f"{why}({e.code}). 다시 실행하세요."]
    if e.kind == "network":
        return ["서버에 닿지 못했어요. 주소·네트워크를 확인하세요."]
    if e.kind == "loopback":
        return ["127.0.0.1 에서 로그인을 기다릴 포트를 열지 못했어요. 원격 셸이면 웹에서 토큰을 발급해 --token-stdin 으로 넣으세요."]
    if e.kind == "bad-response":
        return ["서버 응답 모양이 맞지 않아요. 아무것도 저장하지 않았어요."]
    out = [f"서버가 받지 않았어요(http-{e.status}" + (f" {e.code}" if e.code else "") + ")" + (f": {e.msg}" if e.msg else "")]
    if e.action:
        out.append("  " + e.action)
    if e.code == "HANDOFF-INVALID":
        out.append("  로그인 코드가 만료됐거나 맞지 않아요(2분·한 번만). 명령을 다시 실행해 로그인부터 하세요.")
    elif e.code in ("NAME-REQUIRED", "MIGRATION-OFF", "MIGRATION-NOT-ALLOWED"):
        out.append("  조치한 뒤 명령을 다시 실행하세요(로그인 코드는 이미 쓰였어요).")
    return out
