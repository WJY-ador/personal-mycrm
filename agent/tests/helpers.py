"""시험 도우미 — 전부 합성 자료. 실제 Keychain·launchd·서버를 쓰지 않는다."""
from __future__ import annotations

import base64
import hashlib
import io
import json
import re
import urllib.parse
import os
import secrets
import shutil
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import config as _config
from agent import keystore

STREAM_ID = "is_5a5a5a5a5a5a5a5a5a5a5a5a"
TOKEN = "imp_" + STREAM_ID + ".tok_Synth01." + "S" * 43
NAMESPACE = "hn_SynthSpace01"


class MemoryKeyStore(keystore.KeyStore):
    """시험 전용 — 메모리에만 둔다(제품 코드에 평문 대체는 없다)."""

    def __init__(self, service="my-crm-agent"):
        self.service = service
        self.items = {}

    def get(self, account):
        return self.items.get(account)

    def set(self, account, secret):
        self.items[account] = secret

    def delete(self, account):
        return self.items.pop(account, None) is not None


class FailingKeyStore(keystore.KeyStore):
    def get(self, account):
        raise keystore.KeyStoreError("denied")

    def set(self, account, secret):
        raise keystore.KeyStoreError("denied")

    def delete(self, account):
        raise keystore.KeyStoreError("denied")


class TempHome:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="mcrm-agent-test-")
        self.home = os.path.join(self.root, "home")
        self.paths = _config.Paths(self.home).ensure()

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


def synth_row(i: int, **over) -> dict:
    row = {
        "id": f"SYNPOST{i:04d}",
        "author": f"synth_author_{i % 3}",
        "text": f"SYNTHETIC-BODY-{i} 다른 사람이 쓴 합성 본문",
        "posted_at": "2026-09-30T01:02:03.000Z",
        "original_url": f"https://example.invalid/@synth_author_{i % 3}/post/SYNPOST{i:04d}",
        "first_seen": "2026-10-01",
        "seed": False,
        "kind": "kindA",
        "source": "synth_src",
        "topic": f"SYNTOPIC{i}",
    }
    row.update(over)
    return row


def write_jsonl(path: str, rows) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(r if isinstance(r, str) else json.dumps(r, ensure_ascii=False))
            f.write("\n")


def connected_config(th: TempHome, server_url: str, likes_path: str | None = None, **likes_over) -> dict:
    cfg = _config.default_config()
    cfg.update({"server_url": server_url, "source_instance_id": STREAM_ID, "device_label": "synthetic",
                "hmac_namespace": NAMESPACE, "policy_revision": 1, "allowed_axes": []})
    cfg["upload"]["min_interval_sec"] = 0
    if likes_path:
        cfg["adapters"]["likes"].update({"enabled": True, "input_path": likes_path, "provider_code": "synthnet",
                                         "include_kinds": ["kindA"]})
        cfg["adapters"]["likes"].update(likes_over)
    _config.save(th.paths, cfg)
    return cfg


def keystore_with_secrets() -> MemoryKeyStore:
    ks = MemoryKeyStore()
    ks.set(_config.token_account(STREAM_ID), TOKEN)
    ks.set(_config.hmac_account(NAMESPACE), secrets.token_hex(32))
    return ks


# ---- 가짜 /api/imports 서버 -------------------------------------------------------
class FakeImportServer:
    """r3 T2 의 HTTP 계약을 흉내 낸다. 멱등: 같은 키·같은 본문 200, 다른 본문 409."""

    def __init__(self, token=TOKEN):
        self.token = token
        self.requests = []          # (headers dict, body bytes)
        self.by_key = {}            # key -> (body, response dict)
        self.script = []            # 앞에서부터 꺼내 쓰는 강제 응답: (status, dict) | "drop"
        self.lock = threading.Lock()
        self.revoked = False
        self.pending = None         # rotate 로 내준 새 토큰(M2: 첫 사용 전까지 옛 토큰도 유효, 1개만)
        self.rotations = 0
        self.rotate_script = []     # rotate 강제 응답: (status, dict) | "drop"(발급은 했는데 응답 유실)
        self.rotated_expires_at = "2027-04-18T00:00:00+09:00"
        self.device_calls = []      # (method, path)
        self.handoffs = {}          # 브라우저 로그인 코드 → {challenge, state, used}
        self.login_requests = []    # /desktop/login 쿼리(dict)
        self.claim_requests = []    # /desktop/cli/claim (헤더 dict, 폼 dict) — 메모리에만
        self.claim_script = []      # claim 강제 응답 (status, dict)
        self.migration_token = None
        self.device_script = []     # 장치 경로 강제 응답
        self.decisions = []         # 웹 판별 목록(서버 순서). 커서 = 다음 위치의 문자열
        self.decisions_page = 100
        self.decisions_script = []  # 판별 목록 강제 응답 (status, dict)
        self.decision_calls = []    # 받은 since 값(None = 없음)
        self.items = {}             # 수집 글 original_id → 서버 항목 ID(접수 응답 target_id)
        self.device_info = {"stream_id": STREAM_ID, "label": "synthetic-device",
                            "policy": {"actions": ["like"],
                                       "transform_versions": ["board-likes/1", "self-text/1", "self-summary/1"],
                                       "axes": []},
                            "policy_revision": 1, "hmac_namespace": NAMESPACE,
                            "token_expires_at": "2027-01-18T00:00:00+09:00"}
        outer = self

        class H(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                return

            def _auth_ok(self):
                with outer.lock:
                    if outer.pending and self.headers.get("Authorization") == "Bearer " + outer.pending:
                        # M2 — 새 토큰 첫 사용: 이때 옛 토큰이 무효가 된다
                        outer.token, outer.pending = outer.pending, None
                        outer.device_info = dict(outer.device_info, token_expires_at=outer.rotated_expires_at)
                if outer.revoked and self.headers.get("Authorization") == "Bearer " + outer.token:
                    self._json(401, {"code": "TOKEN-REVOKED", "msg": "revoked"})
                    return False
                if self.headers.get("Authorization") != "Bearer " + outer.token:
                    self._json(401, {"code": "AUTH-INVALID", "msg": "bad"})
                    return False
                return True

            def _device(self, method):
                with outer.lock:
                    outer.device_calls.append((method, self.path))
                    forced = outer.device_script.pop(0) if outer.device_script else None
                if forced is not None:
                    return self._json(*forced)
                if not self._auth_ok():
                    return
                if method == "GET":
                    return self._json(200, outer.device_info)
                outer.revoked = True
                return self._json(200, {"stream_id": outer.device_info["stream_id"], "revoked": True})

            def _rotate(self):
                with outer.lock:
                    outer.device_calls.append(("POST", self.path))
                    forced = outer.rotate_script.pop(0) if outer.rotate_script else None
                if forced is not None and forced != "drop":
                    return self._json(*forced)
                if not self._auth_ok():
                    return
                with outer.lock:
                    outer.rotations += 1
                    new = "imp_" + outer.device_info["stream_id"] + f".tok_Rot{outer.rotations:02d}." + secrets.token_urlsafe(32)
                    outer.pending = new           # 다음 교체가 덮어쓴다
                if forced == "drop":
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                return self._json(200, {"stream_id": outer.device_info["stream_id"], "token": new,
                                        "token_expires_at": outer.rotated_expires_at})

            def _desktop_login(self):
                q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.path).query))
                with outer.lock:
                    outer.login_requests.append(q)
                ok = (re.match(r"^[A-Za-z0-9_-]{43}$", q.get("challenge", ""))
                      and re.match(r"^[A-Za-z0-9_-]{16,64}$", q.get("state", ""))
                      and re.match(r"^http://127\.0\.0\.1:\d{4,5}/cb$", q.get("redirect_uri", "")))
                if not ok:
                    return self._json(400, {"code": "ARG-INVALID"})
                code = secrets.token_urlsafe(32)
                with outer.lock:
                    outer.handoffs[code] = {"challenge": q["challenge"], "state": q["state"], "used": False}
                loc = q["redirect_uri"] + "?" + urllib.parse.urlencode({"code": code, "state": q["state"]})
                self.send_response(302)
                self.send_header("Location", loc)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def _cli_claim(self, body):
                form = dict(urllib.parse.parse_qsl(body.decode("ascii")))
                hdrs = {k: v for k, v in self.headers.items()}
                with outer.lock:
                    outer.claim_requests.append((hdrs, form))
                    forced = outer.claim_script.pop(0) if outer.claim_script else None
                    h = outer.handoffs.get(form.get("code", ""))
                    good = (h is not None and not h["used"] and h["state"] == form.get("state")
                            and base64.urlsafe_b64encode(hashlib.sha256(form.get("verifier", "").encode()).digest())
                            .rstrip(b"=").decode() == h["challenge"])
                    if h is not None:
                        h["used"] = True
                if forced is not None:
                    return self._json(*forced)
                if "Origin" in hdrs:
                    return self._json(403, {"code": "ORIGIN"})
                if not good:
                    return self._json(400, {"code": "HANDOFF-INVALID", "msg": "다시 로그인해 주세요"})
                scope = form.get("scope")
                if scope == "device":
                    if not 1 <= len(form.get("client_name", "")) <= 80:
                        return self._json(400, {"code": "ARG-INVALID"})
                    tok = "imp_" + outer.device_info["stream_id"] + ".tok_Brw01." + secrets.token_urlsafe(32)
                    with outer.lock:
                        outer.token, outer.revoked = tok, False
                        outer.device_info = dict(outer.device_info, label=form["client_name"])
                    return self._json(200, {"scope": "device", "token": tok, "stream_id": outer.device_info["stream_id"],
                                            "token_expires_at": outer.device_info["token_expires_at"],
                                            "account_label": "synth@example.invalid"})
                if scope == "migration":
                    tok = "mig_mt_" + secrets.token_hex(8) + "." + secrets.token_urlsafe(32)
                    outer.migration_token = tok
                    return self._json(200, {"scope": "migration", "token": tok, "token_id": "mt_" + secrets.token_hex(8),
                                            "expires_at": "2026-11-16T00:00:00+09:00",
                                            "account_label": "synth@example.invalid"})
                return self._json(400, {"code": "ARG-INVALID"})

            def _decisions(self):
                from agent.uploader import DECISIONS_PATH
                u = urllib.parse.urlsplit(self.path)
                if u.path != DECISIONS_PATH:
                    return self._json(404, {"code": "NOT-FOUND"})
                since = dict(urllib.parse.parse_qsl(u.query)).get("since")
                with outer.lock:
                    outer.decision_calls.append(since)
                    forced = outer.decisions_script.pop(0) if outer.decisions_script else None
                if forced is not None:
                    return self._json(*forced)
                if not self._auth_ok():
                    return
                start = int(since or 0)
                page = outer.decisions[start:start + outer.decisions_page]
                return self._json(200, {"decisions": page, "next_cursor": str(start + len(page))})

            def do_GET(self):
                if self.path.startswith("/api/imports/decisions"):
                    return self._decisions()
                if self.path.startswith("/desktop/login?"):
                    return self._desktop_login()
                if self.path == "/api/imports/device":
                    return self._device("GET")
                return self._json(404, {"code": "NOT-FOUND"})

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(n)
                if self.path == "/api/imports/device/revoke":
                    return self._device("POST")
                if self.path == "/api/device/rotate":
                    return self._rotate()
                if self.path == "/desktop/cli/claim":
                    return self._cli_claim(body)
                hdrs = {k: v for k, v in self.headers.items()}
                with outer.lock:
                    outer.requests.append((hdrs, body))
                    forced = outer.script.pop(0) if outer.script else None
                if self.path != "/api/imports":
                    return self._json(404, {"code": "NOT-FOUND"})
                if not self._auth_ok():
                    return
                key = self.headers.get("Idempotency-Key")
                if forced is not None and forced != "drop" and forced != "drop-after-apply":
                    st, payload = forced
                    return self._json(st, payload)
                with outer.lock:
                    prev = outer.by_key.get(key)
                    if prev is not None:
                        if prev[0] != body:
                            res = (409, {"code": "IDEMPOTENCY-CONFLICT"})
                        else:
                            res = (200, dict(prev[1], duplicate=True))
                    else:
                        obj = json.loads(body)
                        resp = {"import_id": "ie_" + secrets.token_hex(6),
                                "state": "applied" if obj["kind"] == "activity" else "pending",
                                "target_kind": "activity" if obj["kind"] == "activity" else "record",
                                "target_id": ("a_" + secrets.token_hex(6)) if obj["kind"] == "activity" else None,
                                "duplicate": False, "received_at": "2026-10-20T00:00:00+09:00",
                                "expires_at": None}
                        if obj["kind"] == "collected_post":   # 서버 _target: 수집 글 = 항목(원본 하나 = 항목 하나)
                            iid = outer.items.setdefault(obj["original_id"], "i_" + secrets.token_hex(8))
                            resp.update({"state": "applied", "target_kind": "item", "target_id": iid})
                        outer.by_key[key] = (body, resp)
                        res = (201, resp)
                if forced in ("drop", "drop-after-apply"):
                    # 서버는 처리했지만 응답이 유실된 상황
                    self.close_connection = True
                    try:
                        self.connection.shutdown(2)
                    except OSError:
                        pass
                    return
                return self._json(*res)

            def _json(self, status, payload):
                data = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def bodies(self):
        return [b for _, b in self.requests]


def run_cli(argv, **kw):
    from agent import cli
    out = io.StringIO()
    code = cli.main(argv, out=out, **kw)
    return code, out.getvalue()


def fake_browser(log=None):
    """가짜 시스템 브라우저 — 주소를 열고 리다이렉트를 따라간다(서버 /desktop/login → 302 → 127.0.0.1 /cb)."""
    import urllib.request

    def open_url(url):
        if log is not None:
            log.append(url)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 환경 프록시를 타지 않게
        with opener.open(url, timeout=10) as r:
            r.read()
        return True
    return open_url
